"""Company-data export reader + filing-screenshot prep (§3).

The operator has an Excel add-in (Refinitiv/LSEG TR formulas), not API
access, so the data contract is the v3 template — the PRIVATE data source.
The add-in resolves the formulas in the operator's Excel; the file the bot
receives carries CACHED VALUES, so this reads with openpyxl data_only=True
(values, never formula strings). Sheets are read strictly BY NAME (any
hidden add-in helper sheets are ignored):

  * `Snapshot`  — point-in-time: `field_key` column + a `Value (auto)`
    column, grouped by Section.
  * `History`   — 6 periods (FY-4 … FY-0, LTM) under the header row; the
    period columns are read DYNAMICALLY from that header, never hardcoded.
  * `Dashboard` — the one-glance summary + flags (this is exactly what the
    numbers sheet reads).
  * `Valuation` — bear/base/bull scenarios + inputs, plus the auto WACC
    (CAPM) and reverse-DCF block (long-form).
  * `Peers`     — the auto-pulled peer table, plus a self-scoring percentile
    block beneath it (two distinct blocks; long-form).
  * `News`      — recent headlines (Date/Headline/Source/URL), spilled by the
    add-in (optional; a news outlet as Source is fine — never a data-terminal
    brand).

A CSV export (`field_key,value`) is accepted for the snapshot only. Missing
required identity/size fields BLOCK the run; other gaps warn.

NOTHING here ever puts the vendor's name on screen: uploaded raw
screenshots are normalized with a generic "FROM THE 10-K" label.
"""

from __future__ import annotations

import csv
import datetime as _dt
import logging
from pathlib import Path

from openpyxl import load_workbook
from PIL import Image, ImageDraw, ImageFont

from config import Settings
from pipeline.models import (
    ALL_DATA_FIELDS,
    HISTORY_FIELDS,
    CompanyData,
    _STRING_FIELDS,
)

log = logging.getLogger(__name__)

_NA_VALUES = {"", "#N/A", "#N/A N/A", "N/A", "NA", "#VALUE!", "#REF!", "#NAME?",
              "NULL", "-", "#DIV/0!"}
# the add-in leaves this literal in cells whose mnemonic didn't resolve
_FORMULA_ERR = "the formula must contain at least one field or function."

# accepted upload names (the bot saves uploads under the first)
EXPORT_NAMES = ("dennis_data.xlsx", "data.xlsx", "dennis_data.csv")

# sheets read by name (anything else — Instructions, hidden helpers — ignored)
SNAPSHOT_SHEET = "Snapshot"
HISTORY_SHEET = "History"
DASHBOARD_SHEET = "Dashboard"
VALUATION_SHEET = "Valuation"
PEERS_SHEET = "Peers"
NEWS_SHEET = "News"


class CompanyDataError(Exception):
    pass


def _is_na(text: str) -> bool:
    t = text.strip()
    return t in _NA_VALUES or t.lower() == _FORMULA_ERR


