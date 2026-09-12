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
    }), encoding="utf-8")


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
    }), encoding="utf-8")
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
# /new is gone (L3). It could not know the lane, so it prepared both prompts
# and left the workspace lane-less — one of the inputs to the format-
# resolution mess. Its last caller was the screener's candidate buttons, and
# those now carry the candidate's own lane.
# --------------------------------------------------------------------------


def test_the_lane_less_alias_is_gone_from_the_core_and_the_frontend():
    from bot import handlers

    assert not hasattr(handlers.BotCore, "new_ticker")
    src = Path(handlers.__file__).read_text(encoding="utf-8")
    assert 'CommandHandler("new"' not in src
    assert 'CommandHandler("refresh"' not in src


def test_a_screener_button_opens_the_lane_the_screen_put_it_in(core, settings):
    """G3: the candidate's lane rides in the callback data.

    Asserting on the workspace the button produces, not on the string that
    was handed to Telegram — the old button routed to a lane-less alias and
    a test on the callback text would have passed either way.
    """
    from bot.keyboards import CODE_LANES, candidates_keyboard

    kb = candidates_keyboard([("EXMPL", "short"), ("OTHER", "long")])
    data = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert data == ["n|s|EXMPL", "n|l|OTHER"]

    for payload, expected in zip(data, ("short", "long")):
        op, code, ticker = payload.split("|")
        assert op == "n"
        core.start_lane(CHAT, CODE_LANES[code], ticker)
        assert core.context.get(CHAT).lane() == expected


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


# --------------------------------------------------------------------------
# GROUP C — intake routes by the lane, and the lane is never inferred.
# --------------------------------------------------------------------------


def test_a_chat_remark_does_not_become_a_long_script(core, settings):
    """The headline defect: `ws.lane()` was never consulted and
    `parse_long_script` rejected only empty input, so a note to the operator
    was saved as a forty-minute script."""
    core.start_lane(CHAT, "long", "EXMPL")
    _with_data(core, "EXMPL")
    ws = Workspace.latest_for(settings, "EXMPL")
    ws.clear_awaiting_angle()

    reply = core.intake_script(
        CHAT, "hold on, the revenue number in row 2 looks wrong")

    assert ws.load_long() is None, "a chat remark must not land as a script"
    assert "⛔" in reply.text


def test_a_short_on_a_short_lane_reports_the_shorts_own_rejection(core, settings):
    """It used to retry a failed SHORT as a LONG whenever the text contained
    brackets — which every SHORT does — and the LONG accepted it."""
    core.start_lane(CHAT, "short", "EXMPL")
    _with_data(core, "EXMPL")
    ws = Workspace.latest_for(settings, "EXMPL")

    reply = core.intake_script(CHAT, '{"format": "short", "hook_text": "[x]"}')

    assert "SHORT script rejected" in reply.text
    assert ws.load_long() is None, "a failed SHORT must not become a LONG"


def test_a_paste_at_telegrams_cut_point_is_refused_not_saved(core, settings):
    """C2: Telegram splits over 4,096 characters and each fragment arrives
    as its own paste. The first one used to be saved as a whole script."""
    core.start_lane(CHAT, "long", "EXMPL")
    _with_data(core, "EXMPL")
    ws = Workspace.latest_for(settings, "EXMPL")
    ws.clear_awaiting_angle()

    fragment = "A" * 4096
    reply = core.intake_script(CHAT, fragment)

    assert ws.load_long() is None
    assert ".txt" in reply.text, "the refusal has to say what to do instead"


def test_the_same_text_as_a_file_is_accepted(core, settings, long_valid_text):
    """A file cannot be split, so the refusal must not apply to one."""
    core.start_lane(CHAT, "long", "EXMPL")
    _with_data(core, "EXMPL")
    ws = Workspace.latest_for(settings, "EXMPL")
    ws.clear_awaiting_angle()

    core.handle_upload(CHAT, "script.txt", long_valid_text.encode("utf-8"))

    assert ws.load_long() is not None


