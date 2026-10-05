"""The workflow layer: the command registry, the active-video default, the
video card, the next-step buttons, the inbox, the /go wizard, the cancel
undo, quiet notifications, and the web panel that drives all of it.

Everything here runs through `bot.commands` — the same entry points the
Telegram glue and the panel use — against a real BotCore in MOCK_MODE.
"""

from __future__ import annotations

import asyncio
import json
import re
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

import pytest

from bot import commands as cmds
from bot import keyboards as kb
from bot.handlers import BotCore, Reply
from pipeline.models import JobKind, JobStatus
from pipeline.workspace import Workspace

CHAT = 5150

# Every name the bot answered before the families. Each must still answer.
OLD_NAMES = {
    "start", "help", "short", "long", "update", "headline", "prompts",
    "render", "render_long", "render_short", "draft", "proof", "repurpose",
    "upload", "probe", "scheduled", "retention", "watch", "earnings", "ideas",
    "idea", "unidea", "thesis", "batch", "script", "edit", "replace", "undo",
    "status", "cancel", "cost", "lines", "hooks", "rules", "runtime",
    "lessons", "shots", "stillness", "said", "find", "ask", "why",
    "experiments", "scoreboard", "correct", "kit", "screen",
}


@pytest.fixture()
def core(settings):
    small = settings.model_copy(update={
        "short_width": 540, "short_height": 960,
        "long_width": 640, "long_height": 360,
        "operator_chat_ids": [CHAT],
    })
    return BotCore(small)


@pytest.fixture()
def xlsx_bytes(fixtures_dir) -> bytes:
    return (fixtures_dir / "company_data" / "dennis_data.xlsx").read_bytes()


def run(coro):
    return asyncio.run(coro)


def cmd(core, text: str, chat: int = CHAT) -> Reply:
    head, _, raw = text.lstrip("/").partition(" ")
    return run(cmds.run_command(core, chat, head, raw.split(), raw=raw))


def _approved_short(core, xlsx_bytes, short_valid_json):
    core.start_lane(CHAT, "short", "EXMPL")
    core.handle_upload(CHAT, "dennis_data.xlsx", xlsx_bytes)
    core.intake_script(CHAT, short_valid_json)
    ws = Workspace.latest_for(core.settings, "EXMPL")
    core.approve("short", "EXMPL", ws.workdate,
                 ws.load_short().content_sha()[:8])
    return ws


def _buttons(reply_or_markup) -> list[str]:
    markup = getattr(reply_or_markup, "keyboard", reply_or_markup)
    rows = getattr(markup, "inline_keyboard", None) or []
    return [b.callback_data for row in rows for b in row]


# --------------------------------------------------------------------------
# The registry.
# --------------------------------------------------------------------------


def test_every_old_name_still_answers():
    names = set(cmds.telegram_names())
    assert OLD_NAMES <= names, sorted(OLD_NAMES - names)
    for old in OLD_NAMES:
        command, family, _a, _r = cmds.resolve(old, [])
        assert family is not None, old


def test_the_menu_is_the_entry_points_and_the_families():
    menu = [n for n, _ in cmds.menu_commands()]
    assert menu[:3] == ["go", "card", "inbox"]
    assert {"new", "script", "render", "publish", "jobs", "ideas", "stats",
            "search", "admin", "help"} <= set(menu)
    assert len(menu) == 13, "the menu is the short list, not every name"


def test_every_name_is_one_telegram_accepts():
    for name in cmds.telegram_names():
        assert re.fullmatch(r"[a-z0-9_]{1,32}", name), name
    for name, desc in cmds.menu_commands():
        assert 1 <= len(desc) <= 256, name


def test_a_sub_word_routes_to_its_command_and_keeps_the_raw_text():
    command, _f, args, raw = cmds.resolve(
        "script", ["edit", "3", "Revenue"], "edit 3 Revenue fell.\nA second line.")
    assert command.name == "script edit"
    assert args == ["3", "Revenue"]
    assert raw == "3 Revenue fell.\nA second line.", "line breaks survive (M10)"

    command, _f, args, _r = cmds.resolve("render", ["proof", "AAPL", "short"])
    assert command.name == "render proof" and args == ["AAPL", "short"]
    command, _f, args, _r = cmds.resolve("render", ["AAPL"])
    assert command.name == "render" and args == ["AAPL"]
    command, _f, _a, _r = cmds.resolve("draft", ["AAPL"])
    assert command.name == "render draft"


