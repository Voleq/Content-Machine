"""The page's workspace screen: one video's ten steps as data (bot/panel_views)."""

from __future__ import annotations

import io
import json

import pytest
from PIL import Image

from bot.handlers import BotCore
from bot.panel import Panel
from bot.panel_views import parse_finding, video_view
from pipeline.workspace import Workspace

CHAT = 5150


@pytest.fixture()
def core(settings):
    small = settings.model_copy(update={
        "short_width": 540, "short_height": 960,
        "long_width": 640, "long_height": 360,
        "operator_chat_ids": [CHAT],
    })
    return BotCore(small)


@pytest.fixture()
def panel(core):
    return Panel(core, loop=None)


@pytest.fixture()
def xlsx_bytes(fixtures_dir) -> bytes:
    return (fixtures_dir / "company_data" / "dennis_data.xlsx").read_bytes()


def _approved_short(core, xlsx_bytes, short_valid_json) -> Workspace:
    core.start_lane(CHAT, "short", "EXMPL")
    core.handle_upload(CHAT, "dennis_data.xlsx", xlsx_bytes)
    core.intake_script(CHAT, short_valid_json)
    ws = Workspace.latest_for(core.settings, "EXMPL")
    core.approve("short", "EXMPL", ws.workdate,
                 ws.load_short().content_sha()[:8])
    return ws


def _status(view) -> dict:
    return {s["id"]: s["status"] for s in view["steps"]}


def test_empty_video_opens_on_data(core, panel):
    core.start_lane(CHAT, "short", "EXMPL")
    ws = core.context.get(CHAT)
    view = video_view(panel, "EXMPL", ws.workdate)
    assert view["now"] == "data"
    status = _status(view)
    assert status["data"] == "now"
    assert [s["id"] for s in view["steps"]] == [
        "data", "angle", "write", "check", "proof", "approve", "voice",
        "render", "upload", "live"]
    assert all(v in ("todo", "skip") for k, v in status.items() if k != "data")
    assert not any("error" in view[s["id"]] for s in view["steps"])


def test_short_has_no_angle_step(core, panel):
    core.start_lane(CHAT, "short", "EXMPL")
    ws = core.context.get(CHAT)
    assert _status(video_view(panel, "EXMPL", ws.workdate))["angle"] == "skip"
    core.start_lane(CHAT, "long", "EXMPL")
    ws = core.context.get(CHAT)
    assert _status(video_view(panel, "EXMPL", ws.workdate))["angle"] != "skip"


def test_a_bad_report_breaks_only_its_step(core, panel, xlsx_bytes,
                                           short_valid_json, monkeypatch):
    ws = _approved_short(core, xlsx_bytes, short_valid_json)
    view = video_view(panel, "EXMPL", ws.workdate)
    assert view["data"]["figures"]
    assert "error" not in view["check"]

    import bot.panel_views as pv

    def broken(_v):
        raise ValueError("half-written")

    monkeypatch.setitem(pv._BUILDERS, "check", broken)
    view = video_view(panel, "EXMPL", ws.workdate)
    assert view["check"] == {"error": "ValueError: half-written"}
    assert [s["summary"] for s in view["steps"] if s["id"] == "check"] == [
        "could not be read"]
    assert "error" not in view["data"] and "error" not in view["approve"]


def test_findings_carry_their_line(core, panel, xlsx_bytes, short_valid_json):
    f = parse_finding("[numbers] L3: a price with no source\n    “up 40%”",
                      "block")
    assert (f["gate"], f["line"], f["message"], f["excerpt"]) == (
        "numbers", 3, "a price with no source", "up 40%")
    plain = parse_finding("could not parse the hook", "warn")
    assert plain["gate"] == "" and plain["message"] == "could not parse the hook"

    ws = _approved_short(core, xlsx_bytes, short_valid_json)
    narration = ws.load_short().audio_script
    first = narration.split(".")[0].strip()
    rep_path = ws.path / "report_short.json"
    rep = json.loads(rep_path.read_text(encoding="utf-8"))
    rep["warnings"] = [f"[tone] L1: too flat\n    “{first[:30]}”"]
    rep_path.write_text(json.dumps(rep), encoding="utf-8")
    check = video_view(panel, "EXMPL", ws.workdate)["check"]
    found = [x for x in check["findings"] if x["gate"] == "tone"]
    assert found and found[0]["line"] == 1
    assert found[0]["raw_line"] >= 1
    assert check["lines"] and check["lines"][0]["n"] == 1


