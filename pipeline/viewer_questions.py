"""Viewer questions (S7): a closing section of the long, behind a switch.

Once a week the top comments under the public videos of the last sixty days
are read and up to eight real questions kept, word for word. The long's
writer is handed them as a closing section: after the last chapter and
before the sign-off, Dennis answers one or two. It is the cheapest proof a
channel has that somebody is listening, and the questions are usually the
part of the story the video skipped.

His rule (10-18): the questions reach the writer ONLY while the switch
(`VIEWER_QUESTIONS`) is on. Off — the default, since there are no viewers
yet — nothing is read and the prompt carries no trace of it. On with
nothing stored, the same.

The pick is the local model's (free); without it, a comment that asks
something, of a readable length, is a question. Either way, a question that
is not in a comment word for word is dropped: the writer quotes it.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from config import Settings

log = logging.getLogger(__name__)

QUESTIONS_FILE = "viewer_questions.json"
WINDOW_DAYS = 60
REFRESH_DAYS = 7
MAX_QUESTIONS = 8
COMMENTS_PER_VIDEO = 50
MIN_CHARS, MAX_CHARS = 12, 200

_SYSTEM = (
    "You read YouTube comments under a finance channel's videos. Copy out, "
    "word for word, up to eight comments (or the one sentence of a comment) "
    "that ask a real question about a company, a number, a filing or how "
    "investing works. Skip insults, spam, links, compliments, jokes, and "
    "anything about a person. One per line, nothing else. NONE if there are "
    "none.")
_LINK_RE = re.compile(r"https?://|www\.", re.IGNORECASE)
_QUESTION_RE = re.compile(r"[^.?!\n]*\?")
_BULLET_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s*")


def _path(settings: Settings):
    return settings.state_dir / QUESTIONS_FILE


def _norm(text: str) -> str:
    return " ".join((text or "").lower().split())


def load_questions(settings: Settings) -> dict:
    from pipeline.standing import _read

    data = _read(_path(settings), {})
    return data if isinstance(data, dict) else {}


def questions_due(settings: Settings, now: datetime | None = None) -> bool:
    """On, and nothing written in the last week."""
    if not settings.viewer_questions:
        return False
    now = now or datetime.now(timezone.utc)
    try:
        at = datetime.fromisoformat(load_questions(settings)["written_at"])
    except (KeyError, TypeError, ValueError):
        return True
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return now - at >= timedelta(days=REFRESH_DAYS)


def fallback_questions(comments: list[str]) -> list[str]:
    """The asking sentence of each comment that asks something readable."""
    out: list[str] = []
    for comment in comments:
        if _LINK_RE.search(comment):
            continue
        for m in _QUESTION_RE.finditer(comment):
            q = " ".join(m.group(0).split())
            if MIN_CHARS <= len(q) <= MAX_CHARS and _norm(q) not in map(_norm, out):
                out.append(q)
                break
    return out[:MAX_QUESTIONS]


def pick_questions(comments: list[str], settings: Settings) -> list[str]:
    """Up to eight questions, each found word for word in a comment."""
    if not comments:
        return []
    from pipeline.llm import OLLAMA, chat_result

    listed = "\n".join(f"- {' '.join(c.split())[:400]}" for c in comments[:300])
    got = chat_result(f"Comments:\n{listed}", settings, system=_SYSTEM,
                      purpose="viewer-questions", providers=[OLLAMA])
    if not got:
        return fallback_questions(comments)
    pool = [_norm(c) for c in comments]
    out: list[str] = []
    for raw in got.text.splitlines():
        q = _BULLET_RE.sub("", raw).strip().strip('"“”')
        if (not q or q.upper() == "NONE" or _LINK_RE.search(q)
                or not MIN_CHARS <= len(q) <= MAX_CHARS):
            continue
        if any(_norm(q) in c for c in pool) and _norm(q) not in map(_norm, out):
            out.append(q)
    return out[:MAX_QUESTIONS]


def refresh_questions(settings: Settings, client,
                      now: datetime | None = None) -> int:
    """Read the comments and store the questions. Returns how many were kept;
    0 without reading anything while the switch is off."""
    if not settings.viewer_questions:
        return 0
    from pipeline.standing import _write
    from pipeline.youtube import _instant, public_since, public_videos

    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=WINDOW_DAYS)
    comments: list[str] = []
    owner: dict[str, tuple[str, str]] = {}
    for v in public_videos(settings, now):
        when = _instant(public_since(v))
        if when is not None and when < since:
            continue
        try:
            got = client.top_comments(v.video_id, COMMENTS_PER_VIDEO)
        except Exception as e:                     # noqa: BLE001
            log.warning("comments for %s unreadable (%s)", v.video_id, e)
            continue
        for c in got:
            comments.append(c)
            owner[_norm(c)] = (v.video_id, v.ticker)
    picked = pick_questions(comments, settings)
    rows = []
    for q in picked:
        vid, ticker = next((owner[c] for c in owner if _norm(q) in c), ("", ""))
        rows.append({"text": q, "video_id": vid, "ticker": ticker})
    _write(_path(settings), {"written_at": now.isoformat(), "questions": rows})
    return len(rows)


def questions_block(settings: Settings) -> str:
    """{{viewer_questions}}: "" while off or empty, else the closing section."""
    if not settings.viewer_questions:
        return ""
    rows = [r for r in load_questions(settings).get("questions") or []
            if isinstance(r, dict) and r.get("text")]
    if not rows:
        return ""
    listed = "\n".join(
        f"- “{r['text']}”" + (f" (under the {r['ticker']} video)"
                              if r.get("ticker") else "")
        for r in rows[:MAX_QUESTIONS])
    return (
        "### VIEWER QUESTIONS — CLOSING SECTION\n"
        f"{listed}\n"
        "After the last chapter and before the sign-off, answer one or two "
        "of these in Dennis's words, as their own short section: quote the "
        "question, never name the commenter, never answer with a call. Pick "
        "the ones this video's company or numbers can actually answer; if "
        "none can, leave the section out.")
