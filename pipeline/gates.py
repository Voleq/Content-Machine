"""Automated gates — the bot checks its own work and only speaks up on failure.

Operator involvement should stay near zero, so these run unprompted between
approval and spend. Silence means proceed; every finding carries a line
reference so it can be acted on without hunting.

Six gates, five of them free and deterministic:

* **fact-check** — every number the script says out loud, re-read against the
  loaded `CompanyData`. This is the main credibility risk: a writer that
  misreads 496 as 490, or invents a margin, produces a video that is wrong
  in a way nobody downstream can catch.
* **voice linter** — bible violations only: hype adjectives, exclamation
  marks, a vendor name reaching screen text. It never counts jokes; density
  is a matter for the writer, not a linter.
* **data freshness** — refuses a render built on a stale snapshot.
* **audio** — refuses a final render that would publish synthesised
  placeholder effects. A banner in the log was the whole defence before this,
  which is discipline rather than a guarantee.
* **kit doctor** — unresolved tag keys, plus which kit families go unused,
  so the library grows from real gaps rather than guesses.
* **skeptic** — an LLM read of the finished script as a hostile investor.
  Notes only; it never rewrites and never blocks.

Narration is *spoken* text, so the numbers in it are written out —
"four hundred million", "four ninety six", "six percent". The fact-checker
therefore parses spelled-out English numerals as well as digits; a
digits-only check would silently pass almost every script.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from config import Settings
from pipeline.models import RATE_FIELDS, VENDOR_WORDS, quarter_words
from pipeline.spoken import eye_written_figures, eye_written_terms

log = logging.getLogger(__name__)


@dataclass
class Finding:
    """One thing worth the operator's attention."""

    gate: str
    # "note" | "warn" | "block". A note is for the record (the pacing
    # summary, a sentence the fact-check could not check): it is listed on
    # the report, and never makes a clean script read as one with warnings.
    severity: str
    message: str
    line: int = 0
    excerpt: str = ""

    def render(self) -> str:
        where = f"L{self.line}: " if self.line else ""
        tail = f"\n    “{self.excerpt}”" if self.excerpt else ""
        return f"[{self.gate}] {where}{self.message}{tail}"


@dataclass
class GateReport:
    findings: list[Finding] = field(default_factory=list)
    # WHAT EACH GATE DID, not just what it found (N2).
    #
    # This held only `findings`, so a gate that ran and found nothing and a
    # gate that never ran both contributed zero and were indistinguishable.
    # `skeptic_notes` makes it concrete: it returns `[]` when the LLM is
    # unavailable and `[]` when the script is clean.
    #
    # For a record whose entire purpose is honesty about what happened,
    # "clean" and "did not check" must not render the same way. Values are
    # `ok` / `warn` / `block` / `skipped:<why>`.
    ran: dict[str, str] = field(default_factory=dict)

    @property
    def blocking(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "block"]

    @property
    def ok(self) -> bool:
        return not [f for f in self.findings if f.severity != "note"]

    def record(self, gate: str, findings: list[Finding]) -> list[Finding]:
        """Note that `gate` ran, at the worst severity it reported (a note
        is not one)."""
        worst = "ok"
        for f in findings:
            if f.severity == "block":
                worst = "block"
                break
            if f.severity == "warn":
                worst = "warn"
        self.ran[gate] = worst
        return findings

    def skipped(self, gate: str, why: str) -> None:
        self.ran[gate] = f"skipped:{why}"

    def ran_line(self) -> str:
        """The provenance record's gates line.

        A skipped gate reads differently from a clean one, which is the
        whole point of the field.
        """
        marks = {"ok": "✓", "warn": "⚠", "block": "⛔"}
        bits = []
        for gate, state in sorted(self.ran.items()):
            if state.startswith("skipped:"):
                bits.append(f"{gate} SKIPPED ({state.split(':', 1)[1]})")
            else:
                bits.append(f"{gate} {marks.get(state, state)}")
        return " · ".join(bits)

    def text(self, limit: int = 20) -> str:
        if self.ok:
            return ""
        lines = [f.render() for f in self.findings[:limit]]
        if len(self.findings) > limit:
            lines.append(f"…and {len(self.findings) - limit} more")
        return "\n".join(lines)


# --------------------------------------------------------------------------
# Spoken-number parsing.
# --------------------------------------------------------------------------

_UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
         "seventy": 70, "eighty": 80, "ninety": 90}
_SCALES = {"hundred": 100, "thousand": 1_000, "million": 1_000_000,
           "billion": 1_000_000_000, "trillion": 1_000_000_000_000}
_NUMBER_WORDS = set(_UNITS) | set(_TENS) | set(_SCALES) | {"and", "point", "a",
                                                           "half"}

_SUFFIX = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000, "bn": 1_000_000_000,
           "t": 1_000_000_000_000, "thousand": 1_000, "million": 1_000_000,
           "billion": 1_000_000_000, "trillion": 1_000_000_000_000}


def _words_to_number(tokens: list[str]) -> float | None:
    """Parse a run of English number words. None when it is not a number.

    Handles the shapes that actually turn up in spoken finance:
    "four hundred million", "one point four billion", "six percent", and the
    idiomatic "four ninety six" (= 496) that a writer uses to avoid saying
    "four hundred and ninety six".
    """
    total = 0.0
    current = 0.0
    seen = False
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t in ("and", "a"):
            i += 1
            continue
        if t == "point":
            frac = []
            i += 1
            while i < len(tokens) and tokens[i] in _UNITS:
                frac.append(str(_UNITS[tokens[i]]))
                i += 1
            if not frac:
                break
            current = (current or 0) + float("0." + "".join(frac))
            seen = True
            continue
        if t == "half":
            # Only ever reaches here from `_half_is_a_number`: "half a
            # billion" and "two and a half billion".
            current += 0.5
            seen = True
            i += 1
            continue
        if t in _UNITS:
            value = _UNITS[t]
            # "one nineteen" -> 119, the same shorthand with a teen; it was
            # summed to twenty.
            if (1 <= value <= 9 and i + 1 < len(tokens)
                    and 10 <= _UNITS.get(tokens[i + 1], 0) <= 19):
                current += value * 100 + _UNITS[tokens[i + 1]]
                seen = True
                i += 2
                continue
            # "four ninety six" -> 4 * 100 + 96
            if (1 <= value <= 9 and i + 1 < len(tokens)
                    and tokens[i + 1] in _TENS):
                nxt = _TENS[tokens[i + 1]]
                i += 2
                if i < len(tokens) and tokens[i] in _UNITS and _UNITS[tokens[i]] < 10:
                    nxt += _UNITS[tokens[i]]
                    i += 1
                current += value * 100 + nxt
                seen = True
                continue
            current += value
            seen = True
            i += 1
            continue
        if t in _TENS:
            current += _TENS[t]
            seen = True
            i += 1
            continue
        if t in _SCALES:
            scale = _SCALES[t]
            if scale == 100:
                current = (current or 1) * 100
            else:
                total += (current or 1) * scale
                current = 0.0
            seen = True
            i += 1
            continue
        break
    if not seen:
        return None
    return total + current


# A scale WORD after digits belongs to them: "496 million" is one number. It
# used to stop at the digits, leaving "million" for the word parser to read as
# a figure of its own — 1,000,000, checked against revenue.
_DIGIT_RE = re.compile(
    r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)\s*"
    r"(percent|%|bn|thousand|million|billion|trillion|[kmbt])?(?![\w])",
    re.IGNORECASE,
)


@dataclass
class SpokenNumber:
    value: float
    text: str
    is_percent: bool = False
    # WHERE IT WAS SAID, not just what was said.
    #
    # The caller used to recover the position with `sentence.find(num.text)`,
    # and for a spoken run `text` is the tokens rejoined with single spaces —
    # so "minus twenty-four million" produced the text "twenty four million",
    # `find` returned -1, and both the minus sign and the metric-ownership
    # scan were computed against character 0 of the sentence. A correct
    # statement of a negative figure was then reported as a fabrication,
    # which for a BLOCKING gate is the one failure that matters.
    #
    # Hyphenated spoken numbers are how a writer actually spells them, so
    # the span is carried out rather than re-derived.
    start: int = -1
    end: int = -1


def _half_is_a_number(tokens: list[str], k: int) -> bool:
    """Is the "half" at `tokens[k]` part of a figure, or just the word?

    "Two and a half billion" and "half a billion" are figures; "the first half
    of the year" and "in half" are not, and reading them as 0.5 would hand the
    fact-check a number nobody said. So a "half" counts only inside one of
    those two shapes.
    """
    if k >= 3 and tokens[k - 2:k] == ["and", "a"]:
        return tokens[k - 3] in _UNITS or tokens[k - 3] in _TENS \
            or tokens[k - 3] in _SCALES
    after = tokens[k + 1:k + 3]
    return (len(after) == 2 and after[0] == "a"
            and (after[1] in _SCALES or after[1] == "percent"))


def extract_numbers(sentence: str) -> list[SpokenNumber]:
    """Every number a sentence states, digits or words."""
    out: list[SpokenNumber] = []
    low = sentence.lower()

    taken: list[tuple[int, int]] = []
    for m in _DIGIT_RE.finditer(low):
        raw = m.group(1).replace(",", "")
        try:
            value = float(raw)
        except ValueError:
            continue
        suffix = (m.group(2) or "").lower()
        pct = suffix in ("percent", "%")
        if suffix in _SUFFIX:
            value *= _SUFFIX[suffix]
        out.append(SpokenNumber(value, m.group(0).strip(), pct,
                                m.start(), m.end()))
        taken.append((m.start(), m.end()))

    words = list(re.finditer(r"[a-z]+|%", low))
    # A word the digits already took ("million" in "496 million") is not read
    # again as a number of its own.
    tokens = ["" if any(a <= w.start() < b for a, b in taken) else w.group(0)
              for w in words]
    tokens = [t if t != "half" or _half_is_a_number(tokens, k) else ""
              for k, t in enumerate(tokens)]
    i = 0
    while i < len(tokens):
        if tokens[i] not in _NUMBER_WORDS or tokens[i] in ("and", "a", "point"):
            i += 1
            continue
        j = i + 1
        # A run is words joined by spaces or hyphens only. Across a comma it
        # is two figures: "four hundred ninety one million, one percent below
        # plan" was read as 491,000,001 percent.
        while (j < len(tokens) and tokens[j] in _NUMBER_WORDS
               and re.fullmatch(r"[\s-]*",
                                low[words[j - 1].end():words[j].start()])):
            j += 1
        run = tokens[i:j]
        value = _words_to_number(run)
        if value is not None:
            pct = j < len(tokens) and tokens[j] in ("percent", "%")
            out.append(SpokenNumber(value, " ".join(run), pct,
                                    words[i].start(), words[j - 1].end()))
        i = max(j, i + 1)
    return out


def spoken_figures(text: str) -> list[SpokenNumber]:
    """The numbers in a line that a viewer hears as a FIGURE.

    `extract_numbers` finds every number, and narration written for the ear
    is full of small ones that are not data — "one reason", "two things",
    "no one". A lone number word under ten is dropped unless it is a
    percentage; digits always count, and so does anything spoken as more
    than one word ("one point four billion", "a hundred and sixty-two").
    """
    return [n for n in extract_numbers(text)
            if n.is_percent or n.value >= 10 or len(n.text.split()) > 1
            or any(ch.isdigit() for ch in n.text)]


# --------------------------------------------------------------------------
# Fact-check.
# --------------------------------------------------------------------------

# Metric -> the words a script uses for it. Only metrics with an unambiguous
# spoken name are checked; a vague one would produce noise, and a noisy gate
# gets ignored, which is worse than no gate.
# The key on the LEFT is the field the export actually carries, and getting
# that wrong is silent: `_series_for` returns nothing for a name the sheet does
# not use, and a metric with no series is skipped rather than reported. "Free
# cash flow" was checked against `free_cash_flow` for as long as the sheet has
# called it `fcf`, so the most quoted line in a cash-flow chapter went through
# unexamined.
#
# The list is longer than the spoken check strictly needs because the ON-SCREEN
# check reads row labels off a numbers sheet, and a sheet's rows are the
# export's own rows: gross profit, operating income, EBITDA, stock comp. A
# metric missing here is a row nothing verifies.
_METRIC_WORDS = {
    "revenue": ("revenue", "sales", "top line"),
    "gross_profit": ("gross profit",),
    "operating_income": ("operating income", "operating profit", "ebit"),
    "ebitda": ("ebitda",),
    "net_income": ("net income", "bottom line", "earnings"),
    "fcf": ("free cash flow", "fcf"),
    "fcf_margin": ("free cash flow margin", "fcf margin"),
    "operating_cf": ("cash from operations", "operating cash flow"),
    "capex": ("capex", "capital expenditure"),
    "sbc": ("stock comp", "stock-based compensation", "share-based comp"),
    "diluted_shares": ("share count", "shares outstanding", "diluted shares"),
    "total_debt": ("total debt", "debt load"),
    "net_debt": ("net debt",),
    "total_equity": ("total equity", "book value"),
    # NOT a bare "cash": that word is in "free cash flow", "cash from
    # operations", "cash used investing" and "net change in cash", and this
    # entry is the BALANCE. Matching a flow against a balance blocks a correct
    # sheet, which is the one thing a blocking gate must never do.
    "cash": ("cash on hand", "cash balance", "cash and equivalents",
             "cash and cash equivalents"),
    "gross_margin": ("gross margin",),
    "operating_margin": ("operating margin",),
    "net_margin": ("net margin",),
}

# CASH FLOW, SAID BARE, IS ONE OF TWO ROWS. "Quarterly cash flow hit three
# hundred thirty two million" names neither free nor operating cash flow, and
# with no metric of its own in reach the figure was handed to the revenue
# named a clause earlier and blocked (BA short, 30 Oct 2026). A spoken name
# only: a sheet row says which one it is.
_EITHER_METRIC = {"cash_flow": ("fcf", "operating_cf")}
_SPOKEN_METRIC_WORDS = {**_METRIC_WORDS, "cash_flow": ("cash flow", "cash flows")}

# What a finding calls a row. Field names are for code; "fcf" on the Check
# step read like a typo.
_METRIC_NAMES = {
    "fcf": "free cash flow", "fcf_margin": "free cash flow margin",
    "operating_cf": "operating cash flow", "ebitda": "EBITDA",
    "sbc": "stock comp", "cash_flow": "cash flow",
}


def _metric_name(metric: str) -> str:
    return _METRIC_NAMES.get(metric, metric.replace("_", " "))

# Spoken figures are rounded ("four hundred million" for 400.2M), so a claim
# counts as supported when it lands inside this band of any real value.
_TOLERANCE = 0.02


class SeriesUnreadable(Exception):
    """The export holds this metric and it could not be read.

    NOT THE SAME AS ABSENCE, and keeping them apart is the whole point. An
    empty series means "the sheet does not carry this metric", and every
    caller correctly skips it — `_METRIC_WORDS` is deliberately longer than
    any one export, so most metrics are absent on most sheets and reporting
    that would be pure noise.

    A metric that IS there and blows up reading has to arrive differently.
    `_series_for` used to catch every exception and return the empty list, so
    a type error, a changed export shape or an unexpected None in a history
    row turned the last line of defence against a fabricated figure into a
    no-op — for that metric, with nothing logged, leaving a gate that passed
    because it never looked. Same defect the GateReport docstring names above:
    a gate that ran and found nothing and a gate that never ran cannot be
    allowed to contribute the same zero.
    """


def _series_for(data, field_name: str) -> list[float]:
    """Every value the data holds for a metric — dashboard and history.

    Raises :class:`SeriesUnreadable` when a value the export does carry cannot
    be read. Returns `[]` only for a metric the sheet genuinely does not have.
    """
    values: list[float] = []
    if data is None:
        return values

    getter = getattr(data, "history_row", None)
    if callable(getter):
        try:
            values.extend(float(v) for v in (getter(field_name) or [])
                          if isinstance(v, (int, float)))
        except (TypeError, ValueError) as exc:
            # The shapes a malformed row actually produces: a row that is not
            # iterable, or a value that claims to be a number and will not
            # convert. Both mean this metric is unverifiable, which is a
            # finding rather than a shrug.
            raise SeriesUnreadable(
                f"{field_name}: history row is malformed ({exc})") from exc
        except Exception as exc:  # noqa: BLE001
            # Anything else is the export having changed shape underneath us.
            # Logged as well as raised, because the traceback is the only thing
            # that says which accessor broke.
            log.exception("fact-check: history_row(%r) failed", field_name)
            raise SeriesUnreadable(
                f"{field_name}: reading the history row failed ({exc})") from exc
    else:  # a plain mapping (tests, fixtures)
        series = (data.get("history") or {}).get(field_name) \
            if hasattr(data, "get") else None
        if isinstance(series, (list, tuple)):
            values.extend(float(v) for v in series if isinstance(v, (int, float)))

    # AND THE QUARTERS (O4). `templates/shots/earnings.json` opens on the
    # print and the beat/miss, and before the Quarters sheet existed the
    # fact-check had only annual series to compare a stated print against —
    # so an earnings SHORT could say any number at all and nothing objected.
    # A quarterly figure is a figure the export carries; it belongs in the
    # same bag as the annual one.
    values.extend(_quarters_for(data, field_name))

    snap = getattr(data, "dashboard", None)
    if hasattr(snap, "get"):
        latest = snap.get(field_name)
        if isinstance(latest, (int, float)):
            values.append(float(latest))
    elif hasattr(data, "get"):
        latest = data.get(field_name)
        if isinstance(latest, (int, float)):
            values.append(float(latest))
    return values


def _known_series(data) -> tuple[dict[str, list[float]], list[Finding]]:
    """Every checkable metric's values, plus a finding per metric that broke.

    THE SECOND HALF IS THE POINT. A metric that cannot be read is dropped from
    the returned map exactly as an absent one is — because there is nothing to
    check it against either way — but it leaves a BLOCKING finding behind, so
    the difference reaches the operator instead of evaporating. Without that,
    every sentence naming only the broken metric is skipped in silence and the
    fact-check reports clean on a script it never examined.
    """
    known: dict[str, list[float]] = {}
    findings: list[Finding] = []
    for metric in _METRIC_WORDS:
        try:
            known[metric] = _series_for(data, metric)
        except SeriesUnreadable as exc:
            findings.append(Finding(
                gate="fact-check", severity="block",
                message=(f"{exc} — every figure spoken or shown for this "
                         f"metric went unchecked, so this script is NOT "
                         f"fact-checked against it"),
            ))
    return known, findings


