"""Candidate sourcing (§14): the front of the funnel.

Two lanes → two formats:
  * trending  (Yahoo movers + StockTwits buzz)  → SHORT candidates
  * value     (Yahoo EquityQuery beaten-down)   → LONG candidates

Data-only and near-zero-cost: never triggers TTS or a render. Every
source sits behind an interface (MarketSource / SentimentSource) so
providers can be swapped; every failure degrades gracefully — a dead
StockTwits runs the trending lane on Yahoo alone (and says so), a dead
Yahoo yields an empty, labelled lane. Screener failures never block the
pipeline and never cost money. MOCK_MODE serves fixture JSON.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Protocol

import httpx

from config import Settings
from pipeline.models import Candidate, Lane
from pipeline.workspace import audited_tickers_since

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Interfaces.
# ---------------------------------------------------------------------------


class MarketSource(Protocol):
    def trending_movers(self) -> list[dict]: ...
    def value_candidates(self) -> list[dict]: ...


class SentimentSource(Protocol):
    def trending(self) -> list[dict] | None: ...


# ---------------------------------------------------------------------------
# Yahoo (yfinance with yahooquery fallback).
# ---------------------------------------------------------------------------


class YahooMarketSource:
    """Predefined screens for the trending lane; a custom EquityQuery with
    sanity filters for the value lane (52w metrics come back on the quotes
    and are filtered client-side — the query fields for them are unstable)."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def _predefined(self, key: str, size: int = 25) -> list[dict]:
        try:
            import yfinance as yf

            body = yf.screen(key, size=size)
            return list((body or {}).get("quotes", []))
        except Exception as e:
            log.warning("yfinance screen %s failed (%s); trying yahooquery", key, e)
        try:  # known yfinance size/offset quirks — yahooquery fallback (§14)
            from yahooquery import Screener

            s = Screener()
            data = s.get_screeners([key], count=size)
            return list(data.get(key, {}).get("quotes", []))
        except Exception as e:
            log.warning("yahooquery screener %s failed too (%s)", key, e)
            return []

    def trending_movers(self) -> list[dict]:
        seen: dict[str, dict] = {}
        for key in ("most_actives", "day_gainers", "day_losers"):
            for q in self._predefined(key):
                sym = q.get("symbol")
                if sym and sym not in seen:
                    seen[sym] = q
        return list(seen.values())

    def quotes(self, tickers: list[str]) -> list[dict]:
        """Live quotes for named tickers — what intraday alerting watches.

        One batched request rather than one per ticker: the watchlist is
        small, but hammering an unofficial endpoint per name every few minutes
        is exactly how a polite client gets blocked. Degrades to [].
        """
        if not tickers:
            return []
        try:
            import yfinance as yf

            data = yf.Tickers(" ".join(tickers))
            out: list[dict] = []
            for sym in tickers:
                try:
                    info = data.tickers[sym].fast_info
                    out.append({
                        "symbol": sym,
                        "regularMarketPrice": getattr(info, "last_price", None),
                        "regularMarketVolume": getattr(info, "last_volume", None),
                        "averageDailyVolume3Month": getattr(
                            info, "three_month_average_volume", None),
                        "regularMarketChangePercent": _pct_change(info),
                    })
                except Exception as e:  # noqa: BLE001 - one bad symbol, not all
                    log.debug("quote for %s failed (%s)", sym, e)
            return out
        except Exception as e:  # noqa: BLE001
            log.warning("batch quote fetch failed (%s)", e)
            return []

    def value_candidates(self) -> list[dict]:
        try:
            import yfinance as yf

            q = yf.EquityQuery("and", [
                yf.EquityQuery("gt", ["intradayprice", self.settings.screen_min_price]),
                yf.EquityQuery("gt", ["intradaymarketcap", self.settings.screen_min_market_cap]),
                yf.EquityQuery("gt", ["avgdailyvol3m", self.settings.screen_min_avg_volume]),
                yf.EquityQuery("eq", ["region", "us"]),
            ])
            body = yf.screen(q, sortField="percentchange", sortAsc=True, size=100)
            return list((body or {}).get("quotes", []))
        except Exception as e:
            log.warning("value EquityQuery failed (%s); using day_losers pool", e)
            return self._predefined("day_losers", size=50)


