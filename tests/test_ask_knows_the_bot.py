"""`/ask` knows the bot as it is right now (10-23): the drawers the bot
opens for the model (`bot.bot_facts`), the manual pinned to the code, no
secret ever in a drawer, and a question that waits while a render holds
the graphics card."""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

import pytest

from bot.bot_facts import CHECKS, SCREENS, STEP_GUIDE, drawers, manual_text
from bot.handlers import BotCore
from pipeline import llm, recall
from pipeline.jobs import JobStore
from pipeline.models import JobKind, JobRecord, JobStatus

ROOT = Path(__file__).resolve().parents[1]


class _Model:
    def __init__(self, answer="Two switches are off [1]."):
        self.calls: list[dict] = []
        self.answer = answer

    def __call__(self, prompt, settings, *, system="", purpose="llm",
                 providers=None):
        self.calls.append({"prompt": prompt, "purpose": purpose})
        text = '["meme", "memes"]' if purpose == "ask-expand" else self.answer
        return llm.LLMResult(text=text, provider=llm.OLLAMA,
                             model="gemma4:12b-it-qat", reason=llm.OK)


def _refuse(*_a, **_k):
    raise AssertionError("the model was called while a render held the card")


def _running(settings, status=JobStatus.RUNNING) -> JobRecord:
    job = JobRecord(id=uuid.uuid4().hex[:10], kind=JobKind.RENDER_LONG,
                    ticker="EXMPL", workdate="2026-10-20", status=status)
    JobStore(settings).save(job)
    return job


def test_the_manual_covers_every_screen_step_and_check():
    from bot.panel_views import STEPS

    assert set(STEP_GUIDE) == {k for k, _ in STEPS}
    tabs = set(re.findall(r'data-tab="([a-z]+)"', (
        ROOT / "bot" / "panel_static" / "index.html").read_text(encoding="utf-8")))
    assert set(SCREENS) == tabs
    gates = (ROOT / "pipeline" / "gates.py").read_text(encoding="utf-8")
    recorded = set(re.findall(r'record\(\s*"([a-z-]+)"', gates))
    recorded |= set(re.findall(r'skipped\(\s*"([a-z-]+)"', gates))
    assert set(CHECKS) == recorded
    text = manual_text()
    assert "Voice room" in text or "voice in the room" in text.lower()


def test_every_drawer_opens(settings):
    core = BotCore(settings)
    for d in drawers(core):
        text = d.build(["meme"])
        assert text and "could not be read" not in text, d.name
    status = next(d for d in drawers(core) if d.always).build([])
    assert "Nothing is rendering or queued." in status
    assert "Voice spend this month" in status and "Switches:" in status


def test_no_secret_reaches_a_drawer(settings):
    s = settings.model_copy(update={"elevenlabs_api_key": "sk-very-secret-1",
                                    "telegram_bot_token": "777:token-value"})
    core = BotCore(s)
    text = next(d for d in drawers(core) if d.name == "settings").build([])
    assert "OLLAMA_MODEL = " in text
    for leak in ("sk-very-secret-1", "777:token-value", "ELEVENLABS_API_KEY",
                 "TELEGRAM_BOT_TOKEN"):
        assert leak not in text


def test_the_question_s_words_open_the_drawers(settings):
    core = BotCore(settings)
    cabinet = drawers(core)

    def opened(question, tickers=frozenset()):
        return [d.name for d in recall.pick_drawers(
            cabinet, recall.terms_of(question), tickers)]

    assert opened("which memes do we have?")[:2] == ["status", "memes"]
    assert "writing:voice_bible" in opened("what does the voice bible say?")
    assert "health" in opened("is anything broken?")
    assert opened("hello") == ["status"]


def test_focus_keeps_what_the_question_is_about():
    text = "\n".join(f"line {i} filler filler filler" for i in range(200))
    text += "\nthe swearing limit is four"
    cut = recall.focus(text, ["swearing"], 300)
    assert "swearing limit" in cut and len(cut) <= 310
    assert cut.startswith("line 0")


def test_the_model_reads_the_drawers_and_cites_them(settings, monkeypatch):
    core = BotCore(settings)
    model = _Model(answer="The library has labelled memes [2].")
    monkeypatch.setattr(llm, "chat_result", model)
    text = core.ask_text(["which", "memes", "do", "we", "have?"])
    prompt = model.calls[-1]["prompt"]
    assert "NOW (the bot as it is this minute):" in prompt
    assert "[1] The bot right now" in prompt and "[2] The meme library" in prompt
    assert "Read: [2] The meme library" in text


def test_a_question_waits_while_a_render_runs(settings, monkeypatch):
    core = BotCore(settings)
    job = _running(settings)
    monkeypatch.setattr(llm, "chat_result", _refuse)
    text = core.ask_text(["which", "memes", "do", "we", "have?"])
    assert text.startswith("⏳ A render is using the graphics card")
    assert "The meme library:" in text           # the drawer, no model needed
    waiting = json.loads((settings.state_dir / core.ASK_WAITING)
                         .read_text(encoding="utf-8"))
    assert [w["q"] for w in waiting] == ["which memes do we have?"]
    assert core.answer_waiting() == []           # still rendering

    def finish(j):
        j.status = JobStatus.DONE

    JobStore(settings).update(job.id, finish)
    model = _Model(answer="Here they are [2].")
    monkeypatch.setattr(llm, "chat_result", model)
    answers = core.answer_waiting()
    assert len(answers) == 1
    assert answers[0].startswith("💬 You asked during the render: “which memes")
    assert "Here they are [2]." in answers[0]
    assert not (settings.state_dir / core.ASK_WAITING).exists()


def test_a_count_still_answers_at_once_during_a_render(settings, monkeypatch):
    core = BotCore(settings)
    _running(settings)
    monkeypatch.setattr(llm, "chat_result", _refuse)
    text = core.ask_text(["how", "many", "shorts", "did", "we", "finish",
                          "this", "month?"])
    assert "counted by the bot's code" in text
    assert not (settings.state_dir / core.ASK_WAITING).exists()


def test_a_waited_answer_reaches_him_in_quiet_mode(settings):
    from bot.commands import NotifyPrefs

    prefs = NotifyPrefs(settings)
    prefs.set("quiet")
    assert prefs.wants("💬 You asked during the render: “x”")
    assert not prefs.wants("🎬 EXMPL: render_long started")
