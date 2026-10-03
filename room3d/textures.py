"""The pictures on the things in Dennis's room: the board's working, the
screen, the filing, the clock, the city through the window, the floor.

Run once before `build.py`; it writes `room3d/textures/`. Every picture here
is the same in every episode, so none of it names a company or a ticker. The
whiteboard and the monitor's chart are left EMPTY: the bot writes them for
each video (`pipeline/room_dressing.py`), so the board is that episode's
working and the screen that company's chart. The board is a wiped white, the
chart area one even backlight, and both colours are written into
`rooms.json` so the writing can be laid on through the room's own light.

    python3 room3d/textures.py
"""
from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
OUT = HERE / "textures"
REPO_FONTS = HERE.parent / "assets" / "fonts"
# the room's own hand (also the board's, pipeline/room_dressing.py)
MARK = str(HERE / "fonts" / "PermanentMarker.ttf")
HAND = str(HERE / "fonts" / "Kalam.ttf")
COUR = str(REPO_FONTS / "CourierPrime-Bold.ttf")
COURR = str(REPO_FONTS / "CourierPrime-Regular.ttf")
NARROW = str(REPO_FONTS / "ArchivoNarrow[wght].ttf")

BLUE, RED, BLACK, GREEN = (38, 66, 156), (192, 46, 40), (28, 30, 36), (30, 120, 70)

# The surfaces the bot writes on, as they are painted here. `build.py` copies
# them into rooms.json; the writing is laid on as (ink / paper) times the
# rendered pixel, so it takes the lamp and the screen's light with it.
BOARD_TEX = (2000, 1220)
BOARD_PAPER = (238, 241, 242)
SCREEN_TEX = (1920, 1080)
# The chart area of the screen, in its picture's pixels, and its backlight: a
# middling blue-grey, so a dark chart background and a bright line both sit
# inside what an 8-bit render of it can carry.
SCREEN_CHART = (60, 116, 1392, 1044)
SCREEN_BACKLIGHT = (148, 158, 170)


def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def wobble(d: ImageDraw.ImageDraw, pts, fill, width: int, rnd: random.Random,
           jitter: float = 1.6) -> None:
    """A marker line: the points joined, every 18 px nudged off true."""
    out = []
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        n = max(int(math.hypot(x1 - x0, y1 - y0) / 18), 1)
        for i in range(n):
            t = i / n
            out.append((x0 + (x1 - x0) * t + rnd.uniform(-jitter, jitter),
                        y0 + (y1 - y0) * t + rnd.uniform(-jitter, jitter)))
    out.append(pts[-1])
    d.line(out, fill=fill, width=width, joint="curve")


def ring(d, cx, cy, rx, ry, fill, width, rnd) -> None:
    pts = [(cx + rx * math.cos(a) * (1 + 0.04 * math.sin(3 * a)), cy + ry * math.sin(a))
           for a in [i / 40 * 2 * math.pi * 1.08 for i in range(41)]]
    wobble(d, pts, fill, width, rnd)


def ghosted(w: int, h: int, base, ghost, rnd: random.Random, n: int = 10):
    """A surface somebody has wiped before: faint smears of old working."""
    im = Image.new("RGB", (w, h), base)
    g = Image.new("L", (w, h), 0)
    gd = ImageDraw.Draw(g)
    for _ in range(n):
        x, y = rnd.randint(0, w), rnd.randint(0, h)
        gd.ellipse([x - 170, y - 46, x + 170, y + 46], fill=rnd.randint(14, 30))
    g = g.filter(ImageFilter.GaussianBlur(34))
    return Image.composite(Image.new("RGB", (w, h), ghost), im, g)


def whiteboard() -> None:
    """The board, wiped: the faint smears of old working and nothing else.
    What is on it is the episode's, written by the bot."""
    rnd = random.Random(11)
    im = ghosted(*BOARD_TEX, BOARD_PAPER, (214, 220, 225), rnd, n=8)
    im.save(OUT / "whiteboard.png")


