"""The data layer: `pipeline/series.py` against the kit's own JavaScript.

Two claims, each checked against design's code rather than a copy of it:

1. THE PORT DRAWS WHAT THE KIT DRAWS. For every plate the kit ships sample data
   for, `series.data_layer` on that data gives the same nodes, number for number,
   as `engine/export.js`'s `dataLayer` — the drawing design reviewed on its own
   proof sheet.
2. THE WRITER'S TAG GETS THERE. Design's sample COPY — the words and figures a
   plate prints — written as a `[PLATE]` tag and read back through the bot's
   grammar and `plate_data`, gives the same figures, flags and positions as the
   kit's sample data. Where a plate prints no scale the bot chooses its own, so
   a y range is the one thing not compared.

Both run the kit's engine in node (about fifteen seconds for all of it), so the
sample set is always the installed kit's, never a fixture that goes stale.
"""

from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from config import Settings
from pipeline import series as S
from pipeline.plate_tags import build_fill
from pipeline.plates import load_plates

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "kit"

# Every plate's sample copy and data at night, and the nodes the kit's own
# dataLayer draws from that data.
_DUMP = r"""
'use strict';
const path = require('path');
const root = path.resolve(process.argv[2]);
const E = require(path.join(root, 'engine/emit'));
const C = require(path.join(root, 'engine/content'));
const X = require(path.join(root, 'engine/export'));
const out = [], done = new Set();
E.build({ decorate: function (it, m, hour) {
  const key = it.key || (m && m.key);
  if (!key || hour !== 'night' || done.has(key)) return '';
  done.add(key);
  let c; try { c = C.contentFor(key, m) || {}; } catch (e) { return ''; }
  if (!c.data || !Object.keys(c.data).length) return '';
  const svg = X.dataLayer(m, c.data, hour), nodes = [];
  const re = /<(rect|circle|path) ([^/]*)\/>/g; let mm;
  while ((mm = re.exec(svg))) {
    const attrs = {}, ra = /([a-z-]+)="([^"]*)"/g; let a;
    while ((a = ra.exec(mm[2]))) attrs[a[1]] = a[2];
    nodes.push({ tag: mm[1], attrs });
  }
  out.push({ key, text: c.text || {}, data: c.data, nodes });
  return '';
}, onFile: function () {} });
process.stdout.write(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def reg():
    return load_plates(Settings(_env_file=None).assets_dir)


@pytest.fixture(scope="module")
def ink(reg):
    return S.ink_for(reg.palettes["night"])


@pytest.fixture(scope="module")
def samples(tmp_path_factory):
    node = shutil.which("node")
    if node is None or not (KIT / "engine" / "export.js").exists():
        pytest.skip("needs node and the kit's engine")
    script = tmp_path_factory.mktemp("kit") / "samples.js"
    script.write_text(_DUMP, encoding="utf-8")
    proc = subprocess.run([node, str(script), str(KIT)], capture_output=True, text=True,
                          timeout=600, cwd=ROOT)
    assert proc.returncode == 0, proc.stderr[-2000:]
    rows = json.loads(proc.stdout)
    assert len(rows) > 250, f"only {len(rows)} plates came back with sample data"
    return rows


def _nums(d: str) -> list[float]:
    return [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", d)]


def _differs(got: list[dict], want: list[dict]) -> str | None:
    """Why two node lists are not the same drawing, or None. Coordinates to a
    twentieth of a unit: the JS prints one decimal, and so does the port."""
    if len(got) != len(want):
        return f"{len(got)} nodes against the kit's {len(want)}"
    for i, (g, w) in enumerate(zip(got, want)):
        if g["tag"] != w["tag"]:
            return f"node {i}: {g['tag']} against {w['tag']}"
        for k, wv in w["attrs"].items():
            gv = str(g["attrs"].get(k))
            if k == "d":
                a, b = _nums(gv), _nums(wv)
                if len(a) != len(b) or any(abs(x - y) > 0.051 for x, y in zip(a, b)):
                    return f"node {i}: path {gv[:60]} against {wv[:60]}"
            elif k in ("fill", "stroke"):
                if gv.upper() != wv.upper():
                    return f"node {i}: {k} {gv} against {wv}"
            else:
                try:
                    if abs(float(gv) - float(wv)) > 0.051:
                        return f"node {i}: {k} {gv} against {wv}"
                except ValueError:
                    if gv != wv:
                        return f"node {i}: {k} {gv} against {wv}"
    return None


# ------------------------------------------------------------------ the port


def test_the_port_draws_every_sample_as_the_kit_does(reg, ink, samples):
    wrong = []
    for row in samples:
        plate = reg.get(row["key"])
        assert plate is not None, f"{row['key']} has sample data and is not installed"
        why = _differs(S.data_layer(S.boxes(plate), row["data"], ink), row["nodes"])
        if why:
            wrong.append(f"{row['key']}: {why}")
    assert not wrong, f"{len(wrong)} of {len(samples)} plates draw differently:\n" + "\n".join(wrong[:20])


# ------------------------------------------------------------ the round trip


def _csv(xs) -> str:
    return ",".join(f"{x:g}" for x in xs)


def _tag(plate, text: dict, data: dict) -> str:
    """Design's sample copy as the tag a writer would put in a script.

    Words go where the plate typesets them (the kit's review layer sets a word
    in a drawing region too; the bot refuses that, correctly). Figures the
    plate prints are its data; figures it does not print are named keys.
    """
    parts = [plate.key.split("/", 1)[1]]
    for k, v in text.items():
        sl = plate.slots.get(k)
        if sl is not None and "|" not in str(v) and not (sl.region and not sl.sets_type):
            parts.append(f"{k}={v}")
    dk = S.data_keys(plate)
    if data.get("series") and "series" in dk:
        parts.append("series=" + _csv(data["series"]))
    if data.get("series2") and "series2" in dk:
        parts.append("series2=" + _csv(data["series2"]))
    if data.get("steps") and "steps" in dk:
        parts += [f"open={data['open']:g}", "steps=" + _csv(data["steps"]), f"close={data['close']:g}"]
    if data.get("points"):
        parts.append("points=" + ",".join(f"{x:g}:{y:g}" for x, y in data["points"]))
    if data.get("split"):
        parts.append("split=" + _csv(data["split"]))
    if data.get("cycle"):
        parts.append("path=" + _csv(data["cycle"]))

    # A position or an extent is written on the scale the plate PRINTS — its
    # axis ends, or its first and last tick — not as the kit's fraction.
    def on_axis(fr: float) -> float:
        lo, hi = S.figure(text.get("axis-low")), S.figure(text.get("axis-high"))
        return lo + fr * (hi - lo) if lo is not None and hi is not None and hi != lo else fr

    ticks = [S.figure(text[n]) for n in sorted((n for n in text if re.match(r"^tick-\d+$", n)),
                                               key=lambda n: int(n.split("-")[1]))]
    ticks = [t for t in ticks if t is not None]
    for k, fr in (data.get("marks") or {}).items():
        if k in plate.slots and not k.startswith("growth-"):   # growth: off growth-value-N
            parts.append(f"{k}={fr * data['max'] if k == 'cac-line' else on_axis(fr):g}")
    for k, b in (data.get("bands") or {}).items():
        if k in plate.slots:
            lo, hi = (ticks[0], ticks[-1]) if len(ticks) >= 2 else (0.0, 1.0)
            tone = f",{b[2]}" if len(b) > 2 else ""
            parts.append(f"{k}={lo + b[0] * (hi - lo):g},{lo + b[1] * (hi - lo):g}{tone}")
    if data.get("low") is not None and "band" in plate.slots:
        parts.append(f"band={on_axis(data['low']):g},{on_axis(data['high']):g}")
    if data.get("mark") is not None and "marker" in plate.slots:
        parts.append(f"marker={on_axis(data['mark']):g}")
    if data.get("accent") is not None and "accent" in dk:
        parts.append(f"accent={data['accent'] + 1}")
    columns = any(re.match(r"^bar-\d+$", n) for n in plate.slots)
    if data.get("accentLast") and "accent" in dk and data.get("accent") is None and not columns:
        parts.append("accent=last")          # the kit draws accentLast on a line only
    return " | ".join(parts)


def _same(a: list[float], b: list[float], tol: float = 0.0) -> bool:
    """Equal, up to ONE power of ten across the whole list: a plate that prints
    `$120m` is read as 120,000,000 where the kit's sample data writes 120, and
    one scale for everything on the plot is all a drawing needs. `tol` is half
    the last digit of the figures the drawing was read from, in the bot's
    units: a plate printing `12.0` draws 12.0 where the sample's data says
    12.04, and the type on screen is the one the drawing has to agree with."""
    if len(a) != len(b):
        return False
    ref = next(((x, y) for x, y in zip(a, b) if abs(x) > 1e-12 and abs(y) > 1e-12), None)
    k = 1.0
    if ref is not None:
        e = round(math.log10(abs(ref[1] / ref[0])))
        k = 10.0 ** e
    return all(abs(x * k - y) <= tol + 1e-6 * max(1.0, abs(y)) for x, y in zip(a, b))


def _flat(v) -> list[float]:
    if isinstance(v, (int, float)):
        return [float(v)]
    out: list[float] = []
    for x in v:
        out += _flat(x) if isinstance(x, (list, tuple)) else [float(x)]
    return out


# Where the kit's sample and the plate disagree, and design has been asked.
# brand-vs-private-label's plot note says "spreadFill between them" and its
# sample leaves the gap unfilled with nothing on the plate saying why; the bot
# follows the note until design says otherwise.
_OPEN_WITH_DESIGN = {("brand-vs-private-label", "spread")}


def test_design_sample_copy_round_trips_to_the_kit_data(reg, samples):
    wrong = []
    for row in samples:
        if not row["nodes"]:
            continue                      # the kit's sample draws nothing either
        plate = reg.get(row["key"])
        stem = re.sub(r"-(16x9|9x16)$", "", plate.key.split("/", 1)[1])
        want = row["data"]
        fill = build_fill(reg, _tag(plate, row["text"], want))
        if fill.problems:
            wrong.append(f"{row['key']}: refused — {fill.problems[0]}")
            continue
        got = S.plate_data(plate, fill.values).data

        def bad(what: str, a, b) -> None:
            if (stem, what.split()[0]) not in _OPEN_WITH_DESIGN:
                wrong.append(f"{row['key']}: {what} is {b!r}, the kit's is {a!r}")

        # Figures drawn off the plate's own type are compared to its rounding.
        text = row["text"]

        def printed(names: list[str]) -> float:
            return max((S.rounding(text[n]) for n in names if S.figure(text.get(n)) is not None),
                       default=0.0)

        first, second = S._printed_series(plate)
        rail = next((f for f in (S._family(plate, s) for s in ("share", "move", "amount"))
                     if f), [])
        walk = S._family(plate, "value") if "bridge" in plate.slots else []
        tol = {"series": printed(first), "series2": printed(second),
               "bars": printed(rail), "split": printed(rail),
               "open": printed(walk), "steps": printed(walk), "close": printed(walk)}
        for k in ("series", "series2", "steps", "open", "close", "bars", "split", "points", "cycle"):
            if k in want and (k != "bars" or "bars" in plate.slots):
                a, b = _flat(want[k]), _flat(got[k]) if got.get(k) is not None else []
                if k == "bars":
                    a = a[:len(S._family(plate, "band"))]   # rowBars draws a bar per row, no more
                if not _same(a, b, tol.get(k, 0.0)):
                    bad(k, want[k], got.get(k))
        if "series2" in want and (got.get("tone2") or "subject2") != (want.get("tone2") or "subject2"):
            bad("tone2", want.get("tone2"), got.get("tone2"))
        if bool(got.get("spread")) != bool(want.get("spread")):
            bad("spread", want.get("spread"), got.get("spread"))
        if "accent" in want and got.get("accent") != want["accent"]:
            bad("accent", want["accent"], got.get("accent"))
        # A position is compared as the fraction the kit draws, to half the
        # printed figure's last digit; `cac-line` sits on the scale the bot
        # chose, which is its own.
        for k, fr in (want.get("marks") or {}).items():
            g = (got.get("marks") or {}).get(k)
            if k != "cac-line" and (g is None or abs(fr - g) > 0.02):
                bad(f"marks[{k}]", fr, g)
        for k, b in (want.get("bands") or {}).items():
            g = (got.get("bands") or {}).get(k)
            if g is None or abs(b[0] - g[0]) > 0.02 or abs(b[1] - g[1]) > 0.02 \
                    or (len(b) > 2 and (len(g) < 3 or g[2] != b[2])):
                bad(f"bands[{k}]", b, g)
        for k in ("low", "high", "mark"):
            if k in want and (got.get(k) is None or abs(want[k] - got[k]) > 0.02):
                bad(k, want[k], got.get(k))
    assert not wrong, f"{len(wrong)} disagreements:\n" + "\n".join(wrong[:25])


# --------------------------------------------------------------- the grammar


def _data(reg, tag: str):
    fill = build_fill(reg, tag)
    return fill, S.plate_data(reg.get(fill.key), fill.values)


def test_the_second_series_is_drawn_in_the_ink_its_legend_keys(reg):
    """book-to-bill keys revenue in quiet; drawn in subject2, the bars are a
    colour the legend beside them does not show."""
    b2b = reg.get("charts/book-to-bill-16x9")
    assert b2b.keys == {"legend-1": "up", "legend-2": "neutral-data"}
    got = S.plate_data(b2b, {f"bar-{i}": str(600 + i) for i in range(1, 9)}
                       | {f"pair-{i}": str(580 + i) for i in range(1, 9)})
    assert got.data["tone2"] == "quiet"
    spread = reg.get("charts/price-cost-spread-16x9")
    assert spread.keys["legend-2"] == "down"
    got = S.plate_data(spread, {"series": "6,5,4,3,2,1,1,1", "series2": "9,7,5,3,2,2,3,4"})
    assert got.data["tone2"] == "subject2"


def test_every_hour_keys_the_same_ink(reg):
    for key in reg.all_plates():
        p = reg.get(key)
        if p.keys and p.at_base_hour and p.at_base_hour != key:
            assert p.keys == reg.get(p.at_base_hour).keys, key


def test_the_gap_is_not_filled_where_the_two_lines_add_up(reg):
    """price and volume ADD to organic growth; the area between them measures
    nothing, and the plate's caution says not to fill it."""
    series = {"series": "8,7,6,4,4,3,2,2", "series2": "-2,-3,-3,-3,-2,-2,-1,0"}
    for stem in ("price-vs-volume", "traffic-vs-ticket", "net-price-vs-volume"):
        got = S.plate_data(reg.get(f"charts/{stem}-16x9"), series)
        assert not got.data.get("spread"), stem
    got = S.plate_data(reg.get("charts/price-cost-spread-16x9"), series)
    assert got.data.get("spread") is True


