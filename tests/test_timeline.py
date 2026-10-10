import json

import pytest

from pipeline.models import DELIVERY_TAG_TYPES, CueKind, ShortScript
from pipeline.parser_long import parse_long_script
from pipeline.timeline import (
    build_long_timeline,
    char_offset_time,
    find_anchor_time,
    plan_long_segments,
)
from pipeline.tts import mock_words


# These are TIMELINE tests, driven by one-line snippets that sit far below the
# LONG parser's length floor (C1). The floor is asserted at its real default in
# `tests/test_parser_long.py`.
@pytest.fixture()
def settings(settings):
    return settings.model_copy(update={"long_min_chars": 0})


# ------------------------------------------------------------------ anchors


def _words(text: str, duration: float = 30.0):
    return mock_words(text, duration)


def test_anchor_single_word():
    words = _words("They burn cash on operations daily.")
    t = find_anchor_time(words, "cash")
    assert t == words[2].start


def test_anchor_phrase():
    words = _words("Free cash flow yield is negative.")
    t = find_anchor_time(words, "cash flow")
    assert t == words[1].start


def test_anchor_case_and_punctuation_insensitive():
    words = _words("Conclusion: sideways, filed and forgotten.")
    assert find_anchor_time(words, "Sideways") == words[1].start
    assert find_anchor_time(words, "FORGOTTEN") == words[-1].start


def test_anchor_not_found_returns_none():
    words = _words("No such token here.")
    assert find_anchor_time(words, "zebra") is None
    assert find_anchor_time(words, "such zebra") is None
    assert find_anchor_time([], "cash") is None


def test_anchor_first_occurrence_wins():
    words = _words("cash today, cash tomorrow")
    assert find_anchor_time(words, "cash") == words[0].start


# -------------------------------------------------------------- char offset


def test_char_offset_inside_word():
    text = "Alpha beta gamma"
    words = _words(text)
    off = text.index("beta") + 2  # middle of "beta"
    assert char_offset_time(words, off) == words[1].start


def test_char_offset_in_whitespace_snaps_forward():
    text = "Alpha beta"
    words = _words(text)
    assert char_offset_time(words, 5) == words[1].start  # the space


def test_char_offset_past_end_uses_last_word():
    text = "Alpha beta"
    words = _words(text)
    assert char_offset_time(words, 999) == words[-1].start
    assert char_offset_time([], 5) == 0.0


def test_char_offset_zero_is_first_word():
    words = _words("Alpha beta")
    assert char_offset_time(words, 0) == words[0].start


# ---------------------------------------------------------- SHORT timeline


@pytest.fixture()
def short_script(short_valid_json) -> ShortScript:
    return ShortScript.model_validate(json.loads(short_valid_json))


















# ----------------------------------------------------------- LONG timeline


def test_long_timeline_offsets_hit_words(long_valid_text, settings):
    script, _ = parse_long_script(long_valid_text, "EXMPL", settings)
    duration = 120.0
    words = mock_words(script.narration, duration)
    cues = build_long_timeline(script, words, duration)

    # every tag EXCEPT delivery direction, which is audio and draws nothing
    drawn = [e for e in script.events if e.type not in DELIVERY_TAG_TYPES]
    assert len(cues) == len(drawn)
    times = [c.t for c in cues]
    assert times == sorted(times)

    first_clip = next(c for c in cues if c.kind is CueKind.CLIP)
    assert first_clip.payload["value"] == "tumbleweed"
    expected = char_offset_time(words, script.events[0].char_offset)
    assert first_clip.t == pytest.approx(expected)

    kinds = {c.kind for c in cues}
    assert {CueKind.CLIP, CueKind.IMG, CueKind.CHART, CueKind.FILING,
            CueKind.MEME, CueKind.SOUND} <= kinds


def test_long_timeline_img_and_product_share_kind(settings):
    script, _ = parse_long_script(
        "See [IMG: factory floor] the plant. And [PRODUCT: the dashboard] the app.",
        "EXMPL", settings,
    )
    cues = build_long_timeline(script, mock_words(script.narration, 20.0), 20.0)
    img_cues = [c for c in cues if c.kind is CueKind.IMG]
    assert len(img_cues) == 2
    assert img_cues[0].payload["tag"] == "IMG"
    assert img_cues[1].payload["tag"] == "PRODUCT"




