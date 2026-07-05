import json

import pytest

from pipeline.models import CueKind, ShortScript
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
    assert kinds.count(CueKind.TRANSITION) == 3          # why / gut / payoff
    assert kinds.count(CueKind.HEADLINE) == len(short_script.headlines)
    assert kinds.count(CueKind.NUMBERS) == 1
    assert kinds.count(CueKind.NUMBER_ROW) == len(short_script.numbers)
    assert kinds.count(CueKind.ANNOTATION) == len(short_script.annotations)
    assert kinds.count(CueKind.ZOOM) == 1                # one numbers annotation
    assert kinds.count(CueKind.MEME) == 1
    assert kinds.count(CueKind.CONCLUSION) == 1

    assert cues[0].kind is CueKind.HOOK and cues[0].t == 0.0
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
    for h in headlines:
        assert hook_end <= h.t < numbers.t, "headlines live in the why-zone"
        assert float(h.payload["until"]) == pytest.approx(numbers.t)


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
    assert meme.payload["key"] == "stonks-man-up-only"
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

    assert len(cues) == len(script.events)
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


# ------------------------------------------------------------ segment plan


def _tiled(segments, duration):
    assert segments[0].start == 0.0
    assert segments[-1].end == pytest.approx(duration)
    for a, b in zip(segments, segments[1:]):
        assert a.end == pytest.approx(b.start)


def test_segments_no_cues_all_filler():
    segments, warnings = plan_long_segments([], 22.0)
    _tiled(segments, 22.0)
    assert all(s.kind == "filler" for s in segments)
    assert all(s.length <= 3.0 + 1e-6 for s in segments), "fast cuts: ≤3s"
    assert all(s.length >= 1.5 - 1e-6 for s in segments)


def test_segments_with_cues(long_valid_text, settings):
    script, _ = parse_long_script(long_valid_text, "EXMPL", settings)
    duration = 120.0
    words = mock_words(script.narration, duration)
    cues = build_long_timeline(script, words, duration)
    segments, warnings = plan_long_segments(cues, duration)
    _tiled(segments, duration)

    clips = [s for s in segments if s.kind == "clip"]
    assert len(clips) >= 3
    clip_cues = [c for c in cues if c.kind is CueKind.CLIP]
    started = {round(s.start, 3) for s in clips}
    hit = sum(1 for c in clip_cues if round(c.t, 3) in started)
    assert hit >= len(clips)  # every kept clip segment maps to a cue
    kinds = {s.kind for s in segments}
    assert {"clip", "img", "chart", "filing", "meme", "filler"} <= kinds
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


def test_segments_stacked_cues_keep_later(settings):
    from pipeline.models import Cue

    cues = [
        Cue(t=5.0, kind=CueKind.CLIP, payload={"value": "a"}),
        Cue(t=5.1, kind=CueKind.CLIP, payload={"value": "b"}),
    ]
    segments, warnings = plan_long_segments(cues, 20.0)
    _tiled(segments, 20.0)
    kept = [s for s in segments if s.kind == "clip"]
    assert len(kept) == 1 and kept[0].payload["value"] == "b"
    assert warnings


def test_segments_cue_near_end_dropped():
    from pipeline.models import Cue

    cues = [Cue(t=19.9, kind=CueKind.CLIP, payload={"value": "a"})]
    segments, warnings = plan_long_segments(cues, 20.0)
    _tiled(segments, 20.0)
    assert all(s.kind == "filler" for s in segments)
    assert any("too close to the end" in w for w in warnings)


def test_segments_hold_capped_by_next_cue():
    from pipeline.models import Cue

    cues = [
        Cue(t=2.0, kind=CueKind.CLIP, payload={"value": "a"}),
        Cue(t=3.5, kind=CueKind.CLIP, payload={"value": "b"}),
    ]
    segments, _ = plan_long_segments(cues, 30.0)
    first = next(s for s in segments if s.kind == "clip")
    assert first.end == pytest.approx(3.5), "a hold never runs over the next cue"
    _tiled(segments, 30.0)
