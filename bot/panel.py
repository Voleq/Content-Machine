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
        roots = [self.settings.workspace_dir, self.settings.templates_dir,
                 Path(self.settings.assets_dir) / "custom"]
        self.roots = [Path(r).resolve() for r in roots]

    # ---- the bridge to the bot's loop
    def run(self, coro, timeout: float = ACTION_TIMEOUT_S):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

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

        states = all_states(self.settings)
        items = inbox(self.settings, states=states)
        active = self.core.context.get(self.chat_id)
        jobs = []
        store = (self.core.queue.store if self.core.queue is not None
                 else None)
        if store is None:
            from pipeline.jobs import JobStore
            store = JobStore(self.settings)
        for j in sorted(store.all(), key=lambda j: j.updated_at,
                        reverse=True)[:15]:
            jobs.append({"id": j.id, "kind": j.kind.value, "ticker": j.ticker,
                         "workdate": j.workdate, "status": j.status.value,
                         "detail": j.detail, "error": j.error[:400],
                         "updated_at": j.updated_at,
                         "link": j.delivered_link})
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
        }


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
                                                       say=panel.say))
                elif url.path == "/api/upload":
                    name = Path((query.get("name") or ["upload.bin"])[0]).name
                    data = self._body()
                    if not data:
                        return self._json({"error": "empty file"}, 400)
                    reply = panel.run(cmds.handle_upload(core, chat, name,
                                                         data, say=panel.say))
                elif url.path == "/api/active":
                    p = self._payload()
                    ticker = str(p.get("ticker") or "").upper()
                    workdate = str(p.get("workdate") or "")
                    from pipeline.workspace import Workspace
                    ws = Workspace(panel.settings, ticker, workdate)
                    if not ticker or not ws.exists:
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
        core.queue.start()

    loop.run_until_complete(boot())
    _server, url = start_panel(core, loop)
    print(f"Dennis panel: {url}")
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":  # pragma: no cover
    main()
