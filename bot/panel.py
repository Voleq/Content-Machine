"""The web control panel: the bot, in a browser.

Served by the bot process itself, on the standard library's HTTP server, so
there is nothing to install and nothing to deploy. Every action goes through
the SAME code the Telegram chat uses — `bot.commands.run_command`,
`handle_callback`, `handle_text`, `handle_upload` — so the panel cannot do
anything the chat cannot, and cannot do it differently.

What it adds over the chat:

- every command, grouped by family, as a form (`/api/registry`);
- the inbox, every recent video as a card with its next step on a button,
  the queue and the month's spend, on one screen (`/api/state`);
- the activity feed — every push the bot made (`/api/feed`);
- a chat with the local AI, every conversation kept (`/api/chats`,
  `/api/chat`; `bot.chat`);
- files of any size (the cloud Bot API stops at 20 MB), and renders played
  in the page rather than downloaded (`/api/file`, with Range support).

SECURITY. It binds to 127.0.0.1 by default and every API call needs the
panel key (`PANEL_TOKEN`, or one generated into `state/panel_token`), sent
as the `X-Panel-Key` header — or `?k=` on a file link, which an `<img>` or
`<video>` cannot set a header for. Files are served only from the workspace,
the templates and the custom-asset folder: never `state/`, which holds the
YouTube credentials and this key. Reach it from another machine through an
SSH tunnel or a private network; do not open the port.

Standalone, without Telegram (the queue runs, pushes go to the feed only):

    python -m bot.panel
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import mimetypes
import secrets
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from bot import commands as cmds
from bot.feed import Feed, keyboard_rows
from bot.handlers import BotCore, Reply

log = logging.getLogger(__name__)

STATIC = Path(__file__).resolve().parent / "panel_static"
# A paste or an angle pick can take minutes (the plan fetches clips, the
# gates call the model). The request waits this long for the answer and
# then hands the page the action's id to look again by: a request held for
# minutes held one of the six connections a browser opens to one address,
# and a few of them froze every other click on the page (his "it gets
# stuck", 30 Oct 2026).
QUICK_S = 3.0


def panel_token(settings) -> str:
    """PANEL_TOKEN, or the one generated the first time and kept."""
    if settings.panel_token:
        return settings.panel_token
    path = Path(settings.state_dir) / "panel_token"
    try:
        token = path.read_text(encoding="utf-8").strip()
        if token:
            return token
    except OSError:
        pass
    token = secrets.token_urlsafe(24)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return token


def panel_chat_id(settings) -> int:
    if settings.panel_chat_id:
        return int(settings.panel_chat_id)
    ids = settings.operator_chat_ids
    return int(ids[0]) if ids else 0


class NoSuchVideo(LookupError):
    """A page action named a video that is not a folder of the bot's."""


async def _on_video(coro, video: tuple[str, str]):
    """Run `coro` with `video` as the active one (`workspace.PINNED`)."""
    from pipeline.workspace import PINNED

    token = PINNED.set(video)
    try:
        return await coro
    finally:
        PINNED.reset(token)


