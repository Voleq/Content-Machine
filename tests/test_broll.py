"""The content engine (§5): per-tag resolution chains, caching, filler
floor, attribution — all offline."""

import json
import pathlib

import pytest
from PIL import Image

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


def test_pexels_cap_degrades_down_the_chain_never_aborts(settings, tmp_path):
    """A spent Pexels cap costs one link, not the whole chain.

    The cap is PEXELS' — the gif providers below it are free — so exhausting
    it falls through to them rather than jumping straight to a filler card.
    Both ends are asserted here: with the free providers present the clip
    still resolves, and with none configured it lands on filler, which is the
    guarantee that never changes.
    """
    capped = settings.model_copy(update={"pexels_monthly_call_cap": 0})

    def capped_manager(**kw):
        m = ContentManager(capped, library_dir=tmp_path / "library", **kw)

        class CapClient(MockPexelsClient):
            def search(self, query, per_page=5):
                m.ledger.check_pexels_budget()  # simulates the real client's gate
                return super().search(query, per_page)

        m.clip_client = CapClient(capped)
        return m

    clip = capped_manager().resolve_clip("dumpster_fire")
    assert clip.source == "mock", "a free provider must still be tried"
    assert clip.path.exists()

    # A DIFFERENT key, because the resolve above warmed the gif cache for
    # `dumpster_fire` and a cache hit would answer before any provider does —
    # which is correct behaviour and the wrong thing to be measuring here.
    bare = capped_manager(gif_clients=[]).resolve_clip("tumbleweed")
    assert bare.source == "filler", "cap exhaustion must degrade, never abort"


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


# ------------------------------------------------- illustration that moves
#
# `[MEME]` is still and `[CLIP]` moves. The tests below are the two halves of
# that one line, plus the chain that makes a SPECIFIC illustration reachable
# at all — Pexels is a stock library and will never have LeBron shooting a
# three, which is exactly what a clip written to prove a claim asks for.


class _NoResultsPexels(MockPexelsClient):
    """Pexels with nothing to say — the normal case for a real moment."""

    def search(self, query, per_page=5):
        self.search_calls.append(query)
        return {"videos": []}


class _Provider:
    """One gif provider, recording and optionally empty-handed."""

    def __init__(self, name, settings, hit=True):
        self.name = name
        self.settings = settings
        self.hit = hit
        self.search_calls: list[str] = []
        self.download_calls: list[str] = []

    def search(self, query, *, animated=False):
        self.search_calls.append(query)
        assert animated, "the clip chain must ask for the MOVING rendition"
        return f"mock://gif/{query.replace(' ', '-')}" if self.hit else None

    def download(self, url, dest):
        self.download_calls.append(url)
        from pipeline.memes import MockMemeClient

        return MockMemeClient(self.settings).download(url, dest)


def _distinct_frames(path, settings, times=(0.0, 0.5)) -> int:
    """How many DIFFERENT frames this clip shows across `times`.

    Counting frames proves nothing — a still normalised to 30fps is sixty
    identical frames of a man stopped mid-jump, which is the exact failure
    this is here to catch. So the frames are compared.
    """
    import hashlib
    import tempfile

    seen = set()
    with tempfile.TemporaryDirectory() as tmp:
        for i, t in enumerate(times):
            out = pathlib.Path(tmp) / f"f{i}.png"
            run_ffmpeg(["-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1",
                        str(out)])
            seen.add(hashlib.sha256(out.read_bytes()).hexdigest())
    return len(seen)


def test_an_animated_source_moves_as_a_clip_and_freezes_as_a_meme(settings, tmp_path):
    """The same gif, down both paths, and they must disagree.

    A clip of a shot going in, reduced to one frame, has lost the only thing
    that made it worth showing. A meme reduced to one frame IS the joke — the
    freeze is its timing. One provider, one query, two answers.
    """
    from pipeline.memes import MemeManager, MockMemeClient

    manager = ContentManager(
        settings, library_dir=tmp_path / "library",
        clip_client=_NoResultsPexels(settings),
        gif_clients=[_Provider("giphy", settings)],
        meme_manager=MemeManager(settings, providers=[MockMemeClient(settings)]),
    )

    clip = manager.resolve_clip("lebron three pointer")
    assert clip.source == "giphy" and clip.is_video
    assert clip.loops, "an animated source has to keep moving through its hold"
    assert _distinct_frames(clip.path, settings) == 2, \
        "the clip froze — this is the freeze-frame the meme path is for"

    meme = manager.resolve_meme("lebron three pointer")
    assert not meme.is_video
    with Image.open(meme.path) as img:
        assert img.format == "PNG"
        assert getattr(img, "n_frames", 1) == 1, "a meme is a freeze-frame"


