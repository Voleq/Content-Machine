"""Writing checks added with voice bible v3 and v4. Every one of them warns.

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
* **Jokes (v4 §7).** The writer declares every joke; a short under three, a
  long under one a minute, a long dry stretch, or a declared line the script
  never says. The bible's floor, counted off the writer's own list.
* **The prompt said aloud (v4).** "The mandatory four-step valuation walk",
  "our first touch on the question": the prompt's scaffolding read into the
  narration or onto a plate, which no host would ever say.

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
# Swearing — bible §10.
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
# None this early (v4 §10): the opening is where the ad review looks hardest.
SWEAR_OPENING_S = 10.0
# Two strong swears closer than this read as a habit rather than a delivery.
SWEAR_GAP_S = 60.0

_STRONG_RE = re.compile("|".join(STRONG_SWEARS), re.IGNORECASE)
_PACKAGE_RE = re.compile("|".join(PACKAGE_SWEARS), re.IGNORECASE)
# NAMES AND WORDS THAT ONLY LOOK LIKE ONE (scan, 24 Oct 2026): a retailer, a
# novel, people a finance channel names, a mushroom, a painter. Taken out of
# the text before it is searched. The names are matched with their capital,
# so "dick's" in lower case is still the word.
_NOT_SWEARS = re.compile(
    r"\bDick's\b|\bMoby[ -]Dick\b|\bK\. ?Dick\b"
    r"|\bDick (?:Fuld|Grasso|Cheney|Clark|Costolo)\b"
    r"|(?i:\bshi+take\w*|\bPissarro\b)")


def swear_lint(narration: str, fmt: str) -> list[Finding]:
    """Strong swears past the limit for this format, or two inside a minute.

    Distance is measured in spoken words at the linter's reading rate, the
    same conversion the twenty-second rule uses, so "a minute" is a minute
    of the voice rather than a minute of reading.
    """
    limit = SHORT_SWEAR_LIMIT if fmt == "short" else LONG_SWEAR_LIMIT
    gap_words = SWEAR_GAP_S * SPOKEN_WPS
    opening_words = SWEAR_OPENING_S * SPOKEN_WPS
    findings: list[Finding] = []
    seen: list[tuple[int, int]] = []          # (word position, line)
    position = 0
    for lineno, line in enumerate(narration.splitlines(), 1):
        for k, word in enumerate(line.split()):
            if not _STRONG_RE.search(word):
                continue
            at = position + k
            seen.append((at, lineno))
            if at < opening_words:
                findings.append(Finding(
                    gate="swearing", severity="warn", line=lineno,
                    message=(f"a strong swear in the first "
                             f"{SWEAR_OPENING_S:.0f} seconds — YouTube's ad "
                             f"review reads the opening hardest; move it "
                             f"later"),
                    excerpt=_excerpt(line)))
            elif len(seen) > limit:
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
        m = _PACKAGE_RE.search(_NOT_SWEARS.sub(
            lambda n: " " * len(n.group(0)), text or ""))
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
# Jokes — bible v4 §7, counted off the writer's own list.
# --------------------------------------------------------------------------

# The floor. A short: three, at three targets. A long: one a minute, which
# is counted in words: the voice reads about a hundred and sixty a minute
# (a short's hundred and fifty words run fifty-odd seconds). The linter's
# slower SPOKEN_WPS is right for "twenty seconds of explanation" and would
# make a minute of this register a minute and ten.
SHORT_JOKE_FLOOR = 3
WORDS_PER_MINUTE = 160
# The longest a long should run without a listed joke. The bible allows one
# straight stretch of about a minute; past two, the chapter has gone dry.
DRY_STRETCH_MIN = 2.0
# How close a declared line has to be to something the script says.
JOKE_MATCH_RATIO = 0.8
# How many unmatched lines are named before the rest are summed up.
_MAX_UNMATCHED_SHOWN = 5

_NORM_RE = re.compile(r"[^a-z0-9' ]+")


def _norm(text: str) -> str:
    text = _TAG_RE.sub(" ", str(text or "")).lower().replace("’", "'")
    return " ".join(_NORM_RE.sub(" ", text).split())


def declared_jokes(script) -> list[tuple[str, str]]:
    """(move, line) for every joke the writer listed, either lane."""
    out = []
    for j in getattr(script, "jokes", None) or []:
        if isinstance(j, str):
            out.append(("", j))
        else:
            out.append((getattr(j, "move", "") or "", getattr(j, "text", "")))
    return [(m, t) for m, t in out if t.strip()]


def _spoken(script) -> str:
    return (getattr(script, "narration", None)
            or getattr(script, "audio_script", "") or "")


def find_joke(line: str, said_words: list[str]) -> int | None:
    """Where `line` is said, as a word index into the narration, or None.

    Exact first (the line, normalised, inside the narration); then the best
    window of the same length, so a comma moved or a word changed between
    the script and the writer's copy still finds it.
    """
    want = _norm(line).split()
    if len(want) < 2 or not said_words:
        return None
    n = len(want)
    for i in range(len(said_words) - n + 1):
        if said_words[i:i + n] == want:
            return i
    best, where = 0.0, None
    sm = difflib.SequenceMatcher(None, autojunk=False)
    sm.set_seq2(want)
    have = set(want)
    sizes = sorted({max(2, n - 1), n, n + 1})
    for i in range(0, max(1, len(said_words) - n + 2)):
        if len(have & set(said_words[i:i + n + 1])) / len(have) < 0.6:
            continue
        for size in sizes:
            sm.set_seq1(said_words[i:i + size])
            r = sm.ratio()
            if r > best:
                best, where = r, i
    return where if best >= JOKE_MATCH_RATIO else None


def joke_floor_lint(script, fmt: str) -> list[Finding]:
    """The bible's floor, against the jokes the writer declared.

    It cannot tell whether a joke is funny, and does not pretend to. What it
    can tell is that the list is short, that a listed line is not in the
    script, or that a long stretch of the long has nothing listed in it —
    which is exactly how the Gemini scripts of 30 Oct 2026 read: a long with
    six polite jokes in twenty-six minutes and a short with one.
    """
    said = _spoken(script)
    words = _norm(said).split()
    if not words:
        return []
    declared = declared_jokes(script)
    where = "the `jokes` field" if fmt == "short" else "a `=== JOKES ===` trailer"
    if not declared:
        return [Finding(
            gate="joke-floor", severity="warn",
            message=(f"no jokes listed — the prompt asks for every joke in "
                     f"{where}, word for word, so they can be counted and "
                     f"read at a glance. A script with none listed usually "
                     f"has none written"))]

    findings: list[Finding] = []
    found: list[tuple[int, int]] = []          # (first word, last word + 1)
    missing: list[str] = []
    for _move, line in declared:
        at = find_joke(line, words)
        if at is None:
            missing.append(line)
        else:
            found.append((at, at + len(_norm(line).split())))
    for line in missing[:_MAX_UNMATCHED_SHOWN]:
        findings.append(Finding(
            gate="joke-floor", severity="warn",
            message=("listed as a joke, and the script never says it — the "
                     "line in the list has to be copied from the narration"),
            excerpt=_excerpt(line)))
    if len(missing) > _MAX_UNMATCHED_SHOWN:
        findings.append(Finding(
            gate="joke-floor", severity="warn",
            message=(f"and {len(missing) - _MAX_UNMATCHED_SHOWN} more listed "
                     f"lines the script never says")))

    count = len({a for a, _b in found})
    minutes = len(words) / WORDS_PER_MINUTE
    if fmt == "short":
        floor = SHORT_JOKE_FLOOR
        if count < floor:
            findings.append(Finding(
                gate="joke-floor", severity="warn",
                message=(f"{count} joke{'s' if count != 1 else ''} in the "
                         f"script — a short carries at least {floor}: one at "
                         f"Dennis, one at the crowd, one on the number")))
    else:
        floor = max(1, int(minutes))
        if count < floor:
            findings.append(Finding(
                gate="joke-floor", severity="warn",
                message=(f"{count} jokes in about {minutes:.0f} minutes — the "
                         f"floor is one a minute, so at least {floor}")))
        # The stretches with nothing listed in them: from the end of one
        # joke to the start of the next, and the two ends of the script.
        marks = sorted(set(found))
        gaps = list(zip([0] + [b for _a, b in marks],
                        [a for a, _b in marks] + [len(words)]))
        limit = DRY_STRETCH_MIN * WORDS_PER_MINUTE
        lines = said.splitlines()
        ends, pos = [], 0
        for ln in lines:
            pos += len(_norm(ln).split())
            ends.append(pos)
        for a, b in gaps:
            if b - a <= limit:
                continue
            lineno = next((k for k, end in enumerate(ends, 1) if a < end), 0)
            findings.append(Finding(
                gate="joke-floor", severity="warn", line=lineno,
                message=(f"about {(b - a) / WORDS_PER_MINUTE:.1f} minutes "
                         f"without a listed joke — the bible allows one "
                         f"straight minute, once; this stretch needs its "
                         f"punchlines"),
                excerpt=_excerpt(lines[lineno - 1]) if lineno else ""))
    # The count, always: the operator reads this line to see the jokes are
    # there before he reads the script.
    rate = (f", {count / minutes:.1f} a minute" if fmt != "short" and minutes
            else "")
    findings.append(Finding(
        gate="joke-floor", severity="note",
        message=(f"{count} of {len(declared)} listed jokes are in the "
                 f"script{rate}: " + " · ".join(
                     (f"{m}: " if m else "") + t[:70]
                     for m, t in declared[:6])
                 + (" · …" if len(declared) > 6 else ""))))
    return findings


# --------------------------------------------------------------------------
# The prompt, said aloud (v4).
# --------------------------------------------------------------------------

# The writing prompt's own scaffolding. Each is a word or phrase the prompt
# uses to organise the writer, read back into the narration or onto a plate
# by a writer taking it literally. No host says any of them to a viewer.
PROMPT_WORDS: tuple[tuple[str, str], ...] = (
    ("mandatory", r"\bmandatory (?:valuation|beat|chapter|walk|step|segment|"
                  r"section|framework)\b"),
    ("four-step", r"\bfour[- ]step\b"),
    # Numbering the valuation chapter's four moves, not a list in a joke.
    ("step one, step two",
     r"\bstep (?:one|two|three|four)\b[^.]{0,40}?\b(?:multiples?|valuation|"
     r"walk|bridge|percentile|reverse|dcf|strip)"),
    ("in exact order", r"\bin exact order\b"),
    ("a touch on the question", r"\b(?:first|second|third|final|last) touch\b"
                                r"|\btouch on the (?:spine|question|board)\b"),
    ("the spine", r"\b(?:the|our|this) spine\b"),
    ("open loop", r"\bopen[- ]loop\b"),
    ("running gag", r"\brunning gag\b"),
    ("narrative frame", r"\bnarrative frame\b"),
    ("recurring segment", r"\brecurring segment\b"),
    ("re-hook", r"\bre-?hook\b"),
    ("the one framework", r"\bone framework\b"
                          r"|\bframework (?:of|for|in|that decides) this video\b"),
    ("epistemic", r"\bepistemic\b"),
)
_PROMPT_RES = [(name, re.compile(rx, re.IGNORECASE)) for name, rx in PROMPT_WORDS]
# On a plate only: a step number in a kicker ("STEP 1: TRAILING MULTIPLES").
_PLATE_STEP_RE = re.compile(r"\bstep\s*[1-4]\b", re.IGNORECASE)


def _printed_texts(script) -> list[tuple[str, str]]:
    """(where, text) for the words that are printed on screen."""
    out: list[tuple[str, str]] = []
    for e in getattr(script, "events", None) or []:
        for slot, value in (getattr(e, "values", None) or {}).items():
            out.append((f"[{e.type.value}] {slot}", str(value)))
    for name in ("hook_text", "numbers_comment", "turn_line", "cheap_or_trap",
                 "conclusion"):
        v = getattr(script, name, None)
        if v:
            out.append((name, str(v)))
    for h in getattr(script, "headlines", None) or []:
        out.append(("headline", f"{getattr(h, 'text', '')} "
                                f"{getattr(h, 'meaning', '')}"))
    return out


def prompt_words_lint(script) -> list[Finding]:
    """The prompt's scaffolding, spoken or printed."""
    findings: list[Finding] = []
    for lineno, line in enumerate(_spoken(script).splitlines(), 1):
        for name, rx in _PROMPT_RES:
            if rx.search(line):
                findings.append(Finding(
                    gate="prompt-words", severity="warn", line=lineno,
                    message=(f"“{name}” is the prompt's word, read out loud — "
                             f"a host never says it; do the thing instead of "
                             f"naming it"),
                    excerpt=_excerpt(line)))
                break
    for where, text in _printed_texts(script):
        hit = next((name for name, rx in _PROMPT_RES if rx.search(text)), None)
        if hit is None and where.startswith("["):
            hit = "step" if _PLATE_STEP_RE.search(text) else None
        if hit:
            findings.append(Finding(
                gate="prompt-words", severity="warn",
                message=(f"“{hit}” is the prompt's word, printed in {where} — "
                         f"it would be on screen"),
                excerpt=_excerpt(text)))
    return findings


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


