"""ElevenLabs TTS with timestamps, content-hash caching and hard budgets (§6).

One public entry point: `TTSEngine.synthesize(text, fmt)`.

Invariants enforced here:
  * character budget checked BEFORE anything else (BudgetExceededError)
  * cache key = sha256(voice_id | model | settings | text) — re-running
    unchanged content makes ZERO paid calls (§2.4)
  * monthly spend cap checked before a real API call (SpendCapExceededError)
  * LONG text is chunked by paragraph, synthesized per-chunk, stitched with
    exact ffprobe chunk durations; word timestamps carry both time offsets
    and char offsets into the ORIGINAL clean text
  * MOCK_MODE generates deterministic ffmpeg audio + linear timestamps —
    zero network, realistic durations
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
from pathlib import Path

import httpx

from config import Settings
from pipeline.cost import BudgetExceededError, SpendLedger, estimate_tts_usd
from pipeline.direction import (V3_MODELS, emission, performs_audio_tags,
                                setting_overrides)
from pipeline.models import TTSResult, WordTimestamp
from pipeline.render_common import concat_audio, ffprobe_duration, run_ffmpeg

log = logging.getLogger(__name__)


class TTSError(Exception):
    pass


class PaidVoiceForbidden(TTSError):
    """A job that guarantees $0 tried to reach the paid voice.

    The guarantee has to be structural, the way SpendLedger.guard_tts_spend is
    — a mode that is free by convention is one mistyped command away from a
    bill. Any caller passing `free_only=True` gets an exception here instead of
    an ElevenLabs request, and it is raised BEFORE the HTTP call, not after.
    """


# --------------------------------------------------------------------------
# Pure helpers (unit-tested directly).
# --------------------------------------------------------------------------

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+")


def chunk_text(text: str, max_chars: int) -> list[str]:
    """Split into <=max_chars chunks on paragraph, then sentence boundaries.

    Guarantee: ``"".join(chunks) == text`` — char offsets accumulate exactly.
    """
    if len(text) <= max_chars:
        return [text]

    # split keeping separators attached to the piece before them
    pieces: list[str] = []
    for para in re.split(r"(\n{2,})", text):
        if not para:
            continue
        if pieces and para.startswith("\n"):
            pieces[-1] += para
        else:
            pieces.append(para)

    # explode any oversized piece on sentence boundaries (separator kept)
    atoms: list[str] = []
    for piece in pieces:
        if len(piece) <= max_chars:
            atoms.append(piece)
            continue
        last = 0
        for m in _SENTENCE_SPLIT_RE.finditer(piece):
            atoms.append(piece[last:m.end()])
            last = m.end()
        if last < len(piece):
            atoms.append(piece[last:])

    chunks: list[str] = []
    current = ""
    for atom in atoms:
        # hard-split pathological atoms (no sentence breaks at all)
        while len(atom) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(atom[:max_chars])
            atom = atom[max_chars:]
        if len(current) + len(atom) <= max_chars:
            current += atom
        else:
            chunks.append(current)
            current = atom
    if current:
        chunks.append(current)

    assert "".join(chunks) == text, "chunking must preserve the text exactly"
    return chunks


def words_from_alignment(text: str, alignment: dict) -> list[WordTimestamp]:
    """ElevenLabs character alignment -> word-level timestamps.

    `alignment` holds parallel arrays: characters,
    character_start_times_seconds, character_end_times_seconds. Characters
    mirror the request text, so indices double as char offsets.
    """
    chars: list[str] = alignment["characters"]
    starts: list[float] = alignment["character_start_times_seconds"]
    ends: list[float] = alignment["character_end_times_seconds"]
    words: list[WordTimestamp] = []
    w_start_idx: int | None = None
    for i, ch in enumerate(chars + [" "]):  # sentinel space flushes last word
        if ch.isspace():
            if w_start_idx is not None:
                words.append(
                    WordTimestamp(
                        word="".join(chars[w_start_idx:i]),
                        start=float(starts[w_start_idx]),
                        end=float(ends[i - 1]),
                        char_start=w_start_idx,
                        char_end=i,
                    )
                )
                w_start_idx = None
        elif w_start_idx is None:
            w_start_idx = i
    return words


# --------------------------------------------------------------------------
# Delivery direction (§expressivity).
# --------------------------------------------------------------------------

# Deadpan comedy is timing, and the pipeline used to send plain stripped text
# with none of it. These directives are stripped from the captions and
# re-inserted into the TTS request only.
#
# WHAT each tag becomes lives in pipeline/direction.py — one table, per model
# tier — so that a model switch is never a content change and the vocabulary
# has exactly one definition. This module decides WHERE the direction goes and
# WHETHER the voice about to speak can perform it.
#
# The rule the table exists to keep: never emit a control the thing doing the
# speaking cannot honour. An unsupported bracket tag is read aloud, and so is
# an SSML break.
#
# V3_MODELS and performs_audio_tags are re-exported from here because this is
# where callers have always looked for them.
__all__ = ["V3_MODELS", "performs_audio_tags", "expand_delivery",
           "remap_to_clean", "delivery_fingerprint", "TTSEngine"]


def expand_delivery(clean_text: str, events, model_id: str,
                    tier: str = "paid") -> tuple[str, dict, list[tuple[int, int]]]:
    """Re-insert delivery direction into the text bound for TTS.

    Returns (tts_text, voice_setting_overrides, inserted_spans). The captions
    keep the clean text, so nothing here can reach the screen.

    `inserted_spans` are [start, end) into tts_text — exactly the characters
    this function added. `remap_to_clean` needs them to put the alignment back
    on the clean text: searching for the words instead is what let a tag whose
    word also appears in the prose ("curious", "quiet", "flat") match real
    text and mis-index every visual cue after it.

    `tier` is which voice is about to speak, and it is not the same question as
    which model is configured. Only the paid tier performs ANY of this. The
    free local voice is Piper, which honours neither audio tags nor SSML and
    reads both out loud — so a [BEAT] in a draft was audibly "break time zero
    point six s" for as long as this function only looked at the model id.
    """
    from pipeline.models import DELIVERY_TAG_TYPES

    directives = [e for e in (events or []) if e.type in DELIVERY_TAG_TYPES]
    if not directives or tier != "paid":
        return clean_text, {}, []

    pieces: list[str] = []
    spans: list[tuple[int, int]] = []
    overrides: dict = {}
    cursor = 0
    out_len = 0
    for e in sorted(directives, key=lambda e: e.char_offset):
        offset = min(max(e.char_offset, 0), len(clean_text))
        if offset < cursor:                  # overlapping offsets: keep the prose
            continue
        segment = clean_text[cursor:offset]
        pieces.append(segment)
        out_len += len(segment)
        cursor = offset

        # The register tags ([FLAT], [DRY]) are the only ones that can move the
        # sliders, and on v3 they must not — see direction.Register.
        overrides.update(setting_overrides(e.type, model_id))

        emitted = emission(e.type, model_id)
        if not emitted:
            continue
        # Always whitespace-separated. The alignment splits words on
        # whitespace, so this is what guarantees an inserted tag is its own
        # token rather than glued to the word before it — which in turn is what
        # makes "inside an inserted span" and "is a directive fragment" the
        # same statement in remap_to_clean.
        if out_len and not pieces[-1][-1:].isspace():
            emitted = " " + emitted
        pieces.append(emitted)
        spans.append((out_len, out_len + len(emitted)))
        out_len += len(emitted)
    pieces.append(clean_text[cursor:])
    return "".join(pieces), overrides, spans


def delivery_fingerprint(events) -> str:
    """A stable signature of the direction a script declares.

    It goes in the cache key on EVERY tier, and it has to, because the request
    text no longer carries the direction on all of them: the local and mock
    voices are handed the clean script (they can perform none of it), so
    keying on the request alone would let a draft of "the line." and a draft of
    "the line. [SIGH]" share one cache entry, and the second would silently
    return the first. What the operator is checking in a draft is the script,
    and the direction is part of the script.
    """
    from pipeline.models import DELIVERY_TAG_TYPES

    marks = sorted(
        (int(getattr(e, "char_offset", 0)), e.type.value)
        for e in (events or []) if e.type in DELIVERY_TAG_TYPES
    )
    return ";".join(f"{off}:{name}" for off, name in marks)


def remap_to_clean(words: list[WordTimestamp], clean_text: str,
                   spans: list[tuple[int, int]] | None = None) -> list[WordTimestamp]:
    """Re-index word char offsets onto the CLEAN text.

    Alignment offsets mirror the request, which carries the delivery direction
    the clean text does not. The timeline resolves every visual cue through
    these offsets, so leaving them pointing at the request text would drift
    every visual in the video.

    Given `spans` — what expand_delivery actually inserted — this is exact
    arithmetic: a word inside an inserted span is a directive fragment and is
    dropped, and every other word shifts back by the length of the insertions
    before it. Nothing is searched for.

    That matters because the fallback below searches. `clean_text.find(w.word,
    cursor)` cannot tell a tag's word from the same word in the prose, so a
    script carrying `[CURIOUS]` and the sentence "a genuinely curious business"
    would map the tag fragment onto the real word, advance the cursor past it,
    and mis-index every cue after that point. The search remains only for
    callers with no spans to give.
    """
    if spans is not None:
        return _remap_by_spans(words, spans)

    out: list[WordTimestamp] = []
    cursor = 0
    for w in words:
        idx = clean_text.find(w.word, cursor)
        if idx < 0:
            continue
        out.append(w.model_copy(update={"char_start": idx,
                                        "char_end": idx + len(w.word)}))
        cursor = idx + len(w.word)
    return out


def _remap_by_spans(words: list[WordTimestamp],
                    spans: list[tuple[int, int]]) -> list[WordTimestamp]:
    """Request offsets -> clean offsets, by subtracting what was inserted."""
    ordered = sorted(spans)
    out: list[WordTimestamp] = []
    for w in words:
        shift = 0
        dropped = False
        for lo, hi in ordered:
            if hi <= w.char_start:
                shift += hi - lo          # entirely before this word
            elif lo < w.char_end:
                dropped = True            # overlaps: a directive fragment
                break
        if dropped:
            continue
        out.append(w.model_copy(update={"char_start": w.char_start - shift,
                                        "char_end": w.char_end - shift}))
    return out


def mock_words(text: str, duration: float, lead_in: float = 0.15) -> list[WordTimestamp]:
    """Deterministic linear word timing weighted by word length."""
    spans: list[tuple[int, int]] = []
    for m in re.finditer(r"\S+", text):
        spans.append((m.start(), m.end()))
    if not spans:
        return []
    speak_time = max(duration - lead_in, 0.001)
    total_weight = sum(end - start + 1 for start, end in spans)
    words: list[WordTimestamp] = []
    t = lead_in
    for start, end in spans:
        share = (end - start + 1) / total_weight * speak_time
        words.append(
            WordTimestamp(
                word=text[start:end],
                start=round(t, 4),
                end=round(t + share, 4),
                char_start=start,
                char_end=end,
            )
        )
        t += share
    return words


def cache_key(voice_id: str, model_id: str, voice_settings: dict, text: str) -> str:
    payload = "|".join([
        voice_id,
        model_id,
        json.dumps(voice_settings, sort_keys=True),
        text,
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# Engine.
# --------------------------------------------------------------------------


class TTSEngine:
    def __init__(
        self,
        settings: Settings,
        ledger: SpendLedger | None = None,
        client: httpx.Client | None = None,
    ):
        self.settings = settings
        self.ledger = ledger or SpendLedger(settings)
        self._client = client  # injectable for tests (httpx.MockTransport)

    # ------------------------------------------------------------------ API
    def tier_for(self, draft: bool) -> str:
        """Which of mock | local | paid a request resolves to (P3.2).

        MOCK_MODE still wins outright — the hard guarantee is that mock mode
        is offline and $0, and a local voice, free as it is, is a subprocess
        and a model file that a test run must not depend on. MOCK_TTS mocks
        just this one, so prices and the screener can stay live.
        """
        if self.settings.mocking_tts:
            return "mock"
        if not draft:
            return "paid"
        from pipeline.local_tts import available

        ok, why = available(self.settings)
        if ok:
            return "local"
        # A draft must never silently escalate to a paid generation.
        log.info("local TTS unavailable (%s) — draft falls back to mock", why)
        return "mock"

    def guard_free_only(self, tier: str) -> None:
        """Raise unless `tier` is one of the free ones.

        The boundary a $0 mode is enforced at. tier_for() already refuses to
        escalate a draft, so reaching this with "paid" means something above
        changed — which is exactly when an assertion is worth having, and
        exactly when a comment promising $0 is not.
        """
        if tier == "paid":
            raise PaidVoiceForbidden(
                f"this job guarantees $0 and may not use the paid voice "
                f"(resolved tier: {tier}). Nothing was sent to ElevenLabs."
            )

    def is_cached(self, text: str, fmt: str, *, events=None,
                  draft: bool = False) -> bool:
        """Would synthesize() be free? (drives the §9.3 cost report)"""
        return self._cache_dir(text, fmt, events, draft)[0].exists()

    def _cache_dir(self, text: str, fmt: str, events, draft: bool):
        """(audio_path's dir marker, cdir, request text, ids) for one request.

        The tier is part of the key. Without it a draft's local audio would
        satisfy the final's cache lookup and the paid voice would never be
        called — the failure mode being a "final" that shipped draft audio.
        """
        voice_id = self.settings.voice_id(fmt) or f"mock-voice-{fmt}"
        model_id = self.settings.active_eleven_model
        vsettings = dict(self.settings.voice_settings(fmt))
        # The tier is resolved FIRST because it decides whether any direction
        # is emitted at all: the local and mock voices perform none of it and
        # would speak whatever they were handed.
        tier = self.tier_for(draft)
        req_text, overrides, spans = expand_delivery(text, events, model_id,
                                                     tier=tier)
        vsettings.update(overrides)
        keyed = dict(vsettings)
        fingerprint = delivery_fingerprint(events)
        if fingerprint:
            keyed["_delivery"] = fingerprint
        if tier != "paid":
            keyed["_tier"] = tier
        key = cache_key(voice_id, model_id, keyed, req_text)
        cdir = self.settings.cache_dir / "tts" / key
        marker = cdir / "audio.m4a"
        return (marker if (cdir / "words.json").exists() else cdir / "__absent__",
                cdir, req_text, voice_id, model_id, vsettings, tier, spans)

    def synthesize(self, text: str, fmt: str, *, events=None,
                   draft: bool = False, free_only: bool = False) -> TTSResult:
        """text must be the CLEAN script (tags stripped). fmt: short|long.

        `events` carries the script's delivery direction ([BEAT], [SIGH],
        [FLAT], [DRY]). Those change the request text and the voice settings,
        and therefore the cache key — which is exactly why they have to be
        authored BEFORE the paid generation rather than added afterwards.

        `draft=True` asks for the free tier: the local neural voice when the
        box has one, the mock hum otherwise. It never reaches ElevenLabs, and
        what it returns is marked `draft` so a final render can refuse it.

        `free_only=True` makes that a guarantee rather than a consequence: the
        call fails loudly instead of spending if the tier ever resolves to
        paid. Callers whose whole promise to the operator is "$0" pass it.
        """
        if fmt not in ("short", "long"):
            raise ValueError(f"fmt must be short|long, got {fmt!r}")
        if free_only:
            # Before the budget check and before the cache probe: a $0 job must
            # not get as far as deciding how much it would have cost.
            self.guard_free_only(self.tier_for(draft))
        budget = self.settings.max_chars(fmt)
        if len(text) > budget:
            raise BudgetExceededError(
                f"{fmt.upper()} script is {len(text)} chars, budget is {budget}. "
                f"No TTS was called."
            )

        clean_text = text
        _, cdir, text, voice_id, model_id, vsettings, tier, spans = self._cache_dir(
            clean_text, fmt, events, draft)
        audio_path = cdir / "audio.m4a"
        words_path = cdir / "words.json"

        if audio_path.exists() and words_path.exists():
            words = [WordTimestamp(**w) for w in json.loads(words_path.read_text(encoding="utf-8"))]
            return TTSResult(
                audio_path=audio_path,
                words=words,
                duration_s=ffprobe_duration(audio_path),
                chars=len(text),
                cached=True,
                cost_usd=0.0,
                tier=tier,
                draft=tier == "local",
            )

        cdir.mkdir(parents=True, exist_ok=True)
        chunks = chunk_text(text, self.settings.tts_chunk_chars)
        log.info("TTS generate: %s chars in %d chunk(s), tier=%s",
                 len(text), len(chunks), tier)

        cost_usd = 0.0
        if tier == "local":
            chunk_files, chunk_words = self._generate_local(text, cdir)
            chunks = [text]          # the local tier splits by sentence itself
        elif tier == "mock":
            chunk_files, chunk_words = self._generate_mock(chunks, fmt, cdir)
        else:
            # The boundary itself. Unreachable through tier_for(), which is
            # the point: this is the last statement before money is spent, so
            # it is where the $0 promise is worth asserting rather than
            # trusting the two branches above to have stayed correct.
            if free_only:
                self.guard_free_only(tier)
            # Code-level spend gate (the operator Approve is the human gate).
            # This is the whole-generation cap check — would this job, in
            # total, blow the month? The RECORDING happens per chunk inside
            # `_generate_real`, because a nine-chunk LONG that dies on chunk
            # five has already been billed for five (A1).
            self.ledger.guard_tts_spend(len(text))
            chunk_files, chunk_words, cost_usd = self._generate_real(
                chunks, voice_id, model_id, vsettings, cdir
            )

        # stitch chunks: offset each chunk's word times by the exact summed
        # durations of prior chunks, and char offsets by prior chunk lengths
        words: list[WordTimestamp] = []
        t_offset = 0.0
        c_offset = 0
        for chunk_text_, cfile, cwords in zip(chunks, chunk_files, chunk_words):
            for w in cwords:
                words.append(
                    WordTimestamp(
                        word=w.word,
                        start=round(w.start + t_offset, 4),
                        end=round(w.end + t_offset, 4),
                        char_start=w.char_start + c_offset,
                        char_end=w.char_end + c_offset,
                    )
                )
            t_offset += ffprobe_duration(cfile)
            c_offset += len(chunk_text_)

        concat_audio(chunk_files, audio_path, self.settings)
        for f in chunk_files:
            if f != audio_path:
                f.unlink(missing_ok=True)
                # The per-chunk sidecar exists so a FAILED run can resume
                # (A1). Once the stitch is done its job is over, and leaving
                # it would let a later run resume against chunks whose text
                # no longer matches.
                f.with_suffix(".words.json").unlink(missing_ok=True)

        # Alignment offsets mirror the REQUEST, which carries break tags the
        # clean script does not. The timeline resolves every visual cue
        # through these offsets, so put them back on the clean text.
        if clean_text != text:
            words = remap_to_clean(words, clean_text, spans)

        duration = ffprobe_duration(audio_path)
        words_path.write_text(json.dumps([w.model_dump() for w in words]), encoding="utf-8")
        (cdir / "meta.json").write_text(json.dumps({
            "voice_id": voice_id,
            "model_id": model_id,
            "voice_settings": vsettings,
            "chars": len(text),
            "chunks": len(chunks),
            "tier": tier,
            "mock": self.settings.mock_mode,
            "cost_usd": cost_usd,
        }, indent=2), encoding="utf-8")

        return TTSResult(
            audio_path=audio_path,
            words=words,
            duration_s=duration,
            chars=len(text),
            cached=False,
            cost_usd=cost_usd,
            tier=tier,
            draft=tier == "local",
        )

    # ----------------------------------------------------------------- local
    def _generate_local(
        self, text: str, cdir: Path
    ) -> tuple[list[Path], list[list[WordTimestamp]]]:
        """The free draft voice. One "chunk" — it splits by sentence itself.

        Its words are already absolute across the whole text, so they come
        back as a single chunk and the caller's per-chunk offsetting adds
        nothing to them.
        """
        from pipeline.local_tts import synthesize_local

        speech = synthesize_local(text, cdir, self.settings)
        joined = cdir / "local_joined.m4a"
        concat_audio(speech.chunk_files, joined, self.settings)
        for f in speech.chunk_files:
            f.unlink(missing_ok=True)
        return [joined], [speech.words]

    # ------------------------------------------------------------------ mock
    def _generate_mock(
        self, chunks: list[str], fmt: str, cdir: Path
    ) -> tuple[list[Path], list[list[WordTimestamp]]]:
        wps = self.settings.mock_wps_short if fmt == "short" else self.settings.mock_wps_long
        files: list[Path] = []
        words: list[list[WordTimestamp]] = []
        for i, chunk in enumerate(chunks):
            n_words = max(len(chunk.split()), 1)
            duration = max(n_words / wps, 0.8)
            f = cdir / f"chunk_{i:03d}.m4a"
            # A deterministic placeholder in the SPEECH BAND, not a hum.
            #
            # This used to be a single 155 Hz sine. Almost all of its energy
            # sat below 200 Hz, so `loudnorm` measured a near-silent programme
            # and raised it ~30 dB, which pushed inaudible sub-bass into the
            # limiter: the render measured 0.0 LUFS integrated with a -0.9 dB
            # peak and played as silence. Three harmonics through a
            # telephone-band filter land where a voice lands, so the mix reads
            # like speech to both the ear and the loudness meter.
            run_ffmpeg([
                "-f", "lavfi",
                "-i", f"sine=frequency=210:sample_rate=44100:duration={duration:.3f}",
                "-f", "lavfi",
                "-i", f"sine=frequency=620:sample_rate=44100:duration={duration:.3f}",
                "-f", "lavfi",
                "-i", f"sine=frequency=1450:sample_rate=44100:duration={duration:.3f}",
                "-filter_complex",
                (f"[0:a]volume=0.5[a0];[1:a]volume=0.8[a1];[2:a]volume=0.4[a2];"
                 f"[a0][a1][a2]amix=inputs=3:normalize=0,"
                 f"highpass=f=180,lowpass=f=3400,"
                 f"tremolo=f={wps:.2f}:d=0.85,volume=0.62[out]"),
                "-map", "[out]",
                "-c:a", "aac", "-b:a", "128k", str(f),
            ])
            files.append(f)
            words.append(mock_words(chunk, ffprobe_duration(f)))
        return files, words

    # ------------------------------------------------------------------ real
    @staticmethod
    def _chunk_paths(cdir: Path, i: int) -> tuple[Path, Path]:
        """Audio and its word-timing sidecar for chunk `i`.

        The sidecar is what makes a resume possible: an mp3 on its own says
        a request was PAID for, not that its alignment survived, and a
        resumed run has to stitch with real word times or the picture drifts
        off the voice for the whole back half.
        """
        return cdir / f"chunk_{i:03d}.mp3", cdir / f"chunk_{i:03d}.words.json"

    def _generate_real(
        self,
        chunks: list[str],
        voice_id: str,
        model_id: str,
        vsettings: dict,
        cdir: Path,
    ) -> tuple[list[Path], list[list[WordTimestamp]], float]:
        """Generate every chunk, metering and resuming per chunk.

        Two properties this has to hold, and the old shape held neither:

        1. **Spend is recorded as it happens.** ElevenLabs bills the chunk
           it answered, not the loop that was going to follow it. Recording
           once after the loop meant a timeout on chunk five reported $0
           spent for five paid generations — and the monthly cap is the only
           hard stop in the system, so under-metering it is the expensive
           direction.
        2. **A retry does not re-pay.** Every chunk that already has both
           its audio and its alignment on disk is reused, so the retry picks
           up where the failure was rather than at zero.

        Returns `(files, words, cost_usd)` where `cost_usd` is the ACTUAL
        cost of what this call generated — a fully resumed run costs $0 and
        says so.
        """
        if not self.settings.elevenlabs_api_key:
            raise TTSError("ELEVENLABS_API_KEY is not set and MOCK_MODE is off.")
        client = self._client or httpx.Client(timeout=120)
        files: list[Path] = []
        words: list[list[WordTimestamp]] = []
        cost_usd = 0.0
        try:
            for i, chunk in enumerate(chunks):
                f, wf = self._chunk_paths(cdir, i)
                if f.exists() and f.stat().st_size > 0 and wf.exists():
                    try:
                        cached = [WordTimestamp(**w) for w in
                                  json.loads(wf.read_text(encoding="utf-8"))]
                    except (json.JSONDecodeError, TypeError, ValueError) as e:
                        # A half-written sidecar is not evidence of anything;
                        # re-request rather than stitch against garbage.
                        log.warning("chunk %d sidecar unreadable (%s) — "
                                    "regenerating", i, e)
                    else:
                        log.info("TTS chunk %d/%d already generated — resuming, "
                                 "not re-paying", i + 1, len(chunks))
                        files.append(f)
                        words.append(cached)
                        continue

                url = (
                    f"{self.settings.eleven_base_url}/v1/text-to-speech/"
                    f"{voice_id}/with-timestamps"
                )
                resp = client.post(
                    url,
                    params={"output_format": "mp3_44100_128"},
                    headers={"xi-api-key": self.settings.elevenlabs_api_key},
                    json={
                        "text": chunk,
                        "model_id": model_id,
                        "voice_settings": vsettings,
                    },
                )
                if resp.status_code != 200:
                    raise TTSError(
                        f"ElevenLabs error {resp.status_code}: {resp.text[:300]}"
                    )
                payload = resp.json()
                f.write_bytes(base64.b64decode(payload["audio_base64"]))
                cwords = words_from_alignment(chunk, payload["alignment"])
                wf.write_text(json.dumps([w.model_dump() for w in cwords]),
                              encoding="utf-8")
                # Recorded HERE, against this chunk's own character count,
                # before anything downstream can raise. The cap is metered on
                # what was actually billed.
                spent = estimate_tts_usd(len(chunk), self.settings)
                self.ledger.record_tts(spent)
                cost_usd += spent
                files.append(f)
                words.append(cwords)
        finally:
            if self._client is None:
                client.close()
        return files, words, cost_usd
