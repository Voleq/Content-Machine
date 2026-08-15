"""Branded chart rendering — the channel's own visual, drawn by the
pipeline from its own data (§4: never a TradingView screenshot).

Products:
  * `render_price_chart`        — the clean SHORT hero: price line + area
    fill on a dark card, ticker + move badge, last-point marker.
  * `render_marker_price_chart` — the crude "napkin chart": the same price
    data drawn as a rough hand-drawn marker scribble on paper. Same meta
    contract, so a SHORT can open on either (chart_style / [CHART: … style=marker]).
  * `render_metric_chart`       — the [CHART: metric] auto-chart for LONG:
    multi-year bars from the company-data history sheet.

Both price charts return layout metadata (plot box, last point, headline
slots) so annotations and headline overlays anchor to real pixels.

Chart-craft rules applied: one axis, single series (the title names it —
no legend), thin marks, recessive grid, direction stated in TEXT (+/-%)
so color is never the only channel. Up/down colors never co-occur on one
chart; all inks pass ≥3:1 contrast on the paper surface.
"""

from __future__ import annotations

import logging
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw

from config import Settings
from pipeline.rasters import (
    drawn_rect,
    mark_image,
    marker_stroke,
    thicken_mark,
    tint_mark,
)

log = logging.getLogger(__name__)

# light-surface palette — the Dennis kit tokens (validated: contrast ≥ 3:1)
SURFACE = (250, 249, 246)     # #faf9f6 card
FRAME = (242, 242, 239)       # #f2f2ef paper around the card
INK = (35, 35, 38)            # #232326 primary text
MUTED = (143, 140, 131)       # #8f8c83 secondary text
GRID = (222, 219, 209)        # #dedbd1 recessive gridlines
UP = (47, 213, 118)           # #2fd576 UP ONLY
DOWN = (255, 82, 71)          # #ff5247 down / emphasis
ACCENT = (255, 82, 71)        # single-hue magnitude (the light kit leads red)

# brand fonts (reproduced from the .dc.html kits)
_SANS = "SpaceGrotesk-Bold.ttf"      # numbers / UI sans
_MONO = "SpaceMono-Regular.ttf"      # labels
_MONO_BOLD = "SpaceMono-Bold.ttf"
_MARKER = "ShantellSans-Bold.ttf"    # hand-drawn marker text


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

    # One rng for every drawn mark on this card, seeded off the series so the
    # same data always draws the same card — a chart that re-wobbles on every
    # render breaks the golden-frame check for no reason.
    rng = random.Random(f"clean|{series.ticker}|{closes[-1]}|{len(closes)}")

    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # The card is still a card — the CLEAN style is the precise register — but
    # its EDGE is drawn. A `rounded_rectangle` outline was the one hard
    # geometric line in a kit whose every other border is a pen stroke.
    d.rounded_rectangle([0, 0, W - 1, H - 1], radius=int(W * 0.03),
                        fill=(*SURFACE, 255))
    drawn_rect(d, [2, 2, W - 3, H - 3], rng, width=2, color=(*GRID, 255),
                jitter=1.4, overshoot=0.004)

    pad = int(W * 0.055)
    head_h = int(H * 0.17)

    # ---- header: ticker (the title names the series — no legend) + badge.
    # Both share one line: shrink the badge text until everything fits.
    tick_font = _font(settings, _SANS, int(head_h * 0.52))
    tick_w = d.textlength(series.ticker, font=tick_font)
    d.text((pad, pad * 0.75), series.ticker, font=tick_font, fill=(*INK, 255))
    move = move_text or f"{series.pct_change_1d:+.1f}%"
    avail = W - pad * 2 - tick_w - int(pad * 0.8)
    size = int(head_h * 0.30)
    badge_font = _font(settings, _SANS, size)
    while size > 12 and d.textlength(move, font=badge_font) + pad * 0.9 > avail:
        size -= 2
        badge_font = _font(settings, _SANS, size)
    while move and d.textlength(move + "…", font=badge_font) + pad * 0.9 > avail:
        move = move[:-1].rstrip()
        if len(move) < 6:
            break
    if not move.endswith("%") and move != (move_text or f"{series.pct_change_1d:+.1f}%"):
        move += "…"
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
    lbl_font = _font(settings, _MONO, max(int(H * 0.026), 12))
    for k in range(4):
        gy = y0 + (y1 - y0) * k / 3
        # Ruled by hand. A 1px grid line is a printed rule; the kit's rules
        # are drawn, and at this jitter it still reads as recessive.
        marker_stroke(d, [(x0, gy), (x1, gy)], rng, width=1,
                       color=(*GRID, 255), jitter=0.9, passes=1)
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

    # ---- last-point marker, ringed by hand
    #
    # It used to sit inside a Gaussian glow. Nothing on paper glows: a blur is
    # a screen effect, and it was the one mark on the card that could not have
    # been made with a pen. The ring is `marks/circle` — the same scrawl the
    # renderer already draws over a numbers row — and a drawn one when the kit
    # has not shipped it.
    lx, ly = pts[-1]
    d.ellipse([lx - 7, ly - 7, lx + 7, ly + 7], fill=(*line_rgb, 255),
              outline=(*SURFACE, 255), width=2)
    _drawn_ring(img, lx, ly, W * 0.042, W * 0.036, rng,
                width=max(int(W * 0.004), 2), color=(*line_rgb, 235),
                settings=settings)
    d = ImageDraw.Draw(img)

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


