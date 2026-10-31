"""What kind of day a SHORT is about: an earnings print, company news, or a
move nothing public explains.

THE TYPE OF VIDEO WAS NEVER WORKED OUT. `/short` cut every trending name as
"noise or signal" — the price chart, a headline, six years of annual figures,
a valuation — and the earnings cut (`templates/shots/earnings.json`: the
print, the street's number, the quarter against a year before, the guide)
was reachable only by typing `/headline TICKER [earnings] …`. So when Boeing
fell 10.7% on the morning it reported (27 Oct 2026), the short said its
revenue went from $62B in FY21 to $95B, which has nothing to do with the day,
and never said what the market reacted to (Valentin, 30 Oct: "the long term
trend rarely matters in an intraday movement").

The day is read off the free record, newest and most certain first:

1. **The operator's word.** `/kind TICKER earnings|news|move` wins.
2. **The SEC.** An 8-K furnished under item 2.02 (results of operations) in
   the last few days IS an earnings day, with the minute it was filed.
   **The earnings date stockanalysis.com lists** is a second clock beside it
   (item 6 of the site picks): it agrees or it says so, and when the 8-K is
   late or filed under another item it still names the day and the session.
3. **The headlines** dated in the same days (the News sheet, the 8-K and IR
   feeds merged into it): an earnings headline is an earnings day; any other
   is company news.
4. Otherwise nothing public explains the move, and the writer is told to go
   and find out — or to say plainly that nobody knows.

Nothing here raises. A source that cannot be read is one fewer signal, and the
answer says which signals it had.
"""

from __future__ import annotations

import datetime as _dt
import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Any

log = logging.getLogger(__name__)

EARNINGS = "earnings"
NEWS = "news"
MOVE = "move"          # a move with no public cause found
KINDS = (EARNINGS, NEWS, MOVE)

# How far back a print or a headline still explains "today". A print after
# Thursday's close is Friday's move, and a short is often cut the evening
# after; a week-old print is not today's news.
WINDOW_DAYS = 4

# Every headline dated in the window is kept, up to a sane bound. The prompt
# lists the first eight its coverage block does not already carry; cut to
# eight here, the site's own stories took every slot and the workbook's
# headlines never reached the prompt at all.
HEADLINES_KEPT = 40

# Words that make a headline a print. Narrower than `/headline`'s list on
# purpose: there the operator has already said the item is news, here a
# headline that merely mentions revenue ("wins a contract worth…") must not
# turn a company-news day into an earnings cut.
_EARNINGS_WORDS = (
    "earnings", "eps", "quarterly results", "quarter results",
    "q1", "q2", "q3", "q4", "first quarter", "second quarter",
    "third quarter", "fourth quarter", "first-quarter", "second-quarter",
    "third-quarter", "fourth-quarter", "full-year results", "guidance",
    "tops estimates", "beats estimates", "misses estimates",
    "loss per share", "earnings per share",
)


@dataclass
class MoveKind:
    """The answer, as it is stored on the workspace and put in the prompt."""

    kind: str = MOVE
    # One sentence for the operator and the writer: what was found and where.
    why: str = ""
    # Where the answer came from: "operator", "SEC 8-K item 2.02", "headlines"
    # or "" when nothing was found.
    source: str = ""
    # THE PRINT, on an earnings day.
    reported_on: str = ""      # ISO day the release was filed
    timing: str = ""           # before the open | during the session | after the close
    period: str = ""           # the quarter's end, from the 10-Q/10-K filed with it
    release_url: str = ""
    release_text: str = ""     # the EX-99.1, cut for the prompt
    # Headlines dated in the window, newest first: {date, headline, source}.
    headlines: list[dict] = field(default_factory=list)
    # THE SECOND CLOCK: the earnings date stockanalysis.com lists, as
    # {which: last|next, date, timing}, or {} when it was not read.
    site_earnings: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, raw: dict | None) -> "MoveKind | None":
        if not isinstance(raw, dict) or raw.get("kind") not in KINDS:
            return None
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in raw.items() if k in known})

    @property
    def is_earnings(self) -> bool:
        return self.kind == EARNINGS


