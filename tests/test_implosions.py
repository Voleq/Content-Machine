"""The implosion screener: the bot finds the stories, he never searches.

Fixtures only: the list pages are Wikipedia's own HTML trimmed to a few rows,
the article and pageview answers for Knight Capital are Wikipedia's as served,
and everything else (the DOJ and SEC releases, the example list) is made up
under /fixture/ paths. Nothing here touches the network.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from pipeline import implosions as im

NOW = datetime(2026, 11, 6, 12, tzinfo=timezone.utc)
ALL_LISTS = ("List of trading losses|List of corporate collapses and scandals|"
             "List of stock market crashes and bear markets|List of example blow-ups")


@pytest.fixture()
def lists(fixtures_dir):
    folder = fixtures_dir / "implosions" / "lists"
    return {p.stem: p.read_text(encoding="utf-8") for p in folder.glob("*.html")}


@pytest.fixture()
def every_list(settings):
    return settings.model_copy(update={"implosion_lists": ALL_LISTS})


# ------------------------------------------------------------- reading lists


def test_the_trading_losses_page_reads_as_wikipedia_serves_it(lists):
    rows = im.parse_list(lists["List_of_trading_losses"], "List of trading losses")
    knight = next(r for r in rows if r["name"] == "Knight Capital Group")
    assert knight["article"] == "Knight_Capital_Group"
    assert knight["year"] == 2012 and knight["loss_usd"] == pytest.approx(440e6)
    assert knight["loss_text"] == "USD 0.44 bn" and knight["what"] == "Equities"
    # The dollar column, never the "2007 USD" or FX columns beside it.
    barings = next(r for r in rows if r["name"] == "Barings Bank")
    assert barings["loss_usd"] == pytest.approx(1.31e9)
    # No person is carried from the list's "associated with" column.
    assert all("Leeson" not in json.dumps(r) for r in rows)


def test_a_see_also_note_names_the_storys_own_article(lists):
    rows = im.parse_list(lists["List_of_corporate_collapses_and_scandals"], "collapses")
    by = {r["name"]: r for r in rows}
    assert by["Enron"]["article"] == "Enron_scandal"
    assert by["FTX"]["article"] == "Bankruptcy_of_FTX"
    assert not by["FTX"]["what"].startswith("See also")
    assert by["Enron"]["loss_usd"] == pytest.approx(63.4e9)
    assert by["Wirecard"]["loss_text"] == "€1.9 billion"


def test_a_crash_with_no_size_is_still_a_story(lists):
    rows = im.parse_list(lists["List_of_stock_market_crashes_and_bear_markets"], "crashes")
    monday = next(r for r in rows if r["name"] == "Black Monday")
    assert monday["article"] == "Black_Monday_(1987)" and monday["year"] == 1987
    assert monday["loss_usd"] is None


@pytest.mark.parametrize("text, usd, want", [
    ("USD 6.12 (EUR 4.9) bn", True, 6.12e9),
    ("GBP 827 mn", False, 827e6 * 1.3),
    ("$1.25M to settle", False, 1.25e6),
    ("lost it in 45 minutes in 2012", False, None),
    ("€1.9 billion went missing", False, 1.9e9 * 1.1),
    ("a $65 billion Ponzi scheme", False, 65e9),
    ("0.44 bn", True, 0.44e9),
])
def test_sums_are_read_roughly_for_ranking(text, usd, want):
    got = im.money_usd(text, usd=usd)
    assert got == (pytest.approx(want) if want else None)


def test_how_a_story_stands_is_read_off_its_own_words():
    today = date(2026, 11, 6)
    assert im.status_of("agreed to pay $12 million") == ("closed", "agreed to pay")
    assert im.status_of("charged in 2008 and sentenced in 2009")[0] == "closed"
    assert im.status_of("was charged with fraud") == ("open", "charged")
    # A collapse closes a story only once its cases have had time to come.
    assert im.status_of("collapsed", year=2001, today=today) == ("closed", "collapsed")
    assert im.status_of("collapsed", year=2025, today=today) == ("open", "recent")
    assert im.status_of("sentenced", year=2026, today=today)[0] == "closed"
    assert im.status_of("nothing either way") == ("unclear", "")
    # The DOJ's own headline words.
    assert im.status_of("Utah County Man Admits His Part in a Ponzi Scheme")[0] == "closed"
    assert im.status_of("Federal grand jury indicts fourteen defendants") == ("open", "indicts")
    assert im.status_of("Bank Officer Pleads Guilty")[0] == "closed"


def test_dates_and_documents():
    assert im.full_date("On August 1, 2012, Knight", 2012) == date(2012, 8, 1)
    assert im.full_date("28 Nov 2001") == date(2001, 11, 28)
    assert im.full_date("June 2020") is None
    assert im.document_kind("https://www.sec.gov/litigation/admin/2013/34-70694.pdf") == ("sec.gov", "regulator")
    assert im.document_kind("https://www.sec.gov/Archives/edgar/data/1/x.htm") == ("sec.gov", "filing")
    assert im.document_kind("https://www.justice.gov/opa/pr/x") == ("justice.gov", "prosecutor")
    assert im.document_kind("https://ecf.nysd.uscourts.gov/doc") == ("uscourts.gov", "court")
    assert im.document_kind("https://www.nytimes.com/x") == ("", "")
    assert im.document_kind("javascript://sec.gov/%0aalert(1)") == ("", "")


# ------------------------------------------------------------------ ranking


def test_the_read_ranks_closed_famous_documented_stories_first(every_list):
    got = im.refresh(every_list, now=NOW)
    names = [s["name"] for s in got["stories"]]
    assert got["mock"] is True and len(got["lists"]) == 4
    # Enron: closed, documented, famous, huge, and 25 years on 28 Nov.
    assert names[0] == "Enron"
    enron = got["stories"][0]
    assert enron["anniversary"] == "25 years on 28 Nov" and enron["status"] == "closed"
    knight = next(s for s in got["stories"] if s["name"] == "Knight Capital Group")
    assert knight["status_word"] == "agreed to pay"
    assert {d["host"] for d in knight["documents"]} == {"sec.gov"}   # the news link is not one
    # A loss this year with no record is open and sinks below every closed one.
    sa = next(s for s in got["stories"] if s["name"] == "Situational Awareness")
    assert sa["status"] == "open"
    assert all(s["score"] > sa["score"] for s in got["stories"] if s["status"] == "closed")
    # Barings is on two lists and is one story.
    assert names.count("Barings Bank") == 1
    # Too small to be a story.
    assert "Tiny Example Fund" not in names


def test_a_company_page_counts_half_its_fame():
    """JPMorgan Chase's readers came for the bank, not the 2012 loss."""
    base = {"year": 2012, "views": 1e6, "loss_usd": 1e9, "documents": [], "status": "unclear"}
    about = im.score({**base, "extract": "In 2012 the firm lost..."})[1]["fame"]
    company = im.score({**base, "extract": "A bank founded in 1799."})[1]["fame"]
    assert company == pytest.approx(about - 0.5, abs=0.01)


