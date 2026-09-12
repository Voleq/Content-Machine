"""Master-prompt filling: the operator never hand-assembles a prompt.

`/new` (after the data upload) returns the SHORT prompt and the LONG *angle*
prompt (Step 1) with every {{placeholder}} injected — the full dataset, the
voice bible, and the meme / b-roll / screenshot / chart-metric catalogues, plus
the PLATE CATALOGUE and the sixteen chapter types — ready to paste into
Claude/GPT. After the operator replies with an angle, `fill_prompt("long_write",
…)` returns the LONG *write* prompt (Step 2) pre-filled with the chosen angle.

The catalogues are injected verbatim so the director SELECTS from real, existing
plates (validated on paste-back) and picks the numbers that decide the story
from the real data.

The plate catalogue is GENERATED from the registry, which ingest wrote from the
kit's own manifests. A hand-maintained list drifts the moment the artwork
changes, and the failure mode of drift is a script full of names that
validate-then-fail.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable

from config import Settings
from pipeline.broll import PALETTE, palette_keys
from pipeline.company_data import list_screenshots
from pipeline.memes import MemeLibrary
from pipeline.models import CompanyData


def voice_bible(settings: Settings) -> str:
    """The tone anchor (assets/voice_bible.md), injected verbatim."""
    f = settings.assets_dir / "voice_bible.md"
    return f.read_text(encoding="utf-8").strip() if f.exists() else "(voice bible missing)"


def confession_ledger(settings: Settings) -> str:
    """What he has already admitted to, and whether one is due.

    The bible deletes "exactly one honest confession per video" — a mandatory
    confession turns a character trait into a segment, and twenty videos in it
    is the same story with the noun swapped. What replaces it is roughly one
    video in three, varying the kind, and a ledger so the same admission cannot
    be reused. This is the ledger, read out: a repetition rule the writer has
    to remember will fail, so the writer is handed the record instead.
    """
    from pipeline.standing import CONFESSION_KINDS, ConfessionLedger

    try:
        led = ConfessionLedger(settings)
        recent = led.confessions(6)
        since = led.videos_since_last()
        due = led.due()
    except Exception:                              # noqa: BLE001 — never fatal
        return "(confession ledger unreadable — write one only if the video earns it)"

    lines = [f"  The six kinds: {', '.join(CONFESSION_KINDS)}."]
    if not recent:
        lines.append("  Nothing recorded yet. Roughly one video in three carries "
                     "a confession; this one may or may not be it.")
    else:
        lines.append(
            f"  {since} video(s) since the last one." +
            ("  ONE IS DUE — write it only if the material earns it, and pick a "
             "kind that is not at the top of this list."
             if due else
             "  One is NOT due. Write one only if it is genuinely the best "
             "line available."))
        lines.append("  Already used, newest first — do not tell any of these again:")
        for c in recent:
            where = f"{c.ticker}" + (f", {c.workdate}" if c.workdate else "")
            lines.append(f"    - [{c.kind}] ({where}) {c.text}")
    lines.append("  Declare it in a `=== CONFESSION ===` trailer as "
                 "`kind | the admission`, once, or leave the block out.")
    return "\n".join(lines)


# Below this many videos a chapter type has not earned the word "evidence".
# One reading is an anecdote and two is a coincidence; the number is deliberately
# low because the alternative — showing nothing until there are eight — is a
# writer told nothing while the channel already knows something.
RETENTION_EVIDENCE_FLOOR = 3


def retention_evidence(settings: Settings) -> str:
    """Which chapter types actually held people, for the writer choosing the plan.

    The loop was built and disconnected at the last inch: retention is pulled,
    mapped onto chapters, stored and shown to the OPERATOR by `/retention`, and
    the one person who picks the chapter plan never saw it. This is the only
    measurement that should influence which chapters get written, so it goes in
    the prompt that writes them.

    Worst first, because the bottom of this list is what changes. Every row
    carries its video count and rows under the floor are marked as not yet
    evidence — a writer handed a single 22% reading and no denominator will
    cut a chapter type on one video's bad afternoon.
    """
    from pipeline.youtube import chapter_type_evidence

    try:
        rows = chapter_type_evidence(settings)
    except Exception:                              # noqa: BLE001 — never fatal
        return ("(retention unreadable — write the chapters the story earns "
                "and ignore this block)")
    if not rows:
        return ("(nothing published has retention against it yet, so there is "
                "no evidence either way. Write the chapters the story earns. "
                "Videos uploaded before the chapter type was recorded carry no "
                "type and never count towards this.)")

    lines = ["  Average watch ratio per chapter TYPE, across every video with "
             "retention. Worst first."]
    for row in rows[:16]:
        n = row["videos"]
        tail = ("" if n >= RETENTION_EVIDENCE_FLOOR
                else "  <- NOT YET EVIDENCE, too few videos")
        lines.append(f"    {row['avg_watch_ratio'] * 100:5.1f}%  "
                     f"{row['type']:<22} (n={n}){tail}")
    thin = sum(1 for r in rows if r["videos"] < RETENTION_EVIDENCE_FLOOR)
    lines.append(
        f"  A type needs at least {RETENTION_EVIDENCE_FLOOR} videos behind it "
        f"before this says anything"
        + (f" — {thin} of the rows above do not have that yet." if thin
           else "; every row above clears that."))
    lines.append("  Use it to decide WHICH optional chapters this video earns "
                 "and where the weak ones sit, not to delete a chapter the "
                 "story needs. A type at the bottom is a type to write BETTER "
                 "or place earlier, not one to stop writing.")
    return "\n".join(lines)


def meme_catalog(settings: Settings) -> str:
    """Every meme key + its 'use when' — the full catalog (capped in use)."""
    idx = MemeLibrary(settings).index()
    if not idx:
        return "(meme library empty)"
    lines = []
    for key in sorted(idx):
        use = (idx[key].get("use_when") or "").strip()
        lines.append(f"  - {key}" + (f" — {use}" if use else ""))
    return "\n".join(lines)


def broll_catalog() -> str:
    """The vetted b-roll palette: key — the search it maps to."""
    return "\n".join(f"  - {k} — {PALETTE[k]}" for k in palette_keys())


# `scribble_styles` was defined twice in this file. The first definition
# imported `pipeline.kit`, a module that does not exist — so it would have
# raised on the first call, and never did, because the SECOND definition (a
# few hundred lines down, reading the plate registry) shadowed it. Harmless
# in the sense that nothing broke; dangerous in the sense that a reader
# looking for the live one found the dead one first (J2). The dead one is
# gone.

def plate_catalogue(settings: Settings, *, fmt: str = "long") -> str:
    """Every plate the director may name, with what it is for and its slots."""
    from pipeline.plate_tags import _slot_summary
    from pipeline.plates import PlateError, load_plates

    try:
        reg = load_plates(settings.assets_dir)
    except PlateError:
        return ("(the design kit is not ingested — run "
                "`python scripts/ingest_kit.py kit`. Until it is, no [PLATE] tag "
                "will resolve and the video will be a talking head.)")

    aspect = "9x16" if fmt == "short" else "16x9"
    lines: list[str] = []
    for family in reg.families():
        if family in ("host", "room", "overlays"):
            continue          # the renderer places these; a script never names one
        keys = [k for k in reg.family(family)
                if not reg.assets[k].aspect or reg.assets[k].aspect == aspect]
        if not keys:
            continue
        lines.append("")
        lines.append(f"{family}/")
        for k in keys:
            plate = reg.assets[k]
            short = k.split("/", 1)[1]
            lines.append(f"  {short}"
                         + (f" — {plate.purpose}" if plate.purpose else ""))
            slots = _slot_summary(plate)
            if slots:
                lines.append(f"      slots: {slots}")
    return "\n".join(lines).strip() or "(no plates in the registry)"


def chapter_type_catalogue(settings: Settings, *, fmt: str = "long") -> str:
    """The sixteen types, what each is for, and the plates it may use."""
    from pipeline.plates import CHAPTER_TYPES, PlateError, load_plates

    try:
        reg = load_plates(settings.assets_dir)
    except PlateError:
        return "(the design kit is not ingested — run scripts/ingest_kit.py kit)"

    aspect = "9x16" if fmt == "short" else "16x9"
    lines: list[str] = []
    for ctype in CHAPTER_TYPES:
        purpose = reg.chapter_purpose(ctype)
        lines.append(f"  {ctype}" + (f" — {purpose}" if purpose else ""))
        # The universal plates are in every type; naming them sixteen times
        # turns the menu into a wall. List what this type ADDS, by plate rather
        # than by family — "figures" is not the same permission as
        # "big-number-l1 and big-number-l2", and the validator enforces the
        # narrower one.
        universal = set(reg.universal_plates())
        extra = sorted({k.split("/", 1)[1] for k in reg.plates_for_chapter(ctype)
                        if k not in universal
                        and (not reg.assets[k].aspect
                             or reg.assets[k].aspect == aspect)})
        if extra:
            lines.append(f"      may also use: {', '.join(extra)}")
    lines.append("")
    lines.append("  Every type may also use: "
                 + ", ".join(sorted({k.split('/', 1)[0]
                                     for k in reg.universal_plates()})))
    return "\n".join(lines)


def scribble_styles(settings: Settings) -> str:
    """The `[SCRIBBLE: mark -> target]` vocabulary, off the registry.

    A style IS an annotations/ plate name, so this is the family listing rather
    than a second naming scheme. Only marks the kit actually ships are offered.
    """
    from pipeline.plates import PlateError, load_plates

    try:
        reg = load_plates(settings.assets_dir)
    except PlateError:
        return "(the design kit is not ingested)"
    return ", ".join(f"`{k.split('/', 1)[1]}`" for k in reg.family("annotations"))


# How densely a script should tag. The reference long script is 35 minutes with
# about 35 tagged visuals — one a minute, which is a talking head with
# occasional pictures.
TAGGING_DENSITY = """\
TAGGING DENSITY — three to five visuals a minute, every minute.

