"""stockanalysis.com, read the way its terms allow (point 7, 30 Oct 2026).

Valentin: "stockanalysis is gonna be a key asset for us, let's scrape as much
as we can". The free public pages carry what the workbook and the SEC feeds
do not: the dated coverage around a move, the press releases, every earnings
call in full with who said what, twenty quarters of statements, the company's
own KPIs, the analysts' target changes, the day's movers and who reports.

THE TERMS DECIDE HOW, not only what (read 30 Oct 2026, last updated 29 Oct):

* "You may not use bots, scripts, scrapers ... or download data in bulk" —
  "This does not apply to search engines, AI agents, or other crawlers that
  follow our robots.txt file." So every request asks robots.txt first, and
  the bot reads a handful of pages per video, on demand, one every couple of
  seconds. Nothing here walks the sitemap or every ticker.
* "You may not let other people, machines or systems access your account."
  The bot never logs in; a cell the page shows as Upgrade or Pro is no value.
* Snippets may be used "as long as you do not modify the content and clearly
  state where you got it from": a quote is shown word for word, and the
  description credits the site (`pipeline/publish.py`).
* The exemption is one sentence of a page that changed the day before it was
  read. `allowed()` reads the terms once a week and turns the whole source
  off by itself if that sentence is gone; `STOCKANALYSIS=false` does the same
  by hand.

Every reader here returns a dict with `status` "ok" or "unavailable" and never
raises: a page that cannot be read, or reads differently from the one these
parsers were written against, is one fewer source, never a failed run.
Results are cached through the free-sources cache (`pipeline/sources.py`), so
a second prompt for the same ticker asks the site nothing.
"""

from __future__ import annotations

import datetime as _dt
import html as _html
import json
import logging
import re
import threading
import time
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.robotparser import RobotFileParser

from config import Settings

log = logging.getLogger(__name__)

BASE = "https://stockanalysis.com"
# Never his email (project rule): the repository says who runs it.
USER_AGENT = "Dennis research bot (+https://github.com/Voleq/Content-Machine)"
NAME = "stockanalysis.com"
UNAVAILABLE = "unavailable"

# The sentence of the terms the bot's access rests on, as it reads on the page.
TERMS_EXEMPTION = "ai agents, or other crawlers that follow our robots.txt"

# The wire services a company's own press releases come through.
WIRES = ("prnewswire", "pr newswire", "business wire", "businesswire",
         "globenewswire", "globe newswire", "accesswire", "newsfile",
         "accessnewswire")

_lock = threading.Lock()
_last = 0.0
# A SITE THAT DID NOT ANSWER IS LEFT ALONE FOR A WHILE. Nothing that failed
# is kept, so with the site down every part of a gather — robots, the terms,
# then the page itself — waited out its own twenty-second timeout, on every
# workbook upload and every /prompts. One timeout, a refused connection, a
# 429 or a 5xx now pauses the source; a page that is merely missing does not.
DOWN_PAUSE_S = 300.0
_down_until = 0.0


def enabled(settings: Settings) -> bool:
    return bool(getattr(settings, "stockanalysis_enabled", True))


def _site_down() -> bool:
    return time.monotonic() < _down_until


def _pause(why: object) -> None:
    global _down_until
    _down_until = time.monotonic() + DOWN_PAUSE_S
    log.info("%s did not answer (%s); left alone for %.0f min", NAME, why,
             DOWN_PAUSE_S / 60)


# --------------------------------------------------------------------------
# Fetching: robots, terms, pace, fixtures.
# --------------------------------------------------------------------------

# Mock mode serves saved copies of the pages (`fixtures/stockanalysis/`): a
# ticker's own folder, the market pages under `_market/`. A ticker with no
# folder reads as unavailable, so the fake EXMPL runs exactly as before.
_FIXTURE_PAGES = (
    (re.compile(r"^/stocks/([a-z0-9.-]+)/$"), "overview"),
    (re.compile(r"^/stocks/([a-z0-9.-]+)/statistics/$"), "statistics"),
    (re.compile(r"^/stocks/([a-z0-9.-]+)/financials/\?p=quarterly$"), "financials"),
    (re.compile(r"^/stocks/([a-z0-9.-]+)/financials/cash-flow-statement/\?p=quarterly$"),
     "cash-flow"),
    (re.compile(r"^/stocks/([a-z0-9.-]+)/metrics/$"), "metrics"),
    (re.compile(r"^/stocks/([a-z0-9.-]+)/forecast/$"), "forecast"),
    (re.compile(r"^/stocks/([a-z0-9.-]+)/company/$"), "company"),
    (re.compile(r"^/stocks/([a-z0-9.-]+)/transcripts/$"), "transcripts"),
    (re.compile(r"^/stocks/([a-z0-9.-]+)/transcripts/([a-z0-9-]+)/$"), "transcript-"),
)


