"""The implosion screener: the bot finds the stories, he never searches.

An implosion long (his OneNote item 44, 11-06) is one famous blow-up told the
way Benjamin tells Knight Capital: funny, and the viewer comes out knowing
how a market works. His word: "i am not going to search myself for cases".
So once a week this reads where blow-ups are listed, ranks them, and has the
local model pitch each of the best in three lines.

Where the stories come from:

* Wikipedia's lists (trading losses, corporate collapses and scandals, stock
  market crashes, and whatever `IMPLOSION_LISTS` adds) are a MAP. A row says a story exists, about
  when and roughly how big. Nothing from Wikipedia goes on screen: the video's
  facts come from the story's documents.
* The article's own external links that point at a primary document (a
  regulator, a prosecutor, a court, an official inquiry) are those documents.
  A story with none has nothing to show, so it ranks low.
* Wikipedia's page views over the last year say whether people still look it
  up, which is the nearest free measure of "people have heard of this".
* The DOJ's national press releases and the SEC's press releases, read back a
  week, catch a big story the day it CLOSES (sentenced, pleaded guilty,
  settled): a known story gets the release as a document and a bump; a big
  one nobody listed yet joins on its own.

The rank, in order of weight: a story that looks closed before one that is
still being fought; documents in hand; fame; size; a round anniversary
coming up. Stories he already made or skipped stay out.

What it never does: decide anything is true. "Looks closed" is the intro's
wording, said as such, for ranking. The pitch is the local model's idea for
the video, labelled as an idea; it is never a fact and never reaches a script
unread. No person is listed beside a story: who is who comes from the
documents when the video is made.
"""

from __future__ import annotations

import json
import logging
import math
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

from config import Settings

log = logging.getLogger(__name__)

STATE_FILE = "implosions.json"
REFRESH_DAYS = 7
CACHE_DAYS = 6
KEEP = 30                 # stories stored after ranking
SHOW = 10                 # stories in /ideas implosions and on the page
ENRICH_MAX = 45           # rows read in full (article + views), biggest first
PITCH_MAX = 10            # stories the local model pitches
MIN_LOSS_USD = 50e6       # a listed row smaller than this is not a story
FRESH_MIN_USD = 250e6     # a release nobody listed must be this big to join
FRESH_DAYS = 8
DOJ_MAX_PAGES = 20
DOJ_REAL_TOTAL = 50_000     # the feed holds ~275k; a stray cached answer, a few hundred
ANNIVERSARY_DAYS = 60
WIKI_GAP_S = 1.0          # between Wikipedia calls (its limit is per address)

DEFAULT_LISTS = ("List of trading losses",
                 "List of corporate collapses and scandals",
                 "List of stock market crashes and bear markets")

WIKI_HTML = "https://en.wikipedia.org/api/rest_v1/page/html/{title}"
WIKI_API = "https://en.wikipedia.org/w/api.php"
VIEWS = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
         "en.wikipedia/all-access/user/{title}/monthly/{start}/{end}")
DOJ_API = "https://www.justice.gov/api/v1/press_releases.json"
SEC_FEEDS = ("https://www.sec.gov/news/pressreleases.rss",
             "https://www.sec.gov/enforcement-litigation/litigation-releases/rss")
# Wikimedia's User-Agent policy: a name/version, a contact (the repo, never
# his email) and the library. The same string `pipeline.broll` sends.
def _agent() -> str:
    try:
        import httpx

        lib = f" httpx/{httpx.__version__}"
    except ImportError:  # pragma: no cover
        lib = ""
    return f"DennisContentMachine/1.0 (https://github.com/Voleq/Content-Machine){lib}"


AGENT = _agent()

# Where a primary document lives. A link to one of these on the story's
# article is a document the video can put on screen.
DOCUMENT_HOSTS = {
    "sec.gov": "regulator", "cftc.gov": "regulator", "finra.org": "regulator",
    "federalreserve.gov": "regulator", "occ.gov": "regulator",
    "occ.treas.gov": "regulator", "fdic.gov": "regulator",
    "consumerfinance.gov": "regulator", "fca.org.uk": "regulator",
    "fsa.gov.uk": "regulator", "bankofengland.co.uk": "regulator",
    "bafin.de": "regulator", "amf-france.org": "regulator",
    "sfc.hk": "regulator", "mas.gov.sg": "regulator", "asic.gov.au": "regulator",
    "osc.ca": "regulator", "osc.gov.on.ca": "regulator",
    "esma.europa.eu": "regulator", "ecb.europa.eu": "regulator",
    "fsa.go.jp": "regulator", "bis.org": "regulator",
    "justice.gov": "prosecutor", "usdoj.gov": "prosecutor", "fbi.gov": "prosecutor",
    "sfo.gov.uk": "prosecutor", "cps.gov.uk": "prosecutor",
    "courtlistener.com": "court", "uscourts.gov": "court",
    "supremecourt.gov": "court", "judiciary.uk": "court",
    "bailii.org": "court", "casetext.com": "court", "law.justia.com": "court",
    "govinfo.gov": "inquiry", "congress.gov": "inquiry", "gao.gov": "inquiry",
    "house.gov": "inquiry", "senate.gov": "inquiry", "fcic.gov": "inquiry",
    "parliament.uk": "inquiry", "publications.parliament.uk": "inquiry",
    "gov.uk": "inquiry", "nationalarchives.gov.uk": "inquiry",
}

