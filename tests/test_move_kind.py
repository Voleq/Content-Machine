"""What kind of day a SHORT is about, and what an earnings day changes.

Valentin's Boeing proof (30 Oct 2026): BA fell 10.7% on the morning it
reported, and the short drew revenue from FY21 to LTM, a move card with a
percentage over a line and no price, and never said why the stock fell.
These hold the fix: the day is read off the SEC and the headlines, an
earnings day is cut as the earnings short with its quarters read against a
year before, the move card carries the price, and the prompt carries the
release and the rule that the cause comes first.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import shutil
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from pipeline import move_kind as mk
from pipeline import short_data as sd

TODAY = dt.date(2026, 10, 28)
RELEASE = {"status": "ok", "form": "8-K", "filed": "2026-10-27",
           "accepted": "2026-10-27T10:31:02.000Z", "items": "2.02,9.01",
           "period": "2026-09-30", "exhibit_url": "https://sec.example/ex99.htm",
           "exhibit_text": "Boeing Reports Third-Quarter Results. Revenue of "
                           "$23.3 billion. Operating cash flow of $0.2 billion."}


# ---------------------------------------------------------------------------
# Reading the day
# ---------------------------------------------------------------------------

def test_an_earnings_8k_in_the_window_makes_an_earnings_day():
    day = mk.classify("BA", TODAY, release=RELEASE, news=[])
    assert day.kind == mk.EARNINGS and day.source == "SEC 8-K item 2.02"
    assert day.reported_on == "2026-10-27"
    assert day.timing == "before the open"
    assert "quarter to 30 Sep 2026" in day.why and "Tue 27 Oct" in day.why
    assert day.release_text.startswith("Boeing Reports Third-Quarter")


def test_a_print_from_last_week_does_not_explain_today():
    old = {**RELEASE, "filed": "2026-10-20"}
    day = mk.classify("BA", TODAY, release=old, news=[])
    assert day.kind == mk.MOVE and not day.release_text


@pytest.mark.parametrize("headline, kind", [
    ("Boeing posts wider third-quarter loss as 777X delays mount", mk.EARNINGS),
    ("Boeing misses estimates on defense charges", mk.EARNINGS),
    ("Boeing wins $4 billion contract for tanker jets", mk.NEWS),
    ("Boeing CEO says revenue will grow with 737 output", mk.NEWS),
])
def test_a_dated_headline_says_earnings_only_when_it_is_a_print(headline, kind):
    news = [{"date": "2026-10-27", "headline": headline, "source": "Reuters"},
            {"date": "2026-09-01", "headline": "Boeing Q2 earnings", "source": "X"}]
    day = mk.classify("BA", TODAY, release=None, news=news)
    assert day.kind == kind
    # Headlines outside the window are not evidence about today.
    assert [h["date"] for h in day.headlines] == ["2026-10-27"]


def test_nothing_on_file_is_said_plainly():
    day = mk.classify("BA", TODAY, release={"status": "unavailable"}, news=[])
    assert day.kind == mk.MOVE and "nothing public" in day.why


def test_the_operator_s_word_wins_and_keeps_the_release():
    day = mk.classify("BA", TODAY, release=RELEASE, news=[], override=mk.NEWS)
    assert day.kind == mk.NEWS and day.source == "operator"
    assert day.release_text, "a print he named otherwise still reaches the prompt"


@pytest.mark.parametrize("accepted, when", [
    ("2026-10-27T10:31:02.000Z", "before the open"),      # 06:31 New York (EDT)
    ("2026-10-27T15:00:00.000Z", "during the session"),   # 11:00
    ("2026-10-27T20:05:00.000Z", "after the close"),      # 16:05
    ("2026-12-01T14:00:00.000Z", "before the open"),      # 09:00 EST, not 10:00
    ("", ""),
    ("not a time", ""),
])
def test_the_filing_minute_is_read_on_new_york_s_clock(accepted, when):
    assert mk.timing_of(accepted) == when


def test_the_day_round_trips_through_the_workspace(settings):
    from pipeline.workspace import Workspace

    ws = Workspace(settings, "BA", "2026-10-28").create()
    day = mk.classify("BA", TODAY, release=RELEASE, news=[])
    ws.set_move_kind({**day.to_json(), "override": ""})
    back = mk.MoveKind.from_json(ws.move_kind())
    assert back is not None and back.is_earnings and back.timing == day.timing
    assert mk.MoveKind.from_json({"kind": "nonsense"}) is None


def test_a_script_says_which_cut_it_was_written_for():
    marks = lambda *k: [NS(key=x) for x in k]               # noqa: E731
    assert mk.earnings_shaped(NS(beat_marks=marks("hook", "reported"), reported=""))
    assert mk.earnings_shaped(NS(beat_marks=[], reported="$1.42"))
    assert not mk.earnings_shaped(NS(beat_marks=marks("hook", "move", "numbers"),
                                     reported=""))


# ---------------------------------------------------------------------------
# The SEC: the print is the 8-K under item 2.02, not the latest 8-K
# ---------------------------------------------------------------------------

def _filing(form, filed, items="", period="", accepted=""):
    from pipeline.sources import Filing

    return Filing(ticker="BA", form=form, filed=filed, accession="0001-26-1",
                  url="https://sec.example/a/b.htm", items=items,
                  accepted=accepted, period=period)


def test_the_earnings_release_is_the_2_02_8k_not_the_newest(settings, monkeypatch):
    from pipeline import sources

    eightks = [_filing("8-K", "2026-10-28", items="5.02", period="2026-10-28"),
               _filing("8-K", "2026-10-27", items="2.02,9.01",
                       period="2026-10-27", accepted="2026-10-27T10:31:02.000Z"),
               _filing("8-K", "2026-07-29", items="2.02,9.01")]
    reports = [_filing("10-Q", "2026-10-27", period="2026-09-30"),
               _filing("10-Q", "2026-07-29", period="2026-06-30")]
    monkeypatch.setattr(sources, "_filings_of", lambda t, s, forms, **k:
                        eightks if "8-K" in forms else reports)
    monkeypatch.setattr(sources, "_find_exhibit",
                        lambda *a: {"url": "u", "text": "Revenue was $23.3B."})
    got = sources.earnings_release("BA", settings, since="2026-10-24")
    assert got["status"] == "ok" and got["filed"] == "2026-10-27"
    assert got["accepted"].startswith("2026-10-27T10:31")
    assert got["period"] == "2026-09-30"
    assert got["exhibit_text"] == "Revenue was $23.3B."


def test_a_release_with_no_10q_yet_names_no_quarter(settings, monkeypatch):
    """An 8-K's own report date is the day of the event: it must not be
    taken for the quarter's end."""
    from pipeline import sources

    monkeypatch.setattr(sources, "_filings_of", lambda t, s, forms, **k:
                        [_filing("8-K", "2026-10-27", items="2.02",
                                 period="2026-10-27")] if "8-K" in forms else [])
    monkeypatch.setattr(sources, "_find_exhibit", lambda *a: None)
    got = sources.earnings_release("BA", settings, since="2026-10-24")
    assert got["status"] == "ok" and got["period"] == ""
    assert "quarter to" not in mk.classify("BA", TODAY, release=got).why


