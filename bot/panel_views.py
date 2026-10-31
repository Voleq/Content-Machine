"""What the page shows, one screen at a time, as JSON.

The panel used to have one view of a video: its card, the chat's text with
the chat's buttons under it. The workspace screen walks the ten steps of a
video in order, and each step needs the facts behind the card as data: the
workbook's problems one by one, the script as lines, each finding on the
line it is about, the voice's sentences with their times, the upload's
fields one copy button each.

Nothing here decides anything. Every builder reads what the bot already
wrote (the workspace's files, the report, the job store, the upload log)
through the same functions the commands print from, and the buttons it
offers carry the same callback data the chat's keyboards do
(`bot/keyboards.py`). The page acts only through `run_command`,
`handle_callback`, `handle_text` and `handle_upload`.

A step whose files are half-written or unreadable comes back as
`{"error": …}` on its own; the rest of the screen still opens.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from bot import keyboards as kb
from bot.feed import keyboard_rows
from pipeline.video_state import VideoState, video_state
from pipeline.workspace import Workspace

log = logging.getLogger(__name__)

STEPS: tuple[tuple[str, str], ...] = (
    ("data", "Data"), ("angle", "Angle"), ("write", "Write"),
    ("check", "Check"), ("proof", "Proof"), ("approve", "Approve"),
    ("voice", "Voice"), ("render", "Render"), ("upload", "Upload"),
    ("live", "Live"),
)

# The prompt each format's writer step hands over.
WRITE_PROMPTS = {"short": "prompt_short.md", "long": "prompt_long_write.md",
                 "update": "prompt_update.md"}
ANGLE_PROMPT = "prompt_long_angle.md"

# The figures the data step shows from the workbook, as (label, field, kind).
FIGURES: tuple[tuple[str, str, str], ...] = (
    ("Company", "company_name", "text"), ("Price", "price", "money"),
    ("Market cap", "market_cap", "big"), ("EV / sales", "ev_sales", "x"),
    ("P/E", "pe_ttm", "x"), ("52-week high", "week52_high", "money"),
    ("52-week low", "week52_low", "money"), ("FCF yield", "fcf_yield", "pct"),
    ("Net debt", "net_debt_now", "big"), ("Short interest", "short_interest", "pct"),
)

# "[gate] L12: message\n    “excerpt”" — `gates.Finding.render`.
_FINDING_RE = re.compile(
    r"^\[(?P<gate>[^\]]+)\]\s+(?:L(?P<line>\d+):\s+)?(?P<message>.*?)"
    r"(?:\n\s*“(?P<excerpt>.*)”)?\s*$", re.S)


@dataclass
class _Video:
    panel: object
    ws: Workspace
    st: VideoState
    fmt: str

    @property
    def core(self):
        return self.panel.core

    @property
    def settings(self):
        return self.panel.settings

    def link(self, path) -> str:
        """A link the page can open, or "" for a file the panel does not
        serve: a path outside the served folders never reaches the page.
        Without the key: the page adds it, so a view never carries it."""
        if not path:
            return ""
        p = Path(path)
        return (f"/api/file?path={quote(str(p))}" if self.panel.allowed(p)
                else "")

    def script(self):
        if self.fmt == "short":
            return self.ws.load_short()
        return self.ws.load_long() if self.fmt else None

    def narration(self, script) -> str:
        if script is None:
            return ""
        return (script.audio_script if self.fmt == "short"
                else script.narration)


# --------------------------------------------------------------------------
# The steps
# --------------------------------------------------------------------------

def _money(v: float) -> str:
    return f"${v:,.2f}"


def _big(v: float) -> str:
    for size, unit in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if abs(v) >= size:
            return f"${v / size:,.1f}{unit}"
    return f"${v:,.0f}"


def _figure(kind: str, v) -> str:
    if v in (None, ""):
        return ""
    if kind == "text" or not isinstance(v, (int, float)):
        return str(v)
    return {"money": _money, "big": _big, "x": lambda x: f"{x:,.1f}×",
            "pct": lambda x: f"{x * 100:.1f}%"}[kind](float(v))


_CHECKS: dict[tuple[str, float], dict] = {}


def _step_data(v: _Video) -> dict:
    from pipeline.company_data import (CompanyDataError, check_export,
                                       find_export, load_company_data)

    out: dict = {"file": v.st.data_file, "as_of": v.st.data_as_of,
                 "problems": [], "figures": [], "freshness": []}
    export = find_export(v.ws.path)
    if export is None:
        return out
    key = (str(export), export.stat().st_mtime)
    # The server answers each request on its own thread: one lookup, so a
    # clear by a second video's view cannot take this entry between a test
    # and a read.
    cached = _CHECKS.get(key)
    if cached is None:
        check = check_export(export, expect_ticker=v.ws.ticker,
                             max_age_days=v.settings.data_max_age_days)
        figures, missing = [], []
        try:
            data = load_company_data(v.ws.path)
        except CompanyDataError as e:
            data = None
            missing = [str(e)]
        if data is not None:
            figures = [{"label": label, "value": _figure(kind, data.get(f))}
                       for label, f, kind in FIGURES
                       if data.get(f) not in (None, "")]
            missing = ([f"missing, needed: {', '.join(data.blocking_missing)}"]
                       if data.blocking_missing else [])
            if data.warning_missing:
                missing.append(f"missing, worth filling: "
                               f"{', '.join(data.warning_missing[:12])}")
        cached = {
            "problems": [{"kind": p.kind, "message": p.message,
                          "blocking": p.blocking} for p in check.problems],
            "figures": figures, "missing": missing,
            "as_of": check.as_of}
        _CHECKS.clear()
        _CHECKS[key] = cached
    out.update(problems=cached["problems"], figures=cached["figures"],
               missing=cached["missing"])
    out["site"] = _site_section(v, export)
    out["as_of"] = out["as_of"] or cached["as_of"]
    if out["as_of"]:
        from pipeline.gates import check_freshness
        try:
            out["freshness"] = [
                {"severity": f.severity, "message": f.message}
                for f in check_freshness(out["as_of"], v.settings, None,
                                         v.ws.path)]
        except Exception as e:                    # noqa: BLE001
            out["freshness"] = [{"severity": "warn",
                                 "message": f"freshness not checked: {e}"}]
    return out


_SITE: dict = {}


def _site_section(v: _Video, export: Path) -> dict | None:
    """What this video took from stockanalysis.com: each part and when it
    was read, the coverage, the call, where the workbook and the site
    disagree, and the blank cells the site filled (`pipeline/site_pack.py`).
    None until the prompt has been made once."""
    from pipeline import site_pack
    from pipeline.company_data import CompanyDataError, load_company_data

    p = site_pack.path(v.ws.path)
    if not p.exists():
        return None
    key = (str(p), p.stat().st_mtime, str(export), export.stat().st_mtime)
    got = _SITE.get(key)
    if got is not None:
        return got
    pack = site_pack.load(v.ws.path) or {}
    diffs, filled = [], []
    try:
        raw = load_company_data(v.ws.path, site=False)
        diffs = site_pack.cross_check(raw, pack)
        filled = site_pack.fill_quarter_gaps(raw, v.ws.path)
    except CompanyDataError:
        pass
    call = pack.get("call") or {}
    news = sorted((n for n in pack.get("news") or []
                   if n.get("kind") in ("article", "release")),
                  key=lambda n: str(n.get("time", "")), reverse=True)
    got = {
        "status": pack.get("status", ""), "why": pack.get("why", ""),
        "fetched_at": pack.get("fetched_at", ""),
        "parts": site_pack.summary(pack),
        "earnings": pack.get("earnings") or {},
        "news": [{k: n.get(k, "") for k in ("time", "source", "title", "kind", "url")}
                 for n in news[:10]],
        "call": ({"title": call.get("title", ""), "date": call.get("date", ""),
                  "url": call.get("url", ""), "picked_by": call.get("picked_by", ""),
                  "passages": call.get("passages") or []} if call else None),
        "diffs": diffs, "filled": filled,
        "refresh": f"/site {v.ws.ticker}@{v.ws.workdate} refresh",
    }
    _SITE.clear()
    _SITE[key] = got
    return got


def _prompt(v: _Video, name: str) -> dict:
    p = v.ws.path / name
    if not p.exists():
        return {"name": name, "url": "", "chars": 0}
    return {"name": name, "url": v.link(p), "chars": p.stat().st_size}


def _step_angle(v: _Video) -> dict:
    return {"prompt": _prompt(v, ANGLE_PROMPT), "chosen": v.st.angle,
            "awaiting": v.st.awaiting_angle,
            "pick": keyboard_rows(kb.angle_keyboard(v.ws.ticker, v.ws.workdate))}


def _step_write(v: _Video) -> dict:
    which = "update" if v.st.update else v.fmt
    return {"prompt": _prompt(v, WRITE_PROMPTS.get(which, "")),
            "script": v.st.script, "chars": v.st.script_chars,
            "revisions": v.st.revisions}


def _report(v: _Video) -> dict:
    p = v.ws.path / f"report_{v.fmt}.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def parse_finding(text: str, severity: str) -> dict:
    """A report line back into its parts. Lines that are not a gate's
    finding (a parse or validation warning) keep their whole text."""
    m = _FINDING_RE.match(text.strip())
    if not m:
        return {"gate": "", "severity": severity, "message": text.strip(),
                "line": 0, "excerpt": ""}
    return {"gate": m["gate"], "severity": severity,
            "message": m["message"].strip(), "line": int(m["line"] or 0),
            "excerpt": (m["excerpt"] or "").strip()}


_AUDIO_RE = re.compile(r'"audio_script"\s*:\s*"((?:[^"\\]|\\.)*)"')
_TAGS_RE = re.compile(r"\[[^\]]*\]")


def _plain(text: str) -> str:
    return " ".join(_TAGS_RE.sub(" ", text).split()).lower()


def short_sentences(raw: str) -> list[dict]:
    """A SHORT's narration as it sits in the stored JSON, one sentence at a
    time: `{"raw": the text exactly as stored (JSON-escaped, tags in), "text":
    the same read back}`. `/script replace raw => new` edits one in place;
    the JSON's own lines are no way to read a script."""
    m = _AUDIO_RE.search(raw or "")
    if not m:
        return []
    body, out, start, depth = m.group(1), [], 0, 0
    for i, ch in enumerate(body):
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth = max(depth - 1, 0)
        elif (ch in ".!?" and depth == 0 and i + 1 < len(body)
              and body[i + 1] == " "):
            out.append(body[start:i + 1])
            start = i + 2
    out.append(body[start:])
    rows = []
    for piece in (x.strip() for x in out):
        if not piece:
            continue
        try:
            text = json.loads(f'"{piece}"')
        except ValueError:
            text = piece
        rows.append({"raw": piece, "text": text})
    return rows