# How a story stands, read off its own words. Closed is checked first:
# an intro that says "charged in 2008 and sentenced in 2009" is closed. A
# record's outcome (sentenced, settled) closes a story at any age; an event
# that merely ended (collapsed, lost, went bankrupt) closes it only once it is
# a couple of years old, because the cases come after the collapse.
_OUTCOME = re.compile(
    r"\b(sentenced|convicted|plead(?:s|ed)? guilty|pled guilty|found guilty|acquitted|"
    r"admit(?:s|ted)? (?:his|her|their|its) (?:part|role)|"
    r"settled|agreed to pay|ordered to pay|was fined|were fined|fined|"
    r"civil penalty|penalt(?:y|ies) of|final judgment)\b", re.IGNORECASE)
_ENDED = re.compile(
    r"\b(settlement|liquidat\w+|dissolved|wound down|ceased operations|"
    r"went bankrupt|filed for bankruptcy|bankruptcy|collapsed|was acquired|"
    r"bailed out|rescued|nationali[sz]ed|lost|losses)\b", re.IGNORECASE)
_OPEN = re.compile(
    r"\b(charged|charges|indict\w*|accused|alleg\w+|under investigation|investigating|"
    r"awaiting trial|pending|lawsuit|case filed|on trial|arrested)\b",
    re.IGNORECASE)
SETTLE_YEARS = 2

_YEAR = re.compile(r"\b(1[2-9]\d\d|20\d\d)\b")
_MONTHS = {m: i for i, m in enumerate(
    ("january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"), start=1)}
_MON = "|".join(list(_MONTHS) + [m[:3] for m in _MONTHS] + ["sept"])
_DATE_DMY = re.compile(rf"\b(\d{{1,2}})\s+({_MON})\.?\s+(1[2-9]\d\d|20\d\d)\b", re.I)
_DATE_MDY = re.compile(rf"\b({_MON})\.?\s+(\d{{1,2}}),?\s+(1[2-9]\d\d|20\d\d)\b", re.I)
_CITE = re.compile(r"\[\s*(?:\d+|[a-z]|note \d+|citation needed)\s*\]", re.I)
_PAREN = re.compile(r"\([^)]*\)")

# Rough rates, for RANKING sizes only: a loss is always shown as written.
_FX = {"USD": 1.0, "$": 1.0, "US$": 1.0, "EUR": 1.1, "€": 1.1, "GBP": 1.3,
       "£": 1.3, "JPY": 0.0067, "¥": 0.0067, "CHF": 1.1, "CAD": 0.73,
       "AUD": 0.66, "INR": 0.012, "₹": 0.012, "CNY": 0.14, "HKD": 0.13,
       "SGD": 0.74, "KRW": 0.00073, "BRL": 0.19, "SEK": 0.095, "NOK": 0.094,
       "DKK": 0.15}
_UNITS = {"trillion": 1e12, "tn": 1e12, "billion": 1e9, "bn": 1e9, "b": 1e9,
          "million": 1e6, "mn": 1e6, "mln": 1e6, "m": 1e6}
_MONEY = re.compile(
    r"(US\$|USD|EUR|GBP|JPY|CHF|CAD|AUD|INR|CNY|HKD|SGD|KRW|BRL|SEK|NOK|DKK|"
    r"[$€£¥₹])?\s*(\d[\d,]*(?:\.\d+)?)\s*"
    r"(trillion|billion|million|mln|bn|tn|mn|b|m)?\b", re.I)


# --------------------------------------------------------------------------
# Small readers
# --------------------------------------------------------------------------


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:60]


def clean(text: str) -> str:
    return " ".join(_CITE.sub("", text or "").split())


def money_usd(text: str, *, usd: bool = False) -> float | None:
    """The biggest sum in `text`, in dollars, roughly. `usd` says the column
    is already in dollars, so a bare "0.44 bn" counts. A bare number with no
    unit and no currency is not a sum (it is a year, a count, a page)."""
    best = None
    for m in _MONEY.finditer(_PAREN.sub(" ", text or "")):
        cur, num, unit = (m.group(1) or "").upper(), m.group(2), (m.group(3) or "").lower()
        if not cur and not unit and not usd:
            continue
        try:
            value = float(num.replace(",", "")) * _UNITS.get(unit, 1.0)
        except ValueError:
            continue
        if not unit and value < 1e5:
            continue                       # "2012", "45 minutes", "4 million" is fine
        got = value * _FX.get(cur or "USD", 1.0)
        best = got if best is None else max(best, got)
    return best


def years_in(text: str) -> list[int]:
    return [int(y) for y in _YEAR.findall(text or "")]


def full_date(text: str, near: int | None = None) -> date | None:
    """The first day-month-year in `text`, within a year of `near`."""
    found = sorted(list(_DATE_DMY.finditer(text or "")) + list(_DATE_MDY.finditer(text or "")),
                   key=lambda m: m.start())
    for m in found:
        if m.re is _DATE_DMY:
            d, mon, y = m.group(1), m.group(2), m.group(3)
        else:
            mon, d, y = m.group(1), m.group(2), m.group(3)
        month = next((i for name, i in _MONTHS.items()
                      if name.startswith(mon.lower().rstrip(".")[:3])), 0)
        try:
            got = date(int(y), month, int(d))
        except ValueError:
            continue
        if near is None or abs(got.year - near) <= 1:
            return got
    return None


