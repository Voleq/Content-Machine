"""Price-history source for the branded chart (§4 SHORT hero visual).

The pipeline renders its own chart from its own price data — never a
TradingView screenshot. The data comes from the same unofficial Yahoo
feed the screener uses, so the rules are the same: wrapped behind an
interface, cached with a TTL, data-only (never spends), and allowed to
fail into a deterministic synthetic series so a dead feed can never
abort a render.

MOCK_MODE serves fixtures/prices/<TICKER>.json when present, otherwise a
seeded synthetic walk — zero network either way.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import random
import time
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Protocol

from config import Settings

log = logging.getLogger(__name__)


@dataclass
class PriceSeries:
    ticker: str
    dates: list[str]          # ISO dates, oldest -> newest
    closes: list[float]       # same length as dates
    source: str = "yahoo"     # yahoo | fixture | synthetic | cache
    degraded: bool = False    # True when the live feed failed and we synthesized

    @property
    def last(self) -> float:
        return self.closes[-1]

    def to_json(self) -> str:
        # `degraded` travels with the series (B1). It used to be dropped
        # here, so the flag survived exactly as long as the object did and
        # was destroyed the moment the series was written to cache — which
        # is the first thing that happens to it. A fabricated chart then
        # read back from that cache as an ordinary one.
        return json.dumps({
            "ticker": self.ticker, "dates": self.dates, "closes": self.closes,
            "source": self.source, "degraded": self.degraded,
        })

    @classmethod
    def from_json(cls, raw: str) -> "PriceSeries":
        d = json.loads(raw)
        # An older cache file has no `degraded` key. Treating its absence as
        # False is right: the flag was never written, so the only series that
        # can be in such a file are ones nothing ever marked.
        return cls(ticker=d["ticker"], dates=list(d["dates"]),
                   closes=[float(c) for c in d["closes"]],
                   source=d.get("source", "yahoo"),
                   degraded=bool(d.get("degraded", False)))


class PriceSource(Protocol):
    def history(self, ticker: str, days: int) -> PriceSeries: ...


def synthetic_series(ticker: str, days: int) -> PriceSeries:
    """Deterministic seeded walk — the never-fail floor (and the mock
    default). Same ticker + length ⇒ identical series, so cached renders
    stay idempotent.

    There is no "event move" on the final bar any more (B1). This series
    exists so a dead price feed cannot abort a render; a floor that lets
    the render complete is defensible, and one engineered to look like a
    real trending stock is the opposite of a floor. The old final bar was
    multiplied by 8–30% in a random direction, which is precisely the
    shape a viewer reads as news — an invented spike, indistinguishable
    from a real one, on a channel whose premise is real numbers.

    What replaces it is nothing: an ordinary walk that looks like an
    ordinary walk. `degraded` is how a caller learns this is not real, and
    since B1 that flag survives the cache and blocks a final render.
    """
    rng = random.Random(f"prices:{ticker.upper()}:{days}")
    n = max(days * 5 // 7, 10)  # trading days
    base = 8.0 + (int(hashlib.sha256(ticker.upper().encode()).hexdigest()[:6], 16) % 900) / 10.0
    drift = rng.uniform(-0.0035, 0.0035)
    closes: list[float] = []
    price = base
    for _ in range(n):
        price = max(price * (1 + drift + rng.gauss(0, 0.022)), 0.5)
        closes.append(round(price, 2))
    start = date.today() - timedelta(days=days)
    dates, d = [], start
    while len(dates) < n:
        if d.weekday() < 5:
            dates.append(d.isoformat())
        d += timedelta(days=1)
    return PriceSeries(ticker=ticker.upper(), dates=dates, closes=closes,
                       source="synthetic")


class MockPriceSource:
    """Fixture-backed (fixtures/prices/<TICKER>.json) or seeded synthetic."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def history(self, ticker: str, days: int) -> PriceSeries:
        fixture = self.settings.fixtures_dir / "prices" / f"{ticker.upper()}.json"
        if fixture.exists():
            series = PriceSeries.from_json(fixture.read_text(encoding="utf-8"))
            series.source = "fixture"
            return series
        return synthetic_series(ticker, days)


