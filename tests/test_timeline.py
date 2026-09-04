import json

import pytest

from pipeline.models import DELIVERY_TAG_TYPES, CueKind, ShortScript
from pipeline.parser_long import parse_long_script
from pipeline.timeline import (
    build_long_timeline,
    build_short_timeline,
    char_offset_time,
    find_anchor_time,
    plan_long_segments,
)
from pipeline.tts import mock_words

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


def test_short_timeline_structure(short_script):
    duration = 58.0
    words = mock_words(short_script.audio_script, duration)
    cues = build_short_timeline(short_script, words, duration)

    kinds = [c.kind for c in cues]
    assert kinds.count(CueKind.HOOK) == 1
    assert kinds.count(CueKind.TRANSITION) == 4          # why / gut / trap / payoff
    assert kinds.count(CueKind.HEADLINE) == len(short_script.headlines)
    assert kinds.count(CueKind.NUMBERS) == 1
    assert kinds.count(CueKind.NUMBER_ROW) == len(short_script.numbers)
    assert kinds.count(CueKind.ANNOTATION) == len(short_script.annotations)
    assert kinds.count(CueKind.ZOOM) == 1                # one numbers annotation
    assert kinds.count(CueKind.MEME) == 1
    assert kinds.count(CueKind.CONCLUSION) == 1

    # the short opens on Dennis talking; the hook card rides the same t=0
    assert kinds.count(CueKind.HOST_OPEN) == 1
    assert kinds.count(CueKind.HOST_CLOSE) == 1
    assert cues[0].t == 0.0
    assert {c.kind for c in cues if c.t == 0.0} == {CueKind.HOST_OPEN, CueKind.HOOK}
    times = [c.t for c in cues]
    assert times == sorted(times)
    assert all(0 <= t <= duration for t in times)


def test_short_beats_are_ordered(short_script):
    duration = 58.0
    words = mock_words(short_script.audio_script, duration)
    cues = build_short_timeline(short_script, words, duration)
    hook = next(c for c in cues if c.kind is CueKind.HOOK)
    headlines = [c for c in cues if c.kind is CueKind.HEADLINE]
    numbers = next(c for c in cues if c.kind is CueKind.NUMBERS)
    conclusion = next(c for c in cues if c.kind is CueKind.CONCLUSION)

    hook_end = float(hook.payload["until"])
    assert 0 < hook_end < numbers.t < conclusion.t < duration
    for i, h in enumerate(headlines):
        assert hook_end <= h.t < numbers.t, "headlines live in the why-zone"
        # each ends when the NEXT one claims the frame — or at the sheet if
        # it is the last — and never past the hold ceiling either way
        nxt = headlines[i + 1].t if i + 1 < len(headlines) else numbers.t
        assert float(h.payload["until"]) == pytest.approx(min(nxt, h.t + 8.0))


def test_short_payoff_anchors_on_conclusion_words(short_script):
    """The conclusion is spoken at the end of audio_script — the payoff
    beat must land on those exact words, not a hardcoded offset."""
    duration = 58.0
    words = mock_words(short_script.audio_script, duration)
    cues = build_short_timeline(short_script, words, duration)
    conclusion = next(c for c in cues if c.kind is CueKind.CONCLUSION)
    anchored = find_anchor_time(words, " ".join(short_script.conclusion.split()[:3]))
    assert anchored is not None
    assert conclusion.t == pytest.approx(anchored, abs=0.01)
    assert not conclusion.fallback


def test_short_number_rows_type_in_order_inside_gut_zone(short_script):
    duration = 58.0
    words = mock_words(short_script.audio_script, duration)
    cues = build_short_timeline(short_script, words, duration)
    numbers = next(c for c in cues if c.kind is CueKind.NUMBERS)
    conclusion = next(c for c in cues if c.kind is CueKind.CONCLUSION)
    rows = [c for c in cues if c.kind is CueKind.NUMBER_ROW]
    assert [c.payload["index"] for c in rows] == list(range(len(short_script.numbers)))
    for c in rows:
        assert numbers.t < c.t < conclusion.t + 0.5
    row_times = [c.t for c in rows]
    assert row_times == sorted(row_times)


