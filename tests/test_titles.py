"""The writer's titles, the title check and the Figma Make prompt (T1-T4)."""

from __future__ import annotations

import json

import pytest

from pipeline.titles import (
    check_thumbnail_text,
    check_title,
    chosen_title,
    long_titles_block,
    pick_titles,
    set_chosen_title,
    short_titles_block,
    title_findings,
)

TITLES = """=== TITLES ===
1. Down 60% and still not obviously cheap | EXMPL is down sixty percent from its high, and the people who bought that high have moved on to newer mistakes.
2. "$212M of marketing to add $5M of revenue" | Two hundred and twelve million on sales and marketing, to add five million of revenue.
3. Down 93% and nobody noticed | The financing line is the story.
4. EXMPL: buy the covenant | That covenant is the whole thesis, and it's four hundred pages in.
5. the covenant four hundred pages in | That covenant is the whole thesis, and it's four hundred pages in.
Thumbnail: the covenant clock
"""


@pytest.fixture()
def long_with_titles(long_valid_text):
    head, _, tail = long_valid_text.partition("=== CHAPTERS ===")
    return head + TITLES + "\n=== CHAPTERS ===" + tail


def _parse(settings, text):
    from pipeline.parser_long import parse_long_script

    return parse_long_script(text, "EXMPL", settings)


# ---------------------------------------------------------------- the trailer


def test_the_titles_trailer_is_read_and_never_spoken(settings, long_with_titles):
    script, _ = _parse(settings, long_with_titles)

    assert [t.text for t in script.titles][:2] == [
        "Down 60% and still not obviously cheap",
        "$212M of marketing to add $5M of revenue"]
    assert script.titles[1].pays_off.startswith("Two hundred and twelve million")
    assert script.thumbnail_text == "the covenant clock"
    assert "TITLES" not in script.narration
    assert "Thumbnail" not in script.narration
    assert "nobody noticed" not in script.narration
    # The chapters after it are still the chapters, and only them.
    assert len(script.chapter_list) == 10
    assert "TITLES" not in script.chapters


def test_the_trailer_may_come_last_after_the_confession(settings, long_valid_text):
    script, _ = _parse(settings, long_valid_text.rstrip() + "\n\n" + TITLES)

    assert len(script.titles) == 5
    assert script.confession is not None
    assert "Down 93%" not in script.confession.text
    assert "TITLES" not in script.narration


def test_titles_never_change_the_hash(settings, long_valid_text, long_with_titles):
    plain, _ = _parse(settings, long_valid_text)
    titled, _ = _parse(settings, long_with_titles)

    assert plain.content_sha() == titled.content_sha()


def test_a_short_takes_titles_in_either_shape(short_valid_json):
    from pipeline.models import ShortScript

    data = json.loads(short_valid_json)
    before = ShortScript.model_validate(data).content_sha()
    data["titles"] = [{"title": "A title", "pays_off": "a line"},
                      "Another | its line", "  3. \"Third\"  "]
    data["thumbnail_text"] = "two words"
    script = ShortScript.model_validate(data)

    assert [t.text for t in script.titles] == ["A title", "Another", "Third"]
    assert script.titles[1].pays_off == "its line"
    assert script.thumbnail_text == "two words"
    assert script.content_sha() == before


# ---------------------------------------------------------------- the check


def test_a_figure_said_in_words_is_the_title_s_figure():
    said = "It went up twenty nine percent today, on a one point one two billion hole."

    assert check_title("Up 29% on nothing", "", said).offered
    assert check_title("A $1.1B hole", "", said).offered
    refused = check_title("Up 35% on nothing", "", said)
    assert not refused.offered
    assert "35%" in refused.refused[0]


def test_what_takes_a_title_away():
    said = "The buyback was a bad idea and the sell-off was worse."

    assert not check_title("x" * 101, "", said).offered
    assert not check_title("Buy the dip on this one", "", said).offered
    assert not check_title("A price target nobody believes", "", said).offered
    assert not check_title("The stock about to crash", "", said).offered
    assert not check_title("The capital iq screen", "", said).offered
    assert not check_title("The shit buyback", "", said).offered
    # Facts that look like calls are facts.
    assert check_title("A bad buyback and a worse sell-off", "", said).offered
    assert check_title("The sellers were right", "", said).offered


def test_what_only_warns():
    said = "The buyback was a bad idea."
    long_one = check_title("A buyback so bad it needs a very long title to say so, "
                           "and here it is", "", said)
    assert long_one.offered and any("characters" in w for w in long_one.warnings)
    first = check_title("$EXMPL and the bad buyback", "The buyback was a bad idea.",
                        said, ticker="EXMPL")
    assert first.offered and any("ticker" in w for w in first.warnings)
    unpaid = check_title("The bad buyback", "a line nobody wrote anywhere", said)
    assert any("not in the script" in w for w in unpaid.warnings)
    assert any("names no line" in w
               for w in check_title("The bad buyback", "", said).warnings)


