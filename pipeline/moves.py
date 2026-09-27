"""Which of design's moves a render plays, when, and what each frame of one
looks like.

WHY THE SHORTS FELT SLOW WAS NOT THE NUMBER OF CUTS. Faster means a new piece
of information on screen every couple of seconds, landing on the word that says
it: the number counting up as it is said, the chart drawing on, the line being
read getting underlined. Design's rebuild-39 publishes exactly those moves
(`kit/engine/motion.js`, ported in :mod:`pipeline.motion`), and this module
decides where they go and draws them.

Two halves, kept apart on purpose:

* **The plan** (:func:`plan_short`) is pure: shots, words and plates in, a list
  of :class:`Move` and :class:`Wipe` out. Nothing is drawn, so the rules — which
  slot counts up, how rare the circle is, which cut gets a wipe — are tested
  without a frame, and the same plan is the record the sound is cut to.
* **The compositor** (:class:`MoveCompositor`) draws one plate layer at one
  instant with whatever moves are playing on it, and the overlays and wipes
  over the whole frame.

THE MOVES ARE PLAYED OVER A PLATE'S PUBLISHED SLOTS, never baked into it, so a
move can never disagree with the plate it animates. A plate is drawn from parts
— its art with the bands that are on, its type, its data — and a move changes
one part: a count-up redraws one slot's text, a line-draw uncovers the data
layer, an underline or a ring is drawn over the top, a zoom crops the lot.

Rules every move keeps (design's DESIGN.md §5): nothing fades; things draw on,
grow, slide, or appear on a frame. The ink is the slot's published ink or the
room's own material.
"""

from __future__ import annotations

import logging
import math
import random
import re
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from pipeline import motion as M

log = logging.getLogger(__name__)

FPS = M.FPS

# The frames, ease and playback of each move are the kit's, from
# `emit/motion.json` through the registry. These are the fallbacks for a kit
# that ships no catalogue, taken from the same file.
_CATALOGUE = {
    "count-up": (7, "out"), "line-draw": (10, "linear"), "bars-grow": (8, "out"),
    "highlight": (6, "out"), "pen-circle": (8, "inOut"),
    "zoom-to-slot": (12, "inOut"), "slide-in": (6, "land"), "tick-over": (6, "inOut"),
}

# Two moves on one plate never overlap: the second waits this long after the
# first lands. One thing at a time is what makes each of them read.
MOVE_GAP_S = 0.15
# A move that cannot finish this long before its shot ends is not started.
# Half a count-up under a cut is a number the viewer never saw land.
END_MARGIN_S = 0.15
# A shot that opens under a wipe keeps its moves until the cover has gone:
# the cut is on the fourth of eight frames, the last four uncover it.
AFTER_WIPE_S = 4 / FPS

# THE CIRCLE IS RARE, AND NEVER ROUND A WHOLE PLATE. Valentin's word on the
# plan (26 Sep 2026): "please make it that he doesn't abuse circling the whole
# plate, make it less frequent". So: only on the one figure the verdict hangs
# on, only in about one short in three, never in two shorts running, and only
# when the figure's own ink is a small part of the plate — a ring round a box
# that fills the frame is circling the plate.
CIRCLE_ONE_IN = 3
CIRCLE_MAX_W = 0.60      # of the plate's width
CIRCLE_MAX_H = 0.22      # of its height
CIRCLE_MAX_AREA = 0.10   # of its area
# Where the verdict's figure can be circled, by the templates' shot ids. A shot
# not named here is never circled, whatever its plate offers. The payoff and
# the print set the figure at display size, so they almost always fail the
# size rule; the circle's real home is the one cell of a full sheet that the
# payoff is about to say, or the gap in a reported-against-expected pair.
CIRCLE_SHOTS = ("the-sheet", "vs-expected", "payoff", "the-print")
VERDICT_SHOTS = ("payoff", "the-print")

# A push-in that barely moves is a wobble, and one that goes too far sets the
# type past the resolution the plate was drawn at (delivered is 2x the frame).
ZOOM_MIN = 1.12
ZOOM_MAX = 1.6

# A slot counts up only when it holds exactly ONE figure: design's anchor also
# lands on units, kickers, dates and the first cell of a sheet, and counting
# up "FY2025" or the oldest year's revenue is noise, not information.
_ONE_FIGURE = re.compile(
    r"^\(?[+\-−]?[$€£]?\d[\d,]*(?:\.\d+)?"
    r"\s?(?:%|x|×|bn|b|m|k|tn|pt|pts|bps)?\)?$", re.IGNORECASE)
# Slots that carry THE figure of a plate, by the kit's own names. Design's
# anchor comes first where it holds a figure; these are the others worth
# counting (the two sides of a comparison, a callout's latest reading).
FIGURE_SLOTS = ("value", "value-1", "value-2", "num", "delta", "huge", "move",
                "latest", "figure", "reported", "expected", "now", "result")

# Spoken units after a figure, so "three percent" is found and "three reasons"
# is not taken for "3%".
_UNIT_WORDS = {"%": "percent", "x": "times", "×": "times", "bn": "billion",
               "b": "billion", "m": "million", "k": "thousand", "tn": "trillion",
               "bps": "basis", "pt": "points", "pts": "points"}

_STRIP = " \t\n\"'“”‘’.,;:!?()[]{}—–-"


def _norm(token: str) -> str:
    return str(token).strip(_STRIP).lower()


def is_one_figure(text: str) -> bool:
    """Whether `text` is one figure and nothing else ("$3.1bn", "−18.4%")."""
    return bool(_ONE_FIGURE.match(str(text or "").strip()))


# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Move:
    """One move, as the render plays it.

    `start` is programme seconds of its first frame; frame f is on screen from
    start + f/12 to start + (f+1)/12, and t = f / (frames - 1) — design's
    review page, and what the sound is timed to.
    """

    move: str
    shot_id: str
    layer: str
    slot: str
    start: float
    frames: int
    ease: str | None = None
    fps: int = FPS
    text: str = ""                     # count-up: the figure it lands on
    seed: int = 5                      # pen-circle: design's review seed

    @property
    def end(self) -> float:
        return self.start + self.frames / self.fps

    def frame_at(self, t: float) -> int | None:
        """Which of its frames shows at `t`: None before it starts, and the
        last one held from then on — a move lands and stays landed."""
        f = math.floor((t - self.start) * self.fps + 1e-9)
        if f < 0:
            return None
        return min(f, self.frames - 1)

    def t_at(self, t: float) -> float | None:
        f = self.frame_at(t)
        return None if f is None else M.t_of_frame(f, self.frames)

    def row(self) -> dict:
        return {"move": self.move, "start": round(self.start, 3),
                "shot_id": self.shot_id, "slot": self.slot}


