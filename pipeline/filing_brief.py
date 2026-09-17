"""The pre-angle filing brief (K): read the filing BEFORE choosing the angle.

`/long TICKER` built its angle prompt from workbook numbers only.
`master_prompt_long_angle.md` carried `{{filing_quotes}}`, filled from the
manifest that `auto_filings` writes — and `auto_filings` only runs after an
angle has been picked. So at angle time the slot was always empty, and the
fallback text said so outright: "they are pulled after you pick an angle".

The model proposed angles blind to the filing, and the prompt told it that
was normal (K0).

WHAT THIS PRODUCES is a survey, not evidence: what changed in the risk
factors, where management's language shifted, which segments moved, and —
the highest-value item — anything that contradicts the workbook dashboard
figures. A filing that disagrees with the numbers the operator loaded is
exactly the tension the angle step is looking for.

THE POST-ANGLE PASS STAYS. `auto_filings` does a different job: verbatim
quotes for a specific thesis, located in the DOM, screenshotted for
`[SHOW FILING]`. A survey and a receipt are not the same artefact and are
not merged (K5).

TWO HALVES, TWO DEPENDENCIES (K3). "What changed in the filing" needs only
EDGAR and can start the instant `/long` is typed, in parallel with the
operator refreshing the workbook. "Does this contradict our numbers" needs
the workbook, which does not exist yet — but it is ONE cheap call against
material already summarised, not a second pass. So the reading is queued
immediately and the cross-check folds in when the workbook lands.

NEVER BLOCKS. No filing, no daemon, a timeout, a foreign filer with no
10-K — every one of them degrades to no brief and a normal angle prompt,
and says which it was.
"""

from __future__ import annotations

import hashlib
import json
import logging
import queue
import re
import threading
from concurrent.futures import Future
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from config import Settings

log = logging.getLogger(__name__)

BRIEF_FILE = "filing_brief.json"

# Sections worth reading, in the order they earn their place. Risk Factors
# and MD&A first because that is where a year-over-year change actually
# shows up; `_compress_sections` already prioritises the same two.
_WANTED_SECTIONS = ("Risk Factors", "MD&A", "Market Risk", "Business",
                    "Legal Proceedings")

# Roughly how many characters a token is worth for a modern BPE tokeniser on
# English filing prose. Deliberately pessimistic: the number exists to
# decide whether a prompt FITS, and guessing high there means guessing that
# something fits when it does not — which is the failure this whole field
# is here to reveal.
CHARS_PER_TOKEN = 3.6

# Room reserved inside the context for the system prompt and the answer.
_RESERVE_TOKENS = 1024

_SECTION_SYSTEM = (
    "You read one section of an SEC filing for a deadpan financial video. "
    "In at most six short bullet points, state only what the section SAYS: "
    "specific risks, specific numbers, specific changes in wording. No "
    "opinion, no hype, no investment advice, and never name a data terminal "
    "or vendor. If the section says nothing notable, say 'nothing notable'."
)

_DIFF_SYSTEM = (
    "You compare two years of one company's SEC filings for a deadpan "
    "financial video. Using ONLY the section notes given, write four short "
    "labelled paragraphs:\n"
    "RISK SHIFT: which risk factors are new, dropped, or reworded, and how.\n"
    "LANGUAGE: where management's tone or hedging changed.\n"
    "SEGMENTS: which parts of the business moved, with the figures given.\n"
    "OPEN QUESTION: the single thing a sceptical reader would want asked.\n"
    "If the notes do not support a paragraph, write 'not visible in these "
    "filings' for it rather than inventing one."
)

_CONTRADICTION_SYSTEM = (
    "You cross-check a company's own filing against a separate set of "
    "numbers. Using ONLY what you are given, list every place the filing "
    "and the numbers disagree, or appear to. One line each: what the "
    "numbers say, what the filing says, and why it matters. If nothing "
    "disagrees, write exactly 'no contradictions found'. Never invent a "
    "figure that is not in front of you."
)

_GRADING_SYSTEM = (
    "You are checking whether a company's latest filings support or "
    "undermine claims a previous video made. Using ONLY the section notes "
    "and the prior claims given, take each claim in turn and say: "
    "SUPPORTED, UNDERMINED, or NOT ADDRESSED, followed by one line of "
    "evidence from the notes. Never invent a figure."
)


