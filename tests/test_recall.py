"""The journal, the search over everything the bot saved, and `/ask`.

What is pinned here is the part that would otherwise drift or lie quietly:
the journal surviving whatever writes to it, the index noticing a change,
the model's description of its own job keeping up with the code, counts and
totals never reaching the model, and a number the model made up being named.
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from pipeline import journal, llm, recall, tally
from pipeline.jobs import JobStore
from pipeline.models import JobKind, JobRecord, JobStatus

ROOT = Path(__file__).resolve().parents[1]
TODAY = date(2026, 9, 25)


# ---------------------------------------------------------------- helpers

def _workspace(settings, ticker="EXMPL", workdate="2026-09-12", *,
               narration="Gross margin fell for the third quarter running.",
               brief=""):
    d = settings.workspace_dir / ticker / workdate
    d.mkdir(parents=True, exist_ok=True)
    (d / "script_long.json").write_text(json.dumps(
        {"title": f"{ticker} deep dive", "narration": narration}),
        encoding="utf-8")
    (d / "lane.json").write_text(json.dumps({"lane": "long"}),
                                 encoding="utf-8")
    (d / "long_angle.json").write_text(json.dumps(
        {"awaiting": False, "chosen": "the margin story is cracking"}),
        encoding="utf-8")
    if brief:
        (d / "filing_brief.json").write_text(json.dumps(
            {"ticker": ticker, "filings": "10-K 2025", "body": brief}),
            encoding="utf-8")
    return d


def _thesis(settings, ticker="EXMPL", status="cracking"):
    path = settings.state_dir / "theses.json"
    book = (json.loads(path.read_text(encoding="utf-8"))
            if path.exists() else {})
    book[ticker] = {"ticker": ticker, "summary": "pricing power is fading",
                    "status": status, "workdate": "2026-09-12",
                    "claims": ["gross margin keeps sliding"]}
    path.write_text(json.dumps(book), encoding="utf-8")


def _job(settings, ticker, kind, status, when: str):
    job = JobRecord(id=uuid.uuid4().hex[:10], kind=kind, ticker=ticker,
                    workdate=when[:10], status=status)
    store = JobStore(settings)
    store.save(job)
    # `save` stamps now; the tests need the job to have finished on `when`.
    raw = json.loads(store.path(job.id).read_text(encoding="utf-8"))
    raw["updated_at"] = when
    store.path(job.id).write_text(json.dumps(raw), encoding="utf-8")
    return job


def _local_noon(day: date) -> str:
    """A UTC stamp that is `day` in the machine's local time."""
    local = datetime(day.year, day.month, day.day, 12).astimezone()
    return local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class _Model:
    """Stands in for `llm.chat_result` and records what it was asked."""

    def __init__(self, expansion='["gross margin", "profitability"]',
                 answer="Margins were cracking [1]."):
        self.calls: list[dict] = []
        self.expansion = expansion
        self.answer = answer

    def __call__(self, prompt, settings, *, system="", purpose="llm",
                 providers=None):
        self.calls.append({"prompt": prompt, "system": system,
                           "purpose": purpose, "providers": providers})
        text = self.expansion if purpose == "ask-expand" else self.answer
        return llm.LLMResult(text=text, provider=llm.OLLAMA,
                             model="gemma4:12b-it-qat", reason=llm.OK)


# ---------------------------------------------------------------- journal

def test_the_journal_reads_back_what_was_written(settings):
    journal.note(settings, "video", "started a LONG", ticker="exmpl",
                 workdate="2026-09-12", lane="long")
    journal.note(settings, "approved", "approved the LONG script")
    rows = journal.entries(settings)
    assert [r.kind for r in rows] == ["video", "approved"]
    assert rows[0].ticker == "EXMPL"
    assert rows[0].data == {"lane": "long"}
    assert journal.entries(settings, kinds=("approved",))[0].text.startswith(
        "approved")
    assert journal.entries(settings, ticker="EXMPL")[0].kind == "video"


def test_a_journal_that_cannot_be_written_never_raises(settings, tmp_path):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("a file where the state dir should be",
                       encoding="utf-8")
    settings.state_dir = blocker
    journal.note(settings, "video", "this line has nowhere to go")
    assert journal.entries(settings) == []


def test_a_torn_last_line_is_skipped_not_fatal(settings):
    journal.note(settings, "video", "one")
    with journal.path_for(settings).open("a", encoding="utf-8") as f:
        f.write('{"at": "2026-09-2')          # the crash mid-write
    assert [e.text for e in journal.entries(settings)] == ["one"]


