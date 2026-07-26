"""In-chat script revision (P3.1c).

The operator picks the ticker and the angle and tweaks the wording — and until
now the tweak meant going back to Claude, re-pasting the whole script, and
re-reading a fresh report. For "cut that one line" or "that number is 4.6, not
4.7", that is a lot of ceremony.

This module is the text surgery, kept away from the bot so it can be reasoned
about on its own. Four operations, all addressed the way the operator sees the
script in chat — by line number, or by the words themselves:

    /edit 12 <new text>      replace line 12
    /edit 12-14 <new text>   replace a range with one line
    /edit 12                 delete line 12
    /replace old => new      first exact occurrence
    /replace all: old => new every occurrence

The invariant that makes this safe to use on an approved script: **an edit
that does not parse never lands.** The caller applies the edit to a candidate
string, runs it back through the ordinary intake — the same parser, the same
gates, the same cost report — and only stores it if that succeeds. A rejected
edit leaves the script exactly as it was, and `/undo` steps back through the
ones that did land.

Line numbers are 1-based and count every line of the raw script, blank ones
included, because that is what `/script` prints. Anything else would have the
operator counting non-blank lines in their head.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# `=>` is the separator: it cannot appear in a bracket tag and reads as an
# arrow in chat. `->` would collide with prose.
REPLACE_SEP = "=>"
_RANGE_RE = re.compile(r"^(\d+)\s*(?:-|–|\.\.)\s*(\d+)$")
_ALL_PREFIX = re.compile(r"^all\s*:\s*", re.IGNORECASE)


class EditError(ValueError):
    """The edit command itself was malformed or out of range."""


@dataclass
class EditResult:
    text: str
    summary: str            # what changed, for the chat reply
    changed_lines: list[int]


def numbered(raw: str, *, width: int = 3) -> str:
    """The script as the operator will see it, so line numbers agree."""
    lines = raw.splitlines()
    return "\n".join(f"{i:>{width}} | {ln}" for i, ln in enumerate(lines, 1))


def _split_lines(raw: str) -> tuple[list[str], bool]:
    """Lines plus whether the original ended in a newline, so rejoining is
    byte-identical when nothing changed."""
    return raw.splitlines(), raw.endswith("\n")


def _join(lines: list[str], trailing: bool) -> str:
    out = "\n".join(lines)
    return out + "\n" if trailing else out


def parse_target(token: str, n_lines: int) -> tuple[int, int]:
    """`"12"` -> (12, 12); `"12-14"` -> (12, 14). 1-based, inclusive."""
    token = token.strip()
    m = _RANGE_RE.match(token)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
    elif token.isdigit():
        lo = hi = int(token)
    else:
        raise EditError(
            f"{token!r} is not a line number or range. Try `/edit 12 new text`, "
            f"`/edit 12-14 new text`, or `/replace old {REPLACE_SEP} new`.")
    if lo < 1 or hi < lo:
        raise EditError(f"line range {token!r} runs backwards or starts below 1.")
    if hi > n_lines:
        raise EditError(
            f"the script has {n_lines} lines — {hi} is past the end. "
            f"Send /script to see it numbered.")
    return lo, hi


def edit_lines(raw: str, target: str, replacement: str) -> EditResult:
    """Replace (or delete) a line or an inclusive range of lines.

    A range collapses to the single replacement line, which is what "replace
    beats 12 to 14 with this one" means. An empty replacement deletes.
    """
    lines, trailing = _split_lines(raw)
    lo, hi = parse_target(target, len(lines))
    new = replacement.rstrip("\n")

    before = lines[lo - 1:hi]
    if new != "" and before == new.split("\n"):
        # An operator re-sending the same text should not be told it worked.
        raise EditError(
            f"line {lo} already reads exactly that." if lo == hi
            else f"lines {lo}–{hi} already read exactly that.")

    if new == "":
        lines[lo - 1:hi] = []
        summary = (f"deleted line {lo}" if lo == hi
                   else f"deleted lines {lo}–{hi}")
        touched: list[int] = []
    else:
        # A multi-line replacement is allowed — the operator may paste a
        # rewritten paragraph — and each of its lines becomes a script line.
        fresh = new.split("\n")
        lines[lo - 1:hi] = fresh
        span = f"line {lo}" if lo == hi else f"lines {lo}–{hi}"
        summary = f"replaced {span}"
        if len(fresh) > 1:
            summary += f" with {len(fresh)} lines"
        touched = list(range(lo, lo + len(fresh)))

    return EditResult(_join(lines, trailing), summary, touched)


def replace_text(raw: str, spec: str) -> EditResult:
    """`old => new`, first occurrence — or `all: old => new` for every one.

    Find-and-replace is the operation the operator actually reaches for when a
    figure is wrong, because the wrong figure is what they can see. `all:`
    exists because a number usually appears in both the narration and a card.
    """
    spec = spec.strip()
    every = bool(_ALL_PREFIX.match(spec))
    if every:
        spec = _ALL_PREFIX.sub("", spec, count=1)
    if REPLACE_SEP not in spec:
        raise EditError(
            f"use `/replace old text {REPLACE_SEP} new text` "
            f"(or `/replace all: old {REPLACE_SEP} new`).")
    old, new = spec.split(REPLACE_SEP, 1)
    old, new = old.strip(), new.strip()
    if not old:
        raise EditError("nothing to search for — put the old text first.")
    if old not in raw:
        raise EditError(f"{old!r} does not appear in the script. "
                        f"Send /script to see it as stored.")
    hits = raw.count(old)
    if every:
        text = raw.replace(old, new)
        summary = (f"replaced {hits} occurrence{'s' if hits != 1 else ''} of "
                   f"{_clip(old)}")
    else:
        if hits > 1:
            # Silently editing the first of several is how the wrong number
            # survives in the second half of the script.
            summary_hint = (f"{_clip(old)} appears {hits} times — editing the "
                            f"first. Use `/replace all: …` for every one.")
        else:
            summary_hint = ""
        text = raw.replace(old, new, 1)
        summary = f"replaced {_clip(old)}"
        if summary_hint:
            summary += f"\n⚠️ {summary_hint}"
    if not new:
        summary = summary.replace("replaced", "deleted")

    changed = [i for i, (a, b) in enumerate(
        zip(raw.splitlines(), text.splitlines()), 1) if a != b]
    return EditResult(text, summary, changed)


def _clip(text: str, n: int = 48) -> str:
    flat = " ".join(text.split())
    return repr(flat if len(flat) <= n else flat[: n - 1] + "…")


def diff_lines(before: str, after: str, context: int = 0) -> str:
    """A compact before/after for the chat reply.

    Not a unified diff: the operator wants to see the line they just changed,
    not learn to read diff syntax.
    """
    a, b = before.splitlines(), after.splitlines()
    out: list[str] = []
    if len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b), 1):
            if x != y:
                out.append(f"{i:>3} −  {x}")
                out.append(f"{i:>3} +  {y}")
    else:
        # Lines shifted; show the neighbourhood of the first divergence.
        first = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y),
                     min(len(a), len(b)))
        lo = max(0, first - context)
        for i in range(lo, min(len(a), first + 1 + context)):
            out.append(f"{i + 1:>3} −  {a[i]}")
        for i in range(lo, min(len(b), first + 1 + context)):
            out.append(f"{i + 1:>3} +  {b[i]}")
    return "\n".join(out[:24])
