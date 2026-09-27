"""Design's chapter bumper and its wipes, as clips the LONG lays over its cut.

THE BUMPER IS A COUNT, NOT A CARD. Rebuild-39's `structure/chapter-bumper`
is the full frame between chapters: the chapter number large, "OF SEVEN", the
chapter's title and the episode, held for two seconds (the plate publishes
the hold). Its number is the one thing that changes between two bumpers in
one episode, and design's `tick-over` move turns it over — the old number up
and out, the new one up and in — so the viewer reads it as counting.

`wipe-blinds` goes under it, which is how design paired them: the slats close
over the last frame of the chapter before and open on the bumper, with the
cut under the fourth frame where the cover is full. The cold open and the end
card get a sweep or a page instead.

Every clip here is drawn at design's 12 frames a second and nothing in it
fades: the number turns over, the slats close. The LONG composites clips by
timestamp, so a 12 fps clip over the 30 fps cut steps exactly as design's
review page does.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from pathlib import Path

from pipeline import motion as M

log = logging.getLogger(__name__)

FPS = M.FPS

# WHEN THE NUMBER TURNS OVER, inside the bumper's two seconds. Design
# publishes the hold and the move's six frames but not where in the hold the
# move starts (item 33 of the motion plan asks them to). A quarter of a
# second in: the slats have opened on the old number, and the new one has
# landed with most of the two seconds left to read the title.
TICK_AT_S = 0.25


@dataclass(frozen=True)
class Clip:
    """A clip for the LONG's overlay stack: where it lands and how long."""

    path: Path
    start: float
    end: float
    name: str
    move: str            # design's id, for the move record ("tick-over", "wipe-blinds")
    cut: float | None = None


def spelled(n: int) -> str:
    """7 -> "SEVEN", as design's bumper sample prints its total."""
    from pipeline.spoken import say_integer

    return say_integer(int(n)).replace(" and ", " ").upper()


def bumper_values(n: int, total: int, title: str, episode: str) -> dict[str, str]:
    """The bumper's slots, in design's own shape ("03", "OF SEVEN")."""
    return {"num": f"{int(n):02d}", "of": f"OF {spelled(total)}",
            "title": str(title or "").strip(), "episode": str(episode or "").strip()}


def _boil(plate, i: int) -> int:
    """Which of the plate's boil frames shows on clip frame `i`."""
    n = max(int(plate.frame_count or 1), 1)
    fps = float(getattr(plate, "fps", 0) or 0)
    if n <= 1 or fps <= 0:
        return 0
    return int(i / FPS * fps) % n


def bumper_frames(reg, settings, *, aspect: str, n: int, total: int, title: str,
                  episode: str, size: tuple[int, int]) -> list:
    """The bumper's frames at 12 fps, sized to the cut, number turning over.

    Chapter `n` turns over from `n - 1`, so the first bumper of an episode
    (before chapter two) reads 01 turning to 02.
    """
    from PIL import Image

    from pipeline.plate_frames import fill_slot, render_frame

    key = reg.aspect_key("structure/chapter-bumper", aspect)
    plate = reg.get(key) if key else None
    if plate is None or plate.slot("num") is None:
        return []
    values = bumper_values(n, total, title, episode)
    rest = {k: v for k, v in values.items() if k != "num" and plate.slot(k) is not None}
    hold = float(plate.hold_s or 2.0)
    count = max(int(round(hold * FPS)), 1)
    spec = (getattr(reg, "motion_moves", None) or {}).get("tick-over") or {}
    tick_frames = int(spec.get("frames") or 6)
    first = int(round(TICK_AT_S * FPS))

    s = max(int(plate.export_scale or 1), 1)
    slot = plate.slots["num"]
    sw, sh = slot.w * s, slot.h * s

    def number(text: str):
        img = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
        fill_slot(img, plate, slot, text, settings, reg, origin=(0, 0))
        return img

    old, new = number(f"{max(int(n) - 1, 0):02d}"), number(values["num"])
    bases: dict[int, object] = {}
    frames = []
    for i in range(count):
        b = _boil(plate, i)
        if b not in bases:
            bases[b] = render_frame(plate, b, rest, settings, reg)
        img = bases[b].copy()
        k = i - first
        window = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
        if k < 0:
            window.alpha_composite(old)
        elif k >= tick_frames:
            window.alpha_composite(new)
        else:
            old_y, new_y = M.tick(sh, M.t_of_frame(k, tick_frames))
            # Both clipped to the slot: the old number leaves through its
            # top edge and the new one comes up through its bottom.
            for part, dy in ((old, old_y), (new, new_y)):
                dy = int(round(dy))
                if -sh < dy < sh:
                    window.alpha_composite(part, (0, dy)) if dy >= 0 else \
                        window.alpha_composite(part.crop((0, -dy, sw, sh)), (0, 0))
        img.alpha_composite(window, (slot.x * s, slot.y * s))
        if img.size != tuple(size):
            img = img.resize(tuple(size), Image.LANCZOS)
        frames.append(img)
    return frames


def wipe_frames(reg, name: str, aspect: str, size: tuple[int, int]) -> tuple[list, int]:
    """A wipe's frames sized to the cut, and the index of the frame the cut
    goes under (design's `cutAt`, counted from one)."""
    from PIL import Image

    key = reg.aspect_key(f"overlays/{name}", aspect)
    plate = reg.get(key) if key else None
    if plate is None:
        return [], 0
    spec = plate.transition or {}
    cut_frame = max(int(spec.get("cutAt") or 4) - 1, 0)
    frames = []
    for path in plate.frame_paths():
        img = Image.open(path).convert("RGBA")
        if img.size != tuple(size):
            img = img.resize(tuple(size), Image.LANCZOS)
        frames.append(img)
    return frames, cut_frame


def bumper_clip(reg, settings, out: Path, *, aspect: str, at: float, n: int,
                total: int, title: str, episode: str,
                size: tuple[int, int]) -> Clip | None:
    from pipeline.rasters import frames_to_alpha_clip

    frames = bumper_frames(reg, settings, aspect=aspect, n=n, total=total,
                           title=title, episode=episode, size=size)
    if not frames:
        log.warning("the kit has no chapter bumper at %s; chapter %d opens "
                    "without one", aspect, n)
        return None
    frames_to_alpha_clip(frames, FPS, out)
    return Clip(out, at, at + len(frames) / FPS, f"bumper_{n}", "tick-over",
                cut=at)


def wipe_clip(reg, out: Path, *, name: str, aspect: str, cut: float,
              size: tuple[int, int]) -> Clip | None:
    """A wipe laid so its full cover is on screen at `cut`."""
    from pipeline.rasters import frames_to_alpha_clip

    frames, cut_frame = wipe_frames(reg, name, aspect, size)
    if not frames:
        return None
    start = cut - cut_frame / FPS
    if start < 0:
        return None
    frames_to_alpha_clip(frames, FPS, out)
    return Clip(out, start, start + len(frames) / FPS, f"{name}@{cut:.2f}", name,
                cut=cut)


def tick_start(clip: Clip) -> float:
    """Programme time of the tick-over's first frame inside a bumper clip."""
    return clip.start + math.floor(TICK_AT_S * FPS + 0.5) / FPS
