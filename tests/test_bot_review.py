"""Bot fixes from the second full review of the bot code (31 Oct 2026).

One regression test per finding, named for what it guards. Each of these
failed on the commit before the fix.
"""

from __future__ import annotations

import asyncio
import threading
from datetime import datetime, timezone
from types import SimpleNamespace as NS

import pytest

from bot.handlers import BotCore, Reply, is_queue_control

CHAT = 3131


@pytest.fixture()
def core(settings):
    return BotCore(settings.model_copy(update={"operator_chat_ids": [CHAT]}))


# --------------------------------------------------------------------------
# The Telegram glue
# --------------------------------------------------------------------------

def _updates():
    """A fresh message and the same message edited, for a command and for
    plain text."""
    from telegram import Chat, Message, MessageEntity, Update, User

    chat, who = Chat(CHAT, "private"), User(CHAT, "op", False)
    now = datetime.now(timezone.utc)

    def msg(text):
        ents = ([MessageEntity("bot_command", 0, len(text.split()[0]))]
                if text.startswith("/") else None)
        return Message(1, now, chat, from_user=who, text=text, entities=ents)

    return {
        "command": Update(1, message=msg("/render XYZ")),
        "edited_command": Update(2, edited_message=msg("/render XYZ")),
        "text": Update(3, message=msg("2")),
        "edited_text": Update(4, edited_message=msg("2")),
    }


def test_an_edited_message_runs_nothing_again(settings):
    """python-telegram-bot hands EDITED messages to every handler by default,
    so fixing a typo in an old `/render XYZ` queued the paid render again,
    and editing an old paste re-ran the intake or answered a question the
    bot had just asked. Only a new message is an instruction."""
    from bot.handlers import build_application

    live = settings.model_copy(update={"telegram_bot_token": "123:ABC",
                                       "operator_chat_ids": [CHAT]})
    app = build_application(live, BotCore(live))
    u = _updates()
    gated = [h for h in app.handlers[0] if getattr(h, "filters", None) is not None]
    assert gated, "the command and message handlers carry filters"
    for h in gated:
        assert not h.filters.check_update(u["edited_command"]), h
        assert not h.filters.check_update(u["edited_text"]), h
    # A new message still gets through: the commands, and a plain reply.
    assert any(h.filters.check_update(u["command"]) for h in gated
               if type(h).__name__ == "CommandHandler")
    assert any(h.check_update(u["text"]) for h in gated
               if type(h).__name__ == "MessageHandler")


@pytest.mark.parametrize("data", ["j|XYZ|2026-10-31", "jx|0123456789"])
def test_a_render_cancel_button_skips_the_line(data):
    """The Cancel 🚫 under a queued or running render (and a queue row's own
    Cancel) is what stops a runaway render; it waited behind a slow upload
    like any other update while the report's Cancel ❌ (`x|`) did not."""
    assert is_queue_control(NS(message=None, callback_query=NS(data=data)))


def test_a_picture_outside_the_photo_limits_goes_as_a_file(tmp_path):
    """A LONG's contact sheet is three thumbnails a row, so a script with a
    hundred and fifty visuals made a sheet over 10,000 pixels tall. Telegram
    refuses such a photo, and the reply died after its text had gone."""
    from PIL import Image

    from bot.handlers import _ship

    tall, small = tmp_path / "sheet.png", tmp_path / "small.png"
    Image.new("RGB", (960, 10_500), (18, 18, 22)).save(tall)
    Image.new("RGB", (960, 540), (18, 18, 22)).save(small)
    sent: list[tuple] = []

    async def text_fn(text, reply_markup=None):
        sent.append(("text",))
        return NS(message_id=1)

    async def photo_fn(fh):
        sent.append(("photo", fh.name))

    async def doc_fn(fh, filename=None):
        sent.append(("document", filename))

    asyncio.run(_ship(Reply("report", photo=tall), text_fn, photo_fn, doc_fn))
    assert ("document", "sheet.png") in sent
    assert not any(s[0] == "photo" for s in sent)
    sent.clear()
    asyncio.run(_ship(Reply("report", photo=small), text_fn, photo_fn, doc_fn))
    assert [s[0] for s in sent] == ["text", "photo"]


class _FlakyBot:
    """A bot that cannot reach the first chat (blocked, left the group)."""

    def __init__(self, bad: int):
        self.bad, self.got = bad, []

    async def send_message(self, chat_id, text, **kw):
        if chat_id == self.bad:
            raise RuntimeError("Forbidden: bot was blocked by the user")
        self.got.append(chat_id)


