"""Render a SHORT from a shot template and the audio clock.

The old renderer chose its own composition from tags in the script and ran to
1,930 lines doing it. This one chooses nothing. `templates/shots/short.json`
fixes space and order, the word timestamps fix duration, and everything here
is the machinery between those two facts and a file on disk.

Every plate comes from the v2 registry and every line of copy goes into a slot
that plate declares. There is no second kit and no register to pick: the
renderer places the plate and says what goes in it, and the kit decides the
face, the size, the weight and the colour role.

Frames are composed in memory and piped straight into a lossless encode —
2,000 uncompressed frames is not something to put on a disk on the way past —
and the captions are burned after, from the same phrase builder the LONG uses,
in the one lossy encode the short gets. The layout is the format's 1080x1920;
the file is drawn at `short_delivery_height` (1440x2560).
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

from pipeline import marks as mk
from pipeline.compose import (MEME_SRC, BuildResult, Layer, build_layers,
                              check_budgets, check_invariants,
                              held_layer_spans, placed_meme, plan_variants,
                              punch_in_slot)
from pipeline.plates import at_episode_hour, load_plates
from pipeline.models import ShortScript
from pipeline.render_common import RenderError, mix_under_picture, run_ffmpeg
from pipeline.sound import (Cut, Move, manifest_rows, measure_lufs,
                            normalises, placeholders_played, short_mix,
                            shot_tags, sound_summary)
from pipeline.shots import (Format, apply_order, beat_keys, choose_order,
                            draws_prices, expand_sequences, load_format,
                            order_by_marks, resolve_spans, voice_keys)

log = logging.getLogger(__name__)

FPS = 30
# The kit boils a data plate through three drawings at 3fps. Code-drawn
# artwork is drawn three times too, and plays at the rate of the plate it
# stands in for.
BOIL_FRAMES = 3
# THE HOST IS IN ONE VERTICAL SHOT, AND IT IS THE TURN.
#
# He was in three — the cold open, the payoff and the close — all at full
# figure in a wide room, which is the shot you use when the room is the point.
# The turn is the line the whole cut rests on and it was being told on bare
# ground with nobody in it. `host/close-up` is head and shoulders and it exists
# for exactly that beat.
#
# Which shots those are is a property of the TEMPLATE, not of this module —
# three formats put him in three different places — so this is read off the
# format rather than written down twice. tests/test_short_shots.py asserts the
# two agree.
def host_shots(fmt) -> tuple[str, ...]:
    """The ids of the shots this format puts the host in."""
    return tuple(sh.id for sh in fmt.shots if sh.host)


HOST_SHOTS = ("the-turn",)

_FIGURE = re.compile(r"^(-?)([$€£]?)([\d.,]+)([KMBT]?)(%?)$")


def _latest(row) -> str:
    """A row's most recent figure, skipping periods it leaves blank."""
    return next((str(v) for v in reversed(row.values) if str(v).strip()), "")


def _latest_index(row) -> int | None:
    """Which period a row's most recent figure is in, or None."""
    return next((k for k in range(len(row.values) - 1, -1, -1)
                 if str(row.values[k]).strip()), None)


# The `numbers.<field>.<row>` sources that draw ONE row as a card of its own
# (item 26), as `ShortResolver._metric_card` answers them.
_CARD_FIELDS = frozenset({"kicker", "title", "cell", "axis", "first",
                          "first_label", "last", "last_label", "change",
                          "since"})


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


# The day's move, as the writing prompt asks for it: `move_summary` LEADS with
# it, signed — "+34% today · 6× average volume". The sign is what the two move
# plates turn on. Each draws its arrow, so a figure is offered to one of them
# only when it says which way it went, and a summary that opens on words
# offers it to neither.
_MOVE_LEAD = re.compile(r"^\s*([+\-\u2212])\s?(\d[\d,]*(?:\.\d+)?)\s?%")


