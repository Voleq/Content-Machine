"""Free data sources (P3.4).

The paid export is the spine of a video but says nothing about today. These
are the feeds that make short-form possible without a data terminal.

The rule every one of them obeys, and what most of this file checks: a source
that is down, keyless, or has nothing to say returns **"unavailable"** — never
an exception, never an empty result dressed up as data. A run must survive any
of them being broken.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.sources import (
    FRED_SERIES,
    TTL_SECONDS,
    UNAVAILABLE,
    cached,
    fred_series,
    institutional_holders,
    insider_transactions,
    ir_feed,
    latest_8k,
    parse_rss,
    store,
    summarise,
    transcribe,
    whisper_available,
)

RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>EXMPL IR</title>
  <item><title>EXMPL to Report Q2</title><link>https://ir/1</link>
        <pubDate>Tue, 21 Jul 2026 12:00:00 GMT</pubDate></item>
  <item><title>EXMPL Announces Buyback</title><link>https://ir/2</link></item>
</channel></rss>"""

ATOM = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry><title>Atom item one</title>
         <link href="https://ir/a1"/><updated>2026-07-21T12:00:00Z</updated></entry>
</feed>"""


# --------------------------------------------------------------------------
# 8-K + EX-99.1 — the numbers are in the exhibit, not the cover page.
# --------------------------------------------------------------------------


def test_the_8k_carries_its_exhibit(settings):
    """An 8-K on its own says a press release was issued and not what it said."""
    got = latest_8k("EXMPL", settings)
    assert got["status"] == "ok"
    assert got["form"] == "8-K"
    assert got["exhibit_url"], "no EX-99.1 — the numbers would be missing"
    assert "Revenue" in got["exhibit_text"]


def test_the_exhibit_text_is_usable_prose(settings):
    text = latest_8k("EXMPL", settings)["exhibit_text"]
    assert "<" not in text, "HTML leaked into the text"
    assert "496" in text


def test_html_stripping_survives_scripts_and_entities():
    from pipeline.sources import _strip_html

    out = _strip_html(
        "<html><style>p{}</style><script>x()</script>"
        "<p>Revenue&nbsp;of&nbsp;$496&#8217;m &amp; rising</p></html>")
    assert "x()" not in out and "p{}" not in out
    assert "Revenue of $496'm & rising" in out


# --------------------------------------------------------------------------
# Form 4 and 13F.
# --------------------------------------------------------------------------


def test_form_4s_come_back_with_dates(settings):
    got = insider_transactions("EXMPL", settings)
    assert got["status"] == "ok"
    assert got["count"] >= 1
    assert all(f["filed"] for f in got["filings"])


def test_13f_says_out_loud_that_it_is_stale(settings):
    """It is always a story about last quarter — a script needs to say so
    rather than implying somebody bought it yesterday."""
    got = institutional_holders("EXMPL", settings)
    assert "45 days" in got["as_of_note"]


# --------------------------------------------------------------------------
# FRED.
# --------------------------------------------------------------------------


def test_friendly_names_map_to_series_ids():
    assert FRED_SERIES["cpi"] == "CPIAUCSL"
    assert FRED_SERIES["unemployment"] == "UNRATE"


def test_a_series_comes_back_oldest_first_with_a_latest(settings):
    got = fred_series("cpi", settings)
    assert got["status"] == "ok"
    obs = got["observations"]
    assert len(obs) > 1
    assert got["latest"] == obs[-1], "latest must be the newest observation"


def test_the_change_is_computed_both_ways(settings):
    change = fred_series("cpi", settings)["change"]
    assert "mom" in change and "yoy" in change


def test_a_series_change_needs_enough_points():
    from pipeline.sources import _series_change

    assert _series_change([]) == {}
    assert _series_change([{"date": "a", "value": 1.0}]) == {}
    two = _series_change([{"date": "a", "value": 100.0},
                          {"date": "b", "value": 110.0}])
    assert two == {"mom": 10.0}, two


def test_no_fred_key_is_unavailable_not_an_error(settings):
    live = settings.model_copy(update={"mock_mode": False, "fred_api_key": ""})
    got = fred_series("cpi", live)
    assert got["status"] == UNAVAILABLE
    assert "FRED_API_KEY" in got["reason"]


def test_a_raw_series_id_is_accepted_too(settings):
    live = settings.model_copy(update={"mock_mode": False, "fred_api_key": ""})
    assert fred_series("DTWEXBGS", live)["series"] == "DTWEXBGS"


# --------------------------------------------------------------------------
# IR RSS.
# --------------------------------------------------------------------------


def test_rss_is_parsed(settings):
    items = parse_rss(RSS)
    assert [i.title for i in items] == ["EXMPL to Report Q2",
                                        "EXMPL Announces Buyback"]
    assert items[0].link == "https://ir/1"


def test_atom_is_parsed_too(settings):
    """Whichever the company's CMS emits."""
    items = parse_rss(ATOM)
    assert len(items) == 1
    assert items[0].title == "Atom item one"
    assert items[0].link == "https://ir/a1"


def test_malformed_xml_is_no_items_rather_than_a_crash():
    assert parse_rss("this is not xml at all") == []
    assert parse_rss("") == []