def test_the_journal_rolls_rather_than_growing_forever(settings, monkeypatch):
    monkeypatch.setattr(journal, "MAX_BYTES", 200)
    for n in range(10):
        journal.note(settings, "job", f"line {n} " + "x" * 40)
    assert journal.path_for(settings).stat().st_size <= 400
    rolled = journal.path_for(settings).with_name(journal.ROLLED_FILE)
    assert rolled.exists()
    # Both halves are read back, oldest first.
    texts = [e.text for e in journal.entries(settings)]
    assert texts == sorted(texts, key=lambda t: int(t.split()[1]))


def test_every_model_call_leaves_a_journal_line_under_its_video(settings):
    with llm.llm_scope("EXMPL/2026-09-12"):
        llm.chat_result("anything", settings, purpose="skeptic")
    (line,) = journal.entries(settings, kinds=("ai",))
    assert line.ticker == "EXMPL" and line.workdate == "2026-09-12"
    assert line.data["purpose"] == "skeptic"
    assert line.data["reason"] == llm.MOCK
    assert "skipped (MOCK_MODE)" in line.text


def test_a_job_leaves_a_line_at_every_change_of_state(settings):
    from pipeline.jobs import RenderJobQueue

    async def run():
        queue = RenderJobQueue(settings, executor=lambda job: "/tmp/out.mp4")
        job = await queue.submit(JobKind.RENDER_SHORT, "EXMPL", "2026-09-12")
        queue.cancel("EXMPL")
        return job

    job = asyncio.run(run())
    texts = [e.text for e in journal.entries(settings, kinds=("job",))]
    assert texts == ["render_short queued",
                     "render_short cancelled by the operator"]
    assert journal.entries(settings)[0].data["job_id"] == job.id


def test_an_upload_is_journaled_once_not_on_every_rewrite(settings):
    from pipeline.youtube import VideoLog, VideoRecord

    log = VideoLog(settings)
    video = VideoRecord(ticker="EXMPL", video_id="abc123", title="EXMPL: the "
                        "margin story", privacy="private", workdate="2026-09-12")
    log.record(video)
    log.record(video)                  # a retention refresh rewrites the row
    (line,) = journal.entries(settings, kinds=("uploaded",))
    assert "EXMPL: the margin story" in line.text


# ---------------------------------------------------------------- the passes

