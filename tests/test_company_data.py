"""v3 company-data reader (§3): sheets read by NAME (Snapshot · History ·
Dashboard · Valuation · Peers), History period columns read dynamically
from the header row, CSV = snapshot-only, generic screenshot label."""

import pytest
from PIL import Image

from pipeline.company_data import (
    CompanyDataError,
    FILING_LABEL,
    find_export,
    list_screenshots,
    load_company_data,
    prepare_screenshot,
)
from pipeline.models import HISTORY_FIELDS


def test_load_snapshot_and_history(workspace):
    data = load_company_data(workspace)
    assert data.get("ticker") == "EXMPL"
    assert data.get("ps_ttm") == 62.0
    assert data.get("as_of_date") == "2026-07-01"
    assert data.blocking_missing == []

    assert data.has_history
    # periods are read dynamically from the header row (FY-4..FY-0, LTM)
    assert data.history_years == ["FY-4", "FY-3", "FY-2", "FY-1", "FY-0", "LTM"]
    assert data.history_row("revenue") == [400e6, 452e6, 471e6, 491e6, 496e6, 496e6]
    assert data.history_row("net_income")[-1] == -89e6
    assert set(data.history) <= set(HISTORY_FIELDS)


def test_dashboard_valuation_peers_surfaced(workspace):
    data = load_company_data(workspace)
    # the Dashboard summary — exactly what the numbers sheet reads
    assert data.dashboard_get("Net margin (LTM)") == -18.0
    assert data.dashboard_get("Profitable? (LTM NI>0)") == "no"
    assert data.dashboard_get("Diluting? (share CAGR>1%)") == "yes"
    # long-form context: bear/base/bull + peers
    assert data.has_valuation and len(data.valuation["scenarios"]) == 3
    assert data.valuation["current_price"] == 84.2
    assert data.has_peers and data.peers[0]["name"] == "Freightwave Systems Inc"


def test_news_parsing_skips_blanks_and_coerces_dates(workspace):
    data = load_company_data(workspace)
    # the blank spill row AND the NA-headline row are skipped
    assert len(data.news) == 4
    first = data.news[0]
    assert set(first) == {"date", "headline", "source", "url"}
    # real dates coerce to ISO day strings
    assert first["date"] == "2026-07-14"
    assert first["headline"].startswith("Example Corp posts record")
    assert first["url"] == "https://example.com/news/record-revenue"
    # every surviving row has a non-empty headline
    assert all(n["headline"] for n in data.news)
    # a news outlet as Source is fine; a data-terminal brand never reaches a field
    assert [n["source"] for n in data.news] == [
        "Reuters", "Bloomberg", "Associated Press", "CNBC",
    ]
    blob = " ".join(str(v) for n in data.news for v in n.values()).lower()
    for brand in ("refinitiv", "lseg", "capital iq"):
        assert brand not in blob


def test_peer_percentiles_parsing_and_block_separation(workspace):
    data = load_company_data(workspace)
    pcts = data.peer_percentiles
    assert len(pcts) == 8
    by_metric = {p["metric"]: p for p in pcts}
    # values + a 0-1 percentile fraction + direction + read
    pe = by_metric["P/E (TTM)"]
    assert pe["subject"] == 34.0 and pe["median"] == 37.5
    assert pe["percentile"] == 0.42 and pe["direction"] == "worse"
    assert pe["read"] == "mid-pack"
    rg = by_metric["Rev growth % (3Y CAGR)"]
    assert rg["direction"] == "better" and rg["read"] == "strong vs peers"
    assert rg["percentile"] == 0.80
    assert by_metric["P/S (TTM)"]["read"] == "expensive vs peers"
    assert all(0.0 <= p["percentile"] <= 1.0 for p in pcts)
    assert {p["direction"] for p in pcts} == {"better", "worse"}
    # the two blocks are DISTINCT: the auto peer table did not consume the
    # percentile rows, and the percentile reader did not grab peer names
    assert [p["name"] for p in data.peers] == [
        "Freightwave Systems Inc", "DepotOps Corp",
        "RouteLogic Holdings", "CargoCloud Inc",
    ]
    assert {p["name"] for p in data.peers}.isdisjoint(by_metric)


def test_valuation_wacc_and_reverse_dcf_keys(workspace):
    data = load_company_data(workspace)
    val = data.valuation
    # the bare 'WACC' row — NOT the 'WACC (auto — CAPM)' band title nor the
    # 'WACC −1%' / 'WACC +1%' sensitivity rows (Unicode-minus labels)
    assert val["wacc"] == 0.092
    # the reverse-DCF row, not the later 'Implied growth sensitivity …' title
    assert val["implied_growth"] == 0.061
    assert val["hist_fcf_cagr"] == 0.045
    assert val["rev_cagr"] == 0.12
    assert val["priced_vs_delivered"] == 0.016
    # a free-text verdict, kept verbatim as a string
    assert val["reverse_dcf_read"] == "market prices in MORE growth than history delivered"
    # the existing bear/base/bull scenario reader is untouched
    assert len(val["scenarios"]) == 3


def test_missing_news_sheet_degrades(workspace):
    # dropping the OPTIONAL News sheet must degrade (news == []), never raise
    from openpyxl import load_workbook

    xlsx = workspace / "dennis_data.xlsx"
    wb = load_workbook(xlsx)
    wb.remove(wb["News"])
    wb.save(xlsx)
    data = load_company_data(workspace)
    assert data.news == []
    # the other optional blocks are unaffected
    assert data.has_peers and len(data.peer_percentiles) == 8


