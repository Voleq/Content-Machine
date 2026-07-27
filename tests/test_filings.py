"""10-K auto-screenshot pipeline (§3, automated) — fully offline.

Every test runs in MOCK_MODE against the committed fixtures (a fake
company_tickers map, two submissions files, a sample 10-K, and the flagged
quotes), so there is zero network and $0 spend — the conftest socket guard
must stay green. The one test that actually drives headless Chromium is
guarded: it skips where a browser cannot launch, never fails.
"""

from __future__ import annotations

import json

import pytest

from pipeline import filings as F
from pipeline.company_data import FILING_LABEL, list_screenshots


# --------------------------------------------------------------- resolve

def test_resolve_cik(settings):
    tickers = F._load_company_tickers(settings)
    assert F.resolve_cik("EXMPL", tickers) == "0001234567"   # 10-digit, zero-padded
    assert F.resolve_cik("exmpl", tickers) == "0001234567"   # case-insensitive
    assert F.resolve_cik("NOPE", tickers) is None            # unknown → None
    assert F.resolve_cik("EXMPL", None) is None              # empty map → None


def test_resolve_filing_builds_edgar_url(settings):
    ref = F.resolve_filing("EXMPL", settings)
    assert ref is not None
    assert ref.form == "10-K"
    assert ref.cik == "0001234567"
    assert ref.accession == "0001234567-26-000012"
    # CIK un-padded, accession de-dashed, primary doc appended
    assert ref.url == (
        "https://www.sec.gov/Archives/edgar/data/1234567/"
        "000123456726000012/exmpl-20251231.htm"
    )


def test_foreign_filer_degrades_to_none(settings):
    # FRGN only files 20-F / 6-K — no domestic 10-K, so no auto-shots
    assert F.resolve_filing("FRGN", settings) is None
    # a ticker absent from the SEC map also degrades
    assert F.resolve_filing("NOPE", settings) is None


# --------------------------------------------------------------- segment / flag

def _sample_html(settings) -> str:
    return (settings.fixtures_dir / "filings" / "sample_10k.html").read_text(encoding="utf-8")


def test_segment_filing_labels_sections(settings):
    sections = {s["title"]: s["text"] for s in F.segment_filing(_sample_html(settings))}
    assert {"Business", "Risk Factors", "MD&A"} <= set(sections)
    assert "net losses" in sections["Risk Factors"]
    assert "net debt to EBITDA" in sections["MD&A"]


def test_flag_quotes_mock_are_verbatim(settings):
    html = _sample_html(settings)
    sections = F.segment_filing(html)
    quotes = F.flag_quotes(sections, "over-levered and diluting", settings)
    assert 2 <= len(quotes) <= 4
    for q in quotes:
        assert q.quote and q.section and q.why
        # "verbatim" is the whole point — every quote must be locatable
        assert F.locate_quote(html, q.quote) is not None, q.quote


# --------------------------------------------------------------- locate

def test_locate_quote_finds_enclosing_block(settings):
    html = _sample_html(settings)
    loc = F.locate_quote(
        html, "Our net debt to EBITDA ratio was 9.8x as of the most recent fiscal year end.")
    assert loc is not None
    assert loc["tag"] == "p"
    assert "net debt to EBITDA" in loc["block_text"]
    # whitespace-normalized matching (the DOM may wrap/indent differently)
    assert F.locate_quote(html, "Our net debt to EBITDA ratio\n   was 9.8x") is not None


def test_locate_quote_absent_returns_none(settings):
    html = _sample_html(settings)
    assert F.locate_quote(html, "we are wildly profitable and always have been") is None
    assert F.locate_quote(html, "") is None


# --------------------------------------------------------------- degradation

def test_graceful_degradation_missing_filing(settings, tmp_path):
    """Missing/unresolvable filing → zero shots, no exception, empty manifest —
    so a render is never blocked by the pull."""
    shots = F.auto_filings("NOPE", "any angle", tmp_path, settings)
    assert shots == []
    assert F.load_manifest(tmp_path).get("shots") == []

    foreign = F.auto_filings("FRGN", "any angle", tmp_path, settings)
    assert foreign == []


def test_disabled_flag_produces_nothing(settings, tmp_path):
    s = settings.model_copy(update={"filings_enabled": False})
    assert F.auto_filings("EXMPL", "angle", tmp_path, s) == []


# --------------------------------------------------------------- happy path (browser)

def test_auto_filings_happy_path(settings, tmp_path):
    """The full offline pull → flag → shoot → normalize, if a headless browser
    can launch here (skipped, never failed, where it cannot)."""
    pytest.importorskip("playwright")
    shots = F.auto_filings("EXMPL", "over-levered and diluting", tmp_path, settings)
    if not shots:
        pytest.skip("headless chromium unavailable in this environment")

    assert 1 <= len(shots) <= settings.filings_max_shots
    # normalized PNGs land at the workspace top level → list_screenshots sees them
    names = list_screenshots(tmp_path)
    for s in shots:
        assert s.name in names
        img = tmp_path / s.name
        assert img.exists() and img.stat().st_size > 0
        assert s.quote and s.section

    # the manifest carries the quote·section·why the write prompt reads
    manifest = F.load_manifest(tmp_path)
    assert manifest["ticker"] == "EXMPL" and manifest["form"] == "10-K"
    assert len(manifest["shots"]) == len(shots)

    # the vendor is NEVER named — only the generic filing chip. (EDGAR is the
    # SEC's free public system, not a data-terminal vendor, so it's fine that
    # the internal manifest URL carries it; it never reaches the screen.)
    assert FILING_LABEL == "FROM THE 10-K"
    blob = json.dumps(manifest).lower()
    for brand in ("refinitiv", "lseg", "eikon", "capital iq", "bloomberg terminal"):
        assert brand not in blob


def test_veto_shot_removes_png_and_manifest_entry(settings, tmp_path):
    pytest.importorskip("playwright")
    shots = F.auto_filings("EXMPL", "levered", tmp_path, settings)
    if not shots:
        pytest.skip("headless chromium unavailable in this environment")
    victim = shots[0].name
    assert (tmp_path / victim).exists()

    assert F.veto_shot(tmp_path, victim) is True
    assert not (tmp_path / victim).exists()
    assert victim not in {s["name"] for s in F.load_manifest(tmp_path)["shots"]}
    assert victim not in list_screenshots(tmp_path)
    # vetoing an already-gone shot is a no-op, not an error
    assert F.veto_shot(tmp_path, victim) is False