class MockMarketSource:
    def __init__(self, settings: Settings):
        self.dir = settings.fixtures_dir / "screener"

    def trending_movers(self) -> list[dict]:
        return json.loads((self.dir / "yahoo_trending.json").read_text(encoding="utf-8"))["quotes"]

    def value_candidates(self) -> list[dict]:
        return json.loads((self.dir / "yahoo_value.json").read_text(encoding="utf-8"))["quotes"]


# ---------------------------------------------------------------------------
# StockTwits (volatile, unofficial — cache, back off, degrade).
# ---------------------------------------------------------------------------


class StockTwitsSentimentSource:
    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.settings = settings
        self._client = client
        self.cache_file = settings.state_dir / "stocktwits_cache.json"

    def trending(self) -> list[dict] | None:
        # short-TTL cache (§14): the endpoint is rate-limited and may change
        try:
            cached = json.loads(self.cache_file.read_text(encoding="utf-8"))
            if time.time() - cached["ts"] < self.settings.screener_cache_ttl_s:
                return cached["symbols"]
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            pass
        try:
            client = self._client or httpx.Client(timeout=20)
            try:
                r = client.get(
                    f"{self.settings.stocktwits_base_url}/api/2/trending/symbols.json"
                )
            finally:
                if self._client is None:
                    client.close()
            if r.status_code == 429:
                log.warning("stocktwits 429 — backing off for one TTL")
                self._save_cache([])  # negative-cache the backoff window
                return None
            if r.status_code != 200:
                log.warning("stocktwits %s — degrading to Yahoo-only", r.status_code)
                return None
            symbols = r.json().get("symbols", [])
            self._save_cache(symbols)
            return symbols
        except httpx.HTTPError as e:
            log.warning("stocktwits unavailable (%s) — degrading to Yahoo-only", e)
            return None

    def _save_cache(self, symbols: list[dict]) -> None:
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        self.cache_file.write_text(json.dumps({"ts": time.time(), "symbols": symbols}), encoding="utf-8")


class MockSentimentSource:
    def __init__(self, settings: Settings):
        self.dir = settings.fixtures_dir / "screener"

    def trending(self) -> list[dict] | None:
        return json.loads((self.dir / "stocktwits_trending.json").read_text(encoding="utf-8"))["symbols"]


# ---------------------------------------------------------------------------
# Scoring + hygiene.
# ---------------------------------------------------------------------------


def _passes_hygiene(q: dict, settings: Settings) -> bool:
    price = q.get("regularMarketPrice") or 0
    mcap = q.get("marketCap") or 0
    avg_vol = q.get("averageDailyVolume3Month") or 0
    sym = (q.get("symbol") or "").upper()
    if settings.screen_deny_list and sym in settings.screen_deny_list:
        return False
    if settings.screen_allow_list and sym not in settings.screen_allow_list:
        return False
    return (
        bool(sym)
        and price >= settings.screen_min_price
        and mcap >= settings.screen_min_market_cap
        and avg_vol >= settings.screen_min_avg_volume
    )


