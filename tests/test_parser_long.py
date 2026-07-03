import pytest

from pipeline.models import TagType
from pipeline.parser_long import LongScriptError, parse_long_script, validate_long_script

PALETTE = {
    "house_of_cards", "confused_office_worker", "clown", "dumpster_fire",
    "sinking_ship", "monopoly_money", "printing_money", "empty_promise_handshake",
}


def test_parse_valid_long(long_valid_text, settings):
    script, warnings = parse_long_script(long_valid_text, "EXMPL", settings)
    assert script.ticker == "EXMPL"
    assert len(script.events) == 13
    assert len(script.events_of(TagType.BROLL)) == 8
    assert len(script.events_of(TagType.SOUND)) == 3
    assert len(script.events_of(TagType.SHOW_REFINITIV)) == 1
    assert len(script.events_of(TagType.STAMP)) == 1
    assert "[" not in script.narration and "]" not in script.narration
    # fixture is deliberately short-form; the parser should flag it
    assert any("short for the LONG format" in w for w in warnings)


def test_offsets_point_into_clean_narration(long_valid_text, settings):
    script, _ = parse_long_script(long_valid_text, "EXMPL", settings)
    first_broll = script.events_of(TagType.BROLL)[0]
    assert first_broll.payload == "house_of_cards"
    after = script.narration[first_broll.char_offset:].lstrip()
    assert after.startswith("We are going to spend")

    refinitiv = script.events_of(TagType.SHOW_REFINITIV)[0]
    assert refinitiv.payload == "income_statement.png"
    after = script.narration[refinitiv.char_offset:].lstrip()
    assert after.startswith("That number is real.")

    stamp = script.events_of(TagType.STAMP)[0]
    assert stamp.payload == "OVERVALUED"
    # events must be ordered and inside the narration
    offsets = [e.char_offset for e in script.events]
    assert offsets == sorted(offsets)
    assert all(0 <= off <= len(script.narration) for off in offsets)


def test_unknown_tag_types_stripped_and_warned(fixtures_dir, settings):
    raw = (fixtures_dir / "scripts" / "long_unknown_tags.txt").read_text()
    script, warnings = parse_long_script(raw, "EXMPL", settings)
    assert "[" not in script.narration, "unknown tags must never be spoken"
    assert any("unknown tag [CAMERA" in w for w in warnings)
    # unknown PAYLOADS are kept as events (the validator handles them)
    broll_keys = [e.payload for e in script.events_of(TagType.BROLL)]
    assert "flying_toasters" in broll_keys


def test_validation_rules(fixtures_dir, settings, tmp_path):
    raw = (fixtures_dir / "scripts" / "long_unknown_tags.txt").read_text()
    script, _ = parse_long_script(raw, "EXMPL", settings)
    warnings, blocking = validate_long_script(script, PALETTE, tmp_path, settings)

    assert any("flying_toasters" in w and "filler" in w for w in warnings)
    assert any("airhorn_extreme" in w for w in warnings)
    assert any("MEDIOCRE" in w for w in warnings)
    assert len(blocking) == 1 and "missing_file.png" in blocking[0]

    # drop the screenshot into the workspace -> no more blockers
    (tmp_path / "missing_file.png").write_bytes(b"fake png")
    _, blocking2 = validate_long_script(script, PALETTE, tmp_path, settings)
    assert blocking2 == []


def test_long_budget_enforced(long_valid_text, settings):
    tight = settings.model_copy(update={"long_max_chars": 200})
    with pytest.raises(LongScriptError, match="budget"):
        parse_long_script(long_valid_text, "EXMPL", tight)


def test_empty_rejected(settings):
    with pytest.raises(LongScriptError):
        parse_long_script("", "EXMPL", settings)
    with pytest.raises(LongScriptError):
        parse_long_script("[B-ROLL: clown]", "EXMPL", settings)


def test_no_tags_is_valid_but_warned(settings):
    script, warnings = parse_long_script("Just words, no direction.", "EXMPL", settings)
    assert script.events == []
    assert any("no [B-ROLL]" in w for w in warnings)
    assert any("no [STAMP]" in w for w in warnings)
