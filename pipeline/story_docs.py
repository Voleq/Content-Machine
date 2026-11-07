"""The documents an implosion is told from, read here, on this machine.

An implosion long has no workbook. Its figures, dates and status words come
from the story's own documents: the regulator's order, the prosecutor's
release, the court's judgment, the inquiry's report. Each is read once and
split into numbered sentences, so `D2.14` is document 2, sentence 14 (and
the page it is on, for a PDF). The writer is handed the sentences that carry a
figure, a date or a status word, and every figure he says is checked against
them before approval (build 3).

Where they come from: the links the screener found on the story, and any PDF
or page he drops on the video. Read locally, a PDF with pypdf and a page with
the HTML parser. No model summarises anything here: what reaches the prompt is
the documents' own sentences.

Network: sec.gov through `filings._sec_get` (his SEC_USER_AGENT, the SEC's
rate limit); everything else with the screener's own agent, which names the
project and never a person. MOCK_MODE reads `fixtures/implosions/docs/`.
"""

from __future__ import annotations

import io
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from config import Settings

log = logging.getLogger(__name__)

DOCS_FILE = "documents.json"
DOCS_DIR = "docs"
STORY_FILE = "story.json"
MAX_FETCH = 8               # links read per story, best kinds first
MAX_PAGES = 150             # pages read from one PDF
MAX_BYTES = 30_000_000
_KIND_ORDER = {"regulator": 0, "prosecutor": 1, "court": 2, "inquiry": 3,
               "filing": 4, "release": 5}
_KIND_WORDS = {"regulator": "regulator", "prosecutor": "prosecutor",
               "court": "court", "inquiry": "inquiry", "filing": "filing",
               "release": "release", "upload": "your upload"}


# --------------------------------------------------------------------------
# Files on the workspace
# --------------------------------------------------------------------------

def path(ws_path: Path) -> Path:
    return Path(ws_path) / DOCS_FILE


