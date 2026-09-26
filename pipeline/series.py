"""The data layer: what goes INSIDE a plate's data regions, drawn flat.

Every data plate in the kit is an empty form. It draws its frame, its axes, its
labels and its rails, reserves a region for the numbers, and says in the
region's note which renderer fills it — "series.bridge", "rowBars draws one bar
per band-N", "axisMark draws it; pass (g + 20) / 40". Design's
`kit/engine/series.js` is those renderers, and `kit/engine/export.js`'s
`dataLayer` is the one place that decides which renderer a plate gets from the
data it is handed. This module is both, ported line for line, so a plate in a
video carries the same data drawing design reviewed on its own proof sheet.

THE RULE EVERY RENDERER OBEYS IS series.js's: read the geometry the plate
published and re-derive nothing. Every x comes from a column's `anchorX`, every
baseline from its `baselineY`, every box from the slot. A renderer that works a
column position out for itself drifts the day the plate changes, and a line half
a tick off its axis still looks like a line.

Renderers return PLAIN NODES — `{"tag": "rect"|"circle"|"path", "attrs": …}` in
the plate's canvas units, exactly the JS shape — and :func:`paint` puts them on
a delivered-size image. Keeping the node list is what lets the tests compare
this port against the kit's own JavaScript, number for number.

The second half is :func:`plate_data`, which is ours: it turns what the WRITER
put in a `[PLATE]` tag into the data object `dataLayer` takes. Where the plate
prints the figures it draws (a walk's `value-N`, a rail's `share-N`), those
printed figures are the data, so the drawing cannot disagree with the type
beside it. Where it prints none (a spread's two lines, a payback curve), the
writer names the series outright. Nothing here computes a figure.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

# ── the kit's ink roles, by the registry's names ──────────────────────────────
#
# series.js asks for `subject`, `subject2`, `quiet`, `axis`, `band`… — the ink
# names in design-tokens.json. The registry publishes the same eight colours
# under the bot's role names, and the kit's own port (engine/port.js `palFor`)
# is the mapping: up IS subject, down IS subject2, and so on. Written once here.
KIT_INK = {
    "ground": "ground",
    "band": "second-ground",
    "structure": "structure",
    "subject": "up",
    "subject2": "down",
    "quiet": "neutral-data",
    "attention": "attention",
    "axis": "other-party",
}


def ink_for(palette: dict[str, str]) -> dict[str, str]:
    """The kit's ink names → hex, from a registry palette (one hour's)."""
    return {kit: palette[ours] for kit, ours in KIT_INK.items() if ours in palette}


# ── helpers, with the JavaScript's own arithmetic ─────────────────────────────


def _js_round(n: float) -> float:
    """`Math.round`: half rounds UP, toward +infinity, not to even."""
    return math.floor(n + 0.5)


def r1(n: float) -> float:
    return _js_round(n * 10) / 10


def num(v) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v) if math.isfinite(v) else None


def clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


def rect(x, y, w, h, fill) -> dict:
    return {"tag": "rect", "attrs": {"x": r1(x), "y": r1(y), "width": r1(max(0.0, w)),
                                     "height": r1(max(0.0, h)), "fill": fill}}


def circle(cx, cy, r, fill) -> dict:
    return {"tag": "circle", "attrs": {"cx": r1(cx), "cy": r1(cy), "r": r1(r), "fill": fill}}


def path(d: str, attrs: dict | None = None) -> dict:
    return {"tag": "path", "attrs": {"d": d, "fill": "none", **(attrs or {})}}


def _pts(points) -> str:
    return "L".join(f"{_fmt(r1(x))},{_fmt(r1(y))}" for x, y in points)


def _fmt(v: float) -> str:
    """A number as JavaScript prints it: `12` not `12.0`."""
    return str(int(v)) if float(v).is_integer() else repr(float(v))


def _ink(ink: dict, name: str, fallback: str) -> str:
    return ink.get(name) or fallback


@dataclass
class Extent:
    lo: float
    hi: float

    @property
    def span(self) -> float:
        return self.hi - self.lo


def extent(values, *, min=None, max=None, zero=None) -> Extent:  # noqa: A002
    """A scale that includes zero when the data crosses it, unless told not to.

    "A bar chart whose baseline is not zero is a lie the audit cannot catch."
    """
    vs = [v for v in values if num(v) is not None]
    lo = min if min is not None else (builtin_min(vs) if vs else math.inf)
    hi = max if max is not None else (builtin_max(vs) if vs else -math.inf)
    if zero is not False and lo > 0:
        lo = 0.0
    if zero is not False and hi < 0:
        hi = 0.0
    if hi == lo:
        hi = lo + 1
    return Extent(float(lo), float(hi))


builtin_min, builtin_max = min, max


# ── the renderers ─────────────────────────────────────────────────────────────


def cycle_arc(box, values, ink, *, trough_box=None, weight=10, dot=7) -> dict:
    """`series.cycleArc`: every period between the two moments, as a ribbon,
    and the trough's coordinates back so its label can sit on the data."""
    if not box or len(values) < 2:
        return {"nodes": [], "returns": None}
    e = extent(values, zero=False)
    n = len(values)
    x = lambda i: box["x"] + (i / (n - 1)) * box["w"]            # noqa: E731
    y = lambda v: box["y"] + box["h"] - ((v - e.lo) / e.span) * box["h"]  # noqa: E731
    pts = [(x(i), y(v)) for i, v in enumerate(values)]
    t = weight / 2
    up = [(p[0], p[1] - t) for p in pts]
    dn = [(p[0], p[1] + t) for p in reversed(pts)]
    subject = _ink(ink, "subject", "#7FD4E8")
    nodes = [{"tag": "path", "attrs": {"d": "M" + _pts(up + dn) + "Z", "fill": subject}}]
    nodes += [circle(x(i), y(v), dot, subject) for i, v in enumerate(values)]
    mi = 0
    for i, v in enumerate(values):
        if num(v) is not None and v < values[mi]:
            mi = i
    nodes.append(circle(x(mi), y(values[mi]), dot + 5, _ink(ink, "attention", "#F07A5A")))
    tb = None
    if trough_box:
        tb = {"x": r1(x(mi) - trough_box["w"] / 2), "y": r1(y(values[mi]) - trough_box["h"] - 18),
              "w": trough_box["w"], "h": trough_box["h"]}
    return {"nodes": nodes, "returns": {"minIndex": mi, "minValue": values[mi],
                                        "x": r1(x(mi)), "y": r1(y(values[mi])), "troughBox": tb}}


def row_bars(box, rows, values, ink, *, accent=None, thickness=0.42, min=None, max=None) -> dict:  # noqa: A002
    """`series.rowBars`: one horizontal bar per row, on ONE scale shared across
    the rows, from a zero rule the renderer places."""
    if not box or not rows:
        return {"nodes": [], "returns": None}
    e = extent(values, min=min, max=max)
    zero_x = box["x"] + ((0 - e.lo) / e.span) * box["w"]
    nodes = []
    if e.lo < 0:
        nodes.append(rect(zero_x - 1, box["y"], 2, box["h"], _ink(ink, "axis", "#4A566A")))
    for i, v in enumerate(values):
        row = rows[i] if i < len(rows) else None
        if not row or num(v) is None:
            continue
        h = _js_round(row["h"] * thickness)
        vx = box["x"] + ((v - e.lo) / e.span) * box["w"]
        nodes.append(rect(builtin_min(zero_x, vx), row["y"] + (row["h"] - h) / 2, abs(vx - zero_x), h,
                          _ink(ink, "attention", "#F07A5A") if i == accent
                          else _ink(ink, "subject", "#7FD4E8")))
    return {"nodes": nodes, "returns": {"zeroX": r1(zero_x), "lo": e.lo, "hi": e.hi}}


def spark_bars(box, values, ink, *, gap=0.22) -> dict:
    """`series.sparkBars`: the row's own values as a shape, scaled to the row."""
    if not box or not values:
        return {"nodes": [], "returns": None}
    e = extent(values, zero=True)
    bw = box["w"] / len(values)
    zero_y = box["y"] + box["h"] - ((0 - e.lo) / e.span) * box["h"]
    nodes = []
    for i, v in enumerate(values):
        if num(v) is None:
            continue
        vy = box["y"] + box["h"] - ((v - e.lo) / e.span) * box["h"]
        nodes.append(rect(box["x"] + i * bw + bw * gap / 2, builtin_min(zero_y, vy), bw * (1 - gap),
                          abs(vy - zero_y),
                          _ink(ink, "attention", "#F07A5A") if v < 0 else _ink(ink, "quiet", "#8592A6")))
    return {"nodes": nodes, "returns": {"zeroY": r1(zero_y)}}


