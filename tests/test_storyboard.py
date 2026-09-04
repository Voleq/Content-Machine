"""The storyboard: see the cut before paying to render it."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from PIL import Image

from pipeline.parser_long import parse_long_script
from pipeline.storyboard import build_storyboard, spoken_between
from pipeline.timeline import build_long_timeline, plan_long_segments
from pipeline.tts import TTSEngine
from pipeline.models import WordTimestamp


def words(*spans):
    return [WordTimestamp(word=w, start=a, end=b, char_start=i * 5, char_end=i * 5 + 4)
            for i, (w, a, b) in enumerate(spans)]


@pytest.fixture()
def planned(long_valid_text, settings, workspace):
    script, _ = parse_long_script(long_valid_text, "EXMPL", settings)
    tts = TTSEngine(settings).synthesize(script.narration, "long")
    cues = build_long_timeline(script, tts.words, tts.duration_s)
    segments, _ = plan_long_segments(cues, tts.duration_s)
    return script, tts, segments, workspace


def test_spoken_between_picks_the_words_under_a_beat():
    w = words(("alpha", 0.0, 1.0), ("beta", 1.0, 2.0), ("gamma", 5.0, 6.0))
    assert spoken_between(w, 0.5, 2.5) == "alpha beta"
    assert spoken_between(w, 8.0, 9.0) == ""


def test_spoken_between_ellipsises_a_long_caption():
    w = words(*[(f"word{i}", i * 0.5, i * 0.5 + 0.4) for i in range(60)])
    got = spoken_between(w, 0.0, 60.0, limit=40)
    assert len(got) <= 40 and got.endswith("…")


def test_a_storyboard_covers_every_beat(planned, settings, tmp_path):
    script, tts, segments, ws = planned
    out, problems = build_storyboard(
        segments, tts.words, tmp_path / "sb.png", settings,
        ticker="EXMPL", workspace=ws, title="EXMPL — LONG",
    )
    assert out.exists()
    im = Image.open(out)
    # one tile per beat, four to a row, plus the header
    rows = (len(segments) + 3) // 4
    assert im.width == 4 * 420
    assert im.height == 78 + rows * 300
    assert isinstance(problems, list)


def test_it_is_fast_enough_to_run_before_every_render(planned, settings, tmp_path):
    """The whole point is that it costs seconds, not an encode. Without a
    ContentManager nothing is fetched, so this is the floor."""
    script, tts, segments, ws = planned
    t0 = time.monotonic()
    build_storyboard(segments, tts.words, tmp_path / "sb.png", settings,
                     ticker="EXMPL", workspace=ws)
    assert time.monotonic() - t0 < 20.0


def test_it_flags_a_beat_whose_asset_is_missing(planned, settings, tmp_path):
    """The failure this exists to catch: a tag that will render as nothing."""
    script, tts, segments, ws = planned
    filings = [s for s in segments if s.kind == "filing"]
    assert filings, "the fixture LONG has a [SHOW FILING] tag"
    # the screenshot has not been uploaded into the workspace
    _, problems = build_storyboard(segments, tts.words, tmp_path / "sb.png",
                                   settings, ticker="EXMPL", workspace=ws)
    assert any("MISSING" in p for p in problems)
    assert any(str(filings[0].payload["value"]) in p for p in problems)


def test_an_unresolvable_plate_is_reported(settings, tmp_path):
    from pipeline.timeline import Segment

    seg = Segment(start=0.0, end=6.0, kind="plate",
                  payload={"value": "tables/not-a-real-plate",
                           "layout": "two-shot"})
    _, problems = build_storyboard([seg], [], tmp_path / "sb.png", settings)
    assert problems and "NOT IN THE KIT" in problems[0]


def test_host_beats_illustrate_with_the_rig(settings, tmp_path):
    from pipeline.timeline import Segment

    seg = Segment(start=0.0, end=5.0, kind="host",
                  payload={"variant": 0, "layout": "host-full"})
    out, problems = build_storyboard([seg], [], tmp_path / "sb.png", settings)
    assert problems == []
    assert out.exists()
