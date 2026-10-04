"""The template and the script, turned into an ordered list of layers.

`templates/shots/*.json` fixes space and order, the word timestamps fix
duration, and this module is the machinery between those two facts and
something a renderer can draw. It chooses nothing: no plate, no figure, no
composition. A format is a file.

**Every asset here comes from the v2 plate registry.** This module used to
read a second one — 476 entries in four hand-drawn registers, with its own
manifest, its own scale rule, its own light and ambient loops — and the two
systems were live in the same repository at the same time. That is how a
rebuild ships dark cards twice: the old path stays resolvable, nothing points
at it, and then something does. The register kit is gone; `plates-registry.json`
is the only library.

Three things follow from the v2 kit that did not hold under the old one:

* **Type goes into slots the plate declares.** A plate is rendered WITH its
  values by `plate_frames`, in the face, size, weight and colour role the kit
  declares for that slot's role. This module places the plate and says what
  goes in it; it does not fit type. The old path drew every line of copy
  itself, over artwork that had no opinion about type at all, and the budgets
  it needed to do that were measured by running the fitter over the templates.
  The kit carries a `maxChars` per slot instead.

* **The host is solved onto the room's anchor.** Not fitted into a figure box:
  the anchor's HEIGHT is his target height, and his own floor line sits on the
  anchor's bottom edge. `host.place_on_room` is that contract, in one place.

* **Data plates used to not boil, and now they do — but not the numbers.**
  Every data plate was once `playback: static`, on the argument that a number
  moving three times a second cannot be read, which is the whole job of a
  number. Most of the kit loops now, and `static` is the kit's own call per
  plate — the host's held poses, the marks, the lower thirds and the source
  tag, some figures, charts, rankings and room angles — read off the
  manifest, never assumed from a family.

  THE ARGUMENT WAS NOT ABANDONED, IT WAS MADE PER-MARK. `kit/engine/build.js`
  §1.5 turns the boil on for a data plate's FURNITURE — paper edge, corner
  wear, rule lines, hatch — while axes, series lines, figures and cells emit
  the identical path they emitted at boil 0, bit for bit. The frame breathes;
  nothing a viewer reads a value off moves. A frozen table in a boiling room
  read as a screenshot pasted over a cartoon, and that is what changed.

  A design decision from the pack, not drift in this file. The previous
  version of this paragraph carried the retraction with the old kit's
  arithmetic still attached — "the 143-plate kit had 47 static" — which is
  the halfway state that reads as authoritative.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Collection, Protocol, Sequence

from pipeline.plates import Plate, Registry, _prefer_unused
from pipeline.shots import (LARGE_TYPE_FH, MIN_TYPE_FH, Format, Shot, Span,
                            TemplateError)

log = logging.getLogger(__name__)

# Moving in on a slot: how much of the frame height it should come to fill,
# and how far the plate may be enlarged doing it. Past about 2.4x the kit's
# stroke is visibly soft, so a slot too small to reach the target simply gets
# as close as the ceiling allows.
FOCUS_FILL = 0.62
FOCUS_MAX_SCALE = 2.4

# How much of a two-shot's width the graphic takes. The rest is his column,
# 845 of 1920 pixels, and a close-up framed at CLOSE_UP_IN_COLUMN_FH inks
# about 770 of them — so his shoulders stay in his half rather than being
# cropped into the graphic's.
TWO_SHOT_GRAPHIC = 0.56

# How much of the frame's height his head takes when the close-up shares the
# frame. The kit's band is 0.42-0.56 and a full-frame close-up sits at its
# centre; at the centre his shoulders are 898 pixels across, wider than his
# column, and the graphic beside him would be drawn over one of them.
CLOSE_UP_IN_COLUMN_FH = 0.42

# HOW MUCH A PLATE MAY CARRY AND STILL SHARE THE FRAME. A two-shot draws the
# graphic at 56% of the width, so its type lands at 56% of the size it was
# drawn at. A quote pull is three slots and reads fine at that; a four-row
# sheet is thirty-nine and its unit row is already the smallest type in the
# kit. The dense plates are the ones a chapter is ABOUT, and a chapter's
# evidence beat can have the frame to itself.
TWO_SHOT_MAX_SLOTS = 10

# What he does in a room that declares `hostAnchor: false`. The role is the
# kit's own, so a kit that renames its framings is followed rather than
# hard-coded around.
HOST_WHERE_NOBODY_STANDS = "to-camera"

# THE BAND A SHORT'S CAPTION MAY SIT IN, top and bottom as fractions of frame
# height, where the plate on screen publishes no `safe` band of its own. It is
# design's shorts band, 260 to 1560 of 1920: on a phone the title, the channel
# name and the buttons lie over the bottom of the frame and the search bar over
# the top. The old band, 78% to 92% of the frame, sat wholly under the buttons,
# so every caption in every short was partly covered.
CAPTION_BAND = (260 / 1920, 1560 / 1920)

# HOW FAR A PLATE MAY SHRINK TO KEEP ITS WORDS IN THE CLEAR AREA (item 27). A
# format that declares a `safe` band (the SHORT: 170 to 1,480 px of 1,920, the
# part of a phone YouTube draws nothing over) gets every plate placed so its
# filled text sits inside it: moved up first, then shrunk, never below this. A
# plate whose REQUIRED words need more is not fillable there, and the rotation
# takes another; its optional words outside the band are dropped. Optional
# words are kept by shrinking only as far as the second figure.
SAFE_MIN_SCALE = 0.85
SAFE_OPTIONAL_MIN_SCALE = 0.94

# The caption's type as a fraction of frame height, and the margins it is
# centred between as a fraction of frame width. The renderer burns the type at
# this size and `build_layers` places the box it sits in, so both read these:
# a box placed for one size and burned at another covers what it was kept off.
CAPTION_TYPE_FH = 0.030
CAPTION_SIDE_FW = 0.10

# How far a caption's box stays off anything it must not cover, as a fraction
# of frame height. Flush against a row of figures, a cream box reads as one
# more row of the table.
CAPTION_CLEARANCE_FH = 0.008

# A LANDSCAPE FRAME KEEPS ITS CAPTION WHERE IT HAS ALWAYS BEEN, the foot of its
# type this far up the frame. No phone lays buttons over a long's frame, and
# the long's captions are another item's, so a 16:9 cut through this engine
# gets a band with exactly one place in it.
LANDSCAPE_CAPTION_MARGIN_FH = 0.13

# How much of a standing figure's box his head can be in. He is seven heads
# tall (`kit/design-tokens.json`, proportion) with his crown at the top of the
# box; seated, the crown drops to about 1.9 heads down (seatedRatio 0.735).
# The top three heads hold it in every pose the kit draws. A framing publishes
# a `head` slot of its own and is read from that instead.
HOST_HEAD_SHARE = 3 / 7

# A row of type is never set below this fraction of the frame's height. Below
# it a figure is present but not readable, which is worse than absent — it
# looks like a design decision.
SLOT_TYPE_FLOOR_FH = MIN_TYPE_FH


@dataclass
class Layer:
    """One thing on screen, over one window of time.

    `shot_id` is carried so "no layer may outlive its shot" is checkable
    without reconstructing which span a layer came from, and `entry_key` so
    "every shot reached the plate the template names" is checkable against the
    registry rather than against the template that asked for it.
    """

    name: str
    kind: str            # ground|plate|fill|media|host|host3d|front|text|mark|caption
    shot_id: str
    t_start: float
    t_end: float
    x: int = 0
    y: int = 0
    w: int = 0
    h: int = 0
    path: Path | None = None            # a resolved image, for media layers
    entry_key: str = ""                 # the registry key this layer reached
    concept: str = ""                   # its family
    values: dict[str, str] = field(default_factory=dict)   # slot -> text
    frame_count: int = 1
    fps: int = 0
    loops: bool = False
    slot: str = ""
    text: str = ""                      # code-drawn type, bare-ground shots only
    size_fh: float = 0.0
    reveal_s: float = 0.0
    max_lines: int = 3
    halign: str = "center"
    lit: bool = True
    panel: bool = False
    z: int = 0
    # A close-up's piece of the plate (x0, y0, x1, y1, 0-1 from the top left),
    # blown up to the box and softened: what is behind the 3D Dennis when the
    # camera's lens is longer (`pipeline.dennis3d`). None is the whole plate.
    window: tuple[float, float, float, float] | None = None

    @property
    def dur(self) -> float:
        return self.t_end - self.t_start

    @property
    def moves(self) -> bool:
        """Whether this layer is redrawing rather than sitting there.

        A room's two-frame loop and a host strip both move. A static data
        plate does not, and its `max_hold_s` is what keeps it short rather
        than a wobble that made the measurement look better than the video.
        The 3D Dennis plays once through and is never still.
        """
        return bool((self.loops or self.kind == "host3d") and self.frame_count > 1)


class Resolver(Protocol):
    """Supplies the words and figures. Knows nothing about composition."""

    def text_for(self, src: str) -> str | None: ...
    def image_for(self, src: str) -> Path | None: ...
    def list_for(self, src: str) -> list[str] | None: ...


@dataclass
class BuildResult:
    layers: list[Layer]
    spans: list[Span]
    frame: tuple[int, int]
    aspect: str = ""
    unfilled: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    def for_shot(self, shot_id: str) -> list[Layer]:
        return [l for l in self.layers if l.shot_id == shot_id]

    def of_kind(self, kind: str) -> list[Layer]:
        return [l for l in self.layers if l.kind == kind]

    @property
    def plates_used(self) -> list[str]:
        return sorted({l.entry_key for l in self.layers if l.entry_key})


# ---------------------------------------------------------------------------
# Resolving what the template names
# ---------------------------------------------------------------------------

# TWO ANGLES OF ONE SPOT. `room/window-talk` is `window-wall` with him moved
# to the pane's left edge (design, rebuild-40): cut from one straight to the
# other and he jumps sideways in a room that did not move. For "never the same
# angle twice running" they are one angle.
SAME_SPOT = {"room/window-talk": "room/window-wall"}


def _spot(reg: Registry, key: str) -> str:
    """The spot a room key is shot from: its angle, its December twin and its
    same-spot sibling folded together."""
    stem = re.sub(r"-(16x9|9x16)$", "", reg.base_key(key))
    stem = stem[: -len("-christmas")] if stem.endswith("-christmas") else stem
    return SAME_SPOT.get(stem, stem)


def resolve_room(reg: Registry, role: str, aspect: str, *, seed: str,
                 step: int, after: str = "") -> Plate | None:
    """A room ROLE — `talk`, `establish`, `read` — to one of its angles.

    ROTATING, NOT DEFAULTING. The registry declares several angles per role
    and a template that names one angle gets it every time; straight-on
    eye-level plates cut like props sliding on a shelf. The seed is the
    video's, so two videos do not open on the same angle.

    THE STEP COUNTS THE ROLE'S OWN USES, NOT THE SHOT'S INDEX. Stepped by the
    shot's index, a role reached from the same place in every chapter — the
    opener and the landing, three shots apart — landed on the same parity
    every time: one long cut `window-wall` eleven times and never reached
    `doorway-wide` at all. Counted per role, every angle a role holds is cut
    to in turn. `after` is the room the previous room shot used, and the one
    thing a count cannot see: two roles that share an angle can hand it to two
    consecutive shots, so where the role has another, it takes the other.

    THE HOUR COMES OFF THE SEED AND THE ANGLE OFF THE STEP, which is not an
    arbitrary split. The seed is the video's and the step is the shot's, so
    reading the hour from the seed alone is what makes it hold still for the
    whole video while the angle keeps rotating under it. Deriving it from
    anything carrying `step` would cut dusk against night inside one video.
    Inside a render the registry is already viewed at the episode's hour, and
    `hour_for` answers with that whatever the seed.
    """
    hour = reg.hour_for(seed)
    keys = reg.angles_for(role, aspect, hour) or [
        stem for stem in reg.room_roles.get(role, ()) if stem in reg]
    resolved: list[Plate] = []
    for key in keys:
        got = reg.plate_at(key, hour)
        if got is not None:
            resolved.append(got)
    if not resolved:
        return None
    # The step rotates WITHIN a video; the seed decides where the rotation
    # starts, so two videos do not open on the same angle. The docstring said
    # both and the code did only the first — every short in the channel opened
    # on the same room.
    offset = (int(hashlib.sha256(seed.encode()).hexdigest(), 16)
              if seed else 0)
    picked = resolved[(offset + step) % len(resolved)]
    if after and _spot(reg, picked.key) == _spot(reg, after):
        for i in range(1, len(resolved)):
            other = resolved[(offset + step + i) % len(resolved)]
            if _spot(reg, other.key) != _spot(reg, after):
                return other
    return picked


def _fillable(variant, shot: Shot, plate: Plate, resolver: Resolver,
              reg: Registry, safe: tuple[int, int] | None = None) -> bool:
    """Would this plate actually compose, for THIS script?

    Asked by running the real fill rather than by re-deriving the rules, which
    matters more than it reads: `head`, `row-3` and `band-2` are the tag
    grammar's names and not slots any plate declares, so a hand-rolled "does it
    declare this slot" test rejects every numbers sheet in the kit, including
    the one the template already names.

    Two ways a plate is wrong for a video and both have to be caught before it
    is chosen rather than after:

    * it cannot take one of the binds — `build_fill` raises, and a raise here
      would take the render down over a drawing that was only ever one of
      several options;
    * a REQUIRED bind the script carries nothing for. `figures/big-number-l2`
      wants a detail line; a video with no verdict has none, so l2 is the wrong
      plate for it and `big-number-l1` is the right one.

    Optional binds, marked `?`, are neither: a blank row is the correct drawing
    and never a reason to reject the plate carrying it.
    """
    bind, lit, focus = variant.resolved(shot)
    probe = replace(shot, plate=plate.key, bind=bind, lit=lit, focus=focus,
                    alts=())
    try:
        values, unfilled, _skipped = _bound_values(probe, plate, resolver, reg)
    except Exception:                              # noqa: BLE001
        return False
    if unfilled:
        return False
    # A PICTURE IT NEEDS AND DOES NOT HAVE (item 34). `_bound_values` leaves
    # media to the compositor, so a media frame whose photo never came would
    # pass here and go up as an empty frame; required media is asked for now.
    for raw in bind.values():
        if raw.startswith(MEDIA_PREFIX) and resolver.image_for(
                raw[len(MEDIA_PREFIX):]) is None:
            return False
    # AND THE COPY HAS TO FIT THE BOXES THIS DRAWING RESERVES FOR IT.
    #
    # `check_budgets` refuses a required fill that runs over, so a rotation
    # that ignored the budgets would trade sameness for a render that fails on
    # the videos whose lines happen to be long — the worst possible trade,
    # because it fails AFTER the writing and only for some seeds.
    #
    # Rejected rather than trimmed: the same words fit the authored plate,
    # which is still in the set. So a long conclusion simply keeps the wide
    # sign-off card and a short one may rotate onto the narrow one.
    from pipeline.plate_frames import slot_limit

    for slot_name, value in values.items():
        slot = plate.slot(slot_name)
        if slot is None:
            continue
        # The WRAPPED limit too, not just `maxChars`. The sign-off line, a
        # quote body and a statement on the two-sided card all wrap, and a
        # check that read `maxChars` alone would answer "no limit" for exactly
        # the slots a long line overruns.
        limit = slot_limit(plate, slot, str(value))
        if limit and len(str(value)) > limit:
            return False
    # A lit band or a focus move that names nothing on this plate is not an
    # error — it just silently does not happen, which is a beat that reads as
    # a held frame. Reject the plate instead.
    # `all` and `read` name every band rather than one, so they are not
    # slots to look up.
    for name in (lit, focus):
        if name and name not in ("all", "read") and plate.slot(name) is None:
            return False
    # AND ITS WORDS HAVE TO FIT WHERE A PHONE SHOWS THEM (item 27).
    if safe:
        required = {n for n, src in bind.items() if not str(src).startswith("?")}
        if safe_placement(plate, values, required, _plate_frame(plate),
                          safe) is None:
            return False
    return True


def _plate_frame(plate: Plate) -> tuple[int, int]:
    """The frame a full-frame plate is placed in: its own canvas."""
    return (int(plate.canvas[0]), int(plate.canvas[1]))


def choose_variant(reg: Registry, shot: Shot, aspect: str, resolver: Resolver,
                   *, seed: str = "", avoid: "Collection[str]" = (),
                   used: "Collection[str]" = (),
                   safe: tuple[int, int] | None = None):
    """Which of a beat's interchangeable plates this video draws.

    THE WRITER CHOOSES NOTHING HERE AND THAT IS DELIBERATE. A SHORT is
    mass-produced: its beats are fixed so the character budgets can be stated
    up front and the cut has a shape that always holds. What was missing is
    that the PICTURE on a beat was fixed too, so every short of a format showed
    the same ten drawings in the same order, and 55 plates drawn at 9:16 had no
    route to a frame at all — the vertical templates never named them and
    `parser_short` ignores the inline tags a director would use in a LONG.

    Rotating here costs the writer nothing and costs the budgets nothing:
    `form._budgets` quotes the narrowest box across the whole set, so whatever
    is picked, the line fits.

    The authored plate is the floor. When every alternate is unresolvable in
    this kit or unfillable by this script it is what comes back, and its own
    failure to resolve stays the caller's error to raise.

    `used` is what THIS video has already drawn, in cut order (item 7), and
    it outranks `avoid`: the same layout twice in one short is sameness a
    viewer sees in fifty seconds, where a plate from last week's short is one
    they may never have seen. Both are preferences, so a beat with nothing
    else still draws; when every option is used, the one used longest ago.
    """
    import random

    variants = shot.variants
    if len(variants) <= 1:
        return variants[0] if variants else None
    primary = variants[0]

    usable: list[tuple[str, object]] = []
    for v in variants:
        try:
            plate = resolve_plate(reg, v.plate, aspect)
        except TemplateError:
            plate = None
        # AN ALTERNATE A KIT DOES NOT CARRY IS DROPPED, NOT RAISED ON. The kit
        # is swapped wholesale and the next drop retires plates by name; a
        # rotation that hard-failed on a retired alternate would turn every
        # swap into a render outage over a picture nothing needed.
        if plate is None or not _fillable(v, shot, plate, resolver, reg,
                                          safe=safe):
            continue
        # BY THE DRAWING, NOT THE HOUR. A dusk video resolves every name to a
        # dusk key, and a night video last week used the night key of the same
        # drawing; compared as keys they never match, so rotation would put the
        # same picture on the same beat two videos running. Base keys also keep
        # the pick itself off the hour: sorted hour keys do not always sort in
        # the order their drawings do.
        usable.append((reg.base_key(plate.key), v))
    if not usable:
        return primary

    keys = [k for k, _ in usable]
    # A drawing this video's own figures fill wins while this video has not
    # drawn it yet; the rotation then picks among those alone.
    last_used = {reg.base_key(k) for k in used}
    preferred = [k for k, v in usable
                 if getattr(v, "prefer", False) and k not in last_used]
    if preferred:
        keys = preferred
    if used:
        # Unused in this video first; when every option has been drawn, the
        # one drawn longest ago, so a layout never comes straight back.
        last = {reg.base_key(k): i for i, k in enumerate(used)}
        fresh = [k for k in keys if k not in last]
        if fresh:
            keys = fresh
        else:
            oldest = min(last[k] for k in keys)
            keys = [k for k in keys if last[k] == oldest]
    keys = _prefer_unused(keys, reg.base_keys(avoid))
    pick = random.Random(f"variant|{shot.id}|{seed}").choice(sorted(keys))
    return next(v for k, v in usable if k == pick)


def plan_variants(reg: Registry, shots: Sequence[Shot], aspect: str,
                  resolver: Resolver, *, seed: str = "",
                  avoid: "Collection[str]" = (),
                  safe: tuple[int, int] | None = None) -> dict[str, Any]:
    """Which drawing each shot with alternates gets, walking the cut in order.

    NO LAYOUT TWICE IN ONE SHORT WHERE THE BEAT HAS ANOTHER (item 7). The
    macro "who it hits" beat played the same quote card three times running,
    20 s of one layout, and a closing card could pick the quote card the
    comment had just used. Each pick here knows every drawing the shots
    before it drew, alternates and fixed plates alike, and steers off them.

    Worked out once for the whole cut, before the timing, so a long beat's
    punch-in (`punch_in_slot`) is asked of the plate `build_layers` then
    draws: both read this map rather than rolling the rotation themselves.
    The second part of a split beat is not here; it is part 1's drawing.
    """
    picks: dict[str, Any] = {}
    used: list[str] = []
    begin = getattr(resolver, "begin_shot", None)
    for shot in shots:
        if getattr(shot, "part", 0) == 2 or not shot.plate or shot.host \
                or shot.plate.startswith("room/"):
            continue
        name = shot.plate
        if shot.alts:
            if begin is not None:
                begin(shot)
            picked = choose_variant(reg, shot, aspect, resolver, seed=seed,
                                    avoid=avoid, used=used, safe=safe)
            picks[shot.id] = picked
            if picked is not None:
                name = picked.plate
        try:
            plate = resolve_plate(reg, name, aspect)
        except TemplateError:
            plate = None
        if plate is not None:
            used.append(reg.base_key(plate.key))
    return picks


def resolve_plate(reg: Registry, name: str, aspect: str) -> Plate | None:
    """A template's plate name against the registry, aspect-aware.

    A template may write `numbers-sheet-3r`, `numbers-sheet-3r-9x16` or the
    full `tables/numbers-sheet-3r-9x16`. The family is the kit's filing
    system, and the aspect is a property of the FORMAT rather than something
    a template should have to repeat on every line.
    """
    name = (name or "").strip()
    if not name:
        return None
    if name in reg:
        return reg.get(name)
    for candidate in (f"{name}-{aspect}" if aspect else "", name):
        if not candidate:
            continue
        hits = [k for k in reg.keys() if k.split("/", 1)[1] == candidate]
        if len(hits) == 1:
            return reg.get(hits[0])
        if hits:
            raise TemplateError(
                f"plate {name!r} is ambiguous — it is "
                f"{' and '.join(sorted(hits))}. Name the family.")
    return None


def _fit(plate: Plate, frame: tuple[int, int]) -> tuple[int, int]:
    """The plate at its largest inside the frame, aspect preserved."""
    fw, fh = frame
    pw, ph = plate.delivered
    k = min(fw / max(pw, 1), fh / max(ph, 1))
    return max(int(pw * k), 1), max(int(ph * k), 1)


def sets_large_type(plate: Plate | None, values: dict, placed_h: int, fh: int) -> bool:
    """Does this plate, as filled, set type big enough to be the frame's subject?

    Large type and the caption band never share a shot. The parser holds a
    template to that for type the TEMPLATE sets, and the payoff says
    `captions: false` by hand because `big-number` sets its figure at 13% of
    the frame. An alternate cannot say it: the flag is the shot's, and the
    rotation picks the plate after the template is written — so the move on
    the day, a 166-unit figure on a 1920 canvas, would come up with a caption
    running under it one video in three. Asked of the drawing instead, per
    filled slot, at the size the plate's own type roles declare.
    """
    if plate is None or not values or not plate.canvas[1] or not fh:
        return False
    k = placed_h / plate.canvas[1] / fh
    for name, value in values.items():
        slot = plate.slot(name)
        if slot is None or not str(value).strip():
            continue
        size = (plate.type_roles.get(slot.role) or {}).get("size")
        if size and float(size) * k >= LARGE_TYPE_FH:
            return True
    return False


def _slot_in_frame(plate: Plate, slot_name: str,
                   placed: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """A declared slot's box, in frame pixels, for a plate placed at `placed`."""
    slot = plate.require_slot(slot_name)
    px, py, pw, ph = placed
    sx, sy, sw, sh = slot.scaled()
    kx = pw / max(plate.delivered[0], 1)
    ky = ph / max(plate.delivered[1], 1)
    return (int(px + sx * kx), int(py + sy * ky),
            max(int(sw * kx), 1), max(int(sh * ky), 1))