def test_long_annotations_do_not_claim_segments(long_doodles_text, settings):
    """An annotation rides over whatever is showing. It never cuts.

    It is drawn in ATTENTION and spends the frame's one attention, which is a
    reason to put it ON a frame rather than to make it a frame of its own.
    """
    script, _ = parse_long_script(long_doodles_text, "EXMPL", settings)
    duration = 90.0
    words = mock_words(script.narration, duration)
    cues = build_long_timeline(script, words, duration)
    assert any(c.kind is CueKind.PLATE for c in cues)
    assert any(c.kind is CueKind.SCRIBBLE for c in cues)
    assert any(c.kind is CueKind.SCREENGRAB for c in cues)
    segments, _ = plan_long_segments(cues, duration)
    kinds = {s.kind for s in segments}
    assert "scribble" not in kinds
    assert "screengrab" in kinds, "a screengrab IS a base frame"


def _reparse(raw: str) -> str:
    """Run the short parser so inline tags become inline_events, then dump
    the model JSON for a clean round-trip in tests."""
    from config import Settings
    from pipeline.parser_short import parse_short_script

    s = Settings(MOCK_MODE=True, _env_file=None)
    script, _ = parse_short_script(raw, s)
    return script.model_dump_json()


# ------------------------------------------------------------ segment plan


def _tiled(segments, duration):
    assert segments[0].start == 0.0
    assert segments[-1].end == pytest.approx(duration)
    for a, b in zip(segments, segments[1:]):
        assert a.end == pytest.approx(b.start)


def test_untagged_narration_is_the_host_holding_the_frame():
    """No tags means Dennis, not a run of filler cards."""
    segments, warnings = plan_long_segments([], 10.0)
    _tiled(segments, 10.0)
    assert [s.kind for s in segments] == ["host"]
    assert segments[0].length == pytest.approx(10.0)
    assert segments[0].payload["layout"] == "host-full"


def test_a_long_untagged_stretch_changes_shot():
    """One segment per gap meant ninety untagged seconds was ninety seconds
    of a single frame with a mouth flap on it — and the planner considered
    that correct, so nothing said so."""
    from pipeline.timeline import MAX_HOST_BEAT_S

    segments, warnings = plan_long_segments([], 95.0)
    _tiled(segments, 95.0)
    assert {s.kind for s in segments} == {"host"}, "still all Dennis"
    assert len(segments) > 1, "the shot never changes"
    assert max(s.length for s in segments) <= MAX_HOST_BEAT_S + 1e-6
    variants = [s.payload["variant"] for s in segments]
    assert len(set(variants)) == len(variants), "consecutive beats repeat a shot"


def test_a_long_untagged_stretch_is_named_in_the_warnings():
    """Splitting keeps the frame alive, but the writer should see where the
    video goes visually silent."""
    _, warnings = plan_long_segments([], 95.0)
    assert any("95s" in w or "0s to 95s" in w for w in warnings), warnings


def test_a_short_gap_is_not_split():
    from pipeline.timeline import MAX_HOST_BEAT_S

    segments, _ = plan_long_segments([], MAX_HOST_BEAT_S - 0.5)
    assert len(segments) == 1


def test_segments_with_cues(long_valid_text, settings):
    script, _ = parse_long_script(long_valid_text, "EXMPL", settings)
    # The fixture's own runtime. At 120s the planner was being handed four
    # minutes of tagged script in two, so it deferred visuals off the end and
    # the test read that as a lost meme — a fault in the test's clock, not in
    # the planner.
    duration = script.word_count / settings.mock_wps_long
    words = mock_words(script.narration, duration)
    cues = build_long_timeline(script, words, duration)
    segments, warnings = plan_long_segments(cues, duration)
    _tiled(segments, duration)

    clips = [s for s in segments if s.kind == "clip"]
    assert len(clips) >= 3
    # A clip segment exists because a clip cue does. The old assertion counted
    # the other way round — that no cue was ever dropped — which is not the
    # contract: the planner drops a cue it cannot give a readable hold, and a
    # script carrying seventeen plates gives it more reason to.
    clip_cues = [c for c in cues if c.kind is CueKind.CLIP]
    assert len(clips) <= len(clip_cues)
    kinds = {s.kind for s in segments}
    assert {"clip", "img", "chart", "filing", "meme", "host", "plate"} <= kinds
    assert all(s.length >= 0.25 - 1e-9 for s in segments)


