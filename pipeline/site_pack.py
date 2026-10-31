"""What one video takes from stockanalysis.com, kept on its workspace.

`pipeline/stockanalysis.py` reads the site; this decides what a SHORT or a
LONG gets from it and keeps that as `site_pack.json` beside the workbook, so
the prompt, the check, the render and the page all read the same snapshot,
and the page can say what was fetched and when.

What a video takes (Valentin's picks, 30 Oct 2026, all but auto-filling the
workbook):

1. the coverage around the move: headline, outlet, minute, summary;
2. the company's press releases among it;
3. the latest earnings call: its summary and the passages that bear on the
   move, word for word, picked by the local AI (keyword scoring when it is
   not running, or while a render has the card);
4. one of those lines on the quote card, only if it is in the call word for
   word (`verified_quote`);
5. for a long, the call a year earlier: what they said they would do;
6. the last earnings date, a second clock beside the SEC's (`move_kind`);
7. twenty quarters of statements, checked against the workbook, and the
   workbook's blank quarters filled from them (`cross_check`,
   `fill_quarter_gaps`);
9. the company's own KPIs; 10. the analysts' target changes; 12. who runs
   it and what it does. (11, the movers and the earnings calendar, are the
   market's, not a video's: `pipeline/stockanalysis.py` and the screener.)

Nothing here raises, and nothing here blocks: a missing part is a line in
the prompt saying so, and every check it adds is a warning.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import re
from pathlib import Path
from typing import Any

from config import Settings

log = logging.getLogger(__name__)

PACK = "site_pack.json"
NEWS_DAYS = {"short": 6, "long": 21}
NEWS_MAX = 30
PASSAGES = 5
PASSAGE_CHARS = 420
# The quote card's body: four lines of 39 on the phone card.
QUOTE_MAX = 150
ATTRIBUTION_MAX = 63
SOURCE_MAX = 47

# The rows a video can use, by the workbook's own field keys.
QUARTER_ROWS = {
    "revenue": "Revenue", "gross_profit": "Gross Profit",
    "operating_income": "Operating Income", "net_income": "Net Income",
    "eps": "Earnings Per Share", "operating_cf": "Operating Cash Flow",
    "capex": "Capital Expenditures", "fcf": "Free Cash Flow",
}
_PER_SHARE = {"eps"}

STAT_ROWS = ("Market Cap", "Enterprise Value", "Shares Outstanding",
             "Owned by Institutions (%)", "Float", "PE Ratio", "Forward PE",
             "EV / EBITDA", "Short Interest", "Short % of Float",
             "52-Week Price Change", "Beta (5Y)", "Revenue", "Net Income",
             "Free Cash Flow", "Gross Margin", "Operating Margin",
             "Total Debt", "Cash & Cash Equivalents", "Altman Z-Score")
COMPANY_FACTS = ("Founded", "Industry", "Sector", "Employees", "CEO",
                 "Country", "Fiscal Year", "IPO Date", "Exchange", "Website")


# --------------------------------------------------------------------------
# The file.
# --------------------------------------------------------------------------

def path(workspace: Path) -> Path:
    return Path(workspace) / PACK


def load(workspace: Path | None) -> dict | None:
    if workspace is None:
        return None
    try:
        got = json.loads(path(workspace).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return got if isinstance(got, dict) else None


def _save(workspace: Path, pack: dict) -> None:
    p = path(workspace)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(pack, indent=1, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(p)
    except OSError as e:
        log.warning("the site pack for %s was not kept: %s", workspace, e)


def used(workspace: Path | None) -> bool:
    """Whether this video carries anything read off the site (the credit)."""
    pack = load(workspace)
    return bool(pack) and any(
        (p or {}).get("status") == "ok" for p in (pack.get("parts") or {}).values())


CREDIT = ("Research for this video, including call transcripts, news and "
          "figures: stockanalysis.com (https://stockanalysis.com).")


def credit(workspace: Path | None) -> str:
    """The description's credit line, or "" when nothing was read off it."""
    return CREDIT if used(workspace) else ""


# --------------------------------------------------------------------------
# Gathering.
# --------------------------------------------------------------------------

def _part(got: dict) -> dict:
    return {k: got.get(k, "") for k in ("status", "why", "fetched_at", "url")}


def _ok(got: dict | None) -> bool:
    return isinstance(got, dict) and got.get("status") == "ok"


def _recent_news(items: list[dict], today: _dt.date, days: int) -> list[dict]:
    out = []
    for it in items:
        try:
            when = _dt.date.fromisoformat(str(it.get("date") or "")[:10])
        except ValueError:
            continue
        if 0 <= (today - when).days <= days:
            out.append(it)
    return out[:NEWS_MAX]


