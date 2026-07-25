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


# Per-beat layout variants shipped by the design kit. "a" is the original
# GET-GO layout; the kit adds b..e per beat. One is picked per short from the
# script hash, so consecutive daily shorts do not repeat a layout — and the
# same script always renders the same way.
SHORT_BEAT_VARIANTS: dict[str, tuple[str, ...]] = {
    "hook": ("a", "b", "c", "d", "e"),
    "why": ("a", "b", "c", "d"),
    "gutcheck": ("a", "b", "c", "d"),
    "payoff": ("a", "b", "c", "d", "e"),
}

# A short is faster than long-form but must never machine-gun: the beats that
# carry data have to survive long enough to be read.
SHORT_MIN_READABLE_S = 4.5   # numbers sheet and the cheap-or-trap card
HOST_BOOKEND_S = (3.0, 5.0)  # Dennis opens and closes on camera


def pick_beat_variant(beat: str, script_sha: str) -> str:
    """Deterministically choose this short's layout for one beat."""
    options = SHORT_BEAT_VARIANTS[beat]
    digest = hashlib.sha256(f"{script_sha}|{beat}".encode()).hexdigest()
    return options[int(digest[:8], 16) % len(options)]


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
    sha = script.content_sha()
    variants = {b: pick_beat_variant(b, sha) for b in SHORT_BEAT_VARIANTS}

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

    # ---- the CHEAP-OR-TRAP beat sits between the numbers and the payoff,
    #      and is held long enough to read. It only earns its own slot when
    #      there is room for it; otherwise it rides on the numbers sheet.
    trap_t: float | None = None
    if script.cheap_or_trap:
        anchored = find_anchor_time(words, " ".join(script.cheap_or_trap.split()[:3]))
        candidate = anchored if anchored is not None else payoff_t - SHORT_MIN_READABLE_S
        window_open = gut_t + SHORT_MIN_READABLE_S
        if payoff_t - window_open >= 1.0:
            trap_t = clamp(min(max(candidate, window_open), payoff_t - 0.5), duration)

    # ---- 0. host bookend: Dennis opens on camera before the hook card lands
    host_open_end = clamp(min(max(hook_end, HOST_BOOKEND_S[0]), HOST_BOOKEND_S[1]),
                          duration)
    cues.append(Cue(t=0.0, kind=CueKind.HOST_OPEN,
                    payload={"until": host_open_end, "text": script.hook_text,
                             "variant": "open"}))

    # ---- 1. cold open: hook card over the branded chart, from t=0
    cues.append(Cue(t=0.0, kind=CueKind.HOOK,
                    payload={"text": script.hook_text, "until": hook_end,
                             "variant": variants["hook"]}))

    # ---- beat-transition stingers (cuts between the fixed beats)
    beats = [("why", hook_end), ("gut", gut_t)]
    if trap_t is not None:
        beats.append(("trap", trap_t))
    beats.append(("payoff", payoff_t))
    for name, t in beats:
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
                     "until": gut_t, "variant": variants["why"]},
        ))

    # ---- 3. gut check: the numbers sheet slides in, rows type on
    cues.append(Cue(t=gut_t, kind=CueKind.NUMBERS,
                    payload={"rows": len(script.numbers), "until": duration,
                             "variant": variants["gutcheck"]}))
    n_rows = len(script.numbers)
    rows_start = gut_t + 0.35
    # The sheet must finish typing before the beat that follows it, so the
    # last row is readable rather than still animating when the frame cuts.
    rows_deadline = trap_t if trap_t is not None else payoff_t
    rows_end = max(rows_deadline - 0.5, rows_start + 0.5)
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

    # ---- 4. cheap or trap: the value-trap read, held long enough to land
    if trap_t is not None:
        cues.append(Cue(t=trap_t, kind=CueKind.CHEAP_OR_TRAP,
                        payload={"text": script.cheap_or_trap,
                                 "until": clamp(max(trap_t + SHORT_MIN_READABLE_S,
                                                    payoff_t), duration)}))

    # ---- 5. payoff: the deadpan conclusion (noise or signal — no stamp)
    cues.append(Cue(t=payoff_t, kind=CueKind.CONCLUSION, fallback=payoff_fallback,
                    payload={"text": script.conclusion, "until": duration,
                             "variant": variants["payoff"]}))

    # ---- 6. host bookend: Dennis closes on camera over the last words
    host_close_len = min(max(duration - payoff_t, HOST_BOOKEND_S[0]), HOST_BOOKEND_S[1])
    cues.append(Cue(t=clamp(duration - host_close_len, duration),
                    kind=CueKind.HOST_CLOSE,
                    payload={"until": duration, "text": script.conclusion,
                             "variant": "close"}))

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