def _text_rows(plate: Plate, values: dict, names,
              placed: tuple[int, int, int, int]) -> tuple[int, int] | None:
    """The rows the filled text slots in `names` span, as placed: (top, foot)."""
    rows = []
    for name in names:
        slot = plate.slot(name)
        if (slot is None or slot.region or slot.control
                or not str(values.get(name, "")).strip()):
            continue
        _, y, _, h = _slot_in_frame(plate, name, placed)
        rows.append((y, y + h))
    if not rows:
        return None
    return min(r[0] for r in rows), max(r[1] for r in rows)


def _fit_rows(span: tuple[int, int], safe: tuple[int, int],
              placed: tuple[int, int, int, int], min_scale: float
              ) -> tuple[int, int, int, int] | None:
    """`placed` moved, and shrunk if it must be, so `span` lands inside `safe`.

    Shrunk about the plate's own horizontal centre, so a left column stays a
    left column. None when it would take more shrinking than `min_scale`.
    """
    top, foot = span
    s_top, s_foot = safe
    px, py, pw, ph = placed
    k = min(1.0, (s_foot - s_top) / max(foot - top, 1))
    if k < min_scale:
        return None
    nw, nh = int(round(pw * k)), int(round(ph * k))
    nx = px + (pw - nw) // 2
    # Where the span's rows land at this size, before any move.
    t0 = py + (top - py) * k
    f0 = py + (foot - py) * k
    dy = 0.0
    if f0 > s_foot:
        dy = s_foot - f0
    if t0 + dy < s_top:
        dy = s_top - t0
    return (nx, int(round(py + dy)), nw, nh)