class _App:
    def __init__(self):
        self.jobs = {}
        self.job_queue = self

    def run_repeating(self, callback, **kw):
        self.jobs[kw["name"]] = callback


def test_the_overnight_batch_reaches_every_chat_when_one_fails(core,
                                                               monkeypatch):
    """Every other push tries each operator chat in turn; the batch's report
    stopped at the first one that failed, and the pass was marked reported."""
    from bot.handlers import schedule_batch
    from pipeline import standing

    two = core.settings.model_copy(update={"operator_chat_ids": [1, 2]})
    core.settings = two
    monkeypatch.setattr(standing, "in_batch_window", lambda s: True)
    monkeypatch.setattr(standing.BatchQueue, "pending", lambda self: [NS()])

    async def run_batch():
        return 1, [], "🌙 batch: 1 queued, 0 skipped"

    monkeypatch.setattr(core, "run_batch", run_batch)
    app = _App()
    schedule_batch(app, core)
    bot = _FlakyBot(bad=1)
    asyncio.run(app.jobs["overnight_batch"](NS(bot=bot)))
    assert bot.got == [2]


def test_the_weekly_note_reaches_every_chat_when_one_fails(core, monkeypatch):
    from bot.handlers import schedule_retention_notes
    from pipeline import retention_notes

    core.settings = core.settings.model_copy(update={
        "operator_chat_ids": [1, 2], "retention_notes_enabled": True})
    monkeypatch.setattr(retention_notes, "notes_due", lambda s: True)
    monkeypatch.setattr(retention_notes, "refresh_notes", lambda s: "short: 3")
    monkeypatch.setattr(retention_notes, "load_notes",
                        lambda s: {"short": {"status": "ok"}})
    app = _App()
    schedule_retention_notes(app, core)
    bot = _FlakyBot(bad=1)
    asyncio.run(app.jobs["retention_notes"](NS(bot=bot)))
    assert bot.got == [2]


def test_the_batch_is_planned_off_the_event_loop(core, monkeypatch):
    """Planning reads every entry's workspace, script and approval; on the
    loop it held up every Telegram update and every page action meanwhile
    (the rule every other command follows, M9)."""
    from pipeline.jobs import RenderJobQueue

    core.queue = RenderJobQueue(core.settings, lambda job: "")
    seen: dict[str, int] = {}

    def plan():
        seen["plan"] = threading.get_ident()
        return [], [], ""

    monkeypatch.setattr(core, "batch_plan", plan)

    async def run():
        seen["loop"] = threading.get_ident()
        return await core.run_batch()

    asyncio.run(run())
    assert seen["plan"] != seen["loop"]


# --------------------------------------------------------------------------
# stockanalysis.com, as the bot reads it
# --------------------------------------------------------------------------

def _movers(change):
    return [{"symbol": "AAA", "name": "A", "change": change, "price": 50.0,
             "market_cap": 5e10},
            {"symbol": "BBB", "name": "B", "change": 0.12, "price": 50.0,
             "market_cap": 5e10}]


def test_a_mover_with_no_change_is_left_off_the_lists(core, monkeypatch):
    """A row whose % change read as "-" kept its None: /movers (and Home's
    Read again) raised TypeError on it, and the page showed it as +0.0%."""
    from pipeline import stockanalysis as sa

    assert [r["symbol"] for r in sa.tradeable(_movers(None), core.settings, 5)] \
        == ["BBB"]
    snap = {"status": "ok", "lists": {"gainers": _movers(None)}, "calendar": {}}
    monkeypatch.setattr(sa, "market_today", lambda s, refresh=False: snap)
    text = core.movers_text([]).text
    assert "BBB +12.0%" in text and "AAA" not in text


def test_the_earnings_calendar_is_read_again_on_a_new_day(settings,
                                                          monkeypatch):
    """Kept under "today" for six hours, the calendar read at 22:00 was
    still the day's reporters at 02:00 the next morning."""
    from pipeline import stockanalysis as sa

    asked: list[str] = []
    real = sa.page

    def page(path, s):
        asked.append(path)
        return real(path, s)

    monkeypatch.setattr(sa, "page", page)
    monkeypatch.setattr(sa, "_market_day", lambda: "2026-10-30", raising=False)
    sa.earnings_calendar(settings)
    sa.earnings_calendar(settings)              # the same day: the kept copy
    monkeypatch.setattr(sa, "_market_day", lambda: "2026-10-31", raising=False)
    sa.earnings_calendar(settings)              # the next day: read again
    assert asked.count("/stocks/earnings-calendar/") == 2
    sa.market_today(settings, refresh=True)     # `refresh` still reads it again
    assert asked.count("/stocks/earnings-calendar/") == 3