def test_two_series_share_one_scale(reg):
    got = S.plate_data(reg.get("charts/price-cost-spread-16x9"),
                       {"series": "1,1,1,1,1,1,1,2", "series2": "10,20,30,40,50,60,70,80"})
    assert got.data["max"] >= 80, "the small series was given a scale of its own"


def test_a_walk_that_does_not_reach_its_close_is_refused(reg):
    plate = reg.get("figures/waterfall-4s-16x9")
    ok = S.plate_data(plate, {"open": "100", "steps": "10,-5,20,-15", "close": "110"})
    assert ok.ok and ok.data["steps"] == [10, -5, 20, -15]
    bad = S.plate_data(plate, {"open": "100", "steps": "10,-5,20,-15", "close": "140"})
    assert any("does not add up" in p for p in bad.problems)


def test_a_walk_with_more_steps_than_columns_is_refused(reg):
    got = S.plate_data(reg.get("figures/waterfall-3s-16x9"),
                       {"open": "100", "steps": "10,-5,20,-15,5", "close": "115"})
    assert got.problems


def test_a_line_accents_only_its_last_point(reg):
    plate = reg.get("charts/price-cost-spread-16x9")
    base = {"series": "6,5,4,3,2,1,1,1"}
    assert S.plate_data(plate, base | {"accent": "last"}).data.get("accentLast") is True
    assert S.plate_data(plate, base | {"accent": "3"}).problems


