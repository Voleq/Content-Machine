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

MONO = "DejaVuSansMono.ttf"
MONO_BOLD = "DejaVuSansMono-Bold.ttf"
DISPLAY_BOLD = "DejaVuSans-Bold.ttf"

RED = (224, 82, 82)
GREEN = (63, 185, 104)
INK = (232, 234, 240)
MUTED = (154, 163, 178)
PANEL = (18, 21, 28)
PANEL_LINE = (38, 43, 54)
GOLD = (255, 205, 60)


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
    """The intro/outro bug: brand name + the sampled hook-bank opener."""
    name_font = load_font(settings, DISPLAY_BOLD, font_size)
    line_font = load_font(settings, MONO_BOLD, int(font_size * 0.72))
    probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    name = settings.brand_name
    nw = probe.textlength(name, font=name_font)
    lw = probe.textlength(opener, font=line_font)
    h = name_font.size + line_font.size + 26
    img = Image.new("RGBA", (width, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.text(((width - nw) / 2, 0), name, font=name_font, fill=(*GOLD, 255),
           stroke_width=2, stroke_fill=(0, 0, 0, 200))
    d.text(((width - lw) / 2, name_font.size + 10), opener, font=line_font,
           fill=(*INK, 235), stroke_width=2, stroke_fill=(0, 0, 0, 200))
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


def headline_card(settings: Settings, text: str, *, width: int,
                  font_size: int = 40) -> Image.Image:
    """News-strip card: gold kicker bar + headline text on a dark chip."""
    font = load_font(settings, DISPLAY_BOLD, font_size)
    probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    pad = int(font_size * 0.55)
    bar_w = int(font_size * 0.30)
    lines = _wrap(probe, text, font, width - 2 * pad - bar_w)
    lh = int(font_size * 1.28)
    h = 2 * pad + lh * len(lines)
    img = Image.new("RGBA", (width, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, width - 1, h - 1], radius=12, fill=(12, 14, 19, 242))
    d.rectangle([0, 6, bar_w, h - 7], fill=(*GOLD, 255))
    for i, line in enumerate(lines):
        d.text((bar_w + pad, pad + i * lh), line, font=font, fill=(*INK, 255))
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

    title_font = load_font(settings, DISPLAY_BOLD, int(ly["title_h"] * 0.46))
    d.text((ly["pad"], ly["pad"] + 4), title, font=title_font, fill=(*GOLD, 255))
    sub_font = load_font(settings, MONO, int(ly["title_h"] * 0.22))
    d.text((ly["pad"], ly["pad"] + title_font.size + 12),
           "from the 10-K · five years", font=sub_font, fill=(*MUTED, 255))

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
               fill=(*INK, 255))
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
                color = GOLD if x >= 0 else RED
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
    color=GOLD,
    fps: int = 30,
    draw_seconds: float = 0.4,
    stroke: int | None = None,
    seed: str = "scribble",
) -> list[Image.Image]:
    """A marker-style mark (circle / underline / arrow) drawing itself on,
    with hand-drawn jitter. Composited over the chart or a numbers row."""
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
    color=GOLD,
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
Style: Caps,DejaVu Sans,{font_size},{bgr(accent_rgb)},&H00FFFFFF,&H00101010,&H96000000,-1,0,0,0,100,100,0,0,1,4,2,2,60,60,{margin_v},1

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
