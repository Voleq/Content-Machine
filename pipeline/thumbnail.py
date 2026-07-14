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

# priority-ordered "shock metric" candidates: (key, format, is_shocking).
# The key resolves against the v3 Snapshot first, then the Dashboard summary
# (by label) via _shock_value — whichever number the metric lives in.
_SHOCK_RULES = [
    ("net_margin", "Net margin: {v:+.0f}%", lambda v: v < 0),
    ("fcf_yield", "FCF yield: {v:+.0f}%", lambda v: v < 0),
    ("ps_ttm", "P/S: {v:.0f}x", lambda v: v >= 15),
    ("debt_to_equity", "Debt/Equity: {v:.0f}%", lambda v: v >= 100),
    ("net_debt_ebitda", "Net debt/EBITDA: {v:.1f}x", lambda v: v >= 3),
    ("revenue_cagr", "Revenue: {v:+.0f}%/yr", lambda v: v < 0 or v > 25),
    ("fcf_margin", "FCF margin: {v:.0f}%", lambda v: v >= 15),
    ("share_cagr", "Dilution: {v:+.0f}%/yr", lambda v: v >= 5),
    ("short_interest", "Short interest: {v:.0f}%", lambda v: v >= 10),
]

# rule key -> (snapshot field_key, Dashboard label)
_SHOCK_SOURCES = {
    "net_margin": ("net_margin", "Net margin (LTM)"),
    "fcf_yield": ("fcf_yield", "FCF yield"),
    "ps_ttm": ("ps_ttm", None),
    "debt_to_equity": ("debt_to_equity", None),
    "net_debt_ebitda": ("net_debt_ebitda_now", "Net debt / EBITDA"),
    "revenue_cagr": (None, "Revenue 4y CAGR"),
    "fcf_margin": (None, "FCF margin (LTM)"),
    "share_cagr": (None, "Share count 4y CAGR"),
    "short_interest": ("short_interest", None),
}


def _shock_value(data: CompanyData, key: str):
    snap_key, dash_label = _SHOCK_SOURCES.get(key, (key, None))
    if snap_key:
        v = data.get(snap_key)
        if isinstance(v, (int, float)):
            return v
    if dash_label:
        v = data.dashboard_get(dash_label)
        if isinstance(v, (int, float)):
            return v
    return None


def shock_metric(data: CompanyData) -> str:
    for key, fmt, is_shocking in _SHOCK_RULES:
        v = _shock_value(data, key)
        if v is not None and is_shocking(v):
            return fmt.format(v=v)
    for key, fmt, _ in _SHOCK_RULES:  # fall back to the first present
        v = _shock_value(data, key)
        if v is not None:
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
