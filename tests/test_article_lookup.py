"""Finding the real article behind a headline the writer paraphrased.

`[SHOW ARTICLE]` carried the URL and nothing else could supply one, so the
highest-credibility visual in the format needed somebody to go and find a
link — and so it was never used. The export already ships the news rows the
script was written from; the match is a token overlap.

The bar these hold is that a WRONG match is worse than none. A screenshot of
an unrelated story is a false citation, not a near miss, so the resolver has
to refuse a weak best match rather than take the least-bad row on offer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from pipeline.article_lookup import (
    MIN_OVERLAP,
    article_url,
    lead_url,
    resolve_url,
    score,
    top_article,
    workspace_news,
)


@dataclass
class _Headline:
    text: str
    meaning: str = ""


@dataclass
class _Script:
    ticker: str = "NVDA"
    headlines: list = field(default_factory=list)


NEWS = [
    {"date": "2026-07-28", "headline": "Nvidia signs $2B supply deal with Saudi AI venture",
     "source": "Reuters", "url": "https://reuters.com/nvda-saudi"},
    {"date": "2026-07-24", "headline": "Nvidia beats on datacenter revenue, guides higher",
     "source": "CNBC", "url": "https://cnbc.com/nvda-q2"},
    {"date": "2026-07-19", "headline": "US widens export licence rules for advanced chips",
     "source": "Bloomberg", "url": "https://bloomberg.com/chip-rules"},
]


# --------------------------------------------------------------------------
# scoring
# --------------------------------------------------------------------------

def test_paraphrase_matches_its_own_row():
    s = score("Nvidia signs a two billion dollar supply deal in Saudi Arabia",
              NEWS[0]["headline"])
    assert s >= MIN_OVERLAP


def test_unrelated_story_scores_below_the_floor():
    s = score("The buyback was funded with debt", NEWS[0]["headline"])
    assert s < MIN_OVERLAP


def test_the_company_name_is_not_evidence_of_a_match():
    """Every row of an NVDA export says "Nvidia" — it cannot be the signal.

    Left in, the shared subject token alone carries a two-word headline over
    the floor and the beat screenshots whichever row sorts first.
    """
    generic = "Nvidia stock moves"
    with_subject = score(generic, NEWS[1]["headline"])
    without = score(generic, NEWS[1]["headline"], frozenset({"nvidia"}))
    assert without < with_subject


# --------------------------------------------------------------------------
# resolution
# --------------------------------------------------------------------------

def test_resolves_the_matching_row():
    url = resolve_url("Nvidia signs $2B supply deal with a Saudi AI venture",
                      NEWS, ticker="NVDA")
    assert url == "https://reuters.com/nvda-saudi"


def test_a_weak_best_match_is_refused():
    """There is always a least-bad row. Taking it is a fabricated citation."""
    assert resolve_url("Management changed the segment reporting", NEWS,
                       ticker="NVDA") is None


def test_rows_without_a_usable_url_are_skipped():
    news = [{"headline": NEWS[0]["headline"], "url": ""},
            {"headline": NEWS[0]["headline"], "url": "n/a"},
            {"headline": "Nvidia signs $2B supply deal with Saudi AI venture",
             "url": "https://reuters.com/nvda-saudi"}]
    assert resolve_url("Nvidia signs $2B Saudi supply deal", news,
                       ticker="NVDA") == "https://reuters.com/nvda-saudi"


def test_no_news_resolves_to_nothing():
    assert resolve_url("anything at all", []) is None
    assert resolve_url("anything at all", None) is None


def test_lead_url_falls_through_to_a_headline_that_does_resolve():
    script = _Script(headlines=[_Headline("Margins compressed again"),
                                _Headline("US widens export licence rules on chips")])
    found = lead_url(script, NEWS)
    assert found is not None
    assert found[1] == "https://bloomberg.com/chip-rules"


def test_top_article_reads_news_off_company_data():
    @dataclass
    class _Data:
        news: list

    script = _Script(headlines=[_Headline("Nvidia beats on datacenter revenue")])
    assert top_article(script, _Data(news=NEWS))[1] == "https://cnbc.com/nvda-q2"


def test_top_article_with_no_news_is_none():
    @dataclass
    class _Data:
        news: list

    script = _Script(headlines=[_Headline("Nvidia beats on datacenter revenue")])
    assert top_article(script, _Data(news=[])) is None


# --------------------------------------------------------------------------
# what the renderer calls
# --------------------------------------------------------------------------

@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """A workspace whose export carries NEWS, without building a workbook."""
    import pipeline.company_data as cd

    class _Data:
        news = NEWS

    monkeypatch.setattr(cd, "load_company_data", lambda ws: _Data())
    return tmp_path


def test_a_pasted_url_is_used_as_written(tmp_path):
    url, how = article_url("https://ft.com/whatever", _Script(), tmp_path)
    assert (url, how) == ("https://ft.com/whatever", "pasted")


def test_a_bare_tag_resolves_off_the_lead_headline(workspace):
    script = _Script(headlines=[_Headline("Nvidia signs a $2B Saudi supply deal")])
    assert article_url("", script, workspace) == (
        "https://reuters.com/nvda-saudi", "auto")


def test_a_named_story_resolves_off_the_payload(workspace):
    """The writer described the row instead of linking it."""
    script = _Script(headlines=[_Headline("Nvidia signs a $2B Saudi supply deal")])
    url, how = article_url("Bloomberg on the export licence rules for chips",
                           script, workspace)
    assert (url, how) == ("https://bloomberg.com/chip-rules", "named")


def test_nothing_matching_falls_back_silently(workspace):
    script = _Script(headlines=[_Headline("The buyback was funded with debt")])
    assert article_url("", script, workspace) is None


def test_a_workspace_with_no_export_is_a_miss_not_a_crash(tmp_path):
    """The ordinary case for a hand-assembled run. It must not raise."""
    assert workspace_news(tmp_path) == []
    assert article_url("", _Script(headlines=[_Headline("anything")]),
                       tmp_path) is None


# --------------------------------------------------------------------------
# End to end: a bare tag, a real export, a manifest that says what happened.
# --------------------------------------------------------------------------

# The two render-integration tests that lived here are gone with the tag
# model. They asserted that a [SHOW ARTICLE] tag reached the renderer and was
# recorded in the render manifest — scene selection from the script, which is
# exactly what the shot templates removed. There is no article cutaway among
# the twelve shots, so there is nothing for the renderer to record.
#
# The resolution logic above is untouched and still covered: article_lookup
# still resolves a tag to a story off the workspace export. What changed is
# that nothing in the SHORT's visual layer consumes the result.
