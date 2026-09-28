"""The note to the writer: which sentences lost viewers, and what they shared.

`retention_lines` can already say where one published video lost people, to
the sentence, and `/lines` prints it. That answer went to the operator and
stopped there. The writing prompts carry the chapter-type averages and
nothing finer, so the one party who could write the next script differently
never saw a sentence anyone left on.

This closes that loop once a week, per lane:

1. **Pull** fresh retention for every recent upload. Nothing else ever did:
   the curve was fetched only when someone typed `/retention TICKER`.
2. **Count, in code.** The steepest drops across the lane's recent videos,
   against every sentence those videos had: how long they run, whether they
   carry a figure, a turn, a question, where in the video they sit. The
   counts are the evidence and they come from code, never from the model.
3. **Read, on the local model.** The model is handed those sentences and the
   counts and asked what they have in common. Any number it writes that is
   not in what it was given is flagged under the note, the way `/ask` flags
   one.
4. **Carry it** into the lane's writing prompts (`{{retention_note}}`).

Free by construction: the retention pull is the Analytics API, and the model
call never falls through to a paid hosted tier (OpenAI is left out of its
routing). With fewer than `NOTE_FLOOR` videos the note says there is nothing
to go on yet and makes no model call at all: two videos' worst sentences are
an anecdote, and a confident paragraph about them would be worse than none.

Never fatal. No credentials, no daemon, no words on file: each degrades to a
thinner note and says which.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

from config import Settings

log = logging.getLogger(__name__)

NOTES_FILE = "retention_notes.json"
LANES = ("short", "long")

# Videos with sentence-level retention a lane needs before a note says
# anything. The same floor the chapter-type evidence uses.
NOTE_FLOOR = 3
# The most recent videos per lane that feed a note. Older ones describe a
# channel that has since changed its writing.
RECENT_VIDEOS = 12
# Sentences taken from each video: its steepest drops. A long has a few
# hundred sentences and a short a dozen, so the long gives more.
WORST_PER_VIDEO = {"short": 2, "long": 4}
# How far back the weekly pull reaches. A video past this has settled; its
# stored curve is still read.
PULL_WITHIN_DAYS = 90


@dataclass
class LeftLine:
    """One sentence people left on, with the one before it for context."""

    ticker: str
    workdate: str
    text: str
    before: str
    start_s: float
    share: float                         # how far into the video, 0..1
    drop: float                          # watch ratio lost across it
    hold: float


def _path(settings: Settings):
    return settings.state_dir / NOTES_FILE


def load_notes(settings: Settings) -> dict:
    try:
        data = json.loads(_path(settings).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(settings: Settings, notes: dict) -> None:
    path = _path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(notes, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    tmp.replace(path)


# --------------------------------------------------------------------------
# 1. The pull.
# --------------------------------------------------------------------------


def _uploaded(record) -> datetime | None:
    try:
        at = datetime.fromisoformat(str(record.uploaded_at).replace("Z", "+00:00"))
    except ValueError:
        return None
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


def refresh_retention(settings: Settings, *, client=None,
                      today: datetime | None = None) -> tuple[int, str]:
    """Pull the curve for every recent upload. Returns (pulled, reason).

    A clip is skipped: its retention runs on its own clock and no sentence
    timings exist on it. A video too new for data comes back "unavailable"
    from `pull_retention` and simply is not counted.
    """
    from pipeline.youtube import (VideoLog, YouTubeClient, available,
                                  pull_retention, record_format)

    if client is None:
        ok, why = available(settings)
        if not ok:
            return 0, why
        client = YouTubeClient(settings)
    now = today or datetime.now(timezone.utc)
    since = now - timedelta(days=PULL_WITHIN_DAYS)
    pulled = 0
    for record in VideoLog(settings).all():
        if record_format(record) == "clip":
            continue
        at = _uploaded(record)
        if at is not None and at < since:
            continue
        payload = pull_retention(record.video_id, settings, client=client,
                                 today=now)
        if payload.get("status") == "ok":
            pulled += 1
    return pulled, ""


# --------------------------------------------------------------------------
# 2. The counts.
# --------------------------------------------------------------------------


def lane_lines(settings: Settings, fmt: str) -> tuple[list[LeftLine],
                                                      list, int]:
    """(the worst sentences, every sentence, how many videos) for one lane.

    Newest videos first, up to `RECENT_VIDEOS` of those that have
    sentence-level retention at all.
    """
    from pipeline.retention_lines import holds_for_video, narration_for
    from pipeline.youtube import VideoLog, record_format

    records = [r for r in VideoLog(settings).all() if record_format(r) == fmt]
    records.sort(key=lambda r: str(r.uploaded_at), reverse=True)
    worst: list[LeftLine] = []
    every: list = []
    videos = 0
    for record in records:
        if videos >= RECENT_VIDEOS:
            break
        holds = holds_for_video(settings, record,
                                narration_for(settings, record))
        if len(holds) < 2:
            continue
        videos += 1
        every.extend(holds)
        ranked = sorted(range(len(holds)), key=lambda i: holds[i].drop,
                        reverse=True)
        for i in ranked[:WORST_PER_VIDEO.get(fmt, 2)]:
            h = holds[i]
            if h.drop <= 0:
                continue
            worst.append(LeftLine(
                ticker=record.ticker, workdate=record.workdate, text=h.text,
                before=holds[i - 1].text if i > 0 else "",
                start_s=h.start_s,
                share=(h.start_s / record.duration_s
                       if record.duration_s > 0 else 0.0),
                drop=h.drop, hold=h.watch_ratio))
    worst.sort(key=lambda w: w.drop, reverse=True)
    return worst, every, videos


def _pct(part: int, whole: int) -> str:
    return f"{round(100 * part / whole)}%" if whole else "n/a"


def counts_text(worst: list[LeftLine], every: list) -> str:
    """What the sentences people left on share, counted rather than read.

    Each line sets the worst sentences against every sentence of the same
    videos, so a trait every sentence has does not read as a finding.
    """
    from pipeline.retention_lines import _features

    if not worst or not every:
        return ""

    def words(text: str) -> int:
        return len(text.split())

    lines = [f"The {len(worst)} sentences people left on, against all "
             f"{len(every)} sentences of the same videos:"]
    lines.append(f"  words per sentence: "
                 f"{sum(words(w.text) for w in worst) / len(worst):.0f} "
                 f"against {sum(words(h.text) for h in every) / len(every):.0f}")
    worst_f = [_features(w.text) for w in worst]
    every_f = [_features(h.text) for h in every]
    for name in worst_f[0]:
        a = sum(1 for f in worst_f if f[name])
        b = sum(1 for f in every_f if f[name])
        lines.append(f"  {name}: {_pct(a, len(worst))} against "
                     f"{_pct(b, len(every))}")
    early = sum(1 for w in worst if w.share < 0.1)
    late = sum(1 for w in worst if w.share >= 0.8)
    lines.append(f"  where they sit: {early} in the first tenth, "
                 f"{len(worst) - early - late} in the middle, "
                 f"{late} in the last fifth")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# 3. The reading.
# --------------------------------------------------------------------------

_SYSTEM = (
    "You read which sentences of a finance channel's videos viewers stopped "
    "watching on. Say what those sentences have in common that the rest do "
    "not, using only the sentences and counts given. Write at most four "
    "short bullets, each quoting a few words of a sentence it rests on, then "
    "one line starting 'Next script:' with one concrete thing the writer can "
    "do differently. Never invent a number. Never comment on the stocks or "
    "the investment case, only on the writing."
)


def _prompt(fmt: str, worst: list[LeftLine], counts: str) -> str:
    lane = "SHORT (about 50 seconds, vertical)" if fmt == "short" else \
        "LONG (a deep dive of many minutes)"
    rows = []
    for w in worst:
        rows.append(f"- lost {w.drop * 100:.1f} points at {w.start_s:.0f}s "
                    f"({w.share * 100:.0f}% in) of {w.ticker}:")
        if w.before:
            rows.append(f"    before: {w.before}")
        rows.append(f"    left on: {w.text}")
    return (f"Lane: {lane}\n\n{counts}\n\n"
            f"The sentences, steepest drop first:\n" + "\n".join(rows))


def _free_providers(settings: Settings) -> list[str]:
    """The routing, minus the one tier that bills. A weekly note is not worth
    money, and a dead daemon should cost a thinner note, not a charge."""
    from pipeline import llm

    return [p for p in llm.provider_order(settings) if p != llm.OPENAI]


def write_note(settings: Settings, fmt: str, *,
               today: datetime | None = None) -> dict:
    """Rewrite one lane's note and store it. Returns the note."""
    from pipeline import llm
    from pipeline.recall import unsupported_numbers

    now = today or datetime.now(timezone.utc)
    worst, every, videos = lane_lines(settings, fmt)
    counts = counts_text(worst, every)
    note = {"fmt": fmt, "written_at": now.isoformat(), "videos": videos,
            "lines": len(worst), "status": "thin", "counts": counts,
            "reading": "", "flagged": [], "provider": "", "model": "",
            "skipped": ""}
    if videos >= NOTE_FLOOR and worst:
        note["status"] = "ok"
        prompt = _prompt(fmt, worst, counts)
        out = llm.chat_result(prompt, settings, system=_SYSTEM,
                              purpose="retention-note",
                              providers=_free_providers(settings))
        if out:
            note["reading"] = out.text.strip()
            note["flagged"] = unsupported_numbers(out.text, prompt)
            note["provider"], note["model"] = out.provider, out.model
        else:
            note["skipped"] = out.reason
        note["worst"] = [asdict(w) for w in worst[:8]]
    notes = load_notes(settings)
    notes[fmt] = note
    _save(settings, notes)
    return note


