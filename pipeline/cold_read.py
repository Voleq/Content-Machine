"""The cold read (S4): a first-time viewer's reaction, before the voice is paid.

The writer has read the script forty times; the operator has read it twice.
Neither can hear it the way somebody who has never seen the channel will.
So the bot writes a prompt the operator pastes into his own Claude chat (no
paid model call here): the narration, numbered, and five questions a cold
viewer answers by quoting the line. The answer is pasted back with
`/script coldread <answer>`, saved beside the script, and every quote is
linked to the line it came from, so `/edit N` is one step away.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

HEADINGS = ("Lost me", "Landed", "Fell flat", "I'd click away",
            "Didn't believe")
QUOTE_RATIO = 0.6

_TAG_RE = re.compile(r"\[[^\]]*\]")
_LREF_RE = re.compile(r"\bL(\d{1,4})\b")
_QUOTE_RE = re.compile(r"[“\"]([^”\"]{8,400})[”\"]")
_SENTENCE_RE = re.compile(r"[^.?!]+[.?!]*")


@dataclass
class ColdRead:
    text: str
    saved_at: str
    quotes: list[tuple[str, int]] = field(default_factory=list)
    script_sha: str = ""


def spoken_lines(script, raw: str = "") -> list[tuple[int, str]]:
    """The spoken words, numbered the way a fix reaches them.

    A LONG is numbered by the stored script's own lines (what `/script` and
    `/edit` number), tags taken out and empty lines skipped. A SHORT's
    stored script is JSON, so its narration is numbered by sentence."""
    narration = (getattr(script, "narration", None)
                 or getattr(script, "audio_script", "") or "")
    if hasattr(script, "chapter_list") and raw:
        # Only the lines the narrator says: trailers and headers are not.
        spoken = " ".join(narration.split())
        out = []
        for n, line in enumerate(raw.splitlines(), 1):
            text = " ".join(_TAG_RE.sub(" ", line).split())
            if text and text in spoken:
                out.append((n, text))
        return out
    sentences = [" ".join(m.group(0).split())
                 for m in _SENTENCE_RE.finditer(narration)]
    return [(n, s) for n, s in enumerate((s for s in sentences if s), 1)]


def cold_read_prompt(lines: list[tuple[int, str]], fmt: str) -> str:
    """The prompt the operator pastes into his own chat."""
    kind = ("a 50-second vertical short" if fmt == "short"
            else "a long YouTube video, ten minutes or more")
    body = "\n".join(f"L{n}: {text}" for n, text in lines)
    heads = "\n".join(f"## {h}" for h in HEADINGS)
    return (
        f"You are a viewer who has never seen this channel. You clicked on "
        f"{kind} about a stock, and below is every word the narrator says, "
        f"line by line. Read it once, at speaking pace, the way you would "
        f"hear it — you cannot scroll back.\n\n"
        f"Then answer under these five headings. Under each, quote the line "
        f"exactly, with its L number, then one sentence on why. Two or "
        f"three lines per heading at most; leave a heading empty if nothing "
        f"belongs there.\n\n{heads}\n\n"
        f"Finish with **## Three fixes**: the three changes that would most "
        f"keep you watching, each naming its L number. Do not rewrite the "
        f"script and do not judge the investment — only how it lands on a "
        f"first listen.\n\n---\n\n{body}\n")


def link_quotes(answer: str, lines: list[tuple[int, str]]) -> list[tuple[str, int]]:
    """(quote, line) for every reference in the answer. An `L12` wins; a
    quoted span is matched to the line it reads most like, if any is close."""
    known = dict(lines)
    out: list[tuple[str, int]] = []
    for row in (answer or "").splitlines():
        refs = [int(n) for n in _LREF_RE.findall(row) if int(n) in known]
        if refs:
            for n in refs:
                out.append((known[n], n))
            continue
        for m in _QUOTE_RE.finditer(row):
            quote = m.group(1).strip()
            best, ratio = 0, 0.0
            for n, text in lines:
                r = (1.0 if quote.lower() in text.lower() else
                     SequenceMatcher(None, quote.lower(), text.lower()).ratio())
                if r > ratio:
                    best, ratio = n, r
            if best and ratio >= QUOTE_RATIO:
                out.append((quote, best))
    seen: set[tuple[str, int]] = set()
    return [q for q in out if not (q in seen or seen.add(q))]


def _path(ws_path: Path, fmt: str) -> Path:
    return Path(ws_path) / f"cold_read_{fmt}.json"


def save_cold_read(ws_path: Path, fmt: str, answer: str,
                   lines: list[tuple[int, str]], script_sha: str = "") -> ColdRead:
    from pipeline.standing import _now

    read = ColdRead(text=answer.strip(), saved_at=_now().isoformat(),
                    quotes=link_quotes(answer, lines), script_sha=script_sha)
    path = _path(ws_path, fmt)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(asdict(read), indent=2, ensure_ascii=False),
                   encoding="utf-8")
    tmp.replace(path)
    return read


def load_cold_read(ws_path: Path, fmt: str) -> ColdRead | None:
    path = _path(ws_path, fmt)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return ColdRead(text=data["text"], saved_at=data.get("saved_at", ""),
                        quotes=[(str(q), int(n)) for q, n in data.get("quotes", [])],
                        script_sha=data.get("script_sha", ""))
    except (OSError, ValueError, KeyError, TypeError):
        return None
