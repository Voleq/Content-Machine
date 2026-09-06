"""Delivery direction: the vocabulary, the ceilings, and the two coordinate
systems it has to keep straight.

The migration to eleven_v3 is not a compatibility exercise — v3 can PERFORM
delivery, and the pipeline was emitting one audio tag out of a vocabulary the
voice bible has been describing for as long as it has existed. §7's "rare
genuine interest — the monotone lifts; these lifts are the retention" had no
mechanism behind it at all.

What is pinned here is the part that can go wrong silently: a tag the model
cannot perform is READ ALOUD, and a tag the alignment mis-indexes moves every
visual cue in the video.
"""

from __future__ import annotations

import pytest

from pipeline.direction import (BANNED_TAGS, DIRECTIONS, PER_SCRIPT_MAX,
                                REGISTERS, emission, performs_audio_tags,
                                setting_overrides)
from pipeline.gates import direction_lint
from pipeline.models import TagEvent, TagType
from pipeline.tagging import tokenize_tags
from pipeline.tts import (TTSEngine, expand_delivery, remap_to_clean,
                          words_from_alignment)

V3 = "eleven_v3"
TURBO = "eleven_turbo_v2_5"


def ev(kind: TagType, offset: int) -> TagEvent:
    return TagEvent(type=kind, payload="", char_offset=offset, raw_offset=offset)


class _Script:
    """The two script models share exactly what the linter reads off them."""

    def __init__(self, narration, events=(), ticker="EXMPL", chapters=()):
        self.narration = narration
        self.events = list(events)
        self.ticker = ticker
        self.chapter_list = list(chapters)


def _alignment(text: str) -> dict:
    """A character alignment of the shape ElevenLabs returns."""
    return {
        "characters": list(text),
        "character_start_times_seconds": [i * 0.1 for i in range(len(text))],
        "character_end_times_seconds": [(i + 1) * 0.1 for i in range(len(text))],
    }


# --------------------------------------------------------------------------
# The vocabulary, per model.
# --------------------------------------------------------------------------


def test_every_tag_the_writer_may_declare_has_a_definition():
    """A delivery tag with no row in the table is one that emits nothing and
    says nothing about why — the exact silence this table exists to end."""
    from pipeline.models import DELIVERY_TAG_TYPES

    defined = set(DIRECTIONS) | set(REGISTERS)
    assert defined == set(DELIVERY_TAG_TYPES), (
        f"undefined: {sorted(t.value for t in DELIVERY_TAG_TYPES - defined)}; "
        f"orphaned: {sorted(t.value for t in defined - DELIVERY_TAG_TYPES)}")


@pytest.mark.parametrize("tag,expected", [
    (TagType.LONG_BEAT, "[long pause]"),
    (TagType.SIGH, "[sighs]"),
    (TagType.EXHALE, "[exhales]"),
    (TagType.SNORT, "[snorts]"),
    (TagType.SARCASTIC, "[sarcastic]"),
    (TagType.CURIOUS, "[curious]"),
    (TagType.QUIET, "[whispers]"),
])
def test_v3_gets_the_audio_tag(tag, expected):
    assert emission(tag, V3).strip() == expected


def test_a_beat_is_an_ellipsis_on_v3():
    """§5: ellipses add pauses and weight, and they are the right replacement
    for an SSML break on a model that reads punctuation as timing."""
    assert emission(TagType.BEAT, V3).strip() == "…"


@pytest.mark.parametrize("tag", [TagType.BEAT, TagType.LONG_BEAT,
                                 TagType.SIGH, TagType.EXHALE])
def test_the_timing_tags_fall_back_to_a_break(tag):
    assert "<break" in emission(tag, TURBO)


@pytest.mark.parametrize("tag", [TagType.SNORT, TagType.SARCASTIC,
                                 TagType.CURIOUS, TagType.QUIET])
def test_a_performance_tag_is_dropped_rather_than_faked(tag):
    """There is no pause that means "sarcastic". On a model that cannot
    perform the direction, emitting nothing is correct and emitting the
    bracket text would have it read aloud."""
    assert emission(tag, TURBO) == ""


def test_no_break_ever_reaches_a_v3_request():
    """The one invariant that covers the whole table: if a <break> got through
    on v3 it would be spoken, and it would be spoken in the middle of the
    sentence it was meant to time."""
    clean = "The bull case holds. It has also been four years."
    every_tag = [ev(t, 20) for t in sorted(set(DIRECTIONS) | set(REGISTERS),
                                           key=lambda t: t.value)]
    text, _, _ = expand_delivery(clean, every_tag, V3)
    assert "<break" not in text
    assert "0.6s" not in text


