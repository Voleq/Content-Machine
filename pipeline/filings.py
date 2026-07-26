"""10-K auto-screenshot pipeline (§3, automated).

Replaces the manual "operator uploads filing PNGs" step. The whole chain,
run thesis-aware after the LONG angle is picked:

  1. RESOLVE   ticker → CIK (SEC company_tickers.json) → latest 10-K (opt.
     10-Q) via the submissions API → the EDGAR primary-document URL. Foreign
     filers (20-F, no 10-K) degrade to nothing.
  2. DOWNLOAD  the filing HTML, cached under the workspace (retention-managed).
  3. SEGMENT   split into sections (Risk Factors, MD&A, Business, …).
  4. FLAG      a cheap, swappable LLM returns 2–4 VERBATIM smoking-gun quotes
     for the chosen angle, each with a section + a one-line "why".
  5. SCREENSHOT  headless Chromium (Playwright) locates each quote's enclosing
     block, scrolls it in, optionally highlights it, and shots it at 2×.
  6. NORMALIZE  every PNG runs through company_data.prepare_screenshot() — the
     generic "FROM THE 10-K" chip, never a vendor — and lands in the workspace
     so list_screenshots() / [SHOW FILING: file] pick it up unchanged. A small
     manifest (quote · section · why) feeds the long-write prompt.

Hard guarantees, all enforced here:
  * MOCK_MODE is fully offline — fixtures only, zero network, $0.
  * A failed pull NEVER blocks a render: every stage catches and degrades to
    fewer (or zero) shots; `auto_filings` never raises.
  * The data vendor is never named on screen (the chip is the only label).
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

from config import Settings

log = logging.getLogger(__name__)

# forms we care about, best first
_PREFERRED_FORMS = ("10-K", "10-K/A", "10-Q", "10-Q/A")
# these mean "no domestic 10-K" — degrade gracefully rather than guess
_FOREIGN_FORMS = ("20-F", "40-F", "6-K")

_WS = re.compile(r"\s+")

# block-level tags a quote's "enclosing block" may be (paragraph / row / item)
_BLOCK_TAGS = {"p", "li", "tr", "td", "th", "div", "section", "blockquote"}

# the last-request clock for SEC fair-access rate limiting (≤ 10 req/s)
_sec_lock = threading.Lock()
_sec_last = 0.0


# --------------------------------------------------------------------------
# small value types
# --------------------------------------------------------------------------

@dataclass
class FilingRef:
    ticker: str
    cik: str          # 10-digit, zero-padded
    form: str         # "10-K", "10-Q", …
    accession: str    # "0000320193-24-000123"
    primary_doc: str  # "aapl-20240928.htm"
    url: str          # full EDGAR archive URL
    filed: str = ""   # ISO filing date


@dataclass
class FlaggedQuote:
    quote: str        # VERBATIM — must be locatable in the HTML
    section: str      # "Risk Factors", "MD&A", …
    why: str          # one-line rationale


@dataclass
class FilingShot:
    name: str         # workspace PNG filename → [SHOW FILING: name]
    quote: str
    section: str
    why: str
    image: str = ""   # absolute path to the normalized PNG


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _norm(text: str) -> str:
    return _WS.sub(" ", text or "").strip()


def _sec_headers(settings: Settings) -> dict:
    return {
        "User-Agent": settings.sec_user_agent or "Dennis research bot",
        "Accept-Encoding": "gzip, deflate",
    }


def _sec_get(url: str, settings: Settings) -> "object | None":
    """Rate-limited GET against SEC hosts. Never used in MOCK_MODE. Returns the
    httpx.Response or None on any failure (caller degrades)."""
    global _sec_last
    try:
        import httpx
    except ImportError:  # pragma: no cover
        return None
    with _sec_lock:
        wait = settings.sec_min_interval_s - (time.monotonic() - _sec_last)
        if wait > 0:
            time.sleep(wait)
        _sec_last = time.monotonic()
    try:
        resp = httpx.get(url, headers=_sec_headers(settings), timeout=20.0,
                         follow_redirects=True)
        resp.raise_for_status()
        return resp
    except Exception as e:  # network / HTTP / timeout — degrade
        log.warning("SEC GET failed for %s: %s", url, e)
        return None


# Images that ship a browser at a known path (the container build does).
# A normal Windows or Linux install has none of these and lets Playwright
# resolve its own download instead.
_PREPROVISIONED_CHROMIUM = (
    Path("/opt/pw-browsers/chromium"),
    Path(r"C:\pw-browsers\chromium\chrome.exe"),
)


def _chromium_executable(settings: Settings) -> str | None:
    """Explicit path wins; otherwise use a pre-provisioned browser if present,
    else let Playwright pick its own bundled Chromium.

    Returning None is the normal case on a machine where
    `playwright install chromium` has run — Playwright then finds its own
    browser, on Windows and Linux alike.
    """
    if settings.playwright_chromium_path:
        return settings.playwright_chromium_path
    for cand in _PREPROVISIONED_CHROMIUM:
        if cand.exists():
            return str(cand)
    return None


# --------------------------------------------------------------------------
# 1. resolve
# --------------------------------------------------------------------------

def _load_company_tickers(settings: Settings) -> dict | None:
    """The SEC ticker→CIK map. MOCK/offline → fixture; live → SEC."""
    if settings.mock_mode:
        f = settings.fixtures_dir / "filings" / "company_tickers.json"
        try:
            return json.loads(f.read_text())
        except Exception as e:
            log.warning("filings: no company_tickers fixture (%s)", e)
            return None
    resp = _sec_get(f"{settings.sec_base_url}/files/company_tickers.json", settings)
    if resp is None:
        return None
    try:
        return resp.json()
    except Exception:
        return None


def resolve_cik(ticker: str, tickers: dict | None) -> str | None:
    """Look a ticker up in the SEC map → 10-digit zero-padded CIK. Pure."""
    if not tickers:
        return None
    want = ticker.strip().upper()
    for row in tickers.values():
        if str(row.get("ticker", "")).upper() == want:
            return str(row.get("cik_str", "")).zfill(10)
    return None


def _load_submissions(cik: str, settings: Settings) -> dict | None:
    if settings.mock_mode:
        f = settings.fixtures_dir / "filings" / f"submissions_CIK{cik}.json"
        try:
            return json.loads(f.read_text())
        except Exception as e:
            log.warning("filings: no submissions fixture for CIK%s (%s)", cik, e)
            return None
    resp = _sec_get(f"{settings.sec_data_base_url}/submissions/CIK{cik}.json", settings)
    if resp is None:
        return None
    try:
        return resp.json()
    except Exception:
        return None


def _pick_filing(cik: str, ticker: str, submissions: dict,
                 include_10q: bool) -> FilingRef | None:
    """Pick the most recent preferred form from the submissions' `recent`
    parallel arrays and build its EDGAR primary-document URL."""
    recent = (submissions.get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    accns = recent.get("accessionNumber") or []
    docs = recent.get("primaryDocument") or []
    dates = recent.get("filingDate") or []
    wanted = ("10-K", "10-K/A") + (("10-Q", "10-Q/A") if include_10q else ())
    for i, form in enumerate(forms):
        if form in wanted and i < len(accns) and i < len(docs):
            accession = accns[i]
            primary = docs[i]
            if not primary:
                continue
            nodash = accession.replace("-", "")
            url = (f"https://www.sec.gov/Archives/edgar/data/"
                   f"{int(cik)}/{nodash}/{primary}")
            return FilingRef(ticker=ticker.upper(), cik=cik, form=form,
                             accession=accession, primary_doc=primary, url=url,
                             filed=dates[i] if i < len(dates) else "")
    # foreign filer / no domestic report — degrade, but say why
    present = set(forms[:20])
    if present & set(_FOREIGN_FORMS):
        log.info("filings: %s files %s, no 10-K — skipping auto-shots",
                 ticker, sorted(present & set(_FOREIGN_FORMS)))
    return None


def resolve_filing(ticker: str, settings: Settings) -> FilingRef | None:
    """ticker → the latest 10-K (or 10-Q) FilingRef, or None (graceful)."""
    tickers = _load_company_tickers(settings)
    cik = resolve_cik(ticker, tickers)
    if cik is None:
        log.info("filings: %s not found in the SEC ticker map", ticker)
        return None
    submissions = _load_submissions(cik, settings)
    if submissions is None:
        return None
    return _pick_filing(cik, ticker, submissions, settings.filings_include_10q)


# --------------------------------------------------------------------------
# 2. download
# --------------------------------------------------------------------------

def download_filing(ref: FilingRef, workspace: Path, settings: Settings) -> Path | None:
    """Fetch the filing HTML into ws/filings/ (cached; the workspace is
    retention-managed). MOCK/offline → the fixture 10-K. None on failure."""
    fdir = workspace / "filings"
    fdir.mkdir(parents=True, exist_ok=True)
    dest = fdir / "filing.html"
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    if settings.mock_mode:
        src = settings.fixtures_dir / "filings" / "sample_10k.html"
        if not src.exists():
            log.warning("filings: no sample_10k.html fixture")
            return None
        dest.write_bytes(src.read_bytes())
        return dest
    resp = _sec_get(ref.url, settings)
    if resp is None:
        return None
    dest.write_bytes(resp.content)
    return dest


# --------------------------------------------------------------------------
# 3. segment
# --------------------------------------------------------------------------

# 10-K item headers → friendly section names (order matters for the scan)
_ITEM_SECTIONS = [
    (re.compile(r"item\s*1a\b.*risk\s*factors", re.I), "Risk Factors"),
    (re.compile(r"item\s*7a\b", re.I), "Market Risk"),
    (re.compile(r"item\s*7\b.*management", re.I), "MD&A"),
    (re.compile(r"item\s*1\b.*business", re.I), "Business"),
    (re.compile(r"item\s*3\b.*legal", re.I), "Legal Proceedings"),
    (re.compile(r"item\s*8\b.*financial\s*statements", re.I), "Financial Statements"),
]


def _section_for(text: str, current: str) -> str:
    low = _norm(text).lower()
    for rx, name in _ITEM_SECTIONS:
        if rx.search(low):
            return name
    return current


def segment_filing(html: str) -> list[dict]:
    """Split the filing into sections. Returns [{title, text}] — the text the
    LLM reads. Best-effort; unlabeled bodies land under 'Filing'."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:  # pragma: no cover - bs4 ships in the base env
        # crude fallback: strip tags, one bucket
        return [{"title": "Filing", "text": _norm(re.sub(r"<[^>]+>", " ", html))}]
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    sections: dict[str, list[str]] = {}
    current = "Business"
    # short elements (incl. header divs) can SWITCH the section; only true text
    # blocks (p/li/td) become body — so container divs never double-count.
    for el in soup.find_all(["h1", "h2", "h3", "h4", "h5", "div", "b", "strong",
                             "p", "li", "td"]):
        txt = _norm(el.get_text(" "))
        if not txt:
            continue
        if len(txt) < 120:
            new = _section_for(txt, current)
            if new != current:
                current = new
                continue  # a header line — not body
        if el.name in ("p", "li", "td"):
            sections.setdefault(current, []).append(txt)
    return [{"title": name, "text": " ".join(chunks)}
            for name, chunks in sections.items() if chunks]


