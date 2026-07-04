import json
from datetime import date, timedelta

from pipeline.models import ShortScript
from pipeline.workspace import ActiveContext, Workspace, audited_tickers_since


def _script(short_valid_json) -> ShortScript:
    return ShortScript.model_validate_json(short_valid_json)


def test_approval_pins_content_sha(settings, short_valid_json):
    ws = Workspace(settings, "exmpl", "2026-07-01").create()
    script = _script(short_valid_json)
    ws.save_short(script, short_valid_json)
    assert not ws.is_approved("short")

    ws.approve("short", script.content_sha(), "report text")
    assert ws.is_approved("short")

    # any script change invalidates the approval
    changed = script.model_copy(update={"cta_text": "Different bait."})
    ws.save_short(changed, short_valid_json)
    assert not ws.is_approved("short")


def test_save_short_clears_previous_approval(settings, short_valid_json):
    ws = Workspace(settings, "EXMPL", "2026-07-01").create()
    script = _script(short_valid_json)
    ws.save_short(script, short_valid_json)
    ws.approve("short", script.content_sha(), "r")
    ws.save_short(script, short_valid_json)  # re-paste == re-review
    assert ws.approved_sha("short") is None


def test_latest_for_picks_newest_date(settings):
    Workspace(settings, "ABC", "2026-06-01").create()
    Workspace(settings, "ABC", "2026-07-01").create()
    ws = Workspace.latest_for(settings, "abc")
    assert ws is not None and ws.workdate == "2026-07-01"
    assert Workspace.latest_for(settings, "NOPE") is None


def test_broll_override_invalidates_long_approval(settings, long_valid_text):
    from pipeline.parser_long import parse_long_script

    ws = Workspace(settings, "EXMPL", "2026-07-01").create()
    script, _ = parse_long_script(long_valid_text, "EXMPL", settings)
    ws.save_long(script, long_valid_text)
    ws.approve("long", script.content_sha(), "r")
    assert ws.is_approved("long")

    ws.set_broll_override("clown", 1)
    assert not ws.is_approved("long")
    assert ws.broll_overrides() == {"clown": 1}


def test_active_context_roundtrip(settings):
    ctx = ActiveContext(settings)
    assert ctx.get(1) is None
    Workspace(settings, "XYZ", "2026-07-01").create()
    ctx.set(1, "xyz", "2026-07-01")
    ws = ctx.get(1)
    assert ws is not None and ws.ticker == "XYZ"


def test_audited_tickers_cooldown(settings):
    recent = date.today().isoformat()
    old = (date.today() - timedelta(days=90)).isoformat()
    Workspace(settings, "FRESH", recent).create()
    Workspace(settings, "STALE", old).create()
    tickers = audited_tickers_since(settings, days=30)
    assert "FRESH" in tickers and "STALE" not in tickers