def _year_ago(events: list[dict], latest: dict) -> dict | None:
    """The earnings call about a year before `latest`."""
    try:
        then = _dt.date.fromisoformat(latest["date"])
    except (KeyError, ValueError):
        return None
    best, gap = None, None
    for e in events:
        if e is latest or e.get("kind") != "earnings":
            continue
        try:
            d = _dt.date.fromisoformat(e["date"])
        except (KeyError, ValueError):
            continue
        off = abs((then - d).days - 365)
        if (then - d).days > 300 and off <= 60 and (gap is None or off < gap):
            best, gap = e, off
    return best


def gather(workspace: Path, ticker: str, settings: Settings, *,
           lane: str = "short", refresh: bool = False, busy: bool = False,
           today: _dt.date | None = None) -> dict:
    """Read what this video takes from the site and keep it on the workspace.

    `busy` says a render has the graphics card: the passages are then picked
    by keyword scoring, never by the local model. `refresh` forgets the
    cached pages for this ticker first.
    """
    from pipeline import stockanalysis as sa

    lane = "long" if lane in ("long", "update") else "short"
    today = today or _dt.date.today()
    pack: dict[str, Any] = {"ticker": ticker.upper(), "lane": lane,
                            "fetched_at": sa._now(), "source": sa.NAME,
                            "parts": {}}
    if not sa.enabled(settings):
        pack.update(status="off", why="switched off (STOCKANALYSIS=false)")
        _save(workspace, pack)
        return pack
    # The passages already picked for this call are kept: the model reads a
    # call once per video, not every time the prompt is made again.
    old = {} if refresh else (load(workspace) or {})
    if refresh:
        sa.forget(ticker, settings)

    news = sa.news(ticker, settings)
    pack["parts"]["news"] = _part(news)
    if _ok(news):
        pack["news"] = _recent_news(news.get("items") or [], today,
                                    NEWS_DAYS[lane])

    stats = sa.statistics(ticker, settings)
    pack["parts"]["statistics"] = _part(stats)
    if _ok(stats):
        pack["earnings"] = stats.get("earnings") or {}
        rows = stats.get("rows") or {}
        pack["stats"] = {k: rows[k] for k in STAT_ROWS if k in rows}

    q = sa.quarterly(ticker, settings)
    pack["parts"]["quarterly"] = _part(q)
    if _ok(q):
        pack["quarterly"] = {
            "periods": q.get("periods") or [],
            "rows": {label: (q.get("rows") or {}).get(label)
                     for label in QUARTER_ROWS.values()
                     if (q.get("rows") or {}).get(label)},
            "segments": _segments(q)}

    m = sa.metrics(ticker, settings)
    pack["parts"]["metrics"] = _part(m)
    if _ok(m):
        pack["kpis"] = (m.get("sections") or [])[:4]

    f = sa.forecast(ticker, settings)
    pack["parts"]["forecast"] = _part(f)
    if _ok(f):
        pack["analysts"] = {"targets": f.get("targets") or {},
                            "consensus": f.get("consensus") or "",
                            "actions": (f.get("actions") or [])[:10]}

    c = sa.company(ticker, settings)
    pack["parts"]["company"] = _part(c)
    if _ok(c):
        facts = c.get("facts") or {}
        pack["company"] = {"facts": {k: facts[k] for k in COMPANY_FACTS if k in facts},
                           "executives": (c.get("executives") or [])[:8],
                           "description": c.get("description") or ""}

    calls = sa.transcript_list(ticker, settings)
    pack["parts"]["calls"] = _part(calls)
    events = calls.get("events") or [] if _ok(calls) else []
    latest = next((e for e in events if e.get("kind") == "earnings"), None)
    if latest:
        pack["call"] = _call(latest, settings, focus="move", busy=busy,
                             kept=old.get("call"))
        pack["parts"]["call"] = _part(pack["call"])
        later = [e for e in events[:events.index(latest)]
                 if e.get("kind") == "conference"]
        if later:
            pack["since_call"] = [{k: e.get(k, "") for k in
                                   ("title", "date", "summary")} for e in later[:2]]
        if lane == "long":
            then = _year_ago(events, latest)
            if then:
                pack["year_ago_call"] = _call(then, settings, focus="promises",
                                              busy=busy,
                                              kept=old.get("year_ago_call"))
                pack["parts"]["year_ago_call"] = _part(pack["year_ago_call"])
    ok = [k for k, v in pack["parts"].items() if v.get("status") == "ok"]
    pack["status"] = "ok" if ok else "unavailable"
    if not ok:
        pack["why"] = next((v.get("why") for v in pack["parts"].values()
                            if v.get("why")), "nothing answered")
    _save(workspace, pack)
    return pack