def _locate(rows: list[dict], probe: str) -> int:
    """The sentence (1-based) a finding's or a claim's words are in."""
    want = _plain(probe)
    if not want:
        return 0
    head = " ".join(want.split()[:6])
    for i, r in enumerate(rows, 1):
        have = _plain(r["text"])
        if want in have or head in have:
            return i
    return 0


def _step_check(v: _Video) -> dict:
    from pipeline.claims import _raw_line, list_claims
    from pipeline.cold_read import (cold_read_prompt, load_cold_read,
                                    spoken_lines)

    raw = v.ws.raw_script(v.fmt) or "" if v.fmt else ""
    out: dict = {"lines": [{"n": i, "text": t}
                           for i, t in enumerate(raw.splitlines(), 1)],
                 "findings": [], "claims": [], "cold_read": None,
                 "cold_prompt": "", "why": v.ws.why[:600],
                 "revisions": v.st.revisions}
    if not raw:
        return out
    script = v.script()
    narr = v.narration(script).splitlines()
    rows = short_sentences(raw) if v.fmt == "short" else []
    if rows:
        # A SHORT is read and edited by sentence; the rest of its JSON (the
        # headlines, the numbers the plates draw) by its own lines.
        out["mode"] = "sentences"
        out["data_lines"] = [ln for ln in out["lines"]
                             if '"audio_script"' not in ln["text"]]
        out["lines"] = [{"n": i, "text": r["text"], "raw": r["raw"]}
                        for i, r in enumerate(rows, 1)]
    rep = _report(v)
    from pipeline.gates import finding_key

    for sev, key in (("block", "blocking"), ("warn", "warnings"), ("note", "notes")):
        for text in rep.get(key) or []:
            f = parse_finding(str(text), sev)
            # The key `/script trust` takes, for the one kind of block he can
            # overrule: a fact-check figure he has checked himself.
            f["key"] = finding_key(str(text))
            f["trustable"] = sev == "block" and f["gate"] == "fact-check"
            # A gate numbers the narration's lines; the editor numbers the
            # stored script's, the ones `/script edit N` takes.
            probe = (narr[f["line"] - 1] if 0 < f["line"] <= len(narr)
                     else f["excerpt"])
            if rows:
                f["raw_line"] = (_locate(rows, f["excerpt"]) if f["excerpt"]
                                 else 0) or (_locate(rows, probe) if len(narr) > 1 else 0)
            else:
                f["raw_line"] = _raw_line(raw, probe) if probe else 0
            out["findings"].append(f)
    out.update(dennis_alone=rep.get("dennis_alone", -1),
               dennis_alone_max=rep.get("dennis_alone_max"),
               est_runtime_min=rep.get("est_runtime_min"),
               est_render_min=rep.get("est_render_minutes"),
               words=rep.get("words"))
    if script is not None:
        out["claims"] = [{"line": _locate(rows, c.text) if rows else c.line,
                          "text": c.text, "why": c.why}
                         for c in list_claims(v.narration(script),
                                              v.ws.ticker, raw)]
        lines = spoken_lines(script, raw)
        out["cold_prompt"] = cold_read_prompt(lines, v.fmt)
        cr = load_cold_read(v.ws.path, v.fmt)
        if cr is not None:
            out["cold_read"] = {
                "text": cr.text, "saved_at": cr.saved_at,
                "stale": bool(cr.script_sha and v.st.sha8
                              and not cr.script_sha.startswith(v.st.sha8)),
                "quotes": [{"quote": q, "line": _locate(rows, q) if rows else n}
                           for q, n in cr.quotes]}
    return out


