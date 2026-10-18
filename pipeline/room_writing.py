"""THE WRITING ON HIS THINGS (18 Oct 2026): what each video letters on them.

The room is rendered with its labels blank (room3d/textures.py `LABELS`) and
says where each one is in a shot (`Plate.writable["labels"]`), so the words on
his things are this video's, laid on by `pipeline/room_dressing.py`:

- THE FILINGS FOLLOW THE VIDEO'S DATE. The binders on his shelf are the last
  six annual reports and the latest three quarterlies, the proxy, the 8-Ks
  and the calls of the year, each with its year; the box by the board holds
  the ten years before; the report on his desk and the stack beside it are
  this company's latest 10-K and 10-Q, with its ticker. A shelf labelled
  '21, '22, '23 aged with the room.
- THE NOTES AND THE CARDS ARE FROM THE SCRIPT. The local model (Gemma, through
  Ollama, never a hosted one) reads the approved script once and writes the
  sticky notes on his screen and the cards on his board, a few words each.
  A number it writes must be in the script word for word, and anything too
  long, odd or advising is thrown out. Its answer is kept in the workspace,
  so a re-render of the same script letters the same things.
- THE REST IS FROM A LIST he can edit (`assets/room_writing.json`): the
  stitched sign every time, and the notes and cards whenever the model is not
  running or wrote nothing usable. Each video takes different lines from it
  than the video before.

NOTHING HERE COMPUTES A FIGURE. The years are the calendar's; every other
number on his things is the list's or the script's own.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import logging
import random
import re
from pathlib import Path

log = logging.getLogger(__name__)

POOL_FILE = "room_writing.json"
CACHE_FILE = "room_writing.json"
# How much the model is asked for, and how long each piece may be: what
# fits a 7.5 cm note and an index card at the back of the room.
NOTES, CARDS = 3, 3
NOTE_MAX = 18
HEAD_MAX = 12
LINE_MAX = 22
SCRIPT_MAX_CHARS = 12000
# The characters the room's marker and handwriting faces carry.
_PLAIN = re.compile(r"^[A-Za-z0-9 .,'\"?!%$&()/:;+#=@-]+$")
_ADVICE = re.compile(r"\b(buy|sell|short it|go long|guarantee\w*|to the moon|financial advice)\b",
                     re.IGNORECASE)
_NUMBER = re.compile(r"\d[\d.,]*")


def when_of(workdate: str) -> _dt.date:
    """The video's date from its workspace's name (`YYYY-MM-DD...`), or today."""
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", str(workdate or ""))
    if m:
        try:
            return _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    return _dt.datetime.now(_dt.UTC).date()


# ------------------------------------------------------------ the filings
def latest_10k(day: _dt.date) -> int:
    """The fiscal year of the last annual report out by `day` (filed by
    March for a calendar year)."""
    return day.year - 1 if day.month >= 3 else day.year - 2


def latest_quarters(day: _dt.date, n: int = 3) -> list[tuple[int, int]]:
    """The last `n` quarterly reports out by `day`, oldest first, as
    (quarter, year): Q1 out by May, Q2 by August, Q3 by November (the
    fourth quarter is the annual report)."""
    m, y = day.month, day.year
    q, yr = ((1, y) if 5 <= m <= 7 else (2, y) if 8 <= m <= 10
             else (3, y) if m >= 11 else (3, y - 1))
    out = []
    for _ in range(n):
        out.append((q, yr))
        q, yr = (q - 1, yr) if q > 1 else (3, yr - 1)
    return out[::-1]


def filings(ticker: str, day: _dt.date) -> dict[str, str]:
    """The filings' labels, by the id of the thing they go on."""
    k = latest_10k(day)
    quarters = latest_quarters(day)
    proxy = day.year if day.month >= 4 else day.year - 1
    yy = lambda y: f"'{y % 100:02d}"
    out = {f"spine1{j}": f"10-K {yy(k - 5 + j)}" for j in range(6)}
    for j, (q, y) in enumerate(quarters):
        out[f"spine2{j}"] = f"10-Q Q{q} {yy(y)}"
    out["spine23"] = f"PROXY {yy(proxy)}"
    out["spine24"] = f"8-Ks {yy(day.year)}"
    out["spine25"] = f"CALLS {yy(day.year)}"
    out["boxlabel"] = f"10-Ks {k - 15}-{k - 6}\nDO NOT THROW OUT"
    t = (ticker or "").upper().strip()
    q, y = quarters[-1]
    out["deskstack-top"] = f"FORM 10-Q\n{t}\nQ{q} {y}".replace("\n\n", "\n")
    out["boxstack-top"] = f"DEF 14A\n{t}\n{proxy}".replace("\n\n", "\n")
    out["filing"] = f"FORM 10-K\nANNUAL REPORT\nFISCAL YEAR {k}" + (f"  ·  {t}" if t else "")
    return out


# --------------------------------------------------------------- the list
def load_pool(assets_dir: Path) -> dict[str, list[str]]:
    """The editable list, or nothing (each kind then goes up blank)."""
    path = Path(assets_dir) / POOL_FILE
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        log.warning("room writing: %s unreadable (%s) — the notes, cards and "
                    "sign go up blank", path, e)
        return {}
    return {k: [str(x) for x in v if str(x).strip()]
            for k, v in raw.items() if isinstance(v, list)}


