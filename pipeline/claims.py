"""Claims to check yourself (S6): the sentences no gate can verify.

The gates check every figure against the workbook. What they cannot check is
the sentence that is not a workbook figure at all: "the CEO resigned in
March", "Example Corp bought its biggest rival in 2021", "the SEC fined them
on a Tuesday". Those come from the writer's memory, and a writer's memory of
a date or a deal is the likeliest thing in the script to be wrong.

So the approval report lists them, by line, for a human to check before the
voice is paid for. The rule is cheap and errs towards listing: a sentence is
a claim when it

* names an event (acquired, sued, resigned, fined, …) with a date, or with a
  name that is not its first word, or
* names a month, a weekday or "yesterday" — workbook periods are fiscal
  years, so a calendar date is the writer's.

Dennis talking about himself is not a claim: a sentence that opens in the
first person singular, or names one of his people, is his story, and the
story has its own file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

EVENT_VERBS = (
    "acquired", "announced", "sued", "settled", "resigned", "fired",
    "founded", "launched", "recalled", "restated", "raised", "cut", "guided",
    "filed", "approved", "banned", "fined", "merged", "spun off", "bought",
    "hired", "investigated", "charged",
)
_EVENT_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(v) for v in EVENT_VERBS) + r")\b",
    re.IGNORECASE)
# A year in digits, or as the narration says it: the prompts have the writer
# spell every spoken figure out for the voice, so "fined in twenty nineteen"
# is the usual shape and "2019" the rare one.
_UNIT = r"(?:one|two|three|four|five|six|seven|eight|nine)"
_TEEN = (r"(?:ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|"
         r"eighteen|nineteen)")
_TENS = r"(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)"
_YEAR_RE = re.compile(
    r"\b(?:19|20)\d{2}\b"
    r"|\b(?:nineteen|twenty)[\s-]+(?:oh[\s-]+" + _UNIT + r"|" + _TEEN + r"|"
    + _TENS + r"(?:[\s-]+" + _UNIT + r")?)\b"
    r"|\btwo thousand(?:\s+and)?[\s-]+(?:" + _TEEN + r"|" + _UNIT + r")\b",
    re.IGNORECASE)
_MONTHS = ("January", "February", "March", "April", "June", "July", "August",
           "September", "October", "November", "December", "Sept")
# "May" is a month only with a day or a year after it; "may" is a verb.
_DATE_RE = re.compile(
    r"\b(?:" + "|".join(_MONTHS) + r")\b|\bMay\s+\d|\b(?:Monday|Tuesday|"
    r"Wednesday|Thursday|Friday|Saturday|Sunday)\b|\byesterday\b|"
    r"\b(?:last|this) week\b|\bthis morning\b")
_NAME_RE = re.compile(r"\b[A-Z][A-Za-z&.'-]+")
# Capitalised words that name nobody.
_NOT_NAMES = {"I", "I'm", "I've", "I'd", "I'll", "Dennis", "OK", "Okay"}
_FIRST_PERSON_RE = re.compile(r"^\W*(?:I|I'm|I've|I'd|I'll|My|Me)\b")
_SENTENCE_RE = re.compile(r"[^.?!]+[.?!]*")
_TAG_RE = re.compile(r"\[[^\]]*\]")


@dataclass
class Claim:
    line: int
    text: str
    why: str


def _cast_re() -> re.Pattern:
    from pipeline.channel_memory import CAST

    return re.compile(r"\b(?:" + "|".join(re.escape(c) for c in CAST) + r")\b")


def _sentences(narration: str):
    for lineno, line in enumerate((narration or "").splitlines(), 1):
        for m in _SENTENCE_RE.finditer(_TAG_RE.sub(" ", line)):
            s = " ".join(m.group(0).split())
            if len(s.split()) >= 3:
                yield lineno, s


def _named(sentence: str, ticker: str) -> bool:
    """A capitalised name somewhere after the first word."""
    words = list(_NAME_RE.finditer(sentence))
    for m in words:
        if m.start() == len(sentence) - len(sentence.lstrip()):
            continue                                 # the first word
        word = m.group(0).rstrip(".'")
        if word in _NOT_NAMES or word.upper() == (ticker or "").upper():
            continue
        if word in _MONTHS or word == "May":
            continue
        return True
    return False


def _why(sentence: str, ticker: str) -> str:
    event = _EVENT_RE.search(sentence)
    dated = _DATE_RE.search(sentence) or _YEAR_RE.search(sentence)
    if event and dated:
        return f"a dated event: “{event.group(0)}”"
    if event and _named(sentence, ticker):
        return f"an event with a name: “{event.group(0)}”"
    if _DATE_RE.search(sentence):
        return "a calendar date, not a fiscal period"
    return ""


def _raw_line(raw: str, sentence: str) -> int:
    """The line of the stored script the sentence sits on, for `/edit N`."""
    probe = " ".join(sentence.split()[:6])
    for lineno, line in enumerate((raw or "").splitlines(), 1):
        if probe and probe in " ".join(_TAG_RE.sub(" ", line).split()):
            return lineno
    return 0


def list_claims(narration: str, ticker: str = "", raw: str = "") -> list[Claim]:
    """Every sentence in the narration a human should check, in order.

    Lines are the stored script's when `raw` is given (what `/script` and
    `/edit` number), else the narration's own."""
    cast = _cast_re()
    out: list[Claim] = []
    seen: set[str] = set()
    for lineno, sentence in _sentences(narration):
        if sentence in seen:
            continue
        if _FIRST_PERSON_RE.search(sentence) or cast.search(sentence):
            continue                                 # Dennis's own story
        why = _why(sentence, ticker)
        if not why:
            continue
        seen.add(sentence)
        out.append(Claim(line=_raw_line(raw, sentence) or lineno,
                         text=sentence, why=why))
    return out


def claims_lines(claims: list[Claim]) -> list[str]:
    """The report's lines: "L{n}: {text} ({why})"."""
    return [f"L{c.line}: {c.text} ({c.why})" for c in claims]


def script_claims(script, ticker: str = "", raw: str = "") -> list[str]:
    """The report lines for a parsed script of either format."""
    narration = (getattr(script, "narration", None)
                 or getattr(script, "audio_script", "") or "")
    return claims_lines(list_claims(narration, ticker, raw))