def _chapters(v: _Video, kind: str) -> list[dict]:
    names = {"short": {"proof": "short_proof.manifest.json",
                       "final": "short_final.manifest.json"},
             "long": {"proof": "render_long_proof_manifest.json",
                      "final": "render_long_manifest.json"}}
    p = v.ws.path / names.get(v.fmt, {}).get(kind, "")
    if not p.is_file():
        return []
    try:
        man = json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return []
    return [{"t": float(c.get("t", 0)), "title": str(c.get("title", ""))}
            for c in man.get("chapters") or []]


def _step_proof(v: _Video) -> dict:
    proof = v.st.renders.get("proof") or v.st.renders.get("draft")
    code = kb.FMT_CODES.get(v.fmt, "s")
    out = {"url": v.link(proof), "name": Path(proof).name if proof else "",
           "chapters": _chapters(v, "proof") if proof else [],
           "render": [{"text": "Render the free proof",
                       "data": f"q|p|{v.ws.ticker}|{v.ws.workdate}|{code}"}],
           "strip": [], "notes": [], "faults": "", "checks": []}
    from pipeline import proof_review

    if proof:
        out["strip"] = [{"t": t, "url": v.link(p)}
                        for t, p in proof_review.cached_strip(Path(proof))]
    out["notes"] = proof_review.load_notes(v.ws.path, v.fmt)
    out["faults"] = proof_review.fault_list(out["notes"])
    out["checks"] = _proof_checks(v, proof)
    # A proof under way: said here, where he pressed for it, with its stage
    # and a Stop. The step said "No proof yet" and offered the button again
    # the whole time one rendered (30 Oct 2026).
    job = v.st.active_job
    out["running"] = (_job_view(v, job) if job and job["kind"].startswith("render_proof")
                      else None)
    if out["running"] is None:
        last = next((j for j in v.st.jobs if j["kind"].startswith("render_proof")), None)
        if last and last["status"] == "failed":
            out["failed"] = {"error": last["error"],
                             "log": _job_log(v, last["id"])}
    return out


