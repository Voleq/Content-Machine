"""Retention located to the sentence, and the four questions that asks."""

from __future__ import annotations

import json

import pytest

from pipeline.retention_lines import (
    EVIDENCE_FLOOR, HOOK_WINDOW_S, Span, hold_over, hook_bench,
    hook_bench_text, line_holds, line_report, load_cues, load_words,
    manifest_spans, rule_evidence, rule_evidence_text, runtime_evidence,
    runtime_evidence_text, sentence_spans, shot_holds, shot_report,
    worst_lines, write_words,
)
from pipeline.youtube import VideoLog, VideoRecord


class _W:
    """A word timing, in the shape the renderer produces."""

    def __init__(self, word, start, end, char_start, char_end):
        self.word = word
        self.start = start
        self.end = end
        self.char_start = char_start
        self.char_end = char_end


def _words_for(narration: str, *, wps: float = 2.0) -> list[_W]:
    """Word timings over a narration, evenly paced, with real char offsets."""
    out: list[_W] = []
    at = 0
    for i, word in enumerate(narration.split()):
        start = narration.index(word, at)
        at = start + len(word)
        out.append(_W(word, i / wps, (i + 1) / wps, start, at))
    return out


def _rows(*pairs) -> dict:
    return {"rows": [{"elapsed_ratio": e, "watch_ratio": w} for e, w in pairs]}


# ---------------------------------------------------------------- the timings


def test_words_round_trip_through_the_workspace(settings, tmp_path):
    words = _words_for("One two three.")
    path = write_words(words, tmp_path / "words.json")

    loaded = load_words(tmp_path)

    assert path.exists()
    assert [w["word"] for w in loaded] == ["One", "two", "three."]
    assert loaded[0]["char_start"] == 0


def test_a_workspace_with_no_words_loads_nothing(tmp_path):
    assert load_words(tmp_path) == []


def test_unreadable_words_are_not_an_error(tmp_path):
    (tmp_path / "words.json").write_text("{not json", encoding="utf-8")
    assert load_words(tmp_path) == []


def test_sentences_carry_the_seconds_they_are_spoken_over():
    narration = "First sentence here. Second sentence follows."
    spans = sentence_spans(narration, [w.__dict__ for w in _words_for(narration)])

    # The terminator stays on: it is what the linter reads as a turn.
    assert [s.text for s in spans] == ["First sentence here.",
                                       "Second sentence follows."]
    assert spans[0].start_s == 0.0
    assert spans[1].start_s >= spans[0].end_s
    assert spans[0].seconds > 0


def test_sentence_spans_need_both_halves():
    assert sentence_spans("Anything at all.", []) == []
    assert sentence_spans("   ", [{"start": 0, "end": 1, "char_start": 0}]) == []


def test_cues_are_the_fallback_when_words_were_never_written(tmp_path):
    (tmp_path / "AAPL.srt").write_text(
        "1\n00:00:00,000 --> 00:00:02,500\nThe opening line\n\n"
        "2\n00:00:02,500 --> 00:00:05,000\nAnd the second\n",
        encoding="utf-8")

    cues = load_cues(tmp_path)

    assert [c.text for c in cues] == ["The opening line", "And the second"]
    assert cues[1].start_s == pytest.approx(2.5)
    assert cues[1].end_s == pytest.approx(5.0)


def test_no_srt_means_no_cues(tmp_path):
    assert load_cues(tmp_path) == []


# ------------------------------------------------------------------ the join


def test_hold_over_averages_the_span_and_reports_the_slope():
    rows = [{"elapsed_ratio": 0.0, "watch_ratio": 1.0},
            {"elapsed_ratio": 0.5, "watch_ratio": 0.6},
            {"elapsed_ratio": 1.0, "watch_ratio": 0.2}]

    ratio, drop = hold_over(rows, 10.0, 0.0, 10.0)

    assert ratio == pytest.approx(0.6)
    assert drop == pytest.approx(0.8), "start minus end, which is the slope"


def test_hold_over_refuses_a_span_with_no_rows_in_it():
    rows = [{"elapsed_ratio": 0.9, "watch_ratio": 0.3}]
    assert hold_over(rows, 10.0, 0.0, 1.0) is None
    assert hold_over([], 10.0, 0.0, 10.0) is None
    assert hold_over(rows, 0.0, 0.0, 10.0) is None
    assert hold_over(rows, 10.0, 5.0, 5.0) is None


