"""Golden frames, the status page and delivery notes.

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

from pipeline.frame_checks import (
    DEFAULT_TOLERANCE,
    bless,
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


def test_the_queue_panel_lists_the_newest_jobs(settings):
    """Job ids are random, so the last twelve files by name were any twelve
    jobs; the panel lists the newest, like /status."""
    from pipeline.status_page import _queue_section

    jobs = settings.state_dir / "jobs"
    jobs.mkdir(parents=True, exist_ok=True)
    for n in range(14):
        # ids that sort the opposite way to when the jobs ran
        (jobs / f"{99 - n:02d}.json").write_text(json.dumps({
            "id": f"{99 - n:02d}", "kind": "render_short",
            "ticker": f"T{n:02d}", "status": "done",
            "updated_at": f"2026-09-{n + 1:02d}T00:00:00Z"}), encoding="utf-8")
    (jobs / "zz.json").write_text("{", encoding="utf-8")
    html = _queue_section(settings)
    assert "T13" in html and "T02" in html
    assert "T01" not in html and "T00" not in html
    assert html.index("T13") < html.index("T12")


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


def test_a_backend_s_own_note_survives_the_credits(settings, tmp_path):
    """`deliver` assigned `result.note`, which discards whatever the backend
    had put there. No backend sets one today — and that is the kind of
    harmless that stops being true the first time one wants to say "the 2 GB
    file went to Drive instead"."""
    from pipeline import delivery as dmod

    artifact = tmp_path / "long_final.mp4"
    artifact.write_bytes(b"video")

    def _fake(art, ticker, workdate, s, extra):
        return dmod.DeliveryResult(backend="local", link=str(art),
                                   note="the backend had something to say")

    original = dmod._local_deliver
    dmod._local_deliver = _fake
    try:
        got = dmod.deliver(artifact, "EXMPL", "2026-09-19", settings)
    finally:
        dmod._local_deliver = original

    assert "the backend had something to say" in got.note
