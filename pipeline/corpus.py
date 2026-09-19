"""Every script this channel has ever shipped, in one queryable place.

A script lives in its own workspace directory and is never read again. That
made three separate questions unanswerable:

* "have I used this line before?" — the writer's question, and the one the
  voice bible's *no construction twice* rule can only answer inside a single
  script;
* "how much of this video is the last video with a different ticker?" — the
  question YouTube's inauthentic-content policy asks, which is about
  repetition ACROSS a channel and therefore about exactly the axis nothing
  measured;
* "which sentences held people?" — which needs somewhere to put the retention
  join in :mod:`pipeline.retention_lines`.

So: one index, built by walking the workspaces, keyed on ticker and workdate,
carrying the narration and whatever the video log knows about what happened
to it. It is a cache, not a source of truth — :func:`build_index` rebuilds it
from the workspaces whenever it is asked to, and a workspace that has been
pruned by :mod:`pipeline.cleanup` keeps its entry, because the scripts are
the small files cleanup deliberately leaves behind.

**The comparison masks the data.** Two videos about different companies share
no figures and no ticker, so comparing raw text would say they are unrelated
no matter how identically they are built. The scaffolding is what repeats, so
numbers, tickers and company names are masked to placeholders before the
shingles are taken. What is left is the shape of the writing, which is the
thing the policy is about.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from config import Settings

log = logging.getLogger(__name__)

INDEX_FILE = "script_corpus.json"

# Five words is long enough that an ordinary English collocation ("at the end
# of the") does not dominate, and short enough that a reworded sentence still
# overlaps with its original. Below four, every script matches every other;
# above seven, a single changed word hides a copied paragraph.
SHINGLE_N = 5

_NUM_RE = re.compile(r"\b\d[\d,.]*\s*(?:%|bn|mn|m|k|b|x)?\b", re.I)
_TICKER_RE = re.compile(r"\b[A-Z]{2,5}\b")
_WORD_RE = re.compile(r"[a-z']+|#")
# Splits BETWEEN sentences and keeps each one's terminator, because the
# terminator is data: a question mark is what the linter reads as a turn, and
# a writer asking "have I used this line" means the line as they typed it.
_SENTENCE_END_RE = re.compile(
    r"(?:(?<=[.!?])|(?<=[.!?][\"')\]]))\s+|\n+")


def mask_data(text: str) -> str:
    """The script with its figures and names replaced by placeholders.

    What survives is the scaffolding: the connectives, the framing, the
    rhetorical moves. Two scripts that say the same thing about different
    companies collapse onto the same text here, which is the whole point —
    that collapse is the signal.
    """
    masked = _NUM_RE.sub(" # ", text)
    masked = _TICKER_RE.sub(" # ", masked)
    return masked


def shingles(text: str, n: int = SHINGLE_N) -> set[tuple[str, ...]]:
    """Overlapping n-word windows over the masked, lowercased text."""
    words = _WORD_RE.findall(mask_data(text).lower())
    if len(words) < n:
        return {tuple(words)} if words else set()
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


def jaccard(a: set, b: set) -> float:
    """Overlap as a fraction of everything either side used. 0 when either
    side is empty — an empty script is not similar to anything, it is
    unreadable, and the caller says so in its own words."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def sentences(text: str) -> list[str]:
    """The narration split the way the linters split it."""
    out = [s.strip() for s in _SENTENCE_END_RE.split(text)]
    return [s for s in out if s]


@dataclass
class ScriptEntry:
    """One shipped script, and what is known about what happened to it."""

    ticker: str
    workdate: str
    fmt: str                                # short | long
    narration: str = ""
    hook: str = ""                          # the opening line, as spoken
    words: int = 0
    video_id: str = ""
    title: str = ""
    uploaded_at: str = ""
    duration_s: float = 0.0
    # Average watch ratio over the whole video, when retention has been
    # pulled. `None` means unknown, which is not the same as zero.
    hold: float | None = None

    @property
    def key(self) -> str:
        return f"{self.ticker}/{self.workdate}/{self.fmt}"

    def to_json(self) -> dict:
        return asdict(self)


def _narration_of(payload: dict) -> str:
    """The spoken text, whichever format's JSON this is."""
    return str(payload.get("narration") or payload.get("audio_script") or "")


def _read_script(path: Path) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        log.debug("corpus: unreadable script at %s (%s)", path, e)
        return None
    return payload if isinstance(payload, dict) else None