def cards() -> None:
    """Index cards held to the board by magnets: the receipts."""
    notes = [
        ("10-K  p.47", ["going concern?", "no. read it twice"], (246, 244, 236)),
        ("Q3 CALL", ["\"visibility\" x 6", "guidance: cut"], (244, 232, 150)),
        ("INSIDERS", ["CFO sold", "CEO bought (small)"], (246, 244, 236)),
        ("FCF", ["3 yrs positive", "capex falling"], (200, 226, 240)),
        ("DEBT", ["matures 2028", "refi at what rate?"], (246, 244, 236)),
        ("PEERS", ["cheaper on EV/S", "worse margins"], (240, 210, 200)),
    ]
    rnd = random.Random(5)
    for i, (head, lines, paper) in enumerate(notes):
        W, H = 600, 400
        im = Image.new("RGB", (W, H), paper)
        d = ImageDraw.Draw(im)
        for k in range(5):
            y = 120 + k * 56
            d.line([(24, y), (W - 24, y)], fill=(170, 196, 220), width=3)
        d.line([(24, 96), (W - 24, 96)], fill=(220, 120, 120), width=4)
        d.text((36, 18), head, font=font(MARK, 66), fill=BLUE if i % 2 else BLACK)
        for k, line in enumerate(lines):
            d.text((40, 118 + k * 74), line, font=font(HAND, 54), fill=BLACK)
        if i == 1:
            ring(d, 330, 236, 230, 46, RED, 6, rnd)
        im.save(OUT / f"card{i}.png")


def monitor() -> None:
    """A charting screen with no symbol on it: the window's chrome, a
    watchlist of bars where the symbols would be, and the chart area left as
    an even backlight for the episode's chart."""
    rnd = random.Random(3)
    W, H = SCREEN_TEX
    im = Image.new("RGB", (W, H), (12, 20, 32))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W, 86], fill=(22, 32, 48))
    for k, w in enumerate((180, 140, 220, 160)):
        d.rounded_rectangle([30 + k * 260, 24, 30 + k * 260 + w, 62], 10, fill=(40, 56, 78))
    d.rectangle(SCREEN_CHART, fill=SCREEN_BACKLIGHT)
    # the side panel: rows of bars where the symbols would be
    d.rectangle([1440, 120, 1890, 1040], fill=(18, 28, 42))
    for k in range(11):
        y = 150 + k * 80
        d.rounded_rectangle([1470, y, 1470 + rnd.randint(90, 160), y + 34], 8, fill=(58, 74, 98))
        col = (127, 212, 232) if rnd.random() < 0.45 else (240, 122, 90)
        d.rounded_rectangle([1740, y, 1860, y + 34], 8, fill=col)
    im.save(OUT / "monitor.png")


def filing() -> None:
    """The annual report on the desk, one line highlighted."""
    rnd = random.Random(13)
    W, H = 850, 1100
    im = Image.new("RGB", (W, H), (240, 238, 230))
    d = ImageDraw.Draw(im)
    d.text((70, 70), "UNITED STATES SECURITIES AND", font=font(COURR, 30), fill=(40, 40, 46))
    d.text((70, 110), "EXCHANGE COMMISSION", font=font(COURR, 30), fill=(40, 40, 46))
    d.text((70, 190), "FORM 10-K", font=font(COUR, 116), fill=(20, 20, 26))
    d.text((70, 330), "ANNUAL REPORT", font=font(COUR, 58), fill=(20, 20, 26))
    d.line([(70, 420), (780, 420)], fill=(40, 40, 46), width=4)
    for i in range(16):
        w = rnd.randint(420, 700)
        d.line([(70, 470 + i * 36), (70 + w, 470 + i * 36)], fill=(120, 120, 128), width=8)
    d.rectangle([60, 860, 560, 930], fill=(246, 214, 120))
    d.line([(70, 895), (540, 895)], fill=(90, 86, 70), width=8)
    im.save(OUT / "filing.png")
    # loose sheets: lines only
    im = Image.new("RGB", (W, H), (232, 234, 236))
    d = ImageDraw.Draw(im)
    for i in range(24):
        w = rnd.randint(380, 700)
        d.line([(70, 110 + i * 38), (70 + w, 110 + i * 38)], fill=(150, 152, 160), width=7)
    im.save(OUT / "sheet.png")


