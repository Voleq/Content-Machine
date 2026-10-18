"""S4: the cold-read prompt, and the answer pasted back."""

import pytest

from bot.handlers import BotCore
from pipeline.cold_read import (HEADINGS, cold_read_prompt, link_quotes,
                                load_cold_read, save_cold_read, spoken_lines)
from pipeline.parser_long import parse_long_script

CHAT = 5151
LINES = [(2, "Revenue grew twelve percent and nobody noticed."),
         (4, "The debt is the part they would rather you skipped."),
         (7, "So I read page forty, which is where the bodies are.")]


def test_prompt_numbers_lines_and_has_headings():
    prompt = cold_read_prompt(LINES, "long")
    assert "L4: The debt is the part" in prompt
    for heading in HEADINGS:
        assert f"## {heading}" in prompt
    assert "## Three fixes" in prompt
    assert "never seen this channel" in prompt


def test_link_by_line_number():
    answer = "## Lost me\nL4 — I don't know what debt they mean.\nL99 nothing"
    assert link_quotes(answer, LINES) == [(LINES[1][1], 4)]


def test_link_by_quote():
    answer = ('## Fell flat\n"So I read page forty, where the bodies are" — '
              'the joke is old.\n"something that is not in the script at all"')
    assert link_quotes(answer, LINES) == [
        ("So I read page forty, where the bodies are", 7)]


def test_save_and_load_roundtrip(tmp_path):
    read = save_cold_read(tmp_path, "long", "L2 landed.\n", LINES, "abc")
    back = load_cold_read(tmp_path, "long")
    assert back is not None
    assert back.text == "L2 landed."
    assert back.quotes == [(LINES[0][1], 2)] == read.quotes
    assert back.script_sha == "abc"
    assert load_cold_read(tmp_path, "short") is None


def test_long_lines_are_the_stored_scripts(settings, long_valid_text):
    script, _ = parse_long_script(long_valid_text, "EXMPL", settings)
    lines = spoken_lines(script, long_valid_text)
    raw = long_valid_text.splitlines()
    assert lines
    for n, text in lines:
        assert text.split()[0] in raw[n - 1]
        assert text in " ".join(script.narration.split())


@pytest.fixture()
def core(settings):
    return BotCore(settings)


def test_command_without_active_video(core):
    assert "No active video" in core.cold_read(CHAT).text


def test_command_round_trip_on_a_short(core, fixtures_dir, short_valid_json):
    core.start_lane(CHAT, "short", "EXMPL")
    core.handle_upload(CHAT, "dennis_data.xlsx",
                       (fixtures_dir / "company_data" / "dennis_data.xlsx")
                       .read_bytes())
    core.intake_script(CHAT, short_valid_json)
    ask = core.cold_read(CHAT)
    assert ask.files and ask.files[0].name == "cold_read_prompt_short.md"
    assert "L1: " in ask.files[0].read_text(encoding="utf-8")
    done = core.cold_read(CHAT, "## Landed\nL1 hooked me.")
    assert "1 note(s) linked: L1" in done.text
    ws = core.context.get(CHAT)
    assert load_cold_read(ws.path, "short").quotes[0][1] == 1
