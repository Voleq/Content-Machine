"""SHORT renderer smoke test: renders a real MP4 from mock audio +
fixture prices at reduced resolution, then verifies the cue timing that
reached the filtergraph against the timeline. The Noise-or-signal
template: chart hero, headlines on the chart, numbers sheet, deadpan
conclusion — and no stamp anywhere."""

import json

import pytest

from pipeline.models import CueKind, ShortScript
from pipeline.render_common import ffprobe_json
from pipeline.render_short import render_short, sample_hook_opener
from pipeline.timeline import build_short_timeline
from pipeline.tts import TTSEngine

# the raw script embeds inline [DOODLE]/[SCRIBBLE] tags and opens on the
# marker chart — parsed (not hand-built) so the inline tokenizer runs
SMOKE_RAW = json.dumps({
    "ticker": "EXMPL",
    "format": "short",
    "hook_text": "Up 29% today. The business is not.",
    "chart_style": "marker",
    "audio_script": (
        "EXMPL is up twenty nine percent today. [DOODLE: crash] "
        "The news is a press release. "
        "Revenue is flat for five years and the losses got [SCRIBBLE: circle -> Net income] wider every year. "
        "The chart went vertical, the business went sideways. "
        "Noise. Set a reminder for the next filing."
    ),
    "move_summary": "+29% today · 5× volume",
    "headlines": [
        {"text": "EXMPL announces AI partnership", "meaning": "A press release, no revenue attached."},
    ],
    "years": ["2021", "2022", "2023", "2024", "2025"],
    "numbers": [
        {"label": "Revenue", "values": ["$400M", "$452M", "$471M", "$491M", "$496M"]},
        {"label": "Net income", "values": ["-$8M", "-$25M", "-$49M", "-$70M", "-$89M"]},
    ],
    "numbers_comment": "Flat revenue, widening losses.",
    "conclusion": "Noise. Set a reminder for the next filing.",
    "meme": {"key": "fomo-stages-wish-i-bought-doodle", "anchor_word": "vertical"},
    "annotations": [
        {"target": "chart", "anchor_word": "today", "note": "this"},
        {"target": "numbers", "row_index": 1, "anchor_word": "wider"},
    ],
})


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    from config import Settings

    from pipeline.parser_short import parse_short_script

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
    script, _ = parse_short_script(SMOKE_RAW, settings)
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
    conclusion = next(c for c in cues if c.kind is CueKind.CONCLUSION)
    numbers = next(c for c in cues if c.kind is CueKind.NUMBERS)
    headline = next(c for c in cues if c.kind is CueKind.HEADLINE)
    annotation = next(c for c in cues if c.kind is CueKind.ANNOTATION)
    zoom = next(c for c in cues if c.kind is CueKind.ZOOM)
    meme = next(c for c in cues if c.kind is CueKind.MEME)

    for cue in (conclusion, numbers, headline, annotation, zoom, meme):
        assert f"between(t,{cue.t:.4f}" in filter_text, f"{cue.kind} cue time missing"
    assert "subtitles=filename=" in filter_text
    # the payoff lands on the conclusion's spoken words (audio-timestamp clock)
    from pipeline.timeline import find_anchor_time

    anchored = find_anchor_time(tts.words, "Noise. Set a")
    assert anchored is not None
    assert conclusion.t == pytest.approx(anchored, abs=0.06)


def test_manifest_reflects_cues_and_kit(rendered):
    settings, script, tts, out, manifest = rendered
    times = [c["t"] for c in manifest["cues"]]
    assert times == sorted(times)
    names = {layer["name"] for layer in manifest["layers"]}
    assert {"chart", "brand_bug", "hook", "numbers_sheet", "conclusion",
            "disclaimer", "meme_0"} <= names
    assert {f"number_row_{i}" for i in range(2)} <= names
    assert any(n.startswith("headline_") for n in names)
    assert any(n.startswith("scribble_") for n in names)
    assert any(n.startswith("zoom_") for n in names)
    assert any(n.startswith("flash_") for n in names)
    conc_layer = next(l for l in manifest["layers"] if l["name"] == "conclusion")
    conc_cue = next(c for c in manifest["cues"] if c["kind"] == "conclusion")
    assert conc_layer["t_start"] == pytest.approx(conc_cue["t"])
    assert manifest["duration"] == pytest.approx(tts.duration_s)
    assert manifest["chart"]["source"] in ("fixture", "synthetic", "cache")


def test_no_desk_no_stamp_anywhere(rendered):
    """The desk scene and the verdict system are gone — not renamed."""
    settings, script, tts, out, manifest = rendered
    names = " ".join(layer["name"] for layer in manifest["layers"])
    for banned in ("stamp", "folder", "whip", "highlight", "typewriter", "cta"):
        assert banned not in names, f"desk-era layer {banned!r} survived"
    assert "verdict" not in json.dumps(manifest).lower()


def test_marker_chart_and_hand_drawn_overlays(rendered):
    """The reference look: marker chart hero + inline doodle + inline
    scribble composited as top layers."""
    settings, script, tts, out, manifest = rendered
    assert manifest["chart"]["style"] == "marker"
    names = {layer["name"] for layer in manifest["layers"]}
    assert any(n.startswith("doodle_") for n in names), "inline doodle composited"
    assert any(n.startswith("scribble_inline_") for n in names), "inline scribble composited"
    # the inline doodle/scribble cue times reached the filtergraph
    filter_text = (out.parent / (out.stem + ".filter.txt")).read_text()
    for kind in ("doodle", "scribble"):
        cue = next(c for c in manifest["cues"] if c["kind"] == kind)
        assert f"between(t,{cue['t']:.4f}" in filter_text


def test_hook_opener_sampling(settings):
    a = sample_hook_opener("sha-one", settings)
    b = sample_hook_opener("sha-one", settings)
    c = sample_hook_opener("sha-two-different", settings)
    assert a == b, "same script sha -> same opener (idempotent re-renders)"
    bank = json.loads((settings.assets_dir / "hook_bank.json").read_text())["openers"]
    assert a in bank and c in bank
