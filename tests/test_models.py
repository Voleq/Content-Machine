import json

import pytest
from pydantic import ValidationError

from pipeline.models import (
    Candidate,
    CostReport,
    HighlightColor,
    Lane,
    RefinitivAudit,
    ShortScript,
    StampDirection,
    Verdict,
)


def test_short_script_valid(short_valid_json: str):
    script = ShortScript.model_validate(json.loads(short_valid_json))
    assert script.ticker == "EXMPL"
    assert script.verdict is Verdict.OVERVALUED
    assert len(script.data_block) == 5
    assert script.highlights[0].line_index == 2
    assert script.highlights[0].color is HighlightColor.RED
    assert script.stamps[0].end_offset() == 3.0
    assert script.missing_anchor_words() == []
    assert script.char_count <= 800


def test_short_script_rejects_bad_line_index(fixtures_dir):
    raw = json.loads((fixtures_dir / "scripts" / "short_bad_index.json").read_text())
    with pytest.raises(ValidationError, match="line_index"):
        ShortScript.model_validate(raw)


def test_short_script_rejects_bad_verdict(fixtures_dir):
    raw = json.loads((fixtures_dir / "scripts" / "short_bad_enum.json").read_text())
    with pytest.raises(ValidationError):
        ShortScript.model_validate(raw)


def test_short_script_requires_stamp(short_valid_json: str):
    raw = json.loads(short_valid_json)
    raw["visual_directions"] = [d for d in raw["visual_directions"] if d["type"] != "stamp"]
    with pytest.raises(ValidationError, match="stamp"):
        ShortScript.model_validate(raw)


def test_short_script_hook_length_cap(short_valid_json: str):
    raw = json.loads(short_valid_json)
    raw["hook_text"] = "x" * 91
    with pytest.raises(ValidationError):
        ShortScript.model_validate(raw)


def test_verdict_polarity():
    assert not Verdict.TOXIC.is_laudatory
    assert Verdict.CASH_COW.is_laudatory
    assert len([v for v in Verdict if v.is_laudatory]) == 5
    assert len(list(Verdict)) == 10


def test_stamp_anchor_end_minus_parsing():
    s = StampDirection(type="stamp", label=Verdict.TOXIC, anchor="end_minus_2.5")
    assert s.end_offset() == 2.5
    s2 = StampDirection(type="stamp", label=Verdict.TOXIC, anchor="collapse")
    assert s2.end_offset() is None


def test_refinitiv_missing_classification():
    audit = RefinitivAudit(values={"company_name": "X", "price": 1.0})
    assert "ticker" in audit.blocking_missing
    assert "pe_ratio" in audit.warning_missing
    assert "pe_ratio" not in audit.blocking_missing


def test_refinitiv_prompt_block():
    audit = RefinitivAudit(values={"company_name": "X", "price": 10.0})
    block = audit.as_prompt_block()
    assert "[identity]" in block and "company_name = X" in block


def test_cost_report_render_text():
    report = CostReport(
        ticker="EXMPL",
        fmt="short",
        words=152,
        chars=784,
        tts_cached=False,
        est_tts_usd=0.12,
        data_block_lines=4,
        stamp="TOXIC",
        highlight_note='Highlight -> line 3 "cash flow" ✓ (anchor found)',
        est_render_minutes=0.7,
        mtd_spend_usd=3.10,
        monthly_cap_usd=50.0,
    )
    text = report.render_text()
    assert "EXMPL — SHORT — ready to render" in text
    assert "$0.12" in text and "$3.10 / $50.00" in text
    assert report.approvable

    report.blocking.append("missing screenshot")
    assert not report.approvable
    assert "BLOCKED" in report.render_text()


def test_candidate_why():
    c = Candidate(
        ticker="ABC",
        lane=Lane.TRENDING,
        score=0.9,
        reasons=["+18% today", "ST #3 trending", "vol 4× avg"],
    )
    assert c.why == "+18% today · ST #3 trending · vol 4× avg"