def _segments(q: dict) -> dict:
    """Revenue by segment rows, when the page carries them between Revenue
    Growth and the total."""
    rows = q.get("rows") or {}
    labels = list(rows)
    try:
        start = labels.index("EPS Growth") + 1
        end = labels.index("Revenue (Total)")
    except ValueError:
        return {}
    return {k: rows[k] for k in labels[start:end] if k != "Eliminations"}


def _call(event: dict, settings: Settings, *, focus: str, busy: bool,
          kept: dict | None = None) -> dict:
    from pipeline import stockanalysis as sa

    got = sa.transcript(event.get("path", ""), settings)
    out = {"status": got.get("status"), "why": got.get("why", ""),
           "fetched_at": got.get("fetched_at", ""),
           "url": got.get("url", sa.BASE + event.get("path", "")),
           "title": event.get("title") or got.get("title", ""),
           "date": event.get("date") or got.get("date", ""),
           "summary": got.get("summary") or event.get("summary", "")}
    if not _ok(got):
        return out
    turns = got.get("turns") or []
    out["turns"] = turns
    kept = kept or {}
    # A keyword pick made while a render had the card is made again once it
    # is free; a model's pick of the same call is kept.
    if (kept.get("url") == out["url"] and kept.get("passages")
            and (busy or not str(kept.get("picked_by", "")).startswith("keyword"))):
        out["passages"], out["picked_by"] = kept["passages"], kept.get("picked_by", "")
        return out
    picked, by = pick_passages(turns, settings, focus=focus, busy=busy)
    out["passages"], out["picked_by"] = picked, by
    return out


# --------------------------------------------------------------------------
# The passages.
# --------------------------------------------------------------------------

_MOVE_WORDS = (
    "guid", "outlook", "expect", "target", "forecast", "delay", "slower",
    "longer than", "shy of", "below", "lower", "cut", "raise", "record",
    "margin", "free cash flow", "cash flow", "deliver", "demand", "backlog",
    "headwind", "pressure", "charge", "impair", "miss", "decline", "growth",
    "inventory", "tariff", "pricing", "orders", "weak", "strong", "risk",
    "challeng", "disappoint", "uncertain", "slow")
_PROMISE_WORDS = (
    "expect", "target", "guid", "will ", "plan", "by the end of", "next year",
    "we anticipate", "on track", "commit", "goal", "aim", "intend", "by 20")
_NUMBER = re.compile(r"(\$\s?\d|\d+(\.\d+)?\s?(%|percent|billion|million)|\b\d{2,}\b)")
_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"“'‘(])")


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SPLIT.split(" ".join(str(text or "").split()))
            if s.strip()]


def _windows(turns: list[dict]) -> list[dict]:
    """Every one- and two-sentence stretch a passage could be."""
    out = []
    for n, turn in enumerate(turns):
        who = str(turn.get("speaker") or "")
        role = str(turn.get("role") or "")
        if who.lower() == "operator":
            continue
        sents = _sentences(turn.get("text", ""))
        for i, s in enumerate(sents):
            if "forward-looking" in s.lower() or len(s) < 40:
                continue
            for width in (1, 2):
                text = " ".join(sents[i:i + width])
                if len(text) > PASSAGE_CHARS or (width == 2 and i + 1 >= len(sents)):
                    continue
                out.append({"turn": n, "at": i, "speaker": who, "role": role,
                            "text": text})
    return out


def _score(w: dict, focus: str) -> float:
    low = w["text"].lower()
    words = _PROMISE_WORDS if focus == "promises" else _MOVE_WORDS
    hits = sum(1 for k in words if k in low)
    score = hits + (1.5 if _NUMBER.search(w["text"]) else 0)
    role = w["role"].lower()
    if any(t in role for t in ("chief", "ceo", "cfo", "president")):
        score += 1.0
    elif "analyst" in role and focus == "move":
        score += 0.5 if "?" in w["text"] else 0
    return score - (0.3 if len(w["text"]) > 300 else 0)


def _diverse(ranked: list[dict], n: int) -> list[dict]:
    """The best `n` that do not overlap, in the order the call said them."""
    out: list[dict] = []
    for w in ranked:
        if any(o["turn"] == w["turn"] and abs(o["at"] - w["at"]) < 3 for o in out):
            continue
        out.append(w)
        if len(out) == n:
            break
    return sorted(out, key=lambda w: (w["turn"], w["at"]))


