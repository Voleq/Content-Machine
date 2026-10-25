"""Used jokes (S3) and Dennis's facts (S8): remembered once, handed on."""

from __future__ import annotations

import json
from types import SimpleNamespace

from bot.prompts import fill_prompt
from pipeline import channel_memory as cm


def _script(text: str):
    return SimpleNamespace(narration=text, events=[], ticker="EXMPL")


NARRATION = (
    "Revenue grew nine percent and margins fell to twelve.\n"
    "That defence is real, and it's the one I'd make. [BEAT] It's also been "
    "four years.\n"
    "My nan bought this in 2021 and never sold.\n"
)


def test_fallback_jokes_without_model(settings):
    # Mock mode: the model is skipped, so the rule-based reading runs.
    jokes = cm.extract_jokes(_script(NARRATION.replace("[BEAT] ", "")),
                             settings)
    assert isinstance(jokes, list)
    beat = cm.fallback_jokes(SimpleNamespace(narration=NARRATION, events=[]))
    assert any(j.startswith("It's also been four years") for j in beat)


def test_fallback_facts_keep_cast_and_own_past():
    facts = cm.fallback_facts(NARRATION)
    assert facts == ["He said: “My nan bought this in 2021 and never sold.”"]


def test_remember_is_idempotent(settings):
    first = cm.remember_video(settings, "exmpl", "2026-07-01", "long",
                              _script(NARRATION))
    again = cm.remember_video(settings, "EXMPL", "2026-07-01", "long",
                              _script(NARRATION))
    assert first["facts"] == 1
    assert again["jokes"] == 0 and again["facts"] == 0
    assert len(cm.FactBook(settings).all()) == 1


def test_recent_is_newest_40(settings):
    book = cm.JokeBook(settings)
    for n in range(45):
        book.add(f"T{n}/2026-07-01/long", [f"joke number {n} about margins"],
                 ticker=f"T{n}", workdate="2026-07-01", fmt="long")
    got = book.recent(cm.PROMPT_JOKES)
    assert len(got) == 40 and got[-1].text == "joke number 44 about margins"


def test_reworded_joke_is_flagged(settings):
    cm.JokeBook(settings).add(
        "ABC/2026-07-01/long",
        ["A restaurant that was excellent in one small room bought the "
         "building next door"], ticker="ABC", workdate="2026-07-01", fmt="long")
    text = ("Think of an excellent restaurant in one small room that bought "
            "the building next door.")
    found = cm.joke_reuse_lint(text, settings)
    assert found and found[0].gate == "jokes" and "ABC" in found[0].message
    assert cm.joke_reuse_lint("Free cash flow fell by half.", settings) == []


def test_junk_ledger(settings):
    (settings.state_dir / cm.JOKES_FILE).write_text(json.dumps({"no": 1}), encoding="utf-8")
    (settings.state_dir / cm.FACTS_FILE).write_text("not json", encoding="utf-8")
    assert cm.used_jokes_block(settings).startswith("(none yet")
    assert cm.dennis_facts_block(settings).startswith("(none yet")
    assert cm.joke_reuse_lint("anything at all here", settings) == []


def test_replace_all_keeps_known_videos(settings):
    book = cm.JokeBook(settings)
    book.add("ABC/2026-07-01/long", ["one joke here", "two joke here"],
             ticker="ABC", workdate="2026-07-01", fmt="long")
    book.replace_all(["two joke here", "his own new one"])
    rows = book.all()
    assert [r.text for r in rows] == ["two joke here", "his own new one"]
    assert rows[0].ticker == "ABC" and rows[1].ticker == ""


def test_a_save_from_an_open_page_keeps_what_shipped_meanwhile(settings):
    """A video shipped while the library was open, and saving an edit there
    dropped its lines. And a video whose lines were all removed was taken as
    never remembered, so a final rendered again added them back."""
    book = cm.JokeBook(settings)
    book.add("ABC/2026-07-01/long", ["one joke here"], ticker="ABC",
             workdate="2026-07-01", fmt="long")
    shown = [r.text for r in book.all()]
    book.add("XYZ/2026-07-02/long", ["a new one meanwhile"], ticker="XYZ",
             workdate="2026-07-02", fmt="long")
    book.replace_all([], was=shown)
    assert [r.text for r in book.all()] == ["a new one meanwhile"]
    assert book.has("ABC/2026-07-01/long")
    assert book.add("ABC/2026-07-01/long", ["one joke here"]) == 0


def test_blocks_fill_in_prompts(settings, workspace):
    from pipeline.company_data import load_company_data

    data = load_company_data(workspace)
    text = fill_prompt("long_write", "EXMPL", data, workspace, settings,
                       chosen_angle="1")
    assert "DENNIS — WHO HE IS" in text and "Dennis, 25" in text
    assert "ALREADY USED ON THIS CHANNEL" in text
    assert "{{" not in text.split("## TAG GRAMMAR")[0]


def test_checking_a_shipped_video_again_does_not_find_its_own_lines(
        settings, fixtures_dir, long_valid_text):
    """Shipping writes a video's jokes and confession to the ledgers, so
    checking it again (a re-render) reported its own lines as "already used
    in EXMPL on <its own date>". Another video's are still found."""
    from datetime import date

    from pipeline.company_data import load_company_data
    from pipeline.gates import run_gates
    from pipeline.parser_long import parse_long_script
    from pipeline.standing import ConfessionLedger
    from pipeline.workspace import Workspace

    data = load_company_data(fixtures_dir / "company_data")
    script, _ = parse_long_script(long_valid_text, "EXMPL", settings)
    joke = next(s for s in script.narration.split(". ")
                if len(cm._content_words(s)) >= 6)
    confession = "I bought it at nineteen in 2019 and it is four now."
    script.confession = SimpleNamespace(kind="financial", text=confession)
    ws = Workspace(settings, "EXMPL", "2026-10-01").create()
    cm.JokeBook(settings).add("EXMPL/2026-10-01/long", [joke], ticker="EXMPL",
                              workdate="2026-10-01", fmt="long")
    ConfessionLedger(settings).note("EXMPL", kind="financial", text=confession,
                                    fmt="long", workdate="2026-10-01")

    def gates(where):
        report = run_gates(script, settings, data=data, skeptic=False,
                           as_of=date.today().isoformat(), workspace=where)
        return {f.gate for f in report.findings}

    assert not {"jokes", "confession"} & gates(ws.path)
    other = Workspace(settings, "EXMPL", "2026-10-20").create()
    assert {"jokes", "confession"} <= gates(other.path)
