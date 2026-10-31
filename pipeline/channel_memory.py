"""What the channel has already said: its jokes (S3) and Dennis's facts (S8).

A writer handed a fresh prompt every video has no memory, so it reaches for
the same analogy, the same callback, the same bit, and twenty videos in the
channel is one joke with the nouns swapped. And a character with a story
contradicts himself the moment the story is improvised: a sister who was a
nurse in March is a teacher in June.

The confession ledger already solved this for one kind of line — "a
repetition rule someone has to remember will fail; a ledger makes it
impossible" — and this is the same idea for two more:

* **Used jokes.** At ship time the jokes the writer declared (bible v4: the
  short's `jokes`, the long's `=== JOKES ===`) are kept, the ones the script
  really says. A script that declared none falls back to the local model
  listing the script's jokes, analogies and callbacks, verbatim. Without the model, the lines the voice
  linter already recognises as constructions are kept, plus the line after
  each `[BEAT]`, which is where this register puts its punchlines. The next
  prompt is handed the latest forty, and a check warns when one comes back,
  even reworded.
* **Dennis's facts.** At ship time the local model lists any new fact Dennis
  stated about himself, his family, his friends or his past. Without the
  model, the sentences that name his cast or speak of his own past are kept
  as said. Every prompt is handed the list beside his story.

Both are plain JSON under `state/`, keyed by video, so a final rendered
twice is remembered once. Both are best-effort: a bookkeeping failure never
turns a delivered video into a failed job. Neither runs in mock mode, where
the voice and the numbers are invented and nothing has been said in public.
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from config import Settings
from pipeline.gates import Finding

log = logging.getLogger(__name__)

JOKES_FILE = "used_jokes.json"
FACTS_FILE = "dennis_facts.json"

# How many used jokes the next prompt is handed. Enough to cover the last
# month or so of videos; more is a wall the writer skims. Doubled with bible
# v4, whose floor puts twenty-odd jokes in one long.
PROMPT_JOKES = 80
# How many facts. The facts list is the record and is kept whole; the prompt
# is handed the newest of it.
PROMPT_FACTS = 60
# Per video, so a model that lists the whole script cannot flood the book.
MAX_PER_VIDEO = 15
# The writer's own list is checked against the script before it is kept, so
# it may run longer: a long at the floor declares one a minute.
MAX_DECLARED_PER_VIDEO = 40

# Dennis's cast, as his story names them. A sentence naming one of them is a
# sentence about his life, not about the company.
CAST = ("Kev", "Linda", "Gary", "Megan", "Nan", "Marco", "Tyler", "Mum", "Dad",
        "Bagholders Anonymous")
_CAST_RE = re.compile(r"\b(?:" + "|".join(re.escape(c) for c in CAST) + r")\b"
                      r"|\bmy (?:mum|dad|sister|nan|mother|father|family|"
                      r"flat|plant|account|car|chair)\b", re.IGNORECASE)
_OWN_PAST_RE = re.compile(
    r"\bI(?:'d| had| was| have| 've|'ve)?\s+(?:bought|sold|lost|quit|dropped|"
    r"paid|owned|made|got|did|tried|traded|moved|lived|grew|studied|blew)\b",
    re.IGNORECASE)

_STOP = frozenset("""a an and the of to in on at for with by from is are was were
be been it its it's this that these those as or but if so than then there
their they them he she his her you your we our i i'm my me not no do does did
just very about into over what which who whom how when where why all any
""".split())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z'’-]+", (text or "").lower())
            if w not in _STOP and len(w) > 2}


@dataclass
class Remembered:
    """One line the channel has said, and which video said it."""

    text: str
    key: str = ""                     # TICKER/workdate/fmt
    ticker: str = ""
    workdate: str = ""
    fmt: str = ""
    added_at: str = ""

    def to_json(self) -> dict:
        return asdict(self)


class _Book:
    """A list of remembered lines, newest last, one batch per video."""

    filename = ""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.path = settings.state_dir / self.filename

    def _rows(self) -> list[dict]:
        from pipeline.standing import _read

        rows = _read(self.path, [])
        return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []

    def all(self) -> list[Remembered]:
        known = set(Remembered.__dataclass_fields__)
        out = []
        for row in self._rows():
            if str(row.get("text") or "").strip():
                out.append(Remembered(**{k: v for k, v in row.items()
                                         if k in known}))
        return out

    def recent(self, n: int) -> list[Remembered]:
        rows = self.all()
        return rows[-n:] if n > 0 else rows

    def has(self, key: str) -> bool:
        return any(r.get("key") == key for r in self._rows())

    def add(self, key: str, lines: list[str], *, ticker: str = "",
            workdate: str = "", fmt: str = "") -> int:
        """Remember one video's lines. A video already remembered adds
        nothing, so a final rendered twice is not counted twice.

        Under `standing`'s lock: a delivery remembering its jokes and the
        page saving the edited list each read the book whole and wrote it
        whole, and the second write lost the first."""
        from pipeline.standing import _LOCK

        with _LOCK:
            return self._add(key, lines, ticker=ticker, workdate=workdate,
                             fmt=fmt)

    def _add(self, key: str, lines: list[str], *, ticker: str,
             workdate: str, fmt: str) -> int:
        from pipeline.standing import _write

        if not key or self.has(key):
            return 0
        clean = []
        for line in lines:
            line = " ".join(str(line or "").split())
            if line and line not in clean:
                clean.append(line)
        rows = self._rows()
        stamp = _now()
        # The extractors cap themselves; the writer's checked list may be
        # longer, so the book holds up to that.
        clean = clean[:MAX_DECLARED_PER_VIDEO]
        for line in clean:
            rows.append(Remembered(text=line, key=key, ticker=ticker.upper(),
                                   workdate=workdate, fmt=fmt,
                                   added_at=stamp).to_json())
        if not clean:
            # Recorded anyway, so the next delivery of it is still a repeat.
            rows.append({"text": "", "key": key, "ticker": ticker.upper(),
                         "workdate": workdate, "fmt": fmt, "added_at": stamp})
        _write(self.path, rows)
        return len(clean)

    def replace_all(self, texts: list[str], was: list[str] | None = None) -> int:
        """The panel's edit: the list as he left it. Lines he kept keep their
        video; new lines are his own and carry none.

        `was` is the list the page showed him. A line a shipped video added
        after the page loaded is not one he removed, and is kept: saved from
        a tab left open, the edit dropped it (scan, 24 Oct 2026). And each
        video stays on record as remembered, its lines removed or not, so a
        final rendered again does not add them back."""
        from pipeline.standing import _LOCK

        with _LOCK:
            return self._replace_all(texts, was)

    def _replace_all(self, texts: list[str], was: list[str] | None) -> int:
        from pipeline.standing import _write

        clean = lambda t: " ".join(str(t or "").split())  # noqa: E731
        old = {r.text: r for r in self.all()}
        wanted = [clean(t) for t in texts]
        if was is not None:
            seen = {clean(t) for t in was}
            wanted += [t for t in old if t not in seen and t not in wanted]
        rows = []
        for t in dict.fromkeys(t for t in wanted if t):
            rows.append((old.get(t) or Remembered(text=t, added_at=_now())).to_json())
        kept = {r["key"] for r in rows if r.get("key")}
        for r in self._rows():
            k = r.get("key")
            if k and k not in kept:
                kept.add(k)
                rows.append({**r, "text": ""})
        _write(self.path, rows)
        return sum(1 for r in rows if r["text"])


class JokeBook(_Book):
    filename = JOKES_FILE

    def index(self) -> list[tuple[Remembered, set[str]]]:
        """Every joke with its content words, worked out once: a check of a
        whole script asks about every sentence, and each used to re-read the
        file and re-split every joke in it (four seconds at a thousand
        jokes, and the book is kept whole)."""
        return [(joke, _content_words(joke.text)) for joke in self.all()]

    def repeats(self, sentence: str, *, overlap: float = 0.6,
                skip: tuple[str, str] | None = None,
                index: list[tuple[Remembered, set[str]]] | None = None,
                ) -> list[Remembered]:
        """Used jokes this sentence re-tells: most of the joke's own content
        words are back, in any order — the same analogy with its nouns moved
        is the same analogy. `skip` is (ticker, workdate) of the video being
        checked: its own jokes, recorded when it shipped, are not repeats."""
        have = _content_words(sentence)
        if len(have) < 3:
            return []
        hits = []
        for joke, want in (index if index is not None else self.index()):
            if skip and (joke.ticker.upper(), joke.workdate) == skip:
                continue
            if len(want) < 4:
                continue
            if len(have & want) / len(want) >= overlap:
                hits.append(joke)
        return hits


class FactBook(_Book):
    filename = FACTS_FILE


# --------------------------------------------------------------------------
# Extraction — the local model first, a rule-based reading without it.
# --------------------------------------------------------------------------

_JOKES_SYSTEM = (
    "You read a finished script for a finance video narrated by a deadpan "
    "cartoon character called Dennis. List its jokes: every line built to be "
    "funny or memorable — a joke, an analogy, a callback, a running gag. Copy "
    "each one VERBATIM from the script, one per line, no numbering, no "
    "commentary. At most 15 lines.")

_FACTS_SYSTEM = (
    "You read a finished script for a finance video narrated by a cartoon "
    "character called Dennis. List every NEW fact he states about himself, "
    "his family, his friends, his flat or his past — not facts about any "
    "company. One fact per line, third person, short, e.g. 'Dennis sold his "
    "car in 2022.' Leave out anything already in the KNOWN list. If there is "
    "nothing new, answer NONE.")

_BULLET_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s*")


def _model_lines(prompt: str, settings: Settings, *, system: str,
                 purpose: str) -> list[str] | None:
    """The local model's answer as lines, or None when it did not answer."""
    from pipeline.llm import OLLAMA, chat_result

    out = chat_result(prompt, settings, system=system, purpose=purpose,
                      providers=[OLLAMA])
    if not out:
        return None
    lines = []
    for raw in out.text.splitlines():
        line = _BULLET_RE.sub("", raw).strip().strip('"“”')
        if line and line.upper() != "NONE":
            lines.append(line)
    return lines


