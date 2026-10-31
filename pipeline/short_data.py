"""What a SHORT's cards say when the operator's workbook is in the workspace.

A short used to be drawn from the script alone. The writer typed six figures a
row, the payoff card took the first row whatever the verdict was about, the
cheap-or-trap card read "Revenue is $496M now. It was $400M." because no row
looked like a multiple, and the workbook the operator filled for this very
video (History, Quarters, Valuation, the Snapshot's 52-week range and short
interest, the News sheet) reached the prompt and the fact-check and never the
screen.

Everything here reads that workbook and returns the words and figures a card's
slots take. It composes nothing and places nothing: `render_short.ShortResolver`
asks, and the shot template decides where the answer goes. Every figure is the
workbook's own, formatted for a phone; the few that are worked out here (a
change between two periods, days to cover, a quarter's gap to consensus) are
arithmetic on two of the workbook's numbers, and the card says what they are.

Nothing here raises for missing data. A card with nothing to say returns None
for its slots, the plate is then not fillable, and the rotation draws another.
"""

from __future__ import annotations

import datetime as _dt
import logging
import math
import re
from typing import Any

from pipeline.models import RATE_FIELDS, quarter_words

log = logging.getLogger(__name__)

# What each History row is called on screen. The workbook's own labels are a
# spreadsheet's ("Stock-Based Comp", "Net Debt / EBITDA"); these are the ones a
# card has room for.
FIELD_LABELS: dict[str, str] = {
    "revenue": "Revenue",
    "gross_profit": "Gross profit",
    "gross_margin": "Gross margin",
    "operating_income": "Operating income",
    "operating_margin": "Operating margin",
    "ebitda": "EBITDA",
    "net_income": "Net income",
    "net_margin": "Net margin",
    "operating_cf": "Operating cash flow",
    "capex": "Capex",
    "fcf": "Free cash flow",
    "fcf_margin": "FCF margin",
    "sbc": "Stock comp",
    "sbc_pct_rev": "Stock comp, % of revenue",
    "dividends_paid": "Dividends paid",
    "buybacks": "Buybacks",
    "cash": "Cash",
    "total_debt": "Total debt",
    "net_debt": "Net debt",
    "total_equity": "Equity",
    "total_assets": "Total assets",
    "invested_capital": "Invested capital",
    "net_debt_ebitda": "Net debt / EBITDA",
    "eps": "EPS",
    "fcf_ps": "FCF per share",
    "bvps": "Book value per share",
    "roic": "ROIC",
    "roe": "ROE",
    "diluted_shares": "Share count",
    "shares_yoy": "Share count change",
}

# THE SHORTER NAME, for a slot too narrow for the long one (item 25). A label
# that did not fit was dropped and the row printed with no name; the kit's own
# notes say to shorten it.
SHORT_LABELS: dict[str, str] = {
    "free cash flow": "FCF",
    "operating cash flow": "Op. cash flow",
    "operating income": "Op. income",
    "operating margin": "Op. margin",
    "net income": "Net income",
    "gross margin": "Gross margin",
    "share count": "Shares",
    "shares outstanding": "Shares",
    "diluted shares": "Shares",
    "stock-based comp": "Stock comp",
    "stock based compensation": "Stock comp",
    "book value per share": "Book/share",
    "fcf per share": "FCF/share",
    "net debt / ebitda": "Debt/EBITDA",
    "invested capital": "Inv. capital",
    "dividends paid": "Dividends",
}


def abbreviate(label: str, limit: int) -> str | None:
    """`label` cut to fit `limit` characters the way an editor would, or None.

    The table of short names first, then the usual contractions. Never a
    truncation mid-word: "Free cash fl" is worse than no label, and a label
    that cannot be shortened honestly is still dropped.
    """
    text = " ".join(str(label or "").split())
    if not text or len(text) <= limit:
        return text or None
    got = SHORT_LABELS.get(text.lower())
    if got and len(got) <= limit:
        return got
    for long, short in (("operating", "op."), ("revenue", "rev."),
                        ("per share", "/share"), ("margin", "mgn"),
                        ("income", "inc."), (" and ", " & ")):
        text = re.sub(long, short, text, flags=re.I)
        if len(text) <= limit:
            return text
    return None


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9/%]+", " ", str(text or "").lower()).strip()


# Label -> History field_key, for a row the writer named by its label only.
_ALIASES: dict[str, str] = {
    "sales": "revenue", "net sales": "revenue", "total revenue": "revenue",
    "revenues": "revenue",
    "net loss": "net_income", "net income loss": "net_income",
    "net earnings": "net_income", "earnings": "net_income",
    "fcf": "fcf", "free cash flow": "fcf",
    "shares": "diluted_shares", "shares out": "diluted_shares",
    "share count": "diluted_shares", "diluted shares": "diluted_shares",
    "shares outstanding": "diluted_shares", "diluted share count": "diluted_shares",
    "operating loss": "operating_income", "ebit": "operating_income",
    "cash from operations": "operating_cf", "operating cash flow": "operating_cf",
    "capital expenditures": "capex", "capital expenditure": "capex",
    "stock based comp": "sbc", "stock based compensation": "sbc",
    "stock comp": "sbc", "sbc": "sbc",
    "eps diluted": "eps", "diluted eps": "eps", "eps": "eps",
    "book value share": "bvps", "book value per share": "bvps",
    "net debt ebitda": "net_debt_ebitda", "leverage": "net_debt_ebitda",
    "debt": "total_debt", "equity": "total_equity",
    "dividends": "dividends_paid", "buyback": "buybacks",
}


