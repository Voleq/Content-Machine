"""Writing checks added with voice bible v3. Every one of them warns.

The voice linter in `pipeline.gates` polices what the bible forbids. These
police what makes a script read as written by a machine, or lifted, or the
same as last week's — the three ways a channel with an AI voice loses the
viewer's trust faster than one without:

* **Phrasing (S1).** The turns of phrase a model reaches for. The list is a
  file he edits (`pipeline.writing_files`), so the check never needs a code
  change to learn a new tell.
* **Swearing.** Bible v3 §10: a few, where they land. YouTube still limits
  ads for frequent strong swearing and for any in a title or thumbnail, so
  the count and the metadata are checked, never the taste.
* **Copy (S2).** A sentence that repeats a bible example or a style
  reference almost word for word. The examples teach a move; the move is
  meant to be reused, the sentence never.
* **Chapter order (S9).** A long whose chapters run in the order one of the
  last three did.

None of these blocks. The sameness gate is the one writing check that may
stop a render, and it only does when a script is effectively a previous one
re-tickered. A warning that names the line and the fix is the whole job.
"""

from __future__ import annotations

import difflib
import logging
import re
from pathlib import Path

from config import Settings
from pipeline.gates import SPOKEN_WPS, Finding

log = logging.getLogger(__name__)


def _excerpt(line: str) -> str:
    return line.strip()[:140]


# --------------------------------------------------------------------------
# S1 — machine-made phrasing.
# --------------------------------------------------------------------------

_TAG_RE = re.compile(r"\[[A-Z][A-Z ]*\]")
# A short question answered by the next couple of words: "The result? Chaos."
# The answer may not be Dennis declining to answer ("I don't know."), which is
# the bible's own *question left open* and the opposite of the tell.
_ANSWERED_RE = re.compile(
    r"(?:^|(?<=[.!?…])\s+)((?:[\w'’-]+\s+){0,4}[\w'’-]+\?)\s+"
    r"(?!(?:i|we|nobody|no one|not)\b)((?:[\w'’-]+\s+){0,2}[\w'’-]+[.!])",
    re.IGNORECASE)


def phrasing_lint(narration: str, settings: Settings) -> list[Finding]:
    """Every listed phrase, plus the answered question from its second use.

    One answered question is a device. Two is a template, and it is the one
    the model reaches for most, so the second is where it is worth saying.
    """
    from pipeline.writing_files import phrase_patterns

    findings: list[Finding] = []
    patterns = phrase_patterns(settings)
    answered: list[int] = []
    for lineno, line in enumerate(narration.splitlines(), 1):
        plain = _TAG_RE.sub(" ", line)
        for phrase, pattern in patterns:
            if pattern.search(plain):
                findings.append(Finding(
                    gate="phrasing", severity="warn", line=lineno,
                    message=(f"“{phrase}” reads as machine-written — cut it, "
                             f"or say the thing it is introducing plainly"),
                    excerpt=_excerpt(line)))
        for m in _ANSWERED_RE.finditer(plain.strip()):
            answered.append(lineno)
            if len(answered) >= 2:
                findings.append(Finding(
                    gate="phrasing", severity="warn", line=lineno,
                    message=(f"a question answered by the next word or two, "
                             f"again (first on line {answered[0]}) — once is "
                             f"a device, twice reads as a template"),
                    excerpt=_excerpt(m.group(0))))
    return findings


# --------------------------------------------------------------------------
# Swearing — bible v3 §10.
# --------------------------------------------------------------------------

# Strong swearing as YouTube's advertiser guidelines mean it: the f-word and
# its family. The milder words are fine in the narration and not counted.
STRONG_SWEARS: tuple[str, ...] = (
    r"\b(?:mother)?f+u+c+k\w*", r"\bf\*+k\w*", r"\bfck\w*", r"\bcunt\w*",
)
# What may not appear in a title, chapter title, description or pinned
# comment at all: the strong ones and the moderate ones YouTube names.
PACKAGE_SWEARS: tuple[str, ...] = STRONG_SWEARS + (
    r"\b(?:bull)?shit\w*", r"\bbitch\w*", r"\basshole\w*", r"\bbastard\w*",
    r"\bdick\b", r"\bpiss\w*",
)
LONG_SWEAR_LIMIT = 4
SHORT_SWEAR_LIMIT = 1
# Two strong swears closer than this read as a habit rather than a delivery.
SWEAR_GAP_S = 60.0

_STRONG_RE = re.compile("|".join(STRONG_SWEARS), re.IGNORECASE)
_PACKAGE_RE = re.compile("|".join(PACKAGE_SWEARS), re.IGNORECASE)


