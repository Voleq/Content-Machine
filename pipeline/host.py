"""Dennis on screen — a composed shot, mouth-flapped to the voice-over.

The kit ships the host as *pairs*: a composed frame and a ``-talk`` twin drawn
with his mouth open. Talking is therefore frame swapping, and the swap schedule
comes from the voice-over word timestamps — ``tts.words``, the same master
clock every other cue reads. The mouth is open while a word is sounding and
closed in the gaps.

Twenty-one assets ship a ``-talk`` twin and twenty of them are usable. The
twenty-first, ``chapters/management/dennis-reads-proxy-talk``, is byte-identical
to the frame it is supposed to differ from, so flapping it animates nothing;
:meth:`pipeline.kit.Kit.talk_pair` returns ``None`` for it and the shot holds
still instead of pretending. That is a gap in the artwork, and the kit doctor
reports it as one.

Four more things move, so a held host shot never reads as a still:

* **He blinks.** A ``-blink`` strip plays every three to six seconds, the
  interval redrawn each time and seeded per shot so two shots never blink
  together, and never over an open mouth — the strip always lands inside a
  closed run, which is the checkable form of "not mid-flap".
* **He settles.** A ``-idle`` strip loops through the long non-speaking spans
  — the ones ``MAX_HOST_BEAT_S`` creates in long-form — so a face waiting out
  a chart shifts its weight instead of holding a pose.
* **The line boils.** Several of the shots are two-frame boil pairs, and held
  frames alternate between them — the same hand-drawn shimmer the doodles use.
* **The shot changes.** Consecutive host beats step through a bank, so a long
  cut never returns to an identical frame.

The first two are resolved by naming convention through the registry, the same
way ``-talk`` is, so an artwork batch adds them with no code change. A shot
that ships neither boils exactly as before: nothing in the micro-motion path
may raise or block a render, because a face is never worth a failed cut.

Everything degrades to ``None`` when the kit cannot supply a shot, so a render
never fails for want of a host — but the SHORT engine treats that as an error
rather than a shrug, because a short with no host is the bug this replaced.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from pathlib import Path

from pipeline.kit import Asset, Kit
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
HOST_BANKS: dict[str, tuple[str, ...]] = {
    "open": (
        "chapters/cold-open/at-desk-open",
        "chapters/cold-open/establishing",
        "chapters/cold-open/desk-lean",
        "chapters/cold-open/title-room",
        "chapters/cold-open/reframe",
        "chapters/cold-open/at-desk-tired",
    ),
    "close": (
        "chapters/resigned-close/dennis-shrug-out",
        "chapters/resigned-close/dennis-defeated",
        "chapters/resigned-close/closing-card",
        "chapters/resigned-close/outro-subscribe",
    ),
    "panel": (
        "chapters/the-numbers/chart-annotated",
        "chapters/the-numbers/chart-bars",
        "chapters/valuation/pe-history",
        "chapters/valuation/dennis-weighing",
        "chapters/bull-vs-bear/dennis-both-hands",
        "chapters/moat/dennis-inspects",
        "chapters/short-interest/dennis-eyes-the-squeeze",
    ),
    "beat": (
        "chapters/how-we-got-here/dennis-narrates",
        "chapters/valuation/dennis-shrug-value",
        "chapters/bull-vs-bear/dennis-torn",
        "chapters/cold-open/desk-lean",
        "chapters/the-numbers/chart-annotated",
    ),
}

# The two-shot figure: a CUT-OUT, not a card.
#
# Every entry in HOST_BANKS is a complete 16:9 scene — Dennis plus a headline
# plus, often, its own illustration. They are slides, and they are right when
# they ARE the frame. Insetting one beside a piece of evidence stacks two
# finished compositions in one frame, which is what made the long cut read as
# a collage: a designed backdrop, an evidence card, and a second slide
# carrying "So... which is it?" over the top of it.
#
# These are the 1:1 mascot poses: 98% transparent, no background, no copy. A
# figure standing next to the evidence on the same sheet of paper is a
# two-shot. A slide pasted onto a slide is not.
#
# WHOLE FIGURES ONLY. Half the `mascot/` family is components for the old
# layer rig — `arm-gesture` is two arm strokes, `layer-body` is a headless
# torso, `face-*` is a head — and one of them in this list put a pair of
# disembodied arms next to the evidence. `_FIGURE_PARTS` is the guard.
PANEL_FIGURES: tuple[str, ...] = (
    "mascot/pointing",
    "mascot/deadpan",
    "mascot/tired-explaining",
    "mascot/shrug",
    "mascot/exasperated",
    "mascot/smug-told-you",
)

# Name prefixes that are pieces of a figure rather than a figure.
_FIGURE_PARTS = ("arm-", "face-", "mouth-", "layer-")


def panel_figure(kit: Kit, index: int = 0) -> Asset | None:
    """One cut-out pose for a two-shot, stepped so a cut never repeats."""
    options = [
        a for k in PANEL_FIGURES
        if not k.rsplit("/", 1)[-1].startswith(_FIGURE_PARTS)
        and (a := kit.get(k)) is not None
    ]
    if not options:
        return None
    return options[index % len(options)]


@dataclass(frozen=True)
class HostShot:
    """One composed shot: the closed-mouth asset and its open-mouth twin.

    `blink` and `idle` are the optional micro-motion strips. They are None on
    every shot the artwork has not reached yet, and the shot boils as before.
    """

    closed: Asset
    open_: Asset
    blink: Asset | None = None
    idle: Asset | None = None

    @property
    def key(self) -> str:
        return self.closed.key


# A bank that may borrow from another once its own shots are exhausted.
#
# `beat` is five shots. On a short that is plenty; on a forty-minute cut with
# a host beat every twelve seconds it wraps every minute, and the repetition
# is the most visible thing in the video. The `panel` shots are also just
# Dennis presenting, so they extend the rotation without changing the register.
BANK_EXTENSIONS: dict[str, tuple[str, ...]] = {
    "beat": ("panel",),
}


def shots(kit: Kit, role: str = "open") -> list[HostShot]:
    """Every usable shot in a bank, in bank order.

    A bank listed in `BANK_EXTENSIONS` continues into its extension, so the
    rotation is long enough for the runtime rather than long enough for the
    bank. Its own shots always come first, and a shot is never listed twice.
    """
    out: list[HostShot] = []
    seen: set[str] = set()
    for bank in (role, *BANK_EXTENSIONS.get(role, ())):
        for key in HOST_BANKS.get(bank, ()):
            pair = kit.talk_pair(key)
            if pair is None:
                log.debug("host shot %s has no usable talk twin — skipped", key)
                continue
            if pair[0].key in seen:
                continue
            seen.add(pair[0].key)
            out.append(HostShot(
                closed=pair[0], open_=pair[1],
                blink=kit.micro_motion(key, "-blink"),
                idle=kit.micro_motion(key, "-idle"),
            ))
    return out


def pick_shot(kit: Kit, role: str, index: int = 0) -> HostShot | None:
    """The `index`-th shot of a bank, wrapping.

    Stepping rather than hashing: consecutive host beats in one video must not
    repeat, and a counter guarantees that where a hash only makes it likely.
    """
    bank = shots(kit, role)
    if not bank:
        return None
    return bank[index % len(bank)]


def available(kit: Kit, role: str = "open") -> bool:
    """True when the kit can supply a lip-synced shot for this role."""
    return bool(shots(kit, role))


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
    kit: Kit,
    settings,
    display_w: int | None = None,
    display_h: int | None = None,
    fps: int = 30,
    role: str = "open",
    shot_index: int = 0,
    strip_furniture: bool = False,
    report: dict | None = None,
) -> tuple[Path, tuple[int, int]] | None:
    """Composite a talking Dennis into an alpha clip for [start, end).

    Returns (clip_path, (w, h)) so the caller can place him, or None when the
    kit has no usable shot for the role.

    `strip_furniture` is for the 9:16 shorts: the host shots are long-form
    chapter cards with a ticker chip and a disclaimer painted into them, and
    the short draws its own. Left on, every short opens and closes with a
    placeholder ticker from the design file on screen next to ours.

    `report`, when given, is filled with what the shot actually did — the key,
    how many blinks were scheduled, whether the idle strip played — so the
    manifest can say whether the face moved rather than the operator having to
    watch for it.
    """
    from PIL import Image

    from pipeline.kit_frames import _resize, strip_baked_furniture
    from pipeline.rasters import frames_to_alpha_clip

    shot = pick_shot(kit, role, shot_index)
    if shot is None or end <= start:
        return None

    def variants(asset: Asset) -> list[Image.Image]:
        imgs = []
        for frame in asset.frames:
            img = Image.open(frame).convert("RGBA")
            if strip_furniture:
                img = strip_baked_furniture(img, asset)
            if display_w or display_h:
                img = _resize(img, display_w, display_h)
            imgs.append(img)
        return imgs

    closed = variants(shot.closed)
    open_ = variants(shot.open_)
    if not closed or not open_:
        return None

    # The micro-motion strips, if this shot has them. A strip that fails to
    # load is the same as a strip that was never delivered: the shot boils.
    def optional(asset: Asset | None) -> list[Image.Image]:
        if asset is None:
            return []
        try:
            return variants(asset)
        except Exception as exc:  # noqa: BLE001 — a face is never fatal
            log.warning("host %s: %s did not load (%s) — boiling instead",
                        shot.key, asset.key, exc)
            return []

    blink = optional(shot.blink)
    idle = optional(shot.idle)

    plan = mouth_schedule(words, start, end, fps)
    # Which output frame each blink starts on. The strip plays straight
    # through from there — three frames at 30fps is a tenth of a second,
    # which is what a blink is.
    blink_at = set()
    if blink:
        blink_at = set(blink_schedule(
            plan, fps, seed=f"{shot.key}|{shot_index}", length=len(blink)))
    # Long quiet stretches — where the idle strip shifts his weight rather
    # than the boil twitching a line.
    quiet = [(a, b) for a, b in quiet_spans(words, start, end)
             if b - a >= IDLE_MIN_SPAN_S] if idle else []

    frames: list[Image.Image] = []
    blinking = -1          # frames remaining in the blink currently playing
    blinks_played = 0
    idle_frames = 0
    for i, is_open in enumerate(plan):
        pool = open_ if is_open else closed
        # The boil only applies to held frames; a mouth mid-flap is already
        # moving and a second jitter on top reads as noise.
        held = i > 0 and plan[i - 1] == is_open
        if blinking < 0 and i in blink_at:
            blinking = 0
            blinks_played += 1
        if 0 <= blinking < len(blink):
            frames.append(blink[blinking])
            blinking += 1
            if blinking >= len(blink):
                blinking = -1
            continue
        blinking = -1
        t = start + i / fps
        if idle and not is_open and any(a <= t < b for a, b in quiet):
            frames.append(idle[int(t * IDLE_HZ) % len(idle)])
            idle_frames += 1
            continue
        idx = int(i / fps * BOIL_HZ) % len(pool) if held and len(pool) > 1 else 0
        frames.append(pool[idx])

    if report is not None:
        report.update({
            "shot": shot.key,
            "blinks": blinks_played,
            "idle_frames": idle_frames,
            "has_blink": bool(blink),
            "has_idle": bool(idle),
        })

    frames_to_alpha_clip(frames, fps, out_path)
    return out_path, frames[0].size
