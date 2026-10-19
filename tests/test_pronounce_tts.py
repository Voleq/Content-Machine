"""A5: the spoken forms reach the paid request, and nothing else."""

import base64
import json

import httpx
import pytest

from pipeline.cost import SpendLedger
from pipeline.pronounce import add_rule
from pipeline.render_common import run_ffmpeg
from pipeline.tts import TTSEngine

TEXT = "Their EBITDA fell. The 10-K says why."


@pytest.fixture()
def live(settings, tmp_path):
    f = tmp_path / "tone.mp3"
    run_ffmpeg(["-f", "lavfi", "-i", "sine=frequency=300:duration=0.6",
                "-c:a", "libmp3lame", "-b:a", "64k", str(f)])
    audio = base64.b64encode(f.read_bytes()).decode()
    sent: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        text = json.loads(request.content)["text"]
        sent.append(text)
        n = len(text)
        return httpx.Response(200, json={"audio_base64": audio, "alignment": {
            "characters": list(text),
            "character_start_times_seconds": [i * 0.05 for i in range(n)],
            "character_end_times_seconds": [i * 0.05 + 0.05 for i in range(n)],
        }})

    s = settings.model_copy(update={"mock_mode": False,
                                    "elevenlabs_api_key": "test-key",
                                    "eleven_voice_id_long": "voiceX"})
    engine = TTSEngine(s, ledger=SpendLedger(s),
                       client=httpx.Client(transport=httpx.MockTransport(handler)))
    return s, engine, sent


def test_request_carries_the_spoken_form(live):
    s, engine, sent = live
    r = engine.synthesize(TEXT, "long")
    assert sent == ["Their ee-bit-dah fell. The 10-K says why."]
    assert [w.word for w in r.words] == ["Their", "EBITDA", "fell.", "The",
                                         "10-K", "says", "why."]
    for w in r.words:
        assert TEXT[w.char_start:w.char_end] == w.word


def test_rule_added_after_voice_keeps_cache(live):
    s, engine, sent = live
    engine.synthesize(TEXT, "long")
    chars = engine.billable_chars(TEXT, "long")
    add_rule(s, "10-K", "ten K")
    assert engine.is_cached(TEXT, "long"), "a list change never re-bills"
    assert engine.billable_chars(TEXT, "long") == chars
    again = engine.synthesize(TEXT, "long")
    assert again.cached and len(sent) == 1


def test_new_script_uses_rules(live):
    s, engine, sent = live
    add_rule(s, "10-K", "ten K")
    engine.synthesize("The 10-K is long.", "long")
    assert sent == ["The ten K is long."]


def test_a_voice_made_before_the_list_is_still_found(live):
    s, engine, sent = live
    engine.synthesize("Plain words only.", "long")
    add_rule(s, "Plain", "playn")
    assert engine.is_cached("Plain words only.", "long")


def test_mock_and_local_get_no_rules(settings):
    engine = TTSEngine(settings)
    assert engine._cache_dir(TEXT, "long", None, False)[2] == TEXT