def test_short_annotation_lands_on_anchor_and_after_its_row(short_script):
    duration = 58.0
    words = mock_words(short_script.audio_script, duration)
    cues = build_short_timeline(short_script, words, duration)
    ann = [c for c in cues if c.kind is CueKind.ANNOTATION]
    chart_ann = next(c for c in ann if c.payload["target"] == "chart")
    num_ann = next(c for c in ann if c.payload["target"] == "numbers")

    anchor_t = find_anchor_time(words, "today")
    assert chart_ann.t == pytest.approx(anchor_t, abs=0.01)
    assert not chart_ann.fallback

    rows = {c.payload["index"]: c.t for c in cues if c.kind is CueKind.NUMBER_ROW}
    assert num_ann.t >= rows[num_ann.payload["row_index"]] + 0.2, \
        "a scribble can never precede the row it circles"
    zoom = next(c for c in cues if c.kind is CueKind.ZOOM)
    assert zoom.t == pytest.approx(num_ann.t + 0.05, abs=0.01)
    assert zoom.payload["row_index"] == num_ann.payload["row_index"]


def test_short_annotation_fallback_when_anchor_missing(short_script):
    duration = 58.0
    raw = short_script.model_dump()
    raw["annotations"][0]["anchor_word"] = "zebra"
    script = ShortScript.model_validate(raw)
    words = mock_words(script.audio_script, duration)
    cues = build_short_timeline(script, words, duration)
    chart_ann = next(c for c in cues if c.kind is CueKind.ANNOTATION
                     and c.payload["target"] == "chart")
    assert chart_ann.fallback


def test_short_meme_lands_on_anchor(short_script):
    duration = 58.0
    words = mock_words(short_script.audio_script, duration)
    cues = build_short_timeline(short_script, words, duration)
    meme = next(c for c in cues if c.kind is CueKind.MEME)
    anchor_t = find_anchor_time(words, "vertical")
    assert meme.t == pytest.approx(anchor_t, abs=0.01)
    assert meme.payload["key"] == "fomo-stages-wish-i-bought-doodle"
    assert not meme.fallback


def test_short_timeline_tiny_duration_smoke(short_script):
    """3–5s smoke renders must still produce a sane, ordered timeline."""
    duration = 4.0
    words = mock_words(short_script.audio_script, duration)
    cues = build_short_timeline(short_script, words, duration)
    times = [c.t for c in cues]
    assert times == sorted(times)
    assert all(0 <= t < duration for t in times)
    numbers = next(c for c in cues if c.kind is CueKind.NUMBERS)
    hook = next(c for c in cues if c.kind is CueKind.HOOK)
    assert numbers.t > float(hook.payload["until"]) - 1e-6


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


def test_short_inline_plate_and_scribble_cues(short_doodles_json):
    script = ShortScript.model_validate_json(_reparse(short_doodles_json))
    duration = 55.0
    words = mock_words(script.audio_script, duration)
    cues = build_short_timeline(script, words, duration)
    plates = [c for c in cues if c.kind is CueKind.PLATE]
    scribbles = [c for c in cues if c.kind is CueKind.SCRIBBLE]
    assert len(plates) == 1
    assert plates[0].payload["value"] == "shorts/hook-card-t2"
    assert plates[0].payload["values"], "the plate carries its own content"
    assert len(scribbles) == 1
    assert scribbles[0].payload["value"] == "scrawl-oval-tight -> Net income"
    # word-anchored into the clean audio_script, and inside the runtime
    for c in plates + scribbles:
        assert 0 <= c.t <= duration
    assert [c.t for c in cues] == sorted(c.t for c in cues)


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
    """Every kind holds long enough to register; data kinds longest."""
    from pipeline.models import Cue
    from pipeline.timeline import DEFAULT_HOLDS

    for kind, hold in DEFAULT_HOLDS.items():
        cues = [Cue(t=2.0, kind=kind, payload={"value": "x"})]
        segments, _ = plan_long_segments(cues, 60.0)
        seg = next(s for s in segments if s.kind == kind.value)
        assert seg.length == pytest.approx(hold)
        assert seg.length >= 3.0, f"{kind.value} still machine-guns"
    assert DEFAULT_HOLDS[CueKind.PLATE] >= DEFAULT_HOLDS[CueKind.MEME] * 2


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