def test_the_clip_chain_reaches_giphy_then_tenor_and_the_library_still_wins(
        settings, tmp_path):
    """owned library -> cache -> Pexels -> Giphy -> Tenor -> filler.

    Order is the whole point. Owned-library-first is what keeps the gif
    providers a fallback rather than the default, which is the mitigation for
    everything user-uploaded about them; Giphy before Tenor is arbitrary but
    fixed, so a swap is reproducible.
    """
    lib = tmp_path / "library"
    lib.mkdir()

    def build(giphy_hits, tenor_hits, library=False):
        giphy = _Provider("giphy", settings, hit=giphy_hits)
        tenor = _Provider("tenor", settings, hit=tenor_hits)
        m = ContentManager(settings, library_dir=lib,
                           clip_client=_NoResultsPexels(settings),
                           gif_clients=[giphy, tenor])
        return m, giphy, tenor

    # 1. Pexels misses, Giphy answers — Tenor is never asked.
    m, giphy, tenor = build(True, True)
    clip = m.resolve_clip("lebron three pointer")
    assert clip.source == "giphy"
    assert m.clip_client.search_calls, "Pexels is still asked first"
    assert giphy.search_calls and tenor.search_calls == []

    # 2. Giphy misses too — Tenor answers.
    m, giphy, tenor = build(False, True)
    clip = m.resolve_clip("a shot from a film nobody uploaded")
    assert clip.source == "tenor"
    assert giphy.search_calls and tenor.search_calls

    # 3. Nothing answers — the filler floor still holds.
    m, giphy, tenor = build(False, False)
    assert m.resolve_clip("nothing at all anywhere").source == "filler"

    # 4. The owned library beats every one of them, and is not even a fetch.
    run_ffmpeg([
        "-f", "lavfi", "-i", "color=c=red:size=640x360:rate=30:duration=2",
        "-c:v", "libx264", "-preset", "ultrafast", str(lib / "clown.mp4"),
    ])
    m, giphy, tenor = build(True, True)
    owned = m.resolve_clip("clown")
    assert owned.source == "local"
    assert m.clip_client.search_calls == []
    assert giphy.search_calls == [] and tenor.search_calls == []


def test_a_gif_clip_keeps_looping_out_of_the_cache(settings, tmp_path):
    """A second render of the same script must not freeze where the first moved.

    `loops` is a property of the SOURCE, so it has to survive the cache the
    same way attribution does — otherwise the re-render an operator does to
    fix visual placement is the one that quietly breaks the visual.
    """
    def build():
        return ContentManager(settings, library_dir=tmp_path / "library",
                              clip_client=_NoResultsPexels(settings),
                              gif_clients=[_Provider("giphy", settings)])

    first = build().resolve_clip("lebron three pointer")
    assert first.source == "giphy" and first.loops

    m = build()
    second = m.resolve_clip("lebron three pointer")
    assert second.source == "cache" and second.path == first.path
    assert second.loops, "the clip came back from the cache frozen"
    assert m.gif_clients[0].search_calls == [], "a cache hit must not re-fetch"


# --------------------------------------------------------------------------
# A3 / A4 — the Pexels quota. These assert on the COUNT the ledger ends up
# holding and on whether a request left at all, not on the arguments handed
# to a client: the old bugs were both invisible from the argument list.
# --------------------------------------------------------------------------


