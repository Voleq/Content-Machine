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

import logging

from pydantic import ValidationError

from config import Settings
from pipeline.models import (
    DELIVERY_TAG_TYPES,
    SELF_RESOLVING_TAG_TYPES,
    SHORT_TAG_TYPES,
    ShortScript,
    TagEvent,
    TagType,
    parse_scribble_payload,
)
from pipeline.tagging import parse_chart_payload, parse_slot_values
from pipeline.tagging import tokenize_tags

log = logging.getLogger(__name__)

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


def _balanced_objects(raw: str) -> list[str]:
    """Every top-level balanced {...} span, string-aware."""
    spans: list[str] = []
    depth = 0
    start = -1
    in_string = False
    escape = False
    for i, ch in enumerate(raw):
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
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0:
                spans.append(raw[start : i + 1])
    return spans


def _extract_json_block(raw: str) -> str:
    """Pull the SHORT script object out of fences/prose.

    The SHORT prompt asks the model to show its work IN ORDER (angle +
    numbers, hook options, script, tags) and THEN emit the JSON, so a
    preamble — even one with stray braces — may precede the real object.
    Prefer the last balanced object that carries the script's `"format"`
    key; fall back to the first balanced object (single-object case)."""
    raw = raw.strip()
    if not raw:
        raise ScriptParseError("Empty message — expected the SHORT script JSON.")

    fenced = _FENCE_RE.search(raw)
    if fenced:
        raw = fenced.group(1).strip()

    objects = _balanced_objects(raw)
    if not objects:
        if "{" not in raw:
            raise ScriptParseError("No JSON object found in the message.")
        raise ScriptParseError("JSON object is not closed (unbalanced braces).")
    tagged = [o for o in objects if '"format"' in o]
    return (tagged[-1] if tagged else objects[0])


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


def _tag_warnings(script: ShortScript, settings: Settings) -> list[str]:
    """What the short's inline tags will and won't reach at render time.

    Kit keys are checked here rather than discovered mid-render, and the
    absence of delivery direction is called out: a script with none reads
    exactly like a script whose [BEAT]s were silently dropped, and for two
    years it was the second one.
    """
    from pipeline.kit import load_kit
    from pipeline.models import KIT_TAG_FAMILIES, KIT_TAG_BLANKS

    out: list[str] = []
    kit = load_kit(settings.assets_dir)
    for e in script.inline_events:
        families = KIT_TAG_FAMILIES.get(e.type)
        if not families or not len(kit):
            continue
        if kit.resolve(families, e.payload) is not None:
            continue
        blank = KIT_TAG_BLANKS.get(e.type)
        if blank and blank in kit:
            out.append(
                f'[{e.type.value}: {e.payload}] has no named artwork — the '
                f'blank layout will be filled with your text instead')
        else:
            options = ", ".join(
                n.rsplit("/", 1)[-1]
                for fam in families for n in kit.family(fam)[:6])
            out.append(
                f'[{e.type.value}: {e.payload}] is not in '
                f'{" / ".join(families)} — the beat will be skipped. '
                f"Available: {options}…")

    if not script.delivery_events():
        out.append(
            "no delivery direction in the script — [BEAT]/[SIGH]/[FLAT]/[DRY] "
            "are what make the deadpan land, and four or five across a short "
            "is the budget. Without them TTS reads it evenly.")
    return out


def parse_short_script(raw: str, settings: Settings) -> tuple[ShortScript, list[str]]:
    """Parse + validate. Returns (script, warnings). Raises ScriptParseError.

    The character budget is enforced HERE, before anything downstream can
    spend (parser rejects over-budget scripts before any spend).
    """
    block = _extract_json_block(raw)
    data = _loads_tolerant(block)

    # Strip the inline tags out of audio_script BEFORE validation: the clean
    # text is what TTS speaks and what the budget is measured against; the
    # events are word-anchored into that clean text.
    #
    # The allowed set is the SHORT's full grammar now. It used to be three
    # tags, which had two consequences worth naming: the evidence tags the
    # prompt showed the writer were stripped with a warning nobody read, and
    # [BEAT]/[FLAT]/[SIGH]/[DRY] — documented in the prompt as the thing that
    # makes the delivery land — were dropped on the floor, so TTS received
    # unpunctuated text and every short came out flat.
    inline_warnings: list[str] = []
    if isinstance(data.get("audio_script"), str):
        clean, raw_tags, tok_warnings = tokenize_tags(
            data["audio_script"], allowed=SHORT_TAG_TYPES
        )
        inline_warnings.extend(tok_warnings)
        events: list[dict] = []
        for rt in raw_tags:
            if rt.type is TagType.SCRIBBLE and parse_scribble_payload(rt.payload) is None:
                inline_warnings.append(
                    f'scribble "{rt.payload}" is malformed (use '
                    f'"circle|arrow|underline -> target") — skipped'
                )
                continue
            payload, style, values = rt.payload, "", {}
            if rt.type not in DELIVERY_TAG_TYPES:
                payload, style = parse_chart_payload(rt.payload)
                # `= value` binds the asset's text slots. Without it, named
                # artwork renders with every box empty — Dennis crushed under
                # a blank rectangle — and 74 slots stay unreachable.
                payload, values = parse_slot_values(payload)
            if (rt.type not in DELIVERY_TAG_TYPES
                    and rt.type not in SELF_RESOLVING_TAG_TYPES
                    and not payload):
                inline_warnings.append(
                    f"[{rt.type.value}] at char {rt.char_offset} carries no "
                    f"key — skipped")
                continue
            events.append(TagEvent(
                type=rt.type, payload=payload, style=style, values=values,
                char_offset=rt.char_offset, raw_offset=rt.raw_offset,
            ).model_dump())
        data["audio_script"] = clean
        data["inline_events"] = events

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

    warnings: list[str] = list(inline_warnings)
    warnings.extend(_tag_warnings(script, settings))
    for anchor in script.missing_anchor_words():
        warnings.append(
            f'anchor_word "{anchor}" not found in audio_script — the cue will '
            f"use a proportional fallback position"
        )
    if not 170 <= script.word_count <= 220:
        warnings.append(
            f"audio_script is {script.word_count} words (target ~180–210 for "
            f"60–75s) — pacing may be off"
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
