"""The SHORT's mix: the voice, the room, and the master bus.

A short went out as the voice alone from 15 August on, because the shots
rewrite replaced the mix with a `-shortest` mux and nothing checked what a
short sounded like. These check it from both ends: what the mix is built
from, and what the file measures.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from pipeline.audio_assets import ROOM_TONE_GAIN_DB, ROOM_TONE_NAME
from pipeline.render_common import mix_under_picture, run_ffmpeg
from pipeline.sound import manifest_rows, normalises, short_mix


@dataclass
class FakeTTS:
    audio_path: Path | None
    draft: bool = False


def _voice(path: Path, pattern: str = "sine=f=220:d=2,apad=pad_dur=1") -> Path:
    """Two seconds of tone, then a second of nothing: a sentence and a pause."""
    run_ffmpeg(["-f", "lavfi", "-i", pattern, "-c:a", "aac", str(path)])
    return path


def _picture(path: Path, seconds: float) -> Path:
    run_ffmpeg(["-f", "lavfi", "-i", f"color=c=0xF2F2EF:s=64x64:d={seconds}:r=15",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)])
    return path


def _silences(path: Path) -> list[str]:
    proc = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", str(path),
         "-af", "silencedetect=n=-70dB:d=0.4", "-f", "null", "-"],
        capture_output=True, text=True, check=True)
    return re.findall(r"silence_start: ([\d.]+)", proc.stderr)


def _integrated_lufs(path: Path) -> float:
    proc = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", str(path),
         "-af", "ebur128", "-f", "null", "-"],
        capture_output=True, text=True, check=True)
    found = re.findall(r"I:\s+(-?[\d.]+) LUFS", proc.stderr)
    assert found, "ebur128 reported no integrated loudness"
    return float(found[-1])


def _streams(path: Path) -> dict[str, dict]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)],
        capture_output=True, text=True, check=True).stdout
    return {s["codec_type"]: s for s in json.loads(out)["streams"]}


# ---------------------------------------------------------------- the tracks


def test_a_short_is_the_voice_over_the_room(settings, tmp_path):
    voice = _voice(tmp_path / "voice.m4a")
    tracks = short_mix(FakeTTS(voice), settings)

    by_name = {t.name: t for t in tracks}
    assert set(by_name) == {"voice", "room_tone"}
    assert by_name["voice"].voice is True, "the voice is compressed, as on the long"
    assert by_name["voice"].gain_db == 0.0
    room = by_name["room_tone"]
    assert room.path.name == ROOM_TONE_NAME
    assert room.loop is True and room.start_s == 0.0
    assert room.gain_db == ROOM_TONE_GAIN_DB, "the same room level as the long"


def test_no_voice_means_no_mix(settings, tmp_path):
    """A room with nobody in it proves nothing; the picture goes out silent,
    which is what a proof on a missing file always did."""
    assert short_mix(FakeTTS(tmp_path / "missing.m4a"), settings) == []
    assert short_mix(FakeTTS(None), settings) == []


def test_placeholder_audio_skips_the_loudness_pass(settings):
    """The LONG's rule, for the LONG's reason: `loudnorm` on a placeholder
    raises it thirty decibels and measures nothing real."""
    assert normalises(settings, FakeTTS(None)) is False, "mock voice"
    live = settings.model_copy(update={"mock_mode": False})
    assert normalises(live, FakeTTS(None)) is True
    assert normalises(live, FakeTTS(None, draft=True)) is False, "draft voice"


def test_the_manifest_row_is_the_long_s_shape(settings, tmp_path):
    rows = manifest_rows(short_mix(FakeTTS(_voice(tmp_path / "v.m4a")), settings))
    assert rows == [
        {"name": "voice", "start": 0.0, "gain_db": 0.0, "loop": False},
        {"name": "room_tone", "start": 0.0,
         "gain_db": round(ROOM_TONE_GAIN_DB, 1), "loop": True},
    ]


# ------------------------------------------------------------ the file itself


def test_the_mix_goes_under_the_picture_at_the_streaming_target(settings, tmp_path):
    """MEASURED OFF THE FILE. The voice ends a second early, which is the
    gap between sentences: the room has to fill it, the whole programme has
    to land at the -14 LUFS YouTube plays at, and the picture must come
    through untouched."""
    picture = _picture(tmp_path / "picture.mp4", 3.0)
    voice = _voice(tmp_path / "voice.m4a")
    tracks = short_mix(FakeTTS(voice), settings)
    out = tmp_path / "short.mp4"

    mix_under_picture(picture, tracks, out, duration=3.0, audio_bitrate="128k",
                      normalise=True, graph_path=tmp_path / "mix.filter.txt")

    graph = (tmp_path / "mix.filter.txt").read_text(encoding="utf-8")
    assert "acompressor=" in graph and "loudnorm=I=-14.0" in graph
    assert "alimiter=" in graph

    streams = _streams(out)
    assert streams["audio"]["codec_name"] == "aac"
    assert streams["video"]["codec_name"] == _streams(picture)["video"]["codec_name"]
    assert abs(float(streams["audio"]["duration"]) - 3.0) < 0.1
    assert not _silences(out), "the gap after the sentence went to digital silence"
    assert abs(_integrated_lufs(out) - (-14.0)) < 2.0


def test_a_placeholder_mix_is_limited_but_not_normalised(settings, tmp_path):
    picture = _picture(tmp_path / "picture.mp4", 2.0)
    voice = _voice(tmp_path / "voice.m4a", "sine=f=220:d=2")
    out = tmp_path / "short.mp4"
    mix_under_picture(picture, short_mix(FakeTTS(voice), settings), out,
                      duration=2.0, audio_bitrate="128k", normalise=False,
                      graph_path=tmp_path / "mix.filter.txt")
    graph = (tmp_path / "mix.filter.txt").read_text(encoding="utf-8")
    assert "loudnorm" not in graph and "alimiter=" in graph
    assert out.exists()


def test_a_mix_with_nothing_in_it_is_refused(tmp_path):
    from pipeline.render_common import RenderError

    with pytest.raises(RenderError):
        mix_under_picture(tmp_path / "p.mp4", [], tmp_path / "o.mp4",
                          duration=1.0, audio_bitrate="128k", normalise=True)


# ------------------------------------------------------------- a real render


def test_a_rendered_short_carries_its_mix(settings, tmp_path, short_valid_json):
    """End to end, on the mock voice: the manifest says what was mixed, and
    the file has a sound floor under the whole cut."""
    from pipeline.parser_short import parse_short_script
    from pipeline.render_short import render_short
    from pipeline.tts import TTSEngine

    script, _ = parse_short_script(short_valid_json, settings)
    tts = TTSEngine(settings).synthesize(script.audio_script, "short")
    out, manifest_path = render_short(script, tts, tmp_path, settings)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    names = [a["name"] for a in manifest["audio"]]
    assert names == ["voice", "room_tone"]
    assert "audio" in _streams(out)
    assert not _silences(out), "a short went to digital silence between words"
