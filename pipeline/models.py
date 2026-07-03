"""Pydantic models + enums shared across the pipeline.

These are the data contracts of §5: the SHORT strict-JSON script, the LONG
tagged-narration script, TTS word timestamps, the Refinitiv audit schema,
job records, screener candidates and the validation/cost report.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# --------------------------------------------------------------------------
# Verdict taxonomy — the brand device. Swings both ways (§10).
# --------------------------------------------------------------------------


class Verdict(str, Enum):
    # scathing
    TOXIC = "TOXIC"
    PONZI_ADJACENT = "PONZI_ADJACENT"
    OVERVALUED = "OVERVALUED"
    DEAD_MONEY = "DEAD_MONEY"
    FALLING_KNIFE = "FALLING_KNIFE"
    # (satirically) laudatory
    VALUE_GEM = "VALUE_GEM"
    CASH_COW = "CASH_COW"
    QUIET_COMPOUNDER = "QUIET_COMPOUNDER"
    SECRETLY_ELITE = "SECRETLY_ELITE"
    BORING_AND_RICH = "BORING_AND_RICH"

    @property
    def is_laudatory(self) -> bool:
        return self in {
            Verdict.VALUE_GEM,
            Verdict.CASH_COW,
            Verdict.QUIET_COMPOUNDER,
            Verdict.SECRETLY_ELITE,
            Verdict.BORING_AND_RICH,
        }


SCATHING_VERDICTS = [v for v in Verdict if not v.is_laudatory]
LAUDATORY_VERDICTS = [v for v in Verdict if v.is_laudatory]

# Fixed SFX taxonomy (assets/sfx/<key>.wav). Unknown keys are skipped+warned.
SFX_KEYS = (
    "windows_error",
    "cash_register",
    "record_scratch",
    "sad_trombone",
    "camera_shutter",
    "vine_boom",
)


class HighlightColor(str, Enum):
    RED = "red"
    GREEN = "green"


# --------------------------------------------------------------------------
# SHORT script (§5.2) — strict JSON.
# --------------------------------------------------------------------------

_END_MINUS_RE = re.compile(r"^end_minus_(\d+(?:\.\d+)?)$")


class HighlightDirection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["highlight"]
    line_index: int = Field(ge=0)
    color: HighlightColor = HighlightColor.RED
    anchor_word: str = Field(min_length=1)


class StampDirection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["stamp"]
    label: Verdict
    anchor: str = "end_minus_3"

    @field_validator("anchor")
    @classmethod
    def _check_anchor(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("stamp anchor must not be empty")
        # either "end_minus_N" or an anchor word/phrase from the script
        return v

    def end_offset(self) -> float | None:
        m = _END_MINUS_RE.match(self.anchor)
        return float(m.group(1)) if m else None


VisualDirection = Annotated[
    Union[HighlightDirection, StampDirection], Field(discriminator="type")
]


class ShortScript(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str = Field(min_length=1, max_length=15)
    format: Literal["short"]
    verdict: Verdict
    hook_text: str = Field(min_length=1, max_length=90)
    audio_script: str = Field(min_length=1)
    data_block: list[str] = Field(min_length=1, max_length=10)
    visual_directions: list[VisualDirection] = Field(min_length=1)
    cta_text: str = Field(min_length=1, max_length=120)

    @field_validator("ticker")
    @classmethod
    def _norm_ticker(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("data_block")
    @classmethod
    def _non_empty_lines(cls, v: list[str]) -> list[str]:
        cleaned = [line.strip() for line in v]
        if any(not line for line in cleaned):
            raise ValueError("data_block contains an empty line")
        return cleaned

    @model_validator(mode="after")
    def _cross_checks(self) -> "ShortScript":
        for d in self.highlights:
            if d.line_index >= len(self.data_block):
                raise ValueError(
                    f"highlight line_index {d.line_index} out of range "
                    f"(data_block has {len(self.data_block)} lines)"
                )
        if not self.stamps:
            raise ValueError("visual_directions must include a stamp direction")
        return self

    @property
    def highlights(self) -> list[HighlightDirection]:
        return [d for d in self.visual_directions if isinstance(d, HighlightDirection)]

    @property
    def stamps(self) -> list[StampDirection]:
        return [d for d in self.visual_directions if isinstance(d, StampDirection)]

    @property
    def word_count(self) -> int:
        return len(self.audio_script.split())

    @property
    def char_count(self) -> int:
        return len(self.audio_script)

    def missing_anchor_words(self) -> list[str]:
        """Anchors not found verbatim (case-insensitive) in audio_script."""
        script = self.audio_script.lower()
        return [
            d.anchor_word
            for d in self.highlights
            if d.anchor_word.lower() not in script
        ]

    def content_sha(self) -> str:
        return hashlib.sha256(
            self.model_dump_json().encode("utf-8")
        ).hexdigest()[:16]


# --------------------------------------------------------------------------
# LONG script (§5.3) — tagged narration.
# --------------------------------------------------------------------------


class TagType(str, Enum):
    BROLL = "B-ROLL"
    SHOW_REFINITIV = "SHOW REFINITIV"
    SOUND = "SOUND"
    STAMP = "STAMP"


class TagEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: TagType
    payload: str
    # offset into the CLEAN narration (tags stripped) — what TTS timestamps
    # refer to. raw_offset is the position in the original tagged text.
    char_offset: int = Field(ge=0)
    raw_offset: int = Field(ge=0)


class LongScript(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str = Field(min_length=1, max_length=15)
    narration: str = Field(min_length=1)  # clean, tag-free — goes to TTS
    events: list[TagEvent] = Field(default_factory=list)

    @field_validator("ticker")
    @classmethod
    def _norm_ticker(cls, v: str) -> str:
        return v.strip().upper()

    @property
    def word_count(self) -> int:
        return len(self.narration.split())

    @property
    def char_count(self) -> int:
        return len(self.narration)

    def events_of(self, t: TagType) -> list[TagEvent]:
        return [e for e in self.events if e.type == t]

    def content_sha(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------
# TTS + timeline primitives.
# --------------------------------------------------------------------------


class WordTimestamp(BaseModel):
    model_config = ConfigDict(extra="forbid")

    word: str
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    # character span of the word in the (clean) script text
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)


class TTSResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    audio_path: Path
    words: list[WordTimestamp]
    duration_s: float
    chars: int
    cached: bool
    cost_usd: float  # 0.0 when served from cache or mock


class CueKind(str, Enum):
    HOOK = "hook"
    WHIP_PAN = "whip_pan"
    DATA_LINE = "data_line"
    HIGHLIGHT = "highlight"
    STAMP = "stamp"
    CTA = "cta"
    BROLL = "broll"
    REFINITIV = "refinitiv"
    SOUND = "sound"


class Cue(BaseModel):
    """One resolved visual/audio event on the master clock."""

    model_config = ConfigDict(extra="allow")

    t: float = Field(ge=0)
    kind: CueKind
    payload: dict = Field(default_factory=dict)
    # True when the anchor word was not found and a fallback position was used
    fallback: bool = False


# --------------------------------------------------------------------------
# Refinitiv audit (§5.1) — stable schema.
# --------------------------------------------------------------------------

REFINITIV_FIELDS: dict[str, list[str]] = {
    "identity": ["company_name", "ticker", "exchange", "sector", "currency", "as_of_date"],
    "size": ["price", "market_cap", "shares_outstanding", "enterprise_value"],
    "growth": ["revenue_ttm", "revenue_yoy_pct", "revenue_cagr_3y_pct"],
    "margins": ["gross_margin_pct", "operating_margin_pct", "net_margin_pct", "net_income_ttm"],
    "cash": ["operating_cf_ttm", "capex_ttm", "fcf_ttm", "fcf_margin_pct", "fcf_yield_pct"],
    "balance": [
        "cash_and_equivalents", "total_debt", "net_debt",
        "net_debt_to_ebitda", "debt_to_equity", "interest_coverage",
    ],
    "returns": ["roic_pct", "roe_pct"],
    "valuation": ["pe_ratio", "ps_ratio", "ev_ebitda", "pb_ratio", "p_fcf"],
    "dilution": ["shares_outstanding_yoy_pct"],
    "optional": ["dividend_yield_pct", "buyback_yield_pct", "short_interest_pct"],
}

# Missing fields in these groups BLOCK the run (§5.1); the rest only warn.
REFINITIV_BLOCKING_GROUPS = ("identity", "size", "margins", "cash")

ALL_REFINITIV_FIELDS: list[str] = [f for group in REFINITIV_FIELDS.values() for f in group]
_STRING_FIELDS = {"company_name", "ticker", "exchange", "sector", "currency", "as_of_date"}


class RefinitivAudit(BaseModel):
    """Clean, typed view of the operator's Refinitiv export."""

    model_config = ConfigDict(extra="forbid")

    values: dict[str, str | float | None] = Field(default_factory=dict)
    source_file: str = ""

    def get(self, field: str):
        return self.values.get(field)

    @property
    def missing(self) -> list[str]:
        return [f for f in ALL_REFINITIV_FIELDS if self.values.get(f) in (None, "")]

    @property
    def blocking_missing(self) -> list[str]:
        blocking = {
            f for g in REFINITIV_BLOCKING_GROUPS for f in REFINITIV_FIELDS[g]
        }
        return [f for f in self.missing if f in blocking]

    @property
    def warning_missing(self) -> list[str]:
        blocking = set(self.blocking_missing)
        return [f for f in self.missing if f not in blocking]

    def as_prompt_block(self) -> str:
        """Render as the {{refinitiv_data}} block for the master prompts."""
        lines: list[str] = []
        for group, fields in REFINITIV_FIELDS.items():
            present = [
                f"{f} = {self.values[f]}"
                for f in fields
                if self.values.get(f) not in (None, "")
            ]
            if present:
                lines.append(f"[{group}]")
                lines.extend(f"  {p}" for p in present)
        return "\n".join(lines) if lines else "(no data)"


