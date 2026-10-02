"""The short reading the operator's workbook, and the material around it.

Items 1-8, 23, 25-28 and 34 of the build plan, checked where they are
decided rather than on pixels: the cards the workbook fills, the release and
the wires off the News sheet, today's session, the series behind a macro
print, and the drawing rules that keep a card readable on a phone.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from pipeline import macro_series, news_page, short_data
from pipeline.company_data import load_company_data


@pytest.fixture()
def data(workspace):
    return load_company_data(workspace)


def _script(**kw):
    base = dict(ticker="EXMPL", headlines=[], move_summary="", hook_text="",
                numbers=[], reported="")
    base.update(kw)
    return NS(**base)


# ---------------------------------------------------------------------------
# The release and the wires (item 5)
# ---------------------------------------------------------------------------

def test_the_release_is_the_news_row_that_is_this_headline(data):
    row = news_page.match_row(data.news, "EXMPL announces AI partnership",
                              company=str(data.get("company_name")),
                              ticker="EXMPL")
    assert row is not None and "partnership" in row["headline"].lower()
    # Sharing only the company's name is not the same story.
    assert news_page.match_row(data.news, "Example Corp shares fall",
                               company=str(data.get("company_name")),
                               ticker="EXMPL") is None


def test_a_release_opens_on_what_was_announced_not_on_its_dateline():
    raw = ("SPRINGFIELD, July 6, 2026 -- Example Corp (NASDAQ: EXMPL), a "
           "provider of routing software, today announced a partnership.")
    assert news_page.lead(raw) == "Example Corp today announced a partnership."


def test_sentences_and_headlines_are_fitted_whole_or_not_at_all():
    text = "One short sentence. Another one that runs on for quite a while."
    assert news_page.fit_sentences(text, 30) == "One short sentence."
    assert news_page.fit_sentences("x" * 50, 30) is None
    assert news_page.fit_headline("Example Corp beats, raises guidance", 20) \
        == "Example Corp beats"
    assert news_page.fit_headline("A" * 40, 20) is None


def test_the_release_card_is_read_off_the_page_the_news_sheet_links(
        data, settings):
    script = _script(headlines=[NS(text="EXMPL announces AI partnership")])
    card = news_page.release_card(data, script, settings)
    assert card is not None
    assert len(card["body"]) <= news_page.RELEASE_BODY_CHARS
    assert card["body"][-1] in ".!?"           # whole sentences only
    assert card["date"] and card["source"]


def test_a_wire_strip_is_the_latest_rows_oldest_first_or_nothing(data):
    rows = news_page.wire_rows(data, 5, 65)
    assert rows is not None and len(rows) == 5
    assert all(len(r["headline"]) <= 65 for r in rows)
    assert news_page.wire_rows(data, 50, 65) is None


# ---------------------------------------------------------------------------
# Today's session (item 4)
# ---------------------------------------------------------------------------

def test_a_session_is_read_off_a_fixture_and_never_invented(settings):
    from pipeline.prices import get_intraday

    got = get_intraday("EXMPL", settings)
    assert got is not None and got.source == "fixture"
    assert get_intraday("NOSUCH", settings) is None


def test_the_session_card_puts_seven_readings_on_the_prior_close(settings):
    from pipeline.prices import get_intraday

    session = get_intraday("EXMPL", settings)
    card = short_data.session_card(
        session, _script(move_summary="+29% today · 5× average volume"))
    figures = [float(x) for x in card["plot-area"].split(",")]
    assert len(figures) == short_data.SESSION_POINTS
    # The last reading is the session's own move, and the figure says so.
    assert figures[-1] == pytest.approx(session.move * 100, abs=0.01)
    assert card["figure"] == "+29.0%"
    assert [card[f"head-{i}"] for i in (1, 7)] == ["09:30", "16:00"]


def test_a_session_that_contradicts_the_narration_is_not_drawn(settings):
    from pipeline.prices import get_intraday

    session = get_intraday("EXMPL", settings)
    assert short_data.session_card(session, _script(move_summary="+3% today")) is None


def test_the_prior_close_sits_on_the_rule_the_plate_draws():
    """`charts/intraday` draws the prior close 62% down its plot."""
    from config import Settings
    from pipeline import series as S
    from pipeline.plates import load_plates

    reg = load_plates(Settings(_env_file=None).assets_dir)
    plate = reg.get("charts/intraday-9x16")
    got = S.plate_data(plate, {"plot-area": "18,34,29,24,27,27,29"}).data
    zero_from_top = (got["max"] - 0) / (got["max"] - got["min"])
    assert zero_from_top == pytest.approx(0.62)
    assert max(got["series"]) <= got["max"] and min(got["series"]) >= got["min"]


# ---------------------------------------------------------------------------
# The series behind a macro print (item 6)
# ---------------------------------------------------------------------------

def test_the_series_is_picked_from_what_the_headline_names():
    pick = lambda text: macro_series.pick(_script(headlines=[NS(text=text)]))  # noqa: E731
    assert pick("CPI 3.4% vs 3.1% expected").fred_id == "CPIAUCSL"
    assert pick("Core CPI cools").fred_id == "CPILFESL"
    assert pick("Jobless claims jump").fred_id == "UNRATE"
    assert pick("Apple beats on iPhone") is None


def test_the_axis_is_five_round_labels_covering_the_series():
    ticks = macro_series.nice_axis(-1.96, 8.9)
    assert len(ticks) == 5 and ticks[0] <= -1.96 and ticks[-1] >= 8.9
    steps = {round(b - a, 6) for a, b in zip(ticks, ticks[1:])}
    assert len(steps) == 1


def test_recessions_inside_the_window_become_bands():
    rec = [(date(2000, m, 1), 0.0) for m in range(1, 13)] + \
          [(date(2001, m, 1), 1.0 if 3 <= m <= 11 else 0.0) for m in range(1, 13)]
    bands = macro_series.recession_bands(rec, date(2000, 1, 1), date(2002, 1, 1))
    assert len(bands) == 1
    a, b = bands[0]
    assert 0.5 < a < b < 1.0


def test_the_macro_card_is_fred_s_and_names_its_source(settings):
    script = _script(headlines=[NS(text="CPI 3.4% vs 3.1% expected")])
    card = macro_series.card(script, settings)
    assert card["source"].startswith("FRED: CPIAUCSL")
    assert len(card["source"]) <= macro_series.SOURCE_CHARS
    heads = [int(card[f"head-{i}"]) for i in range(1, 11)]
    assert heads == list(range(heads[0], heads[0] + 28, 3))
    assert card.get("band-1")                    # the last recessions shaded
    assert len(card["series"].split(",")) > 300  # 27 years, monthly


def test_a_print_fred_disagrees_with_is_flagged_before_approval(settings):
    script = _script(headlines=[NS(text="CPI 3.4% vs 3.1% expected")],
                     reported="5.0%")
    assert "FRED" in macro_series.print_check(script, settings)
    near = _script(headlines=[NS(text="CPI 3.4% vs 3.1% expected")],
                   reported=macro_series.card(script, settings)["caption"]
                   .split()[1])
    assert macro_series.print_check(near, settings) is None


# ---------------------------------------------------------------------------
# The workbook's own cards (items 1, 2, 3, 23)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(short_data.CARDS))
def test_every_workbook_card_fills_from_the_fixture_or_says_none(name, data):
    card = short_data.CARDS[name](data, script=_script(reported="$0.06"))
    if card is None:
        return
    assert all(isinstance(v, str) and v for v in card.values())


def test_the_quarter_bars_are_drawn_from_the_figures_they_print(data):
    card = short_data.quarter_bars(data)
    assert card is not None
    assert not [k for k in card if k.startswith("bar-")]
    assert [k for k in card if k.startswith("value-")]


def test_a_loss_hangs_from_zero():
    from pipeline.series import column_bars

    cols = [{"x": i * 10, "y": 0, "w": 8, "h": 100} for i in range(3)]
    nodes = column_bars(cols, [10, -5, 20], {})["nodes"]
    loss = nodes[1]["attrs"]
    # Drawn from the zero line down, not up from the foot of the plot: on a
    # -5..20 scale zero is 80 px down a 100 px plot.
    assert loss["y"] == pytest.approx(80.0)
    assert loss["height"] == pytest.approx(20.0)


# ---------------------------------------------------------------------------
# The writer's budgets (item 34's picture frame)
# ---------------------------------------------------------------------------

def test_a_box_holding_a_supplied_value_does_not_narrow_the_writer():
    from pipeline.form import _writer_bind

    assert _writer_bind("script.conclusion")
    assert _writer_bind("?source.numbers_comment")
    assert not _writer_bind("pic.company.source")
    assert not _writer_bind("?data.week52.kicker")