def score_trending(
    quotes: list[dict], st_symbols: list[dict] | None, settings: Settings
) -> list[Candidate]:
    """Buzz score: |% move| + volume/avg ratio + StockTwits rank/heat."""
    quotes = [q for q in quotes if _passes_hygiene(q, settings)]
    if not quotes:
        return []
    st_rank: dict[str, int] = {}
    st_heat: dict[str, float] = {}
    if st_symbols:
        max_watch = max((s.get("watchlist_count") or 1) for s in st_symbols)
        for i, s in enumerate(st_symbols):
            sym = (s.get("symbol") or "").upper()
            st_rank[sym] = i + 1
            st_heat[sym] = (s.get("watchlist_count") or 0) / max_watch

    max_move = max(abs(q.get("regularMarketChangePercent") or 0) for q in quotes) or 1
    ratios = {}
    for q in quotes:
        vol = q.get("regularMarketVolume") or 0
        avg = q.get("averageDailyVolume3Month") or 1
        ratios[q["symbol"]] = vol / max(avg, 1)
    max_ratio = max(ratios.values()) or 1

    out: list[Candidate] = []
    for q in quotes:
        sym = q["symbol"].upper()
        move = q.get("regularMarketChangePercent") or 0.0
        ratio = ratios[q["symbol"]]
        n_move = abs(move) / max_move
        n_ratio = ratio / max_ratio
        n_rank = (len(st_rank) - st_rank[sym] + 1) / len(st_rank) if sym in st_rank else 0.0
        n_heat = st_heat.get(sym, 0.0)
        score = 0.35 * n_move + 0.25 * n_ratio + 0.25 * n_rank + 0.15 * n_heat

        reasons = [f"{move:+.1f}% today"]
        if ratio >= 1.5:
            reasons.append(f"vol {ratio:.1f}× avg")
        if sym in st_rank:
            reasons.append(f"ST #{st_rank[sym]} trending")
        out.append(Candidate(
            ticker=sym, lane=Lane.TRENDING, score=round(score, 4),
            reasons=reasons, price=q.get("regularMarketPrice"),
            pct_change=move,
            metrics={"volume_ratio": round(ratio, 2)},
        ))
    out.sort(key=lambda c: c.score, reverse=True)
    return out


def score_value(
    quotes: list[dict], st_symbols: list[dict] | None, settings: Settings
) -> list[Candidate]:
    """Beaten-down score: drawdown from 52w high + proximity to 52w low +
    cheap valuation; StockTwits presence only as a light capitulation flag."""
    out: list[Candidate] = []
    st_set = {(s.get("symbol") or "").upper() for s in (st_symbols or [])}
    for q in quotes:
        if not _passes_hygiene(q, settings):
            continue
        price = q.get("regularMarketPrice") or 0
        low = q.get("fiftyTwoWeekLow") or 0
        high = q.get("fiftyTwoWeekHigh") or 0
        if not price or not low or not high or high <= low:
            continue
        drawdown_pct = (high - price) / high * 100
        dist_low_pct = (price - low) / low * 100
        if drawdown_pct < settings.screen_value_drawdown_pct:
            continue
        if dist_low_pct > settings.screen_value_low_pct:
            continue

        n_draw = min((drawdown_pct - settings.screen_value_drawdown_pct) / 50.0, 1.0)
        n_low = 1.0 - dist_low_pct / settings.screen_value_low_pct
        ps = q.get("priceToSalesTrailing12Months")
        pe = q.get("trailingPE")
        cheap = 0.0
        if isinstance(ps, (int, float)) and ps > 0:
            cheap = max(cheap, min(1.0, 1.0 / ps))
        if isinstance(pe, (int, float)) and 0 < pe:
            cheap = max(cheap, min(1.0, 8.0 / pe))
        sym = q["symbol"].upper()
        flag = 0.1 if sym in st_set else 0.0
        score = 0.40 * n_draw + 0.35 * n_low + 0.25 * cheap + flag

        reasons = [f"−{drawdown_pct:.0f}% off 52w high", f"{dist_low_pct:.0f}% above 52w low"]
        if isinstance(ps, (int, float)):
            reasons.append(f"P/S {ps:.1f}")
        elif isinstance(pe, (int, float)):
            reasons.append(f"P/E {pe:.1f}")
        if flag:
            reasons.append("retail capitulation buzz")
        out.append(Candidate(
            ticker=sym, lane=Lane.VALUE, score=round(score, 4),
            reasons=reasons, price=price, pct_change=q.get("regularMarketChangePercent"),
            metrics={"drawdown_pct": round(drawdown_pct, 1),
                     "dist_low_pct": round(dist_low_pct, 1)},
        ))
    out.sort(key=lambda c: c.score, reverse=True)
    return out