def test_a_family_without_a_default_answers_with_its_help(core):
    reply = cmd(core, "/stats")
    assert "/stats lines" in reply.text and "/stats retention" in reply.text


def test_a_typo_gets_did_you_mean(core):
    assert "/render" in cmd(core, "/rendr EXMPL").text
    # A sub-word typed as a command is pointed at its family.
    assert "/publish calendar" in cmds.unknown_command_text("calendar")


def test_the_help_lists_the_families_and_the_old_names():
    text = cmds.help_text()
    for fam in cmds.FAMILIES:
        assert f"/{fam.name}" in text
    assert "/render_long" in text and "/upload" in text


def test_family_help_fills_in_the_active_ticker(core):
    core.start_lane(CHAT, "short", "EXMPL")
    text = cmds.family_help("render", core=core, chat_id=CHAT)
    assert "e.g. /render proof EXMPL" in text
    assert "(was /draft)" in text


# --------------------------------------------------------------------------
# The active video stands in for a missing ticker (§2).
# --------------------------------------------------------------------------


def test_a_missing_ticker_is_the_active_video(core):
    core.start_lane(CHAT, "short", "EXMPL")
    ws = core.context.get(CHAT)
    c = cmds.Call(core, CHAT, ["short"])
    cmds._fill_ticker(c, cmds.SUBS["render"]["proof"])
    assert c.args == [f"EXMPL@{ws.workdate}", "short"]
    assert c.filled == f"EXMPL {ws.workdate}"

    c = cmds.Call(core, CHAT, [])
    cmds._fill_ticker(c, cmds.SUBS["stats"]["lines"])
    assert c.args == ["EXMPL"], "the upload log is keyed by the bare ticker"


def test_a_named_ticker_is_left_alone(core):
    core.start_lane(CHAT, "short", "EXMPL")
    c = cmds.Call(core, CHAT, ["OTHER"])
    cmds._fill_ticker(c, cmds.SUBS["render"][""])
    assert c.args == ["OTHER"] and not c.filled


def test_free_text_is_not_mistaken_for_a_ticker(core):
    """`/script why great story` — GREAT has no workspace, so it is the
    sentence, and the active video is what it is about."""
    core.start_lane(CHAT, "short", "EXMPL")
    c = cmds.Call(core, CHAT, ["great", "story"])
    cmds._fill_ticker(c, cmds.SUBS["script"]["why"])
    assert c.args[0].startswith("EXMPL@") and c.args[1:] == ["great", "story"]


def test_a_ticker_that_means_every_video_is_not_filled(core):
    core.start_lane(CHAT, "short", "EXMPL")
    c = cmds.Call(core, CHAT, [])
    cmds._fill_ticker(c, cmds.SUBS["stats"]["retention"])
    assert c.args == [], "no ticker is the across-everything view"


def test_no_active_video_is_said_rather_than_guessed(core):
    reply = cmd(core, "/render proof")
    assert "Which video?" in reply.text


def test_the_reply_names_the_video_it_acted_on(core):
    core.start_lane(CHAT, "short", "EXMPL")
    reply = cmd(core, "/render")
    assert reply.text.startswith("📁 EXMPL ")


# --------------------------------------------------------------------------
# The video card, the inbox, the calendar.
# --------------------------------------------------------------------------


def test_the_card_follows_the_video_through_its_stages(core, xlsx_bytes,
                                                       short_valid_json):
    core.start_lane(CHAT, "short", "EXMPL")
    card = cmd(core, "/card")
    assert card.text.startswith("📁 EXMPL · SHORT")
    assert "waiting for dennis_data.xlsx" in card.text
    assert card.card.startswith("EXMPL@")

    ws = _approved_short(core, xlsx_bytes, short_valid_json)
    card = core.video_card("EXMPL")
    assert "approval  ✅" in card.text
    assert "render the final" in card.text
    assert f"r|s|EXMPL|{ws.workdate}" in _buttons(card)

    (ws.path / "short_final.mp4").write_bytes(b"\0" * 64)
    card = core.video_card("EXMPL")
    assert "final ✅" in card.text and "upload it" in card.text
    assert f"u|s|EXMPL|{ws.workdate}" in _buttons(card)


