"""The peer percentiles, on screen at last.

`company_data.py` has read a ``peer_percentiles`` block off the Peers sheet for
as long as the export has existed — metric, the subject's figure, the peer
median, the percentile, and a plain-text read ("expensive vs peers") — and
nothing has ever displayed it. It reached the writing prompt as text and stopped
there, so the most quotable comparison in the dataset was something the
voice-over could assert and the frame could not show.

``peers/peer-strip-16x9`` and ``-9x16`` are the plates for it. The strip is a
ledger: a heavy rule under the heads, a closing rule at the foot, a divide
between label and figures, a dashed rail per row, and a `bars` region that
`series.rowBars` fills with the move as a shape on one scale shared across the
rows.

Two things about it are decided by the plate and must not be re-decided here:

* **The subject's ticker is `structure` and every peer's is `other-party`**, so
  the row you are in is legible with no highlight at all — which is what keeps
  `band-N` free for the row the voice-over is actually on.
* **Emphasis is in the plate, not the caller.** The move is the largest figure,
  the multiple second, the ticker smallest, because a ticker is a label and not
  a number.

An empty cell means NO DATA. The script that prompted this plate named Micron,
SK Hynix and WDC and priced none of them, and the honest render of that is seven
empty cells — not seven invented numbers.
"""

from __future__ import annotations

import logging
import re

from pipeline.plates import Plate, Registry

log = logging.getLogger(__name__)

# How many rows each aspect holds. Portrait cannot carry five at a legible move
# size: cut rows, never columns.
ROWS = {"16x9": 5, "9x16": 4}

# The ticker column is SEVEN characters — a ticker is what it was drawn for, and
# `maxChars` is a hard limit in this kit rather than a hint: over it, the line
# collides with rules drawn in ink. So a metric name going in that column is
# abbreviated, and abbreviated deliberately rather than truncated, because
# "Gross m" is not a label anybody reads.
METRIC_SHORT = {
    "ev/sales": "EV/S",
    "ev/ebitda": "EV/EBI",
    "ev/ebit": "EV/EBIT",
    "p/e": "P/E",
    "forward p/e": "FWD P/E",
    "price/book": "P/B",
    "gross margin": "GM",
    "operating margin": "OP M",
    "net margin": "NET M",
    "fcf margin": "FCF M",
    "revenue growth": "REV GR",
    "net debt/ebitda": "ND/EBI",
    "roic": "ROIC",
    "roe": "ROE",
    "dividend yield": "DIV Y",
    "buyback yield": "BUYBK",
    "short interest": "SHORT",
}


def _short(metric: str, limit: int) -> str:
    """A metric name that fits the column the plate reserved for it."""
    name = str(metric or "").strip()
    if not name:
        return ""
    short = METRIC_SHORT.get(name.lower())
    if short:
        return short[:limit]
    if len(name) <= limit:
        return name.upper()
    # Initials, which stay readable where a truncation does not: "Free cash
    # flow margin" -> "FCFM", not "Free ca".
    words = [w for w in re.split(r"[^A-Za-z0-9/]+", name) if w]
    if len(words) > 1:
        initials = "".join(w[0] for w in words).upper()
        if len(initials) <= limit:
            return initials
    return name.upper()[:limit]


def _pct(value) -> str:
    """`0.9` -> `90th`. The percentile is a fraction in the export."""
    try:
        n = float(value)
    except (TypeError, ValueError):
        return ""
    n = n * 100 if n <= 1.0 else n
    i = int(round(n))
    suffix = ("th" if 10 <= i % 100 <= 20 else
              {1: "st", 2: "nd", 3: "rd"}.get(i % 10, "th"))
    return f"{i}{suffix}"


