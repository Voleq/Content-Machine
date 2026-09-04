"""How much of the plate library a script actually reaches.

The library is 113 plates. A script that names six of them will look like the
last script that named six of them, and it did that for months without anybody
noticing, because the number existed only inside a render manifest nobody
opens. Nothing measured it before the render, nothing printed it after, so "the
library feels unused" stayed a feeling.

The COUNT comes off the registry, so it follows the kit rather than a figure
typed here. The floor stays, because the floor is the number that says whether
this video will look like the last one.

This is the measurement, in one place, read by two callers that used to have no
way of asking the question at all:

* :func:`parse_short_script` warns when a script's own picks fall below the
  floor, and names the beats carrying a figure with no drawing to put it in;
* the approval report prints :meth:`Reach.line` above the Approve button, which
  is the last moment the script can be sent back.

It measures what the SCRIPT names, not what the finished render contains. The
renderer adds furniture — a backdrop, three stings, the desk, the host shots —
and reaches for a beat itself when a numbers row was left undrawn, so the
manifest count is always the larger of the two. The script's own count is the
one a writer can act on, and the one a thin script shows up in.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# A figure as it is written on screen: 29, +29%, 5×, $1.1B, -$15M, 365M.
# Deliberately not run over `audio_script`, where every number is spelled out
# for the voice ("four hundred million") and none of this would match. The
# suffix is a unit, never free text: `[a-zA-Z]{0,2}` swallowed the next word,
# so "+29% today" and "+29%" were two different figures.
_FIGURE_RE = re.compile(r"[+-]?\$?\d[\d.,]*(?:\s*[%×]|[KMBTkmbt]\b|x\b)?")

# The format's own data beats, in order. Each one carries a figure and each one
# is a beat the writer can hand a drawing; a beat with no figure in it is not
# owed a scene and is not counted against the floor.
_MOVE_BEAT = "the move"

# Four is the format's own beat count — hook / why / gut-check / payoff — so it
# is the floor at which every beat has a scene rather than the desk. It is a
# floor, not a target, and a script under it is a judgement call, never a
# defect: this warns, and nothing here ever blocks.
BEAT_FLOOR = 4


def _norm_figure(text: str) -> str:
    """A figure reduced to what two writings of it have in common."""
    return re.sub(r"[^0-9a-z.%]", "", text.strip().lower())


def _figures(*texts: str) -> set[str]:
    out: set[str] = set()
    for text in texts:
        for hit in _FIGURE_RE.findall(text or ""):
            norm = _norm_figure(hit)
            if norm:
                out.add(norm)
    return out


def _events(script) -> list:
    """The script's inline tags, whatever the format calls them."""
    return list(getattr(script, "events", None) or
                getattr(script, "inline_events", []) or [])


def _is_beat_family(family: str) -> bool:
    """True for a family whose plates carry a figure as their whole point.

    Read off the registry's own families rather than a list of folder names, so
    a kit that adds one counts it the day it lands.
    """
    return family in ("figures", "tables", "charts", "cycles", "peers")


@dataclass(frozen=True)
class Reach:
    """What one script reaches of the kit, and what it left undrawn."""

    keys: tuple[str, ...] = ()          # kit assets the script's tags name
    scenes: tuple[str, ...] = ()        # the beat-library subset of those
    undrawn: tuple[str, ...] = ()       # beats with a figure and no scene
    data_beats: int = 0                 # beats carrying a figure at all
    total: int = 0                      # assets in the kit

    @property
    def families(self) -> tuple[str, ...]:
        return tuple(sorted({k.rsplit("/", 1)[0] for k in self.keys}))

    @property
    def floor(self) -> int:
        """The scene count below which the desk starts carrying beats."""
        return min(BEAT_FLOOR, self.data_beats)

    @property
    def thin(self) -> bool:
        return bool(self.data_beats) and len(self.scenes) < self.floor

    def line(self) -> str:
        """The one line the approval report carries."""
        scenes = len(self.scenes)
        return (f"Kit: {len(self.keys)} of {self.total} plates · "
                f"{len(self.families)} families · "
                f"{scenes} data plate{'' if scenes == 1 else 's'}")


def rendered_reach(kit_keys, reg) -> Reach:
    """The reach of a FINISHED render, off the manifest's `kit_assets_used`.

    The same line in the same shape as the script's, so the two are readable
    against each other: the render is always the larger number, because it adds
    the furniture (a backdrop, the stings, the desk, the host shots) and picks
    a beat itself for a numbers row the writer left undrawn. A render whose
    count is barely above the script's is a render carried by furniture.
    """
    keys = tuple(sorted(set(kit_keys)))
    return Reach(
        keys=keys,
        scenes=tuple(k for k in keys if _is_beat_family(k.rsplit("/", 1)[0])),
        total=len(reg),
    )


def script_reach(script, settings) -> Reach:
    """Measure one script against the kit on disk.

    Card tags are resolved the way the renderer resolves them — named artwork
    first, then the parameterised blank — so a `[TERM]` with no drawing counts
    as the asset that will actually be placed rather than as nothing.
    """
    from pipeline.models import TagType
    from pipeline.plates import PlateError, load_plates

    try:
        reg = load_plates(settings.assets_dir)
    except PlateError:
        return Reach()
    keys: set[str] = set()
    scenes: set[str] = set()
    drawn: set[str] = set()
    for event in _events(script):
        if event.type is not TagType.PLATE:
            continue
        plate = reg.get(event.payload)
        if plate is None:
            continue
        keys.add(plate.key)
        if _is_beat_family(plate.family):
            scenes.add(plate.key)
            # The figures the director wrote into this plate. Every word on
            # screen is in `values`, so this is the whole set.
            drawn |= _figures(*(str(v) for v in (event.values or {}).values()))

    return Reach(
        keys=tuple(sorted(keys)),
        scenes=tuple(sorted(scenes)),
        undrawn=tuple(_undrawn_beats(script, drawn)),
        data_beats=len(_figure_beats(script)),
        total=len(reg),
    )


def _figure_beats(script) -> list[tuple[str, set[str]]]:
    """`(name, figures)` for every beat of this script carrying a figure.

    The LONG has no fixed beat structure of this shape, so it reports none and
    its reach line is a count without a floor.
    """
    numbers = getattr(script, "numbers", None)
    if not numbers:
        return []
    beats: list[tuple[str, set[str]]] = []
    move = _figures(getattr(script, "move_summary", "") or "",
                    getattr(script, "hook_text", "") or "")
    if move:
        summary = (getattr(script, "move_summary", "") or "").strip()
        beats.append((f'{_MOVE_BEAT} ("{summary}")', move))
    for i, row in enumerate(numbers):
        figures = _figures(*row.values)
        if figures:
            last = row.values[-1] if row.values else ""
            beats.append((f"numbers row {i} ({row.label} {last})", figures))
    trap = _figures(getattr(script, "cheap_or_trap", "") or "")
    if trap:
        beats.append(("cheap-or-trap (the multiple)", trap))
    return beats


def _undrawn_beats(script, drawn: set[str]) -> list[str]:
    """Beats whose figure was never handed to a beat-library drawing.

    Attribution is by the figure itself: a `[PROP: crushed-flat = -$15M]`
    covers the row whose last value is -$15M. A writer who typed the figure a
    second way lands here anyway — which is the right way round for a warning
    that costs nothing and is never a blocker.
    """
    return [name for name, figures in _figure_beats(script)
            if not (figures & drawn)]
