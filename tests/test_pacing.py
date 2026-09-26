"""Rhythm: pacing, dead air, open loops and whether the title fits."""

from __future__ import annotations

from pipeline.pacing import (
    FIGURE_GAP_LIMIT_S, FIRST_FIGURE_LIMIT_S, STILL_LIMIT_S, change_times,
    dead_air, dead_air_report, frame_holds_report, loop_check,
    measure_pacing, open_loops, pacing_report, title_coherence,
)


class _Script:
    """The smallest thing the gates treat as a script."""

    def __init__(self, narration: str, hook: str = ""):
        self.audio_script = narration
        self.hook_text = hook
        self.ticker = "EXMPL"
        self.events = []


# -------------------------------------------------------------------- pacing


def test_pacing_measures_a_script_with_no_audio_anywhere():
    # The whole point of measuring here: this runs before a paid call exists.
    pacing = measure_pacing("One sentence. Then a second one here.")

    assert pacing.words == 7
    assert pacing.sentences == 2
    assert pacing.seconds > 0
    assert pacing.words_per_second > 0


def test_an_empty_script_measures_as_nothing():
    pacing = measure_pacing("   ")
    assert pacing.words == 0
    assert pacing.words_per_second == 0.0


def test_the_first_figure_is_timed_from_the_top():
    late = "word " * 60 + "and revenue was 4 billion."
    assert measure_pacing(late).first_figure_s > FIRST_FIGURE_LIMIT_S

    early = "Revenue was 4 billion. " + "word " * 60
    assert measure_pacing(early).first_figure_s < 2.0


def test_a_script_with_no_figure_at_all_says_so():
    assert measure_pacing("No numbers here. None at all.").first_figure_s is None


def test_the_longest_figure_free_stretch_is_found_and_quoted():
    narration = ("Revenue was 4 billion. " + "filler word here " * 40
                 + "And margin was 12 percent.")
    pacing = measure_pacing(narration)

    assert pacing.longest_figure_gap_s > FIGURE_GAP_LIMIT_S
    assert pacing.figure_gap_opening


def test_the_report_leads_with_the_numbers_and_never_blocks():
    findings = pacing_report(_Script("Revenue was 4 billion. It fell 12%."))

    assert findings
    assert all(f.severity == "warn" for f in findings)
    assert "Pacing:" in findings[0].message


def test_the_report_flags_a_late_first_figure():
    findings = pacing_report(_Script("word " * 60 + "and it was 4 billion."))
    assert any("first figure lands" in f.message for f in findings)


def test_the_report_flags_a_script_with_no_figures():
    findings = pacing_report(_Script("There are no numbers anywhere in this."))
    assert any("no figure is spoken" in f.message for f in findings)


def test_a_dense_read_and_a_staccato_read_are_both_named():
    dense = _Script(" ".join(["word"] * 40) + " and 4 billion. "
                    + " ".join(["word"] * 40) + " and 5 billion.")
    assert any("dense read" in f.message for f in pacing_report(dense))

    staccato = _Script("It fell. Hard. Down 4%. Again. Twice. Yes. No. Out.")
    assert any("staccato" in f.message for f in pacing_report(staccato))


def test_an_empty_script_gets_no_pacing_notes():
    assert pacing_report(_Script("   ")) == []


# ------------------------------------------------------------------ dead air


def test_change_times_reads_the_short_manifest():
    manifest = {"shots": [{"id": "a", "plate": "room/x", "start_s": 0.0},
                          {"id": "b", "plate": "data/y", "start_s": 4.0}]}
    assert change_times(manifest) == [(0.0, "room/x"), (4.0, "data/y")]


def test_change_times_reads_the_long_manifest_layers():
    manifest = {"layers": [{"name": "chart", "t_start": 1.0, "t_end": 9.0}]}
    assert change_times(manifest) == [(1.0, "chart"), (9.0, "chart")]


def test_the_short_manifest_records_its_layers_as_a_count():
    """`render_short` writes `layers` as a count. Iterating it made /stillness
    a TypeError on every short there has ever been."""
    manifest = {"duration_s": 20.0, "layers": 31,
                "shots": [{"id": "a", "plate": "room/x", "start_s": 0.0},
                          {"id": "b", "plate": "data/y", "start_s": 4.0}]}
    assert change_times(manifest) == [(0.0, "room/x"), (4.0, "data/y")]
    assert "16.0s still" in dead_air_report(manifest)


def test_the_long_cut_is_its_segments_not_only_its_overlays():
    """The LONG records its cut as `segments`. Reading only the overlay
    layers reported "178 s still" on a video that cuts every eleven."""
    manifest = {"duration": 44.0,
                "segments": [
                    {"kind": "host", "start": 0.0, "end": 11.0},
                    {"kind": "img", "value": "fed-chart", "start": 11.0,
                     "end": 22.0},
                    {"kind": "plate", "layout": "two-shot", "start": 22.0,
                     "end": 33.0},
                    {"kind": "host", "start": 33.0, "end": 44.0}],
                "layers": [{"name": "lower-third", "t_start": 2.0,
                            "t_end": 6.0}]}
    assert change_times(manifest) == [
        (0.0, "host"), (2.0, "lower-third"), (6.0, "lower-third"),
        (11.0, "img: fed-chart"), (22.0, "plate: two-shot"), (33.0, "host")]
    stills = dead_air(manifest)
    assert [round(s.seconds, 1) for s in stills] == [11.0, 11.0, 11.0], stills
    overlays_only = {"duration": 44.0, "layers": manifest["layers"]}
    assert dead_air(overlays_only)[0].seconds == 38.0


