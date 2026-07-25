"""Dennis on screen — the layered stickman rig, composited into a talking clip.

The design kit ships the host as separate PNG frames rather than an animation:
a pose is one file, and the mouth is baked into it. Talking is therefore
*frame swapping*, and the swap schedule comes from the voice-over word
timestamps — `tts.words`, the same master clock every other cue reads. The
mouth is open while a word is sounding and closed in the gaps, stepping
through the half-open `mid` frame so it ramps rather than snaps.

Two more things move, so a held host shot never reads as a still:

* **The face swaps on beats.** At a sentence pause the open-mouth frame
  alternates between the tired `talk-open` face and the eyebrows-up
  `interested-open` one. Both are open-mouth frames, so the lip-sync is
  unaffected while the expression genuinely changes.
* **The line boils.** Poses that ship an `_b` twin alternate between the two
  on held frames, which is the same hand-drawn shimmer the doodles use.

Everything degrades to `None` when the kit is missing, so a render never
fails for want of a host — the caller falls back to a designed backdrop.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from pipeline.models import WordTimestamp

log = logging.getLogger(__name__)

KIT_MASCOT = Path("assets") / "kit" / "mascot"

# Frames per second the mouth is allowed to change. Real speech flaps at
# roughly this rate; faster reads as a buzz, slower as a puppet.
FLAP_HZ = 7.0

# A gap this long between words reads as a sentence break — where the face is
# allowed to change without looking twitchy.
BEAT_GAP_S = 0.32

# Held (non-speaking) frames alternate with their _b twin at this rate.
BOIL_HZ = 4.0


@dataclass(frozen=True)
class HostRig:
    """One pose family: the frames a single host shot swaps between."""

    closed: str
    open_: str
    mid: str | None = None
    alt_open: str | None = None  # the face-swap frame, also open-mouthed

    def frames(self) -> tuple[str, ...]:
        return tuple(f for f in (self.closed, self.mid, self.open_, self.alt_open) if f)


# `facing` is which way Dennis is turned, which is the opposite side from the
# panel he is addressing: a chart on the right needs a host looking right.
RIGS: dict[tuple[str, str], HostRig] = {
    ("talk", "right"): HostRig(
        closed="host/look-right-talk-closed", mid="host/look-right-talk-mid",
        open_="host/look-right-talk-open", alt_open="host/look-right-interested-open"),
    ("talk", "left"): HostRig(
        closed="host/look-left-talk-closed", mid="host/look-left-talk-mid",
        open_="host/look-left-talk-open", alt_open="host/look-left-interested-open"),
    # arm out at the panel — the two-shot pose. No mid frame shipped, so the
    # flap is a straight closed/open.
    ("point", "right"): HostRig(
        closed="host/point-at-board-right", open_="host/point-at-board-right-open"),
    ("point", "left"): HostRig(
        closed="host/point-at-board-left", open_="host/point-at-board-left-open"),
    # reading something down at the desk
    ("down", "right"): HostRig(
        closed="host/look-down-closed", mid="host/look-down-mid",
        open_="host/look-down-open"),
    ("down", "left"): HostRig(
        closed="host/look-down-closed", mid="host/look-down-mid",
        open_="host/look-down-open"),
}


def _kit_path(root: Path, rel: str) -> Path:
    return root / KIT_MASCOT / f"{rel}.png"


def rig_for(expression: str, facing: str) -> HostRig | None:
    return RIGS.get((expression, facing)) or RIGS.get(("talk", facing))


def available(root: Path, expression: str = "talk", facing: str = "right") -> bool:
    """True when every frame this rig needs is on disk."""
    rig = rig_for(expression, facing)
    return bool(rig) and all(_kit_path(root, f).exists() for f in rig.frames())


def speaking_spans(words: list[WordTimestamp], start: float, end: float) -> list[tuple[float, float]]:
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


def mouth_schedule(
    words: list[WordTimestamp],
    start: float,
    end: float,
    fps: int,
) -> list[int]:
    """One mouth level per frame: 0 closed, 1 mid, 2 open.

    The level moves at most one step per frame, so speech onset ramps
    closed -> mid -> open instead of snapping, and the mouth flutters between
    mid and open while a word is actually sounding.
    """
    spans = speaking_spans(words, start, end)
    n = max(int(round((end - start) * fps)), 1)
    levels: list[int] = []
    level = 0
    for i in range(n):
        t = start + i / fps
        speaking = any(a <= t < b for a, b in spans)
        if speaking:
            # alternate the target so the mouth works rather than gaping
            target = 2 if int(t * FLAP_HZ) % 2 == 0 else 1
        else:
            target = 0
        level += (target > level) - (target < level)
        levels.append(level)
    return levels


def beat_times(words: list[WordTimestamp], start: float, end: float) -> list[float]:
    """Sentence-ish pauses inside the segment — where the face may change."""
    spans = speaking_spans(words, start, end)
    return [b for (_, b), (a2, _) in zip(spans, spans[1:]) if a2 - b >= BEAT_GAP_S]


def frame_plan(
    words: list[WordTimestamp],
    start: float,
    end: float,
    fps: int,
    rig: HostRig,
) -> list[str]:
    """The kit frame to show on each frame of the segment."""
    levels = mouth_schedule(words, start, end, fps)
    beats = beat_times(words, start, end)
    plan: list[str] = []
    swapped = False
    beat_i = 0
    for i, level in enumerate(levels):
        t = start + i / fps
        while beat_i < len(beats) and beats[beat_i] <= t:
            swapped = not swapped
            beat_i += 1
        if level >= 2:
            frame = (rig.alt_open if swapped and rig.alt_open else rig.open_)
        elif level == 1 and rig.mid:
            frame = rig.mid
        elif level == 1:
            frame = rig.open_        # no mid shipped: treat as open
        else:
            frame = rig.closed
        plan.append(frame)
    return plan


def build_host_clip(
    words: list[WordTimestamp],
    start: float,
    end: float,
    out_path: Path,
    *,
    display_h: int,
    fps: int = 30,
    expression: str = "talk",
    facing: str = "right",
    root: Path | None = None,
) -> tuple[Path, tuple[int, int]] | None:
    """Composite a talking Dennis into an alpha clip for [start, end).

    Returns (clip_path, (w, h)) so the caller can place him, or None when the
    rig is unavailable — a missing host degrades to the designed backdrop
    rather than failing the render.
    """
    from PIL import Image  # local: keep the module importable without PIL

    from pipeline.rasters import frames_to_alpha_clip

    root = root or Path.cwd()
    rig = rig_for(expression, facing)
    if rig is None or not all(_kit_path(root, f).exists() for f in rig.frames()):
        log.warning("host rig %r/%r unavailable — falling back to a backdrop",
                    expression, facing)
        return None
    if end <= start:
        return None

    # Load each distinct frame once, scaled to the height it will be drawn at,
    # together with its _b boil twin where the kit ships one.
    cache: dict[str, list[Image.Image]] = {}
    for rel in rig.frames():
        variants: list[Image.Image] = []
        for candidate in (rel, f"{rel}_b"):
            p = _kit_path(root, candidate)
            if not p.exists():
                continue
            img = Image.open(p).convert("RGBA")
            if img.height != display_h:
                ratio = display_h / img.height
                img = img.resize((max(int(img.width * ratio), 1), display_h), Image.LANCZOS)
            variants.append(img)
        cache[rel] = variants

    plan = frame_plan(words, start, end, fps, rig)
    frames = []
    for i, rel in enumerate(plan):
        variants = cache[rel]
        # The boil only applies to held frames; a mouth mid-flap is already
        # moving and a second jitter on top of it just reads as noise.
        held = i > 0 and plan[i - 1] == rel
        idx = int(i / fps * BOIL_HZ) % len(variants) if held and len(variants) > 1 else 0
        frames.append(variants[idx])

    frames_to_alpha_clip(frames, fps, out_path)
    return out_path, frames[0].size
