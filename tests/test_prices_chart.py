"""The data path, and the four ways a chart can lie about its own numbers.

`chart.py` draws the series and nothing else — the plate draws the axes, the
gridlines, the period heads and the frame. Every test here is a way the path can
disagree with the furniture behind it, which is the failure mode that looks
completely fine in a thumbnail.
"""

from __future__ import annotations

import pytest
from PIL import Image

from config import Settings
from pipeline.chart import (
    PlotArea,
    axis_domain,
    draw_bars,
    draw_line,
    draw_row_bars,
    plot_area,
    render_series,
    series_points,
    trough_point,
)
from pipeline.plates import load_plates


@pytest.fixture(scope="module")
def reg():
    return load_plates(Settings(_env_file=None).assets_dir)


@pytest.fixture(scope="module")
def settings():
    return Settings(_env_file=None)


# ---------------------------------------------------------------- six periods

def test_a_series_must_be_six_periods():
    """Four fiscal years, the last full year, LTM.

    Five is not a shorter chart, it is a chart with LTM missing — which is the
    column the argument usually turns on.
    """
    with pytest.raises(ValueError, match="six periods|LTM"):
        series_points([1.0, 2.0, 3.0, 4.0, 5.0])


def test_six_periods_is_accepted():
    pts = series_points([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    assert len(pts) == 6


def test_an_empty_period_stays_empty():
    """An empty cell means NO DATA. Interpolating across it invents a number,
    which is the one thing the renderer must never do."""
    pts = series_points([1.0, None, 3.0, 4.0, 5.0, 6.0])
    assert pts[1] is None
    assert [p for p in pts if p is not None][1] == (2, 3.0)


def _period_heads(plate) -> list[str]:
    """`head-1`…`head-6`. NOT `head-spark`, which labels the sparkline column
    rather than naming a period — counting it reads a six-period sheet as
    seven, which is how a check like this ends up being deleted for crying
    wolf instead of being made precise."""
    return [n for n in plate.slots
            if n.startswith("head-") and n.split("-", 1)[1].isdigit()]


def test_every_time_series_plate_is_authored_six_wide(reg):
    """The plates themselves, not just the code that fills them."""
    for key in reg.family("charts"):
        if "dense" in key:
            continue          # line-dense is four heads over many observations
        heads = _period_heads(reg.assets[key])
        assert len(heads) == 6, f"{key} has {len(heads)} period heads"

    for key in reg.family("tables"):
        heads = _period_heads(reg.assets[key])
        if not heads:
            continue          # cash-flow is a statement, not a period grid
        assert len(heads) == 6, f"{key} has {len(heads)} period heads"

    for key in reg.family("structure"):
        heads = _period_heads(reg.assets[key])
        if heads:
            assert len(heads) == 6, f"{key} has {len(heads)} period heads"


# ------------------------------------------------------------------- the axis

def test_the_domain_comes_from_the_axis_labels(reg):
    """The scale is what the DIRECTOR wrote on the axis.

    A path fitted to its own min and max lands wherever it likes against
    gridlines that claim otherwise — a peak between the 12 and 16 rules while
    the label says 13.2.
    """
    plate = reg.require("charts/line-6y-16x9")
    got = axis_domain(plate, {"y-1": "0", "y-2": "4", "y-3": "8",
                              "y-4": "12", "y-5": "16"})
    assert got == (0.0, 16.0)


def test_an_unlabelled_axis_has_no_domain(reg):
    """None, not a guess — the caller falls back to the data's own range, and
    then nothing on the plate claims otherwise."""
    plate = reg.require("charts/line-6y-16x9")
    assert axis_domain(plate, {}) is None


def test_the_axis_reads_units_off_the_label(reg):
    plate = reg.require("charts/line-6y-16x9")
    assert axis_domain(plate, {"y-1": "$0", "y-5": "$16B"}) == (0.0, 16e9)
    assert axis_domain(plate, {"y-1": "-2", "y-5": "6"}) == (-2.0, 6.0)


def test_the_path_lands_on_the_scale_the_axis_declares(reg, settings):
    """The whole point, measured: a value at the top of the declared domain
    reaches the top of the plot area."""
    plate = reg.require("charts/line-6y-16x9")
    area = plot_area(plate)
    img = Image.new("RGBA", plate.pixel_size, (0, 0, 0, 0))
    draw_line(img, area, [0.0, 0.0, 0.0, 0.0, 0.0, 16.0], (0, 0, 0),
              domain=(0.0, 16.0))
    box = img.getbbox()
    assert box is not None
    # The last point is at the domain's ceiling, so the ink reaches the top of
    # the reserved region (within the stroke's own width).
    assert box[1] <= area.y + 12, f"top of ink at {box[1]}, plot area at {area.y}"
    assert box[3] >= area.y + area.h - 12


# -------------------------------------------------------------------- the bars

def test_bars_stand_on_the_zero_the_domain_declares(reg):
    """A negative bar hangs below zero and a positive one stands on it, with
    zero where the axis puts it — not where the data happens to start."""
    plate = reg.require("charts/bars-6y-16x9")
    area = plot_area(plate)
    img = Image.new("RGBA", plate.pixel_size, (0, 0, 0, 0))
    draw_bars(img, area, [1.0, None, None, None, None, None],
              lambda v: (0, 0, 0), domain=(-2.0, 6.0))
    pos = img.getbbox()
    img2 = Image.new("RGBA", plate.pixel_size, (0, 0, 0, 0))
    draw_bars(img2, area, [-1.0, None, None, None, None, None],
              lambda v: (0, 0, 0), domain=(-2.0, 6.0))
    neg = img2.getbbox()
    zero_y = area.y + (1.0 - (0.0 - -2.0) / 8.0) * area.h
    assert pos[3] <= zero_y + 12, "a positive bar should not cross zero"
    assert neg[1] >= zero_y - 12, "a negative bar should not cross zero"


def test_row_bars_put_zero_where_the_domain_does():
    """When every move is negative, zero lands on the right-hand edge and every
    bar runs left from it — the shape the beat has."""
    area = PlotArea(0, 0, 400, 200)
    img = Image.new("RGBA", (400, 200), (0, 0, 0, 0))
    draw_row_bars(img, area, [-1.0, -2.0, -3.0, -4.0], lambda v: (0, 0, 0))
    box = img.getbbox()
    assert box is not None
    assert box[2] >= 390, "bars should run left from a zero at the right edge"


# ------------------------------------------------------------------- the cycle

def test_the_trough_is_reported_on_real_coordinates():
    area = PlotArea(0, 0, 600, 300)
    values = [10.0, 4.0, 2.0, 5.0, 8.0, 12.0]
    pt = trough_point(area, values, 2)
    assert pt is not None
    x, y = pt
    # Index 2 of six is two fifths across, and the minimum sits at the bottom.
    assert abs(x - 240.0) < 1.0
    assert y > 250


# ---------------------------------------------------------- the whole plate

def test_a_rendered_chart_is_the_plate_plus_a_path(reg, settings):
    """The plate is drawn, and the path is drawn into it. Nothing else."""
    plate = reg.require("charts/line-6y-16x9")
    values = {"y-1": "0", "y-2": "4", "y-3": "8", "y-4": "12", "y-5": "16",
              "head-1": "FY21", "head-6": "LTM", "title": "Revenue"}
    img = render_series(reg, plate, [5.6, 9.8, 6.1, 6.7, 7.4, 13.2],
                        settings, slot_values=values)
    assert img.size == tuple(plate.pixel_size)
    # The path put ink inside the plot area that the bare plate does not have.
    bare = Image.open(plate.path).convert("RGB")
    area = plot_area(plate)
    crop = (area.x + 20, area.y + 20, area.x + area.w - 20, area.y + area.h - 20)
    assert list(img.convert("RGB").crop(crop).getdata()) != \
        list(bare.crop(crop).getdata())
