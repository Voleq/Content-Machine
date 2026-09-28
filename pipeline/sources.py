"""Free data sources (P3.4).

The paid export is the spine of a video, but it says nothing about *today*.
These are the free feeds that make short-form possible without a data
terminal, all built on the patterns `filings.py` already established: the
same rate-limited EDGAR client, disk caching, and — the rule that matters —
**degrading to "unavailable" rather than failing a run**.

What is here:

* **8-K + EX-99.1** — the earnings press release. The 8-K itself is a cover
  page; the numbers live in the exhibit, which is why the exhibit is the
  thing worth fetching. This is the reliable automated spine for
  `/headline earnings`.
* **Form 4** — insider transactions. Pairs with the `insider-selling` kit
  asset and is a strong short hook on its own.
* **FRED** — CPI, rates, jobs, for `/headline macro`, replacing scraped
  headlines with the actual series.
* **Company IR RSS** — press releases, the news for a name too small to
  make the headlines.

Every fetch goes through one cache with a per-source TTL, because these
endpoints are either rate-limited (SEC) or key-limited (FRED), and because
re-asking for a quarterly filing every fifteen minutes is rude.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

from config import Settings

log = logging.getLogger(__name__)

UNAVAILABLE = "unavailable"

# Per-source cache lifetimes. A macro series moves monthly; a price-moving
# 8-K does not wait.
TTL_SECONDS = {
    "8k": 900,          # 15 min — an earnings 8-K is the time-critical one
    "form4": 3600,
    "fred": 3600 * 6,
    "rss": 1800,
}


# --------------------------------------------------------------------------
# Cache.
# --------------------------------------------------------------------------


def _cache_path(settings: Settings, kind: str, key: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", key)[:80]
    return settings.cache_dir / "sources" / kind / f"{safe}.json"


def cached(settings: Settings, kind: str, key: str) -> Any | None:
    p = _cache_path(settings, kind, key)
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    ttl = TTL_SECONDS.get(kind, 3600)
    if time.time() - float(payload.get("_at", 0)) > ttl:
        return None
    return payload.get("data")


def store(settings: Settings, kind: str, key: str, data: Any) -> Any:
    p = _cache_path(settings, kind, key)
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        p.write_text(json.dumps({"_at": time.time(), "data": data}, default=str), encoding="utf-8")
    except OSError as e:
        log.warning("could not cache %s/%s: %s", kind, key, e)
    return data


# --------------------------------------------------------------------------
# EDGAR: 8-K + EX-99.1, Form 4.
# --------------------------------------------------------------------------


@dataclass
class Filing:
    ticker: str
    form: str
    filed: str
    accession: str
    url: str
    title: str = ""

    def to_json(self) -> dict:
        return asdict(self)


def _recent(cik: str, settings: Settings) -> dict:
    from pipeline.filings import _load_submissions

    subs = _load_submissions(cik, settings)
    return ((subs or {}).get("filings") or {}).get("recent") or {}


def _cik_for(ticker: str, settings: Settings) -> str | None:
    from pipeline.filings import _load_company_tickers, resolve_cik

    return resolve_cik(ticker, _load_company_tickers(settings))


def _filings_of(ticker: str, settings: Settings, forms: Sequence[str],
                limit: int = 5) -> list[Filing]:
    """The most recent filings of the given forms. [] when anything is off."""
    cik = _cik_for(ticker, settings)
    if not cik:
        return []
    recent = _recent(cik, settings)
    out: list[Filing] = []
    names = recent.get("form") or []
    accns = recent.get("accessionNumber") or []
    docs = recent.get("primaryDocument") or []
    dates = recent.get("filingDate") or []
    for i, form in enumerate(names):
        if form not in forms:
            continue
        if i >= len(accns) or i >= len(docs) or not docs[i]:
            continue
        nodash = accns[i].replace("-", "")
        out.append(Filing(
            ticker=ticker.upper(), form=form,
            filed=dates[i] if i < len(dates) else "",
            accession=accns[i],
            url=(f"{settings.sec_base_url}/Archives/edgar/data/"
                 f"{int(cik)}/{nodash}/{docs[i]}")))
        if len(out) >= limit:
            break
    return out


def latest_8k(ticker: str, settings: Settings) -> dict:
    """The most recent 8-K, plus its EX-99.1 exhibit when there is one.

    The 8-K itself is a cover page — "on this date the registrant issued a
    press release" — and the numbers are in the exhibit. Fetching only the
    8-K gets you a document that says a thing happened and not what it was.
    """
    key = ticker.upper()
    hit = cached(settings, "8k", key)
    if hit is not None:
        return hit
    if settings.mock_mode:
        return store(settings, "8k", key, _fixture(settings, "sec_8k.json", {
            "status": UNAVAILABLE, "ticker": key}))
    filings = _filings_of(ticker, settings, ("8-K", "8-K/A"), limit=1)
    if not filings:
        return store(settings, "8k", key,
                     {"status": UNAVAILABLE, "ticker": key,
                      "reason": "no recent 8-K on file"})
    f = filings[0]
    payload = {"status": "ok", **f.to_json(), "exhibit_url": "", "exhibit_text": ""}
    exhibit = _find_exhibit(f, settings)
    if exhibit:
        payload["exhibit_url"] = exhibit["url"]
        payload["exhibit_text"] = exhibit["text"][:20000]
    return store(settings, "8k", key, payload)


def _find_exhibit(filing: Filing, settings: Settings) -> dict | None:
    """The EX-99.1 press release inside an 8-K's filing index."""
    from pipeline.filings import _sec_get

    base = filing.url.rsplit("/", 1)[0]
    resp = _sec_get(f"{base}/index.json", settings)
    if resp is None:
        return None
    try:
        items = resp.json()["directory"]["item"]
    except (KeyError, ValueError, TypeError):
        return None
    for item in items:
        name = str(item.get("name", "")).lower()
        if "ex99" in name.replace("-", "").replace("_", "") or "ex-99" in name:
            doc = _sec_get(f"{base}/{item['name']}", settings)
            if doc is None:
                continue
            return {"url": f"{base}/{item['name']}", "text": _strip_html(doc.text)}
    return None


