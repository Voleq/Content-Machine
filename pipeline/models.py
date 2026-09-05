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

from pipeline.plates import PERIOD_COUNT

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
    # THE PLATE TAG. The director names the plate and writes what goes on it;
    # the renderer puts that text in the declared slots and does nothing else.
    # It never picks a plate and it never computes a value — those were the two
    # halves of the same defect, and they are gone together.
    PLATE = "PLATE"              # [PLATE: name | slot=value | …]
    IMG = "IMG"                  # real imagery: operations/facilities/people
    PRODUCT = "PRODUCT"          # real imagery: the product itself
    MEME = "MEME"                # owned meme library first (capped per video)
    CLIP = "CLIP"                # ironic stock footage (Pexels palette)
    BROLL = "BROLL"              # alias of CLIP (legacy spelling)
    CHART = "CHART"              # a data path drawn into a charts/ plate
    SHOW_FILING = "SHOW FILING"  # the (unnamed-source) data screenshot
    SHOW_ARTICLE = "SHOW ARTICLE"  # a screenshot of the real article's headline
    SCREENGRAB = "SCREENGRAB"    # operator-supplied app/screen capture (blocks if missing)
    SOUND = "SOUND"              # sfx palette
    SCRIBBLE = "SCRIBBLE"        # an annotations/ mark on a number or a word
    # delivery direction — stripped from captions, passed to TTS
    BEAT = "BEAT"                # a deliberate pause
    SIGH = "SIGH"
    FLAT = "FLAT"                # hold the register flatter than baseline
    DRY = "DRY"

    # [ASSET] IS GONE, AND SO ARE THE FAMILY TAGS.
    #
    # [ASSET: slug] blocked a render until an operator pasted a prompt into
    # Claude Design, exported a PNG and uploaded it. A bespoke asset per video
    # does not scale to daily shorts and it was the slowest step in the loop —
    # and the whole point of the pivot is that the director picks from a library
    # that already exists. [SCREENGRAB] stays: that is an operator-supplied
    # capture of something real, which is a different thing.
    #
    # [TERM]/[BIGNUM]/[TABLE]/[PROP]/[ALERT] named a FAMILY and let the renderer
    # choose inside it. That is the bot picking its own assets, which is the
    # behaviour being removed. All five are now [PLATE: <name>] against the
    # cards/, figures/, tables/ and paper/ families, where the director names
    # the plate and fills its slots.
    #
    # [DOODLE] folded into [SCRIBBLE], which resolves to the annotations/ family.


# Tag types that claim a visual SEGMENT on the LONG timeline (the base frame).
# SCRIBBLE is an overlay that rides on top of whatever is on screen, so it never
# claims a segment of its own.
VISUAL_TAG_TYPES = frozenset({
    TagType.PLATE,
    TagType.IMG, TagType.PRODUCT, TagType.MEME, TagType.CLIP, TagType.BROLL,
    TagType.CHART, TagType.SHOW_FILING, TagType.SHOW_ARTICLE,
    TagType.SCREENGRAB,
})

# Foreign media — anything not drawn by the kit's own engine. All four are
# composited INSIDE a frames/ plate rather than landing full-frame, because a
# raw photograph over the whole frame destroys the drawn surface the rest of the
# video is built on. See pipeline.media_frames.
FOREIGN_MEDIA_TAG_TYPES = frozenset({
    TagType.CLIP, TagType.BROLL, TagType.IMG, TagType.PRODUCT,
    TagType.SHOW_ARTICLE, TagType.SHOW_FILING, TagType.SCREENGRAB,
    TagType.MEME,
})

# Overlay tag types — composited over the current frame, not a segment.
OVERLAY_TAG_TYPES = frozenset({TagType.SCRIBBLE})

# Delivery direction. These never reach the screen — they are stripped from
# the captions and re-inserted into the TTS request, because deadpan comedy
# is timing and the pipeline was sending flat text with none of it.
DELIVERY_TAG_TYPES = frozenset({TagType.BEAT, TagType.SIGH, TagType.FLAT,
                                TagType.DRY})

# What a SHORT's `audio_script` may carry inline. The same grammar as the long,
# minus the tags that need a runtime the short does not have.
SHORT_TAG_TYPES = frozenset(
    OVERLAY_TAG_TYPES | DELIVERY_TAG_TYPES | {
        TagType.PLATE, TagType.IMG, TagType.PRODUCT, TagType.SHOW_FILING,
        TagType.SHOW_ARTICLE, TagType.SCREENGRAB, TagType.MEME, TagType.CLIP,
        TagType.BROLL, TagType.CHART,
    })

