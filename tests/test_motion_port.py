"""`pipeline/motion.py` against the kit's own `engine/motion.js`.

THE PORT MOVES AS DESIGN'S FILE MOVES. Every function the renderer plays a
move with is called here on the same arguments in both languages, and the
answers compared number for number: the eases at every frame a move can land
on, the count-up's text, the reveal boxes, the pen's ring, the zoom's viewBox,
the loops. The node side loads the installed kit's file itself, so a drop that
changes an ease fails this rather than drifting quietly away from the review
page design signed off.
"""

from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from pipeline import motion as M

ROOT = Path(__file__).resolve().parents[1]
MOTION_JS = ROOT / "kit" / "engine" / "motion.js"

TS = [i / 24 for i in range(-3, 28)] + [f / 6 for f in range(7)] + \
     [f / 7 for f in range(8)] + [f / 11 for f in range(12)] + [0.4948, 0.6632]

COUNTS = ["$3.1bn", "−40%", "+2.6pt", "12,400", "03", "SOURCE · 10-K",
          "1,234,567.89", "-0.5x", "no digits", "$0", "+29%", "4.1×", "18th",
          "(12.5)", "1,000", "0.25", "+2.5", "7.5%", "$1.28", "5× average"]

BOXES = [(90, 717, 900, 267), (430, 282, 560, 56), (160, 260, 1160, 480),
         (0, 0, 40, 20), (1400, 344, 360, 122)]

_CASES = r"""
'use strict';
const M = require(process.argv[2]);
const cases = JSON.parse(require('fs').readFileSync(process.argv[3], 'utf8'));
const out = {};
out.eases = {};
for (const e of ['linear', 'out', 'inOut', 'land'])
  out.eases[e] = cases.ts.map(t => M.E[e](t));
out.count = cases.counts.map(s => cases.ts.map(t => M.countText(s, t)));
const box = b => ({ x: b[0], y: b[1], w: b[2], h: b[3] });
out.reveal = cases.boxes.map(b => ['bottom', 'top', 'left', 'left-linear'].map(
  side => cases.ts.map(t => M.reveal(box(b), t, side))));
out.pen = cases.boxes.map(b => [5, 7, 0, 123].map(seed => M.penCircle(box(b), seed)));
out.dash = cases.ts.map(t => M.penDash(1000, t).dashoffset);
out.zoom = [[1920, 1080], [1080, 1920]].map(cv => cases.boxes.map(b =>
  [60, 40, 0].map(pad => cases.ts.map(t => M.zoomBox(cv, box(b), t, pad)))));
out.snow = [...Array(12).keys()].map(f => M.snow(box([100, 50, 400, 300]), f));
out.rain = [...Array(12).keys()].map(f => M.RAIN(box([100, 50, 400, 300]), f));
out.twinkle = [...Array(6).keys()].map(i => [...Array(13).keys()].map(f => M.twinkleInk(i, f)));
out.outset = cases.boxes.map(b => [0, 14, 60].map(p => M.outset(box(b), p)));
out.stagger = [...Array(16).keys()].map(f => [0, 1, 5].map(i => M.stagger(f, i, 8)));
out.pin = cases.ts.map(t => M.pinDrop(t));
out.slide = cases.ts.map(t => [M.slideX(900, t), M.slideX(980, t)]);
out.tick = cases.ts.map(t => M.tick(348, t));
out.pulse = [M.SCREEN_PULSE, M.LAMP_FLICKER, M.TWINKLE, M.FPS, M.TWINKLE_STEP];
out.timings = M.TIMINGS;
process.stdout.write(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def kit(tmp_path_factory):
    node = shutil.which("node")
    if node is None or not MOTION_JS.exists():
        pytest.skip("needs node and the kit's engine/motion.js")
    d = tmp_path_factory.mktemp("motion")
    script, cases = d / "cases.js", d / "cases.json"
    script.write_text(_CASES, encoding="utf-8")
    cases.write_text(json.dumps({"ts": TS, "counts": COUNTS, "boxes": BOXES}),
                     encoding="utf-8")
    proc = subprocess.run([node, str(script), str(MOTION_JS), str(cases)],
                          capture_output=True, text=True, timeout=120, cwd=ROOT)
    assert proc.returncode == 0, proc.stderr[-2000:]
    return json.loads(proc.stdout)


def _close(a: float, b: float, tol: float = 1e-9) -> bool:
    return math.isclose(a, b, rel_tol=tol, abs_tol=tol)


def test_every_ease_matches_at_every_frame_a_move_can_land_on(kit):
    for name, fn in (("linear", M.linear), ("out", M.out),
                     ("inOut", M.in_out), ("land", M.land)):
        for t, want in zip(TS, kit["eases"][name]):
            assert _close(fn(t), want), f"{name}({t}) = {fn(t)}, kit {want}"


def test_a_count_up_reads_the_same_text_on_every_frame(kit):
    for text, row in zip(COUNTS, kit["count"]):
        for t, want in zip(TS, row):
            assert M.count_text(text, t) == want, (text, t)


def test_a_reveal_grows_the_same_box_from_every_side(kit):
    sides = ["bottom", "top", "left", "left-linear"]
    for b, per_side in zip(BOXES, kit["reveal"]):
        for side, row in zip(sides, per_side):
            for t, want in zip(TS, row):
                got = M.reveal(M.Box(*b), t, side)
                for k in "xywh":
                    assert _close(getattr(got, k), want[k]), (b, side, t, k)


def test_the_pen_draws_the_same_ring_and_the_same_length(kit):
    """The ring's points against the path string design strokes, to the
    tenth it is printed at, and its length exactly."""
    for b, per_seed in zip(BOXES, kit["pen"]):
        for seed, want in zip([5, 7, 0, 123], per_seed):
            got = M.pen_circle(M.Box(*b), seed)
            assert _close(got.length, want["len"]), (b, seed)
            printed = [float(x) for x in re.findall(r"-?\d+\.\d", want["d"])]
            flat = [c for p in got.points for c in p]
            assert len(printed) == len(flat) == 90
            assert all(abs(p - q) <= 0.05 + 1e-9 for p, q in zip(flat, printed))


def test_the_pen_shows_what_the_dash_offset_hides(kit):
    for t, offset in zip(TS, kit["dash"]):
        assert _close(M.pen_drawn(1000, t), 1000 - offset)


def test_the_zoom_arrives_on_the_same_viewbox(kit):
    for cv, per_box in zip([(1920, 1080), (1080, 1920)], kit["zoom"]):
        for b, per_pad in zip(BOXES, per_box):
            for pad, row in zip([60, 40, 0], per_pad):
                for t, want in zip(TS, row):
                    got = M.zoom_box(cv, M.Box(*b), t, pad)
                    assert all(_close(g, w) for g, w in zip(got, want)), (cv, b, pad, t)


def test_the_room_loops_fall_and_twinkle_the_same(kit):
    pane = M.Box(100, 50, 400, 300)
    for f, flakes in enumerate(kit["snow"]):
        got = M.snow(pane, f)
        assert len(got) == len(flakes) == 26
        for g, w in zip(got, flakes):
            assert _close(g.x, w["x"]) and _close(g.y, w["y"]) and _close(g.r, w["r"])
    for f, drops in enumerate(kit["rain"]):
        got = M.rain(pane, f)
        assert len(got) == len(drops) == 40
        for g, w in zip(got, drops):
            assert _close(g.x, w["x"]) and _close(g.y, w["y"])
            assert (g.w, g.h) == (w["w"], w["h"])
    for i, row in enumerate(kit["twinkle"]):
        assert [M.twinkle_ink(i, f) for f in range(13)] == row
    pulse, lamp, twinkle, fps, step = kit["pulse"]
    assert list(M.SCREEN_PULSE) == pulse and list(M.LAMP_FLICKER) == lamp
    assert list(M.TWINKLE) == twinkle and M.FPS == fps and M.TWINKLE_STEP == step


def test_every_loop_is_seamless_frame_twelve_is_frame_zero():
    """Design's promise for rebuild-40, and what the bot bakes: a loop that
    jumps at its seam jumps every second on screen."""
    pane = M.Box(100, 50, 400, 300)
    for a, b in zip(M.snow(pane, 0), M.snow(pane, 12)):
        assert _close(a.x, b.x) and _close(a.y, b.y)
    for a, b in zip(M.rain(pane, 0), M.rain(pane, 12)):
        assert _close(a.x, b.x) and _close(a.y, b.y)
    for phase in range(3):
        assert M.twinkle_ink(phase, 0) == M.twinkle_ink(phase, 12)


def test_a_column_grows_one_frame_after_the_last_and_a_plot_grows_by_its_bleed(kit):
    for b, per_pad in zip(BOXES, kit["outset"]):
        for p, want in zip([0, 14, 60], per_pad):
            got = M.outset(M.Box(*b), p)
            assert all(_close(getattr(got, k), want[k]) for k in "xywh"), (b, p)
    for f, row in enumerate(kit["stagger"]):
        for i, want in zip([0, 1, 5], row):
            assert _close(M.stagger(f, i, 8), want), (f, i)


def test_the_timings_the_registry_carries_are_the_kit_s(kit):
    """The bumper's tick-over and the source tag's rule are read off the
    registry, not written into the bot: they must be design's."""
    from config import Settings
    from pipeline.plates import load_plates

    reg = load_plates(Settings(_env_file=None).assets_dir)
    if not reg.motion_timings:
        pytest.skip("the kit is not ingested")
    assert reg.motion_timings == kit["timings"]