# --------------------------------------------------------------------------
# §2 — the register tags, which need opposite mechanisms per model.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("tag", [TagType.FLAT, TagType.DRY])
def test_the_register_moves_the_sliders_on_a_pre_v3_model(tag):
    assert setting_overrides(tag, TURBO) == {"stability": 0.85, "style": 0.0}
    assert emission(tag, TURBO) == ""


@pytest.mark.parametrize("tag", [TagType.FLAT, TagType.DRY])
def test_the_register_must_not_touch_stability_on_v3(tag):
    """0.85 is v3's Robust end, and Robust reduces responsiveness to
    directional prompts. [FLAT] and [DRY] are the two commonest tags in any
    Dennis script, so on the slider path they would suppress every other tag
    around them — the migration would buy a vocabulary and then mute it."""
    assert setting_overrides(tag, V3) == {}
    assert emission(tag, V3).strip() in ("[flat]", "[deadpan]")


def test_flat_still_suppresses_nothing_when_it_shares_a_script():
    clean = "A line. Another line."
    text, overrides, _ = expand_delivery(
        clean, [ev(TagType.FLAT, 0), ev(TagType.CURIOUS, 8)], V3)
    assert "[curious]" in text, "the register must not eat the other tags"
    assert "stability" not in overrides


# --------------------------------------------------------------------------
# The tier, which is not the same question as the model.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("tier", ["local", "mock"])
def test_a_voice_that_performs_nothing_is_handed_nothing(tier):
    """Piper honours neither audio tags nor SSML — it reads both out loud. A
    [BEAT] in a draft was audibly "break time zero point six s" for as long as
    this looked only at the configured model.
    """
    clean = "The bull case holds. It has also been four years."
    text, overrides, spans = expand_delivery(
        clean, [ev(TagType.BEAT, 20), ev(TagType.SIGH, 20)], V3, tier=tier)
    assert text == clean
    assert overrides == {} and spans == []


def test_the_direction_is_in_the_cache_key_on_every_tier(settings):
    """Otherwise a draft of "the line." and a draft of "the line. [SIGH]"
    share one entry, and the second silently returns the first — on the very
    tier the operator uses to check the script."""
    engine = TTSEngine(settings)
    plain = engine._cache_dir("A line here.", "long", None, True)[1]
    sighed = engine._cache_dir("A line here.", "long",
                               [ev(TagType.SIGH, 6)], True)[1]
    assert plain != sighed


# --------------------------------------------------------------------------
# §6 — the alignment remap. The highest-stakes item here.
# --------------------------------------------------------------------------


def test_a_tag_never_steals_a_word_from_the_prose():
    """`clean_text.find(w.word, cursor)` cannot tell a directive fragment from
    the same characters in the narration.

    The ellipsis is where this bites, and §5 is what makes it bite: [BEAT]
    emits "…" on v3, and a writer is allowed to have written one. The search
    matched the writer's ellipsis, consumed it, and then dropped the real one
    as "not found" — losing a token and shifting every offset after it.
    """
    clean = "They called it a transformation … of the cost base. The margin fell."
    request, _, spans = expand_delivery(clean, [ev(TagType.BEAT, 17)], V3)
    words = words_from_alignment(request, _alignment(request))
    untagged = words_from_alignment(clean, _alignment(clean))

    exact = remap_to_clean(words, clean, spans)
    assert [(w.word, w.char_start, w.char_end) for w in exact] == \
        [(w.word, w.char_start, w.char_end) for w in untagged], (
            "a tagged script must anchor on exactly the words an untagged one does")

    searched = remap_to_clean(words, clean)
    assert len(searched) < len(exact), (
        "the search-based fallback is meant to be demonstrably worse here — "
        "if it has stopped losing the word, this test no longer pins anything")


def test_every_offset_points_at_its_own_word_with_the_whole_vocabulary():
    clean = ("The buyback is curious. A genuinely curious use of the cash, "
             "and the quiet part is that the flat line was the point.")
    events = [ev(TagType.CURIOUS, 23), ev(TagType.QUIET, 61),
              ev(TagType.FLAT, 0), ev(TagType.SNORT, 100)]
    request, _, spans = expand_delivery(clean, events, V3)
    words = remap_to_clean(words_from_alignment(request, _alignment(request)),
                           clean, spans)
    for w in words:
        assert clean[w.char_start:w.char_end] == w.word, (
            f"{w.word!r} points at {clean[w.char_start:w.char_end]!r}")


