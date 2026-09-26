"""Rhythm: the properties of a script that retention actually measures.

The approval card carries fact-checks, type budgets, reach and cost. Every
one of those is about whether the video is *true* or *affordable*. None of
them is about whether it is watchable, and the thing retention measures is
watchability.

Four checks live here, and all four are computable before a single paid call:

* :func:`pacing_report` — words per second, sentence lengths, how long before
  the first figure lands and the longest stretch carrying none. A writer
  cannot feel any of these by reading their own draft.
* :func:`dead_air` — stretches where the audio runs and the picture holds
  still, read off the render manifest. Offline, no retention needed, and it
  works on a video that has never shipped.
* :func:`open_loops` — a question posed early and answered later is the
  mechanic that carries a viewer past the first third. Nothing asked for one.
* :func:`title_coherence` — a title promising one thing over an opener
  delivering another is the textbook thirty-second drop.

The thresholds here are judgements, the same as the voice bible's are, and
they are named constants for the same reason: so that
:func:`pipeline.retention_lines.rule_evidence` can eventually argue with
them.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from config import Settings
from pipeline.gates import SPOKEN_WPS, Finding

log = logging.getLogger(__name__)

# A figure is what this channel is for. Longer than this at the top without
# one and the viewer has been asked to take an argument on trust.
FIRST_FIGURE_LIMIT_S = 12.0

# The longest the narration should run without a number in it. Generous:
# the turn, the confession and the framing are all figure-free by design.
FIGURE_GAP_LIMIT_S = 30.0

# Mean sentence length, in words. Above the ceiling the read is dense; below
# the floor it is staccato. Both are legitimate choices and neither is a
# block — the point is that the writer is told which one they made.
SENTENCE_WORDS_CEILING = 24.0
SENTENCE_WORDS_FLOOR = 8.0

# How long the picture may hold still under running narration. A shot with a
# host in it is alive at fifteen seconds; a static data plate is a held
# photograph at eight, which is the number the renderer's own pacing block
# already uses for its ceiling.
STILL_LIMIT_S = 8.0

# Seconds from the top within which an open loop has to be posed, if it is
# going to do the job of carrying someone past the opening.
LOOP_WINDOW_S = 20.0

_FIGURE_RE = re.compile(r"\d")
_WORD_RE = re.compile(r"[a-z][a-z'-]+")

# Words too common to mean anything when a title and an opener share them.
_STOP = frozenset("""
a an the and or but if then than that this these those is are was were be been
being it its of to in on at by for with from as into over under about after
before between out up down off again once here there all any both each few
more most other some such no nor not only own same so too very can will just
should now what which who whom when where why how i you he she we they them
his her their our your my me him us do does did doing done have has had having
""".split())


def _content_words(text: str) -> set[str]:
    return {w for w in _WORD_RE.findall(text.lower()) if w not in _STOP}


# --------------------------------------------------------------------------
# Pacing (31).
# --------------------------------------------------------------------------


@dataclass
class Pacing:
    """What the rhythm of a script looks like, in numbers."""

    seconds: float = 0.0
    words: int = 0
    sentences: int = 0
    mean_sentence_words: float = 0.0
    longest_sentence_words: int = 0
    first_figure_s: float | None = None      # None: no figure is ever spoken
    longest_figure_gap_s: float = 0.0
    figure_gap_opening: str = ""

    @property
    def words_per_second(self) -> float:
        return (self.words / self.seconds) if self.seconds else 0.0

    def line(self) -> str:
        first = ("never" if self.first_figure_s is None
                 else f"{self.first_figure_s:.0f}s")
        return (f"Pacing: {self.seconds:.0f}s, {self.sentences} sentences, "
                f"{self.mean_sentence_words:.0f} words each on average "
                f"(longest {self.longest_sentence_words}); first figure at "
                f"{first}; longest stretch with no figure "
                f"{self.longest_figure_gap_s:.0f}s")


def measure_pacing(narration: str) -> Pacing:
    """The rhythm of a script, from the script alone.

    Seconds are derived from the word count at the read's own rate, not from
    an audio file, because this runs before any audio exists — which is the
    entire point of measuring it here.
    """
    from pipeline.corpus import sentences

    said = sentences(narration)
    words = narration.split()
    if not words:
        return Pacing()
    lengths = [len(s.split()) for s in said] or [0]
    pacing = Pacing(
        seconds=len(words) / SPOKEN_WPS,
        words=len(words),
        sentences=len(said),
        mean_sentence_words=sum(lengths) / len(lengths),
        longest_sentence_words=max(lengths),
    )
    # WORD BY WORD, not sentence by sentence. A figure forty words into a
    # sixty-word sentence lands forty words in; attributing it to the
    # sentence's own start reports an opening that was never spoken — and a
    # long unbroken sentence is exactly the shape this check exists to catch.
    clock = 0.0
    gap_start = 0.0
    gap_opening: list[str] = []
    for word in words:
        if _FIGURE_RE.search(word):
            if pacing.first_figure_s is None:
                pacing.first_figure_s = clock
            if clock - gap_start > pacing.longest_figure_gap_s:
                pacing.longest_figure_gap_s = clock - gap_start
                pacing.figure_gap_opening = " ".join(gap_opening[:12])
            gap_start = clock + 1 / SPOKEN_WPS
            gap_opening = []
        elif len(gap_opening) < 12:
            gap_opening.append(word)
        clock += 1 / SPOKEN_WPS
    if clock - gap_start > pacing.longest_figure_gap_s:
        pacing.longest_figure_gap_s = clock - gap_start
        pacing.figure_gap_opening = " ".join(gap_opening[:12])
    return pacing


def pacing_report(script) -> list[Finding]:
    """Rhythm, as notes on the approval card. Never blocks — a slow opening
    is a choice, and a linter that blocked one would be writing the video."""
    from pipeline.gates import delivery_text

    narration = delivery_text(script)
    pacing = measure_pacing(narration)
    if not pacing.words:
        return []
    out = [Finding("pacing", "warn", pacing.line())]
    if pacing.first_figure_s is None:
        out.append(Finding("pacing", "warn",
                           "no figure is spoken anywhere in this script — on "
                           "a channel whose whole claim is the numbers, that "
                           "is worth being deliberate about"))
    elif pacing.first_figure_s > FIRST_FIGURE_LIMIT_S:
        out.append(Finding(
            "pacing", "warn",
            f"the first figure lands at {pacing.first_figure_s:.0f}s — "
            f"{FIRST_FIGURE_LIMIT_S:.0f}s is about as long as an opening can "
            f"ask someone to take on trust"))
    if pacing.longest_figure_gap_s > FIGURE_GAP_LIMIT_S:
        out.append(Finding(
            "pacing", "warn",
            f"{pacing.longest_figure_gap_s:.0f}s of narration with no figure "
            f"in it", excerpt=pacing.figure_gap_opening[:90]))
    if pacing.mean_sentence_words > SENTENCE_WORDS_CEILING:
        out.append(Finding(
            "pacing", "warn",
            f"sentences average {pacing.mean_sentence_words:.0f} words — this "
            f"is a dense read, and it will sound like one"))
    elif pacing.mean_sentence_words < SENTENCE_WORDS_FLOOR:
        out.append(Finding(
            "pacing", "warn",
            f"sentences average {pacing.mean_sentence_words:.0f} words — this "
            f"is a staccato read, which works for a short and rarely for a long"))
    return out


# --------------------------------------------------------------------------
# Dead air (32).
# --------------------------------------------------------------------------


@dataclass
class Still:
    """A stretch where the audio runs and the picture does not change."""

    start_s: float
    end_s: float
    what: str = ""

    @property
    def seconds(self) -> float:
        return max(0.0, self.end_s - self.start_s)


def segment_label(seg: dict) -> str:
    """A LONG segment as the operator would name it: its kind, and what it
    shows when the record says (`host`, `img: ...`, `plate: ...`)."""
    kind = str(seg.get("kind") or "segment")
    what = seg.get("value") or seg.get("layout")
    return f"{kind}: {what}" if what else kind


def change_times(manifest: dict) -> list[tuple[float, str]]:
    """Every moment the picture changes, from either renderer's manifest.

    The SHORT records shots with their own bounds; the LONG records its cut
    as `segments` and its overlays as layers with `t_start`/`t_end`, and a
    layer appearing or leaving is a change in the picture as surely as a cut
    is. All of it is folded into one sorted list so the caller never has to
    know which engine ran.

    Reading only the layers is how a long cut every eleven seconds came out
    as "178 s still": the segments are the cut, and they were never read. And
    the SHORT's `layers` is a count, not a list, which made every short a
    TypeError here.
    """
    events: list[tuple[float, str]] = []
    for shot in manifest.get("shots") or []:
        if isinstance(shot, dict) and shot.get("start_s") is not None:
            events.append((float(shot["start_s"]),
                           str(shot.get("plate") or shot.get("id") or "shot")))
    segments = manifest.get("segments")
    for seg in segments if isinstance(segments, list) else []:
        if isinstance(seg, dict) and isinstance(seg.get("start"), (int, float)):
            events.append((float(seg["start"]), segment_label(seg)))
    layers = manifest.get("layers")
    for layer in layers if isinstance(layers, list) else []:
        if not isinstance(layer, dict):
            continue
        name = str(layer.get("name", "layer"))
        for key in ("t_start", "t_end"):
            if isinstance(layer.get(key), (int, float)):
                events.append((float(layer[key]), name))
    return sorted(events)


def dead_air(manifest: dict, *, limit_s: float = STILL_LIMIT_S) -> list[Still]:
    """Stretches of held picture longer than the limit, longest first.

    Needs the duration to judge the tail: a last shot that runs to the end of
    the video is as still as one in the middle, and it is the one nobody
    notices because no cut follows it.
    """
    duration = float(manifest.get("duration_s")
                     or manifest.get("duration") or 0.0)
    events = change_times(manifest)
    if not events:
        return []
    stills: list[Still] = []
    for i, (at, what) in enumerate(events):
        end = events[i + 1][0] if i + 1 < len(events) else duration
        if end - at > limit_s:
            stills.append(Still(start_s=at, end_s=end, what=what))
    return sorted(stills, key=lambda s: s.seconds, reverse=True)


def dead_air_report(manifest: dict, *,
                    limit_s: float = STILL_LIMIT_S) -> str:
    stills = dead_air(manifest, limit_s=limit_s)
    if not change_times(manifest):
        return ("This manifest records no shot or layer timings, so how long "
                "the picture holds still cannot be read off it.")
    if not stills:
        return (f"🎞 No stretch holds still longer than {limit_s:.0f}s. "
                f"The picture keeps moving.")
    lines = [f"🎞 Held picture over {limit_s:.0f}s — {len(stills)} stretch(es)"]
    for still in stills[:6]:
        lines.append(f"  {still.start_s:6.1f}s  {still.seconds:4.1f}s still  "
                     f"{still.what}")
    lines.append("  These are where people leave, and none of them costs a "
                 "paid call to fix.")
    return "\n".join(lines)


def frame_holds_report(manifest: dict) -> str:
    """The pictures the finished SHORT held past its ceiling, or "".

    Read off the frames at render time (`render_short.held_over_ceiling`),
    so this is what the encode did rather than what the cut planned. Empty
    when nothing held, and for a manifest written before it was measured; a
    render whose frames could not be read says so rather than passing.
    """
    pacing = manifest.get("pacing")
    if not isinstance(pacing, dict) or "held_over_ceiling" not in pacing:
        return ""
    held = pacing["held_over_ceiling"]
    ceiling = float(pacing.get("hold_ceiling_s") or 0.0)
    if held is None:
        return (f"🎞 The frames could not be read back, so the "
                f"{ceiling:.0f}s hold ceiling went unchecked on this render.")
    if not held:
        return ""
    lines = [f"🎞 Measured on the frames, {len(held)} picture(s) hold past "
             f"the {ceiling:.0f}s ceiling:"]
    for h in held[:4]:
        lines.append(f"  {h.get('shot') or 'the cut'} holds "
                     f"{float(h['held_s']):.1f}s from "
                     f"{float(h['start_s']):.1f}s")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Open loops (30).
# --------------------------------------------------------------------------


@dataclass
class Loop:
    """A question posed early, and whether the script comes back to it."""

    question: str
    asked_s: float
    closed_s: float | None = None
    shared: list[str] = field(default_factory=list)

    @property
    def closed(self) -> bool:
        return self.closed_s is not None


def open_loops(narration: str, *,
               window_s: float = LOOP_WINDOW_S) -> list[Loop]:
    """Questions asked in the opening, and where each is picked back up.

    "Picked back up" is content-word recurrence, not comprehension: a
    question about inventory that is never followed by a sentence about
    inventory was not answered, whatever else the script did. Crude, and
    crude in the safe direction — it under-reports a loop closed in different
    words rather than inventing one that was never closed.
    """
    from pipeline.corpus import sentences

    said = sentences(narration)
    loops: list[Loop] = []
    clock = 0.0
    spans: list[tuple[float, str]] = []
    for one in said:
        spans.append((clock, one))
        clock += len(one.split()) / SPOKEN_WPS
    for i, (at, text) in enumerate(spans):
        if at > window_s or "?" not in text:
            continue
        asked = _content_words(text)
        if not asked:
            continue
        loop = Loop(question=text.strip(), asked_s=at)
        for later_at, later in spans[i + 1:]:
            shared = asked & _content_words(later)
            if len(shared) >= 2:
                loop.closed_s = later_at
                loop.shared = sorted(shared)
                break
        loops.append(loop)
    return loops


def loop_check(script) -> list[Finding]:
    """Notes on the opening's open loops. Warns, never blocks."""
    from pipeline.gates import delivery_text

    narration = delivery_text(script)
    if not narration.split():
        return []
    loops = open_loops(narration)
    if not loops:
        return [Finding(
            "loops", "warn",
            f"no question is asked in the first {LOOP_WINDOW_S:.0f}s. An "
            f"open loop is the mechanic that carries someone past the "
            f"opening, and this script opens without one")]
    out = []
    for loop in loops:
        if loop.closed:
            continue
        out.append(Finding(
            "loops", "warn",
            "a question is asked at the top and never picked back up — an "
            "open loop that stays open is a promise the video breaks",
            excerpt=loop.question[:90]))
    return out