@dataclass(frozen=True)
class Wipe:
    """A wipe over a cut: design's eight frames, the cut under the fourth.

    Frame f of a wipe is t = (f + 1) / 8, so its first frame already covers a
    quarter of the frame, the cover is full on frame 3 and the two shots are
    cut under it there. It starts three frames before the cut.
    """

    key: str
    cut: float
    shot_out: str
    shot_in: str
    frames: int = 8
    cut_frame: int = 3
    fps: int = FPS

    @property
    def start(self) -> float:
        return self.cut - self.cut_frame / self.fps

    @property
    def end(self) -> float:
        return self.start + self.frames / self.fps

    def frame_at(self, t: float) -> int | None:
        f = math.floor((t - self.start) * self.fps + 1e-9)
        return f if 0 <= f < self.frames else None

    def row(self) -> dict:
        return {"transition": self.key, "cut": round(self.cut, 3),
                "start": round(self.start, 3),
                "shot_out": self.shot_out, "shot_in": self.shot_in}


@dataclass(frozen=True)
class Tag:
    """A source line slid in under a figure, for the rest of its shot."""

    key: str                           # the overlay plate
    shot_id: str
    text: str
    start: float
    end: float
    x: int
    y: int
    w: int
    h: int
    frames: int = 6

    def frame_at(self, t: float) -> int | None:
        if not (self.start <= t < self.end):
            return None
        return min(math.floor((t - self.start) * FPS + 1e-9), self.frames - 1)

    def move(self) -> Move:
        return Move("slide-in", self.shot_id, "", "source", self.start,
                    self.frames, "land")


@dataclass
class MovePlan:
    moves: list[Move] = field(default_factory=list)
    wipes: list[Wipe] = field(default_factory=list)
    tags: list[Tag] = field(default_factory=list)
    # Why a move a plate offered did not play, for the manifest: a circle
    # that sat this video out is a decision, not a bug, and says so.
    skipped: list[str] = field(default_factory=list)

    def for_layer(self, name: str) -> list[Move]:
        return [m for m in self.moves if m.layer == name]

    @property
    def layers(self) -> set[str]:
        return {m.layer for m in self.moves if m.layer}

    def record(self) -> dict:
        """Every move the render played and when, for the manifest and the
        sound: design's move ids, the programme time of each first frame, the
        shot and the slot. Source tags are slide-ins; wipes list their cut."""
        rows = [m.row() for m in self.moves] + [t.move().row() for t in self.tags]
        return {"moves": sorted(rows, key=lambda r: (r["start"], r["move"])),
                "wipes": [w.row() for w in self.wipes],
                "skipped": list(self.skipped)}


def _catalogue(reg, move: str) -> tuple[int, str | None]:
    spec = (getattr(reg, "motion_moves", None) or {}).get(move) or {}
    frames, ease = _CATALOGUE.get(move, (8, "out"))
    return int(spec.get("frames") or frames), spec.get("ease", ease)


def _said_forms(figure: str) -> list[list[str]]:
    """How a figure may be heard: as the prompts ask ("twenty-nine percent",
    "three point one billion") and as digits, for a script that slipped."""
    from pipeline.spoken import say_decimals, say_integer

    m = re.search(r"(\d[\d,]*)(?:\.(\d+))?", figure)
    if not m:
        return []
    whole = int(m.group(1).replace(",", ""))
    said = say_integer(whole).split() + (say_decimals(m.group(2)).split()
                                         if m.group(2) else [])
    tail = figure[m.end():].strip().lower().rstrip(")")
    unit = _UNIT_WORDS.get(tail[:3].strip(), _UNIT_WORDS.get(tail[:2].strip(),
                           _UNIT_WORDS.get(tail[:1], "")))
    words = [_norm(w) for w in said]
    if unit:
        words.append(unit)
    forms = [words[:4]]
    digits = m.group(0).replace(",", "")
    forms.append([digits] + ([unit] if unit and unit != "percent" else []))
    # A bare single word ("three", "ten") with no unit to follow it is too
    # common to hear as THE figure; it is only taken as digits.
    if len(forms[0]) == 1 and whole < 100:
        forms = forms[1:]
    return [f for f in forms if f]


def _heard(words: Sequence, forms: list[list[str]], lo: float, hi: float) -> float | None:
    """When one of `forms` is first spoken inside [lo, hi), or None."""
    toks = [(_norm(getattr(w, "word", "")), float(getattr(w, "start", 0.0)))
            for w in words]
    for i, (tok, at) in enumerate(toks):
        if not (lo <= at < hi):
            continue
        for form in forms:
            n = len(form)
            got = [t for t, _ in toks[i:i + n]]
            # A spoken "twenty-nine%" or "29%," normalises to the form's first
            # token; a figure's digits may carry their own unit ("29%").
            if got == form or (n and got[:1] == form[:1] and
                               re.sub(r"[^\d.]", "", tok) == form[0]):
                return at
    return None


def _phrase_at(words: Sequence, text: str, lo: float, hi: float) -> float | None:
    """When the first three words of `text` are spoken inside [lo, hi)."""
    want = [_norm(t) for t in str(text).split() if _norm(t)][:3]
    if len(want) < 2:
        return None
    toks = [(_norm(getattr(w, "word", "")), float(getattr(w, "start", 0.0)))
            for w in words]
    for i in range(len(toks) - len(want) + 1):
        if lo <= toks[i][1] < hi and [t for t, _ in toks[i:i + len(want)]] == want:
            return toks[i][1]
    return None


def _data_kind(plate, values: dict) -> str:
    """"line", "bars" or "" — what this plate's data layer draws.

    Asked of the data the plate will actually draw rather than of design's
    anchor, which names a plot area on 84 bar and part plates where there is
    no line to draw on.
    """
    from pipeline import series as S

    try:
        got = S.plate_data(plate, dict(values))
    except Exception:                                    # noqa: BLE001
        return ""
    d = got.data or {}
    names = set(plate.slots)
    bars = any(re.match(r"^bar-\d+$", n) for n in names)
    if (d.get("series") and bars) or d.get("bars") or d.get("steps") or d.get("split"):
        return "bars"
    if (d.get("series") and "plot-area" in names) or d.get("panels") or d.get("tiles"):
        return "line"
    return ""


_CELL = re.compile(r"^cell-(\d+)-(\d+)$")


