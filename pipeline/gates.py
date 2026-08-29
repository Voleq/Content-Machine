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
_METRIC_WORDS = {
    "revenue": ("revenue", "sales", "top line"),
    "net_income": ("net income", "bottom line", "earnings"),
    "free_cash_flow": ("free cash flow", "fcf"),
    "shares_outstanding": ("share count", "shares outstanding", "diluted shares"),
    "total_debt": ("total debt", "debt load"),
    "cash": ("cash", "cash on hand", "cash balance"),
    "gross_margin": ("gross margin",),
    "operating_margin": ("operating margin",),
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


def voice_lint(narration: str) -> list[Finding]:
    """Flags what the bible forbids. Never a joke quota — density is the
    writer's call and a linter that policed it would flatten the voice."""
    findings: list[Finding] = []
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

    return findings, {
        "used": sorted(used),
        "unresolved_keys": unresolved,
        "never_used": sorted(never_used),
        "never_used_count": len(never_used),
        "unfilled": unfilled,
        "kit_size": len(reg),
        "outfit": reg.outfit,
        "renders_seen": renders_seen,
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
    report.findings += voice_lint(narration)
    report.findings += check_freshness(as_of, settings, workspace=workspace)
    report.findings += check_audio(settings, final=final)
    kit_findings, kit_stats = kit_doctor(script, settings)
    report.findings += kit_findings
    if skeptic:
        report.findings += skeptic_notes(narration, settings)
    log.info("gates: %d findings (%d blocking); kit uses %d assets",
             len(report.findings), len(report.blocking), len(kit_stats["used"]))
    return report
