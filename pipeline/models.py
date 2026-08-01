"""Pydantic models + enums shared across the pipeline.

The data contracts of the Dennis build: the SHORT "Noise or signal?"
strict-JSON script, the LONG tagged-narration script, TTS word
timestamps, the company-data schema (latest snapshot + 5-year history,
vendor never named), job records, screener candidates and the
validation/cost report.

There is deliberately NO verdict enum anywhere — videos end on a deadpan
free-text conclusion and the viewer draws their own.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Fixed SFX taxonomy (assets/sfx/<key>.wav). Unknown keys are skipped+warned.
SFX_KEYS = (
    "windows_error",
    "cash_register",
    "record_scratch",
    "sad_trombone",
    "camera_shutter",
    "vine_boom",
    # the deadpan set — dry, lo-fi, no drama. Used sparsely: these are the
    # room Dennis is sitting in, not a punchline.
    "coffee_slurp",
    "keyboard_clack",
    "paper_rustle",
    "buzzer",
    "ding",
)


# --------------------------------------------------------------------------
# Shared tag grammar — used by BOTH formats (LONG narration tags, SHORT
# inline [DOODLE]/[SCRIBBLE] tags). Kept up here so the SHORT script can
# carry inline-parsed events too.
# --------------------------------------------------------------------------


class TagType(str, Enum):
    IMG = "IMG"                  # real imagery: operations/facilities/people
    PRODUCT = "PRODUCT"          # real imagery: the product itself
    MEME = "MEME"                # owned meme library first (capped per video)
    CLIP = "CLIP"                # ironic stock footage (Pexels palette)
    BROLL = "BROLL"              # alias of CLIP (legacy spelling)
    CHART = "CHART"              # auto-generated chart in the channel style
    SHOW_FILING = "SHOW FILING"  # the (unnamed-source) data screenshot
    SHOW_ARTICLE = "SHOW ARTICLE"  # a screenshot of the real article's headline
    SCREENGRAB = "SCREENGRAB"    # operator-supplied app/screen capture (blocks if missing)
    SOUND = "SOUND"              # sfx palette
    ASSET = "ASSET"              # bespoke Claude-Design asset (blocks if missing)
    DOODLE = "DOODLE"            # crude hand-drawn overlay (owned, top layer)
    SCRIBBLE = "SCRIBBLE"        # drawn annotation on a number/point (top layer)
    # design-kit families, resolved by name through pipeline.kit
    TERM = "TERM"                # the "teach one framework" definition card
    BIGNUM = "BIGNUM"            # the single-stat card
    TABLE = "TABLE"              # a strict readable table (P&L, comps, …)
    PROP = "PROP"                # a generic object cutaway (warehouse, servers…)
    ALERT = "ALERT"              # mid-frame lower-third interjection (overlay)
    # delivery direction — stripped from captions, passed to TTS
    BEAT = "BEAT"                # a deliberate pause
    SIGH = "SIGH"
    FLAT = "FLAT"                # hold the register flatter than baseline
    DRY = "DRY"


# tag types that claim a visual SEGMENT on the LONG timeline (the base
# frame). DOODLE and SCRIBBLE are overlays that ride on top of whatever is
# on screen, so they never claim a segment of their own.
VISUAL_TAG_TYPES = frozenset({
    TagType.IMG, TagType.PRODUCT, TagType.MEME, TagType.CLIP, TagType.BROLL,
    TagType.CHART, TagType.SHOW_FILING, TagType.SHOW_ARTICLE,
    TagType.SCREENGRAB, TagType.ASSET,
    TagType.TERM, TagType.BIGNUM, TagType.TABLE, TagType.PROP,
})

# overlay tag types — composited over the current frame, not a segment.
OVERLAY_TAG_TYPES = frozenset({TagType.DOODLE, TagType.SCRIBBLE, TagType.ALERT})

# Delivery direction. These never reach the screen — they are stripped from
# the captions and re-inserted into the TTS request, because deadpan comedy
# is timing and the pipeline was sending flat text with none of it.
DELIVERY_TAG_TYPES = frozenset({TagType.BEAT, TagType.SIGH, TagType.FLAT,
                                TagType.DRY})

# What a SHORT's `audio_script` may carry inline.
#
# It used to be three tags. The prompt documented [BEAT]/[FLAT]/[SIGH]/[DRY]
# and the parser dropped them on the floor, so TTS got unpaused text and the
# delivery was flat by omission — the one failure here you cannot see in a
# frame. And the whole evidence grammar the LONG has was simply unavailable,
# which is why a short reached six assets out of 384.
SHORT_TAG_TYPES = frozenset(
    OVERLAY_TAG_TYPES | DELIVERY_TAG_TYPES | {
        TagType.IMG, TagType.PRODUCT, TagType.SHOW_FILING,
        TagType.SHOW_ARTICLE, TagType.SCREENGRAB, TagType.PROP,
        TagType.BIGNUM, TagType.TERM, TagType.MEME, TagType.CLIP,
        TagType.BROLL,
    })

# Tags that claim the SHORT's frame for a beat (as opposed to riding on top of
# whatever is showing). Delivery tags claim nothing — they are audio.
SHORT_SEGMENT_TAG_TYPES = frozenset({
    TagType.IMG, TagType.PRODUCT, TagType.SHOW_FILING, TagType.SHOW_ARTICLE,
    TagType.SCREENGRAB, TagType.PROP, TagType.BIGNUM, TagType.TERM,
    TagType.MEME, TagType.CLIP, TagType.BROLL,
})

# Kit families each design-kit tag resolves against, in search order.
#
# A tuple, not a string: the rebuilt kit spreads one tag's artwork across
# several folders — an ALERT is a press lower-third, a PROP may be a prop, a
# concept illustration or an in-joke — and a tag pinned to a single hardcoded
# folder is how most of the library stayed unreachable.
KIT_TAG_FAMILIES: dict[TagType, tuple[str, ...]] = {
    TagType.TERM: ("blanks", "type"),
    TagType.BIGNUM: ("blanks", "type"),
    TagType.TABLE: ("chapters/sector-comps", "charts-style"),
    TagType.PROP: ("props", "concepts", "restyled/concepts", "restyled/injokes",
                   "shorts/dennis-vs-numbers", "shorts/dennis-vs-numbers-2",
                   "shorts/transformations", "shorts/transformations-2",
                   "shorts/vertical-scenes", "shorts/vertical-scenes-2"),
    TagType.ALERT: ("press",),
}

# The parameterised layout each card tag falls back to when no named artwork
# exists for the key. These are the blank layouts the previous kit shipped and
# nothing ever filled: the slot names are the fields the renderer composites.
KIT_TAG_BLANKS: dict[TagType, str] = {
    TagType.TERM: "blanks/term-card-blank",
    TagType.BIGNUM: "blanks/big-number-blank",
}


class ScribbleStyle(str, Enum):
    CIRCLE = "circle"
    ARROW = "arrow"
    UNDERLINE = "underline"


def parse_scribble_payload(payload: str) -> tuple[ScribbleStyle, str] | None:
    """`[SCRIBBLE: circle -> target]` -> (style, target). None if malformed
    or the style is unknown (caller logs + skips — never fatal)."""
    if "->" not in payload:
        return None
    style_raw, target = payload.split("->", 1)
    style_raw = style_raw.strip().lower()
    target = target.strip()
    if not target:
        return None
    try:
        return ScribbleStyle(style_raw), target
    except ValueError:
        return None


class TagEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: TagType
    payload: str
    # offset into the CLEAN text (tags stripped) — what TTS timestamps
    # refer to. raw_offset is the position in the original tagged text.
    char_offset: int = Field(ge=0)
    raw_offset: int = Field(ge=0)
    # optional modifier — [CHART: metric style=marker] parses to style.
    style: str = ""


# --------------------------------------------------------------------------
# SHORT script — the "Noise or signal?" format (§4). Strict JSON.
# --------------------------------------------------------------------------


class ChartStyle(str, Enum):
    CLEAN = "clean"    # the branded price card
    MARKER = "marker"  # the crude hand-drawn "napkin" chart


class Headline(BaseModel):
    """One driver headline overlaid ON the branded chart."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=120)     # shown on screen, mute-safe
    meaning: str = Field(min_length=1, max_length=240)  # what it actually means


