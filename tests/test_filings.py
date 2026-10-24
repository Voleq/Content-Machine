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
from pipeline.company_data import FILING_SOURCE, list_screenshots


# --------------------------------------------------------------- resolve

def test_resolve_cik(settings):
    tickers = F._load_company_tickers(settings)
    assert F.resolve_cik("EXMPL", tickers) == "0001234567"   # 10-digit, zero-padded
    assert F.resolve_cik("exmpl", tickers) == "0001234567"   # case-insensitive
    assert F.resolve_cik("NOPE", tickers) is None            # unknown → None
    assert F.resolve_cik("EXMPL", None) is None              # empty map → None
    # the SEC writes a share class with a dash
    classes = {"0": {"ticker": "BRK-B", "cik_str": 1067983}}
    assert F.resolve_cik("BRK.B", classes) == "0001067983"
    assert F.resolve_cik("brk-b", classes) == "0001067983"


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


def _submissions(rows):
    """EDGAR's `recent` block from (form, accession, filed, period) rows,
    newest first, as the SEC serves it."""
    return {"filings": {"recent": {
        "form": [r[0] for r in rows],
        "accessionNumber": [r[1] for r in rows],
        "primaryDocument": [f"doc-{i}.htm" for i, _ in enumerate(rows)],
        "filingDate": [r[2] for r in rows],
        "reportDate": [r[3] for r in rows],
    }}}


AMENDED = [
    ("10-K/A", "0001234567-26-000020", "2026-04-20", "2025-12-31"),
    ("10-K", "0001234567-26-000012", "2026-02-20", "2025-12-31"),
    ("10-Q/A", "0001234567-25-000050", "2025-12-01", "2025-09-30"),
    ("10-Q", "0001234567-25-000045", "2025-11-04", "2025-09-30"),
    ("10-K", "0001234567-25-000010", "2025-02-20", "2024-12-31"),
    ("10-Q", "0001234567-24-000046", "2024-11-05", "2024-09-30"),
]


def test_an_amendment_does_not_stand_in_for_its_own_year():
    """A 10-K/A restates the year its 10-K already covers. Kept as a filing of
    its own it came first, newest-first, and the year-over-year pair was the
    amendment and the original of the SAME year."""
    subs = _submissions(AMENDED)
    annual = F.pick_filings("0001234567", "EXMPL", subs, F.ANNUAL_FORMS)
    assert [(r.form, r.period) for r in annual] == [
        ("10-K", "2025-12-31"), ("10-K", "2024-12-31")]
    quarterly = F.pick_filings("0001234567", "EXMPL", subs, F.QUARTERLY_FORMS)
    assert [(r.form, r.period) for r in quarterly] == [
        ("10-Q", "2025-09-30"), ("10-Q", "2024-09-30")]


def test_an_amendment_is_kept_when_nothing_else_covers_its_period():
    subs = _submissions([("10-K/A", "0001234567-26-000021", "2026-05-20",
                          "2025-12-31"),
                         ("10-K/A", "0001234567-26-000020", "2026-04-20",
                          "2025-12-31")])
    annual = F.pick_filings("0001234567", "EXMPL", subs, F.ANNUAL_FORMS)
    assert [r.accession for r in annual] == ["0001234567-26-000021"]


def test_the_reading_list_never_pairs_a_year_with_itself(settings, monkeypatch):
    monkeypatch.setattr(F, "_load_company_tickers", lambda s: {
        "0": {"ticker": "EXMPL", "cik_str": 1234567}})
    monkeypatch.setattr(F, "_load_submissions",
                        lambda cik, s: _submissions(AMENDED))
    fs = F.resolve_filings("EXMPL", settings)
    assert (fs.latest_annual.form, fs.latest_annual.period) == \
        ("10-K", "2025-12-31")
    assert (fs.prior_annual.form, fs.prior_annual.period) == \
        ("10-K", "2024-12-31")
    # The newest 10-K reports on a later period than the newest 10-Q, so the
    # quarter is inside it — and the year-ago quarter is the prior 10-K.
    assert fs.latest_quarter.period != fs.year_ago_quarter.period
    assert len({r.accession for r in fs.refs()}) == len(fs.refs())


# --------------------------------------------------------------- segment / flag

def _sample_html(settings) -> str:
    return (settings.fixtures_dir / "filings" / "sample_10k.html").read_text(encoding="utf-8")


def test_segment_filing_labels_sections(settings):
    sections = {s["title"]: s["text"] for s in F.segment_filing(_sample_html(settings))}
    assert {"Business", "Risk Factors", "MD&A"} <= set(sections)
    assert "net losses" in sections["Risk Factors"]
    assert "net debt to EBITDA" in sections["MD&A"]


