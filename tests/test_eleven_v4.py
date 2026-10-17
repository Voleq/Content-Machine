"""Eleven v4: the narration model, at v3's price, with two voice settings.

What the ElevenLabs pages said on 2026-10-17: v4 and v3 both list at $0.08 per
1,000 characters; v4 performs the same audio tags; and "Both variants use two
voice settings: Stability and Similarity ... Style and Speed sliders are not
available in Eleven v4".
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import httpx
import pytest

from pipeline.cost import SpendLedger
from pipeline.models import TagType
from pipeline.tts import TTSEngine, expand_delivery

ROOT = Path(__file__).resolve().parents[1]


class _Ev:
    def __init__(self, type_, offset):
        self.type = type_
        self.char_offset = offset


def test_v4_costs_what_v3_costs(settings):
    from config import ELEVEN_USD_PER_1K_CHARS

    v4 = settings.model_copy(update={"eleven_model_id": "eleven_v4"})
    v3 = settings.model_copy(update={"eleven_model_id": "eleven_v3"})
    assert v4.tts_usd_per_1k_chars == 0.08
    assert v4.tts_usd_per_1k_chars == v3.tts_usd_per_1k_chars
    # The real-time variant is half the price and a different model: the
    # lookup stays exact, so the narration model is never billed at its rate.
    assert ELEVEN_USD_PER_1K_CHARS["eleven_v4_turbo"] == 0.04


@pytest.mark.parametrize("model", ["eleven_v4", "eleven_v4_turbo"])
def test_v4_performs_the_direction_instead_of_reading_it(model):
    text = "Well. Fine. It is interesting."
    events = [_Ev(TagType.SIGH, 6), _Ev(TagType.CURIOUS, 12),
              _Ev(TagType.FLAT, 0)]
    req, overrides, _ = expand_delivery(text, events, model)
    assert "[sighs]" in req and "[curious]" in req and "[flat]" in req
    assert "<break" not in req
    # The register goes inline; the sliders stay where the cast left them.
    assert overrides == {}


def _engine(settings, model, calls, alignment_sample, audio_b64):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={
            "audio_base64": audio_b64,
            "alignment": alignment_sample["alignment"],
        })

    live = settings.model_copy(update={
        "mock_mode": False, "elevenlabs_api_key": "test-key",
        "eleven_voice_id_short": "voiceX", "eleven_model_id": model,
    })
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return TTSEngine(live, ledger=SpendLedger(live), client=client)


@pytest.fixture()
def audio_b64(tmp_path):
    from tests.test_tts import _tiny_mp3_b64

    return _tiny_mp3_b64(tmp_path)


def test_v4_is_sent_only_the_two_settings_it_has(settings, alignment_sample,
                                                 audio_b64):
    calls: list[dict] = []
    engine = _engine(settings, "eleven_v4", calls, alignment_sample, audio_b64)
    engine.synthesize(alignment_sample["text"], "short")
    assert calls[0]["model_id"] == "eleven_v4"
    assert calls[0]["voice_settings"] == {
        "stability": settings.eleven_stability_short,
        "similarity_boost": settings.eleven_similarity_short,
    }


def test_v3_still_gets_its_style_and_speed(settings, alignment_sample,
                                           audio_b64):
    calls: list[dict] = []
    engine = _engine(settings, "eleven_v3", calls, alignment_sample, audio_b64)
    engine.synthesize(alignment_sample["text"], "short")
    sent = calls[0]["voice_settings"]
    assert sent["speed"] == settings.eleven_speed_short
    assert sent["style"] == settings.eleven_style_short


def _preflight():
    spec = importlib.util.spec_from_file_location(
        "_check_preflight_v4", ROOT / "scripts" / "check_preflight.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_preflight_says_whether_the_voice_performs_the_tags(settings):
    mod = _preflight()
    voiced = {"elevenlabs_api_key": "k", "eleven_voice_id_short": "a",
              "eleven_voice_id_long": "b"}
    for model, says in (("eleven_v4", "performs the direction tags"),
                        ("eleven_turbo_v2_5", "ELEVEN_MODEL_ID=eleven_v4")):
        report = mod.Report()
        mod._voice(settings.model_copy(update={**voiced,
                                               "eleven_model_id": model}),
                   report, live=True)
        state, _, detail = report.rows[0]
        assert state == mod.PASS
        assert says in detail
