"""SHORT renderer smoke test (§0.5): renders a real 5–7s MP4 from mock
audio + placeholder assets at reduced resolution, then verifies the cue
timing that reached the filtergraph against the timeline."""

import json

import pytest

from pipeline.models import CueKind, ShortScript
from pipeline.render_common import ffprobe_json
from pipeline.render_short import render_short
from pipeline.timeline import build_short_timeline
from pipeline.tts import TTSEngine

SMOKE_SCRIPT = {
    "ticker": "EXMPL",
    "format": "short",
    "verdict": "OVERVALUED",
    "hook_text": "60x sales. Let's talk.",
    "audio_script": (
        "The market pays sixty times sales. They burn cash on operations. "
        "The story has no second act. Verdict overvalued."
    ),
    "data_block": ["Revenue growth: +1%", "FCF yield: -3%", "P/S: 62x"],
    "visual_directions": [
        {"type": "highlight", "line_index": 1, "color": "red", "anchor_word": "cash"},
        {"type": "stamp", "label": "OVERVALUED", "anchor": "end_minus_3"},
    ],
    "cta_text": "Tell me I'm wrong.",
}


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    from config import Settings

    tmp = tmp_path_factory.mktemp("render_short")
    settings = Settings(
        MOCK_MODE=True,
        workspace_dir=tmp / "ws",
        cache_dir=tmp / "cache",
        state_dir=tmp / "state",
        short_width=540,
        short_height=960,
        _env_file=None,
    )
    settings.ensure_runtime_dirs()
    script = ShortScript.model_validate(SMOKE_SCRIPT)
    tts = TTSEngine(settings).synthesize(script.audio_script, "short")
    ws = settings.workspace_dir / "EXMPL" / "test"
    ws.mkdir(parents=True)
    out, manifest = render_short(script, tts, ws, settings)
    return settings, script, tts, out, json.loads(manifest.read_text())


def test_smoke_output_streams(rendered):
    settings, script, tts, out, manifest = rendered
    assert out.exists() and out.stat().st_size > 50_000
    info = ffprobe_json(out)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    a = next(s for s in info["streams"] if s["codec_type"] == "audio")
    assert v["codec_name"] == "h264" and v["pix_fmt"] == "yuv420p"
    assert (v["width"], v["height"]) == (540, 960)
    assert a["codec_name"] == "aac"
    assert float(info["format"]["duration"]) == pytest.approx(tts.duration_s, abs=0.5)


def test_cue_times_reached_the_filtergraph(rendered):
    """No hardcoded scene timings: the enable windows in the actual
    filtergraph must equal the timeline's resolved cue times."""
    settings, script, tts, out, manifest = rendered
    filter_text = (out.parent / (out.stem + ".filter.txt")).read_text()

    cues = build_short_timeline(script, tts.words, tts.duration_s)
    stamp = next(c for c in cues if c.kind is CueKind.STAMP)
    whip = next(c for c in cues if c.kind is CueKind.WHIP_PAN)
    cta = next(c for c in cues if c.kind is CueKind.CTA)
    highlight = next(c for c in cues if c.kind is CueKind.HIGHLIGHT)

    for cue in (stamp, whip, cta, highlight):
        assert f"between(t,{cue.t:.4f}" in filter_text, f"{cue.kind} cue time missing"
    assert "subtitles=filename=" in filter_text
    # stamp must land at audio_duration - 3 (end_minus_3), from ffprobe truth
    assert stamp.t == pytest.approx(tts.duration_s - 3.0, abs=0.06)


def test_manifest_reflects_cues(rendered):
    settings, script, tts, out, manifest = rendered
    times = [c["t"] for c in manifest["cues"]]
    assert times == sorted(times)
    names = {layer["name"] for layer in manifest["layers"]}
    assert {"folder_closed", "whip_pan", "folder_open", "stamp", "hook",
            "cta", "disclaimer"} <= names
    assert {f"data_line_{i}" for i in range(3)} <= names
    stamp_layer = next(l for l in manifest["layers"] if l["name"] == "stamp")
    stamp_cue = next(c for c in manifest["cues"] if c["kind"] == "stamp")
    assert stamp_layer["t_start"] == pytest.approx(stamp_cue["t"])
    assert manifest["duration"] == pytest.approx(tts.duration_s)
