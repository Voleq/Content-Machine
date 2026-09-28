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
import unicodedata
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
    "Write at most six points, each stating only what the section SAYS: a "
    "specific risk, a specific number, a specific change in wording. No "
    "opinion, no hype, no investment advice, and never name a data terminal "
    "or vendor.\n"
    "Every point is exactly two lines:\n"
    "POINT: <what the section says, in your own words, with any figure>\n"
    "SOURCE: \"<the one sentence it comes from, copied word for word>\"\n"
    "Copy the sentence exactly as the section has it: no shortening, no "
    "ellipsis, no rewording. Leave out any point you cannot back with one "
    "sentence from the section. If the section says nothing notable, write "
    "'nothing notable'."
)

_DIFF_SYSTEM = (
    "You compare two years of one company's SEC filings for a deadpan "
    "financial video. Using ONLY the numbered points given, write four short "
    "labelled paragraphs:\n"
    "RISK SHIFT: which risk factors are new, dropped, or reworded, and how.\n"
    "LANGUAGE: where management's tone or hedging changed.\n"
    "SEGMENTS: which parts of the business moved, with the figures given.\n"
    "OPEN QUESTION: the single thing a sceptical reader would want asked.\n"
    "After every statement, give the numbers of the points it rests on in "
    "square brackets, like [P3] or [P3, P7]. If the points do not support a "
    "paragraph, write 'not visible in these filings' for it rather than "
    "inventing one."
)

_CONTRADICTION_SYSTEM = (
    "You cross-check a company's own filing against a separate set of "
    "numbers. Using ONLY what you are given, list every place the filing "
    "and the numbers disagree, or appear to. One line each: what the "
    "numbers say, what the filing says with the number of the point it "
    "comes from in square brackets (like [P4]), and why it matters. If "
    "nothing disagrees, write exactly 'no contradictions found'. Never "
    "invent a figure that is not in front of you."
)

_GRADING_SYSTEM = (
    "You are checking whether a company's latest filings support or "
    "undermine claims a previous video made. Using ONLY the numbered points "
    "and the prior claims given, take each claim in turn and say: "
    "SUPPORTED, UNDERMINED, or NOT ADDRESSED, followed by one line of "
    "evidence from the points with their numbers in square brackets (like "
    "[P4]). Never invent a figure."
)


# --------------------------------------------------------------------------
# Points: what the local model says a section says, and the sentence behind it.
# --------------------------------------------------------------------------
#
# WHY EVERY POINT CARRIES ITS SENTENCE. The brief is written by a 12B model
# on the operator's own box, and it is the input the angle is chosen from.
# A small model's summary reads exactly as confident when it misreads a
# figure as when it gets one right, and nothing downstream could tell. So
# each point now names the one sentence it came from; code throws out any
# point whose sentence is not actually in the section the model was shown;
# and the angle prompt has the writer (Claude, in the operator's own chat,
# at no extra cost) check each surviving point against its sentence before
# building on it. Code proves the sentence is real; the writer judges
# whether the point reads it right. Neither half can do the other's job.

# A shorter "sentence" matches too easily to prove anything.
_MIN_SOURCE_WORDS = 5

# Past this the full sentence is a table row or a run-on the segmenter
# glued together, and the model's own span is the more useful thing to show.
_MAX_SENTENCE_CHARS = 700

_WORD = re.compile(r"[a-z0-9]+", re.I)
_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s*")
# The labels in capitals or title case only: "the main source: of cash" in a
# point's own words is not a label.
_POINT_LINE = re.compile(r"^\**\s*(?:POINT|Point)\s*\**\s*[:\-–]\s*\**\s*(.*)$")
_SOURCE_AT = re.compile(r"\**\s*(?:SOURCE|Source)\s*\**\s*[:\-–]\s*\**\s*")
_QUOTES = "\"'“”‘’`"
# Where a sentence ends: terminal punctuation, maybe a closing quote, then
# whitespace and something that starts a sentence. "$89.0" and "1.5x" never
# qualify, because nothing follows the period but a digit.
_SENTENCE_END = re.compile(r"[.!?][\"”’)]?(?=\s+[A-Z0-9\"“(]|\s*$)")
# A citation is P-numbers inside brackets: "[P3]", "[P3, P7]", "[P3][P7]",
# and the "(P3)" a small model writes instead. Loose in a sentence, "P500"
# is as likely to be the S&P.
_CITE_GROUP = re.compile(r"[\[(]([^\])]*)[\])]")
_CITE = re.compile(r"\bP(\d+)\b", re.I)


