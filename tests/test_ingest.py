"""The kit ingest, and the four things it must refuse to let through.

A missing asset must never degrade silently into an empty box. That is the
whole job of this layer, and every test here is a way the kit can be wrong
that would otherwise only show up as a hole in a rendered frame.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from pipeline.kit_manifest import (LIGHT_REGISTER, REGISTERS, Entry, KitError,
                                   _parse_entries, load_kit, pick_register,
                                   verify_entries)

ROOT = Path(__file__).resolve().parents[1]


def _entry(tmp: Path, **over) -> dict:
    base = {
        "key": "thing--marker", "concept": "thing", "group": "C",
        "register": "marker",
        "canvas": {"w": 100, "h": 200}, "delivered": {"w": 200, "h": 400},
        "background": "transparent", "frames": 1, "fps": 0,
        "playback": "static", "files": ["thing.png"], "svg": ["thing.svg"],
        "dir": "assets/marker/", "svgDir": "assets/marker-svg/",
        "slots": [{"name": "interior", "x": 10, "y": 10, "w": 50, "h": 50}],
    }
    base.update(over)
    return base


def _write(tmp: Path, entries: list[dict], sizes: dict[str, tuple[int, int]] | None = None):
    (tmp / "assets").mkdir(parents=True, exist_ok=True)
    (tmp / "assets" / "manifest.json").write_text(
        json.dumps({"assets": entries, "registers": list(REGISTERS)}),
        encoding="utf-8")
    for e in entries:
        d = tmp / e["dir"]
        d.mkdir(parents=True, exist_ok=True)
        for f in e["files"]:
            size = (sizes or {}).get(f, (e["delivered"]["w"], e["delivered"]["h"]))
            Image.new("RGBA", size, (0, 0, 0, 0)).save(d / f)
    return tmp


# ---------------------------------------------------------------------------
# The real delivery
# ---------------------------------------------------------------------------

def test_the_installed_kit_verifies():
    kit = load_kit(ROOT, registers={"marker"})
    assert len(kit) == 476
    assert sum(e.frames for e in kit) == 1772


def test_every_register_is_present_and_light_is_delivered_once():
    kit = load_kit(ROOT, check_files=False)
    regs = {e.register for e in kit}
    assert set(REGISTERS) <= regs
    light = [e for e in kit if e.register == LIGHT_REGISTER]
    assert light and all(e.group == "M" for e in light)


def test_scale_is_read_per_entry_and_is_not_always_two():
    """The headline rule is 2x. Twenty-four entries are not, and they have slots.

    Compositing those against an assumed 2x puts every figure at double its
    intended position, on a drawing that still looks correct.
    """
    kit = load_kit(ROOT, check_files=False)
    scales = {e.scale for e in kit}
    assert (2.0, 2.0) in scales
    assert (1.0, 1.0) in scales, "the 1:1 entries vanished — re-check the ingest"
    one_to_one = [e for e in kit if e.scale == (1.0, 1.0)]
    assert any(e.slots for e in one_to_one), (
        "a 1:1 entry with slots is the whole reason scale is read per entry")


def test_playback_and_fps_come_from_the_entry():
    kit = load_kit(ROOT, check_files=False)
    by_playback = {}
    for e in kit:
        by_playback.setdefault(e.playback, set()).add(e.fps)
    assert by_playback["boil"] == {7}, "boil is 3 frames at 7fps"
    assert len(by_playback["loop"]) > 1, (
        "loops run at several rates; a hardcoded one would be wrong for most")


def test_every_slot_sits_inside_its_own_canvas():
    kit = load_kit(ROOT, check_files=False)
    for e in kit:
        for s in e.slots.values():
            assert 0 <= s.x and 0 <= s.y
            assert s.x + s.w <= e.canvas[0]
            assert s.y + s.h <= e.canvas[1]


def test_a_slot_reaches_pixels_only_through_its_entrys_scale():
    kit = load_kit(ROOT, check_files=False)
    e = kit.concept("sheet-tall", "marker")
    x, y, w, h = e.slot_px("row-1")
    raw = e.slots["row-1"]
    sx, sy = e.scale
    assert (x, y, w, h) == (round(raw.x * sx), round(raw.y * sy),
                            round(raw.w * sx), round(raw.h * sy))


def test_asking_for_a_slot_that_does_not_exist_says_which_ones_do():
    kit = load_kit(ROOT, check_files=False)
    e = kit.concept("sheet-tall", "marker")
    with pytest.raises(KitError, match="row-1"):
        e.slot_px("row-99")


# ---------------------------------------------------------------------------
# The four refusals
# ---------------------------------------------------------------------------

def test_a_missing_frame_fails_the_load(tmp_path):
    _write(tmp_path, [_entry(tmp_path)])
    (tmp_path / "assets" / "marker" / "thing.png").unlink()
    with pytest.raises(KitError, match="missing frame"):
        load_kit(tmp_path, registers={"marker"})


def test_a_frame_at_the_wrong_size_fails_the_load(tmp_path):
    _write(tmp_path, [_entry(tmp_path)], sizes={"thing.png": (200, 399)})
    with pytest.raises(KitError, match="on disk but the manifest declares"):
        load_kit(tmp_path, registers={"marker"})


def test_a_slot_outside_its_canvas_fails_the_load(tmp_path):
    e = _entry(tmp_path)
    e["slots"] = [{"name": "interior", "x": 60, "y": 10, "w": 90, "h": 50}]
    _write(tmp_path, [e])
    with pytest.raises(KitError, match="outside canvas"):
        load_kit(tmp_path, registers={"marker"})


def test_a_frame_count_that_disagrees_with_the_file_list_fails(tmp_path):
    e = _entry(tmp_path, frames=3)
    _write(tmp_path, [e])
    with pytest.raises(KitError, match="declares 3 frames but lists 1"):
        load_kit(tmp_path, registers={"marker"})


def test_a_missing_manifest_says_how_to_get_one(tmp_path):
    with pytest.raises(KitError, match="ingest_kit"):
        load_kit(tmp_path)


def test_verification_reports_every_problem_not_just_the_first(tmp_path):
    a = _entry(tmp_path, key="a--marker", concept="a", files=["a.png"],
               svg=["a.svg"])
    b = _entry(tmp_path, key="b--marker", concept="b", files=["b.png"],
               svg=["b.svg"])
    _write(tmp_path, [a, b])
    (tmp_path / "assets" / "marker" / "a.png").unlink()
    (tmp_path / "assets" / "marker" / "b.png").unlink()
    problems = verify_entries(_parse_entries(
        json.loads((tmp_path / "assets" / "manifest.json").read_text(
            encoding="utf-8")), tmp_path),
        registers={"marker"})
    assert len(problems) == 2


# ---------------------------------------------------------------------------
# Register selection
# ---------------------------------------------------------------------------

def test_a_video_is_one_register_seeded_by_its_script():
    assert pick_register("abc123def") == pick_register("abc123def")
    assert pick_register("abc123def") in REGISTERS
    spread = {pick_register(f"{i:08x}0000") for i in range(256)}
    assert spread == set(REGISTERS), "some register is never chosen"


def test_light_resolves_in_any_register():
    """Group M is delivered once and must not need a register to be found."""
    kit = load_kit(ROOT, check_files=False)
    for register in REGISTERS:
        assert kit.concept("light-3am", register).register == LIGHT_REGISTER