# --------------------------------------------------------------------------
# The chart's ring, on the shared primitives.
#
# Both charts go through it. The channel had two chart renderers speaking two
# different visual languages: one drew wobbly axes with a chunky nib, the other
# drew `rounded_rectangle(radius=W*0.03)`, 1px grid lines and a Gaussian glow.
# Two chart STYLES in one channel is fine — precision is a legitimate register.
# Two drawing LANGUAGES is not, and the clean card was the only surface in the
# kit that looked machine-made.
#
# The primitives themselves — `marker_stroke`, `drawn_rect`, `mark_image` and
# the mark's tint/dilate — live in `rasters.py`, because the charts are no
# longer the only surface drawing with them.
# --------------------------------------------------------------------------


def _drawn_ring(img, cx, cy, rx, ry, rng, *, width, color, settings=None,
                turns=1.15):
    """The kit's "doubt" ring around a point, drawn onto `img` in place.

    Prefers real artwork: `marks/circle` is the mark the channel actually
    uses, and a drawn one is the fallback for a kit that has not shipped it.
    Never a glow — nothing on paper glows, and a Gaussian blur was the one
    effect in the light kit that could not have been made with a pen.

    The centre is pulled back onto the card when the point it marks sits near
    an edge. A last close is very often the highest or the newest point, so
    the ring ran off the right-hand side more often than not — the procedural
    scrawl got away with it because it was thin, a real mark does not.
    """
    cx = min(max(cx, rx), max(img.width - rx, rx))
    cy = min(max(cy, ry), max(img.height - ry, ry))
    if settings is not None:
        mark = mark_image(settings, "marks/circle")
        if mark is not None:
            # Its OWN aspect, not a square: the mark is a 5:4 scrawl and
            # squashing it to a circle is the machine look coming back in
            # through the resize.
            box = max(int(rx * 2), 8), max(int(ry * 2), 8)
            scale = min(box[0] / mark.width, box[1] / mark.height)
            w = max(int(mark.width * scale), 8)
            h = max(int(mark.height * scale), 8)
            mark = mark.resize((w, h), Image.LANCZOS)
            # A 1200px-wide drawing at 76px has a sub-pixel stroke, so the
            # scrawl arrives as a hairline — thinner than the data line it is
            # marking. Dilating the ink back to the nib is what keeps it a pen
            # stroke rather than a downscaling artefact.
            mark = thicken_mark(mark, max(int(width) - 1, 0))
            img.alpha_composite(tint_mark(mark, color),
                                (int(cx - w / 2), int(cy - h / 2)))
            return
    d = ImageDraw.Draw(img)
    for _ in range(2):
        ring = []
        for t in range(53):
            th = -math.pi / 2 + 2 * math.pi * turns * (t / 52)
            ring.append((cx + rx * math.cos(th) + rng.uniform(-3, 3),
                         cy + ry * math.sin(th) + rng.uniform(-3, 3)))
        d.line(ring, fill=color, width=width, joint="curve")


