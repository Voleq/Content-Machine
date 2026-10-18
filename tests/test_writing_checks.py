"""The writing checks added for the 10-18 picks: phrasing (S1), swearing,
the copy check (S2) and the chapter order (S9). All of them warn."""

from __future__ import annotations

from pipeline import writing_checks as wc
from pipeline import writing_files


# --------------------------------------------------------------- S1 phrasing
def test_listed_phrase_warns_with_line(settings):
    text = "Revenue fell nine percent.\nHere's the thing: margins held."
    found = wc.phrasing_lint(text, settings)
    assert [f.line for f in found] == [2]
    assert found[0].gate == "phrasing" and found[0].severity == "warn"
    assert "here's the thing" in found[0].message.lower()


def test_answered_question_flags_only_the_second(settings):
    text = ("The result? Chaos.\nMargins fell to nine percent.\n"
            "The reason? Freight.")
    found = [f for f in wc.phrasing_lint(text, settings)
             if "question" in f.message]
    assert [f.line for f in found] == [3]


def test_phrasing_empty(settings):
    assert wc.phrasing_lint("", settings) == []


def test_his_edited_list_is_the_one_checked(settings):
    writing_files.write_text(settings, "ai_phrases", "frankly\n")
    found = wc.phrasing_lint("Frankly, the debt is the story.", settings)
    assert len(found) == 1


# --------------------------------------------------------------- swearing
def _spread(n: int, gap_words: int = 200) -> str:
    filler = " ".join(["the margin held"] * (gap_words // 3))
    return "\n".join(f"{filler} and that is fucking bleak." for _ in range(n))


def test_long_fifth_swear_warns():
    found = wc.swear_lint(_spread(5), "long")
    assert len(found) == 1 and found[0].line == 5
    assert found[0].gate == "swearing"


def test_four_spread_out_is_fine():
    assert wc.swear_lint(_spread(4), "long") == []


def test_two_swears_within_a_minute_warn():
    text = "This is fucking grim.\nTruly fucked, the debt schedule."
    found = wc.swear_lint(text, "long")
    assert len(found) == 1 and found[0].line == 2
    assert "minute" in found[0].message


def test_short_second_swear_warns():
    text = "Fuck. " + " ".join(["the margin held"] * 60) + " Fucking grim."
    found = wc.swear_lint(text, "short")
    assert len(found) == 1


def test_mild_words_are_not_counted():
    assert wc.swear_lint("Damn. Hell of a quarter. Shit margins.", "short") == []


def test_swear_in_title_warns():
    found = wc.package_swears({"title 1": "This stock is shit",
                               "description": "A fine description."})
    assert len(found) == 1 and "title 1" in found[0].message


def test_clean_package_no_findings():
    assert wc.package_swears({"title 1": "The margin that fell ninety percent",
                              "pinned comment": "Not advice."}) == []


def test_run_gates_records_phrasing_and_swearing(settings):
    from pipeline.gates import run_gates

    class _Script:
        ticker = "EXMPL"
        narration = "Here's the thing. It fell, and it is fucking grim."
        events: list = []

    report = run_gates(_Script(), settings, skeptic=False)
    assert "phrasing" in report.ran and "swearing" in report.ran
    assert any(f.gate == "phrasing" for f in report.findings)


# --------------------------------------------------------------- S2 copy
def test_bible_line_reused_warns(settings):
    text = ("Revenue grew.\nPut a dollar in. Get three and a half cents back "
            "a year.")
    found = wc.copy_check(text, settings)
    assert found and found[0].gate == "copy" and found[0].line == 2
    assert "bible" in found[0].message


def test_style_reference_reworded_slightly_warns(settings):
    text = ("If you draw enough horizontal lines on a chart, the stock is "
            "eventually going to bounce off one of them.")
    found = wc.copy_check(text, settings)
    assert found and "style reference" in found[0].message


def test_same_topic_different_words_passes(settings):
    text = ("Tyler has drawn support at forty dollars, at thirty-five and at "
            "thirty. It is not a support line any more, it is a staircase.")
    assert wc.copy_check(text, settings) == []


def test_copy_empty(settings):
    assert wc.copy_check("", settings) == []
