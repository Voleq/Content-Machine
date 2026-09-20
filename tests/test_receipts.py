"""The receipts: the disclosure record, corrections, the companion page,
the clip pairs and the quarterly scoreboard."""

from __future__ import annotations

import json

import pytest

from pipeline.companion import build_page, write_companion
from pipeline.experiments import experiments, experiments_text, pair_id
from pipeline.scoreboard import build, quarter_bounds, quarter_of, scoreboard_text
from pipeline.standing import ThesisBook
from pipeline.youtube import (
    VideoLog, VideoRecord, UploadError, corrections_text, pin_correction,
)
from datetime import date


# -------------------------------------------------------- disclosure receipt


def test_a_record_written_before_the_field_existed_still_loads(settings):
    # The whole reason this could be added without a migration.
    log_ = VideoLog(settings)
    log_.path.parent.mkdir(parents=True, exist_ok=True)
    log_.path.write_text(json.dumps([
        {"ticker": "AAPL", "video_id": "v1", "title": "t", "privacy": "private"}
    ]), encoding="utf-8")

    record = log_.get("v1")

    assert record is not None
    assert record.synthetic_declared is None, "unknown, not denied"
    assert record.corrections == []


def test_the_declaration_is_three_states_not_two(settings):
    for declared, expected in ((True, True), (False, False), (None, None)):
        record = VideoRecord(ticker="A", video_id=f"v{declared}", title="t",
                             privacy="private", synthetic_declared=declared)
        VideoLog(settings).record(record)
        assert VideoLog(settings).get(f"v{declared}").synthetic_declared is expected


# ---------------------------------------------------------------- corrections


def test_a_correction_lands_on_the_record(settings):
    VideoLog(settings).record(VideoRecord(
        ticker="AAPL", video_id="v1", title="AAPL video", privacy="public",
        uploaded_at="2026-09-01T00:00:00+00:00"))

    out = pin_correction("AAPL", "gross margin was 41%, not 44%", settings)

    record = VideoLog(settings).get("v1")
    assert len(record.corrections) == 1
    assert "41%" in record.corrections[0]["text"]
    assert "Correction pinned" in out


def test_a_correction_needs_a_video_that_was_uploaded(settings):
    with pytest.raises(UploadError):
        pin_correction("NOPE", "something", settings)


def test_corrections_read_back_newest_first(settings):
    VideoLog(settings).record(VideoRecord(
        ticker="AAPL", video_id="v1", title="t", privacy="public",
        uploaded_at="2026-09-01T00:00:00+00:00"))
    pin_correction("AAPL", "first one", settings)
    pin_correction("AAPL", "second one", settings)

    text = corrections_text(settings)

    assert "2 correction" in text
    assert text.index("second one") < text.index("first one")


def test_no_corrections_is_a_record_worth_keeping(settings):
    assert "worth keeping true" in corrections_text(settings)


def test_a_correction_in_mock_mode_never_reaches_the_network(settings):
    # `settings` is MOCK_MODE and the suite's network guard would fail the
    # test if this tried; the assertion is that the record is still written.
    VideoLog(settings).record(VideoRecord(
        ticker="AAPL", video_id="v1", title="t", privacy="public"))
    pin_correction("AAPL", "a fix", settings)

    assert VideoLog(settings).get("v1").corrections


# ------------------------------------------------------------ companion page


def test_the_page_carries_the_provenance_a_viewer_would_ask_for():
    page = build_page({
        "ticker": "AAPL", "format": "short", "duration_s": 61.2,
        "prices": {"source": "stooq", "degraded": False},
        "provenance": {"filings": ["10-K 2025"],
                       "voice": {"voice": "dennis", "model": "eleven_v3"},
                       "gates": "fact-check ✓ prices ✓"},
    }, why="Because the inventory line is the whole story.")

    assert "AAPL" in page
    assert "stooq" in page
    assert "10-K 2025" in page
    assert "Because the inventory line" in page
    assert "generated, not recorded" in page
    assert page.startswith("<!doctype html>")


def test_the_page_says_the_narration_is_synthetic_even_with_no_voice_block():
    assert "generated, not recorded" in build_page({"ticker": "AAPL"})


def test_a_degraded_price_chart_is_admitted_on_the_page():
    page = build_page({"ticker": "A",
                       "prices": {"source": "floor", "degraded": True}})
    assert "seeded floor" in page


def test_a_thin_manifest_still_produces_a_page():
    # A receipt that refuses to print because one line is missing is not a
    # receipt.
    assert build_page({}).startswith("<!doctype html>")


