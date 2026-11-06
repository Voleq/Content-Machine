"""The voice's chunks join sample-exact, so the effects land under the picture.

RDDT long, 2 Nov 2026: the free voice was one AAC file a sentence, joined by
the concat demuxer. Each sentence decodes longer than its container says, the
overlaps went into the voice as squeezed timestamps, and the final mix's
timestamps ran behind its samples: a player keeping the picture on them heard
the chapter sound 1.5 s before the board at 16:26 and the meme sound at 17:33
before its picture, 1.84 s by the end of the video.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from pipeline.render_common import (AudioTrack, CompositeSpec, audio_graph,
                                    ffprobe_duration, join_audio, run_ffmpeg)

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None,
                                reason="needs ffmpeg")

RATE = 48000


def _sentences(tmp: Path, n: int) -> list[Path]:
    """`n` AAC sentence files, as the free voice used to write them."""
    out = []
    for i in range(n):
        f = tmp / f"chunk_{i:03d}.m4a"
        run_ffmpeg(["-f", "lavfi", "-i",
                    f"sine=frequency=440:sample_rate=22050:duration={1.0 + (i % 5) * 0.37:.3f}",
                    "-af", "volume=0.02", "-ac", "1", "-ar", "44100", "-c:a", "aac", "-b:a", "128k", str(f)])
        out.append(f)
    return out


def _packet_pts(path: Path) -> list[int]:
    got = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
         "packet=pts", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True).stdout
    return [int(x.strip().rstrip(",")) for x in got.split() if x.strip()]


def test_joined_lengths_are_what_the_joined_file_holds(tmp_path, settings):
    chunks = _sentences(tmp_path, 12)
    out = tmp_path / "audio.m4a"
    lengths = join_audio(chunks, out, settings)
    assert len(lengths) == 12
    # The file is as long as the parts said, to a frame of audio: the old
    # join was ~12 ms longer per sentence than the offsets it handed out.
    assert abs(ffprobe_duration(out) - sum(lengths)) < 0.03
    assert not list(tmp_path.glob("*.join")), "the PCM parts are cleaned up"


def test_a_wav_join_is_pcm(tmp_path, settings):
    out = tmp_path / "joined.wav"
    lengths = join_audio(_sentences(tmp_path, 3), out, settings)
    got = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                          "stream=codec_name", "-of", "csv=p=0", str(out)],
                         capture_output=True, text=True, check=True).stdout
    assert got.strip() == "pcm_s16le"
    assert abs(ffprobe_duration(out) - sum(lengths)) < 0.001


def test_an_effect_lands_where_it_was_placed_over_a_joined_voice(tmp_path, settings):
    """The whole path: joined voice + an effect at 30 s through the mix every
    render uses. The packet that carries the effect is stamped 30 s, and no
    packet in the mix is squeezed."""
    chunks = _sentences(tmp_path, 30)
    voice = tmp_path / "audio.m4a"
    lengths = join_audio(chunks, voice, settings)
    total = sum(lengths) + 1.0
    click = tmp_path / "click.wav"
    run_ffmpeg(["-f", "lavfi", "-i",
                "sine=frequency=3000:sample_rate=44100:duration=0.05", str(click)])
    at = 30.0
    spec = CompositeSpec(base_input_args=[], duration=total, normalise_audio=False,
                         audio=[AudioTrack(path=voice, voice=True),
                                AudioTrack(path=click, start_s=at)])
    inputs, lines = audio_graph(spec, first_input=0)
    mix = tmp_path / "mix.m4a"
    run_ffmpeg([*inputs, "-filter_complex", ";".join(lines), "-map", "[aout]",
                "-t", f"{total:.3f}", "-c:a", "aac", "-b:a", "192k", str(mix)])
    pts = _packet_pts(mix)
    squeezed = [i for i in range(1, len(pts)) if pts[i] - pts[i - 1] != 1024]
    assert not squeezed, f"{len(squeezed)} packets with squeezed timestamps"
    # Where the click's samples are, by count, and the stamp on that packet.
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(mix), "-af",
                          "highpass=f=2000", "-ac", "1", "-ar", str(RATE),
                          "-f", "s16le", "-"], capture_output=True, check=True).stdout
    import array

    samples = array.array("h", raw)
    peak = max(abs(s) for s in samples)
    first = next(i for i, s in enumerate(samples) if abs(s) > 0.5 * peak)
    stamp = pts[min(first // 1024 + 1, len(pts) - 1)] / RATE
    assert abs(first / RATE - at) < 0.03
    assert abs(stamp - at) < 0.05
