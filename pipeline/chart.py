"""The data path — and nothing else.

The kit draws the chart. Axes, ticks, gridlines, the plot-area tint, the period
heads, the frame, the y-axis labels: all of it is on the plate, authored by the
same hand as everything else in the video. What is left for code is the series
itself, drawn inside the region the plate reserved for it.

That is the split ``kit/engine/series.js`` was built around, and every plate states
it: ``charts/line-6y``'s ``plot-area`` carries the note *"code draws the data
path in here only"*, ``peers/peer-strip``'s ``bars`` region names
``series.rowBars``, ``cycles/cycle-frame``'s ``path`` names ``series.cycleArc``.
A plate reserves a region and knows nothing about numbers; this is the other
half.

What used to be here was a whole chart renderer — card, border, gridlines,
badges, a glow, a drawn ring around the last point, its own fonts and its own
palette. All of that is now furniture the plate already draws, and drawing it
again put a second card inside the first one.

**Six periods.** Four fiscal years, the last full year, LTM. The plates are
authored six wide and :func:`series_points` refuses a series that is not,
because dropping to five silently drops LTM — which is the column the argument
usually turns on.

**Colour by role.** A rise is ``up``, a fall is ``down``, and a quantity with no
direction is ``neutral-data`` even when the story about it is bad news. The
subject's own series is ``structure``; a peer's, consensus, or last year's is
``other-party``.

**Flat, like the kit.** The rebuild draws with one contour weight, flat fills and
no hand: no wobble, no pressure, no hatching. A series drawn in the old kit's
hand over a flat plate reads as a different object pasted on, so everything
here is a straight polyline or a filled box. A plate's declared data regions
are drawn by :mod:`pipeline.series`, the port of the kit's own renderers.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from PIL import ImageDraw

from config import Settings
from pipeline import series as S
from pipeline.plates import PERIOD_COUNT, Plate, Registry

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlotArea:
    """The region a plate reserved for data, in delivered pixels."""

    x: int
    y: int
    w: int
    h: int

    def point(self, fx: float, fy: float) -> tuple[float, float]:
        """A fraction of the region (0..1, y up) as a pixel."""
        return (self.x + fx * self.w, self.y + (1.0 - fy) * self.h)


def plot_area(plate: Plate, name: str = "plot-area") -> PlotArea | None:
    """The plate's data region, or None when it has not reserved one."""
    slot = plate.slot(name)
    if slot is None:
        slot = next((s for s in plate.slots.values()
                     if s.role in ("plot-area", "bars", "path")), None)
    if slot is None:
        return None
    x, y, w, h = slot.scaled()
    return PlotArea(x, y, w, h)


def series_points(values: list[float | None], *, periods: int = PERIOD_COUNT
                  ) -> list[tuple[int, float] | None]:
    """`(index, value)` per period, with gaps kept as gaps.

    An empty period is None and stays None. In this library an empty cell means
    NO DATA, and interpolating across it invents a number — which is the one
    thing the renderer must never do.
    """
    if len(values) != periods:
        raise ValueError(
            f"a series has to be {periods} periods — four fiscal years, the "
            f"last full year and LTM — and this one is {len(values)}. Dropping "
            f"to five drops LTM.")
    return [None if v is None else (i, float(v)) for i, v in enumerate(values)]


def axis_domain(plate: Plate, slot_values: dict[str, str]) -> tuple[float, float] | None:
    """The scale, read off the axis labels the DIRECTOR wrote.

    This is the renderer-computes-nothing rule applied to the one place it is
    easy to miss. The plate draws five gridlines and reserves `y-1`…`y-5` for
    their labels; whoever writes "0, 4, 8, 12, 16" has declared the scale, and a
    path fitted to its own min and max instead lands wherever it likes against
    those gridlines. The first cut of this drew a revenue line whose peak sat
    between the 12 and 16 rules while the label said 13.2.

    Returns None when the axis is unlabelled, and the caller falls back to the
    data's own range — which is honest, because then nothing on the plate
    claims otherwise.
    """
    return S.axis_domain(plate, slot_values)