def _live(settings, monkeypatch):
    from pipeline import request_count
    from pipeline import stockanalysis as sa

    monkeypatch.setattr(settings, "mock_mode", False)
    monkeypatch.setattr(settings, "stockanalysis_gap_s", 0.0)
    monkeypatch.setattr(request_count, "count", lambda s, svc: None)
    monkeypatch.setattr(sa, "_down_until", 0.0, raising=False)
    return sa


def test_a_site_that_is_down_is_not_asked_again_for_every_page(settings,
                                                               monkeypatch):
    """Nothing that failed was kept, so with the site down every part of a
    gather — robots, the terms, then the page, ten parts — waited out its
    own twenty-second timeout, on every workbook upload and /prompts."""
    import httpx

    sa = _live(settings, monkeypatch)
    tries: list[str] = []

    def down(url, **kw):
        tries.append(url)
        raise httpx.ConnectTimeout("timed out")

    monkeypatch.setattr(httpx, "get", down)
    for _ in range(5):
        assert sa._raw_get("/stocks/ba/", settings) is None
    assert len(tries) == 1
    ok, why = sa.allowed("/stocks/ba/", settings)
    assert not ok and "did not answer" in why
    monkeypatch.setattr(sa, "_down_until", 0.0)  # the pause is over
    sa._raw_get("/stocks/ba/", settings)
    assert len(tries) == 2


@pytest.mark.parametrize("status, pauses", [(404, False), (503, True),
                                            (429, True)])
def test_only_a_site_wide_refusal_pauses_the_source(settings, monkeypatch,
                                                    status, pauses):
    """One page missing (a ticker the site does not carry) is not the site
    being down; a 503 or a 429 is, and asking again at once makes it worse."""
    import httpx

    sa = _live(settings, monkeypatch)
    tries: list[str] = []

    class _R:
        status_code = status
        text = ""

    monkeypatch.setattr(httpx, "get", lambda url, **kw: tries.append(url) or _R())
    sa._raw_get("/stocks/zzzz/", settings)
    sa._raw_get("/stocks/zzzz/", settings)
    assert len(tries) == (1 if pauses else 2)


def test_a_lane_less_folder_reads_the_long_pack_for_its_angle_prompt(
        core, monkeypatch, fixtures_dir):
    """An old folder with no lane gets both prompts; the site was read as a
    SHORT's, so the angle prompt never had the year-ago call."""
    import shutil

    from pipeline.workspace import Workspace, today_str

    ws = Workspace(core.settings, "EXMPL", today_str()).create()
    shutil.copy(fixtures_dir / "company_data" / "dennis_data.xlsx",
                ws.path / "dennis_data.xlsx")
    core.context.set(CHAT, "EXMPL", ws.workdate)
    lanes: list[str] = []
    monkeypatch.setattr(core, "_site_pack",
                        lambda w, lane, **kw: lanes.append(lane))
    reply = core.prompts_reply(CHAT)
    assert {f.name for f in reply.files} == {"prompt_short.md",
                                             "prompt_long_angle.md"}
    assert lanes == ["long"]


def test_an_angle_pick_reads_the_workbook_once(core, monkeypatch, fixtures_dir):
    """With the site already on file, the pick parsed the workbook three
    times: for the pick, for the prompt, and again for a pack it already
    had."""
    from pipeline import site_pack

    xlsx = (fixtures_dir / "company_data" / "dennis_data.xlsx").read_bytes()
    core.start_lane(CHAT, "long", "EXMPL")
    core.handle_upload(CHAT, "dennis_data.xlsx", xlsx)
    ws = core.context.get(CHAT)
    assert site_pack.load(ws.path) is not None
    loads: list[int] = []
    real = BotCore._company_data

    def counted(self, w):
        loads.append(1)
        return real(self, w)

    monkeypatch.setattr(BotCore, "_company_data", counted)
    reply = core.angle_pick(CHAT, "EXMPL", ws.workdate, "2")
    assert reply.text.startswith("✅ Angle locked")
    assert len(loads) == 1


