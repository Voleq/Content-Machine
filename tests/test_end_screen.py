"""V3: the long's ending holds the end screen (10-18 pick).

YouTube's end screen sits over the last 20 seconds and he places its boxes
in Studio by hand. The bot's half: the last 20 s are one shot of him, and
that shot leaves a side of clear wall, off his figure and off the sign."""

from __future__ import annotations

import pytest

from pipeline.end_screen import (END_SCREEN_S, checklist_line, clear_side,
                                 extend_for_end, zone)
from pipeline.timeline import Segment


def _plan(*spans) -> list[Segment]:
    return [Segment(a, b, kind, {"variant": i} if kind == "host" else {})
            for i, (a, b, kind) in enumerate(spans)]


def test_a_short_sign_off_gets_a_quiet_tail():
    segs = _plan((0, 580, "plate"), (580, 592, "host"))
    out, end = extend_for_end(segs, 592.0)
    assert end == pytest.approx(600.0)
    assert out[-1].kind == "host" and out[-1].start == 580
    assert out[-1].end == pytest.approx(600.0)
    assert out[-1].payload["end_screen"] is True


def test_the_cover_into_the_last_beat_is_not_counted():
    segs = _plan((0, 580, "plate"), (580, 592, "host"))
    _, end = extend_for_end(segs, 592.0, cover_s=1.2)
    assert end == pytest.approx(601.2)


def test_a_long_last_beat_needs_no_tail():
    segs = _plan((0, 560, "plate"), (560, 600, "host"))
    out, end = extend_for_end(segs, 600.0)
    assert end == 600.0 and out[-1].end == 600.0 and len(out) == 2


def test_a_video_ending_on_evidence_gets_a_beat_of_him():
    segs = _plan((0, 590, "host"), (590, 600, "plate"))
    out, end = extend_for_end(segs, 600.0, cover_s=0.3)
    assert len(out) == 3
    assert out[-1].kind == "host" and out[-1].start == 600.0
    assert end == pytest.approx(600.0 + END_SCREEN_S + 0.3)
    assert out[-1].payload["variant"] == 1        # after the last beat of him


def test_the_end_lands_on_the_frame_grid():
    segs = _plan((0, 580, "plate"), (580, 592.01, "host"))
    _, end = extend_for_end(segs, 592.01, fps=30)
    assert abs(end * 30 - round(end * 30)) < 1e-6 and end >= 600.0


def test_the_input_is_not_changed():
    segs = _plan((0, 580, "plate"), (580, 592, "host"))
    extend_for_end(segs, 592.0)
    assert segs[-1].end == 592


def test_the_right_side_is_clear_when_he_stands_left():
    him = (0.07, 0.20, 0.34, 0.95)
    side, rect = clear_side(him, [])
    assert side == "right" and rect == zone("right")


def test_the_sign_pushes_the_boxes_to_the_other_side():
    him = (0.45, 0.20, 0.58, 0.95)
    sign = (0.70, 0.30, 0.80, 0.40)
    side, _ = clear_side(him, [sign])
    assert side == "left"


def test_no_clear_side_says_so():
    assert clear_side((0.30, 0.1, 0.70, 0.9), [(0.85, 0.5, 0.9, 0.6),
                                                (0.1, 0.5, 0.15, 0.6)]) is None


def test_the_checklist_line_names_the_time_and_the_side():
    line = checklist_line({"start": 581.0, "end": 601.2, "side": "right",
                           "clear": True})
    assert "9:41" in line and "right" in line
    assert checklist_line({}) == ""
    warn = checklist_line({"start": 581.0, "end": 601.2, "side": "", "clear": False})
    assert "9:41" in warn and "no clear side" in warn
