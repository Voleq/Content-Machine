"""The titles the writer writes, and the bot's check on each (T1-T4).

Until 7 Nov 2026 no title was written by anyone: the upload package built
three from a template, and the third was a phrase the prompts themselves list
as used up. Now each writing prompt asks for five options with the line of
the script that pays each one off, plus two to four words for the thumbnail,
and this module decides which of them the upload may offer.

A title is the one line of the video most people ever read, so it is held to
the video. A title YouTube would refuse, one with a figure the script never
gives, one that swears or reads as a call, or one naming a data vendor is NOT
OFFERED, and the check says why. Everything softer is a warning: long for a
phone, opening on the ticker, a payoff line the script does not say.

The rules are shapes learned from a creator's titles (the Benjamin study), never
his titles: the story or the verdict first, one concrete figure, one judging
word on a finance noun, a format label when the video has one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Past this a title is cut off in search and on a phone. A warning: some
# good titles run longer.
TITLE_WARN_CHARS = 60
# YouTube refuses a longer one (`pipeline.youtube.TITLE_MAX`).
TITLE_HARD_CHARS = 100
THUMB_MIN_WORDS, THUMB_MAX_WORDS = 2, 4
# The writer is asked for five; the upload offers at most these.
TITLES_OFFERED = 5

# READS AS A CALL. Buy, sell, a target, a crash foretold. "Buyback",
# "sellers" and "sell-off" are facts and pass; "the 1987 crash" is history
# and passes; "about to crash" is a prediction and does not.
_CALL_RE = re.compile(
    r"\b(?:buy|buying|sell|selling)\b(?![- ]?(?:off|side|back)s?\b)"
    r"|\bstrong buy\b|\bprice targets?\b|\btargets?\b"
    r"|\b(?:will|about to|going to|gonna|set to|due to|ready to)\s+crash\b"
    r"|\bcrash(?:es)? (?:is |are )?coming\b|\bnext crash\b"
    r"|\bbefore (?:it|the|they) crash(?:es)?\b"
    r"|\bto the moon\b|\bgoing to zero\b|\bmust[- ](?:own|buy|have)\b",
    re.IGNORECASE)

_WORD_RE = re.compile(r"[a-z0-9']+")
_STOP = frozenset(
    "a an and the of to in on for with at by from is are was were be been it "
    "its this that these those as or but not no so if than then into over "
    "under up down out off just only very what why how who when where which "
    "you your we our i my me he she they them his her their".split())


@dataclass
class TitleCheck:
    """One title option, and what the check made of it."""

    text: str
    pays_off: str = ""
    # Reasons it is NOT offered. Empty means the upload may use it.
    refused: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def offered(self) -> bool:
        return not self.refused


# --------------------------------------------------------------------------
# What the video says and shows.
# --------------------------------------------------------------------------


def said_text(script) -> str:
    """Everything the video says or draws: the narration (or the short's
    audio), and every field or tag value that reaches the screen. A title's
    figure has to be one of these."""
    parts: list[str] = []
    if getattr(script, "narration", None):
        parts.append(script.narration)
        for e in getattr(script, "events", None) or []:
            parts.append(str(getattr(e, "payload", "") or ""))
            parts += [str(v) for v in (getattr(e, "values", None) or {}).values()]
        for c in getattr(script, "chapter_list", None) or []:
            parts.append(str(getattr(c, "title", "") or ""))
    elif getattr(script, "audio_script", None):
        try:
            from pipeline.parser_short import _text_surfaces

            parts += list(_text_surfaces(script).values())
        except Exception:  # noqa: BLE001 — the audio alone still serves
            parts.append(script.audio_script)
    return "\n".join(p for p in parts if p)


def _content_words(text: str) -> set[str]:
    return {w for w in _WORD_RE.findall(str(text or "").lower())
            if w not in _STOP and len(w) > 1}


# --------------------------------------------------------------------------
# Figures.
# --------------------------------------------------------------------------

_SCALE = {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6, "b": 1e9,
          "bn": 1e9, "billion": 1e9, "t": 1e12, "trillion": 1e12}
_UNIT_RE = re.compile(r"(?:\d)\s*(thousand|million|billion|trillion|bn|[kmbt])\b", re.I)
_DECIMALS_RE = re.compile(r"\d[\d,]*\.(\d+)")


def _is_year(n) -> bool:
    return (not n.is_percent and float(n.value).is_integer()
            and 1900 <= n.value <= 2100 and n.text.strip().isdigit())


def _same_figure(title_n, said_n) -> bool:
    """Whether a figure said in the script is the title's figure, at the
    precision the title gives it: "$1.1B" is said as "one point one two
    billion", "29%" as "twenty eight point six percent"."""
    a, b = abs(float(title_n.value)), abs(float(said_n.value))
    if a == b:
        return True
    if max(a, b) > 0 and abs(a - b) <= 0.01 * max(a, b):
        return True
    unit = _UNIT_RE.search(title_n.text)
    scale = _SCALE.get(unit.group(1).lower(), 1.0) if unit else 1.0
    dec = _DECIMALS_RE.search(title_n.text)
    places = len(dec.group(1)) if dec else 0
    return round(b / scale, places) == round(a / scale, places)