def test_segments_meme_holds_shorter_than_clips():
    from pipeline.models import Cue

    cues = [
        Cue(t=5.0, kind=CueKind.MEME, payload={"value": "bagholder"}),
        Cue(t=20.0, kind=CueKind.CLIP, payload={"value": "clown"}),
    ]
    segments, _ = plan_long_segments(cues, 40.0)
    meme = next(s for s in segments if s.kind == "meme")
    clip = next(s for s in segments if s.kind == "clip")
    assert meme.length < clip.length, "a meme is a beat, a clip is a thought"
    _tiled(segments, 40.0)


def test_stacked_cues_are_deferred_not_dropped(settings):
    """Two tags on adjacent words: the second waits its turn rather than
    cutting the first one short."""
    from pipeline.models import Cue

    cues = [
        Cue(t=5.0, kind=CueKind.CLIP, payload={"value": "a"}),
        Cue(t=5.1, kind=CueKind.CLIP, payload={"value": "b"}),
    ]
    segments, warnings = plan_long_segments(cues, 30.0)
    _tiled(segments, 30.0)
    kept = [s for s in segments if s.kind == "clip"]
    assert [k.payload["value"] for k in kept] == ["a", "b"]
    assert kept[0].end == pytest.approx(kept[1].start)
    assert any("deferred" in w for w in warnings)


def test_segments_cue_near_end_dropped():
    from pipeline.models import Cue

    cues = [Cue(t=19.9, kind=CueKind.CLIP, payload={"value": "a"})]
    segments, warnings = plan_long_segments(cues, 20.0)
    _tiled(segments, 20.0)
    assert all(s.kind == "host" for s in segments)
    assert any("no longer fits before the end" in w for w in warnings)


def test_data_visuals_are_never_cut_short():
    """A chart the viewer is still reading is not cut for the next tag."""
    from pipeline.models import Cue
    from pipeline.timeline import MIN_READABLE_S

    cues = [
        Cue(t=2.0, kind=CueKind.CHART, payload={"value": "revenue"}),
        Cue(t=3.5, kind=CueKind.CLIP, payload={"value": "b"}),
    ]
    segments, _ = plan_long_segments(cues, 40.0)
    chart = next(s for s in segments if s.kind == "chart")
    clip = next(s for s in segments if s.kind == "clip")
    assert chart.length >= MIN_READABLE_S
    assert clip.start >= chart.end - 1e-9, "the clip waits for the chart to finish"
    _tiled(segments, 40.0)


def test_holds_are_deliberate_not_machine_gun():
    """Every glanced kind holds long enough to register."""
    from pipeline.models import Cue
    from pipeline.timeline import DEFAULT_HOLDS

    for kind, hold in DEFAULT_HOLDS.items():
        cues = [Cue(t=2.0, kind=kind, payload={"value": "x"})]
        segments, _ = plan_long_segments(cues, 60.0)
        seg = next(s for s in segments if s.kind == kind.value)
        assert seg.length == pytest.approx(hold)
        assert seg.length >= 3.0, f"{kind.value} still machine-guns"


