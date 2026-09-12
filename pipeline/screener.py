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
from datetime import datetime
from pathlib import Path
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
    # What each source did on this run (J6), reported in the digest.
    health: dict[str, str] = {}

    if lane in ("trending", "all"):
        try:
            st_symbols = sentiment.trending()
            health["stocktwits"] = "ok" if st_symbols else "empty"
        except Exception as e:  # pragma: no cover — belt and braces
            log.warning("sentiment source blew up: %s", e)
            st_symbols = None
            health["stocktwits"] = "failed"
        try:
            movers = market.trending_movers()
            health["yahoo"] = "ok" if movers else "empty"
        except Exception as e:
            log.warning("market source blew up: %s", e)
            movers = []
            health["yahoo"] = "failed"
        cands = [c for c in score_trending(movers, st_symbols, settings)
                 if c.ticker not in cooled]
        result["trending"] = cands[: settings.screen_top_n]
        result["trending_degraded"] = st_symbols is None  # type: ignore[assignment]

    if lane in ("value", "all"):
        try:
            pool = market.value_candidates()
            # Yahoo answers both lanes. A value screen that came back empty
            # while trending worked is a filter result, not a dead source,
            # so an existing "ok" is not downgraded.
            health.setdefault("yahoo", "ok" if pool else "empty")
        except Exception as e:
            log.warning("market source blew up: %s", e)
            pool = []
            health["yahoo"] = "failed"
        cands = [c for c in score_value(pool, st_symbols, settings)
                 if c.ticker not in cooled]
        result["value"] = cands[: settings.screen_top_n]

    # The update lane, exempt from the cooldown by construction: it is built
    # from the thesis book rather than from candidates, and every ticker in it
    # is cooled — that is what having covered it means.
    result["updates"] = _theses_worth_revisiting(settings)  # type: ignore[assignment]
    # A SILENTLY BROKEN SCREENER IS INDISTINGUISHABLE FROM A QUIET MARKET
    # (J6). Yahoo and StockTwits are both unofficial endpoints; a failure
    # degraded to an empty lane and a log line, and the digest still went
    # out — just shorter. So the digest says what each source did.
    result["sources"] = health  # type: ignore[assignment]

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


# How long a screener move figure stays usable in a prompt. The digest fires
# pre-market, so its "+0.5% today" is the PREVIOUS completed session and on a
# Monday that is Friday — a whole trading day of divergence before anyone
# types anything. Twenty minutes is about as long as an intraday move figure
# stays true; past that the text says how old it is rather than pretending.
SCREEN_CONTEXT_FRESH_S = 20 * 60
SCREEN_CONTEXT_MAX_AGE_S = 86400


def last_screen_context(settings: Settings, ticker: str) -> str:
    """The move context for a ticker from the most recent screen run.

    The move figure is STAMPED WITH ITS AGE once it is past
    `SCREEN_CONTEXT_FRESH_S`, because the string the screener writes is
    `"{move:+.1f}% today"` and "today" means the day the screen ran, which
    nothing else records. A model handed "+0.5% today" at 11:00 on a Monday
    reports it faithfully, and it is Friday's close (B2).

    `""` when unknown or older than a day.
    """
    path = settings.state_dir / "last_screen.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return ""
    age = time.time() - float(data.get("ts", 0))
    if age > SCREEN_CONTEXT_MAX_AGE_S:
        return ""
    entry = (data.get("tickers") or {}).get(ticker.upper())
    if not entry:
        return ""
    bits = list(entry.get("reasons") or [])
    if entry.get("lane"):
        bits.append(f"{entry['lane']} lane")
    text = " · ".join(bits)
    if text and age > SCREEN_CONTEXT_FRESH_S:
        text += f" (as screened {_age_phrase(age)}, NOT as of now)"
    return text


def _age_phrase(seconds: float) -> str:
    if seconds < 3600:
        return f"{int(seconds // 60)} minutes ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h ago"
    return f"{seconds / 86400:.1f} days ago"


def live_move_context(settings: Settings, ticker: str) -> str:
    """Today's real intraday move for `ticker`, or `""` if it cannot be had.

    `YahooMarketSource.quotes()` already computes `last_price` vs
    `previous_close` through `_pct_change`, which IS the true intraday move.
    Its only caller was the alert poller; the SHORT prompt — the one place a
    market number is actually spoken — never fetched a quote at all and was
    filled from a cached screener string instead (B2).

    Data-only and never raises: a dead feed gives "" and the caller falls
    back to the cached line, which is worse but labelled. Mocked the same way
    the screener is, so the offline suite never reaches the network.
    """
    ticker = (ticker or "").strip().upper()
    if not ticker or settings.mocking_screener:
        return ""
    try:
        quotes = YahooMarketSource(settings).quotes([ticker])
    except Exception as e:  # noqa: BLE001 - a dead feed is not an error here
        log.warning("live quote for %s failed (%s)", ticker, e)
        return ""
    for q in quotes:
        if str(q.get("symbol", "")).upper() != ticker:
            continue
        move = q.get("regularMarketChangePercent")
        price = q.get("regularMarketPrice")
        if move is None:
            continue
        bits = [f"{float(move):+.1f}% so far today"]
        if price:
            bits.append(f"last {float(price):.2f}")
        vol = q.get("regularMarketVolume")
        avg = q.get("averageDailyVolume3Month")
        try:
            if vol and avg and float(avg):
                bits.append(f"vol {float(vol) / float(avg):.1f}x avg")
        except (TypeError, ValueError):
            pass
        return " · ".join(bits)
    return ""


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
    health = result.get("sources") or {}
    if health:
        # A short digest because the market was quiet and a short digest
        # because Yahoo returned a 403 read identically (J6). This is the
        # line that tells them apart.
        icons = {"ok": "ok", "empty": "no results", "failed": "DEGRADED"}
        lines.append("\nsources: " + " · ".join(
            f"{name} {icons.get(state, state)}"
            for name, state in sorted(health.items())))
    lines.append("Tap a ticker to open it in its own lane.")
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
    seen = _candidate_lanes(result)
    return Reply(digest_text(result),
                 keyboard=candidates_keyboard(seen) if seen else None)


