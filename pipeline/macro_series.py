"""The macro short's own chart: the official series behind the print (item 6).

A macro short is about one print, and the kit drew `charts/macro-series` for
exactly that: the series the print belongs to, over decades, with the
recessions shaded behind it. Nothing filled it. The figures are FRED's,
read off its public CSV (no key, no cost), and the series is picked from
what the script says the video is about: a CPI headline gets CPI, a jobs
headline the unemployment rate.

Nothing here writes a word. The line, the shading, the axis and the latest
reading are FRED's; the source line names the series so anyone can check
it, which the plate's own note says is required. A headline that names no
series we know leaves the beat its headline band.
"""
from __future__ import annotations

import csv
import io
import logging
import math
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

log = logging.getLogger(__name__)

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv"
# The plate labels ten ticks evenly across the plot, so the window is nine
# equal steps: 27 years, a tick every three, which spans the last three
# recessions.
TICKS = 10
STEP_YEARS = 3
WINDOW_YEARS = STEP_YEARS * (TICKS - 1)
MAX_BANDS = 4
CACHE_TTL_S = 12 * 3600
# The source line's box (`maxChars` 74) and the kicker's (26).
SOURCE_CHARS = 74
KICKER_CHARS = 26


@dataclass(frozen=True)
class Series:
    """One FRED series as the chart prints it."""

    words: tuple[str, ...]       # what in a headline names it
    fred_id: str
    transformation: str          # FRED's own: "" as published, "pc1" % a year
    kicker: str
    unit: str
    suffix: str                  # how an axis label and the reading print
    note: str                    # how the source line describes it


# Most specific first: "core CPI" is not the CPI.
SERIES = (
    Series(("core cpi", "core inflation"), "CPILFESL", "pc1",
           "US CORE CPI · YEAR ON YEAR", "% a year", "%",
           "change from a year ago"),
    Series(("pce",), "PCEPI", "pc1", "US PCE INFLATION", "% a year",
           "%", "change from a year ago"),
    Series(("cpi", "inflation", "consumer price"), "CPIAUCSL", "pc1",
           "US CPI · YEAR ON YEAR", "% a year", "%", "change from a year ago"),
    Series(("unemployment", "jobless", "payroll", "jobs report", "nonfarm",
            "labor market", "labour market"), "UNRATE", "",
           "US UNEMPLOYMENT RATE", "% of workforce", "%",
           "monthly, seasonally adjusted"),
    Series(("fed funds", "fomc", "rate cut", "rate hike", "the fed ",
            "interest rate"), "FEDFUNDS", "", "FED FUNDS RATE", "monthly avg",
           "%", "monthly average"),
    Series(("10-year", "ten-year", "treasury", "bond yield"), "GS10", "",
           "10-YEAR TREASURY YIELD", "monthly avg", "%", "monthly average"),
    Series(("gdp",), "A191RL1Q225SBEA", "", "US REAL GDP GROWTH",
           "annualised", "%", "quarterly, annualised"),
    Series(("oil", "crude", "wti"), "MCOILWTICO", "", "WTI CRUDE OIL",
           "$ a barrel", "$", "monthly average"),
)


def pick(script) -> Series | None:
    """The series the script's own headline, hook or move names, or None."""
    heads = " ".join(str(getattr(h, "text", h) or "")
                     for h in (getattr(script, "headlines", None) or []))
    said = " ".join([heads, str(getattr(script, "move_summary", "") or ""),
                     str(getattr(script, "hook_text", "") or "")]).lower()
    said = f" {said} "
    for s in SERIES:
        if any(w in said for w in s.words):
            return s
    return None


# ---------------------------------------------------------------------------
# Reading FRED
# ---------------------------------------------------------------------------

def _name(fred_id: str, transformation: str) -> str:
    return f"{fred_id}_{transformation}" if transformation else fred_id


def _parse(text: str) -> list[tuple[date, float]]:
    rows = []
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 2 or not row[0][:1].isdigit():
            continue
        try:
            rows.append((date.fromisoformat(row[0][:10]), float(row[1])))
        except ValueError:
            continue                    # "." is FRED's missing value
    return rows


def fetch(fred_id: str, settings, transformation: str = ""
          ) -> list[tuple[date, float]] | None:
    """The series as `(date, value)` oldest first, or None. Never raises.

    MOCK_MODE (prices mocked) reads fixtures/fred/<ID>[_<t>].csv only.
    """
    name = _name(fred_id, transformation)
    if settings.mocking_prices:
        f = Path(settings.fixtures_dir) / "fred" / f"{name}.csv"
        return (_parse(f.read_text(encoding="utf-8")) or None) if f.exists() else None
    cache = Path(settings.cache_dir) / "fred" / f"{name}.csv"
    try:
        if cache.exists() and time.time() - cache.stat().st_mtime < CACHE_TTL_S:
            return _parse(cache.read_text(encoding="utf-8")) or None
    except OSError:
        pass
    try:
        import httpx

        params = {"id": fred_id}
        if transformation:
            params["transformation"] = transformation
        r = httpx.get(FRED_CSV, params=params, timeout=30.0,
                      follow_redirects=True)
        r.raise_for_status()
        rows = _parse(r.text)
    except Exception as e:                               # noqa: BLE001
        log.warning("FRED %s could not be read (%s); no macro chart", name, e)
        return None
    if not rows:
        return None
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(r.text, encoding="utf-8")
    return rows


