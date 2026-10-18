"""THE EPISODE, WRITTEN IN THE ROOM (item 36): the board, the monitor and
the writing on his things.

The long's rooms are one 3D room (`room3d/build.py`), rendered with the board
wiped and the monitor showing a flat backlight, and every room that has
either in shot says where (`Plate.writable`): four corners in canvas units,
the colour the surface is painted, and a mask of what the camera sees of it.
This writes each video's own board and chart there, in the room's
perspective and in its light:

- THE BOARD AS INK, multiplied into the painted surface in linear light, so
  the writing darkens with the room when the screen dips and goes behind
  whatever stands between the camera and the board;
- THE MONITOR AS A PICTURE SHONE AT THE RENDER'S OWN BRIGHTNESS, over the
  whole glass, so the made-up app the room was rendered with goes under it
  and a sticky note on the glass stays on top of it.

THE MONITOR FOLLOWS THE CHAPTER (items 49, 54): through each chapter it shows
a plate that chapter puts on screen, drawn with the chapter's own figures
(`pipeline/room_screen.py` decides which), or the price's run. Since 10 Oct
2026 it is a sheet of the plates' own paper filling the glass, with no app
round it (no title bar, prompt or sidebar), so the picture on his screen and
the plate the camera cuts to are one page; the first time a chapter's
picture is seen it draws itself in (`reveal_frames`).

THE WRITING ON HIS THINGS (18 Oct 2026): the binder spines, the box's label,
the stacks and the report on his desk, the notes on his screen, the cards on
his board and the stitched sign are rendered blank and lettered here, each
in its own perspective, as ink in the room's light like the board
(`label_ink`). What they say is the video's (`pipeline/room_writing.py`).

Every frame and every front layer of a room is written the same way, so the
desk he stands behind carries the same monitor as the room behind him.

NOTHING HERE COMPUTES A FIGURE. The board names the episode, the ticker, the
question the video asks and its chapters; the line on the board and the
monitor is the closes the price feed returned, drawn with no value on it, and
not drawn at all when the feed failed and the series was made up.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import logging
import math
import random
import textwrap
from dataclasses import dataclass, replace
from pathlib import Path

log = logging.getLogger(__name__)

# Bumped when the drawing changes, so a workspace's written rooms are redone.
VERSION = "6"

# What the board asks when the writer's script sets no [BOARD].
BOARD_DEFAULT_QUESTION = "what are we paying for?"
# A [BOARD] is the line a man writes on a whiteboard, not a paragraph.
BOARD_MAX_CHARS = 48
# The chapters the board lists. Every one, since each is ticked off on it
# as the video goes (`tick_frames`): ten is the longest the writer's menu
# runs, and still a line a man could read from the board's own angle.
BOARD_MAX_CHAPTERS = 10

# Marker colours, as they read on the board's paper.
_INK = {"black": (34, 38, 48), "blue": (30, 58, 132), "red": (176, 34, 40)}
# THE MONITOR ON PAPER: the kit's paper and its inks (subject, structure,
# quiet), the sheet every plate is drawn on. A chapter's picture brings its
# own paper to the glass; these draw the price's run.
_PAPER = (244, 242, 234)
_PAPER_INK = (40, 60, 154)
_PAPER_TEXT = (11, 14, 22)
_PAPER_QUIET = (85, 90, 102)

# THE WHOLE GLASS. The room renders a made-up charting app on the monitor (a
# title bar, tabs, a sidebar of coloured bars) round the flat backlit chart
# area rooms.json names, and it read as a fake app. The picture now covers
# the glass: its corners are the chart area's carried out through the same
# perspective, from where that area sits in the screen's texture
# (room3d/textures.py SCREEN_TEX and SCREEN_CHART). The screen's mask is the
# whole glass already, less the notes stuck on it.
_SCREEN_TEX = (1920, 1080)
_SCREEN_CHART = (60, 116, 1392, 1044)
# The glass's width over its height in the room: build.py's MONITOR_GLASS,
# 16:9 since 18 Oct 2026 (it was a 2.16 sheet floating in front of Kenney's
# bigger dark screen, and a plate on it read as paper taped to a monitor).
# Pictures are drawn at this shape before they go on the glass.
GLASS_ASPECT = 16 / 9
# Where the chapter's picture goes on the glass, as fractions of it: all of
# it, edge to edge, as a screen shows a page. The sticky notes are on the
# frame and only lap over the picture's corners.
_PICTURE_BOX = (0.0, 0.0, 1.0, 1.0)
# How bright the glass shines its paper, as a share of the picture: a screen
# turned down for a night room, not a light box.
SCREEN_LEVEL = 0.85
# A screen seen across a room is a little brighter in its middle than at its
# edges: how much darker the corners are.
SCREEN_FALLOFF = 0.12
# THE GLOW: a lit screen in a dark room spills past its edge in a camera.
# What spills, as a share of what the glass shines, and how far, as a share
# of the glass's width. Only round the glass, never over it or the notes on
# it, which a haze over made look smeared.
GLOW = 0.18
GLOW_RADIUS = 0.035
# How many pictures the chapter's chart takes to draw itself in, at what rate:
# a second.
REVEAL_FRAMES = 12
REVEAL_FPS = 12


@dataclass(frozen=True)
class Dressing:
    """What one episode writes in the room. `episode` 0 is a short, which has
    no number in the channel's run: its board leads with the ticker."""
    episode: int
    ticker: str
    question: str = BOARD_DEFAULT_QUESTION
    chapters: tuple[str, ...] = ()
    # The price feed's closes, oldest first; empty when there is no real one.
    closes: tuple[float, ...] = ()
    span: str = "5Y"
    # WHAT THE MONITOR SHOWS THROUGH ONE CHAPTER (item 49): a picture of a
    # plate the chapter puts on screen, drawn by the renderer with the
    # chapter's own figures. Empty: the price's run.
    screen: str = ""
    # The picture's content hash: a new picture is a new written room.
    screen_stamp: str = ""
    # What the picture is, for the manifest; nothing on the glass says it.
    screen_label: str = ""
    # THE WRITING ON HIS THINGS, as (id, text) pairs (`room_writing.props`):
    # an id the room letters and this does not name goes up blank.
    props: tuple[tuple[str, str], ...] = ()
    # THE CHAPTER THE VIDEO IS IN, counted from one (0: none, a short or a
    # cover). The board circles its number and every one before it, and
    # ticks off the ones before it, so a wide shot in chapter four shows the
    # board as the last chapter break left it.
    chapter: int = 0

    @property
    def fingerprint(self) -> str:
        raw = json.dumps([VERSION, self.episode, self.ticker, self.question,
                          list(self.chapters), [round(c, 4) for c in self.closes],
                          self.span, self.screen_stamp, self.screen_label,
                          [list(p) for p in self.props], self.chapter])
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    @property
    def board_seed(self) -> str:
        """What the board's hand is seeded by: the episode, never the chapter
        or the monitor, so the box and the underline are the same strokes all
        video long and only the marks are added."""
        return replace(self, screen="", screen_stamp="", screen_label="",
                       chapter=0).fingerprint

    def in_chapter(self, n: int) -> Dressing:
        """This dressing with the board ticked off up to chapter `n`."""
        return replace(self, chapter=max(int(n), 0))

    def showing(self, picture: Path | None, label: str = "") -> "Dressing":
        """This dressing with `picture` on the monitor; the price's run if None."""
        if picture is None:
            return replace(self, screen="", screen_stamp="", screen_label="")
        h = hashlib.sha256(Path(picture).read_bytes()).hexdigest()[:16]
        return replace(self, screen=str(picture), screen_stamp=h,
                       screen_label=label)


EPISODES_FILE = "episodes.json"


