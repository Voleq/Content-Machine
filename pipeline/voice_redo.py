"""The voice, sentence by sentence (A6, A7).

`sentences` cuts the finished voice into the script's sentences with their
times, read off the word timings, so a sentence can be listened to, pointed
at by number, and voiced again on its own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

MAX_REDOS = 10
_SENTENCE_RE = re.compile(r"[^.?!\n]+(?:[.?!]+[\"”’)]*|$)")


@dataclass
class SpokenSentence:
    index: int            # 1-based, what `/voice redo N` takes
    text: str
    start: float
    end: float
    char_start: int
    char_end: int


def sentences(words, clean_text: str) -> list[SpokenSentence]:
    """The clean script's sentences that the voice actually says, timed."""
    out: list[SpokenSentence] = []
    for m in _SENTENCE_RE.finditer(clean_text or ""):
        a, b = m.span()
        while a < b and clean_text[a].isspace():
            a += 1
        text = clean_text[a:b].strip()
        if not text:
            continue
        said = [w for w in words if a <= w.char_start < b]
        if not said:
            continue
        out.append(SpokenSentence(index=len(out) + 1, text=text,
                                  start=said[0].start, end=said[-1].end,
                                  char_start=a, char_end=a + len(text)))
    return out


def clock(seconds: float) -> str:
    m, s = divmod(max(0.0, seconds), 60)
    return f"{int(m)}:{s:04.1f}"


# -- redo one sentence (A7) ---------------------------------------------------
# A sentence the voice got wrong is said again on its own, with the same words,
# and the new take is cut into the voice in the pause either side of it. The
# cut points sit halfway into those pauses and the pauses keep their length,
# so the rhythm around the sentence does not move; only the sentence does.
# It is a paid generation of a few dozen characters, through the same fence
# and ledger as the whole voice, and capped per video. Whether Eleven v4
# joins cleanly at the cut is untested; the first real run will say.

FRAG_LEAD_S = 0.02     # kept before the take's first word
FRAG_TAIL_S = 0.06     # and after its last


class RedoRefused(Exception):
    pass


@dataclass
class RedoResult:
    index: int
    text: str
    old_s: float
    new_s: float
    cost_usd: float
    left: int


def redos_path(ws_path, fmt: str):
    from pathlib import Path

    return Path(ws_path) / f"voice_redos_{fmt}.json"


def redos_done(ws_path, fmt: str) -> list[dict]:
    import json

    try:
        rows = json.loads(redos_path(ws_path, fmt).read_text(encoding="utf-8"))
        return rows if isinstance(rows, list) else []
    except (OSError, ValueError):
        return []


def _cut_points(rows: list[SpokenSentence], i: int, duration: float):
    """(cut_a, cut_b) halfway into the pauses either side of sentence i."""
    s = rows[i]
    a = (rows[i - 1].end + s.start) / 2 if i > 0 else 0.0
    b = (s.end + rows[i + 1].start) / 2 if i + 1 < len(rows) else duration
    return max(0.0, min(a, s.start)), min(duration, max(b, s.end))


def splice_words(words, frag_words, rows, i, duration, cut_a, cut_b):
    """The voice's words after the take is cut in, and the new duration."""
    from pipeline.models import WordTimestamp

    s = rows[i]
    f0 = max(0.0, frag_words[0].start - FRAG_LEAD_S)
    f1 = frag_words[-1].end + FRAG_TAIL_S
    # The take's own pre- and post-roll count towards the pauses, so the
    # pause before the sentence and the one after keep their length.
    lead = max(0.0, (s.start - cut_a) - (frag_words[0].start - f0))
    tail = max(0.0, (cut_b - s.end) - (f1 - frag_words[-1].end))
    seg = lead + (f1 - f0) + tail
    delta = seg - (cut_b - cut_a)
    out = [w for w in words if w.char_start < s.char_start]
    for w in frag_words:
        out.append(WordTimestamp(
            word=w.word,
            start=round(cut_a + lead + (w.start - f0), 4),
            end=round(cut_a + lead + (w.end - f0), 4),
            char_start=w.char_start + s.char_start,
            char_end=w.char_end + s.char_start))
    for w in words:
        if w.char_start >= s.char_end:
            out.append(w.model_copy(update={"start": round(w.start + delta, 4),
                                            "end": round(w.end + delta, 4)}))
    return out, (f0, f1, lead, tail), duration + delta


