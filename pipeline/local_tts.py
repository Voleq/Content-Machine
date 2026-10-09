"""Local neural TTS: the free draft tier (P3.2).

There were two tiers and a gap between them. `MOCK_MODE` gives a hum with
made-up word timings — enough to prove the pipeline runs, useless for judging
whether a script *sounds* right. ElevenLabs gives the real thing and costs
money, so every pacing experiment was a purchase.

This is the middle: a local neural voice on the render box's GPU, producing
listenable speech with word timings, for free. You iterate on pacing, on where
the cuts land, on whether a `[BEAT]` is doing anything — and spend one paid
generation on the final.

**Word timings are the hard part.** Piper emits audio, not an alignment. So
the text is synthesized *sentence by sentence*, each sentence's real duration
is measured with ffprobe, and words are distributed inside it in proportion to
their length. Sentence boundaries are therefore exact; a word's position
*within* a sentence is interpolated, off by a fraction of a second on a long
one. That is the right trade for a draft — every visual cue lands on the
correct sentence, which is what you are actually judging — and it is why draft
audio must never reach a final render, where the master clock has to be real.

Draft audio is marked as such all the way through: the tier is in the cache
key, in the `TTSResult`, and in the render manifest, and `render_long` refuses
to make a final out of it.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from config import Settings
from pipeline.models import WordTimestamp
from pipeline.render_common import RenderError, ffprobe_duration, run_ffmpeg

log = logging.getLogger(__name__)

# Sentence split that keeps the terminator, so durations sum to the whole.
# A terminator ends a sentence only when whitespace (or the end) follows it:
# the old `[^.!?]+` cut "4.7 percent" into "4." and "7 percent.", and the
# voice read a figure as two sentences.
_SENTENCE_RE = re.compile(r"\S.*?(?:[.!?]+(?=\s|$)|$)", re.S)
# Where a long sentence may be cut: a comma with whitespace after it — never
# the thousands separator inside "1,234", which a split turned into
# "1, 234" ("one, two hundred thirty-four").
_CLAUSE_RE = re.compile(r",(?=\s)")

# A sentence longer than this is split further: interpolation error grows with
# sentence length, and one 40-word run would smear every cue inside it.
MAX_SENTENCE_WORDS = 24


class LocalTTSUnavailable(RuntimeError):
    """No local voice on this host — the caller falls back to mock."""


def split_sentences(text: str) -> list[str]:
    """Sentences, then over-long ones split at commas.

    Each returned piece gets its own synthesis call and its own measured
    duration, so this list is exactly the set of anchors that will be exact.

    EVERY PIECE IS A SLICE OF `text`, verbatim. The pieces used to be
    rebuilt with `", ".join`, which changed the text the voice was given
    and stopped `text.find(piece)` from finding it — the char offsets then
    fell back to wherever the last piece ended, and every visual cue after
    that point drifted in a draft or a proof.
    """
    out: list[str] = []
    for m in _SENTENCE_RE.finditer(text):
        s = m.group(0).strip()
        if not s:
            continue
        if len(s.split()) <= MAX_SENTENCE_WORDS:
            out.append(s)
            continue
        # Prefer a comma boundary: it is where the voice would breathe anyway.
        start = 0
        for c in _CLAUSE_RE.finditer(s):
            if len(s[start:c.end()].split()) >= MAX_SENTENCE_WORDS:
                out.append(s[start:c.end()].strip())
                start = c.end()
        tail = s[start:].strip()
        if tail:
            out.append(tail)
    return out or ([text.strip()] if text.strip() else [])


def distribute_words(sentence: str, start: float, duration: float,
                     char_offset: int = 0) -> list[WordTimestamp]:
    """Word timings inside one measured sentence.

    Weighted by word length rather than split evenly: "the" and
    "extraordinary" do not take the same time to say, and evenly-spaced
    timings visibly drag a cue away from its word on any sentence with a long
    word in it.
    """
    words = sentence.split()
    if not words:
        return []
    weights = [len(w) + 1 for w in words]      # +1 for the space after
    total = sum(weights) or 1
    out: list[WordTimestamp] = []
    t = start
    cursor = 0
    for w, weight in zip(words, weights):
        span = duration * weight / total
        idx = sentence.find(w, cursor)
        if idx < 0:
            idx = cursor
        cursor = idx + len(w)
        out.append(WordTimestamp(
            word=w,
            start=round(t, 4),
            end=round(t + span, 4),
            char_start=char_offset + idx,
            char_end=char_offset + idx + len(w),
        ))
        t += span
    return out


# --------------------------------------------------------------------------
# The synthesis seam.
# --------------------------------------------------------------------------


class LocalVoice(Protocol):
    """Turn one sentence into one audio file."""

    def say(self, text: str, out_path: Path) -> Path: ...


@dataclass
class PiperVoice:
    """Piper via its CLI. Not exercised by the suite — no Piper on this box.

    Piper reads text on stdin and writes a WAV, which is the whole contract;
    everything clever (sentence splitting, timing) happens above it.
    """

    binary: str
    model: str
    speaker: int | None = None
    use_cuda: bool = True

    def say(self, text: str, out_path: Path) -> Path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        args = [self.binary, "--model", self.model,
                "--output_file", str(out_path)]
        if self.speaker is not None:
            args += ["--speaker", str(self.speaker)]
        if self.use_cuda:
            args.append("--cuda")
        try:
            proc = subprocess.run(args, input=text.encode("utf-8"),
                                  capture_output=True, timeout=180, check=False)
        except FileNotFoundError as e:
            raise LocalTTSUnavailable(f"{self.binary} is not on PATH") from e
        except subprocess.TimeoutExpired as e:
            raise RenderError(f"local TTS timed out on {text[:40]!r}") from e
        if proc.returncode != 0 or not out_path.exists():
            detail = proc.stderr.decode("utf-8", "replace")[:300]
            # --cuda fails loudly on a box without the ONNX GPU provider; the
            # CPU voice is slower but still free and still listenable.
            if self.use_cuda and "cuda" in detail.lower():
                log.warning("local TTS: CUDA unavailable (%s) — falling back to CPU",
                            detail.strip()[:120])
                self.use_cuda = False
                return self.say(text, out_path)
            raise RenderError(f"local TTS failed ({proc.returncode}): {detail}")
        return out_path


def available(settings: Settings) -> tuple[bool, str]:
    """(usable, reason). Never raises, never synthesizes."""
    if not settings.local_tts_enabled:
        return False, "local TTS is switched off (LOCAL_TTS_ENABLED=false)."
    binary = settings.local_tts_binary or "piper"
    if shutil.which(binary) is None:
        return False, (f"{binary!r} is not on PATH — install Piper for free "
                       f"draft audio (drafts fall back to the mock hum).")
    model = settings.local_tts_model
    if not model:
        return False, "LOCAL_TTS_MODEL is not set (path to a .onnx voice)."
    if not Path(model).exists():
        return False, f"the local voice model is missing at {model}."
    return True, f"local TTS ready ({Path(model).stem})"


def build_voice(settings: Settings) -> LocalVoice:
    ok, why = available(settings)
    if not ok:
        raise LocalTTSUnavailable(why)
    return PiperVoice(
        binary=settings.local_tts_binary or "piper",
        model=settings.local_tts_model,
        speaker=settings.local_tts_speaker if settings.local_tts_speaker >= 0 else None,
        use_cuda=settings.local_tts_cuda and sys.platform != "darwin",
    )


# --------------------------------------------------------------------------
# The tier itself.
# --------------------------------------------------------------------------


@dataclass
class LocalSpeech:
    chunk_files: list[Path]
    words: list[WordTimestamp]


def synthesize_local(text: str, out_dir: Path, settings: Settings, *,
                     voice: LocalVoice | None = None) -> LocalSpeech:
    """Speak `text` locally, returning the pieces and real word timings.

    Returns the per-sentence files rather than one stitched track so the
    caller can reuse the engine's existing concat + offset logic, which is
    already the thing that gets chunk stitching right.
    """
    voice = voice or build_voice(settings)
    sentences = split_sentences(text)
    if not sentences:
        raise RenderError("nothing to speak")

    out_dir.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    words: list[WordTimestamp] = []
    t = 0.0
    search_from = 0

    for i, sentence in enumerate(sentences):
        wav = out_dir / f"local_{i:03d}.wav"
        voice.say(sentence, wav)
        m4a = out_dir / f"chunk_{i:03d}.m4a"
        # Normalised to the same container the paid tier produces, so nothing
        # downstream has to know which tier made it.
        run_ffmpeg(["-i", str(wav), "-ac", "1", "-ar", "44100",
                    "-c:a", "aac", "-b:a", "128k", str(m4a)])
        wav.unlink(missing_ok=True)
        duration = ffprobe_duration(m4a)

        # Character offsets must point into the ORIGINAL text: the timeline
        # resolves every visual cue through them, and a sentence-local offset
        # would put every cue after the first sentence in the wrong place.
        idx = text.find(sentence, search_from)
        if idx < 0:
            idx = search_from
        search_from = idx + len(sentence)

        words += distribute_words(sentence, t, duration, char_offset=idx)
        files.append(m4a)
        t += duration

    log.info("local TTS: %d sentence(s), %.1fs total", len(sentences), t)
    return LocalSpeech(chunk_files=files, words=words)


def draft_notice(reason: str = "") -> str:
    """What the operator is told, every time, so it can't be forgotten."""
    tail = f" ({reason})" if reason else ""
    return ("🎧 DRAFT AUDIO — a free local voice, not the real one. Word "
            "timings are exact per sentence and interpolated within one, so "
            "judge pacing and edit points, not lip-sync. The final render "
            "needs the paid voice." + tail)
