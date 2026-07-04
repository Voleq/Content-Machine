"""Telegram command/callback handlers (§9).

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
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw

from config import Settings
from pipeline.broll import BrollManager, palette_keys
from pipeline.cost import (
    SpendLedger,
    build_long_report,
    build_short_report,
)
from pipeline.delivery import deliver
from pipeline.jobs import JobCancelled, JobRecord, RenderJobQueue
from pipeline.models import JobKind, TagType
from pipeline.parser_long import LongScriptError, parse_long_script, validate_long_script
from pipeline.parser_short import ScriptParseError, parse_short_script
from pipeline.rasters import load_font
from pipeline.refinitiv import RefinitivError, list_screenshots, load_audit
from pipeline.render_long import render_long
from pipeline.render_short import render_short
from pipeline.tts import TTSEngine
from pipeline.workspace import ActiveContext, Workspace, today_str

from bot.keyboards import approval_keyboard, swap_keyboard
from bot.prompts import fill_prompt

log = logging.getLogger(__name__)

HELP_TEXT = """Due Diligence Desk — operator commands

/new TICKER — open today's workspace, get the audit template
/prompts — re-send the pre-filled master prompts
/screen [trending|value|all] — ranked candidate tickers
/render TICKER — render the approved SHORT
/render_long TICKER — render the approved LONG
/draft TICKER — cheap low-res LONG timing check (no TTS spend)
/status — job queue
/cancel TICKER — cancel queued/running jobs + pending approval
/cost — month-to-date spend vs cap
/help — this text

