"""The quarterly scoreboard: what we said, and what happened (09).

:mod:`pipeline.standing` already records every shipped thesis, the numbers it
rested on, and whether those numbers have since moved enough to call it
intact, cracking or broken. That record is a private card nobody outside this
machine ever sees.

Published, it is three things at once. It is original substance by
construction — nothing about it is a template with a ticker swapped in, which
is the property YouTube's inauthentic-content rule is actually asking for. It
is the cheapest episode in the system, because every number in it was already
gathered for an earlier video. And it is the most direct answer available to
a viewer who distrusts a synthetic voice on a finance channel: a record of
being wrong, in public, with dates.

Quarterly rather than monthly, which is the operator's call and the right
one: a thesis that moved inside four weeks mostly moved with the market, and
a scoreboard that reports noise every month teaches its audience to ignore it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from config import Settings

log = logging.getLogger(__name__)

# How the book's three states read on a scoreboard, worst first so the
# opening line is the uncomfortable one. A scoreboard that leads with its
# wins is an advertisement.
STATUS_ORDER = ("broken", "cracking", "intact")

STATUS_WORDS = {
    "broken": "wrong",
    "cracking": "under pressure",
    "intact": "holding",
}


def quarter_of(when: date) -> str:
    return f"{when.year}-Q{(when.month - 1) // 3 + 1}"


def quarter_bounds(quarter: str) -> tuple[date, date]:
    """First and last day of a `YYYY-Qn` string."""
    year_s, _, q_s = quarter.partition("-Q")
    year, q = int(year_s), int(q_s)
    start = date(year, 3 * (q - 1) + 1, 1)
    end = (date(year + 1, 1, 1) if q == 4
           else date(year, 3 * q + 1, 1))
    return start, end


@dataclass
class Row:
    """One thesis on the scoreboard."""

    ticker: str
    status: str
    summary: str
    workdate: str
    moves: list[dict] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        return STATUS_WORDS.get(self.status, self.status)

    def line(self) -> str:
        moved = ""
        material = [m for m in self.moves if m.get("material")]
        if material:
            first = material[0]
            moved = (f" — {first.get('field', 'a tracked number')} moved "
                     f"{first.get('change', 0) * 100:+.0f}%")
        return (f"  {self.ticker:<6} {self.verdict:<16} {self.workdate}"
                f"{moved}")


@dataclass
class Scoreboard:
    quarter: str
    rows: list[Row] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        out = {status: 0 for status in STATUS_ORDER}
        for row in self.rows:
            out[row.status] = out.get(row.status, 0) + 1
        return out

    @property
    def scored(self) -> int:
        return len(self.rows)

    def headline(self) -> str:
        """The opening claim, which leads with what went wrong.

        Deliberate: a record of calls that opens on its hit rate is an
        advertisement, and the one thing this format has to be is the
        opposite of one.
        """
        counts = self.counts
        if not self.scored:
            return (f"{self.quarter}: nothing shipped with a thesis behind "
                    f"it, so there is nothing to score.")
        wrong = counts.get("broken", 0)
        pressure = counts.get("cracking", 0)
        holding = counts.get("intact", 0)
        return (f"{self.quarter}: {wrong} of {self.scored} calls are wrong, "
                f"{pressure} under pressure, {holding} still holding.")

    def render_text(self) -> str:
        lines = [f"📒 What we said, and what happened — {self.quarter}",
                 f"  {self.headline()}"]
        if not self.rows:
            lines.append("  Nothing to show. This fills in as videos ship "
                         "with a thesis recorded against them.")
            return "\n".join(lines)
        for status in STATUS_ORDER:
            group = [r for r in self.rows if r.status == status]
            if not group:
                continue
            lines.append(f"  — {STATUS_WORDS.get(status, status)} —")
            lines += [r.line() for r in group]
        lines.append("  Every number here was already gathered for the video "
                     "it came from, so this episode costs one voice "
                     "generation and no research.")
        return "\n".join(lines)

    def script_brief(self) -> str:
        """What the writer needs to write the episode.

        Not a script: this pipeline's whole shape is that a human writes and
        the machine renders, and a scoreboard that wrote its own copy would be
        the one template this channel cannot afford.
        """
        lines = [f"SCOREBOARD BRIEF — {self.quarter}",
                 "",
                 self.headline(),
                 "",
                 "Each call, with what moved under it:"]
        for status in STATUS_ORDER:
            for row in [r for r in self.rows if r.status == status]:
                lines.append(f"- {row.ticker} ({row.workdate}) — "
                             f"{row.verdict}. Said: {row.summary}")
                for move in row.moves:
                    if move.get("material"):
                        lines.append(
                            f"    {move.get('field', '?')}: "
                            f"{move.get('change', 0) * 100:+.1f}%")
        lines += ["",
                  "Lead with the ones that were wrong. The point of this "
                  "episode is the record, not the hit rate."]
        return "\n".join(lines)


def build(settings: Settings, quarter: str = "") -> Scoreboard:
    """The scoreboard for one quarter, from the thesis book.

    A thesis whose workdate cannot be read is included rather than dropped:
    an unreadable date is not evidence the call was not made, and leaving it
    out would quietly improve the record.
    """
    from pipeline.standing import ThesisBook

    quarter = quarter or quarter_of(datetime.now(timezone.utc).date())
    try:
        start, end = quarter_bounds(quarter)
    except (ValueError, IndexError):
        raise ValueError(f"{quarter!r} is not a quarter like 2026-Q3") from None
    book = ThesisBook(settings)
    rows: list[Row] = []
    for ticker in book.tickers():
        thesis = book.get(ticker)
        if thesis is None:
            continue
        when = thesis.workdate or thesis.recorded_at[:10]
        try:
            covered = start <= date.fromisoformat(when[:10]) < end
        except (ValueError, TypeError):
            covered = True
        if not covered:
            continue
        rows.append(Row(ticker=thesis.ticker, status=thesis.status,
                        summary=thesis.summary, workdate=when[:10],
                        moves=list(thesis.last_moves or [])))
    rows.sort(key=lambda r: (STATUS_ORDER.index(r.status)
                             if r.status in STATUS_ORDER else 9, r.ticker))
    return Scoreboard(quarter=quarter, rows=rows)


def scoreboard_text(settings: Settings, quarter: str = "") -> str:
    try:
        return build(settings, quarter).render_text()
    except ValueError as e:
        return str(e)