def field_for(label: str, field: str | None = None) -> str | None:
    """The History field_key a sheet row names, or None."""
    from pipeline.models import HISTORY_FIELDS

    if field and field in HISTORY_FIELDS:
        return field
    key = _norm(label)
    if not key:
        return None
    if key.replace(" ", "_") in HISTORY_FIELDS:
        return key.replace(" ", "_")
    for f, lab in FIELD_LABELS.items():
        if _norm(lab) == key:
            return f
    return _ALIASES.get(key)


# ---------------------------------------------------------------------------
# Formatting a workbook figure for a phone
# ---------------------------------------------------------------------------

_PER_SHARE = frozenset({"eps", "fcf_ps", "bvps", "eps_consensus", "eps_street"})
_COUNT = frozenset({"diluted_shares"})
_MULTIPLE = frozenset({"net_debt_ebitda"})


def _sig(x: float) -> str:
    """Three significant figures, no trailing zeros: 496, 45.2, 1.23."""
    if x == 0:
        return "0"
    digits = max(0, 2 - int(math.floor(math.log10(abs(x)))))
    text = f"{x:.{digits}f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def money(v: float, *, currency: str = "$") -> str:
    """`496000000` -> `$496M`; `-89000000` -> `-$89M`; `1.23e9` -> `$1.23B`."""
    # Rounded to the three figures it prints BEFORE the suffix is chosen:
    # $999.6M used to print as "$1000M".
    a = float(f"{abs(v):.3g}")
    sign = "-" if v < 0 and a else ""
    for div, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= div:
            return f"{sign}{currency}{_sig(a / div)}{suffix}"
    return f"{sign}{currency}{_sig(a)}"


def count(v: float) -> str:
    """`364600000` -> `365M`."""
    return money(v, currency="")


def rate(v: float) -> str:
    """A percentage the workbook holds as a percent: `58.0` -> `58%`."""
    # Rounded first, so -0.04 is "0%" rather than "-0.0%" and 9.96 is "10%"
    # rather than "10.0%".
    r = round(v, 1)
    if r == 0:
        return "0%"
    return f"{r:.1f}%" if abs(r) < 10 and r != int(r) else f"{r:.0f}%"


def per_share(v: float) -> str:
    sign = "-" if v < 0 else ""
    return f"{sign}${abs(v):.2f}"


def fmt(field: str, v: float | None) -> str:
    """One workbook figure as a card prints it; "" for no data."""
    if v is None:
        return ""
    if field in RATE_FIELDS:
        return rate(v)
    if field in _PER_SHARE:
        return per_share(v)
    if field in _COUNT:
        return count(v)
    if field in _MULTIPLE:
        return f"{v:.1f}x"
    return money(v)


def change(field: str, first: float | None, last: float | None) -> str | None:
    """How far a row moved between two periods, as a card prints it.

    A rate moves in POINTS: a margin from 58 to 52 is "-6 pts", never a
    percentage change of a percentage. A quantity that crosses zero or starts
    at zero has no honest percentage either, so it gets none; nor does a loss,
    because a loss from $8M to $89M printed "-1012%", which reads as the
    opposite of what happened.
    """
    if first is None or last is None:
        return None
    if field in RATE_FIELDS:
        d = last - first
        return f"{d:+.0f} pts" if abs(d) >= 1 else f"{d:+.1f} pts"
    if first <= 0 or last < 0:
        return None
    pct = (last - first) / abs(first) * 100.0
    return f"{pct:+.0f}%"


# ---------------------------------------------------------------------------
# Periods
# ---------------------------------------------------------------------------

_RELATIVE_FY = re.compile(r"^FY\s*-\s*(\d+)$", re.I)


def year_labels(data, script_years: list[str] | None = None) -> list[str]:
    """The six period heads a card prints under the History figures.

    The writer's `years` when it gave six (it read them off the table in the
    prompt); else the workbook's own headers, which name real years once the
    sheet carries its `fiscal_year` row. A template still on relative headers
    (`FY-4`) gets them turned into years off `as_of_date`: the last full year
    is the one before the as-of year. That guess is right for a December year
    end and a year early for a company whose year closed between January and
    the as-of date, so it is used only where nothing better exists.
    """
    if script_years and len(script_years) == len(getattr(data, "history_years", []) or script_years):
        return list(script_years)
    heads = list(getattr(data, "history_years", []) or [])
    if not heads:
        return list(script_years or [])
    as_of = str((data.get("as_of_date") if hasattr(data, "get") else "") or "")
    try:
        year = _dt.date.fromisoformat(as_of[:10]).year
    except ValueError:
        year = None
    out = []
    for h in heads:
        m = _RELATIVE_FY.match(h.strip())
        if m and year is not None:
            out.append(f"FY{(year - 1 - int(m.group(1))) % 100:02d}")
        else:
            out.append(h)
    return out


_RELATIVE_Q = re.compile(r"^Q\s*-\s*(\d+)$", re.I)
_RELATIVE_QFY = re.compile(r"^Q([1-4])\s*FY\s*-\s*(\d+)$", re.I)


def _as_of_year(data) -> int | None:
    as_of = str((data.get("as_of_date") if hasattr(data, "get") else "") or "")
    try:
        return _dt.date.fromisoformat(as_of[:10]).year
    except ValueError:
        return None