def _domain(values: list[float]) -> tuple[float, float]:
    lo, hi = min(values), max(values)
    if hi == lo:
        pad = abs(hi) * 0.1 or 1.0
        return lo - pad, hi + pad
    pad = (hi - lo) * 0.08
    return lo - pad, hi + pad


def _polyline(d: ImageDraw.ImageDraw, pts: list[tuple[float, float]], colour,
              width: int) -> None:
    """A flat polyline with round joins and round ends, as series.linePath
    asks for (`stroke-linejoin` and `stroke-linecap` round)."""
    if len(pts) < 2:
        return
    fill = (*colour[:3], 255)
    d.line(pts, fill=fill, width=width, joint="curve")
    r = width / 2
    for x, y in (pts[0], pts[-1]):
        d.ellipse([x - r, y - r, x + r, y + r], fill=fill)


def draw_line(img, area: PlotArea, values: list[float | None], colour,
              *, width: int = 6, seed: str = "line",
              domain: tuple[float, float] | None = None) -> None:
    """The subject's series as a path, inside the plate's plot area.

    No axis, no grid, no frame, no badge, no glow. Those are on the plate.
    `domain` is the scale the axis labels declare — pass it, or the path fits
    itself and stops agreeing with the gridlines behind it. A gap stays a gap:
    the path breaks at an empty period rather than joining across it.
    """
    pts = series_points(values, periods=len(values))
    present = [p for p in pts if p is not None]
    if len(present) < 2:
        return
    lo, hi = domain or _domain([v for _, v in present])
    span = hi - lo or 1.0
    n = max(len(values) - 1, 1)
    d = ImageDraw.Draw(img)
    run: list[tuple[float, float]] = []
    for p in pts + [None]:
        if p is None:
            _polyline(d, run, colour, width)
            run = []
            continue
        i, v = p
        run.append(area.point(i / n, (v - lo) / span))


def draw_bars(img, area: PlotArea, values: list[float | None],
              colour_for, *, seed: str = "bars", gap: float = 0.34,
              domain: tuple[float, float] | None = None) -> None:
    """One bar per period, on a shared scale with the zero rule placed from the
    domain — so when every value is negative the bars run down from a zero at
    the top, which is the shape the beat has.

    `colour_for` takes a value and returns its role colour, so direction is
    decided once, by the caller, from the registry. Flat fills: the rebuild
    draws a bar as a box, and so does this.
    """
    pts = [p for p in series_points(values, periods=len(values)) if p is not None]
    if not pts:
        return
    vals = [v for _, v in pts]
    lo, hi = domain or (min(0.0, min(vals)), max(0.0, max(vals)))
    span = (hi - lo) or 1.0
    n = len(values)
    slot_w = area.w / n
    bw = slot_w * (1.0 - gap)
    zero_y = area.y + (1.0 - (0.0 - lo) / span) * area.h
    d = ImageDraw.Draw(img)
    for i, v in pts:
        cx = area.x + slot_w * (i + 0.5)
        top = area.y + (1.0 - (v - lo) / span) * area.h
        y0, y1 = (top, zero_y) if v >= 0 else (zero_y, top)
        d.rectangle([cx - bw / 2, y0, cx + bw / 2, max(y1, y0 + 3)],
                    fill=(*colour_for(v)[:3], 255))


