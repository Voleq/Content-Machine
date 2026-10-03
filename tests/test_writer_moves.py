"""The writer's moves: `[MOVE: name]` on the plate already on screen.

Four of the kit's moves are the writer's to call — count-up, highlight,
pen-circle, zoom-to-slot — and each lands in the slot the plate's own motion
anchors publish. These cover the three places that has to hold: the menu the
writer is shown, the validation that refuses what a plate cannot do before
any money is spent, and the list the render is handed with each move's
plate, slot and time on the real clock.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.models import Chapter, Cue, CueKind, TagType
from pipeline.parser_long import parse_long_script, validate_long_script
from pipeline.plates import (
    AUTOMATIC_MOVES,
    WRITER_MOVES,
    load_plates,
    one_number,
    writer_moves,
)
from pipeline.timeline import (
    Segment,
    build_long_timeline,
    chapter_windows,
    plan_long_segments,
    plan_writer_moves,
)
from pipeline.tts import mock_words

ROOT = Path(__file__).resolve().parents[1]

BIG = ("[PLATE: big-number-l1-16x9 | kicker=FREE CASH FLOW | value={v} | "
       "label=LTM]")
QUOTE = ("[PLATE: quote-pull-16x9 | body=We remain confident in the long "
         "term. | attribution=The CEO]")
# A figure called out beside its chart: a small part of the plate, so the
# pen may ring it. The big number's figure IS its plate and is never ringed.
CALLOUT = ("[PLATE: earnings-vs-cash-16x9 | kicker=EARNINGS VS CASH | "
           "gap={v}]")
FILING = ("[PLATE: filing-page-16x9 | kicker=10-K | docref=p. 41 | "
          "passage=We may not be able to refinance the notes on acceptable "
          "terms.]")


@pytest.fixture()
def settings(settings):
    # Tokeniser-sized snippets, far below the LONG floor (asserted at its real
    # default in test_parser_long).
    return settings.model_copy(update={"long_min_chars": 0})


@pytest.fixture()
def reg(settings):
    return load_plates(settings.assets_dir)


def _check(raw: str, settings, tmp_path) -> tuple[list[str], list[str], object]:
    script, _ = parse_long_script(raw, "EXMPL", settings)
    warnings, blocking = validate_long_script(script, set(), tmp_path, settings)
    return ([w for w in warnings if "MOVE" in w],
            [b for b in blocking if "MOVE" in b], script)


# --------------------------------------------------------------- the plates


def test_one_number_is_a_single_figure_and_nothing_else():
    for good in ("$3.1bn", "−12%", "1,240", "14x", "+4.2pp", "US$1.2B",
                 "~40%", "€900m", "37 days", "0.8"):
        assert one_number(good), good
    for bad in ("Q3", "FY24", "4–6%", "40% of sales", "$3.1bn and rising",
                "three", "", "12x–14x", "1.2/3.4"):
        assert not one_number(bad), bad


def test_a_plate_offers_only_the_moves_its_kit_anchors_publish(reg):
    big = writer_moves(reg.get("figures/big-number-l1-16x9"))
    assert big == {"count-up": "value"}, "the big figure is never ringed"
    assert writer_moves(reg.get("charts/earnings-vs-cash-16x9")) == {
        "count-up": "gap", "pen-circle": "gap"}
    # A row of figures resolves to its LATEST column, the year being talked
    # about (design, rebuild-40), never the oldest.
    assert writer_moves(reg.get("charts/bars-6y-16x9"))["count-up"] == "value-6"
    sheet = writer_moves(reg.get("tables/numbers-sheet-4r-16x9"))
    assert sheet["count-up"] == sheet["pen-circle"] == "cell-1-6"
    quote = writer_moves(reg.get("cards/quote-pull-16x9"))
    assert quote["highlight"] == "body"
    assert "zoom-to-slot" not in quote, "zoom is for paper only"
    filing = writer_moves(reg.get("paper/filing-page-16x9"))
    assert filing["zoom-to-slot"] == filing["highlight"] == "passage"


def test_line_draw_and_bars_grow_are_never_the_writers(reg):
    assert not set(AUTOMATIC_MOVES) & set(WRITER_MOVES)
    chart = reg.get("charts/bars-6y-16x9")
    assert "bars-grow" in chart.motion
    assert not set(AUTOMATIC_MOVES) & set(writer_moves(chart))


# ---------------------------------------------------------------- the parse


def test_a_move_is_parsed_onto_the_plate_before_it(settings):
    raw = f"Cash. {BIG.format(v='$3.1bn')} It made [MOVE: Count Up] a lot."
    script, _ = parse_long_script(raw, "EXMPL", settings)
    move = script.events_of(TagType.MOVE)[0]
    assert move.payload == "count-up"
    assert move.values == {"plate": "figures/big-number-l1-16x9",
                           "on": "PLATE"}
    assert "[MOVE" not in script.narration and "Count" not in script.narration


def test_a_valid_move_passes_validation(settings, tmp_path):
    raw = (f"Cash. {BIG.format(v='$3.1bn')} It made [MOVE: count-up] a lot. "
           f"{FILING} Page forty one [MOVE: zoom-to-slot] says so.")
    warnings, blocking, _ = _check(raw, settings, tmp_path)
    assert blocking == [] and warnings == []


def test_a_move_the_plate_cannot_do_blocks_and_names_what_it_can(settings,
                                                                  tmp_path):
    raw = f"Cash. {BIG.format(v='$3.1bn')} It made [MOVE: highlight] a lot."
    _, blocking, _ = _check(raw, settings, tmp_path)
    assert len(blocking) == 1
    assert "cannot do highlight" in blocking[0]
    assert "count-up (on value)" in blocking[0]
    assert 'before "a lot"' in blocking[0], "the writer is told where"


def test_a_count_up_on_a_slot_that_is_not_one_number_blocks(settings,
                                                             tmp_path):
    raw = f"Guide. {BIG.format(v='4–6%')} They guided [MOVE: count-up] low."
    _, blocking, _ = _check(raw, settings, tmp_path)
    assert len(blocking) == 1
    assert "exactly one number" in blocking[0] and "'4–6%'" in blocking[0]


def test_a_zoom_off_paper_blocks_and_points_at_highlight(settings, tmp_path):
    raw = f"He said. {QUOTE} Confident [MOVE: zoom-to-slot] twice."
    _, blocking, _ = _check(raw, settings, tmp_path)
    assert len(blocking) == 1
    assert "paper/ plates only" in blocking[0]
    assert "Use highlight on it instead" in blocking[0]


def test_a_move_where_the_frame_is_not_a_plate_blocks(settings, tmp_path):
    raw = (f"Cash. {BIG.format(v='$3.1bn')} It made a lot. "
           f"[CLIP: tumbleweed] Nobody [MOVE: count-up] came.")
    _, blocking, _ = _check(raw, settings, tmp_path)
    assert len(blocking) == 1 and "belongs to a [CLIP]" in blocking[0]


def test_a_move_after_a_plate_that_failed_never_lands_on_the_one_before(
        settings, tmp_path):
    """The failed plate is dropped at parse; its move must not slide back
    onto the plate before it, which the writer never meant."""
    raw = (f"Cash. {BIG.format(v='$3.1bn')} A lot. "
           f"[PLATE: no-such-plate-16x9 | value=$9bn] Then [MOVE: count-up] "
           f"more.")
    script, _ = parse_long_script(raw, "EXMPL", settings)
    assert script.events_of(TagType.MOVE)[0].values["plate"] == ""
    _, blocking, _ = _check(raw, settings, tmp_path)
    assert any("did not resolve" in b for b in blocking)
    cues = build_long_timeline(script, mock_words(script.narration, 10.0), 10.0)
    move = next(c for c in cues if c.kind is CueKind.MOVE)
    assert move.payload["plate_order"] is None


def test_an_unknown_move_suggests_the_nearest_one(settings, tmp_path):
    raw = f"Cash. {BIG.format(v='$3.1bn')} It made [MOVE: circle] a lot."
    _, blocking, _ = _check(raw, settings, tmp_path)
    assert len(blocking) == 1 and "did you mean pen-circle" in blocking[0]


def test_a_tagged_line_draw_only_warns(settings, tmp_path):
    raw = f"Cash. {BIG.format(v='$3.1bn')} It made [MOVE: line-draw] a lot."
    warnings, blocking, _ = _check(raw, settings, tmp_path)
    assert blocking == []
    assert len(warnings) == 1 and "plays by itself" in warnings[0]


def test_the_same_move_twice_on_one_plate_blocks(settings, tmp_path):
    raw = (f"Cash. {BIG.format(v='$3.1bn')} It made [MOVE: count-up] a lot, "
           f"[MOVE: count-up] a lot.")
    _, blocking, _ = _check(raw, settings, tmp_path)
    assert len(blocking) == 1 and "already has a count-up" in blocking[0]


def test_a_move_written_after_its_plate_has_gone_warns(settings, tmp_path):
    filler = " ".join(["and then he keeps on talking"] * 12)
    raw = (f"Cash. {CALLOUT.format(v='$3.1bn')} It made a lot {filler}. "
           f"Later [MOVE: pen-circle] that number.")
    warnings, blocking, _ = _check(raw, settings, tmp_path)
    assert blocking == []
    assert any("back on screen" in w for w in warnings)


def _circles(n: int, gap_words: int = 0) -> str:
    gap = " ".join(["word"] * gap_words)
    return " ".join(f"{CALLOUT.format(v=f'${i + 1}bn')} It made [MOVE: pen-circle] "
                    f"that. {gap}" for i in range(n))


def test_a_second_pen_circle_in_a_chapter_blocks(settings, tmp_path):
    # Long enough to be spoken past the second chapter's 5:00, so the
    # estimate puts both circles well inside the first.
    raw = (_circles(2) + " " + " ".join(["word"] * 900)
           + " The end.\n\n=== CHAPTERS ===\n"
           "00:00 cold-open | the hook\n"
           "05:00 the-numbers | the numbers\n")
    _, blocking, _ = _check(raw, settings, tmp_path)
    assert len(blocking) == 1
    assert '2 [MOVE: pen-circle] in "the hook"' in blocking[0]
    assert "one a chapter" in blocking[0]


def test_a_second_pen_circle_near_a_chapter_boundary_only_warns(settings,
                                                                tmp_path):
    """The parse can only estimate time; at a boundary the render decides."""
    raw = (_circles(2) + " " + " ".join(["word"] * 100)
           + " The end.\n\n=== CHAPTERS ===\n"
           "00:00 cold-open | the hook\n"
           "00:10 the-numbers | the numbers\n")
    warnings, blocking, _ = _check(raw, settings, tmp_path)
    assert not any("pen-circle] in" in b for b in blocking)
    assert any("near a chapter boundary" in w for w in warnings)


def test_a_fourth_pen_circle_in_the_video_blocks(settings, tmp_path):
    raw = (_circles(4, gap_words=400) + "\n\n=== CHAPTERS ===\n"
           "00:00 cold-open | one\n"
           "02:40 the-numbers | two\n"
           "05:20 the-business | three\n"
           "08:00 valuation | four\n")
    _, blocking, script = _check(raw, settings, tmp_path)
    assert any("4 [MOVE: pen-circle] in the video" in b and "limit is 3" in b
               for b in blocking)
    assert not any("pen-circle] in \"" in b for b in blocking), \
        "one a chapter each is within the chapter ration"


# ------------------------------------------------------------ the render data


def _plan(raw: str, settings, duration: float, chapter_starts=(0.0,)):
    script, _ = parse_long_script(raw, "EXMPL", settings)
    cues = build_long_timeline(script, mock_words(script.narration, duration),
                               duration)
    segments, _ = plan_long_segments(cues, duration)
    moves, warnings = plan_writer_moves(
        cues, segments, load_plates(settings.assets_dir),
        chapter_starts=list(chapter_starts))
    return segments, moves, warnings


def test_every_move_reaches_the_render_data_with_its_plate_slot_and_time(
        settings):
    raw = ("Here is where the money went, and it went somewhere. "
           f"{BIG.format(v='$3.1bn')} It made [MOVE: count-up] three point "
           "one billion dollars last year. Then a long stretch of talk with "
           "nothing on screen while he explains the plan in some detail. "
           f"{FILING} Page forty one says [MOVE: zoom-to-slot] they may not "
           "refinance.")
    segments, moves, warnings = _plan(raw, settings, 30.0)
    assert warnings == []
    assert [(m.move, m.plate, m.slot) for m in moves] == [
        ("count-up", "figures/big-number-l1-16x9", "value"),
        ("zoom-to-slot", "paper/filing-page-16x9", "passage")]
    for m in moves:
        seg = segments[m.segment]
        assert seg.kind == "plate" and seg.payload["value"] == m.plate
        assert seg.start <= m.t < seg.end
        assert m.at == pytest.approx(m.t - seg.start)
        assert set(m.box) == {"x", "y", "w", "h"}
        row = m.to_json()
        assert set(row) >= {"move", "plate", "slot", "t", "segment", "at",
                            "box", "text", "order"}
    assert moves[0].text == "$3.1bn"


def _cue(t, kind, order, **payload):
    return Cue(t=t, kind=kind, payload={"order": order, **payload})


def test_a_move_on_a_deferred_plate_plays_when_the_plate_arrives(reg):
    big = "figures/big-number-l1-16x9"
    cues = [
        _cue(2.0, CueKind.PLATE, 0, value=big, values={"value": "$1bn"}),
        _cue(4.0, CueKind.PLATE, 1, value=big, values={"value": "$2bn"}),
        _cue(5.0, CueKind.MOVE, 2, value="count-up", plate=big,
             plate_order=1),
    ]
    segments, _ = plan_long_segments(cues, 30.0)
    second = next(i for i, s in enumerate(segments)
                  if s.payload.get("order") == 1)
    assert segments[second].start > 5.0, "the second plate was deferred"
    moves, _ = plan_writer_moves(cues, segments, reg)
    assert moves[0].segment == second
    assert moves[0].t == segments[second].start and moves[0].at == 0.0
    assert moves[0].text == "$2bn"


def test_a_move_spoken_after_its_plate_has_gone_is_dropped(reg):
    big = "charts/earnings-vs-cash-16x9"
    # The writer moved on at 10 s (the clip), so the plate was gone by 20.
    cues = [_cue(2.0, CueKind.PLATE, 0, value=big, values={"gap": "$1bn"}),
            _cue(10.0, CueKind.CLIP, 1, value="x"),
            _cue(20.0, CueKind.MOVE, 2, value="pen-circle", plate=big,
                 plate_order=0)]
    segments, _ = plan_long_segments(cues, 30.0)
    moves, warnings = plan_writer_moves(cues, segments, reg)
    assert moves == []
    assert any("cut back to Dennis" in w for w in warnings)


def test_pen_circle_keeps_one_a_chapter_and_three_a_video_by_real_time(reg):
    big = "charts/earnings-vs-cash-16x9"
    segments = [Segment(start=0.0, end=1.0, kind="host")]
    cues = []
    for k in range(5):
        a = 1.0 + k * 10.0
        segments.append(Segment(start=a, end=a + 7.0, kind="plate",
                                payload={"order": 2 * k, "value": big,
                                         "values": {"gap": f"${k}bn"}}))
        segments.append(Segment(start=a + 7.0, end=a + 10.0, kind="host"))
        cues.append(_cue(a + 1.0, CueKind.MOVE, 2 * k + 1, value="pen-circle",
                         plate=big, plate_order=2 * k))
    # Chapters at 0, 20, 30, 40: the first two circles share chapter one.
    moves, warnings = plan_writer_moves(cues, segments, reg,
                                        chapter_starts=[0.0, 20.0, 30.0, 40.0])
    assert [m.t for m in moves] == [2.0, 22.0, 32.0]
    assert any("chapter 1 already has its pen-circle" in w for w in warnings)
    assert any("already has 3 pen-circles" in w for w in warnings)


def test_chapter_windows_follow_the_render_s_chapter_plan():
    chapters = [Chapter(type="cold-open", title="a", start_s=0.0),
                Chapter(type="the-numbers", title="b", start_s=120.0),
                Chapter(type="valuation", title="c"),
                Chapter(type="resigned-close", title="d", start_s=500.0)]
    # A chapter with no timestamp sits at its even share of the runtime,
    # exactly where render_long draws its opener (duration * i / n).
    assert chapter_windows(chapters, 600.0) == [
        (0.0, 120.0), (120.0, 300.0), (300.0, 500.0), (500.0, 600.0)]
    assert chapter_windows([], 600.0) == []


# ----------------------------------------------------------------- the menu


def test_the_long_menu_marks_where_each_move_lands(settings):
    from bot.prompts import plate_catalogue

    long = plate_catalogue(settings, fmt="long")
    assert "[MOVE: name]" in long and "◆slot" in long and "▭slot" in long

    def slots_line(text: str, name: str) -> str:
        lines = text.splitlines()
        i = next(i for i, l in enumerate(lines) if l.strip().startswith(name))
        return next(l for l in lines[i:] if "slots:" in l)

    # The big figure fills the tag's spot, so a [SOURCE] has no room on it.
    assert slots_line(long, "big-number-l1-16x9").endswith("◆value  ✕source")
    assert slots_line(long, "filing-page-16x9").endswith("◆kicker  ▭passage")
    assert "▭" not in slots_line(long, "big-number-l1-16x9")

    short = plate_catalogue(settings, fmt="short")
    assert "◆" not in short and "[MOVE" not in short and "✕source" not in short, \
        "a short has no [MOVE] or [SOURCE] grammar"


def test_the_chapter_types_carry_the_pen_circle_ration(settings):
    from bot.prompts import chapter_type_catalogue

    text = chapter_type_catalogue(settings, fmt="long")
    assert "pen-circle: at most 1 a chapter, 3 a video" in text


def test_the_write_prompt_teaches_the_move_tag():
    text = (ROOT / "templates" / "master_prompt_long_write.md").read_text(
        encoding="utf-8")
    assert "[MOVE: name]" in text
    assert "[MOVE: count-up]" in text, "with a worked example"
