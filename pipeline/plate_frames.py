"""Playing plates, and filling their slots.

Two jobs that have to agree with each other, so they live together.

**Playback.** 96 of the 143 plates are two-frame loops; the other 47 are data
plates that deliberately never boil, because a figure that moves is a figure
being re-read. The registry says which is which, at what rate and over how many
frames, and :func:`frame_indices` turns that into one source-frame index per
output frame. There is no per-family branch anywhere in this module: the next
delivery adds artwork, not code.

**Slots.** 1,444 declared boxes across the library, and every word on screen
comes out of one — the plates carry no baked text at all. Filling one honours
the plate's own ``typeRoles``: font, size, weight, colour ROLE, tracking, case
and ``maxChars``.

That last part is the change worth naming. Type sizes belong to the PLATE, and
the plate declares them, so the renderer sets rather than guesses. The previous
version fitted every value to its box by shrinking until it fit, which meant a
long label and a short one on the same sheet came out at different sizes — the
plate had reserved a column at one size and the renderer quietly ignored it.
Here the declared size is what gets set, ``maxChars`` is a hard limit the way
the manifest says it is, and shrinking is the fallback for an overflow rather
than the mechanism.

Two traps, both silent when missed, both handled here rather than at each call
site:

* ``exportScale`` is 2 — slot boxes are canvas units and the PNGs are double
  that. Compositing against raw pixels without scaling puts every figure at
  exactly half its intended position, on a drawing that still looks fine.
* **Slots are not clipped to the canvas.** Twelve annotation slots sit outside
  their own plate on purpose, because a mark is composited onto something else
  and its caption lands beside the mark. Clipping drops them silently.
"""

from __future__ import annotations

import logging
from pathlib import Path

from config import Settings
from pipeline.plates import Plate, Registry, Slot

log = logging.getLogger(__name__)

# The kit names two families and nothing else, and ships both. A manifest that
# names a font it does not ship renders wrong silently — the renderer
# substitutes, every plate is subtly off, and nobody notices until it is out.
#
# Archivo Narrow is a VARIABLE font covering the whole 400–700 axis, which is
# every weight the typeRoles reference. Do not substitute another narrow
# grotesque: the maxChars in every typeRoles table were measured against this
# face, and a wider one overflows cells the manifest promises fit.
_VARIABLE = {"archivo narrow": "ArchivoNarrow[wght].ttf"}
_STATIC = {
    ("courier prime", 700): "CourierPrime-Bold.ttf",
    ("courier prime", 400): "CourierPrime-Regular.ttf",
}
_FALLBACK = "CourierPrime-Regular.ttf"

# When a plate declares no size for a role, the box decides — but that is the
# exception, not the mechanism. 103 of 143 plates carry a typeRoles table.
_MIN_PT = 8
_FIT_STEPS = 48


# --------------------------------------------------------------------------
# Playback
# --------------------------------------------------------------------------
def frame_indices(plate: Plate, duration_s: float, fps: int) -> list[int]:
    """One source-frame index per output frame, for `duration_s` at `fps`.

    Driven entirely by ``playback``/``frameCount``/``fps`` from the registry.
    ``static`` holds its single frame; ``loop`` cycles the strip at the plate's
    own rate, which is slower than the output frame rate on purpose — a boil is
    a hand redrawing a line, not an animation.
    """
    n_out = max(int(round(max(duration_s, 0.0) * fps)), 1)
    n_src = max(plate.frame_count, 1)
    if n_src == 1 or plate.playback == "static":
        return [0] * n_out
    rate = plate.fps or fps
    if plate.playback == "one-shot":
        return [min(int(i / fps * rate), n_src - 1) for i in range(n_out)]
    return [int(i / fps * rate) % n_src for i in range(n_out)]


def playback_seconds(plate: Plate) -> float:
    """How long one pass through the strip takes."""
    if plate.frame_count <= 1 or plate.playback == "static":
        return 0.0
    return plate.frame_count / float(plate.fps or 12)