def _video_index(settings: Settings) -> dict[str, dict]:
    """What the video log knows, keyed on `TICKER/workdate`.

    Read through a try: a corpus that cannot be built because nothing has ever
    been uploaded is a corpus of scripts, which is still useful.
    """
    try:
        from pipeline.youtube import VideoLog

        records = VideoLog(settings).all()
    except Exception as e:  # noqa: BLE001 — the scripts are the point
        log.debug("corpus: video log unreadable (%s)", e)
        return {}
    out: dict[str, dict] = {}
    for rec in records:
        if not rec.workdate:
            continue
        rows = (rec.retention or {}).get("rows") or []
        ratios = [r.get("watch_ratio") for r in rows
                  if isinstance(r, dict) and isinstance(
                      r.get("watch_ratio"), (int, float))]
        out[f"{rec.ticker}/{rec.workdate}"] = {
            "video_id": rec.video_id,
            "title": rec.title,
            "uploaded_at": rec.uploaded_at,
            "duration_s": rec.duration_s,
            "hold": (sum(ratios) / len(ratios)) if ratios else None,
        }
    return out


def build_index(settings: Settings) -> list[ScriptEntry]:
    """Walk the workspaces and read every script that was ever saved.

    Ordered oldest first, so "the last ten" is a slice off the end and a
    caller comparing against history never has to sort.
    """
    base = settings.workspace_dir
    videos = _video_index(settings)
    entries: list[ScriptEntry] = []
    if not base.is_dir():
        return entries
    for ticker_dir in sorted(p for p in base.iterdir() if p.is_dir()):
        for date_dir in sorted(p for p in ticker_dir.iterdir() if p.is_dir()):
            for fmt in ("short", "long"):
                payload = _read_script(date_dir / f"script_{fmt}.json")
                if payload is None:
                    continue
                narration = _narration_of(payload)
                if not narration.strip():
                    continue
                said = sentences(narration)
                meta = videos.get(f"{ticker_dir.name}/{date_dir.name}", {})
                entries.append(ScriptEntry(
                    ticker=ticker_dir.name,
                    workdate=date_dir.name,
                    fmt=fmt,
                    narration=narration,
                    hook=said[0] if said else "",
                    words=len(narration.split()),
                    video_id=str(meta.get("video_id", "")),
                    title=str(meta.get("title", "")),
                    uploaded_at=str(meta.get("uploaded_at", "")),
                    duration_s=float(meta.get("duration_s") or 0.0),
                    hold=meta.get("hold"),
                ))
    entries.sort(key=lambda e: (e.workdate, e.ticker, e.fmt))
    return entries


class Corpus:
    """The index, with the questions worth asking of it.

    Built from the workspaces on construction. The JSON cache exists so a
    command that only wants to print the last five hooks does not walk every
    workspace on disk; :meth:`refresh` rebuilds it, and any caller that needs
    certainty passes ``fresh=True``.
    """

    def __init__(self, settings: Settings, *, fresh: bool = False):
        self.settings = settings
        self.path = settings.state_dir / INDEX_FILE
        self.entries: list[ScriptEntry] = []
        if fresh or not self._load():
            self.refresh()

    # ------------------------------------------------------------- storage
    def _load(self) -> bool:
        try:
            rows = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if not isinstance(rows, list):
            return False
        try:
            self.entries = [ScriptEntry(**r) for r in rows]
        except TypeError:
            # The shape changed under an old cache. Rebuilding is free.
            return False
        return True

    def refresh(self) -> "Corpus":
        self.entries = build_index(self.settings)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps([e.to_json() for e in self.entries], indent=1),
                encoding="utf-8")
        except OSError as e:  # noqa: BLE001 — the index in memory is usable
            log.warning("corpus: could not write the index (%s)", e)
        return self

    # ------------------------------------------------------------- queries
    def __len__(self) -> int:
        return len(self.entries)

    def for_format(self, fmt: str) -> list[ScriptEntry]:
        return [e for e in self.entries if e.fmt == fmt]

    def recent(self, n: int, *, fmt: str = "",
               exclude: str = "") -> list[ScriptEntry]:
        """The n most recent entries, newest last. `exclude` drops one key —
        the script being checked, which is in the corpus if it was saved."""
        rows = [e for e in self.entries
                if (not fmt or e.fmt == fmt) and e.key != exclude]
        return rows[-n:] if n > 0 else rows

    def search(self, phrase: str, *, limit: int = 20) -> list[tuple[ScriptEntry, str]]:
        """Every sentence that contains this phrase, with the script it is in.

        Case- and whitespace-insensitive; matched against the narration as
        written, not the masked text, because a writer asking "have I used
        this line" means the line they typed.
        """
        needle = " ".join(phrase.lower().split())
        if not needle:
            return []
        hits: list[tuple[ScriptEntry, str]] = []
        for entry in reversed(self.entries):
            for said in sentences(entry.narration):
                if needle in " ".join(said.lower().split()):
                    hits.append((entry, said))
                    if len(hits) >= limit:
                        return hits
        return hits

    def hooks(self, *, fmt: str = "short") -> list[tuple[ScriptEntry, float]]:
        """Openers that have retention against them, best hold first."""
        rows = [(e, e.hold) for e in self.for_format(fmt)
                if e.hook and e.hold is not None]
        return sorted(((e, float(h)) for e, h in rows),
                      key=lambda r: r[1], reverse=True)


