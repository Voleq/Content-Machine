"""Render the LONG from chapter templates, through the same engine.

The director picks nine chapter types; each expands to its own small shot
list from `templates/chapters/`. Nobody authors thirty-eight shots, and
nothing here knows what a chapter means — that is entirely in the files.

THE ROOM IS A LOBBY. A chapter opens in the room, dives into the monitor
where the substance happens, and surfaces back to close before the next
stinger. Across nine chapters that is twelve dives, which makes them the
most-used motion in the format.

This module is a RESOLVER and an entry point. Every line of composition,
timing, invariant checking and drawing is the code the SHORT already uses:
if the long needed its own compositor, the engine would be wrong.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from pipeline.models import LongScript
from pipeline.render_short import ShortResolver, render_short

# The narration is one long block of prose. A chapter's lines are the
# sentences that fall inside its share of it — which is a stopgap: under the
# writing form each chapter gets its own fields and this goes away with the
# rest of the prose-slicing.
_SENT = re.compile(r"(?<=[.!?])\s+")


@dataclass
class LongResolver(ShortResolver):
    """Supplies a chapter's words. Composes nothing, same as the short's.

    `chapter.line.N` is the Nth sentence of the chapter currently being
    built — the compositor asks per shot, and the shot's id carries which
    chapter it belongs to, so the resolver is told the chapter before each
    shot rather than guessing from the source string.
    """

    chapters: list[list[str]] = field(default_factory=list)
    current: int = 0
    # The LONG's metric rows and periods come from the data export, not from
    # the script, and its real media comes off the workspace.
    number_rows: list = field(default_factory=list)
    periods: list = field(default_factory=list)
    media: dict = field(default_factory=dict)

    @property
    def rows(self):
        return list(self.number_rows)

    def image_for(self, src: str):
        """Real media, by name, off the workspace.

        The compositor has already refused this unless it is landing inside a
        container — the portal rule is enforced there, not trusted here.
        """
        if src.startswith("media."):
            return self.media.get(src.split(".", 1)[1])
        return super().image_for(src)

    def begin_shot(self, shot) -> None:
        """Point at the chapter this shot belongs to, before it is built."""
        if getattr(shot, "chapter_n", 0):
            self.current = shot.chapter_n - 1

    def text_for(self, src: str) -> str | None:
        # The periods live on the resolver here, not on the script: a LONG's
        # sheet is measured over the export's fiscal years.
        if src == "numbers.header":
            return ("\t" + "\t".join(self.periods)) if self.periods else None
        if src == "numbers.years":
            return ",".join(self.periods) if self.periods else None
        parts = src.split(".")
        if parts[0] == "chapter":
            return self._chapter(parts[1:])
        return super().text_for(src)

    def _chapter(self, rest: list[str]) -> str | None:
        if not rest:
            return None
        if rest[0] == "number":
            return f"{self.current + 1:02d}"
        if rest[0] == "title":
            return _title(self.chapters, self.current)
        if rest[0] == "phrase":
            # A chain box holds twenty-two characters. A narration sentence is
            # thirty to seventy, so the small slots take a PHRASE — the head
            # of the sentence — until the writing form gives each chapter its
            # own short fields.
            line = self._chapter(["line"] + rest[1:]) or ""
            words = line.split()
            out, n = [], 0
            for w in words:
                if n + len(w) + 1 > 20:
                    break
                out.append(w)
                n += len(w) + 1
            return " ".join(out).rstrip(",.;:") or None
        if rest[0] == "line":
            lines = (self.chapters[self.current]
                     if 0 <= self.current < len(self.chapters) else [])
            i = int(rest[1]) if len(rest) > 1 and rest[1].isdigit() else 0
            return lines[i] if i < len(lines) else None
        return None


def _title(chapters: list[list[str]], i: int) -> str | None:
    if not (0 <= i < len(chapters)) or not chapters[i]:
        return None
    # The first few words of the chapter's first sentence. A real title comes
    # from the writing form; this keeps the stinger honest until then.
    return " ".join(chapters[i][0].split()[:4]).rstrip(",.;:")


def split_chapters(narration: str, n: int) -> list[list[str]]:
    """The narration in `n` roughly equal runs of whole sentences."""
    sents = [s.strip() for s in _SENT.split(narration.strip()) if s.strip()]
    if not sents:
        return [[] for _ in range(n)]
    per = max(len(sents) / max(n, 1), 1.0)
    out: list[list[str]] = [[] for _ in range(n)]
    for i, s in enumerate(sents):
        out[min(int(i / per), n - 1)].append(s)
    return out


def _rows_from(company_data: dict | None) -> tuple[list, list]:
    """Metric rows out of the data export, in the SHORT's row shape.

    The LONG's sheet is the same plate reading the same kind of fact, so it
    uses the same NumberRow — including its flow/stock kind, which is what
    keeps a period apart from a point in time here too.
    """
    from pipeline.models import NumberRow
    if company_data is None:
        return [], []
    # SIX PERIODS, LTM INCLUDED. Four fiscal years, the last full year and LTM
    # is what every table and every time-series plate in the kit is authored
    # for, and LTM is usually the column the argument turns on. This dropped
    # it — "not a fiscal period" — and then handed five figures to a plate
    # with six heads, which the header check now refuses outright.
    years = list(company_data.history_years or [])
    hist = company_data.history or {}
    wanted = ("revenue", "net_income", "ebitda", "operating_income",
              "gross_profit", "free_cash_flow")
    out = []
    for label in wanted:
        series = hist.get(label)
        if not isinstance(series, (list, tuple)):
            continue
        vals = [_short(v) for v in series[:len(years)] if v not in (None, "")]
        if len(vals) >= 2:
            out.append(NumberRow(label=label.replace("_", " ").title()[:40],
                                 values=vals))
        if len(out) >= 5:
            break
    from pipeline.plates import PERIOD_COUNT
    return out, [str(y) for y in years][-PERIOD_COUNT:]


def _short(v) -> str:
    """A figure at sheet width. 496000000 does not fit a row band."""
    try:
        n = float(v)
    except (TypeError, ValueError):
        return str(v)
    for cut, suf in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(n) >= cut:
            return f"{n / cut:.1f}{suf}".replace(".0", "")
    return f"{n:.0f}"


def _media_in(ws: Path) -> dict:
    """Real media the operator put in the workspace, by portal name."""
    found = {}
    for name, pat in (("filing", "*income_statement*.png"),
                      ("screenshot", "*screengrab*.png")):
        hit = sorted(ws.glob(pat))
        if hit:
            found[name] = hit[0]
    return found


def render_long_shots(script: LongScript, tts, workspace: Path, settings, *,
                      content=None, prices=None, company_data=None,
                      out_name: str = "long_final.mp4") -> tuple[Path, Path]:
    """Render the LONG. Returns `(mp4, manifest)`."""
    from pipeline.shots import load_format

    fmt = load_format("long")
    n_chapters = len({s.chapter_n for s in fmt.shots if s.chapter_n})
    chapters = split_chapters(script.narration, max(n_chapters, 1))
    rows, periods = _rows_from(company_data)

    resolver = LongResolver(script=script, workdir=Path(workspace),
                            settings=settings, prices=prices,
                            chapters=chapters,
                            number_rows=rows, periods=periods,
                            media=_media_in(Path(workspace)))

    # A chapter's words belong to that chapter. The resolver is pointed at
    # the right one before each shot is built, keyed off the chapter number
    # the expansion stamped into the shot id.
    anchors = {}
    for i, lines in enumerate(chapters):
        if lines:
            anchors[f"ch{i + 1}"] = lines[0]

    return render_short(script, tts, Path(workspace), settings,
                        content=content, prices=prices,
                        out_name=out_name, format_name="long",
                        resolver=resolver, anchors=anchors)
