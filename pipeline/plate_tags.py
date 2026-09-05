"""`[PLATE: …]` — the director names the plate and writes what goes on it.

    [PLATE: numbers-sheet-4r-16x9 | unit=$M | head=2021,2022,2023,2024,2025,LTM
      | label-1=Revenue | row-1=5.6,9.8,6.1,6.7,7.4,13.2 ]

THE RENDERER NEVER PICKS A PLATE AND NEVER COMPUTES A VALUE. Those are the two
halves of the same rule, and both used to be broken in the same direction: the
bot chose its own artwork from whatever the kit happened to ship, and then
filled it from whatever the data export happened to hold. The result was a video
whose visuals nobody had decided on. Here the director decides, the tag carries
it, and this module's only job is to check that what was written can be put in
the slots the plate actually declares.

Three things are rejected, and each of them is a frame that would otherwise ship
wrong rather than fail:

* **an unknown plate** — a name that resolves to nothing draws nothing, and an
  empty area on screen looks like a design choice.
* **an undeclared slot** — the text goes nowhere. Silently.
* **a row whose length disagrees with the header** — five figures under six
  period heads is a table that lies about which year each number belongs to.

The compact forms exist because a six-row sheet is 55 slots and nobody writes 36
`cell-R-C=` pairs by hand. They expand against the slots the plate declares, so
the expansion cannot invent a slot that is not there:

    head=a,b,c,d,e,f   ->  head-1 … head-6
    row-3=1,2,3,4,5,6  ->  cell-3-1 … cell-3-6
    label-3=Revenue    ->  label-3          (already a slot name — verbatim)
    body=Margins fell, and stayed there     (verbatim: commas are content)

A key that names a declared slot the plate SETS TYPE IN is taken verbatim, which
is what keeps a comma inside prose from being read as a list separator. A key
naming a slot that takes no type — a plot area, a spark, a path — is read as the
series of figures the renderer draws through, and checked against the header.

**Not every value is a string.** `tables/multiples-strip`'s `marker-N` is a
region that takes a PAIR OF NUMBERS, and it is the first slot in the library
that does:

    marker-3 = t:0.82, median:0.41

`t` is 0 at the peer low and 1 at the peer high; `median` is the peer set's own
position on that same scale. Both are written by the director off the data —
the renderer computes neither, the same rule as every other value here.

Three things follow, and each is checked below:

* **`t` outside 0–1 is a real reading and passes through unclamped.** The peer
  range is p10–p90, so a subject priced above every peer lands at t > 1: that is
  the most quotable row on the plate, and clamping it in the parser to be safe
  destroys the finding. The renderer clamps the DOT to the end tick and draws a
  chevron past it; the number itself is never touched.
* **The pair is named, never positional.** `t` and `median` are on one scale and
  look alike, so `marker-3 = 0.82, 0.41` would be two numbers whose order
  nobody could check — and getting them the wrong way round draws a perfectly
  plausible row that says the opposite thing.
* **Neither half is optional.** On 9:16 especially: the portrait strip has no
  median COLUMN, so the tick `rangeMark` puts on the rail *is* the peer number.
  Omit it and the short shows a position with nothing to be positioned against.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pipeline.plates import PERIOD_COUNT, Plate, Registry

# `[PLATE: name | k=v | k=v]`. The parts split on `|`; the first is the plate
# name, the rest are assignments. Newlines inside the tag are folded, so a
# director may break a long table across lines the way the example does.
_PART_SPLIT = re.compile(r"\s*\|\s*")
_ASSIGN = re.compile(r"^([a-zA-Z][a-zA-Z0-9_-]*)\s*=\s*(.*)$", re.DOTALL)

# `row-3` / `cell-3` -> the row's figures, spread across that row's cells.
_ROW_RE = re.compile(r"^(?:row|cells?)-(\d+)$")

# A `<stem>-<n>` family of slots, for the generic list expansion.
_INDEXED_RE = re.compile(r"^(.*)-(\d+)$")

# `t:0.82` / `median:-0.4` — one half of a marker pair. Named rather than
# positional on purpose: see the module docstring.
_MARKER_PART = re.compile(r"^(t|median)\s*:\s*(-?(?:\d+\.?\d*|\.\d+))$", re.I)
_MARKER_KEYED = re.compile(r"^\s*(t|median)\s*:", re.I)


@dataclass(frozen=True)
class MarkerValue:
    """Where the subject sits on a peer range, and where the peer set does.

    Both on ONE scale: 0 is the peer low (p10), 1 is the peer high (p90).
    Neither is a percentile — a rank-based number computes `median` to 0.5 on
    every row, which puts every median tick dead centre and kills the one
    comparison the plate exists to make. `Peers!I` and `Peers!J` are the two
    columns that carry these.
    """

    t: float
    median: float

    @property
    def off_range(self) -> bool:
        """Whether the subject is outside the peer range — a READING, not an error."""
        return not 0.0 <= self.t <= 1.0

    @property
    def canonical(self) -> str:
        """The wire form. Values travel as text through the script model; this
        is the one spelling they travel in, so a round-trip is lossless."""
        return f"t:{self.t:g},median:{self.median:g}"

    def __str__(self) -> str:                     # noqa: D105
        return self.canonical


def looks_like_marker(raw: str) -> bool:
    """Whether this value was WRITTEN as a marker pair, well-formed or not.

    Shape, not validity: it is what lets a numeric pair bound to a text slot be
    reported as the wrong kind of value rather than typeset as the literal
    string "t:0.82,median:0.41".
    """
    return any(_MARKER_KEYED.match(part) for part in str(raw or "").split(","))


def parse_marker(raw: str) -> tuple[MarkerValue | None, str]:
    """`"t:0.82, median:0.41"` -> `(MarkerValue, "")`, else `(None, why)`.

    NOTHING IS CLAMPED HERE. `t = 1.4` parses to 1.4 and reaches the renderer
    as 1.4.
    """
    got: dict[str, float] = {}
    for part in str(raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        m = _MARKER_PART.match(part)
        if not m:
            return None, (
                f"{part!r} is not one of `t:<number>` or `median:<number>`")
        key = m.group(1).lower()
        if key in got:
            return None, f"{key} is written twice"
        got[key] = float(m.group(2))
    missing = [k for k in ("t", "median") if k not in got]
    if missing:
        return None, f"no {' and no '.join(missing)}"
    return MarkerValue(t=got["t"], median=got["median"]), ""


def marker_slots(plate: Plate) -> list[str]:
    """Every slot on this plate that takes a `{t, median}` pair, in row order."""
    out = [(int(m.group(2)), n) for n, s in plate.slots.items()
           if _is_marker(s) and (m := _INDEXED_RE.match(n))]
    return [n for _, n in sorted(out)]


def _is_marker(slot) -> bool:
    """Whether the KIT says this slot is a range mark.

    Asked of the manifest — the role plus the renderer it names — and not of a
    list of slot names kept here, which is the mistake the whole registry is
    built to avoid.
    """
    return bool(slot.region
                and (slot.role == "marker"
                     or slot.renderer.rsplit(".", 1)[-1] == "rangeMark"))


def _draws_a_series(slot) -> bool:
    """Whether this region is one the director hands a run of figures.

    `series.rowBars`, `series.cycleArc`, `series.sparkBars` and the bare
    `plot-area` are drawn THROUGH a series. `series.rangeMark` is not — it
    takes two named numbers — and a figure, a mouth or a host anchor is not
    drawn from data at all.
    """
    if _is_marker(slot):
        return False
    return bool(slot.renderer) or slot.role in ("plot-area", "bars", "path", "spark")


def _never_typeset(slot) -> bool:
    """Whether typing a string into this slot is always wrong.

    A REGION IS NOT AUTOMATICALLY A NO-TYPE SLOT, and this is the trap. Eight
    slots in the library are `region: true` AND declare a typeRole —
    `cycles/cycle-frame`'s `trough` and `charts/line-dense`'s three marks — and
    they are regions for a different reason: only the data knows *where* the
    low point is, so the box floats, but a figure absolutely goes in it. The
    kit answers this with its typeRoles table, exactly as it answers it for
    every other slot; reading `region` alone would silently drop those eight.
    """
    return bool(slot.region) and not slot.is_text


@dataclass
class PlateFill:
    """A resolved `[PLATE]` tag: which plate, and what goes in each slot."""

    key: str                                   # the registry key
    name: str                                  # what the director wrote
    values: dict[str, str] = field(default_factory=dict)   # slot -> text
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def resolve_name(reg: Registry, name: str, aspect: str = "") -> str | None:
    """The registry key for what the director wrote, or None.

    A director writes `numbers-sheet-4r-16x9`, not `tables/numbers-sheet-4r-16x9`
    — the family is the kit's filing system, not something a writer should have
    to carry. A bare name that is unique across families resolves; one that is
    ambiguous does not, and says so rather than picking.
    """
    name = name.strip()
    if not name:
        return None
    if name in reg.assets:
        return name
    hits = [k for k in reg.assets if k.split("/", 1)[1] == name]
    if len(hits) == 1:
        return hits[0]
    if hits:
        return None                      # ambiguous — the caller reports it
    # A name with no aspect suffix, when the shot has an aspect: `both-true`
    # in a 16:9 chapter is `structure/both-true-16x9`.
    if aspect:
        stem_hits = [k for k in reg.assets
                     if k.split("/", 1)[1] == f"{name}-{aspect}"]
        if len(stem_hits) == 1:
            return stem_hits[0]
    return None


def parse_plate_payload(payload: str) -> tuple[str, list[tuple[str, str]]]:
    """`"name | k=v | k=v"` -> `("name", [(k, v), …])`. No registry needed."""
    folded = " ".join(payload.split())
    parts = [p for p in _PART_SPLIT.split(folded) if p.strip()]
    if not parts:
        return "", []
    name = parts[0].strip()
    assigns: list[tuple[str, str]] = []
    for part in parts[1:]:
        m = _ASSIGN.match(part.strip())
        if m:
            assigns.append((m.group(1), m.group(2).strip()))
        else:
            assigns.append(("", part.strip()))     # malformed; reported later
    return name, assigns


def _head_count(plate: Plate) -> int:
    """How many period heads this plate declares."""
    return sum(1 for n in plate.slots if _INDEXED_RE.match(n)
               and _INDEXED_RE.match(n).group(1) == "head")


def _column_count(plate: Plate) -> int:
    """How many periods this plate is authored for.

    Six, everywhere it matters: four fiscal years, the last full year and LTM.
    Read off the declared slots rather than assumed, because `charts/line-dense`
    is deliberately four heads over many observations.
    """
    return _head_count(plate) or plate.columns or PERIOD_COUNT


def _indexed_family(plate: Plate, stem: str) -> list[str]:
    """`"head"` -> `["head-1", …]`, in index order, only where they exist."""
    out: list[tuple[int, str]] = []
    for n in plate.slots:
        m = _INDEXED_RE.match(n)
        if m and m.group(1) == stem:
            out.append((int(m.group(2)), n))
    return [n for _, n in sorted(out)]


def _row_cells(plate: Plate, row: int) -> list[str]:
    """`cell-3-1 … cell-3-6`, in column order."""
    out: list[tuple[int, str]] = []
    for n in plate.slots:
        parts = n.split("-")
        if len(parts) == 3 and parts[0] == "cell" and parts[1] == str(row):
            try:
                out.append((int(parts[2]), n))
            except ValueError:
                continue
    return [n for _, n in sorted(out)]


def build_fill(reg: Registry, payload: str, *, aspect: str = "",
               chapter_type: str = "") -> PlateFill:
    """Resolve a `[PLATE]` payload against the registry. Never raises."""
    name, assigns = parse_plate_payload(payload)
    key = resolve_name(reg, name, aspect)
    fill = PlateFill(key=key or "", name=name)

    if not name:
        fill.problems.append("[PLATE] has no plate name")
        return fill
    if key is None:
        ambiguous = [k for k in reg.assets if k.split("/", 1)[1] == name]
        if ambiguous:
            fill.problems.append(
                f"[PLATE: {name}] is ambiguous — it is "
                f"{' and '.join(sorted(ambiguous))}. Name the family.")
        else:
            near = reg.nearest(name) or reg.nearest(f"tables/{name}")
            fill.problems.append(
                f"[PLATE: {name}] is not a plate in the kit"
                + (f". Did you mean {near.split('/', 1)[1]}?" if near else "."))
        return fill

    plate = reg.assets[key]

    # The TYPE decides which plates a chapter may use. Not the title, which is
    # free text and may repeat, and not the renderer, which never picks.
    if chapter_type and not reg.chapter_allows(chapter_type, key):
        fill.problems.append(
            f"[PLATE: {name}] is not available to a {chapter_type} chapter")

    if aspect and plate.aspect and plate.aspect != aspect:
        # THERE IS NO PORTRAIT BRIDGE, and this is where that is enforced.
        # `structure/multiple-bridge` ships 16:9 only: a trailing-to-forward
        # walk is three figures and two connectors, and it does not belong in
        # seventy-five seconds. The generic message below already refuses it —
        # this names it, because "is 16x9 and this is a 9x16 cut" reads like a
        # missing file rather than a decision.
        only_aspect = not any(
            k != key and reg.assets[k].aspect == aspect
            for k in reg.assets
            if k.rsplit("-", 1)[0] == key.rsplit("-", 1)[0])
        fill.problems.append(
            f"[PLATE: {name}] is {plate.aspect} and this is a {aspect} cut — "
            f"9:16 is a re-author, never a crop"
            + (f". {plate.name.rsplit('-', 1)[0]} ships {plate.aspect} only; "
               f"there is no {aspect} variant of it to route to."
               if only_aspect else ""))

    cols = _column_count(plate)
    header_len = 0

    for k, raw in assigns:
        if not k:
            fill.problems.append(
                f"[PLATE: {name}] has a part with no `slot=value`: {raw!r}")
            continue

        named = plate.slots.get(k)

        # 0. A RANGE MARK TAKES A PAIR OF NUMBERS, and only a pair of numbers.
        #
        #    This has to come first, and specifically ahead of the series
        #    branch below, because `marker-3=0.82,0.41` is two comma-separated
        #    figures: read as a series it validates clean and draws a mark at
        #    an arbitrary place, which is the exact failure this shape
        #    introduces.
        if named is not None and _is_marker(named):
            pair, why = parse_marker(raw)
            if pair is None:
                detail = f" The kit says: {named.note}" if named.note else ""
                fill.problems.append(
                    f"[PLATE: {name}] {k}= is a region, not a text slot: it "
                    f"takes `t:<number>, median:<number>` from the data and "
                    f"never a string, and this one has {why}. `t` is 0 at the "
                    f"peer low and 1 at the peer high; `median` is the peer "
                    f"set on the same scale, and on a 9:16 strip it is the "
                    f"only place the peer number reaches the plate at all."
                    + detail)
                continue
            # UNCLAMPED, DELIBERATELY. The peer range is p10-p90, so a subject
            # priced above every peer reads t > 1 — the most quotable row on
            # the plate. The renderer clamps the dot to the end tick and draws
            # a chevron past it; the reading itself is never touched.
            fill.values[k] = pair.canonical
            if pair.off_range:
                fill.warnings.append(
                    f"[PLATE: {name}] {k}= t is {pair.t:g}, outside the peer "
                    f"range — drawn on the end tick with a chevron past it. "
                    f"This is a reading, not a mistake: say it in the line.")
            continue

        # 0b. A REGION THE KIT SETS NO TYPE IN IS NEVER TYPESET.
        #
        #     Asked of the manifest, never of a list here: eight regions in the
        #     library DO declare a typeRole and do take a figure. The check is
        #     "the kit gives this slot no type", not "the slot is a region".
        if (named is not None and _never_typeset(named)
                and not named.is_band and "," not in raw):
            detail = f" The kit says: {named.note}" if named.note else ""
            fill.problems.append(
                f"[PLATE: {name}] {k}= is a region the plate sets no type in, "
                f"so {raw!r} would be typeset into an area reserved for a "
                f"drawing.{detail}")
            continue

        # 0c. A NUMERIC PAIR IN A TEXT SLOT is the same mistake mirrored.
        if named is not None and named.is_text and looks_like_marker(raw):
            markers = marker_slots(plate) or ["(none — this plate has no rail)"]
            fill.problems.append(
                f"[PLATE: {name}] {k}= is a text slot and {raw!r} is a range "
                f"mark. The pair goes on {markers[0].rsplit('-', 1)[0]}-N; "
                f"{k} takes the figure as it is written on screen.")
            continue

        # 1. An exact slot name that TAKES TYPE is taken VERBATIM. This is what
        #    lets prose keep its commas — `body=Margins fell, and stayed there`
        #    is one value.
        if named is not None and named.is_text:
            fill.values[k] = raw
            if k == "head":
                header_len = len([v for v in raw.split(",")])
            continue

        # 2. A DATA REGION takes the figures it draws through.
        #
        #    `path=14.2,9.1,3.1,4.8,6.2,7.8` on a cycle frame. The plate
        #    reserves the region and declares which renderer fills it; it has no
        #    per-period slot for the intervening figures, because they are a
        #    shape rather than type. The director still writes every one of
        #    them — this is not the renderer computing a series, it is the
        #    renderer being handed one.
        #
        #    This has to come AFTER the verbatim branch and be reachable from
        #    it: `path` is a slot name, so a branch that took every slot name
        #    verbatim swallowed the series and none of the checks below ever
        #    ran — a five-figure path against a six-period header validated
        #    clean and drew a line one period short.
        region = named
        if region is not None and not region.is_band and _draws_a_series(region):
            vals = [v.strip() for v in raw.split(",")]
            if len(vals) < 2:
                # Covers both shapes of this mistake: a one-point series, and a
                # value written to a slot that takes no type and has no
                # renderer either. The kit's own note on the slot says which.
                detail = f" The kit says: {region.note}." if region.note else ""
                fill.problems.append(
                    f"[PLATE: {name}] {k}= is not a text slot — it takes the "
                    f"figures a renderer draws through, and {raw!r} is not a "
                    f"series.{detail}")
                continue
            # THE HEADS ARE NOT ALWAYS ONE PER FIGURE, AND THE PLATE SAYS SO.
            #
            # `charts/line-dense` declares `columns: 6` and four heads: the
            # heads are axis labels spanning the series, not a label per
            # observation, which is the whole point of a dense chart — sixty
            # daily closes under four dates. Every per-period plate declares as
            # many heads as it has columns, so the two agreeing is the signal
            # that a figure belongs under a head. Checking regardless refused a
            # 61-point price series for not being six points long.
            per_period = _head_count(plate) == (plate.columns or PERIOD_COUNT)
            if per_period and header_len and len(vals) != header_len:
                fill.problems.append(
                    f"[PLATE: {name}] {k}= has {len(vals)} figures against "
                    f"{header_len} period heads")
                continue
            fill.values[k] = ",".join(vals)
            continue

        # 2b. A band slot named directly just lights, like `band=N` below.
        if region is not None and region.is_band:
            fill.values[k] = raw
            continue

        # 2c. A region left over here draws neither type nor a series: it is a
        #     figure, a pair of eyes, a media well, an anchor. Nothing the
        #     director writes belongs in one, and a comma in the value is not a
        #     licence — `figure=he, seated` is prose, not a series.
        if region is not None and _never_typeset(region):
            detail = f" The kit says: {region.note}" if region.note else ""
            fill.problems.append(
                f"[PLATE: {name}] {k}= is a region the plate reserves for a "
                f"drawing, and it declares no renderer to draw {raw!r} "
                f"through.{detail}")
            continue

        # 3. `band=N` lights row N. A band is not a text box — it is the row
        #    highlight, and the only sanctioned way to emphasise a row — so it
        #    takes the row NUMBER rather than a value. Writing `band-2=1` put a
        #    literal "1" on top of the lit row.
        if k == "band":
            wanted = [v.strip() for v in raw.split(",") if v.strip()]
            bands = _indexed_family(plate, "band")
            if not bands:
                fill.problems.append(
                    f"[PLATE: {name}] has no row bands to light")
                continue
            for wv in wanted:
                target = f"band-{wv}"
                if target not in plate.slots:
                    fill.problems.append(
                        f"[PLATE: {name}] band={wv} — there is no row {wv} "
                        f"(the plate has {len(bands)} rows)")
                    continue
                fill.values[target] = wv
            if len(wanted) > 1:
                fill.warnings.append(
                    f"[PLATE: {name}] lights {len(wanted)} rows at once — a "
                    f"highlight that covers half the sheet highlights nothing")
            continue

        # 4. `row-N` spreads across that row's cells.
        m = _ROW_RE.match(k)
        if m:
            row = int(m.group(1))
            cells = _row_cells(plate, row)
            if not cells:
                rows = sorted({int(n.split("-")[1]) for n in plate.slots
                               if n.startswith("cell-") and len(n.split("-")) == 3})
                fill.problems.append(
                    f"[PLATE: {name}] has no row {row} — it has "
                    + (f"rows {rows[0]}–{rows[-1]}" if rows else "no rows"))
                continue
            vals = [v.strip() for v in raw.split(",")]
            want = header_len or len(cells)
            if len(vals) != want:
                fill.problems.append(
                    f"[PLATE: {name}] row-{row} has {len(vals)} figures against "
                    f"{want} period heads — a row that does not match its header "
                    f"puts every figure under the wrong year")
                continue
            if len(vals) != len(cells):
                fill.problems.append(
                    f"[PLATE: {name}] row-{row} has {len(vals)} figures and the "
                    f"plate declares {len(cells)} cells in that row")
                continue
            for cell, v in zip(cells, vals):
                fill.values[cell] = v
            continue

        # 5. A list across an indexed family: `head=…` -> head-1 … head-N.
        family = _indexed_family(plate, k)
        if family:
            vals = [v.strip() for v in raw.split(",")]
            if len(vals) > len(family):
                fill.problems.append(
                    f"[PLATE: {name}] {k}= has {len(vals)} values and the plate "
                    f"declares {len(family)} {k} slots")
                continue
            for slot, v in zip(family, vals):
                fill.values[slot] = v
            if k == "head":
                header_len = len(vals)
                if len(vals) != cols:
                    fill.warnings.append(
                        f"[PLATE: {name}] head= has {len(vals)} periods and the "
                        f"plate is authored for {cols} — four fiscal years, the "
                        f"last full year and LTM")
            continue

        # 6. Nothing it could be — but two shapes of "no slot" are worth
        #    naming, because both are a director reaching for a plate that
        #    cannot hold what they picked rather than a typo.
        if _capacity_problem(plate, k, fill, name):
            continue
        near = _nearest_slot(plate, k)
        fill.problems.append(
            f"[PLATE: {name}] has no slot {k!r}"
            + (f" — did you mean {near!r}?" if near else
               f" (it declares {_slot_summary(plate)})"))

    _warn_unfilled(plate, fill)
    return fill



def _capacity_problem(plate: Plate, k: str, fill: "PlateFill", name: str) -> bool:
    """Report `k` as over capacity or as a column this aspect dropped. True if reported.

    Both are the same director error in two shapes — a plate picked for content
    it cannot hold — and both are silent in the worst way: `median-3` on a
    portrait strip is a peer figure that simply never reaches the screen, and
    `label-6` on a three-row plate is two metrics quietly missing from the cut.

    THE ROWS AND THE SLOT NAMES COME OFF THE MANIFEST, never off the landscape
    plate's list. `tables/multiples-strip-9x16` is a re-author with three rows
    AND one fewer column, so validating a portrait tag against the 16:9 slot
    names accepts four things that are not there.
    """
    m = _INDEXED_RE.match(k)
    stem = m.group(1) if m else k

    # A column this aspect does not have. The peer number still has to reach
    # the plate — through the marker's `median`, which is why that argument is
    # mandatory in 9:16 and optional nowhere else.
    # A column this aspect dropped ENTIRELY — not merely a row index past the
    # end of one. `median-7` on the LANDSCAPE strip is over capacity and the
    # row check below owns it; only a plate carrying no median slot at all has
    # dropped the column.
    if stem in ("median", "head-median") or k == "head-median":
        has_median = any(n == "head-median" or n.rsplit("-", 1)[0] == "median"
                         for n in plate.slots)
        if not has_median and any(_is_marker(s) for s in plate.slots.values()):
            fill.problems.append(
                f"[PLATE: {name}] has no {k!r}: the {plate.aspect} strip is "
                f"three columns — metric, subject, rail — and carries no "
                f"median column at all. The peer number goes on the rail "
                f"instead, as the `median:` half of marker-N, which is "
                f"mandatory here for exactly this reason.")
            return True

    # A row above what the plate was authored for.
    if m and plate.rows:
        idx = int(m.group(2))
        if idx > plate.rows and any(
                n.rsplit("-", 1)[0] == stem for n in plate.slots):
            fill.problems.append(
                f"[PLATE: {name}] has no {k!r}: it is authored for "
                f"{plate.rows} rows and this asks for row {idx}. A "
                f"{plate.aspect or 'plate'} that holds {plate.rows} metrics "
                f"cannot be given more of them; pick the {plate.rows} that "
                f"carry the argument.")
            return True
    return False


def _nearest_slot(plate: Plate, key: str) -> str:
    import difflib
    names = list(plate.slots) + sorted(
        {m.group(1) for n in plate.slots if (m := _INDEXED_RE.match(n))})
    m = difflib.get_close_matches(key, names, n=1, cutoff=0.6)
    return m[0] if m else ""


def _slot_summary(plate: Plate) -> str:
    """The slot names, with indexed families collapsed: `head-1…6`."""
    stems: dict[str, list[int]] = {}
    plain: list[str] = []
    for n in sorted(plate.slots):
        m = _INDEXED_RE.match(n)
        if m:
            stems.setdefault(m.group(1), []).append(int(m.group(2)))
        else:
            plain.append(n)
    parts = list(plain)
    for stem, idx in sorted(stems.items()):
        parts.append(f"{stem}-{min(idx)}…{max(idx)}" if len(idx) > 1
                     else f"{stem}-{idx[0]}")
    return ", ".join(parts)


def _warn_unfilled(plate: Plate, fill: PlateFill) -> None:
    """Text slots the director left empty.

    A warning, never a failure: an empty cell in this library means NO DATA, and
    that is information. But a plate whose slots are ALL empty is a blank
    rectangle with a border, and that is never what anyone meant.
    """
    text_slots = set(plate.text_slots())
    if not text_slots:
        return
    filled = text_slots & set(fill.values)
    if not filled:
        fill.problems.append(
            f"[PLATE: {fill.name}] fills none of its {len(text_slots)} text "
            f"slots — it would render as an empty frame")
        return
    empty = text_slots - filled
    if empty and len(empty) <= 6:
        fill.warnings.append(
            f"[PLATE: {fill.name}] leaves {', '.join(sorted(empty))} empty")
    elif empty:
        fill.warnings.append(
            f"[PLATE: {fill.name}] leaves {len(empty)} of {len(text_slots)} "
            f"text slots empty")


def check_bound(reg: Registry, key: str, values: dict[str, str], *,
                chapter_type: str = "", aspect: str = "") -> PlateFill:
    """Re-check a tag that has ALREADY been resolved into slot values.

    The approval pass runs after the parser, and the parser has replaced the
    payload with the registry key — so re-parsing it there finds a name and no
    assignments, and every plate in the script gets reported as filling none of
    its slots. That warning was on every beat of a perfectly good script, which
    is how a validation layer teaches people to ignore it.
    """
    fill = PlateFill(key=key, name=key.split("/", 1)[-1], values=dict(values))
    plate = reg.get(key)
    if plate is None:
        fill.problems.append(f"[PLATE: {fill.name}] is not a plate in the kit")
        return fill
    if chapter_type and not reg.chapter_allows(chapter_type, key):
        fill.problems.append(
            f"[PLATE: {fill.name}] is not available to a {chapter_type} chapter")
    # THE ASPECT IS RE-CHECKED HERE, not only at parse time. A storyboard, an
    # approval pass and the kit gate all arrive with values already bound, and
    # `structure/multiple-bridge` in a 9:16 cut has to fail at every one of
    # them — a plate that is 16:9 only is not a thing a portrait render can
    # fall back from.
    if aspect and plate.aspect and plate.aspect != aspect:
        fill.problems.append(
            f"[PLATE: {fill.name}] is {plate.aspect} and this is a {aspect} "
            f"cut — 9:16 is a re-author, never a crop")
    unknown = sorted(set(values) - set(plate.slots))
    for name in unknown:
        if _capacity_problem(plate, name, fill, fill.name):
            continue
        fill.problems.append(f"[PLATE: {fill.name}] has no slot {name!r}")
    # The values are already bound, so the marker pairs are already in their
    # canonical form — but this pass is the last one before a render, and a
    # pair that lost a half somewhere between the parser and here draws a
    # position against nothing.
    for sname, raw in values.items():
        slot = plate.slots.get(sname)
        if slot is None:
            continue
        if _is_marker(slot):
            pair, why = parse_marker(raw)
            if pair is None:
                fill.problems.append(
                    f"[PLATE: {fill.name}] {sname}= takes `t:<number>, "
                    f"median:<number>` and has {why}")
        elif slot.is_text and looks_like_marker(raw):
            fill.problems.append(
                f"[PLATE: {fill.name}] {sname}= is a text slot and {raw!r} is "
                f"a range mark")
        elif _never_typeset(slot) and not slot.is_band and not _draws_a_series(slot):
            fill.problems.append(
                f"[PLATE: {fill.name}] {sname}= is a region the plate sets no "
                f"type in, and {raw!r} would be typeset into it")
    _warn_unfilled(plate, fill)
    return fill


def catalogue(reg: Registry, *, aspect: str = "", chapter_type: str = "") -> list[str]:
    """The plate catalogue, generated from the manifests.

    Name, purpose, slot names, and which chapter types may use it. Generated
    rather than written down for the same reason every other catalogue here is:
    a hand-maintained list drifts the moment the artwork changes, and the
    failure mode of drift is a script full of names that validate-then-fail.
    """
    rows: list[str] = []
    by_type: dict[str, list[str]] = {}
    for ct in reg.chapter_types_available():
        for k in reg.plates_for_chapter(ct):
            by_type.setdefault(k, []).append(ct)

    for family in reg.families():
        keys = [k for k in reg.family(family)
                if (not aspect or not reg.assets[k].aspect
                    or reg.assets[k].aspect == aspect)
                and (not chapter_type or reg.chapter_allows(chapter_type, k))]
        if not keys:
            continue
        rows.append(f"  {family}/")
        for k in keys:
            p = reg.assets[k]
            short = k.split("/", 1)[1]
            line = f"    {short}"
            if p.purpose:
                line += f" — {p.purpose}"
            rows.append(line)
            slots = _slot_summary(p)
            if slots:
                rows.append(f"        slots: {slots}")
    return rows