def _figure_slots(plate, values: dict, lit: str = "") -> list[str]:
    """The slots on this plate holding one figure worth counting, top first.

    A sheet's cells are not counted, except the latest figure of the row the
    shot lights: design's anchor on every sheet is the FIRST cell, the oldest
    year, which is the one number on the sheet nobody is talking about.
    """
    anchor = ((plate.motion or {}).get("count-up") or {}).get("slot")
    if anchor and _CELL.match(anchor):
        anchor = None
    names = ([anchor] if anchor else []) + [n for n in FIGURE_SLOTS if n != anchor]
    row = re.match(r"^band-(\d+)$", lit or "")
    if row:
        cells = [(int(m.group(2)), n) for n in values
                 if (m := _CELL.match(n)) and m.group(1) == row.group(1)
                 and str(values[n]).strip()]
        if cells:
            names.append(max(cells)[1])
    got = [n for n in names
           if n in plate.slots and plate.slots[n].is_text
           and is_one_figure(values.get(n, ""))]
    return sorted(dict.fromkeys(got), key=lambda n: (plate.slots[n].y, plate.slots[n].x))


def figure_number(text: str) -> float | None:
    """The signed number a one-figure string states ("-$71M" is -71), or None."""
    if not is_one_figure(text):
        return None
    s = str(text).strip()
    m = re.search(r"\d[\d,]*(?:\.\d+)?", s)
    v = float(m.group(0).replace(",", ""))
    neg = s.startswith(("-", "−", "(")) or s[:2] in ("$-", "$−")
    return -v if neg else v


def _circle_slot(shot_id: str, plate, values: dict, verdict: float | None) -> str | None:
    """Which slot the pen may ring on this shot, if any. See `CIRCLE_SHOTS`."""
    if shot_id not in CIRCLE_SHOTS:
        return None
    if shot_id in VERDICT_SHOTS:
        return "value" if is_one_figure(values.get("value", "")) else None
    if shot_id == "vs-expected":
        return next((n for n in ("delta", "value-1")
                     if is_one_figure(values.get(n, ""))), None)
    # A full sheet: the one cell holding the figure the payoff will say,
    # latest column first. No verdict figure on the sheet, no ring.
    if verdict is None:
        return None
    cells = sorted(((int(m.group(2)), int(m.group(1)), n) for n in values
                    if (m := _CELL.match(n))), reverse=True)
    return next((n for _, _, n in cells
                 if figure_number(values[n]) == verdict), None)


def _circle_this_video(seed: str, recent_circled: bool) -> bool:
    """About one short in three, and never two running."""
    if recent_circled:
        return False
    return random.Random(f"pen-circle|{seed}").randrange(CIRCLE_ONE_IN) == 0


def circle_box(plate, slot_name: str, value: str, settings, reg):
    """The ring's box in canvas units: the figure's own ink, or None when the
    ink is too big a part of the plate to ring without ringing the plate."""
    from pipeline.plate_frames import drawn_box

    slot = plate.slot(slot_name)
    if slot is None:
        return None
    got = drawn_box(plate, slot, value, settings, reg)
    if got is None:
        return None
    s = max(int(plate.export_scale or 1), 1)
    box = M.Box(got[0] / s, got[1] / s, got[2] / s, got[3] / s)
    cw, ch = plate.canvas
    if (box.w > cw * CIRCLE_MAX_W or box.h > ch * CIRCLE_MAX_H
            or box.w * box.h > cw * ch * CIRCLE_MAX_AREA):
        return None
    # The ring runs 26 units wide of the ink and 18 above and below it; it
    # has to land on the plate, not off the edge of the frame.
    if (box.x - 30 < 0 or box.y - 22 < 0 or box.x + box.w + 30 > cw
            or box.y + box.h + 22 > ch):
        return None
    return box


def zoom_pad(canvas: tuple[float, float], box) -> float:
    """Design's 60-unit pad, widened when a small slot would push in past
    ZOOM_MAX: the view never gets narrower than the canvas over ZOOM_MAX."""
    ar = canvas[0] / canvas[1]
    target = canvas[0] / ZOOM_MAX
    return max(60.0, min((target - box.w) / 2, (target / ar - box.h) / 2))


def _zoom_factor(plate, box) -> float:
    vx, vy, vw, vh = M.zoom_box(plate.canvas, box, 1.0, zoom_pad(plate.canvas, box))
    return plate.canvas[0] / max(vw, 1.0)


class _Lane:
    """The moves on one plate, placed one after another without overlap."""

    def __init__(self, t0: float, t1: float, earliest: float) -> None:
        self.t0, self.t1 = t0, t1
        self.free = earliest
        self.moves: list[Move] = []

    def place(self, mv: Move, want: float) -> Move | None:
        start = max(want, self.free, self.t0)
        if start + mv.frames / mv.fps > self.t1 - END_MARGIN_S:
            return None
        placed = Move(mv.move, mv.shot_id, mv.layer, mv.slot, start, mv.frames,
                      mv.ease, mv.fps, mv.text, mv.seed)
        self.moves.append(placed)
        self.free = placed.end + MOVE_GAP_S
        return placed


def shot_plates(result) -> dict:
    """Each shot's own plate layer, by shot id.

    Not every plate layer on a shot is the shot's: a meme is drawn in a
    `frames/` plate laid over the end of the verdict, and a move played on
    that frame would be a move on the wrong picture.
    """
    got: dict = {}
    for l in result.layers:
        if l.kind == "plate" and f"{l.shot_id}:plate:" in l.name:
            got.setdefault(l.shot_id, l)
    return got