class Panel:
    """The state the request handler needs, and the loop it runs on."""

    def __init__(self, core: BotCore, loop: asyncio.AbstractEventLoop):
        self.core = core
        self.loop = loop
        self.settings = core.settings
        self.token = panel_token(self.settings)
        self.chat_id = panel_chat_id(self.settings)
        if core.feed is None:
            core.feed = Feed()
        self.feed: Feed = core.feed
        # The voice's cache holds the audio and its word times, which the
        # page's voice step plays; nothing else under the cache is served.
        # The Library shows the owned memes, b-roll, sounds and the rooms:
        # artwork and audio the repo ships, nothing private.
        assets = Path(self.settings.assets_dir)
        roots = [self.settings.workspace_dir, self.settings.templates_dir,
                 self.settings.custom_assets_dir,
                 Path(self.settings.cache_dir) / "tts",
                 assets / "meme_library", assets / "broll_library",
                 assets / "sfx", assets / "score", assets / "plates" / "room"]
        self.roots = [Path(r).resolve() for r in roots]
        self.actions: dict[str, dict] = {}  # the page's actions, newest last
        self._acts_lock = threading.Lock()
        # The chat with the local AI answers on the bot, one question at a
        # time, whether or not a page is open to see it (`bot.chat`).
        self.chats = core.chats
        self.chats.start()

    # ---- the page's actions
    # Every button, command, paste and upload runs on the bot's loop as it
    # always did. The request waits `QUICK_S` for the answer; a slower one
    # answers with the action's id, and the page looks again by it
    # (`GET /api/action`) while the action carries on. What the bot says on
    # the way ("⏳ re-checking…") is kept on the action, so the page shows it
    # where it waits. An answer no page came back for goes to Activity.
    ACTIONS_KEPT = 40
    UNCLAIMED_S = 15.0          # a finished answer no page took, to Activity

    def act(self, make, origin: str = "", video: tuple[str, str] | None = None,
            quick: float | None = None) -> dict:
        """`{"reply": Reply}` when the action answers within `quick`, or
        `{"pending": view}`. `make(say)` is the action's coroutine, given
        where to say what it is doing; `video` is the one the page named,
        which the action runs on whatever is made active meanwhile. An
        action that raised within `quick` raises here."""
        entry = {"id": secrets.token_hex(6), "origin": origin[:200],
                 "started": time.time(), "finished": None, "reply": None,
                 "error": None, "notes": [], "seen": time.time(),
                 "claimed": False}

        async def say(reply: Reply) -> None:
            # Activity keeps it, as before; the waiting page shows it too.
            self.feed.add("reply", reply.text, files=reply.files,
                          keyboard=reply.keyboard)
            with self._acts_lock:
                entry["notes"] = (entry["notes"] + [reply.text])[-5:]

        coro = make(say)
        if video is not None:
            coro = _on_video(coro, video)
        with self._acts_lock:
            self.actions[entry["id"]] = entry
            while len(self.actions) > self.ACTIONS_KEPT:
                self.actions.pop(next(iter(self.actions)))
        fut = asyncio.run_coroutine_threadsafe(coro, self.loop)
        fut.add_done_callback(lambda f: self._finished(entry, f))
        try:
            reply = fut.result(QUICK_S if quick is None else quick)
        except TimeoutError:
            return {"pending": self.action_view(entry["id"], claim=False)}
        finally:
            if fut.done():          # this request answers it, either way
                with self._acts_lock:
                    entry["claimed"] = True
        return {"reply": reply}

    def _finished(self, entry: dict, fut) -> None:
        try:
            reply, error = fut.result(), None
        except ValueError as e:     # a refusal: the page says it, as a 400 did
            reply, error = None, str(e)
        except Exception as e:                          # noqa: BLE001
            log.warning("panel action %s failed", entry["origin"], exc_info=True)
            reply, error = None, f"💥 {e}"
        with self._acts_lock:
            entry.update(reply=reply, error=error, finished=time.time())
            # The page looks every second or two; one that has not looked
            # for ten has gone (reloaded, closed).
            gone = not entry["claimed"] and time.time() - entry["seen"] > 10
        if gone:
            self._unclaimed(entry)
        else:
            t = threading.Timer(self.UNCLAIMED_S, self._unclaimed, args=(entry,))
            t.daemon = True
            t.start()

    def _unclaimed(self, entry: dict) -> None:
        with self._acts_lock:
            if entry["claimed"]:
                return
            entry["claimed"] = True
        reply = entry["reply"]
        if entry["error"]:
            self.feed.add("reply", f"{entry['origin']}: {entry['error']}")
        elif isinstance(reply, Reply) and (reply.text or reply.files):
            self.feed.add("reply", reply.text, files=reply.files,
                          keyboard=reply.keyboard)

    def action_view(self, action_id: str, claim: bool = True) -> dict | None:
        """One action as the page shows it: `done`, then `reply` or `error`.
        Looking at a finished one hands its answer to that page."""
        with self._acts_lock:
            entry = self.actions.get(action_id)
            if entry is None:
                return None
            now = time.time()
            entry["seen"] = now
            done = entry["finished"] is not None
            if done and claim:
                entry["claimed"] = True
            out = {"id": entry["id"], "origin": entry["origin"],
                   "seconds": round((entry["finished"] or now) - entry["started"]),
                   "notes": list(entry["notes"]), "done": done,
                   "error": entry["error"], "reply": None}
            reply = entry["reply"]
        if done and isinstance(reply, Reply):
            out["reply"] = self.reply_json(reply)
        return out

    def open_actions(self) -> list[dict]:
        """What a page opened (or reloaded) now should pick up: every action
        still running, and any finished one no page has taken."""
        with self._acts_lock:
            ids = [a["id"] for a in self.actions.values()
                   if a["finished"] is None or not a["claimed"]]
        return [v for v in (self.action_view(i, claim=False) for i in ids) if v]

    # ---- what a reply looks like to the page
    def file_url(self, path) -> str:
        return f"/api/file?path={quote(str(path))}&k={quote(self.token)}"

    def reply_json(self, reply: Reply) -> dict:
        files = [str(p) for p in reply.files]
        if reply.photo is not None:
            files.insert(0, str(reply.photo))
        return {"text": reply.text,
                "buttons": keyboard_rows(reply.keyboard),
                "files": [{"path": f, "name": Path(f).name,
                           "url": self.file_url(f)} for f in files],
                "card": reply.card}

    def allowed(self, path: Path) -> bool:
        try:
            real = path.resolve()
        except OSError:
            return False
        return real.is_file() and any(real.is_relative_to(r)
                                      for r in self.roots)

    # ---- the screens
    def state(self) -> dict:
        from pipeline.video_state import all_states, card_text, inbox
        from pipeline.workspace import today_str

        states = all_states(self.settings)
        items = inbox(self.settings, states=states)
        active = self.core.context.get(self.chat_id)
        jobs = []
        store = (self.core.queue.store if self.core.queue is not None
                 else None)
        if store is None:
            from pipeline.jobs import JobStore
            store = JobStore(self.settings)
        from pipeline.jobs import progress

        est = {(st.ticker, st.workdate): st.est_render_min for st in states}
        for j in sorted(store.all(), key=lambda j: j.updated_at,
                        reverse=True)[:15]:
            row = {"id": j.id, "kind": j.kind.value, "ticker": j.ticker,
                   "workdate": j.workdate, "status": j.status.value,
                   "detail": j.detail, "error": j.error[:400],
                   "updated_at": j.updated_at, "started_at": j.started_at,
                   "link": j.delivered_link}
            if j.status.value in ("queued", "running"):
                row["progress"] = progress(row, est.get((j.ticker, j.workdate)))
            jobs.append(row)
        ledger = self.core.ledger
        try:
            mtd = ledger.mtd_spend_usd()
        except Exception:  # noqa: BLE001 - an unreadable ledger is shown
            mtd = None
        videos = []
        for st in states:
            row = st.to_json()
            row["card_text"] = card_text(st)
            row["buttons"] = keyboard_rows(cmds.kb.card_keyboard(st))
            row["media"] = [{"name": Path(p).name, "url": self.file_url(p)}
                            for p in (list(st.renders.values()) + st.clips
                                      + st.thumbnails)]
            videos.append(row)
        return {
            "active": ({"ticker": active.ticker, "workdate": active.workdate}
                       if active else None),
            "inbox": [dict(i.to_json(), buttons=keyboard_rows(
                cmds.kb.inbox_keyboard([i]))) for i in items],
            "videos": videos,
            "jobs": jobs,
            "queue_running": self.core.queue is not None,
            "spend": {"mtd": mtd,
                      "cap": self.settings.monthly_spend_cap_usd},
            "mock": self.settings.mock_banner(),
            "notify": cmds.NotifyPrefs(self.settings).level(),
            "feed_seq": self.feed.last_seq,
            "chat_id": self.chat_id,
            # The bot's own date: "today" is the render box's, not the
            # browser's, when the two sit in different time zones.
            "today": today_str(),
            "week": self.week(),
            # what the next plain message will be taken as, with a Cancel
            "waiting": cmds.waiting_for(self.core, self.chat_id),
            "max_upload_mb": self.settings.panel_max_upload_mb,
        }

    def week(self) -> list[dict]:
        """What went out in the last seven days and goes out in the next
        seven, from the upload log: Home's "this week"."""
        from datetime import datetime, timedelta, timezone

        from pipeline.youtube import (VideoLog, public_since, record_format,
                                      still_scheduled)

        now = datetime.now(timezone.utc)
        out = []
        for v in VideoLog(self.settings).all():
            when = public_since(v)
            try:
                t = datetime.fromisoformat(when.replace("Z", "+00:00"))
            except (AttributeError, ValueError):
                continue
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
            if abs(t - now) > timedelta(days=7):
                continue
            out.append({"ticker": v.ticker, "workdate": v.workdate,
                        "title": v.title, "url": v.url(), "when": when,
                        "privacy": v.privacy, "fmt": record_format(v),
                        "pending": still_scheduled(v, now)})
        return sorted(out, key=lambda r: r["when"])


