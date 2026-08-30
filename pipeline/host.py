"""Dennis on screen — a cut-out placed on the room, flapped to the voice-over.

The kit ships six poses, each as three two-frame strips: the base (a hold), a
``-talk`` strip whose first frame has the mouth open, and an ``-idle`` strip
whose second frame bobs three canvas units. Talking is frame swapping, and the
swap schedule comes from the voice-over word timestamps — ``tts.words``, the
same master clock every other cue reads.

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

# Held (non-speaking) frames alternate with their boil twin at this rate.
BOIL_HZ = 4.0

# --------------------------------------------------------------------------
# Micro-motion.
#
# The face composed exactly two states — mouth-open and mouth-closed — plus a
# boil on held frames. Over forty minutes that is a face that only ever talks,
# and it is the most-viewed element in the channel: a host who never blinks
# reads as a still with a mouth cut into it.
#
# `-blink` and `-idle` strips are resolved by naming convention through the
# registry, exactly the way `-talk` is, so a later artwork batch adds them and
# nothing here changes. Everything degrades to the current boil when a shot
# ships neither — nothing in this file may raise or block a render.
# --------------------------------------------------------------------------

# How often a face blinks. Real resting rate is every 3-6 seconds, and the
# interval is redrawn per blink so it never falls into a rhythm.
BLINK_EVERY_S = (3.0, 6.0)

# How far a scheduled blink may be nudged to find a closed-mouth run long
# enough to hold it. One that cannot is dropped rather than forced onto an
# open mouth, which reads as a dropped frame.
BLINK_SEARCH_S = 0.9

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

# The idle strip loops at this rate: a slow shift of weight, not a fidget.
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
    """One pose, as the three strips a beat plays: hold, talk, idle."""

    pose: Plate                     # the base strip — a hold, and the cut frame
    talk: Plate | None = None       # mouth open on f01; None when talks=false
    idle: Plate | None = None       # f02 bobs three canvas units

    @property
    def key(self) -> str:
        return self.pose.key

    @property
    def floor_line_y(self) -> int:
        return int(self.pose.floor_line_y or self.pose.canvas[1])

    @property
    def is_framing(self) -> bool:
        """Whether this is a camera DISTANCE rather than a figure in a room.

        `close-up` and `medium` publish `floorLineY: false`: they are head-and-
        shoulders and waist-up crops, so there is no floor line to pin and no
        anchor to solve them onto. A framing IS the shot. Treating one as a
        cut-out puts a disembodied head standing on a desk.
        """
        return not self.pose.floor_line_y

    @property
    def glance(self) -> str:
        """Where he is looking: `to camera`, `camera-left`, `camera-right`."""
        return str(getattr(self.pose, "glance", "") or "to camera")


def shots(reg: Registry, role: str = "open") -> list[HostShot]:
    """Every usable pose for a shot role, in the order the registry declares.

    A pose that declares ``talks: false`` still appears — it is a perfectly good
    hold — but its talk strip is None, so a speaking beat will not choose it.
    """
    out: list[HostShot] = []
    for key in reg.host_roles.get(role, ()):
        pose = reg.get(key)
        if pose is None:
            log.debug("host role %s names %s, which the kit does not ship", role, key)
            continue
        out.append(HostShot(pose=pose,
                            talk=reg.host_strip(key, "talk"),
                            idle=reg.host_strip(key, "idle")))
    return out


def pick_shot(reg: Registry, role: str, index: int = 0, *,
              speaking: bool = False, used: dict[str, int] | None = None
              ) -> HostShot | None:
    """The `index`-th pose of a role, wrapping.

    Stepping rather than hashing: consecutive host beats in one video must not
    repeat, and a counter guarantees that where a hash only makes it likely.

    `used` carries how often each pose has already appeared, so a pose that
    declares a ``limit`` is not chosen past it. head-in-hands is capped at one
    per video by the kit itself: it is the cost of being right, and a second one
    turns it into a running joke.
    """
    bank = [s for s in shots(reg, role) if not speaking or s.talk is not None]
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


def available(reg: Registry, role: str = "open") -> bool:
    """True when the registry can supply a pose for this role."""
    return bool(shots(reg, role))


# --------------------------------------------------------------------------
# Placement — the anchor contract.
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Placement:
    """Where a host cut-out goes on a room, in DELIVERED pixels."""

    scale: float
    x: int                      # left edge of the scaled host plate
    y: int                      # top edge of the scaled host plate
    width: int
    height: int


def place_on_room(room: Plate, host: HostShot) -> Placement | None:
    """Solve the host onto a room's ``host-anchor``. None if either lacks one.

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
    """
    # A ROOM MAY REFUSE. `room/high-desk-down` is the camera above the desk and
    # `room/wall-of-calls` is a wall of index cards: neither has a floor in
    # shot, and both say so in the field rather than leaving it out. That is
    # not the same as a plate nobody decided about, which `Registry.verify`
    # now refuses outright.
    if room.refuses_host:
        log.debug("%s declares hostAnchor: false — nobody stands here", room.key)
        return None
    anchor = room.slot("host-anchor")
    figure = host.pose.slot("figure")
    if anchor is None or figure is None or host.is_framing:
        return None

    # Everything in DELIVERED pixels from here. Mixing canvas units and
    # delivered pixels in this calculation is the exportScale trap the manifest
    # warns about, and it comes out as a host at exactly half or double his
    # intended size — on a composite that otherwise looks entirely plausible.
    hs = host.pose.export_scale
    standing = (host.floor_line_y - figure.y) * hs   # delivered px, host plate
    if standing <= 0:
        return None

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


def composite_on_room(room_img, host_img, placement: Placement):
    """Paste a scaled host cut-out onto a room frame, in place."""
    from PIL import Image

    scaled = host_img.convert("RGBA").resize(
        (max(placement.width, 1), max(placement.height, 1)), Image.LANCZOS)
    room_img.alpha_composite(scaled, (placement.x, placement.y))
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

    The kit ships two mouth states, not three, so this is a boolean rather than
    the old ramp: open while a word is sounding, alternating with closed at
    :data:`FLAP_HZ` so the mouth *works* rather than gaping through a sentence.
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
    whether it spoke, how many idle frames played — so the manifest can say
    whether the face moved rather than the operator having to watch for it.
    """
    from PIL import Image

    from pipeline.plate_frames import _resize_to
    from pipeline.rasters import frames_to_alpha_clip

    speaking = any(start <= w.start < end for w in words)
    shot = pick_shot(reg, role, shot_index, speaking=speaking, used=used)
    if shot is None or end <= start:
        return None

    def variants(plate: Plate) -> list["Image.Image"]:
        imgs = []
        for frame in plate.frame_paths():
            img = Image.open(frame).convert("RGBA")
            if display_w or display_h:
                img = _resize_to(img, display_w, display_h)
            imgs.append(img)
        return imgs

    hold = variants(shot.pose)
    if not hold:
        return None

    def optional(plate: Plate | None) -> list["Image.Image"]:
        if plate is None:
            return []
        try:
            return variants(plate)
        except Exception as exc:  # noqa: BLE001 — a face is never fatal
            log.warning("host %s: %s did not load (%s) — holding instead",
                        shot.key, plate.key, exc)
            return []

    talk = optional(shot.talk)
    idle = optional(shot.idle)

    plan = mouth_schedule(words, start, end, fps) if talk else [False] * max(
        int(round((end - start) * fps)), 1)
    quiet = [(a, b) for a, b in quiet_spans(words, start, end)
             if b - a >= IDLE_MIN_SPAN_S] if idle else []

    frames: list["Image.Image"] = []
    idle_frames = 0
    talk_frames = 0
    for i, is_open in enumerate(plan):
        t = start + i / fps
        if talk and is_open:
            # f01 is the open mouth. Cut hard — a dissolve between two boil
            # frames reads as a camera artefact, not as a hand redrawing a line.
            frames.append(talk[0])
            talk_frames += 1
            continue
        in_quiet = any(a <= t < b for a, b in quiet)
        if idle and in_quiet:
            frames.append(idle[int(t * IDLE_HZ) % len(idle)])
            idle_frames += 1
            continue
        pool = talk if (talk and not is_open and talk_frames) else hold
        frames.append(pool[int(t * BOIL_HZ) % len(pool)])

    if report is not None:
        report.update({
            "pose": shot.key,
            "spoke": bool(talk) and talk_frames > 0,
            "talk_frames": talk_frames,
            "idle_frames": idle_frames,
            "has_talk": bool(talk),
            "has_idle": bool(idle),
        })

    frames_to_alpha_clip(frames, fps, out_path)
    return out_path, frames[0].size
