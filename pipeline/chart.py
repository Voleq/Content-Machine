"""Branded chart rendering — the channel's own visual, drawn by the
pipeline from its own data (§4: never a TradingView screenshot).

Two products, one style:
  * `render_price_chart`  — the SHORT hero: price line + area fill on a
    dark card, ticker + move badge, last-point marker. Returns layout
    metadata so annotations (scribbles) and headline overlays can anchor
    to real pixel positions instead of guessing.
  * `render_metric_chart` — the [CHART: metric] auto-chart for LONG:
    multi-year bars from the company-data history sheet.

Chart-craft rules applied: one axis, single series (the title names it —
no legend), thin marks, recessive grid, direction stated in TEXT (+/-%)
so color is never the only channel. Up/down colors never co-occur on one
chart; all inks pass ≥3:1 contrast on the dark surface.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from config import Settings

# dark-surface palette (validated: contrast vs SURFACE ≥ 3:1)
SURFACE = (18, 21, 28)        # #12151C card
FRAME = (11, 13, 18)          # around the card
INK = (232, 234, 240)         # primary text
MUTED = (154, 163, 178)       # secondary text
GRID = (38, 43, 54)           # recessive gridlines
UP = (63, 185, 104)           # #3FB968
DOWN = (224, 82, 82)          # #E05252
ACCENT = (255, 205, 60)       # brand gold (badges, single-hue bars)


def _font(settings: Settings, name: str, size: int):
    from PIL import ImageFont

    return ImageFont.truetype(str(settings.fonts_dir / name), size)


def _fmt_price(v: float) -> str:
    if v >= 1000:
        return f"{v:,.0f}"
    if v >= 100:
        return f"{v:.1f}"
    return f"{v:.2f}"


def render_price_chart(
    series,
    out_path: Path,
    settings: Settings,
    *,
    size: tuple[int, int] = (1000, 780),
    move_text: str = "",
) -> tuple[Path, dict]:
    """Draw the branded price card. Returns (png_path, meta) where meta
    holds pixel anchors: plot box, last close point, headline slots.

    `series` is a pipeline.prices.PriceSeries.
    """
    W, H = size
    closes = list(series.closes)
    up = closes[-1] >= closes[0]
    line_rgb = UP if up else DOWN

    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, W - 1, H - 1], radius=int(W * 0.03),
                        fill=(*SURFACE, 255), outline=(*GRID, 255), width=2)

    pad = int(W * 0.055)
    head_h = int(H * 0.17)

    # ---- header: ticker (the title names the series — no legend) + badge
    tick_font = _font(settings, "DejaVuSans-Bold.ttf", int(head_h * 0.52))
    d.text((pad, pad * 0.75), series.ticker, font=tick_font, fill=(*INK, 255))
    move = move_text or f"{series.pct_change_1d:+.1f}%"
    badge_font = _font(settings, "DejaVuSans-Bold.ttf", int(head_h * 0.30))
    bw = d.textlength(move, font=badge_font)
    bx1 = W - pad
    bx0 = bx1 - bw - int(pad * 0.9)
    by0 = pad * 0.75
    by1 = by0 + head_h * 0.52
    d.rounded_rectangle([bx0, by0, bx1, by1], radius=int((by1 - by0) / 2),
                        fill=(*line_rgb, 255))
    d.text((bx0 + int(pad * 0.45), by0 + (by1 - by0 - badge_font.size) / 2 - 2),
           move, font=badge_font, fill=(12, 14, 18, 255))

    # ---- plot box
    x0, y0 = pad, head_h + pad
    x1, y1 = W - pad, H - pad - int(H * 0.055)
    lo, hi = min(closes), max(closes)
    span = (hi - lo) or 1.0
    lo -= span * 0.06
    hi += span * 0.06
    span = hi - lo

    def pt(i: int) -> tuple[float, float]:
        x = x0 + (x1 - x0) * (i / max(len(closes) - 1, 1))
        y = y1 - (y1 - y0) * ((closes[i] - lo) / span)
        return x, y

    # recessive grid: 4 horizontals + right-edge price labels (muted)
    lbl_font = _font(settings, "DejaVuSansMono.ttf", max(int(H * 0.026), 12))
    for k in range(4):
        gy = y0 + (y1 - y0) * k / 3
        d.line([x0, gy, x1, gy], fill=(*GRID, 255), width=1)
        val = hi - span * k / 3
        d.text((x1 - d.textlength(_fmt_price(val), font=lbl_font), gy - lbl_font.size - 3),
               _fmt_price(val), font=lbl_font, fill=(*MUTED, 255))
    # 3 date labels along the bottom
    if series.dates:
        for frac in (0.0, 0.5, 1.0):
            i = int(frac * (len(series.dates) - 1))
            label = series.dates[i][5:]  # MM-DD
            lx = x0 + (x1 - x0) * frac - d.textlength(label, font=lbl_font) * frac
            d.text((lx, y1 + 6), label, font=lbl_font, fill=(*MUTED, 255))

    # ---- area fill (vertical fade of the direction color)
    pts = [pt(i) for i in range(len(closes))]
    area = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ad = ImageDraw.Draw(area)
    ad.polygon(pts + [(x1, y1), (x0, y1)], fill=(*line_rgb, 60))
    fade = Image.new("L", (1, H), 0)
    for yy in range(H):
        if yy <= y0:
            fade.putpixel((0, yy), 255)
        elif yy >= y1:
            fade.putpixel((0, yy), 0)
        else:
            fade.putpixel((0, yy), int(255 * (1 - (yy - y0) / (y1 - y0)) * 0.9 + 20))
    area.putalpha(Image.composite(
        area.getchannel("A"), Image.new("L", (W, H), 0), fade.resize((W, H))
    ))
    img.alpha_composite(area)

    # ---- the line itself (thin mark: ~3px at 1000w)
    d = ImageDraw.Draw(img)
    d.line(pts, fill=(*line_rgb, 255), width=max(int(W * 0.004), 2), joint="curve")

    # ---- last-point marker with a soft glow
    lx, ly = pts[-1]
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([lx - 14, ly - 14, lx + 14, ly + 14],
                                 fill=(*line_rgb, 140))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(6)))
    d.ellipse([lx - 7, ly - 7, lx + 7, ly + 7], fill=(*line_rgb, 255),
              outline=(*SURFACE, 255), width=2)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)

    meta = {
        "size": [W, H],
        "plot_box": [x0, y0, x1, y1],
        "last_point": [round(lx), round(ly)],
        "direction": "up" if up else "down",
        # stacked slots where headline cards overlay ON the chart without
        # burying the line's endpoint
        "headline_slots": [
            [pad, int(y0 + (y1 - y0) * 0.06 + i * (y1 - y0) * 0.30)]
            for i in range(3)
        ],
        "source": series.source,
        "degraded": series.degraded,
    }
    return out_path, meta


def render_metric_chart(
    label: str,
    years: list[str],
    values: list[float | None],
    out_path: Path,
    settings: Settings,
    *,
    size: tuple[int, int] = (1600, 900),
) -> Path:
    """Multi-year bars in the channel style for [CHART: metric] — single
    hue for magnitude; negative years dip below a zero line in the down
    color with the sign printed, so polarity is never color-alone."""
    W, H = size
    img = Image.new("RGB", (W, H), FRAME)
    d = ImageDraw.Draw(img)
    pad = int(W * 0.06)
    d.rounded_rectangle([pad // 2, pad // 2, W - pad // 2, H - pad // 2],
                        radius=24, fill=SURFACE, outline=GRID, width=2)

    title_font = _font(settings, "DejaVuSans-Bold.ttf", int(H * 0.062))
    d.text((pad, pad * 0.85), label, font=title_font, fill=INK)

    vals = [(v if isinstance(v, (int, float)) else None) for v in values]
    present = [v for v in vals if v is not None]
    if not present:
        d.text((pad, H / 2), "no data", font=title_font, fill=MUTED)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(out_path)
        return out_path

    x0, y0 = pad, pad + int(H * 0.12)
    x1, y1 = W - pad, H - pad - int(H * 0.07)
    lo, hi = min(min(present), 0.0), max(max(present), 0.0)
    span = (hi - lo) or 1.0

    def y_of(v: float) -> float:
        return y1 - (y1 - y0) * ((v - lo) / span)

    zero_y = y_of(0.0)
    for k in range(4):  # recessive grid
        gy = y0 + (y1 - y0) * k / 3
        d.line([x0, gy, x1, gy], fill=GRID, width=1)
    d.line([x0, zero_y, x1, zero_y], fill=MUTED, width=2)

    n = len(vals)
    slot = (x1 - x0) / n
    bar_w = slot * 0.56
    yr_font = _font(settings, "DejaVuSansMono.ttf", max(int(H * 0.034), 14))
    val_font = _font(settings, "DejaVuSansMono-Bold.ttf", max(int(H * 0.036), 14))

    def _fmt(v: float) -> str:
        a = abs(v)
        if a >= 1e9:
            return f"{v / 1e9:.1f}B"
        if a >= 1e6:
            return f"{v / 1e6:.0f}M"
        if a >= 1e3:
            return f"{v / 1e3:.0f}K"
        return f"{v:.1f}".rstrip("0").rstrip(".")

    for i, v in enumerate(vals):
        cx = x0 + slot * (i + 0.5)
        if years and i < len(years):
            yl = str(years[i])
            d.text((cx - d.textlength(yl, font=yr_font) / 2, y1 + 8),
                   yl, font=yr_font, fill=MUTED)
        if v is None:
            d.text((cx - d.textlength("–", font=yr_font) / 2, zero_y - yr_font.size - 4),
                   "–", font=yr_font, fill=MUTED)
            continue
        vy = y_of(v)
        color = ACCENT if v >= 0 else DOWN
        top, bot = (vy, zero_y) if v >= 0 else (zero_y, vy)
        if bot - top < 3:
            bot = top + 3
        d.rounded_rectangle([cx - bar_w / 2, top, cx + bar_w / 2, bot],
                            radius=4, fill=color)
        # selective direct labels: first, last, and any negative year
        if i in (0, n - 1) or v < 0:
            txt = _fmt(v)
            ty = top - val_font.size - 6 if v >= 0 else bot + 6
            d.text((cx - d.textlength(txt, font=val_font) / 2, ty),
                   txt, font=val_font, fill=INK)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path