def test_no_key_and_no_state_paths_in_the_view(core, panel, xlsx_bytes,
                                               short_valid_json):
    ws = _approved_short(core, xlsx_bytes, short_valid_json)
    (ws.path / "short_final.mp4").write_bytes(b"\0" * 64)
    view = video_view(panel, "EXMPL", ws.workdate)
    text = json.dumps(view)
    assert panel.token not in text
    assert str(core.settings.state_dir) not in text
    assert view["render"]["final_url"].startswith("/api/file?path=")
    assert view["upload"]["downloads"][0]["name"] == "short_final.mp4"


def test_a_path_is_not_a_video(panel):
    assert video_view(panel, "..", "../state")["error"] == "no such video"
    assert video_view(panel, "EXMPL", "../../state")["steps"] == []


def test_upload_package_as_fields(core, panel, xlsx_bytes, short_valid_json):
    ws = _approved_short(core, xlsx_bytes, short_valid_json)
    assert video_view(panel, "EXMPL", ws.workdate)["upload"]["ready"] is False
    (ws.path / "short_final.mp4").write_bytes(b"\0" * 64)
    up = video_view(panel, "EXMPL", ws.workdate)["upload"]
    assert up["ready"] and up["titles"] and up["description"]
    assert up["tags"] and isinstance(up["pinned"], str)
    assert any("synthetic" in line.lower() for line in up["checklist"])
    data = [b["data"] for row in up["buttons"] for b in row]
    assert f"u|s|EXMPL|{ws.workdate}" in data
    # The link is saved against this folder, not the ticker's newest.
    assert up["mark_hint"] == f"/publish mark EXMPL@{ws.workdate} short "


def test_a_final_with_no_script_still_opens_its_upload_step(core, panel):
    """A final with no script on file (one copied in by hand): the files
    download, the fields are empty, and the step is not an error."""
    core.start_lane(CHAT, "short", "EXMPL")
    ws = core.context.get(CHAT)
    (ws.path / "short_final.mp4").write_bytes(b"\0" * 64)
    up = video_view(panel, "EXMPL", ws.workdate)["upload"]
    assert "error" not in up
    assert up["ready"] and up["titles"] == [] and up["description"] == ""
    assert up["downloads"][0]["name"] == "short_final.mp4"


def _png(colour) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 36), colour).save(buf, "PNG")
    return buf.getvalue()


def test_his_thumbnail_replaces_the_cover(core, panel, xlsx_bytes,
                                          short_valid_json):
    ws = _approved_short(core, xlsx_bytes, short_valid_json)
    shipped = ws.path / "thumbnail_tall.png"
    shipped.write_bytes(_png("blue"))
    reply = core.set_thumbnail("EXMPL", ws.workdate, "short", _png("red"))
    assert "your cover" in reply.text
    assert Image.open(shipped).getpixel((1, 1)) == (255, 0, 0)
    assert Image.open(ws.path / "cover_bot_short.png").getpixel((1, 1)) == (0, 0, 255)

    # A re-render draws the bot's again; his goes back on top.
    from pipeline.thumbnail import _keep_his_cover
    shipped.write_bytes(_png("green"))
    _keep_his_cover(ws, "short")
    assert Image.open(shipped).getpixel((1, 1)) == (255, 0, 0)

    assert "❌" in core.set_thumbnail("EXMPL", ws.workdate, "short", b"not a picture").text
    assert "bot's cover" in core.set_thumbnail("EXMPL", ws.workdate, "short", b"").text
    assert Image.open(shipped).getpixel((1, 1)) == (0, 128, 0)
    assert "❌" in core.set_thumbnail("..", "../state", "short", _png("red")).text


