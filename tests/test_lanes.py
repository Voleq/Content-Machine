"""Explicit `/short` and `/long` lane commands (addendum 1d).

`/new` prepared both master prompts and left the format implicit, so the
operator picked twice: once when running a prompt, again at `/render` vs
`/render_long`. The lane is now declared up front, one command prepares one
prompt, and the render follows from it.

The editorial rule survives as a *warning*, not a gate: long-form is the
beaten-down/value lane, never the trending name of the day — but the screener
is a suggestion engine and the operator has reasons it can't see.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import pytest

from bot.handlers import BotCore
from pipeline.models import JobKind
from pipeline.screener import last_screen_lane
from pipeline.workspace import Workspace

CHAT = 909
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture()
def core(settings):
    return BotCore(settings)


def _with_data(core: BotCore, ticker: str) -> Workspace:
    ws = core.context.get(CHAT)
    shutil.copy(FIXTURES / "company_data" / "dennis_data.xlsx",
                ws.path / "dennis_data.xlsx")
    return ws


def _seed_screen(settings, ticker: str, lane: str) -> None:
    """Pretend the last screen put `ticker` in `lane`."""
    (settings.state_dir).mkdir(parents=True, exist_ok=True)
    (settings.state_dir / "last_screen.json").write_text(json.dumps({
        "ts": time.time(),
        "tickers": {ticker.upper(): {"lane": lane, "reasons": ["seeded"]}},
    }))


# --------------------------------------------------------------------------
# One command, one lane, one prompt.
# --------------------------------------------------------------------------


def test_short_declares_the_lane_and_says_the_format(core, settings):
    reply = core.start_lane(CHAT, "short", "exmpl")
    assert "EXMPL" in reply.text
    assert "SHORT" in reply.text and "60–75s" in reply.text
    assert core.context.get(CHAT).lane() == "short"


def test_long_declares_the_lane_and_opens_the_angle_step(core, settings):
    reply = core.start_lane(CHAT, "long", "exmpl")
    assert "LONG" in reply.text
    ws = core.context.get(CHAT)
    assert ws.lane() == "long"
    assert ws.awaiting_angle(), "the LONG flow starts at the angle pick"


def test_short_prepares_only_the_short_prompt(core, settings):
    core.start_lane(CHAT, "short", "EXMPL")
    ws = _with_data(core, "EXMPL")
    reply = core.prompts_reply(CHAT)
    names = [f.name for f in reply.files]
    assert names == ["prompt_short.md"], names
    assert "SHORT" in reply.text
    assert "prompt_long_angle" not in reply.text
    assert not ws.awaiting_angle(), "a SHORT is not in the angle flow"


def test_long_prepares_only_the_angle_prompt(core, settings):
    core.start_lane(CHAT, "long", "EXMPL")
    ws = _with_data(core, "EXMPL")
    reply = core.prompts_reply(CHAT)
    names = [f.name for f in reply.files]
    assert names == ["prompt_long_angle.md"], names
    assert ws.awaiting_angle()


def test_a_bad_ticker_gets_the_lane_specific_usage(core):
    assert "/short TICKER" in core.start_lane(CHAT, "short", "").text
    assert "/long TICKER" in core.start_lane(CHAT, "long", "!!").text


def test_switching_lanes_on_the_same_ticker_reprepares(core, settings):
    """An operator who starts a SHORT and changes their mind gets the LONG
    flow, not a workspace remembering the old lane."""
    core.start_lane(CHAT, "short", "EXMPL")
    _with_data(core, "EXMPL")
    assert [f.name for f in core.prompts_reply(CHAT).files] == ["prompt_short.md"]

    core.start_lane(CHAT, "long", "EXMPL")
    ws = core.context.get(CHAT)
    assert ws.lane() == "long"
    assert [f.name for f in core.prompts_reply(CHAT).files] == ["prompt_long_angle.md"]


# --------------------------------------------------------------------------
# The editorial rule: warn, never block.
# --------------------------------------------------------------------------


def test_a_trending_name_in_the_long_lane_is_warned_about(core, settings):
    """Long-form is the value lane. A name that ran today is usually a SHORT."""
    _seed_screen(settings, "EXMPL", "trending")
    reply = core.start_lane(CHAT, "long", "EXMPL")
    assert "⚠️" in reply.text
    assert "trending" in reply.text
    # warned, not blocked
    assert core.context.get(CHAT).lane() == "long"


def test_a_value_name_in_the_short_lane_is_warned_about(core, settings):
    _seed_screen(settings, "EXMPL", "value")
    reply = core.start_lane(CHAT, "short", "EXMPL")
    assert "⚠️" in reply.text and "value" in reply.text
    assert core.context.get(CHAT).lane() == "short"


def test_the_matching_lane_is_not_nagged_about(core, settings):
    _seed_screen(settings, "EXMPL", "value")
    assert "⚠️" not in core.start_lane(CHAT, "long", "EXMPL").text
    _seed_screen(settings, "OTHER", "trending")
    assert "⚠️" not in core.start_lane(CHAT, "short", "OTHER").text


def test_a_ticker_the_screener_never_saw_is_not_second_guessed(core, settings):
    assert "⚠️" not in core.start_lane(CHAT, "long", "NEVERSEEN").text


def test_a_stale_screen_stops_being_used_as_evidence(core, settings):
    """Yesterday's lane is not evidence about today's ticker."""
    (settings.state_dir).mkdir(parents=True, exist_ok=True)
    (settings.state_dir / "last_screen.json").write_text(json.dumps({
        "ts": time.time() - 90000,          # >24h
        "tickers": {"EXMPL": {"lane": "trending", "reasons": []}},
    }))
    assert last_screen_lane(settings, "EXMPL") == ""
    assert "⚠️" not in core.start_lane(CHAT, "long", "EXMPL").text


# --------------------------------------------------------------------------
# /render follows the lane.
# --------------------------------------------------------------------------


def test_render_takes_the_format_from_the_lane(core, settings, short_valid_json):
    core.start_lane(CHAT, "short", "EXMPL")
    ws = _with_data(core, "EXMPL")
    core.intake_script(CHAT, short_valid_json)
    script = ws.load_short()
    ws.approve("short", script.content_sha(), "report")

    kind, text, got = core.render_request("EXMPL")      # no format given
    assert kind is JobKind.RENDER_SHORT, text
    assert got is not None


def test_render_takes_the_long_lane_too(core, settings, long_valid_text):
    core.start_lane(CHAT, "long", "EXMPL")
    ws = _with_data(core, "EXMPL")
    core.intake_script(CHAT, long_valid_text)
    script = ws.load_long()
    ws.approve("long", script.content_sha(), "report")

    kind, text, _ = core.render_request("EXMPL")
    assert kind is JobKind.RENDER_LONG, text


def test_render_without_a_lane_or_a_script_asks_which(core, settings):
    Workspace(settings, "EXMPL", "2026-07-01").create()
    kind, text, _ = core.render_request("EXMPL")
    assert kind is None
    assert "/short EXMPL" in text and "/long EXMPL" in text


def test_an_explicit_format_still_wins(core, settings, short_valid_json):
    """`/render_long` must keep working for a ticker that has both."""
    core.start_lane(CHAT, "short", "EXMPL")
    ws = _with_data(core, "EXMPL")
    core.intake_script(CHAT, short_valid_json)

    kind, text, _ = core.render_request("EXMPL", "long")
    assert kind is None
    assert "No LONG script" in text


# --------------------------------------------------------------------------
# /new survives one release as an alias.
# --------------------------------------------------------------------------


def test_new_still_works_and_says_it_is_deprecated(core, settings):
    core.new_ticker(CHAT, "EXMPL")
    _with_data(core, "EXMPL")
    reply = core.prompts_reply(CHAT)
    names = sorted(f.name for f in reply.files)
    assert names == ["prompt_long_angle.md", "prompt_short.md"], names
    assert "deprecated" in reply.text
    assert "/short TICKER" in reply.text


def test_new_leaves_the_lane_unset_which_is_what_makes_it_the_old_behaviour(
        core, settings):
    core.new_ticker(CHAT, "EXMPL")
    assert core.context.get(CHAT).lane() == ""


def test_new_with_a_bad_ticker_points_at_the_replacements(core):
    text = core.new_ticker(CHAT, "").text
    assert "/short TICKER" in text and "/long TICKER" in text


# --------------------------------------------------------------------------
# The lane is remembered across a restart.
# --------------------------------------------------------------------------


def test_the_lane_survives_a_restart(core, settings):
    core.start_lane(CHAT, "long", "EXMPL")
    fresh = BotCore(settings)
    ws = fresh.context.get(CHAT)
    assert ws is not None
    assert ws.lane() == "long"
    assert ws.current_format() == "long"
