"""LONG renderer smoke test: renders a real MP4 (reduced res) from mock
audio + the multi-source content engine, verifies fast-cut structure,
filing flash, meme sting, draft path, and that cue times reached the
filtergraph. No stamp anywhere."""

import json

import pytest
from PIL import Image, ImageDraw

from pipeline.broll import ContentManager
from pipeline.company_data import load_company_data
from pipeline.models import CueKind
from pipeline.parser_long import parse_long_script
from pipeline.render_common import ffprobe_json
from pipeline.render_long import render_long
from pipeline.timeline import build_long_timeline
from pipeline.tts import TTSEngine

RAW = """EXMPL is down sixty percent and nobody cares anymore. [CLIP: tumbleweed] Which is when I start reading.
Here is what they actually do. [IMG: EXMPL logistics warehouse] Software for depots. Real customers. [SOUND: cash_register]
The numbers, five years of them. [CHART: revenue] Revenue is a plateau wearing a growth costume. [SHOW FILING: income_statement.png] The filing says minus eighty nine million. [SOUND: windows_error] Every year wider. [MEME: astronaut-always-has-been-dilution]
The industry is two giants and a coupon. [CLIP: boardroom_suits] Pricing power is a memoir title.
Bull case: sticky contracts. Bear case: the balance sheet has a clock on it. I'll be up at three a.m. either way. See you at the next filing."""


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    import shutil
    from pathlib import Path

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
    ImageDraw.Draw(img).text((40, 40), "income statement mock", fill=(210, 210, 210))
    img.save(ws / "income_statement.png")
    fixtures = Path(__file__).resolve().parents[1] / "fixtures"
    shutil.copy(fixtures / "company_data" / "dennis_data.xlsx", ws / "dennis_data.xlsx")
    data = load_company_data(ws)

    tts = TTSEngine(settings).synthesize(script.narration, "long")
    out, manifest = render_long(script, tts, ws, settings,
                                content=ContentManager(settings),
                                as_of="2026-07-01", company_data=data)
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


def test_fast_cut_structure_with_all_kinds(rendered):
    settings, script, tts, out, manifest = rendered
    segs = manifest["segments"]
    # tiles the whole duration
    assert segs[0]["start"] == 0.0
    assert segs[-1]["end"] == pytest.approx(tts.duration_s, abs=0.01)
    for a, b in zip(segs, segs[1:]):
        assert a["end"] == pytest.approx(b["start"], abs=0.01)
    kinds = {s["kind"] for s in segs}
    assert {"clip", "img", "chart", "filing", "meme", "filler"} <= kinds
    # fast cuts: fillers never exceed the max cut
    for s in segs:
        if s["kind"] == "filler":
            assert s["end"] - s["start"] <= settings.long_max_cut_s + 1e-6
    # visual segments start exactly on their cue's anchor-word time
    cues = build_long_timeline(script, tts.words, tts.duration_s)
    cue_times = {round(c.t, 3) for c in cues if c.kind is not CueKind.SOUND}
    for seg in segs:
        if seg["kind"] != "filler":
            assert round(seg["start"], 3) in cue_times


def test_cue_times_reached_the_filtergraph(rendered):
    settings, script, tts, out, manifest = rendered
    filter_text = (out.parent / (out.stem + ".filter.txt")).read_text()
    refin = next(s for s in manifest["segments"] if s["kind"] == "filing")
    assert f"between(t,{refin['start']:.4f}" in filter_text  # the glitch flash
    assert "concat=n=%d" % len(manifest["segments"]) in filter_text
    assert "subtitles=filename=" in filter_text
    # sounds mixed at their cue times
    cues = build_long_timeline(script, tts.words, tts.duration_s)
    for c in cues:
        if c.kind is CueKind.SOUND:
            assert f"adelay={int(c.t * 1000)}" in filter_text
    # the meme freeze gets its boom sting
    meme = next(s for s in manifest["segments"] if s["kind"] == "meme")
    assert f"adelay={int(meme['start'] * 1000)}" in filter_text
    assert "stamp" not in filter_text.lower(), "the verdict system is deleted"


def test_sources_and_attributions_carried(rendered):
    settings, script, tts, out, manifest = rendered
    segs = manifest["segments"]
    assert any("Pexels" in (s.get("attribution") or "") for s in segs)
    assert any("Wikimedia" in (s.get("attribution") or "") for s in segs)
    meme = next(s for s in segs if s["kind"] == "meme")
    assert meme["source"] == "library"
    chart = next(s for s in segs if s["kind"] == "chart")
    assert chart["source"] == "generated"
    assert any("Pexels" in a for a in manifest["attributions"])
    assert "verdict" not in json.dumps(manifest).lower()


def test_draft_reuses_cached_tts_and_is_smaller(rendered):
    settings, script, tts, out, manifest = rendered
    engine = TTSEngine(settings)
    cached = engine.synthesize(script.narration, "long")
    assert cached.cached, "draft path must reuse the cached TTS"
    ws = out.parent
    draft_out, draft_manifest = render_long(
        script, cached, ws, settings, content=ContentManager(settings), draft=True,
    )
    info = ffprobe_json(draft_out)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert v["width"] == int(640 * settings.draft_scale) // 2 * 2
    assert json.loads(draft_manifest.read_text())["draft"] is True