def test_short_opens_and_closes_on_the_host(short_script):
    """Dennis bookends the short: ~3-5s on camera at each end."""
    duration = 68.0
    cues = build_short_timeline(short_script, mock_words(short_script.audio_script, duration),
                                duration)
    opener = next(c for c in cues if c.kind is CueKind.HOST_OPEN)
    closer = next(c for c in cues if c.kind is CueKind.HOST_CLOSE)

    assert opener.t == 0.0
    assert 3.0 <= float(opener.payload["until"]) <= 5.0
    assert float(closer.payload["until"]) == duration
    assert 3.0 <= duration - closer.t <= 5.0
    # the closer must not open before the payoff it rides on
    conclusion = next(c for c in cues if c.kind is CueKind.CONCLUSION)
    assert closer.t >= conclusion.t - 0.01


def test_cheap_or_trap_is_held_long_enough_to_read(short_script):
    from pipeline.timeline import SHORT_MIN_READABLE_S

    duration = 68.0
    cues = build_short_timeline(short_script, mock_words(short_script.audio_script, duration),
                                duration)
    trap = next(c for c in cues if c.kind is CueKind.CHEAP_OR_TRAP)
    numbers = next(c for c in cues if c.kind is CueKind.NUMBERS)

    assert float(trap.payload["until"]) - trap.t >= SHORT_MIN_READABLE_S - 0.01
    # it sits between the numbers sheet and the payoff, and the sheet gets
    # its own readable window first
    assert trap.t - numbers.t >= SHORT_MIN_READABLE_S - 0.01
    rows = [c for c in cues if c.kind is CueKind.NUMBER_ROW]
    assert max(c.t for c in rows) <= trap.t, "the sheet must finish typing before the cut"


def test_a_short_without_the_trap_beat_still_builds(short_script):
    """The beat is optional — scripts written to the four-beat format parse."""
    script = short_script.model_copy(update={"cheap_or_trap": None})
    duration = 68.0
    cues = build_short_timeline(script, mock_words(script.audio_script, duration), duration)
    assert not [c for c in cues if c.kind is CueKind.CHEAP_OR_TRAP]
    assert next(c for c in cues if c.kind is CueKind.CONCLUSION)


def test_beat_variants_are_deterministic_and_rotate():
    from pipeline.timeline import SHORT_BEAT_VARIANTS, pick_beat_variant

    for beat, options in SHORT_BEAT_VARIANTS.items():
        assert pick_beat_variant(beat, "abc123") == pick_beat_variant(beat, "abc123")
        picked = {pick_beat_variant(beat, f"sha{i:04d}") for i in range(400)}
        assert picked == set(options), f"{beat} never reached every variant"

    # two different scripts should not share every beat layout
    a = {b: pick_beat_variant(b, "script-one") for b in SHORT_BEAT_VARIANTS}
    b = {b: pick_beat_variant(b, "script-two") for b in SHORT_BEAT_VARIANTS}
    assert a != b


def test_beat_variants_reach_the_cues(short_script):
    duration = 68.0
    cues = build_short_timeline(short_script, mock_words(short_script.audio_script, duration),
                                duration)
    hook = next(c for c in cues if c.kind is CueKind.HOOK)
    numbers = next(c for c in cues if c.kind is CueKind.NUMBERS)
    conclusion = next(c for c in cues if c.kind is CueKind.CONCLUSION)
    for cue, beat in ((hook, "hook"), (numbers, "gutcheck"), (conclusion, "payoff")):
        from pipeline.timeline import SHORT_BEAT_VARIANTS
        assert cue.payload["variant"] in SHORT_BEAT_VARIANTS[beat]


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
    from pipeline.timeline import _LONG_NO_CUE_REASONS, _TAG_TO_KIND

    undecided = sorted(
        t.value for t in TagType
        if t not in _TAG_TO_KIND
        and t not in DELIVERY_TAG_TYPES
        and t not in _LONG_NO_CUE_REASONS
    )
    assert not undecided, (
        f"{undecided} reach a LONG script but build_long_timeline has no "
        f"CueKind for them and no recorded reason they draw nothing. Map them "
        f"in _TAG_TO_KIND or record why in _LONG_NO_CUE_REASONS."
    )


