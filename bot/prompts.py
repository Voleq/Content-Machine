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
