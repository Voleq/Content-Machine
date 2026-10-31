"""The page's chat with the local AI, with every conversation kept.

His ask (30 Oct 2026): the page's /ask "still doesn't answer, there's
nowhere to find the answer, maybe just make it an llm chat with history".
It was one box holding one answer, kept in memory: a question asked while a
render ran was answered later in Telegram, and a restart lost the lot.

Now a conversation is a file in `state/chats/`, a question is a turn in one,
and a follow-up is read with the turns before it (`recall.ask(history=...)`),
so "and the second one?" means something.

ONE WORKER, ONE QUESTION AT A TIME, in the order they were asked. The model
shares the graphics card with the render, so a second question waits for the
first rather than splitting the card. The page asks (`say`), then looks again
by the conversation's id while the answer is written: `view` carries the
words so far and the step it is on. While a render holds the card the
question waits (his call, 10-23) and is answered once the queue is empty;
`BotCore.job_changed` wakes the worker. A question a restart cut off is
asked again at the next start, so nothing asked is ever lost.

Read-only, as /ask always was: nothing here changes the bot.
"""

from __future__ import annotations

import json
import logging
import re
import secrets
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)

CHAT_DIR = "chats"
_ID_RE = re.compile(r"^[0-9a-f]{12}$")
TITLE_CHARS = 60
QUESTION_MAX_CHARS = 4000
LISTED = 100                # conversations the page's list shows
RENDER_RECHECK_S = 20.0     # how often a waiting question looks at the queue

# What an answer is doing. The first three are still to come.
QUEUED = "queued"           # behind another question
WAITING = "waiting"         # a render holds the graphics card
THINKING = "thinking"       # being answered now
DONE = "done"
FAILED = "failed"
STOPPED = "stopped"
PENDING = (QUEUED, WAITING, THINKING)

# Reset when an answer is asked again.
_ANSWER_KEYS = ("text", "stage", "started", "finished", "seconds", "answered",
                "reason", "model", "provider", "cited", "loose", "read",
                "note", "error")


def _mid() -> str:
    return "m" + secrets.token_hex(5)


def _plain(text) -> str:
    """An answer on one line without its markdown, for the list."""
    text = re.sub(r"[*`]+|^#+\s*|^\s*[-•]\s+", "", str(text or ""), flags=re.M)
    return " ".join(text.split())


def title_of(text: str) -> str:
    """A conversation's name: its first question, cut at a word."""
    t = " ".join(text.split())
    if len(t) <= TITLE_CHARS:
        return t
    cut = t[:TITLE_CHARS].rsplit(" ", 1)[0]
    return (cut or t[:TITLE_CHARS]).rstrip(",;:.") + "…"


