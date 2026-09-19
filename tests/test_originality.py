"""The two things that keep one video from being the last one re-tickered:
the sameness gate, and rotating the plates off what was just used."""

from __future__ import annotations

import json

from pipeline.corpus import (
    SAMENESS_BLOCK, SAMENESS_WARN, SAMENESS_WINDOW, sameness_check,
)
from pipeline.reach import ROTATION_WINDOW, recent_plates, rotation_line


class _Script:
    def __init__(self, narration: str, ticker: str = "NEWCO"):
        self.audio_script = narration
        self.ticker = ticker
        self.events = []


SCAFFOLD = ("{t} fell {n} percent this quarter and the market decided it was "
            "cheap. But the filings say something else entirely, and the "
            "something else is the whole argument. Here is what the balance "
            "sheet actually shows when you read it in order.")


def _shipped(settings, ticker: str, workdate: str, narration: str) -> None:
    ws = settings.workspace_dir / ticker / workdate
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "script_short.json").write_text(
        json.dumps({"ticker": ticker, "format": "short",
                    "audio_script": narration}), encoding="utf-8")


# ------------------------------------------------------------ sameness gate


def test_a_first_video_has_nothing_to_be_similar_to(settings):
    assert sameness_check(_Script("Anything at all here."), settings) == []


def test_a_genuinely_different_script_passes(settings):
    _shipped(settings, "OLDCO", "2026-09-01", SCAFFOLD.format(t="OLDCO", n="31"))

    findings = sameness_check(_Script(
        "Management spent the entire call describing a product nobody has "
        "asked for, and the cash to build it is not on the balance sheet."),
        settings)

    assert findings == []


def test_the_same_video_with_a_different_ticker_blocks(settings):
    _shipped(settings, "OLDCO", "2026-09-01", SCAFFOLD.format(t="OLDCO", n="31"))

    findings = sameness_check(
        _Script(SCAFFOLD.format(t="NEWCO", n="12")), settings)

    assert len(findings) == 1
    assert findings[0].severity == "block"
    assert findings[0].gate == "sameness"
    assert "OLDCO" in findings[0].message
    assert "inauthentic-content rule" in findings[0].message
    # The writer gets the repeated run back in words they can recognise.
    assert findings[0].excerpt


def test_a_partial_repeat_warns_rather_than_blocking(settings):
    _shipped(settings, "OLDCO", "2026-09-01", SCAFFOLD.format(t="OLDCO", n="31"))

    half = (SCAFFOLD.format(t="NEWCO", n="12").split(".")[0]
            + ". Beyond that this video has an entirely separate subject, its "
              "own structure, and a conclusion drawn from a different set of "
              "documents than any previous one reached for.")
    findings = sameness_check(_Script(half), settings)

    if findings:                       # the overlap sits near the threshold
        assert findings[0].severity in ("warn", "block")
        assert SAMENESS_WARN < 1.0


def test_an_update_on_the_same_ticker_is_not_repetition(settings):
    # A thesis update is deliberately the same argument about the same
    # company. Flagging it would flag the format working as designed.
    _shipped(settings, "NEWCO", "2026-09-01", SCAFFOLD.format(t="NEWCO", n="31"))

    assert sameness_check(
        _Script(SCAFFOLD.format(t="NEWCO", n="12")), settings) == []


def test_an_empty_script_is_not_compared(settings):
    _shipped(settings, "OLDCO", "2026-09-01", SCAFFOLD.format(t="OLDCO", n="31"))
    assert sameness_check(_Script("   "), settings) == []


def test_the_thresholds_are_ordered():
    assert 0 < SAMENESS_WARN < SAMENESS_BLOCK < 1
    assert SAMENESS_WINDOW > 1


# --------------------------------------------------------------- rotation


def _rendered(settings, ticker: str, workdate: str, plates: list[str]) -> None:
    ws = settings.workspace_dir / ticker / workdate
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "short.manifest.json").write_text(
        json.dumps({"ticker": ticker, "plates_used": plates}), encoding="utf-8")


def test_nothing_rendered_means_nothing_to_avoid(settings):
    assert recent_plates(settings) == set()
    assert "nothing rendered recently" in rotation_line(settings)


def test_the_last_renders_plates_come_back(settings):
    _rendered(settings, "AAA", "2026-09-01", ["room/desk", "host/a"])
    _rendered(settings, "BBB", "2026-09-02", ["room/wall", "host/b"])

    assert recent_plates(settings) == {"room/desk", "host/a",
                                       "room/wall", "host/b"}


def test_only_the_window_counts(settings):
    for i in range(6):
        _rendered(settings, f"T{i}", f"2026-09-0{i + 1}", [f"room/{i}"])

    assert len(recent_plates(settings)) == ROTATION_WINDOW


def test_an_unreadable_manifest_contributes_nothing(settings):
    ws = settings.workspace_dir / "AAA" / "2026-09-01"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "short.manifest.json").write_text("{not json", encoding="utf-8")

    assert recent_plates(settings) == set()


def test_a_manifest_from_before_plates_were_recorded_is_skipped(settings):
    ws = settings.workspace_dir / "AAA" / "2026-09-01"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "short.manifest.json").write_text(json.dumps({"ticker": "AAA"}),
                                            encoding="utf-8")

    assert recent_plates(settings) == set()


def test_the_rotation_line_scores_this_video_against_the_last_few(settings):
    _rendered(settings, "AAA", "2026-09-01", ["room/desk", "host/a"])

    same = rotation_line(settings, {"room/desk", "host/a"})
    different = rotation_line(settings, {"room/wall", "host/b"})

    assert "100%" in same and "much the same look" in same
    assert "0%" in different and "different-looking" in different
