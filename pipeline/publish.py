"""Publishing by-products: subtitles and the upload metadata package.

Everything here is derived from artefacts the render already produced — the
word timestamps and the chapter trailer — so it costs nothing and is emitted
automatically rather than on request.

Subtitles come from `tts.words`, which is the same master clock the visuals
are cut against. That means the captions burned into the video and the `.srt`
uploaded alongside it are the same timing, not two independent guesses.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from pipeline.models import WordTimestamp

log = logging.getLogger(__name__)

# Subtitle shaping. Two lines of ~42 characters is the broadcast convention
# and roughly what a phone can read at arm's length.
MAX_CHARS = 84
MAX_LINE = 42
MAX_CUE_S = 6.0
MIN_CUE_S = 0.9
GAP_SPLIT_S = 0.6   # a pause this long ends the cue — usually a sentence


def _timestamp(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _wrap(text: str) -> str:
    if len(text) <= MAX_LINE:
        return text
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(f"{cur} {w}".strip()) <= MAX_LINE or not cur:
            cur = f"{cur} {w}".strip()
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return "\n".join(lines[:2])


def group_cues(words: list[WordTimestamp]) -> list[tuple[float, float, str]]:
    """Word timings -> readable subtitle cues.

    Breaks on sentence-ending punctuation, on a pause long enough to be a
    breath, and on length — in that order of preference, so a cue rarely
    splits mid-clause.
    """
    cues: list[tuple[float, float, str]] = []
    bucket: list[WordTimestamp] = []

    def flush() -> None:
        if not bucket:
            return
        text = " ".join(w.word for w in bucket).strip()
        if text:
            start = bucket[0].start
            end = max(bucket[-1].end, start + MIN_CUE_S)
            cues.append((start, end, _wrap(text)))
        bucket.clear()

    for i, w in enumerate(words):
        bucket.append(w)
        text_len = sum(len(x.word) + 1 for x in bucket)
        span = w.end - bucket[0].start
        ends_sentence = w.word.rstrip("\"'”’)").endswith((".", "!", "?", "…"))
        next_gap = (words[i + 1].start - w.end) if i + 1 < len(words) else 0.0
        if ends_sentence or next_gap >= GAP_SPLIT_S or text_len >= MAX_CHARS \
                or span >= MAX_CUE_S:
            flush()
    flush()
    return cues


def write_srt(words: list[WordTimestamp], out_path: Path) -> Path:
    """A .srt built from the render's own word timings."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    blocks = []
    for n, (start, end, text) in enumerate(group_cues(words), 1):
        blocks.append(f"{n}\n{_timestamp(start)} --> {_timestamp(end)}\n{text}\n")
    out_path.write_text("\n".join(blocks), encoding="utf-8")
    log.info("wrote %d subtitle cues -> %s", len(blocks), out_path)
    return out_path


# --------------------------------------------------------------------------
# The upload package.
# --------------------------------------------------------------------------

_CHAPTER_RE = re.compile(r"^\s*(\d{1,2}:\d{2}(?::\d{2})?)\s+(.{2,80})$")


@dataclass
class UploadPackage:
    ticker: str
    titles: list[str] = field(default_factory=list)
    description: str = ""
    tags: list[str] = field(default_factory=list)
    pinned_comment: str = ""

    def render_text(self) -> str:
        lines = [f"=== {self.ticker} — upload package ===", "", "TITLE OPTIONS"]
        lines += [f"  {i}. {t}" for i, t in enumerate(self.titles, 1)]
        lines += ["", "DESCRIPTION", self.description, "",
                  "TAGS", ", ".join(self.tags), "",
                  "PINNED COMMENT", self.pinned_comment, ""]
        return "\n".join(lines)


def normalise_chapters(chapters: str, duration_s: float = 0.0) -> list[tuple[str, str]]:
    """The `mm:ss Title` trailer as (timestamp, title) pairs.

    YouTube only renders chapters when the first one is at 00:00 and there
    are at least three, so a malformed trailer is worth catching here rather
    than discovering on the upload.
    """
    out: list[tuple[str, str]] = []
    for line in (chapters or "").splitlines():
        m = _CHAPTER_RE.match(line)
        if m:
            out.append((m.group(1).strip(), m.group(2).strip()))
    if out and not out[0][0].startswith("00:00"):
        out[0] = ("00:00", out[0][1])
    return out


def build_package(script, settings, *, ticker: str = "",
                  hook: str = "", runtime_min: float = 0.0) -> UploadPackage:
    """Title options, description with chapters, tags and a pinned comment.

    Deliberately mechanical: it assembles what the script already decided
    rather than inventing new claims. Nothing here should say anything the
    video does not.
    """
    ticker = (ticker or getattr(script, "ticker", "")).upper()
    chapters = normalise_chapters(getattr(script, "chapters", ""))
    narration = getattr(script, "narration", "") or getattr(script, "audio_script", "")
    first_line = next((s.strip() for s in re.split(r"(?<=[.!?])\s+", narration)
                       if s.strip()), "")
    hook = hook or first_line

    titles = [
        f"{ticker} — {hook[:70].rstrip('.')}",
        f"What ${ticker} actually is, {'{:.0f}'.format(runtime_min)} minutes"
        if runtime_min else f"What ${ticker} actually is",
        f"${ticker}: the numbers nobody screenshots",
    ]

    body = [hook, ""]
    if chapters:
        body.append("Chapters")
        body += [f"{ts} {title}" for ts, title in chapters]
        body.append("")
    body += [
        settings.disclaimer_text,
        "",
        "Everything on screen is from the filings. No sponsor, no position "
        "unless stated, no price targets.",
    ]

    return UploadPackage(
        ticker=ticker,
        titles=titles,
        description="\n".join(body).strip(),
        tags=[ticker, f"${ticker}", "stocks", "investing", "earnings",
              "value investing", "stock analysis", "10-K"],
        pinned_comment=(
            f"Numbers are from {ticker}'s own filings. If I got one wrong, "
            f"say so and I'll pin the correction."),
    )
