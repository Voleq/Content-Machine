"""The cover — a frame from the video, not a poster for a different one.

A thumbnail is the only part of the channel most people ever see, and this one
advertised a product that no longer exists. It painted on
``backgrounds/dennis_bg_wide.png`` — mean luminance 17, a near-black photo —
darkened it further, and accented in a gold that is not in the kit palette,
with every string carrying a six-pixel black outline because that is what type
needs to survive on a photograph. The video it was selling is ink on paper.

So it is drawn the way the frames are drawn: a kit paper background, Dennis
as a real kit figure, the ticker in Shantell, the leading figure in Space
Mono, and a border that is a pen stroke rather than a rectangle primitive. Red
means the number is bad, green is reserved for an up-move, and everything else
is ink — the same rule the charts follow, so colour still means one thing
across the channel.

Dennis is a `mascot/` CUT-OUT rather than a host chapter card. The chapter
cards are complete 16:9 scenes carrying their own headline, and 69 of them
still have the long-form ticker chip and disclaimer baked in — dropping one
behind a cover that already has a ticker on it puts two tickers in the frame.
The cut-outs are the same figures the long-form two-shot stands beside the
evidence, which is the composition this is imitating.

Both formats get one. `make_thumbnail` took a `LongScript`, so the SHORT — the
daily-volume format — produced no cover at all; it now takes either and emits
the 9:16 alongside the 16:9.
"""

from __future__ import annotations

import logging
import random
import re
from pathlib import Path

from PIL import Image, ImageDraw

from config import Settings
from pipeline.company_data import CompanyDataError, load_company_data
from pipeline.models import CompanyData
from pipeline.rasters import (
    CARD_LINE,
    GREEN,
    INK,
    MONO_BOLD,
    MUTED,
    BG,
    RED,
    SHANTELL,
    drawn_rect,
    load_font,
)

log = logging.getLogger(__name__)

# 16:9 for YouTube, 9:16 for the shorts shelf. Both are the platform's own
# cover sizes — a 1280x720 cover cropped to a vertical shelf loses the figure.
WIDE = (1280, 720)
TALL = (1080, 1920)

# The paper the kit ships, per orientation. `room-*` carries the desk vignette,
# which is what makes a cover read as a frame from the video rather than as a
# card about it.
BACKDROPS = {"wide": ("backgrounds/room-wide", "backgrounds/flat-wide"),
             "tall": ("backgrounds/room-tall", "backgrounds/flat-tall")}

# Whole-figure mascot poses — the same cut-outs the two-shot uses. A host
# chapter card would bring its own headline and its own baked furniture into a
# frame that already has copy on it.
FIGURES = ("mascot/deadpan", "mascot/tired-explaining", "mascot/shrug",
           "mascot/exasperated")

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


# A figure with its unit: `-18%`, `+29%`, `3.4x`, `$1.1B`.
_FIGURE_RE = re.compile(r"[-+]?\$?\d[\d,]*\.?\d*\s*(?:%|x|bn|b|m|k)?", re.I)


def split_metric(metric: str) -> tuple[str, str]:
    """`"Net margin: -12%"` -> `("NET MARGIN", "-12%")`.

    The label and the figure are set differently — the label is small and
    muted, the figure is the thing you can read across a room — so they are
    separated here rather than drawn as one string in one size, which is what
    made the old cover's metric line unreadable at shelf size.

    A SHORT has no workbook half the time, so it leads on its `move_summary`,
    which is prose with no colon in it: `"+29% today · 5x average volume"`.
    Set whole, that shrinks to fit the width and the cover has no figure on it
    at all — so the leading number is pulled out and the rest becomes the
    label.
    """
    label, sep, value = metric.partition(":")
    if sep:
        return label.strip().upper(), value.strip()
    m = _FIGURE_RE.match(metric.strip())
    if m and m.group(0).strip():
        rest = metric.strip()[m.end():].strip(" ·-—,")
        return rest.upper(), m.group(0).strip()
    return "", metric.strip()


def metric_colour(value: str, *, is_move: bool = False) -> tuple[int, int, int]:
    """Ink unless the figure earns a colour.

    The kit's rule, and the charts already follow it: red is a bad number,
    green is UP ONLY, ink is everything else. The old cover accented in gold,
    which said nothing at all because it was on every thumbnail.

    `is_move` is what keeps "up only" from meaning "positive". A price move
    that is up is the one thing green is for; `Net margin: +5%` is a positive
    number and not an up-move, so it stays ink. Without the distinction green
    either never appears — and the rule is decoration — or it appears on any
    positive figure, and it stops meaning direction.
    """
    m = re.search(r"-?\d+(?:\.\d+)?", value)
    if m is None:
        return INK
    if value.strip().startswith("-") or float(m.group(0)) < 0:
        return RED
    return GREEN if is_move else INK


def _fit(text: str, settings: Settings, font_name: str, size: int,
         max_w: int, probe: ImageDraw.ImageDraw):
    """The largest font at or below `size` whose text fits `max_w`."""
    while size > 12:
        font = load_font(settings, font_name, size)
        if probe.textlength(text, font=font) <= max_w:
            return font
        size -= 4
    return load_font(settings, font_name, size)


def _backdrop(settings: Settings, orient: str, size: tuple[int, int]) -> Image.Image:
    """The kit's paper for this orientation, or plain paper."""
    from pipeline.kit import load_kit

    try:
        kit = load_kit(settings.assets_dir)
        for key in BACKDROPS[orient]:
            asset = kit.get(key)
            if asset is not None and asset.frames:
                return (Image.open(asset.frames[0]).convert("RGB")
                        .resize(size, Image.LANCZOS))
    except Exception as exc:  # noqa: BLE001 — a cover is never fatal
        log.debug("thumbnail: no kit backdrop (%s)", exc)
    return Image.new("RGB", size, BG)


