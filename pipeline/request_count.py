"""Requests a day to the two services whose limits arrive as silence.

The SEC answers a heavy day by refusing the address (and the filings, the
filing walk and the claims behind them go quiet), and Pexels allows 200 an
hour and a month's cap: either way a feature stops with nothing on screen to
say why. `/admin usage` shows the count a day, so a coming block shows first.

A count is the dispatch, as the Pexels ledger counts it: a request that came
back refused was still sent. Kept for `KEEP_DAYS` in `state/requests_by_day.json`;
a count lost to a race or an unreadable file is a smaller number, never a
failed request.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import date, timedelta
from pathlib import Path

from config import Settings

log = logging.getLogger(__name__)

FILE = "requests_by_day.json"
KEEP_DAYS = 14
SERVICES = ("sec", "pexels", "stockanalysis")
LABELS = {"sec": "SEC", "pexels": "Pexels", "stockanalysis": "stockanalysis.com"}

_lock = threading.Lock()


def _path(settings: Settings) -> Path:
    return Path(settings.state_dir) / FILE


def _load(path: Path) -> dict:
    try:
        got = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def count(settings: Settings, service: str, n: int = 1) -> None:
    """One request to `service` sent today. Never raises."""
    path = _path(settings)
    today = date.today()
    try:
        with _lock:
            data = _load(path)
            day = data.setdefault(today.isoformat(), {})
            day[service] = int(day.get(service, 0) or 0) + n
            oldest = (today - timedelta(days=KEEP_DAYS - 1)).isoformat()
            data = {d: v for d, v in data.items() if d >= oldest}
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
            os.replace(tmp, path)
    except OSError as e:
        log.warning("request count for %s not kept: %s", service, e)


def on_day(settings: Settings, day: date) -> dict[str, int]:
    """{service: requests} sent on `day`."""
    got = _load(_path(settings)).get(day.isoformat()) or {}
    return {s: int(got.get(s, 0) or 0) for s in SERVICES}


def usage_lines(settings: Settings) -> list[str]:
    """Today, yesterday and the busiest of the last week, per service."""
    today = date.today()
    week = [on_day(settings, today - timedelta(days=i)) for i in range(7)]
    lines = []
    for s in SERVICES:
        most = max(d[s] for d in week)
        lines.append(f"{LABELS[s]}: {week[0][s]:,} today, {week[1][s]:,} "
                     f"yesterday, busiest day this week {most:,}")
    return lines
