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
from dataclasses import dataclass, field

from pipeline.models import (
    AnnotationTarget,
    Cue,
    CueKind,
    LongScript,
    ShortScript,
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
# SHORT beat timeline (§4).
# --------------------------------------------------------------------------


def build_short_timeline(
    script: ShortScript,
    words: list[WordTimestamp],
    duration: float,
    *,
    numbers_frac: float = 0.52,
    conclusion_lead_s: float = 5.0,
    meme_hold_s: float = 1.4,
    cutaway_hold_s: float = 2.0,
    doodle_hold_s: float = 1.6,
) -> list[Cue]:
    """Every SHORT cue, positioned off the spoken audio. No number in the
    renderer may override these."""
    cues: list[Cue] = []

    # ---- beat boundaries, scaled by the real duration, refined by anchors
    hook_end = clamp(_first_sentence_end(words, duration), duration)

    payoff_t = duration - conclusion_lead_s
    payoff_fallback = True
    conc_tokens = script.conclusion.split()
    if len(conc_tokens) >= 3:
        anchored = find_anchor_time(words, " ".join(conc_tokens[:3]))
        if anchored is not None:
            payoff_t = anchored
            payoff_fallback = False
    payoff_t = clamp(max(payoff_t, duration * 0.6), duration)

    gut_t = duration * numbers_frac
    for a in script.annotations:
        if a.target is AnnotationTarget.NUMBERS:
            anchored = find_anchor_time(words, a.anchor_word)
            if anchored is not None:
                gut_t = min(gut_t, anchored - 1.2)
    gut_t = clamp(gut_t, duration)
    gut_t = max(gut_t, hook_end + 1.5)
    gut_t = min(gut_t, max(payoff_t - 1.5, hook_end + 1.5))

    # ---- 1. cold open: hook card over the branded chart, from t=0
    cues.append(Cue(t=0.0, kind=CueKind.HOOK,
                    payload={"text": script.hook_text, "until": hook_end}))

    # ---- beat-transition stingers (fast cuts between the fixed beats)
    for name, t in (("why", hook_end), ("gut", gut_t), ("payoff", payoff_t)):
        cues.append(Cue(t=clamp(t, duration), kind=CueKind.TRANSITION,
                        payload={"name": name}))

    # ---- 2. why: driver headlines overlaid ON the chart
    n_head = len(script.headlines)
    why_span = max(gut_t - hook_end, 0.5)
    for i, h in enumerate(script.headlines):
        t = hook_end + why_span * i / n_head + 0.15
        cues.append(Cue(
            t=clamp(min(t, gut_t - 0.2), duration),
            kind=CueKind.HEADLINE,
            payload={"index": i, "text": h.text, "meaning": h.meaning,
                     "until": gut_t},
        ))

    # ---- 3. gut check: the numbers sheet slides in, rows type on
    cues.append(Cue(t=gut_t, kind=CueKind.NUMBERS,
                    payload={"rows": len(script.numbers), "until": duration}))
    n_rows = len(script.numbers)
    rows_start = gut_t + 0.35
    rows_end = max(payoff_t - 0.5, rows_start + 0.5)
    slot = (rows_end - rows_start) / n_rows
    row_times: list[float] = []
    for i, row in enumerate(script.numbers):
        t = clamp(rows_start + i * slot, duration)
        row_times.append(t)
        cues.append(Cue(
            t=t, kind=CueKind.NUMBER_ROW,
            payload={"index": i, "label": row.label, "values": row.values,
                     "type_seconds": round(min(0.9, slot * 0.5), 3)},
        ))

    # ---- annotations (hand-drawn scribbles) + zoom-punch on key numbers
    for i, a in enumerate(script.annotations):
        anchored = find_anchor_time(words, a.anchor_word)
        fb = anchored is None
        if a.target is AnnotationTarget.NUMBERS:
            idx = a.row_index if a.row_index is not None else 0
            floor = row_times[idx] + 0.25
            t = anchored if anchored is not None else floor + 0.15
            t = max(t, floor)  # never before its row has typed in
        else:
            t = anchored if anchored is not None else hook_end + why_span * 0.5
            t = max(t, 0.3)
        t = clamp(t, duration)
        cues.append(Cue(
            t=t, kind=CueKind.ANNOTATION, fallback=fb,
            payload={"index": i, "target": a.target.value, "note": a.note,
                     "row_index": a.row_index, "anchor_word": a.anchor_word},
        ))
        if a.target is AnnotationTarget.NUMBERS:
            cues.append(Cue(
                t=clamp(t + 0.05, duration), kind=CueKind.ZOOM, fallback=fb,
                payload={"row_index": a.row_index if a.row_index is not None else 0},
            ))

    # ---- optional meme freeze-frame / ironic cutaway
    if script.meme is not None:
        anchored = find_anchor_time(words, script.meme.anchor_word) \
            if script.meme.anchor_word else None
        fb = anchored is None
        t = anchored if anchored is not None else max(payoff_t - 2.4, gut_t + 0.5)
        t = clamp(min(t, duration - meme_hold_s - 0.2), duration)
        cues.append(Cue(t=t, kind=CueKind.MEME, fallback=fb,
                        payload={"key": script.meme.key, "duration": meme_hold_s}))
    if script.broll is not None:
        anchored = find_anchor_time(words, script.broll.anchor_word) \
            if script.broll.anchor_word else None
        fb = anchored is None
        t = anchored if anchored is not None else hook_end + why_span * 0.65
        t = clamp(min(t, duration - cutaway_hold_s - 0.2), duration)
        cues.append(Cue(t=t, kind=CueKind.CUTAWAY, fallback=fb,
                        payload={"key": script.broll.key, "duration": cutaway_hold_s}))

    # ---- inline [DOODLE]/[SCRIBBLE] overlays, word-anchored to their
    #      position in the (clean) audio_script — composited on top, so
    #      they never disturb the beat structure
    for e in script.doodle_events():
        t = clamp(char_offset_time(words, e.char_offset), duration)
        cues.append(Cue(t=t, kind=CueKind.DOODLE,
                        payload={"value": e.payload, "hold": doodle_hold_s}))
    for e in script.scribble_events():
        t = clamp(char_offset_time(words, e.char_offset), duration)
        cues.append(Cue(t=t, kind=CueKind.SCRIBBLE,
                        payload={"value": e.payload, "hold": doodle_hold_s}))

    # ---- 4. payoff: the deadpan conclusion (noise or signal — no stamp)
    cues.append(Cue(t=payoff_t, kind=CueKind.CONCLUSION, fallback=payoff_fallback,
                    payload={"text": script.conclusion, "until": duration}))

    cues.sort(key=lambda c: c.t)
    return cues


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
    TagType.ASSET: CueKind.ASSET,
    TagType.DOODLE: CueKind.DOODLE,
    TagType.SCRIBBLE: CueKind.SCRIBBLE,
}