def load(ws_path: Path) -> dict:
    try:
        data = json.loads(path(ws_path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def documents(ws_path: Path) -> list[dict]:
    return [d for d in load(ws_path).get("documents") or [] if isinstance(d, dict)]


def _save(ws_path: Path, docs: list[dict]) -> dict:
    payload = {"read_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "documents": docs}
    p = path(ws_path)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)
    return payload


def load_story(ws_path: Path) -> dict:
    try:
        data = json.loads((Path(ws_path) / STORY_FILE).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_story(ws_path: Path, story: dict) -> None:
    keep = {k: v for k, v in story.items() if k not in ("parts",)}
    (Path(ws_path) / STORY_FILE).write_text(
        json.dumps(keep, indent=1, ensure_ascii=False), encoding="utf-8")


# --------------------------------------------------------------------------
# Reading one document
# --------------------------------------------------------------------------

_ABBREV = {
    "inc", "co", "corp", "ltd", "llc", "l.l.c", "no", "nos", "mr", "ms", "mrs",
    "dr", "st", "jr", "sr", "u.s", "u.s.c", "v", "vs", "jan", "feb", "mar",
    "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec", "sec",
    "e.g", "i.e", "al", "fed", "reg", "exh", "ex", "p", "pp", "para", "art",
    "approx", "cf", "s.a", "n.v", "plc", "dept", "gov", "rev", "stat", "supp",
    "f", "cir", "d", "s.d.n.y", "n.y", "n.d", "e.d", "u.k", "a.g",
}
_BOUNDARY = re.compile(r"(?<=[.!?])[\"”’)\]]?\s+(?=[\"“(\[]?[A-Z0-9$])")
_LAST_WORD = re.compile(r"([A-Za-z][A-Za-z.]*)\.$")
_ENDS = re.compile(r"[.!?][\"”’)\]]?$")


def _split(text: str) -> list[str]:
    """Sentences, with the usual legal abbreviations (Inc., U.S., No., v.,
    a single initial) kept inside the sentence they belong to."""
    out: list[str] = []
    start = 0
    for m in _BOUNDARY.finditer(text):
        head = text[start:m.start() + 1].rstrip()
        w = _LAST_WORD.search(head[-14:])
        if w and (w.group(1).lower().rstrip(".") in _ABBREV or len(w.group(1)) == 1):
            continue
        out.append(text[start:m.end()].strip())
        start = m.end()
    tail = text[start:].strip()
    if tail:
        out.append(tail)
    return out


def _tidy(text: str) -> str:
    text = text.replace("­", "").replace("ﬁ", "fi").replace("ﬂ", "fl")
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)      # a word broken over a line
    return re.sub(r"\s+", " ", text).strip()


def _worth_keeping(s: str) -> bool:
    """Prose, not a table row or a page footer. A dateline ("Washington
    D.C., Oct. 16, 2013.") is mostly digits and still the date a release
    gives: a sentence that names a date or a sum is kept on fewer letters."""
    if len(s) < 20:
        return False
    letters = sum(c.isalpha() for c in s)
    if letters >= 0.5 * len(s):
        return True
    return letters >= 0.3 * len(s) and bool(_DATE.search(s) or _FIGURE.search(s))


def sentences_of(pages: list[str]) -> list[dict]:
    """`{"n", "page", "text"}` for every sentence, numbered from 1. A
    sentence that runs onto the next page is counted on the page it starts."""
    out: list[dict] = []
    carry, carry_page = "", 1
    for i, page in enumerate(pages, start=1):
        start_page = carry_page if carry else i
        text = _tidy(page)
        if carry:
            text = f"{carry} {text}".strip()
        parts = _split(text)
        carry = ""
        if parts and i < len(pages) and not _ENDS.search(parts[-1]):
            carry = parts.pop()
            carry_page = i if parts else start_page
        for k, s in enumerate(parts):
            if _worth_keeping(s):
                out.append({"n": len(out) + 1, "page": start_page if k == 0 else i,
                            "text": s[:1500]})
    if carry and _worth_keeping(carry):
        out.append({"n": len(out) + 1, "page": carry_page, "text": carry[:1500]})
    return out


def _pdf_pages(data: bytes) -> tuple[str, list[str], str]:
    try:
        from pypdf import PdfReader
    except ImportError:  # pragma: no cover - the filings extra installs it
        return "", [], "pypdf is not installed (pip install -e '.[filings]')"
    try:
        reader = PdfReader(io.BytesIO(data))
        title = str((reader.metadata or {}).get("/Title") or "").strip()
        pages = []
        for page in reader.pages[:MAX_PAGES]:
            try:
                pages.append(page.extract_text() or "")
            except Exception:  # noqa: BLE001 - one bad page is one blank page
                pages.append("")
    except Exception as e:  # noqa: BLE001 - an unreadable PDF is a reason, not a crash
        return "", [], f"the PDF could not be read ({type(e).__name__})"
    if not any(p.strip() for p in pages):
        return title, [], "the PDF has no text layer (a scan): nothing to quote"
    return title, pages, ""


def _html_pages(html: str) -> tuple[str, list[str], str]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:  # pragma: no cover
        return "", [], "beautifulsoup4 is not installed"
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:  # noqa: BLE001 - lxml missing: the slower parser
        soup = BeautifulSoup(html, "html.parser")
    title = (soup.title.get_text(" ", strip=True) if soup.title else "")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside",
                     "form", "noscript", "svg", "button"]):
        tag.decompose()
    body = None
    for sel in ("article", "main", "[role=main]", "#main-content", ".article-body",
                ".field--name-body"):
        node = soup.select_one(sel)
        if node is not None and len(node.get_text(" ", strip=True)) > 400:
            body = node
            break
    body = body or soup.body or soup
    h1 = body.find("h1") if hasattr(body, "find") else None
    if h1 is not None and h1.get_text(strip=True):
        title = h1.get_text(" ", strip=True)
    # One "page" per block, so a heading never runs into the paragraph under it.
    blocks = [el.get_text(" ", strip=True) for el in
              body.find_all(["p", "li", "h1", "h2", "h3", "h4", "td", "blockquote"])]
    blocks = [b if re.search(r"[.!?:]$", b) else b + "." for b in blocks if b]
    text = "\n".join(blocks) or body.get_text(" ", strip=True)
    if not text.strip():
        return title, [], "the page has no text"
    return title, [text], ""