def _history_for(data, field_name: str) -> list[float]:
    """The ordered history series alone — no dashboard value appended.

    `_series_for` is a bag of everything the export knows about a metric, which
    is the right shape for "is this figure real" and the wrong one for "is this
    figure in the right column".
    """
    if data is None:
        return []
    getter = getattr(data, "history_for", None)
    series = None
    if callable(getter):
        try:
            series = getter(field_name)
        except Exception:                          # noqa: BLE001
            series = None
    if series is None:
        hist = getattr(data, "history", None)
        if hasattr(hist, "get"):
            series = hist.get(field_name)
        elif hasattr(data, "get"):
            series = (data.get("history") or {}).get(field_name)
    if not isinstance(series, (list, tuple)):
        return []
    return [float(v) for v in series if isinstance(v, (int, float))] \
        if all(isinstance(v, (int, float)) for v in series) else []


def _quarters_for(data, field_name: str) -> list[float]:
    """The ordered quarterly series alone, or []."""
    if data is None:
        return []
    rows = getattr(data, "quarters", None)
    series = None
    if hasattr(rows, "get"):
        series = rows.get(field_name)
    elif hasattr(data, "get"):
        series = (data.get("quarters") or {}).get(field_name)
    if not isinstance(series, (list, tuple)):
        return []
    return [float(v) for v in series if isinstance(v, (int, float))]


def _quarter_labels(data) -> list[str]:
    """The quarter columns as a finding names them: `Q-0` reads as the
    latest quarter (`quarter_words`), never as a quarter called zero."""
    labels = getattr(data, "quarter_labels", None)
    if not isinstance(labels, (list, tuple)) and hasattr(data, "get"):
        labels = data.get("quarter_labels")
    return ([quarter_words(str(x)) for x in labels]
            if isinstance(labels, (list, tuple)) else [])


def _matches(value: float, known: list[float]) -> bool:
    for k in known:
        if k == 0:
            if abs(value) < 1e-9:
                return True
            continue
        # accept the value, the same figure in millions/billions, and the
        # rounded form a script would actually say
        for scaled in (value, value * 1e6, value * 1e9, value / 1e6, value / 1e9):
            if abs(scaled - k) <= abs(k) * _TOLERANCE:
                return True
    return False


# Metrics whose values ARE percentages, so a spoken "sixty-two percent" is a
# direct claim about them rather than something derived. Every one of these
# used to be skipped outright, which meant a wrong margin was never checked.
# One definition, in `models.py`, because the quarterly comparison needs the
# same distinction: a move in a rate is a move in POINTS (O2).
_RATE_METRICS = RATE_FIELDS

# Phrases that contain a metric word but name a line the export does not
# carry. "Two hundred and twelve million on SALES and marketing" is not a
# claim about revenue, and the same trap as the `cash` note above: matching a
# figure against the wrong row makes a blocking gate block a correct script,
# which is the one thing it must never do.
# A RATIO NAMES TWO LINES AND IS NEITHER. "Net debt to EBITDA is two point
# one" was checked as an EBITDA of 2.1 and blocked (scan, 24 Oct 2026); the
# price multiples are the voice lint's own spoken forms.
_RATIO_PHRASES = (
    "net debt to ebitda", "debt to ebitda", "ev to ebitda",
    "enterprise value to ebitda", "price to earnings", "price to sales",
    "price to book", "price to free cash flow", "debt to equity",
    "ev to sales", "ev to ebit",
)
_DECOY_PHRASES = (
    "sales and marketing", "sales & marketing", "sales team", "sales force",
    "salesforce", "cost of sales", "cost of revenue", "sales cycle",
    "sales pipeline", "research and development",
) + _RATIO_PHRASES

# A number attached to its own subject by a preposition belongs to that
# subject, not to a metric named elsewhere in the sentence.
_ATTACHED_RE = re.compile(r"^\s*(?:on|for|in|per|across|toward|towards)\s+"
                          r"((?:[a-z][\w'-]*\s+){0,4}[a-z][\w'-]*)")

# "A loss of 89 million" is a minus without the word: the figure is a loss and
# the sheet holds it as -89M.
_NEGATIVE_RE = re.compile(
    r"(?:minus|negative|-|\b(?:loss(?:es)?|deficit|outflow|burn) of"
    r"(?: about| around| roughly| nearly| almost)?)\s*$")
# ...and a minus said AFTER the figure: "a three hundred million loss",
# "three fifty seven million of cash burn", "eighty million in the red".
_NEGATIVE_AFTER_RE = re.compile(
    r"^\s*(?:dollars?\s+)?(?:in\s+the\s+red\b|(?:of\s+)?(?:net\s+|cash\s+)?"
    r"(?:loss|losses|burn|outflows?)\b)")

# A FIGURE ABOUT THE FUTURE is not on the sheet. The long's guidance chapter
# and the earnings short's expected beat are invited to say what management
# guided to and what analysts expect, and each was checked against history
# and blocked (scan, 24 Oct 2026). Its own clause decides, so the reported
# figure beside it in the same sentence is still checked.
_FORWARD_CLAUSE_RE = re.compile(
    r"\b(?:guid(?:e|es|ed|ing|ance)|expect(?:s|ed|ing|ation|ations)?|"
    r"consensus|estimates?|estimated|forecasts?|forecasted|projects|"
    r"projected|projections?|outlook|targets?|targeted|next (?:year|quarter)|"
    r"looking for|predicts?|predicted)\b")
_CLAUSE_EDGE_RE = re.compile(r"[,;:—–()]|\b(?:and|but|while|whereas)\b")


def _clause(low: str, pos: int, end: int) -> str:
    """The clause around the figure at `pos:end` of the sentence."""
    starts = [m.end() for m in _CLAUSE_EDGE_RE.finditer(low, 0, pos)]
    after = _CLAUSE_EDGE_RE.search(low, end)
    return low[(starts[-1] if starts else 0):(after.start() if after else len(low))]


# A FALL SAID WITH A VERB is a negative change. "Revenue dropped two point
# four percent" against a sheet that fell 2.4% was compared as +2.4% and
# blocked a true sentence (scan, 24 Oct 2026). Only when the verb leads
# straight into the figure (or through "by"): "fell to four hundred million"
# and "down from five hundred" name levels, not the change.
_FALL_RE = re.compile(
    r"\b(?:fell|falls?|falling|dropped|drops?|dropping|declined|declines?|"
    r"declining|down|shrank|shrunk|shrinks?|shrinking|slid|slides?|sliding|"
    r"slipped|slips?|decreased|decreases?|contracted|contracts?|plunged|"
    r"plunges?|sank|sinks?|tumbled|tumbles?|lost|loses?|losing|"
    # Cash BURNED is cash gone: "free cash flow burned three fifty seven
    # million" against a sheet holding -357M was compared as +357M and
    # blocked a true sentence (BA short, 30 Oct 2026).
    r"burn(?:ed|t|s|ing)?(?:\s+through)?|bled|bleeds?|bleeding)"
    r"(?:\s+(?:by|about|around|roughly|nearly|almost|some|just|over|another|"
    r"more\s+than|less\s+than))*\s*$")

# A PRICE MOVE IS NOT A METRIC CLAIM. "EXMPL is up twelve percent because the
# boring machine beat earnings again" names earnings, and the nearest-metric
# rule read the day's move as net-income growth and blocked a correct short —
# a hook of exactly the shape every short opens with. A percentage whose
# subject is the STOCK moving (the ticker, "the stock", "shares", "the share
# price") is about the price; a metric named after it is the reason for the
# move, not the owner of the number. "Shares outstanding" and "the share count"
# never match: a word between the subject and its verb is a different subject.
_MOVE_TAIL = (r"\s+(?:(?:is|was|are|were|has|have|had|'s)\s+)?(?:been\s+)?"
              r"(?:up|down|higher|lower|rose|fell|jumped|dropped|gained|lost|climbed|"
              r"slid|popped|sank|surged|tumbled|rallied)"
              r"(?:\s+(?:by|about|around|nearly|almost|over|some))?\s*$")


def _price_move_re(ticker: str, names: tuple[str, ...] = ()) -> re.Pattern:
    """The stock as the subject of a move, ending where the number starts.

    THE COMPANY'S NAME IS THE STOCK TOO. "Boeing is down ten point seven
    percent today" never matched, because only the ticker, "the stock" and
    "shares" did, and the day's move was read as operating income growth and
    blocked the render (BA short, 30 Oct 2026). Every hook names the company.
    """
    subjects = [r"(?:the\s+)?stock", r"(?:the\s+)?shares", r"(?:the\s+)?share\s+price"]
    if ticker.strip():
        subjects.append(re.escape(ticker.strip().lower()))
    subjects += [re.escape(n) + r"(?:'s|’s)?(?:\s+(?:stock|shares))?"
                 for n in names if n]
    return re.compile(r"\b(?:" + "|".join(subjects) + r")" + _MOVE_TAIL)


# The words a company name carries that a script drops: "The Boeing Company"
# is "Boeing" out loud.
_LEGAL_WORDS_RE = re.compile(
    r"\b(?:the|inc|incorporated|corp|corporation|co|company|companies|"
    r"holdings?|group|plc|ltd|limited|llc|lp|sa|ag|nv|se|class\s+[a-z])\b\.?")


def _company_names(data) -> tuple[str, ...]:
    """How a script says the company: the name without its legal words, and
    its first word when that reads as a name on its own (four letters or
    more, and not a word like "General" that starts many names)."""
    raw = data.get("company_name") if hasattr(data, "get") else None
    if not isinstance(raw, str) or not raw.strip():
        return ()
    clean = " ".join(re.sub(r"[^\w\s&'-]", " ",
                            _LEGAL_WORDS_RE.sub(" ", raw.lower())).split())
    out = [clean] if len(clean) >= 3 else []
    first = clean.split()[0] if clean else ""
    if len(first) >= 4 and first not in out and first not in _COMMON_FIRST:
        out.append(first)
    return tuple(out)


# A first word that is a word before it is a name: "General Motors" is not
# "General is down", "American Express" not "American".
_COMMON_FIRST = frozenset({
    "general", "american", "united", "first", "national", "international",
    "global", "new", "royal", "western", "eastern", "southern", "northern",
    "public", "union", "federal", "advanced", "applied", "digital",
})


# A FIGURE SAID WITH THE SESSION IS THE PRICE. "Down ten point seven percent
# today", "up four percent after hours": in a clause naming no line of the
# workbook, a percentage that happened today is the stock's move.
_SESSION_RE = re.compile(
    r"\b(?:today|tonight|this morning|this afternoon|intraday|"
    r"pre-?market|after[- ]hours|overnight|on the day|at the open|"
    r"at the close|in one session|since the (?:print|report|call|open))\b")


def _unit_scale(series: list[float]) -> float:
    """What one unit of this series is worth in absolute terms.

    The workbook holds a metric either way — the shipped History sheet
    carries revenue as 400000000, the Peers sheet carries the same idea as
    2037.36 — and nothing reconciled that with the magnitude a script speaks
    in (B4). Inferred from the series rather than configured, because the
    sheet does not declare it and a setting nobody maintains is how this
    drifts again.
    """
    magnitudes = [abs(v) for v in series if v]
    if not magnitudes:
        return 1.0
    return 1.0 if max(magnitudes) >= 1e5 else 1e6


def _shorthand(value: float, target: float) -> float:
    """`value` brought to `target`'s own order of magnitude.

    A script that has just said "four hundred million" then says "four
    ninety six" and means 496 million. That shorthand is how anyone reads a
    series out loud, and a check that cannot follow it reports every recital
    as a mismatch.

    This walks by factors of a thousand, so it changes the SCALE and never
    the digits: 912 cannot become 496 by any number of steps, which is the
    property that keeps a genuinely wrong figure caught.
    """
    if not value or not target:
        return value
    v, limit = value, abs(target)
    while abs(v) * 1000 <= limit:
        v *= 1000
    while abs(v) > limit * 1000:
        v /= 1000
    return v


def _matches_scaled(value: float, candidates: list[float]) -> bool:
    """Does `value` land on any of `candidates`, allowing spoken shorthand?"""
    for target in candidates:
        if target == 0:
            if abs(value) < 1e-9:
                return True
            continue
        if abs(_shorthand(value, target) - target) <= abs(target) * _TOLERANCE:
            return True
    return False


_YEAR_RE = re.compile(r"\b(20\d{2})\b")


def _period_index(sentence: str, labels: list[str]) -> int | None:
    """Which column of the history a sentence is talking about, if it says.

    The comparison ran against every value in the series at once, so a figure
    from the wrong year passed (B4). When the sentence names a period the
    export labels, the check narrows to that column.
    """
    if not labels:
        return None
    low = sentence.lower()
    for i, label in enumerate(labels):
        lab = str(label).strip().lower()
        if lab and lab in low:
            return i
    m = _YEAR_RE.search(low)
    if m:
        for i, label in enumerate(labels):
            if m.group(1) in str(label):
                return i
    return None


_QUARTER_WORDS = {"first": 1, "second": 2, "third": 3, "fourth": 4}
_QUARTER_NUM_RE = re.compile(r"\bq\s?-?\s?([1-4])\b", re.IGNORECASE)
_QUARTER_WORD_RE = re.compile(
    r"\b(first|second|third|fourth)\s+quarter\b", re.IGNORECASE)


# A HEADER'S FISCAL QUARTER. Not `Q-4`: the template's relative headers count
# quarters back from the latest, so "the fourth quarter" checked against the
# column a year ago and blocked a correct print (scan, 24 Oct 2026). A sheet
# whose fiscal rows filled in says `Q4 FY25` instead.
_LABEL_QUARTER_RE = re.compile(r"\bq\s?([1-4])\b", re.IGNORECASE)


def _label_quarter(label: str) -> int | None:
    m = _LABEL_QUARTER_RE.search(str(label))
    return int(m.group(1)) if m else None


def _quarter_indices(sentence: str, labels: list[str]) -> list[int]:
    """Which quarterly columns a sentence is talking about, if it says.

    Returns EVERY column a bare quarter number could mean rather than
    guessing the newest (O4). An eight-quarter sheet has two Q4s, and a
    blocking gate that picks one and blocks a script meaning the other is
    worse than no gate — the one thing the fact-check must never do is
    refuse a correct script. Two columns is still a far narrower comparison
    than the whole bag.

    "Last quarter" and "the most recent quarter" deliberately narrow
    nothing: they are ambiguous between the quarter just reported and the
    one before it, and the honest answer to an ambiguous reference is the
    wider comparison.
    """
    if not labels:
        return []
    low = sentence.lower()
    for i, label in enumerate(labels):
        lab = str(label).strip().lower()
        if lab and lab in low:
            return [i]
    q = None
    m = _QUARTER_NUM_RE.search(low)
    if m:
        q = int(m.group(1))
    else:
        m = _QUARTER_WORD_RE.search(low)
        if m:
            q = _QUARTER_WORDS[m.group(1).lower()]
    if q is None:
        return []
    return [i for i, label in enumerate(labels) if _label_quarter(label) == q]


_PERIOD_TOKEN_RE = re.compile(r"\b(?:fy|q|h|cy)\s?-?\s?\d{1,4}\b",
                              re.IGNORECASE)

# A spoken year. "Free cash flow turned negative in twenty twenty two" is a
# DATE, and the word-number parser reads it as a quantity — which the old
# magnitude floor hid and a blocking gate cannot afford to.
#
# "Twenty" and a lone digit word is a NUMBER: "twenty one percent" is not the
# year 2001, which is said "two thousand and one" or "twenty oh one". Read
# as one, a margin of twenty-one percent went unchecked and "twenty five
# million" left a bare "million" behind to block (scan, 24 Oct 2026).
_YEAR_UNIT = r"(?:one|two|three|four|five|six|seven|eight|nine)"
_YEAR_TEEN = (r"(?:nineteen|eighteen|seventeen|sixteen|fifteen|fourteen|"
              r"thirteen|twelve|eleven|ten)")
_SPOKEN_YEAR_RE = re.compile(
    rf"\b(?:twenty\s+(?:oh\s+{_YEAR_UNIT}|{_YEAR_TEEN}|"
    rf"(?:twenty|thirty)(?:[\s-]+{_YEAR_UNIT})?)"
    rf"|two thousand(?:\s+and)?\s+(?:oh\s+)?"
    rf"(?:{_YEAR_TEEN}|(?:twenty|thirty)(?:[\s-]+{_YEAR_UNIT})?|{_YEAR_UNIT}))\b",
    re.IGNORECASE)

_DIGIT_YEAR_RE = re.compile(
    r"(?:\b(?:in|since|by|during|through|until|from)\s+)((?:19|20)\d{2})\b",
    re.IGNORECASE)

# NAMES WRITTEN IN DIGITS. The writer prompt says "the 10-K shows", and a
# page, note or item number, a bare year ("fiscal 2023", "from 2019 to 2023")
# or a day of a month ("March 3") is a name or a date, never a figure. Each
# was read as one and blocked against whatever metric the sentence named.
_FORM_NAME_RE = re.compile(r"\b(?:\d{1,2}-[kqf]|[sf]-\d)\b", re.IGNORECASE)
_NUMBERED_RE = re.compile(
    r"\b(?:page|pages|p\.|note|notes|item|items|section|exhibit|form|part|"
    r"chapter|slide|footnote|table|schedule)\s+(\d+[a-z]?(?:\.\d+)?)\b",
    re.IGNORECASE)
# ...and the same names SAID, as the prompts ask: "on page four hundred and
# eleven", "note fourteen", "the ten K" (scan, 24 Oct 2026).
_SPOKEN_NUMBER_WORD = (r"(?:zero|one|two|three|four|five|six|seven|eight|nine|"
                       r"ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|"
                       r"seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|"
                       r"sixty|seventy|eighty|ninety|hundred|thousand)")