def test_every_tag_type_is_drawn_or_deliberately_not_on_short():
    from pipeline.models import SHORT_TAG_TYPES, TagType
    from pipeline.timeline import _SHORT_NO_CUE_REASONS, _SHORT_TAG_TO_KIND

    undecided = sorted(
        t.value for t in TagType
        # a tag a SHORT may not carry at all is the parser's problem, not the
        # timeline's — the guarantee here covers everything that can arrive.
        if t in SHORT_TAG_TYPES
        and t not in _SHORT_TAG_TO_KIND
        and t not in _SHORT_NO_CUE_REASONS
    )
    assert not undecided, (
        f"{undecided} are allowed in a SHORT but build_short_timeline neither "
        f"cues them nor records why not."
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
    before the paid TTS call — because at render time it is already too late."""
    from pipeline.timeline import unrenderable_long_tags

    script, _ = parse_long_script(
        "The filing says one thing. [SHOW ARTICLE] The tape says another.",
        "EXMPL", settings,
    )
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


def test_no_short_beat_is_planned_to_hold_past_the_ceiling(settings):
    """The invariant, at the layer that decides it. A composition may not sit
    unchanged longer than the format's own longest legitimate data hold."""
    from pipeline.timeline import SHORT_DATA_HOLD_S

    script = _sndk_shaped(settings)
    duration = 80.0
    ceiling = settings.short_max_hold_s
    cues = build_short_timeline(script, mock_words(script.audio_script, duration),
                                duration, max_hold_s=ceiling)

    over = []
    for c in cues:
        until = c.payload.get("until")
        # Beats whose window is a STAGE CLAIM rather than a drawn composition:
        # the thing on screen changes inside them. NUMBERS is carried by its
        # NUMBER_ROW cues and CHEAP_OR_TRAP by its TRAP_LINE cues; the payoff
        # and the bookends legitimately own the tail of the frame.
        if until is None or c.kind in (CueKind.NUMBERS, CueKind.CHEAP_OR_TRAP,
                                       CueKind.CONCLUSION, CueKind.HOST_CLOSE,
                                       CueKind.HOST_OPEN):
            continue
        if float(until) - c.t > ceiling + 1e-6:
            over.append((c.kind.value, round(c.t, 1), round(float(until) - c.t, 1)))
    assert not over, f"planned to hold past {ceiling}s: {over}"
    assert ceiling == SHORT_DATA_HOLD_S[1]


def test_the_trap_lands_one_clause_at_a_time_not_as_a_paragraph(settings):
    """It was a single panel carrying forty words, held from the moment it
    landed until the payoff, while the caption underneath read it aloud."""
    script = _sndk_shaped(settings)
    duration = 80.0
    cues = build_short_timeline(script, mock_words(script.audio_script, duration),
                                duration, max_hold_s=settings.short_max_hold_s)

    lines = [c for c in cues if c.kind is CueKind.TRAP_LINE]
    assert len(lines) >= 3, "the paragraph was not broken into beats"
    times = [c.t for c in lines]
    assert times == sorted(times)
    # they must be spread across the beat, not stacked on one instant — an
    # anchor resolving outside the beat's own window used to collapse them
    assert len(set(round(t, 1) for t in times)) == len(times), times
    trap = next(c for c in cues if c.kind is CueKind.CHEAP_OR_TRAP)
    assert max(times) < float(trap.payload["until"])


def test_headline_cards_are_removed_not_accumulated(settings):
    """The Citi card landed at ~10s and was still there at 30s with the second
    stacked under it, both shrunk to roughly 9px-equivalent on a phone."""
    script = _sndk_shaped(settings)
    duration = 80.0
    cues = build_short_timeline(script, mock_words(script.audio_script, duration),
                                duration, max_hold_s=settings.short_max_hold_s)

    heads = sorted((c for c in cues if c.kind is CueKind.HEADLINE), key=lambda c: c.t)
    assert len(heads) >= 2
    for a, b in zip(heads, heads[1:]):
        assert float(a.payload["until"]) <= b.t + 1e-6, (
            "a headline is still on screen when the next one lands")
