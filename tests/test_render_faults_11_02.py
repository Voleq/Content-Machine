"""His notes on the INTC short and the RDDT long (2-3 Nov 2026).

Each test names the fault it keeps fixed, in his words where he wrote some.
"""

from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from pipeline import short_data as sd
from pipeline.compose import figure_tokens, same_figure
from pipeline.models import Cue, CueKind
from pipeline.prices import IntradaySession


def _intc_session() -> IntradaySession:
    """INTC, 30 Oct 2026: down 28% on the open and flat all day."""
    times = ["09:30", "10:30", "11:30", "12:30", "13:30", "14:30", "15:30", "16:00"]
    prices = [66.10, 65.20, 65.71, 66.40, 65.90, 66.05, 65.70, 65.88]
    return IntradaySession(ticker="INTC", day="2026-10-30", times=times,
                           prices=prices, prior_close=92.07)


# --- 14: "I do not fucking know what this graph wants to show" -------------

def test_a_gap_day_draws_no_session_chart():
    session = _intc_session()
    assert sd.gap_day(session)
    card = sd.session_card(session, NS(ticker="INTC",
                                       move_summary="-28.6% · on the guide"))
    assert card is not None, "the move plates still get the session"
    for slot in sd.SESSION_CHART_SLOTS:
        assert slot not in card, slot
    # ...and the box under the move card's figure still draws the day.
    assert len(card["path-6"].split(",")) == 6
    assert card["unit6"].startswith("the session, 09:30")


def test_a_day_that_moved_in_the_session_keeps_its_chart(settings):
    from pipeline.prices import get_intraday

    session = get_intraday("EXMPL", settings)      # +18% gap, +29% by the close
    assert not sd.gap_day(session)
    card = sd.session_card(session, NS(ticker="EXMPL", move_summary="+29% today"))
    assert card["plot-area"] and card["figure"] == "+29.0%"


# --- 15: "why it showed two similar assets one after another" -------------

def test_one_move_in_other_digits_is_the_same_figure():
    a = figure_tokens("−28.4%")
    b = figure_tokens("-28.6%")
    assert a == [("%", -28.4)] and b == [("%", -28.6)]
    assert same_figure(a[0], b[0])
    assert same_figure(figure_tokens("$16.5B")[0], figure_tokens("$16.4B")[0])
    assert not same_figure(("%", 12.0), ("%", -12.0))
    assert not same_figure(("$b", 16.5), ("$m", 16.5))
    # A year or a count is not a figure for this.
    assert figure_tokens("Q3 FY26, 2024") == []


# --- 17: "don't get this plate" ---------------------------------------------

def test_the_implied_card_prints_no_zero_as_a_delivered_figure():
    data = NS(ticker="INTC",
              valuation={"implied_growth": 0.14, "hist_fcf_cagr": None,
                         "rev_cagr": -0.096},
              get=lambda k, d=None: {"ticker": "INTC"}.get(k, d))
    card = sd.implied(data)
    assert card["history-low"] == "revenue -9.6%"
    assert "history-high" not in card
    # Two bars from zero: what the price needs, what revenue did.
    assert card["marker"] == "0%,14%,structure"
    assert card["band"] == "-9.6%,0%"


# --- 2: "Need to find another way to open the longs" ------------------------

def test_the_long_opens_on_him():
    from pipeline.render_long import _opens_on_him

    cues = [Cue(t=0.0, kind=CueKind.SCENE, payload={"value": "room/desk-wide"}),
            Cue(t=1.2, kind=CueKind.SOUND, payload={"value": "knock"}),
            Cue(t=1.5, kind=CueKind.IMG, payload={"value": "a photo"}),
            Cue(t=2.7, kind=CueKind.PLATE, payload={"value": "paper/headline-stack-3-16x9"}),
            Cue(t=3.0, kind=CueKind.SCRIBBLE, payload={"value": "circle"}),
            Cue(t=12.6, kind=CueKind.CLIP, payload={"value": "trading_screen"})]
    got = _opens_on_him(cues, 5.0)
    kinds = [(c.kind, round(c.t, 2)) for c in got]
    assert kinds == [(CueKind.SCENE, 0.0), (CueKind.SOUND, 1.2),
                     (CueKind.PLATE, 5.0), (CueKind.SCRIBBLE, 5.0),
                     (CueKind.CLIP, 12.6)]
    assert _opens_on_him(cues, 0.0) == cues