_SPOKEN_NUMBERED_RE = re.compile(
    r"\b(?:page|pages|note|notes|item|items|section|exhibit|part|chapter|"
    r"slide|footnote|table|schedule)\s+"
    rf"((?:{_SPOKEN_NUMBER_WORD}(?:[\s-]+and[\s-]+|[\s-]+)?)*"
    rf"{_SPOKEN_NUMBER_WORD})\b",
    re.IGNORECASE)
_SPOKEN_FORM_RE = re.compile(r"\b(?:ten|eight)[\s-]+[kq]s?\b", re.IGNORECASE)
_BARE_YEAR_RE = re.compile(
    r"(?<![\d$£€.,])((?:19|20)\d{2})(?![\d,]|\.\d|\s*(?:%|percent\b|"
    r"thousand\b|million\b|billion\b|trillion\b|bn\b|[kmbt]\b))",
    re.IGNORECASE)
_MONTHS_RE = (r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|"
              r"june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|"
              r"nov(?:ember)?|dec(?:ember)?)")
_DAY_OF_MONTH_RE = re.compile(
    rf"\b{_MONTHS_RE}\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b"
    rf"|\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?{_MONTHS_RE}\b",
    re.IGNORECASE)

# "Eleven times earnings" is a MULTIPLE, not an earnings figure. The metric
# word is there and the number is not a claim about it.
_MULTIPLE_RE = re.compile(r"^\s*(?:x|times)\b", re.IGNORECASE)


# A SHARE IS NOT A MEASURE OF THE NEAREST METRIC. "About three percent of
# revenue" is a ratio to something, and the nearest-metric rule read it as
# revenue's growth.
_SHARE_OF_RE = re.compile(r"^\s*(?:percent\b|%)?\s*of\b")

# A NUMBER THAT COUNTS THINGS IS NOT A FIGURE. "Flat for three years", "two of
# the last five", "three cents a share", "two hundred layoffs": each is a
# number in a sentence that happens to name a metric, and read as a claim about
# it the script is refused over a sentence that never claimed anything.
#
# What gives a count away is what it counts, so the word right after the number
# is the evidence: a unit of time or of cents, a partitive ("of the last"), or
# any other plural noun. Plural nouns are told apart from the words that
# happen to end in -s by an exclusion list rather than a vocabulary, and the
# units a sheet really does state in — points of margin, shares — are kept.
#
# ONLY A BARE NUMBER IS EVER A COUNT. One that carries a million, a billion or
# a trillion is an amount, and "fifty two million becomes twelve" is a verb
# after a figure, not a noun it counts.
_COUNT_UNITS = frozenset({"year", "quarter", "month", "week", "day", "decade",
                          "hour", "minute", "cent", "time"})
_PARTITIVES = frozenset({"the", "those", "these", "them"})
_FIGURE_UNITS = frozenset({"points", "shares"})
_NOT_NOUNS = frozenset({"versus", "across", "unless", "towards", "whereas",
                        "besides", "always", "perhaps"})
_COUNTED_RE = re.compile(r"^[\s-]*([a-z]+)(?:\s+([a-z]+))?")
_LAST_N_RE = re.compile(r"\b(?:last|past|previous|prior|next|first|final)\s+$")
_SCALED_RE = re.compile(r"million|billion|trillion|\d\s*(?:[mbt]|bn)$")


def _counts_things(low: str, num: SpokenNumber) -> bool:
    """Is this number a COUNT of something rather than an amount of it?"""
    if num.is_percent or _SCALED_RE.search(num.text):
        return False
    # A run that ends on "a" or "and" hands the next word to the article:
    # "two hundred and twelve million a year" counts nothing.
    if num.text.split()[-1] in ("a", "and"):
        return False
    # "The last five", "the past three": a small number after a period word.
    if num.value < 100 and _LAST_N_RE.search(low[:num.start]):
        return True
    m = _COUNTED_RE.match(low[num.end:])
    if not m:
        return False
    word, after = m.groups()
    if word == "of":
        return after in _PARTITIVES
    if word.rstrip("s") in _COUNT_UNITS:
        return True
    if word in _FIGURE_UNITS or word in _NOT_NOUNS:
        return False
    return len(word) > 4 and word.endswith("s")


def _blank(m) -> str:
    return "·" * len(m.group(0))


def _mask_labels(sentence: str, labels: list[str]) -> str:
    """Blank period labels and dates so their digits are not read as spoken
    figures. Same length out as in, so character positions still line up."""
    out = sentence
    for label in labels:
        lab = str(label).strip()
        if len(lab) >= 2:
            out = re.sub(re.escape(lab), _blank, out, flags=re.IGNORECASE)
    out = _PERIOD_TOKEN_RE.sub(_blank, out)
    out = _SPOKEN_YEAR_RE.sub(_blank, out)
    out = _FORM_NAME_RE.sub(_blank, out)
    out = _SPOKEN_FORM_RE.sub(_blank, out)
    for rx in (_DIGIT_YEAR_RE, _NUMBERED_RE, _SPOKEN_NUMBERED_RE,
               _BARE_YEAR_RE, _DAY_OF_MONTH_RE):
        out = rx.sub(_blank_groups, out)
    return out


def _blank_groups(m) -> str:
    """The match with only its captured digits blanked."""
    text, at = list(m.group(0)), m.start(0)
    for g in range(1, (m.re.groups or 0) + 1):
        if m.start(g) >= 0:
            text[m.start(g) - at:m.end(g) - at] = "·" * (m.end(g) - m.start(g))
    return "".join(text)


def _history_labels(data) -> list[str]:
    labels = getattr(data, "history_years", None)
    if not isinstance(labels, (list, tuple)) and hasattr(data, "get"):
        labels = data.get("history_years")
    return [str(x) for x in labels] if isinstance(labels, (list, tuple)) else []


def _mask_decoys(text: str) -> str:
    """Blank out phrases that contain a metric word but name another line."""
    for phrase in _DECOY_PHRASES:
        text = text.replace(phrase, "·" * len(phrase))
    return text


def _metric_spans(masked: str, words: dict | None = None
                  ) -> list[tuple[str, int, int]]:
    """Every metric word in `masked` as (metric, start, end).

    A word that sits INSIDE a longer word of another metric is not a mention
    of its own metric: "ebit" is in "ebitda" and "fcf" is in "fcf margin", and
    matching the shorter one checked EBITDA against operating income and a
    free-cash-flow margin against free cash flow itself.
    """
    spans = [(metric, at, at + len(w))
             for metric, names in (words or _METRIC_WORDS).items()
             for w in names
             for at in (m.start() for m in re.finditer(re.escape(w), masked))]
    return [s for s in spans
            if not any(o[0] != s[0] and o[1] <= s[1] and s[2] <= o[2]
                       and o[2] - o[1] > s[2] - s[1] for o in spans)]


def _metrics_named(low: str, words: dict | None = None
                   ) -> dict[str, tuple[int, int]]:
    """metric -> (start, end) of its first mention, decoys removed."""
    words = words or _METRIC_WORDS
    spans = _metric_spans(_mask_decoys(low), words)
    out: dict[str, tuple[int, int]] = {}
    for metric in words:
        mine = [(start, end) for m, start, end in spans if m == metric]
        if mine:
            out[metric] = min(mine)
    return out


# Words that, with a period token, make up a phrase naming WHEN rather than
# WHAT. "In Q4", "in FY-2", "in 2024", "in the fourth quarter", "in that same
# quarter" — none of them is a subject a number could belong to.
_PERIOD_WORDS = frozenset({
    "quarter", "quarters", "year", "years", "fiscal", "half", "period",
    "the", "that", "this", "last", "latest", "same", "most", "recent",
    "previous", "prior", "first", "second", "third", "fourth", "q", "fy",
    "cy", "lt", "ltm", "trailing", "twelve", "months", "month", "ago",
})


def _is_period_phrase(phrase: str) -> bool:
    """Does this attached phrase name a TIME rather than a subject?

    `_ATTACHED_RE` exists to stop "two hundred and twelve million ON SALES
    AND MARKETING" being read as a revenue claim. But it also matched "minus
    forty million IN Q4" and "in FY-0" — and since neither "q4" nor "fy-0"
    is a metric the export carries, the number was discarded as belonging to
    something else. Naming the period is exactly what a careful script does,
    so the narrowing was silently switching the gate off on the sentences
    most worth checking (O4's interaction with B4).
    """
    body = _PERIOD_TOKEN_RE.sub(" ", phrase.lower())
    body = re.sub(r"\b(?:19|20)\d{2}\b", " ", body)
    words = [w for w in re.findall(r"[a-z]+", body) if w not in _PERIOD_WORDS]
    return not words


def _gap(mention: tuple[int, int], start: int, end: int) -> int:
    """Characters between a metric's name and a number, whichever comes first."""
    if mention[1] <= start:
        return start - mention[1]
    if mention[0] >= end:
        return mention[0] - end
    return 0


def _owner_of(number_start: int, number_end: int, tail: str,
              named: dict[str, tuple[int, int]], low: str,
              figures=(), *, percent: bool = False) -> tuple[str | None, bool]:
    """Which metric a number is a claim about, and whether that is KNOWN.

    Returns `(metric, sure)`, or `(None, False)` when the number is not a
    claim about any metric. Rules, in order:

    1. A number attached to its own subject by a preposition belongs to that
       subject. "Two hundred and twelve million ON SALES AND MARKETING" is
       not a revenue figure, even in a sentence that goes on to mention
       revenue — and reading it as one is how a blocking gate blocks a
       correct script.
    2. A percentage that names its own subject belongs to it: "nine point
       four percent perpetual cash growth" is nobody's EBITDA growth, and
       "ten percent revenue growth" is revenue's.
    3. Inside its own clause first. "Revenue sat at four hundred ninety six
       million, free cash flow at negative fifteen million": the 496 is
       nearer "free cash flow" by characters and is still revenue's. Nearest
       is the gap to the metric's NAME, not to where the name starts.
    4. A clause that is only the series going on ("…, to four fifty, then
       four ninety six") belongs to the metric the series started with, so a
       recital is checked through to its last number.
    5. Anything else goes to the nearest metric in the sentence, and that is
       a GUESS. "Boeing is down ten point seven percent today, with sixty
       million of operating profit" handed the day's move to operating
       income, a clause away, and blocked the render (BA short, 30 Oct
       2026). A guess is still checked, and only ever warns.
    """
    if not named:
        return None, False
    if _MULTIPLE_RE.match(tail):
        return None, False   # "eleven times earnings" is a multiple
    attached = _ATTACHED_RE.match(tail)
    if attached and not _is_period_phrase(attached.group(1)):
        owners = [m for m in _metrics_named(attached.group(1),
                                            _SPOKEN_METRIC_WORDS) if m in named]
        if not owners:
            return None, False   # attached to something the export has no row for
        return owners[0], True
    head = _OWN_HEAD_RE.match(tail) if percent else None
    if head and not _neutral_head(head.group(1)):
        owners = [m for m in _metrics_named(head.group(1), _SPOKEN_METRIC_WORDS)
                  if m in named]
        return (owners[0], True) if owners else (None, False)
    lo, hi = _own_clause(low, number_start, number_end)
    mine = {m: at for m, at in named.items() if lo <= at[0] and at[1] <= hi}
    if mine:
        return min(mine, key=lambda m: _gap(mine[m], number_start, number_end)), True
    # "A hundred million shares became a hundred and twenty six": in a
    # sentence that names the share count, a clause counting shares is it.
    if "diluted_shares" in named and _SHARES_RE.search(low[lo:hi]):
        return "diluted_shares", True
    nearest = min(named, key=lambda m: _gap(named[m], number_start, number_end))
    if _is_recital(low, lo, hi, figures):
        before = {m: at for m, at in named.items() if at[1] <= number_start}
        if before:
            return max(before, key=lambda m: before[m][1]), True
        return nearest, True
    return nearest, False


_SHARES_RE = re.compile(r"\bshares\b")

# Where one clause of a recital ends and the next begins. "Yet", "though" and
# "because" start a clause with a subject of its own as surely as "but" does.
_CLAUSE_CUT_RE = re.compile(
    r"[,;:]|\s(?:and|but|while|whereas|yet|though|although|because)\s")


def _own_clause(low: str, start: int, end: int) -> tuple[int, int]:
    """Where the clause holding the figure at `start:end` begins and ends."""
    cuts = list(_CLAUSE_CUT_RE.finditer(low))
    lo = max((c.end() for c in cuts if c.end() <= start), default=0)
    hi = min((c.start() for c in cuts if c.start() >= end), default=len(low))
    return lo, hi


# A percentage followed by the thing it measures: "nine percent dividend
# yield", "four percent perpetual cash growth", "fifty eight percent gross
# margin". The words before the head noun say whose it is.
_OWN_HEAD_RE = re.compile(
    r"^\s*(?:percent\b|%)?\s*((?:[a-z][\w'-]*\s+){0,3}?"
    r"(?:growth|cagr|margins?|yields?|returns?|rates?|discount|premium|stake|"
    r"dilution)\b)")
# Words that say WHEN or HOW a growth was measured, not WHAT grew: "nine
# percent annual growth" is still the growth of the metric the sentence names.
_HEAD_NEUTRAL = frozenset({
    "annual", "annualised", "annualized", "yearly", "quarterly", "year",
    "over", "sequential", "compound", "compounded", "average", "total",
    "organic", "top", "line", "growth", "cagr", "rate", "rates", "a", "an",
    "the", "of", "its", "their", "his", "her",
})


def _neutral_head(phrase: str) -> bool:
    return all(w in _HEAD_NEUTRAL for w in re.findall(r"[a-z]+", phrase))


# What a clause of a spoken series is made of besides its figure. "To four
# fifty", "then minus twenty five", "and finally ninety six": a clause holding
# only these is the series going on.
_RECITAL_WORDS = frozenset({
    "to", "then", "and", "from", "at", "about", "around", "roughly", "nearly",
    "almost", "just", "over", "under", "a", "an", "the", "of", "in", "on",
    "by", "dollars", "dollar", "percent", "per", "cent", "minus", "negative",
    "plus", "positive", "up", "down", "was", "were", "is", "it", "its",
    "finally", "now", "or", "more", "less", "than", "still", "only",
    "another", "again", "back", "so", "after", "before", "million", "billion",
    "thousand", "trillion", "hundred", "point", "bn", "m", "b", "k", "s",
}) | _PERIOD_WORDS


def _is_recital(low: str, lo: int, hi: int, figures) -> bool:
    text = list(low[lo:hi])
    for n in figures:
        if lo <= n.start and n.end <= hi:
            text[n.start - lo:n.end - lo] = " " * (n.end - n.start)
    words = re.findall(r"[a-z]+", "".join(text))
    return all(w in _RECITAL_WORDS for w in words)


# A PERCENTAGE THE PRICE IMPLIES is not one the company reported. "Seventy
# times EBITDA assumes nine point four percent perpetual cash growth" is the
# reverse DCF talking, and was checked as EBITDA's growth and blocked (BA
# short, 30 Oct 2026).
_IMPLIED_RE = re.compile(
    r"\b(?:assum(?:es|ed|ing|ptions?)|impl(?:ies|ied|y|ying)|priced (?:for|in)|"
    r"baked in|perpetual|perpetuity|terminal|reverse dcf|discount rate|"
    r"to justify)\b")

# THE PERIOD A SENTENCE SAYS WITHOUT NAMING A COLUMN. "Quarterly cash flow hit
# three hundred thirty two million" is a quarter's figure, and comparing it
# with the yearly rows is what made the check read a quarter as a year.
_QUARTERLY_RE = re.compile(
    r"\b(?:quarterly|this quarter|the quarter|that quarter|last quarter|"
    r"latest quarter|most recent quarter|per quarter|quarter[- ]over[- ]quarter|"
    r"sequential(?:ly)?|qoq)\b")
_YEARLY_RE = re.compile(
    r"\b(?:yearly|annual|annually|full[- ]year|for the year|fiscal year|"
    r"per year|trailing twelve months)\b")


def _said_period(low: str) -> str:
    """"quarterly", "yearly", or "" when the sentence says neither (or both)."""
    q, y = bool(_QUARTERLY_RE.search(low)), bool(_YEARLY_RE.search(low))
    return "quarterly" if q and not y else "yearly" if y and not q else ""


_BEAT_TAG_RE = re.compile(r"\[BEAT\b[^\]]*\]", re.IGNORECASE)


def _sentences(line: str) -> list[str]:
    """A narration line as sentences. A `[BEAT]` mark ends one too: the
    writer starts a new beat where the voice starts a new thought, full stop
    or not, and "…of sales [BEAT: headline] Revenue missed…" read as one
    sentence handed the headline's figure to the hook's metric."""
    out: list[str] = []
    for chunk in _BEAT_TAG_RE.split(line):
        out += [s for s in re.split(r"(?<=[.!?])\s+", chunk.strip()) if s]
    return out


def _raw_row(data, which: str, field_name: str) -> list:
    """One row of the History or Quarters sheet as stored, blanks and all,
    so position i is still column i."""
    if which == "history":
        getter = getattr(data, "history_for", None)
        if callable(getter):
            try:
                got = getter(field_name)
            except Exception:                      # noqa: BLE001
                got = None
            if isinstance(got, (list, tuple)):
                return list(got)
    rows = getattr(data, which, None)
    if not hasattr(rows, "get") and hasattr(data, "get"):
        rows = data.get(which)
    series = rows.get(field_name) if hasattr(rows, "get") else None
    return list(series) if isinstance(series, (list, tuple)) else []


def _latest_value(data, field_name: str) -> float | None:
    snap = getattr(data, "dashboard", None)
    got = snap.get(field_name) if hasattr(snap, "get") else (
        data.get(field_name) if hasattr(data, "get") else None)
    return float(got) if isinstance(got, (int, float)) and not isinstance(got, bool) else None


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _pct(a: float, b: float) -> float | None:
    return (b - a) / abs(a) * 100.0 if a else None


@dataclass
class _Verdict:
    """What one figure was compared with, and whether it landed."""

    ok: bool
    flipped: bool        # it lands with the other sign
    where: str           # " for Q4 FY25", a column the sentence named
    shown: str
    when: str = ""       # "quarterly " / "yearly ", a period it said