@dataclass
class FilingBrief:
    """The survey, and an honest account of how complete it is."""

    ticker: str = ""
    # What was read, so the brief can be audited without re-reading it.
    filings: str = ""
    accessions: list[str] = field(default_factory=list)
    sections: int = 0
    # DID EVERY PROMPT FIT? Ollama does not error on an overflowing prompt —
    # it drops the front and summarises what remains, so a brief built from
    # half a section reads exactly like one built from all of it (K2). This
    # is the only field that can say otherwise.
    context_held: bool = True
    body: str = ""
    contradictions: str = ""
    grading: str = ""
    # Why there is no body, when there is not one. `skipped` is a normal
    # outcome here, never an error.
    reason: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.body)

    def to_json(self) -> dict:
        return {"ticker": self.ticker, "filings": self.filings,
                "accessions": list(self.accessions),
                "sections": self.sections, "context_held": self.context_held,
                "body": self.body, "contradictions": self.contradictions,
                "grading": self.grading, "reason": self.reason}

    @classmethod
    def from_json(cls, data: dict) -> "FilingBrief":
        return cls(
            ticker=str(data.get("ticker") or ""),
            filings=str(data.get("filings") or ""),
            accessions=[str(a) for a in (data.get("accessions") or [])],
            sections=int(data.get("sections") or 0),
            context_held=bool(data.get("context_held", True)),
            body=str(data.get("body") or ""),
            contradictions=str(data.get("contradictions") or ""),
            grading=str(data.get("grading") or ""),
            reason=str(data.get("reason") or ""))

    def render_text(self) -> str:
        """What reaches `{{filing_brief}}`.

        An absent brief says why it is absent. The writing prompt used to
        carry a fallback explaining that quotes arrive after the angle is
        picked — text that is simply wrong once a brief can be present, and
        that taught the model to expect an empty slot (K4).
        """
        if not self.body:
            return f"(no filing brief — {self.reason or 'not run'})"
        lines = [f"Read: {self.filings}" if self.filings else ""]
        if not self.context_held:
            # Said first and in capitals, because everything below it may be
            # built from partial text and nothing else in the output would
            # show that.
            lines.append("WARNING: at least one section did not fit the "
                         "model's context window, so the notes below may be "
                         "built from partial text. Treat them as leads, not "
                         "as facts.")
        lines.append(self.body.strip())
        if self.contradictions:
            lines.append("\nAGAINST OUR NUMBERS:\n"
                         + self.contradictions.strip())
        if self.grading:
            lines.append("\nAGAINST WHAT WE SAID LAST TIME:\n"
                         + self.grading.strip())
        return "\n".join(ln for ln in lines if ln)


# --------------------------------------------------------------------------
# Cache: per accession set, under cache_dir, so it survives the workspace.
# --------------------------------------------------------------------------


def cache_path(accessions: list[str], settings: Settings) -> Path:
    """Where the brief for exactly this set of filings lives.

    Keyed on the accessions rather than the ticker and date: a same-day
    re-run lands in the same workspace anyway, and what this buys is the
    re-visit six weeks later against filings that have not changed (K3).

    THE CONTEXT BUDGET IS PART OF THE KEY. It changes the output — a brief
    built under a truncating `num_ctx` is a different, worse artefact than
    one built with room — so a box whose window was raised must not keep
    being served the old, partial brief out of the cache. This is the same
    mistake the defect it guards against was made of: a load-bearing value
    in one place and the thing it governs in another.
    """
    material = "|".join(sorted(accessions)) + f"@{_budget(settings)}"
    key = hashlib.sha256(material.encode()).hexdigest()[:16]
    return settings.cache_dir / "filing_briefs" / f"{key}.json"


def _budget(settings: Settings) -> int:
    """The per-section character budget actually in force."""
    return min(int(settings.filings_llm_max_chars),
               context_budget_chars(settings))