def _fixture(path: str, settings: Settings) -> str | None:
    root = Path(settings.fixtures_dir) / "stockanalysis"
    if path == "/robots.txt":
        name = root / "_market" / "robots.txt"
    elif path.startswith("/markets/") or path in ("/stocks/earnings-calendar/",
                                                  "/terms-of-use/"):
        name = root / "_market" / (path.strip("/").split("/")[-1] + ".html")
    else:
        name = None
        for pattern, page in _FIXTURE_PAGES:
            m = pattern.match(path)
            if m:
                file = page + (m.group(2) if page == "transcript-" else "")
                name = root / m.group(1).upper() / f"{file}.html"
                break
    if name is None:
        return None
    try:
        return name.read_text(encoding="utf-8")
    except OSError:
        return None


def _raw_get(path: str, settings: Settings) -> str | None:
    """One page, paced, counted, never raising. None on any refusal."""
    global _last
    if settings.mock_mode:
        return _fixture(path, settings)
    try:
        import httpx
    except ImportError:                                  # pragma: no cover
        return None
    from pipeline import request_count

    gap = float(getattr(settings, "stockanalysis_gap_s", 2.0) or 0.0)
    with _lock:
        if _site_down():
            return None
        wait = gap - (time.monotonic() - _last)
        if wait > 0:
            time.sleep(wait)
        try:
            request_count.count(settings, "stockanalysis")
            r = httpx.get(BASE + path, timeout=20.0, follow_redirects=True,
                          headers={"User-Agent": USER_AGENT,
                                   "Accept": "text/html,text/plain"})
        except Exception as e:                           # noqa: BLE001
            _pause(f"{path}: {e}")
            return None
        finally:
            _last = time.monotonic()
        if r.status_code == 429 or r.status_code >= 500:
            _pause(f"{path} answered {r.status_code}")
            return None
    if r.status_code != 200:
        log.info("%s%s answered %s", NAME, path, r.status_code)
        return None
    return r.text


def _robots(settings: Settings) -> RobotFileParser | None:
    from pipeline.sources import cached, store

    text = cached(settings, "sa_robots", "robots")
    if not isinstance(text, str):
        got = _raw_get("/robots.txt", settings)
        if got is None:
            return None
        text = store(settings, "sa_robots", "robots", got)
    rp = RobotFileParser()
    rp.parse(text.splitlines())
    return rp


def terms_still_allow(settings: Settings) -> bool | None:
    """Whether the terms still carry the crawler exemption: True, False, or
    None when the page could not be read (the last reading stands)."""
    from pipeline.sources import cached, store

    got = cached(settings, "sa_terms", "terms")
    if isinstance(got, dict) and "allows" in got:
        return bool(got["allows"])
    page = _raw_get("/terms-of-use/", settings)
    if page is None:
        return None
    text = " ".join(_text(page).lower().split())
    allows = TERMS_EXEMPTION in text
    if not allows:
        log.warning("%s's terms no longer carry the crawler exemption; the "
                    "source is off until they do", NAME)
    store(settings, "sa_terms", "terms", {"allows": allows})
    return allows


def allowed(path: str, settings: Settings) -> tuple[bool, str]:
    """(may this page be read, why not). The order is the cheap one first."""
    if not enabled(settings):
        return False, "switched off (STOCKANALYSIS=false)"
    if _site_down():
        return False, (f"{NAME} did not answer; it is asked again in a few "
                       f"minutes")
    if terms_still_allow(settings) is False:
        return False, "its terms no longer allow crawlers that follow robots.txt"
    rp = _robots(settings)
    if rp is None:
        return False, "robots.txt could not be read"
    if not rp.can_fetch(USER_AGENT, BASE + path):
        return False, "robots.txt disallows it"
    return True, ""