def swear_lint(narration: str, fmt: str) -> list[Finding]:
    """Strong swears past the limit for this format, or two inside a minute.

    Distance is measured in spoken words at the linter's reading rate, the
    same conversion the twenty-second rule uses, so "a minute" is a minute
    of the voice rather than a minute of reading.
    """
    limit = SHORT_SWEAR_LIMIT if fmt == "short" else LONG_SWEAR_LIMIT
    gap_words = SWEAR_GAP_S * SPOKEN_WPS
    findings: list[Finding] = []
    seen: list[tuple[int, int]] = []          # (word position, line)
    position = 0
    for lineno, line in enumerate(narration.splitlines(), 1):
        for k, word in enumerate(line.split()):
            if not _STRONG_RE.search(word):
                continue
            at = position + k
            seen.append((at, lineno))
            if len(seen) > limit:
                findings.append(Finding(
                    gate="swearing", severity="warn", line=lineno,
                    message=(f"strong swear number {len(seen)} — a {fmt} "
                             f"carries at most {limit}; keep the one that "
                             f"lands hardest"),
                    excerpt=_excerpt(line)))
            elif len(seen) > 1 and at - seen[-2][0] < gap_words:
                findings.append(Finding(
                    gate="swearing", severity="warn", line=lineno,
                    message=(f"two strong swears inside a minute (the other "
                             f"is on line {seen[-2][1]}) — one of them goes"),
                    excerpt=_excerpt(line)))
        position += len(line.split())
    return findings


def package_swears(texts: dict[str, str]) -> list[Finding]:
    """Any swear in the words around the video: titles, chapter titles, the
    description, the pinned comment. `texts` is {what it is: its words}."""
    findings: list[Finding] = []
    for where, text in texts.items():
        m = _PACKAGE_RE.search(text or "")
        if m:
            findings.append(Finding(
                gate="swearing", severity="warn",
                message=(f"“{m.group(0)}” in the {where} — YouTube limits ads "
                         f"for swearing in a title, chapter title, "
                         f"thumbnail or description; keep it in the "
                         f"narration"),
                excerpt=_excerpt(text)))
    return findings


def chapter_title_swears(script) -> list[Finding]:
    """The chapter titles go on screen AND into the description's chapters."""
    titles = {f"chapter title {n}": getattr(c, "title", "")
              for n, c in enumerate(getattr(script, "chapter_list", None) or [], 1)}
    return package_swears(titles)


# --------------------------------------------------------------------------
# S2 — a bible example or a style reference, said again.
# --------------------------------------------------------------------------

# Below this many words a sentence is a phrase, and phrases repeat honestly.
COPY_MIN_WORDS = 6
# Word-level similarity at which a sentence is the reference said again.
COPY_RATIO = 0.75
# A cheap gate before the expensive one: share this much vocabulary first.
_COPY_PREFILTER = 0.4

_WORDS_RE = re.compile(r"[a-z0-9']+")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def _words(text: str) -> list[str]:
    return _WORDS_RE.findall(text.lower().replace("’", "'"))


def reference_lines(settings: Settings) -> list[tuple[str, str]]:
    """(where it is from, the sentence) for everything Dennis must not
    repeat: the bible's quoted examples and the style references."""
    from pipeline.writing_files import list_lines, read_file

    out: list[tuple[str, str]] = []
    text = read_file(settings, "voice_bible")
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith(">"):
            continue
        body = line.lstrip("> ").strip()
        # An example is usually `context: "the line"`; the line is the quote.
        quoted = re.findall(r"[\"“]([^\"”]+)[\"”]", body)
        for chunk in quoted or [body]:
            out += [("bible", s) for s in _SENTENCE_RE.split(chunk) if s.strip()]
    for ref in list_lines(settings, "style_references"):
        out += [("style reference", s) for s in _SENTENCE_RE.split(ref)
                if s.strip()]
    return out


# A clause lifted out of a longer reference: the shorter side is this much
# inside the longer one, in order. Only past a length where that is no
# accident — ten words in the same order is a quotation.
LIFT_RATIO = 0.85
LIFT_MIN_WORDS = 10


def _lifted(sm: difflib.SequenceMatcher, a: int, b: int) -> bool:
    shorter = min(a, b)
    if shorter < LIFT_MIN_WORDS:
        return False
    matched = sum(block.size for block in sm.get_matching_blocks())
    return matched / shorter >= LIFT_RATIO


