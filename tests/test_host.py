"""The on-screen host: roles off the registry, the face, and the anchor.

The rig changed shape with the kit. The host is twelve poses and one framing,
each four strips — the hold, `-talk` (closed, mid and wide mouths), `-idle`
(his weight settling) and `-blink` — and the frames say what they are, so the
player reads `mouthOpen` and `eyes` rather than a frame's position. WHICH POSE
SERVES WHICH ROLE comes off the registry, not out of a list in host.py. That
is the test that matters: a kit with different poses has to drop in without
editing Python.

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
    BLINK_S,
    IDLE_MIN_SPAN_S,
    available,
    beat_times,
    build_host_clip,
    face_plan,
    frame_shot,
    host_shot,
    mouth_schedule,
    pick_framing,
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
    mistake. The declaration is honoured, not the file list.

    WHICH IS THE POINT, AND IT DOES NOT NEED THE FILE TO BE THERE. This used
    to also require `{key}-talk` on disk, which was never the rule — it was an
    incidental property of the only two silent poses the kit had at the time.
    `host/empty-chair` declares talks:false and ships no talk strip, which is
    more correct than either of them: an empty chair has no talking version to
    be continuous with. Requiring the file turned a pose that is right for a
    better reason into a failure.

    So the assertion is the declaration, both ways round: a silent pose is
    never offered a talk strip, whether the file exists or not.
    """
    silent = [k for k, v in reg.host_poses.items() if not v.get("talks", True)]
    assert silent, "the kit declares no non-talking poses"
    for key in silent:
        assert reg.host_strip(key, "talk") is None, (
            f"{key} declares talks:false and was offered a talk strip")


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
    room = reg.require("room/desk-front-16x9")
    anchor = room.slot("host-anchor")
    _, _, aw, _ = anchor.scaled()
    placed = place_on_room(room, shot)
    figure_w = shot.pose.slot("figure").w * shot.pose.export_scale * placed.scale
    assert abs(figure_w - aw) > 1.0, \
        "the figure box was fitted to the anchor width"


def test_a_room_with_no_anchor_refuses_rather_than_guessing(reg):
    """It RAISES. A host somewhere arbitrary is worse than no host, because
    nobody looks for a bug in a frame that has a man in it — and returning
    nothing is what let the caller put him somewhere arbitrary."""
    from pipeline.host import HostPlacementError

    shot = shots(reg, "beat")[0]
    plate = reg.require("tables/numbers-sheet-6r-16x9")
    with pytest.raises(HostPlacementError, match="host-anchor"):
        place_on_room(plate, shot)


# --------------------------------------------------------------------------
# The framings — a camera distance is not a cut-out.
# --------------------------------------------------------------------------


def _framing(reg, key):
    return host_shot(reg, key)


def test_a_framing_is_never_solved_onto_an_anchor(reg):
    """`close-up` publishes `floorLineY: false`.

    It is a head-and-shoulders window on him: there is no floor line to pin
    and no anchor to solve it onto. Fitted into a room's standing spot, a
    close-up is a head the size of a man hovering where his shoes would be.
    """
    from pipeline.host import HostPlacementError, stands_on

    shot = _framing(reg, "host/close-up")
    assert shot.is_framing
    room = reg.require("room/desk-front-16x9")
    assert not stands_on(room, shot)
    with pytest.raises(HostPlacementError, match="camera distance"):
        place_on_room(room, shot)


@pytest.mark.parametrize("frame", ((1920, 1080), (1080, 1920)))
def test_a_framing_sits_its_crop_on_the_bottom_of_the_frame(reg, frame):
    """The window cuts him across the chest, so its bottom edge is at or below
    the frame's. Lifted to put the eye line on the upper third, a short crop
    draws a straight cut across him partway up the picture."""
    placed = frame_shot(_framing(reg, "host/close-up"), frame)
    assert placed is not None
    assert placed.y + placed.height >= frame[1] - 1


