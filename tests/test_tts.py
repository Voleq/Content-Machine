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
