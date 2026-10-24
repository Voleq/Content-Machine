"""The pictures on the things in Dennis's room: the board's working, the
screen, the filing, the clock, the city through the window, the floor.

Run once before `build.py`; it writes `room3d/textures/`. Every picture here
is the same in every episode, so none of it names a company or a ticker. The
whiteboard and the monitor's chart are left EMPTY: the bot writes them for
each video (`pipeline/room_dressing.py`), so the board is that episode's
working and the screen that company's chart. The board is a wiped white, the
chart area one even backlight, and both colours are written into
`rooms.json` so the writing can be laid on through the room's own light.

THE WRITING ON HIS THINGS IS EACH VIDEO'S TOO (18 Oct 2026): the binder
spines, the box's label, the tops of the printed stacks, the report on the
desk, the notes on the screen, the cards on the board and the stitched sign
are painted here with their paper and none of their words (`LABELS`), so a
shelf of "10-K '21" does not age with the room. The bot writes them per video:
the years from its date, the ticker on what he is reading, the notes and the
cards from its script.

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

# THE THINGS THE BOT LETTERS, by kind: the picture's size, the paper the words
# go on and the box they go in (its pixels), so `build.py` can say all three in
# rooms.json and the bot's hand lands where the painted label is. A paper of
# None is the item's own (`NOTE_PAPERS`, `CARD_PAPERS`).
LABELS = {
    "spine": ((160, 600), (250, 250, 246), (20, 66, 140, 354)),
    "note": ((400, 400), None, (26, 30, 374, 370)),
    "card": ((600, 400), None, (30, 14, 570, 386)),
    "stitch": ((900, 900), (236, 230, 214), (56, 98, 844, 802)),
    # the wall clock's face: its hands are the video's time (the clock jump)
    "clock": ((600, 600), (234, 232, 224), (0, 0, 600, 600)),
    "box": ((900, 500), (176, 140, 96), (40, 50, 860, 450)),
    "cover": ((850, 1100), (238, 238, 234), (70, 60, 790, 280)),
    "report": ((850, 1100), (240, 238, 230), (70, 60, 790, 440)),
    # the tag in the plant's pot: the company he was last wrong about
    "plant": ((360, 200), (242, 242, 236), (20, 24, 340, 176)),
    # his phone's lock screen, dark: lit by the video when Kev texts
    "phone": ((400, 800), (16, 18, 24), (28, 150, 372, 470)),
}
NOTE_PAPERS = ((246, 222, 92), (246, 160, 170), (246, 222, 92))
CARD_PAPERS = ((246, 244, 236), (244, 232, 150), (246, 244, 236),
               (200, 226, 240), (246, 244, 236), (240, 210, 200))
# the stitched sign's grid of crosses (pipeline/room_dressing.py stitches the
# words on the same grid)
STITCH_CELLS = 64


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
    """Index cards held to the board by magnets: the receipts. Ruled and
    blank: what is on them is the video's (`LABELS`)."""
    (W, H), _, _ = LABELS["card"]
    for i, paper in enumerate(CARD_PAPERS):
        im = Image.new("RGB", (W, H), paper)
        d = ImageDraw.Draw(im)
        for k in range(5):
            y = 120 + k * 56
            d.line([(24, y), (W - 24, y)], fill=(170, 196, 220), width=3)
        d.line([(24, 96), (W - 24, 96)], fill=(220, 120, 120), width=4)
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
    """The annual report on the desk, one line highlighted: its cover's
    words are the video's (`LABELS`, "report"). The one he holds up
    (`dennis.py`, `filing_held.png`) keeps a cover with no year on it."""
    for held in (False, True):
        rnd = random.Random(13)
        (W, H), paper, _ = LABELS["report"]
        im = Image.new("RGB", (W, H), paper)
        d = ImageDraw.Draw(im)
        if held:
            d.text((70, 70), "UNITED STATES SECURITIES AND", font=font(COURR, 30), fill=(40, 40, 46))
            d.text((70, 110), "EXCHANGE COMMISSION", font=font(COURR, 30), fill=(40, 40, 46))
            d.text((70, 190), "FORM 10-K", font=font(COUR, 116), fill=(20, 20, 26))
            d.text((70, 330), "ANNUAL REPORT", font=font(COUR, 58), fill=(20, 20, 26))
        d.line([(70, 450), (780, 450)], fill=(40, 40, 46), width=4)
        for i in range(16):
            w = rnd.randint(420, 700)
            d.line([(70, 490 + i * 34), (70 + w, 490 + i * 34)], fill=(120, 120, 128), width=8)
        d.rectangle([60, 860, 560, 930], fill=(246, 214, 120))
        d.line([(70, 895), (540, 895)], fill=(90, 86, 70), width=8)
        im.save(OUT / ("filing_held.png" if held else "filing.png"))
    W, H = 850, 1100
    # loose sheets: lines only
    im = Image.new("RGB", (W, H), (232, 234, 236))
    d = ImageDraw.Draw(im)
    for i in range(24):
        w = rnd.randint(380, 700)
        d.line([(70, 110 + i * 38), (70 + w, 110 + i * 38)], fill=(150, 152, 160), width=7)
    im.save(OUT / "sheet.png")


