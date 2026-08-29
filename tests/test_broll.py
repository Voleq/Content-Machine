"""The content engine (§5): per-tag resolution chains, caching, filler
floor, attribution — all offline."""

import json

import pytest

from pipeline.broll import (
    PALETTE,
    ContentManager,
    MockImageClient,
    MockPexelsClient,
    content_cache_key,
    palette_keys,
)
from pipeline.render_common import ffprobe_duration, ffprobe_json, run_ffmpeg


def test_palette_is_a_real_vetted_palette():
    assert 40 <= len(PALETTE) <= 60, "palette must stay in the 40-60 key range"
    assert all(q.strip() for q in PALETTE.values())
    # keys the fixtures/master prompt rely on must exist
    for key in ("dumpster_fire", "clown", "tumbleweed", "hamster_wheel",
                "boardroom_suits", "growing_plant", "monopoly_money",
                "printing_money"):
        assert key in PALETTE
    assert palette_keys() == sorted(PALETTE)


def test_cache_key_by_query_and_provider():
    a = content_cache_key("dumpster fire burning night", "pexels")
    assert a == content_cache_key("dumpster fire burning night", "pexels")
    assert a != content_cache_key("dumpster fire burning night", "pixabay")
    assert a != content_cache_key("other query", "pexels")


@pytest.fixture()
def manager(settings, tmp_path):
    return ContentManager(settings, library_dir=tmp_path / "library")


# ------------------------------------------------------------------- clips


def test_clip_fetch_normalizes_and_attributes(manager, settings):
    clip = manager.resolve_clip("dumpster_fire")
    assert clip.kind == "clip" and clip.is_video
    assert clip.source == "pexels"
    assert clip.path.exists()
    assert "Alex Mockman" in clip.attribution
    info = ffprobe_json(clip.path)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert (v["width"], v["height"]) == settings.long_resolution
    assert not [s for s in info["streams"] if s["codec_type"] == "audio"], "audio must be stripped"
    assert ffprobe_duration(clip.path) <= settings.broll_max_clip_s + 0.2


def test_clip_cache_hit_makes_no_client_calls(manager):
    first = manager.resolve_clip("dumpster_fire")
    client: MockPexelsClient = manager.clip_client
    searches = len(client.search_calls)
    downloads = len(client.download_calls)

    second = manager.resolve_clip("dumpster_fire")
    assert second.source == "cache"
    assert second.path == first.path
    assert len(client.search_calls) == searches, "re-run must make zero fetch calls"
    assert len(client.download_calls) == downloads
    assert "Alex Mockman" in second.attribution, "attribution survives the cache"


def test_clip_portrait_variant_cached_separately(manager, settings):
    landscape = manager.resolve_clip("dumpster_fire")
    portrait = manager.resolve_clip("dumpster_fire", portrait=True)
    assert portrait.path != landscape.path
    v = next(s for s in ffprobe_json(portrait.path)["streams"]
             if s["codec_type"] == "video")
    assert (v["width"], v["height"]) == settings.short_resolution


def test_local_library_wins(settings, tmp_path):
    lib = tmp_path / "library"
    lib.mkdir()
    run_ffmpeg([
        "-f", "lavfi", "-i", "color=c=red:size=640x360:rate=30:duration=2",
        "-c:v", "libx264", "-preset", "ultrafast", str(lib / "clown.mp4"),
    ])
    manager = ContentManager(settings, library_dir=lib)
    clip = manager.resolve_clip("clown")
    assert clip.source == "local"
    assert "owned library clip" in clip.attribution
    assert manager.clip_client.search_calls == [], "library hit must not touch Pexels"
    v = next(s for s in ffprobe_json(clip.path)["streams"] if s["codec_type"] == "video")
    assert (v["width"], v["height"]) == settings.long_resolution


def test_non_palette_clip_key_is_fetched_as_raw_query(manager):
    """§5: [CLIP: query] — unknown keys become raw queries, not dead ends."""
    clip = manager.resolve_clip("abandoned mall escalator")
    assert clip.source == "pexels"
    assert manager.clip_client.search_calls[-1] == "abandoned mall escalator"


def test_pexels_cap_degrades_to_filler(settings, tmp_path):
    capped = settings.model_copy(update={"pexels_monthly_call_cap": 0})
    manager = ContentManager(capped, library_dir=tmp_path / "library")

    class CapClient(MockPexelsClient):
        def search(self, query, per_page=5):
            manager.ledger.check_pexels_budget()  # simulates the real client's gate
            return super().search(query, per_page)

    manager.clip_client = CapClient(capped)
    clip = manager.resolve_clip("dumpster_fire")
    assert clip.source == "filler", "cap exhaustion must degrade, never abort"


def test_swap_choice_picks_other_candidate(manager):
    a = manager.resolve_clip("dumpster_fire", choice=0)
    b = manager.resolve_clip("dumpster_fire", choice=1)
    assert a.path != b.path
    assert "Priya Fixture" in b.attribution  # second fixture video
    assert manager.alternates_count("dumpster_fire") >= 2


