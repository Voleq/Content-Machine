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
    }), encoding="utf-8")
    out, info = repurpose_short_from_long(src, manifest, small)
    assert out.exists()
    v = next(s for s in ffprobe_json(out)["streams"] if s["codec_type"] == "video")
    assert (v["width"], v["height"]) == (306, 544)
    assert info["window"] == [0.0, 30.0]
    assert out.with_suffix(".repurpose.json").exists()


# --------------------------------------------------------------- thumbnail


def test_shock_metric_priority():
    from pipeline.models import CompanyData

    data = CompanyData(values={"ps_ttm": 62.0}, dashboard={"Net margin (LTM)": -18.0})
    assert shock_metric(data) == "Net margin: -18%"
    data2 = CompanyData(values={"ps_ttm": 62.0}, dashboard={"Net margin (LTM)": 12.0})
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


# --------------------------------------------------------------------------
# The cover is a frame from the video.
#
# It used to paint on a near-black photo (mean luminance 17), darken it, and
# accent in a gold that is not in the kit palette, with a six-pixel black
# outline on every string. The video it advertised is ink on paper.
# --------------------------------------------------------------------------


def _mean_luminance(img) -> float:
    px = list(img.convert("RGB").resize((160, 90)).getdata())
    return sum((r * 299 + g * 587 + b * 114) // 1000 for r, g, b in px) / len(px)


def test_the_cover_is_paper_not_a_dark_photo(settings, workspace, long_valid_text):
    """The one measurement that says which product this is selling."""
    from PIL import Image

    from pipeline.parser_long import parse_long_script
    from pipeline.workspace import Workspace

    script, _ = parse_long_script(long_valid_text, "EXMPL", settings)
    out = make_thumbnail(script, Workspace(settings, "EXMPL", "2026-07-01"), settings)
    assert out is not None
    lum = _mean_luminance(Image.open(out))
    assert lum > 150, f"the cover reads dark ({lum:.0f}) in a light-kit channel"


def test_no_gold_anywhere_on_the_cover(settings, workspace, long_valid_text):
    """Nothing on the cover may sit outside the kit's eight roles.

    The old cover accented in a gold that is not in this palette, which said
    nothing at all because it was on every thumbnail.
    """
    from PIL import Image

    from pipeline.parser_long import parse_long_script
    from pipeline.plates import PALETTE_ROLES, load_plates
    from pipeline.workspace import Workspace

    script, _ = parse_long_script(long_valid_text, "EXMPL", settings)
    out = make_thumbnail(script, Workspace(settings, "EXMPL", "2026-07-01"), settings)
    img = Image.open(out).convert("RGB")
    reg = load_plates(settings.assets_dir)
    # Plus the two CHARACTER colours: skin and hair are the host's own, and
    # deliberately not a ninth and tenth data role.
    allowed = tuple(reg.colour(r) for r in PALETTE_ROLES) + (
        (221, 183, 148), (122, 102, 80),
        (124, 139, 98), (181, 116, 90), (46, 55, 66),   # set: foliage, terracotta, screen
    )
    # Saturated pixels have to be a kit colour. The old gold (#c8a24a) is
    # saturated and would fail; paper, ink and greys are not saturated.
    bad = 0
    for r, g, b in img.resize((320, 180)).getdata():
        if max(r, g, b) - min(r, g, b) < 40:
            continue                       # neutral: paper, ink, the greys
        if any(abs(r - c[0]) + abs(g - c[1]) + abs(b - c[2]) < 120 for c in allowed):
            continue
        bad += 1
    assert bad < 200, f"{bad} saturated px outside the kit palette"


def test_a_short_gets_a_cover_at_all(settings, workspace, short_valid_json):
    """It was typed to `LongScript`, so the daily-volume format had none."""
    from PIL import Image

    from pipeline.parser_short import parse_short_script
    from pipeline.workspace import Workspace

    script, _ = parse_short_script(short_valid_json, settings)
    ws = Workspace(settings, "EXMPL", "2026-07-01")
    out = make_thumbnail(script, ws, settings)
    assert out is not None and out.exists()
    assert Image.open(out).size == (1280, 720)
    tall = ws.path / "thumbnail_tall.png"
    assert tall.exists(), "a short has a vertical shelf and needs a 9:16 cover"
    assert Image.open(tall).size == (1080, 1920)


def test_a_long_gets_no_vertical_cover(settings, workspace, long_valid_text):
    from pipeline.parser_long import parse_long_script
    from pipeline.workspace import Workspace

    script, _ = parse_long_script(long_valid_text, "EXMPL", settings)
    ws = Workspace(settings, "EXMPL", "2026-07-01")
    make_thumbnail(script, ws, settings)
    assert not (ws.path / "thumbnail_tall.png").exists()


def test_the_leading_figure_is_pulled_out_of_a_move_summary():
    """A short leads on prose with no colon in it. Set whole it shrinks to
    fit and the cover ends up with no figure on it at all."""
    from pipeline.thumbnail import split_metric

    assert split_metric("Net margin: -18%") == ("NET MARGIN", "-18%")
    assert split_metric("+29% today · 5x average volume") == (
        "TODAY · 5X AVERAGE VOLUME", "+29%")
    assert split_metric("no numbers here") == ("", "no numbers here")


def test_green_means_up_and_only_up(settings):
    """Red for a bad number, green for an up-move, ink for everything else.

    Without the move/metric distinction green either never appears — and the
    rule is decoration — or it lands on any positive figure and stops meaning
    direction.
    """
    from pipeline.plates import load_plates
    from pipeline.thumbnail import metric_colour

    reg = load_plates(settings.assets_dir)
    down, up, structure = (reg.colour("down"), reg.colour("up"),
                           reg.colour("structure"))
    assert metric_colour(settings, "-18%") == down
    assert metric_colour(settings, "-18%", is_move=True) == down
    assert metric_colour(settings, "+29%", is_move=True) == up
    assert metric_colour(settings, "+5%") == structure, \
        "a positive metric is not an up-move"
    assert metric_colour(settings, "22x") == structure
    assert metric_colour(settings, "n/a") == structure
