"""Storyboard contact sheet — see the cut before paying to render it.

A LONG can be forty minutes. Discovering a wrong asset, a dead b-roll key or
a chapter that cuts away from the host at the wrong moment *after* the encode
is the single most expensive mistake in the pipeline. This module turns the
segment plan into one PNG in a few seconds: every beat as a thumbnail with
its layout, the asset that will fill it, the words spoken over it, and how
long it holds.

Nothing is encoded. Stills are opened directly; a video segment contributes
one extracted frame. Visuals resolve through the same `ContentManager` the
renderer uses, so what the sheet shows is what the render will produce — and
because that manager caches, resolving here costs the render nothing.
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

from config import Settings, detect_ffmpeg
from pipeline.kit import load_kit
from pipeline.models import KIT_TAG_FAMILIES, TagType, WordTimestamp
from pipeline.rasters import BG, BORDER, CARD, INK, MONO, MONO_BOLD, MUTED, RED, load_font

log = logging.getLogger(__name__)

# Tile geometry, in the sheet's own pixel space.
TILE_W, TILE_H = 420, 300
THUMB_H = 190
PAD = 14
COLS = 4

# Segment kinds whose thumbnail comes from the design kit rather than from
# the content engine.
_KIT_KINDS = {t.value.lower(): fam for t, fam in KIT_TAG_FAMILIES.items()}


def spoken_between(words: list[WordTimestamp], start: float, end: float,
                   limit: int = 110) -> str:
    """The narration under a segment — what the viewer hears over it."""
    said = [w.word for w in words if w.start < end and w.end > start]
    text = " ".join(said).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _video_frame(path: Path, dest: Path) -> Path | None:
    """One frame out of a clip, for the thumbnail. Cheap: no re-encode."""
    ffmpeg, _ = detect_ffmpeg()
    try:
        subprocess.run(
            [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
             "-ss", "0.3", "-i", str(path), "-frames:v", "1", str(dest)],
            capture_output=True, timeout=60, check=True,
        )
    except (subprocess.SubprocessError, OSError) as e:
        log.debug("storyboard: could not grab a frame from %s (%s)", path, e)
        return None
    return dest if dest.exists() else None


def _thumbnail_for(seg, settings: Settings, content, tmp: Path, idx: int,
                   *, ticker: str = "", company_data=None,
                   workspace: Path | None = None) -> tuple[Image.Image | None, str]:
    """(thumbnail, asset label) for one segment. Never raises — a beat the
    storyboard cannot illustrate is exactly what the operator needs to see."""
    kind = seg.kind
    value = str(seg.payload.get("value", ""))
    kit = load_kit(settings.assets_dir)

    try:
        if kind == "host":
            from pipeline.host import pick_shot

            shot = pick_shot(kit, "beat", idx)
            # the open-mouth twin: a storyboard of closed mouths reads as a
            # video with no host in it, which is the thing being checked
            p = shot.open_.path if shot else None
            return (Image.open(p).convert("RGBA") if p else None), "Dennis (talking)"

        if kind in _KIT_KINDS:
            p = kit.resolve(_KIT_KINDS[kind], value)
            label = f"{kind}: {value}" + ("" if p else "  ← NOT IN KIT")
            return (Image.open(p).convert("RGBA") if p else None), label

        if kind == "filing":
            p = (workspace / value) if workspace else None
            ok = bool(p and p.exists())
            return (Image.open(p).convert("RGBA") if ok else None), \
                f"filing: {value}" + ("" if ok else "  ← MISSING")

        if content is None:
            return None, f"{kind}: {value}"

        visual = content.resolve_visual(
            kind, value, ticker=ticker, company_data=company_data,
            style=seg.payload.get("style", "clean"),
        )
        label = f"{kind}: {visual.key} ({visual.source})"
        if visual.is_video:
            frame = _video_frame(visual.path, tmp / f"f{idx}.png")
            return (Image.open(frame).convert("RGBA") if frame else None), label
        return Image.open(visual.path).convert("RGBA"), label
    except Exception as e:  # noqa: BLE001 — a broken beat must still be shown
        log.info("storyboard: %s/%s did not resolve (%s)", kind, value, e)
        return None, f"{kind}: {value}  ← UNRESOLVED ({type(e).__name__})"


def _draw_tile(sheet: Image.Image, settings: Settings, box: tuple[int, int],
               seg, thumb: Image.Image | None, label: str, caption: str,
               index: int) -> None:
    x, y = box
    d = ImageDraw.Draw(sheet)
    d.rectangle([x, y, x + TILE_W - 1, y + TILE_H - 1], fill=CARD, outline=BORDER)

    # thumbnail, contained (never cropped — the point is to see the asset)
    inner = (TILE_W - 2 * PAD, THUMB_H)
    frame_box = [x + PAD, y + PAD, x + PAD + inner[0], y + PAD + inner[1]]
    d.rectangle(frame_box, fill=BG, outline=BORDER)
    if thumb is not None:
        t = thumb.copy()
        t.thumbnail(inner, Image.LANCZOS)
        sheet.paste(t, (x + PAD + (inner[0] - t.width) // 2,
                        y + PAD + (inner[1] - t.height) // 2), t)
    else:
        f = load_font(settings, MONO_BOLD, 22)
        d.text((x + PAD + 16, y + PAD + inner[1] // 2 - 12), "no preview",
               font=f, fill=RED)

    mono = load_font(settings, MONO_BOLD, 17)
    small = load_font(settings, MONO, 15)
    ty = y + PAD + THUMB_H + 8
    text_w = TILE_W - 2 * PAD
    layout = seg.payload.get("layout", "")
    head = f"{index:02d}  {seg.length:5.1f}s  {layout}" if layout else \
           f"{index:02d}  {seg.length:5.1f}s"
    d.text((x + PAD, ty), head, font=mono, fill=INK)
    for line in _fit(d, label, small, text_w, 1):
        d.text((x + PAD, ty + 22), line, font=small,
               fill=RED if "←" in label else MUTED)
    if caption:
        for i, line in enumerate(_fit(d, f"“{caption}”", small, text_w, 2)):
            d.text((x + PAD, ty + 42 + i * 18), line, font=small, fill=MUTED)


def _fit(d: ImageDraw.ImageDraw, text: str, font, width: int,
         max_lines: int) -> list[str]:
    """Wrap to the tile, ellipsising the overflow. Measured rather than
    guessed at a character count — the mono face is wider than it looks."""
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if d.textlength(trial, font=font) <= width or not cur:
            cur = trial
            continue
        lines.append(cur)
        cur = w
        if len(lines) == max_lines:
            break
    if len(lines) < max_lines and cur:
        lines.append(cur)
    if len(lines) == max_lines:
        last = lines[-1]
        while last and d.textlength(last + "…", font=font) > width:
            last = last[:-1]
        consumed = sum(len(x) for x in lines) + len(lines)
        if consumed < len(text):
            lines[-1] = last.rstrip() + "…"
    return lines[:max_lines]


def build_storyboard(
    segments,
    words: list[WordTimestamp],
    out_path: Path,
    settings: Settings,
    *,
    content=None,
    ticker: str = "",
    company_data=None,
    workspace: Path | None = None,
    title: str = "",
    cols: int = COLS,
) -> tuple[Path, list[str]]:
    """Write the contact sheet. Returns (path, problems).

    `problems` lists beats whose asset did not resolve — the thing worth
    fixing before spending an encode on it.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rows = (len(segments) + cols - 1) // cols
    header_h = 78
    sheet = Image.new("RGBA", (cols * TILE_W, header_h + rows * TILE_H), (*BG, 255))
    d = ImageDraw.Draw(sheet)

    total = sum(s.length for s in segments)
    head_font = load_font(settings, MONO_BOLD, 28)
    sub_font = load_font(settings, MONO, 18)
    d.text((PAD + 4, 16), title or "storyboard", font=head_font, fill=INK)
    kinds: dict[str, int] = {}
    for s in segments:
        kinds[s.kind] = kinds.get(s.kind, 0) + 1
    mix = "  ".join(f"{k}×{n}" for k, n in sorted(kinds.items()))
    d.text((PAD + 4, 50),
           f"{len(segments)} beats · {total / 60:.1f} min · {mix}",
           font=sub_font, fill=MUTED)

    problems: list[str] = []
    with tempfile.TemporaryDirectory(prefix="storyboard_") as td:
        tmp = Path(td)
        for i, seg in enumerate(segments):
            thumb, label = _thumbnail_for(
                seg, settings, content, tmp, i, ticker=ticker,
                company_data=company_data, workspace=workspace,
            )
            if "←" in label:
                problems.append(f"beat {i:02d} @ {seg.start:.1f}s — {label}")
            _draw_tile(
                sheet, settings,
                ((i % cols) * TILE_W, header_h + (i // cols) * TILE_H),
                seg, thumb, label, spoken_between(words, seg.start, seg.end), i,
            )

    sheet.convert("RGB").save(out_path)
    log.info("storyboard: %d beats -> %s (%d problems)",
             len(segments), out_path, len(problems))
    return out_path, problems
