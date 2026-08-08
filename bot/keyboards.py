"""Inline keyboards for the approval flow (§9.2).

Callback data grammar (64-byte Telegram limit — keep it terse):
    a|<fmt>|<ticker>|<date>|<sha8>     approve
    x|<fmt>|<ticker>|<date>           cancel
    w|<ticker>|<date>                 open the swap-clip menu (LONG)
    s|<ticker>|<date>|<key>           swap this b-roll key to its next take
    n|<ticker>                        fire /new from a screener candidate
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


def swap_keyboard(ticker: str, workdate: str, keys: list[str]) -> InlineKeyboardMarkup:
    rows = []
    for i in range(0, len(keys), 2):
        rows.append([
            InlineKeyboardButton(f"🔄 {k}", callback_data=f"s|{ticker}|{workdate}|{k}")
            for k in keys[i:i + 2]
        ])
    rows.append([InlineKeyboardButton("◀ back to report", callback_data=f"w!|{ticker}|{workdate}")])
    return InlineKeyboardMarkup(rows)


def filing_veto_keyboard(ticker: str, workdate: str,
                         names: list[str]) -> InlineKeyboardMarkup:
    """One drop button per auto-pulled filing shot (veto a bad crop)."""
    rows = []
    row = []
    for i, name in enumerate(names, 1):
        row.append(InlineKeyboardButton(
            f"❌ drop #{i}", callback_data=f"fv|{ticker}|{workdate}|{name}"
        ))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(rows)


def candidates_keyboard(tickers: list[str]) -> InlineKeyboardMarkup:
    rows = []
    for i in range(0, len(tickers), 3):
        rows.append([
            InlineKeyboardButton(f"/new {t}", callback_data=f"n|{t}")
            for t in tickers[i:i + 3]
        ])
    return InlineKeyboardMarkup(rows)
