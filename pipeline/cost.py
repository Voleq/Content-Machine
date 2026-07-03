"""Cost estimation + the monthly spend guard (§8).

The ledger is the single source of truth for month-to-date paid usage.
Every module that spends (TTS, Pexels) records here and must check
`guard_tts_spend` / `check_pexels_budget` BEFORE the paid call — the
approval flow in the bot is the human gate, this is the code gate.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from config import Settings


class SpendCapExceededError(Exception):
    """A paid action would exceed MONTHLY_SPEND_CAP — blocked (§8.4)."""


class BudgetExceededError(Exception):
    """A script exceeds its per-format character budget — no spend allowed."""


def month_key(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return now.strftime("%Y-%m")


def estimate_tts_usd(chars: int, settings: Settings) -> float:
    return round(chars / 1000.0 * settings.usd_per_1k_chars, 4)


class SpendLedger:
    """Month-keyed spend/usage counters persisted to state/spend.json."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.path: Path = settings.state_dir / "spend.json"
        self._lock = threading.Lock()

    # ------------------------------------------------------------- internals
    def _load(self) -> dict:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text())
            except json.JSONDecodeError:
                return {}
        return {}

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(self.path)

    def _month(self, data: dict) -> dict:
        return data.setdefault(month_key(), {"tts_usd": 0.0, "pexels_calls": 0})

    # ------------------------------------------------------------------ read
    def mtd_spend_usd(self) -> float:
        with self._lock:
            return float(self._load().get(month_key(), {}).get("tts_usd", 0.0))

    def pexels_calls_this_month(self) -> int:
        with self._lock:
            return int(self._load().get(month_key(), {}).get("pexels_calls", 0))

    def would_exceed(self, additional_usd: float) -> bool:
        return self.mtd_spend_usd() + additional_usd > self.settings.monthly_spend_cap_usd

    # ----------------------------------------------------------------- gates
    def guard_tts_spend(self, chars: int) -> float:
        """Raise if the estimated TTS cost would blow the monthly cap.

        Returns the estimate so callers can record it after success.
        """
        est = estimate_tts_usd(chars, self.settings)
        if self.would_exceed(est):
            raise SpendCapExceededError(
                f"TTS for {chars} chars (~${est:.2f}) would exceed the monthly "
                f"cap: ${self.mtd_spend_usd():.2f} spent of "
                f"${self.settings.monthly_spend_cap_usd:.2f}."
            )
        return est

    def check_pexels_budget(self) -> None:
        if self.pexels_calls_this_month() >= self.settings.pexels_monthly_call_cap:
            raise SpendCapExceededError(
                f"Pexels monthly call cap reached "
                f"({self.settings.pexels_monthly_call_cap}). Using fallbacks."
            )

    # ---------------------------------------------------------------- record
    def record_tts(self, usd: float) -> None:
        with self._lock:
            data = self._load()
            self._month(data)["tts_usd"] = round(self._month(data)["tts_usd"] + usd, 4)
            self._save(data)

    def record_pexels_call(self) -> None:
        with self._lock:
            data = self._load()
            self._month(data)["pexels_calls"] += 1
            self._save(data)
