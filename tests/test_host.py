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
    frame_shot,
    looking_at,
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
# The framings — a camera distance is not a cut-out.
# --------------------------------------------------------------------------


def _framing(reg, key):
    from pipeline.host import HostShot
    return HostShot(pose=reg.require(key),
                    talk=reg.host_strip(key, "talk"),
                    idle=reg.host_strip(key, "idle"))


@pytest.mark.parametrize("key", ("host/close-up", "host/medium"))
def test_a_framing_is_never_solved_onto_an_anchor(reg, key):
    """`close-up` and `medium` publish `floorLineY: false`.

    They are head-and-shoulders and waist-up crops: there is no floor line to
    pin and no anchor to solve them onto. Fitted into a room's standing spot,
    a close-up is a head the size of a man hovering where his shoes would be.
    """
    shot = _framing(reg, key)
    assert shot.is_framing
    assert place_on_room(reg.require("room/wide-16x9"), shot) is None


@pytest.mark.parametrize("frame", ((1920, 1080), (1080, 1920)))
@pytest.mark.parametrize("key", ("host/close-up", "host/medium"))
def test_a_framing_sits_its_crop_on_the_bottom_of_the_frame(reg, key, frame):
    """The ink runs to the plate's bottom edge — `figure` is y=40 h=1400 on a
    1440 canvas — so that edge is at or below the frame's. Lifted to put the
    eye line on the upper third, a medium draws a straight cut across his
    hands a quarter of the way up the picture."""
    placed = frame_shot(_framing(reg, key), frame)
    assert placed is not None
    assert placed.y + placed.height >= frame[1] - 1


@pytest.mark.parametrize("key", ("host/close-up", "host/medium"))
def test_a_framing_is_placed_on_its_eye_line_and_its_head(reg, key):
    """Scale by the head, place by the eyes. Both numbers are the plate's."""
    shot = _framing(reg, key)
    fw, fh = 1920, 1080
    placed = frame_shot(shot, (fw, fh))
    head = shot.pose.slot("head")
    k = placed.height / shot.pose.delivered[1]
    head_h = head.h * shot.pose.export_scale * k
    want = 0.49 if shot.pose.framing == "close-up" else 0.31
    assert abs(head_h / fh - want) < 0.01, \
        f"{key}: head is {head_h / fh:.0%} of frame height"
    # And his head is on screen, whatever his plate does at the sides.
    hx = placed.x + head.x * shot.pose.export_scale * k
    assert hx >= 0 and hx + head.w * shot.pose.export_scale * k <= fw


def test_the_width_of_a_framing_is_not_a_bound(reg):
    """The kit is explicit: both framings run off the left and right edges by
    design, and cropping to the width re-frames the shot into a narrower one
    than was drawn. In a 9:16 frame the close-up is wider than the frame."""
    placed = frame_shot(_framing(reg, "host/close-up"), (1080, 1920))
    assert placed.width > 1080


def test_a_glance_is_cut_only_when_the_side_is_known(reg):
    """A glance against a graphic on the OPPOSITE side is worse than him
    facing camera, so straight to camera is the default and the fallback."""
    shot = _framing(reg, "host/medium")
    assert looking_at(reg, shot, "left").key == "host/medium-glance-left"
    assert looking_at(reg, shot, "right").key == "host/medium-glance-right"
    assert looking_at(reg, shot, "").key == "host/medium"
    assert looking_at(reg, shot, "up").key == "host/medium"


def test_a_pose_with_no_glance_drawn_stays_facing_camera(reg):
    """The kit drew glances for the two framings and nothing else. A figure
    asked to look at a graphic returns unchanged rather than resolving to a
    key that is not there."""
    figure = shots(reg, "panel")[0]
    assert looking_at(reg, figure, "left").key == figure.key


def test_a_room_that_refuses_a_host_places_nobody(reg):
    """`hostAnchor: false` is DATA. The camera is above the desk on
    `high-desk-down` and square to a wall of index cards on `wall-of-calls`:
    neither has a floor in shot and both say so in the field rather than
    leaving it out. Reading a refusal as an omission is how a renderer ends up
    compositing a man onto a surface the camera is above."""
    figure = shots(reg, "beat")[0]
    for key in ("room/high-desk-down-16x9", "room/wall-of-calls-16x9"):
        room = reg.require(key)
        assert room.refuses_host
        assert place_on_room(room, figure) is None


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