def clock() -> None:
    im = Image.new("RGB", (600, 600), (234, 232, 224))
    d = ImageDraw.Draw(im)
    for k in range(12):
        a = k / 12 * 2 * math.pi
        r0, r1 = (226, 280) if k % 3 == 0 else (250, 280)
        d.line([(300 + r0 * math.sin(a), 300 - r0 * math.cos(a)),
                (300 + r1 * math.sin(a), 300 - r1 * math.cos(a))],
               fill=(30, 30, 36), width=16 if k % 3 == 0 else 8)
    # three in the morning, a little after
    for a, r, w in ((3 / 12 * 2 * math.pi + 0.05, 150, 20), (0.25, 230, 12)):
        d.line([(300, 300), (300 + r * math.sin(a), 300 - r * math.cos(a))], fill=(30, 30, 36), width=w)
    d.ellipse([284, 284, 316, 316], fill=RED)
    im.save(OUT / "clock.png")


def night(snow: bool = False) -> None:
    """Across the street at night: towers, a few windows still lit, a moon."""
    rnd = random.Random(21)
    W, H = 1600, 1400
    im = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(im)
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)], fill=(int(16 + 22 * t), int(26 + 26 * t), int(52 + 34 * t)))
    d.ellipse([1140, 150, 1250, 260], fill=(226, 232, 238))
    for bx, bw, bh in ((-20, 330, 820), (330, 270, 1010), (630, 360, 700),
                       (1010, 250, 900), (1280, 340, 760)):
        d.rectangle([bx, H - bh, bx + bw, H], fill=(14, 18, 28))
        d.rectangle([bx, H - bh, bx + bw, H - bh + 14], fill=(24, 30, 44))
        for yy in range(H - bh + 46, H - 40, 66):
            for xx in range(bx + 24, bx + bw - 36, 52):
                if rnd.random() < 0.2:
                    d.rectangle([xx, yy, xx + 26, yy + 34], fill=(240, 196, 120))
    if snow:
        flakes = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        fd = ImageDraw.Draw(flakes)
        for _ in range(700):
            x, y, r = rnd.randint(0, W), rnd.randint(0, H), rnd.choice((3, 4, 5, 6))
            fd.ellipse([x - r, y - r, x + r, y + r], fill=(236, 240, 246, 220))
        im = Image.alpha_composite(im.convert("RGBA"), flakes).convert("RGB")
        d = ImageDraw.Draw(im)
        d.rectangle([0, H - 60, W, H], fill=(200, 208, 220))
    im.save(OUT / ("night_snow.png" if snow else "night.png"))


def chalkboard() -> None:
    """The slate the chapter's title is chalked on: dark, worn, empty."""
    rnd = random.Random(17)
    W, H = 1600, 760
    im = ghosted(W, H, (30, 38, 40), (58, 66, 70), rnd, n=14)
    im.save(OUT / "chalkboard.png")


def floor() -> None:
    """Floorboards: long planks, staggered, each its own shade of oak."""
    rnd = random.Random(2)
    W, H = 2048, 2048
    im = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(im)
    rows, plank = 16, 2048 // 16
    for r in range(rows):
        x = -rnd.randint(0, 700)
        while x < W:
            ln = rnd.randint(500, 900)
            base = rnd.randint(-10, 10)
            col = (92 + base, 68 + base, 50 + base)
            d.rectangle([x, r * plank, x + ln, (r + 1) * plank], fill=col)
            for k in range(6):  # grain
                yy = r * plank + rnd.randint(8, plank - 8)
                d.line([(x + 10, yy), (x + ln - 10, yy + rnd.randint(-3, 3))],
                       fill=(col[0] - 9, col[1] - 8, col[2] - 6), width=2)
            d.line([(x, r * plank), (x, (r + 1) * plank)], fill=(40, 30, 24), width=5)
            x += ln
        d.line([(0, r * plank), (W, r * plank)], fill=(40, 30, 24), width=5)
    im.save(OUT / "floor.png")


