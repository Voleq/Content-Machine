"""Counts and totals, answered by code rather than by the model.

A 12B model reading a page is good at saying what the page says. It is bad at
counting forty job records or adding up a month of voice charges, and it is
bad in the worst way: the wrong total reads exactly like the right one. So
`/ask` never lets it do arithmetic.

Two ways in, both computed here from the records the bot already keeps:

* :func:`answer` takes a question that is plainly a count or a total — "how
  many shorts this month", "what did voice cost in August", "what's in the
  queue" — and answers it outright. The model is not called at all.
* :func:`facts` is the handful of headline figures every other `/ask` hands
  the model, with the instruction to copy them rather than work anything out.

The sources are the job records (`state/jobs/`), the video log, the spend
ledger, the thesis book, the idea queue, and the journal for what the local
model did. A figure the journal cannot know yet — it starts on the day it was
installed — says so rather than reading as zero.
"""

from __future__ import annotations

import calendar
import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from config import Settings

# ---------------------------------------------------------------- periods

_MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
_MONTHS.update({name.lower(): i for i, name in enumerate(calendar.month_abbr)
                if name})


@dataclass(frozen=True)
class Period:
    start: date | None
    end: date | None
    label: str

    def contains(self, day: date | None) -> bool:
        if day is None:
            return False
        if self.start and day < self.start:
            return False
        if self.end and day > self.end:
            return False
        return True


ALL_TIME = Period(None, None, "all time")


def _month(year: int, month: int, label: str = "") -> Period:
    last = calendar.monthrange(year, month)[1]
    return Period(date(year, month, 1), date(year, month, last),
                  label or f"{calendar.month_name[month]} {year}")


def parse_period(text: str, today: date | None = None) -> Period | None:
    """The period a question names, or None when it names none."""
    today = today or date.today()
    t = text.lower()
    if re.search(r"\btoday\b", t):
        return Period(today, today, "today")
    if re.search(r"\byesterday\b", t):
        day = today - timedelta(days=1)
        return Period(day, day, "yesterday")
    m = re.search(r"\b(?:last|past) (\d{1,3}) days\b", t)
    if m:
        return Period(today - timedelta(days=int(m.group(1)) - 1), today,
                      f"the last {m.group(1)} days")
    monday = today - timedelta(days=today.weekday())
    if re.search(r"\bthis week\b", t):
        return Period(monday, today, "this week")
    if re.search(r"\blast week\b", t):
        return Period(monday - timedelta(days=7), monday - timedelta(days=1),
                      "last week")
    if re.search(r"\bthis month\b", t):
        return Period(today.replace(day=1), today, "this month")
    if re.search(r"\blast month\b", t):
        prev = today.replace(day=1) - timedelta(days=1)
        return _month(prev.year, prev.month)
    if re.search(r"\bthis year\b", t):
        return Period(date(today.year, 1, 1), today, f"{today.year}")
    if re.search(r"\blast year\b", t):
        y = today.year - 1
        return Period(date(y, 1, 1), date(y, 12, 31), f"{y}")
    m = re.search(r"\b(20\d\d)-(0[1-9]|1[0-2])\b", t)
    if m:
        return _month(int(m.group(1)), int(m.group(2)))
    # A month name. "may" only counts after a preposition or before a year,
    # because "how many may still render" is not a question about May.
    names = "|".join(sorted(_MONTHS, key=len, reverse=True))
    for m in re.finditer(
            rf"\b(in|during|for|of|since|from)?\s*\b({names})\b\.?(?:\s+(20\d\d))?",
            t):
        prep, name, year = m.group(1), m.group(2), m.group(3)
        if name == "may" and not (prep or year):
            continue
        month = _MONTHS[name]
        y = int(year) if year else (today.year if month <= today.month
                                    else today.year - 1)
        return _month(y, month)
    m = re.search(r"\b(?:in|during|for) (20\d\d)\b", t)
    if m:
        y = int(m.group(1))
        return Period(date(y, 1, 1), date(y, 12, 31), f"{y}")
    return None


def _local_day(stamp: str) -> date | None:
    """An ISO timestamp as a local date. Workspace dates are cut on the
    machine's clock, so this is the clock "this month" means."""
    if not stamp:
        return None
    try:
        when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        try:
            return date.fromisoformat(stamp[:10])
        except ValueError:
            return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone().date()


