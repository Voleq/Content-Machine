"""Telegram command/callback handlers.

All decision logic lives in `BotCore` — a plain object that consumes
strings/bytes and returns `Reply` values — so the whole flow is unit
-testable without Telegram. The PTB glue at the bottom only unwraps
updates, enforces the operator allow-list and ships Reply objects.

The one rule that matters: NOTHING paid runs before the operator taps
Approve on the validation+cost report, and /render only accepts a script
whose content hash still matches that approval.
"""

from __future__ import annotations

import logging
import os
import re
import uuid
from concurrent.futures import CancelledError
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw

from config import Settings
from pipeline.broll import (ContentManager, override_choice, palette_keys,
                           swap_slots)
from pipeline.company_data import (
    CompanyDataError,
    check_export,
    list_screenshots,
    load_company_data,
)
from pipeline.cost import (
    SpendLedger,
    build_long_report,
    build_short_report,
)
from pipeline import journal
from pipeline.corpus import INDEX_PROXIES
from pipeline.delivery import deliver
from pipeline.filing_brief import FilingReader
from pipeline.gates import run_gates
from pipeline.jobs import JobCancelled, JobRecord, RenderJobQueue
from pipeline.llm import llm_scope
from pipeline.models import JobKind, TagType
from pipeline.parser_long import LongScriptError, parse_long_script, validate_long_script
from pipeline.parser_short import ScriptParseError, parse_short_script
from pipeline.plates import PlateError
from pipeline.rasters import COURIER_BOLD, load_font
from pipeline.render_long import render_long
from pipeline.script_edit import (
    EditError,
    diff_lines,
    edit_lines,
    numbered,
    replace_text,
)
from pipeline.render_short import render_short
from pipeline.tts import TTSEngine
from pipeline.workspace import ActiveContext, Workspace, today_str

from bot.keyboards import (
    angle_keyboard,
    approval_keyboard,
    approved_keyboard,
    card_keyboard,
    confirm_render_keyboard,
    filing_veto_keyboard,
    swap_keyboard,
    undo_cancel_keyboard,
    uploaded_keyboard,
)
from bot.prompts import fill_prompt

log = logging.getLogger(__name__)

# The command list (`/help`), the Telegram menu and the README's command
# reference are generated from the registry in `bot/commands.py`.


@dataclass
class Reply:
    text: str
    keyboard: object | None = None  # telegram.InlineKeyboardMarkup
    files: list[Path] = field(default_factory=list)
    photo: Path | None = None
    # "TICKER@YYYY-MM-DD" when this is a video card, so the frontend can
    # remember the message and edit it as the video moves.
    card: str = ""


def _save_report_json(ws: Workspace, fmt: str, report) -> None:
    """The report as data, beside the text one: the video card, the inbox
    and the panel read the price and the findings off it rather than out of
    a sentence written for a person."""
    try:
        (ws.path / f"report_{fmt}.json").write_text(
            report.model_dump_json(), encoding="utf-8")
    except Exception as e:  # noqa: BLE001 - the card degrades, the report stands
        log.warning("could not save the %s report as JSON: %s", fmt, e)


def _journal_script(settings: Settings, ws: Workspace, fmt: str,
                    report) -> None:
    """One journal line for a pasted script and what the checks said."""
    ok = bool(getattr(report, "approvable", False))
    journal.note(settings, "script",
                 f"{fmt.upper()} script checked: "
                 f"{'approvable' if ok else 'blocked'}",
                 ticker=ws.ticker, workdate=ws.workdate, fmt=fmt,
                 approvable=ok)


# ---------------------------------------------------------------------------
# /headline mode detection — company (A) · earnings (B) · macro (C).
# ---------------------------------------------------------------------------

# common index / sector proxies + the "macro" keyword all route to macro mode
_INDEX_SYMS = set(INDEX_PROXIES)
_MACRO_SYMS = {"MACRO"} | _INDEX_SYMS
_MACRO_KW = (
    "cpi", "inflation", "deflation", "the fed", "fomc", "rate hike", "rate cut",
    "interest rate", "jobs report", "payroll", "nonfarm", "unemployment", "jobless",
    "gdp", "pce", "treasury yield", "recession", "powell", "basis points",
    "soft landing", "ppi", "retail sales", "rate decision",
)
_EARNINGS_KW = (
    "earnings", "eps", "beat", "missed", "misses", "guidance", "guides", "guided",
    "quarterly", "q1", "q2", "q3", "q4", "top line", "bottom line", "revenue beat",
    "revenue miss", "raises guidance", "cuts guidance", "reports results",
)
_HEADLINE_MODES = {"a": "company", "b": "earnings", "c": "macro",
                   "company": "company", "earnings": "earnings", "macro": "macro"}
_URL_RE = re.compile(r"^https?://\S+$", re.IGNORECASE)
# A ticker as the commands take one: letters and digits, with the `.` and `-`
# of share classes (BRK.B, BF-B), and an optional `@YYYY-MM-DD` workspace.
_TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,14}(@\d{4}-\d{2}-\d{2})?$")


def _strip_mode_tag(text: str) -> tuple[str | None, str]:
    """A leading [company]/[earnings]/[macro] (or [a]/[b]/[c]) tag forces the
    framing. Returns (mode | None, remaining headline text)."""
    m = re.match(r"\s*\[\s*([a-zA-Z]+)\s*\]\s*(.*)", text, re.DOTALL)
    if m and m.group(1).strip().lower() in _HEADLINE_MODES:
        return _HEADLINE_MODES[m.group(1).strip().lower()], m.group(2).strip()
    return None, text.strip()


def detect_headline_mode(symbol: str, headline: str) -> str:
    """company | earnings | macro from the symbol + headline text. Symbol wins
    for macro (an index or 'macro'); otherwise keywords decide, defaulting to
    company news."""
    sym = symbol.strip().upper()
    low = f" {headline.lower()} "
    if sym in _MACRO_SYMS or any(k in low for k in _MACRO_KW):
        return "macro"
    if any(f" {k} " in low or low.strip().startswith(k) for k in _EARNINGS_KW):
        return "earnings"
    return "company"


def _macro_index_for(symbol: str) -> str:
    """The chart proxy for macro mode — a named index passes through, plain
    'macro' defaults to the broad market."""
    sym = symbol.strip().upper()
    return sym if sym in _INDEX_SYMS else "SPY"


# What the cloud Bot API accepts, so a push is refused HERE with a reason
# rather than by Telegram with nobody listening (H2).
TELEGRAM_PHOTO_MAX_BYTES = 10_000_000
TELEGRAM_PHOTO_MAX_SIDES = 10_000      # width + height
TELEGRAM_PHOTO_MAX_RATIO = 20


def telegram_send_kind(path: Path, settings: Settings) -> str:
    """`video`, `photo` or `document` for one file the bot pushes.

    Raises `ValueError` naming the limit when the file cannot go at all: the
    cloud Bot API takes `telegram_upload_limit_mb` (50 MB) per upload, which
    a full-resolution proof passes easily. A self-hosted Bot API server
    (`TELEGRAM_API_BASE_URL`) lifts that, so the check is skipped there.

    A picture goes as a photo only inside the photo endpoint's limits — 10 MB,
    width + height ≤ 10,000, sides no more than 20:1. A tall multi-tile
    contact sheet is outside them and goes as a document, intact.
    """
    p = Path(path)
    size = p.stat().st_size            # a missing file raises, and says which
    limit = int(settings.telegram_upload_limit_mb) * 1_000_000
    if not settings.telegram_api_base_url and size > limit:
        raise ValueError(
            f"{p.name} is {size / 1e6:.0f} MB — over the "
            f"{settings.telegram_upload_limit_mb} MB the cloud Bot API "
            f"accepts. Use DELIVERY_BACKEND=gdrive, or a self-hosted Bot API "
            f"server (TELEGRAM_API_BASE_URL).")
    suffix = p.suffix.lower()
    if suffix in (".mp4", ".mov", ".mkv", ".webm"):
        return "video"
    if suffix in (".png", ".jpg", ".jpeg", ".webp") \
            and size <= TELEGRAM_PHOTO_MAX_BYTES:
        try:
            with Image.open(p) as im:
                w, h = im.size
        except Exception:  # noqa: BLE001 - unreadable goes as a file
            return "document"
        if (w + h <= TELEGRAM_PHOTO_MAX_SIDES
                and max(w, h) <= TELEGRAM_PHOTO_MAX_RATIO * max(min(w, h), 1)):
            return "photo"
    return "document"


def _frame_holds(manifest_path) -> str:
    """The finished SHORT's over-ceiling holds as operator text, or "".

    Best-effort: a manifest that cannot be read costs the operator this note,
    never the delivery it rides on.
    """
    import json as _json

    from pipeline.pacing import frame_holds_report

    try:
        data = _json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return ""
    return frame_holds_report(data) if isinstance(data, dict) else ""


def _what_it_said(script, fmt: str) -> dict:
    """`hook` / `conclusion` / `claims` off a shipped script, best-effort.

    The two formats carry very different amounts of structure, so this is the
    one place the difference is handled rather than a branch at every reader:

    * a SHORT declares all of it — `hook_text`, `conclusion`, and two prose
      fields (`numbers_comment`, `cheap_or_trap`) that ARE the claims;
    * a LONG carries only `narration` and the chapter trailer, so the closing
      claim is the last two sentences of the narration (the format ends on the
      verdict, deliberately) and the chapter titles are the claim skeleton —
      the trailer is already the argument's outline.

    Never raises. A shipped video is not failed by bookkeeping, and a thesis
    with empty fields is honestly thin rather than wrong.
    """
    if script is None:
        return {}
    try:
        if fmt == "short":
            claims = [c for c in (getattr(script, "numbers_comment", ""),
                                  getattr(script, "cheap_or_trap", "") or "")
                      if c]
            return {"hook": getattr(script, "hook_text", "") or "",
                    "conclusion": getattr(script, "conclusion", "") or "",
                    "claims": claims}
        from pipeline.publish import normalise_chapters

        narration = getattr(script, "narration", "") or ""
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", narration)
                     if s.strip()]
        titles = [title for _ts, title, _type in
                  normalise_chapters(getattr(script, "chapters", "") or "")]
        return {"hook": sentences[0] if sentences else "",
                "conclusion": " ".join(sentences[-2:]),
                "claims": titles}
    except Exception as e:  # noqa: BLE001 — bookkeeping, never the video
        log.warning("could not read back what the %s said: %s", fmt, e)
        return {}