@pytest.mark.parametrize("frame", ((1920, 1080), (1080, 1920)))
def test_a_framing_is_placed_on_its_eye_line_and_its_head(reg, frame):
    """Scale by the head, place by the eyes. Both numbers are the plate's.

    THE EYES ARE ON THE UPPER THIRD, not wherever the crop's bottom edge
    drags them. The crop was pulled UP until its bottom sat on the frame's —
    a `min` that meant `max` — which on the rebuild's close-up, a window that
    runs well past a 16:9 frame, lifted his eyes off the top of the picture:
    the one shot whose whole point is his face.
    """
    shot = _framing(reg, "host/close-up")
    fw, fh = frame
    placed = frame_shot(shot, frame)
    head = shot.pose.slot("head")
    k = placed.height / shot.pose.delivered[1]
    head_h = head.h * shot.pose.export_scale * k
    assert abs(head_h / fh - 0.49) < 0.01, \
        f"head is {head_h / fh:.0%} of frame height"
    eyes = placed.y + shot.pose.fit["eyeLineY"] * shot.pose.export_scale * k
    assert abs(eyes - fh / 3) <= 2, \
        f"his eyes are at {eyes:.0f}px, the upper third at {fh / 3:.0f}px"
    # And his head is on screen, whatever his plate does at the sides.
    hx = placed.x + head.x * shot.pose.export_scale * k
    assert hx >= 0 and hx + head.w * shot.pose.export_scale * k <= fw
    assert placed.y + head.y * shot.pose.export_scale * k >= 0, \
        "the top of his head is off the frame"


def test_the_width_of_a_framing_is_not_a_bound(reg):
    """The kit is explicit: a framing runs off the left and right edges by
    design, and cropping to the width re-frames the shot into a narrower one
    than was drawn. In a 9:16 frame the close-up is wider than the frame."""
    placed = frame_shot(_framing(reg, "host/close-up"), (1080, 1920))
    assert placed.width > 1080


@pytest.mark.parametrize("graphic_side", ("left", "right"))
def test_a_close_up_beside_a_graphic_keeps_his_shoulders_in_his_column(
        reg, graphic_side):
    """A two-shot gives him 44% of a 16:9 frame. At the full-frame head size
    his shoulders are wider than that, and the graphic is drawn over one of
    them — so in a column the close-up is framed at the loose end of the
    kit's band, and his ink stays on his side of the split."""
    from PIL import Image

    from pipeline.compose import CLOSE_UP_IN_COLUMN_FH, TWO_SHOT_GRAPHIC

    assert 0.42 <= CLOSE_UP_IN_COLUMN_FH <= 0.56, "outside the kit's own band"
    fw, fh = 1920, 1080
    gw = int(fw * TWO_SHOT_GRAPHIC)
    col_x, col_w = (gw, fw - gw) if graphic_side == "left" else (0, fw - gw)

    shot = _framing(reg, "host/close-up")
    placed = frame_shot(shot, (fw, fh), head_fh=CLOSE_UP_IN_COLUMN_FH,
                        centre_fw=(col_x + col_w / 2) / fw)
    img = Image.open(shot.pose.frame_paths()[0]).convert("RGBA")
    x0, _, x1, _ = img.getchannel("A").getbbox()
    k = placed.width / img.width
    left, right = placed.x + x0 * k, placed.x + x1 * k
    if graphic_side == "left":
        assert left >= col_x - 2, f"his shoulder crosses into the graphic by {col_x - left:.0f}px"
    else:
        assert right <= col_x + col_w + 2, f"his shoulder crosses into the graphic by {right - col_w:.0f}px"


def test_a_room_that_refuses_a_host_places_nobody(reg):
    """`hostAnchor: false` is DATA. The camera is above the desk on
    `desk-top-down` and square to the board on `board`: neither has a floor
    in shot and both say so in the field rather than leaving it out. Reading a refusal as an omission is how a renderer ends up
    compositing a man onto a surface the camera is above."""
    from pipeline.host import HostPlacementError, stands_on

    figure = shots(reg, "beat")[0]
    for key in ("room/desk-top-down-16x9", "room/board-16x9"):
        room = reg.require(key)
        assert room.refuses_host
        assert not stands_on(room, figure)
        with pytest.raises(HostPlacementError, match="nobody stands here"):
            place_on_room(room, figure)