def draw_row_bars(img, area: PlotArea, values: list[float | None],
                  colour_for, *, seed: str = "rows") -> None:
    """`series.rowBars` — one horizontal bar per row, one shared scale.

    The zero rule is placed from the domain, so when every move is red zero
    lands on the right-hand edge and every bar runs left from it. The plate
    cannot know that, which is why it reserves the column and leaves this here.
    """
    present = [(i, v) for i, v in enumerate(values) if v is not None]
    if not present:
        return
    vals = [v for _, v in present]
    lo, hi = min(0.0, min(vals)), max(0.0, max(vals))
    span = (hi - lo) or 1.0
    rows = len(values)
    row_h = area.h / rows
    zero_x = area.x + ((0.0 - lo) / span) * area.w
    thick = max(row_h * 0.42, 4)
    d = ImageDraw.Draw(img)
    for i, v in present:
        cy = area.y + row_h * (i + 0.5)
        end_x = area.x + ((v - lo) / span) * area.w
        x0, x1 = sorted((zero_x, end_x))
        d.rectangle([x0, cy - thick / 2, max(x1, x0 + 1), cy + thick / 2],
                    fill=(*colour_for(v)[:3], 255))


def draw_range_mark(img, area: PlotArea, t: float, median: float | None,
                    reg: Registry, *, seed: str = "mark") -> bool:
    """`series.rangeMark` — where the subject sits on the peer range, and where
    the peer set does. Returns whether anything was drawn.

    The plate draws the rail and its two end ticks, so the row holds its shape
    with no data on it; this is what sits ON the rail. `t` is 0 at the peer low
    and 1 at the peer high, `median` is the peer set on that same scale, and
    both are written by the director off `Peers!I` and `Peers!J` — the renderer
    computes neither.

    Three rules, and each of them is a decision rather than an implementation
    detail:

    * **The scale is inset by the mark's own radius.** Mapped edge to edge, a
      subject level with the top peer draws a dot centred on the high end tick:
      it hides the tick it is being measured against and half of it lands
      outside the region the plate reserved. Inset, `t = 1` sits tangent to
      that tick and nothing paints past the box.
    * **Off the range is a READING, not an error.** The peer ends are p10 and
      p90, so a subject priced above every peer is `t > 1` — the most quotable
      row on the plate. The dot is pushed against its end tick from the inside
      and a chevron points out past it, both still inside the region. Dropping
      the mark, or clamping it silently, loses the one row worth talking about.
    * **Nothing here is drawn in `up` or `down`.** Cheap is not up and
      expensive is not down: a multiple is a price, not a direction, and a red
      dot high on the rail would argue the short before the script does.
      Position carries the claim. The subject is `structure`, the peer set is
      `other-party` — the same pairing as every other plate in the library.
    """
    if t is None:
        return False
    cy = area.y + area.h / 2.0
    # THE MARK IS CAPPED AGAINST THE RAIL IT SITS ON, not only against the
    # region's height — and this is a deliberate divergence from
    # `series.rangeMark`, which sizes it as `max(9, h * 0.3)` alone.
    #
    # That formula was tuned on the landscape rail, which is 669x65 canvas
    # units: 10.3:1, a dot 6% of the rail's length, 94% of it left to position
    # against. 09b's F3 fix made the portrait rows 430 units tall to fill the
    # safe band, which took its marker region to 243x260 — very nearly square.
    # `h * 0.3` there is a radius of 78 on a rail 243 long: a dot covering 64%
    # of its own scale, hiding the median tick it is being compared with, and
    # squeezing the entire 0-to-1 range into the 87 units left over.
    #
    # The cap leaves 16:9 EXACTLY as the engine draws it (19.5 either way) and
    # gives 9:16 a dot of 22 with 82% of the rail to move along. Design owns
    # the real fix — it belongs in series.js so the proofs agree — and this is
    # in the report that goes back with this pack.
    r = min(max(9.0, area.h * 0.3), area.w * 0.09)
    span = max(area.w - r * 2.0, 1.0)

    def x_at(v: float) -> float:
        return area.x + r + max(0.0, min(1.0, v)) * span

    d = ImageDraw.Draw(img)

    # The median as a TICK, not a second dot: two dots on one rail read as two
    # subjects, and the peer set is not a subject.
    if median is not None:
        mx = x_at(median)
        other = reg.colour("other-party")
        w = max(int(r * 0.42), 4)
        d.rectangle([mx - w / 2, cy - area.h * 0.4, mx + w / 2, cy + area.h * 0.4],
                    fill=(*other[:3], 255))

    off = 1 if t > 1.0 else -1 if t < 0.0 else 0
    subject = reg.colour("structure")
    cx = x_at(t) - off * r * 1.9
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(*subject[:3], 255))
    if off:
        tip = x_at(t) + off * r * 0.85
        _polyline(d, [(tip - off * r * 0.8, cy - r * 0.6), (tip, cy),
                      (tip - off * r * 0.8, cy + r * 0.6)],
                  subject, max(int(r * 0.2), 3))
    return True


