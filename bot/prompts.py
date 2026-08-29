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
from datetime import date
from pathlib import Path

from config import Settings
from pipeline.broll import PALETTE, palette_keys
from pipeline.company_data import list_screenshots
from pipeline.memes import MemeLibrary
from pipeline.models import CompanyData


def voice_bible(settings: Settings) -> str:
    """The tone anchor (assets/voice_bible.md), injected verbatim."""
    f = settings.assets_dir / "voice_bible.md"
    return f.read_text(encoding="utf-8").strip() if f.exists() else "(voice bible missing)"


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


def scribble_styles(settings: Settings) -> str:
    """The `[SCRIBBLE: style -> target]` vocabulary, off the kit on disk.

    Generated for the same reason every other catalog here is: the templates
    named three styles while the kit ships twelve marks, and none of the three
    drew the artwork — so a writer was never told the drawings existed and
    could not have asked for one. A style whose artwork is missing still
    renders (a drawn stand-in takes it), but it is not offered.
    """
    from pipeline.kit import load_kit
    from pipeline.rasters import SCRIBBLE_MARKS

    kit = load_kit(settings.assets_dir)
    have = [s for s, (key, _) in sorted(SCRIBBLE_MARKS.items())
            if kit.get(key) is not None]
    return ", ".join(f"`{s}`" for s in have) or "`circle`, `arrow`, `underline`"


# --------------------------------------------------------------------------
# The plate catalogue — generated from the manifests, never written down.
# --------------------------------------------------------------------------
#
# A hand-maintained list drifts the moment the artwork changes, and the failure
# mode of drift is a script full of names that validate-then-fail. So the
# catalogue is emitted from the registry that ingest wrote from the kit's own
# manifests: name, purpose, slot names, and which chapter types may use it.


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


EXPRESSIVITY_AND_PACING = """\
Expressivity tags — inline, sparing, and never on every sentence:
  [BEAT]  a held pause before a punchline or a number lands
  [SIGH]  weary resignation; at most once or twice in a whole script
  [FLAT]  deadpan delivery of something that should sound dramatic
  [DRY]   the joke that is not signposted as a joke
  Four or five across a short, a dozen or so across a long. Tagging every
  sentence flattens the effect and reads as a tic.

Pacing:
  - Every chapter OPENS and CLOSES on the host's face. He introduces the
    evidence and he reacts to it; cutting straight from one chart to the next
    loses the person the viewer is actually watching.
  - A readable asset — a table, a filing quote, a chart worth studying —
    holds 6-8 seconds. Long enough to read it twice. Do not stack two
    readable things back to back.
  - The rhythm is: he says it, you show it, he reacts. Not: montage.
"""


def chart_metrics_line(data: CompanyData) -> str:
    """Only metrics with a real multi-year series in THIS data (+ price)."""
    return ", ".join(data.available_chart_metrics())


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


