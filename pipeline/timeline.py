"""The master clock (§7, §11-keep): resolve every visual/audio event to an
absolute time derived from REAL audio word timestamps.

Pure logic, no I/O, no subprocesses. Renderers consume the cue lists and
segment plans produced here and never invent their own timings.

Anchor resolution rules:
  * anchor word/phrase  -> start time of the first case/punctuation-
                           insensitive match in the word stream
  * anchor not found    -> proportional fallback position, cue flagged
                           `fallback=True` (callers log the warning)
  * LONG char_offset    -> the word containing that clean-text offset,
                           else the first word starting after it

SHORT beats (Noise or signal?): Hook -> Why (headlines ON the chart) ->
Gut check (multi-year numbers sheet) -> Payoff (deadpan conclusion).
Beat boundaries scale with the real audio duration and are refined by the
script's own anchors — no scene time is ever hardcoded in a renderer.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from pipeline.models import (
    DELIVERY_TAG_TYPES,
    Cue,
    CueKind,
    LongScript,
    TagEvent,
    TagType,
    WordTimestamp,
)

_STRIP_CHARS = ".,;:!?…\"'()[]{}“”‘’-—–"


def _norm(token: str) -> str:
    return token.strip(_STRIP_CHARS).lower()


# --------------------------------------------------------------------------
# Primitive resolvers.
# --------------------------------------------------------------------------


def find_anchor_time(words: list[WordTimestamp], anchor: str) -> float | None:
    """Start time of the first occurrence of `anchor` (word or phrase)."""
    tokens = [_norm(t) for t in anchor.split() if _norm(t)]
    if not tokens or not words:
        return None
    norm_words = [_norm(w.word) for w in words]
    for i in range(len(norm_words) - len(tokens) + 1):
        if norm_words[i : i + len(tokens)] == tokens:
            return words[i].start
    return None


def char_offset_time(words: list[WordTimestamp], offset: int) -> float:
    """Time of the word whose clean-text span contains `offset`."""
    if not words:
        return 0.0
    for w in words:
        if w.char_start <= offset < w.char_end:
            return w.start
    for w in words:
        if w.char_start >= offset:
            return w.start
    return words[-1].start


def clamp(t: float, duration: float) -> float:
    return min(max(t, 0.0), max(duration - 0.05, 0.0))


# --------------------------------------------------------------------------
# The SHORT beat timeline lived here, and nothing called any of it (D4).
# --------------------------------------------------------------------------
#
# `build_short_timeline` positioned every SHORT cue off the spoken audio —
# the fixed beats, the host bookends, and the tag grammar that let a short
# "reach the library" — and `plan_short_pacing` graded the result against a
# per-75s event band. Both were reachable only from each other, and from
# their own tests.
#
# `render_short` is a fixed shot template: `load_format` reads
# `templates/shots/<format>.json`, which fixes which plate each beat uses,
# and `ShortResolver` binds text into it from the script's STRUCTURED fields
# (hook_text, headlines, numbers, cheap_or_trap, conclusion). It never
# consulted the script's inline tags, its `annotations` array, or any of
# this.
#
# Two render engines for one format could not both be real, and the shot
# template is the one the renderer, the committed samples and the suite are
# built on. A dead engine is worse than no engine: it makes it genuinely
# ambiguous which code is live, and it kept the SHORT prompt asking the
# writer for `[IMG]`, `[MEME]`, `[CLIP]`, `[SHOW FILING]` and `[SCREENGRAB]`
# work that was tokenised, validated, costed, listed on the contact sheet
# and then discarded.
#
# Gone with it: `ShortScript.evidence_events()` (called only from inside it)
# and the SHORT half of the prompt's visual vocabulary.

# --------------------------------------------------------------------------
# LONG tag timeline + jump-cut segment plan (§5, §7).
# --------------------------------------------------------------------------

_TAG_TO_KIND = {
    TagType.IMG: CueKind.IMG,
    TagType.PRODUCT: CueKind.IMG,
    TagType.MEME: CueKind.MEME,
    TagType.CLIP: CueKind.CLIP,
    TagType.BROLL: CueKind.CLIP,
    TagType.CHART: CueKind.CHART,
    TagType.SHOW_FILING: CueKind.FILING,
    TagType.SCREENGRAB: CueKind.SCREENGRAB,
    TagType.SOUND: CueKind.SOUND,
    TagType.PLATE: CueKind.PLATE,
    TagType.SCRIBBLE: CueKind.SCRIBBLE,
    # A timed instruction to the plate already on screen; it claims no frame.
    # plan_writer_moves turns these into the render's `writer_moves`.
    TagType.MOVE: CueKind.MOVE,
    # The same kind of instruction: where the figure on that plate comes from.
    # plan_writer_sources pairs it with its beat.
    TagType.SOURCE: CueKind.SOURCE,
    # The writer's room and pose for every beat of Dennis from here on. It
    # claims no frame; `plan_long_segments` cuts the beat of him it lands in.
    TagType.SCENE: CueKind.SCENE,
}

# Tag types that draw nothing on the LONG timeline BY DESIGN, and why.
#
# This is the other half of _TAG_TO_KIND, and it exists so that "produces no
# cue" is a decision recorded in the source rather than an absence. A TagType
# in neither table is UNMAPPED: the renderer would drop a tag the writer asked
# for, so validation blocks on it before the paid TTS call and the timeline
# warns if it ever gets that far.
#
# The value is the reason, phrased for the operator's report.
_LONG_NO_CUE_REASONS: dict[TagType, str] = {
    # Delivery direction is audio, not picture: tts.py's expand_delivery
    # turns these into <break> and voice settings and the captions are built
    # from the clean text. One of them reaching the screen would be the bug.
    # Keyed off DELIVERY_TAG_TYPES rather than listed, so a future delivery
    # tag inherits the exclusion instead of crashing the render.
    **{t: "delivery direction — consumed by TTS, never drawn"
       for t in DELIVERY_TAG_TYPES},
    # Retired from the grammar; the tokenizer strips it. Only a script saved
    # before the retirement can still carry one, and it is skipped, said out
    # loud, rather than mapped to a segment kind nothing paints.
    TagType.SHOW_ARTICLE: (
        "[SHOW ARTICLE] is retired and draws nothing. Use [SCREENGRAB] with "
        "the capture, or cut the tag"),
}


def unrenderable_long_tags(script: LongScript) -> list[tuple[TagEvent, str]]:
    """Every tag on a LONG that will not become a cue, with the reason.

    Resolvability is a pure function of the script, which is the whole point:
    this runs at validation time, before the paid TTS call, instead of
    KeyError-ing in build_long_timeline once the money is already spent.

    Delivery tags are excluded from the result entirely — they are supposed to
    draw nothing, so reporting them would be noise. An unmapped tag gets the
    empty string as its reason, meaning "nobody decided this": that is a
    defect in the mapping, not a design choice, and callers block on it.
    """
    out: list[tuple[TagEvent, str]] = []
    for e in script.events:
        if e.type in _TAG_TO_KIND or e.type in DELIVERY_TAG_TYPES:
            continue
        out.append((e, _LONG_NO_CUE_REASONS.get(e.type, "")))
    return out


# cue kinds that claim a visual segment on the LONG timeline (the base
# frame). SCRIBBLE is an overlay; SOUND is audio — neither claims a cut.
VISUAL_CUE_KINDS = (CueKind.CLIP, CueKind.IMG, CueKind.MEME, CueKind.CHART,
                    CueKind.FILING, CueKind.SCREENGRAB, CueKind.PLATE)

# Tags whose cue claims the frame. A [MOVE] acts on the last of these before
# it — and only when that one is a [PLATE], because a move lands in a slot the
# plate's own drawing publishes, and a clip or a meme has no slots.
FRAME_TAG_TYPES = frozenset(
    t for t, k in _TAG_TO_KIND.items() if k in VISUAL_CUE_KINDS)


# Tags that act on the plate already on screen rather than claiming a frame.
PLATE_ACTION_TAG_TYPES = frozenset({TagType.MOVE, TagType.SOURCE})


def move_targets(events: list[TagEvent],
                 types: frozenset[TagType] = frozenset({TagType.MOVE}),
                 ) -> dict[int, int | None]:
    """For every [MOVE] in `events`, the index of the tag holding the frame.

    `None` when nothing before it claims the frame (the move would open on
    Dennis). The caller decides what a target that is not a plate means.
    `types` widens it to the other tags that act on the plate on screen.
    """
    out: dict[int, int | None] = {}
    last: int | None = None
    for i, e in enumerate(events):
        if e.type in FRAME_TAG_TYPES:
            last = i
        elif e.type in types:
            out[i] = last
    return out


# How long an annotation stays on screen before it lifts off. An annotation is
# drawn in ATTENTION and spends the frame's one attention, so it is a beat in
# its own right rather than decoration that can linger.
SCRIBBLE_HOLD_S = 2.0


def build_long_timeline(
    script: LongScript,
    words: list[WordTimestamp],
    duration: float,
) -> list[Cue]:
    """Resolve each TagEvent's clean-text char offset to its spoken time, so
    the ironic cut lands on the exact word it undercuts."""
    cues: list[Cue] = []
    targets = move_targets(script.events, PLATE_ACTION_TAG_TYPES)
    for idx, e in enumerate(script.events):
        # Not every tag draws. Delivery direction is audio and is filtered
        # against DELIVERY_TAG_TYPES so the intent stays readable here;
        # anything else without a CueKind is skipped rather than crashing the
        # render, and validate_long_script has already reported it.
        if e.type in DELIVERY_TAG_TYPES:
            continue
        kind = _TAG_TO_KIND.get(e.type)
        if kind is None:
            continue
        t = clamp(char_offset_time(words, e.char_offset), duration)
        payload = {"order": idx, "value": e.payload, "tag": e.type.value,
                   "values": dict(e.values)}
        if kind is CueKind.CHART and e.style:
            payload["style"] = e.style
        if e.beside:
            # `with=`: Dennis stands beside this one (the two-shot).
            payload["beside"] = e.beside
        if e.hold:
            # `[CLIP: … | hold=2.5]`. Only present when the director wrote
            # one, so an untagged hold still falls through to DEFAULT_HOLDS
            # and every script already written plans identically.
            payload["hold"] = e.hold
        if kind is CueKind.SCRIBBLE:
            payload["hold"] = SCRIBBLE_HOLD_S
        if kind in (CueKind.MOVE, CueKind.SOURCE):
            # WHICH PLATE, by the order of its tag. The parser recorded the
            # plate key the move was written after, and that plate may have
            # been dropped there; only when the tag holding the frame here is
            # that same plate is the move paired, so it can never slide back
            # onto an earlier plate the writer did not mean.
            at = targets.get(idx)
            held = script.events[at] if at is not None else None
            same = (held is not None and held.type is TagType.PLATE
                    and held.payload == e.values.get("plate"))
            payload["plate_order"] = at if same else None
            payload["plate"] = held.payload if same else ""
        cues.append(Cue(t=t, kind=kind, payload=payload))
    cues.sort(key=lambda c: (c.t, c.payload.get("order", 0)))
    return cues


@dataclass
class Segment:
    start: float
    end: float
    kind: str          # clip | img | meme | chart | filing | screengrab | asset | filler
    payload: dict = field(default_factory=dict)

    @property
    def length(self) -> float:
        return self.end - self.start


MIN_SEGMENT_S = 0.25


# How long each GLANCED kind holds before cutting back to the host WHEN THE
# DIRECTOR DID NOT SAY. A meme is a beat; a photograph or a clip a little
# longer. The kinds a viewer READS — a plate, a chart, a filing — have no row
# here since item 31: they hold until the writer moves on (`READABLE_KINDS`).
#
# A `[CLIP: … | hold=2.5]` overrides its row. One number per KIND cannot be
# right for both a glance and a beat to sit in, and the writer is the only one
# who knows which this is.
DEFAULT_HOLDS = {
    CueKind.CLIP: 5.0,
    CueKind.IMG: 5.0,
    CueKind.MEME: 3.0,
}

# Kinds carrying data a viewer has to READ rather than glance at. These never
# cut early: a later visual is pushed back rather than truncating one of
# these, and the voice-over simply keeps running underneath.
#
# AND THEY STAY UP WHILE HE TALKS ABOUT THEM (item 31). Every plate used to
# hold exactly its `DEFAULT_HOLDS` row, 7.0 s, and cut back to Dennis — while
# the writing prompt promised "the renderer holds the visual for as long as
# your words about it last". A readable beat now holds until the writer's
# next visual tag, the next [SCENE], the end of its paragraph or the next
# chapter's bookend, whichever comes first: the writer moving on is the cut.
# Never under `MIN_READABLE_S`, never over `MAX_READABLE_S`.
READABLE_KINDS = (CueKind.CHART, CueKind.FILING, CueKind.SCREENGRAB,
                  CueKind.PLATE)
MIN_READABLE_S = 5.0

# The longest a readable beat holds when nothing ends it sooner. A script
# written as one paragraph with a plate at the top would otherwise hold that
# plate for the whole stretch; past this he comes back, and the planner says
# where so the writer can break the paragraph or add the next piece.
MAX_READABLE_S = 30.0

# The kinds Dennis MAY stand beside (the two-shot), and only when the writer
# asks with `with=` on the tag (items 30 and 11). By default a plate or chart
# fills the frame: shrunk into a column beside him it read as a mini player,
# and a still two-shot froze his face. Real photographs, footage, filings and
# memes take the whole frame, as ever.
TWO_SHOT_KINDS = (CueKind.CHART, CueKind.PLATE)

# Dennis bookends every chapter: this much host on each side of a chapter
# boundary is reserved, so a chapter always opens and closes on his face.
CHAPTER_HOST_S = 2.5

# The shortest host beat worth cutting to. A third of a second of Dennis
# between two cutaways is a blink, not a beat — below this the evidence
# already on screen simply stays up until the next one is due.
MIN_HOST_BEAT_S = 1.2

# The LONGEST one host beat may run before the shot has to change. There was
# no maximum: `add_host` emitted exactly one segment per untagged gap, so
# ninety untagged seconds was ninety seconds of a single frame with a mouth
# flap on it — and the planner considered that correct, so nothing said so.
# A gap longer than this is split into consecutive beats with the shot
# advancing, which is what the bank and the variant counter were already for.
MAX_HOST_BEAT_S = 12.0

# A gap this long has no visual of its own at all. Splitting it keeps the
# frame alive, but the writer should know where the video goes visually
# silent, so it is named with its timestamp.
HOST_GAP_WARN_S = 25.0


def chapter_start_times(chapters: str, duration: float) -> list[tuple[float, str]]:
    """`(seconds, title)` from the `=== CHAPTERS ===` trailer's `mm:ss Title`.

    The times are the writer's estimates, not measurements — they are used to
    reserve a host beat around each boundary and to place the section
    stingers, never to place audio. Anything unparseable or past the end of
    the cut is skipped.

    The TITLE is returned as well because the renderer was throwing it away:
    it spaced its stingers evenly across the runtime and drew them from a
    hardcoded six-entry list, so every long video carried section titles that
    had nothing to do with its own sections.
    """
    out: list[tuple[float, str]] = []
    for line in (chapters or "").splitlines():
        stamp, _, title = line.strip().partition(" ")
        parts = stamp.split(":")
        if not (2 <= len(parts) <= 3) or not all(p.isdigit() for p in parts):
            continue
        seconds = 0.0
        for p in parts:
            seconds = seconds * 60 + int(p)
        if 0.0 < seconds < duration:
            out.append((seconds, title.strip()))
    # Sorted by time, first title wins a duplicated timestamp.
    seen: set[float] = set()
    unique: list[tuple[float, str]] = []
    for t, title in sorted(out, key=lambda p: p[0]):
        if t not in seen:
            seen.add(t)
            unique.append((t, title))
    return unique


def _diversify_fillers(segments: list["Segment"]) -> None:
    """Number the host beats sequentially (payload['variant']).

    The renderer spreads that index across the rig's poses and boil seeds, so
    a long cut does not return to an identical Dennis every time. Consecutive
    beats get consecutive indices, so neighbours can never match."""
    counter = 0
    for seg in segments:
        if seg.kind != "host":
            continue
        seg.payload["variant"] = counter
        counter += 1



def quantise_to_frames(segments: list[Segment], fps: int,
                       duration: float) -> list[Segment]:
    """Snap every segment boundary onto the frame grid (D1).

    Each segment was encoded with `-t {duration}` at `-r {fps}`, which lands
    on a whole number of frames, and the clips were then joined as-is — so
    every segment lost up to one frame and the losses ACCUMULATED. Forty
    segments of 1.011s at 30fps become 30 frames each, 1.000s each, and the
    picture ends 0.44s ahead of a voice that is still on the real clock. The
    repo's own 22-minute sample plan has 142 segments.

    Nothing caught it. The final length check compares the container's
    duration against the audio, and the container's duration FOLLOWS the
    audio track — so the deviation reads as zero and the last moments are a
    frozen frame.

    The fix is to decide the frame boundaries here, where the whole timeline
    is visible, rather than letting each encode round independently. Every
    boundary becomes the nearest frame index; the remainder is therefore
    carried into the next segment instead of being dropped, and the segments
    still tile [0, duration] exactly. Cut lengths move by at most half a
    frame, which is below anything a viewer can see and is the point: the
    error stays bounded instead of summing.
    """
    if fps <= 0 or not segments:
        return segments
    last_frame = round(duration * fps)
    out: list[Segment] = []
    prev_frame = round(segments[0].start * fps)
    for i, seg in enumerate(segments):
        end_frame = last_frame if i == len(segments) - 1 \
            else round(seg.end * fps)
        # Never let a rounding collapse a segment to nothing: a zero-length
        # clip is an ffmpeg failure, not a shorter cut.
        end_frame = max(end_frame, prev_frame + 1)
        out.append(Segment(start=prev_frame / fps, end=end_frame / fps,
                           kind=seg.kind, payload=seg.payload))
        prev_frame = end_frame
    return out

_PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\n\s*(?=\S)")


def paragraph_starts(narration: str, words: list[WordTimestamp]) -> list[float]:
    """When each paragraph after the first starts being said, in order.

    A blank line in the narration is the writer's paragraph; the time is the
    first word after it, off the same clock every tag is placed on.
    """
    out: list[float] = []
    if not words:
        return out
    for m in _PARAGRAPH_BREAK.finditer(narration or ""):
        t = char_offset_time(words, m.end())
        if t > 0.0 and (not out or t > out[-1]):
            out.append(t)
    return out


def scene_in_force(cues: list[Cue], t: float) -> Cue | None:
    """The writer's [SCENE] a beat of him starting at `t` is shot in, or None.

    The latest one said by then. A scene said within a beat's first moments
    claims the whole beat: the word is where the writer wanted the cut, and a
    sliver of the old scene in front of it would be a cut nobody asked for.
    """
    got = None
    for c in sorted((c for c in cues if c.kind is CueKind.SCENE),
                    key=lambda c: (c.t, c.payload.get("order", 0))):
        if c.t <= t + MIN_HOST_BEAT_S:
            got = c
        else:
            break
    return got


def plan_long_segments(
    cues: list[Cue],
    duration: float,
    *,
    holds: dict | None = None,
    chapter_starts: list[float] | list[tuple[float, str]] | None = None,
    min_readable_s: float = MIN_READABLE_S,
    chapter_host_s: float = CHAPTER_HOST_S,
    fps: int = 0,
    paragraphs: list[float] | None = None,
    max_readable_s: float = MAX_READABLE_S,
) -> tuple[list[Segment], list[str]]:
    """Tile [0, duration] with host beats and the evidence he cuts away to.

    Dennis is the DEFAULT base frame: every stretch the director did not tag
    is one held host segment, not a run of filler cards. A visual cue claims
    the frame from its anchor word and keeps it for its full hold — if the
    next cue lands during that hold it is pushed back rather than cutting the
    current one short, so nothing on screen is ever unreadable. Chapter
    boundaries reserve a host beat on each side.

    A READABLE beat's hold is the writer's moving on (item 31): it lasts until
    the next visual tag, the next [SCENE], the next of `paragraphs` (when
    each paragraph after the first starts, `paragraph_starts`) or the next
    chapter's bookend — at least `min_readable_s`, at most `max_readable_s`.
    Other kinds hold their `DEFAULT_HOLDS` row; a writer's `hold=` beats both.

    Returns (segments, warnings). Invariant: segments tile the full duration
    with no gaps or overlaps.

    `fps`, when given, snaps every boundary onto the frame grid so the cuts
    stay on the real clock through the encode — see `quantise_to_frames`.
    """
    holds = {**DEFAULT_HOLDS, **(holds or {})}
    warnings: list[str] = []
    visual = [c for c in cues if c.kind in VISUAL_CUE_KINDS]
    visual.sort(key=lambda c: c.t)

    # Windows the evidence may not occupy, so each chapter opens and closes
    # on Dennis talking. `chapter_starts` carries titles now; either shape is
    # accepted so a caller that only has times still works.
    starts = [t[0] if isinstance(t, (tuple, list)) else float(t)
              for t in (chapter_starts or [])]
    blocked: list[tuple[float, float]] = [
        (max(t - chapter_host_s, 0.0), min(t + chapter_host_s, duration))
        for t in sorted(starts) if 0.0 < t < duration
    ]

    def push_past_chapter_beat(t: float) -> float:
        for a, b in blocked:
            if a <= t < b:
                return b
        return t

    segments: list[Segment] = []
    host_i = 0

    # THE WRITER'S SCENES, in the order they are said. Each holds for every
    # beat of Dennis after it until the next, across the cutaways between.
    scenes = sorted((c for c in cues if c.kind is CueKind.SCENE),
                    key=lambda c: (c.t, c.payload.get("order", 0)))

    def scene_at(t: float) -> Cue | None:
        return scene_in_force(scenes, t)

    def add_host(a: float, b: float) -> None:
        """Host beats for the gap — never chopped into filler cuts, but never
        one frame for a minute and a half either.

        A gap longer than `MAX_HOST_BEAT_S` becomes consecutive host segments.
        They are still all Dennis talking, so this is not a cut away from him;
        it is the shot changing, which the bank and the `variant` counter
        already do between gaps and never did inside one.

        A [SCENE] said inside the gap cuts it on the scene's word, and a beat
        the writer directed is one shot however long it runs: the room and the
        pose are his, and splitting it would cut his picture against itself.
        """
        nonlocal host_i
        span = b - a
        if span <= 0:
            return
        if span < MIN_HOST_BEAT_S and segments:
            # too short to be a beat: leave the previous visual up instead of
            # blinking to the host and straight back out
            segments[-1].end = b
            return
        # Two scenes said a breath apart are one cut, to the later of them.
        edges = [a]
        for t in sorted({c.t for c in scenes
                         if a + MIN_HOST_BEAT_S < c.t < b - MIN_HOST_BEAT_S}):
            if t - edges[-1] >= MIN_HOST_BEAT_S:
                edges.append(t)
        edges.append(b)
        for p0, p1 in zip(edges, edges[1:]):
            scene = scene_at(p0)
            if scene is None:
                _undirected(p0, p1)
                continue
            # A chapter that starts inside a scene still gets its cut: the
            # chapter's card lands on the first cut at or after its time, and
            # one shot held across the boundary would push the card past it.
            inner = [t for t in starts if p0 + MIN_HOST_BEAT_S < t < p1 - MIN_HOST_BEAT_S]
            pts = [p0, *sorted(inner), p1]
            for q0, q1 in zip(pts, pts[1:]):
                _directed(q0, q1, scene)

    def _directed(a: float, b: float, scene: Cue) -> None:
        """One beat of him, shot as the writer's scene has it."""
        nonlocal host_i
        if b - a > HOST_GAP_WARN_S:
            warnings.append(
                f"one scene held {b - a:.0f}s from {a:.0f}s to {b:.0f}s "
                f"({scene.payload.get('value', '')}) — nothing on screen "
                f"changes; a [SCENE] or a visual in that stretch moves the "
                f"picture")
        segments.append(Segment(
            start=a, end=b, kind="host",
            payload={"variant": host_i, "layout": "host-full",
                     "scene": dict(scene.payload.get("values") or {}),
                     "scene_order": scene.payload.get("order", 0)}))
        host_i += 1

    def _undirected(a: float, b: float) -> None:
        """Beats of him the writer left to the bot: even parts, as ever."""
        nonlocal host_i
        span = b - a
        if span > HOST_GAP_WARN_S:
            warnings.append(
                f"{span:.0f}s with no visual from {a:.0f}s to {b:.0f}s — the "
                f"shot changes but nothing new is shown; consider a tag in "
                f"that stretch"
            )
        # Even parts, so the last one is never a stub.
        n = max(int(math.ceil(span / MAX_HOST_BEAT_S)), 1)
        step = span / n
        for i in range(n):
            start = a + i * step
            end = b if i == n - 1 else a + (i + 1) * step
            segments.append(Segment(start=start, end=end, kind="host",
                                    payload={"variant": host_i,
                                             "layout": "host-full"}))
            host_i += 1

    # Where the writer moves on: a readable beat holds until the first of
    # these after it starts. Each chapter's bookend begins `chapter_host_s`
    # before its card, and that is where the evidence has to be gone by.
    scene_times = sorted(c.t for c in scenes)
    para_times = sorted(float(t) for t in (paragraphs or ()))
    bookends = sorted(a for a, _b in blocked)

    def talked_about_until(k: int, start: float) -> tuple[float, str]:
        """(when the writer moves on from visual `k`, what ends it)."""
        cue_t = visual[k].t
        found = [(duration, "the end")]
        later = [c.t for c in visual[k + 1:] if c.t > cue_t + 1e-6]
        if later:
            found.append((min(later), "the next visual"))
        for times, why in ((scene_times, "the next [SCENE]"),
                           (para_times, "the paragraph's end"),
                           (bookends, "the chapter's end")):
            nxt = next((t for t in times if t > start + 1e-6), None)
            if nxt is not None:
                found.append((nxt, why))
        return min(found)

    cursor = 0.0
    for k, c in enumerate(visual):
        # never before the previous visual has finished, never inside a
        # chapter bookend
        start = push_past_chapter_beat(max(c.t, cursor))
        if not segments and start < MIN_HOST_BEAT_S:
            # the cut opens on Dennis, even when the first tag lands early
            start = min(MIN_HOST_BEAT_S, duration)
        if start >= duration - MIN_SEGMENT_S:
            warnings.append(
                f"visual cue at {c.t:.2f}s no longer fits before the end — dropped"
            )
            continue
        if start - c.t > 2.0:
            warnings.append(
                f"visual cue at {c.t:.2f}s deferred to {start:.2f}s — the previous "
                f"visual was still being read"
            )
        add_host(cursor, start)
        # THE DIRECTOR'S HOLD WINS. A number in the tag is the one place in
        # this planner where somebody who read the line decided how long the
        # frame stays; `DEFAULT_HOLDS` is what to do when nobody did. It has
        # already been clamped to a sane band at parse time.
        asked = float(c.payload.get("hold") or 0.0)
        if asked:
            hold = asked
        elif c.kind in READABLE_KINDS:
            until, why = talked_about_until(k, start)
            hold = min(max(until - start, min_readable_s), max_readable_s)
            if until - start > max_readable_s + 1e-6 and \
                    start + max_readable_s < duration - MIN_HOST_BEAT_S:
                warnings.append(
                    f"{c.kind.value} at {start:.0f}s would hold "
                    f"{until - start:.0f}s until {why}; it holds "
                    f"{max_readable_s:.0f}s and he comes back — break the "
                    f"paragraph or tag what comes next")
        else:
            hold = holds.get(c.kind, 5.0)
        end = min(start + hold, duration)
        payload = dict(c.payload)
        # The evidence fills the frame. Dennis stands beside a plate or a
        # chart only where the writer put `with=` on its tag.
        payload["layout"] = ("two-shot" if c.kind in TWO_SHOT_KINDS
                             and c.payload.get("beside") else "cutaway-full")
        segments.append(Segment(start=start, end=end, kind=c.kind.value,
                                payload=payload))
        cursor = end
    add_host(cursor, duration)

    # ---- scene-variety pass (§editing) -------------------------------------
    # Host beats are numbered so the renderer can vary his pose and the boil
    # seed across a long cut. Adjacent same-TYPE cutaways are flagged (rare —
    # they only happen when the director stacks two of a kind back-to-back).
    _diversify_fillers(segments)
    for a, b in zip(segments, segments[1:]):
        if a.kind == b.kind and a.kind != "host":
            warnings.append(
                f"adjacent {a.kind} cuts at {a.start:.2f}s/{b.start:.2f}s "
                f"— same visual type back-to-back"
            )

    if fps:
        segments = quantise_to_frames(segments, fps, duration)

    # tiling invariant — fail loudly in dev rather than desync audio/video.
    # `eps` is half a frame once the plan is quantised: the last boundary is
    # the nearest frame to `duration`, which is the closest a frame grid can
    # come to it, and demanding exactness would be demanding the impossible.
    eps = (0.5 / fps + 1e-6) if fps else 1e-6
    assert segments, "segment plan must not be empty"
    assert abs(segments[0].start) < eps and abs(segments[-1].end - duration) < eps
    for a, b in zip(segments, segments[1:]):
        assert abs(a.end - b.start) < 1e-6, "segments must tile without gaps"
    return segments, warnings