class YahooPriceSource:
    """yfinance daily history, wrapped so any failure degrades to the
    synthetic floor with a warning (chart renders regardless)."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def history(self, ticker: str, days: int) -> PriceSeries:
        try:
            import yfinance as yf

            hist = yf.Ticker(ticker).history(
                period=f"{max(days, 5)}d", interval="1d", auto_adjust=True,
            )
            closes = [round(float(c), 4) for c in hist["Close"].tolist()]
            dates = [d.date().isoformat() if hasattr(d, "date") else str(d)[:10]
                     for d in hist.index.tolist()]
            if len(closes) >= 2:
                return PriceSeries(ticker=ticker.upper(), dates=dates,
                                   closes=closes, source="yahoo")
            log.warning("yahoo history for %s came back empty — synthetic", ticker)
        except Exception as e:
            log.warning("yahoo history for %s failed (%s) — synthetic", ticker, e)
        series = synthetic_series(ticker, days)
        series.degraded = True
        return series


def make_price_source(settings: Settings) -> PriceSource:
    return MockPriceSource(settings) if settings.mocking_prices else YahooPriceSource(settings)


# How long a SYNTHETIC series is served from the cache. Long enough for one
# job to read the same series twice (the gate, then the chart); short enough
# that "retry once the feed is back" fetches again instead of meeting the
# same random walk for the rest of the hour.
DEGRADED_TTL_S = 300


def get_price_history(ticker: str, settings: Settings,
                      source: PriceSource | None = None) -> PriceSeries:
    """TTL-cached price history (§2.4-style: unchanged inputs ⇒ zero calls).
    Never raises — worst case is the labelled synthetic series."""
    ticker = ticker.upper()
    days = settings.price_history_days
    cdir = settings.cache_dir / "prices"
    cfile = cdir / f"{ticker}_{days}.json"
    try:
        age = time.time() - cfile.stat().st_mtime if cfile.exists() else None
        if age is not None and age < settings.prices_cache_ttl_s:
            series = PriceSeries.from_json(cfile.read_text(encoding="utf-8"))
            if not series.degraded or age < DEGRADED_TTL_S:
                return series
    except (json.JSONDecodeError, KeyError, ValueError, OSError):
        pass

    src = source or make_price_source(settings)
    try:
        series = src.history(ticker, days)
    except Exception as e:  # belt and braces — a chart must never abort a render
        log.warning("price source blew up for %s (%s) — synthetic", ticker, e)
        series = synthetic_series(ticker, days)
        series.degraded = True

    if not math.isfinite(sum(series.closes)) or len(series.closes) < 2:
        series = synthetic_series(ticker, days)
        series.degraded = True

    cdir.mkdir(parents=True, exist_ok=True)
    cfile.write_text(series.to_json(), encoding="utf-8")
    return series


# ---------------------------------------------------------------------------
# One session (item 4)
# ---------------------------------------------------------------------------

@dataclass
class IntradaySession:
    """One trading session, as the exchange printed it.

    `times` are the exchange's own clock ("09:30"), `prices` the last trade
    in each bar, `prior_close` the close the session is read against. There
    is NO synthetic session: a day that never happened, drawn on the beat
    about what happened today, is invented news, so a session that cannot be
    read is None and the beat keeps its other drawings.
    """

    ticker: str
    day: str                  # ISO date of the session
    times: list[str]
    prices: list[float]
    prior_close: float
    source: str = "yahoo"     # yahoo | fixture
    complete: bool = True     # False while the session is still trading

    def to_json(self) -> str:
        return json.dumps(self.__dict__)

    @classmethod
    def from_json(cls, raw: str) -> "IntradaySession":
        d = json.loads(raw)
        return cls(ticker=d["ticker"], day=d["day"], times=list(d["times"]),
                   prices=[float(x) for x in d["prices"]],
                   prior_close=float(d["prior_close"]),
                   source=d.get("source", "yahoo"),
                   complete=bool(d.get("complete", True)))

    @property
    def move(self) -> float:
        """The session's move from the prior close, as a fraction."""
        return self.prices[-1] / self.prior_close - 1.0


# A session older than this is not "today" for a short about today's move.
INTRADAY_MAX_AGE_DAYS = 4
# A short is cut while the story is live, so the cache is short too.
INTRADAY_TTL_S = 900


def _yahoo_session(ticker: str) -> IntradaySession | None:
    import yfinance as yf

    t = yf.Ticker(ticker)
    bars = t.history(period="1d", interval="5m", auto_adjust=False,
                     prepost=False)
    days = t.history(period="5d", interval="1d", auto_adjust=False)
    if bars is None or bars.empty or days is None or len(days) < 2:
        return None
    day = bars.index[-1].date()
    session = bars[[ix.date() == day for ix in bars.index]]
    closes = [float(c) for c in session["Close"].tolist()]
    times = [ix.strftime("%H:%M") for ix in session.index]
    # The prior close is the last DAILY close before this session's day: the
    # daily table carries today's partial bar too, so it is skipped by date.
    prior = [float(c) for ix, c in zip(days.index, days["Close"].tolist())
             if ix.date() < day]
    if len(closes) < 8 or not prior:
        return None
    return IntradaySession(ticker=ticker.upper(), day=day.isoformat(),
                           times=times, prices=[round(c, 4) for c in closes],
                           prior_close=round(prior[-1], 4), source="yahoo",
                           complete=times[-1] >= "15:55")


def get_intraday(ticker: str, settings: Settings) -> IntradaySession | None:
    """Today's session for `ticker`, or None. Never raises, never invents.

    MOCK_MODE reads fixtures/prices/<TICKER>_intraday.json and nothing else:
    with no fixture there is no session, where the daily history would fall
    back to a synthetic walk.
    """
    ticker = (ticker or "").upper()
    if not ticker:
        return None
    if settings.mocking_prices:
        fixture = settings.fixtures_dir / "prices" / f"{ticker}_intraday.json"
        if not fixture.exists():
            return None
        try:
            got = IntradaySession.from_json(fixture.read_text(encoding="utf-8"))
        except (ValueError, KeyError, OSError) as e:
            log.warning("intraday fixture for %s unreadable: %s", ticker, e)
            return None
        got.source = "fixture"
        return got

    cfile = settings.cache_dir / "prices" / f"{ticker}_intraday.json"
    try:
        if cfile.exists() and time.time() - cfile.stat().st_mtime < INTRADAY_TTL_S:
            return IntradaySession.from_json(cfile.read_text(encoding="utf-8"))
    except (ValueError, KeyError, OSError):
        pass
    try:
        got = _yahoo_session(ticker)
    except Exception as e:                                # noqa: BLE001
        log.warning("intraday for %s failed (%s); no session chart", ticker, e)
        return None
    if got is None:
        return None
    age = (date.today() - date.fromisoformat(got.day)).days
    if age > INTRADAY_MAX_AGE_DAYS:
        log.info("intraday for %s is %s days old; no session chart", ticker, age)
        return None
    cfile.parent.mkdir(parents=True, exist_ok=True)
    cfile.write_text(got.to_json(), encoding="utf-8")
    return got

