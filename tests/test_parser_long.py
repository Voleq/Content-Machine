import pytest

from pipeline.models import TagType
from pipeline.parser_long import LongScriptError, parse_long_script, validate_long_script

PALETTE = {
    "tumbleweed", "hamster_wheel", "boardroom_suits", "growing_plant",
    "clown", "dumpster_fire", "sinking_ship", "monopoly_money",
}
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
    assert len(script.events_of(TagType.PLATE)) == 17
    assert len(script.events_of(TagType.CLIP)) == 4
    assert len(script.events_of(TagType.IMG)) == 1
    assert len(script.events_of(TagType.PRODUCT)) == 1
    assert len(script.events_of(TagType.CHART)) == 1
    assert len(script.events_of(TagType.MEME)) == 1
    assert len(script.events_of(TagType.SOUND)) == 2
    assert len(script.events_of(TagType.SCRIBBLE)) == 6
    assert "[" not in script.narration and "]" not in script.narration
    # fixture is deliberately short-form; the parser should flag it as thin
    # even for the shortest LONG cut
    assert any("thin even for the shortest LONG cut" in w for w in warnings)


def test_a_quoted_filing_is_shown(long_valid_text, settings):
    """[SHOW FILING] whenever the script quotes a filing.

    The reference script narrated "it's in the risk factors, and it names a
    person" and showed nothing, which asks the audience to take your word for
    the most checkable claim in the video.
    """
    script, _ = parse_long_script(long_valid_text, "EXMPL", settings)
    filings = script.events_of(TagType.SHOW_FILING)
    assert len(filings) == 2
    assert any("risk_factors" in e.payload for e in filings), \
        "the risk-factor beat quotes a filing and does not show it"


def test_the_chapters_are_a_type_and_a_title(long_valid_text, settings):
    from pipeline.plates import CHAPTER_TYPES

    script, _ = parse_long_script(long_valid_text, "EXMPL", settings)
    assert len(script.chapter_list) == 10
    for ch in script.chapter_list:
        assert ch.type in CHAPTER_TYPES
        assert ch.title and ch.title == ch.title.strip()
    # No ordinal anywhere, and nothing assumes the types are unique.
    assert script.chapter_list[0].type == "cold-open"
    assert script.chapter_list[-1].type == "resigned-close"


def test_a_type_may_appear_twice_under_different_titles(settings):
    """A video may legitimately return to the numbers after guidance."""
    raw = ("Words enough to parse.\n\n=== CHAPTERS ===\n"
           "00:00 cold-open | the hook\n"
           "01:00 the-numbers | six years, one direction\n"
           "02:00 guidance-estimates | what they promised\n"
           "03:00 the-numbers | and what that does to the model\n")
    script, warnings = parse_long_script(raw, "EXMPL", settings)
    types = [c.type for c in script.chapter_list]
    assert types.count("the-numbers") == 2
    titles = [c.title for c in script.chapter_list]
    assert len(set(titles)) == len(titles), "the titles are what distinguishes them"
    assert not any("duplicate" in w.lower() for w in warnings)


def test_an_unknown_chapter_type_is_named_and_skipped(settings):
    raw = ("Words enough to parse.\n\n=== CHAPTERS ===\n"
           "00:00 cold-open | the hook\n"
           "01:00 the-vibes | not one of the sixteen\n")
    script, warnings = parse_long_script(raw, "EXMPL", settings)
    assert [c.type for c in script.chapter_list] == ["cold-open"]
    assert any("the-vibes" in w or "not one of the sixteen" in w
               for w in warnings), warnings


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

    # [ASSET] is gone. A script that still carries one loses the TAG rather
    # than blocking a render on a file nobody is going to draw.
    assert "revenue-flywheel" not in blocking_text
    assert not [e for e in script.events if e.type.value == "ASSET"]

    # drop the screenshot in -> no more blockers
    (tmp_path / "missing_file.png").write_bytes(b"fake png")
    _, blocking2 = validate_long_script(script, PALETTE, tmp_path, settings)
    assert blocking2 == []


def test_a_bad_plate_never_reaches_the_render(fixtures_dir, settings, tmp_path):
    """The three rejections, on one script.

    Each of them is a frame that would otherwise ship wrong rather than fail:
    a name that draws nothing, a row that puts figures under the wrong year,
    and text that goes nowhere.
    """
    raw = (fixtures_dir / "scripts" / "long_unknown_tags.txt").read_text(encoding="utf-8")
    script, warnings = parse_long_script(raw, "EXMPL", settings)
    text = "\n".join(warnings)
    assert "not-a-real-plate" in text and "is not a plate in the kit" in text
    assert "5 figures against 6 period heads" in text
    assert "has no slot 'nonesuch'" in text
    # None of the three reached the event list.
    plates = [e for e in script.events if e.type is TagType.PLATE]
    assert len(plates) == 0


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
def test_the_short_no_longer_resolves_card_tags_at_all():
    """The tag grammar reached the visual layer; now nothing does."""
    import inspect

    from pipeline import render_short

    src = inspect.getsource(render_short)
    assert "card_asset_for" not in src
    assert "KIT_TAG" not in src


def test_the_confession_trailer_is_parsed_and_never_spoken(settings,
                                                           long_valid_text):
    """Declared rather than detected.

    Six kinds of admission phrased six hundred ways are not reliably findable
    in prose, and a ledger that cannot say which sentences were the confession
    cannot stop one being told twice. So the writer names it, the way they
    name the chapters — and like the chapter trailer, it is metadata and the
    voice never reads it.
    """
    from pipeline.parser_long import parse_long_script

    # The committed fixture carries one, so strip it to get the other case.
    bare = long_valid_text.split("=== CONFESSION ===")[0]
    plain, _ = parse_long_script(bare, "EXMPL", settings)
    assert plain.confession is None

    said = ("I bought it at nineteen. It is four. I have had a lot of time to "
            "think about that.")
    with_block = f"{bare}\n\n=== CONFESSION ===\nfinancial | {said}\n"
    script, _ = parse_long_script(with_block, "EXMPL", settings)
    assert script.confession is not None
    assert script.confession.kind == "financial"
    assert script.confession.text == said
    assert "nineteen" not in script.narration


def test_a_malformed_confession_warns_and_is_dropped(settings, long_valid_text):
    """Never fatal. The confession is texture; the video is the deliverable,
    and losing a render over a mistyped trailer would be the bookkeeping
    deciding what ships."""
    from pipeline.parser_long import parse_long_script

    bare = long_valid_text.split("=== CONFESSION ===")[0]
    bad = f"{bare}\n\n=== CONFESSION ===\nsad | nothing in particular\n"
    script, warnings = parse_long_script(bad, "EXMPL", settings)
    assert script.confession is None
    assert any("confession" in w for w in warnings)

    shapeless = f"{bare}\n\n=== CONFESSION ===\nI lost money again\n"
    script, warnings = parse_long_script(shapeless, "EXMPL", settings)
    assert script.confession is None
    assert any("kind | the admission" in w for w in warnings)