def estimate_dennis_alone(script, settings) -> float | None:
    """The share of the video that is Dennis alone in frame, before a word
    is spoken (item 32), or None for an empty script.

    The planner itself, run on the voice's estimated timings (the words over
    the words a second the mock voice and the real one agree on), so the
    approval screen reads off the same rules the render will cut by. A
    two-shot has him beside the evidence and counts as evidence, as the
    storyboard counts it.
    """
    from pipeline.tts import mock_words

    wps = max(float(getattr(settings, "mock_wps_long", 2.3) or 2.3), 0.1)
    duration = script.word_count / wps
    if duration <= 0:
        return None
    words = mock_words(script.narration, duration)
    cues = build_long_timeline(script, words, duration)
    starts = [a for a, _b in chapter_windows(script.chapter_list, duration)]
    segments, _ = plan_long_segments(
        cues, duration, chapter_starts=starts,
        min_readable_s=settings.long_min_readable_s,
        chapter_host_s=settings.long_chapter_host_s,
        paragraphs=paragraph_starts(script.narration, words),
        max_readable_s=settings.long_max_readable_s)
    alone = sum(s.length for s in segments if s.kind == "host")
    return alone / duration


# --------------------------------------------------------------------------
# Chapter windows, and the writer's moves on the plates.
# --------------------------------------------------------------------------