def _figure(settings: Settings, seed: str) -> Image.Image | None:
    """One mascot cut-out, trimmed to its own ink."""
    from pipeline.kit import load_kit

    try:
        kit = load_kit(settings.assets_dir)
        options = [a for k in FIGURES if (a := kit.get(k)) is not None]
        if not options:
            return None
        asset = options[random.Random(seed).randrange(len(options))]
        img = Image.open(asset.frames[0]).convert("RGBA")
        box = img.getbbox()
        return img.crop(box) if box else img
    except Exception as exc:  # noqa: BLE001
        log.debug("thumbnail: no mascot figure (%s)", exc)
        return None


def _compose(settings: Settings, *, ticker: str, metric: str, kicker: str,
             size: tuple[int, int], orient: str,
             is_move: bool = False) -> Image.Image:
    """One cover. Paper, a drawn border, the ticker, the number, Dennis."""
    W, H = size
    img = _backdrop(settings, orient, size).convert("RGBA")
    d = ImageDraw.Draw(img)
    rng = random.Random(f"thumb|{ticker}|{metric}|{orient}")

    # The border is a pen stroke. The frames it is selling have no geometric
    # rules in them anywhere.
    inset = int(min(W, H) * 0.035)
    drawn_rect(d, [inset, inset, W - inset, H - inset], rng,
               width=max(int(min(W, H) * 0.005), 3), color=(*CARD_LINE, 255),
               jitter=2.0, overshoot=0.006)

    pad = int(inset * 1.9)
    # Type sizes as a fraction of the frame's HEIGHT, per orientation. The
    # vertical cover is more than twice as tall for the same content, so
    # reusing the wide fractions left a third of the frame empty between the
    # figure and the type — on a shelf that reads as an unfinished card.
    wide = orient == "wide"
    tick_h = 0.17 if wide else 0.11
    val_h = 0.23 if wide else 0.20
    lab_h = 0.036 if wide else 0.026
    fig_h = 0.58 if wide else 0.50

    # Dennis first, so the type sits over him rather than under.
    fig = _figure(settings, f"{ticker}|{orient}")
    if fig is not None:
        fh = int(H * fig_h)
        fw = max(int(fig.width * fh / fig.height), 1)
        fig = fig.resize((fw, fh), Image.LANCZOS)
        img.alpha_composite(fig, (W - fw - pad, H - fh - pad))

    # The wide cover reserves a column for the figure; the tall one puts him
    # below the type, so the type gets the full width.
    text_w = W - 2 * pad - (int(W * 0.30) if wide else 0)
    y = pad

    tick_font = _fit(f"${ticker}", settings, SHANTELL, int(H * tick_h), text_w, d)
    d.text((pad, y), f"${ticker}", font=tick_font, fill=(*INK, 255))
    y += int(tick_font.size * 1.15)

    label, value = split_metric(metric)
    if label:
        lab_font = load_font(settings, MONO_BOLD, int(H * lab_h))
        # One line. A move summary can run long and a wrapped grey line under
        # the ticker is not what anybody is reading the cover for.
        while (label and d.textlength(label, font=lab_font) > text_w
               and " " in label):
            label = label.rsplit(" ", 1)[0]
        d.text((pad, y), label, font=lab_font, fill=(*MUTED, 255))
        y += int(lab_font.size * 1.6)
    if value:
        val_font = _fit(value, settings, MONO_BOLD, int(H * val_h), text_w, d)
        d.text((pad, y), value, font=val_font,
               fill=(*metric_colour(value, is_move=is_move), 255))

    # The kicker sits on the baseline, muted — it names the format, it is not
    # the headline.
    kick_font = load_font(settings, MONO_BOLD,
                          int(H * (0.038 if orient == "wide" else 0.022)))
    d.text((pad, H - pad - kick_font.size), kicker.upper(), font=kick_font,
           fill=(*MUTED, 255))
    return img.convert("RGB")


def make_thumbnail(script, ws, settings: Settings) -> Path | None:
    """Cover art for a finished video. Returns the 16:9 PNG path.

    `script` is a `LongScript` or a `ShortScript` — the SHORT is the
    daily-volume format and it had no cover at all, because this was typed to
    the LONG. A short gets the 9:16 as well, written beside it.

    Never raises: a missing cover is a nuisance, a failed render is not.
    """
    try:
        try:
            metric = shock_metric(load_company_data(ws.path))
        except CompanyDataError:
            metric = ""

        ticker = str(getattr(script, "ticker", "") or "").upper()
        is_short = str(getattr(script, "format", "long")).lower() == "short"
        # A SHORT leads on the move — that is what the format is about, and it
        # is the one figure that is there even when no workbook was uploaded.
        # A LONG leads on the shock metric out of the filings.
        move = str(getattr(script, "move_summary", "") or "").strip()
        is_move = bool(is_short and move) or not metric
        if is_move and move:
            metric = move
        kicker = "noise or signal?" if is_short else "the deep dive"

        out = ws.path / "thumbnail.png"
        _compose(settings, ticker=ticker, metric=metric, kicker=kicker,
                 size=WIDE, orient="wide", is_move=is_move).save(out)
        if is_short:
            _compose(settings, ticker=ticker, metric=metric, kicker=kicker,
                     size=TALL, orient="tall",
                     is_move=is_move).save(ws.path / "thumbnail_tall.png")
        return out
    except Exception:
        log.exception("thumbnail generation failed (non-fatal)")
        return None