def _sentences(text: str) -> list[str]:
    from pipeline.corpus import sentences

    return sentences(text)


def fallback_jokes(script) -> list[str]:
    """The lines the voice linter recognises as constructions, and the line
    after each `[BEAT]` — where this register lands its punchlines."""
    from pipeline.gates import _CONSTRUCTIONS, delivery_text

    text = delivery_text(script)
    found: list[str] = []
    for line in text.splitlines():
        for _name, _described, pattern in _CONSTRUCTIONS:
            for s in _sentences(line):
                if pattern.search(s):
                    found.append(re.sub(r"\[[A-Z ]+\]", "", s).strip())
    for m in re.finditer(r"\[BEAT\]\s*([^\[\n]+)", text):
        said = _sentences(m.group(1))
        if said:
            found.append(said[0].strip())
    out: list[str] = []
    for line in found:
        line = " ".join(line.split())
        if len(line.split()) >= 3 and line not in out:
            out.append(line)
    return out[:MAX_PER_VIDEO]


def declared_jokes_said(script) -> list[str]:
    """The jokes the writer listed that the script really says."""
    from pipeline.writing_checks import _norm, declared_jokes, find_joke

    narration = getattr(script, "narration", None) or getattr(
        script, "audio_script", "")
    words = _norm(narration).split()
    out: list[str] = []
    for _move, line in declared_jokes(script):
        line = " ".join(line.split())
        if line not in out and find_joke(line, words) is not None:
            out.append(line)
    return out[:MAX_DECLARED_PER_VIDEO]


