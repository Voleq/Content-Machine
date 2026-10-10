"""End-to-end operator flow WITHOUT Telegram: BotCore consumes strings/
bytes and returns Reply values. Covers the full loop: /long → upload →
prompts → paste script → report → approve → render gate → executed job →
local delivery. All in MOCK_MODE, zero network."""

import json
from pathlib import Path

import pytest

from pipeline.models import JobKind, JobRecord, JobStatus
from pipeline.workspace import Workspace

from bot.handlers import BotCore

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


def test_starting_a_lane_creates_the_workspace_and_context(core):
    reply = core.start_lane(CHAT, "long", "exmpl")
    assert "EXMPL" in reply.text
    assert reply.files and reply.files[0].name == "dennis_data_template.xlsx"
    assert core.context.get(CHAT).ticker == "EXMPL"
    assert core.context.get(CHAT).lane() == "long"
    assert "Refinitiv" not in reply.text


def test_upload_on_a_short_lane_yields_exactly_the_short_prompt(core, xlsx_bytes):
    """One lane, one prompt. The lane is declared, never inferred."""
    core.start_lane(CHAT, "short", "EXMPL")
    reply = core.handle_upload(CHAT, "dennis_data.xlsx", xlsx_bytes)
    assert "saved dennis_data.xlsx" in reply.text
    assert [f.name for f in reply.files] == ["prompt_short.md"]
    short_prompt = reply.files[0].read_text(encoding="utf-8")

    import re as _re
    unfilled = _re.compile(r"\{\{(?!placeholder\}\})[a-z_]+\}\}")
    assert not unfilled.search(short_prompt), "short placeholders filled"

    assert "Ticker: EXMPL" in short_prompt and "ps_ttm = 62.0" in short_prompt
    assert "[history" in short_prompt, "the 5y history feeds the gut check"
    assert "bars-6y" in short_prompt              # the plate catalogue
    # THE MEME AND B-ROLL CATALOGUES ARE NOT HERE, and that is the fix (P3).
    # Both were offered to the SHORT lane while the same prompt, forty lines
    # later, told the writer the inline form of those two tags was LONG-form
    # grammar that a short "draws none of". The structured `meme`/`broll`
    # fields are no better off: no shot template binds them, so the choice
    # validated, was counted on the cost report, and reached no frame.
    assert "dumpster_fire — dumpster fire burning night" not in short_prompt
    assert "harold-quick-flip-became-bagholder" not in short_prompt
    assert "reach no frame" in short_prompt, \
        "the writer is not told why those fields are absent"
    assert "## VOICE BIBLE" in short_prompt and "deadpan" in short_prompt
    assert "Refinitiv" not in short_prompt


def test_upload_on_a_long_lane_yields_exactly_the_angle_prompt(core, xlsx_bytes):
    core.start_lane(CHAT, "long", "EXMPL")
    reply = core.handle_upload(CHAT, "dennis_data.xlsx", xlsx_bytes)
    assert [f.name for f in reply.files] == ["prompt_long_angle.md"]
    angle_prompt = reply.files[0].read_text(encoding="utf-8")

    import re as _re
    unfilled = _re.compile(r"\{\{(?!placeholder\}\})[a-z_]+\}\}")
    assert not unfilled.search(angle_prompt), "angle placeholders filled"

    # the angle prompt is Step 1: ranked angles, no script, gets the full data
    assert "PICK THE ANGLE" in angle_prompt and "pick an angle" in angle_prompt
    assert "ps_ttm = 62.0" in angle_prompt
    assert "★recommended" in angle_prompt
    assert "ASSET PROMPTS" not in angle_prompt, "no tags/assets at the angle step"
    assert "Refinitiv" not in angle_prompt
    # the workspace is now awaiting the operator's angle pick
    ws = Workspace.latest_for(core.settings, "EXMPL")
    assert ws.awaiting_angle()