def _candidate_lanes(result: dict) -> list[tuple[str, str]]:
    """`(ticker, bot lane)` for every candidate, first occurrence wins.

    The screener's own lane names are editorial ("trending", "value"); the
    bot's are formats ("short", "long"). The mapping is the editorial rule the
    screener exists to apply — a name that ran today is SHORT material, a
    beaten-down one is LONG material — so it lives here, next to the screens
    that produce it, rather than being re-derived at the button.
    """
    lane_for = {"trending": "short", "value": "long", "update": "long"}
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for screen_lane in ("trending", "value", "update"):
        for c in result.get(screen_lane, []) or []:
            if c.ticker in seen:
                continue
            seen.add(c.ticker)
            out.append((c.ticker, lane_for[screen_lane]))
    return out


def parse_cron(expr: str) -> tuple[int, int, tuple[int, ...]]:
    """'M H * * DOW' -> (minute, hour, ptb_days).

    Both numberings are Sunday-first, so the day field passes through
    unchanged apart from cron's 7-as-Sunday alias (F3).

    This used to shift every day by one — `((d % 7) - 1) % 7` — which was
    right for `python-telegram-bot` before v20, where `run_daily(days=…)`
    counted 0-6 as Monday-Sunday. **PTB 20.0 changed it to Sunday-Saturday**
    and its own docstring in the pinned 22.8 says so:

        days: ... where ``0-6`` correspond to sunday - saturday
        .. versionchanged:: 20.0
            Changed day of the week mapping of 0-6 from monday-sunday to
            sunday-saturday.

    So the default `"30 7 * * 1-5"` — the weekday morning digest — was
    scheduled for Sunday through Thursday. Friday never got a digest and
    Sunday got one nobody asked for, and it had been that way since the
    v20 upgrade.

    The old test could not catch it: it asserted the integers this function
    produced against the same assumption the function was making, and the
    author's own comment (`# Sun,Sat -> PTB Sat=5?`) recorded the doubt.
    The replacement asserts the CALENDAR DAYS the digest fires on — see
    `tests/test_screener.py`. That is X1's rule: anything crossing an
    external contract is asserted on the result, not on the request.
    """
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
        # cron's 7 is Sunday, same as its 0. Everything else is identical to
        # PTB's numbering.
        days = tuple(sorted({d % 7 for d in cron_days}))
    return minute, hour, days


# Which weekday each PTB `days=` integer means, for tests and for anything
# that has to say out loud what it scheduled. PTB 20.0+: 0 = Sunday.
PTB_WEEKDAYS = ("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday",
                "Friday", "Saturday")


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


def _digest_state(settings: Settings) -> Path:
    return settings.state_dir / "last_digest.json"


def last_digest_date(settings: Settings):
    """The date the digest last went out, or None."""
    from datetime import date as _date

    try:
        raw = json.loads(_digest_state(settings).read_text(encoding="utf-8"))
        return _date.fromisoformat(str(raw.get("date", "")))
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
        return None


def mark_digest_sent(settings: Settings, day) -> None:
    try:
        path = _digest_state(settings)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"date": day.isoformat()}), encoding="utf-8")
    except OSError as e:  # advisory — never let bookkeeping break a digest
        log.warning("could not record the digest date: %s", e)


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

    tz = ZoneInfo(settings.screen_timezone)

    async def digest_job(ctx, *, catch_up: bool = False) -> None:
        import asyncio

        from bot.keyboards import candidates_keyboard

        result = await asyncio.to_thread(run_screen, settings, "all")
        head = ("🌅 Morning screen (catch-up — the bot was down when this "
                "was due)\n\n" if catch_up else "🌅 Morning screen\n\n")
        text = head + digest_text(result)
        seen = _candidate_lanes(result)
        kb = candidates_keyboard(seen) if seen else None
        for chat_id in settings.operator_chat_ids:
            await ctx.bot.send_message(chat_id, text, reply_markup=kb)
        mark_digest_sent(settings, datetime.now(tz).date())

    application.job_queue.run_daily(
        digest_job,
        time=dtime(hour=hour, minute=minute, tzinfo=tz),
        days=days,
        name="screen_digest",
    )

    async def catch_up(ctx) -> None:
        """One late digest on boot if today's was missed (F5).

        `run_daily` fires once and nothing noticed a miss: a box asleep,
        restarting, or a bot down at 07:30 ET lost that day's digest with no
        trace — and the digest is the top of the whole funnel.

        Only for a day the schedule actually covers, only after the hour it
        was due, and only once — the sent date is persisted, so a restart
        loop does not send seven of them.
        """
        today = datetime.now(tz)
        if today.weekday() not in {(d - 1) % 7 for d in days}:
            return                       # PTB 0=Sun -> Python 0=Mon
        if (today.hour, today.minute) < (hour, minute):
            return                       # not due yet; run_daily will do it
        if last_digest_date(settings) == today.date():
            return
        log.info("digest for %s was missed — sending it now", today.date())
        await digest_job(ctx, catch_up=True)

    application.job_queue.run_once(catch_up, when=5, name="screen_digest_catchup")
    log.info("screen digest scheduled: %02d:%02d %s on %s",
             hour, minute, settings.screen_timezone,
             ", ".join(PTB_WEEKDAYS[d] for d in days))


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
