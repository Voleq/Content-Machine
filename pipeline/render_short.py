"""Render a SHORT from a shot template and the audio clock.

The old renderer chose its own composition from tags in the script and ran to
1,930 lines doing it. This one chooses nothing. `templates/shots/short.json`
fixes space and order, the word timestamps fix duration, and everything here
is the machinery between those two facts and a file on disk.

The register is picked once from the script sha and every plate in the video
is drawn in it. Frames are composed in memory and piped straight into the
encoder — 2,000 uncompressed 1080x1920 frames is not something to put on a
disk on the way past.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

from pipeline import marks as mk
from pipeline.compose import (BuildResult, Layer, build_layers,
                              check_budgets, check_invariants,
                              held_layer_spans)
from pipeline.kit_manifest import KitError, kit_for, pick_register
from pipeline.models import ShortScript
from pipeline.render_common import RenderError, encode_profile, run_ffmpeg
from pipeline.shots import (Format, expand_sequences, load_format,
                            resolve_spans)

FPS = 30
# The kit boils at three frames, 7fps. Code-drawn artwork matches it.
BOIL_FRAMES = 3
# The SHORT's host shots. The spec said 1, 5-8, 11, 12; 5-8 are the numbers
# walk, and the walk pushes in until the sheet is full-bleed and the plate's
# figure slot is off the bottom of the frame. A figure clamped back in stands
# on the numbers. So the host is out of the walk and the spec is amended here
# rather than in a comment that disagrees with the template.
# tests/test_short_shots.py asserts this and the template agree.
HOST_SHOTS = ("cold-open", "payoff", "close")

# One definition, in marks, so the fitter and the budget measurement agree.
BODY_FONT = mk.BODY_FONT
DISPLAY_FONT = mk.DISPLAY_FONT

_FIGURE = re.compile(r"^(-?)([$€£]?)([\d.,]+)([KMBT]?)(%?)$")


def _unit_of(rows) -> str:
    """The unit every flow row on this sheet shares, or "".

    "$400M" is five characters where "400" is three, and a sheet row is
    1003px wide holding a label and five figures: at five characters each,
    nothing fits above the legibility floor and the row sets at 33px. The
    currency and the magnitude are the same on every row of a company sheet,
    so they are said ONCE, in the header's empty label cell, and the columns
    carry the number.

    Returns "" unless every figure agrees — a mixed sheet keeps its units in
    the figures, where an ambiguous column would otherwise be a wrong one.
    """
    from pipeline.models import MetricKind
    seen = set()
    for r in rows:
        if r.measured is not MetricKind.FLOW:
            continue
        for v in r.values:
            m = _FIGURE.match(str(v).strip())
            if not m:
                return ""
            seen.add(m.group(2) + m.group(4) + m.group(5))
    return seen.pop() if len(seen) == 1 else ""


def _bare(value: str, unit: str) -> str:
    """A figure with the sheet's shared unit taken off the front and back."""
    if not unit:
        return value
    m = _FIGURE.match(str(value).strip())
    if not m or m.group(2) + m.group(4) + m.group(5) != unit:
        return value
    return f"{m.group(1)}{m.group(3)}"


# ---------------------------------------------------------------------------
# Binding the script to the template
# ---------------------------------------------------------------------------