def chapter_windows(chapters, duration: float) -> list[tuple[float, float]]:
    """`(start, end)` seconds per chapter of `script.chapter_list`.

    The same placement render_long's chapter plan draws its openers at: a
    trailer timestamp where the writer gave one, else the chapter's even share
    of the runtime, because the ORDER is still information. The first window
    opens at zero so the cold open owns everything before the first boundary.
    Empty when there are no chapters.
    """
    n = len(chapters)
    starts: list[float] = []
    for i, ch in enumerate(chapters):
        start_s = float(getattr(ch, "start_s", 0.0) or 0.0)
        starts.append(start_s if start_s or i == 0 else duration * i / max(n, 1))
    if starts:
        starts[0] = 0.0
    out: list[tuple[float, float]] = []
    for i, a in enumerate(starts):
        b = starts[i + 1] if i + 1 < n else duration
        a = min(max(a, 0.0), duration)
        out.append((a, min(max(b, a), duration)))
    return out


def chapter_at(t: float, starts: list[float]) -> int:
    """Index of the chapter `t` falls in, by sorted chapter start times."""
    i = 0
    for j, s in enumerate(starts):
        if t >= s:
            i = j
    return i


@dataclass(frozen=True)
class WriterMove:
    """One `[MOVE]` the writer called, as the render should play it.

    `t` is programme time in seconds, off the word timings; `at` is the same
    moment measured from the start of the plate's segment, which is what an
    engine animating one segment in isolation needs. `slot` and `box` are the
    kit's anchor for this move on this plate (`Plate.motion`), never chosen
    here; `text` is what the writer put in that slot, so a count-up knows the
    figure it counts to without re-reading the tag.
    """

    move: str
    plate: str
    slot: str
    t: float
    segment: int
    at: float
    box: dict = field(default_factory=dict)
    text: str = ""
    order: int = 0

    def to_json(self) -> dict:
        return {"move": self.move, "plate": self.plate, "slot": self.slot,
                "t": round(self.t, 3), "segment": self.segment,
                "at": round(self.at, 3), "box": dict(self.box),
                "text": self.text, "order": self.order}


