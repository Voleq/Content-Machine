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
# gates call the model); an upload can be a long clip. The page waits.
ACTION_TIMEOUT_S = 20 * 60


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

    # ---- the bridge to the bot's loop
    def run(self, coro, timeout: float = ACTION_TIMEOUT_S):
        """The action's reply, or TimeoutError after `timeout`. The page
        then says the result will appear in Activity, so it is put there
        when the action does finish: a long's upload outlasts the wait,
        and its link was thrown away (scan, 24 Oct 2026)."""
        fut = asyncio.run_coroutine_threadsafe(coro, self.loop)
        try:
            return fut.result(timeout)
        except TimeoutError:
            fut.add_done_callback(self._late_reply)
            raise

    def _late_reply(self, fut) -> None:
        try:
            reply = fut.result()
        except Exception as e:                          # noqa: BLE001
            self.feed.add("reply", f"💥 {e}")
            return
        if isinstance(reply, Reply) and (reply.text or reply.files):
            self.feed.add("reply", reply.text, files=reply.files,
                          keyboard=reply.keyboard)

    async def say(self, reply: Reply) -> None:
        """An interim message ("⏳ got it…") goes to the feed, where the
        page shows it while the action is still running."""
        self.feed.add("reply", reply.text, files=reply.files,
                      keyboard=reply.keyboard)

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
                  extra: dict | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, data, status: int = 200) -> None:
            self._send(status, json.dumps(data).encode("utf-8"),
                       "application/json; charset=utf-8")

        def _authed(self, query: dict) -> bool:
            key = self.headers.get("X-Panel-Key") or \
                (query.get("k") or [""])[0]
            return bool(key) and hmac.compare_digest(key, panel.token)

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
                if url.path == "/api/file":
                    return self._file((query.get("path") or [""])[0])
                if url.path == "/api/video":
                    from bot.panel_views import video_view
                    return self._json(video_view(
                        panel, (query.get("t") or [""])[0],
                        (query.get("d") or [""])[0]))
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
                    out = thumbnail(panel, (query.get("path") or [""])[0],
                                    int((query.get("w") or ["360"])[0] or 360))
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
            try:
                if url.path == "/api/run":
                    text = str(self._payload().get("text") or "").strip()
                    if not text.startswith("/"):
                        text = "/" + text
                    head, _, raw = text.partition(" ")
                    if "\n" in head:
                        head, _, rest = head.partition("\n")
                        raw = rest + (" " + raw if raw else "")
                    reply = panel.run(cmds.run_command(
                        core, chat, head[1:], raw.split(), raw=raw,
                        say=panel.say))
                elif url.path == "/api/callback":
                    data = str(self._payload().get("data") or "")
                    reply = panel.run(cmds.handle_callback(core, chat, data,
                                                           say=panel.say))
                elif url.path == "/api/text":
                    text = str(self._payload().get("text") or "")
                    if not text.strip():
                        return self._json({"error": "nothing to send"}, 400)
                    reply = panel.run(cmds.handle_text(core, chat, text,
                                                       say=panel.say,
                                                       from_page=True))
                elif url.path == "/api/upload":
                    name = Path((query.get("name") or ["upload.bin"])[0]).name
                    data = self._body()
                    if not data:
                        return self._json({"error": "empty file"}, 400)
                    reply = panel.run(cmds.handle_upload(core, chat, name,
                                                         data, say=panel.say))
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
                elif url.path == "/api/ask":
                    # Read-only, and as long as the model takes: this
                    # request's own thread waits, the page shows "reading".
                    question = " ".join(str(self._payload().get("question") or "").split())
                    if not question:
                        return self._json({"error": "ask a question"}, 400)
                    text = core.ask_text(question.split())
                    panel.feed.add("reply", f"❓ {question}\n\n{text}")
                    reply = Reply(text)
                elif url.path == "/api/memory":
                    p = self._payload()
                    texts = p.get("texts")
                    if not isinstance(texts, list):
                        return self._json({"error": "texts must be a list"}, 400)
                    reply = core.edit_memory(str(p.get("book") or ""), texts)
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
            except TimeoutError:
                return self._json({"error": "still running — the result will "
                                            "appear in Activity"}, 504)
            except Exception as e:  # noqa: BLE001 - the page shows it
                log.exception("panel POST %s", url.path)
                return self._json({"error": f"💥 {e}"}, 500)
            return self._json({"reply": panel.reply_json(reply)})

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
