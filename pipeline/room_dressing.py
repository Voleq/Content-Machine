"""THE EPISODE, WRITTEN IN THE ROOM (item 36): the board and the monitor.

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

Every frame and every front layer of a room is written the same way, so the
desk he stands behind carries the same monitor as the room behind him.

NOTHING HERE COMPUTES A FIGURE. The board names the episode, the ticker, the
question the video asks and its chapters; the line on the board and the
monitor is the closes the price feed returned, drawn with no value on it, and
not drawn at all when the feed failed and the series was made up.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import textwrap
from dataclasses import dataclass, replace
from pathlib import Path

log = logging.getLogger(__name__)

# Bumped when the drawing changes, so a workspace's written rooms are redone.
VERSION = "3"

# What the board asks when the writer's script sets no [BOARD].
BOARD_DEFAULT_QUESTION = "what are we paying for?"
# A [BOARD] is the line a man writes on a whiteboard, not a paragraph.
BOARD_MAX_CHARS = 48
# The chapters the board lists: more than this is a smudge at any angle.
BOARD_MAX_CHAPTERS = 6

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
# The glass's width over its height in the room: build.py's screenface
# plane, 0.80 of Kenney's screen across and 0.60 of it up. Pictures are drawn
# at this shape before they go on the glass; drawn at the chart area's
# texture pixels, they came out a fifth too wide.
GLASS_ASPECT = 2.16
# Where the chapter's picture goes on the glass, as fractions of it: as tall
# as the glass less a hair, and clear of the sticky notes on its corners,
# which build.py keeps within 0.11 of either side. A 16:9 plate fills it.
_PICTURE_BOX = (0.115, 0.03, 0.885, 0.97)
# How bright the glass shines its paper, as a share of the picture: a screen
# turned down for a night room, not a light box.
SCREEN_LEVEL = 0.85
# THE GLOW: a lit screen in a dark room spills past its edge in a camera.
# What spills, as a share of what the glass shines, and how far, as a share
# of the glass's width.
GLOW = 0.3
GLOW_RADIUS = 0.05
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

    @property
    def fingerprint(self) -> str:
        raw = json.dumps([VERSION, self.episode, self.ticker, self.question,
                          list(self.chapters), [round(c, 4) for c in self.closes],
                          self.span, self.screen_stamp, self.screen_label])
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

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


def board_ink(d: Dressing, fonts: Path, size: tuple[int, int]):
    """The board's writing, as marker on a clear layer `size` big.

    Top left the episode in a box (none on a short), beside it the ticker; under them the
    question, underlined; the chapters down the left; the price's run as a
    red line on two ruled axes in the corner, marked with its span and no
    value.
    """
    from PIL import Image, ImageDraw

    W, H = size
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    rnd = random.Random(d.fingerprint)
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

    tick = _font(fonts, "PermanentMarker.ttf", 0.15 * H)
    tx = bx1 + 0.05 * W
    ticker = f"${d.ticker}"
    while dr.textlength(ticker, font=tick) > W - pad - tx and tick.size > 12:
        tick = _font(fonts, "PermanentMarker.ttf", tick.size * 0.9)
    dr.text((tx, by0 - 0.02 * H), ticker, font=tick, fill=_INK["black"] + (255,))

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
            text = f"{i}. {title}"
            while dr.textlength(text, font=cf) > chap_w and len(text) > 6:
                text = text[:-2].rstrip() + "…"
            dr.text((pad, y), text, font=cf, fill=_INK["black"] + (255,))
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
    kind: str           # board | screen
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
            reveal: float = 1.0, only: frozenset[str] | None = None) -> list[_Layer]:
    """The board's ink and the monitor's picture, each warped into a frame
    `size` big (the plate's delivered size unless said)."""
    import numpy as np
    from PIL import Image, ImageDraw

    size = tuple(size or plate.delivered)
    k = size[0] / plate.canvas[0]
    out = []
    for which, surf in sorted(plate.writable.items()):
        if only is not None and which not in only:
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
            tex = board_ink(d, fonts, (tw, th))
            colour = surf.get("paper")
        elif which == "screen":
            th = max(int(tw / GLASS_ASPECT), 16)
            tex = screen_chart(d, fonts, (tw, th), reveal=reveal)
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
        if L.kind == "board":
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
                f = f + GLOW * _soft(lit, L.glow) * (1 - a)
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
                 ", ".join(L.kind for L in layers))
    return replace(plate, root=root, writable={})


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
    board = _layers(plate, d, fonts, size=size, only=frozenset({"board"}))
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