def _show_levels(run: list[tuple[str, float]], rate: bool, n: int) -> str:
    def one(v: float) -> str:
        if rate:
            return f"{v:,.1f}%"
        from pipeline.models import _mag
        return _mag(v)
    picked = run[-n:] if len(run) > n else run
    return " · ".join(f"{label} {one(v)}" for label, v in picked)


def _judge(data, metric: str, sentence: str, value: float, percent: bool,
           period: str) -> _Verdict | str | None:
    """One figure against one metric's rows.

    A `_Verdict`, a reason to list the sentence as not checked, or None when
    there is nothing to hold it to.

    EACH SHEET IS ITS OWN SERIES. The rows used to be poured into one bag —
    the years, then the quarters, then the dashboard — and growth was taken
    between neighbours in the bag, so the step from the last year to the
    first quarter was a "growth rate", and a quarter's growth on the same
    quarter a year earlier, the number an earnings video leads with, was not
    a candidate at all.
    """
    rate = metric in _RATE_METRICS
    ylab, qlab = _history_labels(data), _quarter_labels(data)
    yrow, qrow = _raw_row(data, "history", metric), _raw_row(data, "quarters", metric)
    ylab = ylab if len(ylab) == len(yrow) else [f"year {i + 1}" for i in range(len(yrow))]
    qlab = qlab if len(qlab) == len(qrow) else [f"quarter {i + 1}" for i in range(len(qrow))]
    latest = _latest_value(data, metric)

    def scaled(row: list) -> list:
        nums = [v for v in row if _num(v)]
        k = 1.0 if rate else _unit_scale(nums)
        return [float(v) * k if _num(v) else None for v in row]

    ys, qs = scaled(yrow), scaled(qrow)
    years = [(lab, v) for lab, v in zip(ylab, ys) if v is not None]
    quarters = [(lab, v) for lab, v in zip(qlab, qs) if v is not None]
    if latest is not None:
        latest *= 1.0 if rate else _unit_scale([latest])
        if any(abs(latest - v) <= abs(v) * 1e-9 for _l, v in years):
            latest = None

    idx = _period_index(sentence, _history_labels(data)) if yrow else None
    qidx = _quarter_indices(sentence, _quarter_labels(data)) if qrow and len(
        _quarter_labels(data)) == len(qrow) else []
    growth = percent and not rate

    levels: list[tuple[str, float]] = []
    moves: list[tuple[str, float]] = []      # (label, change) — level deltas
    # (label, % growth, shown?) — a quarter's growth is listed for the latest
    # quarter only, on the quarter before and the same quarter a year ago;
    # the rest are compared and not printed.
    rates: list[tuple[str, float, bool]] = []

    def run_moves(run: list, *, quarterly: bool) -> None:
        cols = [(lab, v) for lab, v in run]
        last = len(cols) - 1
        for i, ((la, a), (lb, b)) in enumerate(zip(cols, cols[1:]), 1):
            moves.append((f"{la}→{lb}", b - a))
            g = _pct(a, b)
            if g is not None:
                rates.append((f"{lb} vs {la}", g, not quarterly or i == last))
        if quarterly:
            for i in range(4, len(cols)):
                g = _pct(cols[i - 4][1], cols[i][1])
                if g is not None:
                    rates.append((f"{cols[i][0]} vs {cols[i - 4][0]}", g,
                                  i == last))
        elif len(cols) >= 3 and cols[0][1]:
            g = _pct(cols[0][1], cols[-1][1])
            if g is not None:
                rates.append((f"{cols[-1][0]} vs {cols[0][0]}", g, True))
            a, b, n = cols[0][1], cols[-1][1], len(cols) - 1
            if a > 0 and b > 0:
                rates.append((f"a year since {cols[0][0]}",
                              ((b / a) ** (1 / n) - 1) * 100.0, True))

    when = ""
    if qidx:
        where = " for " + "/".join(qlab[i] for i in qidx)
        for i in qidx:
            if qs[i] is None:
                continue
            levels.append((qlab[i], qs[i]))
            for back in (1, 4):
                j = i - back
                if j >= 0 and qs[j] is not None:
                    moves.append((f"{qlab[j]}→{qlab[i]}", qs[i] - qs[j]))
                    g = _pct(qs[j], qs[i])
                    if g is not None:
                        rates.append((f"{qlab[i]} vs {qlab[j]}", g, True))
        shown_levels = levels
    elif idx is not None and idx < len(ys):
        where = f" for {ylab[idx]}"
        if ys[idx] is None:
            return None
        levels = [(ylab[idx], ys[idx])]
        shown_levels = levels
        if growth:
            return None      # a growth INTO a named year: nothing safe to hold it to
    elif period == "quarterly":
        if not quarters:
            return (f"a quarterly figure, and the workbook has no quarterly "
                    f"{_metric_name(metric)} row to check it against")
        where, when = "", "quarterly "
        levels = list(quarters)
        run_moves(quarters, quarterly=True)
        shown_levels = quarters
    elif period == "yearly":
        if not years and latest is None:
            return None
        where, when = "", "yearly "
        levels = years + ([("latest", latest)] if latest is not None else [])
        run_moves(years, quarterly=False)
        shown_levels = levels
    else:
        where = ""
        levels = years + quarters + ([("latest", latest)] if latest is not None else [])
        run_moves(years, quarterly=False)
        run_moves(quarters, quarterly=True)
        shown_levels = []

    if growth:
        candidates = [g for _l, g, _s in rates]
        shown = " · ".join(f"{lab} {g:+,.1f}%" for lab, g, s in rates if s)
    else:
        candidates = [v for _l, v in levels] + [d for _l, d in moves]
        if shown_levels:
            shown = _show_levels(shown_levels, rate, 8)
        else:
            parts = []
            if years:
                parts.append(_show_levels(years, rate, 6))
            if quarters:
                parts.append("quarters " + _show_levels(quarters, rate, 4))
            if latest is not None:
                parts.append(_show_levels([("latest", latest)], rate, 1))
            shown = "; ".join(parts)
    if not candidates:
        return None
    return _Verdict(ok=_matches_scaled(value, candidates),
                    flipped=bool(value) and _matches_scaled(-value, candidates),
                    where=where, shown=shown, when=when)


def fact_check(narration: str, data, *,
               severity: str = "block", ticker: str = "",
               unchecked: list | None = None) -> list[Finding]:
    """Re-read every numeric claim against the loaded company data.

    This is the last line of defence the README describes, and it BLOCKS.
    Every finding was `severity="warn"` for the life of this function, so
    Approve stayed available through any mismatch — beside the code's own
    comment calling this "the one error nobody downstream can catch". An
    advisory last line of defence is not one.

    Blocking is only safe because the four blind spots below are closed. A
    gate that blocks has to be right, so every widening here comes with the
    narrowing that keeps it from firing on a correct script.

    - **No magnitude floor.** Anything under 1,000 was skipped, which is most
      of a workbook written in millions. The unit scale is derived from the
      series, and spoken shorthand ("four ninety six" after "four hundred
      million") is followed by powers of a thousand — a transform that
      changes scale and never digits, so a wrong figure stays wrong.
    - **Percentages are checked.** Every one was skipped, so a wrong margin
      or growth rate was never examined. A rate metric is checked against its
      own series; a percentage against a currency metric is checked against
      that metric's period-over-period growth (and a quarter's against the
      same quarter a year earlier).
    - **A period-specific claim checks that period.** A named column checks
      that column; "quarterly" checks the Quarters sheet and "annual" the
      History sheet, so a quarter's figure is never held to a year's.
    - **Derived claims are claims.** Levels alone could not verify "five
      million of revenue" against a sheet going 491 to 496, so consecutive
      deltas are in the comparison set.

    Sentence-level attribution is the one thing a regex cannot do, and it is
    handled conservatively: a number attached to its own subject is not read
    as a claim about a metric named elsewhere, a bare number that counts
    something ("three years", "two hundred layoffs") is not a figure, a
    percentage OF something is a share of it, the day's move is the price's,
    and a figure whose only metric is in another clause of the sentence is
    a guess, which warns and never blocks (`_owner_of`). The coreference case
    — a figure whose metric was named in the PREVIOUS sentence — is
    deliberately out of scope rather than approximated.
    """
    findings: list[Finding] = []
    if data is None:
        return findings
    # WHAT IT PASSED UNREAD, when `unchecked` is a list: (line, sentence,
    # why) for a figure about the future or a ratio, which the sheet has no
    # row for. They passed silently, and read on the report as checked.
    skipped: list = unchecked if unchecked is not None else []

    def _skip(lineno: int, sentence: str, why: str) -> None:
        if not any(n == lineno and t == sentence for n, t, _w in skipped):
            skipped.append((lineno, sentence, why))

    known, unreadable = _known_series(data)
    findings.extend(unreadable)
    for name, parts in _EITHER_METRIC.items():
        known[name] = [v for p in parts for v in known.get(p) or []]
    price_move = _price_move_re(ticker, _company_names(data))
    labels = _history_labels(data)
    for lineno, line in enumerate(narration.splitlines(), 1):
        for sentence in _sentences(line):
            low = sentence.lower()
            named = {m: pos for m, pos in
                     _metrics_named(low, _SPOKEN_METRIC_WORDS).items()
                     if known.get(m)}
            ratio = next((r for r in _RATIO_PHRASES if r in low), "")
            if ratio and spoken_figures(_mask_labels(sentence, labels)):
                _skip(lineno, sentence, f"{ratio}: a ratio, not a line of the workbook")
            if not named:
                continue
            # A period label is not a figure. "In FY-2, revenue was…" carries
            # a 2 that `extract_numbers` reads as a number, and the old
            # magnitude floor hid it — dropping the floor exposed it, so the
            # labels are masked out before anything is extracted.
            # Figures only: "there is one reason revenue stalled" states no
            # revenue of one (`spoken_figures`).
            figures = spoken_figures(_mask_labels(sentence, labels))
            period = _said_period(low)
            for num in figures:
                # The span the extractor recorded, never a re-`find`: a
                # hyphenated spoken run does not appear verbatim in the
                # sentence and used to collapse to position 0.
                pos, end = num.start, num.end
                if num.is_percent and price_move.search(low[:pos]):
                    continue
                if _counts_things(low, num):
                    continue
                clause = _clause(low, pos, end)
                if _FORWARD_CLAUSE_RE.search(clause):
                    _skip(lineno, sentence, "guidance or an estimate: the "
                                            "workbook only has what was reported")
                    continue
                if num.is_percent and _IMPLIED_RE.search(clause):
                    _skip(lineno, sentence, "what the price implies: a "
                                            "valuation, not a figure the "
                                            "company reported")
                    continue
                lo, hi = _own_clause(low, pos, end)
                if (num.is_percent and _SESSION_RE.search(low[lo:hi])
                        and not any(lo <= at[0] and at[1] <= hi
                                    for at in named.values())):
                    continue         # "down ten percent today": the price
                metric, sure = _owner_of(pos, end, low[end:], named, low,
                                         figures, percent=num.is_percent)
                if metric is None:
                    continue
                # A margin IS a share of revenue; only a level's growth is
                # not what "three percent of revenue" says.
                if (num.is_percent and metric not in _RATE_METRICS
                        and _SHARE_OF_RE.match(low[end:])):
                    continue

                value = num.value
                before = low[:pos].rstrip() if pos >= 0 else ""
                if _NEGATIVE_RE.search(before) or (
                        value > 0 and (_FALL_RE.search(before) or (
                            not num.is_percent
                            and _NEGATIVE_AFTER_RE.match(low[end:])))):
                    value = -value
                verdicts, reasons = [], []
                for part in _EITHER_METRIC.get(metric, (metric,)):
                    if not known.get(part):
                        continue
                    got = _judge(data, part, sentence, value, num.is_percent,
                                 period)
                    if isinstance(got, str):
                        reasons.append(got)
                    elif got is not None:
                        verdicts.append(got)
                if not verdicts:
                    if reasons:
                        _skip(lineno, sentence, reasons[0])
                    continue
                if any(v.ok for v in verdicts):
                    continue
                v = verdicts[0]
                kind = _metric_name(metric)
                if metric in _EITHER_METRIC:
                    kind += " (free or operating)"
                if num.is_percent and metric not in _RATE_METRICS:
                    kind += " growth"
                message = (f"“{num.text}” is stated for {v.when}{kind}{v.where} "
                           f"but your workbook has {v.shown}")
                if v.flipped:
                    message += (" — the size matches, the sign does not: if "
                                "it is a loss or an outflow, say “negative”, "
                                "“a loss of” or “burned”" if value > 0 else
                                " — the size matches, the sign does not: the "
                                "workbook has it above zero")
                level = severity
                if not sure:
                    at = named[metric]
                    message += (f" — a guess: “{low[at[0]:at[1]]}” is the "
                                f"nearest figure name, but it is in another "
                                f"part of the sentence, so this does not block")
                    level = "warn" if severity == "block" else severity
                findings.append(Finding(
                    gate="fact-check", severity=level, line=lineno,
                    message=message, excerpt=sentence.strip()[:140],
                ))
    return findings


# --------------------------------------------------------------------------
# Voice linter — bible violations only.
# --------------------------------------------------------------------------

_HYPE = ("massive", "insane", "incredible", "unbelievable", "skyrocket",
         "explosive", "game-changer", "game changer", "to the moon",
         "guaranteed", "no-brainer", "must-buy", "slam dunk", "epic")
_CALLS = ("buy now", "you should buy", "you should sell", "price target",
          "strong buy", "table pounding")
_VENDORS = VENDOR_WORDS


# --------------------------------------------------------------------------
# The two v2 rules that are checkable.
#
# "No construction twice in one script. One reframe, one simile chain, one
# bathos drop, one fake-out. Maximum. ... This is checkable by the voice
# linter: pattern-match the construction and flag the repeat."
#
# Three of the four have a surface form precise enough to match. BATHOS DOES
# NOT, and it is deliberately absent rather than approximated: its signature is
# a grand setup deflated by something mundane, which has no lexical marker at
# all, and a fuzzy matcher for it would fire on ordinary sentences. A check
# that cries wolf gets switched off, and takes the three accurate ones with it.
_CONSTRUCTIONS: tuple[tuple[str, str, "re.Pattern[str]"], ...] = (
    ("reframe", "that's not X, it's Y",
     re.compile(r"\bth(?:at|is|at's|is's|ese|ose)?\s*(?:'s|is|isn't|is not|"
                r"was|wasn't)?\s*n(?:o|ot)\b[^.?!]{2,60}?[,;]\s*"
                r"(?:it|that|this)\s*(?:'s|is|was)\b", re.I)),
    ("simile", "a flat simile",
     re.compile(r"\b(?:like|as if)\s+(?:a|an|the|it|you|they|somebody|"
                r"someone|watching)\b", re.I)),
    ("fake-out", "the sincere fake-out",
     re.compile(r"\[BEAT\]\s*(?:it|that|and it|but it)\s*(?:'s|is|has|"
                r"was)\s+(?:also|still|been)\b", re.I)),
)

# How many of each a script may carry before the next is flagged (bible v4
# §4). The reframe and the fake-out stay at one: the first is the phrase a
# machine reaches for, the second stops working once it can be heard coming.
# A joke-dense script uses more similes than v3's did, so three of those.
CONSTRUCTION_LIMITS: dict[str, int] = {"reframe": 1, "fake-out": 1, "simile": 3}

# A TURN, for the twenty-second rule. Not "anything interesting happened" —
# the four things the bible names: an aside, a number anchored, a mode shift,
# a question. A bare figure is not one of them: this register states figures
# continuously, so counting them as turns would mean the check never fires,
# which is the same as not having it. What makes an anchored number a turn is
# the anchor, and the anchor is addressed to somebody.
def _turn_pattern() -> "re.Pattern[str]":
    from pipeline.models import DELIVERY_TAG_TYPES

    marks = "|".join(re.escape(t.value) for t in
                     sorted(DELIVERY_TAG_TYPES, key=lambda t: t.value))
    return re.compile(rf"[?]|\[(?:{marks})\]|"
                      r"\b(?:i|i'm|i've|i'd|i'll|me|my|you|you're|you've|you'd|"
                      r"you'll|your|we|we're|us|our)\b", re.I)


_TURN = _turn_pattern()

# Seconds of unbroken exposition before it is worth saying so. The bible says
# "about twenty", and about is the operative word — 24 gives a long sentence
# room to finish rather than flagging the one that runs two words over.
UNBROKEN_LIMIT_S = 24.0

# Spoken words per second. The read is slow and the number only has to be
# right enough to turn a word count into "about twenty seconds".
SPOKEN_WPS = 2.4

def _unbroken_runs(narration: str) -> list[tuple[int, float, str]]:
    """Stretches with no turn in them: (line, seconds, opening words).

    Counted word by word rather than sentence by sentence. A turn three words
    into a forty-word sentence ends the run there — attributing the rest of
    that sentence to the stretch before it reports a stretch that was never
    spoken, and the number in the message has to be one the writer can hear.
    """
    runs: list[tuple[int, float, str]] = []
    for lineno, line in enumerate(narration.splitlines(), 1):
        run: list[str] = []
        # A tag is one token: "[LONG BEAT]" split on its space was never seen.
        for word in re.findall(r"\[[^\]]*\]|\S+", line):
            run.append(word)
            if not _TURN.search(word):
                continue
            # The turn's own word ends the run and does not start the next.
            secs = (len(run) - 1) / SPOKEN_WPS
            if secs > UNBROKEN_LIMIT_S:
                runs.append((lineno, secs, " ".join(run[:12])))
            run = []
        if len(run) / SPOKEN_WPS > UNBROKEN_LIMIT_S:
            runs.append((lineno, len(run) / SPOKEN_WPS, " ".join(run[:12])))
    return runs


