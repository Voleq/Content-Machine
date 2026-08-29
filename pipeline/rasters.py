"""What the kit does not draw: captions, alpha clips, and figure animation.

Everything with a plate equivalent has gone. This module existed because the
renderer had to draw what the kit did not ship — sheets, cards, panels, chapter
stingers, backdrops — and the kit now ships all of it. What is left is the work
that is genuinely not a plate:

* **captions** (`build_phrase_ass`, `phrase_pages`) — ASS subtitles, which are
  a text format rather than a drawing
* **alpha clips** (`frames_to_alpha_clip`) — the encode step every animated
  overlay goes through
* **figure animation** (`count_up_frames`, `roll_steps`, `roll_over_lines`) — a
  number counting up is a value CHANGING over time, and a plate is one moment
* **annotation marks** (`fitted_mark`, `mark_frames`) — solving an
  `annotations/` cut-out onto a target and drawing it on
* **small utilities** (`simple_text`, `drawn_rect`, `flash_frames`,
  `cover_fill_frame`)

THERE ARE NO COLOUR CONSTANTS HERE ANY MORE. `INK`, `RED`, `GREEN`, `PANEL` and
`CARD_LINE` named a palette that no longer exists, and worse, `RED` carried both
"this went down" and "look at this" — so nothing on screen could tell the two
apart. Colour is asked for by ROLE through the registry
(`pipeline.plates.Registry.colour`): ground, second-ground, structure, down, up,
neutral-data, attention, other-party. Red means down. Emphasis is attention.
"""

from __future__ import annotations

import logging
import math
import random
import re
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from config import Settings
from pipeline.models import WordTimestamp
from pipeline.render_common import run_ffmpeg

log = logging.getLogger(__name__)

# The two faces the kit ships, and the only two anything here may set. Every
# plate's typeRoles names one of them; a third face in a caption is a third
# voice on screen.
ARCHIVO = "ArchivoNarrow[wght].ttf"
COURIER = "CourierPrime-Regular.ttf"
COURIER_BOLD = "CourierPrime-Bold.ttf"


def role(settings: Settings, name: str) -> tuple[int, int, int]:
    """A palette colour, BY ROLE, off the registry.

    The one way anything in this module gets a colour. There is no hex here to
    go stale, and no name that means two things: ``down`` is a fall, and
    emphasis is ``attention``.
    """
    from pipeline.plates import load_plates

    return load_plates(settings.assets_dir).colour(name)


