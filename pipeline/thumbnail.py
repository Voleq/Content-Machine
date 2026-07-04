"""Auto YouTube thumbnail for LONG videos (§6): ticker + the single most
shocking number + the verdict stamp, on-brand, via Pillow."""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance

from config import Settings
from pipeline.models import LongScript, RefinitivAudit, TagType, Verdict
from pipeline.rasters import DISPLAY_BOLD, GREEN, MONO_BOLD, RED, load_font
from pipeline.refinitiv import RefinitivError, load_audit

log = logging.getLogger(__name__)

# priority-ordered "shock metric" candidates: (field, format, is_shocking)
_SHOCK_RULES = [
    ("net_margin_pct", "Net margin: {v:+.0f}%", lambda v: v < 0),
    ("fcf_yield_pct", "FCF yield: {v:+.0f}%", lambda v: v < 0),
    ("ps_ratio", "P/S: {v:.0f}x", lambda v: v >= 15),
    ("debt_to_equity", "Debt/Equity: {v:.0f}%", lambda v: v >= 100),
    ("revenue_yoy_pct", "Revenue: {v:+.0f}% YoY", lambda v: v < 0 or v > 25),
    ("fcf_margin_pct", "FCF margin: {v:.0f}%", lambda v: v >= 15),
    ("shares_outstanding_yoy_pct", "Dilution: {v:+.0f}%/yr", lambda v: v >= 5),
    ("short_interest_pct", "Short interest: {v:.0f}%", lambda v: v >= 10),
]


def shock_metric(audit: RefinitivAudit) -> str:
    for field, fmt, is_shocking in _SHOCK_RULES:
        v = audit.get(field)
        if isinstance(v, (int, float)) and is_shocking(v):
            return fmt.format(v=v)
    for field, fmt, _ in _SHOCK_RULES:  # fall back to the first present
        v = audit.get(field)
        if isinstance(v, (int, float)):
            return fmt.format(v=v)
    return ""


def make_thumbnail(script: LongScript, ws, settings: Settings) -> Path | None:
    """ws: pipeline.workspace.Workspace. Returns the PNG path (1280x720)."""
    try:
        stamps = script.events_of(TagType.STAMP)
        verdict = None
        for e in reversed(stamps):
            if e.payload in Verdict.__members__:
                verdict = Verdict(e.payload)
                break
        try:
            audit = load_audit(ws.path)
            metric = shock_metric(audit)
        except RefinitivError:
            metric = ""

        W, H = 1280, 720
        bg_path = settings.assets_dir / "backgrounds" / "desk_wide.png"
        img = Image.open(bg_path).convert("RGB").resize((W, H), Image.LANCZOS)
        img = ImageEnhance.Brightness(img).enhance(0.75)
        d = ImageDraw.Draw(img)

        accent = GREEN if (verdict and verdict.is_laudatory) else RED
        d.rectangle([0, 0, 26, H], fill=accent)

        ticker_font = load_font(settings, DISPLAY_BOLD, 170)
        d.text((70, 60), script.ticker, font=ticker_font,
               fill=(245, 240, 230), stroke_width=6, stroke_fill=(0, 0, 0))

        if metric:
            metric_font = load_font(settings, MONO_BOLD, 76)
            d.text((74, 300), metric, font=metric_font,
                   fill=(255, 214, 84), stroke_width=4, stroke_fill=(0, 0, 0))

        d.text((74, H - 90), "THE FULL AUDIT", font=load_font(settings, MONO_BOLD, 44),
               fill=(230, 230, 230), stroke_width=3, stroke_fill=(0, 0, 0))

        if verdict is not None:
            stamp = Image.open(
                settings.assets_dir / "stamps" / f"{verdict.value}.png"
            ).convert("RGBA")
            ratio = 560 / stamp.width
            stamp = stamp.resize((560, int(stamp.height * ratio)), Image.LANCZOS)
            img.paste(stamp, (W - stamp.width - 40, H - stamp.height - 60), stamp)

        out = ws.path / "thumbnail.png"
        img.save(out)
        return out
    except Exception:
        log.exception("thumbnail generation failed (non-fatal)")
        return None