# ---------------------------------------------------------------------------
# The screener runner.
# ---------------------------------------------------------------------------


def make_sources(settings: Settings) -> tuple[MarketSource, SentimentSource]:
    if settings.mocking_screener:
        return MockMarketSource(settings), MockSentimentSource(settings)
    return YahooMarketSource(settings), StockTwitsSentimentSource(settings)


def run_screen(settings: Settings, lane: str = "all") -> dict[str, list[Candidate]]:
    """Returns {'trending': [...], 'value': [...], 'updates': [...]} after
    hygiene, cooldown dedup and top-N capping. Never raises; empty lanes mean
    degraded.

    The cooldown suppresses a recently-covered ticker as a FRESH candidate,
    which is right and stays. It must not suppress an update, because being
    recently covered is the precondition for one rather than a reason to skip
    it — a thesis that broke three weeks after the video is the single
    strongest thing this bot knows, and the cooldown was hiding it from the one
    surface the operator reads every morning.
    """
    market, sentiment = make_sources(settings)
    cooled = audited_tickers_since(settings, settings.cooldown_days)
    st_symbols = None
    result: dict[str, list[Candidate]] = {}

    if lane in ("trending", "all"):
        try:
            st_symbols = sentiment.trending()
        except Exception as e:  # pragma: no cover — belt and braces
            log.warning("sentiment source blew up: %s", e)
            st_symbols = None
        try:
            movers = market.trending_movers()
        except Exception as e:
            log.warning("market source blew up: %s", e)
            movers = []
        cands = [c for c in score_trending(movers, st_symbols, settings)
                 if c.ticker not in cooled]
        result["trending"] = cands[: settings.screen_top_n]
        result["trending_degraded"] = st_symbols is None  # type: ignore[assignment]

    if lane in ("value", "all"):
        try:
            pool = market.value_candidates()
        except Exception as e:
            log.warning("market source blew up: %s", e)
            pool = []
        cands = [c for c in score_value(pool, st_symbols, settings)
                 if c.ticker not in cooled]
        result["value"] = cands[: settings.screen_top_n]

    # The update lane, exempt from the cooldown by construction: it is built
    # from the thesis book rather than from candidates, and every ticker in it
    # is cooled — that is what having covered it means.
    result["updates"] = _theses_worth_revisiting(settings)  # type: ignore[assignment]

    _save_last_screen(settings, result)
    # Every screen feeds the standing backlog (P3.3), so a session opens with
    # a list instead of a blank page. Best-effort — bookkeeping must never
    # break a screen.
    try:
        from pipeline.standing import ideas_from_screen

        ideas_from_screen(settings, result)
    except Exception as e:  # noqa: BLE001
        log.warning("could not feed the idea queue: %s", e)
    return result


def _theses_worth_revisiting(settings: Settings) -> list[str]:
    """Covered tickers whose thesis is no longer intact.

    Read off the last recorded check rather than re-checking here: a screen
    runs against live sources and this must not turn into a second data pull
    that can fail. `/thesis` is what updates the status; this only surfaces it.

    Best-effort, like every other piece of standing-state bookkeeping in this
    module — a screen still screens when the book is unreadable.
    """
    try:
        from pipeline.standing import ThesisBook

        book = ThesisBook(settings)
        return [t for t in book.tickers()
                if (book.get(t) or None) and book.get(t).status != "intact"]
    except Exception as e:  # noqa: BLE001
        log.warning("could not read the thesis book for the update lane: %s", e)
        return []


