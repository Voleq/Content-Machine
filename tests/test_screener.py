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