def strip_values(data, *, ticker: str, aspect: str = "16x9",
                 metric: str = "") -> dict[str, str]:
    """Slot values for a `peers/peer-strip`, from the export's own block.

    The subject goes in row one — the plate draws that row's ticker in
    `structure` — and the peer rows follow. Nothing here computes a figure: it
    reads the percentile block the export already carries.
    """
    rows = list(getattr(data, "peer_percentiles", None) or
                (data or {}).get("peer_percentiles", []) or [])
    if not rows:
        return {}

    # Which metric leads. It supplies the caption; the rows carry the rest.
    chosen = None
    if metric:
        chosen = next((r for r in rows
                       if str(r.get("metric", "")).lower() == metric.lower()), None)
    if chosen is None:
        chosen = rows[0]
    # The caption is the export's own plain-text read of the headline metric —
    # "expensive vs peers". Written by the sheet, not by this code.

    n = ROWS.get(aspect, 5)
    # ONE ROW PER METRIC: the subject's own figure against where it sits in the
    # peer distribution. That is the shape the export holds — it carries no
    # per-peer figures at all — and inventing five peer names to fill a strip
    # drawn for them would be exactly the "renderer computes a value" the whole
    # pivot removes.
    values: dict[str, str] = {
        "unit": f"{ticker.upper()} against its peer set",
        "head-move": "SUBJECT",
        "head-fwd": "PCTILE",
        "caption": str(chosen.get("read") or ""),
    }
    bars: list[str] = []
    for i, row in enumerate(rows[:n], start=1):
        values[f"ticker-{i}"] = _short(row.get("metric"), 7)
        values[f"move-{i}"] = _fmt(row.get("subject"))
        values[f"fwd-{i}"] = _pct(row.get("percentile"))
        bars.append(_bar(row.get("percentile")))

    # THE BARS ARE THE PERCENTILES, not the subject figures beside them.
    #
    # The plate's `bars` region draws the `move` column when nobody says
    # otherwise, which is right on the movers strip this plate was drawn for:
    # five tickers, one unit, five price moves. Here every row is a different
    # metric — a multiple, a margin, a growth rate — and a bar chart across
    # those has no common axis to be long or short against. It came out as
    # four blobs where the widest was a 60% margin and the 90th-percentile
    # valuation was a smudge. A percentile is 0 to 100 for every row, which is
    # the whole reason the export carries it.
    if any(b for b in bars):
        values["bars"] = ",".join(bars)
    return values


def _bar(value) -> str:
    """A percentile as a bar length, or empty when there is none."""
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return ""


def _fmt(value) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, (int, float)):
        return f"{value:,.1f}".rstrip("0").rstrip(".")
    return str(value)


def render(reg: Registry, data, settings, *, ticker: str,
           aspect: str = "16x9", metric: str = ""):
    """The peer strip, filled and with its bars drawn. None when there is no data."""
    from pipeline.chart import draw_row_bars, plot_area
    from pipeline.plate_frames import render_still

    values = strip_values(data, ticker=ticker, aspect=aspect, metric=metric)
    if not values:
        return None
    key = reg.aspect_key("peers/peer-strip", aspect)
    if key is None:
        return None
    plate: Plate = reg.require(key)
    img = render_still(plate, values, settings, reg)

    # The bars are DATA and the plate reserves the column for them. They are
    # the PERCENTILES the rows already carry, on one 0-to-100 axis — see
    # `strip_values`. Reading the `move` column instead put a 60% margin and a
    # 7.8x multiple on the same axis, and the widest bar on the strip was
    # whichever row happened to be quoted in the largest units.
    area = plot_area(plate, "bars")
    if area is not None:
        n = ROWS.get(aspect, 5)
        written = [v for v in str(values.get("bars", "")).split(",") if v != ""]
        series: list[float | None] = []
        for i in range(n):
            raw = written[i] if i < len(written) else ""
            try:
                series.append(float(str(raw).replace(",", "").replace("%", "")))
            except ValueError:
                series.append(None)
        # NEUTRAL DATA, not direction. A percentile has no direction: being in
        # the 90th on price is not "up" and the 5th on FCF margin is not
        # "down", however bad the story about either is. up/down are direction
        # ONLY, and colouring a distribution by sign is the exact misuse the
        # eight roles exist to prevent.
        neutral = reg.colour("neutral-data")
        draw_row_bars(img, area, series, lambda v: neutral, seed=plate.key)
    return img