def splice_audio(orig, frag, out, cut_a, cut_b, window, settings,
                 duration: float) -> None:
    """orig[0:cut_a] + lead silence + frag[f0:f1] + tail silence + orig[cut_b:].
    A side with nothing in it (the first or last sentence) is left out."""
    from pipeline.render_common import run_ffmpeg

    f0, f1, lead, tail = window
    fmt = "aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=mono"
    parts, labels = [], []
    if cut_a > 0.001:
        parts.append(f"[0:a]{fmt},atrim=0:{cut_a:.4f},asetpts=PTS-STARTPTS,"
                     f"afade=t=out:st={max(0.0, cut_a - 0.01):.4f}:d=0.01[a]")
        labels.append("[a]")
    parts.append(
        f"[1:a]{fmt},atrim={f0:.4f}:{f1:.4f},asetpts=PTS-STARTPTS,"
        f"afade=t=in:d=0.01,afade=t=out:st={max(0.0, f1 - f0 - 0.01):.4f}:d=0.01,"
        f"adelay={int(round(lead * 1000))}:all=1,apad=pad_dur={tail:.4f}[b]")
    labels.append("[b]")
    if cut_b < duration - 0.001:
        parts.append(f"[0:a]{fmt},atrim=start={cut_b:.4f},asetpts=PTS-STARTPTS,"
                     f"afade=t=in:d=0.01[c]")
        labels.append("[c]")
    graph = ";".join(parts) + ";" + "".join(labels) + (
        f"concat=n={len(labels)}:v=0:a=1[out]")
    run_ffmpeg(["-i", str(orig), "-i", str(frag), "-filter_complex", graph,
                "-map", "[out]", "-c:a", "aac", "-b:a", settings.audio_bitrate,
                str(out)])


def redo_sentence(engine, settings, *, text: str, fmt: str, events, index: int,
                  ticker: str, ws_path) -> RedoResult:
    """Say sentence `index` (1-based) again and cut it into the voice."""
    import json
    import shutil

    from pipeline.models import WordTimestamp
    from pipeline.render_common import ffprobe_duration
    from pipeline.standing import _now

    cdir = engine.voice_dir(text, fmt, events=events)
    if cdir is None:
        raise RedoRefused("there is no voice for this script yet — it is made "
                          "when the render starts")
    done = redos_done(ws_path, fmt)
    if len(done) >= MAX_REDOS:
        raise RedoRefused(f"all {MAX_REDOS} sentence redos for this video are "
                          f"used; a script edit and a fresh approval re-voice "
                          f"the whole thing")
    audio, words_file = cdir / "audio.m4a", cdir / "words.json"
    words = [WordTimestamp(**w) for w in
             json.loads(words_file.read_text(encoding="utf-8"))]
    rows = sentences(words, text)
    if not 1 <= index <= len(rows):
        raise RedoRefused(f"there is no sentence {index}; the voice has "
                          f"{len(rows)} (/voice lists them)")
    i = index - 1
    pick = rows[i]
    take = 1 + sum(1 for r in done if r.get("text") == pick.text)
    frag = engine.synthesize(pick.text, fmt, ticker=ticker, take=take)
    if not frag.words:
        raise RedoRefused("the new take came back with no words; nothing was "
                          "changed")
    duration = ffprobe_duration(audio)
    cut_a, cut_b = _cut_points(rows, i, duration)
    new_words, window, _new_dur = splice_words(words, frag.words, rows, i,
                                               duration, cut_a, cut_b)
    orig = cdir / "audio.orig.m4a"
    if not orig.exists():
        shutil.copy2(audio, orig)
        shutil.copy2(words_file, cdir / "words.orig.json")
    tmp = cdir / "audio.redo.m4a"
    splice_audio(audio, frag.audio_path, tmp, cut_a, cut_b, window, settings,
                 duration)
    tmp.replace(audio)
    words_file.write_text(json.dumps([w.model_dump() for w in new_words]),
                          encoding="utf-8")
    new_len = ffprobe_duration(audio)
    row = {"index": index, "text": pick.text, "take": take,
           "at": _now().isoformat(), "cost_usd": frag.cost_usd,
           "tier": frag.tier, "voice": cdir.name}
    path = redos_path(ws_path, fmt)
    path.write_text(json.dumps(done + [row], indent=2), encoding="utf-8")
    return RedoResult(index=index, text=pick.text, old_s=duration,
                      new_s=new_len, cost_usd=frag.cost_usd,
                      left=MAX_REDOS - len(done) - 1)
