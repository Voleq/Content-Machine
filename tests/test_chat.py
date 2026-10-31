"""The page's chat with the local AI (his 30 Oct 2026 ask: "make it an llm
chat with history"): the answer streamed from Ollama with the conversation
before it, a follow-up read with that conversation, every conversation kept
on disk and answered on the bot one question at a time, waiting while a
render holds the graphics card, and asked again after a restart."""

from __future__ import annotations

import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from bot import chat as chat_mod
from bot.chat import Chats, title_of
from bot.handlers import BotCore
from pipeline import llm, recall
from pipeline.jobs import JobStore
from pipeline.models import JobKind, JobRecord, JobStatus


# ------------------------------------------------- a stand-in Ollama daemon

@pytest.fixture()
def ollama(monkeypatch):
    """An HTTP server that answers /api/chat the way Ollama does: one JSON
    line per piece when streaming. `said` holds what it was sent."""
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy",
                 "https_proxy", "all_proxy"):
        monkeypatch.delenv(name, raising=False)
    state = {"said": [], "pieces": ["Two ", "switches ", "are off [1]."],
             "status": 200, "error": "", "thinking": False}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_a):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["said"].append(body)
            if state["status"] != 200:
                out = json.dumps({"error": state["error"]}).encode()
                self.send_response(state["status"])
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)
                return
            if not body.get("stream"):
                out = json.dumps({"message": {"content": "".join(state["pieces"])},
                                  "done": True}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.end_headers()
            lines = []
            if state["thinking"]:
                lines.append({"message": {"content": "", "thinking": "hmm"}, "done": False})
            lines += [{"message": {"content": p}, "done": False} for p in state["pieces"]]
            if state["error"]:
                lines.append({"error": state["error"]})
            lines.append({"message": {"content": ""}, "done": True})
            for line in lines:
                self.wfile.write(json.dumps(line).encode() + b"\n")
                self.wfile.flush()
                time.sleep(0.02)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    state["url"] = f"http://127.0.0.1:{server.server_address[1]}"
    yield state
    server.shutdown()


def _live(settings, url):
    return settings.model_copy(update={"mock_mode": False, "ollama_base_url": url})


def test_the_answer_streams_with_the_conversation_before_it(settings, ollama):
    s = _live(settings, ollama["url"])
    seen = []
    history = [{"role": "user", "content": "what is off?"},
               {"role": "assistant", "content": "The voice room [1]."}]
    out = llm.chat_result("and the rest?", s, system="be brief", purpose="ask",
                          providers=["ollama"], history=history,
                          on_text=lambda text, thinking: seen.append(text))
    assert out.text == "Two switches are off [1]." and out.reason == llm.OK
    assert seen == ["Two ", "Two switches ", "Two switches are off [1]."]
    sent = ollama["said"][0]
    assert sent["stream"] is True
    assert [m["role"] for m in sent["messages"]] == ["system", "user", "assistant", "user"]
    assert sent["messages"][-1]["content"] == "and the rest?"
    assert sent["options"]["num_ctx"] == s.ollama_num_ctx


def test_without_a_callback_the_call_is_the_plain_one(settings, ollama):
    out = llm.chat_result("hi", _live(settings, ollama["url"]), purpose="ask",
                          providers=["ollama"])
    assert out.text == "Two switches are off [1]."
    assert ollama["said"][0]["stream"] is False
    assert len(ollama["said"][0]["messages"]) == 1      # no system, no history


def test_a_thinking_model_says_so_before_its_first_word(settings, ollama):
    ollama["thinking"] = True
    seen = []
    llm.chat_result("hi", _live(settings, ollama["url"]), purpose="ask",
                    providers=["ollama"], on_text=lambda t, th: seen.append((t, th)))
    assert seen[0] == ("", True) and seen[-1] == ("Two switches are off [1].", False)


def test_stop_ends_a_streamed_answer(settings, ollama):
    def on_text(text, _thinking):
        if text.startswith("Two switches"):
            raise llm.Stop()

    with pytest.raises(llm.Stop):
        llm.chat_result("hi", _live(settings, ollama["url"]), purpose="ask",
                        providers=["ollama"], on_text=on_text)


@pytest.mark.parametrize("stream", [False, True])
def test_what_ollama_said_when_it_refused_is_kept(settings, ollama, stream):
    """'model not found' read as "is Ollama running?" before (30 Oct 2026)."""
    ollama.update(status=404, error="model 'gemma4:12b-it-qat' not found")
    out = llm.chat_result("hi", _live(settings, ollama["url"]), purpose="ask",
                          providers=["ollama"],
                          on_text=(lambda *_a: None) if stream else None)
    assert out.reason == llm.MODEL_ERROR and "not found" in out.detail


def test_an_error_in_the_middle_of_a_stream_is_kept(settings, ollama):
    ollama["error"] = "out of memory"
    out = llm.chat_result("hi", _live(settings, ollama["url"]), purpose="ask",
                          providers=["ollama"], on_text=lambda *_a: None)
    assert out.reason == llm.MODEL_ERROR and out.detail == "out of memory"


def test_nothing_listening_is_still_no_daemon(settings):
    out = llm.chat_result("hi", _live(settings, "http://127.0.0.1:9"),
                          purpose="ask", providers=["ollama"],
                          on_text=lambda *_a: None)
    assert out.reason == llm.NO_DAEMON


# ------------------------------------------------------- a follow-up question

def _workspace(settings, ticker="EXMPL", workdate="2026-09-12",
               narration="Gross margin fell for the third quarter running."):
    d = settings.workspace_dir / ticker / workdate
    d.mkdir(parents=True, exist_ok=True)
    (d / "script_long.json").write_text(json.dumps(
        {"title": f"{ticker} deep dive", "narration": narration}), encoding="utf-8")
    (d / "lane.json").write_text(json.dumps({"lane": "long"}), encoding="utf-8")
    return d


class _Model:
    """Stands in for `llm.chat_result`, history and streaming included."""

    def __init__(self, answer="Revenue grew [1]."):
        self.calls: list[dict] = []
        self.answer = answer

    def __call__(self, prompt, settings, *, system="", purpose="llm",
                 providers=None, history=(), on_text=None):
        self.calls.append({"prompt": prompt, "system": system, "purpose": purpose,
                           "history": list(history), "streamed": on_text is not None})
        if purpose == "ask-expand":
            return llm.LLMResult(text='["revenue", "sales"]', provider=llm.OLLAMA,
                                 model="gemma4:12b-it-qat", reason=llm.OK)
        if on_text is not None:
            on_text(self.answer[:5], False)
            on_text(self.answer, False)
        return llm.LLMResult(text=self.answer, provider=llm.OLLAMA,
                             model="gemma4:12b-it-qat", reason=llm.OK)


def test_a_follow_up_is_read_with_the_conversation(settings, monkeypatch):
    _workspace(settings, narration="Revenue grew eleven percent on new orders.")
    _workspace(settings, "OTHER", narration="Revenue fell at the other one.")
    model = _Model()
    monkeypatch.setattr(llm, "chat_result", model)
    stages, streamed = [], []
    answer = recall.ask(
        settings, "and the revenue?",
        history=[("what did we say about EXMPL margins?",
                  "Margins fell [1].\n\nRead: [1] script · EXMPL\n— answered locally, gemma")],
        on_stage=stages.append, on_text=lambda t, _th: streamed.append(t))
    expand, main = model.calls
    # the rewording sees what "the revenue" points back to
    assert "Q: what did we say about EXMPL margins?" in expand["prompt"]
    # the earlier turn goes as turns, without the bot's lines under it
    assert main["history"] == [
        {"role": "user", "content": "what did we say about EXMPL margins?"},
        {"role": "assistant", "content": "Margins fell [1]."}]
    assert main["streamed"] and streamed[-1] == "Revenue grew [1]."
    assert "This is a conversation on the bot's web page" in main["system"]
    # the ticker asked of last is the one read about
    assert "eleven percent" in main["prompt"]
    assert answer.body == "Revenue grew [1]." and answer.cited[0]["n"] == 1
    assert "Read: [1]" in answer.text
    assert stages[0] == "Searching the bot's records"
    assert any(s.startswith("Reading ") for s in stages)


def test_telegram_s_ask_is_unchanged(settings, monkeypatch):
    _workspace(settings)
    model = _Model()
    monkeypatch.setattr(llm, "chat_result", model)
    recall.ask(settings, "what about EXMPL?")
    main = model.calls[1]
    assert main["history"] == [] and not main["streamed"]
    assert "It is read in Telegram" in main["system"]


def test_a_long_conversation_keeps_its_newest_turns(settings, monkeypatch):
    _workspace(settings)
    model = _Model()
    monkeypatch.setattr(llm, "chat_result", model)
    history = [(f"question {n}", "word " * 900) for n in range(20)]
    recall.ask(settings, "what about EXMPL?", history=history)
    turns = model.calls[1]["history"]
    assert 2 <= len(turns) < 40 and turns[-2]["content"] == "question 19"
    assert sum(len(t["content"]) for t in turns) <= recall._HISTORY_MAX_CHARS


# --------------------------------------------------- the conversations kept

def _answers(monkeypatch, text="The memes are fine [1]."):
    """`recall.ask` stood in: records what it was asked, answers `text`."""
    asked = []

    def fake(settings, question, *, drawers=(), history=(), on_text=None,
             on_stage=None, wait=False, **_kw):
        asked.append({"question": question, "history": list(history), "wait": wait})
        if wait:
            return recall.Answer("⏳ A render is using the graphics card…",
                                 reason="waiting")
        if on_stage:
            on_stage("Reading 3 records and writing the answer (the local AI)")
        if on_text:
            on_text(text[:4], False)
        return recall.Answer(text + "\n— answered locally, gemma", provider="ollama",
                             model="gemma4:12b-it-qat", reason="ok", body=text,
                             cited=[{"n": 1, "title": "the meme library", "about": "",
                                     "where": "Library"}],
                             hits=[object(), object(), object()])

    monkeypatch.setattr(recall, "ask", fake)
    return asked


def _settled(chats, cid, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        c = chats.view(cid, seen=False)
        if c and not any(m.get("status") in chat_mod.PENDING for m in c["messages"]):
            return c
        time.sleep(0.02)
    raise AssertionError(f"never answered: {chats.view(cid, seen=False)}")


@pytest.fixture()
def chats(settings):
    core = BotCore(settings)
    c = core.chats
    yield c
    c.close()


def test_a_question_is_kept_and_answered(chats, monkeypatch):
    asked = _answers(monkeypatch)
    chats.start()
    c = chats.say(None, "  which memes do we have?  ")
    assert c["title"] == "which memes do we have?"
    assert [m["role"] for m in c["messages"]] == ["user", "assistant"]
    assert c["messages"][1]["status"] in chat_mod.PENDING
    done = _settled(chats, c["id"])
    a = done["messages"][1]
    assert a["status"] == "done" and a["answered"] == "model"
    assert a["text"] == "The memes are fine [1]." and a["read"] == 3
    assert a["cited"][0]["where"] == "Library" and a["model"] == "gemma4:12b-it-qat"
    assert asked[0]["question"] == "which memes do we have?" and asked[0]["history"] == []
    # on disk, so a restart keeps it
    on_disk = json.loads((chats.dir / f"{c['id']}.json").read_text(encoding="utf-8"))
    assert on_disk["messages"][1]["text"] == "The memes are fine [1]."
    # the list says there is an answer he has not seen, until he opens it
    row = chats.list()[0]
    assert row["unread"] and row["questions"] == 1 and row["pending"] is None
    chats.view(c["id"])
    assert not chats.list()[0]["unread"]


def test_a_follow_up_carries_the_answers_before_it(chats, monkeypatch):
    asked = _answers(monkeypatch)
    chats.start()
    c = chats.say(None, "which memes do we have?")
    _settled(chats, c["id"])
    chats.say(c["id"], "and which are used least?")
    done = _settled(chats, c["id"])
    assert len(done["messages"]) == 4
    assert asked[1]["history"] == [("which memes do we have?", "The memes are fine [1].")]


def test_an_answer_that_never_came_is_not_history(chats, monkeypatch):
    asked = _answers(monkeypatch)
    chats.start()
    c = chats.say(None, "first")
    _settled(chats, c["id"])
    path = chats.dir / f"{c['id']}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["messages"][1]["answered"] = "none"          # the model was down
    path.write_text(json.dumps(data), encoding="utf-8")
    chats.say(c["id"], "second")
    _settled(chats, c["id"])
    assert asked[1]["history"] == []


def test_questions_are_answered_one_at_a_time_in_order(chats, monkeypatch):
    gate = threading.Event()
    order = []

    def slow(settings, question, **kw):
        order.append(question)
        if question == "first":
            gate.wait(5)
        return recall.Answer(question.upper(), body=question.upper(), reason="ok")

    monkeypatch.setattr(recall, "ask", slow)
    chats.start()
    a = chats.say(None, "first")
    b = chats.say(None, "second")
    time.sleep(0.2)
    waiting = chats.view(b["id"])["messages"][1]
    assert waiting["status"] == "queued" and waiting["ahead"] == 1
    assert order == ["first"]
    gate.set()
    assert _settled(chats, b["id"])["messages"][1]["text"] == "SECOND"
    assert order == ["first", "second"] and _settled(chats, a["id"])


def test_the_words_so_far_show_while_it_writes(chats, monkeypatch):
    gate = threading.Event()

    def writing(settings, question, *, on_text=None, on_stage=None, **kw):
        on_stage("Writing the answer (the local AI)")
        on_text("The memes", False)
        gate.wait(5)
        return recall.Answer("The memes are fine.", body="The memes are fine.",
                             reason="ok")

    monkeypatch.setattr(recall, "ask", writing)
    chats.start()
    c = chats.say(None, "which memes?")
    for _ in range(200):
        m = chats.view(c["id"])["messages"][1]
        if m.get("text"):
            break
        time.sleep(0.02)
    assert m["status"] == "thinking" and m["text"] == "The memes"
    assert m["stage"] == "Writing the answer (the local AI)" and m["seconds"] >= 0
    assert chats.list()[0]["pending"] == "thinking"
    gate.set()
    assert _settled(chats, c["id"])["messages"][1]["text"] == "The memes are fine."


def _render(settings, status=JobStatus.RUNNING) -> JobRecord:
    job = JobRecord(id=uuid.uuid4().hex[:10], kind=JobKind.RENDER_LONG,
                    ticker="EXMPL", workdate="2026-10-20", status=status)
    JobStore(settings).save(job)
    return job


def test_a_question_waits_while_a_render_holds_the_card(chats, monkeypatch):
    """His call (10-23): the model waits for the render. The answer still
    lands in the conversation when it is done, not in Telegram."""
    asked = _answers(monkeypatch)
    job = _render(chats.settings)
    monkeypatch.setattr(chat_mod, "RENDER_RECHECK_S", 0.1)
    chats.start()
    c = chats.say(None, "which memes?")
    for _ in range(200):
        m = chats.view(c["id"])["messages"][1]
        if m["status"] == "waiting" and m.get("note"):
            break
        time.sleep(0.02)
    assert m["status"] == "waiting" and "render" in m["stage"]
    assert m["note"].startswith("⏳") and asked[0]["wait"] is True
    job.status = JobStatus.DONE
    JobStore(chats.settings).save(job)
    chats.core.job_changed(job)
    done = _settled(chats, c["id"])["messages"][1]
    assert done["status"] == "done" and "note" not in done
    assert [a["wait"] for a in asked] == [True, False]


def test_a_question_a_restart_cut_off_is_asked_again(settings, monkeypatch):
    asked = _answers(monkeypatch)
    first = BotCore(settings).chats            # no worker: as if it died
    c = first.say(None, "which memes?")
    path = first.dir / f"{c['id']}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["messages"][1].update(status="thinking", started=time.time())
    path.write_text(json.dumps(data), encoding="utf-8")
    again = BotCore(settings).chats            # the bot started again
    again.start()
    try:
        assert _settled(again, c["id"])["messages"][1]["status"] == "done"
        assert len(asked) == 1
    finally:
        again.close()


def test_stop_drops_a_waiting_question_and_ends_a_written_one(chats, monkeypatch):
    started = threading.Event()

    def endless(settings, question, *, on_text=None, **kw):
        n = 0
        while True:
            n += 1
            on_text("word " * n, False)    # raises llm.Stop once stopped
            started.set()
            time.sleep(0.01)

    monkeypatch.setattr(recall, "ask", endless)
    chats.start()
    a = chats.say(None, "first")
    b = chats.say(None, "second")
    assert started.wait(5)
    chats.stop(b["id"], b["messages"][1]["id"])
    assert chats.view(b["id"])["messages"][1]["status"] == "stopped"
    chats.stop(a["id"], a["messages"][1]["id"])
    m = _settled(chats, a["id"])["messages"][1]
    assert m["status"] == "stopped" and m["text"].startswith("word")


def test_ask_again_answers_it_fresh(chats, monkeypatch):
    asked = _answers(monkeypatch)
    chats.start()
    c = chats.say(None, "which memes?")
    first = _settled(chats, c["id"])["messages"][1]
    chats.retry(c["id"], first["id"])
    again = _settled(chats, c["id"])["messages"][1]
    assert again["status"] == "done" and again["id"] == first["id"]
    assert len(asked) == 2


def test_a_failure_is_said_not_swallowed(chats, monkeypatch):
    def broken(*_a, **_k):
        raise RuntimeError("the index is locked")

    monkeypatch.setattr(recall, "ask", broken)
    chats.start()
    c = chats.say(None, "which memes?")
    m = _settled(chats, c["id"])["messages"][1]
    assert m["status"] == "failed" and "the index is locked" in m["error"]


def test_rename_delete_and_what_is_refused(chats, monkeypatch):
    _answers(monkeypatch)
    c = chats.say(None, "which memes?")
    assert chats.rename(c["id"], "  Memes   check ")["title"] == "Memes check"
    with pytest.raises(ValueError):
        chats.rename(c["id"], "   ")
    with pytest.raises(ValueError):
        chats.say(None, "   ")
    with pytest.raises(ValueError):
        chats.say(None, "x" * (chat_mod.QUESTION_MAX_CHARS + 1))
    with pytest.raises(LookupError):
        chats.say("0123456789ab", "hello")
    # an id is twelve hex characters, never a path
    for bad in ("../../state/panel_token", "..", "", "ABCDEF012345"):
        assert chats.view(bad) is None
        with pytest.raises(LookupError):
            chats.delete(bad)
    chats.delete(c["id"])
    assert chats.view(c["id"]) is None and chats.list() == []


def test_a_title_is_the_first_question_cut_at_a_word():
    assert title_of("why did the BA short fail?") == "why did the BA short fail?"
    long = title_of("why did the last render of the Boeing short fail at the "
                    "frames step, and what do I do about it")
    assert long.endswith("…") and len(long) <= chat_mod.TITLE_CHARS + 1
    assert " " not in long[-2:]