# ------------------------------------------------------------------ images


def test_image_resolves_via_commons_with_attribution(manager, settings):
    img = manager.resolve_image("EXMPL factory floor")
    assert img.kind == "img" and not img.is_video
    assert img.source == "mock"  # wikimedia chain, mock client
    assert "Wikimedia Commons" in img.attribution
    from PIL import Image

    assert Image.open(img.path).size == settings.long_resolution


def test_image_cache_hit(manager):
    first = manager.resolve_image("EXMPL factory floor")
    client: MockImageClient = manager.image_client
    n = len(client.search_calls)
    second = manager.resolve_image("EXMPL factory floor")
    assert second.source == "cache"
    assert second.path == first.path
    assert len(client.search_calls) == n
    assert "Wikimedia Commons" in second.attribution


def test_image_failure_degrades_to_filler(settings, tmp_path):
    class DeadImageClient:
        def search(self, query, limit=5):
            raise OSError("network down")
        def download(self, url, dest):
            raise OSError("network down")

    manager = ContentManager(settings, image_client=DeadImageClient(),
                             library_dir=tmp_path / "library")
    img = manager.resolve_image("anything")
    assert img.source == "filler"
    assert img.path.exists()


# ------------------------------------------------------------------- memes


def test_meme_resolution_through_manager(manager):
    meme = manager.resolve_meme("bagholder")
    assert meme.kind == "meme"
    assert meme.source == "library", "owned library always wins"
    assert meme.path.suffix == ".png"


# ------------------------------------------------------------------ charts


def test_chart_metric_from_history(manager, workspace):
    from pipeline.company_data import load_company_data

    data = load_company_data(workspace)
    chart = manager.resolve_chart("revenue", ticker="EXMPL", company_data=data)
    assert chart.kind == "chart" and chart.source == "generated"
    assert chart.path.exists()
    # cached: same inputs, same file
    again = manager.resolve_chart("revenue", ticker="EXMPL", company_data=data)
    assert again.path == chart.path


def test_chart_price_uses_price_feed(manager):
    chart = manager.resolve_chart("price", ticker="EXMPL")
    assert chart.source == "generated"
    assert chart.path.exists()
def test_chart_unknown_metric_falls_back(manager):
    chart = manager.resolve_chart("mystery_metric", ticker="EXMPL", company_data=None)
    assert chart.source == "filler"
def test_screengrab_image_pad_fits(manager, settings):
    from PIL import Image

    missing = manager.resolve_screengrab("no-such-grab")
    assert missing.source == "filler"

    custom = settings.assets_dir / "custom"
    custom.mkdir(parents=True, exist_ok=True)
    target = custom / "phone-pnl.png"
    Image.new("RGB", (1170, 2532), (18, 22, 28)).save(target)  # tall phone capture
    try:
        grab = manager.resolve_screengrab("phone-pnl")
        assert grab.kind == "screengrab" and grab.source == "local"
        assert not grab.is_video
        # pad-fit (never cover-crop): output is exactly long res, letterboxed
        assert Image.open(grab.path).size == settings.long_resolution
    finally:
        target.unlink()


def test_screengrab_clip_normalized(manager, settings):
    custom = settings.assets_dir / "custom"
    custom.mkdir(parents=True, exist_ok=True)
    target = custom / "screen-record.mp4"
    run_ffmpeg([
        "-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=30:duration=2",
        "-c:v", "libx264", "-preset", "ultrafast", str(target),
    ])
    try:
        grab = manager.resolve_screengrab("screen-record")
        assert grab.is_video and grab.source == "local"
        v = next(s for s in ffprobe_json(grab.path)["streams"]
                 if s["codec_type"] == "video")
        assert (v["width"], v["height"]) == settings.long_resolution
        assert not [s for s in ffprobe_json(grab.path)["streams"]
                    if s["codec_type"] == "audio"], "audio stripped"
    finally:
        target.unlink()
def test_plan_resolves_all_fetchable_kinds(manager, settings, long_valid_text, workspace):
    from pipeline.company_data import load_company_data
    from pipeline.parser_long import parse_long_script

    script, _ = parse_long_script(long_valid_text, "EXMPL", settings)
    data = load_company_data(workspace)
    plan = manager.plan(script, company_data=data)
    kinds = {v.kind for v in plan}
    assert {"clip", "img", "meme", "chart"} <= kinds
    assert all(v.path.exists() for v in plan)
    # filing screenshots are not fetches and never appear in the plan
    assert not any(v.kind == "filing" for v in plan)

    thumb = manager.thumbnail(plan[0], settings.cache_dir / "t.png")
    assert thumb.exists() and thumb.stat().st_size > 500
    still = next(v for v in plan if not v.is_video)
    thumb2 = manager.thumbnail(still, settings.cache_dir / "t2.png")
    assert thumb2.exists()


def test_generic_fixture_used_for_unfixtured_keys(manager):
    clip = manager.resolve_clip("piggy_bank")  # no dedicated fixture json
    assert clip.source == "pexels"
    assert "Generic Fixture" in clip.attribution