def load_font(settings: Settings, name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(settings.fonts_dir / name), size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        words = para.split()
        cur = ""
        for w in words:
            trial = f"{cur} {w}".strip()
            if draw.textlength(trial, font=font) <= max_width or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
    return lines
def simple_text(
    settings: Settings,
    text: str,
    *,
    font_name: str = COURIER_BOLD,
    font_size: int = 44,
    fill=None,
    stroke_width: int = 0,
    stroke_fill=None,
) -> Image.Image:
    fill = fill if fill is not None else (*role(settings, "structure"), 255)
    stroke_fill = (stroke_fill if stroke_fill is not None
                   else (*role(settings, "ground"), 255))
    font = load_font(settings, font_name, font_size)
    probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    w = int(probe.textlength(text, font=font)) + 2 * stroke_width + 8
    ascent, descent = font.getmetrics()
    h = ascent + descent + 2 * stroke_width + 6
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.text((stroke_width + 4, stroke_width + 2), text, font=font, fill=fill,
           stroke_width=stroke_width, stroke_fill=stroke_fill)
    return img
def _cover(img: Image.Image, W: int, H: int) -> Image.Image:
    """Scale + centre-crop `img` to exactly WxH (cover fit, no bars)."""
    scale = max(W / img.width, H / img.height)
    bw, bh = max(int(img.width * scale), W), max(int(img.height * scale), H)
    resized = img.resize((bw, bh), Image.LANCZOS)
    ox, oy = (bw - W) // 2, (bh - H) // 2
    return resized.crop((ox, oy, ox + W, oy + H))


def cover_fill_frame(
    src,
    width: int,
    height: int,
    *,
    ground: tuple[int, int, int],
    line: tuple[int, int, int],
    keep_min: float = 0.72,
    blur: int = 26,
    darken: float = 0.5,
    border: bool = True,
) -> Image.Image:
    """One media still, composed to fill a WxH frame in the Dennis look.

    If the media's aspect is close enough to the target that a cover-crop
    keeps at least `keep_min` of it, the media fills the frame edge-to-edge
    (real photos become the background). Otherwise — logos, tall phone
    grabs, panoramas — the media is CONTAINed sharp over a blurred, darkened,
    brand-tinted cover of itself, so it still reads as a designed full-frame
    shot and never a letterboxed black frame.
    """
    img = (src if isinstance(src, Image.Image) else Image.open(src)).convert("RGB")
    W, H = width, height
    src_ar, dst_ar = img.width / img.height, W / H
    kept = min(src_ar / dst_ar, dst_ar / src_ar)  # fraction of area cover keeps
    if kept >= keep_min:
        return _cover(img, W, H)

    bg = ImageEnhance.Brightness(_cover(img, W, H).filter(
        ImageFilter.GaussianBlur(blur))).enhance(darken)
    bg = Image.blend(bg, Image.new("RGB", (W, H), ground), 0.42)
    fg = img.copy()
    fg.thumbnail((int(W * 0.92), int(H * 0.9)), Image.LANCZOS)
    ox, oy = (W - fg.width) // 2, (H - fg.height) // 2
    bg.paste(fg, (ox, oy))
    if border:
        ImageDraw.Draw(bg).rectangle(
            [ox - 2, oy - 2, ox + fg.width + 1, oy + fg.height + 1],
            outline=line, width=2)
    return bg


# the designed filler families — visually distinct looks so consecutive
# filler beats never read as "the same scene on repeat"
LONG_BACKDROP_FAMILIES = 5
def frames_to_alpha_clip(frames: list[Image.Image], fps: int, out_path: Path) -> Path:
    """Encode RGBA frames once into a PNG-codec .mov (alpha preserved)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="frames_") as td:
        for i, frame in enumerate(frames):
            frame.save(Path(td) / f"f_{i:05d}.png")
        run_ffmpeg([
            "-framerate", str(fps),
            "-i", str(Path(td) / "f_%05d.png"),
            "-c:v", "png", "-pix_fmt", "rgba", str(out_path),
        ])
    return out_path
def flash_frames(w: int, h: int, *, fps: int = 30,
                 flash_seconds: float = 0.14) -> list[Image.Image]:
    """A white flash stinger for beat transitions."""
    n = max(int(flash_seconds * fps), 2)
    frames = []
    for k in range(n + 1):
        p = k / n
        alpha = int(190 * (1 - p))
        img = Image.new("RGBA", (w, h), (255, 255, 255, alpha))
        frames.append(img)
    return frames


# --------------------------------------------------------------------------
# ASS karaoke captions (libass `subtitles` filter burns these in) — the
# word-synced punch-in style, driven by the real audio timestamps.
# --------------------------------------------------------------------------


def _ass_time(t: float) -> str:
    t = max(t, 0.0)
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"
def phrase_pages(
    words: list[WordTimestamp],
    *,
    max_words: int = 6,
    max_chars: int = 30,
    max_gap: float = 0.45,
) -> list[list[WordTimestamp]]:
    """Group words into caption lines that break on phrase boundaries.

    Three things end a line, in priority order: sentence-final punctuation, a
    real pause in the delivery, and clause punctuation once the line is long
    enough to be worth breaking. The length caps are a backstop, and when one
    fires it walks back off a function word rather than stranding it.
    """
    pages: list[list[WordTimestamp]] = []
    page: list[WordTimestamp] = []

    def flush() -> None:
        nonlocal page
        if page:
            pages.append(page)
            page = []

    for i, w in enumerate(words):
        page.append(w)
        text = w.word.strip()
        n_chars = sum(len(x.word) + 1 for x in page) - 1
        nxt = words[i + 1] if i + 1 < len(words) else None
        gap = (nxt.start - w.end) if nxt else 0.0

        hard = bool(re.search(r"[.!?…]$", text))
        soft = bool(_PHRASE_END.search(text)) and len(page) >= 3
        paused = nxt is not None and gap >= max_gap and len(page) >= 2
        full = len(page) >= max_words or n_chars >= max_chars

        if hard or soft or paused:
            flush()
        elif full:
            # Walk back off a dangling function word so the break lands
            # somewhere a reader would have paused anyway.
            if len(page) > 2 and page[-1].word.strip(".,;:!?").lower() in _NEVER_LAST:
                carry = page.pop()
                flush()
                page = [carry]
            else:
                flush()
    flush()
    return pages


def build_phrase_ass(
    words: list[WordTimestamp],
    *,
    settings: Settings,
    play_res: tuple[int, int],
    font_size: int = 62,
    margin_v: int = 300,
    margin_h: int = 70,
    max_words: int = 6,
    max_chars: int = 30,
    duration: float | None = None,
    punch: bool = True,
) -> str:
    """The SHORT's captions: structure ink on the ground, phrase by phrase.

    Not karaoke. The word-by-word red fill was doing two things at once —
    colouring text in the same red that means a down-move, and drawing the eye
    along a line that had already been split mid-clause. This is one legible
    phrase at a time, in the same ink as everything else on the frame.

    `punch` gives each line a 60ms scale-up on entry. It is the caption half of
    the motion layer: enough to register as a cut, not enough to bounce.
    """
    W, H = play_res

    def bgr(c):  # ASS colours are &HAABBGGRR
        r, g, b = c
        return f"&H00{b:02X}{g:02X}{r:02X}"

    ink = role(settings, "structure")

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caps,Archivo Narrow,{font_size},{bgr(ink)},{bgr(ink)},&H0AF6F9FA,&H0AF6F9FA,-1,0,0,0,100,100,0,0,3,14,0,2,{margin_h},{margin_h},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events: list[str] = []
    pages = phrase_pages(words, max_words=max_words, max_chars=max_chars)
    for i, page in enumerate(pages):
        start = page[0].start
        if i + 1 < len(pages):
            end = max(pages[i + 1][0].start, page[-1].end)
        else:
            end = page[-1].end + 0.7
        if duration is not None:
            end = min(end, duration)
        if end <= start:
            continue
        text = " ".join(w.word for w in page)
        prefix = "{\\fscx92\\fscy92\\t(0,60,\\fscx100\\fscy100)}" if punch else ""
        events.append(
            f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Caps,,0,0,0,,{prefix}{text}"
        )
    return header + "\n".join(events) + "\n"


# --------------------------------------------------------------------------
# Motion layer.
#
# Every one of these takes a finished still and returns the frames that bring
# it on. They are deliberately transforms rather than bespoke animations: the
# artwork is already drawn, and the motion is how it ARRIVES. Nothing here
# pans or zooms a held frame — the movement is entry only, and then it stops.
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# The drawn primitives.
#
# The kit is a pen on paper: every border in it is a stroke, not a geometric
# rule. These live here rather than in `chart.py` because every module now
# draws with them — both charts, the thumbnail, and every card in this file —
# and a card that frames itself with `rounded_rectangle` is advertising a
# different product from the one it is part of.
# --------------------------------------------------------------------------


def marker_stroke(d, pts, rng, *, width, color, jitter, passes=2):
    """A marker line: the polyline drawn a few times with per-point jitter
    and a chunky nib — the crude hand-drawn look."""
    for _ in range(passes):
        wobbled = [(x + rng.uniform(-jitter, jitter),
                    y + rng.uniform(-jitter, jitter)) for x, y in pts]
        d.line(wobbled, fill=color, width=width, joint="curve")


def drawn_rect(d, box, rng, *, width, color, jitter=1.6, passes=1,
                overshoot=0.0):
    """A rectangle drawn by hand: four strokes, not a rounded_rectangle.

    `overshoot` runs each stroke past its corner by that fraction of the side,
    the way a pen does when you do not lift it — which is what stops four
    jittered lines from reading as a rectangle with bad anti-aliasing.
    """
    x0, y0, x1, y1 = box
    ox, oy = (x1 - x0) * overshoot, (y1 - y0) * overshoot
    for a, b in (((x0 - ox, y0), (x1 + ox, y0)),
                 ((x1, y0 - oy), (x1, y1 + oy)),
                 ((x1 + ox, y1), (x0 - ox, y1)),
                 ((x0, y1 + oy), (x0, y0 - oy))):
        marker_stroke(d, [a, b], rng, width=width, color=color,
                       jitter=jitter, passes=passes)


def stroke_inset(box, *, width, jitter, overshoot) -> tuple[int, int]:
    """`(x, y)` — how far inside `box` a `drawn_rect` has to start.

    A pen stroke reaches past the geometry it is drawn against in three ways:
    it overshoots the corner, it wobbles by `jitter`, and it has a nib. Every
    card in this module is measured somewhere else — the numbers sheet returns
    a layout that positions every row overlay, a hook card's height decides
    where the stage begins — so the stroke moves inward and the box does not
    grow.
    """
    w, h = abs(box[2] - box[0]), abs(box[3] - box[1])
    reach = jitter + width / 2 + 1
    return (int(math.ceil(w * overshoot + reach)),
            int(math.ceil(h * overshoot + reach)))
# A mark's nib, in delivered pixels. A plate downscaled onto a small target
# loses its stroke before it loses its shape, so the alpha is grown back to a
# floor — otherwise a tight oval around one cell arrives as a grey smudge.
MARK_NIB_PX = 11
MARK_MIN_NIB_PX = 5


# An annotation's style IS its plate name. The old table mapped twelve invented
# style words onto the retired `marks/` family; there is nothing left to map,
# because `[SCRIBBLE: strike-out -> …]` resolves to `annotations/strike-out`.
# `pipeline.models.SCRIBBLE_ALIASES` catches what a writer is likely to type
# instead ("circle", "underline") so a beat is never lost over a synonym.
#
# The second element is the procedural stroke drawn when the plate cannot be
# loaded. Decoration is never allowed to fail a render.
SCRIBBLE_MARKS: dict[str, tuple[str, str]] = {
    "scrawl-oval-wide": ("annotations/scrawl-oval-wide", "circle"),
    "scrawl-oval-tight": ("annotations/scrawl-oval-tight", "circle"),
    "underline-swipe": ("annotations/underline-swipe", "underline"),
    "underline-tight": ("annotations/underline-tight", "underline"),
    "strike-out": ("annotations/strike-out", "cross-out"),
    "box-scrawl": ("annotations/box-scrawl", "box"),
    "bracket-rows": ("annotations/bracket-rows", "bracket"),
    "arrow-elbow": ("annotations/arrow-elbow", "arrow"),
    "caret-note": ("annotations/caret-note", "caret"),
    "tick-marks": ("annotations/tick-marks", "check"),
}

# The legible band for a solved mark's stroke, in canvas units. The kit warns
# when `inkWeight x solve` leaves it: below, the mark is a hairline nobody sees;
# above, it is a smear over the thing it was meant to point at.
#
# SOLVE SCALE IS NOT THE METRIC. A tight mark reads fine at 0.4x and a wide mark
# at 0.4x is a hairline — the first version of this check compared scale alone
# and told the operator to use the tight mark they were already using.
INK_WEIGHT_BAND = (3.2, 26.0)


def mark_image(settings: Settings, key: str) -> Image.Image | None:
    """Frame one of an `annotations/` plate, or None.

    Never raises: a caller that cannot find its mark draws one rather than
    failing to render, which is the only sane failure mode for decoration.
    """
    try:
        from pipeline.plates import load_plates

        plate = load_plates(settings.assets_dir).get(key)
        if plate is None or not plate.frames:
            return None
        return Image.open(plate.frame_paths()[0]).convert("RGBA")
    except Exception:  # noqa: BLE001 — decoration is never fatal
        log.debug("no %s in the kit — the mark will be drawn instead", key)
        return None


def thicken_mark(img: Image.Image, radius: int) -> Image.Image:
    """Grow a mark's alpha, so a downscaled stroke keeps a legible nib."""
    if radius <= 0:
        return img
    a = img.getchannel("A").filter(ImageFilter.MaxFilter(2 * radius + 1))
    out = img.copy()
    out.putalpha(a)
    return out


def tint_mark(img: Image.Image, color) -> Image.Image:
    solid = Image.new("RGBA", img.size, (*color[:3], 0))
    solid.putalpha(img.getchannel("A"))
    return solid


def solve_mark(settings: Settings, style: str, target: tuple[int, int, int, int]
               ) -> tuple[tuple[int, int, int, int], list[str]] | None:
    """Where an annotation goes, given the box it wraps. Returns (box, warnings).

    THE MARK GOES ON THE TYPE, NOT ON THE SLOT RECTANGLE. A table cell is 216
    canvas units tall for 30-unit figures; an oval stretched onto the rectangle
    is an oval around empty space. Each mark declares an `area` slot — "what
    this wraps" — and the transform that lands `area` on the target is what puts
    the ink where it was drawn to fall. That is also what makes
    `underline-swipe` work with no special case: its swipe is drawn BELOW its
    area slot, so solving the area onto the word puts the swipe under the word.

    How a mark may be solved is declared, not assumed:

    * ``both``       x and y independently. Only safe for marks that ENCLOSE —
                     an oval is meant to take its target's proportions.
    * ``x-uniform``  fit the width, same scale for y. A line of its own natural
                     thickness stretched independently in y becomes a fat wave.

    and those carry an anchor: ``bottom`` for underlines, whose ink sits below
    the area slot, ``middle`` for strikes.
    """
    from pipeline.plates import load_plates

    key = SCRIBBLE_MARKS.get(style, ("", ""))[0]
    if not key:
        return None
    reg = load_plates(settings.assets_dir)
    plate = reg.get(key)
    if plate is None:
        return None
    area = plate.slot("area")
    if area is None:
        return None

    tx, ty, tw, th = target
    sx = tw / max(area.w, 1)
    sy = th / max(area.h, 1)
    if (plate.solve or "both") != "both":
        sy = sx                      # x-uniform: one scale, both axes

    warnings: list[str] = []
    if plate.ink_weight:
        solved = plate.ink_weight * sx
        lo, hi = INK_WEIGHT_BAND
        if not (lo <= solved <= hi):
            warnings.append(
                f"{key} solves to a {solved:.1f}-unit stroke against a legible "
                f"band of {lo}–{hi} — use the "
                f"{'tight' if solved > hi else 'wide'} mark instead")

    # Place the whole plate so its area slot lands on the target.
    w = int(round(plate.canvas[0] * sx))
    h = int(round(plate.canvas[1] * sy))
    x = int(round(tx - area.x * sx))
    y = int(round(ty - area.y * sy))
    if plate.anchor == "bottom":
        y = int(round(ty + th - (area.y + area.h) * sy))
    elif plate.anchor == "middle":
        y = int(round(ty + th / 2 - (area.y + area.h / 2) * sy))

    # A MARK DRAWS OUTSIDE WHAT IT WRAPS. A target so wide that the solved
    # canvas leaves the frame cannot be circled at all — the fix is to circle
    # the figure rather than the sentence, and saying so is more use than
    # silently drawing two arcs off the edge.
    return (x, y, w, h), warnings


def fitted_mark(settings: Settings, w: int, h: int, *, style: str,
                color=None) -> Image.Image | None:
    """An annotation plate scaled into a w x h box, tinted, or None."""
    key = SCRIBBLE_MARKS.get(style, ("", ""))[0]
    if not key:
        return None
    mark = mark_image(settings, key)
    if mark is None:
        return None
    scale = min(w / mark.width, h / mark.height)
    mw, mh = max(int(mark.width * scale), 1), max(int(mark.height * scale), 1)
    mark = mark.resize((mw, mh), Image.LANCZOS)
    mark = thicken_mark(
        mark, int(round((MARK_MIN_NIB_PX - MARK_NIB_PX * scale) / 2)))
    if color is not None:
        mark = tint_mark(mark, color)
    plate = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    plate.alpha_composite(mark, ((w - mw) // 2, (h - mh) // 2))
    return plate


def mark_frames(
    settings: Settings | None,
    w: int,
    h: int,
    *,
    style: str,
    color=None,
    fps: int = 30,
    draw_seconds: float = 0.4,
    stroke: int | None = None,
    seed: str = "mark",
) -> list[Image.Image]:
    """`style` drawing itself on — the kit's mark when one ships, else drawn.

    An annotation is drawn in ATTENTION, and that is the point: it SPENDS the
    frame's one attention, so a plate that already carries an attention mark
    cannot also be annotated.
    """
    if color is None:
        color = role(settings, "attention") if settings else (224, 160, 22)
    art = fitted_mark(settings, w, h, style=style, color=color) if settings else None
    n = max(int(draw_seconds * fps), 1)
    if art is not None:
        # Wipe the artwork on left to right, so it reads as being drawn.
        out = []
        for i in range(n):
            frac = _ease_out((i + 1) / n)
            frame = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            cut = max(int(w * frac), 1)
            frame.paste(art.crop((0, 0, cut, h)), (0, 0))
            out.append(frame)
        return out
    return _drawn_mark_frames(
        w, h, style=SCRIBBLE_MARKS.get(style, ("", "circle"))[1], color=color,
        fps=fps, draw_seconds=draw_seconds, stroke=stroke, seed=seed)


def _drawn_mark_frames(w: int, h: int, *, style: str, color, fps: int,
                       draw_seconds: float, stroke: int | None,
                       seed: str) -> list[Image.Image]:
    """The procedural fallback, for when the plate cannot be loaded.

    Deliberately crude. It is not trying to be the artwork — it is here so that
    a missing mark is a rougher mark rather than a missing beat, and so nothing
    in the annotation path can raise during a render.
    """
    rng = random.Random(seed)
    width = stroke or max(int(min(w, h) * 0.055), 3)
    cx, cy = w / 2, h / 2
    rx, ry = w * 0.46, h * 0.42

    def ellipse_pts(n: int = 44) -> list[tuple[float, float]]:
        return [(cx + rx * math.cos(2 * math.pi * i / n + 0.4),
                 cy + ry * math.sin(2 * math.pi * i / n + 0.4))
                for i in range(n + 3)]

    paths: list[list[tuple[float, float]]] = {
        "circle": [ellipse_pts()],
        "box": [[(w * .06, h * .1), (w * .94, h * .08), (w * .95, h * .9),
                 (w * .05, h * .92), (w * .06, h * .1)]],
        "underline": [[(w * .04, h * .74), (w * .96, h * .68)],
                      [(w * .08, h * .88), (w * .9, h * .84)]],
        "cross-out": [[(w * .06, h * .18), (w * .94, h * .84)],
                      [(w * .06, h * .84), (w * .94, h * .18)]],
        "bracket": [[(w * .72, h * .04), (w * .22, h * .1), (w * .2, h * .9),
                     (w * .7, h * .96)]],
        "arrow": [[(w * .05, h * .12), (w * .55, h * .2), (w * .9, h * .8)],
                  [(w * .78, h * .74), (w * .9, h * .8), (w * .76, h * .9)]],
        "caret": [[(w * .3, h * .9), (w * .5, h * .5), (w * .7, h * .9)]],
        "check": [[(w * .1, h * .55), (w * .3, h * .8), (w * .6, h * .2)]],
    }.get(style, [ellipse_pts()])

    total = sum(max(len(p) - 1, 1) for p in paths)
    n = max(int(draw_seconds * fps), 1)
    frames: list[Image.Image] = []
    for i in range(n):
        drawn = _ease_out((i + 1) / n) * total
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        budget = drawn
        for path in paths:
            take = int(min(max(budget, 0), len(path) - 1)) + 1
            if take >= 2:
                marker_stroke(d, path[:take], rng, width=width,
                              color=(*color[:3], 255), jitter=1.5)
            budget -= len(path) - 1
        frames.append(img)
    return frames


def _ease_out(t: float) -> float:
    """Fast, then settling. The house easing for anything that lands."""
    return 1.0 - (1.0 - min(max(t, 0.0), 1.0)) ** 3


# The figure inside a display string. Shared by the roller and the locator so
# what gets found is exactly what gets rolled.
_ROLL_RE = re.compile(r"-?\d[\d,]*\.?\d*")


def roll_steps(value: str, n: int) -> list[str] | None:
    """`value` rolling from zero to itself over `n+1` display strings.

    None when there is no number in it, so a caller can hold the string
    instead of animating punctuation. The prefix, suffix and sign do not
    count — "$4.1B" rolls "0.0" to "4.1" and keeps the dollar and the B,
    because a currency symbol flickering through the alphabet is noise.

    Split out of `count_up_frames` so the roll is not tied to one raster.
    Every figure in a short arrives somewhere — a slot on a drawing, a
    blank layout's `figure` box, a headline card, the ledger line — and only
    the numbers-sheet cue was ever animated, so every other one appeared
    fully formed and the motion layer stopped at the sheet.
    """
    m = _ROLL_RE.search(value or "")
    if m is None:
        return None
    raw = m.group(0).replace(",", "")
    try:
        target = float(raw)
    except ValueError:
        return None
    head, tail = value[:m.start()], value[m.end():]
    decimals = len(raw.split(".")[1]) if "." in raw else 0
    grouped = "," in m.group(0)
    out: list[str] = []
    for k in range(max(n, 1) + 1):
        cur = target * _ease_out(k / max(n, 1))
        body = f"{cur:,.{decimals}f}" if grouped else f"{cur:.{decimals}f}"
        out.append(f"{head}{body}{tail}")
    return out


def roll_over_lines(
    base: Image.Image,
    placed: list[tuple[str, float, float]],
    font,
    *,
    fill,
    bg,
    line_h: int,
    fps: int = 30,
    seconds: float = 0.7,
) -> list[Image.Image] | None:
    """`base` re-drawn with the first figure in `placed` counting up to itself.

    `placed` is `[(line_text, x, y)]` — the wrapped lines exactly as the card
    drew them. None when no line carries a figure, so this is safe to call on
    any card.

    The figure is repainted INSIDE the box it already occupies rather than the
    line being re-rendered around it. Both display faces have PROPORTIONAL
    figures — a `4` is 33% wider than a `1` in Space Grotesk Bold, and 60% in
    Shantell — so re-wrapping "fell 0%" into "fell 41%" slides every word
    after the number back and forth under the digits. That reads as a wobble,
    not as a counter, and it is worse than the static card it replaced.

    The last frame is `base` itself, so a card that holds after the roll holds
    exactly the pixels the rest of the render was measured against.
    """
    for line, lx, ly in placed:
        m = _ROLL_RE.search(line)
        if m is None:
            continue
        probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
        body = line[m.start():m.end()]
        steps = roll_steps(body, max(int(seconds * fps), 2))
        if steps is None:
            continue
        bx = lx + probe.textlength(line[:m.start()], font=font)
        bw = probe.textlength(body, font=font)
        frames: list[Image.Image] = []
        for s in steps[:-1]:
            f = base.copy()
            d = ImageDraw.Draw(f)
            # The card's plate is a flat fill, so painting the box back to it
            # restores exactly what was under the digits.
            d.rectangle([bx, ly, bx + bw + 1, ly + line_h], fill=bg)
            # RIGHT-aligned in the box the final value will fill. A narrower
            # step has to leave its slack somewhere, and the right edge puts it
            # at the word boundary before the number instead of between the
            # number and its unit — left-aligned, "12%" mid-roll rendered as
            # "12 %", which reads as a typo rather than as a count.
            d.text((bx + bw - probe.textlength(s, font=font), ly), s,
                   font=font, fill=fill)
            frames.append(f)
        frames.append(base)
        return frames
    return None


def count_up_frames(
    settings: Settings,
    value: str,
    *,
    width: int,
    height: int,
    fps: int = 30,
    seconds: float = 0.8,
    font_name: str = COURIER_BOLD,
    fill=None,
    align: str = "center",
) -> list[Image.Image]:
    """A figure rolling up to its spoken value.

    The digits count; the prefix, suffix and sign do not — "$4.1B" rolls
    "0.0" to "4.1" and keeps the dollar and the B, because a currency symbol
    flickering through the alphabet is noise, not motion. A value with no
    digits at all is simply held, so this is safe to call on anything.
    """
    fill = fill if fill is not None else role(settings, "structure")
    m = re.search(r"-?\d[\d,]*\.?\d*", value)
    frames: list[Image.Image] = []
    n = max(int(seconds * fps), 2)

    def draw(text: str) -> Image.Image:
        img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        size = int(height * 0.82)
        font = load_font(settings, font_name, size)
        while size > 10 and d.textlength(text, font=font) > width:
            size = int(size * 0.92)
            font = load_font(settings, font_name, size)
        w = d.textlength(text, font=font)
        x = 0 if align == "left" else (width - w if align == "right" else (width - w) / 2)
        ascent, descent = font.getmetrics()
        d.text((x, (height - ascent - descent) / 2), text, font=font, fill=(*fill, 255))
        return img

    if m is None:
        return [draw(value)] * 2

    head, tail = value[:m.start()], value[m.end():]
    raw = m.group(0).replace(",", "")
    try:
        target = float(raw)
    except ValueError:
        return [draw(value)] * 2
    decimals = len(raw.split(".")[1]) if "." in raw else 0
    grouped = "," in m.group(0)

    for k in range(n + 1):
        cur = target * _ease_out(k / n)
        body = f"{cur:,.{decimals}f}" if grouped else f"{cur:.{decimals}f}"
        frames.append(draw(f"{head}{body}{tail}"))
    return frames