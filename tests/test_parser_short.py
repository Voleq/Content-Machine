import json

import pytest

from pipeline.models import ChartStyle, TagType
from pipeline.parser_short import ScriptParseError, parse_short_script


def test_parse_valid_json(short_valid_json, settings):
    script, warnings = parse_short_script(short_valid_json, settings)
    assert script.ticker == "EXMPL"
    assert len(script.headlines) == 2
    assert not any("anchor" in w for w in warnings)


def test_inline_plate_and_scribble_stripped_and_anchored(short_doodles_json, settings):
    script, warnings = parse_short_script(short_doodles_json, settings)
    # tags are stripped from the spoken/captioned text
    assert "[" not in script.audio_script and "]" not in script.audio_script
    assert "PLATE" not in script.audio_script and "SCRIBBLE" not in script.audio_script
    plates = [e for e in script.inline_events if e.type is TagType.PLATE]
    scribbles = script.scribble_events()
    assert [e.payload for e in plates] == ["shorts/hook-card-t2"]
    assert [e.payload for e in scribbles] == ["scrawl-oval-tight -> Net income"]
    # offsets index the CLEAN audio_script (the word right after each tag)
    for e in plates + scribbles:
        assert e.type in (TagType.PLATE, TagType.SCRIBBLE)
        assert 0 <= e.char_offset <= len(script.audio_script)
    after = script.audio_script[plates[0].char_offset:].lstrip()
    assert after.startswith("The news")


def test_chart_style_marker_parsed(short_doodles_json, settings):
    script, _ = parse_short_script(short_doodles_json, settings)
    assert script.chart_style is ChartStyle.MARKER


def test_chart_style_defaults_to_the_house_language(short_valid_json, settings):
    """A script that says nothing gets the marker chart.

    The default was CLEAN, and the short holds its chart from the stage open
    to the gut check — one of the longest single holds in the video. So unless
    a writer thought to ask, every short spent that hold on the machine-drawn
    card in a channel whose whole argument is that a person drew this.
    """
    script, _ = parse_short_script(short_valid_json, settings)
    assert script.chart_style is ChartStyle.MARKER


def test_clean_is_still_selectable(short_valid_json, settings):
    """Two chart STYLES is fine — precision is a legitimate register."""
    import json

    data = json.loads(short_valid_json)
    data["chart_style"] = "clean"
    script, _ = parse_short_script(json.dumps(data), settings)
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
        "years": ["FY21", "FY22", "FY23", "FY24", "FY25", "LTM"],
        "numbers": [{"label": "Rev", "values": ["", "", "", "", "$1M", "$2M"]}],
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
        "years": ["FY21", "FY22", "FY23", "FY24", "FY25", "LTM"],
        "numbers": [{"label": "Rev", "values": ["", "", "", "", "$1M", "$2M"]}],
        "numbers_comment": "flat", "conclusion": "Noise.",
    }
    script, warnings = parse_short_script(json.dumps(data), settings)
    assert script.scribble_events() == []
    assert any("scribble" in w.lower() and "malformed" in w.lower() for w in warnings)


def _short_with(audio_script: str) -> str:
    import json

    return json.dumps({
        "ticker": "EXMPL", "format": "short",
        "hook_text": "A muted hook line here.",
        "audio_script": audio_script,
        "move_summary": "+5% today",
        "headlines": [{"text": "H", "meaning": "M"}],
        "years": ["FY21", "FY22", "FY23", "FY24", "FY25", "LTM"],
        "numbers": [{"label": "Rev", "values": ["", "", "", "", "$1M", "$2M"]}],
        "numbers_comment": "flat", "conclusion": "Noise.",
    })
def test_delivery_direction_reaches_the_voice_instead_of_the_floor(settings):
    """[BEAT]/[SIGH]/[FLAT]/[DRY] were documented in the prompt and dropped by
    the parser, so TTS got unpunctuated text and every short came out flat.
    They never reach the screen — they reach the request."""
    from pipeline.models import DELIVERY_TAG_TYPES

    script, warnings = parse_short_script(
        _short_with("The number lands. [BEAT] It is not good. [DRY] Noise."),
        settings)
    for tag in ("[BEAT]", "[DRY]"):
        assert tag not in script.audio_script
    delivery = [e for e in script.inline_events if e.type in DELIVERY_TAG_TYPES]
    assert len(delivery) == 2
    assert all(e.payload == "" for e in delivery)
    assert not any("not allowed here" in w for w in warnings)


