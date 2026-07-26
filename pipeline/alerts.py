"""Intraday alerting (addendum 3b).

The screener is a single pre-market digest, which suits the value lane —
beaten-down names stay beaten down. It does not suit short-form, which is
time-sensitive: a Wednesday earnings run is stale by Friday, and by the time
the next morning's digest arrives the move has been covered by everyone else.

So this watches during market hours and pushes when something happens:

* a **move** — a price change or a volume multiple past a threshold;
* an **earnings print** on a covered or watchlisted name, flagged both before
  (it reports after Wednesday's close) and after;
* a **filing** — a Form 4 or an 8-K landing on one.

Every alert arrives as a one-tap `/short TICKER`, so "it moved" to "script
running" is a single action.

Three disciplines, all of which exist because a chatty alerter gets muted and
a muted alerter is worse than none:

* **De-duplication.** One stock moving all day is one alert, not forty. A
  ticker is silenced for `alert_cooldown_minutes` once it has spoken, and a
  repeat only gets through by clearing a materially higher bar.
* **Quiet hours.** Nothing outside the configured window, and nothing at
  weekends. The operator sleeps.
* **Degrading quietly.** Same rule as the screener: unofficial sources,
  cached, rate-limited, and a source that is down produces no alert rather
  than an error. Nothing here can fail a render or block a session.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Iterable, Sequence

from config import Settings

log = logging.getLogger(__name__)

STATE_FILE = "alerts.json"
CALENDAR_FILE = "earnings_calendar.json"
WATCHLIST_FILE = "watchlist.json"

# Severity ordering, so a repeat has to actually beat the last one.
KIND_RANK = {"filing": 3, "earnings": 3, "move": 2, "volume": 1}


@dataclass
class Alert:
    ticker: str
    kind: str                  # move | volume | earnings | filing
    headline: str
    detail: str = ""
    magnitude: float = 0.0     # |pct| or the volume multiple — used for repeats
    at: str = ""

    def render(self) -> str:
        icon = {"move": "📈", "volume": "🔊", "earnings": "📊",
                "filing": "📄"}.get(self.kind, "🔔")
        body = f"{icon} {self.ticker} — {self.headline}"
        if self.detail:
            body += f"\n{self.detail}"
        return body + f"\n→ /short {self.ticker}"

    def to_json(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------
# Thresholds.
# --------------------------------------------------------------------------


def evaluate(quote: dict, settings: Settings) -> list[Alert]:
    """Turn one quote into zero or more alerts. Pure — easy to reason about.

    A quote missing the fields we need produces nothing rather than a
    fabricated alert: an unofficial feed drops fields constantly, and an
    alert built on a missing number is worse than silence.
    """
    ticker = str(quote.get("symbol") or quote.get("ticker") or "").upper()
    if not ticker:
        return []
    out: list[Alert] = []

    pct = _float(quote.get("regularMarketChangePercent"))
    if pct is not None and abs(pct) >= settings.alert_move_pct:
        direction = "up" if pct > 0 else "down"
        price = _float(quote.get("regularMarketPrice"))
        detail = f"now {price:.2f}" if price is not None else ""
        out.append(Alert(ticker=ticker, kind="move",
                         headline=f"{direction} {abs(pct):.1f}% today",
                         detail=detail, magnitude=abs(pct)))

    vol = _float(quote.get("regularMarketVolume"))
    avg = _float(quote.get("averageDailyVolume3Month")) or _float(
        quote.get("averageDailyVolume10Day"))
    if vol and avg and avg > 0:
        mult = vol / avg
        if mult >= settings.alert_volume_multiple:
            out.append(Alert(ticker=ticker, kind="volume",
                             headline=f"{mult:.1f}× normal volume",
                             detail="something is going on", magnitude=mult))
    return out


def _float(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None      # NaN is not a number we can act on


# --------------------------------------------------------------------------
# The watchlist: what gets monitored at all.
# --------------------------------------------------------------------------


class Watchlist:
    """Names worth watching intraday.

    Seeded from what the bot has already covered — those are the names it can
    say something informed about — plus anything the operator pins.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.path = settings.state_dir / WATCHLIST_FILE

    def _pinned(self) -> list[str]:
        try:
            rows = json.loads(self.path.read_text())
            return [str(t).upper() for t in rows] if isinstance(rows, list) else []
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return []

    def add(self, ticker: str) -> list[str]:
        rows = self._pinned()
        t = ticker.strip().upper()
        if t and t not in rows:
            rows.append(t)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(sorted(rows), indent=2))
        return rows

    def remove(self, ticker: str) -> bool:
        rows = self._pinned()
        t = ticker.strip().upper()
        if t not in rows:
            return False
        rows.remove(t)
        self.path.write_text(json.dumps(sorted(rows), indent=2))
        return True

    def all(self) -> list[str]:
        """Pinned names plus every ticker with a thesis on file."""
        out = set(self._pinned())
        try:
            from pipeline.standing import ThesisBook

            out.update(ThesisBook(self.settings).tickers())
        except Exception as e:  # noqa: BLE001 - never block the watch
            log.debug("watchlist could not read the thesis book: %s", e)
        return sorted(out)


