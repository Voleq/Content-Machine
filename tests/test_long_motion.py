"""Chapters, motion and the host-beat cap in the LONG.

Three things the suite passed green on while they were absent:

* the stingers spaced six HARDCODED titles evenly across the runtime and
  ignored the script's own `=== CHAPTERS ===` trailer entirely, so every video
  announced sections it did not have;
* not one of `render_clip`, `frame_indices`, `punch_crop`, `is_full_frame`,
  `transition_asset` or `playback_seconds` was reachable from a long cut — 84
  multi-frame drawings frozen, 57 boil pairs never shimmering;
* `add_host` emitted exactly one segment per untagged gap and there was no
  maximum, so ninety untagged seconds was ninety seconds of a single frame.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.host import BANK_EXTENSIONS, HOST_BANKS, shots
from pipeline.kit import load_kit
from pipeline.kit_frames import (
    ORIENTATION_SUFFIXES,
    TRANSITION_FAMILIES,
    _orientation_base,
    cover_keeps_fraction,
    crop_window_coverage,
    is_full_frame,
    transition_asset,
)
from pipeline.render_long import _CHAPTERS, _chapter_plan
from pipeline.timeline import (
    HOST_GAP_WARN_S,
    MAX_HOST_BEAT_S,
    chapter_start_times,
    plan_long_segments,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def kit():
    return load_kit(ROOT / "assets")


# --------------------------------------------------------------------------
# Chapters come from the script.
# --------------------------------------------------------------------------

TRAILER = """
0:00 the setup
0:35 what the money actually does
1:10 five years of numbers
2:15 the resigned close
"""


def test_the_trailer_yields_times_and_titles():
    got = chapter_start_times(TRAILER, 300.0)
    assert got == [(35.0, "what the money actually does"),
                   (70.0, "five years of numbers"),
                   (135.0, "the resigned close")]


def test_a_chapter_past_the_end_is_dropped():
    got = chapter_start_times(TRAILER, 60.0)
    assert [t for t, _ in got] == [35.0]


def test_hours_parse_too():
    assert chapter_start_times("1:02:03 late", 10_000)[0][0] == 3723.0


def test_a_junk_line_is_skipped_not_fatal():
    assert chapter_start_times("not a timestamp\n0:30 real", 100)[0][1] == "real"


def test_the_plan_uses_the_scripts_own_titles():
    warnings: list[str] = []
    plan = _chapter_plan(TRAILER, 300.0, warnings.append)
    assert [ti for _, ti in plan] == ["what the money actually does",
                                      "five years of numbers",
                                      "the resigned close"]
    assert warnings == [], "a usable trailer must not warn"


def test_no_trailer_falls_back_and_says_so():
    """The fallback is fine; using it silently is not — the titles will be
    wrong for this video and only a human can tell."""
    warnings: list[str] = []
    plan = _chapter_plan("", 300.0, warnings.append)
    assert plan, "the fallback still has to divide the acts"
    assert [ti for _, ti in plan] == [t for _, t in _CHAPTERS[1:]]
    assert warnings and "CHAPTERS" in warnings[0]


def test_a_timestamp_with_no_title_borrows_one_and_warns():
    warnings: list[str] = []
    plan = _chapter_plan("0:30\n1:00 real title", 300.0, warnings.append)
    assert plan[0][1], "a blank card is not an option"
    assert any("no title" in w for w in warnings)


# --------------------------------------------------------------------------
# The host beat is capped.
# --------------------------------------------------------------------------


def test_a_long_gap_becomes_several_beats():
    segments, _ = plan_long_segments([], 95.0)
    assert {s.kind for s in segments} == {"host"}
    assert max(s.length for s in segments) <= MAX_HOST_BEAT_S + 1e-6


def test_the_split_beats_tile_the_gap_exactly():
    segments, _ = plan_long_segments([], 95.0)
    assert segments[0].start == 0.0
    assert segments[-1].end == pytest.approx(95.0)
    for a, b in zip(segments, segments[1:]):
        assert a.end == pytest.approx(b.start)


def test_a_visually_silent_stretch_is_named():
    _, warnings = plan_long_segments([], HOST_GAP_WARN_S + 10)
    assert any("no visual" in w for w in warnings), warnings


def test_the_beat_bank_is_long_enough_for_a_long_cut(kit):
    """Five shots wrapping every minute is the most visible thing in a
    forty-minute video."""
    assert "panel" in BANK_EXTENSIONS["beat"]
    beat = shots(kit, "beat")
    assert len(beat) > len(HOST_BANKS["beat"]), "the bank never widened"
    keys = [s.key for s in beat]
    assert len(set(keys)) == len(keys), "a shot is offered twice"


def test_extending_a_bank_keeps_its_own_shots_first(kit):
    beat = [s.key for s in shots(kit, "beat")]
    own = [k for k in HOST_BANKS["beat"] if k in beat]
    assert beat[:len(own)] == own


# --------------------------------------------------------------------------
# Transitions pick by aspect.
# --------------------------------------------------------------------------


def test_a_vertical_frame_only_draws_vertical_strips(kit):
    """Picking uniformly let a 9:16 short draw a 16:9 strip, which a
    cover-fit crops to a third of its width."""
    if not any(kit.family(f) for f in TRANSITION_FAMILIES):
        pytest.skip("no transition strips ship yet")
    picked = [transition_asset(kit, "seed", i, frame=(1080, 1920))
              for i in range(8)]
    assert all(p is not None for p in picked)
    if any(is_full_frame(p, (1080, 1920)) for p in picked):
        assert all(is_full_frame(p, (1080, 1920)) for p in picked), \
            [p.name for p in picked]


def test_a_horizontal_frame_only_draws_horizontal_strips(kit):
    if not any(kit.family(f) for f in TRANSITION_FAMILIES):
        pytest.skip("no transition strips ship yet")
    picked = [transition_asset(kit, "seed", i, frame=(1920, 1080))
              for i in range(8)]
    assert all(is_full_frame(p, (1920, 1080)) for p in picked), \
        [p.name for p in picked]


def test_a_wide_strip_never_competes_with_its_tall_twin(kit):
    """`paper-slide-tall` is the vertical twin of `paper-slide`, not a
    twelfth independent option."""
    tall = [k for k in kit.family("stings") if k.endswith("-tall")]
    if not tall:
        pytest.skip("no orientation variants ship yet")
    picked = {transition_asset(kit, "seed", i, frame=(1080, 1920)).name
              for i in range(12)}
    for key in tall:
        base = _orientation_base(kit.get(key).name)
        assert base not in picked, \
            f"{base} was offered alongside its tall twin"


def test_orientation_bases_strip_the_suffix():
    assert _orientation_base("paper-slide-tall") == "paper-slide"
    assert _orientation_base("paper-slide") == "paper-slide"
    assert all(s.startswith("-") for s in ORIENTATION_SUFFIXES)


def test_the_cover_ratio_is_measured_not_assumed(kit):
    """A 16:9 strip cover-fitted into 9:16 keeps 32% of its width. That is
    fine for an effect in the middle and fatal for one that crosses."""
    wide = next((kit.get(k) for k in kit.family("stings")
                 if kit.get(k).aspect == "16:9"), None)
    if wide is None:
        pytest.skip("no wide strips ship yet")
    keep = cover_keeps_fraction(wide, 1080, 1920)
    assert 0.30 < keep < 0.34, keep
    assert cover_keeps_fraction(wide, 1920, 1080) == pytest.approx(1.0)


def test_a_strip_that_covers_the_crop_window_is_allowed_to_crop(settings, kit):
    """The commissioned wide strips are drawn to cover the frame, so the
    centre crop still lands a cut under them."""
    wide = next((kit.get(k) for k in kit.family("stings")
                 if kit.get(k).aspect == "16:9"), None)
    if wide is None:
        pytest.skip("no wide strips ship yet")
    keep = cover_keeps_fraction(wide, 1080, 1920)
    assert crop_window_coverage(wide, settings, keep) > 0.6
