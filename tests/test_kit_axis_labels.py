"""The 9:16 axis labels stay out of the plot they label.

Rebuild-41's 9:16 type floor grew right-set y-axis labels past their zone and
slid them across the axis line onto the bars, on eleven charts. The bot
patched design's `engine/grounds.js` for it (46544f6) and sent the patch back;
design's rebuild-41c carries it as its own (`DATA`, `DATA_GAP`), so `kit/` has
no bot patch left in it. What is pinned is the result, read off the slot table
the kit publishes: a drop that loses the stop fails here, whoever's code it
was.
"""

from __future__ import annotations

import json
from pathlib import Path

SLOTS = Path(__file__).resolve().parents[1] / "kit" / "emit" / "slots.json"
# The regions a plate draws its data in (grounds.js `DATA`).
DATA = {"plot-area", "bars", "bar", "bridge", "path", "spark", "media", "mark-area"}


def _meets(a: dict, b: dict) -> bool:
    return not (a["x"] + a["w"] <= b["x"] or a["x"] >= b["x"] + b["w"]
                or a["y"] + a["h"] <= b["y"] or a["y"] >= b["y"] + b["h"])


def test_no_right_set_axis_label_sits_in_a_data_region():
    plates = json.loads(SLOTS.read_text(encoding="utf-8"))["plates"]
    checked, inside = 0, []
    for key, plate in plates.items():
        slots = plate["slots"]
        data = [s for s in slots.values() if s.get("role") in DATA]
        for name, s in slots.items():
            if s.get("role") != "axis" or s.get("align") != "right":
                continue
            checked += 1
            inside += [f"{key} {name}" for d in data if _meets(s, d)]
    assert checked > 100, "the kit publishes no right-set axis labels to check"
    assert not inside, (
        f"{len(inside)} right-set axis label(s) overlap the plot they label: "
        f"{', '.join(inside[:6])}. Rebuild-41's 9:16 floor slid them there; "
        f"grounds.js must stop a grown box DATA_GAP short of a data region.")