def _save_last_screen(settings: Settings, result: dict) -> None:
    """Persist the run so the SHORT master prompt can carry the ticker's
    move context ({{move_context}}) without re-hitting any source."""
    entries: dict[str, dict] = {}
    for lane_name in ("trending", "value"):
        for c in result.get(lane_name, []) or []:
            entries[c.ticker] = {
                "lane": c.lane.value, "reasons": c.reasons,
                "price": c.price, "pct_change": c.pct_change,
            }
    try:
        path = settings.state_dir / "last_screen.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"ts": time.time(), "tickers": entries}), encoding="utf-8")
    except OSError as e:  # advisory only — never let it break a screen
        log.warning("could not persist last screen: %s", e)


def last_screen_context(settings: Settings, ticker: str) -> str:
    """The move context for a ticker from the most recent screen run, or ""
    when unknown/stale (older than one trading day)."""
    path = settings.state_dir / "last_screen.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return ""
    if time.time() - float(data.get("ts", 0)) > 86400:
        return ""
    entry = (data.get("tickers") or {}).get(ticker.upper())
    if not entry:
        return ""
    bits = list(entry.get("reasons") or [])
    if entry.get("lane"):
        bits.append(f"{entry['lane']} lane")
    return " · ".join(bits)


def last_screen_lane(settings: Settings, ticker: str) -> str:
    """Which lane the last screen put this ticker in — `""` if it didn't.

    Used by `/short` and `/long` to warn when a ticker looks like the wrong
    lane. Deliberately advisory: the screener is a suggestion engine and the
    operator's judgement outranks it, so a mismatch is a sentence in the reply,
    never a refusal.
    """
    path = settings.state_dir / "last_screen.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return ""
    if time.time() - float(data.get("ts", 0)) > 86400:
        return ""
    entry = (data.get("tickers") or {}).get(ticker.upper())
    return str(entry.get("lane") or "") if entry else ""


def digest_text(result: dict) -> str:
    lines: list[str] = []
    if "trending" in result:
        header = "🔥 Trending lane (SHORT candidates)"
        if result.get("trending_degraded"):
            header += " — Yahoo only, StockTwits unavailable"
        lines.append(header)
        if not result["trending"]:
            lines.append("  (no candidates passed the filters)")
        for c in result["trending"]:
            lines.append(f"  {c.ticker}: {c.why}")
    if "value" in result:
        lines.append("🕳 Beaten-down lane (LONG candidates)")
        if not result["value"]:
            lines.append("  (no candidates passed the filters)")
        for c in result["value"]:
            lines.append(f"  {c.ticker}: {c.why}")
    if result.get("updates"):
        lines.append("🔁 Already covered, thesis moved (UPDATE candidates)")
        for ticker in result["updates"]:
            lines.append(f"  {ticker}: /update {ticker}")
    lines.append("\nTap a ticker to open its workspace (/new).")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Bot integration (imported lazily by bot/handlers.py and main.py).
# ---------------------------------------------------------------------------


async def screen_reply(core, lane: str = "all"):
    """Builds the /screen Reply. Runs sources in a thread — never blocks
    the bot loop."""
    import asyncio

    from bot.handlers import Reply
    from bot.keyboards import candidates_keyboard

    if lane not in ("trending", "value", "all"):
        return Reply("Usage: /screen [trending|value|all]")
    result = await asyncio.to_thread(run_screen, core.settings, lane)
    tickers = [c.ticker for c in result.get("trending", [])] + \
              [c.ticker for c in result.get("value", [])]
    seen: list[str] = []
    for t in tickers:
        if t not in seen:
            seen.append(t)
    return Reply(digest_text(result),
                 keyboard=candidates_keyboard(seen) if seen else None)