def move_lead(summary: str) -> tuple[str, str, str] | None:
    """`"+34% today · 6× average volume"` -> `("up", "+34%", "today · 6× average volume")`.

    None when the summary does not open on a signed percentage, or opens on
    a zero one — a flat day has no arrow to draw.
    """
    m = _MOVE_LEAD.match(summary or "")
    if not m or not float(m.group(2).replace(",", "")):
        return None
    way = "up" if m.group(1) == "+" else "down"
    rest = summary[m.end():].strip(" ·-—–,;:")
    return way, f"{m.group(1)}{m.group(2)}%", rest


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
    # Which format this resolver answers for. The meme picker reads a macro
    # print differently from a company's day; the renderer sets it.
    format_name: str = ""
    # THE OPERATOR'S WORKBOOK for this video (`CompanyData`), when the
    # workspace has one. `data.<card>.<slot>` reads a card it fills on its own
    # (`pipeline.short_data`); without it those cards are not fillable and the
    # rotation draws the script's.
    data: object | None = None
    # The content manager the LONG fetches its pictures through: a short's
    # pictures (item 34) come from the same chain and the same cache.
    content: object | None = None

    def __post_init__(self) -> None:
        self._images: dict[str, Path | list[Path] | None] = {}
        # The meme this short was given, once asked — kept so the manifest
        # can say which one and why, not only that a still was drawn.
        self.meme_choice = None

    @property
    def rows(self):
        """The metric rows, from whichever script this is.

        A SHORT carries them on the script. A LONG does not — its numbers
        come from the data export — so this is read through, not reached for.
        """
        return list(getattr(self.script, "numbers", []) or [])

    # -- text -------------------------------------------------------------
    def text_for(self, src: str) -> str | None:
        if "|" in src:
            # `a|b`: the first alternative that says something. How a card
            # prints the writer's source for its beat where there is one and
            # its own line where there is not.
            for alt in src.split("|"):
                got = self.text_for(alt.strip())
                if got is not None and str(got).strip():
                    return got
            return None
        parts = src.split(".")
        if parts[0] == "channel":
            return self.handle or None
        if parts[0] == "source":
            # The writer's `sources` line for a beat. A plate with a source
            # line of its own gets no slide-in tag, so this is the only way
            # the writer's source reaches the screen on one.
            got = (getattr(self.script, "sources", None) or {}).get(
                ".".join(parts[1:]))
            return got or None
        if parts[0] == "compare":
            return self._compare(parts[1])
        if parts[0] == "numbers":
            return self._numbers(parts[1:])
        if parts[0] == "chart":
            return self._chart_source(parts[1:])
        if parts[0] == "wrap":
            return self._wrapped(parts[1:])
        if parts[0] == "data":
            return self._data(parts[1:])
        if parts[0] == "sent":
            return self._sentence(parts[1:])
        if parts[0] == "news":
            return self._news(parts[1:])
        if parts[0] == "pic":
            return self._picture_line(parts[1:])
        if parts[0] == "fred":
            return self._fred(parts[1:])
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

    def _data(self, rest: list[str]) -> str | None:
        """`data.<card>.<slot>`: a card the workbook fills on its own."""
        from pipeline.short_data import CARDS

        if not rest or self.data is None or rest[0] not in CARDS:
            return None
        cache = self.__dict__.setdefault("_cards", {})
        if rest[0] not in cache:
            try:
                cache[rest[0]] = CARDS[rest[0]](self.data, script=self.script)
            except Exception as e:                       # noqa: BLE001
                log.warning("the %s card could not be filled: %s", rest[0], e)
                cache[rest[0]] = None
        card = cache[rest[0]]
        if not card or len(rest) < 2:
            return None
        got = card.get(".".join(rest[1:]))
        return got if got not in (None, "") else None

    def _fred(self, rest: list[str]) -> str | None:
        """`fred.<slot>`: the official series behind a macro print (item 6),
        off FRED, for `charts/macro-series`."""
        from pipeline import macro_series

        if not rest:
            return None
        if "_fred_card" not in self.__dict__:
            try:
                self.__dict__["_fred_card"] = macro_series.card(
                    self.script, self.settings)
            except Exception as e:                       # noqa: BLE001
                log.warning("the macro series could not be read: %s", e)
                self.__dict__["_fred_card"] = None
        card = self.__dict__["_fred_card"] or {}
        return card.get(".".join(rest)) or None

    def _session(self, rest: list[str]) -> str | None:
        """`chart.session.<slot>`: today's session against the prior close
        (item 4), for `charts/intraday`. None without a real session, or when
        the session disagrees with the move the writer narrates."""
        from pipeline.prices import get_intraday
        from pipeline.short_data import session_card

        if "_session_card" not in self.__dict__:
            try:
                self.__dict__["_session_card"] = session_card(
                    get_intraday(self.script.ticker, self.settings),
                    self.script)
            except Exception as e:                       # noqa: BLE001
                log.warning("the session chart could not be filled: %s", e)
                self.__dict__["_session_card"] = None
        card = self.__dict__["_session_card"] or {}
        return card.get(".".join(rest)) or None

    def _news(self, rest: list[str]) -> str | None:
        """The news beat's own material (item 5).

        `news.release.<slot>`: the release the video is about, opened from
        the News sheet's link (`pipeline.news_page.release_card`).
        `news.wire.<n>.<chars>.<i>.<slot>`: row `i` of the `n` latest
        headlines cut to `chars`; `news.wire.kicker` the strip's heading.
        """
        from pipeline import news_page

        if not rest or self.data is None:
            return None
        cache = self.__dict__.setdefault("_news_cache", {})
        if rest[0] == "release":
            if "release" not in cache:
                try:
                    cache["release"] = news_page.release_card(
                        self.data, self.script, self.settings)
                except Exception as e:                   # noqa: BLE001
                    log.warning("the release could not be read: %s", e)
                    cache["release"] = None
            card = cache["release"] or {}
            return (card.get(rest[1]) or None) if len(rest) > 1 else None
        if rest[0] != "wire" or len(rest) < 2:
            return None
        if rest[1] == "kicker":
            t = str(self.data.get("ticker") or self.script.ticker or "").upper()
            return f"{t} · the latest wires" if t else "the latest wires"
        try:
            n, chars, i = int(rest[1]), int(rest[2]), int(rest[3])
            slot = rest[4]
        except (IndexError, ValueError):
            return None
        key = f"wire.{n}.{chars}"
        if key not in cache:
            cache[key] = news_page.wire_rows(self.data, n, chars)
        rows = cache[key]
        if not rows or i >= len(rows):
            return None
        return rows[i].get(slot) or None

    def _picture(self, what: str):
        """The picture for `what` (item 34), as the content chain resolved it,
        or None. A filler card is none: a frame around "imagery unavailable"
        is a broken drawing, and the beat keeps its card instead."""
        pics = self.__dict__.setdefault("_pictures", {})
        if what in pics:
            return pics[what]
        got = None
        if what == "company" and self.content is not None:
            name = str((self.data.get("company_name") if self.data is not None
                        else "") or "").strip()
            site = str(self.data.get("website") or "") if self.data is not None else ""
            for query in ([f"{name} store", f"{name} headquarters", name]
                          if name else []):
                try:
                    v = self.content.resolve_image(query, kind="img",
                                                   website=site)
                except Exception as e:                   # noqa: BLE001
                    log.warning("picture %r failed: %s", query, e)
                    continue
                if v is not None and v.source != "filler" and v.path:
                    got = v
                    break
        pics[what] = got
        return got

    # Who a picture came from, as its frame's source line says it.
    _PICTURE_SOURCES = {"wikimedia": "Photo: Wikimedia Commons",
                        "company_site": "Photo: the company's website",
                        "pexels": "Photo: Pexels",
                        "mock": "Photo: stand-in (mock mode)"}

    def _picture_line(self, rest: list[str]) -> str | None:
        """`pic.company.caption` / `pic.company.source`: the words under a
        picture, only when there is a picture."""
        if len(rest) < 2 or self._picture(rest[0]) is None:
            return None
        v = self._picture(rest[0])
        if rest[1] == "source":
            return self._PICTURE_SOURCES.get(v.source, "Photo: " + v.source)
        if rest[1] == "caption" and self.data is not None:
            name = str(self.data.get("company_name") or "").strip()
            what = str(self.data.get("industry") or "").strip().lower()
            return f"{name} · {what}" if name and what else (name or None)
        return None

    def attributions(self) -> list[str]:
        """The credit lines for every picture this short drew."""
        out = []
        for v in (self.__dict__.get("_pictures") or {}).values():
            if v is not None and getattr(v, "attribution", ""):
                out.append(v.attribution)
        return out

    def _sentence(self, rest: list[str]) -> str | None:
        """`sent.3.0.script.conclusion`: sentence 0 of a text that has exactly
        three. A card that sets a passage one line a slot is only right for a
        passage with that many lines; anything else leaves the first slot
        empty, which makes the card unfillable, and the rotation takes a card
        drawn for one line (item 25)."""
        try:
            want, i = int(rest[0]), int(rest[1])
        except (IndexError, ValueError):
            return None
        text = self.text_for(".".join(rest[2:]))
        if not text:
            return None
        parts = [s.strip() for s in re.split(r"(?<=[.!?])\s+", " ".join(str(text).split()))
                 if s.strip()]
        if len(parts) != want or i >= len(parts):
            return None
        return parts[i]

    def _wrapped(self, rest: list[str]) -> str | None:
        """`wrap.34.4.0.script.consequences.1`: line 0 of that text broken at
        34 characters, for a plate that sets a passage as separate lines, one
        slot a line (design's short-quote). None for a line past the end, and
        for every line when the text needs more lines than the plate has: the
        first line is a required bind, so the plate is then not fillable and
        the rotation takes another rather than cutting the passage short."""
        import textwrap

        try:
            width, most, i = int(rest[0]), int(rest[1]), int(rest[2])
        except (IndexError, ValueError):
            return None
        text = self.text_for(".".join(rest[3:]))
        if not text or not str(text).strip():
            return None
        lines = textwrap.wrap(" ".join(str(text).split()), width=width,
                              break_long_words=False)
        if not lines or len(lines) > most or i >= len(lines):
            return None
        return lines[i]

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
        if field in ("headline_figure", "headline_label", "headline_kicker",
                     "headline_context", "headline_title"):
            # THE ROW THE VERDICT TURNS ON (item 2): the one the writer names
            # in `payoff_row`, else the first, as it always was.
            from pipeline.short_data import row_for
            row = row_for(self.script, getattr(self.script, "payoff_row", None))
            row = row or (rows[0] if rows else None)
            if row is None:
                return None
            years = list(getattr(self.script, "years", []) or [])
            at = _latest_index(row)
            if field == "headline_figure":
                return row.values[at] if at is not None else None
            if field == "headline_label":
                return row.label
            if field == "headline_kicker":
                return years[at] if at is not None and at < len(years) else None
            if field == "headline_title":
                when = years[at] if at is not None and at < len(years) else ""
                return f"{row.label}, {when}" if when else row.label
            return self._since(row, years)
        if field == "head":
            years = list(getattr(self.script, "years", []) or [])
            i = int(rest[0]) if rest and rest[0].isdigit() else -1
            return years[i] if 0 <= i < len(years) else None

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
        if field in _CARD_FIELDS:
            return self._metric_card(field, r, rest[1:])
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

    def _since(self, row, years: list[str]) -> str | None:
        """`from $400M in FY21`: where a row started, for a card that shows
        where it is now."""
        first = next((k for k, v in enumerate(row.values) if str(v).strip()), None)
        last = _latest_index(row)
        if first is None or last is None or first == last:
            return None
        when = years[first] if first < len(years) else ""
        return f"from {row.values[first]} in {when}" if when else f"from {row.values[first]}"

    def _metric_card(self, field: str, row, rest: list[str]) -> str | None:
        """One row as a card of its own (item 26): its bars, its axis, where it
        started and where it is.

        `cell.k` is period k's figure as printed; `axis.k` the k-th gridline
        from the bottom, on the scale of the printed figures; `change` how far
        it moved from its first figure to its last (points for a rate, and
        nothing across zero, where a percentage means nothing).
        """
        from pipeline import short_data as sd

        years = list(getattr(self.script, "years", []) or [])
        k = int(rest[0]) if rest and rest[0].isdigit() else None
        first = next((j for j, v in enumerate(row.values) if str(v).strip()), None)
        last = _latest_index(row)
        figs = [sd.parse_figure(v) for v in row.values]
        wb_field = sd.field_for(row.label, getattr(row, "field", None))
        if field == "kicker":
            return row.label.upper()
        if field == "title":
            span = (f"{years[first]} to {years[last]}"
                    if first is not None and last is not None
                    and last < len(years) and first != last else "")
            return f"{row.label}, {span}" if span else row.label
        if field == "cell":
            if k is None or k >= len(row.values):
                return None
            return str(row.values[k]).strip() or None
        if field == "axis":
            present = [f for f in figs if f is not None]
            if k is None or len(present) < 2:
                return None
            ticks = sd.axis_ticks(present)
            if k >= len(ticks):
                return None
            like = next((v for v in row.values if str(v).strip()), "")
            return sd.tick_label(wb_field, ticks[k], like)
        if field in ("first", "first_label", "last", "last_label"):
            at = first if field.startswith("first") else last
            if at is None or (first == last):
                return None
            if field.endswith("_label"):
                return years[at] if at < len(years) else None
            return str(row.values[at]).strip() or None
        if field == "change":
            if first is None or last is None or first == last:
                return None
            if wb_field:
                return sd.change(wb_field, figs[first], figs[last])
            rate = str(row.values[last]).strip().endswith("%")
            return sd.change("gross_margin" if rate else "revenue",
                             figs[first], figs[last])
        if field == "since":
            return self._since(row, years)
        return None

    def _chart_source(self, rest: list[str]) -> str | None:
        """The price chart, as the slots `charts/line-dense` declares.

        The plate reserves a `plot-area` and knows nothing about numbers; the
        series goes in as figures and the renderer draws a path THROUGH them.
        That is not the renderer computing anything — it is being handed one.
        """
        if not rest:
            return None
        field = rest[0]
        if field == "session":
            return self._session(rest[1:])
        # THE MOVE, which is the writer's figure and needs no price data: a
        # short with no prices loaded still has one, in its move summary.
        if field in ("move_up", "move_down", "move_detail"):
            lead = move_lead(str(getattr(self.script, "move_summary", "") or ""))
            if lead is None:
                return None
            way, figure, detail = lead
            if field == "move_detail":
                return detail or None
            return figure if field == f"move_{way}" else None
        # THE MOVE IN FRAME ONE (item 6): the hook card's own `move` slot takes
        # the signed figure in either direction, where it counts up while the
        # first sentence is spoken, and its `sub` line takes the rest of the
        # summary. A summary that does not open on a signed move leaves the
        # slot empty and keeps the whole summary in the sub line, as before.
        if field in ("move", "move_rest"):
            summary = str(getattr(self.script, "move_summary", "") or "").strip()
            lead = move_lead(summary)
            if field == "move":
                return lead[1] if lead else None
            return (lead[2] if lead else summary) or None
        if self.prices is None:
            return None
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
                    or (_latest(rows[0]) if rows else None))
        if which == "expected":
            return getattr(self.script, "expected", None)
        if which == "print_label":
            # WHAT THE PRINT IS, only when the sheet says so: the row whose
            # latest figure is the reported one. It used to be the sheet's
            # first row whatever the print was, so an earnings short put an
            # EPS beat of $1.42 on screen labelled "Revenue", under "LTM".
            # No row matching leaves the label empty; the caption carries the
            # move summary, which says what printed.
            reported = (getattr(self.script, "reported", None) or "").strip()
            for r in rows:
                if reported and _latest(r).strip() == reported:
                    return r.label
            return None
        if which == "guidance_label":
            return "Guidance"
        pick = None
        for r in rows:
            # BY WORD. "pe" as a substring picked "Operating income" as the
            # video's multiple.
            lab = r.label.lower()
            if re.search(r"(?<![a-z])(p/e|pe|p/s|p/b|p/fcf|multiple|ev/\w*|price)(?![a-z])", lab):
                pick = r
                break
        pick = pick or (rows[0] if rows else None)
        if pick is None:
            return None
        if which == "kicker":
            return "BOTH TRUE"
        if which == "expected_label":
            return "Expected"
        if which == "reported_label":
            return "Reported"
        # `structure/both-true` takes two STATEMENTS, not two stacked figures.
        # The plate wraps them itself in the face it declares, so a newline
        # here would be a second opinion about the line break.
        #
        # From the FIGURES THE ROW HAS. A row is six periods wide and may
        # leave its early ones blank (a macro series with four years of
        # history, an earnings sheet from FY22), and the first period was
        # taken whatever it held: "It was ." on the earnings and macro cut.
        # With fewer than two figures there is no then-and-now to state, and
        # the beat takes its other plate or none.
        figures = [v for v in pick.values if str(v).strip()]
        if which in ("heavy", "light") and len(figures) < 2:
            return None
        if which == "heavy":
            return f"{pick.label} is {figures[-1]} now."
        if which == "light":
            return f"It was {figures[0]}."
        return None

    # -- images -----------------------------------------------------------
    def image_for(self, src: str) -> Path | list[Path] | None:
        if src in self._images:
            return self._images[src]
        out = None
        if src == "chart.price":
            out = self._chart()
        elif src == MEME_SRC:
            out = self.meme().path
        elif src.startswith("plate."):
            out = None       # nested plates resolve through the kit, not here
        elif src.startswith("photo."):
            v = self._picture(src.split(".", 1)[1])
            out = Path(v.path) if v is not None else None
        self._images[src] = out
        return out

    def meme(self):
        """The one meme this short gets from the owned library, or none.

        Asked only when the template has a place for one, and answered once.
        The proof and the final of a video seed the pick with the same
        script hash, so they show the same meme unless another video went
        out between them and used it.

        The rotation reads every workspace but this one. `workdir` is this
        workspace's `render_short/`, and a final that read the manifest its
        own proof wrote would steer off the meme the proof showed.
        """
        if self.meme_choice is None:
            from pipeline.memes import choose_for_short, recent_memes

            lead = move_lead(getattr(self.script, "move_summary", "") or "")
            self.meme_choice = choose_for_short(
                self.script, self.settings,
                fmt=self.format_name or "short",
                direction=lead[0] if lead else "",
                seed=self.script.content_sha(),
                avoid=recent_memes(self.settings,
                                   exclude=Path(self.workdir).parent))
        return self.meme_choice

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
                path, _meta = render_price_plate(
                    reg, _legible(self.prices), out, self.settings,
                    aspect="9x16", seed=f"boil{i}",
                    slot_values=self._chart_labels())
                paths.append(path)
        except Exception:                                    # noqa: BLE001
            return None
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
        # Each later row's card listens for its own name (item 26), so it
        # comes up as that row is read rather than on an even share. In a
        # MARKED script only where the name is said inside the numbers beat:
        # a row first named after the next marker is talked about in another
        # beat, and a card that waited for it would push that beat's own
        # shot off its marker.
        inside = _beat_text(script, "numbers")
        for i, row in enumerate(script.numbers[1:], start=1):
            if inside is None or row.label.lower() in inside:
                out[f"numbers.{i}"] = row.label
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
    # A MARKED BEAT LISTENS FOR THE WORDS SPOKEN RIGHT AFTER ITS MARKER. A
    # field is what goes ON the plate, and the writer rarely says it aloud
    # word for word — `move_summary` is "+29% today · 5x average volume",
    # which no narration contains — so a shot listening for its field found
    # nothing and was shared out evenly with its neighbours. The marker is the
    # writer saying where the beat starts; what follows it is what is heard.
    for mark in getattr(script, "beat_marks", None) or ():
        heard = script.words_after_mark(mark.key)
        if len(heard.split()) >= 2:
            out[mark.key] = heard
    return out