def test_the_short_prompt_lists_a_headline_once(settings):
    """The site's coverage joins the workbook's News on load, so each of its
    stories came back as a dated headline AND as a line of the coverage by
    the minute: the same story read as two sources."""
    import datetime as dt
    import re
    import shutil
    from pathlib import Path

    from bot.prompts import _Ctx, why_it_moved_block
    from pipeline import site_pack
    from pipeline.move_kind import classify

    day = dt.date(2026, 10, 28)
    ws = settings.workspace_dir / "BA" / day.isoformat()
    ws.mkdir(parents=True)
    fixtures = Path(__file__).resolve().parent.parent / "fixtures"
    shutil.copy(fixtures / "company_data" / "dennis_data.xlsx",
                ws / "dennis_data.xlsx")
    site_pack.gather(ws, "BA", settings, lane="short", today=day)
    own = {"date": day.isoformat(), "headline": "A story only the workbook had",
           "source": "Reuters"}
    kind = classify("BA", day, news=site_pack.news_rows(ws) + [own])
    block = why_it_moved_block(_Ctx(fmt="short", ticker="BA", data=None,
                                    workspace=ws, settings=settings,
                                    move_kind=kind))
    coverage = [n["title"] for n in site_pack.load(ws)["news"]
                if n.get("kind") in ("article", "release")
                and n["date"] >= (day - dt.timedelta(days=1)).isoformat()]
    assert coverage, "the fixture has coverage around the print"
    # Listed once. (The day's own line may still quote the headline that
    # made it an earnings day: that is the reason, not a second source.)
    listed = "\n".join(ln for ln in block.splitlines() if ln.startswith("  "))
    for title in coverage[:14]:
        assert len(re.findall(re.escape(title), listed)) == 1, title
    assert "A story only the workbook had" in listed


def test_when_the_site_was_read_carries_its_clock(monkeypatch):
    """/site printed the UTC stamp as it is stored, with no zone, beside
    coverage kept in New York time."""
    import time

    from bot.handlers import _local_stamp

    monkeypatch.setenv("TZ", "America/New_York")
    time.tzset()
    try:
        assert _local_stamp("2026-10-31T14:05:00+00:00") == "2026-10-31 10:05 EDT"
        assert _local_stamp("") == ""
        assert _local_stamp("not a time") == "not a time"
    finally:
        monkeypatch.undo()
        time.tzset()


# --------------------------------------------------------------------------
# State the page and the chat share
# --------------------------------------------------------------------------

def _slow_loads(monkeypatch, cls):
    """The file is read, then the other thread reads it before this one has
    written: the race the lock is for, made certain."""
    import time

    real = cls._load

    def slow(self):
        data = real(self)
        time.sleep(0.05)
        return data

    monkeypatch.setattr(cls, "_load", slow)