def test_line_holds_names_the_sentence_people_left_on():
    spans = [Span("They stayed for this", 0.0, 5.0),
             Span("And they left on this", 5.0, 10.0)]
    retention = _rows((0.0, 1.0), (0.25, 0.98), (0.6, 0.5), (0.95, 0.2))

    holds = line_holds(spans, retention, 10.0)
    worst = worst_lines(holds, 1)[0]

    assert len(holds) == 2
    assert worst.text == "And they left on this"
    assert worst.drop > 0


def test_line_report_says_so_when_there_is_nothing_to_say():
    assert "No sentence-level retention" in line_report([])


def test_line_report_names_the_worst_and_the_best():
    spans = [Span("Held", 0.0, 5.0), Span("Lost them", 5.0, 10.0)]
    text = line_report(line_holds(spans, _rows(
        (0.0, 1.0), (0.4, 0.95), (0.6, 0.5), (0.9, 0.1)), 10.0))

    assert "Lost them" in text
    assert "Best held" in text


# ------------------------------------------------------------- the hook bench


def _published(settings, ticker, workdate, narration, *, duration, retention,
               fmt="short"):
    ws = settings.workspace_dir / ticker / workdate
    ws.mkdir(parents=True, exist_ok=True)
    key = "narration" if fmt == "long" else "audio_script"
    (ws / f"script_{fmt}.json").write_text(
        json.dumps({"ticker": ticker, "format": fmt, key: narration}),
        encoding="utf-8")
    write_words(_words_for(narration), ws / "words.json")
    VideoLog(settings).record(VideoRecord(
        ticker=ticker, video_id=f"vid-{ticker}", title=f"{ticker} video",
        privacy="public", workdate=workdate, duration_s=duration,
        retention=retention))


def test_the_bench_ranks_openers_by_what_they_held(settings):
    # Rows inside the opening window itself — a five-second window on a
    # sixty-second video is the first 8% of the curve.
    _published(settings, "AAPL", "2026-09-01", "A strong opener here. Then more.",
               duration=60.0, retention=_rows((0.0, 1.0), (0.05, 0.95), (1.0, 0.4)))
    _published(settings, "MSFT", "2026-09-02", "A weak opener here. Then more.",
               duration=60.0, retention=_rows((0.0, 1.0), (0.05, 0.30), (1.0, 0.1)))

    bench = hook_bench(settings)

    assert [h.ticker for h in bench] == ["AAPL", "MSFT"]
    assert bench[0].text == "A strong opener here."
    assert bench[0].hold > bench[1].hold


def test_the_bench_is_scored_over_the_opening_window_only(settings):
    # A video that loses everyone at the end still has a good opener, and the
    # bench has to say so or it is just the overall average again.
    _published(settings, "AAPL", "2026-09-01", "Great start. Terrible finish.",
               duration=100.0,
               retention=_rows((0.0, 1.0), (HOOK_WINDOW_S / 100.0 - 0.001, 0.99),
                               (0.9, 0.05)))

    assert hook_bench(settings)[0].hold > 0.9


def test_a_video_without_retention_is_not_on_the_bench(settings):
    _published(settings, "AAPL", "2026-09-01", "An opener. More.",
               duration=60.0, retention={})
    assert hook_bench(settings) == []


def test_the_bench_text_says_when_it_is_not_evidence(settings):
    _published(settings, "AAPL", "2026-09-01", "An opener. More.",
               duration=60.0, retention=_rows((0.0, 1.0), (0.05, 0.9)))

    text = hook_bench_text(settings)

    assert "An opener" in text
    assert "not as evidence" in text


def test_the_bench_text_is_honest_when_empty(settings):
    assert "No openers" in hook_bench_text(settings)


# ------------------------------------------------------------ rules on trial


def test_the_rules_are_scored_against_the_hold_where_they_appear(settings):
    # Sentences carrying a question hold; those without do not. The evidence
    # should say so, in points.
    narration = ("Does the balance sheet agree? " * 3 + "It does not. " * 3)
    _published(settings, "AAPL", "2026-09-01", narration, duration=60.0,
               retention=_rows(*[(i / 20.0, 1.0 - i / 40.0) for i in range(21)]))

    rows = {r.rule: r for r in rule_evidence(settings)}

    assert "a question" in rows
    assert rows["a question"].n_with > 0
    assert rows["a question"].n_without > 0


