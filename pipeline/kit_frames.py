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
    if not text and not slot.clear:
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
        #
        # This runs even for an EMPTY value. A card that uses three of its four
        # boxes has to blank the fourth, or the layout's own dummy copy — "What
        # the number is" — is what ships.
        draw.rectangle([x0, y0, x0 + bw - 1, y0 + bh - 1],
                       fill=(*_colour(slot.clear), 255))
    if not text:
        return

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
        # A slot that declares `clear` is ALWAYS processed, even with no value:
        # it is a blank layout's box with dummy copy printed in it, and
        # skipping it is how "What the number is" ended up shipping under a
        # real figure.
        if value in (None, "") and not slot.clear:
            continue
        origin = delta.at(slot, idx) if delta is not None else None
        fill_slot(img, slot, value, settings,
                  export_scale=asset.export_scale, origin=origin)
    return img


def unfilled_slots(asset: Asset, values: dict[str, str] | None) -> list[str]:
    """The boxes this drawing declares that `values` leaves EMPTY.

    The other direction — a value naming a box the drawing does not have — has
    been reported since the slots existed. This one never was, and it is the
    one that reaches the screen: an unbound slot is not a no-op, it is a
    drawn, empty box in the middle of a beat, and the catalogue promises the
    writer otherwise ("WITHOUT the `= value` the drawing renders with its
    boxes EMPTY. Always give a figure.").

    A slot declaring `clear` is not counted. Its box carries dummy copy that
    an empty value ERASES, so leaving it empty is a decision the layout
    depends on rather than an omission.
    """
    values = values or {}
    return [s.name for s in asset.slots
            if not str(values.get(s.name) or "").strip() and not s.clear]


def render_still(asset: Asset, values: dict[str, str] | None, settings: Settings):
    """The frame to show when an asset is used as a still.

    A one-shot's *last* frame is its end state — a transformation shown on its
    first frame is a drawing of nothing having happened yet.
    """
    idx = asset.frame_count - 1 if asset.playback == "one-shot" else 0
    # Said once per beat, HERE rather than in `render_frame`, which an
    # animated asset calls once per distinct frame. Only when somebody tried
    # to fill this drawing: a plate or a card asked for with no values at all
    # is a still being used as artwork, not a beat that lost its figure.
    if values:
        for name in unfilled_slots(asset, values):
            log.warning("%s: slot %r has no value — it renders as an empty box",
                        asset.key, name)
    return render_frame(asset, idx, values, settings)


def roll_still_frames(asset: Asset, values: dict[str, str] | None,
                      settings: Settings, *, fps: int = 30,
                      seconds: float = 0.7, transform=None):
    """A still whose numeric slots ROLL to their values on arrival.

    Returns None when nothing in `values` is a number, so the caller holds the
    still and no frames are wasted. The count-up only ever fired on the
    numbers-sheet cue, so every other figure in a short — a drawing's
    `number`, a big-number card's `figure` — appeared fully formed while the
    one on the sheet counted.
    """
    from pipeline.rasters import roll_steps

    values = values or {}
    n = max(int(seconds * fps), 2)
    rolled = {k: steps for k, v in values.items()
              if (steps := roll_steps(str(v), n)) is not None}
    if not rolled:
        return None

    idx = asset.frame_count - 1 if asset.playback == "one-shot" else 0
    frames = []
    for k in range(n + 1):
        step = dict(values)
        for name, steps in rolled.items():
            step[name] = steps[k]
        img = render_frame(asset, idx, step, settings)
        frames.append(transform(img) if transform is not None else img)
    return frames


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
    transform=None,
) -> tuple[Path, tuple[int, int]]:
    """An alpha clip of `asset` playing for `duration_s`.

    Returns (path, (w, h)) so the caller can place it. Distinct source frames
    are rendered once and reused across the schedule — a six-frame loop over a
    four-second beat is six images, not a hundred and twenty.

    `transform` is applied to each distinct frame after slot filling — how a
    full-bleed or punched beat gets its framing without a second code path for
    animated assets.
    """
    from pipeline.rasters import frames_to_alpha_clip

    plan = frame_indices(asset, duration_s, fps)
    cache: dict[int, "object"] = {}
    for idx in set(plan):
        img = render_frame(asset, idx, values, settings)
        if transform is not None:
            img = transform(img)
        elif display_w or display_h:
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


