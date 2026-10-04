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


def test_the_push_in_on_a_release_never_cuts_its_date_in_half(settings):
    """Pushing in on the headline took the date off the side of the frame
    at "6 July 202". A push that leaves a line half in view is not taken;
    the headline is highlighted instead."""
    from pipeline import moves
    from pipeline.plates import load_plates

    reg = load_plates(settings.assets_dir)
    plate = reg.get("paper/press-release-9x16")
    values = {"source": "BUSINESS WIRE", "date": "6 July 2026",
              "headline": "Example Corp Announces AI Partnership with a "
                          "Cloud Provider",
              "body": "Example Corp today announced a strategic partnership."}
    box = moves._ink_box(plate, "headline", values["headline"], settings, reg)
    assert moves._zoom_cuts_a_line(plate, box, "headline", values, settings, reg)
    alone = {"headline": values["headline"]}
    assert not moves._zoom_cuts_a_line(plate, box, "headline", alone,
                                       settings, reg)


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


def test_the_macro_chart_keeps_its_name_and_goes_uncaptioned(
        settings, fixtures_dir, tmp_path):
    """The chart runs from its title to its source line, taller than the
    clear band. Shrunk to fit with the title optional, the title was the line
    dropped; and with the chart filling the band, a caption had nowhere to go
    but over its years."""
    from pipeline.compose import build_layers
    from pipeline.parser_short import parse_short_script
    from pipeline.plates import load_plates
    from pipeline.render_short import ShortResolver
    from pipeline.shots import expand_sequences, load_format, resolve_spans

    reg = load_plates(settings.assets_dir)
    script, _ = parse_short_script(
        (fixtures_dir / "scripts" / "macro_valid.json").read_text(encoding="utf-8"),
        settings)
    resolver = ShortResolver(script=script, workdir=tmp_path, settings=settings,
                             prices=None, handle="@channel")
    fmt = expand_sequences(load_format("macro"), lambda _s: ["a", "b", "c"])
    shot = next(s for s in fmt.shots if s.id == "the-statement")
    chart = next(v for v in shot.alts if v.plate == "charts/macro-series-9x16")
    assert chart.captions is False
    words = [NS(word=f"w{i}", start=i * 0.25, end=i * 0.25 + 0.2,
                char_start=0, char_end=0) for i in range(240)]
    spans = resolve_spans(fmt, words, 60.0, {})
    built = build_layers(fmt, spans, resolver, reg, aspect=fmt.aspect,
                         seed="macro", variants={"the-statement": chart})
    mine = [l for l in built.layers if l.shot_id == "the-statement"]
    plate = next(l for l in mine if l.kind == "plate")
    assert plate.entry_key == "charts/macro-series-9x16"
    assert plate.values.get("kicker", "").startswith("US CPI")
    assert not [l for l in mine if l.kind == "caption"]
    # Every other beat keeps its captions.
    assert [l for l in built.layers if l.kind == "caption"
            and l.shot_id == "the-mechanism"]


def test_a_change_is_printed_only_where_a_percentage_is_honest():
    assert short_data.change("revenue", 400.0, 496.0) == "+24%"
    assert short_data.change("gross_margin", 58.0, 52.0) == "-6 pts"
    # A loss that widened is not "-1012%", and a crossing has no percentage.
    assert short_data.change("net_income", -8.0, -89.0) is None
    assert short_data.change("net_income", 12.0, -15.0) is None
    assert short_data.change("revenue", 0.0, 5.0) is None


def test_the_move_card_draws_the_session_in_the_six_points_its_box_holds(settings):
    """`figures/move-on-the-day*` reserve the lower half of the frame for the
    session and draw six points. Handed the seven of `charts/intraday`, the
    plate drew nothing and the box sat empty under the figure."""
    from config import Settings
    from pipeline import series as S
    from pipeline.plates import load_plates
    from pipeline.prices import get_intraday

    session = get_intraday("EXMPL", settings)
    card = short_data.session_card(
        session, _script(move_summary="+29% today · 5× average volume"))
    six = [float(x) for x in card["path-6"].split(",")]
    assert len(six) == 6
    assert six[-1] == pytest.approx(session.move * 100, abs=0.01)
    assert six[0] == pytest.approx(float(card["plot-area"].split(",")[0]), abs=0.01)

    reg = load_plates(Settings(_env_file=None).assets_dir)
    for key in ("figures/move-on-the-day-up-9x16", "figures/move-on-the-day-9x16"):
        got = S.plate_data(reg.get(key), {"plot-area": card["path-6"]})
        assert got.data and len(got.data["series"]) == 6, (key, got)


