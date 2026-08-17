"""From a template plus a script to a LAYER LIST, and the rules it must obey.

The layer list is the composition, stated as data before a single pixel is
drawn. That is deliberate: every invariant this format has is a property of
which layers exist and when, so they are checked here — cheaply, in unit
tests, on every render — rather than inferred from the output afterwards.

The pixel measurement still runs (`byproducts.held_spans`), because a layer
list that satisfies every rule can still encode to a frame that sits still.
The two checks answer different questions and neither replaces the other:
this one says the composition was specified correctly, that one says the
video actually moves.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, Sequence

from pipeline.kit_manifest import AMBIENT_REPLACING, Entry, Kit, KitError
from pipeline.marks import LINE_LEADING, block_height, face_for
from pipeline.shots import (LARGE_TYPE_FH, MIN_TYPE_FH, Format, Shot, Span,
                            TemplateError)

# THE DRAWN WORLD BOILS; TYPE AND DATA NEVER DO.
#
# The delivery boils every plate at 7fps on the principle that the drawing is
# made again each frame, and code-drawn MARKS follow it — a ring, an arrow, a
# connector, the clock's hands are drawings, and a drawing that sits still
# next to a boiling plate is the thing that reads as pasted on.
#
#   BOIL    plates, room, props, host, marks, transitions
#   NEVER   figures, labels, headers, captions, quotes, any code-drawn text,
#           and any rule or box framing it
#
# Type was boiling too, and it was wrong: a number that moves three times a
# second cannot be read, which is the whole job of a number. The two-pixel
# re-placement that reads as "the same hand" on a scribble reads as a
# vibrating figure on a sheet row. `check_invariants` refuses a text-bearing
# layer that carries a boil rate, so this cannot come back by accident.
BOIL_FPS = 7

# Moving in on a slot: how much of the frame height it should come to fill,
# and how far the plate may be enlarged doing it. Past about 2.4x the kit's
# 2x delivery starts to soften, which is the real ceiling here.
FOCUS_FILL = 0.30
# A sheet row spans the plate's full width, so any real blow-up cuts the
# labels off both sides — "Revenue" rendered as "ue". The push-in stays
# gentle and the PAN does the work: the lit row moves to the middle of the
# frame, which is the change a viewer reads between steps.
FOCUS_MAX_SCALE = 1.14

# Two different floors, because they answer different questions.
#
# MIN_TYPE_FH (3.5%) is the AUTHORED floor: a template may not ask for prose
# smaller than this, and the parser refuses it.
#
# This one is for type whose size comes from a KIT SLOT rather than from the
# template — a sheet row band, a card label. Those are short strings read in
# context, not prose, and the kit's own geometry sets them: a six-band sheet
# gives 57px rows, which is legible. What is NOT legible is a card label at
# 33px because four cards were arranged where two fit, and that is what this
# catches.
SLOT_TYPE_FLOOR_FH = 0.025

# THE PORTAL RULE. Real media — Pexels, memes, EDGAR screenshots — never
# appears as a raw cutaway. It arrives inside a container that makes it a
# thing in the room: a filing ON a screen, a print ON the desk, an item
# PINNED to the wall, a still thrown at the projection wall.
#
# This is enforced here rather than asked for in a prompt, because "b-roll
# looks imported" was a diagnosis on the format that got scrapped, and a
# convention nobody checks is how it got there.
MEDIA_PREFIX = "media."
PORTAL_CONTAINERS = {
    "filing-on-screen": ("screen",),
    "print-on-desk": ("image",),
    "pinned-item": ("image",),
    "projection-wall-16": ("projection",),
    "monitor": ("screen",),
    "cu-page": ("page",),
}


@dataclass
class Layer:
    """One thing on screen, over one window of time.

    `shot_id` is carried so "no layer may outlive its shot" is checkable
    without reconstructing which span a layer came from, and `entry_key` so
    "every shot reached the plate the template names" is checkable against
    the kit rather than against the template that asked for it.
    """

    name: str
    kind: str                    # ground|plate|fill|host|text|mark|enter|caption|ambient
    shot_id: str
    t_start: float
    t_end: float
    x: int = 0
    y: int = 0
    w: int = 0
    h: int = 0
    path: Path | None = None
    frames: tuple[Path, ...] = ()
    fps: int = 0
    loops: bool = False
    size_fh: float = 0.0         # type only; 0 for everything else
    entry_key: str = ""
    concept: str = ""
    slot: str = ""
    text: str = ""
    reveal_s: float = 0.0        # type draws on over this long
    boil_fps: int = 0            # redraw rate for code-drawn ink
    lit: bool = True             # a ghosted row is present but pushed back
    max_lines: int = 3           # the template's line budget, not a default
    halign: str = "center"       # the template's alignment, not a default
    type_px: int = 0             # a size the whole group agreed on, if any
    panel: bool = False          # paper drawn under type that sits on artwork
    z: int = 0

    @property
    def dur(self) -> float:
        return self.t_end - self.t_start

    @property
    def moves(self) -> bool:
        """Whether this layer is redrawing rather than sitting there.

        A boil plate at 7fps and a host loop at 12 both move. So does a MARK
        this code draws, on the same principle: the drawing is made again
        each frame rather than transformed. Type does not — a bare shot of
        one sentence on paper is genuinely a held frame now, and its
        `max_hold_s` is what keeps it short rather than a wobble that made
        the measurement look better than the video.
        """
        return bool((self.loops and self.frames) or self.boil_fps)


class Resolver(Protocol):
    """Supplies the words and figures. Knows nothing about composition."""

    def text_for(self, src: str) -> str | None: ...
    def image_for(self, src: str) -> Path | None: ...
    def list_for(self, src: str) -> list[str] | None: ...


@dataclass
class BuildResult:
    layers: list[Layer]
    spans: list[Span]
    register: str
    frame: tuple[int, int]
    unfilled: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    def for_shot(self, shot_id: str) -> list[Layer]:
        return [l for l in self.layers if l.shot_id == shot_id]

    def of_kind(self, kind: str) -> list[Layer]:
        return [l for l in self.layers if l.kind == kind]


def _fit_into(entry: Entry, frame: tuple[int, int]) -> tuple[int, int, float]:
    """Place a delivered plate into the output frame.

    A plate authored at the frame's own aspect covers it; anything smaller (a
    card, a page, a host cut-out) keeps its proportion and is centred by the
    caller. The scale is derived from `delivered`, which is read from the
    entry — 2x canvas for most of the kit and 1:1 for two groups of it.
    """
    fw, fh = frame
    dw, dh = entry.delivered
    if abs(dw / dh - fw / fh) < 0.02:
        return fw, fh, fw / dw
    s = min(fw / dw, fh / dh)
    return int(round(dw * s)), int(round(dh * s)), s


def _slot_in_frame(entry: Entry, slot: str, placed: tuple[int, int, int, int]
                   ) -> tuple[int, int, int, int]:
    """A slot box in OUTPUT-frame pixels, for a plate drawn at `placed`.

    Two scales compose here and both are read, never assumed: the entry's own
    `delivered / canvas`, and then the plate's placement into the frame.
    """
    px, py, pw, ph = placed
    sx, sy, sw, sh = entry.slot_px(slot)
    k = pw / entry.delivered[0]
    return (px + int(round(sx * k)), py + int(round(sy * k)),
            int(round(sw * k)), int(round(sh * k)))


def _arrange(n: int, how: str, frame: tuple[int, int],
             box: tuple[int, int, int, int] | None = None
             ) -> list[tuple[int, int, int, int]]:
    """`n` cells filling `box`, or the middle of the frame if none is given.

    Kept deliberately dumb: a grid, a row or a column, with a margin. Cards
    are centred inside their cell by the caller, so a cell being wider than
    the card it holds is fine and no card is ever stretched.

    Passing a box is how cards land ON something — the desk, the sheet —
    rather than floating on bare paper in the middle of the frame.
    """
    if box is not None:
        ox, oy, fw, fh = box
        margin = 0.03
    else:
        ox, oy = 0, 0
        fw, fh = frame
        margin = None
    if n <= 0:
        return []
    if how == "row":
        cols, rows = n, 1
    elif how == "column":
        cols, rows = 1, n
    else:
        cols = 1 if n == 1 else 2
        rows = (n + cols - 1) // cols
    if margin is None:
        mx, my = int(fw * 0.04), int(fh * 0.08)
    else:
        mx, my = int(fw * margin), int(fh * margin)
    gx, gy = int(fw * 0.03), int(fh * 0.02)
    cw = (fw - 2 * mx - gx * (cols - 1)) // cols
    ch = (fh - 2 * my - gy * (rows - 1)) // rows
    out = []
    for i in range(n):
        r, c = divmod(i, cols)
        out.append((ox + mx + c * (cw + gx), oy + my + r * (ch + gy), cw, ch))
    return out


def build_layers(fmt: Format, spans: Sequence[Span], resolver: Resolver,
                 kit: Kit, register: str, *,
                 progression: bool = False) -> BuildResult:
    """Turn the template and the script into the ordered layer list.

    `progression` advances the room across the runtime — light, clutter, the
    wall and the clock. It is off by default because a 70-second SHORT has
    nowhere to travel; the LONG turns it on.
    """
    from pipeline import progression as prog
    frame = fmt.frame
    fw, fh = frame
    layers: list[Layer] = []
    unfilled: list[str] = []
    skipped: list[str] = []

    for span in spans:
        shot = span.shot
        t0, t1 = span.start, span.end
        # A resolver may need to know which shot it is answering for — the
        # LONG serves a different chapter's words per shot. Optional, so a
        # resolver that does not care implements nothing.
        begin = getattr(resolver, "begin_shot", None)
        if begin is not None:
            begin(shot)

        # Where this shot sits in the video decides the state of the room.
        total = spans[-1].end if spans else 1.0
        state = prog.at(((t0 + t1) / 2) / total if total else 0.0)

        # -- the ground. Every frame has paper under it; kit plates are
        #    transparent PNGs and would composite onto nothing otherwise.
        layers.append(Layer(name=f"{shot.id}:ground", kind="ground",
                            shot_id=shot.id, t_start=t0, t_end=t1,
                            w=fw, h=fh, z=0))

        placed: tuple[int, int, int, int] | None = None
        entry: Entry | None = None

        # -- the transition INTO this shot, played once at the cut
        if shot.enter:
            try:
                ent = kit.concept(shot.enter, register)
            except KitError as exc:
                raise TemplateError(
                    f"{fmt.name}/{shot.id}: enter {shot.enter!r} — {exc}") from exc
            w, h, _ = _fit_into(ent, frame)
            layers.append(Layer(
                name=f"{shot.id}:enter:{shot.enter}", kind="enter",
                shot_id=shot.id, t_start=t0,
                t_end=min(t0 + ent.cycle_s, t1),
                x=(fw - w) // 2, y=(fh - h) // 2, w=w, h=h,
                frames=ent.paths, fps=ent.fps, loops=ent.loops,
                entry_key=ent.key, concept=ent.concept, z=90))

        # -- the plate. `None` is a real value: a bare-ground shot.
        if shot.plate:
            plate_name = (prog.restate(shot.plate, state)
                          if progression else shot.plate)
            try:
                entry = kit.concept(plate_name, register)
            except KitError as exc:
                raise TemplateError(
                    f"{fmt.name}/{shot.id}: plate {plate_name!r} — {exc}") from exc
            w, h, _ = _fit_into(entry, frame)
            placed = ((fw - w) // 2, (fh - h) // 2, w, h)
            # Moving in on a slot: scale the plate so that slot fills a real
            # share of the frame, and centre it there. Without this a walk
            # down a list is one wide shot with a rectangle migrating down it,
            # which a viewer reads as a single held composition.
            if shot.focus and shot.focus in entry.slots:
                sx, sy, sw, sh = entry.slot_px(shot.focus)
                k = min((fh * FOCUS_FILL) / max(sh, 1), FOCUS_MAX_SCALE)
                k = max(k, 1.0)
                nw, nh = int(w * k), int(h * k)
                cx = int((sx + sw / 2) * (nw / entry.delivered[0]))
                cy = int((sy + sh / 2) * (nh / entry.delivered[1]))
                placed = (fw // 2 - cx, fh // 2 - cy, nw, nh)
                w, h = nw, nh
            layers.append(Layer(
                name=f"{shot.id}:plate:{plate_name}", kind="plate",
                shot_id=shot.id, t_start=t0, t_end=t1,
                x=placed[0], y=placed[1], w=w, h=h,
                frames=entry.paths, fps=entry.fps, loops=entry.loops,
                entry_key=entry.key, concept=entry.concept, z=10))

        # -- LIGHT, above the plate and below anything code draws.
        #
        # The room is lit; the numbers are not. Light sits at z=11 — over the
        # plate and the host, who are both in the room and should be — and
        # under every fill, panel, line of type and mark, which are data and
        # must never be tinted.
        if progression and entry is not None and kit.has(state.light, register):
            lent = kit.concept(state.light, register)
            if abs(lent.delivered[0] / lent.delivered[1] - fw / fh) < 0.05:
                layers.append(Layer(
                    name=f"{shot.id}:light:{state.light}", kind="light",
                    shot_id=shot.id, t_start=t0, t_end=t1,
                    x=0, y=0, w=fw, h=fh,
                    frames=lent.paths, fps=lent.fps, loops=lent.loops,
                    entry_key=lent.key, concept=lent.concept, z=11))

        # -- THE CLOCK. Its face is a slot; the hands are drawn to the hour
        #    the light is telling, so the window and the clock agree.
        if progression and entry is not None and "clock-face" in entry.slots:
            cb = _slot_in_frame(entry, "clock-face", placed)
            layers.append(Layer(
                name=f"{shot.id}:clock", kind="clock", shot_id=shot.id,
                t_start=t0, t_end=t1, x=cb[0], y=cb[1], w=cb[2], h=cb[3],
                size_fh=state.hour, boil_fps=BOIL_FPS, z=12))

        # -- AMBIENT. Steam off the mug, the cursor, the second hand: these
        #    run continuously under every room shot and are what keeps a
        #    held wide shot alive. Only the ADDITIVE ones — see progression.
        if progression and entry is not None and shot.plate and \
                shot.plate.startswith(("room-", "at-the-", "desk-")):
            for amb in prog.AMBIENT_ADDITIVE_USED:
                if not kit.has(amb, register):
                    continue
                aent = kit.concept(amb, register)
                fx, fy, fwr, fhr = prog.AMBIENT_PLACEMENT[amb]
                layers.append(Layer(
                    name=f"{shot.id}:amb:{amb}", kind="plate",
                    shot_id=shot.id, t_start=t0, t_end=t1,
                    x=int(fw * fx), y=int(fh * fy),
                    w=int(fw * fwr), h=int(fh * fhr),
                    frames=aent.paths, fps=aent.fps, loops=aent.loops,
                    entry_key=aent.key, concept=aent.concept, z=13))

        # -- slot fills: charts, nested plates, row content
        for fill_index, (slot, src) in enumerate(shot.bind.items()):
            # Declaration order is entry order when the shot staggers.
            fill_t0 = min(t0 + fill_index * shot.stagger_s, max(t1 - 0.3, t0))
            # A leading '?' means the slot is optional: a sheet has six row
            # bands and a script may carry four metrics, and two blank bands
            # is the correct drawing, not a missing asset. Everything without
            # the mark is required and fails the build when it is empty.
            optional = src.startswith("?")
            src = src.lstrip("?")
            box = None
            if entry is not None and slot in entry.slots:
                box = _slot_in_frame(entry, slot, placed)

            # A nested plate — the page on the desk, the card on the table —
            # resolves through the kit, in the video's own register, and is
            # fitted into the slot it was bound to.
            if src.startswith("plate."):
                nested = kit.concept(src.split(".", 1)[1], register)
                bw, bh = (box[2], box[3]) if box else (fw, fh)
                k = min(bw / nested.delivered[0], bh / nested.delivered[1])
                nw, nh = int(nested.delivered[0] * k), int(nested.delivered[1] * k)
                nx = (box[0] + (bw - nw) // 2) if box else (fw - nw) // 2
                ny = (box[1] + (bh - nh) // 2) if box else (fh - nh) // 2
                layers.append(Layer(
                    name=f"{shot.id}:fill:{slot}", kind="fill",
                    shot_id=shot.id, t_start=fill_t0, t_end=t1,
                    x=nx, y=ny, w=nw, h=nh,
                    frames=nested.paths, fps=nested.fps, loops=nested.loops,
                    entry_key=nested.key, concept=nested.concept,
                    slot=slot, z=20))
                continue

            # The portal rule, checked before anything is placed.
            if src.startswith(MEDIA_PREFIX):
                allowed = PORTAL_CONTAINERS.get(shot.plate or "")
                if allowed is None:
                    raise TemplateError(
                        f"{fmt.name}/{shot.id}: binds real media {src!r} on "
                        f"plate {shot.plate!r}, which is not a container. "
                        f"Media arrives inside one of "
                        f"{sorted(PORTAL_CONTAINERS)} — never as a raw "
                        f"cutaway.")
                if slot not in allowed:
                    raise TemplateError(
                        f"{fmt.name}/{shot.id}: binds real media {src!r} to "
                        f"slot {slot!r} of {shot.plate}, whose media slot is "
                        f"{allowed[0]!r}.")

            img = resolver.image_for(src)
            if img is None:
                txt = resolver.text_for(src)
                if txt is None:
                    if not optional:
                        unfilled.append(f"{shot.id}.{slot} <- {src}")
                    continue
                layers.append(Layer(
                    name=f"{shot.id}:fill:{slot}", kind="fill",
                    shot_id=shot.id, t_start=fill_t0, t_end=t1,
                    x=box[0] if box else 0, y=box[1] if box else 0,
                    w=box[2] if box else fw, h=box[3] if box else fh,
                    slot=slot, text=txt,
                    lit=shot.lit in (None, "all", slot), z=20))
                continue
            # A resolver may hand back a SEQUENCE instead of one file: an
            # image that was drawn more than once so it can boil like the
            # plates do. It is a normal animated layer from here on.
            if isinstance(img, (list, tuple)):
                layers.append(Layer(
                    name=f"{shot.id}:fill:{slot}", kind="fill",
                    shot_id=shot.id, t_start=fill_t0, t_end=t1,
                    x=box[0] if box else 0, y=box[1] if box else 0,
                    w=box[2] if box else fw, h=box[3] if box else fh,
                    frames=tuple(img), fps=BOIL_FPS, loops=True,
                    slot=slot, z=20))
                continue
            layers.append(Layer(
                name=f"{shot.id}:fill:{slot}", kind="fill",
                shot_id=shot.id, t_start=fill_t0, t_end=t1,
                x=box[0] if box else 0, y=box[1] if box else 0,
                w=box[2] if box else fw, h=box[3] if box else fh,
                path=img, slot=slot, z=20))

        # -- a repeated concept: N instances of one card, from a list
        if shot.repeat and shot.repeat.spatial:
            rep = shot.repeat
            items = []
            getter = getattr(resolver, "list_for", None)
            if getter is not None:
                items = list(getter(rep.src) or [])
            if not items:
                unfilled.append(f"{shot.id}.repeat <- {rep.src}")
            items = items[:max(rep.max, 1)]
            if rep.only is not None:
                items = items[rep.only:rep.only + 1]
            rent = kit.concept(rep.concept, register)
            within = None
            if rep.within and entry is not None and rep.within in entry.slots:
                within = _slot_in_frame(entry, rep.within, placed)
            for idx, (bx, by, bw, bh) in enumerate(
                    _arrange(len(items), rep.arrange, frame, within)):
                k = min(bw / rent.delivered[0], bh / rent.delivered[1])
                cw, ch = int(rent.delivered[0] * k), int(rent.delivered[1] * k)
                cx, cy = bx + (bw - cw) // 2, by + (bh - ch) // 2
                # Each card enters on its own beat. That stagger is the motion
                # the ceiling rule looks for, and it is why this beat can run
                # seven seconds without being a held frame.
                enter_at = min(t0 + idx * rep.stagger_s, max(t1 - 0.4, t0))
                layers.append(Layer(
                    name=f"{shot.id}:repeat:{rep.concept}:{idx}", kind="plate",
                    shot_id=shot.id, t_start=enter_at, t_end=t1,
                    x=cx, y=cy, w=cw, h=ch,
                    frames=rent.paths, fps=rent.fps, loops=rent.loops,
                    entry_key=rent.key, concept=rent.concept, z=15))
                # The arrows BETWEEN the cards are what makes a chain a
                # chain. Drawn in the gap after each card except the last —
                # inside every card, they connect nothing and three panels
                # read as three unrelated notes.
                if rep.connector and idx + 1 < len(items) and rep.arrange in ("column", "row"):
                    if rep.arrange == "column":
                        gx0, gy0 = cx + cw // 2 - int(cw * 0.10), cy + ch
                        gw, gh = int(cw * 0.20), max(by + bh - (cy + ch), 12)
                    else:
                        gx0, gy0 = cx + cw, cy + ch // 2 - int(ch * 0.08)
                        gw, gh = max(bx + bw - (cx + cw), 12), int(ch * 0.16)
                    layers.append(Layer(
                        name=f"{shot.id}:link:{idx}", kind="mark",
                        shot_id=shot.id, t_start=enter_at, t_end=t1,
                        x=gx0, y=gy0, w=gw, h=gh,
                        slot=rep.connector, boil_fps=BOIL_FPS, z=26))

                for slot_name, expr in (rep.bind or {}).items():
                    if slot_name not in rent.slots:
                        continue
                    sx, sy, sw, sh = rent.slot_px(slot_name)
                    kk = cw / rent.delivered[0]
                    bx = (cx + int(sx * kk), cy + int(sy * kk),
                          int(sw * kk), int(sh * kk))
                    # A card's `mark` slot exists for a drawn mark, not for
                    # type. Left unbound it is a declared, empty box in the
                    # middle of every card.
                    if expr.startswith("$mark:"):
                        layers.append(Layer(
                            name=f"{shot.id}:repeat:{slot_name}:{idx}",
                            kind="mark", shot_id=shot.id,
                            t_start=enter_at, t_end=t1,
                            x=bx[0], y=bx[1], w=bx[2], h=bx[3],
                            slot=expr.split(":", 1)[1], boil_fps=BOIL_FPS,
                            z=25))
                        continue
                    value = (items[idx] if expr == "$item"
                             else resolver.text_for(expr))
                    if value is None:
                        continue
                    layers.append(Layer(
                        name=f"{shot.id}:repeat:{slot_name}:{idx}", kind="fill",
                        shot_id=shot.id, t_start=enter_at, t_end=t1,
                        x=bx[0], y=bx[1], w=bx[2], h=bx[3],
                        slot=slot_name, text=str(value), z=25))

        # -- the host, in the plate's figure slot
        if shot.host:
            try:
                hent = kit.concept(shot.host.pose, register)
            except KitError as exc:
                raise TemplateError(
                    f"{fmt.name}/{shot.id}: host {shot.host.pose!r} — {exc}"
                ) from exc
            if entry is not None and shot.host.slot in entry.slots:
                hx, hy, hw, hh = _slot_in_frame(entry, shot.host.slot, placed)
                k = min(hw / hent.delivered[0], hh / hent.delivered[1])
                dw, dh = (int(hent.delivered[0] * k), int(hent.delivered[1] * k))
                hx, hy = hx + (hw - dw) // 2, hy + (hh - dh)
            else:
                k = min(fw / hent.delivered[0], fh * 0.55 / hent.delivered[1])
                dw, dh = (int(hent.delivered[0] * k), int(hent.delivered[1] * k))
                hx, hy = (fw - dw) // 2, fh - dh
            # THE HOST IS A SUBJECT AND HAS TO BE SEEN. A figure slot belongs
            # to the plate, and a plate that is pushed in on a row carries the
            # slot off the bottom with it: in the numbers walk the host stood
            # at y=1832 in a 1920 frame — 13% of him on screen, reading as a
            # smudge at the edge — and the amount clipped changed shot to
            # shot with which row was lit. Clamped into the frame, he stands
            # at the bottom of it instead, which is where a figure in front
            # of a wall-sized sheet belongs.
            if dh > fh:
                dw, dh = int(dw * fh / dh), fh
            hy = min(max(hy, 0), fh - dh)
            hx = min(max(hx, 0), max(fw - dw, 0))
            layers.append(Layer(
                name=f"{shot.id}:host:{shot.host.pose}", kind="host",
                shot_id=shot.id, t_start=t0, t_end=t1,
                x=hx, y=hy, w=dw, h=dh,
                frames=hent.paths, fps=hent.fps, loops=hent.loops,
                entry_key=hent.key, concept=hent.concept, z=40))

        # -- type
        for spec in shot.text:
            body = resolver.text_for(spec.src)
            if not body:
                skipped.append(f"{shot.id}.{spec.name} <- {spec.src}")
                continue
            size_px = int(round(spec.size_fh * fh))
            if spec.slot and entry is not None:
                # "page.headline" means the headline slot of the plate nested
                # INTO this shot, not of the shot's own plate. Both the entry
                # and the placement have to come from the nested layer, or the
                # type lands in the outer plate's coordinates.
                where, _, sname = spec.slot.rpartition(".")
                host_entry, host_placed = entry, placed
                if where:
                    nested = next((l for l in layers
                                   if l.shot_id == shot.id and l.kind == "fill"
                                   and l.entry_key), None)
                    if nested is not None:
                        host_entry = kit[nested.entry_key]
                        host_placed = (nested.x, nested.y, nested.w, nested.h)
                try:
                    bx = _slot_in_frame(host_entry, sname, host_placed)
                except KitError:
                    bx = (int(fw * 0.08), int(fh * 0.4),
                          int(fw * 0.84), int(fh * 0.2))
            else:
                bw = int(fw * 0.84)
                bh = block_height(face_for(spec.size_fh), size_px,
                                  spec.max_lines)
                if spec.align == "top":
                    by = int(fh * 0.06)
                elif spec.align == "center":
                    by = (fh - bh) // 2
                elif spec.align == "bottom":
                    by = fh - bh - int(fh * 0.08)
                else:
                    by = int(float(spec.align) * fh) - bh // 2
                bx = (int(fw * 0.08), by, bw, bh)
            # Type free-placed over artwork needs its own paper. The room is
            # a drawing of a room: a line set at the top of it lands across
            # the window, the shelf and the clock, and no amount of sizing
            # fixes that. A slot-bound line needs nothing — the plate already
            # left that box empty for it.
            needs_panel = spec.slot is None and entry is not None
            if needs_panel:
                # Size the paper to the LINES ACTUALLY DRAWN, not to the box
                # they were allowed. A three-line budget holding one line left
                # two lines of empty paper under it, which is the same fault
                # as a declared box with nothing in it.
                from pipeline import marks as _mk
                _tw, th = _mk.measure_block(
                    body, bx, font_name=face_for(spec.size_fh),
                    size_px=int(spec.size_fh * fh),
                    max_lines=spec.max_lines)
                th = min(max(th, int(spec.size_fh * fh)), bx[3])
                layers.append(Layer(
                    name=f"{shot.id}:panel:{spec.name}", kind="panel",
                    shot_id=shot.id, t_start=t0, t_end=t1,
                    x=bx[0] - int(fw * 0.03), y=bx[1] - int(fh * 0.012),
                    w=bx[2] + int(fw * 0.06), h=th + int(fh * 0.024),
                    z=55))
            layers.append(Layer(
                name=f"{shot.id}:text:{spec.name}", kind="text",
                shot_id=shot.id,
                t_start=t0, t_end=t1,
                x=bx[0], y=bx[1], w=bx[2], h=bx[3],
                size_fh=spec.size_fh, text=body, reveal_s=spec.draw_on_s,
                slot=spec.color, halign=spec.halign,
                max_lines=spec.max_lines, panel=needs_panel, z=60))

        # -- marks land after the thing they mark
        for m in shot.marks:
            bx = None
            # A mark inside a filled image — the extreme candle on the chart —
            # is positioned in fractions of that image by whoever drew it, so
            # the ring lands on the datum and not on a box near it.
            if "." in m.target:
                frac = getattr(resolver, "frac_box_for", lambda _s: None)(m.target)
                host_fill = next(
                    (l for l in layers
                     if l.shot_id == shot.id and l.kind == "fill"
                     and (l.path or l.frames)),
                    None)
                if frac is not None and host_fill is not None:
                    fx, fy, fwr, fhr = frac
                    bx = (host_fill.x + int(host_fill.w * fx),
                          host_fill.y + int(host_fill.h * fy),
                          max(int(host_fill.w * fwr), 8),
                          max(int(host_fill.h * fhr), 8))
            # "page.body-3-circled" is a slot of the plate nested INTO this
            # shot, the same address the text specs use. Resolved the same way,
            # or the ring silently fails to land on the clause it is for.
            if bx is None and "." in m.target:
                where, _, sname = m.target.rpartition(".")
                nested = next((l for l in layers
                               if l.shot_id == shot.id and l.kind == "fill"
                               and l.entry_key), None)
                if where and nested is not None:
                    ne = kit[nested.entry_key]
                    if sname in ne.slots:
                        bx = _slot_in_frame(
                            ne, sname, (nested.x, nested.y, nested.w, nested.h))
            if bx is None:
                target = next(
                    (l for l in layers
                     if l.shot_id == shot.id
                     and (l.slot == m.target or l.name.endswith(m.target))),
                    None)
                if target is not None:
                    bx = (target.x, target.y, target.w, target.h)
                elif entry is not None and m.target in entry.slots:
                    bx = _slot_in_frame(entry, m.target, placed)
            if bx is None:
                skipped.append(f"{shot.id}.mark:{m.kind} <- {m.target}")
                continue
            layers.append(Layer(
                name=f"{shot.id}:mark:{m.name}", kind="mark",
                shot_id=shot.id,
                t_start=min(t0 + 0.35, t1), t_end=t1,
                x=bx[0], y=bx[1], w=bx[2], h=bx[3], slot=m.kind,
                boil_fps=BOIL_FPS, z=70))

    _agree_on_a_sheet(layers, fh)
    return BuildResult(layers=layers, spans=list(spans), register=register,
                       frame=frame, unfilled=unfilled, skipped=skipped)


def _row_size(l: Layer, fh: int) -> int:
    """The size a sheet row actually sets at, by the renderer's own fitter."""
    from PIL import Image, ImageDraw
    from pipeline import marks as _mk
    parts = l.text.split("\t")
    size, _kept, _drop = _mk.fit_columns(
        ImageDraw.Draw(Image.new("L", (8, 8))), parts[0],
        [v for v in parts[1:] if v], l.w, l.h,
        font_name=_mk.DISPLAY_FONT if l.lit else _mk.BODY_FONT,
        start_px=l.type_px, min_px=int(SLOT_TYPE_FLOOR_FH * fh))
    return size