def extract_jokes(script, settings: Settings) -> list[str]:
    narration = getattr(script, "narration", None) or getattr(
        script, "audio_script", "")
    if not narration.strip():
        return []
    declared = declared_jokes_said(script)
    if declared:
        return declared
    got = _model_lines(f"Script:\n\n{narration[:14000]}", settings,
                       system=_JOKES_SYSTEM, purpose="jokes")
    if got is None:
        return fallback_jokes(script)
    return [g for g in got if len(g.split()) >= 3][:MAX_PER_VIDEO]


def fallback_facts(narration: str) -> list[str]:
    out = []
    for s in _sentences(narration):
        s = " ".join(s.split())
        if (_CAST_RE.search(s) or _OWN_PAST_RE.search(s)) and s not in out:
            out.append(f"He said: “{s}”")
    return out[:MAX_PER_VIDEO]


def extract_facts(narration: str, settings: Settings,
                  known: list[str]) -> list[str]:
    if not narration.strip():
        return []
    listed = "\n".join(f"- {k}" for k in known[-120:]) or "(none)"
    got = _model_lines(f"KNOWN:\n{listed}\n\nScript:\n\n{narration[:14000]}",
                       settings, system=_FACTS_SYSTEM, purpose="dennis-facts")
    found = fallback_facts(narration) if got is None else got
    # Never the same fact twice, however the model phrased it.
    seen = [_content_words(k) for k in known]
    out = []
    for fact in found:
        words = _content_words(fact)
        if words and not any(w and len(words & w) / len(words) >= 0.8
                             for w in seen):
            out.append(fact)
            seen.append(words)
    return out[:MAX_PER_VIDEO]


