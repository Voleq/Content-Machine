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

from pipeline.models import RATE_FIELDS

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
    a = abs(v)
    sign = "-" if v < 0 else ""
    for div, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= div:
            return f"{sign}{currency}{_sig(a / div)}{suffix}"
    return f"{sign}{currency}{_sig(a)}"


def count(v: float) -> str:
    """`364600000` -> `365M`."""
    return money(v, currency="")


def rate(v: float) -> str:
    """A percentage the workbook holds as a percent: `58.0` -> `58%`."""
    return f"{v:.1f}%" if abs(v) < 10 and v != int(v) else f"{v:.0f}%"


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
        elif h.strip().upper() == "FY-0" and year is not None:
            out.append(f"FY{(year - 1) % 100:02d}")
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


def quarter_labels(data) -> list[str]:
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


def quarter_heads(data) -> list[str]:
    """Each quarter's head as a card prints it (7 characters at most).

    `Q2 FY25` becomes `Q2 '25`. A sheet still on relative headers (`Q-7`) gets
    `-7Q`…`LATEST`, which is what those columns are, rather than a date the
    workbook never gave.
    """
    out = []
    for h in quarter_labels(data):
        m = re.match(r"^Q([1-4])\s*FY\s*(\d{2,4})$", h.strip(), re.I)
        if m:
            out.append(f"Q{m.group(1)} '{m.group(2)[-2:]}")
            continue
        r = _RELATIVE_Q.match(h.strip())
        if r:
            n = int(r.group(1))
            out.append("LATEST" if n == 0 else f"-{n}Q")
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


def fill_numbers(script, data) -> tuple[Any, list[str]]:
    """`script` with every sheet row it can match taken from the workbook.

    The writer names the rows; the figures on screen are the History sheet's,
    so the sheet cannot disagree with the workbook. A row that names no field
    and whose label matches none keeps the figures typed for it, and is
    reported. Returns `(script, notes)`; the script is a copy.
    """
    rows = list(getattr(script, "numbers", []) or [])
    if data is None or not rows or not getattr(data, "has_history", False):
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


def axis_ticks(values: list[float]) -> list[float]:
    """Five evenly spaced gridline values that hold every bar and zero."""
    lo, hi = min([0.0] + values), max([0.0] + values)
    if hi == lo:
        hi = lo + 1.0
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
    pos = (now - lo) / (hi - lo)
    off = (now / hi - 1.0) * 100.0
    return {
        "kicker": f"{_ticker(data, script)} · the last 52 weeks",
        "label-high": "52-week high",
        "figure-high": f"${hi:,.2f}"[:8],
        "label-now": (f"now, {abs(off):.0f}% below the high" if off <= -1
                      else "now, at the high"),
        "now": f"${now:,.2f}"[:9],
        "label-low": "52-week low",
        "figure-low": f"${lo:,.2f}"[:8],
        "band": "0,1",
        "marker": f"{min(max(pos, 0.0), 1.0):.3f}",
    }


# Short interest worth a card of its own: more than this share of the float.
SHORT_INTEREST_CARD = 0.10


def short_interest_share(data) -> float | None:
    """Short interest as a FRACTION of the float, or None.

    The template divides the add-in's percentage by 100 (`Snapshot!D49`); the
    committed fixture still carries it as a percentage. A value over 1 is read
    as the percentage it plainly is.
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
    out = {
        "kicker": f"{ticker} · {when.day} {when:%B}".upper()[:25],
        "unit": "price, one session" if session.complete else "price, so far today",
        "figure": _signed_pct(move),
        "plot-area": ",".join(f"{(p / session.prior_close - 1) * 100:.2f}"
                              for _t, p in pts),
        "event-label": f"At {pts[2][0]}, {_signed_pct(pts[2][1] / session.prior_close - 1)}",
        "caption": f"The line across is the prior close, ${session.prior_close:,.2f}",
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


CARDS = {
    "implied": implied,
    "week52": week52,
    "short_interest": short_interest,
    "qbars": quarter_bars,
    "three_lines": three_lines,
    "qoq_yoy": qoq_yoy,
    "print_vs_consensus": print_vs_consensus,
}