def plan_short(fmt, result, reg, words: Sequence = (), *, seed: str = "",
               settings=None, sources: dict[str, str] | None = None,
               recent_circled: bool = False, max_wipes: int = 3) -> MovePlan:
    """The moves a SHORT plays, shot by shot. Pure: nothing is drawn.

    `sources` maps a shot id to the source line of the figure it shows; a
    shot with none gets no tag. `recent_circled` says whether the last short
    already had the pen-circle, so two never run back to back.
    """
    plan = MovePlan()
    sources = sources or {}
    words = list(words or ())
    plate_layers = shot_plates(result)
    circle_ok = _circle_this_video(seed, recent_circled)
    circled = False
    verdict = next((figure_number(plate_layers[s].values.get("value", ""))
                    for s in VERDICT_SHOTS if s in plate_layers), None)

    # WIPES FIRST: a shot a wipe opens holds its moves until the cover goes.
    plan.wipes = plan_wipes(fmt, result, reg, seed=seed, max_wipes=max_wipes)
    wiped_in = {w.shot_in: w for w in plan.wipes}

    first = next(iter(result.spans), None)
    # A BEAT SPLIT FOR RUNNING LONG is one drawing seen twice, wide then
    # close (`resolve_spans`). Its data drew on, its rows lit and its figures
    # counted in the wide part; the close part opens on all of that landed,
    # and plays only an emphasis or a source the wide part did not have.
    emphasised: set[str] = set()
    tagged: set[str] = set()
    for span in result.spans:
        shot = span.shot
        beat = getattr(shot, "part_of", "") or shot.id
        closer = getattr(shot, "part", 0) == 2
        layer = plate_layers.get(shot.id)
        if layer is None:
            continue
        plate = reg.get(layer.entry_key)
        if plate is None:
            continue
        values = dict(layer.values)
        motion = plate.motion or {}
        lit = shot.lit or ""
        t0, t1 = layer.t_start, layer.t_end
        earliest = t0 + (AFTER_WIPE_S if shot.id in wiped_in else 0.0)
        lane = _Lane(t0, t1, earliest)

        def new(move: str, slot: str, text: str = "", seed_: int = 5) -> Move:
            frames, ease = _catalogue(reg, move)
            return Move(move, shot.id, layer.name, slot, t0, frames, ease,
                        text=text, seed=seed_)

        # 1. THE DATA DRAWS ON, on the cut: a chart's line left to right, a
        #    bar chart's columns up from the baseline.
        kind = _data_kind(plate, values) if not closer else None
        if kind == "line" and motion.get("line-draw"):
            lane.place(new("line-draw", "plot-area"), earliest)
        elif kind == "bars" and motion.get("bars-grow"):
            lane.place(new("bars-grow", "plot-area"), earliest)

        # 2. ROWS LIGHT AS THEY ARE READ. A sheet told `lit: "read"` lights
        #    each row's band when its label is spoken, and they stay lit, so
        #    the shot ends with every row up. A shot that lights one row
        #    sweeps that row's band in on the cut.
        if closer:
            pass
        elif lit == "read":
            rows = _sheet_rows(plate, values)
            if rows:
                usable = max(t1 - END_MARGIN_S - earliest, 0.0)
                step = usable / (len(rows) + 1)
                for i, (band, label) in enumerate(rows):
                    at = _phrase_at(words, label, earliest, t1) if label else None
                    lane.place(new("highlight", band),
                               at if at is not None else earliest + step * i)
        elif re.match(r"^band-\d+$", lit) and plate.slot(lit) is not None \
                and plate.slots[lit].is_band and str(values.get(lit, "")).strip():
            lane.place(new("highlight", lit), earliest)

        # 3. EVERY FIGURE COUNTS UP AS IT IS SAID. A figure the voice never
        #    says counts up as the shot opens, and so does the opening shot's:
        #    the first half-second belongs to the ticker and the move (item 6),
        #    whenever the hook gets round to saying it.
        opening = span is first
        for slot in (_figure_slots(plate, values, lit) if not closer else ()):
            at = None if opening else _heard(words, _said_forms(values[slot]), t0, t1)
            lane.place(new("count-up", slot, text=values[slot]),
                       at if at is not None else earliest)

        # 4. ONE EMPHASIS AT MOST: the circle, a push-in, or an underline.
        done = beat in emphasised
        target = _circle_slot(shot.id, plate, values, verdict) if not circled else None
        if target is not None and settings is not None:
            box = circle_box(plate, target, values.get(target, ""), settings, reg)
            if box is None:
                plan.skipped.append(
                    f"{shot.id}: no pen-circle, {target} is too big a part of "
                    f"the plate to ring without ringing the plate")
            elif not circle_ok:
                plan.skipped.append(
                    f"{shot.id}: pen-circle sits this video out (about one "
                    f"short in {CIRCLE_ONE_IN}, never two running)")
            else:
                fig = next((m for m in lane.moves
                            if m.move == "count-up" and m.slot == target), None)
                at = _heard(words, _said_forms(values[target]), t0, t1)
                want = fig.end if fig else (at if at is not None else earliest + 0.35)
                if lane.place(new("pen-circle", target), want) is not None:
                    circled = done = True
                    emphasised.add(beat)
        hl = (motion.get("highlight") or {}).get("slot")
        text = values.get(hl, "") if hl else ""
        if not done and hl and str(text).strip() and plate.slot(hl) is not None \
                and not plate.slots[hl].is_band:
            at = _phrase_at(words, text, t0, t1)
            zbox = None
            if plate.family == "paper" and settings is not None:
                zbox = _ink_box(plate, hl, text, settings, reg)
            if zbox is not None and ZOOM_MIN <= _zoom_factor(plate, zbox):
                done = lane.place(new("zoom-to-slot", hl),
                                  at if at is not None else earliest + 0.6) is not None
            if not done:
                done = lane.place(new("highlight", hl),
                                  at if at is not None else earliest + 0.35) is not None
            if done:
                emphasised.add(beat)

        plan.moves += lane.moves

        # 5. THE SOURCE SLIDES IN under the figure once it has landed.
        src = sources.get(shot.id) or sources.get(beat) \
            or sources.get(beat.rsplit("-", 1)[0])
        if src and beat not in tagged:
            tag = _source_tag(reg, fmt, plate, shot.id, src, lane, t0, t1, earliest)
            if tag is not None:
                plan.tags.append(tag)
                tagged.add(beat)
    return plan


def _sheet_rows(plate, values: dict) -> list[tuple[str, str]]:
    """(band, label) for each filled row of a sheet, top to bottom."""
    rows = []
    for name, slot in plate.slots.items():
        m = re.match(r"^band-(\d+)$", name)
        if not m or not slot.is_band:
            continue
        n = m.group(1)
        label = values.get(f"label-{n}", "")
        filled = str(label).strip() or any(
            k.startswith(f"cell-{n}-") and str(v).strip() for k, v in values.items())
        if filled:
            rows.append((slot.y, name, str(label)))
    return [(b, l) for _, b, l in sorted(rows)]


def _ink_box(plate, slot_name: str, value: str, settings, reg):
    from pipeline.plate_frames import drawn_box

    slot = plate.slot(slot_name)
    if slot is None:
        return None
    got = drawn_box(plate, slot, value, settings, reg)
    if got is None:
        return None
    s = max(int(plate.export_scale or 1), 1)
    return M.Box(got[0] / s, got[1] / s, got[2] / s, got[3] / s)


# Where the source tag rests on a vertical frame: clear of the platform's
# buttons (design's shorts safe band stops at 1560 of 1920), left-aligned with
# the plates' own margin. Design publishes no position for it (item 33 asks).
TAG_MARGIN = 24


