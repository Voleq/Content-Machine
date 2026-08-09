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
from pipeline.cost import BudgetExceededError, SpendLedger
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
# `<break>` is honoured by the v2/turbo models this pipeline uses. Bracketed
# audio tags like `[sighs]` are an eleven_v3 feature; on any other model they
# would be READ ALOUD, which is why SIGH degrades to a pause rather than
# gambling on support. That is the "degrade silently" rule: never emit a
# control the configured model cannot honour.
V3_MODELS = ("eleven_v3",)

DELIVERY_BREAKS = {
    "BEAT": 0.6,
    "SIGH": 0.4,   # without audio-tag support, a held pause is the honest read
}


def expand_delivery(clean_text: str, events, model_id: str) -> tuple[str, dict]:
    """Re-insert delivery direction into the text bound for TTS.

    Returns (tts_text, voice_setting_overrides). The captions keep the clean
    text, so nothing here can reach the screen.
    """
    from pipeline.models import DELIVERY_TAG_TYPES

    directives = [e for e in (events or []) if e.type in DELIVERY_TAG_TYPES]
    if not directives:
        return clean_text, {}

    supports_tags = any(m in (model_id or "") for m in V3_MODELS)
    pieces: list[str] = []
    cursor = 0
    overrides: dict = {}
    for e in sorted(directives, key=lambda e: e.char_offset):
        name = e.type.value
        offset = min(max(e.char_offset, 0), len(clean_text))
        pieces.append(clean_text[cursor:offset])
        cursor = offset
        if name in ("FLAT", "DRY"):
            # A register instruction, not an inline event: hold the whole
            # generation flatter. Stability up, style down.
            overrides["stability"] = 0.85
            overrides["style"] = 0.0
            continue
        if name == "SIGH" and supports_tags:
            pieces.append("[sighs] ")
            continue
        pieces.append(f'<break time="{DELIVERY_BREAKS[name]}s" /> ')
    pieces.append(clean_text[cursor:])
    return "".join(pieces), overrides


def remap_to_clean(words: list[WordTimestamp], clean_text: str) -> list[WordTimestamp]:
    """Re-index word char offsets onto the CLEAN text.

    Alignment offsets mirror the request, which now carries break tags the
    clean text does not have. The timeline resolves every visual cue through
    these offsets, so leaving them pointing at the request text would drift
    every tag in the video. Words that do not appear in the clean text are
    directive fragments and are dropped.
    """
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
        req_text, overrides = expand_delivery(text, events, model_id)
        vsettings.update(overrides)
        tier = self.tier_for(draft)
        keyed = dict(vsettings)
        if tier != "paid":
            keyed["_tier"] = tier
        key = cache_key(voice_id, model_id, keyed, req_text)
        cdir = self.settings.cache_dir / "tts" / key
        marker = cdir / "audio.m4a"
        return (marker if (cdir / "words.json").exists() else cdir / "__absent__",
                cdir, req_text, voice_id, model_id, vsettings, tier)

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
        _, cdir, text, voice_id, model_id, vsettings, tier = self._cache_dir(
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
            # code-level spend gate (the operator Approve is the human gate)
            est = self.ledger.guard_tts_spend(len(text))
            chunk_files, chunk_words = self._generate_real(
                chunks, voice_id, model_id, vsettings, cdir
            )
            self.ledger.record_tts(est)
            cost_usd = est

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

        # Alignment offsets mirror the REQUEST, which carries break tags the
        # clean script does not. The timeline resolves every visual cue
        # through these offsets, so put them back on the clean text.
        if clean_text != text:
            words = remap_to_clean(words, clean_text)

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
    def _generate_real(
        self,
        chunks: list[str],
        voice_id: str,
        model_id: str,
        vsettings: dict,
        cdir: Path,
    ) -> tuple[list[Path], list[list[WordTimestamp]]]:
        if not self.settings.elevenlabs_api_key:
            raise TTSError("ELEVENLABS_API_KEY is not set and MOCK_MODE is off.")
        client = self._client or httpx.Client(timeout=120)
        files: list[Path] = []
        words: list[list[WordTimestamp]] = []
        try:
            for i, chunk in enumerate(chunks):
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
                f = cdir / f"chunk_{i:03d}.mp3"
                f.write_bytes(base64.b64decode(payload["audio_base64"]))
                files.append(f)
                words.append(words_from_alignment(chunk, payload["alignment"]))
        finally:
            if self._client is None:
                client.close()
        return files, words