def _real_quarter_labels(data) -> list[str]:
    """The Quarters sheet's column names, with relative years made real.

    `Q3 FY25` stays; `Q3 FY-1` becomes `Q3 FY24` off `as_of_date`, the same
    guess `year_labels` makes; a bare `Q-7` stays as it is.
    """
    year = _as_of_year(data)
    out = []
    for h in list(getattr(data, "quarter_labels", []) or []):
        m = _RELATIVE_QFY.match(h.strip())
        if m and year is not None:
            out.append(f"Q{m.group(1)} FY{(year - 1 - int(m.group(2))) % 100:02d}")
        else:
            out.append(h.strip())
    return out


def quarter_labels(data) -> list[str]:
    """The quarter columns as a card prints them.

    A bare `Q-0` is a position, so it reads as the latest quarter, the prior
    quarter or so many quarters back (`quarter_words`), never as `Q-0`.
    """
    return [quarter_words(h) for h in _real_quarter_labels(data)]


def quarter_heads(data) -> list[str]:
    """Each quarter's head as a card prints it (7 characters at most).

    `Q2 FY25` becomes `Q2 '25`, and a quarter named by its end, `qtr to Sep
    '26`, becomes `Sep '26`. A sheet still on relative headers (`Q-7`) gets
    `-7Q`…`LATEST`, which is what those columns are, rather than a date the
    workbook never gave.
    """
    out = []
    for h in _real_quarter_labels(data):
        m = re.match(r"^Q([1-4])\s*FY\s*(\d{2,4})$", h.strip(), re.I)
        if m:
            out.append(f"Q{m.group(1)} '{m.group(2)[-2:]}")
            continue
        r = _RELATIVE_Q.match(h.strip())
        if r:
            n = int(r.group(1))
            out.append("LATEST" if n == 0 else f"-{n}Q")
            continue
        e = re.match(r"^qtr to (\w{3} '\d{2})$", h.strip(), re.I)
        if e:
            out.append(e.group(1))
            continue
        out.append(h.strip()[:7])
    return out


# ---------------------------------------------------------------------------
# The sheet rows, from the History sheet (item 23)
# ---------------------------------------------------------------------------

def history_values(data, field: str) -> list[float | None] | None:
    """A History row, or None when the workbook has fewer than two figures."""
    if data is None or not field:
        return None
    vals = list((getattr(data, "history", {}) or {}).get(field) or [])
    if sum(1 for v in vals if v is not None) < 2:
        return None
    return vals


# A period head that names a quarter: `Q3 FY26`, `Q3 '26`, `Q3 2026`, `3Q26`.
_QUARTER_HEAD = re.compile(
    r"^(?:Q[1-4]\s*(?:FY)?\s*'?\d{2}(?:\d{2})?|[1-4]Q\s*'?\d{2}(?:\d{2})?)$", re.I)


def is_quarterly(script, data=None) -> bool:
    """Whether a SHORT's sheet is quarters rather than years.

    An EARNINGS short reads the quarter against the same quarter a year
    earlier (Valentin, 30 Oct 2026: "it should've compared year to year,
    revenue by quarters, not the revenue from 2021 onwards"), so its writer
    sets `years` to the last six quarter heads of the Quarters table. Told by
    those heads: the workbook's own last six, or six heads that each name a
    quarter.
    """
    years = [str(y).strip() for y in getattr(script, "years", []) or []]
    if len(years) < 2:
        return False
    if data is not None:
        labels = quarter_labels(data)
        if len(labels) >= len(years) and years == labels[-len(years):]:
            return True
    return all(_QUARTER_HEAD.match(y) for y in years)


def year_ago_index(values: list, years: list[str] | None = None,
                   quarterly: bool | None = None) -> int | None:
    """Which column a row's latest figure is compared with.

    On a quarterly sheet the same quarter a year earlier, four columns back:
    the quarter before it is a seasonal comparison, and the first column is
    six quarters ago, which is neither. On an annual sheet the first figure
    the row has, as it always was. None when there is nothing to compare.
    """
    cells = [str(v).strip() for v in values]
    last = next((k for k in range(len(cells) - 1, -1, -1) if cells[k]), None)
    if last is None:
        return None
    if quarterly is None:
        quarterly = bool(years) and all(
            _QUARTER_HEAD.match(str(y).strip()) for y in years)
    if quarterly:
        k = last - 4
        return k if k >= 0 and cells[k] else None
    first = next((k for k, c in enumerate(cells) if c), None)
    return first if first is not None and first != last else None


def quarter_values(data, field: str, n: int) -> list[float | None] | None:
    """The last `n` quarters of a Quarters row, or None with fewer than two."""
    if data is None or not field:
        return None
    vals = list((getattr(data, "quarters", {}) or {}).get(field) or [])[-n:]
    if len(vals) != n or sum(1 for v in vals if v is not None) < 2:
        return None
    return vals