# ---------------------------------------------------------------- records

# What counts as a finished video, by job kind. Proofs and drafts are looks
# at a video, not videos, and are counted apart.
_FINISHED = {"render_short": "short", "render_long": "long",
             "repurpose": "clip"}
_PREVIEWS = {"render_proof_short": "proof", "render_proof_long": "proof",
             "render_draft_long": "draft"}


def _jobs(settings: Settings) -> list:
    from pipeline.jobs import JobStore

    return JobStore(settings).all()


def finished_videos(settings: Settings, period: Period = ALL_TIME, *,
                    ticker: str = "", previews: bool = False) -> list:
    """Jobs that finished inside the period, dated by when they finished."""
    kinds = _PREVIEWS if previews else _FINISHED
    out = []
    for job in _jobs(settings):
        if job.status.value != "done" or job.kind.value not in kinds:
            continue
        if ticker and job.ticker != ticker.upper():
            continue
        if period.contains(_local_day(job.updated_at)):
            out.append(job)
    return sorted(out, key=lambda j: j.updated_at)


def uploads(settings: Settings, period: Period = ALL_TIME, *,
            ticker: str = "") -> list:
    from pipeline.youtube import VideoLog

    out = []
    for video in VideoLog(settings).all():
        if ticker and video.ticker != ticker.upper():
            continue
        if period.contains(_local_day(video.uploaded_at)):
            out.append(video)
    return sorted(out, key=lambda v: v.uploaded_at)


