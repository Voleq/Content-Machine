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
