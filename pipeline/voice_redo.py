"""The voice, sentence by sentence (A6, A7).

`sentences` cuts the finished voice into the script's sentences with their
times, read off the word timings, so a sentence can be listened to, pointed
at by number, and voiced again on its own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

MAX_REDOS = 10
_SENTENCE_RE = re.compile(r"[^.?!\n]+(?:[.?!]+[\"”’)]*|$)")


@dataclass
class SpokenSentence:
    index: int            # 1-based, what `/voice redo N` takes
    text: str
    start: float
    end: float
    char_start: int
    char_end: int


def sentences(words, clean_text: str) -> list[SpokenSentence]:
    """The clean script's sentences that the voice actually says, timed."""
    out: list[SpokenSentence] = []
    for m in _SENTENCE_RE.finditer(clean_text or ""):
        a, b = m.span()
        while a < b and clean_text[a].isspace():
            a += 1
        text = clean_text[a:b].strip()
        if not text:
            continue
        said = [w for w in words if a <= w.char_start < b]
        if not said:
            continue
        out.append(SpokenSentence(index=len(out) + 1, text=text,
                                  start=said[0].start, end=said[-1].end,
                                  char_start=a, char_end=a + len(text)))
    return out


def clock(seconds: float) -> str:
    m, s = divmod(max(0.0, seconds), 60)
    return f"{int(m)}:{s:04.1f}"