# Tags that mean something with no payload at all, because the renderer can
# work out what they point at.
#
# `[SHOW ARTICLE]` is the only one: the export already carries the news rows the
# script was written from, and `script.headlines` is the writer's paraphrase of
# those same rows, so demanding a pasted URL asked the writer to go and find
# something the pipeline was already holding.
SELF_RESOLVING_TAG_TYPES = frozenset({TagType.SHOW_ARTICLE})

# Tags that claim the SHORT's frame for a beat (as opposed to riding on top of
# whatever is showing). Delivery tags claim nothing — they are audio.
SHORT_SEGMENT_TAG_TYPES = frozenset({
    TagType.PLATE, TagType.IMG, TagType.PRODUCT, TagType.SHOW_FILING,
    TagType.SHOW_ARTICLE, TagType.SCREENGRAB, TagType.MEME, TagType.CLIP,
    TagType.BROLL, TagType.CHART,
})


class ScribbleStyle(str, Enum):
    """The `[SCRIBBLE: …]` vocabulary — one member per drawing in ``annotations/``.

    The values ARE the plate names: a style resolves straight to
    ``annotations/<value>`` and there is no per-mark code path anywhere. The old
    list mapped twelve invented style words onto the retired ``marks/`` family;
    these ten are what the kit actually ships.

    An annotation is drawn in ATTENTION and therefore SPENDS the frame's one
    attention. A plate that already carries an attention mark cannot also be
    annotated — that is why these are a family and not a flag on every plate:
    the choice has to be made, by someone, once per frame.
    """

    SCRAWL_OVAL_WIDE = "scrawl-oval-wide"
    SCRAWL_OVAL_TIGHT = "scrawl-oval-tight"
    UNDERLINE_SWIPE = "underline-swipe"
    UNDERLINE_TIGHT = "underline-tight"
    STRIKE_OUT = "strike-out"
    BOX_SCRAWL = "box-scrawl"
    BRACKET_ROWS = "bracket-rows"
    ARROW_ELBOW = "arrow-elbow"
    CARET_NOTE = "caret-note"
    TICK_MARKS = "tick-marks"


# What a writer is likely to type, mapped to the mark that does that job. A
# beat lost over a synonym is a silent nothing on screen, which is worse than
# a rejection — but the plate names stay the vocabulary, so this is a doormat,
# not a second naming scheme.
SCRIBBLE_ALIASES: dict[str, str] = {
    "circle": "scrawl-oval-wide",
    "oval": "scrawl-oval-wide",
    "circle-tight": "scrawl-oval-tight",
    "oval-tight": "scrawl-oval-tight",
    "underline": "underline-swipe",
    "cross-out": "strike-out",
    "strike": "strike-out",
    "strikethrough": "strike-out",
    "box": "box-scrawl",
    "bracket": "bracket-rows",
    "arrow": "arrow-elbow",
    "caret": "caret-note",
    "check": "tick-marks",
    "ticks": "tick-marks",
}


def parse_scribble_payload(payload: str) -> tuple[ScribbleStyle, str] | None:
    """`[SCRIBBLE: circle -> target]` -> (style, target). None if malformed
    or the style is unknown (caller logs + skips — never fatal).

    Spaces and underscores fold to hyphens, the way kit keys resolve: a writer
    typing `[SCRIBBLE: cross out -> …]` means the mark called `cross-out`, and
    losing the beat over the separator would be a silent nothing on screen.
    """
    if "->" not in payload:
        return None
    style_raw, target = payload.split("->", 1)
    style_raw = style_raw.strip().lower().replace(" ", "-").replace("_", "-")
    style_raw = SCRIBBLE_ALIASES.get(style_raw, style_raw)
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
    # Slot values written on the tag: `[PROP: crushed-flat = -41%]`. Keys are
    # slot names, `""` for a single unnamed value, `#N` for a positional one;
    # bound to the asset's real slots at render time.
    values: dict[str, str] = Field(default_factory=dict)


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


class MetricKind(str, Enum):
    """Whether a metric is measured OVER a period or AT a date.

    Revenue and net income accumulate across a year; shares outstanding and
    total debt are a reading taken on one day. Rendering them identically
    makes them indistinguishable, and the writer inherits the confusion —
    "revenue has flatlined for three years" under a row of five values that
    might be either.

    They do not share a row format. A FLOW row is a series under FY column
    headers. A STOCK row is one figure with the date it was taken.
    """

    FLOW = "flow"     # measured over a period: revenue, income, cash flow
    STOCK = "stock"   # measured at a date: shares out, debt, cash, book value


