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
from datetime import date, datetime, time as dt_time, timezone
from pathlib import Path

from config import Settings

log = logging.getLogger(__name__)


@dataclass
class Finding:
    """One thing worth the operator's attention."""

    gate: str
    severity: str          # "warn" | "block"
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

    @property
    def blocking(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "block"]

    @property
    def ok(self) -> bool:
        return not self.findings

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
_NUMBER_WORDS = set(_UNITS) | set(_TENS) | set(_SCALES) | {"and", "point", "a"}

_SUFFIX = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000, "bn": 1_000_000_000,
           "t": 1_000_000_000_000}


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
        if t in _UNITS:
            value = _UNITS[t]
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


_DIGIT_RE = re.compile(
    r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)\s*(percent|%|bn|[kmbt])?(?![\w])",
    re.IGNORECASE,
)


@dataclass
class SpokenNumber:
    value: float
    text: str
    is_percent: bool = False


def extract_numbers(sentence: str) -> list[SpokenNumber]:
    """Every number a sentence states, digits or words."""
    out: list[SpokenNumber] = []
    low = sentence.lower()

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
        out.append(SpokenNumber(value, m.group(0).strip(), pct))

    tokens = re.findall(r"[a-z]+|%", low)
    i = 0
    while i < len(tokens):
        if tokens[i] not in _NUMBER_WORDS or tokens[i] in ("and", "a", "point"):
            i += 1
            continue
        j = i
        while j < len(tokens) and tokens[j] in _NUMBER_WORDS:
            j += 1
        run = tokens[i:j]
        value = _words_to_number(run)
        if value is not None:
            pct = j < len(tokens) and tokens[j] in ("percent", "%")
            out.append(SpokenNumber(value, " ".join(run), pct))
        i = max(j, i + 1)
    return out


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

# Spoken figures are rounded ("four hundred million" for 400.2M), so a claim
# counts as supported when it lands inside this band of any real value.
_TOLERANCE = 0.02


def _series_for(data, field_name: str) -> list[float]:
    """Every value the data holds for a metric — dashboard and history."""
    values: list[float] = []
    if data is None:
        return values

    getter = getattr(data, "history_row", None)
    if callable(getter):
        try:
            values.extend(float(v) for v in (getter(field_name) or [])
                          if isinstance(v, (int, float)))
        except Exception:  # noqa: BLE001
            pass
    else:  # a plain mapping (tests, fixtures)
        series = (data.get("history") or {}).get(field_name) \
            if hasattr(data, "get") else None
        if isinstance(series, (list, tuple)):
            values.extend(float(v) for v in series if isinstance(v, (int, float)))

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


