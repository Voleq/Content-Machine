"""Auto YouTube thumbnail for LONG videos: ticker + the single most
shocking number on the Dennis backdrop, via Pillow. No verdict, no stamp
— the number does the talking."""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance

from config import Settings
from pipeline.models import CompanyData, LongScript
from pipeline.company_data import CompanyDataError, load_company_data
from pipeline.rasters import DISPLAY_BOLD, GOLD, MONO_BOLD, RED, load_font

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


def shock_metric(data: CompanyData) -> str:
    for field, fmt, is_shocking in _SHOCK_RULES:
        v = data.get(field)
        if isinstance(v, (int, float)) and is_shocking(v):
            return fmt.format(v=v)
    for field, fmt, _ in _SHOCK_RULES:  # fall back to the first present
        v = data.get(field)
        if isinstance(v, (int, float)):
            return fmt.format(v=v)
    return ""


def make_thumbnail(script: LongScript, ws, settings: Settings) -> Path | None:
    """ws: pipeline.workspace.Workspace. Returns the PNG path (1280x720)."""
    try:
        try:
            data = load_company_data(ws.path)
            metric = shock_metric(data)
        except CompanyDataError:
            metric = ""

        W, H = 1280, 720
        bg_path = settings.assets_dir / "backgrounds" / "dennis_bg_wide.png"
        img = Image.open(bg_path).convert("RGB").resize((W, H), Image.LANCZOS)
        img = ImageEnhance.Brightness(img).enhance(0.85)
        d = ImageDraw.Draw(img)

        d.rectangle([0, 0, 26, H], fill=GOLD)

        ticker_font = load_font(settings, DISPLAY_BOLD, 170)
        d.text((70, 60), script.ticker, font=ticker_font,
               fill=(240, 242, 248), stroke_width=6, stroke_fill=(0, 0, 0))

        if metric:
            metric_font = load_font(settings, MONO_BOLD, 76)
            negative = "-" in metric.split(":")[-1]
            d.text((74, 300), metric, font=metric_font,
                   fill=RED if negative else GOLD,
                   stroke_width=4, stroke_fill=(0, 0, 0))

        d.text((74, H - 100), "THE DEEP DIVE", font=load_font(settings, MONO_BOLD, 44),
               fill=(230, 230, 230), stroke_width=3, stroke_fill=(0, 0, 0))

        brand_font = load_font(settings, DISPLAY_BOLD, 54)
        brand = settings.brand_name
        bw = d.textlength(brand, font=brand_font)
        d.text((W - bw - 48, H - 110), brand, font=brand_font,
               fill=GOLD, stroke_width=3, stroke_fill=(0, 0, 0))

        out = ws.path / "thumbnail.png"
        img.save(out)
        return out
    except Exception:
        log.exception("thumbnail generation failed (non-fatal)")
        return None