def page(path: str, settings: Settings) -> tuple[str | None, str]:
    """(html, why there is none). Robots and the terms are asked first."""
    ok, why = allowed(path, settings)
    if not ok:
        return None, why
    got = _raw_get(path, settings)
    return got, ("" if got is not None else "the page did not answer")


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def _read(kind: str, key: str, path: str, parse, settings: Settings) -> dict:
    """Cached page → parsed dict, with status, url and when it was fetched."""
    from pipeline.sources import cached, store

    hit = cached(settings, kind, key)
    if isinstance(hit, dict):
        return hit
    html, why = page(path, settings)
    out: dict = {"status": UNAVAILABLE, "url": BASE + path, "why": why,
                 "fetched_at": _now()}
    if html is not None:
        try:
            got = parse(html)
        except Exception as e:                           # noqa: BLE001
            log.warning("%s%s could not be read (%s)", NAME, path, e)
            got = None
        if got:
            out.update(got, status="ok", why="")
        else:
            out["why"] = "the page did not read as expected"
    # An unavailable answer is not kept: the next ask tries again.
    return store(settings, kind, key, out) if out["status"] == "ok" else out


# --------------------------------------------------------------------------
# HTML reading.
# --------------------------------------------------------------------------

def _text(fragment: str) -> str:
    """Visible text of a fragment, entities decoded, spaces collapsed."""
    t = re.sub(r"<(script|style|svg)\b.*?</\1>", " ", fragment, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    return " ".join(_html.unescape(t).split())


class _Tables(HTMLParser):
    """Every <table> as rows of cells, each cell its separate text pieces."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[list[str]]]] = []
        self._stack: list[list[list[list[str]]]] = []
        self._row: list[list[str]] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._stack.append([])
        elif tag == "tr" and self._stack:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append([p for p in self._cell if p])
            self._cell = None
        elif tag == "tr" and self._row is not None and self._stack:
            self._stack[-1].append(self._row)
            self._row = None
        elif tag == "table" and self._stack:
            self.tables.append(self._stack.pop())

    def handle_data(self, data):
        if self._cell is not None:
            piece = " ".join(data.split())
            if piece:
                self._cell.append(piece)


def tables(html: str) -> list[list[list[list[str]]]]:
    p = _Tables()
    p.feed(html)
    return p.tables


def _cell(pieces: list[str]) -> str:
    return " ".join(pieces)


def number(text: str) -> float | None:
    """"24,188" → 24188; "745.43B" → 7.4543e11; "8.96%" → 0.0896; "-" → None."""
    t = str(text or "").strip().replace(",", "").replace("$", "")
    t = t.replace("−", "-")
    m = re.match(r"^([+-]?\d+(?:\.\d+)?)\s*([KMBT%])?$", t)
    if not m:
        return None
    v = float(m.group(1))
    scale = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12, "%": 0.01}.get(m.group(2) or "", 1.0)
    return v * scale


_DATE = re.compile(r"([A-Z][a-z]{2,8})\.? (\d{1,2}), (\d{4})")


def date_of(text: str) -> str:
    """The last "Mon D, YYYY" in `text`, as ISO, or ""."""
    for mon, day, year in reversed(_DATE.findall(str(text or ""))):
        for name, fmt in ((mon, "%B %d %Y"), (mon[:3], "%b %d %Y")):
            try:
                return _dt.datetime.strptime(f"{name} {day} {year}",
                                             fmt).date().isoformat()
            except ValueError:
                continue
    return ""


def time_of(text: str) -> str:
    """"Oct 27, 2026, 3:36 PM EDT" → "2026-10-27T15:36:00-04:00" (New York)."""
    raw = str(text or "").strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}T", raw):
        try:
            from zoneinfo import ZoneInfo

            when = _dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if when.tzinfo is None:
                when = when.replace(tzinfo=_dt.timezone.utc)
            return when.astimezone(ZoneInfo("America/New_York")).isoformat(
                timespec="seconds")
        except (ValueError, KeyError):
            return raw
    m = re.match(r"^([A-Z][a-z]{2}) (\d{1,2}), (\d{4}),? (\d{1,2}):(\d{2}) ?([AP]M)", raw)
    if not m:
        day = date_of(raw)
        return day
    try:
        from zoneinfo import ZoneInfo

        when = _dt.datetime.strptime(" ".join(m.groups()), "%b %d %Y %I %M %p")
        return when.replace(tzinfo=ZoneInfo("America/New_York")).isoformat()
    except (ValueError, KeyError):
        return date_of(raw)


def _period_table(table: list[list[list[str]]]) -> dict | None:
    """A statement table: its periods (label + end date) and its rows."""
    if len(table) < 2:
        return None
    head = [_cell(c) for c in table[0]]
    periods, start = [], 0
    ends = None
    for i, row in enumerate(table[:3]):
        first = _cell(row[0]) if row else ""
        if first.lower().startswith("period ending"):
            ends = [date_of(_cell(c)) for c in row[1:]]
            start = i + 1
    labels = head[1:] if not head[0].lower().startswith("period ending") else []
    if ends is None:
        return None
    count = len(ends)
    for i in range(count):
        label = labels[i] if i < len(labels) else ""
        periods.append({"label": label, "end": ends[i]})
    rows: dict[str, list[float | None]] = {}
    for row in table[start:]:
        if len(row) < 2 or not row[0]:
            continue
        label = row[0][0]
        rows[label] = [number(_cell(c)) for c in row[1:count + 1]]
    return {"periods": periods, "rows": rows}


def _section_titles(html: str) -> list[str]:
    return [_text(m.group(1)) for m in re.finditer(r"<h2[^>]*>(.*?)</h2>", html, re.S)]


# --------------------------------------------------------------------------
# The pages.
# --------------------------------------------------------------------------

def _kind_of(source: str) -> str:
    low = source.lower()
    if low == "transcripts":
        return "transcript"
    if low == "filings":
        return "filing"
    if any(w in low for w in WIRES):
        return "release"
    return "article"


def parse_news(html: str) -> dict | None:
    """The stock page's news list: headline, link, summary, outlet, time."""
    items = []
    for chunk in html.split("<h3")[1:]:
        a = re.search(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', chunk, re.S)
        # The byline: `title="<when>"` and "3 days ago - Investopedia". The
        # time is spelled either way ("Oct 27, 2026, 3:36 PM EDT" or ISO UTC).
        when = next((m for m in re.finditer(r'title="([^"]+)"[^>]*>([^<]*)<', chunk)
                     if " - " in m.group(2)), None)
        if not a or not when:
            continue
        title = _text(a.group(2))
        p = re.search(r"<p\b[^>]*>(.*?)</p>", chunk, re.S)
        summary = _text(p.group(1)) if p else ""
        tail = _html.unescape(when.group(2))
        source = tail.split(" - ", 1)[1].strip() if " - " in tail else ""
        stamp = time_of(when.group(1))
        if not title:
            continue
        items.append({"title": title, "url": _html.unescape(a.group(1)),
                      "summary": summary, "source": source, "time": stamp,
                      "date": stamp[:10], "kind": _kind_of(source)})
    return {"items": items} if items else None


_EARNINGS_SENTENCE = re.compile(
    r"The (last|next) (?:estimated )?earnings date (?:was|is)\s+"
    r"(?:\w+day, )?([A-Z][a-z]+ \d{1,2}, \d{4})(?:,? (before market open|after "
    r"market close|during market hours))?", re.I)
_TIMING = {"before market open": "before the open",
           "after market close": "after the close",
           "during market hours": "during the session"}


def parse_statistics(html: str) -> dict | None:
    rows: dict[str, str] = {}
    for table in tables(html):
        for row in table:
            if len(row) == 2 and row[0] and row[1]:
                rows.setdefault(_cell(row[0]), _cell(row[1]))
    if not rows:
        return None
    out: dict[str, Any] = {"rows": rows, "earnings": {}}
    m = _EARNINGS_SENTENCE.search(_text(html))
    if m:
        out["earnings"] = {"which": m.group(1).lower(),
                           "date": date_of(m.group(2)),
                           "timing": _TIMING.get((m.group(3) or "").lower(), "")}
    return out


def parse_statements(html: str) -> dict | None:
    """Every period table on a statements page, merged: one period list,
    every row by its label (values in the page's unit, millions)."""
    periods, rows = None, {}
    for table in tables(html):
        got = _period_table(table)
        if not got or not got["periods"]:
            continue
        if periods is None:
            periods = got["periods"]
        if [p["end"] for p in got["periods"]] != [p["end"] for p in periods]:
            continue
        for label, values in got["rows"].items():
            rows.setdefault(label, values)
    if not periods or not rows:
        return None
    return {"periods": periods, "rows": rows, "unit": "millions"}


def parse_metrics(html: str) -> dict | None:
    titles = ["Operating metrics"] + _section_titles(html)
    sections = []
    n = 0
    for table in tables(html):
        got = _period_table(table)
        if not got:
            continue
        rows = {k: v for k, v in got["rows"].items()
                if not k.lower().endswith("growth")}
        if rows:
            sections.append({"title": titles[n] if n < len(titles) else "",
                             "periods": [p["end"] for p in got["periods"]],
                             "rows": rows})
        n += 1
    return {"sections": sections} if sections else None


_TARGET = re.compile(r"\$?([\d,.]+)\s*(?:→|->)\s*\$?([\d,.]+)|\$([\d,.]+)")


def parse_forecast(html: str) -> dict | None:
    out: dict[str, Any] = {"targets": {}, "actions": [], "consensus": ""}
    for table in tables(html):
        head = [_cell(c).lower() for c in table[0]] if table else []
        if head[:1] == ["target"] and len(table) > 1:
            for label, cell in zip(head[1:], table[1][1:]):
                v = number(_cell(cell))
                if v is not None:
                    out["targets"][label] = v
        elif "analyst" in head and "price target" in head:
            col = {h: i for i, h in reversed(list(enumerate(head)))}
            for row in table[1:]:
                if len(row) < len(head):
                    continue
                pt = _cell(row[col["price target"]])
                m = _TARGET.search(pt)
                old = new = None
                if m and m.group(1):
                    old, new = number(m.group(1)), number(m.group(2))
                elif m:
                    new = number(m.group(3))
                analyst = row[col["analyst"]][0] if row[col["analyst"]] else ""
                out["actions"].append({
                    "analyst": analyst, "firm": _cell(row[col["firm"]]),
                    "rating": _cell(row[col["rating"] + 1]) if col["rating"] + 1 < len(row) else "",
                    "action": _cell(row[col["action"]]) if "action" in col else "",
                    "target_from": old, "target_to": new,
                    "date": date_of(_cell(row[col["date"]])) if "date" in col else ""})
    m = re.search(r'average (?:analyst )?rating for [^"]{0,80} stock is "([^"]+)"', _text(html))
    if m:
        out["consensus"] = m.group(1)
    if not out["targets"] and not out["actions"]:
        return None
    return out


def parse_company(html: str) -> dict | None:
    facts: dict[str, str] = {}
    executives = []
    for table in tables(html):
        head = [_cell(c).lower() for c in table[0]] if table else []
        if head[:2] == ["name", "position"]:
            for row in table[1:]:
                if len(row) >= 2:
                    executives.append({"name": _cell(row[0]), "position": _cell(row[1])})
            continue
        if head[:1] == ["date"]:
            continue
        for row in table:
            if len(row) == 2 and row[0] and row[1]:
                facts.setdefault(_cell(row[0]), _cell(row[1]))
    description = ""
    i = html.find("Company Description")
    if i >= 0:
        paras = re.findall(r"<p\b[^>]*>(.*?)</p>", html[i:i + 20000], re.S)
        description = " ".join(_text(p) for p in paras[:2]).strip()
    if not facts and not executives:
        return None
    return {"facts": facts, "executives": executives[:12],
            "description": description[:1200]}


def parse_transcript_list(html: str) -> dict | None:
    events = []
    for chunk in html.split("<li")[1:]:
        a = re.search(r'<a\b[^>]*href="(/stocks/[^"]+/transcripts/[^"/]+/)"[^>]*>(.*?)</a>', chunk, re.S)
        if not a:
            continue
        title = _text(a.group(2))
        if not title or any(e["path"] == a.group(1) for e in events):
            continue
        when = re.search(r"<span\b[^>]*>([A-Z][a-z]{2} \d{1,2}, \d{4})</span>", chunk)
        p = re.search(r"<p\b[^>]*>(.*?)</p>", chunk, re.S)
        events.append({"title": title, "path": a.group(1),
                       "date": date_of(when.group(1)) if when else "",
                       "summary": _text(p.group(1)) if p else "",
                       "kind": ("earnings" if title.lower().startswith("earnings call")
                                else "conference")})
    return {"events": events} if events else None


def parse_transcript(html: str) -> dict | None:
    h1 = re.search(r"<h1\b[^>]*>(.*?)</h1>\s*<p\b[^>]*>(.*?)</p>", html, re.S)
    summary = ""
    s = re.search(r">\s*Summary\s*</p>\s*<p\b[^>]*>(.*?)</p>", html, re.S)
    if s:
        summary = _text(s.group(1))
    turns = []
    for chunk in re.split(r'<div class="text-lg font-bold[^"]*">', html)[1:]:
        name = _text(chunk.split("</div>", 1)[0])
        rest = chunk.split("</div>", 1)[1] if "</div>" in chunk else ""
        role = ""
        r = re.match(r'\s*<div class="text-sm italic[^"]*">(.*?)</div>', rest, re.S)
        if r:
            role = _text(r.group(1))
        sentences = [_text(x) for x in
                     re.findall(r'<span class="transcript-sentence[^"]*"[^>]*>(.*?)</span>',
                                rest, re.S)]
        text = " ".join(x for x in sentences if x)
        if name and text:
            turns.append({"speaker": name, "role": role, "text": text})
    if not turns:
        return None
    return {"title": _text(h1.group(1)) if h1 else "",
            "date": date_of(_text(h1.group(2))) if h1 else "",
            "summary": summary, "turns": turns}


def parse_movers(html: str) -> dict | None:
    out = []
    for table in tables(html):
        head = [_cell(c).lower() for c in table[0]] if table else []
        if "symbol" not in head or "% change" not in head:
            continue
        col = {h: i for i, h in enumerate(head)}
        rows = []
        for row in table[1:]:
            if len(row) < len(head):
                continue
            price_col = next((i for h, i in col.items() if "price" in h), None)
            rows.append({
                "symbol": _cell(row[col["symbol"]]),
                "name": _cell(row[col["company name"]]) if "company name" in col else "",
                "change": number(_cell(row[col["% change"]])),
                "price": number(_cell(row[price_col])) if price_col is not None else None,
                "volume": number(_cell(row[col["volume"]])) if "volume" in col else None,
                "market_cap": number(_cell(row[col["market cap"]])) if "market cap" in col else None,
            })
        if rows:
            out.append(rows)
    return {"tables": out} if out else None


def parse_earnings_calendar(html: str) -> dict | None:
    day = re.search(r"<h2[^>]*>\s*([A-Z][a-z]{2} \d{1,2})\s*·\s*(\d+) Earnings", html)
    rows = []
    for table in tables(html):
        head = [_cell(c).lower() for c in table[0]] if table else []
        if "symbol" not in head or "earnings time" not in head:
            continue
        col = {h: i for i, h in enumerate(head)}
        for row in table[1:]:
            if len(row) < len(head):
                continue
            rows.append({"symbol": _cell(row[col["symbol"]]),
                         "name": _cell(row[col["company name"]]),
                         "time": _cell(row[col["earnings time"]]),
                         "market_cap": number(_cell(row[col["market cap"]]))
                         if "market cap" in col else None})
    coming = [{"date": date_of(f"{d}"), "day": wd, "count": int(n)}
              for d, wd, n in re.findall(
                  r"([A-Z][a-z]{2} \d{1,2}, \d{4}) (\w+day) (\d+) Earnings", _text(html))]
    if not rows and not coming:
        return None
    today = ""
    if day:
        year = next((c["date"][:4] for c in coming if c["date"]), "")
        today = date_of(f"{day.group(1)}, {year}") if year else ""
    return {"date": today, "rows": rows, "days": coming}


# --------------------------------------------------------------------------
# What the rest of the bot asks for.
# --------------------------------------------------------------------------

def _slug(ticker: str) -> str:
    return re.sub(r"[^a-z0-9.-]", "", str(ticker or "").lower().replace("/", "."))


def news(ticker: str, settings: Settings) -> dict:
    t = _slug(ticker)
    return _read("sa_news", t, f"/stocks/{t}/", parse_news, settings)


def statistics(ticker: str, settings: Settings) -> dict:
    t = _slug(ticker)
    return _read("sa_stats", t, f"/stocks/{t}/statistics/", parse_statistics, settings)


def quarterly(ticker: str, settings: Settings) -> dict:
    """Income (the financials page) and cash flow, by quarter, merged."""
    t = _slug(ticker)
    inc = _read("sa_income_q", t, f"/stocks/{t}/financials/?p=quarterly",
                parse_statements, settings)
    if inc.get("status") != "ok":
        return inc
    cash = _read("sa_cash_q", t,
                 f"/stocks/{t}/financials/cash-flow-statement/?p=quarterly",
                 parse_statements, settings)
    rows = dict(inc.get("rows") or {})
    if cash.get("status") == "ok" and \
            [p["end"] for p in cash.get("periods", [])] == \
            [p["end"] for p in inc.get("periods", [])]:
        for k, v in (cash.get("rows") or {}).items():
            rows.setdefault(k, v)
    return {**inc, "rows": rows}


def metrics(ticker: str, settings: Settings) -> dict:
    t = _slug(ticker)
    return _read("sa_metrics", t, f"/stocks/{t}/metrics/", parse_metrics, settings)


def forecast(ticker: str, settings: Settings) -> dict:
    t = _slug(ticker)
    return _read("sa_forecast", t, f"/stocks/{t}/forecast/", parse_forecast, settings)


def company(ticker: str, settings: Settings) -> dict:
    t = _slug(ticker)
    return _read("sa_company", t, f"/stocks/{t}/company/", parse_company, settings)


def transcript_list(ticker: str, settings: Settings) -> dict:
    t = _slug(ticker)
    return _read("sa_calls", t, f"/stocks/{t}/transcripts/", parse_transcript_list,
                 settings)


def transcript(path: str, settings: Settings) -> dict:
    """One call, by the path the list gave (`/stocks/ba/transcripts/…/`)."""
    if not re.match(r"^/stocks/[a-z0-9.-]+/transcripts/[a-z0-9-]+/$", path or ""):
        return {"status": UNAVAILABLE, "why": "not a transcript path"}
    return _read("sa_call", path.strip("/").replace("/", "_"), path,
                 parse_transcript, settings)


MOVER_PAGES = {"gainers": "/markets/gainers/", "losers": "/markets/losers/",
               "premarket": "/markets/premarket/",
               "afterhours": "/markets/afterhours/"}
# The lists `movers` makes of those pages, in the order every reader shows
# them (`/movers`, Home), each with its title.
MOVER_LISTS = (("gainers", "Up today"), ("losers", "Down today"),
               ("premarket_up", "Up before the open"),
               ("premarket_down", "Down before the open"),
               ("afterhours_up", "Up after the close"),
               ("afterhours_down", "Down after the close"))


def movers(settings: Settings, which: tuple[str, ...] = tuple(MOVER_PAGES)) -> dict:
    """The day's lists. Premarket and after hours carry two tables each
    (gainers, then losers); the day pages one."""
    out: dict[str, Any] = {"status": UNAVAILABLE, "fetched_at": _now(), "lists": {}}
    for name in which:
        got = _read("sa_movers", name, MOVER_PAGES[name], parse_movers, settings)
        if got.get("status") != "ok":
            continue
        tabs = got.get("tables") or []
        if name in ("premarket", "afterhours"):
            if tabs:
                out["lists"][f"{name}_up"] = tabs[0]
            if len(tabs) > 1:
                out["lists"][f"{name}_down"] = tabs[1]
        elif tabs:
            out["lists"][name] = tabs[0]
        out["fetched_at"] = got.get("fetched_at", out["fetched_at"])
    if out["lists"]:
        out["status"] = "ok"
    return out


def _market_day() -> str:
    """Today in New York, the calendar's own day.

    The calendar is kept under it: kept under "today" for six hours, the
    calendar read at 22:00 was still the day's reporters at 02:00."""
    try:
        from zoneinfo import ZoneInfo

        return _dt.datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    except (ImportError, KeyError):      # no zone data here: the machine's day
        return _dt.date.today().isoformat()


def earnings_calendar(settings: Settings) -> dict:
    return _read("sa_calendar", _market_day(), "/stocks/earnings-calendar/",
                 parse_earnings_calendar, settings)


_PER_TICKER = ("sa_news", "sa_stats", "sa_income_q", "sa_cash_q", "sa_metrics",
               "sa_forecast", "sa_company", "sa_calls")


def forget(ticker: str, settings: Settings) -> int:
    """Drop what was kept for one name, so the next read fetches it again.
    Calls are kept: a transcript does not change once it is posted."""
    from pipeline.sources import _cache_path

    t, gone = _slug(ticker), 0
    for kind in _PER_TICKER:
        p = _cache_path(settings, kind, t)
        try:
            p.unlink()
            gone += 1
        except OSError:
            pass
    return gone


# --------------------------------------------------------------------------
# The market's day (11): kept in state, so the page reads a file and never
# the site.
# --------------------------------------------------------------------------

MARKET_FILE = "site_market.json"


def market_today(settings: Settings, *, refresh: bool = False) -> dict:
    """The day's movers and earnings calendar, read and kept.

    `/movers`, the page's button and a live screen call this; the page's
    Home and Calendar read what it kept (`market_saved`)."""
    if refresh:
        from pipeline.sources import _cache_path

        for kind, key in ([("sa_movers", n) for n in MOVER_PAGES]
                          + [("sa_calendar", _market_day())]):
            try:
                _cache_path(settings, kind, key).unlink()
            except OSError:
                pass
    if not enabled(settings):
        out = {"status": "off", "why": "switched off (STOCKANALYSIS=false)",
               "fetched_at": _now()}
    else:
        mv, cal = movers(settings), earnings_calendar(settings)
        out = {"status": "ok" if "ok" in (mv.get("status"), cal.get("status"))
               else UNAVAILABLE,
               "why": mv.get("why") or cal.get("why") or "",
               "fetched_at": _now(), "lists": mv.get("lists") or {},
               "calendar": {k: cal.get(k) for k in ("date", "rows", "days")}
               if cal.get("status") == "ok" else {}}
    p = settings.state_dir / MARKET_FILE
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(out, default=str), encoding="utf-8")
    except OSError as e:
        log.warning("the market snapshot was not kept: %s", e)
    return out


def market_saved(settings: Settings) -> dict | None:
    try:
        got = json.loads((settings.state_dir / MARKET_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return got if isinstance(got, dict) else None


def tradeable(rows: list[dict], settings: Settings, n: int) -> list[dict]:
    """The first `n` rows a short could be about: the screener's own price
    and size floors, so the page does not lead with penny stocks."""
    out = []
    for r in rows or []:
        # A change the page printed as "-" is no move to show: it reached
        # /movers as None and raised there, and the page drew it as +0.0%.
        if not isinstance(r.get("change"), (int, float)):
            continue
        price, cap = r.get("price") or 0, r.get("market_cap") or 0
        if price >= settings.screen_min_price and cap >= settings.screen_min_market_cap:
            out.append(r)
        if len(out) == n:
            break
    return out


def screener_quotes(settings: Settings, have: set[str]) -> tuple[list[dict], str]:
    """The site's day gainers and losers as screener quotes, for names the
    first source did not list (`pipeline.screener.run_screen`).

    The site gives no average volume, so the day's own stands in for it:
    such a name scores no volume surge rather than an invented one."""
    snap = market_today(settings)
    if snap.get("status") != "ok":
        return [], "off" if snap.get("status") == "off" else "failed"
    out = []
    for name in ("gainers", "losers"):
        for r in (snap.get("lists") or {}).get(name) or []:
            sym = str(r.get("symbol") or "").upper()
            if not sym or sym in have or r.get("change") is None:
                continue
            have.add(sym)
            out.append({"symbol": sym, "shortName": r.get("name", ""),
                        "regularMarketPrice": r.get("price"),
                        "regularMarketChangePercent": float(r["change"]) * 100,
                        "regularMarketVolume": r.get("volume"),
                        "averageDailyVolume3Month": r.get("volume"),
                        "marketCap": r.get("market_cap"),
                        "_from": f"on stockanalysis.com's day {name}"})
    return out, "ok" if snap.get("lists") else "empty"