def test_two_chats_asking_at_once_keep_both_questions(settings, monkeypatch):
    """The page and Telegram each run in a thread of their own; both read
    `chat_state.json`, and the second save threw the first one's away."""
    from bot.commands import ChatState

    _slow_loads(monkeypatch, ChatState)
    cs = ChatState(settings)
    threads = [threading.Thread(target=cs.ask, args=(chat, "schedule"),
                                kwargs={"ticker": "XYZ"}) for chat in (1, 2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert cs.pending(1) and cs.pending(2)


def test_two_chats_switching_video_at_once_keep_both(settings, monkeypatch):
    from pipeline.workspace import ActiveContext

    _slow_loads(monkeypatch, ActiveContext)
    for t in ("AAA", "BBB"):
        (settings.workspace_dir / t / "2026-10-31").mkdir(parents=True)
    ctx = ActiveContext(settings)
    threads = [threading.Thread(target=ctx.set, args=(chat, t, "2026-10-31"))
               for chat, t in ((1, "AAA"), (2, "BBB"))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert ctx.get(1).ticker == "AAA" and ctx.get(2).ticker == "BBB"


# --------------------------------------------------------------------------
# The page
# --------------------------------------------------------------------------

def _video(core, st, fmt="short"):
    from bot.panel_views import _Video
    from pipeline.workspace import Workspace

    ws = Workspace(core.settings, "XYZ", "2026-10-31")
    return _Video(NS(core=core, settings=core.settings, allowed=lambda p: False),
                  ws, st, fmt)


@pytest.mark.parametrize("cached, priced", [(True, False), (False, True)])
def test_the_page_prices_a_render_only_when_the_voice_costs(core, cached,
                                                             priced):
    """The card, the report and the chat drop the price once the voice is in
    the cache; the page's Approve and Render steps still printed ~$1.23 on
    a render that would cost nothing."""
    from bot.panel_views import _step_approve, _step_render

    st = NS(approved=True, renders={}, est_usd=1.23, tts_cached=cached,
            report_ok=True, blockers=[], sha8="abcd1234", active_job=None,
            jobs=[])
    v = _video(core, st)
    texts = ([b["text"] for row in _step_approve(v)["buttons"] for b in row]
             + [b["text"] for row in _step_render(v)["render"] for b in row])
    assert sum("💰" in t for t in texts) == 2
    assert all(("~$1.23" in t) is priced for t in texts if "💰" in t)


@pytest.fixture()
def served(core):
    """The panel on a free port, as `tests/test_workflow.py` serves it."""
    import json
    import urllib.request

    from bot.panel import start_panel

    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    server, url = start_panel(core, loop, host="127.0.0.1", port=0)
    base, key = url.split("/#")[0], url.split("#k=")[1]
    fetch = urllib.request.build_opener(urllib.request.ProxyHandler({})).open

    def get(path):
        req = urllib.request.Request(base + path, headers={"X-Panel-Key": key})
        with fetch(req, timeout=30) as resp:
            return json.loads(resp.read())

    yield get
    core.chats.close()
    server.shutdown()
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=5)


def test_the_feed_says_which_run_of_the_bot_it_is(core, served):
    """The page asks for the events after the last number it saw. A
    restarted bot counts from one again, so the page asked for events after
    250, got none, and jumped to the new count: every push the new run made
    before that never reached Activity. The epoch tells it to start over."""
    from bot.feed import Feed

    a, b = Feed(), Feed()
    assert a.epoch and a.epoch != b.epoch
    core.feed.add("notice", "✅ XYZ: render_short done")
    got = served("/api/feed?since=0")
    assert got["epoch"] == core.feed.epoch and got["seq"] == 1


def test_the_page_scripts_declare_each_global_once():
    """The page's scripts share one global scope, in load order. chat.js,
    loaded last, declared its own `copyText` and replaced video.js's: every
    copy button in a video's workspace lost its label ("Copy the prompt"
    came back as "Copy"), and the copy that works without the clipboard API
    with it."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "bot" / "panel_static"
    decl = re.compile(r"^(?:async\s+)?(?:function\*?|const|let|var|class)\s+"
                      r"([A-Za-z_$][\w$]*)", re.M)
    seen: dict[str, str] = {}
    twice = []
    for f in [root / "app.js", *sorted((root / "screens").glob("*.js"))]:
        for name in decl.findall(f.read_text(encoding="utf-8")):
            if name in seen:
                twice.append(f"{name}: {seen[name]} and {f.name}")
            seen[name] = f.name
    assert seen and not twice


# --------------------------------------------------------------------------
# The page's chat
# --------------------------------------------------------------------------

def test_a_question_asked_while_one_is_answered_knows_its_place(settings,
                                                                monkeypatch):
    """The page shows a waiting question's place in line, read off the order
    only the worker rebuilt, between answers: one asked while the local
    model answered another (a minute, often) had no place until that answer
    was done. CI caught it as `KeyError: 'ahead'` (31 Oct 2026)."""
    import time as _time

    from pipeline import recall

    asked = threading.Event()
    gate = threading.Event()

    def slow(settings, question, **kw):
        asked.set()
        gate.wait(5)
        return recall.Answer(question.upper(), body=question.upper(),
                             reason="ok")

    monkeypatch.setattr(recall, "ask", slow)
    chats = BotCore(settings).chats
    chats.start()
    try:
        chats.say(None, "first")
        assert asked.wait(5), "the worker took the first question"
        b = chats.say(None, "second")
        waiting = b["messages"][1]
        assert waiting["status"] == "queued"
        assert waiting.get("ahead") == 1
    finally:
        gate.set()
        chats.close()
        _time.sleep(0.1)


def test_the_inbox_retention_button_opens_the_video_on_the_line(settings):
    """The inbox lists each video whose retention is ready; its button sent
    the ticker alone, which `/stats retention` reads as the ticker's newest
    upload — a clip or a short gone up since, often too new to have any. The
    upload card's buttons carry the video since 24 Oct; this one did not."""
    from datetime import datetime, timedelta, timezone

    from bot.keyboards import inbox_keyboard
    from pipeline.video_state import inbox
    from pipeline.youtube import VideoLog, VideoRecord

    now = datetime.now(timezone.utc)
    log_ = VideoLog(settings)
    log_.record(VideoRecord(ticker="EXMPL", video_id="longvid0001",
                            title="the long", privacy="public", fmt="long",
                            uploaded_at=(now - timedelta(days=5)).isoformat(),
                            workdate="2026-10-20"))
    log_.record(VideoRecord(ticker="EXMPL", video_id="shortvid001",
                            title="the short", privacy="public", fmt="short",
                            uploaded_at=(now - timedelta(hours=20)).isoformat(),
                            workdate="2026-10-30"))
    items = [i for i in inbox(settings, now=now) if i.section == "retention"]
    assert [i.text.split(" (")[0] for i in items] == ["the long"]
    button = inbox_keyboard(items).inline_keyboard[0][0]
    assert button.callback_data == "rt|EXMPL|longvid0001"
