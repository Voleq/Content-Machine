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

A key that IS a declared slot name is always taken verbatim, which is what keeps
a comma inside prose from being read as a list separator.
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


def _column_count(plate: Plate) -> int:
    """How many periods this plate is authored for.

    Six, everywhere it matters: four fiscal years, the last full year and LTM.
    Read off the declared slots rather than assumed, because `charts/line-dense`
    is deliberately four heads over many observations.
    """
    heads = sum(1 for n in plate.slots if _INDEXED_RE.match(n)
                and _INDEXED_RE.match(n).group(1) == "head")
    return heads or plate.columns or PERIOD_COUNT


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
        fill.problems.append(
            f"[PLATE: {name}] is {plate.aspect} and this is a {aspect} cut — "
            f"9:16 is a re-author, never a crop")

    cols = _column_count(plate)
    header_len = 0

    for k, raw in assigns:
        if not k:
            fill.problems.append(
                f"[PLATE: {name}] has a part with no `slot=value`: {raw!r}")
            continue

        # 1. An exact slot name is taken VERBATIM. This is what lets prose keep
        #    its commas — `body=Margins fell, and stayed there` is one value.
        if k in plate.slots:
            fill.values[k] = raw
            if k == "head":
                header_len = len([v for v in raw.split(",")])
            continue

        # 2. `band=N` lights row N. A band is not a text box — it is the row
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

        # 3. `row-N` spreads across that row's cells.
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

        # 4. A list across an indexed family: `head=…` -> head-1 … head-N.
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

        # 5. Nothing it could be.
        near = _nearest_slot(plate, k)
        fill.problems.append(
            f"[PLATE: {name}] has no slot {k!r}"
            + (f" — did you mean {near!r}?" if near else
               f" (it declares {_slot_summary(plate)})"))

    _warn_unfilled(plate, fill)
    return fill


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
                chapter_type: str = "") -> PlateFill:
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
    unknown = sorted(set(values) - set(plate.slots))
    for name in unknown:
        fill.problems.append(f"[PLATE: {fill.name}] has no slot {name!r}")
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