def load_brief(workspace: Path) -> FilingBrief | None:
    """The brief this workspace holds, if the pass has run."""
    try:
        data = json.loads((Path(workspace) / BRIEF_FILE)
                          .read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return FilingBrief.from_json(data)


def save_brief(workspace: Path, brief: FilingBrief,
               settings: Settings | None = None) -> Path:
    """Write the brief into the workspace, and into the cache when we can.

    The workspace copy is what `{{filing_brief}}` and the provenance record
    read; the cache copy is what makes the second run free.
    """
    ws = Path(workspace)
    ws.mkdir(parents=True, exist_ok=True)
    dest = ws / BRIEF_FILE
    payload = json.dumps(brief.to_json(), indent=2)
    dest.write_text(payload, encoding="utf-8")
    if settings is not None and brief.accessions and brief.body:
        cache = cache_path(brief.accessions, settings)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(payload, encoding="utf-8")
    return dest


# --------------------------------------------------------------------------
# The reading.
# --------------------------------------------------------------------------


def context_budget_chars(settings: Settings) -> int:
    """How many characters of prompt the local model can actually hold."""
    tokens = max(int(settings.ollama_num_ctx) - _RESERVE_TOKENS, 256)
    return int(tokens * CHARS_PER_TOKEN)


def _fits(text: str, settings: Settings) -> bool:
    return len(text) <= context_budget_chars(settings)


def _sections_to_read(sections: list[dict], settings: Settings) -> list[dict]:
    """The sections worth reading, longest-first within each title.

    `segment_filing` returns whatever the document had; this narrows it to
    the five that carry a year-over-year signal and drops the boilerplate.
    """
    by_title: dict[str, dict] = {}
    for s in sections:
        title = str(s.get("title") or "")
        if title not in _WANTED_SECTIONS:
            continue
        text = str(s.get("text") or "").strip()
        if len(text) < 200:
            continue
        if title not in by_title or len(text) > len(by_title[title]["text"]):
            by_title[title] = {"title": title, "text": text}
    return [by_title[t] for t in _WANTED_SECTIONS if t in by_title]


def _summarise_sections(ref, sections: list[dict], settings: Settings,
                        counters: dict) -> tuple[list[str], bool]:
    """One summary per section. Returns `(notes, every_prompt_fit)`.

    SEGMENT FIRST, SUMMARISE PER SECTION, CONDENSE AFTER — two full 10-Ks
    fit no local context window, and the condensation pass has to hold every
    section summary from both filings at once, which is the call that gets
    tight (K1, K2b).
    """
    from pipeline.filings import _compress_sections
    from pipeline.llm import chat

    notes: list[str] = []
    held = True
    budget = _budget(settings)
    for section in sections:
        # ASK WHETHER THE SECTION FIT, not whether the packed result did.
        # `_compress_sections` clips to the budget, so the thing it hands
        # back always fits by construction — checking that would be checking
        # nothing, and the truncation would stay exactly as invisible as it
        # is inside Ollama. This is `_compress_sections`'s own clipping
        # condition, asked before it runs.
        raw = str(section.get("text") or "")
        room = budget - len(f"\n## {section['title']}\n")
        if len(raw) > room:
            held = False
        packed = _compress_sections([section], budget)
        counters["llm"] = counters.get("llm", 0) + 1
        out = chat(f"FILING: {ref.form} for {ref.period or ref.filed}\n{packed}",
                   settings, system=_SECTION_SYSTEM,
                   purpose="filing-brief-section")
        if not out:
            continue
        notes.append(f"### {ref.form} {ref.period or ref.filed} — "
                     f"{section['title']}\n{out.strip()}")
    return notes, held


def _read_one(ref, workspace: Path, settings: Settings,
              counters: dict) -> tuple[list[str], int, bool]:
    """Fetch, segment and summarise one filing. Never raises."""
    from pipeline.filings import download_filing, segment_filing

    counters["download"] = counters.get("download", 0) + 1
    path = download_filing(ref, workspace, settings)
    if path is None:
        log.info("filing brief: could not download %s", ref.label)
        return [], 0, True
    html = path.read_text(errors="replace", encoding="utf-8")
    sections = _sections_to_read(segment_filing(html), settings)
    if not sections:
        log.info("filing brief: %s had no readable sections", ref.label)
        return [], 0, True
    notes, held = _summarise_sections(ref, sections, settings, counters)
    return notes, len(sections), held


def build_brief(ticker: str, workspace: Path, settings: Settings, *,
                counters: dict | None = None) -> FilingBrief:
    """The pre-angle pass. NEVER raises; every failure is a `reason`.

    Reads the latest annual report, the prior year's, and the quarterly pair
    beside them — with the Q4 case, where the 10-K is the filing that covers
    the latest quarter, handled by `resolve_filings` rather than coming back
    empty (O3).
    """
    from pipeline.filings import resolve_filings
    from pipeline.llm import chat

    counters = counters if counters is not None else {}
    out = FilingBrief(ticker=ticker.upper())
    if not settings.filings_enabled:
        out.reason = "filings are switched off"
        return out
    try:
        fset = resolve_filings(ticker, settings)
        refs = fset.refs()
        if not refs:
            # A foreign filer, or a ticker the SEC map does not carry.
            out.reason = "no domestic filings for this ticker"
            return out
        out.filings = fset.describe()
        out.accessions = [r.accession for r in refs]

        cached = _from_cache(out.accessions, settings)
        if cached is not None:
            log.info("filing brief: cache hit for %s (%s)",
                     out.ticker, ", ".join(out.accessions))
            return cached

        notes: list[str] = []
        for ref in refs:
            got, n, held = _read_one(ref, workspace, settings, counters)
            notes.extend(got)
            out.sections += n
            out.context_held = out.context_held and held
        if not notes:
            # The daemon is down, the token is missing, or MOCK_MODE is on.
            # All three mean the same thing to the caller and none is an
            # error: a normal angle prompt, with the slot saying why.
            out.reason = "no LLM answered — the filing was not read"
            return out

        joined = "\n\n".join(notes)
        if not _fits(joined, settings):
            # The condensation call is the one that gets tight: every
            # section summary from up to four filings at once.
            out.context_held = False
            joined = joined[:context_budget_chars(settings)]
        counters["llm"] = counters.get("llm", 0) + 1
        body = chat(joined, settings, system=_DIFF_SYSTEM,
                    purpose="filing-brief-condense")
        if not body:
            out.reason = "the condensation pass did not answer"
            return out
        out.body = body.strip()
        _to_cache(out, settings)
    except Exception as e:  # noqa: BLE001 — a survey must never block a render
        log.warning("filing brief: %s failed (%s)", ticker, e)
        out.reason = f"the reading failed ({type(e).__name__})"
    return out


def _to_cache(brief: FilingBrief, settings: Settings) -> None:
    """Cache the finished brief. Written by `build_brief` itself rather than
    by whoever remembers to call `save_brief`, because "the second run costs
    nothing" is a property of the pass, not of its callers."""
    if not (brief.accessions and brief.body):
        return
    try:
        dest = cache_path(brief.accessions, settings)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(brief.to_json(), indent=2), encoding="utf-8")
    except OSError as e:
        log.warning("filing brief: could not cache (%s)", e)


