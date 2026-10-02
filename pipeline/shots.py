"""Shot templates: a FORMAT is an ordered list of SHOTS, and it is data.

`templates/shots/<format>.json` fixes SPACE and ORDER — which plate, what goes
in which slot, in what sequence. It fixes no durations. The audio clock fixes
those: every shot binds to a span of narration and word timestamps decide when
it starts and when it ends. Nothing here is expressed in seconds except
`max_hold_s`, which is a ceiling to be checked rather than a duration to be
applied.

Adding a format is authoring a JSON file. If a new format needs a code change
here, the engine is wrong and that should be said out loud rather than
special-cased.

The scenarist chooses none of this. The script supplies words and figures; the
template decides where they land.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Collection, Sequence

TEMPLATE_DIR = Path("templates/shots")

# A shot may not be shorter than this. Below it nothing on screen can be read,
# and a span that collapses this far means the anchoring is wrong upstream.
MIN_SHOT_S = 0.8

# Nothing renders below this fraction of frame height. Type smaller than this
# is unreadable on a phone, which is the only place a SHORT is watched.
MIN_TYPE_FH = 0.035


class TemplateError(RuntimeError):
    """A shot template is malformed, or names something the kit lacks."""


# Templates are data, which means a typo in one is a silent no-op unless the
# parser refuses what it does not understand. `repeat` was dropped without a
# word the first time MACRO declared it, and the shot parsed as bare ground
# with nothing in it — a format quietly one shot shorter than it says it is.
# Every key any of these objects may carry is listed, and anything else is an
# error naming the key and the shot it is in.
FORMAT_KEYS = frozenset({"format", "aspect", "frame", "shots", "notes",
                         "orders", "safe"})
SHOT_KEYS = frozenset({"id", "plate", "bind", "text", "marks", "host", "enter",
                       "lit", "anchor", "max_hold_s", "captions", "notes",
                       "repeat", "stagger_s", "focus", "alts", "meme"})
# An ALTERNATE is the same beat drawn on a different plate. It carries its own
# `bind` because interchangeable plates rarely name their slots the same way:
# `structure/closing` writes `line-1` and `structure/end-card` writes `line`,
# and a shared bind map would name a slot one of them does not declare.
ALT_KEYS = frozenset({"plate", "bind", "lit", "focus", "notes", "prefer"})
ORDER_KEYS = frozenset({"name", "shots", "notes"})
TEXT_KEYS = frozenset({"name", "src", "size_fh", "align", "halign",
                       "max_lines", "draw_on_s", "color", "slot"})
MARK_KEYS = frozenset({"kind", "target", "name", "after_s"})
# `meme` marks the ONE place in a format where a still from the owned meme
# library may go. `at` says which end of the shot's span it takes; nothing
# else is authored, because what fits is the picker's job and how long it
# holds is the compositor's. See `MemeSpec`.
MEME_KEYS = frozenset({"at", "notes"})
MEME_AT = ("start", "end")
REPEAT_KEYS = frozenset({"concept", "src", "max", "bind", "arrange",
                         "stagger_s", "lit", "connector", "within",
                         "focus", "anchor"})


def _reject_unknown(obj: dict, allowed: frozenset, where: str) -> None:
    extra = sorted(set(obj) - allowed)
    if extra:
        raise TemplateError(
            f"{where}: unknown key(s) {extra}. A template key the engine does "
            f"not read is a silent no-op, so it is refused here. Known keys: "
            f"{sorted(allowed)}")


@dataclass(frozen=True)
class TextSpec:
    """Type drawn by code, sized as a fraction of FRAME height.

    Sizing in frame fractions rather than points is what makes one template
    work at any delivery resolution, and it is what makes the "nothing below
    3.5% of frame height" invariant checkable rather than aspirational.
    """

    src: str
    size_fh: float
    align: str = "center"          # top | center | bottom, or a slot name
    halign: str = "center"         # left | center | right
    max_lines: int = 3
    draw_on_s: float = 0.0         # type draws on over this many seconds
    color: str = "ink"             # a palette key
    slot: str | None = None        # place inside this plate slot
    name: str = ""

    def __post_init__(self) -> None:
        if self.size_fh < MIN_TYPE_FH:
            raise TemplateError(
                f"text {self.name or self.src!r} is {self.size_fh:.3%} of "
                f"frame height; nothing renders below {MIN_TYPE_FH:.1%}")


@dataclass(frozen=True)
class MarkSpec:
    """A hand-drawn mark: a scribble ring, an underline, a strike.

    `target` names what it lands on. A ring goes round the thing itself — the
    extreme candle, the row — never round a label describing it. `after_s` is
    how long after the shot opens it lands: a mark is drawn on something the
    viewer has already found.
    """

    kind: str
    target: str
    name: str = ""
    after_s: float = 0.6


@dataclass(frozen=True)
class RepeatSpec:
    """One shot that places a LIST rather than a single plate.

    Every other shot in every format names one plate and fills its slots.
    MACRO's "who it hits" is four to five consequence cards in one beat, and
    the SHORT's four numbers shots are the same idea written out longhand.
    So this is a general capability, not a macro affordance: N instances of
    one concept, arranged, each entering on its own beat.

    The stagger is load-bearing. Cards arriving one at a time is something
    provably entering, which is what lets a seven-second beat clear the hold
    ceiling honestly rather than by exemption.
    """

    src: str
    concept: str | None = None     # spatial only; a sequence reuses the plate
    max: int = 5
    bind: dict[str, str] = field(default_factory=dict)
    # grid | row | column place N cards in ONE shot.
    # sequence expands the shot into N shots in TIME, one per item — which is
    # what the SHORT's numbers beats are: one sheet, the lit row advancing.
    arrange: str = "grid"
    stagger_s: float = 0.5
    lit: str | None = None         # sequence only: which slot each step lights
    # A mark drawn in the GAP between consecutive cards. The arrows are what
    # make a chain read as a chain rather than as unrelated notes.
    connector: str | None = None
    # Arrange inside this slot of the shot's own plate rather than across the
    # bare frame. Cards on the desk are in the room; cards centred on paper
    # are nowhere.
    within: str | None = None
    # Set by expansion, never authored: which single item of the list this
    # expanded shot places. A sequence of CARDS is one card per beat, full
    # size — three in a column measure 33px type, under the readability
    # floor, so a chain of three at 9:16 has to be told over time.
    only: int | None = None
    # Which slot each step moves in on. Four steps that differ only by which
    # row carries a box are one shot with extra runtime — the composition has
    # to change, not just the highlight.
    focus: str | None = None
    # WHAT EACH STEP AFTER THE FIRST LISTENS FOR, with `$n` the step. The
    # first step keeps the shot's own anchor, so a `[BEAT: numbers]` marker
    # still finds it; step two of `numbers.$n-1` listens for `numbers.1`, the
    # second row's own words, and a card lands as its row is read.
    anchor: str | None = None

    @property
    def spatial(self) -> bool:
        return self.arrange in ("grid", "row", "column")


@dataclass(frozen=True)
class Variant:
    """One way to draw a beat: a plate, and what goes in ITS slots.

    A shot names one plate and every short of that format shows that drawing.
    The kit holds alternatives for most beats — three hook treatments, three
    headline bands, a big number with a detail line and one without — and
    until this existed none of them could be reached from a SHORT, because the
    vertical formats are fixed shot lists and `parser_short` ignores the inline
    tags a director would use in a LONG.

    So the alternatives live HERE, in the template, next to the beat they draw.
    The writer still chooses nothing; code picks, rotating off what the last
    few videos used. Which is the point: shorts are mass-produced, so the
    variety has to come from the code rather than from a person.

    `bind`, `lit` and `focus` fall back to the shot's own when the alternate
    names its slots the same way, and replace them wholesale when it does not.
    They are never merged: a half-inherited bind map names slots from the plate
    it was written for, and those are exactly the names the alternate lacks.
    """

    plate: str
    bind: dict[str, str] | None = None
    lit: str | None = None
    focus: str | None = None
    notes: str = ""
    # A drawing only THIS video's own figures can fill (the implied growth off
    # the workbook, the print against the street) is taken whenever it can
    # be, ahead of the rotation: it is the beat's substance, not one more
    # layout for it. The authored plate stays the fallback.
    prefer: bool = False

    def resolved(self, shot: "Shot") -> tuple[dict[str, str], str | None,
                                              str | None]:
        """What this variant ACTUALLY composes with: `(bind, lit, focus)`.

        One place, because two callers need the same answer and disagreeing
        about it is the whole bug class: the compositor swaps the shot over to
        this variant, and the chooser has to have checked the plate against the
        same three things it will then be asked to draw.
        """
        if self.bind is not None:
            return dict(self.bind), self.lit, self.focus
        return (dict(shot.bind),
                self.lit if self.lit else shot.lit,
                self.focus if self.focus else shot.focus)


@dataclass(frozen=True)
class MemeSpec:
    """The one place in a format where a meme may go, and which end of it.

    A SHORT gets at most one meme: a still from Valentin's own library, held
    for about a second at the turn or the verdict, and none at all when
    nothing in the library fits the story. The template says WHERE, because
    where is a property of the format — which beat can take a joke without
    losing its sentence. It says nothing about WHICH meme or HOW LONG. The
    picker (`memes.choose_for_short`) reads the script for the first, and the
    compositor (`compose._meme_layers`) fixes the second inside the shot's
    audio span, so a template that authors a meme place still fixes no
    durations.

    `at` is `"start"` or `"end"`: the meme OVERLAYS that end of the shot's
    span and never inserts time. A cut that pushed the next shot later would
    move it off the words it is bound to, and the audio clock is the one
    thing a template does not get to override.

    A template without the key renders exactly as it did; the meme is an
    addition to a beat, never a beat of its own.
    """

    at: str = "end"
    notes: str = ""


@dataclass(frozen=True)
class HostSpec:
    """The host, as a concept name plus the plate slot they stand in."""

    pose: str
    slot: str = "figure"
    name: str = "host"


@dataclass(frozen=True)
class Shot:
    id: str
    # `None` is a real value: the shot is bare ground and whatever code draws
    # on it. THE TURN is one sentence on paper and nothing else — it is
    # allowed to be empty, and that is its job.
    plate: str | None
    bind: dict[str, str] = field(default_factory=dict)
    text: tuple[TextSpec, ...] = ()
    marks: tuple[MarkSpec, ...] = ()
    host: HostSpec | None = None
    repeat: RepeatSpec | None = None
    enter: str | None = None
    # Which bound slot is LIT. Every row of the sheet is visible in every
    # numbers shot — one carries the figures being talked about and the rest
    # are ghosted back, so the eye lands without the sheet redrawing.
    lit: str | None = None
    anchor: str | None = None
    # Fills enter in declaration order, this many seconds apart. A chain of
    # three that appears all at once is not a chain, and on a sparse plate —
    # a number, three boxes and two arrows — the boil moves too little ink to
    # read as motion at all. Something entering is what the ceiling rule
    # actually asks for.
    stagger_s: float = 0.0
    # Move in on this slot of the plate, so it fills the frame rather than
    # sitting in a wide shot with a box round it.
    focus: str | None = None
    max_hold_s: float = 8.0
    captions: bool = True
    notes: str = ""
    # Other plates that can carry this beat. Empty is the old behaviour: one
    # plate, every time.
    alts: tuple[Variant, ...] = ()
    # Where this format's one meme may go, if it has one. `None` everywhere
    # but one shot at most.
    meme: MemeSpec | None = None
    # SET BY `resolve_spans`, NEVER AUTHORED. A beat that runs past its ceiling
    # is cut in two: part 1 is the drawing wide, part 2 moves in on one slot of
    # the SAME drawing. `part_of` names the shot part 2 was cut from, so the
    # compositor draws it on the plate part 1 picked instead of rolling the
    # rotation again and cutting to a different picture of the same beat.
    part: int = 0
    part_of: str = ""

    @property
    def variants(self) -> tuple[Variant, ...]:
        """Every way to draw this beat, the authored plate FIRST.

        First is load-bearing twice over. It is the fallback when nothing else
        resolves in this kit, and it is the one whose failure to resolve is
        still an error — an alternate a kit does not carry is dropped quietly,
        because a drop is how a kit swap is supposed to degrade.
        """
        if not self.plate:
            return ()
        mine = Variant(plate=self.plate, bind=dict(self.bind), lit=self.lit,
                       focus=self.focus)
        return (mine, *self.alts)

    @property
    def has_large_type(self) -> bool:
        """Large type and the caption band are mutually exclusive."""
        return any(t.size_fh >= LARGE_TYPE_FH for t in self.text)


# At or above this fraction of frame height, type is the subject of the shot
# and a caption band underneath it is two things competing to be read.
LARGE_TYPE_FH = 0.065


@dataclass(frozen=True)
class ShotOrder:
    """A named sequence the format's shots may be cut in."""

    name: str
    shots: tuple[str, ...]
    notes: str = ""