def _proof_checks(v: _Video, proof) -> list[str]:
    """What the proof's render found worth his eye (V5, V7), off its manifest."""
    if not proof:
        return []
    from pipeline.render_notes import notes_at

    if v.fmt == "long":
        return notes_at(v.ws.path / "render_long_proof_manifest.json", "long")
    return notes_at(Path(proof).with_suffix(".manifest.json"), "short")


def _step_approve(v: _Video) -> dict:
    st = v.st
    ledger = v.core.ledger
    try:
        mtd = ledger.mtd_spend_usd()
    except Exception:                                # noqa: BLE001
        mtd = None
    out = {"est_usd": st.est_usd, "cached": st.tts_cached,
           "approved": st.approved, "report_ok": st.report_ok,
           "blockers": st.blockers, "sha8": st.sha8, "mtd": mtd,
           "cap": v.settings.monthly_spend_cap_usd, "buttons": []}
    if st.approved:
        out["buttons"] = keyboard_rows(kb.approved_keyboard(
            v.fmt, v.ws.ticker, v.ws.workdate, st.est_usd))
    elif st.sha8 and st.report_ok:
        out["buttons"] = [[{"text": "Approve ✅",
                            "data": f"a|{v.fmt}|{v.ws.ticker}|{v.ws.workdate}|{st.sha8}"}]]
    return out