def test_a_readable_beat_stays_up_until_the_writer_moves_on():
    """Item 31: a plate holds to the next tag, [SCENE], paragraph or chapter
    bookend — not a fixed 7.0 s — never under the floor, never over the cap."""
    from pipeline.models import Cue
    from pipeline.timeline import MAX_READABLE_S, MIN_READABLE_S, READABLE_KINDS

    def plate(t):
        return Cue(t=t, kind=CueKind.PLATE, payload={"value": "p"})

    def first(segs, kind="plate"):
        return next(s for s in segs if s.kind == kind)

    # to the next visual tag
    segs, _ = plan_long_segments([plate(2.0), Cue(t=19.0, kind=CueKind.CLIP,
                                                  payload={"value": "c"})], 60.0)
    assert (first(segs).start, first(segs).end) == pytest.approx((2.0, 19.0))
    # to the next [SCENE]
    segs, _ = plan_long_segments(
        [plate(2.0), Cue(t=14.0, kind=CueKind.SCENE,
                         payload={"values": {"room": "room/desk-side"}})], 60.0)
    assert first(segs).end == pytest.approx(14.0)
    # to the end of its paragraph, the nearest of all
    segs, _ = plan_long_segments([plate(2.0)], 60.0, paragraphs=[11.0, 40.0])
    assert first(segs).end == pytest.approx(11.0)
    # to the next chapter's bookend
    segs, _ = plan_long_segments([plate(2.0)], 60.0, chapter_starts=[20.0])
    assert first(segs).end == pytest.approx(20.0 - 2.5)
    # never under the floor: the next tag waits
    segs, _ = plan_long_segments([plate(2.0)], 60.0, paragraphs=[3.0])
    assert first(segs).length == pytest.approx(MIN_READABLE_S)
    # never over the cap, and the writer is told where
    segs, warnings = plan_long_segments([plate(2.0)], 60.0)
    assert first(segs).length == pytest.approx(MAX_READABLE_S)
    assert any("break the paragraph" in w for w in warnings)
    for kind in READABLE_KINDS:
        segs, _ = plan_long_segments(
            [Cue(t=2.0, kind=kind, payload={"value": "x"})], 60.0,
            paragraphs=[16.0])
        assert first(segs, kind.value).end == pytest.approx(16.0)


def test_a_plate_fills_the_frame_unless_the_writer_puts_him_beside_it():
    """Items 30 and 11: two-shot only on `with=`."""
    from pipeline.models import Cue

    cues = [Cue(t=2.0, kind=CueKind.PLATE, payload={"value": "a"}),
            Cue(t=12.0, kind=CueKind.CHART, payload={"value": "price",
                                                     "beside": "dennis"}),
            Cue(t=22.0, kind=CueKind.PLATE,
                payload={"value": "b", "beside": "host/gesturing-at-plate"})]
    segs, _ = plan_long_segments(cues, 40.0)
    layouts = [s.payload["layout"] for s in segs if s.kind != "host"]
    assert layouts == ["cutaway-full", "two-shot", "two-shot"]


def test_paragraph_starts_are_the_first_word_after_each_blank_line():
    from pipeline.timeline import paragraph_starts
    from pipeline.tts import mock_words

    text = "One two three.\n\nFour five six.\n  \nSeven."
    words = mock_words(text, 10.0)
    got = paragraph_starts(text, words)
    by_word = {w.word: w.start for w in words}
    assert got == [by_word["Four"], by_word["Seven."]]


# ------------------------------------------------------ scene-variety planner


def test_host_beats_get_distinct_looks():
    """Consecutive host beats are numbered so the renderer never returns to
    an identical shot."""
    from pipeline.models import Cue

    cues = [Cue(t=t, kind=CueKind.CLIP, payload={"value": f"c{i}"})
            for i, t in enumerate((10.0, 25.0, 40.0, 55.0))]
    segments, _ = plan_long_segments(cues, 80.0)
    hosts = [s for s in segments if s.kind == "host"]
    assert len(hosts) >= 4
    variants = [h.payload["variant"] for h in hosts]
    assert variants == sorted(variants) and len(set(variants)) == len(variants)


def test_adjacent_same_type_real_cuts_are_flagged():
    from pipeline.models import Cue

    cues = [
        Cue(t=2.0, kind=CueKind.CLIP, payload={"value": "a"}),
        Cue(t=3.5, kind=CueKind.CLIP, payload={"value": "b"}),
    ]
    _, warnings = plan_long_segments(cues, 30.0)
    assert any("same visual type" in w for w in warnings), \
        "two clips back-to-back should warn the variety planner"


# --------------------------------------------------------------------------
# SHORT: host bookends, the cheap-or-trap hold, deterministic beat variants
# --------------------------------------------------------------------------












