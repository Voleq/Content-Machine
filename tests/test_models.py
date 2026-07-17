import json

import pytest
from pydantic import ValidationError

from pipeline.models import (
    Candidate,
    CompanyData,
    CostReport,
    Lane,
    ShortScript,
    VisualPlanItem,
)


def test_short_script_valid(short_valid_json: str):
    script = ShortScript.model_validate(json.loads(short_valid_json))
    assert script.ticker == "EXMPL"
    assert len(script.headlines) == 2
    assert len(script.numbers) == 4
    assert all(len(r.values) == 5 for r in script.numbers), "multi-year rows"
    assert script.years == ["2021", "2022", "2023", "2024", "2025"]
    assert script.meme is not None and script.meme.key == "fomo-stages-wish-i-bought-doodle"
    assert script.missing_anchor_words() == []
    assert script.char_count <= 1200
    assert "noise" in script.conclusion.lower()


def test_short_script_rejects_bad_row_index(fixtures_dir):
    raw = json.loads((fixtures_dir / "scripts" / "short_bad_index.json").read_text())
    with pytest.raises(ValidationError, match="row_index"):
        ShortScript.model_validate(raw)


def test_short_script_rejects_four_headlines(fixtures_dir):
    raw = json.loads((fixtures_dir / "scripts" / "short_bad_headlines.json").read_text())
    with pytest.raises(ValidationError, match="headlines"):
        ShortScript.model_validate(raw)


def test_short_script_requires_multi_year_numbers(short_valid_json: str):
    raw = json.loads(short_valid_json)
    raw["numbers"] = [{"label": "Revenue", "values": ["$496M"]}]  # single year
    with pytest.raises(ValidationError):
        ShortScript.model_validate(raw)


def test_short_script_conclusion_is_free_text(short_valid_json: str):
    """No verdict enum anywhere — the conclusion is prose."""
    raw = json.loads(short_valid_json)
    raw["conclusion"] = "Somewhere between noise and a cry for help."
    script = ShortScript.model_validate(raw)
    assert script.conclusion.startswith("Somewhere")
    import pipeline.models as models

    assert not hasattr(models, "Verdict"), "the verdict system is deleted"


def test_short_script_hook_length_cap(short_valid_json: str):
    raw = json.loads(short_valid_json)
    raw["hook_text"] = "x" * 91
    with pytest.raises(ValidationError):
        ShortScript.model_validate(raw)


def test_short_script_anchor_words_include_cutaways(short_valid_json: str):
    script = ShortScript.model_validate(json.loads(short_valid_json))
    anchors = script.anchor_words()
    assert "today" in anchors and "wider" in anchors
    assert "vertical" in anchors  # the meme anchor


def test_company_data_missing_classification():
    data = CompanyData(values={"company_name": "X", "price": 1.0})
    assert "ticker" in data.blocking_missing
    assert "pe_ttm" in data.warning_missing
    assert "pe_ttm" not in data.blocking_missing
    assert "short_interest" in data.warning_missing, "ownership is optional, never blocking"


def test_company_data_prompt_block_with_history():
    data = CompanyData(
        values={"company_name": "X", "price": 10.0},
        history_years=["FY-1", "FY-0"],
        history={"revenue": [100.0, 120.0], "fcf": [None, None]},
    )
    block = data.as_prompt_block()
    assert "[identity]" in block and "company_name = X" in block
    assert "[history" in block and "FY-1 | FY-0" in block
    assert "revenue: 100 | 120" in block
    assert "fcf" not in block.split("[history")[1], "all-empty history rows are omitted"
    assert data.has_history


def test_company_data_without_history():
    data = CompanyData(values={"company_name": "X"})
    assert not data.has_history
    assert "[history" not in data.as_prompt_block()


def test_cost_report_render_text_short():
    report = CostReport(
        ticker="EXMPL",
        fmt="short",
        words=152,
        chars=784,
        tts_cached=False,
        est_tts_usd=0.12,
        headline_count=2,
        numbers_rows=4,
        numbers_years=5,
        annotation_note='Scribble -> chart "today" ✓ (anchor found)',
        est_render_minutes=0.7,
        mtd_spend_usd=3.10,
        monthly_cap_usd=50.0,
    )
    text = report.render_text()
    assert "EXMPL — SHORT — ready to render" in text
    assert "$0.12" in text and "$3.10 / $50.00" in text
    assert "Headlines: 2" in text and "4 rows × 5yr" in text
    assert report.approvable

    report.blocking.append("missing screenshot")
    assert not report.approvable
    assert "BLOCKED" in report.render_text()


def test_cost_report_render_text_long_visual_buckets():
    report = CostReport(
        ticker="EXMPL", fmt="long", words=1800, chars=9000,
        tts_cached=True, est_tts_usd=0.0,
        visuals=[
            VisualPlanItem(key="clown", kind="clip", source="library"),
            VisualPlanItem(key="q", kind="img", source="wikimedia"),
            VisualPlanItem(key="x", kind="clip", source="cache"),
            VisualPlanItem(key="y", kind="clip", source="filler"),
        ],
        filing_overlays=2, meme_count=1, meme_cap=2,
        mtd_spend_usd=0.0, monthly_cap_usd=50.0,
    )
    text = report.render_text()
    assert "Visuals: 4 (owned 1 / cache 1 / fetched 1 / filler 1)" in text
    assert "Filing overlays: 2" in text and "Memes: 1/2" in text


def test_candidate_why():
    c = Candidate(
        ticker="ABC",
        lane=Lane.TRENDING,
        score=0.9,
        reasons=["+18% today", "ST #3 trending", "vol 4× avg"],
    )
    assert c.why == "+18% today · ST #3 trending · vol 4× avg"
