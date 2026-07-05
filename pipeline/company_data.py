"""Company-data export reader + filing-screenshot prep (§3).

The operator has an Excel add-in, not API access, so the data contract is
`templates/dennis_data_template.xlsx` — the PRIVATE data source, two
fixed sheets read strictly by field name (never by cell position):

  * `Latest`  — the snapshot: `field | value | group` rows.
  * `History` — 5 fiscal years per direction metric: row 1 holds the
    year labels (oldest → newest), column A the field name.

A CSV export (`field,value`) is accepted for the snapshot only. Missing
identity/size/margins/cash fields BLOCK the run; other gaps warn; a
missing history sheet warns (the multi-year gut check needs it).

NOTHING here ever puts the vendor's name on screen: uploaded raw
screenshots are normalized with a generic "FROM THE 10-K" label.
"""

from __future__ import annotations

import csv
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

_NA_VALUES = {"", "#N/A", "#N/A N/A", "N/A", "NA", "#VALUE!", "#REF!", "#NAME?", "NULL", "-"}

# accepted upload names (the bot saves uploads under the first pair)
EXPORT_NAMES = ("dennis_data.xlsx", "dennis_data.csv")


class CompanyDataError(Exception):
    pass


def _coerce(field: str, raw) -> str | float | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if text in _NA_VALUES:
        return None
    if field in _STRING_FIELDS:
        return text
    try:
        return float(text.replace(",", "").replace("%", "").replace("$", ""))
    except ValueError:
        log.warning("company data field %s: cannot coerce %r to number", field, raw)
        return None


def _coerce_history(field: str, raw) -> float | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if text in _NA_VALUES:
        return None
    try:
        return float(text.replace(",", "").replace("%", "").replace("$", ""))
    except ValueError:
        log.warning("history field %s: cannot coerce %r to number", field, raw)
        return None


def find_export(workspace: Path) -> Path | None:
    for name in EXPORT_NAMES:
        p = workspace / name
        if p.exists():
            return p
    return None


def _read_latest_sheet(ws) -> dict[str, object]:
    pairs: dict[str, object] = {}
    for row in ws.iter_rows(min_row=1, max_col=2, values_only=True):
        if not row or row[0] is None:
            continue
        field = str(row[0]).strip()
        if field and field != "field":
            pairs[field] = row[1] if len(row) > 1 else None
    return pairs


def _read_history_sheet(ws) -> tuple[list[str], dict[str, list[float | None]]]:
    """Row 1: 'field' + year labels. Rows: field name + one value per year."""
    rows = ws.iter_rows(min_row=1, values_only=True)
    try:
        header = next(rows)
    except StopIteration:
        return [], {}
    years = [str(c).strip() for c in (header[1:] if header else []) if c is not None]
    if not years:
        return [], {}
    history: dict[str, list[float | None]] = {}
    for row in rows:
        if not row or row[0] is None:
            continue
        field = str(row[0]).strip()
        if not field or field == "field":
            continue
        vals = [_coerce_history(field, row[1 + i] if 1 + i < len(row) else None)
                for i in range(len(years))]
        history[field] = vals
    unknown = [k for k in history if k not in HISTORY_FIELDS]
    for k in unknown:
        log.warning("history sheet has unknown field %r — ignored", k)
        history.pop(k)
    return years, history


def load_company_data(workspace: Path) -> CompanyData:
    """Load + type-coerce the export (both sheets). Raises CompanyDataError
    if absent or unreadable; missing-field policy lives on the model."""
    src = find_export(workspace)
    if src is None:
        raise CompanyDataError(
            "No dennis_data.xlsx / dennis_data.csv in the workspace. "
            "Refresh the data template for this ticker and upload it."
        )

    pairs: dict[str, object] = {}
    history_years: list[str] = []
    history: dict[str, list[float | None]] = {}
    if src.suffix == ".xlsx":
        wb = load_workbook(src, data_only=True, read_only=True)
        latest_ws = wb["Latest"] if "Latest" in wb.sheetnames else wb.worksheets[0]
        pairs = _read_latest_sheet(latest_ws)
        if "History" in wb.sheetnames:
            history_years, history = _read_history_sheet(wb["History"])
        else:
            log.warning("export has no History sheet — multi-year numbers unavailable")
        wb.close()
    else:
        with open(src, newline="", encoding="utf-8-sig") as f:
            for row in csv.reader(f):
                if len(row) >= 2 and row[0].strip() and row[0].strip() != "field":
                    pairs[row[0].strip()] = row[1]
        log.warning("CSV export carries the snapshot only — no history sheet")

    unknown = [k for k in pairs if k not in ALL_DATA_FIELDS]
    for k in unknown:
        log.warning("export has unknown field %r — ignored", k)

    values = {field: _coerce(field, pairs.get(field)) for field in ALL_DATA_FIELDS}
    return CompanyData(values=values, history_years=history_years,
                       history=history, source_file=str(src))


# ---------------------------------------------------------------------------
# Screenshot prep: raw data screenshots -> normalized full-screen flashes
# with a GENERIC source label — the vendor is never named on screen (§3).
# ---------------------------------------------------------------------------

FILING_LABEL = "FROM THE 10-K"


def prepare_screenshot(src: Path, dest: Path, settings: Settings) -> Path:
    """Fixed canvas, fitted image, subtle border, generic '10-K' chip —
    deterministic output."""
    W, H = settings.long_resolution
    margin = int(H * 0.05)
    img = Image.open(src).convert("RGB")
    img.thumbnail((W - 2 * margin, H - 2 * margin), Image.LANCZOS)

    canvas = Image.new("RGB", (W, H), (10, 13, 18))
    x = (W - img.width) // 2
    y = (H - img.height) // 2
    canvas.paste(img, (x, y))
    d = ImageDraw.Draw(canvas)
    d.rectangle([x - 3, y - 3, x + img.width + 2, y + img.height + 2],
                outline=(96, 106, 122), width=3)

    # generic source chip — "the filing", never the vendor
    font = ImageFont.truetype(str(settings.fonts_dir / "DejaVuSansMono-Bold.ttf"),
                              max(int(H * 0.026), 14))
    pad = int(H * 0.012)
    tw = d.textlength(FILING_LABEL, font=font)
    cx0, cy0 = margin // 2, margin // 2
    d.rounded_rectangle(
        [cx0, cy0, cx0 + tw + 2 * pad, cy0 + font.size + 2 * pad],
        radius=8, fill=(24, 28, 36), outline=(96, 106, 122), width=2,
    )
    d.text((cx0 + pad, cy0 + pad), FILING_LABEL, font=font, fill=(255, 205, 60))

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