# --------------------------------------------------------------------------
# De-duplication and quiet hours.
# --------------------------------------------------------------------------


class AlertLog:
    """What has already been said, so it isn't said again."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.path = settings.state_dir / STATE_FILE

    def _all(self) -> dict[str, dict]:
        try:
            data = json.loads(self.path.read_text())
            return data if isinstance(data, dict) else {}
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}

    def _save(self, rows: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(rows, indent=2, sort_keys=True))

    def should_send(self, alert: Alert, now: datetime | None = None) -> bool:
        """Is this worth interrupting for, given what we already said?

        A repeat inside the cooldown gets through only by being materially
        bigger (a stock at −4% that reaches −12% is genuinely new information)
        or more severe (a filing outranks the move that preceded it). Anything
        else is the same event restated, which is what makes people mute a bot.
        """
        now = now or datetime.now(timezone.utc)
        prev = self._all().get(alert.ticker)
        if not prev:
            return True
        try:
            when = datetime.fromisoformat(str(prev.get("at")))
        except ValueError:
            return True
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if now - when >= timedelta(minutes=self.settings.alert_cooldown_minutes):
            return True
        if KIND_RANK.get(alert.kind, 0) > KIND_RANK.get(prev.get("kind", ""), 0):
            return True
        prev_mag = float(prev.get("magnitude") or 0.0)
        return alert.magnitude >= prev_mag * self.settings.alert_escalation_factor

    def record(self, alert: Alert, now: datetime | None = None) -> None:
        rows = self._all()
        stamped = alert.to_json()
        stamped["at"] = (now or datetime.now(timezone.utc)).isoformat()
        rows[alert.ticker] = stamped
        self._save(rows)

    def clear(self) -> int:
        rows = self._all()
        self._save({})
        return len(rows)


def in_quiet_hours(settings: Settings, now: datetime | None = None) -> bool:
    """True when nothing should be pushed. Weekends included.

    The window is expressed as the hours alerts ARE allowed, so a window that
    crosses midnight is handled the same way the batch window is.
    """
    current = now or datetime.now()
    if current.weekday() >= 5 and not settings.alert_weekends:
        return True
    start = time(hour=settings.alert_start_hour % 24)
    end = time(hour=settings.alert_end_hour % 24)
    t = current.time()
    awake = (start <= t < end) if start <= end else (t >= start or t < end)
    return not awake


# --------------------------------------------------------------------------
# The earnings calendar.
# --------------------------------------------------------------------------


@dataclass
class EarningsEntry:
    ticker: str
    date: str                  # ISO day
    when: str = ""             # "bmo" | "amc" | ""
    flagged_pre: bool = False
    flagged_post: bool = False


class EarningsCalendar:
    """When covered names report, so the bot knows in advance.

    Cached on disk and refreshed at most daily: an earnings date does not
    change minute to minute, and hammering an unofficial endpoint for it is
    how you get blocked.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.path = settings.state_dir / CALENDAR_FILE

    def _all(self) -> dict[str, dict]:
        try:
            data = json.loads(self.path.read_text())
            return data.get("entries", {}) if isinstance(data, dict) else {}
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}

    def _save(self, entries: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(
            {"updated": datetime.now(timezone.utc).isoformat(),
             "entries": entries}, indent=2, sort_keys=True))

    def set(self, ticker: str, when_date: str, when: str = "") -> EarningsEntry:
        entries = self._all()
        entry = EarningsEntry(ticker=ticker.upper(), date=when_date, when=when)
        entries[entry.ticker] = asdict(entry)
        self._save(entries)
        return entry

    def get(self, ticker: str) -> EarningsEntry | None:
        row = self._all().get(ticker.upper())
        return EarningsEntry(**row) if row else None

    def upcoming(self, within_days: int = 7,
                 today: date | None = None) -> list[EarningsEntry]:
        today = today or date.today()
        out: list[EarningsEntry] = []
        for row in self._all().values():
            try:
                d = date.fromisoformat(str(row.get("date")))
            except (TypeError, ValueError):
                continue
            if 0 <= (d - today).days <= within_days:
                out.append(EarningsEntry(**row))
        return sorted(out, key=lambda e: e.date)

    def due_alerts(self, today: date | None = None) -> list[Alert]:
        """Pre- and post-print flags, each fired once.

        Two flags because they are two different videos: "reports after the
        close tonight" is a setup, "reported last night" is a reaction, and
        the second is the one that has to go out fast.
        """
        today = today or date.today()
        entries = self._all()
        out: list[Alert] = []
        changed = False
        for ticker, row in entries.items():
            try:
                d = date.fromisoformat(str(row.get("date")))
            except (TypeError, ValueError):
                continue
            delta = (d - today).days
            when = str(row.get("when") or "")
            if delta == 0 and not row.get("flagged_pre"):
                slot = {"bmo": "before the open", "amc": "after the close"}.get(
                    when, "today")
                out.append(Alert(ticker=ticker, kind="earnings",
                                 headline=f"reports {slot}",
                                 detail="worth having the angle ready",
                                 magnitude=1.0))
                row["flagged_pre"] = True
                changed = True
            elif delta < 0 and not row.get("flagged_post"):
                out.append(Alert(ticker=ticker, kind="earnings",
                                 headline="reported — the numbers are out",
                                 detail="the fast one: /headline works too",
                                 magnitude=2.0))
                row["flagged_post"] = True
                changed = True
        if changed:
            self._save(entries)
        return out


