"""Pillow raster + animation-frame generation, and ASS karaoke captions.

All text is rendered with Pillow (never ImageMagick / MoviePy TextClip).
Animated moments (row type-ons, hand-drawn scribbles, zoom-punches, flash
stingers) are generated here as short RGBA frame sequences, encoded once
by ffmpeg into small alpha .mov clips, and composited by the FFmpeg
filtergraph — Python never renders per-frame at video resolution for the
full timeline.

This is the reusable SHORT asset kit (§4): headline-overlay treatment,
numbers sheet, caption style, hand-drawn annotations, transition
stingers, intro/outro bug. Placeholder aesthetics; the production kit
from Claude Design drops over the same components.
"""

from __future__ import annotations

import math
import random
import re
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from config import Settings
from pipeline.models import WordTimestamp
from pipeline.render_common import run_ffmpeg

# Bundled brand fonts (Google Fonts, reproduced from the .dc.html kits):
#   Shantell Sans — hand-drawn headlines + marker text
#   Space Grotesk — numbers / UI sans
#   Space Mono    — labels + tags
SHANTELL = "ShantellSans-Bold.ttf"
SHANTELL_ITALIC = "ShantellSans-BoldItalic.ttf"
GROTESK = "SpaceGrotesk-Medium.ttf"
GROTESK_BOLD = "SpaceGrotesk-Bold.ttf"
MONO = "SpaceMono-Regular.ttf"
MONO_BOLD = "SpaceMono-Bold.ttf"
DISPLAY_BOLD = GROTESK_BOLD          # UI display sans (back-compat alias)

# Palette — the LIGHT kit. Dennis is drawn in dark ink on paper, and the
# names below keep their meaning through the swap: BG is whatever the page
# is, INK is whatever text is drawn in. Only the values inverted, so every
# card, chart and caption in this module followed without touching them.
#
# Red carries down-moves and emphasis; green is UP ONLY — it is the one
# colour the kit refuses to use decoratively.
BG = (242, 242, 239)       # #f2f2ef  paper
BG_CARD = (250, 249, 246)  # #faf9f6  the tall beat card
BG_MARK = (242, 242, 239)  # #f2f2ef  marker chart paper
CARD = (250, 249, 246)     # #faf9f6  inner card
CARD2 = (238, 236, 229)    # #eeece5
CARD_LINE = (226, 223, 213)  # #e2dfd5  inner card border
BORDER = (207, 204, 194)   # #cfccc2  card border
BORDER2 = (211, 207, 196)  # #d3cfc4  chip border
INK = (35, 35, 38)         # #232326  text
MUTED = (143, 140, 131)    # #8f8c83  muted text
MUTED2 = (74, 71, 63)      # #4a473f  secondary text
FAINT = (179, 176, 166)    # #b3b0a6  faintest label
GREEN = (47, 213, 118)     # #2fd576  UP ONLY
RED = (255, 82, 71)        # #ff5247  down / emphasis
GRID = (222, 219, 209)     # #dedbd1  chart gridlines
ACCENT = RED               # the light kit leads with red, not green
GOLD = RED                 # back-compat alias
PANEL = CARD               # back-compat alias
PANEL_LINE = CARD_LINE     # back-compat alias


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


def text_panel(
    settings: Settings,
    text: str,
    *,
    width: int,
    font_name: str = DISPLAY_BOLD,
    font_size: int = 64,
    fg=(*INK, 255),
    bg=(*PANEL, 235),
    accent=None,
    pad: int = 36,
    align: str = "center",
    radius: int = 26,
) -> Image.Image:
    """Auto-height rounded panel with wrapped text (hook / conclusion cards)."""
    font = load_font(settings, font_name, font_size)
    probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    inner = width - 2 * pad - (14 if accent else 0)
    lines = _wrap(probe, text, font, inner)
    ascent, descent = font.getmetrics()
    lh = int((ascent + descent) * 1.12)
    height = 2 * pad + lh * len(lines)

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, width - 1, height - 1], radius=radius, fill=bg)
    if accent:
        d.rounded_rectangle([0, 0, 14, height - 1], radius=7, fill=(*accent, 255))
    x0 = pad + (14 if accent else 0)
    for i, line in enumerate(lines):
        lw = probe.textlength(line, font=font)
        if align == "center":
            x = (width - lw) / 2
        else:
            x = x0
        d.text((x, pad + i * lh), line, font=font, fill=fg)
    return img


def simple_text(
    settings: Settings,
    text: str,
    *,
    font_name: str = MONO_BOLD,
    font_size: int = 44,
    fill=(*INK, 255),
    stroke_width: int = 0,
    stroke_fill=(*BG, 255),
) -> Image.Image:
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