def test_this_weeks_releases_close_a_known_story_and_add_big_new_ones(every_list):
    got = im.refresh(every_list, now=NOW)
    by = {s["name"]: s for s in got["stories"]}
    lender = by["Example Lending Corp"]
    assert lender["fresh"]["source"] == "DOJ" and lender["status"] == "closed"
    assert lender["documents"][0]["url"].endswith("fixture-example-lending-sentenced")
    judged = next(s for n, s in by.items() if n.startswith("SEC Obtains Final Judgment"))
    assert judged["status"] == "closed"
    charged = next(s for n, s in by.items() if n.startswith("Exampleton"))
    assert charged["status"] == "open" and charged["score"] < lender["score"]
    # A US attorney's release counts too: the big frauds are mostly theirs.
    assert by[next(n for n in by if n.startswith("Regional Office"))]["status"] == "closed"
    titles = " ".join(by)
    for gone in ("Sampleville", "Drug Ring", "Old Example", "Grants"):
        assert gone not in titles      # small, not finance, too old


def test_a_release_joins_a_story_only_when_it_names_its_year_too():
    story = {"name": "UBS", "year": 2011}
    assert im._mentions(story, "Former UBS trader's 2011 loss: appeal refused")
    assert not im._mentions(story, "UBS agrees to pay $10 million over 2019 accounts")
    assert not im._mentions({"name": "Bank", "year": 2011}, "Bank 2011")


def test_skip_done_and_back(every_list):
    im.refresh(every_list, now=NOW)
    first = im.shown(every_list)[0]
    assert im.mark(every_list, first["id"], "skipped")
    assert first["id"] not in [s["id"] for s in im.shown(every_list)]
    # A later read keeps it out.
    im.refresh(every_list, now=NOW)
    assert first["id"] not in [s["id"] for s in im.shown(every_list)]
    assert im.mark(every_list, first["id"], "back")
    im.refresh(every_list, now=NOW)
    assert im.shown(every_list)[0]["id"] == first["id"]
    assert not im.mark(every_list, "no-such-story", "skipped")


def test_the_weekly_read_is_due_once_a_week_and_never_in_mock(settings):
    live = settings.model_copy(update={"mock_mode": False, "mock_screener": None})
    assert not im.due(settings)                      # mocked: never on its own
    assert im.due(live, NOW)                         # nothing read yet
    from pipeline.standing import _write

    _write(settings.state_dir / im.STATE_FILE, {"written_at": NOW.isoformat()})
    assert not im.due(live, NOW)
    assert im.due(live, NOW.replace(day=14))
    assert not im.due(live.model_copy(update={"implosions_enabled": False}), NOW.replace(day=20))


# --------------------------------------------------------------- the pitch


