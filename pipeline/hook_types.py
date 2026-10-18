"""Opener types (S11): which kind of first line, so they rotate.

A channel whose every video opens on a figure that sounds wrong is a
channel whose opener the viewer has learned to skip. There are five kinds
of opener this register uses, and the cheapest variety there is, is not
using the same one twice running:

* **number** — one figure that sounds wrong, stated flat;
* **question** — a question the video answers, asked straight;
* **withheld** — the thing described completely before it is named;
* **confession** — Dennis admits something, specifically;
* **contradiction** — two true things that cannot both feel right.

The kind is read off the words, by rule, so it costs nothing and works on
every opener the corpus already holds. The prompt is told the recent kinds
and handed the one used least recently; `/hooks` reads retention by kind
once there are published videos to read it from.
"""

from __future__ import annotations

import re

from config import Settings

HOOK_TYPES = ("number", "question", "withheld", "confession", "contradiction")

DEFINITIONS = {
    "number": "one figure that sounds wrong, stated flat, and nothing else",
    "question": "a question this video answers, asked straight, never "
                "rhetorical",
    "withheld": "describe the thing completely — what it sells, how fast it "
                "grew, who buys it — and name it last",
    "confession": "Dennis admits something specific about himself and this "
                  "company (it counts as the video's confession)",
    "contradiction": "two true facts side by side that cannot both feel "
                     "right",
}

_CONFESSION_RE = re.compile(
    r"^\s*I\b|\bI(?:'ve| have| had)?\s+(?:bought|sold|lost|owned|paid|got|"
    r"was|did|held|shorted)\b|\bmy (?:account|portfolio|position|shares)\b",
    re.IGNORECASE)
_WITHHELD_RE = re.compile(
    r"\bnot\s+[^.?!]{1,40}[.]\s+not\b|^\s*(?:a|an|one)\s+(?:business|company|"
    r"stock|firm|brand)\s+(?:that|which|with)\b", re.IGNORECASE)
_CONTRADICTION_RE = re.compile(
    r"\b(?:but|yet|and still|despite|even though|which is strange|and "
    r"somehow|anyway)\b", re.IGNORECASE)


def classify_hook(text: str) -> str:
    """The kind of opener, or "other". Earlier kinds win: a confession that
    asks a question is still a confession."""
    text = " ".join((text or "").split())
    if not text:
        return "other"
    if _CONFESSION_RE.search(text):
        return "confession"
    if "?" in text:
        return "question"
    if _WITHHELD_RE.search(text):
        return "withheld"
    if _CONTRADICTION_RE.search(text):
        return "contradiction"
    from pipeline.gates import spoken_figures

    if spoken_figures(text):
        return "number"
    return "other"


def recent_hook_types(settings: Settings, fmt: str, n: int = 6) -> list[str]:
    """The kinds of the last n shipped openers of this format, newest last."""
    from pipeline.corpus import Corpus

    try:
        rows = [e for e in Corpus(settings).recent(0, fmt=fmt) if e.shipped]
    except Exception:                              # noqa: BLE001
        return []
    return [classify_hook(e.hook) for e in rows[-n:]]


def pick_hook_type(recent: list[str], *, allow_confession: bool = True) -> str:
    """The kind used least recently; never used beats used, ties go in
    `HOOK_TYPES` order."""
    kinds = [k for k in HOOK_TYPES if allow_confession or k != "confession"]

    def last_seen(kind: str) -> int:
        for back, seen in enumerate(reversed(recent)):
            if seen == kind:
                return back
        return len(recent) + 1

    return max(kinds, key=lambda k: (last_seen(k), -kinds.index(k)))


def hook_type_block(settings: Settings, fmt: str) -> str:
    """{{hook_type}}: the recent kinds, and the kind to open this one with."""
    from pipeline.standing import ConfessionLedger

    lane = "short" if fmt in ("short", "headline") else "long"
    recent = recent_hook_types(settings, lane)
    try:
        confess = lane == "short" or ConfessionLedger(settings).due()
    except Exception:                              # noqa: BLE001
        confess = False
    pick = pick_hook_type(recent, allow_confession=confess)
    seen = (f"The last {len(recent)} {lane} openers were, newest last: "
            f"{', '.join(recent)}." if recent else
            f"No {lane} openers on record yet.")
    kinds = "; ".join(f"{k} ({DEFINITIONS[k]})" for k in HOOK_TYPES)
    return (f"{seen} Open THIS one with a **{pick}** opener: "
            f"{DEFINITIONS[pick]}. The five kinds rotate so no viewer learns "
            f"to skip the first line: {kinds}.")


def bench_by_type(bench) -> list[tuple[str, float, int]]:
    """(kind, mean hold over the opening window, videos), best first."""
    groups: dict[str, list[float]] = {}
    for hook in bench:
        groups.setdefault(classify_hook(hook.text), []).append(hook.hold)
    rows = [(k, sum(v) / len(v), len(v)) for k, v in groups.items()]
    return sorted(rows, key=lambda r: r[1], reverse=True)
