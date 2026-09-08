"""Shared offset-aware tag tokenizer for both script formats.

One pass over the text with `re.finditer`; every bracket tag is stripped
and its position recorded as an offset INTO THE CLEAN TEXT — the exact
string that goes to TTS, so word timestamps and tag offsets share one
coordinate system. The LONG parser tokenizes its whole narration; the
SHORT parser tokenizes only the `audio_script` and restricts the allowed
tags to the overlay set ([DOODLE]/[SCRIBBLE]).

Unknown tag *types* are logged, stripped and skipped — never fatal, never
spoken. Payload-level validation is the caller's job.

The one piece of payload GRAMMAR that lives here is the `|` field split —
`[CLIP: lebron three pointer | hold=2.5]` — because two tags now want it and
`[PLATE]` already had its own. What a field means is still the caller's.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from pipeline.models import TagType

# A broad net so unknown tag types are stripped rather than spoken. The
# payload is optional: delivery directives ([BEAT], [SIGH]) carry none.
_ANY_TAG_RE = re.compile(r"\[([A-Z][A-Z -]*?)(?::\s*([^\]\n]+))?\]")
_KNOWN_TYPES = {t.value: t for t in TagType}

# [CHART: revenue style=marker] — optional trailing style token.
_CHART_STYLE_RE = re.compile(r"\bstyle\s*=\s*([a-z_]+)\b", re.IGNORECASE)


@dataclass
class RawTag:
    type: TagType
    payload: str
    char_offset: int   # into the clean (tag-stripped) text
    raw_offset: int    # into the original tagged text


def tokenize_tags(
    raw: str,
    allowed: frozenset[TagType] | None = None,
) -> tuple[str, list[RawTag], list[str]]:
    """Strip every bracket tag; return (clean_text, tags, warnings).

    `allowed` (when given) restricts which tag types are kept — a tag of a
    known type that is not allowed in this context is stripped and warned
    (e.g. a [CLIP] inside a SHORT audio_script).
    """
    clean_parts: list[str] = []
    clean_len = 0
    tags: list[RawTag] = []
    warnings: list[str] = []
    last = 0

    for m in _ANY_TAG_RE.finditer(raw):
        segment = raw[last:m.start()]
        clean_parts.append(segment)
        clean_len += len(segment)
        last = m.end()

        type_str = m.group(1).strip()
        payload = (m.group(2) or "").strip()
        tag_type = _KNOWN_TYPES.get(type_str)
        if tag_type is None:
            # A tag the voice bible refuses is named as refused. Stripped
            # either way — nothing here reaches the audience — but "unknown,
            # skipped" teaches a writer nothing, and the whole reason these are
            # listed in pipeline/direction.py is that the first writer to read
            # the ElevenLabs docs will try them.
            #
            # This catches the SHOUTED spelling, which is the one this
            # grammar matches. The lowercase spelling the ElevenLabs docs use
            # is not a tag at all by this regex: it survives into the
            # narration and is caught by gates.direction_lint, where it is a
            # block, because there it would be spoken and captioned.
            from pipeline.direction import BANNED_TAGS

            reason = BANNED_TAGS.get(type_str.lower())
            if reason:
                warnings.append(
                    f"[{type_str}] is not an allowed direction — {reason}. "
                    f"Stripped, so nothing was spoken."
                )
            else:
                warnings.append(
                    f"unknown tag [{type_str}: {payload}] at char {m.start()} — skipped"
                )
            continue
        if allowed is not None and tag_type not in allowed:
            warnings.append(
                f"tag [{type_str}] is not allowed here — skipped "
                f"(only {', '.join(sorted(t.value for t in allowed))})"
            )
            continue
        tags.append(RawTag(type=tag_type, payload=payload,
                           char_offset=clean_len, raw_offset=m.start()))

    clean_parts.append(raw[last:])
    return "".join(clean_parts), tags, warnings


def parse_chart_payload(payload: str) -> tuple[str, str]:
    """`[CHART: revenue style=marker]` -> ("revenue", "marker"). Returns an
    empty style when no explicit token is present (the renderer treats an
    unset style as the clean default)."""
    style = ""
    m = _CHART_STYLE_RE.search(payload)
    if m:
        style = m.group(1).lower()
        payload = _CHART_STYLE_RE.sub("", payload)
    return payload.strip(), style


# --------------------------------------------------------------------------
# `|` fields on a payload.
# --------------------------------------------------------------------------

# `[CLIP: lebron three pointer | hold=2.5]`
#
# `[PLATE]` has parsed its own `|` fields since it shipped, in plate_tags,
# because a plate's fields ARE its content and they are checked against the
# slots the plate declares. Nothing else had any, so there was nothing to
# share. Now `hold` is on two more tags, and the shape has recurred — so the
# SPLIT lives here, once, and what a field MEANS stays with whoever asked for
# it. plate_tags keeps its own splitter: a plate value may legitimately be
# prose containing an `=`, and folding whitespace the way a table needs is
# not what a one-field payload wants.
_FIELD_SPLIT = re.compile(r"\s*\|\s*")
_FIELD_ASSIGN = re.compile(r"^([a-zA-Z][a-zA-Z0-9_-]*)\s*=\s*(.*)$", re.DOTALL)


def split_payload_fields(payload: str) -> tuple[str, dict[str, str], list[str]]:
    """`"key | hold=2.5"` -> `("key", {"hold": "2.5"}, [])`.

    The head is everything before the first `|` — the thing the tag is about,
    and the whole payload when no `|` is written, which is what makes every
    bare tag in every script that already exists parse exactly as it did.
    Field names are lower-cased; a part that is not `name=value` is dropped
    and warned about rather than silently swallowed into the key.
    """
    parts = _FIELD_SPLIT.split(payload)
    head = parts[0].strip()
    fields: dict[str, str] = {}
    warnings: list[str] = []
    for part in parts[1:]:
        part = part.strip()
        if not part:
            continue
        m = _FIELD_ASSIGN.match(part)
        if not m:
            warnings.append(
                f"{part!r} is not a `name=value` field — ignored")
            continue
        fields[m.group(1).lower()] = m.group(2).strip()
    return head, fields, warnings


# The band a director may hold a visual for, in seconds.
#
# Under 0.8 nothing is read — it is a frame flashing past, and the pacing
# checks downstream cannot rescue a hold that was never long enough to see.
# Over 5.0 the cut has stopped being a video. Outside the band is a TYPO, not
# an instruction ("hold=30" is a slipped decimal point, not somebody asking
# for a thirty-second still), so it clamps to the nearest edge and says so
# rather than failing the parse and costing the writer the whole script.
HOLD_MIN_S = 0.8
HOLD_MAX_S = 5.0


def parse_hold(payload: str, *, tag: str = "") -> tuple[str, float, list[str]]:
    """`"lebron three pointer | hold=2.5"` -> `("lebron three pointer", 2.5, [])`.

    Returns the payload with its fields stripped, the hold in seconds, and any
    warnings. A hold of **0.0 means the writer did not ask for one** — the
    bare form — and every caller reads that as "use the default you always
    used", so nothing that exists today changes.
    """
    head, fields, warnings = split_payload_fields(payload)
    where = f"[{tag}: {head}] " if tag else ""
    warnings = [f"{where}{w}" for w in warnings]

    raw = fields.pop("hold", "")
    for name in fields:
        warnings.append(f"{where}has no `{name}` field — ignored")
    if not raw:
        return head, 0.0, warnings
    try:
        hold = float(raw.rstrip("s").strip())
    except ValueError:
        hold = math.nan
    # `nan` and `inf` are floats and neither clamps: `min(max(nan, …), …)` is
    # nan, which would reach the model as a hold and fail validation there
    # instead of here, where the writer can be told what they typed.
    if not math.isfinite(hold):
        warnings.append(
            f"{where}hold={raw!r} is not a number of seconds — ignored, so "
            f"this holds for as long as it always did")
        return head, 0.0, warnings

    clamped = min(max(hold, HOLD_MIN_S), HOLD_MAX_S)
    if clamped != hold:
        warnings.append(
            f"{where}asked to hold {hold:g}s, which is outside the "
            f"{HOLD_MIN_S:g}-{HOLD_MAX_S:g}s band — held {clamped:g}s instead")
    return head, clamped, warnings


# --------------------------------------------------------------------------
# Slot values on a tag.
# --------------------------------------------------------------------------

# `[PROP: crushed-flat = -41%]`                       one figure
# `[PROP: see-saw-two-numbers = heavy:$1.1B, light:$40M]`  one per named slot
# `[PROP: numbers-raining = -8%, -12%, -3%]`          in slot order
#
# 74 slots across 51 assets are what turn a fixed drawing into a card that says
# something different in every video. Without a way to write the value into the
# tag, named artwork rendered with every slot empty — Dennis crushed under a
# blank rectangle — and the only filled slots in a build were on the two blank
# layouts.

# A named part is `slot: value`. The name has to look like a slot name, so a
# bare value that happens to contain a colon ("3:1", "9:16") is not mistaken
# for one.
_SLOT_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]*$")

# The key an unnamed value is stored under. Bound to the asset's only slot (or
# the one called `number`) at render time, when its slots are known.
DEFAULT_SLOT = ""

# Positional keys, for a comma list with no names: `#0` is the first slot.
POSITIONAL_PREFIX = "#"


def parse_slot_values(payload: str) -> tuple[str, dict[str, str]]:
    """`key = …` -> (key, {slot: value}).

    Three forms, and the rule between them is "never split a figure in half":
    every comma-separated part must bind a plausible slot name for the named
    form to apply, and a tail that does not is kept whole as one value.

    The writer should not have to know that `crushed-flat`'s slot is called
    `number`, so an unnamed value is bound to the asset at render time.
    """
    key, sep, rest = payload.partition("=")
    key, rest = key.strip(), rest.strip()
    if not sep or not rest:
        return key or payload.strip(), {}

    parts = [p.strip() for p in rest.split(",") if p.strip()]
    if len(parts) == 1 and not _is_binding(parts[0]):
        return key, {DEFAULT_SLOT: parts[0]}

    if all(_is_binding(p) for p in parts):
        named: dict[str, str] = {}
        for part in parts:
            name, _, value = part.partition(":")
            named[name.strip().lower()] = value.strip()
        return key, named

    if not any(_is_binding(p) for p in parts):
        # A bare list fills the slots in the order the registry declares them.
        return key, {f"{POSITIONAL_PREFIX}{i}": v for i, v in enumerate(parts)}

    # Half-bound: almost certainly a comma inside one value, so keep it whole
    # rather than guess. The render-time binder warns if it cannot place it.
    return key, {DEFAULT_SLOT: rest}


def _is_binding(part: str) -> bool:
    name, colon, value = part.partition(":")
    return bool(colon and value.strip() and _SLOT_NAME_RE.match(name.strip().lower()))
