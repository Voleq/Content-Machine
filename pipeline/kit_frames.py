"""Playing kit assets, and filling their text slots.

Two jobs that have to agree with each other, so they live together:

**Playback.** 84 of the 384 assets are multi-frame. The registry says how each
one moves — ``static``, ``boil`` (a two-frame line wobble at ~6fps),
``one-shot`` (play once, hold the last frame) or ``loop`` — and how fast, and
how many frames. :func:`frame_indices` turns that into one frame index per
output frame. There is deliberately no per-family branch anywhere in this
module: the next delivery adds artwork, not code.

**Slots.** 74 declared boxes across 42 assets turn a fixed drawing into a card
that says something different in every video. Filling one honours ``align``,
``valign`` and ``font`` — Space Mono 700 for figures, Shantell Sans 800 for
display text.

Two traps, both silent when missed, both handled here rather than at each call
site:

* ``exportScale: 2`` — slot boxes are canvas coordinates and the shorts PNGs
  are double that. Compositing against the raw pixels without scaling puts
  every number at exactly half its intended position, on a drawing that still
  looks fine.
* ``slotFrameDelta`` on ``shorts/dennis-vs-numbers/numbers-raining`` — the
  boxes fall with the rain and wrap. Filling frame 0's geometry into all six
  frames leaves the figures hanging in the air while the drops move past them.

Everything returns Pillow images or an alpha ``.mov``; the FFmpeg graph does
the compositing, exactly as the rest of the pipeline does.
"""

from __future__ import annotations

import logging
from pathlib import Path

from config import Settings
from pipeline.kit import PALETTE, Asset, Slot, SlotFrameDelta

log = logging.getLogger(__name__)

# Registry font family + weight -> the face bundled in assets/fonts. The
# registry names design fonts; this is the only place that has to know which
# file that is.
_FACES = {
    ("space mono", True): "SpaceMono-Bold.ttf",
    ("space mono", False): "SpaceMono-Regular.ttf",
    ("shantell sans", True): "ShantellSans-Bold.ttf",
    ("shantell sans", False): "ShantellSans-Regular.ttf",
    ("space grotesk", True): "SpaceGrotesk-Bold.ttf",
    ("space grotesk", False): "SpaceGrotesk-Regular.ttf",
}
_ITALIC = {"ShantellSans-Bold.ttf": "ShantellSans-BoldItalic.ttf"}

# A slot is a box, not a text length, so the type is fitted to it: start at the
# height of the box and shrink until the value fits. These bound that search.
_MIN_SLOT_PT = 10
_FIT_STEPS = 64


def font_file(slot: Slot) -> str:
    bold = slot.font_weight >= 600
    face = _FACES.get((slot.font_family.strip().lower(), bold))
    if face is None:
        face = "SpaceMono-Bold.ttf" if bold else "SpaceMono-Regular.ttf"
    if slot.italic:
        face = _ITALIC.get(face, face)
    return face


# --------------------------------------------------------------------------
# Playback
# --------------------------------------------------------------------------
def frame_indices(asset: Asset, duration_s: float, fps: int) -> list[int]:
    """One source-frame index per output frame, for `duration_s` at `fps`.

    Driven entirely by ``playback``/``frameCount``/``fps`` from the registry:

    ``static``    the single frame, held.
    ``boil``      alternate the pair at the asset's own rate — the hand-drawn
                  ink shimmer, which is slower than the output frame rate on
                  purpose.
    ``one-shot``  play the strip once at the asset's rate, then hold the last
                  frame for as long as the beat lasts.
    ``loop``      cycle the strip for the whole beat.
    """
    n_out = max(int(round(max(duration_s, 0.0) * fps)), 1)
    n_src = max(asset.frame_count, 1)
    if n_src == 1 or asset.playback == "static":
        return [0] * n_out

    rate = asset.fps or fps
    if asset.playback == "boil":
        # Two frames, alternating. Any longer strip still alternates its ends
        # rather than playing through — a boil is a wobble, not an animation.
        pair = (0, min(1, n_src - 1))
        return [pair[int(i / fps * rate) % 2] for i in range(n_out)]
    if asset.playback == "one-shot":
        return [min(int(i / fps * rate), n_src - 1) for i in range(n_out)]
    # loop
    return [int(i / fps * rate) % n_src for i in range(n_out)]


