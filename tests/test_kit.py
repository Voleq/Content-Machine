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
