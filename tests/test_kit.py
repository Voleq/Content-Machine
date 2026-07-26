"""The design-kit registry: names in, paths out."""

from __future__ import annotations

from pathlib import Path

from pipeline.kit import Kit, load_kit

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"


def kit() -> Kit:
    return load_kit(ASSETS)


def test_the_exported_kit_is_indexed():
    k = kit()
    assert len(k) > 700, "Part 0's export should be on disk"
    assert "mascot/host/look-left-talk-open" in k
    assert "type/callouts/term-roic" in k


def test_every_indexed_name_still_points_at_a_real_file():
    """`Kit.path()` returns None for a file that is not there, so a manifest
    that has drifted from disk degrades silently — every beat using the moved
    artwork quietly falls back. Renaming a family (`restyle/con/` →
    `restyle/concepts/`, which Windows cannot check out) has to move both."""
    k = kit()
    missing = [name for name in k._assets if k.path(name) is None]
    assert not missing, f"{len(missing)} manifest names have no file: {missing[:10]}"


def test_a_missing_name_is_none_not_an_error():
    k = kit()
    assert k.path("type/callouts/does-not-exist") is None
    assert "nope" not in k


def test_a_missing_kit_degrades_quietly(tmp_path):
    empty = Kit(tmp_path / "kit")
    assert len(empty) == 0
    assert empty.path("anything") is None
    assert empty.family("type/callouts") == ()
    assert empty.pick("type/callouts", "seed") is None
    assert empty.sequence("stings/logo-in") == []


def test_tags_resolve_through_the_family_prefix():
    """[PROP: laptop] finds props/objects/obj-laptop without the author
    knowing the kit's internal naming."""
    k = kit()
    assert k.resolve("props/objects", "laptop").name == "obj-laptop.png"
    assert k.resolve("type/callouts", "roic").name == "term-roic.png"
    assert k.resolve("type/tables", "pl-plain").name == "pl-plain.png"
    assert k.resolve("props/objects", "not-a-thing") is None


def test_resolve_normalises_the_key():
    k = kit()
    assert k.resolve("props/objects", "  LAPTOP  ") == k.resolve("props/objects", "laptop")
    assert k.resolve("props/objects", "obj_laptop") == k.resolve("props/objects", "laptop")


def test_resolve_strips_a_multi_segment_naming_prefix():
    """`[BIGNUM: buyback]` has to reach `big-number-buyback`.

    Stripping only the first hyphen segment left `number-buyback`, so the key
    resolved to nothing and the beat quietly degraded to a plain backdrop —
    while the kit had the artwork all along.
    """
    k = kit()
    assert k.resolve("type/callouts", "buyback") is not None
    assert k.resolve("type/callouts", "big-number-buyback") == \
        k.resolve("type/callouts", "buyback")
    assert k.resolve("type/callouts", "share-count") is not None
    # single-segment prefixes still work
    assert k.resolve("type/callouts", "roic") is not None


def test_resolve_still_refuses_a_key_that_is_not_there():
    """Looser prefix matching must not start inventing matches."""
    k = kit()
    assert k.resolve("type/callouts", "not-a-real-card") is None
    assert k.resolve("props/objects", "spaceship") is None


def test_families_exclude_boil_twins():
    k = kit()
    objects = k.family("props/objects")
    assert objects, "the objects family shipped"
    assert not any(n.endswith("_b") for n in objects), "_b frames are alternates"
    # …but they are reachable as a pair
    pair = k.boil(objects[0])
    assert len(pair) == 2 and pair[1].stem.endswith("_b")


def test_picking_from_a_family_is_deterministic_and_spreads():
    k = kit()
    assert k.pick("mascot/reactions", "EXMPL") == k.pick("mascot/reactions", "EXMPL")
    picked = {k.pick("mascot/reactions", f"s{i}") for i in range(200)}
    assert len(picked) == len(k.family("mascot/reactions"))


def test_stings_are_ordered_frame_sequences():
    k = kit()
    names = k.sequences("stings")
    assert "logo-in" in names and len(names) >= 10
    frames = k.sequence("stings/logo-in")
    assert [p.stem for p in frames] == [f"f0{i}" for i in range(1, 7)]


def test_bumpers_ship_as_in_hold_out_stills():
    """Unlike the stings, the bumper document exports one frame per state —
    its marker's '6 frames each' describes what the edit interpolates, not
    what shipped. The three states are addressed by name."""
    k = kit()
    for state in ("in", "hold", "out"):
        assert f"type/bumpers/paper/{state}" in k


def test_sizes_come_from_the_manifest():
    k = kit()
    assert k.size("type/callouts/term-roic") == (1920, 1080)
    assert k.size("thumbs/crash") == (1280, 720)
    assert k.has_alpha("mascot/host/look-left-talk-open")
    assert not k.has_alpha("type/callouts/term-roic")


# ------------------------------------------- cross-video variant memory


def test_the_ledger_spreads_picks_across_consecutive_uploads(tmp_path):
    """A seed alone stops repeats WITHIN a video. Nothing stopped two
    consecutive uploads opening on the same layout — which is what makes a
    daily channel look stale."""
    from pipeline.kit import VariantLedger

    k = kit()
    family_size = len(k.family("mascot/reactions"))
    ledger = VariantLedger(tmp_path / "v.json", keep=family_size)
    picks = [k.pick("mascot/reactions", "identical-seed", ledger=ledger).stem
             for _ in range(family_size)]
    assert len(set(picks)) == family_size, "every option before any repeat"


def test_without_a_ledger_the_pick_is_still_stable(tmp_path):
    k = kit()
    a = k.pick("mascot/reactions", "seed-x")
    b = k.pick("mascot/reactions", "seed-x")
    assert a == b


def test_the_ledger_round_trips_through_disk(tmp_path):
    from pipeline.kit import VariantLedger

    k = kit()
    path = tmp_path / "v.json"
    first = VariantLedger(path)
    used = k.pick("mascot/reactions", "s", ledger=first)
    first.save()

    reloaded = VariantLedger(path)
    assert any(r.endswith(used.stem) for r in reloaded.recent("mascot/reactions"))
    # the freshly-loaded ledger keeps steering away from it
    assert k.pick("mascot/reactions", "s", ledger=reloaded) != used


def test_a_corrupt_ledger_is_treated_as_no_history(tmp_path):
    from pipeline.kit import VariantLedger

    bad = tmp_path / "v.json"
    bad.write_text("{not json")
    assert VariantLedger(bad).recent("anything") == []


def test_a_family_smaller_than_the_window_still_returns_something(tmp_path):
    from pipeline.kit import VariantLedger

    k = kit()
    ledger = VariantLedger(tmp_path / "v.json", keep=50)
    for _ in range(30):
        assert k.pick("mascot/reactions", "s", ledger=ledger) is not None