def test_the_format_follows_the_lane_not_the_files_on_disk(core, settings,
                                                           short_valid_json,
                                                           long_valid_text):
    """C3: `current_format()` preferred LONG unconditionally, so one stray
    paste made every keyed command target the wrong script for the day."""
    core.start_lane(CHAT, "short", "EXMPL")
    _with_data(core, "EXMPL")
    core.intake_script(CHAT, short_valid_json)
    ws = Workspace.latest_for(settings, "EXMPL")

    # A LONG lands in the same folder (a second lane on the same date).
    ws.save_long(*_parse_long(settings, long_valid_text))

    assert ws.load_long() is not None, "the LONG really is on disk"
    assert ws.current_format() == "short", \
        "the declared lane decides, not which file exists"
    assert ws.format_conflict() == "long", "and the disagreement is visible"


def _parse_long(settings, text):
    from pipeline.parser_long import parse_long_script

    script, _ = parse_long_script(text, "EXMPL", settings)
    return script, text


def test_both_formats_on_one_date_are_each_reachable(core, settings,
                                                     short_valid_json,
                                                     long_valid_text):
    """C4: there was no `/render_short`, so the SHORT became unreachable the
    moment a LONG existed."""
    core.start_lane(CHAT, "short", "EXMPL")
    _with_data(core, "EXMPL")
    core.intake_script(CHAT, short_valid_json)
    ws = Workspace.latest_for(settings, "EXMPL")
    ws.save_long(*_parse_long(settings, long_valid_text))
    ws.approve("short", ws.load_short().content_sha(), "report")
    ws.approve("long", ws.load_long().content_sha(), "report")

    from pipeline.models import JobKind

    kind, _, _ = core.render_request("EXMPL", "short", False)
    assert kind is JobKind.RENDER_SHORT
    kind, _, _ = core.render_request("EXMPL", "long", False)
    assert kind is JobKind.RENDER_LONG


def test_render_short_is_registered_and_documented():
    """`tests/test_docs.py` checks the table against the handlers; this
    checks the handler exists at all."""
    from pathlib import Path

    from bot import handlers

    src = Path(handlers.__file__).read_text(encoding="utf-8")
    assert 'CommandHandler("render_short"' in src


def test_a_missing_design_kit_surfaces_as_a_refusal_not_an_internal_error(
        core, settings, tmp_path, monkeypatch):
    """C5, reproduced on a kit-less checkout before the kit was ingested.

    `parse_long_script` calls `load_plates` for a `[PLATE:]` tag, and
    `assets/plates/` is gitignored and built by `scripts/ingest_kit.py`. On a
    checkout without it that raises `PlateError`, which is not
    `LongScriptError` — so it escaped `intake_script`'s handler entirely and
    the operator saw an internal error instead of the rejection.
    """
    from pipeline import plates

    core.start_lane(CHAT, "long", "EXMPL")
    _with_data(core, "EXMPL")
    ws = Workspace.latest_for(settings, "EXMPL")
    ws.clear_awaiting_angle()

    def no_kit(_assets_dir):
        raise plates.PlateError(
            "no plates-registry.json — run `python scripts/ingest_kit.py kit`")

    monkeypatch.setattr("pipeline.parser_long.load_plates", no_kit)

    text = ("EXMPL is down sixty percent from its high and nobody is left to "
            "sell it, which is the only moment worth reading a filing in. "
            "The revenue line went four hundred million to four ninety six "
            "over five years, which is technically growth in the way a coma "
            "is technically rest, and the losses widened every single year "
            "underneath it. [PLATE: cards/hook-card-t1 | title: Hello] "
            "I will be up at three in the morning either way. "
            "See you at the next filing.")
    reply = core.intake_script(CHAT, text)

    assert "design kit is not installed" in reply.text
    assert "ingest_kit" in reply.text