def fill_numbers(script, data) -> tuple[Any, list[str]]:
    """`script` with every sheet row it can match taken from the workbook.

    The writer names the rows; the figures on screen are the History sheet's,
    so the sheet cannot disagree with the workbook — or the Quarters sheet's,
    for an earnings short whose heads are quarters. A row that names no field
    and whose label matches none keeps the figures typed for it, and is
    reported. Returns `(script, notes)`; the script is a copy.
    """
    rows = list(getattr(script, "numbers", []) or [])
    if data is None or not rows:
        return script, []
    if is_quarterly(script, data):
        return _fill_quarters_rows(script, data, rows)
    if not getattr(data, "has_history", False):
        return script, []
    heads = year_labels(data, list(getattr(script, "years", []) or []))
    notes: list[str] = []
    new_rows = []
    for row in rows:
        f = field_for(row.label, getattr(row, "field", None))
        vals = history_values(data, f) if f else None
        if vals is None or len(vals) != len(heads):
            if f is None:
                notes.append(f"{row.label}: no workbook row by that name; "
                             f"the typed figures are shown")
            new_rows.append(row)
            continue
        figures = [fmt(f, v) for v in vals]
        typed = [str(x).strip() for x in row.values]
        if typed and any(t and t != g for t, g in zip(typed, figures)):
            notes.append(f"{row.label}: shown from the workbook "
                         f"({', '.join(g for g in figures if g)}) instead of "
                         f"the typed {', '.join(t for t in typed if t)}")
        new_rows.append(row.model_copy(update={"values": figures, "field": f}))
    update: dict = {"numbers": new_rows}
    if len(heads) == len(new_rows[0].values) and heads != list(script.years or []):
        update["years"] = heads
    return script.model_copy(update=update), notes


def _fill_quarters_rows(script, data, rows) -> tuple[Any, list[str]]:
    """`fill_numbers` for a sheet of quarters: the Quarters sheet's figures
    under the workbook's own quarter heads."""
    if not getattr(data, "has_quarters", False):
        return script, ["the sheet is quarters and the workbook has no "
                        "Quarters sheet: the typed figures are shown"]
    n = len(getattr(script, "years", []) or [])
    heads = quarter_labels(data)[-n:]
    notes: list[str] = []
    new_rows = []
    for row in rows:
        f = field_for(row.label, getattr(row, "field", None))
        vals = quarter_values(data, f, n) if f else None
        if vals is None:
            notes.append(f"{row.label}: no quarterly row by that name in the "
                         f"workbook; the typed figures are shown")
            new_rows.append(row)
            continue
        figures = [fmt(f, v) for v in vals]
        typed = [str(x).strip() for x in row.values]
        if typed and any(t and t != g for t, g in zip(typed, figures)):
            notes.append(f"{row.label}: shown from the workbook's quarters "
                         f"({', '.join(g for g in figures if g)}) instead of "
                         f"the typed {', '.join(t for t in typed if t)}")
        new_rows.append(row.model_copy(update={"values": figures, "field": f}))
    update: dict = {"numbers": new_rows}
    if len(heads) == n and heads != list(script.years or []):
        update["years"] = heads
    return script.model_copy(update=update), notes


def row_for(script, name: str | None):
    """The sheet row a name picks (label or field_key), or None."""
    if not name:
        return None
    rows = list(getattr(script, "numbers", []) or [])
    want = _norm(name)
    for r in rows:
        if _norm(r.label) == want:
            return r
    f = field_for(name)
    for r in rows:
        if f and field_for(r.label, getattr(r, "field", None)) == f:
            return r
    return None


# ---------------------------------------------------------------------------
# A one-metric card (item 26)
# ---------------------------------------------------------------------------

def _nice_step(span: float) -> float:
    raw = span / 4.0
    if raw <= 0:
        return 1.0
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 1.25, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if raw <= m * mag:
            return m * mag
    return 10 * mag


def axis_ticks(values: list[float], headroom: float = 0.0) -> list[float]:
    """Five evenly spaced gridline values that hold every bar and zero.

    `headroom` is how much of the scale above the tallest bar stays empty, as
    a share of the bars' span: 1/3 keeps the tallest bar at three quarters of
    the top gridline or lower. A short's metric card asks for it so its
    caption has a clear row between the figures printed along the top and
    the bars (30 Oct 2026: on a card whose tallest bar reached the top
    gridline, the caption went over the bars).
    """
    lo, hi = min([0.0] + values), max([0.0] + values)
    if hi == lo:
        hi = lo + 1.0
    if headroom > 0 and hi > 0:
        hi += (hi - lo) * headroom
    step = _nice_step(hi - lo)
    base = math.floor(lo / step) * step
    ticks = [base + i * step for i in range(5)]
    while ticks[-1] < hi - 1e-9:
        step = _nice_step((hi - base) * 1.25)
        base = math.floor(lo / step) * step
        ticks = [base + i * step for i in range(5)]
    return ticks


def parse_figure(text: str) -> float | None:
    from pipeline.series import figure

    return figure(text)


def tick_label(field: str | None, v: float, like: str = "") -> str:
    """An axis label in the same units as the printed figures beside it."""
    if field:
        text = fmt(field, v)
        return "$0" if text in ("$0", "-$0") else text
    # A typed row: follow the printed figures' own shape.
    cur = "$" if "$" in like else ""
    pct = "%" if like.strip().endswith("%") else ""
    if pct:
        return f"{v:g}%"
    if any(s in like.upper() for s in ("B", "M", "K")):
        return money(v, currency=cur)
    return f"{cur}{v:g}"


# ---------------------------------------------------------------------------
# The cards the workbook fills on its own
# ---------------------------------------------------------------------------

def _pct(frac: float) -> str:
    """A fraction as a percentage a card prints: 0.061 -> 6.1%, 0.15 -> 15%."""
    v = round(frac * 100.0, 1)
    if v == int(v) or abs(v) >= 10:
        return f"{v:.0f}%"
    return f"{v:.1f}%"


