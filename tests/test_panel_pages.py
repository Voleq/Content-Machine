"""The page's Ideas, Calendar and Stats screens as data (bot/panel_pages)."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from bot.handlers import BotCore
from bot.panel import Panel
from bot.panel_pages import calendar_view, ideas_view, stats_view

CHAT = 5150


@pytest.fixture()
def panel(settings):
    return Panel(BotCore(settings.model_copy(update={"operator_chat_ids": [CHAT]})), loop=None)


def test_ideas_view(panel):
    from pipeline.alerts import EarningsCalendar, Watchlist
    from pipeline.standing import IdeaQueue

    s = panel.settings
    IdeaQueue(s).add("ACME", "up 30% on a contract", "operator", score=2.0, lane="short")
    Watchlist(s).add("ZZZ")
    EarningsCalendar(s).set("ACME", "2099-01-05", "amc")
    (s.state_dir / "last_screen.json").write_text(json.dumps({"ts": 1.0, "tickers": {
        "ACME": {"lane": "trending", "reasons": ["volume 5x"], "price": 12.5, "pct_change": 30.1}}}),
        encoding="utf-8")
    view = ideas_view(panel)
    assert view["backlog"][0]["ticker"] == "ACME" and view["backlog"][0]["lane"] == "short"
    assert view["screen"]["rows"][0]["reasons"] == ["volume 5x"]
    assert "ZZZ" in view["watch"]
    assert view["earnings"] == [{"ticker": "ACME", "date": "2099-01-05", "when": "amc"}]


def test_calendar_marks_gaps(panel):
    from pipeline.youtube import VideoLog, VideoRecord

    VideoLog(panel.settings).record(VideoRecord(
        ticker="EXMPL", video_id="v1", title="one", privacy="scheduled",
        publish_at="2026-10-21T14:00:00Z", uploaded_at="2026-10-18T09:00:00Z",
        workdate="2026-10-18", fmt="short"))
    now = datetime(2026, 10, 19, 9, 0, tzinfo=timezone.utc)
    view = calendar_view(panel, "2026-10", now=now)
    days = {d["date"]: d for d in view["days"]}
    assert len(view["days"]) == 31 and view["title"] == "October 2026"
    assert days["2026-10-21"]["items"][0]["pending"] is True
    assert days["2026-10-21"]["gap"] is False
    assert days["2026-10-22"]["gap"] is True
    assert days["2026-10-01"]["gap"] is False and days["2026-10-01"]["past"]
    assert view["prev"] == "2026-09" and view["next"] == "2026-11"
    assert calendar_view(panel, "nonsense", now=now)["month"] == "2026-10"


def test_calendar_offers_finished_videos(panel, fixtures_dir, short_valid_json):
    core = panel.core
    core.start_lane(CHAT, "short", "EXMPL")
    core.handle_upload(CHAT, "dennis_data.xlsx",
                       (fixtures_dir / "company_data" / "dennis_data.xlsx").read_bytes())
    core.intake_script(CHAT, short_valid_json)
    ws = core.context.get(CHAT)
    assert calendar_view(panel)["ready"] == []
    (ws.path / "short_final.mp4").write_bytes(b"\0" * 64)
    assert calendar_view(panel)["ready"] == [
        {"ticker": "EXMPL", "workdate": ws.workdate, "fmt": "short"}]


def test_stats_view_with_no_videos(panel):
    view = stats_view(panel)
    for key in ("hooks", "rules", "runtime", "chapters", "experiments", "scoreboard"):
        assert "error" not in view[key], (key, view[key])
    assert view["hooks"]["short"]["rows"] == []
    assert view["chapters"]["rows"] == []
    assert isinstance(view["scoreboard"]["text"], str)