def _beat_text(script, key: str) -> str | None:
    """What a marked beat says, lower-cased, from its marker to the next; None
    when the script does not mark that beat."""
    marks = sorted(getattr(script, "beat_marks", None) or (),
                   key=lambda m: m.char_offset)
    for i, m in enumerate(marks):
        if m.key == key:
            end = marks[i + 1].char_offset if i + 1 < len(marks) else None
            return script.audio_script[m.char_offset:end].lower()
    return None


def marked_beats(script, fmt: Format) -> list[str]:
    """The beats the script marks that this format can cut, in spoken order.

    A marker for a beat this format does not have — a macro key in a script
    rendered as a plain short — orders nothing and is left out.
    """
    order = getattr(script, "beat_order", None)
    if order is None:
        return []
    keys = set(beat_keys(fmt))
    return [k for k in order() if k in keys]


def shot_sources(script, fmt: Format) -> dict[str, str]:
    """The writer's `sources`, from the beat each names to the shot playing it.

    A beat's key is its shot's anchor, so `numbers_comment` is the shot
    `the-comment`. A split beat's close-up finds its source through the wide
    part it belongs to, and the tag goes under whichever part plays first.
    """
    got = getattr(script, "sources", None) or {}
    return {sh.id: got[sh.anchor] for sh in fmt.shots
            if sh.anchor and sh.anchor in got}