def certificate() -> None:
    """The framed print on the wall: an old share certificate, no issuer."""
    rnd = random.Random(4)
    W, H = 1400, 1000
    im = Image.new("RGB", (W, H), (226, 220, 196))
    d = ImageDraw.Draw(im)
    for k in range(4):
        d.rectangle([30 + k * 14, 30 + k * 14, W - 30 - k * 14, H - 30 - k * 14],
                    outline=(60, 110, 90), width=4)
    for k in range(60):  # the guilloche border, as overlapping rings
        a = k / 60 * 2 * math.pi
        cx, cy = W / 2 + 560 * math.cos(a), H / 2 + 380 * math.sin(a)
        d.ellipse([cx - 40, cy - 40, cx + 40, cy + 40], outline=(80, 130, 110), width=2)
    d.text((W / 2, 250), "ONE HUNDRED SHARES", font=font(COUR, 76), fill=(40, 70, 60), anchor="mm")
    d.text((W / 2, 360), "COMMON STOCK", font=font(COURR, 52), fill=(40, 70, 60), anchor="mm")
    d.ellipse([W / 2 - 120, 470, W / 2 + 120, 710], outline=(150, 60, 50), width=10)
    d.text((W / 2, 590), "100", font=font(COUR, 96), fill=(150, 60, 50), anchor="mm")
    for i in range(3):
        w = rnd.randint(500, 800)
        d.line([(W / 2 - w / 2, 790 + i * 44), (W / 2 + w / 2, 790 + i * 44)], fill=(110, 110, 96), width=6)
    im.save(OUT / "certificate.png")


# ------------------------------------------------------------ his things
# The room is his, so the props say who he is (assets/voice_bible.md): a man
# who blew up his own account and now reads the filings nobody reads, at
# 3am, flat about all of it. No real broker, firm or person is named on any
# of them.

def margin_call() -> None:
    """The margin call that ended the trading years, framed like a diploma."""
    W, H = 850, 1100
    im = Image.new("RGB", (W, H), (242, 240, 232))
    d = ImageDraw.Draw(im)
    d.rectangle([40, 40, W - 40, 150], fill=(30, 34, 44))
    d.text((70, 62), "MARGIN CALL", font=font(COUR, 74), fill=(242, 240, 232))
    f = font(COURR, 34)
    lines = ["NOTICE OF MAINTENANCE DEFICIENCY", "", "Your account equity has fallen",
             "below the maintenance requirement.", "", "AMOUNT DUE:      $41,280.17",
             "DUE BY:          4:00 PM ET", "", "If funds are not received,",
             "positions may be liquidated", "without further notice."]
    for i, ln in enumerate(lines):
        d.text((70, 200 + i * 46), ln, font=f, fill=(30, 30, 36))
    # the stamp, crooked, as stamps are
    stamp = Image.new("RGBA", (620, 190), (0, 0, 0, 0))
    sd = ImageDraw.Draw(stamp)
    sd.rectangle([8, 8, 612, 182], outline=(192, 46, 40, 230), width=12)
    sd.text((34, 44), "LIQUIDATED", font=font(COUR, 88), fill=(192, 46, 40, 230))
    stamp = stamp.rotate(14, expand=True, resample=Image.BICUBIC)
    im.paste(stamp, (110, 700), stamp)
    im.save(OUT / "margin_call.png")


