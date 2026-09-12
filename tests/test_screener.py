import httpx
import pytest

from pipeline.models import Lane
from pipeline.screener import (
    MockMarketSource,
    MockSentimentSource,
    StockTwitsSentimentSource,
    digest_text,
    parse_cron,
    run_screen,
    score_trending,
    score_value,
)
from pipeline.workspace import Workspace


def test_trending_scoring_and_hygiene(settings):
    quotes = MockMarketSource(settings).trending_movers()
    st = MockSentimentSource(settings).trending()
    cands = score_trending(quotes, st, settings)
    tickers = [c.ticker for c in cands]
    assert "TINY" not in tickers, "market-cap floor must exclude it"
    assert "MEME" in tickers and "HYPE" in tickers
    # MEME: -22.5% move, 5x volume, ST #1 -> should out-rank QUIET
    assert tickers.index("MEME") < tickers.index("QUIET")
    meme = next(c for c in cands if c.ticker == "MEME")
    assert any("ST #1" in r for r in meme.reasons)
    assert any("vol" in r for r in meme.reasons)
    assert "-22.5% today" in meme.why


def test_trending_degrades_without_stocktwits(settings):
    quotes = MockMarketSource(settings).trending_movers()
    cands = score_trending(quotes, None, settings)
    assert cands, "Yahoo-only lane must still produce candidates"
    assert all(not any("ST #" in r for r in c.reasons) for c in cands)


def test_value_scoring_filters(settings):
    quotes = MockMarketSource(settings).value_candidates()
    cands = score_value(quotes, None, settings)
    tickers = [c.ticker for c in cands]
    assert "FALLEN" in tickers          # −75% off high, 7% above low, P/S 0.38
    assert "MIDWAY" not in tickers      # only −33% off high
    assert "PENNY" not in tickers       # fails price/mcap/volume floors
    fallen = next(c for c in cands if c.ticker == "FALLEN")
    assert fallen.lane is Lane.VALUE
    assert any("off 52w high" in r for r in fallen.reasons)


def test_run_screen_applies_cooldown(settings):
    from pipeline.workspace import today_str

    Workspace(settings, "MEME", today_str()).create()  # audited recently
    result = run_screen(settings, "all")
    trending = [c.ticker for c in result["trending"]]
    assert "MEME" not in trending, "cooldown must exclude recent audits"
    assert "HYPE" in trending
    assert len(result["trending"]) <= settings.screen_top_n
    assert result["value"], "value lane populated from fixtures"
    text = digest_text(result)
    assert "Trending lane" in text and "Beaten-down lane" in text


def test_run_screen_never_raises_on_dead_sources(settings, monkeypatch):
    import pipeline.screener as scr

    class DeadMarket:
        def trending_movers(self):
            raise RuntimeError("yahoo down")

        def value_candidates(self):
            raise RuntimeError("yahoo down")

    class DeadSentiment:
        def trending(self):
            raise RuntimeError("stocktwits down")

    monkeypatch.setattr(scr, "make_sources", lambda s: (DeadMarket(), DeadSentiment()))
    result = run_screen(settings, "all")
    assert result["trending"] == [] and result["value"] == []
    assert result["trending_degraded"] is True
    assert "no candidates" in digest_text(result)