def test_no_print_since_the_window_opened_is_unavailable(settings, monkeypatch):
    from pipeline import sources

    monkeypatch.setattr(sources, "_filings_of", lambda *a, **k:
                        [_filing("8-K", "2026-07-29", items="2.02")])
    got = sources.earnings_release("BA", settings, since="2026-10-24")
    assert got["status"] == sources.UNAVAILABLE


def test_edgar_s_item_and_minute_columns_are_kept(settings, monkeypatch):
    from pipeline import filings, sources

    monkeypatch.setattr(filings, "_load_company_tickers", lambda s: {
        "0": {"ticker": "BA", "cik_str": 12927}})
    monkeypatch.setattr(filings, "_load_submissions", lambda cik, s: {
        "filings": {"recent": {
            "form": ["8-K"], "accessionNumber": ["0000012927-26-000101"],
            "primaryDocument": ["ba-20261027.htm"], "filingDate": ["2026-10-27"],
            "items": ["2.02,9.01"],
            "acceptanceDateTime": ["2026-10-27T10:31:02.000Z"],
            "reportDate": ["2026-10-27"]}}})
    got = sources._filings_of("BA", settings, ("8-K",), limit=3)
    assert got and got[0].items == "2.02,9.01"
    assert got[0].accepted == "2026-10-27T10:31:02.000Z"


