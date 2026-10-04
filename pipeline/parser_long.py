"""LONG script parser: tagged narration -> LongScript (§5).

A real offset-aware tokenizer, not per-section regex hacks. One pass over
the text with `re.finditer`; every bracket tag is stripped from the clean
narration and its position recorded as an offset INTO THE CLEAN TEXT — the
exact string that goes to TTS, so timestamps and tag offsets share one
coordinate system.

The Dennis tag grammar:
    [PLATE: name | slot=value | …]    a plate from the kit, with its content
    [IMG: query] [PRODUCT: query]     real operations/product imagery
    [MEME: key | hold=2.0]            owned library first, capped per video
    [CLIP: query | hold=2.5]          footage/illustration; the clip moves
    [CHART: metric]                   a data path drawn into a charts/ plate
    [SHOW FILING: file.png]           unnamed-source data screenshot
    [SCREENGRAB: slug]                operator-supplied app/screen capture
    [SOUND: key]                      sfx palette
    [SCRIBBLE: mark -> target]        an annotations/ mark on a word or figure
    [MOVE: count-up]                  a design move on the plate on screen
    [SOURCE: Q2 10-Q]                 where the figure on that plate comes from

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
    HOLDABLE_TAG_TYPES,
    SFX_KEYS,
    SOURCE_MAX_CHARS,
    VISUAL_TAG_TYPES,
    Chapter,
    LongScript,
    TagEvent,
    TagType,
    parse_scribble_payload,
)
from pipeline.plate_tags import build_fill, check_bound
from pipeline.plates import (
    AUTOMATIC_MOVES,
    CHAPTER_TYPES,
    NUMBER_MOVES,
    PEN_CIRCLES_PER_CHAPTER,
    PEN_CIRCLES_PER_VIDEO,
    WRITER_MOVES,
    ZOOM_FAMILIES,
    load_plates,
    one_number,
    writer_moves,
)
from pipeline.tagging import (parse_chart_payload, parse_hold, pop_field,
                              tokenize_tags)

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


# The optional `=== CONFESSION ===` trailer: `kind | the admission`, one line.
# Declared rather than detected, because six kinds of admission phrased six
# hundred ways are not reliably findable in prose, and a ledger that cannot say
# which sentences were the confession cannot stop one being told twice.
_CONFESSION_TRAILER_RE = re.compile(r"^\s*=+\s*CONFESSION\s*=+\s*$",
                                    re.IGNORECASE | re.MULTILINE)


def _split_chapters_trailer(raw: str) -> tuple[str, str]:
    """Cut the `=== CHAPTERS ===` trailer off the narration.

    Returns (body, chapters_text). The trailer is never spoken.
    """
    m = _CHAPTERS_TRAILER_RE.search(raw)
    if not m:
        return raw, ""
    return raw[: m.start()], raw[m.end():].strip()


def _split_confession_trailer(raw: str) -> tuple[str, str]:
    """Cut the `=== CONFESSION ===` trailer off. Never spoken."""
    m = _CONFESSION_TRAILER_RE.search(raw)
    if not m:
        return raw, ""
    return raw[: m.start()], raw[m.end():].strip()


def parse_confession(text: str) -> tuple[object | None, list[str]]:
    """`kind | the admission` -> a ScriptConfession. Returns (it, warnings).

    A malformed block warns and is dropped rather than failing the parse. The
    confession is texture; the video is the deliverable, and losing a render
    over a mistyped trailer would be the bookkeeping deciding what ships.
    """
    from pipeline.models import ScriptConfession
    from pipeline.standing import CONFESSION_KINDS

    body = (text or "").strip()
    if not body:
        return None, []
    line = next((ln.strip() for ln in body.splitlines()
                 if ln.strip() and not ln.strip().startswith("#")), "")
    if "|" not in line:
        return None, [f"confession {line!r} is not `kind | the admission` — "
                      f"dropped. The six kinds are {', '.join(CONFESSION_KINDS)}"]
    kind, _, said = line.partition("|")
    try:
        return ScriptConfession(kind=kind.strip(), text=said.strip()), []
    except Exception as exc:                       # noqa: BLE001 — never fatal
        first = str(exc).splitlines()
        detail = next((ln.strip() for ln in first if "Value error" in ln),
                      str(exc).strip())
        return None, [f"confession dropped: {detail}"]


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


def _title_warnings(chapters, settings: Settings) -> list[str]:
    """A title longer than the chapter card holds runs into the drawing."""
    from pipeline.bumper import chapter_title_limit
    from pipeline.plates import PlateError, load_plates

    try:
        limit = chapter_title_limit(load_plates(settings.assets_dir))
    except PlateError:
        return []
    if not limit:
        return []
    return [f"chapter title {ch.title!r} is {len(ch.title)} characters and "
            f"the chapter card holds {limit} — past that the line runs into "
            f"the drawing. Shorten it; the joke survives."
            for ch in chapters if len(ch.title) > limit]


def parse_long_script(raw: str, ticker: str, settings: Settings) -> tuple[LongScript, list[str]]:
    """Tokenize tagged narration. Returns (script, warnings).

    Enforces the LONG character budget before anything can spend, and
    hard-rejects the data vendor's name (it would land in the captions).
    """
    if not raw or not raw.strip():
        raise LongScriptError("Empty message — expected the tagged LONG narration.")

    raw, chapters = _split_chapters_trailer(raw)
    # The confession block may sit before or after the chapter trailer, so it
    # is cut from both halves rather than from a position.
    raw, confession_text = _split_confession_trailer(raw)
    chapters, more = _split_confession_trailer(chapters)
    confession_text = confession_text or more
    raw = _strip_hook_options(raw)
    if not raw.strip():
        raise LongScriptError("Narration is empty (only a chapter trailer was sent).")

    narration, raw_tags, warnings = tokenize_tags(raw)
    for w in warnings:
        log.warning("long tokenize: %s", w)

    from pipeline.timeline import FRAME_TAG_TYPES

    events: list[TagEvent] = []
    # WHAT HOLDS THE FRAME, as the writer wrote it: the tag type, and the
    # plate's key when it is a plate that resolved. Tracked over the RAW tags
    # because a plate that fails to resolve is dropped below, and a [MOVE]
    # written after it must not quietly land on the plate before it.
    holder_type, holder_plate = "", ""
    for rt in raw_tags:
        payload = rt.payload
        style = ""
        hold = 0.0
        values: dict[str, str] = {}
        beside = ""
        if rt.type in (TagType.PLATE, TagType.CHART):
            # `with=` asks for Dennis beside the evidence (items 30 and 11).
            # Taken off before the plate's own fields are read, so it is
            # never mistaken for a slot.
            payload, asked_with = pop_field(payload, "with")
            if asked_with:
                from pipeline.scenes import resolve_beside

                beside, beside_warnings = resolve_beside(
                    load_plates(settings.assets_dir), asked_with,
                    tag=rt.type.value)
                warnings.extend(beside_warnings)
        if rt.type in HOLDABLE_TAG_TYPES:
            # `hold=` is the writer's call on whether this is a glance or a
            # beat to sit in, and it is the only `|` field these tags take.
            payload, hold, hold_warnings = parse_hold(payload, tag=rt.type.value)
            warnings.extend(hold_warnings)
        if rt.type is TagType.PLATE:
            # The tag carries its own content. Resolution and slot-filling
            # happen here so a bad plate name or a mis-sized row is caught at
            # parse time, not discovered as a blank rectangle in the cut.
            # `values` is slot -> text, and the renderer does nothing but place
            # it: it never picks the plate and never computes a figure.
            fill = build_fill(load_plates(settings.assets_dir), payload,
                              aspect="16x9")
            payload = fill.key or fill.name
            values = fill.values
            warnings.extend(fill.warnings)
            holder_type, holder_plate = rt.type.value, (
                fill.key if fill.ok else "")
            if not fill.ok:
                warnings.extend(fill.problems)
                continue
        elif rt.type in FRAME_TAG_TYPES:
            holder_type, holder_plate = rt.type.value, ""
        elif rt.type is TagType.MOVE:
            # `[MOVE: Count Up]` and `[MOVE: count-up]` are the same move.
            # Which plate it acts on is fixed HERE, where the writer's order
            # is still whole; whether that plate can do it is validation's.
            payload = normalize_slug(payload).replace("_", "-")
            values = {"plate": holder_plate, "on": holder_type}
        elif rt.type is TagType.SOURCE:
            # The words are the writer's and go on screen as written; only
            # the spacing is tidied. Like a move, it is fixed to the plate
            # holding the frame here, and checked against it in validation.
            payload = " ".join(payload.split())
            values = {"plate": holder_plate, "on": holder_type}
        elif rt.type is TagType.BOARD:
            # The writer's words, written on the board as typed; only the
            # spacing is tidied. It claims no frame and no moment.
            payload = " ".join(payload.split())
            if not payload:
                warnings.append("[BOARD] with nothing in it — skipped; the board "
                                "asks its default question")
                continue
        elif rt.type is TagType.SCREEN:
            # A plate's name or `price`, tidied; matched against the
            # chapter's plates at render, where the chapters have times.
            payload = " ".join(payload.split())
            if not payload:
                warnings.append("[SCREEN] with nothing in it — skipped; the bot "
                                "picks what his monitor shows")
                continue
        elif rt.type is TagType.SCENE:
            # The writer's room and pose, resolved against the kit here so a
            # room it does not draw is named at intake, not found as a cut
            # to the wrong set. A scene claims no frame, so a [MOVE] after it
            # still acts on the plate before it.
            from pipeline.scenes import resolve_scene

            scene = resolve_scene(load_plates(settings.assets_dir), payload)
            warnings.extend(scene.warnings)
            if not scene.ok:
                warnings.extend(scene.problems)
                continue
            payload = scene.room
            values = scene.values
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
            type=rt.type, payload=payload, values=values, hold=hold,
            char_offset=rt.char_offset, raw_offset=rt.raw_offset, style=style,
            beside=beside,
        ))

    if not narration.strip():
        raise LongScriptError("Narration is empty after stripping tags.")

    low = narration.lower()
    if any(w in low for w in VENDOR_WORDS):
        raise LongScriptError(
            "The narration names the data vendor — it would be spoken and land "
            'in the captions. Data is "from the 10-K"; source stays unnamed.'
        )
    # A [SOURCE] is not narration, so the check above never sees it — and it
    # is the one tag whose whole job is to put a source's name on screen.
    for e in events:
        if e.type is TagType.BOARD and any(w in e.payload.lower() for w in VENDOR_WORDS):
            raise LongScriptError(
                f"[BOARD: {e.payload}] names the data vendor — it would be "
                f"written on the board in shot. Ask the question, never the vendor.")
        if e.type is TagType.SOURCE and any(w in e.payload.lower()
                                            for w in VENDOR_WORDS):
            raise LongScriptError(
                f"[SOURCE: {e.payload}] names the data vendor — it would be on "
                f'screen. Name the filing ("Q2 10-Q", "FY24 10-K") or the '
                f"agency, never the vendor.")

    budget = settings.max_chars("long")
    if len(narration) > budget:
        raise LongScriptError(
            f"Narration is {len(narration)} chars — over the LONG budget of "
            f"{budget}. Trim and resend (no TTS was called)."
        )

    # The floor (C1). Without one this function rejected only empty input, so
    # anything that was not JSON became a LONG script — a chat remark, half a
    # Telegram-split paste, an angle reply that arrived a moment late. Each
    # was saved over the real script and triggered the full slow intake.
    floor = getattr(settings, "long_min_chars", 0)
    if floor and len(narration) < floor:
        raise LongScriptError(
            f"Narration is {len(narration)} chars — a LONG runs to tens of "
            f"thousands, and anything under {floor} is a message rather than "
            f"a script. If this really is the script, send it as a .txt file; "
            f"if it was a note to me, it did not overwrite anything."
        )

    chapter_list, chapter_warnings = parse_chapters(chapters)
    warnings.extend(chapter_warnings)
    warnings.extend(_title_warnings(chapter_list, settings))
    if not chapter_list:
        warnings.append(
            "the script has no usable `=== CHAPTERS ===` trailer — every "
            "chapter opener will be missing its title, and the openers are the "
            "only place a title appears on screen")

    confession, confession_warnings = parse_confession(confession_text)
    warnings.extend(confession_warnings)

    script = LongScript(ticker=ticker, narration=narration, events=events,
                        chapter_list=chapter_list, chapters=chapters,
                        confession=confession)

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
    # tags are offsets, so this maps them through the narration's own length
    # over the estimated runtime — approximate on purpose, and a warning for
    # exactly that reason. The scale is the whole runtime, not the last
    # chapter's start: on that scale the last chapter began at the end of the
    # text and was always reported empty.
    chapters = script.chapter_list
    if len(chapters) < 2 or not chapters[-1].start_s:
        return out
    for i, ch in enumerate(chapters):
        start_s = ch.start_s
        end_s = chapters[i + 1].start_s if i + 1 < len(chapters) else duration
        if end_s - start_s < 60:
            continue
        lo = int(len(script.narration) * min(start_s / duration, 1.0))
        hi = int(len(script.narration) * min(end_s / duration, 1.0))
        n = sum(1 for e in visuals if lo <= e.char_offset < hi)
        mins = (end_s - start_s) / 60.0
        if n / mins < DENSITY_FLOOR_PER_MIN:
            out.append(
                f'chapter "{ch.title}" ({ch.type}) has {n} tagged visual'
                f'{"" if n == 1 else "s"} across {mins:.0f} minutes '
                f"({n / mins:.1f}/min) — below the floor of "
                f"{DENSITY_FLOOR_PER_MIN:.0f}")
    return out


def dennis_alone_warnings(script: LongScript, settings: Settings) -> list[str]:
    """Item 32: over the operator's share of Dennis alone in frame.

    Estimated with the planner on the voice's estimated timings, so it reads
    off the rules the render cuts by. A warning: where he talks is the
    writer's call, and the approval screen prints the share either way.
    """
    from pipeline.timeline import estimate_dennis_alone

    share = estimate_dennis_alone(script, settings)
    limit = float(getattr(settings, "long_dennis_alone_max", 0.35) or 0.35)
    if share is None or share <= limit:
        return []
    return [
        f"Dennis is alone on screen for about {share:.0%} of the video, over "
        f"the {limit:.0%} you set. The evidence carries the explaining: put "
        f"the figure he is talking through on a [PLATE], [CHART] or [SHOW "
        f"FILING], and keep him for setting up, the joke and the line each "
        f"chapter lands on."]


# ---------------------------------------------------------------------------
# [MOVE] — the writer's design moves on the plate on screen.
# ---------------------------------------------------------------------------


def _short_name(key: str) -> str:
    """`figures/big-number-l1-16x9` as the writer names it in the tag."""
    return key.split("/", 1)[-1]


def _spoken_after(script: LongScript, e: TagEvent, n: int = 5) -> str:
    """The first few words after a tag — where the writer will look for it."""
    words = script.narration[e.char_offset:e.char_offset + 120].split()[:n]
    return " ".join(words).rstrip(",.;:!?") or "the end of the narration"


def estimated_hold(script: LongScript, holder: int, settings: Settings
                   ) -> tuple[float, str]:
    """(seconds the frame tag `holder` stays up, what ends it), estimated.

    The planner's rule (item 31) read off the script: a plate, chart or
    filing stays up until the next visual tag, the next [SCENE] or the end of
    its paragraph, never under the readable floor or over the ceiling. Times
    are words over the voice's words a second, as every estimate here is.
    """
    from pipeline.timeline import FRAME_TAG_TYPES

    wps = max(float(getattr(settings, "mock_wps_long", 2.5) or 2.5), 0.1)
    text = script.narration
    at = script.events[holder].char_offset

    def est(offset: int) -> float:
        return len(text[:offset].split()) / wps

    ends = [(len(text), "the end")]
    nxt = next((e.char_offset for e in script.events[holder + 1:]
                if e.char_offset > at and (e.type in FRAME_TAG_TYPES
                                           or e.type is TagType.SCENE)), None)
    if nxt is not None:
        ends.append((nxt, "the next tag"))
    brk = re.search(r"\n[ \t]*\n", text[at:])
    if brk:
        ends.append((at + brk.start(), "the paragraph's end"))
    end, why = min(ends)
    floor = float(getattr(settings, "long_min_readable_s", 5.0) or 5.0)
    ceiling = float(getattr(settings, "long_max_readable_s", 30.0) or 30.0)
    return min(max(est(end) - est(at), floor), ceiling), why


def move_refusal(move: str, plate, values: dict[str, str]) -> str:
    """Why `plate` cannot do `move` with these slot values, or "" if it can.

    Each refusal says what to do instead, because a writer told only that a
    move is refused will guess, and the guess is usually a second refusal.
    """
    if move in AUTOMATIC_MOVES:
        return (f"{move} plays by itself on every chart — there is nothing to "
                f"tag. Cut the [MOVE].")
    if move not in WRITER_MOVES:
        import difflib
        near = ([m for m in WRITER_MOVES if move and move in m]
                or difflib.get_close_matches(move, WRITER_MOVES, n=1,
                                             cutoff=0.6))
        return (f"{move!r} is not a move you can call"
                + (f" — did you mean {near[0]}?" if near else "")
                + f" Yours are {', '.join(WRITER_MOVES)}.")
    name = _short_name(plate.key)
    can = writer_moves(plate)
    if move == "zoom-to-slot" and plate.family not in ZOOM_FAMILIES:
        return (f"zoom-to-slot pushes into a passage on paper/ plates only, "
                f"and {name} is {plate.family}/. "
                + ("Use highlight on it instead." if "highlight" in can
                   else "Put the zoom on the filing page or footnote it "
                        "comes from."))
    slot = can.get(move)
    if not slot:
        offer = ", ".join(f"{m} (on {sl})" for m, sl in can.items())
        return (f"{name} cannot do {move} — the kit gives it nothing to act "
                f"on. " + (f"It can do: {offer}." if offer
                          else "It takes no moves at all."))
    if move in NUMBER_MOVES:
        text = str(values.get(slot) or "").strip()
        if not text:
            return (f"{move} acts on {name}'s ◆ {slot}, which you left empty — "
                    f"fill it with the one figure, or cut the move.")
        if not one_number(text):
            return (f"{move} acts on {name}'s ◆ {slot}, which holds "
                    f"{text!r} — it needs exactly one number there, like "
                    f"$3.1bn or −12%. Put the figure alone in {slot}, or cut "
                    f"the move.")
    return ""


def move_problems(script: LongScript, reg, settings: Settings
                  ) -> tuple[list[str], list[str]]:
    """Every [MOVE] checked against the plate it acts on. `(warnings, blocking)`.

    BLOCKING: a move the plate cannot do, a number move on a slot that is not
    one number, a zoom off paper, a move with no plate on screen, the same move
    twice on one plate, and a pen-circle over the video's three. A second
    pen-circle in one chapter blocks too, unless either sits close enough to
    a chapter boundary that the estimate below could have put it on the wrong
    side — then it is a warning, and the render keeps the first by real time.

    Times here are ESTIMATES — words before the tag over the voice's words a
    second — because nothing has been spoken yet.
    """
    from pipeline.timeline import (
        CHAPTER_HOST_S, FRAME_TAG_TYPES, chapter_at,
        chapter_windows, move_targets)

    warnings: list[str] = []
    blocking: list[str] = []
    events = script.events
    targets = move_targets(events)
    if not targets:
        return warnings, blocking
    wps = max(float(getattr(settings, "mock_wps_long", 2.5) or 2.5), 0.1)

    def est(e: TagEvent) -> float:
        return len(script.narration[:e.char_offset].split()) / wps

    duration = script.word_count / wps
    windows = chapter_windows(script.chapter_list, duration)
    starts = [a for a, _ in windows]

    # The frames that already carry a [SCRIBBLE], by the index of the tag
    # holding the frame — the same pairing a move uses.
    scribbled: set[int] = set()
    last: int | None = None
    for i, ev in enumerate(events):
        if ev.type in FRAME_TAG_TYPES:
            last = i
        elif ev.type is TagType.SCRIBBLE and last is not None:
            scribbled.add(last)

    seen: set[tuple[int, str]] = set()
    circles: list[tuple[TagEvent, float]] = []
    for idx, holder in targets.items():
        e = events[idx]
        move = e.payload
        tag = f'[MOVE: {move}] before "{_spoken_after(script, e)}"'
        plate_key = e.values.get("plate", "")
        held_by = e.values.get("on", "")
        if move not in WRITER_MOVES:
            # Named first, before any question of which plate: "circle is
            # not a move" is the fix, wherever the tag sits. A tagged
            # line-draw is redundant rather than wrong — the chart plays it
            # anyway — so that one only warns.
            (warnings if move in AUTOMATIC_MOVES else blocking).append(
                f"{tag}: {move_refusal(move, None, {})}")
            continue
        if not plate_key:
            if held_by == "PLATE":
                blocking.append(
                    f"{tag} follows a [PLATE] that did not resolve — fix that "
                    f"plate and the move goes with it.")
            elif held_by:
                blocking.append(
                    f"{tag} acts on the plate on screen, but the frame there "
                    f"belongs to a [{held_by}], which has no slots. Put the "
                    f"move after the [PLATE] it is for.")
            else:
                blocking.append(
                    f"{tag} comes before any [PLATE] — a move acts on the last "
                    f"plate before it. Put it after the plate it is for.")
            continue
        plate = reg.get(plate_key)
        if plate is None or holder is None:
            continue   # the plate itself is refused by the PLATE check
        why = move_refusal(move, plate, events[holder].values)
        if why:
            blocking.append(f"{tag}: {why}")
            continue
        if (holder, move) in seen:
            blocking.append(
                f"{tag}: {_short_name(plate_key)} already has a {move} — one "
                f"of each move a plate. Cut the second.")
            continue
        seen.add((holder, move))
        gap = est(e) - est(events[holder])
        hold, why = estimated_hold(script, holder, settings)
        if gap > hold:
            warnings.append(
                f"{tag} lands about {gap:.0f}s after its plate goes up, and "
                f"the plate holds about {hold:.0f}s, until {why} — by then he "
                f"is back on screen and the move is dropped. Put it on a word "
                f"while the plate is up.")
        if move == "pen-circle":
            circles.append((e, est(e)))
            if holder in scribbled:
                warnings.append(
                    f"{tag}: the same plate also carries a [SCRIBBLE]. Both "
                    f"spend the frame's one attention — keep one.")

    if len(circles) > PEN_CIRCLES_PER_VIDEO:
        extra = ", ".join(f'"{_spoken_after(script, e, 4)}"'
                          for e, _ in circles[PEN_CIRCLES_PER_VIDEO:])
        blocking.append(
            f"{len(circles)} [MOVE: pen-circle] in the video — the limit is "
            f"{PEN_CIRCLES_PER_VIDEO}, one for each figure the argument turns "
            f"on. Cut {len(circles) - PEN_CIRCLES_PER_VIDEO} (the ones past "
            f"the limit are before {extra}), keeping the three the argument "
            f"needs most.")
    per_chapter: dict[int, list[tuple[TagEvent, float]]] = {}
    for e, t in circles:
        per_chapter.setdefault(chapter_at(t, starts), []).append((e, t))

    def near_boundary(t: float) -> bool:
        # Fifteen seconds, or a twentieth of the way in, whichever is more:
        # the estimate drifts with every sentence read faster or slower than
        # the average, so it drifts more the later the tag.
        slack = max(15.0, 0.05 * t) + CHAPTER_HOST_S
        return any(abs(t - b) < slack for b in starts[1:])

    for ch, hits in sorted(per_chapter.items()):
        if len(hits) <= PEN_CIRCLES_PER_CHAPTER:
            continue
        title = (script.chapter_list[ch].title
                 if ch < len(script.chapter_list) else f"chapter {ch + 1}")
        where = ", ".join(f'"{_spoken_after(script, e, 4)}"' for e, _ in hits)
        close = any(near_boundary(t) for _, t in hits)
        msg = (f"{len(hits)} [MOVE: pen-circle] in \"{title}\" (before {where})"
               f" — one a chapter, on the single figure the chapter turns on. "
               f"Keep the one that matters and cut the rest.")
        if close:
            warnings.append(msg + " (One sits near a chapter boundary, so "
                            "this is an estimate; the render keeps the first "
                            "by real time.)")
        else:
            blocking.append(msg)
    return warnings, blocking


# ---------------------------------------------------------------------------
# [SOURCE] — where the figure on screen comes from (item 14).
# ---------------------------------------------------------------------------

# Design's tag holds about this much in its source slot at its drawn size; a
# longer line would be cut by the slot. A source is a citation, not a caption.
def source_problems(script: LongScript, reg, settings: Settings
                    ) -> tuple[list[str], list[str]]:
    """Every [SOURCE] checked against the plate it goes under.

    BLOCKING: a source with no plate on screen, one longer than the tag holds,
    two on one plate, one on a plate that prints its own source in a slot of
    its own (the source goes in that slot), and one on a plate design gives no
    clear spot for the tag (it would cover the plate's own figures: design's
    word is to say the source instead). A source written long after its plate
    went up warns, the way a late move does. `(warnings, blocking)`.
    """
    from pipeline.moves import tag_clear
    from pipeline.timeline import move_targets

    warnings: list[str] = []
    blocking: list[str] = []
    events = script.events
    targets = move_targets(events, frozenset({TagType.SOURCE}))
    if not targets:
        return warnings, blocking
    wps = max(float(getattr(settings, "mock_wps_long", 2.5) or 2.5), 0.1)

    def est(e: TagEvent) -> float:
        return len(script.narration[:e.char_offset].split()) / wps

    seen: set[int] = set()
    for idx, holder in targets.items():
        e = events[idx]
        tag = f'[SOURCE: {e.payload}] before "{_spoken_after(script, e)}"'
        if not e.payload.strip():
            blocking.append(f"{tag} is empty — name the filing or the agency, "
                            f"or cut the tag.")
            continue
        if len(e.payload) > SOURCE_MAX_CHARS:
            blocking.append(
                f"{tag} is {len(e.payload)} characters — the tag holds "
                f"{SOURCE_MAX_CHARS}. Name the document, like \"Q2 10-Q\" or "
                f"\"BLS, August CPI\".")
            continue
        plate_key = e.values.get("plate", "")
        held_by = e.values.get("on", "")
        if not plate_key:
            if held_by == "PLATE":
                blocking.append(f"{tag} follows a [PLATE] that did not resolve "
                                f"— fix that plate and the source goes with it.")
            elif held_by:
                blocking.append(
                    f"{tag} goes under the plate on screen, but the frame there "
                    f"belongs to a [{held_by}]. Put it after the [PLATE] whose "
                    f"figure it sources.")
            else:
                blocking.append(f"{tag} comes before any [PLATE] — a source goes "
                                f"under the last plate before it.")
            continue
        plate = reg.get(plate_key)
        if plate is None or holder is None:
            continue   # the plate itself is refused by the PLATE check
        if plate.slot("source") is not None:
            blocking.append(
                f"{tag}: {_short_name(plate_key)} prints its own source — put "
                f"it in the plate's tag as source={e.payload} and cut the "
                f"[SOURCE].")
            continue
        if not tag_clear(plate):
            covers = ((plate.motion or {}).get("slide-in") or {}).get("covers") or ()
            what = f" ({', '.join(list(covers)[:3])})" if covers else ""
            blocking.append(
                f"{tag}: {_short_name(plate_key)} has no clear spot for the "
                f"source tag — it would cover the plate's own figures{what}. "
                f"Say where the figure is from in the sentence and cut the "
                f"[SOURCE], or put the figure on a plate without the ✕source mark.")
            continue
        if holder in seen:
            blocking.append(f"{tag}: {_short_name(plate_key)} already has a "
                            f"source — one a plate. Cut the second.")
            continue
        seen.add(holder)
        gap = est(e) - est(events[holder])
        hold, why = estimated_hold(script, holder, settings)
        if gap > hold:
            warnings.append(
                f"{tag} lands about {gap:.0f}s after its plate goes up, and "
                f"the plate holds about {hold:.0f}s, until {why} — by then he "
                f"is back on screen and the source is dropped. Put it in a "
                f"sentence while the plate is up.")
    return warnings, blocking


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
      SOURCE with no plate, too long, -> BLOCKING (see source_problems)
        twice on a plate, or on a plate
        that prints its own source
      MOVE the plate cannot do        -> BLOCKING (see move_problems: quota,
                                         paper-only zoom, one-number slots)
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

    # THE MEME IS CAPPED AND THE CLIP IS NOT, and that is a decision rather
    # than an omission. A meme is a joke and jokes are rationed. A `[CLIP]` is
    # ILLUSTRATION — the visual that proves the claim — which is
    # information-first, which is the thing §8 of the bible actively wants:
    # the boredom is aimed at the hype, never at the work. Capping it would
    # fight the reason it exists, and the pacing and hold-ceiling checks
    # already stop a video becoming a slideshow.
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
            fill = check_bound(reg, e.payload, e.values, aspect="16x9")
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

    move_warnings, move_blocking = move_problems(script, reg, settings)
    warnings.extend(move_warnings)
    blocking.extend(move_blocking)
    source_warnings, source_blocking = source_problems(script, reg, settings)
    warnings.extend(source_warnings)
    blocking.extend(source_blocking)
    from pipeline.scenes import scene_problems

    scene_warnings, scene_blocking = scene_problems(script, reg)
    warnings.extend(scene_warnings)
    blocking.extend(scene_blocking)

    warnings.extend(density_warnings(script, settings))
    warnings.extend(dennis_alone_warnings(script, settings))

    from pipeline.room_dressing import BOARD_MAX_CHARS

    boards = [e for e in script.events if e.type is TagType.BOARD]
    if len(boards) > 1:
        warnings.append(
            f"{len(boards)} [BOARD] tags — the board is written once, with the "
            f"first: {boards[0].payload!r}. Keep one.")
    if boards and len(boards[0].payload) > BOARD_MAX_CHARS:
        warnings.append(
            f"[BOARD: {boards[0].payload}] is {len(boards[0].payload)} characters; "
            f"the board fits about {BOARD_MAX_CHARS}, so it is written small. "
            f"Cut it to the question.")

    from pipeline.room_screen import PRICE, plate_stem

    shown = {plate_stem(e.payload) for e in script.events if e.type is TagType.PLATE}
    for e in script.events:
        if e.type is TagType.SCREEN and e.payload.strip().lower() != PRICE \
                and plate_stem(e.payload.strip().lower()) not in shown:
            warnings.append(
                f"[SCREEN: {e.payload}] names no plate this script shows — his "
                f"monitor shows a plate from its chapter's [PLATE] tags, or "
                f"`price`. The bot picks for that chapter.")

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
