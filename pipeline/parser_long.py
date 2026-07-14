"""LONG script parser: tagged narration -> LongScript (§5).

A real offset-aware tokenizer, not per-section regex hacks. One pass over
the text with `re.finditer`; every bracket tag is stripped from the clean
narration and its position recorded as an offset INTO THE CLEAN TEXT — the
exact string that goes to TTS, so timestamps and tag offsets share one
coordinate system.

The Dennis tag grammar:
    [IMG: query] [PRODUCT: query]     real operations/product imagery
    [MEME: key]                       owned library first, capped per video
    [CLIP: query] / [BROLL: query]    ironic stock footage (vetted palette)
    [CHART: metric style=marker]      auto chart; clean (default) or marker
    [SHOW FILING: file.png]           unnamed-source data screenshot
    [SCREENGRAB: slug]                operator-supplied app/screen capture
    [SOUND: key]                      sfx palette
    [ASSET: slug]                     bespoke Claude-Design asset
    [DOODLE: key]                     crude hand-drawn overlay (owned)
    [SCRIBBLE: circle|arrow|underline -> target]   drawn annotation on a point

Unknown tag *types* ([CAMERA: ...] — or the retired [STAMP: ...]) are
logged, stripped and skipped — never fatal, and never spoken.

The director may append ready-to-paste Claude Design prompts after an
`=== ASSET PROMPTS ===` line; that trailer is split off BEFORE tokenizing
(so it is never spoken) and stored on the script keyed by slug.
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
    LongScript,
    TagEvent,
    TagType,
    parse_scribble_payload,
)
from pipeline.tagging import parse_chart_payload, tokenize_tags

log = logging.getLogger(__name__)

VENDOR_WORDS = ("refinitiv", "lseg", "eikon")


class LongScriptError(Exception):
    """Fatal LONG script problem (shown in Telegram)."""


_ASSET_TRAILER_RE = re.compile(r"^\s*=+\s*ASSET PROMPTS\s*=+\s*$",
                               re.IGNORECASE | re.MULTILINE)
_ASSET_BLOCK_RE = re.compile(r"^---\s*ASSET:\s*([^-\s][^\n]*?)\s*---\s*$",
                             re.IGNORECASE | re.MULTILINE)
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

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


def _split_asset_trailer(raw: str) -> tuple[str, dict[str, str]]:
    """Cut the `=== ASSET PROMPTS ===` trailer off the narration and parse
    it into {slug: prompt}."""
    m = _ASSET_TRAILER_RE.search(raw)
    if not m:
        return raw, {}
    body, trailer = raw[: m.start()], raw[m.end():]
    prompts: dict[str, str] = {}
    blocks = list(_ASSET_BLOCK_RE.finditer(trailer))
    for i, bm in enumerate(blocks):
        slug = normalize_slug(bm.group(1))
        end = blocks[i + 1].start() if i + 1 < len(blocks) else len(trailer)
        prompt = trailer[bm.end():end].strip()
        if slug and prompt:
            prompts[slug] = prompt
    return body, prompts


def parse_long_script(raw: str, ticker: str, settings: Settings) -> tuple[LongScript, list[str]]:
    """Tokenize tagged narration. Returns (script, warnings).

    Enforces the LONG character budget before anything can spend, and
    hard-rejects the data vendor's name (it would land in the captions).
    """
    if not raw or not raw.strip():
        raise LongScriptError("Empty message — expected the tagged LONG narration.")

    raw, asset_prompts = _split_asset_trailer(raw)
    raw = _strip_hook_options(raw)
    if not raw.strip():
        raise LongScriptError("Narration is empty (only an asset-prompt trailer was sent).")

    narration, raw_tags, warnings = tokenize_tags(raw)
    for w in warnings:
        log.warning("long tokenize: %s", w)

    events: list[TagEvent] = []
    for rt in raw_tags:
        payload = rt.payload
        style = ""
        if rt.type in (TagType.ASSET, TagType.SCREENGRAB):
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
            type=rt.type, payload=payload,
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

    script = LongScript(ticker=ticker, narration=narration, events=events,
                        asset_prompts=asset_prompts)

    if script.word_count < 800:
        warnings.append(
            f"narration is only {script.word_count} words — short for the LONG "
            f"format (target ~1600–2200)"
        )
    if not script.events_of(TagType.CLIP, TagType.BROLL, TagType.IMG,
                            TagType.PRODUCT, TagType.CHART):
        warnings.append("no visual tags found — the video will be mostly filler")
    orphan_prompts = set(asset_prompts) - set(script.asset_slugs())
    for slug in sorted(orphan_prompts):
        warnings.append(f'asset prompt "{slug}" has no matching [ASSET: {slug}] tag')
    return script, warnings


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
      DOODLE key not in owned library -> warning (skipped at render)
      SCREENGRAB file missing         -> BLOCKING (operator drops it in custom/)
      ASSET file missing              -> BLOCKING until the operator pastes the
                                         appended prompt into Claude Design and
                                         drops the export at assets/custom/<slug>
    """
    from pipeline.doodles import DoodleLibrary
    from pipeline.memes import MemeLibrary

    palette = set(palette_keys)
    present_metrics = set(data_metrics) if data_metrics is not None else None
    meme_lib = MemeLibrary(settings)
    doodle_lib = DoodleLibrary(settings)
    warnings: list[str] = []
    blocking: list[str] = []

    meme_count = script.meme_count()
    if meme_count > settings.meme_max_per_long:
        blocking.append(
            f"{meme_count} [MEME] tags — the cap is {settings.meme_max_per_long} "
            f"per LONG (information-first, not meme-spam). Cut some."
        )

    custom_dir = settings.assets_dir / "custom"
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
        elif e.type is TagType.DOODLE:
            if doodle_lib.match(e.payload) is None:
                warnings.append(
                    f'doodle "{e.payload}" not in the owned library — skipped at render'
                )
        elif e.type is TagType.SCREENGRAB:
            hits = list(custom_dir.glob(f"{e.payload}.*")) if custom_dir.is_dir() else []
            if not hits:
                blocking.append(
                    f'[SCREENGRAB: {e.payload}] has no file at '
                    f'assets/custom/{e.payload}.* — drop the screenshot or short '
                    f'screen-record there (or upload it in chat named {e.payload}).'
                )
        elif e.type is TagType.ASSET:
            hits = list(custom_dir.glob(f"{e.payload}.*")) if custom_dir.is_dir() else []
            if not hits:
                hint = (" Its Claude Design prompt was appended to the script — "
                        "paste it into Claude Design, export, and upload the file."
                        if e.payload in script.asset_prompts else
                        " No prompt was appended for it — ask the director run for one.")
                blocking.append(
                    f'[ASSET: {e.payload}] has no file at assets/custom/{e.payload}.*'
                    f' — render is blocked until it exists.{hint}'
                )
    return warnings, blocking
