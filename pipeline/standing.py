"""Standing state: what the bot remembers between sessions (P3.3).

Every session started from a blank page. The bot knew nothing about what it
had already covered, what it had said about it, or what was worth looking at
next — so the operator held all of that, and the backlog lived in their head.

Four things live here, and they lean on each other:

* **Thesis tracking.** When a video ships, the thesis and the handful of
  numbers behind it are recorded. On the next refresh those numbers are
  re-read and compared; a material move says an update video is warranted and
  names what moved. This is what makes the THESIS: intact / cracking / broken
  card mean something rather than being a shrug.
* **Idea queue.** A ranked backlog fed by the screener, by thesis triggers,
  and (once the free sources land) by IR feeds. A session opens with a list.
* **`/repurpose` picking 2-3 clips**, not one. A forty-minute cut has more
  than one good minute in it, and the second-best was being thrown away.
* **Overnight batch.** Queue renders to run unattended, and be harmless when
  the machine is off — it is a desktop, not a server, so "the batch didn't run
  because the box was asleep" has to be a non-event.

Everything persists as plain JSON under `state/`, because the interesting
failure is a reboot mid-week, not a schema migration.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from config import Settings

log = logging.getLogger(__name__)

THESES_FILE = "theses.json"
QUEUE_FILE = "idea_queue.json"
BATCH_FILE = "batch.json"

# What "materially moved" means, per metric. A percentage-point metric moving
# 3 points is a different event from a price moving 3%, so these are not one
# number. Anything not listed uses `_DEFAULT_MOVE`.
_MOVE_THRESHOLDS: dict[str, float] = {
    "price": 0.20,              # 20% — the market changed its mind
    "market_cap": 0.20,
    "revenue_ltm": 0.10,
    "fcf": 0.25,                # cash flow is lumpy; a small move is noise
    "net_income": 0.25,
    "gross_margin": 0.05,       # margins are the thesis for most businesses
    "operating_margin": 0.05,
    "net_debt": 0.30,
    "total_debt_now": 0.30,
    "shares_out": 0.05,         # 5% dilution is never nothing
    "pe_ttm": 0.35,
    "ev_ebitda": 0.35,
}
_DEFAULT_MOVE = 0.25

# Metrics worth pinning to a thesis by default — the ones a Dennis video is
# usually *about*.
DEFAULT_TRACKED = ("price", "market_cap", "revenue_ltm", "gross_margin",
                   "operating_margin", "fcf", "shares_out", "net_debt",
                   "pe_ttm")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _read(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def _write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    tmp.replace(path)          # atomic: a crash never leaves half a backlog


# --------------------------------------------------------------------------
# Thesis tracking.
# --------------------------------------------------------------------------


@dataclass
class Move:
    """One tracked number that moved since the thesis was recorded."""

    field: str
    before: float
    after: float

    @property
    def change(self) -> float:
        if self.before in (0, None):
            return 0.0
        return (self.after - self.before) / abs(self.before)

    @property
    def material(self) -> bool:
        return abs(self.change) >= _MOVE_THRESHOLDS.get(self.field, _DEFAULT_MOVE)

    def render(self) -> str:
        pct = self.change * 100
        arrow = "↑" if pct > 0 else "↓"
        return f"{self.field} {arrow}{abs(pct):.0f}% ({_num(self.before)} → {_num(self.after)})"


def _num(v: float) -> str:
    if abs(v) >= 1_000_000_000:
        return f"{v / 1e9:.1f}B"
    if abs(v) >= 1_000_000:
        return f"{v / 1e6:.1f}M"
    if abs(v) >= 1_000:
        return f"{v / 1e3:.1f}K"
    return f"{v:.2f}".rstrip("0").rstrip(".")


@dataclass
class Thesis:
    """What one video claimed, and the numbers it claimed it about.

    `summary` was the whole record for a long time, and it is enough to remind
    the OPERATOR which video this was. It is not enough for a writer: "I said
    the margin would hold, and it didn't" needs the claim, not a label for it.
    So the video's own words are pinned too.

    Every field past `summary` is optional and defaults to empty, because there
    is live state on the operator's disk and this module's whole premise is
    that the interesting failure is a reboot mid-week, not a migration. A
    thesis recorded before these existed still loads, and the prompt says which
    fields are absent rather than inventing them.
    """

    ticker: str
    summary: str                       # the angle, in the operator's words
    numbers: dict[str, float] = field(default_factory=dict)
    recorded_at: str = ""
    workdate: str = ""
    status: str = "intact"             # intact | cracking | broken
    checked_at: str = ""
    last_moves: list[dict] = field(default_factory=list)
    # What the video actually said, for the writer of the next one.
    hook: str = ""                     # what it opened on
    conclusion: str = ""               # the closing claim, verbatim
    claims: list[str] = field(default_factory=list)   # the 2-3 things asserted
    fmt: str = ""                      # short | long

    def to_json(self) -> dict:
        return asdict(self)


class ThesisBook:
    """Every covered ticker's thesis and the numbers behind it."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.path = settings.state_dir / THESES_FILE

    def _all(self) -> dict[str, dict]:
        return _read(self.path, {})

    def get(self, ticker: str) -> Thesis | None:
        row = self._all().get(ticker.upper())
        if not row:
            return None
        # Unknown keys are dropped rather than raised on: a file written by a
        # NEWER build than the one reading it is the other half of the
        # compatibility this record is designed for, and a TypeError there
        # would take the whole book down, not one row.
        known = {f for f in Thesis.__dataclass_fields__}
        return Thesis(**{k: v for k, v in row.items() if k in known})

    def tickers(self) -> list[str]:
        return sorted(self._all())

    def record(self, ticker: str, summary: str, data, *,
               workdate: str = "", tracked: Sequence[str] = (),
               hook: str = "", conclusion: str = "",
               claims: Sequence[str] = (), fmt: str = "") -> Thesis:
        """Pin the thesis, the numbers it rests on, and what it said.

        Everything past `summary` is optional at the call site as well as in
        the record: this runs at ship time, best-effort, and a video that
        delivered must never be turned into a failure by bookkeeping.
        """
        fields = list(tracked or DEFAULT_TRACKED)
        numbers = {}
        for f in fields:
            v = _value_of(data, f)
            if v is not None:
                numbers[f] = v
        t = Thesis(ticker=ticker.upper(), summary=summary.strip(),
                   numbers=numbers, recorded_at=_now().isoformat(),
                   workdate=workdate,
                   hook=(hook or "").strip(),
                   conclusion=(conclusion or "").strip(),
                   claims=[c.strip() for c in claims if c and c.strip()],
                   fmt=fmt)
        rows = self._all()
        rows[t.ticker] = t.to_json()
        _write(self.path, rows)
        log.info("thesis recorded for %s on %d number(s)", t.ticker, len(numbers))
        return t

    def check(self, ticker: str, data) -> tuple[Thesis | None, list[Move]]:
        """Re-read the pinned numbers. Returns (thesis, material moves).

        Only material moves come back. A thesis whose numbers all drifted a
        couple of percent has not changed, and reporting that would train the
        operator to ignore the notification — which is the real failure mode
        of anything that watches numbers.
        """
        t = self.get(ticker)
        if t is None:
            return None, []
        moves: list[Move] = []
        for f, before in t.numbers.items():
            after = _value_of(data, f)
            if after is None or before is None:
                continue
            m = Move(field=f, before=float(before), after=float(after))
            if m.material:
                moves.append(m)

        t.checked_at = _now().isoformat()
        t.last_moves = [asdict(m) | {"change": round(m.change, 4)} for m in moves]
        t.status = _status_for(moves)
        rows = self._all()
        rows[t.ticker] = t.to_json()
        _write(self.path, rows)
        return t, moves

    def set_status(self, ticker: str, status: str) -> None:
        rows = self._all()
        row = rows.get(ticker.upper())
        if row:
            row["status"] = status
            _write(self.path, rows)

    def forget(self, ticker: str) -> bool:
        rows = self._all()
        if rows.pop(ticker.upper(), None) is None:
            return False
        _write(self.path, rows)
        return True


