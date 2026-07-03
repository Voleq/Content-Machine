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
    proportional_fallback,
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
    words = _words("Verdict: overvalued, stamped and filed.")
    assert find_anchor_time(words, "Overvalued") == words[1].start
    assert find_anchor_time(words, "FILED") == words[-1].start


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
    duration = 55.0
    words = mock_words(short_script.audio_script, duration)
    cues = build_short_timeline(short_script, words, duration)

    kinds = [c.kind for c in cues]
    assert kinds.count(CueKind.HOOK) == 1
    assert kinds.count(CueKind.WHIP_PAN) == 1
    assert kinds.count(CueKind.DATA_LINE) == len(short_script.data_block)
    assert kinds.count(CueKind.HIGHLIGHT) == 1
    assert kinds.count(CueKind.STAMP) == 1
    assert kinds.count(CueKind.CTA) == 1

    assert cues[0].kind is CueKind.HOOK and cues[0].t == 0.0
    times = [c.t for c in cues]
    assert times == sorted(times)
    assert all(0 <= t <= duration for t in times)


def test_short_stamp_is_duration_minus_three(short_script):
    duration = 55.0
    words = mock_words(short_script.audio_script, duration)
    cues = build_short_timeline(short_script, words, duration)
    stamp = next(c for c in cues if c.kind is CueKind.STAMP)
    assert stamp.t == pytest.approx(52.0, abs=0.06)
    assert not stamp.fallback
    assert stamp.payload["label"] == "OVERVALUED"


def test_short_highlight_lands_on_anchor_word(short_script):
    duration = 55.0
    words = mock_words(short_script.audio_script, duration)
    cues = build_short_timeline(short_script, words, duration)
    hl = next(c for c in cues if c.kind is CueKind.HIGHLIGHT)
    anchor_t = find_anchor_time(words, "cash")
    assert hl.t == pytest.approx(anchor_t, abs=0.01)
    assert not hl.fallback
    assert hl.payload["line_index"] == 2


def test_short_highlight_fallback_when_anchor_missing(short_script):
    duration = 55.0
    raw = short_script.model_dump()
    raw["visual_directions"][0]["anchor_word"] = "zebra"
    script = ShortScript.model_validate(raw)
    words = mock_words(script.audio_script, duration)
    cues = build_short_timeline(script, words, duration)
    hl = next(c for c in cues if c.kind is CueKind.HIGHLIGHT)
    assert hl.fallback
    expected = proportional_fallback(2, len(script.data_block), duration)
    assert hl.t == pytest.approx(expected, abs=0.5)


def test_short_data_lines_paced_between_whip_and_stamp(short_script):
    duration = 58.0
    words = mock_words(short_script.audio_script, duration)
    cues = build_short_timeline(short_script, words, duration)
    whip = next(c for c in cues if c.kind is CueKind.WHIP_PAN)
    stamp = next(c for c in cues if c.kind is CueKind.STAMP)
    lines = [c for c in cues if c.kind is CueKind.DATA_LINE]
    assert [c.payload["index"] for c in lines] == list(range(len(short_script.data_block)))
    for c in lines:
        assert whip.t < c.t < stamp.t
    line_times = [c.t for c in lines]
    assert line_times == sorted(line_times)


def test_short_timeline_tiny_duration_smoke(short_script):
    """3–5s smoke renders must still produce a sane, ordered timeline."""
    duration = 4.0
    words = mock_words(short_script.audio_script, duration)
    cues = build_short_timeline(short_script, words, duration)
    times = [c.t for c in cues]
    assert times == sorted(times)
    assert all(0 <= t < duration for t in times)
    stamp = next(c for c in cues if c.kind is CueKind.STAMP)
    whip = next(c for c in cues if c.kind is CueKind.WHIP_PAN)
    assert stamp.t > whip.t


# ----------------------------------------------------------- LONG timeline


def test_long_timeline_offsets_hit_words(long_valid_text, settings):
    script, _ = parse_long_script(long_valid_text, "EXMPL", settings)
    duration = 100.0
    words = mock_words(script.narration, duration)
    cues = build_long_timeline(script, words, duration)

    assert len(cues) == len(script.events)  # OVERVALUED stamp is valid
    times = [c.t for c in cues]
    assert times == sorted(times)

    first_broll = next(c for c in cues if c.kind is CueKind.BROLL)
    assert first_broll.payload["key"] == "house_of_cards"
    # the cue must land on the word right after the tag ("We are going…")
    expected = char_offset_time(words, script.events[0].char_offset)
    assert first_broll.t == pytest.approx(expected)


def test_long_timeline_drops_invalid_stamp(settings):
    script, _ = parse_long_script(
        "Words here. [STAMP: MEDIOCRE] More words. [STAMP: TOXIC] End.",
        "EXMPL", settings,
    )
    words = mock_words(script.narration, 20.0)
    cues = build_long_timeline(script, words, 20.0)
    stamps = [c for c in cues if c.kind is CueKind.STAMP]
    assert len(stamps) == 1 and stamps[0].payload["label"] == "TOXIC"


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
    assert all(s.length <= 5.0 + 1e-6 for s in segments)
    assert all(s.length >= 3.0 - 1e-6 for s in segments)


def test_segments_with_cues(long_valid_text, settings):
    script, _ = parse_long_script(long_valid_text, "EXMPL", settings)
    duration = 110.0
    words = mock_words(script.narration, duration)
    cues = build_long_timeline(script, words, duration)
    segments, warnings = plan_long_segments(cues, duration)
    _tiled(segments, duration)

    brolls = [s for s in segments if s.kind == "broll"]
    assert len(brolls) >= 6
    # each broll segment starts exactly on its cue time
    broll_cues = [c for c in cues if c.kind is CueKind.BROLL]
    started = {round(s.start, 3) for s in brolls}
    hit = sum(1 for c in broll_cues if round(c.t, 3) in started)
    assert hit >= len(brolls)  # every kept broll segment maps to a cue
    assert any(s.kind == "refinitiv" for s in segments)
    assert all(s.length >= 0.25 - 1e-9 for s in segments)


def test_segments_stacked_cues_keep_later(settings):
    from pipeline.models import Cue

    cues = [
        Cue(t=5.0, kind=CueKind.BROLL, payload={"key": "a"}),
        Cue(t=5.1, kind=CueKind.BROLL, payload={"key": "b"}),
    ]
    segments, warnings = plan_long_segments(cues, 20.0)
    _tiled(segments, 20.0)
    kept = [s for s in segments if s.kind == "broll"]
    assert len(kept) == 1 and kept[0].payload["key"] == "b"
    assert warnings


def test_segments_cue_near_end_dropped():
    from pipeline.models import Cue

    cues = [Cue(t=19.9, kind=CueKind.BROLL, payload={"key": "a"})]
    segments, warnings = plan_long_segments(cues, 20.0)
    _tiled(segments, 20.0)
    assert all(s.kind == "filler" for s in segments)
    assert any("too close to the end" in w for w in warnings)


def test_segments_broll_hold_capped():
    from pipeline.models import Cue

    cues = [Cue(t=2.0, kind=CueKind.BROLL, payload={"key": "a"})]
    segments, _ = plan_long_segments(cues, 60.0, broll_hold_s=5.0)
    broll = next(s for s in segments if s.kind == "broll")
    assert broll.length == pytest.approx(5.0)
    _tiled(segments, 60.0)