def _step_voice(v: _Video) -> dict:
    out: dict = {"audio_url": "", "words": [], "sentences": [],
                 "redos_left": None, "compare": []}
    if not v.fmt or not hasattr(v.core, "_voice_of"):
        return out
    from pipeline.voice_redo import MAX_REDOS, redos_done

    script, text, _events, cdir = v.core._voice_of(v.ws, v.fmt)
    if script is None or cdir is None:
        return out
    words = json.loads((Path(cdir) / "words.json").read_text(encoding="utf-8"))
    out["audio_url"] = v.link(Path(cdir) / "audio.m4a")
    out["words"] = [{"w": w["word"], "s": round(w["start"], 3),
                     "e": round(w["end"], 3)} for w in words]
    out["sentences"] = [{"index": r.index, "text": r.text,
                         "start": round(r.start, 2), "end": round(r.end, 2)}
                        for r in v.core._voice_sentences(Path(cdir), text)]
    out["redos_left"] = MAX_REDOS - len(redos_done(v.ws.path, v.fmt))
    folder = v.ws.path / "voice_compare"
    out["compare"] = [{"name": p.stem.removeprefix("compare_"), "url": v.link(p)}
                      for p in sorted(folder.glob("compare_*.wav"))]
    return out


def _job_log(v: _Video, job_id: str, n: int = 12) -> list[str]:
    from pipeline.jobs import job_log

    return job_log(v.settings, job_id or "", n)


def _job_view(v: _Video, job: dict) -> dict:
    """A queued or running job as the page shows it wherever it is asked
    for: its stage in words and how far, its last log lines, a Stop, and,
    while it waits, what runs ahead of it."""
    from pipeline.jobs import JobStore, progress

    out = {"job": job, "progress": progress(job, v.st.est_render_min),
           "log": _job_log(v, job["id"]),
           "cancel": keyboard_rows(kb.queued_keyboard(v.ws.ticker, v.ws.workdate)),
           "ahead": []}
    if job["status"] == "queued":
        # One render at a time, oldest first (`RenderJobQueue`): what runs
        # now, and what was queued before this one.
        store = getattr(v.core.queue, "store", None) or JobStore(v.settings)
        live = sorted((j for j in store.all()
                       if j.status.value in ("queued", "running")),
                      key=lambda j: (j.status.value != "running", j.created_at))
        for j in live:
            if j.id == job["id"]:
                break
            out["ahead"].append({"ticker": j.ticker, "kind": j.kind.value,
                                 "status": j.status.value, "detail": j.detail})
    return out