Flow: /new → upload data_refinitiv.xlsx (+ screenshot PNGs) → run the
prompts in Claude/GPT → paste the output back here → review the
validation & cost report → Approve ✅ → /render. Nothing paid happens
before Approve."""


@dataclass
class Reply:
    text: str
    keyboard: object | None = None  # telegram.InlineKeyboardMarkup
    files: list[Path] = field(default_factory=list)
    photo: Path | None = None


class BotCore:
    def __init__(self, settings: Settings):
        self.settings = settings
        settings.ensure_runtime_dirs()
        self.ledger = SpendLedger(settings)
        self.tts = TTSEngine(settings, ledger=self.ledger)
        self.broll = BrollManager(settings, ledger=self.ledger)
        self.context = ActiveContext(settings)
        self.queue: RenderJobQueue | None = None  # attached in main.py

    # ------------------------------------------------------------- helpers
    def _ws_or_error(self, ticker: str) -> Workspace | None:
        return Workspace.latest_for(self.settings, ticker)

    def _active_ws(self, chat_id: int) -> Workspace | None:
        return self.context.get(chat_id)

    # ---------------------------------------------------------------- /new
    def new_ticker(self, chat_id: int, ticker: str) -> Reply:
        ticker = ticker.strip().upper()
        if not ticker or not ticker.replace(".", "").replace("-", "").isalnum():
            return Reply("Usage: /new TICKER")
        ws = Workspace(self.settings, ticker, today_str()).create()
        self.context.set(chat_id, ticker, ws.workdate)
        template = self.settings.templates_dir / "refinitiv_audit_template.xlsx"
        return Reply(
            f"📁 Workspace ready: {ticker} / {ws.workdate}\n\n"
            f"1. Refresh the attached audit template for {ticker} in Excel "
            f"(Refinitiv add-in), save, and upload it here as data_refinitiv.xlsx "
            f"(CSV also accepted).\n"
            f"2. Optionally upload raw Refinitiv screenshot PNGs for "
            f"[SHOW REFINITIV] moments.\n"
            f"3. I'll reply with the pre-filled master prompts.",
            files=[template] if template.exists() else [],
        )

    # ------------------------------------------------------------ /prompts
    def prompts_reply(self, chat_id: int) -> Reply:
        ws = self._active_ws(chat_id)
        if ws is None:
            return Reply("No active workspace — start with /new TICKER.")
        try:
            audit = load_audit(ws.path)
        except RefinitivError as e:
            return Reply(f"⛔ {e}")
        if audit.blocking_missing:
            return Reply(
                "⛔ Refinitiv export is missing required fields "
                f"({', '.join(audit.blocking_missing[:8])}…). Refresh and re-upload."
            )
        files = []
        for fmt in ("short", "long"):
            text = fill_prompt(fmt, ws.ticker, audit, ws.path, self.settings)
            f = ws.path / f"prompt_{fmt}.md"
            f.write_text(text)
            files.append(f)
        warn = ""
        if audit.warning_missing:
            warn = f"\n⚠️ optional fields missing: {', '.join(audit.warning_missing[:6])}"
        return Reply(
            f"📋 Master prompts for {ws.ticker} (as of {audit.get('as_of_date')}) — "
            f"run in Claude/GPT and paste the output back here.{warn}",
            files=files,
        )

    # ------------------------------------------------------------- uploads
    def handle_upload(self, chat_id: int, filename: str, data: bytes) -> Reply:
        ws = self._active_ws(chat_id)
        if ws is None:
            return Reply("No active workspace — start with /new TICKER, then re-upload.")
        name = Path(filename).name
        suffix = Path(name).suffix.lower()

        if suffix in (".xlsx", ".csv"):
            dest = ws.path / f"data_refinitiv{suffix}"
            dest.write_bytes(data)
            reply = self.prompts_reply(chat_id)
            reply.text = f"💾 saved {dest.name} for {ws.ticker}.\n\n" + reply.text
            return reply

        if suffix in (".png", ".jpg", ".jpeg"):
            safe = name.replace(" ", "_")
            (ws.path / safe).write_bytes(data)
            shots = list_screenshots(ws.path)
            return Reply(
                f"🖼 saved {safe}. Screenshots available for [SHOW REFINITIV]: "
                f"{', '.join(shots)}"
            )

        if suffix in (".txt", ".json", ".md"):
            return self.intake_script(chat_id, data.decode("utf-8", errors="replace"))

        return Reply(f"Unsupported file type: {name}")

    # ------------------------------------------------------- script intake
    def intake_script(self, chat_id: int, text: str) -> Reply:
        ws = self._active_ws(chat_id)
        if ws is None:
            return Reply("No active workspace — /new TICKER first.")
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
        v_warnings, v_blocking = validate_long_script(
            script, palette_keys(), ws.path, self.settings
        )
        ws.save_long(script, raw)
        keys = self._long_broll_keys(script)
        plan = self.broll.plan(keys, ws.broll_overrides())
        refin_count = len({e.payload for e in script.events_of(TagType.SHOW_REFINITIV)})
        report = build_long_report(
            script, warnings, v_warnings, v_blocking,
            self.settings, self.ledger, self.tts, plan, refin_count,
        )
        (ws.path / "report_long.txt").write_text(report.render_text())
        sheet = self._contact_sheet(ws, plan)
        return Reply(
            report.render_text(),
            keyboard=approval_keyboard("long", ws.ticker, ws.workdate,
                                       report.script_sha, report.approvable, bool(plan)),
            photo=sheet,
        )

    @staticmethod
    def _long_broll_keys(script) -> list[str]:
        seen: list[str] = []
        for e in script.events_of(TagType.BROLL):
            if e.payload not in seen:
                seen.append(e.payload)
        return seen

    def _contact_sheet(self, ws: Workspace, plan) -> Path | None:
        """Grid of proposed b-roll thumbnails (§9.2)."""
        if not plan:
            return None
        thumbs = []
        for clip in plan:
            t = ws.path / "thumbs" / f"{clip.key}.png"
            try:
                self.broll.thumbnail(clip, t)
                thumbs.append((clip, Image.open(t).convert("RGB")))
            except Exception:
                log.warning("thumbnail failed for %s", clip.key)
        if not thumbs:
            return None
        cols = min(3, len(thumbs))
        rows = (len(thumbs) + cols - 1) // cols
        tw, th, label_h = 320, 180, 30
        sheet = Image.new("RGB", (cols * tw, rows * (th + label_h)), (18, 18, 22))
        d = ImageDraw.Draw(sheet)
        font = load_font(self.settings, "DejaVuSansMono-Bold.ttf", 18)
        for i, (clip, img) in enumerate(thumbs):
            x, y = (i % cols) * tw, (i // cols) * (th + label_h)
            sheet.paste(img.resize((tw, th)), (x, y))
            d.text((x + 6, y + th + 5), f"{clip.key} [{clip.source}]",
                   font=font, fill=(240, 240, 240))
        out = ws.path / "broll_contact_sheet.png"
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
        keys = self._long_broll_keys(script)
        return Reply(
            "Pick the b-roll key to swap to its next take "
            "(approval resets after a swap):",
            keyboard=swap_keyboard(ticker, workdate, keys),
        )

    def swap_key(self, chat_id: int, ticker: str, workdate: str, key: str) -> Reply:
        ws = Workspace(self.settings, ticker, workdate)
        script = ws.load_long()
        if script is None:
            return Reply("No LONG script on file.")
        current = ws.broll_overrides().get(key, 0)
        n = self.broll.alternates_count(key)
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
                    and not self.tts.is_cached(script.narration, "long")
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
            tts = self.tts.synthesize(script.audio_script, "short")
            checkpoint("render")
            out, manifest = render_short(script, tts, ws.path, self.settings)
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
            tts = self.tts.synthesize(script.narration, "long")
            checkpoint("render")
            audit_as_of = ""
            try:
                audit_as_of = str(load_audit(ws.path).get("as_of_date") or "")
            except RefinitivError:
                pass
            out, manifest = render_long(
                script, tts, ws.path, self.settings, broll=self.broll,
                draft=draft, broll_overrides=ws.broll_overrides(), as_of=audit_as_of,
            )
            if draft:
                job.delivered_link = f"file://{out}"
                return str(out)
            checkpoint("delivery")
            import json as _json
            attributions = _json.loads(Path(manifest).read_text()).get("attributions", [])
            extra: list[Path] = []
            try:  # LONG gets an auto thumbnail (M9 module)
                from pipeline.thumbnail import make_thumbnail
                thumb = make_thumbnail(script, ws, self.settings)
                if thumb:
                    extra.append(thumb)
            except ImportError:
                pass
            result = deliver(out, job.ticker, job.workdate, self.settings,
                             attributions=attributions, extra_files=extra)
            self._finish(job, result)
            return str(out)

        raise RuntimeError(f"unknown job kind {job.kind}")

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
        from pipeline.screener import screen_reply  # M10 module
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
    app.add_handler(CommandHandler("prompts", cmd_prompts))
    app.add_handler(CommandHandler("render", cmd_render))
    app.add_handler(CommandHandler("render_long", cmd_render_long_impl))
    app.add_handler(CommandHandler("draft", cmd_draft))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("cost", cmd_cost))
    app.add_handler(CommandHandler("screen", cmd_screen))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    return app