# ---------------------------------------------------------------------------
# The sheet: quarters against a year before
# ---------------------------------------------------------------------------

@pytest.fixture()
def data(workspace):
    from pipeline.company_data import load_company_data

    return load_company_data(workspace)


def _quarter_script(data, **over):
    from pipeline.models import ShortScript

    heads = sd.quarter_labels(data)[-6:]
    raw = {
        "ticker": "EXMPL", "format": "short",
        "hook_text": "A muted hook line here.",
        "audio_script": "Numbers first. Then the point. Noise.",
        "move_summary": "-8.5% · after the print",
        "headlines": [{"text": "H", "meaning": "M"}],
        "years": heads,
        "numbers": [{"label": "Revenue", "field": "revenue",
                     "values": ["$1M"] * 6}],
        "numbers_comment": "flat", "conclusion": "Noise.",
    }
    raw.update(over)
    return ShortScript.model_validate(raw)


def test_a_sheet_of_quarter_heads_is_quarterly(data):
    assert sd.is_quarterly(_quarter_script(data), data)
    assert sd.is_quarterly(NS(years=["Q3 '25", "Q4 '25", "Q1 '26", "Q2 '26",
                                     "Q3 '26", "3Q26"]))
    assert not sd.is_quarterly(NS(years=["FY21", "FY22", "FY23", "FY24",
                                         "FY25", "LTM"]), data)


def test_a_quarter_is_set_against_the_same_quarter_a_year_before():
    values = ["$1", "$2", "$3", "$4", "$5", "$6"]
    assert sd.year_ago_index(values, quarterly=True) == 1
    assert sd.year_ago_index(values, quarterly=False) == 0
    # The year before is missing: nothing is compared, rather than the
    # wrong quarter.
    assert sd.year_ago_index(["", "", "$3", "$4", "$5", "$6"],
                             quarterly=True) is None
    assert sd.year_ago_index(["$1", "$2", "$3", "$4", "$5", ""],
                             quarterly=True) == 0


def test_an_earnings_sheet_is_drawn_from_the_quarters(data):
    script, notes = sd.fill_numbers(_quarter_script(data), data)
    row = script.numbers[0]
    want = [sd.fmt("revenue", v) for v in data.quarters["revenue"][-6:]]
    assert row.values == want
    assert script.years == sd.quarter_labels(data)[-6:]
    assert any("quarters" in n for n in notes)


def test_the_metric_card_reads_the_quarter_against_a_year_before(data, settings,
                                                                tmp_path):
    from pipeline.render_short import ShortResolver

    script, _ = sd.fill_numbers(_quarter_script(data), data)
    r = ShortResolver(script=script, workdir=tmp_path, settings=settings,
                      prices=None, handle="@channel", data=data)
    heads = script.years
    assert r.text_for("numbers.first_label.0") == f"{heads[1]}, a year earlier"
    assert r.text_for("numbers.last_label.0") == f"{heads[5]}, this quarter"
    assert r.text_for("numbers.first.0") == script.numbers[0].values[1]


# ---------------------------------------------------------------------------
# The move card's price
# ---------------------------------------------------------------------------

def _prices(closes, dates=None, **kw):
    dates = dates or [f"2026-10-{20 + i:02d}" for i in range(len(closes))]
    return NS(**{"dates": dates, "closes": closes, "degraded": False,
                 "source": "yahoo", **kw})


def test_the_move_s_day_is_the_session_that_made_the_narrated_move():
    # The 27th fell 10.7%; the 28th was flat.
    closes = [190.0, 189.0, 188.31, 168.18, 168.5]
    p = _prices(closes, ["2026-10-23", "2026-10-24", "2026-10-26",
                         "2026-10-27", "2026-10-28"])
    day = sd.move_day(p, -10.7)
    assert day["day"] == "2026-10-27" and day["close"] == 168.18
    assert day["prior"] == 188.31
    assert sd.move_day(p, +20.0) is None
    assert sd.move_day(p, None)["day"] == "2026-10-28"
    assert sd.move_day(_prices(closes, source="synthetic"), -10.7) is None