# cue kinds that claim a visual segment on the LONG timeline (the base
# frame). DOODLE/SCRIBBLE are overlays; SOUND is audio — none claim a cut.
VISUAL_CUE_KINDS = (CueKind.CLIP, CueKind.IMG, CueKind.MEME, CueKind.CHART,
                    CueKind.FILING, CueKind.SCREENGRAB, CueKind.ASSET)

# how long a hand-drawn overlay stays on screen before it lifts off
DOODLE_HOLD_S = 2.0


def build_long_timeline(
    script: LongScript,
    words: list[WordTimestamp],
    duration: float,
) -> list[Cue]:
    """Resolve each TagEvent's clean-text char offset to its spoken time, so
    the ironic cut lands on the exact word it undercuts."""
    cues: list[Cue] = []
    for idx, e in enumerate(script.events):
        t = clamp(char_offset_time(words, e.char_offset), duration)
        kind = _TAG_TO_KIND[e.type]
        payload = {"order": idx, "value": e.payload, "tag": e.type.value}
        if kind is CueKind.CHART and e.style:
            payload["style"] = e.style
        if kind is CueKind.SCRIBBLE:
            payload["hold"] = DOODLE_HOLD_S
        elif kind is CueKind.DOODLE:
            payload["hold"] = DOODLE_HOLD_S
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

# how long each visual kind holds before cutting back (a meme is a beat,
# a clip is a thought)
DEFAULT_HOLDS = {
    CueKind.CLIP: 3.0,
    CueKind.IMG: 2.8,
    CueKind.CHART: 3.0,
    CueKind.FILING: 2.8,
    CueKind.SCREENGRAB: 3.0,
    CueKind.ASSET: 3.0,
    CueKind.MEME: 1.8,
}