def test_the_intake_saves_the_report_as_data(core, xlsx_bytes,
                                             short_valid_json):
    ws = _approved_short(core, xlsx_bytes, short_valid_json)
    report = json.loads((ws.path / "report_short.json").read_text(
        encoding="utf-8"))
    assert report["ticker"] == "EXMPL" and "est_tts_usd" in report


def test_the_inbox_lists_what_waits_on_you(core, xlsx_bytes, short_valid_json):
    assert "Inbox zero" in core.inbox_reply().text
    ws = _approved_short(core, xlsx_bytes, short_valid_json)
    reply = core.inbox_reply()
    assert "approved, not rendered" in reply.text and "EXMPL" in reply.text
    assert f"c|EXMPL|{ws.workdate}" in _buttons(reply)

    (ws.path / "short_final.mp4").write_bytes(b"\0" * 64)
    assert "rendered, not uploaded" in core.inbox_reply().text


def test_a_scheduled_upload_lands_on_its_day_and_gaps_are_marked(core):
    from pipeline.youtube import VideoLog, VideoRecord

    when = (datetime.now(timezone.utc) + timedelta(days=2)).replace(
        hour=15, minute=0, second=0, microsecond=0)
    VideoLog(core.settings).record(VideoRecord(
        ticker="EXMPL", video_id="v1", title="t", privacy="scheduled",
        publish_at=when.isoformat(), uploaded_at=when.isoformat(),
        workdate="2026-10-01", fmt="short"))
    text = core.calendar_text([]).text
    assert "EXMPL SHORT" in text
    assert text.count("— gap") == 6


# --------------------------------------------------------------------------
# The buttons.
# --------------------------------------------------------------------------


def test_every_new_button_fits_telegrams_64_bytes():
    t, d = "ABCDEFGHIJKLMNO", "2026-10-05"   # the longest ticker allowed
    markups = [
        kb.approval_keyboard("long", t, d, "f" * 64, True, True),
        kb.angle_keyboard(t, d), kb.approved_keyboard("long", t, d, 1.94),
        kb.confirm_render_keyboard("long", t, d), kb.queued_keyboard(t, d),
        kb.delivered_keyboard("long", t, d), kb.uploaded_keyboard(t),
        kb.undo_cancel_keyboard(),
    ]
    for markup in markups:
        for data in _buttons(markup):
            assert len(data.encode("utf-8")) <= kb.CALLBACK_DATA_MAX, data


def test_approve_offers_the_free_looks_and_the_priced_render(
        core, xlsx_bytes, short_valid_json):
    core.start_lane(CHAT, "short", "EXMPL")
    core.handle_upload(CHAT, "dennis_data.xlsx", xlsx_bytes)
    core.intake_script(CHAT, short_valid_json)
    ws = core.context.get(CHAT)
    reply = core.approve("short", "EXMPL", ws.workdate,
                         ws.load_short().content_sha()[:8])
    data = _buttons(reply)
    assert f"q|p|EXMPL|{ws.workdate}|s" in data
    assert f"r|s|EXMPL|{ws.workdate}" in data


def test_the_render_button_asks_before_it_spends(core, xlsx_bytes,
                                                 short_valid_json):
    ws = _approved_short(core, xlsx_bytes, short_valid_json)
    reply = run(cmds.handle_callback(core, CHAT, f"r|s|EXMPL|{ws.workdate}"))
    assert reply.text.startswith("💰 Render EXMPL SHORT")
    assert "Month so far" in reply.text
    assert f"r!|s|EXMPL|{ws.workdate}" in _buttons(reply)
    assert core.queue is None or not core.queue.store.all(), "nothing queued yet"


