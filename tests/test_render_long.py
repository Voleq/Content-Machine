"""LONG renderer smoke test: renders a real ~20s MP4 (reduced res) from
mock audio + mock b-roll, verifies jump-cut structure, refinitiv flash,
draft path, and that cue times reached the filtergraph."""

import json

import pytest
from PIL import Image, ImageDraw

from pipeline.broll import BrollManager
from pipeline.models import CueKind
from pipeline.parser_long import parse_long_script
from pipeline.render_common import ffprobe_json
from pipeline.render_long import render_long
from pipeline.timeline import build_long_timeline
from pipeline.tts import TTSEngine

RAW = """EXMPL trades at sixty two times sales. [B-ROLL: house_of_cards] We are going to find out why that is a mistake.
Revenue grew one percent. [SHOW REFINITIV: income_statement.png] That number is real. [SOUND: windows_error] Management calls the quarter transformational. [B-ROLL: clown] They spend a dollar ten to make each dollar. [SOUND: sad_trombone]
Verdict: overvalued. [STAMP: OVERVALUED] I already did my diligence."""


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    from config import Settings

    tmp = tmp_path_factory.mktemp("render_long")
    settings = Settings(
        MOCK_MODE=True,
        workspace_dir=tmp / "ws", cache_dir=tmp / "cache", state_dir=tmp / "state",
        long_width=640, long_height=360,
        _env_file=None,
    )
    settings.ensure_runtime_dirs()
    script, _ = parse_long_script(RAW, "EXMPL", settings)
    ws = settings.workspace_dir / "EXMPL" / "test"
    ws.mkdir(parents=True)
    img = Image.new("RGB", (1200, 700), (14, 18, 26))
    ImageDraw.Draw(img).text((40, 40), "REFINITIV mock", fill=(210, 210, 210))
    img.save(ws / "income_statement.png")

    tts = TTSEngine(settings).synthesize(script.narration, "long")
    out, manifest = render_long(script, tts, ws, settings,
                                broll=BrollManager(settings), as_of="2026-07-01")
    return settings, script, tts, out, json.loads(manifest.read_text())


def test_streams_and_duration(rendered):
    settings, script, tts, out, manifest = rendered
    assert out.exists() and out.stat().st_size > 100_000
    info = ffprobe_json(out)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    a = next(s for s in info["streams"] if s["codec_type"] == "audio")
    assert v["codec_name"] == "h264" and (v["width"], v["height"]) == (640, 360)
    assert a["codec_name"] == "aac"
    assert float(info["format"]["duration"]) == pytest.approx(tts.duration_s, abs=0.7)


def test_jump_cut_structure(rendered):
    settings, script, tts, out, manifest = rendered
    segs = manifest["segments"]
    # tiles the whole duration
    assert segs[0]["start"] == 0.0
    assert segs[-1]["end"] == pytest.approx(tts.duration_s, abs=0.01)
    for a, b in zip(segs, segs[1:]):
        assert a["end"] == pytest.approx(b["start"], abs=0.01)
    kinds = {s["kind"] for s in segs}
    assert {"broll", "refinitiv", "filler"} <= kinds
    # b-roll segments start exactly on their cue's anchor-word time
    cues = build_long_timeline(script, tts.words, tts.duration_s)
    broll_cue_times = {round(c.t, 3) for c in cues if c.kind is CueKind.BROLL}
    for seg in segs:
        if seg["kind"] == "broll":
            assert round(seg["start"], 3) in broll_cue_times


def test_cue_times_reached_the_filtergraph(rendered):
    settings, script, tts, out, manifest = rendered
    filter_text = (out.parent / (out.stem + ".filter.txt")).read_text()
    cues = build_long_timeline(script, tts.words, tts.duration_s)
    stamp = next(c for c in cues if c.kind is CueKind.STAMP)
    assert f"between(t,{stamp.t:.4f}" in filter_text
    refin = next(s for s in manifest["segments"] if s["kind"] == "refinitiv")
    assert f"between(t,{refin['start']:.4f}" in filter_text  # the glitch flash
    assert "concat=n=%d" % len(manifest["segments"]) in filter_text
    assert "subtitles=filename=" in filter_text
    # sounds mixed at their cue times
    sound_cues = [c for c in cues if c.kind is CueKind.SOUND]
    for c in sound_cues:
        assert f"adelay={int(c.t * 1000)}" in filter_text


def test_attributions_carried(rendered):
    settings, script, tts, out, manifest = rendered
    assert any("Pexels" in a for a in manifest["attributions"])


def test_draft_reuses_cached_tts_and_is_smaller(rendered):
    settings, script, tts, out, manifest = rendered
    engine = TTSEngine(settings)
    cached = engine.synthesize(script.narration, "long")
    assert cached.cached, "draft path must reuse the cached TTS (§7.2)"
    ws = out.parent
    draft_out, draft_manifest = render_long(
        script, cached, ws, settings, broll=BrollManager(settings), draft=True
    )
    info = ffprobe_json(draft_out)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert v["width"] == int(640 * settings.draft_scale) // 2 * 2
    assert json.loads(draft_manifest.read_text())["draft"] is True
