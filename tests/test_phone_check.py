"""A11: the mix heard through a phone's speaker."""

import shutil

import pytest

from pipeline.phone_check import (bass_share, masked_seconds, phone_line,
                                  phone_report)
from pipeline.provenance import Provenance
from pipeline.render_common import AudioTrack, run_ffmpeg

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


def _tone(path, src):
    run_ffmpeg(["-f", "lavfi", "-i", src, "-ac", "1", "-ar", "44100", str(path)])
    return path


def test_bass_effect_flagged(tmp_path):
    boom = _tone(tmp_path / "vine_boom.wav", "sine=frequency=100:duration=1")
    assert bass_share(boom) >= 0.7


def test_voice_band_effect_passes(tmp_path):
    ding = _tone(tmp_path / "ding.wav", "sine=frequency=2000:duration=1")
    assert bass_share(ding) < 0.2


def test_masked_seconds(tmp_path):
    voice = _tone(tmp_path / "v.wav", "sine=frequency=1000:duration=4")
    # quiet for two seconds, then as loud as he is
    bed = _tone(tmp_path / "r.wav",
                "aevalsrc='if(gte(t,2),0.2*sin(2*PI*800*t),0)':d=4:s=44100")
    assert masked_seconds(voice, bed) == [2, 3]
    assert masked_seconds(bed, voice) == [2, 3], "he speaks only where he is heard"


def test_report_line():
    assert phone_line({}) == ""
    assert phone_line({"masked": [4, 9], "bass_effects": []}) == \
        "voice reads · effects read"
    assert phone_line({"masked": list(range(61, 68)), "bass_effects": ["impact", "vine_boom"]}) \
        == ("VOICE BURIED 7s (1:01, 1:02, 1:03, 1:04, 1:05 +2) · "
            "NO SOUND ON A PHONE: impact, vine_boom")


def test_a_mix_measured_and_on_the_record(tmp_path):
    voice = _tone(tmp_path / "voice.wav", "sine=frequency=1000:duration=3")
    boom = _tone(tmp_path / "vine_boom-2.wav", "sine=frequency=60:duration=0.5")
    ding = _tone(tmp_path / "ding.wav", "sine=frequency=2500:duration=0.3")
    bed = _tone(tmp_path / "bed.wav", "sine=frequency=700:duration=3")
    tracks = [AudioTrack(path=voice, voice=True, name="voice"),
              AudioTrack(path=boom, start_s=0.5, name="vine_boom@0.50"),
              AudioTrack(path=ding, start_s=1.0, name="ding@1.00"),
              AudioTrack(path=bed, gain_db=6.0, duck=True, name="bed")]
    report = phone_report(tracks, 3.0, tmp_path)
    assert report["bass_effects"] == ["vine_boom"], "the variant is named by its key"
    assert isinstance(report["masked"], list)
    assert not (tmp_path / "phone_voice.wav").exists(), "the stems are not kept"
    assert phone_report(tracks[:1], 3.0, tmp_path) == {}, "nothing under him"
    p = Provenance(ticker="EXMPL", fmt="short", phone=report)
    back = Provenance.from_json(p.to_json())
    assert back.phone == report
    assert any(l.startswith("phone     ") and "vine_boom" in l
               for l in back.render_text().splitlines())


def test_the_ducked_bed_is_measured_ducked(tmp_path):
    """The rest is measured as the mix plays it, pushed down under him."""
    voice = _tone(tmp_path / "voice.wav", "sine=frequency=1000:duration=4")
    bed = _tone(tmp_path / "bed.wav", "sine=frequency=700:duration=4")
    loud = [AudioTrack(path=voice, voice=True, name="voice"),
            AudioTrack(path=bed, gain_db=1.0, name="bed")]
    ducked = [loud[0], AudioTrack(path=bed, gain_db=1.0, duck=True, name="bed")]
    assert len(phone_report(loud, 4.0, tmp_path)["masked"]) == 4
    assert len(phone_report(ducked, 4.0, tmp_path)["masked"]) < 4