def delivery_text(script) -> str:
    """The narration with its PACING marks put back where the writer wrote them.

    `script.narration` is what the voice reads, so the tokenizer has taken
    every bracket out of it — including `[BEAT]`, `[SIGH]`, `[DRY]` and
    `[FLAT]`, which are not visuals but punctuation the writer placed. Linting
    the stripped text makes a beat invisible, so a stretch broken by one reads
    as unbroken and the sincere fake-out — whose whole shape is a concession, a
    beat, then a short clause — cannot be recognised at all.

    Not the RAW script: that carries `[PLATE]` payloads full of prose, and a
    caption reading "like a memoir title" is not a simile Dennis spoke.
    """
    narration = getattr(script, "narration", None) or getattr(
        script, "audio_script", "")
    from pipeline.models import DELIVERY_TAG_TYPES

    marks = {t.value for t in DELIVERY_TAG_TYPES}
    # A SHORT keeps its tags in `inline_events`, as `_delivery_events` reads.
    events = [e for e in (getattr(script, "events", None)
                          or getattr(script, "inline_events", None) or [])
              if str(getattr(getattr(e, "type", None), "value", "")).upper() in marks]
    if not events:
        return narration
    out = []
    at = 0
    for e in sorted(events, key=lambda e: getattr(e, "char_offset", 0)):
        cut = max(0, min(int(getattr(e, "char_offset", 0)), len(narration)))
        if cut < at:
            continue
        out.append(narration[at:cut])
        out.append(f" [{str(e.type.value).upper()}] ")
        at = cut
    out.append(narration[at:])
    return "".join(out)


def voice_lint(narration: str) -> list[Finding]:
    """Flags what the bible forbids. The joke floor is not here: it is
    counted off the writer's declared list (`writing_checks.joke_floor_lint`),
    because a regex cannot find a joke and guessing would flatten the voice.

    Two of the flags are structural rather than lexical, and they are the two
    the bible asks for by name: a construction used twice in one script, and a
    stretch of explanation with no turn in it. Both are warnings. The first
    repeat of a good construction is not a defect that should stop a render —
    it is the thing the writer should go and fix, and saying which line it was
    is the whole use of saying it at all.
    """
    findings: list[Finding] = []

    # A construction used past its allowance. The allowance is the licence;
    # the next one is the finding, and it carries the first's line number so
    # the writer can see what it is repeating rather than hunting for it.
    for name, described, pattern in _CONSTRUCTIONS:
        allowed = CONSTRUCTION_LIMITS.get(name, 1)
        hits = [(n, ln) for n, ln in enumerate(narration.splitlines(), 1)
                if pattern.search(ln)]
        for lineno, line in hits[allowed:]:
            findings.append(Finding(
                gate="voice", severity="warn", line=lineno,
                message=(f"{described} again — "
                         f"{'one' if allowed == 1 else allowed} {name}"
                         f"{'' if allowed == 1 else 's'} per script. "
                         f"The first is on line {hits[0][0]}; no individual "
                         f"one is bad, the repeat is what reads as tired"),
                excerpt=line.strip()[:140]))

    for lineno, secs, opening in _unbroken_runs(narration):
        findings.append(Finding(
            gate="voice", severity="warn", line=lineno,
            message=(f"about {secs:.0f} seconds of explanation with no turn in "
                     f"it — an aside, a number anchored, a mode shift or a "
                     f"question, roughly every twenty"),
            excerpt=opening.strip()[:140]))

    for lineno, line in enumerate(narration.splitlines(), 1):
        low = line.lower()
        for word in _HYPE:
            if word in low:
                findings.append(Finding(
                    gate="voice", severity="warn", line=lineno,
                    message=f"hype adjective “{word}” — the bible bans these",
                    excerpt=line.strip()[:140]))
        for phrase in _CALLS:
            if phrase in low:
                findings.append(Finding(
                    gate="voice", severity="warn", line=lineno,
                    message=f"“{phrase}” reads as a call — Dennis is anti-Cramer",
                    excerpt=line.strip()[:140]))
        for vendor in _VENDORS:
            if vendor in low:
                findings.append(Finding(
                    gate="voice", severity="block", line=lineno,
                    message=f"data vendor “{vendor}” would be spoken and captioned",
                    excerpt=line.strip()[:140]))
        if "!" in line:
            findings.append(Finding(
                gate="voice", severity="warn", line=lineno,
                message="exclamation mark — the register is flat",
                excerpt=line.strip()[:140]))
        # A figure written for the eye. WARNING, never a block: whether the
        # number is RIGHT is fact_check's question and it has already been
        # asked, and a render stopped over a dollar sign would be a gate
        # nobody leaves switched on. This is only about how it is spelled —
        # and it is the one defect the two existing verification systems can
        # both pass while the voice still says it wrong out loud.
        for raw, said in eye_written_figures(line):
            findings.append(Finding(
                gate="voice", severity="warn", line=lineno,
                message=(f"“{raw}” is written for the eye — the voice reads a "
                         f"symbol, a comma and a decimal point literally. "
                         f"Write it spoken: “{said}”"),
                excerpt=line.strip()[:140]))
        # The same defect one layer out: the abbreviations this register is
        # built from. A figure at least arrives as digits a voice recognises;
        # "YoY" is a word to it, and it says one.
        for raw, said in eye_written_terms(line):
            findings.append(Finding(
                gate="voice", severity="warn", line=lineno,
                message=(f"“{raw}” is written for the eye — the voice does not "
                         f"say it the way a person does. "
                         f"Write it spoken: “{said}”"),
                excerpt=line.strip()[:140]))
    return findings


# --------------------------------------------------------------------------
# Delivery direction: what the writer may declare, and how much of it.
# --------------------------------------------------------------------------
# The vocabulary and the ceilings are in pipeline/direction.py. This reads them
# rather than restating them, so the prompts, the expander and the linter
# cannot drift apart on what a tag is or how often it may appear.
#
# Everything here is a WARNING except one thing: a banned tag written in the
# lowercase spelling the ElevenLabs docs use is a BLOCK, because that spelling
# is not a tag at all to the bracket grammar. It survives into the narration,
# gets spoken, and lands in the captions — the same class of defect as the
# data vendor's name, which blocks for the same reason.

# `[laughs]`, `[applause]`, `[Laughs]` — anything the bracket grammar did not
# recognise as a tag and therefore left in the narration to be spoken. Matched
# in ANY case: the tokenizer only strips a SHOUTED type, so `[Laughs]` escapes
# it exactly as the lowercase spelling does, and an uppercase tag cannot reach
# this text at all.
_SPOKEN_TAG_RE = re.compile(r"\[([A-Za-z][A-Za-z ]{1,30})\]")
# The opening of a tag with a payload the tokenizer left behind.
_LEFTOVER_TAG_RE = re.compile(r"\[[A-Z][A-Z -]*:")

# A shouted word used for emphasis. v3 and v4 read capitals as emphasis, which
# makes it live formatting rather than typography — but the captions use the
# CLEAN text, so it also reaches the screen shouting. The bible already bans
# the exclamation mark for this exact reason.
_EMPHASIS_CAPS_RE = re.compile(r"(?<![\w'’])([A-Z]{2,})(?![\w'’])")

# Tokens that are legitimately capitalised in a filing discussion and are not
# somebody leaning on a word. The ticker is added per script.
_ACRONYMS = frozenset({
    "AI", "API", "ARR", "ARPU", "CAGR", "CAPEX", "CEO", "CFO", "COO", "CTO",
    "DCF", "EBIT", "EBITDA", "EPS", "ESG", "ETF", "EU", "EV", "FCF", "FDA",
    "FX", "GAAP", "GDP", "GPU", "IPO", "IRR", "KPI", "M&A", "NASDAQ", "NAV",
    "NYSE", "OEM", "OPEX", "P&L", "PE", "R&D", "ROE", "ROIC", "RSU", "SAAS",
    "SEC", "SG&A", "SKU", "TAM", "TSR", "UK", "US", "USA", "USD", "VAT", "YOY",
    "YTD",
    # The workbook's own row names and the macro chapter's institutions: the
    # scan's clean scripts warned on every one (24 Oct 2026).
    "LTM", "TTM", "COGS", "SBC", "CPI", "FOMC",
})


def _peer_tokens(peers) -> set[str]:
    """The Peers sheet's names as a script would write them: a ticker
    ("NASDAQGS:ACME" or "ACME") or a name already in capitals ("IBM Corp").
    A peer named in its own capitals is a ticker, not a shout."""
    out: set[str] = set()
    for p in peers or ():
        name = str((p.get("name") if isinstance(p, dict) else p) or "")
        name = name.rsplit(":", 1)[-1]
        out.update(w for w in re.findall(r"[A-Za-z&]{2,}", name) if w.isupper())
    return out

_SENTENCE_END_RE = re.compile(r"[.!?…]+[\s\"'’”)]*")

# Below this the script is a fragment and a per-thousand rate says nothing.
_RATE_FLOOR_CHARS = 400


def _delivery_events(script) -> list:
    """The delivery direction on a script of either format."""
    from pipeline.models import DELIVERY_TAG_TYPES

    events = (getattr(script, "events", None)
              or getattr(script, "inline_events", None) or [])
    return sorted((e for e in events if e.type in DELIVERY_TAG_TYPES),
                  key=lambda e: getattr(e, "char_offset", 0))


def _sentence_index(narration: str) -> list[int]:
    """The sentence number each character of the narration belongs to."""
    idx = [0] * (len(narration) + 1)
    n = 0
    at = 0
    for m in _SENTENCE_END_RE.finditer(narration):
        for i in range(at, min(m.end(), len(narration) + 1)):
            idx[i] = n
        at = m.end()
        n += 1
    for i in range(at, len(narration) + 1):
        idx[i] = n
    return idx


def direction_lint(script, *, peers=()) -> list[Finding]:
    """The delivery vocabulary, and the ceilings on using it.

    A device used constantly stops being a device — the bible caps repetition
    for that reason and direction is a device. None of this is a rewrite: the
    ceilings are notes, the writer decides.
    """
    from pipeline.direction import (BANNED_TAGS, MAX_TAGS_PER_SENTENCE,
                                    PER_SCRIPT_MAX, TAGS_PER_1K_CHARS_WARN)

    narration = getattr(script, "narration", None) or getattr(
        script, "audio_script", "")
    findings: list[Finding] = []

    # 1. A banned tag that is going to be SPOKEN.
    for lineno, line in enumerate(narration.splitlines(), 1):
        for m in _SPOKEN_TAG_RE.finditer(line):
            reason = BANNED_TAGS.get(m.group(1).lower())
            if reason:
                findings.append(Finding(
                    gate="direction", severity="block", line=lineno,
                    message=(f"“[{m.group(1)}]” is not an allowed direction — "
                             f"{reason}. Written in lowercase it is not a tag "
                             f"at all: it would be read out and captioned"),
                    excerpt=line.strip()[:140]))

    # 1a. A tag the tokenizer could not read ("[PLATE: …" never closed, or
    #     broken by a blank line) is still in the text: the voice would read
    #     its slot syntax out and the captions would print it.
    for lineno, line in enumerate(narration.splitlines(), 1):
        m = _LEFTOVER_TAG_RE.search(line)
        if m:
            findings.append(Finding(
                gate="direction", severity="block", line=lineno,
                message=(f"“{m.group(0)}…” is still in the spoken text — the "
                         f"tag is not closed on its own lines, so it would "
                         f"be read out and captioned. Close it with ] before "
                         f"any blank line"),
                excerpt=line.strip()[:140]))

    # 1b. A shouted word. On v3 and v4 capitals are live formatting — the docs
    #     say it increases emphasis — so this is no longer only typography.
    #     It is also NOT only an audio decision: captions are built from the
    #     clean text, so an emphasised word reaches the screen shouting too.
    #     Banned on the same ground as the exclamation mark, which the bible
    #     already forbids: shouting in text is the written form of trying.
    known = set(_ACRONYMS)
    ticker = str(getattr(script, "ticker", "") or "").upper()
    if ticker:
        known.add(ticker)
    known |= _peer_tokens(peers)
    for lineno, line in enumerate(narration.splitlines(), 1):
        for m in _EMPHASIS_CAPS_RE.finditer(line):
            word = m.group(1)
            if word in known:
                continue
            findings.append(Finding(
                gate="direction", severity="warn", line=lineno,
                message=(f"“{word}” is shouted. The voice reads capitals as "
                         f"emphasis, and the captions are built from this same "
                         f"text — so it is heard AND seen leaning on the word. "
                         f"The bible bans the exclamation mark for this; write "
                         f"the emphasis into the sentence, or place a "
                         f"direction"),
                excerpt=line.strip()[:140]))

    events = _delivery_events(script)
    if not events:
        return findings

    # 2a. A direction that landed INSIDE a word. Almost always a missing space
    #     before the bracket — but it splits the word in the request, so the
    #     alignment comes back with two half-words and any cue anchored on that
    #     word anchors on half of it. Cheap to say, invisible otherwise.
    for e in events:
        off = int(getattr(e, "char_offset", 0))
        if 0 < off < len(narration) and not (
                narration[off - 1].isspace() or narration[off].isspace()):
            word = narration[max(0, off - 20):off + 20].strip()
            findings.append(Finding(
                gate="direction", severity="warn",
                message=(f"[{e.type.value}] falls inside a word — it splits it "
                         f"in the request, so the voice pauses mid-word and any "
                         f"visual anchored there anchors on half of one. Put a "
                         f"space before the bracket"),
                excerpt=word[:140]))

    # 2. One per sentence, and never two with nothing between them.
    sent = _sentence_index(narration)
    per_sentence: dict[int, list] = {}
    for e in events:
        off = max(0, min(int(getattr(e, "char_offset", 0)), len(narration)))
        per_sentence.setdefault(sent[off], []).append(e)
    for _, group in sorted(per_sentence.items()):
        if len(group) > MAX_TAGS_PER_SENTENCE:
            names = ", ".join(f"[{e.type.value}]" for e in group)
            findings.append(Finding(
                gate="direction", severity="warn",
                message=(f"{len(group)} directions in one sentence ({names}) — "
                         f"the ceiling is {MAX_TAGS_PER_SENTENCE}. Stacked "
                         f"direction is the model performing, which is the "
                         f"thing the flat register is instead of")))
    for a, b in zip(events, events[1:]):
        gap = narration[getattr(a, "char_offset", 0):getattr(b, "char_offset", 0)]
        if not gap.strip():
            findings.append(Finding(
                gate="direction", severity="warn",
                message=(f"[{a.type.value}] and [{b.type.value}] are adjacent "
                         f"with no words between them — one direction at a "
                         f"time, or the delivery is doing the writing")))

    # 3. Across the whole script. Not on a fragment: below a few hundred
    #    characters a "per thousand" rate is arithmetic about a script that
    #    does not exist, and the per-sentence ceiling above is the one that
    #    means anything there.
    if len(narration) >= _RATE_FLOOR_CHARS:
        rate = len(events) / (len(narration) / 1000.0)
        if rate > TAGS_PER_1K_CHARS_WARN:
            findings.append(Finding(
                gate="direction", severity="warn",
                message=(f"{len(events)} directions across {len(narration)} "
                         f"characters ({rate:.1f} per 1,000; the ceiling is "
                         f"{TAGS_PER_1K_CHARS_WARN:.0f}) — past this the "
                         f"direction is the texture rather than the exception "
                         f"to it")))

    # 4. Per-tag ceilings. The lift is the retention, and a lift that happens
    #    six times is a monotone again.
    counts: dict = {}
    for e in events:
        counts[e.type] = counts.get(e.type, 0) + 1
    for tag, cap in PER_SCRIPT_MAX.items():
        n = counts.get(tag, 0)
        if n > cap:
            findings.append(Finding(
                gate="direction", severity="warn",
                message=(f"[{tag.value}] {n} times — the ceiling is {cap} per "
                         f"script. Used more often it stops being the "
                         f"exception it is for")))

    # 5. Dark calm is earned, not opened on. Chapters carry no offsets until
    #    the timeline exists, so "the first chapter" is the opening share of
    #    the narration by chapter count — approximate on purpose, and a
    #    warning for exactly that reason.
    from pipeline.models import TagType

    chapters = getattr(script, "chapter_list", None) or []
    if chapters and narration:
        opening = len(narration) / max(len(chapters), 1)
        for e in events:
            if e.type is TagType.QUIET and getattr(e, "char_offset", 0) < opening:
                findings.append(Finding(
                    gate="direction", severity="warn",
                    message=("[QUIET] in the opening chapter — dark calm is "
                             "the register the video earns its way down to, "
                             "and it has nothing to drop from yet")))
    return findings


# --------------------------------------------------------------------------
# Figures that reach the screen.
# --------------------------------------------------------------------------

# What a plate's `unit=` slot means as a multiplier. The director writes `400`
# under `unit=$M`, and the export holds 400,000,000; comparing those raw
# rejects every correct sheet in the library.
_UNIT_SCALE: tuple[tuple[str, float], ...] = (
    ("$b", 1e9), ("bn", 1e9), ("billion", 1e9),
    ("$m", 1e6), ("mm", 1e6), ("million", 1e6),
    ("$k", 1e3), ("thousand", 1e3),
)


def _declared_unit(values: dict[str, str]) -> float | None:
    """The multiplier the plate declares, or None when it declares none.

    Looked for in `unit` AND `kicker`, because the kit puts it in both:
    each `tables/numbers-sheet-*` has a `unit` slot reading "$M", and
    `structure/row-spotlight` carries it in the kicker as "NET INCOME, $M".
    Reading only `unit` made every spotlight compare millions against dollars,
    and every correct one of them blocked.
    """
    for slot in ("unit", "kicker", "head-move"):
        low = str(values.get(slot) or "").strip().lower()
        for token, mult in _UNIT_SCALE:
            if token in low:
                return mult
    return None


# The families a numbers plate uses for its rows, and where each finds its
# label. Read off the slot names the FILL produced rather than off the plate,
# because what is being checked is what the director actually wrote.
_ROW_STEMS = ("cell", "row", "subtotal", "total")

# A row label that says it holds a RATE OF CHANGE of the line it names.
_GROWTH_LABEL_RE = re.compile(r"\bgrowth\b|\byoy\b|\by/y\b|\bcagr\b")


