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

* **Data plates do not boil.** 47 of the 143 are `playback: static` — tables,
  charts, figures, structure. A number that moves three times a second cannot
  be read, which is the whole job of a number. The rooms, the host, the cards
  and the paper loop; everything carrying figures is still.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, Sequence

from pipeline.plates import Plate, Registry
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
# and a medium framing draws about 39% of a 16:9 frame — so he has room to
# stand in his half rather than being cropped into it.
TWO_SHOT_GRAPHIC = 0.56

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

# Where a caption band sits, as a fraction of frame height, and how tall it is
# allowed to be. Kept clear of the disclaimer and of the top strip so a long
# line can never stack with the furniture.
CAPTION_BAND = (0.78, 0.14)

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
    kind: str            # ground|plate|fill|media|host|text|mark|caption
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

    @property
    def dur(self) -> float:
        return self.t_end - self.t_start

    @property
    def moves(self) -> bool:
        """Whether this layer is redrawing rather than sitting there.

        A room's two-frame loop and a host strip both move. A static data
        plate does not, and its `max_hold_s` is what keeps it short rather
        than a wobble that made the measurement look better than the video.
        """
        return bool(self.loops and self.frame_count > 1)


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

def resolve_room(reg: Registry, role: str, aspect: str, *, seed: str,
                 step: int) -> Plate | None:
    """A room ROLE — `talk`, `establish`, `read` — to one of its angles.

    ROTATING, NOT DEFAULTING. The registry declares several angles per role
    and a template that names `room/wide` gets `room/wide` every time; nine
    straight-on eye-level plates cut like props sliding on a shelf, which is
    why the kit added three camera positions. The step is the shot's index, so
    consecutive rooms in one video differ, and the seed is the video's, so two
    videos do not open on the same angle.
    """
    options = [k for k in reg.room_roles.get(role, ())]
    resolved: list[Plate] = []
    for stem in options:
        key = reg.aspect_key(stem, aspect) or (stem if stem in reg else None)
        got = reg.get(key) if key else None
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
    return resolved[(offset + step) % len(resolved)]


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
                 seed: str = "") -> BuildResult:
    """Turn the template and the script into the ordered layer list."""
    frame = fmt.frame
    fw, fh = frame
    aspect = aspect or getattr(fmt, "aspect", "") or ""
    layers: list[Layer] = []
    unfilled: list[str] = []
    skipped: list[str] = []

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
        # The area the plate owns, and where the host stands if he is not on a
        # room. A one-up shot gives the plate the whole frame and the host
        # nothing to be beside; a two-shot splits it.
        stage: tuple[int, int, int, int] = (0, 0, fw, fh)
        host_column: tuple[int, int, int, int] | None = None
        graphic_side = ""

        # -- the plate. `None` is a real value: a bare-ground shot.
        if shot.plate:
            # `room/<role>` is a ROLE, not a key: the template says what kind
            # of angle this beat wants and the registry picks one, rotating.
            role = shot.plate.split("/", 1)[1] if shot.plate.startswith("room/") else ""
            if role and role in reg.room_roles:
                plate = resolve_room(reg, role, aspect, seed=seed,
                                     step=span_index)
            else:
                plate = resolve_plate(reg, shot.plate, aspect)
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
            #    consecutive two-shots are not the same picture; and the
            #    glance is cut toward the graphic.
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

            # MOVING IN ON A SLOT — AND NEVER PAST THE EDGES OF WHAT IT
            # HAS TO SHOW. Without this a walk down a list is one wide shot
            # with a rectangle migrating down it, which a viewer reads as a
            # single held composition.
            #
            # The zoom is bounded by the frame's WIDTH, not only by the target
            # height. A vertical sheet's row band is 1044 of 1080 canvas units
            # wide: scaled until it filled 62% of the frame's height it came
            # out at 1.4x, and the last three columns of every row went off
            # the right-hand edge. A row you cannot see the figures on is not
            # a row anybody moved in on. Where the slot is already full width
            # the move is a PAN — the composition still changes, and every
            # figure stays on screen.
            if shot.focus and plate.slot(shot.focus) is not None:
                gx, gy, gw2, gh2 = stage
                sx, sy, sw, sh_px = _slot_in_frame(plate, shot.focus, placed)
                by_height = (gh2 * FOCUS_FILL) / max(sh_px, 1)
                by_width = gw2 / max(sw, 1)
                k = max(min(by_height, by_width, FOCUS_MAX_SCALE), 1.0)
                nw, nh = int(w * k), int(h * k)
                base = (gx + (gw2 - nw) // 2, gy + (gh2 - nh) // 2, nw, nh)
                sx, sy, sw, sh_px = _slot_in_frame(plate, shot.focus, base)
                nx = base[0] + (gx + gw2 // 2 - (sx + sw // 2))
                ny = base[1] + (gy + gh2 // 2 - (sy + sh_px // 2))
                # Never open a gap at an edge: a plate larger than its stage
                # covers it, and one that is not stays centred on that axis.
                nx = (min(gx, max(nx, gx + gw2 - nw)) if nw >= gw2
                      else gx + (gw2 - nw) // 2)
                ny = (min(gy, max(ny, gy + gh2 - nh)) if nh >= gh2
                      else gy + (gh2 - nh) // 2)
                placed = (nx, ny, nw, nh)
                w, h = nw, nh

            # -- what goes in its slots. The renderer draws the plate WITH
            #    these; nothing here sets type.
            values, missing, gone = _bound_values(shot, plate, resolver, reg)
            # THE WALL IS THE RECEIPTS, so it is filled from the book rather
            # than from the script: seven tickers this channel actually
            # covered, when, and one word for how it went. A template cannot
            # bind them — they are not facts about this video.
            if plate.name.startswith("wall-of-calls"):
                from pipeline.plates import wall_of_calls
                values = {**wall_of_calls(_settings()), **values}
            unfilled += missing
            skipped += gone

            layers.append(Layer(
                name=f"{shot.id}:plate:{plate.key}", kind="plate",
                shot_id=shot.id, t_start=t0, t_end=t1,
                x=placed[0], y=placed[1], w=w, h=h,
                entry_key=plate.key, concept=plate.family, values=values,
                frame_count=plate.frame_count, fps=plate.fps or 0,
                loops=plate.animated, z=10))

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
                    loops=nested.animated, z=20))
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
                                     graphic_side=graphic_side)
            if host_layer is not None:
                layers.append(host_layer)

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

        # -- marks land after the thing they mark
        for spec in shot.marks:
            target = None
            if plate is not None and plate.slot(spec.on) is not None:
                target = _slot_in_frame(plate, spec.on, placed or (0, 0, fw, fh))
            if target is None:
                skipped.append(f"{shot.id}.mark:{spec.style} <- {spec.on}")
                continue
            layers.append(Layer(
                name=f"{shot.id}:mark:{spec.style}", kind="mark",
                shot_id=shot.id,
                t_start=min(t0 + spec.after_s, t1), t_end=t1,
                x=target[0], y=target[1], w=target[2], h=target[3],
                slot=spec.style, z=70))

        # -- captions
        if shot.captions and not shot.has_large_type:
            layers.append(Layer(
                name=f"{shot.id}:caption", kind="caption", shot_id=shot.id,
                t_start=t0, t_end=t1,
                x=int(fw * 0.06), y=int(fh * CAPTION_BAND[0]),
                w=int(fw * 0.88), h=int(fh * CAPTION_BAND[1]), z=80))

    layers.sort(key=lambda l: (l.t_start, l.z))
    return BuildResult(layers=layers, spans=list(spans), frame=frame,
                       aspect=aspect, unfilled=unfilled, skipped=skipped)


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
                graphic_side: str = "") -> Layer | None:
    """The host, solved onto the room's anchor.

    THE ANCHOR'S HEIGHT IS HIS TARGET HEIGHT — never its width, which the
    figure box's arms are meant to pass, and never the figure box's own
    height, which runs past the floor line to carry his shoes. Both are
    ten-to-twenty-percent errors that read as a bad composite rather than as a
    bug. `host.place_on_room` is the contract; this only decides which pose.
    """
    from pipeline.host import (HostShot, dressed, frame_shot,
                               looking_at, place_on_room, stands_on)

    role = shot.host.pose
    # THE SEED IS PER SHOT, NOT PER VIDEO. `to-camera` is the close-up and the
    # medium; hashed on the video's seed alone, every to-camera beat in a long
    # resolves to the same one of them and the other is never cut to at all.
    pose = (reg.get(role) if role in reg
            else reg.host_for(role, seed=f"{seed}|{shot.id}"))

    # A ROOM THAT REFUSES A CUT-OUT STILL TAKES A SHOT OF HIS FACE. The camera
    # is above the desk on `high-desk-down` and square to a wall of index cards
    # on `wall-of-calls`: there is no floor in either, and both say so in the
    # field rather than leaving it out. Standing a figure there put him on a
    # surface the camera was above. A framing has no floor line to pin, so the
    # beat survives as the close-up it should probably have been — which is
    # branching on the refusal rather than reading it as an omission.
    if (plate is not None and plate.refuses_host
            and pose is not None and pose.floor_line_y):
        instead = reg.host_for(HOST_WHERE_NOBODY_STANDS,
                               seed=f"{seed}|{shot.id}")
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
    host = dressed(reg, HostShot(pose=pose,
                                 talk=reg.host_strip(pose.key, "talk"),
                                 idle=reg.host_strip(pose.key, "idle")),
                   seed=seed)

    # A GLANCE IS CUT AGAINST THE SIDE THE GRAPHIC IS ON, and only then. The
    # kit says on the plate that a glance with the graphic on the opposite
    # side is worse than him facing camera, so straight to camera is both the
    # default and the fallback: `looking_at` returns him unchanged when the
    # side is unknown or the glance was never drawn for this pose.
    if graphic_side:
        host = looking_at(reg, host, graphic_side)

    box = None
    # A FRAMING IS A CAMERA DISTANCE AND IS NEVER SOLVED ONTO AN ANCHOR.
    # `close-up` and `medium` carry no floor line: fit into a room's standing
    # spot, a close-up is a head the size of a man, hovering where his shoes
    # would be. It is placed against the frame — or, in a two-shot, against
    # his half of it — on the eye line the plate publishes.
    if host.is_framing:
        stage = column or (0, 0, fw, fh)
        spot = frame_shot(host, (fw, fh),
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

    # THE HOST IS A SUBJECT AND HAS TO BE SEEN. A plate pushed in on a row
    # carries its anchor off the bottom with it: in the numbers walk he stood
    # at y=1832 in a 1920 frame — 13% of him on screen, reading as a smudge at
    # the edge — and the amount clipped changed shot to shot with which row
    # was lit. Clamped into the frame, he stands at the bottom of it instead.
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
    with rules drawn in ink. This is the same check the LONG runs over its
    `[PLATE]` tags, in the shape the templates need.

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
