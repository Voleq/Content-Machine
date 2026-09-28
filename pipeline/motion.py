"""Design's motion catalogue, in Python: a line-for-line port of
``kit/engine/motion.js``.

THE MOVES ARE DESIGN'S, NOT OURS. The kit publishes thirteen moves as data
rather than as baked frames: each names what it applies to, its length in
frames at 12 fps, its easing, and a pure function a renderer calls per frame.
The plates stay stills and a renderer plays a move OVER a plate's published
slots, so no plate is re-drawn per move and a move can never disagree with the
plate it animates.

Node is not in the render path (``ingest_kit.py`` and ``test_kit_ingest.py``
refuse it), so the renderer needs the arithmetic here. It is ported rather than
re-derived for the same reason ``pipeline/series.py`` is: a count-up that eases
differently from design's review page, or a circle that closes a frame late, is
a disagreement nobody would find by looking. ``tests/test_motion_port.py`` runs
the kit's own file in node and compares every function, number for number.

Rules every move keeps (design's DESIGN.md §5): no partial opacity, so nothing
fades; things draw on, grow, slide, or appear on a frame.

What is NOT here: where a move lands. Design's ``anchorFor``, ``tagPlace``
and ``roomTargets`` already ran when the kit was emitted and their answers are
on every plate (``Plate.motion``) and room (``Registry.motion_rooms``), from
``kit/emit/motion.json``, with the timings design fixes outside a plate
(``Registry.motion_timings``). Re-running them here would be a second opinion
about a question the kit has answered.
"""

from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal
from typing import NamedTuple

FPS = 12


def _clamp(t: float) -> float:
    return max(0.0, min(1.0, float(t)))


def linear(t: float) -> float:
    return _clamp(t)


def out(t: float) -> float:
    return 1 - (1 - _clamp(t)) ** 3


def in_out(t: float) -> float:
    t = _clamp(t)
    return 4 * t * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


# A settle: overshoots and comes back, for things that land. motion.js says
# "~6%"; measured, the continuous peak is 3.9% at t = 0.663.
_LAND_C = 1.70158 * 0.6


def land(t: float) -> float:
    t = _clamp(t)
    return 1 + (_LAND_C + 1) * (t - 1) ** 3 + _LAND_C * (t - 1) ** 2


EASES = {"linear": linear, "out": out, "inOut": in_out, "land": land}


def ease(name: str | None, t: float) -> float:
    """An ease by the name the catalogue gives it; no name is linear."""
    return EASES.get(name or "linear", linear)(t)


def t_of_frame(f: int, frames: int) -> float:
    """Where frame `f` of a once-played move is, from 0 to 1.

    Design's review page steps a move of N frames through f / (N - 1): frame
    0 is t = 0 and the last frame is t = 1. motion.js does not state it; the
    timing contract measured it off the review page, and every hit time the
    sound is cut to assumes it.
    """
    return 1.0 if frames <= 1 else _clamp(f / (frames - 1))


# ---------------------------------------------------------------------------
# count-up
# ---------------------------------------------------------------------------

import re as _re

# The JS pattern, verbatim: a lazy prefix, an optional sign, the first run of
# digits (with thousands commas), its decimals, and the rest as the suffix.
_COUNT = _re.compile(r"^(.*?)([−+-]?)(\d[\d,]*)(\.\d+)?(.*)$")
_THOUSANDS = _re.compile(r"\B(?=(\d{3})+(?!\d))")


def _to_fixed(v: float, digits: int) -> str:
    """JavaScript's ``Number.prototype.toFixed`` for v >= 0.

    Not Python's ``format``: that rounds a tie to even, toFixed takes the
    larger of the two nearest, and a count-up whose last frame reads 2 where
    design's reads 3 is exactly the disagreement this file exists to prevent.
    Both round the EXACT binary value, which ``Decimal(v)`` holds.
    """
    q = Decimal(1).scaleb(-digits) if digits else Decimal(1)
    return str(Decimal(v).quantize(q, rounding=ROUND_HALF_UP))