def fact_check(narration: str, data) -> list[Finding]:
    """Re-read every numeric claim against the loaded company data.

    Only sentences that name a metric are checked, and only against that
    metric's own values — a number floating free of any metric is prose, not
    a claim, and flagging it would bury the real mismatches.
    """
    findings: list[Finding] = []
    if data is None:
        return findings

    known: dict[str, list[float]] = {
        m: _series_for(data, m) for m in _METRIC_WORDS
    }
    for lineno, line in enumerate(narration.splitlines(), 1):
        for sentence in re.split(r"(?<=[.!?])\s+", line):
            low = sentence.lower()
            for metric, words in _METRIC_WORDS.items():
                if not any(w in low for w in words):
                    continue
                series = known.get(metric) or []
                if not series:
                    continue
                for num in extract_numbers(sentence):
                    if num.is_percent or num.value < 1000:
                        continue  # rates and small counts are derived, not raw
                    if not _matches(num.value, series):
                        findings.append(Finding(
                            gate="fact-check", severity="warn", line=lineno,
                            message=(f"“{num.text}” is stated for {metric} but "
                                     f"the data has "
                                     f"{', '.join(f'{v:,.0f}' for v in series[:6])}"),
                            excerpt=sentence.strip()[:140],
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
_VENDORS = ("refinitiv", "lseg", "eikon", "bloomberg terminal", "capital iq",
            "factset")


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

# A TURN, for the twenty-second rule. Not "anything interesting happened" —
# the four things the bible names: an aside, a number anchored, a mode shift,
# a question. A bare figure is not one of them: this register states figures
# continuously, so counting them as turns would mean the check never fires,
# which is the same as not having it. What makes an anchored number a turn is
# the anchor, and the anchor is addressed to somebody.
_TURN = re.compile(r"[?]|\[(?:BEAT|SIGH|DRY|FLAT)\]|"
                   r"\b(?:i|i'm|i've|i'd|i'll|me|my|you|you're|you've|you'd|"
                   r"you'll|your|we|we're|us|our)\b", re.I)

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
        for word in line.split():
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
    marks = {"BEAT", "SIGH", "DRY", "FLAT"}
    events = [e for e in (getattr(script, "events", None) or [])
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
    """Flags what the bible forbids. Never a joke quota — density is the
    writer's call and a linter that policed it would flatten the voice.

    Two of the flags are structural rather than lexical, and they are the two
    the bible asks for by name: a construction used twice in one script, and a
    stretch of explanation with no turn in it. Both are warnings. The first
    repeat of a good construction is not a defect that should stop a render —
    it is the thing the writer should go and fix, and saying which line it was
    is the whole use of saying it at all.
    """
    findings: list[Finding] = []

    # A construction used a second time. The FIRST is the licence; the second
    # is the finding, and it carries both line numbers so the writer can see
    # what it is repeating rather than hunting for it.
    for name, described, pattern in _CONSTRUCTIONS:
        hits = [(n, ln) for n, ln in enumerate(narration.splitlines(), 1)
                if pattern.search(ln)]
        for lineno, line in hits[1:]:
            findings.append(Finding(
                gate="voice", severity="warn", line=lineno,
                message=(f"{described} again — one {name} per script. "
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
    `tables/numbers-sheet` has a `unit` slot reading "$M", and
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
    if cleaned[-1:].lower() in "kmbt":
        mult = {"k": 1e3, "m": 1e6, "b": 1e9, "t": 1e12}[cleaned[-1].lower()]
        cleaned = cleaned[:-1]
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
    known = {m: _series_for(data, m) for m in _METRIC_WORDS}

    for event in getattr(script, "events", None) or []:
        values = dict(getattr(event, "values", None) or {})
        if not values:
            continue
        declared = _declared_unit(values)
        scale = declared if declared is not None else 1.0
        for label, figures in _row_figures(values):
            low = str(label).lower()
            metric = next((m for m, words in _METRIC_WORDS.items()
                           if any(w in low for w in words)), "")
            series = known.get(metric) or []
            if not metric or not series:
                continue

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


def confession_lint(script, settings: Settings) -> list[Finding]:
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
        prior = ConfessionLedger(settings).repeats(said.text)
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

    The COM refresh stamp is still honoured when one is present, but only as a
    fallback for a workspace populated that way, and only when the sheet
    carries no date of its own. On the Linux target nothing writes it.
    """
    parsed = _parse_as_of(as_of)

    if parsed is not None:
        age = ((today or date.today()) - parsed).days
        if age > settings.data_max_age_days:
            severity = "block" if settings.data_stale_blocks else "warn"
            return [Finding(
                gate="freshness", severity=severity,
                message=(f"the data export is {age} days old (as of {as_of}; "
                         f"limit {settings.data_max_age_days}) — refresh it "
                         f"and upload dennis_data.xlsx again"))]
        return []

    # No usable date on the sheet. Fall back to a recorded COM refresh if this
    # workspace has one.
    if workspace is not None:
        from pipeline.excel_refresh import refresh_age_days

        now = None
        if today is not None:
            now = datetime.combine(today, dt_time(), tzinfo=timezone.utc)
        age_days = refresh_age_days(workspace, now=now)
        if age_days is not None:
            if age_days > settings.data_max_age_days:
                severity = "block" if settings.data_stale_blocks else "warn"
                return [Finding(
                    gate="freshness", severity=severity,
                    message=(f"the data was last refreshed {age_days:.1f} days "
                             f"ago (limit {settings.data_max_age_days}) — "
                             f"refresh it and upload it again"))]
            return []

    if not as_of:
        return [Finding(gate="freshness", severity="warn",
                        message="the data export carries no as-of date")]
    return [Finding(gate="freshness", severity="warn",
                    message=f"could not read the as-of date {as_of!r}")]


def _parse_as_of(as_of: str) -> date | None:
    """The sheet's as-of date, or None when it is absent or unreadable."""
    if not as_of:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(as_of.strip()[:10], fmt).date()
        except ValueError:
            continue
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
    return [Finding(
        gate="audio", severity="block" if blocks else "warn",
        message=(f"PLACEHOLDER AUDIO — {len(placeholders)} of the sound files "
                 f"this render plays are ffmpeg oscillators, not real effects "
                 f"({shown}). Run scripts/fetch_sfx.py before publishing "
                 f"({reason})."))]


# --------------------------------------------------------------------------
# Kit doctor.
# --------------------------------------------------------------------------

# Families the renderer reaches for itself. A director writes `[PLATE:
# tables/numbers-sheet-4r]`; nobody writes `[PLATE: room/wide]` or `[PLATE:
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

    * ``template`` — a shot file names it, or a role it fills does. This is
      the format putting it on screen with no help from a writer.
    * ``tag``      — the chapter-type curation offers it, so a director can
      write a `[PLATE]` for it. Reachable, but only if somebody chooses it.
    * ``code``     — the renderer reaches for it by name: the annotations a
      SCRIBBLE resolves to, the frame a photograph gets, the band that lights
      under a row. No template mentions these and none should.

    What is in none of the three is drawn artwork with no way to the screen.
    """
    from pipeline.plates import CHAPTER_TYPES
    from pipeline.rasters import SCRIBBLE_MARKS
    from pipeline.shots import available_formats, load_format

    by_template: set[str] = set()
    by_tag: set[str] = set()

    def _pose(key: str) -> None:
        by_template.add(key)
        # A pose is three strips and, for a framing, two glances the pipeline
        # picks itself. Reaching the base reaches all of them.
        for suffix in ("-talk", "-idle", "-glance-left", "-glance-right",
                       "-glance-left-talk", "-glance-left-idle",
                       "-glance-right-talk", "-glance-right-idle"):
            if f"{key}{suffix}" in reg:
                by_template.add(f"{key}{suffix}")

    def _named(name: str, aspect: str) -> None:
        from pipeline.compose import resolve_plate

        if name.startswith("room/"):
            role = name.split("/", 1)[1]
            if role in reg.room_roles:
                for stem in reg.room_roles[role]:
                    for a in ("16x9", "9x16"):
                        key = reg.aspect_key(stem, a)
                        if key:
                            by_template.add(key)
                return
        got = resolve_plate(reg, name, aspect)
        if got is not None:
            by_template.add(got.key)

    for fmt_name in available_formats():
        fmt = load_format(fmt_name)
        for shot in fmt.shots:
            if shot.plate:
                _named(shot.plate, fmt.aspect)
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

    for ctype in CHAPTER_TYPES:
        by_tag |= set(reg.plates_for_chapter(ctype))

    # The three are counted INDEPENDENTLY. Computing `code` only for what the
    # other two missed made it read zero and hid that the annotations and the
    # media frames have no other route: a reader needs to know which of the
    # three reaches a plate, not which one got there first.
    by_code: set[str] = set()
    source = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in sorted(Path("pipeline").glob("*.py")))
    for key, _stroke in SCRIBBLE_MARKS.values():
        if key in reg:
            by_code.add(key)
    for key in reg.keys():
        # Anchored on the OPENING quote, so `f"frames/capture-frame-{aspect}"`
        # counts and a key named in a comment does not.
        stem = key.rsplit("-16x9", 1)[0].rsplit("-9x16", 1)[0]
        if any(f'{q}{name}' in source
               for q in ('"', "'") for name in ({key, stem})):
            by_code.add(key)
        # A plate another plate's SLOT names. `overlays/row-band` is reached
        # by neither a template nor a source literal: a sheet's row slot
        # declares it as its `overlay`, and the renderer follows that.
        for other in reg.assets.values():
            if any(slot.overlay == key for slot in other.slots.values()):
                by_code.add(key)
                break

    # A `[PLATE]` TAG CANNOT NAME THE SET OR THE MAN STANDING IN IT. The
    # chapter curation lists `room/`, `host/`, `annotations/`, `overlays/` and
    # `frames/` as universal because every chapter has a set, a host, marks and
    # a way to hold a photograph — but a director does not write a [PLATE] for
    # any of them, the renderer does. Counting them as tag-reachable is what
    # made this report say every plate had a route when `room/high-desk-down`
    # demonstrably did not.
    by_tag -= {k for k in by_tag
               if k.split("/", 1)[0] in RENDERER_OWNED_FAMILIES}
    return {"template": by_template, "tag": by_tag, "code": by_code}


def kit_doctor(script, settings: Settings) -> tuple[list[Finding], dict]:
    """What the kit could not answer, and what it is never asked for.

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
    from pipeline.plates import PlateError, load_plates, load_variant_ledger

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
    for e in events:
        if e.type is not TagType.PLATE:
            continue
        fill = check_bound(reg, e.payload, e.values)
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

    ledger = load_variant_ledger(settings)
    ever_used = used | ledger.all_used()
    never_used = [k for k in reg.keys() if k not in ever_used]
    renders_seen = len(ledger.recent("render"))

    # WHAT NOTHING CAN REACH, which is a different question from what nothing
    # HAS reached: an empty ledger makes the list above the whole library,
    # and this one is true on a fresh checkout with no renders behind it.
    routes = reachable_plates(reg)
    reached = routes["template"] | routes["tag"] | routes["code"]
    unreachable = sorted(k for k in reg.keys() if k not in reached)
    no_template = sorted(k for k in reg.keys() if k not in routes["template"])
    for key in unreachable:
        findings.append(Finding(
            gate="kit", severity="warn",
            message=f"{key} is drawn and no template, chapter type or "
                    f"renderer can put it on screen"))

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
    # below. `room/high-desk-down` sat in the kit for a delta with no template
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
        lines.append("  (the render ledger is empty — nothing has been "
                     "recorded yet, so this list is the whole library rather "
                     "than a gap)")
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
                  max_chars: int = 12000) -> list[Finding]:
    """A separate read of the finished script as a hostile investor.

    Advisory by construction: the result is appended to the validation report
    as notes. It never rewrites and never blocks.
    """
    from pipeline.llm import chat

    body = narration[:max_chars]
    out = chat(
        f"Script:\n\n{body}\n\n"
        "List at most 5 items. One line each, format: `weakness — counterargument`.",
        settings, system=_SKEPTIC_SYSTEM, purpose="skeptic",
    )
    if not out:
        return []
    notes = [ln.strip(" -•\t") for ln in out.splitlines() if ln.strip()]
    return [Finding(gate="skeptic", severity="warn", message=n)
            for n in notes[:5]]


# --------------------------------------------------------------------------
# The whole battery.
# --------------------------------------------------------------------------


def run_gates(script, settings: Settings, *, data=None, as_of: str = "",
              skeptic: bool = True, workspace: Path | None = None,
              final: bool = True) -> GateReport:
    """Every gate, in cost order. Silence means proceed.

    `final` says whether what follows approval is a publishable render. It
    defaults to true because this battery runs on the intake path, and intake
    leads to the Approve button — the only thing on the other side of it is a
    final. A draft never comes through here (it skips approval entirely, which
    is the point of a draft), and the flag is what keeps the audio gate from
    blocking one if it ever does.
    """
    narration = getattr(script, "narration", None) or getattr(script, "audio_script", "")
    report = GateReport()
    report.findings += fact_check(narration, data)
    report.findings += onscreen_fact_check(script, data)
    report.findings += voice_lint(delivery_text(script))
    report.findings += confession_lint(script, settings)
    report.findings += check_freshness(as_of, settings, workspace=workspace)
    report.findings += check_audio(settings, final=final)
    kit_findings, kit_stats = kit_doctor(script, settings)
    report.findings += kit_findings
    if skeptic:
        report.findings += skeptic_notes(narration, settings)
    log.info("gates: %d findings (%d blocking); kit uses %d assets",
             len(report.findings), len(report.blocking), len(kit_stats["used"]))
    return report
