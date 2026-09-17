"""Inline keyboards for the approval flow (§9.2).

Callback data grammar (64-byte Telegram limit — keep it terse):
    a|<fmt>|<ticker>|<date>|<sha8>     approve
    x|<fmt>|<ticker>|<date>           cancel
    w|<ticker>|<date>                 open the swap-clip menu (LONG)
    s|<ticker>|<date>|<i>             swap visual #i to its next take
    n|<lane>|<ticker>                 open a screener candidate in its own lane
    fv|<ticker>|<date>|<file>         veto (drop) an auto-pulled filing shot
"""

from __future__ import annotations

# `python-telegram-bot` is a real dependency of the running bot, but it is a
# dependency of the FRONTEND only: `BotCore` handles strings and bytes and
# treats a keyboard as an opaque object it hands back. Importing it at module
# scope made three test modules — including the one whose own docstring says
# "WITHOUT Telegram" — fail at COLLECTION on a checkout that had not installed
# it, which turns one missing wheel into a suite that cannot start.
#
# So the buttons degrade to a plain data shape. The frontend still gets real
# Telegram objects wherever the package is installed, which is everywhere it
# is actually sending messages from.
try:  # pragma: no cover - exercised by whichever branch the env provides
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
except ImportError:  # pragma: no cover
    from dataclasses import dataclass, field

    @dataclass
    class InlineKeyboardButton:      # type: ignore[no-redef]
        text: str
        callback_data: str = ""

    @dataclass
    class InlineKeyboardMarkup:      # type: ignore[no-redef]
        inline_keyboard: list = field(default_factory=list)


def approval_keyboard(fmt: str, ticker: str, workdate: str, sha: str,
                      approvable: bool, has_broll: bool) -> InlineKeyboardMarkup:
    rows = []
    row = []
    if approvable:
        row.append(InlineKeyboardButton(
            "Approve ✅", callback_data=f"a|{fmt}|{ticker}|{workdate}|{sha[:8]}"
        ))
    if has_broll:
        row.append(InlineKeyboardButton(
            "Swap clip 🔄", callback_data=f"w|{ticker}|{workdate}"
        ))
    row.append(InlineKeyboardButton(
        "Cancel ❌", callback_data=f"x|{fmt}|{ticker}|{workdate}"
    ))
    rows.append(row)
    return InlineKeyboardMarkup(rows)


# Telegram rejects callback data over 64 BYTES, and rejects the whole markup
# when one button is over — so the menu failed with "internal error" rather
# than dropping a button (G4). `s|` + ticker + `|` + a 10-char date + `|`
# leaves roughly 44 bytes, and the payload that went in there was a
# free-text clip subject the prompt actively encourages writing in full.
#
# An index is bounded by construction, and it pairs with G5: the index is
# the occurrence, so two beats that share a subject are separately
# swappable.
CALLBACK_DATA_MAX = 64


def swap_keyboard(ticker: str, workdate: str,
                  keys: list[str]) -> InlineKeyboardMarkup:
    """One button per swappable visual, addressed BY INDEX.

    `keys` is the label list in plan order; the index is what travels, and
    the handler resolves it against the stored plan.
    """
    rows = []
    for i in range(0, len(keys), 2):
        row = []
        for j, k in enumerate(keys[i:i + 2], start=i):
            label = k if len(k) <= 28 else k[:27] + "…"
            row.append(InlineKeyboardButton(
                f"🔄 {label}", callback_data=f"s|{ticker}|{workdate}|{j}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("◀ back to report", callback_data=f"w!|{ticker}|{workdate}")])
    return InlineKeyboardMarkup(rows)


def filing_veto_keyboard(ticker: str, workdate: str,
                         names: list[str]) -> InlineKeyboardMarkup:
    """One drop button per auto-pulled filing shot (veto a bad crop)."""
    rows = []
    row = []
    # Same shape as the swap menu, same reason: a filename in the callback
    # data blows the 64-byte limit and takes the whole markup with it (G4).
    for i, _name in enumerate(names, 1):
        row.append(InlineKeyboardButton(
            f"❌ drop #{i}", callback_data=f"fv|{ticker}|{workdate}|{i - 1}"
        ))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(rows)


# The screener puts every candidate in a lane, and that lane is the whole
# reason the candidate is on the list — a trending name is SHORT material, a
# beaten-down one is LONG material. Dropping it on the way to the button was
# what made the button open a lane-less workspace (G3), which is one of the
# inputs to the format-resolution mess in Group C. So the lane rides in the
# callback data and the handler routes to `start_lane`, not to a lane-less
# alias that has to guess.
LANE_CODES = {"short": "s", "long": "l"}
CODE_LANES = {v: k for k, v in LANE_CODES.items()}


def candidates_keyboard(
    candidates: list[tuple[str, str]],
) -> InlineKeyboardMarkup:
    """One button per candidate, as `(ticker, lane)` pairs.

    `lane` is "short" or "long"; anything else is treated as "short", which
    is what a trending candidate is and the cheaper mistake of the two.
    """
    rows = []
    for i in range(0, len(candidates), 3):
        row = []
        for ticker, lane in candidates[i:i + 3]:
            code = LANE_CODES.get(lane, "s")
            cmd = "short" if code == "s" else "long"
            row.append(InlineKeyboardButton(
                f"/{cmd} {ticker}", callback_data=f"n|{code}|{ticker}"))
        rows.append(row)
    return InlineKeyboardMarkup(rows)
