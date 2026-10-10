"""The short's price chart: the last close beside the end of its line, on a
scale whose labels are the numbers they print.

Valentin, 10 Oct 2026, on the short: "it shows a 15.42 between 16 and 17, i
don't really know what that means, maybe it does want to show the current
stock price, but it is not well placed". The kit leaves `mark-last` to code
("placed by code at the path end"); it was typeset in its box instead, the
middle of the right-hand column.
"""

from __future__ import annotations

import numpy as np
import pytest

CLOSES = [15.2, 15.9, 16.8, 17.6, 18.1, 17.2, 17.8, 16.4, 16.9, 15.6, 15.42]


@pytest.fixture(scope="module")
def settings():
    from config import Settings
    return Settings(MOCK_MODE=True, _env_file=None)


@pytest.fixture(scope="module")
def reg(settings):
    from pipeline.plates import load_plates
    return load_plates(settings.assets_dir).at("night")


def test_mark_last_is_set_by_code_not_in_its_box(reg):
    plate = reg.get("charts/line-dense-9x16")
    assert plate.slots["mark-last"].placed
    assert not plate.slots["mark-high"].placed


def test_the_last_close_sits_beside_where_the_line_ends(reg, settings):
    from pipeline.chart import declared_layer
    from pipeline.macro_series import nice_axis

    plate = reg.get("charts/line-dense-9x16")
    axis = nice_axis(min(CLOSES), max(CLOSES), 4)
    values = {"plot-area": ",".join(f"{c:.2f}" for c in CLOSES),
              **{f"y-{i + 1}": f"{v:g}" for i, v in enumerate(axis)}}
    bare = np.asarray(declared_layer(reg, plate, values, settings=settings))
    marked = np.asarray(declared_layer(reg, plate, {**values, "mark-last": "15.42"},
                                       settings=settings))
    changed = np.abs(marked.astype(int) - bare.astype(int)).max(axis=2) > 0
    ys, xs = np.nonzero(changed)
    assert len(ys), "mark-last drew nothing"
    k = plate.export_scale
    area = plate.slots["plot-area"]
    lo, hi = axis[0], axis[-1]
    end_y = (area.y + area.h - (CLOSES[-1] - lo) / (hi - lo) * area.h) * k
    # within a line or two of the end of the line, in the column's right side
    assert abs(ys.mean() - end_y) < 70 * k, (ys.mean(), end_y)
    assert xs.min() > (area.x + area.w / 2) * k


def test_the_axis_labels_are_round_and_hold_the_whole_series():
    from pipeline.macro_series import nice_axis

    got = nice_axis(15.13, 18.20, 4)
    assert got[0] <= 15.13 and got[-1] >= 18.20
    assert all(abs(v * 2 - round(v * 2)) < 1e-9 for v in got), got


def test_the_last_close_is_never_set_on_the_line_itself(reg, settings):
    """The render's own shape: a ridge, a fall straight down the right-hand
    column between two closes, then low wiggles. Tested against the closes
    alone, "15.42" sat on the fall."""
    from pipeline.chart import declared_layer
    from pipeline.macro_series import nice_axis

    ridge = [17.0 + 0.8 * ((i * 7) % 5) / 4 for i in range(44)]
    closes = ridge + [17.6, 15.9, 15.6, 15.3, 15.9, 15.2, 15.42]
    plate = reg.get("charts/line-dense-9x16")
    axis = nice_axis(min(closes), max(closes), 4)
    values = {"plot-area": ",".join(f"{c:.2f}" for c in closes),
              **{f"y-{i + 1}": f"{v:g}" for i, v in enumerate(axis)}}
    bare = np.asarray(declared_layer(reg, plate, values, settings=settings))
    marked = np.asarray(declared_layer(reg, plate, {**values, "mark-last": "15.42"},
                                       settings=settings))
    changed = np.abs(marked.astype(int) - bare.astype(int)).max(axis=2) > 0
    ys, xs = np.nonzero(changed)
    assert len(ys), "mark-last drew nothing"
    line = bare[..., 3] > 0
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    assert not line[y0:y1, x0:x1].any(), "the label is set on the line"
