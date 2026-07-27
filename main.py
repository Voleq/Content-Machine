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

from bot.handlers import BotCore, build_application

log = logging.getLogger("dennis")


def main() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    ffmpeg, _ = detect_ffmpeg()
    log.info("ffmpeg: %s | mock_mode=%s", ffmpeg, settings.mock_mode)
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

    core = BotCore(settings)
    app = build_application(settings, core)

    async def _post_init(application) -> None:
        async def notify(text: str) -> None:
            for chat_id in settings.operator_chat_ids:
                await application.bot.send_message(chat_id, text)

        loop = asyncio.get_running_loop()

        def push_file(path, caption: str = "") -> None:
            """Called from the render worker thread — hop back to the bot's
            loop to actually send."""
            async def _send() -> None:
                for chat_id in settings.operator_chat_ids:
                    with open(path, "rb") as fh:
                        await application.bot.send_photo(chat_id, fh,
                                                         caption=caption[:1024])
            asyncio.run_coroutine_threadsafe(_send(), loop)

        core.file_pusher = push_file
        core.queue = RenderJobQueue(settings, core.execute_job, notify)
        core.queue.start()

        try:  # scheduled screener digest (§14) — degrades silently if absent
            from pipeline.screener import schedule_alerts, schedule_digest
            schedule_digest(application, core)
            # Intraday watch (3b): the digest covers the value lane, this
            # covers short-form, which goes stale in hours.
            schedule_alerts(application, core)
        except ImportError:
            log.info("screener module not present; digest not scheduled")

    app.post_init = _post_init
    log.info("starting polling")
    app.run_polling(allowed_updates=None)


if __name__ == "__main__":
    main()