# --------------------------------------------------------------------------
# The poll.
# --------------------------------------------------------------------------


def poll_once(settings: Settings, *, quotes: Iterable[dict] | None = None,
              filings: Sequence[Alert] = (),
              now: datetime | None = None) -> list[Alert]:
    """One pass: what should be pushed right now, already de-duplicated.

    `quotes` and `filings` are injectable so the whole decision path is
    testable without a network. In production they come from the same Yahoo
    source the screener uses and from the EDGAR client.
    """
    if not settings.alerts_enabled:
        return []
    if in_quiet_hours(settings, now):
        return []

    log_ = AlertLog(settings)
    watch = set(Watchlist(settings).all())
    candidates: list[Alert] = []

    for quote in quotes or []:
        found = evaluate(quote, settings)
        for a in found:
            # A move on a name we have never covered is the screener's job,
            # not an interruption — unless it is enormous.
            if a.ticker not in watch and a.magnitude < settings.alert_unwatched_pct:
                continue
            candidates.append(a)

    candidates += [a for a in filings if a.ticker in watch]
    candidates += EarningsCalendar(settings).due_alerts(
        (now or datetime.now(timezone.utc)).date())

    # Highest-severity, then biggest, so a ticker's single allowed alert is
    # its most important one rather than whichever was evaluated first.
    candidates.sort(key=lambda a: (-KIND_RANK.get(a.kind, 0), -a.magnitude))

    out: list[Alert] = []
    spoken: set[str] = set()
    for a in candidates:
        if a.ticker in spoken:
            continue
        if not log_.should_send(a, now):
            continue
        log_.record(a, now)
        spoken.add(a.ticker)
        out.append(a)
        if len(out) >= settings.alert_max_per_poll:
            break
    if out:
        log.info("alerts: pushing %d of %d candidate(s)", len(out), len(candidates))
    return out


def fetch_filings(settings: Settings, tickers: Sequence[str]) -> list[Alert]:
    """Form 4s and 8-Ks landing on watched names (P3.4 feeding 3b).

    Cached and rate-limited by `sources`, and silent on anything unavailable —
    a filing feed that is down produces no alerts, not an error. Only the
    filing DATE is compared, so a name that filed today alerts once and the
    AlertLog handles the rest.
    """
    if not tickers:
        return []
    out: list[Alert] = []
    today = datetime.now(timezone.utc).date().isoformat()
    try:
        from pipeline.sources import insider_transactions, latest_8k
    except ImportError:  # pragma: no cover
        return []
    for ticker in tickers:
        try:
            eightk = latest_8k(ticker, settings)
            if eightk.get("status") == "ok" and eightk.get("filed") == today:
                tail = " with a press release" if eightk.get("exhibit_url") else ""
                out.append(Alert(ticker=ticker, kind="filing",
                                 headline=f"filed an 8-K{tail}",
                                 detail="something they had to disclose",
                                 magnitude=2.0))
            form4 = insider_transactions(ticker, settings)
            if form4.get("status") == "ok":
                fresh = [f for f in form4.get("filings", [])
                         if f.get("filed") == today]
                if fresh:
                    out.append(Alert(
                        ticker=ticker, kind="filing",
                        headline=f"{len(fresh)} insider transaction(s) filed today",
                        detail="Form 4 — worth reading which way",
                        magnitude=1.5))
        except Exception as e:  # noqa: BLE001 - one bad ticker, not the pass
            log.debug("filing watch for %s failed: %s", ticker, e)
    return out


def fetch_quotes(settings: Settings, tickers: Sequence[str]) -> list[dict]:
    """Quotes for the watchlist. Degrades to [] — never raises.

    MOCK_MODE reads the screener's fixture, so the alerting path is exercised
    offline like everything else.
    """
    if not tickers:
        return []
    if settings.mock_mode:
        try:
            raw = json.loads(
                (settings.fixtures_dir / "screener" / "yahoo_trending.json").read_text())
            wanted = {t.upper() for t in tickers}
            return [q for q in raw.get("quotes", [])
                    if str(q.get("symbol", "")).upper() in wanted]
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return []
    try:
        from pipeline.screener import YahooMarketSource

        return YahooMarketSource(settings).quotes(list(tickers))
    except Exception as e:  # noqa: BLE001 - a dead feed is not an error here
        log.warning("alert quote fetch failed (%s) — no alerts this pass", e)
        return []


def digest(alerts: Sequence[Alert]) -> str:
    if not alerts:
        return ""
    return "\n\n".join(a.render() for a in alerts)
