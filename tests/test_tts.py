import base64
import json

import httpx
import pytest

from pipeline.cost import BudgetExceededError, SpendCapExceededError, SpendLedger
from pipeline.render_common import ffprobe_duration, run_ffmpeg
from pipeline.tts import (
    TTSEngine,
    cache_key,
    chunk_text,
    mock_words,
    words_from_alignment,
)

# ------------------------------------------------------------------ chunking


def test_chunk_short_text_is_single():
    assert chunk_text("hello world", 100) == ["hello world"]


def test_chunk_join_identity_paragraphs():
    text = ("Para one is here. More of it.\n\n" * 10) + "Tail paragraph."
    chunks = chunk_text(text, 120)
    assert "".join(chunks) == text
    assert all(len(c) <= 120 for c in chunks)
    assert len(chunks) > 1


def test_chunk_oversized_paragraph_splits_on_sentences():
    text = "One sentence here. " * 30  # single paragraph, ~570 chars
    chunks = chunk_text(text, 100)
    assert "".join(chunks) == text
    assert all(len(c) <= 100 for c in chunks)


def test_chunk_pathological_no_breaks():
    text = "x" * 350
    chunks = chunk_text(text, 100)
    assert "".join(chunks) == text
    assert max(len(c) for c in chunks) <= 100


# ------------------------------------------------------- alignment -> words


def test_words_from_alignment_fixture(alignment_sample):
    words = words_from_alignment(alignment_sample["text"], alignment_sample["alignment"])
    assert [w.word for w in words] == ["The", "market", "pays", "sixty", "times", "sales."]
    text = alignment_sample["text"]
    for w in words:
        assert text[w.char_start:w.char_end] == w.word
    starts = [w.start for w in words]
    assert starts == sorted(starts)
    assert words[0].start >= 0.2  # fixture has a lead-in


def test_mock_words_spans_and_monotonic():
    text = "Alpha beta  gamma."
    words = mock_words(text, duration=3.0)
    assert [w.word for w in words] == ["Alpha", "beta", "gamma."]
    for w in words:
        assert text[w.char_start:w.char_end] == w.word
    assert words[-1].end == pytest.approx(3.0, abs=0.01)


# ------------------------------------------------------------------- caching


def test_cache_key_sensitivity():
    base = cache_key("v1", "m1", {"stability": 0.5}, "hello")
    assert cache_key("v1", "m1", {"stability": 0.5}, "hello") == base
    assert cache_key("v2", "m1", {"stability": 0.5}, "hello") != base
    assert cache_key("v1", "m2", {"stability": 0.5}, "hello") != base
    assert cache_key("v1", "m1", {"stability": 0.6}, "hello") != base
    assert cache_key("v1", "m1", {"stability": 0.5}, "hello!") != base


def test_mock_synthesize_and_cache_hit(settings):
    engine = TTSEngine(settings)
    text = "The market pays sixty times sales for this company. It is not printing money."
    r1 = engine.synthesize(text, "short")
    assert r1.audio_path.exists()
    assert not r1.cached and r1.cost_usd == 0.0
    n_words = len(text.split())
    assert len(r1.words) == n_words
    # duration ~ words/wps
    assert r1.duration_s == pytest.approx(n_words / settings.mock_wps_short, rel=0.25)
    # word char spans index the original text
    for w in r1.words:
        assert text[w.char_start:w.char_end] == w.word

    mtime = r1.audio_path.stat().st_mtime_ns
    r2 = engine.synthesize(text, "short")
    assert r2.cached and r2.cost_usd == 0.0
    assert r2.audio_path.stat().st_mtime_ns == mtime, "cache hit must not regenerate"
    assert [w.word for w in r2.words] == [w.word for w in r1.words]


def test_budget_rejected_before_anything(settings):
    engine = TTSEngine(settings)
    with pytest.raises(BudgetExceededError, match="budget"):
        engine.synthesize("x " * settings.short_max_chars, "short")


def test_chunked_long_offsets(settings):
    small = settings.model_copy(update={"tts_chunk_chars": 150})
    engine = TTSEngine(small)
    text = (
        "First paragraph with several words in it. It keeps going for a while.\n\n"
        "Second paragraph continues the narration with more words.\n\n"
        "Third paragraph closes the argument. The verdict is unchanged."
    )
    assert len(chunk_text(text, 150)) > 1
    r = engine.synthesize(text, "long")
    assert len(r.words) == len(text.split())
    for w in r.words:
        assert text[w.char_start:w.char_end] == w.word, "char offsets must span chunks"
    starts = [w.start for w in r.words]
    assert starts == sorted(starts), "times must be monotonic across chunk stitches"
    assert r.duration_s > 5


# ---------------------------------------------------------------- real path