@dataclass
class ShortResolver:
    """Supplies words and figures for a source expression. Composes nothing."""

    script: ShortScript
    workdir: Path
    settings: object
    prices: object | None = None
    handle: str = ""

    def __post_init__(self) -> None:
        self._images: dict[str, Path | list[Path] | None] = {}
        self._fracs: dict[str, tuple[float, float, float, float]] = {}

    @property
    def rows(self):
        """The metric rows, from whichever script this is.

        A SHORT carries them on the script. A LONG does not — its numbers
        come from the data export — so this is read through, not reached for.
        """
        return list(getattr(self.script, "numbers", []) or [])

    # -- text -------------------------------------------------------------
    def text_for(self, src: str) -> str | None:
        parts = src.split(".")
        if parts[0] == "channel":
            return self.handle or None
        if parts[0] == "compare":
            return self._compare(parts[1])
        if parts[0] == "numbers":
            return self._numbers(parts[1:])
        if parts[0] != "script":
            return None
        obj: object = self.script
        for p in parts[1:]:
            if p.isdigit():
                try:
                    obj = obj[int(p)]        # type: ignore[index]
                except (IndexError, TypeError):
                    return None
            else:
                obj = getattr(obj, p, None)
            if obj is None:
                return None
        return str(obj) if obj is not None else None

    def list_for(self, src: str) -> list[str] | None:
        """A list source, for a shot that places a repeat."""
        parts = src.split(".")
        if parts[0] != "script" or len(parts) != 2:
            return None
        if parts[1] == "numbers":
            return [r.label for r in self.rows] or None
        got = getattr(self.script, parts[1], None)
        if isinstance(got, list) and got:
            return [str(x) for x in got]
        return None

    def _numbers(self, rest: list[str]) -> str | None:
        """One row of the sheet: its label and its figures, oldest to newest.

        The plate draws no rows — group C interiors are empty for code — so
        every band on the sheet is type this puts there.
        """
        from pipeline.models import MetricKind
        rows = self.rows
        field = "row"
        if rest and not rest[0].isdigit():
            field, rest = rest[0], rest[1:]

        # The column header. Without it five figures in a row are one long
        # number, and there is nothing to say which year is which. Its label
        # cell is empty, so the sheet's shared unit goes there.
        if field == "header":
            years = list(getattr(self.script, "years", []) or [])
            return (f"{_unit_of(rows)}\t" + "\t".join(years)) if years else None

        if not rest or not rest[0].isdigit():
            return None
        i = int(rest[0])
        if i >= len(rows):
            return None
        r = rows[i]
        if field == "label":
            return r.label
        if field == "latest":
            return r.values[-1]

        # Tab-separated: the renderer lays these out as COLUMNS on one line,
        # so a figure sits under its year. A flow is a series across periods;
        # a stock is one reading and the date it was taken, and the two do
        # not share a row format because they are not the same kind of fact.
        if r.measured is MetricKind.STOCK:
            years = list(getattr(self.script, "years", []) or [])
            asat = years[-1] if years else "latest"
            return f"{r.label}\t{r.values[-1]}\tat {asat}"
        unit = _unit_of(rows)
        return f"{r.label}\t" + "\t".join(_bare(v, unit) for v in r.values)

    def _compare(self, which: str) -> str | None:
        """The two multiples in CHEAP OR TRAP, heavy against light."""
        rows = self.rows
        if which == "versus":
            return "vs"
        # EARNINGS and MACRO put the print against consensus. Both are their
        # own fields when the script carries them.
        if which == "reported":
            return (getattr(self.script, "reported", None)
                    or (rows[0].values[-1] if rows else None))
        if which == "expected":
            return getattr(self.script, "expected", None)
        pick = None
        for r in rows:
            lab = r.label.lower()
            if any(k in lab for k in ("p/e", "pe", "multiple", "ev/", "price")):
                pick = r
                break
        pick = pick or (rows[0] if rows else None)
        if pick is None:
            return None
        if which == "heavy":
            return f"{pick.label}\n{pick.values[-1]}"
        if which == "light":
            return f"{pick.label}\n{pick.values[0]}"
        return None

    # -- images -----------------------------------------------------------
    def image_for(self, src: str) -> Path | list[Path] | None:
        if src in self._images:
            return self._images[src]
        out = None
        if src == "chart.price":
            out = self._chart()
        elif src.startswith("plate."):
            out = None       # nested plates resolve through the kit, not here
        self._images[src] = out
        return out

    def frac_box_for(self, src: str) -> tuple[float, float, float, float] | None:
        """A mark target inside an image, as fractions of that image."""
        self.image_for("chart.price")
        return self._fracs.get(src)

    def _chart(self) -> list[Path] | None:
        """The chart, drawn three times.

        A full-bleed chart covers the plate behind it, so if the chart is one
        still PNG the shot stops boiling and becomes a photograph with a live
        plate hidden underneath. Three seeds is the kit's own answer: the
        drawing is made again rather than transformed.
        """
        if self.prices is None:
            return None
        from pipeline.chart import render_marker_price_chart
        paths = []
        try:
            for i in range(BOIL_FRAMES):
                out = self.workdir / f"chart_price_f{i + 1:02d}.png"
                path, meta = render_marker_price_chart(
                    _legible(self.prices), out, self.settings,
                    size=(872, 1712), move_text="", seed=f"boil{i}",
                    ring=False)
                paths.append(path)
        except Exception:                                    # noqa: BLE001
            return None
        # The ring goes on the extreme CANDLE, never on a label and never
        # near it. The chart reports where it actually drew that point, so
        # the mark is placed from the drawing rather than from a second
        # guess at the same arithmetic.
        # The ring goes on the EXTREME point, which is the one the shot is
        # about — not on the last one, which is merely where the line stops
        # and is often sitting on the axis.
        cw, ch = meta["size"]
        x0, y0, x1, y1 = meta["plot_box"]
        closes = list(_legible(self.prices).closes)
        lo, hi = min(closes), max(closes)
        i = closes.index(hi if abs(hi - closes[0]) >= abs(lo - closes[0]) else lo)
        px = x0 + (x1 - x0) * (i / max(len(closes) - 1, 1))
        py = y1 - (y1 - y0) * ((closes[i] - lo) / (hi - lo) if hi > lo else 0.5)
        rx, ry = 0.09, 0.09 * cw / ch
        self._fracs["chart.extreme_candle"] = (
            max(0.0, px / cw - rx), max(0.0, py / ch - ry), rx * 2, ry * 2)
        return paths