class Chats:
    """The conversations on disk, and the thread that answers them."""

    def __init__(self, core):
        self.core = core
        self.settings = core.settings
        self.dir = Path(self.settings.state_dir) / CHAT_DIR
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._live: dict[str, dict] = {}    # the answer being written, by message
        self._stopping: set[str] = set()
        self._order: list[str] = []          # pending answers, first asked first
        self._thread: threading.Thread | None = None
        self._closed = False

    # ------------------------------------------------------------- files
    def _path(self, cid: str) -> Path | None:
        return self.dir / f"{cid}.json" if _ID_RE.match(str(cid or "")) else None

    def _load(self, cid: str) -> dict | None:
        path = self._path(cid)
        if path is None:
            return None
        try:
            chat = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(chat, dict) or not isinstance(chat.get("messages"), list):
            return None
        return chat

    def _save(self, chat: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self.dir / f"{chat['id']}.json"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(chat, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        tmp.replace(path)

    def _all(self) -> list[dict]:
        if not self.dir.is_dir():
            return []
        out = []
        for path in self.dir.glob("*.json"):
            chat = self._load(path.stem)
            if chat is not None:
                out.append(chat)
        return out

    @staticmethod
    def _find(chat: dict, mid: str) -> dict | None:
        return next((m for m in chat["messages"] if m.get("id") == mid), None)

    # ---------------------------------------------------- what the page reads
    def list(self) -> list[dict]:
        """The conversations, the newest first, as the page's list shows
        them: a question still being answered, and an answer not yet seen."""
        with self._lock:
            chats = self._all()
        rows = []
        for chat in chats:
            msgs = chat["messages"]
            pending = next((m for m in msgs if m.get("status") in PENDING), None)
            answered = [m.get("finished") or 0 for m in msgs
                        if m.get("role") == "assistant" and m.get("finished")]
            last = next((m for m in reversed(msgs)
                         if m.get("text") and m.get("status") not in PENDING), None)
            rows.append({
                "id": chat["id"], "title": chat.get("title") or "A conversation",
                "updated": chat.get("updated") or chat.get("created") or 0,
                "questions": sum(1 for m in msgs if m.get("role") == "user"),
                "pending": pending.get("status") if pending else None,
                "unread": bool(answered) and max(answered) > (chat.get("seen") or 0),
                "last": _plain((last or {}).get("text", ""))[:90],
            })
        rows.sort(key=lambda r: r["updated"], reverse=True)
        return rows[:LISTED]

    def view(self, cid: str, *, seen: bool = True) -> dict | None:
        """One conversation, with the answer being written as far as it has
        got. `seen`: the page is showing it, so its answers are read."""
        now = time.time()
        with self._lock:
            chat = self._load(cid)
            if chat is None:
                return None
            done_at = max((m.get("finished") or 0 for m in chat["messages"]
                           if m.get("role") == "assistant"), default=0)
            if seen and done_at and (chat.get("seen") or 0) < done_at:
                chat["seen"] = now
                self._save(chat)
            order = list(self._order)
            msgs = []
            for m in chat["messages"]:
                m = dict(m)
                if m.get("status") in PENDING:
                    live = dict(self._live.get(m["id"]) or {})
                    m["text"] = live.get("text", m.get("text") or "")
                    m["stage"] = live.get("stage") or m.get("stage") or ""
                    m["thinking"] = bool(live.get("thinking"))
                    m["seconds"] = round(now - (m.get("started") or m.get("at") or now))
                    if m["status"] == QUEUED and m["id"] in order:
                        m["ahead"] = order.index(m["id"])
                msgs.append(m)
        return dict(chat, messages=msgs)

    # ------------------------------------------------- what the page does
    def say(self, cid: str | None, text: str) -> dict:
        """Ask `text`, in conversation `cid` or a new one. Answers at once;
        the answer follows (`view`)."""
        text = str(text or "").strip()
        if not text:
            raise ValueError("write a question first")
        if len(text) > QUESTION_MAX_CHARS:
            raise ValueError(f"a question can be {QUESTION_MAX_CHARS:,} "
                             f"characters at most")
        now = time.time()
        with self._lock:
            chat = self._load(cid) if cid else None
            if cid and chat is None:
                raise LookupError("no such conversation")
            if chat is None:
                chat = {"id": secrets.token_hex(6), "title": title_of(text),
                        "created": now, "updated": now, "seen": 0,
                        "messages": []}
            chat["messages"] += [
                {"id": _mid(), "role": "user", "text": text, "at": now},
                {"id": _mid(), "role": "assistant", "status": QUEUED,
                 "text": "", "stage": "", "at": now}]
            chat["updated"] = now
            self._save(chat)
        self.wake()
        return self.view(chat["id"], seen=False)

    def stop(self, cid: str, mid: str) -> dict:
        """Stop an answer: one being written ends where it has got to, one
        still waiting is dropped."""
        with self._lock:
            chat = self._need(cid)
            m = self._find(chat, mid)
            if m is not None and m.get("status") == THINKING:
                self._stopping.add(mid)
            elif m is not None and m.get("status") in PENDING:
                m.update(status=STOPPED, finished=time.time(), stage="")
                self._save(chat)
        self.wake()
        return self.view(cid)

    def retry(self, cid: str, mid: str) -> dict:
        """Ask an answered (or stopped, or failed) question again."""
        with self._lock:
            chat = self._need(cid)
            m = self._find(chat, mid)
            if m is None or m.get("role") != "assistant":
                raise LookupError("no such answer")
            if m.get("status") not in PENDING:
                for k in _ANSWER_KEYS:
                    m.pop(k, None)
                now = time.time()
                m.update(status=QUEUED, text="", stage="", at=now)
                chat["updated"] = now
                self._save(chat)
        self.wake()
        return self.view(cid)

    def rename(self, cid: str, title: str) -> dict:
        title = " ".join(str(title or "").split())[:120]
        if not title:
            raise ValueError("give it a name")
        with self._lock:
            chat = self._need(cid)
            chat["title"] = title
            self._save(chat)
        return self.view(cid, seen=False)

    def delete(self, cid: str) -> None:
        with self._lock:
            chat = self._need(cid)
            for m in chat["messages"]:
                if m.get("status") == THINKING:
                    self._stopping.add(m["id"])
            self._path(cid).unlink(missing_ok=True)
        self.wake()

    def _need(self, cid: str) -> dict:
        chat = self._load(cid)
        if chat is None:
            raise LookupError("no such conversation")
        return chat

    # ------------------------------------------------------------ the worker
    def start(self) -> None:
        """Start answering; a question a restart cut off is asked again."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            for chat in self._all():
                cut = [m for m in chat["messages"] if m.get("status") == THINKING]
                for m in cut:
                    m.update(status=QUEUED, text="", started=None,
                             stage="Asked again: the bot restarted while it answered")
                if cut:
                    self._save(chat)
            self._closed = False
            self._thread = threading.Thread(target=self._run, name="chat",
                                            daemon=True)
            self._thread.start()

    def close(self) -> None:
        self._closed = True
        self._wake.set()

    def wake(self) -> None:
        self._wake.set()

    def _run(self) -> None:
        while not self._closed:
            self._wake.clear()
            try:
                delay = self._step()
            except Exception:                           # noqa: BLE001
                log.exception("chat: the worker stumbled; it carries on")
                delay = 30.0
            if delay == 0:
                continue
            self._wake.wait(delay)

    def _pending(self) -> list[tuple[float, str, str, str]]:
        """Every answer still to come, first asked first."""
        rows = []
        with self._lock:
            for chat in self._all():
                for m in chat["messages"]:
                    if m.get("status") in PENDING:
                        rows.append((m.get("at") or 0, chat["id"], m["id"],
                                     m["status"]))
        rows.sort()
        return rows

    def _step(self) -> float | None:
        """Answer the oldest question. 0: look again at once; None: nothing
        to do until woken; seconds: a render holds the card, look again."""
        queue = self._pending()
        self._order = [mid for _at, _cid, mid, _st in queue]
        if not queue:
            return None
        if self.core.render_busy():
            for _at, cid, mid, status in queue:
                if status != WAITING:
                    self._park(cid, mid)
            return RENDER_RECHECK_S
        _at, cid, mid, _st = queue[0]
        self._answer(cid, mid)
        return 0

    def _question(self, chat: dict, mid: str) -> tuple[str, list]:
        """The question an answer is for, and the conversation before it as
        (question, answer) pairs: only the answers that came."""
        msgs = chat["messages"]
        i = next(n for n, m in enumerate(msgs) if m.get("id") == mid)
        question = msgs[i - 1]["text"] if i and msgs[i - 1].get("role") == "user" else ""
        history, asked = [], None
        for m in msgs[:max(i - 1, 0)]:
            if m.get("role") == "user":
                asked = m.get("text") or ""
            elif asked and m.get("status") == DONE and m.get("text") \
                    and m.get("answered") != "none":
                history.append((asked, m["text"]))
                asked = None
        return question, history

    def _park(self, cid: str, mid: str) -> None:
        """A render holds the card: the question waits, and meanwhile says
        what the search and the bot's state found, as /ask always did."""
        from bot.bot_facts import drawers
        from pipeline.recall import ask

        with self._lock:
            chat = self._load(cid)
            m = chat and self._find(chat, mid)
            if not m or m.get("status") not in (QUEUED, WAITING):
                return
            question, _history = self._question(chat, mid)
            m.update(status=WAITING, stage="Waiting for the render to finish: "
                     "it is using the graphics card")
            self._save(chat)
        try:
            note = ask(self.settings, question, drawers=drawers(self.core),
                       wait=True).text
        except Exception as e:                          # noqa: BLE001
            log.warning("chat: what is on file could not be read: %s", e)
            return
        with self._lock:
            chat = self._load(cid)
            m = chat and self._find(chat, mid)
            if m and m.get("status") == WAITING:
                m["note"] = note
                self._save(chat)

    def _answer(self, cid: str, mid: str) -> None:
        from bot.bot_facts import drawers
        from pipeline import llm
        from pipeline.recall import ask

        started = time.time()
        with self._lock:
            chat = self._load(cid)
            m = chat and self._find(chat, mid)
            if not m or m.get("status") not in PENDING:
                return
            question, history = self._question(chat, mid)
            m.update(status=THINKING, started=started, text="",
                     stage="Starting")
            m.pop("note", None)           # what was on file while it waited
            self._save(chat)
            live = self._live[mid] = {"text": "", "stage": "Starting",
                                      "thinking": False}

        def on_stage(words: str) -> None:
            if mid in self._stopping:
                raise llm.Stop()
            live["stage"] = words

        def on_text(text: str, thinking: bool) -> None:
            if mid in self._stopping:
                raise llm.Stop()
            live["text"], live["thinking"] = text, thinking
            if thinking:
                live["stage"] = "Thinking it over before it writes (the local AI)"
            elif text and not live.get("writing"):
                live["writing"] = True
                live["stage"] = "Writing the answer (the local AI)"

        result: dict
        try:
            if not question:
                raise ValueError("this answer has no question before it")
            answer = ask(self.settings, question, drawers=drawers(self.core),
                         history=history, on_text=on_text, on_stage=on_stage)
            if answer.by_code:
                answered = "code"
            elif answer.body:
                answered = "model"
            else:
                answered = "none"
            result = {"status": DONE, "text": answer.body or answer.text,
                      "answered": answered, "reason": answer.reason,
                      "model": answer.model, "provider": answer.provider,
                      "cited": answer.cited, "loose": answer.loose,
                      "read": len(answer.hits)}
        except llm.Stop:
            result = {"status": STOPPED, "text": live.get("text", "")}
        except Exception as e:                          # noqa: BLE001
            log.exception("chat: a question failed")
            result = {"status": FAILED, "text": "", "error": f"{type(e).__name__}: {e}"}
        finally:
            self._stopping.discard(mid)
            self._live.pop(mid, None)
        now = time.time()
        with self._lock:
            chat = self._load(cid)
            m = chat and self._find(chat, mid)
            if not m:
                return                    # deleted while it was answered
            m.update(result, stage="", finished=now,
                     seconds=round(now - started))
            chat["updated"] = now
            self._save(chat)
