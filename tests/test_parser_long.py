import pytest

from pipeline.models import TagType
from pipeline.parser_long import LongScriptError, parse_long_script, validate_long_script

PALETTE = {
    "tumbleweed", "hamster_wheel", "boardroom_suits", "growing_plant",
    "clown", "dumpster_fire", "sinking_ship", "monopoly_money",
}


def test_parse_new_tags(long_doodles_text, settings):
    script, warnings = parse_long_script(long_doodles_text, "EXMPL", settings)
    assert "[" not in script.narration and "]" not in script.narration
    # chart with a marker style
    charts = script.events_of(TagType.CHART)
    price_chart = next(e for e in charts if e.payload == "price")
    assert price_chart.style == "marker"
    revenue_chart = next(e for e in charts if e.payload == "revenue")
    assert revenue_chart.style == ""  # clean default
    # doodles, scribbles, screengrab
    assert [e.payload for e in script.events_of(TagType.DOODLE)] == \
        ["impact-pow", "face-down"]
    assert len(script.events_of(TagType.SCRIBBLE)) == 2
    assert script.screengrab_slugs() == ["broker-pnl"]


def test_hook_options_preamble_is_stripped(settings):
    """The Step-2 write prompt emits a HOOK OPTIONS menu before the script —
    it must never be spoken (stripped like the ASSET PROMPTS trailer)."""
    raw = (
        '=== HOOK OPTIONS ===\n'
        '1. "It is an excellent company. I will not touch the stock."\n'
        '2. "Down sixty percent, and nobody left to sell."\n'
        'Chosen: 2\n\n'
        'Down sixty percent, and nobody left to sell. [CLIP: tumbleweed] '
        'Which is when I start reading. See you at the next filing.'
    )
    script, _ = parse_long_script(raw, "EXMPL", settings)
    assert "HOOK OPTIONS" not in script.narration
    assert "Chosen:" not in script.narration
    assert "excellent company" not in script.narration, "the hook menu is not spoken"
    assert script.narration.startswith("Down sixty percent")
    assert [e.payload for e in script.events_of(TagType.CLIP)] == ["tumbleweed"]


def test_chapters_trailer_split_and_stored(settings):
    """The `=== CHAPTERS ===` trailer is YouTube metadata — split off like the
    ASSET PROMPTS trailer so it is never spoken, and stored on the script."""
    raw = (
        "Down sixty percent, and nobody left to sell. [CLIP: tumbleweed] "
        "Which is when I start reading. See you at the next filing.\n\n"
        "=== CHAPTERS ===\n"
        "00:00 Cold open — nobody left to sell\n"
        "02:30 What they actually do\n"
        "18:40 What you're paying for\n"
    )
    script, _ = parse_long_script(raw, "EXMPL", settings)
    assert "CHAPTERS" not in script.narration
    assert "00:00" not in script.narration and "Cold open" not in script.narration
    assert script.narration.startswith("Down sixty percent")
    assert "00:00 Cold open" in script.chapters
    assert "What you're paying for" in script.chapters
    assert [e.payload for e in script.events_of(TagType.CLIP)] == ["tumbleweed"]


def test_chapters_and_asset_trailers_coexist(settings):
    """Chapters sit before the asset trailer; both are split off, neither is
    spoken, and each is captured on the script."""
    raw = (
        "Words and a diagram. [ASSET: revenue-flywheel] More words to speak.\n\n"
        "=== CHAPTERS ===\n"
        "00:00 Cold open\n"
        "05:00 The flywheel\n\n"
        "=== ASSET PROMPTS ===\n"
        "--- ASSET: revenue-flywheel ---\n"
        "A 16:9 diagram of the revenue flywheel on a dark background.\n"
    )
    script, _ = parse_long_script(raw, "EXMPL", settings)
    assert "CHAPTERS" not in script.narration and "ASSET PROMPTS" not in script.narration
    assert "flywheel" not in script.narration.lower(), "asset/chapter text is never spoken"
    assert "00:00 Cold open" in script.chapters and "05:00 The flywheel" in script.chapters
    assert script.asset_slugs() == ["revenue-flywheel"]
    assert "revenue-flywheel" in script.asset_prompts
    # the chapter lines must NOT have leaked into the asset prompt
    assert "05:00" not in script.asset_prompts["revenue-flywheel"]


