"""Cost estimation + the monthly spend guard (§8).

The ledger is the single source of truth for month-to-date paid usage.
Every module that spends (TTS, Pexels) records here and must check
`guard_tts_spend` / `check_pexels_budget` BEFORE the paid call — the
approval flow in the bot is the human gate, this is the code gate.
"""

from __future__ import annotations

import json
import threading
import uuid
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
    """What `chars` characters will cost at the SELECTED model's rate.

    Not at a fixed rate: this used to bill everything at a hardcoded $0.15/1k
    that matched neither model the code could pick, so the ledger below stopped
    a $50 cap at roughly $16.67 of real spend and every report read 3x high.
    An estimate the cap is enforced with has to track the model actually being
    called.
    """
    return round(chars / 1000.0 * settings.tts_usd_per_1k_chars, 4)


class SpendLedger:
    """Month-keyed spend/usage counters persisted to state/spend.json."""

    # ONE LOCK FOR EVERY LEDGER IN THE PROCESS. It used to be per-instance,
    # which protects nothing that matters: `BotCore` builds a ledger and
    # hands it to `TTSEngine` and `ContentManager`, and any script that
    # builds its own gets a second lock guarding the same file. A
    # read-modify-write on one file needs one lock.
    _LOCK = threading.RLock()

    def __init__(self, settings: Settings):
        self.settings = settings
        self.path: Path = settings.state_dir / "spend.json"
        self._lock = SpendLedger._LOCK

    # ------------------------------------------------------------- internals
    def _load(self) -> dict:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return {}
        return {}

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def _month(self, data: dict) -> dict:
        return data.setdefault(month_key(), {"tts_usd": 0.0, "pexels_calls": 0})

    # ----------------------------------------------------------- reservations
    #
    # The cap used to be check-then-act: `guard_tts_spend` read the
    # month-to-date, released the lock, and the generation it authorised
    # recorded its spend minutes later. Two jobs could both read $40 of a $50
    # cap and both proceed, and the ledger is the only hard stop in the
    # system. The queue is one worker today, so nothing concurrent reached
    # it — which is exactly the kind of thing that stops being true quietly.
    #
    # So a guard RESERVES what it is about to spend, under the same lock that
    # writes, and the reservation counts against the cap until the generation
    # that owns it finishes and releases it. `record_tts` is unchanged: real
    # spend still lands per chunk, as it is billed.
    #
    # A reservation whose process died would otherwise eat cap headroom until
    # the month rolled over, so each one carries the time it was taken and
    # anything older than `_RESERVATION_TTL_S` is swept on the next read. No
    # paid generation runs for an hour; one that appears to have been is a
    # crash, not a job.
    _RESERVATION_TTL_S = 3600.0

    def _live_reservations(self, data: dict) -> list[dict]:
        """This month's reservations, with the abandoned ones dropped."""
        month = self._month(data)
        now = datetime.now(timezone.utc).timestamp()
        live = [r for r in month.get("reservations", [])
                if isinstance(r, dict)
                and now - float(r.get("at", 0) or 0) < self._RESERVATION_TTL_S]
        if len(live) != len(month.get("reservations", [])):
            month["reservations"] = live
        return live

    def reserved_usd(self) -> float:
        """What is spoken for but not yet billed."""
        with self._lock:
            return round(sum(float(r.get("usd", 0.0) or 0.0)
                             for r in self._live_reservations(self._load())), 4)

    def release_reservation(self, token: str) -> None:
        """Give back what a finished (or failed) generation did not spend."""
        if not token:
            return
        with self._lock:
            data = self._load()
            month = self._month(data)
            live = self._live_reservations(data)
            month["reservations"] = [r for r in live if r.get("token") != token]
            self._save(data)

    # ------------------------------------------------------------------ read
    def mtd_spend_usd(self) -> float:
        with self._lock:
            return float(self._load().get(month_key(), {}).get("tts_usd", 0.0))

    def pexels_calls_this_month(self) -> int:
        with self._lock:
            return int(self._load().get(month_key(), {}).get("pexels_calls", 0))

    # ---------------------------------------------------------- reconciled
    #
    # NOTHING RECONCILES THIS LEDGER AGAINST THE PROVIDER (P7). Every figure
    # in it is what Dennis BELIEVES it spent: chunks counted at the rate in
    # config, against a cap enforced from the same number. A drift — a rate
    # change, a retried chunk billed twice, a model switch — is invisible
    # from inside, and the first symptom is a bill.
    #
    # Not automated: reading the ElevenLabs dashboard is a human act, and a
    # scraper against a billing page is a worse idea than a date. What this
    # does is the same trick as the provenance record — the failure mode is
    # nobody looking, so the number that matters carries its own age.
    RECONCILED_KEY = "reconciled_on"

    def reconciled_on(self) -> str:
        """ISO date the operator last checked this against the provider."""
        with self._lock:
            return str(self._load().get(self.RECONCILED_KEY) or "")

    def mark_reconciled(self, today: "date | None" = None) -> str:
        """Stamp today. Returns the date written."""
        from datetime import date as _date

        stamp = (today or _date.today()).isoformat()
        with self._lock:
            data = self._load()
            data[self.RECONCILED_KEY] = stamp
            self._save(data)
        return stamp

    def reconciled_line(self, today: "date | None" = None) -> str:
        """One line for `/cost` saying how old the check is."""
        from datetime import date as _date

        stamp = self.reconciled_on()
        now = today or _date.today()
        if not stamp:
            return ("Reconciled: NEVER — nothing has ever checked this "
                    "against the provider's own number. `/cost reconciled` "
                    "after you have.")
        try:
            when = _date.fromisoformat(stamp)
        except ValueError:
            return f"Reconciled: {stamp} (unreadable date)"
        days = (now - when).days
        if days <= 0:
            return f"Reconciled: today ({stamp})"
        ago = f"{days} day{'s' if days != 1 else ''} ago"
        flag = "  ⚠️ stale" if days > 31 else ""
        return f"Reconciled: {stamp} — {ago}{flag}"

    def llm_usd_this_month(self) -> float:
        with self._lock:
            return float(self._load().get(month_key(), {}).get("llm_usd", 0.0))

    def would_exceed(self, additional_usd: float) -> bool:
        """Would this spend breach the cap, counting what is already claimed?

        Reservations count. A job that has been authorised and is mid-
        generation has not been billed yet, and treating its money as
        available is how two jobs pass one cap.
        """
        with self._lock:
            committed = self.mtd_spend_usd() + self.reserved_usd()
        return committed + additional_usd > self.settings.monthly_spend_cap_usd

    # ----------------------------------------------------------------- gates
    def guard_tts_spend(self, chars: int) -> float:
        """Raise if the estimated TTS cost would blow the monthly cap.

        Returns the estimate so callers can record it after success. Prefer
        `reserve_tts_spend`, which holds the headroom it just checked;
        this stays for callers that only want the question answered.
        """
        est, token = self.reserve_tts_spend(chars)
        self.release_reservation(token)
        return est

    def reserve_tts_spend(self, chars: int) -> tuple[float, str]:
        """Check the cap and CLAIM the headroom. Returns `(estimate, token)`.

        The claim and the check happen under one lock, so the answer cannot
        go stale between them. The caller releases the token when the
        generation is over, whether it spent or raised.
        """
        est = estimate_tts_usd(chars, self.settings)
        with self._lock:
            data = self._load()
            month = self._month(data)
            live = self._live_reservations(data)
            claimed = sum(float(r.get("usd", 0.0) or 0.0) for r in live)
            spent = float(month.get("tts_usd", 0.0) or 0.0)
            cap = self.settings.monthly_spend_cap_usd
            if spent + claimed + est > cap:
                raise SpendCapExceededError(
                    f"TTS for {chars} chars (~${est:.2f}) would exceed the "
                    f"monthly cap: ${spent:.2f} spent"
                    + (f" and ${claimed:.2f} claimed by a job already running"
                       if claimed else "")
                    + f", of ${cap:.2f}."
                )
            token = uuid.uuid4().hex[:12]
            month["reservations"] = live + [
                {"token": token, "usd": est,
                 "at": datetime.now(timezone.utc).timestamp()}]
            self._save(data)
        return est, token

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