def tag_rect(tag, plate, frame: tuple[int, int]) -> tuple[int, int, int, int]:
    """Where the source tag rests over `plate` drawn at `frame`: (x, y, w, h).

    Scaled with the plate, above its safe bottom (design's 1560 of 1920 on a
    vertical frame), centred in the vertical frame's width, which leaves it
    on the plates' own margin, and on that margin on a horizontal one.
    """
    fw, fh = frame
    w, h = tag.canvas
    k = fw / (1920 if fw > fh else 1080)
    w, h = int(w * k), int(h * k)
    safe_bottom = (plate.safe or {}).get("bottom") if isinstance(plate.safe, dict) else None
    bottom = int((safe_bottom or (1560 if fh > fw else 1032)) * fh / (1920 if fh > fw else 1080))
    x = (fw - w) // 2 if fh > fw else int(80 * k)
    y = bottom - h - int(TAG_MARGIN * k)
    return x, y, w, h


def _source_tag(reg, fmt, plate, shot_id: str, text: str, lane: _Lane,
                t0: float, t1: float, earliest: float) -> Tag | None:
    """The source tag for one shot, or None when the plate prints its own
    source or the shot is too short to slide it in and read it."""
    if plate.slot("source") is not None:
        return None
    aspect = getattr(fmt, "aspect", "") or "9x16"
    key = reg.aspect_key("overlays/source-tag", aspect) if hasattr(reg, "aspect_key") else None
    tag = reg.get(key) if key else None
    if tag is None:
        return None
    x, y, w, h = tag_rect(tag, plate, fmt.frame)
    figs = [m for m in lane.moves if m.move in ("count-up", "line-draw", "bars-grow")]
    start = max(earliest + 0.3, figs[0].end + MOVE_GAP_S if figs else earliest + 0.3)
    if start + 1.5 > t1:
        return None
    return Tag(key=tag.key, shot_id=shot_id, text=text, start=start, end=t1,
               x=x, y=y, w=w, h=h)


def plan_wipes(fmt, result, reg, *, seed: str = "", max_wipes: int = 3) -> list[Wipe]:
    """A wipe on each cut the template marks as a change of subject.

    A shot says `"enter": "wipe"` to be wiped in; the wipe alternates sweep
    and page so two in one short are not the same move, `"wipe-sweep"`,
    `"wipe-page"` or `"wipe-blinds"` name one. Every other cut stays a hard
    cut: a wipe is a signpost, and a signpost on every cut is none.
    """
    aspect = getattr(fmt, "aspect", "") or ""
    spans = list(result.spans)
    order = ["wipe-sweep", "wipe-page"]
    if random.Random(f"wipes|{seed}").random() < 0.5:
        order.reverse()
    got: list[Wipe] = []
    for i in range(1, len(spans)):
        enter = (getattr(spans[i].shot, "enter", None) or "").strip()
        if not enter.startswith("wipe") or len(got) >= max_wipes:
            continue
        name = enter if enter != "wipe" else order[len(got) % 2]
        key = reg.aspect_key(f"overlays/{name}", aspect) if hasattr(reg, "aspect_key") else None
        plate = reg.get(key) if key else None
        if plate is None:
            continue
        spec = plate.transition or {}
        frames = int(spec.get("frames") or plate.frame_count or 8)
        cut_frame = max(int(spec.get("cutAt") or 4) - 1, 0)
        cut = spans[i].start
        w = Wipe(key=plate.key, cut=cut, shot_out=spans[i - 1].shot.id,
                 shot_in=spans[i].shot.id, frames=frames, cut_frame=cut_frame)
        # The cover must fit inside the two shots it hides the cut between.
        if w.start < spans[i - 1].start or w.end > spans[i].end:
            continue
        got.append(w)
    return got


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------