def test_the_page_is_written_beside_the_render(settings, tmp_path):
    manifest = tmp_path / "short.manifest.json"
    manifest.write_text(json.dumps({"ticker": "AAPL"}), encoding="utf-8")

    out = write_companion(manifest, settings)

    assert out is not None and out.exists()
    assert out.name == "companion.html"


def test_an_unreadable_manifest_yields_no_page_and_no_exception(settings, tmp_path):
    bad = tmp_path / "x.manifest.json"
    bad.write_text("{not json", encoding="utf-8")

    assert write_companion(bad, settings) is None


# ---------------------------------------------------------------- clip pairs


def _clip(settings, video_id, tag, start, ratios):
    VideoLog(settings).record(VideoRecord(
        ticker="AAPL", video_id=video_id, title=f"clip {video_id}",
        privacy="public", experiment=tag, clip_start_s=start,
        retention={"rows": [{"elapsed_ratio": i / 10, "watch_ratio": r}
                            for i, r in enumerate(ratios)]} if ratios else {}))


def test_two_clips_off_one_render_are_one_experiment(settings):
    tag = pair_id("AAPL", "2026-09-01")
    _clip(settings, "v1", tag, 120.0, [1.0, 0.8, 0.6])
    _clip(settings, "v2", tag, 900.0, [1.0, 0.4, 0.2])

    found = experiments(settings)

    assert len(found) == 1
    assert found[0].decided
    assert found[0].winner.video_id == "v1"
    assert "held best" in found[0].line()


def test_one_clip_is_not_an_experiment(settings):
    _clip(settings, "v1", pair_id("AAPL", "2026-09-01"), 0.0, [1.0])
    assert experiments(settings) == []


def test_a_pair_with_no_views_yet_says_so(settings):
    tag = pair_id("AAPL", "2026-09-01")
    _clip(settings, "v1", tag, 0.0, [])
    _clip(settings, "v2", tag, 60.0, [])

    line = experiments(settings)[0].line()

    assert "no views yet" in line
    assert "Not decided yet" in line


def test_an_ordinary_upload_is_in_no_experiment(settings):
    VideoLog(settings).record(VideoRecord(
        ticker="AAPL", video_id="v1", title="t", privacy="public"))
    assert experiments(settings) == []
    assert "No clip pairs shipped yet" in experiments_text(settings)


# --------------------------------------------------------------- scoreboard


def test_the_quarter_of_a_date():
    assert quarter_of(date(2026, 1, 5)) == "2026-Q1"
    assert quarter_of(date(2026, 9, 19)) == "2026-Q3"
    assert quarter_of(date(2026, 12, 31)) == "2026-Q4"


def test_quarter_bounds_cover_the_whole_quarter():
    start, end = quarter_bounds("2026-Q4")
    assert start == date(2026, 10, 1)
    assert end == date(2027, 1, 1)


def _thesis(settings, ticker, status, workdate, moves=()):
    book = ThesisBook(settings)
    rows = book._all()
    rows[ticker] = {"ticker": ticker, "summary": f"{ticker} is mispriced",
                    "status": status, "workdate": workdate,
                    "last_moves": list(moves), "numbers": {}}
    book.path.parent.mkdir(parents=True, exist_ok=True)
    book.path.write_text(json.dumps(rows), encoding="utf-8")


def test_the_scoreboard_leads_with_what_was_wrong(settings):
    _thesis(settings, "AAA", "broken", "2026-08-10",
            [{"field": "margin", "change": -0.31, "material": True}])
    _thesis(settings, "BBB", "intact", "2026-08-20")

    board = build(settings, "2026-Q3")

    assert board.scored == 2
    assert "1 of 2 calls are wrong" in board.headline()
    assert board.rows[0].ticker == "AAA", "worst first"
    assert "margin moved -31%" in board.rows[0].line()


def test_a_thesis_from_another_quarter_is_not_on_this_board(settings):
    _thesis(settings, "AAA", "broken", "2026-02-10")
    assert build(settings, "2026-Q3").scored == 0


def test_an_empty_quarter_says_there_is_nothing_to_score(settings):
    assert "nothing to score" in build(settings, "2026-Q3").headline()
    assert "fills in as videos ship" in scoreboard_text(settings, "2026-Q3")


def test_a_nonsense_quarter_is_refused_in_words(settings):
    assert "is not a quarter" in scoreboard_text(settings, "banana")


def test_the_brief_gives_the_writer_the_calls_not_a_script(settings):
    _thesis(settings, "AAA", "broken", "2026-08-10",
            [{"field": "margin", "change": -0.31, "material": True}])

    brief = build(settings, "2026-Q3").script_brief()

    assert "AAA" in brief
    assert "is mispriced" in brief
    assert "Lead with the ones that were wrong" in brief