def _spend_data(settings: Settings) -> dict:
    try:
        data = json.loads((settings.state_dir / "spend.json")
                          .read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def spend(settings: Settings, period: Period, *,
          today: date | None = None) -> list[tuple[str, float, float, int]]:
    """`(month label, voice usd, filing-AI usd, pexels calls)` per month the
    period touches. A month the period covers whole reads the ledger's own
    total; a part-month adds up that month's events inside the period."""
    today = today or date.today()
    data = _spend_data(settings)
    rows = []
    for key in sorted(k for k in data if re.fullmatch(r"\d{4}-\d{2}", k)):
        year, month = int(key[:4]), int(key[5:])
        whole = _month(year, month)
        if period.start and whole.end < period.start:
            continue
        if period.end and whole.start > period.end:
            continue
        month_data = data[key] if isinstance(data[key], dict) else {}
        covers = ((not period.start or period.start <= whole.start)
                  and (not period.end or period.end >= min(whole.end, today)))
        if covers:
            voice = float(month_data.get("tts_usd") or 0.0)
            ai = float(month_data.get("llm_usd") or 0.0)
            pexels = int(month_data.get("pexels_calls") or 0)
        else:
            voice = sum(float(e.get("usd") or 0.0)
                        for e in month_data.get("events") or []
                        if period.contains(_local_day(str(e.get("at") or ""))))
            ai, pexels = 0.0, 0
        rows.append((whole.label, round(voice, 2), round(ai, 2), pexels))
    return rows


def ai_calls(settings: Settings, period: Period = ALL_TIME, *,
             ticker: str = "") -> dict:
    """What the model did, from the journal: answered locally, answered by a
    hosted fallback, did not run — and by which pass."""
    from pipeline import journal
    from pipeline.llm import OK, OLLAMA

    rows = journal.entries(settings, kinds=("ai",), ticker=ticker,
                           since=period.start, until=period.end)
    local = hosted = 0
    missed: Counter = Counter()
    by_purpose: Counter = Counter()
    for e in rows:
        if e.data.get("reason") == OK:
            if e.data.get("provider") == OLLAMA:
                local += 1
            else:
                hosted += 1
            by_purpose[str(e.data.get("purpose") or "llm")] += 1
        else:
            missed[str(e.data.get("reason") or "unknown")] += 1
    first = journal.entries(settings, limit=0)
    return {"local": local, "hosted": hosted, "missed": missed,
            "by_purpose": by_purpose,
            "journal_since": first[0].local_date() if first else None}


def queue(settings: Settings) -> dict[str, list]:
    running, queued = [], []
    for job in _jobs(settings):
        if job.status.value == "running":
            running.append(job)
        elif job.status.value == "queued":
            queued.append(job)
    try:
        from pipeline.standing import BatchQueue

        batch = BatchQueue(settings).pending()
    except Exception:  # noqa: BLE001 — a missing batch file is an empty one
        batch = []
    return {"running": running, "queued": queued, "batch": batch}


def theses(settings: Settings) -> dict[str, list[str]]:
    from pipeline.standing import ThesisBook

    book = ThesisBook(settings)
    out: dict[str, list[str]] = {"intact": [], "cracking": [], "broken": []}
    for ticker in book.tickers():
        thesis = book.get(ticker)
        if thesis is not None:
            out.setdefault(thesis.status, []).append(ticker)
    return out


def ideas(settings: Settings) -> list:
    from pipeline.standing import IdeaQueue

    return IdeaQueue(settings).ranked(limit=1000)


# ---------------------------------------------------------------- words

def _plural(n: int, word: str, many: str = "") -> str:
    return f"{n} {word if n == 1 else (many or word + 's')}"


def _split(jobs: list) -> Counter:
    return Counter(_FINISHED.get(j.kind.value) or _PREVIEWS.get(j.kind.value)
                   for j in jobs)


def _video_lines(settings: Settings, period: Period, ticker: str,
                 question: str) -> list[str]:
    done = finished_videos(settings, period, ticker=ticker)
    kinds = _split(done)
    who = f" for {ticker}" if ticker else ""
    lines = [f"Videos finished{who}, {period.label}: {len(done)} "
             f"({_plural(kinds['short'], 'short')}, "
             f"{_plural(kinds['long'], 'long')}, "
             f"{_plural(kinds['clip'], 'clip')})."]
    for job in done[-12:]:
        lines.append(f"  {job.ticker} {_FINISHED[job.kind.value]} · "
                     f"{_local_day(job.updated_at)}")
    if len(done) > 12:
        lines.append(f"  … and {len(done) - 12} earlier")
    if re.search(r"\b(proofs?|drafts?|previews?)\b", question.lower()):
        looks = _split(finished_videos(settings, period, ticker=ticker,
                                       previews=True))
        lines.append(f"Looks rendered in that time: "
                     f"{_plural(looks['proof'], 'proof')}, "
                     f"{_plural(looks['draft'], 'draft')}.")
    up = uploads(settings, period, ticker=ticker)
    lines.append(f"Uploaded to YouTube in that time: {len(up)}.")
    return lines


def _spend_lines(settings: Settings, period: Period,
                 today: date) -> list[str]:
    rows = spend(settings, period, today=today)
    cap = settings.monthly_spend_cap_usd
    if not rows:
        return [f"No spend is recorded for {period.label}. "
                f"The monthly voice cap is ${cap:.2f}."]
    lines = []
    for label, voice, ai, pexels in rows:
        lines.append(f"{label}: voice ${voice:.2f} of the ${cap:.2f} monthly "
                     f"cap · filing AI ${ai:.2f} · {_plural(pexels, 'Pexels call')}")
    if len(rows) > 1:
        lines.append(f"Voice total, {period.label}: "
                     f"${sum(r[1] for r in rows):.2f}.")
    lines.append("These are what Dennis believes it spent; /cost says when "
                 "they were last checked against the provider.")
    return lines


def _ai_lines(settings: Settings, period: Period, ticker: str) -> list[str]:
    calls = ai_calls(settings, period, ticker=ticker)
    missed = calls["missed"]
    lines = [f"The model's passes, {period.label}: {calls['local']} answered "
             f"locally, {calls['hosted']} went to a hosted model, "
             f"{sum(missed.values())} did not run."]
    if missed:
        lines.append("  Did not run: " + ", ".join(
            f"{reason} {n}" for reason, n in missed.most_common()))
    if calls["by_purpose"]:
        lines.append("  By pass: " + ", ".join(
            f"{p} {n}" for p, n in calls["by_purpose"].most_common(6)))
    since = calls["journal_since"]
    if since is None:
        lines.append("The journal has no entries yet, so there is nothing to "
                     "count.")
    elif period.start is None or period.start < since:
        lines.append(f"The journal starts on {since}; nothing before that "
                     f"was recorded.")
    return lines


def _queue_lines(settings: Settings) -> list[str]:
    q = queue(settings)
    lines = [f"Right now: {_plural(len(q['running']), 'job')} running, "
             f"{len(q['queued'])} queued, "
             f"{_plural(len(q['batch']), 'render')} waiting for the "
             f"overnight batch."]
    for label, jobs in (("running", q["running"]), ("queued", q["queued"])):
        for job in jobs:
            lines.append(f"  {label}: {job.ticker} {job.kind.value}")
    for item in q["batch"]:
        lines.append(f"  batch: {item.ticker} {item.fmt}")
    return lines


def _thesis_lines(settings: Settings) -> list[str]:
    book = theses(settings)
    total = sum(len(v) for v in book.values())
    lines = [f"Theses on file: {total} — "
             + ", ".join(f"{len(book.get(s, []))} {s}"
                         for s in ("intact", "cracking", "broken")) + "."]
    for status in ("broken", "cracking", "intact"):
        if book.get(status):
            lines.append(f"  {status}: {', '.join(sorted(book[status]))}")
    return lines


def _idea_lines(settings: Settings) -> list[str]:
    backlog = ideas(settings)
    lines = [f"Ideas in the backlog: {len(backlog)}."]
    for idea in backlog[:5]:
        lines.append(f"  {idea.render()}")
    return lines


# ---------------------------------------------------------------- routing

_COUNTING = re.compile(r"\bhow (many|much|often)\b|\bcount\b|\bnumber of\b|"
                       r"\btotal\b|\bsum\b")
_TOPICS: list[tuple[str, re.Pattern]] = [
    ("spend", re.compile(r"\b(spen[dt]|spending|costs?|cost me|money|budget|"
                         r"bill|dollars?|paid|pay|elevenlabs|pexels)\b|\$")),
    ("ai", re.compile(r"\b(ai|llm|model|gemma|ollama|passes|fallbacks?|"
                      r"hosted)\b")),
    ("queue", re.compile(r"\b(queue|queued|running|rendering|in progress|"
                         r"pending|batch)\b")),
    ("videos", re.compile(r"\b(videos?|shorts?|longs?|clips?|renders?|"
                          r"rendered|made|make|shipped|finished|published|"
                          r"uploads?|uploaded|proofs?|drafts?)\b")),
    ("theses", re.compile(r"\b(thes[ie]s|broken|cracking|intact)\b")),
    ("ideas", re.compile(r"\b(ideas?|backlog)\b")),
]
# Asked without a counting word and still a question for code: nobody
# wants the model's reading of what is in the queue.
_ALWAYS = {"queue"}


def route(question: str) -> str:
    """The topic code should answer, or "" when this is the model's."""
    t = question.lower()
    counting = bool(_COUNTING.search(t))
    for topic, pattern in _TOPICS:
        if pattern.search(t) and (counting or topic in _ALWAYS):
            return topic
    return ""


def answer(settings: Settings, question: str, *, ticker: str = "",
           today: date | None = None) -> str | None:
    """The answer, when the question is one code should answer."""
    today = today or date.today()
    topic = route(question)
    if not topic:
        return None
    period = parse_period(question, today) or ALL_TIME
    if topic == "spend":
        lines = _spend_lines(settings, period, today)
    elif topic == "ai":
        lines = _ai_lines(settings, period, ticker)
    elif topic == "videos":
        lines = _video_lines(settings, period, ticker, question)
    elif topic == "queue":
        lines = _queue_lines(settings)
    elif topic == "theses":
        lines = _thesis_lines(settings)
    else:
        lines = _idea_lines(settings)
    return "\n".join(lines)


def facts(settings: Settings, *, today: date | None = None) -> list[str]:
    """The headline figures handed to the model with every question."""
    today = today or date.today()
    month = Period(today.replace(day=1), today, "this month")
    out = [f"Today is {today.isoformat()}."]
    for section in (
            lambda: _video_lines(settings, month, "", "")[:1],
            lambda: _video_lines(settings, ALL_TIME, "", "")[:1],
            lambda: _spend_lines(settings, month, today)[:1],
            lambda: _queue_lines(settings)[:1],
            lambda: _thesis_lines(settings)[:1],
            lambda: _idea_lines(settings)[:1],
            lambda: _ai_lines(settings, month, "")[:1]):
        try:
            out.extend(section())
        except Exception:  # noqa: BLE001 — one unreadable record, one line fewer
            continue
    out.append("MOCK_MODE is " + ("ON: nothing real is fetched or paid for."
                                  if settings.mock_mode else "off."))
    return out