def _strip_html(html: str) -> str:
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = (text.replace("&nbsp;", " ").replace("&amp;", "&")
                .replace("&lt;", "<").replace("&gt;", ">").replace("&#8217;", "'"))
    return re.sub(r"\s+", " ", text).strip()


# Form 4 transaction codes worth distinguishing. P is an open-market purchase
# — the one that actually means something, since sales are mostly scheduled.
_CODE_MEANING = {
    "P": "open-market purchase",
    "S": "open-market sale",
    "A": "grant/award",
    "M": "option exercise",
    "F": "shares withheld for tax",
    "D": "disposition to the issuer",
}


def insider_transactions(ticker: str, settings: Settings,
                         limit: int = 8) -> dict:
    """Recent Form 4s. Pairs with the `insider-selling` kit asset.

    The read that matters is P versus everything else: routine grants,
    exercises and tax withholding dominate the feed and mean very little,
    while an open-market purchase is somebody spending their own money.
    """
    key = ticker.upper()
    hit = cached(settings, "form4", key)
    if hit is not None:
        return hit
    if settings.mock_mode:
        return store(settings, "form4", key,
                     _fixture(settings, "sec_form4.json",
                              {"status": UNAVAILABLE, "ticker": key}))
    filings = _filings_of(ticker, settings, ("4", "4/A"), limit=limit)
    if not filings:
        return store(settings, "form4", key,
                     {"status": UNAVAILABLE, "ticker": key,
                      "reason": "no recent Form 4 on file"})
    return store(settings, "form4", key, {
        "status": "ok", "ticker": key,
        "filings": [f.to_json() for f in filings],
        "count": len(filings),
    })


# --------------------------------------------------------------------------
# FRED: the macro series.
# --------------------------------------------------------------------------

# The handful worth having for `/headline macro`, by what you'd call them.
FRED_SERIES = {
    "cpi": "CPIAUCSL",
    "core_cpi": "CPILFESL",
    "unemployment": "UNRATE",
    "payrolls": "PAYEMS",
    "fed_funds": "FEDFUNDS",
    "ten_year": "DGS10",
    "two_year": "DGS2",
    "gdp": "GDPC1",
    "pce": "PCEPI",
}

# Series that are already a rate. Their change is in percentage points: the
# unemployment rate going from 4.1 to 4.3 is up two tenths of a point, and
# "+4.9%" is a number a script would read out as if it were the rate.
RATE_SERIES = frozenset({"UNRATE", "FEDFUNDS", "DGS10", "DGS2"})


def fred_series(name: str, settings: Settings, *, limit: int = 13) -> dict:
    """One macro series, most recent observations last.

    `name` may be a friendly key (`cpi`) or a raw FRED id. No key configured
    means unavailable, not an error — the macro format simply falls back to
    the operator's own headline text.
    """
    series_id = FRED_SERIES.get(name.lower(), name.upper())
    hit = cached(settings, "fred", series_id)
    if hit is not None:
        return hit
    if settings.mock_mode:
        return store(settings, "fred", series_id,
                     _fixture(settings, "fred.json",
                              {"status": UNAVAILABLE, "series": series_id}))
    if not settings.fred_api_key:
        return {"status": UNAVAILABLE, "series": series_id,
                "reason": "FRED_API_KEY is not set"}
    try:
        import httpx

        resp = httpx.get(f"{settings.fred_base_url}/fred/series/observations",
                         params={"series_id": series_id,
                                 "api_key": settings.fred_api_key,
                                 "file_type": "json",
                                 "sort_order": "desc",
                                 "limit": limit},
                         timeout=20.0)
        resp.raise_for_status()
        rows = resp.json().get("observations", [])
    except Exception as e:  # noqa: BLE001 - degrade, never raise
        log.warning("FRED %s failed: %s", series_id, e)
        return {"status": UNAVAILABLE, "series": series_id, "reason": str(e)[:120]}

    obs = [{"date": r.get("date"), "value": _fnum(r.get("value"))}
           for r in reversed(rows) if _fnum(r.get("value")) is not None]
    return store(settings, "fred", series_id, {
        "status": "ok", "series": series_id, "name": name.lower(),
        "observations": obs,
        "latest": obs[-1] if obs else None,
        "change": _series_change(obs, points=series_id in RATE_SERIES),
    })