def test_an_inline_xbrl_filing_keeps_its_prose():
    """Most 10-Ks are inline XBRL now: spans in divs, not one <p>. Only
    <p>, <li> and <td> were read, so the brief saw its tables and none of
    its words. A div with nothing block-level in it is a paragraph; the
    divs around it are not read twice."""
    risk = ("Our customers are concentrated, and the loss of any one of them "
            "would reduce our revenue materially.")
    html = ("<html><body><div><div><span style='font-weight:700'>Item 1A. Risk "
            "Factors</span></div>"
            f"<div><span>{risk}</span></div><div><span>23</span></div>"
            "<div><table><tr><td>Revenue grew 4%.</td></tr></table></div>"
            "</div></body></html>")
    sections = {s["title"]: s["text"] for s in F.segment_filing(html)}
    assert sections["Risk Factors"].count("customers are concentrated") == 1
    assert "23" not in sections["Risk Factors"].split()
    assert sections["Risk Factors"].count("Revenue grew 4%") == 1


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

    # the vendor is NEVER named — only the filing, in design's source tag.
    # (EDGAR is the SEC's free public system, not a data-terminal vendor, so
    # it's fine that the internal manifest URL carries it; it never reaches
    # the screen.)
    assert FILING_SOURCE == "10-K"
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


# ------------------------------------------------- the manifest's own shape
#
# `load_manifest` returns the WHOLE manifest — ticker, form, accession, url
# and `shots` — and two readers took it for the shot list itself. Both are
# exercised here WITHOUT a browser, which is why neither was caught: the veto
# test above needs Chromium and skips on any box that has none.

def _hand_written_manifest(workspace, n: int = 2) -> list[str]:
    """A manifest and its PNGs, built by hand so no browser is needed."""
    names = [f"filing_{i}.png" for i in range(1, n + 1)]
    for name in names:
        (workspace / name).write_bytes(b"not really a png")
    F._manifest_path(workspace).parent.mkdir(parents=True, exist_ok=True)
    F._manifest_path(workspace).write_text(json.dumps({
        "ticker": "EXMPL",
        "form": "10-K",
        "accession": "0001234567-26-000012",
        "url": "https://www.sec.gov/Archives/edgar/data/1234567/x.htm",
        "shots": [{"name": name, "section": "Risk Factors",
                   "accession": "0001234567-26-000012",
                   "image": str(workspace / name)} for name in names],
    }, indent=2), encoding="utf-8")
    return names


def test_the_provenance_record_counts_shots_not_manifest_keys(settings, tmp_path):
    """The render's provenance block reads the shot list, not the manifest.

    Reading the manifest as a list counted its five top-level keys as five
    shots and then walked them as dicts — an AttributeError on `str.get`,
    raised while writing the manifest, i.e. after the encode and after the
    paid voice had already been spent.
    """
    from pipeline.render_long import _provenance

    workspace = tmp_path / "EXMPL" / "2026-09-19"
    workspace.mkdir(parents=True)
    _hand_written_manifest(workspace, n=2)

    class _Script:
        ticker = "EXMPL"
        events: list = []
        narration = "Nothing here draws a price chart."

        def events_of(self, *_types):
            return []

    record = _provenance(_Script(), settings, workspace, 12.0, [], None,
                         draft=False, proof=False)
    assert record.filings["shots"] == 2
    assert record.filings["refs"] == ["10-K 0001234567-26-000012"]


def test_the_veto_button_resolves_a_shot_by_index(settings, tmp_path):
    """`fv|…|<i>` addresses the i-th shot; the manifest is not that list.

    Indexing the manifest dict raised `KeyError: 0`, which the handler's own
    except clause did not name — so every tap of a drop button came back as
    an internal error and the crop stayed in.
    """
    from bot.handlers import BotCore

    core = BotCore(settings)
    workspace = settings.workspace_dir / "EXMPL" / "2026-09-19"
    workspace.mkdir(parents=True)
    names = _hand_written_manifest(workspace, n=2)

    core.veto_filing(1, "EXMPL", "2026-09-19", "0")

    assert not (workspace / names[0]).exists()
    remaining = {s["name"] for s in F.load_manifest(workspace)["shots"]}
    assert remaining == {names[1]}


def test_the_sec_ticker_map_is_fetched_once_a_day(settings, monkeypatch):
    """`company_tickers.json` was downloaded on every call, and each alert
    poll read it twice per watched name, with the submissions file twice
    too: about 1,200 requests a day for ten names, which is how a client
    gets the SEC's fair-access block."""
    from types import SimpleNamespace

    from pipeline import filings

    live = settings.model_copy(update={"mock_mode": False})
    calls: list[str] = []

    def fake_get(url, _settings):
        calls.append(url)
        body = ({"0": {"cik_str": 1, "ticker": "EXMPL"}}
                if url.endswith("company_tickers.json") else {"filings": {}})
        return SimpleNamespace(json=lambda: body)

    monkeypatch.setattr(filings, "_sec_get", fake_get)
    for _ in range(3):
        assert filings._load_company_tickers(live)["0"]["ticker"] == "EXMPL"
        assert filings._load_submissions("0000000001", live) == {"filings": {}}
    assert len(calls) == 2