@dataclass(frozen=True)
class Format:
    name: str
    aspect: str
    frame: tuple[int, int]
    shots: tuple[Shot, ...]
    source: Path | None = None
    # Alternate cut orders. The authored sequence is always available under
    # AS_AUTHORED and is never listed here.
    orders: tuple[ShotOrder, ...] = ()
    # Whether the room advances across the runtime — light, clutter, the
    # wall, the clock. Declared by the template, because it is a property of
    # the format and not of the frame: a future 16:9 format that is ninety
    # seconds long has nowhere to travel, and guessing from the aspect ratio
    # would switch four devices on for it in silence.
    # THE ROWS A PHONE SHOWS CLEAR, `(top, bottom)` in frame pixels, or None.
    # A short's words stay inside it (item 27): YouTube lays its title,
    # channel name and buttons over the bottom of a Short and its search bar
    # over the top, so a footnote at 1,740 px is a footnote nobody sees.
    safe: tuple[int, int] | None = None

    def __len__(self) -> int:
        return len(self.shots)

    def __iter__(self):
        return iter(self.shots)

    def shot(self, shot_id: str) -> Shot:
        for s in self.shots:
            if s.id == shot_id:
                return s
        raise TemplateError(f"{self.name} has no shot {shot_id!r}")


def _text_specs(raw: Any, where: str) -> tuple[TextSpec, ...]:
    out = []
    for i, t in enumerate(raw or ()):
        if not isinstance(t, dict):
            raise TemplateError(f"{where}: text #{i} is not an object")
        _reject_unknown(t, TEXT_KEYS, f"{where} text #{i}")
        try:
            out.append(TextSpec(
                src=t["src"], size_fh=float(t["size_fh"]),
                align=t.get("align", "center"),
                halign=t.get("halign", "center"),
                max_lines=int(t.get("max_lines", 3)),
                draw_on_s=float(t.get("draw_on_s", 0.0)),
                color=t.get("color", "ink"), slot=t.get("slot"),
                name=t.get("name", t.get("src", f"text{i}"))))
        except KeyError as exc:
            raise TemplateError(f"{where}: text #{i} missing {exc}") from exc
    return tuple(out)