def _status_for(moves: Sequence[Move]) -> str:
    """intact / cracking / broken, from what actually moved.

    Deliberately crude: two material moves, or one big one, is "cracking";
    it takes a lot to call a thesis broken automatically. The operator makes
    the real call — this only decides whether to interrupt them.
    """
    if not moves:
        return "intact"
    worst = max(abs(m.change) for m in moves)
    if len(moves) >= 3 or worst >= 0.5:
        return "broken"
    return "cracking"


def _value_of(data, field_name: str) -> float | None:
    """Pull one number out of a CompanyData, snapshot first then history."""
    if data is None:
        return None
    v = data.get(field_name) if hasattr(data, "get") else None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    row = getattr(data, "history", {}).get(field_name) if hasattr(data, "history") else None
    if row:
        for x in reversed(row):
            if isinstance(x, (int, float)):
                return float(x)
    return None


def update_warranted(moves: Sequence[Move], ticker: str = "") -> str:
    """The message, or "" when nothing is worth interrupting for.

    It names the action now. "An update video is warranted" told the operator
    a conclusion and left them to work out what to type — and what they typed
    was `/long`, which filled a prompt identical to a first-time one and
    forgot everything this notice had just proved the bot knew.
    """
    if not moves:
        return ""
    lines = [m.render() for m in moves[:6]]
    action = (f"\n An update video is warranted: /update {ticker.upper()}"
              if ticker else "\n An update video is warranted.")
    return ("📌 the numbers behind this thesis moved:\n  "
            + "\n  ".join(lines) + action)