def test_chart_metric_absent_from_data_is_flagged(settings, tmp_path):
    (tmp_path / "income_statement.png").write_bytes(b"png")
    script, _ = parse_long_script(
        "The tape. [CHART: revenue] and [CHART: sbc_pct_rev] over five years.",
        "EXMPL", settings,
    )
    # revenue has a series; sbc_pct_rev is a valid metric with no data here
    warnings, _ = validate_long_script(
        script, PALETTE, tmp_path, settings, data_metrics={"revenue", "price"}
    )
    assert any("sbc_pct_rev" in w and "no multi-year series" in w for w in warnings)
    assert not any("revenue" in w and "no multi-year series" in w for w in warnings)


def test_screengrab_blocks_until_file_present(long_doodles_text, settings, tmp_path):
    script, _ = parse_long_script(long_doodles_text, "EXMPL", settings)
    # the fixture references income_statement.png too — satisfy that first
    (tmp_path / "income_statement.png").write_bytes(b"png")
    _, blocking = validate_long_script(script, PALETTE, tmp_path, settings)
    assert any("SCREENGRAB" in b and "broker-pnl" in b for b in blocking)

    custom = settings.assets_dir / "custom"
    custom.mkdir(parents=True, exist_ok=True)
    grab = custom / "broker-pnl.png"
    grab.write_bytes(b"png")
    try:
        _, blocking2 = validate_long_script(script, PALETTE, tmp_path, settings)
        assert not any("broker-pnl" in b for b in blocking2)
    finally:
        grab.unlink()


def test_unknown_doodle_warns_not_blocks(settings, tmp_path):
    script, _ = parse_long_script(
        "Words. [DOODLE: not-a-real-doodle] More words. And a real one. "
        "[DOODLE: shrug] Done.", "EXMPL", settings,
    )
    warnings, blocking = validate_long_script(script, PALETTE, tmp_path, settings)
    assert blocking == []
    assert any("not-a-real-doodle" in w and "skipped" in w for w in warnings)


def test_malformed_scribble_skipped(settings):
    script, warnings = parse_long_script(
        "A point. [SCRIBBLE: wobble -> target] and [SCRIBBLE: circle -> the debt] end.",
        "EXMPL", settings,
    )
    scribbles = script.events_of(TagType.SCRIBBLE)
    assert len(scribbles) == 1 and scribbles[0].payload == "circle -> the debt"
    assert any("malformed" in w for w in warnings)


def test_parse_valid_long(long_valid_text, settings):
    script, warnings = parse_long_script(long_valid_text, "EXMPL", settings)
    assert script.ticker == "EXMPL"
    assert len(script.events_of(TagType.CLIP)) == 4
    assert len(script.events_of(TagType.IMG)) == 1
    assert len(script.events_of(TagType.PRODUCT)) == 1
    assert len(script.events_of(TagType.CHART)) == 1
    assert len(script.events_of(TagType.SHOW_FILING)) == 1
    assert len(script.events_of(TagType.MEME)) == 1
    assert len(script.events_of(TagType.SOUND)) == 2
    assert "[" not in script.narration and "]" not in script.narration
    # fixture is deliberately short-form; the parser should flag it as thin
    # even for the shortest LONG cut
    assert any("thin even for the shortest LONG cut" in w for w in warnings)


def test_offsets_point_into_clean_narration(long_valid_text, settings):
    script, _ = parse_long_script(long_valid_text, "EXMPL", settings)
    first_clip = script.events_of(TagType.CLIP)[0]
    assert first_clip.payload == "tumbleweed"
    after = script.narration[first_clip.char_offset:].lstrip()
    assert after.startswith("Which is usually when")

    filing = script.events_of(TagType.SHOW_FILING)[0]
    assert filing.payload == "income_statement.png"
    after = script.narration[filing.char_offset:].lstrip()
    assert after.startswith("Net income, from the actual filing")

    offsets = [e.char_offset for e in script.events]
    assert offsets == sorted(offsets)
    assert all(0 <= off <= len(script.narration) for off in offsets)


def test_unknown_tag_types_stripped_and_warned(fixtures_dir, settings):
    raw = (fixtures_dir / "scripts" / "long_unknown_tags.txt").read_text(encoding="utf-8")
    script, warnings = parse_long_script(raw, "EXMPL", settings)
    assert "[" not in script.narration, "unknown tags must never be spoken"
    assert any("unknown tag [CAMERA" in w for w in warnings)
    # the retired verdict grammar is just another unknown type now
    assert any("unknown tag [STAMP" in w for w in warnings)
    # unknown PAYLOADS are kept as events (the validator handles them)
    clip_keys = [e.payload for e in script.events_of(TagType.CLIP)]
    assert "flying_toasters" in clip_keys