def _diversify_fillers(segments: list["Segment"]) -> None:
    """Number the fillers sequentially (payload['variant']). The renderer
    spreads that index across a wide pool of DESIGNED backdrops, so a run of
    filler beats reads as motion through a deck — and because consecutive
    fillers get consecutive indices they can never land on the same backdrop.
    LONG_FILLER_LOOKS is the minimum distinct looks the renderer guarantees."""
    counter = 0
    for seg in segments:
        if seg.kind != "filler":
            continue
        seg.payload["variant"] = counter
        counter += 1


def plan_long_segments(
    cues: list[Cue],
    duration: float,
    *,
    min_cut_s: float = 1.5,
    max_cut_s: float = 3.0,
    holds: dict | None = None,
) -> tuple[list[Segment], list[str]]:
    """Tile [0, duration] with fast jump-cut segments (~1.5–3s).

    Visual cues claim a segment starting exactly at their anchor time; the
    gaps between them are subdivided into filler cuts no longer than
    `max_cut_s`. Returns (segments, warnings). Invariant: segments tile
    the full duration with no gaps or overlaps.
    """
    holds = {**DEFAULT_HOLDS, **(holds or {})}
    warnings: list[str] = []
    visual = [c for c in cues if c.kind in VISUAL_CUE_KINDS]
    visual.sort(key=lambda c: c.t)

    # drop cues that would produce sub-minimum segments (stacked tags)
    pruned: list[Cue] = []
    for c in visual:
        if c.t >= duration - MIN_SEGMENT_S:
            warnings.append(f"visual cue at {c.t:.2f}s is too close to the end — dropped")
            continue
        if pruned and c.t - pruned[-1].t < MIN_SEGMENT_S:
            warnings.append(
                f"visual cues stacked at {pruned[-1].t:.2f}s/{c.t:.2f}s — kept the later one"
            )
            pruned.pop()
        pruned.append(c)

    segments: list[Segment] = []
    filler_i = 0

    def add_filler(a: float, b: float) -> None:
        nonlocal filler_i
        gap = b - a
        if gap <= 0:
            return
        if gap < MIN_SEGMENT_S and segments:
            segments[-1].end = b  # absorb slivers into the previous cut
            return
        pieces = max(1, math.ceil(gap / max_cut_s))
        # avoid machine-gun cuts: don't create pieces shorter than min_cut
        # unless the gap itself is short
        while pieces > 1 and gap / pieces < min_cut_s:
            pieces -= 1
        step = gap / pieces
        for i in range(pieces):
            segments.append(Segment(
                start=a + i * step,
                end=b if i == pieces - 1 else a + (i + 1) * step,
                kind="filler",
                payload={"variant": filler_i % 4},
            ))
            filler_i += 1

    cursor = 0.0
    for i, c in enumerate(pruned):
        add_filler(cursor, c.t)
        next_t = pruned[i + 1].t if i + 1 < len(pruned) else duration
        hold = holds.get(c.kind, 3.0)
        end = min(c.t + hold, next_t, duration)
        segments.append(Segment(start=c.t, end=end, kind=c.kind.value,
                                payload=dict(c.payload)))
        cursor = end
    add_filler(cursor, duration)

    # ---- scene-variety pass (§editing) -------------------------------------
    # Give every filler a DESIGNED backdrop family that differs from its
    # neighbour, so a run of filler cuts (a long gap with no assigned media)
    # never reads as the same bare frame on repeat. Real media cues keep
    # their own type. Adjacent same-TYPE real cuts are flagged (rare — they
    # only happen when the director stacks two of a kind back-to-back).
    _diversify_fillers(segments)
    for a, b in zip(segments, segments[1:]):
        if a.kind == b.kind and a.kind != "filler":
            warnings.append(
                f"adjacent {a.kind} cuts at {a.start:.2f}s/{b.start:.2f}s "
                f"— same visual type back-to-back"
            )

    # tiling invariant — fail loudly in dev rather than desync audio/video
    eps = 1e-6
    assert segments, "segment plan must not be empty"
    assert abs(segments[0].start) < eps and abs(segments[-1].end - duration) < eps
    for a, b in zip(segments, segments[1:]):
        assert abs(a.end - b.start) < eps, "segments must tile without gaps"
    return segments, warnings