# --------------------------------------------------------------------------
# Type
# --------------------------------------------------------------------------
def _face_for(family: str, weight: int) -> tuple[str, int | None]:
    """`("Archivo Narrow", 700)` -> the file, and the axis value to set."""
    fam = (family or "").strip().lower()
    if fam in _VARIABLE:
        return _VARIABLE[fam], max(400, min(int(weight or 400), 700))
    for w in (700, 400):
        if (fam, w) in _STATIC:
            if int(weight or 400) >= 600 and (fam, 700) in _STATIC:
                return _STATIC[(fam, 700)], None
            return _STATIC[(fam, 400)], None
    return _FALLBACK, None


def _load(settings: Settings, family: str, weight: int, size: int):
    from PIL import ImageFont

    face, axis = _face_for(family, weight)
    font = ImageFont.truetype(str(settings.fonts_dir / face), max(int(size), 1))
    if axis is not None:
        try:
            font.set_variation_by_axes([axis])
        except Exception:          # a FreeType without variable support
            log.debug("no variable-font support; %s stays at its default weight",
                      face)
    return font


def type_role(plate: Plate, slot: Slot, value: str = "") -> dict:
    """The plate's declared type for this slot's role, or an empty dict.

    A plate may declare a role PAIR — `move` in ``down`` beside `moveUp` in
    ``up`` — and then the value's sign chooses, because that is the only thing
    a pair like that can mean. The renderer was always taking the base role,
    so on the peer strip a positive figure drew in the fall colour: gross
    margin of 60 in red. Red means down and nothing else, and it does not get
    to mean it about a number that went up.
    """
    roles = plate.type_roles or {}
    up = roles.get(f"{slot.role}Up")
    if up and _positive(value):
        return up or {}
    return roles.get(slot.role, {}) or {}


def budget(plate: Plate, slot: Slot, value: str = "") -> dict:
    """The type spec for this slot, with the budget for THIS BOX applied.

    `maxChars` lives in two places and they mean different things:

    * ``slots[name].maxChars`` is the number for that box, derived from its own
      width and the face it is set in. It is what an audit must read.
    * ``typeRoles[role].maxChars`` is the FLOOR — the narrowest slot on the
      plate that sets the role.

    So the slot's own number wins where it has one, and the role's stands in
    where it does not. Keeping the floor as the fallback is what makes a reader
    that only knows about roles stay inside every box rather than silently go
    loose: too wide a budget waves through copy that collides with the rule
    beside it, which is the direction that breaks a render.
    """
    spec = dict(type_role(plate, slot, value))
    for key, own in (("maxChars", slot.max_chars),
                     ("maxCharsPerLine", slot.max_chars_per_line),
                     ("maxLines", slot.max_lines)):
        if own:
            spec[key] = own
    return spec


