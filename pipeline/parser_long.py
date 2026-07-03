"""LONG script parser: tagged narration -> LongScript (§5.3).

A real offset-aware tokenizer, not per-section regex hacks. One pass over
the text with `re.finditer`; every bracket tag is stripped from the clean
narration and its position recorded as an offset INTO THE CLEAN TEXT — the
exact string that goes to TTS, so timestamps and tag offsets share one
coordinate system.

Unknown tag *types* ([CAMERA: ...]) are logged, stripped and skipped —
never fatal, and never spoken. Unknown payloads are the validator's job:
missing screenshots block, unknown b-roll keys fall back, unknown sounds
and stamp labels are skipped with a warning.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Iterable

from config import Settings
from pipeline.models import SFX_KEYS, LongScript, TagEvent, TagType, Verdict

log = logging.getLogger(__name__)


class LongScriptError(Exception):
    """Fatal LONG script problem (shown in Telegram)."""


# The §5.3 grammar. A broader net first so unknown tag types are stripped
# rather than spoken by the TTS voice.
_ANY_TAG_RE = re.compile(r"\[([A-Z][A-Z -]*?):\s*([^\]\n]+)\]")
_KNOWN_TYPES = {t.value: t for t in TagType}


def parse_long_script(raw: str, ticker: str, settings: Settings) -> tuple[LongScript, list[str]]:
    """Tokenize tagged narration. Returns (script, warnings).

    Enforces the LONG character budget before anything can spend.
    """
    if not raw or not raw.strip():
        raise LongScriptError("Empty message — expected the tagged LONG narration.")

    warnings: list[str] = []
    clean_parts: list[str] = []
    clean_len = 0
    events: list[TagEvent] = []
    last = 0

    for m in _ANY_TAG_RE.finditer(raw):
        segment = raw[last:m.start()]
        clean_parts.append(segment)
        clean_len += len(segment)
        last = m.end()

        type_str = m.group(1).strip()
        payload = m.group(2).strip()
        tag_type = _KNOWN_TYPES.get(type_str)
        if tag_type is None:
            warnings.append(f"unknown tag [{type_str}: {payload}] at char {m.start()} — skipped")
            log.warning("unknown tag type %r skipped", type_str)
            continue
        events.append(
            TagEvent(
                type=tag_type,
                payload=payload,
                char_offset=clean_len,
                raw_offset=m.start(),
            )
        )

    clean_parts.append(raw[last:])
    narration = "".join(clean_parts)

    if not narration.strip():
        raise LongScriptError("Narration is empty after stripping tags.")

    budget = settings.max_chars("long")
    if len(narration) > budget:
        raise LongScriptError(
            f"Narration is {len(narration)} chars — over the LONG budget of "
            f"{budget}. Trim and resend (no TTS was called)."
        )

    script = LongScript(ticker=ticker, narration=narration, events=events)

    if script.word_count < 300:
        warnings.append(
            f"narration is only {script.word_count} words — short for the LONG "
            f"format (target ~1600–2200)"
        )
    if not script.events_of(TagType.BROLL):
        warnings.append("no [B-ROLL] tags found — the video will be mostly desk filler")
    if not script.events_of(TagType.STAMP):
        warnings.append("no [STAMP] tag found — the video will end without a verdict stamp")
    return script, warnings


def validate_long_script(
    script: LongScript,
    palette_keys: Iterable[str],
    workspace: Path,
    settings: Settings,
) -> tuple[list[str], list[str]]:
    """Validate every payload against the palette / workspace / sfx library.

    Returns (warnings, blocking). Blocking issues stop the approval flow;
    warnings degrade gracefully at render time (§5.3):
      B-ROLL key not in palette      -> warning (generic filler at render)
      SHOW REFINITIV file missing    -> BLOCKING (discovering it mid-render is a bug)
      SOUND key unknown              -> warning (skipped)
      STAMP label not in the enum    -> warning (skipped)
    """
    palette = set(palette_keys)
    warnings: list[str] = []
    blocking: list[str] = []

    for e in script.events:
        if e.type is TagType.BROLL:
            if e.payload not in palette:
                warnings.append(
                    f'b-roll key "{e.payload}" not in the vetted palette — '
                    f"generic filler will be used"
                )
        elif e.type is TagType.SHOW_REFINITIV:
            if not (workspace / e.payload).exists():
                blocking.append(
                    f'screenshot "{e.payload}" not found in the workspace — '
                    f"upload it or remove the tag"
                )
        elif e.type is TagType.SOUND:
            if e.payload not in SFX_KEYS:
                warnings.append(f'sound "{e.payload}" not in the sfx library — skipped')
        elif e.type is TagType.STAMP:
            if e.payload not in Verdict.__members__:
                warnings.append(f'stamp label "{e.payload}" not in the verdict enum — skipped')
    return warnings, blocking