def _sound_tags(result, reg, shot_id: str) -> set[str]:
    """What the room under a shot should sound like: the room loops its
    plates' frames play (rain in the window, the screen's flicker) and the
    season they are dressed for."""
    keys, loops, seasons = [], [], []
    for layer in result.for_shot(shot_id):
        if not layer.entry_key:
            continue
        keys.append(layer.entry_key)
        plate = reg.get(layer.entry_key)
        if plate is not None:
            loops += list(getattr(plate, "loops", ()) or ())
            seasons.append(getattr(plate, "season", "") or "")
    return shot_tags(keys, loops, seasons)


def _part_fields(shot) -> dict:
    """`part` and `part_of` for a manifest entry, or nothing for a whole shot."""
    if not getattr(shot, "part", 0):
        return {}
    out = {"part": shot.part}
    if shot.part_of:
        out["part_of"] = shot.part_of
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
        # BY THE PICTURE, NOT THE INDEX. A room's twelve-frame loop shows two
        # or three pictures, and keyed by index it held twelve decoded 4K
        # copies of them — half a gigabyte for one room shot.
        frame = self._frame_file(key, frame_i)
        sized_key = (key, frame, vkey, w, h)
        hit = self._sized.get(sized_key)
        if hit is not None:
            return hit

        drawn_key = (key, frame, vkey)
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

    def _frame_file(self, key: str, frame_i: int):
        """The file frame `frame_i` of `key` shows; the index if there is none."""
        plate = self.reg.get(key)
        if plate is None or not 0 <= frame_i < len(plate.frames):
            return frame_i
        return plate.frames[frame_i].png

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

    fps and playback come from the plate the layer was built from — a data
    plate boils at 3, a room loops at 12, a talk strip runs at 8, an idle at
    4. Nothing here assumes a rate, and a static plate has one frame and no
    clock.
    """
    if layer.frame_count <= 1 or layer.fps <= 0:
        return 0
    i = int((t - layer.t_start) * layer.fps)
    return (i % layer.frame_count) if layer.loops \
        else min(i, layer.frame_count - 1)


def _draw_layer(canvas: Image.Image, layer: Layer, t: float, cache: _Cache,
                *, reg, settings, face=None, lost: dict[str, int]) -> None:
    """One layer, at one instant, onto the frame.

    `face` is what a host layer shows at this instant — a strip and which of
    its frames, off :func:`pipeline.host.face_plan` — and nothing else reads
    it.
    """
    if layer.kind == "ground":
        return                                    # the canvas IS the ground

    if layer.kind in ("plate", "fill"):
        img = cache.plate(layer.entry_key, _frame_index(layer, t),
                          layer.values, layer.w, layer.h)
        if img is not None:
            canvas.alpha_composite(img, (layer.x, layer.y))
        return

    if layer.kind == "host":
        key, index = (face.key, face.index) if face is not None \
            else (layer.entry_key, 0)
        img = cache.plate(key, index, {}, layer.w, layer.h)
        if img is None and key != layer.entry_key:
            img = cache.plate(layer.entry_key, 0, {}, layer.w, layer.h)
        if img is not None:
            canvas.alpha_composite(img, (layer.x, layer.y))
        return

    if layer.kind == "front":
        # The desk he stands behind: the room's front layer, after him.
        if layer.path is not None and Path(layer.path).exists():
            canvas.alpha_composite(cache.file(Path(layer.path), layer.w,
                                              layer.h), (layer.x, layer.y))
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


# ONE LOSSY ENCODE, NOT TWO. The frames went to x264 at veryfast/CRF 20 and
# the captions were burned in a second pass at CRF 20: every picture was
# compressed twice, at 0.16 Mbit/s, and the dark ground came out blocky.
# (2 Oct 2026: "the video seems laggy and not quality".) The frames now go to
# a lossless file — still x264, so a held card costs nothing — in RGB, so
# the colour is converted once, in the final pass.
def lossless_args() -> tuple[str, ...]:
    """The encoder arguments for the frames' lossless file."""
    if _has_encoder("libx264rgb"):
        return ("-c:v", "libx264rgb", "-preset", "ultrafast", "-qp", "0",
                "-pix_fmt", "rgb24")
    return ("-c:v", "libx264", "-preset", "ultrafast", "-qp", "0",
            "-pix_fmt", "yuv444p")


_ENCODERS: dict[str, bool] = {}


def _has_encoder(name: str) -> bool:
    if name not in _ENCODERS:
        try:
            out = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"],
                                 capture_output=True, text=True, timeout=30).stdout
        except (OSError, subprocess.SubprocessError):
            out = ""
        _ENCODERS[name] = any(line.split()[1:2] == [name]
                              for line in out.splitlines() if line.strip())
    return _ENCODERS[name]


def delivery_scale(settings, frame: tuple[int, int], *, proof: bool = False) -> float:
    """Output pixels per layout pixel: `short_delivery_height` over the frame's.

    YouTube gives a 1440p upload a better encode than a 1080p one, and
    design's art is delivered at twice the canvas, so drawing the same layout
    at 1440x2560 costs no sharpness. A proof stays at the layout's size: it
    asks whether the type reads, and buys its speed back where it can.
    """
    want = int(getattr(settings, "short_delivery_height", 0) or 0)
    if proof or want <= frame[1]:
        return 1.0
    return want / frame[1]


def _even(v: float) -> int:
    return max(int(round(v / 2.0)) * 2, 2)


def delivered_size(frame: tuple[int, int], scale: float) -> tuple[int, int]:
    """The file's size for a layout `frame` drawn at `scale`."""
    if scale == 1.0:
        return frame
    return _even(frame[0] * scale), _even(frame[1] * scale)


def _scaled(layer: Layer, scale: float) -> Layer:
    """`layer` with its box in output pixels. Edges are rounded, not sizes,
    so two layers that met in the layout still meet."""
    if scale == 1.0:
        return layer
    from dataclasses import replace
    x0, y0 = int(round(layer.x * scale)), int(round(layer.y * scale))
    x1 = int(round((layer.x + layer.w) * scale))
    y1 = int(round((layer.y + layer.h) * scale))
    return replace(layer, x=x0, y=y0, w=x1 - x0, h=y1 - y0)