def _fnum(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _series_change(obs: list[dict], *, points: bool = False) -> dict:
    """Month-on-month and year-on-year, when there are enough points.

    `points` gives the change of a rate in percentage points, and marks it
    with `"unit": "pts"` so nothing prints it with a percent sign.
    """
    if len(obs) < 2:
        return {}
    latest = obs[-1]["value"]
    step = _pts if points else _pct
    out = {"mom": step(obs[-2]["value"], latest)}
    if len(obs) >= 13:
        out["yoy"] = step(obs[-13]["value"], latest)
    out = {k: v for k, v in out.items() if v is not None}
    if points and out:
        out["unit"] = "pts"
    return out


def _pts(before, after) -> float | None:
    if before is None or after is None:
        return None
    return round(after - before, 2)


def _pct(before, after) -> float | None:
    if not before:
        return None
    return round((after - before) / abs(before) * 100, 2)


# --------------------------------------------------------------------------
# Company IR RSS.
# --------------------------------------------------------------------------


@dataclass
class FeedItem:
    title: str
    link: str
    published: str = ""

    def to_json(self) -> dict:
        return asdict(self)


def ir_feed(url: str, settings: Settings, limit: int = 10) -> dict:
    """A company's press-release RSS. Parsed with the stdlib, no new dep."""
    hit = cached(settings, "rss", url)
    if hit is not None:
        return hit
    if settings.mock_mode:
        return store(settings, "rss", url,
                     _fixture(settings, "ir_feed.json",
                              {"status": UNAVAILABLE, "url": url}))
    try:
        import httpx

        resp = httpx.get(url, timeout=20.0, follow_redirects=True,
                         headers={"User-Agent": settings.sec_user_agent
                                  or "Dennis research bot"})
        resp.raise_for_status()
        items = parse_rss(resp.text, limit)
    except Exception as e:  # noqa: BLE001
        log.warning("IR feed %s failed: %s", url, e)
        return {"status": UNAVAILABLE, "url": url, "reason": str(e)[:120]}
    return store(settings, "rss", url,
                 {"status": "ok", "url": url,
                  "items": [i.to_json() for i in items]})


def parse_rss(xml: str, limit: int = 10) -> list[FeedItem]:
    """RSS or Atom, whichever the company's CMS emits. Never raises."""
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []
    out: list[FeedItem] = []
    # RSS 2.0
    for item in root.iter("item"):
        out.append(FeedItem(title=_text(item, "title"),
                            link=_text(item, "link"),
                            published=_text(item, "pubDate")))
    if not out:  # Atom
        ns = "{http://www.w3.org/2005/Atom}"
        for entry in root.iter(f"{ns}entry"):
            link = entry.find(f"{ns}link")
            out.append(FeedItem(
                title=_text(entry, f"{ns}title"),
                link=(link.get("href") if link is not None else ""),
                published=_text(entry, f"{ns}updated")))
    return [i for i in out if i.title][:limit]


def _text(node, tag: str) -> str:
    el = node.find(tag)
    return (el.text or "").strip() if el is not None and el.text else ""


# --------------------------------------------------------------------------
# Fixtures + reporting.
# --------------------------------------------------------------------------


def _fixture(settings: Settings, name: str, fallback: dict) -> dict:
    """MOCK_MODE reads a fixture when one exists, so the path runs offline."""
    try:
        return json.loads((settings.fixtures_dir / "sources" / name).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return fallback


def summarise(payload: dict) -> str:
    """One line for the operator. Says "unavailable" out loud rather than
    presenting an empty result as if it were data."""
    if payload.get("status") != "ok":
        reason = payload.get("reason") or "not available"
        return f"({reason})"
    if "observations" in payload:
        latest = payload.get("latest") or {}
        bits = [f"{payload.get('series')}: {latest.get('value')} "
                f"({latest.get('date')})"]
        change = payload.get("change") or {}
        unit = (" percentage points" if change.get("unit") == "pts"
                else "%")
        spec = "+.2f" if change.get("unit") == "pts" else "+.1f"
        if "yoy" in change:
            bits.append(f"{change['yoy']:{spec}}{unit} y/y")
        elif "mom" in change:
            bits.append(f"{change['mom']:{spec}}{unit} m/m")
        return " · ".join(bits)
    if "filings" in payload:
        return f"{payload.get('count', 0)} recent {payload.get('ticker')} Form 4(s)"
    if "items" in payload:
        return f"{len(payload['items'])} IR item(s)"
    if payload.get("form"):
        tail = " + EX-99.1" if payload.get("exhibit_url") else ""
        return f"{payload['form']} filed {payload.get('filed')}{tail}"
    return "ok"
