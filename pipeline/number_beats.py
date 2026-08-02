"""Reaching for the numbers batch automatically.

Twenty-three drawings in ``dennis-vs-numbers`` and ``dennis-vs-numbers-2``
exist for exactly one job — making a figure land instead of scrolling past in a
table row — and they only appeared if the writer named one. Most videos
therefore used none of them, and the core batch stayed occasional artwork
rather than the mechanism it was built to be.

So a key-number beat that carries no tag of its own picks one here. The choice
is:

* **read off the number**, not random — a figure that went up gets a drawing
  about going up, a scale mismatch gets the ruler;
* **deterministic**, seeded by the script sha and the row, so a re-render is
  identical;
* **spread across uploads** through the :class:`~pipeline.kit.VariantLedger`,
  so the channel does not open on the same drawing two days running.

The value goes into the asset's slot, which is the whole point: the drawing is
about *that* number, not about numbers in general.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Collection

from pipeline.kit import Kit, VariantLedger

log = logging.getLogger(__name__)

# What the figure is doing -> the drawings that say that.
#
# Grouped by MEANING rather than by family, because the writer's alternative is
# to name one by hand and the whole point is that they do not have to. Every
# key here has a single `number` slot.
NUMBER_BEATS: dict[str, tuple[str, ...]] = {
    "up": (
        "shorts/dennis-vs-numbers/chart-ride-up",
        "shorts/dennis-vs-numbers/climb-bars",
        "shorts/dennis-vs-numbers/sit-on-number",
        "shorts/dennis-vs-numbers-2/balance-on-nose",
        "shorts/dennis-vs-numbers-2/inflate-the-number",
    ),
    "down": (
        "shorts/dennis-vs-numbers/crushed-flat",
        "shorts/dennis-vs-numbers/chart-off-cliff",
        "shorts/dennis-vs-numbers/stand-in-hole",
        "shorts/dennis-vs-numbers/hold-collapsing-bar",
        "shorts/dennis-vs-numbers-2/saw-the-bar",
        "shorts/dennis-vs-numbers-2/digging-the-hole",
    ),
    "scale": (
        "shorts/dennis-vs-numbers/measure-tiny-ruler",
        "shorts/dennis-vs-numbers/dwarfed-by-bar",
        "shorts/dennis-vs-numbers/atlas-percent",
        "shorts/dennis-vs-numbers-2/wheelbarrow-of-cash",
    ),
    # A grind rather than a fall: debt, burn, a target being strained toward.
    "burden": (
        "shorts/dennis-vs-numbers/push-boulder",
        "shorts/dennis-vs-numbers-2/tug-of-war-line",
        "shorts/dennis-vs-numbers-2/sweeping-it-under",
    ),
}

# An INCREASE this large is about scale rather than direction — a figure that
# went up eleven-fold is "look how big this is", not "it rose". A decrease of
# the same size is still a fall, and a loss deepening from -$8M to -$89M is
# emphatically a fall: checking magnitude before direction called that one
# "scale" and reached for a wheelbarrow of cash.
SCALE_RATIO = 8.0


def classify(values: list[float] | None, label: str = "") -> str:
    """Which bank a series belongs in.

    Reads the series the row already carries, so the choice is about the
    number rather than about the writer remembering to say so.
    """
    low = label.lower()
    if any(w in low for w in ("debt", "burn", "capex", "obligation", "lease")):
        return "burden"
    if not values or len(values) < 2:
        return "scale"

    first, last = values[0], values[-1]
    if last < first:
        return "down"
    if last > first:
        # Direction first, then magnitude: only a big RISE is about scale.
        grew = abs(last) / max(abs(first), 1e-9) if first else 0.0
        return "scale" if grew >= SCALE_RATIO else "up"
    return "scale"


def pick(kit: Kit, direction: str, *, seed: str,
         ledger: VariantLedger | None = None,
         exclude: Collection[str] = ()) -> str | None:
    """A key from `direction`'s bank, deterministic and spread across uploads.

    `exclude` is names the caller must not be handed — in practice the
    drawings the writer already asked for by name. It is applied to the bank
    BEFORE the choice, so a collision picks a different drawing rather than
    losing the beat; filtering afterwards silently dropped one every time the
    dice landed on a tagged prop.
    """
    banned = {e.rsplit("/", 1)[-1].lower() for e in exclude}
    options = [k for k in NUMBER_BEATS.get(direction, ())
               if k in kit and k.rsplit("/", 1)[-1].lower() not in banned]
    if not options:
        return None
    if ledger is not None:
        fresh = [k for k in options if k not in ledger.all_used()]
        options = fresh or options
    digest = hashlib.sha256(f"number-beat|{direction}|{seed}".encode()).hexdigest()
    chosen = options[int(digest[:8], 16) % len(options)]
    if ledger is not None:
        ledger.record("number-beats", chosen)
    return chosen


def beat_for_row(
    kit: Kit,
    label: str,
    values: list[str],
    *,
    seed: str,
    ledger: VariantLedger | None = None,
    exclude: Collection[str] = (),
) -> tuple[str, dict[str, str]] | None:
    """(kit key, slot values) for one numbers row, or None.

    The slot takes the row's LATEST value — the figure the beat is about is
    the one being said out loud, not the series.
    """
    from pipeline.rasters import parse_row_values

    if not values:
        return None
    direction = classify(parse_row_values(values), label)
    key = pick(kit, direction, seed=f"{seed}|{label}", ledger=ledger,
               exclude=exclude)
    if key is None:
        return None
    asset = kit.get(key)
    slot = asset.slots[0].name if asset and asset.slots else "number"
    return key, {slot: values[-1]}