def _ticker(data, script=None) -> str:
    t = str((data.get("ticker") if data is not None else "") or "").strip()
    return (t or str(getattr(script, "ticker", "") or "")).upper()


def implied(data, script=None) -> dict[str, str] | None:
    """`structure/implied`: the growth today's price assumes, against what the
    business delivered (item 1). From the Valuation sheet's reverse DCF.

    The demand is `implied_growth` (WACC less the FCF yield on EV: the growth
    in free cash flow, every year, that makes today's price a fair one). The
    band is what the last four years delivered, free cash flow's CAGR and
    revenue's, both off the same sheet; with only one of them the band is that
    one figure's reach from zero. Nothing is shown when the sheet has no
    implied growth or nothing delivered to set it against.
    """
    if data is None:
        return None
    val = getattr(data, "valuation", {}) or {}
    ig = val.get("implied_growth")
    fcf = val.get("hist_fcf_cagr")
    rev = val.get("rev_cagr")
    if ig is None or (fcf is None and rev is None):
        return None
    delivered = [x for x in (fcf, rev) if x is not None]
    lo, hi = min(delivered), max(delivered)
    if len(delivered) == 1:
        lo, hi = min(0.0, lo), max(0.0, hi)
    top = max([ig, hi, 0.0])
    bottom = min([ig, lo, 0.0])
    step = 0.05
    axis_hi = math.ceil(top / step + 1e-9) * step or step
    axis_lo = math.floor(bottom / step - 1e-9) * step if bottom < 0 else 0.0
    said = _pct(fcf) if fcf is not None else _pct(rev)
    what = "free cash flow" if fcf is not None else "revenue"
    verb = "needs" if ig > (fcf if fcf is not None else rev) else "asks for only"
    out = {
        "kicker": f"{_ticker(data, script)} · what the price assumes",
        "statement": (f"The price {verb} {_pct(ig)} a year. The last four "
                      f"years of {what} did {said}."),
        "demand": f"{_pct(ig)} a year",
        "demand-label": "free cash flow growth today's price assumes, for good",
        "history-label": "what the last four years delivered",
        "axis-low": _pct(axis_lo),
        "axis-high": _pct(axis_hi),
        "marker": _pct(ig),
        "band": f"{_pct(lo)},{_pct(hi)}",
    }
    if fcf is not None and rev is not None:
        a, b = sorted([(fcf, "FCF"), (rev, "revenue")])
        out["history-low"] = f"{b_or(a)}"
        out["history-high"] = f"{b_or(b)}"
    else:
        out["history-low"] = _pct(lo)
        out["history-high"] = _pct(hi)
    return out


def b_or(pair) -> str:
    """`(0.045, "FCF")` -> `FCF 4.5% a year`."""
    return f"{pair[1]} {_pct(pair[0])} a year"


def week52(data, script=None) -> dict[str, str] | None:
    """`figures/52-week-position`: where the price sits in its year (item 4)."""
    if data is None:
        return None
    hi, lo = data.get("week52_high"), data.get("week52_low")
    now = data.get("price")
    try:
        hi, lo, now = float(hi), float(lo), float(now)
    except (TypeError, ValueError):
        return None
    if hi <= lo:
        return None
    from pipeline.chart import _price_text

    pos = (now - lo) / (hi - lo)
    off = (now / hi - 1.0) * 100.0
    # The cents go before a digit does: cut to length, $1,234.56 read
    # "$1,234.5" and $12,345.67 "$12,345.".
    return {
        "kicker": f"{_ticker(data, script)} · the last 52 weeks",
        "label-high": "52-week high",
        "figure-high": f"${_price_text(hi, 7)}",
        "label-now": (f"now, {abs(off):.0f}% below the high" if off <= -1
                      else "now, at the high"),
        "now": f"${_price_text(now, 8)}",
        "label-low": "52-week low",
        "figure-low": f"${_price_text(lo, 7)}",
        "band": "0,1",
        "marker": f"{min(max(pos, 0.0), 1.0):.3f}",
    }


# Short interest worth a card of its own: more than this share of the float.
SHORT_INTEREST_CARD = 0.10


def short_interest_share(data) -> float | None:
    """Short interest as a FRACTION of the float, or None.

    The template divides the add-in's percentage by 100 (`Snapshot!D49`), and
    the committed fixture carries it the same way. A value over 1 is still read
    as the percentage it plainly is, for a sheet filled in by hand.
    """
    if data is None:
        return None
    raw = data.get("short_interest")
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    return v / 100.0 if v > 1.0 else v


def short_interest(data, script=None) -> dict[str, str] | None:
    """`figures/short-interest`, only above 10% of the float (item 4)."""
    si = short_interest_share(data)
    if si is None or si <= SHORT_INTEREST_CARD:
        return None
    return {
        "kicker": f"{_ticker(data, script)} · short interest",
        "unit": "share of the float",
        "float-label": "the float",
        "short-label": f"{_pct(si)} sold short",
        "short": _pct(si),
    }


# ---------------------------------------------------------------------------
# Quarters (item 3)
# ---------------------------------------------------------------------------

def _quarter_row(data, field: str) -> list[float | None]:
    return list((getattr(data, "quarters", {}) or {}).get(field) or [])


