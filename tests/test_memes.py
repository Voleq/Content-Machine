"""Owned meme library + fallback chain (§6): library first, providers
only on a miss, filler floor, cached, offline."""

import json

from pipeline.memes import MemeLibrary, MemeManager, MockMemeClient

ROOT_INDEX_KEYS = 32  # the committed library ships 32 indexed memes


def test_committed_index_shape(settings):
    lib = MemeLibrary(settings)
    index = lib.index()
    assert len(index) == ROOT_INDEX_KEYS
    for stem, entry in index.items():
        assert stem == stem.lower().replace(" ", "-"), "stems are kebab-case"
        assert entry.get("tags"), f"{stem} needs tags"
        assert entry.get("use_when"), f"{stem} needs a one-line use_when"
        assert lib._file_for(stem) is not None, f"{stem} has no image file"


def test_match_exact_stem(settings):
    lib = MemeLibrary(settings)
    assert lib.match("harold-quick-flip-became-bagholder") == "harold-quick-flip-became-bagholder"


def test_match_by_tag(settings):
    lib = MemeLibrary(settings)
    assert lib.match("bagholder") == "harold-quick-flip-became-bagholder"
    assert lib.match("margin-call") == "margin-call-due-532k-daily-loss"
    assert lib.match("circular-financing") == "altman-jensen-sell-me-this-pen-circular-financing"


def test_match_normalizes_key(settings):
    lib = MemeLibrary(settings)
    assert lib.match("Buy The Dip") == "buy-the-dip-dippity-dip"
    assert lib.match("inverse_cramer") == "inverse-cramer-trading-card"


def test_library_hit_never_calls_providers(settings):
    manager = MemeManager(settings)
    asset = manager.resolve("bagholder")
    assert asset.source == "library"
    assert asset.path.exists() and asset.path.suffix == ".png"
    assert "owned meme library" in asset.attribution
    client: MockMemeClient = manager.providers[0]
    assert client.search_calls == [], "library hit must not touch fallbacks"


def test_miss_falls_through_to_provider_then_cache(settings):
    manager = MemeManager(settings)
    first = manager.resolve("some-unindexed-meme")
    assert first.source == "mock"
    assert first.path.exists()

    client: MockMemeClient = manager.providers[0]
    searches = len(client.search_calls)
    second = manager.resolve("some-unindexed-meme")
    assert second.source == "cache"
    assert second.path == first.path
    assert len(client.search_calls) == searches, "cache hit must make zero calls"
    assert "mock" in second.attribution


def test_provider_failure_degrades_to_filler(settings):
    class DeadProvider:
        name = "dead"
        def search(self, query):
            raise OSError("network down")
        def download(self, url, dest):
            raise OSError("network down")

    manager = MemeManager(settings, providers=[DeadProvider()])
    asset = manager.resolve("totally-unknown-meme")
    assert asset.source == "filler"
    assert asset.path.exists()


def test_no_providers_configured_means_filler(settings):
    manager = MemeManager(settings, providers=[])
    asset = manager.resolve("nothing-matches-this")
    assert asset.source == "filler"


def test_index_json_is_committed_and_valid():
    from pathlib import Path

    f = Path(__file__).resolve().parents[1] / "assets" / "meme_library" / "meme_index.json"
    index = json.loads(f.read_text())
    assert len(index) == ROOT_INDEX_KEYS