def clock() -> None:
    """The wall clock's face with no hands: the bot sets them to the video's
    time (`LABELS["clock"]`, pipeline/room_dressing.py)."""
    im = Image.new("RGB", (600, 600), LABELS["clock"][1])
    d = ImageDraw.Draw(im)
    for k in range(12):
        a = k / 12 * 2 * math.pi
        r0, r1 = (226, 280) if k % 3 == 0 else (250, 280)
        d.line([(300 + r0 * math.sin(a), 300 - r0 * math.cos(a)),
                (300 + r1 * math.sin(a), 300 - r1 * math.cos(a))],
               fill=(30, 30, 36), width=16 if k % 3 == 0 else 8)
    im.save(OUT / "clock_face.png")


# THE SKIES (V10): across the street at each hour and in each weather. The
# room has one pane for each, see-through and lit by itself, and a picture
# of the room is a mix of them (`build.py` SKIES and `states`), so the dusk
# sky lights the room near the window as a dusk sky would. Same street, same
# towers, the same windows: only the light changes.
TOWERS = ((-20, 330, 820), (330, 270, 1010), (630, 360, 700), (1010, 250, 900), (1280, 340, 760))
SKY_TONES = {
    # top of the sky, bottom of it, the towers, their roofline, lit windows' share
    "night": ((16, 26, 52), (38, 52, 86), (14, 18, 28), (24, 30, 44), 0.20),
    "dusk": ((58, 52, 110), (236, 140, 96), (40, 36, 66), (64, 56, 92), 0.34),
    "night_rain": ((30, 36, 50), (52, 58, 72), (24, 28, 38), (32, 38, 50), 0.16),
    "dusk_rain": ((70, 66, 92), (150, 120, 120), (48, 46, 64), (62, 60, 80), 0.28),
}