def quarter_bars(data, field: str = "revenue", script=None) -> dict[str, str] | None:
    """`charts/quarter-bars-8q`: eight quarters of one row, this one last."""
    if data is None:
        return None
    vals = _quarter_row(data, field)[-8:]
    heads = quarter_heads(data)[-8:]
    if len(vals) < 8 or any(v is None for v in vals):
        return None
    name = FIELD_LABELS.get(field, field).upper()
    out = {"kicker": f"{name} · last 8 quarters"[:25],
           "unit": "USD" if field not in RATE_FIELDS else "%"}
    # The bars are drawn through the figures the plate prints under them
    # (`value-N`), so there is nothing to bind to the columns themselves.
    for i, (v, h) in enumerate(zip(vals, heads), start=1):
        out[f"head-{i}"] = h
        out[f"value-{i}"] = fmt(field, v)
    return out


def _yoy_pair(data, field: str) -> tuple[float, float] | None:
    vals = _quarter_row(data, field)
    if len(vals) < 5 or vals[-1] is None or vals[-5] is None:
        return None
    return vals[-5], vals[-1]


def three_lines(data, script=None) -> dict[str, str] | None:
    """`tables/three-lines`: revenue, margin and EPS against a year earlier."""
    if data is None:
        return None
    labels = quarter_labels(data)
    if len(labels) < 5:
        return None
    rows = [("revenue", "Revenue"), ("gross_margin", "Gross margin"),
            ("eps", "EPS")]
    got = [(f, lab, _yoy_pair(data, f)) for f, lab in rows]
    if any(p is None for _, _, p in got):
        return None
    out = {"kicker": f"{_ticker(data, script)} · {labels[-1]} vs a year before",
           "head-1": labels[-5], "head-2": labels[-1]}
    for i, (f, lab, (then, now)) in enumerate(got, start=1):
        out[f"label-{i}"] = lab
        out[f"cell-{i}-1"] = fmt(f, then)
        out[f"cell-{i}-2"] = fmt(f, now)
        moved = change(f, then, now)
        if moved:
            out[f"delta-{i}"] = moved
    return out


def qoq_yoy(data, field: str = "revenue", script=None) -> dict[str, str] | None:
    """`figures/qoq-yoy`: one row against last quarter and last year."""
    if data is None:
        return None
    vals = _quarter_row(data, field)
    labels = quarter_labels(data)
    if len(vals) < 5 or None in (vals[-1], vals[-2], vals[-5]):
        return None
    qoq, yoy = change(field, vals[-2], vals[-1]), change(field, vals[-5], vals[-1])
    if not qoq or not yoy:
        return None
    return {
        "kicker": f"{FIELD_LABELS.get(field, field)} · {labels[-1]}".upper()[:29],
        "figure": fmt(field, vals[-1]),
        "qoq-label": f"against the quarter before, {labels[-2]}",
        "qoq": qoq,
        "yoy-label": f"against the same quarter a year earlier, {labels[-5]}",
        "yoy": yoy,
    }


def print_vs_consensus(data, script=None) -> dict[str, str] | None:
    """`figures/print-vs-consensus`: the print and the street, one gap.

    EPS when the script's own print is a per-share figure or says nothing,
    revenue when it is an amount. The gap is the difference of the two
    workbook figures, in the print's units, labelled beat or miss.
    """
    got = data.consensus() if data is not None and hasattr(data, "consensus") else None
    if not got:
        return None
    typed = str(getattr(script, "reported", "") or "")
    want = "revenue" if re.search(r"\d\s*[MBK]\b", typed, re.I) else "eps"
    pair = got.get(want) or got.get("eps") or got.get("revenue")
    what = want if got.get(want) else ("eps" if got.get("eps") else "revenue")
    if not pair:
        return None
    reported, expected = pair
    field = "eps_street" if what == "eps" else "revenue"
    gap = reported - expected
    if what == "eps":
        delta = f"{'+' if gap >= 0 else '-'}${abs(gap):.2f}"
    else:
        delta = (f"{gap / abs(expected) * 100:+.1f}%" if expected else "")
    return {
        "kicker": f"{_ticker(data, script)} · "
                  f"{(quarter_labels(data) or [got['label']])[-1]}",
        "label": ("EPS, adjusted, against the analysts' average" if what == "eps"
                  else "revenue against the analysts' average"),
        "reported": fmt(field, reported),
        "expected-label": "expected",
        "expected": fmt(field, expected),
        "delta-label": "beat by" if gap >= 0 else "missed by",
        "delta": delta,
    }


# ---------------------------------------------------------------------------
# One session (item 4)
# ---------------------------------------------------------------------------

# `charts/intraday` draws seven points, one a column, and labels every other
# one with a time. Its prior-close rule is drawn into the plate 62% of the
# way down the plot, which is why the figures go in as the move from that
# close: zero is the rule (`pipeline.series.PINNED_ZERO`).
SESSION_POINTS = 7
# Where the writer's move and the tape may differ before the chart is
# withheld: a narration saying +29% over a session that closed +3% is a
# stale tape or a wrong script, and either way the drawing would contradict
# the voice.
SESSION_AGREE_PTS = 3.0


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _clock(minutes: float) -> str:
    m = int(round(minutes))
    return f"{m // 60:02d}:{m % 60:02d}"