def _positive(value: str) -> bool:
    """Whether a written figure reads as a rise. Unparseable is not a rise."""
    text = str(value or "").strip()
    if not text:
        return False
    cleaned = "".join(c for c in text if c.isdigit() or c in ".-+")
    try:
        return float(cleaned) > 0
    except ValueError:
        return False


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
    are set wide enough that drawing them solid reads as a different plate."""
    if tracking_px <= 0:
        draw.text(xy, text, font=font, fill=fill)
        return
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += draw.textlength(ch, font=font) + tracking_px


# A face's visible extent, measured once per size on a reference that carries
# a cap, an x-height and a descender. NOT `ascent + descent`: that is the em
# box, which stands taller than any glyph by the internal leading, and a slot
# box in the manifest is drawn around the type as it appears. On
# `cards/definition-16x9` the gap is 218px of em box against 133px of ink in a
# 176px slot — enough to shrink a declared 76pt term to 58pt to "fit" a box it
# already sat inside. Every single-line slot in the library was doing it.
#
# Measured on a fixed reference rather than on the string, so "Revenue" and
# "Margin (%)" sit on the same baseline. A per-string bbox would centre each
# cell on its own ink and stagger a table row by the height of a descender.
_INK_REF = "Hg"


def _ink_extent(font) -> tuple[int, int]:
    """`(top offset, height)` of one line of this face, in pixels."""
    _, top, _, bottom = font.getbbox(_INK_REF)
    return top, max(bottom - top, 1)


def _tracked_width(draw, text: str, font, tracking_px: float) -> float:
    w = draw.textlength(text, font=font)
    return w + tracking_px * max(len(text) - 1, 0) if tracking_px > 0 else w


def _em(value, size: int) -> float:
    """`".16em"` at a given size, in pixels."""
    if not value:
        return 0.0
    try:
        s = str(value).strip()
        return float(s[:-2]) * size if s.endswith("em") else float(s)
    except ValueError:
        return 0.0


def _in_last_column(plate: Plate, slot: Slot) -> bool:
    """Whether this slot is the rightmost of its row or header family.

    `cell-2-6` against `cell-2-1 … cell-2-6`, `head-6` against `head-1 … head-6`.
    Read off the slots the plate declares rather than off PERIOD_COUNT, because
    `charts/line-dense` is authored four heads wide on purpose.
    """
    stem, _, tail = slot.name.rpartition("-")
    if not stem or not tail.isdigit():
        return False
    peers = [int(n.rpartition("-")[2]) for n in plate.slots
             if n.rpartition("-")[0] == stem and n.rpartition("-")[2].isdigit()]
    return bool(peers) and int(tail) == max(peers)


def fill_slot(img, plate: Plate, slot: Slot, value: str, settings: Settings,
              reg: Registry, *, origin: tuple[int, int] | None = None) -> list[str]:
    """Composite `value` into `slot` on `img`, in place. Returns warnings.

    The type comes from the plate's ``typeRoles`` for this slot's role. A
    declared size is SET, not fitted — the plate reserved that column at that
    size — and it only shrinks when the value genuinely will not fit, which is
    a warning, because ``maxChars`` is a hard limit in the manifest and going
    over it means the line collides with rules drawn in ink.
    """
    from PIL import ImageDraw

    warnings: list[str] = []
    text = str(value if value is not None else "").strip()
    if not text:
        return warnings

    tr = budget(plate, slot, text)
    transform = str(tr.get("transform", "")).lower()
    if transform == "uppercase":
        text = text.upper()
    elif transform == "lowercase":
        text = text.lower()

    max_chars = tr.get("maxChars")
    if max_chars and len(text) > int(max_chars):
        warnings.append(
            f"{plate.key} {slot.name}: {len(text)} characters against a "
            f"declared limit of {max_chars} — the plate reserved that width, "
            f"and over it the line collides with ink")

    scale = max(int(plate.export_scale or 1), 1)
    ox, oy = origin if origin is not None else (slot.x, slot.y)
    x0, y0 = ox * scale, oy * scale
    bw, bh = slot.w * scale, slot.h * scale
    if bw <= 0 or bh <= 0:
        return warnings

    draw = ImageDraw.Draw(img)
    family = tr.get("font", "Courier Prime")
    weight = int(tr.get("weight", 400) or 400)
    # Ten sheets set their last column heavier: LTM is the column the argument
    # usually turns on, and the kit says so in the typeRole rather than leaving
    # it to a renderer to decide what to emphasise.
    if tr.get("lastColumnWeight") and _in_last_column(plate, slot):
        weight = int(tr["lastColumnWeight"])
    colour_role = tr.get("colour", "structure")
    try:
        rgb = reg.colour(colour_role)
    except Exception:
        rgb = reg.colour("structure")
    alpha = int(round(255 * float(tr.get("opacity", 1.0) or 1.0)))
    fill = (*rgb, max(0, min(alpha, 255)))

    declared = tr.get("size")
    size = int(int(declared) * scale) if declared else max(int(bh * 0.8), _MIN_PT)
    declared_lines = tr.get("maxLines")

    lines = [text]
    for step in range(_FIT_STEPS):
        font = _load(settings, family, weight, size)
        tracking_px = _em(tr.get("tracking"), size)
        ascent, descent = font.getmetrics()
        line_h = int((ascent + descent) * 1.06)
        _, ink_h = _ink_extent(font)

        # THE BOX HEIGHT IS A DECLARATION TOO.
        #
        # `structure/flow-16x9`'s boxes are 256 wide and 216 tall and allow 30
        # characters — thirty characters of 34pt Archivo do not go on one 256
        # unit line, and the box is four lines tall because it is meant to
        # wrap. Requiring an explicit `maxLines` before wrapping read that box
        # as a single line and shrank a 24-character step to 25pt to make it
        # one. A box holds as many lines as it has room for, unless the kit
        # names a smaller number.
        capacity = max(1, (bh - ink_h) // line_h + 1)
        max_lines = int(declared_lines) if declared_lines else capacity
        wrap = max_lines > 1 or bool(tr.get("maxCharsPerLine"))

        lines = _wrap_to(draw, text, font, bw) if wrap else [text]
        widest = max(_tracked_width(draw, ln, font, tracking_px) for ln in lines)
        block_h = (len(lines) - 1) * line_h + ink_h
        fits = widest <= bw and block_h <= bh and len(lines) <= max_lines
        if fits or size <= _MIN_PT:
            if step and declared:
                warnings.append(
                    f"{plate.key} {slot.name}: set at {size // scale}pt instead "
                    f"of the declared {declared}pt to fit {len(text)} characters")
            break
        size = max(int(size * 0.94), _MIN_PT)

    font = _load(settings, family, weight, size)
    tracking_px = _em(tr.get("tracking"), size)
    ascent, descent = font.getmetrics()
    line_h = int((ascent + descent) * 1.06)
    ink_top, ink_h = _ink_extent(font)
    block_h = (len(lines) - 1) * line_h + ink_h

    # `y` is where PIL starts the em box; the ink starts `ink_top` below it.
    # Aligning the box instead of the ink hangs type off the top of its slot
    # by the internal leading, which on a big figure is a visible drop.
    valign = str(tr.get("valign", "middle")).lower()
    if valign == "top":
        y = y0 - ink_top
    elif valign == "bottom":
        y = y0 + bh - block_h - ink_top
    else:
        y = y0 + (bh - block_h) // 2 - ink_top

    for line in lines:
        lw = _tracked_width(draw, line, font, tracking_px)
        if slot.align == "right":
            x = x0 + bw - lw
        elif slot.align in ("center", "centre"):
            x = x0 + (bw - lw) / 2
        else:
            x = x0
        _draw_tracked(draw, (x, y), line, font, fill, tracking_px)
        y += line_h
    return warnings


# --------------------------------------------------------------------------
# Rendering a plate
# --------------------------------------------------------------------------
def render_frame(plate: Plate, frame_index: int, values: dict[str, str] | None,
                 settings: Settings, reg: Registry):
    """One frame of a plate with its slots filled, as an RGBA image."""
    from PIL import Image

    idx = min(max(frame_index, 0), len(plate.frames) - 1)
    img = Image.open(plate.frame_paths()[idx]).convert("RGBA")
    if not values:
        return img

    unknown = set(values) - set(plate.slots)
    if unknown:
        log.warning("%s has no slot named %s — value dropped",
                    plate.key, ", ".join(sorted(unknown)))

    # Row bands go down FIRST, under the figures: a band is a highlight on the
    # row, not a wash over it. `overlays/row-band` stretches in X ONLY — in Y
    # its hatch degenerates into a slab.
    for name, slot in plate.slots.items():
        if slot.overlay and str(values.get(name) or "").strip():
            band = reg.get(slot.overlay)
            if band is not None:
                _paste_band(img, band, slot, plate.export_scale)

    for name, slot in plate.slots.items():
        value = values.get(name)
        if value in (None, "") or not slot.is_text:
            continue
        for w in fill_slot(img, plate, slot, value, settings, reg):
            log.warning("%s", w)
    return img


def _paste_band(img, band: Plate, slot: Slot, export_scale: int) -> None:
    """Stretch a row band across a slot — in X only, native height, centred."""
    from PIL import Image

    src = Image.open(band.path).convert("RGBA")
    scale = max(int(export_scale or 1), 1)
    x, y, w, h = slot.x * scale, slot.y * scale, slot.w * scale, slot.h * scale
    if w <= 0 or h <= 0:
        return
    stretched = src.resize((w, src.height), Image.LANCZOS)
    top = y + (h - stretched.height) // 2
    img.alpha_composite(stretched, (x, top))


def render_still(plate: Plate, values: dict[str, str] | None,
                 settings: Settings, reg: Registry):
    """The frame to show when a plate is used as a still — always frame one.

    Which is the base file, byte for byte, on every boiling plate in the kit.
    """
    return render_frame(plate, 0, values, settings, reg)


def drawn_box(plate: Plate, slot: Slot, value: str, settings: Settings,
              reg: Registry) -> tuple[int, int, int, int] | None:
    """The box the TYPE occupies in a slot, in delivered pixels. None if empty.

    A MARK GOES ON THE TYPE, NOT ON THE SLOT RECTANGLE — `solve_mark` says so
    and then can only work with the box it is handed. `unit-ladder`'s value
    column is a third of the sheet wide and its figures are right-aligned
    three characters into it, so a strike solved onto the rectangle runs from
    the labels to past the plate's edge and crosses out the row below.

    Measured by drawing rather than by re-deriving the fit, so it cannot drift
    from what `fill_slot` actually puts down.
    """
    from PIL import Image

    scale = max(int(plate.export_scale or 1), 1)
    w, h = slot.w * scale, slot.h * scale
    if w <= 0 or h <= 0 or not str(value or "").strip():
        return None
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    fill_slot(img, plate, slot, value, settings, reg, origin=(0, 0))
    ink = img.getbbox()
    if ink is None:
        return None
    return (slot.x * scale + ink[0], slot.y * scale + ink[1],
            max(ink[2] - ink[0], 1), max(ink[3] - ink[1], 1))


def unfilled_slots(plate: Plate, values: dict[str, str] | None) -> list[str]:
    """What this plate declares that `values` leaves empty.

    An empty cell in this library means NO DATA, and that is information — so
    this reports rather than fails.

    Two kinds count. A TEXT box with nothing in it, and a slot with a
    ``renderer`` that was handed no figures: `peers/peer-strip`'s bars are
    drawn into the plate as placeholder lengths, so a strip whose bars nobody
    filled ships four bars of invented data rather than an empty box — the
    worse of the two failures, and the one that looks most like a design
    choice. Reserved AREAS are excluded: a ``host-anchor`` is not something a
    script fills.
    """
    values = values or {}
    def empty(name: str) -> bool:
        return not str(values.get(name) or "").strip()
    return sorted(n for n, s in plate.slots.items()
                  if (s.is_text or s.renderer) and empty(n))


def render_clip(plate: Plate, values: dict[str, str] | None, duration_s: float,
                settings: Settings, reg: Registry, out: Path, fps: int = 24) -> Path:
    """A plate played for `duration_s`, as a PNG sequence directory."""
    out.mkdir(parents=True, exist_ok=True)
    cache: dict[int, object] = {}
    for i, src in enumerate(frame_indices(plate, duration_s, fps)):
        if src not in cache:
            cache[src] = render_frame(plate, src, values, settings, reg)
        cache[src].save(out / f"f{i:05d}.png")
    return out


# --------------------------------------------------------------------------
# Fitting
# --------------------------------------------------------------------------
def fit_into(img, box_w: int, box_h: int):
    """Contain `img` inside a box, preserving aspect. Never upscales past 1:1."""
    from PIL import Image

    if box_w <= 0 or box_h <= 0:
        return img
    ratio = min(box_w / img.width, box_h / img.height)
    if ratio >= 1.0:
        return img
    return img.resize((max(int(img.width * ratio), 1),
                       max(int(img.height * ratio), 1)), Image.LANCZOS)


def _resize_to(img, width: int | None, height: int | None):
    """Resize to a target width or height, preserving aspect."""
    from PIL import Image

    if not width and not height:
        return img
    if width and height:
        w, h = width, height
    elif width:
        w = width
        h = max(int(round(img.height * (width / img.width))), 1)
    else:
        h = height
        w = max(int(round(img.width * (height / img.height))), 1)
    return img.resize((max(w, 1), max(h, 1)), Image.LANCZOS)


def cover_into(img, box_w: int, box_h: int):
    """Fill a box completely, cropping the overflow — for foreign media."""
    from PIL import Image

    if box_w <= 0 or box_h <= 0 or img.width == 0 or img.height == 0:
        return img
    ratio = max(box_w / img.width, box_h / img.height)
    w, h = max(int(img.width * ratio), 1), max(int(img.height * ratio), 1)
    scaled = img.resize((w, h), Image.LANCZOS)
    left, top = (w - box_w) // 2, (h - box_h) // 2
    return scaled.crop((left, top, left + box_w, top + box_h))


def paste_into_slot(base, plate: Plate, slot_name: str, image):
    """Composite an image into a named region — cover-fitted to its box."""
    slot = plate.slot(slot_name)
    if slot is None:
        raise KeyError(f"{plate.key} has no slot {slot_name!r}")
    x, y, w, h = slot.scaled()
    base.alpha_composite(cover_into(image.convert("RGBA"), w, h), (x, y))
    return base
