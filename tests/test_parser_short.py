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


def test_chart_style_still_parses_though_nothing_draws_it(short_valid_json,
                                                          short_doodles_json,
                                                          settings):
    """There is one price chart now, the kit's, so `chart_style` selects
    nothing. It stays on the model because the script's hash covers it: an
    approval recorded against an older script must still match."""
    script, _ = parse_short_script(short_doodles_json, settings)
    assert script.chart_style is ChartStyle.MARKER
    script, _ = parse_short_script(short_valid_json, settings)
    assert script.chart_style is ChartStyle.MARKER
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


def test_fields_no_template_draws_are_reported_not_placed(short_valid_json,
                                                           settings):
    """A short draws neither scribbles nor a chosen chart style, so an anchor
    word for one is not checked, and the fields are named as unbound."""
    import json

    data = json.loads(short_valid_json.replace('"anchor_word": "today"',
                                               '"anchor_word": "zebra"'))
    data["chart_style"] = "clean"
    _, warnings = parse_short_script(json.dumps(data), settings)
    assert not any("zebra" in w for w in warnings)
    (unbound,) = [w for w in warnings if "no shot template binds" in w]
    assert "annotations" in unbound and "chart_style" in unbound


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


def test_show_article_is_retired_and_stripped(settings, short_valid_json):
    """Nothing drew it in either format, so it left the grammar. A writer who
    still types it is told so; the tag is stripped, never spoken or kept."""
    import json

    data = json.loads(short_valid_json)
    data["audio_script"] = "The news is a partnership. [SHOW ARTICLE] " + \
        data["audio_script"]
    script, warnings = parse_short_script(json.dumps(data), settings)
    assert not [e for e in script.inline_events
                if e.type is TagType.SHOW_ARTICLE]
    assert "SHOW ARTICLE" not in script.audio_script
    assert any("[SHOW ARTICLE] is no longer part of the grammar" in w
               for w in warnings), warnings


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
        "| head=FY22,FY23,FY24,FY25,LTM | label-1=Revenue | row-1=1,2,3] "
        + data["audio_script"])
    _, warnings = parse_short_script(json.dumps(data), settings)
    # Five periods on a phone's sheet since rebuild-41.
    assert any("3 figures against 5 period heads" in w for w in warnings), warnings


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


# ---------------------------------------------------------------------------
# Beat markers: `[BEAT: key]`
# ---------------------------------------------------------------------------

# Where each beat of the fixture starts, as a writer would mark it.
_MARKS = (
    ("EXMPL is up twenty nine", "hook"),
    ("The news is an AI", "headline"),
    ("A press release, not", "turn"),
    ("Revenue went four hundred", "numbers"),
    ("Then the share count.", "numbers_comment"),
    ("Eleven times earnings", "cheap_or_trap"),
    ("Noise. A press release", "conclusion"),
)


def _marked(short_valid_json: str, marks=_MARKS) -> str:
    data = json.loads(short_valid_json)
    text = data["audio_script"]
    for words, key in marks:
        assert text.count(words) == 1, words
        text = text.replace(words, f"[BEAT: {key}] {words}")
    data["audio_script"] = text
    return json.dumps(data)


def test_a_beat_marker_is_taken_out_and_never_reaches_the_voice(
        short_valid_json, settings):
    """The narration a marked script speaks is character for character the
    narration of the same script unmarked — the same TTS request, the same
    cache key, the same count against the budget."""
    plain, _ = parse_short_script(short_valid_json, settings)
    marked, _ = parse_short_script(_marked(short_valid_json), settings)
    assert "[BEAT:" not in marked.audio_script
    assert marked.audio_script == plain.audio_script
    assert marked.char_count == plain.char_count


def test_a_marker_is_not_a_pause(short_valid_json, settings):
    """A bare [BEAT] is performed; a keyed one would stop the voice at every
    beat boundary if it were filed beside the pauses."""
    plain, _ = parse_short_script(short_valid_json, settings)
    marked, _ = parse_short_script(_marked(short_valid_json), settings)
    assert ([(e.type, e.char_offset) for e in marked.delivery_events()]
            == [(e.type, e.char_offset) for e in plain.delivery_events()])
    assert ([(e.type, e.char_offset) for e in marked.inline_events]
            == [(e.type, e.char_offset) for e in plain.inline_events])


def test_each_marker_points_at_the_first_word_of_its_beat(
        short_valid_json, settings):
    marked, _ = parse_short_script(_marked(short_valid_json), settings)
    assert marked.beat_order() == [key for _w, key in _MARKS]
    for words, key in _MARKS:
        n = len(words.split())
        assert marked.words_after_mark(key, n).startswith(words)