def axis_mark(box, value, ink, *, axis="horizontal", weight=8, tone=None) -> dict:
    """`series.axisMark`: one position on an axis, 0 to 1. Off the end is
    clamped to the end and REPORTED — a mark sitting on the end of a range is
    a different claim from one off the end of it.

    `tone` is the ink role the mark's slot publishes (the event calendar's
    first date in attention and the rest in subject, the sector ranking's
    market line in quiet); attention when it publishes none."""
    raw = num(value)
    if not box or raw is None:
        return {"nodes": [], "returns": None}
    v = clamp01(raw)
    t = weight
    fill = (ink.get(tone) if tone else None) or _ink(ink, "attention", "#F07A5A")
    if axis == "vertical":
        y = box["y"] + box["h"] - v * box["h"]
        nodes = [rect(box["x"], y - t / 2, box["w"], t, fill)]
    else:
        x = box["x"] + v * box["w"]
        nodes = [rect(x - t / 2, box["y"], t, box["h"], fill)]
    return {"nodes": nodes, "returns": {"clamped": raw != v, "raw": raw, "value": v,
                                        "overshoot": raw - 1 if raw > 1 else raw if raw < 0 else 0}}


def history_band(box, low, high, ink, *, tone=None, axis="horizontal") -> dict:
    """`series.historyBand`: an extent on an axis, NOT a bar from zero."""
    lo, hi = num(low), num(high)
    if not box or lo is None or hi is None:
        return {"nodes": [], "returns": None}
    a, b = clamp01(builtin_min(lo, hi)), clamp01(builtin_max(lo, hi))
    fill = (ink.get(tone) if tone else None) or _ink(ink, "band", "#1F2634")
    if axis == "vertical":
        nodes = [rect(box["x"], box["y"] + box["h"] - b * box["h"], box["w"], (b - a) * box["h"], fill)]
    else:
        nodes = [rect(box["x"] + a * box["w"], box["y"], (b - a) * box["w"], box["h"], fill)]
    return {"nodes": nodes, "returns": {"low": a, "high": b}}


def line_path(box, values, ink, *, columns=(), min=None, max=None, zero=None,  # noqa: A002
              tone=None, zero_rule=False, accent_last=False, weight=6) -> dict:
    """The line series a chart frame reserves: x READ from each column's
    `anchorX`, or spaced evenly across the region where the plate publishes
    no columns."""
    if not box or not values:
        return {"nodes": [], "returns": None}
    cols = list(columns)
    if len(cols) != len(values):
        if cols:
            return {"nodes": [], "returns": None}
        n = len(values)
        cols = [{"anchorX": box["x"] + (box["w"] / 2 if n == 1 else (i / (n - 1)) * box["w"])}
                for i in range(n)]
    e = extent(values, min=min, max=max, zero=zero)
    y = lambda v: box["y"] + box["h"] - ((v - e.lo) / e.span) * box["h"]  # noqa: E731
    pts = [(cols[i]["anchorX"], y(v)) for i, v in enumerate(values)]
    col = ink.get(tone or "subject") or _ink(ink, "subject", "#7FD4E8")
    nodes = []
    if zero_rule and e.lo < 0 < e.hi:
        nodes.append(rect(box["x"], y(0) - 1, box["w"], 2, _ink(ink, "axis", "#4A566A")))
    nodes.append(path("M" + _pts(pts), {"stroke": col, "stroke-width": weight,
                                        "stroke-linejoin": "round", "stroke-linecap": "round"}))
    for i, p in enumerate(pts):
        last = i == len(pts) - 1
        nodes.append(circle(p[0], p[1], 13 if last and accent_last else 9,
                            _ink(ink, "attention", "#F07A5A") if last and accent_last else col))
    return {"nodes": nodes, "returns": {"lo": e.lo, "hi": e.hi,
                                        "points": [(r1(p[0]), r1(p[1])) for p in pts]}}


def column_bars(columns, values, ink, *, min=None, max=None, accent=None, tone=None) -> dict:  # noqa: A002
    """`series.columnBars`: one bar per `bar-N` column, up from the column's
    OWN `baselineY` — never assumed to be the bottom of the plot."""
    cols = list(columns)
    if not cols or len(cols) != len(values):
        return {"nodes": [], "returns": None}
    e = extent(values, min=min, max=max)
    nodes = []
    for i, v in enumerate(values):
        c = cols[i]
        if not c or num(v) is None:
            continue
        base = c["baselineY"] if c.get("baselineY") is not None else c["y"] + c["h"]
        top = c["y"] + c["h"] - ((v - e.lo) / e.span) * c["h"]
        y0, hgt = builtin_min(base, top), builtin_max(3, abs(base - top))
        fill = (_ink(ink, "attention", "#F07A5A") if i == accent
                else ink.get(tone or "subject") or _ink(ink, "subject", "#7FD4E8"))
        nodes.append(rect(c["x"], y0, c["w"], hgt, fill))
    return {"nodes": nodes, "returns": {"lo": e.lo, "hi": e.hi}}


def split_bar(box, values, ink, *, accent=None, gap=6, thickness=0.5) -> dict:
    """`series.splitBar`: ONE bar and its parts, end to end, as shares of their
    own sum; the accent part in attention, the rest alternating two quiet inks
    so a boundary shows without a stroke."""
    vals = [0.0 if num(v) is None else builtin_max(0.0, v) for v in values]
    total = sum(vals)
    if not box or not total:
        return {"nodes": [], "returns": None}
    h = box["h"] * thickness
    y = box["y"] + (box["h"] - h) / 2
    usable = box["w"] - gap * (len(vals) - 1)
    nodes, parts, x = [], [], box["x"]
    for i, v in enumerate(vals):
        w = usable * v / total
        fill = (_ink(ink, "attention", "#F07A5A") if i == accent
                else _ink(ink, "quiet", "#8592A6") if i % 2 else _ink(ink, "subject", "#7FD4E8"))
        nodes.append(rect(x, y, w, h, fill))
        parts.append((r1(x), r1(x + w)))
        x += w + gap
    return {"nodes": nodes, "returns": {"parts": parts, "sum": total}}


def scatter(box, points, ink, *, accent=None) -> dict:
    """`series.scatter`: one mark per company, on the plate's FIXED scale where
    it publishes one; the accent paints last so a cluster cannot bury it."""
    if not box or not points:
        return {"nodes": [], "returns": None}
    sc = box.get("scale") or {"x": [0, 1], "y": [0, 1]}
    clamped, nodes = [], []
    for i, p in enumerate(points):
        if not p or num(p[0]) is None or num(p[1]) is None:
            continue
        fx = (p[0] - sc["x"][0]) / (sc["x"][1] - sc["x"][0])
        fy = (p[1] - sc["y"][0]) / (sc["y"][1] - sc["y"][0])
        if fx != clamp01(fx) or fy != clamp01(fy):
            clamped.append(i)
        acc = i == accent
        nodes.append(circle(box["x"] + clamp01(fx) * box["w"], box["y"] + box["h"] - clamp01(fy) * box["h"],
                            22 if acc else 14,
                            _ink(ink, "attention", "#F07A5A") if acc else _ink(ink, "subject", "#7FD4E8")))
    if accent is not None and 0 <= accent < len(nodes):
        nodes.append(nodes.pop(accent))
    return {"nodes": nodes, "returns": {"clamped": clamped}}


def spread_fill(box, a, b, ink, *, columns=(), min=None, max=None) -> dict:  # noqa: A002
    """`series.spreadFill`: the area between two series on one plot, under
    both lines — price against cost, where the gap IS the margin."""
    cols = list(columns)
    if not box or not a or len(a) != len(b) or (cols and len(cols) != len(a)):
        return {"nodes": [], "returns": None}
    xs = ([c["anchorX"] for c in cols] if cols
          else [box["x"] + (i / (len(a) - 1)) * box["w"] for i in range(len(a))])
    e = extent(list(a) + list(b), min=min, max=max)
    y = lambda v: box["y"] + box["h"] - ((v - e.lo) / e.span) * box["h"]  # noqa: E731
    up = [(xs[i], y(v)) for i, v in enumerate(a)]
    dn = list(reversed([(xs[i], y(v)) for i, v in enumerate(b)]))
    return {"nodes": [{"tag": "path", "attrs": {"d": "M" + _pts(up + dn) + "Z",
                                                "fill": _ink(ink, "band", "#1F2634")}}],
            "returns": {"lo": e.lo, "hi": e.hi}}


