"""Finding the real article behind a headline the script wrote.

A screenshot of the actual published headline is the highest-credibility
visual the short has: real, current, specific, and free. It is the difference
between "a press release, not a purchase order" as an assertion and as
something somebody can see was printed.

It needed the writer to paste a URL into `[SHOW ARTICLE: …]`, which meant it
almost never happened. But the operator's data export already carries the
drivers — `CompanyData.news` is `{date, headline, source, url}` — and
`script.headlines` is the writer's paraphrase of those same drivers. Matching
one to the other is a token overlap, not a research problem.

Nothing here fails loudly. A short with no resolvable article draws the
headline card it always drew.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

# Words that carry no signal about WHICH story this is.
_STOP = frozenset({
    "a", "an", "and", "as", "at", "be", "by", "for", "from", "in", "is", "it",
    "its", "of", "on", "or", "the", "to", "with", "after", "over", "amid",
    "says", "said", "will", "has", "have", "up", "down", "new",
})

# Below this the "match" is two common words in a row and the screenshot would
# be of an unrelated story — which is worse than no screenshot at all,
# because it looks like evidence.
MIN_OVERLAP = 0.34


def _tokens(text: str, drop: frozenset[str] = frozenset()) -> set[str]:
    words = re.findall(r"[a-z0-9']+", (text or "").lower())
    return {w for w in words
            if len(w) > 2 and w not in _STOP and w not in drop}


def _subject_words(ticker: str) -> frozenset[str]:
    """Tokens that every row of this export shares, so they prove nothing.

    A video about NVDA has "nvidia" in the script's headline AND in all six
    news rows. Counting that as overlap makes every candidate look like a
    match and hands the tie to whichever row happens to be first.
    """
    return frozenset(_tokens(ticker))


def score(headline: str, candidate: str, drop: frozenset[str] = frozenset()) -> float:
    """Token overlap of two headlines, 0..1, normalised by the shorter one."""
    a, b = _tokens(headline, drop), _tokens(candidate, drop)
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def resolve_url(headline: str, news: list, *, ticker: str = "") -> str | None:
    """The URL of the story `headline` is describing, or None.

    Ranked by overlap, and a weak best match is refused: a screenshot of the
    wrong article is a false citation, not a near miss.
    """
    drop = _subject_words(ticker)
    best: tuple[float, str] = (0.0, "")
    for item in news or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url.lower().startswith(("http://", "https://")):
            continue
        s = score(headline, str(item.get("headline") or ""), drop)
        if s > best[0]:
            best = (s, url)
    if best[0] < MIN_OVERLAP:
        if best[1]:
            log.info("article lookup: best match for %r scored %.2f, below "
                     "%.2f — not screenshotting somebody else's story",
                     headline[:60], best[0], MIN_OVERLAP)
        return None
    log.info("article lookup: %r -> %s (overlap %.2f)",
             headline[:60], best[1], best[0])
    return best[1]


def lead_url(script, news: list) -> tuple[str, str] | None:
    """`(headline text, url)` for the short's lead driver, or None.

    The first headline is the one the WHY beat is about, so it is the one
    worth a real screenshot — but a later one that resolves beats an earlier
    one that doesn't, because the alternative is no screenshot at all.
    """
    ticker = str(getattr(script, "ticker", "") or "")
    for h in getattr(script, "headlines", None) or []:
        text = str(getattr(h, "text", "") or "")
        url = resolve_url(text, news, ticker=ticker)
        if url:
            return text, url
    return None


def top_article(script, company_data) -> tuple[str, str] | None:
    """`lead_url` against a loaded `CompanyData`."""
    return lead_url(script, list(getattr(company_data, "news", None) or []))


def workspace_news(workspace: Path) -> list:
    """The export's news rows, or `[]` when there is no export to read.

    The renderer is downstream of a run that already loaded this workbook, so
    re-reading it is cheap relative to the screenshot it feeds, and it keeps
    the lookup out of `render_short`'s signature and off every caller.
    """
    try:
        from pipeline.company_data import load_company_data
        return list(load_company_data(Path(workspace)).news or [])
    except Exception as e:  # noqa: BLE001 — an absent or odd workbook is a miss
        log.debug("article lookup: no news to search (%s)", e)
        return []


def row_url(news: list, n: int) -> str | None:
    """The URL of the nth news row, 1-based, or None if there isn't one.

    Out of range is a MISS, not an error: it falls back to the token match
    like any other unresolved beat, because a screenshot is a visual and no
    visual in this pipeline fails a render.
    """
    rows = [r for r in news or [] if isinstance(r, dict)]
    if not 1 <= n <= len(rows):
        log.warning("article lookup: [SHOW ARTICLE: %d] — the export carries "
                    "%d news row(s), so there is no row %d. Falling back to "
                    "matching the story by its words", n, len(rows), n)
        return None
    url = str(rows[n - 1].get("url") or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        log.warning("article lookup: news row %d has no usable url — falling "
                    "back to matching the story by its words", n)
        return None
    return url


def article_url(value: str, script, workspace: Path) -> tuple[str, str] | None:
    """`(url, how)` for a `[SHOW ARTICLE]` beat, or None. Never raises.

    Four ways a beat gets its URL, in order of how much the writer said:
      * they pasted one                       -> `pasted`
      * they numbered the row                 -> `row`, `[SHOW ARTICLE: 2]`
      * they named the story in the payload   -> `named`
      * they wrote a bare `[SHOW ARTICLE]`    -> `auto`, off the lead headline

    The number exists because self-resolution is a token overlap, and when two
    of the week's headlines cover the same theme it can pick the wrong one
    SILENTLY: the screenshot is of a real, current, adjacent story, and
    nothing about the frame says it is the wrong one. A row number is the
    cheapest way for a writer who can see the export to say which. Bare stays
    exactly as it was — requiring a payload is what stopped this being used.
    """
    value = (value or "").strip()
    if value.lower().startswith(("http://", "https://")):
        return value, "pasted"

    news = workspace_news(workspace)
    if not news:
        if value:
            log.info("article lookup: %r is not a url and the export carried "
                     "no news — falling back to the headline card", value[:60])
        return None

    if value.isdigit():
        url = row_url(news, int(value))
        if url:
            return url, "row"
        value = ""      # out of range: nothing left to match on, so self-resolve

    if value:
        url = resolve_url(value, news, ticker=str(getattr(script, "ticker", "")))
        if url:
            return url, "named"

    found = lead_url(script, news)
    if found:
        return found[1], "auto"
    return None