# --------------------------------------------------------------------------
# The idea queue.
# --------------------------------------------------------------------------


@dataclass
class Idea:
    ticker: str
    reason: str
    source: str                # screener | thesis | ir | operator
    score: float = 0.0
    lane: str = ""             # short | long | ""
    added_at: str = ""
    seen: bool = False

    def render(self) -> str:
        lane = f" [{self.lane}]" if self.lane else ""
        return f"{self.ticker}{lane} — {self.reason}  ({self.source})"


# How much each source is trusted, before its own score. A thesis trigger is
# the strongest signal the bot has: it already covered the name and something
# it staked a claim on has changed.
_SOURCE_WEIGHT = {"thesis": 3.0, "operator": 2.5, "ir": 1.5, "screener": 1.0}


class IdeaQueue:
    """A ranked backlog, so a session never starts from a blank page."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.path = settings.state_dir / QUEUE_FILE

    def _all(self) -> list[dict]:
        rows = _read(self.path, [])
        return rows if isinstance(rows, list) else []

    def add(self, ticker: str, reason: str, source: str = "screener", *,
            score: float = 0.0, lane: str = "") -> Idea:
        """Add or refresh an idea. One row per ticker — the newest reason wins.

        De-duplicating on the ticker matters: the screener runs daily and a
        beaten-down name stays beaten down, so without this the queue becomes
        the same twenty names repeated.
        """
        idea = Idea(ticker=ticker.upper(), reason=reason.strip(), source=source,
                    score=score, lane=lane, added_at=_now().isoformat())
        rows = [r for r in self._all() if r.get("ticker") != idea.ticker]
        rows.append(asdict(idea))
        _write(self.path, rows)
        return idea

    def extend(self, ideas: Iterable[tuple[str, str, str]]) -> int:
        n = 0
        for ticker, reason, source in ideas:
            self.add(ticker, reason, source)
            n += 1
        return n

    def ranked(self, limit: int = 10, *, include_seen: bool = False) -> list[Idea]:
        out = [Idea(**r) for r in self._all()]
        if not include_seen:
            out = [i for i in out if not i.seen]
        out.sort(key=lambda i: (-(i.score + _SOURCE_WEIGHT.get(i.source, 1.0)),
                                i.added_at))
        return out[:limit]

    def mark_seen(self, ticker: str) -> bool:
        rows = self._all()
        hit = False
        for r in rows:
            if r.get("ticker") == ticker.upper():
                r["seen"] = True
                hit = True
        if hit:
            _write(self.path, rows)
        return hit

    def drop(self, ticker: str) -> bool:
        rows = self._all()
        keep = [r for r in rows if r.get("ticker") != ticker.upper()]
        if len(keep) == len(rows):
            return False
        _write(self.path, keep)
        return True

    def prune(self, max_age_days: int = 30) -> int:
        """Drop stale ideas. A three-week-old "it moved 9% today" is not an idea."""
        cutoff = _now() - timedelta(days=max_age_days)
        rows = self._all()
        keep = []
        for r in rows:
            try:
                when = datetime.fromisoformat(str(r.get("added_at")))
            except ValueError:
                keep.append(r)
                continue
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            if when >= cutoff:
                keep.append(r)
        if len(keep) != len(rows):
            _write(self.path, keep)
        return len(rows) - len(keep)

    def render(self, limit: int = 10) -> str:
        ideas = self.ranked(limit)
        if not ideas:
            return ("💤 the idea queue is empty — /screen fills it, and a "
                    "thesis that moves adds itself.")
        lines = [f"{i + 1}. {idea.render()}" for i, idea in enumerate(ideas)]
        return "🗂 Idea queue\n" + "\n".join(lines)


# --------------------------------------------------------------------------
# Overnight batch.
# --------------------------------------------------------------------------


@dataclass
class BatchItem:
    ticker: str
    fmt: str                   # short | long
    added_at: str = ""
    done_at: str = ""
    error: str = ""


class BatchQueue:
    """Renders queued to run unattended, overnight.

    Harmless when the machine is off, which is the whole design constraint:
    this is a desktop that sleeps, so "the batch didn't run" must be a
    non-event. Nothing expires, nothing is skipped for being late — the next
    time the window opens, the work is still there.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.path = settings.state_dir / BATCH_FILE

    def _all(self) -> list[dict]:
        rows = _read(self.path, [])
        return rows if isinstance(rows, list) else []

    def add(self, ticker: str, fmt: str) -> BatchItem:
        item = BatchItem(ticker=ticker.upper(), fmt=fmt,
                         added_at=_now().isoformat())
        rows = [r for r in self._all()
                if not (r.get("ticker") == item.ticker and r.get("fmt") == fmt
                        and not r.get("done_at"))]
        rows.append(asdict(item))
        _write(self.path, rows)
        return item

    def pending(self) -> list[BatchItem]:
        return [BatchItem(**r) for r in self._all() if not r.get("done_at")]

    def mark_done(self, ticker: str, fmt: str, error: str = "") -> None:
        rows = self._all()
        for r in rows:
            if (r.get("ticker") == ticker.upper() and r.get("fmt") == fmt
                    and not r.get("done_at")):
                r["done_at"] = _now().isoformat()
                r["error"] = error
                break
        _write(self.path, rows)

    def clear(self) -> int:
        rows = self._all()
        _write(self.path, [])
        return len(rows)

    def render(self) -> str:
        items = self.pending()
        if not items:
            return "🌙 nothing queued for the overnight batch."
        lines = [f"  {i.ticker} {i.fmt.upper()}" for i in items]
        window = (f"{self.settings.batch_start_hour:02d}:00–"
                  f"{self.settings.batch_end_hour:02d}:00")
        return (f"🌙 Overnight batch ({len(items)} queued, window {window})\n"
                + "\n".join(lines)
                + "\n  Nothing runs if the machine is off; it waits.")