# --------------------------------------------------------------------------
# Binding tag values to an asset's slots.
# --------------------------------------------------------------------------
def bind_slot_values(
    asset: Asset,
    values: dict[str, str] | None,
) -> tuple[dict[str, str], list[str]]:
    """(slot name -> value, warnings) for the values written on a tag.

    Three forms, resolved here because this is the first point that knows what
    slots the asset has:

    * **named** — ``heavy:$1.1B`` binds the slot called ``heavy``;
    * **positional** — a bare comma list fills the slots in registry order;
    * **unnamed** — a single value goes to the asset's only slot, or the one
      called ``number``, which is what 38 of the 42 slotted assets call it.

    A value that cannot be placed is dropped with a warning rather than
    guessed at: putting a figure in the wrong box is worse than leaving the
    box empty, because it looks deliberate.

    And the reverse, which used to be silent: a BOX WITH NOTHING IN IT is
    reported too. The asymmetry ran one way for the whole life of the feature
    — a value with nowhere to go warned, a value naming a slot that does not
    exist warned, and a slot that received nothing said nothing at all, while
    being the only one of the three the viewer can see. A tag written with no
    `= value` was the worst case and the quietest: it returned `({}, [])` on
    the first line and drew every box empty.

    Warnings, never blockers. A deliberately empty box is a legitimate choice
    on some drawings and only the operator can judge it.
    """
    from pipeline.tagging import DEFAULT_SLOT, POSITIONAL_PREFIX

    values = values or {}
    slots = list(asset.slots)
    warnings: list[str] = []
    if not slots:
        if not values:
            return {}, []
        return {}, [f"{asset.key} has no slots — "
                    f"{', '.join(sorted(v for v in values.values()))} dropped"]

    names = [s.name for s in slots]
    out: dict[str, str] = {}
    for key, value in values.items():
        if key == DEFAULT_SLOT:
            target = names[0] if len(names) == 1 else next(
                (n for n in names if n == "number"), None)
            if target is None:
                warnings.append(
                    f"{asset.key} has {len(names)} slots ({', '.join(names)}) "
                    f"— name which one {value!r} goes in")
                continue
            out[target] = value
        elif key.startswith(POSITIONAL_PREFIX):
            idx = int(key[len(POSITIONAL_PREFIX):] or 0)
            if idx >= len(names):
                warnings.append(
                    f"{asset.key} has {len(names)} slots — {value!r} was the "
                    f"{idx + 1}th value and has nowhere to go")
                continue
            out[names[idx]] = value
        elif key in names:
            out[key] = value
        else:
            warnings.append(
                f"{asset.key} has no slot called {key!r} "
                f"(it has: {', '.join(names)}) — {value!r} dropped")
    for name in unfilled_slots(asset, out):
        warnings.append(
            f"{asset.key}: slot {name!r} has no value — it renders as an empty "
            f"box. Write `= <figure>` on the tag, or leave it if you mean it.")
    return out, warnings