def final_encode(src: Path, out: Path, settings, *, captions: Path | None = None) -> Path:
    """The short's one lossy encode: the captions burned, the colour
    converted to BT.709 and tagged so, at `short_crf` with x264's
    `short_final_preset`.

    `-tune animation` and `aq-mode=3` are for what the short is: flat colour
    on a dark ground, where x264's defaults starve the dark and band it.
    """
    vf = []
    if captions is not None:
        # The filter takes a PATH, and a Windows drive letter or a colon in a
        # workspace name is a filtergraph separator. Escaped the way libavfilter
        # asks rather than by hoping the path is plain.
        spec = str(captions).replace("\\", "/").replace(":", "\\:")
        # THE KIT'S FONTS, BY DIRECTORY. The style names Archivo Narrow, which
        # no install puts on the system, and without `fontsdir` libass fell
        # back to DejaVu Sans: every short's captions were set in a face that
        # runs a line nearly twice as wide as the one they were placed for.
        # The LONG has always passed it (`render_common`).
        fonts = str(settings.fonts_dir).replace("\\", "/").replace(":", "\\:")
        vf.append(f"ass='{spec}':fontsdir='{fonts}'")
    vf.append("scale=out_color_matrix=bt709:out_range=tv,format=yuv420p")
    run_ffmpeg(["-i", str(src), "-vf", ",".join(vf), "-an",
                "-c:v", "libx264",
                "-preset", str(getattr(settings, "short_final_preset", "slow")),
                "-crf", str(getattr(settings, "short_crf", 17)),
                "-tune", "animation", "-x264-params", "aq-mode=3",
                "-colorspace", "bt709", "-color_primaries", "bt709",
                "-color_trc", "bt709", "-color_range", "tv", str(out)])
    return out


def render_frames(result: BuildResult, resolver, duration: float,
                  out_video: Path, settings, *, reg, words=(), plan=None,
                  scale: float = 1.0) -> Path:
    """Compose every frame and pipe it into the encoder.

    Frames are composed in memory and go straight into ffmpeg — 2,000
    uncompressed 1080x1920 frames is not something to put on a disk on the
    way past.

    `plan` is the move plan (`pipeline.moves.plan_short`): a plate with
    moves on it is drawn by the move compositor, and its source tags and
    wipes go over everything else on the frame. Without one, every plate is
    the still it always was.

    `scale` is how many output pixels each layout pixel gets
    (:func:`delivery_scale`). The layout is the format's frame and nothing
    in it moves; each layer is drawn at its box times `scale`, from design's
    art, which is delivered at twice the canvas.

    `out_video` is LOSSLESS (:func:`lossless_args`): the one lossy encode is
    :func:`final_encode`, after the captions.
    """
    from pipeline.host import face_plan, host_shot
    from pipeline.moves import MoveCompositor

    w, h = delivered_size(result.frame, scale)
    n = max(int(round(duration * FPS)), 1)
    cache = _Cache(settings, reg)
    mover = (MoveCompositor(plan, reg, settings, cache)
             if plan is not None and (plan.moves or plan.wipes or plan.tags)
             else None)
    paper = reg.colour("ground")

    # WHAT HIS FACE DOES, per host layer, planned once: which frame of which
    # strip is on screen at every output frame — the talk strip's open mouths
    # under words, the idle strip in silence, a blink every few seconds, and
    # on a close-up never the still. `face_plan` is the same call the long
    # makes, so the two lanes cannot disagree about a face.
    faces: dict[str, tuple[int, list]] = {}
    face_reports: dict[str, dict] = {}
    for l in result.of_kind("host"):
        shot = host_shot(reg, l.entry_key)
        if shot is None:
            continue
        plan, did = face_plan(shot, list(words), l.t_start, l.t_end, FPS,
                              seed=l.name)
        faces[l.name] = (int(round(l.t_start * FPS)), plan)
        face_reports[l.name] = did

    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
           "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{w}x{h}",
           "-r", str(FPS), "-i", "-", "-an", *lossless_args(), str(out_video)]
    out_video.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE)
    assert proc.stdin is not None

    ordered = [_scaled(l, scale)
               for l in sorted(result.layers, key=lambda l: (l.z, l.t_start))]
    lost: dict[str, int] = {}
    try:
        for i in range(n):
            t = i / FPS
            canvas = Image.new("RGBA", (w, h), (*paper, 255))
            for layer in ordered:
                if not (layer.t_start - 1e-6 <= t < layer.t_end):
                    continue
                if mover is not None and mover.owns(layer):
                    mover.draw_layer(canvas, layer, t, _frame_index(layer, t))
                    continue
                face = None
                if layer.name in faces:
                    first, strip = faces[layer.name]
                    face = strip[min(max(i - first, 0), len(strip) - 1)]
                _draw_layer(canvas, layer, t, cache, reg=reg, settings=settings,
                            face=face, lost=lost)
            if mover is not None:
                mover.draw_overlays(canvas, t, scale=scale)
            proc.stdin.write(canvas.tobytes())
    finally:
        proc.stdin.close()
        err = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
        rc = proc.wait()
    if rc != 0:
        raise RenderError(f"encode failed ({rc}): {err[-800:]}")
    render_frames.last_text_overflow = dict(lost)     # type: ignore[attr-defined]
    render_frames.last_faces = dict(face_reports)     # type: ignore[attr-defined]
    return out_video
# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _meme_record(resolver, result: BuildResult) -> dict:
    """The manifest's line for the meme: which, where, and on what — or why not."""
    layer = placed_meme(result)
    choice = getattr(resolver, "meme_choice", None)
    if layer is None:
        why = next((s.split(" <- ", 1)[1] for s in result.skipped
                    if ".meme <- " in s), "")
        if choice is not None and not choice and choice.why:
            why = choice.why
        out = {"key": None,
               "why": why or "the format has no place for a meme"}
        if choice:
            out["picked"] = choice.key       # chosen, and then no room for it
        return out
    frame = next((l.entry_key for l in result.for_shot(layer.shot_id)
                  if l.kind == "plate" and l.slot == MEME_SRC), "")
    return {
        "key": (choice.key if choice else "") or Path(layer.path).stem,
        "file": (choice.file if choice else "") or Path(layer.path).name,
        "source": "library",
        "shot": layer.shot_id,
        "start_s": round(layer.t_start, 3),
        "end_s": round(layer.t_end, 3),
        "frame": frame,
        "score": choice.score if choice else None,
        "matched": list(choice.matched) if choice else [],
        "why": choice.why if choice else "",
    }


def _provenance(script, settings, workspace: Path, duration: float,
                prices, tts, format_name: str, *, proof: bool,
                visual_sources: dict | None = None):
    """The render's provenance record (N3)."""
    from pipeline import provenance as prov

    label = format_name or "short"
    if proof:
        label = f"{label}-proof"
    return prov.build(
        ticker=getattr(script, "ticker", ""), fmt=label,
        workdate=workspace.name, duration_s=duration,
        # WHICH CODE DREW THIS (P4). The shot template is picked per video
        # from the headline mode, so `short`, `earnings` and `macro` are
        # three different beat orders out of one renderer, which was not
        # recoverable from the artefact.
        render={"engine": "shots", "format": format_name},
        prices=prices,
        # A SHORT's visuals are the shot template's plates plus whatever came
        # from outside the kit. It fetches nothing; the one thing from outside
        # is the meme, and that is counted as the owned library it came from.
        visual_sources=dict(visual_sources or {}), filings={}, tts=tts,
        settings=settings)


def _safe_report(fmt: Format, result: BuildResult, reg) -> dict | None:
    """The format's clear area and every filled word placed outside it.

    Empty `outside` is the goal. What is in it names the shot, the slot and
    the rows, so a card that still reaches under the title can be found.
    """
    if not fmt.safe:
        return None
    from pipeline.compose import _slot_in_frame

    top, bottom = fmt.safe
    outside = []
    for l in result.of_kind("plate"):
        plate = reg.get(l.entry_key)
        if plate is None or plate.family == "room":
            continue
        for name, value in l.values.items():
            slot = plate.slot(name)
            if (slot is None or slot.region or slot.control
                    or not str(value).strip()):
                continue
            _, y, _, h = _slot_in_frame(plate, name, (l.x, l.y, l.w, l.h))
            if y < top - 1 or y + h > bottom + 1:
                outside.append({"shot": l.shot_id, "slot": name,
                                "rows": [y, y + h]})
    scaled = sorted({l.shot_id for l in result.of_kind("plate")
                     if l.w < result.frame[0] - 1})
    return {"top": top, "bottom": bottom, "outside": outside,
            "shrunk_to_fit": scaled}


