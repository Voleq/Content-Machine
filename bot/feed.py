"""The activity feed: every push the bot makes, kept for the web panel.

Telegram is the only place a render-finished push, a storyboard or a failure
used to go. The panel shows the same stream, so it is recorded here as it
is sent: a bounded, in-memory ring with a sequence number the panel polls
from. Nothing here persists — a restart starts a fresh feed, and the
durable record of what happened is the journal and the job store.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field


@dataclass
class FeedEvent:
    seq: int
    at: float
    kind: str                  # notice | file | reply
    text: str = ""
    files: list[str] = field(default_factory=list)
    buttons: list = field(default_factory=list)   # [[{"text", "data"}]]

    def to_json(self) -> dict:
        return {"seq": self.seq, "at": self.at, "kind": self.kind,
                "text": self.text, "files": self.files,
                "buttons": self.buttons}


def keyboard_rows(keyboard) -> list:
    """An inline keyboard (Telegram's or the fallback shape) as plain
    rows of {"text", "data"}; anything else (a ForceReply) as none."""
    rows = getattr(keyboard, "inline_keyboard", None)
    if not rows:
        return []
    return [[{"text": b.text, "data": getattr(b, "callback_data", "") or ""}
             for b in row] for row in rows]


class Feed:
    def __init__(self, size: int = 300):
        self._events: deque[FeedEvent] = deque(maxlen=size)
        self._seq = 0
        self._lock = threading.Lock()

    def add(self, kind: str, text: str = "", files=None,
            keyboard=None) -> FeedEvent:
        with self._lock:
            self._seq += 1
            ev = FeedEvent(self._seq, time.time(), kind, text,
                           [str(f) for f in (files or [])],
                           keyboard_rows(keyboard))
            self._events.append(ev)
            return ev

    def since(self, seq: int) -> list[FeedEvent]:
        with self._lock:
            return [e for e in self._events if e.seq > seq]

    @property
    def last_seq(self) -> int:
        with self._lock:
            return self._seq
