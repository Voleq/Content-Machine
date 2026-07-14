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

from PIL import Image, ImageDraw, ImageFont

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

# Palette — the exact tokens from the Dennis visual-identity kits.
BG = (10, 10, 11)          # #0a0a0b  page
BG_CARD = (12, 12, 14)     # #0c0c0e  the tall beat card
BG_MARK = (5, 5, 6)        # #050506  marker chart black
CARD = (19, 19, 25)        # #131319  inner card
CARD2 = (25, 25, 32)       # #191920
CARD_LINE = (35, 35, 41)   # #232329  inner card border
BORDER = (35, 35, 38)      # #232326  card border
BORDER2 = (42, 42, 52)     # #2a2a34  chip border
INK = (242, 242, 239)      # #f2f2ef  text
MUTED = (107, 107, 112)    # #6b6b70  muted text
MUTED2 = (201, 201, 204)   # #c9c9cc  secondary text
FAINT = (74, 74, 79)       # #4a4a4f  faintest label
GREEN = (47, 213, 118)     # #2fd576  up / signal green
RED = (255, 82, 71)        # #ff5247  down / marker red
GRID = (30, 30, 36)        # #1e1e24  chart gridlines
ACCENT = GREEN             # the brand accent (the kit uses no gold)
GOLD = GREEN               # back-compat alias — accent is the signal green
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
    fg=(255, 255, 255, 255),
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
    fill=(255, 255, 255, 255),
    stroke_width: int = 0,
    stroke_fill=(0, 0, 0, 255),
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
    d.text(((width - nw) / 2 - 6, 0), name, font=name_font, fill=(*INK, 255),
           stroke_width=2, stroke_fill=(0, 0, 0, 200))
    d.text(((width - nw) / 2 - 6 + nw, 0), ".", font=name_font, fill=(*RED, 255),
           stroke_width=2, stroke_fill=(0, 0, 0, 200))
    d.text(((width - lw) / 2, name_font.size + 12), opener, font=line_font,
           fill=(*MUTED, 235), stroke_width=2, stroke_fill=(0, 0, 0, 200))
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
    d.text((padx, pady - 2), label, font=font, fill=(10, 10, 11, 255))
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
    a mono kicker and the red terminal dot — the LONG section divider."""
    img = Image.new("RGBA", (width, height), (*BG, 235))
    d = ImageDraw.Draw(img)
    kick = load_font(settings, MONO_BOLD, max(int(height * 0.045), 14))
    big = load_font(settings, SHANTELL, max(int(height * 0.16), 28))
    d.text((int(width * 0.1), int(height * 0.36)), number.upper(), font=kick,
           fill=(*MUTED, 255))
    probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    tw = probe.textlength(title, font=big)
    d.text((int(width * 0.1), int(height * 0.44)), title, font=big, fill=(*INK, 255))
    d.text((int(width * 0.1) + tw, int(height * 0.44)), ".", font=big, fill=(*RED, 255))
    return img


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


def sheet_layout(settings: Settings, n_rows: int, *, width: int,
                 row_h: int = 118, title_h: int = 96, years_h: int = 64,
                 pad: int = 28) -> dict:
    """Pixel geometry shared by the base card, row clips and zoom pops."""
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

    # year headers over the value columns
    if years:
        yr_font = load_font(settings, MONO_BOLD, int(ly["years_h"] * 0.44))
        x0 = ly["label_w"]
        cols_w = W - x0 - ly["bars_w"] - ly["pad"]
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
) -> str:
    """Word-synced karaoke: unspoken text white, spoken fills accent."""
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
Style: Caps,Space Grotesk,{font_size},{bgr(accent_rgb)},&H00FFFFFF,&H000A0A0A,&H96000000,-1,0,0,0,100,100,0,0,1,4,2,2,60,60,{margin_v},1

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
