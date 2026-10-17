"""Bot fixes from the full code review (10-16)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace as NS

import pytest

from bot.handlers import control_first_processor, is_queue_control


def _msg(text):
    return NS(message=NS(text=text), callback_query=None)


def _tap(data):
    return NS(message=None, callback_query=NS(data=data))


@pytest.mark.parametrize("update, control", [
    (_msg("/jobs"), True),
    (_msg("/jobs cancel XYZ"), True),
    (_msg("/status"), True),
    (_msg("/cancel@dennis_bot"), True),
    (_tap("x|short|XYZ|2026-10-16"), True),
    (_msg("/render XYZ"), False),
    (_msg("cancel"), False),
    (_msg("/"), False),
    (_tap("a|short|XYZ|2026-10-16|abcd1234"), False),
    (NS(), False),
])
def test_which_updates_are_queue_controls(update, control):
    assert is_queue_control(update) is control


def test_a_cancel_answers_while_a_slow_update_holds_the_line():
    """An upload waiting out a filing reading used to hold every update
    behind it, /jobs cancel included."""
    async def run():
        proc = control_first_processor()
        done: list[str] = []
        release = asyncio.Event()

        async def slow():
            await release.wait()
            done.append("upload")

        async def quick(name):
            done.append(name)

        t1 = asyncio.create_task(proc.process_update(_msg("dennis_data.xlsx"), slow()))
        await asyncio.sleep(0)
        t2 = asyncio.create_task(proc.process_update(_msg("/render XYZ"), quick("render")))
        t3 = asyncio.create_task(proc.process_update(_msg("/jobs cancel"), quick("cancel")))
        await asyncio.sleep(0.05)
        assert done == ["cancel"], "the cancel waited behind the upload"
        release.set()
        await asyncio.gather(t1, t2, t3)
        # Everything else still runs in the order it arrived.
        assert done == ["cancel", "upload", "render"]

    asyncio.run(run())


@pytest.mark.parametrize("typed, want", [
    ("NOW", ["NOW"]),                         # a video called NOW exists
    ("now", ["XYZ@2026-10-16", "now"]),       # the keyword, lower case
    ("RUN", ["XYZ@2026-10-16", "RUN"]),       # no video called RUN here
])
def test_a_ticker_that_is_also_a_keyword_is_not_replaced(settings, tmp_path,
                                                          typed, want):
    """With XYZ active, `/render NOW` used to render XYZ."""
    from bot.commands import Call, _fill_ticker, resolve

    live = settings.model_copy(update={"workspace_dir": tmp_path})
    (tmp_path / "NOW" / "2026-10-15").mkdir(parents=True)
    core = NS(settings=live,
              context={7: NS(ticker="XYZ", workdate="2026-10-16")})
    cmd, _fam, args, raw = resolve("render", [typed], "")
    c = Call(core, 7, args, raw, None)
    assert _fill_ticker(c, cmd) is None
    assert c.args == want


@pytest.mark.parametrize("picked, words, block", [
    ("2", "", "Angle 2 from the ranked angles you gave in Step 1"),
    ("Angle 3", "", "Angle 3 from the ranked angles"),
    ("the moat is a toll road", "the moat is a toll road", "the moat is a toll road"),
    ("", "", "use your ★recommended angle"),
])
def test_an_angle_picked_by_number_is_a_choice_not_a_thesis(picked, words, block):
    """An "Angle 2" tap used to reach the quote flagger as the thesis "2"."""
    from bot.handlers import angle_words
    from bot.prompts import _angle_block

    assert angle_words(picked) == words
    assert block in _angle_block(picked)


def test_the_angle_tap_flags_quotes_against_no_thesis(settings, monkeypatch):
    from bot.handlers import BotCore
    from pipeline.workspace import Workspace

    core = BotCore(settings)
    ws = Workspace(settings, "EXMPL", "2026-10-16").create()
    seen: list[str] = []
    monkeypatch.setattr(core, "_company_data", lambda ws: object())
    monkeypatch.setattr(core, "_auto_filings", lambda ws, angle: seen.append(angle))
    monkeypatch.setattr(core, "_long_write_reply", lambda ws, header: header)
    core._intake_angle(ws, "2")
    assert seen == [""] and ws.chosen_angle() == "2"


@pytest.mark.parametrize("symbol, headline, mode", [
    ("WMT", "Walmart tops holiday shopping forecasts", "company"),
    ("UPS", "UPS stops shipping to three countries", "company"),
    ("AMZN", "Amazon dropping prices across Prime", "company"),
    ("SPY", "Anything at all", "macro"),
    ("XYZ", "Hot PPI print rattles markets", "macro"),
    ("XYZ", "Payrolls jump as jobless claims fall", "macro"),
    ("XYZ", "XYZ beats on Q3: EPS up 20%", "earnings"),
    ("XYZ", "Earnings: XYZ guides higher", "earnings"),
])
def test_headline_keywords_are_whole_words(symbol, headline, mode):
    from bot.handlers import detect_headline_mode

    assert detect_headline_mode(symbol, headline) == mode


@pytest.mark.parametrize("env", [
    {"INBOX_HOUR": "30"}, {"PUBLISH_HOUR": "99"}, {"ALERT_START_HOUR": "-1"},
    {"BATCH_END_HOUR": "25"}, {"PUBLISH_MINUTE": "60"},
    {"ALERT_POLL_MINUTES": "0"},
])
def test_a_clock_setting_out_of_range_is_refused_at_start(monkeypatch, env):
    from pydantic import ValidationError

    from config import Settings

    for k, v in env.items():
        monkeypatch.setenv(k, v)
    with pytest.raises(ValidationError, match=next(iter(env))):
        Settings(_env_file=None)


def test_an_end_hour_of_24_is_midnight(monkeypatch):
    from config import Settings

    monkeypatch.setenv("ALERT_END_HOUR", "24")
    assert Settings(_env_file=None).alert_end_hour == 24


@pytest.mark.parametrize("agent, warned", [
    ("", True), ("Your Name your@email", True), ("Dennis channel", True),
    ("YourChannel contact@your-channel-domain.com", True),
    ("Dennis Desk desk@example.org", False),
])
def test_the_shipped_sec_placeholder_is_warned_about(settings, agent, warned):
    live = settings.model_copy(update={"mock_mode": False,
                                       "sec_user_agent": agent})
    said = any("SEC_USER_AGENT" in w for w in live.deployment_warnings())
    assert said is warned


def test_a_new_video_card_survives_the_prune(settings):
    """Past 200 videos the alphabetically first keys used to go, so a new
    AAA card was dropped by the call that stored it."""
    from bot import commands as cmds
    from bot.handlers import BotCore

    board = cmds.CardBoard(BotCore(settings))
    for i in range(200):
        board.remember(f"Z{i:03d}@2026-10-01", 1, i)
    board.remember("AAA@2026-10-16", 1, 999)
    assert board.cards("AAA@2026-10-16") == [(1, 999)]
    assert board.cards("Z000@2026-10-01") == []          # the oldest went
    # A video shown again counts as recent.
    board.remember("Z001@2026-10-01", 1, 1000)
    board.remember("BBB@2026-10-16", 1, 1001)
    assert board.cards("Z001@2026-10-01") == [(1, 1000)]
    assert board.cards("Z002@2026-10-01") == []


def test_cost_says_when_a_lane_passes_the_weekly_mark(settings):
    from bot.handlers import BotCore

    core = BotCore(settings.model_copy(update={"weekly_spend_warn_usd": 5.0}))
    assert "weekly mark" not in core.cost_text()
    core.ledger.record_tts(6.0, lane="long", ticker="XYZ")
    text = core.cost_text()
    assert "on the long lane, past the $5.00 weekly mark" in text
    assert "short lane" not in text
