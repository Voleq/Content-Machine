import pytest

from pipeline.models import ChartStyle, TagType
from pipeline.parser_short import ScriptParseError, parse_short_script


def test_parse_valid_json(short_valid_json, settings):
    script, warnings = parse_short_script(short_valid_json, settings)
    assert script.ticker == "EXMPL"
    assert len(script.headlines) == 2
    assert not any("anchor" in w for w in warnings)


def test_inline_doodle_and_scribble_stripped_and_anchored(short_doodles_json, settings):
    script, warnings = parse_short_script(short_doodles_json, settings)
    # tags are stripped from the spoken/captioned text
    assert "[" not in script.audio_script and "]" not in script.audio_script
    assert "DOODLE" not in script.audio_script and "SCRIBBLE" not in script.audio_script
    doodles = script.doodle_events()
    scribbles = script.scribble_events()
    assert [e.payload for e in doodles] == ["stick-staring-at-crash"]
    assert [e.payload for e in scribbles] == ["circle -> Net income"]
    # offsets index the CLEAN audio_script (the word right after each tag)
    for e in doodles + scribbles:
        assert e.type in (TagType.DOODLE, TagType.SCRIBBLE)
        assert 0 <= e.char_offset <= len(script.audio_script)
    after = script.audio_script[doodles[0].char_offset:].lstrip()
    assert after.startswith("The news")


def test_chart_style_marker_parsed(short_doodles_json, settings):
    script, _ = parse_short_script(short_doodles_json, settings)
    assert script.chart_style is ChartStyle.MARKER


def test_chart_style_defaults_clean(short_valid_json, settings):
    script, _ = parse_short_script(short_valid_json, settings)
    assert script.chart_style is ChartStyle.CLEAN


def test_budget_measured_on_clean_text(settings):
    import json

    # audio_script is 40 real chars + a big doodle tag; the tag must not count
    body = "The number is bad and the chart is worse, honestly. "
    padded = body + "[DOODLE: scribble-explosion] " + body
    data = {
        "ticker": "EXMPL", "format": "short",
        "hook_text": "Bad number, worse chart.",
        "audio_script": padded,
        "move_summary": "+10% today",
        "headlines": [{"text": "H", "meaning": "M"}],
        "years": ["2024", "2025"],
        "numbers": [{"label": "Rev", "values": ["$1M", "$2M"]}],
        "numbers_comment": "flat", "conclusion": "Noise.",
    }
    tight = settings.model_copy(update={"short_max_chars": len(padded) - 5})
    # the clean text (tag stripped) is shorter than the raw, so it fits
    script, _ = parse_short_script(json.dumps(data), tight)
    assert "[DOODLE" not in script.audio_script
    assert script.char_count <= tight.short_max_chars


def test_malformed_inline_scribble_warned_and_skipped(settings):
    import json

    data = {
        "ticker": "EXMPL", "format": "short",
        "hook_text": "A hook that works muted.",
        "audio_script": "Numbers first. [SCRIBBLE: wobble -> nothing] Then the point. Noise.",
        "move_summary": "+5% today",
        "headlines": [{"text": "H", "meaning": "M"}],
        "years": ["2024", "2025"],
        "numbers": [{"label": "Rev", "values": ["$1M", "$2M"]}],
        "numbers_comment": "flat", "conclusion": "Noise.",
    }
    script, warnings = parse_short_script(json.dumps(data), settings)
    assert script.scribble_events() == []
    assert any("scribble" in w.lower() and "malformed" in w.lower() for w in warnings)


def test_non_overlay_inline_tag_stripped(settings):
    import json

    data = {
        "ticker": "EXMPL", "format": "short",
        "hook_text": "A muted hook line here.",
        "audio_script": "Here is a clip tag [CLIP: dumpster_fire] that does not belong. Noise.",
        "move_summary": "+5% today",
        "headlines": [{"text": "H", "meaning": "M"}],
        "years": ["2024", "2025"],
        "numbers": [{"label": "Rev", "values": ["$1M", "$2M"]}],
        "numbers_comment": "flat", "conclusion": "Noise.",
    }
    script, warnings = parse_short_script(json.dumps(data), settings)
    assert "[CLIP" not in script.audio_script, "non-overlay tags stripped from SHORT"
    assert script.inline_events == []
    assert any("not allowed" in w for w in warnings)