def _agree_on_a_sheet(layers: list[Layer], fh: int) -> None:
    """One type size and one set of periods for every row of a sheet.

    Two faults, one cause: a row sized on its own knows nothing about the
    rows above it.

    THE SIZE. A stock row has a single figure where a flow has five, so it
    never has to shrink and comes out half again as big — "Shares out" was
    shouting over the table it is a row of. The rows are measured together
    and the smallest size wins.

    THE PERIODS. `fit_columns` gives up the oldest period rather than set a
    row below the legibility floor, which is the right policy for one row and
    a disaster for five: Revenue kept three years, Free cash flow kept two,
    and the header still said five. Columns that do not line up are worse
    than small type. So the DROP is decided for the sheet — the most periods
    every series row can show — and every row shows the same ones.

    Both answers come from the same `fit_columns` the renderer draws with,
    called once more here, so neither can drift from what lands on the frame.
    """
    from PIL import Image, ImageDraw
    from pipeline import marks as _mk
    d = ImageDraw.Draw(Image.new("L", (8, 8)))
    floor = int(SLOT_TYPE_FLOOR_FH * fh)
    rows: dict[tuple[str, int], list[Layer]] = {}
    for l in layers:
        if l.kind == "fill" and "\t" in (l.text or "") and l.h:
            rows.setdefault((l.shot_id, l.h), []).append(l)

    for group in rows.values():
        if len(group) < 2:
            continue
        parsed = [(l, l.text.split("\t")[0],
                   [v for v in l.text.split("\t")[1:] if v]) for l in group]
        widest = max(len(v) for _l, _lab, v in parsed)
        if widest < 2:
            continue

        def _measure(keep: int) -> tuple[int, bool]:
            sizes, clean = [], True
            for l, lab, vals in parsed:
                # A stock row is one reading and a date, not a series: it
                # shares the SIZE but has no periods to give up.
                use = vals[-keep:] if len(vals) == widest else vals
                size, _kept, dropped = _mk.fit_columns(
                    d, lab, use, l.w, l.h, min_px=floor,
                    font_name=_mk.DISPLAY_FONT if l.lit else _mk.BODY_FONT)
                sizes.append(size)
                clean = clean and not dropped
            return min(sizes), clean

        keep = widest
        while keep > 2:
            size, clean = _measure(keep)
            if clean and size >= floor:
                break
            keep -= 1
        else:
            size, _clean = _measure(keep)

        for l, lab, vals in parsed:
            if len(vals) == widest and keep < widest:
                l.text = "\t".join([lab] + vals[-keep:])
            l.type_px = size


