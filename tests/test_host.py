"""The on-screen host: shot banks, mouth-flap and the boil.

The rig changed shape with the kit. The old one composited a pose from
separately exported mouth frames; the rebuilt kit ships the host as *pairs* —
a composed shot and its `-talk` twin — so a shot is two frames and talking is
a swap between them. The tests follow: what used to be a three-level mouth
ramp is a two-state flap, and what used to be a hardcoded pose table is a bank
resolved through the registry.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.host import (
    BEAT_GAP_S,
    HOST_BANKS,
    available,
    beat_times,
    build_host_clip,
    mouth_schedule,
    pick_shot,
    shots,
    speaking_spans,
)
from pipeline.kit import Kit
from pipeline.models import WordTimestamp

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def kit() -> Kit:
    return Kit(ROOT / "assets" / "kit")


def words(*spans: tuple[float, float]) -> list[WordTimestamp]:
    return [
        WordTimestamp(word=f"w{i}", start=a, end=b, char_start=i * 3, char_end=i * 3 + 2)
        for i, (a, b) in enumerate(spans)
    ]


# --------------------------------------------------------------------------
# The banks.
# --------------------------------------------------------------------------


def test_every_bank_can_supply_a_lip_synced_shot(kit):
    """A short with no host is the bug this replaced; assert it can't recur."""
    for role in HOST_BANKS:
        assert available(kit, role), f"the {role!r} bank has no usable talk pair"
        for shot in shots(kit, role):
            assert shot.closed.key != shot.open_.key
            assert shot.closed.frames and shot.open_.frames


def test_a_dead_talk_twin_is_never_offered_as_a_shot(kit):
    """`chapters/management/dennis-reads-proxy-talk` is byte-identical to its
    base, so flapping it animates nothing. The kit says so rather than letting
    the render pretend."""
    assert kit.talk_pair("chapters/management/dennis-reads-proxy") is None
    every = {s.key for role in HOST_BANKS for s in shots(kit, role)}
    assert "chapters/management/dennis-reads-proxy" not in every


def test_consecutive_beats_step_through_the_bank(kit):
    """A counter, not a hash: consecutive host beats MUST differ, and a hash
    only makes that likely."""
    bank = shots(kit, "panel")
    assert len(bank) >= 2
    picked = [pick_shot(kit, "panel", i).key for i in range(len(bank))]
    assert len(set(picked)) == len(bank), "the bank repeats before exhausting"
    assert pick_shot(kit, "panel", len(bank)).key == picked[0], "it wraps"


def test_an_empty_bank_returns_nothing_rather_than_raising(tmp_path):
    empty = Kit(tmp_path / "no-kit")
    assert shots(empty, "open") == []
    assert pick_shot(empty, "open", 0) is None
    assert not available(empty, "open")


# --------------------------------------------------------------------------
# The flap.
# --------------------------------------------------------------------------


def test_speaking_spans_are_clipped_to_the_segment():
    w = words((0.0, 1.0), (2.0, 3.0), (9.0, 10.0))
    assert speaking_spans(w, 0.5, 5.0) == [(0.5, 1.0), (2.0, 3.0)]


def test_mouth_is_open_on_words_and_closed_in_gaps():
    fps = 30
    w = words((0.0, 1.0), (3.0, 4.0))
    plan = mouth_schedule(w, 0.0, 5.0, fps)
    assert len(plan) == 5 * fps
    assert any(plan[int(0.0 * fps):int(1.0 * fps)]), "the mouth opens on a word"
    assert not plan[int(2.5 * fps)], "the long gap closes it"
    assert not plan[-1], "it ends closed"


def test_the_mouth_works_rather_than_gaping():
    """Open for a whole sentence is a puppet. It alternates at FLAP_HZ."""
    plan = mouth_schedule(words((0.0, 3.0)), 0.0, 3.0, 30)
    assert any(plan) and not all(plan)
    flips = sum(1 for a, b in zip(plan, plan[1:]) if a != b)
    assert flips >= 6, f"only {flips} mouth changes across three seconds"


def test_a_silent_segment_never_opens_the_mouth():
    assert not any(mouth_schedule(words((20.0, 21.0)), 0.0, 4.0, 30))


def test_beats_are_the_sentence_pauses():
    w = words((0.0, 1.0), (1.05, 2.0), (2.8, 3.5))
    assert beat_times(w, 0.0, 5.0) == [2.0]  # only the >= BEAT_GAP_S pause
    assert 2.8 - 2.0 >= BEAT_GAP_S


# --------------------------------------------------------------------------
# The clip.
# --------------------------------------------------------------------------


def test_build_host_clip_writes_an_alpha_clip(tmp_path, kit, settings):
    out = build_host_clip(words((0.2, 1.2), (1.6, 2.4)), 0.0, 3.0,
                          tmp_path / "host.mov", kit=kit, settings=settings,
                          display_w=320, fps=12, role="open")
    assert out is not None
    path, (w, h) = out
    assert path.exists() and path.stat().st_size > 0
    assert w == 320 and h > 0


def test_a_missing_kit_degrades_instead_of_failing(tmp_path, settings):
    """No kit on disk must not raise here — the SHORT engine decides that a
    missing host is fatal, which is a different question from this one."""
    empty = Kit(tmp_path / "no-kit")
    assert build_host_clip(words((0.0, 1.0)), 0.0, 2.0, tmp_path / "x.mov",
                           kit=empty, settings=settings, display_w=100,
                           fps=12) is None


def test_zero_length_segment_builds_nothing(tmp_path, kit, settings):
    assert build_host_clip(words((0.0, 1.0)), 2.0, 2.0, tmp_path / "x.mov",
                           kit=kit, settings=settings, display_w=100,
                           fps=12) is None