def test_a_script_with_no_delivery_direction_is_called_out(settings):
    script, warnings = parse_short_script(
        _short_with("A flat sentence with no direction at all. Noise."), settings)
    assert not script.delivery_events()
    assert any("delivery direction" in w for w in warnings)
def test_the_showcase_fixture_leaves_no_box_empty(short_valid_json, settings):
    """The fixture the sample MP4 is built from, and the first thing anyone
    reads to learn the format. It was demonstrating the bug."""
    _, warnings = parse_short_script(short_valid_json, settings)
    assert [w for w in warnings if "no value" in w] == []


def test_a_tag_the_short_cannot_act_on_is_still_refused(settings):
    """Looser is not open season: [SOUND] claims nothing on a short's frame
    and is stripped with a warning, as it always was."""
    script, warnings = parse_short_script(
        _short_with("A line with a sound cue [SOUND: buzzer] in it. Noise."),
        settings)
    assert "[SOUND" not in script.audio_script
    assert script.inline_events == []
    assert any("not allowed here" in w for w in warnings)
    assert any("not allowed" in w for w in warnings)


def test_parse_code_fenced_with_prose(fixtures_dir, settings):
    raw = (fixtures_dir / "scripts" / "short_fenced.txt").read_text(encoding="utf-8")
    script, _ = parse_short_script(raw, settings)
    assert script.ticker == "BORV"
    assert "signal" in script.conclusion.lower()  # the gritted-teeth positive path
    assert script.numbers[3].label == "Shares out"


def test_parse_smart_quotes(fixtures_dir, settings):
    raw = (fixtures_dir / "scripts" / "short_smart_quotes.txt").read_text(encoding="utf-8")
    script, _ = parse_short_script(raw, settings)
    assert script.ticker == "DEDM"
    assert "transformation" in script.hook_text


def test_parse_trailing_commas(short_valid_json, settings):
    raw = short_valid_json.replace("]\n}", "],\n}")  # comma after the last field
    assert raw != short_valid_json
    script, _ = parse_short_script(raw, settings)
    assert script.ticker == "EXMPL"


def test_reject_four_headlines(fixtures_dir, settings):
    raw = (fixtures_dir / "scripts" / "short_bad_headlines.json").read_text(encoding="utf-8")
    with pytest.raises(ScriptParseError, match="headlines"):
        parse_short_script(raw, settings)


def test_reject_bad_row_index(fixtures_dir, settings):
    raw = (fixtures_dir / "scripts" / "short_bad_index.json").read_text(encoding="utf-8")
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
    # shrink the script well under the ~180-word floor to force the warning
    import json

    data = json.loads(short_valid_json)
    data["audio_script"] = " ".join(data["audio_script"].split()[:40])
    _, warnings = parse_short_script(json.dumps(data), settings)
    assert any("words" in w for w in warnings)


def test_warning_on_thin_history(short_valid_json, settings):
    # Edited through JSON, not through a string match on the fixture's
    # formatting — the literal broke the moment the fixture was re-indented.
    data = json.loads(short_valid_json)
    for row in data["numbers"]:
        if row["label"] == "Revenue":
            # Six periods, two of them carrying a figure: the shape of a
            # company with two years of history, not a narrower sheet.
            row["values"] = ["", "", "", "", "$491M", "$496M"]
    raw = json.dumps(data)
    _, warnings = parse_short_script(raw, settings)
    assert any("fewer than 3 years" in w for w in warnings)


def test_show_your_work_preamble_before_json(settings, short_valid_json):
    """The restructured SHORT prompt emits the angle/hooks/tags reasoning as
    prose FIRST — even with stray braces — then the JSON. The extractor must
    skip the prose (and any fake object) and find the real script object."""
    raw = (
        "ANGLE & NUMBERS: a plateau in a costume {this brace is not the object}.\n"
        "HOOK OPTIONS:\n1. \"x\"\n2. \"y\" ★\n"
        "Here is the script object:\n" + short_valid_json
    )
    script, _ = parse_short_script(raw, settings)
    assert script.ticker == "EXMPL" and script.format == "short"


