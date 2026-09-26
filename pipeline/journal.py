"""What the bot did, one line at a time, in a file that survives a restart.

Most of what Dennis does already leaves a record somewhere: a job file, a
script in its workspace, a thesis, a row in the video log. What it never left
was the ORDER of events — which of those happened when, and what the local
model was doing in between. The LLM tally in :mod:`pipeline.llm` is
process-local by design (it answers "what happened in this video") and a
reboot wipes it, so "what did you work on yesterday" had no answer anywhere.

So every event worth remembering appends one JSON line to
``state/journal.jsonl``: a video started, a script received, an approval, a
job queued / started / finished / failed, a delivery, an upload, a thesis
pinned, every pass the local model ran, and every question put to ``/ask``.
:mod:`pipeline.recall` indexes it alongside everything else the bot saves.

**Never fatal.** A journal that cannot be written is a missing line, not a
failed render — the same rule as the thesis bookkeeping. :func:`note`
swallows every error and logs it at debug level.

**Bounded.** Past ``MAX_BYTES`` the file rolls to ``journal.1.jsonl`` and the
older roll is dropped. At a few dozen lines a video that is years of work;
the bound exists so a runaway loop cannot fill the disk.

Times are stored in UTC and read back in the machine's local time, which is
the clock workspace dates are cut on.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable

from config import Settings

log = logging.getLogger(__name__)

JOURNAL_FILE = "journal.jsonl"
ROLLED_FILE = "journal.1.jsonl"
MAX_BYTES = 4_000_000

# The kinds a line can carry. A kind outside this set is still written — a
# journal that refuses a line is worse than one with an odd label — but the
# set is what the index and `/ask` describe to the model.
KINDS: dict[str, str] = {
    "video": "a video was started with /short, /long, /update or /headline",
    "script": "a script was pasted and checked",
    "approved": "the operator approved a script",
    "job": "a render job was queued, started, finished, failed or cancelled",
    "delivered": "a finished video was delivered",
    "uploaded": "a video went up to YouTube",
    "thesis": "a thesis was pinned when a video shipped",
    "ai": "the local model ran one of its passes",
    "asked": "the operator asked the bot a question with /ask",
}

_LOCK = threading.Lock()


@dataclass
class Entry:
    at: str                     # ISO-8601, UTC
    kind: str
    text: str
    ticker: str = ""
    workdate: str = ""
    data: dict = field(default_factory=dict)

    def local_time(self) -> datetime | None:
        try:
            when = datetime.fromisoformat(self.at.replace("Z", "+00:00"))
        except ValueError:
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return when.astimezone()

    def local_date(self) -> date | None:
        when = self.local_time()
        return when.date() if when else None

    def render(self) -> str:
        when = self.local_time()
        stamp = when.strftime("%Y-%m-%d %H:%M") if when else self.at
        who = f" {self.ticker}" if self.ticker else ""
        return f"{stamp}{who} · {self.text}"


def path_for(settings: Settings) -> Path:
    return settings.state_dir / JOURNAL_FILE


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def note(settings: Settings, kind: str, text: str, *, ticker: str = "",
         workdate: str = "", **data) -> None:
    """Append one line. Never raises."""
    try:
        entry = Entry(at=_now(), kind=kind, text=" ".join(str(text).split()),
                      ticker=(ticker or "").upper(), workdate=workdate or "",
                      data={k: v for k, v in data.items() if v not in (None, "")})
        line = json.dumps(asdict(entry), ensure_ascii=False, default=str)
        path = path_for(settings)
        with _LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                if path.stat().st_size > MAX_BYTES:
                    path.replace(path.with_name(ROLLED_FILE))
            except FileNotFoundError:
                pass
            # One write of one line, opened for append: a second process
            # appending at the same moment interleaves whole lines, not bytes.
            with path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception as e:  # noqa: BLE001 — a missing line, never a failure
        log.debug("journal: could not write %s line (%s)", kind, e)


def _read(path: Path) -> list[Entry]:
    out: list[Entry] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, OSError):
        return out
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            out.append(Entry(**{k: row.get(k, d) for k, d in (
                ("at", ""), ("kind", ""), ("text", ""), ("ticker", ""),
                ("workdate", ""), ("data", {}))}))
        except (ValueError, TypeError):
            continue            # a torn last line after a crash is not news
    return out


def entries(settings: Settings, *, ticker: str = "",
            kinds: Iterable[str] = (), since: date | None = None,
            until: date | None = None, limit: int = 0) -> list[Entry]:
    """Lines oldest first, filtered. `since` and `until` are inclusive local
    dates; `limit` keeps the newest N."""
    rows = (_read(path_for(settings).with_name(ROLLED_FILE))
            + _read(path_for(settings)))
    wanted = set(kinds)
    ticker = ticker.upper()
    out = []
    for e in rows:
        if wanted and e.kind not in wanted:
            continue
        if ticker and e.ticker != ticker:
            continue
        if since or until:
            day = e.local_date()
            if day is None or (since and day < since) or (until and day > until):
                continue
        out.append(e)
    return out[-limit:] if limit else out