def test_the_render_button_refuses_an_unapproved_script(core):
    core.start_lane(CHAT, "short", "EXMPL")
    ws = core.context.get(CHAT)
    reply = run(cmds.handle_callback(core, CHAT, f"r|s|EXMPL|{ws.workdate}"))
    assert reply.text.startswith("⛔") and not _buttons(reply)


def test_the_confirmed_render_queues_it(core, xlsx_bytes, short_valid_json):
    from pipeline.jobs import RenderJobQueue

    ws = _approved_short(core, xlsx_bytes, short_valid_json)
    core.queue = RenderJobQueue(core.settings, lambda job: "")
    reply = run(cmds.handle_callback(core, CHAT, f"r!|s|EXMPL|{ws.workdate}"))
    assert "queued SHORT render" in reply.text
    (job,) = core.queue.store.all()
    assert job.kind is JobKind.RENDER_SHORT and job.workdate == ws.workdate


def test_an_angle_button_is_the_same_as_typing_its_number(core, monkeypatch):
    core.start_lane(CHAT, "long", "EXMPL")
    ws = core.context.get(CHAT)
    seen = []
    monkeypatch.setattr(core, "_intake_angle",
                        lambda w, text: seen.append(text) or Reply("ok"))
    run(cmds.handle_callback(core, CHAT, f"g|EXMPL|{ws.workdate}|2"))
    assert seen == ["2"]


def test_a_cancel_can_be_undone_within_the_minute(core, xlsx_bytes,
                                                  short_valid_json):
    ws = _approved_short(core, xlsx_bytes, short_valid_json)
    reply = run(cmds.handle_callback(core, CHAT, f"j|EXMPL|{ws.workdate}"))
    assert "approvals withdrawn" in reply.text and "z" in _buttons(reply)
    assert not ws.is_approved("short")

    reply = run(cmds.handle_callback(core, CHAT, "z"))
    assert "1 approval(s) restored" in reply.text
    assert ws.is_approved("short")
    assert "Nothing to undo" in run(cmds.handle_callback(core, CHAT, "z")).text


def test_an_undo_does_not_approve_a_script_edited_since(
        core, xlsx_bytes, short_valid_json):
    ws = _approved_short(core, xlsx_bytes, short_valid_json)
    core.cancel_jobs(f"EXMPL@{ws.workdate}")
    core.intake_script(CHAT, short_valid_json.replace("29%", "31%"))
    run(cmds.handle_callback(core, CHAT, "z"))
    assert not ws.is_approved("short"), "the approval pins the old hash"


def test_schedule_asks_for_a_time_and_the_next_message_answers(core,
                                                               monkeypatch):
    core.start_lane(CHAT, "short", "EXMPL")
    ws = core.context.get(CHAT)
    reply = run(cmds.handle_callback(core, CHAT, f"us|s|EXMPL|{ws.workdate}"))
    assert "When should EXMPL SHORT go public" in reply.text
    got = []
    monkeypatch.setattr(core, "upload_command",
                        lambda args: got.append(args) or Reply("📺 ok"))
    run(cmds.handle_text(core, CHAT, "2026-10-20 17:00"))
    assert got == [[f"EXMPL@{ws.workdate}", "short", "2026-10-20", "17:00"]]
    assert not cmds.ChatState(core.settings).pending(CHAT), "answered once"


def test_a_script_paste_is_never_eaten_by_a_pending_question(
        core, monkeypatch, short_valid_json):
    core.start_lane(CHAT, "short", "EXMPL")
    cmds.ChatState(core.settings).ask(CHAT, "correct", ticker="EXMPL")
    monkeypatch.setattr(core, "correct_command",
                        lambda args: pytest.fail("a script went to /correct"))
    monkeypatch.setattr(core, "intake_script", lambda chat, text: Reply("intake"))
    assert run(cmds.handle_text(core, CHAT, short_valid_json)).text == "intake"


# --------------------------------------------------------------------------
# The /go wizard.
# --------------------------------------------------------------------------


