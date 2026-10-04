"""What his monitor shows, chapter by chapter (items 49, 56)."""

from __future__ import annotations

from types import SimpleNamespace

from pipeline import room_screen as rs
from pipeline.models import TagType

WINDOWS = [(0.0, 30.0), (30.0, 70.0), (70.0, 100.0)]


def _seg(start: float, kind: str = "plate", value: str = ""):
    return SimpleNamespace(kind=kind, start=start, payload={"value": value} if value else {})


SEGMENTS = [
    _seg(2.0, "host"),
    _seg(8.0, value="tables/numbers-sheet-4r-16x9"),
    _seg(14.0, value="charts/line-6y-16x9"),
    _seg(31.0, value="tables/numbers-sheet-4r-16x9"),
    _seg(40.0, "host"),
    _seg(72.0, "host"),
    _seg(80.0, value="explainers/definition-16x9"),
]


def test_a_plate_stem_is_the_name_a_writer_uses():
    assert rs.plate_stem("charts/line-6y-16x9") == "line-6y"
    assert rs.plate_stem("figures/big-number-l1-9x16") == "big-number-l1"
    assert rs.plate_stem("bars-6y") == "bars-6y"


def test_the_bot_picks_a_chart_then_a_table_then_the_price():
    picks = rs.plan_screens(SEGMENTS, WINDOWS)
    assert [p.chapter for p in picks] == [0, 1, 2]
    # A chart over the table that came first.
    assert picks[0].plate_key == "charts/line-6y-16x9" and picks[0].seg_index == 2
    # Only a table in chapter two.
    assert picks[1].plate_key == "tables/numbers-sheet-4r-16x9" and picks[1].seg_index == 3
    # Nothing that reads on a monitor in chapter three: the price.
    assert picks[2].seg_index is None and picks[2].plate_key == ""
    assert all(p.by == "bot" for p in picks)
    assert [(p.start, p.end) for p in picks] == WINDOWS


def test_the_writer_picks_by_name_or_price():
    tags = [(5.0, "numbers sheet 4r"), (35.0, "price")]
    picks = rs.plan_screens(SEGMENTS, WINDOWS, tags)
    assert picks[0].by == "writer" and picks[0].seg_index == 1
    assert picks[1].by == "writer" and picks[1].seg_index is None
    assert picks[2].by == "bot"


def test_a_writer_naming_a_plate_his_chapter_does_not_show_is_told():
    said: list[str] = []
    picks = rs.plan_screens(SEGMENTS, WINDOWS, [(75.0, "line-6y")], warn=said.append)
    assert picks[2].by == "bot" and picks[2].seg_index is None
    assert said and "line-6y" in said[0] and "chapter 3" in said[0]


def test_two_screen_tags_in_one_chapter_take_the_first():
    said: list[str] = []
    picks = rs.plan_screens(SEGMENTS, WINDOWS, [(3.0, "price"), (20.0, "line-6y")],
                            warn=said.append)
    assert picks[0].seg_index is None and picks[0].by == "writer"
    assert any("2 [SCREEN] tags" in m for m in said)


def test_pick_at_finds_the_chapter_in_force():
    picks = rs.plan_screens(SEGMENTS, WINDOWS)
    assert rs.pick_at(picks, 0.0).chapter == 0
    assert rs.pick_at(picks, 30.0).chapter == 1
    assert rs.pick_at(picks, 99.0).chapter == 2
    assert rs.pick_at(picks, 150.0).chapter == 2
    assert rs.pick_at([], 3.0) is None


def test_the_writer_sets_the_screen(long_valid_text, settings, tmp_path):
    from pipeline.parser_long import parse_long_script, validate_long_script
    from pipeline.timeline import unrenderable_long_tags

    text = "[SCREEN:   line-6y ]\n[SCREEN: no-such-plate]\n[SCREEN:  ]\n" + long_valid_text
    script, warnings = parse_long_script(text, "EXMPL", settings)
    screens = [e.payload for e in script.events if e.type is TagType.SCREEN]
    assert screens == ["line-6y", "no-such-plate"]
    assert any("[SCREEN] with nothing in it" in w for w in warnings)
    assert not [e for e, _ in unrenderable_long_tags(script) if e.type is TagType.SCREEN]
    got, blocking = validate_long_script(script, {}, tmp_path, settings)
    named = [w for w in got if w.startswith("[SCREEN:")]
    assert len(named) == 1 and "no-such-plate" in named[0]
    assert not [b for b in blocking if "SCREEN" in b]