class MoveCompositor:
    """Draws the plate layers that have moves on them, and the frame's
    overlays and wipes.

    A plate with moves is built from its parts — art with the static bands,
    type, data — rather than from one cached still, so each move changes one
    part. Composed frames are cached by the state of every move on the layer,
    so a landed move costs nothing on the frames after it.
    """

    def __init__(self, plan: MovePlan, reg, settings, cache, *,
                 memory: int = 48) -> None:
        self.plan = plan
        self.reg = reg
        self.settings = settings
        self.cache = cache                  # render_short._Cache, for overlays
        self._by_layer: dict[str, list[Move]] = {}
        for m in plan.moves:
            self._by_layer.setdefault(m.layer, []).append(m)
        self._parts: dict[tuple, object] = {}
        self._composed: "OrderedDict[tuple, object]" = OrderedDict()
        self._memory = memory

    def owns(self, layer) -> bool:
        return layer.kind == "plate" and layer.name in self._by_layer

    # -- parts, at the plate's delivered size ---------------------------------
    def _part(self, key: tuple, make):
        got = self._parts.get(key)
        if got is None:
            got = self._parts[key] = make()
        return got

    def _base(self, plate, frame_i: int, bands: tuple[str, ...], text: tuple):
        """The plate's art with `bands` on and `text` set, exactly as its
        still is drawn — the type straight onto the art, as `render_frame`
        sets it, so a slot with a published opacity reads the same."""
        from pipeline.plate_frames import render_frame

        return self._part(("base", plate.key, frame_i, bands, text), lambda: render_frame(
            plate, frame_i, {**{b: "1" for b in bands}, **dict(text)},
            self.settings, self.reg))

    def _data(self, plate, values: tuple, seed: str = ""):
        from pipeline.chart import declared_layer

        return self._part(("data", plate.key, values, seed), lambda: declared_layer(
            self.reg, plate, dict(values), plate.pixel_size, seed=seed or plate.key))

    def _ink(self, plate, name: str) -> tuple[int, int, int, int]:
        from pipeline import series as S
        from pipeline.chart import _ink

        inks = _ink(self.reg, plate)
        return S._rgba(inks.get(name) or inks.get("attention") or "#F07A5A")

    # -- one layer --------------------------------------------------------------
    def state(self, layer, t: float) -> tuple:
        """Which frame of each of the layer's moves shows at `t`."""
        return tuple(m.frame_at(t) for m in self._by_layer.get(layer.name, []))

    def frame(self, layer, t: float, frame_i: int):
        """The layer as it looks at `t` on boil frame `frame_i`, at its size."""
        moves = self._by_layer.get(layer.name, [])
        state = self.state(layer, t)
        key = (layer.name, frame_i, state)
        img = self._composed.get(key)
        if img is None:
            img = self._compose(layer, moves, state, frame_i)
            self._composed[key] = img
            if len(self._composed) > self._memory:
                self._composed.popitem(last=False)
        else:
            self._composed.move_to_end(key)
        return img

    def draw_layer(self, canvas, layer, t: float, frame_i: int) -> None:
        img = self.frame(layer, t, frame_i)
        if img is not None:
            canvas.alpha_composite(img, (layer.x, layer.y))

    def _compose(self, layer, moves: list[Move], state: tuple, frame_i: int):
        from PIL import Image

        from pipeline.plate_frames import fill_slot

        plate = self.reg.get(layer.entry_key)
        if plate is None:
            return None
        s = max(int(plate.export_scale or 1), 1)
        values = dict(layer.values)
        live = [(m, f) for m, f in zip(moves, state)]

        def is_band(name: str) -> bool:
            return plate.slot(name) is not None and plate.slots[name].is_band

        # A band that draws on is left off the art until it has landed; every
        # other lit band is on from the first frame. The type goes over the
        # bands, so while one is still drawing the type is set after it.
        sweeping = [(m, f) for m, f in live if m.move == "highlight" and is_band(m.slot)
                    and (f is None or f < m.frames - 1)]
        held = {m.slot for m, _ in sweeping}
        bands = tuple(sorted(n for n, v in values.items()
                             if is_band(n) and str(v).strip() and n not in held))
        counting = {m.slot for m, _ in live if m.move == "count-up"}
        reveal = next(((m, f) for m, f in live if m.move in ("line-draw", "bars-grow")), None)
        # A chart's marks label points on the line ("15.42" at its end), so
        # they wait for the line to reach them: printed before it lands, the
        # label sits in empty plot beside nothing.
        drawing = reveal is not None and (reveal[1] is None
                                          or reveal[1] < reveal[0].frames - 1)
        text = tuple(sorted((k, v) for k, v in values.items()
                            if k not in counting and k in plate.slots
                            and plate.slots[k].is_text
                            and not (drawing and k.startswith("mark-"))))

        if not sweeping:
            img = self._base(plate, frame_i, bands, text).copy()
        else:
            img = self._base(plate, frame_i, bands, ()).copy()
            for m, f in sweeping:
                if f is not None:
                    self._draw_band(img, plate, m, f)
            for name, value in text:
                if str(value).strip():
                    fill_slot(img, plate, plate.slots[name], value, self.settings, self.reg)
        for m, f in live:
            if m.move == "count-up" and f is not None:
                fill_slot(img, plate, plate.slots[m.slot],
                          M.count_text(m.text, M.t_of_frame(f, m.frames)),
                          self.settings, self.reg)
        data = self._data(plate, tuple(sorted(values.items())),
                          getattr(layer, "seed", "") or "")
        if data is not None:
            if reveal is not None:
                data = self._reveal(data, plate, *reveal)
            img.alpha_composite(data)
        for m, f in live:
            if f is None:
                continue
            if m.move == "highlight" and not is_band(m.slot):
                self._draw_underline(img, plate, m, f, values.get(m.slot, ""))
            elif m.move == "pen-circle":
                self._draw_ring(img, plate, m, f, values.get(m.slot, ""))

        zoom = next(((m, f) for m, f in live if m.move == "zoom-to-slot"
                     and f is not None), None)
        if zoom is not None:
            m, f = zoom
            box = _ink_box(plate, m.slot, values.get(m.slot, ""), self.settings, self.reg)
            if box is not None:
                vx, vy, vw, vh = M.zoom_box(plate.canvas, box, M.t_of_frame(f, m.frames),
                                            zoom_pad(plate.canvas, box))
                vw, vh = min(vw, plate.canvas[0]), min(vh, plate.canvas[1])
                # The push never shows past the plate's edge: design's box is
                # not held inside the canvas, and an edge of empty ground
                # sliding in reads as the frame breaking.
                vx = min(max(vx, 0.0), plate.canvas[0] - vw)
                vy = min(max(vy, 0.0), plate.canvas[1] - vh)
                img = img.crop((int(vx * s), int(vy * s),
                                int((vx + vw) * s), int((vy + vh) * s)))
        if img.size != (layer.w, layer.h):
            img = img.resize((max(layer.w, 1), max(layer.h, 1)), Image.LANCZOS)
        return img

    def _reveal(self, data, plate, m: Move, f: int | None):
        """The data layer with the part of the plot not yet drawn cut away.

        Only inside the plot: a mark or a sparkline elsewhere on the plate is
        not part of the line and is never hidden by it. The plot is padded
        20 x 30 units, as design's review page pads it, so the line's stroke
        and its last point are not clipped at the plot's own edge.
        """
        from PIL import Image

        slot = plate.slot(m.slot) or plate.slot("plot-area")
        box = ((plate.motion or {}).get(m.move) or {}).get("box")
        if box:
            px, py, pw, ph = box["x"], box["y"], box["w"], box["h"]
        elif slot is not None:
            px, py, pw, ph = slot.x, slot.y, slot.w, slot.h
        else:
            return data
        px, py, pw, ph = px - 20, py - 30, pw + 40, ph + 60
        s = max(int(plate.export_scale or 1), 1)
        if f is None:
            shown = M.Box(px, py, 0, 0)
        elif m.move == "line-draw":
            shown = M.reveal(M.Box(px, py, pw, ph), M.t_of_frame(f, m.frames), "left-linear")
        else:
            shown = M.reveal(M.Box(px, py, pw, ph), M.t_of_frame(f, m.frames), "bottom")
        out = data.copy()
        hide = Image.new("RGBA", (int(pw * s) + 1, int(ph * s) + 1), (0, 0, 0, 0))
        ox, oy = int(px * s), int(py * s)
        if shown.w > 0 and shown.h > 0:
            keep = data.crop((int(shown.x * s), int(shown.y * s),
                              int((shown.x + shown.w) * s), int((shown.y + shown.h) * s)))
            hide.paste(keep, (int(shown.x * s) - ox, int(shown.y * s) - oy))
        out.paste(hide, (ox, oy))
        return out

    def _draw_band(self, img, plate, m: Move, f: int) -> None:
        """A row band drawn on from the left, under the row's type."""
        from PIL import Image

        slot = plate.slots[m.slot]
        band = self.reg.get(slot.overlay)
        if band is None:
            return
        s = max(int(plate.export_scale or 1), 1)
        x, y, w, h = slot.x * s, slot.y * s, slot.w * s, slot.h * s
        src = self._part(("band", band.key, w), lambda: Image.open(band.path)
                         .convert("RGBA").resize((w, Image.open(band.path).height),
                                                 Image.LANCZOS))
        shown = M.reveal(M.Box(0, 0, w, h), M.t_of_frame(f, m.frames), "left")
        cut = int(round(shown.w))
        if cut <= 0:
            return
        top = y + (h - src.height) // 2
        img.alpha_composite(src.crop((0, 0, cut, src.height)), (x, top))

    def _draw_underline(self, img, plate, m: Move, f: int, value: str) -> None:
        """Design's highlight: a rule under the line being read, drawn on from
        the left. Under the type's own ink rather than the slot's box, which
        on a nine-line hook box sits a third of the frame below the words."""
        from PIL import ImageDraw

        box = _ink_box(plate, m.slot, value, self.settings, self.reg)
        if box is None:
            return
        s = max(int(plate.export_scale or 1), 1)
        slot = plate.slots[m.slot]
        ink = self._ink(plate, slot.underline or "attention")
        shown = M.reveal(box, M.t_of_frame(f, m.frames), "left")
        if shown.w <= 0:
            return
        y = (box.y + box.h + 8) * s
        ImageDraw.Draw(img).rectangle(
            [box.x * s, y, (box.x + shown.w) * s, y + 5 * s], fill=ink)

    def _draw_ring(self, img, plate, m: Move, f: int, value: str) -> None:
        """The pen's ring round the figure's ink, as much of it as is drawn."""
        box = circle_box(plate, m.slot, value, self.settings, self.reg)
        if box is None:
            return
        path = M.pen_circle(box, m.seed)
        pts = M.partial_path(path.points,
                             M.pen_drawn(path.length, M.t_of_frame(f, m.frames)))
        if len(pts) < 2:
            return
        s = max(int(plate.export_scale or 1), 1)
        stroke(img, [(x * s, y * s) for x, y in pts], 7 * s, self._ink(plate, "attention"))

    # -- the whole frame --------------------------------------------------------
    def draw_overlays(self, canvas, t: float) -> None:
        """Source tags, then wipes, over everything else on the frame."""
        for tag in self.plan.tags:
            f = tag.frame_at(t)
            if f is None:
                continue
            img = self.cache.plate(tag.key, 0, {"label": "SOURCE", "source": tag.text},
                                   tag.w, tag.h)
            if img is not None:
                x = tag.x + int(round(M.slide_x(tag.w, M.t_of_frame(f, tag.frames))))
                canvas.alpha_composite(img, (x, tag.y)) if x >= 0 else \
                    canvas.alpha_composite(img.crop((-x, 0, tag.w, tag.h)), (0, tag.y))
        for w in self.plan.wipes:
            f = w.frame_at(t)
            if f is None:
                continue
            img = self.cache.plate(w.key, f, {}, canvas.width, canvas.height)
            if img is not None:
                canvas.alpha_composite(img)