# Metrics whose name gives their kind away. The writer may state `kind`
# explicitly; this is what is inferred when they do not, so existing scripts
# keep working and get the right rendering anyway.
# Order matters: "free cash flow" contains "cash" and is emphatically a
# flow, so the flow words are checked first.
_FLOW_HINTS = ("revenue", "sales", "income", "profit", "loss", "margin",
               "ebitda", "eps", "flow", "capex", "opex", "spend", "buyback")
_STOCK_HINTS = ("shares", "share count", "debt", "cash", "book value",
                "equity", "assets", "inventory", "backlog", "headcount")


class NumberRow(BaseModel):
    """One metric row on the numbers sheet — MULTI-YEAR, oldest -> newest."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=40)
    values: list[str] = Field(min_length=2, max_length=6)
    # A period measure or a point-in-time one. Inferred from the label when
    # the script does not say, so nothing already written breaks.
    kind: MetricKind | None = None

    @property
    def measured(self) -> MetricKind:
        if self.kind is not None:
            return self.kind
        lab = self.label.lower()
        if any(h in lab for h in _FLOW_HINTS):
            return MetricKind.FLOW
        return (MetricKind.STOCK
                if any(h in lab for h in _STOCK_HINTS) else MetricKind.FLOW)

    @field_validator("values")
    @classmethod
    def _non_empty_values(cls, v: list[str]) -> list[str]:
        """An empty cell is allowed; an empty ROW is not.

        AN EMPTY CELL MEANS NO DATA, and that is information — a company with
        four years of history under a six-period header has two empty columns,
        and writing something in them would be inventing a figure. What is
        never meaningful is a row with no figures at all: that is a label with
        nothing after it, and it draws as a label with nothing after it.
        """
        cleaned = [x.strip() for x in v]
        if not any(cleaned):
            raise ValueError("values are all empty — a row with no figures is "
                             "a label with nothing after it")
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

    # SIX PERIODS, ALWAYS — four fiscal years, the last full year, LTM. Every
    # table and every time-series chart in the kit is authored six wide, and a
    # five-period script does not draw a narrower sheet: it draws a six-column
    # plate with LTM empty, which is the column the argument usually turns on.
    # Validated below rather than left to the renderer, because by then the
    # only evidence is a blank last column that looks like a design choice.

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
    # THE TURN: the one sentence the whole short pivots on, alone on the
    # frame at 9% of frame height. It has its own field because the shot has
    # its own slot in the template — under the form the writing prompt
    # becomes, every shot is a field and this is that shot's. Optional so
    # scripts written before the turn existed still parse; the renderer skips
    # the shot when it is absent rather than drawing an empty frame.
    turn_line: str | None = Field(default=None, max_length=120)
    # EARNINGS and MACRO fields. Optional so a plain SHORT still parses, and
    # so a script that fills none of them simply loses those shots rather
    # than rendering them empty. Under the form the writing prompt becomes,
    # each of these is one field of one shot.
    verdict: str | None = Field(default=None, max_length=60)      # the stamp
    guidance: str | None = Field(default=None, max_length=140)
    expected: str | None = Field(default=None, max_length=60)     # consensus
    reported: str | None = Field(default=None, max_length=60)     # the print
    mechanism: list[str] = Field(default_factory=list, max_length=3)
    consequences: list[str] = Field(default_factory=list, max_length=5)
    conclusion: str = Field(min_length=1, max_length=220)  # noise vs signal, free text

    @model_validator(mode="after")
    def _six_periods(self):
        """Every row is as wide as the header, and the header is six wide."""
        if self.years and len(self.years) != PERIOD_COUNT:
            raise ValueError(
                f"`years` has {len(self.years)} periods and every table and "
                f"time-series plate in the kit is authored for {PERIOD_COUNT} — "
                f"four fiscal years, the last full year and LTM. Dropping to "
                f"five drops LTM.")
        for row in self.numbers:
            if self.years and len(row.values) != len(self.years):
                raise ValueError(
                    f"row {row.label!r} has {len(row.values)} figures against "
                    f"{len(self.years)} period heads — a row that does not "
                    f"match its header puts every figure under the wrong year.")
        return self
    # The chart the short opens on, and holds from the stage open to the gut
    # check — one of the longest single holds in the video.
    #
    # The default was CLEAN, so unless a script asked otherwise every short
    # spent that hold on the machine-drawn card: a rounded rectangle, 1px
    # rules and a Gaussian glow, in a channel whose whole visual argument is
    # that a person drew this at three in the morning. MARKER is the house
    # language; CLEAN stays selectable for a script that wants precision.
    chart_style: ChartStyle = ChartStyle.MARKER
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

    def scribble_events(self) -> list[TagEvent]:
        return [e for e in self.inline_events if e.type is TagType.SCRIBBLE]

    def evidence_events(self) -> list[TagEvent]:
        """Inline tags that claim the frame — the short's own tag grammar.

        Ordered by position in the spoken text, which is the order they fire.
        """
        return [e for e in self.inline_events
                if e.type in SHORT_SEGMENT_TAG_TYPES]

    def delivery_events(self) -> list[TagEvent]:
        return [e for e in self.inline_events if e.type in DELIVERY_TAG_TYPES]

    def content_sha(self) -> str:
        return hashlib.sha256(
            self.model_dump_json().encode("utf-8")
        ).hexdigest()[:16]


# --------------------------------------------------------------------------
# LONG script — tagged narration with the Dennis tag grammar (§5).
# --------------------------------------------------------------------------


class Chapter(BaseModel):
    """A chapter: a generic TYPE, and a display title the director wrote.

    The type is one of the sixteen and decides which plates the chapter may
    use. The title is free text and is the ONLY thing that reaches the screen —
    a chapter opener is the room plate with this string in its title slot.

    A type may appear twice in one video under different titles ("the numbers"
    before guidance and again after it), so nothing keyed off a type may assume
    uniqueness, and there is no ordinal anywhere: the old kit baked "01"…"14"
    into the artwork, which is why a chapter could not be moved, repeated or cut
    without redrawing it.
    """

    model_config = ConfigDict(extra="forbid")

    type: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=64)
    start_s: float = Field(default=0.0, ge=0.0)

    @field_validator("type")
    @classmethod
    def _known_type(cls, v: str) -> str:
        from pipeline.plates import CHAPTER_TYPES
        t = v.strip().lower().replace(" ", "-").replace("_", "-")
        if t not in CHAPTER_TYPES:
            raise ValueError(
                f"{v!r} is not one of the sixteen chapter types: "
                + ", ".join(CHAPTER_TYPES))
        return t

    @field_validator("title")
    @classmethod
    def _clean_title(cls, v: str) -> str:
        return " ".join(v.split())


class ScriptConfession(BaseModel):
    """What this video admitted, declared rather than detected.

    The ledger's whole purpose is that the same admission cannot be reused, and
    that only works if the bot knows which sentences were the admission. Six
    kinds of confession, phrased six hundred ways, are not reliably findable in
    prose — so the writer names it in a trailer, the way they name the
    chapters. A video with nothing to confess writes no block, and the ledger
    records that too: "roughly one video in three" is a question about the
    videos that did not carry one.
    """

    model_config = ConfigDict(extra="forbid")

    kind: str
    text: str = Field(min_length=1, max_length=600)

    @field_validator("kind")
    @classmethod
    def _known_kind(cls, v: str) -> str:
        from pipeline.standing import CONFESSION_KINDS

        got = str(v or "").strip().lower().replace(" ", "-")
        if got not in CONFESSION_KINDS:
            raise ValueError(
                f"{v!r} is not one of the six kinds: "
                f"{', '.join(CONFESSION_KINDS)}")
        return got


class LongScript(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str = Field(min_length=1, max_length=15)
    narration: str = Field(min_length=1)  # clean, tag-free — goes to TTS
    events: list[TagEvent] = Field(default_factory=list)
    # The `=== CONFESSION ===` trailer, when the video carries one. Optional:
    # roughly one video in three does, and a mandatory confession is the rule
    # the bible deleted.
    confession: ScriptConfession | None = None
    # The `=== CHAPTERS ===` trailer, parsed: a type and a display title per
    # chapter. Metadata for YouTube AND the source of every on-screen chapter
    # title, so the two can no longer disagree — which they did, silently,
    # whenever the fallback list ran.
    chapter_list: list[Chapter] = Field(default_factory=list)
    # the raw trailer text, kept for the YouTube description
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
    TRAP_LINE = "trap_line"      # one clause of it, landing on its own figure
    CONCLUSION = "conclusion"
    HOST_CLOSE = "host_close"    # Dennis talking, after the payoff
    HOST_BEAT = "host_beat"      # Dennis returning mid-video, every 4-5 beats
    CUTAWAY = "cutaway"          # ironic broll cutaway (SHORT)
    # LONG visuals (MEME + SOUND are shared by both formats)
    MEME = "meme"
    CLIP = "clip"
    IMG = "img"
    CHART = "chart"
    FILING = "filing"
    ARTICLE = "article"          # a screenshot of the real article's headline
    SCREENGRAB = "screengrab"
    # One kind for every plate the director names. There is deliberately not a
    # kind per family: TERM/BIGNUM/TABLE/PROP were four kinds for four tags that
    # each let the renderer choose inside a family, and the choosing is what was
    # removed. A plate cue carries the plate's key and its slot values.
    PLATE = "plate"
    CHAPTER = "chapter"          # a chapter opener: the room, with a title
    SOUND = "sound"
    # hand-drawn overlays (both formats) — composited on top, no segment
    SCRIBBLE = "scribble"


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


# Fields the workbook holds as a FRACTION and a writer would otherwise read as a
# percentage. `Snapshot!D50`/`D51` are 0-1, the same convention `D49`
# short_interest uses, and `insider_own = 0.08` in a prompt is a line that comes
# back as "0.08% insider ownership" — a real number, off by a hundred, in a
# sentence that reads perfectly well.
#
# Only the two ownership fields are here. `fcf_yield`, `dividend_yield`,
# `debt_to_equity` and `short_interest` are fractions in the template too, but
# the committed fixture still carries them as percentages, so formatting them
# here would show a 100x error rather than fix one. That disagreement is real
# and is reported with this pack; it is not silently patched from this end.
_FRACTION_FIELDS = frozenset({"insider_own", "institutional_own"})


def _present(field: str, value):
    """One snapshot value as the writer should read it.

    A BLANK NEVER REACHES HERE — the caller drops it — and that is the point:
    ownership legitimately does not resolve for some tickers, and the chapter
    has to drop the line rather than say "0% insider ownership", which is a
    claim about the company rather than about the data.
    """
    if field in _FRACTION_FIELDS and isinstance(value, (int, float)):
        return f"{value * 100:.1f}% of shares outstanding (fraction {value:g})"
    return value


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
                f"{f} = {_present(f, self.values[f])}"
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
    # Full-resolution, real-fps, free-voice pass — the only way to see what a
    # video will actually LOOK like without buying a voice. Both formats have
    # one, because the SHORT is the daily-volume format and had no free
    # preview at all.
    RENDER_PROOF_SHORT = "render_proof_short"
    RENDER_PROOF_LONG = "render_proof_long"
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
    # Which chart the script actually asked for. The report used to state
    # "branded" unconditionally, so a script with "chart_style": "marker" —
    # the crude napkin chart — was shown a line describing the other one.
    chart_style: str = ChartStyle.CLEAN.value
    # LONG specifics
    visuals: list[VisualPlanItem] = Field(default_factory=list)
    filing_overlays: int = 0
    meme_count: int = 0
    meme_cap: int = 2
    est_runtime_min: float = 0.0   # estimated finished VIDEO length (min)
    est_render_minutes: float = 0.0  # estimated ffmpeg processing time (min)
    mtd_spend_usd: float = 0.0
    monthly_cap_usd: float = 0.0
    # How much of the 442-asset kit this script asks for. It lived only in
    # `kit_assets_used` in a render manifest nobody opens, so a short reaching
    # 17 assets and one beat-library scene went unremarked for months. The
    # approval screen is the last moment a thin script can be sent back, so
    # this is the moment to say it.
    kit_reach: str = ""
    warnings: list[str] = Field(default_factory=list)
    blocking: list[str] = Field(default_factory=list)
    script_sha: str = ""
    # Which subsystems produced invented data for this run. The report is the
    # artifact an operator reads before spending money and approving a render;
    # it has to say when the numbers in it are fixtures.
    mock_subsystems: list[str] = Field(default_factory=list)

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
        if self.mock_subsystems:
            joined = " + ".join(self.mock_subsystems)
            lines.append(
                f"⚠️ MOCK DATA — {joined} "
                f"{'are' if len(self.mock_subsystems) > 1 else 'is'} invented, "
                f"not real. Nothing below is a market observation.")
            lines.append("")
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
            # The approval screen is the one place in this system that has to
            # be true, so it reports the chart that was REQUESTED rather than
            # a hardcoded description of one of the two.
            chart = ("hand-drawn napkin" if self.chart_style == ChartStyle.MARKER.value
                     else "branded")
            lines.append(
                f"Chart: {chart}, from cached prices ✓   "
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
        if self.kit_reach:
            lines.append(self.kit_reach)
        lines.append(
            f"Est. render: ~{self.est_render_minutes:.0f} min   "
            f"MTD spend: ${self.mtd_spend_usd:.2f} / ${self.monthly_cap_usd:.2f} cap"
        )
        for w in self.warnings:
            lines.append(f"⚠️ {w}")
        for b in self.blocking:
            lines.append(f"⛔ {b}")
        return "\n".join(lines)
