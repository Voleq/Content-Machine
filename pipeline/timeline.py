"""The master clock (§2.1, §6): resolve every visual/audio event to an
absolute time derived from REAL audio word timestamps.

Pure logic, no I/O, no subprocesses. Renderers consume the cue lists and
segment plans produced here and never invent their own timings.

Anchor resolution rules:
  * anchor word/phrase  -> start time of the first case/punctuation-
                           insensitive match in the word stream
  * anchor not found    -> proportional fallback position, cue flagged
                           `fallback=True` (callers log the warning)
  * "end_minus_N"       -> duration - N (clamped)
  * LONG char_offset    -> the word containing that clean-text offset,
                           else the first word starting after it
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from pipeline.models import (
    Cue,
    CueKind,
    HighlightDirection,
    LongScript,
    ShortScript,
    StampDirection,
    TagType,
    Verdict,
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
    """Time of the word whose clean-text span contains `offset` (§5.3)."""
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


def proportional_fallback(line_index: int, n_lines: int, duration: float) -> float:
    """Position for a highlight whose anchor word was not found."""
    return duration * (line_index + 1) / (n_lines + 1)


# --------------------------------------------------------------------------
# SHORT scene timeline (§7.1).
# --------------------------------------------------------------------------


def _first_sentence_end(words: list[WordTimestamp], duration: float) -> float:
    for w in words:
        if w.word.rstrip("\"'”’)").endswith((".", "!", "?", "…")):
            return w.end
    return min(2.5, duration * 0.15)


def build_short_timeline(
    script: ShortScript,
    words: list[WordTimestamp],
    duration: float,
    *,
    whip_pan_s: float = 0.45,
    data_end_margin_s: float = 1.0,
    cta_lead_s: float = 1.6,
    stamp_fallback_from_end_s: float = 3.0,
) -> list[Cue]:
    """Every SHORT scene cue, positioned off the spoken audio. No number in
    the renderer may override these."""
    cues: list[Cue] = []

    # 1. cold-open hook at t=0, simultaneous with the first spoken word
    whip_t = clamp(_first_sentence_end(words, duration), duration)
    cues.append(Cue(t=0.0, kind=CueKind.HOOK,
                    payload={"text": script.hook_text, "until": whip_t}))

    # 2. whip-pan punctuation right after the hook sentence lands
    cues.append(Cue(t=whip_t, kind=CueKind.WHIP_PAN, payload={"duration": whip_pan_s}))

    # 5/6. stamp climax — resolve before the data zone so typing can respect it
    stamp = script.stamps[0]
    stamp_fallback = False
    end_off = stamp.end_offset()
    if end_off is not None:
        stamp_t = duration - end_off
    else:
        anchored = find_anchor_time(words, stamp.anchor)
        stamp_fallback = anchored is None
        stamp_t = anchored if anchored is not None else duration - stamp_fallback_from_end_s
    stamp_t = clamp(stamp_t, duration)
    if stamp_t <= whip_t:  # degenerate tiny-duration smoke renders
        stamp_t = clamp(whip_t + 0.6 * (duration - whip_t), duration)

    # 4. typewriter data block, paced across the zone between the whip-pan
    #    and the stamp
    data_start = whip_t + whip_pan_s
    data_end = max(stamp_t - data_end_margin_s, data_start + 0.5)
    n = len(script.data_block)
    slot = (data_end - data_start) / n
    line_times = [data_start + i * slot for i in range(n)]

    # the highlight fires ON the anchor word (§7.1) — if the voice reaches
    # that word before the even pacing would have typed its row, pull the
    # schedule forward so the row is on screen in time
    for h in script.highlights:
        anchored = find_anchor_time(words, h.anchor_word)
        if anchored is None:
            continue
        idx = h.line_index
        target = max(anchored - 0.35, data_start + 0.1 * (idx + 1))
        if target < line_times[idx]:
            for j in range(idx + 1):
                frac = j / idx if idx else 1.0
                line_times[j] = data_start + (target - data_start) * frac
            remaining = n - idx - 1
            if remaining > 0:
                step = (data_end - target) / (remaining + 1)
                for k in range(remaining):
                    line_times[idx + 1 + k] = target + step * (k + 1)
    for j in range(1, n):  # keep strictly ordered whatever the pulls did
        line_times[j] = max(line_times[j], line_times[j - 1] + 0.15)

    for i, line in enumerate(script.data_block):
        cues.append(Cue(
            t=clamp(min(line_times[i], data_end), duration),
            kind=CueKind.DATA_LINE,
            payload={
                "index": i,
                "text": line,
                "type_seconds": round(min(1.1, slot * 0.55), 3),
            },
        ))

    # 5. highlighter fired at the anchor word (or proportional fallback)
    for h in script.highlights:
        anchored = find_anchor_time(words, h.anchor_word)
        fb = anchored is None
        t = anchored if anchored is not None else proportional_fallback(
            h.line_index, n, duration
        )
        # never before its own line has typed in
        t = max(t, line_times[h.line_index] + 0.2)
        cues.append(Cue(
            t=clamp(t, duration),
            kind=CueKind.HIGHLIGHT,
            fallback=fb,
            payload={
                "line_index": h.line_index,
                "color": h.color.value,
                "anchor_word": h.anchor_word,
            },
        ))

    cues.append(Cue(
        t=stamp_t, kind=CueKind.STAMP, fallback=stamp_fallback,
        payload={"label": stamp.label.value},
    ))

    # 7. loop/re-hook CTA
    cues.append(Cue(
        t=clamp(duration - cta_lead_s, duration),
        kind=CueKind.CTA,
        payload={"text": script.cta_text},
    ))

    cues.sort(key=lambda c: c.t)
    return cues


# --------------------------------------------------------------------------
# LONG tag timeline + jump-cut segment plan (§7.2).
# --------------------------------------------------------------------------

_TAG_TO_KIND = {
    TagType.BROLL: CueKind.BROLL,
    TagType.SHOW_REFINITIV: CueKind.REFINITIV,
    TagType.SOUND: CueKind.SOUND,
    TagType.STAMP: CueKind.STAMP,
}


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
        payload: dict = {"order": idx}
        if e.type is TagType.BROLL:
            payload["key"] = e.payload
        elif e.type is TagType.SHOW_REFINITIV:
            payload["file"] = e.payload
        elif e.type is TagType.SOUND:
            payload["key"] = e.payload
        elif e.type is TagType.STAMP:
            if e.payload not in Verdict.__members__:
                continue  # validator already warned; never fatal
            payload["label"] = e.payload
        cues.append(Cue(t=t, kind=kind, payload=payload))
    cues.sort(key=lambda c: (c.t, c.payload.get("order", 0)))
    return cues


@dataclass
class Segment:
    start: float
    end: float
    kind: str          # "broll" | "refinitiv" | "filler"
    payload: dict = field(default_factory=dict)

    @property
    def length(self) -> float:
        return self.end - self.start


MIN_SEGMENT_S = 0.25


def plan_long_segments(
    cues: list[Cue],
    duration: float,
    *,
    min_cut_s: float = 3.0,
    max_cut_s: float = 5.0,
    broll_hold_s: float = 5.0,
    refinitiv_hold_s: float = 3.5,
) -> tuple[list[Segment], list[str]]:
    """Tile [0, duration] with jump-cut segments.

    Visual cues (broll / refinitiv) claim a segment starting exactly at
    their anchor time; the gaps between them are subdivided into filler
    cuts no longer than `max_cut_s` (the 3–5s jump-cut rhythm). Returns
    (segments, warnings). Invariant: segments tile the full duration with
    no gaps or overlaps.
    """
    warnings: list[str] = []
    visual = [c for c in cues if c.kind in (CueKind.BROLL, CueKind.REFINITIV)]
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
        hold = broll_hold_s if c.kind is CueKind.BROLL else refinitiv_hold_s
        end = min(c.t + hold, next_t, duration)
        seg_kind = "broll" if c.kind is CueKind.BROLL else "refinitiv"
        segments.append(Segment(start=c.t, end=end, kind=seg_kind, payload=dict(c.payload)))
        cursor = end
    add_filler(cursor, duration)

    # tiling invariant — fail loudly in dev rather than desync audio/video
    eps = 1e-6
    assert segments, "segment plan must not be empty"
    assert abs(segments[0].start) < eps and abs(segments[-1].end - duration) < eps
    for a, b in zip(segments, segments[1:]):
        assert abs(a.end - b.start) < eps, "segments must tile without gaps"
    return segments, warnings
