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
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw

from config import Settings
from pipeline.broll import ContentManager, palette_keys
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
from pipeline.delivery import deliver
from pipeline.excel_refresh import (
    ExcelUnavailable,
    RefreshError,
    RefreshTimeout,
    excel_available,
    refresh_age_days,
    refresh_for_ticker,
    set_symbol_override,
)
from pipeline.gates import run_gates
from pipeline.jobs import JobCancelled, JobRecord, RenderJobQueue
from pipeline.models import JobKind, TagType
from pipeline.parser_long import LongScriptError, parse_long_script, validate_long_script
from pipeline.parser_short import ScriptParseError, parse_short_script
from pipeline.rasters import load_font
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

from bot.keyboards import approval_keyboard, filing_veto_keyboard, swap_keyboard
from bot.prompts import fill_prompt

log = logging.getLogger(__name__)

HELP_TEXT = """Dennis — operator commands

/short TICKER — start a SHORT (9:16, 60–75s); refreshes the numbers itself
/long TICKER — start a LONG (16:9 deep dive, value lane)
/update TICKER — revisit a name we've covered: what I said, what happened, was I right
/refresh TICKER [RIC] — re-pull the numbers in Excel; a RIC pins the override
/headline TICKER <news> — a SHORT about a specific headline (macro: /headline macro <text>)
/prompts — re-send this lane's pre-filled master prompt
/screen [trending|value|all] — ranked candidates (trending → SHORT, value → LONG)
/ideas — the ranked backlog; /idea TICKER <why> adds, /unidea TICKER drops
/thesis [TICKER] — what we said, and whether the numbers still back it
/batch [TICKER [fmt] | run | clear] — queue renders to run unattended overnight
/upload TICKER [YYYY-MM-DD HH:MM] — YouTube, private or scheduled (never public)
/scheduled — what's queued to publish and when
/retention [TICKER] — per-chapter drop-off; no ticker = the evidence across all
/watch [TICKER | drop TICKER] — intraday watch (published names join automatically)
/earnings TICKER YYYY-MM-DD [bmo|amc] — so the bot flags the print both sides
/render TICKER — render the approved script for this ticker's lane
/render_long TICKER — force the LONG (only needed if a ticker has both)
/script — the stored script, numbered, ready to edit
/edit N <text> — replace line N (N-M for a range; no text deletes it)
/replace old => new — fix a figure or a phrase in place (all: for every hit)
/undo — step back one revision
/draft TICKER — cheap low-res LONG timing check (no TTS spend)
/proof TICKER [short|long] — FULL-RES look test: real visuals, free voice, $0
/repurpose TICKER — free 9:16 SHORT from the finished LONG
/status — job queue
/cancel TICKER — cancel queued/running jobs + pending approval
/cost — month-to-date spend vs cap
/kit doctor — unresolved tag keys, never-used artwork, unregistered PNGs
/help — this text

Flow: /short or /long TICKER (the numbers refresh themselves; upload
dennis_data.xlsx if Excel isn't available) → run the prompt in Claude/GPT →
(LONG: pick an angle; I auto-pull the 10-K shots) → paste the output back
here → review the validation & cost report → tweak it in chat if you want
(/script, /edit, /replace — every revision re-runs the gates and re-prices)
→ Approve ✅ → /render. Nothing paid happens before Approve, and the approval
is pinned to the exact version you approved. If a LONG uses [ASSET] tags, paste the appended
prompt into Claude Design and upload the exported PNG here — the render
stays blocked until every asset file exists."""


@dataclass
class Reply:
    text: str
    keyboard: object | None = None  # telegram.InlineKeyboardMarkup
    files: list[Path] = field(default_factory=list)
    photo: Path | None = None


# ---------------------------------------------------------------------------
# /headline mode detection — company (A) · earnings (B) · macro (C).
# ---------------------------------------------------------------------------