# Lines the short prompts' worked examples used to carry, which writers
# copied word for word into real scripts: the BA short of 30 Oct 2026 turned
# on "But here is the part nobody screenshots" and closed on "Mostly noise,
# one number worth watching." Still checked after the examples changed.
RETIRED_EXAMPLE_LINES: tuple[str, ...] = (
    "But here is the part nobody screenshots.",
    "But here is the part you never see in the screenshots.",
    "But here's the part the headline skips.",
    "Mostly noise, one number worth watching.",
    "That is not growth, that is a plateau in a costume, and you pay them to own it.",
)
_EXAMPLE_PROMPTS = ("master_prompt_short.md", "master_prompt_headline.md")


def example_lines(settings: Settings) -> list[str]:
    """The spoken lines and declared jokes of the short prompts' worked
    examples. A writer copies an example's shape first and, given half a
    chance, its sentences too."""
    import json

    out: list[str] = list(RETIRED_EXAMPLE_LINES)
    for name in _EXAMPLE_PROMPTS:
        try:
            text = (settings.templates_dir / name).read_text(encoding="utf-8")
            example = text[text.index("## STRUCTURE EXAMPLE"):]
            obj = json.loads(example[example.index("{"):])
        except (OSError, ValueError) as e:
            log.debug("no worked example in %s (%s)", name, e)
            continue
        said = _TAG_RE.sub(" ", re.sub(r"\[BEAT:[^\]]*\]", " ",
                                       str(obj.get("audio_script", ""))))
        out += [s for s in _SENTENCE_RE.split(" ".join(said.split())) if s]
        out += [str(j) for j in obj.get("jokes") or []]
    return out


def reference_lines(settings: Settings) -> list[tuple[str, str]]:
    """(where it is from, the sentence) for everything Dennis must not
    repeat: the bible's quoted examples, the prompts' worked examples and
    the style references."""
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
    out += [("prompt example", s) for s in example_lines(settings)]
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