def test_asset_trailer_split_and_stored(fixtures_dir, settings):
    raw = (fixtures_dir / "scripts" / "long_unknown_tags.txt").read_text(encoding="utf-8")
    script, _ = parse_long_script(raw, "EXMPL", settings)
    assert script.asset_slugs() == ["revenue-flywheel"]
    assert "revenue-flywheel" in script.asset_prompts
    prompt = script.asset_prompts["revenue-flywheel"]
    assert "Claude" not in script.narration
    assert "ASSET PROMPTS" not in script.narration, "trailer must never be spoken"
    assert "16:9" in prompt and "flywheel" in prompt


def test_orphan_asset_prompt_warns(settings):
    raw = ("Plain narration with no asset tag.\n\n=== ASSET PROMPTS ===\n"
           "--- ASSET: unused-diagram ---\nSome prompt text.")
    script, warnings = parse_long_script(raw, "EXMPL", settings)
    assert script.asset_prompts == {"unused-diagram": "Some prompt text."}
    assert any("unused-diagram" in w and "no matching" in w for w in warnings)


def test_validation_rules(fixtures_dir, settings, tmp_path):
    raw = (fixtures_dir / "scripts" / "long_unknown_tags.txt").read_text(encoding="utf-8")
    script, _ = parse_long_script(raw, "EXMPL", settings)
    warnings, blocking = validate_long_script(script, PALETTE, tmp_path, settings)

    assert any("flying_toasters" in w and "raw query" in w for w in warnings)
    assert any("airhorn_extreme" in w for w in warnings)
    assert any("mystery_metric" in w for w in warnings)
    assert any("obscure-meme-nobody-indexed" in w for w in warnings)
    blocking_text = "\n".join(blocking)
    assert "missing_file.png" in blocking_text
    assert "revenue-flywheel" in blocking_text
    assert "Claude Design" in blocking_text, "the prompt hint must reach the operator"

    # drop the screenshot + the custom asset in -> no more blockers
    (tmp_path / "missing_file.png").write_bytes(b"fake png")
    custom = settings.assets_dir / "custom"
    custom.mkdir(parents=True, exist_ok=True)
    (custom / "revenue-flywheel.png").write_bytes(b"fake png")
    try:
        _, blocking2 = validate_long_script(script, PALETTE, tmp_path, settings)
        assert blocking2 == []
    finally:
        (custom / "revenue-flywheel.png").unlink()


def test_meme_cap_blocks(settings, tmp_path):
    raw = ("One. [MEME: bagholder] Two. [MEME: dilution] "
           "Three. [MEME: stonks] The information got up and left.")
    script, _ = parse_long_script(raw, "EXMPL", settings)
    assert script.meme_count() == 3
    _, blocking = validate_long_script(script, PALETTE, tmp_path, settings)
    assert any("cap is 2" in b for b in blocking)


def test_two_memes_pass_the_cap(settings, tmp_path):
    raw = "One. [MEME: bagholder] Two. [MEME: dilution] Fine."
    script, _ = parse_long_script(raw, "EXMPL", settings)
    _, blocking = validate_long_script(script, PALETTE, tmp_path, settings)
    assert blocking == []


def test_vendor_name_in_narration_rejected(settings):
    with pytest.raises(LongScriptError, match="vendor"):
        parse_long_script("According to Refinitiv, revenue fell.", "EXMPL", settings)


def test_long_budget_enforced(long_valid_text, settings):
    tight = settings.model_copy(update={"long_max_chars": 200})
    with pytest.raises(LongScriptError, match="budget"):
        parse_long_script(long_valid_text, "EXMPL", tight)


def test_empty_rejected(settings):
    with pytest.raises(LongScriptError):
        parse_long_script("", "EXMPL", settings)
    with pytest.raises(LongScriptError):
        parse_long_script("[CLIP: clown]", "EXMPL", settings)


def test_no_tags_is_valid_but_warned(settings):
    script, warnings = parse_long_script("Just words, no direction.", "EXMPL", settings)
    assert script.events == []
    assert any("no visual tags" in w for w in warnings)


def test_bad_asset_slug_skipped(settings):
    script, warnings = parse_long_script(
        "Words. [ASSET: Totally Bad Slug!!] More words.", "EXMPL", settings,
    )
    assert script.events_of(TagType.ASSET) == []
    assert any("not kebab-case" in w for w in warnings)