def _step_render(v: _Video) -> dict:
    job = v.st.active_job
    last = v.st.jobs[0] if v.st.jobs else None
    out: dict = {"job": job, "progress": None, "last": last,
                 "final_url": v.link(v.st.renders.get("final")),
                 "log": _job_log(v, (job or last or {}).get("id", "")),
                 "cancel": [], "render": [], "running": None}
    if job:
        out["running"] = _job_view(v, job)
        out.update(progress=out["running"]["progress"], log=out["running"]["log"],
                   cancel=out["running"]["cancel"])
    elif v.st.approved and "final" not in v.st.renders:
        code = kb.FMT_CODES.get(v.fmt, "s")
        price = f" ~${v.st.est_usd:.2f}" if v.st.est_usd else ""
        out["render"] = [[{"text": f"Render the final 💰{price}",
                           "data": f"r!|{code}|{v.ws.ticker}|{v.ws.workdate}"}]]
    return out


STUDIO_CHECKLIST = (
    "Upload as Unlisted first, and watch it there once.",
    "Altered or synthetic content: Yes (the voice is AI).",
    "Check where YouTube puts the AI label on the watch page.",
    "Paste each field from here: title, description, tags, then the pinned comment.",
    "Add your Figma thumbnail.",
    "Paste the link here when it is up, so the bot knows it is out.",
)


