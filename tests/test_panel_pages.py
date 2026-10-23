"""The page's Ideas, Calendar, Stats, Library and Settings screens as data
(bot/panel_pages), and the switches and edits they make."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from bot.handlers import BotCore
from bot.panel import Panel
from bot.panel_pages import (calendar_view, ideas_view, library_view,
                             settings_view, stats_view, thumbnail)

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


def test_switch_reaches_settings_and_persists(panel):
    s = panel.settings
    assert s.voice_room is False
    reply = panel.core.set_switch("voice_room", True)
    assert "on from now" in reply.text and s.voice_room is True
    # A restart: a fresh Settings off .env (here, the defaults) gets the
    # page's word back when the bot starts.
    fresh = s.model_copy(update={"voice_room": False})
    BotCore(fresh)
    assert fresh.voice_room is True
    row = {r["name"]: r for r in settings_view(panel)["switches"]}["voice_room"]
    assert row["on"] and row["from_page"] and row["env"] == "VOICE_ROOM"
    # The .env spelling works from Telegram too.
    panel.core.set_switch("VOICE_ROOM", False)
    assert s.voice_room is False


def test_unknown_switch_refused(panel):
    reply = panel.core.set_switch("dennis_3d", True)
    assert reply.text.startswith("❌") and "voice_room" in reply.text
    assert not (panel.settings.state_dir / "switches.json").exists()
    # A hand-edited file with a key or a non-bool in it changes nothing.
    (panel.settings.state_dir / "switches.json").write_text(
        json.dumps({"elevenlabs_api_key": True, "short_meme": "yes"}), encoding="utf-8")
    from pipeline.switches import apply
    assert apply(panel.settings) == {}


def test_writing_file_save_and_reset(panel):
    from bot.prompts import voice_bible

    core, s = panel.core, panel.settings
    shipped = voice_bible(s)
    assert core.save_writing("voice_bible", "Dennis is dry.\n").text.startswith("💾")
    assert voice_bible(s) == "Dennis is dry."
    assert (s.assets_dir / "voice_bible.md").read_text(encoding="utf-8").strip() == shipped
    row = {w["name"]: w for w in library_view(panel)["writing"]}["voice_bible"]
    assert row["edited"] and row["text"].startswith("Dennis is dry.")
    assert core.save_writing("voice_bible", "   ").text.startswith("❌")
    assert core.save_writing("passwords", "x").text.startswith("❌")
    assert "shipped one again" in core.reset_writing("voice_bible").text
    assert voice_bible(s) == shipped


def test_library_lists_memes_with_labels(panel):
    lib = library_view(panel)
    memes = lib["memes"]["rows"]
    assert memes and all(m["tags"] and m["use_when"] for m in memes)
    assert all(m["file"].startswith("/api/file?path=") and "k=" not in m["file"] for m in memes)
    first = memes[0]["file"].split("path=", 1)[1]
    from urllib.parse import unquote
    small = thumbnail(panel, unquote(first), 200)
    assert small is not None and small.stat().st_size < 200_000
    assert thumbnail(panel, str(panel.settings.state_dir / "x.png"), 200) is None
    assert all(not s["file"] or s["file"].startswith("/api/file") for s in lib["sounds"])


def test_memory_lists_are_edited_as_he_leaves_them(panel):
    from pipeline.channel_memory import FactBook

    s = panel.settings
    FactBook(s).add("k1", ["Dennis sold his car in 2022.", "Dennis has a cat."],
                    ticker="ACME", workdate="2026-10-01")
    reply = panel.core.edit_memory("facts", ["Dennis has a cat.", "Dennis hates Mondays."])
    assert "2 facts" in reply.text
    rows = library_view(panel)["facts"]
    assert [r["text"] for r in rows] == ["Dennis has a cat.", "Dennis hates Mondays."]
    assert rows[0]["ticker"] == "ACME" and rows[1]["ticker"] == ""
    assert panel.core.edit_memory("secrets", []).text.startswith("❌")


def test_health_rows(panel):
    view = settings_view(panel)
    names = {r["name"] for r in view["health"]}
    assert {"design kit", "sound provenance", "3D Dennis", "DELIVERY_BACKEND"} <= names
    assert all(r["state"] in ("ok", "bad", "skip") for r in view["health"])
    assert "test suite" not in names
    assert view["dennis_3d"] == "off" and "DENNIS_3D" in view["dennis_3d_warning"]
    assert view["disk"] and view["disk"][0]["free_gb"] > 0
    assert view["failures"] == []
    # No key or password reaches the page.
    blob = json.dumps(view)
    for secret in ("elevenlabs_api_key", "telegram_bot_token"):
        value = getattr(panel.settings, secret, "") or ""
        assert not value or value not in blob