def held_over_ceiling(video: Path, spans,
                      ceiling: float) -> list[dict] | None:
    """The compositions in `video` that hold past `ceiling`, by shot.

    MEASURED OFF THE FRAMES, which is what `short_max_hold_s` always said it
    was and what nothing did. A span inside its own `max_hold_s` can still sit
    on one unchanged picture for longer, and only the encode shows it. Each
    entry names the shot it happens in and where. `None` means the frames
    could not be read, which is not the same answer as "none held".
    """
    from pipeline.frame_checks import (BOIL_SAMPLE_FPS, BOIL_SCALE, held_spans,
                                     holds_past)

    try:
        measured = held_spans(video, sample_fps=BOIL_SAMPLE_FPS,
                              scale=BOIL_SCALE)
    except (RenderError, OSError) as e:
        log.warning("could not measure the holds in %s: %s", video.name, e)
        return None
    found: list[dict] = []
    for lo, hi in holds_past(measured, [sp.start for sp in spans], ceiling):
        shot = next((sp.shot.id for sp in spans
                     if sp.start - 1e-6 <= lo < sp.end), "")
        found.append({"shot": shot, "start_s": round(lo, 2),
                      "end_s": round(hi, 2), "held_s": round(hi - lo, 2)})
    return found


def render_short(script, tts, workspace: Path, settings, *,
                 content=None, prices=None, proof: bool = False,
                 out_name: str | None = None,
                 format_name: str = "short",
                 resolver=None, anchors=None,
                 company_data=None) -> tuple[Path, Path]:
    """Render the SHORT. Returns `(mp4, manifest)`.

    At ONE HOUR for the whole cut, fixed here and recorded on the manifest;
    see `plates.at_episode_hour`. The work is `_render_short`.

    `company_data` is the operator's workbook for this video, when there is
    one: the sheet rows are then the workbook's figures (item 23), and the
    cards only the workbook can fill are in the rotation.
    """
    with at_episode_hour(settings, workspace, script.ticker):
        return _render_short(script, tts, workspace, settings,
                             content=content, prices=prices, proof=proof,
                             out_name=out_name, format_name=format_name,
                             resolver=resolver, anchors=anchors,
                             company_data=company_data)


def drop_unfillable(fmt: Format, reg, resolver) -> tuple[Format, list[str]]:
    """Drop every shot none of whose drawings this video can fill (item 25).

    A shot used to draw its authored plate whatever the script carried, so a
    card the workbook fills (the implied growth, the quarter bars) would have
    gone up as its empty furniture on a video with no workbook. A shot is
    kept when any of its drawings can be filled, and always when it is a room,
    carries the host, places a list or names no plate.
    """
    from dataclasses import replace

    from pipeline.compose import _fillable, resolve_plate

    keep, dropped = [], []
    for shot in fmt.shots:
        if (not shot.plate or shot.host or shot.repeat is not None
                or shot.plate.startswith("room/")):
            keep.append(shot)
            continue
        ok = False
        for v in shot.variants:
            try:
                plate = resolve_plate(reg, v.plate, fmt.aspect)
            except Exception:                            # noqa: BLE001
                plate = None
            if plate is not None and _fillable(v, shot, plate, resolver, reg,
                                               safe=fmt.safe):
                ok = True
                break
        (keep if ok else dropped).append(shot if ok else shot.id)
    if not keep:
        raise RenderError("every shot was dropped; the script fills nothing")
    return replace(fmt, shots=tuple(keep)), dropped