# ------------------------------------------------- tag -> cue coverage
#
# The regression these exist for: _TAG_TO_KIND was a bare dict lookup covering
# 17 of 22 TagTypes, so every LONG carrying a [BEAT] — the tag the write prompt
# calls "the single most useful tool you have" — died with a KeyError inside
# build_long_timeline. It died AFTER the paid TTS call, and no fixture in the
# repo contained a delivery tag, so ~190 green tests never touched it.
#
# The point of these two is that adding a TagType now fails here, loudly, until
# somebody records what it draws or why it draws nothing.


def test_every_tag_type_is_drawn_or_deliberately_not_on_long():
    from pipeline.models import DELIVERY_TAG_TYPES, TagType
    from pipeline.timeline import EPISODE_TAG_TYPES, _LONG_NO_CUE_REASONS, _TAG_TO_KIND

    # An episode tag ([BOARD]) is decided too: read once by the render for
    # the whole video, never a cue.
    undecided = sorted(
        t.value for t in TagType
        if t not in _TAG_TO_KIND
        and t not in DELIVERY_TAG_TYPES
        and t not in _LONG_NO_CUE_REASONS
        and t not in EPISODE_TAG_TYPES
    )
    assert not undecided, (
        f"{undecided} reach a LONG script but build_long_timeline has no "
        f"CueKind for them and no recorded reason they draw nothing. Map them "
        f"in _TAG_TO_KIND or record why in _LONG_NO_CUE_REASONS."
    )




def test_a_delivery_tag_on_a_long_renders_instead_of_crashing(long_valid_text, settings):
    """[BEAT]/[SIGH]/[FLAT]/[DRY] are audio direction: they must reach TTS and
    draw nothing, rather than KeyError-ing the render after the money is spent."""
    from pipeline.models import DELIVERY_TAG_TYPES

    script, _ = parse_long_script(long_valid_text, "EXMPL", settings)
    delivery = [e for e in script.events if e.type in DELIVERY_TAG_TYPES]
    assert delivery, "the long fixture no longer exercises delivery tags"

    duration = 120.0
    cues = build_long_timeline(script, mock_words(script.narration, duration), duration)

    assert len(cues) == len(script.events) - len(delivery)
    assert not [c for c in cues
                if c.payload.get("tag") in {e.type.value for e in delivery}]


def test_an_unmapped_long_tag_is_reported_not_swallowed(settings):
    """A tag with no CueKind and no recorded reason is a blocker at approval —
    before the paid TTS call — because at render time it is already too late.

    `[SHOW ARTICLE]` is retired, so only a script saved before that can still
    carry one; it loads, and is skipped with its reason."""
    from pipeline.models import LongScript, TagEvent, TagType
    from pipeline.timeline import unrenderable_long_tags

    script, _ = parse_long_script(
        "The filing says one thing. The tape says another.", "EXMPL", settings,
    )
    saved = script.model_dump(mode="json")
    saved["events"].append(TagEvent(
        type=TagType.SHOW_ARTICLE, payload="", char_offset=27,
        raw_offset=27).model_dump(mode="json"))
    script = LongScript.model_validate_json(json.dumps(saved))
    reported = unrenderable_long_tags(script)
    assert [e.type.value for e, _ in reported] == ["SHOW ARTICLE"]
    # decided-and-skipped carries a reason; unmapped carries none, and
    # validate_long_script blocks on exactly that difference.
    assert reported[0][1]


def test_delivery_tags_are_never_reported_as_unrenderable(long_valid_text, settings):
    from pipeline.timeline import unrenderable_long_tags

    script, _ = parse_long_script(long_valid_text, "EXMPL", settings)
    assert unrenderable_long_tags(script) == []


# ------------------------------------------------- the hold ceiling
#
# Measured on a real SNDK short: four compositions carried 40 of its 79
# seconds — a 12.5s still, an 11.5s still, a 9.5s still — with 72% of the
# runtime inside holds of 3s or more, in a format whose spec is fast cuts.
# Two causes, both here: the value-trap read was one text panel carrying a
# whole paragraph and held to the payoff, and headline cards were added and
# never removed.


