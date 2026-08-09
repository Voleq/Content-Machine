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

import re
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

    A card whose baked furniture cannot be stripped is never offered. The
    renderer refuses to place one, so offering it would steer a writer into a
    blocking gate finding — the catalog and the renderer have to agree about
    what exists, in both directions.
    """
    prefixes = (prefix,) if isinstance(prefix, str) else tuple(prefix)
    out: list[str] = []
    for fam in prefixes:
        head = fam.rstrip("/") + "/"
        for name in kit.family(fam):
            leaf = name[len(head):]
            if keep and not leaf.startswith(keep):
                continue
            if not kit.placeable(name):
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
    """Chapter kits that ship dedicated, placeable artwork.

    A family whose every drawing keeps its baked furniture has nothing the
    renderer will place, so promising "name a chapter close to one of these and
    it gets its own visuals" would be false — four families are in exactly that
    state until Design redraws them.
    """
    return sorted(
        f.split("/", 1)[1] for f in kit.families()
        if f.startswith("chapters/")
        and any(kit.placeable(k) for k in kit.family(f))
    )


# --------------------------------------------------------------------------
# The beat library, grouped by SITUATION rather than by folder.
# --------------------------------------------------------------------------
# The catalog used to list the shorts batch family by family — grouped, that
# is, by the folder the artwork happens to live in. That says what exists and
# never says when to reach for it, and a writer handed 51 options with no
# selection rule reaches for the four beats it already knows. The showcase
# render is the proof: 17 of 442 assets, one beat-library scene.
#
# So the headings below are situations, and every one of them is DERIVED. Each
# rule reads registry metadata that already exists — slot count, slot names,
# frameCount, aspect, the title — so artwork added tomorrow is filed the day it
# lands and nothing here needs a code change. That property is the generator's
# best one and a hand-maintained key -> situation table would cost it. An asset
# no rule can place is listed under the last heading rather than dropped.

SIT_DOC = "A DOCUMENT, a filing, a press release"
SIT_BECOMES = "A thing BECOMING another thing (animated)"
SIT_FULL_HEIGHT = "Fills the FULL HEIGHT — drawn to be the 9:16 frame"
SIT_MANY = "MANY figures at once"
SIT_TWO = "TWO figures weighed against each other"
SIT_SCALE = "ONE figure, absurd in scale next to him"
SIT_BAD = "ONE figure, and it went the wrong way"
SIT_GOOD = "ONE figure, and it went the right way"
SIT_REST = "Everything else in the beat library"

# Display order, which is also the order an asset is TESTED against them: the
# first rule that matches wins, so this tuple is the precedence. Situation
# beats format — `b-filings-stack` is a filing that happens to be 9:16, and a
# writer looking for a filing has to find it under filings.
BEAT_SITUATIONS: tuple[str, ...] = (
    SIT_DOC, SIT_BECOMES, SIT_FULL_HEIGHT, SIT_MANY, SIT_TWO,
    SIT_SCALE, SIT_BAD, SIT_GOOD, SIT_REST,
)

# What each heading is FOR, in the writer's terms. The heading names the shape
# of the beat; this says when to reach for the shape.
_SIT_NOTE = {
    SIT_DOC: "the evidence is paper",
    SIT_BECOMES: "the beat IS the change — play it, don't hold it",
    SIT_FULL_HEIGHT: "no letterboxing, no desk behind it — one per short",
    SIT_MANY: "a whole row of figures at once, not one",
    SIT_TWO: "this against that",
    SIT_SCALE: "the size of the number IS the joke",
    SIT_BAD: "down, red, buried",
    SIT_GOOD: "up, green, on top of it",
    SIT_REST: "no heuristic placed these — read the titles",
}

# Wording that says what a beat is doing, matched against the asset's key leaf
# and its title. Deliberately NOT against the slot notes: those carry rendering
# instructions ("scale down 24% per frame"), and a note like that reads as a
# down beat to any word match while describing the balloon that INFLATES.
_DOC_RE = re.compile(
    r"\b(doc\w*|filing\w*|paper\w*|page\w*|press release|redact\w*|memo"
    r"|prospectus|10 [kq])\b")
_SCALE_RE = re.compile(
    r"\b(atlas|tiny|dwarf\w*|tower\w*|giant|enormous|huge|ruler|measur\w*"
    r"|colossal|microscop\w*)\b")
# `red` and `up` are whole-word on purpose: `\bred` also matches "redacting",
# and `\bup` also matches "uphill", which is a grind, not a rally.
_DOWN_RE = re.compile(
    r"\b(down|fall\w*|fell|drop\w*|crush\w*|cliff|hole|collaps\w*|red|sink\w*"
    r"|under|buried|bury|flat|deflat\w*|melt\w*|toppl\w*|snap\w*|tear\w*|torn"
    r"|evaporat\w*|crumpl\w*|uphill|saw\w*|cut|sweep\w*|drag\w*|tug|war"
    r"|fight\w*|struggl\w*|loss\w*|wrong|negative|miss)\b")
_UP_RE = re.compile(
    r"\b(up|rise|rising|ride|riding|climb\w*|green|grow\w*|inflat\w*|lift\w*"
    r"|sit\w*|win\w*|gain\w*|beat|record)\b")


def _beat_words(asset) -> str:
    """An asset's key leaf and title, normalised for word matching."""
    leaf = asset.key.rsplit("/", 1)[-1]
    return f"{leaf} {asset.title}".lower().replace("-", " ")