_PICK_SYSTEM = (
    "You read earnings-call excerpts for a finance video. You only choose "
    "excerpts by number; you never rewrite them. Reply with a JSON list of "
    "numbers and nothing else.")
_FOCUS = {
    "move": ("the stock's reaction to this report: changes to guidance, what "
             "management said about a miss, a delay, cash, demand or margins, "
             "and the analysts' sharpest questions"),
    "promises": ("commitments about the future that can be checked a year "
                 "later: targets, guidance, timelines, rates, dates"),
}


def pick_passages(turns: list[dict], settings: Settings, *, focus: str = "move",
                  busy: bool = False, n: int = PASSAGES) -> tuple[list[dict], str]:
    """(passages, who picked them). Every passage is the call's own text: the
    model only chooses among numbered excerpts, so nothing it writes can
    reach the prompt as a quote."""
    windows = _windows(turns)
    if not windows:
        return [], ""
    ranked = sorted(windows, key=lambda w: _score(w, focus), reverse=True)
    shortlist = _diverse(ranked, 36)
    picked, by = None, "keyword scoring"
    if busy:
        by = "keyword scoring (a render had the graphics card)"
    else:
        picked, who = _model_pick(shortlist, settings, focus, n)
        if picked:
            by = who
    if not picked:
        picked = _diverse(ranked, n)
    return [{"speaker": w["speaker"], "role": w["role"], "text": w["text"]}
            for w in picked], by


def _model_pick(shortlist: list[dict], settings: Settings, focus: str,
                n: int) -> tuple[list[dict] | None, str]:
    from pipeline.llm import OLLAMA, chat_result

    lines = [f"[{i + 1}] {w['speaker']} ({w['role'] or 'participant'}): {w['text']}"
             for i, w in enumerate(shortlist)]
    prompt = (f"Choose the {n} excerpts that best explain {_FOCUS[focus]}.\n\n"
              + "\n".join(lines) + f"\n\nReply with {n} numbers as a JSON list, "
              "best first, e.g. [4, 11, 2, 19, 7].")
    try:
        got = chat_result(prompt, settings, system=_PICK_SYSTEM,
                          purpose="transcript-passages", providers=[OLLAMA])
    except Exception as e:                               # noqa: BLE001
        log.info("the passage pick did not run (%s)", e)
        return None, ""
    text = getattr(got, "text", "") or ""
    m = re.search(r"\[[\d,\s]+\]", text)
    if not m:
        return None, ""
    try:
        nums = [int(x) for x in json.loads(m.group(0))]
    except (ValueError, TypeError):
        return None, ""
    chosen = []
    for k in nums:
        if 1 <= k <= len(shortlist) and shortlist[k - 1] not in chosen:
            chosen.append(shortlist[k - 1])
        if len(chosen) == n:
            break
    if len(chosen) < min(3, n):
        return None, ""
    return sorted(chosen, key=lambda w: (w["turn"], w["at"])), "the local AI"


# --------------------------------------------------------------------------
# Quotes.
# --------------------------------------------------------------------------

def _norm(text: str) -> str:
    t = str(text or "")
    for a, b in (("’", "'"), ("‘", "'"), ("“", '"'), ("”", '"'),
                 ("—", "-"), ("–", "-"), ("…", "...")):
        t = t.replace(a, b)
    t = " ".join(t.split()).strip().strip('"').strip()
    return t.rstrip(".").lower()


def verified_quote(workspace: Path | None, text: str) -> dict | None:
    """Who said `text`, on which call, when it is in a call word for word.

    Whitespace, curly quotes and a final full stop do not count; a changed,
    added or dropped word does."""
    want = _norm(text)
    if len(want) < 12:
        return None
    pack = load(workspace) or {}
    for key in ("call", "year_ago_call"):
        call = pack.get(key) or {}
        for turn in call.get("turns") or []:
            if want in _norm(turn.get("text", "")):
                return {"speaker": turn.get("speaker", ""),
                        "role": turn.get("role", ""),
                        "event": call.get("title", ""),
                        "date": call.get("date", "")}
    return None


def _event_words(title: str, date: str) -> str:
    """"Earnings Call: Q3 2026", "2026-10-27" → "Q3 2026 earnings call, 27 Oct 2026"."""
    t = str(title or "").strip()
    m = re.match(r"(?i)earnings call:\s*(.+)$", t)
    head = f"{m.group(1)} earnings call" if m else t
    try:
        d = _dt.date.fromisoformat(date)
        head += f", {d.day} {d:%b %Y}"
    except (TypeError, ValueError):
        pass
    return head