def test_the_thumbnail_words_add_to_the_title():
    said = "The buyback was a bad idea, and it cost two billion."

    assert check_thumbnail_text("bad buyback", "The bad buyback", said).warnings
    assert check_thumbnail_text("one word", "The bad buyback", said).warnings == []
    assert check_thumbnail_text("five whole words in here", "x", said).warnings
    assert check_thumbnail_text("$9B gone", "x", said).refused


# ---------------------------------------------------------------- the pick


def test_the_upload_offers_only_what_the_check_lets_through(settings, long_with_titles):
    script, _ = _parse(settings, long_with_titles)
    pick = pick_titles(script, ticker="EXMPL")

    assert pick.from_writer
    assert "Down 93% and nobody noticed" not in pick.titles
    assert "EXMPL: buy the covenant" not in pick.titles
    assert pick.titles[0] == "Down 60% and still not obviously cheap"
    assert any("Title 3 not offered" in n for n in pick.notes)
    assert any("Title 4 not offered" in n for n in pick.notes)
    assert pick.thumbnail_text == "the covenant clock"

    picked = pick_titles(script, ticker="EXMPL",
                         chosen="the covenant four hundred pages in")
    assert picked.titles[0] == "the covenant four hundred pages in"
    assert picked.payoffs[0].startswith("That covenant")


def test_a_script_without_titles_gets_the_bot_s_two(settings, long_valid_text):
    script, _ = _parse(settings, long_valid_text)
    pick = pick_titles(script, ticker="EXMPL", hook="EXMPL is down sixty percent")

    assert not pick.from_writer and len(pick.titles) == 2
    assert all("nobody screenshots" not in t for t in pick.titles)


def test_the_script_check_names_each_refused_title(settings, long_with_titles):
    script, _ = _parse(settings, long_with_titles)
    found = title_findings(script)
    text = " ".join(f.message for f in found)

    assert "title 3 is not offered" in text
    assert "title 4 is not offered" in text
    assert all(f.severity == "warn" for f in found)


def test_his_pick_is_kept_per_format(tmp_path):
    assert chosen_title(tmp_path, "long") == ""
    set_chosen_title(tmp_path, "long", "The one")
    set_chosen_title(tmp_path, "short", "The short one")
    assert chosen_title(tmp_path, "long") == "The one"
    set_chosen_title(tmp_path, "long", "")
    assert chosen_title(tmp_path, "long") == ""
    assert chosen_title(tmp_path, "short") == "The short one"


# ---------------------------------------------------------------- the package


def test_the_package_carries_the_titles_and_the_figma_prompt(settings, long_with_titles):
    from pipeline.publish import build_package

    script, _ = _parse(settings, long_with_titles)
    pkg = build_package(script, settings, ticker="EXMPL", fmt="long",
                        company="Example Corp", cover_figure="Net margin: -18%",
                        cover_name="the bot's cover (thumbnail.png)")

    assert pkg.titles_from_writer
    assert pkg.titles[0] == "Down 60% and still not obviously cheap"
    assert pkg.thumbnail_text == "the covenant clock"
    prompt = pkg.thumbnail_prompt
    assert "1280 x 720" in prompt
    assert "THE COVENANT CLOCK" in prompt
    assert "Example Corp (EXMPL)" in prompt
    assert "thumbnail.png" in prompt
    # The cover's figure is not one the video gives, so it stays off.
    assert "-18%" not in prompt
    assert "#F4F2EA" in prompt
    text = pkg.render_text()
    assert "FIGMA MAKE PROMPT" in text and "THUMBNAIL WORDS" in text
    assert "pays off: EXMPL is down sixty percent" in text
    assert "Title 3 not offered" in text


def test_a_short_s_prompt_is_tall(settings, short_valid_json):
    from pipeline.models import ShortScript
    from pipeline.publish import build_package

    script = ShortScript.model_validate_json(short_valid_json)
    pkg = build_package(script, settings, ticker=script.ticker, fmt="short")

    assert "1080 x 1920" in pkg.thumbnail_prompt
    assert "9:16" in pkg.thumbnail_prompt


# ---------------------------------------------------------------- the prompts


def test_every_lane_asks_for_titles_the_same_way():
    assert "=== TITLES ===" in long_titles_block()
    assert "Thumbnail:" in long_titles_block()
    assert '"pays_off"' in short_titles_block()
    for block in (long_titles_block(), short_titles_block()):
        assert "60 characters" in block and "100" in block
