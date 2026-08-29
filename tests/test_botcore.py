"""End-to-end operator flow WITHOUT Telegram: BotCore consumes strings/
bytes and returns Reply values. Covers the full loop: /new → upload →
prompts → paste script → report → approve → render gate → executed job →
local delivery. All in MOCK_MODE, zero network."""

import json

import pytest

from pipeline.models import JobKind, JobRecord
from pipeline.workspace import Workspace

from bot.handlers import BotCore, Reply

CHAT = 4242


@pytest.fixture()
def core(settings):
    small = settings.model_copy(update={
        "short_width": 540, "short_height": 960,
        "long_width": 640, "long_height": 360,
    })
    return BotCore(small)


@pytest.fixture()
def xlsx_bytes(fixtures_dir) -> bytes:
    return (fixtures_dir / "company_data" / "dennis_data.xlsx").read_bytes()


def test_new_ticker_creates_workspace_and_context(core):
    reply = core.new_ticker(CHAT, "exmpl")
    assert "Workspace ready: EXMPL" in reply.text
    assert reply.files and reply.files[0].name == "dennis_data_template.xlsx"
    assert core.context.get(CHAT).ticker == "EXMPL"
    assert "Refinitiv" not in reply.text


def test_upload_xlsx_yields_short_and_long_angle_prompts(core, xlsx_bytes):
    core.new_ticker(CHAT, "EXMPL")
    reply = core.handle_upload(CHAT, "dennis_data.xlsx", xlsx_bytes)
    assert "saved dennis_data.xlsx" in reply.text
    # SHORT is one paste; LONG is now Step 1 (the angle prompt)
    assert len(reply.files) == 2
    short_prompt = next(f for f in reply.files if f.name == "prompt_short.md").read_text(encoding="utf-8")
    angle_prompt = next(f for f in reply.files if "long_angle" in f.name).read_text(encoding="utf-8")
    # no real placeholder braces survive in either (the header's literal
    # "{{placeholder}}" doc token is not a real field)
    import re as _re
    unfilled = _re.compile(r"\{\{(?!placeholder\}\})[a-z_]+\}\}")
    assert not unfilled.search(short_prompt), "short placeholders filled"
    assert not unfilled.search(angle_prompt), "angle placeholders filled"

    assert "Ticker: EXMPL" in short_prompt and "ps_ttm = 62.0" in short_prompt
    assert "[history" in short_prompt, "the 5y history feeds the gut check"
    # catalogs injected into the SHORT writing prompt (with queries / use-when)
    assert "dumpster_fire — dumpster fire burning night" in short_prompt
    assert "numbers-sheet" in short_prompt        # doodle catalog, grouped
    assert "harold-quick-flip-became-bagholder" in short_prompt  # meme catalog
    assert "## VOICE BIBLE" in short_prompt and "deadpan" in short_prompt

    # the angle prompt is Step 1: ranked angles, no script, gets the full data
    assert "PICK THE ANGLE" in angle_prompt and "pick an angle" in angle_prompt
    assert "ps_ttm = 62.0" in angle_prompt
    assert "★recommended" in angle_prompt
    assert "ASSET PROMPTS" not in angle_prompt, "no tags/assets at the angle step"
    assert "Refinitiv" not in short_prompt and "Refinitiv" not in angle_prompt
    # the workspace is now awaiting the operator's angle pick
    ws = Workspace.latest_for(core.settings, "EXMPL")
    assert ws.awaiting_angle()


def test_long_two_step_angle_then_write(core, xlsx_bytes, long_valid_text):
    core.new_ticker(CHAT, "EXMPL")
    core.handle_upload(CHAT, "dennis_data.xlsx", xlsx_bytes)
    ws = Workspace.latest_for(core.settings, "EXMPL")
    assert ws.awaiting_angle()

    # a plain-text reply is the angle pick -> Step 2 writing prompt appears
    reply = core.intake_script(CHAT, "1, but lean on the debt")
    assert "Angle locked" in reply.text
    write = next(f for f in reply.files if "long_write" in f.name).read_text(encoding="utf-8")
    assert "WRITE THE SCRIPT" in write
    assert "1, but lean on the debt" in write, "chosen angle injected"
    assert "## VOICE BIBLE" in write and "dumpster_fire" in write
    assert ws.chosen_angle() == "1, but lean on the debt"

    # now the tagged script pastes back through the normal LONG intake
    import io

    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (800, 500), (20, 24, 30)).save(buf, format="PNG")
    core.handle_upload(CHAT, "income_statement.png", buf.getvalue())
    core.handle_upload(CHAT, "risk_factors.png", buf.getvalue())
    reply2 = core.intake_script(CHAT, long_valid_text)
    assert "EXMPL — LONG" in reply2.text
    assert not ws.awaiting_angle(), "past the angle stage once a script is on file"


