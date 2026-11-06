"""The fix-up prompt: everything the checks found, as one message for the
writer.

Valentin writes scripts by pasting the bot's prompt into his own Claude chat.
When the checks come back (RDDT long, 1 Nov 2026: eight blocks, six copy
blocks over their boxes, two refused moves, seventeen stretches of Dennis
alone and a page of warnings) every one of them was his to carry back to
that chat by hand. This turns the Check step's findings into the message he
pastes there, so the writer that wrote the script fixes it in one pass.

Only what the writer can act on goes in: what stops Approve, and the
warnings that are about the words or the tags. Notes, the skeptic's
counterpoints and the claims to check himself stay on the page.
"""

from __future__ import annotations

import re

# Warnings worth a writer's pass, by gate.
_WARN_GATES = frozenset({"budget", "kit", "joke-floor", "jokes", "direction",
                         "prompt-words", "density", "persona"})
# ...and by what an ungated report line says.
_WARN_WORDS = ("Dennis is alone", "holds him in one shot", "tagging density",
               "below the floor of", "is a region the plate sets no type in",
               "no imagery resolved",
               # a [WEB] address the writer has to change
               "is not opened:", "there is no page at that address")
# Never: they are the bot's to fix or his to decide, not the writer's.
_SKIP_WORDS = ("not in the vetted palette", "you let this through",
               "is a website or app screen", "blocks the bot's browser",
               "has no shot:")

MAX_ITEMS = 60

_FACT_HELP = (
    "For each figure the fact-check could not match: if the figure is "
    "right, say plainly what it is (per user, per share, a share of "
    "revenue, one segment, which period) so it cannot be read as another "
    "line of the workbook; if it is wrong, correct it from the workbook.")
_ALONE_HELP = (
    "Dennis is on screen alone too long. In each stretch named below, "
    "never more than about fifty words (twenty seconds) without a visual "
    "tag: put the figure he is saying on a [PLATE] or [CHART], or a [CLIP] "
    "that proves the line. A new [SCENE] is still Dennis alone.")


def _is_alone(f: dict) -> bool:
    msg = f.get("message", "")
    return "Dennis is alone" in msg or "holds him in one shot" in msg


def _wanted(f: dict) -> bool:
    msg = f.get("message", "")
    if any(w in msg for w in _SKIP_WORDS):
        return False
    if f.get("severity") == "block":
        return True
    if f.get("severity") != "warn":
        return False
    gate = (f.get("gate") or "").lower()
    if gate == "kit" and re.search(r"leaves .* empty", msg):
        return False            # an empty slot is often the honest choice
    return gate in _WARN_GATES or any(w in msg for w in _WARN_WORDS)


def _item(f: dict) -> str:
    gate = f.get("gate") or ""
    line = (f"[{gate}] " if gate else "") + " ".join(f.get("message", "").split())
    if f.get("excerpt"):
        line += f"\n   The sentence: “{f['excerpt'].strip()}”"
    return line


def fixup_prompt(findings: list[dict], fmt: str) -> str:
    """The message for the writer's chat, or "" when there is nothing in
    `findings` (the Check step's parsed report lines) for it to fix."""
    wanted = [f for f in findings if _wanted(f)]
    if not wanted:
        return ""
    alone = [f for f in wanted if _is_alone(f)]
    rest = [f for f in wanted if not _is_alone(f)]
    must = [f for f in rest if f.get("severity") == "block"]
    should = [f for f in rest if f.get("severity") != "block"]

    if fmt == "short":
        shape = ("the whole JSON again, every field, in the same shape")
    else:
        shape = ("the WHOLE script again in the same format: the narration "
                 "with its tags, then the === CHAPTERS === and === JOKES === "
                 "trailers (and === CONFESSION === if it had one)")
    out = [
        "The bot checked the script you wrote and found the problems below. "
        f"Fix each one and send back {shape}. Change only what a line below "
        "asks for and keep every other sentence word for word; keep the "
        "jokes list matching the narration.",
    ]
    n = 0
    if must:
        out += ["", "MUST FIX — the video will not render until these are gone:"]
        for f in must[:MAX_ITEMS]:
            n += 1
            out.append(f"{n}. {_item(f)}")
        if any((f.get("gate") or "") == "fact-check" for f in must):
            out.append(_FACT_HELP)
    if alone:
        out += ["", "DENNIS ALONE — " + _ALONE_HELP]
        for f in alone[:MAX_ITEMS]:
            n += 1
            out.append(f"{n}. {_item(f)}")
    if should and n < MAX_ITEMS:
        out += ["", "SHOULD FIX:"]
        for f in should[:MAX_ITEMS - n]:
            n += 1
            out.append(f"{n}. {_item(f)}")
    return "\n".join(out).strip()