def _render_short(script, tts, workspace: Path, settings, *,
                  content=None, prices=None, proof: bool = False,
                  out_name: str | None = None,
                  format_name: str = "short",
                  resolver=None, anchors=None,
                  company_data=None) -> tuple[Path, Path]:
    """`render_short`, at the hour it has already fixed for the episode.

    Interpolated word timings must never be the master clock of a published
    cut, so draft audio cannot make a FINAL. A PROOF is the deliberate
    exception: it exists to be looked at and never delivered.

    A proof therefore writes `short_proof.mp4`, not `short_final.mp4` (D5).
    It used to default to the final's name and the proof call did not
    override it, so a pass rendered with the free voice replaced a paid
    final — and `/upload`, which reads `short_final.mp4`, would then send
    the proof to YouTube. The LONG path has always done this correctly.
    """
    if out_name is None:
        out_name = "short_proof.mp4" if proof else "short_final.mp4"
    if not proof and getattr(tts, "draft", False):
        raise RenderError(
            f"refusing to render a SHORT from {tts.tier} draft audio — its "
            f"word timings are interpolated. Approve the script so the paid "
            f"voice runs first.")

    workdir = Path(workspace) / "render_short"
    workdir.mkdir(parents=True, exist_ok=True)

    # THE SHEET IS THE WORKBOOK'S (item 23). The writer names the rows; with
    # the workbook here, the figures on screen are its History sheet's, so
    # the sheet cannot disagree with it. What was replaced is recorded.
    workbook_notes: list[str] = []
    if company_data is not None:
        from pipeline.short_data import fill_numbers
        script, workbook_notes = fill_numbers(script, company_data)

    reg = load_plates(settings.assets_dir)
    # Which template, by name. This is the whole of what the engine needed to
    # carry three formats instead of one — there is no per-format branch
    # anywhere below, and a fourth format is a JSON file and this argument.
    fmt: Format = load_format(format_name)
    # BEATS and SHOTS are different counts and both matter. A beat is an idea
    # the format has; a shot is a frame. The beats are the shots the format
    # was authored with, before a repeat expands them. Counted here, off the
    # format actually being rendered — re-reading the file at manifest time
    # is a second parse that can disagree with the first.
    n_beats = len(fmt)

    words = list(getattr(tts, "words", []) or [])
    duration = float(getattr(tts, "duration_s", 0.0) or 0.0)
    if duration <= 0:
        raise RenderError("the audio has no duration; there is no clock to cut to")

    # Prices before the resolver: the resolver holds them, and a resolver
    # built with None leaves THE MOVE's chart slot unfilled.
    # `get_price_history` never raises — worst case is a labelled synthetic
    # series — so the slot is always fillable. A format that draws no prices
    # (`earnings`, `macro`) fetches none, so its record does not report on a
    # feed that is not in the picture.
    if prices is None and draws_prices(fmt):
        from pipeline.prices import get_price_history
        prices = get_price_history(getattr(script, "ticker", ""), settings)

    handle0 = getattr(settings, "brand_handle", "") or ""
    if resolver is None:
        resolver = ShortResolver(script=script, workdir=workdir,
                                 settings=settings, prices=prices,
                                 handle=handle0, data=company_data,
                                 content=content)
    else:
        resolver.workdir, resolver.prices = workdir, prices
        resolver.handle = resolver.handle or handle0
    if isinstance(resolver, ShortResolver):
        resolver.format_name = resolver.format_name or format_name
        resolver.script = script
        if resolver.data is None:
            resolver.data = company_data
        if resolver.content is None:
            resolver.content = content

    # A shot the script carries no words for is DROPPED, not rendered blank.
    # THE TURN is one sentence on bare ground; with no sentence it is a held
    # empty frame, which is the exact failure this rewrite exists to remove.
    # A sequence repeat becomes one shot per item BEFORE anything is timed:
    # how many numbers beats a video has is a fact about its script.
    probe = resolver if resolver is not None else resolver_probe(script, settings)

    # WHICH SEQUENCE THIS VIDEO IS CUT IN (03). Before anything is expanded or
    # pruned, because an order names the shots the template was AUTHORED with
    # and a sequence repeat renames them. Rotating off the recent orders the
    # same way the plates rotate off the recent plates.
    #
    # THE NARRATION DECIDES WHICH ORDERS ARE OPEN. A marked script says where
    # each beat starts, so the cut follows its markers: the rotation picks
    # among the declared orders that put the beats where the voice does, and
    # `order_by_marks` puts them there whatever it picks. An unmarked script
    # was written to the authored beat order and is heard in it, so only the
    # orders that keep that sequence are open to it — the same choice, from
    # the same list, that it always had.
    from pipeline.reach import recent_orders, recent_plates

    seed = script.content_sha()
    marks = marked_beats(script, fmt)
    shot_order = choose_order(fmt, seed=seed,
                              avoid=recent_orders(settings, exclude=workspace),
                              heard=marks or voice_keys(fmt.shots))
    fmt = apply_order(fmt, shot_order)
    if marks:
        fmt = order_by_marks(fmt, marks)

    fmt = expand_sequences(fmt, probe.list_for)
    fmt, dropped = prune_empty_shots(fmt, probe)
    fmt, unfillable = drop_unfillable(fmt, reg, resolver)
    dropped += unfillable

    # WHAT THE LAST FEW VIDEOS ALREADY LOOKED LIKE (02). Read once and handed
    # to both the timing and the composition: a long beat's punch-in is asked
    # of the plate the rotation will draw, and asking with a different avoid
    # set would ask about a different plate.
    recent = recent_plates(settings, exclude=workspace)
    # WHICH DRAWING EACH BEAT GETS, once for the cut, never one layout twice
    # where a beat has another (item 7). The punch-ins and the composition
    # both read it, so a long beat's punch-in is asked of the plate drawn.
    variants = plan_variants(reg, fmt.shots, fmt.aspect, resolver,
                             seed=seed, avoid=recent, safe=fmt.safe)

    def punch_in(shot):
        return punch_in_slot(reg, shot, fmt.frame, resolver,
                             aspect=fmt.aspect, seed=seed, avoid=recent,
                             variants=variants, safe=fmt.safe)

    # A marked script's anchors are searched IN ORDER, each after the last:
    # the words after a marker can also be said earlier, and the first place
    # they are said is not where that beat starts.
    # HE IS ON CAMERA FOR HIS LINE (item 28), and the cards after him take
    # the rest of the stretch as the figures are read.
    host_lines = ({"turn": script.turn_line}
                  if getattr(script, "turn_line", None) else {})
    spans = resolve_spans(fmt, words, duration,
                          anchors if anchors is not None
                          else build_anchors(script),
                          ordered=bool(marks), punch_in=punch_in,
                          host_lines=host_lines)

    # The recent plates (02). The seed alone makes two videos differ by
    # chance; nothing stopped three in a row opening on the same pose in the
    # same room. This steers off what is recent where the kit has an
    # alternative, and is silently empty on a fresh install. It also decides
    # which of a beat's interchangeable plates this video draws — the
    # rotation the vertical formats never had, because a fixed shot list
    # names one drawing per beat and `parser_short` ignores the inline tags a
    # director would use in a LONG.
    result = build_layers(fmt, spans, resolver, reg,
                          aspect=fmt.aspect, seed=seed, avoid=recent,
                          words=words, variants=variants)

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

    # WHAT MOVES, AND WHEN (items 8-14 of the motion plan). Planned off the
    # finished composition and the words, before a frame is drawn, so the
    # manifest records what the frames play and the sound is cut to it.
    from pipeline.moves import plan_short, recent_circled

    plan = plan_short(fmt, result, reg, words, seed=script.content_sha(),
                      settings=settings,
                      sources=shot_sources(script, fmt),
                      recent_circled=recent_circled(settings, exclude=workspace))

    silent = workdir / "video_frames.mkv"
    scale = delivery_scale(settings, result.frame, proof=proof)
    delivered = delivered_size(result.frame, scale)
    render_frames(result, resolver, duration, silent, settings, reg=reg,
                  words=words, plan=plan, scale=scale)
    overflow = getattr(render_frames, "last_text_overflow", {}) or {}
    faces = getattr(render_frames, "last_faces", {}) or {}
    # THE CEILING, MEASURED ON THE FRAMES the shots drew, before captions
    # are burned over them: it bounds the composition, not the subtitle
    # track. Warned and recorded rather than refused, because the voice
    # is already paid for and whether nine seconds on a table is too long
    # is the operator's call.
    held_over = held_over_ceiling(silent, result.spans,
                                  settings.short_max_hold_s)
    for h in held_over or ():
        log.warning("%s holds one picture for %.1fs (%.1f-%.1fs), over "
                    "the %.0fs ceiling", h["shot"] or "the cut",
                    h["held_s"], h["start_s"], h["end_s"],
                    settings.short_max_hold_s)

    # Captions are BURNED, not drawn per frame: one phrase at a time, in the
    # same ink as everything else on the frame, from the same builder the LONG
    # uses. Drawing them into every one of two thousand frames sets the same
    # line thirty times a second for no reason.
    from pipeline.compose import CAPTION_SIDE_FW, CAPTION_TYPE_FH
    from pipeline.rasters import build_phrase_ass

    W, H = result.frame
    # ONLY THE SHOTS THAT ASKED FOR THEM. `captions: false` is how a template
    # says the type on this plate IS the line — the hook card sets its own hook
    # at 18 characters a line, and a caption of the same sentence underneath is
    # the same words twice. Burning the whole track ignored the flag, because
    # the flag lives per shot and a subtitle file does not.
    #
    # AND WHERE EACH SHOT PUT THEM. `build_layers` placed every caption inside
    # the band the phone leaves clear and off whatever its shot is showing,
    # and the layer's box is the caption's box. Each window carries the foot
    # of that box, so a line burns where its own shot placed it, and a line
    # that runs on across a cut moves with the cut.
    bands = [(l.t_start, l.t_end, l.y + l.h) for l in result.of_kind("caption")]
    spoken = [w for w in words
              if any(a <= float(getattr(w, "start", 0.0)) < b
                     for a, b, _ in bands)]
    ass = workdir / "captions.ass"
    # TWO TO FOUR WORDS A LINE, ONE OF THEM IN `attention`. On-screen text that
    # repeats the narration word for word can hurt understanding, and five
    # words at a time was most of the sentence; a figure or a turn word in
    # colour is what the eye takes from a line it only glances at.
    ass.write_text(build_phrase_ass(
        spoken, settings=settings, play_res=(W, H),
        font_size=int(H * CAPTION_TYPE_FH), margin_v=int(H * 0.13),
        margin_h=int(W * CAPTION_SIDE_FW), max_words=4, min_words=2,
        max_chars=24, key_words=True,
        duration=duration, windows=bands), encoding="utf-8")
    # Always run, captions or not: the frames' file is lossless, and this is
    # the encode that makes the picture the viewer gets.
    silent = final_encode(silent, workdir / "video.mp4", settings,
                          captions=ass if spoken else None)

    # Write beside the target and `os.replace` into position (D2). Muxing
    # straight over the existing file meant any failure past this point left
    # the operator with nothing — not the new render and not the good one
    # they already had. `segments._encode_one` already worked this way; this
    # is the same pattern, which is why it is not a new one.
    out = Path(workspace) / out_name
    part = out.with_suffix(".part.mp4")
    # THE MIX, not the voice alone. See `pipeline/sound.py` for what this
    # replaced and why it is the LONG's mixer rather than a second one.
    # Sound reads the spans AFTER composition, so whatever pacing the shots
    # land on, the swish lands on the cut.
    # The move record is what the sound is timed to: design's move ids and
    # the programme time of each first frame, and the wipes with their cuts.
    wiped = {round(w.cut, 3): (w.start, w.end) for w in plan.wipes}
    cuts = [Cut(shot_id=sp.shot.id, start=sp.start, end=sp.end,
                tags=frozenset(_sound_tags(result, reg, sp.shot.id)),
                part=int(getattr(sp.shot, "part", 0) or 0),
                wipe=wiped.get(round(sp.start, 3)))
            for sp in result.spans]
    moves = [Move(r["move"], r["start"], r["shot_id"], r["slot"], int(r.get("frames") or 0))
             for r in plan.record()["moves"]]
    tracks = short_mix(tts, settings, cuts=cuts, hour=reg.hour,
                       seed=script.content_sha(),
                       workspace=workspace, moves=moves)
    if tracks:
        mix_under_picture(silent, tracks, part, duration=duration,
                          audio_bitrate=settings.audio_bitrate,
                          normalise=normalises(settings, tts),
                          graph_path=workdir / "mix.filter.txt")
    else:
        silent.replace(part)
    if not part.exists() or part.stat().st_size == 0:
        part.unlink(missing_ok=True)
        raise RenderError(f"the SHORT mux produced nothing at {part}")
    os.replace(part, out)

    meme = _meme_record(resolver, result)
    provenance = _provenance(script, settings, Path(workspace), duration,
                             prices, tts, fmt.name, proof=proof,
                             visual_sources=({"library": 1} if meme.get("key")
                                             else {}))
    audio_rows = manifest_rows(tracks)
    provenance.sound = sound_summary(
        audio_rows, lufs=measure_lufs(out) if tracks else None,
        placeholders=placeholders_played(settings, tracks))

    manifest_path = Path(workspace) / f"{Path(out_name).stem}.manifest.json"
    manifest_path.write_text(json.dumps({
        "ticker": script.ticker,
        "format": fmt.name,
        # The hour the set is at, for the whole cut; the next pass of this
        # video reads it back (`plates.hour_of_episode`).
        "hour": reg.hour,
        # "Who it hits" is one beat told across four shots because four cards
        # cannot share a frame legibly — so a nine-beat format cutting to
        # fourteen shots is the design working, not drift.
        "beats": n_beats,
        # The engine, beside the template it ran (P4).
        "engine": "shots",
        "shots_count": len(spans),
        "anchored_shots": sum(1 for sp in spans if sp.anchored),
        "kit": "v2-plates",
        # Where the numbers on the chart came from, and whether they are
        # real (B1). `degraded` means the live feed failed and the seeded
        # floor drew the chart instead — which is invisible on screen, so
        # the artefact has to say it.
        "prices": {
            "source": getattr(prices, "source", ""),
            "degraded": bool(getattr(prices, "degraded", False)),
        },
        # THE WHOLE RECORD (N3). Same shape as the LONG's, so the delivery
        # message is built the same way for both formats.
        "provenance": provenance.to_json(),
        "duration_s": round(duration, 3),
        "frame": {"w": result.frame[0], "h": result.frame[1]},
        # The file's own size: the layout above, drawn at `delivery_scale`.
        # Every box in this manifest is in the layout's pixels.
        "delivered": {"w": delivered[0], "h": delivered[1]},
        # A beat split for running long shows as both its parts: `part` 1 is
        # the wide picture under the beat's own id, `part` 2 the move in,
        # under `<id>-in` with `part_of` naming the beat. Unsplit shots carry
        # neither key, so a manifest reader that knows nothing of parts reads
        # every shot as it always did.
        "shots": [{
            "id": s.shot.id,
            "plate": s.shot.plate,
            "start_s": round(s.start, 3),
            "end_s": round(s.end, 3),
            "anchored": s.anchored,
            "max_hold_s": s.shot.max_hold_s,
            "layers": [l.name for l in result.for_shot(s.shot.id)],
            **_part_fields(s.shot),
        } for s in result.spans],
        "layers": len(result.layers),
        # What the render actually reached. Under the tag model this was an
        # emergent accident and a SHORT once reached 4% of its own library;
        # under the templates it is a property of the twelve shots, and it is
        # recorded so it stays visible rather than being rediscovered.
        "plates_used": result.plates_used,
        # WHICH SEQUENCE IT WAS CUT IN, so the next video can rotate off it.
        # `recent_orders` reads this back exactly as `recent_plates` reads
        # `plates_used`; a manifest from before the field existed simply
        # contributes nothing.
        "shot_order": shot_order,
        # EVERY MOVE THE FRAMES PLAYED: design's move id, the programme time
        # of its first frame, the shot and the slot; each wipe with the cut it
        # covers. The sound's move hits are cut to this, and `recent_moves`
        # reads it back so the pen-circle never plays in two shorts running.
        "moves": plan.record(),
        # THE ONE MEME, or why there is none. `memes.recent_memes` reads `key`
        # back so the next short rotates off it, exactly as `recent_plates`
        # reads `plates_used`; `key` is null whenever nothing went on screen,
        # so a meme that was picked and then had no room is not counted.
        "meme": meme,
        # And the beats as the narration marked them, which is what put them
        # in that order. Empty for an unmarked script.
        "beat_order": marks,
        # WHAT THE MIX DID, in the LONG's shape. A short had no mix for six
        # weeks and no field that would have shown it (`pipeline/sound.py`).
        "audio": audio_rows,
        "kit_reach": (
            f"Kit: {len(result.plates_used)} of {len(reg)} plates, "
            f"{len({l.concept for l in result.layers if l.concept})} families, "
            f"{sum(1 for l in result.layers if l.moves)} animated layers"),
        "skipped": result.skipped,
        "dropped_shots": dropped,
        # WHERE THE FIGURES CAME FROM (item 23): the workbook, when it was
        # in the workspace, and which typed figures it replaced.
        "workbook": ({"file": Path(getattr(company_data, "source_file", "")
                                   or "").name,
                      "notes": workbook_notes}
                     if company_data is not None else None),
        # THE CLEAR AREA the words were kept inside (item 27), and every word
        # that still sits outside it.
        "safe_area": _safe_report(fmt, result, reg),
        # THE CREDITS for every picture the short drew (item 34), which the
        # bot sends with the video the way it does the long's stock footage.
        "attributions": (resolver.attributions()
                         if isinstance(resolver, ShortResolver) else []),
        # Characters that did not fit even at the readability floor. Non-empty
        # means a script said more than its shot can hold, and the words were
        # cut. Under the writing form this is what a character budget prevents.
        "text_overflow": overflow,
        # WHAT HIS FACE DID, per host shot: whether he spoke, how many talk
        # and idle frames played, how often he blinked, and how many frames
        # held the still — which on a close-up is meant to be none.
        "host_faces": faces,
        "longest_layer_hold_s": round(
            max((b - a for a, b, _ in held_layer_spans(result)), default=0.0), 3),
        # PACING, WHICH IS A PROPERTY OF THE CUT AND NOT OF THE SUITE. The
        # only place it shows is here or in the video. `still` is the number
        # that matters: a shot with
        # a host in it is alive at fifteen seconds and a static data plate is a
        # held photograph at eight.
        "pacing": {
            "shots": len(result.spans),
            "longest_span_s": round(
                max((sp.end - sp.start for sp in result.spans), default=0.0), 2),
            "longest_still_span_s": round(max(
                (sp.end - sp.start for sp in result.spans
                 if sp.shot.plate and not sp.shot.host
                 and not sp.shot.plate.startswith("room/")), default=0.0), 2),
            "spans_over_their_ceiling": [
                f"{sp.shot.id} {sp.end - sp.start:.1f}s over {sp.shot.max_hold_s}s"
                for sp in result.spans
                if sp.end - sp.start > sp.shot.max_hold_s + 0.05],
            # The same question asked of the frames rather than the plan:
            # a shot inside its own ceiling can still hold one picture
            # past this one. `null` means they could not be measured.
            "hold_ceiling_s": settings.short_max_hold_s,
            "held_over_ceiling": held_over,
        },
    }, indent=1), encoding="utf-8")

    return out, manifest_path