def test_prompts_carry_screener_move_context(core, xlsx_bytes):
    state = core.settings.state_dir / "last_screen.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    import time

    state.write_text(json.dumps({
        "ts": time.time(),
        "tickers": {"EXMPL": {"lane": "trending",
                              "reasons": ["+29.0% today", "vol 5.0× avg"],
                              "price": 19.67, "pct_change": 29.0}},
    }), encoding="utf-8")
    core.new_ticker(CHAT, "EXMPL")
    reply = core.handle_upload(CHAT, "dennis_data.xlsx", xlsx_bytes)
    short_prompt = next(f for f in reply.files if "short" in f.name).read_text(encoding="utf-8")
    assert "+29.0% today" in short_prompt
    assert "trending lane" in short_prompt


def test_prompts_blocked_without_upload(core):
    core.new_ticker(CHAT, "EXMPL")
    reply = core.prompts_reply(CHAT)
    assert "⛔" in reply.text


def test_short_intake_report_and_approval_flow(core, xlsx_bytes, short_valid_json):
    core.new_ticker(CHAT, "EXMPL")
    core.handle_upload(CHAT, "dennis_data.xlsx", xlsx_bytes)
    reply = core.intake_script(CHAT, short_valid_json)
    assert "EXMPL — SHORT — ready to render" in reply.text
    assert "$" in reply.text and "cap" in reply.text
    assert "Headlines: 2" in reply.text and "4 rows × 6yr" in reply.text
    assert reply.keyboard is not None

    ws = Workspace.latest_for(core.settings, "EXMPL")
    script = ws.load_short()
    assert script is not None

    # render before approve must be refused (spend gate)
    kind, text, _ = core.render_request("EXMPL", "short")
    assert kind is None and "not approved" in text

    reply = core.approve("short", "EXMPL", ws.workdate, script.content_sha()[:8])
    assert "approved" in reply.text
    kind, text, ws2 = core.render_request("EXMPL", "short")
    assert kind is JobKind.RENDER_SHORT and ws2 is not None


def test_stale_sha_approval_refused(core, xlsx_bytes, short_valid_json):
    core.new_ticker(CHAT, "EXMPL")
    core.handle_upload(CHAT, "dennis_data.xlsx", xlsx_bytes)
    core.intake_script(CHAT, short_valid_json)
    ws = Workspace.latest_for(core.settings, "EXMPL")
    reply = core.approve("short", "EXMPL", ws.workdate, "deadbeef")
    assert "changed" in reply.text
    assert not ws.is_approved("short")


def test_malformed_script_reports_friendly_error(core, xlsx_bytes):
    core.new_ticker(CHAT, "EXMPL")
    core.handle_upload(CHAT, "dennis_data.xlsx", xlsx_bytes)
    reply = core.intake_script(CHAT, '{"ticker": "EXMPL", "format": "short"')
    assert "⛔" in reply.text and "rejected" in reply.text


def test_long_intake_blocks_on_missing_screenshot(core, xlsx_bytes, long_valid_text):
    core.new_ticker(CHAT, "EXMPL")
    core.handle_upload(CHAT, "dennis_data.xlsx", xlsx_bytes)
    reply = core.intake_script(CHAT, long_valid_text)
    assert "BLOCKED" in reply.text
    assert "income_statement.png" in reply.text
    # blocked reports still render a contact sheet for review
    assert reply.photo is not None and reply.photo.exists()

    # uploading the screenshot unblocks on re-paste
    from PIL import Image
    import io
    buf = io.BytesIO()
    Image.new("RGB", (800, 500), (20, 24, 30)).save(buf, format="PNG")
    core.handle_upload(CHAT, "income_statement.png", buf.getvalue())
    core.handle_upload(CHAT, "risk_factors.png", buf.getvalue())
    reply2 = core.intake_script(CHAT, long_valid_text)
    assert "ready to render" in reply2.text
    assert "Visuals:" in reply2.text
    assert "Memes: 1/2" in reply2.text