def bridge(box, columns, steps, ink, *, open=0, close=0, open_column=None,  # noqa: A002
           close_column=None, floats=False, min=None, max=None) -> dict:  # noqa: A002
    """`series.bridge`: each step a delta, spanning from the running total to
    the new one — the only reading under which the steps add up to the ends.
    The scale holds the running total, not just the ends; a walk between two
    RATES floats, and then its ends are levels rather than bars from zero."""
    cols = list(columns)
    if not box or len(cols) != len(steps):
        return {"nodes": [], "returns": None}
    o = num(open) or 0.0
    c_ = num(close) or 0.0
    levels, run = [o, c_], o
    for dv in steps:
        if num(dv) is not None:
            run += dv
            levels.append(run)
    hi, lo = builtin_max(levels), builtin_min(levels)
    if floats:
        pad = (hi - lo) * 0.14 or 1
        hi += pad
        lo -= pad
    else:
        hi, lo = builtin_max(hi, 0.0), builtin_min(lo, 0.0)
    if min is not None:
        lo = min
    if max is not None:
        hi = max
    span = (hi - lo) or 1
    y = lambda v: box["y"] + box["h"] - ((v - lo) / span) * box["h"]  # noqa: E731
    nodes, joins = [], []

    def end(col, v, fill):
        if not col:
            return
        if floats:
            nodes.append(rect(col["x"], y(v) - 7, col["w"], 14, fill))
            return
        base = col["baselineY"] if col.get("baselineY") is not None else y(0)
        nodes.append(rect(col["x"], builtin_min(base, y(v)), col["w"], builtin_max(3, abs(base - y(v))), fill))

    axis_ink = _ink(ink, "axis", "#4A566A")
    end(open_column, o, _ink(ink, "quiet", "#8592A6"))
    prev, run = open_column or None, o
    for i, dv in enumerate(steps):
        col = cols[i] if i < len(cols) else None
        if not col or num(dv) is None:
            continue
        if prev and open_column:
            joins.append(rect(prev["x"] + prev["w"], y(run) - 1, col["x"] - (prev["x"] + prev["w"]), 2, axis_ink))
        y0 = y(run)
        run += dv
        y1 = y(run)
        nodes.append(rect(col["x"], builtin_min(y0, y1), col["w"], builtin_max(3, abs(y1 - y0)),
                          _ink(ink, "attention", "#F07A5A") if dv < 0 else _ink(ink, "subject", "#7FD4E8")))
        prev = col
    if prev and close_column:
        joins.append(rect(prev["x"] + prev["w"], y(run) - 1, close_column["x"] - (prev["x"] + prev["w"]), 2,
                          axis_ink))
    end(close_column, c_, _ink(ink, "structure", "#C6D2E0"))
    return {"nodes": joins + nodes,
            "returns": {"closes": r1(run), "expected": c_, "reconciles": abs(run - c_) < 1e-6, "lo": lo, "hi": hi}}


# ── export.js dataLayer ───────────────────────────────────────────────────────

_INDEX = re.compile(r"-(\d+)$")
_NUMBERED = re.compile(r"^(.+)-(\d+)$")


def _pick(slots: dict, pattern: str) -> list[dict]:
    rx = re.compile(pattern)
    names = [k for k in slots if rx.match(k)]
    names.sort(key=lambda k: int(k.rsplit("-", 1)[1]))
    return [slots[k] for k in names]


def data_layer(slots: dict[str, dict], data: dict, ink: dict[str, str]) -> list[dict]:
    """`export.js` `dataLayer`: which renderer a plate gets, from its data.

    `slots` are the plate's boxes as series.js reads them (canvas units, with
    `anchorX`, `baselineY`, `axis`, `scale`); `data` is the kit's data object;
    `ink` is one hour's inks by the kit's names. Ported branch for branch —
    including which branch wins when a plate could take two — so the bot and
    design's review set agree about what a plate with this data looks like.
    """
    SL = slots
    if not data:
        return []
    outs: list[dict] = []
    # A RANGE BEHIND A LINE paints before the series, or it hides the line it
    # frames: a band that publishes `under` (valuation history's own range,
    # the floor under a ratio) goes first, every other band after the marks.
    for k, v in (data.get("bands") or {}).items():
        b = SL.get(k)
        if b and v and b.get("under"):
            outs.append(history_band(b, v[0], v[1], ink, tone=v[2] if len(v) > 2 else None,
                                     axis=b.get("axis") or "horizontal"))
    # The fill between two series and the second series' ink default to what
    # the plate PUBLISHES on its plot area, so a plate drawn without them in
    # the data still matches its own legend.
    pa = SL.get("plot-area") or {}
    data = {**data,
            "spread": data["spread"] if data.get("spread") is not None else pa.get("spreadFill") is True,
            "tone2": data.get("tone2") or pa.get("tone2") or "subject2"}
    bar_cols = _pick(SL, r"^bar-\d+$")
    pair_cols = _pick(SL, r"^pair-\d+$")
    point_cols = _pick(SL, r"^point-\d+$")
    g = data.get
    if g("spread") and g("series") and g("series2") and SL.get("plot-area"):
        outs.append(spread_fill(SL["plot-area"], g("series"), g("series2"), ink, columns=point_cols,
                                min=g("min"), max=g("max")))
    if g("series") and bar_cols:
        outs.append(column_bars(bar_cols, g("series")[:len(bar_cols)], ink, min=g("min"), max=g("max"),
                                accent=g("accent")))
    elif g("series") and SL.get("plot-area"):
        outs.append(line_path(SL["plot-area"], g("series"), ink, columns=point_cols, min=g("min"),
                              max=g("max"), accent_last=bool(g("accentLast")), zero_rule=bool(g("zeroRule")),
                              zero=g("zero")))
    if g("series2") and pair_cols:
        outs.append(column_bars(pair_cols, g("series2")[:len(pair_cols)], ink, min=g("min"), max=g("max"),
                                tone=g("tone2")))
    elif g("series2") and SL.get("plot-area"):
        outs.append(line_path(SL["plot-area"], g("series2"), ink, columns=point_cols, min=g("min"),
                              max=g("max"), tone=g("tone2"), zero_rule=bool(g("zeroRule")),
                              zero=g("zero")))
    if g("split") and SL.get("bars"):
        outs.append(split_bar(SL["bars"], g("split"), ink, accent=g("accent")))
    elif g("bars") and SL.get("bars"):
        outs.append(row_bars(SL["bars"], _pick(SL, r"^band-\d+$"), g("bars"), ink,
                             accent=g("accent") if g("accent") is not None else 0, min=g("min"), max=g("max")))
    if g("steps") and SL.get("bridge"):
        outs.append(bridge(SL["bridge"], _pick(SL, r"^step-\d+$"), g("steps"), ink, open=g("open"),
                           close=g("close"), open_column=SL.get("step-open"), close_column=SL.get("step-close"),
                           floats=bool(g("float"))))
    if g("points") and SL.get("plot-area"):
        outs.append(scatter(SL["plot-area"], g("points"), ink, accent=g("accent")))
    for k, v in (g("marks") or {}).items():
        b = SL.get(k)
        if b:
            outs.append(axis_mark(b, v, ink, axis=b.get("axis") or "horizontal", tone=b.get("ink")))
    # The attention underline a slot publishes (the footnote spotlight).
    for b in SL.values():
        if b.get("underline"):
            outs.append({"nodes": [rect(_js_round(b["x"]), _js_round(b["y"] + b["h"] + 2),
                                        _js_round(b["w"] * 0.8), 5,
                                        _ink(ink, b["underline"], _ink(ink, "attention", "#F07A5A")))]})
    # Said-vs-happened's tie: one attention bar down the middle of the named
    # column's `diverge-N` box.
    for i in g("diverge") or ():
        b = SL.get(f"diverge-{i}")
        if b:
            outs.append({"nodes": [rect(_js_round(b["x"] + b["w"] / 2 - 4), _js_round(b["y"]), 8,
                                        _js_round(b["h"]), _ink(ink, "attention", "#F07A5A"))]})
    # Small multiples: one series per published `panel-N`, all on the plate's
    # ONE min-max unless the data scales a panel of its own, evenly spaced
    # across the panel, in the ink the panel publishes.
    for k, vals in (g("panels") or {}).items():
        b = SL.get(k)
        ps = (g("panelScale") or {}).get(k) or [g("min"), g("max")]
        if b:
            outs.append(line_path(b, vals, ink, min=ps[0], max=ps[1], zero_rule=bool(g("zeroRule")),
                                  accent_last=bool(g("accentLast")), tone=b.get("tone")))
    for k, v in (g("bands") or {}).items():
        b = SL.get(k)
        if b and v and not b.get("under"):
            outs.append(history_band(b, v[0], v[1], ink, tone=v[2] if len(v) > 2 else None,
                                     axis=b.get("axis") or "horizontal"))
    if g("cycle") and SL.get("path"):
        outs.append(cycle_arc(SL["path"], g("cycle"), ink, trough_box=SL.get("trough")))
    if g("spark"):
        for box in _pick(SL, r"^spark-\d+$"):
            outs.append(spark_bars(box, g("spark"), ink))
    if g("low") is not None and SL.get("band"):
        outs.append(history_band(SL["band"], g("low"), g("high"), ink, axis=SL["band"].get("axis")))
    if g("mark") is not None and SL.get("marker"):
        outs.append(axis_mark(SL["marker"], g("mark"), ink, axis=SL["marker"].get("axis")))
    nodes: list[dict] = []
    for o in outs:
        nodes.extend(o.get("nodes") or [])
    # OURS, not export.js's: a numbers sheet's spark column draws EACH ROW's own
    # figures (the note: "the row's own six values as a shape"). The review set
    # passes one sample series to every row because it has one; a real sheet
    # has a series per row, so `data["sparks"]` carries them by slot name.
    for name, vals in (g("sparks") or {}).items():
        box = SL.get(name)
        if box and vals:
            nodes.extend(spark_bars(box, vals, ink)["nodes"])
    # `series.divide`, which the plates name and series.js never wrote: one
    # region, divided end to end from parts that sum to the whole — splitBar's
    # rule, filling the region the plate outlines.
    if g("segments") and SL.get("segments"):
        nodes.extend(split_bar(SL["segments"], g("segments"), ink, thickness=1.0)["nodes"])
    # Small multiples: each tile is a SHAPE on its own vertical scale (the
    # plate's note), so no tile is flattened by another's larger numbers.
    for name, vals in (g("tiles") or {}).items():
        box = SL.get(name)
        if box and len(vals) >= 2:
            nodes.extend(line_path(box, vals, ink, zero=False)["nodes"])
    return nodes