def playback_seconds(asset: Asset) -> float:
    """How long one pass through the strip takes — the floor for a one-shot
    beat, so a six-frame transformation is never cut off half-drawn."""
    if asset.frame_count <= 1 or asset.playback == "static":
        return 0.0
    return asset.frame_count / float(asset.fps or 12)


# --------------------------------------------------------------------------
# Slot filling
# --------------------------------------------------------------------------
def _colour(name: str) -> tuple[int, int, int]:
    return PALETTE.get(name, PALETTE["ink"])


def _wrap_to(draw, text: str, font, max_w: int) -> list[str]:
    lines: list[str] = []
    for para in str(text).split("\n"):
        cur = ""
        for word in para.split():
            trial = f"{cur} {word}".strip()
            if draw.textlength(trial, font=font) <= max_w or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
    return lines


def _draw_tracked(draw, xy, text: str, font, fill, tracking_px: float) -> None:
    """Letter-spaced text. Pillow has no tracking, and the kit's mono kickers
    are set wide enough that drawing them solid reads as a different card."""
    if tracking_px <= 0:
        draw.text(xy, text, font=font, fill=fill)
        return
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += draw.textlength(ch, font=font) + tracking_px


def _tracked_width(draw, text: str, font, tracking_px: float) -> float:
    w = draw.textlength(text, font=font)
    return w + tracking_px * max(len(text) - 1, 0) if tracking_px > 0 else w


def fill_slot(
    img,
    slot: Slot,
    value: str,
    settings: Settings,
    *,
    export_scale: int = 1,
    origin: tuple[int, int] | None = None,
) -> None:
    """Composite `value` into `slot` on `img`, in place.

    `origin` overrides the slot's own (x, y) in CANVAS coordinates — that is
    how ``slotFrameDelta`` moves a box per frame without every caller
    re-deriving the geometry.
    """
    from PIL import Image, ImageDraw

    text = str(value if value is not None else "").strip()
    if not text:
        return
    if slot.case == "upper":
        text = text.upper()
    elif slot.case == "lower":
        text = text.lower()

    scale = max(int(export_scale or 1), 1)
    ox, oy = origin if origin is not None else (slot.x, slot.y)
    x0, y0 = ox * scale, oy * scale
    bw, bh = slot.w * scale, slot.h * scale
    if bw <= 0 or bh <= 0:
        return

    draw = ImageDraw.Draw(img)
    if slot.clear:
        # Only the blank layouts need this: their placeholder copy is baked
        # into the PNG, so the box is painted back to paper before the real
        # value goes down. Shorts slots sit on empty drawing and never set it.
        draw.rectangle([x0, y0, x0 + bw - 1, y0 + bh - 1],
                       fill=(*_colour(slot.clear), 255))

    face = font_file(slot)
    fill = (*_colour(slot.colour), 255)

    # Fit to the box: start at its height and shrink until the value fits both
    # ways. A slot is geometry, not a promise about how long the text is.
    size = max(int(bh * 0.86), _MIN_SLOT_PT)
    lines: list[str] = [text]
    for _ in range(_FIT_STEPS):
        font = _load(settings, face, size)
        tracking_px = slot.tracking * size
        lines = _wrap_to(draw, text, font, bw) if slot.wrap else [text]
        widest = max(_tracked_width(draw, ln, font, tracking_px) for ln in lines)
        ascent, descent = font.getmetrics()
        line_h = int((ascent + descent) * 1.08)
        if (widest <= bw and line_h * len(lines) <= bh) or size <= _MIN_SLOT_PT:
            break
        size = max(int(size * 0.92), _MIN_SLOT_PT)

    font = _load(settings, face, size)
    tracking_px = slot.tracking * size
    ascent, descent = font.getmetrics()
    line_h = int((ascent + descent) * 1.08)
    block_h = line_h * len(lines)

    if slot.valign == "top":
        y = y0
    elif slot.valign == "bottom":
        y = y0 + bh - block_h
    else:
        y = y0 + (bh - block_h) // 2

    for line in lines:
        lw = _tracked_width(draw, line, font, tracking_px)
        if slot.align == "left":
            x = x0
        elif slot.align == "right":
            x = x0 + bw - lw
        else:
            x = x0 + (bw - lw) / 2
        _draw_tracked(draw, (x, y), line, font, fill, tracking_px)
        y += line_h