# --------------------------------------------------------------------------
# 4. flag smoking-gun quotes (cheap, swappable LLM)
# --------------------------------------------------------------------------

_FLAG_SYSTEM = (
    "You extract smoking-gun quotes from SEC 10-K filings for a deadpan "
    "financial video. Given the filing text and a thesis/angle, return 2 to 4 "
    "VERBATIM quotes (copied exactly, so they can be located in the document) "
    "that most support or complicate the thesis. Prefer risk factors, MD&A "
    "admissions, and concrete numbers. Respond ONLY with a JSON array of "
    '{"quote","section","why"} objects; "why" is one short line.'
)


def _mock_flagged(settings: Settings) -> list[FlaggedQuote]:
    f = settings.fixtures_dir / "filings" / "flagged_quotes.json"
    try:
        rows = json.loads(f.read_text())
    except Exception as e:
        log.warning("filings: no flagged_quotes fixture (%s)", e)
        return []
    return [FlaggedQuote(quote=r.get("quote", ""), section=r.get("section", ""),
                         why=r.get("why", "")) for r in rows if r.get("quote")]


def _compress_sections(sections: list[dict], budget: int) -> str:
    """Pack section text under the per-call char budget (free tiers are
    rate-limited) — prioritise Risk Factors + MD&A."""
    order = {"Risk Factors": 0, "MD&A": 1, "Market Risk": 2, "Business": 3}
    ordered = sorted(sections, key=lambda s: order.get(s["title"], 9))
    out, used = [], 0
    for s in ordered:
        head = f"\n## {s['title']}\n"
        room = budget - used - len(head)
        if room <= 0:
            break
        body = s["text"][:room]
        out.append(head + body)
        used += len(head) + len(body)
    return "".join(out)


