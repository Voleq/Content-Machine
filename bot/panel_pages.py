"""The page's screens that are not one video: Ideas, Calendar, Stats,
Library and Settings.

Like `bot/panel_views.py`, read-only. Each reads what the bot already keeps
(the idea queue, the last screener run, the watch list and earnings dates,
the upload log, the retention evidence) through the functions the commands
print from, and the page acts through commands: `/ideas add`, `/new short`,
`/publish TICKER@DATE short YYYY-MM-DD HH:MM`, and so on, or through the
`BotCore` method a command would call (`set_switch`, `save_writing`,
`edit_memory`) where no command fits a page edit.

A section that cannot be read comes back as `{"error": …}` on its own.
"""

from __future__ import annotations

import calendar as _cal
import json
import logging
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

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


# --------------------------------------------------------------------------
# Library
# --------------------------------------------------------------------------

_IMAGES = (".png", ".jpg", ".jpeg", ".webp", ".gif")
_VIDEOS = (".mp4", ".mov", ".mkv", ".webm")
THUMB_DIR = "panel_thumbs"


def _link(panel, path) -> str:
    """A served file's link, without the key (the page adds it)."""
    from urllib.parse import quote

    return f"/api/file?path={quote(str(path))}" if panel.allowed(Path(path)) else ""


def _thumb(panel, path, w: int = 360) -> str:
    from urllib.parse import quote

    return (f"/api/thumb?path={quote(str(path))}&w={w}"
            if panel.allowed(Path(path)) else "")


def thumbnail(panel, raw_path: str, width: int = 360) -> Path | None:
    """A small JPEG of a served picture, drawn once per file version into the
    cache, so a grid of 4K room renders loads as a few hundred kilobytes."""
    import hashlib

    path = Path(raw_path)
    if not raw_path or not panel.allowed(path) or path.suffix.lower() not in _IMAGES:
        return None
    real = path.resolve()
    st = real.stat()
    width = max(80, min(int(width), 800))
    key = hashlib.sha1(f"{real}|{st.st_mtime_ns}|{st.st_size}|{width}"
                       .encode("utf-8")).hexdigest()[:24]
    out = Path(panel.settings.cache_dir) / THUMB_DIR / f"{key}.jpg"
    if out.is_file():
        return out
    from PIL import Image

    out.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(real) as im:
        im = im.convert("RGBA")
        ground = Image.new("RGBA", im.size, (255, 255, 255, 255))
        ground.alpha_composite(im)
        small = ground.convert("RGB")
        small.thumbnail((width, width * 4))
        tmp = out.with_suffix(".part.jpg")
        small.save(tmp, "JPEG", quality=80)
        tmp.replace(out)
    return out


def _writing(panel) -> list[dict]:
    from pipeline import writing_files as wf

    s = panel.settings
    return [{"name": n, "title": wf.TITLES.get(n, n), "text": wf.read_file(s, n),
             "edited": wf.is_edited(s, n)} for n in wf.WRITING_FILES]


def _book(panel, which: str) -> list[dict]:
    from pipeline.channel_memory import FactBook, JokeBook

    book = (FactBook if which == "facts" else JokeBook)(panel.settings)
    return [{"text": r.text, "ticker": r.ticker, "workdate": r.workdate}
            for r in book.all()]


def _bits(panel) -> dict:
    from pipeline.recurring_bits import BITS, NAMES, BitLedger, due_bit

    s = panel.settings
    led = BitLedger(s)
    return {"due": NAMES.get(due_bit(s), ""),
            "bits": [{"bit": b, "name": NAMES.get(b, b), "since": led.since(b),
                      "gap": led.gap_for(b), "overdue": led.overdue(b)} for b in BITS],
            "recent": [{"ticker": r.get("ticker", ""), "workdate": r.get("workdate", ""),
                        "bit": NAMES.get(r.get("bit") or "", "")}
                       for r in led.rows()[-8:]][::-1]}


def _memes(panel) -> dict:
    from pipeline.memes import MemeLibrary, recent_memes

    s = panel.settings
    lib = MemeLibrary(s)
    index = lib.index()
    try:
        recent = recent_memes(s)
    except Exception:                                 # noqa: BLE001
        recent = set()
    rows, seen = [], set()
    for stem in sorted(index):
        f = lib._file_for(stem)
        seen.add(f.name if f else "")
        e = index[stem] or {}
        rows.append({"stem": stem, "tags": list(e.get("tags") or []),
                     "use_when": str(e.get("use_when") or ""),
                     "file": _link(panel, f) if f else "",
                     "thumb": _thumb(panel, f, 320) if f else "",
                     "recent": stem in recent})
    unlabelled = [p.name for p in sorted(lib.dir.glob("*"))
                  if p.suffix.lower() in _IMAGES and p.name not in seen] \
        if lib.dir.is_dir() else []
    return {"rows": rows, "unlabelled": unlabelled}


