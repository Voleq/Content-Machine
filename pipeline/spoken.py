"""Figures as they are SAID, not as they are typed.

Nothing in the pipeline normalises numbers, and neither writing prompt asked
for spoken-form figures. It has worked so far by convention — the bible's own
examples happen to be written that way ("fifty-nine point six", "a hundred and
sixty-two percent") — and a convention is not a guarantee. One `$1,234.56`
reaching the voice is read wrong, out loud, on a figure the on-screen
fact-check gate has already verified: two verification systems that never meet.

This is the spelling half of that, and only the spelling half. What the number
IS remains `pipeline.gates.fact_check`'s question; this answers how it should
be written so the voice says it the way a person would. It is deliberately not
wired into the TTS path: silently rewriting a script before it is spoken would
put words in the narration that nobody read, and the writer is the one who
should hear it. `voice_lint` warns and suggests; the writer decides.

The register is the bible's: British "and" in the hundreds, "a hundred" rather
than "one hundred" where it leads, decimals read digit by digit after "point".
"""

from __future__ import annotations

import re

_ONES = ("zero", "one", "two", "three", "four", "five", "six", "seven",
         "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen",
         "fifteen", "sixteen", "seventeen", "eighteen", "nineteen")
_TENS = ("", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy",
         "eighty", "ninety")
_SCALES = ((10 ** 12, "trillion"), (10 ** 9, "billion"),
           (10 ** 6, "million"), (1000, "thousand"))

# Symbol -> (major singular, major plural, minor singular, minor plural).
# The minor unit is only ever used for a figure written to exactly two places,
# which is the only form where "and fifty-six cents" is what a person says.
_CURRENCY = {
    "$": ("dollar", "dollars", "cent", "cents"),
    "£": ("pound", "pounds", "penny", "pence"),
    "€": ("euro", "euros", "cent", "cents"),
}

# A figure as a writer types it: an optional sign, an optional currency
# symbol, digits (grouped or not), optional decimals, an optional scale word
# the writer already spelled out, and an optional percent sign.
FIGURE_RE = re.compile(
    r"(?P<sign>[-−])?"
    r"(?P<currency>[$£€])?"
    r"(?P<digits>\d{1,3}(?:,\d{3})+|\d+)"
    r"(?:\.(?P<frac>\d+))?"
    r"(?:\s+(?P<scale>trillion|billion|million|thousand))?"
    r"\s*(?P<pct>%)?",
    re.I,
)


def _under_hundred(n: int) -> str:
    if n < 20:
        return _ONES[n]
    tens, ones = divmod(n, 10)
    return _TENS[tens] + (f"-{_ONES[ones]}" if ones else "")


def _under_thousand(n: int, *, article: bool) -> str:
    """1..999. `article` gives "a hundred" instead of "one hundred", which is
    what a person says when the hundred leads the figure."""
    hundreds, rest = divmod(n, 100)
    if not hundreds:
        return _under_hundred(rest)
    head = ("a" if article and hundreds == 1 else _ONES[hundreds]) + " hundred"
    return head + (f" and {_under_hundred(rest)}" if rest else "")


def say_integer(n: int) -> str:
    """`1234` -> "one thousand two hundred and thirty-four"."""
    if n < 0:
        return f"minus {say_integer(-n)}"
    if n == 0:
        return "zero"
    parts: list[str] = []
    leading = True
    for value, name in _SCALES:
        chunk, n = divmod(n, value)
        if chunk:
            parts.append(f"{_under_thousand(chunk, article=leading)} {name}")
            leading = False
    if n:
        # "two thousand AND twenty-four", not "two thousand twenty-four": the
        # last group takes an "and" when it is under a hundred and something
        # came before it. Above a hundred it carries its own.
        tail = _under_thousand(n, article=leading)
        parts.append(f"and {tail}" if parts and n < 100 else tail)
    return " ".join(parts)


def say_decimals(frac: str) -> str:
    """`"56"` -> "point five six". Digit by digit, which is how a decimal is
    read aloud — "point fifty-six" is a different number to most listeners."""
    return "point " + " ".join(_ONES[int(d)] for d in frac)


def spoken_number(raw: str) -> str:
    """One typed figure as it should be said, or `raw` back if it is not one.

    `$1,234.56` -> "one thousand two hundred and thirty-four dollars and
    fifty-six cents"; `59.6%` -> "fifty-nine point six percent"; `162%` ->
    "a hundred and sixty-two percent"; `$1.2 billion` -> "one point two
    billion dollars".
    """
    m = FIGURE_RE.fullmatch(raw.strip())
    return _spoken(m) if m else raw


def _spoken(m: "re.Match[str]") -> str:
    digits = m.group("digits").replace(",", "")
    frac = m.group("frac") or ""
    scale = (m.group("scale") or "").lower()
    symbol = m.group("currency") or ""
    whole = int(digits)

    # Money written to exactly two places is the one case with a minor unit:
    # "$1,234.56" is dollars AND cents, not a decimal dollar. A scale word
    # rules that out — "$1.25 billion" is a decimal, not twenty-five cents.
    if symbol and frac and len(frac) == 2 and not scale:
        major, majors, minor, minors = _CURRENCY[symbol]
        cents = int(frac)
        if not whole and cents:
            # "forty-two cents", not "zero dollars and forty-two cents".
            return _finish(
                f"{say_integer(cents)} {minor if cents == 1 else minors}", m)
        said = f"{say_integer(whole)} {major if whole == 1 else majors}"
        if cents:
            said += f" and {say_integer(cents)} {minor if cents == 1 else minors}"
        return _finish(said, m)

    said = say_integer(whole) + (f" {say_decimals(frac)}" if frac else "")
    if scale:
        said += f" {scale}"
    if symbol:
        major, majors, _, _ = _CURRENCY[symbol]
        said += f" {major if (whole == 1 and not frac and not scale) else majors}"
    return _finish(said, m)


def _finish(said: str, m: "re.Match[str]") -> str:
    if m.group("sign"):
        said = f"minus {said}"
    if m.group("pct"):
        said += " percent"
    return said


def eye_written_figures(text: str) -> list[tuple[str, str]]:
    """Every figure in `text` written for the eye, as (as typed, as said).

    A bare integer is left alone: "eighty nine" and "89" are read the same way
    and flagging every year and every count would make the check noise. What
    is flagged is the four things a voice actually gets wrong — a currency
    symbol, a percent sign, a thousands comma, and a decimal point.
    """
    out: list[tuple[str, str]] = []
    for m in FIGURE_RE.finditer(text):
        if not (m.group("currency") or m.group("pct")
                or "," in m.group("digits") or m.group("frac")):
            continue
        out.append((m.group(0).strip(), _spoken(m)))
    return out