def test_a_tag_glued_to_a_word_is_still_its_own_token():
    """A writer who omits the space — "holds.[SIGH]" — must not produce a word
    that is half prose and half direction, because the remap drops whatever
    overlaps an insertion."""
    clean = "The bull case holds.It has also been four years."
    request, _, spans = expand_delivery(clean, [ev(TagType.SIGH, 20)], V3)
    words = remap_to_clean(words_from_alignment(request, _alignment(request)),
                           clean, spans)
    assert "holds." in [w.word for w in words]
    for w in words:
        assert clean[w.char_start:w.char_end] == w.word


# --------------------------------------------------------------------------
# §6 — captions, and the request length.
# --------------------------------------------------------------------------


def test_no_direction_survives_into_the_captions(settings):
    """Captions are built from the word list, so a directive fragment left in
    it is visible to the viewer and invisible in the logs."""
    from pipeline.rasters import build_phrase_ass

    clean = ("He read the guidance twice. Then he read the cash flow "
             "statement, which was the interesting one.")
    out = TTSEngine(settings).synthesize(
        clean, "long", events=[ev(TagType.BEAT, 26), ev(TagType.SIGH, 26)])
    for w in out.words:
        assert clean[w.char_start:w.char_end] == w.word
        assert "[" not in w.word and "<" not in w.word

    ass = build_phrase_ass(out.words, settings=settings, play_res=(1080, 1920))
    for banned in ("[sighs]", "<break", "[curious]", "[flat]"):
        assert banned not in ass


def test_chunking_counts_the_tags_the_request_will_carry(settings):
    """The character budget is checked on the CLEAN script before any spend,
    which is right — but the request carries the re-inserted direction, so it
    is longer than the thing that was budgeted. Chunking has to be computed on
    what is actually sent or a request can exceed the model's own limit where
    the clean text did not."""
    from pipeline.tts import chunk_text

    engine = TTSEngine(settings)
    clean = ". ".join(f"Sentence number {i} runs on for a while" for i in range(80))
    events = [ev(TagType.BEAT, i * 40) for i in range(1, 20)]
    request = engine._cache_dir(clean, "long", events, False)[2]

    limit = settings.tts_chunk_chars
    assert all(len(c) <= limit for c in chunk_text(request, limit))
    assert "".join(chunk_text(request, limit)) == request


# --------------------------------------------------------------------------
# §3 — banned, and banned by name.
# --------------------------------------------------------------------------


def test_a_lowercase_banned_tag_blocks_because_it_would_be_spoken():
    """The bracket grammar only matches a SHOUTED type, so `[laughs]` — the
    spelling the ElevenLabs docs use — is not a tag at all. It survives into
    the narration, gets read out, and lands in the captions."""
    findings = direction_lint(_Script("He read it. [laughs] Then read it again."))
    assert [f.severity for f in findings] == ["block"]
    assert "trying" in findings[0].message


def test_a_sound_effect_is_banned_on_the_stronger_ground():
    findings = direction_lint(_Script("The guidance held. [applause] For now."))
    assert findings and findings[0].severity == "block"
    assert "did not happen" in findings[0].message


def test_a_shouted_banned_tag_is_named_where_it_is_stripped():
    """Harmless — the tokenizer takes it out — but "unknown tag, skipped"
    teaches a writer nothing, and the whole reason these are listed is that
    the first writer to read the ElevenLabs docs will try them."""
    _, _, warnings = tokenize_tags("He read it. [LAUGHS] Then again.")
    assert len(warnings) == 1
    assert "not an allowed direction" in warnings[0]
    assert "trying" in warnings[0]


def test_an_ordinary_unknown_tag_is_still_just_unknown():
    _, _, warnings = tokenize_tags("He read it. [WOBBLE] Then again.")
    assert len(warnings) == 1 and "unknown tag" in warnings[0]


def test_nothing_banned_is_also_reachable():
    """A tag cannot be both refused by name and offered in the table."""
    offered = {e.strip().strip("[]").lower()
               for t in (set(DIRECTIONS) | set(REGISTERS))
               for e in (emission(t, V3),) if e}
    assert not (offered & set(BANNED_TAGS))


# --------------------------------------------------------------------------
# §4 — density. Warnings, never blocks: the writer decides.
# --------------------------------------------------------------------------