# ---------------------------------------------------------------------------
# The invariants
# ---------------------------------------------------------------------------

def check_invariants(fmt: Format, result: BuildResult,
                     *, host_shots: Sequence[str] | None = None) -> list[str]:
    """Every rule the composition must obey, as human-readable failures.

    Empty list means the composition is legal. This is what the unit tests
    assert on, and what a render refuses to proceed past.
    """
    problems: list[str] = []
    spans = {s.shot.id: s for s in result.spans}
    fh = result.frame[1]

    # 1. No layer may outlive its shot.
    for l in result.layers:
        sp = spans.get(l.shot_id)
        if sp is None:
            problems.append(f"{l.name}: belongs to no shot in this cut")
            continue
        if l.t_start < sp.start - 1e-6 or l.t_end > sp.end + 1e-6:
            problems.append(
                f"{l.name}: runs {l.t_start:.2f}-{l.t_end:.2f}s, outside its "
                f"shot {l.shot_id} ({sp.start:.2f}-{sp.end:.2f}s)")
        if l.dur <= 0:
            problems.append(f"{l.name}: zero-length layer")

    # 2. No composition may sit unchanged longer than max_hold_s unless
    #    something provably enters or leaves inside its span.
    #
    #    A composition changes exactly when a layer starts or ends. So the
    #    holds inside a shot are the gaps between consecutive layer
    #    boundaries, and the longest of them is what the ceiling applies to —
    #    not the shot's own duration, which is why a long shot with a mark
    #    landing inside it is legal and a short one with nothing moving is not.
    for sp in result.spans:
        ceiling = sp.shot.max_hold_s
        marks = {sp.start, sp.end}
        for l in result.layers:
            if l.shot_id != sp.shot.id:
                continue
            # A looping element redraws continuously — a boil plate at 7fps is
            # the whole reason a frame does not read as a photograph — so it
            # is motion for the entire time it is on screen.
            if l.moves and l.dur > 0:
                marks.update((l.t_start, l.t_end))
                continue
            marks.update((l.t_start, l.t_end))
            if l.reveal_s > 0:
                marks.add(min(l.t_start + l.reveal_s, l.t_end))
        moving = any(l.shot_id == sp.shot.id and l.moves
                     for l in result.layers)
        if moving:
            continue
        ordered = sorted(m for m in marks if sp.start - 1e-6 <= m <= sp.end + 1e-6)
        worst = max((b - a for a, b in zip(ordered, ordered[1:])), default=sp.dur)
        if worst > ceiling + 1e-6:
            problems.append(
                f"{sp.shot.id}: composition holds {worst:.2f}s with nothing "
                f"entering or leaving, over its {ceiling:.1f}s ceiling")

    # 3. Large type and the caption band are mutually exclusive.
    for sp in result.spans:
        big = [l for l in result.layers
               if l.shot_id == sp.shot.id and l.kind == "text"
               and l.size_fh >= LARGE_TYPE_FH]
        if big and sp.shot.captions:
            problems.append(
                f"{sp.shot.id}: type at {max(l.size_fh for l in big):.1%} of "
                f"frame height shares the frame with the caption band")

    # 4. The host appears in the shots named and nowhere else.
    if host_shots is not None:
        got = {l.shot_id for l in result.layers if l.kind == "host"}
        want = set(host_shots)
        for extra in sorted(got - want):
            problems.append(f"{extra}: host present in a shot they are not in")
        for miss in sorted(want - got):
            problems.append(f"{miss}: host missing from a shot they are in")

    # 5b. A slot whose natural type size is under the floor. The box exists
    #     and the words fit it, but nobody can read them on a phone — which
    #     is a geometry problem in the arrangement, not in the script.
    for l in result.layers:
        if l.kind != "fill" or not l.text:
            continue
        # A two-letter marker like "vs" sits in a deliberately tiny slot and
        # is legible there; the floor is about words you have to READ.
        if len(l.text) <= 6:
            continue
        # A tabbed row is MEASURED with the fitter, not estimated from the
        # band height. `h * 0.42` said 81px while the row actually set at
        # 33px, so the floor this rule exists to enforce was never tested
        # against the number that reaches the frame.
        if "\t" in l.text:
            natural = _row_size(l, fh)
        else:
            natural = int(l.h * 0.34)
        if natural and natural < fh * SLOT_TYPE_FLOOR_FH:
            problems.append(
                f"{l.name}: its slot gives {natural}px type, under the "
                f"{int(fh * SLOT_TYPE_FLOOR_FH)}px slot floor — too many "
                f"placed where fewer fit")

    # 4b. The host is not mostly off the frame.
    #
    #     A figure slot belongs to the PLATE, and a focus push moves the plate.
    #     Nothing else notices: the layer exists, the invariants above are all
    #     satisfied, and the host is drawn — 87% of him past the bottom edge.
    for l in result.layers:
        if l.kind != "host" or not (l.w and l.h):
            continue
        vis_w = max(min(l.x + l.w, result.frame[0]) - max(l.x, 0), 0)
        vis_h = max(min(l.y + l.h, fh) - max(l.y, 0), 0)
        seen = (vis_w * vis_h) / float(l.w * l.h)
        if seen < 0.75:
            problems.append(
                f"{l.name}: {seen:.0%} of the host is on screen — the rest is "
                f"past the frame edge, drawn and not seen")
        # And he does not stand on the data. Clamping him into the frame is
        # only half the rule: pushed in on a sheet there is nowhere for a
        # figure that is not over a row, and the answer is that he is not in
        # that shot, not that he is drawn across the numbers.
        for o in result.for_shot(l.shot_id):
            if o.kind not in ("fill", "text") or not o.text:
                continue
            ox = min(l.x + l.w, o.x + o.w) - max(l.x, o.x)
            oy = min(l.y + l.h, o.y + o.h) - max(l.y, o.y)
            if ox > 0 and oy > 0 and (ox * oy) > 0.20 * o.w * o.h:
                problems.append(
                    f"{l.name} stands over {o.name} — the host is drawn "
                    f"across {(ox * oy) / (o.w * o.h):.0%} of it")

    # 4c. THE DRAWN WORLD BOILS; TYPE AND DATA NEVER DO.
    #
    #     A number that moves three times a second cannot be read, which is
    #     the whole job of a number. The wobble that reads as "the same hand"
    #     on a ring reads as a vibrating figure on a sheet row — and it was
    #     on every row, every label, every caption and every panel edge.
    #
    #     Checked on the layer list, so it is answered before a frame is
    #     drawn and cannot come back as a default somebody re-adds.
    for l in result.layers:
        if not l.boil_fps:
            continue
        if l.text or l.kind in ("text", "panel", "caption"):
            problems.append(
                f"{l.name}: carries type and a {l.boil_fps}fps boil — the "
                f"drawn world boils, type and data never do")

    # 5c. A text box that cannot hold the lines it promises, at the smallest
    #     size those lines are allowed to be.
    #
    #     This is pure geometry and needs no words: LINE_LEADING * the
    #     readability floor is the height of one line, and a box shorter than
    #     that holds nothing readable however short the script is. The fitter
    #     shrinks type to fit, but it stops at the floor — below that it draws
    #     THROUGH the bottom of the box rather than under it, and says nothing,
    #     because the words all fitted the line count it was given.
    #
    #     THE NEWS shipped this way: a headline slot 123px tall in frame,
    #     asked for three lines, drew three lines of 67px type 237px tall
    #     straight over the red annotation in the slot below it. Nothing in
    #     the suite could see it, because no characters were lost.
    for l in result.layers:
        if l.kind != "text" or not l.h:
            continue
        line_h = MIN_TYPE_FH * fh * LINE_LEADING
        holds = int(l.h / line_h)
        if holds < 1:
            problems.append(
                f"{l.name}: its box is {l.h}px tall and one line at the "
                f"{MIN_TYPE_FH:.1%} floor is {int(line_h)}px — no readable "
                f"type fits it at all")
        elif holds < l.max_lines:
            problems.append(
                f"{l.name}: asks for {l.max_lines} lines in a {l.h}px box "
                f"that holds {holds} at the {MIN_TYPE_FH:.1%} floor — the "
                f"rest draws through whatever is under it")

    # 5d. Two blocks of type in one shot may not overlap.
    #
    #     Slot-bound type cannot collide, because the plate authored the
    #     slots apart. FREE-PLACED type can: `align` is a fraction of frame
    #     height and two of them chosen by hand will eventually meet. The
    #     boxes are known before the render, so the collision is too.
    for sp in result.spans:
        blocks = [l for l in result.layers
                  if l.shot_id == sp.shot.id and l.kind in ("text", "panel")]
        for i, a in enumerate(blocks):
            for b in blocks[i + 1:]:
                if a.name.split(":")[-1] == b.name.split(":")[-1]:
                    continue        # a panel and the type it sits under
                if (a.x < b.x + b.w and b.x < a.x + a.w
                        and a.y < b.y + b.h and b.y < a.y + a.h):
                    problems.append(
                        f"{a.name} and {b.name} overlap — two blocks of type "
                        f"in one shot, drawn over each other")

    # 5. Nothing renders below 3.5% of frame height.
    for l in result.layers:
        if l.kind == "text" and 0 < l.size_fh < MIN_TYPE_FH:
            problems.append(
                f"{l.name}: type at {l.size_fh:.2%} of frame height, below "
                f"the {MIN_TYPE_FH:.1%} floor")
        if l.kind in ("plate", "fill", "host") and 0 < l.h < fh * MIN_TYPE_FH:
            problems.append(
                f"{l.name}: {l.h}px tall, under {MIN_TYPE_FH:.1%} of frame")

    # 6. Every shot reached the plate its template names.
    for sp in result.spans:
        if not sp.shot.plate:
            continue
        got = [l for l in result.layers
               if l.shot_id == sp.shot.id and l.kind == "plate"]
        if not got:
            problems.append(f"{sp.shot.id}: names plate "
                            f"{sp.shot.plate!r} but no plate layer exists")
        elif not _same_plate(got[0].concept, sp.shot.plate):
            problems.append(
                f"{sp.shot.id}: names plate {sp.shot.plate!r} but reached "
                f"{got[0].concept!r}")

    # 7. No unfilled slot. A slot with no value is a drawn, empty box.
    for u in result.unfilled:
        problems.append(f"unfilled slot: {u}")

    return problems


