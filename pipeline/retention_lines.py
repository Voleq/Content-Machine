"""Retention, located to the sentence instead of the chapter.

:func:`pipeline.youtube.map_retention_to_chapters` answers "which chapter
loses them". A chapter is twenty to ninety seconds long, so the answer points
at a paragraph and shrugs. The writer cannot act on a paragraph.

Everything needed to do better is already on disk and has been all along.
The Analytics API returns rows as a ratio through the video; the render
stores word-level timings, which are the same master clock the visuals are
cut against. Join the two and the answer is the sentence people left on.

That join is the substrate. Four questions become slices of it:

* **The hook bench** — openers ranked by the hold over their own first
  seconds, rather than by the whole video's average.
* **The voice rules on trial** — the linter blocks about twenty seconds with
  no turn in it, caps the direction tags and tracks confessions. Every one of
  those thresholds was a judgement call and none has ever been checked
  against whether it holds anybody. Here each sentence carries its features
  and its hold, so the rules can be asked to justify themselves.
* **Runtime** — hold against duration, per lane. Sixty to seventy-five
  seconds is an assumption in a spec, not a finding.
* **The cut** — retention mapped onto the render manifest's own shot spans,
  so the evidence reaches pacing and not only the outline.

Nothing here is ever fatal. A video with no retention pulled, a workspace
whose words were never written, a manifest from before this existed: each
yields an empty result and a reason, the way every other free source in this
pipeline degrades.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from config import Settings

log = logging.getLogger(__name__)

WORDS_FILE = "words.json"

# A short's opener is judged over this many seconds. Long enough to be a
# sentence or two, short enough to be the decision a viewer actually makes.
HOOK_WINDOW_S = 5.0

# Below this many videos a comparison is arithmetic, not evidence. The same
# floor the chapter-type evidence uses, and for the same reason.
EVIDENCE_FLOOR = 3


# --------------------------------------------------------------------------
# The timings.
# --------------------------------------------------------------------------


@dataclass
class Span:
    """One sentence of narration, and when it is spoken."""

    text: str
    start_s: float
    end_s: float

    @property
    def seconds(self) -> float:
        return max(0.0, self.end_s - self.start_s)


def write_words(words, path: Path) -> Path:
    """Persist the render's word timings beside its other by-products.

    The `.srt` has carried these timings since subtitles existed, but grouped
    into display cues and rounded to the centisecond. This is the same clock
    unrounded, which is what a join against retention wants.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [{"word": w.word, "start": w.start, "end": w.end,
                "char_start": w.char_start, "char_end": w.char_end}
               for w in words]
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def load_words(ws_path: Path) -> list[dict]:
    """The word timings for one workspace, or an empty list."""
    try:
        rows = json.loads((ws_path / WORDS_FILE).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [r for r in rows if isinstance(r, dict) and "start" in r]


_SRT_TIME = re.compile(
    r"(\d{2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*"
    r"(\d{2}):(\d{2}):(\d{2})[,.](\d{1,3})")


def load_cues(ws_path: Path) -> list[Span]:
    """Subtitle cues, as the fallback for a video rendered before words were
    written. Coarser than the words — a cue is a line or two — but it is the
    same clock, so it localises a drop to a line rather than a chapter."""
    try:
        text = next(ws_path.glob("*.srt")).read_text(encoding="utf-8")
    except (StopIteration, OSError):
        return []
    spans: list[Span] = []
    blocks = [b for b in re.split(r"\n\s*\n", text) if b.strip()]
    for block in blocks:
        m = _SRT_TIME.search(block)
        if not m:
            continue
        g = [int(x) for x in m.groups()]
        start = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000.0
        end = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000.0
        body = "\n".join(line for line in block.splitlines()
                         if not _SRT_TIME.search(line)
                         and not line.strip().isdigit())
        if body.strip():
            spans.append(Span(text=" ".join(body.split()),
                              start_s=start, end_s=end))
    return spans


def sentence_spans(narration: str, words: list[dict]) -> list[Span]:
    """Each sentence of the narration, with the seconds it occupies.

    The word timings carry character offsets into the same clean text the
    sentences are split from, so the two line up by construction rather than
    by matching strings — which would fail on the first spelled-out numeral
    the tokenizer normalised.
    """
    from pipeline.corpus import sentences

    if not words or not narration.strip():
        return []
    said = sentences(narration)
    spans: list[Span] = []
    cursor = 0
    for text in said:
        at = narration.find(text, cursor)
        if at < 0:
            continue
        cursor = at + len(text)
        inside = [w for w in words
                  if at <= int(w.get("char_start", -1)) < cursor]
        if not inside:
            continue
        spans.append(Span(text=text,
                          start_s=float(min(w["start"] for w in inside)),
                          end_s=float(max(w["end"] for w in inside))))
    return spans


# --------------------------------------------------------------------------
# The join.
# --------------------------------------------------------------------------


@dataclass
class LineHold:
    """One span of narration with the retention over it."""

    text: str
    start_s: float
    end_s: float
    watch_ratio: float
    drop: float                          # what it lost, start to end

    @property
    def opening(self) -> str:
        words = self.text.split()
        return " ".join(words[:11]) + ("…" if len(words) > 11 else "")


def _rows_of(retention: dict) -> list[dict]:
    rows = (retention or {}).get("rows") or []
    return sorted((r for r in rows
                   if isinstance(r, dict)
                   and isinstance(r.get("elapsed_ratio"), (int, float))
                   and isinstance(r.get("watch_ratio"), (int, float))),
                  key=lambda r: r["elapsed_ratio"])


def hold_over(rows: list[dict], duration_s: float,
              start_s: float, end_s: float) -> tuple[float, float] | None:
    """Average watch ratio across a span, and the drop across it.

    The drop is the number that matters: a span late in a video starts low
    because everything late in a video starts low, and only the slope says
    whether this span is where they went.
    """
    if not rows or duration_s <= 0 or end_s <= start_s:
        return None
    # Half-open, so a shot ending where the next begins does not claim the
    # next one's first row — except at the very end of the video, where a
    # half-open interval would drop the final row from every span there is.
    last = end_s >= duration_s

    def _inside(at: float) -> bool:
        return start_s <= at <= end_s if last else start_s <= at < end_s

    inside = [r for r in rows if _inside(r["elapsed_ratio"] * duration_s)]
    if not inside:
        return None
    ratios = [float(r["watch_ratio"]) for r in inside]
    return sum(ratios) / len(ratios), ratios[0] - ratios[-1]


def line_holds(spans: list[Span], retention: dict,
               duration_s: float) -> list[LineHold]:
    """Every sentence with the retention over it, in spoken order."""
    rows = _rows_of(retention)
    out: list[LineHold] = []
    for span in spans:
        got = hold_over(rows, duration_s, span.start_s, span.end_s)
        if got is None:
            continue
        ratio, drop = got
        out.append(LineHold(text=span.text, start_s=span.start_s,
                            end_s=span.end_s, watch_ratio=ratio, drop=drop))
    return out


def spans_for(settings: Settings, ticker: str, workdate: str,
              narration: str = "") -> list[Span]:
    """The best timing available for one workspace: words, else cues."""
    ws_path = settings.workspace_dir / ticker.upper() / workdate
    words = load_words(ws_path)
    if words and narration:
        spans = sentence_spans(narration, words)
        if spans:
            return spans
    return load_cues(ws_path)


def holds_for_video(settings: Settings, record,
                    narration: str = "") -> list[LineHold]:
    """The sentence-level holds for one published video, or nothing."""
    if not record.retention or record.duration_s <= 0:
        return []
    spans = spans_for(settings, record.ticker, record.workdate, narration)
    return line_holds(spans, record.retention, record.duration_s)


def worst_lines(holds: list[LineHold], n: int = 5) -> list[LineHold]:
    """The steepest drops, worst first. Where they actually left."""
    return sorted(holds, key=lambda h: h.drop, reverse=True)[:n]


def line_report(holds: list[LineHold], n: int = 6) -> str:
    if not holds:
        return ("No sentence-level retention yet — either the video has no "
                "retention pulled, or it was rendered before the word timings "
                "were written beside it.")
        # Both cases are ordinary, and neither is an error.
    lines = ["📉 Where they left, to the sentence"]
    for h in worst_lines(holds, n):
        lines.append(f"  {h.start_s:5.1f}s  −{h.drop * 100:4.1f}pts  "
                     f"(held {h.watch_ratio * 100:.0f}%)  {h.opening}")
    best = max(holds, key=lambda h: h.watch_ratio)
    lines.append(f"  Best held: {best.watch_ratio * 100:.0f}%  {best.opening}")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# The hook bench (07).
# --------------------------------------------------------------------------


@dataclass
class Hook:
    ticker: str
    workdate: str
    text: str
    hold: float                          # over the opening window

    def line(self) -> str:
        return f"  {self.hold * 100:5.1f}%  {self.ticker:<6} {self.text}"


def hook_bench(settings: Settings, *, fmt: str = "short",
               window_s: float = HOOK_WINDOW_S) -> list[Hook]:
    """Every opener that has retention against it, best hold first.

    Scored over the opening window rather than the whole video, because an
    opener's job ends after a few seconds and a short that loses people in
    its last ten does not mean the first line failed.
    """
    from pipeline.corpus import Corpus
    from pipeline.youtube import VideoLog

    corpus = Corpus(settings)
    by_key = {f"{e.ticker}/{e.workdate}/{e.fmt}": e for e in corpus.entries}
    out: list[Hook] = []
    for record in VideoLog(settings).all():
        entry = by_key.get(f"{record.ticker}/{record.workdate}/{fmt}")
        if entry is None or not record.retention or record.duration_s <= 0:
            continue
        got = hold_over(_rows_of(record.retention), record.duration_s,
                        0.0, window_s)
        if got is None or not entry.hook:
            continue
        out.append(Hook(ticker=record.ticker, workdate=record.workdate,
                        text=entry.hook, hold=got[0]))
    return sorted(out, key=lambda h: h.hold, reverse=True)


def hook_bench_text(settings: Settings, *, fmt: str = "short",
                    n: int = 5) -> str:
    bench = hook_bench(settings, fmt=fmt)
    if not bench:
        return ("No openers have retention against them yet. This fills in "
                "as published videos accumulate a day or two of views.")
    lines = [f"🪝 Openers that held, over the first "
             f"{HOOK_WINDOW_S:.0f} seconds ({len(bench)} videos)"]
    lines += [h.line() for h in bench[:n]]
    if len(bench) > n:
        lines.append("  ── worst ──")
        lines += [h.line() for h in bench[-min(2, len(bench) - n):]]
    if len(bench) < EVIDENCE_FLOOR:
        lines.append(f"  Fewer than {EVIDENCE_FLOOR} videos: read this as a "
                     f"list, not as evidence.")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# The voice rules, on trial (29).
# --------------------------------------------------------------------------


@dataclass
class RuleEvidence:
    """One linter rule, and whether the videos agree with it."""

    rule: str
    with_it: float                       # mean hold where the feature is present
    without: float
    n_with: int
    n_without: int

    @property
    def points(self) -> float:
        return (self.with_it - self.without) * 100

    @property
    def verdict(self) -> str:
        if min(self.n_with, self.n_without) < EVIDENCE_FLOOR:
            return "not yet evidence"
        if abs(self.points) < 1.0:
            return "no measurable difference"
        return "holds better" if self.points > 0 else "holds worse"

    def line(self) -> str:
        return (f"  {self.points:+5.1f}pts  {self.rule:<28} "
                f"(n={self.n_with}/{self.n_without})  {self.verdict}")


def _features(text: str) -> dict[str, bool]:
    """What the linter would say about one sentence."""
    from pipeline.gates import _TURN

    low = text.lower()
    return {
        "a turn in the sentence": bool(_TURN.search(text)),
        "a direction tag": bool(re.search(r"\[[a-z ]+\]", text)),
        "a question": "?" in text,
        "a figure spoken": bool(re.search(r"\d", text)),
        "first person": bool(re.search(r"\b(i|we|my|our)\b", low)),
    }


def rule_evidence(settings: Settings) -> list[RuleEvidence]:
    """Each feature the linter cares about, against the hold where it appears.

    Sentence-level and pooled across videos. Deliberately crude: it compares
    means and reports its own denominators rather than claiming a model. The
    question it answers is "is this rule doing anything at all", which is the
    question nobody has been able to ask.
    """
    from pipeline.corpus import Corpus
    from pipeline.youtube import VideoLog

    corpus = Corpus(settings)
    narrations = {f"{e.ticker}/{e.workdate}": e.narration
                  for e in corpus.entries}
    buckets: dict[str, tuple[list[float], list[float]]] = {}
    for record in VideoLog(settings).all():
        holds = holds_for_video(
            settings, record,
            narrations.get(f"{record.ticker}/{record.workdate}", ""))
        for hold in holds:
            for rule, present in _features(hold.text).items():
                yes, no = buckets.setdefault(rule, ([], []))
                (yes if present else no).append(hold.watch_ratio)
    out = [RuleEvidence(rule=rule,
                        with_it=(sum(yes) / len(yes)) if yes else 0.0,
                        without=(sum(no) / len(no)) if no else 0.0,
                        n_with=len(yes), n_without=len(no))
           for rule, (yes, no) in buckets.items()]
    return sorted(out, key=lambda r: abs(r.points), reverse=True)


def rule_evidence_text(settings: Settings) -> str:
    rows = rule_evidence(settings)
    if not rows:
        return ("Nothing to try the rules against yet — this needs published "
                "videos with retention and word timings beside them.")
    lines = ["⚖️ What the voice rules are worth, measured",
             "  Mean hold on sentences carrying the feature, against those "
             "that do not."]
    lines += [r.line() for r in rows]
    lines.append("  A rule with no measurable difference is a rule to argue "
                 "about, not yet one to delete.")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Runtime (36).
# --------------------------------------------------------------------------


@dataclass
class RuntimeBand:
    label: str
    videos: int
    mean_hold: float

    def line(self) -> str:
        return (f"  {self.label:<14} {self.mean_hold * 100:5.1f}%  "
                f"(n={self.videos})")


def runtime_evidence(settings: Settings, *,
                     bands: tuple[float, ...] = (45, 60, 75, 120, 300, 600)
                     ) -> list[RuntimeBand]:
    """Mean hold by runtime band, across everything published.

    The bands are seconds and deliberately straddle the format's own
    assumptions, so a short that should be forty seconds shows up as the band
    below the one the spec named.
    """
    from pipeline.youtube import VideoLog

    buckets: dict[str, list[float]] = {}
    for record in VideoLog(settings).all():
        rows = _rows_of(record.retention)
        if not rows or record.duration_s <= 0:
            continue
        ratios = [float(r["watch_ratio"]) for r in rows]
        edges = list(bands)
        label = f"over {edges[-1]:.0f}s"
        low = 0.0
        for edge in edges:
            if record.duration_s <= edge:
                label = f"{low:.0f}–{edge:.0f}s"
                break
            low = edge
        buckets.setdefault(label, []).append(sum(ratios) / len(ratios))
    out = [RuntimeBand(label=label, videos=len(vals),
                       mean_hold=sum(vals) / len(vals))
           for label, vals in buckets.items()]
    return sorted(out, key=lambda b: b.mean_hold, reverse=True)


def runtime_evidence_text(settings: Settings) -> str:
    rows = runtime_evidence(settings)
    if not rows:
        return ("No published video has retention against it yet, so how long "
                "these should run is still an assumption.")
    lines = ["⏱ Hold by runtime, across everything published"]
    lines += [r.line() for r in rows]
    thin = sum(1 for r in rows if r.videos < EVIDENCE_FLOOR)
    if thin:
        lines.append(f"  {thin} band(s) carry fewer than {EVIDENCE_FLOOR} "
                     f"videos and are not yet evidence.")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# The cut (10).
# --------------------------------------------------------------------------


@dataclass
class ShotHold:
    shot: str
    plate: str
    start_s: float
    end_s: float
    watch_ratio: float
    drop: float

    @property
    def seconds(self) -> float:
        return max(0.0, self.end_s - self.start_s)


def manifest_spans(manifest: dict) -> list[tuple[str, str, float, float]]:
    """Shot spans out of either renderer's manifest.

    The SHORT records `shots` with their own bounds; the LONG records its cut
    as `segments`. Both are the cut, described differently, and a caller
    asking "which shot were they on" should not have to know which renderer
    ran. The LONG's layers are the overlays on top of the cut; they answer
    only for a manifest written before segments were recorded.
    """
    shots = manifest.get("shots")
    if isinstance(shots, list) and shots:
        return [(str(s.get("id", "")), str(s.get("plate", "")),
                 float(s.get("start_s", 0.0)), float(s.get("end_s", 0.0)))
                for s in shots if isinstance(s, dict)]
    segments = manifest.get("segments")
    if isinstance(segments, list) and segments:
        from pipeline.pacing import segment_label
        return [(str(s.get("kind", "")), segment_label(s),
                 float(s.get("start", 0.0)), float(s.get("end", 0.0)))
                for s in segments if isinstance(s, dict)
                and isinstance(s.get("start"), (int, float))
                and isinstance(s.get("end"), (int, float))]
    layers = manifest.get("layers")
    if isinstance(layers, list) and layers and isinstance(layers[0], dict):
        return [(str(l.get("name", "")), str(l.get("name", "")),
                 float(l.get("t_start", 0.0)), float(l.get("t_end", 0.0)))
                for l in layers if isinstance(l, dict)
                and l.get("t_end") is not None]
    return []


def shot_holds(manifest: dict, retention: dict,
               duration_s: float) -> list[ShotHold]:
    """Retention mapped onto the cut, worst drop first.

    This is the half of the loop the renderer never heard: the chapter
    evidence reaches the writer choosing a plan, and nothing has ever told
    the pacing which shot lengths lose people.
    """
    rows = _rows_of(retention)
    out: list[ShotHold] = []
    for shot, plate, start, end in manifest_spans(manifest):
        got = hold_over(rows, duration_s, start, end)
        if got is None:
            continue
        ratio, drop = got
        out.append(ShotHold(shot=shot, plate=plate, start_s=start, end_s=end,
                            watch_ratio=ratio, drop=drop))
    return sorted(out, key=lambda s: s.drop, reverse=True)


def shot_report(holds: list[ShotHold], n: int = 6) -> str:
    if not holds:
        return ("No shot-level retention for this video — it needs both a "
                "render manifest and retention pulled against it.")
    lines = ["🎬 Which shots lose them"]
    for h in holds[:n]:
        lines.append(f"  {h.start_s:5.1f}s {h.seconds:4.1f}s  "
                     f"−{h.drop * 100:4.1f}pts  {h.plate or h.shot}")
    long_losers = [h for h in holds[:n] if h.seconds >= 8.0]
    if long_losers:
        lines.append(f"  {len(long_losers)} of those are 8s or longer — "
                     f"length is the first thing to try.")
    return "\n".join(lines)
