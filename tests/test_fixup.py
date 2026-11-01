"""The fix-up prompt: the Check step's findings as one message for the
chat that wrote the script (RDDT long, 1 Nov 2026)."""

from __future__ import annotations

from bot.panel_views import parse_finding
from pipeline.fixup import fixup_prompt


def _f(text: str, sev: str) -> dict:
    return parse_finding(text, sev)


REPORT = [
    _f("[fact-check] L45: “thirty six” is stated for revenue growth but your "
       "workbook has FY22 vs FY21 +37.5%\n    “Revenue per user is up "
       "thirty-six percent in a year.”", "block"),
    _f("[budget] paper/filing-page-16x9 docref: 74 characters against the 38 "
       "that box holds.\n    “Form 10-Q, quarter ended 30 June 2026”", "block"),
    _f("Dennis is alone on screen for about 60% of the video, over the 35% "
       "you set.", "warn"),
    _f('the [SCENE] over "Reddit has a habit: guide" holds him in one shot '
       "for about 40s.", "warn"),
    _f("[joke-floor] 12 jokes at Dennis's own expense (self-owns, family, his "
       "account)", "warn"),
    _f("[kit] [PLATE: revenue-mix-16x9] leaves 9 of 21 text slots empty", "warn"),
    _f('clip "air fryer" not in the vetted palette — will fetch it as a raw '
       "query", "warn"),
    _f("[voice] L9: about 29 seconds of explanation with no turn in it", "warn"),
    _f("[skeptic] AI cannibalization — data licensing offsets it.", "warn"),
    _f("[fact-check] L39: you let this through: “six eighty seven”", "note"),
]


def test_it_carries_what_the_writer_can_fix_and_nothing_else():
    text = fixup_prompt(REPORT, "long")
    assert "send back the WHOLE script" in text and "=== JOKES ===" in text
    must = text[text.index("MUST FIX"):text.index("DENNIS ALONE")]
    assert "thirty six" in must and "Revenue per user is up" in must
    assert "docref" in must and "say plainly what it is" in must
    alone = text[text.index("DENNIS ALONE"):text.index("SHOULD FIX")]
    assert "fifty words" in alone and "Reddit has a habit" in alone
    assert "own expense" in text[text.index("SHOULD FIX"):]
    for left_out in ("leaves 9 of 21", "vetted palette", "seconds of "
                     "explanation", "AI cannibalization", "six eighty seven"):
        assert left_out not in text, left_out


def test_nothing_to_fix_is_no_prompt():
    assert fixup_prompt([REPORT[-1], REPORT[-2], REPORT[5]], "long") == ""


def test_a_short_is_sent_back_as_its_json():
    text = fixup_prompt(REPORT[:2], "short")
    assert "the whole JSON again" in text and "=== JOKES ===" not in text