# A 66-second chart showing every daily close reads as an audio waveform, not
# as a price. The shape of the move is the point; the tick detail is noise at
# this size, so the series is thinned to about this many points for drawing.
CHART_MAX_POINTS = 60


def _legible(series):
    """The same series, thinned so its SHAPE is what reads.

    Drawn, not resampled cleverly: every nth close, with the last one kept so
    the line still ends where the move ended.
    """
    closes = list(series.closes)
    if len(closes) <= CHART_MAX_POINTS:
        return series
    from dataclasses import replace
    step = len(closes) / CHART_MAX_POINTS
    idx = sorted({min(int(i * step), len(closes) - 1)
                  for i in range(CHART_MAX_POINTS)} | {len(closes) - 1})
    return replace(series, closes=[closes[i] for i in idx],
                   dates=[series.dates[i] for i in idx])


def build_anchors(script: ShortScript) -> dict[str, str]:
    """The words each shot listens for in the narration.

    A shot starts where its own text is spoken. This is the whole of the
    timing model: no shot has a duration until the audio says what it is.
    """
    out: dict[str, str] = {}
    if script.hook_text:
        out["hook"] = script.hook_text
    if script.move_summary:
        out["move"] = script.move_summary
    if script.headlines:
        out["headline"] = script.headlines[0].text
    if script.turn_line:
        out["turn"] = script.turn_line
    if script.numbers:
        out["numbers"] = script.numbers[0].label
    if script.numbers_comment:
        out["numbers_comment"] = script.numbers_comment
    if script.cheap_or_trap:
        out["cheap_or_trap"] = script.cheap_or_trap
    if script.conclusion:
        out["conclusion"] = script.conclusion
    # EARNINGS and MACRO listen for their own beats. A key with no field
    # behind it simply never anchors, and its shot interpolates.
    if script.verdict:
        out["verdict"] = script.verdict
    if script.guidance:
        out["guidance"] = script.guidance
    if script.expected:
        out["expected"] = script.expected
    if script.numbers:
        out["print"] = script.numbers[0].label
    if script.mechanism:
        out["mechanism"] = script.mechanism[0]
    if script.consequences:
        out["consequences"] = script.consequences[0]
    if script.headlines:
        out["statement"] = script.headlines[0].text
    if script.cheap_or_trap:
        out["priced"] = script.cheap_or_trap
    return out


def cap_one_shots(spans, kit, register):
    """A transition may not outlive its own strip.

    dive-in is ten frames at 12fps — 0.83s — and then it has nothing left to
    play. Given an equal share of the runtime it holds its last frame for
    another three seconds, which is a freeze in the middle of the format's
    most-used motion. The span is cut to the strip and the time handed to the
    shot that follows, where something is actually happening.

    Done here rather than in the span resolver because it needs the kit: how
    long a strip runs is a fact about the asset, not about the template.
    """
    from pipeline.shots import Span
    out = list(spans)
    for i, sp in enumerate(out):
        if not sp.shot.plate:
            continue
        try:
            e = kit.concept(sp.shot.plate, register)
        except KitError:
            continue
        if e.loops or e.playback != "one-shot":
            continue
        strip = e.cycle_s
        if strip <= 0 or sp.dur <= strip + 1e-6:
            continue
        cut = sp.start + strip
        out[i] = Span(sp.shot, sp.start, cut, sp.anchored)
        if i + 1 < len(out):
            nxt = out[i + 1]
            out[i + 1] = Span(nxt.shot, cut, nxt.end, nxt.anchored)
    return out