BUDGETS_PATH = Path("templates") / "budgets.json"


def check_budgets(fmt: Format, result: BuildResult,
                  root: Path | str = ".") -> list[str]:
    """Every line that will not fit the box the template puts it in.

    Shrink-then-cut was the wrong contract. Type that does not fit is a script
    the renderer cannot express, and the operator has to know that BEFORE the
    encode, not discover a sentence ending mid-word in the output. So this
    runs on the layer list and its findings block the render.

    The budgets are measured, not guessed: `templates/budgets.json` is
    produced by running the real fitter against the real templates, and
    `tests/test_budgets.py` fails if the two ever disagree.
    """
    path = Path(root) / BUDGETS_PATH
    if not path.exists():
        return []
    import json
    budgets = json.loads(path.read_text(encoding="utf-8")).get("formats", {})
    mine = budgets.get(fmt.name)
    if not mine:
        return []

    problems: list[str] = []
    for l in result.layers:
        if l.kind not in ("text", "fill") or not l.text:
            continue
        dest = l.name.split(":", 1)[1]
        budget = mine.get(dest)
        if budget is None:
            continue
        n = len(l.text)
        if n > budget:
            problems.append(
                f"{l.shot_id}: {dest} holds {budget} characters and was given "
                f"{n} — {n - budget} would be cut. Shorten the script, or "
                f"change the shot.")
    return problems