def test_long_two_step_angle_then_write(core, xlsx_bytes, long_valid_text):
    core.start_lane(CHAT, "long", "EXMPL")
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
    core.start_lane(CHAT, "short", "EXMPL")
    reply = core.handle_upload(CHAT, "dennis_data.xlsx", xlsx_bytes)
    short_prompt = next(f for f in reply.files if "short" in f.name).read_text(encoding="utf-8")
    assert "trending lane" in short_prompt


def test_prompts_blocked_without_upload(core):
    core.start_lane(CHAT, "long", "EXMPL")
    reply = core.prompts_reply(CHAT)
    assert "⛔" in reply.text


def test_short_intake_report_and_approval_flow(core, xlsx_bytes, short_valid_json):
    core.start_lane(CHAT, "short", "EXMPL")
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
    core.start_lane(CHAT, "short", "EXMPL")
    core.handle_upload(CHAT, "dennis_data.xlsx", xlsx_bytes)
    core.intake_script(CHAT, short_valid_json)
    ws = Workspace.latest_for(core.settings, "EXMPL")
    reply = core.approve("short", "EXMPL", ws.workdate, "deadbeef")
    assert "changed" in reply.text
    assert not ws.is_approved("short")


def test_malformed_script_reports_friendly_error(core, xlsx_bytes):
    core.start_lane(CHAT, "short", "EXMPL")
    core.handle_upload(CHAT, "dennis_data.xlsx", xlsx_bytes)
    reply = core.intake_script(CHAT, '{"ticker": "EXMPL", "format": "short",\n'
                                     '"hook_text": "x", "audio_script": "y"}')
    assert "⛔" in reply.text and "rejected" in reply.text


def test_long_intake_blocks_on_missing_screenshot(core, xlsx_bytes, long_valid_text):
    core.start_lane(CHAT, "long", "EXMPL")
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

    raw = ("EXMPL is cheap and hated, which is the only interesting "
           "combination there is, and it is why I am still reading the "
           "filings at three in the morning instead of sleeping like a "
           "person with a balanced life. The revenue line went four "
           "hundred million to four ninety six over five years, which is "
           "technically growth in the way a coma is technically rest. "
           "Here is my account, for context. "
           "[SCREENGRAB: broker-pnl] Twenty five thousand dollars to zero "
           "dollars and zero cents, which I mention not for sympathy but "
           "because it is the only credential that matters in this "
           "business. I will be up at three a.m. either way. "
           "See you at the next filing.")
    core.start_lane(CHAT, "long", "EXMPL")
    core.handle_upload(CHAT, "dennis_data.xlsx", xlsx_bytes)

    # `assets/custom/` is the SHARED library, not a tmp dir — it has to be,
    # because that is where the renderer looks. A run killed between the
    # upload and the cleanup below therefore leaves a file that makes this
    # test pass for the wrong reason next time, so it is cleared going in as
    # well as coming out.
    custom = core.settings.assets_dir / "custom"
    for stale in custom.glob("broker-pnl.*"):
        stale.unlink()

    reply = core.intake_script(CHAT, raw)
    assert "BLOCKED" in reply.text
    assert "SCREENGRAB" in reply.text and "broker-pnl" in reply.text

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

    core.start_lane(CHAT, "long", "EXMPL")
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

    # Swap buttons address an OCCURRENCE by index now (G4, G5): the payload
    # text does not fit Telegram's 64-byte callback limit, and keying on it
    # swapped every beat that shared a palette key.
    slots = core.swappable_slots(ws.load_long())
    i = next(n for n, (_tag, payload) in enumerate(slots)
             if payload == "tumbleweed")
    reply = core.swap_key(CHAT, "EXMPL", ws.workdate, str(i))
    assert "tumbleweed" in reply.text and "take" in reply.text
    assert ws.broll_overrides()[f"{slots[i][0]}:{i}"] == 1
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
    core.start_lane(CHAT, "short", "EXMPL")
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
    # The SHORT's by-products, which it used to ship without: `/upload
    # short` had no cover and no captions to send, and its retention could
    # never be joined to a sentence. Under the SHORT's own names, so a LONG
    # in the same folder keeps its own.
    for name in ("EXMPL.short.srt", "words_short.json", "thumbnail_tall.png",
                 "upload_package_short.txt", "companion_short.html",
                 "EXMPL.short.transcript.txt"):
        assert (ws.path / name).exists(), name
        assert (delivered.parent / name).exists() or name == "words_short.json", name
    assert not (ws.path / "EXMPL.srt").exists(), "the LONG's name is the LONG's"