def test_the_move_plates_take_the_session_where_there_is_one():
    from pipeline.shots import load_format

    shot = next(s for s in load_format("short").shots if s.id == "the-move")
    for v in shot.variants:
        if v.plate.startswith("figures/move-on-the-day"):
            # Optional: a short with no session keeps its move card.
            assert v.bind.get("plot-area") == "?chart.session.path-6", v.plate


# ---------------------------------------------------------------------------
# Type that fills its box on a phone card (item 35)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def kit():
    from config import Settings
    from pipeline.plates import load_plates
    return load_plates(Settings(_env_file=None).assets_dir)


def test_small_type_on_a_phone_card_starts_bigger_and_stays_under_its_betters(kit):
    from config import Settings
    from pipeline.plate_frames import PHONE_GROW_MAX, phone_size

    s = Settings(_env_file=None)
    release = kit.get("paper/press-release-9x16")
    # Body grows; the headline (62) is not small and keeps its size.
    assert phone_size(release, 30, s) > 30
    assert phone_size(release, 62, s) == 62
    assert phone_size(release, 30, s) <= min(PHONE_GROW_MAX, int(62 * 0.9))
    # The closing card's lines stay under the date figure it sets at 44.
    closing = kit.get("structure/closing-9x16")
    assert 30 < phone_size(closing, 30, s) < 44
    # A landscape plate is the long's, and keeps the kit's sizes.
    wide = next(p for k in kit.keys() if (p := kit.get(k)).canvas[0] > p.canvas[1])
    assert phone_size(wide, 30, s) == 30
    # And it can be switched off.
    assert phone_size(release, 30, Settings(_env_file=None, short_type_grow=1.0)) == 30


def test_a_grown_paragraph_fills_more_of_its_box(kit):
    from config import Settings
    from pipeline.plate_frames import drawn_box

    release = kit.get("paper/press-release-9x16")
    body = release.slots["body"]
    text = ("Example Corp today announced a strategic partnership to bring "
            "generative AI features to its routing platform.")
    kit_size = drawn_box(release, body, text, Settings(_env_file=None, short_type_grow=1.0), kit)
    grown = drawn_box(release, body, text, Settings(_env_file=None), kit)
    assert grown[3] > kit_size[3] * 1.4
    s = max(int(release.export_scale or 1), 1)
    # Still inside the box design drew.
    assert grown[1] + grown[3] <= (body.y + body.h) * s
    assert grown[0] + grown[2] <= (body.x + body.w) * s


def test_grown_labels_side_by_side_never_run_together(kit):
    """A bar chart's value labels sit in boxes edge to edge, one per column."""
    from config import Settings
    from pipeline.plate_frames import drawn_box

    bars = kit.get("charts/bars-6y-9x16")
    names = sorted((n for n, sl in bars.slots.items()
                    if sl.is_text and n.startswith("value-")),
                   key=lambda n: bars.slots[n].x)
    assert len(names) >= 2
    boxes = [drawn_box(bars, bars.slots[n], "-$89M", Settings(_env_file=None), kit)
             for n in names]
    for a, b in zip(boxes, boxes[1:]):
        assert a[0] + a[2] < b[0], "two value labels touch"


def test_a_row_of_figures_is_set_at_one_size(kit):
    """Grown each to fit its own box, the short's bar values came out at two
    sizes: "812" half as big again as "1,050" in the next column."""
    from config import Settings
    from pipeline.plate_frames import drawn_box

    bars = kit.get("charts/bars-6y-9x16")
    s = Settings(_env_file=None)
    short = drawn_box(bars, bars.slots["value-1"], "812", s, kit)
    long_ = drawn_box(bars, bars.slots["value-2"], "10500", s, kit)
    assert short[3] == long_[3]           # digits only: same ink height, same size
    # A single line on the same card still grows (item 35).
    unit = bars.slots["unit"]
    assert drawn_box(bars, unit, "Revenue", s, kit)[3] > drawn_box(
        bars, unit, "Revenue", Settings(_env_file=None, short_type_grow=1.0), kit)[3]