# common index / sector proxies + the "macro" keyword all route to macro mode
_INDEX_SYMS = {"SPY", "QQQ", "DIA", "IWM", "VIX", "TLT", "VOO", "IVV", "RSP", "MARKET"}
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
        titles = [title for _ts, title in
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

    # ------------------------------------------------------------- helpers
    def _ws_or_error(self, ticker: str) -> Workspace | None:
        return Workspace.latest_for(self.settings, ticker)

    def _active_ws(self, chat_id: int) -> Workspace | None:
        return self.context.get(chat_id)

    def _company_data(self, ws: Workspace):
        try:
            return load_company_data(ws.path)
        except CompanyDataError:
            return None

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
        if lane == "long" and not update:
            ws.set_awaiting_angle()
        else:
            ws.clear_awaiting_angle()

        label = ("UPDATE (16:9 — grading the last call)" if update else
                 "SHORT (9:16, 60–75s)" if lane == "short" else
                 "LONG (16:9 deep dive)")
        head = f"📁 {ticker} / {ws.workdate} — {label}"
        warn = "" if update else self._lane_warning(ticker, lane)

        name = "update" if update else lane
        can_refresh, _why = excel_available(self.settings)
        if can_refresh:
            return Reply(
                f"{head}{warn}\n\nRefreshing {ticker} in Excel now — a minute "
                f"while the add-in resolves. The {name} prompt follows when the "
                f"numbers are in.")
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

    # ---------------------------------------------------------------- /new
    def new_ticker(self, chat_id: int, ticker: str) -> Reply:
        """Deprecated: kept for one release as an alias.

        It cannot know the lane, so it does what it always did — prepares both
        prompts — and points at the replacement.
        """
        ticker = ticker.strip().upper()
        if not ticker or not ticker.replace(".", "").replace("-", "").isalnum():
            return Reply("Usage: /short TICKER  or  /long TICKER")
        ws = Workspace(self.settings, ticker, today_str()).create()
        self.context.set(chat_id, ticker, ws.workdate)
        # On the Windows box with Excel + the add-in the bot refreshes the
        # numbers itself; the template only goes out when it can't (P3.1b).
        can_refresh, _why = excel_available(self.settings)
        if can_refresh:
            return Reply(
                f"📁 Workspace ready: {ticker} / {ws.workdate}\n\n"
                f"Refreshing {ticker} in Excel now — this takes a minute while "
                f"the add-in resolves. I'll send the prompts when the numbers "
                f"are in. (Upload a workbook yourself any time to override, or "
                f"/refresh {ticker} to try again.)"
            )
        template = self.settings.templates_dir / "dennis_data_template.xlsx"
        return Reply(
            f"📁 Workspace ready: {ticker} / {ws.workdate}\n\n"
            f"1. Refresh the attached data template for {ticker} in Excel "
            f"(both sheets — Latest and the 5-year History), save, and upload "
            f"it here as dennis_data.xlsx (CSV accepted, snapshot only).\n"
            f"2. I'll reply with the pre-filled master prompts. For a LONG, "
            f"once you pick an angle I auto-pull the relevant 10-K excerpts "
            f"and snap them for [SHOW FILING] — no screenshot uploads needed "
            f"(they carry a generic 'from the 10-K' label; the source stays "
            f"unnamed).",
            files=[template] if template.exists() else [],
        )

    # ------------------------------------------------------------ /refresh
    def refresh_data(self, chat_id: int, args: list[str]) -> Reply:
        """Refresh this ticker's workbook in Excel and hand back the prompts.

        Blocking — the add-in takes tens of seconds — so callers run it off
        the event loop. A failure here is loud and changes nothing: whatever
        workbook the workspace already had is still the workbook it has, and
        the manual upload is still open.
        """
        ticker = args[0].strip().upper() if args else ""
        symbol = args[1].strip() if len(args) > 1 else None

        if ticker:
            ws = Workspace(self.settings, ticker, today_str()).create()
            self.context.set(chat_id, ticker, ws.workdate)
        else:
            ws = self._active_ws(chat_id)
            if ws is None:
                return Reply("Usage: /refresh TICKER [VENDOR_SYMBOL] "
                             "— or /short TICKER first.")
            ticker = ws.ticker

        ok, why = excel_available(self.settings)
        if not ok:
            template = self.settings.templates_dir / "dennis_data_template.xlsx"
            return Reply(
                f"⛔ Can't drive Excel here: {why}\n"
                f"Refresh the attached template for {ticker} by hand and upload "
                f"it — that path is unchanged.",
                files=[template] if template.exists() else [],
            )

        if symbol:
            # An explicit vendor symbol is worth remembering: the ticker→RIC
            # mapping is an entitlement question the bot can't answer itself.
            set_symbol_override(self.settings, ticker, symbol)

        try:
            result = refresh_for_ticker(self.settings, ticker, ws.path,
                                        symbol=symbol)
        except ExcelUnavailable as e:
            return Reply(f"⛔ Excel is not usable: {e}\n"
                         f"The manual upload still works.")
        except RefreshTimeout as e:
            return Reply(
                f"⛔ {ticker}: {e}\n"
                f"Nothing was saved — a half-refreshed workbook is worse than "
                f"none. Check the add-in is signed in, then /refresh {ticker} "
                f"again. If the symbol is wrong for the add-in, pin it: "
                f"/refresh {ticker} {ticker}.O")
        except RefreshError as e:
            return Reply(f"⛔ {ticker}: refresh failed — {e}\n"
                         f"Nothing was saved; upload a workbook to proceed.")
        except Exception as e:  # noqa: BLE001 - COM raises anything
            log.exception("excel refresh blew up")
            return Reply(f"💥 {ticker}: Excel refresh error — {e}\n"
                         f"The manual upload still works.")

        # New numbers invalidate an approval. The approval pins the script's
        # hash, which does not change when the data underneath it does — so
        # without this, approve → refresh → render would ship figures the
        # operator never saw in the cost + fact-check report.
        withdrawn = [fmt for fmt in ("short", "long") if ws.is_approved(fmt)]
        for fmt in withdrawn:
            ws._invalidate_approval(fmt)

        reply = self.prompts_reply(chat_id)
        reply.text = f"{result.summary()}\n\n{reply.text}"
        if withdrawn:
            reply.text += (
                f"\n\n⚠️ the {'/'.join(withdrawn)} approval was withdrawn — "
                f"these are different numbers than the report you approved. "
                f"Re-read the report and Approve again.")
        reply.files = list(reply.files) + [result.archive]
        return reply

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
        from pipeline.screener import last_screen_context

        move_context = last_screen_context(self.settings, ws.ticker)
        # One lane, one prompt (1d). A workspace opened by the deprecated
        # /new has no lane, so it still gets both — that is the alias's whole
        # job for the release it survives.
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
        if "long_angle" in wanted:
            ws.set_awaiting_angle()
        warn = ""
        if not data.has_history:
            warn += ("\n⚠️ no History sheet — the multi-year gut check will "
                     "have nothing to show; re-export with both sheets")
        if data.warning_missing:
            warn += f"\n⚠️ optional fields missing: {', '.join(data.warning_missing[:6])}"
        # When the bot refreshed the numbers itself, say how old they really
        # are — the sheet's =TODAY() only records the last recalculation.
        age = refresh_age_days(ws.path)
        if age is not None:
            warn += (f"\n🕒 numbers refreshed "
                     + ("just now" if age < 0.02 else
                        f"{age * 24:.0f}h ago" if age < 1 else f"{age:.1f} days ago"))
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
            lines.append("(/new is deprecated — /short TICKER or /long TICKER "
                         "prepares just the one prompt.)")
        return Reply("\n".join(lines) + warn, files=files)

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
        ws.clear_awaiting_angle()  # a headline short is never in the LONG angle flow
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
                # a Claude Design export ([ASSET]) or an operator capture
                # ([SCREENGRAB]) — into the shared custom library, where
                # pre-render validation looks for it
                custom = self.settings.assets_dir / "custom"
                custom.mkdir(parents=True, exist_ok=True)
                (custom / f"{stem}{suffix}").write_bytes(data)
                remaining = [s for s in self._pending_custom_slugs(ws) if s != stem]
                kind = "screengrab" if pending[stem] == "screengrab" else "custom asset"
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
            return self.intake_script(chat_id, data.decode("utf-8", errors="replace"))

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
        for kind, slugs in (("asset", script.asset_slugs()),
                            ("screengrab", script.screengrab_slugs())):
            for slug in slugs:
                if not (custom.is_dir() and list(custom.glob(f"{slug}.*"))):
                    out[slug] = kind
        return out

    # ------------------------------------------------------- script intake
    @staticmethod
    def _looks_like_script(text: str) -> bool:
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

    def intake_script(self, chat_id: int, text: str) -> Reply:
        ws = self._active_ws(chat_id)
        if ws is None:
            return Reply("No active workspace — /short TICKER or /long TICKER first.")
        # LONG two-step: a plain-text reply while awaiting the angle pick is
        # the operator's angle choice, not a script — hand back Step 2.
        if ws.awaiting_angle() and text.strip() and not self._looks_like_script(text):
            return self._intake_angle(ws, text)
        stripped = text.lstrip()
        looks_short = stripped.startswith("{") or '"format"' in text or "```" in text
        if looks_short:
            try:
                return self._intake_short(ws, text)
            except ScriptParseError as e:
                # a fenced LONG narration could false-positive; try long too
                if "[" in text and "]" in text:
                    try:
                        return self._intake_long(ws, text)
                    except LongScriptError:
                        pass
                return Reply(f"⛔ SHORT script rejected:\n{e}")
        try:
            return self._intake_long(ws, text)
        except LongScriptError as e:
            return Reply(f"⛔ LONG script rejected:\n{e}")

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
                    mode: str = "lines") -> Reply:
        """Apply a targeted edit, then re-run the whole intake on the result.

        The revision is only stored if it parses, so an edit can never leave
        the workspace holding a script the renderer would choke on. Because it
        goes back through the ordinary intake, the gates re-run and a fresh
        cost report comes back — and saving invalidates the approval, so the
        approval stays pinned to the version actually read.
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
                result = replace_text(raw, " ".join(args))
            else:
                if not args:
                    raise EditError(
                        "Usage: `/edit N new text` · `/edit N-M new text` · "
                        "`/edit N` to delete. `/script` shows the numbers.")
                result = edit_lines(raw, args[0], " ".join(args[1:]))
        except EditError as e:
            return Reply(f"⛔ {e}")

        return self._revise(ws, fmt, raw, result.text,
                            note=f"✏️ {result.summary}",
                            diff=diff_lines(raw, result.text))

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
        reply = self._revise(ws, fmt, current, previous,
                             note="↩️ reverted to the previous revision",
                             diff=diff_lines(current, previous))
        # `_revise` saved, which pushed `current` onto the stack; drop it so a
        # second /undo goes further back rather than toggling between two.
        ws.pop_revision(fmt)
        return reply

    def _revise(self, ws: Workspace, fmt: str, before: str, after: str,
                *, note: str, diff: str = "") -> Reply:
        """Validate a candidate script and, only if it holds up, store it.

        On rejection the workspace keeps `before` untouched: the operator gets
        the parser's complaint and can try again, with nothing lost.
        """
        try:
            reply = (self._intake_short(ws, after) if fmt == "short"
                     else self._intake_long(ws, after))
        except (ScriptParseError, LongScriptError) as e:
            return Reply(
                f"⛔ that edit doesn't parse, so I've left the script alone:\n{e}"
                f"\n\nThe script is unchanged — /script to see it.")
        head = note
        if diff:
            head += f"\n```\n{diff}\n```"
        reply.text = f"{head}\n\n{reply.text}"
        return reply

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
            return Reply("⛔ No data export on file — upload dennis_data.xlsx first.")
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

    def veto_filing(self, chat_id: int, ticker: str, workdate: str, name: str) -> Reply:
        """Operator dropped an auto-pulled filing crop — remove it and re-send
        the writing prompt (regenerated without that shot)."""
        from pipeline.filings import veto_shot

        ws = Workspace(self.settings, ticker, workdate)
        self.context.set(chat_id, ticker, workdate)
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
        font = load_font(self.settings, "DejaVuSansMono-Bold.ttf", 16)
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
        report = build_short_report(script, warnings, self.settings, self.ledger, self.tts)
        (ws.path / "report_short.txt").write_text(report.render_text(), encoding="utf-8")
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
        prompt_files = self._save_asset_prompts(ws, script)
        plan = self.content.plan(script, company_data=data,
                                 overrides=ws.broll_overrides())
        filing_count = len({e.payload for e in script.events_of(TagType.SHOW_FILING)})
        report = build_long_report(
            script, warnings, v_warnings, v_blocking,
            self.settings, self.ledger, self.tts, plan, filing_count,
        )
        (ws.path / "report_long.txt").write_text(report.render_text(), encoding="utf-8")
        sheet = self._contact_sheet(ws, plan)
        return Reply(
            report.render_text(),
            keyboard=approval_keyboard("long", ws.ticker, ws.workdate,
                                       report.script_sha, report.approvable, bool(plan)),
            photo=sheet,
            files=prompt_files,
        )

    def _save_asset_prompts(self, ws: Workspace, script) -> list[Path]:
        """Persist appended Claude Design prompts as paste-ready .txt files
        the operator receives with the report."""
        out: list[Path] = []
        if not script.asset_prompts:
            return out
        pdir = ws.path / "asset_prompts"
        pdir.mkdir(exist_ok=True)
        for slug, prompt in script.asset_prompts.items():
            f = pdir / f"{slug}.claude-design.txt"
            f.write_text(prompt + "\n", encoding="utf-8")
            out.append(f)
        return out

    @staticmethod
    def _long_clip_keys(script) -> list[str]:
        seen: list[str] = []
        for e in script.events_of(TagType.CLIP, TagType.BROLL):
            if e.payload not in seen:
                seen.append(e.payload)
        return seen

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
        font = load_font(self.settings, "DejaVuSansMono-Bold.ttf", 18)
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
        report_file = ws.path / f"report_{fmt}.txt"
        ws.approve(fmt, script.content_sha(),
                   report_file.read_text(encoding="utf-8") if report_file.exists() else "")
        cmd = "/render" if fmt == "short" else "/render_long"
        return Reply(
            f"✅ {ticker} {fmt.upper()} approved (script {sha8}).\n"
            f"{cmd} {ticker} to render — this is the point where money is spent."
            + ("\nTip: /draft first for a cheap timing check." if fmt == "long" else "")
        )

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
        keys = self._long_clip_keys(script)
        if not keys:
            return Reply("This LONG has no [CLIP] tags to swap.")
        return Reply(
            "Pick the clip key to swap to its next take "
            "(approval resets after a swap):",
            keyboard=swap_keyboard(ticker, workdate, keys),
        )

    def swap_key(self, chat_id: int, ticker: str, workdate: str, key: str) -> Reply:
        ws = Workspace(self.settings, ticker, workdate)
        script = ws.load_long()
        if script is None:
            return Reply("No LONG script on file.")
        current = ws.broll_overrides().get(key, 0)
        n = self.content.alternates_count(key)
        ws.set_broll_override(key, (current + 1) % max(n, 1))
        raw = (ws.path / "script_long.raw.txt").read_text(encoding="utf-8")
        self.context.set(chat_id, ticker, workdate)
        reply = self.intake_script(chat_id, raw)  # rebuild report + sheet
        reply.text = f"🔄 {key}: take {(current + 1) % max(n, 1) + 1}/{max(n, 1)}\n\n" + reply.text
        return reply

    # ------------------------------------------------------------- renders
    def render_request(self, ticker: str, fmt: str | None = None,
                       draft: bool = False, proof: bool = False,
                       ) -> tuple[JobKind | None, str, Workspace | None]:
        """Queue a render. `fmt=None` takes the format from the workspace's lane.

        Since /short and /long declare the format up front (1d), plain /render
        follows from it rather than making the operator pick twice.
        """
        ws = self._ws_or_error(ticker)
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
                "mock": "⚠ mock hum — Piper is not installed on this box, so "
                        "you get real pictures over a placeholder tone",
            }.get(tier, tier)
            kind = (JobKind.RENDER_PROOF_SHORT if fmt == "short"
                    else JobKind.RENDER_PROOF_LONG)
            return kind, (
                f"🖼 queued FULL-RES PROOF for {ticker} {fmt.upper()}\n"
                f"📺 real visuals — live prices, Pexels, Wikimedia, memes, "
                f"filings and charts, exactly as a final\n"
                f"🎧 {voice}\n"
                f"💵 $0, enforced in code — this job cannot reach the paid "
                f"voice\n"
                f"⏱ cue times shift slightly when the paid voice lands: the "
                f"draft clock is exact per sentence, interpolated inside one"
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
                "mock": "mock hum — the local voice isn't installed, so this "
                        "checks timing only",
            }.get(tier, tier)
            return JobKind.RENDER_DRAFT_LONG, (
                f"🎬 queued LOW-RES DRAFT for {ticker}\n🎧 {note}. $0 either "
                f"way; the final still needs the paid voice."), ws
        if not ws.is_approved(fmt):
            return None, (
                f"⛔ {ticker} {fmt.upper()} is not approved (or the script changed "
                f"after approval). Paste the script and tap Approve first — the "
                f"approval gate is the spend gate."
            ), None
        kind = JobKind.RENDER_SHORT if fmt == "short" else JobKind.RENDER_LONG
        return kind, f"🎬 queued {fmt.upper()} render for {ticker}", ws

    def repurpose_request(self, ticker: str) -> tuple[JobKind | None, str, Workspace | None]:
        """SHORT-from-LONG: free (no TTS, no fetches), so no approval gate."""
        ws = self._ws_or_error(ticker)
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
        store = self.queue.store if self.queue else None

        def checkpoint(detail: str) -> None:
            if store:
                fresh = store.load(job.id)
                if fresh and fresh.status.value == "cancelled":
                    raise JobCancelled()
                if fresh:
                    fresh.detail = detail
                    store.save(fresh)

        if job.kind in (JobKind.RENDER_PROOF_SHORT, JobKind.RENDER_PROOF_LONG):
            return self._run_proof(job, ws, checkpoint)

        if job.kind is JobKind.RENDER_SHORT:
            script = ws.load_short()
            if script is None or not ws.is_approved("short"):
                raise RuntimeError("script/approval vanished before render")
            checkpoint("tts")
            tts = self.tts.synthesize(script.audio_script, "short",
                                      events=script.inline_events)
            checkpoint("render")
            out, manifest = render_short(script, tts, ws.path, self.settings,
                                         content=self.content)
            checkpoint("delivery")
            result = deliver(out, job.ticker, job.workdate, self.settings)
            self._finish(job, result)
            return str(out)

        if job.kind in (JobKind.RENDER_LONG, JobKind.RENDER_DRAFT_LONG):
            draft = job.kind is JobKind.RENDER_DRAFT_LONG
            script = ws.load_long()
            if script is None:
                raise RuntimeError("script vanished before render")
            if not draft and not ws.is_approved("long"):
                raise RuntimeError("approval vanished before render")
            checkpoint("tts")
            # A draft asks for the free tier (P3.2): the local neural voice if
            # the box has one, the mock hum otherwise. Never ElevenLabs — the
            # whole point of a draft is to iterate on pacing without spending.
            tts = self.tts.synthesize(script.narration, "long",
                                      events=script.events, draft=draft)
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
                job.delivered_link = f"file://{out}"
                return str(out)
            checkpoint("delivery")
            import json as _json
            attributions = _json.loads(Path(manifest).read_text(encoding="utf-8")).get("attributions", [])
            extra: list[Path] = []
            try:  # LONG gets an auto thumbnail
                from pipeline.thumbnail import make_thumbnail
                thumb = make_thumbnail(script, ws, self.settings)
                if thumb:
                    extra.append(thumb)
            except ImportError:
                pass
            # Free by-products of a finished render: subtitles straight off
            # the master clock (so they match the burned-in captions exactly)
            # and the upload package. Best-effort — neither is worth losing a
            # completed render over.
            try:
                from pipeline.publish import build_package, write_srt

                extra.append(write_srt(tts.words, ws.path / f"{job.ticker}.srt"))
                pkg = build_package(script, self.settings, ticker=job.ticker,
                                    runtime_min=tts.duration_s / 60.0)
                pkg_path = ws.path / "upload_package.txt"
                pkg_path.write_text(pkg.render_text(), encoding="utf-8")
                extra.append(pkg_path)
            except Exception:  # noqa: BLE001
                log.exception("publishing by-products failed — delivering anyway")
            # The rest of the kit's by-products (P3.6): eight thumbnail
            # layouts, the social cards, the end screens. All free — same data,
            # artwork already drawn — and the alternative is making them by
            # hand at midnight.
            if self.settings.byproducts_enabled:
                try:
                    from pipeline.byproducts import build_byproducts

                    made = build_byproducts(ws.path, self.settings,
                                            ticker=job.ticker, script=script,
                                            data=data)
                    checkpoint(f"by-products: {made.total()} assets")
                except Exception:  # noqa: BLE001 - never lose a finished render
                    log.exception("by-products failed — delivering anyway")
            result = deliver(out, job.ticker, job.workdate, self.settings,
                             attributions=attributions, extra_files=extra)
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
            if script and self.tts.is_cached(script.narration, "long",
                                             events=script.events):
                words = self.tts.synthesize(script.narration, "long",
                                            events=script.events).words  # cache hit
            checkpoint("repurpose")
            # A forty-minute cut has more than one good minute in it (P3.3).
            clips = repurpose_clips_from_long(
                long_mp4, manifest, self.settings,
                n=self.settings.repurpose_clips, words=words,
            )
            if not clips:
                raise RuntimeError("no usable window in the finished LONG")
            checkpoint("delivery")
            import json as _json
            attributions = _json.loads(manifest.read_text(encoding="utf-8")).get("attributions", [])
            result = ""
            for i, (path, _info) in enumerate(clips, 1):
                checkpoint(f"delivery {i}/{len(clips)}")
                result = deliver(path, job.ticker, job.workdate, self.settings,
                                 attributions=attributions)
            self._finish(job, result)
            return str(clips[0][0])

        raise RuntimeError(f"unknown job kind {job.kind}")

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
            out, _ = render_short(script, tts, ws.path, self.settings,
                                  content=self.content, proof=True)
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
        job.delivered_link = f"file://{out}"
        self.push_file(Path(out), (
            f"{job.ticker} — {'SHORT' if short else 'LONG'} PROOF, full "
            f"resolution, {tts.tier} voice, $0. Cue times move slightly under "
            f"the paid voice."))
        return str(out)

    def _send_storyboard(self, job: JobRecord, script, tts, ws, data) -> None:
        """Contact sheet of the planned cut, pushed before the encode starts.

        Best-effort by design: a storyboard that fails to build must never
        stop a render the operator has already approved.
        """
        try:
            from pipeline.storyboard import build_storyboard
            from pipeline.timeline import (
                build_long_timeline, chapter_start_times, plan_long_segments,
            )

            cues = build_long_timeline(script, tts.words, tts.duration_s)
            segments, _ = plan_long_segments(
                cues, tts.duration_s,
                chapter_starts=chapter_start_times(script.chapters, tts.duration_s),
                min_readable_s=self.settings.long_min_readable_s,
                chapter_host_s=self.settings.long_chapter_host_s,
            )
            sheet, problems = build_storyboard(
                segments, tts.words, ws.path / "storyboard.png", self.settings,
                content=self.content, ticker=job.ticker, company_data=data,
                workspace=ws.path, title=f"{job.ticker} — LONG",
            )
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
        caption = f"{job.ticker} — storyboard, {len(segments)} beats"
        if problems:
            caption += "\n⚠ " + "\n⚠ ".join(problems[:6])
        self.push_file(sheet, caption)

    def push_file(self, path: Path, caption: str = "") -> None:
        """Send a file to the operator from a worker thread.

        `file_pusher` is wired by main.py against the bot's event loop; when
        it is absent (tests, CLI) the path is logged instead, which is all a
        local run needs.
        """
        if self.file_pusher is None:
            log.info("%s%s", caption + "\n" if caption else "", path)
            return
        try:
            self.file_pusher(path, caption)
        except Exception:  # noqa: BLE001
            log.exception("could not push %s to the operator", path)

    def _finish(self, job: JobRecord, result) -> None:
        job.delivered_link = result.link
        if self.queue:
            fresh = self.queue.store.load(job.id)
            if fresh:
                fresh.delivered_link = result.link
                fresh.detail = f"delivered via {result.backend}"
                self.queue.store.save(fresh)
        self._record_thesis(job)

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
        except Exception as e:  # noqa: BLE001 - never fail a shipped video
            log.warning("thesis bookkeeping failed for %s: %s", job.ticker, e)

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
        ws = Workspace.latest_for(self.settings, ticker)
        data = self._company_data(ws) if ws else None
        if data is None:
            return Reply(f"📌 {ticker}: {th.summary}\n"
                         f"(no current data to check it against — /refresh {ticker})")
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
        ticker = head.upper()
        fmt = (args[1].lower() if len(args) > 1 else "")
        if fmt not in ("short", "long"):
            ws = Workspace.latest_for(self.settings, ticker)
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
        for item in pending:
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

    # --------------------------------- YouTube publishing (P3.5 + 5b)
    def upload_command(self, args: list[str]) -> Reply:
        """`/upload TICKER [YYYY-MM-DD HH:MM]` — private, or scheduled.

        Never public: the most this does unattended is schedule, and a human
        still decides whether that schedule was right.
        """
        from pipeline.youtube import (
            UploadError, YouTubeUnavailable, available, resolve_publish_at,
            upload_video,
        )

        if not args:
            return Reply("Usage: /upload TICKER [YYYY-MM-DD HH:MM]\n"
                         "No time = private. A time = scheduled publish.")
        ticker = args[0].upper()
        when_raw = " ".join(args[1:]).strip()
        try:
            when = resolve_publish_at(when_raw or None)
        except ValueError as e:
            return Reply(f"⛔ {e}")

        ws = Workspace.latest_for(self.settings, ticker)
        if ws is None:
            return Reply(f"No workspace for {ticker}.")
        fmt = ws.current_format() or "long"
        video = ws.path / ("long_final.mp4" if fmt == "long" else "short_final.mp4")
        if not video.exists():
            return Reply(f"No finished {fmt.upper()} render for {ticker} yet.")

        pkg_path = ws.path / "upload_package.txt"
        package = self._upload_package(ws, fmt)
        if package is None:
            return Reply("⛔ no upload package on file — re-render to build one.")

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
                chapters=self._chapter_pairs(ws, fmt),
                duration_s=self._render_duration(ws, fmt))
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
        return Reply(f"📺 {ticker}: {tail}\n{record.url()}")

    def scheduled_text(self) -> Reply:
        from pipeline.youtube import VideoLog

        rows = VideoLog(self.settings).scheduled()
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
                             "of views first).")
            lines = ["📊 Which chapter types hold attention (all videos)"]
            for row in evidence[:12]:
                lines.append(f"  {row['avg_watch_ratio'] * 100:5.1f}%  "
                             f"{row['chapter'][:40]}  (n={row['videos']})")
            lines.append("\nWorst first. One video is an anecdote; the same "
                         "chapter type dropping across several is evidence.")
            return Reply("\n".join(lines))

        ticker = args[0].upper()
        videos = log_.for_ticker(ticker)
        if not videos:
            return Reply(f"Nothing published for {ticker} yet.")
        video = videos[-1]
        payload = pull_retention(video.video_id, self.settings)
        if payload.get("status") != "ok":
            stored = (video.retention or {}).get("chapters")
            if stored:
                return Reply(f"({payload.get('reason', 'live pull unavailable')})"
                             f"\n\n{retention_report(stored)}")
            return Reply(f"📊 {ticker}: {payload.get('reason', payload['status'])}")
        return Reply(f"📊 {ticker} — {video.title[:60]}\n"
                     + retention_report(payload["chapters"]))

    def _upload_package(self, ws: Workspace, fmt: str):
        from pipeline.cost import build_long_report  # noqa: F401  (import guard)
        from pipeline.publish import build_package

        script = ws.load_long() if fmt == "long" else ws.load_short()
        if script is None:
            return None
        return build_package(script, self.settings, ticker=ws.ticker,
                             runtime_min=self._render_duration(ws, fmt) / 60.0)

    def _chapter_pairs(self, ws: Workspace, fmt: str) -> list:
        from pipeline.publish import normalise_chapters

        script = ws.load_long() if fmt == "long" else None
        return normalise_chapters(getattr(script, "chapters", "") or "")

    def _render_duration(self, ws: Workspace, fmt: str) -> float:
        name = ("render_long_manifest.json" if fmt == "long"
                else "render_short_manifest.json")
        try:
            import json as _json
            return float(_json.loads((ws.path / name).read_text(encoding="utf-8")).get("duration", 0))
        except (FileNotFoundError, ValueError, KeyError, OSError):
            return 0.0

    # ------------------------------------------ intraday alerting (3b)
    def watch_command(self, args: list[str]) -> Reply:
        """What gets watched intraday, and when the watched names report."""
        from pipeline.alerts import EarningsCalendar, Watchlist, in_quiet_hours

        wl = Watchlist(self.settings)
        if args:
            head = args[0].lower()
            if head in ("drop", "remove", "off") and len(args) > 1:
                ticker = args[1].upper()
                gone = wl.remove(ticker)
                return Reply(f"👁 {'unpinned' if gone else 'was not pinned'}: {ticker}"
                             f"\n(names with a thesis on file are always watched.)")
            ticker = head.upper()
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

    def poll_alerts(self) -> list:
        """One alert pass. Sync, so the scheduler and tests share a path."""
        from pipeline.alerts import (
            Watchlist, fetch_filings, fetch_quotes, poll_once,
        )

        tickers = Watchlist(self.settings).all()
        quotes = fetch_quotes(self.settings, tickers)
        filings = fetch_filings(self.settings, tickers)
        return poll_once(self.settings, quotes=quotes, filings=filings)

    # ----------------------------------------------------------- utilities
    def cost_text(self) -> str:
        return (
            f"💰 Month-to-date: ${self.ledger.mtd_spend_usd():.2f} of "
            f"${self.settings.monthly_spend_cap_usd:.2f} cap\n"
            f"Pexels calls: {self.ledger.pexels_calls_this_month()} of "
            f"{self.settings.pexels_monthly_call_cap}\n"
            f"Filing-flagger LLM: ${self.ledger.llm_usd_this_month():.2f}\n"
            f"Mode: {'MOCK (no paid calls possible)' if self.settings.mock_mode else 'LIVE'}\n"
            + self._mock_status_line()
        )

    def _mock_status_line(self) -> str:
        """Which subsystems are fake, spelled out — never just "mock mode".

        Three of them can be mocked independently now, and a run with real
        prices and a placeholder voice looks identical to a run with neither
        unless something says so.
        """
        s = self.settings
        rows = [f"{name}: {'MOCK' if on else 'live'}" for name, on in (
            ("TTS", s.mocking_tts), ("Prices", s.mocking_prices),
            ("Screener", s.mocking_screener))]
        banner = s.mock_banner()
        return "  ·  ".join(rows) + (f"\n{banner}" if banner else "")


# ---------------------------------------------------------------------------
# PTB glue: thin async wrappers around BotCore.
# ---------------------------------------------------------------------------


def _authorized(core: BotCore, chat_id: int) -> bool:
    ids = core.settings.operator_chat_ids
    return bool(ids) and chat_id in ids


async def _send(update, reply: Reply) -> None:
    msg = update.effective_message
    text = reply.text
    while text:  # Telegram 4096-char message cap
        chunk, text = text[:4000], text[4000:]
        await msg.reply_text(chunk, reply_markup=reply.keyboard if not text else None)
    if reply.photo is not None:
        with open(reply.photo, "rb") as f:
            await msg.reply_photo(f)
    for path in reply.files:
        with open(path, "rb") as f:
            await msg.reply_document(f, filename=path.name)


def build_application(settings: Settings, core: BotCore):
    """Wire PTB. Import here so BotCore stays importable without a token."""
    from telegram import Update
    from telegram.ext import (
        Application,
        CallbackQueryHandler,
        CommandHandler,
        ContextTypes,
        MessageHandler,
        filters,
    )

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

    @guard
    async def cmd_start(update, ctx):
        await _send(update, Reply(HELP_TEXT))

    async def _run_refresh(update, args: list[str]) -> None:
        """The Excel refresh blocks for tens of seconds — off the loop it goes,
        or the bot stops answering while the add-in thinks."""
        import asyncio
        reply = await asyncio.to_thread(
            core.refresh_data, update.effective_chat.id, args)
        await _send(update, reply)

    async def _start_lane(update, lane: str, args: list[str], *,
                          is_update: bool = False) -> None:
        ticker = args[0] if args else ""
        await _send(update, core.start_lane(update.effective_chat.id, lane,
                                            ticker, update=is_update))
        # The refresh follows immediately — the manual data step is what P3.1b
        # removes, and the lane's prompt comes back with the numbers.
        if ticker and excel_available(core.settings)[0]:
            await _run_refresh(update, [ticker])

    @guard
    async def cmd_short(update, ctx):
        await _start_lane(update, "short", list(ctx.args or []))

    @guard
    async def cmd_long(update, ctx):
        await _start_lane(update, "long", list(ctx.args or []))

    @guard
    async def cmd_update(update, ctx):
        """Dennis grading his own call. Explicit, never inferred from /long —
        whether this is an update or a fresh take is the operator's call."""
        await _start_lane(update, "long", list(ctx.args or []), is_update=True)

    @guard
    async def cmd_new(update, ctx):
        ticker = ctx.args[0] if ctx.args else ""
        await _send(update, core.new_ticker(update.effective_chat.id, ticker))
        if ticker and excel_available(core.settings)[0]:
            await _run_refresh(update, [ticker])

    @guard
    async def cmd_refresh(update, ctx):
        if not (ctx.args or core.context.get(update.effective_chat.id)):
            await _send(update, Reply("Usage: /refresh TICKER [VENDOR_SYMBOL]"))
            return
        if excel_available(core.settings)[0]:
            await _send(update, Reply(
                "🔄 Refreshing in Excel — waiting for the add-in to resolve…"))
        await _run_refresh(update, list(ctx.args or []))

    @guard
    async def cmd_headline(update, ctx):
        await _send(update, core.headline_command(update.effective_chat.id, ctx.args or []))

    @guard
    async def cmd_prompts(update, ctx):
        await _send(update, core.prompts_reply(update.effective_chat.id))

    @guard
    async def cmd_render(update, ctx, fmt: str | None = None, draft: bool = False):
        """Plain /render follows the workspace's lane (1d)."""
        if not ctx.args:
            await _send(update, Reply("Usage: /render TICKER"))
            return
        kind, text, ws = core.render_request(ctx.args[0].upper(), fmt, draft)
        if kind is None or ws is None:
            await _send(update, Reply(text))
            return
        try:
            await core.queue.submit(kind, ws.ticker, ws.workdate)
        except ValueError as e:
            text = f"⛔ {e}"
        await _send(update, Reply(text))

    @guard
    async def cmd_render_long_impl(update, ctx):
        if not ctx.args:
            await _send(update, Reply("Usage: /render_long TICKER"))
            return
        kind, text, ws = core.render_request(ctx.args[0].upper(), "long", False)
        if kind is None or ws is None:
            await _send(update, Reply(text))
            return
        try:
            await core.queue.submit(kind, ws.ticker, ws.workdate)
        except ValueError as e:
            text = f"⛔ {e}"
        await _send(update, Reply(text))

    @guard
    async def cmd_draft(update, ctx):
        if not ctx.args:
            await _send(update, Reply("Usage: /draft TICKER"))
            return
        kind, text, ws = core.render_request(ctx.args[0].upper(), "long", True)
        if kind is None or ws is None:
            await _send(update, Reply(text))
            return
        try:
            await core.queue.submit(kind, ws.ticker, ws.workdate)
        except ValueError as e:
            text = f"⛔ {e}"
        await _send(update, Reply(text))

    @guard
    async def cmd_proof(update, ctx):
        """Full-res, real visuals, free voice, $0 — for BOTH formats.

        `/proof TICKER` follows the workspace's lane; `/proof TICKER short`
        or `/proof TICKER long` picks one. Unlike /render there is no
        approval gate, because approval gates spend and this cannot spend.
        """
        if not ctx.args:
            await _send(update, Reply("Usage: /proof TICKER [short|long]"))
            return
        fmt = None
        if len(ctx.args) > 1 and ctx.args[1].lower() in ("short", "long"):
            fmt = ctx.args[1].lower()
        kind, text, ws = core.render_request(ctx.args[0].upper(), fmt,
                                             draft=False, proof=True)
        if kind is None or ws is None:
            await _send(update, Reply(text))
            return
        try:
            await core.queue.submit(kind, ws.ticker, ws.workdate)
        except ValueError as e:
            text = f"⛔ {e}"
        await _send(update, Reply(text))

    @guard
    async def cmd_repurpose(update, ctx):
        if not ctx.args:
            await _send(update, Reply("Usage: /repurpose TICKER"))
            return
        kind, text, ws = core.repurpose_request(ctx.args[0].upper())
        if kind is None or ws is None:
            await _send(update, Reply(text))
            return
        try:
            await core.queue.submit(kind, ws.ticker, ws.workdate)
        except ValueError as e:
            text = f"⛔ {e}"
        await _send(update, Reply(text))

    @guard
    async def cmd_script(update, ctx):
        await _send(update, core.script_listing(update.effective_chat.id))

    @guard
    async def cmd_edit(update, ctx):
        await _send(update, core.edit_script(update.effective_chat.id,
                                            list(ctx.args or [])))

    @guard
    async def cmd_replace(update, ctx):
        await _send(update, core.edit_script(update.effective_chat.id,
                                            list(ctx.args or []),
                                            mode="replace"))

    @guard
    async def cmd_undo(update, ctx):
        await _send(update, core.undo_edit(update.effective_chat.id))

    @guard
    async def cmd_upload(update, ctx):
        import asyncio
        reply = await asyncio.to_thread(core.upload_command, list(ctx.args or []))
        await _send(update, reply)

    @guard
    async def cmd_scheduled(update, ctx):
        await _send(update, core.scheduled_text())

    @guard
    async def cmd_retention(update, ctx):
        import asyncio
        reply = await asyncio.to_thread(core.retention_text, list(ctx.args or []))
        await _send(update, reply)

    @guard
    async def cmd_watch(update, ctx):
        await _send(update, core.watch_command(list(ctx.args or [])))

    @guard
    async def cmd_earnings(update, ctx):
        await _send(update, core.earnings_command(list(ctx.args or [])))

    @guard
    async def cmd_ideas(update, ctx):
        await _send(update, core.queue_text())

    @guard
    async def cmd_idea(update, ctx):
        await _send(update, core.queue_add(list(ctx.args or [])))

    @guard
    async def cmd_unidea(update, ctx):
        await _send(update, core.queue_drop(list(ctx.args or [])))

    @guard
    async def cmd_thesis(update, ctx):
        await _send(update, core.thesis_text(list(ctx.args or [])))

    @guard
    async def cmd_batch(update, ctx):
        args = list(ctx.args or [])
        if args and args[0].lower() == "run":
            submittable, skipped, note = core.batch_plan()
            queued = 0
            for kind, ws, item in submittable:
                try:
                    await core.queue.submit(kind, ws.ticker, ws.workdate)
                    core.batch_done(item.ticker, item.fmt)
                    queued += 1
                except ValueError as e:
                    skipped.append(f"{item.ticker} {item.fmt.upper()}: {e}")
            lines = [f"🌙 batch: {queued} queued, {len(skipped)} skipped"]
            lines += [f"  ⛔ {s}" for s in skipped[:6]]
            if note:
                lines.append(f"  {note}")
            await _send(update, Reply("\n".join(lines)))
            return
        await _send(update, core.batch_text(args))

    @guard
    async def cmd_status(update, ctx):
        await _send(update, Reply(core.queue.status_text()))

    @guard
    async def cmd_cancel(update, ctx):
        if not ctx.args:
            await _send(update, Reply("Usage: /cancel TICKER"))
            return
        ticker = ctx.args[0].upper()
        cancelled = core.queue.cancel(ticker)
        ws = Workspace.latest_for(core.settings, ticker)
        if ws:
            ws._invalidate_approval("short")
            ws._invalidate_approval("long")
        await _send(update, Reply(
            f"🚫 {ticker}: {len(cancelled)} job(s) cancelled, approvals withdrawn."
        ))

    @guard
    async def cmd_cost(update, ctx):
        await _send(update, Reply(core.cost_text()))

    @guard
    async def cmd_kit(update, ctx):
        """`/kit doctor` — what the library cannot answer, and what nothing
        has asked for. The gap list is the input to the next batch of art."""
        from pipeline.gates import kit_doctor_text

        what = (ctx.args[0].lower() if ctx.args else "doctor")
        if what not in ("doctor", "report"):
            await _send(update, Reply("usage: /kit doctor"))
            return
        await _send(update, Reply(kit_doctor_text(core.settings)))

    @guard
    async def cmd_screen(update, ctx):
        from pipeline.screener import screen_reply
        lane = ctx.args[0].lower() if ctx.args else "all"
        reply = await screen_reply(core, lane)
        await _send(update, reply)

    @guard
    async def on_text(update, ctx):
        await _send(update, core.intake_script(
            update.effective_chat.id, update.effective_message.text or ""
        ))

    @guard
    async def on_document(update, ctx):
        doc = update.effective_message.document
        f = await doc.get_file()
        data = bytes(await f.download_as_bytearray())
        await _send(update, core.handle_upload(
            update.effective_chat.id, doc.file_name or "upload.bin", data
        ))

    @guard
    async def on_photo(update, ctx):
        photo = update.effective_message.photo[-1]
        f = await photo.get_file()
        data = bytes(await f.download_as_bytearray())
        name = f"screenshot_{photo.file_unique_id}.png"
        await _send(update, core.handle_upload(update.effective_chat.id, name, data))

    @guard
    async def on_callback(update, ctx):
        q = update.callback_query
        await q.answer()
        parts = (q.data or "").split("|")
        op = parts[0]
        chat_id = update.effective_chat.id
        if op == "a" and len(parts) == 5:
            reply = core.approve(parts[1], parts[2], parts[3], parts[4])
        elif op == "x" and len(parts) == 4:
            reply = core.cancel_approval(parts[1], parts[2], parts[3])
        elif op == "w" and len(parts) == 3:
            reply = core.swap_menu(parts[1], parts[2])
        elif op == "w!" and len(parts) == 3:
            core.context.set(chat_id, parts[1], parts[2])
            raw_file = Workspace(core.settings, parts[1], parts[2]).path / "script_long.raw.txt"
            reply = (core.intake_script(chat_id, raw_file.read_text(encoding="utf-8"))
                     if raw_file.exists() else Reply("No LONG script on file."))
        elif op == "s" and len(parts) == 4:
            reply = core.swap_key(chat_id, parts[1], parts[2], parts[3])
        elif op == "fv" and len(parts) == 4:
            reply = core.veto_filing(chat_id, parts[1], parts[2], parts[3])
        elif op == "n" and len(parts) == 2:
            reply = core.new_ticker(chat_id, parts[1])
        else:
            reply = Reply("Unknown action.")
        await _send(update, reply)

    builder = Application.builder().token(settings.telegram_bot_token)
    if settings.telegram_api_base_url:
        builder = builder.base_url(f"{settings.telegram_api_base_url}/bot")
    app = builder.build()

    app.add_handler(CommandHandler(["start", "help"], cmd_start))
    app.add_handler(CommandHandler("short", cmd_short))
    app.add_handler(CommandHandler("long", cmd_long))
    app.add_handler(CommandHandler("update", cmd_update))
    app.add_handler(CommandHandler("new", cmd_new))     # deprecated alias
    app.add_handler(CommandHandler("refresh", cmd_refresh))
    app.add_handler(CommandHandler("headline", cmd_headline))
    app.add_handler(CommandHandler("prompts", cmd_prompts))
    app.add_handler(CommandHandler("render", cmd_render))
    app.add_handler(CommandHandler("render_long", cmd_render_long_impl))
    app.add_handler(CommandHandler("draft", cmd_draft))
    app.add_handler(CommandHandler("proof", cmd_proof))
    app.add_handler(CommandHandler("repurpose", cmd_repurpose))
    app.add_handler(CommandHandler("upload", cmd_upload))
    app.add_handler(CommandHandler("scheduled", cmd_scheduled))
    app.add_handler(CommandHandler("retention", cmd_retention))
    app.add_handler(CommandHandler("watch", cmd_watch))
    app.add_handler(CommandHandler("earnings", cmd_earnings))
    app.add_handler(CommandHandler("ideas", cmd_ideas))
    app.add_handler(CommandHandler("idea", cmd_idea))
    app.add_handler(CommandHandler("unidea", cmd_unidea))
    app.add_handler(CommandHandler("thesis", cmd_thesis))
    app.add_handler(CommandHandler("batch", cmd_batch))
    app.add_handler(CommandHandler("script", cmd_script))
    app.add_handler(CommandHandler("edit", cmd_edit))
    app.add_handler(CommandHandler("replace", cmd_replace))
    app.add_handler(CommandHandler("undo", cmd_undo))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("cost", cmd_cost))
    app.add_handler(CommandHandler("kit", cmd_kit))
    app.add_handler(CommandHandler("screen", cmd_screen))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    return app