def _day(text: str) -> _dt.date | None:
    try:
        return _dt.date.fromisoformat(str(text or "")[:10])
    except ValueError:
        return None


def _in_window(day: _dt.date | None, today: _dt.date) -> bool:
    return day is not None and 0 <= (today - day).days <= WINDOW_DAYS


def timing_of(accepted: str) -> str:
    """When in the US trading day an EDGAR acceptance time falls.

    `accepted` is UTC ("2026-10-27T11:30:23.000Z"). The exchange's clock is
    New York's, daylight saving and all, so the conversion goes through the
    zone rather than a fixed offset.
    """
    text = str(accepted or "").strip()
    if not text:
        return ""
    try:
        from zoneinfo import ZoneInfo

        when = _dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
        if when.tzinfo is None:
            when = when.replace(tzinfo=_dt.timezone.utc)
        et = when.astimezone(ZoneInfo("America/New_York"))
    except (ValueError, KeyError):
        return ""
    minutes = et.hour * 60 + et.minute
    if minutes < 9 * 60 + 30:
        return "before the open"
    if minutes >= 16 * 60:
        return "after the close"
    return "during the session"


def _looks_like_earnings(headline: str) -> bool:
    low = str(headline or "").lower()
    return any(re.search(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])", low)
               for w in _EARNINGS_WORDS)


