"""Hand-drawn line primitives and type fitting, lifted out of the old kit.

These five things were the genuinely reusable part of `rasters.py`: they draw
a line the way a hand draws one, and they fit type into a box. Everything
around them — the tag-driven composition that chose which asset went where —
is gone. These came across because the new compositor needs exactly the same
marks, and re-deriving a marker stroke would have produced a different one.

`marker_stroke`, `drawn_rect` and `ease_out` are the originals. The type
fitting is the same wrap-then-shrink loop, generalised to work in fractions of
frame height instead of hardcoded point sizes.
"""

from __future__ import annotations

import math
import random
from pathlib import Path
from typing import Sequence

from PIL import ImageDraw, ImageFont

# The kit's palette, from assets/manifest.json. World colour appears only on
# physical objects — never on a chart, a number, a label or a plate interior —
# which is what keeps green meaning an up move and nothing else.
INK = (35, 35, 38, 255)
INK_BALLPOINT = (43, 50, 66, 255)
INK_GREASE = (42, 39, 36, 255)
PAPER = (242, 242, 239, 255)
CARD = (250, 249, 246, 255)
CARD_LINE = (226, 223, 213, 255)
MUTED = (143, 140, 131, 255)
RED = (255, 82, 71, 255)
GREEN = (47, 213, 118, 255)

INK_FOR_REGISTER = {
    "marker": INK,
    "ballpoint": INK_BALLPOINT,
    "grease-pencil": INK_GREASE,
    "cut-paper": INK,
}

PALETTE = {
    "ink": INK, "paper": PAPER, "card": CARD, "cardLine": CARD_LINE,
    "muted": MUTED, "red": RED, "green": GREEN,
}


def ease_out(t: float) -> float:
    """Fast, then settling. The house easing for anything that lands."""
    return 1.0 - (1.0 - min(max(t, 0.0), 1.0)) ** 3


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


def scribble_ring(d, box, rng, *, color, width=6, passes=2):
    """A ring scribbled round something, the way you circle a number.

    It goes round the THING — the extreme candle, the row — never round a
    label describing the thing. Two loose passes, deliberately not closing
    where they started.
    """
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    # ENCLOSE the thing, do not inscribe a shape inside it. A ring drawn to
    # the exact bounds of a wide, short text slot is a flat ellipse that
    # crosses the words instead of going round them — which is what a ring on
    # a circled clause looked like the first time. Pad outward, and never let
    # the minor axis collapse below a readable fraction of the major one.
    rx, ry = (x1 - x0) / 2, (y1 - y0) / 2
    rx *= 1.06
    ry = max(ry * 1.35, rx * 0.22)
    for p in range(passes):
        pts = []
        start = rng.uniform(0, 0.6)
        for i in range(41):
            a = (start + i / 40 * 2.08) * math.pi
            wob = 1.0 + rng.uniform(-0.055, 0.055)
            pts.append((cx + math.cos(a) * rx * wob * (1 + p * 0.03),
                        cy + math.sin(a) * ry * wob * (1 + p * 0.03)))
        marker_stroke(d, pts, rng, width=width, color=color, jitter=1.4,
                      passes=1)


def arrow_down(d, box, rng, *, color, width=6):
    """A hand-drawn down arrow: the shaft, then two strokes for the head."""
    x0, y0, x1, y1 = box
    cx = (x0 + x1) / 2
    marker_stroke(d, [(cx, y0), (cx, y1)], rng, width=width, color=color,
                  jitter=1.8, passes=2)
    head = (x1 - x0) * 0.34
    marker_stroke(d, [(cx - head, y1 - head), (cx, y1)], rng, width=width,
                  color=color, jitter=1.5, passes=2)
    marker_stroke(d, [(cx + head, y1 - head), (cx, y1)], rng, width=width,
                  color=color, jitter=1.5, passes=2)


def cross(d, box, rng, *, color, width=6):
    """Two strokes through a box. Drawn, not typed."""
    x0, y0, x1, y1 = box
    marker_stroke(d, [(x0, y0), (x1, y1)], rng, width=width, color=color,
                  jitter=2.0, passes=2)
    marker_stroke(d, [(x1, y0), (x0, y1)], rng, width=width, color=color,
                  jitter=2.0, passes=2)


def underline(d, box, rng, *, color, width=6):
    """One stroke under a line of type, run slightly past both ends."""
    x0, _y0, x1, y1 = box
    over = (x1 - x0) * 0.03
    marker_stroke(d, [(x0 - over, y1), (x1 + over, y1)], rng,
                  width=width, color=color, jitter=1.8, passes=2)


# ---------------------------------------------------------------------------
# Type
# ---------------------------------------------------------------------------

# The two faces. Named here rather than in the renderer so the budget
# measurement and the fitter cannot be measuring different type.
BODY_FONT = "Inter-Regular.ttf"
DISPLAY_FONT = "Inter-Bold.ttf"

_FONT_DIR = Path("assets/fonts")
_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def load_font(name: str, size: int) -> ImageFont.FreeTypeFont:
    key = (name, int(size))
    hit = _font_cache.get(key)
    if hit is not None:
        return hit
    path = _FONT_DIR / name
    try:
        f = ImageFont.truetype(str(path), int(size))
    except OSError:
        candidates = sorted(_FONT_DIR.glob("*.ttf")) + sorted(_FONT_DIR.glob("*.otf"))
        if not candidates:
            f = ImageFont.load_default()
        else:
            f = ImageFont.truetype(str(candidates[0]), int(size))
    _font_cache[key] = f
    return f


