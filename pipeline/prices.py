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
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
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

    @property
    def pct_change_1d(self) -> float:
        if len(self.closes) < 2 or not self.closes[-2]:
            return 0.0
        return (self.closes[-1] - self.closes[-2]) / self.closes[-2] * 100.0

    @property
    def pct_change_period(self) -> float:
        if len(self.closes) < 2 or not self.closes[0]:
            return 0.0
        return (self.closes[-1] - self.closes[0]) / self.closes[0] * 100.0

    def to_json(self) -> str:
        return json.dumps({
            "ticker": self.ticker, "dates": self.dates, "closes": self.closes,
            "source": self.source,
        })

    @classmethod
    def from_json(cls, raw: str) -> "PriceSeries":
        d = json.loads(raw)
        return cls(ticker=d["ticker"], dates=list(d["dates"]),
                   closes=[float(c) for c in d["closes"]],
                   source=d.get("source", "yahoo"))


class PriceSource(Protocol):
    def history(self, ticker: str, days: int) -> PriceSeries: ...


def synthetic_series(ticker: str, days: int) -> PriceSeries:
    """Deterministic seeded walk — the never-fail floor (and the mock
    default). Same ticker + length ⇒ identical series, so cached renders
    stay idempotent."""
    rng = random.Random(f"prices:{ticker.upper()}:{days}")
    n = max(days * 5 // 7, 10)  # trading days
    base = 8.0 + (int(hashlib.sha256(ticker.upper().encode()).hexdigest()[:6], 16) % 900) / 10.0
    drift = rng.uniform(-0.0035, 0.0035)
    closes: list[float] = []
    price = base
    for i in range(n):
        price = max(price * (1 + drift + rng.gauss(0, 0.022)), 0.5)
        # the final day carries an "event" move so trending fixtures look
        # like trending stocks (a real pct_change_1d for the move badge)
        if i == n - 1:
            price *= 1 + rng.choice([-1, 1]) * rng.uniform(0.08, 0.30)
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
    return MockPriceSource(settings) if settings.mock_mode else YahooPriceSource(settings)


def get_price_history(ticker: str, settings: Settings,
                      source: PriceSource | None = None) -> PriceSeries:
    """TTL-cached price history (§2.4-style: unchanged inputs ⇒ zero calls).
    Never raises — worst case is the labelled synthetic series."""
    ticker = ticker.upper()
    days = settings.price_history_days
    cdir = settings.cache_dir / "prices"
    cfile = cdir / f"{ticker}_{days}.json"
    try:
        if cfile.exists() and time.time() - cfile.stat().st_mtime < settings.prices_cache_ttl_s:
            series = PriceSeries.from_json(cfile.read_text(encoding="utf-8"))
            return series
    except (json.JSONDecodeError, KeyError, ValueError):
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