def resolver_probe(script: ShortScript, settings) -> "ShortResolver":
    """A resolver used only to ask whether a shot has anything to say."""
    return ShortResolver(script=script, workdir=Path("."), settings=settings,
                         handle=getattr(settings, "brand_handle", "") or "")


def prune_empty_shots(fmt: Format, probe: "ShortResolver") -> tuple[Format, list[str]]:
    """Drop every shot with no plate and no text the script can fill.

    A shot that names a plate always has something to draw. A bare-ground shot
    is only ever its type, so when the type is missing the shot is nothing —
    and an empty frame in the cut is worse than one fewer shot in it.
    """
    from dataclasses import replace
    keep, dropped = [], []
    for shot in fmt.shots:
        # A shot that lights one row of the sheet is about that row. With
        # fewer metrics than the template has numbers shots, the extra shots
        # have nothing to light — one row per shot means no row, no shot.
        if shot.lit and shot.lit != "all":
            src = (shot.bind.get(shot.lit) or "").lstrip("?")
            if src and not probe.text_for(src):
                dropped.append(shot.id)
                continue
        if shot.plate or shot.bind:
            keep.append(shot)
            continue
        # A repeat shot names no plate and binds no slot — it places a list.
        # Without this it was pruned as empty and MACRO rendered eight shots
        # of nine, silently.
        if shot.repeat:
            if probe.list_for(shot.repeat.src):
                keep.append(shot)
            else:
                dropped.append(shot.id)
            continue
        if any(probe.text_for(t.src) for t in shot.text):
            keep.append(shot)
        else:
            dropped.append(shot.id)
    if not keep:
        raise RenderError("every shot was dropped; the script fills nothing")
    return replace(fmt, shots=tuple(keep)), dropped


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------

class _Cache:
    """Resized frames, keyed by path and size. A boil is three images."""

    def __init__(self) -> None:
        self._d: dict[tuple[str, int, int], Image.Image] = {}

    def get(self, path: Path, w: int, h: int) -> Image.Image:
        key = (str(path), w, h)
        hit = self._d.get(key)
        if hit is None:
            im = Image.open(path).convert("RGBA")
            if im.size != (w, h):
                im = im.resize((max(w, 1), max(h, 1)), Image.LANCZOS)
            self._d[key] = hit = im
        return hit


def _frame_for(layer: Layer, t: float) -> Path:
    """Which frame of an animated layer is showing at `t`.

    fps and playback come from the manifest entry the layer was built from —
    a boil runs at 7, a host loop at 12, a one-shot plays once at 12 and holds
    its last frame. Nothing here assumes a rate.
    """
    if not layer.frames:
        raise RenderError(f"{layer.name}: animated layer with no frames")
    if len(layer.frames) == 1 or layer.fps <= 0:
        return layer.frames[0]
    i = int((t - layer.t_start) * layer.fps)
    if layer.loops:
        i %= len(layer.frames)
    else:
        i = min(i, len(layer.frames) - 1)
    return layer.frames[max(i, 0)]


def _type_floor(canvas: Image.Image) -> int:
    """The smallest type any layer may shrink to: the readability floor.

    Type shrinks before it truncates, but it stops here — below this nothing
    can be read on a phone, and losing the words is then the lesser evil,
    provided it is said out loud.
    """
    from pipeline.shots import MIN_TYPE_FH
    return max(12, int(MIN_TYPE_FH * canvas.height))


def _slot_floor(canvas: Image.Image) -> int:
    """The floor for type whose size comes from a KIT SLOT, not a template.

    A sheet row band or a card label is a short string read in context, not
    prose, and the kit's own geometry sets it. Holding those to the authored
    prose floor makes a five-year row give up three years to buy 20px it did
    not need — see `_agree_on_a_sheet`.
    """
    from pipeline.compose import SLOT_TYPE_FLOOR_FH
    return max(12, int(SLOT_TYPE_FLOOR_FH * canvas.height))


