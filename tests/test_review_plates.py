"""Findings from the full review of the plates, pictures and memes code.

Each test names what a viewer or the operator would have seen go wrong.
"""

from __future__ import annotations

import json

import httpx
from PIL import Image


def test_a_plate_tag_wrapped_over_lines_is_still_a_plate(settings,
                                                        long_valid_text):
    """The writer prompt's own numbers-sheet example wraps its tag; wrapped,
    the bracket stayed in the narration and the paid voice read the slots."""
    from pipeline.models import TagType
    from pipeline.parser_long import parse_long_script

    flat, _ = parse_long_script(long_valid_text, "EXMPL", settings)
    tag = ("[PLATE: big-number-l1-16x9 | kicker=FROM THE HIGH | value=-60% | "
           "label=and still not obviously cheap | caption=EXMPL, close to close]")
    assert tag in long_valid_text
    wrapped_tag = tag.replace(" | value", "\n  | value").replace(
        " | caption", "\n  | caption")
    wrapped, _ = parse_long_script(long_valid_text.replace(tag, wrapped_tag),
                                   "EXMPL", settings)

    def plates(s):
        return [e for e in s.events if e.type is TagType.PLATE]

    assert len(plates(wrapped)) == len(plates(flat))
    assert plates(wrapped)[0].values == plates(flat)[0].values
    assert "[PLATE" not in wrapped.narration
    assert wrapped.narration.split() == flat.narration.split()


def test_a_tag_left_unclosed_is_blocked_before_the_voice(settings,
                                                        long_valid_text):
    from pipeline.gates import direction_lint
    from pipeline.parser_long import parse_long_script

    broken = long_valid_text.replace(
        "| caption=EXMPL, close to close]", "| caption=EXMPL,\n\nclose to close]")
    script, _ = parse_long_script(broken, "EXMPL", settings)
    blocks = [f for f in direction_lint(script) if f.severity == "block"]
    assert any("[PLATE:" in f.message for f in blocks)
    clean, _ = parse_long_script(long_valid_text, "EXMPL", settings)
    assert not any("is still in the spoken text" in f.message
                   for f in direction_lint(clean))


def test_a_screengrab_is_shown_whole(settings, tmp_path):
    """A 4:3 grab was cover-cropped to 16:9 (cutting its top and bottom rows)
    and then shrunk a second time inside a margin."""
    from pipeline.broll import normalize_image

    src = tmp_path / "grab.png"
    img = Image.new("RGB", (1200, 900), (255, 255, 255))
    for y in list(range(12)) + list(range(888, 900)):
        for x in range(1200):
            img.putpixel((x, y), (255, 0, 0))
    img.save(src)
    out = normalize_image(src, tmp_path / "out.png", settings, keep_min=1.01)
    frame = Image.open(out).convert("RGB")
    assert frame.size == settings.long_resolution
    column = [frame.getpixel((960, y)) for y in range(frame.height)]
    reds = [y for y, (r, g, b) in enumerate(column) if r > 200 and g < 60]
    # Both bands made it: the top and the bottom of the grab are on screen.
    assert reds and reds[0] < 540 < reds[-1]
    assert reds[-1] - reds[0] > 0.8 * frame.height


def test_a_true_minus_on_a_short_cover_reads_as_a_fall(settings):
    """A summary opening on U+2212 became one shrunk "figure" in the rise ink."""
    from pipeline.rasters import role
    from pipeline.thumbnail import metric_colour, split_metric

    for minus in ("−", "–"):
        assert split_metric(f"{minus}12% today · 5x average volume") == (
            "TODAY · 5X AVERAGE VOLUME", "-12%")
        assert metric_colour(settings, f"{minus}12%", is_move=True) == role(
            settings, "down")


def test_a_fall_written_any_way_is_not_drawn_as_a_rise():
    from pipeline.plate_frames import _positive

    for fall in ("−12%", "–12%", "−$1.2bn", "(4.2%)", "(4.2)%", "-12%"):
        assert not _positive(fall), fall
    for rise in ("+12%", "12", "60", "$1.2bn"):
        assert _positive(rise), rise


def _manager(settings, tmp_path):
    from pipeline.broll import ContentManager

    return ContentManager(settings, library_dir=tmp_path / "library")


def test_a_swap_past_the_owned_clips_reaches_the_providers(settings, tmp_path):
    """With one owned clip, takes 2 to 6 all showed that same clip."""
    manager = _manager(settings, tmp_path)
    first = manager.resolve_clip("dumpster_fire", choice=0)
    second = manager.resolve_clip("dumpster_fire", choice=1)

    lib = tmp_path / "library"
    lib.mkdir(parents=True, exist_ok=True)
    (lib / "dumpster_fire.mp4").write_bytes(b"\x00")
    assert manager.alternates_count("dumpster_fire") == 6
    # Take 1 is the owned clip; takes 2 and 3 are the providers' first two.
    assert manager.resolve_clip("dumpster_fire", choice=1).path == first.path
    assert manager.resolve_clip("dumpster_fire", choice=2).path == second.path


def test_a_cut_short_clip_credit_does_not_stop_the_render(settings, tmp_path):
    manager = _manager(settings, tmp_path)
    cdir = manager._clip_cache_dir("dumpster_fire")
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / "normalized_0.mp4").write_bytes(b"clip")
    (cdir / "meta_0.json").write_text('{"attribution": "Video by', "utf-8")
    clip = manager.resolve_clip("dumpster_fire")
    assert clip.source == "cache"
    assert clip.path == cdir / "normalized_0.mp4"


def test_a_meme_whose_download_fails_asks_the_next_provider(settings):
    from pipeline.memes import MemeManager, MockMemeClient

    class Broken:
        name = "broken"

        def search(self, query, *, animated=False):
            return "https://example.invalid/meme.gif"

        def download(self, url, dest):
            raise httpx.ConnectError("404")

    second = MockMemeClient(settings)
    meme = MemeManager(settings, providers=[Broken(), second]).resolve(
        "zz-review-no-such-meme")
    assert meme.source == "mock"
    assert second.search_calls

    # A credit cut short loses the credit, not the meme.
    cdir = MemeManager(settings)._cache_dir("zz-review-no-such-meme")
    (cdir / "meta.json").write_text('{"attri', encoding="utf-8")
    again = MemeManager(settings, providers=[]).resolve("zz-review-no-such-meme")
    assert again.source == "cache"


def test_the_kit_doctor_counts_what_renders_put_on_screen(settings):
    """It read a ledger nothing ever wrote, so every plate stayed
    "never reached" however many videos had shipped."""
    from pipeline.reach import plates_by_render, recent_plates

    for day, used in (("2026-10-01", ["cards/a-16x9"]),
                      ("2026-10-02", ["cards/b-16x9", "cards/a-16x9"])):
        ws = settings.workspace_dir / "EXMPL" / day
        ws.mkdir(parents=True, exist_ok=True)
        (ws / "render_manifest.json").write_text(
            json.dumps({"plates_used": used}), encoding="utf-8")
    bad = settings.workspace_dir / "EXMPL" / "2026-10-03"
    bad.mkdir(parents=True)
    (bad / "render_manifest.json").write_text("[1, 2]", encoding="utf-8")

    rendered = plates_by_render(settings)
    assert len(rendered) == 2
    assert recent_plates(settings) == {"cards/a-16x9", "cards/b-16x9"}