class NumberRow(BaseModel):
    """One metric row on the numbers sheet — MULTI-YEAR, oldest -> newest."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=40)
    values: list[str] = Field(min_length=2, max_length=6)

    @field_validator("values")
    @classmethod
    def _non_empty_values(cls, v: list[str]) -> list[str]:
        cleaned = [x.strip() for x in v]
        if any(not x for x in cleaned):
            raise ValueError("values contains an empty entry")
        return cleaned


class AnnotationTarget(str, Enum):
    CHART = "chart"
    NUMBERS = "numbers"


class Annotation(BaseModel):
    """A hand-drawn scribble on the chart or the numbers sheet, fired at
    an anchor word in the audio."""

    model_config = ConfigDict(extra="forbid")

    target: AnnotationTarget
    anchor_word: str = Field(min_length=1)
    note: str = Field(default="", max_length=40)      # optional scribbled text
    row_index: int | None = Field(default=None, ge=0)  # numbers target only


class CutawayTag(BaseModel):
    """Optional meme / ironic-broll cutaway with an optional anchor word."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=80)
    anchor_word: str = ""


class ShortScript(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str = Field(min_length=1, max_length=15)
    format: Literal["short"]
    hook_text: str = Field(min_length=1, max_length=90)   # mute-safe cold open
    audio_script: str = Field(min_length=1)
    move_summary: str = Field(min_length=1, max_length=80)  # how much / how active
    headlines: list[Headline] = Field(min_length=1, max_length=3)
    numbers: list[NumberRow] = Field(min_length=1, max_length=6)
    years: list[str] = Field(default_factory=list, max_length=6)  # sheet columns
    numbers_comment: str = Field(min_length=1, max_length=300)    # holistic read
    # the CHEAP-OR-TRAP beat: is the multiple a bargain or a value trap? Held
    # on screen ~4-5s so it can actually be read. Optional so scripts written
    # against the four-beat format still parse.
    cheap_or_trap: str | None = Field(default=None, max_length=260)
    conclusion: str = Field(min_length=1, max_length=220)  # noise vs signal, free text
    chart_style: ChartStyle = ChartStyle.CLEAN  # open on clean or marker chart
    meme: CutawayTag | None = None
    broll: CutawayTag | None = None
    annotations: list[Annotation] = Field(default_factory=list, max_length=4)
    # inline [DOODLE]/[SCRIBBLE] tags the parser strips out of audio_script
    # (never spoken); offsets index the CLEAN audio_script. Model-populated,
    # never authored directly in the JSON.
    inline_events: list[TagEvent] = Field(default_factory=list)

    @field_validator("ticker")
    @classmethod
    def _norm_ticker(cls, v: str) -> str:
        return v.strip().upper()

    @model_validator(mode="after")
    def _cross_checks(self) -> "ShortScript":
        for a in self.annotations:
            if a.target is AnnotationTarget.NUMBERS:
                idx = a.row_index if a.row_index is not None else 0
                if idx >= len(self.numbers):
                    raise ValueError(
                        f"annotation row_index {idx} out of range "
                        f"(numbers has {len(self.numbers)} rows)"
                    )
        return self

    @property
    def word_count(self) -> int:
        return len(self.audio_script.split())

    @property
    def char_count(self) -> int:
        return len(self.audio_script)

    def anchor_words(self) -> list[str]:
        """Every anchor the timeline will try to resolve."""
        anchors = [a.anchor_word for a in self.annotations]
        for tag in (self.meme, self.broll):
            if tag is not None and tag.anchor_word:
                anchors.append(tag.anchor_word)
        return anchors

    def missing_anchor_words(self) -> list[str]:
        """Anchors not found verbatim (case-insensitive) in audio_script."""
        script = self.audio_script.lower()
        return [a for a in self.anchor_words() if a.lower() not in script]

    def doodle_events(self) -> list[TagEvent]:
        return [e for e in self.inline_events if e.type is TagType.DOODLE]

    def scribble_events(self) -> list[TagEvent]:
        return [e for e in self.inline_events if e.type is TagType.SCRIBBLE]

    def content_sha(self) -> str:
        return hashlib.sha256(
            self.model_dump_json().encode("utf-8")
        ).hexdigest()[:16]


# --------------------------------------------------------------------------
# LONG script — tagged narration with the Dennis tag grammar (§5).
# --------------------------------------------------------------------------


class LongScript(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str = Field(min_length=1, max_length=15)
    narration: str = Field(min_length=1)  # clean, tag-free — goes to TTS
    events: list[TagEvent] = Field(default_factory=list)
    # slug -> the self-contained Claude Design prompt the director appended
    asset_prompts: dict[str, str] = Field(default_factory=dict)
    # the `=== CHAPTERS ===` trailer (mm:ss Title lines) — YouTube chapter
    # markers the operator pastes; metadata only, split off so it's never spoken
    chapters: str = ""

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

    def events_of(self, *types: TagType) -> list[TagEvent]:
        wanted = set(types)
        return [e for e in self.events if e.type in wanted]

    def meme_count(self) -> int:
        return len(self.events_of(TagType.MEME))

    def asset_slugs(self) -> list[str]:
        seen: list[str] = []
        for e in self.events_of(TagType.ASSET):
            if e.payload not in seen:
                seen.append(e.payload)
        return seen

    def screengrab_slugs(self) -> list[str]:
        seen: list[str] = []
        for e in self.events_of(TagType.SCREENGRAB):
            if e.payload not in seen:
                seen.append(e.payload)
        return seen

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
    # Which tier produced it: mock | local | paid.
    #
    # `draft` means specifically "the word timings are INTERPOLATED and are
    # being passed off as real" — which is true of the local voice and of
    # nothing else. Mock audio has synthetic timings too, but MOCK_MODE is the
    # established offline contract: the suite and the whole dev loop render
    # finals from it, and everyone involved knows the video is a test artifact.
    # The local tier is the one that produces something that SOUNDS finished
    # while being a fraction of a second out, which is why it alone is fenced
    # off from final renders (P3.2).
    tier: str = "paid"
    draft: bool = False


class CueKind(str, Enum):
    # SHORT beats (Noise or signal?)
    HOST_OPEN = "host_open"      # Dennis talking, before the hook lands
    HOOK = "hook"
    TRANSITION = "transition"
    HEADLINE = "headline"
    NUMBERS = "numbers"          # the sheet slides in
    NUMBER_ROW = "number_row"    # one row types on
    ANNOTATION = "annotation"    # hand-drawn scribble
    ZOOM = "zoom"                # zoom-punch on the key number
    CHEAP_OR_TRAP = "cheap_or_trap"  # the value-trap beat, held to be read
    CONCLUSION = "conclusion"
    HOST_CLOSE = "host_close"    # Dennis talking, after the payoff
    CUTAWAY = "cutaway"          # ironic broll cutaway (SHORT)
    # LONG visuals (MEME + SOUND are shared by both formats)
    MEME = "meme"
    CLIP = "clip"
    IMG = "img"
    CHART = "chart"
    FILING = "filing"
    SCREENGRAB = "screengrab"
    ASSET = "asset"
    TERM = "term"                # the framework/definition card
    BIGNUM = "bignum"            # the single-stat card
    TABLE = "table"              # a strict readable table
    PROP = "prop"                # a generic object cutaway
    SOUND = "sound"
    # hand-drawn overlays (both formats) — composited on top, no segment
    DOODLE = "doodle"
    SCRIBBLE = "scribble"
    ALERT = "alert"              # lower-third interjection over the frame


class Cue(BaseModel):
    """One resolved visual/audio event on the master clock."""

    model_config = ConfigDict(extra="allow")

    t: float = Field(ge=0)
    kind: CueKind
    payload: dict = Field(default_factory=dict)
    # True when the anchor word was not found and a fallback position was used
    fallback: bool = False


# --------------------------------------------------------------------------
# Company data (§3) — the PRIVATE data source, the v3 template. Sheets read
# by NAME: Snapshot (point-in-time), History (6 periods, oldest → newest,
# read dynamically from the header row), Dashboard (the one-glance summary
# the numbers sheet reads), plus Valuation (bear/base/bull) and Peers for
# long-form. The vendor is never named on-screen; internally this is just
# "company data".
# --------------------------------------------------------------------------

# Snapshot field_keys, grouped by the sheet's Section column.
DATA_FIELDS: dict[str, list[str]] = {
    "identity": ["company_name", "ticker", "exchange", "sector", "industry",
                 "country", "currency", "as_of_date"],
    # `shares_dill_out` (diluted) arrived with the v3.1 template; the basic
    # count stays the required one, and the dilution gap between them is the
    # interesting number.
    "size": ["price", "market_cap", "enterprise_value", "shares_out",
             "shares_dill_out", "avg_volume_3m", "beta", "week52_high",
             "week52_low", "pct_from_52w_high"],
    "valuation": ["pe_ttm", "forward_pe", "ps_ttm", "ev_ebitda", "ev_sales",
                  "ev_fcf", "pb", "p_fcf", "peg", "earnings_yield",
                  "fcf_yield", "dividend_yield", "buyback_yield",
                  "shareholder_yield"],
    "balance": ["cash_st", "total_debt_now", "net_debt_now",
                "net_debt_ebitda_now", "debt_to_equity", "current_ratio",
                "quick_ratio", "interest_coverage", "goodwill_intang",
                "tangible_bv"],
    "ownership": ["short_interest", "insider_own", "institutional_own"],
}

# These fields BLOCK the run when missing; everything else only warns.
DATA_REQUIRED: list[str] = ["company_name", "ticker", "as_of_date", "price",
                            "market_cap", "shares_out"]

ALL_DATA_FIELDS: list[str] = [f for group in DATA_FIELDS.values() for f in group]
_STRING_FIELDS = {"company_name", "ticker", "exchange", "sector", "industry",
                  "country", "currency", "as_of_date"}

# History sheet field_keys (col A). Period columns (FY-4..FY-0, LTM) are
# read dynamically from the header row — never hardcoded here.
HISTORY_FIELDS: list[str] = [
    "revenue", "gross_profit", "gross_margin", "operating_income",
    "operating_margin", "ebitda", "net_income", "net_margin", "operating_cf",
    "capex", "fcf", "fcf_margin", "sbc", "sbc_pct_rev", "dividends_paid",
    "buybacks", "cash", "total_debt", "net_debt", "total_equity",
    "total_assets", "invested_capital", "net_debt_ebitda", "eps", "fcf_ps",
    "bvps", "roic", "roe", "diluted_shares", "shares_yoy",
]


class CompanyData(BaseModel):
    """Clean, typed view of the operator's v3 data export.

    `valuation` is a dict carrying the scenario inputs (`current_price`,
    `ltm_eps`, `ltm_fcf_ps`), the bear/base/bull `scenarios` list, and the
    auto WACC + reverse-DCF block: `wacc`, `implied_growth`, `hist_fcf_cagr`,
    `rev_cagr`, `priced_vs_delivered` (all numeric) and `reverse_dcf_read`
    (a free-text verdict).

    `news` is a list of `{date, headline, source, url}` dicts (dates ISO,
    Source a news outlet — never a data-terminal brand). `peer_percentiles`
    is a list of `{metric, subject, median, percentile, direction, read}`
    dicts — the subject's self-score vs its peers (percentile 0–1;
    direction `better`/`worse`)."""

    model_config = ConfigDict(extra="forbid")

    values: dict[str, str | float | None] = Field(default_factory=dict)
    history_years: list[str] = Field(default_factory=list)   # oldest -> newest
    history: dict[str, list[float | None]] = Field(default_factory=dict)
    dashboard: dict[str, str | float | None] = Field(default_factory=dict)
    valuation: dict = Field(default_factory=dict)   # inputs + bear/base/bull + WACC/reverse-DCF
    peers: list[dict] = Field(default_factory=list)
    peer_percentiles: list = Field(default_factory=list)  # subject self-score vs peers
    news: list = Field(default_factory=list)              # recent headlines (optional)
    source_file: str = ""

    def get(self, field: str):
        return self.values.get(field)

    @property
    def missing(self) -> list[str]:
        return [f for f in ALL_DATA_FIELDS if self.values.get(f) in (None, "")]

    @property
    def blocking_missing(self) -> list[str]:
        return [f for f in DATA_REQUIRED if self.values.get(f) in (None, "")]

    @property
    def warning_missing(self) -> list[str]:
        blocking = set(self.blocking_missing)
        return [f for f in self.missing if f not in blocking]

    @property
    def has_history(self) -> bool:
        return bool(self.history_years) and any(
            any(v is not None for v in vals) for vals in self.history.values()
        )

    @property
    def has_valuation(self) -> bool:
        return bool(self.valuation.get("scenarios"))

    @property
    def has_peers(self) -> bool:
        return bool(self.peers)

    def history_row(self, field: str) -> list[float | None]:
        return self.history.get(field, [])

    def available_chart_metrics(self) -> list[str]:
        """History metrics that have a multi-year series the renderer can draw
        trend bars from, plus 'price' (always drawable from the price feed).
        The director may only feature [CHART: metric] / numbers from these."""
        out = [
            f for f in HISTORY_FIELDS
            if sum(1 for v in self.history.get(f, []) if v is not None) >= 2
        ]
        out.append("price")
        return out

    def metric(self, key: str):
        """Snapshot value first, then the Dashboard summary (by label) —
        lets the thumbnail / scripts read a number wherever it lives."""
        v = self.values.get(key)
        if v not in (None, ""):
            return v
        return self.dashboard.get(key)

    def dashboard_get(self, label: str):
        return self.dashboard.get(label)

    def as_prompt_block(self) -> str:
        """Render as the {{company_data}} block for the master prompts —
        the snapshot by group, the multi-year history table, the one-glance
        Dashboard, then (long-form) the valuation scenarios + peer table."""
        lines: list[str] = []
        for group, fields in DATA_FIELDS.items():
            present = [
                f"{f} = {self.values[f]}"
                for f in fields
                if self.values.get(f) not in (None, "")
            ]
            if present:
                lines.append(f"[{group}]")
                lines.extend(f"  {p}" for p in present)
        if self.has_history:
            lines.append("[history · periods, oldest → newest]")
            lines.append("  periods: " + " | ".join(self.history_years))
            for f in HISTORY_FIELDS:
                vals = self.history.get(f)
                if vals and any(v is not None for v in vals):
                    cells = " | ".join("n/a" if v is None else f"{v:g}" for v in vals)
                    lines.append(f"  {f}: {cells}")
        if self.dashboard:
            lines.append("[dashboard · one-glance summary + flags]")
            for label, val in self.dashboard.items():
                if val not in (None, ""):
                    lines.append(f"  {label}: {val}")
        if self.has_valuation:
            lines.append("[valuation · bear/base/bull]")
            for k in ("current_price", "ltm_eps", "ltm_fcf_ps"):
                if self.valuation.get(k) not in (None, ""):
                    lines.append(f"  {k} = {self.valuation[k]}")
            for sc in self.valuation.get("scenarios", []):
                cells = ", ".join(f"{k}={v}" for k, v in sc.items()
                                  if v not in (None, ""))
                if cells:
                    lines.append(f"  {cells}")
        if self.has_peers:
            lines.append(f"[peers · {len(self.peers)} names]")
            for p in self.peers:
                name = p.get("name")
                if not name:
                    continue
                cells = ", ".join(f"{k}={v}" for k, v in p.items()
                                  if k != "name" and v not in (None, ""))
                lines.append(f"  {name}: {cells}")
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
    TRENDING = "trending"   # -> SHORT candidates
    VALUE = "value"         # -> LONG candidates (long-form NEVER covers trending)


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
# Validation + cost report — the spend gate artifact.
# --------------------------------------------------------------------------


class VisualPlanItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    key: str
    kind: str = "clip"   # clip | img | meme | chart | filing | asset
    source: str = ""     # local | library | cache | pexels | wikimedia | ... | filler
    path: str = ""
    attribution: str = ""


# report bucketing: where each resolver source counts
_OWNED_SOURCES = {"local", "library"}
_FILLER_SOURCES = {"filler"}


class CostReport(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ticker: str
    fmt: str  # "short" | "long"
    words: int
    chars: int
    tts_cached: bool
    est_tts_usd: float
    # Delivery direction changes the request text and the voice settings, so
    # it changes the cache key: it has to be authored before the paid run.
    delivery_directives: int = 0
    # SHORT specifics
    headline_count: int = 0
    numbers_rows: int = 0
    numbers_years: int = 0
    annotation_note: str = ""
    # LONG specifics
    visuals: list[VisualPlanItem] = Field(default_factory=list)
    filing_overlays: int = 0
    meme_count: int = 0
    meme_cap: int = 2
    est_runtime_min: float = 0.0   # estimated finished VIDEO length (min)
    est_render_minutes: float = 0.0  # estimated ffmpeg processing time (min)
    mtd_spend_usd: float = 0.0
    monthly_cap_usd: float = 0.0
    warnings: list[str] = Field(default_factory=list)
    blocking: list[str] = Field(default_factory=list)
    script_sha: str = ""

    @property
    def approvable(self) -> bool:
        return not self.blocking

    @property
    def visual_counts(self) -> dict[str, int]:
        counts = {"owned": 0, "cache": 0, "fetched": 0, "filler": 0}
        for item in self.visuals:
            if item.source in _OWNED_SOURCES:
                counts["owned"] += 1
            elif item.source == "cache":
                counts["cache"] += 1
            elif item.source in _FILLER_SOURCES:
                counts["filler"] += 1
            else:
                counts["fetched"] += 1
        return counts

    def render_text(self) -> str:
        """The human report shown in Telegram above the Approve button."""
        lines: list[str] = []
        head = f"{self.ticker} — {self.fmt.upper()} — "
        head += "ready to render" if self.approvable else "BLOCKED"
        lines.append(head)

        tts = f"Audio: {self.words} words / {self.chars} chars / ~{self.est_runtime_min:.0f} min video"
        tts += "  (cached — $0.00 TTS)" if self.tts_cached else f"  (~${self.est_tts_usd:.2f} TTS)"
        if self.delivery_directives:
            tts += (f"\n  {self.delivery_directives} delivery directive(s) "
                    f"([BEAT]/[SIGH]/[FLAT]/[DRY]) are baked into this "
                    f"generation — adding one later re-bills the whole script.")
        lines.append(tts)

        if self.fmt == "short":
            lines.append(
                f"Chart: branded, from cached prices ✓   "
                f"Headlines: {self.headline_count} ✓   "
                f"Numbers: {self.numbers_rows} rows × {self.numbers_years}yr"
            )
            if self.annotation_note:
                lines.append(self.annotation_note)
        if self.visuals:
            c = self.visual_counts
            lines.append(
                f"Visuals: {len(self.visuals)} "
                f"(owned {c['owned']} / cache {c['cache']} / fetched {c['fetched']} / filler {c['filler']})"
            )
        if self.fmt == "long":
            lines.append(f"Filing overlays: {self.filing_overlays or 'not used'}   "
                         f"Memes: {self.meme_count}/{self.meme_cap}")
        lines.append(
            f"Est. render: ~{self.est_render_minutes:.0f} min   "
            f"MTD spend: ${self.mtd_spend_usd:.2f} / ${self.monthly_cap_usd:.2f} cap"
        )
        for w in self.warnings:
            lines.append(f"⚠️ {w}")
        for b in self.blocking:
            lines.append(f"⛔ {b}")
        return "\n".join(lines)
