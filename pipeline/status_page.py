"""A localhost status page (P3.6, optional and last).

Telegram stays the control channel — nothing here changes anything. This is a
read-only window for the times you want to *look* at state rather than ask for
it a line at a time: the queue, the idea backlog, what's scheduled, what
recently rendered.

Deliberately the smallest thing that works: `http.server` from the stdlib, one
self-contained page, no framework, no build step, no JavaScript beyond a meta
refresh. It binds to loopback only — this exposes a render box's internals and
has no authentication, so it must not be reachable from the network.
"""

from __future__ import annotations

import html
import json
import logging
import threading
from datetime import datetime, timezone
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from config import Settings

log = logging.getLogger(__name__)

_CSS = """
:root { color-scheme: light dark; }
body { font: 15px/1.5 -apple-system, Segoe UI, Roboto, sans-serif;
       max-width: 60rem; margin: 2rem auto; padding: 0 1rem; }
h1 { font-size: 1.4rem; margin-bottom: .2rem; }
h2 { font-size: 1rem; margin: 1.6rem 0 .4rem; text-transform: uppercase;
     letter-spacing: .06em; opacity: .65; }
.muted { opacity: .6; }
table { border-collapse: collapse; width: 100%; }
td, th { text-align: left; padding: .25rem .6rem .25rem 0;
         border-bottom: 1px solid rgba(128,128,128,.25); }
code { background: rgba(128,128,128,.14); padding: .05rem .3rem; border-radius: 3px; }
.empty { opacity: .55; font-style: italic; }
"""


def _rows(headers: list[str], rows: list[list[str]], empty: str) -> str:
    if not rows:
        return f'<p class="empty">{html.escape(empty)}</p>'
    head = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in r) + "</tr>"
        for r in rows)
    return f"<table><tr>{head}</tr>{body}</table>"


def render_page(settings: Settings) -> str:
    """The whole page. Pure — every section degrades to a note on failure."""
    sections: list[str] = []

    sections.append("<h2>Render queue</h2>")
    sections.append(_safe(lambda: _queue_section(settings),
                          "the job store is unreadable"))

    sections.append("<h2>Idea queue</h2>")
    sections.append(_safe(lambda: _ideas_section(settings),
                          "the idea queue is unreadable"))

    sections.append("<h2>Theses</h2>")
    sections.append(_safe(lambda: _thesis_section(settings),
                          "the thesis book is unreadable"))

    sections.append("<h2>Scheduled to publish</h2>")
    sections.append(_safe(lambda: _scheduled_section(settings),
                          "the publish log is unreadable"))

    sections.append("<h2>Recent renders</h2>")
    sections.append(_safe(lambda: _renders_section(settings),
                          "the workspace is unreadable"))

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return (
        "<!doctype html><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<meta http-equiv='refresh' content='{max(5, settings.status_refresh_s)}'>"
        "<title>Dennis — status</title>"
        f"<style>{_CSS}</style>"
        "<h1>Dennis</h1>"
        f"<p class='muted'>read-only · {stamp} · Telegram is still the "
        "control channel</p>"
        + "".join(sections)
    )


def _safe(fn, message: str) -> str:
    try:
        return fn()
    except Exception as e:  # noqa: BLE001 - a broken panel is not a broken page
        log.debug("status panel failed: %s", e)
        return f'<p class="empty">{html.escape(message)}</p>'


def _queue_section(settings: Settings) -> str:
    rows = []
    store = settings.state_dir / "jobs"
    if store.is_dir():
        for f in sorted(store.glob("*.json"))[-12:]:
            job = json.loads(f.read_text())
            rows.append([job.get("ticker", ""), job.get("kind", ""),
                         job.get("status", ""), job.get("detail", "")[:48]])
    return _rows(["Ticker", "Kind", "Status", "Detail"], rows, "nothing queued")


def _ideas_section(settings: Settings) -> str:
    from pipeline.standing import IdeaQueue

    rows = [[i.ticker, i.lane or "—", i.source, i.reason[:60]]
            for i in IdeaQueue(settings).ranked(12)]
    return _rows(["Ticker", "Lane", "Source", "Why"], rows,
                 "no ideas — /screen fills this")


def _thesis_section(settings: Settings) -> str:
    from pipeline.standing import ThesisBook

    book = ThesisBook(settings)
    rows = []
    for t in book.tickers():
        th = book.get(t)
        rows.append([t, th.status, th.summary[:60], th.checked_at[:10] or "—"])
    return _rows(["Ticker", "Thesis", "Summary", "Checked"], rows,
                 "nothing covered yet")


def _scheduled_section(settings: Settings) -> str:
    from pipeline.youtube import VideoLog

    rows = [[v.publish_at[:16].replace("T", " "), v.ticker, v.title[:50]]
            for v in VideoLog(settings).scheduled()]
    return _rows(["Publishes", "Ticker", "Title"], rows, "nothing scheduled")


def _renders_section(settings: Settings) -> str:
    root = settings.workspace_dir
    rows: list[list[str]] = []
    if root.is_dir():
        finished = []
        for mp4 in root.glob("*/*/*_final.mp4"):
            finished.append((mp4.stat().st_mtime, mp4))
        for mtime, mp4 in sorted(finished, reverse=True)[:10]:
            when = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
            rows.append([when, mp4.parent.parent.name, mp4.name,
                         f"{mp4.stat().st_size / 1e6:.0f} MB"])
    return _rows(["When", "Ticker", "File", "Size"], rows, "nothing rendered yet")


class _Handler(BaseHTTPRequestHandler):
    def __init__(self, settings: Settings, *args, **kwargs):
        self.settings = settings
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        if self.path not in ("/", "/index.html"):
            self.send_error(404)
            return
        body = render_page(self.settings).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        log.debug("status page: " + fmt, *args)


def serve(settings: Settings, *, block: bool = False) -> ThreadingHTTPServer | None:
    """Start the page. Loopback only — no auth, and it shows internals.

    Returns the server so a caller can shut it down; None when disabled.
    """
    if not settings.status_page_enabled:
        return None
    host = "127.0.0.1"          # never 0.0.0.0: this has no authentication
    server = ThreadingHTTPServer((host, settings.status_page_port),
                                 partial(_Handler, settings))
    log.info("status page on http://%s:%d", host, settings.status_page_port)
    if block:
        server.serve_forever()
        return server
    thread = threading.Thread(target=server.serve_forever, daemon=True,
                              name="status-page")
    thread.start()
    return server