def test_a_final_on_synthetic_prices_stops_before_the_voice(core, xlsx_bytes,
                                                            short_valid_json,
                                                            tmp_path):
    """Approval ran the price gate, but the final renders later on a fresh
    fetch. A feed that died in between must stop the job before the paid
    voice, not draw a random walk into a video that ships."""
    from pipeline.prices import PriceSeries

    core.start_lane(CHAT, "short", "EXMPL")
    core.handle_upload(CHAT, "dennis_data.xlsx", xlsx_bytes)
    core.intake_script(CHAT, short_valid_json)
    ws = Workspace.latest_for(core.settings, "EXMPL")
    core.approve("short", "EXMPL", ws.workdate, ws.load_short().content_sha()[:8])

    core.settings = core.settings.model_copy(update={
        "mock_mode": False, "cache_dir": tmp_path / "c"})
    # what `get_price_history` returns when the live feed is down
    cdir = core.settings.cache_dir / "prices"
    cdir.mkdir(parents=True)
    fake = PriceSeries(ticker="EXMPL", dates=["2026-01-01", "2026-01-02"],
                       closes=[10.0, 10.4], source="synthetic", degraded=True)
    (cdir / f"EXMPL_{core.settings.price_history_days}.json").write_text(
        fake.to_json(), encoding="utf-8")

    def no_voice(*_a, **_k):
        raise AssertionError("the voice was paid for")
    core.tts.synthesize = no_voice
    job = JobRecord(id="synthetic", kind=JobKind.RENDER_SHORT,
                    ticker="EXMPL", workdate=ws.workdate)
    with pytest.raises(RuntimeError, match="SYNTHETIC PRICE DATA"):
        core.execute_job(job)

    # MOCK_MODE is synthetic by construction, so it warns and renders.
    core.settings = core.settings.model_copy(update={"mock_mode": True})
    core._refuse_synthetic_prices(ws.load_short())


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


# --------------------------------------------------------------------------
# GROUP E — delivery. Everything below was computed by the delivery layer and
# read by nobody.
# --------------------------------------------------------------------------


def test_the_telegram_backend_actually_sends_the_video(core, tmp_path):
    """E1: `send_file` was written by the telegram backend and read nowhere,
    so `DELIVERY_BACKEND=telegram` reported success, reported "(sent in
    chat)", and delivered nothing."""
    from pipeline.delivery import DeliveryResult
    from pipeline.models import JobKind, JobRecord

    artifact = tmp_path / "long_final.mp4"
    artifact.write_bytes(b"the video")
    sent: list = []
    core.file_pusher = lambda path, caption="": sent.append(Path(path))

    job = JobRecord(id="e1", kind=JobKind.RENDER_LONG, ticker="EXMPL",
                    workdate="2026-09-12")
    core._finish(job, DeliveryResult(backend="telegram", link="(sent in chat)",
                                     send_file=artifact))

    assert sent == [artifact], "the file has to leave the machine"


