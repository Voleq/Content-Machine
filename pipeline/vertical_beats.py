"""Reaching for the vertical scenes automatically.

Eleven drawings in ``shorts/vertical-scenes`` and ``shorts/vertical-scenes-2``
are 1080x1920 compositions — a person tiny at the base of a towering bar, a
number falling at him from the top of frame, a wall of red built out of a
series. They are the ONLY assets in the kit drawn to fill this frame, and
:func:`pipeline.kit_frames.is_full_frame` has always routed them correctly to
the full-bleed register.

They just never fired, because they only appeared when a writer named one by
key. Most scripts named none, so the assets built to be the frame were the
assets a short never used.

So a key-number beat reaches for one, the same way
:mod:`pipeline.number_beats` reaches for the small drawings — read off the
number, deterministic per script, spread across uploads by the ledger. One per
video: the register is the whole frame, and a short that cuts to full-bleed
six times is not emphasising anything.

The difference from `number_beats` is the SLOTS. Eight of these take a single
figure; three are built around a series — a ladder of rungs, six floors of a
lift shaft, six bricks in a wall — and want the row itself.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Collection

from pipeline.kit import Kit, VariantLedger
from pipeline.number_beats import classify

log = logging.getLogger(__name__)

# What the figure is doing -> the full-frame scenes that say that.
VERTICAL_BEATS: dict[str, tuple[str, ...]] = {
    "up": (
        "shorts/vertical-scenes/b-towering-chart",
        "shorts/vertical-scenes-2/b2-crane-lifting",
        "shorts/vertical-scenes/b-number-ladder",
    ),
    "down": (
        "shorts/vertical-scenes/b-long-fall-line",
        "shorts/vertical-scenes/b-falling-at-him",
        "shorts/vertical-scenes-2/b2-elevator-drop",
    ),
    "scale": (
        "shorts/vertical-scenes/b-under-the-pile",
        "shorts/vertical-scenes/b-filings-stack",
        "shorts/vertical-scenes-2/b2-conveyor-filings",
    ),
    "burden": (
        "shorts/vertical-scenes-2/b2-wall-of-red",
        "shorts/vertical-scenes-2/b2-tightrope",
        "shorts/vertical-scenes/b-under-the-pile",
    ),
}


def pick(kit: Kit, direction: str, *, seed: str,
         ledger: VariantLedger | None = None,
         exclude: Collection[str] = ()) -> str | None:
    """A key from `direction`'s bank, deterministic and spread across uploads."""
    banned = {e.rsplit("/", 1)[-1].lower() for e in exclude}
    options = [k for k in VERTICAL_BEATS.get(direction, ())
               if k in kit and k.rsplit("/", 1)[-1].lower() not in banned]
    if not options:
        # Any vertical scene beats none: the register is the point.
        options = [k for fam in ("shorts/vertical-scenes",
                                 "shorts/vertical-scenes-2")
                   for k in kit.family(fam)
                   if k.rsplit("/", 1)[-1].lower() not in banned]
    if not options:
        return None
    if ledger is not None:
        fresh = [k for k in options if k not in ledger.all_used()]
        options = fresh or options
    digest = hashlib.sha256(f"vertical|{direction}|{seed}".encode()).hexdigest()
    chosen = options[int(digest[:8], 16) % len(options)]
    if ledger is not None:
        ledger.record("vertical-beats", chosen)
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

    A single-slot scene takes the row's LATEST value — the figure being said
    out loud. A multi-slot one takes the series, oldest first, because the
    drawing IS the series: a ladder with one rung filled is not a ladder.
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
    if asset is None or not asset.slots:
        return key, {}
    names = [s.name for s in asset.slots]
    if len(names) == 1:
        return key, {names[0]: values[-1]}
    # The series, oldest first, into as many boxes as the drawing has. A
    # shorter row leaves the far boxes empty rather than repeating itself.
    return key, {n: v for n, v in zip(names, values[-len(names):])}
