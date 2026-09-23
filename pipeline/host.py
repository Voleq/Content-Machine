"""Dennis on screen — a cut-out placed on the room, flapped to the voice-over.

The kit draws twelve poses and one framing, and each is four strips: the pose
itself (one frame, a hold); ``-talk``, three frames whose mouths are closed,
mid and wide; ``-idle``, three frames that settle his weight a canvas unit up
and down; and ``-blink``, open eyes then closed. The frames say what they are
— ``mouthOpen``, ``eyes``, ``bob`` — and this module reads that rather than a
frame's position, because the rebuild reordered the talk strip: its FIRST
frame is the closed mouth now, where the kit before it put the open one there,
and a player that took ``talk[0]`` as "open" would have mouthed every word
shut. Talking is frame swapping, and the swap schedule comes from the
voice-over word timestamps — ``tts.words``, the same master clock every other
cue reads. :func:`face_plan` is the one place that decides which frame of
which strip is on screen, and both lanes ask it.

WHICH POSE SERVES WHICH SHOT COMES OFF THE REGISTRY, not out of a list here.
``kit/roles.json`` declares the roles (open, beat, panel, close) and which poses
fill them, and ingest stamps that into the registry. A new kit with a different
set of poses drops in by shipping its own ``roles.json`` and no Python changes —
which is the test the previous version failed: ``HOST_BANKS`` named twenty
specific v1 asset paths, so the kit could not be replaced without editing this
file.

The registry also carries what a pose may DO. ``head-in-hands`` and
``walking-out-of-frame`` ship talk frames for continuity of the file set and
declare ``talks: false``, because using them looks like a mistake; and
``head-in-hands`` declares ``limit: 1``, because it is the cost of being right
and not a reaction to a mild loss. Both are honoured from the declaration.

PLACEMENT IS THE ANCHOR CONTRACT, and it is the one thing here that is silently
wrong if approximated. A room declares ``floorLineY`` and a ``host-anchor``
region. The region's HEIGHT is the host's target height:

    scale so that (host.floorLineY - host.slots.figure.y) == anchor.h
    then sit the host's floorLineY on the anchor's bottom edge

Never scale to the anchor's WIDTH, and never to the figure box's height. The
figure box runs past the floor line to carry the shoes, and it includes the arms,
which are meant to pass the anchor. Both mistakes put him at a plausible-looking
size that is wrong by ten to twenty percent, standing slightly above or below the
floor — which reads as a bad composite rather than as an error.

In the rebuild every pose is drawn in ONE standing box, 400 by 720 canvas units
(DESIGN.md §2.5), so the figure box is the whole plate and its floor line is its
bottom edge: the rule above comes out as "the box fills the anchor's height, its
top on the anchor's top", which is design's own wording of it. The seated pose
is in the same box and scales like the rest.

A ROOM IS TWO LAYERS AND HE STANDS BETWEEN THEM. The desk he stands behind is
drawn after him, not under him: :func:`front_of` is the room's front layer, and
whoever composites him on a room paints it after him. Pasting him over the whole
room put the desk behind his legs on every angle that has one in front of him.

Everything degrades to ``None`` when the registry cannot supply a pose, so a
render never fails for want of a host — but the SHORT engine treats that as an
error rather than a shrug, because a short with no host is the bug this replaced.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from pathlib import Path

from pipeline.plates import Plate, Registry
from pipeline.models import WordTimestamp

log = logging.getLogger(__name__)

# Frames per second the mouth is allowed to change. Real speech flaps at
# roughly this rate; faster reads as a buzz, slower as a puppet.
FLAP_HZ = 7.0

# A gap this long between words reads as a sentence break — where the shot is
# allowed to settle without looking twitchy.
BEAT_GAP_S = 0.32

# --------------------------------------------------------------------------
# Micro-motion.
#
# Over forty minutes the face is the most-viewed element in the channel, and a
# host who only ever opens and shuts his mouth reads as a still with a mouth
# cut into it. So a beat has four things to play, all off the registry by
# naming convention exactly the way `-talk` is: the talk strip under words,
# the idle strip in silence, a blink every few seconds, and the pose itself as
# the hold between. There is no boil any more — §6 of the rebuild removed it —
# so a hold is one frame, and the idle strip is what keeps a silence alive.
#
# Everything degrades to the hold when a pose ships no strip: nothing in this
# file may raise or block a render for want of a face.
# --------------------------------------------------------------------------

# How often a face blinks. Real resting rate is every 3-6 seconds, and the
# interval is redrawn per blink so it never falls into a rhythm.
BLINK_EVERY_S = (3.0, 6.0)

# How far a scheduled blink may be nudged to find a closed-mouth run long
# enough to hold it. One that cannot is dropped rather than forced onto an
# open mouth, which reads as a dropped frame.
BLINK_SEARCH_S = 0.9

# How long the eyes stay shut. A real blink is a tenth of a second or a little
# more; the kit's strip plays at 4fps, which would hold them shut for a quarter
# of a second and read as a slow, tired close. So the length is set in time and
# the strip only supplies the drawing.
BLINK_S = 0.1

# A non-speaking span at least this long is somewhere the idle strip plays.
# Shorter than this and the shift is over before it registers.
#
# It fires on real silence only, and that is the most the artwork contract
# allows: an `-idle` frame is a whole composed frame, so playing one sets the
# mouth too, and it cannot run under a flap.
#
# Worth knowing before wondering why a fixture render reports `idle_frames:
# 0`: MOCK WORD TIMINGS ARE WALL TO WALL. Measured on the sample long, the
# twelve host segments hold 67s of host time between them and contain 0.16s
# of non-speaking time in total — not one span reaches this threshold. Real
# TTS alignment returns gaps at punctuation and at the [BEAT] tags the script
# grammar exists to place, and the idle plays in those. The same mock
# flatness makes `beat_times` return nothing, which is worth fixing in the
# mock rather than working around here.
IDLE_MIN_SPAN_S = 1.8

# The idle strip loops at this rate when it does not publish its own: a slow
# shift of weight, not a fidget. The rebuild's idle strips all say 4fps.
IDLE_HZ = 3.0

# The shot banks. Every entry is a kit key whose ``-talk`` twin exists, so the
# host is always lip-synced rather than a still with subtitles.
#
# `open`  he is talking to camera before the evidence starts
# `close` he is talking to camera after the payoff
# `panel` the two-shot: him beside the thing being discussed
# `beat`  a mid-video return to his face
@dataclass(frozen=True)
class HostShot:
    """One pose, as the four strips a beat plays: hold, talk, idle, blink."""

    pose: Plate                     # the pose itself — a hold, and the cut frame
    talk: Plate | None = None       # closed, mid, wide mouths; None when talks=false
    idle: Plate | None = None       # the weight settling, a canvas unit each way
    blink: Plate | None = None      # eyes open, then shut

    @property
    def key(self) -> str:
        return self.pose.key

    @property
    def floor_line_y(self) -> int:
        return int(self.pose.floor_line_y or self.pose.canvas[1])

    @property
    def is_framing(self) -> bool:
        """Whether this is a camera DISTANCE rather than a figure in a room.

        `close-up` publishes `floorLineY: false`: it is a head-and-shoulders
        window on him, so there is no floor line to pin and no anchor to solve
        it onto. A framing IS the shot. Treating one as a cut-out puts a
        disembodied head standing on a desk.
        """
        return not self.pose.floor_line_y


def host_shot(reg: Registry, pose: Plate | str | None) -> HostShot | None:
    """A pose with every strip the kit draws for it. None if there is no pose.

    ONE CONSTRUCTOR, because there used to be five — in this module, the long
    renderer, the compositor and the tests — each building a `HostShot` out of
    the strips it happened to remember. The blink was in none of them, which
    is how the kit shipped a blink for every pose and no frame of any video
    ever closed his eyes.
    """
    if isinstance(pose, str):
        pose = reg.get(pose)
    if pose is None:
        return None
    return HostShot(pose=pose,
                    talk=reg.host_strip(pose.key, "talk"),
                    idle=reg.host_strip(pose.key, "idle"),
                    blink=reg.host_strip(pose.key, "blink"))


def shots(reg: Registry, role: str = "open") -> list[HostShot]:
    """Every usable pose for a shot role, in the order the registry declares.

    A pose that declares ``talks: false`` still appears — it is a perfectly good
    hold — but its talk strip is None, so a speaking beat will not choose it.
    """
    out: list[HostShot] = []
    for key in reg.host_roles.get(role, ()):
        shot = host_shot(reg, key)
        if shot is None:
            log.debug("host role %s names %s, which the kit does not ship", role, key)
            continue
        out.append(shot)
    return out


def pick_shot(reg: Registry, role: str, index: int = 0, *,
              speaking: bool = False, used: dict[str, int] | None = None,
              figures_only: bool = False) -> HostShot | None:
    """The `index`-th pose of a role, wrapping.

    Stepping rather than hashing: consecutive host beats in one video must not
    repeat, and a counter guarantees that where a hash only makes it likely.

    `used` carries how often each pose has already appeared, so a pose that
    declares a ``limit`` is not chosen past it. head-in-hands is capped at one
    per video by the kit itself: it is the cost of being right, and a second one
    turns it into a running joke.

    `figures_only` is for a shot that will hold him STILL: a framing held
    still is the closed mouth at close-up scale, which reads as a dash
    (ANSWERS.md §4, finding 2), so a still never takes one.
    """
    bank = [s for s in shots(reg, role)
            if (not speaking or s.talk is not None)
            and not (figures_only and s.is_framing)]
    if used:
        allowed = []
        for shot in bank:
            cap = reg.host_limit(shot.key)
            if cap is not None and used.get(shot.key, 0) >= cap:
                continue
            allowed.append(shot)
        bank = allowed or bank
    if not bank:
        return None
    return bank[index % len(bank)]


def pick_framing(reg: Registry, role: str = "to-camera", index: int = 0, *,
                 used: dict[str, int] | None = None) -> HostShot | None:
    """The `index`-th FRAMING a role serves, or None if it serves none.

    For the one situation that needs a camera distance rather than a figure:
    a room that declares ``hostAnchor: false`` has no floor to stand anybody
    on, so the beat survives as a shot of his face or it does not survive.

    Asking `pick_shot` for a `to-camera` pose and using whatever comes back is
    the same call ONLY while that role serves nothing but framings. It stopped
    being true in delta-15, which added `host/sitting-at-desk` — a cut-out with
    a floor line — to the role, so a caller could swap an unplaceable pose for
    another unplaceable pose and look like it had handled the case.

    A role is curation and can gain a member in any drop. `is_framing` is the
    kit's own answer, off `floorLineY`, so this filters on the property rather
    than trusting the role to keep its shape across a delivery.
    """
    bank = [s for s in shots(reg, role) if s.is_framing]
    if used:
        allowed = [s for s in bank
                   if (cap := reg.host_limit(s.key)) is None
                   or used.get(s.key, 0) < cap]
        bank = allowed or bank
    if not bank:
        return None
    return bank[index % len(bank)]


def available(reg: Registry, role: str = "open") -> bool:
    """True when the registry can supply a pose for this role."""
    return bool(shots(reg, role))


# --------------------------------------------------------------------------
# Placement — the anchor contract.
# --------------------------------------------------------------------------
class HostPlacementError(Exception):
    """The host cannot be placed, and improvising is worse than stopping.

    Everything in this module used to degrade to None so a render never failed
    for want of a host. That is the right instinct for a MISSING pose and the
    wrong one for a placement that cannot be solved: the frame still gets
    drawn, with him at a size and a position nobody chose.
    """


@dataclass(frozen=True)
class Placement:
    """Where a host cut-out goes on a room, in DELIVERED pixels."""

    scale: float
    x: int                      # left edge of the scaled host plate
    y: int                      # top edge of the scaled host plate
    width: int
    height: int


def stands_on(room: Plate, host: HostShot) -> bool:
    """Whether this pose is a cut-out this room has a floor for.

    The two DECLARED cases, both of which are data rather than a failure:

    * `room.refuses_host` — `room/high-desk-down` is the camera above the desk
      and `room/wall-of-calls` is a wall of index cards. Neither has a floor
      in shot, and both say so in the field rather than leaving it out.
    * `host.is_framing` — a close-up is a camera distance, not a cut-out.
      There is no floor line on it to pin.

    A caller asks this and then places him, or frames him, or leaves him out.
    """
    return not room.refuses_host and not host.is_framing


def place_on_room(room: Plate, host: HostShot) -> Placement:
    """Solve the host onto a room's ``host-anchor``. Raises rather than shrugs.

    The anchor's HEIGHT is the target: scale so that
    ``(host.floorLineY - figure.y)`` equals it, then sit the host's floor line
    on the anchor's bottom edge.

    Never the anchor's width — the figure box includes the arms, which are meant
    to pass it, so fitting the width makes him small and puts his feet in the
    air. Never the figure box's own height either: the box runs past the floor
    line to carry the shoes, so matching it sinks him into the floor by the
    height of his feet. Both are ten-to-twenty-percent errors that read as a bad
    composite rather than as a bug, which is why the rule is written on the
    plate and repeated here.

    THIS USED TO RETURN NONE AND THE CALLERS IMPROVISED. A close-up handed to
    it came back as nothing, and the caller fitted a head into a body-sized
    anchor; a room with no anchor came back as nothing, and the caller stood
    him at a guessed column. Both read as compositing bugs and neither was
    visible until somebody watched the frame. Every one of those is a caller
    that should have asked `stands_on` first, so every one of them is a raise
    now and shows up on the first render.
    """
    if not stands_on(room, host):
        raise HostPlacementError(
            f"{host.key} cannot stand on {room.key}: "
            + ("the room declares hostAnchor: false — nobody stands here"
               if room.refuses_host else
               f"{host.key} is a {host.pose.framing or 'framing'}, a camera "
               f"distance with no floor line — frame it with `frame_shot`")
            + ". Ask `stands_on` before placing.")
    anchor = room.slot("host-anchor")
    figure = host.pose.slot("figure")
    if anchor is None:
        raise HostPlacementError(
            f"{room.key} declares neither a host-anchor nor `hostAnchor: "
            f"false` — `Registry.verify` refuses that, so this registry is "
            f"stale: re-run `python scripts/ingest_kit.py kit`")
    if figure is None:
        raise HostPlacementError(
            f"{host.key} has no `figure` slot, so there is nothing to measure "
            f"his standing height from")

    # Everything in DELIVERED pixels from here. Mixing canvas units and
    # delivered pixels in this calculation is the exportScale trap the manifest
    # warns about, and it comes out as a host at exactly half or double his
    # intended size — on a composite that otherwise looks entirely plausible.
    hs = host.pose.export_scale
    standing = (host.floor_line_y - figure.y) * hs   # delivered px, host plate
    if standing <= 0:
        raise HostPlacementError(
            f"{host.key}: floorLineY {host.floor_line_y} is at or above the "
            f"figure box's top ({figure.y}) — he has no height to scale")

    ax, ay, aw, ah = anchor.scaled()                 # delivered px, room plate
    scale = ah / standing

    width = int(round(host.pose.delivered[0] * scale))
    height = int(round(host.pose.delivered[1] * scale))

    # Sit his floor line on the anchor's bottom edge.
    floor_px = host.floor_line_y * hs * scale
    y = int(round(ay + ah - floor_px))
    # WHERE HE STANDS LATERALLY. The anchor's width is advisory — it says how
    # much lateral room he has, and it never decides his size — so on its own
    # he is centred in it, which on a wide angle is a man standing in open
    # floor beside a desk he is not touching.
    #
    # Twelve room plates publish a `contact` point: which pose makes contact at
    # this angle, what he is touching, and where his hand lands. His own rig
    # publishes `forearmY` but no forearm X, so what this can do soundly is put
    # him AT the furniture rather than beside it: his figure box is centred on
    # the contact point. The height rule above is untouched — the anchor
    # decides his size, and nothing here is allowed to argue with it.
    contact = room.host_contact
    if contact.get("x") is not None:
        fig_mid = (figure.x + figure.w / 2) * hs * scale
        x = int(round(float(contact["x"]) * room.export_scale - fig_mid))
    else:
        x = int(round(ax + (aw - width) / 2))
    return Placement(scale=scale, x=x, y=y, width=width, height=height)


# A FRAMING IS PLACED ON THE EYE LINE. The head is the fraction of frame
# height the shot wants; the eye line sits on the frame's upper third. Both
# numbers are the kit's, and the plate carries them.
CLOSE_UP_HEAD_FH = 0.49         # the kit's band is 0.42-0.56: this is its centre
EYE_LINE_FH = 1.0 / 3.0


def frame_shot(host: HostShot, frame: tuple[int, int], *,
               head_fh: float = 0.0,
               centre_fw: float = 0.5) -> Placement | None:
    """Place a framing against the FRAME. None if this pose is not one.

    `close-up` is a camera distance. It has no floor line and no anchor to
    solve onto, and the plate is explicit about what it takes instead: scale
    so `slots.head` is the fraction of frame height the shot wants, then put
    `fit.eyeLineY` on the frame's upper third.

    THE WIDTH IS NOT A BOUND. A framing may run off the left and right edges
    by design — cropping to the width re-frames the shot into something
    narrower than what was drawn — so `x` here may be negative and `x + width`
    may pass the frame's right edge. `centre_fw` moves his head, not his
    bounding box: in a two-shot he sits at a third and the graphic takes the
    rest.
    """
    if not host.is_framing:
        return None
    head = host.pose.slot("head")
    fit = host.pose.fit or {}
    if head is None or not fit.get("eyeLineY"):
        return None

    fw, fh = frame
    hs = host.pose.export_scale
    scale = (fh * (head_fh or CLOSE_UP_HEAD_FH)) / max(head.h * hs, 1)

    width = int(round(host.pose.delivered[0] * scale))
    height = int(round(host.pose.delivered[1] * scale))
    # His eyes on the upper third, and his head — not the plate — on centre_fw.
    y = int(round(fh * EYE_LINE_FH - float(fit["eyeLineY"]) * hs * scale))
    # NEVER FLOAT THE CROP. The window cuts him across the chest, so its bottom
    # edge has to be at or below the frame's — a framing lifted to put its eye
    # line on the third would otherwise draw a straight cut across him in the
    # middle of the picture. So the crop may go DOWN to reach the bottom, and
    # never up.
    #
    # This line said `min` and did the opposite. A crop taller than the space
    # under the eye line was pulled UP until its bottom sat on the frame's,
    # which is harmless while the crop is short and, on the rebuild's close-up
    # (a window that runs well past the frame), lifted his eyes off the top of
    # a 16:9 picture: the one shot whose whole point is his face.
    y = max(y, fh - height)
    head_mid = (head.x + head.w / 2) * hs * scale
    x = int(round(fw * centre_fw - head_mid))
    return Placement(scale=scale, x=x, y=y, width=width, height=height)


def front_of(room: Plate | None) -> Path | None:
    """The part of a room that stands IN FRONT of him, or None.

    A rebuild room is two layers split where he stands — `back` is the wall
    and everything on it, `front` is the desk and what is on the desk — and
    the base file is both at once, for a shot with nobody in it. So a man
    stands on a room as: the room, then him, then this. Painting the front
    again over the base is a no-op everywhere he is not, which is why the
    back layer is never needed on its own.

    None on a room drawn in one piece, and on a room whose front file is
    missing: `Registry.verify` reports that, and a render without a desk in
    front of him is a smaller wrong than a render that stops.
    """
    if room is None:
        return None
    path = room.layer_path("front")
    return path if path is not None and path.exists() else None


def composite_on_room(room_img, host_img, placement: Placement, *,
                      front=None):
    """Paste a scaled host cut-out onto a room frame, in place.

    `front` is the room's front layer at the room frame's size, when it has
    one (:func:`front_of`): it goes on after him, so the desk he stands behind
    is in front of his legs rather than behind them.
    """
    from PIL import Image

    scaled = host_img.convert("RGBA").resize(
        (max(placement.width, 1), max(placement.height, 1)), Image.LANCZOS)
    room_img.alpha_composite(scaled, (placement.x, placement.y))
    if front is not None:
        layer = front.convert("RGBA")
        if layer.size != room_img.size:
            layer = layer.resize(room_img.size, Image.LANCZOS)
        room_img.alpha_composite(layer)
    return room_img


def speaking_spans(words: list[WordTimestamp], start: float,
                   end: float) -> list[tuple[float, float]]:
    """The [start, end) windows inside the segment where a word is sounding."""
    spans: list[tuple[float, float]] = []
    for w in words:
        a, b = max(w.start, start), min(w.end, end)
        if b > a:
            if spans and a - spans[-1][1] < 1e-3:
                spans[-1] = (spans[-1][0], b)
            else:
                spans.append((a, b))
    return spans


def mouth_schedule(words: list[WordTimestamp], start: float, end: float,
                   fps: int) -> list[bool]:
    """True on every output frame where the mouth should be open.

    Open while a word is sounding, alternating with closed at :data:`FLAP_HZ`
    so the mouth *works* rather than gaping through a sentence. The talk strip
    draws two open mouths, mid and wide, and which of them an open frame shows
    is :func:`face_plan`'s business: this only says open or shut.
    """
    spans = speaking_spans(words, start, end)
    n = max(int(round((end - start) * fps)), 1)
    out: list[bool] = []
    for i in range(n):
        t = start + i / fps
        speaking = any(a <= t < b for a, b in spans)
        out.append(bool(speaking and int(t * FLAP_HZ) % 2 == 0))
    return out


def beat_times(words: list[WordTimestamp], start: float, end: float) -> list[float]:
    """Sentence-ish pauses inside the segment."""
    spans = speaking_spans(words, start, end)
    return [b for (_, b), (a2, _) in zip(spans, spans[1:]) if a2 - b >= BEAT_GAP_S]


def quiet_spans(words: list[WordTimestamp], start: float,
                end: float) -> list[tuple[float, float]]:
    """The windows inside the segment where nothing is being said."""
    out: list[tuple[float, float]] = []
    t = start
    for a, b in speaking_spans(words, start, end):
        if a > t:
            out.append((t, a))
        t = max(t, b)
    if end > t:
        out.append((t, end))
    return out


def blink_intervals(start: float, end: float, *, seed: str) -> list[float]:
    """Candidate blink times: every three to six seconds across [start, end).

    The interval is redrawn each time so it never settles into a rhythm, and
    the sequence is seeded per shot so two shots in one cut do not blink in
    lockstep — which is the specific thing that reads as a puppet.
    """
    if end <= start:
        return []
    rng = random.Random(f"blink|{seed}|{start:.3f}")
    lo, hi = BLINK_EVERY_S
    out: list[float] = []
    t = start + rng.uniform(lo * 0.4, hi)
    while t < end:
        out.append(t)
        t += rng.uniform(lo, hi)
    return out


def blink_schedule(plan: list[bool], fps: int, *, seed: str,
                   length: int = 3) -> list[int]:
    """Output-frame indices where a blink starts. Never mid-flap.

    A blink needs `length` consecutive CLOSED-mouth frames. That is what "not
    mid-flap" means and it is checkable frame by frame, which "in a gap
    between words" is not:

    word timings arrive WALL TO WALL. Measured on the fixture short, every
    single gap between consecutive words is 0.000s, so a shot has no acoustic
    silence in it at all — and under a rule of "only where nobody is
    speaking" a face talking for fourteen seconds blinks exactly zero times,
    which is the static face this whole thing exists to fix.

    The mouth alternates at :data:`FLAP_HZ`, so a closed run is about four
    frames at 30fps and a three-frame blink fits inside one even mid-sentence
    — where people do in fact blink. A candidate that cannot find a closed run
    within :data:`BLINK_SEARCH_S` is dropped rather than forced.
    """
    if not plan or length <= 0:
        return []
    reach = max(int(BLINK_SEARCH_S * fps), 1)
    out: list[int] = []
    for t in blink_intervals(0.0, len(plan) / fps, seed=seed):
        want = int(round(t * fps))
        landed = None
        for delta in range(reach + 1):
            for j in (want - delta, want + delta):
                if 0 <= j <= len(plan) - length and not any(plan[j:j + length]):
                    landed = j
                    break
            if landed is not None:
                break
        # Two blinks on top of each other is a flutter, not a blink.
        if landed is not None and (not out or landed - out[-1] >= length * 2):
            out.append(landed)
    return out


@dataclass(frozen=True)
class FaceFrame:
    """What is on screen for one output frame: a strip, and which of its frames."""

    key: str
    index: int = 0


def _frames_where(plate: Plate | None, test) -> list[int]:
    return [i for i, f in enumerate(plate.frames) if test(f)] if plate else []


def face_plan(shot: HostShot, words: list[WordTimestamp], start: float,
              end: float, fps: int, *, seed: str) -> tuple[list[FaceFrame], dict]:
    """Which frame of which strip shows on every output frame of [start, end).

    THE ONE PLACE THAT DECIDES IT, for both lanes: the long builds a clip out of
    this list and the short draws it frame by frame, and before this they each
    had their own idea of a face — and neither ever blinked.

    Under a word the mouth flaps at :data:`FLAP_HZ`: shut on the off-beats,
    and on the beats one of the strip's OPEN mouths, mid and wide in turn, so
    a sentence is not the same two drawings swapped forty times. The frames
    are found by what they say they are (`mouthOpen`), never by position.

    In a silence long enough to register (:data:`IDLE_MIN_SPAN_S`) the idle
    strip plays at its own rate. Anywhere else he holds the pose.

    A FRAMING NEVER HOLDS THE POSE. design's crop review (ANSWERS.md §4,
    finding 2): the closed mouth is a filled bar, which at full figure is a
    mouth and at close-up scale is a horizontal dash, and a still close framing
    holds that dash on screen. "Cut close on -talk or -idle, where the mouth
    shapes cycle — this belongs in the shot list as a rule." So in a framing
    every frame that is not a word is an idle frame, however short the gap.

    A blink replaces a run of closed-mouth frames with the blink strip's
    shut-eyes drawing for :data:`BLINK_S`, every three to six seconds
    (:func:`blink_schedule`). The report says what happened, so the manifest
    can say whether the face moved rather than somebody having to watch.
    """
    n = max(int(round((end - start) * fps)), 1)
    talk = shot.talk
    opens = _frames_where(talk, lambda f: f.mouth_open)
    shuts = _frames_where(talk, lambda f: not f.mouth_open)
    if talk is not None and not opens:
        log.warning("%s draws no open mouth — he will not talk", talk.key)
        talk = None
    idle = shot.idle if shot.idle is not None and shot.idle.frames else None
    idle_fps = float(idle.fps or IDLE_HZ) if idle else IDLE_HZ
    framing = shot.is_framing
    if framing and idle is None:
        log.warning("%s is a framing with no idle strip — its silences hold "
                    "the still, which the kit says never to do", shot.key)

    is_open = mouth_schedule(words, start, end, fps) if talk else [False] * n
    quiet = ([(a, b) for a, b in quiet_spans(words, start, end)
              if framing or b - a >= IDLE_MIN_SPAN_S] if idle else [])
    speaking = speaking_spans(words, start, end)

    hold = FaceFrame(shot.pose.key, 0)
    shut = FaceFrame(talk.key, shuts[0]) if talk and shuts else hold
    plan: list[FaceFrame] = []
    talk_frames = idle_frames = 0
    for i in range(n):
        t = start + i / fps
        if talk is not None and is_open[i]:
            beat = int(t * FLAP_HZ) // 2
            plan.append(FaceFrame(talk.key, opens[beat % len(opens)]))
            talk_frames += 1
            continue
        if idle is not None and any(a <= t < b for a, b in quiet):
            plan.append(FaceFrame(idle.key,
                                  int((t - start) * idle_fps) % len(idle.frames)))
            idle_frames += 1
            continue
        # Between two words: the talk strip's own shut mouth, which is the
        # same drawing as the pose, so a sentence never cuts to another file.
        in_word = any(a <= t < b for a, b in speaking)
        plan.append(shut if in_word else hold)

    blinks = 0
    shut_eyes = _frames_where(shot.blink, lambda f: f.eyes == "closed")
    if shut_eyes:
        length = max(int(round(BLINK_S * fps)), 1)
        for j in blink_schedule(is_open, fps, seed=seed, length=length):
            for m in range(j, min(j + length, n)):
                plan[m] = FaceFrame(shot.blink.key, shut_eyes[0])
            blinks += 1

    report = {
        "pose": shot.key,
        "spoke": talk_frames > 0,
        "talk_frames": talk_frames,
        "idle_frames": idle_frames,
        "blinks": blinks,
        "has_talk": talk is not None,
        "has_idle": idle is not None,
        "held_frames": sum(1 for f in plan if f == hold),
    }
    return plan, report


def build_host_clip(
    words: list[WordTimestamp],
    start: float,
    end: float,
    out_path: Path,
    *,
    reg: Registry,
    settings,
    display_w: int | None = None,
    display_h: int | None = None,
    fps: int = 30,
    role: str = "open",
    shot_index: int = 0,
    used: dict[str, int] | None = None,
    report: dict | None = None,
) -> tuple[Path, tuple[int, int]] | None:
    """Composite a talking Dennis into an alpha clip for [start, end).

    Returns (clip_path, (w, h)) so the caller can place him, or None when the
    registry has no usable pose for the role.

    There is no furniture to strip any more. The v1 host shots were full-frame
    chapter cards with a ticker chip and a disclaimer painted into them, so a
    short that drew its own printed both — twice, in two faces. The v2 host is
    an alpha cut-out with no baked text at all, which is what that whole code
    path existed to work around.

    `report`, when given, is filled with what the shot actually did — the pose,
    whether it spoke, how many idle frames played, how often he blinked — so
    the manifest can say whether the face moved rather than the operator
    having to watch for it.
    """
    from PIL import Image

    from pipeline.plate_frames import _resize_to
    from pipeline.rasters import frames_to_alpha_clip

    speaking = any(start <= w.start < end for w in words)
    shot = pick_shot(reg, role, shot_index, speaking=speaking, used=used)
    if shot is None or end <= start:
        return None
    if not shot.pose.frames or not shot.pose.frame_paths()[0].exists():
        return None

    plan, did = face_plan(shot, words, start, end, fps,
                          seed=f"{shot.key}|{start:.3f}")

    loaded: dict[tuple[str, int], "Image.Image"] = {}

    def image(face: FaceFrame) -> "Image.Image":
        got = loaded.get((face.key, face.index))
        if got is not None:
            return got
        try:
            plate = reg.require(face.key)
            img = Image.open(plate.frame_paths()[face.index]).convert("RGBA")
        except Exception as exc:  # noqa: BLE001 — a face is never fatal
            if face.key == shot.pose.key:
                raise
            log.warning("host %s: %s frame %d did not load (%s) — holding "
                        "instead", shot.key, face.key, face.index, exc)
            img = image(FaceFrame(shot.pose.key, 0))
        else:
            if display_w or display_h:
                img = _resize_to(img, display_w, display_h)
        loaded[(face.key, face.index)] = img
        return img

    frames = [image(face) for face in plan]
    if report is not None:
        report.update(did)

    frames_to_alpha_clip(frames, fps, out_path)
    return out_path, frames[0].size
