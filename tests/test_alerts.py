"""Intraday alerting (addendum 3b).

One pre-market digest suits the value lane; short-form goes stale in hours.
So this watches during market hours — but the hard part is not noticing a
move, it is *not saying so forty times*. A chatty alerter gets muted, and a
muted alerter is worse than no alerter, so most of what follows is about
staying quiet.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pytest

from pipeline.alerts import (
    Alert,
    AlertLog,
    EarningsCalendar,
    Watchlist,
    digest,
    evaluate,
    in_quiet_hours,
    poll_once,
)

MARKET_HOURS = datetime(2026, 7, 27, 14, 0, tzinfo=timezone.utc)   # a Monday


@pytest.fixture()
def live(settings):
    """Alerts on, watching one name, mid-session."""
    Watchlist(settings).add("EXMPL")
    return settings


def quote(symbol="EXMPL", pct=0.0, volume=None, avg=None, price=10.0):
    q = {"symbol": symbol, "regularMarketChangePercent": pct,
         "regularMarketPrice": price}
    if volume is not None:
        q["regularMarketVolume"] = volume
    if avg is not None:
        q["averageDailyVolume3Month"] = avg
    return q


# --------------------------------------------------------------------------
# Thresholds.
# --------------------------------------------------------------------------


def test_a_quiet_day_says_nothing(settings):
    assert evaluate(quote(pct=1.2), settings) == []


def test_a_real_move_is_an_alert_with_the_direction(settings):
    alerts = evaluate(quote(pct=-9.4, price=12.3), settings)
    assert len(alerts) == 1
    assert alerts[0].kind == "move"
    assert "down 9.4%" in alerts[0].headline
    assert "12.3" in alerts[0].detail


def test_volume_is_its_own_signal(settings):
    alerts = evaluate(quote(pct=0.5, volume=9_000_000, avg=2_000_000), settings)
    kinds = [a.kind for a in alerts]
    assert "volume" in kinds
    assert "4.5×" in next(a for a in alerts if a.kind == "volume").headline


def test_a_quote_missing_the_numbers_produces_nothing(settings):
    """An unofficial feed drops fields constantly, and an alert built on a
    missing number is worse than silence."""
    assert evaluate({"symbol": "EXMPL"}, settings) == []
    assert evaluate({"symbol": "EXMPL", "regularMarketChangePercent": None},
                    settings) == []
    assert evaluate({"regularMarketChangePercent": -30.0}, settings) == []
    assert evaluate({"symbol": "EXMPL",
                     "regularMarketChangePercent": float("nan")}, settings) == []


def test_zero_average_volume_does_not_divide_by_zero(settings):
    assert evaluate(quote(volume=1000, avg=0), settings) == []


# --------------------------------------------------------------------------
# Not being chatty.
# --------------------------------------------------------------------------


def test_one_stock_moving_all_day_is_one_alert(live):
    """The whole reason people mute bots."""
    quotes = [quote(pct=-9.0)]
    first = poll_once(live, quotes=quotes, now=MARKET_HOURS)
    assert len(first) == 1

    later = poll_once(live, quotes=quotes,
                      now=MARKET_HOURS + timedelta(minutes=20))
    assert later == [], "it said the same thing twice"


def test_a_materially_worse_move_does_get_through(live):
    """−4% reaching −12% is genuinely new information."""
    poll_once(live, quotes=[quote(pct=-6.5)], now=MARKET_HOURS)
    out = poll_once(live, quotes=[quote(pct=-19.0)],
                    now=MARKET_HOURS + timedelta(minutes=20))
    assert len(out) == 1
    assert "19" in out[0].headline


def test_a_more_severe_kind_outranks_the_cooldown(live):
    """A filing on a name that merely moved is a different event."""
    poll_once(live, quotes=[quote(pct=-9.0)], now=MARKET_HOURS)
    filing = Alert(ticker="EXMPL", kind="filing",
                   headline="Form 4: the CFO sold", magnitude=1.0)
    out = poll_once(live, quotes=[], filings=[filing],
                    now=MARKET_HOURS + timedelta(minutes=5))
    assert [a.kind for a in out] == ["filing"]


def test_the_cooldown_expires(live):
    """Still inside the alert window — this is about the cooldown, not the
    quiet hours (which is why the day starts early here)."""
    morning = datetime(2026, 7, 27, 10, 0, tzinfo=timezone.utc)
    poll_once(live, quotes=[quote(pct=-9.0)], now=morning)
    out = poll_once(live, quotes=[quote(pct=-9.0)],
                    now=morning + timedelta(hours=4))
    assert not in_quiet_hours(live, morning + timedelta(hours=4))
    assert len(out) == 1


def test_a_ticker_speaks_once_per_pass_with_its_biggest_news(live):
    """A name that moved AND spiked on volume is one alert, the important one."""
    out = poll_once(live, quotes=[quote(pct=-11.0, volume=9e6, avg=2e6)],
                    now=MARKET_HOURS)
    assert len(out) == 1
    assert out[0].kind == "move", "the move outranks the volume note"


def test_a_flood_is_capped(settings):
    wl = Watchlist(settings)
    quotes = []
    for i in range(12):
        wl.add(f"T{i}")
        quotes.append(quote(symbol=f"T{i}", pct=-15.0 - i))
    out = poll_once(settings, quotes=quotes, now=MARKET_HOURS)
    assert len(out) == settings.alert_max_per_poll
    # …and the biggest movers are the ones that made the cut
    assert all(a.magnitude >= 20.0 for a in out), [a.magnitude for a in out]


def test_an_uncovered_name_needs_a_much_bigger_move(settings):
    """Otherwise this just duplicates the screener, loudly."""
    modest = poll_once(settings, quotes=[quote(symbol="RANDO", pct=-7.0)],
                       now=MARKET_HOURS)
    assert modest == []
    enormous = poll_once(settings, quotes=[quote(symbol="RANDO", pct=-25.0)],
                         now=MARKET_HOURS)
    assert len(enormous) == 1


# --------------------------------------------------------------------------
# Quiet hours.
# --------------------------------------------------------------------------


def test_nothing_is_pushed_at_night(live):
    night = datetime(2026, 7, 27, 3, 0)
    assert in_quiet_hours(live, night)
    assert poll_once(live, quotes=[quote(pct=-30.0)], now=night) == []


def test_nothing_is_pushed_at_the_weekend(live):
    saturday = datetime(2026, 7, 25, 12, 0)
    assert saturday.weekday() == 5
    assert in_quiet_hours(live, saturday)


def test_weekends_can_be_switched_on(settings):
    s = settings.model_copy(update={"alert_weekends": True})
    assert not in_quiet_hours(s, datetime(2026, 7, 25, 12, 0))


def test_a_window_crossing_midnight_works(settings):
    s = settings.model_copy(update={"alert_start_hour": 22, "alert_end_hour": 4})
    assert not in_quiet_hours(s, datetime(2026, 7, 27, 23, 0))
    assert not in_quiet_hours(s, datetime(2026, 7, 27, 1, 0))
    assert in_quiet_hours(s, datetime(2026, 7, 27, 12, 0))


def test_the_whole_thing_can_be_switched_off(live):
    off = live.model_copy(update={"alerts_enabled": False})
    assert poll_once(off, quotes=[quote(pct=-30.0)], now=MARKET_HOURS) == []


# --------------------------------------------------------------------------
# The watchlist.
# --------------------------------------------------------------------------


def test_covered_names_are_watched_without_being_pinned(settings):
    """The names the bot can say something informed about."""
    from pipeline.standing import ThesisBook

    class Data:
        def get(self, k):
            return 10.0 if k == "price" else None
        history: dict = {}

    ThesisBook(settings).record("COVERED", "a thesis", Data())
    assert "COVERED" in Watchlist(settings).all()


def test_pinning_and_unpinning(settings):
    wl = Watchlist(settings)
    wl.add("exmpl")
    assert "EXMPL" in wl.all()
    assert wl.remove("EXMPL") is True
    assert wl.remove("EXMPL") is False


def test_the_watchlist_survives_a_restart(settings):
    Watchlist(settings).add("EXMPL")
    assert "EXMPL" in Watchlist(settings).all()


# --------------------------------------------------------------------------
# The earnings calendar.
# --------------------------------------------------------------------------


def test_it_knows_in_advance_that_a_name_reports(settings):
    cal = EarningsCalendar(settings)
    cal.set("EXMPL", "2026-07-29", "amc")
    soon = cal.upcoming(within_days=7, today=date(2026, 7, 27))
    assert [e.ticker for e in soon] == ["EXMPL"]
    assert soon[0].when == "amc"


def test_a_distant_print_is_not_upcoming(settings):
    EarningsCalendar(settings).set("EXMPL", "2026-12-01")
    assert EarningsCalendar(settings).upcoming(7, today=date(2026, 7, 27)) == []


def test_both_sides_of_the_print_are_flagged_once_each(settings):
    """Two different videos: a setup, then a reaction — and the reaction is
    the one that has to go out fast."""
    cal = EarningsCalendar(settings)
    cal.set("EXMPL", "2026-07-29", "amc")

    pre = cal.due_alerts(today=date(2026, 7, 29))
    assert len(pre) == 1 and "after the close" in pre[0].headline
    assert cal.due_alerts(today=date(2026, 7, 29)) == [], "flagged twice"

    post = cal.due_alerts(today=date(2026, 7, 30))
    assert len(post) == 1 and "reported" in post[0].headline
    assert cal.due_alerts(today=date(2026, 7, 30)) == []


def test_a_malformed_calendar_row_is_skipped_not_fatal(settings):
    cal = EarningsCalendar(settings)
    cal.set("EXMPL", "2026-07-29")
    cal.path.write_text(json.dumps({"entries": {
        "EXMPL": {"ticker": "EXMPL", "date": "not-a-date", "when": ""}}}), encoding="utf-8")
    assert cal.due_alerts(today=date(2026, 7, 30)) == []
    assert cal.upcoming(today=date(2026, 7, 30)) == []


# --------------------------------------------------------------------------
# One tap from "it moved" to "script running".
# --------------------------------------------------------------------------


def test_every_alert_carries_the_command_that_acts_on_it(live):
    out = poll_once(live, quotes=[quote(pct=-9.0)], now=MARKET_HOURS)
    assert "/short EXMPL" in out[0].render()
    assert "/short EXMPL" in digest(out)


def test_an_empty_digest_is_empty():
    assert digest([]) == ""


# --------------------------------------------------------------------------
# Degrading quietly.
# --------------------------------------------------------------------------


def test_a_dead_feed_produces_no_alerts_rather_than_an_error(settings, monkeypatch):
    from pipeline import alerts as alerts_mod

    live_settings = settings.model_copy(update={"mock_mode": False})

    def boom(*a, **k):
        raise RuntimeError("yahoo is down")

    monkeypatch.setattr("pipeline.screener.YahooMarketSource", boom)
    assert alerts_mod.fetch_quotes(live_settings, ["EXMPL"]) == []


def test_mock_mode_reads_the_fixture_so_the_path_runs_offline(settings):
    from pipeline.alerts import fetch_quotes

    raw = json.loads((settings.fixtures_dir / "screener" /
                      "yahoo_trending.json").read_text(encoding="utf-8"))
    symbols = [q["symbol"] for q in raw["quotes"][:2]]
    got = fetch_quotes(settings, symbols)
    assert {q["symbol"] for q in got} == set(symbols)


def test_no_watchlist_means_no_fetch(settings):
    from pipeline.alerts import fetch_quotes

    assert fetch_quotes(settings, []) == []


# --------------------------------------------------------------------------
# The bot surface.
# --------------------------------------------------------------------------


@pytest.fixture()
def core(settings):
    from bot.handlers import BotCore

    return BotCore(settings)


def test_watch_explains_itself_when_empty(core):
    text = core.watch_command([]).text
    assert "/watch TICKER" in text
    assert "watched automatically" in text


def test_watch_pins_and_lists(core, settings):
    assert "watching EXMPL" in core.watch_command(["exmpl"]).text
    listing = core.watch_command([]).text
    assert "EXMPL" in listing


def test_watch_can_drop_a_pin(core):
    core.watch_command(["EXMPL"])
    assert "unpinned" in core.watch_command(["drop", "EXMPL"]).text


def test_the_listing_shows_upcoming_prints(core, settings):
    core.watch_command(["EXMPL"])
    core.earnings_command(["EXMPL", "2026-12-01", "amc"])
    EarningsCalendar(settings).set("EXMPL", date.today().isoformat(), "amc")
    text = core.watch_command([]).text
    assert "Reporting soon" in text


def test_earnings_rejects_a_bad_date(core):
    assert "isn't a date" in core.earnings_command(["EXMPL", "next tuesday"]).text
    assert "bmo" in core.earnings_command(["EXMPL", "2026-07-29", "lunchtime"]).text


def test_earnings_records_both_the_date_and_the_slot(core, settings):
    reply = core.earnings_command(["exmpl", "2026-07-29", "amc"])
    assert "2026-07-29" in reply.text
    entry = EarningsCalendar(settings).get("EXMPL")
    assert entry is not None and entry.when == "amc"


def test_the_alert_log_can_be_cleared(settings):
    log_ = AlertLog(settings)
    log_.record(Alert(ticker="EXMPL", kind="move", headline="h"), MARKET_HOURS)
    assert log_.clear() == 1
    assert log_.should_send(Alert(ticker="EXMPL", kind="move", headline="h"),
                            MARKET_HOURS)