def wrap_to(draw, text: str, font, max_w: int) -> list[str]:
    """Greedy wrap. A word longer than the box gets its own line rather than
    being dropped — an overflowing line is visible, a missing one is not."""
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
    return [ln for ln in lines if ln]


def fit_lines(draw, text: str, font_name: str, box_w: int, box_h: int,
              *, size_px: int, max_lines: int, min_px: int | None = None
              ) -> tuple[list[str], ImageFont.FreeTypeFont, int]:
    """Wrap `text` into at most `max_lines`, shrinking until it fits.

    Returns the lines and the font that holds them. The caller passes the size
    it WANTS — a fraction of frame height turned into pixels — and gets back
    the largest size at or below it that actually fits the box. Type that
    silently overflows its box is how a disclaimer ends up printed twice.
    """
    # The floor is how small type may go before it is better to overflow. It
    # was 55% of the asked size, which is not enough range for a wide clause
    # in a one-line slot: the loop hit the floor, gave up, and drew two lines
    # in a box that holds one. 38% still clears the 3.5%-of-frame-height rule
    # for every size any template asks for.
    floor = min_px if min_px is not None else max(12, int(size_px * 0.38))
    # The floor limits how far type may SHRINK. It must never raise the ask:
    # a 26px label in a small slot was being drawn at the 67px readability
    # floor because the loop below could not run at all, which made the type
    # two and a half times its box and truncated every card in the chain.
    # Type that is too small for the frame is a geometry problem to report,
    # not something to fix by drawing it bigger than the box that holds it.
    floor = min(floor, int(size_px))
    size = int(size_px)
    while size >= floor:
        font = load_font(font_name, size)
        lines = wrap_to(draw, text, font, box_w)
        # Width as well as line count. `wrap_to` puts a word too long for the
        # box on a line of its own rather than dropping it, so a narrow slot
        # accepted lines far wider than itself: three chain boxes rendered
        # their labels straight through each other and off the frame. A line
        # that does not fit the box is not a fit.
        widest = max((draw.textlength(ln, font=font) for ln in lines),
                     default=0)
        if len(lines) <= max_lines and widest <= box_w:
            asc, desc = font.getmetrics()
            line_h = (asc + desc) * 1.18
            if line_h * len(lines) <= box_h:
                return lines, font, 0
        size -= max(1, int(size * 0.06))

    # Below the floor, words start being lost. Smaller type is always better
    # than a clause that stops mid-sentence, so the only truncation that ever
    # happens is at the hard readability floor — and it is REPORTED, in
    # characters, rather than being dropped on the way to the screen.
    font = load_font(font_name, floor)
    full = wrap_to(draw, text, font, box_w)
    lines = full[:max_lines]
    lost = sum(len(ln) for ln in full[max_lines:])
    return lines, font, lost


def draw_block(img, text: str, box: tuple[int, int, int, int], *,
               font_name: str, size_px: int, color, max_lines: int = 3,
               halign: str = "center", valign: str = "top",
               reveal: float = 1.0, min_px: int | None = None
               ) -> tuple[int, int, int, int, int]:
    """Draw wrapped type into `box`.

    Returns `(x, y, w, h, characters_lost)`. The last element is how much text
    did not fit even at the readability floor — always zero in a healthy
    render, and never silently non-zero.

    `reveal` between 0 and 1 draws only that fraction of the characters, which
    is how type "draws on": the letters appear in reading order rather than
    the whole block fading up.
    """
    x, y, w, h = box
    d = ImageDraw.Draw(img)
    lines, font, lost = fit_lines(d, text, font_name, w, h, size_px=size_px,
                                  max_lines=max_lines, min_px=min_px)
    if not lines:
        return (x, y, 0, 0, len(text))

    asc, desc = font.getmetrics()
    line_h = int((asc + desc) * 1.18)
    total_h = line_h * len(lines)
    if valign == "center":
        oy = y + (h - total_h) // 2
    elif valign == "bottom":
        oy = y + h - total_h
    else:
        oy = y

    shown = max(0, int(round(sum(len(ln) for ln in lines) * min(max(reveal, 0.0), 1.0))))
    used_w = 0
    budget = shown
    for i, ln in enumerate(lines):
        if reveal < 1.0:
            if budget <= 0:
                break
            ln = ln[:budget]
            budget -= len(ln)
        tw = int(d.textlength(ln, font=font))
        used_w = max(used_w, tw)
        if halign == "center":
            ox = x + (w - tw) // 2
        elif halign == "right":
            ox = x + w - tw
        else:
            ox = x
        d.text((ox, oy + i * line_h), ln, font=font, fill=color)
    return (x, oy, used_w or w, total_h, lost)


def measure_block(text: str, box: tuple[int, int, int, int], *,
                  font_name: str, size_px: int,
                  max_lines: int = 3) -> tuple[int, int]:
    """`(w, h)` the type will occupy. Same fitter, so the same answer."""
    """`(w, h)` the type will occupy, without drawing it."""
    from PIL import Image
    d = ImageDraw.Draw(Image.new("L", (8, 8)))
    lines, font, _lost = fit_lines(d, text, font_name, box[2], box[3],
                                   size_px=size_px, max_lines=max_lines)
    if not lines:
        return (0, 0)
    asc, desc = font.getmetrics()
    return (int(max(d.textlength(ln, font=font) for ln in lines)),
            int((asc + desc) * 1.18 * len(lines)))


def rng_for(*parts: object) -> random.Random:
    """A deterministic RNG for a mark, so a re-render draws the same line."""
    return random.Random("|".join(str(p) for p in parts))
