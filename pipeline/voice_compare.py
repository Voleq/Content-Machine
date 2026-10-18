"""The before-and-after clip for the room and the de-esser (A8, A9).

Both ship switched off, because nobody here can hear his voice: Claude makes
no paid voice, and the stand-in voice is not the one viewers hear. So after
his first paid voice he asks for this clip — twenty seconds from the middle
of it, four ways — listens, and switches on what he liked.
"""

from __future__ import annotations

from pathlib import Path

from pipeline.render_common import (AudioTrack, CompositeSpec, ffprobe_duration,
                                    render_audio, run_ffmpeg)

CLIP_S = 20.0
VARIANTS = {"dry": (False, False), "room": (True, False),
            "deess": (False, True), "both": (True, True)}


def voice_compare(audio: Path, out_dir: Path) -> list[Path]:
    """compare_dry / _room / _deess / _both .wav, the same twenty seconds."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    duration = ffprobe_duration(audio)
    length = min(CLIP_S, duration)
    start = max(0.0, duration / 2 - length / 2)
    source = out_dir / "compare_source.wav"
    run_ffmpeg(["-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", str(audio),
                str(source)])
    out = []
    try:
        for name, (room, deess) in VARIANTS.items():
            spec = CompositeSpec(base_input_args=[], duration=length,
                                 audio=[AudioTrack(path=source, voice=True,
                                                   room=room, deess=deess,
                                                   name="voice")])
            out.append(render_audio(spec, out_dir / f"compare_{name}.wav"))
    finally:
        source.unlink(missing_ok=True)
    return out