def _llm_chat(prompt: str, settings: Settings, system: str = _FLAG_SYSTEM) -> str | None:
    """One OpenAI-compatible chat completion. Provider is swappable via
    config; returns the message content or None on any failure."""
    try:
        import httpx
    except ImportError:  # pragma: no cover
        return None
    provider = settings.filings_llm_provider.lower()
    if provider == "openai":
        base, token = settings.openai_base_url, settings.openai_api_key
        url = base.rstrip("/") + "/v1/chat/completions"
    else:  # github models (default), OpenAI-compatible
        base, token = settings.github_models_endpoint, settings.github_models_token
        url = base.rstrip("/") + "/chat/completions"
    if not token:
        log.warning("filings: no token for LLM provider %r — skipping", provider)
        return None
    try:
        resp = httpx.post(
            url,
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"},
            json={
                "model": settings.filings_llm_model,
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": prompt}],
                "temperature": 0.2,
            },
            timeout=45.0,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        log.warning("filings: LLM call failed (%s)", e)
        return None


_SUMMARY_SYSTEM = (
    "You summarize a news article for a deadpan financial video. In 2-3 plain "
    "sentences, state only what happened and the key figures — no opinion, no "
    "hype, and never name a data terminal or vendor."
)


def fetch_and_summarize(url: str, settings: Settings, ledger=None) -> str:
    """Best-effort: fetch a news URL, extract its readable text, and summarize
    it so the /headline 'what it actually means' beat is grounded. Returns ''
    on any failure — NEVER blocks. Not called in MOCK_MODE (the caller skips
    network); spend (usually free-tier) is recorded when a summary comes back."""
    try:
        import httpx
    except ImportError:  # pragma: no cover
        return ""
    try:
        resp = httpx.get(url, timeout=15.0, follow_redirects=True,
                         headers={"User-Agent": settings.sec_user_agent or "Dennis bot"})
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        log.warning("headline fetch failed for %s (%s)", url, e)
        return ""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        for t in soup(["script", "style", "nav", "footer", "header", "aside"]):
            t.decompose()
        text = _norm(soup.get_text(" "))
    except ImportError:  # pragma: no cover
        text = _norm(re.sub(r"<[^>]+>", " ", html))
    if not text:
        return ""
    summary = _llm_chat(text[:settings.filings_llm_max_chars], settings,
                        system=_SUMMARY_SYSTEM) or ""
    if summary and ledger is not None:
        try:
            ledger.record_llm(settings.filings_llm_usd_per_call)
        except Exception:
            pass
    return summary.strip()


def _parse_quote_json(raw: str) -> list[FlaggedQuote]:
    if not raw:
        return []
    m = re.search(r"```(?:json)?\s*(.*?)```", raw, re.DOTALL)
    if m:
        raw = m.group(1)
    m = re.search(r"\[.*\]", raw, re.DOTALL)
    if not m:
        return []
    try:
        rows = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    out: list[FlaggedQuote] = []
    for r in rows if isinstance(rows, list) else []:
        if isinstance(r, dict) and r.get("quote"):
            out.append(FlaggedQuote(quote=str(r["quote"]), section=str(r.get("section", "")),
                                    why=str(r.get("why", ""))))
    return out


def flag_quotes(sections: list[dict], angle: str, settings: Settings,
                ledger=None) -> list[FlaggedQuote]:
    """2–4 verbatim smoking-gun quotes for the angle. MOCK/offline or the
    'mock' provider → fixtures; otherwise the configured LLM. Spend (even $0)
    is recorded in the ledger."""
    if settings.mock_mode or settings.filings_llm_provider.lower() == "mock":
        return _mock_flagged(settings)
    packed = _compress_sections(sections, settings.filings_llm_max_chars)
    prompt = f"THESIS / ANGLE:\n{angle or '(none given — pick the most material items)'}\n\nFILING TEXT:\n{packed}"
    raw = _llm_chat(prompt, settings)
    quotes = _parse_quote_json(raw or "")
    if quotes and ledger is not None:
        try:
            ledger.record_llm(settings.filings_llm_usd_per_call)
        except Exception:
            pass
    return quotes


# --------------------------------------------------------------------------
# 5a. locate a quote's enclosing block (pure — testable without a browser)
# --------------------------------------------------------------------------

def locate_quote(html: str, quote: str) -> dict | None:
    """Find the smallest block element whose normalized text contains the
    (normalized) quote. Returns {quote, block_text, tag} or None if absent —
    so we only ever try to screenshot a quote that is actually in the DOM."""
    needle = _norm(quote)
    if not needle:
        return None
    try:
        from bs4 import BeautifulSoup
    except ImportError:  # pragma: no cover
        return {"quote": quote, "block_text": needle, "tag": "p"} if needle in _norm(html) else None
    soup = BeautifulSoup(html, "html.parser")
    best = None
    for el in soup.find_all(list(_BLOCK_TAGS)):
        block_text = _norm(el.get_text(" "))
        if needle in block_text:
            # smallest containing block wins (most specific paragraph / row)
            if best is None or len(block_text) < len(best[1]):
                best = (el.name, block_text)
    if best is None:
        return None
    return {"quote": quote, "block_text": best[1], "tag": best[0]}


# --------------------------------------------------------------------------
# 5b. screenshot each located block (Playwright, run off the event loop)
# --------------------------------------------------------------------------

# a distinctive slice Playwright's text engine can match across inline nodes
def _needle(located: dict) -> str:
    q = _norm(located.get("quote", ""))
    return q[:80] if len(q) > 80 else q


def _shoot_blocks(html_path: Path, located: list[dict], out_dir: Path,
                  settings: Settings) -> list[Path]:
    """Sync Playwright work — MUST run in a plain thread (no asyncio loop).
    Best-effort: returns whatever shots succeed."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.warning("filings: playwright not installed — no auto-shots")
        return []
    out_dir.mkdir(parents=True, exist_ok=True)
    exe = _chromium_executable(settings)
    results: list[Path] = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, executable_path=exe)
            try:
                page = browser.new_page(device_scale_factor=2,
                                        viewport={"width": 1280, "height": 1600})
                page.goto(html_path.resolve().as_uri(), wait_until="load", timeout=15000)
                for i, loc in enumerate(located):
                    try:
                        el = page.get_by_text(_needle(loc), exact=False).first
                        # climb to the enclosing paragraph / row / list item
                        block = el.locator(
                            "xpath=ancestor-or-self::*[self::p or self::li or "
                            "self::tr or self::blockquote][1]")
                        target = block.first if block.count() else el
                        target.scroll_into_view_if_needed(timeout=4000)
                        _highlight(page, _needle(loc))
                        shot = out_dir / f"raw_{i:02d}.png"
                        target.screenshot(path=str(shot), timeout=5000)
                        results.append(shot)
                    except Exception as e:
                        log.warning("filings: shot %d failed (%s)", i, e)
            finally:
                browser.close()
    except Exception as e:
        log.warning("filings: browser launch failed (%s) — no auto-shots", e)
        return []
    return results


def _highlight(page, needle: str) -> None:
    """Best-effort soft highlight of the matched sentence before the shot."""
    try:
        page.evaluate(
            """(needle) => {
                const norm = s => s.replace(/\\s+/g,' ').trim();
                const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                let n;
                while (n = w.nextNode()) {
                    const t = norm(n.textContent);
                    if (t && needle && t.includes(needle.slice(0, 30))) {
                        const s = document.createElement('mark');
                        s.style.background = '#ffe27a';
                        s.style.color = 'inherit';
                        n.parentNode.replaceChild(s, n);
                        s.appendChild(n);
                        return;
                    }
                }
            }""",
            needle,
        )
    except Exception:
        pass


def screenshot_quotes(html_path: Path, located: list[dict], out_dir: Path,
                      settings: Settings) -> list[Path]:
    """Screenshot each located block. Playwright's sync API cannot run inside
    a running asyncio loop (the bot handler), so always do it in a worker
    thread — which never has one."""
    if not located:
        return []
    with ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(_shoot_blocks, html_path, located, out_dir, settings).result()


# --------------------------------------------------------------------------
# 6. orchestrate + manifest
# --------------------------------------------------------------------------

def _manifest_path(workspace: Path) -> Path:
    return workspace / "filings" / "manifest.json"


def load_manifest(workspace: Path) -> dict:
    try:
        return json.loads(_manifest_path(workspace).read_text())
    except Exception:
        return {}


def _write_manifest(workspace: Path, ref: FilingRef | None,
                    shots: list[FilingShot]) -> None:
    _manifest_path(workspace).parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ticker": ref.ticker if ref else "",
        "form": ref.form if ref else "",
        "accession": ref.accession if ref else "",
        "url": ref.url if ref else "",
        "shots": [asdict(s) for s in shots],
    }
    _manifest_path(workspace).write_text(json.dumps(payload, indent=2))


def auto_filings(ticker: str, angle: str, workspace: Path, settings: Settings,
                 ledger=None, max_shots: int | None = None) -> list[FilingShot]:
    """The whole pipeline, thesis-aware. NEVER raises — every failure degrades
    to fewer/zero shots so a render is never blocked. Normalized PNGs land at
    the workspace top level (list_screenshots / [SHOW FILING] pick them up);
    a manifest of quote·section·why is written under ws/filings/."""
    if not settings.filings_enabled:
        return []
    cap = settings.filings_max_shots if max_shots is None else max_shots
    try:
        ref = resolve_filing(ticker, settings)
        if ref is None:
            _write_manifest(workspace, None, [])
            return []
        html_path = download_filing(ref, workspace, settings)
        if html_path is None:
            _write_manifest(workspace, ref, [])
            return []
        html = html_path.read_text(errors="replace")
        sections = segment_filing(html)
        flagged = flag_quotes(sections, angle, settings, ledger=ledger)[:cap]

        # keep only quotes we can actually locate in the DOM
        located: list[dict] = []
        kept: list[FlaggedQuote] = []
        for fq in flagged:
            loc = locate_quote(html, fq.quote)
            if loc is not None:
                located.append(loc)
                kept.append(fq)
            else:
                log.info("filings: dropped unlocatable quote %r", fq.quote[:48])

        raw_shots = screenshot_quotes(html_path, located,
                                      workspace / "filings" / "raw", settings)

        # normalize each raw shot into the workspace with the generic chip
        from pipeline.company_data import prepare_screenshot
        shots: list[FilingShot] = []
        for i, raw in enumerate(raw_shots):
            fq = kept[i]
            name = f"filing_{i + 1:02d}.png"
            dest = workspace / name
            try:
                prepare_screenshot(raw, dest, settings)
            except Exception as e:
                log.warning("filings: normalize failed for shot %d (%s)", i, e)
                continue
            shots.append(FilingShot(name=name, quote=fq.quote, section=fq.section,
                                    why=fq.why, image=str(dest)))
        _write_manifest(workspace, ref, shots)
        return shots
    except Exception as e:  # the whole thing is best-effort
        log.warning("filings: auto_filings degraded (%s)", e)
        try:
            _write_manifest(workspace, None, [])
        except Exception:
            pass
        return []


def veto_shot(workspace: Path, name: str) -> bool:
    """Operator vetoed a crop: delete the normalized PNG and drop it from the
    manifest so [SHOW FILING] can never reference it. Returns True if removed."""
    manifest = load_manifest(workspace)
    shots = manifest.get("shots", [])
    remaining = [s for s in shots if s.get("name") != name]
    if len(remaining) == len(shots):
        return False
    (workspace / name).unlink(missing_ok=True)
    manifest["shots"] = remaining
    _manifest_path(workspace).write_text(json.dumps(manifest, indent=2))
    return True
