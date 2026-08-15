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
    enter: str | None = None
    # Which bound slot is LIT. Every row of the sheet is visible in every
    # numbers shot — one carries the figures being talked about and the rest
    # are ghosted back, so the eye lands without the sheet redrawing.
    lit: str | None = None
    anchor: str | None = None
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


def parse_format(raw: dict, source: Path | None = None) -> Format:
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
        where = f"{name} shot #{i}"
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
        marks = tuple(MarkSpec(kind=m["kind"], target=m["target"],
                               name=m.get("name", m["kind"]))
                      for m in (s.get("marks") or ()))
        shots.append(Shot(
            id=sid, plate=plate,
            bind=dict(s.get("bind") or {}),
            text=_text_specs(s.get("text"), where),
            marks=marks, host=host,
            enter=s.get("enter"), lit=s.get("lit"),
            anchor=s.get("anchor"),
            max_hold_s=float(s.get("max_hold_s", 8.0)),
            captions=bool(s.get("captions", True)),
            notes=s.get("notes", "")))

    fmt = Format(name=name, aspect=raw.get("aspect", "9:16"), frame=frame,
                 shots=tuple(shots), source=source)

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
    return parse_format(raw, source=path)


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

    # A shot with no plate has no boil under it: once its type has drawn on,
    # the frame is genuinely motionless, and its ceiling is therefore a limit
    # on the SPAN and not just on the gap between layer edges. Cap it and hand
    # the time to the next shot, which has a plate and can hold it.
    #
    # A shot with a plate is exempt because its plate is redrawn seven times a
    # second for as long as it is on screen. That is the whole reason the kit
    # boils, and it is why only the bare shots need this.
    for i, sp in enumerate(spans):
        if sp.shot.plate or sp.dur <= sp.shot.max_hold_s:
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
    if spans:
        spans[-1] = Span(spans[-1].shot, min(spans[-1].start, duration - MIN_SHOT_S),
                         duration, spans[-1].anchored)
    return spans
