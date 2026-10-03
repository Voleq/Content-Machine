"""The news beat's own material: the release itself, and the wires (item 5).

A short's news beat was the writer's headline typed on a band. Two better
pictures were drawn for it and never filled:

* `paper/press-release`, the release as a document: masthead, dateline,
  headline and its opening paragraph. The operator's News sheet already
  carries a link for every headline, so the release is OPENED, not guessed
  at: the row whose headline is the video's own news, fetched, and its first
  real paragraph lifted off the page.
* `paper/wire-strip-3` and `-5`, the week's headlines as a ticker with
  times, which is the News sheet itself.

Nothing here writes a word. Every line on either card is a line that was
published, and a page that cannot be read leaves the beat its typed band.

Fetching is plain HTTP. A page that refuses a script is asked again as a
browser would ask (`curl_cffi`, already installed for the price feed), and
past that it is left alone: no headless browser, and nothing is ever
scraped off a data terminal.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse

log = logging.getLogger(__name__)

# The press-release card's boxes, as the kit declares them. The body is
# two lines of 74 at 30 px: its `maxChars` says 438, and 377 characters set
# into those two lines came out at 12 px, so the lines are the budget.
RELEASE_BODY_CHARS = 2 * 74
RELEASE_SOURCE_CHARS = 23
RELEASE_DATE_CHARS = 21

_STOP = frozenset("""a an the and or of to in on at for with by from as is are
was were be been its it this that after over into up down new says said
inc corp corporation co ltd plc llc group holdings company""".split())

# A paragraph that is page furniture rather than the release.
_FURNITURE = re.compile(
    r"cookie|javascript|subscribe|sign up|newsletter|all rights reserved|"
    r"privacy policy|terms of (use|service)|click here|advertisement",
    re.I)


def _words(text: str, drop: set[str]) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", str(text).lower())
            if w not in _STOP and w not in drop and len(w) > 1}


def match_row(news: list[dict], headline: str, *, company: str = "",
              ticker: str = "") -> dict | None:
    """The News row that IS this headline, or None.

    By shared words, with the company's own name and ticker taken out: every
    row on the sheet names the company, so those words say nothing about
    which story it is. Two shared words and half the headline's own, or it is
    not the same story, and a release for a different story is worse than
    none.
    """
    drop = _words(company, set()) | {ticker.lower()}
    want = _words(headline, drop)
    if not want:
        return None
    best, best_n = None, 0
    for row in news or ():
        got = _words(row.get("headline", ""), drop)
        n = len(want & got)
        if n > best_n:
            best, best_n = row, n
    if best is None or best_n < 2 or best_n * 2 < len(want):
        return None
    return best


# ---------------------------------------------------------------------------
# Opening the page
# ---------------------------------------------------------------------------

def _cache_file(settings, url: str) -> Path:
    key = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
    return Path(settings.cache_dir) / "news_pages" / f"{key}.json"


def _mock_html(settings, url: str) -> str | None:
    """MOCK_MODE reads a fixture page named by the link's last path part."""
    slug = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
    page = Path(settings.fixtures_dir) / "news_pages" / f"{slug}.html"
    return page.read_text(encoding="utf-8") if page.exists() else None


def _get(url: str) -> str | None:
    """The page, by plain HTTP, then as a browser; None when neither works."""
    import httpx

    headers = {"User-Agent": "Mozilla/5.0 (compatible; dennis-content-machine/1.0)",
               "Accept": "text/html,application/xhtml+xml"}
    try:
        r = httpx.get(url, headers=headers, timeout=20.0, follow_redirects=True)
        if r.status_code == 200 and "html" in r.headers.get("content-type", "html"):
            return r.text
        log.info("release %s: HTTP %s, asking as a browser", url, r.status_code)
    except httpx.HTTPError as e:
        log.info("release %s: %s, asking as a browser", url, e)
    try:
        from curl_cffi import requests as creq

        r = creq.get(url, impersonate="chrome", timeout=20)
        if r.status_code == 200:
            return r.text
        log.info("release %s: refused (HTTP %s); the beat keeps its band",
                 url, r.status_code)
    except Exception as e:                              # noqa: BLE001
        log.info("release %s: %s; the beat keeps its band", url, e)
    return None


