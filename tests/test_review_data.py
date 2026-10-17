"""Findings from the full review of the data, fact-check and parsing code."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def data(tmp_path_factory):
    from pipeline.company_data import load_company_data

    d = tmp_path_factory.mktemp("wb")
    shutil.copy(ROOT / "fixtures" / "company_data" / "dennis_data.xlsx",
                d / "dennis_data.xlsx")
    return load_company_data(d)


def _blocks(text, data):
    from pipeline.gates import fact_check

    return [f.message for f in fact_check(text, data)]


def test_a_comma_ends_a_spoken_figure():
    """"four hundred ninety one million, one percent below plan" was one
    figure of 491,000,001 percent."""
    from pipeline.gates import extract_numbers

    got = [(n.value, n.is_percent) for n in extract_numbers(
        "four hundred ninety one million, one percent below plan")]
    assert got == [(491_000_000, False), (1, True)]
    got = [n.value for n in extract_numbers(
        "sixty three, sixty two, sixty one, fifty nine, fifty eight percent")]
    assert got == [63, 62, 61, 59, 58]


@pytest.mark.parametrize("words, value", [
    ("one nineteen", 119), ("two twelve", 212), ("one twenty", 120),
    ("four ninety six", 496)])
def test_the_hundreds_shorthand_takes_a_teen_too(words, value):
    from pipeline.gates import _words_to_number

    assert _words_to_number(words.split()) == value


@pytest.mark.parametrize("sentence", [
    "The 10-K shows revenue grew.",
    "Revenue, per page 87 and Note 4, rose.",
    "From 2019 to 2023 revenue rose.",
    "Fiscal 2023 revenue rose.",
    "On March 3 revenue was reported.",
    "There is one reason revenue stalled.",
    "Revenue grew for two straight years.",
])
def test_a_name_a_date_or_a_small_count_is_not_a_figure(sentence, data):
    assert _blocks(sentence, data) == []


def test_a_figure_belongs_to_the_metric_in_its_own_clause(data):
    """In a recital the 496 sat nearer "free cash flow" by characters and
    was checked as free cash flow."""
    assert _blocks("Revenue sat at four hundred ninety six million, free cash "
                   "flow at negative fifteen million.", data) == []
    wrong = _blocks("Revenue sat at nine hundred million, free cash flow at "
                    "negative fifteen million.", data)
    assert len(wrong) == 1 and "for revenue" in wrong[0]


def test_a_wrong_figure_still_blocks(data):
    assert _blocks("Revenue was nine hundred million.", data)
    assert _blocks("Revenue rose 40 percent in 2023.", data)


def test_a_short_keeps_its_beat_marks_for_the_voice_lint(settings):
    """`delivery_text` read only `events`; a SHORT keeps its tags in
    `inline_events`, so its [BEAT]s vanished from the lint."""
    from pipeline.gates import delivery_text
    from pipeline.parser_short import parse_short_script

    raw = (ROOT / "fixtures" / "scripts" / "short_valid.json").read_text(
        encoding="utf-8")
    script, _ = parse_short_script(raw, settings)
    assert "[BEAT]" in delivery_text(script)


def test_a_long_beat_is_a_turn():
    from pipeline.gates import _unbroken_runs

    words = " ".join(["word"] * 40)
    assert _unbroken_runs(f"{words} [LONG BEAT] {words}") == []
    assert _unbroken_runs(f"{words} {words}")


def test_every_long_reaches_the_price_feed(settings):
    """The room's monitor shows the price for every chapter with no plate of
    its own, so a LONG with no [CHART: price] still draws the feed."""
    from pipeline.gates import _reaches_a_price_chart
    from pipeline.parser_long import parse_long_script

    raw = (ROOT / "fixtures" / "scripts" / "long_valid.txt").read_text(
        encoding="utf-8")
    script, _ = parse_long_script(raw, "EXMPL", settings)
    assert _reaches_a_price_chart(script)


@pytest.mark.parametrize("cell, value", [
    ("$", None), ("%", None), (",", None), ("0.9bn", 0.9e9),
    ("900mm", 900e6), ("$3.1bn", 3.1e9), ("1.2B", 1.2e9), ("(12)", -12.0),
])
def test_a_plate_cell_reads_its_units_and_never_crashes(cell, value):
    from pipeline.gates import _cell_value

    assert _cell_value(cell) == value


def test_a_bar_a_pixel_wide_does_not_kill_the_render():
    from PIL import Image

    from pipeline.series import paint

    img = Image.new("RGBA", (200, 200))
    nodes = [
        {"tag": "rect", "attrs": {"x": 10, "y": 10, "width": 2.05,
                                  "height": 50, "fill": "#000000",
                                  "stroke": "#111111", "stroke-width": 2}},
        {"tag": "rect", "attrs": {"x": 40, "y": 10, "width": 0.2,
                                  "height": 0.3, "fill": "#000000"}},
    ]
    paint(img, nodes, 1.0, supersample=1)


def test_the_kit_audit_of_the_whole_library_is_not_in_each_scripts_gates(
        settings):
    from pipeline.gates import kit_doctor, run_gates
    from pipeline.parser_long import parse_long_script

    raw = (ROOT / "fixtures" / "scripts" / "long_valid.txt").read_text(
        encoding="utf-8")
    script, _ = parse_long_script(raw, "EXMPL", settings)
    findings, stats = kit_doctor(script, settings, library=False)
    assert not any("can put it on screen" in f.message for f in findings)
    assert stats["unreachable"] == []
    report = run_gates(script, settings, skeptic=False)
    assert not any("can put it on screen" in f.message
                   for f in report.findings)


def test_a_macro_short_says_freshness_was_skipped(settings):
    from pipeline.gates import run_gates
    from pipeline.parser_short import parse_short_script

    raw = (ROOT / "fixtures" / "scripts" / "macro_valid.json").read_text(
        encoding="utf-8")
    script, _ = parse_short_script(raw, settings)
    report = run_gates(script, settings, skeptic=False, format_name="macro")
    assert report.ran["freshness"].startswith("skipped:")


def test_the_hook_menu_goes_even_without_a_chosen_line():
    from pipeline.parser_long import _strip_hook_options

    raw = ('=== HOOK OPTIONS ===\n1. "aaa"\n2. "bbb"\n3. "ccc"\n\n'
           "The real script starts here.")
    assert _strip_hook_options(raw) == "The real script starts here."


@pytest.mark.parametrize("label, field, kind", [
    ("Share Count YoY %", None, "flow"),
    ("Invested Capital", None, "stock"),
    ("Anything", "diluted_shares", "stock"),
    ("Shares", "shares_yoy", "flow"),
])
def test_a_rows_kind_comes_from_its_field_then_a_better_label_read(
        label, field, kind):
    from pipeline.models import NumberRow

    row = NumberRow(label=label, values=["1", "2"], field=field)
    assert row.measured.value == kind