def _sndk_shaped(settings):
    """A SHORT with the shape that produced the long holds: a multi-clause
    trap whose opening words are spoken EARLY (so the beat anchors early and
    then has nothing to do until the payoff), and two headlines across a wide
    why-span."""
    import json

    from pipeline.parser_short import parse_short_script

    raw = json.loads(
        (FIXTURES / "scripts" / "short_valid.json").read_text(encoding="utf-8")
        if (FIXTURES := __import__("pathlib").Path(__file__).resolve().parents[1]
            / "fixtures") else "")
    raw["cheap_or_trap"] = (
        "Twelve times earnings is not cheap when the earnings are falling. "
        "Revenue fell forty one percent last year, and the buyback stopped in "
        "March. Management calls it a transition.")
    raw["audio_script"] = (
        "Twelve times earnings is what the screen says. " + raw["audio_script"]
        + " Revenue fell forty one percent last year, and the buyback stopped "
        "in March. Management calls it a transition, which is a word that buys "
        "time. So the multiple is not the story, the direction is, and the "
        "direction is down.")
    script, _ = parse_short_script(json.dumps(raw), settings)
    return script








# ------------------------------------------------------- the written hold


def _long_segments(raw: str, settings, duration: float = 90.0):
    script, _ = parse_long_script(raw, "EXMPL", settings)
    words = mock_words(script.narration, duration)
    cues = build_long_timeline(script, words, duration)
    segments, warnings = plan_long_segments(cues, duration)
    return script, segments, warnings


_FILLER = "Words that go on for a while so nothing collides. " * 12


def test_the_written_hold_is_the_length_on_screen(settings):
    """`DEFAULT_HOLDS` is what to do when nobody decided. Somebody did."""
    raw = (f"{_FILLER} [CLIP: lebron three pointer | hold=2.5] {_FILLER} "
           f"[MEME: bagholder | hold=2.0] {_FILLER}")
    _, segments, _ = _long_segments(raw, settings)
    clip = next(s for s in segments if s.kind == "clip")
    meme = next(s for s in segments if s.kind == "meme")
    assert clip.length == pytest.approx(2.5, abs=0.01)
    assert meme.length == pytest.approx(2.0, abs=0.01)


def test_a_bare_tag_still_gets_the_format_s_own_default(settings):
    """The regression that matters: every script already written plans
    identically. A bare [CLIP] is 5s and a bare [MEME] is 3s, as they were."""
    from pipeline.timeline import DEFAULT_HOLDS

    raw = f"{_FILLER} [CLIP: tumbleweed] {_FILLER} [MEME: bagholder] {_FILLER}"
    script, segments, _ = _long_segments(raw, settings)
    clip = next(s for s in segments if s.kind == "clip")
    meme = next(s for s in segments if s.kind == "meme")
    assert clip.length == pytest.approx(DEFAULT_HOLDS[CueKind.CLIP], abs=0.01)
    assert meme.length == pytest.approx(DEFAULT_HOLDS[CueKind.MEME], abs=0.01)

    # …and the cue does not carry a `hold` at all, rather than carrying one
    # that happens to equal the default. The planner reads its presence.
    cues = build_long_timeline(script, mock_words(script.narration, 90.0), 90.0)
    for c in cues:
        if c.kind in (CueKind.CLIP, CueKind.MEME):
            assert "hold" not in c.payload




def test_the_long_parser_strips_a_retired_tag_and_says_so(settings):
    script, warnings = parse_long_script(
        "The filing says one thing. [SHOW ARTICLE] The tape says another.",
        "EXMPL", settings,
    )
    assert not [e for e in script.events if e.type.value == "SHOW ARTICLE"]
    assert any("[SHOW ARTICLE] is no longer part of the grammar" in w
               for w in warnings), warnings


# ------------------------------------------------------- chapters and queues


def _plate(t, name, order=0):
    from pipeline.models import Cue

    return Cue(t=t, kind=CueKind.PLATE, payload={"value": name, "order": order})


def test_two_tags_on_one_word_share_the_chapter_in_order():
    """Two pictures for one line: the first holds its minimum and the second
    follows. Read as "the next visual said later", the first held to the
    chapter's end and the second went up in the next chapter."""
    from pipeline.timeline import MIN_READABLE_S

    cues = [_plate(10.0, "a", 0), _plate(10.0, "b", 1)]
    report: list = []
    segments, _ = plan_long_segments(cues, 60.0, chapter_starts=[0.0, 30.0],
                                     report=report)
    _tiled(segments, 60.0)
    a, b = [s for s in segments if s.kind == "plate"]
    assert a.length == pytest.approx(MIN_READABLE_S)
    assert b.start == pytest.approx(a.end) and b.end <= 30.0
    assert [r["what"] for r in report] == ["late"]