def session_points(session, n: int = SESSION_POINTS
                   ) -> list[tuple[str, float]] | None:
    """`n` evenly spaced readings across the session, as (time, price).

    Read off the tape by straight-line interpolation between the two bars
    either side of each time, so a label under a point is the time that
    point is for.
    """
    ts = [_minutes(t) for t in session.times]
    ps = list(session.prices)
    if len(ts) < 2 or len(ts) != len(ps) or ts[-1] <= ts[0]:
        return None
    out = []
    for i in range(n):
        at = ts[0] + (ts[-1] - ts[0]) * i / (n - 1)
        j = next(k for k in range(1, len(ts)) if ts[k] >= at - 1e-9)
        a, b = ts[j - 1], ts[j]
        f = 0.0 if b == a else (at - a) / (b - a)
        out.append((_clock(at), ps[j - 1] + (ps[j] - ps[j - 1]) * f))
    return out


def _signed_pct(frac: float) -> str:
    v = round(frac * 100.0, 1)
    return f"{'+' if v > 0 else '−' if v < 0 else ''}{abs(v):.1f}%"


SESSION_KICKER_CHARS = 17


def session_card(session, script=None) -> dict[str, str] | None:
    """`charts/intraday`: today's session against the prior close.

    None when there is no session, or when the session's move does not
    agree with the move the writer is narrating.
    """
    if session is None or not session.prior_close:
        return None
    pts = session_points(session)
    if not pts:
        return None
    move = session.move
    claimed = None
    summary = str(getattr(script, "move_summary", "") or "")
    m = re.match(r"^\s*([+\-−–])\s*(\d+(?:\.\d+)?)\s*%", summary)
    if m:
        claimed = float(m.group(2)) * (1 if m.group(1) == "+" else -1)
    if claimed is not None and abs(claimed - move * 100.0) > SESSION_AGREE_PTS:
        log.info("the session closed %s and the script says %s%%: no session "
                 "chart", _signed_pct(move), claimed)
        return None
    when = _dt.date.fromisoformat(session.day)
    ticker = (session.ticker or str(getattr(script, "ticker", "") or "")).upper()
    now = session.prices[-1]
    # THE DAY AND WHAT THE LINE IS, in what `charts/intraday` holds: its
    # kicker takes 17 characters and its unit 14, so "EXMPL · 11 SEPTEMBER"
    # and "price, one session" were dropped and the card went up undated.
    kicker = f"{ticker} · {when.day} {when:%B}".upper()
    if len(kicker) > SESSION_KICKER_CHARS:
        kicker = f"{ticker} · {when.day} {when:%b}".upper()
    out = {
        "kicker": kicker,
        "unit": "price, one day" if session.complete else "price so far",
        "figure": _signed_pct(move),
        "plot-area": ",".join(f"{(p / session.prior_close - 1) * 100:.2f}"
                              for _t, p in pts),
        # A PRICE ON THE LINE, not only a percentage (30 Oct 2026: "it just
        # shows a line that went down").
        "event-label": (f"{pts[2][0]} · ${pts[2][1]:,.2f} · "
                        f"{_signed_pct(pts[2][1] / session.prior_close - 1)}"),
        "caption": (f"${now:,.2f} {'close' if session.complete else 'now'}; "
                    f"the line across is ${session.prior_close:,.2f}"),
        # What the six-point box under a move figure is, in words.
        "unit6": f"the session, {session.times[0]} to {session.times[-1]}",
    }
    for i in (1, 3, 5, 7):
        out[f"head-{i}"] = pts[i - 1][0]
    # THE SAME SESSION IN SIX POINTS, for the move plates
    # (`figures/move-on-the-day*`), which reserve a box under the figure for
    # the session and draw six. It sat empty on every short that cut to them,
    # half the frame of nothing (2 Oct 2026, "it still looks too empty").
    six = session_points(session, 6) or []
    if len(six) == 6:
        out["path-6"] = ",".join(f"{(p / session.prior_close - 1) * 100:.2f}"
                                 for _t, p in six)
    return out


def claimed_move(script) -> float | None:
    """The move the writer narrates, in percent, off `move_summary`'s lead."""
    summary = str(getattr(script, "move_summary", "") or "")
    m = re.match(r"^\s*([+\-−–])\s*(\d+(?:\.\d+)?)\s*%", summary)
    if not m:
        return None
    return float(m.group(2)) * (1 if m.group(1) == "+" else -1)


# How close a day's close-to-close change must come to the narrated move to be
# the day the short is about.
MOVE_DAY_PTS = 1.5


def move_day(prices, claimed: float | None, *, look_back: int = 6
             ) -> dict | None:
    """The session the narrated move happened on, off the daily closes.

    `{"day", "close", "prior", "move"}` for the latest of the last few
    sessions whose change matches the move within `MOVE_DAY_PTS`, and the
    latest session when nothing is claimed. None without two closes or a
    match: a price printed beside a move it did not make is worse than none.
    """
    dates = list(getattr(prices, "dates", []) or [])
    closes = list(getattr(prices, "closes", []) or [])
    if len(dates) < 2 or len(dates) != len(closes):
        return None
    if getattr(prices, "degraded", False) or \
            str(getattr(prices, "source", "")) == "synthetic":
        return None
    for i in range(len(closes) - 1, max(0, len(closes) - 1 - look_back), -1):
        prior, close = closes[i - 1], closes[i]
        if not prior or close is None:
            continue
        moved = (close / prior - 1.0) * 100.0
        if claimed is None or abs(moved - claimed) <= MOVE_DAY_PTS:
            return {"day": str(dates[i])[:10], "close": float(close),
                    "prior": float(prior), "move": moved}
    return None