def _beat_situation(asset) -> str:
    """Which situation heading a beat-library asset belongs under.

    First match wins, in :data:`BEAT_SITUATIONS` order, so every asset lands
    under exactly one heading and the listing is a partition of the library.
    """
    text = _beat_words(asset)
    if _DOC_RE.search(text):
        return SIT_DOC
    # The family is what the prompt names; the frame count is what makes the
    # rule survive a transformation exported into some other folder. Every
    # 8-frame asset in the kit today is one of these.
    if "transformations" in asset.family or asset.frame_count >= 8:
        return SIT_BECOMES
    if asset.aspect == "9:16":
        return SIT_FULL_HEIGHT
    if len(asset.slots) >= 3:
        return SIT_MANY
    if len(asset.slots) == 2:
        return SIT_TWO
    if len(asset.slots) == 1:
        if _SCALE_RE.search(text):
            return SIT_SCALE
        if _DOWN_RE.search(text):
            return SIT_BAD
        if _UP_RE.search(text):
            return SIT_GOOD
    return SIT_REST


def _beat_row(asset) -> str:
    """One asset's line: the key the writer types, then what it is."""
    bits: list[str] = []
    if asset.title:
        bits.append(asset.title)
    if asset.frame_count > 1:
        bits.append(f"{asset.frame_count}f {asset.playback}")
    if asset.slots:
        # Slot NAMES, because they are what the writer types after the `=`,
        # and the first slot's note, because "what goes in it" is the thing
        # the name does not say.
        names = ", ".join(s.name for s in asset.slots)
        note = next((s.note for s in asset.slots if s.note), "")
        bits.append(f"takes {names}" + (f" ({note})" if note else ""))
    leaf = asset.key.rsplit("/", 1)[-1]
    return f"{leaf}" + (f" — {'; '.join(bits)}" if bits else "")


def _beat_library(kit, *, aspects: tuple[str, ...]) -> list[tuple[str, list[str]]]:
    """`(situation heading, rows)` for the beat library, headings in order.

    Only the shorts families ``[PROP]`` actually resolves against are listed.
    ``shorts/the-world`` (the desk) and ``shorts/open-close`` (the signature
    open and close) are not among them — the renderer places those itself —
    and the catalog offered all six as `[PROP:]` keys that resolve to nothing.
    The catalog and the resolver have to agree in both directions.
    """
    from pipeline.models import KIT_TAG_FAMILIES, TagType

    grouped: dict[str, list[str]] = {}
    for family in KIT_TAG_FAMILIES[TagType.PROP]:
        if not family.startswith("shorts/"):
            continue
        for key in kit.family(family):
            asset = kit.get(key)
            if asset is None or not kit.placeable(key):
                continue
            if asset.aspect not in aspects:
                continue
            grouped.setdefault(_beat_situation(asset), []).append(_beat_row(asset))
    return [(sit, sorted(grouped[sit])) for sit in BEAT_SITUATIONS if grouped.get(sit)]


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

    # The beat library — drawings built to carry a figure, grouped by the
    # situation they are FOR. The whole thing was gated behind fmt == "short",
    # which cost the LONG 38 drawings for no reason anyone had stated: the 1:1
    # half is square, so it composites into 16:9 whole, with no crop. Only the
    # 9:16 half is genuinely short-only — those were drawn to BE the vertical
    # frame, and contain-fitting one into 16:9 is a letterboxed stamp.
    library = _beat_library(kit, aspects=("1:1", "9:16") if fmt == "short"
                            else ("1:1",))
    if library:
        out.append("")
        out.append(
            ("SHORT BEAT LIBRARY" if fmt == "short" else "BEAT LIBRARY")
            + " — name one as [PROP: key = value] and the renderer plays it, "
            "composites your figure into the drawing, and holds it for the "
            "beat. Grouped by WHAT THE BEAT IS DOING; pick the situation "
            "first, the drawing second.")
        out.append(
            "  [PROP: crushed-flat = -41%]                         one slot")
        out.append(
            "  [PROP: see-saw-two-numbers = heavy:$1.1B, light:$40M]  named")
        out.append(
            "  [PROP: numbers-raining = -8%, -12%, -3%]            in order")
        out.append(
            "  WITHOUT the `= value` the drawing renders with its boxes "
            "EMPTY. Always give a figure.")
        if fmt != "short":
            out.append(
                "  These are square, so they arrive in the 16:9 frame whole "
                "and uncropped. The full-height half of the library is "
                "9:16 and stays short-only.")
        for situation, rows in library:
            note = _SIT_NOTE.get(situation, "")
            out.append(f"  {situation}:" + (f"  ({note})" if note else ""))
            for row in rows:
                out.append(f"    - {row}")

    if fmt != "short":
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
    age = _days_since(thesis.recorded_at)
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
        r["{{doodle_catalog}}"] = doodle_catalog(settings)
        r["{{meme_catalog}}"] = meme_catalog(settings)
        r["{{broll_palette}}"] = broll_catalog()
        r["{{scribble_styles}}"] = scribble_styles(settings)
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
        r["{{scribble_styles}}"] = scribble_styles(settings)
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
        r["{{scribble_styles}}"] = scribble_styles(settings)
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
