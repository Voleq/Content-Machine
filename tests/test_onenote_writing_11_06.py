"""His 11-06 notes on the writing: no Dennis in a short, his account about
one video in twenty, and the examples clean of both."""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from pipeline import recurring_bits as rb
from pipeline import writing_checks as wc

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"


def _ship(settings, n: int, account: bool = False, start: int = 0) -> None:
    led = rb.AccountLedger(settings)
    said = "My account went to zero in a week." if account else "Revenue rose."
    for k in range(start, start + n):
        led.note(f"T{k}/2026-07-{k + 1:02d}/short", said)


def _long(text: str):
    return SimpleNamespace(narration=text, chapter_list=[])


def test_the_account_is_open_until_it_is_used(settings):
    led = rb.AccountLedger(settings)
    assert led.since() is None and led.allowed()
    assert "MAY" in rb.account_line(settings)


def test_the_account_waits_nineteen_videos_after_it_is_used(settings):
    _ship(settings, 1, account=True)
    led = rb.AccountLedger(settings)
    assert led.since() == 0 and not led.allowed()
    assert "STAYS OUT" in rb.account_line(settings)
    _ship(settings, rb.ACCOUNT_EVERY - 2, start=1)
    assert not led.allowed()
    _ship(settings, 1, start=rb.ACCOUNT_EVERY - 1)
    assert led.since() == rb.ACCOUNT_EVERY - 1 and led.allowed()


def test_a_video_is_counted_once(settings):
    led = rb.AccountLedger(settings)
    assert led.note("A/2026-07-01/long", "my portfolio is a crime scene")
    assert not led.note("A/2026-07-01/long", "my portfolio is a crime scene")
    assert len(led.rows()) == 1


def test_shipping_a_video_writes_the_account_row(settings):
    from pipeline import channel_memory as cm

    script = SimpleNamespace(narration="I got liquidated on a Tuesday.",
                             events=[], chapter_list=[])
    cm.remember_video(settings, "EXMPL", "2026-07-01", "long", script)
    assert rb.AccountLedger(settings).since() == 0


def test_a_long_is_warned_when_the_account_is_not_due(settings):
    _ship(settings, 1, account=True)
    found = rb.account_lint(_long("Then my account went to zero."), settings)
    assert found and found[0].gate == "bits" and found[0].severity == "warn"
    assert "one video in twenty" in found[0].message
    assert rb.account_lint(_long("Revenue fell."), settings) == []


def test_a_long_is_not_warned_when_the_account_is_due(settings):
    assert rb.account_lint(_long("Then my account went to zero."), settings) == []


def test_the_prompt_carries_the_account_line(settings):
    assert "HIS OWN ACCOUNT" in rb.bits_block(settings)


@pytest.mark.parametrize("line", [
    "the bagholder got margin called by lunch",
    "my position is that the price is wrong",
    "I tried to find a number in it and there isn't one",
])
def test_lines_about_somebody_else_are_not_his_account(line):
    script = SimpleNamespace(audio_script=line)
    assert wc.persona_lint(script, "short") == []


@pytest.mark.parametrize("line", [
    "My mum asked me about this stock.",
    "I bought this at the top in twenty twenty one.",
    "My account went to zero on a stock like this.",
    "I got liquidated on this exact chart.",
])
def test_a_short_about_dennis_is_warned(line):
    found = wc.persona_lint(SimpleNamespace(audio_script=f"Revenue fell. {line}"),
                            "short")
    assert found and found[0].gate == "persona" and found[0].severity == "warn"
    # A long may carry him; the check is the short's.
    assert wc.persona_lint(SimpleNamespace(narration=line), "long") == []


@pytest.mark.parametrize("fmt", ["short", "headline"])
def test_the_short_examples_say_nothing_about_dennis(fmt):
    text = (TEMPLATES / f"master_prompt_{fmt}.md").read_text(encoding="utf-8")
    example = re.search(r'"audio_script": "(\[BEAT: hook\].*?)",\n', text).group(1)
    assert wc.persona_lint(SimpleNamespace(audio_script=example), "short") == []
    words = len(re.sub(r"\[[^\]]*\]", " ", example).split())
    assert 160 <= words <= 190, words


def test_the_persona_check_is_explained_and_fed_to_the_fixup():
    from bot.bot_facts import CHECKS
    from pipeline.fixup import _WARN_GATES

    assert "persona" in CHECKS
    assert "persona" in _WARN_GATES