def _handler_for(panel: Panel):
    class Handler(BaseHTTPRequestHandler):
        server_version = "DennisPanel/1"

        def log_message(self, fmt, *args):  # the key rides on file links
            log.debug("panel %s %s", self.command,
                      urlparse(self.path).path)

        # ---- plumbing
        def _send(self, status: int, body: bytes, ctype: str,
                  extra: dict | None = None) -> bool:
            """False when the page had gone by the time this was ready
            (reloaded, closed): there is no one to send it to."""
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            try:
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                log.info("panel %s: the page left before its answer",
                         urlparse(self.path).path)
                self.close_connection = True
                return False
            return True

        def _json(self, data, status: int = 200) -> bool:
            return self._send(status, json.dumps(data).encode("utf-8"),
                              "application/json; charset=utf-8")

        def _authed(self, query: dict) -> bool:
            key = self.headers.get("X-Panel-Key") or \
                (query.get("k") or [""])[0]
            # compared as bytes: a key with a letter outside ASCII made
            # compare_digest raise, and the connection dropped instead of a
            # 401 (scan, 24 Oct 2026)
            return bool(key) and hmac.compare_digest(
                key.encode("utf-8", "surrogateescape"), panel.token.encode("utf-8"))

        def _body(self) -> bytes:
            n = int(self.headers.get("Content-Length") or 0)
            limit = panel.settings.panel_max_upload_mb * 1_000_000
            if n > limit:
                raise ValueError(f"over the {panel.settings.panel_max_upload_mb}"
                                 f" MB panel limit (PANEL_MAX_UPLOAD_MB)")
            return self.rfile.read(n) if n else b""

        def _payload(self) -> dict:
            raw = self._body()
            try:
                data = json.loads(raw or b"{}")
            except ValueError:
                raise ValueError("the request body is not JSON") from None
            if not isinstance(data, dict):
                raise ValueError("the request body is not a JSON object")
            return data

        # ---- routes
        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            url = urlparse(self.path)
            query = parse_qs(url.query)
            if url.path in ("/", "/index.html"):
                return self._static("index.html")
            if url.path.startswith("/static/"):
                return self._static(url.path[len("/static/"):])
            if not url.path.startswith("/api/"):
                return self._json({"error": "not found"}, 404)
            if not self._authed(query):
                return self._json({"error": "the panel key is missing or "
                                            "wrong"}, 401)
            try:
                if url.path == "/api/state":
                    return self._json(panel.state())
                if url.path == "/api/registry":
                    return self._json(cmds.registry_json(panel.core,
                                                         panel.chat_id))
                if url.path == "/api/feed":
                    since = int((query.get("since") or ["0"])[0] or 0)
                    return self._json({"events": [e.to_json() for e in
                                                  panel.feed.since(since)],
                                       "seq": panel.feed.last_seq})
                if url.path == "/api/help":
                    fam = (query.get("family") or [""])[0]
                    return self._json({"text": cmds.help_text(
                        fam, panel.core, panel.chat_id)})
                if url.path == "/api/chats":
                    return self._json({"chats": panel.chats.list()})
                if url.path == "/api/chat":
                    return self._json({"chat": panel.chats.view(
                        (query.get("id") or [""])[0])})
                if url.path == "/api/action":
                    aid = (query.get("id") or [""])[0]
                    if not aid:
                        return self._json({"actions": panel.open_actions()})
                    return self._json({"action": panel.action_view(aid)})
                if url.path == "/api/file":
                    return self._file((query.get("path") or [""])[0])
                if url.path == "/api/video":
                    from bot.panel_views import video_view
                    step = query.get("step")
                    return self._json(video_view(
                        panel, (query.get("t") or [""])[0],
                        (query.get("d") or [""])[0],
                        step=step[0] if step else None))
                if url.path in ("/api/ideas", "/api/calendar", "/api/stats",
                                "/api/library", "/api/settings"):
                    from bot import panel_pages
                    if url.path == "/api/ideas":
                        return self._json(panel_pages.ideas_view(panel))
                    if url.path == "/api/calendar":
                        return self._json(panel_pages.calendar_view(
                            panel, (query.get("m") or [""])[0]))
                    if url.path == "/api/library":
                        return self._json(panel_pages.library_view(panel))
                    if url.path == "/api/settings":
                        return self._json(panel_pages.settings_view(panel))
                    return self._json(panel_pages.stats_view(panel))
                if url.path == "/api/thumb":
                    from bot.panel_pages import thumbnail
                    w = (query.get("w") or ["360"])[0] or "360"
                    if not w.isdigit():
                        return self._json({"error": "w must be a width in pixels"}, 400)
                    out = thumbnail(panel, (query.get("path") or [""])[0], int(w))
                    if out is None:
                        return self._json({"error": "not a picture the panel "
                                                    "serves"}, 404)
                    return self._send(200, out.read_bytes(), "image/jpeg")
                if url.path == "/api/joblog":
                    from pipeline.jobs import job_log
                    n = min(int((query.get("n") or ["50"])[0] or 50), 200)
                    return self._json({"lines": job_log(
                        panel.settings, (query.get("id") or [""])[0], n)})
            except Exception as e:  # noqa: BLE001 - the page shows it
                log.exception("panel GET %s", url.path)
                return self._json({"error": str(e)}, 500)
            return self._json({"error": "not found"}, 404)

        def do_POST(self):
            url = urlparse(self.path)
            query = parse_qs(url.query)
            if not self._authed(query):
                return self._json({"error": "the panel key is missing or "
                                            "wrong"}, 401)
            core, chat = panel.core, panel.chat_id

            def _video(ticker, workdate) -> tuple[str, str] | None:
                """The video a page action names, made the active one: the
                action runs on it, whatever else is made active meanwhile."""
                if not ticker and not workdate:
                    return None
                from bot.panel_views import is_video_key
                from pipeline.workspace import Workspace

                ticker, workdate = str(ticker).upper(), str(workdate)
                if not is_video_key(ticker, workdate) or \
                        not Workspace(panel.settings, ticker, workdate).exists:
                    raise NoSuchVideo("no such video")
                core.context.set(chat, ticker, workdate)
                return ticker, workdate

            def _named(p: dict) -> tuple[str, str] | None:
                v = p.get("video") or {}
                return _video(v.get("ticker"), v.get("workdate")) \
                    if isinstance(v, dict) else None

            def _act(make, video, origin) -> Reply | None:
                """The action's reply, or None once the page has been told
                it is still running and where to look (202)."""
                out = panel.act(make, str(origin or url.path), video)
                if "pending" in out:
                    self._json({"pending": out["pending"]}, 202)
                    return None
                return out["reply"]

            try:
                if url.path == "/api/run":
                    p = self._payload()
                    video = _named(p)
                    text = str(p.get("text") or "").strip()
                    if not text.startswith("/"):
                        text = "/" + text
                    head, _, raw = text.partition(" ")
                    if "\n" in head:
                        head, _, rest = head.partition("\n")
                        raw = rest + (" " + raw if raw else "")
                    reply = _act(lambda say: cmds.run_command(
                        core, chat, head[1:], raw.split(), raw=raw, say=say),
                        video, p.get("origin") or text[:80])
                elif url.path == "/api/callback":
                    p = self._payload()
                    video = _named(p)
                    data = str(p.get("data") or "")
                    reply = _act(lambda say: cmds.handle_callback(
                        core, chat, data, say=say), video, p.get("origin") or data)
                elif url.path == "/api/text":
                    p = self._payload()
                    text = str(p.get("text") or "")
                    if not text.strip():
                        return self._json({"error": "nothing to send"}, 400)
                    video = _named(p)
                    reply = _act(lambda say: cmds.handle_text(
                        core, chat, text, say=say, from_page=True), video,
                        p.get("origin") or f"Paste · {len(text):,} characters")
                elif url.path == "/api/upload":
                    name = Path((query.get("name") or ["upload.bin"])[0]).name
                    video = _video((query.get("t") or [""])[0],
                                   (query.get("d") or [""])[0])
                    data = self._body()
                    if not data:
                        return self._json({"error": "empty file"}, 400)
                    reply = _act(lambda say: cmds.handle_upload(
                        core, chat, name, data, say=say), video,
                        (query.get("o") or [""])[0] or f"Upload · {name}")
                elif url.path == "/api/thumbnail":
                    reply = panel.core.set_thumbnail(
                        (query.get("t") or [""])[0], (query.get("d") or [""])[0],
                        (query.get("fmt") or [""])[0], self._body())
                elif url.path == "/api/switch":
                    p = self._payload()
                    reply = core.set_switch(str(p.get("name") or ""),
                                            bool(p.get("on")))
                elif url.path == "/api/writing":
                    p = self._payload()
                    name = str(p.get("name") or "")
                    reply = (core.reset_writing(name) if p.get("reset") else
                             core.save_writing(name, str(p.get("text") or "")))
                elif url.path.startswith("/api/chat"):
                    return self._chat(url.path, self._payload())
                elif url.path == "/api/memory":
                    p = self._payload()
                    texts = p.get("texts")
                    if not isinstance(texts, list):
                        return self._json({"error": "texts must be a list"}, 400)
                    reply = core.edit_memory(str(p.get("book") or ""), texts,
                                             was=p.get("was"))
                elif url.path == "/api/active":
                    p = self._payload()
                    ticker = str(p.get("ticker") or "").upper()
                    workdate = str(p.get("workdate") or "")
                    from bot.panel_views import is_video_key
                    from pipeline.workspace import Workspace
                    ws = Workspace(panel.settings, ticker, workdate)
                    # A ticker and a date, as /api/video checks: ".." with
                    # no date made the project folder the active video.
                    if not is_video_key(ticker, workdate) or not ws.exists:
                        return self._json({"error": "no such video"}, 404)
                    core.context.set(chat, ticker, workdate)
                    reply = Reply(f"📁 now working on {ticker} {workdate} — "
                                  f"a paste or an upload lands here.")
                else:
                    return self._json({"error": "not found"}, 404)
            except ValueError as e:
                return self._json({"error": str(e)}, 400)
            except NoSuchVideo as e:
                return self._json({"error": str(e)}, 404)
            except Exception as e:  # noqa: BLE001 - the page shows it
                log.exception("panel POST %s", url.path)
                return self._json({"error": f"💥 {e}"}, 500)
            if reply is None:
                return                    # still running: the page looks again
            if not self._json({"reply": panel.reply_json(reply)}) \
                    and (reply.text or reply.files):
                # the page that asked has gone: Activity keeps the reply
                panel.feed.add("reply", reply.text, files=reply.files,
                               keyboard=reply.keyboard)

        def _chat(self, path: str, p: dict) -> bool:
            """The chat with the local AI. Read-only: a question is answered
            on the bot (`bot.chat`), and the page looks again by its id."""
            chats, cid = panel.chats, str(p.get("id") or "")
            mid = str(p.get("message") or "")
            try:
                if path == "/api/chat":
                    chat = chats.say(cid or None, str(p.get("text") or ""))
                elif path == "/api/chat/stop":
                    chat = chats.stop(cid, mid)
                elif path == "/api/chat/retry":
                    chat = chats.retry(cid, mid)
                elif path == "/api/chat/rename":
                    chat = chats.rename(cid, str(p.get("title") or ""))
                elif path == "/api/chat/delete":
                    chats.delete(cid)
                    return self._json({"deleted": cid})
                else:
                    return self._json({"error": "not found"}, 404)
            except LookupError as e:
                return self._json({"error": str(e)}, 404)
            return self._json({"chat": chat})

        # ---- files
        def _static(self, name: str) -> None:
            path = (STATIC / name).resolve()
            if not path.is_relative_to(STATIC) or not path.is_file():
                return self._json({"error": "not found"}, 404)
            ctype = mimetypes.guess_type(path.name)[0] or "text/plain"
            if ctype.startswith("text/") or ctype.endswith("javascript"):
                ctype += "; charset=utf-8"
            self._send(200, path.read_bytes(), ctype)

        def _file(self, raw_path: str) -> None:
            path = Path(raw_path)
            if not raw_path or not panel.allowed(path):
                return self._json({"error": "not a file the panel serves"},
                                  404)
            path = path.resolve()
            size = path.stat().st_size
            ctype = mimetypes.guess_type(path.name)[0] or \
                "application/octet-stream"
            start, end = 0, size - 1
            rng = self.headers.get("Range", "")
            status = 200
            if rng.startswith("bytes=") and size:
                a, _, b = rng[6:].split(",")[0].partition("-")
                try:
                    if a:
                        start = int(a)
                        end = int(b) if b else size - 1
                    else:                         # the last N bytes
                        start = max(size - int(b), 0)
                    end = min(end, size - 1)
                except ValueError:
                    start, end = 0, size - 1
                if start > end:
                    self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.end_headers()
                    return
                status = 206
            length = end - start + 1 if size else 0
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(length))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Cache-Control", "private, max-age=60")
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            disposition = "inline" if ctype.split("/")[0] in (
                "image", "video", "audio", "text") else "attachment"
            self.send_header("Content-Disposition",
                             f'{disposition}; filename="{path.name}"')
            # A FILING IS SOMEONE ELSE'S HTML, opened on the panel's own
            # address, where the key lives: it runs no script, sends no
            # form, and nothing frames it but the panel.
            self.send_header("Content-Security-Policy",
                             "sandbox; script-src 'none'; object-src 'none'; "
                             "frame-ancestors 'self'")
            self.send_header("X-Frame-Options", "SAMEORIGIN")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if self.command == "HEAD" or not length:
                return
            with open(path, "rb") as fh:
                fh.seek(start)
                left = length
                while left > 0:
                    chunk = fh.read(min(1 << 20, left))
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        return            # the player seeked away
                    left -= len(chunk)

    return Handler