def _meme_spec(raw: Any, where: str, *, repeat: Any) -> MemeSpec | None:
    """`"meme": "end"` or `"meme": {"at": "end", "notes": ...}`, checked."""
    if raw is None or raw is False:
        return None
    if isinstance(raw, str):
        raw = {"at": raw}
    if not isinstance(raw, dict):
        raise TemplateError(f"{where}: meme is not \"start\", \"end\" or an "
                            f"object")
    _reject_unknown(raw, MEME_KEYS, f"{where} meme")
    at = raw.get("at")
    if at not in MEME_AT:
        raise TemplateError(
            f"{where} meme: \"at\" is {at!r}; it must be one of {MEME_AT}. "
            f"The meme overlays one end of the shot's span, so it has to be "
            f"told which.")
    if repeat:
        # A sequence repeat copies the shot once per item, and every copy
        # would carry the place: four memes where the format allows one. A
        # spatial repeat is cards entering on a stagger, and a still over
        # them hides the cards the stagger exists to show arriving.
        raise TemplateError(
            f"{where}: a shot with a repeat cannot carry the meme place")
    return MemeSpec(at=at, notes=str(raw.get("notes", "")))


def parse_format(raw: dict, source: Path | None = None) -> Format:
    _reject_unknown(raw, FORMAT_KEYS, "template")
    try:
        name = raw["format"]
        frame = (int(raw["frame"]["w"]), int(raw["frame"]["h"]))
        shots_raw = raw["shots"]
    except KeyError as exc:
        raise TemplateError(f"template missing {exc}") from exc
    if not shots_raw:
        raise TemplateError(f"{name}: a format with no shots")

    shots = []
    seen: set[str] = set()
    for i, s in enumerate(shots_raw):
        where = f"{name} shot #{i} ({s.get('id', 'unnamed')})"
        _reject_unknown(s, SHOT_KEYS, where)
        try:
            sid = s["id"]
            # Present-but-null is a bare-ground shot; absent is an authoring
            # slip, and the two must not be confused.
            plate = s["plate"]
        except KeyError as exc:
            raise TemplateError(
                f"{where} missing {exc} (use \"plate\": null for a shot that "
                f"is deliberately bare)") from exc
        if sid in seen:
            raise TemplateError(f"{name}: two shots share the id {sid!r}")
        seen.add(sid)

        host_raw = s.get("host")
        host = None
        if host_raw:
            if isinstance(host_raw, str):
                host = HostSpec(pose=host_raw)
            else:
                host = HostSpec(pose=host_raw["pose"],
                                slot=host_raw.get("slot", "figure"))
        for j, m in enumerate(s.get("marks") or ()):
            _reject_unknown(m, MARK_KEYS, f"{where} mark #{j}")
        marks = tuple(MarkSpec(kind=m["kind"], target=m["target"],
                               name=m.get("name", m["kind"]),
                               after_s=float(m.get("after_s", 0.6)))
                      for m in (s.get("marks") or ()))

        rep_raw = s.get("repeat")
        repeat = None
        if rep_raw:
            _reject_unknown(rep_raw, REPEAT_KEYS, f"{where} repeat")
            try:
                repeat = RepeatSpec(
                    src=rep_raw["src"], concept=rep_raw.get("concept"),
                    max=int(rep_raw.get("max", 5)),
                    bind=dict(rep_raw.get("bind") or {}),
                    arrange=rep_raw.get("arrange", "grid"),
                    stagger_s=float(rep_raw.get("stagger_s", 0.5)),
                    lit=rep_raw.get("lit"),
                    connector=rep_raw.get("connector"),
                    within=rep_raw.get("within"),
                    focus=rep_raw.get("focus"),
                    anchor=rep_raw.get("anchor"))
            except KeyError as exc:
                raise TemplateError(f"{where} repeat missing {exc}") from exc
            if repeat.spatial and not repeat.concept:
                raise TemplateError(
                    f"{where} repeat: a {repeat.arrange} repeat places cards "
                    f"and needs a concept")
            if not repeat.spatial and repeat.arrange != "sequence":
                raise TemplateError(
                    f"{where} repeat: unknown arrange {repeat.arrange!r}")
        alts: list[Variant] = []
        for j, a in enumerate(s.get("alts") or ()):
            if isinstance(a, str):
                a = {"plate": a}
            if not isinstance(a, dict):
                raise TemplateError(f"{where}: alt #{j} is not a plate name "
                                    f"or an object")
            _reject_unknown(a, ALT_KEYS, f"{where} alt #{j}")
            try:
                alt_plate = a["plate"]
            except KeyError as exc:
                raise TemplateError(f"{where} alt #{j} missing {exc}") from exc
            if not plate:
                raise TemplateError(
                    f"{where}: names alternates but no plate of its own. The "
                    f"authored plate is the fallback every alternate is "
                    f"measured against, so a bare-ground shot cannot have any.")
            alts.append(Variant(
                plate=alt_plate,
                bind=dict(a["bind"]) if a.get("bind") is not None else None,
                lit=a.get("lit"), focus=a.get("focus"),
                notes=a.get("notes", ""), prefer=bool(a.get("prefer", False))))
        alt_keys = [v.plate for v in alts]
        if len(set(alt_keys)) != len(alt_keys) or plate in alt_keys:
            raise TemplateError(
                f"{where}: an alternate repeats a plate this shot already "
                f"names ({sorted(alt_keys)}). A duplicate is weight on the "
                f"rotation, not another picture.")
        meme = _meme_spec(s.get("meme"), where, repeat=rep_raw)

        shots.append(Shot(
            id=sid, plate=plate, alts=tuple(alts),
            bind=dict(s.get("bind") or {}),
            text=_text_specs(s.get("text"), where),
            marks=marks, host=host, repeat=repeat,
            enter=s.get("enter"), lit=s.get("lit"),
            anchor=s.get("anchor"), stagger_s=float(s.get("stagger_s", 0.0)),
            focus=s.get("focus"),
            max_hold_s=float(s.get("max_hold_s", 8.0)),
            captions=bool(s.get("captions", True)),
            notes=s.get("notes", ""), meme=meme))

    # ONE MEME PER VIDEO. Two places would let a short carry two jokes, and
    # the second is the one that makes the channel read as a meme page.
    meme_shots = [sh.id for sh in shots if sh.meme]
    if len(meme_shots) > 1:
        raise TemplateError(
            f"{name}: {len(meme_shots)} shots name a meme place "
            f"({meme_shots}). A format has one place for a meme at most.")

    safe = None
    if raw.get("safe") is not None:
        try:
            safe = (int(raw["safe"]["top"]), int(raw["safe"]["bottom"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise TemplateError(
                f"{name}: `safe` takes {{\"top\": px, \"bottom\": px}}") from exc
        if not 0 <= safe[0] < safe[1] <= frame[1]:
            raise TemplateError(f"{name}: `safe` {safe} is not a band inside "
                                f"the {frame[1]} px frame")
    fmt = Format(name=name, aspect=raw.get("aspect", "9:16"), frame=frame,
                 shots=tuple(shots), source=source,
                 orders=_parse_orders(raw.get("orders"), name, tuple(shots)),
                 safe=safe)

    for sh in fmt.shots:
        if not (sh.plate or sh.text or sh.bind or sh.repeat or sh.host):
            raise TemplateError(
                f"{name}/{sh.id}: names no plate, no text, no binding and no "
                f"repeat — there is nothing for this shot to draw")

    # Large type and the caption band are mutually exclusive. This is checked
    # at parse time so an unrenderable template cannot reach a render at all.
    for s in fmt.shots:
        if s.has_large_type and s.captions:
            raise TemplateError(
                f"{name}/{s.id}: carries type at "
                f"{max(t.size_fh for t in s.text):.1%} of frame height AND the "
                f"caption band. They are mutually exclusive — set "
                f'"captions": false')
    return fmt


# The authored sequence, as a name the rotation can pick and a manifest can
# record. A format never lists it; it is always in play.
AS_AUTHORED = "as-authored"
# The narration's own sequence, when the script marks its beats in an order no
# declared order cuts. Recorded on the manifest like any other name, and read
# back by `apply_order` as the authored sequence — which is right, because the
# markers, not the name, are what put the beats in order.
AS_MARKED = "as-marked"


def voice_keys(shots: Sequence[Shot]) -> tuple[str, ...]:
    """The beats a run of shots listens for, by anchor key, in order.

    A shot with an `anchor` starts where its own words are spoken, so this is
    the order the NARRATION has to put the beats in for the picture to be on
    the right sentence. Two shots listening for the same words are one beat to
    the voice — the SHORT's sheet and comment both start on the numbers
    comment — so a run of them counts once, and swapping them inside the run
    changes nothing the voice can hear.
    """
    out: list[str] = []
    for sh in shots:
        if sh.anchor and (not out or out[-1] != sh.anchor):
            out.append(sh.anchor)
    return tuple(out)


def beat_keys(fmt: Format) -> tuple[str, ...]:
    """The beats a writer may mark in this format — `[BEAT: key]` — in order.

    They are the anchor keys, because a marker is the writer saying where the
    words a shot listens for begin. A key two shots share is one marker.
    """
    out: list[str] = []
    for sh in fmt.shots:
        if sh.anchor and sh.anchor not in out:
            out.append(sh.anchor)
    return tuple(out)


def marker_formats(root: Path | str = ".") -> dict[str, tuple[str, ...]]:
    """Every format a SHORT renders through, with the beats it can mark."""
    return {name: beat_keys(load_format(name, root))
            for name in available_formats(root)}


def _parse_orders(raw: Any, fmt_name: str,
                  shots: tuple[Shot, ...]) -> tuple[ShotOrder, ...]:
    """The format's declared alternate cut orders, checked.

    AN ORDER MAY MOVE A BEAT THE NARRATION PINS, and until the markers it could
    not. A pinned shot starts where its own words are spoken, and the words
    were one take written to the authored beat order, so a picture moved ahead
    of its sentence talked over the wrong one — `resolve_spans` dropped its
    anchor for landing before one already fixed, and it interpolated to
    somewhere that matched nothing. Now the writing prompt names the order
    before a word is written and the script marks where each beat starts, so a
    narration can be in any declared order. `choose_order` keeps an order that
    moves a pinned beat away from any script whose narration does not say it
    is in that order, and an unmarked script never is.

    What stays refused is what no script could be written to match: an order
    that drops or repeats a shot, one that opens on anything but the hook, and
    one that parts two shots listening for the same words.
    """
    ids = [sh.id for sh in shots]
    by_id = {sh.id: sh for sh in shots}
    out: list[ShotOrder] = []
    seen: set[str] = set()
    for i, o in enumerate(raw or ()):
        where = f"{fmt_name} order #{i}"
        if not isinstance(o, dict):
            raise TemplateError(f"{where} is not an object")
        _reject_unknown(o, ORDER_KEYS, where)
        try:
            oname, oshots = o["name"], list(o["shots"])
        except KeyError as exc:
            raise TemplateError(f"{where} missing {exc}") from exc
        where = f"{fmt_name} order {oname!r}"
        if oname == AS_AUTHORED:
            raise TemplateError(
                f"{where}: {AS_AUTHORED!r} is the authored sequence and is "
                f"always in the rotation — it is never listed.")
        if oname in seen:
            raise TemplateError(f"{fmt_name}: two orders named {oname!r}")
        seen.add(oname)
        if sorted(oshots) != sorted(ids):
            missing = sorted(set(ids) - set(oshots))
            extra = sorted(set(oshots) - set(ids))
            raise TemplateError(
                f"{where}: an order is a resequencing of the WHOLE format, so "
                f"it names every shot exactly once. Missing {missing}, "
                f"unknown {extra}. Dropping a beat here would drop it "
                f"silently — prune it from the script instead.")
        # ONE BEAT IS ONE RUN OF SHOTS. Two shots listening for the same words
        # start on the same sentence; an order that puts another beat between
        # them asks the voice to say that sentence twice, and no script can be
        # marked to match it — the order would parse and never be cut.
        heard = voice_keys([by_id[s] for s in oshots])
        parted = sorted({k for k in heard if heard.count(k) > 1})
        if parted:
            raise TemplateError(
                f"{where}: puts another beat between the shots that listen "
                f"for {parted}. They start on the same words, so the voice "
                f"hears them as one beat, and a narration cannot reach one "
                f"beat twice.")
        # The opening is the one position an unpinned shot cannot take.
        # `resolve_spans` puts whatever is first at 0.0 and drops the hook's
        # anchor for landing on top of it, so an unanchored shot moved ahead
        # of the hook holds an even share of the opening while the hook is
        # spoken over it. `sign-off-first` did exactly that: the closing card
        # for the first 4.5-7 s of every other earnings and macro short.
        if oshots[0] != ids[0]:
            raise TemplateError(
                f"{where}: opens on {oshots[0]!r}. The cut opens on "
                f"{ids[0]!r}, the shot the first words are spoken over, and "
                f"nothing may go ahead of it: a shot placed first holds the "
                f"opening seconds while the hook is spoken over it.")
        out.append(ShotOrder(name=oname, shots=tuple(oshots),
                             notes=o.get("notes", "")))
    return tuple(out)


def order_names(fmt: Format) -> tuple[str, ...]:
    """Every cut order this format can be shot in, the authored one first."""
    return (AS_AUTHORED, *(o.name for o in fmt.orders))


def apply_order(fmt: Format, name: str) -> Format:
    """`fmt` resequenced. An unknown name is the authored order, not an error.

    Forgiving on purpose: the order is recorded on a manifest and read back
    later, and a template that has since dropped an order must not make an old
    workspace unrenderable.
    """
    from dataclasses import replace

    if not name or name == AS_AUTHORED:
        return fmt
    for o in fmt.orders:
        if o.name == name:
            by_id = {sh.id: sh for sh in fmt.shots}
            return replace(fmt, shots=tuple(by_id[i] for i in o.shots))
    return fmt


def choose_order(fmt: Format, seed: str = "",
                 avoid: "Collection[str]" = (), *,
                 heard: Sequence[str] | None = None) -> str:
    """Which cut order this video gets, rotating off the recent ones.

    The same preference the plates use: drop what the last few videos were cut
    in unless that leaves nothing, then let the seed decide. A format that
    declares no orders always answers with the authored one.

    `heard` is the order the NARRATION puts the beats in, by anchor key, and
    it narrows the rotation to the orders that cut those beats in that
    sequence. `None` is the writing prompt, choosing before a word exists:
    every declared order is open, because the writer is about to be told
    which one to follow. A render passes what it heard — the marked beats, or
    for an unmarked script the authored beats, which leaves exactly the orders
    the rotation offered before orders could move a pinned beat, so an
    unmarked script picks what it always picked.

    When the markers put the beats in an order nothing declares, the answer
    is `AS_MARKED`: the markers order the cut and there is no name to rotate.
    """
    import random

    names = list(order_names(fmt))
    if heard is not None:
        want = tuple(heard)
        keys = set(want)
        names = [n for n in names
                 if tuple(k for k in voice_keys(apply_order(fmt, n).shots)
                          if k in keys) == want]
        if not names:
            return AS_MARKED
    options = _prefer_unused_names(names, avoid)
    return random.Random(f"order|{fmt.name}|{seed}").choice(options)


def order_by_marks(fmt: Format, heard: Sequence[str]) -> Format:
    """`fmt` resequenced to where the narration's markers put its beats.

    Each shot whose beat is marked starts a block. A shot with no anchor, or
    one whose beat the writer left unmarked, rides in the block before it: the
    sign-off stays behind the payoff wherever the payoff goes, which is the
    only place a shot listening for nothing can be put and still be on the
    right sentence. Blocks sort by where their marker falls, stably, so two
    shots on the same words keep the order the template or the chosen order
    gave them.

    The opening shot's block never moves. The first words are spoken over it,
    and a cut that opens on anything else holds that picture while the hook
    is heard over it.
    """
    from dataclasses import replace

    rank = {k: i for i, k in enumerate(heard)}
    blocks: list[tuple[int, list[Shot]]] = []
    for n, sh in enumerate(fmt.shots):
        if n == 0:
            blocks.append((-1, [sh]))
        elif sh.anchor in rank:
            blocks.append((rank[sh.anchor], [sh]))
        else:
            blocks[-1][1].append(sh)
    blocks.sort(key=lambda b: b[0])
    return replace(fmt, shots=tuple(sh for _r, b in blocks for sh in b))


def _prefer_unused_names(options: list[str],
                         avoid: "Collection[str]") -> list[str]:
    """`plates._prefer_unused`, for names that are not plate keys.

    Same rule, same reason it is a preference: a rotation that could fail a
    render for want of a fresh sequence would be a worse bug than the sameness
    it prevents.
    """
    if not avoid:
        return options
    return [k for k in options if k not in avoid] or options


def load_format(name: str, root: Path | str = ".") -> Format:
    path = Path(root) / TEMPLATE_DIR / f"{name}.json"
    if not path.exists():
        raise TemplateError(
            f"no shot template at {path}. A format is a JSON file; adding one "
            f"is authoring a file, not writing code.")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TemplateError(f"{path} is not valid JSON: {exc}") from exc
    return parse_format(raw, source=path)


def _sub(value: str | None, n: int) -> str | None:
    """`$n` is the 1-based step of a sequence repeat; `$n+1` and `$n-1` shift it.

    The offset forms exist because the step number and the thing it names are
    rarely the same number. A sheet's first band may be the year header, so
    metric N lives in row N+1; a script's list is indexed from zero, so step
    one places `consequences.0`. Longest token first, or `$n+1` is read as
    `$n` followed by a stray `+1`.
    """
    if value is None:
        return None
    return (value.replace("$n+1", str(n + 1))
                 .replace("$n-1", str(n - 1))
                 .replace("$n", str(n)))


def expand_sequences(fmt: Format, items_for) -> Format:
    """Expand every `arrange: "sequence"` shot into one shot per item.

    The SHORT's numbers beats are one sheet with the lit row advancing, and
    they were four near-identical shot definitions differing only in which row
    they lit. That is the same repeat MACRO uses to place a list of cards —
    over TIME instead of over the frame — so it is the same declaration, and
    two ways to express one thing is how templates drift apart.

    `items_for(src)` supplies the list; the number of steps is what the SCRIPT
    carries, capped by the template's `max`. Four metrics make four shots,
    two make two, and neither case is authored twice.
    """
    out: list[Shot] = []
    from dataclasses import replace
    for shot in fmt.shots:
        rep = shot.repeat
        if rep is None or rep.spatial:
            out.append(shot)
            continue
        items = list(items_for(rep.src) or [])[:max(rep.max, 1)]
        if not items:
            # Nothing to step through. The repeat comes OFF — left on, it
            # reaches the compositor as an unexpanded sequence and is taken
            # for a spatial one. The shot keeps its plate; the caller's prune
            # drops it if that leaves nothing.
            out.append(replace(shot, repeat=None))
            continue
        for i in range(1, len(items) + 1):
            # A sequence that names a concept places that card, one per step.
            # A sequence that does not reuses the shot's own plate and only
            # advances which slot is lit.
            step = (replace(rep, arrange="grid", only=i - 1)
                    if rep.concept else None)
            out.append(replace(
                shot,
                id=f"{shot.id}-{i}",
                repeat=step,
                lit=_sub(rep.lit, i),
                focus=_sub(rep.focus, i),
                # THE BINDS STEP TOO. A sequence that reuses the plate and
                # changes nothing but which row is lit is fine on a sheet,
                # where the figures are all already on screen. It is not fine
                # on a card: MACRO's four consequences expanded to four shots
                # of the identical picture and the measurement read 23.8s of
                # one held composition, over an 8s ceiling. `$n` in a bind is
                # which item of the list this step places.
                bind={k: _sub(v, i) or v for k, v in (shot.bind or {}).items()},
                # THE ALTERNATES STEP TOO. A sequence shot that carries them
                # placed item `$n` on the authored plate and a literal "$n" on
                # every other one, so the beat read correctly until the
                # rotation picked a different drawing for it.
                alts=tuple(replace(
                    v,
                    bind=({k: _sub(b, i) or b for k, b in v.bind.items()}
                          if v.bind is not None else None),
                    lit=_sub(v.lit, i), focus=_sub(v.focus, i))
                    for v in shot.alts),
                anchor=(shot.anchor if i == 1
                        else _sub(rep.anchor, i) if rep.anchor else None),
                # A wipe marks the change of subject INTO the sequence, not
                # each step of it.
                enter=shot.enter if i == 1 else None,
                marks=tuple(replace(m, target=_sub(m.target, i),
                                    name=_sub(m.name, i) or m.kind)
                            for m in shot.marks),
            ))
    return replace(fmt, shots=tuple(out))


# The `chart.*` fields the writer's move summary fills (`ShortResolver`). Every
# other `chart.*` field is drawn from the price series.
_MOVE_FIELDS = frozenset({"move", "move_rest", "move_up", "move_down",
                          "move_detail"})


def draws_prices(fmt: Format) -> bool:
    """Whether any beat of this format can put the price series on screen.

    The plain short's move beat is a price line; `earnings` and `macro` show
    the move as the writer's figure and draw no prices at all, so a dead
    price feed is nothing to them.
    """
    for shot in fmt.shots:
        binds = [v.bind or {} for v in shot.variants]
        if shot.repeat is not None:
            binds.append(shot.repeat.bind)
        srcs = [str(s) for b in binds for s in b.values()]
        srcs += [t.src for t in shot.text]
        for src in srcs:
            head, _, name = src.lstrip("?").partition(".")
            if head == "chart" and name not in _MOVE_FIELDS:
                return True
    return False


def available_formats(root: Path | str = ".") -> list[str]:
    d = Path(root) / TEMPLATE_DIR
    return sorted(p.stem for p in d.glob("*.json")) if d.is_dir() else []


# ---------------------------------------------------------------------------
# Spans: the audio clock decides duration.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Span:
    shot: Shot
    start: float
    end: float
    anchored: bool = False

    @property
    def dur(self) -> float:
        return self.end - self.start




def resolve_spans(fmt: Format, words: Sequence[Any], duration: float,
                  anchors: dict[str, str] | None = None, *,
                  ordered: bool = False,
                  punch_in: "Callable[[Shot], str | None] | None" = None,
                  host_lines: dict[str, str] | None = None,
                  ) -> list[Span]:
    """Give every shot a start and an end, off the spoken audio.

    A shot whose `anchor` names text that can be found in the narration starts
    where that text is spoken. Every other shot shares the time between its
    anchored neighbours. The result is monotonic and covers the full duration
    exactly once — no shot may start before the one before it ends, because
    two compositions at the same instant is not a thing the format can
    express.

    `anchors` maps a shot's anchor key to the literal words to look for; the
    caller builds it from the script, because this module knows about shots
    and not about tickers.

    `ordered` looks for each shot's words only AFTER the words of the shot
    before it. A marked script asks for it: its anchors are the words spoken
    right after each marker, and a phrase that also turns up earlier — the
    first words of the payoff said once in the hook — must not pin the payoff
    to the hook. An unmarked script searches the whole narration, as it
    always did.

    `punch_in(shot)` names the slot a beat that runs long can move in on; see
    `_split_long_beats`. Without it a long beat holds.

    `host_lines` maps a host shot's anchor to the line he says on camera
    (`{"turn": script.turn_line}`). His shot then ends when that line does,
    and the shots after him take the rest of the stretch; see
    `_host_says_his_line`. Without it he holds the whole stretch, as before.
    """
    from pipeline.timeline import clamp, find_anchor_time

    anchors = anchors or {}
    words = list(words)
    shots = fmt.shots
    n = len(shots)
    if ordered:
        at = _ordered_anchor_times(shots, words, duration, anchors)
    else:
        at = [None] * n
        for i, s in enumerate(shots):
            if not s.anchor:
                continue
            phrase = anchors.get(s.anchor)
            if not phrase:
                continue
            tokens = str(phrase).split()
            if len(tokens) < 2:
                continue
            t = find_anchor_time(words, " ".join(tokens[:4]))
            if t is not None:
                at[i] = clamp(t, duration)

    # The cut opens on the first shot. This is fixed before anything else and
    # is never revisited: an opening the audio clock pushes later leaves the
    # video starting on blank paper, which is what happened the first time.
    at[0] = 0.0
    # Monotonic: an anchor that lands before one already fixed is not usable.
    last = 0.0
    for i in range(1, n):
        if at[i] is None:
            continue
        if at[i] < last + MIN_SHOT_S:
            at[i] = None
        else:
            last = at[i]

    starts = _share_runs(shots, at, duration)

    spans: list[Span] = []
    for i, s in enumerate(shots):
        start = starts[i]
        end = starts[i + 1] if i + 1 < n else duration
        if end - start < MIN_SHOT_S:
            end = min(start + MIN_SHOT_S, duration)
        spans.append(Span(shot=s, start=start, end=end,
                          anchored=at[i] is not None))

    # Repair any overlap the minimum introduced, then pin the tail to the
    # audio: a shot that outlives the narration is a frame with no reason to
    # be there.
    for i in range(len(spans) - 1):
        if spans[i].end > spans[i + 1].start:
            spans[i] = Span(spans[i].shot, spans[i].start,
                            spans[i + 1].start, spans[i].anchored)
    if spans:
        spans[-1] = Span(spans[-1].shot,
                         min(spans[-1].start, duration - MIN_SHOT_S),
                         duration, spans[-1].anchored)

    # max_hold_s is a CEILING ON THE SPAN, for every shot — and it is no
    # longer met by starting the next shot early.
    #
    # It used to be. A span over its ceiling was ended at the ceiling and the
    # next shot began there, so the next picture went up while the voice was
    # still on the last beat: the payoff figure over the valuation sentence,
    # the sheet over the headline. Then the slack that left at the end was
    # spread over the host shots, which moved every start after them later —
    # anchored ones included. Both are gone. A start the words fix stays where
    # the words are; a run of shots shares its own time (`_share_runs`); and
    # a beat that is still too long becomes two pictures of one drawing
    # (`_split_long_beats`) or, where it has nothing to move in on, holds —
    # which `held_over_ceiling` measures on the frames and reports.
    if host_lines:
        spans = _host_says_his_line(spans, words, host_lines)
    if punch_in is not None:
        spans = _split_long_beats(spans, words, punch_in)
    return spans


# How long he stays on after the last word of his line, and the least he is
# ever on for. A cut on the last syllable reads as a mistake; a close-up under
# two and a half seconds reads as a flash.
HOST_TAIL_S = 0.6
HOST_MIN_S = 2.5


def _host_says_his_line(spans: list[Span], words: Sequence[Any],
                        host_lines: dict[str, str]) -> list[Span]:
    """He is on camera for his line, and the evidence takes what follows.

    THE TURN WAS 15.9 SECONDS OF ONE CLOSE-UP (item 28). His shot starts on
    the turn line and the next picture waited for the next anchored words, so
    every figure he read after the turn was read over his face, and the
    run's slack went to him on purpose (`_run_shares`). The line is one
    sentence and takes four or five seconds to say. So his shot ends a beat
    after its last word, and the unanchored shots after him share the time
    up to the next anchored start: the cards the figures are on come up as
    he reads them.

    Nothing anchored moves. When the shot after him starts on its own words,
    there is nothing to hand the time to, and he keeps it.
    """
    from pipeline.timeline import _norm

    out = list(spans)
    for i, sp in enumerate(out):
        sh = sp.shot
        line = host_lines.get(sh.anchor or "") if sh.host else None
        if not line or not sp.anchored:
            continue
        n = sum(1 for tok in str(line).split() if _norm(tok))
        spoken = [w for w in words
                  if float(getattr(w, "start", 0.0)) >= sp.start - 0.05
                  and _norm(str(getattr(w, "word", "")))]
        if n == 0 or len(spoken) < n:
            continue
        last = spoken[n - 1]
        end = float(getattr(last, "end", getattr(last, "start", 0.0))) + HOST_TAIL_S
        end = max(end, sp.start + HOST_MIN_S)
        run = []
        for j in range(i + 1, len(out)):
            if out[j].anchored:
                break
            run.append(j)
        if not run or end >= sp.end - MIN_SHOT_S:
            continue
        stop = out[run[-1]].end
        share = (stop - end) / len(run)
        if share < MIN_SHOT_S:
            continue
        out[i] = Span(sh, sp.start, end, sp.anchored)
        t = end
        for k in run:
            out[k] = Span(out[k].shot, t, t + share, out[k].anchored)
            t += share
        out[run[-1]] = Span(out[run[-1]].shot, out[run[-1]].start, stop,
                            out[run[-1]].anchored)
    return out


def _ordered_anchor_times(shots: Sequence[Shot], words: Sequence[Any],
                          duration: float,
                          anchors: dict[str, str]) -> list[float | None]:
    """Each shot's start, looking only after the words of the shot before it.

    A key two shots share is found once, for the first of them. The second is
    the same beat's second picture; sent looking for the same sentence further
    on, it would find it again only by accident, and pin itself there.
    """
    from pipeline.timeline import _norm, clamp

    # A punctuation-only token — a dash read as a pause — is not a word, and a
    # phrase has to match across it.
    spoken = [(w, _norm(str(getattr(w, "word", "")))) for w in words]
    spoken = [(w, tok) for w, tok in spoken if tok]
    at: list[float | None] = [None] * len(shots)
    found: set[str] = set()
    cursor = 0
    for i, s in enumerate(shots):
        if not s.anchor or s.anchor in found:
            continue
        raw = str(anchors.get(s.anchor) or "").split()
        if len(raw) < 2:
            continue
        want = [_norm(t) for t in raw[:4] if _norm(t)]
        if not want:
            continue
        for p in range(cursor, len(spoken) - len(want) + 1):
            if all(spoken[p + k][1] == want[k] for k in range(len(want))):
                at[i] = clamp(float(spoken[p][0].start), duration)
                found.add(s.anchor)
                cursor = p + 1
                break
    return at


def _share_runs(shots: Sequence[Shot], at: Sequence[float | None],
                duration: float) -> list[float]:
    """Every shot's start: an anchored one where its words are, and the shots
    after it sharing the time up to the next anchored start.

    THE NEXT SHOT STARTS ON ITS OWN WORDS, NEVER EARLY. Nothing below moves an
    anchored start; the only freedom is how a run divides the time it has.
    """
    n = len(shots)
    fixed = [i for i in range(n) if at[i] is not None]
    starts = [0.0] * n
    for k, a in enumerate(fixed):
        b = fixed[k + 1] if k + 1 < len(fixed) else n
        t0 = float(at[a])
        t1 = float(at[b]) if b < n else duration
        run = list(range(a, b))
        t = t0
        for i, share in zip(run, _run_shares([shots[i] for i in run],
                                             max(t1 - t0, 0.0))):
            starts[i] = t
            t += share
    return starts


def _run_shares(run: Sequence[Shot], total: float) -> list[float]:
    """How one stretch of narration divides between the shots cut over it.

    Evenly, unless an even share carries a shot past its ceiling while a shot
    with the HOST in it could take the difference. He is the most alive frame
    in the format — he talks, he blinks, the room boils behind him — so the
    slack goes to him and the evidence keeps to its ceiling. That was the rule
    the old shortfall spread applied across the whole cut, where it moved
    every start after him; inside one run it cannot move an anchored start.
    Host shots are never split, so this is also the only way a host shot
    grows.
    """
    even = total / len(run)
    hosts = sum(1 for sh in run if sh.host)
    if not hosts or all(sh.host or sh.max_hold_s >= even for sh in run):
        return [even] * len(run)
    kept = [0.0 if sh.host else min(sh.max_hold_s, even) for sh in run]
    rest = (total - sum(kept)) / hosts
    return [rest if sh.host else k for sh, k in zip(run, kept)]


def _split_long_beats(spans: list[Span], words: Sequence[Any],
                      punch_in: "Callable[[Shot], str | None]") -> list[Span]:
    """A beat that runs past its ceiling becomes two pictures of one drawing.

    Part 1 is the drawing wide; part 2 moves in on the slot being read —
    `punch_in(shot)` says which, and a shot it names nothing for holds. The
    composition changes, so the frame is no longer one held picture, and
    nothing about the beat's timing moves: part 2 ends where the beat did,
    and the next shot still starts on its own words.

    NEVER A HOST SHOT, A ROOM OR A REPEAT. He is alive at any length and is
    what `_run_shares` gives the slack to; a room is picked per role and its
    second pick would be a different room; a repeat's cards enter on a
    stagger that a cut through the middle would restart.
    """
    from dataclasses import replace

    out: list[Span] = []
    for sp in spans:
        sh = sp.shot
        if (sp.dur <= sh.max_hold_s + 1e-6 or sp.dur < 2 * MIN_SHOT_S
                or sh.part or sh.host or sh.repeat is not None
                or not sh.plate or sh.plate.startswith("room/")):
            out.append(sp)
            continue
        slot = punch_in(sh)
        if not slot:
            out.append(sp)
            continue
        cut = _split_point(sp, words)
        wide = replace(sh, part=1)
        # Part 2 is a cut, not an entrance: whatever part 1 drew on, staggered
        # in or landed is already on screen, so none of it starts again.
        close = replace(
            sh, id=f"{sh.id}-in", part=2, part_of=sh.id, focus=slot,
            anchor=None, enter=None, stagger_s=0.0,
            text=tuple(replace(t, draw_on_s=0.0) for t in sh.text),
            marks=tuple(replace(m, after_s=0.0) for m in sh.marks))
        out.append(Span(wide, sp.start, cut, sp.anchored))
        out.append(Span(close, cut, sp.end, False))
    return out


def _split_point(sp: Span, words: Sequence[Any]) -> float:
    """Where inside a long beat the second picture comes in.

    On a sentence boundary when the words give one near the middle — the cut
    lands as the voice starts a new thought, which is where an editor puts
    it — and at the midpoint when they do not. Never so near either end that
    one part is a flash: each keeps a quarter of the beat.
    """
    margin = max(MIN_SHOT_S, 0.25 * sp.dur)
    lo, hi = sp.start + margin, sp.end - margin
    mid = (sp.start + sp.end) / 2
    best: float | None = None
    for w, nxt in zip(words, list(words)[1:]):
        t = float(getattr(nxt, "start", 0.0))
        if not lo <= t <= hi:
            continue
        said = str(getattr(w, "word", "")).rstrip("\"'”’)")
        if not said.endswith((".", "!", "?", "…")):
            continue
        if best is None or abs(t - mid) < abs(best - mid):
            best = t
    return best if best is not None else mid