def _purposes_in_code() -> set[str]:
    found: set[str] = set()
    for path in list((ROOT / "pipeline").glob("*.py")) + list(
            (ROOT / "bot").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        found |= set(re.findall(r'purpose(?:: str)?\s*=\s*"([^"]+)"', text))
    return found


def test_every_pass_the_code_runs_is_described_to_the_model():
    """The model is told what it does inside the bot from `PURPOSES`. A pass
    added without a line there would be one it cannot account for."""
    used = _purposes_in_code()
    assert {"skeptic", "filing-brief-section", "ask"} <= used, used
    missing = used - set(llm.PURPOSES)
    assert not missing, f"describe these in pipeline.llm.PURPOSES: {missing}"


def test_the_self_description_is_built_from_the_code(settings):
    text = recall.self_description(settings)
    for name in llm.PURPOSES:
        if name != "llm":
            assert name in text
    commands = recall.commands()
    assert len(commands) >= 25
    usages = " ".join(u for u, _ in commands)
    for cmd in ("/ask", "/find", "/thesis", "/render", "/update"):
        assert cmd in usages
    assert settings.ollama_model in text
    assert "MOCK_MODE is ON" in text


# ---------------------------------------------------------------- the index

def test_find_reaches_scripts_briefs_and_theses_with_stemming(settings):
    _workspace(settings, brief="Risk factors now name a supplier dispute.")
    _thesis(settings)
    out = recall.find_text(settings, "margins")         # the script says margin
    assert "script · EXMPL · 2026-09-12" in out
    assert "thesis" in recall.find_text(settings, "pricing power")
    assert "filing brief" in recall.find_text(settings, "supplier dispute")


def test_find_falls_back_to_any_word_and_says_so(settings):
    _workspace(settings)
    out = recall.find_text(settings, "margin zeppelin")
    assert "nothing has every word" in out
    assert "EXMPL" in out
    assert recall.find_text(settings, "zeppelin").startswith("Nothing on file")


def test_search_words_that_are_fts_syntax_are_searched_not_obeyed(settings):
    _workspace(settings)
    for query in ('margin AND NEAR(', '"unbalanced', "gross-margin*", "OR"):
        recall.find_text(settings, query)      # must not raise


def test_the_index_rebuilds_when_a_record_changes_and_only_then(settings):
    _workspace(settings)
    index = recall.Index(settings).refresh()
    built = index.path.stat().st_mtime_ns
    recall.Index(settings).refresh()
    assert index.path.stat().st_mtime_ns == built       # nothing changed
    _thesis(settings, "NEWCO")
    assert recall.find_text(settings, "NEWCO").startswith("🔎")


def test_the_readme_and_commands_are_searchable(settings):
    out = recall.find_text(settings, "reconciled")
    assert "/cost" in out


def test_tickers_count_only_in_capitals_or_with_a_dollar():
    known = {"COST", "EXMPL"}
    assert recall.mentioned_tickers("what did voice cost", known) == set()
    assert recall.mentioned_tickers("what did we say on COST", known) == {"COST"}
    assert recall.mentioned_tickers("and $exmpl?", known) == {"EXMPL"}


# ---------------------------------------------------------------- tally

@pytest.mark.parametrize("text,start,end", [
    ("how many this month", date(2026, 9, 1), TODAY),
    ("in August", date(2026, 8, 1), date(2026, 8, 31)),
    ("during december", date(2025, 12, 1), date(2025, 12, 31)),
    ("in May 2026", date(2026, 5, 1), date(2026, 5, 31)),
    ("last week", date(2026, 9, 14), date(2026, 9, 20)),
    ("yesterday", date(2026, 9, 24), date(2026, 9, 24)),
    ("the last 7 days", date(2026, 9, 19), TODAY),
    ("in 2026-03", date(2026, 3, 1), date(2026, 3, 31)),
])
def test_periods(text, start, end):
    period = tally.parse_period(text, TODAY)
    assert (period.start, period.end) == (start, end)


def test_may_the_verb_is_not_may_the_month():
    assert tally.parse_period("which renders may fail", TODAY) is None


@pytest.mark.parametrize("question,topic", [
    ("how many shorts did we finish this month?", "videos"),
    ("what did voice cost in August", ""),     # no counting word: the model's
    ("how much did we spend in August", "spend"),
    ("how many times did the model fall back to hosted", "ai"),
    ("what's in the queue", "queue"),
    ("how many shorts are queued", "queue"),
    ("how many theses are broken", "theses"),
    ("what did we say about EXMPL's margins", ""),
])
def test_routing(question, topic):
    assert tally.route(question) == topic


def test_video_counts_come_from_the_job_records(settings):
    _job(settings, "EXMPL", JobKind.RENDER_SHORT, JobStatus.DONE,
         _local_noon(date(2026, 9, 3)))
    _job(settings, "OTHR", JobKind.RENDER_LONG, JobStatus.DONE,
         _local_noon(date(2026, 9, 10)))
    _job(settings, "OTHR", JobKind.RENDER_SHORT, JobStatus.FAILED,
         _local_noon(date(2026, 9, 11)))
    _job(settings, "OLD", JobKind.RENDER_SHORT, JobStatus.DONE,
         _local_noon(date(2026, 8, 30)))
    _job(settings, "EXMPL", JobKind.RENDER_PROOF_SHORT, JobStatus.DONE,
         _local_noon(date(2026, 9, 4)))
    out = tally.answer(settings, "how many videos did we finish this month?",
                       today=TODAY)
    assert "this month: 2 (1 short, 1 long, 0 clips)" in out
    assert "OLD" not in out and "FAILED" not in out
    assert "proof" not in out
    out = tally.answer(settings, "how many videos and proofs this month",
                       today=TODAY)
    assert "1 proof" in out


def test_spend_comes_from_the_ledger_and_is_added_up_by_code(settings):
    (settings.state_dir / "spend.json").write_text(json.dumps({
        "2026-08": {"tts_usd": 4.5, "llm_usd": 0.0, "pexels_calls": 3},
        "2026-09": {"tts_usd": 1.25, "pexels_calls": 1},
    }), encoding="utf-8")
    out = tally.answer(settings, "how much did we spend in August",
                       today=TODAY)
    assert "August 2026: voice $4.50" in out and "September" not in out
    out = tally.answer(settings, "how much have we spent in total",
                       today=TODAY)
    assert "Voice total, all time: $5.75." in out


def test_model_activity_says_when_the_journal_started(settings):
    with llm.llm_scope("EXMPL/2026-09-12"):
        llm.chat_result("x", settings, purpose="skeptic")
    out = tally.answer(settings, "how many times did the model run",
                       today=date.today())
    assert "0 answered locally" in out and "1 did not run" in out
    assert "The journal starts on" in out


# ---------------------------------------------------------------- /ask

def test_a_count_never_reaches_the_model(settings, monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("a count went to the model")

    monkeypatch.setattr(llm, "chat_result", refuse)
    answer = recall.ask(settings, "how many shorts did we finish this month?")
    assert answer.by_code
    assert "counted by the bot's code" in answer.text
    assert journal.entries(settings, kinds=("asked",))[0].data[
        "answered_by"] == "code"


def test_ask_in_mock_mode_says_why_and_shows_the_search(settings):
    _workspace(settings)
    answer = recall.ask(settings, "what did we say about margins?")
    assert answer.text.startswith("The local AI did not answer: MOCK_MODE")
    assert "EXMPL" in answer.text


def test_ask_reads_the_records_and_cites_them(settings, monkeypatch):
    _workspace(settings, narration="Gross profit is shrinking, again.")
    _thesis(settings)
    model = _Model()
    monkeypatch.setattr(llm, "chat_result", model)
    answer = recall.ask(settings, "what did we say about EXMPL?")
    expand_call, answer_call = model.calls
    assert expand_call["purpose"] == "ask-expand"
    assert answer_call["purpose"] == "ask"
    # Local only unless the operator says otherwise.
    assert answer_call["providers"] == ["ollama"]
    assert "Gross profit is shrinking" in answer_call["prompt"]
    assert "pricing power is fading" in answer_call["prompt"]
    assert "FACTS (counted by the bot's code" in answer_call["prompt"]
    assert "You are the local assistant inside Dennis" in answer_call["system"]
    assert "Margins were cracking [1]." in answer.text
    assert "Read: [1]" in answer.text
    assert "answered locally" in answer.text


def test_the_model_s_rewording_finds_what_the_words_alone_would_not(
        settings, monkeypatch):
    _workspace(settings, narration="Gross profit is shrinking, again.")
    model = _Model(expansion='["gross profit", "shrinking"]')
    monkeypatch.setattr(llm, "chat_result", model)
    recall.ask(settings, "which video worried about profitability?")
    assert "Gross profit is shrinking" in model.calls[1]["prompt"]


def test_a_number_the_model_made_up_is_named(settings, monkeypatch):
    _workspace(settings, narration="Gross margin fell to 41.5% this year.")
    model = _Model(answer="Gross margin fell to 41.5% [1], down 37 points.")
    monkeypatch.setattr(llm, "chat_result", model)
    answer = recall.ask(settings, "what happened to EXMPL's margin?")
    assert "⚠️ Not in anything it read: 37." in answer.text
    assert "41.5" not in answer.text.split("⚠️")[1]


def test_unsupported_numbers_ignore_citations_and_formatting():
    given = "Revenue was $1,200 million, 12.50% up, on 2026-09-12."
    assert recall.unsupported_numbers(
        "Revenue $1200 million [1], 12.5% [2, 3] on 2026-09-12.", given) == []
    assert recall.unsupported_numbers("It was 13%.", given) == ["13%"]


def test_a_missing_model_is_one_quick_probe_not_two_waits(settings,
                                                         monkeypatch):
    _workspace(settings)
    calls = []

    def absent(prompt, settings, **kw):
        calls.append(kw["purpose"])
        return llm.LLMResult(provider=llm.OLLAMA, reason=llm.NO_DAEMON)

    monkeypatch.setattr(llm, "chat_result", absent)
    answer = recall.ask(settings, "what did we say about margins?")
    assert calls == ["ask-expand"]
    assert "is Ollama running?" in answer.text
    assert "EXMPL" in answer.text


def test_the_prompt_fits_the_context_the_model_is_given(settings, monkeypatch):
    for n in range(12):
        _workspace(settings, f"TK{n:02d}", narration="margin " * 3000)
    settings.ollama_num_ctx = 4096
    model = _Model()
    monkeypatch.setattr(llm, "chat_result", model)
    recall.ask(settings, "margin")
    call = model.calls[1]
    chars = len(call["prompt"]) + len(call["system"])
    room = (4096 - recall._ANSWER_TOKENS) * recall._CHARS_PER_TOKEN
    assert chars <= room, chars
    # It made room by dropping the command list, not the records.
    assert "The operator's commands:" not in call["system"]
    assert call["prompt"].count("\n[") >= 2


def test_a_normal_context_carries_the_command_list(settings, monkeypatch):
    _workspace(settings)
    model = _Model()
    monkeypatch.setattr(llm, "chat_result", model)
    recall.ask(settings, "margin")
    assert "The operator's commands:" in model.calls[1]["system"]


def test_an_empty_question_explains_itself(settings):
    assert recall.ask(settings, "  ").text.startswith("usage: /ask")
    assert recall.find_text(settings, "").startswith("usage: /find")


# ---------------------------------------------------------------- the bot

def test_the_bot_sends_a_bare_string_reply():
    """Eleven read commands return strings. `_send` read `.text` off them."""
    from bot.handlers import _send

    sent = []

    class _Msg:
        async def reply_text(self, text, reply_markup=None):
            sent.append(text)

    class _Update:
        effective_message = _Msg()

    asyncio.run(_send(_Update(), "Nothing in the corpus says it."))
    assert sent == ["Nothing in the corpus says it."]


def test_the_bot_answers_find_and_ask(settings):
    from bot.handlers import BotCore

    _workspace(settings)
    core = BotCore(settings)
    assert "EXMPL" in core.find_text(["margin"])
    assert core.ask_text([]).startswith("usage: /ask")
