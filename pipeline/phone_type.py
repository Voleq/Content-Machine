"""Type too small for a phone (V5).

Most of a long's views are on a phone held sideways, where the 1920-wide
frame is about `PHONE_W` px across. A line set under `MIN_PHONE_PX` there is
a smudge. The kit declares nothing that small (its smallest role is 21-22
units of a 1920 canvas, 7 px on the phone), so what this finds is a line the
fitter shrank to make it fit, and a plate drawn so small beside him in a
two-shot that not even its biggest line reads.

A two-shot's kicker and small print are always under the line: the plate is
drawn at about a third of the frame there, and the writer chose him over the
type (the writer's prompt says so). Naming them on every two-shot would be a
warning he learns to skip, so a two-shot is named only when its biggest line
is too small too, and then the plate says nothing at all on a phone.

`fill_slot` notes the size it set every line at; the long's renderer opens a
beat around each plate it draws (`at_beat`), and anything noted outside one
is not recorded. `findings` turns the notes into what the delivery message
and the page's Proof step say: one line per beat.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

PHONE_W = 640
MIN_PHONE_PX = 7.0
# How many lines a report names before it says how many more there are.
REPORT_MAX = 3

_BEAT: ContextVar[tuple[list, dict] | None] = ContextVar("phone_type_beat",
                                                         default=None)


@contextmanager
def at_beat(rows: list, seg_i: int, t: float) -> Iterator[None]:
    """Record every line set while this beat's plate is drawn into `rows`."""
    token = _BEAT.set((rows, {"seg": int(seg_i), "t": round(float(t), 3)}))
    try:
        yield
    finally:
        _BEAT.reset(token)


def note(plate: Any, slot: Any, text: str, units: float) -> None:
    """A line set at `units` of `plate`'s canvas, when a beat is open."""
    beat = _BEAT.get()
    if beat is None:
        return
    rows, where = beat
    canvas = getattr(plate, "canvas", None) or (1920, 1080)
    rows.append({**where, "plate": getattr(plate, "key", ""),
                 "slot": getattr(slot, "name", ""), "text": str(text),
                 "units": round(float(units), 2), "canvas_w": int(canvas[0])})


def findings(rows: list[dict], shown: dict[int, float] | None = None,
             beside: set[int] | frozenset[int] = frozenset()) -> list[dict]:
    """The beats with a line under `MIN_PHONE_PX` on a phone, one each.

    `shown` is the fraction of the frame's width each beat's plate is drawn
    at, by segment index; a beat it does not name filled the frame. `beside`
    names the beats drawn beside him (two-shots): one of those is named only
    when its biggest line is under the floor too, by that line. Any other
    beat is named by its smallest line, with how many more are under the
    floor (`more`). A slot set more than once (a figure counting up) is
    measured as the text it lands on, the last one it was set with.
    """
    landed: dict[int, dict[tuple, dict]] = {}
    for r in rows:
        landed.setdefault(r["seg"], {})[(r["plate"], r["slot"])] = r
    out = []
    for seg, lines in landed.items():
        frac = (shown or {}).get(seg, 1.0)
        sized = sorted(((r["units"] / max(r["canvas_w"], 1) * frac * PHONE_W, r)
                        for r in lines.values()), key=lambda pr: pr[0])
        small = [pr for pr in sized if pr[0] < MIN_PHONE_PX]
        two_shot = seg in beside
        if not small or (two_shot and len(small) < len(sized)):
            continue
        px, r = sized[-1] if two_shot else small[0]
        out.append({"t": r["t"], "plate": r["plate"], "slot": r["slot"],
                    "text": r["text"], "phone_px": round(px, 1),
                    "beside": two_shot, "shown": round(frac, 2),
                    "more": 0 if two_shot else len(small) - 1})
    return sorted(out, key=lambda f: (f["t"], f["plate"]))


def _clock(t: float) -> str:
    s = int(round(t))
    return f"{s // 60}:{s % 60:02d}"


def _line(f: dict) -> str:
    where = f"{_clock(f['t'])} {f['plate']}"
    if f.get("beside"):
        return (f"  {where}, beside him at {int(round(f['shown'] * 100))}% of "
                f"the frame: even \"{f['text']}\" is {f['phone_px']} px. Drop "
                f"with= on that tag so the plate fills the frame.")
    more = f.get("more") or 0
    tail = f", and {more} more line{'s' if more != 1 else ''} on it" if more else ""
    return (f"  {where}: \"{f['text']}\" is {f['phone_px']} px "
            f"({f['slot']}){tail}. Shorten the line or split it so it is set "
            f"at the kit's size.")


def report(manifest: dict) -> str:
    """The render's small type as operator text, or "" when there is none."""
    got = list((manifest or {}).get("phone_type") or [])
    if not got:
        return ""
    lines = [f"{len(got)} plate{'s' if len(got) != 1 else ''} with type too "
             f"small to read on a phone held sideways:"]
    lines += [_line(f) for f in got[:REPORT_MAX]]
    if len(got) > REPORT_MAX:
        lines.append(f"  and {len(got) - REPORT_MAX} more")
    return "\n".join(lines)