def parse_cron(expr: str) -> tuple[int, int, tuple[int, ...]]:
    """'M H * * DOW' -> (minute, hour, ptb_days). Supports lists/ranges/*
    in the DOW field; day numbering: cron 0/7=Sun … 6=Sat -> PTB 0=Mon."""
    fields = expr.split()
    if len(fields) != 5:
        raise ValueError(f"cron must have 5 fields: {expr!r}")
    minute, hour = int(fields[0]), int(fields[1])
    dow_field = fields[4]
    if dow_field == "*":
        days = tuple(range(7))
    else:
        cron_days: set[int] = set()
        for part in dow_field.split(","):
            if "-" in part:
                a, b = part.split("-")
                cron_days.update(range(int(a), int(b) + 1))
            else:
                cron_days.add(int(part))
        days = tuple(sorted(((d % 7) - 1) % 7 for d in cron_days))
    return minute, hour, days


def _pct_change(info) -> float | None:
    """Percent change from the previous close, when both numbers are there."""
    last = getattr(info, "last_price", None)
    prev = getattr(info, "previous_close", None)
    try:
        if last and prev and float(prev) != 0:
            return (float(last) - float(prev)) / float(prev) * 100.0
    except (TypeError, ValueError):
        pass
    return None


def schedule_digest(application, core) -> None:
    """Morning digest via PTB's JobQueue (APScheduler under the hood)."""
    from datetime import time as dtime
    from zoneinfo import ZoneInfo

    settings = core.settings
    try:
        minute, hour, days = parse_cron(settings.screen_digest_cron)
    except ValueError as e:
        log.warning("SCREEN_DIGEST_CRON invalid (%s) — digest disabled", e)
        return

    async def digest_job(ctx) -> None:
        import asyncio

        from bot.keyboards import candidates_keyboard

        result = await asyncio.to_thread(run_screen, settings, "all")
        text = "🌅 Morning screen\n\n" + digest_text(result)
        tickers = [c.ticker for lane in ("trending", "value")
                   for c in result.get(lane, [])]
        kb = candidates_keyboard(list(dict.fromkeys(tickers))) if tickers else None
        for chat_id in settings.operator_chat_ids:
            await ctx.bot.send_message(chat_id, text, reply_markup=kb)

    application.job_queue.run_daily(
        digest_job,
        time=dtime(hour=hour, minute=minute, tzinfo=ZoneInfo(settings.screen_timezone)),
        days=days,
        name="screen_digest",
    )
    log.info("screen digest scheduled: %02d:%02d %s days=%s",
             hour, minute, settings.screen_timezone, days)


def schedule_alerts(application, core) -> None:
    """Intraday watch (3b), on the same JobQueue as the digest.

    A repeating job rather than a cron: what matters is "every N minutes
    while the market is open", and the quiet-hours check inside the poll is
    what decides whether a given firing says anything. Keeping that decision
    in one place means the tests exercise the real gate.
    """
    settings = core.settings
    if not settings.alerts_enabled:
        log.info("intraday alerts disabled")
        return

    async def alert_job(ctx) -> None:
        import asyncio

        from pipeline.alerts import (
            Watchlist, digest, fetch_filings, fetch_quotes, poll_once,
        )

        try:
            tickers = Watchlist(settings).all()
            quotes = await asyncio.to_thread(fetch_quotes, settings, tickers)
            filings = await asyncio.to_thread(fetch_filings, settings, tickers)
            alerts = await asyncio.to_thread(poll_once, settings, quotes=quotes,
                                             filings=filings)
        except Exception as e:  # noqa: BLE001 - a watch that dies is silent
            log.warning("alert poll failed (%s) — skipping this pass", e)
            return
        if not alerts:
            return
        text = digest(alerts, settings)
        for chat_id in settings.operator_chat_ids:
            await ctx.bot.send_message(chat_id, text)

    interval = max(1, settings.alert_poll_minutes) * 60
    application.job_queue.run_repeating(
        alert_job, interval=interval, first=interval, name="intraday_alerts")
    log.info("intraday alerts scheduled every %d min (%02d:00-%02d:00 %s)",
             settings.alert_poll_minutes, settings.alert_start_hour,
             settings.alert_end_hour, settings.screen_timezone)