def render_marker_price_chart(
    series,
    out_path: Path,
    settings: Settings,
    *,
    size: tuple[int, int] = (1000, 780),
    move_text: str = "",
    seed: str = "",
    ring: bool = True,
) -> tuple[Path, dict]:
    """The napkin chart: `series` price line drawn as a rough marker
    scribble on black. Returns (png_path, meta) with the SAME anchor
    contract as render_price_chart.

    `seed` moves the hand without moving the data: the same series drawn
    again lands its line 2-3% differently, which is how a full-bleed chart
    boils instead of sitting on the frame as a photograph. Empty seed
    reproduces the original drawing exactly."""
    W, H = size
    closes = list(series.closes)
    up = closes[-1] >= closes[0]
    line_rgb = UP if up else DOWN
    rng = random.Random(f"marker|{series.ticker}|{closes[-1]}|{len(closes)}|{seed}")

    # The napkin chart is marker on PAPER, not chalk on black. It used to be
    # the one dark surface left in a light kit, and it sat behind the hook —
    # so a short opened by inverting its own theme.
    PAPER = FRAME
    CHALK = INK
    img = Image.new("RGBA", (W, H), (*PAPER, 255))
    d = ImageDraw.Draw(img)
    nib = max(int(W * 0.006), 3)

    pad = int(W * 0.06)
    head_h = int(H * 0.16)
    # scrawled title (the title names the series — no legend) + move aside
    tick_font = _font(settings, _MARKER, int(head_h * 0.55))
    d.text((pad + rng.randint(-3, 3), pad * 0.7), series.ticker,
           font=tick_font, fill=(*CHALK, 255))
    move = move_text or f"{series.pct_change_1d:+.1f}%"
    move_font = _font(settings, _MARKER, int(head_h * 0.30))
    mw = d.textlength(move, font=move_font)
    if pad + d.textlength(series.ticker, font=tick_font) + mw + pad < W:
        d.text((W - pad - mw, pad * 0.9 + head_h * 0.18), move,
               font=move_font, fill=(*line_rgb, 255))

    x0, y0 = pad, head_h + pad
    x1, y1 = W - pad, H - pad - int(H * 0.05)
    # crude hand-drawn axes
    marker_stroke(d, [(x0, y0 - 6), (x0, y1)], rng, width=nib, color=(*CHALK, 220),
                   jitter=2.5, passes=1)
    marker_stroke(d, [(x0, y1), (x1 + 4, y1)], rng, width=nib, color=(*CHALK, 220),
                   jitter=2.5, passes=1)

    lo, hi = min(closes), max(closes)
    span = (hi - lo) or 1.0
    lo -= span * 0.08
    hi += span * 0.08
    span = hi - lo

    def pt(i: int):
        x = x0 + (x1 - x0) * (i / max(len(closes) - 1, 1))
        y = y1 - (y1 - y0) * ((closes[i] - lo) / span)
        return x, y

    pts = [pt(i) for i in range(len(closes))]
    marker_stroke(d, pts, rng, width=nib + 2, color=(*line_rgb, 255),
                   jitter=3.2, passes=3)

    # a scrawled arrow off the last point, in the move direction
    lx, ly = pts[-1]
    ax, ay = lx + W * 0.02, ly - (H * 0.06 if up else -H * 0.06)
    marker_stroke(d, [(lx, ly), (ax, ay)], rng, width=nib, color=(*line_rgb, 255),
                   jitter=2, passes=2)
    head = H * 0.028
    if up:
        marker_stroke(d, [(ax - head, ay + head), (ax, ay), (ax + head, ay + head * 0.6)],
                       rng, width=nib, color=(*line_rgb, 255), jitter=1.5, passes=1)
    else:
        marker_stroke(d, [(ax - head, ay - head), (ax, ay), (ax + head, ay - head * 0.6)],
                       rng, width=nib, color=(*line_rgb, 255), jitter=1.5, passes=1)

    # The red scrawl circle around the spike (the kit's signature "doubt"
    # mark). Optional, because under the shot templates a mark is composition
    # and composition belongs to the template: with both drawing one, the
    # frame carried two rings in two weights, on two different candles.
    if ring:
        _drawn_ring(img, lx, ly, W * 0.11, H * 0.11, rng, width=nib,
                    color=(*DOWN, 255), settings=settings)
    d = ImageDraw.Draw(img)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)

    meta = {
        "size": [W, H],
        "plot_box": [x0, y0, x1, y1],
        "last_point": [round(lx), round(ly)],
        "direction": "up" if up else "down",
        "style": "marker",
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

    title_font = _font(settings, _SANS, int(H * 0.062))
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
    yr_font = _font(settings, _MONO, max(int(H * 0.034), 14))
    val_font = _font(settings, _MONO_BOLD, max(int(H * 0.036), 14))

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
