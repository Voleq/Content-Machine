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

Two more things move, so a held host shot never reads as a still:

* **The line boils.** Several of the shots are two-frame boil pairs, and held
  frames alternate between them — the same hand-drawn shimmer the doodles use.
* **The shot changes.** Consecutive host beats step through a bank, so a long
  cut never returns to an identical frame.

Everything degrades to ``None`` when the kit cannot supply a shot, so a render
never fails for want of a host — but the SHORT engine treats that as an error
rather than a shrug, because a short with no host is the bug this replaced.
"""

from __future__ import annotations

import logging
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
    """One composed shot: the closed-mouth asset and its open-mouth twin."""

    closed: Asset
    open_: Asset

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
            out.append(HostShot(closed=pair[0], open_=pair[1]))
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
) -> tuple[Path, tuple[int, int]] | None:
    """Composite a talking Dennis into an alpha clip for [start, end).

    Returns (clip_path, (w, h)) so the caller can place him, or None when the
    kit has no usable shot for the role.

    `strip_furniture` is for the 9:16 shorts: the host shots are long-form
    chapter cards with a ticker chip and a disclaimer painted into them, and
    the short draws its own. Left on, every short opens and closes with a
    placeholder ticker from the design file on screen next to ours.
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

    plan = mouth_schedule(words, start, end, fps)
    frames: list[Image.Image] = []
    for i, is_open in enumerate(plan):
        pool = open_ if is_open else closed
        # The boil only applies to held frames; a mouth mid-flap is already
        # moving and a second jitter on top reads as noise.
        held = i > 0 and plan[i - 1] == is_open
        idx = int(i / fps * BOIL_HZ) % len(pool) if held and len(pool) > 1 else 0
        frames.append(pool[idx])

    frames_to_alpha_clip(frames, fps, out_path)
    return out_path, frames[0].size
