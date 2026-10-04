"""WHAT HIS MONITOR SHOWS, CHAPTER BY CHAPTER (items 49, 54, 56).

The 3D room's monitor is written per video (`pipeline/room_dressing.py`). It
used to show the share price's five years for the whole video. Now it shows
what the chapter is about: the chart or the figure from a plate the chapter
already puts on screen, so in the room behind him the viewer sees the same
picture the next cut fills the frame with.

- THE WRITER PICKS with `[SCREEN: ...]` anywhere in a chapter: `price` for the
  five-year chart, or the name of a plate that chapter shows
  (`[SCREEN: bars-6y]`), which goes on the monitor with the figures the
  chapter's [PLATE] gave it.
- THE BOT PICKS when the writer did not: the chapter's first chart, figure,
  peer or cycle plate, else its first table, else the five-year chart.

Nothing here draws. It decides, per chapter, which beat's plate the monitor
carries, and the renderer draws that plate the way it draws the beat.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

# What `[SCREEN: price]` and every chapter with nothing better show.
PRICE = "price"
# The plate families that read on a monitor at the back of a room, first
# choice to last: a chart or one big figure reads, a table is a spreadsheet,
# and nothing else is picked by the bot.
FIRST_CHOICE = ("charts", "figures", "peers", "cycles")
SECOND_CHOICE = ("tables",)


@dataclass(frozen=True)
class ScreenPick:
    """What the monitor shows through one chapter."""
    chapter: int            # index into the chapter windows
    start: float
    end: float
    seg_index: int | None   # the plate beat whose picture it carries; None: price
    plate_key: str = ""
    by: str = "bot"         # writer | bot


_ASPECT = re.compile(r"-(16x9|9x16)$")


def plate_stem(key: str) -> str:
    """`figures/big-number-l1-16x9` -> `big-number-l1`: the name a writer uses."""
    name = key.rsplit("/", 1)[-1]
    return _ASPECT.sub("", name)


def _norm(name: str) -> str:
    return plate_stem(name.strip().lower().replace(" ", "-"))


def screen_tags(script, words) -> list[tuple[float, str]]:
    """Every `[SCREEN: ...]` as (time, payload), in script order."""
    from pipeline.models import TagType
    from pipeline.timeline import char_offset_time

    return [(char_offset_time(words, e.char_offset), e.payload.strip())
            for e in getattr(script, "events", ()) or ()
            if e.type is TagType.SCREEN and e.payload.strip()]


def _plates_in(segments: Sequence, start: float, end: float) -> list[tuple[int, str]]:
    return [(i, s.payload.get("value", "")) for i, s in enumerate(segments)
            if s.kind == "plate" and start <= s.start < end and s.payload.get("value")]


def _family(key: str) -> str:
    return key.split("/", 1)[0] if "/" in key else ""


def plan_screens(segments: Sequence, windows: Sequence[tuple[float, float]],
                 tags: Sequence[tuple[float, str]] = (),
                 warn=lambda _m: None) -> list[ScreenPick]:
    """One pick per chapter window, in order.

    `segments` are the render's planned beats, `windows` the chapter windows
    (`timeline.chapter_windows`), `tags` the writer's [SCREEN]s with their
    times. A tag names a plate of ITS chapter; one that names a plate the
    chapter does not show is reported and the bot picks.
    """
    out: list[ScreenPick] = []
    for k, (a, b) in enumerate(windows):
        plates = _plates_in(segments, a, b)
        mine = [p for t, p in tags if a <= t < b]
        if len(mine) > 1:
            warn(f"chapter {k + 1} has {len(mine)} [SCREEN] tags — the monitor "
                 f"shows the first, {mine[0]!r}")
        if mine:
            want = mine[0]
            if want.strip().lower() == PRICE:
                out.append(ScreenPick(k, a, b, None, by="writer"))
                continue
            hit = next(((i, key) for i, key in plates if _norm(key) == _norm(want)), None)
            if hit is not None:
                out.append(ScreenPick(k, a, b, hit[0], hit[1], by="writer"))
                continue
            warn(f"[SCREEN: {want}] — chapter {k + 1} shows no plate by that name "
                 f"({', '.join(sorted({plate_stem(p) for _, p in plates})) or 'none'}); "
                 f"the bot picks")
        pick = None
        for families in (FIRST_CHOICE, SECOND_CHOICE):
            pick = next(((i, key) for i, key in plates if _family(key) in families), None)
            if pick is not None:
                break
        if pick is None:
            out.append(ScreenPick(k, a, b, None))
        else:
            out.append(ScreenPick(k, a, b, pick[0], pick[1]))
    return out


def pick_at(picks: Sequence[ScreenPick], t: float) -> ScreenPick | None:
    """The pick in force at programme time `t`."""
    for p in picks:
        if p.start <= t < p.end:
            return p
    return picks[-1] if picks else None
