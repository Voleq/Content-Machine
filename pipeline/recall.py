"""A search engine over everything the bot has saved, and `/ask` on top of it.

The local model does not remember anything between calls, and it does not
need to. Dennis already writes down nearly everything it does: every script
in its workspace, every filing brief, every check report, the theses, the
idea backlog, the job records, the video log, and now the journal. What was
missing was a way to find the right few of those and hand them to the model
when a question comes in. That is this module.

**The index.** One SQLite full-text table (`state/recall.sqlite`), built by
reading the records where they already live. It is a cache, never a source of
truth: it is rebuilt whenever any file it reads has changed since the last
build, so it cannot go stale and deleting it costs one rebuild. Plain keyword
search, stemmed (``margins`` finds ``margin``), and it works with the model
switched off. That is `/find`.

**Search by meaning, on the model already installed.** A keyword search for
"the one where we said margins were cracking" misses a script that said
"gross profit is shrinking". Rather than a second, embedding-only model, the
local model rewrites the question into the words the records would use —
synonyms, the finance vocabulary, the likely metric names — and both searches
run. Their rankings are merged by reciprocal rank, so a record either search
ranks highly comes through.

**The answer.** `/ask` gives the model the best few records, the headline
figures from :mod:`pipeline.tally`, and a description of the bot built from
the code (:func:`self_description`). It is told to answer only from those,
to cite them, and to say "I don't have that on file" when they do not
contain the answer. Two things are enforced in code rather than hoped for:

* a question that is plainly a count or a total is answered by
  :mod:`pipeline.tally` and never reaches the model, and
* any number in the model's answer that appears in none of what it was given
  is named underneath the answer as unsupported.

**Local only by default.** `ASK_PROVIDER_ORDER` is `ollama`, so a question
typed in passing never becomes hosted spend. With the model absent, `/ask`
says why and shows what the search found.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import threading
from contextlib import closing
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from config import Settings
from pipeline import journal

log = logging.getLogger(__name__)

INDEX_FILE = "recall.sqlite"
README = Path(__file__).resolve().parents[1] / "README.md"

# Bumped whenever what the collectors read changes, so an index built by an
# older version of this file is rebuilt rather than trusted.
_VERSION = "1"

KIND_LABELS: dict[str, str] = {
    "video": "video",
    "script": "script",
    "brief": "filing brief",
    "report": "check report",
    "thesis": "thesis",
    "idea": "idea",
    "confession": "confession",
    "job": "job",
    "upload": "YouTube upload",
    "journal": "journal",
    "command": "command",
    "pass": "AI pass",
    "docs": "README",
}

# Words that carry no meaning for a search. The question words matter most:
# "what did we say about margins" is a search for "margins".
_STOPWORDS = frozenset("""
a about above after again all also am an and any are as at be because been
before being below between both but by can could did do does doing done
during each even ever for from further get got had has have having he her
here hers him his how i if in into is it its itself just let like me more
most my no nor not now of off on once only or other our ours out over own
please same she should show so some such tell than that the their them then
there these they this those through to too under until up us very was we
were what when where which while who whom why will with would you your
yours dennis bot
""".split())

_WORD_RE = re.compile(r"[A-Za-z0-9$][A-Za-z0-9$%.'&-]*")


# ---------------------------------------------------------------- documents

@dataclass
class Doc:
    kind: str
    title: str
    body: str
    ticker: str = ""
    workdate: str = ""
    place: str = ""             # where it lives, in words the operator can use


@dataclass
class Hit(Doc):
    snippet: str = ""
    score: float = 0.0

    def label(self) -> str:
        parts = [KIND_LABELS.get(self.kind, self.kind)]
        if self.ticker:
            parts.append(self.ticker)
        if self.workdate:
            parts.append(self.workdate)
        return " · ".join(parts)


def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


_DATE_DIR = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _workspace_dirs(settings: Settings) -> list[Path]:
    base = settings.workspace_dir
    if not base.is_dir():
        return []
    out = []
    for ticker_dir in sorted(p for p in base.iterdir() if p.is_dir()):
        out.extend(sorted(p for p in ticker_dir.iterdir()
                          if p.is_dir() and _DATE_DIR.match(p.name)))
    return out


# The workspace files the index reads, and nothing else: renders, clips and
# manifests are large and carry nothing a question is about.
_WS_FILES = ("script_short.json", "script_long.json", "filing_brief.json",
             "report_short.txt", "report_long.txt", "lane.json",
             "long_angle.json", "headline.json", "why.txt",
             "approval_short.json", "approval_long.json")


def _workspace_docs(settings: Settings, d: Path) -> list[Doc]:
    ticker, workdate = d.parent.name, d.name
    place = f"workspace {ticker}/{workdate}"
    docs: list[Doc] = []
    for fmt in ("short", "long"):
        payload = _load_json(d / f"script_{fmt}.json", None)
        if isinstance(payload, dict):
            narration = str(payload.get("narration")
                            or payload.get("audio_script") or "")
            title = str(payload.get("title") or "").strip()
            if narration.strip():
                first = narration.strip().split("\n")[0][:90]
                docs.append(Doc("script", f"{fmt.upper()} script: "
                                f"{title or first}", narration, ticker,
                                workdate, f"{place}, script_{fmt}.json"))
        report = _text(d / f"report_{fmt}.txt")
        if report.strip():
            docs.append(Doc("report", f"{fmt.upper()} check report", report,
                            ticker, workdate, f"{place}, report_{fmt}.txt"))
    brief = _load_json(d / "filing_brief.json", None)
    if isinstance(brief, dict) and brief.get("body"):
        body = "\n\n".join(str(brief.get(k) or "") for k in
                           ("body", "contradictions", "grading")).strip()
        docs.append(Doc("brief", f"filing brief: {brief.get('filings') or ''}",
                        body, ticker, workdate, f"{place}, filing_brief.json"))
    lines = []
    lane = _load_json(d / "lane.json", {})
    if isinstance(lane, dict) and lane.get("lane"):
        lines.append(f"lane: {lane.get('lane')}"
                     + (" (update)" if lane.get("update") else ""))
    angle = _load_json(d / "long_angle.json", {})
    if isinstance(angle, dict) and angle.get("chosen"):
        lines.append(f"angle chosen: {angle['chosen']}")
    headline = _load_json(d / "headline.json", {})
    if isinstance(headline, dict) and headline:
        text = headline.get("headline") or headline.get("text") or ""
        if text:
            lines.append(f"headline: {text}")
        if headline.get("summary"):
            lines.append(f"the article: {headline['summary']}")
    why = _text(d / "why.txt").strip()
    if why:
        lines.append(f"why it is worth making: {why}")
    approved = [fmt for fmt in ("short", "long")
                if (d / f"approval_{fmt}.json").exists()]
    if approved:
        lines.append("approved: " + ", ".join(approved))
    if lines:
        docs.append(Doc("video", f"{ticker} video of {workdate}",
                        "\n".join(lines), ticker, workdate, place))
    return docs


def _state_docs(settings: Settings) -> list[Doc]:
    state = settings.state_dir
    docs: list[Doc] = []

    theses = _load_json(state / "theses.json", {})
    for ticker, t in (theses.items() if isinstance(theses, dict) else ()):
        if not isinstance(t, dict):
            continue
        lines = [f"what we said: {t.get('summary') or ''}",
                 f"status: {t.get('status') or 'intact'}"
                 + (f", checked {t['checked_at'][:10]}" if t.get("checked_at")
                    else "")]
        if t.get("hook"):
            lines.append(f"opened on: {t['hook']}")
        for claim in t.get("claims") or []:
            lines.append(f"claimed: {claim}")
        if t.get("conclusion"):
            lines.append(f"concluded: {t['conclusion']}")
        for move in t.get("last_moves") or []:
            if isinstance(move, dict):
                lines.append(f"moved: {move.get('metric')} "
                             f"{move.get('before')} -> {move.get('after')}")
        docs.append(Doc("thesis", f"thesis on {ticker}: {t.get('status')}",
                        "\n".join(lines), ticker, str(t.get("workdate") or ""),
                        f"/thesis {ticker}"))

    for idea in _load_json(state / "idea_queue.json", []) or []:
        if isinstance(idea, dict) and idea.get("ticker"):
            docs.append(Doc(
                "idea", f"idea: {str(idea.get('reason') or '')[:80]}",
                f"{idea.get('reason') or ''}\nsource: {idea.get('source')}"
                f"{' · lane ' + idea['lane'] if idea.get('lane') else ''}"
                f"{' · seen' if idea.get('seen') else ''}",
                str(idea["ticker"]), str(idea.get("added_at") or "")[:10],
                "/ideas"))

    for c in _load_json(state / "confessions.json", []) or []:
        if isinstance(c, dict) and c.get("kind"):
            docs.append(Doc("confession", f"confession: {c['kind']}",
                            str(c.get("text") or ""), str(c.get("ticker") or ""),
                            str(c.get("workdate") or ""), "confession ledger"))

    jobs_dir = state / "jobs"
    for p in sorted(jobs_dir.glob("*.json")) if jobs_dir.is_dir() else ():
        job = _load_json(p, None)
        if not isinstance(job, dict):
            continue
        lines = [f"{job.get('kind')} {job.get('status')}",
                 f"created {job.get('created_at')}, updated {job.get('updated_at')}"]
        for key in ("detail", "error", "delivered_link", "artifact"):
            if job.get(key):
                lines.append(f"{key.replace('_', ' ')}: {job[key]}")
        lines.extend(str(b) for b in job.get("byproducts") or [])
        docs.append(Doc("job", f"{job.get('kind')}: {job.get('status')}",
                        "\n".join(lines), str(job.get("ticker") or ""),
                        str(job.get("workdate") or ""), "/status"))

    from pipeline.youtube import RECORDS_FILE

    for v in _load_json(state / RECORDS_FILE, []) or []:
        if not isinstance(v, dict):
            continue
        lines = [f"privacy: {v.get('privacy')}",
                 f"uploaded {v.get('uploaded_at') or '?'}"
                 + (f", publishes {v['publish_at']}" if v.get("publish_at")
                    else ""),
                 f"https://youtu.be/{v.get('video_id')}"]
        for chapter in v.get("chapters") or []:
            if isinstance(chapter, (list, tuple)) and len(chapter) == 2:
                lines.append(f"chapter {chapter[0]} {chapter[1]}")
        for fix in v.get("corrections") or []:
            if isinstance(fix, dict):
                lines.append(f"correction: {fix.get('text')}")
        if v.get("experiment"):
            lines.append(f"experiment pair {v['experiment']}")
        docs.append(Doc("upload", str(v.get("title") or "untitled upload"),
                        "\n".join(lines), str(v.get("ticker") or ""),
                        str(v.get("workdate") or ""), "the video log"))

    for e in journal.entries(settings):
        day = e.local_date()
        docs.append(Doc("journal", e.text[:100],
                        f"{e.render()}\n({journal.KINDS.get(e.kind, e.kind)})",
                        e.ticker, day.isoformat() if day else "", "the journal"))
    return docs


# ------------------------------------------------------ what the bot is

def _clean(cell: str) -> str:
    cell = cell.replace("\\|", "|").replace("**", "").replace("`", "")
    return " ".join(cell.split())


def commands(readme: Path = README) -> list[tuple[str, str]]:
    """`(usage, what it does)` for every command, off the README's command
    reference — the table `tests/test_docs.py` pins against the handlers the
    bot registers, in both directions, so it cannot name a command that does
    not exist or miss one that does."""
    text = _text(readme)
    try:
        start = text.index("## Command reference")
        end = text.index("### Things that are not commands", start)
    except ValueError:
        return []
    out = []
    for line in text[start:end].splitlines():
        if not line.startswith("| `/"):
            continue
        cells = re.split(r"(?<!\\)\|", line)
        if len(cells) < 3:
            continue
        usage, what = _clean(cells[1]), _clean(cells[2])
        first = re.split(r"(?<=[.!?])\s", what, maxsplit=1)[0]
        out.append((usage, first))
    return out


def _readme_docs(readme: Path = README) -> list[Doc]:
    """The README by section, so "how do I reconcile the spend" finds the
    paragraph that says."""
    text = _text(readme)
    docs: list[Doc] = []
    for usage, what in commands(readme):
        docs.append(Doc("command", usage, what, place="the README"))
    parts = re.split(r"(?m)^(#{2,3} .+)$", text)
    for heading, body in zip(parts[1::2], parts[2::2]):
        title = heading.lstrip("#").strip()
        if title.startswith("Command reference") or not body.strip():
            continue
        docs.append(Doc("docs", title, body.strip()[:6000],
                        place=f"README, “{title}”"))
    return docs


def _pass_docs() -> list[Doc]:
    from pipeline.llm import PURPOSES

    return [Doc("pass", f"AI pass: {name}", what, place="pipeline/llm.py")
            for name, what in PURPOSES.items()]


_WHAT_DENNIS_IS = (
    "You are the local assistant inside Dennis, a Telegram bot that makes "
    "financial videos for one YouTube channel: 9:16 SHORTS (60 to 75 seconds) "
    "on trending stocks, and 16:9 LONG deep dives on value stocks. The "
    "operator supplies the numbers (an uploaded workbook), the thesis and "
    "the approval; the bot does the voice, the visuals, the composition and "
    "the render. The voice is synthetic and disclosed as such.\n\n"
    "How a video moves through the bot: /short or /long TICKER opens a "
    "workspace; the operator uploads the refreshed workbook; the bot sends "
    "the writing prompt (a LONG first reads the company's filings and offers "
    "angles); the script is written outside the bot and pasted back; the "
    "checks run and a report with the cost comes back; the operator taps "
    "Approve; /render buys the voice, fetches the visuals, composes and "
    "renders; the video is delivered; /upload sends it to YouTube, private or "
    "scheduled, never public. Nothing is paid for before Approve.")


def self_description(settings: Settings, *, with_commands: bool = True) -> str:
    """What the model is told about the bot it lives in.

    Built from the code on every question, so it cannot drift: the commands
    come off the README table the docs test pins to the registered handlers,
    the passes off `pipeline.llm.PURPOSES` (pinned by `tests/test_recall.py`
    to every `purpose=` in the code), and the settings are the live ones.

    The command list is the bulk of it. A context too small to hold it and
    the records gets it without, since every command is also in the index.
    """
    from pipeline.llm import PURPOSES, provider_order

    lines = [_WHAT_DENNIS_IS, "", "What you, the local model, do inside the bot:"]
    lines.extend(f"- {name}: {what}" for name, what in PURPOSES.items()
                 if name != "llm")
    cmds = commands() if with_commands else []
    if cmds:
        lines += ["", "The operator's commands:"]
        lines.extend(f"- {usage}: {what}" for usage, what in cmds)
    lines += ["", "What the journal records:"]
    lines.extend(f"- {kind}: {what}" for kind, what in journal.KINDS.items())
    lines += ["", "How the bot is set up right now:",
              f"- MOCK_MODE is {'ON (nothing real is fetched or paid for)' if settings.mock_mode else 'off'}",
              f"- local model: {settings.ollama_model}, told to use a "
              f"{settings.ollama_num_ctx}-token context",
              f"- the passes try: {', '.join(provider_order(settings))}; "
              f"/ask tries: {', '.join(ask_providers(settings)) or 'nothing'}",
              f"- videos are delivered via {settings.delivery_backend}",
              f"- the monthly voice cap is ${settings.monthly_spend_cap_usd:.2f}",
              f"- the overnight batch runs {settings.batch_start_hour:02d}:00 "
              f"to {settings.batch_end_hour:02d}:00"
              + ("" if settings.batch_enabled else " (switched off)")]
    return "\n".join(lines)


def ask_providers(settings: Settings) -> list[str]:
    return [p.strip().lower() for p in settings.ask_provider_order.split(",")
            if p.strip()]


# ---------------------------------------------------------------- the index

def _source_files(settings: Settings) -> list[Path]:
    """Every file the collectors read. Their sizes and times are the index's
    signature, so a change to any of them triggers a rebuild."""
    files: list[Path] = [README]
    for d in _workspace_dirs(settings):
        files.extend(d / name for name in _WS_FILES)
    state = settings.state_dir
    from pipeline.youtube import RECORDS_FILE

    files.extend(state / name for name in (
        "theses.json", "idea_queue.json", "confessions.json", RECORDS_FILE,
        journal.JOURNAL_FILE, journal.ROLLED_FILE))
    jobs_dir = state / "jobs"
    if jobs_dir.is_dir():
        files.extend(sorted(jobs_dir.glob("*.json")))
    return files


def _signature(settings: Settings) -> str:
    h = hashlib.sha1(_VERSION.encode())
    for path in _source_files(settings):
        try:
            st = path.stat()
        except OSError:
            continue
        h.update(f"{path}|{st.st_mtime_ns}|{st.st_size}\n".encode())
    return h.hexdigest()


def collect(settings: Settings) -> list[Doc]:
    docs: list[Doc] = []
    for d in _workspace_dirs(settings):
        docs.extend(_workspace_docs(settings, d))
    docs.extend(_state_docs(settings))
    docs.extend(_readme_docs())
    docs.extend(_pass_docs())
    return docs


class Index:
    """The full-text index, rebuilt whenever what it reads has changed."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.path = settings.state_dir / INDEX_FILE

    def _query(self, sql: str, args=()) -> list[tuple]:
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute(sql, args).fetchall()

    def _signature_on_disk(self) -> str:
        try:
            rows = self._query("SELECT v FROM meta WHERE k='signature'")
        except sqlite3.Error:
            return ""
        return rows[0][0] if rows else ""

    def refresh(self) -> "Index":
        signature = _signature(self.settings)
        if self.path.exists() and self._signature_on_disk() == signature:
            return self
        self.build(signature)
        return self

    def build(self, signature: str = "") -> int:
        """Write a fresh index beside the old one and swap it in, so a
        search running meanwhile reads a whole index, never half of one."""
        docs = collect(self.settings)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(
            f"{INDEX_FILE}.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.unlink(missing_ok=True)
        try:
            with closing(sqlite3.connect(tmp)) as db:
                db.execute(
                    "CREATE VIRTUAL TABLE docs USING fts5(kind UNINDEXED, "
                    "ticker, workdate UNINDEXED, title, body, place UNINDEXED, "
                    "tokenize='porter unicode61')")
                db.execute("CREATE TABLE meta(k TEXT PRIMARY KEY, v TEXT)")
                db.executemany(
                    "INSERT INTO docs VALUES (?,?,?,?,?,?)",
                    [(d.kind, d.ticker, d.workdate, d.title, d.body, d.place)
                     for d in docs])
                db.execute("INSERT INTO meta VALUES ('signature', ?)",
                           (signature or _signature(self.settings),))
                db.commit()
            os.replace(tmp, self.path)
        finally:
            tmp.unlink(missing_ok=True)
        log.info("recall: indexed %d records", len(docs))
        return len(docs)

    def tickers(self) -> set[str]:
        return {r[0] for r in self._query("SELECT DISTINCT ticker FROM docs")
                if r[0]}

    def search(self, terms: list[str], *, any_terms: bool = False,
               tickers: set[str] | frozenset = frozenset(),
               limit: int = 8) -> list[Hit]:
        match = _match(terms, any_terms=any_terms)
        if not match:
            return []
        sql = ("SELECT kind, title, body, ticker, workdate, place, "
               "snippet(docs, 4, '«', '»', ' … ', 16), "
               "bm25(docs, 0.0, 4.0, 0.0, 3.0, 1.0, 0.0) AS score "
               "FROM docs WHERE docs MATCH ?")
        args: list = [match]
        if tickers:
            sql += f" AND ticker IN ({','.join('?' * len(tickers))})"
            args.extend(sorted(tickers))
        sql += " ORDER BY score LIMIT ?"
        args.append(limit)
        try:
            rows = self._query(sql, args)
        except sqlite3.Error as e:
            log.warning("recall: search failed (%s)", e)
            return []
        return [Hit(kind=r[0], title=r[1], body=r[2], ticker=r[3],
                    workdate=r[4], place=r[5], snippet=" ".join(r[6].split()),
                    score=r[7]) for r in rows]

    def latest_for(self, tickers: set[str], limit: int = 10) -> list[Hit]:
        """A ticker's records, newest first, the most telling kinds ahead.
        "What did we say about EXMPL" has almost no search words in it; the
        answer is whatever is on file for EXMPL."""
        order = {"thesis": 0, "video": 1, "brief": 2, "script": 3,
                 "upload": 4, "report": 5, "job": 6, "journal": 7}
        rows = self._query(
            f"SELECT kind, title, body, ticker, workdate, place FROM docs "
            f"WHERE ticker IN ({','.join('?' * len(tickers))})",
            sorted(tickers))
        rows.sort(key=lambda r: (r[4] or ""), reverse=True)
        rows.sort(key=lambda r: order.get(r[0], 9))
        return [Hit(kind=r[0], title=r[1], body=r[2], ticker=r[3],
                    workdate=r[4], place=r[5],
                    snippet=" ".join(r[2].split())[:200])
                for r in rows[:limit]]


def terms_of(text: str) -> list[str]:
    """The words of a query worth searching for, in order, once each."""
    out: list[str] = []
    for word in _WORD_RE.findall(text):
        word = word.strip(".'-&")
        if not word or word.lower() in _STOPWORDS:
            continue
        if word.lower() not in (w.lower() for w in out):
            out.append(word)
    return out


def _match(terms: list[str], *, any_terms: bool) -> str:
    """An FTS5 query. Every term is quoted, so a word that happens to be
    FTS syntax (AND, NEAR, a hyphen) is searched for, not obeyed."""
    quoted = []
    for term in terms:
        term = " ".join(term.replace('"', " ").split())
        if term:
            quoted.append(f'"{term}"')
    return (" OR " if any_terms else " ").join(quoted)


def fuse(*rankings: list[Hit], limit: int = 8) -> list[Hit]:
    """Reciprocal-rank fusion: a record near the top of any ranking wins."""
    scores: dict[tuple, float] = {}
    first: dict[tuple, Hit] = {}
    for ranking in rankings:
        for rank, hit in enumerate(ranking):
            key = (hit.kind, hit.ticker, hit.workdate, hit.title, hit.place)
            scores[key] = scores.get(key, 0.0) + 1.0 / (60 + rank)
            first.setdefault(key, hit)
    best = sorted(scores, key=lambda k: scores[k], reverse=True)
    return [first[k] for k in best[:limit]]


# ---------------------------------------------------------------- /find

def find(settings: Settings, query: str, *, limit: int = 8) -> tuple[list[Hit], bool]:
    """Hits for every word, or for any word when none has them all.
    Returns the hits and whether it had to fall back to any-word."""
    index = Index(settings).refresh()
    terms = terms_of(query)
    hits = index.search(terms, limit=limit)
    if hits or len(terms) < 2:
        return hits, False
    return index.search(terms, any_terms=True, limit=limit), True


def render_hits(hits: list[Hit], *, snippet_chars: int = 180) -> list[str]:
    lines = []
    for n, hit in enumerate(hits, 1):
        lines.append(f"{n}. {hit.label()} — {hit.title[:80]}")
        if hit.snippet:
            lines.append(f"   {hit.snippet[:snippet_chars]}")
    return lines


def find_text(settings: Settings, query: str) -> str:
    query = query.strip()
    if not query:
        return ("usage: /find some words\n"
                "Searches every script, filing brief, check report, thesis, "
                "idea, job, upload and journal line the bot has saved. No AI "
                "involved; /ask for an answer instead of a list.")
    hits, loose = find(settings, query)
    if not hits:
        return f"Nothing on file mentions “{query}”."
    head = f"🔎 {len(hits)} match{'es' if len(hits) != 1 else ''} for “{query}”"
    if loose:
        head += " (nothing has every word, so these have some of them)"
    return "\n".join([head, *render_hits(hits)])


# ---------------------------------------------------------------- /ask

# The model gets at most this much of the records, however large its
# context: past it, the answer gets slower without getting better. Below it,
# the budget follows `OLLAMA_NUM_CTX`, at a conservative three characters to
# the token, so the prompt can never be silently cut the way the filing
# briefs once were (K2).
_SOURCES_MAX_CHARS = 16000
_CHARS_PER_TOKEN = 3
_ANSWER_TOKENS = 1024
_SOURCES = 8

_RULES = (
    "\n\nRULES FOR ANSWERING:\n"
    "- Answer only from FACTS and SOURCES below. If they do not contain the "
    "answer, say \"I don't have that on file\" and name the command that "
    "would know, if one would.\n"
    "- Put the source number in brackets, like [2], after each sentence that "
    "uses it.\n"
    "- Never count, add, subtract or average anything yourself. Every number "
    "you write must be copied from FACTS or SOURCES.\n"
    "- Keep it short: at most eight lines of plain text, no tables, no "
    "markdown headings. It is read in Telegram.\n"
    "- Never invent a ticker, a date, a link or a quote.")

_EXPAND_SYSTEM = (
    "You turn a question about a financial-video bot's records into search "
    "words. The records are video scripts, SEC filing summaries, investment "
    "theses, check reports, job logs and YouTube uploads. Return ONLY a JSON "
    "list of 6 to 12 lowercase words or two-word phrases: the question's own "
    "key words, their synonyms, and the finance terms a script about it "
    "would use (e.g. margins -> \"gross margin\", \"profitability\"). No "
    "stock tickers, no explanation.")


@dataclass
class Answer:
    text: str
    hits: list[Hit] = field(default_factory=list)
    provider: str = ""
    model: str = ""
    reason: str = ""
    by_code: bool = False


def mentioned_tickers(question: str, known: set[str]) -> set[str]:
    """Tickers the question names: typed in capitals, or with a `$`. A
    lowercase "cost" is a word, even with Costco on file."""
    out = set()
    for word in re.findall(r"\$?[A-Za-z][A-Za-z.]{0,5}", question):
        bare = word.lstrip("$").rstrip(".")
        if (word.startswith("$") or bare.isupper()) and bare.upper() in known:
            out.add(bare.upper())
    return out


def expand(settings: Settings, question: str) -> tuple[list[str], str]:
    """The question in the records' own words, from the local model.
    Returns the words and the model's outcome (an `llm` reason)."""
    from pipeline import llm

    out = llm.chat_result(question, settings, system=_EXPAND_SYSTEM,
                          purpose="ask-expand",
                          providers=ask_providers(settings))
    if not out:
        return [], out.reason
    text = out.text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
    start, end = text.find("["), text.rfind("]")
    try:
        words = json.loads(text[start:end + 1]) if 0 <= start < end else []
    except ValueError:
        words = []
    words = [str(w).strip() for w in words
             if isinstance(w, str) and str(w).strip()][:12]
    return words, out.reason


def retrieve(index: Index, question: str, expansion: list[str] = (), *,
             tickers: set[str] = frozenset(),
             limit: int = _SOURCES) -> list[Hit]:
    """The records to hand the model: the question's own words, the
    model's rewording of them, and — when it names a ticker — what is on
    file for that ticker, fused into one ranking."""
    rankings = [index.search(terms_of(question), any_terms=True,
                             tickers=tickers, limit=20)]
    if expansion:
        rankings.append(index.search(list(expansion), any_terms=True,
                                     tickers=tickers, limit=20))
    if tickers:
        rankings.append(index.latest_for(tickers))
    return fuse(*rankings, limit=limit)


# Below this much room for the records, the command list comes out of the
# model's instructions to make space.
_SOURCES_MIN_CHARS = 4000
_PER_SOURCE_MIN_CHARS = 400


def _budget(settings: Settings, fixed_chars: int) -> int:
    """Characters left for the records once the instructions, the figures,
    the question and room for the answer are counted."""
    window = settings.ollama_num_ctx * _CHARS_PER_TOKEN
    left = window - fixed_chars - _ANSWER_TOKENS * _CHARS_PER_TOKEN
    return max(0, min(_SOURCES_MAX_CHARS, left))


def _sources_block(hits: list[Hit], budget: int) -> tuple[str, list[Hit]]:
    """The records as the model reads them, inside `budget` characters.
    A tight budget carries fewer records rather than slivers of all of
    them. Returns the block and the records it carries, numbered as sent."""
    fit = min(len(hits), budget // _PER_SOURCE_MIN_CHARS)
    if not fit:
        return "(nothing fits in the model's context)" if hits else \
            "(the search found nothing)", []
    hits = hits[:fit]
    per = budget // fit
    parts = []
    for n, hit in enumerate(hits, 1):
        head = f"[{n}] {hit.label()} — {hit.title}"[:200]
        room = max(0, per - len(head) - 4)
        body = hit.body if len(hit.body) <= room else hit.body[:room] + " …"
        parts.append(f"{head}\n{body}")
    return "\n\n".join(parts), hits


_NUMBER_RE = re.compile(r"(?<![A-Za-z])\$?\d[\d,]*(?:\.\d+)?%?")
_CITATION_RE = re.compile(r"\[\d+(?:\s*[,–-]\s*\d+)*\]")


def _numbers(text: str) -> set[str]:
    out = set()
    for raw in _NUMBER_RE.findall(text):
        clean = raw.strip("$%").replace(",", "")
        try:
            value = float(clean)
        except ValueError:
            continue
        out.add(f"{value:g}")
    return out


def unsupported_numbers(answer: str, given: str) -> list[str]:
    """Numbers in the answer that appear nowhere in what the model read."""
    said = _CITATION_RE.sub(" ", answer)
    have = _numbers(given)
    seen = []
    for raw in _NUMBER_RE.findall(said):
        clean = raw.strip("$%").replace(",", "")
        try:
            key = f"{float(clean):g}"
        except ValueError:
            continue
        if key not in have and raw not in seen:
            seen.append(raw)
    return seen


_WHY_NOT = {
    "mock": "MOCK_MODE is on, so the model is never called",
    "no_daemon": "nothing answered at the Ollama address — is Ollama running?",
    "timeout": "the model took too long",
    "no_provider": "no model is configured for /ask (ASK_PROVIDER_ORDER)",
    "empty": "the model came back empty",
    "parse_error": "the model's reply could not be read",
}


def _fallback(question: str, hits: list[Hit], reason: str,
              settings: Settings) -> str:
    why = _WHY_NOT.get(reason, reason or "no model answered")
    if reason == "timeout":
        why += f" (over {settings.ollama_timeout_s:.0f}s)"
    lines = [f"The local AI did not answer: {why}."]
    if hits:
        lines.append(f"Here is what the search found for “{question}”:")
        lines.extend(render_hits(hits[:6]))
    else:
        lines.append("The search found nothing on file for it either.")
    return "\n".join(lines)


def ask(settings: Settings, question: str, *,
        today: date | None = None) -> Answer:
    """One question, answered from the bot's own records."""
    from pipeline import llm, tally

    question = " ".join(question.split())
    if not question:
        return Answer(
            "usage: /ask a question about the bot's own work\n"
            "  /ask what did we say about EXMPL's margins?\n"
            "  /ask which videos used the filing brief's contradictions?\n"
            "  /ask how many shorts did we finish this month?\n"
            "Counts and totals are worked out by code, never by the AI. "
            "/find lists matches without the AI.")

    index = Index(settings).refresh()
    tickers = mentioned_tickers(question, index.tickers())
    direct = tally.answer(settings, question,
                          ticker=next(iter(tickers)) if len(tickers) == 1 else "",
                          today=today)
    if direct:
        journal.note(settings, "asked", f"asked: {question[:200]} "
                     f"(answered by code)", answered_by="code")
        return Answer(direct + "\n\n(counted by the bot's code, not the AI)",
                      by_code=True)

    expansion, reason = expand(settings, question)
    hits = retrieve(index, question, expansion, tickers=tickers)
    # The expansion call is the cheap probe: if the model is not there, or
    # is too slow to answer a one-line prompt, the answer call would fail
    # the same way after a longer wait.
    if reason not in (llm.OK, llm.EMPTY, llm.PARSE_ERROR):
        journal.note(settings, "asked", f"asked: {question[:200]} "
                     f"(the model did not answer: {reason})",
                     answered_by="none", reason=reason)
        return Answer(_fallback(question, hits, reason, settings), hits,
                      reason=reason)

    facts = "\n".join(tally.facts(settings, today=today))
    system = self_description(settings) + _RULES
    fixed = len(facts) + len(question) + 200
    if _budget(settings, fixed + len(system)) < _SOURCES_MIN_CHARS:
        system = self_description(settings, with_commands=False) + _RULES
    sources, hits = _sources_block(hits, _budget(settings, fixed + len(system)))
    prompt = (f"FACTS (counted by the bot's code; copy them, never recount):\n"
              f"{facts}\n\nSOURCES:\n{sources}\n\nQUESTION: {question}")
    out = llm.chat_result(prompt, settings, system=system, purpose="ask",
                          providers=ask_providers(settings))
    if not out:
        journal.note(settings, "asked", f"asked: {question[:200]} "
                     f"(the model did not answer: {out.reason})",
                     answered_by="none", reason=out.reason)
        return Answer(_fallback(question, hits, out.reason, settings), hits,
                      provider=out.provider, model=out.model,
                      reason=out.reason)

    text = out.text.strip()
    lines = [text]
    loose = unsupported_numbers(text, f"{facts}\n{sources}\n{question}")
    if loose:
        lines.append(f"\n⚠️ Not in anything it read: {', '.join(loose)}. "
                     f"Treat those as the model's guesses.")
    cited = sorted({int(n) for n in re.findall(r"\[(\d+)\]", text)
                    if 0 < int(n) <= len(hits)})
    if cited:
        lines.append("\nRead: " + " · ".join(
            f"[{n}] {hits[n - 1].label()}" for n in cited))
    elif hits:
        lines.append(f"\n(It read {len(hits)} records and cited none of "
                     f"them. /find shows what they were.)")
    where = "locally" if out.provider == llm.OLLAMA else "by a HOSTED model"
    lines.append(f"— answered {where}, {out.model}")
    journal.note(settings, "asked", f"asked: {question[:200]}",
                 answered_by=out.provider, model=out.model,
                 sources=len(hits), cited=len(cited))
    return Answer("\n".join(lines), hits, provider=out.provider,
                  model=out.model, reason=out.reason)
