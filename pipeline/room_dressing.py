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
- THE MONITOR AS A PICTURE SHONE THROUGH ITS BACKLIGHT, so it dims with the
  render's own dip and a sticky note on the glass stays on top of it.

THE MONITOR FOLLOWS THE CHAPTER (items 49, 54): through each chapter it shows
a plate that chapter puts on screen, drawn with the chapter's own figures
(`pipeline/room_screen.py` decides which), or the price's run. It is not a
still picture: a cursor blinks on its prompt line, which makes every room
with the monitor in shot a one-second loop, and the first time a chapter's
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
import math
import random
import textwrap
from dataclasses import dataclass, replace
from pathlib import Path

log = logging.getLogger(__name__)

# Bumped when the drawing changes, so a workspace's written rooms are redone.
VERSION = "2"

# What the board asks when the writer's script sets no [BOARD].
BOARD_DEFAULT_QUESTION = "what are we paying for?"
# A [BOARD] is the line a man writes on a whiteboard, not a paragraph.
BOARD_MAX_CHARS = 48
# The chapters the board lists: more than this is a smudge at any angle.
BOARD_MAX_CHAPTERS = 6

# Marker colours, as they read on the board's paper.
_INK = {"black": (34, 38, 48), "blue": (30, 58, 132), "red": (176, 34, 40)}
# The monitor's chart.
_SCREEN_BG = (12, 20, 32)
_SCREEN_GRID = (32, 46, 66)
_SCREEN_LINE = (86, 214, 250)
_SCREEN_FILL = (22, 64, 86)
_SCREEN_TEXT = (168, 184, 204)

# THE CURSOR (item 54): on for half a second, off for half, as a terminal's
# does. A room with the monitor in shot loops at the room's own twelve frames
# a second; a room that held still becomes a one-second loop of twelve.
BLINK_FPS = 12
BLINK_FRAMES = 12
# How many pictures the chapter's chart takes to draw itself in: a second.
REVEAL_FRAMES = 12


def cursor_on(frame: int, fps: float = BLINK_FPS) -> bool:
    """Whether the cursor shows on frame `frame` of a loop at `fps`."""
    return (frame / float(fps or BLINK_FPS)) % 1.0 < 0.5


@dataclass(frozen=True)
class Dressing:
    """What one episode writes in the room."""
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
    # What the terminal's title bar says after the ticker.
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


def episode_number(settings, ticker: str, workdate: str) -> int:
    """This long's number in the channel's run of longs, counted from one.

    Its place among the longs already uploaded when it is one of them (a
    re-render keeps its number), else the next one. A long is one per ticker
    and workdate however many times it went up.
    """
    from pipeline.youtube import VideoLog, record_format

    rows = [v for v in VideoLog(settings).all() if record_format(v) == "long"]
    rows.sort(key=lambda v: v.uploaded_at or v.publish_at or v.workdate or "")
    seen: list[tuple[str, str]] = []
    for v in rows:
        k = (v.ticker.upper(), v.workdate)
        if k not in seen:
            seen.append(k)
    me = (ticker.upper(), workdate)
    return seen.index(me) + 1 if me in seen else len(seen) + 1


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

    Top left the episode in a box, beside it the ticker; under them the
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
    dr.line(_wobble(rnd, [(bx0, by0), (bx1, by0), (bx1, by1), (bx0, by1), (bx0, by0)],
                    0.004 * W), fill=_INK["black"] + (255,), width=stroke, joint="curve")
    dr.text((bx0 + 0.025 * W, by0 + 0.012 * H), label, font=ep, fill=_INK["black"] + (255,))

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


def _fit_text(dr, text: str, fonts: Path, face: str, size: float, width: float):
    """(font, text) at `size` or smaller, shortened with an ellipsis to fit."""
    font = _font(fonts, face, size)
    while dr.textlength(text, font=font) > width and font.size > 0.6 * size:
        font = _font(fonts, face, font.size * 0.92)
    while dr.textlength(text, font=font) > width and len(text) > 4:
        text = text[:-2].rstrip() + "…"
    return font, text