def safe_placement(plate: Plate, values: dict, required, frame: tuple[int, int],
                   safe: tuple[int, int] | None,
                   placed: tuple[int, int, int, int] | None = None,
                   ) -> tuple[tuple[int, int, int, int], list[str]] | None:
    """Where a plate goes so its words sit in the format's clear area.

    `(placed, dropped)`: the placement, and the optional slots whose words
    still fall outside it and are left empty. None when the REQUIRED words
    cannot be brought inside without shrinking past `SAFE_MIN_SCALE`.
    Without a `safe` band the plate keeps `placed`, and nothing is dropped.
    """
    base = placed or (0, 0, *frame)
    if not safe:
        return base, []
    filled = [n for n in values if str(values.get(n, "")).strip()]
    need = [n for n in filled if n in required]
    everything = _text_rows(plate, values, filled, base)
    if everything is None:
        return base, []
    got = _fit_rows(everything, safe, base, SAFE_OPTIONAL_MIN_SCALE)
    if got is None:
        must = _text_rows(plate, values, need, base)
        got = (_fit_rows(must, safe, base, SAFE_MIN_SCALE) if must is not None
               else base)
        if got is None:
            return None
    dropped = []
    for name in filled:
        if name in required:
            continue
        span = _text_rows(plate, values, [name], got)
        if span is not None and (span[0] < safe[0] - 1 or span[1] > safe[1] + 1):
            dropped.append(name)
    return got, dropped


def _on_the_ink(plate: Plate, values: dict, reg: Registry) -> Plate:
    """`plate` with each filled text slot cut down to the type it sets.

    A MOVE IN IS ON THE WORDS, NOT THE BOX THEY MAY USE. Rebuild-41 stretched
    a phone plate's text boxes across the whole clear width, so moved in on
    the box the payoff's "$496M" came out at 1.02x, under `PUNCH_MIN_SCALE`,
    and no long beat on a card could split; the other boxes, full width too,
    read as sliced by any move at all. Framed by their ink, a short figure
    gets its close-up and a paragraph that fills its box still frames as the
    box. Only the geometry asks this: the plate drawn is the plate itself.
    """
    from pipeline.plate_frames import drawn_box

    settings = None
    slots = dict(plate.slots)
    s = max(int(plate.export_scale or 1), 1)
    for name, value in values.items():
        slot = plate.slot(name)
        if slot is None or not slot.is_text or not str(value or "").strip():
            continue
        settings = settings or _settings()
        try:
            got = drawn_box(plate, slot, str(value), settings, reg)
        except Exception:                          # noqa: BLE001
            got = None
        if got:
            slots[name] = replace(slot, x=int(got[0] / s), y=int(got[1] / s),
                                  w=max(int(round(got[2] / s)), 1),
                                  h=max(int(round(got[3] / s)), 1))
    return replace(plate, slots=slots)


# How close to the frame's side a moved-in word may come. A punch-in that
# put a card's body against the left edge read as cropped even with every
# letter on screen.
PUNCH_EDGE = 0.04