def plan_writer_moves(
    cues: list[Cue],
    segments: list[Segment],
    reg,
    *,
    chapter_starts: list[float] | None = None,
) -> tuple[list[WriterMove], list[str]]:
    """Pair each `[MOVE]` cue with the plate segment it acts on.

    Validation refused what the script got wrong before any money was spent;
    this re-applies the same rules against the REAL clock, because only the
    spoken timings say what is on screen when the word lands:

    * a plate the planner deferred (the previous visual was still being read)
      takes its move with it, so the move plays as the plate arrives rather
      than over whatever came before it;
    * a move whose word is spoken after the plate has cut back to Dennis has
      nothing to act on, and is dropped with a warning, never replayed over
      the host;
    * pen-circle keeps to one a chapter and three a video by real chapter
      time, first come first kept, because a parse-time estimate near a
      chapter boundary can be wrong in either direction;
    * the same move twice on one segment plays once.

    Returns `(moves, warnings)`, moves in programme order.
    """
    from pipeline.plates import (
        NUMBER_MOVES,
        PEN_CIRCLES_PER_CHAPTER,
        PEN_CIRCLES_PER_VIDEO,
        move_box,
        one_number,
        writer_moves,
    )

    by_order = {s.payload.get("order"): i for i, s in enumerate(segments)
                if s.kind == CueKind.PLATE.value}
    starts = sorted(float(t) for t in (chapter_starts or []))
    out: list[WriterMove] = []
    warnings: list[str] = []
    circles_video = 0
    circles_chapter: dict[int, int] = {}
    played: set[tuple[int, str]] = set()

    moves = sorted((c for c in cues if c.kind is CueKind.MOVE),
                   key=lambda c: (c.t, c.payload.get("order", 0)))
    for c in moves:
        move = str(c.payload.get("value") or "")
        where = f"[MOVE: {move}] at {c.t:.1f}s"
        seg_i = by_order.get(c.payload.get("plate_order"))
        if c.payload.get("plate_order") is None:
            warnings.append(f"{where} has no plate on screen to act on — skipped")
            continue
        if seg_i is None:
            warnings.append(f"{where}: its plate never reached the screen "
                            f"(dropped from the plan) — skipped")
            continue
        seg = segments[seg_i]
        key = str(seg.payload.get("value") or "")
        plate = reg.get(key) if reg is not None else None
        slot = writer_moves(plate).get(move)
        if not slot:
            warnings.append(f"{where}: {key} cannot do {move} — skipped")
            continue
        values = seg.payload.get("values") or {}
        text = str(values.get(slot, ""))
        if move in NUMBER_MOVES and not one_number(text):
            warnings.append(f"{where}: {key}'s {slot} holds {text!r}, not one "
                            f"number — skipped")
            continue
        t = max(c.t, seg.start)
        if t >= seg.end:
            warnings.append(
                f"{where}: {key} had cut back to Dennis at {seg.end:.1f}s, "
                f"before the word the move was written on — skipped")
            continue
        if (seg_i, move) in played:
            warnings.append(f"{where}: {move} already plays on {key} in this "
                            f"beat — skipped")
            continue
        if move == "pen-circle":
            ch = chapter_at(t, starts)
            if circles_video >= PEN_CIRCLES_PER_VIDEO:
                warnings.append(
                    f"{where}: the video already has {PEN_CIRCLES_PER_VIDEO} "
                    f"pen-circles — skipped")
                continue
            if circles_chapter.get(ch, 0) >= PEN_CIRCLES_PER_CHAPTER:
                warnings.append(
                    f"{where}: chapter {ch + 1} already has its pen-circle "
                    f"— skipped")
                continue
            circles_video += 1
            circles_chapter[ch] = circles_chapter.get(ch, 0) + 1
        played.add((seg_i, move))
        out.append(WriterMove(
            move=move, plate=key, slot=slot, t=t, segment=seg_i,
            at=t - seg.start, box=move_box(plate, move), text=text,
            order=int(c.payload.get("order", 0))))
    return out, warnings


