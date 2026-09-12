"""The provenance record (N): one block, per render, saying what was real.

Every test here asserts on the RENDERED record or on the blocking decision,
never on the fact that a builder function ran (X1). The record exists
because a fabricated price chart, an uncounted Tenor gif, a truncated
filing brief and a gate that never ran were all invisible in the output —
so "invisible" is what these tests are for, and a test that passes with the
data missing from the block would be testing nothing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.provenance import Provenance


def _degraded_cache(settings, ticker: str) -> None:
    """Pre-seed the price cache with a series the live feed did not provide.

    `get_price_history` reads the cache first, so this is what both the gate
    and the render's own record will see — the same object the chart would
    have been drawn from.
    """
    from pipeline.prices import PriceSeries

    cdir = settings.cache_dir / "prices"
    cdir.mkdir(parents=True, exist_ok=True)
    fake = PriceSeries(ticker=ticker.upper(),
                       dates=["2026-01-01", "2026-01-02", "2026-01-03"],
                       closes=[10.0, 10.4, 10.2],
                       source="synthetic", degraded=True)
    (cdir / f"{ticker.upper()}_{settings.price_history_days}.json").write_text(
        fake.to_json(), encoding="utf-8")


# --------------------------------------------------------------------------
# N5.1 — a synthetic series is named, in both surfaces, and blocks a final.
# --------------------------------------------------------------------------


def test_a_synthetic_series_is_named_in_the_manifest_and_in_the_message(
        settings, short_valid_json, tmp_path):
    """N5.1: the manifest says it, the operator reads it, and it blocks.

    Three surfaces off one degraded series, because B1 shipped a fabricated
    chart that was honest in none of them: the flag was set, dropped by
    `to_json`, read by nobody, and the render finished.
    """
    from pipeline.gates import check_prices
    from pipeline.parser_short import parse_short_script
    from pipeline.prices import get_price_history
    from pipeline.render_short import _provenance

    script, _ = parse_short_script(short_valid_json, settings=settings)
    live = settings.model_copy(update={"mock_mode": False,
                                       "cache_dir": tmp_path / "c"})
    _degraded_cache(live, script.ticker)
    series = get_price_history(script.ticker, live)
    assert series.degraded, "fixture setup: the cached series must be degraded"

    # 1. THE MANIFEST. Built by the renderer's own builder, so the record
    #    cannot speak a different vocabulary from the thing it describes.
    ws = tmp_path / "ws" / "2026-09-12"
    ws.mkdir(parents=True)
    record = _provenance(script, live, ws, 48.0, series, None, "short",
                         proof=False)
    block = record.to_json()
    assert block["prices"]["degraded"] is True
    assert block["prices"]["source"] == "synthetic"

    # 2. THE DELIVERY TEXT, read back off that manifest the way the bot
    #    reads it — not rebuilt, so the two cannot drift.
    (ws / "short_final.manifest.json").write_text(
        json.dumps({"provenance": block}), encoding="utf-8")
    text = Provenance.from_json(
        json.loads((ws / "short_final.manifest.json")
                   .read_text(encoding="utf-8"))["provenance"]).render_text()
    prices_line = next(ln for ln in text.splitlines()
                       if ln.startswith("prices"))
    assert "SYNTHETIC" in prices_line
    assert "NOT market data" in prices_line
    assert "LIVE" not in prices_line

    # 3. AND IT STOPS. A warning on a channel whose premise is real numbers
    #    is not enough (N4).
    blocking = [f for f in check_prices(script, live, final=True)
                if f.severity == "block"]
    assert blocking, "a fabricated chart must not reach a final render"


def test_a_real_series_reads_as_live_and_says_where_it_came_from(
        settings, short_valid_json, tmp_path):
    """The other half of N5.1: the good case must not read as synthetic.

    Without this the line above could be a constant.
    """
    from pipeline.parser_short import parse_short_script
    from pipeline.prices import PriceSeries
    from pipeline.render_short import _provenance

    script, _ = parse_short_script(short_valid_json, settings=settings)
    live = settings.model_copy(update={"mock_mode": False,
                                       "cache_dir": tmp_path / "c"})
    good = PriceSeries(ticker=script.ticker,
                       dates=["2026-01-01", "2026-01-02"],
                       closes=[10.0, 11.0], source="yahoo")
    ws = tmp_path / "ws" / "2026-09-12"
    ws.mkdir(parents=True)
    line = next(ln for ln in _provenance(script, live, ws, 48.0, good, None,
                                         "short", proof=False)
                .render_text().splitlines() if ln.startswith("prices"))
    assert "LIVE" in line and "yahoo" in line
    assert "SYNTHETIC" not in line
    assert "as-of 2026-01-02" in line, "the newest bar is the as-of date"


# --------------------------------------------------------------------------
# N5.2 — a GIF-sourced visual is counted as one.
# --------------------------------------------------------------------------


def test_a_gif_that_replaced_a_capped_pexels_clip_is_counted_as_a_gif(
        settings, tmp_path):
    """N5.2: driven through `ContentManager` with the Pexels cap tripped.

    The point is the VOCABULARY, which is why the source is not written by
    hand here: `Visual.source` is what the renderer puts on the manifest, so
    if the gif chain ever answered with a value the record does not bucket
    (H3's failure — a Tenor pull counted as an ordinary stock fetch), this
    fails.
    """
    from pipeline.broll import ContentManager, MockPexelsClient
    from pipeline.provenance import build
    from pipeline.render_long import _visual_source_counts

    capped = settings.model_copy(update={"pexels_monthly_call_cap": 0})

    class _Gif:
        """A gif provider that answers, like Tenor with a hit."""

        name = "tenor"

        def search(self, query, *, animated=False):
            return f"mock://gif/{query.replace(' ', '-')}"

        def download(self, url, dest):
            from pipeline.memes import MockMemeClient

            return MockMemeClient(capped).download(url, dest)

    m = ContentManager(capped, library_dir=tmp_path / "library",
                       gif_clients=[_Gif()])

    class CapClient(MockPexelsClient):
        def search(self, query, per_page=5):
            m.ledger.check_pexels_budget()  # the real client's gate
            return super().search(query, per_page)

    m.clip_client = CapClient(capped)

    gif = m.resolve_clip("tumbleweed")
    assert gif.source == "tenor", "fixture setup: the gif chain must answer"

    # The manifest's own shape, and then the line the operator reads.
    seg_meta = [{"source": gif.source}, {"source": "pexels"},
                {"source": "pexels"}, {"source": "local"}]
    counts = _visual_source_counts(seg_meta)
    assert counts["tenor"] == 1

    line = next(ln for ln in build(ticker="EXMPL", fmt="long", workdate="d",
                                   duration_s=1.0, visual_sources=counts)
                .render_text().splitlines() if ln.startswith("visuals"))
    assert "1 GIF (tenor)" in line, f"a gif went uncounted: {line}"
    assert "2 pexels" in line and "1 owned" in line
    assert "1 tenor" not in line, "a gif is not an ordinary stock fetch"


def test_the_visuals_line_says_zero_filler_out_loud(settings):
    """A filler card is the absence of a visual, so an omitted count reads
    as "fine" exactly when it is not. Said either way."""
    from pipeline.provenance import build

    clean = build(ticker="E", fmt="long", workdate="d", duration_s=1.0,
                  visual_sources={"pexels": 3})
    assert "0 filler" in clean.render_text()
    fell_back = build(ticker="E", fmt="long", workdate="d", duration_s=1.0,
                      visual_sources={"pexels": 1, "filler": 2})
    assert "2 filler" in fell_back.render_text()


# --------------------------------------------------------------------------
# N5.3 — a skipped gate does not read like a clean one.
# --------------------------------------------------------------------------


def test_a_skipped_skeptic_reads_differently_from_a_clean_one(
        settings, short_valid_json, monkeypatch):
    """N5.3: `skeptic_notes` returned `[]` for a clean script and `[]` for a
    dead daemon. A gate whose silence means two opposite things is not a
    gate, and a record whose purpose is honesty cannot render them alike."""
    import pipeline.llm as llm
    from pipeline.gates import run_gates
    from pipeline.parser_short import parse_short_script

    script, _ = parse_short_script(short_valid_json, settings=settings)

    # MOCK_MODE is one real way the pass does not run, and the suite's way.
    skipped = run_gates(script, settings, skeptic=True).ran_line()
    assert "skeptic SKIPPED" in skipped
    assert "skeptic ✓" not in skipped

    # The same battery with an LLM that answers.
    def _answered(prompt, settings, *, system="", purpose="llm"):
        return llm.LLMResult(text="thin moat — contracts are sticky",
                             provider="ollama", model="gemma4:12b",
                             reason=llm.OK)

    monkeypatch.setattr(llm, "chat_result", _answered)
    ran = run_gates(script, settings, skeptic=True).ran_line()
    assert "skeptic SKIPPED" not in ran
    assert "skeptic ⚠" in ran, f"the skeptic's notes are warnings: {ran}"
    assert ran != skipped, "a dead daemon must not render as a clean read"


def test_a_gate_that_found_nothing_is_not_a_gate_that_did_not_run(settings):
    """The distinction, at the smallest scale it exists: same zero findings,
    two different lines."""
    from pipeline.gates import GateReport

    clean = GateReport()
    clean.record("fact-check", [])
    assert clean.ran_line() == "fact-check ✓"

    absent = GateReport()
    absent.skipped("fact-check", "no company data")
    assert absent.ran_line() == "fact-check SKIPPED (no company data)"
    assert absent.ran_line() != clean.ran_line()


def test_fact_check_without_a_workbook_says_it_did_not_check(
        settings, short_valid_json):
    """`run_gates(data=None)` cannot fact-check anything. It used to report
    the same clean zero as a script checked against a full workbook."""
    from pipeline.gates import run_gates
    from pipeline.parser_short import parse_short_script

    script, _ = parse_short_script(short_valid_json, settings=settings)
    line = run_gates(script, settings, data=None, skeptic=False).ran_line()
    assert "fact-check SKIPPED (no company data)" in line
    assert "on-screen SKIPPED (no company data)" in line


# --------------------------------------------------------------------------
# N5.4 — the record round-trips, so the two surfaces cannot drift.
# --------------------------------------------------------------------------


def _full_record() -> Provenance:
    return Provenance(
        ticker="EXMPL", fmt="long", workdate="2026-09-12", duration_s=1334.0,
        prices={"source": "yahoo", "degraded": False, "days": 120,
                "as_of": "2026-09-11"},
        visuals={"pexels": 6, "wikimedia": 2, "local": 3, "tenor": 1},
        filings={"shots": 2, "refs": ["10-K 0000320193-26-000012"],
                 "brief": {"sections": 8, "context_held": True}},
        audio={"tier": "paid", "model": "eleven_v3", "chunks": 9,
               "cost_usd": 0.94},
        llm={"provider": "ollama", "model": "gemma4:12b-it-qat", "calls": 16,
             "hosted_fallbacks": 0},
        gates="fact-check ✓ · skeptic SKIPPED (no_daemon)")


def test_the_record_survives_the_manifest_unchanged(tmp_path):
    """N5.4: through a real JSON file, because that is the trip it makes."""
    p = _full_record()
    f = tmp_path / "render_long_manifest.json"
    f.write_text(json.dumps({"provenance": p.to_json()}), encoding="utf-8")
    back = Provenance.from_json(
        json.loads(f.read_text(encoding="utf-8"))["provenance"])
    assert back.render_text() == p.render_text()
    assert back.to_json() == p.to_json()


@pytest.mark.parametrize("field,mutation", [
    ("prices", {"source": "synthetic", "degraded": True}),
    ("visuals", {"filler": 4}),
    ("filings", {"shots": 9}),
    ("audio", {"tier": "free", "model": "piper", "chunks": 1}),
    ("llm", {"provider": "openai", "model": "gpt-x", "calls": 3}),
    ("gates", "voice ⛔"),
])
def test_every_line_is_derived_from_the_manifest_and_nothing_else(
        field, mutation):
    """N5.4, the half that has teeth: change the manifest, the words change.

    A line assembled from somewhere other than the block — a global, a
    re-fetch, a constant — would survive this untouched, and that is exactly
    the drift the record is supposed to make impossible.
    """
    base = _full_record()
    data = base.to_json()
    data[field] = mutation
    moved = Provenance.from_json(data).render_text()
    assert moved != base.render_text(), (
        f"{field} changed on the manifest and the delivery text did not")


def test_the_record_renders_the_specimen_in_the_brief():
    """The block as documented, so the shape is a contract rather than
    whatever the formatter happens to do today."""
    text = _full_record().render_text()
    assert text.splitlines() == [
        "EXMPL · LONG · 2026-09-12 · 22m14s",
        "prices    LIVE  yahoo · 120d · as-of 2026-09-11",
        "visuals   6 pexels · 2 wikimedia · 3 owned · 1 GIF (tenor) · 0 filler",
        "filings   2 shots · 10-K 0000320193-26-000012 · brief: 8 sections, full context",
        "audio     PAID  eleven_v3 · 9 chunks · $0.94",
        "llm       LOCAL ollama/gemma4:12b-it-qat · 16 calls",
        "gates     fact-check ✓ · skeptic SKIPPED (no_daemon)",
    ], text


def test_a_truncated_filing_brief_says_so(tmp_path):
    """K2's failure mode has a line of its own: a brief built from half a
    section reads exactly like one built from all of it."""
    from pipeline.render_long import _filing_brief_provenance

    (tmp_path / "filing_brief.json").write_text(json.dumps(
        {"sections": 8, "context_held": False, "accessions": ["x"]}),
        encoding="utf-8")
    p = Provenance(ticker="E", fmt="long", workdate="d", duration_s=1.0,
                   filings={"brief": _filing_brief_provenance(tmp_path)})
    assert "CONTEXT TRUNCATED" in p.render_text()

    (tmp_path / "filing_brief.json").write_text(json.dumps(
        {"sections": 8, "context_held": True}), encoding="utf-8")
    ok = Provenance(ticker="E", fmt="long", workdate="d", duration_s=1.0,
                    filings={"brief": _filing_brief_provenance(tmp_path)})
    assert "CONTEXT TRUNCATED" not in ok.render_text()
    assert "full context" in ok.render_text()


# --------------------------------------------------------------------------
# N5.5 — hosted spend on a local-first box is visible.
# --------------------------------------------------------------------------


def test_a_hosted_fallback_is_named_and_counted(settings, monkeypatch):
    """N5.5: `llm_provider_order` defaults to local-first, so a dead Ollama
    becomes hosted spend with nothing anywhere saying so. The provenance
    line must name the provider that actually answered and count the
    fallbacks — not read "local" by omission."""
    import pipeline.llm as llm

    live = settings.model_copy(update={
        "mock_mode": False, "llm_provider_order": "ollama,github",
        "github_models_token": "t", "filings_llm_model": "gpt-4o-mini"})

    calls: list[str] = []

    def _post(url, payload, headers, timeout):
        calls.append(url)
        if "11434" in url or "ollama" in url:
            raise ConnectionError("connection refused")
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(llm, "_post", _post)
    llm.reset_llm_calls()
    for _ in range(3):
        assert llm.chat("q", live, purpose="skeptic") == "ok"
    assert any("11434" in u or "ollama" in u for u in calls), \
        "fixture setup: the local provider must have been tried first"

    line = next(ln for ln in Provenance(
        ticker="E", fmt="long", workdate="d", duration_s=1.0,
        llm=llm.llm_summary(live)).render_text().splitlines()
        if ln.startswith("llm"))
    llm.reset_llm_calls()

    assert "HOSTED github" in line, f"the hosted provider is unnamed: {line}"
    assert "LOCAL" not in line
    assert "3 HOSTED FALLBACKS" in line, f"the spend is uncounted: {line}"


def test_a_local_answer_is_not_reported_as_a_fallback(settings, monkeypatch):
    """The other end: a box doing what it was configured to do must not
    accuse itself of spending money."""
    import pipeline.llm as llm

    live = settings.model_copy(update={
        "mock_mode": False, "llm_provider_order": "ollama,github"})

    monkeypatch.setattr(llm, "_post", lambda *a, **k: {
        "message": {"content": "ok"}})
    llm.reset_llm_calls()
    assert llm.chat("q", live, purpose="skeptic") == "ok"
    line = next(ln for ln in Provenance(
        ticker="E", fmt="long", workdate="d", duration_s=1.0,
        llm=llm.llm_summary(live)).render_text().splitlines()
        if ln.startswith("llm"))
    llm.reset_llm_calls()

    assert "LOCAL ollama/" in line
    assert "FALLBACK" not in line


def test_no_llm_ran_at_all_is_its_own_answer(settings):
    """MOCK_MODE, or a box with neither a daemon nor a token. "Nothing ran"
    and "sixteen local calls" must not both render as silence."""
    import pipeline.llm as llm

    llm.reset_llm_calls()
    assert llm.chat("q", settings, purpose="skeptic") is None
    line = next((ln for ln in Provenance(
        ticker="E", fmt="long", workdate="d", duration_s=1.0,
        llm=llm.llm_summary(settings)).render_text().splitlines()
        if ln.startswith("llm")), "")
    llm.reset_llm_calls()

    assert "none ran" in line and "mock" in line


# --------------------------------------------------------------------------
# N3 — it arrives without being asked for.
# --------------------------------------------------------------------------


def test_the_record_rides_on_the_delivery_message(settings, tmp_path):
    """N3: not a command. A `/provenance TICKER` gets typed when you already
    suspect something is wrong, which is exactly when you do not need it.

    Asserted all the way to the push the operator receives — `_done_text` —
    because every link in that chain existed before and the record still did
    not arrive: `extra_links` and `note` were computed every run and read by
    nobody (E2), which is the same defect one layer down.
    """
    from pipeline.delivery import DeliveryResult
    from pipeline.jobs import RenderJobQueue
    from pipeline.models import JobKind, JobRecord
    from pipeline.workspace import Workspace

    from bot.handlers import BotCore

    core = BotCore(settings)
    core.queue = RenderJobQueue(settings, lambda job: "")
    ws = Workspace(settings, "EXMPL", "2026-09-12")
    ws.path.mkdir(parents=True, exist_ok=True)
    (ws.path / "render_long_manifest.json").write_text(
        json.dumps({"provenance": _full_record().to_json()}), encoding="utf-8")

    job = JobRecord(id="j1", chat_id=1, ticker="EXMPL",
                    workdate="2026-09-12", kind=JobKind.RENDER_LONG)
    core.queue.store.save(job)
    core._finish(job, DeliveryResult(backend="gdrive",
                                     link="https://drive/final"))

    # The operator's message, off the persisted job — nothing here asks for
    # the record.
    text = core.queue._done_text(core.queue.store.load("j1"))
    assert "EXMPL · LONG · 2026-09-12" in text
    assert "prices    LIVE  yahoo" in text
    assert "1 GIF (tenor)" in text
    assert "audio     PAID  eleven_v3" in text


def test_a_short_leaves_a_record_too(settings, tmp_path):
    """Both manifests are read, because a SHORT is the format that ships
    most often and the one whose manifest has a different name."""
    from pipeline.models import JobKind, JobRecord
    from pipeline.workspace import Workspace

    from bot.handlers import BotCore

    core = BotCore(settings)
    ws = Workspace(settings, "EXMPL", "2026-09-12")
    ws.path.mkdir(parents=True, exist_ok=True)
    record = _full_record()
    record.fmt = "short"
    (ws.path / "short_final.manifest.json").write_text(
        json.dumps({"provenance": record.to_json()}), encoding="utf-8")

    job = JobRecord(id="j2", chat_id=1, ticker="EXMPL",
                    workdate="2026-09-12", kind=JobKind.RENDER_SHORT)
    assert "EXMPL · SHORT" in core._provenance_text(job)


def test_a_render_that_left_no_record_says_nothing(settings):
    """No manifest, no block, no noise — a missing record must not become an
    exception on the delivery path."""
    from pipeline.models import JobKind, JobRecord

    from bot.handlers import BotCore

    core = BotCore(settings)
    job = JobRecord(id="j1", chat_id=1, ticker="NOPE", workdate="2026-09-12",
                    kind=JobKind.RENDER_LONG)
    assert core._provenance_text(job) == ""
