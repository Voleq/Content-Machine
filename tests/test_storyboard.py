"""The storyboard: see the cut before paying to render it."""

from __future__ import annotations

import time

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


# ---------------------------------------------------- how much is the host
#
# The long test script had Dennis on screen for about 80% of a 22-minute cut
# in beats of about ten seconds. The storyboard reports each chapter's share
# and flags the ones over 70%; it changes nothing.


def _chapters(*spec):
    from pipeline.models import Chapter

    return [Chapter(type=t, title=title, start_s=s) for t, title, s in spec]


def _segs(*spec):
    from pipeline.timeline import Segment

    return [Segment(start=a, end=b, kind=k) for k, a, b in spec]


def test_host_share_is_host_seconds_over_chapter_seconds():
    from pipeline.storyboard import host_share

    segs = _segs(("host", 0, 40), ("plate", 40, 50), ("host", 50, 60),
                 ("chart", 60, 80), ("host", 80, 100))
    got = host_share(segs, _chapters(("cold-open", "hook", 0.0),
                                     ("the-numbers", "numbers", 60.0)), 100.0)
    assert [(c.title, c.host_s, c.seconds) for c in got] == [
        ("hook", 50.0, 60.0), ("numbers", 20.0, 40.0)]
    assert got[0].share == pytest.approx(50 / 60) and got[0].flagged
    assert got[1].share == pytest.approx(0.5) and not got[1].flagged


def test_a_two_shot_counts_as_evidence_not_as_host():
    """He is in frame beside a plate, but the viewer is shown something."""
    from pipeline.storyboard import host_share
    from pipeline.timeline import Segment

    segs = [Segment(start=0, end=10, kind="plate",
                    payload={"layout": "two-shot"}),
            Segment(start=10, end=20, kind="host")]
    (only,) = host_share(segs, [], 20.0)
    assert only.title == "the whole video" and only.share == pytest.approx(0.5)


def test_a_chapter_over_seventy_percent_host_is_flagged_and_nothing_changes():
    from pipeline.storyboard import HOST_SHARE_FLAG, host_share_lines

    assert HOST_SHARE_FLAG == 0.70
    segs = _segs(("host", 0, 80), ("plate", 80, 90), ("host", 90, 100),
                 ("chart", 100, 130), ("host", 130, 150))
    before = [(s.kind, s.start, s.end) for s in segs]
    lines = host_share_lines(
        segs, _chapters(("cold-open", "the hook", 0.0),
                        ("the-numbers", "the numbers", 100.0)), 150.0)
    assert lines[0].startswith("host on screen 73% of the cut")
    assert lines[1].startswith("⚠  90%") and "the hook" in lines[1]
    assert lines[2].startswith("·  40%") and "the numbers" in lines[2]
    assert "the writer's call" in lines[-1]
    assert [(s.kind, s.start, s.end) for s in segs] == before


def test_the_caption_fits_telegram_and_counts_what_it_cut():
    from pipeline.storyboard import CAPTION_LIMIT, storyboard_caption

    problems = [f"beat {i:02d} @ {i}.0s — clip X ← NOT FOUND " + "x" * 120
                for i in range(12)]
    caption = storyboard_caption("EXMPL — storyboard, 40 beats", problems,
                                 ["host on screen 80% of the cut"] * 6)
    assert len(caption) <= CAPTION_LIMIT
    assert caption.startswith("EXMPL — storyboard, 40 beats\nhost on screen")
    assert "more on the sheet" in caption.splitlines()[-1]


def test_the_sheet_draws_the_chapters_only_when_it_is_given_them(settings,
                                                                  tmp_path):
    from pipeline.timeline import Segment

    segs = [Segment(start=0.0, end=5.0, kind="host",
                    payload={"variant": 0, "layout": "host-full"})]
    plain, _ = build_storyboard(segs, [], tmp_path / "a.png", settings)
    chaptered, _ = build_storyboard(
        segs, [], tmp_path / "b.png", settings,
        chapters=_chapters(("cold-open", "the hook", 0.0)))
    assert Image.open(plain).height == 78 + 300
    assert Image.open(chaptered).height > Image.open(plain).height