# --------------------------------------------------------------------------
# Title and opener (35).
# --------------------------------------------------------------------------


def title_coherence(title: str, hook: str) -> list[Finding]:
    """Does the first thing anyone hears deliver what the title promised?

    Shared content words, which is a low bar deliberately: the check exists
    to catch a title written for a different video, not to police phrasing.
    """
    want = _content_words(title)
    got = _content_words(hook)
    if not want or not got:
        return []
    shared = want & got
    if shared:
        return []
    return [Finding(
        "title", "warn",
        f"the title and the opening line share no subject — a viewer "
        f"arriving on “{title.strip()[:60]}” hears something else first",
        excerpt=hook.strip()[:90])]


def check_title_package(script, settings: Settings) -> list[Finding]:
    """The coherence check against the package the uploader would send."""
    from pipeline.corpus import sentences
    from pipeline.gates import delivery_text

    hook = getattr(script, "hook_text", "") or ""
    if not hook:
        said = sentences(delivery_text(script))
        hook = said[0] if said else ""
    try:
        from pipeline.publish import build_package

        titles = build_package(script, settings,
                               ticker=getattr(script, "ticker", "")).titles
    except Exception as e:  # noqa: BLE001 — a missing package is not a gate
        log.debug("title check: no package (%s)", e)
        return []
    if not titles or not hook:
        return []
    # The first title is the one the uploader defaults to.
    return title_coherence(titles[0], hook)