def test_the_overlays_slide_pin_and_tick_the_same(kit):
    for t, pin, slide, tk in zip(TS, kit["pin"], kit["slide"], kit["tick"]):
        dy, rot = M.pin_drop(t)
        assert _close(dy, pin["dy"]) and _close(rot, pin["rot"])
        assert _close(M.slide_x(900, t), slide[0]) and _close(M.slide_x(980, t), slide[1])
        old, new = M.tick(348, t)
        assert _close(old, tk["oldY"]) and _close(new, tk["newY"])


def test_the_catalogue_the_registry_carries_is_the_one_this_port_plays():
    """Frames, ease and playback per move come from `emit/motion.json` via the
    registry; every ease it names must be one this file has."""
    from config import Settings
    from pipeline.plates import load_plates

    reg = load_plates(Settings(_env_file=None).assets_dir)
    assert reg.motion_fps == M.FPS
    assert len(reg.motion_moves) == 13
    for move, spec in reg.motion_moves.items():
        assert spec.get("ease") in (None, *M.EASES), (move, spec.get("ease"))


def test_a_count_up_ends_on_the_figure_it_started_from():
    """Except where design's own drops zero padding: "03" lands on "3"."""
    for text in ("$3.1bn", "−40%", "+2.6pt", "12,400", "1,234,567.89", "+29%"):
        assert M.count_text(text, 1.0) == text
    assert M.count_text("03", 1.0) == "3"
    assert M.count_text("+29%", 0.0) == "0%"


def test_a_partial_path_stops_mid_segment_at_the_drawn_length():
    pts = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]
    assert M.partial_path(pts, 0) == []
    assert M.partial_path(pts, 5) == [(0.0, 0.0), (5.0, 0.0)]
    assert M.partial_path(pts, 15) == [(0.0, 0.0), (10.0, 0.0), (10.0, 5.0)]
    assert M.partial_path(pts, 99) == pts