# ---------------------------------------------------------------------------
# The LONG: one plate beat at a time
# ---------------------------------------------------------------------------

def plan_segment(plate, values: dict, rows: Sequence[dict], *, seg_len: float,
                 shot_id: str, layer: str = "plate", earliest: float = 0.0,
                 settings=None, reg=None) -> tuple[list[Move], list[str]]:
    """The moves one LONG plate beat plays, timed from the beat's first frame.

    Nothing is picked here: the writer called these (`rows`, the beat's
    `[MOVE]`s as `plan_writer_moves` placed them), each on the word it was
    written on. The only move added is the data drawing on as the plate
    arrives, which every chart in the kit is built for. They play one after
    another on the beat, as on a short, and a move that cannot land before
    the beat cuts is not started.

    A pen-circle is dropped here if the figure's ink would make the ring a
    ring round the plate: the writer is not offered the circle on a slot that
    big, but the ink of what they wrote is only known now.

    `earliest` is when the beat is first seen, for one that opens under a
    chapter bumper or a wipe: nothing moves before it.
    """
    lane = _Lane(0.0, float(seg_len), max(float(earliest), 0.0))
    skipped: list[str] = []
    motion = plate.motion or {}

    def new(move: str, slot: str, text: str = "") -> Move:
        frames, ease = _catalogue(reg, move)
        return Move(move, shot_id, layer, slot, 0.0, frames, ease, text=text)

    kind = _data_kind(plate, values)
    if kind == "line" and motion.get("line-draw"):
        lane.place(new("line-draw", "plot-area"), 0.0)
    elif kind == "bars" and motion.get("bars-grow"):
        lane.place(new("bars-grow", "plot-area"), 0.0)

    for r in sorted(rows, key=lambda r: (float(r.get("at") or 0.0), int(r.get("order") or 0))):
        move, slot = str(r.get("move") or ""), str(r.get("slot") or "")
        text = str(r.get("text") or values.get(slot, ""))
        where = f"{shot_id}: {move} on {slot}"
        if plate.slot(slot) is None or move not in _CATALOGUE:
            skipped.append(f"{where}: the plate has nothing there to act on")
            continue
        if move == "count-up" and not is_one_figure(text):
            skipped.append(f"{where}: {text!r} is not one figure to count to")
            continue
        if move == "pen-circle" and (
                settings is None or circle_box(plate, slot, text, settings, reg) is None):
            skipped.append(f"{where}: {text!r} is too big a part of the plate to "
                           f"ring without ringing the plate")
            continue
        if move == "zoom-to-slot":
            box = _ink_box(plate, slot, text, settings, reg) if settings is not None else None
            if box is None or _zoom_factor(plate, box) < ZOOM_MIN:
                # A push-in of a few percent reads as a wobble, not a zoom:
                # the line is underlined instead, which is what it was for.
                skipped.append(f"{where}: too big to push in on; underlined instead")
                move = "highlight"
        if lane.place(new(move, slot, text), float(r.get("at") or 0.0)) is None:
            skipped.append(f"{where}: no room to land before the beat cuts")
    return lane.moves, skipped


@dataclass(frozen=True)
class SegmentClips:
    """A LONG plate beat with its moves, as the cut plays it.

    `moving` plays from the beat's first frame until every move has landed.
    A still plate then holds that clip's last frame; a boiling one goes on in
    `landed`, the plate's own boil with every move landed on it, looped, from
    `landed_at` (the moving clip's last frame, which already shows it).
    """

    moving: Path
    landed: Path | None
    landed_at: float
    fps: int