# --------------------------------------------------------------------------
# Similarity — the measurement idea 01's gate is built on.
# --------------------------------------------------------------------------


@dataclass
class Overlap:
    """How much one script repeats another."""

    entry: ScriptEntry
    phrasing: float                      # masked shingle overlap, 0..1
    shared: list[str] = field(default_factory=list)   # the repeated runs

    @property
    def percent(self) -> int:
        return round(self.phrasing * 100)


def _runs_from(shared: set[tuple[str, ...]], text: str,
               limit: int = 3) -> list[str]:
    """The longest repeated stretches, as the writer would recognise them.

    Shingles are five-word tuples and a reader cannot see a tuple, so adjacent
    shingles are stitched back into the longest runs they form and reported as
    phrases.
    """
    if not shared:
        return []
    words = _WORD_RE.findall(mask_data(text).lower())
    flagged = [False] * len(words)
    for i in range(len(words) - SHINGLE_N + 1):
        if tuple(words[i:i + SHINGLE_N]) in shared:
            for j in range(i, i + SHINGLE_N):
                flagged[j] = True
    runs: list[str] = []
    current: list[str] = []
    for word, hit in zip(words, flagged):
        if hit:
            current.append(word)
        elif current:
            runs.append(" ".join(current))
            current = []
    if current:
        runs.append(" ".join(current))
    runs.sort(key=lambda r: len(r.split()), reverse=True)
    return runs[:limit]


def compare(narration: str, against: list[ScriptEntry]) -> list[Overlap]:
    """This script against each of those, most similar first."""
    mine = shingles(narration)
    out: list[Overlap] = []
    for entry in against:
        theirs = shingles(entry.narration)
        score = jaccard(mine, theirs)
        out.append(Overlap(entry=entry, phrasing=score,
                           shared=_runs_from(mine & theirs, narration)))
    out.sort(key=lambda o: o.phrasing, reverse=True)
    return out


# --------------------------------------------------------------------------
# The gate (01).
# --------------------------------------------------------------------------

# How many earlier scripts a new one is checked against. Ten is roughly a
# month of output on both lanes, which is the window a viewer scrolling a
# channel page actually sees.
SAMENESS_WINDOW = 10

# Above this, the script repeats a previous one enough to say so. Chosen
# against the masked text, where two videos built from the same scaffolding
# score above 0.8 and two genuinely different ones sit under 0.1 — so 0.35 is
# well clear of ordinary English and well under a template.
SAMENESS_WARN = 0.35

# Above this it is the same video with a different ticker. It blocks, because
# the monetisation rule it protects is not a style preference: YouTube's
# inauthentic-content policy names templated, low-variation output as
# ineligible, and a channel learns it crossed that line by losing revenue.
SAMENESS_BLOCK = 0.60


def sameness_check(script, settings: Settings) -> list:
    """This script against the ones already shipped.

    The thirteenth gate. Every other gate asks whether this video is true;
    this one asks whether it is another copy of the last one, which is the
    axis the platform's own rule is written on and the one nothing measured.

    Never fatal in its own machinery: a corpus that cannot be built is a
    corpus of nothing, and a first video has nothing to be similar to.
    """
    from pipeline.gates import Finding, delivery_text

    narration = delivery_text(script)
    if not narration.strip():
        return []
    fmt = "long" if getattr(script, "narration", None) else "short"
    try:
        corpus = Corpus(settings, fresh=True)
    except Exception as e:  # noqa: BLE001 — a gate never takes the run down
        log.warning("sameness: the corpus could not be read (%s)", e)
        return []
    ticker = str(getattr(script, "ticker", "")).upper()
    prior = [e for e in corpus.recent(SAMENESS_WINDOW, fmt=fmt)
             if e.ticker != ticker]
    if not prior:
        return []
    top = compare(narration, prior)[0]
    if top.phrasing < SAMENESS_WARN:
        return []
    severity = "block" if top.phrasing >= SAMENESS_BLOCK else "warn"
    shared = top.shared[0] if top.shared else ""
    tail = ("" if severity == "warn" else
            " — this is the same video with a different ticker, which is "
            "what the inauthentic-content rule is written about")
    return [Finding(
        "sameness", severity,
        f"{top.percent}% of this script's phrasing is shared with "
        f"{top.entry.ticker} ({top.entry.workdate}){tail}",
        excerpt=shared[:120])]