def build_short_report(script, parse_warnings, settings, ledger, tts_engine,
                       *, gate_report=None) -> "CostReport":
    from pipeline.gates import check_audio
    from pipeline.models import AnnotationTarget, CostReport  # avoid a cycle
    from pipeline.reach import script_reach

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
    warnings = list(parse_warnings)
    if not cached and ledger.would_exceed(est):
        blocking.append(
            f"TTS (~${est:.2f}) would exceed the monthly cap "
            f"(${ledger.mtd_spend_usd():.2f}/${settings.monthly_spend_cap_usd:.2f})"
        )
    # The SHORT lane runs the gate battery now (B3). `_intake_short` builds
    # the report and folds the findings in here, exactly as the LONG does —
    # the daily-volume format used to have nothing between a fabricated
    # figure and an upload.
    #
    # `check_audio` is still called directly when no battery was handed in,
    # so the report keeps working for callers that have no CompanyData to
    # gate against (the sample renderer, and the tests that predate this).
    if gate_report is not None:
        for f in gate_report.findings:
            (blocking if f.severity == "block" else warnings).append(f.render())
    else:
        for f in check_audio(settings):
            (blocking if f.severity == "block" else warnings).append(f.message)
    return CostReport(
        mock_subsystems=settings.active_mocks(),
        ticker=script.ticker,
        fmt="short",
        words=script.word_count,
        chars=script.char_count,
        tts_cached=cached,
        est_tts_usd=est,
        headline_count=len(script.headlines),
        chart_style=script.chart_style.value,
        numbers_rows=len(script.numbers),
        numbers_years=max(len(r.values) for r in script.numbers),
        annotation_note="\n".join(notes),
        meme_count=1 if script.meme else 0,
        meme_cap=settings.meme_max_per_long,
        gif_cap=settings.gif_max_per_video,
        est_runtime_min=estimate_runtime_minutes(script.word_count, settings.mock_wps_short),
        delivery_directives=_count_directives(script),
        est_render_minutes=estimate_render_minutes("short", script.word_count, settings.mock_wps_short),
        mtd_spend_usd=ledger.mtd_spend_usd(),
        monthly_cap_usd=settings.monthly_spend_cap_usd,
        kit_reach=script_reach(script, settings).line(),
        warnings=warnings,
        blocking=blocking,
        script_sha=script.content_sha(),
    )