def test_every_bot_upload_declares_synthetic(settings):
    from datetime import datetime, timedelta, timezone

    from pipeline.publish import UploadPackage
    from pipeline.youtube import build_body

    pkg = UploadPackage(ticker="EXMPL", titles=["t"], description="d", tags=["x"])
    later = datetime.now(timezone.utc) + timedelta(days=1)
    for kwargs in ({}, {"title": "other"}, {"publish_at": later},
                   {"settings": settings}):
        assert build_body(pkg, **kwargs)["status"]["containsSyntheticMedia"] is True


def test_live_before_upload_is_empty(core, panel, xlsx_bytes, short_valid_json):
    ws = _approved_short(core, xlsx_bytes, short_valid_json)
    live = video_view(panel, "EXMPL", ws.workdate)["live"]
    assert live["video"] is None and live["curve"] == [] and live["lines"] == []


def test_live_rows_from_a_logged_video(core, panel, xlsx_bytes, short_valid_json):
    from pipeline.youtube import VideoLog, VideoRecord

    ws = _approved_short(core, xlsx_bytes, short_valid_json)
    (ws.path / "short_final.mp4").write_bytes(b"\0" * 64)
    VideoLog(core.settings).record(VideoRecord(
        ticker="EXMPL", video_id="abc123", title="t", privacy="public",
        uploaded_at="2026-10-01T10:00:00Z", workdate=ws.workdate, fmt="short",
        duration_s=40.0, chapters=[("0:00", "Hook"), ("0:20", "Turn")],
        synthetic_declared=True,
        retention={"rows": [{"elapsed_ratio": 0.0, "watch_ratio": 1.0},
                            {"elapsed_ratio": 0.5, "watch_ratio": 0.6}]}))
    view = video_view(panel, "EXMPL", ws.workdate)
    live = view["live"]
    assert live["video"]["video_id"] == "abc123"
    assert live["curve"] == [{"x": 0.0, "y": 1.0}, {"x": 0.5, "y": 0.6}]
    assert live["chapters"][1] == {"t": 20.0, "title": "Turn"}
    assert live["synthetic_declared"] is True
    assert view["now"] == "live"


def test_strip_is_cached(tmp_path):
    import subprocess

    from pipeline.proof_review import frame_strip

    video = tmp_path / "short_proof.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                    "-i", "testsrc=size=160x90:rate=10:duration=2", "-pix_fmt",
                    "yuv420p", str(video)], check=True)
    rows = frame_strip(video, n=4)
    assert [t for t, _ in rows] == [0.25, 0.75, 1.25, 1.75]
    assert all(p.is_file() for _, p in rows)
    first = rows[0][1].stat().st_mtime_ns
    again = frame_strip(video, n=4)
    assert again == rows and again[0][1].stat().st_mtime_ns == first


def test_notes_sorted_and_numbered(core, xlsx_bytes, short_valid_json):
    ws = _approved_short(core, xlsx_bytes, short_valid_json)
    assert "none yet" in core.proof_notes(CHAT, []).text
    core.proof_notes(CHAT, ["add", "0:30", "the", "chart", "is", "late"])
    core.proof_notes(CHAT, ["add", "12.4", "mouth", "drifts"])
    reply = core.proof_notes(CHAT, [])
    assert reply.text.endswith("1. 0:12 mouth drifts\n2. 0:30 the chart is late")
    core.proof_notes(CHAT, ["drop", "1"])
    assert "1. 0:30 the chart is late" in core.proof_notes(CHAT, []).text
    assert "❌" in core.proof_notes(CHAT, ["drop", "9"]).text
    from pipeline.proof_review import load_notes
    assert [n["text"] for n in load_notes(ws.path, "short")] == ["the chart is late"]