def _num(raw) -> float | None:
    """NA-aware numeric coerce (values, never formulas)."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).strip()
    if _is_na(text):
        return None
    try:
        return float(text.replace(",", "").replace("%", "").replace("$", ""))
    except ValueError:
        return None


def _coerce(field: str, raw) -> str | float | None:
    if raw is None:
        return None
    if isinstance(raw, (_dt.datetime, _dt.date)):
        # as_of_date etc. arrive as real dates — keep a clean ISO day
        return raw.date().isoformat() if isinstance(raw, _dt.datetime) else raw.isoformat()
    text = str(raw).strip()
    if _is_na(text):
        return None
    if field in _STRING_FIELDS:
        return text
    val = _num(raw)
    if val is None:
        log.warning("company data field %s: cannot coerce %r to number", field, raw)
    return val


def _text_or_none(raw) -> str | None:
    """NA-aware free-text coerce; a real date collapses to an ISO day string.
    Used by the News / peer-percentile readers, whose cells are free text (or
    spilled dates) rather than typed field_keys."""
    if raw is None:
        return None
    if isinstance(raw, _dt.datetime):
        return raw.date().isoformat()
    if isinstance(raw, _dt.date):
        return raw.isoformat()
    text = str(raw).strip()
    return None if _is_na(text) else text


def find_export(workspace: Path) -> Path | None:
    for name in EXPORT_NAMES:
        p = workspace / name
        if p.exists():
            return p
    return None


# --------------------------------------------------------------------------
# v3 sheet readers — locate headers by text, never by fixed cell position.
# --------------------------------------------------------------------------

def _rows(ws) -> list[tuple]:
    return list(ws.iter_rows(values_only=True))


def _cell_text(v) -> str:
    return "" if v is None else str(v).strip()


def _header_row(rows: list[tuple], marker: str) -> int | None:
    """Index of the first row containing a cell equal to `marker`."""
    m = marker.strip().lower()
    for i, row in enumerate(rows):
        if any(_cell_text(c).lower() == m for c in row):
            return i
    return None


def _col_of(header: tuple, *names: str) -> int | None:
    wanted = {n.strip().lower() for n in names}
    for j, c in enumerate(header):
        if _cell_text(c).lower() in wanted:
            return j
    return None


def _read_snapshot(ws) -> dict[str, object]:
    rows = _rows(ws)
    hr = _header_row(rows, "field_key")
    if hr is None:
        return {}
    header = rows[hr]
    key_c = _col_of(header, "field_key")
    val_c = _col_of(header, "value (auto)", "value")
    if key_c is None or val_c is None:
        return {}
    pairs: dict[str, object] = {}
    for row in rows[hr + 1:]:
        if key_c >= len(row):
            continue
        key = _cell_text(row[key_c])
        if not key or key == "field_key":
            continue
        pairs[key] = row[val_c] if val_c < len(row) else None
    return pairs


def _read_history(ws) -> tuple[list[str], dict[str, list[float | None]]]:
    """Header row carries `field_key`, `Label`, the period labels, then
    `CAGR …` and the mnemonic column. The period columns are everything
    between `Label` and the CAGR/mnemonic tail — read dynamically."""
    rows = _rows(ws)
    hr = _header_row(rows, "field_key")
    if hr is None:
        return [], {}
    header = rows[hr]
    key_c = _col_of(header, "field_key")
    label_c = _col_of(header, "label")
    start = (label_c if label_c is not None else key_c) + 1
    period_cols: list[int] = []
    periods: list[str] = []
    for j in range(start, len(header)):
        txt = _cell_text(header[j])
        low = txt.lower()
        if not txt:
            continue
        if low.startswith("cagr") or "mnemonic" in low:
            break  # the trailing computed/verify columns
        period_cols.append(j)
        periods.append(txt)
    if not period_cols:
        return [], {}
    history: dict[str, list[float | None]] = {}
    for row in rows[hr + 1:]:
        if key_c >= len(row):
            continue
        key = _cell_text(row[key_c])
        if not key or key == "field_key":
            continue
        history[key] = [_num(row[j] if j < len(row) else None) for j in period_cols]
    unknown = [k for k in history if k not in HISTORY_FIELDS]
    for k in unknown:
        log.warning("history sheet has unknown field %r — ignored", k)
        history.pop(k)
    return periods, history


def _read_dashboard(ws) -> dict[str, object]:
    """`label | value` pairs (the one-glance summary + flags). Skips the
    title/subtitle banner rows; keeps `yes/no` flag strings verbatim."""
    out: dict[str, object] = {}
    for row in _rows(ws):
        if not row:
            continue
        label = _cell_text(row[0])
        if not label:
            continue
        low = label.lower()
        if low.startswith("dennis") or low.startswith("auto from"):
            continue
        raw = row[1] if len(row) > 1 else None
        if _cell_text(raw) == "" or label.lower() == "quick flags":
            out[label] = None if label.lower() != "quick flags" else ""
            continue
        text = _cell_text(raw)
        if _is_na(text):
            out[label] = None
        elif text.lower() in ("yes", "no"):
            out[label] = text.lower()
        else:
            num = _num(raw)
            out[label] = num if num is not None else text
    return out


def _read_news(ws) -> list[dict]:
    """Recent headlines. The header row carries `Date | Headline | Source |
    URL` (anchor on the row with a cell equal to `Headline`); data rows spill
    beneath, possibly blank/NA. Skip any row whose headline is empty/NA;
    dates coerce to ISO day strings. Source is a news outlet, never a
    data-terminal brand."""
    rows = _rows(ws)
    hr = _header_row(rows, "headline")
    if hr is None:
        return []
    header = rows[hr]
    date_c = _col_of(header, "date")
    head_c = _col_of(header, "headline")
    src_c = _col_of(header, "source")
    url_c = _col_of(header, "url")
    if head_c is None:
        return []

    def _cell(row, c):
        return row[c] if c is not None and c < len(row) else None

    news: list[dict] = []
    for row in rows[hr + 1:]:
        headline = _text_or_none(_cell(row, head_c))
        if not headline:
            continue  # blank/NA spill row — skip (do NOT stop; gaps happen)
        news.append({
            "date": _text_or_none(_cell(row, date_c)),
            "headline": headline,
            "source": _text_or_none(_cell(row, src_c)),
            "url": _text_or_none(_cell(row, url_c)),
        })
    return news


def _read_valuation(ws) -> dict:
    rows = _rows(ws)
    val: dict = {}

    def _find_value(label: str):
        for row in rows:
            if row and _cell_text(row[0]).lower() == label:
                return _num(row[1]) if len(row) > 1 else None
        return None

    def _find_value_prefix(prefix: str):
        """First row whose col-A label STARTS WITH `prefix` (lowercased). The
        add-in emits these labels with a Unicode minus (U+2212) and en-dashes,
        so we anchor on the clean leading text, never on hardcoded punctuation."""
        for row in rows:
            if row and _cell_text(row[0]).lower().startswith(prefix):
                return _num(row[1]) if len(row) > 1 else None
        return None

    def _find_text(label: str):
        for row in rows:
            if row and _cell_text(row[0]).lower() == label:
                return _text_or_none(row[1]) if len(row) > 1 else None
        return None

    val["current_price"] = _find_value("current price")
    val["ltm_eps"] = _find_value("ltm eps")
    val["ltm_fcf_ps"] = _find_value("ltm fcf / share")

    # WACC + reverse-DCF block (fully auto). Match on exact / leading text so
    # the bare `WACC` row is captured but NOT the "WACC (auto — CAPM)" band
    # title nor the "WACC −1%" / "WACC +1%" sensitivity rows. `implied_growth`
    # takes the reverse-DCF row (first "Implied growth …"), not the later
    # "Implied growth sensitivity …" title.
    val["wacc"] = _find_value("wacc")
    val["implied_growth"] = _find_value_prefix("implied growth")
    val["hist_fcf_cagr"] = _find_value("historical fcf cagr (4y)")
    val["rev_cagr"] = _find_value("revenue cagr (4y)")
    val["priced_vs_delivered"] = _find_value_prefix("priced-for")
    val["reverse_dcf_read"] = _find_text("read")

    hr = _header_row(rows, "scenario")
    scenarios: list[dict] = []
    if hr is not None:
        for row in rows[hr + 1:]:
            name = _cell_text(row[0]) if row else ""
            if name.lower() not in ("bear", "base", "bull"):
                continue
            scenarios.append({
                "scenario": name,
                "metric": _cell_text(row[1]) or _cell_text(row[2]) if len(row) > 2 else "",
                "exit_multiple": _num(row[3]) if len(row) > 3 else None,
                "implied_price": _num(row[4]) if len(row) > 4 else None,
                "upside_pct": _num(row[5]) if len(row) > 5 else None,
            })
    val["scenarios"] = scenarios
    return val


_PEER_COLS = ["price", "market_cap", "pe", "ev_ebitda", "ps", "rev_growth",
              "gross_margin", "net_margin", "fcf_yield", "net_debt_ebitda"]


def _read_peers(ws) -> list[dict]:
    rows = _rows(ws)
    hr = _header_row(rows, "peer (auto)")
    if hr is None:
        return []
    peers: list[dict] = []
    for row in rows[hr + 1:]:
        name = _cell_text(row[0]) if row else ""
        if not name:
            # the PEERS() spill is contiguous; the first blank name ends the
            # auto table — stop here so we never wander into the self-scoring
            # percentile block that lives beneath it.
            break
        entry: dict = {"name": name}
        for k, j in zip(_PEER_COLS, range(1, 1 + len(_PEER_COLS))):
            entry[k] = _num(row[j]) if j < len(row) else None
        peers.append(entry)
    return peers


def _percentile_direction(raw) -> str | None:
    """Normalize the "Higher is" column to `better` / `worse`. The cell reads
    e.g. "better" or "worse (expensive/levered)" — we keep just the polarity."""
    text = _text_or_none(raw)
    if text is None:
        return None
    low = text.lower()
    if low.startswith("better"):
        return "better"
    if low.startswith("worse"):
        return "worse"
    return None


def _read_peer_percentiles(ws) -> list[dict]:
    """The SECOND block on the Peers sheet — the subject's self-score vs its
    peers — which lives beneath the auto table (`_read_peers` handles that).
    Anchor on the header row whose col-A cell equals `Metric`
    (Metric | Subject | Peer median | Percentile | Higher is | Read); metric
    rows follow until the first blank metric. `percentile` is a 0–1 fraction;
    `direction` is the polarity of the "Higher is" column; `read` is the
    plain-text verdict ("expensive vs peers" / "strong vs peers" / …)."""
    rows = _rows(ws)
    hr = _header_row(rows, "metric")
    if hr is None:
        return []
    header = rows[hr]
    m_c = _col_of(header, "metric")
    subj_c = _col_of(header, "subject")
    med_c = _col_of(header, "peer median")
    pct_c = _col_of(header, "percentile")
    dir_c = _col_of(header, "higher is")
    read_c = _col_of(header, "read")
    if m_c is None:
        return []

    def _cell(row, c):
        return row[c] if c is not None and c < len(row) else None

    out: list[dict] = []
    for row in rows[hr + 1:]:
        metric = _cell_text(row[m_c]) if m_c < len(row) else ""
        if not metric:
            break  # the first blank metric ends the block
        out.append({
            "metric": metric,
            "subject": _num(_cell(row, subj_c)),
            "median": _num(_cell(row, med_c)),
            "percentile": _num(_cell(row, pct_c)),
            "direction": _percentile_direction(_cell(row, dir_c)),
            "read": _text_or_none(_cell(row, read_c)),
        })
    return out


def load_company_data(workspace: Path) -> CompanyData:
    """Load + type-coerce the v3 export (all sheets, by name). Raises
    CompanyDataError if absent or unreadable; missing-field policy lives on
    the model."""
    src = find_export(workspace)
    if src is None:
        raise CompanyDataError(
            "No dennis_data.xlsx / data.xlsx / dennis_data.csv in the workspace. "
            "Refresh the data template for this ticker and upload it."
        )

    pairs: dict[str, object] = {}
    history_years: list[str] = []
    history: dict[str, list[float | None]] = {}
    dashboard: dict[str, object] = {}
    valuation: dict = {}
    peers: list[dict] = []
    peer_percentiles: list[dict] = []
    news: list[dict] = []
    if src.suffix == ".xlsx":
        wb = load_workbook(src, data_only=True)
        names = set(wb.sheetnames)
        snap_ws = wb[SNAPSHOT_SHEET] if SNAPSHOT_SHEET in names else wb.worksheets[0]
        pairs = _read_snapshot(snap_ws)
        if HISTORY_SHEET in names:
            history_years, history = _read_history(wb[HISTORY_SHEET])
        else:
            log.warning("export has no History sheet — multi-year numbers unavailable")
        if DASHBOARD_SHEET in names:
            dashboard = _read_dashboard(wb[DASHBOARD_SHEET])
        if VALUATION_SHEET in names:
            valuation = _read_valuation(wb[VALUATION_SHEET])
        if PEERS_SHEET in names:
            # two distinct blocks on the one sheet — the raw auto table and
            # the self-scoring percentile block below it.
            peers = _read_peers(wb[PEERS_SHEET])
            peer_percentiles = _read_peer_percentiles(wb[PEERS_SHEET])
        if NEWS_SHEET in names:
            news = _read_news(wb[NEWS_SHEET])
        else:
            log.warning("export has no News sheet — recent-headlines flow unavailable")
        wb.close()
    else:
        with open(src, newline="", encoding="utf-8-sig") as f:
            for row in csv.reader(f):
                if len(row) >= 2 and row[0].strip() and row[0].strip() not in ("field", "field_key"):
                    pairs[row[0].strip()] = row[1]
        log.warning("CSV export carries the snapshot only — no history/dashboard")

    unknown = [k for k in pairs if k not in ALL_DATA_FIELDS]
    for k in unknown:
        log.warning("export has unknown field %r — ignored", k)

    values = {field: _coerce(field, pairs.get(field)) for field in ALL_DATA_FIELDS}
    return CompanyData(values=values, history_years=history_years,
                       history=history, dashboard=dashboard,
                       valuation=valuation, peers=peers,
                       peer_percentiles=peer_percentiles, news=news,
                       source_file=str(src))


# ---------------------------------------------------------------------------
# Screenshot prep: raw data screenshots -> normalized full-screen flashes
# with a GENERIC source label — the vendor is never named on screen (§3).
# ---------------------------------------------------------------------------

FILING_LABEL = "FROM THE 10-K"


def prepare_screenshot(src: Path, dest: Path, settings: Settings) -> Path:
    """Full-frame designed filing card: the screenshot fitted sharp over a
    blurred, brand-tinted cover of itself (never a letterboxed black frame),
    a subtle border, and the generic '10-K' chip. Deterministic output."""
    from pipeline.rasters import cover_fill_frame

    W, H = settings.long_resolution
    margin = int(H * 0.05)
    canvas = cover_fill_frame(src, W, H, keep_min=1.1)  # always contain-on-fill
    d = ImageDraw.Draw(canvas)

    # generic source chip — "the filing", never the vendor
    font = ImageFont.truetype(str(settings.fonts_dir / "SpaceMono-Bold.ttf"),
                              max(int(H * 0.026), 14))
    pad = int(H * 0.012)
    tw = d.textlength(FILING_LABEL, font=font)
    cx0, cy0 = margin // 2, margin // 2
    d.rounded_rectangle(
        [cx0, cy0, cx0 + tw + 2 * pad, cy0 + font.size + 2 * pad],
        radius=8, fill=(24, 28, 36), outline=(96, 106, 122), width=2,
    )
    d.text((cx0 + pad, cy0 + pad), FILING_LABEL, font=font, fill=(47, 213, 118))

    dest.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dest)
    return dest


def list_screenshots(workspace: Path) -> list[str]:
    """Raw screenshot files the operator dropped into the workspace (these
    are what [SHOW FILING: file] may reference)."""
    reserved = set(EXPORT_NAMES)
    return sorted(
        p.name for p in workspace.glob("*.png")
        if p.name not in reserved and not p.name.startswith("_")
    )