def turn(episode: int, ticker: str, day: _dt.date) -> int:
    """Which turn of the lists this video takes: the long's number, else the
    day (a short) with the ticker breaking a tie between two the same day."""
    if episode > 0:
        return episode
    tie = int(hashlib.sha256(str(ticker).upper().encode()).hexdigest(), 16) % 3
    return day.toordinal() * 3 + tie


def take(pool: list[str], n: int, at: int, salt: str) -> list[str]:
    """`n` from `pool`, in a fixed shuffle, the `at`th run of `n`: the next
    video's run starts where this one's ended, so neighbours share none
    while the list holds two runs."""
    if not pool:
        return []
    order = list(pool)
    random.Random(f"room-writing|{salt}").shuffle(order)
    return [order[(at * n + i) % len(order)] for i in range(min(n, len(order)))]


# --------------------------------------------------------------- the model
def _numbers_ok(text: str, script: str) -> bool:
    return all(m.group(0).rstrip(".,") in script for m in _NUMBER.finditer(text))


def _clean(text, limit: int, script: str) -> str | None:
    t = " ".join(str(text or "").split())
    if not t or len(t) > limit or not _PLAIN.match(t) or _ADVICE.search(t):
        return None
    return t if _numbers_ok(t, script) else None


def _parse(answer: str, script: str) -> tuple[list[str], list[str]]:
    """(notes, cards) the model wrote that pass, each card "HEAD\\nl1\\nl2"."""
    m = re.search(r"\{.*\}", answer or "", re.DOTALL)
    if not m:
        return [], []
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return [], []
    notes = [n for n in (_clean(x, NOTE_MAX, script) for x in data.get("notes") or [])
             if n][:NOTES]
    cards = []
    for c in data.get("cards") or []:
        if not isinstance(c, dict):
            continue
        head = _clean(c.get("head"), HEAD_MAX, script)
        lines = [ln for ln in (_clean(x, LINE_MAX, script) for x in (c.get("lines") or [])[:2])
                 if ln]
        if head and lines:
            cards.append("\n".join([head.upper(), *lines]))
    return notes, cards[:CARDS]


PROMPT = """Dennis is a deadpan investor who reads company filings at 3am. Below is \
the script of his next video, about {ticker}. Write what he scribbled while \
preparing it, as JSON and nothing else:

{{"notes": [3 sticky notes for his monitor, each 1 to 3 words, at most {note} characters],
 "cards": [3 index cards for his whiteboard, each {{"head": "1 or 2 words, at most {head} characters",
           "lines": ["2 short lines, at most {line} characters each"]}}]}}

Rules: only what the script says or asks. No number unless that exact number \
is in the script. No advice to buy or sell. Plain letters, no emoji.

SCRIPT:
{script}
"""


def from_script(script_text: str, ticker: str, settings) -> tuple[list[str], list[str]]:
    """The notes and cards the local model wrote from the script; empty when
    it is not running or wrote nothing that passes."""
    from pipeline.llm import OLLAMA, chat_result

    text = (script_text or "").strip()
    if not text:
        return [], []
    out = chat_result(
        PROMPT.format(ticker=ticker, note=NOTE_MAX, head=HEAD_MAX, line=LINE_MAX,
                      script=text[:SCRIPT_MAX_CHARS]),
        settings, system="You write the scribbles on a finance video's desk props. "
                         "Reply with JSON only.",
        purpose="room-writing", providers=[OLLAMA])
    if not out:
        return [], []
    return _parse(out.text, text)


# ------------------------------------------------------------ one video
def script_text(script) -> str:
    return str(getattr(script, "narration", "") or getattr(script, "audio_script", "") or "")


def props(script, *, ticker: str, workdate: str, episode: int, settings,
          workspace: Path | None = None) -> tuple[tuple[str, str], ...]:
    """Everything lettered on his things for one video, as (id, text) pairs."""
    day = when_of(workdate)
    out = filings(ticker, day)
    pool = load_pool(settings.assets_dir)
    at = turn(episode, ticker, day)
    text = script_text(script)
    sha = hashlib.sha256(text.encode()).hexdigest()[:16]
    notes: list[str] = []
    cards: list[str] = []
    cache = Path(workspace) / CACHE_FILE if workspace is not None else None
    if cache is not None and cache.exists():
        try:
            kept = json.loads(cache.read_text(encoding="utf-8"))
            if kept.get("sha") == sha:
                notes, cards = list(kept.get("notes") or []), list(kept.get("cards") or [])
        except (OSError, ValueError):
            pass
    if not notes and not cards and text:
        notes, cards = from_script(text, ticker, settings)
        if (notes or cards) and cache is not None:
            # only the model's answer is kept: a list fallback is taken
            # again next time, when the model may be running
            try:
                cache.write_text(json.dumps({"sha": sha, "notes": notes, "cards": cards},
                                            indent=1), encoding="utf-8")
            except OSError:
                pass
    notes = (notes + [n for n in take(pool.get("notes", []), NOTES * 2, at, "notes")
                      if n not in notes])[:NOTES]
    cards = (cards + [c for c in take(pool.get("cards", []), CARDS * 2, at, "cards")
                      if c not in cards])[:CARDS]
    for i, n in enumerate(notes):
        out[f"note{i}"] = n
    for i, c in enumerate(cards):
        out[f"card{i}"] = c
    sign = take(pool.get("stitches", []), 1, at, "stitches")
    if sign:
        out["cs"] = sign[0]
    return tuple(sorted(out.items()))