def test_a_visual_is_never_put_up_in_the_next_chapter():
    """Queued behind a plate that holds to the chapter's end, the next one is
    dropped, not shown under the next chapter's words."""
    # a holds 21-26, into the closing beat; b would go up after the card
    cues = [_plate(21.0, "a", 0), _plate(22.0, "b", 1)]
    report: list = []
    segments, warnings = plan_long_segments(cues, 60.0, chapter_starts=[0.0, 28.0],
                                            report=report)
    _tiled(segments, 60.0)
    shown = [s.payload["value"] for s in segments if s.kind == "plate"]
    assert shown == ["a"]
    assert [(r["what"], r["cue"].payload["value"]) for r in report] == [("dropped", "b")]
    assert any("[PLATE: b] dropped" in w for w in warnings)


def test_a_visual_ends_on_the_next_chapter_s_card_at_the_latest():
    from pipeline.timeline import MIN_BEFORE_CHAPTER_S

    # 4 s before the card: up for 4 s and gone on the card, not 5 s across it
    segments, _ = plan_long_segments([_plate(24.0, "a")], 60.0,
                                     chapter_starts=[0.0, 28.0])
    a = next(s for s in segments if s.kind == "plate")
    assert a.start == pytest.approx(24.0) and a.end == pytest.approx(28.0)
    # under the floor before the card, it is dropped
    report: list = []
    t = 28.0 - 2.5 - 0.1   # just ahead of the closing beat
    segments, _ = plan_long_segments([_plate(t - MIN_BEFORE_CHAPTER_S + 0.6, "a"),
                                      _plate(t, "b", 1)], 60.0,
                                     chapter_starts=[0.0, 28.0], report=report)
    _tiled(segments, 60.0)
    assert all(s.payload.get("value") != "b" for s in segments)
    assert report and report[-1]["what"] == "dropped"


def test_the_approval_screen_names_visuals_that_go_up_late(settings):
    """Three tags inside four seconds queue behind each other's five-second
    minimum; the writer hears where, in the script's words, before a cent."""
    from pathlib import Path

    from pipeline.parser_long import late_visual_warnings

    text = (Path(__file__).parent.parent / "fixtures/scripts/long_sample.txt").read_text(
        encoding="utf-8")
    script, _ = parse_long_script(text, "EXMPL", settings)
    lines = late_visual_warnings(script, settings)
    assert any(line.startswith('[CHART: price] before "Five years of the share"')
               and "goes up about" in line for line in lines), lines


def test_a_chart_of_what_a_chart_plate_just_drew_is_dropped():
    """One figure, one picture: [CHART: revenue] after a revenue line plate in
    the same chapter was two revenue charts five seconds apart, one from
    zero and one from 400. The writer's plate stays; the chart goes. In the
    next chapter, or of another figure, it is a picture of its own."""
    from pipeline.models import Cue

    line = Cue(t=5.0, kind=CueKind.PLATE, payload={
        "value": "charts/line-6y-16x9", "order": 0,
        "values": {"unit": "Revenue, $M", "value-1": "400"}})

    def chart(t, metric, order):
        return Cue(t=t, kind=CueKind.CHART, payload={"value": metric, "order": order})

    report: list = []
    segments, warnings = plan_long_segments(
        [line, chart(12.0, "revenue", 1), chart(20.0, "fcf", 2), chart(40.0, "revenue", 3)],
        60.0, chapter_starts=[0.0, 30.0], report=report)
    _tiled(segments, 60.0)
    shown = [(s.kind, s.payload.get("value")) for s in segments if s.kind != "host"]
    assert shown == [("plate", "charts/line-6y-16x9"), ("chart", "fcf"),
                     ("chart", "revenue")], shown
    assert [(r["what"], r["cue"].t) for r in report] == [("dropped", 12.0)]
    assert "already charts revenue" in report[0]["why"]
    assert any("[CHART: revenue] dropped" in w for w in warnings)
