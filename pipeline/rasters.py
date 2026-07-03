"""Pillow raster + animation-frame generation, and ASS karaoke captions.

All text is rendered with Pillow (never ImageMagick / MoviePy TextClip §3).
Animated moments (whip-pan, stamp impact, typewriter, highlight sweep) are
generated here as short RGBA frame sequences, encoded once by ffmpeg into
small alpha .mov clips, and composited by the FFmpeg filtergraph — Python
never renders per-frame at video resolution for the full timeline.
"""

from __future__ import annotations

import math
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from config import Settings
from pipeline.models import WordTimestamp
from pipeline.render_common import run_ffmpeg

MONO = "DejaVuSansMono.ttf"
MONO_BOLD = "DejaVuSansMono-Bold.ttf"
DISPLAY_BOLD = "DejaVuSans-Bold.ttf"

RED = (203, 44, 52)
GREEN = (36, 158, 82)
INK = (42, 34, 24)
PAPER = (242, 235, 218)
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
    bg=(12, 10, 9, 216),
    accent=None,
    pad: int = 36,
    align: str = "center",
    radius: int = 26,
) -> Image.Image:
    """Auto-height rounded panel with wrapped text (hook / CTA cards)."""
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
    """Monospace typewriter reveal of one data-block line."""
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


def highlight_sweep_frames(
    width: int,
    height: int,
    color: str,
    *,
    fps: int = 30,
    sweep_seconds: float = 0.35,
    alpha: int = 110,
) -> list[Image.Image]:
    """Semi-transparent marker rect expanding left->right over a data row."""
    rgb = RED if color == "red" else GREEN
    n = max(int(sweep_seconds * fps), 2)
    frames = []
    for k in range(n + 1):
        prog = (k / n) ** 0.8
        img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        w = max(int(width * prog), 8)
        d.rounded_rectangle([0, 0, w, height - 1], radius=14, fill=(*rgb, alpha))
        frames.append(img)
    return frames


def stamp_drop_frames(
    stamp: Image.Image,
    *,
    fps: int = 30,
    drop_seconds: float = 0.3,
    final_width: int = 880,
) -> list[Image.Image]:
    """Impact drop: 200% -> 100% scale with a settle wobble (§7.1.6)."""
    ratio = final_width / stamp.width
    final = stamp.resize((final_width, int(stamp.height * ratio)), Image.LANCZOS)
    cw, ch = int(final_width * 1.25), int(final.height * 1.25)
    n = max(int(drop_seconds * fps), 3)
    frames = []
    for k in range(n + 1):
        p = k / n
        scale = 2.0 - (2.0 - 1.0) * (1 - (1 - p) ** 3)  # ease-out cubic
        if k == n:
            scale = 1.0
        rot = (1 - p) * 6.0
        alpha = min(1.0, 0.25 + p * 1.2)
        img = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        s = final.rotate(rot, expand=True, resample=Image.BICUBIC)
        sw, sh = int(s.width * scale), int(s.height * scale)
        s = s.resize((max(sw, 1), max(sh, 1)), Image.BICUBIC)
        if alpha < 1.0:
            a = s.getchannel("A").point(lambda v: int(v * alpha))
            s.putalpha(a)
        img.alpha_composite(s, ((cw - s.width) // 2, (ch - s.height) // 2))
        frames.append(img)
    # settle bounce
    for scale in (1.045, 1.0):
        img = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        s = final.resize((int(final.width * scale), int(final.height * scale)), Image.BICUBIC)
        img.alpha_composite(s, ((cw - s.width) // 2, (ch - s.height) // 2))
        frames.append(img)
    return frames


def whip_pan_frames(
    closed_folder: Image.Image,
    open_folder: Image.Image,
    canvas: tuple[int, int],
    positions: tuple[tuple[int, int], tuple[int, int]],
    *,
    fps: int = 30,
    duration: float = 0.45,
) -> list[Image.Image]:
    """Closed folder whips off-left, open folder whips in from the right,
    ending exactly at the open folder's static resting position."""
    W, H = canvas
    (cx, cy), (ox, oy) = positions
    n = max(int(duration * fps), 4)
    frames = []
    for k in range(n + 1):
        p = k / n
        ease = 1 - (1 - p) ** 2.2
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        # closed folder exits left
        x_closed = int(cx - ease * (cx + closed_folder.width + 80))
        blur = int(ease * 14)
        cf = closed_folder.filter(ImageFilter.BoxBlur((blur, 0))) if blur else closed_folder
        img.alpha_composite(cf, (x_closed, cy))
        # open folder enters from the right
        x_open = int(W + 60 - ease * (W + 60 - ox))
        of = open_folder
        if blur and p < 0.85:
            of = open_folder.filter(ImageFilter.BoxBlur((max(10 - blur, 0), 0)))
        img.alpha_composite(of, (x_open, oy))
        frames.append(img)
    return frames


# --------------------------------------------------------------------------
# ASS karaoke captions (libass `subtitles` filter burns these in).
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
