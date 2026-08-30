"""Render a SHORT from a shot template and the audio clock.

The old renderer chose its own composition from tags in the script and ran to
1,930 lines doing it. This one chooses nothing. `templates/shots/short.json`
fixes space and order, the word timestamps fix duration, and everything here
is the machinery between those two facts and a file on disk.

Every plate comes from the v2 registry and every line of copy goes into a slot
that plate declares. There is no second kit and no register to pick: the
renderer places the plate and says what goes in it, and the kit decides the
face, the size, the weight and the colour role.

Frames are composed in memory and piped straight into the encoder — 2,000
uncompressed 1080x1920 frames is not something to put on a disk on the way
past — and the captions are burned after, from the same phrase builder the
LONG uses.
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
from pipeline.plates import load_plates
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
        if parts[0] == "chart":
            return self._chart_source(parts[1:])
        if parts[0] == "headline":
            # The band's kicker is what KIND of page this is, and the script
            # carries no source field. Naming it is honest; inventing an
            # outlet name would be the renderer writing copy.
            return "THE HEADLINE" if parts[1:] == ["kicker"] else None
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
        if field == "years":
            years = list(getattr(self.script, "years", []) or [])
            return ",".join(years) if years else None
        if field == "unit":
            return _unit_of(rows) or None
        if field == "headline_figure":
            return rows[0].values[-1] if rows else None
        if field == "headline_label":
            return rows[0].label if rows else None
        if field == "headline_kicker":
            years = list(getattr(self.script, "years", []) or [])
            return (years[-1] if years else None)

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
        if field == "figures":
            # A ROW, for the cell expansion — the same comma list a director
            # writes into a `[PLATE]` tag. The sheet's shared unit is said once
            # in the unit slot, so the figures themselves are bare.
            return ",".join(_bare(v, _unit_of(rows)) for v in r.values)

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

    def _chart_source(self, rest: list[str]) -> str | None:
        """The price chart, as the slots `charts/line-dense` declares.

        The plate reserves a `plot-area` and knows nothing about numbers; the
        series goes in as figures and the renderer draws a path THROUGH them.
        That is not the renderer computing anything — it is being handed one.
        """
        if not rest or self.prices is None:
            return None
        field = rest[0]
        series = _legible(self.prices)
        closes = [float(c) for c in getattr(series, "closes", []) or []]
        if not closes:
            return None
        labels = self._chart_labels()

        if field == "unit":
            return "Close, $"
        if field == "series":
            return ",".join(f"{c:.2f}" for c in closes)
        if field == "heads":
            got = [labels.get(f"head-{i + 1}") for i in range(4)]
            return ",".join(g for g in got if g) if any(got) else None
        if field == "axis":
            # Four y labels across the range the series actually covers. The
            # domain comes from the figures, not from a rounded guess at them.
            lo, hi = min(closes), max(closes)
            if hi <= lo:
                return None
            return ",".join(f"{lo + (hi - lo) * i / 3:.0f}" for i in range(4))
        return labels.get(f"mark-{field}") or labels.get(field)

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
        if which == "kicker":
            return "BOTH TRUE"
        # `structure/both-true` takes two STATEMENTS, not two stacked figures.
        # The plate wraps them itself in the face it declares, so a newline
        # here would be a second opinion about the line break.
        if which == "heavy":
            return f"{pick.label} is {pick.values[-1]} now."
        if which == "light":
            return f"It was {pick.values[0]}."
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

    def _chart_labels(self) -> dict[str, str]:
        """The period heads and the three marks the dense chart declares.

        Read off the series the caller supplied — the renderer never computes a
        figure, so these are the dates and closes it was handed, formatted.
        """
        if self.prices is None:
            return {}
        closes = list(self.prices.closes)
        dates = list(getattr(self.prices, "dates", []) or [])
        if not closes:
            return {}
        lo, hi = min(closes), max(closes)
        out: dict[str, str] = {
            "mark-high": f"{hi:,.2f}"[:7],
            "mark-low": f"{lo:,.2f}"[:7],
            "mark-last": f"{closes[-1]:,.2f}"[:7],
        }
        # Four heads on this plate, evenly spaced across the series.
        for i in range(4):
            j = min(int(i * (len(dates) - 1) / 3), len(dates) - 1) if dates else 0
            if dates:
                out[f"head-{i + 1}"] = str(dates[j])[-5:]
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
        from pipeline.chart import render_price_plate
        from pipeline.plates import load_plates

        reg = load_plates(self.settings.assets_dir)
        paths = []
        try:
            for i in range(BOIL_FRAMES):
                out = self.workdir / f"chart_price_f{i + 1:02d}.png"
                path, meta = render_price_plate(
                    reg, _legible(self.prices), out, self.settings,
                    aspect="9x16", seed=f"boil{i}",
                    slot_values=self._chart_labels())
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
    """Rendered plate frames, keyed by what makes them different.

    A plate WITH ITS VALUES IN IT is the unit here, not a PNG: `plate_frames`
    sets the type into the slots the kit declares, and doing that per output
    frame would set the same nine lines thirty times a second. Keyed on the
    plate, which boil frame, and the values — because two shots of one sheet
    differing only in which row is lit are two different pictures.
    """

    def __init__(self, settings, reg) -> None:
        self.settings = settings
        self.reg = reg
        self._drawn: dict[tuple, Image.Image] = {}
        self._sized: dict[tuple, Image.Image] = {}

    def plate(self, key: str, frame_i: int, values: dict[str, str],
              w: int, h: int) -> Image.Image | None:
        vkey = tuple(sorted(values.items()))
        sized_key = (key, frame_i, vkey, w, h)
        hit = self._sized.get(sized_key)
        if hit is not None:
            return hit

        drawn_key = (key, frame_i, vkey)
        img = self._drawn.get(drawn_key)
        if img is None:
            plate = self.reg.get(key)
            if plate is None:
                return None
            from pipeline.plate_frames import render_frame
            img = render_frame(plate, frame_i, dict(values), self.settings,
                               self.reg)
            # A plate that reserves a data region gets its series drawn through
            # the figures the SCRIPT wrote into it. Without this a charts/ or
            # cycles/ plate is a set of labels around an empty box.
            from pipeline.chart import draw_declared
            draw_declared(self.reg, plate, dict(values), img, seed=key)
            self._drawn[drawn_key] = img
        out = img if img.size == (w, h) else img.resize(
            (max(w, 1), max(h, 1)), Image.LANCZOS)
        self._sized[sized_key] = out
        return out

    def file(self, path: Path, w: int, h: int) -> Image.Image:
        key = ("file", str(path), 0, (), w, h)
        hit = self._sized.get(key)
        if hit is None:
            im = Image.open(path).convert("RGBA")
            if im.size != (w, h):
                im = im.resize((max(w, 1), max(h, 1)), Image.LANCZOS)
            self._sized[key] = hit = im
        return hit


def _frame_index(layer: Layer, t: float) -> int:
    """Which frame of an animated layer is showing at `t`.

    fps and playback come from the plate the layer was built from — a room
    boils at 2, a talk strip runs at 8, an idle at 4. Nothing here assumes a
    rate, and a static plate has one frame and no clock.
    """
    if layer.frame_count <= 1 or layer.fps <= 0:
        return 0
    i = int((t - layer.t_start) * layer.fps)
    return (i % layer.frame_count) if layer.loops \
        else min(i, layer.frame_count - 1)


def _host_strip(reg, layer: Layer, speaking: bool) -> tuple[str, int, bool]:
    """Which of a pose's three strips plays, and at what rate.

    A hold, a talk and an idle. He talks while there are words under him and
    idles when there are not — a mouth that keeps moving through silence is
    the thing that makes a rig look like a puppet rather than a person.
    """
    kind = "talk" if speaking else "idle"
    strip = reg.host_strip(layer.entry_key, kind)
    if strip is None:
        return layer.entry_key, layer.fps or 2, True
    return strip.key, int(strip.fps or 4), True


def _draw_layer(canvas: Image.Image, layer: Layer, t: float, cache: _Cache,
                *, reg, settings, speaking: bool, lost: dict[str, int]) -> None:
    """One layer, at one instant, onto the frame."""
    if layer.kind == "ground":
        return                                    # the canvas IS the ground

    if layer.kind in ("plate", "fill"):
        img = cache.plate(layer.entry_key, _frame_index(layer, t),
                          layer.values, layer.w, layer.h)
        if img is not None:
            canvas.alpha_composite(img, (layer.x, layer.y))
        return

    if layer.kind == "host":
        key, fps, loops = _host_strip(reg, layer, speaking)
        shown = Layer(name=layer.name, kind="host", shot_id=layer.shot_id,
                      t_start=layer.t_start, t_end=layer.t_end,
                      entry_key=key, frame_count=2, fps=fps, loops=loops)
        img = cache.plate(key, _frame_index(shown, t), {}, layer.w, layer.h)
        if img is not None:
            canvas.alpha_composite(img, (layer.x, layer.y))
        return

    if layer.kind == "media":
        if layer.path is None or not Path(layer.path).exists():
            return
        from pipeline.plate_frames import cover_into
        src = Image.open(layer.path).convert("RGBA")
        canvas.alpha_composite(cover_into(src, layer.w, layer.h),
                               (layer.x, layer.y))
        return

    if layer.kind == "text":
        _draw_text(canvas, layer, settings, reg, lost)
        return

    if layer.kind == "mark":
        from pipeline.rasters import fitted_mark, role
        art = fitted_mark(settings, max(layer.w, 1), max(layer.h, 1),
                          style=layer.slot or "underline-swipe",
                          color=role(settings, "attention"))
        if art is not None:
            canvas.alpha_composite(art, (layer.x, layer.y))
        return

    # captions are drawn by the caller, which is the only thing that has the
    # words and the clock together.


def _draw_text(canvas: Image.Image, layer: Layer, settings, reg,
               lost: dict[str, int]) -> None:
    """Type with no plate to put it in — a bare shot, or a repeated row.

    Everything else in this renderer sets type into a slot the kit declares,
    in the face and size the kit declares for it. This is the remainder: a
    line the format places itself, sized as a fraction of frame height.
    """
    from PIL import ImageDraw

    from pipeline import marks as mk

    draw = ImageDraw.Draw(canvas)
    want = max(int(round(layer.size_fh * canvas.height)), _type_floor(canvas))
    lines, font, size = mk.fit_lines(
        draw, layer.text, mk.face_for(layer.size_fh),
        max(layer.w, 1), max(layer.h, 1),
        size_px=want, max_lines=layer.max_lines,
        min_px=_type_floor(canvas))
    ink = (*reg.colour("structure"), 255)
    step = int(size * mk.LINE_LEADING)
    y = layer.y + max((layer.h - step * len(lines)) // 2, 0)
    for line in lines:
        w = draw.textlength(line, font=font)
        if layer.halign == "left":
            x = layer.x
        elif layer.halign == "right":
            x = layer.x + layer.w - w
        else:
            x = layer.x + (layer.w - w) / 2
        draw.text((x, y), line, font=font, fill=ink)
        y += step
    shown = " ".join(lines)
    if len(shown) < len(layer.text.strip()):
        lost[layer.name] = len(layer.text.strip()) - len(shown)


def _type_floor(canvas: Image.Image) -> int:
    """The smallest type any layer may shrink to: the readability floor.

    Type shrinks before it truncates, but it stops here — below this nothing
    can be read on a phone, and losing the words is then the lesser evil,
    provided it is said out loud.
    """
    from pipeline.shots import MIN_TYPE_FH
    return max(12, int(MIN_TYPE_FH * canvas.height))


def render_frames(result: BuildResult, resolver, duration: float,
                  out_video: Path, settings, *, reg, words=()) -> Path:
    """Compose every frame and pipe it into the encoder.

    Frames are composed in memory and go straight into ffmpeg — 2,000
    uncompressed 1080x1920 frames is not something to put on a disk on the
    way past.
    """
    from pipeline.host import speaking_spans

    w, h = result.frame
    n = max(int(round(duration * FPS)), 1)
    cache = _Cache(settings, reg)
    profile = encode_profile(settings, "short")
    paper = reg.colour("ground")

    # When he is talking, per host layer. Computed once: `speaking_spans` walks
    # the word list, and doing that per frame is the same answer 2,000 times.
    speech: dict[str, list[tuple[float, float]]] = {}
    for l in result.of_kind("host"):
        speech[l.name] = list(speaking_spans(list(words), l.t_start, l.t_end))

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
            canvas = Image.new("RGBA", (w, h), (*paper, 255))
            for layer in ordered:
                if not (layer.t_start - 1e-6 <= t < layer.t_end):
                    continue
                talking = any(a <= t < b for a, b in speech.get(layer.name, ()))
                _draw_layer(canvas, layer, t, cache, reg=reg, settings=settings,
                            speaking=talking, lost=lost)
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

    reg = load_plates(settings.assets_dir)
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

    result = build_layers(fmt, spans, resolver, reg,
                          aspect=fmt.aspect, seed=script.content_sha())

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
    over = check_budgets(fmt, result, reg)
    if over:
        raise RenderError(
            "the script does not fit the shots it is written for:\n  "
            + "\n  ".join(over))

    silent = workdir / "video_silent.mp4"
    render_frames(result, resolver, duration, silent, settings, reg=reg,
                  words=words)
    overflow = getattr(render_frames, "last_text_overflow", {}) or {}

    # Captions are BURNED, not drawn per frame: one phrase at a time, in the
    # same ink as everything else on the frame, from the same builder the LONG
    # uses. Drawing them into every one of two thousand frames sets the same
    # line thirty times a second for no reason.
    from pipeline.rasters import build_phrase_ass

    W, H = result.frame
    # ONLY THE SHOTS THAT ASKED FOR THEM. `captions: false` is how a template
    # says the type on this plate IS the line — the hook card sets its own hook
    # at 18 characters a line, and a caption of the same sentence underneath is
    # the same words twice. Burning the whole track ignored the flag, because
    # the flag lives per shot and a subtitle file does not.
    bands = [(l.t_start, l.t_end) for l in result.of_kind("caption")]
    spoken = [w for w in words
              if any(a <= float(getattr(w, "start", 0.0)) < b for a, b in bands)]
    ass = workdir / "captions.ass"
    ass.write_text(build_phrase_ass(
        spoken, settings=settings, play_res=(W, H),
        font_size=int(H * 0.030), margin_v=int(H * 0.13),
        margin_h=int(W * 0.10), max_words=5, max_chars=24,
        duration=duration), encoding="utf-8")
    if spoken:
        burned = workdir / "video_captioned.mp4"
        # The filter takes a PATH, and a Windows drive letter or a colon in a
        # workspace name is a filtergraph separator. Escaped the way libavfilter
        # asks rather than by hoping the path is plain.
        spec = str(ass).replace("\\", "/").replace(":", "\\:")
        run_ffmpeg(["-i", str(silent), "-vf", f"ass='{spec}'",
                    "-c:v", "libx264", "-preset", "medium",
                    "-crf", "20", "-pix_fmt", "yuv420p", str(burned)])
        silent = burned

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
        "kit": "v2-plates",
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
        "plates_used": result.plates_used,
        "kit_reach": (
            f"Kit: {len(result.plates_used)} of {len(reg)} plates, "
            f"{len({l.concept for l in result.layers if l.concept})} families, "
            f"{sum(1 for l in result.layers if l.moves)} animated layers"),
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