def status_of(*texts: str, year: int | None = None,
              today: date | None = None) -> tuple[str, str]:
    """("closed" | "open" | "unclear", the word that said so).

    With `year` and `today`, an ended-but-recent story (younger than
    `SETTLE_YEARS`) is "open": its cases are still to come."""
    joined = " ".join(t for t in texts if t)
    m = _OUTCOME.search(joined)
    if m:
        return "closed", m.group(0).lower()
    m = _ENDED.search(joined)
    recent = bool(year and today and year >= today.year - SETTLE_YEARS)
    if m and not recent:
        return "closed", m.group(0).lower()
    o = _OPEN.search(joined)
    if o:
        return "open", o.group(0).lower()
    if recent:
        return "open", "recent"
    return ("closed", m.group(0).lower()) if m else ("unclear", "")


def document_kind(url: str) -> tuple[str, str]:
    """(host, kind) when `url` is a primary document, else ("", "")."""
    try:
        parts = urlparse(url or "")
        host = (parts.hostname or "").lower()
    except ValueError:
        return "", ""
    if parts.scheme not in ("http", "https"):
        return "", ""
    host = host[4:] if host.startswith("www.") else host
    for known, kind in DOCUMENT_HOSTS.items():
        if host == known or host.endswith("." + known):
            if known == "sec.gov" and "/archives/edgar/" in url.lower():
                kind = "filing"
            return known, kind
    return "", ""


def _article(href: str) -> str:
    """'./Knight_Capital_Group' or '/wiki/Knight_Capital_Group' -> the title."""
    if not href or "#cite_note" in href:
        return ""
    for head in ("./", "/wiki/"):
        if href.startswith(head):
            name = unquote(href[len(head):].split("#", 1)[0])
            if name and ":" not in name and not name.startswith("List_of"):
                return name
    return ""


# --------------------------------------------------------------------------
# Parsing a list page
# --------------------------------------------------------------------------

_NAME_HEADS = ("company", "name", "firm", "entity", "organization",
               "organisation", "scheme", "bank", "fund", "event")
_LOSS_HEADS = ("usd equivalent", "loss", "lost", "amount", "assets", "size",
               "value", "usd", "$")
_SKIP_LOSS_HEADS = ("fx rate", "inflation", "2007 usd", "rate")
_YEAR_HEADS = ("year", "date", "when", "period")
_WHAT_HEADS = ("source of loss", "causes", "cause", "type", "activity",
               "business", "description", "notes", "summary", "scandal")
_COUNTRY_HEADS = ("country", "hq", "headquarters", "location")


def _pick(heads: list[str], wanted, skip=()) -> int | None:
    for want in wanted:
        for i, h in enumerate(heads):
            if want in h and not any(s in h for s in skip):
                return i
    return None


