"""Findings from the full review of the money, voice, sound and ops code.

Each test names what a viewer or the operator would have seen go wrong.
"""

from __future__ import annotations

import os
import time
from datetime import date, datetime, timedelta, timezone

from pipeline.workspace import Workspace


def _ready_to_upload(st):
    st.lane, st.fmt, st.data_file, st.script = "short", "short", "x", True
    st.report_ok, st.approved = True, True
    st.renders = {"final": "short_final.mp4"}
    return st


def test_a_scheduled_upload_whose_time_has_passed_is_published(settings):
    """The card said "scheduled for 2026-09-05" a month after it went public,
    and the inbox never offered its retention: a scheduled row is never
    rewritten when its time comes."""
    from pipeline.video_state import inbox, video_state
    from pipeline.youtube import VideoLog, VideoRecord

    now = datetime(2026, 10, 5, 12, tzinfo=timezone.utc)
    uploaded = now - timedelta(days=30)
    publish = now - timedelta(days=4)
    ws = Workspace(settings, "EXMPL", "2026-09-04").create()
    rec = VideoRecord(ticker="EXMPL", video_id="v1", title="t",
                      privacy="scheduled", publish_at=publish.isoformat(),
                      uploaded_at=uploaded.isoformat(),
                      workdate=ws.workdate, fmt="short")
    st = _ready_to_upload(video_state(settings, ws, jobs=[], videos=[rec],
                                      now=now))
    up = st.uploaded
    assert up["pending"] is False
    # Its age runs from when viewers could first see it, not the upload.
    assert up["age_h"] == 96.0
    assert st.next_step() == ("read where viewers left: /stats retention",
                              "retention")

    VideoLog(settings).record(rec)
    sections = [i.section for i in inbox(settings, now=now, states=[])]
    assert "retention" in sections

    # Still ahead: still scheduled, and nothing to read yet.
    ahead = VideoRecord(**{**rec.__dict__,
                           "publish_at": (now + timedelta(days=1)).isoformat()})
    st = _ready_to_upload(video_state(settings, ws, jobs=[], videos=[ahead],
                                      now=now))
    assert st.uploaded["pending"] is True
    assert st.next_step()[0].startswith("scheduled for")


def test_since_a_month_runs_to_today():
    """"How much did voice cost since august" answered August alone."""
    from pipeline.tally import parse_period

    today = date(2026, 10, 16)
    got = parse_period("how much did voice cost since august", today)
    assert (got.start, got.end) == (date(2026, 8, 1), today)
    assert got.label == "since August 2026"
    got = parse_period("how many shorts since 2025", today)
    assert (got.start, got.end) == (date(2025, 1, 1), today)
    # "in august" is still the month.
    got = parse_period("spend in august", today)
    assert (got.start, got.end) == (date(2026, 8, 1), date(2026, 8, 31))


def test_a_range_is_not_read_as_a_minus_sign():
    """"margins of 5-10%" was flagged as "minus ten percent", which an
    operator following the lint would have written into the narration."""
    from pipeline.spoken import eye_written_figures

    said = dict(eye_written_figures("margins of 5-10% this year, "
                                    "from 2.5%-4% and $10-$12 million"))
    assert not any("minus" in v for v in said.values()), said
    assert dict(eye_written_figures("it fell -10% today")) == {
        "-10%": "minus ten percent"}


def test_the_status_page_is_started_with_the_bot():
    """STATUS_PAGE_ENABLED was documented and nothing ever called `serve`."""
    from pathlib import Path

    main = (Path(__file__).resolve().parents[1] / "main.py").read_text(
        encoding="utf-8")
    assert "from pipeline.status_page import serve" in main
    assert "serve(settings)" in main


def test_a_count_reaching_past_the_kept_jobs_says_so(settings):
    """Finished renders are counted from job records, which the cleanup
    deletes after JOBS_RETENTION_DAYS; "all time" silently left them out."""
    from pipeline.tally import ALL_TIME, Period, _video_lines

    lines = _video_lines(settings, ALL_TIME, "", "how many shorts")
    assert any("kept" in line and "days" in line for line in lines)
    today = date.today()
    lines = _video_lines(settings, Period(today, today, "today"), "",
                         "how many shorts")
    assert not any("kept" in line for line in lines)


def test_a_short_and_a_long_of_one_day_are_two_uploads(settings):
    """Keyed on the day alone, an abandoned LONG beside an uploaded SHORT
    counted as shipped and joined the sameness comparisons."""
    import json

    from pipeline.corpus import build_index
    from pipeline.youtube import VideoLog, VideoRecord

    for fmt, key in (("short", "audio_script"), ("long", "narration")):
        ws = settings.workspace_dir / "AAA" / "2026-09-01"
        ws.mkdir(parents=True, exist_ok=True)
        (ws / f"script_{fmt}.json").write_text(
            json.dumps({"ticker": "AAA", "format": fmt, key: "One. Two."}),
            encoding="utf-8")
    VideoLog(settings).record(VideoRecord(
        ticker="AAA", video_id="s1", title="t", privacy="private",
        uploaded_at="2026-09-01T10:00:00+00:00", workdate="2026-09-01",
        fmt="short"))
    by_fmt = {e.fmt: e for e in build_index(settings)}
    assert by_fmt["short"].shipped
    assert not by_fmt["long"].shipped


def test_a_dry_run_counts_each_file_once(settings):
    from pipeline.cleanup import cleanup

    old = (date.today() - timedelta(days=30)).isoformat()
    ws = Workspace(settings, "OLD", old).create()
    (ws.path / "render_short").mkdir()
    (ws.path / "render_short" / "frames.mp4").write_bytes(b"x" * 1_000_000)
    # Last worked on a month ago too: a folder written to inside the window
    # is kept.
    when = time.time() - 30 * 86400
    for p in [ws.path, *ws.path.rglob("*")]:
        os.utime(p, (when, when))
    dry = cleanup(settings, dry_run=True)
    real = cleanup(settings)
    assert dry["freed_mb"] == real["freed_mb"] == 1.0


def test_the_week_includes_its_days_in_the_month_before(settings):
    """An ISO week straddling a month stays one week, and the weekly mark
    read only this month's events."""
    import json

    from pipeline.cost import SpendLedger

    (settings.state_dir / "spend.json").write_text(json.dumps({
        "2026-09": {"tts_usd": 3.0, "events": [
            {"usd": 3.0, "week": "2026-W40", "lane": "long"}]},
        "2026-10": {"tts_usd": 2.0, "events": [
            {"usd": 2.0, "week": "2026-W40", "lane": "long"},
            {"usd": 7.0, "week": "2026-W41", "lane": "long"}]},
    }), encoding="utf-8")
    assert SpendLedger(settings).weekly_usd(week="2026-W40") == 5.0