def draw_cycle_arc(img, area: PlotArea, values: list[float | None], colour,
                   *, seed: str = "cycle") -> tuple[int, float] | None:
    """`series.cycleArc` — every period between the two moments, one colour.

    Returns the trough `(index, value)` so the caller can label it on real
    coordinates. ONE colour for the whole path: colouring the fall in `down` and
    the recovery in `up` makes the frame argue for the recovery, and the reason
    this plate exists is that the line went somewhere else first.
    """
    draw_line(img, area, values, colour, width=6, seed=seed)
    present = [(i, v) for i, v in enumerate(values) if v is not None]
    if not present:
        return None
    return min(present, key=lambda p: p[1])


def trough_point(area: PlotArea, values: list[float | None],
                 index: int) -> tuple[float, float] | None:
    """Where the trough sits in the plot area, for the label's drop line."""
    present = [v for v in values if v is not None]
    if not present or values[index] is None:
        return None
    lo, hi = _domain(present)
    span = hi - lo or 1.0
    n = max(len(values) - 1, 1)
    return area.point(index / n, (values[index] - lo) / span)


# Which slot family carries the figures a plate's data region draws through,
# per renderer region. The DIRECTOR writes these — `value=400,431,…` on a line
# chart, `cell=…` on a row spotlight, `move-N` on a peer strip — so the path is
# drawn through the numbers that are printed on the plate beside it. Nothing
# here computes a figure; it reads the ones already on screen.
SERIES_SLOTS = {
    "plot-area": ("value", "point", "cell"),
    "bars": ("move",),
    "path": ("value", "cell"),
}


def _num(raw: str) -> float | None:
    """A figure as the director wrote it. None when it is not a number.

    An empty cell means NO DATA and stays None — the path breaks there rather
    than interpolating, because interpolating invents a figure. The reading is
    :func:`pipeline.series.figure`'s, so `$1.2bn`, `−$18m` and `+1.6pt` are
    figures here exactly as they are on a walk.
    """
    return S.figure(raw)


class ChartSlotError(RuntimeError):
    """A data region whose plate offers no slot stem this code knows.

    The ethos everywhere else in this pipeline is that a name resolving to
    nothing fails the build rather than drawing an empty area —
    `Registry.require` raises, `compose.build_layers` raises. This was the one
    place that shrugged: `SERIES_SLOTS` maps a region to the slot stems it
    reads, a kit that renamed a stem matched none of them, and the chart drew
    its axes, its grid and its frame with no data path in it at all. Silently,
    and with no test anywhere.
    """


def declared_series(plate: Plate, values: dict[str, str],
                    region: str) -> list[float | None]:
    """The series a data region draws, read off the slots the director filled.

    Raises when the plate declares NO slot for any stem this region knows —
    that is a kit and renderer that disagree about what a chart is made of,
    and it has to be loud. An empty list still comes back when the stems are
    there and the director simply filled none of them: a chapter that names a
    chart and gives it no figures is a script problem, and the gates are
    where a script is refused.
    """
    stems = SERIES_SLOTS.get(region, ())
    if not stems:
        raise ChartSlotError(
            f"no slot stems are known for the data region {region!r}. "
            f"SERIES_SLOTS covers {', '.join(sorted(SERIES_SLOTS))} — either "
            f"the kit renamed a region or this table is behind it")
    found_any = False
    for stem in stems:
        idx = sorted(
            (int(n.rsplit("-", 1)[1]), n) for n in plate.slots
            if n.startswith(f"{stem}-") and n.rsplit("-", 1)[1].isdigit())
        if not idx:
            continue
        found_any = True
        series = [_num(values.get(n, "")) for _, n in idx]
        if any(v is not None for v in series):
            return series
    if not found_any:
        raise ChartSlotError(
            f"{plate.key} draws a {region!r} region but declares no "
            f"{'/'.join(f'{stem}-N' for stem in stems)} slots for it, so "
            f"there is no path for the data onto the plate. A renamed stem "
            f"in a new kit looks exactly like this, and used to draw an "
            f"empty chart instead of saying so")
    return []


