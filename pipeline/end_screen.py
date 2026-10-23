"""THE END SCREEN (V3, Valentin's pick 18 Oct 2026).

YouTube's end screen is the boxes (next video, subscribe) over the last 5
to 20 seconds of a long. He places them in Studio by hand: the API cannot
set them. The bot's half is the picture under them. The last 20 seconds
are one shot of him, never evidence, and that shot leaves one side of the
frame as clear wall: off his figure and off the NOT FINANCIAL ADVICE
cross-stitch, which is never covered.

A sign-off shorter than that gets a quiet tail: he stays in the shot, idle,
while the outro theme (placed to end with the video) plays out. A video
that ends on a plate gets a beat of him after it.

Everything here works in fractions of the frame, 0-1 from the top left.
"""

from __future__ import annotations

import math
from dataclasses import replace

from pipeline.timeline import Segment

END_SCREEN_S = 20.0
# The boxes' column: two video boxes stacked and the subscribe circle take
# about a third of the frame's width in Studio. Kept off the top band (his
# ticker and date sit top right) and the bottom (the player's own bar).
ZONE_W = 0.36
ZONE_Y = (0.14, 0.86)
ZONE_MARGIN = 0.03
# Room for his arms and the sway of a 3D idle around the place he stands.
HIM_PAD = 0.04

Rect = tuple[float, float, float, float]


def extend_for_end(segments: list[Segment], voice_end: float, *,
                   cover_s: float = 0.0, fps: int = 0) -> tuple[list[Segment], float]:
    """(the plan with its last beat of him holding the end screen, the
    video's new end).

    `cover_s` is how long the cut into the last beat is covered (the end
    wipe, or the clock): the 20 seconds count from when it lifts. The input
    is not changed. `fps` puts the new end on the frame grid, rounding up.
    """
    if not segments:
        return list(segments), voice_end
    out = list(segments)
    last = out[-1]
    if last.kind == "host":
        end = max(voice_end, last.start + cover_s + END_SCREEN_S)
        end = _on_grid(end, fps)
        out[-1] = replace(last, end=end,
                          payload={**last.payload, "end_screen": True})
        return out, end
    variant = max((s.payload.get("variant", -1) for s in out if s.kind == "host"),
                  default=-1) + 1
    end = _on_grid(voice_end + cover_s + END_SCREEN_S, fps)
    out.append(Segment(start=voice_end, end=end, kind="host",
                       payload={"variant": variant, "layout": "host-full",
                                "end_screen": True}))
    return out, end


def _on_grid(t: float, fps: int) -> float:
    if not fps:
        return t
    return math.ceil(t * fps - 1e-6) / fps


def zone(side: str) -> Rect:
    """Where the boxes go on `side`, as (x0, y0, x1, y1)."""
    y0, y1 = ZONE_Y
    if side == "left":
        return (ZONE_MARGIN, y0, ZONE_MARGIN + ZONE_W, y1)
    return (1.0 - ZONE_MARGIN - ZONE_W, y0, 1.0 - ZONE_MARGIN, y1)


def _meets(a: Rect, b: Rect) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def clear_side(him: Rect | None, signs: list[Rect]) -> tuple[str, Rect] | None:
    """The side whose box column misses him (padded) and every sign, the
    right first; None when neither does."""
    blocks = list(signs)
    if him is not None:
        blocks.append((him[0] - HIM_PAD, him[1] - HIM_PAD,
                       him[2] + HIM_PAD, him[3] + HIM_PAD))
    for side in ("right", "left"):
        z = zone(side)
        if not any(_meets(z, b) for b in blocks):
            return side, z
    return None


def room_blocks(room) -> tuple[Rect | None, list[Rect]]:
    """(where he stands, the signs) in `room`, from the kit: the host
    anchor, and the bounds of each cross-stitch the room's labels carry."""
    cw, ch = (room.canvas if getattr(room, "canvas", None) else (1920, 1080))
    a = room.slot("host-anchor")
    him = ((a.x / cw, a.y / ch, (a.x + a.w) / cw, (a.y + a.h) / ch)
           if a is not None and a.w and a.h else None)
    signs: list[Rect] = []
    items = ((getattr(room, "writable", None) or {}).get("labels") or {}).get("items") or ()
    for it in items:
        quad = it.get("quad") or ()
        if it.get("kind") != "stitch" or len(quad) != 4:
            continue
        xs, ys = [float(p[0]) for p in quad], [float(p[1]) for p in quad]
        signs.append((min(xs) / cw, min(ys) / ch, max(xs) / cw, max(ys) / ch))
    return him, signs


def _clock(t: float) -> str:
    t = max(int(t), 0)
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}" if t >= 3600 \
        else f"{t // 60}:{t % 60:02d}"


def checklist_line(end_screen: dict) -> str:
    """The Studio step for the end screen, off the manifest's record."""
    if not end_screen or "start" not in end_screen:
        return ""
    at = _clock(float(end_screen["start"]))
    if end_screen.get("clear") and end_screen.get("side"):
        return (f"End screen: from {at} to the end, with the boxes on the "
                f"{end_screen['side']} side, where the wall is clear.")
    return (f"End screen: from {at} to the end. The render found no clear side "
            f"of the wall, so look at the last 20 seconds before placing the boxes.")