# --------------------------------------------------------------------------
# Baked furniture.
#
# The 16:9 chapter cards were drawn for the long-form video, where the frame's
# own furniture is part of the artwork: a ticker chip top-left and the
# "Opinion / entertainment. Not financial advice." line bottom-left are
# PAINTED INTO the PNG. A short composites those cards over a 9:16 frame that
# already draws both, so the result is a duplicated disclaimer and — much
# worse — a hard-coded placeholder ticker from the design file sitting on
# screen: `$EXMPL` in our chip, `GYMX ▼ 34%` in theirs.
#
# The real fix is artwork without the furniture (see README, "artwork owed").
# Until then this erases it, and it is deliberately timid about doing so: the
# two elements sit at a FIXED position on the 1600x900 canvas, so a card only
# gets touched when the ink in the band actually matches that signature. A
# blanket crop of the same bands was measured against the library first and
# would have damaged 32 cards at the top and 75 at the bottom — legs, chart
# axes and table rules all cross there — so anything that does not match is
# left exactly as drawn.
FURNITURE_BANDS = {
    # name: (top, bottom, probe right, erase right, air side) as fractions
    "chip":       (74 / 900, 104 / 900, 0.45, 0.35, +1),
    "disclaimer": (813 / 900, 845 / 900, 0.55, 0.40, -1),
}
FURNITURE_LEFT = 73 / 1600      # both elements share the card's left margin
_FURNITURE_TOL = 5              # px of slack on the signature, at canvas size
# The furniture is a lone line with clear paper between it and the artwork:
# air below the chip, air above the disclaimer. Requiring that gap is what
# separates it from a bar label or a table row that merely happens to start at
# the same left margin — without it the erase ate the last row of
# `sector-comps/comps-table`, a bullet on `bull-vs-bear/split` and a bar
# label on `capital-allocation/uses-of-cash`.
_FURNITURE_AIR = 34 / 900


def carries_baked_furniture(img, asset: Asset | None = None) -> bool:
    """True when a card has its own chip or disclaimer painted into it.

    A DETECTOR, not an eraser. It never touches a pixel, and it is deliberately
    more eager than :func:`strip_baked_furniture`: the two answer different
    questions and pay different prices for being wrong.

    * The eraser has to be timid. Removing ink that is artwork damages the
      drawing, and a blanket crop of these bands was measured against the
      library — 32 cards damaged at the top, 75 at the bottom.
    * The detector decides whether a card may be PLACED on a frame that draws
      its own furniture. A false positive costs one card out of a hundred going
      unused; a false negative puts the disclaimer on screen twice, in two
      faces, on YouTube.

    So it allows the furniture at either margin. `resigned-close/outro-subscribe`
    prints the same disclaimer sentence RIGHT-aligned — the eraser's
    left-margin signature does not match it, and the sentence is on screen
    twice all the same. Ink that matches neither margin is artwork crossing the
    band (`resigned-close/end-card`'s "watch next" boxes), and is not furniture.
    """
    try:
        import numpy as np
    except ImportError:      # pragma: no cover - numpy ships with Pillow's peers
        return False

    if asset is not None and asset.aspect not in ("16:9", ""):
        return False
    arr = np.asarray(img.convert("RGBA")).astype(int)
    h, w = arr.shape[:2]
    if not h or not w:
        return False
    tol = _FURNITURE_TOL * 2 * w / 1600      # the margin, not the glyph run
    for top_f, bot_f, _probe_f, _erase_f, _air in FURNITURE_BANDS.values():
        y0, y1 = max(int(top_f * h) - 5, 0), int(bot_f * h) + 6
        band = arr[y0:y1]
        ink = (band[..., :3].mean(axis=2) < 205) & (band[..., 3] > 60)
        if not ink.any():
            continue
        xs = np.nonzero(ink)[1]
        left, right = int(xs.min()), int(xs.max())
        margin = FURNITURE_LEFT * w
        if abs(left - margin) <= tol or abs((w - right) - margin) <= tol:
            return True
    return False