def _row_figures(values: dict[str, str]) -> list[tuple[str, list[str]]]:
    """(label, its figures) for every labelled row the director filled.

    Row keys are whatever sits between the stem and the final column index, so
    one rule covers all three shapes the library uses: `cell-3-1 … cell-3-6`
    under `label-3` on a plain sheet, `cell-2-1-1 … cell-2-1-6` under
    `label-2-1` on a grouped cash-flow statement, and a single unindexed row's
    `cell-1 … cell-6` under `label`. Subtotals and the total line are rows too
    — "cash from operations" is the most quoted line on a cash-flow sheet, and
    it is a subtotal.
    """
    rows: dict[tuple[str, str], list[tuple[int, str]]] = {}
    labels: dict[tuple[str, str], str] = {}
    for name, raw in values.items():
        parts = name.split("-")
        stem, rest = parts[0], parts[1:]
        if stem == "label":
            labels[("cell", "-".join(rest))] = str(raw)
            continue
        if stem not in _ROW_STEMS:
            continue
        if rest and rest[0] == "label":
            labels[(stem, "-".join(rest[1:]))] = str(raw)
            continue
        if not rest or not rest[-1].isdigit():
            continue
        rows.setdefault((stem, "-".join(rest[:-1])), []).append(
            (int(rest[-1]), str(raw)))

    out = []
    for (stem, key), cells in rows.items():
        label = (labels.get((stem, key)) or labels.get((stem, ""))
                 or labels.get(("cell", key)) or "")
        if label:
            out.append((label, [v for _, v in sorted(cells)]))
    return out


_CELL_UNIT_RE = re.compile(r"\d\s*(?:bn|mm|mn|[kmbt])\s*\)?$", re.IGNORECASE)


def _cell_has_unit(raw: str) -> bool:
    """Does the cell carry its own scale letter, as `_cell_value` reads it?"""
    text = (str(raw or "").replace(",", "").replace("$", "").replace("%", "")
            .strip())
    return bool(_CELL_UNIT_RE.search(text))


def _cell_value(raw: str) -> float | None:
    """A plate cell as a signed number, or None when it holds no figure.

    NOT `extract_numbers`, which is built for prose and returns the magnitude:
    it reads "-8" as eight, so a loss compared clean against a profit and every
    negative row on every sheet passed. A cell is not a sentence — it is a
    figure the director typed, and it is read as one.
    """
    text = str(raw or "").strip()
    if not text:
        return None                     # an empty cell means NO DATA
    cleaned = (text.replace(",", "").replace("$", "").replace("%", "")
                   .replace("\u2212", "-").replace("\u2013", "-").strip())
    mult = 1.0
    # "0.9bn", "900mm", "$3.1bn" (the prompt's own example) as well as the
    # single letters. A cell of only "$" or "%" used to test "" against
    # "kmbt", which is True, and the index that followed crashed the battery.
    unit = re.search(r"(bn|mm|mn|[kmbt])$", cleaned, re.IGNORECASE)
    if unit and unit.start() > 0:
        mult = {"k": 1e3, "m": 1e6, "mm": 1e6, "mn": 1e6, "b": 1e9,
                "bn": 1e9, "t": 1e12}[unit.group(1).lower()]
        cleaned = cleaned[:unit.start()].strip()
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = "-" + cleaned[1:-1]   # accountants' parentheses are a minus
    try:
        return float(cleaned) * mult
    except ValueError:
        return None


def onscreen_fact_check(script, data) -> list[Finding]:
    """Figures written into a plate, checked against the export. BLOCKING.

    "The register is sharper and more confident than v1, which raises what an
    error costs. A dry channel that gets a number wrong looks careless; a
    sharp one that gets a number wrong looks like it was never checking."

    So this blocks where the spoken check warns, and the asymmetry is the
    point rather than an inconsistency: a spoken figure is a sentence a viewer
    hears once and a linter can misread, while a figure in a `[PLATE]` slot is
    a number the director typed, held on screen for six seconds, and
    screenshotted by anyone who disagrees with it. The voice gets to be as
    confident as it likes precisely because these were verified before
    anything rendered.
    """
    findings: list[Finding] = []
    if data is None:
        return findings
    known, unreadable = _known_series(data)
    findings.extend(unreadable)

    for event in getattr(script, "events", None) or []:
        values = dict(getattr(event, "values", None) or {})
        if not values:
            continue
        declared = _declared_unit(values)
        for label, figures in _row_figures(values):
            low = str(label).lower()
            metric = next(iter(_metrics_named(low)), "")
            series = known.get(metric) or []
            if not metric or not series:
                continue
            # A GROWTH ROW IS NOT THE LEVEL IT NAMES. "Revenue growth" names
            # revenue, and its percentages were compared with revenue in
            # dollars. The export holds no growth row to check them against,
            # so the row is left alone rather than blocked.
            if metric not in _RATE_METRICS and _GROWTH_LABEL_RE.search(low):
                continue
            # THE SHEET'S UNIT IS ITS CURRENCY. `unit=$M` scales the money
            # rows; a margin on the same sheet is already in percent, and
            # multiplying it by a million compared 58% with 58,000,000.
            scale = 1.0 if metric in _RATE_METRICS or declared is None \
                else declared

            # POSITION MATTERS ON A SHEET. Six cells under six period heads
            # against a six-period history is a column-by-column comparison,
            # and only that catches a figure put under the wrong year — a
            # membership test passes every one of those, because the number is
            # in the series, just not there. Where the lengths disagree the
            # test falls back to membership rather than guessing an alignment.
            history = _history_for(data, metric)
            aligned = history if len(history) == len(figures) else []

            for i, figure in enumerate(figures):
                stated = _cell_value(figure)
                if stated is None:
                    continue            # an empty cell means NO DATA
                if "%" in figure and metric not in _RATE_METRICS:
                    continue            # a share of a money line is not its level
                # A cell that says its own unit ("$1.1B") is not scaled by
                # the sheet's again: under `unit=$B` it read as 1.1e18 and
                # every cell blocked (scan, 24 Oct 2026).
                if not _cell_has_unit(figure):
                    stated *= scale
                if aligned:
                    want = aligned[i]
                    # With a unit declared the comparison is exact. Without
                    # one the plate has not said what "212" means, so the
                    # scale-tolerant test is the only honest one — still
                    # against THAT column, which is the half that matters.
                    hit = (abs(stated - want) <= max(abs(want) * _TOLERANCE, 1e-9)
                           if declared is not None else _matches(stated, [want]))
                    if hit:
                        continue
                    expected = f"{want:,.0f} in that column"
                else:
                    if _matches(stated, series):
                        continue
                    expected = ", ".join(f"{v:,.0f}" for v in series[:6])
                findings.append(Finding(
                    gate="fact-check", severity="block",
                    message=(f"“{figure}” is on screen for {metric} and the "
                             f"data has {expected} — a figure that reaches the "
                             f"frame is verified before anything renders"),
                    excerpt=f"{label}: {', '.join(figures)}"[:140]))
    return findings


# --------------------------------------------------------------------------
# The confession ledger, checked.
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# The valuation chapter's four moves, in order.
# --------------------------------------------------------------------------

# Move 2 — a forward multiple is being quoted. A forward number is a smaller
# number because something came out of the denominator.
_FORWARD_WORDS = (
    "forward p/e", "forward pe", "forward multiple", "forward earnings",
    "forward peg", "next year's earnings", "next year's estimates",
    "on forward numbers", "fwd p/e",
    # The spoken forms the voice lint asks for: written that way, a forward
    # multiple with no peer comparison passed (scan, 24 Oct 2026).
    "forward price to earnings", "forward price-to-earnings", "forward p e",
    "forward p-e", "forward ev to ebitda", "forward enterprise value",
    "price to next year's earnings",
)

# Move 3 — the subject placed against the peer set. Any of these is the move
# being made; the plate is the strongest signal and the language is the rest.
_PEER_WORDS = (
    "percentile", "peer", "peers", "against the group", "versus the group",
    "vs the group", "in its sector", "comparable companies", "comps",
    "cheaper than", "dearer than", "more expensive than", "trades above",
    "trades below", "rest of the industry",
)

# Move 4 — the reverse DCF. The line this chapter has always been able to
# reach for, and the one it reaches for INSTEAD of move 3.
_REVERSE_DCF_WORDS = (
    "priced for", "implied growth", "priced in", "baked in", "bakes in",
    "has to grow", "would have to grow", "what has to be true",
    "reverse dcf", "already assumes", "the price assumes",
)

# The plates that ARE move 3 and move 2. A director who reached for either has
# made the move whatever the narration calls it.
_PEER_PLATES = ("tables/multiples-strip", "peers/peer-strip")
_BRIDGE_PLATE = "structure/multiple-bridge"


def valuation_moves(script, settings: Settings) -> list[Finding]:
    """The valuation chapter's four moves, in order. BLOCKING on a skipped 3.

    1 trailing multiples, 2 forward multiples (and SAY the denominator
    changed), 3 where the subject sits against the peer set, 4 the reverse DCF.

    The order is the argument: 1 into 2 establishes that the number is
    contested, 3 says whether it is expensive against anyone else, and 4 says
    what would have to be true. **A chapter that does 4 without 3 is the old
    behaviour** — it quotes a forward multiple, jumps straight to "the price is
    priced for 25% growth", and never answers the question a viewer actually
    has, which is "expensive compared to what?". That jump is the thing the
    whole multiples-strip pack exists to end, so it blocks.

    It fires only on the exact signature: forward multiples present, reverse
    DCF present, peer comparison absent in BOTH the narration and the plates.
    A chapter that never reaches move 2 or move 4 is a different shape and is
    not this gate's business — a script is not failed here for being short.
    """
    from pipeline.models import TagType

    narration = (getattr(script, "narration", None)
                 or getattr(script, "audio_script", "") or "")
    low = narration.lower()

    keys = {str(getattr(e, "payload", "") or "")
            for e in (getattr(script, "events", None)
                      or getattr(script, "inline_events", None) or [])
            if getattr(e, "type", None) is TagType.PLATE}

    did_forward = (any(w in low for w in _FORWARD_WORDS)
                   or any(k.startswith(_BRIDGE_PLATE) for k in keys))
    did_reverse_dcf = any(w in low for w in _REVERSE_DCF_WORDS)
    did_peers = (any(w in low for w in _PEER_WORDS)
                 or any(k.startswith(_PEER_PLATES) for k in keys))

    if not (did_forward and did_reverse_dcf) or did_peers:
        return []
    return [Finding(
        gate="valuation",
        severity="block",
        message=(
            "the valuation chapter goes from forward multiples straight to the "
            "reverse DCF and never places the subject against its peer set — "
            "move 3 of four is missing. 'Priced for growth' answers 'expensive "
            "compared to what?' with nothing. Add the peer comparison: "
            "`tables/multiples-strip` (six rows in a long, three in a short) "
            "carries it, one row per metric, with the subject's position on "
            "the peer range. `Peers!I` and `Peers!J` are the two numbers each "
            "row's `marker-N` takes."),
        excerpt=_first_hit(narration, _REVERSE_DCF_WORDS)[:140],
    )]


def _first_hit(text: str, words: tuple[str, ...]) -> str:
    """The sentence a phrase landed in, so the finding points somewhere."""
    low = text.lower()
    best = min((low.find(w) for w in words if low.find(w) >= 0), default=-1)
    if best < 0:
        return ""
    start = max(low.rfind(".", 0, best) + 1, 0)
    end = low.find(".", best)
    return text[start: end if end > 0 else len(text)].strip()


# --------------------------------------------------------------------------
# Type budgets, at the gate rather than at the end of the render.
# --------------------------------------------------------------------------


def budget_check(script, settings: Settings) -> list[Finding]:
    """Copy that does not fit the box the kit drew for it. BLOCKING.

    THE BUDGET IS CHECKED HERE BECAUSE HERE IS WHERE IT IS CHEAP. The SHORT
    already refused an over-budget fill at render time, and for a 50-second
    video that is a tolerable place to find out. A LONG is forty minutes: the
    same failure arriving as a `RenderError` after the encode costs the whole
    build to learn that one label is six characters too long. It is a property
    of the SCRIPT, it is knowable before a frame is drawn, and a script gate is
    where the writer can still do something about it.

    So this is the same check `compose.check_budgets` makes, moved to where the
    fact-check gate runs and reported as a named finding against the slot. The
    render-time check stays as a backstop rather than as the only line: a SHORT
    fills some slots from its template and its resolvers rather than from the
    script, and those values never pass through here.

    `maxChars` is read off the BOX the copy lands in, with the role's narrowest
    box as the floor behind it — one role is set in boxes of very different
    widths on the same plate, and the role's number alone is wrong in one of
    them by construction.
    """
    from pipeline.models import TagType
    from pipeline.plate_frames import budget
    from pipeline.plates import PlateError, load_plates

    findings: list[Finding] = []
    try:
        reg = load_plates(settings.assets_dir)
    except PlateError:
        return findings

    # A short's [PLATE] tags are parsed and discarded (see `kit_doctor`), so
    # a long value in one fits no box because it is in none.
    events = list(getattr(script, "events", None) or [])
    for event in events:
        if getattr(event, "type", None) is not TagType.PLATE:
            continue
        plate = reg.get(str(getattr(event, "payload", "") or ""))
        if plate is None:
            continue                    # an unresolved plate is the kit gate's
        for name, value in (getattr(event, "values", None) or {}).items():
            slot = plate.slot(name)
            if slot is None:
                continue                # an undeclared slot is the kit gate's
            limit = budget(plate, slot, str(value)).get("maxChars")
            text = str(value)
            if not limit or len(text) <= int(limit):
                continue
            findings.append(Finding(
                gate="budget",
                severity="block",
                message=(
                    f"{plate.key} {name}: {len(text)} characters against the "
                    f"{limit} that box holds — the plate reserved that width "
                    f"and the line collides with the rule beside it. Cut it to "
                    f"{limit} or move it to a slot drawn wider."),
                excerpt=text[:140]))
    return findings


def confession_lint(script, settings: Settings, *,
                    skip: tuple[str, str] | None = None) -> list[Finding]:
    """The same admission, told twice.

    "A repetition rule someone has to remember will fail; a ledger makes it
    impossible." The ledger is the mechanism and this is the reading of it: a
    warning, naming the video the story was already told in, so a writer who
    genuinely means to return to an old loss can — they just have to mean it.

    Nothing here asks for a confession. Roughly one video in three carries one
    and the writing prompt is where that gets said; a gate that nagged for one
    every time would rebuild the rule the bible deleted.
    """
    said = getattr(script, "confession", None)
    if said is None or not getattr(said, "text", ""):
        return []
    from pipeline.standing import ConfessionLedger

    try:
        prior = ConfessionLedger(settings).repeats(said.text, skip=skip)
    except Exception as exc:                       # noqa: BLE001 — never fatal
        log.debug("confession ledger unreadable (%s)", exc)
        return []
    out: list[Finding] = []
    for c in prior:
        where = c.ticker or "a previous video"
        when = f" on {c.workdate}" if c.workdate else ""
        out.append(Finding(
            gate="confession", severity="warn",
            message=(f"this admission was already made about {where}{when} — "
                     f"the ledger exists so the same story is not told twice"),
            excerpt=c.text[:140]))
    return out


# --------------------------------------------------------------------------
# Data freshness.
# --------------------------------------------------------------------------


def check_freshness(as_of: str, settings: Settings,
                    today: date | None = None,
                    workspace: Path | None = None) -> list[Finding]:
    """A render built on a stale snapshot states old numbers as current.

    The workbook's own as-of date is the authority. The numbers are refreshed
    outside the bot now and uploaded, so the sheet is the only thing that
    knows when they were actually pulled — and it is the same date the
    operator can see in the file they exported.

    Deliberately NOT the file's mtime: re-saving a workbook, or copying it
    between machines, resets that without touching a single number, which is
    exactly the case this gate exists to catch.

    A date this cannot READ is a block too, at the same severity as a stale
    one (B5). It used to be a silent skip, which is the wrong shape: an
    unreadable date is not evidence of freshness, it is the absence of
    evidence, and the gate exists precisely to refuse to proceed without it.
    """
    parsed = _parse_as_of(as_of)

    if parsed is not None:
        age = ((today or date.today()) - parsed).days
        if age < -1:
            # A date in the future is a typo, and it would otherwise pass
            # this gate for as long as it stays in the future. A day of
            # slack covers a workbook stamped in a timezone ahead of this box.
            return [Finding(
                gate="freshness", severity="warn",
                message=(f"the data export's as-of date {as_of} is "
                         f"{-age} days in the future — check the sheet; "
                         f"freshness cannot be judged from it"))]
        if age > settings.data_max_age_days:
            severity = "block" if settings.data_stale_blocks else "warn"
            return [Finding(
                gate="freshness", severity=severity,
                message=(f"the data export is {age} days old (as of {as_of}; "
                         f"limit {settings.data_max_age_days}) — refresh it "
                         f"and upload dennis_data.xlsx again"))]
        return []

    severity = "block" if settings.data_stale_blocks else "warn"
    if not as_of:
        return [Finding(
            gate="freshness", severity=severity,
            message=("the data export carries no as-of date — there is "
                     "nothing here that says when these numbers were "
                     "pulled, so they cannot be checked for staleness"))]
    return [Finding(
        gate="freshness", severity=severity,
        message=(f"could not read the as-of date {as_of!r} — an unreadable "
                 f"date is not evidence of freshness. Write it as "
                 f"YYYY-MM-DD in the sheet and re-upload"))]


# Written as a US date first. The workbook is exported on a US-locale
# machine against US market data, so `09/03/2026` is 9 March there — read
# day-first it silently became 3 September, six months adrift and inside
# any staleness limit either way (B5).
#
# The formats after it are the ones the sheet actually produces when the
# operator's locale, or Excel's own formatting, gets involved; every one of
# them used to return None and skip the check entirely.
_AS_OF_FORMATS = (
    "%Y-%m-%d",      # ISO — what the template asks for
    "%m/%d/%Y",      # US, before day-first: see above
    "%d/%m/%Y",      # day-first, for a sheet saved under a European locale
    "%Y/%m/%d",
    "%d-%b-%Y",      # 3-Sep-2026
    "%d %b %Y",      # 3 Sep 2026
    "%b %d, %Y",     # Sep 3, 2026
    "%B %d, %Y",     # September 3, 2026
    "%d-%B-%Y",
    "%m/%d/%y",
    "%d.%m.%Y",
)

