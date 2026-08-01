"""The design-kit registry: keys in, assets out.

Rewritten around `kit-registry.json`. The old index walked the filesystem and
read a manifest that had been written by the exporter; this one reads the
registry and nothing else, which is the whole point — a file with no entry does
not exist, and a name with two spellings resolves to one drawing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.kit import Kit, KitError, load_kit

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"


def kit() -> Kit:
    return load_kit(ASSETS)


# --------------------------------------------------------------------------
# The index.
# --------------------------------------------------------------------------


def test_the_registry_is_the_index():
    k = kit()
    assert len(k) >= 384, "the delivery's 384 assets, plus the blank layouts"
    assert "mascot/deadpan" in k
    assert "shorts/dennis-vs-numbers/numbers-raining" in k
    assert "blanks/term-card-blank" in k


def test_every_registered_key_still_points_at_a_real_file():
    """A registry that has drifted from disk degrades silently: every beat
    using the moved artwork falls back and nothing says so."""
    k = kit()
    missing = [key for key in k.keys() if k.path(key) is None]
    assert not missing, f"{len(missing)} keys have no file: {missing[:10]}"


def test_the_kit_on_disk_verifies_both_ways():
    """A missing frame AND a PNG with no entry — the second is the shape that
    let twenty contact sheets become addressable assets."""
    assert kit().verify() == []


def test_a_missing_key_is_none_not_an_error():
    k = kit()
    assert k.path("blanks/does-not-exist") is None
    assert "nope" not in k


def test_a_missing_kit_degrades_quietly(tmp_path):
    empty = Kit(tmp_path / "kit")
    assert len(empty) == 0
    assert empty.path("anything") is None
    assert empty.family("mascot") == ()
    assert empty.pick("mascot", "seed") is None
    assert empty.boil("mascot/deadpan") == []


def test_require_raises_rather_than_degrading():
    """The SHORT engine calls this. A beat that silently becomes a backdrop is
    how a render shipped looking wrong with every test green."""
    k = kit()
    with pytest.raises(KitError) as err:
        k.require("type/callouts/term-roic", why="the TERM beat")
    assert "the TERM beat" in str(err.value)
    assert "kit doctor" in str(err.value)
    assert k.require("mascot/deadpan").key == "mascot/deadpan"


# --------------------------------------------------------------------------
# Resolution.
# --------------------------------------------------------------------------


def test_tags_resolve_through_the_family_prefix():
    k = kit()
    assert k.resolve("props", "podium-ceo").name == "podium-ceo.png"
    assert k.resolve_asset("blanks", "term-card-blank").key == "blanks/term-card-blank"
    assert k.resolve("props", "not-a-thing") is None


def test_resolve_normalises_the_key():
    k = kit()
    assert k.resolve("props", "  PODIUM-CEO  ") == k.resolve("props", "podium-ceo")
    assert k.resolve("props", "podium_ceo") == k.resolve("props", "podium-ceo")


def test_resolve_strips_a_multi_segment_naming_prefix():
    """`[BIGNUM: buyback]` has to reach `big-number-buyback`.

    Stripping only the first hyphen segment left `number-buyback`, so the key
    resolved to nothing and the beat quietly degraded — while the kit had the
    artwork all along.
    """
    k = kit()
    assert k.resolve_asset("blanks", "blank").key == "blanks/big-number-blank"
    assert k.resolve_asset("shorts/dennis-vs-numbers", "raining").key == \
        "shorts/dennis-vs-numbers/numbers-raining"


def test_resolve_searches_several_families():
    """One tag's artwork lives across more than one folder now; a tag pinned
    to a single hardcoded folder is how most of the library stayed
    unreachable."""
    k = kit()
    families = ("blanks", "props", "concepts")
    assert k.resolve_asset(families, "podium-ceo").key == "props/podium-ceo"
    assert k.resolve_asset(families, "risk-iceberg").key == "concepts/risk-iceberg"


def test_resolve_still_refuses_a_key_that_is_not_there():
    k = kit()
    assert k.resolve("blanks", "not-a-real-card") is None
    assert k.resolve("props", "spaceship") is None


# --------------------------------------------------------------------------
# Aliases and twins.
# --------------------------------------------------------------------------


def test_an_alias_resolves_to_its_canonical_drawing():
    k = kit()
    assert k.get("restyled/reactions/deadpan").key == "mascot/deadpan"
    assert k.canonical("restyled/poses/shrug-idk-man") == "mascot/shrug"


def test_families_offer_only_things_that_are_actually_different():
    """Aliases and `-talk` twins are the same drawing under a second name.
    Offering them separately is what let "pick a different reaction" return
    the identical frame — 25 fake reactions where there are 10."""
    k = kit()
    assert k.family("restyled/reactions") == (), "all nine are aliases of mascot/"
    cold_open = k.family("chapters/cold-open")
    assert cold_open
    assert not any(n.endswith("-talk") for n in cold_open)
    # …but a twin is still reachable as a pair
    pair = k.talk_pair("chapters/cold-open/at-desk-open")
    assert pair is not None and pair[0].key != pair[1].key


def test_a_boil_pair_is_reachable_as_frames():
    k = kit()
    frames = k.boil("chapters/bull-vs-bear/dennis-both-hands")
    assert len(frames) == 2 and frames[1].stem.endswith("_b")


# --------------------------------------------------------------------------
# Registry facts.
# --------------------------------------------------------------------------


def test_playback_and_geometry_come_from_the_registry():
    k = kit()
    rain = k.get("shorts/dennis-vs-numbers/numbers-raining")
    assert (rain.playback, rain.frame_count, rain.fps) == ("loop", 6, 12)
    assert rain.canvas == (1080, 1080) and rain.export_scale == 2
    assert rain.pixel_size == (2160, 2160)

    boil = k.get("chapters/bull-vs-bear/dennis-both-hands")
    assert boil.playback == "boil" and boil.frame_count == 2

    still = k.get("blanks/term-card-blank")
    assert still.playback == "static" and not still.animated
    assert k.has_alpha("mascot/deadpan")
    assert not k.has_alpha("blanks/term-card-blank")


def test_slot_boxes_are_canvas_coords_and_scale_to_the_export():
    """The silent trap: get this wrong and every number sits at exactly half
    its intended position on a drawing that still looks fine."""
    k = kit()
    slot = k.get("shorts/dennis-vs-numbers/sit-on-number").slots[0]
    assert (slot.x, slot.y, slot.w, slot.h) == (244, 478, 592, 334)
    assert slot.scaled(2) == (488, 956, 1184, 668)
    assert slot.scaled(1) == (244, 478, 592, 334)


def test_the_rain_slots_fall_with_the_drops():
    """`slotFrameDelta`: ignore it and the figures hang in the air while the
    rain animates past them."""
    k = kit()
    rain = k.get("shorts/dennis-vs-numbers/numbers-raining")
    delta, slot = rain.slot_frame_delta, rain.slots[0]
    assert delta is not None
    assert delta.at(slot, 0) == (slot.x, slot.y)
    for i in range(1, rain.frame_count):
        assert delta.at(slot, i)[1] > delta.at(slot, i - 1)[1]
    # the whole cycle moves about one drop-height, not six
    travel = delta.at(slot, rain.frame_count - 1)[1] - slot.y
    assert 90 < travel < 110, f"the rain travelled {travel} canvas px per cycle"


def test_the_dead_mouth_flap_is_recorded_rather_than_silent():
    """The twin is byte-identical to its base, so flapping it animates
    nothing. Recorded as artwork owed rather than left as a silent no-op —
    and read off the raw entries, because `get()` follows the alias to the
    base and would report nothing at all."""
    k = kit()
    assert "chapters/management/dennis-reads-proxy-talk" in k.dead_mouth_flaps()
    assert k.talk_pair("chapters/management/dennis-reads-proxy") is None


# ------------------------------------------- cross-video variant memory


def test_the_ledger_spreads_picks_across_consecutive_uploads(tmp_path):
    """A seed alone stops repeats WITHIN a video. Nothing stopped two
    consecutive uploads opening on the same layout — which is what makes a
    daily channel look stale."""
    from pipeline.kit import VariantLedger

    k = kit()
    family_size = len(k.family("concepts"))
    ledger = VariantLedger(tmp_path / "v.json", keep=family_size)
    picks = [k.pick("concepts", "identical-seed", ledger=ledger).stem
             for _ in range(family_size)]
    assert len(set(picks)) == family_size, "every option before any repeat"


def test_without_a_ledger_the_pick_is_still_stable(tmp_path):
    k = kit()
    assert k.pick("concepts", "seed-x") == k.pick("concepts", "seed-x")


def test_the_ledger_round_trips_through_disk(tmp_path):
    from pipeline.kit import VariantLedger

    k = kit()
    path = tmp_path / "v.json"
    first = VariantLedger(path)
    used = k.pick("concepts", "s", ledger=first)
    first.save()

    reloaded = VariantLedger(path)
    assert any(r.endswith(used.stem) for r in reloaded.recent("concepts"))
    # the freshly-loaded ledger keeps steering away from it
    assert k.pick("concepts", "s", ledger=reloaded) != used


def test_the_ledger_reports_everything_it_has_seen():
    """What the kit doctor diffs the library against."""
    from pipeline.kit import VariantLedger

    ledger = VariantLedger(Path("/nonexistent/v.json"))
    ledger.record("concepts", "concepts/dont-swing")
    ledger.record("mascot", "mascot/deadpan")
    assert ledger.all_used() == {"concepts/dont-swing", "mascot/deadpan"}


def test_a_corrupt_ledger_is_treated_as_no_history(tmp_path):
    from pipeline.kit import VariantLedger

    bad = tmp_path / "v.json"
    bad.write_text("{not json", encoding="utf-8")
    assert VariantLedger(bad).recent("anything") == []


def test_a_family_smaller_than_the_window_still_returns_something(tmp_path):
    from pipeline.kit import VariantLedger

    k = kit()
    ledger = VariantLedger(tmp_path / "v.json", keep=50)
    for _ in range(30):
        assert k.pick("concepts", "s", ledger=ledger) is not None