def unsaid_figures(text: str, said: str) -> tuple[list[str], list[str]]:
    """The figures in `text` the video never gives: (figures, years).

    Years are apart because the narration says them as words two ways
    ("twenty ten", "two thousand and ten"), and a year missed by that is a
    warning, not a title taken away.
    """
    from pipeline.gates import extract_numbers, spoken_figures

    have = extract_numbers(said)
    low = said.lower()
    missing, years = [], []
    # A lone small number word ("one stock", "two kinds") is not a figure.
    for n in spoken_figures(text):
        if any(_same_figure(n, s) for s in have):
            continue
        if _is_year(n):
            if n.text.strip() not in low:
                years.append(n.text.strip())
            continue
        missing.append(n.text.strip())
    return missing, years


# --------------------------------------------------------------------------
# The checks.
# --------------------------------------------------------------------------


def _vendor(text: str) -> str:
    from pipeline.models import VENDOR_WORDS

    low = text.lower()
    return next((w for w in VENDOR_WORDS if w in low), "")


def _swear(text: str) -> str:
    from pipeline.writing_checks import package_swears

    found = package_swears({"title": text})
    if not found:
        return ""
    m = re.search(r"“([^”]+)”", found[0].message)
    return m.group(1) if m else "a swear"


def _hype(text: str) -> str:
    from pipeline.gates import _HYPE

    low = text.lower()
    return next((w for w in _HYPE if re.search(rf"\b{re.escape(w)}\b", low)), "")


def _common_refusals(text: str, said: str, what: str) -> tuple[list[str], list[str]]:
    """What takes a title or the thumbnail's words away, and what only warns."""
    refused, warnings = [], []
    if "<" in text or ">" in text:
        refused.append("YouTube refuses angle brackets in a title")
    swear = _swear(text)
    if swear:
        refused.append(f"“{swear}” — YouTube limits ads for a swear in the {what}")
    call = _CALL_RE.search(text)
    if call:
        refused.append(f"“{call.group(0)}” reads as a call; Dennis never makes one")
    vendor = _vendor(text)
    if vendor:
        refused.append(f"names the data vendor ({vendor})")
    missing, years = unsaid_figures(text, said)
    if missing:
        refused.append(f"{', '.join(missing)} is not a figure the video gives")
    if years:
        warnings.append(f"the video never says {', '.join(years)} as written; "
                        f"check it is the year the script means")
    hype = _hype(text)
    if hype:
        warnings.append(f"“{hype}” is a hype word; the dry version is stronger")
    return refused, warnings


def check_title(text: str, pays_off: str, said: str, *, ticker: str = "") -> TitleCheck:
    from pipeline.writing_checks import _norm, find_joke

    out = TitleCheck(text=text, pays_off=pays_off)
    if len(text) > TITLE_HARD_CHARS:
        out.refused.append(f"{len(text)} characters; YouTube refuses past "
                           f"{TITLE_HARD_CHARS}")
    elif len(text) > TITLE_WARN_CHARS:
        out.warnings.append(f"{len(text)} characters; past {TITLE_WARN_CHARS} "
                            f"it is cut off on a phone")
    refused, warnings = _common_refusals(text, said, "title")
    out.refused += refused
    out.warnings += warnings
    t = (ticker or "").strip().upper()
    head = text.lstrip("\"“'").split()[:1]
    if head and (head[0].startswith("$")
                 or (t and head[0].strip(":,—-").upper() == t)):
        out.warnings.append("opens on the ticker; the story or the verdict "
                            "comes first, the ticker can follow")
    if not pays_off.strip():
        out.warnings.append("names no line that pays it off — which sentence "
                            "of the script answers it?")
    elif find_joke(pays_off, _norm(said).split()) is None:
        out.warnings.append("the line it names as its payoff is not in the "
                            "script, so the video may not answer it")
    return out