def test_the_pitch_is_three_labelled_lines_from_the_local_model(settings, monkeypatch):
    import pipeline.llm as llm

    seen = {}

    class Got(SimpleNamespace):
        def __bool__(self):
            return True

    def fake(prompt, s, **kw):
        seen.update(kw, prompt=prompt)
        return Got(text="DETOUR: Babbage's engine.\n**LESSON:** how a market maker "
                        "quotes both sides.\nJOKE: forty-five minutes.\n")

    monkeypatch.setattr(llm, "chat_result", fake)
    p = im.pitch({"name": "Knight Capital Group", "year": 2012, "loss_text": "USD 0.44 bn",
                  "what": "Equities"}, settings)
    assert p == {"detour": "Babbage's engine.",
                 "lesson": "how a market maker quotes both sides.",
                 "joke": "forty-five minutes."}
    assert seen["providers"] == [llm.OLLAMA]         # free: never a hosted model
    assert "Knight Capital Group (2012)" in seen["prompt"]


def test_no_local_model_means_no_pitch(settings):
    assert im.pitch({"name": "Enron", "year": 2001}, settings) == {}   # mock: no LLM


# -------------------------------------------------------------- live reader


class _Resp:
    def __init__(self, status, payload=None, text="", headers=None):
        self.status_code, self._payload, self.text = status, payload, text
        self.headers = headers or {}

    def json(self):
        return self._payload


def test_the_live_reader_reads_wikipedias_real_answers(settings, fixtures_dir, monkeypatch):
    import httpx

    live = settings.model_copy(update={"mock_mode": False, "mock_screener": None})
    folder = fixtures_dir / "implosions" / "live"
    article = json.loads((folder / "article_Knight_Capital_Group.json").read_text(encoding="utf-8"))
    views = json.loads((folder / "views_Knight_Capital_Group.json").read_text(encoding="utf-8"))
    calls = []

    def get(url, params=None, headers=None, **kw):
        calls.append((url, params, headers))
        if "pageviews" in url:
            return _Resp(429, headers={"retry-after": "1"}) if len(calls) == 2 else _Resp(200, views)
        return _Resp(200, article)

    monkeypatch.setattr(httpx, "get", get)
    monkeypatch.setattr(im.time, "sleep", lambda s: None)
    reader = im.Reader(live)
    got = reader.article("Knight_Capital_Group")
    assert "August 2012 trading error lost $460 million" in got["extract"]
    docs = [u for u in got["links"] if im.document_kind(u)[1] == "regulator"]
    assert "https://www.sec.gov/litigation/admin/2013/34-70694.pdf" in docs
    assert reader.views("Knight_Capital_Group", NOW.date()) == 78022   # after one 429
    assert all("Voleq/Content-Machine" in h["User-Agent"] for _u, _p, h in calls)
    assert all("@" not in h["User-Agent"] for _u, _p, h in calls)      # never an email


def test_a_list_that_cannot_be_read_says_so(settings, monkeypatch):
    import httpx

    live = settings.model_copy(update={"mock_mode": False, "mock_screener": None})
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _Resp(503))
    monkeypatch.setattr(im.time, "sleep", lambda s: None)
    monkeypatch.setattr(im.Reader, "sec", lambda self: [])
    got = im.refresh(live, now=NOW, pitches=False)
    assert got["lists"] == [] and got["stories"] == []
    assert "List of trading losses (503)" in got["failed"]
    # A dead read never wipes the last good list, and stays due.
    from pipeline.standing import _write

    _write(live.state_dir / im.STATE_FILE, {"written_at": "2026-10-01T00:00:00+00:00",
                                           "stories": [{"id": "enron-2001", "name": "Enron"}]})
    got = im.refresh(live, now=NOW, pitches=False)
    assert [s["name"] for s in got["stories"]] == ["Enron"]
    assert im.load(live)["written_at"].startswith("2026-10-01") and im.due(live, NOW)


# ---------------------------------------------------------- what he reads


def test_the_reply_and_the_page(every_list):
    from bot.handlers import BotCore
    from bot.panel_pages import ideas_view

    core = BotCore(every_list)
    empty = core.implosions_command([]).text
    assert "No implosion stories read yet" in empty
    text = core.implosions_command(["refresh"]).text
    assert text.splitlines()[1].startswith("1. Enron (2001) · $63.4 billion")
    assert "FIXTURE DATA" in text and "not facts" in text
    skipped = core.implosions_command(["skip", "1"]).text
    assert "Enron won't come up again" in skipped and "back enron-2001" in skipped
    assert "1. Enron" not in skipped
    back = core.implosions_command(["back", "enron-2001"]).text
    assert "back on the list" in back and "\n1. Enron" in back
    page = ideas_view(SimpleNamespace(settings=every_list))["implosions"]
    assert page["rows"][0]["name"] == "Enron" and page["mock"] is True
    assert page["rows"][0]["documents"][0]["host"] == "sec.gov"
    assert core.implosions_command(["skip", "99"]).text.startswith("💥 Which one?")