def test_nothing_in_the_placement_chain_returns_nothing(reg):
    """EVERY BUG IN THIS CHAIN WAS THE SAME SHAPE.

    Something returned None and the caller improvised: a head fitted into a
    body-sized anchor, a two-shot composed on flat ground, a wardrobe that was
    unreachable by name. None of the three failed a render and none of them
    was visible until somebody watched a frame.

    So the contract is that they raise, and this is that contract — asserted
    on the three signatures rather than on one example of each, because the
    next one of these will be a function somebody adds.
    """
    import inspect

    from pipeline.host import frame_shot, place_on_room
    from pipeline.plates import Registry

    for fn in (place_on_room, Registry.room_for):
        ret = inspect.signature(fn).return_annotation
        assert "None" not in str(ret), (
            f"{fn.__qualname__} may return None again — a caller will "
            f"improvise, and the frame will still get drawn")
    # `frame_shot` is the exception that proves it: it answers a question
    # ("is this a framing?") the caller is allowed not to know the answer to.
    assert "None" in str(inspect.signature(frame_shot).return_annotation)


def test_a_registry_with_no_wardrobe_block_is_refused(tmp_path):
    """It reads as a kit that declares no outfits and it is a stale build.

    `roles.json` has always carried the block; an ingest that does not stamp
    it wrote `{}`, which reads exactly like a kit with one outfit.
    """
    import json
    import shutil

    from pipeline.plates import PlateError, REGISTRY_NAME, load_plates

    src = Settings(_env_file=None).assets_dir / "plates"
    dest = tmp_path / "plates"
    dest.mkdir(parents=True)
    raw = json.loads((src / REGISTRY_NAME).read_text(encoding="utf-8"))
    raw.pop("wardrobe")
    (dest / REGISTRY_NAME).write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(PlateError, match="wardrobe"):
        load_plates(tmp_path)


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


# --------------------------------------------------------------------------
# A room with no floor. The substitution has to change the KIND of shot.
# --------------------------------------------------------------------------


def test_the_fallback_for_a_floorless_room_is_always_a_framing(reg):
    """`to-camera` is asked for a camera distance, not for its next member.

    Twelve rooms declare `hostAnchor: false` — the camera is above the desk, or
    square to a wall of index cards — and a beat that lands in one survives as a
    shot of his face or not at all. Both callers used to ask the `to-camera`
    role for a pose and take what came back, which was the same question only
    while that role served nothing but the two framings.

    delta-15 added `host/sitting-at-desk` to it: a cut-out, `floorLineY: 1728`,
    no `framing`. From then on the fallback could answer with a figure that
    still has to stand somewhere — swapping one unplaceable pose for another,
    and reading as handled because a swap had happened.
    """
    for i in range(len(reg.host_roles.get("to-camera", ())) + 3):
        shot = pick_framing(reg, "to-camera", i)
        assert shot is not None, "the kit ships two framings; one must come back"
        assert shot.is_framing, (
            f"{shot.key} has a floor line — it cannot stand in a room that "
            f"declares it has no floor")


def test_the_seeded_picker_agrees_with_the_stepped_one(reg):
    """`compose` picks by seed and `render_long` by index; both must filter.

    Two call sites, two pickers, one rule — and the rule is the kit's own
    answer about the plate rather than the shape of the role.
    """
    for seed in ("EXMPL", "AAPL", "", "ch11-short-interest-open"):
        pose = reg.framing_for("to-camera", seed=seed)
        assert pose is not None
        assert not pose.floor_line_y, f"{pose.key} is a cut-out, not a framing"