def _load(settings: Settings, face: str, size: int):
    from PIL import ImageFont

    return ImageFont.truetype(str(settings.fonts_dir / face), max(int(size), 1))


def render_frame(
    asset: Asset,
    frame_index: int,
    values: dict[str, str] | None,
    settings: Settings,
):
    """One frame of an asset with its slots filled, as an RGBA image."""
    from PIL import Image

    idx = min(max(frame_index, 0), len(asset.frames) - 1)
    img = Image.open(asset.frames[idx]).convert("RGBA")
    if not values:
        return img
    delta: SlotFrameDelta | None = asset.slot_frame_delta
    unknown = set(values) - {s.name for s in asset.slots}
    if unknown:
        log.warning("%s has no slot named %s — value dropped",
                    asset.key, ", ".join(sorted(unknown)))
    for slot in asset.slots:
        value = values.get(slot.name)
        if value in (None, ""):
            continue
        origin = delta.at(slot, idx) if delta is not None else None
        fill_slot(img, slot, value, settings,
                  export_scale=asset.export_scale, origin=origin)
    return img


def render_still(asset: Asset, values: dict[str, str] | None, settings: Settings):
    """The frame to show when an asset is used as a still.

    A one-shot's *last* frame is its end state — a transformation shown on its
    first frame is a drawing of nothing having happened yet.
    """
    idx = asset.frame_count - 1 if asset.playback == "one-shot" else 0
    return render_frame(asset, idx, values, settings)


def render_clip(
    asset: Asset,
    out_path: Path,
    *,
    duration_s: float,
    fps: int,
    settings: Settings,
    values: dict[str, str] | None = None,
    display_w: int | None = None,
    display_h: int | None = None,
) -> tuple[Path, tuple[int, int]]:
    """An alpha clip of `asset` playing for `duration_s`.

    Returns (path, (w, h)) so the caller can place it. Distinct source frames
    are rendered once and reused across the schedule — a six-frame loop over a
    four-second beat is six images, not a hundred and twenty.
    """
    from pipeline.rasters import frames_to_alpha_clip

    plan = frame_indices(asset, duration_s, fps)
    cache: dict[int, "object"] = {}
    for idx in set(plan):
        img = render_frame(asset, idx, values, settings)
        if display_w or display_h:
            img = _resize(img, display_w, display_h)
        cache[idx] = img
    frames = [cache[i] for i in plan]
    frames_to_alpha_clip(frames, fps, out_path)  # type: ignore[arg-type]
    return out_path, frames[0].size  # type: ignore[union-attr]


def _resize(img, width: int | None, height: int | None):
    from PIL import Image

    if width and not height:
        ratio = width / img.width
        height = max(int(img.height * ratio), 1)
    elif height and not width:
        ratio = height / img.height
        width = max(int(img.width * ratio), 1)
    if not width or not height:
        return img
    return img.resize((max(width, 1), max(height, 1)), Image.LANCZOS)


def fit_into(img, box_w: int, box_h: int):
    """Contain-fit an asset into a box, preserving registration.

    Frames of a strip share a canvas and a top-left registration point, so an
    asset is scaled as a whole and never re-fitted per frame — re-fitting is
    what makes a sequence appear to drift.
    """
    ratio = min(box_w / img.width, box_h / img.height)
    return _resize(img, max(int(img.width * ratio), 1), max(int(img.height * ratio), 1))
