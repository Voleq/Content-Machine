"""The on-screen host: roles off the registry, the face, and the anchor.

The rig changed shape with the kit. The host is eighteen poses and one
framing, each four strips — the hold, `-talk` (six mouths since rebuild-31,
closed first), `-idle` (his weight settling) and `-blink` — and the frames say
what they are, so the player reads `mouthOpen` and `eyes` rather than a
frame's position. WHICH POSE
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
    CLOSE_CUE,
    CUES,
    IDLE_MIN_SPAN_S,
    MOUTH_CLOSED,
    MOUTH_HZ,
    available,
    beat_times,
    build_host_clip,
    cast_pose,
    cues_in,
    face_plan,
    frame_shot,
    host_shot,
    letter_mouth,
    mouth_frames,
    mouth_schedule,
    pick_framing,
    pick_shot,
    place_on_room,
    room_stem,
    shots,
    speaking_spans,
    word_mouths,
)
from pipeline.models import WordTimestamp
from pipeline.plates import Registry, load_plates
from pipeline.tts import mock_words

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


def said(text: str, seconds: float = 4.0) -> list[WordTimestamp]:
    """A line read by the proof voice: real words, timed wall to wall."""
    return mock_words(text, seconds)


# Twelve seconds of the kind of thing he says, for the face: every mouth the
# strip draws, lips that meet on m, b and p, and no pause long enough to idle.
READ = ("The company sells software to hospitals, and it has done so for "
        "twenty years without once raising its prices. Last quarter that "
        "changed. Revenue grew faster than it has in a decade, and the filing "
        "says why in a single sentence that most people will never read.")


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
# The mouth.
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
    """Open for a whole sentence is a puppet. The words move it: it changes
    shape with the letters and shuts on the m, b and p in them."""
    mouths = mouth_frames(said("Maybe the business will be fine, but maybe "
                               "not.", 3.0), 0.0, 3.0, 30)
    assert MOUTH_CLOSED in mouths[5:-5], "his lips never met mid-sentence"
    shapes = sum(1 for a, b in zip(mouths, mouths[1:]) if a != b)
    assert shapes >= 12, f"only {shapes} mouth changes across three seconds"


def test_each_letter_is_said_with_its_mouth():
    for letters, mouth in (("ouw", "mouthO"), ("eiy", "mouthEE"),
                           ("fv", "mouthFV"), ("mbp", MOUTH_CLOSED),
                           ("a", "mouthWide"), ("cdghjklnqrstxz", "mouthMid")):
        for ch in letters:
            assert letter_mouth(ch) == mouth, ch


def test_a_word_is_mouthed_as_it_is_said_rather_than_spelled():
    """A doubled letter is one sound, "ph" is an f, a final e after a
    consonant is silent, and a figure is said as the word it is."""
    assert word_mouths("moo") == [MOUTH_CLOSED, "mouthO"]
    assert word_mouths("phone") == ["mouthFV", "mouthO", "mouthMid"]
    assert word_mouths("move") == [MOUTH_CLOSED, "mouthO", "mouthFV"]
    assert word_mouths("Naïve,") == ["mouthMid", "mouthWide", "mouthEE",
                                     "mouthFV"]
    assert word_mouths("4%") == word_mouths("fourpercent")
    assert word_mouths("—") == [], "a dash is not said"


def test_a_word_that_starts_on_its_lips_shuts_them_and_then_says_the_rest(reg):
    """"moo" is lips together, then round: the talk strip's closed frame and
    then its O — found by the name each frame carries."""
    shot = host_shot(reg, "host/to-camera")
    moo = [WordTimestamp(word="moo", start=0.0, end=0.5, char_start=0,
                         char_end=3)]
    plan, did = face_plan(shot, moo, 0.0, 0.5, 30, seed="m")
    mouths = [shot.talk.frames[f.index].mouth for f in plan
              if f.key == shot.talk.key]
    assert mouths[0] == MOUTH_CLOSED and mouths[-1] == "mouthO", mouths
    assert did["mouths"] == [MOUTH_CLOSED, "mouthO"]


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
    `mouthOpen` — and a sentence plays more than one of them."""
    shot = host_shot(reg, "host/to-camera")
    plan, did = face_plan(shot, words((0.0, 3.0)), 0.0, 3.0, 30, seed="t")
    talking = [f for f in plan if f.key == shot.talk.key]
    opens = {f.index for f in talking if _strip_frame(reg, f).mouth_open}
    assert did["talk_frames"] > 0 and len(opens) >= 2, \
        "a sentence swaps one open mouth, not the strip's two"
    for f in plan:
        if f.key == shot.talk.key and f.index == 0:
            assert not _strip_frame(reg, f).mouth_open


