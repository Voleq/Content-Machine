"""What state one video is in, read off its workspace folder.

One reader for every place that shows it: the Telegram video card
(`/card`), the morning inbox (`/inbox`) and the web panel. They used to be
three different questions answered by three different commands — `/status`
for the queue, `/script` for the approval, `/scheduled` for the upload — and
nothing put them side by side.

Pure reads. Nothing here writes, spends, fetches or calls a model, so it is
safe to call on every refresh of the card and every poll of the panel.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from config import Settings
from pipeline.workspace import Workspace, today_str

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Render outputs, by what they are. A proof never overwrites a final and a
# draft is LONG-only, so each has a name of its own.
RENDER_FILES = {
    "short": {"final": "short_final.mp4", "proof": "short_proof.mp4"},
    "long": {"final": "long_final.mp4", "proof": "long_proof.mp4",
             "draft": "long_draft.mp4"},
}
THUMBNAILS = ("thumbnail.png", "thumbnail_short.png", "thumbnail_tall.png")
ACTIVE_JOB_STATES = ("queued", "running")
# How long after an upload YouTube has enough views for retention to mean
# anything. The card offers the button before then and says "too early".
RETENTION_READY_H = 48


@dataclass
class VideoState:
    ticker: str
    workdate: str
    lane: str = ""                 # short | long | ""
    update: bool = False           # a LONG grading an earlier call
    fmt: str = ""                  # the format the lane renders
    data_file: str = ""            # dennis_data.xlsx / .csv, if uploaded
    data_as_of: str = ""
    awaiting_angle: bool = False
    angle: str = ""
    script: bool = False
    script_chars: int = 0
    script_lines: int = 0
    revisions: int = 0
    sha8: str = ""
    report: bool = False
    report_ok: bool | None = None  # None: no report on file
    warnings: int = 0
    blocking: int = 0
    blockers: list[str] = field(default_factory=list)
    est_usd: float | None = None   # the TTS estimate the report priced
    tts_cached: bool = False
    est_render_min: float | None = None
    est_runtime_min: float | None = None
    approved: bool = False
    renders: dict[str, str] = field(default_factory=dict)   # kind -> path
    clips: list[str] = field(default_factory=list)
    thumbnails: list[str] = field(default_factory=list)
    jobs: list[dict] = field(default_factory=list)
    uploads: list[dict] = field(default_factory=list)
    why: str = ""

    # ---------------------------------------------------------- derived
    @property
    def key(self) -> str:
        return f"{self.ticker}@{self.workdate}"

    @property
    def active_job(self) -> dict | None:
        return next((j for j in self.jobs if j["status"] in ACTIVE_JOB_STATES),
                    None)

    @property
    def uploaded(self) -> dict | None:
        """The newest upload of this video's own format (not a clip)."""
        own = [u for u in self.uploads if u["fmt"] in (self.fmt, "")]
        return max(own, key=lambda u: u["uploaded_at"]) if own else None

    def next_step(self) -> tuple[str, str]:
        """(what you do next, an action code the card and panel turn into a
        button). The code is "" when the next step is not a button — a
        paste, an upload, or waiting."""
        if not self.lane:
            return ("declare the lane: /new short or /new long", "")
        if not self.data_file:
            return ("upload the refreshed workbook (dennis_data.xlsx)", "")
        if self.awaiting_angle and not self.script:
            return ("run prompt_long_angle.md in Claude and pick an angle",
                    "angle")
        if not self.script:
            return ("run the prompt in Claude and paste the script back",
                    "prompt")
        if self.report_ok is False:
            return (f"fix {self.blocking} blocking finding(s) — /script edit",
                    "edit")
        job = self.active_job
        if job:
            return (f"rendering: {job['kind']} — {job['detail'] or job['status']}",
                    "")
        if not self.approved and "final" not in self.renders:
            return ("read the report and approve it", "approve")
        if "final" not in self.renders:
            return ("render the final (this is where money is spent)",
                    "render")
        up = self.uploaded
        if up is None:
            return ("upload it to YouTube (private or scheduled)", "upload")
        if up["privacy"] == "scheduled" and up["publish_at"]:
            return (f"scheduled for {up['publish_at'][:16].replace('T', ' ')}",
                    "")
        if up["age_h"] < RETENTION_READY_H:
            return ("uploaded — retention reads from 48 h after", "")
        return ("read where viewers left: /stats retention", "retention")

    def to_json(self) -> dict:
        out = asdict(self)
        step, action = self.next_step()
        out.update(key=self.key, next_step=step, next_action=action,
                   active_job=self.active_job, uploaded=self.uploaded)
        return out