def start_panel(core: BotCore, loop: asyncio.AbstractEventLoop,
                host: str | None = None, port: int | None = None
                ) -> tuple[ThreadingHTTPServer, str]:
    """Serve the panel on a daemon thread; returns the server and the link
    (with the key in the fragment, which never reaches a server log)."""
    panel = Panel(core, loop)
    host = host or core.settings.panel_host
    port = core.settings.panel_port if port is None else port
    server = ThreadingHTTPServer((host, port), _handler_for(panel))
    server.daemon_threads = True
    shown = "127.0.0.1" if host in ("0.0.0.0", "") else host
    if host not in ("127.0.0.1", "localhost", "::1"):
        log.warning("the web panel is listening on %s, not just this machine: "
                    "its key travels in plain HTTP — prefer an SSH tunnel "
                    "or a private network", host or "every interface")
    url = f"http://{shown}:{server.server_address[1]}/#k={panel.token}"
    thread = threading.Thread(target=server.serve_forever, name="panel",
                              daemon=True)
    thread.start()
    core.panel_url = url
    log.info("web panel on http://%s:%d/ (the link with its key: /admin panel)",
             shown, server.server_address[1])
    return server, url


def main() -> None:  # pragma: no cover - exercised by hand
    """The panel without Telegram: the queue runs here, pushes go to the
    feed. For a box where the bot is not running, or for a look around in
    MOCK_MODE."""
    from config import get_settings
    from pipeline.jobs import RenderJobQueue

    settings = get_settings()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # httpx logs every request URL at INFO, and Giphy, Tenor and FRED take
    # their key in the URL: run on its own, the panel wrote them to the
    # console (scan, 24 Oct 2026). main.py has always done this.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    core = BotCore(settings)
    core.feed = Feed()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def boot() -> None:
        async def notify(text: str) -> None:
            core.feed.add("notice", text)

        def push(path, caption: str = "") -> None:
            core.feed.add("file", caption, files=[path])

        core.file_pusher = push
        core.queue = RenderJobQueue(settings, core.execute_job, notify)
        core.queue.store.listeners.append(core.job_changed)
        core.queue.start()
        core.answer_waiting_soon()

    loop.run_until_complete(boot())
    _server, url = start_panel(core, loop)
    print(f"Dennis panel: {url}")
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":  # pragma: no cover
    main()