@dataclass
class Point:
    """One thing a filing section says, and the sentence it says it."""

    n: int = 0
    # "10-K 2025-12-31" and "Risk Factors": which year's filing matters as
    # much as the sentence, because the brief compares two of them.
    filing: str = ""
    section: str = ""
    text: str = ""
    # The WHOLE sentence from the filing, not the model's copy of part of
    # it: a clause cut from "Although we expected margins to recover, they
    # did not" reads the opposite way on its own.
    source: str = ""
    # Figures in the point that its own sentence does not carry. A hint for
    # the writer's check, never a reason to drop: a point can fairly restate
    # "$89.0 million" as "$89 million".
    unmatched: list[str] = field(default_factory=list)

    @property
    def tag(self) -> str:
        return f"P{self.n}"

    def to_json(self) -> dict:
        return {"n": self.n, "filing": self.filing, "section": self.section,
                "text": self.text, "source": self.source,
                "unmatched": list(self.unmatched)}

    @classmethod
    def from_json(cls, data: dict) -> "Point":
        return cls(n=int(data.get("n") or 0),
                   filing=str(data.get("filing") or ""),
                   section=str(data.get("section") or ""),
                   text=str(data.get("text") or ""),
                   source=str(data.get("source") or ""),
                   unmatched=[str(x) for x in (data.get("unmatched") or [])])


def _parse_points(answer: str) -> list[tuple[str, str]]:
    """`(point, source)` pairs out of a section answer, source "" when the
    model gave none.

    Takes the two-line POINT/SOURCE shape the instruction asks for, and the
    shapes a small model drifts into instead: both on one line, bulleted,
    bolded, a sentence wrapped onto a second line, or a bare bullet with no
    source at all (kept here so the caller counts it as dropped rather than
    never seeing it).
    """
    pairs: list[list[str]] = []
    for raw in (answer or "").splitlines():
        bulleted = bool(_BULLET.match(raw))
        line = _BULLET.sub("", raw.strip()).strip()
        if not line or line.lower().startswith("nothing notable"):
            continue
        m = _POINT_LINE.match(line)
        body = m.group(1) if m else line
        parts = _SOURCE_AT.split(body, maxsplit=1)
        if len(parts) > 1:
            head, source = parts[0].strip(), parts[1].strip()
            if head or m:
                pairs.append([head, source])
            elif pairs and not pairs[-1][1]:
                # "SOURCE: ..." on its own line belongs to the point above.
                pairs[-1][1] = source
            continue
        if m or bulleted:
            pairs.append([body, ""])
        elif pairs and pairs[-1][1] and not _closed(pairs[-1][1]):
            pairs[-1][1] += " " + line       # a sentence wrapped in two
        elif pairs and not pairs[-1][1]:
            pairs[-1][0] += " " + line       # a point wrapped in two
        elif not line.endswith(":"):         # a "Here are the points:" preamble
            pairs.append([line, ""])
    out = []
    for text, source in pairs:
        text = text.strip().rstrip(" -–|").strip()
        if not text or text.lower().startswith("nothing notable"):
            continue
        out.append((text, source.strip().strip(_QUOTES).strip()))
    return out


def _closed(source: str) -> bool:
    """Whether a quoted source already ended on the line it started."""
    tail = source.rstrip()
    return len(tail) > 1 and tail[-1] in _QUOTES


def _words(text: str) -> list[str]:
    return _WORD.findall(unicodedata.normalize("NFKC", text or "").lower())


def find_sentence(section: str, quote: str) -> str | None:
    """The sentence of `section` that `quote` was copied from, or None.

    VERBATIM TO THE WORD, NOT TO THE BYTE. The words have to appear in the
    section in the same order with nothing between them; punctuation, curly
    quotes, dashes, spacing and case do not count, because the model's copy
    of "$89.0 million — up 3%" differs from the filing's in exactly those
    and in nothing that matters. An ellipsis is a cut, and a cut is not a
    copy.
    """
    if "..." in quote or "…" in quote:
        return None
    needle = _words(quote)
    if len(needle) < _MIN_SOURCE_WORDS:
        return None
    text = unicodedata.normalize("NFKC", section or "")
    spans = [(m.group(0).lower(), m.start(), m.end())
             for m in _WORD.finditer(text)]
    words = [w for w, _, _ in spans]
    k = len(needle)
    first = needle[0]
    for i, w in enumerate(words):
        if w != first or words[i:i + k] != needle:
            continue
        start, end = spans[i][1], spans[i + k - 1][2]
        before = [m.end() for m in _SENTENCE_END.finditer(text, 0, start)]
        s0 = before[-1] if before else 0
        after = _SENTENCE_END.search(text, end)
        s1 = after.end() if after else len(text)
        whole = text[s0:s1].strip()
        if len(whole) > _MAX_SENTENCE_CHARS:
            whole = text[start:end].strip()
        return whole
    return None


