"""The weekly note to the writer, and the stored curve it stands on."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta, timezone

import pytest

from pipeline import llm
from pipeline import retention_notes as rn
from pipeline.publish import byproduct_name
from pipeline.retention_lines import (hook_bench, holds_for_video,
                                      narration_for, write_words)
from pipeline.youtube import (VideoLog, VideoRecord, pull_retention,
                              retention_rows)

NOW = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)

# Six sentences, four words each, at two words a second: twelve seconds.
# The fourth is spoken over 6.0-8.0 s and is where the curve falls.
NARRATION = ("The stock moved today. Volume ran five times. Nobody knows "
             "why yet. Revenue fell forty percent. The margin held anyway. "
             "See you next filing.")
STEEP = "Revenue fell forty percent."


class _W:
    def __init__(self, word, start, end, char_start, char_end):
        self.word, self.start, self.end = word, start, end
        self.char_start, self.char_end = char_start, char_end


def _words_for(narration: str, *, wps: float = 2.0) -> list[_W]:
    out, at = [], 0
    for i, word in enumerate(narration.split()):
        start = narration.index(word, at)
        at = start + len(word)
        out.append(_W(word, i / wps, (i + 1) / wps, start, at))
    return out


def _curve(duration: float = 12.0, cliff_at: float = 7.0) -> list[dict]:
    """A slow slide with one cliff inside the fourth sentence."""
    rows = []
    for e in range(21):
        t = e / 20 * duration
        rows.append({"elapsed_ratio": e / 20,
                     "watch_ratio": 1.0 - 0.01 * e - (0.3 if t >= cliff_at else 0)})
    return rows


def _published(settings, ticker, *, days_ago=3, retention=None, fmt="short",
               narration=NARRATION, duration=12.0, experiment=""):
    workdate = (NOW - timedelta(days=days_ago)).date().isoformat()
    ws = settings.workspace_dir / ticker / workdate
    ws.mkdir(parents=True, exist_ok=True)
    if fmt != "clip":
        key = "narration" if fmt == "long" else "audio_script"
        (ws / f"script_{fmt}.json").write_text(
            json.dumps({"ticker": ticker, "format": fmt, key: narration}),
            encoding="utf-8")
        write_words(_words_for(narration), ws / byproduct_name("words", fmt))
    record = VideoRecord(
        ticker=ticker, video_id=f"vid-{ticker}-{fmt}", title=f"{ticker} video",
        privacy="public", workdate=workdate, duration_s=duration,
        uploaded_at=(NOW - timedelta(days=days_ago)).isoformat(),
        retention=({"rows": retention} if retention is not None else {}),
        fmt=fmt, experiment=experiment)
    VideoLog(settings).record(record)
    return record


class _Analytics:
    """Stands in for the YouTube client: only the retention call."""

    def __init__(self, rows):
        self.rows = rows
        self.asked: list[str] = []

    def retention(self, video_id, start, end):
        self.asked.append(video_id)
        return self.rows


def _model(text: str, calls: list):
    def chat_result(prompt, settings, *, system="", purpose="llm",
                    providers=None):
        calls.append({"prompt": prompt, "purpose": purpose,
                      "providers": providers})
        return llm.LLMResult(text=text, provider=llm.OLLAMA, model="m",
                             reason=llm.OK)
    return chat_result


# ------------------------------------------------------ the stored curve


def test_a_pull_stores_the_curve_not_how_long_it_was(settings):
    """`pull_retention` stored `len(rows)` under `rows`, and every reader
    downstream reads `rows` as the curve."""
    _published(settings, "AAPL")
    payload = pull_retention("vid-AAPL-short", settings,
                             client=_Analytics(_curve()), today=NOW)

    stored = VideoLog(settings).get("vid-AAPL-short").retention
    assert payload["status"] == "ok"
    assert stored["rows"] == _curve()
    assert stored["row_count"] == 21


def test_a_pulled_curve_reaches_the_sentence_join(settings):
    """End to end, through the real pull rather than a record built by hand
    with the curve already in place, which is how the bug hid."""
    _published(settings, "AAPL")
    pull_retention("vid-AAPL-short", settings, client=_Analytics(_curve()),
                   today=NOW)

    record = VideoLog(settings).get("vid-AAPL-short")
    holds = holds_for_video(settings, record, narration_for(settings, record))

    assert holds, "the pulled curve joined nothing"
    assert max(holds, key=lambda h: h.drop).text == STEEP


def test_a_record_holding_a_count_reads_as_no_curve(settings):
    """Rows pulled before the fix hold an integer. Every reader treats that
    as nothing pulled yet, and none of them raises."""
    from pipeline.corpus import _video_index
    from pipeline.experiments import experiments

    record = _published(settings, "AAPL", experiment="pair-x")
    VideoLog(settings).update_retention(record.video_id,
                                        {"status": "ok", "rows": 21})
    old = VideoLog(settings).get(record.video_id)

    assert retention_rows(old.retention) == []
    assert holds_for_video(settings, old, NARRATION) == []
    assert hook_bench(settings) == []
    assert _video_index(settings)[f"AAPL/{old.workdate}"]["hold"] is None
    experiments(settings)


def test_retention_rows_drops_malformed_rows():
    got = retention_rows({"rows": [{"elapsed_ratio": 0.0, "watch_ratio": 1.0},
                                   {"elapsed_ratio": "x", "watch_ratio": 1.0},
                                   "junk"]})
    assert got == [{"elapsed_ratio": 0.0, "watch_ratio": 1.0}]
    assert retention_rows(None) == []


# --------------------------------------------------------------- the pull


def test_the_weekly_pull_skips_clips_and_settled_videos(settings):
    _published(settings, "AAPL", days_ago=3)
    _published(settings, "MSFT", days_ago=rn.PULL_WITHIN_DAYS + 30)
    _published(settings, "NVDA", days_ago=3, experiment="pair-y", duration=58.0,
               fmt="clip")
    client = _Analytics(_curve())

    pulled, why = rn.refresh_retention(settings, client=client, today=NOW)

    assert (pulled, why) == (1, "")
    assert client.asked == ["vid-AAPL-short"]


def test_no_youtube_is_a_reason_not_an_error(settings):
    pulled, why = rn.refresh_retention(settings, today=NOW)
    assert pulled == 0
    assert why, "the reason nothing was pulled is said, not swallowed"


# ---------------------------------------------------------------- the note


def test_under_the_floor_the_note_says_so_and_asks_no_model(settings,
                                                             monkeypatch):
    for ticker in ("AAPL", "MSFT"):
        _published(settings, ticker, retention=_curve())

    def refuse(*a, **k):
        raise AssertionError("two videos are an anecdote; no model call")
    monkeypatch.setattr(llm, "chat_result", refuse)

    note = rn.write_note(settings, "short", today=NOW)

    assert note["status"] == "thin"
    assert note["videos"] == 2
    assert "2 of the 3 videos" in rn.note_block(settings, "short")


def test_at_the_floor_the_note_counts_then_reads(settings, monkeypatch):
    for ticker in ("AAPL", "MSFT", "NVDA"):
        _published(settings, ticker, retention=_curve())
    calls: list = []
    monkeypatch.setattr(llm, "chat_result", _model(
        "- They open on a figure: 'Revenue fell forty percent'. 83% of them do.\n"
        "Next script: put the turn before the number.", calls))

    note = rn.write_note(settings, "short", today=NOW)

    assert note["status"] == "ok"
    assert note["videos"] == 3
    assert note["worst"][0]["text"] == STEEP
    assert "sentences people left on" in note["counts"]
    assert "a figure spoken" in note["counts"]
    # The model saw the sentence and the one before it, and the counts.
    assert STEEP in calls[0]["prompt"]
    assert "before: Nobody knows why yet." in calls[0]["prompt"]
    assert calls[0]["purpose"] == "retention-note"
    # A number the counts do not contain is flagged, not repeated as fact.
    assert "83%" in note["flagged"]


def test_the_note_never_reaches_the_paid_tier(settings, monkeypatch):
    for ticker in ("AAPL", "MSFT", "NVDA"):
        _published(settings, ticker, retention=_curve())
    calls: list = []
    monkeypatch.setattr(llm, "chat_result", _model("- a reading", calls))

    rn.write_note(settings, "short", today=NOW)

    assert llm.OPENAI not in calls[0]["providers"]
    assert llm.OLLAMA in calls[0]["providers"]


def test_a_dead_daemon_leaves_the_counts(settings, monkeypatch):
    for ticker in ("AAPL", "MSFT", "NVDA"):
        _published(settings, ticker, retention=_curve())
    monkeypatch.setattr(llm, "chat_result", lambda *a, **k: llm.LLMResult(
        provider=llm.OLLAMA, reason=llm.NO_DAEMON))

    note = rn.write_note(settings, "short", today=NOW)

    assert note["status"] == "ok"
    assert note["reading"] == ""
    assert note["skipped"] == llm.NO_DAEMON
    assert "sentences people left on" in rn.note_block(settings, "short")


def test_lanes_do_not_borrow_each_others_videos(settings, monkeypatch):
    for ticker in ("AAPL", "MSFT", "NVDA"):
        _published(settings, ticker, retention=_curve())
    monkeypatch.setattr(llm, "chat_result", _model("- a reading", []))

    assert rn.write_note(settings, "long", today=NOW)["videos"] == 0


def test_a_note_is_due_weekly(settings, monkeypatch):
    monkeypatch.setattr(llm, "chat_result", _model("- a reading", []))
    assert rn.notes_due(settings, today=NOW)

    rn.refresh_notes(settings, today=NOW)

    assert not rn.notes_due(settings, today=NOW + timedelta(days=1))
    assert rn.notes_due(settings, today=NOW + timedelta(
        days=settings.retention_note_days))


def test_the_weekly_pass_writes_both_lanes_without_youtube(settings):
    summary = rn.refresh_notes(settings, today=NOW)

    assert "no fresh retention" in summary
    assert set(rn.load_notes(settings)) == {"short", "long"}


# ------------------------------------------------------------ the prompts


def _prompt(settings, fixtures_dir, tmp_path, fmt):
    from pipeline.company_data import load_company_data

    from bot.prompts import fill_prompt

    ws = tmp_path / f"ws-{fmt}"
    ws.mkdir()
    shutil.copy(fixtures_dir / "company_data" / "dennis_data.xlsx",
                ws / "dennis_data.xlsx")
    return fill_prompt(fmt, "EXMPL", load_company_data(ws), ws, settings,
                       chosen_angle="x", headline="x")


def test_every_writing_prompt_carries_its_lanes_note(settings, fixtures_dir,
                                                     tmp_path, monkeypatch):
    for ticker in ("AAPL", "MSFT", "NVDA"):
        _published(settings, ticker, retention=_curve())
    monkeypatch.setattr(llm, "chat_result",
                        _model("- They open on a figure.", []))
    rn.refresh_notes(settings, today=NOW)

    for fmt in ("short", "headline"):
        text = _prompt(settings, fixtures_dir, tmp_path, fmt)
        assert "{{retention_note}}" not in text
        assert "They open on a figure." in text, fmt
    for fmt in ("long_write", "update"):
        text = _prompt(settings, fixtures_dir, tmp_path, fmt)
        assert "{{retention_note}}" not in text
        assert "Nothing to act on yet" in text, fmt
    assert "WHERE VIEWERS HAVE LEFT" not in _prompt(
        settings, fixtures_dir, tmp_path, "long_angle")


def test_a_prompt_with_no_note_yet_says_so(settings, fixtures_dir, tmp_path):
    assert "no note yet" in _prompt(settings, fixtures_dir, tmp_path, "short")


def test_switched_off_the_prompt_says_so(settings, fixtures_dir, tmp_path,
                                         monkeypatch):
    monkeypatch.setattr(settings, "retention_notes_enabled", False)
    assert "switched off" in _prompt(settings, fixtures_dir, tmp_path, "short")


# ---------------------------------------------------------------- /lessons


def test_lessons_is_honest_when_empty(settings):
    from bot.handlers import BotCore

    assert "No note yet" in BotCore(settings).lessons_text([])


def test_lessons_now_rewrites_and_shows_it(settings, monkeypatch):
    from bot.handlers import BotCore

    for ticker in ("AAPL", "MSFT", "NVDA"):
        _published(settings, ticker, retention=_curve())
    monkeypatch.setattr(llm, "chat_result",
                        _model("- They open on a figure.", []))

    text = BotCore(settings).lessons_text(["now"])

    assert text.startswith("Rewritten:")
    assert "SHORT" in text and "3 videos" in text
    assert "Revenue fell forty percent" in text
    assert "They open on a figure." in text