def test_a_manifest_with_no_timings_has_no_changes():
    assert change_times({}) == []
    assert dead_air({}) == []
    assert "cannot be read off it" in dead_air_report({})


def test_a_held_shot_is_found_and_a_moving_one_is_not():
    still = {"duration_s": 30.0,
             "shots": [{"id": "a", "plate": "data/table", "start_s": 0.0},
                       {"id": "b", "plate": "room/x", "start_s": 20.0}]}
    found = dead_air(still)

    assert len(found) == 2, "the tail to the end of the video counts too"
    assert found[0].seconds == 20.0
    assert found[0].what == "data/table"
    assert "data/table" in dead_air_report(still)


def test_a_video_that_keeps_moving_reports_nothing():
    moving = {"duration_s": 12.0,
              "shots": [{"id": str(i), "plate": "p", "start_s": float(i * 3)}
                        for i in range(4)]}
    assert dead_air(moving) == []
    assert "keeps moving" in dead_air_report(moving)


def test_the_limit_is_the_caller_s_to_move():
    manifest = {"duration_s": 10.0,
                "shots": [{"id": "a", "plate": "p", "start_s": 0.0}]}
    assert dead_air(manifest, limit_s=STILL_LIMIT_S)
    assert dead_air(manifest, limit_s=20.0) == []


def test_a_hold_measured_on_the_frames_is_named_by_its_shot():
    manifest = {"pacing": {"hold_ceiling_s": 8.0, "held_over_ceiling": [
        {"shot": "numbers", "start_s": 21.4, "end_s": 31.0, "held_s": 9.6}]}}
    report = frame_holds_report(manifest)

    assert "8s ceiling" in report
    assert "numbers holds 9.6s from 21.4s" in report


def test_frames_that_could_not_be_read_say_so_and_old_manifests_say_nothing():
    unread = {"pacing": {"hold_ceiling_s": 8.0, "held_over_ceiling": None}}
    assert "unchecked" in frame_holds_report(unread)

    clean = {"pacing": {"hold_ceiling_s": 8.0, "held_over_ceiling": []}}
    assert frame_holds_report(clean) == ""
    assert frame_holds_report({"pacing": {"shots": 9}}) == ""
    assert frame_holds_report({}) == ""


# ---------------------------------------------------------------- open loops


def test_a_question_answered_later_is_a_closed_loop():
    narration = ("So why is the inventory rising? " + "filler " * 20
                 + "The inventory is rising because nobody is buying.")
    loops = open_loops(narration)

    assert len(loops) == 1
    assert loops[0].closed
    assert "inventory" in loops[0].shared


def test_a_question_never_returned_to_stays_open():
    narration = ("So why is the inventory rising? "
                 "Management changed auditors in March. And then left.")
    loops = open_loops(narration)

    assert len(loops) == 1
    assert not loops[0].closed


def test_a_question_asked_late_is_not_an_opening_loop():
    narration = ("Filler sentence here. " * 40) + "But why is inventory rising?"
    assert open_loops(narration) == []


def test_the_check_says_so_when_the_script_opens_with_no_question():
    findings = loop_check(_Script("It fell. It kept falling. That is that."))
    assert any("no question is asked" in f.message for f in findings)


def test_the_check_flags_the_promise_a_video_breaks():
    findings = loop_check(_Script(
        "Why is the inventory rising? Management changed auditors. Goodbye."))
    assert any("never picked back up" in f.message for f in findings)


def test_a_closed_loop_draws_no_finding():
    findings = loop_check(_Script(
        "Why is the inventory rising? " + "filler " * 10
        + "The inventory is rising because nobody is buying."))
    assert findings == []


def test_an_empty_script_gets_no_loop_notes():
    assert loop_check(_Script("  ")) == []


# --------------------------------------------------------------- title fit


def test_a_title_and_an_opener_about_the_same_thing_pass():
    assert title_coherence("EXMPL — the inventory problem",
                           "The inventory is the problem here.") == []


def test_a_title_promising_something_else_is_flagged():
    findings = title_coherence("EXMPL — the inventory problem",
                               "Management changed auditors in March.")

    assert len(findings) == 1
    assert findings[0].severity == "warn"
    assert "share no subject" in findings[0].message


def test_an_opener_with_no_subject_at_all_is_not_judged():
    # Nothing to compare is not the same as a mismatch, and a linter that
    # invented one here would be scolding a short opener for being short.
    assert title_coherence("The inventory problem", "And there it is.") == []


def test_a_missing_half_is_not_a_finding():
    assert title_coherence("", "an opener") == []
    assert title_coherence("a title", "") == []
