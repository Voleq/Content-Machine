"""The companion page: the receipt for one video (25).

Every finished render already carries a provenance record — where the prices
came from, what the visuals were, which filings, which voice at what cost,
which LLM provider, and which gates actually ran. It lives on a manifest and
in one Telegram message, which means the only person who ever sees it is the
person who already knows.

A viewer arriving on a finance video narrated by a synthetic voice has
exactly one question, and it is not answerable from the video: where did
these numbers come from. This is that answer, as a page, linked from the
description.

It is also the per-video original artefact the platform's originality rule
asks for, and it is free: every field on it was gathered for the render.

Plain, self-contained HTML with no external anything — it has to survive
being dropped on any host, and a page that fetches a stylesheet from
somewhere is a page that breaks the day that somewhere moves.
"""

from __future__ import annotations

import html
import json
import logging
from pathlib import Path

from config import Settings

log = logging.getLogger(__name__)

PAGE_NAME = "companion.html"

_CSS = """
:root { color-scheme: light dark;
  --ink:#141a1d; --paper:#f4f2ed; --rule:#c9c3b6; --muted:#5d6b70; --accent:#8a3324; }
@media (prefers-color-scheme: dark) { :root {
  --ink:#ece7dd; --paper:#14181a; --rule:#333c40; --muted:#94a2a8; --accent:#d98b6f; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--paper); color:var(--ink); padding:32px 20px 64px;
  font:16px/1.6 "Iowan Old Style", Georgia, serif; }
main { max-width: 42rem; margin: 0 auto; }
h1 { font-size: 2rem; margin:0 0 4px; letter-spacing:-0.01em; }
.sub { color:var(--muted); margin:0 0 28px; font-size:0.95rem; }
h2 { font-size:0.8rem; text-transform:uppercase; letter-spacing:0.12em;
  color:var(--accent); margin:32px 0 10px; font-family:ui-monospace,monospace; }
table { width:100%; border-collapse:collapse; font-size:0.95rem; }
td { padding:7px 0; border-bottom:1px solid var(--rule); vertical-align:top; }
td:first-child { color:var(--muted); width:38%; padding-right:16px; }
.num { font-variant-numeric: tabular-nums; }
ul { margin:0; padding-left:1.1rem; }
li { margin-bottom:5px; }
footer { margin-top:40px; padding-top:16px; border-top:2px solid var(--ink);
  color:var(--muted); font-size:0.85rem; }
"""


def _rows(pairs) -> str:
    out = []
    for label, value in pairs:
        if value in (None, "", [], {}):
            continue
        out.append(f"<tr><td>{html.escape(str(label))}</td>"
                   f"<td class='num'>{html.escape(str(value))}</td></tr>")
    return "<table>" + "".join(out) + "</table>" if out else ""


def _list(items) -> str:
    rows = [f"<li>{html.escape(str(i))}</li>" for i in items if i]
    return f"<ul>{''.join(rows)}</ul>" if rows else ""


def build_page(manifest: dict, *, ticker: str = "", title: str = "",
               why: str = "", video_url: str = "") -> str:
    """The page, from the manifest the render already wrote.

    Everything is read defensively. A manifest from an older build, a render
    that skipped a section, a provenance block that is not there: each drops
    its own section rather than failing the page. A receipt that refuses to
    print because one line is missing is not a receipt.
    """
    prov = manifest.get("provenance") or {}
    ticker = ticker or str(manifest.get("ticker", "")) or "—"
    heading = title or f"{ticker}: where these numbers came from"
    prices = manifest.get("prices") or prov.get("prices") or {}
    duration = manifest.get("duration_s") or manifest.get("duration") or 0

    parts = [f"<h1>{html.escape(heading)}</h1>"]
    parts.append(
        "<p class='sub'>The record this video was built from. Every figure "
        "on screen was read against it before the render ran.</p>")
    if why.strip():
        parts.append("<h2>Why this one</h2>"
                     f"<p>{html.escape(why.strip())}</p>")
    parts.append("<h2>The video</h2>" + _rows([
        ("Ticker", ticker),
        ("Format", manifest.get("format") or
         ("long" if manifest.get("engine") == "segments" else "")),
        ("Runtime", f"{float(duration):.0f}s" if duration else ""),
        ("Watch", video_url),
    ]))

    if prices:
        parts.append("<h2>Prices</h2>" + _rows([
            ("Source", prices.get("source")),
            ("Live feed", "no — drawn from the seeded floor"
             if prices.get("degraded") else "yes"),
        ]))

    filings = prov.get("filings") or []
    if filings:
        parts.append("<h2>Filings read</h2>" + _list(filings))

    visuals = prov.get("visuals") or prov.get("broll") or []
    if visuals:
        parts.append("<h2>Visuals</h2>" + _list(visuals))

    voice = prov.get("voice") or prov.get("tts") or {}
    if voice:
        parts.append("<h2>Narration</h2>" + _rows([
            ("Voice", voice.get("voice") if isinstance(voice, dict) else voice),
            ("Model", voice.get("model") if isinstance(voice, dict) else ""),
            ("Synthetic", "yes — this narration is generated, not recorded"),
        ]))
    else:
        parts.append("<h2>Narration</h2><p>This narration is generated, not "
                     "recorded. No person is speaking.</p>")

    gates = prov.get("gates") or prov.get("gates_line") or ""
    if gates:
        parts.append("<h2>Checks that ran</h2>"
                     f"<p class='num'>{html.escape(str(gates))}</p>")

    parts.append(
        "<footer>Nothing here is advice. The numbers are the company's own, "
        "as filed; the reading of them is one person's.</footer>")
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,"
            f"initial-scale=1'><title>{html.escape(heading)}</title>"
            f"<style>{_CSS}</style></head><body><main>"
            + "".join(parts) + "</main></body></html>")


def write_companion(manifest_path: Path, settings: Settings, *,
                    out_path: Path | None = None, why: str = "",
                    video_url: str = "") -> Path | None:
    """Write the page beside the render. Never fatal.

    A by-product, on the same terms as the subtitles and the upload package:
    worth having, never worth losing a finished render over.
    """
    try:
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        log.warning("companion page: unreadable manifest (%s)", e)
        return None
    if not isinstance(manifest, dict):
        return None
    out = out_path or Path(manifest_path).parent / PAGE_NAME
    try:
        out.write_text(build_page(manifest, why=why, video_url=video_url),
                       encoding="utf-8")
    except OSError as e:
        log.warning("companion page: could not be written (%s)", e)
        return None
    return out