def test_the_move_is_priced_off_its_day_when_no_session_is_drawn():
    day = {"day": "2026-10-27", "close": 168.18, "prior": 188.31, "move": -10.7}
    assert sd.move_price(None, day) == "$168.18 at the close, from $188.31"
    assert sd.move_price(None, None) is None


def test_the_claimed_move_is_read_off_the_summary_s_sign():
    assert sd.claimed_move(NS(move_summary="-10.7% · after the print")) == -10.7
    assert sd.claimed_move(NS(move_summary="−12% after the call")) == -12.0
    assert sd.claimed_move(NS(move_summary="+34% today")) == 34.0
    assert sd.claimed_move(NS(move_summary="Q3 print")) is None


def test_the_session_card_prints_prices_not_only_percentages(settings):
    from pipeline.prices import get_intraday

    session = get_intraday("EXMPL", settings)
    card = sd.session_card(session, NS(ticker="EXMPL",
                                       move_summary="+29% today",
                                       headlines=[], hook_text="",
                                       numbers=[], reported=""))
    assert "$" in card["event-label"] and "$" in card["caption"]
    assert card["unit6"].startswith("the session, 09:30 to")
    price = sd.move_price(session, None, NS(move_summary="+29% today"))
    assert price.startswith("$") and "from $" in price


def test_the_move_card_binds_the_price_on_both_cuts():
    from pipeline.shots import load_format

    for name in ("short", "earnings"):
        shot = next(s for s in load_format(name).shots if s.id == "the-move")
        for v in shot.variants:
            if v.plate.startswith("figures/move-on-the-day"):
                assert v.bind["label"] == "?chart.move_price|chart.move_detail"
                assert v.bind["kicker"] == "?chart.move_kicker"


# ---------------------------------------------------------------------------
# The earnings cut: the move and the why come before the print
# ---------------------------------------------------------------------------

def test_every_earnings_order_shows_the_move_and_the_why():
    raw = json.loads((Path(__file__).resolve().parents[1] / "templates" /
                      "shots" / "earnings.json").read_text(encoding="utf-8"))
    ids = {s["id"] for s in raw["shots"]}
    assert {"the-move", "the-why"} <= ids
    for order in raw.get("orders") or []:
        assert {"the-move", "the-why"} <= set(order["shots"]), order["name"]


# ---------------------------------------------------------------------------
# The prompt
# ---------------------------------------------------------------------------

def _fill(workspace, settings, day):
    from bot.prompts import fill_prompt
    from pipeline.company_data import load_company_data

    data = load_company_data(workspace)
    return fill_prompt("short", "EXMPL", data, workspace, settings,
                       move_kind=day)


def test_an_earnings_day_prompt_asks_for_quarters_and_the_cause(workspace,
                                                               settings):
    day = mk.classify("EXMPL", TODAY, release=RELEASE, news=[])
    text = _fill(workspace, settings, day)
    assert not re.search(r"\{\{[a-z_]+\}\}", text.split("## SYSTEM ROLE", 1)[-1])
    assert "THIS IS AN EARNINGS REACTION" in text
    assert "Boeing Reports Third-Quarter Results" in text, "the release itself"
    assert "SAME QUARTER A YEAR EARLIER" in text
    from pipeline.company_data import load_company_data

    heads = sd.quarter_labels(load_company_data(workspace))[-6:]
    assert f'"years": [{", ".join(json.dumps(h) for h in heads)}]' in text
    assert '"reported":' in text and '"expected":' in text
    assert "trailing-twelve-month" in text


def test_a_news_day_prompt_keeps_the_years_and_the_plain_cut(workspace, settings):
    day = mk.classify("EXMPL", TODAY, release=None, news=[
        {"date": "2026-10-27", "headline": "EXMPL wins a contract",
         "source": "Reuters"}])
    text = _fill(workspace, settings, day)
    assert not re.search(r"\{\{[a-z_]+\}\}", text.split("## SYSTEM ROLE", 1)[-1])
    assert "COMPANY-NEWS DAY" in text and "EXMPL wins a contract" in text
    assert '"FY21", "FY22"' in text
    assert '"reported":' not in text


# ---------------------------------------------------------------------------
# The bot: routing and /kind
# ---------------------------------------------------------------------------

CHAT = 4242


