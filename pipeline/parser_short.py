"""SHORT script parser: LLM output -> validated ShortScript (§4).

The master prompt demands raw JSON, but LLM output arrives dirty in
practice: code fences, prose around the object, smart quotes, trailing
commas. This parser is tolerant on *transport* and strict on *content* —
anything that survives extraction must validate against the pydantic
"Noise or signal?" schema and the character budget, or the whole script
is rejected with a message the operator can act on.
"""

from __future__ import annotations

import json
import re

from pydantic import ValidationError

from config import Settings
from pipeline.models import ShortScript

VENDOR_WORDS = ("refinitiv", "lseg", "eikon", "workspace.refinitiv")


class ScriptParseError(Exception):
    """Human-readable parse/validation failure (shown in Telegram)."""


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)

# best-effort typography normalization for broken LLM JSON
_QUOTE_MAP = str.maketrans({
    "“": '"', "”": '"', "„": '"', "«": '"', "»": '"',
    "‘": "'", "’": "'", "‚": "'",
    "–": "-", "—": "-", " ": " ",
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


def vendor_name_hits(script: ShortScript) -> list[str]:
    """Fields that leak the data vendor's name — hard-blocked (§3)."""
    hits: list[str] = []
    surfaces = {
        "hook_text": script.hook_text,
        "audio_script": script.audio_script,
        "move_summary": script.move_summary,
        "numbers_comment": script.numbers_comment,
        "conclusion": script.conclusion,
    }
    for i, h in enumerate(script.headlines):
        surfaces[f"headlines[{i}]"] = f"{h.text} {h.meaning}"
    for i, row in enumerate(script.numbers):
        surfaces[f"numbers[{i}]"] = f"{row.label} {' '.join(row.values)}"
    for name, text in surfaces.items():
        low = text.lower()
        if any(w in low for w in VENDOR_WORDS):
            hits.append(name)
    return hits


def parse_short_script(raw: str, settings: Settings) -> tuple[ShortScript, list[str]]:
    """Parse + validate. Returns (script, warnings). Raises ScriptParseError.

    The character budget is enforced HERE, before anything downstream can
    spend (parser rejects over-budget scripts before any spend).
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

    leaks = vendor_name_hits(script)
    if leaks:
        raise ScriptParseError(
            "The data vendor's name appears on-screen fields: "
            + ", ".join(leaks)
            + '. Data is "from the 10-K" — source unnamed. Fix and resend.'
        )

    warnings: list[str] = []
    for anchor in script.missing_anchor_words():
        warnings.append(
            f'anchor_word "{anchor}" not found in audio_script — the cue will '
            f"use a proportional fallback position"
        )
    if not 130 <= script.word_count <= 170:
        warnings.append(
            f"audio_script is {script.word_count} words (target ~140–165 for "
            f"55–60s) — pacing may be off"
        )
    year_counts = {len(row.values) for row in script.numbers}
    if script.years and max(year_counts) != len(script.years):
        warnings.append(
            f"years has {len(script.years)} labels but the widest numbers row "
            f"has {max(year_counts)} values — the sheet will align right"
        )
    if any(c < 3 for c in year_counts):
        warnings.append(
            "some numbers rows carry fewer than 3 years — direction is the "
            "point of the gut check"
        )
    return script, warnings
