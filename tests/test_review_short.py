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
