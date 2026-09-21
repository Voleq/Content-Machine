"""What the writer is actually asked for, derived rather than declared.

The writing prompt used to hand the writer a CATALOGUE OF DRAWINGS — every
family in the kit, grouped by situation — and ask them to name one per beat.
That was right when the script chose composition. It is not right now: the
template chooses composition, and the only thing a script supplies is WORDS
AT A SIZE.

So the form is not authored. It is READ OFF the templates: every `src` a
template asks for is a field, its budget is the measured budget of the
destination it lands in, and a source feeding several destinations takes the
smallest of them. There is no fourth file to drift out of step, and a new
format is a form the moment its JSON exists.

Two kinds of source, and only one of them is the writer's:

* **WRITER** — `script.*` for the verticals, `chapter.*` for the long. Prose
  somebody has to compose, with a character budget it has to fit.
* **SUPPLIED** — `numbers.*` and `compare.*` come from the data export,
  `chart.*` and `media.*` off the workspace, `plate.*` out of the kit,
  `channel.*` from settings. The writer never sees these and must never be
  asked to invent them.

The budget is the point. It is the kit's own `maxChars` per slot, measured by
real fitter against the real templates; the same numbers gate the render
(`compose.check_budgets`) and describe the field here, so a field cannot be
advertised at a length the frame will refuse.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from pipeline.shots import available_formats, expand_sequences, load_format

# Sources the writer composes. Everything else is supplied by the pipeline,
# and asking a writer for it is how a hallucinated figure reaches a frame.
WRITER_ROOTS = ("script", "chapter")

# THE BUDGET COMES FROM THE KIT, NOT FROM A MEASUREMENT OF THIS CODE.
#
# It used to live in `templates/budgets.json`, produced by running the type
# fitter over the templates and re-measured on every test run so the two could
# not drift. That file existed because the old renderer drew every line of
# copy itself over artwork with no opinion about type. The v2 plates declare a
# `maxChars` per slot ROLE, measured against the face and size that slot is
# actually set in — so the budget is a property of the drawing, and asking the
# drawing is both shorter and true by construction.


@dataclass(frozen=True)
class Field:
    """One thing the writer supplies, and how much room it has."""

    src: str                       # "script.hook_text"
    destinations: tuple[str, ...]  # ("text:hook",)
    budget: int | None             # characters, measured; None if unmeasured
    shots: tuple[str, ...]         # which shots read it

    @property
    def name(self) -> str:
        """The field name a form would show: the last meaningful part."""
        return self.src.split(".", 1)[1] if "." in self.src else self.src

    @property
    def writer(self) -> bool:
        return self.src.split(".", 1)[0] in WRITER_ROOTS


def _budgets(name: str, root: Path | str = ".") -> dict[str, int]:
    """`fill:<slot>` -> characters, read off the plates the format names."""
    try:
        from config import Settings
        from pipeline.compose import resolve_plate
        from pipeline.plate_frames import slot_limit
        from pipeline.plates import load_plates
    except Exception:                              # noqa: BLE001
        return {}
    try:
        reg = load_plates(Settings(_env_file=None).assets_dir)
        fmt = load_format(name, root)
    except Exception:                              # noqa: BLE001
        return {}

    out: dict[str, int] = {}
    for shot in fmt.shots:
        if not shot.plate:
            continue
        # EVERY PLATE THE BEAT MIGHT LAND ON, NOT JUST THE AUTHORED ONE.
        # The rotation picks between them at render time and the writer is
        # asked for the line long before that, so the number they are given
        # has to be the one that fits WHICHEVER is picked — the narrowest box
        # across the set. Quoting the authored plate's figure would promise
        # room an alternate does not have, and the render refuses rather than
        # truncating, which puts the failure after the writing.
        for i, variant in enumerate(shot.variants):
            try:
                plate = resolve_plate(reg, variant.plate, fmt.aspect)
            except Exception:                      # noqa: BLE001
                plate = None
            if plate is None:
                continue
            bind, _lit, _focus = variant.resolved(shot)
            # The authored plate contributes every box it is given; an
            # alternate only the ones it REQUIRES, for the reason spelled out
            # in `form_for` — an optional value that does not fit is left out
            # of that drawing rather than refused, so a narrow optional box on
            # one alternate must not shrink what the writer may write for every
            # video.
            if i:
                bind = {k: v for k, v in bind.items() if not v.startswith("?")}
            _slot_budgets(out, plate, bind, slot_limit)
    return out


def _slot_budgets(out: dict[str, int], plate, binds, slot_limit) -> None:
    """Fold one plate's limits into `out`, keeping the tightest per slot."""
    for slot_name in binds:
        slot = plate.slot(slot_name)
        if slot is None:
            continue
        # The budget for THIS box, falling back to the role's floor — the
        # same resolution `check_budgets` uses, so a field cannot advertise
        # a length the compositor will then refuse.
        # A wrapping slot says how many lines and how wide each is, and
        # `slot_limit` multiplies the two out — the same arithmetic the
        # rotation uses to decide whether a line fits a plate it is
        # considering, so a field cannot advertise a length the compositor
        # will then refuse.
        limit = slot_limit(plate, slot)
        if limit:
            key = f"fill:{slot_name}"
            out[key] = min(out.get(key, int(limit)), int(limit))