def _broll(panel) -> dict:
    from pipeline.broll import PALETTE

    lib = Path(panel.settings.assets_dir) / "broll_library"
    clips = [{"name": p.name, "key": p.stem.split("__")[0], "file": _link(panel, p)}
             for p in sorted(lib.glob("*")) if p.suffix.lower() in _VIDEOS] \
        if lib.is_dir() else []
    owned = {c["key"] for c in clips}
    return {"clips": clips, "keys": len(PALETTE),
            "without": sorted(k for k in PALETTE if k not in owned)}


def _sounds(panel) -> list[dict]:
    from pipeline.audio_assets import AUDIO_DIRS, AUDIO_SUFFIXES, load_sources

    out = []
    for sub in AUDIO_DIRS:
        d = Path(panel.settings.assets_dir) / sub
        if not d.is_dir():
            continue
        known = load_sources(d)
        for p in sorted(d.iterdir()):
            if p.suffix.lower() not in AUDIO_SUFFIXES:
                continue
            e = known.get(p.name)
            out.append({"dir": sub, "name": p.name, "file": _link(panel, p),
                        "source": e.source if e else "", "licence": e.licence if e else "",
                        "author": e.author if e else "",
                        "placeholder": e is None or e.generated})
    return out


def _rooms(panel) -> list[dict]:
    from pipeline.plates import load_plates

    reg = load_plates(panel.settings.assets_dir)
    out = []
    for key, p in sorted(reg.assets.items()):
        if p.family != "room" or not p.files_png:
            continue
        f = Path(p.root) / "room" / p.files_png
        out.append({"key": key.split("/", 1)[-1], "aspect": p.aspect,
                    "hour": p.hour or "", "season": p.season or "",
                    "purpose": p.purpose or "", "file": _link(panel, f),
                    "thumb": _thumb(panel, f, 360)})
    return out


def library_view(panel) -> dict:
    return {"writing": _guard(_writing, panel),
            "facts": _guard(_book, panel, "facts"),
            "jokes": _guard(_book, panel, "jokes"),
            "bits": _guard(_bits, panel), "memes": _guard(_memes, panel),
            "broll": _guard(_broll, panel), "sounds": _guard(_sounds, panel),
            "rooms": _guard(_rooms, panel)}


# --------------------------------------------------------------------------
# Settings and health
# --------------------------------------------------------------------------

def _preflight(panel) -> list[dict]:
    """The machine-checkable half of `scripts/check_preflight.py`, row by
    row; the test suite row is left out (it is a 25-minute run)."""
    import importlib.util

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "_preflight_for_panel", root / "scripts" / "check_preflight.py")
    pre = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pre)
    s = panel.settings
    live = not s.mock_mode
    report = pre.Report()
    checks = [(pre._kit, ()), (pre._sfx, ()), (pre._sec_agent, (live,)),
              (pre._voice, (live,)), (pre._dennis_3d, (live,)), (pre._broll, ()),
              (pre._delivery, (live,)), (pre._publish_window, ()),
              (pre._state_backup, ())]
    for fn, extra in checks:
        try:
            fn(s, report, *extra)
        except Exception as e:                        # noqa: BLE001
            report.add(pre.FAIL, fn.__name__.strip("_").replace("_", " "),
                       f"the check itself failed: {type(e).__name__}: {e}")
    state = {pre.PASS: "ok", pre.FAIL: "bad", pre.SKIP: "skip"}
    return [{"state": state.get(st, st), "name": n, "detail": d}
            for st, n, d in report.rows]


def _disk(panel) -> list[dict]:
    import shutil

    s = panel.settings
    out = []
    for label, path in (("workspace", s.workspace_dir), ("cache", s.cache_dir)):
        try:
            u = shutil.disk_usage(path)
        except OSError:
            continue
        out.append({"name": label, "path": str(path), "free_gb": round(u.free / 1e9, 1),
                    "total_gb": round(u.total / 1e9, 1)})
    return out


def _failures(panel) -> list[dict]:
    from pipeline.jobs import JobStore

    store = panel.core.queue.store if getattr(panel.core, "queue", None) else JobStore(panel.settings)
    failed = [j for j in store.all() if str(getattr(j.status, "value", j.status)) == "failed"]
    failed.sort(key=lambda j: j.updated_at, reverse=True)
    return [{"id": j.id, "kind": str(getattr(j.kind, "value", j.kind)), "ticker": j.ticker,
             "workdate": j.workdate, "at": j.updated_at, "error": j.error[:400]}
            for j in failed[:8]]


def settings_view(panel) -> dict:
    from bot.commands import NotifyPrefs
    from pipeline.switches import rows

    s = panel.settings
    mode = (s.dennis_3d or "off").strip().lower()
    return {"switches": _guard(rows, s),
            "quiet": _guard(lambda: NotifyPrefs(s).level() == "quiet"),
            "dennis_3d": mode,
            "dennis_3d_warning": "" if mode == "on" else (
                f"DENNIS_3D is {mode}: renders draw the old 2D Dennis. Set "
                f"DENNIS_3D=on in .env once `room3d/perform.py --bench` runs."),
            "mock": s.mock_banner(),
            "health": _guard(_preflight, panel), "disk": _guard(_disk, panel),
            "failures": _guard(_failures, panel)}