def test_a_rail_plate_takes_the_row_the_script_is_about(reg):
    plate = reg.get("figures/end-market-exposure-16x9")
    assert "accent" in S.data_keys(plate)
    fill, got = _data(reg, "end-market-exposure-16x9 | share-1=34% | share-2=26% | share-3=18% "
                           "| share-4=12% | share-5=10% | accent=3")
    assert got.data["accent"] == 2


def test_a_plot_named_series_draws_its_line_once(reg):
    """macro-series has a region called `series`; `series=` is the plot's line,
    not a small-multiple tile on a scale of its own."""
    plate = reg.get("charts/macro-series-16x9")
    got = S.plate_data(plate, {"series": "11,11.4,11.8,12,11.9,13.9"})
    assert "tiles" not in got.data
    paths = [n for n in S.data_layer(S.boxes(plate), got.data, {}) if n["tag"] == "path"]
    assert len(paths) == 1


def test_a_figure_reads_the_way_a_filing_prints_it():
    assert S.figure("$4.1m") == pytest.approx(4.1e6)
    assert S.figure("−3.5%") == pytest.approx(-3.5)
    assert S.figure("(120)") == pytest.approx(-120)
    assert S.figure("1.2bn") == pytest.approx(1.2e9)
    assert S.figure("0.84x") == pytest.approx(0.84)
    assert S.figure("n/a") is None
    assert S.figure("+6%") == pytest.approx(6)


