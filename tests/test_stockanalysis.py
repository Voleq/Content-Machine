"""stockanalysis.com as a source (point 7 of 30 Oct 2026): the readers on
saved pages, the rules it is read under, and what a video takes from it.

The pages under `fixtures/stockanalysis/` are Boeing's on 30 Oct 2026, three
days after it reported Q3 and fell 10.7%: the case the short got wrong.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import shutil
from pathlib import Path

import pytest

from pipeline import site_pack
from pipeline import stockanalysis as sa

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
DAY = dt.date(2026, 10, 28)


@pytest.fixture()
def ws(settings) -> Path:
    """A SHORT's workspace on the day after the print, with the fake
    workbook (the readers do not care whose figures it holds)."""
    path = settings.workspace_dir / "BA" / DAY.isoformat()
    path.mkdir(parents=True)
    shutil.copy(FIXTURES / "company_data" / "dennis_data.xlsx",
                path / "dennis_data.xlsx")
    return path


# ------------------------------------------------------------ the readers

def test_the_news_reads_outlet_minute_and_kind(settings):
    got = sa.news("BA", settings)
    assert got["status"] == "ok"
    items = got["items"]
    assert len(items) == 24
    kinds = {i["kind"] for i in items}
    assert {"article", "release", "transcript"} <= kinds
    first = next(i for i in items if "big reason Boeing" in i["title"])
    assert first["source"] == "Market Watch"
    # The byline's UTC time, in New York's clock.
    assert first["time"].startswith("2026-10-27T13:59")
    rel = [i for i in items if i["kind"] == "release"]
    assert all(i["source"] in ("PRNewsWire", "Business Wire") for i in rel)


def test_statistics_carry_the_earnings_date_and_session(settings):
    got = sa.statistics("BA", settings)
    assert got["earnings"] == {"which": "last", "date": "2026-10-27",
                               "timing": "before the open"}
    # As the page prints it: the prompt quotes it, nothing computes with it.
    assert got["rows"]["Market Cap"].endswith("B")


def test_quarters_are_millions_newest_first_with_cash_merged(settings):
    got = sa.quarterly("BA", settings)
    assert got["status"] == "ok"
    assert got["periods"][0]["label"] == "Q3 2026"
    assert got["periods"][0]["end"] == "2026-09-30"
    assert len(got["periods"]) == 20
    assert "Revenue" in got["rows"] and "Free Cash Flow" in got["rows"]


def test_kpis_forecast_company_calls(settings):
    m = sa.metrics("BA", settings)
    titles = [s["title"] for s in m["sections"]]
    assert "Operating metrics" in titles
    f = sa.forecast("BA", settings)
    assert f["targets"]["average"] and f["actions"][0]["firm"]
    c = sa.company("BA", settings)
    assert c["facts"]["Founded"] == "1916"
    assert any("Ortberg" in e["name"] for e in c["executives"])
    calls = sa.transcript_list("BA", settings)
    latest = next(e for e in calls["events"] if e["kind"] == "earnings")
    assert latest["date"] == "2026-10-27"
    t = sa.transcript(latest["path"], settings)
    assert len(t["turns"]) > 50
    assert t["turns"][0]["speaker"]


def test_a_path_that_is_not_a_transcript_is_refused(settings):
    assert sa.transcript("/stocks/ba/../../admin/", settings)["status"] == sa.UNAVAILABLE


def test_movers_and_the_earnings_calendar(settings):
    m = sa.movers(settings)
    assert set(m["lists"]) == {"gainers", "losers", "premarket_up",
                               "premarket_down", "afterhours_up",
                               "afterhours_down"}
    # A fraction, as every reader here keeps percentages.
    assert 0 < m["lists"]["gainers"][0]["change"] < 5
    cal = sa.earnings_calendar(settings)
    assert cal["rows"] and cal["days"]


def test_numbers_read_as_the_page_prints_them():
    assert sa.number("745.43B") == pytest.approx(7.4543e11)
    assert sa.number("-10.7%") == pytest.approx(-0.107)
    assert sa.number("Upgrade") is None


def test_a_ticker_with_no_saved_pages_is_unavailable_and_asks_nothing(settings):
    """Mock mode reads the saved pages only: the fake EXMPL has none."""
    got = sa.news("EXMPL", settings)
    assert got["status"] == sa.UNAVAILABLE


# ------------------------------------------------------- the rules it reads by

def test_the_bot_names_itself_and_never_a_person():
    assert "@" not in sa.USER_AGENT
    assert "github.com/Voleq/Content-Machine" in sa.USER_AGENT


def test_robots_decides_and_a_disallowed_path_is_not_read(settings):
    ok, _ = sa.allowed("/stocks/ba/", settings)
    assert ok
    ok, why = sa.allowed("/p/anything/", settings)
    assert not ok and "robots" in why


def test_the_source_turns_itself_off_when_the_terms_drop_the_exemption(
        settings, monkeypatch):
    real = sa._raw_get

    def terms_without(path, s):
        page = real(path, s)
        if path == "/terms-of-use/":
            return page.replace("AI agents", "agents").replace("ai agents", "agents")
        return page

    monkeypatch.setattr(sa, "_raw_get", terms_without)
    assert sa.terms_still_allow(settings) is False
    ok, why = sa.allowed("/stocks/ba/", settings)
    assert not ok and "terms" in why
    assert sa.news("BA", settings)["status"] == sa.UNAVAILABLE


def test_switched_off_reads_nothing(settings, monkeypatch):
    monkeypatch.setattr(settings, "stockanalysis_enabled", False)
    asked = []
    monkeypatch.setattr(sa, "_raw_get", lambda p, s: asked.append(p))
    assert sa.news("BA", settings)["status"] == sa.UNAVAILABLE
    assert asked == []


def test_live_requests_are_paced_and_counted(settings, monkeypatch):
    """One page every couple of seconds, each counted for /admin usage."""
    import httpx

    from pipeline import request_count

    monkeypatch.setattr(settings, "mock_mode", False)
    monkeypatch.setattr(settings, "stockanalysis_gap_s", 0.2)
    calls: list[tuple[float, dict]] = []

    class _R:
        status_code = 200
        text = "ok"

    def fake_get(url, **kw):
        import time

        calls.append((time.monotonic(), kw["headers"]))
        return _R()

    monkeypatch.setattr(httpx, "get", fake_get)
    counted = []
    monkeypatch.setattr(request_count, "count", lambda s, svc: counted.append(svc))
    for _ in range(3):
        assert sa._raw_get("/stocks/ba/", settings) == "ok"
    gaps = [b[0] - a[0] for a, b in zip(calls, calls[1:])]
    assert all(g >= 0.19 for g in gaps), gaps
    assert counted == ["stockanalysis"] * 3
    assert calls[0][1]["User-Agent"] == sa.USER_AGENT


def test_the_site_name_never_reaches_a_script():
    from pipeline.models import VENDOR_WORDS

    assert any(w in "according to stockanalysis.com" for w in VENDOR_WORDS)


# ------------------------------------------------------------ the video's pack

def test_a_short_takes_the_coverage_the_call_and_the_rest(ws, settings):
    pack = site_pack.gather(ws, "BA", settings, lane="short", today=DAY)
    assert pack["status"] == "ok"
    assert pack["earnings"]["date"] == "2026-10-27"
    assert pack["call"]["title"].endswith("Q3 2026")
    assert len(pack["call"]["passages"]) == site_pack.PASSAGES
    # Every passage is the call's own words.
    turns = " ".join(t["text"] for t in pack["call"]["turns"])
    assert all(p["text"] in turns for p in pack["call"]["passages"])
    assert "year_ago_call" not in pack
    saved = json.loads(site_pack.path(ws).read_text(encoding="utf-8"))
    assert saved["ticker"] == "BA"
    assert site_pack.used(ws)


def test_a_long_also_takes_the_call_a_year_earlier(ws, settings):
    pack = site_pack.gather(ws, "BA", settings, lane="long", today=DAY)
    assert pack["year_ago_call"]["date"].startswith("2025-10")
    assert "A YEAR EARLIER" in site_pack.promises_block(ws)


def test_the_local_ai_only_picks_numbers_and_never_writes_a_quote(
        ws, settings, monkeypatch):
    from pipeline import llm

    seen = {}

    class _Got:
        text = "Here: [3, 1, 2, 9, 4]"

    def fake(prompt, s, **kw):
        seen.update(kw)
        return _Got()

    monkeypatch.setattr(llm, "chat_result", fake)
    pack = site_pack.gather(ws, "BA", settings, lane="short", today=DAY)
    assert pack["call"]["picked_by"] == "the local AI"
    assert seen["providers"] == [llm.OLLAMA]
    assert seen["purpose"] == "transcript-passages"
    turns = " ".join(t["text"] for t in pack["call"]["turns"])
    assert all(p["text"] in turns for p in pack["call"]["passages"])


def test_a_render_on_the_card_means_keyword_scoring(ws, settings, monkeypatch):
    from pipeline import llm

    monkeypatch.setattr(llm, "chat_result",
                        lambda *a, **k: pytest.fail("the model was asked"))
    pack = site_pack.gather(ws, "BA", settings, lane="short", today=DAY,
                            busy=True)
    assert pack["call"]["picked_by"].startswith("keyword scoring")


def test_a_ticker_the_site_does_not_have_says_so(settings, tmp_path):
    pack = site_pack.gather(tmp_path, "EXMPL", settings, today=DAY)
    assert pack["status"] == "unavailable"
    assert "not read" not in site_pack.call_block(tmp_path, "short")
    assert site_pack.call_block(tmp_path, "short").startswith("(")
    assert not site_pack.used(tmp_path)


def test_the_workbook_gains_the_site_headlines_and_never_loses_its_own(
        ws, settings):
    from pipeline.company_data import load_company_data

    before = load_company_data(ws)
    site_pack.gather(ws, "BA", settings, lane="short", today=DAY)
    after = load_company_data(ws)
    assert after.news[:len(before.news)] == before.news
    added = after.news[len(before.news):]
    assert added and all(r["source"] for r in added)
    assert not any("stockanalysis" in r["source"].lower() for r in added)
    assert load_company_data(ws, site=False).news == before.news


# ------------------------------------------------------------- the quote card

def _line(ws) -> dict:
    return (site_pack.load(ws) or {})["call"]["passages"][1]


def test_a_quote_in_the_call_word_for_word_is_drawn(ws, settings):
    from pipeline.models import CallQuote

    site_pack.gather(ws, "BA", settings, today=DAY)
    p = _line(ws)
    text = site_pack._sentences(p["text"])[0][:site_pack.QUOTE_MAX]
    text = text[:text.rfind(" ")] if len(text) == site_pack.QUOTE_MAX else text
    card = site_pack.quote_card(ws, CallQuote(text=text.replace("'", "’")))
    assert card is not None
    assert card["text"].startswith("“")
    assert card["source"].startswith("Q3 2026 earnings call")
    assert len(card["attribution"]) <= site_pack.ATTRIBUTION_MAX


def test_a_changed_word_means_no_card_and_a_warning(ws, settings, short_valid_json):
    from pipeline.models import CallQuote
    from pipeline.parser_short import parse_short_script

    site_pack.gather(ws, "BA", settings, today=DAY)
    words = site_pack._sentences(_line(ws)["text"])[0].split()
    words[3] = "definitely"
    bent = " ".join(words)[:140]
    assert site_pack.quote_card(ws, CallQuote(text=bent)) is None
    raw = json.loads(short_valid_json)
    raw["call_quote"] = {"text": bent, "speaker": "the CFO"}
    script, _ = parse_short_script(json.dumps(raw), settings)
    found = site_pack.quote_findings(script, ws)
    assert [f.gate for f in found] == ["call-quote"]
    assert found[0].severity == "warn"


def test_the_resolver_draws_the_card_only_from_a_verified_quote(
        ws, settings, short_valid_json):
    from pipeline.parser_short import parse_short_script
    from pipeline.render_short import ShortResolver

    site_pack.gather(ws, "BA", settings, today=DAY)
    line = site_pack._sentences(_line(ws)["text"])[0]
    line = line if len(line) <= site_pack.QUOTE_MAX else " ".join(line.split()[:12])
    raw = json.loads(short_valid_json)
    raw["call_quote"] = {"text": line}
    script, _ = parse_short_script(json.dumps(raw), settings)
    r = ShortResolver(script=script, workdir=ws / "render_short", settings=settings)
    assert r.text_for("site.quote.text") == f"“{line}”"
    assert r.text_for("site.quote.source").startswith("Q3 2026 earnings call")
    raw["call_quote"] = {"text": "We are thrilled with every number this quarter."}
    script, _ = parse_short_script(json.dumps(raw), settings)
    r = ShortResolver(script=script, workdir=ws / "render_short", settings=settings)
    assert r.text_for("site.quote.text") is None


def test_a_call_quote_never_refuses_a_script(short_valid_json, settings):
    from pipeline.parser_short import parse_short_script

    raw = json.loads(short_valid_json)
    raw["call_quote"] = "x" * 900
    script, _ = parse_short_script(json.dumps(raw), settings)
    assert len(script.call_quote.text) == 600
    raw["call_quote"] = None
    script, _ = parse_short_script(json.dumps(raw), settings)
    assert script.call_quote is None


# -------------------------------------------------------- the quarters check

def _pack_with(revenue_m: list[float | None]) -> dict:
    return {"quarterly": {
        "periods": [{"label": f"Q{q} 2026", "end": e} for q, e in
                    ((2, "2026-06-30"), (1, "2026-03-31"))],
        "rows": {"Revenue": revenue_m}}}


def test_a_quarter_that_disagrees_is_listed_and_one_that_agrees_is_not(settings):
    from pipeline.models import CompanyData

    data = CompanyData(quarter_labels=["Q1 FY26", "Q2 FY26"],
                       quarters={"revenue": [100e6, 120e6]})
    rows = site_pack.cross_check(data, _pack_with([131.0, 100.4]))
    assert [(r["quarter"], r["field"]) for r in rows] == [("Q2 FY26", "revenue")]
    assert rows[0]["workbook"] == "$120.00M" and rows[0]["site"] == "$131.00M"


def test_a_blank_quarter_is_filled_and_a_filled_one_never_overwritten(tmp_path):
    from pipeline.models import CompanyData

    site_pack._save(tmp_path, _pack_with([131.0, 99.0]))
    data = CompanyData(quarter_labels=["qtr to Mar '26", "Q2 FY26"],
                       quarters={"revenue": [None, 120e6]})
    filled = site_pack.fill_quarter_gaps(data, tmp_path)
    assert data.quarters["revenue"] == [99e6, 120e6]
    assert filled == ["qtr to Mar '26 revenue"]


# ------------------------------------------------------- the second clock

def test_the_site_s_earnings_date_names_the_day_when_the_sec_has_not():
    from pipeline.move_kind import EARNINGS, SITE, classify

    day = classify("BA", DAY, site_earnings={
        "which": "last", "date": "2026-10-27", "timing": "before the open"})
    assert day.kind == EARNINGS and day.source == SITE
    assert day.reported_on == "2026-10-27" and day.timing == "before the open"


def test_the_two_clocks_say_whether_they_agree():
    from pipeline.move_kind import classify

    release = {"status": "ok", "filed": "2026-10-27",
               "accepted": "2026-10-27T10:30:00.000Z"}
    same = classify("BA", DAY, release=release, site_earnings={
        "which": "last", "date": "2026-10-27"})
    assert same.source == "SEC 8-K item 2.02" and "agrees" in same.why
    other = classify("BA", DAY, release=release, site_earnings={
        "which": "last", "date": "2026-10-20"})
    assert "does not match" in other.why


def test_a_coming_report_is_mentioned_and_does_not_make_an_earnings_day():
    from pipeline.move_kind import MOVE, classify

    day = classify("BA", DAY, site_earnings={
        "which": "next", "date": "2026-11-04", "timing": "after the close"})
    assert day.kind == MOVE and "next report is due" in day.why


# --------------------------------------------------------- what the writer sees

def test_the_short_prompt_carries_the_call_and_the_coverage(ws, settings):
    from bot.prompts import fill_prompt
    from pipeline.company_data import load_company_data
    from pipeline.move_kind import classify

    pack = site_pack.gather(ws, "BA", settings, today=DAY)
    data = load_company_data(ws)
    day = classify("BA", DAY, news=data.news, site_earnings=pack["earnings"])
    text = fill_prompt("short", "BA", data, ws, settings, move_kind=day)
    assert "THE LATEST EARNINGS CALL" in text
    assert "THE COVERAGE BY THE MINUTE" in text
    assert "call_quote" in text
    assert "THE ANALYSTS" in text and "THE COMPANY'S OWN KPIs" in text
    assert not re.search(r"\{\{(call_transcript|analyst_moves|business_kpis|"
                         r"company_facts|why_it_moved)\}\}", text)


def test_the_description_credits_the_site_only_when_it_was_used(
        ws, settings, short_valid_json):
    from pipeline.parser_short import parse_short_script
    from pipeline.publish import build_package

    script, _ = parse_short_script(short_valid_json, settings)
    assert site_pack.credit(ws) == ""
    site_pack.gather(ws, "BA", settings, today=DAY)
    pkg = build_package(script, settings, credit=site_pack.credit(ws))
    assert "stockanalysis.com" in pkg.description


def test_the_live_screen_adds_the_site_s_names(settings, monkeypatch):
    rows = sa.screener_quotes(settings, set())[0]
    assert rows and all(r["_from"].startswith("on stockanalysis.com") for r in rows)
    # Percent, as Yahoo's quotes carry it.
    assert abs(rows[0]["regularMarketChangePercent"]) > 1
    kept = json.loads((settings.state_dir / sa.MARKET_FILE).read_text(encoding="utf-8"))
    assert kept["status"] == "ok" and kept["calendar"]["rows"]


# ------------------------------------------------------------- the bot, the page

CHAT = 5150


@pytest.fixture()
def core(settings):
    from bot.handlers import BotCore

    return BotCore(settings.model_copy(update={"operator_chat_ids": [CHAT]}))


def test_the_prompt_reads_the_site_and_the_data_step_shows_it(core):
    """Nothing here depends on today's date: the call, the quarters and the
    profile are the same pages whenever the suite runs."""
    from bot.panel import Panel
    from bot.panel_views import video_view

    core.start_lane(CHAT, "short", "BA")
    ws = core.context.get(CHAT)
    shutil.copy(FIXTURES / "company_data" / "dennis_data.xlsx",
                ws.path / "dennis_data.xlsx")
    reply = core.prompts_reply(CHAT)
    assert "📰 stockanalysis.com:" in reply.text
    assert "THE LATEST EARNINGS CALL" in (ws.path / "prompt_short.md").read_text(
        encoding="utf-8")
    view = video_view(Panel(core, loop=None), "BA", ws.workdate, step="data")
    site = view["data"]["site"]
    assert {p["key"] for p in site["parts"]} >= {"statistics", "quarterly", "call"}
    assert site["call"]["passages"]
    assert site["refresh"] == f"/site BA@{ws.workdate} refresh"
    text = core.site_command(CHAT, []).text
    assert "Latest earnings call" in text and "Quarterly statements" in text


def test_movers_reach_home_and_the_calendar(core):
    from bot.panel import Panel
    from bot.panel_pages import _reporting

    text = core.movers_text([]).text
    assert text.startswith("📈 Today's movers")
    assert "Reporting" in text
    home = Panel(core, loop=None).movers()
    assert home["status"] == "ok"
    for rows in home["lists"].values():
        assert all(r["price"] >= core.settings.screen_min_price for r in rows)
    rep = _reporting(core.settings)
    assert rep["rows"][0]["symbol"] and rep["count"] >= len(rep["rows"])


def test_the_switch_turns_the_source_off_on_the_page(core):
    from pipeline.switches import SWITCHES

    assert SWITCHES["stockanalysis_enabled"].env == "STOCKANALYSIS"
    core.set_switch("stockanalysis_enabled", False)
    assert core.settings.stockanalysis_enabled is False
    assert sa.market_today(core.settings)["status"] == "off"