def test_unclosed_json_still_rejected(settings):
    with pytest.raises(ScriptParseError):
        parse_short_script('prose then {"ticker": "EXMPL", "format": "short"', settings)


def test_a_bare_show_article_survives_the_parser(settings, short_valid_json):
    """`[SHOW ARTICLE]` means something with no payload at all.

    Every other tag needs a key, so the parser dropped any tag without one —
    which meant the writer had to paste a URL for the highest-credibility
    visual the format has, and so it was never used. The renderer resolves the
    link off the export's own news rows; the tag only has to reach it.
    """
    import json

    data = json.loads(short_valid_json)
    data["audio_script"] = "The news is a partnership. [SHOW ARTICLE] " + \
        data["audio_script"]
    script, warnings = parse_short_script(json.dumps(data), settings)
    articles = [e for e in script.inline_events
                if e.type is TagType.SHOW_ARTICLE]
    assert len(articles) == 1
    assert articles[0].payload == ""
    assert not any("carries no key" in w for w in warnings)
def _thin(short_valid_json: str, *tags: str) -> str:
    """The fixture with its beat library stripped out, plus `tags`.

    The committed fixture draws every beat it has, which is the point of it —
    so the thin case has to be built rather than borrowed.
    """
    import json
    import re

    data = json.loads(short_valid_json)
    stripped = re.sub(r"\[PROP:[^\]]*\]\s*", "", data["audio_script"])
    assert "[PROP" not in stripped
    data["audio_script"] = " ".join(tags) + " " + stripped
    return json.dumps(data)
def test_the_reach_warning_never_blocks(settings, short_valid_json):
    """A thin script is a judgement call, not a defect. It parses, it renders,
    and the operator decides — a gate here would teach gate-skipping."""
    from pipeline.cost import SpendLedger, build_short_report
    from pipeline.tts import TTSEngine

    script, warnings = parse_short_script(_thin(short_valid_json), settings)
    report = build_short_report(script, warnings, settings,
                                SpendLedger(settings), TTSEngine(settings))
    assert report.approvable
    assert not any("beat-library" in b for b in report.blocking)
    assert any("beat-library" in w for w in report.warnings)

# --------------------------------------------------------------------------
# The plate tag, in the short.
# --------------------------------------------------------------------------


def test_the_short_grammar_carries_plates_and_strips_them_from_the_text(
        short_valid_json, settings):
    """[PLATE] is parsed, resolved and removed from what gets spoken."""
    script, _ = parse_short_script(short_valid_json, settings)
    plates = [e for e in script.inline_events if e.type is TagType.PLATE]
    assert len(plates) >= 4
    assert all("/" in e.payload for e in plates), "payloads are registry keys"
    assert all(e.values for e in plates), "every plate carries its own content"
    assert "[PLATE" not in script.audio_script
    assert "|" not in script.audio_script


def test_a_plate_that_names_a_slot_the_kit_does_not_have_is_reported(
        short_valid_json, settings):
    import json

    data = json.loads(short_valid_json)
    data["audio_script"] = (
        "EXMPL is up. [PLATE: hook-card-t1 | ticker=EXMPL | nonesuch=x] "
        + data["audio_script"])
    _, warnings = parse_short_script(json.dumps(data), settings)
    assert any("has no slot 'nonesuch'" in w for w in warnings), warnings


def test_a_row_that_does_not_match_its_header_is_reported(
        short_valid_json, settings):
    import json

    data = json.loads(short_valid_json)
    data["audio_script"] = (
        "EXMPL is up. [PLATE: numbers-sheet-4r-9x16 | unit=$M "
        "| head=FY21,FY22,FY23,FY24,FY25,LTM | label-1=Revenue | row-1=1,2,3] "
        + data["audio_script"])
    _, warnings = parse_short_script(json.dumps(data), settings)
    assert any("3 figures against 6 period heads" in w for w in warnings), warnings


def test_a_landscape_plate_is_refused_in_a_vertical_cut(
        short_valid_json, settings):
    """9:16 is a re-author, never a crop."""
    import json

    data = json.loads(short_valid_json)
    data["audio_script"] = (
        "EXMPL is up. [PLATE: numbers-sheet-6r-16x9 | unit=$M] "
        + data["audio_script"])
    _, warnings = parse_short_script(json.dumps(data), settings)
    assert any("16x9" in w and "9x16" in w for w in warnings), warnings