def test_two_directions_in_one_sentence_warn():
    n = "The bull case holds and it has held for four years now."
    out = direction_lint(_Script(n, [ev(TagType.SIGH, 20), ev(TagType.BEAT, 30)]))
    assert any("in one sentence" in f.message for f in out)
    assert all(f.severity == "warn" for f in out)


def test_one_direction_a_sentence_is_fine():
    n = ("The bull case holds and it has held for four years. "
         "The margin did not. That is the whole story, told twice.")
    at = [i for i, c in enumerate(n) if c == " "]
    out = direction_lint(_Script(n, [ev(TagType.SIGH, at[3]),
                                     ev(TagType.BEAT, at[11])]))
    assert out == [], [f.message for f in out]


def test_a_direction_inside_a_word_is_named():
    """A missing space before the bracket. It splits the word in the request,
    so the voice pauses mid-word and a cue anchored there anchors on half."""
    n = "The bull case holds and it has held for four long years now."
    out = direction_lint(_Script(n, [ev(TagType.BEAT, 6)]))
    assert any("inside a word" in f.message for f in out)


def test_adjacent_directions_warn():
    n = "The bull case holds and it has held for four long years now."
    out = direction_lint(_Script(n, [ev(TagType.SIGH, 20), ev(TagType.BEAT, 20)]))
    assert any("adjacent" in f.message for f in out)


@pytest.mark.parametrize("tag,cap", sorted(PER_SCRIPT_MAX.items(),
                                           key=lambda kv: kv[0].value))
def test_the_per_script_ceilings_warn_above_and_not_at(tag, cap):
    """The lift is the retention, and a lift that happens six times is a
    monotone again — but the ceiling itself is allowed."""
    n = " ".join(f"Sentence number {i} is here." for i in range(40))
    at = direction_lint(_Script(n, [ev(tag, 28 * i) for i in range(cap)]))
    assert not [f for f in at if f"[{tag.value}]" in f.message and "ceiling" in f.message]

    over = direction_lint(_Script(n, [ev(tag, 28 * i) for i in range(cap + 1)]))
    assert [f for f in over if f"[{tag.value}]" in f.message and "ceiling" in f.message]


def test_the_rate_ceiling_ignores_a_fragment():
    """Below a few hundred characters a "per thousand" rate is arithmetic
    about a script that does not exist."""
    out = direction_lint(_Script("Short.", [ev(TagType.BEAT, 5)]))
    assert not [f for f in out if "per 1,000" in f.message]


def test_quiet_may_not_open_the_video():
    from pipeline.models import Chapter

    n = " ".join(f"Sentence number {i} is here." for i in range(40))
    chapters = [Chapter(type="cold-open", title="One"),
                Chapter(type="the-numbers", title="Two")]
    early = direction_lint(_Script(n, [ev(TagType.QUIET, 10)], chapters=chapters))
    assert any("opening chapter" in f.message for f in early)

    late = direction_lint(_Script(n, [ev(TagType.QUIET, len(n) - 30)],
                                  chapters=chapters))
    assert not [f for f in late if "opening chapter" in f.message]


# --------------------------------------------------------------------------
# §5 — capitalisation is live formatting now.
# --------------------------------------------------------------------------


def test_a_shouted_word_is_flagged():
    out = direction_lint(_Script("That is NOT what the filing says."))
    assert any("shouted" in f.message for f in out)


def test_acronyms_and_the_ticker_are_not_shouting():
    out = direction_lint(_Script(
        "The SEC filing says EXMPL grew EBITDA and free cash flow in the US.",
        ticker="EXMPL"))
    assert out == [], [f.message for f in out]


# --------------------------------------------------------------------------
# §7 — the thing that must not be wired in.
# --------------------------------------------------------------------------


def test_nothing_inserts_direction_on_the_writers_behalf():
    """The writer declares delivery; the pipeline never invents it. Same rule
    as the plates, and the reason ElevenLabs' "Enhance" pass is not wired in:
    it would put a model in charge of the register."""
    clean = "He read the guidance. It said what it said."
    text, overrides, spans = expand_delivery(clean, [], V3)
    assert (text, overrides, spans) == (clean, {}, [])


def test_performs_audio_tags_survives_a_dated_model_id():
    assert performs_audio_tags("eleven_v3")
    assert performs_audio_tags("eleven_v3_preview_2026_01")
    assert not performs_audio_tags(TURBO)
    assert not performs_audio_tags("")