def test_one_clip_costs_one_api_call_not_two(settings, monkeypatch, tmp_path):
    """A3: search is the API call; the download is a CDN fetch."""
    import httpx

    from pipeline.broll import RealPexelsClient
    from pipeline.cost import SpendLedger

    live = settings.model_copy(update={"mock_mode": False,
                                       "pexels_api_key": "test-key",
                                       "pexels_min_interval_s": 0.0})
    ledger = SpendLedger(live)
    client = RealPexelsClient(live, ledger)

    monkeypatch.setattr("pipeline.broll.httpx.get", lambda *a, **k: httpx.Response(
        200, json={"videos": [{"id": 1, "video_files": []}]},
        request=httpx.Request("GET", "https://x")))

    class _Stream:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
        status_code = 200

        def iter_bytes(self, n):
            yield b"\x00" * 16

    monkeypatch.setattr("pipeline.broll.httpx.stream", lambda *a, **k: _Stream())

    client.search("dumpster fire burning night")
    client.download("https://cdn.example/clip.mp4", tmp_path / "raw.mp4")

    assert ledger.pexels_calls_this_month() == 1, \
        "the CDN fetch is not an API call and must not spend quota"


def test_a_search_that_never_comes_back_is_still_counted(settings, monkeypatch):
    """A3: the quota was spent the moment the request left.

    A 429 was already counted, because the old code recorded after the
    response object existed. A timeout or a dropped connection was not —
    the exception escaped before the record — and those are precisely the
    calls a rate limit produces. So the count is taken at dispatch.
    """
    import httpx

    from pipeline.broll import RealPexelsClient
    from pipeline.cost import SpendLedger

    live = settings.model_copy(update={"mock_mode": False,
                                       "pexels_api_key": "test-key",
                                       "pexels_min_interval_s": 0.0})
    ledger = SpendLedger(live)
    client = RealPexelsClient(live, ledger)

    def boom(*a, **k):
        raise httpx.ConnectTimeout("the request never came back")

    monkeypatch.setattr("pipeline.broll.httpx.get", boom)

    with pytest.raises(httpx.ConnectTimeout):
        client.search("anything")
    assert ledger.pexels_calls_this_month() == 1, \
        "a call that left and timed out still consumed the quota"


def test_opening_the_swap_menu_spends_no_quota(manager, monkeypatch):
    """A4: a number on a button is not worth an API call."""
    searched = []
    real_search = manager.clip_client.search

    def counting(query, per_page=5):
        searched.append(query)
        return real_search(query, per_page)

    monkeypatch.setattr(manager.clip_client, "search", counting)

    n = manager.alternates_count("dumpster_fire")

    assert n >= 1
    assert searched == [], "the swap menu must read the cache, not the provider"


def test_the_swap_count_is_still_a_number_a_swap_can_reach(manager, tmp_path):
    """Not spending on it must not make it useless.

    The count drives `(choice + 1) % n`, so an n of 1 makes the Swap button
    a no-op. It has to stay the range the chain can actually address.
    """
    n = manager.alternates_count("dumpster_fire")
    assert n > 1, "a swap has to be able to go somewhere"

    # Every take the count promises resolves to something, and consecutive
    # takes differ — which is what the operator tapped the button for.
    seen = {manager.resolve_clip("dumpster_fire", choice=i).path
            for i in range(n)}
    assert len(seen) > 1

    # An owned library adds to it, because those are extra reachable takes.
    lib = tmp_path / "library"
    lib.mkdir(parents=True, exist_ok=True)
    (lib / "dumpster_fire.mp4").write_bytes(b"\x00")
    assert manager.alternates_count("dumpster_fire") > n


# --------------------------------------------------------------------------
# H1 — the raw download filename has to carry the orientation too.
# --------------------------------------------------------------------------


def test_the_two_orientations_do_not_share_a_raw_download_path(manager):
    """Asserting on the files on disk, not on the string that was built."""
    manager.resolve_clip("dumpster_fire", portrait=False)
    manager.resolve_clip("dumpster_fire", portrait=True)

    cdir = manager._clip_cache_dir("dumpster_fire")
    # The raws are unlinked after normalising, so what is asserted is that
    # the two normalised outputs both survived — a shared raw path lets the
    # second fetch delete the first's input mid-normalise.
    norms = sorted(p.name for p in cdir.glob("normalized_*"))
    assert norms == ["normalized_0.mp4", "normalized_0_p.mp4"], norms

    import inspect

    src = inspect.getsource(manager._fetch_clip)
    assert 'raw_{choice}{suffix}' in src, \
        "the raw filename must be orientation-keyed like the normalised one"