def test_prompt_block_carries_history_and_dashboard(workspace):
    data = load_company_data(workspace)
    block = data.as_prompt_block()
    assert "[history" in block
    assert "revenue:" in block and "FY-0" in block
    assert "[dashboard" in block and "Net margin (LTM):" in block
    # the vendor is never named (only the RIC ticker itself may carry a dot)
    assert "refinitiv" not in block.lower() and "lseg" not in block.lower()


def test_csv_is_snapshot_only(workspace, fixtures_dir):
    (workspace / "dennis_data.xlsx").unlink()
    csv_src = fixtures_dir / "company_data" / "dennis_data.csv"
    (workspace / "dennis_data.csv").write_bytes(csv_src.read_bytes())
    data = load_company_data(workspace)
    assert data.get("ticker") == "EXMPL"
    assert not data.has_history, "CSV carries no history sheet"
    assert data.news == [] and data.peer_percentiles == []


def test_missing_export_raises(settings):
    empty = settings.workspace_dir / "NONE" / "2026-07-01"
    empty.mkdir(parents=True)
    assert find_export(empty) is None
    with pytest.raises(CompanyDataError, match="dennis_data"):
        load_company_data(empty)


def test_na_values_and_unknown_fields(workspace):
    data = load_company_data(workspace)
    assert data.get("pe_ttm") is None       # '#N/A' in the fixture
    assert "pe_ttm" in data.warning_missing


def test_the_value_column_is_found_however_the_template_titles_it(tmp_path):
    """The v3.1 template renamed `Value (auto)` to `Value (Capital IQ) MM`.

    An exact-match column lookup read ZERO snapshot fields off it — a workbook
    that was present, opened cleanly, and parsed to nothing, which then looks
    identical to "the operator never refreshed it". Match on the prefix.
    """
    from openpyxl import Workbook

    for title in ("Value (auto)", "Value", "Value (Capital IQ) MM",
                  "Value (Refinitiv)"):
        wb = Workbook()
        ws = wb.active
        ws.title = "Snapshot"
        ws.cell(row=6, column=2, value="field_key")
        ws.cell(row=6, column=3, value="Label")
        ws.cell(row=6, column=4, value=title)
        for i, (k, v) in enumerate([("company_name", "Example Inc"),
                                    ("ticker", "EXMPL"),
                                    ("as_of_date", "2026-07-01"),
                                    ("price", 12.5),
                                    ("market_cap", 1.0e9),
                                    ("shares_out", 8.0e7)]):
            ws.cell(row=7 + i, column=2, value=k)
            ws.cell(row=7 + i, column=4, value=v)
        d = tmp_path / title.replace(" ", "_").replace("(", "").replace(")", "")
        d.mkdir(parents=True)
        wb.save(d / "dennis_data.xlsx")

        data = load_company_data(d)
        assert data.get("company_name") == "Example Inc", f"{title!r} read nothing"
        assert data.blocking_missing == [], title


def test_the_shipped_template_parses_structurally(tmp_path):
    """Guard the whole contract: whatever revision of the template ships, its
    Snapshot sheet must still be readable by field_key."""
    import shutil
    from pathlib import Path

    template = Path(__file__).resolve().parents[1] / "templates" / "dennis_data_template.xlsx"
    d = tmp_path / "ws"
    d.mkdir(parents=True)
    shutil.copy(template, d / "dennis_data.xlsx")

    # The shipped template holds formulas with no cached values, so every value
    # reads None — but the KEYS must all be found, which is what broke.
    from pipeline.company_data import _read_snapshot
    from openpyxl import load_workbook
    from pipeline.models import ALL_DATA_FIELDS

    wb = load_workbook(d / "dennis_data.xlsx", data_only=True)
    pairs = _read_snapshot(wb["Snapshot"])
    wb.close()
    assert len(pairs) >= 40, f"only {len(pairs)} field_keys found in the template"
    unknown = [k for k in pairs if k not in ALL_DATA_FIELDS]
    assert not unknown, f"template has field_keys the model doesn't know: {unknown}"

    data = load_company_data(d)
    assert data.has_history
    assert data.history_years == ["FY-4", "FY-3", "FY-2", "FY-1", "FY-0", "LTM"]


def test_screenshot_gets_generic_filing_label(workspace, settings, tmp_path):
    src = tmp_path / "raw.png"
    Image.new("RGB", (1400, 800), (30, 34, 40)).save(src)
    out = prepare_screenshot(src, tmp_path / "norm.png", settings)
    img = Image.open(out)
    assert img.size == settings.long_resolution
    assert FILING_LABEL == "FROM THE 10-K"
    # the label chip is drawn in the top-left margin — the corner must no
    # longer be the plain canvas color
    corner = img.crop((0, 0, 200, 60))
    colors = corner.getcolors(maxcolors=4096)
    assert colors and len(colors) > 2, "label chip must be present"


def test_list_screenshots_excludes_exports(workspace):
    (workspace / "income_statement.png").write_bytes(b"png")
    (workspace / "_hidden.png").write_bytes(b"png")
    shots = list_screenshots(workspace)
    assert shots == ["income_statement.png"]