def episode_number(settings, ticker: str, workdate: str, *,
                   assign: bool = False) -> int:
    """This long's number in the channel's run of longs, counted from one.

    A number a FINAL was drawn with is kept (`state/episodes.json`), so the
    board and the cover never disagree with the video that went out. A long
    with no number yet takes its place among the longs already uploaded when
    it is one of them, else the next free number; `assign` (a final render)
    records it.

    Computed from uploads alone, two longs rendered before either went up
    both read "the next one" and carried the same number on the board, and
    an out-of-order upload renumbered a video that had already been drawn.
    """
    import json

    from pipeline.youtube import VideoLog, record_format

    me_key = f"{ticker.upper()}/{workdate}"
    path = Path(settings.state_dir) / EPISODES_FILE
    try:
        book = json.loads(path.read_text(encoding="utf-8"))
        book = book if isinstance(book, dict) else {}
    except (OSError, ValueError):
        book = {}
    if me_key in book:
        return int(book[me_key])

    rows = [v for v in VideoLog(settings).all() if record_format(v) == "long"]
    rows.sort(key=lambda v: v.uploaded_at or v.publish_at or v.workdate or "")
    seen: list[tuple[str, str]] = []
    for v in rows:
        k = (v.ticker.upper(), v.workdate)
        if k not in seen:
            seen.append(k)
    me = (ticker.upper(), workdate)
    if me in seen:
        n = seen.index(me) + 1
    else:
        taken = [int(x) for x in book.values() if str(x).isdigit()]
        n = max([len(seen), *taken]) + 1
    if assign:
        book[me_key] = n
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(book, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(path)
    return n


def board_question(script) -> str:
    """The writer's [BOARD], or the default question."""
    from pipeline.models import TagType

    for e in getattr(script, "events", ()) or ():
        if e.type is TagType.BOARD and e.payload.strip():
            return e.payload.strip()
    return BOARD_DEFAULT_QUESTION


# ------------------------------------------------------------------ drawing
# The room's own hand: the marker and the handwriting the board is written in,
# the same two the room's sticky notes and binder labels were lettered in
# (room3d/textures.py). They live with the room, not in assets/fonts/, which
# holds only the kit's two type faces: this is ink on a whiteboard, not type
# the bot sets, and nothing else may reach for it.
ROOM_HAND = Path(__file__).resolve().parent.parent / "room3d" / "fonts"
_HAND_FACES = frozenset({"PermanentMarker.ttf", "Kalam.ttf"})


def _font(fonts: Path, name: str, size: int):
    from PIL import ImageFont

    root = ROOM_HAND if name in _HAND_FACES else fonts
    return ImageFont.truetype(str(root / name), max(int(size), 6))


def _fit_lines(draw, text: str, fonts: Path, face: str, size: int, width: float,
               lines: int):
    """(font, wrapped lines) at the largest size up to `size` that fits."""
    while True:
        font = _font(fonts, face, size)
        avg = max(draw.textlength("abcdefghij", font=font) / 10, 1)
        wrapped = textwrap.wrap(text, max(int(width / avg), 4)) or [""]
        if (len(wrapped) <= lines
                and max(draw.textlength(w, font=font) for w in wrapped) <= width) \
                or size <= 10:
            return font, wrapped[:lines]
        size = int(size * 0.9)


def _wobble(rnd: random.Random, pts, amp: float) -> list[tuple[float, float]]:
    """A ruled line as a hand draws it: the corners a little off."""
    return [(x + rnd.uniform(-amp, amp), y + rnd.uniform(-amp, amp)) for x, y in pts]


def _path(closes, box, points: int = 0) -> list[tuple[float, float]]:
    """The closes as points in `box` (x0, y0, x1, y1), one every three pixels
    or `points` in all, each the mean of the closes it stands for (a hand on
    a board draws the run, not every day of it)."""
    x0, y0, x1, y1 = box
    n = len(closes)
    k = min(points or max(int(x1 - x0) // 3, 2), n)
    edges = [round(i * n / k) for i in range(k + 1)]
    vals = [sum(closes[a:b]) / (b - a) for a, b in zip(edges, edges[1:]) if b > a]
    vals[0], vals[-1] = closes[0], closes[-1]
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1.0
    m = len(vals) - 1 or 1
    return [(x0 + (x1 - x0) * i / m, y1 - (y1 - y0) * (v - lo) / rng)
            for i, v in enumerate(vals)]


def board_ink(d: Dressing, fonts: Path, size: tuple[int, int], *,
              tick: float = 1.0, ring: float = 1.0):
    """The board's writing, as marker on a clear layer `size` big.

    Top left the episode in a box (none on a short), beside it the ticker; under them the
    question, underlined; the chapters down the left, ticked off up to the
    one the video is in and their numbers circled; the price's run as a
    red line on two ruled axes in the corner, marked with its span and no
    value.

    `tick` and `ring` are how much of the newest marks is drawn: the tick on
    the chapter just finished and the ring on the one starting, as the
    chapter break draws them (`tick_frames`).
    """
    from PIL import Image, ImageDraw

    W, H = size
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    rnd = random.Random(d.board_seed)
    pad = 0.04 * W
    stroke = max(int(0.006 * W), 2)

    ep = _font(fonts, "PermanentMarker.ttf", 0.085 * H)
    label = f"EP. {d.episode}"
    tw = dr.textlength(label, font=ep)
    asc, desc = ep.getmetrics()
    bx0, by0 = pad, pad
    bx1, by1 = bx0 + tw + 0.05 * W, by0 + asc + desc + 0.03 * H
    if d.episode > 0:
        dr.line(_wobble(rnd, [(bx0, by0), (bx1, by0), (bx1, by1), (bx0, by1), (bx0, by0)],
                        0.004 * W), fill=_INK["black"] + (255,), width=stroke, joint="curve")
        dr.text((bx0 + 0.025 * W, by0 + 0.012 * H), label, font=ep, fill=_INK["black"] + (255,))
    else:
        bx1 = pad - 0.05 * W        # a short has no number: the ticker leads

    tf = _font(fonts, "PermanentMarker.ttf", 0.15 * H)
    tx = bx1 + 0.05 * W
    ticker = f"${d.ticker}"
    while dr.textlength(ticker, font=tf) > W - pad - tx and tf.size > 12:
        tf = _font(fonts, "PermanentMarker.ttf", tf.size * 0.9)
    dr.text((tx, by0 - 0.02 * H), ticker, font=tf, fill=_INK["black"] + (255,))

    qy = by1 + 0.06 * H
    qfont, qlines = _fit_lines(dr, d.question, fonts, "PermanentMarker.ttf",
                               int(0.085 * H), W - 2 * pad, 2)
    qa, qd = qfont.getmetrics()
    for line in qlines:
        dr.text((pad, qy), line, font=qfont, fill=_INK["blue"] + (255,))
        qy += qa + qd
    if qlines:
        uw = dr.textlength(qlines[-1], font=qfont)
        dr.line(_wobble(rnd, [(pad, qy + 0.004 * H), (pad + uw, qy - 0.004 * H)], 0.003 * W),
                fill=_INK["blue"] + (255,), width=stroke)

    top = qy + 0.05 * H
    chap_w = 0.52 * W
    chapters = list(d.chapters[:BOARD_MAX_CHAPTERS])
    if chapters:
        room = (H - pad - top) / max(len(chapters), 1)
        cf = _font(fonts, "Kalam.ttf", min(0.07 * H, room * 0.82))
        y = top
        for i, title in enumerate(chapters, 1):
            text = f"{i}.  {title}"       # room for the ring round the number
            while dr.textlength(text, font=cf) > chap_w and len(text) > 6:
                text = text[:-2].rstrip() + "…"
            dr.text((pad, y), text, font=cf, fill=_INK["black"] + (255,))
            if i < d.chapter:
                _tick(dr, cf, pad + dr.textlength(text, font=cf), y,
                      tick if i == d.chapter - 1 else 1.0, f"{d.board_seed}|tick{i}", stroke)
            if i <= d.chapter:
                _ring(dr, dr.textbbox((pad, y), f"{i}.", font=cf), cf,
                      ring if i == d.chapter else 1.0, f"{d.board_seed}|ring{i}", stroke)
            y += room

    gx0, gy0, gx1, gy1 = 0.60 * W, top + 0.02 * H, W - pad, H - pad
    if gy1 - gy0 > 0.12 * H:
        axis = _INK["black"] + (255,)
        dr.line(_wobble(rnd, [(gx0, gy0), (gx0, gy1), (gx1, gy1)], 0.003 * W),
                fill=axis, width=stroke, joint="curve")
        sf = _font(fonts, "PermanentMarker.ttf", 0.06 * H)
        dr.text((gx0 + 0.015 * W, gy0 - 0.01 * H), d.span, font=sf, fill=axis)
        if len(d.closes) >= 2:
            pts = _path(d.closes, (gx0 + 0.03 * W, gy0 + 0.09 * H, gx1 - 0.02 * W,
                                   gy1 - 0.04 * H), points=56)
            pts = [(x, y + rnd.uniform(-0.002, 0.002) * H) for x, y in pts]
            dr.line(pts, fill=_INK["red"] + (255,), width=int(stroke * 1.2), joint="curve")
    return img


# THE CHAPTER MARKS: red marker, a tick after a finished chapter's title and
# a ring round each started chapter's number, drawn as a hand draws them.
_MARK_INK = _INK["red"] + (255,)


def _drawn(pts: list[tuple[float, float]], frac: float) -> list[tuple[float, float]]:
    """The first `frac` of the stroke through `pts`, by its length."""
    if frac >= 1.0 or len(pts) < 2:
        return pts
    if frac <= 0.0:
        return []
    pairs = list(itertools.pairwise(pts))
    legs = [math.dist(a, b) for a, b in pairs]
    left = sum(legs) * frac
    out = [pts[0]]
    for (a, b), leg in zip(pairs, legs):
        if left >= leg:
            out.append(b)
            left -= leg
            continue
        f = left / leg if leg else 0.0
        out.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))
        break
    return out


def _tick(dr, font, x: float, y: float, frac: float, seed: str, stroke: int) -> None:
    """A tick after a line of text set at (x, y) in `font`, `frac` of it drawn."""
    asc, desc = font.getmetrics()
    h = asc + desc
    rnd = random.Random(seed)
    x0 = x + 0.35 * h
    pts = [(x0, y + 0.52 * h), (x0 + 0.2 * h, y + 0.66 * h), (x0 + 0.3 * h, y + 0.8 * h),
           (x0 + 0.5 * h, y + 0.5 * h), (x0 + 0.72 * h, y + 0.26 * h), (x0 + 0.9 * h, y + 0.1 * h)]
    pts = [(px + rnd.uniform(-0.03, 0.03) * h, py + rnd.uniform(-0.03, 0.03) * h)
           for px, py in pts]
    part = _drawn(pts, frac)
    if len(part) >= 2:
        dr.line(part, fill=_MARK_INK, width=int(stroke * 1.3), joint="curve")


def _ring(dr, box, font, frac: float, seed: str, stroke: int) -> None:
    """A ring round the text in `box`, a little more than once round, as a
    marker goes, `frac` of it drawn."""
    asc, desc = font.getmetrics()
    h = asc + desc
    rnd = random.Random(seed)
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    rx = (x1 - x0) / 2 + 0.16 * h
    ry = (y1 - y0) / 2 + 0.1 * h
    start = rnd.uniform(-2.4, -1.6)
    turn, phase = rnd.uniform(1.12, 1.2), rnd.uniform(0, 6.28)
    n = 48
    pts = []
    for j in range(n + 1):
        a = start + 2 * math.pi * turn * j / n
        wob = 1 + 0.06 * math.sin(3 * a + phase) + 0.05 * j / n
        pts.append((cx + rx * wob * math.cos(a), cy + ry * wob * math.sin(a)))
    part = _drawn(pts, frac)
    if len(part) >= 2:
        dr.line(part, fill=_MARK_INK, width=max(int(stroke * 0.9), 2), joint="curve")


# ------------------------------------------------------ his things, lettered
# The marker on a label, the stitches of the sign (navy, as it was stitched),
# a filing's print, the red ring a card's last line gets on the second card.
_LABEL_INK = (28, 30, 36)
_STITCH_INK = (36, 50, 110)
_PRINT_INK = (24, 24, 30)
_PRINT_QUIET = (40, 40, 46)
# The sign's grid: textures.py STITCH_CELLS, one cell every 14 of its 900
# pixels (`cross_stitch`).
_STITCH_CELLS = 64
_STITCH_STEP = 14


def _fit_block(dr, text: str, fonts: Path, face: str, box_w: float, box_h: float,
               start: float, *, spacing: float = 0.08):
    """(font, lines, line height) for `text` at the largest size up to
    `start` whose lines (its own, each wrapped) fit `box_w` by `box_h`."""
    size = max(start, 8)
    while True:
        font = _font(fonts, face, size)
        avg = max(dr.textlength("abcdefghij", font=font) / 10, 1)
        lines: list[str] = []
        for part in text.split("\n"):
            # a word too long for the line shrinks the size, never splits
            lines += textwrap.wrap(part, max(int(box_w / avg), 3),
                                   break_long_words=False) or [""]
        asc, desc = font.getmetrics()
        lh = (asc + desc) * (1 + spacing)
        if (max(dr.textlength(ln, font=font) for ln in lines) <= box_w
                and lh * len(lines) <= box_h) or size <= 8:
            return font, lines, lh
        size *= 0.92


def _centred(dr, lines, font, lh, box, fill, *, left: bool = False) -> None:
    x0, y0, x1, y1 = box
    top = y0 + (y1 - y0 - lh * len(lines)) / 2
    for i, ln in enumerate(lines):
        w = dr.textlength(ln, font=font)
        x = x0 if left else x0 + (x1 - x0 - w) / 2
        dr.text((x, top + i * lh), ln, font=font, fill=fill)


def _stitches(img, text: str, fonts: Path, k: float) -> None:
    """`text` cross-stitched on the sign's grid, `k` its picture's scale."""
    from PIL import Image, ImageDraw

    cells = _STITCH_CELLS
    lines = [ln.strip() for ln in text.upper().split("\n") if ln.strip()][:4]
    if not lines:
        return
    small = Image.new("L", (cells, cells), 0)
    sd = ImageDraw.Draw(small)
    size = 14
    while size > 7:
        f = _font(fonts, "ArchivoNarrow[wght].ttf", size)
        lh = size * 0.98
        if max(sd.textlength(ln, font=f) for ln in lines) <= cells - 6 and lh * len(lines) <= cells - 16:
            break
        size -= 1
    f = _font(fonts, "ArchivoNarrow[wght].ttf", size)
    try:
        f.set_variation_by_name("Bold")       # a stitch is a thick thread
    except (OSError, ValueError, AttributeError):
        pass
    lh = size * 0.98
    top = (cells - lh * len(lines)) / 2 - 1
    for i, ln in enumerate(lines):
        sd.text(((cells - sd.textlength(ln, font=f)) / 2, top + i * lh), ln, font=f, fill=255)
    px = small.load()
    dr = ImageDraw.Draw(img)
    step = _STITCH_STEP * k
    w = max(round(5 * k), 1)
    c = _STITCH_INK + (255,)
    for cy in range(cells):
        for cx in range(cells):
            if px[cx, cy] < 120:
                continue
            x0, y0 = cx * step, cy * step
            if step < 6:
                # too small for a cross to be seen: the stitch as the block
                # of thread it reads as across the room
                dr.rectangle([x0, y0, x0 + step, y0 + step], fill=c)
                continue
            dr.line([(x0 + k, y0 + k), (x0 + step - 2 * k, y0 + step - 2 * k)], fill=c, width=w)
            dr.line([(x0 + step - 2 * k, y0 + k), (x0 + k, y0 + step - 2 * k)], fill=c, width=w)


def clock_minutes(text: str) -> float | None:
    """Minutes past twelve of "H:MM" (or "H:MM.5", a hand between two)."""
    try:
        h, m = str(text).strip().split(":")
        return (int(h) % 12) * 60 + float(m)
    except ValueError:
        return None


def clock_text(minutes: float) -> str:
    """`minutes` past twelve as the clock's "H:MM", fractions kept."""
    minutes %= 720
    h, m = divmod(minutes, 60)
    return f"{int(h) or 12}:{m:05.2f}" if m % 1 else f"{int(h) or 12}:{int(m):02d}"


def _hands(dr, text: str, cx: float, cy: float, k: float) -> None:
    """The clock's hands at "H:MM", on its face's picture (textures.clock:
    600 across, the hour hand 150 long, the minute hand 230, a red pin)."""
    m = clock_minutes(text)
    if m is None:
        return
    ink = (30, 30, 36, 255)
    for turn, length, width in ((m / 720, 150, 20), (m % 60 / 60, 230, 12)):
        a = turn * 2 * math.pi
        dr.line([(cx, cy), (cx + length * k * math.sin(a), cy - length * k * math.cos(a))],
                fill=ink, width=max(int(width * k), 1))
    r = 16 * k
    dr.ellipse([cx - r, cy - r, cx + r, cy + r], fill=_INK["red"] + (255,))


def label_ink(item: dict, text: str, fonts: Path, size: tuple[int, int]):
    """The words on one of his things, on a clear layer `size` big (its
    picture's shape): marker on a spine, a note or a box, a hand on a card,
    stitches on the sign, print on a filing; in the box its picture leaves."""
    from PIL import Image, ImageDraw

    W = size[0]
    tw, th = item.get("tex") or size
    k = W / tw
    x0, y0, x1, y1 = [v * k for v in (item.get("box") or (0, 0, tw, th))]
    bw, bh = x1 - x0, y1 - y0
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    ink = _LABEL_INK + (255,)
    kind = item.get("kind")
    text = str(text or "").strip()
    if not text:
        return img
    rnd = random.Random(f"{item.get('id')}|{text}")
    if kind == "spine":
        # read up the spine, as a binder's label is
        lay = Image.new("RGBA", (max(int(bh), 1), max(int(bw), 1)), (0, 0, 0, 0))
        ld = ImageDraw.Draw(lay)
        f, lines, lh = _fit_block(ld, text, fonts, "PermanentMarker.ttf", bh * 0.9, bw * 0.92,
                                  bw * 0.62, spacing=-0.12)
        _centred(ld, lines, f, lh, (0, 0, lay.width, lay.height), ink)
        lay = lay.rotate(90, expand=True)
        img.alpha_composite(lay, (int(x0 + (bw - lay.width) / 2), int(y0 + (bh - lay.height) / 2)))
    elif kind in ("note", "box"):
        f, lines, lh = _fit_block(dr, text, fonts, "PermanentMarker.ttf", bw, bh,
                                  bh * (0.42 if kind == "note" else 0.3), spacing=0.0)
        _centred(dr, lines, f, lh, (x0, y0, x1, y1), ink)
    elif kind == "card":
        head, *body = text.split("\n")
        blue = item.get("id", "").endswith(("1", "3", "5"))
        hf, hl, _ = _fit_block(dr, head, fonts, "PermanentMarker.ttf", bw * 0.94, 76 * k, 66 * k)
        dr.text((x0 + 6 * k, y0 + 4 * k), hl[0], font=hf,
                fill=((30, 58, 132) if blue else _LABEL_INK) + (255,))
        bf = _font(fonts, "Kalam.ttf", 54 * k)
        last = None
        for i, line in enumerate(body[:2]):
            while dr.textlength(line, font=bf) > bw * 0.96 and bf.size > 12:
                bf = _font(fonts, "Kalam.ttf", bf.size * 0.92)
            y = y0 + 104 * k + i * 74 * k
            dr.text((x0 + 10 * k, y), line, font=bf, fill=ink)
            last = (x0 + 10 * k, y, dr.textlength(line, font=bf))
        if item.get("id") == "card1" and last is not None:
            # the second card's last line, ringed in red, as the board's was
            lx, ly, lw = last
            cx, cy = lx + lw / 2, ly + 0.62 * bf.size
            pts = [(cx + (lw / 2 + 16 * k) * math.cos(a) * (1 + 0.04 * math.sin(3 * a)),
                    cy + 0.68 * bf.size * math.sin(a))
                   for a in [i / 40 * 2 * math.pi * 1.08 for i in range(41)]]
            dr.line(_wobble(rnd, pts, 1.6 * k), fill=_INK["red"] + (255,),
                    width=max(int(6 * k), 1), joint="curve")
    elif kind == "stitch":
        _stitches(img, text, fonts, k)
    elif kind == "clock":
        _hands(dr, text, (x0 + x1) / 2, (y0 + y1) / 2, k)
    elif kind in ("cover", "report"):
        title, *rest = text.split("\n")
        y = y0
        if kind == "report":
            sf = _font(fonts, "CourierPrime-Regular.ttf", 30 * k)
            for ln in ("UNITED STATES SECURITIES AND", "EXCHANGE COMMISSION"):
                dr.text((x0, y), ln, font=sf, fill=_PRINT_QUIET + (255,))
                y += 40 * k
            y += 40 * k
        tf = _font(fonts, "CourierPrime-Bold.ttf", (116 if kind == "report" else 84) * k)
        while dr.textlength(title, font=tf) > bw and tf.size > 10:
            tf = _font(fonts, "CourierPrime-Bold.ttf", tf.size * 0.92)
        dr.text((x0, y), title, font=tf, fill=_PRINT_INK + (255,))
        y += tf.size * 1.12
        for i, ln in enumerate(rest[:3]):
            big = kind == "report" and i == 0
            face = "CourierPrime-Bold.ttf" if big else "CourierPrime-Regular.ttf"
            rf = _font(fonts, face, (58 if big else 50) * k)
            while dr.textlength(ln, font=rf) > bw and rf.size > 8:
                rf = _font(fonts, face, rf.size * 0.92)
            if y + rf.size > y1:
                break
            dr.text((x0, y), ln, font=rf, fill=(_PRINT_INK if big else _PRINT_QUIET) + (255,))
            y += rf.size * 1.25
    return img


def _ground_of(pic) -> tuple[int, int, int]:
    """The paper a picture is drawn on: the median of its outermost pixels."""
    import numpy as np

    a = np.asarray(pic.convert("RGB"))
    ring = np.concatenate([a[:2].reshape(-1, 3), a[-2:].reshape(-1, 3),
                           a[:, :2].reshape(-1, 3), a[:, -2:].reshape(-1, 3)])
    return tuple(int(v) for v in np.median(ring, axis=0))


def _fit(pw: int, ph: int, box) -> tuple[float, float, float, float]:
    """`pw` x `ph` fitted whole in `box` (x0, y0, x1, y1) and centred in it."""
    x0, y0, x1, y1 = box
    k = min((x1 - x0) / pw, (y1 - y0) / ph)
    w, h = pw * k, ph * k
    x, y = x0 + (x1 - x0 - w) / 2, y0 + (y1 - y0 - h) / 2
    return x, y, x + w, y + h


def _picture(img, pic, box, reveal: float) -> None:
    """The chapter's plate `pic` in `box`, fitted whole, drawn in from the
    left as far as `reveal` with a pen's edge where it is being drawn."""
    from PIL import Image, ImageDraw

    x0, y0, x1, y1 = _fit(pic.width, pic.height, box)
    px, py = int(round(x0)), int(round(y0))
    pw, ph = max(int(round(x1)) - px, 1), max(int(round(y1)) - py, 1)
    pic = pic.resize((pw, ph), Image.LANCZOS)
    show = int(pw * max(min(reveal, 1.0), 0.0))
    if show <= 0:
        return
    img.paste(pic.crop((0, 0, show, ph)), (px, py))
    if show < pw:
        ImageDraw.Draw(img).line([(px + show, py), (px + show, py + ph)],
                                 fill=_PAPER_INK, width=max(img.width // 400, 2))


def screen_chart(d: Dressing, fonts: Path, size: tuple[int, int], *,
                 reveal: float = 1.0):
    """The monitor's whole glass, `size` big at the glass's shape: the
    chapter's plate on its own paper, or the price's run on the kit's paper
    with no value on it; drawn in as far as `reveal`."""
    from PIL import Image, ImageDraw

    W, H = size
    if d.screen:
        pic = Image.open(d.screen).convert("RGB")
        img = Image.new("RGB", size, _ground_of(pic))
        bx0, by0, bx1, by1 = _PICTURE_BOX
        _picture(img, pic, (bx0 * W, by0 * H, bx1 * W, by1 * H), reveal)
        return img
    img = Image.new("RGB", size, _PAPER)
    dr = ImageDraw.Draw(img)
    x0, y0, x1, y1 = 0.13 * W, 0.26 * H, 0.87 * W, 0.86 * H
    head = _font(fonts, "ArchivoNarrow[wght].ttf", 0.09 * H)
    dr.text((x0, 0.07 * H), f"{d.ticker}  ·  {d.span}", font=head, fill=_PAPER_TEXT)
    rule = tuple(int(p + (q - p) * 0.3) for p, q in zip(_PAPER, _PAPER_QUIET))
    for i in range(4):
        y = y0 + (y1 - y0) * i / 3
        dr.line([(x0, y), (x1, y)], fill=rule, width=max(W // 700, 1))
    if len(d.closes) >= 2:
        pts = _path(d.closes, (x0, y0 + 0.03 * H, x1, y1 - 0.03 * H))
        n = len(pts) if reveal >= 1 else int(len(pts) * max(reveal, 0.0))
        if n >= 2:
            pts = pts[:n]
            tint = tuple(int(p + (q - p) * 0.12) for p, q in zip(_PAPER, _PAPER_INK))
            dr.polygon(pts + [(pts[-1][0], y1), (pts[0][0], y1)], fill=tint)
            dr.line(pts, fill=_PAPER_INK, width=max(int(0.006 * W), 2), joint="curve")
            x, y = pts[-1]
            r = 0.008 * W
            dr.ellipse([x - r, y - r, x + r, y + r], fill=_PAPER_INK)
    else:
        f = _font(fonts, "ArchivoNarrow[wght].ttf", 0.12 * H)
        msg = "NO DATA"
        dr.text(((W - dr.textlength(msg, font=f)) / 2, 0.44 * H), msg, font=f,
                fill=_PAPER_QUIET)
    return img


def glass_quad(surf: dict, k: float = 1.0) -> list[tuple[float, float]]:
    """The monitor's whole glass as four points (top left, top right, bottom
    right, bottom left), from the chart area's `surf["quad"]` in canvas
    units, times `k`."""
    W, H = _SCREEN_TEX
    x0, y0, x1, y1 = _SCREEN_CHART
    h = _homography([(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
                    [(x * k, y * k) for x, y in surf["quad"]])

    def at(x, y):
        p = h @ (x, y, 1.0)
        return (float(p[0] / p[2]), float(p[1] / p[2]))

    return [at(0, 0), at(W, 0), at(W, H), at(0, H)]


def picture_quad(plate, d: Dressing, size: tuple[int, int]):
    """Where the chapter's picture is on the monitor, as four points of a
    frame `size` big (top left, top right, bottom right, bottom left); None
    when the room has no monitor in shot or the monitor shows the price.

    The same fit `_picture` draws it with, carried through the glass's
    corners: item 60 pushes the camera into exactly this, so the plate the
    cut lands on is the picture that was on the monitor.
    """
    from PIL import Image

    surf = (getattr(plate, "writable", None) or {}).get("screen")
    if surf is None or not d.screen:
        return None
    pw, ph = Image.open(d.screen).size
    bx0, by0, bx1, by1 = _PICTURE_BOX
    # In units of the glass's height, so its width is its aspect.
    u0, v0, u1, v1 = _fit(pw, ph, (bx0 * GLASS_ASPECT, by0, bx1 * GLASS_ASPECT, by1))
    u0, u1 = u0 / GLASS_ASPECT, u1 / GLASS_ASPECT
    h = _homography([(0, 0), (1, 0), (1, 1), (0, 1)],
                    glass_quad(surf, size[0] / plate.canvas[0]))

    def at(u, v):
        x, y, w = h @ (u, v, 1.0)
        return (float(x / w), float(y / w))

    return [at(u0, v0), at(u1, v0), at(u1, v1), at(u0, v1)]


# BACK OUT OF THE MONITOR (transitions, 18 Oct 2026): a chapter that ends on
# a full-screen chart pulls back out of it, the chart shrinking onto his
# monitor and the room coming up round it, the reverse of the push-in (item
# 60). The pull, then the room held a moment before the chapter break.
PULL_S, PULL_HOLD_S = 0.7, 0.3
# How much of the pull the chart is the plate's own sharp picture before it
# is the monitor's: at the start the camera is inside the glass, where the
# room's few hundred pixels of monitor would be a blur.
PULL_SHARP = 0.45


def pull_back_frames(room, quad, pic, size: tuple[int, int], fps: int) -> list:
    """The pull back out of the monitor as RGB frames `size` big, at `fps`.

    `room` is the written room with the chart on its monitor, `quad` where
    the chart is in it (top left, top right, bottom right, bottom left, in
    `room`'s pixels) and `pic` the chart. The first frame is `pic` filling
    the frame, the last the whole room. The camera's way out is the push-in's
    way in, its corners carried from the frame's to the picture's; its pace
    eases in and out by the picture's size, so the room does not lurch.
    """
    import numpy as np
    from PIL import Image

    W, H = size
    rw, rh = room.size
    full = [(0.0, 0.0), (rw, 0.0), (rw, rh), (0.0, rh)]
    out_corners = [(0.0, 0.0), (W, 0.0), (W, H), (0.0, H)]
    xs, ys = [p[0] for p in quad], [p[1] for p in quad]
    r = min(max(((max(xs) - min(xs)) / rw + (max(ys) - min(ys)) / rh) / 2, 0.05), 0.95)
    n = max(round(PULL_S * fps), 2)
    frames = []
    for f in range(n + round(PULL_HOLD_S * fps)):
        p = min(f / (n - 1), 1.0)
        ease = p * p * (3 - 2 * p)
        e = (1 - r ** (1 - ease)) / (1 - r)       # 1: inside the glass, 0: out
        window = [(fx + (qx - fx) * e, fy + (qy - fy) * e)
                  for (fx, fy), (qx, qy) in zip(full, quad)]
        h = _homography(out_corners, window)
        frame = room.transform((W, H), Image.PERSPECTIVE,
                               tuple(float(c) for c in (h / h[2, 2]).flatten()[:8]),
                               Image.BICUBIC)
        sharp = 1.0 - min(p / PULL_SHARP, 1.0)
        sharp = sharp * sharp * (3 - 2 * sharp)
        if sharp > 0:
            back = _homography(window, out_corners)

            def at(x, y, m=back):
                u, v, w = m @ (x, y, 1.0)
                return (float(u / w), float(v / w))

            warped = _warp(pic, [at(x, y) for x, y in quad], (W, H))
            if warped is not None:
                px, (x0, y0) = warped
                arr = np.asarray(frame, dtype=np.float32) / 255.0
                ph, pw = px.shape[:2]
                a = px[..., 3:4] * sharp
                region = arr[y0:y0 + ph, x0:x0 + pw]
                region[:] = region * (1 - a) + px[..., :3] * a
                frame = Image.fromarray((arr * 255 + 0.5).astype(np.uint8))
        frames.append(frame.convert("RGB"))
    return frames


# --------------------------------------------------------------- the warp
def _homography(src, dst):
    """The 3x3 that takes the four `src` points to the four `dst` points."""
    import numpy as np

    a, b = [], []
    for (x, y), (u, v) in zip(src, dst):
        a.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        a.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        b += [u, v]
    h = np.linalg.solve(np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64))
    return np.append(h, 1.0).reshape(3, 3)


def _warp(tex, quad, frame_size, pad: int = 0):
    """`tex` laid on `quad` (frame pixels), as (RGBA crop, (x0, y0)), or None.

    Only the quad's box is drawn, `pad` more each way, so a board a tenth of
    the frame costs a tenth of it.
    """
    import numpy as np
    from PIL import Image

    W, H = frame_size
    xs, ys = [p[0] for p in quad], [p[1] for p in quad]
    x0, y0 = max(int(min(xs)) - 2 - pad, 0), max(int(min(ys)) - 2 - pad, 0)
    x1, y1 = min(int(max(xs)) + 3 + pad, W), min(int(max(ys)) + 3 + pad, H)
    if x1 <= x0 or y1 <= y0:
        return None
    tw, th = tex.size
    corners = [(0, 0), (tw, 0), (tw, th), (0, th)]
    inv = _homography([(x - x0, y - y0) for x, y in quad], corners)
    coeffs = (inv / inv[2, 2]).flatten()[:8]
    out = tex.convert("RGBA").transform((x1 - x0, y1 - y0), Image.PERSPECTIVE,
                                        tuple(float(c) for c in coeffs),
                                        Image.BICUBIC, fillcolor=(0, 0, 0, 0))
    return np.asarray(out, dtype=np.float32) / 255.0, (x0, y0)


_LUT = None


def _linear(rgb8):
    import numpy as np

    global _LUT
    if _LUT is None:
        c = np.arange(256, dtype=np.float64) / 255.0
        _LUT = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4).astype(np.float32)
    return _LUT[rgb8]


def _encode(lin):
    import numpy as np

    c = np.clip(lin, 0.0, 1.0)
    s = np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055)
    return (s * 255 + 0.5).astype(np.uint8)


@dataclass
class _Layer:
    kind: str           # board | screen | label
    pixels: object      # float RGBA crop, 0..1, the texture in the frame
    at: tuple[int, int]
    mask: object        # float crop, 0..1, what the camera sees of the surface
    colour: object      # the surface's painted colour, linear
    # The screen's: where the render shows its bare backlight (the chart area
    # it was rendered with), to read how bright it drew it; and how far its
    # glow spills, in pixels.
    probe: object = None
    glow: float = 0.0


def _layers(plate, d: Dressing, fonts: Path, *, size: tuple[int, int] | None = None,
            reveal: float = 1.0, only: frozenset[str] | None = None,
            marks: tuple[float, float] = (1.0, 1.0)) -> list[_Layer]:
    """The board's ink and the monitor's picture, each warped into a frame
    `size` big (the plate's delivered size unless said). `marks` is how much
    of the newest tick and ring the board has (`board_ink`)."""
    import numpy as np
    from PIL import Image, ImageDraw

    size = tuple(size or plate.delivered)
    k = size[0] / plate.canvas[0]
    out = []
    for which, surf in sorted(plate.writable.items()):
        if only is not None and which not in only:
            continue
        if which == "labels":
            out += _label_layers(plate, surf, d, fonts, size, k)
            continue
        if which == "screen":
            quad = glass_quad(surf, k)
        else:
            quad = [(x * k, y * k) for x, y in surf["quad"]]
        edge = max(abs(quad[1][0] - quad[0][0]), abs(quad[2][0] - quad[3][0]))
        tw = int(min(max(edge * 1.25, 640), 3000))
        pad = 0
        if which == "board":
            sw, sh = surf.get("size") or (16, 9)
            th = max(int(tw * sh / sw), 16)
            tex = board_ink(d, fonts, (tw, th), tick=marks[0], ring=marks[1])
            colour = surf.get("paper")
        elif which == "screen":
            th = max(int(tw / GLASS_ASPECT), 16)
            tex = _falloff(screen_chart(d, fonts, (tw, th), reveal=reveal))
            colour = surf.get("backlight")
            glow = GLOW_RADIUS * edge
            pad = int(3 * glow) + 1
        else:
            continue
        warped = _warp(tex, quad, size, pad)
        mpath = plate.writable_mask(which)
        if warped is None or colour is None or mpath is None or not mpath.exists():
            continue
        px, (x0, y0) = warped
        h, w = px.shape[:2]
        m = Image.open(mpath).convert("L")
        if m.size != size:
            m = m.resize(size, Image.BILINEAR)
        mask = np.asarray(m.crop((x0, y0, x0 + w, y0 + h)), dtype=np.float32) / 255.0
        layer = _Layer(which, px, (x0, y0), mask,
                       _linear(np.asarray(colour, dtype=np.uint8)).astype(np.float32))
        if which == "screen":
            # The chart area drawn in a tenth from its edges: the backlight
            # and nothing of the app round it.
            chart = [(x * k - x0, y * k - y0) for x, y in surf["quad"]]
            cx = sum(p[0] for p in chart) / 4
            cy = sum(p[1] for p in chart) / 4
            probe = Image.new("L", (w, h), 0)
            ImageDraw.Draw(probe).polygon(
                [(cx + (x - cx) * 0.8, cy + (y - cy) * 0.8) for x, y in chart], fill=255)
            layer.probe = np.asarray(probe) > 0
            layer.glow = glow
        out.append(layer)
    return out


def _label_layers(plate, surf: dict, d: Dressing, fonts: Path, size, k: float) -> list[_Layer]:
    """One ink layer for each lettered thing in shot that this video says
    something on. The mask is all of them at once, so each takes only the
    part of it inside its own corners, and of two that overlap in the frame
    the nearer takes the overlap."""
    import numpy as np
    from PIL import Image, ImageDraw

    said = dict(d.props)
    mpath = plate.writable_mask("labels")
    if not said or mpath is None or not mpath.exists():
        return []
    m = Image.open(mpath).convert("L")
    if m.size != size:
        m = m.resize(size, Image.BILINEAR)
    whole = np.asarray(m, dtype=np.float32) / 255.0
    taken = np.zeros(whole.shape, dtype=bool)
    out = []
    for item in sorted(surf.get("items") or [], key=lambda it: float(it.get("depth", 0))):
        quad = [(x * k, y * k) for x, y in item.get("quad") or ()]
        if len(quad) != 4:
            continue
        poly = Image.new("L", size, 0)
        ImageDraw.Draw(poly).polygon(quad, fill=255)
        inside = (np.asarray(poly) > 0) & ~taken
        taken |= inside & (whole > 0.5)
        text = said.get(item.get("id"))
        if not text:
            continue
        sides = [((quad[i][0] - quad[i - 1][0]) ** 2 + (quad[i][1] - quad[i - 1][1]) ** 2) ** 0.5
                 for i in range(4)]
        tw, th = item.get("tex") or (400, 400)
        # drawn about twice the size it is seen, so the warp has detail to
        # spare and nothing to alias
        long_side = max(min(max(sides) * 2.2, max(tw, th)), 48)
        s = long_side / max(tw, th)
        tex = label_ink(item, text, fonts, (max(int(tw * s), 8), max(int(th * s), 8)))
        warped = _warp(tex, quad, size)
        if warped is None:
            continue
        px, (x0, y0) = warped
        h, w = px.shape[:2]
        mask = whole[y0:y0 + h, x0:x0 + w] * inside[y0:y0 + h, x0:x0 + w]
        if not mask.any():
            continue
        out.append(_Layer("label", px, (x0, y0), mask,
                          _linear(np.asarray(item.get("paper") or (240, 240, 236),
                                             dtype=np.uint8)).astype(np.float32)))
    return out


def _falloff(img):
    """`img` a touch darker towards its corners (SCREEN_FALLOFF), as a lit
    screen reads, rather than a flat card."""
    import numpy as np
    from PIL import Image

    w, h = img.size
    x = np.linspace(-1.0, 1.0, w, dtype=np.float32)[None, :]
    y = np.linspace(-1.0, 1.0, h, dtype=np.float32)[:, None]
    k = 1.0 - SCREEN_FALLOFF * (0.6 * x * x + 0.4 * y * y)
    a = np.asarray(img.convert("RGB"), dtype=np.float32) * k[..., None]
    return Image.fromarray(np.clip(a + 0.5, 0, 255).astype(np.uint8), "RGB")


def _soft(a, r: float):
    """`a` (h, w, channels) blurred about `r` pixels: three box passes each
    way, which reads as a Gaussian."""
    import numpy as np

    r = max(int(round(r / 1.7)), 1)
    out = a.astype(np.float64)
    for axis in (0, 1):
        for _ in range(3):
            pad = [(0, 0)] * out.ndim
            pad[axis] = (r + 1, r)
            c = np.cumsum(np.pad(out, pad), axis=axis)
            n = out.shape[axis]
            out = (np.take(c, range(2 * r + 1, n + 2 * r + 1), axis=axis)
                   - np.take(c, range(0, n), axis=axis)) / (2 * r + 1)
    return out.astype(np.float32)


def dress(img, layers: list[_Layer]):
    """`img` (RGB or RGBA, at the delivered size) with the layers written on it."""
    import numpy as np
    from PIL import Image

    arr = np.asarray(img).copy()
    for L in layers:
        x0, y0 = L.at
        h, w = L.mask.shape
        region = arr[y0:y0 + h, x0:x0 + w, :3]
        f = _linear(region)
        a = (L.pixels[..., 3] * L.mask)[..., None]
        tex = _linear((L.pixels[..., :3] * 255 + 0.5).astype(np.uint8))
        if L.kind != "screen":
            # Ink takes light away from the paint it is on: darker by the
            # ink's share of the paper, and only where it is.
            ratio = tex / np.maximum(L.colour, 1e-4)
            f = f * (1 - a * (1 - np.minimum(ratio, 1.0)))
        else:
            # The glass shines the picture as bright as the render drew its
            # backlight (dimmer where the room dips), replacing what was on
            # it: the app the room was rendered with goes under the picture.
            lit_b = L.colour
            if L.probe is not None:
                sel = L.probe & (L.mask > 0.99)
                if arr.shape[2] == 4:
                    sel &= arr[y0:y0 + h, x0:x0 + w, 3] > 0
                if sel.sum() >= 16:
                    lit_b = np.median(f[sel], axis=0)
            lit = a * tex * (SCREEN_LEVEL * lit_b / np.maximum(L.colour, 1e-4))
            f = f * (1 - a) + lit
            if L.glow > 0:
                outside = (1 - L.pixels[..., 3])[..., None]
                f = f + GLOW * _soft(lit, L.glow) * outside
        arr[y0:y0 + h, x0:x0 + w, :3] = _encode(f)
        if arr.shape[2] == 4:
            # A front layer is clear where nothing stands in front of him.
            clear = arr[y0:y0 + h, x0:x0 + w, 3] == 0
            arr[y0:y0 + h, x0:x0 + w, :3][clear] = 0
    return Image.fromarray(arr, img.mode)


# ------------------------------------------------------------- the room
def _files(plate) -> list[str]:
    """Every picture of the plate a renderer can open, each once."""
    names = [plate.files_png] + [f.png for f in plate.frames]
    names += [f.front for f in plate.frames if f.front]
    names += list(plate.layers.values())
    return list(dict.fromkeys(n for n in names if n))


def _stamp(plate, d: Dressing, names: list[str]) -> str:
    src = plate.root / plate.family
    stamp = hashlib.sha256()
    stamp.update(d.fingerprint.encode())
    for n in names:
        st = (src / n).stat()
        stamp.update(f"{n}:{st.st_size}:{st.st_mtime_ns}".encode())
    return stamp.hexdigest()[:12]


def written_room(plate, d: Dressing, out: Path, fonts: Path):
    """`plate` with this episode on its board and monitor, or `plate` itself.

    The written pictures go under `out`, named as the kit names them, and the
    plate that comes back is the same plate rooted there: every renderer that
    opens a frame, a front layer or the base file opens the written one, and
    nothing else about the room (its anchor, its slots, its own loop) changes.

    Done once per room, dressing and drawing; a second call finds it on disk.
    """
    if not getattr(plate, "writable", None):
        return plate
    src = plate.root / plate.family
    names = _files(plate)
    root = out / f"{plate.name}_{_stamp(plate, d, names)}"
    fam = root / plate.family
    done = fam / ".written"
    if not done.exists():
        from PIL import Image

        layers = _layers(plate, d, fonts)
        if not layers:
            return plate
        fam.mkdir(parents=True, exist_ok=True)
        for n in names:
            im = Image.open(src / n)
            im = im.convert("RGBA" if "A" in im.getbands() else "RGB")
            if im.size != tuple(plate.delivered):
                im = im.resize(tuple(plate.delivered), Image.LANCZOS)
            dress(im, layers).save(fam / n, compress_level=1)
        done.write_text(d.fingerprint, encoding="utf-8")
        log.info("room: wrote episode %d on %s (%s)", d.episode, plate.key,
                 ", ".join(sorted({L.kind for L in layers})))
    return replace(plate, root=root, writable={})


# THE CHAPTER BREAK ON THE BOARD (transitions, 18 Oct 2026): in place of the
# paper card between chapters, the video cuts to the board and the chapter
# just finished is ticked off, then the next one's number circled, at a
# marker's pace. In REVEAL_FPS drawings: the tick a third of a second in and
# drawn in five (the marker sound `highlight` runs 5/12 s), the ring from the
# eleventh in seven (`pen-circle`, 7/12 s), and the board held to the end.
TICK_AT, TICK_FRAMES = 4, 5
RING_AT, RING_FRAMES = 11, 7
TICK_CLIP_S = 2.0


def tick_frames(plate, d: Dressing, fonts: Path, size: tuple[int, int]):
    """Chapter `d.chapter` starting on the board, as (room, front or None)
    pairs at `size`, REVEAL_FPS of them a second for TICK_CLIP_S; None when
    the room has no board in shot or the chapter is not on it.

    The first pictures are the board as the chapter before left it; a room
    that loops keeps looping under the marker.
    """
    if ("board" not in (getattr(plate, "writable", None) or {})
            or not 2 <= d.chapter <= min(len(d.chapters), BOARD_MAX_CHAPTERS)):
        return None
    from PIL import Image

    src = plate.root / plate.family
    still = _layers(plate, d, fonts, size=size, only=frozenset({"labels", "screen"}))
    seq = list(plate.frames) if plate.animated else []
    cache: dict[str, object] = {}

    def _open(n, mode):
        if n not in cache:
            cache[n] = Image.open(src / n).convert(mode).resize(size, Image.LANCZOS)
        return cache[n]

    def _part(i: int, at: int, n: int) -> float:
        return min(max((i - at + 1) / n, 0.0), 1.0)

    out = []
    boards: dict[tuple[float, float], list] = {}
    for i in range(round(TICK_CLIP_S * REVEAL_FPS)):
        f = seq[i % len(seq)] if seq else None
        png = f.png if f is not None else plate.files_png
        front = (f.front if f is not None and f.front else plate.layers.get("front", ""))
        marks = (_part(i, TICK_AT, TICK_FRAMES), _part(i, RING_AT, RING_FRAMES))
        if marks not in boards:
            boards[marks] = _layers(plate, d, fonts, size=size, marks=marks,
                                    only=frozenset({"board"}))
        lay = boards[marks] + still
        room = dress(_open(png, "RGB"), lay)
        fr = dress(_open(front, "RGBA"), lay) if front else None
        out.append((room, fr))
    return out


# THE CLOCK JUMP (transitions, 18 Oct 2026): between two scenes inside a
# chapter, a cut to the wall clock close, its hands running on half an hour:
# it is late and he is still reading. The close-up is the room's own render
# (room3d/build.py `clock`, its face lettered blank), read from the committed
# pictures rather than the kit, which has no such room. Held, swept, held.
CLOCK_ANGLE = "clock"
CLOCK_HOLD_S, CLOCK_SWEEP_S, CLOCK_AFTER_S = 0.35, 0.45, 0.4
CLOCK_S = CLOCK_HOLD_S + CLOCK_SWEEP_S + CLOCK_AFTER_S
# How far each jump runs the hands on, in minutes.
CLOCK_JUMP_MIN = 30
ROOM3D_RENDERS = Path(__file__).resolve().parents[1] / "room3d" / "renders"


class _Shot:
    """One committed 3D render as the little of a plate the lettering reads."""

    def __init__(self, renders: Path, entry: dict):
        self.renders = renders
        self.entry = entry
        self.canvas = (1920, 1080) if entry.get("aspect", "16x9") == "16x9" else (1080, 1920)
        self.writable = {k: dict(v, mask=(entry.get("masks") or {}).get(k, ""))
                         for k, v in (entry.get("surfaces") or {}).items()
                         if (entry.get("masks") or {}).get(k)}

    def writable_mask(self, which: str) -> Path | None:
        m = (self.entry.get("masks") or {}).get(which)
        return self.renders / m if m else None

    @property
    def picture(self) -> Path:
        return self.renders / self.entry["states"][0]["png"]


def clock_shot(renders: Path = ROOM3D_RENDERS) -> _Shot | None:
    """The clock close-up, or None where the room was rendered without one."""
    try:
        entry = json.loads((renders / "rooms.json").read_text(encoding="utf-8"))[CLOCK_ANGLE]
    except (OSError, ValueError, KeyError):
        return None
    shot = _Shot(renders, entry)
    items = (shot.writable.get("labels") or {}).get("items") or []
    if not shot.picture.exists() or not any(i.get("kind") == "clock" for i in items):
        return None
    return shot


def clock_jump_frames(shot: _Shot, fonts: Path, size: tuple[int, int], fps: int,
                      start: float, end: float) -> list:
    """The clock close, its hands going from `start` to `end` (minutes past
    twelve), as RGB frames `size` big at `fps`: held, swept, held."""
    from PIL import Image

    face = next(i for i in shot.writable["labels"]["items"] if i.get("kind") == "clock")
    base = Image.open(shot.picture).convert("RGB").resize(size, Image.LANCZOS)
    hold, sweep, after = (max(round(x * fps), 1) for x in
                          (CLOCK_HOLD_S, CLOCK_SWEEP_S, CLOCK_AFTER_S))
    out, drawn = [], {}
    for f in range(hold + sweep + after):
        p = min(max((f - hold + 1) / sweep, 0.0), 1.0)
        at = round(start + (end - start) * p * p * (3 - 2 * p), 2)
        if at not in drawn:
            d = Dressing(episode=0, ticker="", props=((face["id"], clock_text(at)),))
            drawn[at] = dress(base, _layers(shot, d, fonts, size=size,
                                            only=frozenset({"labels"})))
        out.append(drawn[at])
    return out


# THE LIGHTS DIP (transitions, 18 Oct 2026): at a cut between two scenes
# inside a chapter, the room's lights sag for a breath, an old building's
# power, and the next shot comes up as they flicker back on. A layer of the
# room's night over the whole frame, a little lighter in the middle where
# his screen still glows. Down, held across the cut, back with one flicker.
DIP_IN_S, DIP_HOLD_S, DIP_OUT_S = 0.22, 0.12, 0.42
DIP_DEPTH = 0.96
_DIP_INK = (6, 9, 20)
# The way back on, as (share of the way, how dark): it catches, drops
# again, then comes up for good.
_DIP_BACK = ((0.0, 1.0), (0.14, 0.35), (0.26, 0.8), (0.4, 0.55), (1.0, 0.0))
DIP_BEFORE_S = DIP_IN_S + DIP_HOLD_S / 2
DIP_AFTER_S = DIP_HOLD_S / 2 + DIP_OUT_S


def _dip_level(p: float) -> float:
    for (p0, a0), (p1, a1) in itertools.pairwise(_DIP_BACK):
        if p <= p1:
            u = (p - p0) / (p1 - p0) if p1 > p0 else 1.0
            if p1 == 1.0:
                u = 1 - (1 - u) ** 2
            return a0 + (a1 - a0) * u
    return 0.0


def dip_frames(size: tuple[int, int], fps: int) -> tuple[list, int]:
    """The dip as RGBA frames `size` big at `fps`, and how many of them come
    before the cut it straddles."""
    import numpy as np
    from PIL import Image

    W, H = size
    n_in, n_hold, n_out = (max(round(x * fps), 1) for x in (DIP_IN_S, DIP_HOLD_S, DIP_OUT_S))
    levels = [((f + 1) / n_in) ** 2 for f in range(n_in)] + [1.0] * n_hold
    levels += [_dip_level((f + 1) / n_out) for f in range(n_out)]
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    r2 = ((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2
    shade = np.clip(0.9 + 0.1 * r2 / 2, 0.0, 1.0)
    ink = np.empty((H, W, 3), dtype=np.uint8)
    ink[:] = _DIP_INK
    out = []
    for lv in levels:
        a = (np.clip(shade * DIP_DEPTH * lv, 0.0, 1.0) * 255 + 0.5).astype(np.uint8)
        out.append(Image.fromarray(np.dstack([ink, a]), "RGBA"))
    return out, n_in + n_hold // 2


def reveal_frames(plate, d: Dressing, fonts: Path, size: tuple[int, int], *,
                  frames: int = REVEAL_FRAMES):
    """The chapter's picture drawing itself on the monitor, as `frames` pairs
    of (room, front or None) at `size`; None if the room has no monitor in
    shot.

    Kept in memory, not written beside the kit's names: only the renderer's
    clip of a chapter's first shot of the room plays them. On a room that
    loops each picture is its loop's frame at that point, so the snow keeps
    falling while the chart draws.
    """
    if "screen" not in (getattr(plate, "writable", None) or {}):
        return None
    from PIL import Image

    src = plate.root / plate.family
    board = _layers(plate, d, fonts, size=size, only=frozenset({"board", "labels"}))
    seq = list(plate.frames) if plate.animated else []
    out = []
    cache: dict[str, object] = {}

    def _open(n, mode):
        if n not in cache:
            cache[n] = Image.open(src / n).convert(mode).resize(size, Image.LANCZOS)
        return cache[n]

    for i in range(frames):
        f = seq[i % len(seq)] if seq else None
        png = f.png if f is not None else plate.files_png
        front = (f.front if f is not None and f.front else plate.layers.get("front", ""))
        lay = board + _layers(plate, d, fonts, size=size, reveal=(i + 1) / frames,
                              only=frozenset({"screen"}))
        room = dress(_open(png, "RGB"), lay)
        fr = dress(_open(front, "RGBA"), lay) if front else None
        out.append((room, fr))
    return out
