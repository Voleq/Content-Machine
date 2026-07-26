"""The on-screen host: mouth-flap, face swaps and the boil."""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.host import (
    BEAT_GAP_S,
    RIGS,
    available,
    beat_times,
    build_host_clip,
    frame_plan,
    mouth_schedule,
    rig_for,
    speaking_spans,
)
from pipeline.models import WordTimestamp

ROOT = Path(__file__).resolve().parents[1]


def words(*spans: tuple[float, float]) -> list[WordTimestamp]:
    return [
        WordTimestamp(word=f"w{i}", start=a, end=b, char_start=i * 3, char_end=i * 3 + 2)
        for i, (a, b) in enumerate(spans)
    ]


def test_the_rig_shipped_with_the_kit():
    assert available(ROOT), "Part 0 must have exported the host poses"
    for expression, facing in RIGS:
        assert available(ROOT, expression, facing), f"{expression}/{facing} incomplete"


def test_speaking_spans_are_clipped_to_the_segment():
    w = words((0.0, 1.0), (2.0, 3.0), (9.0, 10.0))
    assert speaking_spans(w, 0.5, 5.0) == [(0.5, 1.0), (2.0, 3.0)]


def test_mouth_is_open_on_words_and_closed_in_gaps():
    fps = 30
    w = words((0.0, 1.0), (3.0, 4.0))
    levels = mouth_schedule(w, 0.0, 5.0, fps)
    assert len(levels) == 5 * fps

    speaking = levels[int(0.4 * fps):int(0.9 * fps)]
    assert max(speaking) == 2, "the mouth opens while a word sounds"
    # the long gap closes it completely
    assert levels[int(2.5 * fps)] == 0
    assert levels[-1] == 0, "it ends closed"


def test_the_mouth_ramps_rather_than_snapping():
    """closed -> mid -> open, one step per frame — never a jump cut."""
    levels = mouth_schedule(words((1.0, 2.0)), 0.0, 3.0, 30)
    for a, b in zip(levels, levels[1:]):
        assert abs(a - b) <= 1


def test_a_silent_segment_never_opens_the_mouth():
    levels = mouth_schedule(words((20.0, 21.0)), 0.0, 4.0, 30)
    assert set(levels) == {0}


def test_beats_are_the_sentence_pauses():
    w = words((0.0, 1.0), (1.05, 2.0), (2.8, 3.5))
    assert beat_times(w, 0.0, 5.0) == [2.0]  # only the >= BEAT_GAP_S pause
    assert 2.8 - 2.0 >= BEAT_GAP_S


def test_the_face_swaps_on_a_beat():
    rig = rig_for("talk", "right")
    w = words((0.0, 1.5), (2.5, 4.0))
    plan = frame_plan(w, 0.0, 5.0, 30, rig)
    opens = {f for f in plan if f in (rig.open_, rig.alt_open)}
    assert opens == {rig.open_, rig.alt_open}, "both faces are used across the beat"
    assert plan.index(rig.open_) < plan.index(rig.alt_open)


def test_a_rig_without_a_mid_frame_still_flaps():
    rig = rig_for("point", "right")
    assert rig.mid is None
    plan = frame_plan(words((0.0, 1.0)), 0.0, 2.0, 30, rig)
    assert set(plan) == {rig.closed, rig.open_}


def test_unknown_expression_falls_back_to_talking():
    assert rig_for("brooding", "left") is RIGS[("talk", "left")]


def test_build_host_clip_writes_an_alpha_clip(tmp_path):
    out = build_host_clip(words((0.2, 1.2), (1.6, 2.4)), 0.0, 3.0,
                          tmp_path / "host.mov", display_h=240, fps=12, root=ROOT)
    assert out is not None
    path, (w, h) = out
    assert path.exists() and path.stat().st_size > 0
    assert h == 240 and w > 0


def test_a_missing_rig_degrades_instead_of_failing(tmp_path):
    """No kit on disk must not fail a render — the caller falls back."""
    assert build_host_clip(words((0.0, 1.0)), 0.0, 2.0, tmp_path / "x.mov",
                           display_h=100, fps=12, root=tmp_path) is None


def test_zero_length_segment_builds_nothing(tmp_path):
    assert build_host_clip(words((0.0, 1.0)), 2.0, 2.0, tmp_path / "x.mov",
                           display_h=100, fps=12, root=ROOT) is None