def test_by_product_links_and_credits_reach_the_operator(core, tmp_path):
    """E2: `extra_links` and `note` were populated and never read, so the
    thumbnail, the .srt, the package and the credits were uploaded and the
    operator was never told where."""
    from pipeline.delivery import DeliveryResult
    from pipeline.models import JobKind, JobRecord

    result = DeliveryResult(
        backend="gdrive", link="https://drive/final",
        extra_links={"EXMPL.srt": "https://drive/srt",
                     "thumbnail.png": "https://drive/thumb"},
        note="Credits:\n- Video by Alex on Pexels")

    job = JobRecord(id="e2", kind=JobKind.RENDER_LONG, ticker="EXMPL",
                    workdate="2026-09-12")
    core._finish(job, result)
    lines = core._byproduct_lines(result)

    assert any("EXMPL.srt" in ln and "drive/srt" in ln for ln in lines)
    assert any("thumbnail.png" in ln for ln in lines)
    assert any("Alex on Pexels" in ln for ln in lines)


def test_a_failed_push_tells_the_operator(core, tmp_path):
    """E3: `push_file` caught the exception and logged it, so the operator
    saw nothing at all — for a proof MP4 they were waiting on."""
    said: list[str] = []
    core.notify = lambda text: said.append(text)

    def broken(path, caption=""):
        raise RuntimeError("file is too big")

    core.file_pusher = broken
    f = tmp_path / "proof.mp4"
    f.write_bytes(b"x")

    assert core.push_file(f, "proof") is False
    assert said and "too big" in said[0]


def test_a_proof_in_mock_mode_blames_mock_mode_for_the_hum(core, xlsx_bytes,
                                                          short_valid_json):
    """It said Piper was not installed, which sent an operator who had
    installed Piper looking for a fault that was MOCK_MODE all along."""
    core.start_lane(CHAT, "short", "EXMPL")
    core.handle_upload(CHAT, "dennis_data.xlsx", xlsx_bytes)
    core.intake_script(CHAT, short_valid_json)
    kind, text, _ = core.render_request("EXMPL", "short", proof=True)
    assert kind is not None
    assert "MOCK_MODE is on" in text and "not installed" not in text


def test_a_drive_final_is_not_world_readable_by_default(settings):
    """E4: an anyone-with-link permission was applied unconditionally to
    every final render of an unpublished video."""
    import inspect

    from pipeline import delivery

    assert settings.gdrive_link_anyone is False
    src = inspect.getsource(delivery.GDriveBackend.upload)
    assert "if self.settings.gdrive_link_anyone:" in src


def test_upload_can_reach_the_short_when_a_long_exists_too(core, xlsx_bytes,
                                                           short_valid_json):
    """E5: `/upload` could only reach whichever format the folder "was"."""
    core.start_lane(CHAT, "short", "EXMPL")
    core.handle_upload(CHAT, "dennis_data.xlsx", xlsx_bytes)
    core.intake_script(CHAT, short_valid_json)
    ws = Workspace.latest_for(core.settings, "EXMPL")
    (ws.path / "short_final.mp4").write_bytes(b"short")
    (ws.path / "long_final.mp4").write_bytes(b"long")

    fmt, video, _ = core._upload_target(ws, "short")
    assert fmt == "short" and video.name == "short_final.mp4"
    fmt, video, _ = core._upload_target(ws, "long")
    assert fmt == "long" and video.name == "long_final.mp4"


def test_upload_can_reach_a_repurposed_clip(core, xlsx_bytes):
    """E5: the path was hard-coded to the two finals, so a repurposed clip —
    a finished, deliverable artefact — could not be uploaded at all."""
    core.start_lane(CHAT, "long", "EXMPL")
    core.handle_upload(CHAT, "dennis_data.xlsx", xlsx_bytes)
    ws = Workspace.latest_for(core.settings, "EXMPL")
    clip = ws.path / "short_repurposed_0.mp4"
    clip.write_bytes(b"clip")

    fmt, video, _ = core._upload_target(ws, "clip")
    assert fmt == "clip" and video == clip