def cross_stitch() -> None:
    """NOT FINANCIAL ADVICE, stitched: the disclaimer he is obliged to say,
    made into the one decoration on his wall."""
    W, H = 900, 900
    cells = 64
    small = Image.new("RGB", (cells, cells), (236, 230, 214))
    d = ImageDraw.Draw(small)
    f = ImageFont.load_default()
    for i, word in enumerate(("NOT", "FINANCIAL", "ADVICE")):
        tw = d.textlength(word, font=f)
        d.text(((cells - tw) / 2, 13 + i * 13), word, font=f, fill=(36, 50, 110))
    for k in range(0, cells, 6):  # a border of little red and green stitches
        for x, y in ((k, 4), (k, cells - 6)):
            d.rectangle([x + 1, y, x + 2, y + 1], fill=(180, 50, 46) if (k // 6) % 2 else (46, 120, 70))
    big = small.resize((W, H), Image.NEAREST)
    bd = ImageDraw.Draw(big)
    step = W // cells
    px = small.load()
    for cy in range(cells):
        for cx in range(cells):
            c = px[cx, cy]
            if c != (236, 230, 214):
                x0, y0 = cx * step, cy * step
                bd.rectangle([x0, y0, x0 + step, y0 + step], fill=(236, 230, 214))
                bd.line([(x0 + 1, y0 + 1), (x0 + step - 2, y0 + step - 2)], fill=c, width=5)
                bd.line([(x0 + step - 2, y0 + 1), (x0 + 1, y0 + step - 2)], fill=c, width=5)
    for k in range(0, W, step):  # the weave
        bd.line([(k, 0), (k, H)], fill=(222, 214, 196), width=1)
        bd.line([(0, k), (W, k)], fill=(222, 214, 196), width=1)
    big.save(OUT / "cross_stitch.png")


def notes() -> None:
    """The sticky notes on his screen."""
    for i, (text, paper, size) in enumerate((("p.41", (246, 222, 92), 150),
                                             ("NO\nCALLS", (246, 160, 170), 110),
                                             ("read the\nfootnotes", (246, 222, 92), 62))):
        im = Image.new("RGB", (400, 400), paper)
        d = ImageDraw.Draw(im)
        d.multiline_text((36, 70), text, font=font(MARK, size), fill=BLACK, spacing=10)
        im.save(OUT / f"note{i}.png")


def binders() -> None:
    """Binder spines: what is on his shelves instead of books."""
    labels = ("10-K '21", "10-K '22", "10-K '23", "10-Q", "PROXY", "CALLS")
    for i, lab in enumerate(labels):
        im = Image.new("RGB", (160, 600), (236, 236, 232))
        d = ImageDraw.Draw(im)
        d.rectangle([14, 60, 146, 360], fill=(250, 250, 246), outline=(60, 60, 66), width=4)
        txt = Image.new("RGBA", (290, 120), (0, 0, 0, 0))
        ImageDraw.Draw(txt).text((10, 20), lab, font=font(MARK, 64), fill=(28, 30, 36, 255))
        txt = txt.rotate(90, expand=True)
        im.paste(txt, (20, 66), txt)
        d.ellipse([60, 470, 100, 510], outline=(60, 60, 66), width=6)
        im.save(OUT / f"binder{i}.png")


def stack_tops() -> None:
    """The top sheets of the printed stacks, and the box they came in."""
    for name, title in (("form10q", "FORM 10-Q"), ("proxy", "DEF 14A")):
        rnd = random.Random(len(name))
        im = Image.new("RGB", (850, 1100), (238, 238, 234))
        d = ImageDraw.Draw(im)
        d.text((80, 90), title, font=font(COUR, 80), fill=(30, 30, 36))
        for i in range(18):
            d.line([(80, 300 + i * 40), (80 + rnd.randint(380, 690), 300 + i * 40)], fill=(150, 152, 160), width=8)
        im.save(OUT / f"{name}.png")
    im = Image.new("RGB", (900, 500), (176, 140, 96))
    d = ImageDraw.Draw(im)
    d.multiline_text((50, 90), "10-Ks\nDO NOT THROW OUT", font=font(MARK, 70), fill=BLACK, spacing=16)
    im.save(OUT / "boxlabel.png")


def dead_screen() -> None:
    """An old trading screen, off, and cracked."""
    rnd = random.Random(31)
    W, H = 960, 540
    im = Image.new("RGB", (W, H), (16, 20, 26))
    d = ImageDraw.Draw(im)
    cx, cy = 620, 210
    for _ in range(9):
        a = rnd.uniform(0, 2 * math.pi)
        x, y = cx, cy
        for _ in range(6):
            nx = x + math.cos(a) * rnd.uniform(40, 110)
            ny = y + math.sin(a) * rnd.uniform(40, 110)
            d.line([(x, y), (nx, ny)], fill=(150, 160, 172), width=3)
            x, y, a = nx, ny, a + rnd.uniform(-0.5, 0.5)
    im.save(OUT / "dead_screen.png")


def blanket() -> None:
    """The blanket on the sofa he sleeps on: a plain wool plaid."""
    W = H = 800
    im = Image.new("RGB", (W, H), (70, 84, 112))
    d = ImageDraw.Draw(im)
    for k in range(0, W, 160):
        d.rectangle([k, 0, k + 46, H], fill=(96, 110, 140))
        d.rectangle([0, k, W, k + 46], fill=(96, 110, 140))
        d.rectangle([k + 70, 0, k + 78, H], fill=(170, 70, 60))
        d.rectangle([0, k + 70, W, k + 78], fill=(170, 70, 60))
    im.save(OUT / "blanket.png")


def main() -> None:
    OUT.mkdir(exist_ok=True)
    whiteboard()
    cards()
    monitor()
    filing()
    clock()
    night()
    night(snow=True)
    chalkboard()
    floor()
    certificate()
    margin_call()
    cross_stitch()
    notes()
    binders()
    stack_tops()
    dead_screen()
    blanket()
    print("textures ->", OUT)


if __name__ == "__main__":
    main()