def _check_points(pairs: list[tuple[str, str]], packed: str, filing: str,
                  section: str) -> tuple[list[Point], int]:
    """Keep the points whose sentence is in what the model was shown.

    Checked against `packed`, the clipped text the model actually read, not
    the whole section: a "quote" from past the clip is one the model cannot
    have copied, however real it is.
    """
    from pipeline.recall import unsupported_numbers

    kept: list[Point] = []
    dropped = 0
    for text, quote in pairs:
        sentence = find_sentence(packed, quote) if quote else None
        if sentence is None:
            dropped += 1
            continue
        kept.append(Point(filing=filing, section=section, text=text,
                          source=sentence,
                          unmatched=unsupported_numbers(
                              text, f"{sentence} {filing}")))
    return kept, dropped


def _points_listing(points: list[Point]) -> str:
    """The points without their sentences, grouped by filing and section —
    what the condensation, cross-check and grading calls read. The
    sentences stay out of those: they would triple the prompt, and the
    small model has nothing to do with them."""
    lines: list[str] = []
    head = None
    for p in points:
        if (p.filing, p.section) != head:
            head = (p.filing, p.section)
            lines.append(f"\n### {p.filing} — {p.section}")
        lines.append(f"[{p.tag}] {p.text}")
    return "\n".join(lines).strip()


def _cited(text: str) -> set[int]:
    return {int(n) for group in _CITE_GROUP.findall(text or "")
            for n in _CITE.findall(group)}


