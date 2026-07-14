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