def test_fault_list_text():
    from pipeline.proof_review import fault_list

    assert fault_list([{"t": 61.9, "text": "cut too early"},
                       {"t": 125, "text": "plate wrong"}]) == (
        "1. 1:01 cut too early\n2. 2:05 plate wrong")
    assert fault_list([]) == ""


def test_a_short_is_read_by_sentence(core, panel, xlsx_bytes, short_valid_json):
    from bot.panel_views import short_sentences

    rows = short_sentences('{"audio_script": "Up 29%. A [PLATE: a | caption=x. y] '
                           'deal, \\"signed\\"? Sure!", "x": 1}')
    assert [r["text"] for r in rows] == [
        "Up 29%.", 'A [PLATE: a | caption=x. y] deal, "signed"?', "Sure!"]
    assert rows[1]["raw"] == 'A [PLATE: a | caption=x. y] deal, \\"signed\\"?'

    ws = _approved_short(core, xlsx_bytes, short_valid_json)
    check = video_view(panel, "EXMPL", ws.workdate)["check"]
    assert check["mode"] == "sentences"
    raw = ws.raw_script("short")
    assert all(ln["raw"] in raw for ln in check["lines"])
    assert check["data_lines"] and not any(
        '"audio_script"' in ln["text"] for ln in check["data_lines"])
    first = check["lines"][0]
    reply = core.edit_script(CHAT, [], mode="replace",
                             raw_args=f"{first['raw']} => Shares jumped today.")
    assert "⛔" not in reply.text
    assert "Shares jumped today." in ws.raw_script("short")


def test_the_upload_step_says_where_the_end_screen_goes(tmp_path):
    """V3: the long's final records its end screen; Studio's checklist says
    from when and on which side the boxes go."""
    from types import SimpleNamespace

    from bot.panel_views import _end_screen_line

    (tmp_path / "render_long_manifest.json").write_text(json.dumps(
        {"end_screen": {"start": 581.0, "end": 601.2, "side": "right", "clear": True}}),
        encoding="utf-8")
    v = SimpleNamespace(fmt="long", ws=SimpleNamespace(path=tmp_path))
    line = _end_screen_line(v)
    assert line.startswith("End screen: from 9:41") and "right side" in line
    assert _end_screen_line(SimpleNamespace(fmt="short", ws=v.ws)) == ""
    (tmp_path / "render_long_manifest.json").write_text("{}", encoding="utf-8")
    assert _end_screen_line(v) == ""


def test_the_proof_step_says_what_the_render_found(tmp_path):
    """V5 and V7 on the page: the proof's manifest names small type and a
    recent video it looks like; an old manifest says nothing."""
    from types import SimpleNamespace

    from bot.panel_views import _proof_checks

    (tmp_path / "render_long_proof_manifest.json").write_text(json.dumps({
        "phone_type": [{"t": 134.0, "plate": "charts/bars-6y", "slot": "axis-1",
                        "text": "Revenue, FY21 to LTM", "phone_px": 5.3}],
        "look_alike": [{"video": "AAA 2026-10-20", "what": "plates", "ratio": 0.82}],
    }), encoding="utf-8")
    v = SimpleNamespace(fmt="long", ws=SimpleNamespace(path=tmp_path))
    got = _proof_checks(v, tmp_path / "render_long_proof.mp4")
    assert len(got) == 2
    assert got[0].startswith("📱") and "2:14" in got[0]
    assert got[1].startswith("🔁") and "AAA 2026-10-20" in got[1]
    assert _proof_checks(v, None) == []
    (tmp_path / "short_proof.manifest.json").write_text("{}", encoding="utf-8")
    short = SimpleNamespace(fmt="short", ws=v.ws)
    assert _proof_checks(short, tmp_path / "short_proof.mp4") == []