def brand_bug(settings: Settings, opener: str, *, width: int,
              font_size: int = 34) -> Image.Image:
    """The intro/outro bug: the marker wordmark + the sampled hook-bank
    opener, in the brand's hand-drawn + mono pairing."""
    name_font = load_font(settings, SHANTELL, font_size)
    line_font = load_font(settings, MONO, int(font_size * 0.62))
    probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    name = settings.brand_name.lower()
    nw = probe.textlength(name, font=name_font)
    lw = probe.textlength(opener, font=line_font)
    h = name_font.size + line_font.size + 30
    img = Image.new("RGBA", (width, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # wordmark, with the signature red terminal dot
    d.text(((width - nw) / 2 - 6, 0), name, font=name_font, fill=(*INK, 255))
    d.text(((width - nw) / 2 - 6 + nw, 0), ".", font=name_font, fill=(*RED, 255))
    d.text(((width - lw) / 2, name_font.size + 12), opener, font=line_font,
           fill=(*MUTED, 255))
    return img


def ticker_pill(settings: Settings, ticker: str, *, font_size: int = 40) -> Image.Image:
    """The $TICKER pill — Space Mono bold, near-black on signal green."""
    font = load_font(settings, MONO_BOLD, font_size)
    label = ticker if ticker.startswith("$") else f"${ticker}"
    probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    tw = probe.textlength(label, font=font)
    padx, pady = int(font_size * 0.42), int(font_size * 0.26)
    w, h = int(tw + 2 * padx), int(font.size + 2 * pady)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=int(h * 0.22), fill=(*GREEN, 255))
    d.text((padx, pady - 2), label, font=font, fill=(*INK, 255))
    return img


def nos_header(settings: Settings, *, font_size: int = 30) -> Image.Image:
    """The "noise or signal?" header — Shantell Sans, muted, with a red "?"."""
    font = load_font(settings, SHANTELL, font_size)
    probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    base, mark = "noise or signal", "?"
    bw = probe.textlength(base, font=font)
    mw = probe.textlength(mark, font=font)
    w, h = int(bw + mw + 8), int(font.size + 10)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.text((0, 2), base, font=font, fill=(*MUTED, 255),
           stroke_width=2, stroke_fill=(0, 0, 0, 160))
    d.text((bw + 2, 2), mark, font=font, fill=(*RED, 255),
           stroke_width=2, stroke_fill=(0, 0, 0, 160))
    return img


def lower_third(settings: Settings, primary: str, secondary: str = "", *,
                width: int, font_size: int = 34) -> Image.Image:
    """A branded lower-third strip: primary line (Space Grotesk) + a muted
    Space Mono secondary, on a dark card with a green left edge."""
    pf = load_font(settings, GROTESK_BOLD, font_size)
    sf = load_font(settings, MONO, int(font_size * 0.6))
    pad = int(font_size * 0.5)
    bar = int(font_size * 0.22)
    h = pad * 2 + pf.size + (sf.size + 6 if secondary else 0)
    img = Image.new("RGBA", (width, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, width - 1, h - 1], radius=10, fill=(*CARD, 235),
                        outline=(*CARD_LINE, 255), width=1)
    d.rounded_rectangle([0, 0, bar, h - 1], radius=3, fill=(*GREEN, 255))
    d.text((bar + pad, pad), primary, font=pf, fill=(*INK, 255))
    if secondary:
        d.text((bar + pad, pad + pf.size + 6), secondary, font=sf, fill=(*MUTED, 255))
    return img


def _brand_grid(d: ImageDraw.ImageDraw, W: int, H: int) -> None:
    step = max(H // 16, 40)
    for x in range(0, W, step):
        d.line([x, 0, x, H], fill=(20, 20, 24), width=1)
    for y in range(0, H, step):
        d.line([0, y, W, y], fill=(20, 20, 24), width=1)


def interstitial_card(
    settings: Settings, *, width: int, height: int, scene_path: Path | None,
    headline: str = "", kicker: str = "", accent=GREEN, period=RED,
) -> Image.Image:
    """A composed full-frame brand card for the LONG's cutaways: a mascot
    scene (carrying its own hand-lettered label) on the brand grid, with a
    Space Mono section kicker + green rule top-left. The scene is the hero;
    the top-right and bottom bands stay clear for the corner bug, the
    lower-third and the captions."""
    W, H = width, height
    img = Image.new("RGBA", (W, H), (*BG, 255))
    d = ImageDraw.Draw(img)
    _brand_grid(d, W, H)
    pad = int(H * 0.075)

    # section kicker, top-left, with a short green rule under it
    if kicker:
        kf = load_font(settings, MONO_BOLD, int(H * 0.03))
        d.text((pad, pad), kicker.upper(), font=kf, fill=(*MUTED, 255))
        d.line([pad, pad + kf.size + 12, pad + int(W * 0.09), pad + kf.size + 12],
               fill=(*accent, 255), width=3)

    # the mascot scene, large, centred in the upper two-thirds (clear of the
    # bottom caption band)
    if scene_path is not None and Path(scene_path).exists():
        scene = Image.open(scene_path).convert("RGBA")
        sh = int(H * 0.56)
        sw = int(scene.width * sh / scene.height)
        if sw > W - 2 * pad:
            sw = W - 2 * pad
            sh = int(scene.height * sw / scene.width)
        scene = scene.resize((sw, sh), Image.LANCZOS)
        img.alpha_composite(scene, ((W - sw) // 2, int(H * 0.13)))

    # optional short hand-drawn line, mid-frame left (for scenes with no
    # baked label) — sits well above the caption band
    if headline:
        hf = load_font(settings, SHANTELL, int(H * 0.06))
        probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
        lw = probe.textlength(headline, font=hf)
        d.text((pad, int(H * 0.76)), headline, font=hf, fill=(*INK, 255))
        d.text((pad + lw, int(H * 0.76)), ".", font=hf, fill=(*period, 255))
    return img


def intro_card(settings: Settings, ticker: str, tagline: str, *,
               width: int, height: int, scene_path: Path | None = None) -> Image.Image:
    """The LONG opening title card: the marker wordmark + $TICKER pill +
    the tagline + a mascot, composed on the brand grid — a real open, not a
    lone mascot on a flat backdrop."""
    W, H = width, height
    img = Image.new("RGBA", (W, H), (*BG, 255))
    d = ImageDraw.Draw(img)
    _brand_grid(d, W, H)

    if scene_path is not None and Path(scene_path).exists():
        scene = Image.open(scene_path).convert("RGBA")
        sh = int(H * 0.42)
        sw = int(scene.width * sh / scene.height)
        scene = scene.resize((sw, sh), Image.LANCZOS)
        img.alpha_composite(scene, ((W - sw) // 2, int(H * 0.10)))

    # wordmark, centred, with the red terminal dot
    wf = load_font(settings, SHANTELL, int(H * 0.16))
    name = settings.brand_name.lower()
    probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    nw = probe.textlength(name, font=wf)
    dot = probe.textlength(".", font=wf)
    wy = int(H * 0.58)
    d.text(((W - nw - dot) / 2, wy), name, font=wf, fill=(*INK, 255))
    d.text(((W - nw - dot) / 2 + nw, wy), ".", font=wf, fill=(*RED, 255))

    # ticker pill + tagline under the wordmark
    pill = ticker_pill(settings, ticker, font_size=int(H * 0.05))
    img.alpha_composite(pill, ((W - pill.width) // 2, wy + int(wf.size * 1.05)))
    tf = load_font(settings, MONO, int(H * 0.032))
    tw = probe.textlength(tagline, font=tf)
    d.text(((W - tw) / 2, wy + int(wf.size * 1.05) + pill.height + int(H * 0.02)),
           tagline, font=tf, fill=(*MUTED, 255))
    return img


def chapter_stinger(settings: Settings, number: str, title: str, *,
                    width: int, height: int) -> Image.Image:
    """A full-frame chapter stinger card: a big Shantell chapter title with
    a mono kicker and the red terminal dot — the LONG section divider.

    The title is FITTED. It used to be drawn at a fixed size from the left
    margin, which was invisible while the titles were six hardcoded two-word
    phrases; the moment the script's own sections reached the card, "what the
    money actually does" ran off the right-hand edge mid-word.
    """
    img = Image.new("RGBA", (width, height), (*BG, 235))
    d = ImageDraw.Draw(img)
    kick = load_font(settings, MONO_BOLD, max(int(height * 0.045), 14))
    left = int(width * 0.1)
    avail = width - left * 2
    probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))

    size = max(int(height * 0.16), 28)
    floor = max(int(height * 0.07), 18)
    big = load_font(settings, SHANTELL, size)
    while size > floor and probe.textlength(f"{title}.", font=big) > avail:
        size -= 2
        big = load_font(settings, SHANTELL, size)

    lines = [title]
    if probe.textlength(f"{title}.", font=big) > avail:
        # Still too long at the floor: break on a word boundary rather than
        # shrinking the section title into illegibility.
        from pipeline.kit_frames import _wrap_to

        lines = _wrap_to(d, title, big, avail) or [title]

    line_h = int(size * 1.12)
    top = int(height * 0.44) - (len(lines) - 1) * line_h // 2
    d.text((left, int(height * 0.36) - (len(lines) - 1) * line_h // 2),
           number.upper(), font=kick, fill=(*MUTED, 255))
    for i, line in enumerate(lines):
        y = top + i * line_h
        d.text((left, y), line, font=big, fill=(*INK, 255))
        if i == len(lines) - 1:
            d.text((left + probe.textlength(line, font=big), y), ".",
                   font=big, fill=(*RED, 255))
    return img


# --------------------------------------------------------------------------
# Full-frame media treatment + designed backdrops (the LONG "media IS the
# background" kit). Every LONG still is composed to fill the frame — never a
# bare black frame, never letterbox bars. The renderer holds it still.
# --------------------------------------------------------------------------


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
    bg = Image.blend(bg, Image.new("RGB", (W, H), BG), 0.42)
    fg = img.copy()
    fg.thumbnail((int(W * 0.92), int(H * 0.9)), Image.LANCZOS)
    ox, oy = (W - fg.width) // 2, (H - fg.height) // 2
    bg.paste(fg, (ox, oy))
    if border:
        ImageDraw.Draw(bg).rectangle(
            [ox - 2, oy - 2, ox + fg.width + 1, oy + fg.height + 1],
            outline=BORDER2, width=2)
    return bg


# the designed filler families — visually distinct looks so consecutive
# filler beats never read as "the same scene on repeat"
LONG_BACKDROP_FAMILIES = 5


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def long_backdrop(
    settings: Settings, width: int, height: int, variant: int, *,
    ticker: str = "", label: str = "", seed: str = "bg",
) -> Image.Image:
    """A DESIGNED Dennis-palette full-frame background for a filler beat.

    `variant` selects one of a few visually distinct families (gradient,
    grid texture, a branded 'signal' chart card, a chapter word, a dot
    field). Because the families differ so strongly, a run of filler cuts
    reads as motion through a designed deck — never a repeated bare frame.
    """
    W, H = width, height
    fam = variant % LONG_BACKDROP_FAMILIES
    rng = random.Random(f"{seed}|{variant}")
    # The light kit leads with red; green is reserved for up-moves, so a
    # decorative backdrop never uses it.
    accent = RED
    # Paper tones, close together — this is the room Dennis stands in, and it
    # must stay quiet enough for dark ink to read on top of it.
    LIFT_HI, LIFT_MID, LIFT_LO = (250, 249, 246), (242, 242, 239), (233, 231, 225)
    img = Image.new("RGB", (W, H), LIFT_MID)
    d = ImageDraw.Draw(img, "RGBA")

    if fam == 0:  # diagonal gradient + a large, clearly visible accent glow
        top, bot = (LIFT_HI, LIFT_LO) if rng.random() < 0.5 else (LIFT_MID, LIFT_LO)
        for y in range(0, H, 2):
            d.line([(0, y), (W, y)], fill=_lerp(top, bot, y / H))
        glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        gx, gy = (rng.choice([int(W * 0.2), int(W * 0.8)]),
                  rng.choice([int(H * 0.25), int(H * 0.75)]))
        ImageDraw.Draw(glow).ellipse(
            [gx - W * 0.45, gy - W * 0.45, gx + W * 0.45, gy + W * 0.45],
            fill=(*accent, 80))
        img = Image.alpha_composite(img.convert("RGBA"),
                                    glow.filter(ImageFilter.GaussianBlur(140))).convert("RGB")
        d = ImageDraw.Draw(img, "RGBA")

    elif fam == 1:  # brand grid texture + a SUBTLE ticker watermark + hairline
        img.paste(LIFT_LO, (0, 0, W, H))
        gd = ImageDraw.Draw(img)
        step = max(H // rng.choice([12, 14, 18]), 40)
        for x in range(0, W, step):
            gd.line([x, 0, x, H], fill=LIFT_MID, width=1)
        for y in range(0, H, step):
            gd.line([0, y, W, y], fill=LIFT_MID, width=1)
        ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        od = ImageDraw.Draw(ov)
        if ticker:  # a faint texture, not the hero — seed varies scale/place
            wf = load_font(settings, SHANTELL, int(H * rng.choice([0.2, 0.26, 0.3])))
            probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
            tw = probe.textlength(f"${ticker}", font=wf)
            wx = rng.choice([int(W * 0.06), (W - tw) / 2, W - tw - int(W * 0.06)])
            wy = rng.choice([int(H * 0.16), (H - wf.size) / 2, int(H * 0.62)])
            od.text((wx, wy), f"${ticker}", font=wf, fill=(*FAINT, 90))
        hy = rng.choice([0.2, 0.5, 0.82])
        od.line([(0, int(H * hy)), (W, int(H * hy))], fill=(*accent, 120),
                width=max(int(H * 0.008), 3))
        img = Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")
        d = ImageDraw.Draw(img, "RGBA")

    elif fam == 2:  # a branded "signal" card — a decorative marker line chart
        d.rectangle([0, 0, W, H], fill=LIFT_LO)
        cx0, cy0, cx1, cy1 = int(W * 0.07), int(H * 0.1), int(W * 0.93), int(H * 0.9)
        d.rounded_rectangle([cx0, cy0, cx1, cy1], radius=int(W * 0.02),
                            fill=(*CARD2, 255), outline=(*BORDER2, 255), width=3)
        x0, x1 = int(W * 0.13), int(W * 0.87)
        y0, y1 = int(H * 0.26), int(H * 0.8)
        for k in range(4):
            gy = y0 + (y1 - y0) * k / 3
            d.line([(x0, gy), (x1, gy)], fill=(*GRID, 255), width=1)
        n = 10
        ys = [rng.uniform(y0, y1) for _ in range(n)]
        pts = [(x0 + (x1 - x0) * i / (n - 1), ys[i]) for i in range(n)]
        area = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(area).polygon(pts + [(x1, y1), (x0, y1)], fill=(*accent, 40))
        img = Image.alpha_composite(img.convert("RGBA"), area).convert("RGB")
        d = ImageDraw.Draw(img, "RGBA")
        d.line(pts, fill=(*accent, 255), width=max(int(W * 0.005), 3), joint="curve")
        d.ellipse([pts[-1][0] - 9, pts[-1][1] - 9, pts[-1][0] + 9, pts[-1][1] + 9],
                  fill=(*accent, 255))
        kf = load_font(settings, MONO_BOLD, int(H * 0.032))
        d.text((int(W * 0.13), int(H * 0.14)), (label or "the tape").upper(),
               font=kf, fill=(*MUTED2, 255))

    elif fam == 3:  # chapter word — big Shantell line, mono kicker, red dot
        for y in range(0, H, 2):
            d.line([(0, y), (W, y)], fill=_lerp(LIFT_MID, LIFT_LO, y / H))
        gd = ImageDraw.Draw(img)
        step = max(H // 14, 44)
        for x in range(0, W, step):
            gd.line([x, 0, x, H], fill=CARD_LINE, width=1)
        d = ImageDraw.Draw(img, "RGBA")
        kf = load_font(settings, MONO_BOLD, int(H * 0.034))
        bf = load_font(settings, SHANTELL, int(H * 0.12))
        word = label or "the deep dive"
        d.text((int(W * 0.1), int(H * 0.39)), ("section" if label else "dennis").upper(),
               font=kf, fill=(*MUTED2, 255))
        d.line([int(W * 0.1), int(H * 0.44), int(W * 0.17), int(H * 0.44)],
               fill=(*accent, 255), width=4)
        probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
        tw = probe.textlength(word, font=bf)
        d.text((int(W * 0.1), int(H * 0.49)), word, font=bf, fill=(*INK, 255))
        d.text((int(W * 0.1) + tw, int(H * 0.49)), ".", font=bf, fill=(*RED, 255))

    else:  # fam == 4: dot field + a bold diagonal accent band
        d.rectangle([0, 0, W, H], fill=LIFT_LO)
        step = max(H // 18, 40)
        for yy in range(step, H, step):
            for xx in range(step, W, step):
                d.ellipse([xx - 3, yy - 3, xx + 3, yy + 3], fill=(*BORDER, 255))
        band = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(band).line([(0, int(H * 0.78)), (W, int(H * 0.32))],
                                  fill=(*accent, 90), width=max(int(H * 0.05), 18))
        img = Image.alpha_composite(img.convert("RGBA"),
                                    band.filter(ImageFilter.GaussianBlur(6))).convert("RGB")
        d = ImageDraw.Draw(img, "RGBA")
        d.line([(0, int(H * 0.78)), (W, int(H * 0.32))], fill=(*accent, 220),
               width=max(int(H * 0.006), 3))

    # a gentle vignette gives the room some depth. On paper it only settles
    # the edges a little — crushing them would put a dark ring behind a host
    # drawn in dark ink.
    vig = Image.new("L", (W, H), 0)
    ImageDraw.Draw(vig).ellipse([-int(W * 0.25), -int(H * 0.25),
                                 int(W * 1.25), int(H * 1.25)], fill=255)
    vig = vig.filter(ImageFilter.GaussianBlur(int(W * 0.05)))
    settled = ImageEnhance.Brightness(img).enhance(0.96)
    return Image.composite(img, settled, vig)


# --------------------------------------------------------------------------
# Frame sequences -> alpha clips.
# --------------------------------------------------------------------------


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


def doodle_clip(
    src: Path,
    out_path: Path,
    *,
    display_w: int,
    duration_s: float,
    fps: int = 30,
    seed: str = "doodle",
) -> tuple[Path, tuple[int, int]]:
    """Resize a doodle PNG to display width, give it the hand-drawn boil,
    and encode an alpha .mov. Returns (clip_path, (w, h)) of the frames so
    the caller can position it."""
    from pipeline.doodles import wobble_frames

    img = Image.open(src).convert("RGBA")
    if img.width != display_w:
        ratio = display_w / img.width
        img = img.resize((display_w, max(int(img.height * ratio), 1)), Image.LANCZOS)
    frames = wobble_frames(img, duration_s=duration_s, fps=fps, seed=seed)
    frames_to_alpha_clip(frames, fps, out_path)
    return out_path, frames[0].size


def typing_frames(
    settings: Settings,
    text: str,
    *,
    font_size: int = 46,
    fill=INK,
    fps: int = 30,
    type_seconds: float = 0.9,
    cursor: bool = True,
) -> list[Image.Image]:
    """Monospace type-on reveal of one line."""
    font = load_font(settings, MONO_BOLD, font_size)
    probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    full_w = int(probe.textlength(text, font=font)) + 26
    ascent, descent = font.getmetrics()
    h = ascent + descent + 10
    n_frames = max(int(type_seconds * fps), 2)
    frames: list[Image.Image] = []
    for k in range(n_frames + 1):
        shown = text[: max(1, round(len(text) * k / n_frames))] if k else ""
        img = Image.new("RGBA", (full_w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.text((4, 4), shown, font=font, fill=(*fill, 255))
        if cursor and k < n_frames:
            cx = d.textlength(shown, font=font) + 6
            d.rectangle([cx, 6, cx + font_size * 0.55, h - 8], fill=(*fill, 200))
        frames.append(img)
    return frames


# --------------------------------------------------------------------------
# Headline overlay (the "why" treatment ON the chart).
# --------------------------------------------------------------------------


def headline_card(settings: Settings, text: str, *, meaning: str = "",
                  width: int, font_size: int = 40) -> Image.Image:
    """Driver-headline card (the WHY beat): a red left border, the quoted
    headline in Space Grotesk, and the red hand-drawn "gloss" line under it
    (Shantell Sans) saying what it actually means."""
    font = load_font(settings, GROTESK_BOLD, font_size)
    gloss_font = load_font(settings, SHANTELL, int(font_size * 0.82))
    probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    pad = int(font_size * 0.55)
    bar_w = int(font_size * 0.30)
    inner = width - 2 * pad - bar_w
    quoted = text if text.strip().startswith('"') else f'"{text}"'
    lines = _wrap(probe, quoted, font, inner)
    lh = int(font_size * 1.24)
    gloss_lines = _wrap(probe, meaning, gloss_font, inner) if meaning else []
    glh = int(gloss_font.size * 1.2)
    h = 2 * pad + lh * len(lines) + (int(pad * 0.6) + glh * len(gloss_lines)
                                     if gloss_lines else 0)
    img = Image.new("RGBA", (width, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, width - 1, h - 1], radius=10, fill=(*CARD, 244),
                        outline=(*CARD_LINE, 255), width=1)
    d.rounded_rectangle([0, 0, bar_w, h - 1], radius=4, fill=(*RED, 255))
    y = pad
    for line in lines:
        d.text((bar_w + pad, y), line, font=font, fill=(*INK, 255))
        y += lh
    y += int(pad * 0.6)
    for line in gloss_lines:
        d.text((bar_w + pad, y), line, font=gloss_font, fill=(*RED, 255))
        y += glh
    return img


# --------------------------------------------------------------------------
# The numbers sheet — a clean statement card with mini trend bars (§4).
# --------------------------------------------------------------------------

_NUM_RE = re.compile(r"-?\d+(?:[.,]\d+)?")


def parse_row_values(values: list[str]) -> list[float] | None:
    """Best-effort numeric parse of display strings for the trend bars."""
    out: list[float] = []
    for v in values:
        m = _NUM_RE.search(v.replace(",", ""))
        if not m:
            return None
        x = float(m.group(0))
        if "-" in v.split(m.group(0))[0] or v.strip().startswith("("):
            x = -abs(x)
        low = v.lower()
        if "b" in low.split(m.group(0))[-1][:2]:
            x *= 1000  # bars only need relative scale vs M
        out.append(x)
    return out


# The sheet's metrics are authored against a 1000px-wide card — the width the
# SHORT's design layout asks for at full resolution.
SHEET_DESIGN_W = 1000


def sheet_layout(settings: Settings, n_rows: int, *, width: int,
                 row_h: int | None = None, title_h: int | None = None,
                 years_h: int | None = None, pad: int | None = None) -> dict:
    """Pixel geometry shared by the base card, row clips and zoom pops.

    Every metric scales with the card's width. They used to be fixed pixel
    counts, so a card rendered at half size kept full-size rows and a
    full-size title — the same sheet, but proportioned differently. That makes
    a reduced-resolution render stop being a miniature of the real one, which
    matters most for the golden frames, whose whole job is to be evidence
    about what ships.
    """
    # The rows are generous because this is a PHONE. The gut check is the most
    # read thing in the short and it rendered as a thin landscape strip —
    # 1000x570 on a 1080x1920 frame, 27% of it — with figures small enough to
    # squint at. The sheet is a generated raster, so unlike the 16:9 card
    # artwork its proportions are a choice rather than arithmetic.
    s = max(width, 1) / SHEET_DESIGN_W
    row_h = row_h if row_h is not None else max(int(176 * s), 24)
    title_h = title_h if title_h is not None else max(int(116 * s), 20)
    years_h = years_h if years_h is not None else max(int(72 * s), 14)
    pad = pad if pad is not None else max(int(30 * s), 6)
    return {
        "width": width,
        "pad": pad,
        "title_h": title_h,
        "years_h": years_h,
        "row_h": row_h,
        "height": title_h + years_h + n_rows * row_h + 2 * pad,
        "rows_y0": pad + title_h + years_h,
        "label_w": int(width * 0.30),
        "bars_w": int(width * 0.16),
    }


def numbers_sheet_base(settings: Settings, n_rows: int, years: list[str], *,
                       width: int, title: str = "THE GUT CHECK") -> tuple[Image.Image, dict]:
    """The empty statement card: title, year headers, ruled row slots.
    Rows type on later as separate overlays positioned by the layout."""
    ly = sheet_layout(settings, n_rows, width=width)
    W, H = width, ly["height"]
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, W - 1, H - 1], radius=22, fill=(*PANEL, 246),
                        outline=(*PANEL_LINE, 255), width=2)

    title_font = load_font(settings, GROTESK_BOLD, int(ly["title_h"] * 0.46))
    d.text((ly["pad"], ly["pad"] + 4), title, font=title_font, fill=(*INK, 255))
    sub_font = load_font(settings, MONO, int(ly["title_h"] * 0.22))
    d.text((ly["pad"], ly["pad"] + title_font.size + 12),
           "from the filing · direction, not a snapshot", font=sub_font,
           fill=(*MUTED, 255))

    # Year headers over the value columns, fitted to the column they sit in.
    # The row VALUES have always shrunk to fit; the headers did not, so a
    # narrow card printed "2021 2022 2023" on top of itself while the numbers
    # under them stayed legible.
    if years:
        x0 = ly["label_w"]
        cols_w = W - x0 - ly["bars_w"] - ly["pad"]
        cell_w = cols_w / len(years)
        ysize = max(int(ly["years_h"] * 0.44), 1)
        yr_font = load_font(settings, MONO_BOLD, ysize)
        widest = max((str(y) for y in years), key=len)
        while ysize > 7 and d.textlength(widest, font=yr_font) > cell_w - 4:
            ysize -= 1
            yr_font = load_font(settings, MONO_BOLD, ysize)
        for j, y in enumerate(years):
            cx = x0 + cols_w * (j + 0.5) / len(years)
            d.text((cx - d.textlength(str(y), font=yr_font) / 2,
                    ly["pad"] + ly["title_h"] + 6),
                   str(y), font=yr_font, fill=(*MUTED, 255))

    for i in range(n_rows):  # recessive rules between row slots
        ry = ly["rows_y0"] + (i + 1) * ly["row_h"]
        if i < n_rows - 1:
            d.line([ly["pad"], ry, W - ly["pad"], ry], fill=(*PANEL_LINE, 200), width=1)
    return img, ly


def number_row_frames(
    settings: Settings,
    label: str,
    values: list[str],
    layout: dict,
    *,
    fps: int = 30,
    type_seconds: float = 0.8,
) -> list[Image.Image]:
    """One sheet row typing on: label, then the year values landing cell by
    cell (oldest -> newest), then the mini trend bars growing."""
    W = layout["width"]
    H = layout["row_h"]
    label_w = layout["label_w"]
    bars_w = layout["bars_w"]
    pad = layout["pad"]
    cols_w = W - label_w - bars_w - pad

    # fit fonts to their columns so long labels / wide values never collide
    probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    lsize = int(H * 0.34)
    label_font = load_font(settings, DISPLAY_BOLD, lsize)
    while lsize > 14 and probe.textlength(label, font=label_font) > label_w - pad - 8:
        lsize -= 2
        label_font = load_font(settings, DISPLAY_BOLD, lsize)
    cell_w = cols_w / max(len(values), 1)
    vsize = int(H * 0.30)
    val_font = load_font(settings, MONO_BOLD, vsize)
    widest = max(values, key=len)
    while vsize > 12 and probe.textlength(widest, font=val_font) > cell_w - 8:
        vsize -= 2
        val_font = load_font(settings, MONO_BOLD, vsize)
    numeric = parse_row_values(values)

    def render(progress: float) -> Image.Image:
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        # phase 1 (0..0.25): the label types
        label_p = min(progress / 0.25, 1.0)
        shown = label[: max(1, round(len(label) * label_p))] if label_p > 0 else ""
        d.text((pad, (H - label_font.size) / 2), shown, font=label_font,
               fill=(*MUTED2, 255))
        # phase 2 (0.25..0.85): values land cell by cell
        n = len(values)
        vals_p = max(0.0, min((progress - 0.25) / 0.60, 1.0))
        visible = int(math.ceil(vals_p * n))
        for j in range(visible):
            v = values[j]
            cx = label_w + cols_w * (j + 0.5) / n
            color = INK
            if numeric is not None and numeric[j] < 0:
                color = RED
            d.text((cx - d.textlength(v, font=val_font) / 2,
                    (H - val_font.size) / 2), v, font=val_font, fill=(*color, 255))
        # phase 3 (0.85..1): mini trend bars grow. Neutral single hue —
        # direction is a fact, not a judgement (rising share count is not
        # good news); only genuinely negative values go red.
        if numeric is not None and len(numeric) >= 2:
            bars_p = max(0.0, min((progress - 0.85) / 0.15, 1.0))
            bx0 = W - bars_w - pad + 6
            bw = (bars_w - 12) / len(numeric)
            lo, hi = min(numeric + [0.0]), max(numeric + [0.0])
            span = (hi - lo) or 1.0
            zero_y = H * 0.78 - (0.0 - lo) / span * H * 0.56
            for j, x in enumerate(numeric):
                vy = H * 0.78 - (x - lo) / span * H * 0.56
                top, bot = (vy, zero_y) if x >= 0 else (zero_y, vy)
                bot = top + max((bot - top) * bars_p, 2)
                color = (72, 72, 84) if x >= 0 else RED  # neutral trend bar; red only if negative
                d.rounded_rectangle(
                    [bx0 + j * bw + 1, top, bx0 + (j + 1) * bw - 2, bot],
                    radius=2, fill=(*color, 220),
                )
        return img

    n_frames = max(int(type_seconds * fps), 4)
    return [render(k / n_frames) for k in range(n_frames + 1)]


def number_row_image(settings: Settings, label: str, values: list[str],
                     layout: dict) -> Image.Image:
    """The row's final frame (used for the zoom-punch pop)."""
    return number_row_frames(settings, label, values, layout, fps=2,
                             type_seconds=1.0)[-1]


# --------------------------------------------------------------------------
# Hand-drawn annotations, zoom-punch, flash stinger.
# --------------------------------------------------------------------------


def scribble_frames(
    w: int,
    h: int,
    *,
    style: str = "circle",
    color=RED,
    fps: int = 30,
    draw_seconds: float = 0.4,
    stroke: int | None = None,
    seed: str = "scribble",
) -> list[Image.Image]:
    """A marker-style mark (circle / underline / arrow) drawing itself on,
    with hand-drawn jitter — the red scrawl the kit uses over the chart or
    a numbers row. Composited on the top layer."""
    rng = random.Random(seed)
    stroke = stroke or max(int(min(w, h) * 0.06), 5)
    n = max(int(draw_seconds * fps), 4)
    cx, cy = w / 2, h / 2
    rx, ry = w / 2 - stroke, h / 2 - stroke
    jitter = [(rng.uniform(-2.5, 2.5), rng.uniform(-2.5, 2.5)) for _ in range(64)]

    def point(theta: float) -> tuple[float, float]:
        j = jitter[int((theta % (2 * math.pi)) / (2 * math.pi) * 63)]
        return (cx + rx * math.cos(theta) + j[0], cy + ry * math.sin(theta) + j[1])

    # an arrow flies in from the top-left corner toward the center
    tail = (stroke * 1.5, stroke * 1.5)
    tip = (cx, cy)

    frames: list[Image.Image] = []
    for k in range(n + 1):
        p = k / n
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        if style == "underline":
            x1 = stroke + (w - 2 * stroke) * p
            wave = [(x, h * 0.6 + math.sin(x / 14) * h * 0.12)
                    for x in range(stroke, int(x1), 6)]
            if len(wave) >= 2:
                d.line(wave, fill=(*color, 235), width=stroke, joint="curve")
        elif style == "arrow":
            hx = tail[0] + (tip[0] - tail[0]) * p
            hy = tail[1] + (tip[1] - tail[1]) * p
            shaft = [(tail[0] + rng.uniform(-2, 2), tail[1] + rng.uniform(-2, 2)),
                     (hx, hy)]
            d.line(shaft, fill=(*color, 235), width=stroke, joint="curve")
            if p > 0.85:  # the arrowhead lands last
                ah = stroke * 3
                d.line([(tip[0] - ah, tip[1] - ah * 0.3), (tip[0], tip[1])],
                       fill=(*color, 235), width=stroke, joint="curve")
                d.line([(tip[0] - ah * 0.3, tip[1] - ah), (tip[0], tip[1])],
                       fill=(*color, 235), width=stroke, joint="curve")
        else:  # circle
            start = -math.pi / 2
            # 1.15 turns so the ellipse visibly closes like a real scribble
            theta_end = start + 2 * math.pi * 1.15 * p
            pts = [point(start + (theta_end - start) * i / 48) for i in range(49)]
            if len(pts) >= 2 and p > 0:
                d.line(pts, fill=(*color, 235), width=stroke, joint="curve")
        frames.append(img)
    return frames


def scribble_callout_frames(
    settings: Settings,
    w: int,
    h: int,
    *,
    style: str,
    target: str,
    fps: int = 30,
    draw_seconds: float = 0.45,
    hold_seconds: float = 1.2,
    color=RED,
    seed: str = "callout",
) -> list[Image.Image]:
    """A scribble mark drawing itself on, plus the target text as a small
    hand-labelled callout beneath it — the LONG/inline `[SCRIBBLE: … -> target]`
    treatment that rides over whatever segment is on screen."""
    mark_h = int(h * 0.62)
    mark = scribble_frames(w, mark_h, style=style, color=color, fps=fps,
                           draw_seconds=draw_seconds, seed=seed)
    font = load_font(settings, MONO_BOLD, max(int(h * 0.12), 16))
    probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    label = target if probe.textlength(target, font=font) < w - 20 else target[:24]
    lw = probe.textlength(label, font=font)

    frames: list[Image.Image] = []
    total = len(mark) + max(int(hold_seconds * fps), 1)
    for k in range(total):
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        img.alpha_composite(mark[min(k, len(mark) - 1)], (0, 0))
        if k >= len(mark) - 2:  # the label appears as the mark completes
            d = ImageDraw.Draw(img)
            lx = (w - lw) / 2
            ly = mark_h + int(h * 0.02)
            d.text((lx, ly), label, font=font, fill=(*color, 255),
                   stroke_width=3, stroke_fill=(8, 9, 11, 230))
        frames.append(img)
    return frames


def zoom_pop_frames(image: Image.Image, *, fps: int = 30,
                    pop_seconds: float = 0.5, max_scale: float = 1.32) -> list[Image.Image]:
    """Zoom-punch on a key number: the row pops out, holds, settles."""
    n = max(int(pop_seconds * fps), 4)
    cw = int(image.width * max_scale) + 8
    ch = int(image.height * max_scale) + 8
    frames: list[Image.Image] = []
    for k in range(n + 1):
        p = k / n
        # fast out, brief hold, ease back
        if p < 0.3:
            s = 1.0 + (max_scale - 1.0) * (p / 0.3)
        elif p < 0.7:
            s = max_scale
        else:
            s = max_scale - (max_scale - 1.0) * ((p - 0.7) / 0.3)
        img = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        scaled = image.resize((max(int(image.width * s), 1),
                               max(int(image.height * s), 1)), Image.BICUBIC)
        img.alpha_composite(scaled, ((cw - scaled.width) // 2,
                                     (ch - scaled.height) // 2))
        frames.append(img)
    return frames


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


def _pages(words: list[WordTimestamp], max_words: int, max_chars: int, max_gap: float):
    page: list[WordTimestamp] = []
    for w in words:
        if page and (
            len(page) >= max_words
            or sum(len(x.word) + 1 for x in page) + len(w.word) > max_chars
            or w.start - page[-1].end > max_gap
        ):
            yield page
            page = []
        page.append(w)
    if page:
        yield page


def build_karaoke_ass(
    words: list[WordTimestamp],
    *,
    play_res: tuple[int, int],
    font_size: int = 66,
    margin_v: int = 250,
    max_words: int = 3,
    max_chars: int = 18,
    accent_rgb: tuple[int, int, int] = GOLD,
    duration: float | None = None,
    box: bool = False,
    margin_h: int = 60,
) -> str:
    """Word-synced karaoke: unspoken text white, spoken fills accent.

    `box=True` switches to an opaque, text-fitted caption box (ASS
    BorderStyle=3): each line gets its own dark chip sized to its content,
    so a LONG caption can never clip off-frame or stack into the furniture.
    The default (outline) style is byte-for-byte the SHORT's captions.
    """
    W, H = play_res

    def bgr(c):  # ASS colours are &HAABBGGRR
        r, g, b = c
        return f"&H00{b:02X}{g:02X}{r:02X}"

    # BorderStyle, Outline (box padding / stroke), Shadow, and the outline/back
    # colours differ between the outline caption (SHORT) and the fitted box (LONG)
    # On the light kit the caption band is paper, not a dark slab: a
    # near-opaque #faf9f6 box for the LONG, and a paper outline for the SHORT
    # so text stays legible over photography without punching a hole in the
    # frame. (&HAABBGGRR — AA is 00 opaque, FF transparent.)
    if box:
        border_style, outline, shadow = 3, 12, 0
        outline_c, back_c = "&H14F6F9FA", "&H14F6F9FA"
    else:
        border_style, outline, shadow = 1, 4, 2
        outline_c, back_c = "&H00EFF2F2", "&H78F6F9FA"

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caps,Space Grotesk,{font_size},{bgr(accent_rgb)},&H00FFFFFF,{outline_c},{back_c},-1,0,0,0,100,100,0,0,{border_style},{outline},{shadow},2,{margin_h},{margin_h},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events: list[str] = []
    pages = list(_pages(words, max_words, max_chars, 0.9))
    for i, page in enumerate(pages):
        start = page[0].start
        if i + 1 < len(pages):
            end = max(pages[i + 1][0].start, page[-1].end)
        else:
            end = page[-1].end + 0.8
            if duration is not None:
                end = min(end, duration)
        parts = []
        for j, w in enumerate(page):
            if j + 1 < len(page):
                span = page[j + 1].start - w.start
            else:
                span = w.end - w.start
            parts.append(f"{{\\k{max(int(round(span * 100)), 1)}}}{w.word}")
        text = " ".join(parts)
        events.append(
            f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Caps,,0,0,0,,{text}"
        )
    return header + "\n".join(events) + "\n"


# --------------------------------------------------------------------------
# Phrase captions (the SHORT's caption track).
# --------------------------------------------------------------------------

# Where a caption may break. A karaoke page that fills up mid-clause splits
# "revenue went four hundred / million to four ninety six", which reads as two
# unrelated fragments; breaking after the punctuation keeps a phrase whole.
_PHRASE_END = re.compile(r"[.!?…]$|[,;:—–]$")

# Function words a line must never end on: a caption ending "of" or "the"
# leaves the eye hanging for a frame and a half.
_NEVER_LAST = {
    "a", "an", "the", "and", "or", "but", "of", "to", "in", "on", "at", "for",
    "from", "with", "by", "as", "is", "was", "are", "were", "that", "which",
    "than", "into", "over", "its", "it's", "their", "your", "our", "his",
}


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
    play_res: tuple[int, int],
    font_size: int = 62,
    margin_v: int = 300,
    margin_h: int = 70,
    max_words: int = 6,
    max_chars: int = 30,
    duration: float | None = None,
    punch: bool = True,
) -> str:
    """The SHORT's captions: dark ink on a paper chip, phrase by phrase.

    Not karaoke. The word-by-word red fill was doing two things at once —
    colouring text the same red the kit uses for a down-move, and drawing the
    eye along a line that had already been split mid-clause. This is one
    legible phrase at a time, in the same ink as everything else on the frame.

    `punch` gives each line a 60ms scale-up on entry. It is the caption half of
    the motion layer: enough to register as a cut, not enough to bounce.
    """
    W, H = play_res

    def bgr(c):  # ASS colours are &HAABBGGRR
        r, g, b = c
        return f"&H00{b:02X}{g:02X}{r:02X}"

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caps,Shantell Sans,{font_size},{bgr(INK)},{bgr(INK)},&H0AF6F9FA,&H0AF6F9FA,-1,0,0,0,100,100,0,0,3,14,0,2,{margin_h},{margin_h},{margin_v},1

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


def _ease_out(t: float) -> float:
    """Fast, then settling. The house easing for anything that lands."""
    return 1.0 - (1.0 - min(max(t, 0.0), 1.0)) ** 3


def count_up_frames(
    settings: Settings,
    value: str,
    *,
    width: int,
    height: int,
    fps: int = 30,
    seconds: float = 0.8,
    font_name: str = MONO_BOLD,
    fill=INK,
    align: str = "center",
) -> list[Image.Image]:
    """A figure rolling up to its spoken value.

    The digits count; the prefix, suffix and sign do not — "$4.1B" rolls
    "0.0" to "4.1" and keeps the dollar and the B, because a currency symbol
    flickering through the alphabet is noise, not motion. A value with no
    digits at all is simply held, so this is safe to call on anything.
    """
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


def draw_on_frames(
    image: Image.Image,
    *,
    fps: int = 30,
    seconds: float = 0.9,
    direction: str = "left",
) -> list[Image.Image]:
    """A finished graphic revealed as if it were being drawn.

    A wipe rather than a re-render: the chart, the bars and the table are
    already correct pixels, and revealing them along the reading direction is
    indistinguishable from watching the line drawn — without a second code
    path that could disagree with the still.
    """
    frames: list[Image.Image] = []
    W, H = image.size
    n = max(int(seconds * fps), 2)
    for k in range(n + 1):
        p = _ease_out(k / n)
        frame = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        if direction == "up":
            box = (0, H - max(int(H * p), 1), W, H)
        elif direction == "down":
            box = (0, 0, W, max(int(H * p), 1))
        else:
            box = (0, 0, max(int(W * p), 1), H)
        frame.paste(image.crop(box), (box[0], box[1]))
        frames.append(frame)
    return frames


def stamp_slam_frames(
    image: Image.Image,
    *,
    fps: int = 30,
    seconds: float = 0.45,
    from_scale: float = 1.9,
) -> list[Image.Image]:
    """A card slammed down onto the frame: oversized, dropping to size, still.

    Ends on the untouched image, so the beat that follows can hold this exact
    frame — the slam is an entrance, not a state.
    """
    frames: list[Image.Image] = []
    W, H = image.size
    n = max(int(seconds * fps), 2)
    for k in range(n + 1):
        p = _ease_out(k / n)
        scale = from_scale + (1.0 - from_scale) * p
        sw, sh = max(int(W * scale), 1), max(int(H * scale), 1)
        scaled = image.resize((sw, sh), Image.LANCZOS)
        frame = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        frame.paste(scaled, (int((W - sw) / 2), int((H - sh) / 2)), scaled)
        if k == n:
            frame = image.copy()
        frames.append(frame)
    return frames


def slide_in_frames(
    image: Image.Image,
    *,
    fps: int = 30,
    seconds: float = 0.4,
    direction: str = "up",
    travel: float = 0.14,
) -> list[Image.Image]:
    """A card arriving from just off its resting position."""
    frames: list[Image.Image] = []
    W, H = image.size
    n = max(int(seconds * fps), 2)
    span = int((H if direction in ("up", "down") else W) * travel)
    for k in range(n + 1):
        p = _ease_out(k / n)
        off = int(span * (1.0 - p))
        dx, dy = 0, 0
        if direction == "up":
            dy = off
        elif direction == "down":
            dy = -off
        elif direction == "left":
            dx = off
        else:
            dx = -off
        frame = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        frame.paste(image, (dx, dy), image)
        frames.append(frame)
    return frames