def _count_directives(script) -> int:
    from pipeline.models import DELIVERY_TAG_TYPES

    events = getattr(script, "events", None) or getattr(script, "inline_events", [])
    return sum(1 for e in events if e.type in DELIVERY_TAG_TYPES)


# What a filler card is standing in FOR, phrased for whoever has to fix it.
# The generic card is drawn identically whatever the tag asked for, so a
# report that only counted fillers said "filler 3" and left the operator to
# guess which three beats went missing.
_FILLER_MEANS = {
    "clip": ("the illustration did not resolve — the owned library, Pexels, "
             "Giphy and Tenor all missed, so this beat draws a blank card "
             "instead of the thing the line is pointing at"),
    "img": "no imagery resolved — this beat draws a blank card",
    "meme": "no meme resolved — this beat draws a blank card",
}


def gif_ceiling_warnings(visual_plan, settings) -> list[str]:
    """One warning when a video leans on the GIF providers past its ceiling.

    Same shape as the meme cap, for the same reason and a sharper one: memes
    come from the OWNED library and were already capped at one or two, while
    Giphy and Tenor content is user-uploaded, frequently copyrighted, and
    fires exactly when a clip is specific enough that stock footage misses
    (H3). It had no counter, no report line and no ceiling at all.

    A warning rather than a block: the alternative to a GIF here is a filler
    card, so refusing the render trades a legal question for a dead beat,
    and the operator is the one who gets to make that trade.
    """
    from pipeline.models import _GIF_SOURCES

    gifs = [v for v in visual_plan
            if getattr(v, "source", "") in _GIF_SOURCES]
    cap = settings.gif_max_per_video
    if len(gifs) <= cap:
        return []
    keys = ", ".join(sorted({v.key for v in gifs})[:6])
    return [
        f"{len(gifs)} visuals came from Giphy/Tenor, over the cap of {cap} "
        f"({keys}). That content is user-uploaded and frequently "
        f"copyrighted, and this chain only fires when the owned library and "
        f"Pexels both missed — so the fix is an owned clip or a palette key, "
        f"not a bigger cap."
    ]


def unresolved_visual_warnings(visual_plan) -> list[str]:
    """One warning per visual that came back as a filler card.

    A `[CLIP]` was written because the point NEEDED SHOWING, and a silent
    miss is the failure mode that costs the most: the render succeeds, the
    card is drawn, the beat is dead, and the only trace is a log line nobody
    reads. The approval report is the last screen before the money, so it is
    where this belongs.
    """
    out: list[str] = []
    for v in visual_plan:
        if getattr(v, "source", "") != "filler":
            continue
        why = _FILLER_MEANS.get(getattr(v, "kind", ""),
                                "did not resolve — this beat draws a blank card")
        out.append(f"[{str(getattr(v, 'kind', '')).upper()}: {v.key}] {why}")
    return out


def build_long_report(
    script, parse_warnings, validation_warnings, validation_blocking,
    settings, ledger, tts_engine, visual_plan, filing_count,
) -> "CostReport":
    from pipeline.models import CostReport, VisualPlanItem
    from pipeline.reach import script_reach

    cached = tts_engine.is_cached(script.narration, "long", events=script.events)
    est = 0.0 if cached else estimate_tts_usd(script.char_count, settings)
    blocking = list(validation_blocking)
    if not cached and ledger.would_exceed(est):
        blocking.append(
            f"TTS (~${est:.2f}) would exceed the monthly cap "
            f"(${ledger.mtd_spend_usd():.2f}/${settings.monthly_spend_cap_usd:.2f})"
        )
    warnings = list(parse_warnings) + list(validation_warnings)
    warnings += unresolved_visual_warnings(visual_plan)
    warnings += gif_ceiling_warnings(visual_plan, settings)
    return CostReport(
        mock_subsystems=settings.active_mocks(),
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
        gif_cap=settings.gif_max_per_video,
        est_runtime_min=estimate_runtime_minutes(script.word_count, settings.mock_wps_long),
        delivery_directives=_count_directives(script),
        est_render_minutes=estimate_render_minutes("long", script.word_count, settings.mock_wps_long),
        mtd_spend_usd=ledger.mtd_spend_usd(),
        monthly_cap_usd=settings.monthly_spend_cap_usd,
        kit_reach=script_reach(script, settings).line(),
        warnings=warnings,
        blocking=blocking,
        script_sha=script.content_sha(),
    )