def form_for(name: str, root: Path | str = ".") -> list[Field]:
    """Every source a format reads, in the order its shots read them.

    Order matters: a form asked in cut order is a form somebody can fill
    while watching the video in their head. Alphabetical is not an order a
    script is written in.
    """
    fmt = expand_sequences(load_format(name, root),
                           lambda _src: ["a", "b", "c", "d"])
    mine = _budgets(name, root)

    seen: dict[str, tuple[list[str], list[str]]] = {}

    def note(src: str, dest: str, shot: str) -> None:
        if not src:
            return
        dests, shots = seen.setdefault(src, ([], []))
        if dest not in dests:
            dests.append(dest)
        if shot not in shots:
            shots.append(shot)

    for shot in fmt.shots:
        for t in shot.text:
            note(t.src, f"text:{t.name}", shot.id)
        # EVERY BOX THE FIELD MAY LAND IN, across every plate this beat may
        # be drawn on. The rotation picks the plate at render time and the
        # alternates rarely name their slots the same way — `script.verdict`
        # is the `detail` rule on `big-number-l2` and the `caption` on `l1`,
        # and those boxes are not the same width. Registering only the
        # authored plate's slot leaves the field quoting a budget for a box it
        # may never land in, and the render refuses rather than truncating.
        for slot, expr in (shot.bind or {}).items():
            # A leading '?' marks an optional slot; it is the SLOT that is
            # optional, not the source, so the name is the same either way.
            note(expr.lstrip("?"), f"fill:{slot}", shot.id)
        # AN ALTERNATE TIGHTENS THE ASK ONLY WHERE IT MUST.
        #
        # The rotation picks the plate at render time and the alternates rarely
        # name their slots the same way, so a field can land in boxes of
        # different widths. Where the alternate REQUIRES the value, the writer
        # has to be given the narrowest of them: the render refuses an
        # over-budget required fill rather than truncating it, and a number
        # quoted off the authored plate alone would put that refusal after the
        # writing instead of during it.
        #
        # Where it is OPTIONAL the opposite holds. An optional value that does
        # not fit is left out of that drawing and the video is fine — that is
        # the kit's own rule, in `_bound_values` — so letting a narrow optional
        # box drag the quoted budget down would shrink what the writer may
        # write for every video, to suit the one plate that can do without it.
        for variant in shot.alts:
            bind, _lit, _focus = variant.resolved(shot)
            for slot, expr in bind.items():
                if not expr.startswith("?"):
                    note(expr, f"fill:{slot}", shot.id)
        if shot.repeat and shot.repeat.src:
            for slot in (shot.repeat.bind or {}):
                note(shot.repeat.src, f"repeat:{slot}", shot.id)

    def budget_of(dest: str) -> int | None:
        if dest in mine:
            return mine[dest]
        # A repeat's cards are measured per index — `repeat:label:0` — because
        # the third card in a row is narrower than the first. The field is one
        # field, so it takes the tightest card it has to fit.
        indexed = [v for k, v in mine.items() if k.startswith(f"{dest}:")]
        return min(indexed) if indexed else None

    out = []
    for src, (dests, shots) in seen.items():
        found = [b for b in (budget_of(d) for d in dests) if b is not None]
        out.append(Field(src=src, destinations=tuple(dests),
                         budget=min(found) if found else None,
                         shots=tuple(shots)))
    return out


def writer_fields(name: str, root: Path | str = ".") -> list[Field]:
    """Only what a person has to write. This is the form."""
    return [f for f in form_for(name, root) if f.writer]


def supplied_fields(name: str, root: Path | str = ".") -> list[Field]:
    """Everything the pipeline fills. Never ask a writer for these."""
    return [f for f in form_for(name, root) if not f.writer]


def render_form(name: str, root: Path | str = ".") -> str:
    """The form as text, for the writing prompt.

    Deliberately plain. Every line is a field, its budget and where it lands,
    because a writer who can see the shot can write to the shot — and a
    budget stated without the reason for it reads as an arbitrary rule.
    """
    lines = [f"FIELDS FOR A {name.upper()} — every one of these is drawn, and",
             "the number is the characters the frame holds. Over it, the",
             "render REFUSES rather than truncating.",
             ""]
    for f in writer_fields(name, root):
        budget = f"{f.budget:>4} chars" if f.budget else "   (unmeasured)"
        where = ", ".join(f.shots[:3])
        lines.append(f"  {f.name:<24} {budget}   -> {where}")
    return "\n".join(lines)


def all_forms(root: Path | str = ".") -> dict[str, list[Field]]:
    return {n: writer_fields(n, root) for n in available_formats(root)}