def read_bytes(data: bytes, *, name: str = "", content_type: str = "") -> dict:
    """`{"title", "type", "pages", "sentences", "why"}` for one document."""
    is_pdf = data[:5] == b"%PDF-" or "pdf" in content_type.lower() \
        or name.lower().endswith(".pdf")
    if is_pdf:
        title, pages, why = _pdf_pages(data)
        kind = "pdf"
    else:
        title, pages, why = _html_pages(data.decode("utf-8", errors="replace"))
        kind = "html"
    sents = sentences_of(pages) if pages else []
    if pages and not sents and not why:
        why = "no sentences in it"
    return {"title": title[:200], "type": kind, "pages": len(pages) if kind == "pdf" else 0,
            "sentences": sents, "why": why}


# --------------------------------------------------------------------------
# Fetching
# --------------------------------------------------------------------------

def _host(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _fixture(url: str, settings: Settings) -> tuple[bytes | None, str]:
    base = Path(settings.fixtures_dir) / "implosions" / "docs"
    try:
        index = json.loads((base / "index.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        index = {}
    name = index.get(url)
    if not name:
        return None, "not in the fixtures (mock mode reads no network)"
    try:
        return (base / name).read_bytes(), ""
    except OSError:
        return None, "fixture file missing"


def fetch(url: str, settings: Settings) -> tuple[bytes | None, str, str]:
    """(bytes, content type, why it failed). Never raises."""
    if settings.mocking_screener:
        data, why = _fixture(url, settings)
        return data, "", why
    if _host(url).endswith("sec.gov"):
        from pipeline.filings import _sec_get

        r = _sec_get(url, settings)
        if r is None:
            return None, "", "sec.gov did not answer (is SEC_USER_AGENT set?)"
        return r.content[:MAX_BYTES], r.headers.get("content-type", ""), ""
    try:
        import httpx

        from pipeline.implosions import AGENT

        r = httpx.get(url, timeout=40.0, follow_redirects=True,
                      headers={"User-Agent": AGENT, "Accept-Encoding": "gzip"})
    except Exception as e:  # noqa: BLE001 - a dead link is one document fewer
        return None, "", f"unreachable ({type(e).__name__})"
    if r.status_code >= 400:
        return None, "", f"the site answered {r.status_code}"
    return r.content[:MAX_BYTES], r.headers.get("content-type", ""), ""


def _next_id(docs: list[dict]) -> str:
    nums = [int(d["id"][1:]) for d in docs if re.fullmatch(r"D\d+", str(d.get("id", "")))]
    return f"D{max(nums, default=0) + 1}"


def _entry(doc_id: str, info: dict, *, url: str = "", host: str = "", kind: str = "",
           file: str = "") -> dict:
    return {"id": doc_id, "url": url, "host": host, "kind": kind, "file": file,
            "title": info.get("title", ""), "type": info.get("type", ""),
            "pages": info.get("pages", 0),
            "status": "read" if info.get("sentences") else "failed",
            "why": info.get("why", ""), "sentences": info.get("sentences", [])}


def gather(story: dict, ws_path: Path, settings: Settings, *,
           fetcher=None) -> dict:
    """Read every document link on the story not read yet, best kinds
    first, at most `MAX_FETCH`. Ids already given keep their numbers, so a
    sentence cited as D2.14 stays D2.14. Returns the saved payload."""
    fetcher = fetcher or (lambda u: fetch(u, settings))
    ws_path = Path(ws_path)
    (ws_path / DOCS_DIR).mkdir(parents=True, exist_ok=True)
    docs = documents(ws_path)
    have = {d.get("url") for d in docs if d.get("url")}
    links = [d for d in story.get("documents") or []
             if isinstance(d, dict) and str(d.get("url", "")).startswith(("http://", "https://"))]
    links.sort(key=lambda d: _KIND_ORDER.get(d.get("kind", ""), 9))
    for link in links[:MAX_FETCH]:
        url = link["url"]
        if url in have:
            continue
        doc_id = _next_id(docs)
        data, ctype, why = fetcher(url)
        if data is None:
            info = {"why": why}
            file = ""
        else:
            info = read_bytes(data, name=urlparse(url).path, content_type=ctype)
            ext = ".pdf" if info["type"] == "pdf" else ".html"
            file = f"{DOCS_DIR}/{doc_id}{ext}"
            (ws_path / file).write_bytes(data)
        docs.append(_entry(doc_id, info, url=url, host=link.get("host") or _host(url),
                           kind=link.get("kind", ""), file=file))
        have.add(url)
    return _save(ws_path, docs)


def add_upload(ws_path: Path, filename: str, data: bytes) -> dict:
    """A PDF or a saved page he dropped on the video: read it and file it
    as the next document. Returns its entry."""
    ws_path = Path(ws_path)
    (ws_path / DOCS_DIR).mkdir(parents=True, exist_ok=True)
    docs = documents(ws_path)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(filename).name)[:80] or "upload"
    # The same file dropped again replaces its first reading, under its id.
    old = next((d for d in docs if d.get("kind") == "upload"
                and d.get("file", "").endswith(f"-{safe}")), None)
    doc_id = old["id"] if old else _next_id(docs)
    file = f"{DOCS_DIR}/{doc_id}-{safe}"
    (ws_path / file).write_bytes(data)
    info = read_bytes(data, name=safe)
    entry = _entry(doc_id, info, host="", kind="upload", file=file)
    entry["title"] = entry["title"] or Path(filename).stem
    docs = [entry if d is old else d for d in docs] if old else docs + [entry]
    _save(ws_path, docs)
    return entry


# --------------------------------------------------------------------------
# What the writer is handed
# --------------------------------------------------------------------------

_FIGURE = re.compile(
    r"[$€£]\s?\d|\b\d[\d,.]*\s?(?:%|percent|per cent|million|billion|trillion|"
    r"shares|orders|trades|minutes|hours|days|months|years|customers|investors|"
    r"employees|accounts)\b|\b\d{1,3}(?:,\d{3})+\b", re.I)
_DATE = re.compile(
    r"\b(?:January|February|March|April|May|June|July|August|September|October|"
    r"November|December)\b|\b(?:19|20)\d\d\b|\b\d{1,2}:\d\d\s?(?:a\.?m\.?|p\.?m\.?)",
    re.I)
_STATUS = re.compile(
    r"\b(?:charged|charges|indicted|indictment|pleaded|pled|pleads|guilty|"
    r"convicted|acquitted|sentenced|settled|settlement|agreed to pay|penalty|"
    r"penalties|fined|fine of|disgorgement|restitution|forfeit\w*|bankrupt\w*|"
    r"admit\w*|deny|denying|consent\w*|barred|censured|violated|violation|"
    r"cease-and-desist|judgment|liquidat\w*|collapsed|lost|loss|losses)\b", re.I)


def weight(text: str) -> int:
    """What a sentence can stand behind: a figure (2), a status word (2),
    a date (1)."""
    return (2 * bool(_FIGURE.search(text)) + 2 * bool(_STATUS.search(text))
            + bool(_DATE.search(text)))


def receipts(doc: dict, cap: int) -> list[dict]:
    """The sentences worth handing over, in the document's order. A short
    document is handed over whole: the sentence that says what went wrong
    ("did not have a procedure to check the code reached every server")
    often carries no number and is the one the video is about. A long one
    gives its first two (what it is), then those carrying a figure, a
    status word or a date, best first, up to `cap`."""
    sents = doc.get("sentences") or []
    if len(sents) <= cap:
        return list(sents)
    head = sents[:2]
    rest = sorted(sents[2:], key=lambda s: (-weight(s["text"]), s["n"]))
    keep = {s["n"] for s in head} | {s["n"] for s in rest[:max(0, cap - len(head))]}
    return [s for s in sents if s["n"] in keep]


def _label(doc: dict) -> str:
    bits = [_KIND_WORDS.get(doc.get("kind", ""), doc.get("kind", "")) or "document"]
    if doc.get("host"):
        bits.insert(0, doc["host"])
    if doc.get("type") == "pdf" and doc.get("pages"):
        bits.append(f"PDF, {doc['pages']} page{'s' if doc['pages'] != 1 else ''}")
    return " · ".join(b for b in bits if b)


def _sentence_line(doc: dict, s: dict, width: int) -> str:
    where = f" p.{s['page']}" if doc.get("type") == "pdf" else ""
    text = s["text"] if len(s["text"]) <= width else s["text"][:width - 1] + "…"
    return f"  {doc['id']}.{s['n']}{where}  {text}"


def prompt_block(ws_path: Path, *, per_doc: int = 40, total_chars: int = 24000,
                 width: int = 480) -> str:
    """Every document read, and its receipt sentences, numbered."""
    docs = documents(ws_path)
    if not docs:
        return ("(no documents read yet. Drop the PDFs (the regulator's order, the "
                "prosecutor's release, the court's judgment) on the video, and the "
                "prompt is made again with their sentences.)")
    out: list[str] = []
    used = 0
    for doc in docs:
        head = f"{doc['id']} · {doc.get('title') or 'untitled'} ({_label(doc)})"
        if doc.get("url"):
            head += f"\n  {doc['url']}"
        if doc.get("status") != "read":
            out.append(f"{head}\n  NOT READ: {doc.get('why') or 'no text'}")
            continue
        picked = receipts(doc, per_doc)
        lines = [head]
        for s in picked:
            line = _sentence_line(doc, s, width)
            if used + len(line) > total_chars:
                lines.append("  (… the rest of this document's sentences are on the "
                             "video's documents list)")
                break
            lines.append(line)
            used += len(line)
        shown = {s["n"] for s in picked}
        left = [s for s in doc.get("sentences") or [] if s["n"] not in shown]
        weighty = sum(1 for s in left if weight(s["text"]))
        if weighty:
            lines.append(f"  ({len(left)} more sentences not listed, {weighty} of them "
                         f"with a figure, a date or a status word. The bot checks "
                         f"against every sentence, listed or not.)")
        elif left:
            lines.append(f"  ({len(left)} more sentences not listed: none carries a "
                         f"figure, a date or a status word)")
        out.append("\n".join(lines))
    return "\n\n".join(out)


def brief_block(ws_path: Path) -> str:
    """The angle step's shorter look at the same documents."""
    return prompt_block(ws_path, per_doc=12, total_chars=9000, width=320)


def story_block(story: dict) -> str:
    if not story:
        return "(no story on file for this video)"
    from pipeline.implosions import status_words

    head = story.get("name") or "?"
    if story.get("year") and str(story["year"]) not in head:
        head += f" ({story['year']})"
    lines = [f"Story: {head}"]
    if story.get("loss_text"):
        lines.append(f"Size, as the list gives it (a map, not a receipt): {story['loss_text']}")
    lines.append(f"Where it stands, as the screener read it: {status_words(story)}")
    if story.get("what"):
        lines.append(f"What the list says: {story['what']}")
    if story.get("extract"):
        lines.append("Background, from the encyclopedia's intro (a map, not a receipt: "
                     "nothing here goes in the script unless a document below says it "
                     f"too):\n  {story['extract']}")
    p = story.get("pitch") or {}
    ideas = [f"  {label}: {p[k]}" for k, label in
             (("detour", "detour"), ("lesson", "what the viewer learns"), ("joke", "joke"))
             if p.get(k)]
    if ideas:
        lines.append("The screener's pitch (the local model's ideas, not facts; use, "
                     "change or ignore):\n" + "\n".join(ideas))
    if story.get("anniversary"):
        lines.append(f"Timing: {story['anniversary']}")
    return "\n".join(lines)


def find_sentence(ws_path: Path, ref: str) -> str:
    """`D2.14` back to its text, or ""."""
    m = re.fullmatch(r"(D\d+)\.(\d+)", (ref or "").strip())
    if not m:
        return ""
    for doc in documents(ws_path):
        if doc.get("id") == m.group(1):
            for s in doc.get("sentences") or []:
                if s["n"] == int(m.group(2)):
                    return s["text"]
    return ""


def summary(ws_path: Path) -> dict:
    """What the page and the card say about the documents."""
    data = load(ws_path)
    docs = [d for d in data.get("documents") or [] if isinstance(d, dict)]
    read = [d for d in docs if d.get("status") == "read"]
    return {"read_at": data.get("read_at", ""), "count": len(docs), "read": len(read),
            "sentences": sum(len(d.get("sentences") or []) for d in read)}
