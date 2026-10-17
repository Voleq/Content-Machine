"""Short-lane fixes from the full code review (10-16)."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def resolver(settings):
    from pipeline.parser_short import parse_short_script
    from pipeline.render_short import ShortResolver

    raw = (ROOT / "fixtures" / "scripts" / "short_valid.json").read_text(encoding="utf-8")
    script, _ = parse_short_script(raw, settings)
    return ShortResolver(script=script, workdir=ROOT, settings=settings,
                         prices=None, handle="@channel")


def _picture(source, provider="", attribution=""):
    from pipeline.broll import Visual

    return Visual(key="x", kind="img", path=ROOT / "README.md", is_video=False,
                  source=source, provider=provider, attribution=attribution)


@pytest.mark.parametrize("pic, line", [
    (("cache", "wikimedia"), "Photo: Wikimedia Commons"),
    (("cache", "company_site"), "Photo: the company's website"),
    (("wikimedia", "wikimedia"), "Photo: Wikimedia Commons"),
    (("cache", "", "Jane Roe, CC BY 4.0"), "Photo: Jane Roe, CC BY 4.0"),
    (("cache",), "Photo: see the credits"),
])
def test_a_cached_picture_credits_who_took_it_not_the_cache(resolver, pic, line):
    resolver._pictures = {"company": _picture(*pic)}
    assert resolver.text_for("pic.company.source") == line


@pytest.mark.parametrize("field, value", [
    ("cheap_or_trap", "per Capital IQ the multiple is cheap"),
    ("turn_line", "FactSet says otherwise"),
    ("mechanism", ["Refinitiv shows the margin"]),
    ("payoff_row", "LSEG margin"),
])
def test_the_vendor_block_covers_every_drawn_field(settings, field, value):
    """Only five fields were checked; cheap_or_trap, the turn line and the
    rest are drawn on cards too."""
    from pipeline.parser_short import parse_short_script, vendor_name_hits

    raw = (ROOT / "fixtures" / "scripts" / "short_valid.json").read_text(encoding="utf-8")
    script, _ = parse_short_script(raw, settings)
    assert vendor_name_hits(script) == []
    leaked = script.model_copy(update={field: value})
    assert any(h.startswith(field) for h in vendor_name_hits(leaked))


def test_one_vendor_list_for_both_lanes_and_the_lint():
    from pipeline import gates, models, parser_long, parser_short

    assert parser_short.VENDOR_WORDS is models.VENDOR_WORDS
    assert parser_long.VENDOR_WORDS is models.VENDOR_WORDS
    assert gates._VENDORS is models.VENDOR_WORDS


def test_the_thinned_price_line_keeps_its_high_and_low():
    """The high and low marks print the full series' extremes; the thinned
    line used to lose one or the other about half the time."""
    import random

    from pipeline.prices import PriceSeries
    from pipeline.render_short import CHART_MAX_POINTS, _legible

    rng = random.Random(7)
    for n in (83, 97, 120):
        for _ in range(50):
            closes = [100 + rng.uniform(-5, 5) for _ in range(n)]
            dates = [f"2026-01-{i:03d}" for i in range(n)]
            thin = _legible(PriceSeries("XYZ", dates, closes))
            assert max(thin.closes) == max(closes)
            assert min(thin.closes) == min(closes)
            assert thin.closes[-1] == closes[-1] and thin.dates[0] == dates[0]
            assert len(thin.closes) <= CHART_MAX_POINTS + 3


# -- a split beat, the tail pin, the anchors, the repeat, the figures ------

class _Word:
    def __init__(self, word, start, end):
        self.word, self.start, self.end = word, start, end


def _bare(sid, **extra):
    return {"id": sid, "plate": None, "captions": False,
            "text": [{"src": f"script.{sid}", "size_fh": 0.07}], **extra}


def _fmt(*shots):
    from pipeline.shots import parse_format

    return parse_format({"format": "t", "aspect": "9x16",
                         "frame": {"w": 1080, "h": 1920}, "shots": list(shots)})


@pytest.mark.parametrize("at, owner", [("end", "payoff-in"), ("start", "payoff")])
def test_a_split_beat_keeps_its_meme_on_the_part_that_owns_that_end(at, owner):
    from pipeline.shots import resolve_spans

    fmt = _fmt(_bare("a", max_hold_s=30),
               {"id": "payoff", "plate": "charts/line-dense-9x16",
                "max_hold_s": 3, "captions": False, "meme": at,
                "text": [{"src": "script.payoff", "size_fh": 0.07}]})
    spans = resolve_spans(fmt, [], 10.0, {}, punch_in=lambda sh: "plot-area")
    assert [s.shot.id for s in spans] == ["a", "payoff", "payoff-in"]
    assert [s.shot.id for s in spans if s.shot.meme] == [owner]


def test_a_last_beat_on_the_last_words_never_overlaps_the_one_before():
    from pipeline.shots import resolve_spans

    fmt = _fmt(_bare("a", max_hold_s=30),
               _bare("payoff", anchor="payoff", max_hold_s=30),
               _bare("close", anchor="close", max_hold_s=30))
    words = [_Word("so", 0.0, 0.3), _Word("the", 22.9, 23.0),
             _Word("payoff", 23.0, 23.3), _Word("is.", 23.3, 23.6),
             _Word("and", 23.7, 23.8), _Word("done", 23.8, 23.9),
             _Word("now.", 23.9, 24.0)]
    spans = resolve_spans(fmt, words, 24.0, {"payoff": "the payoff is",
                                             "close": "and done now"})
    assert spans[-1].end == 24.0
    assert spans[-1].end - spans[-1].start >= 0.8 - 1e-9
    for before, after in zip(spans, spans[1:]):
        assert before.end <= after.start + 1e-9, (before, after)


def test_the_print_listens_for_what_was_reported(settings):
    from pipeline.parser_short import parse_short_script
    from pipeline.render_short import build_anchors
    from pipeline.shots import load_format

    raw = (ROOT / "fixtures" / "scripts" / "earnings_valid.json").read_text(encoding="utf-8")
    script, _ = parse_short_script(raw, settings)
    built = set(build_anchors(script))
    assert "reported" in built
    anchored = set()
    for name in ("short", "earnings", "macro"):
        for sh in load_format(name).shots:
            anchored |= {sh.anchor} if sh.anchor else set()
            if sh.repeat and sh.repeat.anchor:
                anchored.add(sh.repeat.anchor.split(".")[0])
    # Every key built is one a template listens for (marks aside).
    marks = {m.key for m in (script.beat_marks or ())}
    assert built - marks - anchored - {"numbers.1", "numbers.2", "numbers.3"} == set()


@pytest.mark.parametrize("arrange", ["grid", "row", "column"])
def test_a_list_placed_side_by_side_is_refused_by_name(arrange):
    from pipeline.shots import TemplateError

    with pytest.raises(TemplateError, match="sequence"):
        _fmt({"id": "cards", "plate": None, "captions": False,
              "repeat": {"src": "script.consequences", "arrange": arrange}})


def test_a_card_concept_on_a_list_is_refused():
    from pipeline.shots import TemplateError

    with pytest.raises(TemplateError):
        _fmt({"id": "cards", "plate": None, "captions": False,
              "repeat": {"src": "script.consequences", "arrange": "sequence",
                         "concept": "cards/consequence"}})


@pytest.mark.parametrize("v, text", [(999.6e6, "$1B"), (999.4e3, "$999K"),
                                     (496e6, "$496M"), (-89e6, "-$89M"),
                                     (1.234e9, "$1.23B")])
def test_money_rounds_before_it_picks_the_suffix(v, text):
    from pipeline.short_data import money

    assert money(v) == text


@pytest.mark.parametrize("v, text", [(-0.04, "0%"), (9.96, "10%"),
                                     (58.0, "58%"), (5.5, "5.5%"),
                                     (12.6, "13%")])
def test_a_rate_never_prints_minus_zero_or_ten_point_oh(v, text):
    from pipeline.short_data import rate

    assert rate(v) == text


def test_a_missing_ffmpeg_leaves_no_log_behind(tmp_path, monkeypatch):
    import subprocess

    from pipeline import render_short

    def _no_ffmpeg(*a, **k):
        raise FileNotFoundError("ffmpeg")

    monkeypatch.setattr(subprocess, "Popen", _no_ffmpeg)

    class _Result:
        frame = (1080, 1920)
        layers = []

        def of_kind(self, kind):
            return []

    class _Reg:
        def colour(self, key):
            return (240, 232, 214)

    out = tmp_path / "frames.mp4"
    with pytest.raises(render_short.RenderError, match="could not start ffmpeg"):
        render_short.render_frames(_Result(), None, 1.0, out,
                                   _settings_for_frames(), reg=_Reg())
    assert not out.with_suffix(".ffmpeg.log").exists()


def _settings_for_frames():
    from config import Settings

    return Settings(_env_file=None)


def test_two_lines_of_bare_type_draw_one_under_the_other(settings):
    from PIL import Image

    from pipeline.compose import Layer
    from pipeline.render_short import _draw_text

    class _Reg:
        def colour(self, key):
            return (20, 20, 20)

    canvas = Image.new("RGBA", (1080, 1920), (255, 255, 255, 255))
    layer = Layer(name="t", kind="text", shot_id="s", t_start=0, t_end=1,
                  x=90, y=600, w=900, h=700, size_fh=0.05, max_lines=3,
                  text="The guide went up and the line stayed flat")
    _draw_text(canvas, layer, settings, _Reg(), {})
    ink = [y for y in range(1920)
           if any(canvas.getpixel((x, y))[0] < 128 for x in range(90, 990, 3))]
    # Ink in at least two separate bands: two lines, not one stacked on itself.
    bands = sum(1 for a, b in zip(ink, ink[1:]) if b - a > 8) + 1
    assert bands >= 2, (ink[:3], ink[-3:])
