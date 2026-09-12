"""The pre-angle filing brief (K): read the filing BEFORE choosing the angle.

`/long TICKER` built its angle prompt from workbook numbers only. The
template's filing slot was filled from the manifest `auto_filings` writes —
and `auto_filings` only runs AFTER an angle has been picked. So at angle
time the slot was always empty, and the fallback text said so outright:
"they are pulled after you pick an angle". The model proposed angles blind
to the filing and the prompt told it that was normal (K0).

Everything here runs offline in MOCK_MODE under the suite's network guard.
Where an answering LLM is needed it is injected — never reached for.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.filing_brief import FilingBrief, build_brief, load_brief


@pytest.fixture()
def answering(monkeypatch):
    """An LLM that answers, and a tally of what it was asked.

    Injected at `chat_result`, which is the one function every LLM path in
    the codebase goes through, so this also proves the brief is not talking
    to some second client of its own.
    """
    import pipeline.llm as llm

    calls: list[str] = []

    def _chat_result(prompt, settings, *, system="", purpose="llm"):
        calls.append(purpose)
        if purpose == "filing-brief-section":
            body = "- revenue concentration is named for the first time"
        elif purpose == "filing-brief-condense":
            body = ("RISK SHIFT: a supplier-concentration factor is new.\n"
                    "LANGUAGE: 'expect' became 'may'.\n"
                    "SEGMENTS: services grew, licences fell.\n"
                    "OPEN QUESTION: who is the supplier?")
        elif purpose == "filing-brief-crosscheck":
            body = ("- the numbers show FCF at -15M; the filing calls cash "
                    "generation 'improving'")
        elif purpose == "filing-brief-grade":
            body = "- claim 1: UNDERMINED — the margin kept falling"
        else:
            body = "ok"
        return llm.LLMResult(text=body, provider="ollama", model="gemma4:12b",
                             reason=llm.OK)

    monkeypatch.setattr(llm, "chat_result", _chat_result)
    return calls


@pytest.fixture()
def live(settings):
    """The suite's own MOCK_MODE settings, unchanged.

    MOCK_MODE stays ON. `chat` delegates to the module-global
    `chat_result`, so replacing that one function gives the brief an LLM
    that answers while every network path stays fixture-served — which is
    the only honest way to test this: turning MOCK_MODE off to get an
    answering model would also turn the SEC download live.
    """
    return settings


# --------------------------------------------------------------------------
# K6.1 — no filing found.
# --------------------------------------------------------------------------


def test_a_foreign_filer_yields_no_brief_and_says_why(live, answering,
                                                      tmp_path):
    """K6.1: a 20-F filer has no 10-K at all."""
    brief = build_brief("FRGN", tmp_path, live)
    assert brief.ok is False
    assert brief.reason == "no domestic filings for this ticker"
    assert answering == [], "nothing should have been read"
    assert "no filing brief" in brief.render_text()
    assert brief.reason in brief.render_text()


def test_a_ticker_the_sec_has_never_heard_of_is_the_same_outcome(
        live, answering, tmp_path):
    brief = build_brief("NOPE", tmp_path, live)
    assert brief.ok is False and brief.reason
    assert answering == []


def test_the_angle_prompt_still_builds_with_no_brief(settings, workspace):
    """K6.1's real assertion: the prompt is unaffected. A survey that cannot
    be produced must cost nothing — the operator gets the angle step they
    have always had."""
    from pipeline.company_data import load_company_data

    from bot.prompts import fill_prompt

    data = load_company_data(workspace)
    text = fill_prompt("long_angle", "EXMPL", data, workspace, settings)
    assert "{{filing_brief}}" not in text, "the token reached the writer raw"
    assert "the filing has not been read for this ticker yet" in text
    # …and the writing prompt is untouched by any of this.
    assert "{{" not in fill_prompt("long_write", "EXMPL", data, workspace,
                                   settings).replace("{{placeholder}}", "")


# --------------------------------------------------------------------------
# K6.2 — the LLM is unavailable.
# --------------------------------------------------------------------------


def test_a_dead_llm_yields_no_brief_and_does_not_raise(settings, tmp_path):
    """K6.2. MOCK_MODE is exactly this case: `chat` returns None before it
    touches httpx, which is also what a box with no daemon and no token
    does."""
    brief = build_brief("EXMPL", tmp_path, settings)
    assert brief.ok is False
    assert brief.reason == "no LLM answered — the filing was not read"
    # The filings were still identified, which is worth keeping: it says the
    # reading failed at the model, not at the SEC.
    assert brief.accessions
    assert "no filing brief" in brief.render_text()


def test_a_condensation_that_does_not_answer_is_its_own_reason(
        live, monkeypatch, tmp_path):
    """The sections summarised and the final pass did not. Two different
    failures, and a brief that said "not run" for both would hide one."""
    import pipeline.llm as llm

    def _chat_result(prompt, settings, *, system="", purpose="llm"):
        if purpose == "filing-brief-condense":
            return llm.LLMResult(reason=llm.TIMEOUT, provider="ollama")
        return llm.LLMResult(text="- a note", provider="ollama",
                             model="m", reason=llm.OK)

    monkeypatch.setattr(llm, "chat_result", _chat_result)
    brief = build_brief("EXMPL", tmp_path, live)
    assert brief.ok is False
    assert brief.reason == "the condensation pass did not answer"
    assert brief.sections > 0, "the sections WERE read — say so"


def test_a_reading_that_explodes_degrades_to_no_brief(live, monkeypatch,
                                                      tmp_path):
    """"Never blocks" has to survive a bug, not just a failure."""
    import pipeline.filings as F

    monkeypatch.setattr(F, "segment_filing",
                        lambda html: (_ for _ in ()).throw(RuntimeError("boom")))
    brief = build_brief("EXMPL", tmp_path, live)
    assert brief.ok is False
    assert "failed" in brief.reason or "not read" in brief.reason


# --------------------------------------------------------------------------
# K6.3 — the second run costs nothing.
# --------------------------------------------------------------------------


def test_a_second_run_downloads_nothing_and_asks_nothing(live, answering,
                                                         tmp_path):
    """K6.3: counting fakes, not log assertions.

    Cached on the ACCESSION SET under `cache_dir`, so it survives the
    workspace — the win is the re-visit weeks later against filings that
    have not changed, not the same-day re-run.
    """
    first: dict = {}
    a = build_brief("EXMPL", tmp_path / "ws1", live, counters=first)
    assert a.ok, a.reason
    assert first["download"] >= 2, "two annual reports should have been read"
    assert first["llm"] >= 3
    calls_after_first = len(answering)

    second: dict = {}
    b = build_brief("EXMPL", tmp_path / "ws2", live, counters=second)
    assert b.ok
    assert b.body == a.body
    assert second.get("download", 0) == 0, "the second run re-downloaded"
    assert second.get("llm", 0) == 0, "the second run re-read the filings"
    assert len(answering) == calls_after_first


def test_the_cache_is_keyed_on_the_filings_not_the_ticker(live, answering,
                                                          tmp_path):
    """A new filing invalidates the brief, which is the only thing that
    should. Keyed on the ticker it would go stale on the day it matters."""
    from pipeline.filing_brief import cache_path

    build_brief("EXMPL", tmp_path / "ws", live)
    a = cache_path(["0001234567-26-000012"], live)
    b = cache_path(["0001234567-26-000012", "0001234567-25-000008"], live)
    assert a != b
    # …and the order the refs came back in must not change the key.
    assert cache_path(["b", "a"], live) == cache_path(["a", "b"], live)

    # AND THE CONTEXT BUDGET IS PART OF THE KEY. A brief built under a
    # truncating window is a different, worse artefact, so raising
    # `num_ctx` has to invalidate it — otherwise the box keeps being served
    # the partial brief out of the cache, which is the very failure the
    # `context_held` field exists to reveal.
    tiny = live.model_copy(update={"ollama_num_ctx": 1300})
    assert cache_path(["a"], tiny) != cache_path(["a"], live)

    partial = build_brief("EXMPL", tmp_path / "tiny", tiny)
    assert partial.context_held is False
    roomy = build_brief("EXMPL", tmp_path / "roomy", live)
    assert roomy.context_held is True, \
        "the truncated brief was served back for a roomier window"


# --------------------------------------------------------------------------
# What the brief actually says.
# --------------------------------------------------------------------------


def test_the_brief_reaches_the_angle_prompt(live, answering, workspace):
    """The whole point of K, asserted on the text the model receives."""
    from pipeline.company_data import load_company_data
    from pipeline.filing_brief import save_brief

    from bot.prompts import fill_prompt

    brief = build_brief("EXMPL", workspace, live)
    assert brief.ok, brief.reason
    save_brief(workspace, brief, live)

    data = load_company_data(workspace)
    text = fill_prompt("long_angle", "EXMPL", data, workspace, live)
    assert "RISK SHIFT: a supplier-concentration factor is new." in text
    assert "10-K 2025-12-31" in text, "the prompt says WHICH filings were read"
    # And the quotes slot no longer tells the reader filing material is
    # unavailable at this step (K4).
    assert "they are pulled after you pick an angle" not in text
    assert "The filing survey above is separate" in text


def test_the_workbook_cross_check_is_the_highest_value_line(live, answering,
                                                            workspace):
    """K1/K3: a filing that disagrees with the numbers the operator loaded
    is exactly the tension the angle step is looking for — and it is one
    cheap call over material already summarised, not a second reading."""
    from pipeline.company_data import load_company_data
    from pipeline.filing_brief import cross_check

    brief = build_brief("EXMPL", workspace, live)
    before = len(answering)
    cross_check(brief, load_company_data(workspace), live)

    assert len(answering) - before == 1, "the cross-check is ONE call"
    assert answering[-1] == "filing-brief-crosscheck"
    assert "cash generation" in brief.contradictions
    assert "AGAINST OUR NUMBERS:" in brief.render_text()


def test_the_cross_check_is_skipped_when_there_is_nothing_to_check(
        live, answering, workspace):
    """No workbook, no cross-check — and no call spent finding that out."""
    from pipeline.filing_brief import cross_check

    brief = build_brief("EXMPL", workspace, live)
    before = len(answering)
    cross_check(brief, None, live)
    assert len(answering) == before
    assert brief.contradictions == ""


def test_the_update_lane_grades_the_last_video_against_the_filing(
        live, answering, workspace):
    """K5b: `/update` asks "what changed since we last covered this", which
    is literally a year-over-year filing diff — so the update lane wants
    this brief more than the long lane does."""
    from pipeline.filing_brief import grade_prior_coverage

    brief = build_brief("EXMPL", workspace, live)
    grade_prior_coverage(brief, "HOOK: it looked cheap.\nCLAIM: margins "
                         "would recover by Q3.", live)
    assert answering[-1] == "filing-brief-grade"
    assert "UNDERMINED" in brief.grading
    assert "AGAINST WHAT WE SAID LAST TIME:" in brief.render_text()


def test_grading_a_placeholder_is_not_grading(live, answering, workspace):
    """`prior_coverage` returns its own empty-state prose when there is no
    thesis on file. Feeding that to the model spends a call to be told
    nothing."""
    from pipeline.filing_brief import grade_prior_coverage

    brief = build_brief("EXMPL", workspace, live)
    before = len(answering)
    grade_prior_coverage(brief, "(no thesis on file for this ticker — "
                         "nothing was recorded from a previous video.)", live)
    assert len(answering) == before
    assert brief.grading == ""


def test_a_truncated_section_is_confessed_in_the_brief_itself(
        live, answering, tmp_path):
    """K2's failure mode is the one this feature could most easily commit:
    Ollama does not error on an overflowing prompt — it drops the front and
    summarises what remains, so a brief built from half a section reads
    exactly like one built from all of it."""
    # ~990 chars of usable prompt, under the fixture's 1,097-char Risk
    # Factors section — so the packer has to clip it.
    tiny = live.model_copy(update={"ollama_num_ctx": 1300})
    brief = build_brief("EXMPL", tmp_path, tiny)
    assert brief.ok, brief.reason
    assert brief.context_held is False
    text = brief.render_text()
    assert "WARNING" in text and "did not fit" in text
    assert text.index("WARNING") < text.index("RISK SHIFT"), \
        "the warning has to come before the notes it is about"

    # The honest case must not cry wolf.
    roomy = build_brief("EXMPL", tmp_path / "other", live)
    assert roomy.context_held is True
    assert "WARNING" not in roomy.render_text()


def test_the_record_round_trips_through_the_workspace(live, answering,
                                                      tmp_path):
    """The brief on disk is what the prompt and the provenance record both
    read, so the file is the contract."""
    from pipeline.filing_brief import save_brief

    brief = build_brief("EXMPL", tmp_path, live)
    save_brief(tmp_path, brief, live)
    back = load_brief(tmp_path)
    assert back is not None
    assert back.to_json() == brief.to_json()
    assert back.render_text() == brief.render_text()

    # And the render's provenance reads the same file (N2).
    from pipeline.render_long import _filing_brief_provenance

    prov = _filing_brief_provenance(tmp_path)
    assert prov["sections"] == brief.sections
    assert prov["context_held"] is True


# --------------------------------------------------------------------------
# K3 — sequencing: the reading starts at /long, not at the upload.
# --------------------------------------------------------------------------


def test_starting_a_long_lane_queues_the_reading_immediately(settings,
                                                             monkeypatch):
    """K3: ten minutes of dead time AFTER an upload is the difference
    between a feature that gets used and one that gets switched off. The
    reading needs only EDGAR, so it runs while the operator refreshes the
    workbook."""
    from bot.handlers import BotCore

    started: list[str] = []
    core = BotCore(settings)
    monkeypatch.setattr(core, "_start_filing_read",
                        lambda ws: started.append(ws.ticker))

    core.start_lane(4242, "long", "EXMPL")
    assert started == ["EXMPL"], "the reading did not start at /long"

    # A SHORT has no angle step and no filing brief — nothing is queued.
    started.clear()
    core.start_lane(4242, "short", "EXMPL")
    assert started == []


def test_the_reading_runs_off_the_calling_thread(settings):
    """It must not block the reply. `/long` answers with the template while
    the SEC pull is still going."""
    from bot.handlers import BotCore
    from pipeline.workspace import Workspace

    core = BotCore(settings)
    ws = Workspace(settings, "EXMPL", "2026-09-12").create()
    fut = core._start_filing_read(ws)
    assert fut is not None and hasattr(fut, "result")
    fut.result(timeout=60)
    assert load_brief(ws.path) is not None, "the brief was never written"


def test_the_upload_folds_in_the_half_that_needed_the_workbook(
        settings, monkeypatch, fixtures_dir):
    """K3's second half, end to end through the bot: the upload reply says
    the brief is ready and what is in it."""
    import pipeline.llm as llm

    from bot.handlers import BotCore

    def _chat_result(prompt, settings, *, system="", purpose="llm"):
        body = {"filing-brief-section": "- a note",
                "filing-brief-condense": "RISK SHIFT: a new one.",
                "filing-brief-crosscheck": "- FCF disagrees"}.get(purpose, "")
        return llm.LLMResult(text=body, provider="ollama", model="m",
                             reason=llm.OK if body else llm.EMPTY)

    monkeypatch.setattr(llm, "chat_result", _chat_result)
    core = BotCore(settings)
    core.start_lane(4242, "long", "EXMPL")
    xlsx = (fixtures_dir / "company_data" / "dennis_data.xlsx").read_bytes()
    reply = core.handle_upload(4242, "dennis_data.xlsx", xlsx)

    assert "filing brief ready" in reply.text
    assert "cross-checked against your numbers" in reply.text
    ws = core.context.get(4242)
    brief = load_brief(ws.path)
    assert brief is not None and brief.contradictions


def test_an_upload_with_no_brief_says_so_rather_than_nothing(settings,
                                                             fixtures_dir):
    """MOCK_MODE: no LLM, so no brief. The operator is told, because a
    silent absence is how the empty filing slot went unnoticed for the life
    of the feature."""
    from bot.handlers import BotCore

    core = BotCore(settings)
    core.start_lane(4242, "long", "EXMPL")
    xlsx = (fixtures_dir / "company_data" / "dennis_data.xlsx").read_bytes()
    reply = core.handle_upload(4242, "dennis_data.xlsx", xlsx)
    assert "no filing brief" in reply.text
    assert "no LLM answered" in reply.text


def test_the_switch_turns_the_whole_thing_off(settings, fixtures_dir):
    """One knob, and nothing downstream changes shape when it is off."""
    from bot.handlers import BotCore
    from pipeline.workspace import Workspace

    off = settings.model_copy(update={"filing_brief_enabled": False})
    core = BotCore(off)
    ws = Workspace(off, "EXMPL", "2026-09-12").create()
    assert core._start_filing_read(ws) is None
    assert core._finish_filing_read(ws) == ""
    assert load_brief(ws.path) is None


def test_the_post_angle_quote_pull_is_untouched(settings, workspace):
    """K5: `auto_filings` stays where it is and keeps doing its own job —
    verbatim quotes for a CHOSEN thesis, located in the DOM and
    screenshotted. A survey and a receipt are not merged."""
    from pipeline.filings import auto_filings, load_manifest

    shots = auto_filings("EXMPL", "the debt is the story", workspace,
                         settings, max_shots=2)
    assert isinstance(shots, list)
    manifest = load_manifest(workspace)
    assert "shots" in manifest
    # The brief and the manifest are different files, deliberately.
    assert (workspace / "filings").is_dir()
    assert load_brief(workspace) is None


def test_the_filings_module_has_one_llm_path(settings, monkeypatch):
    """K2: `filings._llm_chat` was a private httpx client reading
    `filings_llm_provider`, while `llm.chat` routed `ollama,github,openai`.
    Two provider-resolution paths in one module is how they drift — and
    they had: a box with Ollama running served every gate locally and every
    filing call over the network, for money, with nothing saying so."""
    import pipeline.filings as F
    import pipeline.llm as llm

    seen: list[str] = []

    def _post(url, payload, headers, timeout):
        seen.append(url)
        return {"message": {"content": "routed"}}

    monkeypatch.setattr(llm, "_post", _post)
    live = settings.model_copy(update={"mock_mode": False})
    assert F._llm_chat("q", live) == "routed"
    assert seen and "11434" in seen[0], \
        f"the filing pass did not go through the local-first router: {seen}"

    # The httpx client it used to own is gone.
    src = Path(F.__file__).read_text(encoding="utf-8")
    body = src.split("def _llm_chat")[1].split("\ndef ")[0]
    assert "httpx.post" not in body
    assert "github_models_endpoint" not in body


# --------------------------------------------------------------------------
# P1 — the reader does not own the process's exit.
# --------------------------------------------------------------------------


def test_a_reading_in_flight_does_not_hold_the_process_open():
    """P1: the pool this replaced was a `ThreadPoolExecutor` nobody shut
    down. Its threads are non-daemon and it registers an atexit handler that
    JOINS them, so stopping the bot during an eight-to-ten-minute reading
    hung until the reading finished. That reads as a frozen shutdown, the
    reflex is `kill -9`, and that is how half-written state happens.

    Asserted by actually exiting a Python process with a reading still
    running — the only version of this claim that means anything.
    """
    import subprocess
    import sys
    import textwrap
    import time

    root = Path(__file__).resolve().parents[1]
    prog = textwrap.dedent(f"""
        import sys, time
        sys.path.insert(0, {str(root)!r})
        from pipeline.filing_brief import FilingReader
        r = FilingReader()
        r.submit("SLOW 2026-09-12", lambda: time.sleep(300))
        time.sleep(0.3)          # let it actually start
        print("started", flush=True)
    """)
    t0 = time.monotonic()
    done = subprocess.run([sys.executable, "-c", prog],
                          capture_output=True, text=True, timeout=60)
    elapsed = time.monotonic() - t0
    assert "started" in done.stdout
    assert elapsed < 20, (
        f"the interpreter took {elapsed:.0f}s to exit with a reading in "
        f"flight — it is waiting for the worker, which is the hang P1 is "
        f"about")


def test_shutdown_names_every_brief_it_abandons(caplog):
    """A dropped brief has to be said out loud. Silence here means re-running
    `/long` and wondering why the angle prompt has no filing in it."""
    import threading

    from pipeline.filing_brief import FilingReader

    started = threading.Event()
    release = threading.Event()
    r = FilingReader()

    def _slow():
        started.set()
        release.wait(timeout=30)
        return "late"

    running = r.submit("EXMPL 2026-09-12", _slow)
    assert started.wait(timeout=10)
    queued = r.submit("MEGA 2026-09-12", lambda: "never")

    with caplog.at_level("WARNING"):
        abandoned = r.shutdown()

    assert "EXMPL 2026-09-12" in abandoned, "the one in flight went unnamed"
    assert "MEGA 2026-09-12" in abandoned, "the queued one went unnamed"
    assert queued.cancelled(), "a queued reading must be dropped, not run"
    logged = " ".join(rec.getMessage() for rec in caplog.records)
    assert "EXMPL" in logged and "MEGA" in logged
    assert "abandoned" in logged.lower()

    # And nothing new is accepted after the switch is off.
    assert r.submit("LATE 2026-09-12", lambda: "no").cancelled()
    release.set()
    running.result(timeout=30)


def test_a_cancelled_reading_lets_the_upload_through(settings, monkeypatch):
    """The other end of the same wire: if the reader is shut down while an
    upload is waiting on it, the operator gets their prompt and a line
    saying why there is no brief — not a stack trace and not a hang."""
    import threading

    from bot.handlers import BotCore
    from pipeline.workspace import Workspace

    core = BotCore(settings)
    ws = Workspace(settings, "EXMPL", "2026-09-12").create()

    started = threading.Event()
    fut = core.filing_reader.submit(
        "EXMPL 2026-09-12", lambda: (started.set(), __import__("time").sleep(5))[0])
    assert started.wait(timeout=10)
    core._filing_reads[core._filing_read_key(ws)] = fut
    fut.cancel()                       # what shutdown() does to a queued one

    note = core._finish_filing_read(ws)
    assert "no filing brief" in note or "cancelled" in note