def money_price(v: float) -> str:
    """A share price as a card prints it: `$168.18`, `$1,204.50`."""
    from pipeline.chart import _price_text

    return f"${_price_text(float(v), 9)}"


def move_price(session, day: dict | None, script=None) -> str | None:
    """`$168.18 at the close, from $188.31`: the price the move took it to.

    Off the session when it is the move's own (it agrees with the narration),
    else off the daily closes of the move's day. None with neither.
    """
    if session is not None and session_card(session, script) is not None:
        now = session.prices[-1]
        when = "at the close" if session.complete else "now"
        return f"{money_price(now)} {when}, from {money_price(session.prior_close)}"
    if day:
        return (f"{money_price(day['close'])} at the close, from "
                f"{money_price(day['prior'])}")
    return None


# ---------------------------------------------------------------------------
# The multiple the cheap-or-trap line is about
# ---------------------------------------------------------------------------

# The valuation multiples a writer names, most specific first: the Snapshot
# field that holds today's figure, the peer table's name for it, and the ways
# it is written or said ("EV/EBITDA", "seventy times EBITDA").
_MULTIPLES: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    ("EV/EBITDA", "ev_ebitda", "EV/EBITDA",
     (r"ev\s*/\s*ebitda", r"enterprise value to ebitda", r"ebitda multiple",
      r"times\s+(?:its\s+|the\s+)?ebitda")),
    ("EV/sales", "ev_sales", "",
     (r"ev\s*/\s*(?:sales|revenue)", r"enterprise value to (?:sales|revenue)")),
    ("EV/FCF", "ev_fcf", "",
     (r"ev\s*/\s*(?:fcf|free cash flow)",)),
    ("P/FCF", "p_fcf", "",
     (r"p\s*/\s*fcf", r"price to free cash flow",
      r"times\s+(?:its\s+)?free cash flow")),
    ("P/S", "ps_ttm", "P/S (TTM)",
     (r"p\s*/\s*s(?![a-z])", r"price to sales",
      r"times\s+(?:its\s+)?(?:sales|revenue)")),
    ("forward P/E", "forward_pe", "",
     (r"forward\s+p\s*/\s*e(?![a-z])", r"times\s+forward\s+earnings")),
    ("P/E", "pe_ttm", "P/E (TTM)",
     (r"p\s*/\s*e(?![a-z])", r"(?<![a-z])pe(?![a-z])", r"price to earnings",
      r"earnings multiple", r"times\s+(?:its\s+)?earnings")),
    ("P/B", "pb", "",
     (r"p\s*/\s*b(?![a-z])", r"price to book", r"times\s+(?:its\s+)?book")),
)


def named_multiple(text: str) -> tuple[str, str, str] | None:
    """The valuation multiple a line names first: `(label, field, peer name)`.

    "Net debt is 9.8 times EBITDA" is leverage, not a price, so a mention
    in the same clause as "debt" just before it does not count ("debt fell,
    yet seventy times EBITDA" is a price).
    """
    low = " ".join(str(text or "").lower().split())
    best = None
    for label, fld, peer, pats in _MULTIPLES:
        for pat in pats:
            for m in re.finditer(pat, low):
                before = low[max(0, m.start() - 25):m.start()]
                if "debt" in before and not re.search(
                        r"[,;:]|\.(?!\d)", before[before.rfind("debt"):]):
                    continue
                if best is None or m.start() < best[0]:
                    best = (m.start(), (label, fld, peer))
                break
    return best[1] if best else None


def times(v: float) -> str:
    """A multiple as a card prints it: 70x, 9.1x."""
    return f"{v:.0f}×" if abs(v) >= 10 else f"{v:.1f}×"


def multiple_statements(data, text: str) -> dict[str, str] | None:
    """`structure/both-true`'s two lines for a cheap-or-trap line that names a
    multiple (31 Oct 2026, Valentin: the card showed revenue then and now
    while the voice was on EV/EBITDA and the growth it implies).

    `heavy` is the multiple today, off the Snapshot; `light` is what that
    price asks for, off the reverse DCF, or else where the peers trade.
    `{}` when the line names a multiple the workbook cannot put a figure to
    (nothing is better than another figure under those words); None when it
    names none.
    """
    named = named_multiple(text)
    if named is None:
        return None
    label, fld, peer = named
    vals = getattr(data, "values", {}) or {} if data is not None else {}
    v = vals.get(fld)
    if not isinstance(v, (int, float)) or v <= 0:
        return {}
    light = None
    ig = ((getattr(data, "valuation", {}) or {}).get("implied_growth")
          if data is not None else None)
    if isinstance(ig, (int, float)):
        # Short enough for the statement boxes on both cards (34 characters
        # on `structure/confession-statement`): the reverse DCF's growth is
        # in cash, every year, for good.
        light = f"Priced for {_pct(ig)} growth, forever."
    elif peer:
        row = next((r for r in (getattr(data, "peer_percentiles", None) or [])
                    if isinstance(r, dict) and r.get("metric") == peer), None)
        med = (row or {}).get("median")
        if isinstance(med, (int, float)) and med > 0:
            light = f"Its peers trade at {times(med)}."
    if light is None:
        return {}
    return {"heavy": f"{label} is {times(v)} today.", "light": light}


CARDS = {
    "implied": implied,
    "week52": week52,
    "short_interest": short_interest,
    "qbars": quarter_bars,
    "three_lines": three_lines,
    "qoq_yoy": qoq_yoy,
    "print_vs_consensus": print_vs_consensus,
}
