"""Bot entrypoint.

    .venv/bin/python main.py

Requires TELEGRAM_BOT_TOKEN and OPERATOR_CHAT_IDS in the environment /
.env (a bot token is free via @BotFather; MOCK_MODE only mocks the PAID
APIs — the bot itself talks to Telegram normally).
"""

from __future__ import annotations

import logging

from config import detect_ffmpeg, get_settings
from pipeline.jobs import RenderJobQueue

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

        core.queue = RenderJobQueue(settings, core.execute_job, notify)
        core.queue.start()

        try:  # scheduled screener digest (§14) — degrades silently if absent
            from pipeline.screener import schedule_digest
            schedule_digest(application, core)
        except ImportError:
            log.info("screener module not present; digest not scheduled")

    app.post_init = _post_init
    log.info("starting polling")
    app.run_polling(allowed_updates=None)


if __name__ == "__main__":
    main()
