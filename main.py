"""Bot entrypoint.

    .venv/bin/python main.py

Requires TELEGRAM_BOT_TOKEN and OPERATOR_CHAT_IDS in the environment /
.env (a bot token is free via @BotFather; MOCK_MODE only mocks the PAID
APIs — the bot itself talks to Telegram normally).
"""

from __future__ import annotations

import asyncio
import logging

from config import detect_ffmpeg, get_settings
from pipeline.jobs import RenderJobQueue
from pipeline.render_common import set_render_politeness

from bot.commands import NotifyPrefs, menu_commands, schedule_inbox
from bot.feed import Feed
from bot.handlers import (BotCore, build_application, schedule_batch,
                          schedule_retention_notes)

log = logging.getLogger("dennis")


def main() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    ffmpeg, _ = detect_ffmpeg()
    log.info("ffmpeg: %s", ffmpeg)
    # Say which subsystems are inventing data, at startup, every time. A run
    # where /screen returned fixture tickers and the chart drew synthetic
    # prices — neither labelled — produced a bug report about numbers that
    # were never real.
    banner = settings.mock_banner()
    if banner:
        log.warning("%s", banner)
        log.warning("mock: %s | live: %s",
                    ", ".join(settings.active_mocks()) or "none",
                    ", ".join(n for n in ("TTS", "PRICES", "SCREENER")
                              if n not in settings.active_mocks()) or "none")
    else:
        log.info("all subsystems LIVE (no mock data)")
    # Under WSL2, workspace/cache/state on a Windows drive (/mnt/c/...) makes
    # the render cache pathologically slow — it is thousands of small files
    # and every access crosses the translation layer. Warned about here rather
    # than left to be discovered as "renders got slow".
    settings.warn_about_windows_drives(log)
    # Renders are unattended on what is also somebody's desktop: cap the
    # ffmpeg thread pools and drop the child processes below normal priority.
    set_render_politeness(settings)
    if not settings.telegram_bot_token:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN is not set. Create a bot with @BotFather and put "
            "the token in .env (see .env.example)."
        )
    if not settings.operator_chat_ids:
        log.warning("OPERATOR_CHAT_IDS is empty — every chat will be refused "
                    "(the refusal message shows the chat id to add).")
    if not settings.mock_mode:
        log.warning("MOCK_MODE is OFF — paid APIs are live. Spend cap: $%.2f",
                    settings.monthly_spend_cap_usd)
    # THINGS THAT QUIETLY MAKE VIDEOS WORSE (P9). None of these refuses to
    # boot and none blocks a render — each costs a feature that degrades
    # silently by design, which is exactly how you lose three of them and
    # are told nothing. Beside the mock banner, at the same moment.
    for warning in settings.deployment_warnings():
        log.warning("%s", warning)
    # Said every boot, empty or not: the size of the owned library decides
    # how often the chain reaches past it, and it is a fact about this box
    # rather than about the code (P9b).
    log.info("owned b-roll library: %d clip(s) in %s",
             settings.broll_library_size(),
             settings.assets_dir / "broll_library")

    core = BotCore(settings)
    # Every push the bot makes is also kept for the web panel's Activity.
    core.feed = Feed()
    app = build_application(settings, core)
    prefs = NotifyPrefs(settings)

    async def _post_init(application) -> None:
        async def notify(text: str) -> None:
            core.feed.add("notice", text)
            # `/admin quiet`: only finished, failed and needs-you reach the
            # chat; the panel's feed keeps everything.
            if not prefs.wants(text):
                return
            # Every operator chat gets its copy: one chat that fails (blocked
            # the bot, left the group) used to stop the rest from hearing.
            for chat_id in settings.operator_chat_ids:
                try:
                    await application.bot.send_message(chat_id, text)
                except Exception:  # noqa: BLE001 - the next chat still hears
                    log.exception("could not notify chat %s", chat_id)

        loop = asyncio.get_running_loop()

        def push_file(path, caption: str = "") -> None:
            """Called from the render worker thread — hop back to the bot's
            loop to actually send, and WAIT for the answer.

            BY TYPE AND SIZE, not always as a photo (E3): `telegram_send_kind`
            picks video, photo or document, and refuses a file the cloud Bot
            API would refuse rather than finding out from it.

            It used to schedule the send and return at once, so a failure
            happened on the loop with nobody listening: `BotCore.push_file`
            reported every push as sent, and `DELIVERY_BACKEND=telegram`
            said "(sent in chat)" about a video Telegram had rejected. Now the
            exception comes back here, and `BotCore.push_file` tells the
            operator where the file is instead.
            """
            from pathlib import Path as _P

            from bot.handlers import telegram_send_kind

            p = _P(path)
            core.feed.add("file", caption, files=[p])
            kind = telegram_send_kind(p, settings)   # raises if unsendable

            async def _send() -> None:
                for chat_id in settings.operator_chat_ids:
                    with open(p, "rb") as fh:
                        if kind == "video":
                            await application.bot.send_video(
                                chat_id, fh, caption=caption[:1024],
                                supports_streaming=True)
                        elif kind == "photo":
                            await application.bot.send_photo(
                                chat_id, fh, caption=caption[:1024])
                        else:
                            await application.bot.send_document(
                                chat_id, fh, caption=caption[:1024])

            fut = asyncio.run_coroutine_threadsafe(_send(), loop)
            try:
                on_loop = asyncio.get_running_loop() is loop
            except RuntimeError:
                on_loop = False
            if on_loop:
                # Waiting here would deadlock the loop the send runs on; the
                # failure is still logged rather than lost.
                fut.add_done_callback(
                    lambda f: f.exception() and log.error(
                        "could not send %s: %s", p.name, f.exception()))
                return
            fut.result(timeout=settings.telegram_send_timeout_s)

        core.file_pusher = push_file
        core.queue = RenderJobQueue(settings, core.execute_job, notify)
        # Video cards edit themselves as their jobs move.
        core.cards.loop = loop
        core.queue.store.listeners.append(core.cards.job_changed)
        core.queue.start()

        # The trimmed "/" menu: the three entry points and the nine
        # families. The old names still answer; they are just not listed.
        try:
            from telegram import BotCommand, BotCommandScopeChat

            menu = [BotCommand(n, d) for n, d in menu_commands()]
            for chat_id in settings.operator_chat_ids:
                await application.bot.set_my_commands(
                    menu, scope=BotCommandScopeChat(chat_id))
        except Exception as e:  # noqa: BLE001 - the menu is a convenience
            log.warning("could not set the Telegram command menu: %s", e)

        # Everything waiting on you, every morning.
        schedule_inbox(application, core, send=core.send_to)

        # The web panel, on this loop.
        if settings.panel_enabled:
            try:
                from bot.panel import start_panel
                start_panel(core, loop)
            except OSError as e:
                log.warning("web panel not started (%s:%d): %s",
                            settings.panel_host, settings.panel_port, e)

        try:  # scheduled screener digest (§14) — degrades silently if absent
            from pipeline.screener import schedule_alerts, schedule_digest
            schedule_digest(application, core)
            # Intraday watch (3b): the digest covers the value lane, this
            # covers short-form, which goes stale in hours.
            schedule_alerts(application, core)
        except ImportError:
            log.info("screener module not present; digest not scheduled")
        # The overnight window: what `/batch` queued runs in it unattended.
        schedule_batch(application, core)
        # Weekly: the sentences viewers left on, into the next writing prompt.
        schedule_retention_notes(application, core)

    async def _post_shutdown(application) -> None:
        """Let go of anything still reading a filing (P1).

        A reading is eight to ten minutes of SEC pulls and LLM calls. Its
        worker is a daemon thread so the interpreter never waits for it, and
        this is where the operator finds out which brief was dropped — a
        silent abandonment is how you re-run `/long` and wonder why the
        angle prompt has no filing in it.
        """
        abandoned = core.filing_reader.shutdown()
        if abandoned:
            log.warning("shutting down with %d filing reading(s) unfinished: "
                        "%s — re-run /long for those tickers; nothing is lost "
                        "but the reading itself",
                        len(abandoned), ", ".join(abandoned))

    app.post_init = _post_init
    app.post_shutdown = _post_shutdown
    log.info("starting polling")
    app.run_polling(allowed_updates=None)


if __name__ == "__main__":
    main()