The last long script ran 35 minutes on 35 tagged visuals: one a minute. That is
a podcast with pictures. Every claim that has a number in it gets a plate; every
comparison gets one; every quote from a filing gets [SHOW FILING]. If a chapter
runs two minutes with one visual, it is under-tagged and you will be told so.

Reach for [SHOW FILING] WHENEVER THE SCRIPT QUOTES A FILING. If the narration
says "it's in the risk factors, and it names a person", show the risk factor.
The reference script said exactly that and showed nothing, which asks the
audience to take your word for the most checkable claim in the video."""


def delivery_vocabulary() -> str:
    """The delivery tags, their modes and their ceilings — from the table.

    GENERATED, like every other catalogue the writer is handed, because a
    hand-kept copy of a vocabulary is a copy that goes stale. The list here,
    what `pipeline/tts.py` emits, and what `gates.direction_lint` refuses are
    the same four facts read off `pipeline/direction.py` once.

    A writer who is not told a tag exists does not use it, which is the whole
    reason §7's "rare genuine interest — the monotone lifts" went unspoken for
    as long as it did: there was a mode in the bible and no way to ask for it.
    """
    from pipeline.direction import (BANNED_TAGS, DIRECTIONS,
                                    MAX_TAGS_PER_SENTENCE, PER_SCRIPT_MAX,
                                    REGISTERS, TAGS_PER_1K_CHARS_WARN)

    rows = []
    for tag, d in sorted(DIRECTIONS.items(), key=lambda kv: kv[0].value):
        rows.append(f"  [{tag.value}]".ljust(15) + f"{d.mode}".ljust(29) + d.why)
    rows.append("")
    for tag, r in sorted(REGISTERS.items(), key=lambda kv: kv[0].value):
        rows.append(f"  [{tag.value}]".ljust(15) + f"{r.mode}".ljust(29) + r.why)

    caps = ", ".join(
        f"[{t.value}] at most {n}" for t, n in
        sorted(PER_SCRIPT_MAX.items(), key=lambda kv: kv[0].value))

    trying, effects = [], []
    for name, reason in sorted(BANNED_TAGS.items()):
        (effects if "did not happen" in reason else trying).append(f"[{name}]")

    return f"""\