def read_page(html: str) -> dict[str, str]:
    """`{title, site, body}` off a release page. `body` is the first
    paragraph that reads as the story: long enough to be one, and not the
    page's cookie banner."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside",
                     "form", "noscript"]):
        tag.decompose()

    def meta(*names: str) -> str:
        for n in names:
            m = (soup.find("meta", attrs={"property": n})
                 or soup.find("meta", attrs={"name": n}))
            if m and m.get("content"):
                return " ".join(str(m["content"]).split())
        return ""

    h1 = soup.find("h1")
    title = (" ".join(h1.get_text(" ").split()) if h1 else "") \
        or meta("og:title", "twitter:title") \
        or (" ".join(soup.title.get_text(" ").split()) if soup.title else "")
    body = ""
    for p in soup.find_all("p"):
        text = " ".join(p.get_text(" ").split())
        if len(text) >= 80 and len(text.split()) >= 12 \
                and not _FURNITURE.search(text):
            body = text
            break
    return {"title": title, "site": meta("og:site_name"), "body": body}


def fetch_release(url: str, settings) -> dict[str, str] | None:
    """The release at `url`, read once and cached; None when it cannot be."""
    if not url or not str(url).startswith(("http://", "https://")):
        return None
    cache = _cache_file(settings, url)
    if cache.exists():
        try:
            got = json.loads(cache.read_text(encoding="utf-8"))
            return got or None
        except (OSError, ValueError):
            pass
    html = _mock_html(settings, url) if settings.mock_mode else _get(url)
    got = read_page(html) if html else {}
    if not got.get("body"):
        got = {}
    if not settings.mock_mode or got:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(got, indent=2), encoding="utf-8")
    return got or None


# ---------------------------------------------------------------------------
# Fitting it to the cards
# ---------------------------------------------------------------------------

# What opens nearly every release and says nothing the card does not: the
# dateline ("SPRINGFIELD, July 6, 2026 --", "July 14 (Reuters) -"), the
# listing ("(NASDAQ: EXMPL)") and the boilerplate description of the company
# between its name and its verb (", a provider of routing software,").
_DATELINE = re.compile(
    r"^\s*(?:[A-Z][A-Za-z .'-]{1,40},\s*){0,2}"
    r"(?:[A-Z][a-z]{2,8}\.? \d{1,2}(?:,? \d{4})?)?"
    r"\s*(?:\([A-Za-z ]+\))?\s*(?:--|-|–|—)\s+")
_LISTING = re.compile(r"\s*\((?:NASDAQ|NYSE|Nasdaq|NYSE American|TSX|LSE|OTC\w*)"
                      r"\s*:\s*[A-Z.]+\)")
_APPOSITIVE = re.compile(r"^([A-Z][^,]{1,60}),\s+(?:a|an|the)\s+[^,]{3,160},\s+")


def lead(text: str) -> str:
    """A release's first paragraph without its dateline, its listing and the
    company's boilerplate self-description. Only whole clauses come out; no
    word of what was announced is changed."""
    text = " ".join(str(text or "").split())
    text = _DATELINE.sub("", text, count=1)
    text = _LISTING.sub("", text)
    text = _APPOSITIVE.sub(r"\1 ", text, count=1)
    return text[:1].upper() + text[1:] if text else text


def fit_sentences(text: str, limit: int) -> str | None:
    """As many whole sentences as fit in `limit`; never a cut sentence."""
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text or None
    out = ""
    for s in re.split(r"(?<=[.!?])\s+(?=[A-Z\"“])", text):
        if len(out) + len(s) + (1 if out else 0) > limit:
            break
        out = f"{out} {s}".strip()
    return out or None


def fit_headline(text: str, limit: int) -> str | None:
    """A headline in `limit` characters: whole, or up to its first clause
    break (a comma, a colon, a dash). Never cut mid-phrase."""
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text or None
    for m in re.finditer(r"\s*(?:,|:|;|\s[-–—]\s)\s*", text):
        head = text[:m.start()].strip()
        if 12 <= len(head) <= limit:
            return head
    return None


def _as_date(raw) -> date | None:
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    try:
        return datetime.strptime(str(raw)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def site_name(row: dict, page: dict) -> str:
    """Who published it, in the masthead's 23 characters."""
    for name in (page.get("site"), row.get("source")):
        if name and len(name) <= RELEASE_SOURCE_CHARS:
            return name
    host = urlparse(row.get("url", "")).netloc.removeprefix("www.")
    return host[:RELEASE_SOURCE_CHARS]


def release_card(data, script, settings) -> dict[str, str] | None:
    """`paper/press-release`, filled from the release the video is about."""
    if data is None or script is None:
        return None
    heads = getattr(script, "headlines", None) or []
    if not heads:
        return None
    row = match_row(getattr(data, "news", []) or [], heads[0].text,
                    company=str(data.get("company_name") or ""),
                    ticker=str(data.get("ticker") or script.ticker or ""))
    if row is None or not row.get("url"):
        return None
    page = fetch_release(row["url"], settings)
    if not page:
        return None
    body = fit_sentences(lead(page["body"]), RELEASE_BODY_CHARS)
    if not body:
        return None
    when = _as_date(row.get("date"))
    return {
        "source": site_name(row, page),
        "date": (f"{when.day} {when:%B %Y}"[:RELEASE_DATE_CHARS] if when else ""),
        "headline": page.get("title") or row.get("headline", ""),
        "body": body,
        "url": row["url"],
    }


def wire_rows(data, n: int, limit: int) -> list[dict[str, str]] | None:
    """The `n` latest News rows as a wire strip prints them, oldest first.

    A headline too long for the strip is cut at its first clause break or
    left out; with fewer than `n` rows that fit, there is no strip, because a
    strip with an empty slot is a broken drawing.
    """
    if data is None:
        return None
    rows = []
    for row in sorted(getattr(data, "news", []) or [],
                      key=lambda r: str(r.get("date", "")), reverse=True):
        head = fit_headline(row.get("headline", ""), limit)
        when = _as_date(row.get("date"))
        if not head or when is None:
            continue
        rows.append({"time": f"{when:%b} {when.day}", "headline": head,
                     "source": str(row.get("source") or "")[:51]})
        if len(rows) == n:
            break
    if len(rows) < n:
        return None
    return list(reversed(rows))
