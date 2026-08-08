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

def test_a_bare_tag_resolves_off_the_workspaces_own_export(tmp_path_factory):
    """The whole point of the feature, on the real reader and a real workbook.

    MOCK_MODE never fetches anybody's website, so the screenshot itself does
    not happen here — the beat falls back to the headline card, silently,
    which is the specified behaviour. What is asserted is the resolution: the
    manifest records the URL and that nobody pasted it.
    """
    import json
    import shutil

    from config import Settings
    from pipeline.parser_short import parse_short_script
    from pipeline.render_short import render_short
    from pipeline.tts import TTSEngine

    root = Path(__file__).resolve().parents[1]
    export = root / "fixtures" / "company_data" / "dennis_data.xlsx"
    raw = json.loads((root / "fixtures" / "scripts" / "short_valid.json")
                     .read_text(encoding="utf-8"))
    raw["audio_script"] = "[SHOW ARTICLE] " + raw["audio_script"]
    # The writer's paraphrase of a story the export actually carries.
    raw["headlines"][0]["text"] = "EXMPL unveils next-gen routing platform"

    tmp = tmp_path_factory.mktemp("article_e2e")
    settings = Settings(MOCK_MODE=True, workspace_dir=tmp / "ws",
                        cache_dir=tmp / "cache", state_dir=tmp / "state",
                        short_width=540, short_height=960, _env_file=None)
    settings.ensure_runtime_dirs()
    script, _ = parse_short_script(json.dumps(raw), settings)
    assert [e for e in script.inline_events if e.type.value == "SHOW ARTICLE"], \
        "the bare tag has to survive the parser to reach the renderer"

    tts = TTSEngine(settings).synthesize(script.audio_script, "short",
                                         events=script.inline_events)
    ws = settings.workspace_dir / "EXMPL" / "article"
    ws.mkdir(parents=True)
    shutil.copy(export, ws / "dennis_data.xlsx")
    out, manifest_path = render_short(script, tts, ws, settings)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert len(manifest["articles"]) == 1, manifest["articles"]
    got = manifest["articles"][0]
    assert got["resolved"] == "auto", "nobody pasted this URL"
    assert got["value"] == "", "the tag carried no payload"
    assert got["url"] == "https://example.com/news/routing-platform"
    assert out.exists() and out.stat().st_size > 0


def test_an_export_with_no_matching_story_records_nothing(tmp_path_factory):
    """A headline the export does not carry must not screenshot the nearest row."""
    import json
    import shutil

    from config import Settings
    from pipeline.parser_short import parse_short_script
    from pipeline.render_short import render_short
    from pipeline.tts import TTSEngine

    root = Path(__file__).resolve().parents[1]
    raw = json.loads((root / "fixtures" / "scripts" / "short_valid.json")
                     .read_text(encoding="utf-8"))
    raw["audio_script"] = "[SHOW ARTICLE] " + raw["audio_script"]
    raw["headlines"] = [
        {"text": "Auditor resigns citing scope limitation",
         "meaning": "Nobody signed the numbers."},
    ]

    tmp = tmp_path_factory.mktemp("article_miss")
    settings = Settings(MOCK_MODE=True, workspace_dir=tmp / "ws",
                        cache_dir=tmp / "cache", state_dir=tmp / "state",
                        short_width=540, short_height=960, _env_file=None)
    settings.ensure_runtime_dirs()
    script, _ = parse_short_script(json.dumps(raw), settings)
    tts = TTSEngine(settings).synthesize(script.audio_script, "short",
                                         events=script.inline_events)
    ws = settings.workspace_dir / "EXMPL" / "article"
    ws.mkdir(parents=True)
    shutil.copy(root / "fixtures" / "company_data" / "dennis_data.xlsx",
                ws / "dennis_data.xlsx")
    out, manifest_path = render_short(script, tts, ws, settings)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["articles"] == [], \
        "a wrong screenshot is a false citation, not a near miss"
    assert out.exists()