def test_a_short_runtime_is_read_from_the_manifest_the_renderer_writes(
        core, xlsx_bytes):
    """E5: it read `render_short_manifest.json` under `"duration"`; the
    renderer writes `short_final.manifest.json` under `"duration_s"`. Both
    wrong, so SHORT runtime was always 0.0 in the upload package and the
    YouTube record."""
    core.start_lane(CHAT, "short", "EXMPL")
    core.handle_upload(CHAT, "dennis_data.xlsx", xlsx_bytes)
    ws = Workspace.latest_for(core.settings, "EXMPL")
    (ws.path / "short_final.manifest.json").write_text(
        json.dumps({"duration_s": 63.5}), encoding="utf-8")

    assert core._render_duration(ws, "short") == 63.5


# --------------------------------------------------------------------------
# F2 — the intake paths ran synchronously inside the handler coroutine, so
# nothing else on the event loop answered until they finished.
# --------------------------------------------------------------------------


def test_the_blocking_intake_paths_run_off_the_event_loop():
    """`intake_script` downloads every clip, runs ffmpeg, hits EDGAR, drives
    headless Chromium and makes LLM calls. While it ran, `/status`,
    `/cancel` and the render-finished push all waited."""
    import ast
    import inspect

    from bot import commands, handlers

    trees = [ast.parse(inspect.getsource(m)) for m in (handlers, commands)]

    blocking = {"intake_script", "handle_upload", "swap_key", "approve",
                "angle_pick", "upload_command", "render_request"}
    offenders: list[str] = []
    def on_the_core(fn) -> bool:
        """`core.x(...)` / `c.core.x(...)` — BotCore's own blocking method,
        not an async wrapper of the same name (`cmds.handle_upload`)."""
        owner = fn.value
        return ((isinstance(owner, ast.Name) and owner.id == "core")
                or (isinstance(owner, ast.Attribute) and owner.attr == "core"))

    for node in (n for tree in trees for n in ast.walk(tree)):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        # A call inside a lambda handed to `to_thread` runs in the thread.
        deferred = {id(c) for lam in ast.walk(node) if isinstance(lam, ast.Lambda)
                    for c in ast.walk(lam)}
        for call in ast.walk(node):
            if not isinstance(call, ast.Call) or id(call) in deferred:
                continue
            fn = call.func
            # `core.intake_script(...)` awaited directly is the bug; the same
            # name inside `asyncio.to_thread(core.intake_script, ...)` is the
            # fix, and appears as an ARGUMENT rather than as the callee.
            if (isinstance(fn, ast.Attribute) and fn.attr in blocking
                    and on_the_core(fn)):
                offenders.append(f"{node.name} calls {fn.attr}() inline")
    assert not offenders, "on the event loop:\n  " + "\n  ".join(offenders)


def test_a_slow_paste_is_acknowledged_before_the_work_starts(core):
    """The operator should not be watching a silent bot for a minute."""
    import inspect

    from bot import commands

    src = inspect.getsource(commands.handle_text)
    assert "asyncio.to_thread" in src
    assert "got it" in src, "the acknowledgement has to actually be sent"


# --------------------------------------------------------------------------
# The Approve button and the world underneath it (G8).
#
# These build the approval state directly rather than going through
# `intake_script`, so the re-check is tested without the cost report's
# dependency on an installed kit.
# --------------------------------------------------------------------------


def _ready_to_approve(core, xlsx_bytes, short_valid_json):
    """A workspace with a saved SHORT and a report on file — the state the
    Approve button is drawn on."""
    from pipeline.models import ShortScript

    core.start_lane(CHAT, "short", "EXMPL")
    core.handle_upload(CHAT, "dennis_data.xlsx", xlsx_bytes)
    ws = Workspace.latest_for(core.settings, "EXMPL")
    # The model rather than the parser: `parse_short_script` checks the
    # script's visual keys against the installed kit, and what is under test
    # here is the approval gate, not the kit.
    script = ShortScript.model_validate_json(short_valid_json)
    ws.save_short(script, short_valid_json)
    (ws.path / "report_short.txt").write_text("the report as written",
                                              encoding="utf-8")
    return ws, script.content_sha()[:8]