def test_a_walk_is_checked_to_the_rounding_it_prints(reg):
    """`$4.2bn` is anything from 4.15 to 4.25 billion. The tolerance is in the
    printed unit, or every walk printed in billions is refused for adding up."""
    plate = reg.get("figures/arr-bridge-16x9")
    walk = {"value-1": "$4.2bn", "value-2": "+$0.3bn", "value-3": "+$0.1bn",
            "value-4": "−$0.2bn", "value-5": "+$0.1bn", "value-6": "$4.6bn"}
    ok = S.plate_data(plate, walk)
    assert ok.ok, ok.problems
    assert ok.data["open"] == pytest.approx(4.2e9)
    wrong = S.plate_data(plate, walk | {"value-6": "$5.2bn"})
    assert any("does not add up" in p for p in wrong.problems)


def test_a_paired_chart_draws_the_rows_it_prints(reg):
    plate = reg.get("charts/sbc-vs-buybacks-16x9")
    rows = {f"spend-{i}": f"${v}m" for i, v in enumerate((0, 120, 240, 310, 380, 420), 1)}
    rows |= {f"sbc-{i}": f"${v}m" for i, v in enumerate((180, 230, 290, 340, 395, 440), 1)}
    got = S.plate_data(plate, rows | {"series": "1,2,3,4,5,6"})
    assert got.data["series"][1] == pytest.approx(120e6)
    assert got.data["series2"][5] == pytest.approx(440e6)
    assert any("series= is not drawn" in w for w in got.warnings)


def test_the_menu_says_what_each_data_plate_draws(reg):
    menu = S.data_menu
    assert "value-1…6 are the walk" in menu(reg.get("figures/arr-bridge-16x9"))
    assert "spend-1…6 and sbc-1…6 are the two series" in menu(reg.get("charts/sbc-vs-buybacks-16x9"))
    b2b = menu(reg.get("charts/book-to-bill-16x9"))
    assert "series=<8 figures>" in b2b and "series2=<8 figures>" in b2b
    assert "share-1…5 draw the bars" in menu(reg.get("figures/end-market-exposure-16x9"))
    assert "cac-line=<one figure, on the line's scale>" in menu(reg.get("figures/cac-payback-16x9"))
    assert menu(reg.get("cards/hook-card-t1-16x9") or reg.get("figures/big-fraction-16x9")) == ""