DELIVERY DIRECTION — inline, sparing, and never on screen. These reach the
voice, not the captions. YOU declare the delivery; nothing downstream invents
it, and nothing downstream second-guesses it.

{chr(10).join(rows)}

  The four modes are the bible's (§7). [CURIOUS] is the one worth learning:
  "a mechanism he actually respects; the monotone lifts — these lifts are the
  retention". It is the only tag that buys a lift, so spend it on the one
  mechanism in the video that genuinely deserves one.

HOW MUCH — a device used constantly stops being a device:
  - At most {MAX_TAGS_PER_SENTENCE} per sentence, and never two with nothing between them.
  - At most {TAGS_PER_1K_CHARS_WARN:.0f} per 1,000 characters across the whole script.
  - Per script: {caps}.
  - [QUIET] never in the opening chapter — dark calm is the register the
    video earns its way down to, so it has nothing to drop from yet.
  - Write them NOW. They change what gets generated, so adding one after the
    audio exists means paying for the generation twice.

NEVER — these are refused by name, with the reason, and the first one is
refused as a BLOCK because in lowercase it is not a tag at all: it would be
read out loud and captioned.
  {" ".join(trying)}
      §2 — still banned: anything that reads as trying. A host who audibly
      laughs at his own line has broken the deadpan, and the flatness IS the
      delivery.
  {" ".join(effects)}
      A sound effect is the pipeline manufacturing an event that did not
      happen, in a product whose whole claim is that every figure is checked.

