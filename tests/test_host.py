"""The on-screen host: roles off the registry, the flap, and the anchor.

The rig changed shape with the kit. The host is six poses, each a base strip, a
`-talk` strip whose first frame has the mouth open, and an `-idle` strip that
bobs — and WHICH POSE SERVES WHICH ROLE comes off the registry, not out of a
list in host.py. That is the test that matters: a kit with different poses has
to drop in without editing Python.

The placement tests are the other half. The anchor contract is the one thing
here that is silently wrong when approximated: scaled to the wrong thing, he
comes out at a plausible size that is wrong by ten to twenty per cent, standing
slightly above or below the floor, which reads as a bad composite rather than as
an error.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from config import Settings
from pipeline.host import (
    BEAT_GAP_S,
    available,
    beat_times,
    build_host_clip,
    mouth_schedule,
    pick_shot,
    place_on_room,
    shots,
    speaking_spans,
)
from pipeline.models import WordTimestamp
from pipeline.plates import Registry, load_plates

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def reg() -> Registry:
    return load_plates(Settings(_env_file=None).assets_dir)


class _EmptyRegistry:
    """A registry with no host at all — the degradation case."""

    host_roles: dict = {}
    host_poses: dict = {}
    assets: dict = {}

    def get(self, key):
        return None

    def host_strip(self, key, kind):
        return None

    def host_limit(self, key):
        return None


def words(*spans: tuple[float, float]) -> list[WordTimestamp]:
    return [
        WordTimestamp(word=f"w{i}", start=a, end=b, char_start=i * 3, char_end=i * 3 + 2)
        for i, (a, b) in enumerate(spans)
    ]


# --------------------------------------------------------------------------
# The banks.
# --------------------------------------------------------------------------


def test_the_roles_come_off_the_registry_not_out_of_this_codebase(reg):
    """The test the previous version failed.

    HOST_BANKS named twenty specific v1 asset paths, so the kit could not be
    replaced without editing host.py. Nothing here may name a pose.
    """
    import inspect

    import pipeline.host as host_module

    source = inspect.getsource(host_module)
    assert "host/leaning-on-desk" not in source, \
        "host.py names a specific pose — a new kit could not be swapped in"
    assert reg.host_roles, "the registry declares no host roles"


def test_every_role_can_supply_a_shot(reg):
    """A video with no host is the bug this replaced; assert it cannot recur."""
    for role in reg.host_roles_available():
        assert available(reg, role), f"the {role!r} role has no usable pose"
        for shot in shots(reg, role):
            assert shot.pose.frames
            assert shot.pose.alpha, f"{shot.key} is not a cut-out"


def test_a_pose_that_does_not_talk_is_never_offered_for_a_speaking_beat(reg):
    """head-in-hands and walking-out-of-frame ship talk frames for continuity
    of the file set, and declare talks:false because using them looks like a
    mistake. The declaration is honoured, not the file list."""
    silent = [k for k, v in reg.host_poses.items() if not v.get("talks", True)]
    assert silent, "the kit declares no non-talking poses"
    for key in silent:
        assert reg.host_strip(key, "talk") is None
        assert f"{key}-talk" in reg.assets, "the strip exists on disk"


def test_a_capped_pose_is_not_reached_twice(reg):
    """head-in-hands is the cost of being right, capped at one per video. A
    second one turns it into a running joke."""
    capped = [k for k, v in reg.host_poses.items() if v.get("limit")]
    assert capped, "the kit caps no pose"
    key = capped[0]
    used = {key: reg.host_limit(key)}
    for i in range(6):
        got = pick_shot(reg, "close", i, used=used)
        if got is not None and len(shots(reg, "close")) > 1:
            assert got.key != key, "a capped pose was reached past its limit"


def test_consecutive_beats_step_through_the_bank(reg):
    """A counter, not a hash: consecutive host beats MUST differ, and a hash
    only makes that likely."""
    bank = shots(reg, "panel")
    assert len(bank) >= 2
    picked = [pick_shot(reg, "panel", i).key for i in range(len(bank))]
    assert len(set(picked)) == len(bank), "the bank repeats before exhausting"
    assert pick_shot(reg, "panel", len(bank)).key == picked[0], "it wraps"


def test_an_empty_registry_returns_nothing_rather_than_raising():
    empty = _EmptyRegistry()
    assert shots(empty, "open") == []
    assert pick_shot(empty, "open", 0) is None
    assert not available(empty, "open")


# --------------------------------------------------------------------------
# The anchor contract.
# --------------------------------------------------------------------------


def test_he_is_scaled_to_the_anchor_height_with_his_floor_line_pinned(reg):
    """The contract, measured on every room angle.

    scale so (host.floorLineY - figure.y) == anchor.h, then sit floorLineY on
    the anchor's bottom edge.
    """
    shot = shots(reg, "beat")[0]
    figure = shot.pose.slot("figure")
    hs = shot.pose.export_scale
    for key in reg.family("room"):
        room = reg.assets[key]
        anchor = room.slot("host-anchor")
        if anchor is None:
            continue
        placed = place_on_room(room, shot)
        assert placed is not None, f"{key} has an anchor and no placement"
        _, ay, _, ah = anchor.scaled()

        standing = (shot.floor_line_y - figure.y) * hs * placed.scale
        assert abs(standing - ah) < 1.5, \
            f"{key}: standing height {standing:.0f} against an anchor of {ah}"

        floor = placed.y + shot.floor_line_y * hs * placed.scale
        assert abs(floor - (ay + ah)) < 1.5, \
            f"{key}: his floor line at {floor:.0f}, the anchor's at {ay + ah}"


def test_he_is_never_scaled_to_the_anchor_width(reg):
    """The figure box includes the arms, which are meant to pass the anchor.
    Fitting the width makes him small and puts his feet in the air."""
    shot = shots(reg, "beat")[0]
    room = reg.require("room/wide-16x9")
    anchor = room.slot("host-anchor")
    _, _, aw, _ = anchor.scaled()
    placed = place_on_room(room, shot)
    figure_w = shot.pose.slot("figure").w * shot.pose.export_scale * placed.scale
    assert abs(figure_w - aw) > 1.0, \
        "the figure box was fitted to the anchor width"


def test_a_room_with_no_anchor_places_nothing(reg):
    """None, rather than a guess. A host somewhere arbitrary is worse than no
    host, because nobody looks for a bug in a frame that has a man in it."""
    shot = shots(reg, "beat")[0]
    plate = reg.require("tables/numbers-sheet-6r-16x9")
    assert place_on_room(plate, shot) is None


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


def test_build_host_clip_writes_an_alpha_clip(tmp_path, reg, settings):
    out = build_host_clip(words((0.2, 1.2), (1.6, 2.4)), 0.0, 3.0,
                          tmp_path / "host.mov", reg=reg, settings=settings,
                          display_w=320, fps=12, role="open")
    assert out is not None
    path, (w, h) = out
    assert path.exists() and path.stat().st_size > 0
    assert w == 320 and h > 0


def test_the_clip_reports_whether_the_face_moved(tmp_path, reg, settings):
    """Over forty minutes the host is the most-viewed element in the channel
    and the easiest to leave static without noticing."""
    report: dict = {}
    build_host_clip(words((0.2, 1.2), (1.6, 2.4)), 0.0, 3.0,
                    tmp_path / "host.mov", reg=reg, settings=settings,
                    display_w=320, fps=12, role="beat", report=report)
    assert report.get("pose")
    assert report.get("spoke") is True, "a speaking beat did not open the mouth"
    assert report.get("talk_frames", 0) > 0


def test_a_missing_kit_degrades_instead_of_failing(tmp_path, settings):
    """No kit on disk must not raise here — the SHORT engine decides that a
    missing host is fatal, which is a different question from this one."""
    assert build_host_clip(words((0.0, 1.0)), 0.0, 2.0, tmp_path / "x.mov",
                           reg=_EmptyRegistry(), settings=settings,
                           display_w=100, fps=12) is None


def test_zero_length_segment_builds_nothing(tmp_path, reg, settings):
    assert build_host_clip(words((0.0, 1.0)), 2.0, 2.0, tmp_path / "x.mov",
                           reg=reg, settings=settings, display_w=100,
                           fps=12) is None