def _tiny_mp3_b64(tmp_path) -> str:
    f = tmp_path / "tone.mp3"
    run_ffmpeg([
        "-f", "lavfi", "-i", "sine=frequency=300:duration=0.6",
        "-c:a", "libmp3lame", "-b:a", "64k", str(f),
    ])
    return base64.b64encode(f.read_bytes()).decode()


def test_real_api_path_with_mock_transport(settings, alignment_sample, tmp_path):
    audio_b64 = _tiny_mp3_b64(tmp_path)
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert "with-timestamps" in str(request.url)
        assert request.headers["xi-api-key"] == "test-key"
        return httpx.Response(200, json={
            "audio_base64": audio_b64,
            "alignment": alignment_sample["alignment"],
        })

    live = settings.model_copy(update={
        "mock_mode": False,
        "elevenlabs_api_key": "test-key",
        "eleven_voice_id_short": "voiceX",
    })
    client = httpx.Client(transport=httpx.MockTransport(handler))
    ledger = SpendLedger(live)
    engine = TTSEngine(live, ledger=ledger, client=client)

    text = alignment_sample["text"]
    r = engine.synthesize(text, "short")
    assert len(calls) == 1
    assert r.cost_usd > 0
    assert ledger.mtd_spend_usd() == pytest.approx(r.cost_usd)
    assert [w.word for w in r.words][:2] == ["The", "market"]
    assert r.audio_path.exists() and r.duration_s > 0

    # unchanged content => zero paid calls (§2.4)
    r2 = engine.synthesize(text, "short")
    assert r2.cached and len(calls) == 1
    assert ledger.mtd_spend_usd() == pytest.approx(r.cost_usd)


def test_real_path_blocked_by_spend_cap(settings, alignment_sample):
    live = settings.model_copy(update={
        "mock_mode": False,
        "elevenlabs_api_key": "test-key",
        "monthly_spend_cap_usd": 0.0001,
    })

    def handler(request):  # pragma: no cover - must never be reached
        raise AssertionError("paid call attempted despite spend cap")

    engine = TTSEngine(live, client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(SpendCapExceededError):
        engine.synthesize(alignment_sample["text"], "short")


def test_real_path_requires_api_key(settings):
    live = settings.model_copy(update={"mock_mode": False})
    engine = TTSEngine(live)
    with pytest.raises(Exception, match="ELEVENLABS_API_KEY"):
        engine.synthesize("hello there", "short")


def test_re_rendering_the_same_approved_script_costs_nothing(
        settings, alignment_sample, tmp_path):
    """The operator renders the same script repeatedly to fix placement.

    Nothing consumes `is_approved()` on render — the approval is a content
    hash and `/render TICKER` runs again — so the only thing standing between
    a fifth pass at visual placement and a fifth TTS bill is the cache. It is
    keyed on the script's own content, global, and never pruned, which is what
    makes the second run $0.

    The things an operator changes BETWEEN those passes are deliberately
    outside the key: a kit rebuild, a plate manifest, `CHAPTER_CUE_SFX`, a
    `hold=` on a tag. None of them changes a word that is spoken, so none of
    them may re-bill the voice.
    """
    audio_b64 = _tiny_mp3_b64(tmp_path)
    calls: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={
            "audio_base64": audio_b64,
            "alignment": alignment_sample["alignment"],
        })

    live = settings.model_copy(update={
        "mock_mode": False,
        "elevenlabs_api_key": "test-key",
        "eleven_voice_id_long": "voiceX",
    })
    ledger = SpendLedger(live)
    text = alignment_sample["text"]

    def render_pass(s):
        engine = TTSEngine(s, ledger=ledger,
                           client=httpx.Client(transport=httpx.MockTransport(handler)))
        return engine.synthesize(text, "long")

    first = render_pass(live)
    assert len(calls) == 1 and first.cost_usd > 0
    spent = ledger.mtd_spend_usd()

    # A fresh engine — a separate `/render` invocation, in a separate process
    # as far as the cache is concerned.
    second = render_pass(live)
    assert second.cached and second.cost_usd == 0.0
    assert len(calls) == 1, "the second render bought the voice again"
    assert ledger.mtd_spend_usd() == pytest.approx(spent)
    assert second.audio_path == first.audio_path

    # …and the settings an operator actually changes between passes do not
    # touch the key.
    tuned = live.model_copy(update={"chapter_cue_sfx": "paper_rustle",
                                    "sfx_gain_db": -3.0})
    third = render_pass(tuned)
    assert third.cached and len(calls) == 1, \
        "a mix setting re-billed the voice — nothing spoken changed"


