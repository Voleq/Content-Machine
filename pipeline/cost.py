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

    def llm_usd_this_month(self) -> float:
        with self._lock:
            return float(self._load().get(month_key(), {}).get("llm_usd", 0.0))

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

    def record_llm(self, usd: float) -> None:
        """Filing-flagger LLM spend. Cheap (often free-tier $0) but tracked for
        visibility. Kept separate from the TTS cap bucket."""
        with self._lock:
            data = self._load()
            month = self._month(data)
            month["llm_usd"] = round(month.get("llm_usd", 0.0) + float(usd), 4)
            self._save(data)


# ---------------------------------------------------------------------------
# The §9.3 validation + cost report (the artifact behind the Approve button).
# ---------------------------------------------------------------------------

# empirical render-speed factors on a cheap VPS (minutes of render per
# minute of output at final quality, libx264 veryfast)
_RENDER_FACTOR = {"short": 0.9, "long": 0.8}
_RENDER_BASE_MIN = {"short": 0.3, "long": 0.5}


def estimate_render_minutes(fmt: str, words: int, wps: float) -> float:
    duration_min = words / wps / 60.0
    return round(duration_min * _RENDER_FACTOR[fmt] + _RENDER_BASE_MIN[fmt], 1)


def estimate_runtime_minutes(words: int, wps: float) -> float:
    """Estimated finished VIDEO length (minutes) at deadpan pace. LONG length
    is complexity-driven, so this rides on the actual word count — a 40-min
    cut is ~2.5x the TTS spend of a 15-min one, and the report shows both."""
    return round(words / wps / 60.0, 1)


def build_short_report(script, parse_warnings, settings, ledger, tts_engine) -> "CostReport":
    from pipeline.models import AnnotationTarget, CostReport  # avoid a cycle

    cached = tts_engine.is_cached(script.audio_script, "short",
                                  events=script.inline_events)
    est = 0.0 if cached else estimate_tts_usd(script.char_count, settings)
    missing = set(script.missing_anchor_words())
    notes = []
    for a in script.annotations:
        mark = "⚠ fallback position" if a.anchor_word in missing else "✓ (anchor found)"
        where = ("chart" if a.target is AnnotationTarget.CHART
                 else f"numbers row {a.row_index if a.row_index is not None else 0}")
        notes.append(f'Scribble -> {where} "{a.anchor_word}" {mark}')
    blocking: list[str] = []
    if not cached and ledger.would_exceed(est):
        blocking.append(
            f"TTS (~${est:.2f}) would exceed the monthly cap "
            f"(${ledger.mtd_spend_usd():.2f}/${settings.monthly_spend_cap_usd:.2f})"
        )
    return CostReport(
        ticker=script.ticker,
        fmt="short",
        words=script.word_count,
        chars=script.char_count,
        tts_cached=cached,
        est_tts_usd=est,
        headline_count=len(script.headlines),
        numbers_rows=len(script.numbers),
        numbers_years=max(len(r.values) for r in script.numbers),
        annotation_note="\n".join(notes),
        meme_count=1 if script.meme else 0,
        meme_cap=settings.meme_max_per_long,
        est_runtime_min=estimate_runtime_minutes(script.word_count, settings.mock_wps_short),
        delivery_directives=_count_directives(script),
        est_render_minutes=estimate_render_minutes("short", script.word_count, settings.mock_wps_short),
        mtd_spend_usd=ledger.mtd_spend_usd(),
        monthly_cap_usd=settings.monthly_spend_cap_usd,
        warnings=list(parse_warnings),
        blocking=blocking,
        script_sha=script.content_sha(),
    )


def _count_directives(script) -> int:
    from pipeline.models import DELIVERY_TAG_TYPES

    events = getattr(script, "events", None) or getattr(script, "inline_events", [])
    return sum(1 for e in events if e.type in DELIVERY_TAG_TYPES)


def build_long_report(
    script, parse_warnings, validation_warnings, validation_blocking,
    settings, ledger, tts_engine, visual_plan, filing_count,
) -> "CostReport":
    from pipeline.models import CostReport, VisualPlanItem

    cached = tts_engine.is_cached(script.narration, "long", events=script.events)
    est = 0.0 if cached else estimate_tts_usd(script.char_count, settings)
    blocking = list(validation_blocking)
    if not cached and ledger.would_exceed(est):
        blocking.append(
            f"TTS (~${est:.2f}) would exceed the monthly cap "
            f"(${ledger.mtd_spend_usd():.2f}/${settings.monthly_spend_cap_usd:.2f})"
        )
    return CostReport(
        ticker=script.ticker,
        fmt="long",
        words=script.word_count,
        chars=script.char_count,
        tts_cached=cached,
        est_tts_usd=est,
        visuals=[
            VisualPlanItem(key=v.key, kind=v.kind, source=v.source,
                           path=str(v.path), attribution=v.attribution)
            for v in visual_plan
        ],
        filing_overlays=filing_count,
        meme_count=script.meme_count(),
        meme_cap=settings.meme_max_per_long,
        est_runtime_min=estimate_runtime_minutes(script.word_count, settings.mock_wps_long),
        delivery_directives=_count_directives(script),
        est_render_minutes=estimate_render_minutes("long", script.word_count, settings.mock_wps_long),
        mtd_spend_usd=ledger.mtd_spend_usd(),
        monthly_cap_usd=settings.monthly_spend_cap_usd,
        warnings=list(parse_warnings) + list(validation_warnings),
        blocking=blocking,
        script_sha=script.content_sha(),
    )
