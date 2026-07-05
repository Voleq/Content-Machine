"""Two-sheet company-data reader (§3): Latest snapshot + 5y History,
field-name matching only, CSV = snapshot-only, generic screenshot label."""

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


def test_load_both_sheets(workspace):
    data = load_company_data(workspace)
    assert data.get("ticker") == "EXMPL"
    assert data.get("ps_ratio") == 62.0
    assert data.get("website") == "https://www.example.com"
    assert data.blocking_missing == []

    assert data.has_history
    assert data.history_years == ["FY2021", "FY2022", "FY2023", "FY2024", "FY2025"]
    assert data.history_row("revenue") == [400e6, 452e6, 471e6, 491e6, 496e6]
    assert data.history_row("net_income")[-1] == -89e6
    assert set(data.history) <= set(HISTORY_FIELDS)


def test_prompt_block_carries_history(workspace):
    data = load_company_data(workspace)
    block = data.as_prompt_block()
    assert "[history" in block
    assert "revenue:" in block and "FY2021" in block
    assert "refinitiv" not in block.lower(), "the vendor is never named"


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
    assert data.get("pe_ratio") is None       # '#N/A' in the fixture
    assert "pe_ratio" in data.warning_missing


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
    assert len(set(corner.getdata())) > 2, "label chip must be present"


def test_list_screenshots_excludes_exports(workspace):
    (workspace / "income_statement.png").write_bytes(b"png")
    (workspace / "_hidden.png").write_bytes(b"png")
    shots = list_screenshots(workspace)
    assert shots == ["income_statement.png"]
