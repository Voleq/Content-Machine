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
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw

from config import Settings
from pipeline.broll import ContentManager, palette_keys
from pipeline.company_data import (
    CompanyDataError,
    list_screenshots,
    load_company_data,
)
from pipeline.cost import (
    SpendLedger,
    build_long_report,
    build_short_report,
)
from pipeline.delivery import deliver
from pipeline.gates import run_gates
from pipeline.jobs import JobCancelled, JobRecord, RenderJobQueue
from pipeline.models import JobKind, TagType
from pipeline.parser_long import LongScriptError, parse_long_script, validate_long_script
from pipeline.parser_short import ScriptParseError, parse_short_script
from pipeline.rasters import load_font
from pipeline.render_long import render_long
from pipeline.render_short import render_short
from pipeline.tts import TTSEngine
from pipeline.workspace import ActiveContext, Workspace, today_str

from bot.keyboards import approval_keyboard, filing_veto_keyboard, swap_keyboard
from bot.prompts import fill_prompt

log = logging.getLogger(__name__)

HELP_TEXT = """Dennis — operator commands

/new TICKER — open today's workspace, get the data template
/headline TICKER <news> — a SHORT about a specific headline (macro: /headline macro <text>)
/prompts — re-send the pre-filled master prompts
/screen [trending|value|all] — ranked candidates (trending → SHORT, value → LONG)
/render TICKER — render the approved SHORT
/render_long TICKER — render the approved LONG
/draft TICKER — cheap low-res LONG timing check (no TTS spend)
/repurpose TICKER — free 9:16 SHORT from the finished LONG
/status — job queue
/cancel TICKER — cancel queued/running jobs + pending approval
/cost — month-to-date spend vs cap
/help — this text

Flow: /new → upload dennis_data.xlsx → run the prompts in Claude/GPT →
(LONG: pick an angle; I auto-pull the 10-K shots) → paste the output back
here → review the validation & cost report → Approve ✅ → /render. Nothing
paid happens before Approve. If a LONG uses [ASSET] tags, paste the appended
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

    # ---------------------------------------------------------------- /new
    def new_ticker(self, chat_id: int, ticker: str) -> Reply:
        ticker = ticker.strip().upper()
        if not ticker or not ticker.replace(".", "").replace("-", "").isalnum():
            return Reply("Usage: /new TICKER")
        ws = Workspace(self.settings, ticker, today_str()).create()
        self.context.set(chat_id, ticker, ws.workdate)
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

    # ------------------------------------------------------------ /prompts
    def prompts_reply(self, chat_id: int) -> Reply:
        ws = self._active_ws(chat_id)
        if ws is None:
            return Reply("No active workspace — start with /new TICKER.")
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
        files = []
        # SHORT is one paste; LONG is now two manual steps in Claude — Step 1
        # (angle) here, Step 2 (write) after the operator replies with a pick.
        for fmt in ("short", "long_angle"):
            text = fill_prompt(fmt, ws.ticker, data, ws.path, self.settings,
                               move_context=move_context)
            f = ws.path / f"prompt_{fmt}.md"
            f.write_text(text)
            files.append(f)
        ws.set_awaiting_angle()
        warn = ""
        if not data.has_history:
            warn += ("\n⚠️ no History sheet — the multi-year gut check will "
                     "have nothing to show; re-export with both sheets")
        if data.warning_missing:
            warn += f"\n⚠️ optional fields missing: {', '.join(data.warning_missing[:6])}"
        return Reply(
            f"📋 Prompts for {ws.ticker} (as of {data.get('as_of_date')}).\n"
            f"• SHORT: run prompt_short.md, paste the output back.\n"
            f"• LONG: run prompt_long_angle.md (Step 1) — it returns ranked "
            f"angles. Reply here with a number (or a tweak) and I'll hand you "
            f"Step 2, the writing prompt.{warn}",
            files=files,
        )

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
        f.write_text(prompt)
        label = {"company": "company-news", "earnings": "earnings",
                 "macro": "macro / market"}.get(mode, mode)
        anchor = "an index chart" if mode == "macro" else "the ticker's multi-year numbers"
        return Reply(
            f"📰 Headline short for {ws.ticker} — {label} framing (anchored on "
            f"{anchor}).\nRun prompt_headline.md in Claude, paste the JSON back "
            f"here, review the cost report, Approve ✅, then /render {ws.ticker}.",
            files=[f],
        )

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
            return Reply("No active workspace — start with /new TICKER, then re-upload.")
        name = Path(filename).name
        suffix = Path(name).suffix.lower()

        if suffix in (".xlsx", ".csv"):
            dest = ws.path / f"dennis_data{suffix}"
            dest.write_bytes(data)
            # a /headline that was waiting on the numbers → hand back the
            # headline prompt now, not the usual short/long_angle pair
            hstate = ws.headline()
            if (hstate.get("mode") in ("company", "earnings")
                    and ws.load_short() is None):
                cdata = self._company_data(ws)
                if cdata is not None:
                    reply = self._headline_prompt_reply(ws, cdata)
                    reply.text = f"💾 saved {dest.name}.\n\n" + reply.text
                    return reply
            reply = self.prompts_reply(chat_id)
            reply.text = f"💾 saved {dest.name} for {ws.ticker}.\n\n" + reply.text
            return reply

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
            return Reply("No active workspace — /new TICKER first.")
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
        f.write_text(prompt)
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
        (ws.path / "report_short.txt").write_text(report.render_text())
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
                          as_of=str((data.get("as_of_date") if data else "") or ""))
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
        (ws.path / "report_long.txt").write_text(report.render_text())
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
            f.write_text(prompt + "\n")
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
                   report_file.read_text() if report_file.exists() else "")
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
        raw = (ws.path / "script_long.raw.txt").read_text()
        self.context.set(chat_id, ticker, workdate)
        reply = self.intake_script(chat_id, raw)  # rebuild report + sheet
        reply.text = f"🔄 {key}: take {(current + 1) % max(n, 1) + 1}/{max(n, 1)}\n\n" + reply.text
        return reply

    # ------------------------------------------------------------- renders
    def render_request(self, ticker: str, fmt: str, draft: bool = False) -> tuple[JobKind | None, str, Workspace | None]:
        ws = self._ws_or_error(ticker)
        if ws is None:
            return None, f"No workspace for {ticker} — /new {ticker} first.", None
        script = ws.load_short() if fmt == "short" else ws.load_long()
        if script is None:
            return None, f"No {fmt.upper()} script for {ticker} — paste it first.", None
        if draft and fmt == "long":
            # a draft's FIRST run triggers the one paid TTS generation, so it
            # sits behind the same approval gate in live mode; in MOCK_MODE
            # (or once audio is cached) it is free
            if (not self.settings.mock_mode
                    and not self.tts.is_cached(script.narration, "long",
                                               events=script.events)
                    and not ws.is_approved("long")):
                return None, (
                    f"⛔ draft for {ticker} would trigger the paid TTS call — "
                    f"approve the LONG report first (the draft then generates "
                    f"the audio once; the final render reuses it)."
                ), None
            return JobKind.RENDER_DRAFT_LONG, f"🎬 queued LOW-RES DRAFT for {ticker}", ws
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
            tts = self.tts.synthesize(script.narration, "long", events=script.events)
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
            attributions = _json.loads(Path(manifest).read_text()).get("attributions", [])
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
            result = deliver(out, job.ticker, job.workdate, self.settings,
                             attributions=attributions, extra_files=extra)
            self._finish(job, result)
            return str(out)

        if job.kind is JobKind.REPURPOSE:
            from pipeline.repurpose import repurpose_short_from_long

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
            out, info = repurpose_short_from_long(
                long_mp4, manifest, self.settings, words=words
            )
            checkpoint("delivery")
            import json as _json
            attributions = _json.loads(manifest.read_text()).get("attributions", [])
            result = deliver(out, job.ticker, job.workdate, self.settings,
                             attributions=attributions)
            self._finish(job, result)
            return str(out)

        raise RuntimeError(f"unknown job kind {job.kind}")

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
        except Exception as e:  # noqa: BLE001
            log.warning("storyboard failed for %s (%s) — rendering anyway",
                        job.ticker, e)
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

    # ----------------------------------------------------------- utilities
    def cost_text(self) -> str:
        return (
            f"💰 Month-to-date: ${self.ledger.mtd_spend_usd():.2f} of "
            f"${self.settings.monthly_spend_cap_usd:.2f} cap\n"
            f"Pexels calls: {self.ledger.pexels_calls_this_month()} of "
            f"{self.settings.pexels_monthly_call_cap}\n"
            f"Filing-flagger LLM: ${self.ledger.llm_usd_this_month():.2f}\n"
            f"Mode: {'MOCK (no paid calls possible)' if self.settings.mock_mode else 'LIVE'}"
        )


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

    @guard
    async def cmd_new(update, ctx):
        ticker = ctx.args[0] if ctx.args else ""
        await _send(update, core.new_ticker(update.effective_chat.id, ticker))

    @guard
    async def cmd_headline(update, ctx):
        await _send(update, core.headline_command(update.effective_chat.id, ctx.args or []))

    @guard
    async def cmd_prompts(update, ctx):
        await _send(update, core.prompts_reply(update.effective_chat.id))

    @guard
    async def cmd_render(update, ctx, fmt: str = "short", draft: bool = False):
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
            reply = (core.intake_script(chat_id, raw_file.read_text())
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
    app.add_handler(CommandHandler("new", cmd_new))
    app.add_handler(CommandHandler("headline", cmd_headline))
    app.add_handler(CommandHandler("prompts", cmd_prompts))
    app.add_handler(CommandHandler("render", cmd_render))
    app.add_handler(CommandHandler("render_long", cmd_render_long_impl))
    app.add_handler(CommandHandler("draft", cmd_draft))
    app.add_handler(CommandHandler("repurpose", cmd_repurpose))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("cost", cmd_cost))
    app.add_handler(CommandHandler("screen", cmd_screen))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    return app