@pytest.fixture()
def core(settings):
    from bot.handlers import BotCore

    return BotCore(settings)


def test_an_earnings_day_routes_to_the_earnings_cut(core, settings):
    from pipeline.workspace import Workspace

    core.start_lane(CHAT, "short", "EXMPL")
    ws = Workspace.latest_for(settings, "EXMPL")
    assert core.short_format_name(ws) == "short"
    ws.set_move_kind({"kind": "earnings", "override": ""})
    assert core.short_format_name(ws) == "earnings"


def test_kind_sets_the_day_and_remakes_the_prompt(core, settings):
    from pipeline.workspace import Workspace

    core.start_lane(CHAT, "short", "EXMPL")
    ws = Workspace.latest_for(settings, "EXMPL")
    shutil.copy(Path(__file__).resolve().parents[1] / "fixtures" /
                "company_data" / "dennis_data.xlsx", ws.path / "dennis_data.xlsx")
    reply = core.kind_command(CHAT, ["earnings"])
    assert "set as an earnings reaction" in reply.text
    assert ws.move_kind()["override"] == "earnings"
    assert ws.move_kind()["kind"] == "earnings", "the prompt was made again"
    assert "THIS IS AN EARNINGS REACTION" in (
        ws.path / "prompt_short.md").read_text(encoding="utf-8")
    assert "Usage" in core.kind_command(CHAT, []).text


# ---------------------------------------------------------------------------
# Wikimedia's User-Agent and the metric card's headroom
# ---------------------------------------------------------------------------

def test_wikimedia_is_told_who_is_asking_without_a_personal_address():
    from pipeline.broll import WIKIMEDIA_AGENT

    assert "https://github.com/" in WIKIMEDIA_AGENT
    assert "@" not in WIKIMEDIA_AGENT


@pytest.mark.parametrize("values", [
    [62.3, 66.6, 77.8, 66.5, 78.4, 95.0],
    [23.3, 23.5, 17.8, 22.0, 23.0, 23.3],
    [0.3, 0.9, 1.5, 2.1],
])
def test_a_metric_card_leaves_its_caption_a_row_above_the_bars(values):
    from pipeline.render_short import METRIC_HEADROOM

    ticks = sd.axis_ticks(values, headroom=METRIC_HEADROOM)
    assert max(values) <= 0.75 * ticks[-1] + 1e-9
    assert ticks[0] <= min([0.0] + values)
    # The broll charts and every other caller keep the old scale.
    assert sd.axis_ticks([0.3, 0.9, 1.5, 2.1])[-1] == pytest.approx(2.4)


def test_the_move_card_reads_price_day_and_rest_off_the_session(settings,
                                                                tmp_path):
    """The fixture's session closed up 29% on 11 Sep 2026."""
    from pipeline.models import ShortScript
    from pipeline.render_short import ShortResolver

    script = ShortScript.model_validate({
        "ticker": "EXMPL", "format": "short", "hook_text": "A muted hook.",
        "audio_script": "Numbers first. Then the point. Noise.",
        "move_summary": "+29% today · 5× average volume",
        "headlines": [{"text": "H", "meaning": "M"}],
        "numbers": [{"label": "Rev", "values": ["$1M", "$2M"]}],
        "numbers_comment": "flat", "conclusion": "Noise."})
    r = ShortResolver(script=script, workdir=tmp_path, settings=settings,
                      prices=None, handle="@channel")
    assert r.text_for("chart.move_price") == "$84.20 at the close, from $65.28"
    assert r.text_for("chart.move_kicker") == "EXMPL · 11 SEPTEMBER"
    assert r.text_for("chart.move_caption") == "today · 5× average volume"


def test_the_session_card_is_dated_in_the_room_its_kicker_has(settings):
    from pipeline.plates import load_plates
    from pipeline.prices import get_intraday

    session = get_intraday("EXMPL", settings)
    card = sd.session_card(session, NS(ticker="EXMPL", move_summary="+29% today"))
    plate = load_plates(settings.assets_dir).get("charts/intraday-9x16")
    for slot in ("kicker", "unit"):
        role = plate.slot(slot).role
        assert len(card[slot]) <= int(plate.type_roles[role]["maxChars"]), slot
    assert card["kicker"] == "EXMPL · 11 SEP"