def test_approval_refuses_a_gate_that_has_turned_blocking_since_the_report(
        core, xlsx_bytes, short_valid_json, monkeypatch):
    """The hash pins the CONTENT, and nothing else. A button drawn on an
    approvable report stayed approvable after the world underneath it
    changed — freshness rolling over, a screengrab deleted — and /render
    then reads `is_approved()` and spends."""
    from pipeline.gates import Finding, GateReport

    ws, sha8 = _ready_to_approve(core, xlsx_bytes, short_valid_json)

    def _blocked(*a, **k):
        report = GateReport()
        report.findings += report.record("freshness", [Finding(
            gate="freshness", severity="block",
            message="the workbook is older than DATA_MAX_AGE_DAYS")])
        return report

    monkeypatch.setattr("bot.handlers.run_gates", _blocked)
    reply = core.approve("short", "EXMPL", ws.workdate, sha8)

    assert "Not approved" in reply.text
    assert "DATA_MAX_AGE_DAYS" in reply.text
    assert not ws.is_approved("short"), "nothing may be spendable after this"


def test_a_battery_that_cannot_run_does_not_refuse_the_approval(
        core, xlsx_bytes, short_valid_json, monkeypatch):
    """A missing kit is not evidence that the script is bad, and refusing
    every approval because of one would be worse than the bug being fixed."""
    ws, sha8 = _ready_to_approve(core, xlsx_bytes, short_valid_json)

    def _explode(*a, **k):
        raise RuntimeError("no plates-registry.json")

    monkeypatch.setattr("bot.handlers.run_gates", _explode)
    assert "approved" in core.approve("short", "EXMPL", ws.workdate, sha8).text
    assert ws.is_approved("short")


def test_the_approval_recheck_does_not_pay_for_a_network_call(
        core, xlsx_bytes, short_valid_json, monkeypatch):
    """The skeptic is the only pass here that costs one, and every finding it
    returns is a warning — so it can never be what refuses this."""
    from pipeline.gates import GateReport

    ws, sha8 = _ready_to_approve(core, xlsx_bytes, short_valid_json)
    seen: dict = {}

    def _spy(script, settings, **kw):
        seen.update(kw)
        return GateReport()

    monkeypatch.setattr("bot.handlers.run_gates", _spy)
    core.approve("short", "EXMPL", ws.workdate, sha8)
    assert seen.get("skeptic") is False
    assert ws.is_approved("short")


# ------------------------------------------------ the batch, run for real


def _approved_short(core, xlsx_bytes, short_valid_json):
    core.start_lane(CHAT, "short", "EXMPL")
    core.handle_upload(CHAT, "dennis_data.xlsx", xlsx_bytes)
    core.intake_script(CHAT, short_valid_json)
    ws = Workspace.latest_for(core.settings, "EXMPL")
    core.approve("short", "EXMPL", ws.workdate,
                 ws.load_short().content_sha()[:8])
    return ws


def test_the_batch_submits_what_it_holds_and_closes_it(
        core, xlsx_bytes, short_valid_json):
    """One runner for `/batch run` and the overnight window."""
    import asyncio

    from pipeline.jobs import RenderJobQueue
    from pipeline.standing import BatchQueue

    _approved_short(core, xlsx_bytes, short_valid_json)
    core.queue = RenderJobQueue(core.settings, lambda job: "")
    BatchQueue(core.settings).add("EXMPL", "short")

    queued, skipped, text = asyncio.run(core.run_batch())

    assert queued == 1 and skipped == []
    assert "1 queued" in text
    # Open until ITS render is done: a render that fails overnight is still
    # queued tomorrow rather than gone from the batch.
    (entry,) = BatchQueue(core.settings).pending()
    assert entry.job_id
    core.queue.store.update(entry.job_id,
                            lambda j: setattr(j, "status", JobStatus.DONE))
    queued, _skipped, _text = asyncio.run(core.run_batch())
    assert queued == 0
    assert BatchQueue(core.settings).pending() == []