def count_text(text: str, t: float) -> str:
    """The figure in `text` counted from zero, keeping its prefix, suffix,
    sign and decimals ("$3.1bn", "−40%", "+2.6pt", "12,400").

    Zero padding is dropped ("03" ends on "3"), and the sign is dropped while
    the figure reads zero, as design's own does. Text with no digits comes
    back unchanged.
    """
    s = str(text)
    m = _COUNT.match(s)
    if not m:
        return s
    whole = float((m.group(3) + (m.group(4) or "")).replace(",", ""))
    d = len(m.group(4)) - 1 if m.group(4) else 0
    v = whole * out(t)
    body = _to_fixed(v, d)
    if "," in m.group(3):
        head, _, tail = body.partition(".")
        head = _THOUSANDS.sub(",", head)
        body = head + ("." + tail if tail else "")
    return m.group(1) + ("" if v == 0 else m.group(2)) + body + m.group(5)


# ---------------------------------------------------------------------------
# Boxes
# ---------------------------------------------------------------------------

class Box(NamedTuple):
    x: float
    y: float
    w: float
    h: float


def reveal(box: Box, t: float, side: str) -> Box:
    """The part of `box` shown at `t`, growing from one edge.

    `bottom` grows upwards (a bar), `top` downwards, `left-linear` from the
    left at a constant speed (a line being drawn), anything else from the left
    on the `out` ease (an underline).
    """
    k = out(t)
    x, y, w, h = box
    if side == "bottom":
        return Box(x, y + h * (1 - k), w, h * k)
    if side == "top":
        return Box(x, y, w, h * k)
    return Box(x, y, w * (linear(t) if side == "left-linear" else k), h)


def outset(box: Box, p: float) -> Box:
    """`box` grown by `p` on every side: a line-draw's clip is the plot grown
    by its bleed, so the line's half-weight and end points are not cut."""
    x, y, w, h = box
    return Box(x - p, y - p, w + p * 2, h + p * 2)


def stagger(f: float, i: int, frames: int) -> float:
    """bars-grow: where column `i` is at frame `f`, each column starting one
    frame after the one before. A move over n columns lasts frames + n - 1."""
    return _clamp((f - i) / max(1, frames - 1))


def _lcg(seed: int):
    """motion.js's seeded generator: s = (s * 9301 + 49297) % 233280."""
    s = seed

    def r() -> float:
        nonlocal s
        s = (s * 9301 + 49297) % 233280
        return s / 233280
    return r


class PenPath(NamedTuple):
    points: list[tuple[float, float]]
    length: float


def pen_circle(box: Box, seed: int = 7) -> PenPath:
    """A hand-drawn ellipse round `box`: 40 steps a turn, 44 drawn.

    The four extra steps are the pen running on past where it started, the
    10% overlap that makes it read as drawn by hand rather than stamped. The
    wobble is seeded, so the same box always gets the same ring.
    """
    x, y, w, h = box
    cx, cy = x + w / 2, y + h / 2
    rx, ry = w / 2 + 26, h / 2 + 18
    n = 40
    r = _lcg(seed or 7)
    pts: list[tuple[float, float]] = []
    for i in range(n + 5):
        a = -math.pi * 0.62 + (i / n) * math.pi * 2
        j = 1 + (r() - 0.5) * 0.06
        pts.append((cx + math.cos(a) * rx * j, cy + math.sin(a) * ry * j))
    length = sum(math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1])
                 for i in range(1, len(pts)))
    return PenPath(pts, length)


def pen_drawn(length: float, t: float) -> float:
    """How much of a pen path of `length` is on the page at `t`.

    motion.js expresses it as a dash offset, ``len * (1 - inOut(t))`` of the
    path still hidden; this is the other half of the same number.
    """
    return length * in_out(t)


def partial_path(points: list[tuple[float, float]],
                 drawn: float) -> list[tuple[float, float]]:
    """The first `drawn` units of a polyline, ending mid-segment if it must.

    What a stroke-dashoffset shows, for a renderer with no dashes.
    """
    if drawn <= 0 or len(points) < 2:
        return []
    got = [points[0]]
    left = drawn
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        seg = math.hypot(x1 - x0, y1 - y0)
        if seg >= left:
            k = left / seg if seg else 0.0
            got.append((x0 + (x1 - x0) * k, y0 + (y1 - y0) * k))
            return got
        got.append((x1, y1))
        left -= seg
    return got


