"""LONG script parser: tagged narration -> LongScript (§5).

A real offset-aware tokenizer, not per-section regex hacks. One pass over
the text with `re.finditer`; every bracket tag is stripped from the clean
narration and its position recorded as an offset INTO THE CLEAN TEXT — the
exact string that goes to TTS, so timestamps and tag offsets share one
coordinate system.

The Dennis tag grammar:
    [PLATE: name | slot=value | …]    a plate from the kit, with its content
    [IMG: query] [PRODUCT: query]     real operations/product imagery
    [MEME: key]                       owned library first, capped per video
    [CLIP: query] / [BROLL: query]    ironic stock footage (vetted palette)
    [CHART: metric]                   a data path drawn into a charts/ plate
    [SHOW FILING: file.png]           unnamed-source data screenshot
    [SCREENGRAB: slug]                operator-supplied app/screen capture
    [SOUND: key]                      sfx palette
    [SCRIBBLE: mark -> target]        an annotations/ mark on a word or figure

Unknown tag *types* are logged, stripped and skipped — never fatal, and never
spoken.

The `=== CHAPTERS ===` trailer is `type | Display Title` per line. The type is
one of the sixteen and gates which plates the chapter may use; the title is free
text and is the only thing that reaches the screen.

There is no `=== ASSET PROMPTS ===` trailer any more. [ASSET] blocked a render
until an operator pasted a prompt into Claude Design, exported a PNG and
uploaded it — a bespoke asset per video does not scale to daily shorts, and the
whole point of the pivot is that the director picks from a library that already
exists.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Iterable

from config import Settings
from pipeline.models import (
    HISTORY_FIELDS,
    SFX_KEYS,
    VISUAL_TAG_TYPES,
    Chapter,
    LongScript,
    TagEvent,
    TagType,
    parse_scribble_payload,
)
from pipeline.plate_tags import build_fill, check_bound
from pipeline.plates import CHAPTER_TYPES, load_plates
from pipeline.tagging import parse_chart_payload, tokenize_tags

log = logging.getLogger(__name__)

VENDOR_WORDS = ("refinitiv", "lseg", "eikon")


class LongScriptError(Exception):
    """Fatal LONG script problem (shown in Telegram)."""


_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

# The write prompt appends a "=== CHAPTERS ===" trailer — `type | Title` per
# line, optionally with a leading mm:ss. Split off before tokenizing so it is
# never spoken. It is BOTH the YouTube chapter list and the source of every
# on-screen chapter title, so the two cannot disagree.
_CHAPTERS_TRAILER_RE = re.compile(r"^\s*=+\s*CHAPTERS\s*=+\s*$",
                                  re.IGNORECASE | re.MULTILINE)

# the Step-2 writing prompt emits a "=== HOOK OPTIONS ===" block, then the
# narration begins after its "Chosen:" line — strip that preamble so the
# hook menu is never spoken (symmetric to the ASSET PROMPTS trailer).
_HOOK_MARKER_RE = re.compile(r"^\s*=+\s*HOOK OPTIONS\s*=+\s*$",
                             re.IGNORECASE | re.MULTILINE)
_CHOSEN_RE = re.compile(r"^\s*chosen\b[^\n]*$", re.IGNORECASE | re.MULTILINE)


def _strip_hook_options(raw: str) -> str:
    m = _HOOK_MARKER_RE.search(raw)
    if not m:
        return raw
    chosen = _CHOSEN_RE.search(raw, m.end())
    cut = chosen.end() if chosen else m.end()
    return raw[cut:].lstrip("\n ")

# metrics [CHART: metric] may reference: the history sheet + the price feed
CHART_METRICS = tuple(HISTORY_FIELDS) + ("price",)


def normalize_slug(payload: str) -> str:
    return payload.strip().lower().replace(" ", "-")


def _split_chapters_trailer(raw: str) -> tuple[str, str]:
    """Cut the `=== CHAPTERS ===` trailer off the narration.

    Returns (body, chapters_text). The trailer is never spoken.
    """
    m = _CHAPTERS_TRAILER_RE.search(raw)
    if not m:
        return raw, ""
    return raw[: m.start()], raw[m.end():].strip()


# `[mm:ss] type | Display Title` — the timestamp is optional (YouTube wants it,
# the renderer does not: it lands a chapter on the nearest cut).
_CHAPTER_LINE_RE = re.compile(
    r"^\s*(?:(?P<ts>\d{1,2}:\d{2}(?::\d{2})?)\s+)?"
    r"(?P<type>[a-zA-Z][a-zA-Z -]*?)\s*\|\s*(?P<title>.+?)\s*$")


def parse_chapters(text: str) -> tuple[list[Chapter], list[str]]:
    """`type | Title` per line -> chapters. Returns (chapters, warnings).

    A chapter is a generic TYPE plus a display title, and that is the whole
    model. The type is one of the sixteen and decides which plates the chapter
    may reach for; the title is the only thing that reaches the screen.

    Nothing here dedupes. A type may legitimately appear twice in one video
    under different titles — "the numbers" before guidance and again after it —
    and the previous scheme could not express that, because the artwork carried
    a baked ordinal and the renderer keyed off the type as an identity.
    """
    chapters: list[Chapter] = []
    warnings: list[str] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        m = _CHAPTER_LINE_RE.match(line)
        if not m:
            warnings.append(
                f"chapter line {line!r} is not `type | Title` — skipped. The "
                f"sixteen types are {', '.join(CHAPTER_TYPES)}")
            continue
        start = 0.0
        if m.group("ts"):
            parts = [int(x) for x in m.group("ts").split(":")]
            while len(parts) < 3:
                parts.insert(0, 0)
            start = parts[0] * 3600 + parts[1] * 60 + parts[2]
        try:
            chapters.append(Chapter(type=m.group("type"), title=m.group("title"),
                                    start_s=start))
        except ValueError as exc:
            warnings.append(f"chapter {m.group('title')!r}: {exc}")
    return chapters, warnings


def parse_long_script(raw: str, ticker: str, settings: Settings) -> tuple[LongScript, list[str]]:
    """Tokenize tagged narration. Returns (script, warnings).

    Enforces the LONG character budget before anything can spend, and
    hard-rejects the data vendor's name (it would land in the captions).
    """
    if not raw or not raw.strip():
        raise LongScriptError("Empty message — expected the tagged LONG narration.")

    raw, chapters = _split_chapters_trailer(raw)
    raw = _strip_hook_options(raw)
    if not raw.strip():
        raise LongScriptError("Narration is empty (only a chapter trailer was sent).")

    narration, raw_tags, warnings = tokenize_tags(raw)
    for w in warnings:
        log.warning("long tokenize: %s", w)

    events: list[TagEvent] = []
    for rt in raw_tags:
        payload = rt.payload
        style = ""
        values: dict[str, str] = {}
        if rt.type is TagType.PLATE:
            # The tag carries its own content. Resolution and slot-filling
            # happen here so a bad plate name or a mis-sized row is caught at
            # parse time, not discovered as a blank rectangle in the cut.
            # `values` is slot -> text, and the renderer does nothing but place
            # it: it never picks the plate and never computes a figure.
            fill = build_fill(load_plates(settings.assets_dir), payload)
            payload = fill.key or fill.name
            values = fill.values
            warnings.extend(fill.warnings)
            if not fill.ok:
                warnings.extend(fill.problems)
                continue
        if rt.type is TagType.SCREENGRAB:
            slug = normalize_slug(payload)
            if not _SLUG_RE.match(slug):
                warnings.append(f'{rt.type.value.lower()} slug "{payload}" is not '
                                f"kebab-case — tag skipped")
                continue
            payload = slug
        elif rt.type is TagType.CHART:
            payload, style = parse_chart_payload(payload)
        elif rt.type is TagType.SCRIBBLE:
            parsed = parse_scribble_payload(payload)
            if parsed is None:
                warnings.append(f'scribble "{payload}" is malformed (use '
                                f'"circle|arrow|underline -> target") — skipped')
                continue
        events.append(TagEvent(
            type=rt.type, payload=payload, values=values,
            char_offset=rt.char_offset, raw_offset=rt.raw_offset, style=style,
        ))

    if not narration.strip():
        raise LongScriptError("Narration is empty after stripping tags.")

    low = narration.lower()
    if any(w in low for w in VENDOR_WORDS):
        raise LongScriptError(
            "The narration names the data vendor — it would be spoken and land "
            'in the captions. Data is "from the 10-K"; source stays unnamed.'
        )

    budget = settings.max_chars("long")
    if len(narration) > budget:
        raise LongScriptError(
            f"Narration is {len(narration)} chars — over the LONG budget of "
            f"{budget}. Trim and resend (no TTS was called)."
        )

    chapter_list, chapter_warnings = parse_chapters(chapters)
    warnings.extend(chapter_warnings)
    if not chapter_list:
        warnings.append(
            "the script has no usable `=== CHAPTERS ===` trailer — every "
            "chapter opener will be missing its title, and the openers are the "
            "only place a title appears on screen")

    script = LongScript(ticker=ticker, narration=narration, events=events,
                        chapter_list=chapter_list, chapters=chapters)

    if script.word_count < 800:
        warnings.append(
            f"narration is only {script.word_count} words — thin even for the "
            f"shortest LONG cut (a clean thesis is ~1600 words / ~12 min; length "
            f"scales up with the chapters the story earns)"
        )
    if not script.events_of(TagType.PLATE, TagType.CLIP, TagType.BROLL,
                            TagType.IMG, TagType.PRODUCT, TagType.CHART):
        warnings.append("no visual tags found — the video will be mostly filler")
    return script, warnings


# TAGGING DENSITY — three to five tagged visuals a minute.
#
# The reference long script is 35 minutes with about 35 tagged visuals: one a
# minute, which is a talking head with occasional pictures. The target is three
# to five, and it is a WARNING rather than a blocker because density is a
# judgement about a specific argument — some passages earn a long hold — and a
# gate that blocks on it would be gamed with filler tags within a week.
#
# It names the thin CHAPTERS rather than reporting one number for the video,
# because "you are at 1.4 per minute" is not actionable and "how-we-got-here
# has two visuals in six minutes" is.
DENSITY_FLOOR_PER_MIN = 3.0
DENSITY_TARGET_PER_MIN = 5.0


def density_warnings(script: LongScript, settings: Settings) -> list[str]:
    """Chapters carrying fewer than the floor of tagged visuals a minute."""
    visuals = [e for e in script.events if e.type in VISUAL_TAG_TYPES]
    words = script.word_count
    if not words:
        return []
    # The narration has not been spoken yet, so runtime is estimated from the
    # words-per-second the TTS mock and the real voice agree on closely enough
    # for a density check.
    duration = words / max(settings.mock_wps_long, 0.1)
    if duration < 60:
        return []

    out: list[str] = []
    rate = len(visuals) / (duration / 60.0)
    if rate < DENSITY_FLOOR_PER_MIN:
        out.append(
            f"tagging density is {rate:.1f} visuals a minute across "
            f"{duration / 60:.0f} minutes — the target is "
            f"{DENSITY_FLOOR_PER_MIN:.0f}–{DENSITY_TARGET_PER_MIN:.0f}. At this "
            f"rate the cut is a talking head with occasional pictures.")

    # Per chapter, by character offset. Chapter boundaries are timestamps and
    # tags are offsets, so this maps them through the narration's own length —
    # approximate on purpose, and a warning for exactly that reason.
    chapters = script.chapter_list
    if len(chapters) < 2 or not chapters[-1].start_s:
        return out
    span = chapters[-1].start_s or duration
    for i, ch in enumerate(chapters):
        start_s = ch.start_s
        end_s = chapters[i + 1].start_s if i + 1 < len(chapters) else duration
        if end_s - start_s < 60:
            continue
        lo = int(len(script.narration) * (start_s / max(span, 1e-6)))
        hi = int(len(script.narration) * (end_s / max(span, 1e-6)))
        n = sum(1 for e in visuals if lo <= e.char_offset < hi)
        mins = (end_s - start_s) / 60.0
        if n / mins < DENSITY_FLOOR_PER_MIN:
            out.append(
                f'chapter "{ch.title}" ({ch.type}) has {n} tagged visual'
                f'{"" if n == 1 else "s"} across {mins:.0f} minutes '
                f"({n / mins:.1f}/min) — below the floor of "
                f"{DENSITY_FLOOR_PER_MIN:.0f}")
    return out


def validate_long_script(
    script: LongScript,
    palette_keys: Iterable[str],
    workspace: Path,
    settings: Settings,
    data_metrics: Iterable[str] | None = None,
) -> tuple[list[str], list[str]]:
    """Validate every payload against the palette / workspace / libraries.

    Returns (warnings, blocking). Blocking issues stop the approval flow;
    warnings degrade gracefully at render time:
      CLIP/BROLL key not in palette   -> warning (fetched as a raw query)
      SHOW FILING file missing        -> BLOCKING (mid-render discovery is a bug)
      SOUND key unknown               -> warning (skipped)
      MEME count over the cap         -> BLOCKING (information-first, 1–2 max)
      MEME key not in owned library   -> warning (fallback providers / filler)
      CHART metric unknown            -> warning (skipped)
      SCRIBBLE mark not in the kit     -> warning (skipped at render)
      SCREENGRAB file missing         -> BLOCKING (operator drops it in custom/)
      PLATE unknown / slot undeclared -> BLOCKING (it would draw an empty box)
      tagging density below the floor -> warning, naming the thin chapters
      tag with no CueKind             -> BLOCKING if nothing decided it draws
                                         nothing; warning if it did

    That last one runs HERE, and not at render time, on purpose. Whether a tag
    resolves to a cue is a pure function of the script, but build_long_timeline
    runs after the paid TTS call — so a tag it could not place used to spend
    the money first and then abort the render. Approval is the last point where
    catching it is free.
    """
    from pipeline.timeline import unrenderable_long_tags
    from pipeline.memes import MemeLibrary

    palette = set(palette_keys)
    present_metrics = set(data_metrics) if data_metrics is not None else None
    meme_lib = MemeLibrary(settings)
    warnings: list[str] = []
    blocking: list[str] = []

    meme_count = script.meme_count()
    if meme_count > settings.meme_max_per_long:
        blocking.append(
            f"{meme_count} [MEME] tags — the cap is {settings.meme_max_per_long} "
            f"per LONG (information-first, not meme-spam). Cut some."
        )

    custom_dir = settings.assets_dir / "custom"
    reg = load_plates(settings.assets_dir)

    # Which chapter each tag falls in, so a plate can be checked against the
    # TYPE that is allowed to use it. Chapters carry timestamps, tags carry
    # character offsets, so the mapping is by position in the narration —
    # approximate, and a warning rather than a block for exactly that reason.
    for e in script.events:
        if e.type in (TagType.CLIP, TagType.BROLL):
            if e.payload not in palette:
                warnings.append(
                    f'clip "{e.payload}" not in the vetted palette — will fetch '
                    f"it as a raw query (filler if that fails)"
                )
        elif e.type is TagType.SHOW_FILING:
            if not (workspace / e.payload).exists():
                blocking.append(
                    f'screenshot "{e.payload}" not found in the workspace — '
                    f"upload it or remove the tag"
                )
        elif e.type is TagType.SOUND:
            if e.payload not in SFX_KEYS:
                warnings.append(f'sound "{e.payload}" not in the sfx library — skipped')
        elif e.type is TagType.MEME:
            if meme_lib.match(e.payload) is None:
                warnings.append(
                    f'meme "{e.payload}" not in the owned library — will try '
                    f"fallback providers (filler if none configured)"
                )
        elif e.type is TagType.CHART:
            if e.payload not in CHART_METRICS:
                warnings.append(
                    f'chart metric "{e.payload}" unknown (use one of: '
                    f'{", ".join(CHART_METRICS)}) — skipped'
                )
            elif present_metrics is not None and e.payload not in present_metrics:
                warnings.append(
                    f'chart metric "{e.payload}" has no multi-year series in this '
                    f"data — the chart will fall back to a filler card"
                )
        elif e.type is TagType.PLATE:
            # Re-checked here because approval is the last point at which a bad
            # plate costs nothing — but against the BOUND values, not the raw
            # payload. The parser has already replaced the payload with the
            # registry key, so re-parsing finds a name with no assignments.
            fill = check_bound(reg, e.payload, e.values)
            blocking.extend(fill.problems)
            warnings.extend(fill.warnings)
        elif e.type is TagType.SCRIBBLE:
            parsed = parse_scribble_payload(e.payload)
            if parsed is not None and f"annotations/{parsed[0].value}" not in reg:
                warnings.append(
                    f'[SCRIBBLE: {parsed[0].value}] is not a mark in the kit — '
                    f"skipped at render")
        elif e.type is TagType.SCREENGRAB:
            hits = list(custom_dir.glob(f"{e.payload}.*")) if custom_dir.is_dir() else []
            if not hits:
                blocking.append(
                    f'[SCREENGRAB: {e.payload}] has no file at '
                    f'assets/custom/{e.payload}.* — drop the screenshot or short '
                    f'screen-record there (or upload it in chat named {e.payload}).'
                )

    warnings.extend(density_warnings(script, settings))

    for e, reason in unrenderable_long_tags(script):
        where = f"char {e.char_offset}"
        if reason:
            # decided: the renderer will skip it, and the operator is told so
            # rather than finding a missing visual in the finished cut.
            warnings.append(f"[{e.type.value}] at {where} — {reason}")
        else:
            # nobody decided anything about this tag. It reaches the timeline,
            # draws nothing, and no one signed off on that.
            blocking.append(
                f"[{e.type.value}] at {where} has no visual on the LONG "
                f"timeline and no recorded reason for it. Map it in "
                f"_TAG_TO_KIND or record why it draws nothing in "
                f"_LONG_NO_CUE_REASONS (pipeline/timeline.py); until then the "
                f"tag would be dropped from the render in silence."
            )
    return warnings, blocking