def test_a_long_read_plays_every_open_mouth_the_strip_draws(reg):
    """rebuild-31 drew six mouths so that a long read no longer loops three
    shapes. The words reach every one of them, and none has to stand in."""
    shot = host_shot(reg, "host/to-camera")
    drawn = {i for i, f in enumerate(shot.talk.frames) if f.mouth_open}
    plan, did = face_plan(shot, said(READ, 12.0), 0.0, 12.0, 30, seed="t")
    played = {f.index for f in plan if f.key == shot.talk.key
              and shot.talk.frames[f.index].mouth_open}
    assert played == drawn
    assert did["mouths_stood_in"] == []


def _mouth_on(shot, face) -> str:
    """What his mouth is doing on one frame: a talk frame's own mouth, shut
    on the still and in a blink (both draw it closed), or the idle."""
    if shot.talk is not None and face.key == shot.talk.key:
        return shot.talk.frames[face.index].mouth
    if face.key in (shot.pose.key, shot.blink.key):
        return MOUTH_CLOSED
    return "idle"


def _runs(seq: list) -> list[tuple[object, int]]:
    out: list[tuple[object, int]] = []
    for x in seq:
        if out and out[-1][0] == x:
            out[-1] = (x, out[-1][1] + 1)
        else:
            out.append((x, 1))
    return out


@pytest.mark.parametrize("key", ("host/to-camera", "host/close-up"))
def test_no_mouth_is_held_for_less_than_a_strip_frame(reg, key):
    """Letters come far faster than a drawn mouth can change — "strengths" is
    nine of them in a third of a second — and a mouth swapped on each is a
    buzz. So every mouth, the blink's shut one included, stays up for at
    least one frame of the strip's own 8fps."""
    shot = host_shot(reg, key)
    fps = 30
    plan, did = face_plan(shot, said(READ, 12.0), 0.0, 12.0, fps, seed="h")
    assert did["blinks"] >= 1
    least = int(fps / MOUTH_HZ)
    runs = _runs([_mouth_on(shot, f) for f in plan])
    brief = [r for r in runs[1:-1] if r[1] < least]
    assert not brief, f"{key}: mouths held under a strip frame: {brief[:5]}"


def test_silence_shuts_the_mouth(reg):
    """Between sentences the mouth is shut or idling — never left open on
    the last letter said."""
    shot = host_shot(reg, "host/to-camera")
    line = said("Revenue fell.", 1.0) + [
        WordTimestamp(word=w.word, start=w.start + 3.0, end=w.end + 3.0,
                      char_start=0, char_end=0)
        for w in said("Then it rose.", 1.0)]
    plan, _did = face_plan(shot, line, 0.0, 4.0, 30, seed="s")
    for face in plan[int(1.3 * 30):int(2.9 * 30)]:
        assert _mouth_on(shot, face) in (MOUTH_CLOSED, "idle")


def _without(shot, *mouths: str):
    """The same pose with a talk strip that does not draw `mouths`."""
    import dataclasses

    talk = dataclasses.replace(
        shot.talk, frames=tuple(f for f in shot.talk.frames
                                if f.mouth not in mouths))
    return dataclasses.replace(shot, talk=talk)