# Excel stores a date as days since 1899-12-30 (the 1900 system, with its
# deliberate leap-year bug already accounted for by that epoch). A cell
# read as a raw serial reaches here as "46265" or "46265.0".
_EXCEL_EPOCH = date(1899, 12, 30)


def _parse_as_of(as_of: str) -> date | None:
    """The sheet's as-of date, or None when it is absent or unreadable."""
    if not as_of:
        return None
    raw = str(as_of).strip()
    if not raw:
        return None

    # A full datetime ("2026-09-03 00:00:00") — take the date half.
    head = raw.split("T")[0].split(" ")[0] if ("T" in raw or " " in raw[:11]) else raw
    for candidate in (raw, head):
        for fmt in _AS_OF_FORMATS:
            try:
                return datetime.strptime(candidate[:len(candidate)], fmt).date()
            except ValueError:
                continue

    # A raw Excel serial number.
    try:
        serial = float(raw)
    except ValueError:
        return None
    # Below ~1000 is not a plausible date (that is 1902); above ~80000 is
    # past 2119. Either is a number that happens to be in the cell, not a
    # date, and guessing at it is how a wrong date passes as a right one.
    if 1000 <= serial <= 80000:
        return _EXCEL_EPOCH + timedelta(days=int(serial))
    return None


# --------------------------------------------------------------------------
# Placeholder audio.
# --------------------------------------------------------------------------


def check_audio(settings: Settings, *, final: bool = True) -> list[Finding]:
    """Every sound file the render would play that is a synthesised placeholder.

    `scripts/gen_assets.py` builds the effects out of ffmpeg oscillators — two
    `sine=` sources standing in for a cash register — which is the right thing
    for a repo that has to build and test offline, and the wrong thing to
    publish. The provenance sidecar has recorded which is which since it was
    written; what nothing did was STOP one.

    `audio_banner` wrote a single INFO line at the top of a render, on a
    pipeline whose whole design principle is that a guarantee lives in code
    rather than in the operator's memory. So it is a gate: a finding the
    validation report carries next to the other blockers, before the Approve
    button rather than after the upload.

    It BLOCKS a real final render (`MOCK_MODE=false`) and warns otherwise —
    drafts and the offline suite are supposed to run on placeholders, that is
    what they are for, and a gate that stopped them would only teach the
    operator to skip gates.
    """
    from pipeline.audio_assets import generated_audio

    placeholders = generated_audio(settings)
    if not placeholders:
        return []
    blocks = final and not settings.mock_mode
    shown = ", ".join(placeholders[:6])
    if len(placeholders) > 6:
        shown += f", …and {len(placeholders) - 6} more"
    reason = ("this render is a FINAL and MOCK_MODE is off"
              if blocks else
              ("MOCK_MODE is on" if settings.mock_mode else "this is a draft"))
    # A music file with no record is not an oscillator; it is a track nobody
    # can say the channel is allowed to play, which is worse.
    score = [p for p in placeholders if p.startswith("score/")]
    fix = "Run scripts/fetch_sfx.py before publishing"
    if score:
        fix += (f"; {len(score)} music file(s) have no record of where they "
                f"came from, so remove them or re-make them with "
                f"scripts/make_score.py")
    return [Finding(
        gate="audio", severity="block" if blocks else "warn",
        message=(f"PLACEHOLDER AUDIO — {len(placeholders)} of the sound files "
                 f"this render plays are ffmpeg oscillators, not real effects "
                 f"({shown}). {fix} ({reason})."))]


# --------------------------------------------------------------------------
# Synthetic price data.
# --------------------------------------------------------------------------


def _reaches_a_price_chart(script, format_name: str = "") -> bool:
    """Would this script put a price series on screen?

    A SHORT does when its shot template draws one: the plain short's move
    beat is a price line, filled whether or not the writer asked, and the
    `earnings` and `macro` templates draw no prices at all. With no
    `format_name` a SHORT is assumed to.

    A LONG always does. `[CHART: price]` draws one, and so does the room:
    the monitor shows the price's run for `[SCREEN: price]` and for every
    chapter with no plate of its own to show (`room_screen.PRICE`). Only
    `[CHART: price]` used to count, so a mocked price line went out on the
    monitor of a final with nothing said.
    """
    fmt = (getattr(script, "format", "") or "").lower()
    if fmt == "short" or type(script).__name__ == "ShortScript":
        if not format_name:
            return True
        from pipeline.shots import TemplateError, draws_prices, load_format

        try:
            return draws_prices(load_format(format_name))
        except TemplateError:
            return True
    return True


def check_prices(script, settings: Settings, *, final: bool = True,
                 format_name: str = "") -> list[Finding]:
    """Whether the price chart in this video is drawn from real prices.

    When Yahoo fails, `YahooPriceSource.history()` falls back to
    `synthetic_series()` — a seeded random walk. That floor is right: a dead
    feed must never abort a render. What was missing is anyone saying so. The
    `degraded` flag was set and read by nothing, anywhere, and was dropped by
    `to_json` the moment the series hit the cache, so a fabricated chart
    shipped looking exactly like a real one and no surface in the product
    could reveal it (B1).

    This blocks the same way `check_audio` does, for the same reason: a FINAL
    render outside `MOCK_MODE` is the thing that gets published. A proof or a
    draft is for looking at, and `MOCK_MODE` is synthetic by construction —
    warning there is honest, blocking there would only teach the operator to
    skip gates.
    """
    if not _reaches_a_price_chart(script, format_name):
        return []
    ticker = (getattr(script, "ticker", "") or "").strip()
    if not ticker:
        return []

    from pipeline.prices import get_price_history, long_history_days

    # Cached and never-raising by contract, so this costs a file read on the
    # path that already fetched it for the render — the long's five years or
    # the short's months, whichever this video draws.
    is_short = ((getattr(script, "format", "") or "").lower() == "short"
                or type(script).__name__ == "ShortScript")
    series = get_price_history(
        ticker, settings,
        days=None if is_short else long_history_days(settings))
    # MOCKED prices are as invented as a dead feed's floor (M12). With
    # `MOCK_MODE=false MOCK_PRICES=true` the mock source hands back a fixture
    # or a seeded walk marked as healthy, and a FINAL — the thing that ships —
    # drew it with nothing in the way.
    # Under MOCK_MODE everything is invented and the banner already says so.
    mocked = (settings.mocking_prices and not settings.mock_mode
              and getattr(series, "source", "") in ("fixture", "synthetic"))
    if not series.degraded and not mocked:
        return []
    if mocked and not series.degraded:
        return [Finding(
            gate="prices", severity="block" if final else "warn",
            message=(f"MOCKED PRICE DATA — MOCK_PRICES is on, so the {ticker} "
                     f"chart in this video is a {series.source} series, not "
                     f"market data. Turn MOCK_PRICES off for a final"
                     + ("" if final else " (fine for a draft or a proof)")
                     + "."))]

    blocks = final and not settings.mock_mode
    reason = ("this render is a FINAL and MOCK_MODE is off" if blocks else
              ("MOCK_MODE is on" if settings.mock_mode else "this is a draft"))
    return [Finding(
        gate="prices", severity="block" if blocks else "warn",
        message=(f"SYNTHETIC PRICE DATA — the {ticker} chart in this video is "
                 f"a seeded random walk, not market data: the live feed "
                 f"failed and the deterministic floor took over. Nothing on "
                 f"screen distinguishes it from a real chart. Retry once the "
                 f"feed is back, or cut the chart ({reason})."))]


# --------------------------------------------------------------------------
# Kit doctor.
# --------------------------------------------------------------------------

# Families the renderer reaches for itself. A director writes `[PLATE:
# tables/numbers-sheet-4r]`; nobody writes `[PLATE: room/desk-wide]` or `[PLATE:
# annotations/strike-out]` — the set, the host, the marks, the row band and
# the frame a photograph goes in are the renderer's, and the chapter curation
# lists them as universal for a different reason.
RENDERER_OWNED_FAMILIES = ("room", "host", "annotations", "overlays", "frames")


def reachable_plates(reg) -> dict[str, set[str]]:
    """Which plates anything can actually put on screen, and by what route.

    `room/surface` was in the kit for a delta and no template named it, so the
    one angle with no floor in shot was ingested and never cut to. That is a
    CLASS of defect rather than one plate: artwork arrives keyed and curated,
    and nothing checks that a route to the screen exists. Finding them one at
    a time, by noticing, is not a method.

    Three routes, and the difference between them matters to whoever reads
    the report:

    * ``template`` — a shot file names it, or a role it fills does, or the
      long casts from that role (`render_long.LONG_ROOM_ROLES`). This is the
      format putting it on screen with no help from a writer.
    * ``tag``      — the chapter-type curation offers it, so a director can
      write a `[PLATE]` for it. Reachable, but only if somebody chooses it.
    * ``code``     — the renderer reaches for it by name: the annotations a
      SCRIBBLE resolves to, the frame a photograph gets, the band that lights
      under a row, the pose a spoken cue casts. No template mentions these
      and none should.

    What is in none of the three is drawn artwork with no way to the screen.
    """
    from pipeline.moves import SHORT_WIPE_SUFFIX
    from pipeline.plates import CHAPTER_TYPES
    from pipeline.rasters import SCRIBBLE_MARKS
    from pipeline.shots import available_formats, load_format

    by_template: set[str] = set()
    by_tag: set[str] = set()

    def _pose(key: str) -> None:
        by_template.add(key)
        # A pose is four strips — the hold, talk, idle and blink — and the
        # pipeline plays all of them off the one it was cut to. Reaching the
        # base reaches every one.
        for suffix in ("-talk", "-idle", "-blink"):
            if f"{key}{suffix}" in reg:
                by_template.add(f"{key}{suffix}")

    def _named(name: str, aspect: str) -> None:
        from pipeline.compose import resolve_plate

        if name.startswith("room/"):
            role = name.split("/", 1)[1]
            if role in reg.room_roles:
                # EVERY HOUR AN EPISODE MAY BE DRAWN AT, asked the way
                # `room_for` asks it. An angle the kit keeps to its own light
                # is out of the role at dusk and still in it at night, so it
                # is reachable as long as some hour in the rotation takes it.
                # The library is the base hour's: a drawing is reachable or
                # not, and its other hours go wherever the episode does.
                for hour in (reg.hour_rotation or ("",)):
                    for a in ("16x9", "9x16"):
                        for key in reg.angles_for(role, a, hour):
                            # And its seasonal twin, which December shoots
                            # in its place (`Registry.at`).
                            by_template.update((key, *reg.twins_of(key)))
                return
        got = resolve_plate(reg, name, aspect)
        if got is not None:
            by_template.add(got.key)

    for fmt_name in available_formats():
        fmt = load_format(fmt_name)
        for shot in fmt.shots:
            # EVERY PLATE THE BEAT CAN LAND ON. A shot's alternates are
            # template routes exactly as its authored plate is — code picks
            # between them with no writer involved — and counting only the
            # authored one is what reported 55 drawn 9:16 plates as having no
            # route to a frame while the templates were reaching for them.
            for variant in shot.variants:
                _named(variant.plate, fmt.aspect)
            for src in (shot.bind or {}).values():
                src = str(src).lstrip("?")
                if src.startswith("plate."):
                    _named(src.split(".", 1)[1], fmt.aspect)
            if shot.host:
                role = shot.host.pose
                if role in reg:
                    _pose(role)
                for key in reg.host_roles.get(role, ()):
                    if key in reg:
                        _pose(key)

    # THE LONG HAS NO SHOT FILE. It casts its rooms and his standing poses by
    # role in code, so they are credited from the roles it declares. Before
    # its chapter-template engine was retired they were credited through that
    # engine's shot file, which no default render ever used; reading the
    # renderer that does draw them is the honest route.
    from pipeline.render_long import (LONG_HOST_ROLES, LONG_ROOM_ROLES,
                                      opener_role)
    for role in (opener_role(reg), *LONG_ROOM_ROLES):
        _named(f"room/{role}", "16x9")
    for role in LONG_HOST_ROLES:
        for key in reg.host_roles.get(role, ()):
            if key in reg:
                _pose(key)

    for ctype in CHAPTER_TYPES:
        by_tag |= set(reg.plates_for_chapter(ctype))

    # The three are counted INDEPENDENTLY. Computing `code` only for what the
    # other two missed made it read zero and hid that the annotations and the
    # media frames have no other route: a reader needs to know which of the
    # three reaches a plate, not which one got there first.
    by_code: set[str] = set()
    # THE RENDERER'S OWN SOURCE, beside this file. `Path("pipeline")` was the
    # working directory's: started anywhere but the repo, the scan read
    # nothing and every plate the code reaches by name was reachable by none.
    source = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in sorted(Path(__file__).resolve().parent.glob("*.py")))
    literals = _QuotedPrefixes(source)
    # Every plate a slot names, collected once. Asked per plate, it walked
    # every slot of the library for each of them: ten million steps and most
    # of the twelve seconds `/kit doctor` took.
    overlaid = {slot.overlay for other in reg.assets.values()
                for slot in other.slots.values() if slot.overlay}
    for key, _stroke in SCRIBBLE_MARKS.values():
        if key in reg:
            by_code.add(key)
    for key in reg.keys():
        # Anchored on the OPENING quote, so `f"frames/capture-frame-{aspect}"`
        # counts and a key named in a comment does not.
        stem = key.rsplit("-16x9", 1)[0].rsplit("-9x16", 1)[0]
        if any(literals.opens(name) for name in {key, stem}):
            by_code.add(key)
        # AN OVERLAY FETCHED BY ITS MOVE'S NAME. The wipes are asked for as
        # `"wipe-sweep"` and prefixed where they are looked up
        # (`moves.wipe_plate`, `bumper.wipe_frames`), with the four-frame
        # `-short` cut taken on a vertical frame, so the scan above never
        # sees `overlays/wipe-sweep` and called all nine wipes stranded.
        if key.startswith("overlays/"):
            move = stem.split("/", 1)[1].removesuffix(SHORT_WIPE_SUFFIX)
            if any(f"{q}{move}{q}" in source for q in ('"', "'")):
                by_code.add(key)
        # A plate another plate's SLOT names. `overlays/row-band` is reached
        # by neither a template nor a source literal: a sheet's row slot
        # declares it as its `overlay`, and the renderer follows that.
        if key in overlaid:
            by_code.add(key)

    # A POSE THE WORDS CAST. `host.cast_pose` stands him in one of these, in
    # either lane, when what he says gives its cue (a count, a "but", the
    # filing) and the room is one it was drawn for. No role and no template
    # names them, so they are the renderer's, reachable wherever a room they
    # fit is; counting them as gaps put six drawn poses on the stranded list.
    from pipeline.host import castable
    rooms = {k.rsplit("-16x9", 1)[0].rsplit("-9x16", 1)[0]
             for k in reg.base_keys(by_template) if k.startswith("room/")}
    for key, spec in castable(reg).items():
        if key in reg and rooms & set(spec.get("fits") or ()):
            by_code.update(k for k in (key, f"{key}-talk", f"{key}-idle",
                                       f"{key}-blink") if k in reg)

    # A `[PLATE]` TAG CANNOT NAME THE SET OR THE MAN STANDING IN IT. The
    # chapter curation lists `room/`, `host/`, `annotations/`, `overlays/` and
    # `frames/` as universal because every chapter has a set, a host, marks and
    # a way to hold a photograph — but a director does not write a [PLATE] for
    # any of them, the renderer does. Counting them as tag-reachable is what
    # made this report say every plate had a route when a room angle no
    # template named demonstrably did not.
    by_tag -= {k for k in by_tag
               if k.split("/", 1)[0] in RENDERER_OWNED_FAMILIES}

    # A [SCENE] DOES NAME THEM, on the long. Its writer picks the room angle
    # he is shot in and the pose he stands in, off the menu the prompt prints
    # from `pipeline.scenes`, so every angle a long can be shot in (with the
    # twin December shoots in its place) and every pose (with the strips it is
    # played through) is a tag route: reachable when somebody chooses it.
    from pipeline.scenes import SCENE_ASPECT, scene_poses, scene_rooms
    for stem in scene_rooms(reg):
        key = reg.aspect_key(stem, SCENE_ASPECT)
        if key:
            by_tag.update((key, *reg.twins_of(key)))
    for key in scene_poses(reg):
        by_tag.update(k for k in (key, f"{key}-talk", f"{key}-idle",
                                  f"{key}-blink") if k in reg)
    return {"template": by_template, "tag": by_tag, "code": by_code}


class _QuotedPrefixes:
    """Does `"name` or `'name` appear in `source`? Asked of every plate.

    Each key used to be searched for as a substring of all of `pipeline/`
    (three megabytes, four searches a plate). The text after every opening
    quote is taken once instead, as far as a plate key's own characters run,
    and sorted: a name follows some quote exactly when one of those runs
    starts with it, and in sorted order that run is the first one not below
    the name.
    """

    _KEY = r"A-Za-z0-9/_.-"

    def __init__(self, source: str):
        self.source = source
        self.runs = sorted(set(re.findall(rf"(?<=[\"'])[{self._KEY}]+", source)))

    def opens(self, name: str) -> bool:
        if not re.fullmatch(rf"[{self._KEY}]+", name):
            return any(f"{q}{name}" in self.source for q in ('"', "'"))
        import bisect

        i = bisect.bisect_left(self.runs, name)
        return i < len(self.runs) and self.runs[i].startswith(name)


