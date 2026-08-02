"""Master-prompt filling: the operator never hand-assembles a prompt.

`/new` (after the data upload) returns the SHORT prompt and the LONG
*angle* prompt (Step 1) with every {{placeholder}} injected — the full
dataset, the voice bible, and the full doodle / meme / b-roll / screenshot
/ chart-metric catalogs — ready to paste into Claude/GPT. After the
operator replies with an angle, `fill_prompt("long_write", …)` returns the
LONG *write* prompt (Step 2) pre-filled with the chosen angle.

The catalogs are injected verbatim so the director SELECTS from real,
existing keys (validated on paste-back) and picks the numbers that decide
the story from the real data — the human decision is the ANGLE, not the
plumbing.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from config import Settings
from pipeline.broll import PALETTE, palette_keys
from pipeline.company_data import list_screenshots
from pipeline.doodles import DoodleLibrary
from pipeline.memes import MemeLibrary
from pipeline.models import CompanyData


def voice_bible(settings: Settings) -> str:
    """The tone anchor (assets/voice_bible.md), injected verbatim."""
    f = settings.assets_dir / "voice_bible.md"
    return f.read_text(encoding="utf-8").strip() if f.exists() else "(voice bible missing)"


def doodle_catalog(settings: Settings) -> str:
    """Every doodle key + its 'use when', grouped by section — the full
    catalog the director picks from (keys must exist; validated on paste)."""
    idx = DoodleLibrary(settings).index()
    if not idx:
        return "(doodle library empty)"
    by_section: dict[str, list[str]] = {}
    for stem in sorted(idx):
        meta = idx[stem]
        section = meta.get("section") or "misc"
        use = (meta.get("use_when") or "").strip()
        by_section.setdefault(section, []).append(
            f"  - {stem}" + (f" — {use}" if use else "")
        )
    lines: list[str] = []
    for section in sorted(by_section):
        lines.append(f"[{section}]")
        lines.extend(by_section[section])
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


# --------------------------------------------------------------------------
# The kit catalog (addendum 1e).
# --------------------------------------------------------------------------

# What each concept illustration is FOR. Concepts are the one family where the
# key alone doesn't say when to reach for it, so they get a line each; the rest
# are self-describing keys and stay terse. Anything not listed here still gets
# offered, just without a gloss — so adding artwork never needs a code change.
_CONCEPT_USE = {
    "actions-vs-words": "management said one thing and did another",
    "dont-swing": "no edge here — the right move is not to play",
    "prayer-session": "the bull case now depends on hope, not numbers",
    "risk-filing": "the risk was disclosed all along, in the filing",
    "risk-iceberg": "the disclosed risk is the small visible part",
    "value-trap-hope": "cheap for a reason, and the reason hasn't changed",
    "value-trap-trap": "the discount is the trap, not the opportunity",
}

# Prefixes stripped from a key when the tag payload doesn't need them:
# `[PROP: laptop]` resolves `obj-laptop`, `[TERM: roic]` resolves `term-roic`.
_STRIP_PREFIXES = ("obj-", "term-", "big-number-", "compare-", "react-", "beat-")


def _leaves(kit, prefix: str | tuple[str, ...], *, keep: str = "",
            strip: bool = True, drop_blanks: bool = False) -> list[str]:
    """Family leaf keys, optionally filtered to one naming prefix.

    Takes several families, because one tag's artwork now lives across more
    than one folder in the rebuilt kit.

    `drop_blanks` removes the empty layouts (`term-card-blank`,
    `big-number-blank`). They are real and useful — they take arbitrary text —
    but in a list headed "frameworks that exist" they read as one more named
    framework, which is exactly the confusion this catalog is meant to remove.
    They get their own line instead.
    """
    prefixes = (prefix,) if isinstance(prefix, str) else tuple(prefix)
    out: list[str] = []
    for fam in prefixes:
        head = fam.rstrip("/") + "/"
        for name in kit.family(fam):
            leaf = name[len(head):]
            if keep and not leaf.startswith(keep):
                continue
            if strip:
                for p in _STRIP_PREFIXES:
                    if leaf.startswith(p):
                        leaf = leaf[len(p):]
                        break
            if drop_blanks and (leaf == "blank" or leaf.endswith("-blank")):
                continue
            out.append(leaf)
    return sorted(set(out))


def _chapter_kits(kit) -> list[str]:
    """Chapter kits that ship dedicated artwork."""
    return sorted(f.split("/", 1)[1] for f in kit.families()
                  if f.startswith("chapters/"))


def _shorts_families(kit) -> list[tuple[str, list[str]]]:
    """The shorts batch, family by family, with each asset's title.

    This is the half of the library the SHORT writer has never been shown. The
    long-form prompt has had a catalog since the kit existed; the short prompt
    got the tags and none of the vocabulary, so every script reached for the
    same four beats.
    """
    out: list[tuple[str, list[str]]] = []
    for family in kit.families():
        if not family.startswith("shorts/"):
            continue
        rows: list[str] = []
        for key in kit.family(family):
            asset = kit.get(key)
            if asset is None:
                continue
            leaf = key.rsplit("/", 1)[-1]
            bits: list[str] = []
            if asset.title:
                bits.append(asset.title)
            if asset.frame_count > 1:
                bits.append(f"{asset.frame_count}f {asset.playback}")
            if asset.slots:
                # Slot NAMES, because they are what the writer types after the
                # `=`, and the first slot's note, because "what goes in it" is
                # the thing the name does not say.
                names = ", ".join(s.name for s in asset.slots)
                note = next((s.note for s in asset.slots if s.note), "")
                bits.append(f"takes {names}" + (f" ({note})" if note else ""))
            rows.append(f"{leaf}" + (f" — {'; '.join(bits)}" if bits else ""))
        if rows:
            out.append((family.split("/", 1)[1], rows))
    return out


def _group(title: str, keys: list[str], *, note: str = "") -> list[str]:
    if not keys:
        return []
    lines = [f"{title}:" + (f"  ({note})" if note else "")]
    # Wrapped rather than one-per-line: this is a menu, and a 762-line menu
    # would swamp the prompt it is meant to inform.
    row: list[str] = []
    for k in keys:
        row.append(k)
        if sum(len(x) + 2 for x in row) > 88:
            lines.append("  " + ", ".join(row))
            row = []
    if row:
        lines.append("  " + ", ".join(row))
    return lines


def kit_catalog(settings: Settings, *, fmt: str = "long") -> str:
    """Every kit key the writer may reference, generated from the manifest.

    Read off disk at prompt-fill time on purpose: a hand-maintained list drifts
    the moment artwork is added or an export changes, and the failure mode of
    drift is a script full of keys that validate-then-fail. Validation already
    rejects unknown keys — this stops them being invented.

    Terse by design. Grouped keys with a `use when` only for the concepts,
    because those are the ones whose names don't say what they're for.
    """
    from pipeline.host import HOST_BANKS  # noqa: F401  (used below)
    from pipeline.kit import load_kit

    kit = load_kit(settings.assets_dir)
    if not len(kit):
        return ("(design kit not ingested — run scripts/ingest_kit.py. "
                "Until then use [ASSET] for anything the kit would have covered.)")

    from pipeline.models import KIT_TAG_FAMILIES, TagType

    out: list[str] = []
    out += _group("[TERM: key] — explainer cards that EXIST (only these)",
                  _leaves(kit, KIT_TAG_FAMILIES[TagType.TERM], keep="term-",
                          drop_blanks=True))
    out += _group("[BIGNUM: key] — one-number cards",
                  _leaves(kit, KIT_TAG_FAMILIES[TagType.BIGNUM],
                          keep="big-number-", drop_blanks=True))
    out.append("  A blank layout exists for both, so an unlisted term or number "
               "still gets a card — the text you write is composited into it.")
    out += _group("[TABLE: kind]", _leaves(kit, KIT_TAG_FAMILIES[TagType.TABLE]))
    out += _group("[ALERT: kind]", _leaves(kit, KIT_TAG_FAMILIES[TagType.ALERT]))
    # The shorts families resolve as [PROP] too, but they get the detailed
    # section below — listing them twice turns a menu into a wall.
    out += _group("[PROP: key] — object cutaways and concept illustrations",
                  _leaves(kit, tuple(f for f in KIT_TAG_FAMILIES[TagType.PROP]
                                     if not f.startswith("shorts/"))))

    concepts = _leaves(kit, "concepts")
    if concepts:
        out.append("Concept illustrations — use when:")
        for c in concepts:
            use = _CONCEPT_USE.get(c, "")
            out.append(f"  - {c}" + (f" — {use}" if use else ""))

    if fmt == "short":
        # The shorts batch, in full. 51 assets, 74 fillable slots, 27 of them
        # animated — the writer names a beat and the renderer plays it. This
        # is the part the short prompt has never carried.
        families = _shorts_families(kit)
        if families:
            out.append("")
            out.append(
                "SHORT BEAT LIBRARY — name one as [PROP: key = value] and the "
                "renderer plays it, composites your figure into the drawing, "
                "and holds it for the beat.")
            out.append(
                "  [PROP: crushed-flat = -41%]                         one slot")
            out.append(
                "  [PROP: see-saw-two-numbers = heavy:$1.1B, light:$40M]  named")
            out.append(
                "  [PROP: numbers-raining = -8%, -12%, -3%]            in order")
            out.append(
                "  WITHOUT the `= value` the drawing renders with its boxes "
                "EMPTY. Always give a figure.")
            for name, rows in families:
                out.append(f"  {name}:")
                for row in rows:
                    out.append(f"    - {row}")
    else:
        out += _group("Chapter kits with dedicated artwork", _chapter_kits(kit),
                      note="name a chapter close to one of these and it gets "
                           "its own visuals")

    out += _group("Host shots (the renderer places these; listed so you know "
                  "what he can do)",
                  sorted({k.rsplit("/", 1)[-1] for role in HOST_BANKS.values()
                          for k in role}))
    out += _group("Host reactions", _leaves(kit, "mascot"))
    out.append(
        "\nAnything genuinely NOT in the lists above: use [ASSET: slug] and append "
        "a Claude Design prompt for it. That is the escape hatch for a diagram the "
        "kit doesn't have — not a shortcut past a key that does exist, and it BLOCKS "
        "the render until the file is delivered.")
    return "\n".join(out)


# The craft rules that were implicit in the templates. Stated once, injected
# into every writing prompt, so they cannot drift between the four of them.
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
        r["{{doodle_catalog}}"] = doodle_catalog(settings)
        r["{{meme_catalog}}"] = meme_catalog(settings)
        r["{{broll_palette}}"] = broll_catalog()
        r["{{kit_catalog}}"] = kit_catalog(settings, fmt="short")
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
        r["{{doodle_catalog}}"] = doodle_catalog(settings)
        r["{{meme_catalog}}"] = meme_catalog(settings)
        r["{{broll_palette}}"] = broll_catalog()
        r["{{kit_catalog}}"] = kit_catalog(settings, fmt="long")
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
        r["{{doodle_catalog}}"] = doodle_catalog(settings)
        r["{{meme_catalog}}"] = meme_catalog(settings)
        r["{{broll_palette}}"] = broll_catalog()
        r["{{kit_catalog}}"] = kit_catalog(settings, fmt="short")
        r["{{craft_rules}}"] = EXPRESSIVITY_AND_PACING
        r["{{peer_percentiles}}"] = (
            peer_percentiles_block(data) if data is not None else "(n/a in macro mode)"
        )
    else:
        raise ValueError(f"unknown prompt fmt {fmt!r}")

    for k, v in r.items():
        text = text.replace(k, v)
    return text