# --------------------------------------------------------------------------
# Jobs.
# --------------------------------------------------------------------------


class JobKind(str, Enum):
    RENDER_SHORT = "render_short"
    RENDER_LONG = "render_long"
    RENDER_DRAFT_LONG = "render_draft_long"
    REPURPOSE = "repurpose"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"  # was running when the process died


class JobRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    kind: JobKind
    ticker: str
    workdate: str  # YYYY-MM-DD workspace folder
    status: JobStatus = JobStatus.QUEUED
    created_at: str = Field(default_factory=lambda: _utcnow())
    updated_at: str = Field(default_factory=lambda: _utcnow())
    error: str = ""
    artifact: str = ""       # path of the rendered MP4 when done
    delivered_link: str = "" # shareable link after delivery
    detail: str = ""         # free-form progress note

    def touch(self) -> None:
        self.updated_at = _utcnow()


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------
# Screener.
# --------------------------------------------------------------------------


class Lane(str, Enum):
    TRENDING = "trending"
    VALUE = "value"


class Candidate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ticker: str
    lane: Lane
    score: float
    reasons: list[str] = Field(default_factory=list)
    price: float | None = None
    pct_change: float | None = None
    metrics: dict = Field(default_factory=dict)

    @property
    def why(self) -> str:
        return " · ".join(self.reasons) if self.reasons else "—"