def quote_card(workspace: Path | None, quote) -> dict | None:
    """The quote card's three slots for a short's `call_quote`, or None when
    the line is not in the call word for word (the card is then not drawn)."""
    if quote is None:
        return None
    text = " ".join(str(getattr(quote, "text", "") or "").split())
    if not text or len(text) > QUOTE_MAX:
        return None
    who = verified_quote(workspace, text)
    if who is None:
        return None
    speaker = " ".join(str(getattr(quote, "speaker", "") or "").split())
    if not speaker:
        role = who["role"].split(",")[0].strip()
        speaker = f"{who['speaker']}, {role}" if role else who["speaker"]
    return {"text": f"“{text.strip(chr(34))}”",
            "attribution": speaker[:ATTRIBUTION_MAX],
            "source": _event_words(who["event"], who["date"])[:SOURCE_MAX]}


def quote_findings(script, workspace: Path | None) -> list:
    """Warnings for a quote said to be management's that is not in the call."""
    from pipeline.gates import Finding

    pack = load(workspace)
    if not pack or not (pack.get("call") or {}).get("turns"):
        return []
    out = []
    q = getattr(script, "call_quote", None)
    if q is not None and str(getattr(q, "text", "") or "").strip():
        text = " ".join(str(q.text).split())
        if len(text) > QUOTE_MAX:
            out.append(Finding("call-quote", "warn",
                               f"`call_quote` runs {len(text)} characters; the "
                               f"card holds {QUOTE_MAX}, so it is not drawn. "
                               f"Take a shorter stretch of the same passage.",
                               excerpt=text[:90]))
        elif verified_quote(workspace, text) is None:
            out.append(Finding("call-quote", "warn",
                               "`call_quote` is not in the call word for word, "
                               "so the quote card is not drawn. Copy it from "
                               "the passages exactly, or leave it out.",
                               excerpt=text[:90]))
    tagged = [*(getattr(script, "events", None) or []),
              *(getattr(script, "inline_events", None) or [])]
    for e in tagged:
        payload = str(getattr(e, "payload", "") or "")
        if not payload.strip().startswith("quote-pull"):
            continue
        fields = {str(k).strip(): str(v) for k, v in
                  (getattr(e, "values", None) or {}).items()}
        if not fields:
            fields = dict(part.split("=", 1) for part in
                          (p.strip() for p in payload.split("|")[1:]) if "=" in part)
        src = (fields.get("source", "") + " " + fields.get("attribution", "")).lower()
        body = fields.get("body", "")
        if body and "call" in src and verified_quote(workspace, body) is None:
            out.append(Finding("call-quote", "warn",
                               "a quote card says it is from the call but its "
                               "words are not in the call word for word.",
                               excerpt=body[:90]))
    return out


# --------------------------------------------------------------------------
# The workbook, checked against the site (7).
# --------------------------------------------------------------------------

_LABEL = re.compile(r"(?i)^Q([1-4])\s+FY?(\d{2,4})$")
_QTR_TO = re.compile(r"(?i)^qtr to ([A-Z][a-z]{2}) '(\d{2})$")


def _year(raw: str) -> int:
    y = int(raw)
    return y + 2000 if y < 100 else y


def _site_index(pack: dict) -> dict:
    """(quarter, year) and ("end", month, year) → the site's column."""
    out = {}
    for i, p in enumerate(((pack.get("quarterly") or {}).get("periods")) or []):
        m = re.match(r"(?i)^Q([1-4])\s+(\d{4})$", str(p.get("label") or ""))
        if m:
            out[(int(m.group(1)), int(m.group(2)))] = i
        try:
            end = _dt.date.fromisoformat(str(p.get("end") or ""))
            out[("end", end.month, end.year)] = i
        except ValueError:
            pass
    return out


def _column(label: str, index: dict) -> int | None:
    m = _LABEL.match(str(label or "").strip())
    if m:
        return index.get((int(m.group(1)), _year(m.group(2))))
    m = _QTR_TO.match(str(label or "").strip())
    if m:
        try:
            month = _dt.datetime.strptime(m.group(1), "%b").month
        except ValueError:
            return None
        return index.get(("end", month, _year(m.group(2))))
    return None


def _site_value(pack: dict, field: str, col: int) -> float | None:
    row = ((pack.get("quarterly") or {}).get("rows") or {}).get(QUARTER_ROWS[field])
    if not row or col >= len(row) or row[col] is None:
        return None
    return float(row[col]) * (1.0 if field in _PER_SHARE else 1e6)


