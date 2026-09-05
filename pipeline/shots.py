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
from typing import Any, Sequence

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
FORMAT_KEYS = frozenset({"format", "aspect", "frame", "shots", "chapters",
                         "notes"})
CHAPTER_KEYS = frozenset({"chapter", "shots", "notes"})
CHAPTER_DIR = Path("templates/chapters")
SHOT_KEYS = frozenset({"id", "plate", "bind", "text", "marks", "host", "enter",
                       "lit", "anchor", "max_hold_s", "captions", "notes",
                       "repeat", "stagger_s", "focus",
                       # set by chapter expansion, never authored
                       "_chapter", "_chapter_n"})
TEXT_KEYS = frozenset({"name", "src", "size_fh", "align", "halign",
                       "max_lines", "draw_on_s", "color", "slot"})
MARK_KEYS = frozenset({"kind", "target", "name"})
REPEAT_KEYS = frozenset({"concept", "src", "max", "bind", "arrange",
                         "stagger_s", "lit", "connector", "within",
                         "focus"})


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
    extreme candle, the row — never round a label describing it.
    """

    kind: str
    target: str
    name: str = ""


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

    @property
    def spatial(self) -> bool:
        return self.arrange in ("grid", "row", "column")


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
    chapter: str = ""            # which chapter type this shot came from
    chapter_n: int = 0           # and which chapter of the video
    # Move in on this slot of the plate, so it fills the frame rather than
    # sitting in a wide shot with a box round it.
    focus: str | None = None
    max_hold_s: float = 8.0
    captions: bool = True
    notes: str = ""

    @property
    def has_large_type(self) -> bool:
        """Large type and the caption band are mutually exclusive."""
        return any(t.size_fh >= LARGE_TYPE_FH for t in self.text)


# At or above this fraction of frame height, type is the subject of the shot
# and a caption band underneath it is two things competing to be read.
LARGE_TYPE_FH = 0.065


@dataclass(frozen=True)
class Format:
    name: str
    aspect: str
    frame: tuple[int, int]
    shots: tuple[Shot, ...]
    source: Path | None = None
    # Whether the room advances across the runtime — light, clutter, the
    # wall, the clock. Declared by the template, because it is a property of
    # the format and not of the frame: a future 16:9 format that is ninety
    # seconds long has nowhere to travel, and guessing from the aspect ratio
    # would switch four devices on for it in silence.

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


def _chapter_shots(names: list[str], fmt_name: str,
                   root: Path | str = ".", *,
                   boundary: str | None = None) -> list[dict]:
    """Every chapter's shots, in order, with ids that say where they came from.

    An id like `ch3-the-event-dive-in` is how a manifest, a contact sheet cell
    and an invariant failure all name the same frame — with a chapter used
    twice, bare shot ids would collide silently.

    `boundary` is the transition the format puts at the top of every chapter.
    It is applied HERE, once, rather than authored into nine chapter files:
    the same rule written nine times is the drift that a template engine is
    supposed to remove, and a chapter type does not know it is a chapter of
    a long — the same file has to work wherever it is picked.
    """
    out: list[dict] = []
    for n, cname in enumerate(names, 1):
        path = Path(root) / CHAPTER_DIR / f"{cname}.json"
        if not path.exists():
            raise TemplateError(
                f"{fmt_name}: no chapter type {cname!r} at {path}. A chapter "
                f"type is a JSON file; adding one is authoring a file.")
        try:
            craw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise TemplateError(f"{path} is not valid JSON: {exc}") from exc
        _reject_unknown(craw, CHAPTER_KEYS, f"chapter {cname}")
        for j, sh in enumerate(craw.get("shots") or ()):
            sh = dict(sh)
            sh["id"] = f"ch{n}-{cname}-{sh['id']}"
            sh["_chapter"] = cname
            sh["_chapter_n"] = n
            # The chapter's first shot anchors to the chapter's first
            # sentence, so nine chapters give nine points where the cut is
            # pinned to the audio rather than interpolated.
            if j == 0 and "anchor" not in sh:
                sh["anchor"] = f"ch{n}"
            if j == 0 and boundary and "enter" not in sh:
                sh["enter"] = boundary
            out.append(sh)
    return out


def parse_format(raw: dict, source: Path | None = None,
                 root: Path | str = ".") -> Format:
    _reject_unknown(raw, FORMAT_KEYS, "template")
    try:
        name = raw["format"]
        frame = (int(raw["frame"]["w"]), int(raw["frame"]["h"]))
        # A format lists SHOTS or CHAPTERS. A chapter is a named small shot
        # list of its own, so nine picks become thirty-eight shots and nobody
        # authors them one at a time.
        shots_raw = raw.get("shots")
        if shots_raw is None:
            shots_raw = _chapter_shots(raw["chapters"], name, root,
                                       boundary=raw.get("chapter_enter"))
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
                               name=m.get("name", m["kind"]))
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
                    focus=rep_raw.get("focus"))
            except KeyError as exc:
                raise TemplateError(f"{where} repeat missing {exc}") from exc
            if repeat.spatial and not repeat.concept:
                raise TemplateError(
                    f"{where} repeat: a {repeat.arrange} repeat places cards "
                    f"and needs a concept")
            if not repeat.spatial and repeat.arrange != "sequence":
                raise TemplateError(
                    f"{where} repeat: unknown arrange {repeat.arrange!r}")
        shots.append(Shot(
            id=sid, plate=plate,
            bind=dict(s.get("bind") or {}),
            text=_text_specs(s.get("text"), where),
            marks=marks, host=host, repeat=repeat,
            enter=s.get("enter"), lit=s.get("lit"),
            anchor=s.get("anchor"), stagger_s=float(s.get("stagger_s", 0.0)),
            focus=s.get("focus"),
            chapter=s.get("_chapter", ""), chapter_n=int(s.get("_chapter_n", 0)),
            max_hold_s=float(s.get("max_hold_s", 8.0)),
            captions=bool(s.get("captions", True)),
            notes=s.get("notes", "")))

    fmt = Format(name=name, aspect=raw.get("aspect", "9:16"), frame=frame,
                 shots=tuple(shots), source=source,
                 )

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
    return parse_format(raw, source=path, root=root)


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
                anchor=shot.anchor if i == 1 else None,
                marks=tuple(replace(m, target=_sub(m.target, i),
                                    name=_sub(m.name, i) or m.kind)
                            for m in shot.marks),
            ))
    return replace(fmt, shots=tuple(out))


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
                  anchors: dict[str, str] | None = None) -> list[Span]:
    """Give every shot a start and an end, off the spoken audio.

    A shot whose `anchor` names text that can be found in the narration starts
    where that text is spoken. Every other shot is distributed evenly between
    its anchored neighbours. The result is monotonic and covers the full
    duration exactly once — no shot may start before the one before it ends,
    because two compositions at the same instant is not a thing the format can
    express.

    `anchors` maps a shot's anchor key to the literal words to look for; the
    caller builds it from the script, because this module knows about shots
    and not about tickers.
    """
    from pipeline.timeline import clamp, find_anchor_time

    anchors = anchors or {}
    n = len(fmt.shots)
    at: list[float | None] = [None] * n

    for i, s in enumerate(fmt.shots):
        if not s.anchor:
            continue
        phrase = anchors.get(s.anchor)
        if not phrase:
            continue
        tokens = str(phrase).split()
        if len(tokens) < 2:
            continue
        t = find_anchor_time(list(words), " ".join(tokens[:4]))
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

    # Interpolate the unanchored runs between their fixed neighbours.
    starts: list[float] = [0.0] * n
    i = 0
    while i < n:
        if at[i] is not None:
            starts[i] = float(at[i])
            i += 1
            continue
        prev = starts[i - 1] if i else 0.0
        j = i
        while j < n and at[j] is None:
            j += 1
        nxt = float(at[j]) if j < n else duration
        gap = max(nxt - prev, 0.0)
        step = gap / (j - i + 1) if j - i + 1 else gap
        for k in range(i, j):
            starts[k] = prev + step * (k - i + 1)
        i = j

    spans: list[Span] = []
    for i, s in enumerate(fmt.shots):
        start = starts[i]
        end = starts[i + 1] if i + 1 < n else duration
        if end - start < MIN_SHOT_S:
            end = min(start + MIN_SHOT_S, duration)
        spans.append(Span(shot=s, start=start, end=end,
                          anchored=at[i] is not None))

    # max_hold_s is a CEILING ON THE SPAN, for every shot.
    #
    # It used to apply only to bare-ground shots, on the reasoning that a
    # plate boils and therefore never sits still. That is true of a dense
    # plate and false of a sparse one: a chapter stinger is two words and two
    # rules, and its boil moves too little ink to read as anything. Given an
    # equal share of a 190-second runtime it held for fifteen seconds.
    #
    # So the ceiling binds the span, and the excess goes to the next shot.
    for i, sp in enumerate(spans):
        if sp.dur <= sp.shot.max_hold_s:
            continue
        capped = sp.start + sp.shot.max_hold_s
        spans[i] = Span(sp.shot, sp.start, capped, sp.anchored)
        if i + 1 < len(spans):
            nxt = spans[i + 1]
            spans[i + 1] = Span(nxt.shot, capped, nxt.end, nxt.anchored)

    # Repair any overlap the minimum introduced, then pin the tail to the
    # audio: a shot that outlives the narration is a frame with no reason to
    # be there.
    for i in range(len(spans) - 1):
        if spans[i].end > spans[i + 1].start:
            spans[i] = Span(spans[i].shot, spans[i].start,
                            spans[i + 1].start, spans[i].anchored)
    # Capping every span leaves a shortfall when the ceilings sum to less than
    # the runtime. Pinning the tail to the audio dumped all of it on the last
    # shot — sixteen seconds on a sign-off. Spread it instead, so every shot
    # runs a little over its ceiling rather than one running four times it.
    if spans:
        used = spans[-1].end
        short = duration - used
        if short > 0.05:
            # THE SLACK GOES TO THE FRAMES THAT ARE STILL MOVING. A bare-
            # ground shot is motionless once its type has drawn on, so
            # extending it is the one thing the ceiling exists to prevent.
            # But "has a plate" was too coarse a test for alive: 44 of the
            # 47 of the 143 plates are `playback: static` by design — a figure that
            # moves is a figure being re-read — so an even share put a data
            # plate on screen for 15.4 seconds in a twelve-minute cut while
            # the room beside it, with a man talking in it, took the same.
            #
            # A shot with a HOST is the most alive frame in the format: he
            # talks, he blinks, the room boils behind him. He takes the
            # remainder first, and a plate only takes it when no shot in the
            # cut has him in it.
            takers = [i for i, sp in enumerate(spans) if sp.shot.host]
            if not takers:
                takers = [i for i, sp in enumerate(spans) if sp.shot.plate]
            if takers:
                share = short / len(takers)
                moved: list[Span] = []
                shift = 0.0
                for i, sp in enumerate(spans):
                    start = sp.start + shift
                    if i in set(takers):
                        shift += share
                    moved.append(Span(sp.shot, start, sp.end + shift,
                                      sp.anchored))
                spans = moved
        spans[-1] = Span(spans[-1].shot,
                         min(spans[-1].start, duration - MIN_SHOT_S),
                         duration, spans[-1].anchored)
    return spans