def test_screengrab_flow_blocks_and_accepts_upload(core, xlsx_bytes):
    """[SCREENGRAB] blocks until the operator's capture is there (image or
    a short screen-record) is routed to assets/custom/ by matching slug."""
    import io

    from PIL import Image

    raw = ("EXMPL is cheap and hated. Here is my account, for context. "
           "[SCREENGRAB: broker-pnl] Twenty five k to zero. "
           "I will be up at three a.m. See you at the next filing.")
    core.new_ticker(CHAT, "EXMPL")
    core.handle_upload(CHAT, "dennis_data.xlsx", xlsx_bytes)

    reply = core.intake_script(CHAT, raw)
    assert "BLOCKED" in reply.text
    assert "SCREENGRAB" in reply.text and "broker-pnl" in reply.text

    custom = core.settings.assets_dir / "custom"
    try:
        # a short screen-record (mp4) whose name matches the slug routes to custom/
        buf = io.BytesIO()
        Image.new("RGB", (1170, 2532), (18, 22, 28)).save(buf, format="PNG")
        r = core.handle_upload(CHAT, "broker-pnl.png", buf.getvalue())
        assert "screengrab broker-pnl" in r.text
        assert (custom / "broker-pnl.png").exists()

        reply2 = core.intake_script(CHAT, raw)
        assert not any(line.startswith("⛔") and "broker-pnl" in line
                       for line in reply2.text.splitlines())
    finally:
        for p in custom.glob("broker-pnl.*"):
            p.unlink()


def test_swap_key_invalidates_approval_and_rotates(core, xlsx_bytes, long_valid_text):
    from PIL import Image
    import io

    core.new_ticker(CHAT, "EXMPL")
    core.handle_upload(CHAT, "dennis_data.xlsx", xlsx_bytes)
    buf = io.BytesIO()
    Image.new("RGB", (800, 500), (20, 24, 30)).save(buf, format="PNG")
    core.handle_upload(CHAT, "income_statement.png", buf.getvalue())
    core.handle_upload(CHAT, "risk_factors.png", buf.getvalue())
    core.intake_script(CHAT, long_valid_text)

    ws = Workspace.latest_for(core.settings, "EXMPL")
    script = ws.load_long()
    core.approve("long", "EXMPL", ws.workdate, script.content_sha()[:8])
    assert ws.is_approved("long")

    reply = core.swap_key(CHAT, "EXMPL", ws.workdate, "tumbleweed")
    assert "take" in reply.text
    assert ws.broll_overrides()["tumbleweed"] == 1
    assert not ws.is_approved("long"), "swap must reset the approval gate"


def test_execute_job_short_end_to_end(core, xlsx_bytes):
    """The worker path: approved SHORT renders and delivers locally."""
    script_json = json.dumps({
        "ticker": "EXMPL",
        "format": "short",
        "hook_text": "Up 12% and still boring. Good.",
        "audio_script": (
            "EXMPL is up twelve percent because the boring machine beat "
            "earnings again. Five years of growth, cash, and fewer shares. "
            "Signal. I hate that it works."
        ),
        "move_summary": "+12% today · earnings beat",
        "headlines": [
            {"text": "EXMPL beats and raises", "meaning": "Actual numbers, not vibes."},
        ],
        "years": ["FY21", "FY22", "FY23", "FY24", "FY25", "LTM"],
        "numbers": [
            {"label": "FCF", "values": ["", "", "", "$195M", "$228M", "$262M"]},
            {"label": "Shares out", "values": ["", "", "", "199M", "194M", "190M"]},
        ],
        "numbers_comment": "Cash up, share count down. The rarest chart.",
        "conclusion": "Signal. I hate that it works.",
        "annotations": [
            {"target": "numbers", "row_index": 1, "anchor_word": "fewer"},
        ],
    })
    core.new_ticker(CHAT, "EXMPL")
    core.handle_upload(CHAT, "dennis_data.xlsx", xlsx_bytes)
    core.intake_script(CHAT, script_json)
    ws = Workspace.latest_for(core.settings, "EXMPL")
    core.approve("short", "EXMPL", ws.workdate, ws.load_short().content_sha()[:8])

    job = JobRecord(id="test1", kind=JobKind.RENDER_SHORT,
                    ticker="EXMPL", workdate=ws.workdate)
    artifact = core.execute_job(job)
    assert artifact.endswith("short_final.mp4")
    assert job.delivered_link.startswith("file://"), "mock mode delivers locally"
    delivered = core.settings.workspace_dir / "_delivered" / "EXMPL" / ws.workdate / "short_final.mp4"
    assert delivered.exists()


def test_unauthorized_helper():
    from bot.handlers import _authorized

    class FakeCore:
        class settings:
            operator_chat_ids = [111]
    assert _authorized(FakeCore, 111)
    assert not _authorized(FakeCore, 222)

    class EmptyCore:
        class settings:
            operator_chat_ids = []
    assert not _authorized(EmptyCore, 111), "empty allow-list denies everyone"