def sky(hour: str = "night", snow: bool = False) -> None:
    """Across the street: towers, some windows lit. At night a moon; at dusk
    the last of the light low behind the towers; in the rain no moon, the
    towers soft in it and their windows smeared. Down in the street, out of
    sight, the laundromat that never closes (pick 8) lights the foot of the
    tower opposite."""
    rnd = random.Random(21)
    W, H = 1600, 1400
    top, low, tower, roof, lit = SKY_TONES[hour]
    im = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(im)
    for y in range(H):
        t = (y / H) ** (1.6 if hour == "dusk" else 1.0)
        d.line([(0, y), (W, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(top, low)))
    if hour == "night":
        d.ellipse([1140, 150, 1250, 260], fill=(226, 232, 238))
    if hour == "dusk":
        d.ellipse([1130, 180, 1166, 216], fill=(236, 226, 208))      # the evening star
    for bx, bw, bh in TOWERS:
        d.rectangle([bx, H - bh, bx + bw, H], fill=tower)
        d.rectangle([bx, H - bh, bx + bw, H - bh + 14], fill=roof)
        for yy in range(H - bh + 46, H - 40, 66):
            for xx in range(bx + 24, bx + bw - 36, 52):
                if rnd.random() < lit:
                    d.rectangle([xx, yy, xx + 26, yy + 34], fill=(240, 196, 120))
    # the laundromat's light up the foot of the street, warm
    glow = Image.new("L", (W, H), 0)
    ImageDraw.Draw(glow).ellipse([W * 0.18, H * 0.86, W * 0.82, H * 1.22], fill=150 if hour != "dusk" else 70)
    glow = glow.filter(ImageFilter.GaussianBlur(70))
    im = Image.composite(Image.new("RGB", (W, H), (244, 176, 104)), im, glow)
    if hour.endswith("rain"):
        # wet air: everything softer, the lit windows run down
        im = im.filter(ImageFilter.GaussianBlur(5))
        smear = im.filter(ImageFilter.BoxBlur(1)).resize((W, H // 6)).resize((W, H))
        im = Image.blend(im, smear, 0.35)
    if snow:
        flakes = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        fd = ImageDraw.Draw(flakes)
        for _ in range(700):
            x, y, r = rnd.randint(0, W), rnd.randint(0, H), rnd.choice((3, 4, 5, 6))
            fd.ellipse([x - r, y - r, x + r, y + r], fill=(236, 240, 246, 220))
        im = Image.alpha_composite(im.convert("RGBA"), flakes).convert("RGB")
        d = ImageDraw.Draw(im)
        d.rectangle([0, H - 60, W, H], fill=(200, 208, 220) if hour == "night" else (226, 206, 200))
    im.save(OUT / f"{hour}{'_snow' if snow else ''}.png")


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


def rug() -> None:
    """The rug in the middle of the room: a worn wool kilim, brick red in a
    navy border, so the floor reads as a home's and not a bare slab."""
    rnd = random.Random(9)
    W, H = 2400, 1600
    NAVY, CREAM, BRICK, OCHRE, DEEP = (44, 52, 78), (206, 190, 156), (132, 54, 42), (196, 146, 64), (96, 36, 30)
    im = Image.new("RGB", (W, H), NAVY)
    d = ImageDraw.Draw(im)
    d.rectangle([150, 150, W - 150, H - 150], fill=CREAM)
    # the border's running diamonds
    for x in range(40, W, 110):
        for y in (75,  H - 75):
            d.polygon([(x, y - 34), (x + 34, y), (x, y + 34), (x - 34, y)], fill=OCHRE)
    for y in range(150, H - 100, 110):
        for x in (75, W - 75):
            d.polygon([(x, y - 34), (x + 34, y), (x, y + 34), (x - 34, y)], fill=OCHRE)
    # the field: a medallion of nested diamonds and two half ones at the ends
    FW, FH = W - 360, H - 360
    field = Image.new("RGB", (FW, FH), BRICK)
    fd = ImageDraw.Draw(field)
    cx, cy = FW / 2, FH / 2
    for r, c in ((560, NAVY), (500, CREAM), (450, DEEP), (330, OCHRE), (270, NAVY), (150, CREAM), (90, BRICK)):
        fd.polygon([(cx, cy - r * 0.9), (cx + r, cy), (cx, cy + r * 0.9), (cx - r, cy)], fill=c)
    for ex in (0, FW):
        for r, c in ((300, NAVY), (240, CREAM), (190, DEEP)):
            fd.polygon([(ex, cy - r * 0.9), (ex + r, cy), (ex, cy + r * 0.9), (ex - r, cy)], fill=c)
    im.paste(field, (180, 180))
    # wool and wear: a fine speckle, and the path to the desk a little paler
    px = im.load()
    for _ in range(140000):
        x, y = rnd.randrange(W), rnd.randrange(H)
        r, g, b = px[x, y]
        k = rnd.randint(-14, 14)
        px[x, y] = (max(0, min(255, r + k)), max(0, min(255, g + k)), max(0, min(255, b + k)))
    wear = Image.new("L", (W, H), 0)
    ImageDraw.Draw(wear).ellipse([W * 0.55, H * 0.15, W * 1.05, H * 0.85], fill=26)
    wear = wear.filter(ImageFilter.GaussianBlur(160))
    im = Image.composite(Image.new("RGB", (W, H), (200, 186, 160)), im, wear)
    im.save(OUT / "rug.png")


def long_run() -> None:
    """The print over the sofa, on the paper the plates are printed on: a
    century of the market drawn by hand, its three worst days marked, under
    a title as flat as he is."""
    rnd = random.Random(23)
    W, H = 1500, 1000
    PAPER, INK, RED = (236, 228, 208), (34, 34, 40), (176, 52, 44)
    im = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(im)
    d.text((W / 2, 110), "THE LONG RUN", font=font(COUR, 92), fill=INK, anchor="mm")
    d.text((W / 2, 190), "(not to scale)", font=font(COURR, 40), fill=(90, 86, 80), anchor="mm")
    x0, x1, base = 120, W - 120, H - 150
    d.line([(x0, base), (x1, base)], fill=INK, width=4)
    d.line([(x0, base), (x0, 270)], fill=INK, width=4)
    pts, y = [], base - 230
    crashes = {0.12: "1929", 0.62: "1987", 0.84: "2008"}
    marks = []
    n = 120
    for i in range(n + 1):
        t = i / n
        y -= 3.8 + rnd.uniform(-5, 5)
        for at in crashes:
            if abs(t - at) < 0.5 / n:
                y += 150 if at == 0.12 else 110
                marks.append((x0 + (x1 - x0) * t, y, crashes[at]))
        pts.append((x0 + (x1 - x0) * t, max(y, 290)))
    wobble(d, pts, INK, 7, rnd, jitter=1.2)
    for x, y, label in marks:
        d.ellipse([x - 26, y - 26, x + 26, y + 26], outline=RED, width=5)
        d.text((x + 30, y + 54), label, font=font(COUR, 40), fill=RED, anchor="lm")
    im.save(OUT / "long_run.png")


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
    """The stitched sign on the cabinet: its border of red and green
    stitches and the weave, and none of its words. What it says is the
    video's, from a list he can edit (NOT FINANCIAL ADVICE among them),
    stitched on this grid by pipeline/room_dressing.py."""
    (W, H), paper, _ = LABELS["stitch"]
    cells = STITCH_CELLS
    small = Image.new("RGB", (cells, cells), paper)
    d = ImageDraw.Draw(small)
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
    """The sticky notes on his screen, blank: the video's script fills them."""
    (W, H), _, _ = LABELS["note"]
    for i, paper in enumerate(NOTE_PAPERS):
        Image.new("RGB", (W, H), paper).save(OUT / f"note{i}.png")


def binders() -> None:
    """Binder spines: what is on his shelves instead of books. The label is
    blank: its filing and year are the video's."""
    (W, H), paper, _ = LABELS["spine"]
    im = Image.new("RGB", (W, H), (236, 236, 232))
    d = ImageDraw.Draw(im)
    d.rectangle([14, 60, 146, 360], fill=paper, outline=(60, 60, 66), width=4)
    d.ellipse([60, 470, 100, 510], outline=(60, 60, 66), width=6)
    im.save(OUT / "binder.png")


def stack_tops() -> None:
    """The top sheets of the printed stacks, and the box they came in: the
    body of each page, and no title (the video's)."""
    (W, H), paper, _ = LABELS["cover"]
    for name in ("form10q", "proxy"):
        rnd = random.Random(len(name))
        im = Image.new("RGB", (W, H), paper)
        d = ImageDraw.Draw(im)
        for i in range(18):
            d.line([(80, 300 + i * 40), (80 + rnd.randint(380, 690), 300 + i * 40)], fill=(150, 152, 160), width=8)
        im.save(OUT / f"{name}.png")
    (W, H), paper, _ = LABELS["box"]
    Image.new("RGB", (W, H), paper).save(OUT / "boxlabel.png")


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


def jar_label() -> None:
    """Mum's jar on the bookcase (pick 3): masking tape, her capitals in
    marker. The same in every video: it is her jar."""
    W, H = 640, 200
    im = Image.new("RGB", (W, H), (226, 212, 172))
    d = ImageDraw.Draw(im)
    rnd = random.Random(5)
    for _ in range(40):                       # the tape's crinkle
        x = rnd.randint(0, W)
        d.line([(x, 0), (x + rnd.randint(-20, 20), H)], fill=(214, 198, 156), width=2)
    d.text((W / 2, H / 2 + 4), "DENNIS (AGAIN)", font=font(MARK, 70), fill=(30, 34, 60), anchor="mm")
    im.save(OUT / "jar_label.png")


def loss_post() -> None:
    """His 2022 post about the loss, printed and framed (pick 4): a forum
    post drawn generic, an up arrow and its count, no site's name or mark."""
    W, H = 880, 1200
    PAPER, INK, QUIET = (246, 246, 242), (28, 30, 36), (120, 124, 132)
    im = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(im)
    d.rectangle([40, 40, W - 40, H - 40], outline=(210, 212, 216), width=4)
    # the vote column: an arrow up, the count, an arrow down
    d.polygon([(110, 130), (160, 80), (210, 130), (180, 130), (180, 170), (140, 170), (140, 130)],
              fill=(236, 92, 44))
    d.text((160, 215), "11k", font=font(COUR, 46), fill=INK, anchor="mm")
    d.polygon([(110, 270), (160, 320), (210, 270), (180, 270), (180, 230), (140, 230), (140, 270)],
              outline=QUIET, width=4)
    d.text((250, 84), "posted by dennis_reads · 2022", font=font(COURR, 28), fill=QUIET)
    title = ["Turned $41k into $612", "in nine trading days.", "AMA I guess"]
    for i, ln in enumerate(title):
        d.text((250, 140 + i * 58), ln, font=font(NARROW, 50), fill=INK)
    rnd = random.Random(8)
    for i in range(9):                         # the post itself, too small to read
        w = rnd.randint(420, 560)
        d.line([(250, 360 + i * 40), (250 + w, 360 + i * 40)], fill=(170, 172, 180), width=10)
    # a screenshot of the account in it: one line, all the way down
    d.rectangle([250, 740, 820, 1040], outline=(190, 192, 198), width=4)
    pts = [(270 + k * 13, 770 + (k / 41) ** 1.6 * 240 + rnd.uniform(-8, 8)) for k in range(42)]
    d.line(pts, fill=(204, 60, 52), width=8)
    d.text((250, 1080), "3.1k comments   ·   share   ·   save", font=font(COURR, 28), fill=QUIET)
    im.save(OUT / "loss_post.png")


def plant_tag() -> None:
    """The plastic tag in the plant's pot (pick 2), blank: the bot writes the
    company he was last wrong about on it."""
    (W, H), paper, _ = LABELS["plant"]
    im = Image.new("RGB", (W, H), paper)
    ImageDraw.Draw(im).rectangle([4, 4, W - 5, H - 5], outline=(214, 214, 206), width=6)
    im.save(OUT / "plant_tag.png")


def phone_screen() -> None:
    """His phone face up on the desk, the screen off (pick 7). When Kev
    texts, the video lights a notification on it (pipeline/room_dressing.py)."""
    (W, H), paper, _ = LABELS["phone"]
    im = Image.new("RGB", (W, H), paper)
    d = ImageDraw.Draw(im)
    d.line([(W * 0.62, 0), (W * 0.15, H)], fill=(30, 33, 42), width=60)    # a sheen on the glass
    im.save(OUT / "phone.png")


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
    for hour in SKY_TONES:
        sky(hour)
    sky("night", snow=True)
    sky("dusk", snow=True)
    chalkboard()
    floor()
    rug()
    long_run()
    certificate()
    margin_call()
    cross_stitch()
    notes()
    binders()
    stack_tops()
    dead_screen()
    blanket()
    jar_label()
    loss_post()
    plant_tag()
    phone_screen()
    print("textures ->", OUT)


if __name__ == "__main__":
    main()