def _focus_placement(plate: Plate, slot_name: str,
                     stage: tuple[int, int, int, int],
                     placed: tuple[int, int, int, int],
                     max_scale: float = FOCUS_MAX_SCALE,
                     ) -> tuple[int, int, int, int]:
    """The plate moved in on one of its slots — and never past the edges of
    what it has to show.

    The zoom is bounded by the frame's WIDTH, not only by the target height. A
    vertical sheet's row band is 1044 of 1080 canvas units wide: scaled until
    it filled 62% of the frame's height it came out at 1.4x, and the last three
    columns of every row went off the right-hand edge. A row you cannot see the
    figures on is not a row anybody moved in on. Where the slot is already full
    width the move is a PAN — the composition still changes, and every figure
    stays on screen.

    And it stops `PUNCH_EDGE` short of the sides: a quote card's body moved
    in until it touched both edges was a cut, not a closer look, so the move
    goes as far as the slot stays clear of them.
    """
    gx, gy, gw2, gh2 = stage
    w, h = placed[2], placed[3]
    sx, sy, sw, sh_px = _slot_in_frame(plate, slot_name, placed)
    by_height = (gh2 * FOCUS_FILL) / max(sh_px, 1)
    by_width = gw2 * (1 - 2 * PUNCH_EDGE) / max(sw, 1)
    k = max(min(by_height, by_width, FOCUS_MAX_SCALE, max_scale), 1.0)
    nw, nh = int(w * k), int(h * k)
    base = (gx + (gw2 - nw) // 2, gy + (gh2 - nh) // 2, nw, nh)
    sx, sy, sw, sh_px = _slot_in_frame(plate, slot_name, base)
    nx = base[0] + (gx + gw2 // 2 - (sx + sw // 2))
    ny = base[1] + (gy + gh2 // 2 - (sy + sh_px // 2))
    # Never open a gap at an edge: a plate larger than its stage covers it,
    # and one that is not stays centred on that axis.
    nx = (min(gx, max(nx, gx + gw2 - nw)) if nw >= gw2
          else gx + (gw2 - nw) // 2)
    ny = (min(gy, max(ny, gy + gh2 - nh)) if nh >= gh2
          else gy + (gh2 - nh) // 2)
    return (nx, ny, nw, nh)


def _move_in(plate: Plate, name: str, values: dict, reg: Registry,
             stage: tuple[int, int, int, int], placed: tuple[int, int, int, int],
             frame: tuple[int, int], safe: tuple[int, int] | None = None,
             ) -> tuple[int, int, int, int] | None:
    """The closest move in on `name`'s words that slices none of the others,
    or None when even `PUNCH_MIN_SCALE` would.

    AS FAR AS IT CAN, NOT ALL OR NOTHING. One zoom was tried, the one that
    fills the frame with the slot, and since rebuild-41 filled a phone
    plate's frame with its words, that one slices a neighbour on every card
    and no long beat could split; a little less close keeps them whole.
    """
    inked = _on_the_ink(plate, values, reg)
    close = _focus_placement(inked, name, stage, placed)
    k = close[2] / max(placed[2], 1)
    while k >= PUNCH_MIN_SCALE:
        if not _cuts_a_filled_slot(inked, values, close, frame, safe=safe):
            return close
        k *= 0.92
        close = _focus_placement(inked, name, stage, placed, max_scale=k)
    return None


# A punch-in smaller than this barely changes the picture, so the beat would
# still read as one held composition — the thing the split exists to end.
PUNCH_MIN_SCALE = 1.1

# Where the kit says the eye goes on a plate, in the order a punch-in asks:
# the passage a reader is on, then the figure that counts up.
PUNCH_MOVES = ("highlight", "count-up")


def punch_in_slot(reg: Registry, shot: Shot, frame: tuple[int, int],
                  resolver: Resolver, *, aspect: str = "", seed: str = "",
                  avoid: "Collection[str]" = (),
                  variants: "dict[str, Any] | None" = None,
                  safe: tuple[int, int] | None = None) -> str | None:
    """Which slot the second picture of a long beat moves in on, or None.

    `resolve_spans` asks this for a beat that runs past its ceiling. The
    answer is the shot's own `focus` when it has one — a numbers step already
    names its row — and otherwise where the kit's own motion anchors put the
    eye: the `highlight` slot, then the `count-up` one. None means the beat
    holds.

    ASKED OF THE PLATE THIS VIDEO WILL ACTUALLY DRAW. The rotation is run the
    way `build_layers` runs it — same seed, same recent plates — because the
    authored plate's slots are not the alternate's, and a focus naming a slot
    the drawn plate lacks is a punch-in that silently does not happen.

    A motion anchor is a hint, not a promise, so it is refused where the move
    would make things worse than the hold it replaces:

    * the slot carries nothing for this script — an unbound date box on the
      sign-off card would fill the frame with an empty rectangle;
    * the move barely moves — under `PUNCH_MIN_SCALE` it is the same picture;
    * the move cuts a filled slot in half at the frame's edge — the first
      figure of a table at 2.4x leaves every other figure sliced. A slot moved
      wholly out of frame is fine: that is what moving in means.
    """
    if not shot.plate or shot.host or shot.plate.startswith("room/"):
        return None
    begin = getattr(resolver, "begin_shot", None)
    if begin is not None:
        begin(shot)
    if shot.alts:
        picked = (variants.get(shot.id) if variants is not None
                  and shot.id in variants
                  else choose_variant(reg, shot, aspect, resolver, seed=seed,
                                      avoid=avoid, safe=safe))
        if picked is not None and picked.plate != shot.plate:
            bind, lit, focus = picked.resolved(shot)
            shot = replace(shot, plate=picked.plate, alts=(), bind=bind,
                           lit=lit, focus=focus)
    try:
        plate = resolve_plate(reg, shot.plate, aspect)
    except TemplateError:
        return None
    if plate is None:
        return None
    if shot.focus and plate.slot(shot.focus) is not None:
        return shot.focus
    try:
        values, _unfilled, _skipped = _bound_values(shot, plate, resolver, reg)
    except Exception:                              # noqa: BLE001
        return None
    fw, fh = frame
    w, h = _fit(plate, frame)
    wide = ((fw - w) // 2, (fh - h) // 2, w, h)
    from pipeline.moves import is_one_figure

    for move in PUNCH_MOVES:
        name = (plate.motion.get(move) or {}).get("slot")
        if not name or plate.slot(name) is None:
            continue
        if not str(values.get(name, "")).strip():
            continue
        # The count-up anchor is there to name what the plate sets biggest.
        # Since rebuild-41's 9:16 type floor set units and kickers at the
        # figures' size, design's anchor lands on "Free cash flow, FY21 to
        # LTM" on dozens of plates; a close-up on the plate's smallest line
        # that is not a figure is a close-up on a caption.
        if move == "count-up" and not is_one_figure(str(values.get(name, ""))) \
                and _type_size(plate, name) <= _smallest_type(plate):
            continue
        if _move_in(plate, name, values, reg, (0, 0, fw, fh), wide, frame,
                    safe=safe) is None:
            continue
        return name
    return None



def _type_size(plate: Plate, name: str) -> float:
    slot = plate.slot(name)
    return float(((plate.type_roles or {}).get(slot.role) or {}).get("size") or 0) if slot else 0.0


def _smallest_type(plate: Plate) -> float:
    """The smallest size a text slot on `plate` is set at."""
    sizes = [_type_size(plate, n) for n, sl in plate.slots.items() if sl.is_text]
    return min((z for z in sizes if z), default=0.0)


def _cuts_a_filled_slot(plate: Plate, values: dict,
                        placed: tuple[int, int, int, int],
                        frame: tuple[int, int],
                        safe: tuple[int, int] | None = None) -> bool:
    """Does this placement leave a filled slot part on and part off the frame?

    "On" means clear of the frame's sides by `PUNCH_EDGE` and, where the
    format declares a clear area (item 27), inside it: a move that lands a
    word under YouTube's title is a cut, not a punch-in.

    A band is left out: it is the lit row's highlight, drawn edge to edge, and
    the figures in it are slots of their own that this checks one by one.
    """
    fw, fh = frame
    m = int(fw * PUNCH_EDGE)
    top, bottom = safe if safe else (0, fh)
    for name, value in values.items():
        slot = plate.slot(name)
        if slot is None or slot.is_band or not str(value).strip():
            continue
        x, y, w, h = _slot_in_frame(plate, name, placed)
        if slot.region or slot.control:
            inside = x >= 0 and y >= 0 and x + w <= fw and y + h <= fh
        else:
            inside = (x >= m and x + w <= fw - m
                      and y >= top and y + h <= bottom)
        outside = x + w <= 0 or y + h <= 0 or x >= fw or y >= fh
        if not inside and not outside:
            return True
    return False


def _arrange(n: int, how: str, frame: tuple[int, int],
             box: tuple[int, int, int, int] | None = None
             ) -> list[tuple[int, int, int, int]]:
    """`n` equal boxes down a column or across a row, inside `box`."""
    fw, fh = frame
    x0, y0, w, h = box or (0, 0, fw, fh)
    if n <= 0:
        return []
    if how == "row":
        step = w // n
        return [(x0 + i * step, y0, step, h) for i in range(n)]
    step = h // n
    return [(x0, y0 + i * step, w, step) for i in range(n)]


# ---------------------------------------------------------------------------
# Building the layer list
# ---------------------------------------------------------------------------

MEDIA_PREFIX = "media."


def _settings():
    from config import Settings
    return Settings(_env_file=None)


def build_layers(fmt: Format, spans: Sequence[Span], resolver: Resolver,
                 reg: Registry, *, aspect: str = "",
                 seed: str = "", avoid: "Collection[str]" = (),
                 words: Sequence[Any] = (),
                 variants: "dict[str, Any] | None" = None) -> BuildResult:
    """Turn the template and the script into the ordered layer list.

    `avoid` is what the last few renders already used. It steers the host and
    framing picks off those where the kit offers an alternative, so two
    consecutive videos do not open on the same pose — a preference the
    registry drops the moment a role has nothing else to give.

    `words` is the voice-over's word timings, when the caller has them. A
    host shot is then cast from what is said during it (`host.cast_pose`): a
    pose that means something — a count, a citation, a shrug — is chosen by
    the words rather than by seed, on a room it was drawn for. Without them
    every host is picked by his role, as before.

    `variants` is the cut's plan of which drawing each beat gets
    (`plan_variants`); worked out here from the spans when not given.
    """
    frame = fmt.frame
    fw, fh = frame
    aspect = aspect or getattr(fmt, "aspect", "") or ""
    safe = getattr(fmt, "safe", None)
    if variants is None:
        variants = plan_variants(reg, [sp.shot for sp in spans], aspect,
                                 resolver, seed=seed, avoid=avoid, safe=safe)
    layers: list[Layer] = []
    unfilled: list[str] = []
    skipped: list[str] = []
    # How often each room role has been cut to so far, and the room the last
    # room shot was in — `resolve_room` rotates on both.
    room_uses: dict[str, int] = {}
    last_room = ""
    # Who has stood in the cut so far, and in the shot before: a cast pose
    # keeps to its `limit` across the video and is never cut to twice running.
    # The CLOSE is the last shot that puts him on screen.
    host_used: dict[str, int] = {}
    last_host = ""
    closing = next((sp.shot.id for sp in reversed(spans) if sp.shot.host), "")
    # Part 1 of each split beat as drawn, for its part 2 to be drawn from.
    drawn: dict[str, Shot] = {}

    for span_index, span in enumerate(spans):
        shot = span.shot
        t0, t1 = span.start, span.end
        # A resolver may need to know which shot it is answering for — the
        # LONG serves a different chapter's words per shot. Optional, so a
        # resolver that does not care implements nothing.
        begin = getattr(resolver, "begin_shot", None)
        if begin is not None:
            begin(shot)

        # -- the ground. Every frame has paper under it; plates are
        #    transparent PNGs and would composite onto nothing otherwise.
        layers.append(Layer(name=f"{shot.id}:ground", kind="ground",
                            shot_id=shot.id, t_start=t0, t_end=t1,
                            w=fw, h=fh, z=0))

        plate: Plate | None = None
        placed: tuple[int, int, int, int] | None = None
        plate_large = False
        # The area the plate owns, and where the host stands if he is not on a
        # room. A one-up shot gives the plate the whole frame and the host
        # nothing to be beside; a two-shot splits it.
        stage: tuple[int, int, int, int] = (0, 0, fw, fh)
        host_column: tuple[int, int, int, int] | None = None
        graphic_side = ""

        # -- WHICH DRAWING THIS BEAT GETS. A shot may name alternates, and the
        #    one picked brings its own bind map with it, so everything below —
        #    the slot fills, the lit band, the focus move, the budgets — reads
        #    the chosen variant rather than the authored one. Swapping the shot
        #    here rather than threading a variant through twenty lines is what
        #    keeps a plate with differently-named slots from being a special
        #    case in each of them.
        #
        #    THE SECOND PART OF A SPLIT BEAT IS THE SAME DRAWING, CLOSER. It is
        #    its own shot with its own id, and the rotation seeds on the id, so
        #    left to itself it would roll again and could cut from one headline
        #    band to a different one mid-sentence. It takes the plate, binds
        #    and lit band part 1 was drawn with, and keeps only its own focus.
        first = drawn.get(shot.part_of) if shot.part == 2 else None
        if first is not None:
            # A sheet that lit its rows as they were read ends part 1 with
            # every row up, so the close-up opens on all of them lit.
            shot = replace(shot, plate=first.plate, alts=(),
                           bind=dict(first.bind), captions=first.captions,
                           lit="all" if first.lit == "read" else first.lit)
        elif shot.plate and shot.alts:
            picked = (variants.get(shot.id) if shot.id in variants
                      else choose_variant(reg, shot, aspect, resolver,
                                          seed=seed, avoid=avoid, safe=safe))
            if picked is not None and picked.plate != shot.plate:
                bind, lit, focus = picked.resolved(shot)
                shot = replace(shot, plate=picked.plate, alts=(),
                               bind=bind, lit=lit, focus=focus,
                               captions=(shot.captions if picked.captions is None
                                         else picked.captions))
        # Part 1 is the WIDE picture: the move in is what part 2 is for, and
        # a part 1 already moved in would make the cut between them a cut to
        # the same frame.
        if shot.part == 1:
            drawn[shot.id] = shot
            shot = replace(shot, focus=None)

        # -- the plate. `None` is a real value: a bare-ground shot.
        if shot.plate:
            # `room/<role>` is a ROLE, not a key: the template says what kind
            # of angle this beat wants and the registry picks one, rotating.
            role = shot.plate.split("/", 1)[1] if shot.plate.startswith("room/") else ""
            if role and role in reg.room_roles:
                plate = resolve_room(reg, role, aspect, seed=seed,
                                     step=room_uses.get(role, 0),
                                     after=last_room)
                room_uses[role] = room_uses.get(role, 0) + 1
            else:
                plate = resolve_plate(reg, shot.plate, aspect)
            if plate is not None and plate.family == "room":
                last_room = plate.key
            if plate is None:
                raise TemplateError(
                    f"{fmt.name}/{shot.id}: plate {shot.plate!r} is not in the "
                    f"kit. The registry is the only library — a name that "
                    f"resolves to nothing draws nothing, and an empty area on "
                    f"screen looks like a design choice.")
            # -- A TWO-SHOT IS A SPLIT FRAME, NOT A MAN OVER A CHART. A shot
            #    carrying both a content plate and a host drew the plate at
            #    the full frame and then composited him into the middle of
            #    it, over the thing he is discussing. The graphic takes a
            #    column and he takes the other; which side alternates, so
            #    consecutive two-shots are not the same picture.
            #
            #    Only where the frame is wider than it is tall. A vertical
            #    two-shot side by side gives each of them 46% of 1080, and a
            #    plate drawn for a phone is not readable in half of one.
            #
            #    NEVER ON AN ANNOTATED BEAT. A mark is drawn at the scale of
            #    the thing it marks, and half a frame is where a nib stops
            #    being legible — which is a composition fault, not a reason to
            #    thicken every stroke in the kit.
            if (shot.host and plate.family != "room" and not shot.marks
                    and plate.slot(shot.host.slot) is None and fw > fh):
                if len(plate.slots) > TWO_SHOT_MAX_SLOTS:
                    raise TemplateError(
                        f"{fmt.name}/{shot.id}: {plate.key} declares "
                        f"{len(plate.slots)} slots and cannot share the frame "
                        f"with the host. A two-shot draws it at "
                        f"{TWO_SHOT_GRAPHIC:.0%} of the width, so its type "
                        f"lands at {TWO_SHOT_GRAPHIC:.0%} of the size it was "
                        f"drawn at. Drop the host from this shot and let the "
                        f"evidence have the frame.")
                graphic_side = "left" if span_index % 2 else "right"
                gw = int(fw * TWO_SHOT_GRAPHIC)
                stage = ((0 if graphic_side == "left" else fw - gw),
                         0, gw, fh)
                host_column = ((gw, 0, fw - gw, fh)
                               if graphic_side == "left" else (0, 0, fw - gw, fh))
            w, h = _fit(plate, (stage[2], stage[3]))
            placed = (stage[0] + (stage[2] - w) // 2,
                      stage[1] + (stage[3] - h) // 2, w, h)

            # -- what goes in its slots. The renderer draws the plate WITH
            #    these; nothing here sets type.
            values, missing, gone = _bound_values(shot, plate, resolver, reg)
            unfilled += missing
            skipped += gone

            # KEEP ITS WORDS WHERE A PHONE SHOWS THEM (item 27). A format with
            # a `safe` band places each plate so its filled text sits inside
            # it, and leaves empty the optional words that still would not.
            # Never on a room: the set is not text, and he stands where he
            # stands.
            if safe and plate.family != "room" and not host_column:
                required = {n for n, src in shot.bind.items()
                            if not str(src).startswith("?")}
                got = safe_placement(plate, values, required, frame, safe,
                                     placed)
                if got is not None:
                    placed, out_of_view = got
                    w, h = placed[2], placed[3]
                    for name in out_of_view:
                        values.pop(name, None)
                        skipped.append(f"{shot.id}.{name} <- outside the "
                                       f"clear area")

            # MOVING IN ON A SLOT. Without this a walk down a list is one wide
            # shot with a rectangle migrating down it, which a viewer reads as
            # a single held composition. The geometry is `_focus_placement`.
            if shot.focus and plate.slot(shot.focus) is not None:
                # A long beat's second part moves in as far as its words stay
                # whole, the way `punch_in_slot` chose it.
                placed = ((shot.part == 2 and _move_in(plate, shot.focus, values, reg,
                                                       stage, placed, (fw, fh), safe=safe))
                          or _focus_placement(_on_the_ink(plate, values, reg),
                                              shot.focus, stage, placed))
                w, h = placed[2], placed[3]

            plate_large = sets_large_type(plate, values, placed[3], fh)

            layers.append(Layer(
                name=f"{shot.id}:plate:{plate.key}", kind="plate",
                shot_id=shot.id, t_start=t0, t_end=t1,
                x=placed[0], y=placed[1], w=w, h=h,
                entry_key=plate.key, concept=plate.family, values=values,
                frame_count=plate.frame_count, fps=plate.fps or 0,
                loops=plate.animated and not plate.plays_once, z=10))

        # -- nested plates and foreign media, into a slot of the shot's plate
        for fill_index, (slot_name, src) in enumerate(shot.bind.items()):
            optional = src.startswith("?")
            src = src.lstrip("?")
            if not src.startswith(("plate.", MEDIA_PREFIX)):
                continue                      # an ordinary slot fill: above
            box = None
            if plate is not None and plate.slot(slot_name) is not None:
                box = _slot_in_frame(plate, slot_name, placed or (0, 0, fw, fh))
            enter_at = min(t0 + fill_index * shot.stagger_s, max(t1 - 0.3, t0))

            if src.startswith("plate."):
                nested = resolve_plate(reg, src.split(".", 1)[1], aspect)
                if nested is None:
                    raise TemplateError(
                        f"{fmt.name}/{shot.id}: nested plate {src!r} is not "
                        f"in the kit")
                bw, bh = (box[2], box[3]) if box else (fw, fh)
                k = min(bw / nested.delivered[0], bh / nested.delivered[1])
                nw, nh = int(nested.delivered[0] * k), int(nested.delivered[1] * k)
                nx = (box[0] + (bw - nw) // 2) if box else (fw - nw) // 2
                ny = (box[1] + (bh - nh) // 2) if box else (fh - nh) // 2
                layers.append(Layer(
                    name=f"{shot.id}:fill:{slot_name}", kind="fill",
                    shot_id=shot.id, t_start=enter_at, t_end=t1,
                    x=nx, y=ny, w=nw, h=nh, slot=slot_name,
                    entry_key=nested.key, concept=nested.family,
                    frame_count=nested.frame_count, fps=nested.fps or 0,
                    loops=nested.animated and not nested.plays_once, z=20))
                continue

            # Foreign media. It never lands on the ground bare — a photograph
            # full-frame destroys the drawn surface everything else is built
            # on — so the template binds it into a slot, and where it has none
            # the renderer puts it in a frames/ plate.
            path = resolver.image_for(src[len(MEDIA_PREFIX):])
            if path is None:
                if not optional:
                    unfilled.append(f"{shot.id}.{slot_name} <- {src}")
                else:
                    skipped.append(f"{shot.id}.{slot_name} <- {src}")
                continue
            bx = box or (int(fw * 0.08), int(fh * 0.22),
                         int(fw * 0.84), int(fh * 0.46))
            layers.append(Layer(
                name=f"{shot.id}:media:{slot_name}", kind="media",
                shot_id=shot.id, t_start=enter_at, t_end=t1,
                x=bx[0], y=bx[1], w=bx[2], h=bx[3], slot=slot_name,
                path=path, z=20))

        # -- a repeated row: one box per item, down the slot the template names
        if shot.repeat is not None:
            layers += _repeat_layers(shot, plate, placed, frame, resolver, t0, t1)

        # -- the host
        if shot.host:
            host_layer = _host_layer(reg, shot, plate, placed, frame, t0, t1,
                                     seed=seed, column=host_column,
                                     avoid=avoid,
                                     words=[w for w in words
                                            if t0 <= w.start < t1],
                                     closing=shot.id == closing,
                                     used=host_used, previous=last_host)
            if host_layer is not None:
                host_used[host_layer.entry_key] = (
                    host_used.get(host_layer.entry_key, 0) + 1)
                last_host = host_layer.entry_key
                layers.append(host_layer)
                front = _front_layer(reg, shot, plate, placed, host_layer)
                if front is not None:
                    layers.append(front)

        # -- type, for a shot with no plate to put it in
        for spec in shot.text:
            body = resolver.text_for(spec.src)
            if not body:
                skipped.append(f"{shot.id}.{spec.name} <- {spec.src}")
                continue
            bx = _text_box(spec, frame)
            layers.append(Layer(
                name=f"{shot.id}:text:{spec.name}", kind="text",
                shot_id=shot.id, t_start=t0, t_end=t1,
                x=bx[0], y=bx[1], w=bx[2], h=bx[3],
                size_fh=spec.size_fh, text=body, reveal_s=spec.draw_on_s,
                slot=spec.color, halign=spec.halign,
                max_lines=spec.max_lines, z=60))

        # -- marks land after the thing they mark. The template grammar is
        #    `kind` and `target` (`shots.MarkSpec`); this read `style` and
        #    `on`, so the first template to declare a mark would have been
        #    an AttributeError mid-build.
        for spec in shot.marks:
            target = None
            if plate is not None and plate.slot(spec.target) is not None:
                target = _slot_in_frame(plate, spec.target,
                                        placed or (0, 0, fw, fh))
            if target is None:
                skipped.append(f"{shot.id}.mark:{spec.kind} <- {spec.target}")
                continue
            layers.append(Layer(
                name=f"{shot.id}:mark:{spec.name or spec.kind}", kind="mark",
                shot_id=shot.id,
                t_start=min(t0 + spec.after_s, t1), t_end=t1,
                x=target[0], y=target[1], w=target[2], h=target[3],
                slot=spec.kind, z=70))

        # -- captions. Not under display type, whoever set it: the template's
        #    own large type or a figure the chosen plate sets at that size.
        #
        #    PLACED PER SHOT, inside the band the phone leaves clear and off
        #    everything this shot is showing (`place_caption`). The layer's
        #    box IS the caption's box, and the renderer burns each line where
        #    its shot's layer says.
        if shot.captions and not shot.has_large_type and not plate_large:
            from pipeline.rasters import caption_box_height

            box_h = caption_box_height(int(fh * CAPTION_TYPE_FH))
            side = int(fw * CAPTION_SIDE_FW)
            band = caption_band(plate, frame, box_h, safe=safe)
            cy, covers = place_caption(
                band, caption_obstacles(
                    reg, [l for l in layers if l.shot_id == shot.id]),
                frame, box_h)
            if covers:
                log.warning(
                    "%s: nothing in the caption band (%d-%d px) is clear, so "
                    "the caption goes where it covers least, %d-%d px, over %s",
                    shot.id, band[0], band[1], cy, cy + box_h,
                    ", ".join(covers[:6]) + (f" and {len(covers) - 6} more"
                                             if len(covers) > 6 else ""))
            layers.append(Layer(
                name=f"{shot.id}:caption", kind="caption", shot_id=shot.id,
                t_start=t0, t_end=t1,
                x=side, y=cy, w=fw - 2 * side, h=box_h, z=80))

    # -- THE ONE MEME, when the format has a place for it and the library had
    #    something that fits. Built after every shot rather than inside the
    #    loop, because whether it fits in time depends on where the payoff
    #    falls, and that is usually another shot's span.
    layers += _meme_layers(spans, resolver, reg, frame, aspect, seed=seed,
                           avoid=avoid, skipped=skipped)

    layers.sort(key=lambda l: (l.t_start, l.z))
    return BuildResult(layers=layers, spans=list(spans), frame=frame,
                       aspect=aspect, unfilled=unfilled, skipped=skipped)


# ---------------------------------------------------------------------------
# The short's one meme
# ---------------------------------------------------------------------------

# What a template's meme place asks the resolver for. The resolver answers
# with a still from the owned library or with nothing (`memes.choose_for_short`).
MEME_SRC = "meme"

# How long the meme holds. Under a second it is a flash nobody reads; past a
# second and a half it has become a beat of its own, and the sentence under it
# has moved on to something the meme is not about.
MEME_HOLD_S = (1.0, 1.5)

# At most this share of the span it overlays. The beat belongs to its own
# plate: a meme taking half of the verdict is the verdict told as a joke.
MEME_SHARE = 1 / 3

# THE PAYOFF LANDS FIRST. `sound.DROP_S` of voice alone before the payoff cut,
# the hit on the number at the cut, and then this long for the number to be
# read before anything is allowed over it. A meme inside that window steps on
# the one moment of the short the mix is built around.
MEME_AFTER_PAYOFF_S = 1.5

# Over everything the shot draws — the host (40), type (60), marks (70) —
# because for its second and a half the meme IS the frame. Captions are
# burned after the frames are drawn, so the line under it still reads.
MEME_Z = 90


def payoff_guards(spans: Sequence[Span]) -> list[tuple[float, float]]:
    """The windows no meme may touch: each payoff's drop, hit and first read.

    Read off `sound.PAYOFF_SHOTS` and `sound.DROP_S` rather than restated
    here. The mix decides where the silence goes, and a second copy of the
    rule is the one that goes stale when the mix changes.
    """
    from pipeline.sound import DROP_S, PAYOFF_SHOTS

    return sorted((max(sp.start - DROP_S, 0.0), sp.start + MEME_AFTER_PAYOFF_S)
                  for sp in spans if sp.shot.id in PAYOFF_SHOTS)


def meme_window(span: Span, spans: Sequence[Span]
                ) -> tuple[float, float] | None:
    """When the meme is on screen inside `span`, or None when it cannot be.

    OVERLAID, NEVER INSERTED. The meme takes the start or the end of an
    existing span, so every other shot stays on the words it is bound to.
    It never slides off the end it was placed at, and it never touches a
    payoff guard: a meme that would land in the drop, on the hit or over
    the number's first read is not drawn at all. Nor is one with under a
    second to hold.
    """
    at = span.shot.meme.at if span.shot.meme else "end"
    t0, t1 = span.start, span.end
    hold = min(MEME_HOLD_S[1], (t1 - t0) * MEME_SHARE)
    if hold < MEME_HOLD_S[0] - 1e-6:
        return None
    start, end = (t1 - hold, t1) if at == "end" else (t0, t0 + hold)
    if any(a < end and b > start for a, b in payoff_guards(spans)):
        return None
    return start, end


def _meme_frame(reg: Registry, aspect: str, *, seed: str,
                avoid: "Collection[str]") -> Plate | None:
    """Which media frame the meme sits in, rotating off recent videos.

    A still from the library is foreign media, and foreign media never lands
    on the ground bare (`media_frames`). The three treatments rotate the way
    they do in a long, one step per video rather than per clip, because a
    short carries one meme at most.
    """
    import random

    from pipeline.media_frames import MEDIA_TREATMENTS

    usable: dict[str, Plate] = {}
    for treatment in MEDIA_TREATMENTS:
        plate = reg.get(f"{treatment}-{aspect}") if aspect else None
        if plate is not None and plate.slot("media") is not None:
            usable[reg.base_key(plate.key)] = plate
    if not usable:
        return None
    keys = _prefer_unused(sorted(usable), reg.base_keys(avoid))
    return usable[random.Random(f"meme-frame|{seed}").choice(keys)]


def _contain(size: tuple[int, int], box: tuple[int, int, int, int]
             ) -> tuple[int, int, int, int]:
    """`size` at its largest inside `box`, centred, never cropped.

    The joke is usually a caption on a picture, and cover-fitting the way a
    photograph goes into a frame cuts the caption off. A letterbox inside a
    drawn frame is paper; a meme missing its punchline is nothing.
    """
    bx, by, bw, bh = box
    mw, mh = max(size[0], 1), max(size[1], 1)
    k = min(bw / mw, bh / mh)
    w, h = max(int(mw * k), 1), max(int(mh * k), 1)
    return bx + (bw - w) // 2, by + (bh - h) // 2, w, h


def _meme_layers(spans: Sequence[Span], resolver: Resolver, reg: Registry,
                 frame: tuple[int, int], aspect: str, *, seed: str,
                 avoid: "Collection[str]", skipped: list[str]) -> list[Layer]:
    """The frame plate and the still inside it, or nothing.

    TWO LAYERS, NOT A COMPOSITE. A frames/ plate drawn full-frame, and the
    meme as a media layer over its aperture, inset by the frame's edge band
    so the drawn border and the tape stay visible. Both are kinds the
    renderer already draws, so the meme costs the renderer nothing new.
    """
    span = next((sp for sp in spans if sp.shot.meme), None)
    if span is None:
        return []
    shot = span.shot
    path = resolver.image_for(MEME_SRC)
    if path is None or isinstance(path, list):
        # NOTHING FITS, WHICH IS ALLOWED. A short without a meme is the
        # ordinary case; a meme that does not fit the story is the defect.
        skipped.append(f"{shot.id}.meme <- nothing in the library fits")
        return []
    window = meme_window(span, spans)
    if window is None:
        skipped.append(
            f"{shot.id}.meme <- no room: {span.end - span.start:.2f}s span, "
            f"clear of the payoff, holds under {MEME_HOLD_S[0]:.1f}s")
        return []
    frame_plate = _meme_frame(reg, aspect, seed=seed, avoid=avoid)
    if frame_plate is None:
        skipped.append(f"{shot.id}.meme <- no media frame in the kit")
        return []
    try:
        from PIL import Image
        with Image.open(path) as im:
            size = im.size
    except OSError:
        skipped.append(f"{shot.id}.meme <- {Path(path).name} does not open")
        return []

    fw, fh = frame
    w, h = _fit(frame_plate, frame)
    placed = ((fw - w) // 2, (fh - h) // 2, w, h)
    ax, ay, aw, ah = _slot_in_frame(frame_plate, "media", placed)
    from pipeline.media_frames import _EDGE_BAND
    band = max(int(min(aw, ah) * _EDGE_BAND), 2)
    box = _contain(size, (ax + band, ay + band, aw - 2 * band, ah - 2 * band))
    t_start, t_end = window
    return [
        Layer(name=f"{shot.id}:meme-frame:{frame_plate.key}", kind="plate",
              shot_id=shot.id, t_start=t_start, t_end=t_end,
              x=placed[0], y=placed[1], w=w, h=h,
              entry_key=frame_plate.key, concept=frame_plate.family,
              frame_count=frame_plate.frame_count, fps=frame_plate.fps or 0,
              loops=frame_plate.animated and not frame_plate.plays_once,
              slot=MEME_SRC, z=MEME_Z),
        Layer(name=f"{shot.id}:meme:{Path(path).stem}", kind="media",
              shot_id=shot.id, t_start=t_start, t_end=t_end,
              x=box[0], y=box[1], w=box[2], h=box[3],
              path=Path(path), slot=MEME_SRC, z=MEME_Z + 1),
    ]


def placed_meme(result: BuildResult) -> Layer | None:
    """The meme's still, if this cut carries one."""
    return next((l for l in result.layers
                 if l.kind == "media" and l.slot == MEME_SRC), None)


def _slot_budget(plate: Plate, slot_name: str) -> int:
    """The kit's own `maxChars` for a slot, or 0 when it declares none."""
    slot = plate.slot(slot_name)
    if slot is None:
        return 0
    role = (plate.type_roles.get(slot.role) or {})
    if role.get("maxChars"):
        return int(role["maxChars"])
    if role.get("maxLines") and role.get("maxCharsPerLine"):
        return int(role["maxLines"]) * int(role["maxCharsPerLine"])
    return 0


# The slot roles whose value is a name rather than a sentence, and so may be
# shortened to fit: "FCF" for "Free cash flow", "Op. income".
_ABBREVIABLE = frozenset({"label", "kicker", "head", "period", "unit",
                          "barLabel", "deltaLabel", "attribution", "tag",
                          "row-label", "rowLabel"})


def _bound_values(shot: Shot, plate: Plate, resolver: Resolver,
                  reg: Registry) -> tuple[dict[str, str], list[str], list[str]]:
    """The slot values for one shot: `(values, unfilled, skipped)`.

    Routed through `plate_tags.build_fill`, which is the grammar a director
    writes a `[PLATE]` tag in. One grammar for both formats: a template may
    write `row-1` and `head` and `band` and get the same cell expansion, the
    same six-period check and the same "that slot is not declared" refusal
    that a LONG's tag gets. The alternative was a second, quieter expansion
    that agreed with the first until it did not.

    A leading `?` means the slot is optional: a sheet has six row bands and a
    script may carry four metrics, and two blank rows is the correct drawing,
    not a missing asset. Everything without the mark is required and fails the
    build when it is empty — a slot with no value must never draw an empty box.
    """
    from pipeline.plate_tags import build_fill

    unfilled: list[str] = []
    skipped: list[str] = []
    parts: list[str] = [plate.key]
    for slot_name, raw in shot.bind.items():
        optional = raw.startswith("?")
        src = raw.lstrip("?")
        if src.startswith(("plate.", MEDIA_PREFIX)):
            continue                          # composited, not typed
        got = resolver.text_for(src)
        if got is None or not str(got).strip():
            (skipped if optional else unfilled).append(
                f"{shot.id}.{slot_name} <- {src}")
            continue
        # AN OPTIONAL SLOT THAT WILL NOT FIT IS LEFT EMPTY, NOT OVERFLOWED,
        # AND NOT A REASON TO REFUSE THE VIDEO. The long binds a chapter's
        # own sentences into slots, and a sentence is whatever length the
        # writer wrote — a 65-character line into a 60-character caption
        # failed the whole render over one optional caption. Required binds
        # still refuse in `check_budgets`: a slot the beat is FOR, carrying
        # something too long, is a beat that does not work.
        budget = _slot_budget(plate, slot_name)
        if budget and len(str(got).strip()) > budget:
            # A LABEL TOO LONG FOR ITS SLOT IS SHORTENED, NOT DROPPED (item
            # 25): "Free cash flow" in a 13-character label slot left a row
            # with no name. Only label-like slots: a sentence is never
            # abbreviated into shorthand.
            slot = plate.slot(slot_name)
            if slot is not None and slot.role in _ABBREVIABLE:
                from pipeline.short_data import abbreviate
                short = abbreviate(str(got), budget)
                if short:
                    got = short
        if optional and budget and len(str(got).strip()) > budget:
            skipped.append(f"{shot.id}.{slot_name} <- {src} "
                           f"({len(str(got).strip())} > {budget} chars)")
            continue
        # A value carrying the tag grammar's own separators would be read as
        # structure. Only `|` can do that; a comma is meaningful and is what
        # spreads a row across its cells.
        parts.append(f"{slot_name}={str(got).replace('|', '/')}")

    # A LIT ROW. `lit` names the band the step is on, or "all" for the pull-back
    # where every row is up. A band is not a text box — naming it lights it —
    # which is why this goes in as the slot name rather than as a value.
    lit = (shot.lit or "").strip()
    if lit == "all":
        parts += [f"{n}=1" for n in sorted(plate.slots)
                  if plate.slots[n].is_band]
    elif lit and plate.slot(lit) is not None:
        parts.append(f"{lit}=1")

    fill = build_fill(reg, " | ".join(parts))
    for problem in fill.problems:
        # "FILLS NONE OF ITS SLOTS" IS A TAG PROTECTION, NOT A TEMPLATE ONE.
        #
        # It exists because a director naming a plate and writing nothing on it
        # gets an empty rectangle that looks like a design choice. A template
        # shot is authored as a whole composition: `the-turn` is a room, a host
        # in close-up and the spoken line, and the room's only text slot is the
        # chapter-opener title that a SHORT has no use for. Which binds are
        # required is carried by the `?` prefix and reported through `unfilled`.
        if "fills none of its" in problem:
            continue
        raise TemplateError(f"{shot.id}: {problem}")
    return fill.values, unfilled, skipped


def _repeat_layers(shot: Shot, plate: Plate | None,
                   placed: tuple[int, int, int, int] | None,
                   frame: tuple[int, int], resolver: Resolver,
                   t0: float, t1: float) -> list[Layer]:
    """One box per item of a repeated list, arranged down its slot."""
    rep = shot.repeat
    items = resolver.list_for(rep.src) or []
    if not items:
        return []
    box = None
    if plate is not None and rep.into and plate.slot(rep.into) is not None:
        box = _slot_in_frame(plate, rep.into, placed or (0, 0, *frame))
    boxes = _arrange(len(items), rep.arrange, frame, box)
    out: list[Layer] = []
    for idx, (value, bx) in enumerate(zip(items, boxes)):
        enter_at = min(t0 + idx * (rep.stagger_s or shot.stagger_s),
                       max(t1 - 0.3, t0))
        out.append(Layer(
            name=f"{shot.id}:repeat:{rep.into or 'frame'}:{idx}", kind="text",
            shot_id=shot.id, t_start=enter_at, t_end=t1,
            x=bx[0], y=bx[1], w=bx[2], h=bx[3],
            size_fh=rep.size_fh, text=str(value), max_lines=1, z=25))
    return out


def _text_box(spec, frame: tuple[int, int]) -> tuple[int, int, int, int]:
    """Where a code-drawn line sits when there is no plate to put it in."""
    from pipeline.marks import block_height, face_for

    fw, fh = frame
    size_px = int(round(spec.size_fh * fh))
    bw = int(fw * 0.84)
    bh = block_height(face_for(spec.size_fh), size_px, spec.max_lines)
    if spec.align == "top":
        by = int(fh * 0.06)
    elif spec.align == "center":
        by = (fh - bh) // 2
    elif spec.align == "bottom":
        by = fh - bh - int(fh * 0.08)
    else:
        by = int(float(spec.align) * fh) - bh // 2
    return (int(fw * 0.08), by, bw, bh)


def _host_layer(reg: Registry, shot: Shot, plate: Plate | None,
                placed: tuple[int, int, int, int] | None,
                frame: tuple[int, int], t0: float, t1: float, *,
                seed: str,
                column: tuple[int, int, int, int] | None = None,
                avoid: "Collection[str]" = (),
                words: Sequence[Any] = (), closing: bool = False,
                used: dict[str, int] | None = None,
                previous: str = "") -> Layer | None:
    """The host, solved onto the room's anchor.

    THE ANCHOR'S HEIGHT IS HIS TARGET HEIGHT — never its width, which the
    figure box's arms are meant to pass, and never the figure box's own
    height, which runs past the floor line to carry his shoes. Both are
    ten-to-twenty-percent errors that read as a bad composite rather than as a
    bug. `host.place_on_room` is the contract; this only decides which pose.

    There is no glance and no second jacket any more. The rebuild draws
    neither: he faces camera in every pose, and the wardrobe rule went with
    the robe (DESIGN §2.5). What a two-shot does to him is the column he is
    framed in, not which way he looks.
    """
    from pipeline.host import (cast_pose, frame_shot, host_shot,
                               place_on_room, stands_on)

    role = shot.host.pose
    # THE SEED IS PER SHOT, NOT PER VIDEO. Hashed on the video's seed alone,
    # every beat of a role in a long resolves to the same pose and the rest of
    # the role is never cut to at all.
    pose = (reg.get(role) if role in reg
            else reg.host_for(role, seed=f"{seed}|{shot.id}",
                              avoid=avoid))

    # THE WORDS MAY CAST HIM, but only where the template left it to a ROLE,
    # the role stood him up as a figure, and there is a room under him. A
    # template that names a pose by key chose it; a framing is a camera
    # distance; and a two-shot's column has no floor, so a count or a shrug
    # cut there would stand on nothing. Every pose is drawn in the same
    # standing box, so the cast lands exactly where the role's pose would have.
    if (role not in reg and pose is not None and pose.floor_line_y
            and plate is not None and plate.family == "room"):
        cast = cast_pose(reg, words, room=plate, closing=closing, used=used,
                         avoid=avoid, previous=previous,
                         seed=f"{seed}|{shot.id}")
        if cast is not None:
            log.debug("%s: %r cast %s over %s", shot.id, cast.cue, cast.pose,
                      pose.key)
            pose = reg.get(cast.pose) or pose

    # A ROOM THAT REFUSES A CUT-OUT STILL TAKES A SHOT OF HIS FACE. A room
    # with no floor in shot says so in the field (`hostAnchor: false`) rather
    # than leaving it out, and standing a figure there puts him on a surface
    # the camera is above. A framing has no floor line to pin, so the beat
    # survives as the close-up — which is branching on the refusal rather than
    # reading it as an omission.
    #
    # `framing_for` RATHER THAN `host_for`, because a role is curation: it
    # can hold cut-outs and framings both, and swapping one unplaceable pose
    # for another would look like it had handled the case.
    if (plate is not None and plate.refuses_host
            and pose is not None and pose.floor_line_y):
        instead = reg.framing_for(HOST_WHERE_NOBODY_STANDS,
                                  seed=f"{seed}|{shot.id}", avoid=avoid)
        if instead is not None:
            log.debug("%s refuses a cut-out — %s is framed instead of %s",
                      plate.key, instead.key, pose.key)
            pose = instead

    if pose is None:
        raise TemplateError(
            f"{shot.id}: host {role!r} is neither a pose in the kit nor a role "
            f"it declares. The roles are "
            f"{', '.join(reg.host_roles_available())}")

    fw, fh = frame
    host = host_shot(reg, pose)

    box = None
    # A FRAMING IS A CAMERA DISTANCE AND IS NEVER SOLVED ONTO AN ANCHOR.
    # `close-up` carries no floor line: fit into a room's standing spot, it is
    # a head the size of a man, hovering where his shoes would be. It is
    # placed against the frame — or, in a two-shot, against his column of it,
    # a little looser so his shoulders stay in the column — on the eye line
    # the plate publishes.
    if host.is_framing:
        stage = column or (0, 0, fw, fh)
        spot = frame_shot(host, (fw, fh),
                          head_fh=CLOSE_UP_IN_COLUMN_FH if column else 0.0,
                          centre_fw=(stage[0] + stage[2] / 2) / max(fw, 1))
        if spot is not None:
            box = (spot.x, spot.y, spot.width, spot.height)
    # HE STANDS ON A ROOM, and only on a room: a content plate has no floor
    # line and no anchor, and `place_on_room` raises rather than guessing at
    # one. Asked here rather than caught, because a caller that cannot answer
    # "is there a floor in this shot" has no business compositing a man.
    if (box is None and plate is not None and placed is not None
            and plate.slot("host-anchor") is not None
            and stands_on(plate, host)):
        spot = place_on_room(plate, host)
        k = placed[2] / max(plate.delivered[0], 1)
        box = (placed[0] + int(spot.x * k), placed[1] + int(spot.y * k),
               max(int(spot.width * k), 1), max(int(spot.height * k), 1))
    if box is None and plate is not None and placed is not None:
        if plate.slot(shot.host.slot) is not None:
            hx, hy, hw, hh = _slot_in_frame(plate, shot.host.slot, placed)
            k = min(hw / host.pose.delivered[0], hh / host.pose.delivered[1])
            dw = int(host.pose.delivered[0] * k)
            dh = int(host.pose.delivered[1] * k)
            box = (hx + (hw - dw) // 2, hy + (hh - dh), dw, dh)
    if box is None:
        stage = column or (0, 0, fw, fh)
        k = min(stage[2] / host.pose.delivered[0],
                fh * 0.55 / host.pose.delivered[1])
        dw = int(host.pose.delivered[0] * k)
        dh = int(host.pose.delivered[1] * k)
        box = (stage[0] + (stage[2] - dw) // 2, fh - dh, dw, dh)

    x, y, dw, dh = box
    # A FRAMING IS ALREADY SOLVED and running off the left and right edges is
    # what it is for — clamping one into the frame crops it into a narrower
    # shot than the one that was drawn. Everything else is a cut-out standing
    # in a room, and a room pushed in on a row carries its anchor off the
    # bottom with it: he stood at y=1832 in a 1920 frame once, 13% of him on
    # screen, reading as a smudge at the edge.
    if not host.is_framing:
        if dh > fh:
            dw, dh = int(dw * fh / dh), fh
        y = min(max(y, 0), fh - dh)
        x = min(max(x, 0), max(fw - dw, 0))
    return Layer(name=f"{shot.id}:host:{host.pose.name}", kind="host",
                 shot_id=shot.id, t_start=t0, t_end=t1,
                 x=x, y=y, w=dw, h=dh,
                 entry_key=host.pose.key, concept=host.pose.family,
                 frame_count=pose.frame_count, fps=pose.fps or 0,
                 loops=True, z=40)


def _front_layer(reg: Registry, shot: Shot, plate: Plate | None,
                 placed: tuple[int, int, int, int] | None,
                 host: Layer) -> Layer | None:
    """The part of the room that stands in front of him, drawn after him.

    A rebuild room ships the whole room and, beside it, the desk and what is
    on the desk as a layer of its own. He goes on between: the room, then
    him, then this, in the room's own box — so it moves with the room when
    the shot pushes in. Only when he is standing IN the room: a framing is a
    camera distance with no floor under it, and a room that refuses a cut-out
    has no front for him to be behind.
    """
    from pipeline.host import front_of

    if plate is None or placed is None or plate.family != "room":
        return None
    pose = reg.get(host.entry_key)
    if pose is None or not pose.floor_line_y or plate.refuses_host:
        return None
    if plate.slot("host-anchor") is None:
        return None
    path = front_of(plate)
    if path is None:
        return None
    return Layer(name=f"{shot.id}:front:{plate.key}", kind="front",
                 shot_id=shot.id, t_start=host.t_start, t_end=host.t_end,
                 x=placed[0], y=placed[1], w=placed[2], h=placed[3],
                 path=path, entry_key=plate.key, concept=plate.family, z=45)


# ---------------------------------------------------------------------------
# Placing the caption
# ---------------------------------------------------------------------------

def caption_band(plate: Plate | None, frame: tuple[int, int],
                 box_h: int, safe: tuple[int, int] | None = None
                 ) -> tuple[int, int]:
    """The rows a shot's caption box may occupy: `(top, bottom)`, frame pixels.

    A plate's own `safe` band when it publishes one. That band is the
    PLATFORM's, restated at the plate's canvas, which is the frame's size, so
    it maps by the canvas's height and never through where the plate is
    placed: moving in on a row does not move the phone's buttons. Otherwise
    design's band on a vertical frame (`CAPTION_BAND`), and on a landscape one
    the single place its caption has always had.
    """
    from pipeline.rasters import CAPTION_BOX_PAD

    fw, fh = frame
    band = _caption_band(plate, frame, box_h)
    if safe and fh > fw:
        # The format's clear area is the outer bound: a plate's own band
        # can narrow it, never reach past it.
        return max(band[0], int(safe[0])), min(band[1], int(safe[1]))
    return band


def _caption_band(plate: Plate | None, frame: tuple[int, int],
                  box_h: int) -> tuple[int, int]:
    from pipeline.rasters import CAPTION_BOX_PAD

    fw, fh = frame
    published = plate.safe if plate is not None else {}
    top, bottom = published.get("top"), published.get("bottom")
    if (isinstance(top, (int, float)) and isinstance(bottom, (int, float))
            and plate is not None and plate.canvas[1] and bottom > top):
        k = fh / plate.canvas[1]
        return int(round(top * k)), int(round(bottom * k))
    if fh > fw:
        return int(round(CAPTION_BAND[0] * fh)), int(round(CAPTION_BAND[1] * fh))
    foot = fh - int(fh * LANDSCAPE_CAPTION_MARGIN_FH) + CAPTION_BOX_PAD
    return foot - box_h, foot


def caption_obstacles(reg: Registry, shot_layers: Sequence[Layer]
                      ) -> list[tuple[str, tuple[int, int, int, int]]]:
    """What a shot's caption must not cover, by name, as frame boxes.

    Every slot on the shot's plate that holds a value, as placed, a lit band
    included because it is the row the beat is about; every data region the
    plate draws a series into; every nested plate, photograph, line of type
    and mark; and the host's head. A room's furniture and his body are not
    here: the caption is allowed to cover the set, never what is being read.
    """
    out: list[tuple[str, tuple[int, int, int, int]]] = []
    for l in shot_layers:
        box = (l.x, l.y, l.w, l.h)
        if l.kind == "plate":
            plate = reg.get(l.entry_key)
            if plate is None:
                continue
            for name, slot in plate.slots.items():
                if slot.control or not (slot.w and slot.h):
                    continue
                if str(l.values.get(name, "")).strip() or (slot.renderer and l.values):
                    out.append((name, _slot_in_frame(plate, name, box)))
        elif l.kind in ("fill", "media", "text", "mark"):
            out.append((l.name.split(":", 1)[-1], box))
        elif l.kind == "host":
            out.append(("the host's head", _head_box(reg, l)))
    return out


def _head_box(reg: Registry, host: Layer) -> tuple[int, int, int, int]:
    """His head, in frame pixels: the pose's own `head` slot, or the top of him."""
    pose = reg.get(host.entry_key)
    box = (host.x, host.y, host.w, host.h)
    if pose is not None and pose.slot("head") is not None:
        return _slot_in_frame(pose, "head", box)
    return (host.x, host.y, host.w, max(int(host.h * HOST_HEAD_SHARE), 1))


def place_caption(band: tuple[int, int],
                  obstacles: Sequence[tuple[str, tuple[int, int, int, int]]],
                  frame: tuple[int, int], box_h: int) -> tuple[int, list[str]]:
    """Where a caption's box goes inside `band`: its top row, and what it covers.

    In order: the place that covers the least of the obstacles (nothing, when
    anywhere is free), then the one that comes least inside
    `CAPTION_CLEARANCE_FH` of them, then the lowest, since the bottom is where
    a caption is looked for. So a shot with room gets the lowest place clear
    by the full margin, a tight gap between two rows of figures gets the
    caption with the space shared out, and a shot with nowhere free gets the
    place that hides least. The names of what it covers come back so the
    caller can say so; they are empty whenever the caption covers nothing.
    Deterministic: a shot places its caption in the same place every time.

    The box is taken at its widest, between the side margins. Which line of
    the shot will be the widest is not known here, and a place that clears
    the widest line clears them all.
    """
    fw, fh = frame
    top, bottom = band
    lo, hi = top, bottom - box_h
    if hi <= lo:
        # A band with no room to choose in is not a placement, and there is
        # nothing to report about it.
        return max(hi, 0), []
    side = int(fw * CAPTION_SIDE_FW)
    pad = int(round(fh * CAPTION_CLEARANCE_FH))

    def rows(grow: int) -> list[tuple[int, int, int, int, str]]:
        """The obstacles as row spans inside the caption's width, grown by `grow`."""
        return [(oy - grow, oy + oh + grow, max(ox, side), min(ox + ow, fw - side),
                 name) for name, (ox, oy, ow, oh) in obstacles
                if oh > 0 and min(ox + ow, fw - side) > max(ox, side)]

    def covered(spans: list, y: int) -> int:
        """The area of the spans' union inside the box with its top at `y`."""
        cuts = sorted({y, y + box_h,
                       *(v for r in spans for v in r[:2] if y < v < y + box_h)})
        area = 0
        for s0, s1 in zip(cuts, cuts[1:]):
            width, reach = 0, None
            for a, b in sorted((a, b) for y0, y1, a, b, _ in spans
                               if y0 < s1 and y1 > s0):
                if reach is None or a > reach:
                    width, reach = width + b - a, b
                elif b > reach:
                    width, reach = width + b - reach, b
            area += width * (s1 - s0)
        return area

    hard, near = rows(0), rows(pad)
    # Either area changes only where the box's top or foot crosses an edge, so
    # the best place is at one of those or at an end of the band.
    edges = {v for r in hard + near for v in r[:2]}
    options = {lo, hi, *edges, *(v - box_h for v in edges)}
    y = min((c for c in options if lo <= c <= hi),
            key=lambda c: (covered(hard, c), covered(near, c), -c))
    return y, sorted({name for y0, y1, _, _, name in hard
                      if y0 < y + box_h and y1 > y})


# ---------------------------------------------------------------------------
# The invariants — a composition that breaks its own rules never reaches an
# encoder.
# ---------------------------------------------------------------------------

def check_invariants(fmt: Format, result: BuildResult,
                     host_shots: Sequence[str] = ()) -> list[str]:
    """Everything that must be true of the layer list. Empty means proceed."""
    problems: list[str] = []
    fw, fh = result.frame
    by_shot = {sp.shot.id: sp for sp in result.spans}

    # 1. No layer outlives its shot. A held frame is usually this.
    for l in result.layers:
        span = by_shot.get(l.shot_id)
        if span is None:
            problems.append(f"{l.name}: belongs to no shot in the cut")
            continue
        if l.t_start < span.start - 1e-6 or l.t_end > span.end + 1e-6:
            problems.append(
                f"{l.name}: runs {l.t_start:.2f}–{l.t_end:.2f} outside its "
                f"shot's {span.start:.2f}–{span.end:.2f}")

    # 2. The host appears in exactly the shots the template puts them in.
    wanted = set(host_shots)
    got = {l.shot_id for l in result.of_kind("host")}
    for missing in sorted(wanted - got):
        problems.append(f"{missing}: the template puts the host here and no "
                        f"host layer was built")
    for extra in sorted(got - wanted):
        problems.append(f"{extra}: a host layer nobody asked for")

    # 3. Large type and the caption band are two things competing to be read.
    for span in result.spans:
        if not span.shot.has_large_type:
            continue
        if any(l.kind == "caption" for l in result.for_shot(span.shot.id)):
            problems.append(
                f"{span.shot.id}: large type and the caption band share a shot")

    # 4. Nothing is set below the readability floor.
    for l in result.layers:
        if l.kind not in ("text",) or not l.size_fh:
            continue
        if l.size_fh < SLOT_TYPE_FLOOR_FH:
            problems.append(
                f"{l.name}: set at {l.size_fh:.3f} of frame height, below the "
                f"{SLOT_TYPE_FLOOR_FH:.3f} floor — present but not readable, "
                f"which looks like a decision")

    # 5. The host is a subject, not a sticker over the evidence.
    #
    # A ROOM IS NOT EVIDENCE. It is the set he is standing in, and a close-up
    # covering 97% of it is not a defect — it is what a close-up is. What this
    # catches is him drawn across the thing he is discussing: a chart, a
    # sheet, a card. Those are what a two-shot gives its own column to.
    for h in result.of_kind("host"):
        for o in result.for_shot(h.shot_id):
            if o.kind not in ("plate", "fill") or not o.w or not o.h:
                continue
            if o.concept == "room":
                continue
            # DRAWN OVER HIM IS NOT STOOD OVER. The meme's frame is a
            # full-frame plate above the host for a second and a half; he is
            # not across it, it is across him, and that is the cutaway.
            if o.z > h.z:
                continue
            ox = max(0, min(h.x + h.w, o.x + o.w) - max(h.x, o.x))
            oy = max(0, min(h.y + h.h, o.y + o.h) - max(h.y, o.y))
            if ox * oy > 0.55 * o.w * o.h:
                problems.append(
                    f"{h.name} stands over {o.name} — the host is drawn "
                    f"across {(ox * oy) / (o.w * o.h):.0%} of it")

    # 6. Nothing is placed off the frame it is drawn in.
    for l in result.layers:
        if l.kind in ("ground", "caption") or not (l.w and l.h):
            continue
        if l.x + l.w <= 0 or l.y + l.h <= 0 or l.x >= fw or l.y >= fh:
            problems.append(f"{l.name}: placed entirely outside the frame")

    # 7. A required slot with no value is a hole in the drawing.
    for miss in result.unfilled:
        problems.append(f"{miss}: required and empty — a slot with no value "
                        f"must fail the build, never draw an empty box")

    return problems


def check_budgets(fmt: Format, result: BuildResult,
                  reg: Registry | None = None) -> list[str]:
    """Copy that does not fit the slot the kit drew for it.

    `maxChars` is the kit's own limit, derived from the box the copy lands in
    and the face it is set in. It is a HARD limit: over it the line collides
    with rules drawn in ink.

    A BACKSTOP, NOT THE ONLY LINE. `gates.budget_check` makes the same check
    against the script, before anything renders, because a script is where the
    writer can still fix it — refusing a six-character overrun after a
    forty-minute encode is a true answer arriving at the most expensive
    possible moment. This one stays because a SHORT fills some slots from its
    template and its resolvers rather than from the script, and those values
    never pass through the gate.

    THE BUDGET IS PER BOX, NOT PER ROLE. `structure/flow-16x9` sets `caption`
    in a 1620-unit strip and again in a 104-unit arrow label; reading the role
    alone is wrong in one of them whichever number the role holds. The role's
    figure is the floor — the narrowest box on the plate — and is the fallback,
    so a slot with no budget of its own is still measured against something it
    fits inside.
    """
    from pipeline.plate_frames import budget

    over: list[str] = []
    if reg is None:
        return over
    for l in result.layers:
        if l.kind != "plate" or not l.values:
            continue
        plate = reg.get(l.entry_key)
        if plate is None:
            continue
        for slot_name, value in l.values.items():
            slot = plate.slot(slot_name)
            if slot is None:
                continue
            limit = budget(plate, slot, str(value)).get("maxChars")
            if limit and len(str(value)) > int(limit):
                over.append(
                    f"{l.shot_id}.{slot_name}: {len(str(value))} characters "
                    f"against the {limit} {plate.key} reserves for it — "
                    f"{str(value)[:60]!r}")
    return over


def held_layer_spans(result: BuildResult) -> list[tuple[float, float, str]]:
    """Windows where nothing on screen is redrawing.

    A composition that neither moves nor changes for longer than its ceiling
    is a still frame with audio over it, and that is what the ceiling exists
    to catch. A static data plate is deliberately still — the ceiling is what
    keeps it short.
    """
    out: list[tuple[float, float, str]] = []
    for span in result.spans:
        shot_layers = result.for_shot(span.shot.id)
        if any(l.moves for l in shot_layers):
            continue
        # Something entering inside the shot breaks the hold at that moment.
        entries = sorted({l.t_start for l in shot_layers
                          if l.t_start > span.start + 1e-6})
        marks = [span.start, *entries, span.end]
        for a, b in zip(marks, marks[1:]):
            if b - a > 0:
                out.append((a, b, span.shot.id))
    return out