# How long each visual kind holds before cutting back to the host. These are
# roughly double the old values: the show is a host talking who cuts away to
# evidence, and evidence the viewer cannot finish reading is worse than no
# evidence at all. A meme is still a beat; a diagram is a paragraph.
DEFAULT_HOLDS = {
    CueKind.CLIP: 5.0,
    CueKind.IMG: 5.0,
    CueKind.CHART: 7.0,
    CueKind.FILING: 6.0,
    CueKind.SCREENGRAB: 6.0,
    CueKind.ASSET: 8.0,
    CueKind.MEME: 3.0,
}

# Kinds carrying data a viewer has to READ rather than glance at. These never
# cut early: a later visual is pushed back rather than truncating one of
# these, and the voice-over simply keeps running underneath.
READABLE_KINDS = (CueKind.CHART, CueKind.FILING, CueKind.SCREENGRAB, CueKind.ASSET)
MIN_READABLE_S = 5.0

# Designed panels sit BESIDE Dennis (the two-shot); real photographs,
# footage, filings and memes take the whole frame raw.
TWO_SHOT_KINDS = (CueKind.CHART, CueKind.ASSET)

# Dennis bookends every chapter: this much host on each side of a chapter
# boundary is reserved, so a chapter always opens and closes on his face.
CHAPTER_HOST_S = 2.5

# The shortest host beat worth cutting to. A third of a second of Dennis
# between two cutaways is a blink, not a beat — below this the evidence
# already on screen simply stays up until the next one is due.
MIN_HOST_BEAT_S = 1.2


def chapter_start_times(chapters: str, duration: float) -> list[float]:
    """Seconds from the `=== CHAPTERS ===` trailer's `mm:ss Title` lines.

    The times are the writer's estimates, not measurements — they are used
    only to reserve a host beat around each boundary, never to place audio.
    Anything unparseable or past the end of the cut is skipped.
    """
    out: list[float] = []
    for line in (chapters or "").splitlines():
        stamp = line.strip().split(" ", 1)[0]
        parts = stamp.split(":")
        if not (2 <= len(parts) <= 3) or not all(p.isdigit() for p in parts):
            continue
        seconds = 0.0
        for p in parts:
            seconds = seconds * 60 + int(p)
        if 0.0 < seconds < duration:
            out.append(seconds)
    return sorted(set(out))


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


def plan_long_segments(
    cues: list[Cue],
    duration: float,
    *,
    holds: dict | None = None,
    chapter_starts: list[float] | None = None,
    min_readable_s: float = MIN_READABLE_S,
    chapter_host_s: float = CHAPTER_HOST_S,
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
    """
    holds = {**DEFAULT_HOLDS, **(holds or {})}
    warnings: list[str] = []
    visual = [c for c in cues if c.kind in VISUAL_CUE_KINDS]
    visual.sort(key=lambda c: c.t)

    # Windows the evidence may not occupy, so each chapter opens and closes
    # on Dennis talking.
    blocked: list[tuple[float, float]] = [
        (max(t - chapter_host_s, 0.0), min(t + chapter_host_s, duration))
        for t in sorted(chapter_starts or []) if 0.0 < t < duration
    ]

    def push_past_chapter_beat(t: float) -> float:
        for a, b in blocked:
            if a <= t < b:
                return b
        return t

    segments: list[Segment] = []
    host_i = 0

    def add_host(a: float, b: float) -> None:
        """One held host beat for the gap — never chopped into filler cuts."""
        nonlocal host_i
        if b - a <= 0:
            return
        if b - a < MIN_HOST_BEAT_S and segments:
            # too short to be a beat: leave the previous visual up instead of
            # blinking to the host and straight back out
            segments[-1].end = b
            return
        segments.append(Segment(start=a, end=b, kind="host",
                                payload={"variant": host_i, "layout": "host-full"}))
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
        hold = holds.get(c.kind, 5.0)
        if c.kind in READABLE_KINDS:
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

    # tiling invariant — fail loudly in dev rather than desync audio/video
    eps = 1e-6
    assert segments, "segment plan must not be empty"
    assert abs(segments[0].start) < eps and abs(segments[-1].end - duration) < eps
    for a, b in zip(segments, segments[1:]):
        assert abs(a.end - b.start) < eps, "segments must tile without gaps"
    return segments, warnings