@dataclass(frozen=True)
class WriterSource:
    """One `[SOURCE]` the writer wrote, paired with the beat it is under.

    `t` is programme time off the word timings, `at` the same moment from the
    start of the plate's segment. The render slides the tag in at `t` or once
    the beat's moves have landed, whichever is later.
    """

    text: str
    plate: str
    t: float
    segment: int
    at: float

    def to_json(self) -> dict:
        return {"text": self.text, "plate": self.plate, "t": round(self.t, 3),
                "segment": self.segment, "at": round(self.at, 3)}


def plan_writer_sources(
    cues: list[Cue],
    segments: list[Segment],
) -> tuple[list[WriterSource], list[str]]:
    """Pair each `[SOURCE]` cue with the plate segment it goes under.

    The same pairing a `[MOVE]` gets, against the real clock: a deferred plate
    takes its source with it, a source whose word comes after the plate has
    cut back to Dennis has nothing to go under and is dropped with a warning,
    and a beat carries one source — the first. Returns `(sources, warnings)`.
    """
    by_order = {s.payload.get("order"): i for i, s in enumerate(segments)
                if s.kind == CueKind.PLATE.value}
    out: list[WriterSource] = []
    warnings: list[str] = []
    taken: set[int] = set()
    for c in sorted((c for c in cues if c.kind is CueKind.SOURCE),
                    key=lambda c: (c.t, c.payload.get("order", 0))):
        text = str(c.payload.get("value") or "").strip()
        where = f"[SOURCE: {text}] at {c.t:.1f}s"
        seg_i = by_order.get(c.payload.get("plate_order"))
        if c.payload.get("plate_order") is None:
            warnings.append(f"{where} has no plate on screen to go under — skipped")
            continue
        if seg_i is None:
            warnings.append(f"{where}: its plate never reached the screen "
                            f"(dropped from the plan) — skipped")
            continue
        seg = segments[seg_i]
        t = max(c.t, seg.start)
        if t >= seg.end:
            warnings.append(f"{where}: the plate had cut back to Dennis at "
                            f"{seg.end:.1f}s — skipped")
            continue
        if seg_i in taken:
            warnings.append(f"{where}: this beat already has its source — skipped")
            continue
        taken.add(seg_i)
        out.append(WriterSource(text=text, plate=str(seg.payload.get("value") or ""),
                                t=t, segment=seg_i, at=t - seg.start))
    return out, warnings