# --------------------------------------------------------------------------
# A1 — a part-failed generation is billed by ElevenLabs whether or not the
# loop finished, so the ledger has to know about it and the retry must not
# pay for it twice. Both assertions are on what the LEDGER SAYS and on how
# many requests actually left, not on the arguments of a call.
# --------------------------------------------------------------------------


def _live(settings, **extra):
    return settings.model_copy(update={
        "mock_mode": False,
        "elevenlabs_api_key": "test-key",
        "eleven_voice_id_long": "voiceL",
        "eleven_voice_id_short": "voiceL",
        "tts_chunk_chars": 60,
        **extra,
    })


def _multi_chunk_text() -> str:
    """Long enough to split into several chunks at tts_chunk_chars=60."""
    return ("The market pays sixty times sales. " * 12).strip()


def _handler_failing_at(audio_b64, alignment, fail_index: int, calls: list):
    def handler(request: httpx.Request) -> httpx.Response:
        i = len(calls)
        calls.append(request)
        if i == fail_index:
            return httpx.Response(429, text="slow down")
        return httpx.Response(200, json={"audio_base64": audio_b64,
                                         "alignment": alignment})
    return handler


def test_a_generation_that_dies_midway_still_meters_what_was_billed(
        settings, alignment_sample, tmp_path):
    """Chunks 0..N-1 were generated and billed. $0 spent is a lie."""
    audio_b64 = _tiny_mp3_b64(tmp_path)
    live = _live(settings)
    text = _multi_chunk_text()
    assert len(chunk_text(text, live.tts_chunk_chars)) >= 4, "need several chunks"

    calls: list = []
    engine = TTSEngine(live, ledger=SpendLedger(live), client=httpx.Client(
        transport=httpx.MockTransport(
            _handler_failing_at(audio_b64, alignment_sample["alignment"], 2, calls))))

    with pytest.raises(Exception):
        engine.synthesize(text, "long")

    assert len(calls) == 3, "two succeeded, the third is the failure"
    assert engine.ledger.mtd_spend_usd() > 0, \
        "two paid chunks came back — the cap must know about them"


def test_a_retry_resumes_instead_of_re_paying_for_finished_chunks(
        settings, alignment_sample, tmp_path):
    """`unchanged content => zero calls` has to survive a partial failure."""
    audio_b64 = _tiny_mp3_b64(tmp_path)
    alignment = alignment_sample["alignment"]
    live = _live(settings)
    text = _multi_chunk_text()
    n_chunks = len(chunk_text(text, live.tts_chunk_chars))

    calls: list = []
    ledger = SpendLedger(live)
    engine = TTSEngine(live, ledger=ledger, client=httpx.Client(
        transport=httpx.MockTransport(
            _handler_failing_at(audio_b64, alignment, 2, calls))))
    with pytest.raises(Exception):
        engine.synthesize(text, "long")
    spent_first = ledger.mtd_spend_usd()

    # Same settings, same cache dir, a transport that now answers everything.
    def ok(request):
        calls.append(request)
        return httpx.Response(200, json={"audio_base64": audio_b64,
                                         "alignment": alignment})

    engine2 = TTSEngine(live, ledger=ledger,
                        client=httpx.Client(transport=httpx.MockTransport(ok)))
    result = engine2.synthesize(text, "long")

    requests_on_retry = len(calls) - 3
    assert requests_on_retry == n_chunks - 2, (
        f"the retry re-requested {requests_on_retry} of {n_chunks} chunks; "
        f"the two already on disk should have been reused")
    assert result.audio_path.exists()
    assert ledger.mtd_spend_usd() > spent_first, "the rest of the job cost money"
    # and the reported cost is only the chunks actually generated this time
    assert result.cost_usd == pytest.approx(
        ledger.mtd_spend_usd() - spent_first)


def test_a_fully_resumed_generation_costs_nothing_more(
        settings, alignment_sample, tmp_path):
    audio_b64 = _tiny_mp3_b64(tmp_path)
    alignment = alignment_sample["alignment"]
    live = _live(settings)
    text = _multi_chunk_text()
    calls: list = []

    def ok(request):
        calls.append(request)
        return httpx.Response(200, json={"audio_base64": audio_b64,
                                         "alignment": alignment})

    ledger = SpendLedger(live)
    engine = TTSEngine(live, ledger=ledger,
                       client=httpx.Client(transport=httpx.MockTransport(ok)))
    first = engine.synthesize(text, "long")
    assert first.cost_usd > 0
    after_first = ledger.mtd_spend_usd()

    # The stitched result is cached, so the second call is free at the top
    # level — the property the README's "unchanged content => zero calls"
    # row is about, and it must survive the per-chunk bookkeeping.
    n = len(calls)
    second = engine.synthesize(text, "long")
    assert second.cached and len(calls) == n
    assert ledger.mtd_spend_usd() == pytest.approx(after_first)