def strip_baked_furniture(img, asset: Asset | None = None, paper=None):
    """Erase a long-form card's painted-in chip and disclaimer.

    Returns the image unchanged unless the ink in a band matches the known
    furniture geometry, so an unrecognised card is never altered.
    """
    try:
        import numpy as np
    except ImportError:      # pragma: no cover - numpy ships with Pillow's peers
        return img
    from PIL import Image

    if asset is not None and asset.aspect not in ("16:9", ""):
        return img
    out = img.convert("RGBA")
    arr = np.asarray(out).astype(int)
    h, w = arr.shape[:2]
    if not h or not w:
        return img
    fixed_paper = paper
    def inked(x0: int, x1: int, y0: int, y1: int):
        band = arr[max(y0, 0):max(y1, 0), max(x0, 0):max(x1, 0)]
        if not band.size:
            return None
        return (band[..., :3].mean(axis=2) < 205) & (band[..., 3] > 60)

    touched = False
    for top_f, bot_f, probe_f, erase_f, air in FURNITURE_BANDS.values():
        y0, y1 = max(int(top_f * h) - 5, 0), int(bot_f * h) + 6
        ink = inked(0, int(probe_f * w), y0, y1)
        if ink is None or not ink.any():
            continue
        ys, xs = np.nonzero(ink)
        bx0, by0, bx1 = int(xs.min()), y0 + int(ys.min()), int(xs.max())
        by1 = y0 + int(ys.max())
        tol = _FURNITURE_TOL * h / 900.0
        if (abs(bx0 - FURNITURE_LEFT * w) > tol
                or abs(by0 - top_f * h) > tol or abs(by1 - bot_f * h) > tol):
            continue        # not the furniture — leave the card alone
        # Artwork can extend the measured bbox past the text; the text's own
        # width is fixed, so cap the erase rather than trusting the bbox.
        right = min(bx1, int(erase_f * w)) + int(6 * w / 1600)
        gap = int(_FURNITURE_AIR * h)
        near = (inked(0, right, by1 + 2, by1 + gap) if air > 0
                else inked(0, right, by0 - gap, by0 - 2))
        if near is None or near.any():
            continue        # something is pressed up against it — not furniture
        pad = int(4 * h / 900)
        box = (max(bx0 - pad, 0), max(by0 - pad, 0),
               min(right, w), min(by1 + pad, h))
        # The paper is faintly textured and not one flat tone, so the patch is
        # sampled from the air the gate just proved is clear, right beside the
        # box. A single colour read from the far edge left a visible rectangle
        # exactly where the chip had been.
        if fixed_paper is not None:
            paper = fixed_paper
        else:
            near_y = (box[3] + pad, box[3] + pad + 6) if air > 0 else \
                     (max(box[1] - pad - 6, 0), max(box[1] - pad, 1))
            strip = arr[near_y[0]:near_y[1], box[0]:box[2], :3]
            paper = (tuple(int(v) for v in np.median(strip.reshape(-1, 3), axis=0))
                     if strip.size else tuple(int(v) for v in arr[h // 2, w - 3][:3]))
        out.paste(Image.new("RGBA", (box[2] - box[0], box[3] - box[1]),
                            (*paper[:3], 255)), box[:2])
        touched = True
    return out if touched else img


# --------------------------------------------------------------------------
# Framing.
#
# Every beat used to land in the same box at the same size, which is the single
# biggest reason a cut reads as a slideshow rather than an edit. Three
# registers, chosen per beat and then held — the variation is in WHICH shot,
# never in movement inside one. Nothing here pans, zooms or drifts.
# --------------------------------------------------------------------------
FULL_BLEED = "full-bleed"   # the asset IS the frame
STAGE = "stage"             # contain-fit into the stage band
PUNCH = "punch"             # cropped tighter and placed larger, for emphasis


def is_full_frame(asset: Asset, frame_aspect: tuple[int, int]) -> bool:
    """True when the asset was drawn to BE the frame rather than sit in it.

    The eleven `vertical-scenes` assets are 1080x1920 compositions — a person
    at the base of a towering bar, a number falling from the top of frame.
    Fitted into a 1000x760 stage box they become a letterboxed thumbnail of a
    shot, which is the one thing they were built not to be.
    """
    if not asset.canvas[0] or not asset.canvas[1]:
        return False
    want = frame_aspect[0] / frame_aspect[1]
    got = asset.canvas[0] / asset.canvas[1]
    return abs(got - want) / want < 0.06


def cover_on_paper(img, width: int, height: int, paper=(242, 242, 239)):
    """Cover-fit onto an opaque paper plate.

    Full-frame kit assets carry alpha, so composited raw over the stage the
    chart and the sheet would show through the drawing they are meant to have
    replaced.
    """
    from PIL import Image

    ratio = max(width / img.width, height / img.height)
    scaled = img.resize((max(int(img.width * ratio), 1),
                         max(int(img.height * ratio), 1)), Image.LANCZOS)
    plate = Image.new("RGBA", (width, height), (*paper, 255))
    plate.alpha_composite(scaled, (int((width - scaled.width) / 2),
                                   int((height - scaled.height) / 2)))
    return plate


def contain_on_paper(img, width: int, height: int, paper=(242, 242, 239)):
    """Contain-fit onto an opaque paper plate — nothing is cropped away."""
    from PIL import Image

    ratio = min(width / img.width, height / img.height)
    scaled = img.resize((max(int(img.width * ratio), 1),
                         max(int(img.height * ratio), 1)), Image.LANCZOS)
    plate = Image.new("RGBA", (width, height), (*paper, 255))
    plate.alpha_composite(scaled, (int((width - scaled.width) / 2),
                                   int((height - scaled.height) / 2)))
    return plate


def cover_keeps_fraction(asset: Asset, width: int, height: int) -> float:
    """How much of the asset's own frame survives a cover-fit into WxH.

    1.0 when the aspects match. A 16:9 strip cover-fitted into a 9:16 frame
    keeps 0.32 of its width — which is fine for an effect that happens in the
    middle and destroys one that crosses the frame.
    """
    aw, ah = asset.canvas
    if not aw or not ah or not width or not height:
        return 1.0
    ratio = max(width / aw, height / ah)
    return min((width / (aw * ratio)) if aw * ratio else 1.0,
               (height / (ah * ratio)) if ah * ratio else 1.0)


# How much of the crop window a transition has to actually fill, at its
# fullest frame, for a centre crop to be doing its job. Below this the effect
# is happening somewhere the crop cannot see.
TRANSITION_COVER_FLOOR = 0.6


def crop_window_coverage(asset: Asset, settings: Settings, keep: float) -> float:
    """The most of a centre crop window this strip ever covers, 0..1.

    Measured off the frames rather than guessed from the name or the
    `direction` note. The question a transition has to answer is not "does the
    ink stay inside the window" — a full-frame effect always touches the edges
    — but "does the window get covered", because that is what a cut lands
    under. `blackout-drop` fills it down the middle; a strip whose action ran
    up one edge would never reach it, and would play as a blank flicker.
    """
    try:
        import numpy as np
    except ImportError:      # pragma: no cover
        return 1.0
    if keep >= 0.999:
        return 1.0

    lo, hi = (1.0 - keep) / 2.0, 1.0 - (1.0 - keep) / 2.0
    best = 0.0
    for idx in range(asset.frame_count):
        img = render_frame(asset, idx, None, settings)
        a = np.asarray(img.convert("RGBA"))
        ink = a[..., 3] > 40
        w = img.width or 1
        window = ink[:, int(lo * w):max(int(hi * w), int(lo * w) + 1)]
        if window.size:
            best = max(best, float(window.mean()))
    return best


def transition_transform(asset: Asset, width: int, height: int,
                         settings: Settings):
    """How a transition strip should be fitted to the frame.

    The commissioned stings are 16:9 and a short is 9:16, so a cover-fit keeps
    less than a third of their width. For `blackout-drop` that is invisible;
    for `paper-slide`, whose sheet crosses the frame edge to edge, the whole
    effect lands outside the crop and the viewer sees a blank flicker.

    So: cover when the action survives it, contain onto paper when it does
    not. Either way the mismatch is logged with the measured ratio, because a
    transition that crops its own action out is worse than the white flash it
    replaced and nothing said so.
    """
    keep = cover_keeps_fraction(asset, width, height)
    if keep < 0.995:
        covered = crop_window_coverage(asset, settings, keep)
        survives = covered >= TRANSITION_COVER_FLOOR
        log.info(
            "transition %s is %s into a %dx%d frame — a cover-fit keeps %.0f%% "
            "of its width, and the action fills %.0f%% of what is left; %s",
            asset.key, asset.aspect or "?", width, height,
            keep * 100, covered * 100,
            "cropping" if survives
            else "too little to land a cut under, containing onto paper instead")
        if not survives:
            return lambda img: contain_on_paper(img, width, height)
    return lambda img: cover_on_paper(img, width, height)


# Air kept around the slots when a punch tightens the frame, as a fraction of
# the canvas per side.
PUNCH_MARGIN = 0.06


def punch_crop(img, asset: Asset | None, *, keep: float = 0.62):
    """A tighter crop of the same drawing, centred on what it is about.

    Centred on EVERY declared slot, not just the first. Where a slot is is
    where the meaning is, and an asset with two of them is a comparison:
    cropping `see-saw-two-numbers` around its first slot showed `$1.1B` on a
    tilted plank with the `$40M` it is being weighed against outside the
    frame. The crop widens to hold them all rather than losing one, so a
    drawing whose slots span the canvas simply punches less.

    A static crop, chosen once for the beat: the emphasis comes from the
    framing, not from moving the frame.
    """
    keep = min(max(keep, 0.2), 1.0)
    w, h = img.size
    cx, cy = w // 2, h // 2
    if asset is not None and asset.slots:
        scale = max(asset.export_scale or 1, 1)
        boxes = [s.scaled(scale) for s in asset.slots]
        ux0 = min(b[0] for b in boxes)
        uy0 = min(b[1] for b in boxes)
        ux1 = max(b[0] + b[2] for b in boxes)
        uy1 = max(b[1] + b[3] for b in boxes)
        cx, cy = (ux0 + ux1) // 2, (uy0 + uy1) // 2
        # One fraction for both axes, so the drawing keeps its aspect.
        need = max((ux1 - ux0) / max(w, 1), (uy1 - uy0) / max(h, 1))
        keep = min(max(keep, need + 2 * PUNCH_MARGIN), 1.0)
    cw, ch = int(w * keep), int(h * keep)
    x0 = min(max(cx - cw // 2, 0), max(w - cw, 0))
    y0 = min(max(cy - ch // 2, 0), max(h - ch, 0))
    return img.crop((x0, y0, x0 + cw, y0 + ch))


def paste_into_slot(base, asset: Asset, slot_name: str, image):
    """Composite an IMAGE into a declared slot, cover-cropped to fill it.

    The four `the-world` desk scenes each declare a `screen` box and nothing
    ever touched it, so the price chart floated on a blank wall while a monitor
    drawn to hold it sat unused two hundred pixels away. A chart on his screen
    is a shot; a chart on a blank wall is a slide.

    Slots are canvas coordinates and the PNG is `exportScale` times that — the
    same trap the text filler handles, and the reason this lives here rather
    than at the call site.
    """
    from PIL import Image

    slot = asset.slot(slot_name)
    if slot is None:
        log.warning("%s has no slot called %r — image not composited",
                    asset.key, slot_name)
        return base
    x, y, w, h = slot.scaled(asset.export_scale)
    if w <= 0 or h <= 0:
        return base
    src = image.convert("RGBA")
    ratio = max(w / src.width, h / src.height)
    scaled = src.resize((max(int(src.width * ratio), 1),
                         max(int(src.height * ratio), 1)), Image.LANCZOS)
    left = max(int((scaled.width - w) / 2), 0)
    top = max(int((scaled.height - h) / 2), 0)
    base.alpha_composite(scaled.crop((left, top, left + w, top + h)), (x, y))
    return base


def plate(asset: Asset, width: int, height: int, settings: Settings, *,
          values: dict[str, str] | None = None,
          screen: tuple[str, "object"] | None = None,
          y_frac: float = 0.42,
          paper=(242, 242, 239),
          rects: dict[str, tuple[int, int, int, int]] | None = None):
    """A full-frame plate built around one asset.

    The desk scenes are 1:1 and the frame is 9:16, so a desk becomes a plate:
    paper, the scene fitted to the width, sitting at `y_frac` down the frame.
    `screen` is (slot name, image) — how the chart gets onto the monitor.

    `rects`, if given, is filled in with each slot's box in FRAME coordinates.
    Callers need it to point at what they composited: the chart annotation
    circled a spot computed for a chart floating at a known offset, and once
    the chart moved onto the monitor the circle stayed behind on the header.
    """
    from PIL import Image

    img = render_still(asset, values, settings)
    if screen is not None:
        img = paste_into_slot(img, asset, screen[0], screen[1])
    scaled = _resize(img, width, None)
    out = Image.new("RGBA", (width, height), (*paper, 255))
    top = int((height - scaled.height) * min(max(y_frac, 0.0), 1.0))
    left = int((width - scaled.width) / 2)
    out.alpha_composite(scaled, (left, top))
    if rects is not None and img.width:
        ratio = scaled.width / img.width
        for slot in asset.slots:
            sx, sy, sw, sh = slot.scaled(asset.export_scale)
            rects[slot.name] = (left + int(sx * ratio), top + int(sy * ratio),
                                max(int(sw * ratio), 1), max(int(sh * ratio), 1))
    return out


# --------------------------------------------------------------------------
# Transitions.
# --------------------------------------------------------------------------
# The design docs specify the stings and bumpers as 6-frame ink transitions.
# They were never exported — there is no `stings/` family in the registry — so
# every cut in the video fires the same white flash.
#
# The MECHANISM is what is missing, not just the artwork: a family-driven
# picker means the strips drop in as data when they are commissioned, and no
# code changes. Until then the fallback is still one flash, but it is a
# fallback rather than the design.
TRANSITION_FAMILIES: tuple[str, ...] = (
    "stings",          # the commissioned ink transitions
    "type/bumpers",    # the bumper strips
)


# Name suffixes marking an orientation variant of another strip.
# `paper-slide-tall` is the vertical twin of `paper-slide`, not a twelfth
# independent option — offering both in a 9:16 frame means the picker shows
# the cropped one half the time, which is the thing the tall variants were
# commissioned to stop.
ORIENTATION_SUFFIXES: tuple[str, ...] = ("-tall", "-wide", "-vertical")


def _orientation_base(name: str) -> str:
    for suffix in ORIENTATION_SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def transition_asset(kit, seed: str, index: int = 0,
                     frame: tuple[int, int] | None = None) -> Asset | None:
    """One transition strip, or None when none ships.

    Only a real frame SEQUENCE qualifies. A static drawing swept over the
    whole frame for a fifth of a second is not a transition, it is a flicker
    of an unrelated picture — so a family full of stills leaves this None and
    the caller keeps the flash.

    Stepped by `index` rather than hashed, so consecutive cuts in one video are
    guaranteed to differ instead of merely likely to.

    `frame` makes the choice ASPECT-AWARE. Picking uniformly across the family
    let a 9:16 short draw a 16:9 strip, which a cover-fit crops to a third of
    its width — the exact failure the `-tall` variants exist to prevent.

    So the rotation is the matching orientation and nothing else, which also
    settles the twin question: `paper-slide-tall` replaces `paper-slide` in a
    vertical frame rather than competing with it. Falling back to the other
    orientation happens only when NOTHING matches, and is logged, because then
    it means a strip is missing rather than that the cut is fine.
    """
    import hashlib

    candidates = [
        a for fam in TRANSITION_FAMILIES for key in kit.family(fam)
        if (a := kit.get(key)) is not None and a.frame_count > 1
    ]
    if not candidates:
        return None

    if frame:
        matching = [a for a in candidates if is_full_frame(a, frame)]
        if matching:
            # ONLY the matching orientation. Ordering the pool was not enough:
            # the step starts at a hashed offset, so a wide strip still came up
            # first five cuts out of six. A strip that has to be cropped is a
            # last resort, not a member of the rotation.
            candidates = matching
        else:
            log.warning(
                "transitions: no strip matches a %dx%d frame — every cut will "
                "use a %s strip cropped to fit. Tall variants are artwork "
                "owed.", frame[0], frame[1],
                candidates[0].aspect or "mismatched")
            # Everything is going to be cropped, so at least do not offer the
            # same effect twice under two orientation names.
            by_base: dict[str, Asset] = {}
            for a in candidates:
                by_base.setdefault(_orientation_base(a.name), a)
            candidates = list(by_base.values())

    keys = [a.key for a in candidates]
    offset = int(hashlib.sha256(f"transition|{seed}".encode()).hexdigest()[:8], 16)
    return kit.get(keys[(offset + index) % len(keys)])