def render_segment(plate, values: dict, moves: Sequence[Move], *, seg_len: float,
                   size: tuple[int, int], settings, reg, out_dir: Path, stem: str,
                   seed: str = "") -> SegmentClips | None:
    """Draw one LONG plate beat's moves into clips, or None when it has none."""
    from types import SimpleNamespace

    from pipeline.rasters import frames_to_alpha_clip, held_frames_to_alpha_clip

    moves = list(moves)
    if not moves:
        return None
    values = dict(values)
    for m in moves:
        # A band the writer highlights stays lit once it has drawn on.
        if m.move == "highlight" and plate.slot(m.slot) is not None \
                and plate.slots[m.slot].is_band:
            values[m.slot] = str(values.get(m.slot) or "").strip() or "1"
    layer = SimpleNamespace(kind="plate", name=moves[0].layer, entry_key=plate.key,
                            values=values, x=0, y=0, w=int(size[0]), h=int(size[1]),
                            seed=seed)
    comp = MoveCompositor(MovePlan(moves=moves), reg, settings, None, memory=8)
    boils = max(int(plate.frame_count or 1), 1) if plate.animated else 1
    boil_fps = max(int(plate.fps or 2), 1)

    def boil(t: float) -> int:
        return int(math.floor(t * boil_fps + 1e-9)) % boils if boils > 1 else 0

    landed = max(m.end for m in moves)
    count = int(math.ceil(min(landed, seg_len) * FPS)) + 1
    held: list[tuple[object, float]] = []
    last = None
    for k in range(count):
        t = k / FPS
        key = (comp.state(layer, t), boil(t))
        if key == last:
            img, secs = held[-1]
            held[-1] = (img, secs + 1 / FPS)
            continue
        img = comp.frame(layer, t, key[1])
        if img is None:
            return None
        held.append((img.copy(), 1 / FPS))
        last = key
    out_dir.mkdir(parents=True, exist_ok=True)
    moving = held_frames_to_alpha_clip(held, out_dir / f"{stem}_moves.mov", fps=FPS)
    if boils <= 1:
        return SegmentClips(moving, None, count / FPS, FPS)
    done = 1e9
    loop = [comp.frame(layer, done, b) for b in range(boils)]
    landed_clip = frames_to_alpha_clip(loop, boil_fps, out_dir / f"{stem}_landed.mov")
    return SegmentClips(moving, landed_clip, (count - 1) / FPS, FPS)


def stroke(img, pts: list[tuple[float, float]], width: float,
           rgba: tuple[int, int, int, int], *, supersample: int = 4) -> None:
    """A round-capped polyline, anti-aliased, onto `img` in place.

    Drawn at four times the size and brought down, as a vector renderer would
    anti-alias it: PIL's own lines have hard edges, and a jagged ring next to
    the kit's smooth type reads as a different hand.
    """
    from PIL import Image, ImageDraw

    if len(pts) < 2:
        return
    r = width / 2
    x0 = int(min(p[0] for p in pts) - r - 2)
    y0 = int(min(p[1] for p in pts) - r - 2)
    x1 = int(max(p[0] for p in pts) + r + 3)
    y1 = int(max(p[1] for p in pts) + r + 3)
    x0, y0 = max(x0, 0), max(y0, 0)
    x1, y1 = min(x1, img.width), min(y1, img.height)
    if x1 <= x0 or y1 <= y0:
        return
    k = supersample
    mask = Image.new("L", ((x1 - x0) * k, (y1 - y0) * k), 0)
    d = ImageDraw.Draw(mask)
    big = [((x - x0) * k, (y - y0) * k) for x, y in pts]
    d.line(big, fill=255, width=max(int(round(width * k)), 1), joint="curve")
    for x, y in (big[0], big[-1]):
        d.ellipse([x - r * k, y - r * k, x + r * k, y + r * k], fill=255)
    mask = mask.resize((x1 - x0, y1 - y0), Image.LANCZOS)
    layer = Image.new("RGBA", mask.size, rgba[:3] + (0,))
    alpha = mask.point(lambda v: v * rgba[3] // 255)
    layer.putalpha(alpha)
    img.alpha_composite(layer, (x0, y0))


def recent_circled(settings, exclude=None) -> bool:
    """Whether the last short rendered played the pen-circle."""
    from pipeline.reach import recent_moves

    return "pen-circle" in recent_moves(settings, window=1, exclude=exclude)


# ---------------------------------------------------------------------------
# The LONG's source tag
# ---------------------------------------------------------------------------

# A tag needs this long on screen after it lands to be read at all.
TAG_READ_S = 1.5


@dataclass(frozen=True)
class TagClip:
    """A source tag sliding in, as a clip for the LONG's overlay stack.

    The clip is a strip from the frame's left edge to the tag's landed right
    edge (plus its overshoot), `y` down, so the tag slides in from off the
    left edge the way design's slide-in does; its last frame is the tag at
    rest, which the overlay holds for the rest of the beat.
    """

    path: Path
    x: int
    y: int
    frames: int


def source_tag_clip(reg, settings, out: Path, *, text: str, plate, aspect: str,
                    panel: tuple[int, int, int, int]) -> TagClip | None:
    """Design's source tag for a LONG beat, sliding in under `plate` as it is
    placed on the frame (`panel` is its x, y, w, h), or None when the kit has
    no tag at this aspect or the plate prints its own source."""
    from PIL import Image

    from pipeline.plate_frames import render_frame
    from pipeline.rasters import held_frames_to_alpha_clip

    if plate is None or plate.slot("source") is not None or not str(text).strip():
        return None
    key = reg.aspect_key("overlays/source-tag", aspect) if hasattr(reg, "aspect_key") else None
    tag = reg.get(key) if key else None
    if tag is None:
        return None
    px, py, pw, ph = panel
    x, y, w, h = tag_rect(tag, plate, (pw, ph))
    img = render_frame(tag, 0, {"label": "SOURCE", "source": str(text).strip()},
                       settings, reg).convert("RGBA")
    if img.size != (w, h):
        img = img.resize((max(w, 1), max(h, 1)), Image.LANCZOS)
    spec = (getattr(reg, "motion_moves", None) or {}).get("slide-in") or {}
    frames = int(spec.get("frames") or 6)
    left = px + x
    over = int(math.ceil(0.25 * (w + 40)))
    strip = (left + w + over, h)
    out_frames = []
    for f in range(frames):
        dx = int(round(M.slide_x(w, M.t_of_frame(f, frames))))
        canvas = Image.new("RGBA", strip, (0, 0, 0, 0))
        at = left + dx
        if at + w > 0:
            canvas.alpha_composite(img, (at, 0)) if at >= 0 else \
                canvas.alpha_composite(img.crop((-at, 0, w, h)), (0, 0))
        out_frames.append((canvas, 1 / FPS))
    held_frames_to_alpha_clip(out_frames, out, fps=FPS)
    return TagClip(path=out, x=0, y=py + y, frames=frames)
