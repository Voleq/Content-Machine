"""A video that looks like the last few (V7).

The sameness gate reads the words. Two videos can say different things over
the same plates in the same order, cut from the same chairs, and a viewer
who saw one has seen the other. Each render records its `look`: the plates
it drew in order (`plates`) and the rooms he was in, beat by beat
(`rooms`). After a proof or a final that look is compared with the last
`LONG_WINDOW` longs or `SHORT_WINDOW` shorts of OTHER videos, by
`difflib.SequenceMatcher` ratio, and a close one is a warning naming the
video it matches. It never stops a render.

Forgiving like `reach.recent_plates`: a first video, a manifest from before
`look` was recorded, or one that will not parse contributes nothing.
"""

from __future__ import annotations

import json
from difflib import SequenceMatcher
from pathlib import Path

PLATE_RATIO = 0.75
ROOM_RATIO = 0.8
LONG_WINDOW = 3
SHORT_WINDOW = 5
# Under this many beats two orders are alike by arithmetic, not by look.
MIN_BEATS = 3


def lane_of(manifest: Path) -> str:
    """"long" for the long's manifests, "short" for a short's."""
    return "long" if manifest.name.startswith("render_long") else "short"


def _recent(settings, lane: str, exclude: Path | str | None) -> list[tuple[str, dict]]:
    """(video, look) for the newest render of each other video, newest first."""
    base = Path(settings.workspace_dir)
    if not base.is_dir():
        return []
    skip = Path(exclude).resolve() if exclude else None
    newest: dict[Path, tuple[float, dict]] = {}
    for m in base.glob("*/*/*manifest*.json"):
        ws = m.parent
        if (skip is not None and ws.resolve() == skip) or lane_of(m) != lane:
            continue
        try:
            look = json.loads(m.read_text(encoding="utf-8")).get("look")
            mtime = m.stat().st_mtime
        except (OSError, ValueError, AttributeError):
            continue
        if not isinstance(look, dict):
            continue
        if ws not in newest or mtime > newest[ws][0]:
            newest[ws] = (mtime, look)
    window = LONG_WINDOW if lane == "long" else SHORT_WINDOW
    got = sorted(newest.items(), key=lambda kv: kv[1][0], reverse=True)[:window]
    return [(f"{ws.parent.name} {ws.name}", look) for ws, (_t, look) in got]


def _ratio(a: list, b: list) -> float | None:
    if len(a) < MIN_BEATS or len(b) < MIN_BEATS:
        return None
    return SequenceMatcher(None, list(a), list(b)).ratio()


def findings(settings, lane: str, look: dict, *,
             exclude: Path | str | None = None) -> list[dict]:
    """Each recent video this look is close to, and in what, closest first."""
    out = []
    for video, other in _recent(settings, lane, exclude):
        for what, floor in (("plates", PLATE_RATIO), ("rooms", ROOM_RATIO)):
            r = _ratio(look.get(what) or [], other.get(what) or [])
            if r is not None and r >= floor:
                out.append({"video": video, "what": what, "ratio": round(r, 2)})
    return sorted(out, key=lambda f: -f["ratio"])


def report(manifest: dict, lane: str = "long") -> str:
    """The render's look-alikes as operator text, or "" when there are none.

    A long's fix is in the script, which picks its plates and rooms. A
    short's plates are the template's, already steered off the recent ones,
    so a short that still matches is told apart by when it goes out.
    """
    got = list((manifest or {}).get("look_alike") or [])
    if not got:
        return ""
    lines = []
    for f in got:
        pct = int(round(f["ratio"] * 100))
        if lane == "short":
            lines.append(f"Looks like {f['video']}: {pct}% the same pictures "
                         f"in the same order, because the kit had nothing "
                         f"else for those beats. Space the two apart when "
                         f"you schedule them.")
        elif f["what"] == "plates":
            lines.append(f"Looks like {f['video']}: {pct}% the same plates in "
                         f"the same order. Swap a few [PLATE] picks or move "
                         f"one, so it does not look like that video again.")
        else:
            lines.append(f"Dennis is in the rooms {f['video']} used, in the "
                         f"same order ({pct}%). Set a different [SCENE] room "
                         f"on a few of his beats.")
    return "\n".join(lines)