def test_a_batch_entry_already_rendering_is_not_rendered_twice(
        core, xlsx_bytes, short_valid_json):
    """Left pending, it submitted a second copy the moment the first one
    finished — a duplicate render and a duplicate delivery."""
    import asyncio

    from pipeline.jobs import RenderJobQueue
    from pipeline.standing import BatchQueue

    ws = _approved_short(core, xlsx_bytes, short_valid_json)
    core.queue = RenderJobQueue(core.settings, lambda job: "")
    first = asyncio.run(core.queue.submit(JobKind.RENDER_SHORT, "EXMPL",
                                          ws.workdate))
    BatchQueue(core.settings).add("EXMPL", "short")

    queued, skipped, _text = asyncio.run(core.run_batch())

    assert queued == 0 and len(skipped) == 1
    assert "following" in skipped[0]
    # The entry follows the render already running, and closes with it —
    # the first one finishing does not start a second.
    (entry,) = BatchQueue(core.settings).pending()
    assert entry.job_id == first.id
    core.queue.store.update(first.id,
                            lambda j: setattr(j, "status", JobStatus.DONE))
    queued, _skipped, _text = asyncio.run(core.run_batch())
    assert queued == 0
    assert BatchQueue(core.settings).pending() == []


def test_the_overnight_window_is_scheduled(core):
    from bot.handlers import schedule_batch

    class _JobQueue:
        def __init__(self):
            self.jobs = []

        def run_repeating(self, callback, **kwargs):
            self.jobs.append(kwargs.get("name"))

    class _App:
        job_queue = _JobQueue()

    app = _App()
    schedule_batch(app, core)
    assert app.job_queue.jobs == ["overnight_batch"]


def test_a_delivery_carries_its_own_formats_record(core):
    """A folder holding both lanes answered a SHORT's delivery with the
    LONG's provenance, because the LONG's manifest came first in a list."""
    import json

    from pipeline.models import JobRecord
    from pipeline.provenance import Provenance

    ws = Workspace(core.settings, "EXMPL", "2026-09-12")
    ws.path.mkdir(parents=True, exist_ok=True)
    for name, fmt in (("render_long_manifest.json", "long"),
                      ("short_final.manifest.json", "short")):
        record = Provenance(ticker="EXMPL", fmt=fmt, workdate="2026-09-12")
        (ws.path / name).write_text(
            json.dumps({"provenance": record.to_json()}), encoding="utf-8")

    short = JobRecord(id="s", chat_id=1, ticker="EXMPL",
                      workdate="2026-09-12", kind=JobKind.RENDER_SHORT)
    long_ = JobRecord(id="l", chat_id=1, ticker="EXMPL",
                      workdate="2026-09-12", kind=JobKind.RENDER_LONG)
    assert "EXMPL · SHORT" in core._provenance_text(short)
    assert "EXMPL · LONG" in core._provenance_text(long_)


def test_retention_reads_the_final_cut_not_a_draft(core):
    """`/shots` and `/stillness` took the first `*manifest*.json` in sorted
    order, which in a folder holding a /draft is the draft's."""
    ws = Workspace(core.settings, "EXMPL", "2026-09-12")
    ws.path.mkdir(parents=True, exist_ok=True)
    for name in ("render_long_draft_manifest.json",
                 "render_long_manifest.json", "short_final.manifest.json"):
        (ws.path / name).write_text("{}", encoding="utf-8")

    assert core._manifest_for(ws, "long").name == "render_long_manifest.json"
    assert core._manifest_for(ws, "short").name == "short_final.manifest.json"
    (ws.path / "render_long_manifest.json").unlink()
    assert core._manifest_for(ws, "long") is None
    assert core._manifest_for(ws, "long", trials=True).name == \
        "render_long_draft_manifest.json"
