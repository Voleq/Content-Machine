import json

import pytest

from pipeline.render_common import ffprobe_json, run_ffmpeg
from pipeline.repurpose import pick_best_window, repurpose_short_from_long
from pipeline.thumbnail import make_thumbnail, shock_metric
from pipeline.tts import mock_words

# ------------------------------------------------------------ window picker


def _cue(t, kind):
    return {"t": t, "kind": kind}


def test_window_prefers_dense_cluster():
    cues = (
        [_cue(10, "clip")]
        + [_cue(t, "clip") for t in (200, 205, 210, 215)]
        + [_cue(220, "filing"), _cue(230, "sound"), _cue(245, "meme")]
    )
    start, end = pick_best_window(cues, duration=300, window_s=58)
    assert 190 <= start <= 220
    assert end - start == pytest.approx(58)
    assert end <= 300


def test_window_whole_video_when_short():
    assert pick_best_window([_cue(3, "clip")], duration=40) == (0.0, 40.0)


def test_window_snaps_to_word_boundary():
    text = " ".join(["word"] * 200)
    words = mock_words(text, 300.0)
    cues = [_cue(120, "meme"), _cue(118, "clip"), _cue(125, "filing")]
    start, end = pick_best_window(cues, 300.0, window_s=58, words=words)
    assert any(abs(w.start - start) < 1e-6 for w in words), "start must be a word start"


def test_window_meme_payoff_bias():
    # two equally dense windows; the one whose meme lands near the END wins
    cues_a = [_cue(20, "clip"), _cue(25, "clip"), _cue(70, "meme")]
    start, end = pick_best_window(cues_a, duration=200, window_s=58)
    assert start <= 20 and end >= 70  # window covering the payoff


# ------------------------------------------------------------- repurposing


def test_repurpose_crops_to_9_16(settings, tmp_path):
    small = settings.model_copy(update={"short_width": 306, "short_height": 544})
    src = tmp_path / "long_final.mp4"
    run_ffmpeg([
        "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=30",
        "-f", "lavfi", "-i", "sine=frequency=220:duration=30",
        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
        "-pix_fmt", "yuv420p", str(src),
    ])
    manifest = tmp_path / "render_long_manifest.json"
    manifest.write_text(json.dumps({
        "duration": 30.0,
        "cues": [_cue(5, "clip"), _cue(12, "filing"), _cue(20, "meme")],
    }))
    out, info = repurpose_short_from_long(src, manifest, small)
    assert out.exists()
    v = next(s for s in ffprobe_json(out)["streams"] if s["codec_type"] == "video")
    assert (v["width"], v["height"]) == (306, 544)
    assert info["window"] == [0.0, 30.0]
    assert out.with_suffix(".repurpose.json").exists()


# --------------------------------------------------------------- thumbnail


def test_shock_metric_priority():
    from pipeline.models import CompanyData

    data = CompanyData(values={"net_margin_pct": -18.0, "ps_ratio": 62.0})
    assert shock_metric(data) == "Net margin: -18%"
    data2 = CompanyData(values={"ps_ratio": 62.0, "net_margin_pct": 12.0})
    assert shock_metric(data2) == "P/S: 62x"
    assert shock_metric(CompanyData(values={})) == ""


def test_make_thumbnail(settings, workspace, long_valid_text):
    from pipeline.parser_long import parse_long_script
    from pipeline.workspace import Workspace

    script, _ = parse_long_script(long_valid_text, "EXMPL", settings)
    ws = Workspace(settings, "EXMPL", "2026-07-01")
    assert ws.path == workspace
    out = make_thumbnail(script, ws, settings)
    assert out is not None and out.exists()
    from PIL import Image

    img = Image.open(out)
    assert img.size == (1280, 720)


# ---------------------------------------------------------------- delivery


def test_delivery_local_with_attribution(settings, tmp_path):
    from pipeline.delivery import deliver

    artifact = tmp_path / "video.mp4"
    artifact.write_bytes(b"fake video")
    result = deliver(artifact, "EXMPL", "2026-07-01", settings,
                     attributions=["Video by A on Pexels (url)"])
    assert result.backend == "local", "MOCK_MODE must force local delivery"
    assert result.link.startswith("file://")
    assert "Video by A" in result.note
    delivered = settings.workspace_dir / "_delivered" / "EXMPL" / "2026-07-01"
    assert (delivered / "video.mp4").exists()
    assert (delivered / "video.attribution.txt").exists()


def test_delivery_telegram_size_gate(settings, tmp_path):
    from pipeline.delivery import DeliveryError, deliver

    live = settings.model_copy(update={
        "mock_mode": False, "delivery_backend": "telegram",
        "telegram_upload_limit_mb": 0,  # force the cap
    })
    artifact = tmp_path / "big.mp4"
    artifact.write_bytes(b"x" * 2_000_000)
    with pytest.raises(DeliveryError, match="cap"):
        deliver(artifact, "EXMPL", "2026-07-01", live)


def test_repurpose_request_gate(settings, tmp_path):
    from bot.handlers import BotCore
    from pipeline.workspace import Workspace

    core = BotCore(settings)
    kind, text, _ = core.repurpose_request("NOPE")
    assert kind is None
    Workspace(settings, "ABC", "2026-07-01").create()
    kind, text, _ = core.repurpose_request("ABC")
    assert kind is None and "render_long first" in text