def notes_due(settings: Settings, *, today: datetime | None = None) -> bool:
    """Whether any lane's note is missing or older than a week."""
    now = today or datetime.now(timezone.utc)
    notes = load_notes(settings)
    for fmt in LANES:
        try:
            at = datetime.fromisoformat(notes[fmt]["written_at"])
        except (KeyError, TypeError, ValueError):
            return True
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        if now - at >= timedelta(days=settings.retention_note_days):
            return True
    return False


def refresh_notes(settings: Settings, *, client=None,
                  today: datetime | None = None) -> str:
    """The weekly pass: pull, then rewrite both lanes. Returns a summary."""
    from pipeline import journal

    pulled, why = refresh_retention(settings, client=client, today=today)
    parts = [f"retention pulled for {pulled} video(s)" if not why
             else f"no fresh retention ({why.rstrip('.')})"]
    for fmt in LANES:
        note = write_note(settings, fmt, today=today)
        if note["status"] == "ok":
            parts.append(f"{fmt}: from {note['videos']} videos"
                         + ("" if note["reading"] else
                            f", counts only ({note['skipped'] or 'no reading'})"))
        else:
            parts.append(f"{fmt}: {note['videos']} of {NOTE_FLOOR} videos "
                         f"needed, nothing to go on yet")
    summary = "; ".join(parts)
    journal.note(settings, "lessons", summary)
    return summary


