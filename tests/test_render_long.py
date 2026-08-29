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
The numbers, five years of them. [CHART: revenue] Revenue is a plateau wearing a growth costume. [SHOW FILING: income_statement.png] The filing says minus eighty nine million. [SOUND: windows_error] Every year wider. [MEME: harold-quick-flip-became-bagholder]
The industry is two giants and a coupon. [CLIP: boardroom_suits] Pricing power is a memoir title.
Bull case: sticky contracts. [PLATE: both-true-16x9 | kicker=BOTH TRUE | statement-1=Forty percent of revenue is contracted. | mark-1=up | statement-2=One point four billion of debt. | mark-2=down] Bear case: the balance sheet has a clock on it. I'll be up at three a.m. either way. See you at the next filing.

=== CHAPTERS ==="""  + """
00:00 cold-open | nobody cares anymore
00:06 the-numbers | five years of them
00:14 bull-vs-bear | both of these are true"""


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
    return settings, script, tts, out, json.loads(manifest.read_text(encoding="utf-8"))


def test_streams_and_duration(rendered):
    settings, script, tts, out, manifest = rendered
    assert out.exists() and out.stat().st_size > 100_000
    info = ffprobe_json(out)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    a = next(s for s in info["streams"] if s["codec_type"] == "audio")
    assert v["codec_name"] == "h264" and (v["width"], v["height"]) == (640, 360)
    assert a["codec_name"] == "aac"
    assert float(info["format"]["duration"]) == pytest.approx(tts.duration_s, abs=0.7)


def test_host_anchored_structure_with_all_kinds(rendered):
    settings, script, tts, out, manifest = rendered
    segs = manifest["segments"]
    # tiles the whole duration
    assert segs[0]["start"] == 0.0
    assert segs[-1]["end"] == pytest.approx(tts.duration_s, abs=0.01)
    for a, b in zip(segs, segs[1:]):
        assert a["end"] == pytest.approx(b["start"], abs=0.01)
    kinds = {s["kind"] for s in segs}
    assert {"clip", "img", "chart", "filing", "meme", "host"} <= kinds

    # deliberate pacing: nothing flashes by, and every gap is ONE held host
    # beat rather than a run of chopped filler
    for s in segs:
        assert s["end"] - s["start"] >= 1.0, f"{s['kind']} flashes by"
    for a, b in zip(segs, segs[1:]):
        assert not (a["kind"] == "host" and b["kind"] == "host"), \
            "consecutive host beats mean the gap was chopped"

    # visual segments start on their cue's anchor-word time, or later when a
    # data visual before them was still being read
    cues = build_long_timeline(script, tts.words, tts.duration_s)
    cue_times = sorted(c.t for c in cues if c.kind is not CueKind.SOUND)
    for seg in segs:
        if seg["kind"] == "host":
            continue
        assert any(seg["start"] >= t - 1e-3 for t in cue_times)


def test_cue_times_reached_the_filtergraph(rendered):
    settings, script, tts, out, manifest = rendered
    filter_text = (out.parent / (out.stem + ".filter.txt")).read_text(encoding="utf-8")
    refin = next(s for s in manifest["segments"] if s["kind"] == "filing")
    assert f"between(t,{refin['start']:.4f}" in filter_text  # the glitch flash
    assert "subtitles=filename=" in filter_text
    # In segmented mode the beats are separate encodes concatenated with
    # -c copy, so the final graph carries only the overlays; in single-graph
    # mode the concat filter is in there.
    if manifest["segmented"]:
        assert (out.parent / "render_long" / "base.mp4").exists()
        assert len(manifest["segments"]) == len(
            [s for s in manifest["segments"] if s.get("filter")])
    else:
        assert "concat=n=%d" % len(manifest["segments"]) in filter_text
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


# ---- the overhaul: media-is-the-background, motion, design system --------


def test_nothing_pans_or_zooms(rendered):
    """No drift on anything — photos, backdrops and b-roll included.

    Motion is the host (mouth flap, boil pairs), the cuts, and real video
    clips. Every still is scale + pad, held. This is also what makes a
    segment cacheable: its output no longer depends on where it sits in the
    timeline.
    """
    settings, script, tts, out, manifest = rendered
    W, H = manifest["resolution"]
    segs = manifest["segments"]
    # every filter this render used: the overlay graph plus each beat's own
    graphs = [(out.parent / (out.stem + ".filter.txt")).read_text(encoding="utf-8")]
    graphs += [s.get("filter", "") for s in segs]
    all_filters = "\n".join(graphs)

    assert "zoompan" not in all_filters, "zoompan is gone for good"
    # a pan is a crop with a time-varying x/y expression
    assert "(iw-ow)*t/" not in all_filters and "(ih-oh)*t/" not in all_filters, \
        "no time-varying crop anywhere"
    assert "1.14" not in all_filters, "the Ken Burns upscale is gone"

    # every still segment is the plain contain-fit hold
    still_kinds = {"chart", "filing", "screengrab", "asset", "img", "meme",
                   "table", "term", "bignum", "prop", "host"}
    stills = [s for s in segs if s["kind"] in still_kinds]
    assert stills
    assert f"pad={W}:{H}" in all_filters


def test_the_ken_burns_vocabulary_is_deleted():
    """Removed outright, not left behind a flag."""
    import pipeline.render_long as rl

    for gone in ("_KB_MODES", "_ken_burns_chain", "_STILL_KINDS"):
        assert not hasattr(rl, gone), f"{gone} should no longer exist"


def test_long_captions_are_whole_phrases_in_a_fitted_box(rendered):
    """An opaque, text-fitted box (BorderStyle=3), carrying a whole clause.

    The karaoke fill lit ONE word and washed the rest of the line out to
    near-invisible — unreadable at a glance, and it coloured the lit word the
    same red the kit reserves for a down-move. Same phrase chips as the short
    now, sized for a 16:9 line.
    """
    settings, script, tts, out, manifest = rendered
    ass = (out.parent / "render_long" / "captions.ass").read_text(encoding="utf-8")
    assert ",3,14,0,2," in ass, "captions use the fitted-box style"
    assert "\\k" not in ass, "the per-word karaoke fill is gone"
    lines = [ln.split(",,0,0,0,,", 1)[1] for ln in ass.splitlines()
             if ln.startswith("Dialogue:") and ",,0,0,0,," in ln]
    assert lines, "no caption lines at all"
    words = [len(ln.split("}")[-1].split()) for ln in lines]
    assert max(words) >= 5, f"longest caption is {max(words)} words — still chips"


def test_host_holds_the_untagged_stretches(rendered):
    """Untagged narration is Dennis on screen, not a designed filler card."""
    settings, script, tts, out, manifest = rendered
    rdir = out.parent / "render_long"
    assert not list(rdir.glob("card_*.png")), "the repeated mascot cards are gone"

    hosts = [s for s in manifest["segments"] if s["kind"] == "host"]
    assert hosts, "the sample has host beats"
    assert all(h["layout"] == "host-full" for h in hosts)
    # a real talking clip was composited for each one
    clips = sorted(rdir.glob("host_*.mov"))
    assert len(clips) >= len(hosts), "every host beat gets a lip-synced clip"
    # host beats are numbered sequentially so the renderer can vary the shot
    variants = [h["variant"] for h in hosts]
    assert len(set(variants)) == len(variants)
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
    assert json.loads(draft_manifest.read_text(encoding="utf-8"))["draft"] is True


# ---- the reference look: doodles, scribbles, screengrab, marker chart ----


@pytest.fixture(scope="module")
def rendered_doodles(tmp_path_factory):
    import shutil
    from pathlib import Path

    from config import Settings

    tmp = tmp_path_factory.mktemp("render_long_doodles")
    settings = Settings(
        MOCK_MODE=True,
        workspace_dir=tmp / "ws", cache_dir=tmp / "cache", state_dir=tmp / "state",
        long_width=640, long_height=360,
        _env_file=None,
    )
    settings.ensure_runtime_dirs()
    fixtures = Path(__file__).resolve().parents[1] / "fixtures"
    raw = (fixtures / "scripts" / "long_doodles.txt").read_text(encoding="utf-8")
    script, _ = parse_long_script(raw, "EXMPL", settings)
    ws = settings.workspace_dir / "EXMPL" / "test"
    ws.mkdir(parents=True)
    Image.new("RGB", (1200, 700), (14, 18, 26)).save(ws / "income_statement.png")
    shutil.copy(fixtures / "company_data" / "dennis_data.xlsx", ws / "dennis_data.xlsx")
    data = load_company_data(ws)
    # the operator-supplied screengrab (a tall phone P&L) lives in custom/
    custom = settings.assets_dir / "custom"
    custom.mkdir(parents=True, exist_ok=True)
    grab = custom / "broker-pnl.png"
    Image.new("RGB", (1170, 2532), (16, 26, 20)).save(grab)
    try:
        tts = TTSEngine(settings).synthesize(script.narration, "long")
        out, manifest = render_long(script, tts, ws, settings,
                                    content=ContentManager(settings),
                                    as_of="2026-07-01", company_data=data)
        yield settings, script, tts, out, json.loads(manifest.read_text(encoding="utf-8"))
    finally:
        grab.unlink(missing_ok=True)


def test_screengrab_and_marker_chart_segments(rendered_doodles):
    settings, script, tts, out, manifest = rendered_doodles
    segs = manifest["segments"]
    kinds = {s["kind"] for s in segs}
    assert "screengrab" in kinds
    grab = next(s for s in segs if s["kind"] == "screengrab")
    assert grab["source"] == "local"
    # two [CHART] segments: one clean (revenue), one marker (price)
    charts = [s for s in segs if s["kind"] == "chart"]
    assert len(charts) >= 2
    assert all(c["source"] == "generated" for c in charts)
def test_the_stinger_sits_above_its_own_transition_strip(rendered):
    """z-order is list order, and the ink wipe belongs behind the divider.

    The comment has always said "under the stinger" while the append order put
    it on top. Harmless at 92% opacity, because everything washed together;
    with an opaque card it decides which one you can read.
    """
    settings, script, tts, out, manifest = rendered
    names = [l["name"] for l in manifest["layers"]]
    for i, name in enumerate(names):
        if not name.startswith("transition_"):
            continue
        k = name.split("_")[1]
        assert f"chapter_{k}" in names, f"{name} has no stinger to sit under"
        assert names.index(f"chapter_{k}") > i, \
            f"{name} is composited over chapter_{k}"

# --------------------------------------------------------------------------
# The room, the host and the chapter openers — the three things the new kit
# put in place of the design-system furniture the old renderer drew itself.
# --------------------------------------------------------------------------


def test_a_chapter_opener_is_the_room_with_the_title_in_its_slot(rendered):
    """Not a separate stinger family, and no ordinal anywhere.

    The old card printed "01"…"14" into the artwork, which is why a chapter
    could not be moved, repeated or cut without the card lying about it.
    """
    settings, script, tts, out, manifest = rendered
    stingers = manifest["stingers"]
    assert stingers, "no chapter openers were drawn"
    for st in stingers:
        assert st["title"], "an opener with no title"
        assert st["type"], "an opener with no type"
        assert "n" not in st, "a chapter opener carries an ordinal"
    assert manifest["chapter_warnings"] == []


def test_every_on_screen_title_is_one_the_director_wrote(rendered, long_valid_text):
    """The failure this replaced put six generic section names on screen
    regardless of what the sections actually were."""
    settings, script, tts, out, manifest = rendered
    written = {(c.type, c.title) for c in script.chapter_list}
    for st in manifest["stingers"]:
        assert (st["type"], st["title"]) in written, \
            f"{st['title']!r} is on screen and not in the trailer"


def test_the_host_is_placed_and_lip_synced(rendered):
    settings, script, tts, out, manifest = rendered
    motion = manifest.get("host_motion") or []
    assert motion, "no host beat reported any motion"
    assert all(m["pose"].startswith("host/") for m in motion)
    assert any(m["spoke"] for m in motion), "the host never opened his mouth"


def test_the_plates_are_the_ones_the_script_named(rendered, long_valid_text):
    """The renderer never picks a plate."""
    from pipeline.models import TagType

    settings, script, tts, out, manifest = rendered
    named = {e.payload for e in script.events_of(TagType.PLATE)}
    drawn = {s["value"] for s in manifest["segments"] if s["kind"] == "plate"}
    assert drawn <= named, f"the renderer drew a plate nobody named: {drawn - named}"