def kit_doctor(script, settings: Settings, *,
               library: bool = True) -> tuple[list[Finding], dict]:
    """What the kit could not answer, and what it is never asked for.

    `library=False` asks only about this script (question 1 and 3). The
    library-wide audit reads every template and renderer, about twelve
    seconds, and its findings are the same for every video: inside each
    script's gates it put a dozen standing "[kit] … can put it on screen"
    lines on every approval screen, at intake and on every Approve tap.
    `/kit doctor` still asks the whole of it.

    Three questions, and the gap list is the input to the next design batch:

    1. **Unresolved plate names** — a `[PLATE]` the director wrote that does not
       resolve. Every one is a beat that would draw an empty frame.
    2. **Plates never reached** across recent renders. Not "unused this video" —
       one script touching six plates says nothing, six weeks of them says
       plenty.
    3. **Slots a script left unfilled.** A plate with an empty box renders as a
       blank area, and an empty cell in this library means NO DATA, so this
       reports rather than blocks — but a plate filling none of its slots is a
       bordered rectangle nobody meant to ship.
    """
    from pipeline.models import TagType
    from pipeline.plate_tags import check_bound
    from pipeline.plates import PlateError, load_plates
    from pipeline.reach import plates_by_render

    findings: list[Finding] = []
    try:
        reg = load_plates(settings.assets_dir)
    except PlateError as exc:
        return [Finding(gate="kit", severity="block", message=str(exc))], {
            "used": [], "unresolved_keys": [], "never_used": [],
            "never_used_count": 0, "unfilled": [], "kit_size": 0,
        }

    used: set[str] = set()
    unresolved: list[str] = []
    unfilled: list[str] = []

    events = list(getattr(script, "events", [])
                  or getattr(script, "inline_events", []))
    # The format decides the aspect. `ShortScript` declares `inline_events` and
    # `LongScript` declares `events` — neither declares both — and nothing else
    # in either model names the cut, so this reads which field the model HAS
    # rather than whether it happens to be populated.
    aspect = "9x16" if (hasattr(script, "inline_events")
                        and not hasattr(script, "events")) else "16x9"
    # A SHORT DRAWS NO INLINE TAG: its frames come from its shot template
    # (`parser_short.SHORT_IGNORED_TAG_TYPES`), so a [PLATE] in one is parsed
    # and discarded, and its key, slots and rows are nobody's problem. Checked
    # anyway, a wrong key blocked the approval of a short it changed nothing
    # in (scan, 24 Oct 2026).
    if aspect == "9x16":
        events = []
    for e in events:
        if e.type is not TagType.PLATE:
            continue
        # A SHORT is 9:16 and a LONG is 16:9, and the gate is the last place
        # that can say so before a render: `structure/multiple-bridge` ships
        # 16:9 only, so a portrait cut reaching for it has nothing to fall back
        # to and must fail here rather than draw an empty frame.
        fill = check_bound(reg, e.payload, e.values, aspect=aspect)
        if not fill.ok:
            unresolved.append(f"[PLATE: {fill.name}]")
            for problem in fill.problems:
                findings.append(Finding(gate="kit", severity="block",
                                        message=problem))
            continue
        used.add(fill.key)
        for w in fill.warnings:
            unfilled.append(w)
            findings.append(Finding(gate="kit", severity="warn", message=w))

    # What the renders on disk put on screen, off their manifests.
    rendered = plates_by_render(settings)
    # By the drawing: a render at dusk reached `cards/definition-dusk-16x9`,
    # which is `cards/definition-16x9` drawn at another hour and not a
    # different plate.
    ever_used = reg.base_keys(used.union(*rendered))
    never_used = [k for k in reg.keys() if k not in ever_used]
    renders_seen = len(rendered)

    # WHAT NOTHING CAN REACH, which is a different question from what nothing
    # HAS reached: an empty ledger makes the list above the whole library,
    # and this one is true on a fresh checkout with no renders behind it.
    routes = (reachable_plates(reg) if library
              else {"template": set(), "tag": set(), "code": set()})
    reached = routes["template"] | routes["tag"] | routes["code"]
    unreachable = (sorted(k for k in reg.keys() if k not in reached)
                   if library else [])
    no_template = (sorted(k for k in reg.keys() if k not in routes["template"])
                   if library else [])
    for key in unreachable:
        findings.append(Finding(
            gate="kit", severity="warn",
            message=f"{key} is drawn and no template, chapter type or "
                    f"renderer can put it on screen"))
    # AN HOUR IS REACHABLE OR NOT AS A WHOLE. The kit draws every plate at
    # every hour it lights, and an hour no episode is drawn at is a full copy
    # of the library with no way to the screen — one line, not two hundred.
    for hour in (sorted(set(reg.hour_suffixes) - set(reg.hour_rotation))
                 if library else []):
        findings.append(Finding(
            gate="kit", severity="warn",
            message=f"the kit draws every plate at {hour} and no episode is "
                    f"drawn at it — `hours.episodes` in roles.json leaves "
                    f"it out"))

    return findings, {
        "used": sorted(used),
        "unresolved_keys": unresolved,
        "never_used": sorted(never_used),
        "never_used_count": len(never_used),
        "unfilled": unfilled,
        "kit_size": len(reg),
        "outfit": reg.outfit,
        "renders_seen": renders_seen,
        "unreachable": unreachable,
        "no_template": no_template,
        "reached_by_template": sorted(routes["template"]),
        "tag_only": sorted(routes["tag"] - routes["template"]),
        "code_only": sorted(routes["code"] - routes["template"] - routes["tag"]),
    }


def kit_doctor_text(settings: Settings, script=None) -> str:
    """The `/kit doctor` report, as text.

    Callable with no script — the library half (never reached) does not need
    one, and that is the half an operator actually goes looking for. THE GAP
    LIST IS THE INPUT TO THE NEXT DESIGN BATCH: what was asked for and missing,
    and what has been drawn and never used.
    """
    from pipeline.plates import PlateError, load_plates

    try:
        reg = load_plates(settings.assets_dir)
    except PlateError as exc:
        return f"KIT DOCTOR — the kit is not ingested.\n  {exc}"

    findings, stats = kit_doctor(script or _EmptyScript(), settings)

    lines = [f"KIT DOCTOR — {stats['kit_size']} plates, "
             f"outfit {stats.get('outfit') or '?'}"]

    unresolved = stats["unresolved_keys"]
    lines.append("")
    lines.append(f"Unresolved plate names ({len(unresolved)}):")
    lines += [f"  {k}" for k in unresolved[:20]] or ["  none"]

    unfilled = stats.get("unfilled") or []
    lines.append("")
    lines.append(f"Slots a script left unfilled ({len(unfilled)}):")
    lines += [f"  {u}" for u in unfilled[:20]] or ["  none"]

    # WHAT NOTHING CAN REACH — true on a fresh checkout, unlike the ledger
    # below. A room angle once sat in the kit for a delta with no template
    # naming its role: not an error, not a warning, just an angle that never
    # appeared. This is that class of defect, listed.
    no_template = stats.get("no_template") or []
    lines.append("")
    lines.append(f"No shot template reaches ({len(no_template)} of "
                 f"{stats['kit_size']}):")
    tag_only = set(stats.get("tag_only") or [])
    code_only = set(stats.get("code_only") or [])
    unreachable = set(stats.get("unreachable") or [])
    for key in no_template:
        if key in unreachable:
            note = "NOTHING REACHES IT"
        elif key in tag_only:
            note = "a director can write a [PLATE] for it"
        elif key in code_only:
            note = "the renderer reaches it"
        else:
            note = "reachable"
        lines.append(f"  {key} — {note}")
    if not no_template:
        lines.append("  none")
    lines.append("")
    lines.append("  A plate only a TAG can reach is on the writer to choose, "
                 "and one nothing reaches is artwork with no way to the "
                 "screen. Both are input to the next batch: the first says "
                 "the formats do not use what was drawn, the second says it "
                 "cannot be used at all.")

    never = stats["never_used"]
    lines.append("")
    seen = stats.get("renders_seen", 0)
    lines.append(f"Never reached in a recent render ({len(never)} of "
                 f"{stats['kit_size']}):")
    if not seen:
        lines.append("  (no render on disk recorded its plates yet, so this "
                     "list is the whole library rather than a gap)")
    if never:
        by_family: dict[str, int] = {}
        for key in never:
            plate = reg.get(key)
            if plate is not None:
                by_family[plate.family] = by_family.get(plate.family, 0) + 1
        for family, n in sorted(by_family.items(), key=lambda kv: -kv[1]):
            total = len(reg.family(family)) or n
            lines.append(f"  {family}: {n} of {total}")
        lines.append("")
        lines.append("  A family that is never reached is either artwork the "
                     "writing prompt does not offer, or artwork the format "
                     "does not need. Both are worth knowing before the next "
                     "batch is commissioned.")
    else:
        lines.append("  none")

    problems = reg.verify()
    if problems:
        lines.append("")
        lines.append(f"Files the registry names and disk does not have "
                     f"({len(problems)}):")
        lines += [f"  {p}" for p in problems[:10]]

    return "\n".join(lines)


class _EmptyScript:
    """A script-shaped nothing, so the doctor runs without one."""

    events: list = []
    inline_events: list = []


# --------------------------------------------------------------------------
# Skeptic — LLM, notes only.
# --------------------------------------------------------------------------

_SKEPTIC_SYSTEM = (
    "You are a hostile but fair institutional investor reading a retail "
    "video script. Name the weakest claims and the strongest counterarguments. "
    "Be specific and terse. Never rewrite the script, never suggest wording, "
    "never comment on style or humour — only on whether the argument holds."
)


def skeptic_notes(narration: str, settings: Settings,
                  max_chars: int = 12000) -> tuple[list[Finding], str]:
    """A separate read of the finished script as a hostile investor.

    Returns `(findings, skip_reason)`. The second half is what makes "clean"
    distinguishable from "did not check" (N2): this returned `[]` for both,
    and a gate whose silence means two opposite things is not a gate.

    Advisory by construction: the result is appended to the validation report
    as notes. It never rewrites and never blocks.
    """
    from pipeline.llm import chat_result

    body = narration[:max_chars]
    out = chat_result(
        f"Script:\n\n{body}\n\n"
        "List at most 5 items. One line each, format: `weakness — counterargument`.",
        settings, system=_SKEPTIC_SYSTEM, purpose="skeptic",
    )
    if not out:
        # The REASON, so `run_gates` can say `skipped:no_daemon` rather than
        # letting a dead daemon read as a clean script (N2).
        return [], out.reason
    notes = [ln.strip(" -•\t") for ln in out.text.splitlines() if ln.strip()]
    return [Finding(gate="skeptic", severity="warn", message=n)
            for n in notes[:5]], ""


# --------------------------------------------------------------------------
# The whole battery.
# --------------------------------------------------------------------------


def _beats_marked(script, text: str) -> str:
    """A SHORT's narration with its `[BEAT]` marks back in, for the
    fact-check's sentence split. The parser lifts them out of `audio_script`
    and keeps their offsets; without them two beats with no full stop between
    them read as one sentence (`_sentences`)."""
    marks = getattr(script, "beat_marks", None) or []
    if not marks or text != getattr(script, "audio_script", None):
        return text
    out = text
    for at in sorted({m.char_offset for m in marks}, reverse=True):
        if 0 < at < len(out):
            out = f"{out[:at]} [BEAT] {out[at:]}"
    return out


# WHEN THE CHECK IS WRONG AND HE KNOWS IT. A fact-check block he has read and
# called right is kept in the video's folder by its key, and comes back as a
# note on every later run of the checks — until the sentence or the workbook
# changes, which changes the key, and the check gets its say again.
TRUSTED_FILE = "fact_check_trusted.json"


def finding_key(rendered: str) -> str:
    """A finding's key, from its rendered text as the report stores it."""
    import hashlib

    return hashlib.sha1(rendered.strip().encode("utf-8")).hexdigest()[:10]


def trusted_findings(workspace: Path | None) -> set[str]:
    if workspace is None:
        return set()
    try:
        import json

        got = json.loads((Path(workspace) / TRUSTED_FILE).read_text(encoding="utf-8"))
        return {str(k) for k in got} if isinstance(got, list) else set()
    except (OSError, ValueError):
        return set()


def trust_finding(workspace: Path, key: str) -> None:
    import json

    keys = sorted(trusted_findings(workspace) | {key})
    (Path(workspace) / TRUSTED_FILE).write_text(json.dumps(keys), encoding="utf-8")


def _let_through(findings: list[Finding], trusted: set[str]) -> list[Finding]:
    if not trusted:
        return findings
    return [Finding(f.gate, "note", f"you let this through: {f.message}",
                    f.line, f.excerpt)
            if f.severity == "block" and finding_key(f.render()) in trusted
            else f for f in findings]


def run_gates(script, settings: Settings, *, data=None, as_of: str = "",
              skeptic: bool = True, workspace: Path | None = None,
              final: bool = True, format_name: str = "") -> GateReport:
    """Every gate, in cost order. Silence means proceed.

    `final` says whether what follows approval is a publishable render. It
    defaults to true because this battery runs on the intake path, and intake
    leads to the Approve button — the only thing on the other side of it is a
    final. A draft never comes through here (it skips approval entirely, which
    is the point of a draft), and the flag is what keeps the audio gate from
    blocking one if it ever does.

    `format_name` is the shot template a SHORT renders through, which
    decides whether it draws prices at all.
    """
    narration = getattr(script, "narration", None) or getattr(script, "audio_script", "")
    report = GateReport()
    # Every gate records that it RAN, at the worst severity it reported (N2).
    # A gate that ran and found nothing used to look exactly like one that
    # never ran, and for a record whose whole purpose is honesty about what
    # happened, those cannot render the same way.
    unread: list = []
    trusted = trusted_findings(workspace)
    report.findings += report.record("fact-check", _let_through(fact_check(
        _beats_marked(script, narration), data,
        ticker=str(getattr(script, "ticker", "") or ""),
        unchecked=unread), trusted))
    # Listed, so "the fact-check passed it" never stands for "it was read".
    report.findings += [Finding("fact-check", "note", f"not checked — {why}",
                                line=n, excerpt=text[:90])
                        for n, text, why in unread]
    report.findings += report.record("on-screen", _let_through(
        onscreen_fact_check(script, data), trusted))
    report.findings += report.record("voice", voice_lint(delivery_text(script)))
    # Bible v3's checks (10-18): machine phrasing (S1) and the swearing
    # limits; v4's (30 Oct): the joke floor and the prompt said aloud. All
    # warn; none can stop a render.
    from pipeline.writing_checks import (chapter_title_swears, joke_floor_lint,
                                         phrasing_lint, prompt_words_lint,
                                         swear_lint)

    lane = "long" if hasattr(script, "chapter_list") else "short"
    report.findings += report.record(
        "phrasing", phrasing_lint(delivery_text(script), settings))
    report.findings += report.record("swearing", swear_lint(narration, lane)
                                     + chapter_title_swears(script))
    report.findings += report.record("joke-floor",
                                     joke_floor_lint(script, lane))
    report.findings += report.record("prompt-words",
                                     prompt_words_lint(script))
    # A bible example or another creator's line, said again (S2).
    from pipeline.writing_checks import copy_check

    report.findings += report.record("copy", copy_check(narration, settings))
    from pipeline.channel_memory import joke_reuse_lint

    # THIS VIDEO'S OWN ROWS. Shipping writes its jokes and confession to the
    # ledgers, so checking it again (a re-render, /check) reported its own
    # lines as "already used in EXMPL on <its own date>".
    this = ((workspace.parent.name.upper(), workspace.name)
            if workspace is not None else None)
    report.findings += report.record("jokes",
                                     joke_reuse_lint(narration, settings,
                                                     skip=this))
    from pipeline.recurring_bits import bits_lint

    report.findings += report.record("bits", bits_lint(script, settings))
    from pipeline.writing_checks import chapter_order_lint

    report.findings += report.record("chapters", chapter_order_lint(
        script, settings, workspace=workspace))
    report.findings += report.record("direction", direction_lint(
        script, peers=getattr(data, "peers", None) or ()))
    report.findings += report.record("confession",
                                     confession_lint(script, settings,
                                                     skip=this))
    report.findings += report.record("valuation",
                                     valuation_moves(script, settings))
    report.findings += report.record("budgets", budget_check(script, settings))
    # WHAT THE SITE SAYS (the stockanalysis picks, 30 Oct 2026): a quote
    # said to be management's that is not in the call, and the workbook's
    # quarters where they disagree with the site's. Both warn.
    from pipeline import site_pack

    report.findings += report.record("call-quote",
                                     site_pack.quote_findings(script, workspace))
    report.findings += report.record("site-figures",
                                     site_pack.cross_check_findings(data, workspace))
    # A MACRO short has no company workbook by design: it is anchored on
    # FRED's series and an index proxy, both fetched live. Asking it for a
    # workbook as-of date blocked every macro short under the production
    # default (`DATA_STALE_BLOCKS=true`) — the suite turns blocking off
    # globally, which is how that hid.
    if format_name == "macro" and data is None:
        report.skipped("freshness", "a macro short has no workbook")
    else:
        report.findings += report.record(
            "freshness", check_freshness(as_of, settings, workspace=workspace))
    report.findings += report.record("audio",
                                     check_audio(settings, final=final))
    report.findings += report.record(
        "prices", check_prices(script, settings, final=final,
                               format_name=format_name))
    kit_findings, kit_stats = kit_doctor(script, settings, library=False)
    report.findings += report.record("kit", kit_findings)
    # THE FOUR THAT ARE ABOUT WATCHABILITY, not truth (01, 30, 31, 35).
    # Every gate above asks whether this video is right or affordable. These
    # ask whether it is another copy of the last one, whether it has a shape,
    # and whether it opens on what its title promised — which is the axis the
    # platform's own originality rule is written on, and the axis retention
    # measures. All warn; the sameness gate is the one that can block, and
    # only when a script is effectively a previous one re-tickered.
    #
    # Imported here rather than at module scope: these read the corpus and
    # the upload package, and `gates` is imported by nearly everything.
    from pipeline.corpus import sameness_check
    from pipeline.pacing import check_title_package, loop_check, pacing_report

    report.findings += report.record("sameness", sameness_check(
        script, settings, workspace=workspace))
    report.findings += report.record("pacing", pacing_report(script))
    report.findings += report.record("loops", loop_check(script))
    report.findings += report.record("title", check_title_package(script, settings))
    if skeptic:
        notes, why = skeptic_notes(narration, settings)
        report.findings += report.record("skeptic", notes)
        if why:
            report.skipped("skeptic", why)
    else:
        report.skipped("skeptic", "not requested")
    if data is None:
        # The two gates that compare against the workbook cannot have run.
        report.skipped("fact-check", "no company data")
        report.skipped("on-screen", "no company data")
    log.info("gates: %d findings (%d blocking); kit uses %d assets; %s",
             len(report.findings), len(report.blocking),
             len(kit_stats["used"]), report.ran_line())
    return report
