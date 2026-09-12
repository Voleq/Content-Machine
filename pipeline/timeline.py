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

import hashlib
import math
import re
from dataclasses import dataclass, field

from pipeline.models import (
    DELIVERY_TAG_TYPES,
    OVERLAY_TAG_TYPES,
    AnnotationTarget,
    Cue,
    CueKind,
    LongScript,
    ShortScript,
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


def proportional_fallback(index: int, n: int, duration: float) -> float:
    """Position for a cue whose anchor word was not found."""
    return duration * (index + 1) / (n + 1)


def _first_sentence_end(words: list[WordTimestamp], duration: float) -> float:
    for w in words:
        if w.word.rstrip("\"'”’)").endswith((".", "!", "?", "…")):
            return w.end
    return min(2.5, duration * 0.15)


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
    # SHORT-only. render_short resolves it through article_lookup +
    # screenshot_article; render_long has no article machinery, and
    # master_prompt_long_write.md never asks for one. It still parses on a
    # LONG (it is self-resolving, so a bare tag needs no payload), so it can
    # arrive here — skipped, and said out loud, not mapped to a segment kind
    # the long renderer cannot paint.
    TagType.SHOW_ARTICLE: (
        "[SHOW ARTICLE] is a SHORT beat — the LONG renderer has no article "
        "path, so this draws nothing. Use [SCREENGRAB] with the capture, or "
        "cut the tag"),
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
# frame). DOODLE/SCRIBBLE are overlays; SOUND is audio — none claim a cut.
VISUAL_CUE_KINDS = (CueKind.CLIP, CueKind.IMG, CueKind.MEME, CueKind.CHART,
                    CueKind.FILING, CueKind.SCREENGRAB, CueKind.PLATE)

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
        if e.hold:
            # `[CLIP: … | hold=2.5]`. Only present when the director wrote
            # one, so an untagged hold still falls through to DEFAULT_HOLDS
            # and every script already written plans identically.
            payload["hold"] = e.hold
        if kind is CueKind.SCRIBBLE:
            payload["hold"] = SCRIBBLE_HOLD_S
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

# size of the renderer's DESIGNED-backdrop pool (each of rasters'
# LONG_BACKDROP_FAMILIES families is drawn with several seeds). Kept as a bare
# int so this module stays pure logic — no PIL/raster import.
LONG_FILLER_LOOKS = 12

# How long each visual kind holds before cutting back to the host WHEN THE
# DIRECTOR DID NOT SAY. These are roughly double the old values: the show is a
# host talking who cuts away to evidence, and evidence the viewer cannot
# finish reading is worse than no evidence at all. A meme is still a beat; a
# diagram is a paragraph.
#
# A `[CLIP: … | hold=2.5]` overrides its row. One number per KIND cannot be
# right for both a glance and a beat to sit in, and the writer is the only one
# who knows which this is.
DEFAULT_HOLDS = {
    CueKind.CLIP: 5.0,
    CueKind.IMG: 5.0,
    CueKind.CHART: 7.0,
    CueKind.FILING: 6.0,
    CueKind.SCREENGRAB: 6.0,
    CueKind.PLATE: 7.0,
    CueKind.MEME: 3.0,
    # the design-kit cards: a term definition and a table are READ

}

# Kinds carrying data a viewer has to READ rather than glance at. These never
# cut early: a later visual is pushed back rather than truncating one of
# these, and the voice-over simply keeps running underneath.
READABLE_KINDS = (CueKind.CHART, CueKind.FILING, CueKind.SCREENGRAB,
                  CueKind.PLATE)
MIN_READABLE_S = 5.0

# Designed panels sit BESIDE Dennis (the two-shot); real photographs,
# footage, filings and memes take the whole frame raw.
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

def plan_long_segments(
    cues: list[Cue],
    duration: float,
    *,
    holds: dict | None = None,
    chapter_starts: list[float] | list[tuple[float, str]] | None = None,
    min_readable_s: float = MIN_READABLE_S,
    chapter_host_s: float = CHAPTER_HOST_S,
    fps: int = 0,
) -> tuple[list[Segment], list[str]]:
    """Tile [0, duration] with host beats and the evidence he cuts away to.

    Dennis is the DEFAULT base frame: every stretch the director did not tag
    is one held host segment, not a run of filler cards. A visual cue claims
    the frame from its anchor word and keeps it for its full hold — if the
    next cue lands during that hold it is pushed back rather than cutting the
    current one short, so nothing on screen is ever unreadable. Chapter
    boundaries reserve a host beat on each side.

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

    def add_host(a: float, b: float) -> None:
        """Host beats for the gap — never chopped into filler cuts, but never
        one frame for a minute and a half either.

        A gap longer than `MAX_HOST_BEAT_S` becomes consecutive host segments.
        They are still all Dennis talking, so this is not a cut away from him;
        it is the shot changing, which the bank and the `variant` counter
        already do between gaps and never did inside one.
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

    cursor = 0.0
    two_shot_i = 0
    for c in visual:
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
        hold = asked or holds.get(c.kind, 5.0)
        if c.kind in READABLE_KINDS and not asked:
            hold = max(hold, min_readable_s)
        end = min(start + hold, duration)
        payload = dict(c.payload)
        if c.kind in TWO_SHOT_KINDS:
            # Dennis stays in frame beside the panel, alternating sides so
            # two two-shots in a row do not look like the same picture.
            payload["layout"] = "two-shot"
            payload["host_side"] = "left" if two_shot_i % 2 == 0 else "right"
            two_shot_i += 1
        else:
            payload["layout"] = "cutaway-full"
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