# --------------------------------------------------------------------------
# Validation + cost report (§9.3) — the spend gate artifact.
# --------------------------------------------------------------------------


class BrollPlanItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    key: str
    source: str  # local | cache | pexels | filler
    path: str = ""
    attribution: str = ""


class CostReport(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ticker: str
    fmt: str  # "short" | "long"
    words: int
    chars: int
    tts_cached: bool
    est_tts_usd: float
    data_block_lines: int = 0
    stamp: str = ""
    highlight_note: str = ""
    broll: list[BrollPlanItem] = Field(default_factory=list)
    refinitiv_overlays: int = 0
    est_render_minutes: float = 0.0
    mtd_spend_usd: float = 0.0
    monthly_cap_usd: float = 0.0
    warnings: list[str] = Field(default_factory=list)
    blocking: list[str] = Field(default_factory=list)
    script_sha: str = ""

    @property
    def approvable(self) -> bool:
        return not self.blocking

    @property
    def broll_counts(self) -> dict[str, int]:
        counts = {"local": 0, "cache": 0, "pexels": 0, "filler": 0}
        for item in self.broll:
            counts[item.source] = counts.get(item.source, 0) + 1
        return counts

    def render_text(self) -> str:
        """The human report shown in Telegram above the Approve button."""
        lines: list[str] = []
        head = f"{self.ticker} — {self.fmt.upper()} — "
        head += "ready to render" if self.approvable else "BLOCKED"
        lines.append(head)

        tts = f"Audio: {self.words} words / {self.chars} chars"
        tts += "  (cached — $0.00 TTS)" if self.tts_cached else f"  (~${self.est_tts_usd:.2f} TTS)"
        lines.append(tts)

        if self.fmt == "short":
            lines.append(f"Data block: {self.data_block_lines} lines ✓   Stamp: {self.stamp} ✓")
            if self.highlight_note:
                lines.append(self.highlight_note)
        if self.broll:
            c = self.broll_counts
            lines.append(
                f"B-roll: {len(self.broll)} clips "
                f"(local {c['local']} / cache {c['cache']} / pexels {c['pexels']} / filler {c['filler']})"
            )
        else:
            lines.append("B-roll: n/a")
        lines.append(f"Refinitiv overlay: {self.refinitiv_overlays or 'not used'}")
        lines.append(
            f"Est. render: ~{self.est_render_minutes:.0f} min   "
            f"MTD spend: ${self.mtd_spend_usd:.2f} / ${self.monthly_cap_usd:.2f} cap"
        )
        for w in self.warnings:
            lines.append(f"⚠️ {w}")
        for b in self.blocking:
            lines.append(f"⛔ {b}")
        return "\n".join(lines)