def in_batch_window(settings: Settings, now: datetime | None = None) -> bool:
    """Is it currently inside the unattended window?

    Handles the window crossing midnight, which is the normal case for
    "overnight" and the easy thing to get wrong.
    """
    current = (now or datetime.now()).time()
    start = time(hour=settings.batch_start_hour % 24)
    end = time(hour=settings.batch_end_hour % 24)
    if start <= end:
        return start <= current < end
    return current >= start or current < end


# --------------------------------------------------------------------------
# Feeding the queue from the screener.
# --------------------------------------------------------------------------


def ideas_from_screen(settings: Settings, result: dict) -> int:
    """Push a screen's candidates into the backlog, ranked by their own score."""
    queue = IdeaQueue(settings)
    n = 0
    for lane_name, lane in (("trending", "short"), ("value", "long")):
        for c in result.get(lane_name, []) or []:
            queue.add(getattr(c, "ticker", ""), getattr(c, "why", "") or "screened",
                      source="screener",
                      score=float(getattr(c, "score", 0.0) or 0.0),
                      lane=lane)
            n += 1
    return n


def ideas_from_thesis_moves(settings: Settings, ticker: str,
                            moves: Sequence[Move]) -> bool:
    """A thesis that moved becomes the strongest kind of idea."""
    if not moves:
        return False
    reason = "thesis moved: " + "; ".join(m.render() for m in moves[:3])
    IdeaQueue(settings).add(ticker, reason, source="thesis",
                            score=2.0 + len(moves), lane="long")
    return True