def test_a_script_carrying_every_tag_anchors_exactly_where_a_bare_one_does():
    """The round trip. Every visual in the video is positioned off these
    offsets, so the test that matters is not "the offsets are plausible" but
    "they are the SAME offsets the untagged script produces"."""
    clean = ("The buyback is curious. A genuinely curious use of the cash, and "
             "the quiet part is that the flat line was the point. He read it "
             "twice, then read the cash flow statement, which was worse.")
    every = sorted(set(DIRECTIONS) | set(REGISTERS), key=lambda t: t.value)
    # At word boundaries, which is where a writer's bracket actually lands.
    # Mid-word is a typo and the linter says so; see the test below.
    boundaries = [i for i, c in enumerate(clean) if c == " "][2:]
    events = [ev(tag, boundaries[i * 2]) for i, tag in enumerate(every)]

    request, _, spans = expand_delivery(clean, events, V3)
    tagged = remap_to_clean(words_from_alignment(request, _alignment(request)),
                            clean, spans)
    bare = words_from_alignment(clean, _alignment(clean))

    assert [(w.word, w.char_start, w.char_end) for w in tagged] == \
        [(w.word, w.char_start, w.char_end) for w in bare]


# --------------------------------------------------------------------------
# §8 — the vocabulary has to reach the writer or it does not exist.
# --------------------------------------------------------------------------


def test_the_prompt_block_names_every_tag_and_is_generated():
    """A hand-kept copy of a vocabulary is a copy that goes stale. This is the
    check that the prompt, the expander and the linter are reading one table."""
    from bot.prompts import delivery_vocabulary

    block = delivery_vocabulary()
    for tag in set(DIRECTIONS) | set(REGISTERS):
        assert f"[{tag.value}]" in block, f"{tag.value} is not offered to the writer"
    for name in BANNED_TAGS:
        assert f"[{name}]" in block, f"{name} is refused but never mentioned"


def test_the_prompt_block_carries_the_ceilings():
    from bot.prompts import delivery_vocabulary
    from pipeline.direction import TAGS_PER_1K_CHARS_WARN

    block = delivery_vocabulary()
    assert f"{TAGS_PER_1K_CHARS_WARN:.0f} per 1,000" in block
    for tag, cap in PER_SCRIPT_MAX.items():
        assert f"[{tag.value}] at most {cap}" in block


def test_no_writing_prompt_keeps_its_own_copy_of_the_tag_list():
    """Every one of them used to, and all four listed the same four tags —
    which is exactly how a writer ends up told about a quarter of what the
    voice can do."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    for name in ("short", "long_write", "headline", "update"):
        text = (root / "templates" / f"master_prompt_{name}.md").read_text(
            encoding="utf-8")
        assert "{{craft_rules}}" in text, f"{name} is not handed the vocabulary"
        # the old hand-kept line, which named exactly these four and no others
        assert "`[FLAT]`, `[DRY]`" not in text
        assert "[FLAT] flatter than baseline" not in text


def test_every_delivery_tag_counts_as_a_turn():
    """The unbroken-exposition check treats a declared mode shift as a turn,
    and a delivery tag is exactly that. Spelled out as four names it would
    have read the six v3 tags as no turn at all — so a chapter broken by a
    [LONG BEAT] would be flagged as twenty unbroken seconds."""
    from pipeline.gates import _TURN
    from pipeline.models import DELIVERY_TAG_TYPES

    for tag in DELIVERY_TAG_TYPES:
        assert _TURN.search(f"[{tag.value}]"), f"[{tag.value}] is not a turn"


def test_the_voice_linter_sees_the_whole_vocabulary():
    """delivery_text puts the writer's marks back so the linter can read the
    shape of a stretch. Anything it does not re-insert is invisible there."""
    from pipeline.gates import delivery_text
    from pipeline.models import DELIVERY_TAG_TYPES

    n = "One. Two. Three. Four."
    for tag in DELIVERY_TAG_TYPES:
        out = delivery_text(_Script(n, [ev(tag, 5)]))
        assert f"[{tag.value}]" in out, f"[{tag.value}] never reaches voice_lint"


@pytest.mark.parametrize("written", ["[laughs]", "[Laughs]", "[LaUgHs]"])
def test_a_banned_tag_is_caught_in_whatever_case_it_was_written(written):
    """The bracket grammar only recognises a SHOUTED type, so anything else
    is not a tag at all — it is prose, and prose gets read out loud."""
    out = direction_lint(_Script(f"He read it. {written} Then read it again."))
    assert [f.severity for f in out] == ["block"]
