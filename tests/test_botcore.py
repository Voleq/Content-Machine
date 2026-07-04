"""End-to-end operator flow WITHOUT Telegram: BotCore consumes strings/
bytes and returns Reply values. Covers the full §9 loop: /new → upload →
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
    return (fixtures_dir / "refinitiv" / "data_refinitiv.xlsx").read_bytes()


def test_new_ticker_creates_workspace_and_context(core):
    reply = core.new_ticker(CHAT, "exmpl")
    assert "Workspace ready: EXMPL" in reply.text
    assert reply.files and reply.files[0].name == "refinitiv_audit_template.xlsx"
    assert core.context.get(CHAT).ticker == "EXMPL"


def test_upload_xlsx_yields_filled_prompts(core, xlsx_bytes):
    core.new_ticker(CHAT, "EXMPL")
    reply = core.handle_upload(CHAT, "data_refinitiv.xlsx", xlsx_bytes)
    assert "saved data_refinitiv.xlsx" in reply.text
    assert len(reply.files) == 2
    short_prompt = next(f for f in reply.files if "short" in f.name).read_text()
    long_prompt = next(f for f in reply.files if "long" in f.name).read_text()
    placeholders = ("{{ticker}}", "{{as_of_date}}", "{{refinitiv_data}}",
                    "{{broll_palette}}", "{{screenshot_files}}")
    for ph in placeholders:
        assert ph not in short_prompt, f"{ph} must be filled"
        assert ph not in long_prompt, f"{ph} must be filled"
    assert "Ticker: EXMPL" in short_prompt
    assert "ps_ratio = 62.0" in short_prompt
    assert "dumpster_fire" in long_prompt  # palette injected


def test_prompts_blocked_without_upload(core):
    core.new_ticker(CHAT, "EXMPL")
    reply = core.prompts_reply(CHAT)
    assert "⛔" in reply.text


def test_short_intake_report_and_approval_flow(core, xlsx_bytes, short_valid_json):
    core.new_ticker(CHAT, "EXMPL")
    core.handle_upload(CHAT, "data_refinitiv.xlsx", xlsx_bytes)
    reply = core.intake_script(CHAT, short_valid_json)
    assert "EXMPL — SHORT — ready to render" in reply.text
    assert "$" in reply.text and "cap" in reply.text
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
    core.handle_upload(CHAT, "data_refinitiv.xlsx", xlsx_bytes)
    core.intake_script(CHAT, short_valid_json)
    ws = Workspace.latest_for(core.settings, "EXMPL")
    reply = core.approve("short", "EXMPL", ws.workdate, "deadbeef")
    assert "changed" in reply.text
    assert not ws.is_approved("short")


def test_malformed_script_reports_friendly_error(core, xlsx_bytes):
    core.new_ticker(CHAT, "EXMPL")
    core.handle_upload(CHAT, "data_refinitiv.xlsx", xlsx_bytes)
    reply = core.intake_script(CHAT, '{"ticker": "EXMPL", "format": "short"')
    assert "⛔" in reply.text and "rejected" in reply.text


def test_long_intake_blocks_on_missing_screenshot(core, xlsx_bytes, long_valid_text):
    core.new_ticker(CHAT, "EXMPL")
    core.handle_upload(CHAT, "data_refinitiv.xlsx", xlsx_bytes)
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
    reply2 = core.intake_script(CHAT, long_valid_text)
    assert "ready to render" in reply2.text
    assert "B-roll:" in reply2.text


def test_swap_key_invalidates_approval_and_rotates(core, xlsx_bytes, long_valid_text):
    from PIL import Image
    import io

    core.new_ticker(CHAT, "EXMPL")
    core.handle_upload(CHAT, "data_refinitiv.xlsx", xlsx_bytes)
    buf = io.BytesIO()
    Image.new("RGB", (800, 500), (20, 24, 30)).save(buf, format="PNG")
    core.handle_upload(CHAT, "income_statement.png", buf.getvalue())
    core.intake_script(CHAT, long_valid_text)

    ws = Workspace.latest_for(core.settings, "EXMPL")
    script = ws.load_long()
    core.approve("long", "EXMPL", ws.workdate, script.content_sha()[:8])
    assert ws.is_approved("long")

    reply = core.swap_key(CHAT, "EXMPL", ws.workdate, "dumpster_fire")
    assert "take" in reply.text
    assert ws.broll_overrides()["dumpster_fire"] == 1
    assert not ws.is_approved("long"), "swap must reset the approval gate"


def test_execute_job_short_end_to_end(core, xlsx_bytes):
    """The worker path: approved SHORT renders and delivers locally."""
    script_json = json.dumps({
        "ticker": "EXMPL",
        "format": "short",
        "verdict": "CASH_COW",
        "hook_text": "Boring. Profitable. Ignored.",
        "audio_script": "Everyone ignores this company. The cash flow statement does not care. Verdict cash cow.",
        "data_block": ["FCF margin: 24%", "Net debt: negative"],
        "visual_directions": [
            {"type": "highlight", "line_index": 0, "color": "green", "anchor_word": "cash"},
            {"type": "stamp", "label": "CASH_COW", "anchor": "end_minus_3"},
        ],
        "cta_text": "Still ignoring it?",
    })
    core.new_ticker(CHAT, "EXMPL")
    core.handle_upload(CHAT, "data_refinitiv.xlsx", xlsx_bytes)
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