def _same_plate(reached: str, named: str) -> bool:
    """Whether a shot got the plate it asked for, allowing for progression.

    A template names `room-wide-16--lived-in`; three-quarters through the
    video progression re-points it at `room-wide-16--3am`. That is the device
    working, not the wrong plate — so the FAMILY has to match and the state
    is free. `evidence-wall-half` for `evidence-wall-empty` likewise.
    """
    if reached == named:
        return True
    if "--" in reached and "--" in named:
        return reached.rpartition("--")[0] == named.rpartition("--")[0]
    for stem in ("evidence-wall-",):
        if reached.startswith(stem) and named.startswith(stem):
            return True
    return False


def held_layer_spans(result: BuildResult) -> list[tuple[float, float, str]]:
    """Every window where nothing enters or leaves, longest first.

    The layer-list twin of `byproducts.held_spans`, for reading a composition
    before it is rendered.
    """
    out = []
    for sp in result.spans:
        if any(l.shot_id == sp.shot.id and l.moves for l in result.layers):
            continue
        marks = {sp.start, sp.end}
        for l in result.layers:
            if l.shot_id == sp.shot.id:
                marks.update((l.t_start, l.t_end))
        o = sorted(marks)
        for a, b in zip(o, o[1:]):
            out.append((a, b, sp.shot.id))
    return sorted(out, key=lambda x: x[1] - x[0], reverse=True)
