"""The free local draft tier (P3.2).

There is no Piper on this box, so the synthesis subprocess is not exercised —
`PiperVoice` is verified on the render machine. What is tested is everything
that decides whether draft audio is *safe*: the sentence-level timing model,
the tier routing (a draft must never escalate to a paid call), the cache key
that keeps draft and final apart, and the renderer's refusal to publish a
final built on interpolated timings.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.local_tts import (
    MAX_SENTENCE_WORDS,
    LocalTTSUnavailable,
    available,
    build_voice,
    distribute_words,
    draft_notice,
    split_sentences,
    synthesize_local,
)
from pipeline.models import TTSResult
from pipeline.render_common import RenderError
from pipeline.models import JobKind as _JobKind
from pipeline.tts import TTSEngine

JobKindProof = _JobKind.RENDER_PROOF_LONG

TEXT = ("EXMPL is cheap and hated. Revenue grew four point seven percent. "
        "That is not a growth company.")


# --------------------------------------------------------------------------
# A fake voice: writes a real (silent) file so ffprobe has something to measure.
# --------------------------------------------------------------------------


class FakeVoice:
    """Speaks at a fixed rate, so durations are predictable and real."""

    def __init__(self, seconds_per_word: float = 0.4):
        self.spw = seconds_per_word
        self.said: list[str] = []

    def say(self, text: str, out_path: Path) -> Path:
        from pipeline.render_common import run_ffmpeg

        self.said.append(text)
        seconds = max(len(text.split()) * self.spw, 0.3)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        run_ffmpeg(["-f", "lavfi",
                    "-i", f"anullsrc=r=44100:cl=mono:d={seconds:.3f}",
                    str(out_path)])
        return out_path


# --------------------------------------------------------------------------
# Sentence splitting — the units that get exact timings.
# --------------------------------------------------------------------------


def test_sentences_keep_their_terminators_so_durations_sum_to_the_whole():
    parts = split_sentences(TEXT)
    assert len(parts) == 3
    assert parts[0] == "EXMPL is cheap and hated."
    assert all(p.endswith((".", "!", "?")) for p in parts)


def test_a_long_sentence_is_split_because_interpolation_error_grows_with_it():
    long_one = ", ".join(f"clause number {i} with several words" for i in range(6))
    parts = split_sentences(long_one + ".")
    assert len(parts) > 1
    for p in parts:
        assert len(p.split()) <= MAX_SENTENCE_WORDS * 1.6, p


def test_text_with_no_terminator_still_yields_something():
    assert split_sentences("just a fragment") == ["just a fragment"]
    assert split_sentences("   ") == []


# --------------------------------------------------------------------------
# The timing model, and its honest limits.
# --------------------------------------------------------------------------


def test_words_fill_exactly_the_measured_span():
    """The sentence boundary is the part that must be exact."""
    words = distribute_words("one two three four", start=2.0, duration=4.0)
    assert words[0].start == pytest.approx(2.0)
    assert words[-1].end == pytest.approx(6.0, abs=1e-3)
    for a, b in zip(words, words[1:]):
        assert b.start == pytest.approx(a.end, abs=1e-3), "a gap opened up"


def test_longer_words_get_more_time_than_short_ones():
    """Evenly-spaced timings visibly drag a cue off its word whenever a long
    word is in the sentence."""
    words = distribute_words("a extraordinarily complicated x", 0.0, 4.0)
    spans = [w.end - w.start for w in words]
    assert spans[1] > spans[0] * 2, spans


def test_char_offsets_point_into_the_sentence():
    words = distribute_words("alpha beta gamma", 0.0, 3.0)
    text = "alpha beta gamma"
    for w in words:
        assert text[w.char_start:w.char_end] == w.word


def test_char_offsets_are_absolute_across_the_whole_text(settings, tmp_path):
    """The timeline resolves every visual cue through these offsets, so a
    sentence-local offset would misplace every cue after the first sentence."""
    speech = synthesize_local(TEXT, tmp_path, settings, voice=FakeVoice())
    for w in speech.words:
        assert TEXT[w.char_start:w.char_end] == w.word, w


def test_timings_are_monotonic_across_sentences(settings, tmp_path):
    speech = synthesize_local(TEXT, tmp_path, settings, voice=FakeVoice())
    for a, b in zip(speech.words, speech.words[1:]):
        assert b.start >= a.start
        assert a.end <= b.end


def test_every_word_of_the_script_is_timed(settings, tmp_path):
    speech = synthesize_local(TEXT, tmp_path, settings, voice=FakeVoice())
    assert [w.word for w in speech.words] == TEXT.split()


def test_sentence_boundaries_land_on_the_real_measured_durations(settings, tmp_path):
    """The claim being made: boundaries exact, interiors interpolated."""
    from pipeline.render_common import ffprobe_duration

    voice = FakeVoice(seconds_per_word=0.5)
    speech = synthesize_local(TEXT, tmp_path, settings, voice=voice)
    assert len(voice.said) == 3, "each sentence got its own synthesis call"

    measured = [ffprobe_duration(f) for f in speech.chunk_files]
    boundaries = []
    t = 0.0
    for d in measured:
        t += d
        boundaries.append(t)
    # the last word of each sentence ends at that sentence's real boundary
    per_sentence = [len(s.split()) for s in split_sentences(TEXT)]
    idx = -1
    for n, edge in zip(per_sentence, boundaries):
        idx += n
        assert speech.words[idx].end == pytest.approx(edge, abs=0.02)


# --------------------------------------------------------------------------
# Availability — and never escalating to paid.
# --------------------------------------------------------------------------


def test_it_is_unavailable_here_and_says_why(settings):
    ok, why = available(settings)
    assert not ok
    assert "piper" in why.lower() or "LOCAL_TTS_MODEL" in why


def test_the_switch_turns_it_off(settings):
    s = settings.model_copy(update={"local_tts_enabled": False})
    ok, why = available(s)
    assert not ok and "switched off" in why


def test_building_an_unavailable_voice_raises_rather_than_half_working(settings):
    with pytest.raises(LocalTTSUnavailable):
        build_voice(settings)


def test_mock_mode_still_wins_outright(settings):
    """The hard guarantee is that MOCK_MODE is offline and $0; a local voice is
    a subprocess and a model file, which a test run must not depend on."""
    engine = TTSEngine(settings)
    assert settings.mock_mode
    assert engine.tier_for(draft=True) == "mock"
    assert engine.tier_for(draft=False) == "mock"


def test_a_draft_never_escalates_to_the_paid_tier(settings):
    """Without Piper the draft falls back to the hum — never to ElevenLabs.
    A draft that quietly spent money would be the worst possible surprise."""
    live = settings.model_copy(update={"mock_mode": False})
    engine = TTSEngine(live)
    assert engine.tier_for(draft=True) == "mock"
    assert engine.tier_for(draft=False) == "paid"


def test_the_local_tier_is_chosen_when_the_voice_is_there(settings, tmp_path,
                                                          monkeypatch):
    model = tmp_path / "voice.onnx"
    model.write_bytes(b"not really an onnx")
    live = settings.model_copy(update={"mock_mode": False,
                                       "local_tts_model": str(model)})
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/piper")
    engine = TTSEngine(live)
    assert engine.tier_for(draft=True) == "local"
    assert engine.tier_for(draft=False) == "paid", "a final must still buy"


# --------------------------------------------------------------------------
# Draft audio is marked, cached apart, and refused by the finals.
# --------------------------------------------------------------------------


def test_mock_audio_is_labelled_but_not_fenced_off(settings):
    """`draft` means "interpolated timings passed off as real", which is the
    local voice and nothing else. MOCK_MODE is the established offline
    contract — the suite and the whole dev loop render finals from it — so
    marking mock as draft would make every offline render refuse itself."""
    engine = TTSEngine(settings)
    result = engine.synthesize("Hello there. This is a test.", "short")
    assert result.tier == "mock"
    assert result.draft is False
    assert result.cost_usd == 0.0


def test_a_mock_final_render_still_works(settings, tmp_path, short_valid_json):
    """The regression guard for the above: this is the offline dev loop."""
    from pipeline.parser_short import parse_short_script
    from pipeline.render_short import render_short

    script, _ = parse_short_script(short_valid_json, settings)
    tts = TTSEngine(settings).synthesize(script.audio_script, "short")
    out, manifest = render_short(script, tts, tmp_path, settings)
    assert out.exists() and manifest.exists()


def test_a_draft_and_a_final_do_not_share_a_cache_entry(settings, monkeypatch,
                                                        tmp_path):
    """Otherwise the draft's local audio satisfies the final's cache lookup and
    the paid voice is never called — a 'final' that shipped draft audio."""
    model = tmp_path / "voice.onnx"
    model.write_bytes(b"x")
    live = settings.model_copy(update={"mock_mode": False,
                                       "local_tts_model": str(model)})
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/piper")
    engine = TTSEngine(live)

    text = "Same words, different tier."
    draft_dir = engine._cache_dir(text, "long", None, True)[1]
    final_dir = engine._cache_dir(text, "long", None, False)[1]
    assert draft_dir != final_dir


def test_is_cached_answers_per_tier(settings):
    engine = TTSEngine(settings)
    text = "Cache me once. Cache me twice."
    assert not engine.is_cached(text, "short")
    engine.synthesize(text, "short")
    assert engine.is_cached(text, "short")


def test_a_final_long_render_refuses_draft_audio(settings, tmp_path,
                                                 long_valid_text):
    """The guarantee, enforced in the renderer rather than by discipline: the
    failure is invisible otherwise — it renders fine, just subtly out of sync."""
    from pipeline.parser_long import parse_long_script
    from pipeline.render_long import render_long

    script, _ = parse_long_script(long_valid_text, "EXMPL", settings)
    tts = TTSResult(audio_path=tmp_path / "a.m4a", words=[], duration_s=10.0,
                    chars=10, cached=False, cost_usd=0.0, tier="local",
                    draft=True)
    with pytest.raises(RenderError) as e:
        render_long(script, tts, tmp_path, settings, draft=False)
    assert "draft audio" in str(e.value)
    assert "interpolated" in str(e.value)


def test_a_draft_render_accepts_it(settings, tmp_path, long_valid_text):
    """…and the draft path must obviously still work, or the tier is useless."""
    from pipeline.parser_long import parse_long_script
    from pipeline.render_long import render_long

    script, _ = parse_long_script(long_valid_text, "EXMPL", settings)
    tts = TTSResult(audio_path=tmp_path / "a.m4a", words=[], duration_s=10.0,
                    chars=10, cached=False, cost_usd=0.0, tier="local",
                    draft=True)
    # It gets past the guard and fails later for a missing audio file, not for
    # being a draft.
    with pytest.raises(Exception) as e:
        render_long(script, tts, tmp_path, settings, draft=True)
    assert "draft audio" not in str(e.value)


def test_a_final_short_render_refuses_draft_audio(settings, tmp_path,
                                                  short_valid_json):
    """Interpolated timings must never be the master clock of a published cut
    — the same rule render_long enforces."""
    from pipeline.parser_short import parse_short_script
    from pipeline.render_short import render_short

    script, _ = parse_short_script(short_valid_json, settings)
    tts = TTSResult(audio_path=tmp_path / "a.m4a", words=[], duration_s=10.0,
                    chars=10, cached=False, cost_usd=0.0, tier="local",
                    draft=True)
    with pytest.raises(RenderError) as e:
        render_short(script, tts, tmp_path, settings)
    assert "draft audio" in str(e.value)


def test_a_short_proof_accepts_draft_audio(settings, tmp_path, short_valid_json):
    """A proof is the deliberate exception: it exists to be looked at and is
    never delivered, so it may run on the free voice. It must not fail for the
    reason a final does."""
    from pipeline.parser_short import parse_short_script
    from pipeline.render_short import render_short

    script, _ = parse_short_script(short_valid_json, settings)
    tts = TTSResult(audio_path=tmp_path / "a.m4a", words=[], duration_s=10.0,
                    chars=10, cached=False, cost_usd=0.0, tier="local",
                    draft=True)
    with pytest.raises(Exception) as e:
        render_short(script, tts, tmp_path, settings, proof=True)
    assert "draft audio" not in str(e.value)


def test_the_operator_is_told_what_they_are_listening_to():
    notice = draft_notice("tier: local")
    assert "DRAFT" in notice
    assert "not the real one" in notice
    assert "interpolated" in notice


def test_the_draft_command_no_longer_gates_on_approval(settings, monkeypatch,
                                                       long_valid_text):
    """A draft used to trigger the one paid generation, so it sat behind the
    approval gate. It is free now, so there is nothing left to gate."""
    import shutil
    from bot.handlers import BotCore
    from pipeline.models import JobKind

    core = BotCore(settings)
    core.start_lane(77, "long", "EXMPL")
    ws = core.context.get(77)
    shutil.copy(Path(__file__).resolve().parents[1] / "fixtures" /
                "company_data" / "dennis_data.xlsx", ws.path / "dennis_data.xlsx")
    core.intake_script(77, long_valid_text)
    assert not ws.is_approved("long")

    kind, text, _ = core.render_request("EXMPL", "long", draft=True)
    assert kind is JobKind.RENDER_DRAFT_LONG, text
    assert "$0" in text


# --------------------------------------------------------------------------
# The PROOF tier: everything real except the voice, and $0 enforced in code.
#
# The gap this closes: the only free path used to be MOCK_MODE, which also
# fakes prices, imagery, memes, filings and delivery — so a free render told
# the operator nothing about what would actually ship. ElevenLabs is the only
# real cost in the system, so the tier that mocks ONLY the voice is the one
# worth having, and its $0 promise has to be structural rather than a comment.
# --------------------------------------------------------------------------


def test_a_proof_cannot_reach_the_paid_voice(settings, monkeypatch):
    """The gate, at the boundary. Not 'does not' — CANNOT."""
    from pipeline.tts import PaidVoiceForbidden

    monkeypatch.setattr(settings, "mock_tts", False)
    monkeypatch.setattr(settings, "mock_mode", False)
    monkeypatch.setattr(settings, "local_tts_enabled", False)  # no Piper here
    eng = TTSEngine(settings)
    # draft=False is exactly the mistyped-command case: without free_only this
    # resolves to "paid" and spends.
    assert eng.tier_for(False) == "paid"
    with pytest.raises(PaidVoiceForbidden):
        eng.synthesize("Noise, or signal?", "short", draft=False, free_only=True)


def test_the_free_only_gate_raises_before_anything_is_sent(settings, monkeypatch):
    """It must fail before the HTTP client is even reached — a gate that
    raises after the request is not a gate."""
    from pipeline.tts import PaidVoiceForbidden

    monkeypatch.setattr(settings, "mock_tts", False)
    monkeypatch.setattr(settings, "mock_mode", False)
    monkeypatch.setattr(settings, "local_tts_enabled", False)

    def explode(*a, **k):  # pragma: no cover — reaching this IS the failure
        raise AssertionError("a free-only job reached the paid generator")

    eng = TTSEngine(settings)
    monkeypatch.setattr(eng, "_generate_real", explode)
    with pytest.raises(PaidVoiceForbidden):
        eng.synthesize("Noise, or signal?", "long", draft=False, free_only=True)


def test_a_proof_falls_back_to_mock_and_never_to_paid(settings, monkeypatch):
    """No Piper on the box is a degraded proof, not a purchase."""
    monkeypatch.setattr(settings, "mock_tts", False)
    monkeypatch.setattr(settings, "mock_mode", False)
    monkeypatch.setattr(settings, "local_tts_enabled", False)
    eng = TTSEngine(settings)
    assert eng.tier_for(True) == "mock"
    res = eng.synthesize("Noise, or signal?", "short", draft=True, free_only=True)
    assert res.cost_usd == 0.0
    assert res.tier == "mock"


def test_the_free_tiers_pass_the_gate(settings):
    """local and mock are free, so the gate must let them through — a gate
    that blocks the tier it exists to protect is just an outage."""
    eng = TTSEngine(settings)
    eng.guard_free_only("local")
    eng.guard_free_only("mock")


def test_the_proof_command_works_for_both_formats(settings, monkeypatch,
                                                  long_valid_text,
                                                  short_valid_json):
    """/draft is LONG-only, and the SHORT is the daily-volume format. A proof
    has to exist for both or the format that ships most often still has no
    free way to be looked at."""
    import shutil
    from bot.handlers import BotCore
    from pipeline.models import JobKind

    core = BotCore(settings)
    core.start_lane(91, "long", "EXMPL")
    ws = core.context.get(91)
    shutil.copy(Path(__file__).resolve().parents[1] / "fixtures" /
                "company_data" / "dennis_data.xlsx", ws.path / "dennis_data.xlsx")
    core.intake_script(91, long_valid_text)
    # the same workspace carries both lanes, so one ticker exercises both
    core.intake_script(91, short_valid_json)

    kind, text, _ = core.render_request("EXMPL", "long", proof=True)
    assert kind is JobKind.RENDER_PROOF_LONG
    kind, _, _ = core.render_request("EXMPL", "short", proof=True)
    assert kind is JobKind.RENDER_PROOF_SHORT
    # and it says what it is, in the reply, without the operator guessing
    assert "$0" in text and "real visuals" in text.lower()


def test_a_proof_needs_no_approval(settings, monkeypatch, long_valid_text):
    """Approval is the SPEND gate. A pass that cannot spend must not be
    behind it, or you approve a video to find out if it is worth approving."""
    import shutil
    from bot.handlers import BotCore
    from pipeline.models import JobKind

    core = BotCore(settings)
    core.start_lane(92, "long", "EXMPL")
    ws = core.context.get(92)
    shutil.copy(Path(__file__).resolve().parents[1] / "fixtures" /
                "company_data" / "dennis_data.xlsx", ws.path / "dennis_data.xlsx")
    core.intake_script(92, long_valid_text)
    assert not ws.is_approved("long")
    kind, _, _ = core.render_request("EXMPL", "long", proof=True)
    assert kind is JobKind.RENDER_PROOF_LONG


def test_a_proof_renders_at_full_resolution(settings):
    """The whole point. Legibility is a resolution question, so a pass that
    scales down cannot answer it — draft (0.5) and preview (0.25) both throw
    away the evidence, which is why this is a third constant and not an
    overload of preview_scale."""
    assert settings.proof_scale == 1.0
    assert settings.proof_scale > settings.draft_scale > settings.preview_scale


def test_a_proof_buys_its_speed_from_the_encoder(settings):
    from pipeline.render_common import encode_profile

    proof = encode_profile(settings, "short", proof=True)
    final = encode_profile(settings, "short")
    assert proof.vcodec == "libx264"
    assert proof.preset == "veryfast"
    # cheaper than a final, nowhere near the throwaway passes
    assert final.crf < proof.crf < settings.preview_crf


def test_a_proof_mocks_the_voice_and_nothing_else(settings, monkeypatch,
                                                  long_valid_text):
    """The complaint this tier answers: MOCK_MODE is the only other free path
    and it fakes prices, imagery, memes, filings and delivery too, so a free
    render was unrepresentative of what ships. A proof may mock exactly one
    subsystem — the only one that costs money."""
    import shutil
    from bot.handlers import BotCore

    live = settings.model_copy(update={"mock_mode": False, "mock_tts": None,
                                       "mock_prices": None, "mock_screener": None})
    live.ensure_runtime_dirs()
    core = BotCore(live)
    core.start_lane(93, "long", "EXMPL")
    ws = core.context.get(93)
    shutil.copy(Path(__file__).resolve().parents[1] / "fixtures" /
                "company_data" / "dennis_data.xlsx", ws.path / "dennis_data.xlsx")
    core.intake_script(93, long_valid_text)

    seen: dict = {}

    def spy(text, fmt, **kw):
        seen.update(kw)
        raise RuntimeError("stop here — the TTS call is all we are inspecting")

    monkeypatch.setattr(core.tts, "synthesize", spy)
    job = type("J", (), {"kind": JobKindProof, "ticker": "EXMPL",
                         "workdate": ws.workdate, "delivered_link": None})()
    with pytest.raises(RuntimeError):
        core._run_proof(job, ws, lambda _d: None)

    # the voice is asked for free, and guaranteed free
    assert seen["draft"] is True and seen["free_only"] is True
    # and nothing else was switched to mock behind the operator's back
    assert not live.mocking_prices
    assert not live.mocking_screener