def parse_list(html: str, list_title: str) -> list[dict]:
    """Every row of every wikitable on a list page that names a story.

    The columns are found by their header words, so a list that adds a
    column, or a new list with its own layout, still reads. A row with no
    article link and no size is skipped: there is nothing to look up."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html or "", "lxml")
    out: list[dict] = []
    for table in soup.select("table.wikitable"):
        rows = table.find_all("tr")
        if not rows:
            continue
        heads: list[str] = []
        for cell in rows[0].find_all(["th", "td"]):
            span = int(cell.get("colspan") or 1) if str(cell.get("colspan") or "1").isdigit() else 1
            heads += [clean(cell.get_text(" ")).lower()] * span
        col_name = _pick(heads, _NAME_HEADS)
        col_loss = _pick(heads, _LOSS_HEADS, _SKIP_LOSS_HEADS)
        col_year = _pick(heads, _YEAR_HEADS)
        col_what = _pick(heads, _WHAT_HEADS)
        col_country = _pick(heads, _COUNTRY_HEADS)
        if col_name is None:
            col_name = 0
        usd_col = col_loss is not None and ("usd" in heads[col_loss] or "$" in heads[col_loss])
        for row in rows[1:]:
            cells = row.find_all(["th", "td"])
            if len(cells) < max(2, len(heads) - 2) or not row.find("td"):
                continue

            # "See also: Enron scandal" names the story's own article, which
            # tells the story better than the company's page does.
            event = ""
            for hat in row.select(".hatnote, [role=note]"):
                event = event or next((_article(a.get("href", "")) for a in hat.find_all("a")
                                       if _article(a.get("href", ""))), "")
                hat.decompose()

            def text(i):
                return clean(cells[i].get_text(" ")) if i is not None and i < len(cells) else ""

            name = text(col_name)
            if not name or len(name) > 90:
                continue
            article = event or next((_article(a.get("href", "")) for a in cells[col_name].find_all("a")
                                     if _article(a.get("href", ""))), "")
            what = text(col_what)
            loss_text = text(col_loss)
            loss = money_usd(loss_text, usd=usd_col)
            if loss is None and what:
                loss = money_usd(what)
                loss_text = loss_text or (_money_words(what) if loss else "")
            when = text(col_year)
            years = years_in(when)
            year = max(years) if years else None
            if not article and not loss:
                continue
            out.append({
                "name": name, "article": article, "year": year,
                "when": when[:40], "loss_usd": loss, "loss_text": loss_text[:40],
                "what": what[:300], "country": text(col_country)[:40],
                "list": list_title,
            })
    return out


def _money_words(text: str) -> str:
    m = _MONEY.search(_PAREN.sub(" ", text or ""))
    return m.group(0).strip() if m and (m.group(1) or m.group(3)) else ""


# --------------------------------------------------------------------------
# Fetching (fixtures while the screener is mocked)
# --------------------------------------------------------------------------


class Reader:
    """Every read this screener makes, in one place, so a test swaps one
    object and the network is never touched."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.mock = settings.mocking_screener
        self.fixtures = Path(settings.fixtures_dir) / "implosions"
        self.cache = Path(settings.cache_dir) / "implosions"
        self._last = 0.0
        self.calls = 0
        self.failed: list[str] = []

    # -- helpers
    def _fixture(self, name: str):
        path = self.fixtures / name
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return None
        return json.loads(text) if name.endswith(".json") else text

    def _get(self, url: str, *, params=None, wiki=True, what=""):
        try:
            import httpx
        except ImportError:  # pragma: no cover
            return None
        if wiki:
            wait = WIKI_GAP_S - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
        for attempt in range(3):
            self._last = time.monotonic()
            self.calls += 1
            try:
                r = httpx.get(url, params=params, timeout=30.0, follow_redirects=True,
                              headers={"User-Agent": AGENT, "Accept-Encoding": "gzip"})
            except Exception as e:  # noqa: BLE001 - a dead read is a smaller list
                log.warning("implosions: %s unreadable (%s)", what or url, e)
                break
            if r.status_code == 429 and attempt < 2:
                try:
                    pause = min(30.0, float(r.headers.get("retry-after") or 10))
                except ValueError:
                    pause = 10.0
                time.sleep(pause)
                continue
            if r.status_code >= 400:
                log.warning("implosions: %s answered %s", what or url, r.status_code)
                self.failed.append(f"{what or url} ({r.status_code})")
                return None
            return r
        self.failed.append(what or url)
        return None

    # -- the reads
    def list_page(self, title: str) -> str:
        key = title.replace(" ", "_")
        if self.mock:
            return self._fixture(f"lists/{key}.html") or ""
        path = self.cache / "lists" / f"{key}.html"
        try:
            if time.time() - path.stat().st_mtime < CACHE_DAYS * 86400:
                return path.read_text(encoding="utf-8")
        except OSError:
            pass
        r = self._get(WIKI_HTML.format(title=quote(key, safe="")), what=title)
        if r is None:
            return ""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(r.text, encoding="utf-8")
        return r.text

    def article(self, title: str) -> dict:
        """{"title", "extract", "links"}: the intro as plain text and every
        external link on the article."""
        if self.mock:
            got = (self._fixture("articles.json") or {}).get(title)
            return got or {}
        r = self._get(WIKI_API, what=f"article {title}", params={
            "action": "query", "format": "json", "formatversion": "2",
            "prop": "extracts|extlinks", "exintro": "1", "explaintext": "1",
            "ellimit": "max", "redirects": "1", "titles": title.replace("_", " ")})
        if r is None:
            return {}
        try:
            pages = r.json().get("query", {}).get("pages") or []
        except ValueError:
            return {}
        if not pages or pages[0].get("missing"):
            return {}
        page = pages[0]
        return {"title": page.get("title") or title,
                "extract": (page.get("extract") or "")[:3000],
                "links": [link.get("url", "") for link in page.get("extlinks") or []]}

    def views(self, title: str, today: date) -> int | None:
        if self.mock:
            got = (self._fixture("views.json") or {}).get(title)
            return int(got) if got is not None else None
        end = today.replace(day=1) - timedelta(days=1)
        start = (end.replace(day=1) - timedelta(days=330)).replace(day=1)
        r = self._get(VIEWS.format(title=quote(title.replace(" ", "_"), safe=""),
                                   start=start.strftime("%Y%m%d00"),
                                   end=end.strftime("%Y%m%d00")), what=f"views {title}")
        if r is None:
            return None
        try:
            return sum(int(i.get("views") or 0) for i in r.json().get("items") or [])
        except (ValueError, AttributeError):
            return None

    def doj(self, since: date) -> list[dict]:
        """National DOJ releases back to `since`, newest first.

        The API's own quirk (read 11-06): no `page` is the newest fifty and
        `page=1` the fifty after; an explicit `page=0` answers some other,
        older set. So the first call names no page."""
        if self.mock:
            return list((self._fixture("doj.json") or {}).get("results") or [])
        out: list[dict] = []
        seen: set[str] = set()
        total = None
        repeats = 0               # its pages overlap now and then: dedupe
        for page in range(DOJ_MAX_PAGES):
            params = {"pagesize": "50", "sort": "date", "direction": "DESC"}
            if page:
                params["page"] = str(page)
                time.sleep(0.5)
            rows = None
            for attempt in range(2):
                r = self._get(DOJ_API, wiki=False, what="DOJ releases", params=params)
                if r is None:
                    break
                try:
                    body = r.json()
                    count = int(((body.get("metadata") or {}).get("resultset") or {}).get("count") or 0)
                    got = body.get("results") or []
                except (ValueError, TypeError, AttributeError):
                    break
                # A page now and then is some other query's cached answer
                # (a few hundred results, not a quarter million): ask again
                # past the cache.
                stray = (abs(count - total) > total * 0.1 if total and count
                         else 0 < count < DOJ_REAL_TOTAL)
                if stray and attempt == 0:
                    params["t"] = str(int(time.time()))
                    continue
                if stray:
                    break
                total = total or count
                rows = got
                break
            if rows is None:
                if r is None:
                    break
                continue
            new = [x for x in rows if (x.get("uuid") or x.get("url")) not in seen]
            seen.update(x.get("uuid") or x.get("url") for x in rows)
            out += new
            repeats = 0 if new else repeats + 1
            days = sorted(d for d in map(_doj_day, rows) if d)
            if not rows or repeats >= 2 or (days and days[len(days) // 2] < since):
                break
        return out

    def sec(self) -> list[str]:
        """The SEC's press and litigation feeds, as raw XML."""
        if self.mock:
            got = self._fixture("sec_press.xml")
            return [got] if got else []
        from pipeline.filings import _sec_get

        out = []
        for url in SEC_FEEDS:
            r = _sec_get(url, self.settings)
            if r is not None:
                out.append(r.text)
            else:
                self.failed.append(url)
        return out


def _doj_day(row: dict) -> date | None:
    try:
        return datetime.fromtimestamp(int(row.get("date") or 0), timezone.utc).date()
    except (TypeError, ValueError, OSError):
        return None


# --------------------------------------------------------------------------
# Fresh releases
# --------------------------------------------------------------------------

_FINANCE_TOPICS = ("securities", "investment fraud", "financial fraud",
                   "commodities", "bank fraud", "corporate fraud")
_FINANCE_WORDS = re.compile(
    r"\b(ponzi|securities|investors?|investment fraud|hedge fund|trading|"
    r"insider|accounting fraud|crypto\w*|market manipulation|bank fraud)\b", re.I)


def _strip_html(text: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", text or "").split())


def fresh_releases(reader: Reader, today: date) -> list[dict]:
    """Big-money releases of the last week: {"title", "url", "date", "usd",
    "status", "word", "text", "source"}."""
    since = today - timedelta(days=FRESH_DAYS)
    out: list[dict] = []
    for row in reader.doj(since):
        url = row.get("url") or ""
        day = _doj_day(row)
        # National releases and the US attorneys' (the big frauds are mostly
        # theirs: SDNY, EDNY), never a component's news page.
        if not re.search(r"/(opa|usao-[a-z]+)/pr/", url) or (day and day < since):
            continue
        topics = " ".join(t.get("name", "") for t in row.get("topic") or []
                          if isinstance(t, dict)).lower()
        title = clean(row.get("title") or "")
        teaser = _strip_html(row.get("teaser") or row.get("body") or "")[:1200]
        if not (any(t in topics for t in _FINANCE_TOPICS) or _FINANCE_WORDS.search(title)):
            continue
        usd = money_usd(f"{title} {teaser}")
        if not usd or usd < MIN_LOSS_USD:
            continue
        status, word = status_of(title)
        out.append({"title": title, "url": url, "date": day.isoformat() if day else "",
                    "usd": usd, "status": status, "word": word, "text": teaser,
                    "source": "DOJ"})
    for xml in reader.sec():
        for item in _rss_items(xml):
            day = item.get("day")
            if day and day < since:
                continue
            usd = money_usd(f"{item['title']} {item['text']}")
            if not usd or usd < MIN_LOSS_USD:
                continue
            status, word = status_of(item["title"])
            out.append({"title": item["title"], "url": item["url"],
                        "date": day.isoformat() if day else "", "usd": usd,
                        "status": status, "word": word, "text": item["text"][:1200],
                        "source": "SEC"})
    return out


def _rss_items(xml: str) -> list[dict]:
    from email.utils import parsedate_to_datetime

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(xml or "", "xml")
    out = []
    for item in soup.find_all("item"):
        def get(tag):
            node = item.find(tag)
            return node.get_text(" ", strip=True) if node else ""
        try:
            day = parsedate_to_datetime(get("pubDate")).date() if get("pubDate") else None
        except (TypeError, ValueError):
            day = None
        out.append({"title": clean(get("title")), "url": get("link"),
                    "text": _strip_html(get("description")), "day": day})
    return out


_SUFFIXES = re.compile(
    r"\b(group|inc|corp|corporation|company|co|plc|ltd|llc|ag|sa|se|nv|"
    r"holdings?|bank|capital management|management|advisors|partners|"
    r"\(company\)|\(.*?\))\.?$", re.I)


def _core_name(name: str) -> str:
    out = name.strip()
    for _ in range(3):
        out = _SUFFIXES.sub("", out).strip(" ,.")
    return out


def _mentions(story: dict, text: str) -> bool:
    """The release is about this story: it names the company AND the
    story's year. A bank's name alone turns up in releases about anything."""
    core = _core_name(story.get("name") or "")
    if len(core) < 3 or not story.get("year"):
        return False
    return (re.search(rf"\b{re.escape(core)}\b", text or "", re.I) is not None
            and str(story["year"]) in (text or ""))


# --------------------------------------------------------------------------
# Ranking
# --------------------------------------------------------------------------


def anniversary(story: dict, today: date) -> str:
    """'15 years on 1 Aug' when a round anniversary (every 5 years) falls in
    the next two months; 'N years this year' on a round year with no day."""
    year = story.get("year")
    if not year:
        return ""
    day = story.get("date")
    if day:
        try:
            d = date.fromisoformat(day)
        except ValueError:
            d = None
        if d:
            for y in (today.year, today.year + 1):
                n = y - d.year
                try:
                    when = d.replace(year=y)
                except ValueError:
                    when = d.replace(year=y, day=28)
                if n >= 5 and n % 5 == 0 and 0 <= (when - today).days <= ANNIVERSARY_DAYS:
                    return f"{n} years on {when.day} {when.strftime('%b')}"
            return ""
    n = today.year - int(year)
    return f"{n} years this year" if n >= 5 and n % 5 == 0 else ""


def score(story: dict) -> tuple[float, dict]:
    """The rank and its parts. Fame counts half when the article's intro
    never names the story's year: the list linked the company's own page
    (JPMorgan Chase, not its 2012 loss), whose readers came for the bank."""
    loss = story.get("loss_usd") or 0
    views = story.get("views") or 0
    year = story.get("year")
    if views and year and story.get("extract") and str(year) not in story["extract"]:
        views = views / 10 ** 0.5
    docs = len(story.get("documents") or [])
    parts = {
        "size": round(max(0.0, min(3.0, math.log10(loss / 1e8))) if loss > 0 else 0.0, 2),
        "fame": round(max(0.0, min(3.0, math.log10(views / 1e4))) if views >= 1e4 else 0.0, 2),
        "documents": round(min(docs, 4) * 0.6, 2),
        "status": {"closed": 2.0, "unclear": 0.0, "open": -3.0}.get(story.get("status"), 0.0),
        "anniversary": 1.5 if " on " in (story.get("anniversary") or "")
        else 0.5 if story.get("anniversary") else 0.0,
        "fresh": 1.0 if story.get("fresh") else 0.0,
    }
    return round(sum(parts.values()), 2), parts


# --------------------------------------------------------------------------
# The pitch
# --------------------------------------------------------------------------

PITCH_SYSTEM = (
    "You pitch videos for a finance YouTube channel. The host is Dennis, a dry, "
    "funny cartoon analyst. The format: one real financial blow-up, told so the "
    "viewer laughs AND comes out understanding how a market, a trade or a rule "
    "works. For the story you are given, write exactly three lines:\n"
    "DETOUR: a piece of history, science or everyday life, outside this story, "
    "that the video could open a detour on and pay off later. One sentence.\n"
    "LESSON: the one mechanism the viewer learns, in plain words. One sentence.\n"
    "JOKE: one dry joke about how absurd the situation was. One sentence. Never "
    "joke that a named person did something the story does not say they did, "
    "nothing about anyone's looks, family or health, no slurs.\n"
    "Use only what you are given and general knowledge you are sure of; leave "
    "out any number you were not given. Nothing else, no preamble.")
_PITCH_LINE = re.compile(r"^\s*\**\s*(DETOUR|LESSON|JOKE)\s*\**\s*[:\-–]\s*\**\s*(.+)$", re.I)


def pitch(story: dict, settings: Settings) -> dict:
    """{"detour", "lesson", "joke"} from the local model, or {} when it is
    not there. Free: local only, never a hosted fallback."""
    from pipeline.llm import OLLAMA, chat_result

    facts = [f"Story: {story['name']}" + (f" ({story['year']})" if story.get("year") else "")]
    if story.get("loss_text"):
        facts.append(f"Size, as listed: {story['loss_text']}")
    if story.get("what"):
        facts.append(f"What the list says: {story['what'][:300]}")
    if story.get("extract"):
        facts.append(f"Summary: {story['extract'][:1200]}")
    got = chat_result("\n".join(facts), settings, system=PITCH_SYSTEM,
                      purpose="implosion-pitch", providers=[OLLAMA])
    if not got:
        return {}
    out = {}
    for line in got.text.splitlines():
        m = _PITCH_LINE.match(line)
        if m and m.group(1).lower() not in out:
            out[m.group(1).lower()] = m.group(2).strip().strip('"')[:220]
    return out if len(out) >= 2 else {}


# --------------------------------------------------------------------------
# The run
# --------------------------------------------------------------------------


def _path(settings: Settings) -> Path:
    return Path(settings.state_dir) / STATE_FILE


def load(settings: Settings) -> dict:
    from pipeline.standing import _read

    got = _read(_path(settings), {})
    return got if isinstance(got, dict) else {}


def lists_wanted(settings: Settings) -> list[str]:
    raw = (settings.implosion_lists or "").strip()
    titles = [t.strip() for t in raw.split("|") if t.strip()] if raw else []
    return titles or list(DEFAULT_LISTS)


def due(settings: Settings, now: datetime | None = None) -> bool:
    """On, live, and nothing written in the last week."""
    if not settings.implosions_enabled or settings.mocking_screener:
        return False
    now = now or datetime.now(timezone.utc)
    try:
        at = datetime.fromisoformat(load(settings)["written_at"])
    except (KeyError, TypeError, ValueError):
        return True
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return now - at >= timedelta(days=REFRESH_DAYS)


def _merge(rows: list[dict]) -> list[dict]:
    """One story per article and year (a company on two lists is one story;
    the same company in two different years is two)."""
    seen: dict[str, dict] = {}
    for row in rows:
        key = f"{(row.get('article') or slug(row['name'])).lower()}|{row.get('year') or ''}"
        if key in seen:
            have = seen[key]
            have["lists"] = sorted(set(have["lists"]) | {row["list"]})
            if (row.get("loss_usd") or 0) > (have.get("loss_usd") or 0):
                have["loss_usd"], have["loss_text"] = row["loss_usd"], row["loss_text"]
            have["what"] = have.get("what") or row.get("what")
            continue
        row = dict(row)
        row["lists"] = [row.pop("list")]
        row["id"] = slug(f"{row['name']} {row.get('year') or ''}")
        seen[key] = row
    return list(seen.values())


def refresh(settings: Settings, *, reader: Reader | None = None,
            now: datetime | None = None, pitches: bool = True) -> dict:
    """Read, rank, pitch, store. Returns the stored payload."""
    from pipeline.standing import _write

    now = now or datetime.now(timezone.utc)
    today = now.date()
    reader = reader or Reader(settings)
    before = load(settings)
    skipped = set(before.get("skipped") or [])
    done = set(before.get("done") or [])

    rows: list[dict] = []
    read_lists = []
    for title in lists_wanted(settings):
        html = reader.list_page(title)
        got = parse_list(html, title) if html else []
        if got:
            read_lists.append(title)
        rows += got
    if not read_lists:
        # Nothing answered: keep the last list and try again at the next
        # check (the date is left alone, so the weekly read stays due).
        kept = dict(before)
        kept["failed"] = reader.failed[:12]
        kept["tried_at"] = now.isoformat()
        if before:
            _write(_path(settings), kept)
        return {**kept, "lists": [], "stories": list(before.get("stories") or [])}
    stories = [s for s in _merge(rows)
               if (s.get("loss_usd") or 0) >= MIN_LOSS_USD or not s.get("loss_usd")]
    stories = [s for s in stories if s["id"] not in skipped and s["id"] not in done]
    # Read the biggest in full; a row with no size only when there is room.
    stories.sort(key=lambda s: -(s.get("loss_usd") or 0))
    sized = [s for s in stories if s.get("loss_usd")]
    unsized = [s for s in stories if not s.get("loss_usd")]
    full = (sized + unsized)[:ENRICH_MAX]

    fresh = fresh_releases(reader, today)
    for item in fresh:
        hit = next((s for s in stories if _mentions(s, f"{item['title']} {item['text'][:1200]}")), None)
        if hit is not None:
            hit["fresh"] = {k: item[k] for k in ("title", "url", "date", "source", "word")}
            if hit not in full:
                full.append(hit)
            continue
        if item["usd"] < FRESH_MIN_USD:
            continue
        sid = slug(item["title"])
        if sid in skipped or sid in done:
            continue
        story = {"id": sid, "name": item["title"][:90], "article": "",
                 "year": int(item["date"][:4]) if item["date"] else today.year,
                 "when": item["date"], "loss_usd": item["usd"],
                 "loss_text": _money_words(f"{item['title']} {item['text']}"),
                 "what": item["text"][:300], "country": "United States",
                 "lists": [f"{item['source']} release"],
                 "fresh": {k: item[k] for k in ("title", "url", "date", "source", "word")}}
        stories.append(story)
        full.append(story)

    for story in full:
        title = story.get("article")
        if title:
            art = reader.article(title)
            story["extract"] = art.get("extract", "")
            docs = []
            for url in art.get("links") or []:
                host, kind = document_kind(url)
                if host and url not in {d["url"] for d in docs}:
                    docs.append({"url": url, "host": host, "kind": kind})
            story["documents"] = docs[:12]
            story["views"] = reader.views(title, today)
        else:
            story.setdefault("documents", [])
            story.setdefault("extract", "")
        if story.get("fresh"):
            f = story["fresh"]
            host, kind = document_kind(f["url"])
            if f["url"] and f["url"] not in {d["url"] for d in story["documents"]}:
                story["documents"].insert(0, {"url": f["url"], "host": host or f["source"].lower(),
                                              "kind": kind or "release"})
        status, word = status_of(story.get("extract", "")[:1500], story.get("when", ""),
                                 story.get("what", ""), year=story.get("year"), today=today)
        f = story.get("fresh") or {}
        if f:
            got = status_of(f["title"], year=story.get("year"), today=today)
            if got[0] == "closed" and f.get("word"):
                status, word = got
            elif status != "closed":
                status, word = got
        story["status"], story["status_word"] = status, word
        d = full_date(story.get("when", ""), story.get("year")) or full_date(
            story.get("extract", ""), story.get("year"))
        story["date"] = d.isoformat() if d else ""
        story["anniversary"] = anniversary(story, today)
        story["score"], story["parts"] = score(story)

    ranked = sorted(full, key=lambda s: -s["score"])[:KEEP]
    if pitches:
        for story in ranked[:PITCH_MAX]:
            story["pitch"] = pitch(story, settings)
    for story in ranked:
        story["extract"] = (story.get("extract") or "")[:600]
    payload = {"written_at": now.isoformat(), "mock": bool(reader.mock),
               "lists": read_lists, "failed": reader.failed[:12],
               "stories": ranked, "skipped": sorted(skipped), "done": sorted(done)}
    _write(_path(settings), payload)
    return payload


def shown(settings: Settings, limit: int = SHOW) -> list[dict]:
    data = load(settings)
    gone = set(data.get("skipped") or []) | set(data.get("done") or [])
    return [s for s in data.get("stories") or []
            if isinstance(s, dict) and s.get("id") not in gone][:limit]


def mark(settings: Settings, story_id: str, how: str) -> bool:
    """`how` = "skipped" | "done": the story stays out of later lists.
    "back" takes it off both."""
    from pipeline.standing import _write

    data = load(settings)
    if not data:
        return False
    ids = {s.get("id") for s in data.get("stories") or []}
    if story_id not in ids and story_id not in set(data.get("skipped") or []) | set(data.get("done") or []):
        return False
    for key in ("skipped", "done"):
        have = set(data.get(key) or [])
        if how == key:
            have.add(story_id)
        elif how == "back":
            have.discard(story_id)
        data[key] = sorted(have)
    _write(_path(settings), data)
    return True


# --------------------------------------------------------------------------
# Making one: the story's code and finding it again
# --------------------------------------------------------------------------

# An implosion's workspace is filed under a story code where a stock's is
# filed under its ticker: `IMP-KNIGHT12`. The prefix is what every
# ticker-shaped step (prices, the filings read, the site, the workbook)
# checks to stand aside, and no exchange lists a symbol that starts with it.
STORY_PREFIX = "IMP-"
_GENERIC = {"the", "long", "term", "first", "new", "national", "american",
            "united", "general", "global", "capital", "bank", "trust", "fund",
            "financial", "securities", "investment", "investments", "group"}


def is_story_code(ticker: str) -> bool:
    return str(ticker or "").strip().upper().startswith(STORY_PREFIX)


def code_word(code: str) -> str:
    """The telling word back out of a story code: `IMP-KNIGHT12B` is
    KNIGHT. What the room's papers say where a ticker would go."""
    m = re.match(rf"^{STORY_PREFIX}(.+?)\d{{2}}[A-Z0-9]?$", str(code or "").upper())
    return m.group(1) if m else str(code or "").upper().removeprefix(STORY_PREFIX)


def story_code(story: dict) -> str:
    """`IMP-` + the name's telling word (or its initials) + the year's two
    digits: Knight Capital Group 2012 is `IMP-KNIGHT12`, Long-Term Capital
    Management 1998 is `IMP-LTCM98`."""
    words = [w for w in re.split(r"[^A-Za-z0-9]+", _core_name(story.get("name") or ""))
             if w]
    pick = next((w for w in words if w.lower() not in _GENERIC and len(w) > 2
                 and not w.isdigit()), "")
    if not pick:
        pick = "".join(w[0] for w in re.split(r"[^A-Za-z0-9]+", story.get("name") or "")
                       if w) or "STORY"
    year = str(story.get("year") or "")[-2:]
    # At most fourteen characters: a letter for a second story with the same
    # code still fits the fifteen a ticker may have (`bot/handlers._TICKER_RE`).
    return f"{STORY_PREFIX}{pick.upper()[:8]}{year}"


def find(settings: Settings, arg: str) -> dict | None:
    """The story `/new implosion` names: its number in the list he was shown,
    its id, or a piece of its name. Stories he made or skipped are found by
    id or name too, so one can be made again on purpose."""
    arg = (arg or "").strip()
    if not arg:
        return None
    rows = shown(settings)
    if arg.isdigit():
        n = int(arg)
        return rows[n - 1] if 1 <= n <= len(rows) else None
    everything = [s for s in load(settings).get("stories") or [] if isinstance(s, dict)]
    for s in everything:
        if s.get("id") == arg:
            return s
    low = arg.lower()
    for pool in (rows, everything):
        for s in pool:
            if low in (s.get("name") or "").lower():
                return s
    return None


# --------------------------------------------------------------------------
# What he reads
# --------------------------------------------------------------------------


def _views_words(n) -> str:
    if not n:
        return ""
    if n >= 1e6:
        return f"{n / 1e6:.1f}m views a year"
    if n >= 1e3:
        return f"{n / 1e3:.0f}k views a year"
    return f"{n} views a year"


def status_words(story: dict) -> str:
    word = story.get("status_word") or ""
    if story.get("status") == "closed":
        return f"looks closed ({word})" if word else "looks closed"
    if story.get("status") == "open":
        return "still open: wait for it to close" if word in ("", "recent") \
            else f"still open ({word}): wait for it to close"
    return "status unclear"


def line_for(i: int, story: dict) -> str:
    head = f"{i}. {story['name']}"
    if story.get("year") and str(story["year"]) not in story["name"]:
        head += f" ({story['year']})"
    if story.get("loss_text"):
        head += f" · {story['loss_text']}"
    docs = story.get("documents") or []
    hosts = sorted({d["host"] for d in docs})
    bits = [status_words(story),
            f"{len(docs)} document{'s' if len(docs) != 1 else ''}"
            + (f" ({', '.join(hosts[:3])})" if hosts else ""),
            _views_words(story.get("views")), story.get("anniversary") or ""]
    if story.get("fresh"):
        f = story["fresh"]
        bits.append(f"in the news {f.get('date') or 'this week'}: {f['source']} "
                    f"'{f['title'][:70]}'")
    lines = [head, "   " + " · ".join(b for b in bits if b)]
    p = story.get("pitch") or {}
    for key, label in (("detour", "detour"), ("lesson", "you learn"), ("joke", "joke")):
        if p.get(key):
            lines.append(f"   {label}: {p[key][:160]}")
    return "\n".join(lines)


def reply_text(settings: Settings) -> str:
    data = load(settings)
    rows = shown(settings)
    if not rows:
        if data.get("written_at"):
            return ("💥 The last read found nothing new. "
                    "/ideas implosions refresh reads again.")
        return ("💥 No implosion stories read yet. The weekly read runs by itself; "
                "/ideas implosions refresh reads now (a few minutes).")
    when = data.get("written_at", "")[:10]
    head = (f"💥 Implosion stories, best first (read {when}"
            + (", FIXTURE DATA: mock mode" if data.get("mock") else "") + ")")
    body = "\n".join(line_for(i, s) for i, s in enumerate(rows, start=1))
    tail = ("The pitches are the local model's ideas, not facts; the video's "
            "facts come from the documents. /ideas implosions skip N hides one.")
    if data.get("failed"):
        tail += f"\nUnread this time: {', '.join(data['failed'][:4])}."
    return f"{head}\n{body}\n{tail}"
