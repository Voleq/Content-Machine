"""Inline keyboards for the approval flow (§9.2).

Callback data grammar (64-byte Telegram limit — keep it terse):
    a|<fmt>|<ticker>|<date>|<sha8>     approve
    x|<fmt>|<ticker>|<date>           cancel
    w|<ticker>|<date>                 open the swap-clip menu (LONG)
    w!|<ticker>|<date>                back from the swap menu to the report
    s|<ticker>|<date>|<i>             swap visual #i to its next take
    n|<lane>|<ticker>                 open a screener candidate in its own lane
    fv|<ticker>|<date>|<i>            veto (drop) auto-pulled filing shot #i

The next-step buttons (one tap to the obvious next thing):
    e|<ticker>|<date>                 the script, numbered, ready to edit
    k|<ticker>|<date>                 the stored report again, with Approve
    g|<ticker>|<date>|<n>             LONG angle pick #n
    p|<ticker>|<date>                 re-send the prompt
    q|<d|p|c>|<ticker>|<date>|<s|l>   queue a FREE pass: draft, proof, clips
    r|<s|l>|<ticker>|<date>           ask before a PAID render (shows the cost)
    r!|<s|l>|<ticker>|<date>          the paid render, confirmed
    u|<s|l>|<ticker>|<date>           upload private
    us|<s|l>|<ticker>|<date>          upload scheduled (asks for the time)
    rt|<ticker>                       retention for the newest upload
    cr|<ticker>                       pin a correction (asks for the text)
    c|<ticker>|<date>                 the video card
    j|<ticker>|<date>                 cancel that video's jobs
    z                                 undo the last cancel (within a minute)
    ib                                the inbox
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
    from telegram import ForceReply, InlineKeyboardButton, InlineKeyboardMarkup
except ImportError:  # pragma: no cover
    from dataclasses import dataclass, field

    @dataclass
    class InlineKeyboardButton:      # type: ignore[no-redef]
        text: str
        callback_data: str = ""

    @dataclass
    class InlineKeyboardMarkup:      # type: ignore[no-redef]
        inline_keyboard: list = field(default_factory=list)

    @dataclass
    class ForceReply:                # type: ignore[no-redef]
        input_field_placeholder: str = ""


FMT_CODES = {"short": "s", "long": "l"}
CODE_FMTS = {v: k for k, v in FMT_CODES.items()}


def _b(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text, callback_data=data)


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
    # The edit is the other answer to a report, and it used to be a command
    # you had to remember the shape of.
    rows.append([_b("Edit ✏️", f"e|{ticker}|{workdate}"),
                 _b("Card 📁", f"c|{ticker}|{workdate}")])
    return InlineKeyboardMarkup(rows)


def angle_keyboard(ticker: str, workdate: str, count: int = 3,
                   ) -> InlineKeyboardMarkup:
    """The LONG's Step 1 returns two or three ranked angles; picking one was
    typing a number. A tweak still goes in as text."""
    return InlineKeyboardMarkup([[
        _b(f"Angle {n}", f"g|{ticker}|{workdate}|{n}")
        for n in range(1, count + 1)]])


def approved_keyboard(fmt: str, ticker: str, workdate: str,
                      est_usd: float | None) -> InlineKeyboardMarkup:
    """After Approve: the two free looks and the paid render, side by side,
    with the price on the button that spends."""
    code = FMT_CODES.get(fmt, "s")
    price = f" ~${est_usd:.2f}" if est_usd else ""
    row = []
    if fmt == "long":
        row.append(_b("Draft $0", f"q|d|{ticker}|{workdate}|{code}"))
    row.append(_b("Proof $0", f"q|p|{ticker}|{workdate}|{code}"))
    row.append(_b(f"Render 💰{price}", f"r|{code}|{ticker}|{workdate}"))
    return InlineKeyboardMarkup([row])


def confirm_render_keyboard(fmt: str, ticker: str,
                            workdate: str) -> InlineKeyboardMarkup:
    """The money moment needs a second tap — and "Not now" comes first, so
    the paid button is never where the eye and the thumb land."""
    code = FMT_CODES.get(fmt, "s")
    return InlineKeyboardMarkup([[
        _b("Not now", f"c|{ticker}|{workdate}"),
        _b("Confirm 💰", f"r!|{code}|{ticker}|{workdate}")]])


def queued_keyboard(ticker: str, workdate: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        _b("Card 📁", f"c|{ticker}|{workdate}"),
        _b("Cancel 🚫", f"j|{ticker}|{workdate}")]])


def delivered_keyboard(fmt: str, ticker: str, workdate: str,
                       final: bool = True) -> InlineKeyboardMarkup:
    """What a finished render is for. A proof or a draft leads to the
    final; a final leads to YouTube."""
    code = FMT_CODES.get(fmt, "s")
    if not final:
        return InlineKeyboardMarkup([[
            _b("Render final 💰", f"r|{code}|{ticker}|{workdate}"),
            _b("Card 📁", f"c|{ticker}|{workdate}")]])
    rows = [[_b("Upload private", f"u|{code}|{ticker}|{workdate}"),
             _b("Schedule…", f"us|{code}|{ticker}|{workdate}")]]
    if fmt == "long":
        rows.append([_b("Cut clips ✂️ $0", f"q|c|{ticker}|{workdate}|l")])
    return InlineKeyboardMarkup(rows)


def uploaded_keyboard(ticker: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        _b("Retention 📊", f"rt|{ticker}"),
        _b("Correct…", f"cr|{ticker}")]])


def undo_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[_b("Undo ↩️ (1 min)", "z")]])


def inbox_keyboard(items: list, limit: int = 6) -> InlineKeyboardMarkup:
    """One button per waiting thing, for the first few: the inbox is a list
    of next steps, so each line is one tap from done."""
    rows = []
    for it in items[:limit]:
        t, d = it.ticker, it.workdate
        if it.action == "approve" and d:
            data, label = f"k|{t}|{d}", f"{t}: report → approve"
        elif it.action == "edit" and d:
            data, label = f"e|{t}|{d}", f"{t}: edit"
        elif it.action == "render" and d:
            data, label = f"c|{t}|{d}", f"{t}: render…"
        elif it.action == "upload" and d:
            data, label = f"c|{t}|{d}", f"{t}: upload…"
        elif it.action == "retention":
            data, label = f"rt|{t}", f"{t}: retention"
        elif d:
            data, label = f"c|{t}|{d}", f"{t}: card"
        else:
            continue
        rows.append([_b(label, data)])
    return InlineKeyboardMarkup(rows)


def card_keyboard(state) -> InlineKeyboardMarkup:
    """The buttons under a video card: the next step first, then the
    always-useful ones. `state` is a `pipeline.video_state.VideoState`."""
    t, d, fmt = state.ticker, state.workdate, state.fmt or "short"
    code = FMT_CODES.get(fmt, "s")
    _step, action = state.next_step()
    first: list = []
    if action == "angle":
        first = list(angle_keyboard(t, d).inline_keyboard[0])
    elif action == "prompt":
        first = [_b("Prompt 📋", f"p|{t}|{d}")]
    elif action == "edit":
        first = [_b("Edit ✏️", f"e|{t}|{d}"), _b("Report", f"k|{t}|{d}")]
    elif action == "approve":
        first = [_b("Report → Approve", f"k|{t}|{d}"),
                 _b("Edit ✏️", f"e|{t}|{d}")]
    elif action == "render":
        price = None if state.tts_cached else state.est_usd
        first = list(approved_keyboard(fmt, t, d, price).inline_keyboard[0])
    elif action == "upload":
        first = list(delivered_keyboard(fmt, t, d).inline_keyboard[0])
    elif action == "retention":
        first = list(uploaded_keyboard(t).inline_keyboard[0])
    rows = [first] if first else []
    tail = [_b("Refresh 🔄", f"c|{t}|{d}")]
    if state.active_job:
        tail.append(_b("Cancel 🚫", f"j|{t}|{d}"))
    elif state.script and action != "render":
        tail.append(_b("Proof $0", f"q|p|{t}|{d}|{code}"))
    rows.append(tail)
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
                  keys: list) -> InlineKeyboardMarkup:
    """One button per swappable visual, addressed BY INDEX.

    `keys` is the label list in plan order, or `(index, label)` pairs when
    some slots get no button (a meme has no other take); the index is what
    travels, and the handler resolves it against the stored plan.
    """
    pairs = [k if isinstance(k, tuple) else (j, k) for j, k in enumerate(keys)]
    rows = []
    for i in range(0, len(pairs), 2):
        row = []
        for j, k in pairs[i:i + 2]:
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
