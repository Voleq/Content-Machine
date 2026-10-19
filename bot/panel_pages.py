"""The page's screens that are not one video: Ideas, Calendar, Stats.

Like `bot/panel_views.py`, read-only. Each reads what the bot already keeps
(the idea queue, the last screener run, the watch list and earnings dates,
the upload log, the retention evidence) through the functions the commands
print from, and the page acts through commands: `/ideas add`, `/new short`,
`/publish TICKER@DATE short YYYY-MM-DD HH:MM`, and so on.

A section that cannot be read comes back as `{"error": …}` on its own.
"""

from __future__ import annotations

import calendar as _cal
import json
import logging
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone

log = logging.getLogger(__name__)


def _guard(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception as e:                           # noqa: BLE001
        log.exception("panel page section %s", getattr(fn, "__name__", fn))
        return {"error": f"{type(e).__name__}: {e}"}


# --------------------------------------------------------------------------
# Ideas
# --------------------------------------------------------------------------

def _backlog(settings) -> list[dict]:
    from pipeline.standing import IdeaQueue

    return [{"ticker": i.ticker, "reason": i.reason, "source": i.source,
             "score": round(i.score, 2), "lane": i.lane,
             "added_at": i.added_at}
            for i in IdeaQueue(settings).ranked(limit=60)]


def _last_screen(settings) -> dict:
    path = settings.state_dir / "last_screen.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"ts": None, "rows": []}
    rows = [{"ticker": t, "lane": e.get("lane", ""),
             "reasons": list(e.get("reasons") or []),
             "price": e.get("price"), "pct_change": e.get("pct_change")}
            for t, e in (data.get("tickers") or {}).items()]
    rows.sort(key=lambda r: (r["lane"], -abs(r["pct_change"] or 0)))
    return {"ts": data.get("ts"), "rows": rows}


def _earnings(settings) -> list[dict]:
    from pipeline.alerts import EarningsCalendar

    cal = EarningsCalendar(settings)
    since = (date.today() - timedelta(days=3)).isoformat()
    rows = []
    for ticker in cal._all():
        e = cal.get(ticker)
        if e is not None and e.date >= since:
            rows.append({"ticker": e.ticker, "date": e.date, "when": e.when})
    return sorted(rows, key=lambda r: r["date"])


def ideas_view(panel) -> dict:
    from pipeline.alerts import Watchlist

    s = panel.settings
    return {"backlog": _guard(_backlog, s), "screen": _guard(_last_screen, s),
            "watch": _guard(lambda: Watchlist(s).all()),
            "earnings": _guard(_earnings, s)}


# --------------------------------------------------------------------------
# Calendar
# --------------------------------------------------------------------------

def _instant(iso: str) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def calendar_view(panel, month: str = "", now: datetime | None = None) -> dict:
    """One month of what went out and what is scheduled, the days with
    nothing marked, and the finished videos not yet uploaded that a free
    day could take."""
    from zoneinfo import ZoneInfo

    from pipeline.video_state import all_states
    from pipeline.youtube import (VideoLog, public_since, record_format,
                                  still_scheduled)

    s = panel.settings
    now = now or datetime.now(timezone.utc)
    try:
        tz = ZoneInfo(s.publish_timezone)
    except Exception:                                 # noqa: BLE001
        tz = timezone.utc
    local_now = now.astimezone(tz)
    try:
        year, mon = (int(x) for x in month.split("-")) if month else (
            local_now.year, local_now.month)
        first = date(year, mon, 1)
    except ValueError:
        first = date(local_now.year, local_now.month, 1)
    days_in = _cal.monthrange(first.year, first.month)[1]
    last = first.replace(day=days_in)

    by_day: dict[str, list[dict]] = {}
    for v in VideoLog(s).all():
        t = _instant(public_since(v))
        if t is None:
            continue
        day = t.astimezone(tz).date()
        if not first <= day <= last:
            continue
        by_day.setdefault(day.isoformat(), []).append({
            "ticker": v.ticker, "title": v.title, "url": v.url(),
            "fmt": record_format(v), "privacy": v.privacy,
            "pending": still_scheduled(v, now), "workdate": v.workdate,
            "time": t.astimezone(tz).strftime("%H:%M")})
    today = local_now.date()
    days = []
    for d in range(1, days_in + 1):
        day = first.replace(day=d)
        items = sorted(by_day.get(day.isoformat(), []), key=lambda r: r["time"])
        days.append({"date": day.isoformat(), "weekday": day.weekday(),
                     "items": items, "past": day < today,
                     "gap": not items and day >= today})
    ready = []
    states = _guard(all_states, s, days=30)
    for st in states if isinstance(states, list) else []:
        if "final" in st.renders and st.uploaded is None and st.fmt in ("short", "long"):
            ready.append({"ticker": st.ticker, "workdate": st.workdate,
                          "fmt": st.fmt})
    prev = (first - timedelta(days=1)).strftime("%Y-%m")
    nxt = (last + timedelta(days=1)).strftime("%Y-%m")
    return {"month": first.strftime("%Y-%m"), "title": first.strftime("%B %Y"),
            "today": today.isoformat(), "prev": prev, "next": nxt,
            "days": days, "ready": ready,
            "error": states.get("error") if isinstance(states, dict) else None,
            "publish_hour": int(getattr(s, "publish_hour", 17)),
            "timezone": str(s.publish_timezone)}


# --------------------------------------------------------------------------
# Stats
# --------------------------------------------------------------------------

def _hooks(s) -> dict:
    from pipeline.retention_lines import hook_bench, hook_bench_text

    return {fmt: {"rows": [asdict(h) for h in hook_bench(s, fmt=fmt)],
                  "text": hook_bench_text(s, fmt=fmt)}
            for fmt in ("short", "long")}


def _rules(s) -> dict:
    from pipeline.retention_lines import rule_evidence, rule_evidence_text

    return {"rows": [dict(asdict(r), points=round(r.points, 2), verdict=r.verdict)
                     for r in rule_evidence(s)],
            "text": rule_evidence_text(s)}


def _runtime(s) -> dict:
    from pipeline.retention_lines import runtime_evidence, runtime_evidence_text

    return {"rows": [asdict(b) for b in runtime_evidence(s)],
            "text": runtime_evidence_text(s)}


def _chapters(s) -> dict:
    from pipeline.youtube import chapter_type_evidence

    return {"rows": chapter_type_evidence(s)}


def _experiments(s) -> dict:
    from pipeline.experiments import experiments, experiments_text

    return {"rows": [{"pair": e.pair,
                      "arms": [asdict(a) for a in e.arms],
                      "winner": (e.winner.title if e.winner else "")}
                     for e in experiments(s)],
            "text": experiments_text(s)}


def _scoreboard(s) -> dict:
    from pipeline.scoreboard import build

    board = build(s)
    return {"quarter": board.quarter, "headline": board.headline(),
            "counts": board.counts, "rows": [dict(asdict(r), verdict=r.verdict) for r in board.rows],
            "text": board.render_text()}


def stats_view(panel) -> dict:
    s = panel.settings
    return {"hooks": _guard(_hooks, s), "rules": _guard(_rules, s),
            "runtime": _guard(_runtime, s), "chapters": _guard(_chapters, s),
            "experiments": _guard(_experiments, s),
            "scoreboard": _guard(_scoreboard, s)}