def check_titles(script) -> list[TitleCheck]:
    said = said_text(script)
    ticker = str(getattr(script, "ticker", "") or "")
    return [check_title(t.text, t.pays_off, said, ticker=ticker)
            for t in getattr(script, "titles", None) or []]


@dataclass
class ThumbCheck:
    text: str
    refused: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def check_thumbnail_text(text: str, title: str, said: str) -> ThumbCheck:
    out = ThumbCheck(text=text)
    if not text.strip():
        return out
    words = text.split()
    if not THUMB_MIN_WORDS <= len(words) <= THUMB_MAX_WORDS:
        out.warnings.append(f"{len(words)} words; a thumbnail reads "
                            f"{THUMB_MIN_WORDS} to {THUMB_MAX_WORDS} at phone size")
    refused, warnings = _common_refusals(text, said, "thumbnail")
    out.refused += refused
    out.warnings += warnings
    mine = _content_words(text)
    if mine and title and mine <= _content_words(title):
        out.warnings.append("repeats the title; the thumbnail should add to "
                            "it, not say it twice")
    return out


# --------------------------------------------------------------------------
# What the upload offers.
# --------------------------------------------------------------------------


def fallback_titles(ticker: str, hook: str, runtime_min: float = 0.0) -> list[str]:
    """The bot's own two, for a script written before the writer wrote
    titles, or one whose every title was refused. The old third, "the
    numbers nobody screenshots", was a phrase the prompts list as used up."""
    out = [f"{ticker} — {hook[:70].rstrip('.')}" if hook else ticker,
           f"What ${ticker} actually is, {runtime_min:.0f} minutes"
           if runtime_min else f"What ${ticker} actually is"]
    return [t for t in out if t.strip()]


@dataclass
class TitlePick:
    titles: list[str]
    payoffs: list[str]
    notes: list[str]
    thumbnail_text: str
    from_writer: bool


def pick_titles(script, *, ticker: str = "", hook: str = "",
                runtime_min: float = 0.0, chosen: str = "") -> TitlePick:
    """The titles the upload offers, best first, and why any were left out.

    The writer's own, in the writer's order, with `chosen` (the one the
    operator picked on the page) moved to the top. The bot's two only when
    the writer wrote none the check lets through.
    """
    ticker = (ticker or getattr(script, "ticker", "") or "").upper()
    checks = check_titles(script)
    notes: list[str] = []
    titles, payoffs = [], []
    for n, c in enumerate(checks, 1):
        if c.offered:
            if c.text not in titles:
                titles.append(c.text)
                payoffs.append(c.pays_off)
        else:
            notes.append(f"Title {n} not offered: “{c.text[:80]}” — "
                         + "; ".join(c.refused))
    titles, payoffs = titles[:TITLES_OFFERED], payoffs[:TITLES_OFFERED]
    from_writer = bool(titles)
    if not titles:
        titles = fallback_titles(ticker, hook, runtime_min)
        payoffs = [""] * len(titles)
        notes.append("The writer's titles were all refused, so these are the "
                     "bot's own." if checks else
                     "This script has no titles from the writer, so these are "
                     "the bot's own.")
    if chosen and chosen in titles:
        k = titles.index(chosen)
        titles.insert(0, titles.pop(k))
        payoffs.insert(0, payoffs.pop(k))
    thumb = str(getattr(script, "thumbnail_text", "") or "")
    if thumb:
        tc = check_thumbnail_text(thumb, titles[0] if titles else "", said_text(script))
        if tc.refused:
            notes.append(f"Thumbnail words not used: “{thumb}” — "
                         + "; ".join(tc.refused))
            thumb = ""
    return TitlePick(titles=titles, payoffs=payoffs, notes=notes,
                     thumbnail_text=thumb, from_writer=from_writer)