def _keep_cited_lines(text: str, points: list[Point]) -> tuple[str, int]:
    """Drop the contradiction lines that cite no point in the brief.

    A contradiction is the line the angle is most likely to be built on,
    and one with no point behind it has no sentence the writer can check
    it against — so it goes, and the brief says how many went.
    """
    real = {p.n for p in points}
    body = (text or "").strip()
    if not body or body.lower().startswith("no contradictions found"):
        return body, 0
    kept, dropped = [], 0
    for line in body.splitlines():
        if not line.strip():
            continue
        if _cited(line) & real:
            kept.append(line)
        else:
            dropped += 1
    return "\n".join(kept), dropped


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
    # Every point the paragraphs above may cite, each with the filing
    # sentence it came from; and how many the model offered that code threw
    # out because their sentence is not in the filing. Empty on a brief
    # written before points carried sentences.
    points: list[Point] = field(default_factory=list)
    dropped: int = 0
    # Contradiction lines that cited no point, and so were thrown out.
    unbacked: int = 0
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
                "grading": self.grading,
                "points": [p.to_json() for p in self.points],
                "dropped": self.dropped, "unbacked": self.unbacked,
                "reason": self.reason}

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
            points=[Point.from_json(p) for p in (data.get("points") or [])
                    if isinstance(p, dict)],
            dropped=int(data.get("dropped") or 0),
            unbacked=int(data.get("unbacked") or 0),
            reason=str(data.get("reason") or ""))

    def render_text(self) -> str:
        """What reaches `{{filing_brief}}`.

        An absent brief says why it is absent. The writing prompt used to
        carry a fallback explaining that quotes arrive after the angle is
        picked — text that is simply wrong once a brief can be present, and
        that taught the model to expect an empty slot (K4).

        The points come LAST, with their sentences, because they are what
        the writer checks everything above against; a paragraph citing a
        point that is not in the brief is named rather than silently kept.
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
        if not self.points:
            lines.append("(this brief was written before its points carried "
                         "the filing sentence behind them, so nothing below "
                         "can be checked: treat all of it as leads)")
        lines.append(self.body.strip())
        if self.contradictions:
            lines.append("\nAGAINST OUR NUMBERS:\n"
                         + self.contradictions.strip())
        if self.unbacked:
            lines.append(f"({self.unbacked} more contradiction "
                         f"{'line' if self.unbacked == 1 else 'lines'} cited "
                         "no point, so there was nothing to check "
                         f"{'it' if self.unbacked == 1 else 'them'} against, "
                         "and the bot dropped "
                         f"{'it' if self.unbacked == 1 else 'them'}.)")
        if self.grading:
            lines.append("\nAGAINST WHAT WE SAID LAST TIME:\n"
                         + self.grading.strip())
        if self.points:
            lines.append(self._points_text())
        return "\n".join(ln for ln in lines if ln)

    def _points_text(self) -> str:
        real = {p.n for p in self.points}
        ghosts = sorted(_cited("\n".join((self.body, self.contradictions,
                                          self.grading))) - real)
        out = ["\nTHE POINTS, EACH WITH THE FILING SENTENCE IT CAME FROM "
               "(the bot confirmed every sentence is in the filing; it did "
               "not confirm the point reads it right):"]
        for p in self.points:
            out.append(f"{p.tag} · {p.filing} · {p.section}\n"
                       f"  Point: {p.text}\n"
                       f"  Sentence: \"{p.source}\"")
            if p.unmatched:
                out.append("  (not in the sentence: "
                           + ", ".join(p.unmatched) + ")")
        if self.dropped:
            out.append(f"({self.dropped} more "
                       f"{'point was' if self.dropped == 1 else 'points were'}"
                       " dropped: the sentence the model gave is not in the "
                       "filing it read.)")
        if ghosts:
            out.append("(cited above but not a point in this brief: "
                       + ", ".join(f"P{n}" for n in ghosts)
                       + ". Whatever rests only on those is unsupported.)")
        return "\n".join(out)


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
    material = ("|".join(sorted(accessions)) + f"@{_budget(settings)}"
                + f"#v{_BRIEF_VERSION}")
    key = hashlib.sha256(material.encode()).hexdigest()[:16]
    return settings.cache_dir / "filing_briefs" / f"{key}.json"


# Part of the cache key. v2: points carry the filing sentence behind them, so
# a brief cached before that has nothing for the writer to check and has to
# be read again rather than served.
_BRIEF_VERSION = 2


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
                        counters: dict) -> tuple[list[Point], bool, int, int]:
    """One reading per section. Returns `(points, every_prompt_fit,
    points_dropped, sections_answered)`.

    SEGMENT FIRST, SUMMARISE PER SECTION, CONDENSE AFTER — two full 10-Ks
    fit no local context window, and the condensation pass has to hold every
    section summary from both filings at once, which is the call that gets
    tight (K1, K2b).
    """
    from pipeline.filings import _compress_sections
    from pipeline.llm import chat

    points: list[Point] = []
    held = True
    dropped = answered = 0
    filing = f"{ref.form} {ref.period or ref.filed}"
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
        answered += 1
        kept, lost = _check_points(_parse_points(out), packed, filing,
                                   section["title"])
        points.extend(kept)
        dropped += lost
    return points, held, dropped, answered


def _read_one(ref, workspace: Path, settings: Settings,
              counters: dict) -> tuple[list[Point], int, bool, int, int]:
    """Fetch, segment and read one filing. Never raises. Returns `(points,
    sections, every_prompt_fit, points_dropped, sections_answered)`."""
    from pipeline.filings import download_filing, segment_filing

    counters["download"] = counters.get("download", 0) + 1
    path = download_filing(ref, workspace, settings)
    if path is None:
        log.info("filing brief: could not download %s", ref.label)
        return [], 0, True, 0, 0
    html = path.read_text(errors="replace", encoding="utf-8")
    sections = _sections_to_read(segment_filing(html), settings)
    if not sections:
        log.info("filing brief: %s had no readable sections", ref.label)
        return [], 0, True, 0, 0
    points, held, dropped, answered = _summarise_sections(
        ref, sections, settings, counters)
    return points, len(sections), held, dropped, answered


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

        answered = 0
        for ref in refs:
            got, n, held, lost, heard = _read_one(ref, workspace, settings,
                                                  counters)
            out.points.extend(got)
            out.sections += n
            out.context_held = out.context_held and held
            out.dropped += lost
            answered += heard
        if not answered:
            # The daemon is down, the token is missing, or MOCK_MODE is on.
            # All three mean the same thing to the caller and none is an
            # error: a normal angle prompt, with the slot saying why.
            out.reason = "no LLM answered — the filing was not read"
            return out
        if not out.points:
            out.reason = ("the model answered, but none of its points named "
                          "a sentence that is actually in the filing"
                          if out.dropped else
                          "the model found nothing notable in the filing")
            return out
        for i, point in enumerate(out.points, 1):
            point.n = i

        joined = _points_listing(out.points)
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
    out = chat(f"OUR NUMBERS:\n{numbers}\n\nFROM THE FILINGS:\n"
               f"{_filing_side(brief, settings)}",
               settings, system=_CONTRADICTION_SYSTEM,
               purpose="filing-brief-crosscheck")
    if out:
        if brief.points:
            brief.contradictions, brief.unbacked = _keep_cited_lines(
                out, brief.points)
        else:
            brief.contradictions = out.strip()
    return brief


def _filing_side(brief: FilingBrief, settings: Settings) -> str:
    """What the cross-check and the grading read from the filing: the
    numbered points, so every line they write can cite one; the condensed
    body only for a brief from before points existed."""
    if not brief.points:
        return brief.body
    # Half the window: the other half is the numbers or the prior claims,
    # and the answer. Ollama would clip an overflow silently, from the front.
    text = _points_listing(brief.points)
    return text[:context_budget_chars(settings) // 2]


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
               f"FROM THE FILINGS:\n{_filing_side(brief, settings)}",
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