def test_parse_code_fenced_with_prose(fixtures_dir, settings):
    raw = (fixtures_dir / "scripts" / "short_fenced.txt").read_text()
    script, _ = parse_short_script(raw, settings)
    assert script.ticker == "BORV"
    assert "signal" in script.conclusion.lower()  # the gritted-teeth positive path
    assert script.numbers[3].label == "Shares out"


def test_parse_smart_quotes(fixtures_dir, settings):
    raw = (fixtures_dir / "scripts" / "short_smart_quotes.txt").read_text()
    script, _ = parse_short_script(raw, settings)
    assert script.ticker == "DEDM"
    assert "transformation" in script.hook_text


def test_parse_trailing_commas(short_valid_json, settings):
    raw = short_valid_json.replace("]\n}", "],\n}")  # comma after the last field
    assert raw != short_valid_json
    script, _ = parse_short_script(raw, settings)
    assert script.ticker == "EXMPL"


def test_reject_four_headlines(fixtures_dir, settings):
    raw = (fixtures_dir / "scripts" / "short_bad_headlines.json").read_text()
    with pytest.raises(ScriptParseError, match="headlines"):
        parse_short_script(raw, settings)


def test_reject_bad_row_index(fixtures_dir, settings):
    raw = (fixtures_dir / "scripts" / "short_bad_index.json").read_text()
    with pytest.raises(ScriptParseError, match="row_index"):
        parse_short_script(raw, settings)


def test_reject_over_budget_before_spend(short_valid_json, settings):
    tight = settings.model_copy(update={"short_max_chars": 100})
    with pytest.raises(ScriptParseError, match="budget"):
        parse_short_script(short_valid_json, tight)


def test_reject_vendor_name_on_screen(short_valid_json, settings):
    """§3: nothing on-screen may name the data vendor."""
    raw = short_valid_json.replace(
        '"move_summary": "+29% today · 5× average volume"',
        '"move_summary": "+29% today per Refinitiv"',
    )
    with pytest.raises(ScriptParseError, match="vendor"):
        parse_short_script(raw, settings)


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
    raw = short_valid_json.replace('"anchor_word": "today"', '"anchor_word": "zebra"')
    script, warnings = parse_short_script(raw, settings)
    assert script.missing_anchor_words() == ["zebra"]
    assert any("zebra" in w and "fallback" in w for w in warnings)


def test_warning_on_word_count(short_valid_json, settings):
    # shrink the script well under the ~140-word floor to force the warning
    raw = short_valid_json.replace(
        "on five times average volume, so the internet has decided it is a "
        "technology company again. The news: an AI partnership. A press "
        "release, not a purchase order. Plus squeeze chatter, because eleven "
        "percent of the float was betting against it. Gut check. I read the "
        "filings so you don't have to. ",
        "",
    )
    assert raw != short_valid_json
    _, warnings = parse_short_script(raw, settings)
    assert any("words" in w for w in warnings)


def test_warning_on_thin_history(short_valid_json, settings):
    raw = short_valid_json.replace(
        '{"label": "Revenue", "values": ["$400M", "$452M", "$471M", "$491M", "$496M"]}',
        '{"label": "Revenue", "values": ["$491M", "$496M"]}',
    )
    _, warnings = parse_short_script(raw, settings)
    assert any("fewer than 3 years" in w for w in warnings)


def test_braces_inside_strings_survive_extraction(settings, short_valid_json):
    raw = "Note: JSON follows. {not the object}... just kidding:\n" + short_valid_json
    # the first '{' opens a fake object; the extractor must still find a
    # balanced block — the fake one — and fail loudly on schema, not crash
    with pytest.raises(ScriptParseError):
        parse_short_script(raw, settings)