def test_the_wizard_walks_a_short_one_step_at_a_time(core, xlsx_bytes,
                                                     short_valid_json):
    reply = cmd(core, "/go EXMPL")
    assert "Step 1/5" in reply.text
    state = cmds.ChatState(core.settings)
    assert state.wizard(CHAT)["step"] == "workbook"

    reply = run(cmds.handle_upload(core, CHAT, "dennis_data.xlsx", xlsx_bytes))
    assert "Step 2/5" in reply.text
    assert state.wizard(CHAT)["step"] == "paste"

    reply = run(cmds.handle_text(core, CHAT, short_valid_json))
    assert "Step 3/5" in reply.text
    ws = core.context.get(CHAT)
    sha = ws.load_short().content_sha()[:8]
    reply = run(cmds.handle_callback(
        core, CHAT, f"a|short|EXMPL|{ws.workdate}|{sha}"))
    assert "Step 4/5" in reply.text
    assert state.wizard(CHAT)["step"] == "render"


def test_the_wizard_offers_the_upload_when_the_render_lands(core):
    core.start_lane(CHAT, "short", "EXMPL")
    ws = core.context.get(CHAT)
    cmds.ChatState(core.settings).set_wizard(CHAT, "EXMPL", ws.workdate,
                                             "rendering")
    sent = []

    async def send(chat_id, reply):
        sent.append((chat_id, reply))

    board = cmds.CardBoard(core, send=send)
    from pipeline.models import JobRecord
    job = JobRecord(id="j1", kind=JobKind.RENDER_SHORT, ticker="EXMPL",
                    workdate=ws.workdate, status=JobStatus.DONE)
    run(board.finished(job))
    (chat_id, reply), = sent
    assert chat_id == CHAT and "Step 5/5" in reply.text
    assert f"u|s|EXMPL|{ws.workdate}" in _buttons(reply)


# --------------------------------------------------------------------------
# Live cards, the job listener, quiet notifications.
# --------------------------------------------------------------------------


def test_a_saved_job_reaches_its_listeners(settings):
    from pipeline.jobs import JobStore
    from pipeline.models import JobRecord

    store = JobStore(settings)
    seen = []
    store.listeners.append(lambda job: seen.append(job.status))
    store.listeners.append(lambda job: 1 / 0)       # a broken one is logged
    store.save(JobRecord(id="x", kind=JobKind.RENDER_SHORT, ticker="EXMPL",
                         workdate="2026-10-05"))
    assert seen == [JobStatus.QUEUED]


def test_a_card_is_edited_when_its_job_moves(core):
    core.start_lane(CHAT, "short", "EXMPL")
    ws = core.context.get(CHAT)
    edits = []

    async def edit(chat_id, message_id, reply):
        edits.append((chat_id, message_id, reply.text))

    board = cmds.CardBoard(core, edit=edit)
    board.remember(f"EXMPL@{ws.workdate}", CHAT, 77)
    assert board.cards(f"EXMPL@{ws.workdate}") == [(CHAT, 77)]
    assert run(board.refresh(f"EXMPL@{ws.workdate}")) == 1
    assert edits[0][:2] == (CHAT, 77) and edits[0][2].startswith("📁 EXMPL")


def test_quiet_keeps_only_finished_failed_and_needs_you(settings):
    prefs = cmds.NotifyPrefs(settings)
    assert prefs.wants("🎬 EXMPL: render_short started")
    prefs.set("quiet")
    assert not prefs.wants("🎬 EXMPL: render_short started")
    assert prefs.wants("✅ EXMPL: render_short done")
    assert prefs.wants("❌ EXMPL render_short failed:")


def test_quiet_toggles_from_the_command(core):
    assert "only finished" in cmd(core, "/admin quiet").text
    assert cmds.NotifyPrefs(core.settings).level() == "quiet"
    assert "everything" in cmd(core, "/admin quiet off").text


# --------------------------------------------------------------------------
# The web panel.
# --------------------------------------------------------------------------


@pytest.fixture()
def panel(core):
    from bot.panel import start_panel

    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    server, url = start_panel(core, loop, host="127.0.0.1", port=0)
    base = url.split("/#")[0]
    key = url.split("#k=")[1]
    # No proxy for loopback; `fetch` rather than `.open`, which the encoding
    # guard in test_platform reads as text I/O.
    fetch = urllib.request.build_opener(urllib.request.ProxyHandler({})).open

    def call(path, body=None, key_=key, raw=None, headers=None):
        data = raw if raw is not None else (
            json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(base + path, data=data,
                                     headers=dict(headers or {}))
        if key_:
            req.add_header("X-Panel-Key", key_)
        if body is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with fetch(req, timeout=60) as resp:
                return resp.status, resp.headers, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers, e.read()

    yield call
    server.shutdown()
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=5)