def _draw_range_marks(reg: Registry, plate: Plate, values: dict[str, str],
                      img, *, seed: str = "") -> bool:
    """Every `marker-N` the director wrote a pair into. True if any drew.

    An unwritten marker draws NOTHING and that is correct: the plate's own rail
    and end ticks are already there, so the row keeps its shape. A rail with no
    mark is a metric nobody had peer data for, which is information; a mark at
    a made-up position would not be.
    """
    from pipeline.plate_tags import parse_marker

    drew = False
    for name, slot in sorted(plate.slots.items()):
        if not (slot.region and slot.renderer.rsplit(".", 1)[-1] == "rangeMark"):
            continue
        raw = str(values.get(name) or "").strip()
        if not raw:
            continue
        pair, why = parse_marker(raw)
        if pair is None:
            # The parser and the gate both refuse this shape, so reaching here
            # means something bound a value behind their backs. Say so and draw
            # nothing rather than guessing at a position.
            log.warning("%s %s: %s — no mark drawn (%r)", plate.key, name, why, raw)
            continue
        x, y, w, h = slot.scaled()
        drew |= draw_range_mark(img, PlotArea(x, y, w, h), pair.t, pair.median,
                                reg, seed=f"{seed or plate.key}|{name}")
    return drew


def _ink(reg: Registry, plate: Plate) -> dict[str, str]:
    """The kit's inks at the hour this plate is drawn at."""
    palette = reg.palettes.get(plate.hour or reg.base_hour) or reg.palette
    return S.ink_for(palette)


def draw_declared(reg: Registry, plate: Plate, values: dict[str, str], img,
                  *, seed: str = "") -> bool:
    """Draw a plate's data regions from its own slot values. True if it drew.

    This is what makes `[PLATE: bars-6y-16x9 | value=400,431,…]` a chart rather
    than a set of labels around an empty box: the plate reserves the regions,
    the writer writes the figures, and the kit's own renderers — ported in
    :mod:`pipeline.series` — draw through them. Every region the plate declares
    is drawn, not the first one found: a rail plate carries a column of share
    bars AND a growth mark per row.

    A tag the grammar would refuse never reaches here, so a problem found now
    is logged and that part is left undrawn rather than guessed at.
    """
    # A PLATE MAY RESERVE MANY REGIONS, NOT ONE. `tables/multiples-strip`
    # declares a rail per row and each takes its own {t, median} pair — the bot's
    # own renderer, with the peer median as a tick, drawn first.
    drew = _draw_range_marks(reg, plate, values, img, seed=seed)
    got = S.plate_data(plate, values)
    for why in got.problems:
        log.warning("%s: %s — that part is not drawn", plate.key, why)
    nodes = S.data_layer(S.boxes(plate), got.data, _ink(reg, plate))
    if nodes:
        S.paint(img, nodes, plate.export_scale * img.width / max(plate.pixel_size[0], 1))
        drew = True
    return drew


