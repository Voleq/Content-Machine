import pytest

from pipeline.models import Verdict
from pipeline.parser_short import ScriptParseError, parse_short_script


def test_parse_valid_json(short_valid_json, settings):
    script, warnings = parse_short_script(short_valid_json, settings)
    assert script.verdict is Verdict.OVERVALUED
    assert script.ticker == "EXMPL"
    assert not any("anchor" in w for w in warnings)


def test_parse_code_fenced_with_prose(fixtures_dir, settings):
    raw = (fixtures_dir / "scripts" / "short_fenced.txt").read_text()
    script, _ = parse_short_script(raw, settings)
    assert script.verdict is Verdict.CASH_COW
    assert script.highlights[0].color.value == "green"


def test_parse_smart_quotes(fixtures_dir, settings):
    raw = (fixtures_dir / "scripts" / "short_smart_quotes.txt").read_text()
    script, _ = parse_short_script(raw, settings)
    assert script.verdict is Verdict.DEAD_MONEY
    assert "transformation" in script.hook_text


def test_parse_trailing_commas(short_valid_json, settings):
    raw = short_valid_json.replace('"cta_text": "Screenshot this before earnings."',
                                   '"cta_text": "Screenshot this before earnings.",')
    script, _ = parse_short_script(raw, settings)
    assert script.ticker == "EXMPL"


def test_reject_bad_enum(fixtures_dir, settings):
    raw = (fixtures_dir / "scripts" / "short_bad_enum.json").read_text()
    with pytest.raises(ScriptParseError, match="verdict"):
        parse_short_script(raw, settings)


def test_reject_bad_line_index(fixtures_dir, settings):
    raw = (fixtures_dir / "scripts" / "short_bad_index.json").read_text()
    with pytest.raises(ScriptParseError, match="line_index"):
        parse_short_script(raw, settings)


def test_reject_over_budget_before_spend(short_valid_json, settings):
    tight = settings.model_copy(update={"short_max_chars": 100})
    with pytest.raises(ScriptParseError, match="budget"):
        parse_short_script(short_valid_json, tight)


def test_reject_non_json(settings):
    with pytest.raises(ScriptParseError, match="No JSON"):
        parse_short_script("here is your script: buy low sell high", settings)


def test_reject_unbalanced(settings):
    with pytest.raises(ScriptParseError, match="not closed"):
        parse_short_script('{"ticker": "X", "format": "short"', settings)


def test_reject_empty(settings):
    with pytest.raises(ScriptParseError, match="Empty"):
        parse_short_script("   \n ", settings)


def test_warning_on_missing_anchor(short_valid_json, settings):
    raw = short_valid_json.replace('"anchor_word": "cash"', '"anchor_word": "zebra"')
    script, warnings = parse_short_script(raw, settings)
    assert script.missing_anchor_words() == ["zebra"]
    assert any("zebra" in w and "fallback" in w for w in warnings)


def test_warning_on_word_count(short_valid_json, settings):
    _, warnings = parse_short_script(short_valid_json, settings)
    assert any("words" in w for w in warnings)  # fixture is ~120 words, target is 140-160


def test_braces_inside_strings_survive_extraction(settings, short_valid_json):
    raw = "Note: JSON follows. {not the object}... just kidding:\n" + short_valid_json
    # the first '{' opens a fake object; the extractor must still find a
    # balanced block — the fake one — and fail loudly on schema, not crash
    with pytest.raises(ScriptParseError):
        parse_short_script(raw, settings)