def zoom_box(canvas: tuple[float, float], box: Box, t: float,
             pad: float | None = 60) -> tuple[float, float, float, float]:
    """The viewBox at `t`, from the whole canvas to `box` padded, eased.

    Kept at the canvas's aspect ratio, so the push never stretches the plate.
    Design's version does not keep it inside the canvas; neither does this —
    whether to clamp is the renderer's call, made where the frame is known.
    """
    k = in_out(t)
    p = 60 if pad is None else pad
    ar = canvas[0] / canvas[1]
    w = box.w + p * 2
    h = w / ar
    if h < box.h + p * 2:
        h = box.h + p * 2
        w = h * ar
    tx = box.x + box.w / 2 - w / 2
    ty = box.y + box.h / 2 - h / 2
    return (tx * k, ty * k,
            canvas[0] + (w - canvas[0]) * k, canvas[1] + (h - canvas[1]) * k)


# ---------------------------------------------------------------------------
# Loops and the room
# ---------------------------------------------------------------------------

# flicker: the frames the screen and lamp drop to their shade tone
SCREEN_PULSE = (0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0)
LAMP_FLICKER = (0, 0, 0, 0, 0, 0, 0, 1, 0, 1, 0, 0)


class Flake(NamedTuple):
    x: float
    y: float
    r: float


def snow(box: Box, frame: float, n: int = 26) -> list[Flake]:
    """Flakes falling in a window pane, seeded, looping over 12 frames.

    Each flake falls a whole number of pane-heights a loop (one or two), so
    frame 12 puts every flake where frame 0 had it and the loop has no seam.
    """
    r = _lcg(11)
    got: list[Flake] = []
    for i in range(n or 26):
        x0, y0 = r(), r()
        sz = 0.8 + r() * 1.4
        sp = 1 if r() < 0.7 else 2
        y = math.fmod(y0 + (frame / 12) * sp, 1)
        x = math.fmod(x0 + math.sin((frame / 12) * math.pi * 2 + i) * 0.02 + 1, 1)
        got.append(Flake(box.x + x * box.w, box.y + y * box.h, sz))
    return got


class Drop(NamedTuple):
    x: float
    y: float
    w: float
    h: float


def rain(box: Box, frame: float) -> list[Drop]:
    """Rain: snow three times as fast, forty short strokes (3 and 6
    pane-heights a loop, so seamless like the snow)."""
    return [Drop(f.x, f.y, 0.6, 5) for f in snow(box, frame * 3, 40)]


TWINKLE = ("attention", "subject2", "subject")
# One ink step every four frames: three inks by four frames is the 12-frame
# loop, so no state holds longer at the seam.
TWINKLE_STEP = 4


def twinkle_ink(phase: int, frame: int) -> str:
    """A bulb's ink at `frame`, from its `phase`, the ink it shows at frame 0
    (the kit publishes it per bulb, `rooms[id].bulbs[n].phase`)."""
    return TWINKLE[(phase + frame // TWINKLE_STEP) % 3]


def pin_drop(t: float) -> tuple[float, float]:
    """A card falling onto the wall and swinging once to rest: (dy, rot)."""
    k = out(t)
    return -60 * (1 - k), -4 + 10 * math.sin(k * math.pi * 2.2) * (1 - k)


def slide_x(width: float, t: float) -> float:
    """An overlay's x offset at `t`: from off the left edge to its place,
    landing with a small overshoot. Out is the same frames reversed."""
    return -(width + 40) * (1 - land(t))


def tick(h: float, t: float) -> tuple[float, float]:
    """tick-over: the old number up and out, the new one up and in.
    Returns (old_y, new_y), both offsets inside a slot of height `h`."""
    k = in_out(t)
    return -h * k, h * (1 - k)