def _read_report(ws: Workspace, fmt: str) -> dict:
    """The structured report the intake saved, or what the text one says."""
    j = ws.path / f"report_{fmt}.json"
    if j.exists():
        try:
            return json.loads(j.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    t = ws.path / f"report_{fmt}.txt"
    if not t.exists():
        return {}
    try:
        text = t.read_text(encoding="utf-8")
    except OSError:
        return {}
    out: dict = {"blocking": [ln[2:].strip() for ln in text.splitlines()
                              if ln.startswith("⛔")],
                 "warnings": [ln for ln in text.splitlines()
                              if ln.startswith("⚠️")]}
    m = re.search(r"~\$(\d+(?:\.\d+)?) TTS", text)
    if m:
        out["est_tts_usd"] = float(m.group(1))
    out["tts_cached"] = "(cached — $0.00 TTS)" in text
    m = re.search(r"Est\. render: ~(\d+(?:\.\d+)?) min", text)
    if m:
        out["est_render_minutes"] = float(m.group(1))
    return out


def _age_hours(iso: str, now: datetime) -> float:
    try:
        when = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return 0.0
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max((now - when).total_seconds() / 3600, 0.0)


def _jobs_for(jobs: list, ticker: str, workdate: str) -> list[dict]:
    out = []
    for j in sorted(jobs, key=lambda j: j.updated_at, reverse=True):
        if j.ticker != ticker or j.workdate != workdate:
            continue
        out.append({"id": j.id, "kind": j.kind.value, "status": j.status.value,
                    "detail": j.detail, "error": j.error[:300],
                    "updated_at": j.updated_at, "link": j.delivered_link})
    return out[:6]


def video_state(settings: Settings, ws: Workspace, jobs: list | None = None,
                videos: list | None = None,
                now: datetime | None = None) -> VideoState:
    """Everything the card shows about one workspace.

    `jobs` and `videos` are passed in when the caller is about to read many
    workspaces at once (the inbox, the panel), so the job store and the
    upload log are each read once rather than per video.
    """
    from pipeline.company_data import find_export

    now = now or datetime.now(timezone.utc)
    st = VideoState(ticker=ws.ticker, workdate=ws.workdate)
    if not ws.exists:
        return st
    st.lane = ws.lane()
    st.update = ws.is_update()
    st.fmt = ws.current_format() or st.lane or ""
    export = find_export(ws.path)
    if export is not None:
        st.data_file = export.name
        st.data_as_of = _as_of(ws.path, export)
    st.awaiting_angle = ws.awaiting_angle()
    st.angle = ws.chosen_angle()[:200]
    st.why = ws.why[:300]
    if st.fmt:
        raw = ws.raw_script(st.fmt)
        if raw:
            st.script = True
            st.script_chars = len(raw)
            st.script_lines = len(raw.splitlines())
            st.revisions = ws.revision_count(st.fmt)
            try:
                script = (ws.load_short() if st.fmt == "short"
                          else ws.load_long())
            except Exception:  # noqa: BLE001 - a bad file is "no script"
                script = None
            if script is not None:
                st.sha8 = script.content_sha()[:8]
        rep = _read_report(ws, st.fmt)
        if rep:
            st.report = True
            blocking = list(rep.get("blocking") or [])
            st.blocking = len(blocking)
            st.blockers = [str(b)[:200] for b in blocking[:6]]
            st.warnings = len(rep.get("warnings") or [])
            st.report_ok = not blocking
            st.est_usd = rep.get("est_tts_usd")
            st.tts_cached = bool(rep.get("tts_cached"))
            st.est_render_min = rep.get("est_render_minutes")
            st.est_runtime_min = rep.get("est_runtime_min")
        st.approved = ws.is_approved(st.fmt)
        for kind, name in RENDER_FILES.get(st.fmt, {}).items():
            p = ws.path / name
            if p.exists():
                st.renders[kind] = str(p)
    st.clips = [str(p) for p in sorted(ws.path.glob("short_repurposed_*.mp4"))]
    st.thumbnails = [str(ws.path / n) for n in THUMBNAILS
                     if (ws.path / n).exists()]
    if jobs is None:
        from pipeline.jobs import JobStore
        jobs = JobStore(settings).all()
    st.jobs = _jobs_for(jobs, ws.ticker, ws.workdate)
    if videos is None:
        from pipeline.youtube import VideoLog
        videos = VideoLog(settings).for_ticker(ws.ticker)
    from pipeline.youtube import record_format
    for v in videos:
        if v.ticker != ws.ticker or v.workdate != ws.workdate:
            continue
        st.uploads.append({
            "video_id": v.video_id, "url": v.url(), "title": v.title,
            "fmt": record_format(v), "privacy": v.privacy,
            "publish_at": v.publish_at, "uploaded_at": v.uploaded_at,
            "age_h": round(_age_hours(v.uploaded_at, now), 1),
            "retention": bool(v.retention)})
    return st


# (export path, mtime) -> as-of date. The panel reads every recent video
# every few seconds; a workbook is parsed once per upload, not per poll.
_AS_OF: dict[tuple[str, float], str] = {}


def _as_of(path: Path, export: Path) -> str:
    """The workbook's as-of date, parsed once per version of the file."""
    try:
        key = (str(export), export.stat().st_mtime)
    except OSError:
        return ""
    if key in _AS_OF:
        return _AS_OF[key]
    try:
        from pipeline.company_data import load_company_data
        data = load_company_data(path)
        value = str(data.get("as_of_date") or "")
    except Exception:  # noqa: BLE001 - the card says "uploaded", not the date
        value = ""
    if len(_AS_OF) > 500:
        _AS_OF.clear()
    _AS_OF[key] = value
    return value


def recent_workspaces(settings: Settings, days: int = 14,
                      limit: int = 40) -> list[Workspace]:
    """Every video folder from the last `days` days, newest first."""
    root = Path(settings.workspace_dir)
    if not root.is_dir():
        return []
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    found: list[Workspace] = []
    for tdir in root.iterdir():
        if not tdir.is_dir() or tdir.name.startswith("_"):
            continue
        for ddir in tdir.iterdir():
            if (ddir.is_dir() and _DATE_RE.match(ddir.name)
                    and ddir.name >= cutoff):
                found.append(Workspace(settings, tdir.name, ddir.name))
    found.sort(key=lambda w: (w.workdate, _mtime(w.path)), reverse=True)
    return found[:limit]


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def all_states(settings: Settings, days: int = 14,
               now: datetime | None = None) -> list[VideoState]:
    """`video_state` for every recent folder, reading the job store and the
    upload log once."""
    from pipeline.jobs import JobStore
    from pipeline.youtube import VideoLog

    jobs = JobStore(settings).all()
    videos = VideoLog(settings).all()
    return [video_state(settings, ws, jobs=jobs, videos=videos, now=now)
            for ws in recent_workspaces(settings, days)]


def card_text(st: VideoState) -> str:
    """The video card as text: one line per stage, the next step last."""
    lane = ("UPDATE" if st.update else (st.lane or "no lane").upper())
    lines = [f"📁 {st.ticker} · {lane} · {st.workdate}"]
    if st.data_file:
        lines.append(f"data      ✅ {st.data_file}"
                     + (f" · as of {st.data_as_of}" if st.data_as_of else ""))
    else:
        lines.append("data      ⏳ waiting for dennis_data.xlsx")
    if st.lane == "long" and not st.update:
        if st.angle:
            lines.append(f"angle     ✅ {st.angle[:60]}")
        elif st.awaiting_angle:
            lines.append("angle     ⏳ waiting for your pick")
    if st.script:
        gates = ("✅" if st.report_ok else
                 f"⛔ {st.blocking} blocking" if st.report_ok is False
                 else "not checked")
        warn = f" · {st.warnings} warning(s)" if st.warnings else ""
        rev = f"rev {st.revisions + 1} · " if st.revisions else ""
        lines.append(f"script    {rev}{st.script_chars:,} chars · "
                     f"gates {gates}{warn}")
    else:
        lines.append("script    —")
    if st.approved:
        cost = ("voice cached $0" if st.tts_cached else
                f"est. ${st.est_usd:.2f}" if st.est_usd is not None else "")
        took = (f" · ~{st.est_render_min:.0f} min" if st.est_render_min
                else "")
        lines.append(f"approval  ✅ sha {st.sha8}"
                     + (f" · {cost}" if cost else "") + took)
    elif st.script:
        lines.append("approval  — not approved")
    renders = [f"{k} ✅" for k in ("draft", "proof", "final")
               if k in st.renders]
    job = st.active_job
    if job:
        renders.append(f"⏳ {job['kind'].replace('render_', '')}: "
                       f"{job['detail'] or job['status']}")
    if st.clips:
        renders.append(f"clips ✅ {len(st.clips)}")
    lines.append("renders   " + (" · ".join(renders) if renders else "—"))
    up = st.uploaded
    if up is None:
        lines.append("upload    —")
    elif up["privacy"] == "scheduled" and up["publish_at"]:
        lines.append(f"upload    📅 {up['publish_at'][:16].replace('T', ' ')}"
                     f" · {up['url']}")
    else:
        lines.append(f"upload    ✅ {up['privacy']} · {up['url']}")
    failed = next((j for j in st.jobs if j["status"] == "failed"), None)
    if failed and not job:
        lines.append(f"last job  ❌ {failed['kind']}: {failed['error'][:120]}")
    step, _ = st.next_step()
    lines.append(f"\n→ next: {step}")
    return "\n".join(lines)


# ----------------------------------------------------------------- inbox
@dataclass
class InboxItem:
    section: str
    ticker: str
    workdate: str
    text: str
    action: str = ""               # the button the card would offer

    def to_json(self) -> dict:
        return asdict(self)


INBOX_SECTIONS = (
    ("approve", "📝 waiting for your approval"),
    ("blocked", "⛔ blocked — needs an edit"),
    ("render", "🎬 approved, not rendered"),
    ("upload", "📤 rendered, not uploaded"),
    ("scheduled", "📅 going public in the next 48 h"),
    ("retention", "📊 retention ready to read"),
    ("failed", "❌ failed overnight"),
)


def inbox(settings: Settings, now: datetime | None = None,
          states: list[VideoState] | None = None) -> list[InboxItem]:
    """Everything waiting on the operator, in the order it should be done."""
    from pipeline.standing import BatchQueue
    from pipeline.youtube import VideoLog

    now = now or datetime.now(timezone.utc)
    states = states if states is not None else all_states(settings, now=now)
    items: list[InboxItem] = []
    for st in states:
        if st.active_job:
            continue                     # it is moving; nothing to do yet
        if st.script and st.report_ok is False:
            items.append(InboxItem("blocked", st.ticker, st.workdate,
                                   f"{st.blocking} blocking finding(s)",
                                   "edit"))
        elif st.script and st.report_ok and not st.approved \
                and "final" not in st.renders:
            cost = (f" · ~${st.est_usd:.2f}" if st.est_usd is not None
                    and not st.tts_cached else "")
            items.append(InboxItem("approve", st.ticker, st.workdate,
                                   f"{st.fmt.upper()} report ready{cost}",
                                   "approve"))
        elif st.approved and "final" not in st.renders:
            items.append(InboxItem("render", st.ticker, st.workdate,
                                   f"{st.fmt.upper()} approved", "render"))
        elif "final" in st.renders and st.uploaded is None:
            items.append(InboxItem("upload", st.ticker, st.workdate,
                                   f"{st.fmt.upper()} final on disk",
                                   "upload"))
        failed = next((j for j in st.jobs if j["status"] == "failed"), None)
        if failed and _age_hours(failed["updated_at"], now) < 24:
            items.append(InboxItem("failed", st.ticker, st.workdate,
                                   f"{failed['kind']}: {failed['error'][:80]}",
                                   "card"))
    log_ = VideoLog(settings)
    for v in log_.scheduled(now=now):
        try:
            when = datetime.fromisoformat(v.publish_at.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if when - now <= timedelta(hours=48):
            items.append(InboxItem("scheduled", v.ticker, v.workdate,
                                   f"{v.publish_at[:16].replace('T', ' ')} — "
                                   f"{v.title[:50]}"))
    for v in log_.all():
        age = _age_hours(v.uploaded_at, now)
        if v.retention or not (RETENTION_READY_H <= age <= 24 * 14):
            continue
        if v.privacy == "scheduled" and v.publish_at:
            continue                     # not public yet: nothing to read
        items.append(InboxItem("retention", v.ticker, v.workdate,
                               f"{v.title[:50]} ({age / 24:.0f} days up)",
                               "retention"))
    for b in BatchQueue(settings).pending():
        if b.error:
            items.append(InboxItem("failed", b.ticker, "",
                                   f"overnight {b.fmt.upper()}: "
                                   f"{b.error[:80]}"))
    order = {name: i for i, (name, _) in enumerate(INBOX_SECTIONS)}
    items.sort(key=lambda i: order.get(i.section, 99))
    return items


def inbox_text(items: list[InboxItem]) -> str:
    if not items:
        return "📥 Inbox zero — nothing is waiting on you."
    titles = dict(INBOX_SECTIONS)
    lines = ["📥 Waiting on you"]
    section = ""
    for it in items:
        if it.section != section:
            section = it.section
            lines.append(f"\n{titles.get(section, section)}")
        where = f"{it.ticker}" + (f" ({it.workdate})"
                                  if it.workdate and it.workdate != today_str()
                                  else "")
        lines.append(f"  • {where} — {it.text}")
    return "\n".join(lines)