def filing_quotes_block(workspace: Path) -> str:
    """Auto-extracted 10-K quotes for the smoking-gun walk (task 5), read from
    the workspace manifest the auto-filings step writes AFTER the angle is
    picked. Each line gives the verbatim quote, its section, the one-line why,
    and the exact [SHOW FILING: file] to flash it. Empty until the angle step
    has run (or when nothing was found — then the walk is simply skipped)."""
    from pipeline.filings import load_manifest

    shots = load_manifest(workspace).get("shots", [])
    if not shots:
        return ("(no auto-extracted filing quotes for this angle yet — they are pulled "
                "after you pick an angle; skip the smoking-gun walk if none appear)")
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
    """Fill one master prompt. `fmt` ∈ {short, long_angle, long_write, headline}.

    Every prompt gets the catalogs it needs; the writing prompts (short,
    long_write, headline) additionally get the voice bible. `long_write` also
    gets the operator's {{chosen_angle}}; `headline` gets the operator's
    {{headline}} + optional {{article_summary}} + the active {{mode}}. `data`
    may be None for the macro headline mode (no single-company financials).
    """
    template_file = settings.templates_dir / f"master_prompt_{fmt}.md"
    text = template_file.read_text(encoding="utf-8")

    as_of = (data.get("as_of_date") if data is not None else None) or date.today().isoformat()
    r: dict[str, str] = {
        "{{ticker}}": ticker.upper(),
        "{{as_of_date}}": str(as_of),
        "{{company_data}}": (
            data.as_prompt_block() if data is not None else
            f"(macro mode — no single-company financials; anchor on {ticker.upper()} "
            f"as the index/sector proxy and the macro figures in the headline)"
        ),
        "{{chart_metrics}}": (
            chart_metrics_line(data) if data is not None else
            f"(index-based — the chart is the {ticker.upper()} proxy; the numbers "
            f"beat is optional and, if used, carries index levels or the macro series)"
        ),
    }

    if fmt == "short":
        r["{{move_context}}"] = move_context or (
            "(no screener context — fill in how much it moved today, on what "
            "volume, and the headline that did it)"
        )
        r["{{voice_bible}}"] = voice_bible(settings)
        r["{{meme_catalog}}"] = meme_catalog(settings)
        r["{{broll_palette}}"] = broll_catalog()
        r["{{scribble_styles}}"] = scribble_styles(settings)
        r["{{plate_catalogue}}"] = plate_catalogue(settings, fmt="short")
        r["{{chapter_types}}"] = chapter_type_catalogue(settings, fmt=fmt)
        r["{{tagging_density}}"] = TAGGING_DENSITY
        r["{{craft_rules}}"] = EXPRESSIVITY_AND_PACING
        r["{{peer_percentiles}}"] = peer_percentiles_block(data)
    elif fmt == "long_angle":
        r["{{available_screenshots}}"] = screenshots_line(workspace)
        r["{{valuation_data}}"] = valuation_data_block(data)
        r["{{peer_percentiles}}"] = peer_percentiles_block(data)
        r["{{filing_quotes}}"] = filing_quotes_block(workspace)
    elif fmt == "long_write":
        r["{{chosen_angle}}"] = chosen_angle.strip() or "(operator did not specify — use your ★recommended angle)"
        r["{{voice_bible}}"] = voice_bible(settings)
        r["{{meme_catalog}}"] = meme_catalog(settings)
        r["{{broll_palette}}"] = broll_catalog()
        r["{{scribble_styles}}"] = scribble_styles(settings)
        r["{{plate_catalogue}}"] = plate_catalogue(settings, fmt="long")
        r["{{chapter_types}}"] = chapter_type_catalogue(settings, fmt=fmt)
        r["{{tagging_density}}"] = TAGGING_DENSITY
        r["{{craft_rules}}"] = EXPRESSIVITY_AND_PACING
        r["{{available_screenshots}}"] = screenshots_line(workspace)
        r["{{valuation_data}}"] = valuation_data_block(data)
        r["{{peer_percentiles}}"] = peer_percentiles_block(data)
        r["{{filing_quotes}}"] = filing_quotes_block(workspace)
    elif fmt == "update":
        # An update is a LONG in every mechanical sense — same tag grammar,
        # same parser, same renderer, same validation — so it takes the long
        # writer's catalogs unchanged. What differs is the spine, and the
        # spine's first movement is `prior_coverage`.
        r["{{prior_coverage}}"] = prior_coverage(settings, ticker) or (
            "(no thesis on file for this ticker — nothing was recorded from a "
            "previous video. Write this as a first-time take instead: "
            "/long TICKER.)"
        )
        r["{{voice_bible}}"] = voice_bible(settings)
        r["{{meme_catalog}}"] = meme_catalog(settings)
        r["{{broll_palette}}"] = broll_catalog()
        r["{{scribble_styles}}"] = scribble_styles(settings)
        r["{{plate_catalogue}}"] = plate_catalogue(settings, fmt="long")
        r["{{chapter_types}}"] = chapter_type_catalogue(settings, fmt=fmt)
        r["{{tagging_density}}"] = TAGGING_DENSITY
        r["{{craft_rules}}"] = EXPRESSIVITY_AND_PACING
        r["{{available_screenshots}}"] = screenshots_line(workspace)
        r["{{valuation_data}}"] = valuation_data_block(data)
        r["{{peer_percentiles}}"] = peer_percentiles_block(data)
        r["{{filing_quotes}}"] = filing_quotes_block(workspace)
    elif fmt == "headline":
        r["{{headline}}"] = headline.strip() or "(no headline text supplied)"
        r["{{article_summary}}"] = article_summary.strip() or (
            "(no article summary — work from the headline itself)"
        )
        r["{{mode}}"] = headline_mode or "company"
        r["{{voice_bible}}"] = voice_bible(settings)
        r["{{meme_catalog}}"] = meme_catalog(settings)
        r["{{broll_palette}}"] = broll_catalog()
        r["{{scribble_styles}}"] = scribble_styles(settings)
        r["{{plate_catalogue}}"] = plate_catalogue(settings, fmt="short")
        r["{{chapter_types}}"] = chapter_type_catalogue(settings, fmt=fmt)
        r["{{tagging_density}}"] = TAGGING_DENSITY
        r["{{craft_rules}}"] = EXPRESSIVITY_AND_PACING
        r["{{peer_percentiles}}"] = (
            peer_percentiles_block(data) if data is not None else "(n/a in macro mode)"
        )
    else:
        raise ValueError(f"unknown prompt fmt {fmt!r}")

    for k, v in r.items():
        text = text.replace(k, v)
    return text