def test_a_mouth_the_strip_does_not_draw_goes_to_the_nearest_one_it_does(reg):
    """A drop that loses the O must not stop him talking or cut to the
    still: the round mouth goes to the wide one, and the report says so."""
    shot = _without(host_shot(reg, "host/to-camera"), "mouthO")
    plan, did = face_plan(shot, said("Who owns you now?", 2.0), 0.0, 2.0, 30,
                          seed="o")
    assert did["mouths_stood_in"] == ["mouthO"]
    assert "mouthO" not in did["mouths"] and "mouthWide" in did["mouths"]
    assert did["talk_frames"] > 0


def test_a_close_up_missing_its_closed_mouth_never_shows_the_still(reg):
    """A figure's closed mouth IS his pose, so a figure whose strip lost it
    shuts on the still. A close-up may not — the still is the dash design
    says never to hold — so it takes the nearest drawn mouth instead."""
    line = said("Maybe the bump helps, maybe the problem is bigger.", 3.0)
    framed = _without(host_shot(reg, "host/close-up"), MOUTH_CLOSED)
    plan, did = face_plan(framed, line, 0.0, 3.0, 30, seed="c")
    assert MOUTH_CLOSED in did["mouths_stood_in"]
    assert all(f.key != framed.pose.key for f in plan)

    figure = _without(host_shot(reg, "host/to-camera"), MOUTH_CLOSED)
    plan, did = face_plan(figure, line, 0.0, 3.0, 30, seed="c")
    assert any(f.key == figure.pose.key for f in plan[5:-5]), \
        "a figure's m, b and p did not shut on his pose"


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
    blink, never on an open one, where it reads as a dropped frame: an open
    mouth, snapped shut for three frames, and the same mouth open again."""
    shot = host_shot(reg, "host/to-camera")
    fps = 30
    plan, did = face_plan(shot, said(READ, 12.0), 0.0, 12.0, fps, seed="b")
    assert 2 <= did["blinks"] <= 4, f"{did['blinks']} blinks in twelve seconds"
    shut = [i for i, f in enumerate(plan) if f.key == shot.blink.key]
    assert shut, "no frame closed his eyes"
    for i in shut:
        assert _strip_frame(reg, plan[i]).eyes == "closed"
    mouths = [_mouth_on(shot, f) for f in plan]
    for i in shut:
        if i + 1 < len(plan) and plan[i + 1].key != shot.blink.key:
            start = i
            while start > 0 and plan[start - 1].key == shot.blink.key:
                start -= 1
            before, after = mouths[start - 1] if start else "", mouths[i + 1]
            assert not (before == after and before not in (MOUTH_CLOSED,
                                                           "idle")), \
                f"he blinked mid-{before} at frame {start}"
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
    a, _ = face_plan(shot, said(READ, 12.0), 0.0, 12.0, 30, seed="one")
    b, _ = face_plan(shot, said(READ, 12.0), 0.0, 12.0, 30, seed="two")
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


# --------------------------------------------------------------------------
# Casting — six poses the words choose, on the angles design drew them for.
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def cast_reg() -> Registry:
    """The installed kit with roles.json's hostPoses, as the next ingest
    stamps them. A registry of its own, because the cached one is shared by
    every test in the run and casting reads fields an older install lacks."""
    import json

    fresh = Registry(Settings(_env_file=None).assets_dir / "plates")
    fresh.host_poses = json.loads(
        (ROOT / "kit" / "roles.json").read_text(encoding="utf-8"))["hostPoses"]
    return fresh


def _cast(cast_reg, text, room="room/desk-front-16x9", **kw):
    got = cast_pose(cast_reg, said(text), room=cast_reg.require(room),
                    seed=kw.pop("seed", "t"), **kw)
    return got.pose if got is not None else None


def test_three_reasons_count_on_his_fingers_where_design_drew_it(cast_reg):
    line = "There are three reasons this matters."
    assert _cast(cast_reg, line) == "host/counting-on-fingers"
    assert _cast(cast_reg, line, "room/window-wide-16x9") == \
        "host/counting-on-fingers"
    assert _cast(cast_reg, line, "room/desk-front-low-16x9") is None, \
        "design did not draw the count for the low desk angle"


def test_one_reason_or_three_percent_is_not_a_list(cast_reg):
    """design's caution: never for one item. And a count of a unit is a
    figure — the one thing a list pose must never be cut to."""
    for line in ("There is one reason this matters.",
                 "Margins rose three percent.",
                 "It took four years and two billion dollars."):
        assert "list" not in cues_in(said(line)), line
        assert _cast(cast_reg, line) is None, line


def test_a_clause_that_opens_on_but_shrugs_and_only_once_a_video(cast_reg):
    assert _cast(cast_reg, "Sales rose. But nobody knows why.") == "host/shrug"
    assert _cast(cast_reg, "Who knows what they will do next?") == "host/shrug"
    assert _cast(cast_reg, "Sales rose. But nobody knows why.",
                 used={"host/shrug-dusk": 1}) is None, \
        "the shrug is limit 1, at whichever hour it stood"


def test_small_but_growing_is_not_a_shrug(cast_reg):
    assert "doubt" not in cues_in(said("The business is small but growing."))


def test_a_citation_holds_up_the_filing(cast_reg):
    for line in ("It says so on page 96.", "Read the 10-K.",
                 "The annual report is blunter than the call."):
        assert _cast(cast_reg, line) == "host/holding-a-filing", line


def test_a_news_hook_takes_out_the_phone(cast_reg):
    for line in ("The price alert went off at four.",
                 "The headline said record quarter."):
        assert _cast(cast_reg, line) == "host/holding-a-phone", line


def test_the_close_takes_the_mug_and_never_on_a_number(cast_reg):
    line = "That is the whole story. Go to bed."
    assert _cast(cast_reg, line, closing=True) == "host/holding-a-mug"
    assert _cast(cast_reg, line, "room/desk-side-16x9",
                 closing=True) == "host/holding-a-mug"
    assert _cast(cast_reg, line) is None, "the mug is for the close only"
    assert _cast(cast_reg, "The stock trades at 14 times earnings.",
                 closing=True) is None, "a figure said over a sip of coffee"


def test_he_gestures_at_the_plate_only_when_it_is_camera_right_of_him(
        cast_reg):
    line = "Look at this chart."
    for room in ("room/panel-left-16x9", "room/board-side-16x9"):
        assert _cast(cast_reg, line, room, plate_on="camera-right") == \
            "host/gesturing-at-plate"
        assert _cast(cast_reg, line, room, plate_on="camera-left") is None
        assert _cast(cast_reg, line, room) is None, "gesturing at a wall"
    assert _cast(cast_reg, line, plate_on="camera-right") is None, \
        "design did not draw the gesture for the desk"


def test_a_pose_is_never_cast_on_an_angle_it_was_not_drawn_for(cast_reg):
    """Every cue at once, on every room the kit ships, at every seed: what
    comes back fits the room or nothing does."""
    line = ("Three reasons, but nobody knows. Page 96 of the filing. The "
            "alert. Look at this chart.")
    spoken = said(line, 8.0)
    fits = {k: set(v["fits"]) for k, v in cast_reg.host_poses.items()
            if v.get("castBy")}
    for key in cast_reg.family("room"):
        room = cast_reg.require(key)
        for seed in ("a", "b", "c"):
            got = cast_pose(cast_reg, spoken, room=room, closing=True,
                            plate_on="camera-right", seed=seed)
            if got is not None:
                assert room_stem(room) in fits[got.pose], (key, got)
                assert not room.refuses_host


def test_a_pose_from_a_recent_video_or_the_last_beat_is_not_cast_again(
        cast_reg):
    line = "There are three reasons this matters."
    assert _cast(cast_reg, line,
                 avoid={"host/counting-on-fingers-dusk"}) is None, \
        "back-to-back videos counted on the same fingers"
    assert _cast(cast_reg, line,
                 previous="host/counting-on-fingers") is None, \
        "two beats in a row cast the same pose"


def test_casting_reads_the_hour_the_episode_is_shot_at(cast_reg):
    dusk = cast_reg.at("dusk")
    got = cast_pose(dusk, said("There are three reasons."),
                    room=dusk.get("room/desk-front-16x9"), seed="d")
    assert got is not None and got.pose == "host/counting-on-fingers"
    assert dusk.get(got.pose).key.endswith("-dusk")


def test_nothing_said_or_nowhere_to_stand_casts_nothing(cast_reg):
    """Every refusal is today's casting, never a missing host."""
    room = cast_reg.require("room/desk-front-16x9")
    assert cast_pose(cast_reg, [], room=room, closing=True) is None, \
        "no words cannot vouch the close carries no number"
    line = said("There are three reasons.")
    assert cast_pose(cast_reg, line, room=None) is None
    assert cast_pose(cast_reg, line,
                     room=cast_reg.require("room/board-16x9")) is None
    assert cast_pose(cast_reg, line,
                     room=cast_reg.require("tables/numbers-sheet-6r-16x9")) \
        is None