# --------------------------------------------------------------------------
# 4. What the writer and the operator see.
# --------------------------------------------------------------------------


def _written(note: dict) -> str:
    return str(note.get("written_at", ""))[:10] or "an unknown date"


def note_block(settings: Settings, fmt: str) -> str:
    """The lane's note, as the writing prompt carries it."""
    note = load_notes(settings).get(fmt)
    if not note:
        return ("(no note yet: nothing published has sentence-level retention "
                "against it. Write the script the story earns.)")
    if note.get("status") != "ok":
        return (f"(as of {_written(note)}, {note.get('videos', 0)} of the "
                f"{NOTE_FLOOR} videos a note needs have sentence-level "
                f"retention. Nothing to act on yet; write the script the story "
                f"earns.)")
    lines = [f"Written {_written(note)} from the {note['videos']} most recent "
             f"{fmt}s with retention.", "", note.get("counts", "")]
    if note.get("reading"):
        lines += ["", "What those sentences share, read by the bot's model:",
                  note["reading"]]
        if note.get("flagged"):
            lines.append(f"(The reading names numbers that are not in the "
                         f"counts: {', '.join(note['flagged'])}. Trust the "
                         f"counts.)")
    lines += ["", "Use it to write THIS script better. It describes sentences, "
              "not stocks: do not reuse their wording, and never drop a beat "
              "the format requires because of it."]
    return "\n".join(lines)


def notes_text(settings: Settings) -> str:
    """`/lessons` — both lanes' notes, as the operator reads them."""
    notes = load_notes(settings)
    if not notes:
        return ("No note yet. It is written weekly once published videos have "
                "retention; /lessons now writes it immediately.")
    out = ["📝 What the writer is told about where viewers left"]
    for fmt in LANES:
        note = notes.get(fmt)
        out.append("")
        if not note:
            out.append(f"{fmt.upper()}: no note yet.")
            continue
        if note.get("status") != "ok":
            out.append(f"{fmt.upper()} ({_written(note)}): "
                       f"{note.get('videos', 0)} of {NOTE_FLOOR} videos with "
                       f"sentence-level retention. Nothing to go on yet.")
            continue
        out.append(f"{fmt.upper()} ({_written(note)}, "
                   f"{note['videos']} videos)")
        out.append(note.get("counts", ""))
        worst = note.get("worst") or []
        if worst:
            out.append("  Steepest:")
            for w in worst[:3]:
                words = w["text"].split()
                opening = " ".join(words[:10]) + ("…" if len(words) > 10 else "")
                out.append(f"    −{w['drop'] * 100:.1f}pts  {w['ticker']}  "
                           f"{opening}")
        if note.get("reading"):
            out.append(note["reading"])
        elif note.get("skipped"):
            out.append(f"(no reading: {note['skipped']})")
        if note.get("flagged"):
            out.append(f"⚠️ numbers not in the counts: "
                       f"{', '.join(note['flagged'])}")
    return "\n".join(out)
