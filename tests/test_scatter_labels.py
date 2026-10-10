"""The peer scatter: marks spread over the plot, each named beside its mark.

`peers/scatter-16x9` publishes no scale, and series.js says points then
"arrive 0-1". Handed raw growth and multiples, every company clamped into the
top right corner as one dot. Its `ticker-N` boxes are `overlay: true`, set
"beside its own mark" by the renderer, and were read as a band named "True":
no company was ever named.
"""

from __future__ import annotations

import numpy as np
import pytest

from pipeline import series as S
from pipeline.chart import draw_declared
from pipeline.plate_frames import render_still

TICKERS = ["EXMPL", "AAA", "BBB", "CCC", "DDD", "EEE"]
VALUES = {"kicker": "GROWTH VS MULTIPLE", "x-axis": "Revenue growth, %",
          "y-axis": "EV/EBIT", "points": "12:25,8:14,15:31,5:11,20:38,10:18",
          "accent": "1", **{f"ticker-{i}": t for i, t in enumerate(TICKERS, start=1)}}


@pytest.fixture(scope="module")
def settings():
    from config import Settings
    return Settings(MOCK_MODE=True, _env_file=None)


@pytest.fixture(scope="module")
def reg(settings):
    from pipeline.plates import load_plates
    return load_plates(settings.assets_dir)


def test_a_ticker_is_placed_by_the_renderer_not_a_band(reg):
    for key in ("peers/scatter-16x9", "peers/rule-of-40-16x9", "peers/rule-of-40-9x16"):
        t = reg.get(key).slots["ticker-1"]
        assert t.placed and not t.is_band and t.overlay == "", key
        assert t.is_text, key
    band = reg.get("tables/numbers-sheet-4r-16x9").slots["band-1"]
    assert band.is_band and not band.placed


def test_unscaled_points_spread_over_the_plot(reg):
    plate = reg.get("peers/scatter-16x9")
    pts = S.plate_data(plate, VALUES).data["points"]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    assert min(xs) == pytest.approx(S.SCATTER_PAD) and max(xs) == pytest.approx(1 - S.SCATTER_PAD)
    assert min(ys) == pytest.approx(S.SCATTER_PAD) and max(ys) == pytest.approx(1 - S.SCATTER_PAD)
    box = S.boxes(plate)["plot-area"]
    marks = S.scatter_marks(box, pts)
    assert len({(round(x), round(y)) for _i, x, y, _r, _o in marks}) == len(TICKERS)
    assert not any(off for *_rest, off in marks)


def test_a_fixed_scale_is_kept(reg):
    plate = reg.get("peers/rule-of-40-16x9")
    pts = S.plate_data(plate, {**VALUES, "points": "10:20,30:5"}).data["points"]
    assert pts == [[10, 20], [30, 5]]


def test_each_company_is_named_beside_its_own_mark(reg, settings):
    view = reg.at("night")
    plate = view.get("peers/scatter-16x9")
    bare = render_still(plate, VALUES, settings, view).convert("RGBA")
    named = bare.copy()
    draw_declared(view, plate, VALUES, named, seed="t", settings=settings)
    unnamed = bare.copy()
    draw_declared(view, plate, {k: v for k, v in VALUES.items() if not k.startswith("ticker-")},
                  unnamed, seed="t", settings=settings)
    type_ink = np.abs(np.asarray(named).astype(int) - np.asarray(unnamed).astype(int)).max(axis=2) > 0
    k = plate.export_scale
    pts = S.plate_data(plate, VALUES).data["points"]
    marks = S.scatter_marks(S.boxes(plate)["plot-area"], pts, 0)
    for i, cx, cy, r, _off in marks:
        w = plate.slots[f"ticker-{i + 1}"].w
        near = type_ink[int((cy - r - 40) * k):int((cy + r + 40) * k),
                        max(int((cx - r - 20 - w) * k), 0):int((cx + r + 20 + w) * k)]
        assert near.any(), f"{TICKERS[i]} is not beside its mark"
    # and none of them is parked in the plot's top-left corner, where the kit
    # publishes the boxes
    t = plate.slots["ticker-1"]
    assert not type_ink[t.y * k:(t.y + t.h) * k, t.x * k:(t.x + t.w) * k].any()