def test_a_role_that_serves_no_framing_says_so_rather_than_guessing(reg):
    """`None` is a real answer: this kit cannot shoot that beat.

    Returning some cut-out instead is how the bug being fixed here worked.
    """
    assert pick_framing(reg, "rests-on") is None or \
        pick_framing(reg, "rests-on").is_framing
    assert reg.framing_for("no-such-role-in-any-kit") is None
    assert pick_framing(reg, "no-such-role-in-any-kit") is None


# --------------------------------------------------------------------------
# The face — one plan for both lanes: talk by mouth shape, idle, blink.
# --------------------------------------------------------------------------


def _strip_frame(reg, face):
    return reg.require(face.key).frames[face.index]


def test_every_pose_carries_its_four_strips(reg):
    """ONE CONSTRUCTOR. The blink was in none of the five places that used to
    build a shot, which is how the kit shipped a blink for every pose and no
    frame of any video ever closed his eyes."""
    for key in reg.host_poses:
        shot = host_shot(reg, key)
        assert shot is not None, key
        assert shot.idle is not None, f"{key} has no idle strip"
        assert shot.blink is not None, f"{key} has no blink strip"
        talks = reg.host_poses[key].get("talks", True)
        assert (shot.talk is not None) == talks, key


def test_the_mouth_is_read_off_the_frame_not_its_position(reg):
    """The rebuild put the CLOSED mouth first in the talk strip, where the kit
    before it put the open one. A player that took `talk[0]` as "open" mouths
    every word shut, so every talking frame has to be one that says
    `mouthOpen` — and a sentence plays both of them, mid and wide."""
    shot = host_shot(reg, "host/to-camera")
    plan, did = face_plan(shot, words((0.0, 3.0)), 0.0, 3.0, 30, seed="t")
    talking = [f for f in plan if f.key == shot.talk.key]
    opens = {f.index for f in talking if _strip_frame(reg, f).mouth_open}
    assert did["talk_frames"] > 0 and len(opens) >= 2, \
        "a sentence swaps one open mouth, not the strip's two"
    for f in plan:
        if f.key == shot.talk.key and f.index == 0:
            assert not _strip_frame(reg, f).mouth_open


def test_a_long_silence_plays_the_idle_and_a_short_one_holds(reg):
    shot = host_shot(reg, "host/to-camera")
    fps = 30
    gap = IDLE_MIN_SPAN_S + 0.5
    plan, did = face_plan(shot, words((0.0, 1.0), (1.0 + gap, 2.0 + gap)),
                          0.0, 2.0 + gap, fps, seed="t")
    mid = plan[int((1.0 + gap / 2) * fps)]
    assert mid.key == shot.idle.key, "a long silence held the still"
    assert did["idle_frames"] > 0

    plan, _ = face_plan(shot, words((0.0, 1.0), (1.3, 2.3)), 0.0, 2.3, fps,
                        seed="t")
    assert plan[int(1.15 * fps)].key != shot.idle.key, \
        "a breath between two words cut to the idle"


def test_a_close_up_never_holds_its_still(reg):
    """design's crop review (ANSWERS.md §4, finding 2): the closed mouth is a
    filled bar, a mouth at full figure and a dash at close-up scale. "Cut
    close on -talk or -idle, where the mouth shapes cycle." So no frame of a
    close-up is the still, however short the gap it falls in."""
    shot = host_shot(reg, "host/close-up")
    for spans in (((0.0, 1.0), (1.3, 2.3)),          # a breath
                  ((0.5, 1.0),),                     # silence either side
                  ()):                               # not a word at all
        plan, did = face_plan(shot, words(*spans), 0.0, 3.0, 30, seed="c")
        assert did["held_frames"] == 0, f"{spans}: held the still"
        assert all(f.key != shot.pose.key for f in plan)