def test_the_panel_page_loads_and_the_api_needs_the_key(panel):
    status, _h, body = panel("/", key_="")
    assert status == 200 and b"Dennis Panel" in body
    assert panel("/static/app.js", key_="")[0] == 200
    assert panel("/api/state", key_="")[0] == 401
    assert panel("/api/state", key_="wrong")[0] == 401
    status, _h, body = panel("/api/state")
    assert status == 200 and "inbox" in json.loads(body)


def test_the_panel_runs_commands_through_the_registry(panel, core):
    status, _h, body = panel("/api/run", {"text": "/new short EXMPL"})
    reply = json.loads(body)["reply"]
    assert status == 200 and reply["text"].startswith("📁 EXMPL")
    assert reply["files"][0]["name"] == "dennis_data_template.xlsx"
    assert core.context.get(core.settings.operator_chat_ids[0]).ticker == "EXMPL"

    status, _h, body = panel("/api/state")
    videos = json.loads(body)["videos"]
    assert videos[0]["ticker"] == "EXMPL" and videos[0]["buttons"]

    reg = json.loads(panel("/api/registry")[2])
    names = {c["name"] for c in reg["commands"]}
    assert {"render proof", "publish calendar", "jobs undo"} <= names
    assert reg["active"]["ticker"] == "EXMPL"


def test_the_panel_takes_an_upload_and_a_button(panel, xlsx_bytes):
    panel("/api/run", {"text": "/new short EXMPL"})
    status, _h, body = panel("/api/upload?name=dennis_data.xlsx",
                             raw=xlsx_bytes)
    assert status == 200
    assert json.loads(body)["reply"]["text"].startswith("💾 saved")
    status, _h, body = panel("/api/callback", {"data": "ib"})
    assert status == 200 and "reply" in json.loads(body)


def test_the_panel_serves_workspace_files_but_never_state(panel, core):
    panel("/api/run", {"text": "/new short EXMPL"})
    ws = core.context.get(core.settings.operator_chat_ids[0])
    clip = ws.path / "short_proof.mp4"
    clip.write_bytes(bytes(range(256)) * 4)
    from urllib.parse import quote

    status, headers, body = panel(f"/api/file?path={quote(str(clip))}",
                                  headers={"Range": "bytes=10-19"})
    assert status == 206 and body == bytes(range(10, 20))
    assert headers["Content-Range"] == f"bytes 10-19/{1024}"

    token = core.settings.state_dir / "panel_token"
    assert token.exists()
    assert panel(f"/api/file?path={quote(str(token))}")[0] == 404
    sneaky = ws.path / ".." / ".." / ".." / "state" / "panel_token"
    assert panel(f"/api/file?path={quote(str(sneaky))}")[0] == 404


def test_the_panel_feed_carries_what_the_bot_said(panel, core):
    core.feed.add("notice", "✅ EXMPL: render_short done")
    events = json.loads(panel("/api/feed?since=0")[2])["events"]
    assert any("render_short done" in e["text"] for e in events)


def test_the_telegram_glue_registers_every_name_from_the_registry(core):
    pytest.importorskip("telegram")
    from telegram.ext import CommandHandler, MessageHandler

    from bot.handlers import build_application

    live = core.settings.model_copy(update={
        "telegram_bot_token": "123456:TEST-not-a-real-token"})
    core.settings = live
    app = build_application(live, core)
    handlers = [h for group in app.handlers.values() for h in group]
    registered = {c for h in handlers if isinstance(h, CommandHandler)
                  for c in h.commands}
    assert registered == set(cmds.telegram_names())
    # "did you mean…" is the last word on any command nothing else took
    assert isinstance(handlers[-1], MessageHandler)
    assert isinstance(core.cards, cmds.CardBoard) and core.send_to is not None