def declared_layer(reg: Registry, plate: Plate, values: dict[str, str],
                   size: tuple[int, int] | None = None, *, seed: str = ""):
    """The data drawing alone, on a transparent layer, or None if nothing drew.

    For a plate that boils: the frames differ, the data does not, so it is
    drawn once and laid over every frame rather than drawn three times.
    """
    from PIL import Image

    layer = Image.new("RGBA", tuple(size or plate.pixel_size), (0, 0, 0, 0))
    return layer if draw_declared(reg, plate, values, layer, seed=seed) else None


def render_series(reg: Registry, plate: Plate, values: list[float | None],
                  settings: Settings, *, slot_values: dict[str, str] | None = None,
                  subject: bool = True, seed: str = ""):
    """A charts/ plate with its data path drawn in. The whole public surface.

    The caller supplies the figures — the renderer never computes one — and the
    plate supplies everything else. Drawn by the kit's own renderers: through
    each column's published `anchorX`, on the scale the axis labels declare.
    """
    from pipeline.plate_frames import render_still

    slot_values = dict(slot_values or {})
    img = render_still(plate, slot_values, settings, reg)
    if plot_area(plate) is None:
        log.warning("%s reserves no plot area — nothing to draw into", plate.key)
        return img
    domain = axis_domain(plate, slot_values)
    if domain is None:
        log.warning("%s has no labelled y-axis — the path is fitted to its own "
                    "range, and the gridlines behind it mean nothing", plate.key)
    data: dict = {"series": [None if v is None else float(v) for v in values]}
    if domain is not None:
        data["min"], data["max"] = domain
    ink = _ink(reg, plate)
    if not subject:
        # A peer's, consensus', last year's series: the other party's ink.
        ink = dict(ink, subject=ink.get("axis", ink.get("subject")))
    present = [v for v in data["series"] if v is not None]
    if len(present) < 2:
        return img
    if any(v is None for v in data["series"]):
        # series.js has no gaps; an empty period is NO DATA and the line
        # breaks there, so a series with holes is drawn as runs.
        area = plot_area(plate)
        draw_line(img, area, data["series"], S._rgba(ink["subject"])[:3], domain=domain)
        return img
    nodes = S.data_layer(S.boxes(plate), data, ink)
    S.paint(img, nodes, plate.export_scale * img.width / max(plate.pixel_size[0], 1))
    return img


def render_price_plate(reg: Registry, series, out: Path, settings: Settings, *,
                       aspect: str = "9x16", slot_values: dict[str, str] | None = None,
                       seed: str = "price") -> tuple[Path, dict]:
    """A price series into `charts/line-dense`, and where it drew its points.

    `line-dense` is the plate for this: many observations, four period heads,
    three marks — for a daily series where the individual points are not the
    point. What comes back is the path plus the plot box in DELIVERED pixels,
    so a mark can be placed from where the line actually went rather than from
    a second guess at the same arithmetic.

    One flat line, no dot per close: sixty dots a phone-width apart is a
    string of beads, and the individual closes are not the claim.
    """
    from pipeline.plate_frames import render_still

    key = reg.aspect_key("charts/line-dense", aspect)
    if key is None:
        raise PlateMissing("charts/line-dense is not in the registry")
    plate = reg.require(key)
    values = dict(slot_values or {})
    img = render_still(plate, values, settings, reg)
    area = plot_area(plate)
    closes = [float(c) for c in series.closes]

    if area is not None and len(closes) >= 2:
        lo, hi = _domain(closes)
        span = hi - lo or 1.0
        n = max(len(closes) - 1, 1)
        px = [area.point(i / n, (v - lo) / span) for i, v in enumerate(closes)]
        # The subject's own series is `structure`. A price line is not a
        # direction — the move is the direction, and it is stated in type.
        _polyline(ImageDraw.Draw(img), px, reg.colour("structure"), 6)

    img.convert("RGBA").save(out)
    box = ((area.x, area.y, area.x + area.w, area.y + area.h) if area
           else (0, 0, img.width, img.height))
    return out, {"size": img.size, "plot_box": box, "plate": plate.key}


class PlateMissing(RuntimeError):
    """The plate this renderer needs is not in the registry."""
