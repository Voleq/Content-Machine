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
    eye_written_terms,
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


@pytest.mark.parametrize("raw,said", [
    ("YoY", "year over year"),
    ("QoQ", "quarter over quarter"),
    ("P/E", "price to earnings"),
    ("EV/EBITDA", "enterprise value to EBITDA"),
    ("EPS", "earnings per share"),
    ("FCF", "free cash flow"),
    ("ROIC", "return on invested capital"),
    ("CAGR", "compound annual growth rate"),
    ("bps", "basis points"),
    ("SG&A", "selling, general and administrative"),
    ("R&D", "research and development"),
])
def test_a_typed_term_becomes_a_spoken_one(raw, said):
    found = dict(eye_written_terms(f"The filing says {raw} and stops there."))
    assert found == {raw: said}


def test_only_the_abbreviations_a_voice_gets_wrong_are_flagged():
    """An abbreviation a person also spells out is not a defect.

    "IPO" and "CEO" are read as letters by a person and by the voice alike.
    Listing them would make the check noise, which is what gets a check
    switched off — the same reasoning that leaves a bare integer alone.
    """
    assert eye_written_terms("The IPO priced and the CEO left before the ETF.") == []


def test_a_ticker_is_left_alone():
    """There is no one spoken form to suggest, and flagging every ticker
    would fire on nearly every line of a stock script."""
    assert eye_written_terms("EXMPL is up today and NVDA is not.") == []


def test_an_unknown_ampersand_is_still_mechanical():
    """The substitution is always right, so the suggestion can be made
    without the term being in the table."""
    assert eye_written_terms("AT&T raised the dividend.") == [("AT&T", "AT and T")]


def test_a_filing_name_is_left_alone():
    """The committed long fixture opens "I've read the 10-K twice".

    That script is what the repo holds up as the register done properly, so a
    rule flagging it would fire on the house style itself.
    """
    assert eye_written_terms("I've read the 10-K twice, and the 10-Q.") == []


def test_terms_come_back_in_the_order_they_were_written():
    """The writer reads the findings against the line, so a table hit and an
    ampersand hit cannot come back in table order."""
    found = eye_written_terms("S&P multiples, then YoY, then the EPS line.")
    assert [raw for raw, _ in found] == ["S&P", "YoY", "EPS"]