def test_he_blinks_and_never_mid_word(reg):
    """Every three to six seconds, for a tenth of a second, on the blink
    strip's shut-eyes drawing — and only over a closed mouth, where people do
    blink, never on an open one, where it reads as a dropped frame."""
    shot = host_shot(reg, "host/to-camera")
    fps = 30
    plan, did = face_plan(shot, words((0.0, 12.0)), 0.0, 12.0, fps,
                          seed="b")
    assert 2 <= did["blinks"] <= 4, f"{did['blinks']} blinks in twelve seconds"
    shut = [i for i, f in enumerate(plan) if f.key == shot.blink.key]
    assert shut, "no frame closed his eyes"
    for i in shut:
        assert _strip_frame(reg, plan[i]).eyes == "closed"
    is_open = mouth_schedule(words((0.0, 12.0)), 0.0, 12.0, fps)
    assert not any(is_open[i] for i in shut), "he blinked over an open mouth"
    runs, run = [], 1
    for a, b in zip(shut, shut[1:]):
        if b == a + 1:
            run += 1
        else:
            runs.append(run)
            run = 1
    runs.append(run)
    assert set(runs) == {max(int(round(BLINK_S * fps)), 1)}


def test_two_shots_do_not_blink_in_lockstep(reg):
    shot = host_shot(reg, "host/to-camera")
    a, _ = face_plan(shot, words((0.0, 12.0)), 0.0, 12.0, 30, seed="one")
    b, _ = face_plan(shot, words((0.0, 12.0)), 0.0, 12.0, 30, seed="two")
    blink = shot.blink.key
    assert ([i for i, f in enumerate(a) if f.key == blink]
            != [i for i, f in enumerate(b) if f.key == blink])


# --------------------------------------------------------------------------
# The room's front layer — he stands between the room and its desk.
# --------------------------------------------------------------------------


def test_a_room_with_a_desk_in_front_ships_it_as_a_layer(reg):
    from pipeline.host import front_of

    room = reg.require("room/desk-front-16x9")
    front = front_of(room)
    assert front is not None and front.exists()
    assert front_of(None) is None
    assert front_of(reg.require("room/board-16x9")) is None


def test_the_front_is_painted_after_him():
    """Pasting him over the whole room put the desk behind his legs."""
    from PIL import Image

    from pipeline.host import Placement, composite_on_room

    room = Image.new("RGBA", (100, 100), (255, 255, 255, 255))
    host = Image.new("RGBA", (40, 80), (255, 0, 0, 255))
    front = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    front.paste((0, 0, 255, 255), (0, 70, 100, 100))      # the desk
    composite_on_room(room, host, Placement(1.0, 30, 10, 40, 80), front=front)
    assert room.getpixel((50, 50))[:3] == (255, 0, 0), "he is not in the room"
    assert room.getpixel((50, 80))[:3] == (0, 0, 255), "the desk is behind him"


def test_compose_lays_the_desk_over_him_only_when_he_stands_there(reg):
    from types import SimpleNamespace

    from pipeline.compose import Layer, _front_layer

    shot = SimpleNamespace(id="s1")
    room = reg.require("room/desk-front-16x9")
    placed = (0, 0, 1920, 1080)
    standing = Layer(name="s1:host", kind="host", shot_id="s1", t_start=0.0,
                     t_end=2.0, entry_key="host/to-camera", z=40)
    front = _front_layer(reg, shot, room, placed, standing)
    assert front is not None and front.kind == "front"
    assert front.z > standing.z
    assert (front.x, front.y, front.w, front.h) == placed

    framed = Layer(name="s1:host", kind="host", shot_id="s1", t_start=0.0,
                   t_end=2.0, entry_key="host/close-up", z=40)
    assert _front_layer(reg, shot, room, placed, framed) is None
    chart = reg.require("tables/numbers-sheet-6r-16x9")
    assert _front_layer(reg, shot, chart, placed, standing) is None


def test_a_still_two_shot_never_takes_a_framing(reg):
    """The long's two-shot is one picture with him pasted in it, so a framing
    there is the still close-up the kit says never to hold."""
    assert pick_shot(reg, "to-camera", 0, figures_only=True) is None
    for i in range(len(shots(reg, "panel")) + 2):
        got = pick_shot(reg, "panel", i, figures_only=True)
        assert got is not None and not got.is_framing