def test_a_key_is_read_however_the_writer_spaced_it(short_valid_json,
                                                    settings):
    raw = _marked(short_valid_json, (("Eleven times earnings", "Cheap or trap"),
                                     ("Then the share count.", "numbers-comment")))
    script, _ = parse_short_script(raw, settings)
    assert script.beat_order() == ["numbers_comment", "cheap_or_trap"]


@pytest.mark.parametrize("marks,refusal", [
    ((("The news is an AI", "the-news"),), "names no beat"),
    ((("The news is an AI", "headline"), ("Revenue went four", "headline")),
     "more than once"),
    ((("EXMPL is up twenty nine", "move"),), "opens on"),
    ((("The news is an AI", "move"), ("Revenue went four", "hook")),
     "hook] comes after"),
])
def test_a_marker_the_render_could_not_act_on_is_refused_by_name(
        short_valid_json, settings, marks, refusal):
    with pytest.raises(ScriptParseError, match=refusal):
        parse_short_script(_marked(short_valid_json, marks), settings)


def test_a_beat_with_nothing_spoken_in_it_is_refused(short_valid_json,
                                                     settings):
    data = json.loads(short_valid_json)
    data["audio_script"] = data["audio_script"].replace(
        "The news is", "[BEAT: move] [BEAT: headline] The news is")
    with pytest.raises(ScriptParseError, match="nothing spoken after it"):
        parse_short_script(json.dumps(data), settings)


def test_an_unmarked_script_parses_as_it_always_did(short_valid_json,
                                                    settings):
    """Same narration, same events, and the same content hash — the hash is
    what an approval is recorded against and every render seed comes from."""
    import hashlib

    script, warnings = parse_short_script(short_valid_json, settings)
    assert script.beat_marks == []
    # The script as it serialised before the beat marks, the sources and the
    # long lane's `beside` on the tag existed.
    old = hashlib.sha256(script.model_dump_json(
        exclude={"beat_marks": True, "sources": True,
                 "inline_events": {"__all__": {"beside"}}}
    ).encode("utf-8")).hexdigest()[:16]
    assert script.content_sha() == old
    assert any("no beat markers" in w for w in warnings)


def test_a_marked_script_hashes_differently_from_the_same_script_unmarked(
        short_valid_json, settings):
    plain, _ = parse_short_script(short_valid_json, settings)
    marked, warnings = parse_short_script(_marked(short_valid_json), settings)
    assert marked.content_sha() != plain.content_sha()
    assert not any("no beat markers" in w for w in warnings)


def test_markers_from_two_formats_are_named_as_a_mix(short_valid_json,
                                                     settings):
    """`numbers_comment` is a short beat and `consequences` a macro one. Each
    is a real key, so neither is refused — but no render can follow both."""
    raw = _marked(short_valid_json, (("Then the share count.",
                                      "numbers_comment"),
                                     ("Eleven times earnings",
                                      "consequences")))
    _, warnings = parse_short_script(raw, settings)
    assert any("mix formats" in w for w in warnings), warnings


def test_the_word_band_is_the_shorter_shorts(short_valid_json, settings):
    data = json.loads(short_valid_json)
    data["audio_script"] += " " + " ".join(["so"] * 20)
    _, warnings = parse_short_script(json.dumps(data), settings)
    assert any("target ~140–160 for 45–55s" in w for w in warnings), warnings
    _, warnings = parse_short_script(short_valid_json, settings)
    assert not any("target ~140–160" in w for w in warnings), warnings


def test_the_character_budget_is_eleven_hundred(short_valid_json, settings):
    assert settings.max_chars("short") == 1100
    data = json.loads(short_valid_json)
    data["audio_script"] += " " + "x" * 400
    with pytest.raises(ScriptParseError, match="over the SHORT budget of 1100"):
        parse_short_script(json.dumps(data), settings)


def test_rows_past_the_sheet_are_named(short_valid_json, settings):
    """Every short template binds four numbers rows. A fifth validates and
    never reaches the screen, so the writer is told which rows will not."""
    from pipeline.parser_short import SHEET_ROWS

    data = json.loads(short_valid_json)
    row = dict(data["numbers"][0], label="Buybacks")
    data["numbers"] = (data["numbers"] * 2)[:SHEET_ROWS] + [row]
    _, warnings = parse_short_script(json.dumps(data), settings)
    (w,) = [w for w in warnings if "the sheet draws" in w]
    assert "Buybacks" in w
    data["numbers"] = data["numbers"][:SHEET_ROWS]
    _, warnings = parse_short_script(json.dumps(data), settings)
    assert not any("the sheet draws" in w for w in warnings)