class BotCore:
    def __init__(self, settings: Settings):
        self.settings = settings
        settings.ensure_runtime_dirs()
        self.ledger = SpendLedger(settings)
        self.tts = TTSEngine(settings, ledger=self.ledger)
        self.content = ContentManager(settings, ledger=self.ledger)
        self.context = ActiveContext(settings)
        # Set by main.py: a thread-safe way for the worker to hand a file
        # (storyboard, thumbnail) to the operator mid-job.
        self.file_pusher: Callable[[Path, str], None] | None = None
        self.queue: RenderJobQueue | None = None  # attached in main.py
        # FILING READINGS IN FLIGHT, keyed (ticker, workdate) → Future (K3).
        #
        # Its own single worker rather than the render queue: a reading is
        # eight to ten minutes of SEC pulls and LLM calls, and the point of
        # starting it at `/long` is that it overlaps the operator refreshing
        # their workbook — a single-worker render queue would put it behind
        # whatever is rendering, and every render behind it. One worker,
        # because the SEC's fair-access limit is per client and a second
        # concurrent reader buys nothing.
        #
        # `FilingReader` rather than a `ThreadPoolExecutor` because the pool
        # this replaced was never shut down and its threads are joined at
        # interpreter exit, so stopping the bot mid-reading hung for as long
        # as the reading had left (P1). `shutdown()` is wired to the
        # application's post_shutdown in main.py.
        self._filing_reads: dict[tuple[str, str], object] = {}
        self.filing_reader = FilingReader()
        # When each chat last sent a paste refused as a FRAGMENT. Telegram
        # delivers a split message's parts within a second or two, and only
        # the full-length parts look cut; the last part is short and used to
        # be accepted as a whole script (saved over the good one).
        self._fragment_at: dict[int, float] = {}
        # The last `/jobs cancel`, for its one-minute undo.
        self._last_cancel: dict | None = None
        # Attached by the frontends: the Telegram glue's card board and
        # sender, the activity feed the web panel reads, the panel's link.
        self.cards = None
        self.send_to = None
        self.feed = None
        self.panel_url = ""

    # ------------------------------------------------------------- helpers
    def _ws_or_error(self, ticker: str, want=None) -> Workspace | None:
        """`ticker` (or `TICKER@YYYY-MM-DD`) to the workspace a command means:
        the newest one `want` accepts, else the newest (`Workspace.resolve`)."""
        return Workspace.resolve(self.settings, ticker, want)

    @staticmethod
    def _from_date(ws: Workspace) -> str:
        """" (from YYYY-MM-DD)" when a command reached past today's folder,
        so the operator knows which video it acted on."""
        return "" if ws.workdate == today_str() else f" (from {ws.workdate})"

    def _active_ws(self, chat_id: int) -> Workspace | None:
        return self.context.get(chat_id)

    def _company_data(self, ws: Workspace):
        try:
            data = load_company_data(ws.path)
        except CompanyDataError:
            return None
        # Workbook headlines first, the free sources filling the gap (M5).
        # An 8-K IS the news for a thinly-covered ticker, and a thin News
        # sheet left the writer composing the headline beat unaided. Cached
        # and gracefully degrading, so a dead feed is a thinner prompt rather
        # than a failed load.
        try:
            from pipeline.company_data import merge_free_news

            data.news = merge_free_news(
                data.news, ws.ticker,
                str(data.get("website") or ""), self.settings)
        except Exception as e:  # noqa: BLE001 - never fatal
            log.warning("free-news merge for %s failed: %s", ws.ticker, e)
        return data

    @staticmethod
    def _llm_scope(ws: Workspace) -> str:
        """The key this workspace's LLM calls are tallied against.

        One video, one scope. The provenance record asks "what did the LLM
        do in THIS video", and a workspace is exactly that — the same
        `ticker/workdate` the brief, the angle and the render all share, so
        a call made at intake is still findable at render time hours later.
        """
        return f"{ws.ticker}/{ws.workdate}"

    # -------------------------------------------------- /short · /long (1d)
    # The format is declared up front rather than inferred from which of two
    # prompts the operator happened to run. Each command prepares only its own
    # lane's prompt, and /render follows from the lane.
    def start_lane(self, chat_id: int, lane: str, ticker: str, *,
                   update: bool = False) -> Reply:
        ticker = ticker.strip().upper()
        if not ticker or not ticker.replace(".", "").replace("-", "").isalnum():
            return Reply(f"Usage: /{'update' if update else lane} TICKER")
        if update:
            from pipeline.standing import ThesisBook

            if ThesisBook(self.settings).get(ticker) is None:
                return Reply(
                    f"No thesis on file for {ticker} — nothing was recorded "
                    f"from a previous video, so there is nothing to grade. "
                    f"/long {ticker} for a first-time take.")
        ws = Workspace(self.settings, ticker, today_str()).create()
        ws.set_lane(lane, update=update)
        self.context.set(chat_id, ticker, ws.workdate)
        # An update has no angle step: the angle is fixed, and it is "I said a
        # thing about this company, here is what happened."
        #
        # Re-running `/long` on a workspace that already has a LONG script
        # (to get the template again, say) keeps the angle it chose: re-arming
        # here wiped it and made the next plain message an angle pick — the
        # G2 guard `prompts_reply` has, missing from the other door.
        if lane == "long" and not update and ws.load_long() is None:
            ws.set_awaiting_angle()
        elif lane != "long" or update:
            ws.clear_awaiting_angle()

        label = ("UPDATE (16:9 — grading the last call)" if update else
                 "SHORT (9:16, 45–55s)" if lane == "short" else
                 "LONG (16:9 deep dive)")
        head = f"📁 {ticker} / {ws.workdate} — {label}"
        warn = "" if update else self._lane_warning(ticker, lane)
        journal.note(self.settings, "video",
                     f"started {'an UPDATE' if update else 'a ' + lane.upper()}",
                     ticker=ticker, workdate=ws.workdate, lane=lane,
                     update=update)

        # THE READING STARTS NOW (K3), not after the upload. It needs only
        # EDGAR, so it runs in parallel with the operator refreshing the
        # workbook; the half that needs the workbook is one cheap call, made
        # when the file lands.
        if lane == "long":
            self._start_filing_read(ws)

        name = "update" if update else lane
        template = self.settings.templates_dir / "dennis_data_template.xlsx"
        return Reply(
            f"{head}{warn}\n\nRefresh the attached template for {ticker} and "
            f"upload it here as dennis_data.xlsx — I'll reply with the {name} "
            f"prompt.",
            files=[template] if template.exists() else [],
        )

    def _lane_warning(self, ticker: str, lane: str) -> str:
        """Flag an apparent wrong-lane pick. Advisory, never a refusal.

        The editorial rule is that long-form is the beaten-down/value lane and
        never the trending name of the day — but the screener is a suggestion
        engine, and the operator has reasons it cannot see. So this says its
        piece and gets out of the way.
        """
        from pipeline.screener import last_screen_lane

        seen = last_screen_lane(self.settings, ticker)
        if not seen:
            return ""      # the screener has nothing to say about this ticker
        if lane == "long" and seen == "trending":
            return ("\n⚠️ the screener had this in the *trending* lane. Long-form "
                    "is the beaten-down/value lane — a name that ran today is "
                    "usually a SHORT. Carrying on if you meant it.")
        if lane == "short" and seen == "value":
            return ("\n⚠️ the screener had this in the *value* lane, which is "
                    "usually long-form material. A SHORT still works if there's "
                    "a move to hang it on.")
        return ""

    def _move_context(self, ticker: str) -> str:
        """What this ticker has actually done today, for the SHORT prompt.

        A live quote first (B2). The screener's cached string is written
        only by `run_screen`, whose default schedule is 07:30 ET — before
        the open, when Yahoo's `regularMarketChangePercent` still carries
        the previous completed session. On a Monday that is Friday, and the
        word "today" in that string means the day the screen ran, which
        nothing recorded. A ticker the screener had NEVER seen produced
        better output than one it had, because the empty-state text asks
        for a real number.

        The quote is the true intraday move and costs one data-only
        request. The cached line is the fallback and now carries its own
        age, so a stale figure cannot be read as a current one.
        """
        from pipeline.screener import last_screen_context, live_move_context

        live = live_move_context(self.settings, ticker)
        cached = last_screen_context(self.settings, ticker)
        if live and cached:
            # Both are worth having: the quote is the number, the screen is
            # why the ticker is on the list at all (volume, lane, reasons).
            return f"{live} · {cached}"
        return live or cached

    # ------------------------------------------------------------ /prompts
    def prompts_reply(self, chat_id: int) -> Reply:
        ws = self._active_ws(chat_id)
        if ws is None:
            return Reply("No active workspace — start with /short TICKER or /long TICKER.")
        try:
            data = load_company_data(ws.path)
        except CompanyDataError as e:
            return Reply(f"⛔ {e}")
        if data.blocking_missing:
            return Reply(
                "⛔ Data export is missing required fields "
                f"({', '.join(data.blocking_missing[:8])}…). Refresh and re-upload."
            )
        move_context = self._move_context(ws.ticker)
        # One lane, one prompt (1d). The lane is declared by /short or /long
        # and is never inferred; the deprecated lane-less /new is gone
        # (Group L), so a workspace without one is an old folder rather than
        # a supported shape, and both prompts is the safe reading of it.
        lane = ws.lane()
        # An update is a long on the long lane with one prompt swapped, and it
        # skips Step 1 — there is no angle to pick.
        wanted = (["update"] if ws.is_update() else
                  {"short": ["short"], "long": ["long_angle"]}.get(
                      lane, ["short", "long_angle"]))
        files = []
        for fmt in wanted:
            text = fill_prompt(fmt, ws.ticker, data, ws.path, self.settings,
                               move_context=move_context)
            f = ws.path / f"prompt_{fmt}.md"
            f.write_text(text, encoding="utf-8")
            files.append(f)
        # LONG is two manual steps in Claude — Step 1 (angle) here, Step 2
        # (write) after the operator replies with a pick.
        #
        # Only re-arm when there is no LONG script yet (G2). Re-arming on a
        # workspace that already has one makes the operator's next plain
        # message an angle pick rather than the script they meant to paste —
        # which is how uploading a corrected workbook mid-flow used to eat
        # the next paste.
        if "long_angle" in wanted and ws.load_long() is None:
            ws.set_awaiting_angle()
        warn = ""
        if not data.has_history:
            warn += ("\n⚠️ no History sheet — the multi-year gut check will "
                     "have nothing to show; re-export with both sheets")
        if data.warning_missing:
            warn += f"\n⚠️ optional fields missing: {', '.join(data.warning_missing[:6])}"
        lines = [f"📋 {ws.ticker} (as of {data.get('as_of_date')})"]
        if "short" in wanted:
            lines.append("• SHORT: run prompt_short.md, paste the output back.")
        if "long_angle" in wanted:
            lines.append("• LONG: run prompt_long_angle.md (Step 1) — it returns "
                         "ranked angles. Reply here with a number (or a tweak) "
                         "and I'll hand you Step 2, the writing prompt.")
        if "update" in wanted:
            lines.append("• UPDATE: run prompt_update.md and paste the script "
                         "back. One step — it already carries what the last "
                         "video claimed and what has moved since.")
        if not lane:
            lines.append("(this workspace has no lane — /short TICKER or "
                         "/long TICKER declares one and prepares just the "
                         "one prompt.)")
        keyboard = (angle_keyboard(ws.ticker, ws.workdate)
                    if "long_angle" in wanted and ws.awaiting_angle() else None)
        return Reply("\n".join(lines) + warn, files=files, keyboard=keyboard)

    # ---------------------------------------------------------- /headline
    def headline_command(self, chat_id: int, args: list[str]) -> Reply:
        """Build a SHORT around a specific news item the operator supplies —
        company news (A), an earnings print (B), or a macro release (C). The
        framing comes from the headline, not the screener's move context."""
        if len(args) < 2:
            return Reply(
                "Usage: /headline TICKER <headline text or URL>\n"
                "       /headline macro <text>   (market/sector — no single ticker)\n"
                "Force the framing with a leading tag, e.g.\n"
                "       /headline AAPL [earnings] Apple tops Q3 estimates, raises guide"
            )
        symbol_raw = args[0].strip()
        rest = " ".join(args[1:]).strip()
        forced_mode, headline = _strip_mode_tag(rest)
        if not headline:
            return Reply("Give me the headline text (or a URL) after the ticker.")
        sym = symbol_raw.upper()
        mode = forced_mode or detect_headline_mode(sym, headline)

        if mode == "macro":
            ws_ticker = _macro_index_for(sym)
        else:
            if not sym or not sym.replace(".", "").replace("-", "").isalnum():
                return Reply("First arg must be a TICKER (or 'macro'). "
                             "e.g. /headline NVDA <headline>")
            ws_ticker = sym

        ws = Workspace(self.settings, ws_ticker, today_str()).create()
        self.context.set(chat_id, ws_ticker, ws.workdate)
        # A headline video is a SHORT, so SAY so (G7). This never set the
        # lane, which left the workspace lane-less and fed straight into the
        # format-resolution mess in Group C — the paste that followed was
        # routed by its shape rather than by what the operator had asked for.
        ws.set_lane("short")
        ws.clear_awaiting_angle()  # a headline short is never in the LONG angle flow
        journal.note(self.settings, "video",
                     f"started a headline SHORT: {headline[:160]}",
                     ticker=ws_ticker, workdate=ws.workdate, lane="short")
        # `_enrich_headline` summarises a linked article with the LLM, which
        # is a call this video made — tally it here rather than against
        # whatever scope happened to be open.
        with llm_scope(self._llm_scope(ws)):
            display_headline, summary = self._enrich_headline(headline)
        # Free primary sources (P3.4): the 8-K's EX-99.1 for an earnings
        # print, the FRED series for a macro one. Best-effort — an
        # unavailable source leaves the operator's own headline as the
        # grounding, which is exactly how it worked before.
        summary = self._ground_headline(mode, ws_ticker, summary)
        ws.set_headline({"mode": mode, "symbol": ws_ticker,
                         "headline": display_headline, "summary": summary})

        if mode in ("company", "earnings"):
            data = self._company_data(ws)
            if data is None:
                template = self.settings.templates_dir / "dennis_data_template.xlsx"
                return Reply(
                    f"📰 Headline stored for {ws_ticker} ({mode} framing).\n"
                    f"I need this ticker's numbers for the gut check — upload "
                    f"dennis_data.xlsx for {ws_ticker} (template attached) and "
                    f"I'll hand you the headline prompt.",
                    files=[template] if template.exists() else [],
                )
            return self._headline_prompt_reply(ws, data)
        return self._headline_prompt_reply(ws, None)  # macro — no company data

    def _headline_prompt_reply(self, ws: Workspace, data) -> Reply:
        hstate = ws.headline()
        mode = hstate.get("mode", "company")
        prompt = fill_prompt("headline", ws.ticker, data, ws.path, self.settings,
                             headline=hstate.get("headline", ""),
                             article_summary=hstate.get("summary", ""),
                             headline_mode=mode)
        f = ws.path / "prompt_headline.md"
        f.write_text(prompt, encoding="utf-8")
        label = {"company": "company-news", "earnings": "earnings",
                 "macro": "macro / market"}.get(mode, mode)
        anchor = "an index chart" if mode == "macro" else "the ticker's multi-year numbers"
        return Reply(
            f"📰 Headline short for {ws.ticker} — {label} framing (anchored on "
            f"{anchor}).\nRun prompt_headline.md in Claude, paste the JSON back "
            f"here, review the cost report, Approve ✅, then /render {ws.ticker}.",
            files=[f],
        )

    def _ground_headline(self, mode: str, ticker: str, summary: str) -> str:
        """Add the primary source behind the headline, when there is one.

        An earnings headline is a claim; the EX-99.1 is the receipt. A macro
        headline is a claim; the FRED series is the number. Both are free, and
        both are strictly additive — a source that is unavailable leaves the
        summary exactly as it was.
        """
        try:
            from pipeline.sources import fred_series, latest_8k, summarise

            if mode == "earnings":
                got = latest_8k(ticker, self.settings)
                if got.get("status") == "ok" and got.get("exhibit_text"):
                    head = got["exhibit_text"][:1500]
                    return (f"{summary}\n\nFROM THE PRESS RELEASE "
                            f"({got.get('filed', '')}):\n{head}").strip()
            elif mode == "macro":
                lines = []
                for name in ("cpi", "unemployment", "fed_funds"):
                    payload = fred_series(name, self.settings)
                    if payload.get("status") == "ok":
                        lines.append(f"  {name}: {summarise(payload)}")
                if lines:
                    return (f"{summary}\n\nTHE ACTUAL SERIES:\n"
                            + "\n".join(lines)).strip()
        except Exception as e:  # noqa: BLE001 - grounding is never required
            log.warning("could not ground the headline (%s)", e)
        return summary

    def _enrich_headline(self, headline: str) -> tuple[str, str]:
        """If the headline is a URL, best-effort fetch + summarize ONCE so the
        'what it actually means' beat is grounded. Never blocks: in MOCK_MODE /
        offline or on any failure the URL is used as-is with no summary."""
        text = headline.strip()
        if not _URL_RE.match(text) or self.settings.mock_mode:
            return text, ""
        try:
            from pipeline.filings import fetch_and_summarize
            return text, (fetch_and_summarize(text, self.settings, ledger=self.ledger) or "")
        except Exception as e:  # pragma: no cover - best-effort enrichment
            log.warning("headline URL enrich failed for %s: %s", text, e)
            return text, ""

    # ------------------------------------------------------------- uploads
    def handle_upload(self, chat_id: int, filename: str, data: bytes) -> Reply:
        ws = self._active_ws(chat_id)
        if ws is None:
            return Reply("No active workspace — /short TICKER or /long TICKER first, then re-upload.")
        name = Path(filename).name
        suffix = Path(name).suffix.lower()

        if suffix in (".xlsx", ".csv"):
            return self._ingest_export(chat_id, ws, suffix, data)

        stem = Path(name).stem.lower().replace(" ", "-").replace("_", "-")

        if suffix in (".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mov", ".mkv", ".webm"):
            pending = self._pending_custom_slugs(ws)
            if stem in pending:
                # an operator capture ([SCREENGRAB]) — into the shared
                # custom library, where pre-render validation looks for it
                custom = self.settings.assets_dir / "custom"
                custom.mkdir(parents=True, exist_ok=True)
                # One file per slug. A re-upload in another format used to
                # sit beside the first, and whichever the glob found first
                # was the one drawn — not necessarily the newer.
                for old in custom.glob(f"{stem}.*"):
                    if old.suffix.lower() != suffix:
                        old.unlink(missing_ok=True)
                (custom / f"{stem}{suffix}").write_bytes(data)
                remaining = [s for s in self._pending_custom_slugs(ws) if s != stem]
                kind = pending[stem]
                note = (f" Still missing: {', '.join(remaining)}." if remaining
                        else " All custom files present — re-paste the script "
                             "to refresh the report.")
                return Reply(f"🎨 saved {kind} {stem}{suffix}.{note}")

        if suffix in (".png", ".jpg", ".jpeg", ".webp"):
            safe = name.replace(" ", "_")
            (ws.path / safe).write_bytes(data)
            shots = list_screenshots(ws.path)
            return Reply(
                f"🖼 saved {safe}. Screenshots available for [SHOW FILING]: "
                f"{', '.join(shots)}"
            )

        if suffix in (".txt", ".json", ".md"):
            return self.intake_script(chat_id,
                                      data.decode("utf-8", errors="replace"),
                                      from_file=True)

        return Reply(f"Unsupported file type: {name}")

    def _ingest_export(self, chat_id: int, ws: Workspace, suffix: str,
                       data: bytes) -> Reply:
        """Take in an uploaded workbook — the primary data route.

        The numbers are refreshed outside the bot and pasted into a clean
        workbook as values, so this is the front door and it validates like
        one. The upload lands in a scratch file first and only becomes
        `dennis_data.xlsx` once it passes: a wrong-company or half-refreshed
        workbook must not overwrite the good one already in the workspace.
        That is the same rule the COM refresh followed, for the same reason —
        a failed load looking like data is the worst outcome available.
        """
        dest = ws.path / f"dennis_data{suffix}"
        staging = ws.path / f".upload_{uuid.uuid4().hex[:8]}{suffix}"
        ws.path.mkdir(parents=True, exist_ok=True)
        staging.write_bytes(data)

        try:
            check = check_export(
                staging,
                expect_ticker=ws.ticker,
                max_age_days=self.settings.data_max_age_days,
            )
            if check.blocking:
                had = "  (the workbook already in the workspace is untouched)" \
                    if dest.exists() else ""
                return Reply(
                    f"⛔ {dest.name} was NOT updated.{had}\n\n"
                    + check.render().replace(staging.name, dest.name))
            os.replace(staging, dest)
        finally:
            staging.unlink(missing_ok=True)

        note = ""
        if check.warnings:
            note = "\n" + check.render().replace(staging.name, dest.name)

        # `find_export` prefers .xlsx, so a CSV uploaded alongside one is read
        # by nothing. Saying so beats letting the operator wonder why their
        # new numbers had no effect.
        if suffix == ".csv" and (ws.path / "dennis_data.xlsx").exists():
            note += ("\n⚠️ dennis_data.xlsx is also in this workspace and takes "
                     "precedence — this CSV will not be read until it is "
                     "replaced or removed.")

        # New numbers invalidate an approval (G2). The approval pins the
        # script's hash, which does not change when the data underneath it
        # does — so without this, approve → upload a corrected workbook →
        # render ships figures nobody reviewed. This used to live on
        # `/refresh`, which was the only path that did it; with the COM
        # refresh deleted (Group L) the upload is the sole data route and
        # therefore the sole place this can happen.
        # A CSV that an .xlsx beside it shadows changed nothing anything reads,
        # so it withdraws nothing either.
        shadowed = suffix == ".csv" and (ws.path / "dennis_data.xlsx").exists()
        withdrawn = ([] if shadowed else
                     [fmt for fmt in ("short", "long") if ws.is_approved(fmt)])
        for fmt in withdrawn:
            ws._invalidate_approval(fmt)
        if withdrawn:
            note += (
                f"\n⚠️ the {'/'.join(withdrawn)} approval was withdrawn — "
                f"these are different numbers than the report you approved. "
                f"Re-read the report and Approve again.")

        # a /headline that was waiting on the numbers → hand back the
        # headline prompt now, not the usual short/long_angle pair
        hstate = ws.headline()
        if (hstate.get("mode") in ("company", "earnings")
                and ws.load_short() is None):
            cdata = self._company_data(ws)
            if cdata is not None:
                reply = self._headline_prompt_reply(ws, cdata)
                reply.text = f"💾 saved {dest.name}.{note}\n\n" + reply.text
                return reply

        # The workbook is here, so the half of the brief that needed it can
        # run: one call over material already summarised (K3).
        note += self._finish_filing_read(ws)

        reply = self.prompts_reply(chat_id)
        reply.text = f"💾 saved {dest.name} for {ws.ticker}.{note}\n\n" + reply.text
        return reply

    def _pending_custom_slugs(self, ws: Workspace) -> dict[str, str]:
        """slug -> kind ("asset"|"screengrab") for the saved LONG script's
        custom-file tags that still lack a file in assets/custom/."""
        script = ws.load_long()
        if script is None:
            return {}
        custom = self.settings.assets_dir / "custom"
        out: dict[str, str] = {}
        # [SCREENGRAB] only. [ASSET] is gone — it blocked a render until an
        # operator pasted a prompt into Claude Design, exported a PNG and
        # uploaded it, which does not scale to daily shorts and was the slowest
        # step in the loop. An operator-supplied CAPTURE of something real is a
        # different thing and still blocks.
        for kind, slugs in (("screengrab", script.screengrab_slugs()),):
            for slug in slugs:
                if not (custom.is_dir() and list(custom.glob(f"{slug}.*"))):
                    out[slug] = kind
        return out

    # ------------------------------------------------------- script intake
    @staticmethod
    def looks_like_script(text: str) -> bool:
        """A pasted SHORT (JSON) or LONG (tagged narration / write-step
        output) — as opposed to a short free-text angle reply."""
        stripped = text.lstrip()
        if stripped.startswith("{") or '"format"' in text or "```" in text:
            return True  # SHORT JSON
        if re.search(r"\[[A-Za-z][A-Za-z ]*:", text):
            return True  # a bracket tag -> LONG narration
        if "ASSET PROMPTS" in text or "HOOK OPTIONS" in text:
            return True  # the LONG write-step output
        return False

    def intake_script(self, chat_id: int, text: str, *,
                      from_file: bool = False) -> Reply:
        ws = self._active_ws(chat_id)
        if ws is None:
            return Reply("No active workspace — /short TICKER or /long TICKER first.")
        # Every LLM call this paste provokes — the angle flagger under
        # `_auto_filings`, the skeptic inside `run_gates` — is tallied
        # against THIS video, so the provenance record written hours later at
        # render time reports this video's calls rather than the bot's.
        if not from_file:
            import time

            now = time.monotonic()
            why = self._looks_truncated(text)
            if why:
                self._fragment_at[chat_id] = now
            elif now - self._fragment_at.get(chat_id, -1e9) < self.SPLIT_TAIL_S:
                self._fragment_at[chat_id] = now
                return self._truncated_reply(
                    "paste", "it arrived right after a message Telegram cut "
                             "at its length limit, so it is the end of the "
                             "same message, not a whole script")
        with llm_scope(self._llm_scope(ws)):
            return self._intake(ws, text, from_file=from_file)

    # How soon after a refused fragment the next paste is taken for the rest
    # of the same split message.
    SPLIT_TAIL_S = 15.0

    def _intake(self, ws: Workspace, text: str, *,
                from_file: bool = False) -> Reply:
        # LONG two-step: a plain-text reply while awaiting the angle pick is
        # the operator's angle choice, not a script — hand back Step 2.
        if ws.awaiting_angle() and text.strip() and not self.looks_like_script(text):
            return self._intake_angle(ws, text)
        # A file arrives whole — Telegram only splits chat MESSAGES — so the
        # truncation check applies to pastes only. Running it on an upload
        # would refuse exactly the thing the refusal asks for.
        truncated = None if from_file else self._looks_truncated(text)
        # Route by the LANE, not by whether the text starts with a brace
        # (C1). `ws.lane()` was never consulted: anything that did not look
        # like JSON went to `_intake_long`, and `parse_long_script` rejected
        # only empty input — so a plain chat remark was saved as a LONG
        # script. And a failed SHORT parse was retried as a LONG whenever the
        # text contained brackets, which every SHORT does.
        lane = ws.lane()
        if lane == "short":
            if truncated:
                return self._truncated_reply("SHORT", truncated)
            try:
                return self._intake_short(ws, text)
            except ScriptParseError as e:
                return Reply(f"⛔ SHORT script rejected:\n{e}")
        if lane == "long":
            if truncated:
                return self._truncated_reply("LONG", truncated)
            try:
                return self._intake_long(ws, text)
            except LongScriptError as e:
                return Reply(f"⛔ LONG script rejected:\n{e}")
            except PlateError as e:
                # The kit is not installed. Say so, rather than letting it
                # escape the handler as an internal error (C5).
                return Reply(f"⛔ LONG script could not be checked — the "
                             f"design kit is not installed:\n{e}")

        # No lane at all: an old workspace, or one created before the lane
        # existed. Shape is the only signal left, and it is the one that was
        # wrong before — so it is used to ASK rather than to decide.
        return Reply(
            "⛔ This workspace has no lane, so I can't tell whether that is a "
            "SHORT or a LONG — and guessing from the text is what used to "
            f"save a chat remark as a script.\n\n/short {ws.ticker} or "
            f"/long {ws.ticker} declares one, then paste it again.")

    # Telegram splits a message over 4,096 characters into separate messages
    # and `on_text` handles each independently (C2). The SHORT prompt asks
    # for four prose sections before the JSON and the repo's own sample is
    # already ~4,200 characters, so the split is the common case rather than
    # the edge one. A LONG arrives as seven to nine fragments, each saved
    # over the last as a complete script.
    #
    # Buffering consecutive messages was the other option. Refusing is more
    # honest: a buffer has to guess when the operator has finished, and
    # guessing wrong silently truncates a script — which is the failure being
    # fixed. A `.txt` upload cannot be split at all.
    TELEGRAM_MESSAGE_LIMIT = 4096

    @classmethod
    def _looks_truncated(cls, text: str) -> str | None:
        """Why this paste looks like a fragment, or None if it does not."""
        stripped = text.strip()
        if not stripped:
            return None
        if stripped.startswith("{") or stripped.startswith("```"):
            # A JSON body that never closes is a fragment whatever its length.
            if stripped.count("{") - stripped.count("}") > 0:
                return "the JSON body never closes"
        # A message AT the limit was cut there. A narrow band rather than a
        # threshold, in both directions:
        #
        # - Not "near" it. Telegram splits at exactly 4,096, so every
        #   fragment but the last is exactly that long, and a loose lower
        #   bound refuses complete messages that merely ran close — the
        #   repo's own SHORT fixture is 4,056 characters.
        # - Not "over" it either. Telegram cannot deliver a chat message
        #   longer than the limit, so anything longer did not come through
        #   the chat at all: it is a file, a test, or a re-intake.
        #
        # The limit counts UTF-16 units and `len()` counts code points, so
        # the band absorbs the handful an emoji or two would differ by.
        if cls.TELEGRAM_MESSAGE_LIMIT - 16 <= len(text) <= cls.TELEGRAM_MESSAGE_LIMIT:
            return (f"it is {len(text)} characters, which is where Telegram "
                    f"cuts a message in two")
        return None

    @staticmethod
    def _truncated_reply(fmt: str, why: str) -> Reply:
        return Reply(
            f"⛔ That {fmt} looks cut off — {why}.\n\n"
            f"Telegram splits anything over 4,096 characters into separate "
            f"messages, and each one arrives here as its own paste. Send the "
            f"script as a .txt file instead — drag it into the chat — and it "
            f"arrives whole.")

    # ------------------------------------------- in-chat revision (P3.1c)
    def script_listing(self, chat_id: int) -> Reply:
        """The stored script, numbered, so `/edit N` and `/script` agree."""
        ws = self._active_ws(chat_id)
        if ws is None:
            return Reply("No active workspace — /short TICKER or /long TICKER first.")
        fmt = ws.current_format()
        raw = ws.raw_script(fmt) if fmt else None
        if not raw:
            return Reply("No script on file yet — paste one first.")
        listing = numbered(raw)
        f = ws.path / f"script_{fmt}.numbered.txt"
        f.write_text(listing, encoding="utf-8")
        state = "approved ✅" if ws.is_approved(fmt) else "not approved"
        revs = ws.revision_count(fmt)
        head = (f"📄 {ws.ticker} {fmt.upper()} — {len(raw.splitlines())} lines, "
                f"{state}"
                + (f", {revs} revision{'s' if revs != 1 else ''} behind" if revs else "")
                + ".\n`/edit N text` · `/edit N-M text` · `/edit N` deletes · "
                  "`/replace old => new` · `/undo`")
        # Short scripts fit in a message; a forty-minute LONG does not.
        if len(listing) <= 3500:
            return Reply(f"{head}\n\n```\n{listing}\n```")
        return Reply(head, files=[f])

    def edit_script(self, chat_id: int, args: list[str], *,
                    mode: str = "lines", raw_args: str | None = None) -> Reply:
        """Apply a targeted edit, then re-run the whole intake on the result.

        The revision is only stored if it parses, so an edit can never leave
        the workspace holding a script the renderer would choke on. Because it
        goes back through the ordinary intake, the gates re-run and a fresh
        cost report comes back — and saving invalidates the approval, so the
        approval stays pinned to the version actually read.

        `raw_args` is the message text after the command, verbatim. Telegram's
        `args` are the text split on whitespace, so a pasted paragraph lost
        its line breaks and a `/replace` across a line break or a double
        space could never match; the glue passes the text itself.
        """
        ws = self._active_ws(chat_id)
        if ws is None:
            return Reply("No active workspace — /short TICKER or /long TICKER first.")
        fmt = ws.current_format()
        raw = ws.raw_script(fmt) if fmt else None
        if not raw:
            return Reply("No script on file to edit — paste one first.")

        try:
            if mode == "replace":
                result = replace_text(
                    raw, raw_args if raw_args is not None else " ".join(args))
            else:
                if raw_args is not None:
                    m = re.match(r"\s*(\S+)\s?(.*)", raw_args, re.S)
                    args = [m.group(1)] if m else []
                    replacement = m.group(2).rstrip() if m else ""
                else:
                    replacement = " ".join(args[1:])
                if not args:
                    raise EditError(
                        "Usage: `/edit N new text` · `/edit N-M new text` · "
                        "`/edit N` to delete. `/script` shows the numbers.")
                result = edit_lines(raw, args[0], replacement)
        except EditError as e:
            return Reply(f"⛔ {e}")

        return self._revise(ws, fmt, raw, result.text,
                            note=f"✏️ {result.summary}",
                            diff=diff_lines(raw, result.text))[0]

    def undo_edit(self, chat_id: int) -> Reply:
        """Step back one revision. The stack survives a restart."""
        ws = self._active_ws(chat_id)
        if ws is None:
            return Reply("No active workspace — /short TICKER or /long TICKER first.")
        fmt = ws.current_format()
        if fmt is None:
            return Reply("No script on file.")
        current = ws.raw_script(fmt) or ""
        previous = ws.pop_revision(fmt)
        if previous is None:
            return Reply("Nothing to undo — this is the script as pasted.")
        depth = ws.revision_count(fmt)
        reply, saved = self._revise(ws, fmt, current, previous,
                                    note="↩️ reverted to the previous revision",
                                    diff=diff_lines(current, previous))
        if saved and ws.revision_count(fmt) > depth:
            # `_revise` saved, which pushed `current` onto the stack; drop it
            # so a second /undo goes further back rather than toggling. Only
            # when it DID push: an identical text is not stacked any more.
            ws.pop_revision(fmt)
        else:
            # It did NOT save, so nothing was pushed — and the second pop
            # used to run anyway and eat a revision that was never replaced
            # (G1). Put back the one this /undo took off, so a failed undo
            # costs nothing.
            ws.push_revision_text(fmt, previous)
        return reply

    def _revise(self, ws: Workspace, fmt: str, before: str, after: str,
                *, note: str, diff: str = "") -> tuple[Reply, bool]:
        """Validate a candidate script and, only if it holds up, store it.

        Returns `(reply, saved)`. The caller needs to know (G1): `/undo`
        pops a revision, calls this, and then pops again to drop the one the
        save pushed — and when this REJECTS the candidate nothing was pushed,
        so the second pop was eating a revision that was never replaced.

        On rejection the workspace keeps `before` untouched: the operator gets
        the parser's complaint and can try again, with nothing lost.
        """
        try:
            reply = (self._intake_short(ws, after) if fmt == "short"
                     else self._intake_long(ws, after))
        except (ScriptParseError, LongScriptError) as e:
            return Reply(
                f"⛔ that edit doesn't parse, so I've left the script alone:\n{e}"
                f"\n\nThe script is unchanged — /script to see it."), False
        head = note
        if diff:
            head += f"\n```\n{diff}\n```"
        reply.text = f"{head}\n\n{reply.text}"
        return reply, True

    def _intake_angle(self, ws: Workspace, text: str) -> Reply:
        """The operator picked a LONG angle — store it, run the thesis-aware
        10-K auto-screenshot pull, and hand back the Step-2 writing prompt
        (pre-filled with the angle + the auto-pulled filing quotes)."""
        data = self._company_data(ws)
        if data is None:
            return Reply("⛔ No data export on file — upload dennis_data.xlsx first.")
        ws.set_chosen_angle(text)
        self._auto_filings(ws, text)  # best-effort; never blocks the flow
        return self._long_write_reply(ws, header=f"✅ Angle locked for {ws.ticker}.")

    # ------------------------------------------------ the pre-angle brief
    def _filing_read_key(self, ws: Workspace) -> tuple[str, str]:
        return (ws.ticker, ws.workdate)

    def _start_filing_read(self, ws: Workspace) -> object | None:
        """Queue the filing reading for this workspace and return at once.

        Never raises and never waits. A failure to even start is the same
        outcome as a failure to finish: no brief, and a normal angle prompt.
        """
        if not (self.settings.filings_enabled
                and self.settings.filing_brief_enabled):
            return None
        key = self._filing_read_key(ws)
        if key in self._filing_reads:
            return self._filing_reads[key]
        # Readings nobody collected (no upload followed) are let go once
        # finished: the brief they wrote is on disk, which is where
        # `_finish_filing_read` looks when there is no future.
        self._filing_reads = {k: f for k, f in self._filing_reads.items()
                              if not getattr(f, "done", lambda: False)()}
        from pipeline.filing_brief import build_brief, save_brief

        def _run():
            # On the reader's OWN thread, so the scope the caller opened is
            # not visible here — this thread opens its own, or the brief's
            # calls land in whatever workspace the operator is pasting into.
            with llm_scope(self._llm_scope(ws)):
                brief = build_brief(ws.ticker, ws.path, self.settings)
                save_brief(ws.path, brief, self.settings)
                return brief

        try:
            fut = self.filing_reader.submit(f"{ws.ticker} {ws.workdate}", _run)
        except Exception as e:  # noqa: BLE001
            log.warning("filing brief: could not queue the reading (%s)", e)
            return None
        self._filing_reads[key] = fut
        return fut

    def _finish_filing_read(self, ws: Workspace) -> str:
        """Wait out a reading still in flight, then cross-check the workbook.

        Returns a line for the upload reply, or "". Bounded by
        `filing_brief_wait_s`: past that the prompt goes out without the
        brief rather than the operator watching a silent bot.
        """
        if not (self.settings.filings_enabled
                and self.settings.filing_brief_enabled):
            return ""
        from pipeline.filing_brief import (
            cross_check,
            grade_prior_coverage,
            load_brief,
            save_brief,
        )

        fut = self._filing_reads.pop(self._filing_read_key(ws), None)
        if fut is None and load_brief(ws.path) is None:
            # Nothing was ever queued for this workspace — an upload into a
            # lane started before this existed, or the switch is off.
            self._start_filing_read(ws)
            fut = self._filing_reads.pop(self._filing_read_key(ws), None)
        waited = ""
        if fut is not None:
            import time

            t0 = time.monotonic()
            try:
                fut.result(timeout=self.settings.filing_brief_wait_s)
            except CancelledError:
                # The bot is shutting down and the reading was dropped. Not
                # an error, and not something to wait out.
                log.info("filing brief: %s was abandoned at shutdown",
                         ws.ticker)
                return ("\n⚠️ the filing reading was cancelled — the prompt "
                        "below has no filing brief in it.")
            except TimeoutError:
                log.warning("filing brief: %s did not finish in %ss",
                            ws.ticker, self.settings.filing_brief_wait_s)
                # Still running: keep its future, so the re-upload waits on
                # this reading rather than starting a second one.
                self._filing_reads[self._filing_read_key(ws)] = fut
                return ("\n⚠️ the filing reading has not finished — the prompt "
                        "below has no filing brief in it. Re-upload the "
                        "workbook once it lands to pick it up.")
            except Exception as e:  # noqa: BLE001 — the reading itself failed
                log.warning("filing brief: %s failed (%s: %s)",
                            ws.ticker, type(e).__name__, e)
                return (f"\n⚠️ the filing reading failed ({type(e).__name__}: "
                        f"{str(e)[:120]}) — the prompt below has no filing "
                        f"brief in it. Re-uploading the workbook tries again.")
            elapsed = time.monotonic() - t0
            if elapsed > 5:
                waited = f" (waited {elapsed:.0f}s for the filing reading)"

        brief = load_brief(ws.path)
        if brief is None or not brief.ok:
            why = (brief.reason if brief is not None else "the pass did not run")
            return f"\nℹ️ no filing brief — {why}."
        data = self._company_data(ws)
        try:
            cross_check(brief, data, self.settings)
            if ws.is_update():
                from bot.prompts import prior_coverage

                grade_prior_coverage(
                    brief, prior_coverage(self.settings, ws.ticker),
                    self.settings)
            save_brief(ws.path, brief, self.settings)
        except Exception as e:  # noqa: BLE001 — the survey survives this
            log.warning("filing brief: cross-check failed for %s (%s)",
                        ws.ticker, e)
        parts = [f"{brief.sections} sections"]
        if brief.points:
            kept = (f"{len(brief.points)} points, each with its filing "
                    "sentence")
            if brief.dropped:
                kept += (f" ({brief.dropped} dropped: their sentence is not "
                         "in the filing)")
            parts.append(kept)
        if brief.contradictions:
            parts.append("cross-checked against your numbers")
        if brief.grading:
            parts.append("graded against the last video")
        if not brief.context_held:
            parts.append("⚠️ some sections did not fit the model's context")
        return f"\n📄 filing brief ready{waited}: " + ", ".join(parts) + "."

    def _auto_filings(self, ws: Workspace, angle: str) -> list:
        """Pull the 10-K, flag smoking-gun quotes, snap + normalize them into
        the workspace. Fully best-effort — a failure here is a warning, never
        a blocked render."""
        if not self.settings.filings_enabled:
            return []
        try:
            from pipeline.filings import auto_filings
            return auto_filings(ws.ticker, angle, ws.path, self.settings,
                                ledger=self.ledger)
        except Exception as e:  # pragma: no cover - auto_filings already guards
            log.warning("auto-filings failed for %s: %s", ws.ticker, e)
            return []

    def _long_write_reply(self, ws: Workspace, header: str) -> Reply:
        """Build the Step-2 writing prompt reply, attaching a contact sheet +
        veto keyboard for whatever auto-pulled filing shots are on file."""
        from pipeline.filings import load_manifest

        data = self._company_data(ws)
        if data is None:
            # `header` says what just happened — a crop was dropped, an angle
            # was locked — and this branch used to throw it away, so a veto
            # on a workspace with no workbook reported a missing upload for
            # an action that had already taken effect.
            return Reply(
                (f"{header}\n" if header else "")
                + "⛔ No data export on file — upload dennis_data.xlsx first.")
        prompt = fill_prompt("long_write", ws.ticker, data, ws.path, self.settings,
                             chosen_angle=ws.chosen_angle())
        f = ws.path / "prompt_long_write.md"
        f.write_text(prompt, encoding="utf-8")
        note = (
            f"{header}\n"
            f"Here's Step 2 — the writing prompt. Run it in the SAME Claude "
            f"chat (so it still has the angle in context), pick a hook, then "
            f"paste the tagged script back here."
        )
        shots = load_manifest(ws.path).get("shots", [])
        photo = keyboard = None
        if shots:
            note += (
                f"\n\n📎 Auto-pulled {len(shots)} shot(s) from the 10-K, "
                f"labelled 'FROM THE 10-K' (source stays unnamed). They're "
                f"already available to [SHOW FILING] and their quotes are in "
                f"the prompt. Tap to drop a bad crop:"
            )
            photo = self._filing_contact_sheet(ws, shots)
            keyboard = filing_veto_keyboard(ws.ticker, ws.workdate,
                                            [s["name"] for s in shots])
        return Reply(note, files=[f], photo=photo, keyboard=keyboard)

    def veto_filing(self, chat_id: int, ticker: str, workdate: str,
                    index: str) -> Reply:
        """Operator dropped an auto-pulled filing crop — remove it and re-send
        the writing prompt (regenerated without that shot).

        Addressed by index for the same reason as the swap menu: a filename
        in the callback data blows Telegram's 64-byte limit and takes the
        whole markup with it (G4).
        """
        from pipeline.filings import load_manifest, veto_shot

        ws = Workspace(self.settings, ticker, workdate)
        self.context.set(chat_id, ticker, workdate)
        shots = load_manifest(ws.path).get("shots", []) or []
        try:
            name = str(shots[int(index)].get("name", ""))
        except (ValueError, IndexError, KeyError, AttributeError):
            # An older button still carrying the filename, or a stale index.
            name = index
        removed = veto_shot(ws.path, name)
        header = f"🗑 Dropped {name}." if removed else f"({name} already gone.)"
        return self._long_write_reply(ws, header=header)

    def _filing_contact_sheet(self, ws: Workspace, shots: list) -> Path | None:
        """Grid of the auto-pulled filing shots so the operator can veto a bad
        crop without opening each one."""
        imgs = []
        for i, s in enumerate(shots, 1):
            p = Path(s.get("image") or "")
            if not p.exists():
                p = ws.path / s.get("name", "")
            try:
                imgs.append((i, s, Image.open(p).convert("RGB")))
            except Exception:
                log.warning("filing thumbnail failed for %s", s.get("name"))
        if not imgs:
            return None
        cols = min(3, len(imgs))
        rows = (len(imgs) + cols - 1) // cols
        tw, th, label_h = 320, 180, 30
        sheet = Image.new("RGB", (cols * tw, rows * (th + label_h)), (18, 18, 22))
        d = ImageDraw.Draw(sheet)
        font = load_font(self.settings, COURIER_BOLD, 16)
        for k, (i, s, img) in enumerate(imgs):
            x, y = (k % cols) * tw, (k // cols) * (th + label_h)
            sheet.paste(img.resize((tw, th)), (x, y))
            d.text((x + 6, y + th + 5), f"#{i} {str(s.get('section', ''))[:22]}",
                   font=font, fill=(240, 240, 240))
        out = ws.path / "filings" / "contact_sheet.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(out)
        return out

    def _intake_short(self, ws: Workspace, raw: str) -> Reply:
        script, warnings = parse_short_script(raw, self.settings)
        if script.ticker != ws.ticker:
            warnings = [f"script ticker {script.ticker} ≠ workspace {ws.ticker} — "
                        f"using the workspace ticker's folder"] + warnings
        ws.save_short(script, raw)
        # The same battery the LONG runs (B3). A SHORT could state an
        # invented revenue figure, name a data vendor — which the LONG hard
        # blocks, because it would be spoken and captioned — or run on stale
        # data, and nothing objected. SHORTs are the higher-volume output.
        data = self._company_data(ws)
        # THE SHEET ON SCREEN IS THE WORKBOOK'S (item 23), so the gates check
        # the rows the render will draw, and a row whose typed figures the
        # workbook replaces says so here, before approval.
        checked = script
        if data is not None:
            from pipeline.short_data import fill_numbers
            checked, notes = fill_numbers(script, data)
            warnings = warnings + notes
        fmt_name = self.short_format_name(ws)
        if fmt_name == "macro":
            # The print against FRED's own latest reading (item 6), before
            # approval: the macro chart draws FRED's series, so a typed print
            # that disagrees with it would disagree on screen too.
            from pipeline.macro_series import print_check
            note = print_check(script, self.settings)
            if note:
                warnings = warnings + [note]
        gates = run_gates(checked, self.settings, data=data,
                          as_of=str((data.get("as_of_date") if data else "") or ""),
                          workspace=ws.path,
                          format_name=fmt_name)
        report = build_short_report(script, warnings, self.settings,
                                    self.ledger, self.tts, gate_report=gates)
        (ws.path / "report_short.txt").write_text(report.render_text(), encoding="utf-8")
        _save_report_json(ws, "short", report)
        _journal_script(self.settings, ws, "short", report)
        return Reply(
            report.render_text(),
            keyboard=approval_keyboard("short", ws.ticker, ws.workdate,
                                       report.script_sha, report.approvable, False),
        )

    def _intake_long(self, ws: Workspace, raw: str) -> Reply:
        script, warnings = parse_long_script(raw, ws.ticker, self.settings)
        data = self._company_data(ws)
        data_metrics = data.available_chart_metrics() if data is not None else None
        v_warnings, v_blocking = validate_long_script(
            script, palette_keys(), ws.path, self.settings, data_metrics=data_metrics
        )
        # The automated gates run here — before approval, before any spend —
        # and only speak up on failure. A fabricated figure is the one error
        # nobody downstream can catch.
        gates = run_gates(script, self.settings, data=data,
                          as_of=str((data.get("as_of_date") if data else "") or ""),
                          workspace=ws.path)
        for f in gates.findings:
            (v_blocking if f.severity == "block" else v_warnings).append(f.render())
        ws.save_long(script, raw)
        ws.clear_awaiting_angle()  # a script is on file — past the angle stage
        prompt_files: list = []
        plan = self.content.plan(script, company_data=data,
                                 overrides=ws.broll_overrides())
        filing_count = len({e.payload for e in script.events_of(TagType.SHOW_FILING)})
        report = build_long_report(
            script, warnings, v_warnings, v_blocking,
            self.settings, self.ledger, self.tts, plan, filing_count,
        )
        (ws.path / "report_long.txt").write_text(report.render_text(), encoding="utf-8")
        _save_report_json(ws, "long", report)
        _journal_script(self.settings, ws, "long", report)
        sheet = self._contact_sheet(ws, plan)
        return Reply(
            report.render_text(),
            keyboard=approval_keyboard("long", ws.ticker, ws.workdate,
                                       report.script_sha, report.approvable, bool(plan)),
            photo=sheet,
            files=prompt_files,
        )

    def _contact_sheet(self, ws: Workspace, plan) -> Path | None:
        """Grid of proposed visual thumbnails for the approval report."""
        if not plan:
            return None
        thumbs = []
        for visual in plan:
            t = ws.path / "thumbs" / f"{visual.kind}_{visual.key[:24].replace(' ', '_')}.png"
            try:
                self.content.thumbnail(visual, t)
                thumbs.append((visual, Image.open(t).convert("RGB")))
            except Exception:
                log.warning("thumbnail failed for %s", visual.key)
        if not thumbs:
            return None
        cols = min(3, len(thumbs))
        rows = (len(thumbs) + cols - 1) // cols
        tw, th, label_h = 320, 180, 30
        sheet = Image.new("RGB", (cols * tw, rows * (th + label_h)), (18, 18, 22))
        d = ImageDraw.Draw(sheet)
        font = load_font(self.settings, COURIER_BOLD, 18)
        for i, (visual, img) in enumerate(thumbs):
            x, y = (i % cols) * tw, (i // cols) * (th + label_h)
            sheet.paste(img.resize((tw, th)), (x, y))
            d.text((x + 6, y + th + 5), f"{visual.key[:24]} [{visual.source}]",
                   font=font, fill=(240, 240, 240))
        out = ws.path / "visual_contact_sheet.png"
        sheet.save(out)
        return out

    # ------------------------------------------------------------ approval
    def approve(self, fmt: str, ticker: str, workdate: str, sha8: str) -> Reply:
        ws = Workspace(self.settings, ticker, workdate)
        script = ws.load_short() if fmt == "short" else ws.load_long()
        if script is None:
            return Reply("⛔ No script on file — paste it first.")
        if script.content_sha()[:8] != sha8:
            return Reply("⛔ The script changed since this report — paste/review again.")
        # THE HASH IS NOT THE WHOLE QUESTION (G8). It pins the content, which
        # is right, and nothing else — so a button drawn on an approvable
        # report stayed approvable after the world underneath it changed.
        # The findings that can turn blocking without a keystroke are the
        # ones that matter: freshness crossing `data_max_age_days` as the day
        # rolls over, a `[SCREENGRAB]` file deleted out of `assets/custom/`,
        # the audio gate flipping. `/render` then reads `is_approved()` and
        # spends.
        #
        # `skeptic=False` because that pass is the only one here that costs a
        # network call, and it is advisory by construction — every finding it
        # returns is a warning, so it can never be what refuses this.
        blocked = self._approval_blockers(ws, script, fmt)
        if blocked:
            return Reply(
                "⛔ Not approved — this passed when the report was written and "
                "does not now:\n"
                + "\n".join(f"  • {b}" for b in blocked[:6])
                + "\n\nPaste the script again for a fresh report."
            )
        report_file = ws.path / f"report_{fmt}.txt"
        ws.approve(fmt, script.content_sha(),
                   report_file.read_text(encoding="utf-8") if report_file.exists() else "")
        journal.note(self.settings, "approved",
                     f"approved the {fmt.upper()} script ({sha8})",
                     ticker=ticker, workdate=workdate, fmt=fmt, sha=sha8)
        from pipeline.video_state import video_state

        st = video_state(self.settings, ws, jobs=[], videos=[])
        est = None if st.tts_cached else st.est_usd
        return Reply(
            f"✅ {ticker} {fmt.upper()} approved (script {sha8}).\n"
            f"/render {fmt} {ticker} to render — this is the point where "
            f"money is spent."
            + ("\nTip: a draft first is a cheap timing check." if fmt == "long"
               else ""),
            keyboard=approved_keyboard(fmt, ticker, workdate, est),
        )

    def _approval_blockers(self, ws: Workspace, script, fmt: str) -> list[str]:
        """Blocking findings as of NOW, for the Approve tap to refuse on.

        The same three sources the report's blockers come from (M2), not
        only the gate battery: the LONG's own validation — where a
        `[SCREENGRAB]` file deleted out of `assets/custom/` is caught, which
        the G8 note above promised and the gates never checked — the gates,
        run on the SHORT's workbook-filled rows exactly as intake ran them,
        and the monthly cap.

        Never raises: a battery that cannot run is not evidence that the
        script is bad, and refusing an approval because the kit is missing
        would be a worse failure than the one this guards.
        """
        from pipeline.cost import billable_chars, estimate_tts_usd

        blocked: list[str] = []
        try:
            data = self._company_data(ws)
            as_of = str((data.get("as_of_date") if data else "") or "")
            with llm_scope(self._llm_scope(ws)):
                if fmt == "short":
                    checked = script
                    if data is not None:
                        from pipeline.short_data import fill_numbers
                        checked, _notes = fill_numbers(script, data)
                    gates = run_gates(checked, self.settings, data=data,
                                      as_of=as_of, workspace=ws.path,
                                      skeptic=False,
                                      format_name=self.short_format_name(ws))
                    text, events = script.audio_script, script.inline_events
                else:
                    metrics = (data.available_chart_metrics()
                               if data is not None else None)
                    _warn, v_blocking = validate_long_script(
                        script, palette_keys(), ws.path, self.settings,
                        data_metrics=metrics)
                    blocked += list(v_blocking)
                    gates = run_gates(script, self.settings, data=data,
                                      as_of=as_of, workspace=ws.path,
                                      skeptic=False)
                    text, events = script.narration, script.events
            blocked += [f.render() for f in gates.findings
                        if f.severity == "block"]
            if not self.tts.is_cached(text, fmt, events=events):
                est = estimate_tts_usd(
                    billable_chars(self.tts, text, fmt, events,
                                   script.char_count), self.settings)
                if self.ledger.would_exceed(est):
                    blocked.append(
                        f"TTS (~${est:.2f}) would exceed the monthly cap "
                        f"(${self.ledger.mtd_spend_usd():.2f}/"
                        f"${self.settings.monthly_spend_cap_usd:.2f})")
        except Exception:  # noqa: BLE001
            log.exception("could not re-check the gates for %s %s — "
                          "letting the approval through on the report",
                          ws.ticker, fmt)
            return []
        return blocked

    def cancel_approval(self, fmt: str, ticker: str, workdate: str) -> Reply:
        ws = Workspace(self.settings, ticker, workdate)
        ws._invalidate_approval(fmt)
        return Reply(f"🚫 {ticker} {fmt.upper()} — approval withdrawn. Nothing was spent.")

    # ---------------------------------------------------------- swap flow
    def swap_menu(self, ticker: str, workdate: str) -> Reply:
        ws = Workspace(self.settings, ticker, workdate)
        script = ws.load_long()
        if script is None:
            return Reply("No LONG script on file.")
        slots = self.swappable_slots(script)
        # A meme has one take — the owned library's match — so a button for
        # it would count "take 2/6" and change nothing. It keeps its place in
        # the index space, which is what every stored override is keyed on.
        labels = [(i, f"{i + 1}. {payload}")
                  for i, (tag, payload) in enumerate(slots) if tag != "MEME"]
        if not labels:
            return Reply("This LONG has no [CLIP] tags to swap.")
        return Reply(
            "Pick the visual to swap to its next take "
            "(approval resets after a swap):",
            keyboard=swap_keyboard(ticker, workdate, labels),
        )

    @staticmethod
    def swappable_slots(script) -> list[tuple[str, str]]:
        """Every swappable visual in the script, IN ORDER, as (tag, payload).

        One entry per OCCURRENCE, not per distinct payload (G5). An override
        keyed on the payload text swapped every beat that shared it — and the
        prompt actively encourages reusing palette keys, so that is the
        common case rather than the edge one. It also could not tell a
        `[CLIP]` from an `[IMG]` carrying the same subject.
        """
        events = getattr(script, "events", []) or []
        # The same count `broll.swap_slots` makes, which is what the report,
        # the storyboard and the renderer all read an override by.
        return [(slot.split(":", 1)[0], events[idx].payload)
                for idx, slot in swap_slots(events).items()]

    def swap_key(self, chat_id: int, ticker: str, workdate: str,
                 index: str) -> Reply:
        """Swap ONE occurrence to its next take.

        `index` is the position in `swappable_slots` — a small integer that
        fits Telegram's 64-byte callback limit (G4) and identifies the
        occurrence rather than the payload text (G5).
        """
        ws = Workspace(self.settings, ticker, workdate)
        script = ws.load_long()
        if script is None:
            return Reply("No LONG script on file.")
        slots = self.swappable_slots(script)
        try:
            i = int(index)
            tag, payload = slots[i]
        except (ValueError, IndexError):
            return Reply("That swap button is stale — the script changed. "
                         "Open the menu again.")
        slot = f"{tag}:{i}"
        current = override_choice(ws.broll_overrides(), slot, payload)
        n = self.content.alternates_count(payload)
        take = (current + 1) % max(n, 1)
        ws.set_broll_override(slot, take)
        raw = (ws.path / "script_long.raw.txt").read_text(encoding="utf-8")
        self.context.set(chat_id, ticker, workdate)
        # Re-intake of a script already on file, not a new paste.
        reply = self.intake_script(chat_id, raw, from_file=True)
        reply.text = (f"🔄 {payload}: take {take + 1}/{max(n, 1)}\n\n"
                      + reply.text)
        return reply

    # ------------------------------------------------------------- renders
    def render_request(self, ticker: str, fmt: str | None = None,
                       draft: bool = False, proof: bool = False,
                       ) -> tuple[JobKind | None, str, Workspace | None]:
        """Queue a render. `fmt=None` takes the format from the workspace's lane.

        Since /short and /long declare the format up front (1d), plain /render
        follows from it rather than making the operator pick twice.
        """
        def has_script(w: Workspace) -> bool:
            f = fmt or w.current_format()
            return bool(f) and (w.path / f"script_{f}.json").exists()

        ws = self._ws_or_error(ticker, has_script)
        ticker = Workspace.split_arg(ticker)[0]
        if ws is None:
            return None, (f"No workspace for {ticker} — /short {ticker} or "
                          f"/long {ticker} first."), None
        if fmt is None:
            fmt = ws.current_format()
            if fmt is None:
                return None, (
                    f"No script for {ticker} yet, so I can't tell which format "
                    f"you mean. /short {ticker} or /long {ticker} sets the lane."
                ), None
        script = ws.load_short() if fmt == "short" else ws.load_long()
        if script is None:
            return None, f"No {fmt.upper()} script for {ticker} — paste it first.", None
        if proof:
            # A PROOF answers "what will this look like?", which is the one
            # question neither existing free pass can: MOCK_MODE fakes the
            # prices, imagery, memes and filings, and both cheap passes throw
            # away the resolution the answer lives in. So: every subsystem
            # live, full frame, and the voice — the only thing in this
            # pipeline that costs money — taken from the free local tier.
            #
            # No approval gate. Approval is the SPEND gate, and this cannot
            # spend; requiring it would mean approving a video to find out
            # whether it is worth approving.
            tier = self.tts.tier_for(True)
            voice = {
                "local": "free local voice",
                "mock": ("⚠ mock hum — MOCK_MODE is on, so the voice and "
                         "the pictures are placeholders"
                         if self.settings.mocking_tts else
                         "⚠ mock hum — Piper is not installed on this box, so "
                         "you get real pictures over a placeholder tone"),
            }.get(tier, tier)
            kind = (JobKind.RENDER_PROOF_SHORT if fmt == "short"
                    else JobKind.RENDER_PROOF_LONG)
            return kind, (
                f"🖼 queued FULL-RES PROOF for {ticker} {fmt.upper()}"
                f"{self._from_date(ws)}\n"
                f"📺 real visuals — live prices, Pexels, Wikimedia, memes, "
                f"filings and charts, exactly as a final\n"
                f"🎧 {voice}\n"
                f"💵 $0, enforced in code — this job cannot reach the paid "
                f"voice\n"
                f"⏱ cue times shift slightly when the paid voice lands: the "
                f"draft clock is exact per sentence, interpolated inside one"
                + self._dennis_3d_note()
            ), ws
        if draft and fmt == "long":
            # Since P3.2 a draft never buys audio: it uses the free local
            # voice, or the mock hum where there isn't one. So the old
            # "a draft would trigger the paid call" gate is gone — there is
            # nothing left for it to gate.
            tier = self.tts.tier_for(True)
            note = {
                "local": "free local voice — listenable, timings interpolated "
                         "within each sentence",
                "mock": ("mock hum — MOCK_MODE is on, so this checks timing "
                         "only" if self.settings.mocking_tts else
                         "mock hum — the local voice isn't installed, so this "
                         "checks timing only"),
            }.get(tier, tier)
            return JobKind.RENDER_DRAFT_LONG, (
                f"🎬 queued LOW-RES DRAFT for {ticker}{self._from_date(ws)}"
                f"\n🎧 {note}. $0 either "
                f"way; the final still needs the paid voice."), ws
        if not ws.is_approved(fmt):
            return None, (
                f"⛔ {ticker} {fmt.upper()} is not approved (or the script changed "
                f"after approval). Paste the script and tap Approve first — the "
                f"approval gate is the spend gate."
            ), None
        kind = JobKind.RENDER_SHORT if fmt == "short" else JobKind.RENDER_LONG
        return kind, (f"🎬 queued {fmt.upper()} render for {ticker}"
                      f"{self._from_date(ws)}" + self._dennis_3d_note()), ws

    def _dennis_3d_note(self) -> str:
        """A line on the queue reply when the 3D Dennis is on: every second
        of him is drawn frame by frame in Blender, and a long can hold the one
        render worker for hours. Said before the job starts, not discovered."""
        mode = (self.settings.dennis_3d or "off").strip().lower()
        if mode in ("", "off", "0", "false", "no"):
            return ""
        return ("\n🧊 DENNIS_3D is on: each second of him is rendered in "
                "Blender, so this can run for hours and holds the queue. "
                "`python room3d/perform.py --bench` times a frame on this box.")

    def repurpose_request(self, ticker: str) -> tuple[JobKind | None, str, Workspace | None]:
        """SHORT-from-LONG: free (no TTS, no fetches), so no approval gate."""
        ws = self._ws_or_error(
            ticker, lambda w: (w.path / "long_final.mp4").exists())
        ticker = Workspace.split_arg(ticker)[0]
        if ws is None:
            return None, f"No workspace for {ticker}.", None
        if not (ws.path / "long_final.mp4").exists():
            return None, (
                f"No finished LONG for {ticker} — /render_long first, then "
                f"/repurpose extracts the best ~58s as a 9:16 SHORT for free."
            ), None
        return JobKind.REPURPOSE, f"✂️ queued repurpose (SHORT-from-LONG) for {ticker}", ws

    # ------------------------------------------------- job executor (worker)
    def execute_job(self, job: JobRecord) -> str:
        """Blocking pipeline for one job; runs in the queue's worker thread.
        Every stage rechecks cancellation; every stage is cache-resumable."""
        ws = Workspace(self.settings, job.ticker, job.workdate)
        # The worker thread sees none of the scope intake opened, so it
        # reopens this video's — that is how the provenance record written
        # below reads back the calls the brief and the gates made hours ago,
        # and only those.
        with llm_scope(self._llm_scope(ws)):
            return self._execute_job(job, ws)

    def _execute_job(self, job: JobRecord, ws: Workspace) -> str:
        store = self.queue.store if self.queue else None

        def checkpoint(detail: str) -> None:
            if store:
                # One locked step, so a `/cancel` saved in between cannot be
                # written over by this progress note (JobStore.update).
                def note(fresh) -> None:
                    if fresh.status.value == "cancelled":
                        raise JobCancelled()
                    fresh.detail = detail

                store.update(job.id, note)

        if job.kind in (JobKind.RENDER_PROOF_SHORT, JobKind.RENDER_PROOF_LONG):
            return self._run_proof(job, ws, checkpoint)

        if job.kind is JobKind.RENDER_SHORT:
            script = ws.load_short()
            if script is None or not ws.is_approved("short"):
                raise RuntimeError("script/approval vanished before render")
            self._refuse_synthetic_prices(script, self.short_format_name(ws))
            checkpoint("tts")
            tts = self.tts.synthesize(script.audio_script, "short",
                                      events=script.inline_events,
                                      ticker=job.ticker)
            checkpoint("render")
            out, manifest = render_short(
                script, tts, ws.path, self.settings, content=self.content,
                format_name=self.short_format_name(ws),
                company_data=self._company_data(ws))
            checkpoint("delivery")
            extra = self._publish_byproducts(job, ws, script, tts, manifest,
                                             "short")
            result = deliver(out, job.ticker, job.workdate, self.settings,
                             attributions=self._attributions(manifest),
                             extra_files=extra)
            held = _frame_holds(manifest)
            if held:
                result.note = "\n\n".join(
                    x for x in (result.note, held) if x)
            self._finish(job, result)
            return str(out)

        if job.kind in (JobKind.RENDER_LONG, JobKind.RENDER_DRAFT_LONG):
            draft = job.kind is JobKind.RENDER_DRAFT_LONG
            script = ws.load_long()
            if script is None:
                raise RuntimeError("script vanished before render")
            if not draft and not ws.is_approved("long"):
                raise RuntimeError("approval vanished before render")
            if not draft:
                self._refuse_synthetic_prices(script)
            checkpoint("tts")
            # A draft asks for the free tier (P3.2): the local neural voice if
            # the box has one, the mock hum otherwise. Never ElevenLabs — the
            # whole point of a draft is to iterate on pacing without spending.
            tts = self.tts.synthesize(script.narration, "long",
                                      events=script.events, draft=draft,
                                      ticker=job.ticker)
            if tts.draft:
                checkpoint(f"draft audio ({tts.tier}) — not the real voice")
            data = self._company_data(ws)
            as_of = str(data.get("as_of_date") or "") if data is not None else ""
            # The storyboard costs seconds and lands before the encode, so a
            # dead b-roll key or a missing screenshot is caught now rather
            # than forty minutes from now.
            checkpoint("storyboard")
            self._send_storyboard(job, script, tts, ws, data)
            checkpoint("render")

            def seg_progress(done: int, total: int) -> None:
                # Real progress, not a spinner: the operator can see a
                # forty-minute cut advancing beat by beat.
                if done == total or done % 5 == 0:
                    checkpoint(f"render {done}/{total} segments")

            out, manifest = render_long(
                script, tts, ws.path, self.settings, content=self.content,
                draft=draft, broll_overrides=ws.broll_overrides(),
                as_of=as_of, company_data=data,
                on_progress=seg_progress,
            )
            if draft:
                self._local_link(job, out)
                return str(out)
            checkpoint("delivery")
            extra = self._publish_byproducts(job, ws, script, tts, manifest,
                                             "long")
            result = deliver(out, job.ticker, job.workdate, self.settings,
                             attributions=self._attributions(manifest),
                             extra_files=extra)
            self._finish(job, result)
            return str(out)

        if job.kind is JobKind.REPURPOSE:
            from pipeline.repurpose import repurpose_clips_from_long

            long_mp4 = ws.path / "long_final.mp4"
            manifest = ws.path / "render_long_manifest.json"
            if not long_mp4.exists() or not manifest.exists():
                raise RuntimeError("no finished LONG render to repurpose")
            script = ws.load_long()
            words = None
            if script:
                # `cached_only` rather than the bare `is_cached` probe this
                # used to trust. A repurpose is advertised as $0 and has no
                # approval gate, so the promise has to be structural the way
                # `/proof`'s is: the cache answers or this raises, and no
                # voice is generated at any tier. Word timings are a nicety
                # here — without them the cut falls back to the manifest's
                # own beat boundaries — so a miss is a log line, not a
                # failed job.
                from pipeline.tts import CacheMissForbidden

                try:
                    words = self.tts.synthesize(
                        script.narration, "long", events=script.events,
                        cached_only=True, ticker=job.ticker).words
                except CacheMissForbidden as e:
                    log.info("repurpose %s: no cached narration (%s) — "
                             "cutting on the manifest's beats", job.ticker, e)
            checkpoint("repurpose")
            # A forty-minute cut has more than one good minute in it (P3.3).
            clips = repurpose_clips_from_long(
                long_mp4, manifest, self.settings,
                n=self.settings.repurpose_clips, words=words,
            )
            if not clips:
                raise RuntimeError("no usable window in the finished LONG")
            checkpoint("delivery")
            attributions = self._attributions(manifest)
            # EVERY clip's link, not just the last one's (I3). `result` was
            # overwritten each pass, so `/status` and the job record showed
            # only the final clip — the first two were delivered and
            # invisible, which is the whole point of cutting three.
            results = []
            for i, (path, _info) in enumerate(clips, 1):
                checkpoint(f"delivery {i}/{len(clips)}")
                results.append(deliver(path, job.ticker, job.workdate,
                                       self.settings,
                                       attributions=attributions))
            self._finish(job, results[0])
            if self.queue is not None:
                extra = [f"clip {i}/{len(results)}: {r.link}"
                         for i, r in enumerate(results, 1)]

                def clips_on(fresh) -> None:
                    fresh.byproducts = extra + list(fresh.byproducts)

                self.queue.store.update(job.id, clips_on)
            return str(clips[0][0])

        raise RuntimeError(f"unknown job kind {job.kind}")

    def _local_link(self, job: JobRecord, out) -> None:
        """A draft's or a proof's link, on the STORED record: the worker
        reloads the job from disk when the executor returns, so a link set on
        the in-memory copy alone never reached `/status` or the done push."""
        job.delivered_link = f"file://{out}"
        if self.queue is not None:
            def link(fresh) -> None:
                fresh.delivered_link = job.delivered_link
            self.queue.store.update(job.id, link)

    def _refuse_synthetic_prices(self, script, format_name: str = "") -> None:
        """Stop a final whose price chart would be the synthetic floor.

        Approval runs the price gate, but a final can render hours later —
        the overnight window, a queue behind a long — on a fresh fetch, and
        a feed that died in between drew a seeded random walk into a video
        that ships. Checked here, before the paid voice, it costs nothing.
        """
        from pipeline.gates import check_prices

        blocks = [f for f in check_prices(script, self.settings, final=True,
                                          format_name=format_name)
                  if f.severity == "block"]
        if blocks:
            raise RuntimeError(blocks[0].message)

    @staticmethod
    def _attributions(manifest) -> list[str]:
        """The stock-footage credits a render recorded, or none."""
        import json as _json

        try:
            data = _json.loads(Path(manifest).read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return []
        got = data.get("attributions") if isinstance(data, dict) else None
        return list(got) if isinstance(got, list) else []

    def _publish_byproducts(self, job: JobRecord, ws: Workspace, script, tts,
                            manifest, fmt: str) -> list[Path]:
        """The free by-products of a finished render, for either format.

        The cover; subtitles straight off the master clock, so they match the
        burned-in captions exactly; the same clock unrounded, which is what
        the retention join names a sentence with; the transcript and the
        timestamps (27); the upload package; and the companion page (25).

        A SHORT used to get none of them — it delivered the MP4 alone — so
        `/upload short` went up with no thumbnail and no captions, its
        description had no "why this one", and its retention could never be
        joined to a sentence. Each format writes under its own names
        (`publish.byproduct_name`), because both lanes can share a folder.

        Best-effort: none of it is worth losing a completed render over.
        """
        from pipeline.publish import byproduct_name

        def path(kind: str) -> Path:
            return ws.path / byproduct_name(kind, fmt, job.ticker)

        extra: list[Path] = []
        try:
            from pipeline.thumbnail import make_thumbnail

            # Writes the 16:9, and the 9:16 beside it for a SHORT — which is
            # the one a SHORT ships.
            if make_thumbnail(script, ws, self.settings) and \
                    path("thumbnail").exists():
                extra.append(path("thumbnail"))
        except ImportError:
            pass
        try:
            from pipeline.companion import write_companion
            from pipeline.publish import (
                build_package, group_cues, timestamps_from_cues,
                transcript_text, write_srt, write_transcript,
            )
            from pipeline.retention_lines import write_words

            extra.append(write_srt(tts.words, path("captions")))
            write_words(tts.words, path("words"))
            extra.append(write_transcript(tts.words, path("transcript")))
            pkg = build_package(
                self._retimed(script, fmt, Path(manifest)), self.settings,
                ticker=job.ticker,
                runtime_min=tts.duration_s / 60.0,
                transcript=transcript_text(tts.words),
                timestamps=timestamps_from_cues(group_cues(tts.words)),
                why=ws.why, duration_s=tts.duration_s)
            pkg_path = path("package")
            pkg_path.write_text(pkg.render_text(), encoding="utf-8")
            extra.append(pkg_path)
            page = write_companion(Path(manifest), self.settings,
                                   out_path=path("companion"), why=ws.why)
            if page:
                extra.append(page)
        except Exception:  # noqa: BLE001
            log.exception("publishing by-products failed — delivering anyway")
        return extra

    def _run_proof(self, job: JobRecord, ws, checkpoint) -> str:
        """The free full-quality pass, for either format.

        Everything except the voice runs exactly as a final would — live
        prices, Pexels, Wikimedia, memes, SEC filings, charts — at full
        resolution and real fps. The voice comes from the free local tier.

        The $0 promise is enforced, not documented: `free_only=True` makes
        TTSEngine raise rather than reach ElevenLabs, so a mistyped command
        cannot spend. `draft=True` is what routes to the free tier; free_only
        is what guarantees it stayed routed there.
        """
        short = job.kind is JobKind.RENDER_PROOF_SHORT
        script = ws.load_short() if short else ws.load_long()
        if script is None:
            raise RuntimeError("script vanished before proof")
        held = ""
        checkpoint("tts")
        tts = self.tts.synthesize(
            script.audio_script if short else script.narration,
            "short" if short else "long",
            events=script.inline_events if short else script.events,
            draft=True, free_only=True,
        )
        checkpoint(f"proof audio ({tts.tier}) — not the real voice")
        if short:
            checkpoint("render")
            # `proof=True` picks `short_proof.mp4` (D5). It used to land on
            # `short_final.mp4` and replace a paid final with a free-voice
            # pass, which `/upload` would then send to YouTube.
            out, manifest = render_short(
                script, tts, ws.path, self.settings, content=self.content,
                proof=True, format_name=self.short_format_name(ws),
                company_data=self._company_data(ws))
            held = _frame_holds(manifest)
        else:
            data = self._company_data(ws)
            as_of = str(data.get("as_of_date") or "") if data is not None else ""
            checkpoint("storyboard")
            self._send_storyboard(job, script, tts, ws, data)
            checkpoint("render")

            def seg_progress(done: int, total: int) -> None:
                if done == total or done % 5 == 0:
                    checkpoint(f"proof {done}/{total} segments")

            out, _ = render_long(
                script, tts, ws.path, self.settings, content=self.content,
                proof=True, broll_overrides=ws.broll_overrides(),
                as_of=as_of, company_data=data, on_progress=seg_progress,
            )
        # Never delivered. A proof is for looking at, and `deliver()` is how
        # something reaches YouTube — the local path is the whole output.
        self._local_link(job, out)
        self.push_file(Path(out), (
            f"{job.ticker} — {'SHORT' if short else 'LONG'} PROOF, full "
            f"resolution, {tts.tier} voice, $0. Cue times move slightly under "
            f"the paid voice." + (f"\n\n{held}" if held else "")))
        return str(out)

    def _send_storyboard(self, job: JobRecord, script, tts, ws, data) -> None:
        """Contact sheet of the planned cut, pushed before the encode starts.

        Best-effort by design: a storyboard that fails to build must never
        stop a render the operator has already approved.
        """
        try:
            from pipeline.storyboard import (
                build_storyboard, host_share_lines, storyboard_caption,
            )
            from pipeline.timeline import (
                build_long_timeline, chapter_start_times,
                measured_chapter_times, paragraph_starts, plan_long_segments,
            )

            cues = build_long_timeline(script, tts.words, tts.duration_s)
            # The chapter times the render will use, measured off the voice,
            # so the sheet plans the same beats the encode does.
            guessed = chapter_start_times(script.chapters, tts.duration_s)
            measured = measured_chapter_times([t for t, _ in guessed],
                                              script.narration, tts.words,
                                              tts.duration_s)
            segments, _ = plan_long_segments(
                cues, tts.duration_s,
                chapter_starts=[(t, title) for t, (_g, title)
                                in zip(measured, guessed)],
                min_readable_s=self.settings.long_min_readable_s,
                chapter_host_s=self.settings.long_chapter_host_s,
                paragraphs=paragraph_starts(script.narration, tts.words),
                max_readable_s=self.settings.long_max_readable_s,
            )
            sheet, problems = build_storyboard(
                segments, tts.words, ws.path / "storyboard.png", self.settings,
                content=self.content, ticker=job.ticker, company_data=data,
                workspace=ws.path, title=f"{job.ticker} — LONG",
                chapters=script.chapter_list,
                overrides=ws.broll_overrides(),
                slots=swap_slots(script.events),
            )
            # How much of each chapter is Dennis alone in frame, flagged over
            # the operator's share (35%). Reported, never acted on: that is
            # the writer's call.
            shares = host_share_lines(segments, script.chapter_list,
                                      tts.duration_s,
                                      flag=self.settings.long_dennis_alone_max)
        except JobCancelled:
            # A cancel is not a storyboard failure. Swallowing it here would
            # answer the operator's cancel with "rendering anyway" and then
            # spend forty minutes doing exactly that.
            raise
        except Exception:  # noqa: BLE001
            # exc_info, not str(e): this branch is the only record that the
            # storyboard did not happen, and a bare exception message is not
            # enough to find the cause. The KeyError this used to mask printed
            # as "<TagType.BEAT: 'BEAT'>" and named neither file nor line.
            log.exception("storyboard failed for %s — rendering anyway",
                          job.ticker)
            return
        caption = storyboard_caption(
            f"{job.ticker} — storyboard, {len(segments)} beats", problems,
            shares)
        self.push_file(sheet, caption)

    def push_file(self, path: Path, caption: str = "") -> bool:
        """Send a file to the operator from a worker thread.

        `file_pusher` is wired by main.py against the bot's event loop; when
        it is absent (tests, CLI) the path is logged instead, which is all a
        local run needs.

        Returns whether it went. A failure used to be swallowed into the log
        and nowhere else (E3), so the operator watched for a proof that had
        silently failed to send — which is the same shape as everything else
        in this codebase that degraded without saying so.
        """
        if self.file_pusher is None:
            log.info("%s%s", caption + "\n" if caption else "", path)
            return True
        try:
            self.file_pusher(path, caption)
            return True
        except Exception as e:  # noqa: BLE001
            log.exception("could not push %s to the operator", path)
            self.notify(f"⚠️ could not send {Path(path).name}: {e}\n"
                        f"It is on the render box at {path}")
            return False

    def notify(self, text: str) -> None:
        """A line to the operator from a worker thread, best-effort."""
        if self.queue is not None and getattr(self.queue, "notifier", None):
            try:
                self.queue.notify_sync(text)
                return
            except Exception:  # noqa: BLE001
                log.exception("could not notify the operator")
        log.warning("operator notice (undelivered): %s", text)

    def _finish(self, job: JobRecord, result) -> None:
        """Consume the WHOLE DeliveryResult (E1, E2).

        It used to read `result.link` and `result.backend` and nothing else,
        which meant three things the delivery layer had already done were
        thrown away:

        - `send_file`, set by the telegram backend, was written and read
          nowhere. `DELIVERY_BACKEND=telegram` reported success, reported
          "(sent in chat)", and delivered nothing.
        - `extra_links` — the thumbnail, the `.srt`, the upload package, the
          attribution file — were uploaded to Drive or S3 and the operator
          was never told where.
        - `note`, carrying the Pexels and Wikimedia credits, likewise.
        """
        job.delivered_link = result.link
        # The telegram backend does not push the file itself: it hands it
        # back for the bot to send, because only the bot has the chat.
        send_file = getattr(result, "send_file", None)
        if send_file is not None and Path(send_file).exists():
            if self.push_file(Path(send_file), f"{job.ticker} — {job.kind.value}"):
                job.delivered_link = "(sent in chat)"
            else:
                job.delivered_link = f"file://{send_file} (send failed)"

        extras = self._byproduct_lines(result)
        # THE PROVENANCE RECORD RIDES ON THE DELIVERY (N3). Not a command:
        # the failure mode here is nobody looking, and a `/provenance`
        # gets typed when you already suspect something is wrong — which is
        # exactly when you do not need it. Attached to the link, it arrives
        # whether or not you thought to ask.
        record = self._provenance_text(job)
        if record:
            extras = extras + ["", record]
        if self.queue:
            def delivered(fresh) -> None:
                fresh.delivered_link = job.delivered_link
                fresh.detail = f"delivered via {result.backend}"
                fresh.byproducts = extras

            self.queue.store.update(job.id, delivered)
        journal.note(self.settings, "delivered",
                     f"{job.kind.value} delivered via {result.backend}: "
                     f"{job.delivered_link}",
                     ticker=job.ticker, workdate=job.workdate,
                     job_kind=job.kind.value, link=job.delivered_link)
        # A MOCK render is not a claim made in public (M13): its prices and
        # voice are invented, and a thesis pinned off it joined the intraday
        # watch, `/thesis`, `/update` and the scoreboard — and stayed there
        # after the box went live on the same state directory.
        if self.settings.mock_mode:
            log.info("MOCK_MODE: no thesis or confession pinned for %s",
                     job.ticker)
        else:
            self._record_thesis(job)

    def _provenance_text(self, job: JobRecord) -> str:
        """The record, read back off the manifest the render just wrote.

        Off the MANIFEST rather than rebuilt, so the machine-readable copy
        and the words the operator reads cannot say different things.
        """
        import json as _json

        from pipeline.provenance import Provenance

        ws = Workspace(self.settings, job.ticker, job.workdate)
        # THIS JOB'S format first. A folder holding both lanes answered a
        # SHORT's delivery with the LONG's record, because the LONG's name
        # came first in a fixed list.
        short = job.kind in (JobKind.RENDER_SHORT, JobKind.RENDER_PROOF_SHORT)
        manifest = self._manifest_for(ws, "short" if short else "long",
                                      trials=True)
        if manifest is None:
            return ""
        try:
            data = _json.loads(manifest.read_text(encoding="utf-8"))
        except (_json.JSONDecodeError, OSError):
            return ""
        block = data.get("provenance") if isinstance(data, dict) else None
        return Provenance.from_json(block).render_text() if block else ""

    @staticmethod
    def _byproduct_lines(result) -> list[str]:
        """The by-products the delivery already produced, as text lines.

        `RenderJobQueue._done_text` formats the success push, so that is
        where these belong — attached to the link the operator receives
        rather than waiting to be asked for.
        """
        lines: list[str] = []
        for name, link in (getattr(result, "extra_links", None) or {}).items():
            lines.append(f"{name}: {link}" if link else name)
        note = (getattr(result, "note", "") or "").strip()
        if note:
            lines.extend(note.splitlines())
        return lines

    def _record_thesis(self, job: JobRecord) -> None:
        """Pin the thesis and its numbers when a video ships (P3.3).

        At ship time, because that is the moment the claim becomes public —
        and best-effort, because a bookkeeping failure must never turn a
        delivered video into a failed job.
        """
        if not self.settings.thesis_tracking:
            return
        if job.kind not in (JobKind.RENDER_LONG, JobKind.RENDER_SHORT):
            return
        try:
            from pipeline.standing import ThesisBook

            ws = Workspace(self.settings, job.ticker, job.workdate)
            data = self._company_data(ws)
            if data is None:
                return
            fmt = "short" if job.kind is JobKind.RENDER_SHORT else "long"
            script = ws.load_short() if fmt == "short" else ws.load_long()
            summary = ws.chosen_angle() or ""
            if not summary:
                summary = (getattr(script, "title", "")
                           or getattr(script, "hook_text", "") or "")
            said = _what_it_said(script, fmt)
            ThesisBook(self.settings).record(
                job.ticker, summary, data, workdate=job.workdate, fmt=fmt,
                **said)
            journal.note(self.settings, "thesis",
                         f"pinned the {fmt.upper()} thesis: {summary[:200]}",
                         ticker=job.ticker, workdate=job.workdate, fmt=fmt)
            self._note_confession(job, script, fmt)
        except Exception as e:  # noqa: BLE001 - never fail a shipped video
            log.warning("thesis bookkeeping failed for %s: %s", job.ticker, e)

    def _note_confession(self, job: JobRecord, script, fmt: str) -> None:
        """Add this video to the confession ledger — including a silent one.

        EVERY shipped video is noted, not only the ones that confessed. "Roughly
        one video in three" is a question about the two that did not, and a
        ledger holding only the admissions can say what has been used but not
        how long it has been, which is the half that decides whether to write
        one at all.
        """
        from pipeline.standing import ConfessionLedger

        said = getattr(script, "confession", None)
        ConfessionLedger(self.settings).note(
            job.ticker, fmt=fmt, workdate=job.workdate,
            kind=getattr(said, "kind", "") or "",
            text=getattr(said, "text", "") or "")

    # --------------------------------------------- standing state (P3.3)
    def queue_text(self, limit: int = 10) -> Reply:
        """The ranked backlog, so a session never starts from a blank page."""
        from pipeline.standing import IdeaQueue

        q = IdeaQueue(self.settings)
        q.prune(self.settings.idea_queue_max_age_days)
        return Reply(q.render(limit) + "\n\n/short TICKER or /long TICKER to start one.")

    def queue_add(self, args: list[str]) -> Reply:
        from pipeline.standing import IdeaQueue

        if not args:
            return Reply("Usage: /idea TICKER <why it's worth covering>")
        ticker = args[0].upper()
        reason = " ".join(args[1:]).strip() or "operator pick"
        IdeaQueue(self.settings).add(ticker, reason, source="operator", score=2.0)
        return Reply(f"🗂 queued {ticker} — {reason}")

    def queue_drop(self, args: list[str]) -> Reply:
        from pipeline.standing import IdeaQueue

        if not args:
            return Reply("Usage: /unidea TICKER")
        ticker = args[0].upper()
        dropped = IdeaQueue(self.settings).drop(ticker)
        return Reply(f"🗂 {'dropped' if dropped else 'not in the queue'}: {ticker}")

    def thesis_text(self, args: list[str]) -> Reply:
        """What we said about a ticker, and whether it still holds.

        Re-reads the pinned numbers against the current export, so this is a
        live check rather than a recital of what was stored.
        """
        from pipeline.standing import ThesisBook, ideas_from_thesis_moves, update_warranted

        book = ThesisBook(self.settings)
        if not args:
            covered = book.tickers()
            if not covered:
                return Reply("No theses on file yet — one is pinned each time a "
                             "video ships.")
            rows = []
            for t in covered:
                th = book.get(t)
                icon = {"intact": "🟢", "cracking": "🟡", "broken": "🔴"}.get(
                    th.status, "⚪")
                rows.append(f"{icon} {t} — {th.summary[:60] or '(no summary)'}")
            return Reply("📌 Theses on file\n" + "\n".join(rows)
                         + "\n\n/thesis TICKER re-checks one against today's numbers.")

        ticker = args[0].upper()
        th = book.get(ticker)
        if th is None:
            return Reply(f"No thesis on file for {ticker}.")
        from pipeline.company_data import find_export

        ws = self._ws_or_error(ticker, lambda w: find_export(w.path) is not None)
        data = self._company_data(ws) if ws else None
        if data is None:
            return Reply(f"📌 {ticker}: {th.summary}\n"
                         f"(no current data to check it against — /short "
                         f"{ticker} or /long {ticker}, then upload the "
                         f"workbook)")
        th, moves = book.check(ticker, data)
        icon = {"intact": "🟢", "cracking": "🟡", "broken": "🔴"}.get(th.status, "⚪")
        body = f"{icon} {ticker} — THESIS: {th.status.upper()}\n{th.summary}"
        note = update_warranted(moves, ticker)
        if note:
            ideas_from_thesis_moves(self.settings, ticker, moves)
            body += f"\n\n{note}\n(added to the idea queue)"
        else:
            body += "\n\nNothing behind it has moved materially."
        return Reply(body)

    def batch_text(self, args: list[str]) -> Reply:
        """Queue renders to run unattended overnight."""
        from pipeline.standing import BatchQueue

        b = BatchQueue(self.settings)
        if not args:
            return Reply(b.render())
        head = args[0].lower()
        if head == "clear":
            return Reply(f"🌙 cleared {b.clear()} batch entr(ies).")
        if head in ("list", "show", "ls"):
            return Reply(b.render())
        ticker = head.upper()
        if not _TICKER_RE.match(ticker):
            return Reply(f"⛔ {args[0]!r} is not a ticker. "
                         f"Usage: /batch [TICKER [short|long] | run | clear]")
        fmt = (args[1].lower() if len(args) > 1 else "")
        if fmt not in ("short", "long"):
            ws = self._ws_or_error(ticker, lambda w: any(
                (w.path / f"script_{f}.json").exists() for f in ("short", "long")))
            fmt = (ws.current_format() if ws else None) or "long"
        b.add(ticker, fmt)
        return Reply(f"🌙 {ticker} {fmt.upper()} queued for the overnight batch.\n"
                     + b.render())

    def batch_plan(self) -> tuple[list[tuple], list[str], str]:
        """(submittable, skipped reasons, note). Pure — submitting is async.

        Everything that can't run is reported rather than dropped: a batch
        that silently skipped the one render you cared about is worse than no
        batch. Nothing expires either — if the machine was asleep, the work is
        still here the next time the window opens.
        """
        from pipeline.standing import BatchQueue, in_batch_window

        b = BatchQueue(self.settings)
        pending = b.pending()
        if not self.settings.batch_enabled:
            return [], [], "🌙 the overnight batch is switched off (BATCH_ENABLED)."
        if not pending:
            return [], [], "🌙 nothing queued."
        submittable: list[tuple] = []
        skipped: list[str] = []
        store = self.queue.store if self.queue is not None else None
        for item in pending:
            if item.job_id and store is not None:
                job = store.load(item.job_id)
                status = job.status.value if job is not None else ""
                if status in ("queued", "running"):
                    continue                       # still going: leave it be
                if status == "done":
                    b.mark_done(item.ticker, item.fmt)
                    continue
                # failed, cancelled, interrupted or gone: run it again, and
                # say why the last one did not finish.
                why = (job.error or job.detail or status) if job else "lost"
                b.reopen(item.ticker, item.fmt, f"last run {status or 'lost'}: "
                                                f"{str(why)[:120]}")
            kind, text, ws = self.render_request(item.ticker, item.fmt)
            if kind is None or ws is None:
                skipped.append(f"{item.ticker} {item.fmt.upper()}: {text}")
                continue
            submittable.append((kind, ws, item))
        note = "" if in_batch_window(self.settings) else (
            "(outside the overnight window — running anyway because you asked)")
        return submittable, skipped, note

    def batch_done(self, ticker: str, fmt: str, error: str = "") -> None:
        from pipeline.standing import BatchQueue

        BatchQueue(self.settings).mark_done(ticker, fmt, error)

    async def run_batch(self) -> tuple[int, list[str], str]:
        """Submit what the batch holds: `(queued, skipped, report)`.

        One runner for `/batch run` and the overnight window, so the two
        cannot drift apart. A render the queue already has — queued or
        running — is the render the batch wanted, so the entry is closed
        rather than left to submit a second copy once the first finishes.
        """
        from pipeline.standing import BatchQueue

        submittable, skipped, note = self.batch_plan()
        queued = 0
        for kind, ws, item in submittable:
            try:
                job = await self.queue.submit(kind, ws.ticker, ws.workdate)
                # Closed when THIS job is done, by the next batch pass — a
                # render that fails overnight is still queued tomorrow.
                BatchQueue(self.settings).mark_submitted(item.ticker, item.fmt,
                                                         job.id)
                queued += 1
            except ValueError as e:
                # The queue already has this render: follow that job instead
                # of submitting a second copy behind it.
                active = next((j for j in self.queue.store.all()
                               if j.ticker == ws.ticker and j.kind == kind
                               and j.status.value in ("queued", "running")),
                              None)
                if active is not None:
                    BatchQueue(self.settings).mark_submitted(
                        item.ticker, item.fmt, active.id)
                    # Said once, on the pass that finds it: the entry is
                    # closed when that render is, not submitted again.
                    skipped.append(f"{item.ticker} {item.fmt.upper()}: already "
                                   f"{active.status.value} — following that "
                                   f"render instead of starting another")
                    continue
                self.batch_done(item.ticker, item.fmt, str(e))
                skipped.append(f"{item.ticker} {item.fmt.upper()}: {e}")
        lines = [f"🌙 batch: {queued} queued, {len(skipped)} skipped"]
        lines += [f"  ⛔ {s}" for s in skipped[:6]]
        if note:
            lines.append(f"  {note}")
        return queued, skipped, "\n".join(lines)

    # --------------------------------- YouTube publishing (P3.5 + 5b)
    def upload_command(self, args: list[str]) -> Reply:
        """`/upload TICKER [short|long|clip [N]|pair] [again] [YYYY-MM-DD HH:MM]`
        — private, or scheduled.

        Never public: the most this does unattended is schedule, and a human
        still decides whether that schedule was right.

        A render that already went up is not sent again unless `again` says
        so: a second `/upload` used to make a second private video, and
        `published.json` — kept "so /upload does not re-upload" — was read
        by nothing for that.
        """
        from pipeline.youtube import (
            UploadError, YouTubeUnavailable, available, resolve_publish_at,
            upload_video,
        )

        if not args:
            return Reply("Usage: /upload TICKER [YYYY-MM-DD HH:MM]\n"
                         "No time = private. A time = scheduled publish.")
        ticker = args[0].upper()
        rest = list(args[1:])
        # An explicit format, so a ticker with both, or a repurposed clip,
        # can be reached at all (E5). `/upload EXMPL short 2026-09-20`.
        wanted_fmt = ""
        if rest and rest[0].lower() in ("short", "long", "clip", "pair"):
            wanted_fmt = rest.pop(0).lower()
        clip_n = 1
        if wanted_fmt == "clip" and rest and rest[0].isdigit():
            clip_n = max(int(rest.pop(0)), 1)
        again = any(r.lower() == "again" for r in rest)
        rest = [r for r in rest if r.lower() != "again"]
        when_raw = " ".join(rest).strip()
        try:
            when = resolve_publish_at(when_raw or None, settings=self.settings)
        except ValueError as e:
            return Reply(f"⛔ {e}")

        ws = self._ws_or_error(ticker, self._has_video(wanted_fmt))
        ticker = Workspace.split_arg(ticker)[0]
        if ws is None:
            return Reply(f"No workspace for {ticker}.")
        if wanted_fmt == "pair":
            return self._upload_pair(ws, when, again=again)
        fmt, video, why = self._upload_target(ws, wanted_fmt, clip_n)
        if video is None:
            return Reply(why)
        if not again:
            from pipeline.youtube import VideoLog, record_format

            done = [v for v in VideoLog(self.settings).for_ticker(ws.ticker)
                    if v.workdate == ws.workdate and record_format(v) == fmt
                    and (fmt != "clip"
                         or abs(v.clip_start_s - self._clip_start(video)) < 0.5)]
            if done:
                v = max(done, key=lambda r: r.uploaded_at)
                return Reply(
                    f"⛔ {ws.ticker} {fmt.upper()} ({ws.workdate}) is already "
                    f"up: {v.url()} ({v.privacy}). /upload {ws.ticker} "
                    f"{fmt} again … sends a second copy.")

        package = self._upload_package(ws, fmt, video)
        if package is None:
            return Reply("⛔ no upload package on file — re-render to build one.")
        # What is about to be sent, on disk, so the by-hand fallback below
        # attaches exactly that rather than whatever the render left.
        from pipeline.publish import byproduct_name

        pkg_path = ws.path / (byproduct_name("package", fmt)
                              or f"upload_package_{fmt}.txt")
        try:
            pkg_path.write_text(package.render_text(), encoding="utf-8")
        except OSError:
            log.warning("could not write %s", pkg_path)

        ok, why = available(self.settings)
        if not ok:
            return Reply(
                f"⛔ can't upload from here: {why}\n"
                f"The package is attached — post it by hand.",
                files=[pkg_path] if pkg_path.exists() else [])
        try:
            record = upload_video(
                video, package, self.settings, publish_at=when,
                workdate=ws.workdate,
                chapters=self._chapter_pairs(ws, fmt, video),
                duration_s=self._render_duration(ws, fmt, video),
                # Both are written by every finished render and were handed
                # to `deliver` and to nobody else (E7).
                thumbnail=self._byproduct(ws, "thumbnail", fmt),
                captions=self._byproduct(ws, "captions", fmt),
                fmt=fmt)
        except (UploadError, YouTubeUnavailable) as e:
            return Reply(f"⛔ upload failed: {e}\nThe package is still yours "
                         f"to post by hand.",
                         files=[pkg_path] if pkg_path.exists() else [])
        except Exception as e:  # noqa: BLE001
            log.exception("youtube upload blew up")
            return Reply(f"💥 upload error: {e}")

        if record.privacy == "scheduled":
            tail = f"scheduled to publish {record.publish_at}"
        else:
            tail = "uploaded PRIVATE — publish it when you're ready"
        note = ""
        if record.comment_posted is True:
            note = ("\n📌 comment posted — pin it in YouTube Studio; the API "
                    "cannot pin.")
        elif record.comment_posted is False and package.pinned_comment:
            note = ("\n📌 the comment did not post (a private video often "
                    "refuses one). Post and pin it once the video is public:\n"
                    f"{package.pinned_comment}")
        return Reply(f"📺 {ticker}: {tail}\n{record.url()}{note}",
                     keyboard=uploaded_keyboard(ticker))

    def probe_command(self, args: list[str]) -> Reply:
        """`/probe TICKER [short|long]` — where YouTube puts the AI label (05).

        `youtube.disclosure_probe` was built for this and never reachable
        from the chat. Whether the synthetic-media label lands under the
        player or only in the expanded description is a property of the
        watch page, so the one way to know is one unlisted upload of a real
        render with the box ticked. Unlisted, never public, never scheduled,
        and not recorded as a published video; delete it once you have
        looked.
        """
        from pipeline.youtube import (
            UploadError, YouTubeUnavailable, available, disclosure_probe,
        )

        if not args:
            return Reply("Usage: /probe TICKER [short|long] — one UNLISTED "
                         "upload of a finished render, to see where YouTube "
                         "puts the AI label.")
        ticker = args[0].upper()
        wanted = args[1].lower() if len(args) > 1 else ""
        if wanted not in ("", "short", "long"):
            return Reply("Usage: /probe TICKER [short|long]")
        ws = self._ws_or_error(ticker, self._has_video(wanted))
        if ws is None:
            return Reply(f"No workspace for {ticker}.")
        fmt, video, why = self._upload_target(ws, wanted)
        if video is None:
            return Reply(why)
        package = self._upload_package(ws, fmt, video)
        if package is None:
            return Reply("⛔ no script on file to describe the probe with.")
        if not self.settings.mock_mode:
            ok, why = available(self.settings)
            if not ok:
                return Reply(f"⛔ can't upload from here: {why}")
        try:
            return Reply(disclosure_probe(video, package, self.settings))
        except (UploadError, YouTubeUnavailable) as e:
            return Reply(f"⛔ probe upload failed: {e}")
        except Exception as e:  # noqa: BLE001
            log.exception("disclosure probe blew up")
            return Reply(f"💥 probe error: {e}")

    def _clip_start(self, clip: Path) -> float:
        """Where in the long this clip was cut from, off its own sidecar."""
        import json as _json

        try:
            info = _json.loads(
                clip.with_suffix(".repurpose.json").read_text(encoding="utf-8"))
            return float((info.get("window") or [0.0])[0])
        except (OSError, ValueError, TypeError, IndexError):
            return 0.0

    def _upload_pair(self, ws: Workspace, when, *, again: bool = False) -> Reply:
        """`/upload TICKER pair` — ship two clips off one long, tagged (33).

        The only free experiment in this pipeline. `/repurpose` has always cut
        two or three non-overlapping windows and one of them shipped; the rest
        were thrown away. Two clips off one render cost no voice generation,
        no fetching and no new composition, and they differ in exactly one
        thing — which minute of the argument they carry. So they go up as a
        pair and `/experiments` compares them once both have views.
        """
        from pipeline.experiments import pair_id
        from pipeline.youtube import (
            UploadError, VideoLog, YouTubeUnavailable, available, record_format,
            upload_video,
        )

        clips = sorted(ws.path.glob("short_repurposed*.mp4"))
        if len(clips) < 2:
            return Reply(
                f"Only {len(clips)} clip on file for {ws.ticker} — a pair "
                f"needs two. /repurpose {ws.ticker} cuts up to three out of a "
                f"finished LONG.")
        ok, why = available(self.settings)
        if not ok:
            return Reply(f"⛔ can't upload from here: {why}")
        tag = pair_id(ws.ticker, ws.workdate)
        lines = [f"🅰🅱 {ws.ticker}: two clips off one render, tagged as a pair"]
        # The single upload's "already up" guard, per clip: run twice (or
        # again after the second clip failed) this sent every clip again, and
        # the pair's tag then covered the duplicates.
        up = [] if again else [
            v for v in VideoLog(self.settings).for_ticker(ws.ticker)
            if v.workdate == ws.workdate and record_format(v) == "clip"]
        sent = 0
        for n, clip in enumerate(clips[:2], 1):
            done = [v for v in up if abs(v.clip_start_s - self._clip_start(clip)) < 0.5]
            if done:
                v = max(done, key=lambda r: r.uploaded_at)
                lines.append(f"  at {self._clip_start(clip):.0f}s — already up: "
                             f"{v.url()} ({v.privacy})")
                continue
            package = self._upload_package(ws, "clip", clip)
            if package is None:
                return Reply("⛔ no upload package on file — re-render to "
                             "build one.")
            try:
                record = upload_video(
                    clip, package, self.settings, publish_at=when,
                    workdate=ws.workdate,
                    duration_s=self._render_duration(ws, "clip", clip),
                    experiment=tag,
                    clip_start_s=self._clip_start(clip), fmt="clip")
            except (UploadError, YouTubeUnavailable) as e:
                # The first may already be up. Say so rather than implying
                # neither went: an untagged single is still a shipped video.
                which = ("the second" if n == 2 else "the first (nothing went up)")
                return Reply("\n".join(lines + [
                    f"⛔ {which} failed: {e}",
                    f"/upload {ws.ticker} pair, run again, sends only what is not up."]))
            except Exception as e:  # noqa: BLE001
                log.exception("clip pair upload blew up")
                return Reply("\n".join(lines + [f"💥 upload error: {e}"]))
            sent += 1
            lines.append(f"  at {self._clip_start(clip):.0f}s — {record.url()}")
        if not sent:
            lines.append(f"Both are already up. /upload {ws.ticker} pair again "
                         f"sends second copies.")
            return Reply("\n".join(lines))
        lines.append("/experiments compares them once both have a day or two "
                     "of views.")
        return Reply("\n".join(lines))

    def scheduled_text(self, now=None) -> Reply:
        from pipeline.youtube import VideoLog

        rows = VideoLog(self.settings).scheduled(now=now)
        if not rows:
            return Reply("📺 nothing scheduled.\n"
                         "/upload TICKER 2026-08-07 18:00 schedules one.")
        lines = ["📺 Scheduled"]
        for v in rows:
            lines.append(f"  {v.publish_at[:16].replace('T', ' ')} — "
                         f"{v.ticker}: {v.title[:50]}")
        return Reply("\n".join(lines))

    def retention_text(self, args: list[str]) -> Reply:
        """Per-chapter retention for one video, or the evidence across all."""
        from pipeline.youtube import (
            VideoLog, chapter_type_evidence, pull_retention, retention_report,
        )

        log_ = VideoLog(self.settings)
        if not args:
            evidence = chapter_type_evidence(self.settings)
            if not evidence:
                return Reply("No retention data yet. /retention TICKER pulls it "
                             "for a published video (YouTube needs a day or two "
                             "of views first). Videos uploaded before the "
                             "chapter type was recorded never count towards "
                             "this — the evidence starts from the next one.")
            lines = ["📊 Which chapter types hold attention (all videos)"]
            for row in evidence[:12]:
                # The type is what aggregates; a title is what the operator
                # recognises, so one of them rides along as the reminder of
                # which chapter this actually was.
                eg = (row.get("titles") or [""])[0]
                lines.append(f"  {row['avg_watch_ratio'] * 100:5.1f}%  "
                             f"{row['type'][:24]:<24} (n={row['videos']})"
                             + (f'  e.g. "{eg[:38]}"' if eg else ""))
            lines.append("\nWorst first. One video is an anecdote; the same "
                         "chapter type dropping across several is evidence.")
            return Reply("\n".join(lines))

        ticker = args[0].upper()
        videos = log_.for_ticker(ticker)
        if not videos:
            return Reply(f"Nothing published for {ticker} yet.")
        video = max(videos, key=lambda v: v.uploaded_at)
        payload = pull_retention(video.video_id, self.settings)
        if payload.get("status") != "ok":
            stored = (video.retention or {}).get("chapters")
            if stored:
                return Reply(f"({payload.get('reason', 'live pull unavailable')})"
                             f"\n\n{retention_report(stored)}")
            return Reply(f"📊 {ticker}: {payload.get('reason', payload['status'])}")
        return Reply(f"📊 {ticker} — {video.title[:60]}\n"
                     + retention_report(payload["chapters"]))

    def _upload_package(self, ws: Workspace, fmt: str, video=None):
        """The package `/upload` sends, built the way the render built it.

        It used to be rebuilt from the script alone, so the description that
        actually went to YouTube had no "why this one", no transcript and no
        timestamps — all three were in `upload_package.txt` and nowhere else —
        and its chapter list was not cut to the rendered length, which is the
        list YouTube reads. A clip is cut from the LONG, so it is the LONG's
        script that describes it, and the LONG's chapter list describes
        twenty minutes the clip does not have: it gets none.
        """
        from pipeline.models import WordTimestamp
        from pipeline.publish import (
            build_package, group_cues, timestamps_from_cues, transcript_text,
        )
        from pipeline.retention_lines import load_words

        script = ws.load_short() if fmt == "short" else ws.load_long()
        if script is None:
            return None
        if fmt == "long":
            script = self._retimed(script, fmt, self._manifest_for(ws, "long"))
        duration = self._render_duration(ws, fmt, video)
        transcript, timestamps = "", ()
        if fmt in ("short", "long"):
            try:
                words = [WordTimestamp(**w) for w in load_words(ws.path, fmt)]
            except (TypeError, ValueError):
                words = []
            if words:
                transcript = transcript_text(words)
                timestamps = timestamps_from_cues(group_cues(words))
        return build_package(
            script, self.settings, ticker=ws.ticker,
            runtime_min=duration / 60.0, transcript=transcript,
            timestamps=timestamps, why=ws.why, duration_s=duration,
            with_chapters=fmt != "clip")

    @staticmethod
    def _retimed(script, fmt: str, manifest: Path | None):
        """`script` with its chapter trailer re-timed to the render's own
        chapters (M8).

        The trailer's `mm:ss` are the writer's guesses; the render moves each
        onto the audio and records where it put it in the manifest. The
        YouTube chapter list and the per-chapter retention map are built from
        the trailer, so they are built from that record — the times the
        viewer actually sees the chapter openers — when there is one.
        """
        if fmt != "long" or script is None or manifest is None:
            return script
        import json as _json

        try:
            rows = _json.loads(Path(manifest).read_text(encoding="utf-8")
                               ).get("chapters") or []
        except (OSError, ValueError, AttributeError):
            return script
        lines = []
        for r in rows:
            try:
                t = max(int(round(float(r["t"]))), 0)
                title = str(r["title"]).strip()
            except (KeyError, TypeError, ValueError):
                return script
            ctype = str(r.get("type") or "").strip()
            stamp = (f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}"
                     if t >= 3600 else f"{t // 60:02d}:{t % 60:02d}")
            lines.append(f"{stamp} {ctype} | {title}" if ctype
                         else f"{stamp} {title}")
        if not lines:
            return script
        try:
            return script.model_copy(update={"chapters": "\n".join(lines)})
        except Exception:  # noqa: BLE001 - the guessed trailer still serves
            return script

    def _chapter_pairs(self, ws: Workspace, fmt: str, video=None) -> list:
        from pipeline.publish import normalise_chapters

        script = ws.load_long() if fmt == "long" else None
        if script is not None:
            script = self._retimed(script, fmt, self._manifest_for(ws, "long"))
        # The rendered duration, so a chapter the cut left behind the end of
        # the video is dropped rather than shipped — YouTube renders no
        # chapter list at all when one is out of range.
        return normalise_chapters(getattr(script, "chapters", "") or "",
                                  self._render_duration(ws, fmt, video))

    def _byproduct(self, ws: Workspace, kind: str,
                   fmt: str = "long") -> Path | None:
        """One format's by-product the render already wrote, if it is still
        there — a missing one is a thing to skip, not to fail on.

        By FORMAT, because both lanes can share a folder: the first `*.srt`
        in it was sent with whatever was uploaded, so a SHORT could go up
        with the LONG's captions. A clip gets neither: it is cut from the
        LONG, so the LONG's `.srt` runs on the wrong clock for it and the
        LONG's cover is the wrong shape.
        """
        from pipeline.publish import byproduct_name

        name = byproduct_name(kind, fmt, ws.ticker)
        candidates = [ws.path / name] if name else []
        for found in candidates:
            if found.is_file() and found.stat().st_size:
                return found
        return None

    @staticmethod
    def short_format_name(ws: Workspace) -> str:
        """Which shot template a SHORT renders through (G7).

        `/headline` detects a mode — company, earnings or macro — and stored
        it on the workspace, and `render_short` defaulted to `"short"` on
        every call from the bot. So `templates/shots/earnings.json` and
        `templates/shots/macro.json` were reachable only from the sample
        script, and the mode changed the WRITING PROMPT and nothing
        downstream.

        That matters more than an unused template: the three formats are
        different arguments with different beat orders. `short` is "noise or
        signal" — chart first, then the news, then multi-year numbers, then a
        valuation judgement. `earnings` is "did they beat, and does it
        matter" — the print against expectations, then guidance, and no price
        chart at all. `macro` is "what happened and who does it hurt" — the
        print, the statement, a mechanism, a who-it-hits beat, and no company
        numbers sheet, because there is no company. An earnings script landed
        on the plain short's chart-first ten beats and the mismatch was
        silent.
        """
        mode = str((ws.headline() or {}).get("mode") or "")
        return mode if mode in ("earnings", "macro") else "short"

    @staticmethod
    def _has_video(wanted: str):
        """A `Workspace.resolve` test: does this folder hold the render
        `/upload` or `/probe` was asked for?"""
        def test(w: Workspace) -> bool:
            if wanted in ("clip", "pair"):
                return any(w.path.glob("short_repurposed*.mp4"))
            f = wanted or w.current_format() or "long"
            return (w.path / f"{f}_final.mp4").exists()
        return test

    def _upload_target(self, ws: Workspace, wanted: str = "", clip_n: int = 1,
                       ) -> tuple[str, Path | None, str]:
        """Which file `/upload` should send, and why if none (E5).

        Three gaps here, all the same shape: the command could only reach
        whichever format the FOLDER "was".

        - `fmt = ws.current_format() or "long"` meant a workspace holding
          both formats had one reachable. The lane decides that now (C3),
          and an explicit `short`/`long`/`clip` argument overrides it.
        - The path was hard-coded to `long_final.mp4` / `short_final.mp4`,
          so a repurposed clip — a finished, deliverable artefact — could
          not be uploaded at all.
        """
        if wanted == "clip":
            clips = sorted(ws.path.glob("short_repurposed*.mp4"))
            if not clips:
                return "clip", None, (
                    f"No repurposed clips for {ws.ticker} — /repurpose "
                    f"{ws.ticker} cuts them from a finished LONG.")
            if clip_n > len(clips):
                return "clip", None, (
                    f"{ws.ticker} has {len(clips)} repurposed clip(s); there "
                    f"is no clip {clip_n}.")
            return "clip", clips[clip_n - 1], ""

        fmt = wanted or ws.current_format() or "long"
        video = ws.path / ("long_final.mp4" if fmt == "long"
                           else "short_final.mp4")
        if video.exists():
            return fmt, video, ""

        # Say what IS there rather than only what is not: with both lanes in
        # one folder, "no finished SHORT" while a LONG sits beside it is the
        # confusing half of the message.
        other = "short" if fmt == "long" else "long"
        alt = ws.path / f"{other}_final.mp4"
        clips = sorted(ws.path.glob("short_repurposed*.mp4"))
        extra = ""
        if alt.exists():
            extra = f" The {other.upper()} is rendered — /upload {ws.ticker} {other}."
        elif clips:
            extra = (f" {len(clips)} repurposed clip(s) are — "
                     f"/upload {ws.ticker} clip.")
        return fmt, None, (
            f"No finished {fmt.upper()} render for {ws.ticker} yet.{extra}")

    # WHERE EACH RENDERER WRITES ITS MANIFEST (E5). The SHORT was read from
    # `render_short_manifest.json` under the key `"duration"`; it writes
    # `short_final.manifest.json` under `"duration_s"`. Both wrong, so SHORT
    # runtime was always 0.0 in the upload package and the YouTube record.
    #
    # Finals first, then the passes that only look (a proof, a draft): the
    # commands that map retention onto a cut used to take the first
    # `*manifest*.json` in sorted order, which in a folder holding a /draft
    # is the draft's — the right video's retention laid over the wrong
    # voice's timings. The LONG's final depends on the engine that cut it.
    _MANIFEST_NAMES: dict[str, dict[str, tuple[str, ...]]] = {
        "long": {"final": ("render_long_manifest.json",
                           "long_final.manifest.json"),
                 "trial": ("render_long_proof_manifest.json",
                           "render_long_draft_manifest.json")},
        "short": {"final": ("short_final.manifest.json",),
                  "trial": ("short_proof.manifest.json",)},
    }

    def _manifest_for(self, ws: Workspace, fmt: str | None = None, *,
                      trials: bool = False) -> Path | None:
        """The manifest of one format's render — or, with no format, the
        lane's first and then the other's. `trials` lets a proof or a draft
        answer when there is no final."""
        order = [fmt] if fmt else [ws.current_format() or "long",
                                   "long", "short"]
        order = [f for f in dict.fromkeys(order) if f in self._MANIFEST_NAMES]
        names = [n for f in order for n in self._MANIFEST_NAMES[f]["final"]]
        if trials:
            names += [n for f in order
                      for n in self._MANIFEST_NAMES[f]["trial"]]
        for name in names:
            if (ws.path / name).is_file():
                return ws.path / name
        return None

    def _render_duration(self, ws: Workspace, fmt: str,
                         video: Path | None = None) -> float:
        manifest = (self._manifest_for(ws, fmt)
                    if fmt in self._MANIFEST_NAMES else None)
        if manifest is not None:
            try:
                import json as _json
                data = _json.loads(manifest.read_text(encoding="utf-8"))
                # The LONG's manifest says "duration"; the shot engine,
                # which cuts every SHORT, says "duration_s".
                got = float(data.get("duration_s") or data.get("duration")
                            or 0)
                if got:
                    return got
            except (ValueError, OSError, TypeError, AttributeError):
                pass
        # A repurposed clip has no manifest of its own, and a manifest that
        # has been swept still leaves the file. Measuring the artefact is
        # slower and always right, so it is the fallback rather than a
        # reported zero.
        if video is not None and Path(video).exists():
            try:
                from pipeline.render_common import ffprobe_duration

                return float(ffprobe_duration(Path(video)))
            except Exception:  # noqa: BLE001 - a duration is not worth failing on
                log.warning("could not measure %s", video)
        return 0.0

    # ------------------------------------------ intraday alerting (3b)
    def watch_command(self, args: list[str]) -> Reply:
        """What gets watched intraday, and when the watched names report."""
        from pipeline.alerts import EarningsCalendar, Watchlist, in_quiet_hours

        wl = Watchlist(self.settings)
        if args and args[0].lower() in ("list", "show", "ls"):
            args = []                     # `/watch list` is the listing
        if args:
            head = args[0].lower()
            if head in ("drop", "remove", "off"):
                # Without the ticker this used to fall through and start
                # WATCHING A STOCK CALLED "DROP" (G6) — the guard required a
                # second argument and there was no else.
                if len(args) < 2:
                    return Reply(
                        f"Usage: /watch drop TICKER\n"
                        f"Currently watched: "
                        f"{', '.join(wl.all()) or '(nothing)'}")
                ticker = args[1].upper()
                gone = wl.remove(ticker)
                return Reply(f"👁 {'unpinned' if gone else 'was not pinned'}: {ticker}"
                             f"\n(names with a thesis on file are always watched.)")
            ticker = head.upper()
            if not _TICKER_RE.match(ticker):
                return Reply(f"⛔ {args[0]!r} is not a ticker. "
                             f"Usage: /watch TICKER | /watch drop TICKER")
            wl.add(ticker)
            return Reply(f"👁 watching {ticker} intraday.")

        watched = wl.all()
        if not watched:
            return Reply("👁 nothing on the intraday watch yet.\n"
                         "/watch TICKER pins one; every ticker you publish is "
                         "watched automatically.")
        lines = ["👁 Intraday watch", "  " + ", ".join(watched)]
        soon = EarningsCalendar(self.settings).upcoming()
        if soon:
            lines.append("\n📊 Reporting soon")
            for e in soon:
                slot = {"bmo": "before the open", "amc": "after the close"}.get(
                    e.when, "")
                lines.append(f"  {e.ticker} — {e.date}{' ' + slot if slot else ''}")
        if in_quiet_hours(self.settings):
            lines.append("\n(quiet hours right now — nothing will be pushed)")
        return Reply("\n".join(lines))

    def earnings_command(self, args: list[str]) -> Reply:
        """Tell the bot when a name reports, so it can flag both sides."""
        from pipeline.alerts import EarningsCalendar

        if len(args) < 2:
            return Reply("Usage: /earnings TICKER YYYY-MM-DD [bmo|amc]")
        ticker = args[0].upper()
        when_date = args[1]
        try:
            date.fromisoformat(when_date)
        except ValueError:
            return Reply(f"⛔ {when_date!r} isn't a date — use YYYY-MM-DD.")
        slot = args[2].lower() if len(args) > 2 else ""
        if slot and slot not in ("bmo", "amc"):
            return Reply("⛔ the third argument is bmo (before open) or amc "
                         "(after close).")
        EarningsCalendar(self.settings).set(ticker, when_date, slot)
        return Reply(f"📊 {ticker} reports {when_date}"
                     f"{' ' + slot if slot else ''}. I'll flag it before and after.")

    # ----------------------------------------------------------- utilities
    def cost_text(self) -> str:
        broken = ("" if self.ledger.readable() else
                  "⛔ THE SPEND LEDGER CANNOT BE READ — every paid call is "
                  f"refused until {self.ledger.path} is restored "
                  "(scripts/backup_state.py keeps archives). The figures "
                  "below are not this month's.\n")
        return broken + (
            f"💰 Month-to-date: ${self.ledger.mtd_spend_usd():.2f} of "
            f"${self.settings.monthly_spend_cap_usd:.2f} cap\n"
            f"Pexels calls: {self.ledger.pexels_calls_this_month()} of "
            f"{self.settings.pexels_monthly_call_cap}\n"
            f"Filing-flagger LLM: ${self.ledger.llm_usd_this_month():.2f}\n"
            # HOW OLD IS THE NUMBER ABOVE (P7). Every figure here is what
            # Dennis BELIEVES it spent — chunks counted at the configured
            # rate, against a cap enforced from the same number. Nothing
            # reconciles it against the provider, so a drift is invisible
            # from inside and the first symptom is a bill. Same reasoning as
            # the provenance record: the failure mode is nobody looking, so
            # the number that matters carries its own age.
            f"{self.ledger.reconciled_line()}\n"
            + self._mock_status_line()
        )

    # ------------------------------------------- retention, scripts, receipts

    def lines_text(self, args: list[str]) -> str:
        """`/lines TICKER` — where a published video lost them, by sentence."""
        from pipeline.retention_lines import (
            holds_for_video, line_report, narration_for,
        )
        from pipeline.youtube import VideoLog, record_format

        if not args:
            return "usage: /lines TICKER"
        ticker = args[0].upper()
        records = VideoLog(self.settings).for_ticker(ticker)
        if not records:
            return (f"No uploaded video on record for {ticker}. "
                    f"/lines reads retention off videos this bot uploaded.")
        record = max(records, key=lambda v: v.uploaded_at)
        if record_format(record) == "clip":
            return (f"{ticker}'s latest upload is a clip. Its retention "
                    f"runs on the clip's own clock and the only sentence "
                    f"timings on file are the LONG's, so it cannot be placed "
                    f"sentence by sentence.")
        return line_report(holds_for_video(
            self.settings, record, narration_for(self.settings, record)))

    def hooks_text(self, args: list[str]) -> str:
        """`/hooks` — the openers that held, over their own first seconds."""
        from pipeline.retention_lines import hook_bench_text

        fmt = (args[0].lower() if args else "short")
        return hook_bench_text(self.settings,
                               fmt=fmt if fmt in ("short", "long") else "short")

    def rules_text(self) -> str:
        """`/rules` — what the voice rules are worth, measured."""
        from pipeline.retention_lines import rule_evidence_text

        return rule_evidence_text(self.settings)

    def runtime_text(self) -> str:
        """`/runtime` — hold against how long the videos run."""
        from pipeline.retention_lines import runtime_evidence_text

        return runtime_evidence_text(self.settings)

    def lessons_text(self, args: list[str]) -> str:
        """`/lessons [now]` — the weekly note the writing prompts carry.

        `now` rewrites it first: a fresh retention pull, the counts, and one
        call to the local model. Free either way — the note's model call never
        reaches the paid hosted tier.
        """
        from pipeline.retention_notes import notes_text, refresh_notes

        if args and args[0].lower() == "now":
            summary = refresh_notes(self.settings)
            return f"Rewritten: {summary}\n\n{notes_text(self.settings)}"
        return notes_text(self.settings)

    def shots_text(self, args: list[str]) -> str:
        """`/shots TICKER` — which shots of a published video lose people."""
        import json as _json

        from pipeline.retention_lines import shot_holds, shot_report
        from pipeline.youtube import VideoLog, record_format

        if not args:
            return "usage: /shots TICKER"
        ticker = args[0].upper()
        records = VideoLog(self.settings).for_ticker(ticker)
        if not records:
            return f"No uploaded video on record for {ticker}."
        record = max(records, key=lambda v: v.uploaded_at)
        fmt = record_format(record)
        if fmt == "clip":
            return (f"{ticker}'s latest upload is a clip, which has no cut of "
                    f"its own on file — only the LONG it came from does.")
        ws = Workspace(self.settings, ticker, record.workdate)
        found = self._manifest_for(ws, fmt) if ws.exists else None
        if found is None:
            return (f"No render manifest left in {ticker}'s workspace — "
                    f"cleanup prunes the heavy artefacts after "
                    f"{self.settings.retention_days} days.")
        try:
            manifest = _json.loads(found.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            return f"That manifest could not be read: {e}"
        return shot_report(shot_holds(manifest, record.retention,
                                      record.duration_s))

    def stillness_text(self, args: list[str]) -> str:
        """`/stillness TICKER` — how long the picture holds still.

        Offline: this needs a manifest and nothing else, so it answers for a
        video that has never been uploaded.
        """
        import json as _json

        from pipeline.pacing import dead_air_report, frame_holds_report

        if not args:
            return "usage: /stillness TICKER"
        ws = self._ws_or_error(
            args[0].upper(),
            lambda w: self._manifest_for(w, trials=True) is not None)
        # The lane's final first; a proof or a draft answers when that is all
        # there is, since this is the check to run before anything ships.
        found = self._manifest_for(ws, trials=True) if ws else None
        if found is None:
            return f"No render manifest for {args[0].upper()} to read."
        try:
            manifest = _json.loads(found.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            return f"That manifest could not be read: {e}"
        measured = frame_holds_report(manifest)
        return "\n\n".join(
            x for x in (dead_air_report(manifest), measured) if x)

    # ------------------------------------------ asking the bot about itself
    def find_text(self, args: list[str]) -> str:
        """`/find WORDS` — every saved record with those words, no model."""
        from pipeline.recall import find_text

        return find_text(self.settings, " ".join(args or []))

    def ask_text(self, args: list[str]) -> str:
        """`/ask QUESTION` — the local model, reading the bot's own records.

        Blocking for as long as the model takes, so the glue runs it off the
        event loop. Counts and totals never reach the model.
        """
        from pipeline.recall import ask

        return ask(self.settings, " ".join(args or [])).text

    def said_text(self, args: list[str]) -> str:
        """`/said PHRASE` — have I used this line before?"""
        from pipeline.corpus import Corpus

        phrase = " ".join(args or [])
        if not phrase.strip():
            return "usage: /said some phrase you think you have used before"
        hits = Corpus(self.settings, fresh=True).search(phrase)
        if not hits:
            return f"Nothing in the corpus says “{phrase}”. It is new."
        lines = [f"🔁 {len(hits)} earlier use(s) of “{phrase}”"]
        for entry, said in hits[:8]:
            lines.append(f"  {entry.ticker} {entry.workdate}: {said[:90]}")
        return "\n".join(lines)

    def why_command(self, args: list[str]) -> str:
        """`/why TICKER your sentence` — the human judgement, on the record."""
        if not args:
            return ("usage: /why TICKER why this one is worth making, in "
                    "your own words")
        ticker = args[0].upper()
        ws = self._ws_or_error(ticker)
        ticker = Workspace.split_arg(ticker)[0]
        if ws is None or not ws.exists:
            return f"No workspace for {ticker} — start one with /short or /long."
        text = " ".join(args[1:]).strip()
        if not text:
            return (ws.why or
                    f"Nothing recorded for {ticker} yet. "
                    f"/why {ticker} <your sentence> records it.")
        ws.set_why(text)
        return (f"Recorded against {ticker} {ws.workdate}. It prints above "
                f"Approve and rides the description.")

    def experiments_reply(self) -> str:
        """`/experiments` — the clip pairs, and which one held."""
        from pipeline.experiments import experiments_text

        return experiments_text(self.settings)

    def scoreboard_reply(self, args: list[str]) -> str:
        """`/scoreboard [YYYY-Qn]` — what we said, and what happened."""
        from pipeline.scoreboard import scoreboard_text

        return scoreboard_text(self.settings, args[0] if args else "")

    def correct_command(self, args: list[str]) -> str:
        """`/correct TICKER what was wrong` — after the video has shipped."""
        from pipeline.youtube import UploadError, corrections_text, pin_correction

        if not args:
            return corrections_text(self.settings)
        ticker = args[0].upper()
        text = " ".join(args[1:]).strip()
        if not text:
            return f"usage: /correct {ticker} what the right number is"
        try:
            return pin_correction(ticker, text, self.settings)
        except UploadError as e:
            return f"⛔ {e}"
        except Exception as e:  # noqa: BLE001
            log.exception("correction failed")
            return f"💥 the correction did not post: {e}"

    def cost_reply(self, args: list[str] | None = None) -> Reply:
        """`/cost` and its one subcommand.

        The routing lives here rather than in the PTB glue so it can be
        exercised without a Telegram application — and so a typo gets an
        answer instead of the report printed as if it had been understood.
        """
        what = (args[0].lower() if args else "")
        if not what:
            return Reply(self.cost_text())
        if what in ("reconciled", "reconcile"):
            return Reply(self.mark_reconciled())
        if what in ("explain", "where", "breakdown"):
            return Reply(self.ledger.explain_text())
        return Reply("usage: /cost  |  /cost explain  |  /cost reconciled")

    def mark_reconciled(self) -> str:
        """`/cost reconciled` — stamp today against the ledger."""
        stamp = self.ledger.mark_reconciled()
        return (
            f"✅ ledger marked reconciled on {stamp}.\n"
            f"Month-to-date reads ${self.ledger.mtd_spend_usd():.2f} — that "
            f"is the figure you just checked against the provider's own "
            f"dashboard.\n\nThis stamps a date and nothing else. It does "
            f"not verify anything, and it is worth exactly as much as the "
            f"check you actually did.")

    # ------------------------------------------------- the video card (§3)
    def _card_ws(self, ticker: str = "", chat_id: int | None = None,
                 workdate: str = "") -> Workspace | None:
        if ticker and workdate:
            ws = Workspace(self.settings, ticker, workdate)
            return ws if ws.exists else None
        if ticker:
            return self._ws_or_error(ticker)
        return self._active_ws(chat_id) if chat_id is not None else None

    def video_card(self, ticker: str = "", chat_id: int | None = None,
                   workdate: str = "") -> Reply:
        """Where one video is — data, script, approval, renders, upload —
        and the next tap, in one message. Viewing a card does not make it
        the active video: a paste after `/card OTHER` must still land in
        the video you were working on."""
        from pipeline.video_state import card_text, video_state

        ws = self._card_ws(ticker, chat_id, workdate)
        if ws is None:
            name = Workspace.split_arg(ticker)[0] if ticker else ""
            return Reply(f"No video for {name} — /new short {name} or "
                         f"/new long {name} starts one." if name else
                         "No active video — /new short TICKER or "
                         "/new long TICKER starts one.")
        jobs = self.queue.store.all() if self.queue else None
        st = video_state(self.settings, ws, jobs=jobs)
        return Reply(card_text(st), keyboard=card_keyboard(st), card=st.key)

    def inbox_reply(self) -> Reply:
        """Everything waiting on you, with a button for the first few."""
        from bot.keyboards import inbox_keyboard
        from pipeline.video_state import inbox, inbox_text

        items = inbox(self.settings)
        return Reply(inbox_text(items),
                     keyboard=inbox_keyboard(items) if items else None)

    def calendar_text(self, args: list[str]) -> Reply:
        """`/publish calendar [weeks]` — the publishing week, gaps marked."""
        from datetime import datetime as _dt
        from datetime import timedelta as _td
        from datetime import timezone as _tz

        from pipeline.youtube import VideoLog, record_format

        weeks = 1
        if args and args[0].isdigit():
            weeks = min(max(int(args[0]), 1), 6)
        try:
            from zoneinfo import ZoneInfo
            zone = ZoneInfo(self.settings.publish_timezone)
        except Exception:  # noqa: BLE001 - a bad zone reads in UTC
            zone = _tz.utc
        today = _dt.now(zone).date()
        days: dict = {today + _td(days=i): [] for i in range(7 * weeks)}
        for v in VideoLog(self.settings).all():
            when_raw = v.publish_at if v.privacy == "scheduled" else ""
            if not when_raw:
                continue
            try:
                when = _dt.fromisoformat(when_raw.replace("Z", "+00:00"))
            except ValueError:
                continue
            if when.tzinfo is None:
                when = when.replace(tzinfo=_tz.utc)
            local = when.astimezone(zone)
            if local.date() in days:
                days[local.date()].append(
                    f"{local:%H:%M} {v.ticker} {record_format(v).upper()}")
        lines = [f"📅 Publishing, next {7 * weeks} days "
                 f"({self.settings.publish_timezone})"]
        gaps = 0
        for day, rows in days.items():
            label = f"{day:%a %d %b}"
            if rows:
                lines.append(f"  {label}  " + " · ".join(sorted(rows)))
            else:
                gaps += 1
                lines.append(f"  {label}  — gap")
        lines.append(f"\n{gaps} day(s) with nothing going out. "
                     f"/publish TICKER YYYY-MM-DD HH:MM schedules one.")
        return Reply("\n".join(lines))

    def show_report(self, chat_id: int, ticker: str = "",
                    workdate: str = "") -> Reply:
        """The stored report, with its buttons, without re-running the
        intake (which re-plans visuals and calls the model)."""
        ws = self._card_ws(ticker, chat_id, workdate)
        if ws is None:
            return Reply("No video to show a report for.")
        fmt = ws.current_format()
        report = ws.path / f"report_{fmt}.txt" if fmt else None
        if report is None or not report.exists():
            return Reply("No report on file yet — paste the script first.")
        script = ws.load_short() if fmt == "short" else ws.load_long()
        text = report.read_text(encoding="utf-8")
        if script is None:
            return Reply(text)
        from pipeline.video_state import video_state

        st = video_state(self.settings, ws, jobs=[], videos=[])
        if st.approved:
            est = None if st.tts_cached else st.est_usd
            return Reply("✅ approved\n\n" + text,
                         keyboard=approved_keyboard(fmt, ws.ticker,
                                                    ws.workdate, est))
        has_broll = fmt == "long" and bool(self.swappable_slots(script))
        return Reply(text, keyboard=approval_keyboard(
            fmt, ws.ticker, ws.workdate, script.content_sha(),
            bool(st.report_ok), has_broll))

    def render_confirm(self, fmt: str, ticker: str, workdate: str) -> Reply:
        """The second tap before money moves: what it costs, how long it
        takes, and the month so far."""
        from pipeline.video_state import video_state

        ws = Workspace(self.settings, ticker, workdate)
        if not ws.exists:
            return Reply(f"No workspace {ticker} {workdate}.")
        if not ws.is_approved(fmt):
            return Reply(f"⛔ {ticker} {fmt.upper()} is not approved (or the "
                         f"script changed after approval) — approve the "
                         f"report first; the approval is the spend gate.")
        st = video_state(self.settings, ws, jobs=[], videos=[])
        cost = ("voice already paid for (cache) — $0.00" if st.tts_cached
                else f"~${st.est_usd:.2f} voice" if st.est_usd is not None
                else "voice cost not on the report")
        took = (f", ~{st.est_render_min:.0f} min to render"
                if st.est_render_min else "")
        mtd = self.ledger.mtd_spend_usd()
        return Reply(
            f"💰 Render {ticker} {fmt.upper()} ({workdate})?\n"
            f"{cost}{took}.\n"
            f"Month so far: ${mtd:.2f} of ${self.settings.monthly_spend_cap_usd:.2f}.",
            keyboard=confirm_render_keyboard(fmt, ticker, workdate))

    def angle_pick(self, chat_id: int, ticker: str, workdate: str,
                   n: str) -> Reply:
        """An angle button: the same as typing its number."""
        ws = Workspace(self.settings, ticker, workdate)
        if not ws.exists:
            return Reply(f"No workspace {ticker} {workdate}.")
        if not ws.awaiting_angle():
            return Reply("That angle is already picked — the next step is "
                         "pasting the script.")
        self.context.set(chat_id, ticker, workdate)
        with llm_scope(self._llm_scope(ws)):
            return self._intake_angle(ws, str(n))

    # -------------------------------------------- cancel, and its undo (§8)
    UNDO_CANCEL_S = 60.0

    def cancel_jobs(self, ticker_arg: str) -> Reply:
        """Cancel a ticker's queued and running jobs and withdraw its
        approvals — remembering both for a minute, so a mis-tap can be put
        back."""
        import time

        ticker = Workspace.split_arg(ticker_arg)[0]
        if not ticker:
            return Reply("Usage: /jobs cancel TICKER")
        cancelled = self.queue.cancel(ticker) if self.queue else []
        # Every workspace a cancelled job was rendering, as well as the
        # newest: the approval worth withdrawing is the one the job was
        # spending against, which need not be today's folder.
        spaces = {(j.ticker, j.workdate) for j in cancelled}
        latest = Workspace.resolve(self.settings, ticker_arg)
        if latest:
            spaces.add((latest.ticker, latest.workdate))
        approvals: dict[str, str] = {}
        for t, d in spaces:
            ws = Workspace(self.settings, t, d)
            for fmt in ("short", "long"):
                f = ws._approval_file(fmt)
                if f.exists():
                    approvals[str(f)] = f.read_text(encoding="utf-8")
                ws._invalidate_approval(fmt)
        self._last_cancel = {
            "at": time.monotonic(), "ticker": ticker,
            "jobs": [(j.kind, j.ticker, j.workdate) for j in cancelled],
            "approvals": approvals}
        undo = (approvals or cancelled)
        return Reply(
            f"🚫 {ticker}: {len(cancelled)} job(s) cancelled, approvals "
            f"withdrawn." + (" Undo within a minute puts both back."
                             if undo else ""),
            keyboard=undo_cancel_keyboard() if undo else None)

    def undo_cancel_plan(self) -> tuple[list, str]:
        """Put the withdrawn approvals back and say which jobs to resubmit.
        The resubmitting is async (the queue), so the caller does it."""
        import time

        last = getattr(self, "_last_cancel", None)
        if not last or time.monotonic() - last["at"] > self.UNDO_CANCEL_S:
            return [], ("Nothing to undo — a cancel can be undone for a "
                        "minute after it.")
        self._last_cancel = None
        restored = 0
        for path, text in last["approvals"].items():
            p = Path(path)
            if not p.exists():
                # The approval pins the script's hash, so putting it back
                # cannot approve a script that changed since: `is_approved`
                # compares it against the script on disk.
                p.write_text(text, encoding="utf-8")
                restored += 1
        return list(last["jobs"]), (
            f"↩️ {last['ticker']}: {restored} approval(s) restored")

    def _mock_status_line(self) -> str:
        """Which subsystems are fake, spelled out — never just "mock mode".

        Three of them can be mocked independently now, and a run with real
        prices and a placeholder voice looks identical to a run with neither
        unless something says so.

        This is also the ONLY mode line in `/cost` (A2). There used to be a
        second one above it derived from `MOCK_MODE`, which is not the thing
        that decides whether the voice spends — `mocking_tts` is, and it
        follows the `MOCK_TTS` override. With `MOCK_MODE=true MOCK_TTS=false`
        the old line read "no paid calls possible" directly above this one
        reading "TTS: live", contradicting itself inside one reply.
        """
        s = self.settings
        rows = [f"{name}: {'MOCK' if on else 'live'}" for name, on in (
            ("TTS", s.mocking_tts), ("Prices", s.mocking_prices),
            ("Screener", s.mocking_screener))]
        # The headline is whether MONEY can move, and only the voice spends
        # per render. Pexels and the filing flagger follow MOCK_MODE, so say
        # so separately rather than folding them into one claim.
        spending = "no paid calls possible" if s.mocking_tts and s.mock_mode \
            else "paid calls possible"
        head = f"Mode: {spending}\n"
        banner = s.mock_banner()
        return head + "  ·  ".join(rows) + (f"\n{banner}" if banner else "")


# ---------------------------------------------------------------------------
# PTB glue: thin async wrappers around BotCore.
# ---------------------------------------------------------------------------


def schedule_batch(application, core: BotCore) -> None:
    """Open the overnight window (the README's "the window picks it up").

    `/batch TICKER` queued, BATCH_START_HOUR and BATCH_END_HOUR were read by
    the listing, and nothing ever ran in the window: the queue only moved on
    `/batch run`. This checks every quarter of an hour, so a box that wakes
    at 03:00 still runs the night's work; outside the window, or with
    nothing queued, a pass does nothing and says nothing. An entry that
    cannot run yet (no approval) stays queued, as `/batch` promises, and is
    reported once a night rather than every pass.
    """
    settings = core.settings
    if not settings.batch_enabled:
        log.info("overnight batch disabled (BATCH_ENABLED)")
        return
    reported: set[str] = set()

    async def batch_job(ctx) -> None:
        from pipeline.standing import BatchQueue, in_batch_window

        if not in_batch_window(settings) or not BatchQueue(settings).pending():
            return
        try:
            queued, skipped, text = await core.run_batch()
        except Exception as e:  # noqa: BLE001 - a pass that dies waits for the next
            log.warning("overnight batch pass failed (%s)", e)
            return
        said = f"{date.today().isoformat()}|{'|'.join(sorted(skipped))}"
        if not queued and (not skipped or said in reported):
            return              # nothing new: entries still rendering, say nothing
        reported.add(said)
        for chat_id in settings.operator_chat_ids:
            await ctx.bot.send_message(chat_id, text)

    application.job_queue.run_repeating(
        batch_job, interval=15 * 60, first=60, name="overnight_batch")
    log.info("overnight batch window %02d:00-%02d:00 (machine clock)",
             settings.batch_start_hour, settings.batch_end_hour)


def schedule_retention_notes(application, core: BotCore) -> None:
    """Rewrite the note to the writer once a week (`RETENTION_NOTE_DAYS`).

    Checked every six hours against the note's own date rather than run on a
    seven-day timer, so a box that restarts every few days still writes it.
    A pass that has nothing due does nothing and says nothing; the operator
    hears about it only when a lane had enough videos to say something.
    """
    settings = core.settings
    if not settings.retention_notes_enabled:
        log.info("weekly retention note disabled (RETENTION_NOTES_ENABLED)")
        return

    async def notes_job(ctx) -> None:
        import asyncio

        from pipeline.retention_notes import (NOTE_FLOOR, load_notes,
                                              notes_due, refresh_notes)

        if not notes_due(settings):
            return
        try:
            summary = await asyncio.to_thread(refresh_notes, settings)
        except Exception as e:  # noqa: BLE001 - a pass that dies waits for the next
            log.warning("weekly retention note failed (%s)", e)
            return
        log.info("weekly retention note: %s", summary)
        notes = load_notes(settings)
        if not any((notes.get(f) or {}).get("status") == "ok"
                   for f in ("short", "long")):
            return
        for chat_id in settings.operator_chat_ids:
            await ctx.bot.send_message(
                chat_id, f"📝 Weekly note to the writer rewritten ({summary}). "
                         f"/lessons shows it; the next prompt carries it. "
                         f"A lane needs {NOTE_FLOOR} videos before it counts.")

    application.job_queue.run_repeating(
        notes_job, interval=6 * 3600, first=10 * 60, name="retention_notes")


# The cloud Bot API's limit on what a bot may DOWNLOAD (getFile).
TELEGRAM_DOWNLOAD_MAX_BYTES = 20_000_000


def _authorized(core: BotCore, chat_id: int) -> bool:
    ids = core.settings.operator_chat_ids
    return bool(ids) and chat_id in ids


async def _ship(reply: Reply | str, text_fn, photo_fn, doc_fn):
    """Send a Reply through three senders; returns the message that carries
    its keyboard (the one a video card is edited through)."""
    # Half the read commands return a bare string. They were handed here
    # as-is and died on `.text`, so /said, /lines, /hooks, /rules, /runtime,
    # /shots, /stillness, /why, /experiments, /scoreboard and /correct
    # answered "internal error" in Telegram while their tests, which call
    # BotCore directly, passed.
    if isinstance(reply, str):
        reply = Reply(reply)
    text = reply.text
    if not text and reply.keyboard is not None:
        text = "…"          # a keyboard rides on a message, so it needs one
    carrier = None
    while text:  # Telegram 4096-char message cap
        chunk, text = text[:4000], text[4000:]
        msg = await text_fn(chunk, reply_markup=reply.keyboard if not text else None)
        if not text:
            carrier = msg
    if reply.photo is not None:
        with open(reply.photo, "rb") as f:
            await photo_fn(f)
    for path in reply.files:
        with open(path, "rb") as f:
            await doc_fn(f, filename=Path(path).name)
    return carrier


async def send_reply(bot, chat_id: int, reply: Reply | str):
    """A push to a chat — nothing to reply to (a finished render, the
    morning inbox)."""
    return await _ship(
        reply,
        lambda t, reply_markup=None: bot.send_message(chat_id, t,
                                                      reply_markup=reply_markup),
        lambda f: bot.send_photo(chat_id, f),
        lambda f, filename=None: bot.send_document(chat_id, f,
                                                   filename=filename))


async def _send(update, reply: Reply | str):
    """An answer, as a reply to the message (or button) that asked — which
    keeps it in the same forum topic."""
    msg = update.effective_message
    return await _ship(
        reply, msg.reply_text,
        lambda f: msg.reply_photo(f),
        lambda f, filename=None: msg.reply_document(f, filename=filename))


def build_application(settings: Settings, core: BotCore):
    """Wire PTB. Import here so BotCore stays importable without a token.

    Every command comes from the registry in `bot/commands.py` — one
    handler per name, the families and the old names alike — so there is no
    second list here to drift from `/help`, the menu and the README.
    """
    from telegram import Update
    from telegram.ext import (
        Application,
        CallbackQueryHandler,
        CommandHandler,
        ContextTypes,
        MessageHandler,
        filters,
    )

    from bot import commands as cmds

    def guard(fn):
        async def wrapped(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
            chat_id = update.effective_chat.id
            if not _authorized(core, chat_id):
                log.warning("unauthorized chat %s", chat_id)
                await update.effective_message.reply_text(
                    f"Not authorized. Add your chat id ({chat_id}) to OPERATOR_CHAT_IDS."
                )
                return
            try:
                await fn(update, ctx)
            except Exception as e:  # surface, never crash the loop
                log.exception("handler error")
                await update.effective_message.reply_text(f"💥 internal error: {e}")
        return wrapped

    async def deliver(update, reply: Reply) -> None:
        """Send, and remember the message when it is a video card so the
        card can edit itself as the video moves."""
        msg = await _send(update, reply)
        board = getattr(core, "cards", None)
        if reply.card and msg is not None and board is not None:
            board.remember(reply.card, update.effective_chat.id, msg.message_id)
        feed = getattr(core, "feed", None)
        if feed is not None:
            feed.add("reply", reply.text, files=reply.files, keyboard=reply.keyboard)

    def _after_command(update) -> str:
        """The message text after `/command`, verbatim — line breaks and all
        (M10). `ctx.args` is that text split on whitespace."""
        text = update.effective_message.text or ""
        parts = text.split(None, 1)
        return parts[1] if len(parts) > 1 else ""

    def command(name: str):
        @guard
        async def handler(update, ctx):
            async def say(reply: Reply) -> None:
                await _send(update, reply)

            reply = await cmds.run_command(
                core, update.effective_chat.id, name, list(ctx.args or []),
                raw=_after_command(update), say=say)
            await deliver(update, reply)
        handler.__name__ = f"cmd_{name}"
        return handler

    @guard
    async def on_unknown(update, ctx):
        text = update.effective_message.text or ""
        name = text.split(None, 1)[0].lstrip("/") if text else ""
        if "@" in name:
            # `/cmd@otherbot` in a group is somebody else's command.
            addressed = name.split("@", 1)[1].lower()
            if addressed != (ctx.bot.username or "").lower():
                return
        await _send(update, Reply(cmds.unknown_command_text(name)))

    async def _say(update):
        async def say(reply: Reply) -> None:
            await _send(update, reply)
        return say

    @guard
    async def on_text(update, ctx):
        # An angle pick and a short remark come back fast; a pasted script
        # does not, and only the slow one is acknowledged ("got it").
        reply = await cmds.handle_text(core, update.effective_chat.id,
                                       update.effective_message.text or "",
                                       say=await _say(update))
        await deliver(update, reply)

    @guard
    async def on_document(update, ctx):
        doc = update.effective_message.document
        # The cloud Bot API hands a bot files up to 20 MB and refuses the rest
        # with an error that read here as "internal error".
        size = getattr(doc, "file_size", 0) or 0
        if (not settings.telegram_api_base_url
                and size > TELEGRAM_DOWNLOAD_MAX_BYTES):
            await _send(update, Reply(
                f"⛔ {doc.file_name or 'that file'} is {size / 1e6:.0f} MB — "
                f"the cloud Bot API only lets a bot download up to 20 MB. "
                f"Trim the clip or export a smaller file, use the web panel "
                f"(/admin panel), or drop it into assets/custom/ on the "
                f"render box by hand."))
            return
        f = await doc.get_file()
        data = bytes(await f.download_as_bytearray())
        reply = await cmds.handle_upload(core, update.effective_chat.id,
                                         doc.file_name or "upload.bin", data,
                                         say=await _say(update))
        await deliver(update, reply)

    @guard
    async def on_photo(update, ctx):
        msg = update.effective_message
        photo = msg.photo[-1]
        f = await photo.get_file()
        data = bytes(await f.download_as_bytearray())
        # Telegram re-encodes a photo as JPEG, so it is named one. A caption
        # names it: a photo captioned with a pending [SCREENGRAB] slug is
        # that capture, which a nameless photo could never be.
        caption = (msg.caption or "").strip().split()
        stem = caption[0] if caption else f"screenshot_{photo.file_unique_id}"
        reply = await cmds.handle_upload(core, update.effective_chat.id,
                                         f"{stem}.jpg", data)
        await deliver(update, reply)

    @guard
    async def on_callback(update, ctx):
        q = update.callback_query
        await q.answer()
        reply = await cmds.handle_callback(core, update.effective_chat.id,
                                           q.data or "", say=await _say(update))
        await deliver(update, reply)

    builder = Application.builder().token(settings.telegram_bot_token)
    if settings.telegram_api_base_url:
        builder = builder.base_url(f"{settings.telegram_api_base_url}/bot")
    app = builder.build()

    for name in cmds.telegram_names():
        app.add_handler(CommandHandler(name, command(name)))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    # Last: a command none of the above answered gets "did you mean…"
    # rather than silence.
    app.add_handler(MessageHandler(filters.COMMAND, on_unknown))

    async def send_to(chat_id: int, reply: Reply) -> int | None:
        msg = await send_reply(app.bot, chat_id, reply)
        if reply.card and msg is not None and core.cards is not None:
            core.cards.remember(reply.card, chat_id, msg.message_id)
        if core.feed is not None:
            core.feed.add("notice", reply.text, files=reply.files,
                          keyboard=reply.keyboard)
        return msg.message_id if msg is not None else None

    async def edit_card(chat_id: int, message_id: int, reply: Reply) -> None:
        try:
            await app.bot.edit_message_text(
                reply.text[:4000] or "…", chat_id=chat_id,
                message_id=message_id, reply_markup=reply.keyboard)
        except Exception as e:  # noqa: BLE001
            if "not modified" not in str(e).lower():
                raise

    core.cards = cmds.CardBoard(core, send=send_to, edit=edit_card)
    core.send_to = send_to
    return app