def remember_video(settings: Settings, ticker: str, workdate: str, fmt: str,
                   script) -> dict:
    """Ship-time bookkeeping for one video: its jokes and Dennis's facts.

    Returns what was added. The caller wraps this in a try: it is called
    after a video is delivered, and must never be what fails it.
    """
    key = f"{(ticker or '').upper()}/{workdate}/{fmt}"
    narration = getattr(script, "narration", None) or getattr(
        script, "audio_script", "")
    jokes, facts = JokeBook(settings), FactBook(settings)
    added = {"jokes": 0, "facts": 0}
    if not jokes.has(key):
        added["jokes"] = jokes.add(key, extract_jokes(script, settings),
                                   ticker=ticker, workdate=workdate, fmt=fmt)
    if not facts.has(key):
        known = [f.text for f in facts.all()]
        added["facts"] = facts.add(
            key, extract_facts(narration, settings, known),
            ticker=ticker, workdate=workdate, fmt=fmt)
    if fmt == "long":
        from pipeline.recurring_bits import note_long

        added["bit"] = note_long(settings, key, ticker, workdate, script)
    return added


# --------------------------------------------------------------------------
# What the writer is handed, and the check against it.
# --------------------------------------------------------------------------


def used_jokes_block(settings: Settings) -> str:
    try:
        rows = JokeBook(settings).recent(PROMPT_JOKES)
    except Exception as e:                         # noqa: BLE001 — never fatal
        log.debug("used jokes unreadable (%s)", e)
        rows = []
    if not rows:
        return ("(none yet — this is one of the channel's first videos, so "
                "nothing is used up)")
    lines = ["Newest last. Every one of these has been said on this channel. "
             "Do not use any of them again, and do not re-tell one with the "
             "nouns changed — the check flags that too."]
    for r in rows:
        where = f"{r.ticker}, {r.workdate}" if r.ticker else "added by hand"
        lines.append(f"  - ({where}) {r.text}")
    return "\n".join(lines)


def dennis_story_block(settings: Settings) -> str:
    from pipeline.writing_files import read_file

    text = read_file(settings, "dennis_story").strip()
    return text or "(his story file is missing — keep him as the bible has him)"


def dennis_facts_block(settings: Settings) -> str:
    try:
        rows = FactBook(settings).recent(PROMPT_FACTS)
    except Exception as e:                         # noqa: BLE001
        log.debug("dennis facts unreadable (%s)", e)
        rows = []
    if not rows:
        return ("(none yet — whatever he says about himself in this video "
                "becomes the record the next one has to keep to)")
    lines = ["Already said on camera, newest last. Never contradict one; "
             "build on them instead."]
    lines += [f"  - {r.text}" for r in rows]
    return "\n".join(lines)


def joke_reuse_lint(narration: str, settings: Settings, *,
                    skip: tuple[str, str] | None = None) -> list[Finding]:
    """A used joke, back again — even reworded. `skip` names this video, so
    checking it again after it shipped does not find its own jokes (scan,
    24 Oct 2026)."""
    try:
        book = JokeBook(settings)
        index = book.index()
        if not index:
            return []
    except Exception as e:                         # noqa: BLE001
        log.debug("used jokes unreadable (%s)", e)
        return []
    findings: list[Finding] = []
    for lineno, line in enumerate(narration.splitlines(), 1):
        for said in _sentences(line):
            prior = book.repeats(said, skip=skip, index=index)
            if prior:
                p = prior[-1]
                where = (f"{p.ticker} on {p.workdate}" if p.ticker
                         else "the used-jokes list")
                findings.append(Finding(
                    gate="jokes", severity="warn", line=lineno,
                    message=(f"this joke was already used in {where} — write "
                             f"a new one"),
                    excerpt=p.text[:140]))
                break
    return findings