def _from_cache(accessions: list[str], settings: Settings) -> FilingBrief | None:
    try:
        data = json.loads(cache_path(accessions, settings)
                          .read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    brief = FilingBrief.from_json(data)
    return brief if brief.body else None


# --------------------------------------------------------------------------
# The second half: the workbook cross-check, and the update lane's grading.
# --------------------------------------------------------------------------


def _dashboard_lines(data) -> str:
    rows = getattr(data, "dashboard", None) or {}
    out = [f"{k}: {v}" for k, v in rows.items() if v not in (None, "")]
    hist = getattr(data, "history", None) or {}
    labels = getattr(data, "history_years", None) or []
    if labels:
        out.append("periods: " + " | ".join(str(x) for x in labels))
    for key in ("revenue", "net_income", "fcf", "total_debt", "cash"):
        vals = hist.get(key)
        if vals:
            out.append(f"{key}: " + " | ".join(
                "n/a" if v is None else f"{v:g}" for v in vals))
    return "\n".join(out)


def cross_check(brief: FilingBrief, data, settings: Settings, *,
                counters: dict | None = None) -> FilingBrief:
    """ONE call: does the filing disagree with the numbers we loaded?

    The highest-value line in the brief and the cheapest — the material is
    already summarised, so this is a single pass over the notes plus the
    dashboard, not a second reading (K3). Returns the brief either way; a
    failure leaves `contradictions` empty rather than losing the survey.
    """
    from pipeline.llm import chat

    counters = counters if counters is not None else {}
    if not brief.body or data is None:
        return brief
    numbers = _dashboard_lines(data)
    if not numbers.strip():
        return brief
    counters["llm"] = counters.get("llm", 0) + 1
    out = chat(f"OUR NUMBERS:\n{numbers}\n\nFROM THE FILINGS:\n{brief.body}",
               settings, system=_CONTRADICTION_SYSTEM,
               purpose="filing-brief-crosscheck")
    if out:
        brief.contradictions = out.strip()
    return brief


def grade_prior_coverage(brief: FilingBrief, prior: str, settings: Settings, *,
                         counters: dict | None = None) -> FilingBrief:
    """Does the filing support what the last video claimed? (K5b)

    `/update` asks "what changed since we last covered this", which is
    literally a year-over-year filing diff — so the update lane wants this
    brief more than the long lane does. `{{prior_coverage}}` already carries
    the previous video's hook, its conclusion verbatim and the two or three
    claims it made; handing those to the same notes turns a survey into a
    grading input, which is the spine of the update format.
    """
    from pipeline.llm import chat

    counters = counters if counters is not None else {}
    if not brief.body or not (prior or "").strip():
        return brief
    if _looks_like_no_coverage(prior):
        return brief
    counters["llm"] = counters.get("llm", 0) + 1
    out = chat(f"WHAT WE SAID LAST TIME:\n{prior.strip()}\n\n"
               f"FROM THE FILINGS:\n{brief.body}",
               settings, system=_GRADING_SYSTEM,
               purpose="filing-brief-grade")
    if out:
        brief.grading = out.strip()
    return brief


def _looks_like_no_coverage(text: str) -> bool:
    """`prior_coverage` returns its own empty-state prose when there is no
    thesis on file. Grading that would be grading a placeholder."""
    return bool(re.match(r"\s*\(", text or ""))


# --------------------------------------------------------------------------
# Running one, in the background, without owning the process's exit.
# --------------------------------------------------------------------------


class FilingReader:
    """A single background worker for filing readings, and its off switch.

    WHY NOT `ThreadPoolExecutor`. That is what this was, and nothing ever
    called `shutdown()`. Its threads are non-daemon and it registers an
    atexit handler that JOINS them, so stopping the bot during a reading —
    Ctrl-C, a service restart, the desktop sleeping — hung the process for
    the eight to ten minutes the reading had left. That reads as a frozen
    shutdown, the reflex is `kill -9`, and that is how half-written state
    happens. `shutdown(wait=False, cancel_futures=True)` does not fix it
    either: cancel_futures only drops work that has not STARTED, and the
    atexit join still waits for the one in flight.

    WHY NOT THE RENDER QUEUE, which is the other obvious home and has the
    persistence, cancellation and boot-time re-enqueue this lacks. It runs
    ONE job at a time. A reading is eight to ten minutes, and the entire
    point of starting it at `/long` is that it overlaps the operator
    refreshing their workbook — so a queued render would push the reading
    behind it and the upload would then wait `filing_brief_wait_s` for
    something that had not begun. In the other direction a reading would
    delay every render behind it by up to ten minutes. Both are worse than
    the bug being fixed, and `/batch` makes both routine.

    So: one daemon thread, which the interpreter never joins, plus an
    explicit shutdown that says what it abandoned. A brief is disposable by
    construction — losing one costs a normal angle prompt, which is what
    every other failure path here already degrades to — so there is nothing
    to persist and nothing to resume.
    """

    def __init__(self) -> None:
        self._queue: "queue.Queue[tuple[str, Future, Callable[[], FilingBrief]] | None]" = (
            queue.Queue())
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._running: str = ""      # the label of the reading in flight
        self._closed = False

    def submit(self, label: str, fn) -> "Future":
        """Queue `fn` and return its future. Starts the worker on first use."""
        fut: Future = Future()
        with self._lock:
            if self._closed:
                fut.cancel()
                return fut
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(
                    target=self._loop, name="filing-read", daemon=True)
                self._thread.start()
        self._queue.put((label, fut, fn))
        return fut

    def _loop(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            label, fut, fn = item
            if not fut.set_running_or_notify_cancel():
                continue
            with self._lock:
                self._running = label
            try:
                fut.set_result(fn())
            except BaseException as e:  # noqa: BLE001 — a survey never escapes
                fut.set_exception(e)
            finally:
                with self._lock:
                    self._running = ""

    def shutdown(self) -> list[str]:
        """Stop accepting work, drop what has not started, and SAY what was
        abandoned. Returns the labels, so the caller can log them too.

        Never joins the worker: the reading in flight is abandoned on
        purpose, because the alternative is the ten-minute hang this class
        exists to remove.
        """
        with self._lock:
            self._closed = True
            in_flight = self._running
        dropped: list[str] = []
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            if item is None:
                continue
            label, fut, _ = item
            fut.cancel()
            dropped.append(label)
        self._queue.put(None)
        abandoned = ([in_flight] if in_flight else []) + dropped
        for label in abandoned:
            log.warning("filing brief abandoned at shutdown: %s — re-run "
                        "/long %s to read it again (nothing was lost but the "
                        "reading itself)", label, label.split()[0])
        return abandoned