# ---------------------------------------------------------------------------
# The card
# ---------------------------------------------------------------------------

def _years_before(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year - years)
    except ValueError:                  # 29 February
        return d.replace(year=d.year - years, day=28)


def nice_axis(lo: float, hi: float, n: int = 5) -> list[float]:
    """`n` evenly spaced round labels covering lo..hi, bottom first."""
    span = max(hi - lo, 1e-9)
    mag = 10 ** math.floor(math.log10(span / (n - 1)))
    for k in (1, 2, 2.5, 3, 4, 5, 10, 20, 25, 30, 40, 50):
        step = k * mag
        start = math.floor(lo / step + 1e-9) * step
        if start + step * (n - 1) >= hi - 1e-9:
            return [round(start + step * i, 6) for i in range(n)]
    step = 100 * mag
    start = math.floor(lo / step) * step
    return [start + step * i for i in range(n)]


def _label(v: float, suffix: str) -> str:
    txt = f"{v:g}" if abs(v - round(v)) > 1e-9 else f"{round(v):d}"
    return f"${txt}" if suffix == "$" else f"{txt}{suffix}"


def _reading(v: float, suffix: str) -> str:
    return f"${v:,.2f}" if suffix == "$" else f"{v:.1f}{suffix}"


def recession_bands(rec: list[tuple[date, float]], start: date, end: date
                    ) -> list[tuple[float, float]]:
    """NBER recessions (USREC = 1) inside the window, as plot fractions."""
    span = (end - start).days or 1
    runs, began = [], None
    for d, v in rec:
        if v >= 0.5 and began is None:
            began = d
        elif v < 0.5 and began is not None:
            runs.append((began, d))
            began = None
    if began is not None:
        runs.append((began, end))
    out = []
    for a, b in runs:
        if b <= start or a >= end:
            continue
        a, b = max(a, start), min(b, end)
        out.append(((a - start).days / span, (b - start).days / span))
    return out[-MAX_BANDS:]


def card(script, settings) -> dict[str, str] | None:
    """`charts/macro-series`, filled from FRED for this script's print."""
    s = pick(script)
    if s is None:
        return None
    rows = fetch(s.fred_id, settings, s.transformation)
    if not rows or len(rows) < 24:
        return None
    end = rows[-1][0]
    start = _years_before(end, WINDOW_YEARS)
    window = [(d, v) for d, v in rows if d >= start]
    if len(window) < 24:
        return None
    values = [v for _d, v in window]
    ticks = nice_axis(min(values), max(values))
    out = {
        "kicker": s.kicker[:KICKER_CHARS],
        "unit": s.unit,
        "series": ",".join(f"{v:.2f}" for v in values),
        "caption": f"Latest: {_reading(values[-1], s.suffix)} in {end:%B %Y}",
    }
    for i, t in enumerate(ticks, start=1):
        out[f"y-{i}"] = _label(t, s.suffix)
    for i in range(TICKS):
        out[f"head-{i + 1}"] = str(start.year + STEP_YEARS * i)
    rec = fetch("USREC", settings)
    bands = recession_bands(rec, window[0][0], end) if rec else []
    for i, (a, b) in enumerate(bands, start=1):
        out[f"band-{i}"] = f"{a:.4f},{b:.4f}"
    source = f"FRED: {s.fred_id}, {s.note}"
    shaded = f"{source}; shaded: recessions (USREC)"
    out["source"] = shaded if bands and len(shaded) <= SOURCE_CHARS else source
    return out


# The headline CPI is reported off the unadjusted index and FRED's change
# from a year ago off the adjusted one, so the two can differ by a tenth.
PRINT_TOLERANCE = 0.15


def print_check(script, settings) -> str | None:
    """A warning when the script's print and FRED's latest reading differ.

    Before approval and never blocking: FRED may not carry a print released
    this morning yet, so a mismatch is something to look at, not a refusal.
    """
    s = pick(script)
    if s is None:
        return None
    said = str(getattr(script, "reported", "") or "")
    try:
        claimed = float(said.replace("$", "").replace("%", "").replace(",", "").strip())
    except ValueError:
        return None
    rows = fetch(s.fred_id, settings, s.transformation)
    if not rows:
        return None
    when, latest = rows[-1]
    if abs(claimed - latest) <= PRINT_TOLERANCE:
        return None
    return (f"the script's print is {said}, and FRED's latest {s.fred_id} "
            f"({s.note}) is {_reading(latest, s.suffix)} for {when:%B %Y}. "
            f"FRED can lag a release by a day; check the figure before approving")