def _money(v: float, per_share: bool) -> str:
    sign, v = ("-" if v < 0 else ""), abs(v)
    if per_share:
        return f"{sign}${v:,.2f}"
    for size, unit in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if v >= size:
            return f"{sign}${v / size:,.2f}{unit}"
    return f"{sign}${v:,.0f}"


def _differ(a: float, b: float, field: str) -> bool:
    if field == "capex":
        a, b = abs(a), abs(b)
    gap = abs(a - b)
    if field in _PER_SHARE:
        return gap > 0.02 and gap > 0.03 * max(abs(a), abs(b))
    return gap > 0.5e6 and gap > 0.03 * max(abs(a), abs(b), 1.0)


def cross_check(data, pack: dict | None, last: int = 5) -> list[dict]:
    """Where the workbook's last `last` quarters and the site disagree.

    Each row: quarter, field, both figures as the page prints them."""
    if not pack or data is None or not getattr(data, "quarter_labels", None):
        return []
    index = _site_index(pack)
    labels = list(data.quarter_labels)
    out = []
    for qi in range(max(0, len(labels) - last), len(labels)):
        col = _column(labels[qi], index)
        if col is None:
            continue
        for field in QUARTER_ROWS:
            ours = (data.quarters.get(field) or [None] * len(labels))
            ours = ours[qi] if qi < len(ours) else None
            theirs = _site_value(pack, field, col)
            if ours is None or theirs is None:
                continue
            if _differ(float(ours), theirs, field):
                ps = field in _PER_SHARE
                out.append({"quarter": labels[qi], "field": field,
                            "label": QUARTER_ROWS[field],
                            "workbook": _money(float(ours), ps),
                            "site": _money(theirs, ps)})
    return out


def cross_check_findings(data, workspace: Path | None) -> list:
    from pipeline.gates import Finding

    rows = cross_check(data, load(workspace))
    return [Finding("site-figures", "warn",
                    f"{r['quarter']} {r['label'].lower()}: the workbook says "
                    f"{r['workbook']}, stockanalysis.com says {r['site']}. "
                    f"Check which is right before it goes on screen.")
            for r in rows[:8]]


def apply(data, workspace: Path | None) -> list[str]:
    """What the workbook takes from the pack when it is loaded: the site's
    headlines after the News sheet's, and the blank quarters filled.
    Returns the cells filled."""
    if load(workspace) is None:
        return []
    seen = {" ".join(str(n.get("headline") or "").split()).lower()
            for n in data.news or []}
    for row in news_rows(workspace):
        key = " ".join(row["headline"].split()).lower()
        if key and key not in seen:
            seen.add(key)
            data.news.append(row)
    return fill_quarter_gaps(data, workspace)


def fill_quarter_gaps(data, workspace: Path | None) -> list[str]:
    """Fill the workbook's blank quarter cells from the site, in place.

    Only a cell the workbook left empty, only in a quarter both name the same
    way, only the rows both carry. Returns what was filled, for the page."""
    pack = load(workspace)
    if not pack or data is None or not getattr(data, "quarter_labels", None):
        return []
    index = _site_index(pack)
    labels = list(data.quarter_labels)
    filled = []
    for field in QUARTER_ROWS:
        row = list(data.quarters.get(field) or [None] * len(labels))
        if len(row) < len(labels):
            row += [None] * (len(labels) - len(row))
        changed = False
        for qi, label in enumerate(labels):
            if row[qi] is not None:
                continue
            col = _column(label, index)
            if col is None:
                continue
            v = _site_value(pack, field, col)
            if v is not None:
                row[qi], changed = v, True
                filled.append(f"{label} {QUARTER_ROWS[field].lower()}")
        if changed:
            data.quarters[field] = row
    return filled


# --------------------------------------------------------------------------
# The prompt's words.
# --------------------------------------------------------------------------

def _missing(pack: dict | None, part: str, what: str) -> str:
    if not pack:
        return f"({what}: not read for this video)"
    if pack.get("status") == "off":
        return f"({what}: stockanalysis.com is switched off)"
    why = ((pack.get("parts") or {}).get(part) or {}).get("why") or "not available"
    return f"({what}: {why})"


def _q(text: str) -> str:
    return f"“{text}”"