def title_findings(script) -> list:
    """Every title and the thumbnail's words, as findings for the script
    check, so a refused title is read before the render rather than
    discovered on the upload page."""
    from pipeline.gates import Finding

    checks = check_titles(script)
    out = []
    if not checks:
        what = ("a `=== TITLES ===` trailer"
                if getattr(script, "narration", None) else "the `titles` field")
        out.append(Finding(
            gate="title", severity="warn",
            message=(f"no titles from the writer ({what}); the upload "
                     f"offers the bot's own two")))
        return out
    for n, c in enumerate(checks, 1):
        for why in c.refused:
            out.append(Finding(gate="title", severity="warn",
                               message=f"title {n} is not offered: {why}",
                               excerpt=c.text[:90]))
        for why in c.warnings:
            out.append(Finding(gate="title", severity="warn",
                               message=f"title {n}: {why}",
                               excerpt=c.text[:90]))
    thumb = str(getattr(script, "thumbnail_text", "") or "")
    first = next((c.text for c in checks if c.offered), "")
    if not thumb:
        out.append(Finding(
            gate="title", severity="warn",
            message=("no thumbnail words — 2 to 4 that add to the title; the "
                     "Figma prompt has nothing to put on the cover")))
    else:
        tc = check_thumbnail_text(thumb, first, said_text(script))
        for why in tc.refused:
            out.append(Finding(gate="title", severity="warn",
                               message=f"the thumbnail words are not used: {why}",
                               excerpt=thumb))
        for why in tc.warnings:
            out.append(Finding(gate="title", severity="warn",
                               message=f"thumbnail words: {why}", excerpt=thumb))
    return out


# --------------------------------------------------------------------------
# His pick on the page.
# --------------------------------------------------------------------------

CHOICE_FILE = "title_choice.json"


def chosen_title(ws_path, fmt: str) -> str:
    """The title he picked on the upload page for this format, or ""."""
    import json
    from pathlib import Path

    try:
        data = json.loads((Path(ws_path) / CHOICE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str(data.get(fmt) or "") if isinstance(data, dict) else ""


def set_chosen_title(ws_path, fmt: str, title: str) -> None:
    import json
    from pathlib import Path

    path = Path(ws_path) / CHOICE_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    if title:
        data[fmt] = title
    else:
        data.pop(fmt, None)
    from pipeline.workspace import _write

    _write(path, json.dumps(data, indent=2, ensure_ascii=False))


# --------------------------------------------------------------------------
# What the writing prompts say (T2). One text for every lane, so the long,
# the update, the shorts and the implosion lane are held to the same rules.
# --------------------------------------------------------------------------

TITLE_RULES = f"""\
The title is the one line of the video most people ever read, and it is yours to write. Five options, your favourite first. These are shapes; never copy another channel's title, and never use these example words as they are:
- The story or the verdict first, never the ticker. No title opens on a symbol or on the ticker; the company's or the person's name may open it ("Intel's...", "The board that...").
- One concrete figure, best set against another: a cost against a result, a size against a time. Only a figure the video gives: the bot takes away any title with a figure the script never says.
- One judging word on a finance noun: a hopeless buyback, a frightening balance sheet, a sad little dividend.
- A format label when the video has one: graded, tested, explained, vs, a tier list.
- Or flat understatement, in lowercase, for the dry ones.
- Under {TITLE_WARN_CHARS} characters, so a phone shows all of it. The bot warns past {TITLE_WARN_CHARS} and refuses past {TITLE_HARD_CHARS}. No swear, no buy, sell, target or crash call, no hype word.
- The video answers it. Next to each title, copy the sentence of the script that pays it off, word for word; the bot reads it back.

The thumbnail gets {THUMB_MIN_WORDS} to {THUMB_MAX_WORDS} words of its own that ADD to the title instead of repeating it: the title says what happened, the thumbnail says how it feels, or gives the one figure. Same rules: no swear, no call, only the video's own figures. The operator makes the thumbnail from them."""


def long_titles_block() -> str:
    """The `=== TITLES ===` trailer, as the long lanes ask for it."""
    return f"""Then a `=== TITLES ===` trailer: five title options, your favourite first, one a line, as `title | the narration sentence that pays it off, word for word`, and last a `Thumbnail:` line. It is never spoken. The operator sees them on the upload page with your favourite on top, and can pick another.

{TITLE_RULES}

=== TITLES ===
<the story or the verdict first, one figure the narration says> | <the sentence that answers it, copied from the narration>
<title 2> | <its sentence>
<title 3> | <its sentence>
<title 4> | <its sentence>
<title 5> | <its sentence>
Thumbnail: <{THUMB_MIN_WORDS} to {THUMB_MAX_WORDS} words that add to the title>"""


def short_titles_block() -> str:
    """The `titles` and `thumbnail_text` fields, as the short lanes ask."""
    return f"""### TITLES — the `titles` and `thumbnail_text` fields

{TITLE_RULES}

In the JSON: `titles` is five objects, your favourite first, each `{{"title": "...", "pays_off": "<the audio_script sentence that answers it, word for word>"}}`; `thumbnail_text` is the {THUMB_MIN_WORDS} to {THUMB_MAX_WORDS} words. Neither is spoken or drawn in the video."""