def test_no_title_card_unless_asked(settings):
    from config import Settings

    assert Settings(_env_file=None).long_title_card is False
    assert Settings(_env_file=None).cold_open_host_s == 5.0


# --- 10, 11: "the gifs are too fucking random"; "use less of pexels" --------

class _Clips:
    """A content manager whose clip chain finds footage for everything but
    the keys it is told are missing."""

    def __init__(self, settings, missing=()):
        self.settings = settings
        self.missing = set(missing)
        self.asked = []

    def resolve_clip(self, key, choice=0, *, portrait=False):
        self.asked.append(key)
        if key in self.missing:
            return NS(source="filler", path=None)
        return NS(source="pexels", path=f"/clips/{key}.mp4")


def test_stock_clips_are_capped_and_spaced(settings):
    from pipeline.render_long import _pictures_found

    settings.clip_max_per_long = 3
    settings.clip_min_gap_s = 60.0
    content = _Clips(settings, missing={"nowhere"})
    times = [10, 30, 80, 100, 150, 220, 300, 400]
    cues = [Cue(t=t, kind=CueKind.CLIP, payload={"value": f"c{t}", "order": i})
            for i, t in enumerate(times)]
    cues.insert(1, Cue(t=12, kind=CueKind.CLIP, payload={"value": "nowhere", "order": 99}))
    script = NS(events=[])
    got = _pictures_found(cues, script, content, None, {})
    assert [c.payload["value"] for c in got] == ["c10", "c80", "c150"]


def test_a_clip_that_finds_nothing_stays_on_him(settings):
    from pipeline.render_long import _pictures_found

    settings.clip_max_per_long = 0
    settings.clip_min_gap_s = 0.0
    content = _Clips(settings, missing={"nowhere"})
    cues = [Cue(t=10, kind=CueKind.CLIP, payload={"value": "nowhere", "order": 0}),
            Cue(t=20, kind=CueKind.CLIP, payload={"value": "calculator", "order": 1})]
    got = _pictures_found(cues, NS(events=[]), content, None, {})
    assert [c.payload["value"] for c in got] == ["calculator"]


def test_the_writer_hears_about_the_clip_cap(settings, tmp_path):
    from pipeline.parser_long import parse_long_script, validate_long_script

    settings.clip_max_per_long = 2
    settings.long_min_chars = 0
    raw = " ".join(f"Line {i} about the business. [CLIP: calculator]"
                   for i in range(4))
    script, _ = parse_long_script(raw, "EXMPL", settings)
    warnings, blocking = validate_long_script(script, ["calculator"], tmp_path,
                                              settings)
    assert any("4 [CLIP] tags" in w and "at most 2" in w for w in warnings)
    assert not any("[CLIP]" in b for b in blocking)


@pytest.mark.parametrize("key", ("structure/implied-9x16", "structure/implied-16x9"))
def test_the_implied_bars_meet_at_zero(key):
    """What the price needs and what the company did, as two bars that start
    on the same zero: the INTC card had a tick and a box with no zero."""
    from config import Settings
    from pipeline import series as S
    from pipeline.chart import _style
    from pipeline.plates import load_plates

    reg = load_plates(Settings(_env_file=None).assets_dir)
    plate = reg.get(key)
    card = sd.implied(NS(ticker="INTC",
                         valuation={"implied_growth": 0.14, "hist_fcf_cagr": None,
                                    "rev_cagr": -0.096},
                         get=lambda k, d=None: {"ticker": "INTC"}.get(k, d)))
    data = S.plate_data(plate, {k: v for k, v in card.items() if k in plate.slots}).data
    needs, did = [n["attrs"] for n in S.data_layer(S.boxes(plate), data, reg.inks(plate),
                                                   **_style(reg, plate))[:2]]
    if key.endswith("9x16"):      # across: needs runs right of zero, did left
        zero = needs["x"]
        assert abs(did["x"] + did["width"] - zero) < 0.1 and needs["width"] > did["width"]
    else:                         # up: needs runs up to zero's line, did down from it
        zero = needs["y"] + needs["height"]
        assert abs(did["y"] - zero) < 0.1 and needs["height"] > did["height"]
    assert needs["fill"] != did["fill"]
    assert "0%" in plate.slots["marker"].note