def _end_screen_line(v: _Video) -> str:
    """The long's end screen as a Studio step (V3), off its final's
    manifest; "" for a short or a final rendered before it was recorded."""
    if v.fmt != "long":
        return ""
    from pipeline.end_screen import checklist_line

    try:
        data = json.loads((v.ws.path / "render_long_manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return checklist_line(data.get("end_screen") or {}) if isinstance(data, dict) else ""


def _step_upload(v: _Video) -> dict:
    from pipeline.publish import byproduct_name
    from pipeline.thumbnail import his_cover, bot_cover

    from pipeline.youtube import sending

    st = v.st
    final = st.renders.get("final")
    # AN UPLOAD UNDER WAY, and how far: the page greys its Upload buttons
    # and shows the share sent, where nothing said it was still going.
    going = (v.ws.ticker, v.ws.workdate) in getattr(v.core, "_uploading", ())
    share = sending(v.ws.path) if going else None
    out: dict = {"ready": bool(final), "uploaded": st.uploaded,
                 "uploading": ({"pct": round((share or 0.0) * 100)} if going else None),
                 "checklist": list(STUDIO_CHECKLIST), "downloads": [],
                 "titles": [], "description": "", "tags": [], "pinned": "",
                 "chapters": [], "buttons": [], "thumbnail": {}}
    if not final:
        return out
    end = _end_screen_line(v)
    if end:
        # Before the "paste the link" line: it is set in Studio, before publishing.
        out["checklist"].insert(len(out["checklist"]) - 1, end)
    out["downloads"].append({"name": Path(final).name, "url": v.link(final)})
    for kind in ("captions", "transcript", "package", "companion"):
        name = byproduct_name(kind, v.fmt, v.ws.ticker)
        p = v.ws.path / name if name else None
        if p is not None and p.exists():
            out["downloads"].append({"name": p.name, "url": v.link(p)})
    # No script on file (a final copied in, or one whose script was lost):
    # the files still download, there is just nothing to paste.
    pkg = v.core._upload_package(v.ws, v.fmt)
    if pkg is not None:
        out.update(titles=list(pkg.titles), description=pkg.description,
                   tags=list(pkg.tags), pinned=pkg.pinned_comment)
    out["chapters"] = [{"stamp": s, "title": t}
                       for s, t, *_ in v.core._chapter_pairs(v.ws, v.fmt)]
    out["buttons"] = keyboard_rows(kb.delivered_keyboard(
        v.fmt, v.ws.ticker, v.ws.workdate, final=True))
    cover = v.ws.path / byproduct_name("thumbnail", v.fmt, v.ws.ticker)
    out["thumbnail"] = {"current": v.link(cover) if cover.exists() else "",
                        "bot": v.link(bot_cover(v.ws, v.fmt)),
                        "his": his_cover(v.ws, v.fmt) is not None,
                        "fmt": v.fmt}
    # The folder's date rides along: without it the link was recorded
    # against the ticker's newest folder, so an older video stayed under
    # "Rendered, not uploaded" (scan, 24 Oct 2026).
    out["mark_hint"] = f"/publish mark {v.ws.ticker}@{v.ws.workdate} {v.fmt} "
    return out


def _step_live(v: _Video) -> dict:
    from pipeline.youtube import VideoLog, record_format, retention_rows

    up = v.st.uploaded
    out: dict = {"video": up, "curve": [], "lines": [], "corrections": [],
                 "buttons": []}
    if not up:
        return out
    rec = VideoLog(v.settings).get(up["video_id"])
    if rec is None:
        return out
    out["curve"] = [{"x": float(r.get("elapsed_ratio", 0)),
                     "y": float(r.get("watch_ratio", 0))}
                    for r in retention_rows(rec.retention)]
    out["chapters"] = [{"t": _stamp(c[0]), "title": str(c[1])}
                       for c in (rec.chapters or [])
                       if isinstance(c, (list, tuple)) and len(c) >= 2]
    out["duration_s"] = rec.duration_s
    out["synthetic_declared"] = rec.synthetic_declared
    out["upload_notes"] = list(rec.upload_notes or [])
    if record_format(rec) != "clip" and rec.retention:
        from pipeline.retention_lines import holds_for_video, narration_for
        holds = holds_for_video(v.settings, rec, narration_for(v.settings, rec))
        out["lines"] = [{"text": h.text, "start": round(h.start_s, 1),
                         "kept": round(h.watch_ratio, 3), "drop": round(h.drop, 3)}
                        for h in holds]
    out["corrections"] = list(rec.corrections or [])
    out["buttons"] = keyboard_rows(kb.uploaded_keyboard(v.ws.ticker, rec.video_id))
    return out


def _stamp(stamp) -> float:
    parts = str(stamp).split(":")
    try:
        nums = [float(x) for x in parts]
    except ValueError:
        return 0.0
    out = 0.0
    for x in nums:
        out = out * 60 + x
    return out


_BUILDERS = {"data": _step_data, "angle": _step_angle, "write": _step_write,
             "check": _step_check, "proof": _step_proof,
             "approve": _step_approve, "voice": _step_voice,
             "render": _step_render, "upload": _step_upload,
             "live": _step_live}


# --------------------------------------------------------------------------
# Where the video is
# --------------------------------------------------------------------------

def current_step(st: VideoState) -> str:
    """The step the video waits on: the card's next step, as a step."""
    if not st.lane or not st.data_file:
        return "data"
    if st.awaiting_angle and not st.script:
        return "angle"
    if not st.script:
        return "write"
    if st.report_ok is False:
        return "check"
    if st.active_job:
        # a proof under way is shown where he asked for it
        return "proof" if st.active_job["kind"].startswith("render_proof") else "render"
    if not st.approved and "final" not in st.renders:
        return "approve"
    if "final" not in st.renders:
        return "render"
    if st.uploaded is None:
        return "upload"
    return "live"


def _status(step: str, st: VideoState, now: str, has_voice: bool) -> str:
    order = [s for s, _ in STEPS]
    if step == "angle" and (st.fmt == "short" or st.update):
        return "skip"
    if step == now:
        return "now"
    done = {
        "data": bool(st.data_file),
        "angle": bool(st.angle) or st.script,
        "write": st.script,
        "check": st.report_ok is True,
        "proof": "proof" in st.renders or "draft" in st.renders,
        "approve": st.approved or "final" in st.renders,
        "voice": has_voice,
        "render": "final" in st.renders,
        "upload": st.uploaded is not None,
        "live": False,
    }[step]
    if done:
        return "done"
    if step == "proof" and order.index(now) > order.index("proof"):
        return "optional"
    return "todo"


def _summary(step: str, st: VideoState, data: dict | None,
             has_voice: bool = False) -> str:
    """The rail's line under a step. `data` is None for a step this view
    did not build (`video_view(step=…)`): the line then comes from the
    video's state alone."""
    if data is not None and "error" in data:
        return "could not be read"
    data = data or {}
    if step == "data":
        return (f"{st.data_file} · as of {st.data_as_of}" if st.data_file
                else "no workbook yet")
    if step == "angle":
        return st.angle[:80] if st.angle else ""
    if step == "write":
        if not st.script:
            return "no script yet"
        size = (f"{st.script_lines} lines" if st.fmt == "long"
                else f"{st.script_chars:,} characters")
        return f"{size} · {st.revisions} edits"
    if step == "check":
        if not st.report:
            return ""
        return (f"{st.blocking} blocking · {st.warnings} warnings"
                if st.blocking else f"clean · {st.warnings} warnings")
    if step == "proof":
        job = st.active_job
        if job and job["kind"].startswith("render_proof"):
            return f"{job['status']}…"
        return "rendered" if ("proof" in st.renders or "draft" in st.renders) else ""
    if step == "approve":
        if st.approved:
            return "approved"
        return f"~${st.est_usd:.2f} voice" if st.est_usd else ""
    if step == "voice":
        n = len(data.get("sentences") or [])
        if n:
            return f"{n} sentences"
        if has_voice:
            return "made"
        return "made when the render starts" if st.approved else ""
    if step == "render":
        job = st.active_job
        if job and not job["kind"].startswith("render_proof"):
            return f"{job['status']}…"
        return "final rendered" if "final" in st.renders else ""
    if step == "upload":
        up = st.uploaded
        return f"{up['privacy']} · {up['url']}" if up else ""
    if step == "live":
        return "retention on file" if (st.uploaded or {}).get("retention") else ""
    return ""


_TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,11}$")
_WORKDATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def is_video_key(ticker: str, workdate: str) -> bool:
    """A ticker and a date, not a path: `../state` is neither."""
    return bool(_TICKER_RE.match(ticker.upper())
                and _WORKDATE_RE.match(workdate))


def _has_voice(v: _Video) -> bool:
    if not v.fmt or not hasattr(v.core, "_voice_of"):
        return False
    try:
        _script, _text, _events, cdir = v.core._voice_of(v.ws, v.fmt)
    except Exception:                                # noqa: BLE001
        return False
    return cdir is not None and (Path(cdir) / "audio.m4a").is_file()


def video_view(panel, ticker: str, workdate: str,
               step: str | None = None) -> dict:
    """What the workspace screen shows about one video.

    `step` is the one step the page is showing ("now" or "" for the one the
    video waits on): only that step is built, the rest of the rail coming
    from the video's state. The page asks every few seconds, and building
    all ten each time (the script parsed, the claims listed, the cold read,
    the voice's words) was most of what a render's busy bot was asked to do
    (30 Oct 2026). None builds every step."""
    settings = panel.settings
    if not is_video_key(ticker, workdate):
        return {"error": "no such video", "exists": False, "steps": []}
    ws = Workspace(settings, ticker.upper(), workdate)
    st = video_state(settings, ws)
    v = _Video(panel, ws, st, st.fmt)
    out: dict = {"ticker": ws.ticker, "workdate": ws.workdate,
                 "exists": ws.exists, "state": st.to_json()}
    now = current_step(st)
    want = None if step is None else (step if step in _BUILDERS else now)
    steps = []
    has_voice = False
    for name, title in STEPS:
        data: dict | None
        if not ws.exists:
            data = {}
        elif want is not None and name != want:
            data = None
        else:
            try:
                data = _BUILDERS[name](v)
            except Exception as e:                   # noqa: BLE001
                log.exception("panel view %s %s %s", ticker, workdate, name)
                data = {"error": f"{type(e).__name__}: {e}"}
        if data is not None:
            out[name] = data
        if name == "voice":
            has_voice = (bool(data.get("audio_url")) if data is not None
                         else ws.exists and _has_voice(v))
        status = _status(name, st, now, name == "voice" and has_voice)
        steps.append({"id": name, "title": title, "status": status,
                      "summary": (_summary(name, st, data,
                                           name == "voice" and has_voice)
                                  if ws.exists else "")})
    out["steps"] = steps
    out["now"] = now
    out["step"] = want or "all"
    return out
