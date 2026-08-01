"""Golden frames, by-products and the status page (P3.6).

The render tests assert on filter graphs and manifests, which catches a wrong
argument and not a host who has gone invisible against a new backdrop — a bug
this project has actually shipped. Golden frames are the check for that class
of failure, and the tolerance is the whole design: byte comparison fails on
every ffmpeg build, a loose threshold notices nothing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from pipeline.byproducts import (
    BYPRODUCT_FAMILIES,
    DEFAULT_TOLERANCE,
    ByProducts,
    bless,
    build_byproducts,
    check_report,
    compare_against_golden,
    frame_distance,
    golden_dir,
    key_times,
)


@pytest.fixture(autouse=True)
def _isolated_goldens(settings, tmp_path):
    """Bless into tmp, never into the repo's fixtures.

    Without this a test run leaves reference frames in `fixtures/golden/`,
    which is both dirty and dangerous: the next run would compare against
    whatever the last run happened to produce.
    """
    settings.golden_dir = str(tmp_path / "goldens")
    return settings


def _frame(path: Path, colour=(240, 240, 236), box=None) -> Path:
    img = Image.new("RGB", (640, 360), colour)
    if box:
        ImageDraw.Draw(img).rectangle(box, fill=(200, 32, 42))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return path


# --------------------------------------------------------------------------
# The tolerance: encoder noise below, real change above.
# --------------------------------------------------------------------------


def test_an_identical_frame_has_no_distance(tmp_path):
    a = _frame(tmp_path / "a.png", box=(100, 100, 300, 250))
    b = _frame(tmp_path / "b.png", box=(100, 100, 300, 250))
    assert frame_distance(a, b) == 0.0


def test_encoder_noise_stays_under_the_tolerance(tmp_path):
    """Two encodes of the same source differ on nearly every pixel by a
    little. Any threshold that failed on that would be useless."""
    a = _frame(tmp_path / "a.png", box=(100, 100, 300, 250))
    img = Image.open(a).convert("RGB")
    px = img.load()
    for y in range(0, img.height, 2):          # ±2 dither over half the frame
        for x in range(0, img.width, 2):
            r, g, bch = px[x, y]
            px[x, y] = (min(255, r + 2), max(0, g - 2), bch)
    noisy = tmp_path / "noisy.png"
    img.save(noisy)
    assert frame_distance(a, noisy) < DEFAULT_TOLERANCE


def test_a_moved_element_goes_over_the_tolerance(tmp_path):
    """The regression this exists to catch: something shifted on screen."""
    a = _frame(tmp_path / "a.png", box=(100, 100, 300, 250))
    b = _frame(tmp_path / "b.png", box=(260, 100, 460, 250))
    assert frame_distance(a, b) > DEFAULT_TOLERANCE


def test_a_changed_plate_colour_goes_over_the_tolerance(tmp_path):
    """The exact bug that shipped once: dark ink on a dark plate."""
    light = _frame(tmp_path / "light.png", colour=(242, 242, 239))
    dark = _frame(tmp_path / "dark.png", colour=(24, 24, 28))
    assert frame_distance(light, dark) > DEFAULT_TOLERANCE * 3


def test_distance_is_symmetric(tmp_path):
    a = _frame(tmp_path / "a.png", box=(10, 10, 60, 60))
    b = _frame(tmp_path / "b.png", box=(90, 90, 140, 140))
    assert frame_distance(a, b) == frame_distance(b, a)


# --------------------------------------------------------------------------
# Sampling.
# --------------------------------------------------------------------------


def test_key_times_avoid_the_very_edges():
    """The first and last frames are a fade — least informative, most likely
    to differ for uninteresting reasons."""
    times = key_times(100.0, n=6)
    assert len(times) == 6
    assert times[0] > 0.0
    assert times[-1] < 100.0
    assert times == sorted(times)


def test_a_very_short_clip_gets_one_sample():
    assert key_times(1.0) == [0.5]
    assert key_times(0) == []


# --------------------------------------------------------------------------
# Blessing and comparing.
# --------------------------------------------------------------------------


def test_blessing_then_comparing_passes(settings, tmp_path):
    frames = [_frame(tmp_path / f"t{i}.png", box=(i * 10, 10, i * 10 + 50, 60))
              for i in range(3)]
    assert bless(frames, settings, "long") == 3
    diffs = compare_against_golden(frames, settings, "long")
    assert len(diffs) == 3
    assert all(d.ok for d in diffs)
    assert "3/3" in check_report(diffs)


def test_a_changed_frame_fails_the_comparison(settings, tmp_path):
    original = [_frame(tmp_path / "t0.png", box=(10, 10, 60, 60))]
    bless(original, settings, "long")
    moved = [_frame(tmp_path / "t0.png", box=(300, 200, 350, 250))]
    diffs = compare_against_golden(moved, settings, "long")
    assert not diffs[0].ok
    assert "A frame moved" in check_report(diffs)


def test_a_frame_with_no_golden_is_a_miss_not_a_pass(settings, tmp_path):
    """"We have no reference for this" and "this matches" must not look
    alike."""
    bless([_frame(tmp_path / "t0.png")], settings, "long")
    fresh = [_frame(tmp_path / "t0.png"), _frame(tmp_path / "t9.png")]
    diffs = compare_against_golden(fresh, settings, "long")
    by_name = {d.name: d for d in diffs}
    assert by_name["t0.png"].ok
    assert not by_name["t9.png"].ok


def test_no_goldens_at_all_says_so(settings, tmp_path):
    diffs = compare_against_golden([_frame(tmp_path / "t0.png")], settings, "never")
    assert diffs == []
    assert "No goldens stored" in check_report(diffs)


def test_blessing_is_explicit_never_a_side_effect(settings, tmp_path):
    """Otherwise the first accidental regression silently becomes the truth."""
    frames = [_frame(tmp_path / "t0.png", box=(10, 10, 60, 60))]
    bless(frames, settings, "long")
    moved = [_frame(tmp_path / "t0.png", box=(300, 200, 350, 250))]
    compare_against_golden(moved, settings, "long")          # a failing compare…
    diffs = compare_against_golden(moved, settings, "long")  # …changed nothing
    assert not diffs[0].ok


def test_the_stored_tolerance_is_used(settings, tmp_path):
    frames = [_frame(tmp_path / "t0.png", box=(10, 10, 60, 60))]
    bless(frames, settings, "long")
    manifest = golden_dir(settings, "long") / "golden.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["tolerance"] = 200.0        # absurdly permissive
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    moved = [_frame(tmp_path / "t0.png", box=(300, 200, 350, 250))]
    assert compare_against_golden(moved, settings, "long")[0].ok


# --------------------------------------------------------------------------
# By-products: the assets that already exist and go unused.
# --------------------------------------------------------------------------


def test_a_render_emits_the_whole_set(settings, tmp_path):
    made = build_byproducts(tmp_path, settings, ticker="EXMPL")
    assert made.thumbnails, "no thumbnails"
    assert made.social, "no social cards"
    assert made.end_screens, "no end screens"
    assert made.total() >= 20


def test_every_by_product_is_a_real_image(settings, tmp_path):
    build_byproducts(tmp_path, settings, ticker="EXMPL")
    files = list((tmp_path / "byproducts").glob("*.png"))
    assert files
    for f in files:
        with Image.open(f) as img:
            assert img.size[0] > 100 and img.size[1] > 100, f.name


def test_the_ticker_reaches_the_artwork(settings, tmp_path):
    """A blank layout is not a by-product."""
    build_byproducts(tmp_path, settings, ticker="EXMPL")
    src_kit = None
    from pipeline.kit import load_kit

    kit = load_kit(settings.assets_dir)
    first = kit.family(BYPRODUCT_FAMILIES["thumbnails"][0][0])[0]
    src_kit = kit.path(first)
    made = tmp_path / "byproducts" / f"thumbnails_{first.rsplit('/', 1)[-1]}.png"
    assert made.exists()
    assert frame_distance(src_kit, made) > 0, "nothing was drawn on it"


def test_the_families_cover_what_the_kit_ships(settings):
    from pipeline.kit import load_kit

    kit = load_kit(settings.assets_dir)
    for label, (families, cap) in BYPRODUCT_FAMILIES.items():
        shipped = [a for fam in families for a in kit.family(fam)]
        assert shipped, f"{label} draws from {families}, all of them empty"
        assert cap >= len(shipped), \
            f"{label} ships {len(shipped)} but the cap silently trims to {cap}"


def test_one_broken_layout_does_not_cost_the_others(settings, tmp_path,
                                                    monkeypatch):
    import pipeline.byproducts as bp

    calls = {"n": 0}
    real = bp._compose

    def flaky(src, dest, **kw):
        calls["n"] += 1
        if calls["n"] % 3 == 0:
            raise RuntimeError("bad layout")
        return real(src, dest, **kw)

    monkeypatch.setattr(bp, "_compose", flaky)
    made = build_byproducts(tmp_path, settings, ticker="EXMPL")
    assert made.total() > 10, "one failure took the rest with it"


def test_a_manifest_records_what_was_made(settings, tmp_path):
    build_byproducts(tmp_path, settings, ticker="EXMPL")
    payload = json.loads((tmp_path / "byproducts" / "byproducts.json").read_text(encoding="utf-8"))
    assert set(payload) == {"thumbnails", "social", "end_screens"}


def test_no_data_is_survivable(settings, tmp_path):
    """A by-product with no shock metric is still a by-product."""
    made = build_byproducts(tmp_path, settings, ticker="EXMPL", data=None)
    assert made.total() > 0


# --------------------------------------------------------------------------
# The status page: read-only, loopback only.
# --------------------------------------------------------------------------


def test_the_page_renders_with_nothing_in_it(settings):
    from pipeline.status_page import render_page

    html = render_page(settings)
    assert "<!doctype html>" in html
    assert "Telegram is still the control channel" in html
    assert "nothing rendered yet" in html


def test_the_page_shows_what_state_there_is(settings):
    from pipeline.standing import IdeaQueue
    from pipeline.status_page import render_page

    IdeaQueue(settings).add("EXMPL", "beaten down and hated", "screener",
                            lane="long")
    html = render_page(settings)
    assert "EXMPL" in html
    assert "beaten down and hated" in html


def test_a_broken_panel_does_not_break_the_page(settings, monkeypatch):
    """A page that 500s because one JSON file is corrupt is worse than a page
    with one empty panel."""
    import pipeline.status_page as sp

    monkeypatch.setattr(sp, "_ideas_section",
                        lambda s: (_ for _ in ()).throw(RuntimeError("boom")))
    html = sp.render_page(settings)
    assert "<!doctype html>" in html
    assert "unreadable" in html


def test_content_is_escaped(settings):
    """State is operator-supplied text; it must not be able to inject markup."""
    from pipeline.standing import IdeaQueue
    from pipeline.status_page import render_page

    IdeaQueue(settings).add("EXMPL", "<script>alert(1)</script>", "operator")
    html = render_page(settings)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_it_is_off_by_default_and_binds_loopback_when_on(settings):
    """No authentication and it shows internals, so it must never be reachable
    from the network."""
    from pipeline.status_page import serve

    assert not settings.status_page_enabled
    assert serve(settings) is None

    on = settings.model_copy(update={"status_page_enabled": True,
                                     "status_page_port": 0})
    server = serve(on)
    try:
        assert server is not None
        assert server.server_address[0] == "127.0.0.1"
    finally:
        if server:
            server.shutdown()
            server.server_close()