def _boil_index(layer: Layer, t: float) -> int:
    """Which redraw of a code-drawn MARK is showing at `t`.

    Marks only. Type used to come through here too — re-PLACED by a pixel or
    two rather than re-drawn, because a font cannot be redrawn stroke by
    stroke — and on a figure that reads as vibration, not as a hand. The
    re-placement helper is gone rather than left as a knob at zero.
    """
    if not layer.boil_fps:
        return 0
    return int((t - layer.t_start) * layer.boil_fps)


def _draw_columns(canvas: Image.Image, layer: Layer, dx: int, dy: int,
                  ink, lost: dict[str, int] | None) -> None:
    """A sheet row: label on the left, figures in fixed columns, ONE line.

    Wrapping a five-year series across two lines destroys the column
    relationship that is the whole point of the row, so this never wraps. If
    the series will not fit it drops the OLDEST period and says how many it
    dropped — fewer years, legibly, beats five years in a heap.
    """
    from PIL import ImageDraw
    d = ImageDraw.Draw(canvas)
    parts = layer.text.split("\t")
    label, values = parts[0], [v for v in parts[1:] if v != ""]
    colour = ink if layer.lit else mk.MUTED
    face = mk.DISPLAY_FONT if layer.lit else mk.BODY_FONT

    # `type_px` is the size the WHOLE SHEET agreed on, measured at build
    # time. A stock row has one column where a flow has five, so sized on its
    # own it never has to shrink and ends up half again as big as the rows
    # around it — which is what "Shares out" was doing to a table it is
    # supposed to be a row of.
    size, values, dropped = mk.fit_columns(
        d, label, values, layer.w, layer.h, font_name=face,
        start_px=layer.type_px, min_px=_slot_floor(canvas))
    font = mk.load_font(face, size)

    asc, desc = font.getmetrics()
    y = layer.y + dy + max((layer.h - (asc + desc)) // 2, 0)
    label_w, col_w = mk.column_widths(
        layer.w, len(values),
        d.textlength(label, font=font) if label else 0.0)
    if label:
        d.text((layer.x + dx, y), label, font=font, fill=colour)
    for i, v in enumerate(values):
        right = layer.x + dx + label_w + col_w * (i + 1) - 4
        d.text((right - d.textlength(v, font=font), y), v, font=font,
               fill=colour)
    if dropped and lost is not None:
        lost[layer.name] = dropped


def _draw_layer(canvas: Image.Image, layer: Layer, t: float, cache: _Cache,
                register: str, resolver: ShortResolver,
                lost: dict[str, int] | None = None) -> None:
    ink = mk.INK_FOR_REGISTER.get(register, mk.INK)

    if layer.kind == "ground":
        canvas.paste(mk.PAPER, (0, 0, canvas.width, canvas.height))
        return

    if layer.kind == "panel":
        # Paper, with a drawn edge. Type over a drawing needs a surface, and
        # in this kit a surface is a torn sheet, not a rounded rectangle.
        # ONE seed for the whole shot: the panel is the box framing type, and
        # a box that redraws three times a second is the same unreadability
        # as type that does.
        rng = mk.rng_for(layer.name)
        d = ImageDraw.Draw(canvas)
        box = (layer.x, layer.y, layer.x + layer.w, layer.y + layer.h)
        d.rectangle(box, fill=mk.PAPER)
        mk.drawn_rect(d, box, rng, width=max(3, canvas.width // 320),
                      color=ink, jitter=1.8, overshoot=0.01)
        return

    if layer.kind == "light":
        # A wash MULTIPLIES. Composited normally it would paint over the ink
        # instead of falling on it, and the room would go flat rather than
        # dim. Alpha is respected so the untouched parts of the overlay leave
        # the paper alone.
        im = cache.get(_frame_for(layer, t), layer.w, layer.h)
        base = canvas.crop((layer.x, layer.y,
                            layer.x + layer.w, layer.y + layer.h)).convert("RGB")
        from PIL import ImageChops
        wash = Image.alpha_composite(
            Image.new("RGBA", im.size, (255, 255, 255, 255)), im).convert("RGB")
        canvas.paste(ImageChops.multiply(base, wash).convert("RGBA"),
                     (layer.x, layer.y))
        return

    if layer.kind == "clock":
        # The hands read the same hour the light does. A clock disagreeing
        # with the window is worse than no clock at all.
        from pipeline.progression import clock_hands
        import math
        rng = mk.rng_for(layer.name, _boil_index(layer, t))
        d = ImageDraw.Draw(canvas)
        cx, cy = layer.x + layer.w / 2, layer.y + layer.h / 2
        r = min(layer.w, layer.h) / 2
        for ang, length, width in zip(clock_hands(layer.size_fh),
                                      (r * 0.52, r * 0.80),
                                      (max(3, int(r * 0.13)),
                                       max(2, int(r * 0.09)))):
            a = math.radians(ang - 90)
            mk.marker_stroke(d, [(cx, cy),
                                 (cx + math.cos(a) * length,
                                  cy + math.sin(a) * length)],
                             rng, width=width, color=ink, jitter=1.0, passes=2)
        return

    if layer.kind in ("plate", "host", "enter"):
        im = cache.get(_frame_for(layer, t), layer.w, layer.h)
        canvas.alpha_composite(im, (layer.x, layer.y))
        return

    if layer.kind == "fill":
        if layer.frames:
            im = cache.get(_frame_for(layer, t), layer.w, layer.h)
            canvas.alpha_composite(im, (layer.x, layer.y))
            return
        if layer.path is not None:
            im = cache.get(layer.path, layer.w, layer.h)
            canvas.alpha_composite(im, (layer.x, layer.y))
            return
        if layer.text:
            # Data does not boil. `dx, dy` stay for the drawing helpers'
            # signatures; they are zero and the row is placed once.
            dx = dy = 0
            if "\t" in layer.text:
                _draw_columns(canvas, layer, dx, dy, ink, lost)
                return
            # How many lines the SLOT holds, not a guess. A kit slot is a
            # declared box of a known height; hardcoding two lines lost the
            # tail of every row that needed three.
            size_px = max(int(layer.h * 0.34), 14)
            fill_lines = max(1, int(layer.h / (size_px * 1.18)))
            *_box, dropped = mk.draw_block(
                canvas, layer.text,
                (layer.x + dx, layer.y + dy, layer.w, layer.h),
                font_name=DISPLAY_FONT if layer.lit else BODY_FONT,
                size_px=size_px,
                color=ink if layer.lit else mk.MUTED,
                max_lines=fill_lines, halign="center", valign="center",
                min_px=_type_floor(canvas))
            if dropped and lost is not None:
                lost[layer.name] = dropped
        return

    if layer.kind == "text":
        colour = mk.PALETTE.get(layer.slot or "ink", ink)
        if (layer.slot or "ink") == "ink":
            colour = ink
        reveal = 1.0
        if layer.reveal_s > 0:
            reveal = mk.ease_out(min((t - layer.t_start) / layer.reveal_s, 1.0))
        *_box, dropped = mk.draw_block(
            canvas, layer.text,
            (layer.x, layer.y, layer.w, layer.h),
            font_name=mk.face_for(layer.size_fh),
            size_px=max(int(layer.size_fh * canvas.height), 12),
            color=colour, max_lines=layer.max_lines,
            halign=layer.halign, valign="top", reveal=reveal,
            min_px=_type_floor(canvas))
        if dropped and lost is not None:
            lost[layer.name] = dropped
        return

    if layer.kind == "mark":
        # Seeded on the boil frame, so the mark is genuinely redrawn rather
        # than nudged: the same principle the plates were baked on.
        rng = mk.rng_for(layer.name, _boil_index(layer, t))
        d = ImageDraw.Draw(canvas)
        box = (layer.x, layer.y, layer.x + layer.w, layer.y + layer.h)
        if layer.slot == "ring":
            mk.scribble_ring(d, box, rng, color=mk.RED,
                             width=max(4, canvas.width // 200))
        elif layer.slot == "underline":
            mk.underline(d, box, rng, color=ink,
                         width=max(4, canvas.width // 240))
        elif layer.slot == "arrow-down":
            mk.arrow_down(d, box, rng, color=mk.RED,
                          width=max(5, canvas.width // 180))
        elif layer.slot == "cross":
            mk.cross(d, box, rng, color=mk.RED,
                     width=max(5, canvas.width // 180))
        else:
            mk.drawn_rect(d, box, rng, width=max(3, canvas.width // 260),
                          color=ink, jitter=2.0, overshoot=0.02)
        return


def render_frames(result: BuildResult, register: str, resolver: ShortResolver,
                  duration: float, out_video: Path, settings) -> Path:
    """Compose every frame and pipe it into the encoder."""
    w, h = result.frame
    n = max(int(round(duration * FPS)), 1)
    cache = _Cache()
    profile = encode_profile(settings, "short")

    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
           "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{w}x{h}",
           "-r", str(FPS), "-i", "-",
           "-an", "-c:v", "libx264", "-preset", getattr(profile, "preset", "medium"),
           "-crf", str(getattr(profile, "crf", 20)),
           "-pix_fmt", "yuv420p", str(out_video)]
    out_video.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE)
    assert proc.stdin is not None

    ordered = sorted(result.layers, key=lambda l: (l.z, l.t_start))
    lost: dict[str, int] = {}
    try:
        for i in range(n):
            t = i / FPS
            canvas = Image.new("RGBA", (w, h), mk.PAPER)
            for layer in ordered:
                if layer.t_start - 1e-6 <= t < layer.t_end:
                    _draw_layer(canvas, layer, t, cache, register, resolver,
                                lost)
            proc.stdin.write(canvas.tobytes())
    finally:
        proc.stdin.close()
        err = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
        rc = proc.wait()
    if rc != 0:
        raise RenderError(f"encode failed ({rc}): {err[-800:]}")
    render_frames.last_text_overflow = dict(lost)     # type: ignore[attr-defined]
    return out_video


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def render_short(script, tts, workspace: Path, settings, *,
                 content=None, prices=None, proof: bool = False,
                 out_name: str = "short_final.mp4",
                 format_name: str = "short",
                 resolver=None, anchors=None) -> tuple[Path, Path]:
    """Render the SHORT. Returns `(mp4, manifest)`.

    Interpolated word timings must never be the master clock of a published
    cut, so draft audio cannot make a FINAL. A PROOF is the deliberate
    exception: it exists to be looked at and never delivered.
    """
    if not proof and getattr(tts, "draft", False):
        raise RenderError(
            f"refusing to render a SHORT from {tts.tier} draft audio — its "
            f"word timings are interpolated. Approve the script so the paid "
            f"voice runs first.")

    workdir = Path(workspace) / "render_short"
    workdir.mkdir(parents=True, exist_ok=True)

    register = pick_register(script.content_sha())
    kit = kit_for(register)
    # Which template, by name. This is the whole of what the engine needed to
    # carry three formats instead of one — there is no per-format branch
    # anywhere below, and a fourth format is a JSON file and this argument.
    fmt: Format = load_format(format_name)
    # BEATS and SHOTS are different counts and both matter. A beat is an idea
    # the format has; a shot is a frame. A chapter-based format's beats are
    # its CHAPTERS; a shot-based one's are the shots it was authored with,
    # before a repeat expands them. Counted here, off the format actually
    # being rendered — re-reading the file at manifest time is a second parse
    # that can disagree with the first.
    n_beats = (len({sh.chapter_n for sh in fmt.shots if sh.chapter_n})
               or len(fmt))

    words = list(getattr(tts, "words", []) or [])
    duration = float(getattr(tts, "duration_s", 0.0) or 0.0)
    if duration <= 0:
        raise RenderError("the audio has no duration; there is no clock to cut to")

    # Prices before the resolver: the resolver holds them, and a resolver
    # built with None leaves THE MOVE's chart slot unfilled.
    # `get_price_history` never raises — worst case is a labelled synthetic
    # series — so the slot is always fillable.
    if prices is None:
        from pipeline.prices import get_price_history
        prices = get_price_history(getattr(script, "ticker", ""), settings)

    handle0 = getattr(settings, "brand_handle", "") or ""
    if resolver is None:
        resolver = ShortResolver(script=script, workdir=workdir,
                                 settings=settings, prices=prices,
                                 handle=handle0)
    else:
        resolver.workdir, resolver.prices = workdir, prices
        resolver.handle = resolver.handle or handle0

    # A shot the script carries no words for is DROPPED, not rendered blank.
    # THE TURN is one sentence on bare ground; with no sentence it is a held
    # empty frame, which is the exact failure this rewrite exists to remove.
    # A sequence repeat becomes one shot per item BEFORE anything is timed:
    # how many numbers beats a video has is a fact about its script.
    probe = resolver if resolver is not None else resolver_probe(script, settings)
    fmt = expand_sequences(fmt, probe.list_for)
    fmt, dropped = prune_empty_shots(fmt, probe)

    spans = resolve_spans(fmt, words, duration,
                          anchors if anchors is not None
                          else build_anchors(script))
    spans = cap_one_shots(spans, kit, register)



    # The LONG travels: light, clutter, the wall and the clock advance across
    # it. A 70-second vertical has nowhere to go, and says so in its template.
    result = build_layers(fmt, spans, resolver, kit, register,
                          progression=fmt.progression)

    # A composition that breaks its own rules never reaches an encoder. This
    # is the check that the last renderer did not have: it shipped a 12.5s
    # still frame and a disclaimer printed twice, under a green suite.
    # The host rule applies to the shots that are actually in this cut, and
    # WHICH shots those are is a property of the template rather than of this
    # module — three formats put the host in three different places.
    present = {sp.shot.id for sp in spans}
    problems = check_invariants(
        fmt, result,
        host_shots=[sh.id for sh in fmt.shots
                    if sh.host and sh.id in present])
    if problems:
        raise RenderError(
            "the composition breaks its own invariants:\n  "
            + "\n  ".join(problems[:20]))

    # A line that does not fit is a script the renderer cannot express. It
    # stops here, named, before a frame is drawn — not silently shortened on
    # the way to the screen.
    over = check_budgets(fmt, result)
    if over:
        raise RenderError(
            "the script does not fit the shots it is written for:\n  "
            + "\n  ".join(over))

    silent = workdir / "video_silent.mp4"
    render_frames(result, register, resolver, duration, silent, settings)
    overflow = getattr(render_frames, "last_text_overflow", {}) or {}

    out = Path(workspace) / out_name
    audio = getattr(tts, "audio_path", None)
    if audio and Path(audio).exists():
        run_ffmpeg(["-y", "-i", str(silent), "-i", str(audio),
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
                    "-shortest", str(out)])
    else:
        silent.replace(out)

    manifest_path = Path(workspace) / f"{Path(out_name).stem}.manifest.json"
    manifest_path.write_text(json.dumps({
        "ticker": script.ticker,
        "format": fmt.name,
        # "Who it hits" is one beat told across four shots because four cards
        # cannot share a frame legibly — so a nine-beat format cutting to
        # fourteen shots is the design working, not drift. Reporting
        # post-expansion shots as beats made the long look like 38 ideas
        # instead of nine.
        "beats": n_beats,
        "shots_count": len(spans),
        "anchored_shots": sum(1 for sp in spans if sp.anchored),
        "register": register,
        "duration_s": round(duration, 3),
        "frame": {"w": result.frame[0], "h": result.frame[1]},
        "shots": [{
            "id": s.shot.id,
            "plate": s.shot.plate,
            "start_s": round(s.start, 3),
            "end_s": round(s.end, 3),
            "anchored": s.anchored,
            "max_hold_s": s.shot.max_hold_s,
            "layers": [l.name for l in result.for_shot(s.shot.id)],
        } for s in result.spans],
        "layers": len(result.layers),
        # What the render actually reached. Under the tag model this was an
        # emergent accident and a SHORT once reached 4% of its own library;
        # under the templates it is a property of the twelve shots, and it is
        # recorded so it stays visible rather than being rediscovered.
        "kit_assets_used": sorted({l.entry_key for l in result.layers
                                   if l.entry_key}),
        "kit_reach": (
            f"Kit: {len({l.entry_key for l in result.layers if l.entry_key})} "
            f"entries in {register}, "
            f"{len({l.concept for l in result.layers if l.concept})} concepts, "
            f"{sum(1 for l in result.layers if len(l.frames) > 1)} animated "
            f"layers"),
        "skipped": result.skipped,
        "dropped_shots": dropped,
        # Characters that did not fit even at the readability floor. Non-empty
        # means a script said more than its shot can hold, and the words were
        # cut. Under the writing form this is what a character budget prevents.
        "text_overflow": overflow,
        "longest_layer_hold_s": round(
            max((b - a for a, b, _ in held_layer_spans(result)), default=0.0), 3),
    }, indent=1), encoding="utf-8")

    return out, manifest_path
