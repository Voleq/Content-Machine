"""SHORT script parser: LLM output -> validated ShortScript (§5.2).

The master prompt demands raw JSON, but LLM output arrives dirty in
practice: code fences, prose around the object, smart quotes, trailing
commas. This parser is tolerant on *transport* and strict on *content* —
anything that survives extraction must validate against the pydantic
model and the character budget, or the whole script is rejected with a
message the operator can act on.
"""

from __future__ import annotations

import json
import re

from pydantic import ValidationError

from config import Settings
from pipeline.models import ShortScript


class ScriptParseError(Exception):
    """Human-readable parse/validation failure (shown in Telegram)."""


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)

# best-effort typography normalization for broken LLM JSON
_QUOTE_MAP = str.maketrans({
    "“": '"', "”": '"', "„": '"', "«": '"', "»": '"',
    "‘": "'", "’": "'", "‚": "'",
    "–": "-", "—": "-", " ": " ",
})

_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")


def _extract_json_block(raw: str) -> str:
    """Pull the JSON object out of fences/prose. Raises if none found."""
    raw = raw.strip()
    if not raw:
        raise ScriptParseError("Empty message — expected the SHORT script JSON.")

    fenced = _FENCE_RE.search(raw)
    if fenced:
        raw = fenced.group(1).strip()

    start = raw.find("{")
    if start == -1:
        raise ScriptParseError("No JSON object found in the message.")

    # balanced-brace scan, string-aware
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(raw)):
        ch = raw[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return raw[start : i + 1]
    raise ScriptParseError("JSON object is not closed (unbalanced braces).")


def _loads_tolerant(block: str) -> dict:
    attempts = [
        block,
        block.translate(_QUOTE_MAP),
        _TRAILING_COMMA_RE.sub(r"\1", block.translate(_QUOTE_MAP)),
    ]
    last_err: Exception | None = None
    for attempt in attempts:
        try:
            data = json.loads(attempt)
            if not isinstance(data, dict):
                raise ScriptParseError("Top-level JSON must be an object.")
            return data
        except json.JSONDecodeError as e:  # try the next normalization
            last_err = e
    raise ScriptParseError(f"Invalid JSON: {last_err}")


def _friendly_validation_error(err: ValidationError) -> str:
    parts = []
    for e in err.errors():
        loc = ".".join(str(p) for p in e["loc"]) or "(root)"
        parts.append(f"{loc}: {e['msg']}")
    return "Schema validation failed:\n" + "\n".join(f"  • {p}" for p in parts)


def parse_short_script(raw: str, settings: Settings) -> tuple[ShortScript, list[str]]:
    """Parse + validate. Returns (script, warnings). Raises ScriptParseError.

    The character budget is enforced HERE, before anything downstream can
    spend (§8.1: parser rejects over-budget scripts before any spend).
    """
    block = _extract_json_block(raw)
    data = _loads_tolerant(block)

    try:
        script = ShortScript.model_validate(data)
    except ValidationError as err:
        raise ScriptParseError(_friendly_validation_error(err)) from err

    budget = settings.max_chars("short")
    if script.char_count > budget:
        raise ScriptParseError(
            f"audio_script is {script.char_count} chars — over the SHORT budget "
            f"of {budget}. Trim the script and resend (no TTS was called)."
        )

    warnings: list[str] = []
    for anchor in script.missing_anchor_words():
        warnings.append(
            f'anchor_word "{anchor}" not found in audio_script — highlight will '
            f"use a proportional fallback position"
        )
    if not 140 <= script.word_count <= 160:
        warnings.append(
            f"audio_script is {script.word_count} words (target 140–160) — "
            f"pacing may be off"
        )
    if len(script.data_block) > 8:
        warnings.append(
            f"data_block has {len(script.data_block)} lines (template targets 4–8)"
        )
    return script, warnings
