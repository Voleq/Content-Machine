import json

import pytest

from pipeline.broll import (
    PALETTE,
    BrollManager,
    MockPexelsClient,
    broll_cache_key,
    palette_keys,
)
from pipeline.render_common import ffprobe_duration, ffprobe_json, run_ffmpeg


def test_palette_is_a_real_vetted_palette():
    assert len(PALETTE) >= 40, "palette must stay in the 40-60 key range"
    assert len(PALETTE) <= 60
    assert all(q.strip() for q in PALETTE.values())
    # the master-prompt fixture keys must exist
    for key in ("dumpster_fire", "clown", "sinking_ship", "house_of_cards",
                "monopoly_money", "printing_money", "empty_promise_handshake",
                "confused_office_worker"):
        assert key in PALETTE
    assert palette_keys() == sorted(PALETTE)


def test_cache_key_by_query_and_provider():
    a = broll_cache_key("dumpster fire burning night")
    assert a == broll_cache_key("dumpster fire burning night")
    assert a != broll_cache_key("dumpster fire burning night", provider="pixabay")
    assert a != broll_cache_key("other query")


@pytest.fixture()
def manager(settings, tmp_path):
    return BrollManager(settings, library_dir=tmp_path / "library")


def test_mock_fetch_normalizes_and_attributes(manager, settings):
    clip = manager.resolve("dumpster_fire")
    assert clip.source == "pexels"
    assert clip.path.exists()
    assert "Alex Mockman" in clip.attribution
    info = ffprobe_json(clip.path)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert (v["width"], v["height"]) == settings.long_resolution
    assert not [s for s in info["streams"] if s["codec_type"] == "audio"], "audio must be stripped"
    assert ffprobe_duration(clip.path) <= settings.broll_max_clip_s + 0.2


def test_cache_hit_makes_no_client_calls(manager):
    first = manager.resolve("dumpster_fire")
    client: MockPexelsClient = manager.client
    searches = len(client.search_calls)
    downloads = len(client.download_calls)

    second = manager.resolve("dumpster_fire")
    assert second.source == "cache"
    assert second.path == first.path
    assert len(client.search_calls) == searches, "re-run must make zero fetch calls"
    assert len(client.download_calls) == downloads
    assert "Alex Mockman" in second.attribution, "attribution survives the cache"


def test_local_library_wins(settings, tmp_path):
    lib = tmp_path / "library"
    lib.mkdir()
    run_ffmpeg([
        "-f", "lavfi", "-i", "color=c=red:size=640x360:rate=30:duration=2",
        "-c:v", "libx264", "-preset", "ultrafast", str(lib / "clown.mp4"),
    ])
    manager = BrollManager(settings, library_dir=lib)
    clip = manager.resolve("clown")
    assert clip.source == "local"
    assert "owned library clip" in clip.attribution
    assert manager.client.search_calls == [], "library hit must not touch Pexels"
    info = ffprobe_json(clip.path)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert (v["width"], v["height"]) == settings.long_resolution, "library clips are normalized too"


def test_unknown_key_falls_back_to_filler(manager):
    clip = manager.resolve("flying_toasters")
    assert clip.source == "filler"
    assert clip.path.exists()
    assert manager.client.search_calls == []


def test_pexels_cap_degrades_to_filler(settings, tmp_path):
    capped = settings.model_copy(update={"pexels_monthly_call_cap": 0})
    manager = BrollManager(capped, library_dir=tmp_path / "library")

    class CapClient(MockPexelsClient):
        def search(self, query, per_page=5):
            manager.ledger.check_pexels_budget()  # simulates the real client's gate
            return super().search(query, per_page)

    manager.client = CapClient(capped)
    clip = manager.resolve("dumpster_fire")
    assert clip.source == "filler", "cap exhaustion must degrade, never abort"


def test_swap_choice_picks_other_candidate(manager):
    a = manager.resolve("dumpster_fire", choice=0)
    b = manager.resolve("dumpster_fire", choice=1)
    assert a.path != b.path
    assert "Priya Fixture" in b.attribution  # second fixture video
    assert manager.alternates_count("dumpster_fire") >= 2


def test_plan_and_thumbnails(manager, tmp_path):
    clips = manager.plan(["dumpster_fire", "clown", "not_a_key"])
    assert [c.source for c in clips] == ["cache", "pexels", "filler"] or \
           [c.source for c in clips] == ["pexels", "pexels", "filler"]
    thumb = manager.thumbnail(clips[0], tmp_path / "t.png")
    assert thumb.exists() and thumb.stat().st_size > 500


def test_generic_fixture_used_for_unfixtured_keys(manager):
    clip = manager.resolve("piggy_bank")  # no dedicated fixture json
    assert clip.source == "pexels"
    assert "Generic Fixture" in clip.attribution