def release_excerpt(text: str, limit: int = 3000) -> str:
    """The front of a press release, where the company says what mattered.

    An EX-99.1 opens on its headline and its summary bullets and ends on
    pages of tables; the first few thousand characters are the part a writer
    can use, cut at a sentence so it does not end mid-figure.
    """
    body = " ".join(str(text or "").split())
    if len(body) <= limit:
        return body
    cut = body[:limit]
    stop = max(cut.rfind(". "), cut.rfind("• "))
    return (cut[:stop + 1] if stop > limit // 2 else cut).rstrip() + " …"


SITE = "stockanalysis.com's earnings date"


def _site_clock(site: dict | None, today: _dt.date) -> tuple[str, str]:
    """(day, timing) of the last report the site lists, when it is in the
    window; ("", "") otherwise."""
    site = site or {}
    when = _day(site.get("date"))
    if site.get("which", "last") != "last" or not _in_window(when, today):
        return "", ""
    return when.isoformat(), str(site.get("timing") or "")


def _site_note(site: dict | None, today: _dt.date, reported_on: str) -> str:
    """One sentence on what the second clock says, beside the first."""
    site = site or {}
    when = _day(site.get("date"))
    if when is None:
        return ""
    timing = f", {site['timing']}" if site.get("timing") else ""
    if site.get("which") == "next" or when > today:
        return (f" The next report is due {when:%a %-d %b}{timing} "
                f"(stockanalysis.com).")
    if not reported_on:
        return ""
    if when.isoformat() == reported_on:
        return " stockanalysis.com's earnings date agrees."
    return (f" stockanalysis.com lists the last report on {when:%a %-d %b}"
            f"{timing}, which does not match: check which day the market "
            f"read it.")


def classify(ticker: str, today: _dt.date, *,
             release: dict | None = None,
             news: list[dict] | None = None,
             override: str = "",
             site_earnings: dict | None = None) -> MoveKind:
    """The kind of day, from what was found. Pure: every input is handed in.

    `release` is `sources.earnings_release(...)`'s payload; `news` the
    workbook's headlines with the free feeds merged in; `site_earnings` the
    earnings date stockanalysis.com lists (`{which, date, timing}`).
    """
    dated = []
    for item in news or []:
        head = " ".join(str(item.get("headline") or "").split())
        when = _day(item.get("date"))
        if head and _in_window(when, today):
            dated.append({"date": when.isoformat(), "headline": head,
                          "source": str(item.get("source") or "").strip()})
    dated.sort(key=lambda d: d["date"], reverse=True)

    out = MoveKind(headlines=dated[:HEADLINES_KEPT],
                   site_earnings=dict(site_earnings or {}))
    site_day, site_timing = _site_clock(site_earnings, today)
    rel = release or {}
    filed = _day(rel.get("filed")) if rel.get("status") == "ok" else None
    if filed is not None and _in_window(filed, today):
        out.reported_on = filed.isoformat()
        out.timing = timing_of(rel.get("accepted", ""))
        out.period = str(rel.get("period") or "")
        out.release_url = str(rel.get("exhibit_url") or rel.get("url") or "")
        out.release_text = release_excerpt(rel.get("exhibit_text", ""))

    if override in KINDS:
        out.kind, out.source = override, "operator"
        out.why = f"You set this one as {_NAMES[override]}."
        if override == EARNINGS and not out.reported_on and site_day:
            out.reported_on, out.timing = site_day, site_timing
        return out
    if out.reported_on:
        out.kind, out.source = EARNINGS, f"SEC 8-K item 2.02"
        when = _dt.date.fromisoformat(out.reported_on)
        quarter = (f" for the quarter to {_dt.date.fromisoformat(out.period):%-d %b %Y}"
                   if _day(out.period) else "")
        out.why = (f"{ticker.upper()} reported its results{quarter} on "
                   f"{when:%a %-d %b}"
                   + (f", {out.timing}" if out.timing else "")
                   + " (SEC 8-K, item 2.02). This is an earnings reaction."
                   + _site_note(site_earnings, today, out.reported_on))
        return out
    if site_day:
        out.kind, out.source = EARNINGS, SITE
        out.reported_on, out.timing = site_day, site_timing
        when = _dt.date.fromisoformat(site_day)
        out.why = (f"{ticker.upper()} reported on {when:%a %-d %b}"
                   + (f", {site_timing}" if site_timing else "")
                   + " (the earnings date stockanalysis.com lists; no SEC "
                   "8-K item 2.02 found yet). This is an earnings reaction.")
        return out
    note = _site_note(site_earnings, today, "")
    earn = [d for d in dated if _looks_like_earnings(d["headline"])]
    if earn:
        out.kind, out.source = EARNINGS, "headlines"
        out.reported_on = earn[0]["date"]
        out.why = (f"An earnings headline is dated {earn[0]['date']}: "
                   f"\"{earn[0]['headline'][:120]}\". This is an earnings "
                   f"reaction." + note)
        return out
    if dated:
        out.kind, out.source = NEWS, "headlines"
        out.why = (f"{len(dated)} headline{'s' if len(dated) > 1 else ''} "
                   f"dated in the last {WINDOW_DAYS} days, newest "
                   f"\"{dated[0]['headline'][:120]}\" ({dated[0]['date']})."
                   + note)
        return out
    out.why = (f"No earnings filing and no headline dated in the last "
               f"{WINDOW_DAYS} days: nothing public on file explains this "
               f"move yet." + note)
    return out


_NAMES = {EARNINGS: "an earnings reaction", NEWS: "a company-news day",
          MOVE: "a move with no public cause"}


def detect(ticker: str, today: _dt.date, settings: Any, *,
           news: list[dict] | None = None, override: str = "",
           site_earnings: dict | None = None) -> MoveKind:
    """`classify`, with the SEC asked for the latest earnings 8-K.

    The 8-K is asked for even when the operator has set the kind, so an
    earnings day he named still carries its release into the prompt.
    """
    release = None
    try:
        from pipeline.sources import earnings_release

        since = (today - _dt.timedelta(days=WINDOW_DAYS)).isoformat()
        release = earnings_release(ticker, settings, since=since)
    except Exception as e:                               # noqa: BLE001
        log.warning("the SEC could not say whether %s reported (%s)", ticker, e)
    return classify(ticker, today, release=release, news=news,
                    override=override, site_earnings=site_earnings)


# The beats only the earnings cut has. A script that marks one of them, or
# carries the print, was written to that cut.
EARNINGS_ONLY_BEATS = frozenset({"reported", "expected", "guidance"})


def earnings_shaped(script: Any) -> bool:
    """Whether a SHORT script was written for the earnings cut."""
    marks = {getattr(m, "key", "") for m in getattr(script, "beat_marks", []) or []}
    return bool(marks & EARNINGS_ONLY_BEATS) or bool(
        str(getattr(script, "reported", "") or "").strip())


def kind_name(kind: str) -> str:
    """The kind in the operator's words."""
    return _NAMES.get(kind, kind)
