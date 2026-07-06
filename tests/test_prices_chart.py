"""Price source + branded chart component (§4: the pipeline renders its
own chart from its own price data — never a screenshot)."""

import json

from PIL import Image

from pipeline.chart import (
    render_marker_price_chart,
    render_metric_chart,
    render_price_chart,
)
from pipeline.prices import (
    MockPriceSource,
    PriceSeries,
    get_price_history,
    synthetic_series,
)

# ------------------------------------------------------------------- prices


def test_synthetic_series_is_deterministic():
    a = synthetic_series("EXMPL", 120)
    b = synthetic_series("EXMPL", 120)
    assert a.closes == b.closes and a.dates == b.dates
    assert synthetic_series("OTHER", 120).closes != a.closes
    assert len(a.closes) == len(a.dates) >= 10


def test_mock_source_prefers_fixture(settings):
    series = MockPriceSource(settings).history("EXMPL", 120)
    assert series.source == "fixture"
    assert series.ticker == "EXMPL"
    assert abs(series.pct_change_1d) > 5, "trending fixture must show a real move"


def test_mock_source_synthesizes_unknown_ticker(settings):
    series = MockPriceSource(settings).history("ZZZQ", 120)
    assert series.source == "synthetic"
    assert len(series.closes) >= 10


def test_history_is_cached(settings):
    class CountingSource:
        calls = 0
        def history(self, ticker, days):
            CountingSource.calls += 1
            return synthetic_series(ticker, days)

    src = CountingSource()
    a = get_price_history("EXMPL", settings, source=src)
    b = get_price_history("EXMPL", settings, source=src)
    assert CountingSource.calls == 1, "second read must come from cache"
    assert a.closes == b.closes
    cache = settings.cache_dir / "prices" / f"EXMPL_{settings.price_history_days}.json"
    assert cache.exists()


def test_history_never_raises(settings):
    class ExplodingSource:
        def history(self, ticker, days):
            raise RuntimeError("feed is down")

    series = get_price_history("BOOM", settings, source=ExplodingSource())
    assert series.degraded and series.source == "synthetic"


def test_pct_changes():
    s = PriceSeries(ticker="T", dates=["a", "b", "c"], closes=[10.0, 10.0, 12.0])
    assert s.pct_change_1d == 20.0
    assert s.pct_change_period == 20.0


# -------------------------------------------------------------------- chart


def test_price_chart_renders_with_meta(settings, tmp_path):
    series = MockPriceSource(settings).history("EXMPL", 120)
    out, meta = render_price_chart(series, tmp_path / "chart.png", settings,
                                   size=(500, 390), move_text="+29% today")
    assert out.exists()
    img = Image.open(out)
    assert img.size == (500, 390)
    x0, y0, x1, y1 = meta["plot_box"]
    lx, ly = meta["last_point"]
    assert x0 < lx <= x1 + 1 and y0 - 1 <= ly <= y1 + 1, "last point inside the plot"
    assert meta["direction"] in ("up", "down")
    assert len(meta["headline_slots"]) == 3
    for sx, sy in meta["headline_slots"]:
        assert 0 <= sx < 500 and 0 <= sy < 390


def test_price_chart_down_direction(settings, tmp_path):
    series = PriceSeries(ticker="DN", dates=[f"2026-06-{d:02d}" for d in range(1, 11)],
                         closes=[10, 9.5, 9.7, 9, 8.5, 8.6, 8, 7.5, 7.2, 6])
    _, meta = render_price_chart(series, tmp_path / "down.png", settings, size=(400, 320))
    assert meta["direction"] == "down"


def test_marker_price_chart_same_contract(settings, tmp_path):
    """The napkin chart returns the same anchor contract so a SHORT can
    open on either style."""
    series = MockPriceSource(settings).history("EXMPL", 120)
    clean = render_price_chart(series, tmp_path / "c.png", settings, size=(500, 390))[1]
    out, marker = render_marker_price_chart(
        series, tmp_path / "m.png", settings, size=(500, 390), move_text="+29%")
    assert out.exists() and Image.open(out).size == (500, 390)
    assert marker["style"] == "marker"
    assert set(clean) - {"style"} <= set(marker), "same keys as the clean chart"
    assert marker["direction"] == clean["direction"]
    x0, y0, x1, y1 = marker["plot_box"]
    lx, ly = marker["last_point"]
    assert x0 < lx <= x1 + 2 and y0 - 2 <= ly <= y1 + 2


def test_marker_chart_is_deterministic(settings, tmp_path):
    series = MockPriceSource(settings).history("EXMPL", 120)
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    render_marker_price_chart(series, a, settings, size=(400, 320))
    render_marker_price_chart(series, b, settings, size=(400, 320))
    assert a.read_bytes() == b.read_bytes(), "seeded wobble -> identical render"


def test_metric_chart_multi_year(settings, tmp_path):
    out = render_metric_chart(
        "Revenue", ["2021", "2022", "2023", "2024", "2025"],
        [400e6, 430e6, 470e6, 490e6, 496e6],
        tmp_path / "metric.png", settings, size=(640, 360),
    )
    assert out.exists()
    assert Image.open(out).size == (640, 360)


def test_metric_chart_handles_negatives_and_gaps(settings, tmp_path):
    out = render_metric_chart(
        "Net income", ["2021", "2022", "2023"], [-50e6, None, 20e6],
        tmp_path / "neg.png", settings, size=(640, 360),
    )
    assert out.exists()


def test_metric_chart_no_data(settings, tmp_path):
    out = render_metric_chart("FCF", [], [None, None],
                              tmp_path / "empty.png", settings, size=(400, 300))
    assert out.exists()


def test_fixture_matches_series_schema(fixtures_dir):
    data = json.loads((fixtures_dir / "prices" / "EXMPL.json").read_text())
    assert len(data["dates"]) == len(data["closes"])
    series = PriceSeries.from_json(json.dumps(data))
    assert series.ticker == "EXMPL"