def boxes(plate) -> dict[str, dict]:
    """A plate's slots as series.js reads them: canvas units, published geometry."""
    out = {}
    for name, s in plate.slots.items():
        box = {"x": s.x, "y": s.y, "w": s.w, "h": s.h}
        if s.anchor_x is not None:
            box["anchorX"] = s.anchor_x
        if s.baseline_y is not None:
            box["baselineY"] = s.baseline_y
        if s.axis:
            box["axis"] = s.axis
        if s.scale is not None:
            box["scale"] = s.scale
        # The inks and the draw order a slot publishes for its data (rebuild-39's
        # round five): which ink a mark or a panel is drawn in, the second
        # series' ink and whether the gap between two lines is filled, whether
        # a band sits under the line, and the ink of an underline.
        for key, val in (("ink", s.ink), ("tone", s.tone), ("tone2", s.tone2),
                         ("underline", s.underline)):
            if val:
                box[key] = val
        if s.spread_fill is not None:
            box["spreadFill"] = s.spread_fill
        if s.under:
            box["under"] = True
        out[name] = box
    return out


# ── painting the nodes ────────────────────────────────────────────────────────


def _rgba(hex_: str) -> tuple[int, int, int, int]:
    h = hex_.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255)


_PATH_NUM = re.compile(r"-?\d+(?:\.\d+)?")


def _path_points(d: str, k: float) -> tuple[list[tuple[float, float]], bool]:
    """`M x,y L x,y … [Z]` — the only path shape series.js emits."""
    closed = d.rstrip().endswith("Z")
    nums = [float(v) for v in _PATH_NUM.findall(d)]
    return [(nums[i] * k, nums[i + 1] * k) for i in range(0, len(nums) - 1, 2)], closed


