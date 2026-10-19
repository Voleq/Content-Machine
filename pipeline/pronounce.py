"""How a word is said (A5): substitutions for the voice, and only the voice.

ElevenLabs says "EBITDA" however it likes, and a ticker read as a word or as
letters depends on the day. The fix every narrator uses is to hand the voice
a spelling of the sound — "ee-bit-dah" — and keep the written word for the
reader. So the list is applied to the text bound for the paid voice, after
the delivery direction is put in and never inside it, and every substitution
is recorded so the alignment can be put back on the written word: the
captions, the plates and the cue timings never see the spoken form.

A rule that turns one word into three ("ee bit dah") comes back from the
voice as three timed words. `undo_rules` merges them back into the one
written word, from the first one's start to the last one's end.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from config import Settings
from pipeline.models import WordTimestamp

log = logging.getLogger(__name__)

FILE = "pronunciations"
_ARROW = "=>"


@dataclass(frozen=True)
class Rule:
    word: str
    said: str


@dataclass(frozen=True)
class Edit:
    """One substitution: [src_start, src_end) in the text before, became
    [dst_start, dst_end) in the text after."""
    src_start: int
    src_end: int
    dst_start: int
    dst_end: int


def parse_rules(lines: list[str]) -> list[Rule]:
    out: list[Rule] = []
    for line in lines:
        if _ARROW not in line:
            log.warning("pronunciation line without '=>' skipped: %r", line)
            continue
        word, said = (p.strip() for p in line.split(_ARROW, 1))
        if word and said and word != said:
            out = [r for r in out if r.word != word] + [Rule(word, said)]
    return out


def load_rules(settings: Settings) -> list[Rule]:
    from pipeline.writing_files import list_lines

    try:
        return parse_rules(list_lines(settings, FILE))
    except Exception as e:                         # noqa: BLE001
        log.warning("pronunciation list unreadable (%s)", e)
        return []


def _pattern(word: str) -> re.Pattern[str]:
    return re.compile(r"(?<!\w)" + re.escape(word) + r"(?!\w)")


def _rewrite(settings: Settings, word: str, said: str | None) -> bool:
    from pipeline.writing_files import read_file, write_file

    lines = read_file(settings, FILE).splitlines()
    kept, found = [], False
    for line in lines:
        bare = line.strip()
        if (bare and not bare.startswith("#") and _ARROW in bare
                and bare.split(_ARROW, 1)[0].strip() == word):
            found = True
            continue
        kept.append(line)
    if said is not None:
        kept.append(f"{word} {_ARROW} {said}")
    elif not found:
        return False
    write_file(settings, FILE, "\n".join(kept).rstrip("\n") + "\n")
    return True


def add_rule(settings: Settings, word: str, said: str) -> Rule:
    """Add or replace one rule in his copy of the list."""
    word, said = word.strip(), " ".join(said.split())
    if not word or not said or _ARROW in word or _ARROW in said:
        raise ValueError("a rule is: WORD => how to say it")
    _rewrite(settings, word, said)
    return Rule(word, said)


def remove_rule(settings: Settings, word: str) -> bool:
    return _rewrite(settings, word.strip(), None)


def rules_hitting(text: str, rules: list[Rule]) -> list[Rule]:
    """The rules that would change this text, in list order."""
    return [r for r in rules if _pattern(r.word).search(text or "")]


def apply_rules(text: str, rules: list[Rule],
                protect: list[tuple[int, int]] | tuple = ()) -> tuple[str, list[Edit]]:
    """The text with every rule applied outside `protect`, and the edits."""
    hits: list[tuple[int, int, str]] = []
    # Longer words first, so "10-K/A" wins over "10-K" where both match.
    for rule in sorted(rules, key=lambda r: len(r.word), reverse=True):
        for m in _pattern(rule.word).finditer(text):
            a, b = m.span()
            if any(a < hi and lo < b for lo, hi in protect):
                continue
            if any(a < hb and ha < b for ha, hb, _ in hits):
                continue
            hits.append((a, b, rule.said))
    if not hits:
        return text, []
    hits.sort()
    pieces, edits, cursor, out_len = [], [], 0, 0
    for a, b, said in hits:
        pieces.append(text[cursor:a])
        out_len += a - cursor
        pieces.append(said)
        edits.append(Edit(a, b, out_len, out_len + len(said)))
        out_len += len(said)
        cursor = b
    pieces.append(text[cursor:])
    return "".join(pieces), edits


def shift_spans(spans: list[tuple[int, int]], edits: list[Edit]) -> list[tuple[int, int]]:
    """Spans in the text before the edits, moved to the text after them.
    Spans never overlap an edit (`protect`), so each moves whole."""
    out = []
    for lo, hi in spans:
        delta = sum((e.dst_end - e.dst_start) - (e.src_end - e.src_start)
                    for e in edits if e.src_end <= lo)
        out.append((lo + delta, hi + delta))
    return out


def _to_src(p: int, edits: list[Edit], *, end: bool) -> tuple[int, Edit | None]:
    """A start (or an end) offset after the edits, before them; and the edit
    it falls inside, if any. A start at an edit's first character and an end
    at its last are inside it."""
    shift = 0
    for e in edits:
        before = p <= e.dst_start if end else p < e.dst_start
        if before:
            break
        past = p > e.dst_end if end else p >= e.dst_end
        if past:
            shift += (e.dst_end - e.dst_start) - (e.src_end - e.src_start)
            continue
        return (e.src_end if end else e.src_start), e
    return p - shift, None


def undo_rules(words: list[WordTimestamp], edits: list[Edit],
               src_text: str) -> list[WordTimestamp]:
    """Word offsets after the edits, put back on the text before them; the
    words a substitution became are merged into the one word it replaced."""
    if not edits:
        return list(words)
    edits = sorted(edits, key=lambda e: e.dst_start)
    out: list[WordTimestamp] = []
    last_edit: Edit | None = None
    for w in words:
        start, e1 = _to_src(w.char_start, edits, end=False)
        stop, e2 = _to_src(w.char_end, edits, end=True)
        inside = e1 or e2
        if (inside is not None and inside is last_edit and out
                and out[-1].char_end >= inside.src_start):
            prev = out[-1]
            cs, ce = prev.char_start, max(prev.char_end, stop)
            out[-1] = prev.model_copy(update={
                "word": src_text[cs:ce], "end": max(prev.end, w.end),
                "char_end": ce})
            continue
        word = src_text[start:stop] if inside is not None else w.word
        out.append(w.model_copy(update={"word": word, "char_start": start,
                                        "char_end": stop}))
        last_edit = inside
    return out
