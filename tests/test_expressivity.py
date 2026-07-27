"""Delivery direction reaching the voice, and the audio master bus."""

from __future__ import annotations

import pytest

from config import Settings
from pipeline.models import TagEvent, TagType, WordTimestamp
from pipeline.tts import TTSEngine, expand_delivery, remap_to_clean


def ev(kind: TagType, offset: int) -> TagEvent:
    return TagEvent(type=kind, payload="", char_offset=offset, raw_offset=offset)


def test_a_beat_becomes_a_break_at_its_own_offset():
    text, overrides = expand_delivery("He paused. Then said it.",
                                      [ev(TagType.BEAT, 11)], "eleven_turbo_v2_5")
    assert text == 'He paused. <break time="0.6s" /> Then said it.'
    assert overrides == {}


def test_flat_and_dry_are_generation_settings_not_inline_text():
    text, overrides = expand_delivery("Flat line.", [ev(TagType.FLAT, 0)],
                                      "eleven_turbo_v2_5")
    assert text == "Flat line.", "a register note must not appear in the speech"
    assert overrides["stability"] == 0.85 and overrides["style"] == 0.0


def test_sigh_degrades_on_a_model_without_audio_tags():
    """`[sighs]` is an eleven_v3 feature. On turbo it would be READ ALOUD,
    so it degrades to a pause instead of gambling on support."""
    turbo, _ = expand_delivery("Well. Fine.", [ev(TagType.SIGH, 5)],
                               "eleven_turbo_v2_5")
    assert "[sighs]" not in turbo and "<break" in turbo

    v3, _ = expand_delivery("Well. Fine.", [ev(TagType.SIGH, 5)], "eleven_v3")
    assert "[sighs]" in v3


def test_no_directives_leaves_the_text_untouched():
    assert expand_delivery("Nothing here.", [], "eleven_turbo_v2_5") == \
        ("Nothing here.", {})


def test_visual_tags_are_not_treated_as_delivery():
    text, overrides = expand_delivery(
        "A line.", [TagEvent(type=TagType.CLIP, payload="clown",
                             char_offset=2, raw_offset=2)], "eleven_turbo_v2_5")
    assert text == "A line." and overrides == {}


def test_offsets_are_remapped_back_onto_the_clean_text():
    """Alignment mirrors the REQUEST, which carries break tags the clean
    script does not. Leaving offsets there would drift every visual cue."""
    clean = "He paused. Then said it."
    words = [
        WordTimestamp(word="He", start=0.0, end=0.2, char_start=0, char_end=2),
        WordTimestamp(word="paused.", start=0.2, end=0.6, char_start=3, char_end=10),
        # a fragment of `<break time="0.6s" />` that alignment returns
        WordTimestamp(word='<break', start=0.6, end=0.6, char_start=11, char_end=17),
        WordTimestamp(word="Then", start=1.2, end=1.4, char_start=30, char_end=34),
    ]
    out = remap_to_clean(words, clean)
    assert [w.word for w in out] == ["He", "paused.", "Then"]
    for w in out:
        assert clean[w.char_start:w.char_end] == w.word


def test_a_directive_changes_the_tts_cache_key(settings):
    """It changes what gets generated, so it must be authored before the
    paid run — the cost report says so, and this is why."""
    engine = TTSEngine(settings)
    plain = engine.is_cached("Some narration here.", "long")
    engine.synthesize("Some narration here.", "long")
    assert engine.is_cached("Some narration here.", "long")
    # the same script with a beat added is a different generation
    assert not engine.is_cached("Some narration here.", "long",
                                events=[ev(TagType.BEAT, 5)])
    assert plain is False


def test_delivery_survives_a_real_synthesis(settings):
    """End to end in MOCK_MODE: offsets still index the clean script."""
    clean = "He paused. Then he said the number out loud."
    out = TTSEngine(settings).synthesize(clean, "long",
                                         events=[ev(TagType.BEAT, 11)])
    assert out.words
    for w in out.words:
        assert clean[w.char_start:w.char_end] == w.word


# ------------------------------------------------------------ master bus


def test_the_mix_is_loudness_normalised(tmp_path, settings):
    from pipeline.render_common import AudioTrack, CompositeSpec, composite_video, encode_profile
    from pipeline.render_common import run_ffmpeg

    voice = tmp_path / "voice.m4a"
    run_ffmpeg(["-f", "lavfi", "-i", "sine=f=220:d=1.0", "-c:a", "aac", str(voice)])
    base = tmp_path / "base.png"
    from PIL import Image
    Image.new("RGB", (64, 64), (242, 242, 239)).save(base)

    out = tmp_path / "out.mp4"
    composite_video(
        CompositeSpec(
            base_input_args=["-loop", "1", "-t", "1.0", "-i", str(base)],
            base_filter="scale=64:64",
            audio=[AudioTrack(path=voice, voice=True)],
            duration=1.0, fps=15,
        ),
        encode_profile(settings, "long", draft=True), "96k", out,
    )
    graph = out.with_suffix(".filter.txt").read_text(encoding="utf-8")
    assert "loudnorm=I=-14.0" in graph, "the programme is normalised to -14 LUFS"
    assert "alimiter=" in graph, "and true-peak limited"
    assert "acompressor=" in graph, "the VO gets light compression before the mix"
    assert out.exists()