def call_block(workspace: Path, fmt: str) -> str:
    """{{call_transcript}}: the latest call's summary and passages."""
    pack = load(workspace)
    call = (pack or {}).get("call") or {}
    if not call.get("passages") and not call.get("summary"):
        return _missing(pack, "call", "no earnings-call transcript")
    lines = [f"THE LATEST EARNINGS CALL — {call.get('title', '')}, "
             f"{call.get('date', '')} (the company's own words, from the "
             f"transcript on stockanalysis.com). The bot read it; you do not "
             f"need to search for it."]
    if call.get("summary"):
        lines.append(f"Summary: {call['summary']}")
    if call.get("passages"):
        lines.append(f"Passages that bear on the move, word for word (picked by "
                     f"{call.get('picked_by') or 'keyword scoring'}):")
        for i, p in enumerate(call["passages"], 1):
            role = f" ({p['role']})" if p.get("role") else ""
            lines.append(f"  [{i}] {p['speaker']}{role}: {_q(p['text'])}")
    for e in (pack or {}).get("since_call") or []:
        lines.append(f"Since then: {e.get('title')} ({e.get('date')}): "
                     f"{e.get('summary', '')}")
    lines.append(
        "These are verbatim. Quote them exactly, or say plainly what was said "
        "and who said it (\"on the call, the CFO said…\"). Never put words in "
        "management's mouth that are not here.")
    if fmt == "short":
        lines.append(
            "ON SCREEN: when one of these lines says why it moved better than "
            "any headline, add it to the JSON as `\"call_quote\": {\"text\": "
            f"\"<copied exactly, {QUOTE_MAX} characters at most>\", \"speaker\": "
            "\"<name, title>\"}`. It goes on the quote card over the why beat. "
            "A line that is not in the call word for word is not drawn. "
            "Leave it out when no line earns it.")
    else:
        lines.append(
            "ON SCREEN: a line worth showing goes on the quote card: "
            "`[PLATE: quote-pull-16x9 | body=<the words exactly> | "
            "attribution=<name, title> | source=<quarter> earnings call]`, "
            "where the plate list offers it. The check warns about a card "
            "whose words are not in the call.")
    return "\n".join(lines)


def promises_block(workspace: Path) -> str:
    """{{call_promises}}: what they said a year earlier (said versus did)."""
    pack = load(workspace)
    call = (pack or {}).get("year_ago_call") or {}
    if not call.get("passages"):
        return _missing(pack, "year_ago_call", "no call from a year earlier")
    lines = [f"WHAT THEY SAID A YEAR EARLIER — {call.get('title', '')}, "
             f"{call.get('date', '')}. Promises, targets and timelines, word "
             f"for word. Hold each against what the numbers and the latest "
             f"call show now: this is said-versus-filed material."]
    for i, p in enumerate(call["passages"], 1):
        role = f" ({p['role']})" if p.get("role") else ""
        lines.append(f"  [{i}] {p['speaker']}{role}: {_q(p['text'])}")
    return "\n".join(lines)


def _target(v) -> str:
    return f"${v:,.0f}" if isinstance(v, (int, float)) else "?"


def analysts_block(workspace: Path) -> str:
    """{{analyst_moves}}: the latest rating and target changes."""
    pack = load(workspace)
    a = (pack or {}).get("analysts") or {}
    if not a.get("actions") and not a.get("targets"):
        return _missing(pack, "forecast", "no analyst actions")
    t = a.get("targets") or {}
    lines = ["THE ANALYSTS — latest rating and price-target changes, newest "
             "first (the firms' public actions):"]
    if t:
        lines.append(f"  average target {_target(t.get('average'))} (low "
                     f"{_target(t.get('low'))}, high {_target(t.get('high'))})"
                     + (f"; consensus {a['consensus']}" if a.get("consensus") else ""))
    for x in a.get("actions") or []:
        move = (f"{_target(x['target_from'])} → {_target(x['target_to'])}"
                if x.get("target_from") is not None else _target(x.get("target_to")))
        lines.append(f"  {x.get('date', '')} · {x.get('firm', '')}: "
                     f"{x.get('action', '')} {x.get('rating', '')}, target {move}")
    lines.append("A cluster of cuts or raises right after a report is part of "
                 "why it moved; say it with the firm and the figure.")
    return "\n".join(lines)


def _kpi_value(label: str, v: float | None) -> str:
    if v is None:
        return ""
    low = label.lower()
    if any(w in low for w in ("deliver", "units", "subscribers", "stores",
                              "customers", "employees", "users", "count")):
        return f"{v:,.0f}"
    return _money(v, False)