Do not SHOUT a word for emphasis either. Capitalisation is read as emphasis by
the voice, and the captions are built from the same text — so it is heard and
seen leaning on the word. The bible bans the exclamation mark for this reason;
this is the same thing wearing a different hat.
"""


PACING = """\
Pacing:
  - Every chapter OPENS and CLOSES on the host's face. He introduces the
    evidence and he reacts to it; cutting straight from one chart to the next
    loses the person the viewer is actually watching.
  - A readable asset — a table, a filing quote, a chart worth studying —
    holds 6-8 seconds. Long enough to read it twice. Do not stack two
    readable things back to back.
  - The rhythm is: he says it, you show it, he reacts. Not: montage.
"""


def expressivity_and_pacing() -> str:
    """What every writing prompt is handed as {{craft_rules}}."""
    return delivery_vocabulary() + "\n" + PACING


def chart_metrics_line(data: CompanyData) -> str:
    """Only metrics with a real multi-year series in THIS data (+ price).

    The quarterly series are named separately (O5) rather than folded into
    the annual list. A writer must not feature a quarterly row the sheet
    does not carry — the same rule the annual list has always enforced —
    and the two lists are genuinely different: a ticker can have five years
    of revenue and no Quarters sheet at all.
    """
    line = ", ".join(data.available_chart_metrics())
    quarterly = data.available_quarter_metrics()
    if quarterly:
        line += ("\nQuarterly series present (a quarterly claim MUST come "
                 "from here): " + ", ".join(quarterly))
    return line


def quarters_block(data: CompanyData) -> str:
    """The `[quarters]` table, or why there is not one.

    A MISSING SHEET IS SAID OUT LOUD rather than leaving a blank where a
    table should be. `templates/shots/earnings.json` is a complete 9:16
    format whose first two beats are `the-print` and `vs-expected`, and
    before O1 there was no quarterly data behind either: the writer supplied
    the print from its own training knowledge and `fact_check` could not
    verify a word of it, because it only had annual series to compare
    against (O0). A silent blank here reproduces that exactly.
    """
    if data.has_quarters:
        return data.quarters_prompt_block()
    return ("(no Quarters sheet in this workbook — you have NO quarterly "
            "data. Do not state a print, a beat/miss, or a quarter-on-quarter "
            "move: nothing here can check it. Work from the annual series "
            "above. To get quarterly numbers, refresh the template and fill "
            "the Quarters sheet.)")


def _pct(v) -> str:
    """A stored fraction (0.074) rendered as a percent (7.4%); n/a when absent."""
    return f"{v * 100:.1f}%" if isinstance(v, (int, float)) else "n/a"


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def valuation_data_block(data: CompanyData) -> str:
    """The reverse-DCF figures for the MANDATORY valuation beat — a perpetuity
    gut-check ("priced for X, has delivered Y"), never a fair value. Exact
    numbers so the writer can cite them instead of guessing."""
    v = data.valuation or {}
    keys = ("implied_growth", "wacc", "hist_fcf_cagr", "rev_cagr", "priced_vs_delivered")
    if not any(v.get(k) is not None for k in keys) and not v.get("reverse_dcf_read"):
        return ("(no reverse-DCF in this export — keep the valuation beat qualitative: "
                "what the current price assumes vs what the business has delivered)")
    lines = [
        'Reverse-DCF — a perpetuity gut-check ("priced for X, has delivered Y"), NOT a fair value:',
        f"  Implied growth priced into today's price (perpetual FCF growth): {_pct(v.get('implied_growth'))}",
        f"  Discount rate used (WACC): {_pct(v.get('wacc'))}",
        f"  Historical FCF CAGR, 4y — what it has ACTUALLY delivered: {_pct(v.get('hist_fcf_cagr'))}",
        f"  Revenue CAGR, 4y: {_pct(v.get('rev_cagr'))}",
        f"  Priced-for minus delivered (FCF), in growth points: {_pct(v.get('priced_vs_delivered'))}",
    ]
    read = v.get("reverse_dcf_read")
    if read:
        lines.append(f"  Read (verdict): {read}")
    return "\n".join(lines)


def peer_percentiles_block(data: CompanyData) -> str:
    """Where THIS ticker ranks within its peer set, metric by metric — the
    "90th percentile on price, 20th on margins" read the valuation beat folds
    in. `percentile` is a 0–1 fraction; `direction` says which way is good."""
    pcts = data.peer_percentiles or []
    if not pcts:
        return "(no peer-percentile block in this export)"
    lines: list[str] = []
    for p in pcts:
        metric = p.get("metric")
        if not metric:
            continue
        pct = p.get("percentile")
        rank = f"{_ordinal(round(pct * 100))} pctile" if isinstance(pct, (int, float)) else "pctile n/a"
        subj, med = p.get("subject"), p.get("median")
        detail = f"subject {subj} vs peer median {med}" if subj is not None and med is not None else ""
        direction = p.get("direction")
        higher = f"higher is {direction}" if direction else ""
        read = p.get("read")
        bits = [b for b in (rank, detail, higher, read) if b]
        lines.append(f"  {metric}: " + " — ".join(bits))
    return "\n".join(lines) if lines else "(no peer-percentile block in this export)"


def filing_brief_block(workspace: Path) -> str:
    """The pre-angle filing survey, or why there is not one (K4).

    A NEW PLACEHOLDER rather than filling `{{filing_quotes}}`: the two
    artefacts are different shapes — a brief is prose, the quotes are
    verbatim receipts carrying `[SHOW FILING: …]` flash instructions — and
    collapsing them means the prompt cannot tell the model which is which.
    """
    from pipeline.filing_brief import load_brief

    brief = load_brief(workspace)
    if brief is None:
        return ("(the filing has not been read for this ticker yet — the "
                "pre-angle pass either has not finished or did not run. "
                "Work from the numbers above.)")
    return brief.render_text()


def filing_quotes_block(workspace: Path) -> str:
    """Verbatim 10-K quotes for the smoking-gun walk (task 5), read from the
    workspace manifest `auto_filings` writes AFTER an angle is picked. Each
    line gives the quote, its section, the one-line why, and the exact
    [SHOW FILING: file] to flash it.

    The empty-state text used to say filing material "is pulled after you
    pick an angle", which was true of the quotes and became misleading the
    moment `{{filing_brief}}` could be present at angle time (K4) — a reader
    told that nothing from the filing is available yet will not use the
    survey sitting directly above it.
    """
    from pipeline.filings import load_manifest

    shots = load_manifest(workspace).get("shots", [])
    if not shots:
        return ("(no verbatim quotes yet — these are pulled for a CHOSEN "
                "angle, so they are normally absent at the angle step. The "
                "filing survey above is separate and may well be present; "
                "skip only the smoking-gun walk if no quotes appear.)")
    lines: list[str] = []
    for s in shots:
        quote = (s.get("quote") or "").strip()
        section = s.get("section") or ""
        why = s.get("why") or ""
        name = s.get("name") or ""
        head = f'  - "{quote}"'
        if section:
            head += f" ({section})"
        lines.append(head)
        if why:
            lines.append(f"      why: {why}")
        if name:
            lines.append(f"      flash: [SHOW FILING: {name}]")
    return "\n".join(lines)


def screenshots_line(workspace: Path) -> str:
    shots = list_screenshots(workspace)
    return ", ".join(shots) if shots else "(none uploaded — upload filing PNGs first)"


# --------------------------------------------------------------------------
# What this channel has already said about the ticker.
# --------------------------------------------------------------------------
# The loop used to be: remember -> notify -> forget. `ThesisBook` recorded a
# thesis when a video shipped, `update_warranted` told the operator the numbers
# had moved and dropped it in the idea queue — and then the writing prompt was
# byte-identical to a first-time one. The bot knew, and never told the writer.


def _days_since(stamp: str) -> int | None:
    """Whole days between an ISO stamp and today, or None if unparseable."""
    from datetime import datetime, timezone

    for text in (stamp or "",):
        try:
            when = datetime.fromisoformat(text)
        except ValueError:
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return max((datetime.now(timezone.utc) - when).days, 0)
    return None


def _moves_since(thesis) -> list[str]:
    """The last check's material moves, rendered.

    Through `Move.render()` rather than a second formatter: it already says
    "gross_margin ↓12% (74.4 → 65.2)", and two formatters for one fact is how
    the report and the notification end up disagreeing about the same number.
    The stored rows carry a cached `change` that `Move` computes itself, so
    unknown keys are dropped rather than passed to the constructor.
    """
    from pipeline.standing import Move

    known = {f for f in Move.__dataclass_fields__}
    out: list[str] = []
    for row in getattr(thesis, "last_moves", None) or []:
        try:
            out.append(Move(**{k: v for k, v in row.items() if k in known}).render())
        except (TypeError, ValueError):
            continue
    return out


def prior_coverage(settings: Settings, ticker: str) -> str:
    """What this channel already said about `ticker`, for the next writer.

    Returns "" when there is no thesis on file — an update prompt filled for a
    name we have never covered has nothing to say, and saying nothing is
    better than a heading over an empty block.

    A thesis recorded before the record was widened carries only a summary. It
    still renders, and the block states which fields are ABSENT: a writer told
    "the conclusion is not on file" writes around it, while a writer told
    nothing invents a conclusion that was never made and grades the channel
    against a claim it never put on screen.
    """
    from pipeline.standing import ThesisBook

    try:
        thesis = ThesisBook(settings).get(ticker)
    except Exception:  # noqa: BLE001 — a thin record never blocks a prompt
        thesis = None
    if thesis is None:
        return ""

    fmt = (thesis.fmt or "").upper()
    when = thesis.workdate or (thesis.recorded_at or "")[:10] or "date not recorded"
    # Off the workdate where there is one, because that is the date shown and
    # a stamp that disagrees with the date beside it reads as a bug.
    age = _days_since(thesis.workdate) or _days_since(thesis.recorded_at)
    ago = {None: "", 0: " — today", 1: " — yesterday"}.get(age, f" — {age} days ago")
    shipped = when + (f" ({fmt})" if fmt else "") + ago

    lines = [f"PRIOR COVERAGE — this channel has already made a video about "
             f"{ticker.upper()}. This is what it said.",
             f"  Shipped: {shipped}"]
    if thesis.summary:
        lines.append(f"  The angle: {thesis.summary}")
    if thesis.hook:
        lines.append(f'  It opened on: "{thesis.hook}"')
    if thesis.conclusion:
        lines.append(f'  It concluded, VERBATIM: "{thesis.conclusion}"')
    if thesis.claims:
        lines.append("  It asserted:")
        lines += [f"    - {c}" for c in thesis.claims]

    status = thesis.status or "intact"
    checked = (thesis.checked_at or "")[:10]
    lines.append(f"  Thesis status: {status}"
                 + (f" (last checked {checked})" if checked else ""))

    moves = _moves_since(thesis)
    if moves:
        lines.append("  What has moved since:")
        lines += [f"    - {m}" for m in moves]
    else:
        lines.append("  What has moved since: nothing material at the last check.")

    absent = [name for name, value in (("the hook", thesis.hook),
                                       ("the conclusion", thesis.conclusion),
                                       ("the specific claims", thesis.claims))
              if not value]
    if absent:
        lines.append(
            "  NOT ON FILE: " + ", ".join(absent) + ". That video shipped "
            "before those were recorded — do NOT invent them. Grade only what "
            "is written above, and say plainly that the rest is not on record.")
    return "\n".join(lines)

# --------------------------------------------------------------------------
# The payload, as a table.
# --------------------------------------------------------------------------
#
# This was five hand-written branches, one per prompt, each listing its own
# placeholders (M6). That is how you get one block computed and discarded,
# another missing where it is needed, and a third that reaches nobody:
#
#   M1  `{{chapter_types}}` was built for `short` and for `headline`, and
#       NEITHER template contains the token. `chapter_type_catalogue` reads
#       the plate registry to build a catalogue that was then thrown away on
#       both paths. Decided rather than papered over: a chapter is a LONG
#       concept and a SHORT has none, so it is not built for them.
#   M2  `{{retention}}` went to `long_write` and not to `update`, though both
#       are 16:9 long-form with the same tag grammar, the same parser and the
#       same renderer — and per-chapter drop-off is MORE useful on a revisit,
#       where there is retention data for the name already.
#   M3  `{{valuation_data}}` went to all three long prompts and not to
#       `short`, whose beat 8 is cheap-or-trap: "Is the multiple a bargain or
#       a trap? Name the multiple, then say what would have to be true for it
#       to be cheap." That asked for a judgement with none of the evidence
#       for it — no scenarios, no WACC, no reverse-DCF read.
#   M5  `news` is one entry here rather than five edits.
#
# One canonical ORDER, facts before instructions, the same in every prompt so
# the model is not relearning the layout each time:
#
#   subject -> what moved -> the numbers -> valuation -> peers
#     -> prior coverage -> source material -> voice -> visual catalogs
#     -> craft rules -> output contract
#
# A mismatch between a template's tokens and what this table fills is now a
# TEST FAILURE rather than a silent no-op: see
# `tests/test_prompt_payload.py`.

_WRITING = ("short", "long_write", "update", "headline")
_LONG_FORM = ("long_write", "update")
_ALL = ("short", "long_angle", "long_write", "update", "headline")


@dataclass(frozen=True)
class PayloadBlock:
    """One `{{token}}`, who receives it, and what builds it."""

    token: str
    formats: tuple[str, ...]
    build: "Callable[[_Ctx], str]"


@dataclass
class _Ctx:
    """Everything any block could need. Built once per fill."""

    fmt: str
    ticker: str
    data: CompanyData | None
    workspace: Path
    settings: Settings
    move_context: str = ""
    chosen_angle: str = ""
    headline: str = ""
    article_summary: str = ""
    headline_mode: str = ""


def _macro(ctx: "_Ctx") -> bool:
    return ctx.data is None


PAYLOAD: tuple[PayloadBlock, ...] = (
    # --- subject
    PayloadBlock("{{ticker}}", _ALL, lambda c: c.ticker.upper()),
    PayloadBlock("{{as_of_date}}", _ALL, lambda c: str(
        (c.data.get("as_of_date") if c.data is not None else None)
        or date.today().isoformat())),
    PayloadBlock("{{mode}}", ("headline",),
                 lambda c: c.headline_mode or "company"),

    # --- what moved
    PayloadBlock("{{move_context}}", ("short",), lambda c: c.move_context or (
        "(no live quote and no screener context — fill in how much it moved "
        "today, on what volume, and the headline that did it)")),
    PayloadBlock("{{headline}}", ("headline",),
                 lambda c: c.headline.strip() or "(no headline text supplied)"),
    PayloadBlock("{{article_summary}}", ("headline",),
                 lambda c: c.article_summary.strip() or
                 "(no article summary — work from the headline itself)"),

    # --- the numbers
    PayloadBlock("{{company_data}}", _ALL, lambda c: (
        c.data.as_prompt_block() if c.data is not None else
        f"(macro mode — no single-company financials; anchor on "
        f"{c.ticker.upper()} as the index/sector proxy and the macro figures "
        f"in the headline)")),
    PayloadBlock("{{quarters}}", _ALL, lambda c: (
        quarters_block(c.data) if c.data is not None else
        "(macro mode — no company quarters)")),
    PayloadBlock("{{chart_metrics}}", _ALL, lambda c: (
        chart_metrics_line(c.data) if c.data is not None else
        f"(index-based — the chart is the {c.ticker.upper()} proxy; the "
        f"numbers beat is optional and, if used, carries index levels or the "
        f"macro series)")),

    # --- valuation, then peers
    PayloadBlock("{{valuation_data}}",
                 ("short", "long_angle", "long_write", "update"),
                 lambda c: valuation_data_block(c.data)),
    PayloadBlock("{{peer_percentiles}}", _ALL, lambda c: (
        "(n/a in macro mode)" if _macro(c)
        else peer_percentiles_block(c.data))),

    # --- prior coverage
    PayloadBlock("{{prior_coverage}}", ("update",),
                 lambda c: prior_coverage(c.settings, c.ticker) or (
                     "(no thesis on file for this ticker — nothing was "
                     "recorded from a previous video. Write this as a "
                     "first-time take instead: /long TICKER.)")),
    PayloadBlock("{{chosen_angle}}", ("long_write",),
                 lambda c: c.chosen_angle.strip() or
                 "(operator did not specify — use your ★recommended angle)"),

    # --- source material
    #
    # THE BRIEF BEFORE THE RECEIPTS. A survey of the filings, present at
    # ANGLE time — which is the whole of K: the angle prompt used to be
    # built from workbook numbers only, and its filing slot was always
    # empty because the quotes are pulled after an angle is chosen.
    PayloadBlock("{{filing_brief}}", ("long_angle", "update"),
                 lambda c: filing_brief_block(c.workspace)),
    PayloadBlock("{{filing_quotes}}", ("long_angle", "long_write", "update"),
                 lambda c: filing_quotes_block(c.workspace)),
    PayloadBlock("{{available_screenshots}}",
                 ("long_angle", "long_write", "update"),
                 lambda c: screenshots_line(c.workspace)),

    # --- voice
    PayloadBlock("{{voice_bible}}", _WRITING,
                 lambda c: voice_bible(c.settings)),
    PayloadBlock("{{confession_ledger}}", _LONG_FORM,
                 lambda c: confession_ledger(c.settings)),
    PayloadBlock("{{retention}}", _LONG_FORM,
                 lambda c: retention_evidence(c.settings)),

    # --- visual catalogs
    # LONG-FORM ONLY. Both were offered to the SHORT lane as well, where
    # nothing draws them: a short's frames come from its shot template, and
    # no template in `templates/shots/` binds `meme`, `broll` or
    # `annotations`. So the prompt offered a choice that validated, was
    # counted on the cost report, and reached no frame — forty lines above
    # the paragraph telling the writer the inline form of the same two tags
    # was LONG-form grammar (P3).
    PayloadBlock("{{meme_catalog}}", _LONG_FORM,
                 lambda c: meme_catalog(c.settings)),
    PayloadBlock("{{broll_palette}}", _LONG_FORM, lambda c: broll_catalog()),
    PayloadBlock("{{plate_catalogue}}", ("short", "long_write", "update"),
                 lambda c: plate_catalogue(
                     c.settings, fmt="short" if c.fmt == "short" else "long")),
    PayloadBlock("{{scribble_styles}}", _LONG_FORM,
                 lambda c: scribble_styles(c.settings)),
    PayloadBlock("{{chapter_types}}", _LONG_FORM,
                 lambda c: chapter_type_catalogue(c.settings, fmt=c.fmt)),

    # --- craft rules
    PayloadBlock("{{tagging_density}}", ("short", "long_write", "update"),
                 lambda c: TAGGING_DENSITY),
    PayloadBlock("{{craft_rules}}", _WRITING,
                 lambda c: expressivity_and_pacing()),
)

PROMPT_FORMATS = _ALL


def payload_tokens(fmt: str) -> set[str]:
    """The tokens this table fills for `fmt`. The test reads this."""
    return {b.token for b in PAYLOAD if fmt in b.formats}


def fill_prompt(
    fmt: str,
    ticker: str,
    data: CompanyData | None,
    workspace: Path,
    settings: Settings,
    move_context: str = "",
    chosen_angle: str = "",
    headline: str = "",
    article_summary: str = "",
    headline_mode: str = "",
) -> str:
    """Fill one master prompt from `PAYLOAD`.

    `fmt` is one of `PROMPT_FORMATS`. Which blocks a prompt receives is
    declared in the table above rather than in a branch here, so adding one
    is a single entry and a prompt cannot quietly be handed a block its
    template does not contain (M6).

    `data` may be None for the macro headline mode (no single-company
    financials).
    """
    if fmt not in PROMPT_FORMATS:
        raise ValueError(f"unknown prompt fmt {fmt!r}")
    template_file = settings.templates_dir / f"master_prompt_{fmt}.md"
    text = template_file.read_text(encoding="utf-8")

    ctx = _Ctx(fmt=fmt, ticker=ticker, data=data, workspace=workspace,
               settings=settings, move_context=move_context,
               chosen_angle=chosen_angle, headline=headline,
               article_summary=article_summary, headline_mode=headline_mode)
    for block in PAYLOAD:
        if fmt in block.formats:
            text = text.replace(block.token, block.build(ctx))
    return text