def paint(img, nodes: list[dict], scale: float = 1.0, *, supersample: int | None = None) -> None:
    """Draw series nodes onto `img` (delivered pixels), in order, flat.

    Nodes are in canvas units; `scale` is the plate's export scale. A small
    image is drawn at 2x on a transparent layer and brought down, so an edge
    that is anti-aliased in the SVG the kit reviews is anti-aliased here too.
    A delivered 4K plate is not: it is brought down to the output size after
    this anyway, which does the same job without a 130 MB layer per frame.
    """
    from PIL import Image, ImageDraw

    if not nodes:
        return
    if supersample is None:
        supersample = 2 if builtin_max(img.size) < 2000 else 1
    ss = builtin_max(int(supersample), 1)
    k = scale * ss
    layer = Image.new("RGBA", (img.width * ss, img.height * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for n in nodes:
        a = n["attrs"]
        if n["tag"] == "rect":
            x, y = a["x"] * k, a["y"] * k
            w, h = a["width"] * k, a["height"] * k
            if w > 0 and h > 0:
                d.rectangle([x, y, x + w - 1, y + h - 1], fill=_rgba(a["fill"]))
        elif n["tag"] == "circle":
            cx, cy, r = a["cx"] * k, a["cy"] * k, a["r"] * k
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=_rgba(a["fill"]))
        elif n["tag"] == "path":
            pts, closed = _path_points(a["d"], k)
            if len(pts) < 2:
                continue
            if closed or a.get("fill", "none") != "none":
                d.polygon(pts, fill=_rgba(a["fill"]))
            if a.get("stroke"):
                w = max(int(round(float(a.get("stroke-width", 1)) * k)), 1)
                d.line(pts, fill=_rgba(a["stroke"]), width=w, joint="curve")
                # Round caps: PIL draws butt ends, series.js asks for round.
                for px, py in (pts[0], pts[-1]):
                    d.ellipse([px - w / 2, py - w / 2, px + w / 2, py + w / 2], fill=_rgba(a["stroke"]))
    if ss > 1:
        layer = layer.resize(img.size, Image.LANCZOS)
    if img.mode != "RGBA":
        base = img.convert("RGBA")
        base.alpha_composite(layer)
        img.paste(base.convert(img.mode))
    else:
        img.alpha_composite(layer)


# ── what the writer wrote, as the kit's data object ───────────────────────────

_MINUS = str.maketrans({"−": "-", "–": "-", "—": "-"})
_FIGURE = re.compile(r"^\(?([+-]?)\$?\s*(\d+(?:\.\d+)?|\.\d+)\s*([a-z%×]*)\)?$")
_MULT = {"k": 1e3, "m": 1e6, "mm": 1e6, "mn": 1e6, "b": 1e9, "bn": 1e9, "t": 1e12, "tn": 1e12}
_PLAIN = {"", "%", "x", "×", "pt", "pts", "pp", "bp", "bps", "d", "days", "y", "yr", "yrs", "years",
          "mo", "months", "q", "st", "nd", "rd", "th"}


def figure(raw) -> float | None:
    """A figure as it is PRINTED on a plate — `$612m`, `+1.6pt`, `−$18m`,
    `15.2%`, `1,180`, `4.1×`, `18th` — as a number. None when it is not one.

    Scale words multiply (`$1.2bn` and `$300m` land on one scale); unit words do
    not. An empty cell is None, and stays None: it means NO DATA.
    """
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return float(raw)
    text = str(raw or "").strip().translate(_MINUS).replace(",", "").replace(" ", "")
    if not text:
        return None
    negative = text.startswith("(") and text.endswith(")")
    m = _FIGURE.match(text.lower())
    if not m:
        return None
    sign, digits, unit = m.groups()
    if unit in _MULT:
        mult = _MULT[unit]
    elif unit in _PLAIN:
        mult = 1.0
    else:
        return None
    v = float(digits) * mult
    return -v if (sign == "-" or negative) else v


def decimals(raw) -> int:
    """How many decimal places a printed figure carries — its rounding."""
    m = re.search(r"\d+\.(\d+)", str(raw or ""))
    return len(m.group(1)) if m else 0


def rounding(raw) -> float:
    """Half the last printed digit, in the figure's own units: `$4.2bn` may be
    anything from 4.15 to 4.25 billion, so ±50 million, not ±0.05."""
    text = str(raw or "").strip().translate(_MINUS).replace(",", "").replace(" ", "")
    m = _FIGURE.match(text.lower())
    mult = _MULT.get(m.group(3), 1.0) if m else 1.0
    return 0.5 * 10 ** -decimals(raw) * mult


def figures(raw: str) -> list[float | None]:
    """`a, b, c` → figures. An empty entry stays None (NO DATA)."""
    return [figure(p) for p in str(raw or "").split(",")]


def _family(plate, stem: str) -> list[str]:
    rx = re.compile(rf"^{re.escape(stem)}-(\d+)$")
    got = [(int(m.group(1)), n) for n in plate.slots if (m := rx.match(n))]
    return [n for _, n in sorted(got)]


def _written(values: dict, names: list[str]) -> list[str] | None:
    """The values written to a family of slots, in order; None if none were."""
    got = [str(values.get(n) or "").strip() for n in names]
    return got if any(got) else None


def _as_series(texts: list[str]) -> list[float | None]:
    return [figure(t) for t in texts]


def _columns(plate, stem: str) -> list[str]:
    """A numbered family as COLUMNS a series is drawn into. A ranking's `bar-N`
    are rails, bands with extents of their own (sector-ranking, peer-rank), and
    a series drawn into them stands columns on top of the rails; the kit's own
    sample draws no series there."""
    fam = _family(plate, stem)
    return [] if fam and all(plate.slots[n].role in ("band", "marker") for n in fam) else fam


def _parallel_shapes(plate, names: list[str]) -> list[str]:
    """The numbered band and marker families that run beside a printed family,
    one shape per printed figure: guidance's `guide-N` and `actual-N` beside
    its `value-N`, a ranking's `bar-N` rails, a combined ratio's two stacked
    parts. Where one does, the printed figures are THOSE shapes' figures, and
    no line is drawn through them: the kit's own sample nulls the series on
    every such plate."""
    if not names:
        return []
    stems = sorted({m.group(1) for k in plate.slots if (m := _NUMBERED.match(k))})
    out = []
    for stem in stems:
        fam = _family(plate, stem)
        if fam != names and len(fam) == len(names) and all(
                plate.slots[n].region and plate.slots[n].role in ("band", "marker") for n in fam):
            out.append(stem)
    return out


def _printed_marks(plate) -> dict[str, str]:
    """{mark: the printed figure that places it}, for a numbered marker family
    beside `value-N`: guidance's `actual-N`, each quarter's reported figure
    printed under it. The mark stands where that figure is, so the printed
    figure places it, as `growth-value-N` places `growth-N`."""
    values = _family(plate, "value")
    out: dict[str, str] = {}
    for stem in _parallel_shapes(plate, values):
        fam = _family(plate, stem)
        if all(plate.slots[n].role == "marker" and plate.slots[n].scale == "plot-area" for n in fam):
            out.update(zip(fam, values))
    return out


def _mixed_units(plate, v: dict, printed_marks: dict) -> str | None:
    """Why the plot's figures cannot share one scale, or None. The printed
    quarters read `$186m` and a range written `180, 195` beside them is a
    hundred-million times smaller: on one scale every bar lies flat on the
    floor. Written as printed (`$180m, $195m`), they agree."""
    marks = [figure(v.get(src)) for src in printed_marks.values()]
    marks = [abs(x) for x in marks if x]
    bands = [abs(figure(p.strip()) or 0) for n, sl in plate.slots.items()
             if sl.scale == "plot-area" and sl.role == "band" and v.get(n)
             for p in str(v[n]).split(",")[:2]]
    bands = [x for x in bands if x]
    if not marks or not bands:
        return None
    ratio = sorted(bands)[len(bands) // 2] / sorted(marks)[len(marks) // 2]
    if 1 / 20 <= ratio <= 20:
        return None
    stem = next(iter(printed_marks.values())).rsplit("-", 1)[0]
    return (f"the ranges and the printed {stem}-N are not in the same units (a range reads "
            f"{ratio:.3g} times the figures printed beside it): write each range the way the "
            f"figures are printed")


def _plot_figures(plate, v: dict, printed_marks: dict) -> list[float]:
    """The figures of every band and mark the plate publishes on the PLOT'S
    scale (`scale: "plot-area"`): a multiple's own range and average, each
    quarter's guided range and reported figure. They are on the plot's one
    min-max with the line, so the scale is worked out over them too. A figure
    that does not read is skipped here and reported where it is placed."""
    out: list[float] = []
    for name, slot in plate.slots.items():
        if slot.scale != "plot-area" or not slot.region:
            continue
        raw = str(v.get(name) or "") or str(v.get(printed_marks.get(name, ""), "") or "")
        if slot.role == "band":
            pair = [figure(p.strip()) for p in raw.split(",")[:2]]
            if len(pair) == 2 and None not in pair:
                out += pair
        elif slot.role == "marker" and figure(raw) is not None:
            out.append(figure(raw))
    return out


def _tight(lo: float, hi: float) -> tuple[float, float]:
    """A scale for figures compared only with EACH OTHER and printed on no
    axis — guided ranges against what was reported, the panels of a small
    multiple, a driver beside its effect: their own extent with a tenth of it
    to spare at each end. Zero is not forced in. Eight quarters of guidance
    between $180m and $230m on a scale from zero are eight identical bars at
    the top of the plot, and design's own samples draw them tight."""
    span = hi - lo if hi > lo else (abs(hi) or 1.0)
    return lo - span * 0.1, hi + span * 0.1


def _note(plate, name: str) -> str:
    s = plate.slots.get(name)
    return (s.note or "").lower() if s is not None else ""


def _axis_scale(plate, values: dict, box_name: str,
                plot: tuple[float, float] | None = None) -> tuple[float, float] | None:
    """The scale a mark or an extent is written on, as the PLATE states it.

    A slot published on the plot's own scale (`scale: "plot-area"`) is on
    `plot`, the one min-max the line and everything else on the plot share.
    Otherwise, first what is printed on the axis the writer filled —
    `axis-low`/`axis-high`, or the first and last `tick-N` — because those
    labels are on screen and a mark that disagrees with them is wrong in front
    of the viewer. Then the slot's own published `scale`. None: the value is
    already a 0-1 position.
    """
    own = plate.slots.get(box_name)
    if own is not None and own.scale == "plot-area" and plot is not None:
        return plot
    lo = figure(values.get("axis-low"))
    hi = figure(values.get("axis-high"))
    if lo is not None and hi is not None and hi != lo:
        return lo, hi
    tick_slots = _family(plate, "tick")
    ticks = [figure(values.get(n)) for n in tick_slots]
    ticks = [t for t in ticks if t is not None]
    if len(ticks) >= 2 and ticks[-1] != ticks[0]:
        return ticks[0], ticks[-1]
    # A PLATE THAT PRINTS TICKS IS READ BY ITS TICKS. rebuild-21's band plates
    # all publish `scale: [0, 180]` while eight of the ten say in their own
    # note that the scale is something else (reserve life is 0-20 years), so
    # on a plate with a tick row the field is not trusted: an unlabelled tick
    # row is a scale nobody can read, and the writer is asked to label it.
    s = plate.slots.get(box_name)
    if not tick_slots and s is not None and isinstance(s.scale, list) and len(s.scale) == 2:
        return float(s.scale[0]), float(s.scale[1])
    return None


def _position(val: float, scale, name: str, out: "PlateData") -> float | None:
    """A written figure as a 0-1 position on its rail, or None with a problem.

    Off the ends is a READING — the kit clamps it to the end and marks it — so
    it passes. What does not pass is a figure that can only be a unit mistake:
    `12` (per cent) on a rail whose axis prints no scale, read as twelve times
    the rail's length.
    """
    if scale is not None:
        return (val - scale[0]) / (scale[1] - scale[0])
    if -0.5 <= val <= 1.5:
        return val
    out.problems.append(
        f"{name}= is {val:g}, and nothing on this plate's axis prints a scale to place it on, "
        f"so it is read as a 0-1 position. Label the axis (axis-low and axis-high, or the ticks) "
        f"or write the position")
    return None


def _round_out(v: float) -> float:
    """`v` rounded UP to a fifth of its own order of magnitude: 6.71 → 6.8,
    308 → 320, 4,840 → 5,000."""
    if v <= 0:
        return 0.0
    step = 10 ** math.floor(math.log10(v)) / 5
    return math.ceil(v / step - 1e-9) * step


def _headroom(lo: float, hi: float) -> tuple[float, float]:
    """A plot's scale when nothing on the plate states one: the data and zero,
    with a tenth to spare at the open end(s), so the peak is a point on the
    plot rather than a mark on its top edge."""
    return (-_round_out(-lo * 1.1) if lo < 0 else lo,
            _round_out(hi * 1.1) if hi > 0 else hi)


def _kit_ceiling(v: float) -> float:
    """The top of a payback plot as design's own sample sets it: 15% over the
    higher of the level and the line, up to the next ten
    (sector-copy.js `payback`). Below ten that rounds everything to one flat
    line at the bottom, so small figures round out instead."""
    top = v * 1.15
    return math.ceil(top / 10) * 10 if top >= 10 else _round_out(top)


@dataclass
class PlateData:
    """The kit's data object for one plate, and what stopped any of it."""

    data: dict = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


# Keys a `[PLATE]` tag may carry that are data rather than a slot: the kit's own
# dataLayer vocabulary. Each is only offered on a plate that can draw it.
DATA_KEYS = ("series", "series2", "open", "steps", "close", "points", "split", "accent")


def data_keys(plate) -> list[str]:
    """The data keys this plate takes, from what it declares."""
    s = plate.slots
    has = lambda stem: bool(_family(plate, stem))           # noqa: E731
    keys: list[str] = []
    columns = bool(_columns(plate, "bar")) or has("point") or "plot-area" in s
    # A plot of bands and marks beside the figures it prints draws no line.
    if _parallel_shapes(plate, _family(plate, "value")):
        columns = False
    if columns and not _scatter(plate):
        keys.append("series")
        if has("pair") or _two_lines(plate):
            keys.append("series2")
    if "bridge" in s:
        keys += ["open", "steps", "close"]
    if _scatter(plate):
        keys += ["points", "accent"]
    if "bars" in s and _split(plate):
        keys.append("split")
    # A rail plate draws its bars from the shares it prints and takes no series,
    # but it still has one row the script is about (rowBars' `accent`, the first
    # row unless the tag says otherwise).
    if (keys or "bars" in s) and "accent" not in keys:
        keys.append("accent")
    return keys


def _span(names: list[str]) -> str:
    """`value-1…6` for a numbered family, or the one name."""
    if not names:
        return ""
    stem = names[0].rsplit("-", 1)[0]
    return names[0] if len(names) == 1 else f"{stem}-1…{len(names)}"


def data_menu(plate) -> str:
    """What this plate DRAWS and where the drawing reads it from, as the one
    line the writer's catalogue shows under its slots. "" for a plate that
    draws nothing.

    It mirrors :func:`plate_data` route for route: printed figures first,
    because a drawing read off the type beside it cannot disagree with it;
    named keys only where the plate prints none.
    """
    s = plate.slots
    fam = lambda stem: _family(plate, stem)             # noqa: E731
    keys = data_keys(plate)
    bar_cols, pair_cols, point_cols = _columns(plate, "bar"), fam("pair"), fam("point")
    parts: list[str] = []

    if "series" in keys:
        n = len(bar_cols or point_cols)
        printed1, printed2 = _printed_series(plate)
        if printed1 and printed2:
            parts.append(f"{_span(printed1)} and {_span(printed2)} are the two series, drawn "
                         f"as printed on one scale")
        elif printed1:
            parts.append(f"{_span(printed1)} are the series, drawn as printed")
        else:
            parts.append(f"series=<{n} figures>" if n else "series=<figures, oldest first>")
        if "series2" in keys and not printed2:
            m = len(pair_cols or point_cols) or n
            parts.append(f"series2=<{m} figures>, on the same scale")
    if "bridge" in s:
        k = len(fam("step"))
        values = fam("value")
        if len(values) == k + 2 and ("step-open" in s or "step-close" in s):
            parts.append(f"{_span(values)} are the walk, drawn as printed: the opening level, "
                         f"{k} steps, the close; open plus the steps must reach the close")
        elif "total" in s and "remainder" in s:
            parts.append(f"steps=<{k} figures> between the total and the remainder it prints; "
                         f"the total plus the steps must reach the remainder")
        else:
            parts.append(f"open= | steps=<{k} figures> | close=; open plus the steps must reach "
                         f"the close")
    if "bars" in s:
        shares, moves, amounts = fam("share"), fam("move"), fam("amount")
        if _split(plate):
            src = amounts or shares
            parts.append((f"{_span(src)} divide the bar" if src else "split=<parts>")
                         + (f"; {_span(shares)} must reach 100% and match them" if shares and amounts
                            else "; shares must reach 100%" if shares else ""))
        elif shares or moves:
            parts.append(f"{_span(shares or moves)} draw the bars, on one scale")
        else:
            parts.append("bars=<one figure per row>")
    if "segments" in s:
        parts.append(f"{_span(fam('value'))} divide the region; printed as shares they must "
                     f"reach 100%")
    if _scatter(plate):
        parts.append("points=<x:y per company, comma-separated>")

    positions, extents = [], []
    for name, slot in s.items():
        if not slot.region or slot.overlay or slot.renderer.endswith("rangeMark"):
            continue
        if slot.role == "marker":
            positions.append(name)
        elif slot.role == "band":
            extents.append(name)
    growth = [n for n in positions if n.startswith("growth-")]
    if growth:
        parts.append(f"{_span(fam('growth-value'))} place the growth marks on the "
                     f"axis-low…axis-high rail")
    printed_marks = _printed_marks(plate)
    if printed_marks:
        stems = sorted({n.rsplit("-", 1)[0] for n in printed_marks})
        parts.append(f"{_span(fam('value'))} place the {' and '.join(stems)} marks, as printed")
    on_plot = "on the plot's one scale, in the figures' own units"
    for name in sorted(n for n in positions if n not in growth and not re.match(r".*-\d+$", n)):
        on = (on_plot if s[name].scale == "plot-area"
              else "on the line's scale" if s[name].axis == "vertical" else "on the scale the axis prints")
        parts.append(f"{name}=<one figure, {on}>")
    numbered = sorted({n.rsplit("-", 1)[0] for n in positions
                       if n not in growth and n not in printed_marks and re.match(r".*-\d+$", n)})
    for stem in numbered:
        parts.append(f"{_span(fam(stem))}=<one figure each, on the scale the plate prints>")
    for stem in sorted({re.sub(r"-\d+$", "", n) for n in extents}):
        names = fam(stem) if re.match(r".*-\d+$", next(n for n in extents if n.startswith(stem))) else [stem]
        label = _span(names) if len(names) > 1 else names[0]
        where = (on_plot if all(s[n].scale == "plot-area" for n in names)
                 else f"on the {'ticks' if fam('tick') else 'axis'}")
        parts.append(f"{label}=<start,end[,tone]> {where}")
    panels = fam("panel")
    if panels:
        own = all(s[n].scale == "own" for n in panels)
        parts.append(f"{_span(panels)}=<figures, oldest first> per panel, "
                     + ("each on its own scale" if own else "all on one shared scale")
                     + "; each line's last figure is the one printed beside it")
    if any(re.match(r"^series-\d+$", n) and sl.region for n, sl in s.items()):
        parts.append(f"{_span([n for n in sorted(s) if re.match(r'^series-[0-9]+$', n)])}"
                     f"=<figures> per tile, each on its own scale")
    if "path" in s and s["path"].region:
        parts.append("path=<figures, first to last>")
    if fam("spark"):
        parts.append("each row's cell-N-1… draw its spark")
    if "accent" in keys:
        lines = "series" in keys and not bar_cols
        parts.append("accent=last marks the latest point" if lines
                     else "accent=N puts one in attention (the first, unless you say)")
    return "; ".join(parts)


def _printed_series(plate) -> tuple[list[str], list[str]]:
    """The families of figures a plate PRINTS for the series it draws.

    A paired chart prints each series as a row of figures directly under its
    keyed row label (`row-1` BOUGHT BACK, then `spend-1…6`), and the row names
    are the plate's own (`spend`/`sbc`, `capex`/`da`, `sa`/`sb`), so they are
    found where they sit rather than by name. A single-series chart prints
    `value-N`, one per column.
    """
    s = plate.slots
    bar_cols = _columns(plate, "bar")
    columns = bar_cols or _family(plate, "point")
    if columns and "row-1" in s and "row-2" in s:
        rows: dict[str, set] = {}
        for name, sl in s.items():
            m = re.match(r"^(.+)-(\d+)$", name)
            if m and sl.role == "value":
                rows.setdefault(m.group(1), set()).add(sl.y)
        under = sorted((next(iter(ys)), stem) for stem, ys in rows.items()
                       if len(ys) == 1 and len(_family(plate, stem)) == len(columns))
        first = next((stem for y, stem in under if y > s["row-1"].y), None)
        second = next((stem for y, stem in under if y > s["row-2"].y), None)
        if first and second and first != second:
            return _family(plate, first), _family(plate, second)
    if "plot-area" in s or bar_cols:
        values = _family(plate, "value")
        if values and (not columns or len(values) == len(columns)) \
                and not _parallel_shapes(plate, values):
            return values, []
    return [], []


def _scatter(plate) -> bool:
    s = plate.slots.get("plot-area")
    note = _note(plate, "plot-area")
    return s is not None and (isinstance(s.scale, dict) and "x" in s.scale
                              or "scatter" in note or "one mark per" in note)


def _two_lines(plate) -> bool:
    note = _note(plate, "plot-area")
    return "two linepaths" in note or "second in" in note or "spreadfill" in note


def _split(plate) -> bool:
    return "splitbar" in _note(plate, "bars") or "divided" in _note(plate, "bars")


# The kit's ink name for each registry palette role — KIT_INK read backwards.
_KIT_NAME = {ours: kit for kit, ours in KIT_INK.items()}

# THE GAP IS NOT ALWAYS A QUANTITY. Every two-line plate built on
# price-cost-spread inherits its plot note, "spreadFill between them", but where
# the two lines are the PARTS of one total (price and volume add to organic
# growth) the area between them measures nothing, and the plate's own caution
# says so: "the gap is not filled", "Do not fill it". The caution wins.
_NOT_FILLED = re.compile(r"\b(?:not|no|never)\s+(?:be\s+)?fill(?:ed)?\b", re.IGNORECASE)


def _unfilled(plate) -> bool:
    return bool(_NOT_FILLED.search(getattr(plate, "caution", "") or ""))


def plate_data(plate, values: dict[str, str]) -> PlateData:
    """The kit data object for `plate`, from what the writer bound to it.

    Where the plate PRINTS the figures it draws, those printed figures are the
    data: a walk's `value-N`, a chart's `value-N`, a rail's `share-N` and
    `growth-value-N`, a peer strip's `move-N`, a sheet's row of cells. Where it
    prints none, the tag names them: `series=`, `series2=`, `steps=`,
    `points=`, `band-N=start,end`, `cac-line=`. A figure is never computed.
    """
    out = PlateData()
    d = out.data
    s = plate.slots
    v = {k: str(val) for k, val in (values or {}).items()}

    def nums(key: str, raw: str) -> list[float] | None:
        got = figures(raw)
        if any(x is None for x in got):
            bad = [p.strip() for p, x in zip(raw.split(","), got) if x is None]
            out.problems.append(f"{key}= has {', '.join(repr(b) for b in bad)}, which "
                                f"{'is' if len(bad) == 1 else 'are'} not a figure")
            return None
        return got

    bar_cols, pair_cols, point_cols = _columns(plate, "bar"), _family(plate, "pair"), _family(plate, "point")
    columns = bar_cols or point_cols
    # A plot of bands and marks beside its printed figures draws no line.
    if _parallel_shapes(plate, _family(plate, "value")):
        columns = []

    # ── the first series ─────────────────────────────────────────────────
    # WHERE THE PLATE PRINTS ITS SERIES, THE PRINTED FIGURES ARE WHAT IS DRAWN:
    # a bar chart's `value-N`, a paired chart's two rows of figures under its
    # keyed row labels. A `series=` beside them is a second copy that can
    # disagree with the type on screen, so it is not the one drawn.
    printed1, printed2 = _printed_series(plate)
    if printed1 and _written(v, printed1):
        d["series"] = _as_series(_written(v, printed1))
        if "series" in v:
            out.warnings.append(f"series= is not drawn: the plate draws the {_span(printed1)} "
                                f"it prints")
    elif "series" in v and not _scatter(plate):
        d["series"] = nums("series", v["series"])
    elif columns and _written(v, columns):
        d["series"] = _as_series(_written(v, columns))
    elif "plot-area" in s and "," in v.get("plot-area", ""):
        d["series"] = nums("plot-area", v["plot-area"])
    if d.get("series") is None:
        d.pop("series", None)
    if "series" in d and columns and len(d["series"]) != len(columns):
        out.problems.append(f"the series has {len(d['series'])} figures and the plate draws "
                            f"{len(columns)} {'columns' if bar_cols else 'points'}")
        d.pop("series")

    # ── the second series ────────────────────────────────────────────────
    if printed2 and _written(v, printed2):
        d["series2"] = _as_series(_written(v, printed2))
        if "series2" in v:
            out.warnings.append(f"series2= is not drawn: the plate draws the {_span(printed2)} "
                                f"it prints")
    elif "series2" in v:
        d["series2"] = nums("series2", v["series2"])
    elif pair_cols and _written(v, pair_cols):
        d["series2"] = _as_series(_written(v, pair_cols))
    if d.get("series2") is None:
        d.pop("series2", None)
    want2 = pair_cols or (point_cols if _two_lines(plate) else [])
    if "series2" in d and want2 and len(d["series2"]) != len(want2):
        out.problems.append(f"series2 has {len(d['series2'])} figures and the plate draws {len(want2)}")
        d.pop("series2")
    # The second series is drawn in the ink its legend keys it in. The kit's
    # default is subject2, and book-to-bill and its sector copies key it in
    # quiet instead: drawn in subject2 there, revenue is a colour the legend
    # beside it does not show.
    key2 = next((plate.keys[k] for k in ("legend-2", "row-2") if k in getattr(plate, "keys", {})), None)
    if "series2" in d and key2 in _KIT_NAME:
        d["tone2"] = _KIT_NAME[key2]
    elif "series2" in d and not pair_cols:
        d["tone2"] = "subject2"
    if "series2" in d and not pair_cols and "spreadfill" in _note(plate, "plot-area") \
            and not _unfilled(plate):
        d["spread"] = True

    # THE SCALE IS WHAT THE PLATE STATES. A plot drawn to a fixed scale says so
    # on the slot — `scale: {"y": [0, 100]}` is a coverage chart whose top edge
    # is the ceiling the plate draws. Otherwise, where the writer labelled the
    # y axis, those labels are the scale: a path fitted to its own range lands
    # wherever it likes against gridlines that claim otherwise.
    pa = s.get("plot-area")
    if pa is not None and isinstance(pa.scale, dict) and "y" in pa.scale and not _scatter(plate):
        d["min"], d["max"] = float(pa.scale["y"][0]), float(pa.scale["y"][1])
    elif (dom := axis_domain(plate, v)) is not None:
        d["min"], d["max"] = dom
    # ONE SCALE FOR EVERYTHING ON ONE PLOT. series.js scales each call to its
    # own data unless it is handed min and max, and dataLayer hands both series
    # the SAME pair for a reason it states: "two scales on one plot is how a
    # viewer reads a correlation the data does not contain". With no scale on
    # the plate, the pair is worked out here, over both series — and over a
    # payback's level, which is drawn on the same axis as its line.
    both = [x for x in (d.get("series") or []) + (d.get("series2") or []) if x is not None]
    # What else is drawn on the plot's own scale — a multiple's range and
    # average, each quarter's guided range and reported figure — is on the same
    # min-max, so it counts toward it. With no line on the plot those figures
    # are only compared with each other, and the scale is their own extent.
    printed_marks = _printed_marks(plate)
    plotted = _plot_figures(plate, v, printed_marks)
    if (why := _mixed_units(plate, v, printed_marks)) is not None:
        out.problems.append(why)
    if "min" not in d and (both or plotted) and not _scatter(plate):
        level = next((figure(v[n]) for n, sl in s.items()
                      if sl.region and sl.role == "marker" and sl.axis == "vertical"
                      and sl.scale != "plot-area"
                      and n in v and figure(v[n]) is not None), None)
        if level is not None and both:
            d["min"] = builtin_min(0.0, builtin_min(both + [level]))
            d["max"] = _kit_ceiling(builtin_max(both + [level]))
        elif both:
            d["min"], d["max"] = _headroom(builtin_min(0.0, builtin_min(both + plotted)),
                                           builtin_max(0.0, builtin_max(both + plotted)))
        else:
            d["min"], d["max"] = _tight(builtin_min(plotted), builtin_max(plotted))
    if any(x < 0 for x in both):
        d["zeroRule"] = True

    # ── a bridge ─────────────────────────────────────────────────────────
    if "bridge" in s:
        _bridge_data(plate, v, out, nums)

    # ── row bars and a split ─────────────────────────────────────────────
    if "bars" in s:
        # The same rule as a series: a row of figures the plate prints is what
        # its bars draw, and a `split=` or `bars=` beside it is not.
        if _split(plate):
            # Amounts before shares where the plate prints both: they are the
            # finer figures, and what the kit's own sample divides the bar by.
            shares = _family(plate, "share")
            family = next((f for f in (_family(plate, "amount"), shares) if _written(v, f)), [])
            if family:
                d["split"] = _as_series(_written(v, family))
                if "split" in v:
                    out.warnings.append(f"split= is not drawn: the plate draws the {_span(family)} "
                                        f"it prints")
            elif "split" in v:
                d["split"] = nums("split", v["split"])
            if d.get("split") is None:
                d.pop("split", None)
            _check_shares(_written(v, shares), d.get("split"), out)
        else:
            raw = v.get("bars", "")
            family = next((f for f in (_family(plate, "share"), _family(plate, "move"))
                           if _written(v, f)), [])
            if family:
                d["bars"] = _as_series(_written(v, family))
                if "," in raw:
                    out.warnings.append(f"bars= is not drawn: the plate draws the {_span(family)} "
                                        f"it prints")
            elif "," in raw:
                d["bars"] = nums("bars", raw)
            if d.get("bars") is None:
                d.pop("bars", None)
            if "bars" in d and _family(plate, "share"):
                # Shares are drawn from the LEFT EDGE (the note), on design's
                # own scale for them: the next ten above the largest, plus ten
                # (sector-copy.js `rails`).
                top = builtin_max([x for x in d["bars"] if x is not None] or [0])
                d["min"], d["max"] = 0.0, math.ceil(top / 10) * 10 + 10

    # ── single positions and extents on their own rails ──────────────────
    marks: dict[str, float] = {}
    bands: dict[str, list] = {}
    for name, slot in s.items():
        if not (slot.region and slot.role in ("marker", "band")) or slot.overlay:
            continue
        if slot.renderer.endswith("rangeMark"):
            continue                        # a {t, median} pair: chart.py draws those
        written = v.get(name, "")
        source = name
        if not written and slot.role == "marker":
            src = (name.replace("growth-", "growth-value-") if name.startswith("growth-")
                   else printed_marks.get(name))
            if src and v.get(src):
                written, source = v[src], src
        if not written:
            continue
        if slot.role == "marker":
            val = figure(written)
            if val is None:
                out.problems.append(f"{source}= {written!r} is not a figure")
                continue
            pos = _position(val, _mark_scale(plate, v, name, d), source, out)
            if pos is not None:
                marks[name] = pos
        else:
            parts = [p.strip() for p in written.split(",")]
            pair = [figure(p) for p in parts[:2]]
            if len(parts) < 2 or any(x is None for x in pair):
                out.problems.append(f"{name}= takes `start, end` and has {written!r}")
                continue
            plot = (d["min"], d["max"]) if d.get("min") is not None and d.get("max") is not None else None
            scale = _axis_scale(plate, v, name, plot=plot)
            got = [_position(x, scale, name, out) for x in pair]
            if any(x is None for x in got):
                continue
            bands[name] = got + ([parts[2]] if len(parts) > 2 and parts[2] in KIT_INK else [])
    if marks:
        d["marks"] = marks
    if bands:
        d["bands"] = bands
    # `band` + `marker` (implied, roic-vs-wacc): the kit's low/high/mark keys.
    if "band" in bands and "band" in s:
        low, high = bands.pop("band")[:2]
        d["low"], d["high"] = low, high
        if not bands:
            d.pop("bands", None)
    if "marker" in marks and "marker" in s and not _family(plate, "marker"):
        d["mark"] = marks.pop("marker")
        if not marks:
            d.pop("marks", None)

    # ── scatter ──────────────────────────────────────────────────────────
    if _scatter(plate) and "points" in v:
        pts = []
        for part in v["points"].split(","):
            xy = [figure(p) for p in part.split(":")]
            if len(xy) != 2 or any(x is None for x in xy):
                out.problems.append(f"points= takes `x:y` per company and has {part.strip()!r}")
                pts = []
                break
            pts.append(xy)
        if pts:
            d["points"] = pts
            acc = figure(v.get("accent", "")) if v.get("accent") else None
            d["accent"] = int(acc) - 1 if acc is not None else 0

    # ── a divided bar (series.divide): the parts the plate prints ────────
    # "ONE region, divided by the renderer from values that sum to the whole
    # … a part-of-a-whole that does not add up is the one thing this plate
    # must never show." Printed as shares, they have to reach 100.
    if "segments" in s:
        raw = v.get("segments", "")
        printed = _written(v, _family(plate, "value"))
        texts = printed or ([p.strip() for p in raw.split(",")] if "," in raw else None)
        if printed and "," in raw:
            out.warnings.append(f"segments= is not drawn: the plate draws the "
                                f"{_span(_family(plate, 'value'))} it prints")
        if texts:
            parts = _as_series(texts)
            if any(x is None for x in parts):
                out.problems.append("the segments are not all figures: "
                                    + ", ".join(repr(t) for t, x in zip(texts, parts) if x is None))
            else:
                if all(t.endswith("%") for t in texts):
                    tol = sum(rounding(t) for t in texts) + 1e-9
                    if abs(sum(parts) - 100) > tol:
                        out.problems.append(f"the parts add up to {sum(parts):g}%, not 100%")
                d["segments"] = parts

    # ── small multiples: each tile its own line, on its own scale ────────
    # Numbered tiles only: a slot named plain `series` is the plot's own line
    # (macro-series), which `series=` already draws in the plot area.
    tiles = {}
    for name, slot in s.items():
        if slot.region and slot.role == "series" and re.match(r"^series-\d+$", name) \
                and "," in v.get(name, ""):
            got = nums(name, v[name])
            if got:
                tiles[name] = got
    if tiles:
        d["tiles"] = tiles

    # ── small multiples, and a driver beside its effect (rebuild-39) ─────
    # One line per `panel-N`, the figures the tag gives it, oldest first. Each
    # panel says which scale it is drawn on: `shared`, every panel on the
    # plate's ONE min-max ("never rescale a panel to itself"), or `own`, its
    # own, handed to the kit as `panelScale` ("never share a plot with the
    # other panel"). Neither prints an axis, so a scale is the figures' own
    # extent. Each line's last point is in attention: it is the figure the
    # panel prints beside it.
    panels = {}
    for name in _family(plate, "panel"):
        if "," in v.get(name, ""):
            got = nums(name, v[name])
            if got:
                panels[name] = got
    if panels:
        d["panels"] = panels
        shared = [x for n, xs in panels.items() if s[n].scale != "own" for x in xs]
        if shared and "min" not in d:
            d["min"], d["max"] = _tight(builtin_min(shared), builtin_max(shared))
        own = {n: list(_tight(builtin_min(xs), builtin_max(xs)))
               for n, xs in panels.items() if s[n].scale == "own"}
        if own:
            d["panelScale"] = own
        if any(x < 0 for xs in panels.values() for x in xs):
            d["zeroRule"] = True
        d["accentLast"] = True

    # ── a cycle's path, and each row's own spark ─────────────────────────
    if "path" in s and "," in v.get("path", ""):
        d["cycle"] = nums("path", v["path"])
        if d["cycle"] is None:
            d.pop("cycle")
    sparks = {}
    for name in _family(plate, "spark"):
        row = name.rsplit("-", 1)[1]
        cells = _written(v, _family(plate, f"cell-{row}"))
        if cells:
            sparks[name] = _as_series(cells)
    if sparks:
        d["sparks"] = sparks
    # ── the one thing to look at ─────────────────────────────────────────
    # `accent=N` (from 1) or `accent=last` puts one column, row, part or
    # company in attention. A line can only accent its last point — that is
    # the only accent series.linePath draws.
    raw_acc = v.get("accent", "").strip().lower()
    if raw_acc and not _scatter(plate):
        n_items = (len(d.get("series") or []) if bar_cols else 0) or len(d.get("split") or []) \
            or len(d.get("bars") or [])
        if raw_acc == "last":
            if bar_cols or "split" in d or "bars" in d:
                d["accent"] = n_items - 1
            else:
                d["accentLast"] = True
        elif raw_acc.isdigit() and 1 <= int(raw_acc) <= builtin_max(n_items, 1):
            if bar_cols or "split" in d or "bars" in d:
                d["accent"] = int(raw_acc) - 1
            elif int(raw_acc) == len(d.get("series") or []):
                d["accentLast"] = True
            else:
                out.problems.append(f"accent={raw_acc}: a line can accent only its last point "
                                    f"(accent=last)")
        else:
            out.problems.append(f"accent= takes a position from 1 or `last`, and has {raw_acc!r}")
    return out


def axis_domain(plate, values: dict[str, str]) -> tuple[float, float] | None:
    """The y scale, read off the axis labels the writer filled (`y-1`…`y-5`).

    None when the axis is unlabelled: the renderer then fits the data's own
    range, which is honest because nothing on the plate claims otherwise.
    """
    got = [figure(values.get(name)) for name, slot in plate.slots.items() if slot.role == "axis"]
    got = [x for x in got if x is not None]
    if len(got) < 2:
        return None
    return builtin_min(got), builtin_max(got)


def _mark_scale(plate, v: dict, name: str, d: dict) -> tuple[float, float] | None:
    """The scale ONE mark is written on.

    `cac-line` is a level on the SAME scale as the line it crosses — the plot's
    y — so it is placed on the scale the line is drawn to. Every other mark is
    placed on what its axis prints, else taken as a 0-1 position.
    """
    slot = plate.slots[name]
    plot = (d["min"], d["max"]) if d.get("min") is not None and d.get("max") is not None else None
    if slot.axis == "vertical" and "plot-area" in plate.slots and plot is not None:
        return plot
    return _axis_scale(plate, v, name, plot=plot)


def _check_shares(texts: list[str] | None, parts: list | None, out: PlateData) -> None:
    """Shares a divided bar prints reach 100%, and each is the part the bar is
    divided by. The check allows one unit of the last printed digit per
    share, because shares rounded to reach 100 move one of them by that much
    (design's own 38 of 282 is printed as 14%)."""
    if not texts:
        return
    pct = _as_series(texts)
    if any(x is None for x in pct):
        return
    if abs(sum(pct) - 100) > sum(rounding(t) for t in texts) + 1e-9:
        out.problems.append(f"the shares add up to {sum(pct):g}%, not 100%")
        return
    if not parts or len(parts) != len(pct) or any(x is None for x in parts) or sum(parts) <= 0:
        return
    total = sum(parts)
    off = [f"{t} is {100 * x / total:.1f}% of the bar"
           for t, x, p in zip(texts, parts, pct) if abs(100 * x / total - p) > 2 * rounding(t) + 1e-9]
    if off:
        out.problems.append("the shares printed are not the parts drawn: " + ", ".join(off))


def _bridge_data(plate, v: dict, out: PlateData, nums) -> None:
    """A bridge's open, steps and close — printed, or written — and whether
    they add up. A walk whose steps do not reach its own close is the one
    thing this plate must never show."""
    d = out.data
    step_cols = _family(plate, "step")
    has_ends = "step-open" in plate.slots or "step-close" in plate.slots
    printed = _written(v, _family(plate, "value"))
    texts: list[str] = []
    # The walk the plate PRINTS is the walk it draws, as for a chart's series.
    if printed and has_ends:
        if len(printed) != len(step_cols) + 2:
            out.problems.append(
                f"the walk prints {len(printed)} figures and the plate draws the opening "
                f"level, {len(step_cols)} steps and the close ({len(step_cols) + 2})")
            return
        vals = _as_series(printed)
        if any(x is None for x in vals):
            out.problems.append("the bridge's value-N figures are not all figures: "
                                + ", ".join(repr(t) for t, x in zip(printed, vals) if x is None))
            return
        opening, steps, closing = vals[0], vals[1:-1], vals[-1]
        texts = printed
        if "steps" in v:
            out.warnings.append(f"steps= is not drawn: the plate draws the "
                                f"{_span(_family(plate, 'value'))} it prints")
    elif "steps" in v:
        steps = nums("steps", v["steps"])
        if steps is None:
            return
        opening, closing = figure(v.get("open") or v.get("total")), figure(v.get("close") or v.get("remainder"))
        texts = [v.get("open") or v.get("total") or "", *v["steps"].split(","),
                 v.get("close") or v.get("remainder") or ""]
    else:
        return
    if opening is None or closing is None:
        out.problems.append("the bridge needs its opening and closing levels"
                            + (" (open= and close=)" if "steps" in v else ""))
        return
    if len(steps) != len(step_cols):
        out.problems.append(f"the bridge has {len(steps)} steps and the plate draws {len(step_cols)}")
        return
    tolerance = sum(rounding(t) for t in texts) + 1e-9
    landed = opening + sum(steps)
    if abs(landed - closing) > tolerance:
        out.problems.append(
            f"the bridge does not add up: {opening:g} plus the steps is {landed:g}, "
            f"and it closes at {closing:g}")
        return
    d.update({"open": opening, "steps": steps, "close": closing,
              "float": bool(plate.slots["bridge"].floats)})