def test_a_rule_with_too_few_sentences_is_not_yet_evidence(settings):
    _published(settings, "AAPL", "2026-09-01", "One sentence only.",
               duration=60.0, retention=_rows((0.0, 1.0), (0.5, 0.5), (1.0, 0.2)))

    rows = rule_evidence(settings)

    assert rows, "the features are still computed"
    assert all(r.verdict == "not yet evidence" for r in rows)


def test_rule_evidence_text_is_honest_when_there_is_nothing(settings):
    assert "Nothing to try the rules against" in rule_evidence_text(settings)


def test_rule_evidence_text_prints_the_denominators(settings):
    narration = " ".join(f"Sentence number {i} is here." for i in range(8))
    _published(settings, "AAPL", "2026-09-01", narration, duration=60.0,
               retention=_rows(*[(i / 20.0, 1.0 - i / 40.0) for i in range(21)]))

    assert "n=" in rule_evidence_text(settings)


# ---------------------------------------------------------------- the runtime


def test_runtime_bands_group_the_videos_by_length(settings):
    _published(settings, "AAPL", "2026-09-01", "Short one.", duration=50.0,
               retention=_rows((0.0, 1.0), (1.0, 0.8)))
    _published(settings, "MSFT", "2026-09-02", "Long one.", duration=400.0,
               retention=_rows((0.0, 1.0), (1.0, 0.2)))

    bands = {b.label: b for b in runtime_evidence(settings)}

    assert "45–60s" in bands
    assert "300–600s" in bands
    assert bands["45–60s"].mean_hold > bands["300–600s"].mean_hold


def test_a_video_longer_than_every_band_lands_in_the_last_one(settings):
    _published(settings, "AAPL", "2026-09-01", "Very long.", duration=5000.0,
               retention=_rows((0.0, 1.0), (1.0, 0.1)))

    assert runtime_evidence(settings)[0].label == "over 600s"


def test_runtime_text_is_honest_when_nothing_is_published(settings):
    assert "still an assumption" in runtime_evidence_text(settings)


def test_runtime_text_flags_the_thin_bands(settings):
    _published(settings, "AAPL", "2026-09-01", "Short one.", duration=50.0,
               retention=_rows((0.0, 1.0), (1.0, 0.8)))

    assert f"fewer than {EVIDENCE_FLOOR}" in runtime_evidence_text(settings)


# -------------------------------------------------------------------- the cut


def test_shot_spans_are_read_from_the_short_manifest():
    manifest = {"shots": [{"id": "a", "plate": "room/x",
                           "start_s": 0.0, "end_s": 4.0}]}
    assert manifest_spans(manifest) == [("a", "room/x", 0.0, 4.0)]


def test_shot_spans_fall_back_to_the_long_manifest_layers():
    manifest = {"layers": [{"name": "chart", "t_start": 1.0, "t_end": 6.0}]}
    assert manifest_spans(manifest) == [("chart", "chart", 1.0, 6.0)]


def test_shot_spans_are_the_long_segments_when_it_records_them():
    """The LONG's layers are the overlays on top of its cut; `segments` is
    the cut, and "which shot were they on" is a question about the cut."""
    manifest = {"segments": [{"kind": "host", "start": 0.0, "end": 11.0},
                             {"kind": "img", "value": "fed-chart",
                              "start": 11.0, "end": 22.0}],
                "layers": [{"name": "lower-third", "t_start": 2.0,
                            "t_end": 6.0}]}
    assert manifest_spans(manifest) == [("host", "host", 0.0, 11.0),
                                        ("img", "img: fed-chart", 11.0, 22.0)]


def test_a_manifest_with_neither_yields_no_spans():
    assert manifest_spans({}) == []
    assert manifest_spans({"layers": 3}) == []


def test_retention_lands_on_the_shot_that_lost_them():
    manifest = {"shots": [
        {"id": "held", "plate": "room/a", "start_s": 0.0, "end_s": 5.0},
        {"id": "lost", "plate": "data/b", "start_s": 5.0, "end_s": 15.0}]}

    holds = shot_holds(manifest, _rows(
        (0.0, 1.0), (0.2, 0.98), (0.5, 0.6), (0.95, 0.2)), 15.0)

    assert holds[0].shot == "lost"
    assert holds[0].seconds == 10.0
    assert "data/b" in shot_report(holds)
    assert "length is the first thing to try" in shot_report(holds)


def test_shot_report_is_honest_when_there_is_nothing():
    assert "No shot-level retention" in shot_report([])
