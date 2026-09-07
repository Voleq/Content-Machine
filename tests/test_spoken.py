"""Figures as they are said.

The suggestion the voice linter offers is the whole value of the warning — a
finding that says "this is wrong" and stops there sends the writer to work out
the spoken form themselves, which is the thing that was never going to happen
reliably. So the conversion is checked on its own, at the edges where a
number-to-words routine is usually wrong.
"""

from __future__ import annotations

import pytest

from pipeline.spoken import (
    eye_written_figures,
    say_decimals,
    say_integer,
    spoken_number,
)


@pytest.mark.parametrize("n,said", [
    (0, "zero"),
    (7, "seven"),
    (13, "thirteen"),
    (20, "twenty"),
    (42, "forty-two"),
    (100, "a hundred"),
    (162, "a hundred and sixty-two"),
    (200, "two hundred"),
    (999, "nine hundred and ninety-nine"),
    (1000, "one thousand"),
    (1234, "one thousand two hundred and thirty-four"),
    (2024, "two thousand and twenty-four"),
    (100_000, "a hundred thousand"),
    (1_000_024, "one million and twenty-four"),
    (89_000_000, "eighty-nine million"),
    (1_400_000_000, "one billion four hundred million"),
    (-89, "minus eighty-nine"),
])
def test_integers_read_the_way_a_person_says_them(n, said):
    assert say_integer(n) == said


def test_decimals_are_read_digit_by_digit():
    """"point fifty-six" is a different number to most listeners."""
    assert say_decimals("6") == "point six"
    assert say_decimals("56") == "point five six"
    assert say_decimals("05") == "point zero five"


@pytest.mark.parametrize("raw,said", [
    # The two the bible writes out itself.
    ("59.6%", "fifty-nine point six percent"),
    ("162%", "a hundred and sixty-two percent"),
    # The one that motivated the whole check.
    ("$1,234.56",
     "one thousand two hundred and thirty-four dollars and fifty-six cents"),
    # Money to two places is dollars AND cents; a scale word means it is not.
    ("$0.42", "forty-two cents"),
    ("$1.00", "one dollar"),
    ("$1.25 billion", "one point two five billion dollars"),
    ("$1.4 billion", "one point four billion dollars"),
    ("$40", "forty dollars"),
    ("-8%", "minus eight percent"),
    ("−12.5%", "minus twelve point five percent"),
    ("1,400", "one thousand four hundred"),
    ("£2.50", "two pounds and fifty pence"),
])
def test_a_typed_figure_becomes_a_spoken_one(raw, said):
    assert spoken_number(raw) == said


def test_something_that_is_not_a_figure_comes_back_untouched():
    assert spoken_number("the filing") == "the filing"
    assert spoken_number("") == ""


def test_only_the_four_things_a_voice_gets_wrong_are_flagged():
    """A currency symbol, a percent sign, a thousands comma, a decimal point.

    A bare integer reads the same either way; flagging every year and every
    count would make the check noise, and noise is what gets a check switched
    off.
    """
    clean = "They opened 8 sites in 2024 and closed 12."
    assert eye_written_figures(clean) == []

    found = dict(eye_written_figures(
        "Revenue was $1,234.56, down 59.6%, across 1,400 stores in 2024."))
    assert set(found) == {"$1,234.56", "59.6%", "1,400"}
    assert found["1,400"] == "one thousand four hundred"