def test_every_cast_pose_names_a_cue_this_module_reads_and_rooms_it_ships(
        cast_reg):
    rooms = {room_stem(cast_reg.require(k)) for k in cast_reg.family("room")}
    cast = {k: v for k, v in cast_reg.host_poses.items() if v.get("castBy")}
    assert len(cast) == 6
    for key, spec in cast.items():
        assert spec["castBy"] in {*CUES, CLOSE_CUE}, key
        assert set(spec["fits"]) <= rooms, f"{key} fits a room the kit lacks"
        assert cast_reg.get(key) is not None and cast_reg.get(key).floor_line_y


def _one_host_shot(pose: str, plate: str, aspect: str = "16x9"):
    from pipeline.shots import parse_format

    w, h = (1920, 1080) if aspect == "16x9" else (1080, 1920)
    return parse_format({
        "format": "cast", "aspect": aspect, "frame": {"w": w, "h": h},
        "shots": [{"id": "the-beat", "plate": plate,
                   "host": {"pose": pose, "slot": "host-anchor"}}]})


class _NoText:
    def text_for(self, src):
        return None

    def image_for(self, src):
        return None

    def list_for(self, src):
        return []


def _host_in(result) -> str:
    return next(layer.entry_key for layer in result.layers
                if layer.kind == "host")


