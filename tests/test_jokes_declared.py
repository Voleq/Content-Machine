"""Bible v4 (30 Oct 2026): the jokes are declared, counted and read back.

Valentin ran the bot's prompts through Gemini and found "nowhere the jokes":
a twenty-six-minute long with six polite ones and a short with one. The fix
is in the bible and the prompts; these are the checks that make a dry script
say so, counted off the writer's own list rather than guessed at.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from pipeline import channel_memory as cm
from pipeline import writing_checks as wc
from pipeline.gates import voice_lint
from pipeline.models import LongScript, ScriptJoke
from pipeline.parser_long import (_split_jokes_trailer, _strip_bit_plan,
                                  parse_jokes, parse_long_script)
from pipeline.parser_short import parse_short_script

TEMPLATES = Path(__file__).resolve().parents[1] / "templates"
WRITING = ("short", "headline", "long_angle", "long_write", "update")


@pytest.fixture()
def settings(settings):
    return settings.model_copy(update={"long_min_chars": 0})


def _example(name: str) -> dict:
    text = (TEMPLATES / f"master_prompt_{name}.md").read_text(encoding="utf-8")
    example = text[text.index("## STRUCTURE EXAMPLE"):]
    return json.loads(example[example.index("{"):])


def _short(settings, **change):
    obj = _example("short")
    obj.update(change)
    script, _ = parse_short_script(json.dumps(obj), settings)
    return script


# --------------------------------------------------------------------------
# The prompts.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", WRITING)
def test_every_writing_prompt_names_the_register(name):
    text = (TEMPLATES / f"master_prompt_{name}.md").read_text(encoding="utf-8")
    assert "Benjamin" in text


@pytest.mark.parametrize("name", WRITING)
def test_no_writing_prompt_caps_the_jokes_low(name):
    """The lines Gemini obeyed when it wrote a dry script."""
    text = (TEMPLATES / f"master_prompt_{name}.md").read_text(encoding="utf-8")
    for line in ("Density stays LOW", "one or two dry jokes is the budget",
                 "One or two dry jokes is the budget", "Almost no teaching",
                 "roughly one per real point", "one honest confession",
                 "dry, deadpan, understated"):
        assert line not in text, (name, line)


def test_the_long_prompt_ends_on_the_voice_not_the_catalogue():
    """The voice was at the top and 150 KB of plates came after it."""
    text = (TEMPLATES / "master_prompt_long_write.md").read_text(encoding="utf-8")
    assert text.index("THE VOICE PASS") > text.index("{{plate_catalogue}}")
    assert text.index("THE VOICE PASS") > text.index("{{scene_catalogue}}")
    assert "=== BIT PLAN ===" in text and "=== JOKES ===" in text


@pytest.mark.parametrize("name", ["short", "headline"])
def test_the_examples_carry_three_jokes_and_no_stock_turn(name, settings):
    obj = _example(name)
    assert len(obj["jokes"]) >= 3
    assert "screenshots" not in obj["audio_script"]
    assert "Mostly noise, one number worth watching" not in obj["audio_script"]
    script, _ = parse_short_script(json.dumps(obj), settings)
    found = wc.joke_floor_lint(script, "short")
    assert [f.severity for f in found] == ["note"], [f.message for f in found]


# --------------------------------------------------------------------------
# The short's `jokes`.
# --------------------------------------------------------------------------


def test_a_short_with_no_jokes_listed_says_so(settings):
    found = wc.joke_floor_lint(_short(settings, jokes=[]), "short")
    assert any(f.severity == "warn" and "no jokes listed" in f.message
               for f in found)


def test_a_short_under_three_says_so(settings):
    obj = _example("short")
    found = wc.joke_floor_lint(_short(settings, jokes=obj["jokes"][:2]), "short")
    assert any("at least 3" in f.message for f in found)


def test_a_listed_joke_the_script_never_says_is_named(settings):
    obj = _example("short")
    jokes = obj["jokes"] + ["the CFO is a golden retriever in a fleece"]
    found = wc.joke_floor_lint(_short(settings, jokes=jokes), "short")
    assert [f.excerpt for f in found if "never says it" in f.message] == [
        "the CFO is a golden retriever in a fleece"]


def test_a_joke_copied_with_a_word_off_is_still_found(settings):
    obj = _example("short")
    jokes = list(obj["jokes"])
    jokes[1] = "WallStreetBets can count up to eleven"
    found = wc.joke_floor_lint(_short(settings, jokes=jokes), "short")
    assert not [f for f in found if "never says it" in f.message]


def test_a_short_without_jokes_keeps_its_hash(settings):
    """The sha is what an approval is recorded against: a script written
    before the field existed must not be un-approved by it."""
    script = _short(settings, jokes=[])
    exclude: dict = {name: True for name in ("beat_marks", "sources")
                     if not getattr(script, name)}
    exclude["jokes"] = True
    if not any(e.beside for e in script.inline_events):
        exclude["inline_events"] = {"__all__": {"beside"}}
    old = hashlib.sha256(script.model_dump_json(exclude=exclude).encode(
        "utf-8")).hexdigest()[:16]
    assert script.content_sha() == old


# --------------------------------------------------------------------------
# The long's `=== JOKES ===` trailer.
# --------------------------------------------------------------------------

_NARRATION = (
    "The company sells boxes. I have bought three of them, which is three "
    "more than my dad's index fund ever needed.\n\n"
    "Revenue went up four percent a year, which is growth the way a "
    "glacier is a commute.\n\n"
)


def test_the_jokes_trailer_is_parsed_and_never_spoken(settings):
    raw = (_NARRATION
           + "=== CHAPTERS ===\n00:00 cold-open | three boxes\n\n"
           + "=== JOKES ===\n"
           + "self-own | which is three more than my dad's index fund ever needed\n"
           + "- growth the way a glacier is a commute\n\n"
           + "=== CONFESSION ===\nepistemic | I do not know what a box costs.\n")
    script, _ = parse_long_script(raw, "EXMPL", settings)
    assert "JOKES" not in script.narration and "self-own" not in script.narration
    assert [j.move for j in script.jokes] == ["self-own", ""]
    assert script.jokes[1].text == "growth the way a glacier is a commute"
    assert script.confession is not None and script.confession.kind == "epistemic"
    assert [c.title for c in script.chapter_list] == ["three boxes"]


def test_the_jokes_trailer_may_come_last(settings):
    raw = (_NARRATION + "=== CHAPTERS ===\n00:00 cold-open | three boxes\n"
           + "=== JOKES ===\nself-own | three more than my dad's index fund\n")
    script, _ = parse_long_script(raw, "EXMPL", settings)
    assert [c.title for c in script.chapter_list] == ["three boxes"]
    assert len(script.jokes) == 1


def test_the_bit_plan_is_never_spoken(settings):
    raw = ("=== HOOK OPTIONS ===\n1. \"Three boxes.\"\nChosen: 1\n\n"
           "=== BIT PLAN ===\nRunning gag: the boxes, three hits\n"
           "Swears: two, late\n\n" + _NARRATION)
    script, _ = parse_long_script(raw, "EXMPL", settings)
    assert "Running gag" not in script.narration
    assert script.narration.startswith("The company sells boxes")


def test_a_bit_plan_without_a_blank_line_stops_at_the_first_tag():
    raw = "=== BIT PLAN ===\nRunning gag: x\n[SCENE: desk-front] The company."
    assert _strip_bit_plan(raw) == "[SCENE: desk-front] The company."


def test_a_joke_line_with_nothing_to_read_back_warns():
    jokes, warnings = parse_jokes("self-own |\n# a comment\nwrong last item | ok then")
    assert [j.text for j in jokes] == ["ok then"]
    assert len(warnings) == 1


def test_the_trailer_is_cut_wherever_it_sits():
    raw = "Body.\n=== JOKES ===\na | b c\n=== CHAPTERS ===\n00:00 cold-open | x\n"
    body, jokes = _split_jokes_trailer(raw)
    assert jokes == "a | b c" and "CHAPTERS" in body and "b c" not in body


def _long(narration: str, jokes: list[str]) -> LongScript:
    return LongScript(ticker="EXMPL", narration=narration,
                      jokes=[ScriptJoke(text=j) for j in jokes])


def test_a_long_under_one_a_minute_says_so():
    para = " ".join(["the margin held at forty percent"] * 40)   # 240 words
    narration = "\n\n".join([para] * 4)                          # ~6 minutes
    found = wc.joke_floor_lint(_long(narration + "\n\nAnd that is a joke.",
                                     ["And that is a joke."]), "long")
    assert any("one a minute" in f.message for f in found)


def test_a_long_dry_stretch_names_its_line():
    joke = "My nan is up forty percent and I am not."
    dry = " ".join(["the margin held at forty percent"] * 70)    # ~2.6 minutes
    narration = f"{joke}\n\n{dry}\n\n{joke}"
    found = wc.joke_floor_lint(_long(narration, [joke]), "long")
    stretch = [f for f in found if "without a listed joke" in f.message]
    assert stretch and stretch[0].line == 3


def test_a_long_without_jokes_keeps_its_hash():
    script = LongScript(ticker="EXMPL", narration="Words.")
    old = hashlib.sha256(script.model_dump_json(
        exclude={"events": {"__all__": {"beside"}}, "jokes": True}
    ).encode("utf-8")).hexdigest()[:16]
    assert script.content_sha() == old


def test_the_joke_book_keeps_the_declared_lines_that_are_said(settings):
    script = _long(_NARRATION, ["growth the way a glacier is a commute",
                                "a line nobody says anywhere at all"])
    assert cm.extract_jokes(script, settings) == [
        "growth the way a glacier is a commute"]


# --------------------------------------------------------------------------
# The prompt, said aloud.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("line", [
    "Now let us run the mandatory four-step valuation walk in exact order.",
    "That is our first touch on the question on the board.",
    "That brings us to the recurring segment where we read the footnote.",
    "Step four is the reverse-DCF perpetuity gut-check.",
    "That brings us to the one framework that decides this entire video.",
])
def test_the_prompt_said_aloud_is_flagged(line):
    found = wc.prompt_words_lint(LongScript(ticker="EXMPL", narration=line))
    assert len(found) == 1 and found[0].gate == "prompt-words"


@pytest.mark.parametrize("line", [
    "They issued a mandatory convertible in March, which is a loan in a mask.",
    "Step one, buy the top. Step two, explain it to your mum.",
    "The footnote nobody read is on page forty-one.",
])
def test_a_host_saying_ordinary_words_is_not(line):
    assert wc.prompt_words_lint(LongScript(ticker="EXMPL", narration=line)) == []


def test_a_step_number_on_a_plate_is_flagged(settings):
    from pipeline.models import TagEvent, TagType

    script = LongScript(ticker="EXMPL", narration="Words.", events=[
        TagEvent(type=TagType.PLATE, payload="big-number-l1-16x9",
                 char_offset=0, raw_offset=0,
                 values={"kicker": "STEP 1: TRAILING MULTIPLES"})])
    found = wc.prompt_words_lint(script)
    assert len(found) == 1 and "kicker" in found[0].message


# --------------------------------------------------------------------------
# The copy check and the simile allowance.
# --------------------------------------------------------------------------


def test_the_stock_turn_the_bot_used_to_suggest_is_flagged(settings):
    found = wc.copy_check("Shares fell. But here is the part nobody "
                          "screenshots. Revenue rose.", settings)
    assert found and "prompt example" in found[0].message


def test_an_example_joke_said_again_is_flagged(settings):
    found = wc.copy_check("I lived in one in twenty twenty two, and it took "
                          "the car, and then it came back for the fucking "
                          "chair.", settings)
    assert found and "prompt example" in found[0].message


def test_three_similes_are_allowed_and_the_fourth_is_flagged():
    lines = [f"It moved like a {w} in the rain." for w in
             ("tram", "barge", "goose", "piano")]
    found = [f for f in voice_lint("\n".join(lines)) if "simile" in f.message]
    assert [f.line for f in found] == [4]


def test_a_short_that_lists_too_many_or_one_string_still_parses(settings):
    """The list is bookkeeping: it never refuses a script."""
    many = [f"joke number {n} about the margin" for n in range(15)]
    assert len(_short(settings, jokes=many).jokes) == 12
    assert _short(settings, jokes="one line\nanother line").jokes == [
        "one line", "another line"]