def test_the_feed_limit_is_honoured():
    many = ("<rss><channel>"
            + "".join(f"<item><title>t{i}</title></item>" for i in range(50))
            + "</channel></rss>")
    assert len(parse_rss(many, limit=5)) == 5


def test_ir_items_become_backlog_entries(settings):
    from pipeline.sources import ideas_from_ir
    from pipeline.standing import IdeaQueue

    n = ideas_from_ir(settings, "EXMPL", "https://ir.example.com/rss")
    assert n >= 1
    top = IdeaQueue(settings).ranked()[0]
    assert top.ticker == "EXMPL" and top.source == "ir"


def test_an_unavailable_feed_adds_nothing(settings, monkeypatch):
    from pipeline import sources as src
    from pipeline.standing import IdeaQueue

    monkeypatch.setattr(src, "ir_feed",
                        lambda *a, **k: {"status": UNAVAILABLE})
    assert src.ideas_from_ir(settings, "EXMPL", "https://x") == 0
    assert IdeaQueue(settings).ranked() == []


# --------------------------------------------------------------------------
# Degrading, and never blocking.
# --------------------------------------------------------------------------


def test_a_dead_network_is_unavailable_not_an_exception(settings, monkeypatch):
    """The whole contract: a broken source must not fail a run."""
    live = settings.model_copy(update={"mock_mode": False,
                                       "fred_api_key": "x"})

    class Boom:
        @staticmethod
        def get(*a, **k):
            raise RuntimeError("network is down")

    monkeypatch.setitem(__import__("sys").modules, "httpx", Boom)
    got = fred_series("cpi", live)
    assert got["status"] == UNAVAILABLE
    assert "network is down" in got["reason"]


def test_an_edgar_miss_is_unavailable_with_a_reason(settings, monkeypatch):
    from pipeline import sources as src

    live = settings.model_copy(update={"mock_mode": False})
    monkeypatch.setattr(src, "_filings_of", lambda *a, **k: [])
    for fn in (latest_8k, insider_transactions):
        got = fn("NOSUCH", live)
        assert got["status"] == UNAVAILABLE
        assert got.get("reason"), fn.__name__


def test_whisper_is_optional_and_says_so(settings):
    ok, why = whisper_available(settings)
    assert not ok
    assert "switched off" in why or "Whisper" in why


def test_transcription_never_raises(settings):
    """Best-effort by definition: nothing downstream waits on it."""
    got = transcribe("https://example.com/webcast.mp3", settings)
    assert got["status"] == UNAVAILABLE
    assert got["reason"]


# --------------------------------------------------------------------------
# The cache: these endpoints are rate- or key-limited.
# --------------------------------------------------------------------------


def test_a_value_round_trips_through_the_cache(settings):
    store(settings, "fred", "X", {"hello": 1})
    assert cached(settings, "fred", "X") == {"hello": 1}


def test_a_stale_entry_is_a_miss(settings):
    store(settings, "8k", "EXMPL", {"v": 1})
    p = next((settings.cache_dir / "sources" / "8k").glob("*.json"))
    payload = json.loads(p.read_text(encoding="utf-8"))
    payload["_at"] = 0        # 1970
    p.write_text(json.dumps(payload), encoding="utf-8")
    assert cached(settings, "8k", "EXMPL") is None


def test_ttls_reflect_how_often_each_source_actually_changes():
    """A 13F is quarterly; a price-moving 8-K is not."""
    assert TTL_SECONDS["8k"] < TTL_SECONDS["form4"] < TTL_SECONDS["13f"]


def test_a_corrupt_cache_file_is_a_miss_not_a_crash(settings):
    store(settings, "fred", "X", {"v": 1})
    next((settings.cache_dir / "sources" / "fred").glob("*.json")).write_text("{{{", encoding="utf-8")
    assert cached(settings, "fred", "X") is None


def test_keys_with_awkward_characters_are_safe_filenames(settings):
    store(settings, "rss", "https://ir.example.com/feed?a=1&b=2", {"v": 1})
    assert cached(settings, "rss", "https://ir.example.com/feed?a=1&b=2") == {"v": 1}


# --------------------------------------------------------------------------
# Reporting.
# --------------------------------------------------------------------------


def test_unavailable_is_reported_as_unavailable(settings):
    """Never present an empty result as though it were data."""
    assert "(" in summarise({"status": UNAVAILABLE, "reason": "no key"})
    assert "no key" in summarise({"status": UNAVAILABLE, "reason": "no key"})


def test_each_payload_kind_has_a_readable_line(settings):
    assert "CPIAUCSL" in summarise(fred_series("cpi", settings))
    assert "Form 4" in summarise(insider_transactions("EXMPL", settings))
    assert "8-K" in summarise(latest_8k("EXMPL", settings))
    assert "EX-99.1" in summarise(latest_8k("EXMPL", settings))
    assert "IR item" in summarise(ir_feed("https://ir.example.com/rss", settings))


def test_everything_runs_offline_in_mock_mode(settings):
    """Same guarantee as the rest of the pipeline: MOCK_MODE never touches
    the network, and the paths are still exercised."""
    assert settings.mock_mode
    for payload in (latest_8k("EXMPL", settings),
                    insider_transactions("EXMPL", settings),
                    institutional_holders("EXMPL", settings),
                    fred_series("cpi", settings),
                    ir_feed("https://ir.example.com/rss", settings)):
        assert payload["status"] == "ok", payload
