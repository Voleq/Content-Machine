"""Regenerate binary/derived fixtures committed to the repo.

Run from the repo root:  .venv/bin/python scripts/gen_fixtures.py

Produces:
  templates/refinitiv_audit_template.xlsx   (the Excel add-in data contract)
  fixtures/refinitiv/data_refinitiv.xlsx    (filled example for EXMPL)
  fixtures/refinitiv/data_refinitiv.csv     (CSV flavour of the same)
  fixtures/tts/alignment_sample.json        (ElevenLabs-style char alignment)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.models import REFINITIV_FIELDS  # noqa: E402

EXMPL_VALUES: dict[str, object] = {
    # identity
    "company_name": "Example Corp",
    "ticker": "EXMPL",
    "exchange": "NASDAQ",
    "sector": "Technology",
    "currency": "USD",
    "as_of_date": "2026-07-01",
    # size
    "price": 84.20,
    "market_cap": 30_700_000_000,
    "shares_outstanding": 364_600_000,
    "enterprise_value": 31_900_000_000,
    # growth
    "revenue_ttm": 496_000_000,
    "revenue_yoy_pct": 1.0,
    "revenue_cagr_3y_pct": 4.2,
    # margins
    "gross_margin_pct": 58.0,
    "operating_margin_pct": -12.0,
    "net_margin_pct": -18.0,
    "net_income_ttm": -89_000_000,
    # cash
    "operating_cf_ttm": -9_000_000,
    "capex_ttm": 6_000_000,
    "fcf_ttm": -15_000_000,
    "fcf_margin_pct": -3.0,
    "fcf_yield_pct": -3.0,
    # balance
    "cash_and_equivalents": 410_000_000,
    "total_debt": 1_450_000_000,
    "net_debt": 1_040_000_000,
    "net_debt_to_ebitda": 9.8,
    "debt_to_equity": 140.0,
    "interest_coverage": 0.9,
    # returns
    "roic_pct": -6.5,
    "roe_pct": -14.0,
    # valuation
    "pe_ratio": None,  # negative earnings -> N/A, a realistic hole
    "ps_ratio": 62.0,
    "ev_ebitda": None,
    "pb_ratio": 18.0,
    "p_fcf": None,
    # dilution
    "shares_outstanding_yoy_pct": 6.0,
    # optional
    "dividend_yield_pct": 0.0,
    "buyback_yield_pct": 0.0,
    "short_interest_pct": 11.0,
}


def build_workbook(values: dict[str, object] | None) -> Workbook:
    """The fixed-layout 'Audit' sheet: A=field, B=value, C=group.

    In the operator's live template column B holds Refinitiv Excel add-in
    formulas (e.g. =TR($B$1,"TR.Revenue")); here it holds either example
    values (fixture) or blanks (template).
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "Audit"
    header_font = Font(bold=True)
    group_fill = PatternFill("solid", fgColor="1F2A36")
    group_font = Font(bold=True, color="FFFFFF")

    ws["A1"], ws["B1"], ws["C1"] = "field", "value", "group"
    for cell in ("A1", "B1", "C1"):
        ws[cell].font = header_font

    row = 2
    for group, fields in REFINITIV_FIELDS.items():
        for field in fields:
            ws.cell(row=row, column=1, value=field)
            if values is not None:
                val = values.get(field)
                ws.cell(row=row, column=2, value="#N/A" if val is None else val)
            ws.cell(row=row, column=3, value=group)
            if values is None:
                ws.cell(row=row, column=1).fill = group_fill
                ws.cell(row=row, column=1).font = group_font
            row += 1
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 24
    ws.column_dimensions["C"].width = 12
    return wb


def gen_alignment_fixture(path: Path) -> None:
    """ElevenLabs with-timestamps style character alignment for a sample text."""
    text = "The market pays sixty times sales."
    words = text.split(" ")
    chars: list[str] = []
    starts: list[float] = []
    ends: list[float] = []
    t = 0.25  # small lead-in silence
    per_char = 0.045
    for i, w in enumerate(words):
        for ch in w:
            chars.append(ch)
            starts.append(round(t, 3))
            t += per_char
            ends.append(round(t, 3))
        if i < len(words) - 1:
            chars.append(" ")
            starts.append(round(t, 3))
            t += 0.06  # pause between words
            ends.append(round(t, 3))
    payload = {
        "text": text,
        "alignment": {
            "characters": chars,
            "character_start_times_seconds": starts,
            "character_end_times_seconds": ends,
        },
    }
    path.write_text(json.dumps(payload, indent=2))


def main() -> None:
    tdir = ROOT / "templates"
    rdir = ROOT / "fixtures" / "refinitiv"
    adir = ROOT / "fixtures" / "tts"
    for d in (tdir, rdir, adir):
        d.mkdir(parents=True, exist_ok=True)

    build_workbook(None).save(tdir / "refinitiv_audit_template.xlsx")
    build_workbook(EXMPL_VALUES).save(rdir / "data_refinitiv.xlsx")

    csv_lines = ["field,value"]
    for group, fields in REFINITIV_FIELDS.items():
        for field in fields:
            val = EXMPL_VALUES.get(field)
            csv_lines.append(f"{field},{'#N/A' if val is None else val}")
    (rdir / "data_refinitiv.csv").write_text("\n".join(csv_lines) + "\n")

    gen_alignment_fixture(adir / "alignment_sample.json")
    print("fixtures written")


if __name__ == "__main__":
    main()