def _prompt(dr, d: Dressing, fonts: Path, W: int, H: int, cursor: bool) -> None:
    """The terminal's prompt line along the bottom, with its cursor.

    Starts clear of the note stuck on the glass's bottom left corner.
    """
    dr.line([(0.035 * W, 0.885 * H), (0.965 * W, 0.885 * H)], fill=_SCREEN_GRID,
            width=max(W // 500, 1))
    f = _font(fonts, "ArchivoNarrow[wght].ttf", 0.058 * H)
    text = f"{d.ticker} ›"
    x, y = 0.17 * W, 0.905 * H
    dr.text((x, y), text, font=f, fill=_SCREEN_TEXT)
    if cursor:
        cx = x + dr.textlength(text + " ", font=f)
        asc, _ = f.getmetrics()
        dr.rectangle([cx, y + 0.12 * asc, cx + 0.022 * W, y + 1.02 * asc],
                     fill=_SCREEN_TEXT)


def _picture(img, path: str, box, reveal: float) -> None:
    """The chapter's plate in `box`, fitted whole, drawn in from the left as
    far as `reveal` with a bright edge where it is being drawn."""
    from PIL import Image, ImageDraw

    x0, y0, x1, y1 = box
    pic = Image.open(path).convert("RGBA")
    k = min((x1 - x0) / pic.width, (y1 - y0) / pic.height)
    pw, ph = max(int(pic.width * k), 1), max(int(pic.height * k), 1)
    pic = pic.resize((pw, ph), Image.LANCZOS)
    px, py = int(x0 + (x1 - x0 - pw) / 2), int(y0 + (y1 - y0 - ph) / 2)
    show = int(pw * max(min(reveal, 1.0), 0.0))
    if show <= 0:
        return
    ground = Image.new("RGBA", (show, ph), _SCREEN_BG + (255,))
    ground.alpha_composite(pic.crop((0, 0, show, ph)))
    img.paste(ground.convert("RGB"), (px, py))
    if show < pw:
        ImageDraw.Draw(img).line([(px + show, py), (px + show, py + ph)],
                                 fill=_SCREEN_LINE, width=max(img.width // 300, 2))


def screen_chart(d: Dressing, fonts: Path, size: tuple[int, int], *,
                 reveal: float = 1.0, cursor: bool = True):
    """The monitor's picture: the chapter's plate, or the price's run on a dark
    terminal with no value on it; drawn in as far as `reveal`, with the
    prompt's cursor on or off."""
    from PIL import Image, ImageDraw

    W, H = size
    img = Image.new("RGB", size, _SCREEN_BG)
    dr = ImageDraw.Draw(img)
    # Clear of the note stuck on the glass's top left corner.
    hx = 0.13 * W
    if d.screen:
        label = f"{d.ticker}  ·  {d.screen_label}" if d.screen_label else d.ticker
        head, label = _fit_text(dr, label, fonts, "ArchivoNarrow[wght].ttf",
                                0.075 * H, 0.965 * W - hx)
        dr.text((hx, 0.03 * H), label, font=head, fill=_SCREEN_TEXT)
        _picture(img, d.screen, (0.035 * W, 0.135 * H, 0.965 * W, 0.865 * H), reveal)
        _prompt(dr, d, fonts, W, H, cursor)
        return img
    for i in range(1, 6):
        x = W * i / 6
        dr.line([(x, 0), (x, 0.865 * H)], fill=_SCREEN_GRID, width=max(W // 600, 1))
    for i in range(1, 4):
        y = 0.865 * H * i / 4
        dr.line([(0, y), (W, y)], fill=_SCREEN_GRID, width=max(W // 600, 1))
    head = _font(fonts, "ArchivoNarrow[wght].ttf", 0.075 * H)
    dr.text((hx, 0.03 * H), f"{d.ticker}  ·  {d.span}", font=head, fill=_SCREEN_TEXT)
    if len(d.closes) >= 2:
        pts = _path(d.closes, (0.035 * W, 0.17 * H, 0.965 * W, 0.80 * H))
        n = len(pts) if reveal >= 1 else int(len(pts) * max(reveal, 0.0))
        if n >= 2:
            pts = pts[:n]
            dr.polygon(pts + [(pts[-1][0], 0.84 * H), (pts[0][0], 0.84 * H)],
                       fill=_SCREEN_FILL)
            dr.line(pts, fill=_SCREEN_LINE, width=max(int(0.005 * W), 2), joint="curve")
            x, y = pts[-1]
            r = 0.009 * W
            dr.ellipse([x - r, y - r, x + r, y + r], fill=_SCREEN_LINE)
    else:
        f = _font(fonts, "ArchivoNarrow[wght].ttf", 0.12 * H)
        msg = "NO DATA"
        dr.text(((W - dr.textlength(msg, font=f)) / 2, 0.38 * H), msg, font=f,
                fill=_SCREEN_TEXT)
    _prompt(dr, d, fonts, W, H, cursor)
    return img


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


def _warp(tex, quad, frame_size):
    """`tex` laid on `quad` (frame pixels), as (RGBA crop, (x0, y0)), or None.

    Only the quad's box is drawn, so a board a tenth of the frame costs a
    tenth of it.
    """
    import numpy as np
    from PIL import Image

    W, H = frame_size
    xs, ys = [p[0] for p in quad], [p[1] for p in quad]
    x0, y0 = max(int(min(xs)) - 2, 0), max(int(min(ys)) - 2, 0)
    x1, y1 = min(int(max(xs)) + 3, W), min(int(max(ys)) + 3, H)
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


def _layers(plate, d: Dressing, fonts: Path, *, size: tuple[int, int] | None = None,
            cursor: bool = True, reveal: float = 1.0,
            only: frozenset[str] | None = None) -> list[_Layer]:
    """The board's ink and the monitor's picture, each warped into a frame
    `size` big (the plate's delivered size unless said)."""
    import numpy as np
    from PIL import Image

    size = tuple(size or plate.delivered)
    k = size[0] / plate.canvas[0]
    out = []
    for which, surf in sorted(plate.writable.items()):
        if only is not None and which not in only:
            continue
        quad = [(x * k, y * k) for x, y in surf["quad"]]
        edge = max(abs(quad[1][0] - quad[0][0]), abs(quad[2][0] - quad[3][0]))
        sw, sh = surf.get("size") or (16, 9)
        tw = int(min(max(edge * 1.25, 640), 3000))
        th = max(int(tw * sh / sw), 16)
        if which == "board":
            tex = board_ink(d, fonts, (tw, th))
            colour = surf.get("paper")
        elif which == "screen":
            tex = screen_chart(d, fonts, (tw, th), reveal=reveal, cursor=cursor)
            colour = surf.get("backlight")
        else:
            continue
        warped = _warp(tex, quad, size)
        mpath = plate.writable_mask(which)
        if warped is None or colour is None or mpath is None or not mpath.exists():
            continue
        px, (x0, y0) = warped
        h, w = px.shape[:2]
        m = Image.open(mpath).convert("L")
        if m.size != size:
            m = m.resize(size, Image.BILINEAR)
        mask = np.asarray(m.crop((x0, y0, x0 + w, y0 + h)), dtype=np.float32) / 255.0
        out.append(_Layer(which, px, (x0, y0), mask,
                          _linear(np.asarray(colour, dtype=np.uint8)).astype(np.float32)))
    return out


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
        ratio = tex / np.maximum(L.colour, 1e-4)
        if L.kind == "board":
            # Ink takes light away from the paint it is on: darker by the
            # ink's share of the paper, and only where it is.
            f = f * (1 - a * (1 - np.minimum(ratio, 1.0)))
        else:
            # The chart replaces the backlight it is shone through.
            f = f * (1 - a + a * ratio)
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


def _off(name: str) -> str:
    """The name the cursor-off picture of `name` is written under."""
    p = Path(name)
    return str(p.with_name(p.stem + ".off" + p.suffix))


def written_room(plate, d: Dressing, out: Path, fonts: Path):
    """`plate` with this episode on its board and monitor, or `plate` itself.

    The written pictures go under `out`, named as the kit names them, and the
    plate that comes back is the same plate rooted there: every renderer that
    opens a frame, a front layer or the base file opens the written one, and
    nothing else about the room (its anchor, its slots) changes.

    A room with the monitor in shot comes back LOOPING (item 54): the cursor
    on the prompt line is on for half of each second and off for the other,
    so a room that held still is now twelve frames a second over its two
    pictures, and a room that already looped (the December lights, the rain)
    keeps its own frames with the cursor written on each. Every renderer that
    plays a looping room plays it unchanged.

    Done once per room, dressing and drawing; a second call finds it on disk.
    """
    if not getattr(plate, "writable", None):
        return plate
    src = plate.root / plate.family
    names = _files(plate)
    root = out / f"{plate.name}_{_stamp(plate, d, names)}"
    fam = root / plate.family
    done = fam / ".written"
    screen = "screen" in plate.writable
    if screen:
        loop = list(plate.frames) if plate.animated else []
        fps = float(plate.fps or BLINK_FPS) if loop else float(BLINK_FPS)
        if loop:
            # Long enough for the cursor's whole second to come round on the
            # room's own loop: a three-frame loop would only ever show it on.
            per = max(int(round(fps)), 1)
            loop = [loop[i % len(loop)]
                    for i in range(len(loop) * per // math.gcd(len(loop), per))]
            # A frame that names no front of its own has the room's one front,
            # which carries the monitor too and so blinks with it.
            front = plate.layers.get("front", "")
            loop = [f if f.front or not front else replace(f, front=front) for f in loop]
        else:
            # A room that held still: its one picture, twelve times.
            base = (plate.frames[0] if plate.frames else None)
            front = plate.layers.get("front", "")
            loop = [replace(base, png=plate.files_png, front=front) if base is not None
                    else _frame(plate.files_png, front)] * BLINK_FRAMES
        offs = sorted({n for i, f in enumerate(loop) if not cursor_on(i, fps)
                       for n in (f.png, f.front) if n})
    if not done.exists():
        from PIL import Image

        layers = _layers(plate, d, fonts)
        if not layers:
            return plate
        # The same with the cursor off: the board as it is, the monitor again.
        dark = ([L for L in layers if L.kind != "screen"]
                + _layers(plate, d, fonts, cursor=False, only=frozenset({"screen"}))
                if screen else [])
        fam.mkdir(parents=True, exist_ok=True)

        def _open(n):
            im = Image.open(src / n)
            im = im.convert("RGBA" if "A" in im.getbands() else "RGB")
            if im.size != tuple(plate.delivered):
                im = im.resize(tuple(plate.delivered), Image.LANCZOS)
            return im

        for n in names:
            im = dress(_open(n), layers)
            im.save(fam / n, compress_level=1)
            if screen and n in offs:
                dress(_open(n), dark).save(fam / _off(n), compress_level=1)
        done.write_text(d.fingerprint, encoding="utf-8")
        log.info("room: wrote episode %d on %s (%s)", d.episode, plate.key,
                 ", ".join(L.kind for L in layers))
    if not screen:
        return replace(plate, root=root, writable={})
    frames = tuple(f if cursor_on(i, fps) else
                   replace(f, png=_off(f.png), front=_off(f.front) if f.front else "")
                   for i, f in enumerate(loop))
    return replace(plate, root=root, writable={}, frames=frames, playback="loop",
                   fps=fps, frame_count=len(frames), base_is_frame=frames[0].tag)


def _frame(png: str, front: str = ""):
    from pipeline.plates import Frame

    return Frame(tag="f0", png=png, front=front)


def reveal_frames(plate, d: Dressing, fonts: Path, size: tuple[int, int], *,
                  frames: int = REVEAL_FRAMES):
    """The chapter's picture drawing itself on the monitor, as `frames` pairs
    of (room, front or None) at `size`, cursor on; None if the room has no
    monitor in shot.

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
