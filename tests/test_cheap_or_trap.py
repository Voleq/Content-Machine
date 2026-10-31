"""The cheap-or-trap card puts up the multiple the line is about.

Valentin's Boeing proof (30 Oct 2026): the voice said "seventy times EBITDA
assumes nine point four percent perpetual cash growth" over a card reading
"Revenue is $94.9B now. It was $62.3B.", because no sheet row was a multiple
and the card took the first row.
"""

from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from pipeline import short_data as sd

BOEING = ("Debt fell, yet seventy times EBITDA assumes nine point four "
          "percent perpetual cash growth.")


@pytest.mark.parametrize("text, label", [
    (BOEING, "EV/EBITDA"),
    ("EV/EBITDA of 25x is a lot for this", "EV/EBITDA"),
    ("At sixty two times sales the price needs a miracle", "P/S"),
    ("A P/E of 34 is cheap only if margins hold", "P/E"),
    ("Forward P/E of 20 assumes the guide holds", "forward P/E"),
    ("Eighteen times book for a software company", "P/B"),
    # Leverage is not a price.
    ("Net debt is 9.8 times EBITDA, and the P/E is 40", "P/E"),
    ("Net debt is 9.8 times EBITDA.", None),
    ("Cheap needs deliveries to double.", None),
])
def test_the_line_s_multiple_is_read_off_its_words(text, label):
    got = sd.named_multiple(text)
    assert (got[0] if got else None) == label


def _data(**over):
    base = dict(values={"ev_ebitda": 70.4, "ps_ttm": 1.6},
                valuation={"implied_growth": 0.094},
                peer_percentiles=[{"metric": "EV/EBITDA", "median": 24.0}])
    base.update(over)
    return NS(**base)


def test_the_card_states_the_multiple_and_what_the_price_asks_for():
    got = sd.multiple_statements(_data(), BOEING)
    assert got == {"heavy": "EV/EBITDA is 70× today.",
                   "light": "Priced for 9.4% growth, forever."}


def test_without_a_reverse_dcf_the_peers_are_the_other_truth():
    got = sd.multiple_statements(_data(valuation={}), BOEING)
    assert got["light"] == "Its peers trade at 24×."


@pytest.mark.parametrize("data", [
    _data(values={"ev_ebitda": None}),
    _data(values={"ev_ebitda": -12.0}),          # negative EBITDA: no multiple
    _data(valuation={}, peer_percentiles=[]),
    None,
])
def test_a_multiple_with_no_figure_draws_nothing_rather_than_revenue(data):
    assert sd.multiple_statements(data, BOEING) == {}


def test_a_line_that_names_no_multiple_is_left_to_the_sheet():
    assert sd.multiple_statements(_data(), "Cheap needs deliveries to double.") is None


# ---------------------------------------------------------------------------
# On the render's own resolver
# ---------------------------------------------------------------------------

def _script(**over):
    from pipeline.models import ShortScript

    raw = {
        "ticker": "EXMPL", "format": "short",
        "hook_text": "A muted hook line here.",
        "audio_script": "Numbers first. Then the point. Noise.",
        "move_summary": "+34% today · 6× average volume",
        "headlines": [{"text": "H", "meaning": "M"}],
        "years": ["FY21", "FY22", "FY23", "FY24", "FY25", "LTM"],
        "numbers": [{"label": "Revenue", "values": ["$400M", "$420M", "$452M",
                                                    "$471M", "$480M", "$496M"]}],
        "numbers_comment": "flat", "conclusion": "Noise.",
    }
    raw.update(over)
    return ShortScript.model_validate(raw)


@pytest.fixture()
def data(workspace):
    from pipeline.company_data import load_company_data

    return load_company_data(workspace)


def _resolver(script, data, settings, tmp_path):
    from pipeline.render_short import ShortResolver

    return ShortResolver(script=script, workdir=tmp_path, settings=settings,
                         prices=None, handle="@channel", data=data)


def test_the_both_true_card_follows_the_line_not_the_first_row(data, settings,
                                                              tmp_path):
    """The fixture workbook: P/S 62, a reverse DCF asking 6.1%."""
    r = _resolver(_script(cheap_or_trap="At sixty two times sales the price "
                                        "needs growth it has never shown."),
                  data, settings, tmp_path)
    assert r.text_for("compare.heavy") == "P/S is 62× today."
    assert r.text_for("compare.light") == "Priced for 6.1% growth, forever."


def test_a_multiple_the_workbook_lacks_leaves_the_card_undrawn(data, settings,
                                                              tmp_path):
    """The fixture has no EV/EBITDA (its EBITDA is negative)."""
    r = _resolver(_script(cheap_or_trap=BOEING), data, settings, tmp_path)
    assert r.text_for("compare.heavy") is None
    assert r.text_for("compare.light") is None


def test_the_sheet_still_speaks_when_the_line_names_no_multiple(data, settings,
                                                               tmp_path):
    r = _resolver(_script(cheap_or_trap="Cheap needs deliveries to double."),
                  data, settings, tmp_path)
    assert r.text_for("compare.heavy") == "Revenue is $496M now."


def test_a_multiple_row_on_the_sheet_still_wins(data, settings, tmp_path):
    rows = [{"label": "P/S", "values": ["40x", "45x", "50x", "55x", "60x", "62x"]},
            {"label": "Revenue", "values": ["$1M"] * 6}]
    r = _resolver(_script(numbers=rows, cheap_or_trap=BOEING), data, settings,
                  tmp_path)
    assert r.text_for("compare.heavy") == "P/S is 62x now."
    assert r.text_for("compare.light") == "It was 40x."


@pytest.mark.parametrize("key", ["structure/both-true-9x16",
                                 "structure/confession-statement-9x16"])
def test_the_lines_fit_both_cards_the_beat_can_draw(key, data, settings,
                                                    tmp_path):
    """Statement boxes hold 34 to 38 characters: a longer line made the card
    unfillable and the beat was dropped from the cut."""
    from pipeline.compose import _fillable, resolve_plate
    from pipeline.plates import load_plates
    from pipeline.shots import load_format

    reg = load_plates(settings.assets_dir)
    fmt = load_format("earnings")
    shot = next(s for s in fmt.shots if s.id == "so-what")
    variant = next(v for v in shot.variants if v.plate == key)
    plate = resolve_plate(reg, key, fmt.aspect)
    for line in ("At sixty two times sales the price needs growth.",
                 "Priced at -12.5% growth by a negative yield? P/S of 62."):
        r = _resolver(_script(cheap_or_trap=line), data, settings, tmp_path)
        assert _fillable(variant, shot, plate, r, reg, safe=fmt.safe), line