def kpis_block(workspace: Path) -> str:
    """{{business_kpis}}: the company's own operating figures."""
    pack = load(workspace)
    sections = (pack or {}).get("kpis") or []
    if not sections:
        return _missing(pack, "metrics", "no company KPIs")
    lines = ["THE COMPANY'S OWN KPIs, from its releases. HOW TO READ THEM: a "
             "flow (deliveries, segment revenue) is the TWELVE MONTHS to the "
             "date shown, not the quarter; a balance (backlog) is at that date. "
             "Say \"over the last twelve months\" for a flow, never \"this "
             "quarter\"."]
    for s in sections:
        periods = s.get("periods") or []
        lines.append(f"  {s.get('title', '')} (newest first: "
                     f"{', '.join(periods[:5])}):")
        for label, values in list((s.get("rows") or {}).items())[:6]:
            shown = [_kpi_value(label, v) for v in (values or [])[:5]]
            lines.append(f"    {label}: {' | '.join(x or '-' for x in shown)}")
    return "\n".join(lines)


def company_block(workspace: Path) -> str:
    """{{company_facts}}: who runs it and what it does."""
    pack = load(workspace)
    c = (pack or {}).get("company") or {}
    if not c:
        return _missing(pack, "company", "no company profile")
    facts = c.get("facts") or {}
    lines = ["THE COMPANY — " + "; ".join(f"{k}: {v}" for k, v in facts.items())]
    if c.get("executives"):
        lines.append("  Executives (use these names and titles exactly): "
                     + "; ".join(f"{e['name']}, {e['position']}"
                                 for e in c["executives"][:6]))
    if c.get("description"):
        lines.append(f"  What it does: {c['description'][:700]}")
    return "\n".join(lines)


def coverage_lines(workspace: Path, since: _dt.date | None = None) -> list[str]:
    """The coverage around the move, oldest first, with the minute it ran."""
    pack = load(workspace)
    items = [n for n in (pack or {}).get("news") or []
             if n.get("kind") in ("article", "release")]
    if since is not None:
        items = [n for n in items if str(n.get("date", "")) >= since.isoformat()]
    out = []
    for n in sorted(items, key=lambda n: str(n.get("time", ""))):
        when = str(n.get("time", ""))[:16].replace("T", " ")
        kind = " (press release)" if n.get("kind") == "release" else ""
        line = f"  {when} ET · {n.get('source') or 'source n/a'}{kind} · {n.get('title', '')}"
        if n.get("summary"):
            line += f" — {n['summary'][:220]}"
        out.append(line)
    return out


def news_rows(workspace: Path | None) -> list[dict]:
    """The coverage as News-sheet rows (date, headline, source, url), the
    outlet named, never the site it was listed on."""
    pack = load(workspace)
    return [{"date": n.get("date", ""), "headline": n.get("title", ""),
             "source": n.get("source", ""), "url": n.get("url", "")}
            for n in (pack or {}).get("news") or []
            if n.get("kind") in ("article", "release") and n.get("title")]


def summary(pack: dict | None) -> list[dict]:
    """One row per part for the page: what was read, when, or why not."""
    if not pack:
        return []
    names = {"news": "News and press releases", "statistics": "Earnings date and statistics",
             "quarterly": "Quarterly statements", "metrics": "Company KPIs",
             "forecast": "Analyst actions", "company": "Company profile",
             "calls": "Call list", "call": "Latest earnings call",
             "year_ago_call": "The call a year earlier"}
    out = []
    for key, part in (pack.get("parts") or {}).items():
        what = ""
        if part.get("status") == "ok":
            if key == "news":
                items = pack.get("news") or []
                rel = sum(1 for n in items if n.get("kind") == "release")
                what = f"{len(items)} items, {rel} press release{'s' if rel != 1 else ''}"
            elif key == "statistics":
                e = pack.get("earnings") or {}
                what = (f"{e.get('which', 'last')} earnings {e.get('date')}"
                        + (f", {e['timing']}" if e.get("timing") else "")) if e else "read"
            elif key == "quarterly":
                ps = (pack.get("quarterly") or {}).get("periods") or []
                what = f"{len(ps)} quarters, latest {ps[0]['label']}" if ps else "read"
            elif key == "metrics":
                what = ", ".join(s.get("title", "") for s in pack.get("kpis") or [])
            elif key == "forecast":
                what = f"{len((pack.get('analysts') or {}).get('actions') or [])} recent actions"
            elif key == "company":
                what = f"{len((pack.get('company') or {}).get('executives') or [])} executives"
            elif key in ("call", "year_ago_call"):
                c = pack.get(key) or {}
                what = (f"{c.get('title', '')} ({c.get('date', '')}), "
                        f"{len(c.get('passages') or [])} passages picked by "
                        f"{c.get('picked_by') or '—'}")
            else:
                what = "read"
        out.append({"key": key, "name": names.get(key, key),
                    "status": part.get("status", ""), "what": what,
                    "why": part.get("why", ""), "fetched_at": part.get("fetched_at", ""),
                    "url": part.get("url", "")})
    return out