def test_stocktwits_client_caches_and_backs_off(settings):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"symbols": [{"symbol": "ABC", "watchlist_count": 5}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    src = StockTwitsSentimentSource(settings, client=client)
    first = src.trending()
    second = src.trending()
    assert first == second and len(calls) == 1, "short-TTL cache must absorb repeats"

    def handler_429(request):
        calls.append(request)
        return httpx.Response(429)

    src2 = StockTwitsSentimentSource(settings, client=httpx.Client(
        transport=httpx.MockTransport(handler_429)))
    src2.cache_file.unlink()
    assert src2.trending() is None, "429 must degrade, not raise"
    # the backoff negative-cache absorbs the next call
    assert src2.trending() == []


def test_stocktwits_network_error_degrades(settings):
    def handler(request):
        raise httpx.ConnectError("boom")

    src = StockTwitsSentimentSource(settings, client=httpx.Client(
        transport=httpx.MockTransport(handler)))
    assert src.trending() is None


def test_parse_cron():
    assert parse_cron("30 7 * * 1-5") == (30, 7, (0, 1, 2, 3, 4))
    assert parse_cron("0 9 * * *")[2] == tuple(range(7))
    assert parse_cron("15 6 * * 0,6")[2] == (5, 6)  # Sun,Sat -> PTB Sat=5? cron0=Sun->PTB6
    with pytest.raises(ValueError):
        parse_cron("not a cron")


async def test_screen_reply_shape(settings):
    from bot.handlers import BotCore
    from pipeline.screener import screen_reply

    core = BotCore(settings)
    reply = await screen_reply(core, "all")
    assert "Trending lane" in reply.text
    assert reply.keyboard is not None
    reply2 = await screen_reply(core, "bogus")
    assert "Usage" in reply2.text


# --------------------------------------------------------------------------
# B2 — "today" in a SHORT script has to mean today. The screener's cached
# string says it about the day the SCREEN ran, which is pre-market, which on
# a Monday is Friday's close.
# --------------------------------------------------------------------------


def test_a_live_quote_is_the_real_intraday_move(settings, monkeypatch):
    """`_pct_change` on a live quote is last vs previous close."""
    from pipeline.screener import live_move_context

    live = settings.model_copy(update={"mock_screener": False})

    class FakeSource:
        def __init__(self, *a, **k):
            pass

        def quotes(self, tickers):
            return [{"symbol": "EXMPL", "regularMarketPrice": 22.0,
                     "regularMarketChangePercent": 10.4,
                     "regularMarketVolume": 5_000_000,
                     "averageDailyVolume3Month": 1_000_000}]

    monkeypatch.setattr("pipeline.screener.YahooMarketSource", FakeSource)
    text = live_move_context(live, "EXMPL")

    assert "+10.4% so far today" in text
    assert "5.0x avg" in text


def test_a_dead_quote_feed_is_silent_not_wrong(settings, monkeypatch):
    from pipeline.screener import live_move_context

    live = settings.model_copy(update={"mock_screener": False})

    class Dead:
        def __init__(self, *a, **k):
            pass

        def quotes(self, tickers):
            raise RuntimeError("yahoo is down")

    monkeypatch.setattr("pipeline.screener.YahooMarketSource", Dead)
    assert live_move_context(live, "EXMPL") == ""


def test_a_stale_screener_line_says_how_stale_it_is(settings):
    """The word "today" cannot be left standing on a day-old figure."""
    import json
    import time

    from pipeline.screener import last_screen_context

    state = settings.state_dir / "last_screen.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps({
        "ts": time.time() - 6 * 3600,
        "tickers": {"EXMPL": {"lane": "trending", "reasons": ["+0.5% today"]}},
    }), encoding="utf-8")

    text = last_screen_context(settings, "EXMPL")
    assert "+0.5% today" in text
    assert "NOT as of now" in text and "6h ago" in text


def test_a_fresh_screener_line_is_left_alone(settings):
    import json
    import time

    from pipeline.screener import last_screen_context

    state = settings.state_dir / "last_screen.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps({
        "ts": time.time() - 60,
        "tickers": {"EXMPL": {"lane": "trending", "reasons": ["+9.0% today"]}},
    }), encoding="utf-8")

    assert "NOT as of now" not in last_screen_context(settings, "EXMPL")


def test_the_short_prompt_carries_the_live_move_not_the_cached_one(
        settings, monkeypatch, fixtures_dir):
    """End to end, on the prompt file the operator actually receives."""
    import json
    import time

    from bot.handlers import BotCore

    live = settings.model_copy(update={"mock_screener": False})
    state = live.state_dir / "last_screen.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps({
        "ts": time.time() - 6 * 3600,
        "tickers": {"EXMPL": {"lane": "trending", "reasons": ["+0.5% today"]}},
    }), encoding="utf-8")

    class FakeSource:
        def __init__(self, *a, **k):
            pass

        def quotes(self, tickers):
            return [{"symbol": "EXMPL", "regularMarketPrice": 22.0,
                     "regularMarketChangePercent": 10.4}]

    monkeypatch.setattr("pipeline.screener.YahooMarketSource", FakeSource)

    core = BotCore(live)
    core.start_lane(7788, "short", "EXMPL")
    reply = core.handle_upload(
        7788, "dennis_data.xlsx",
        (fixtures_dir / "company_data" / "dennis_data.xlsx").read_bytes())
    prompt = next(f for f in reply.files if "short" in f.name).read_text(encoding="utf-8")

    assert "+10.4% so far today" in prompt, "the prompt must carry today's move"
    assert "NOT as of now" in prompt, "and label the stale line it kept"