def test_compose_casts_a_role_from_its_words_and_keeps_the_role_without(
        cast_reg):
    from pipeline.compose import build_layers
    from pipeline.shots import resolve_spans

    fmt = _one_host_shot("beat", "room/desk-front-16x9")
    line = said("There are three reasons this matters.")
    spans = resolve_spans(fmt, line, 4.0, {})
    cast = build_layers(fmt, spans, _NoText(), cast_reg, aspect="16x9",
                        seed="s", words=line)
    assert _host_in(cast) == "host/counting-on-fingers"
    plain = build_layers(fmt, spans, _NoText(), cast_reg, aspect="16x9",
                         seed="s")
    assert _host_in(plain) in cast_reg.host_roles["beat"], \
        "without words he is cast by his role, as before"

    named = _one_host_shot("host/to-camera", "room/desk-front-16x9")
    got = build_layers(named, resolve_spans(named, line, 4.0, {}), _NoText(),
                       cast_reg, aspect="16x9", seed="s", words=line)
    assert _host_in(got) == "host/to-camera", "a pose named by key is chosen"


def test_no_vertical_template_stands_him_where_a_pose_could_be_cast(
        cast_reg):
    """The 9:16 finding. A short's only host is the turn, which names the
    close-up by key: a framing, and a pose the template chose. So nothing in
    a vertical video is cast; a template that stands him up by role is where
    that changes, and this test with it."""
    from pipeline.shots import available_formats, load_format

    for name in available_formats():
        fmt = load_format(name)
        if fmt.aspect != "9x16":
            continue
        for shot in fmt.shots:
            if shot.host:
                pose = cast_reg.get(shot.host.pose)
                assert pose is not None and not pose.floor_line_y, (
                    f"{name}/{shot.id} stands him up by role — casting now "
                    f"reaches the {name}")