def copy_check(narration: str, settings: Settings) -> list[Finding]:
    """A spoken sentence that is a reference sentence said again.

    Two references in a row can make one long sentence of Dennis's, and one
    reference can be split over two of his, so a reference is compared with
    each sentence and with each pair of neighbouring sentences.
    """
    refs = [(src, _words(s)) for src, s in reference_lines(settings)]
    refs = [(src, w) for src, w in refs if len(w) >= COPY_MIN_WORDS]
    if not refs:
        return []
    findings: list[Finding] = []
    for lineno, line in enumerate(narration.splitlines(), 1):
        said = [s for s in _SENTENCE_RE.split(_TAG_RE.sub(" ", line)) if s.strip()]
        spans = said + [f"{a} {b}" for a, b in zip(said, said[1:])]
        hit = None
        for span in spans:
            words = _words(span)
            if len(words) < COPY_MIN_WORDS:
                continue
            have = set(words)
            for src, ref in refs:
                shared = len(have & set(ref)) / max(1, len(set(ref)))
                if shared < _COPY_PREFILTER:
                    continue
                sm = difflib.SequenceMatcher(None, words, ref, autojunk=False)
                if (sm.ratio() >= COPY_RATIO
                        or _lifted(sm, len(words), len(ref))):
                    hit = (src, " ".join(ref))
                    break
            if hit:
                break
        if hit:
            findings.append(Finding(
                gate="copy", severity="warn", line=lineno,
                message=(f"repeats a {hit[0]} line almost word for word — the "
                         f"move is his to reuse, the sentence never: "
                         f"“{hit[1][:90]}”"),
                excerpt=_excerpt(line)))
    return findings


# --------------------------------------------------------------------------
# S9 — chapters in the order one of the last three longs ran them.
# --------------------------------------------------------------------------

CHAPTER_ORDER_WINDOW = 3
# A run of this many chapter types in the same order is the same video's
# skeleton, even when the rest of the order differs.
CHAPTER_RUN = 5


def _types_on_file(path: Path) -> list[str]:
    import json

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rows = payload.get("chapter_list") if isinstance(payload, dict) else None
    return [str(r.get("type", "")) for r in rows or [] if isinstance(r, dict)]


def recent_chapter_orders(settings: Settings, n: int = CHAPTER_ORDER_WINDOW,
                          exclude: Path | None = None
                          ) -> list[tuple[str, list[str]]]:
    """(`TICKER workdate`, its chapter types) for the last n shipped longs."""
    from pipeline.corpus import Corpus

    try:
        rows = [e for e in Corpus(settings).recent(0, fmt="long") if e.shipped]
    except Exception:                              # noqa: BLE001
        return []
    out: list[tuple[str, list[str]]] = []
    for e in reversed(rows):
        folder = settings.workspace_dir / e.ticker / e.workdate
        if exclude is not None and Path(exclude).resolve() == folder.resolve():
            continue
        types = _types_on_file(folder / "script_long.json")
        if types:
            out.append((f"{e.ticker} {e.workdate}", types))
        if len(out) >= n:
            break
    return out


def _shared_run(a: list[str], b: list[str]) -> int:
    """The longest run of chapter types the two share in the same order."""
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    return max((m.size for m in sm.get_matching_blocks()), default=0)


def chapter_order_lint(script, settings: Settings,
                       workspace: Path | None = None) -> list[Finding]:
    types = [c.type for c in getattr(script, "chapter_list", None) or []]
    if len(types) < 3:
        return []
    for where, theirs in recent_chapter_orders(settings, exclude=workspace):
        run = _shared_run(types, theirs)
        if types == theirs or run >= min(CHAPTER_RUN, len(types)):
            what = ("the same chapter order" if types == theirs else
                    f"{run} chapters in a row in the same order")
            return [Finding(
                gate="chapters", severity="warn",
                message=(f"{what} as {where} — move a chapter, or open on a "
                         f"different one, so the two do not share a "
                         f"skeleton"),
                excerpt=" → ".join(types)[:140])]
    return []


def chapter_orders_block(settings: Settings, workspace: Path | None = None) -> str:
    """{{recent_chapter_orders}}: what the last longs did, so this one differs."""
    rows = recent_chapter_orders(settings, exclude=workspace)
    if not rows:
        return "(no long on record yet — any order the material wants)"
    lines = ["Your last longs ran their chapters in these orders. Do not "
             f"repeat one, or {CHAPTER_RUN} of them in a row:"]
    lines += [f"  - {where}: {' → '.join(types)}" for where, types in rows]
    return "\n".join(lines)
