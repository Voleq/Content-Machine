"""The mix through a phone's speaker (A11): does he still read over the rest,
and does every effect still make a sound.

Most people hear a short, and a good part of a long, through the speaker of
the phone they are holding. It gives almost nothing under 300 Hz and little
over 7 kHz, so the warmth of the voice, the room and the low half of every
effect go, and the music's middle is what is left to sit on his words. A mix
that reads on headphones can bury him there.

`phone_report` renders two stems of the finished mix through the same graph
the video's sound is (`render_common.audio_graph`), audio only and not
normalised: the voice alone, and everything else with the voice still
pushing the music down but not in it. Both go through the phone filter, a
second at a time. A second he speaks in and leads the rest by less than
`MARGIN_DB` is a second the phone buries him. Each effect file the mix plays
is measured too: one that keeps less than a third of its level through the
filter is a boom the phone will not play.

It says so on the record beside the link (`provenance`), and changes nothing
in the mix: what to do about a buried second is his call.
"""

from __future__ import annotations

import hashlib
import logging
import math
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Sequence

from pipeline.render_common import AudioTrack, CompositeSpec, render_audio

log = logging.getLogger(__name__)

PHONE = "highpass=f=300,lowpass=f=7000"
RATE = 16000
MARGIN_DB = 6.0          # he has to lead the rest by this, through the phone
SPEAKS_DB = -40.0        # quieter than this through the phone is a pause
MASKED_WARN_S = 3        # a second or two is a breath; this many is a mix
BASS_WARN = 0.7          # the share of an effect's level the phone loses
SHOW_S = 5               # buried seconds named on the line, the rest counted

_bass_cache: dict[str, float] = {}


def _pcm(path: Path, *, phone: bool):
    import numpy as np

    af = f"{PHONE}," if phone else ""
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-loglevel", "error", "-i", str(path),
         "-vn", "-af", f"{af}aformat=channel_layouts=mono", "-ar", str(RATE),
         "-f", "s16le", "-"], capture_output=True, timeout=1200)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode(errors="replace")[-300:])
    return np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float64) / 32768.0


def _levels(path: Path) -> list[float]:
    """Through the phone, the level of each whole second, in dBFS."""
    x = _pcm(path, phone=True)
    out = []
    for i in range(len(x) // RATE):
        sec = x[i * RATE:(i + 1) * RATE]
        rms = math.sqrt(float((sec * sec).mean())) if len(sec) else 0.0
        out.append(20 * math.log10(rms) if rms > 1e-9 else -120.0)
    return out


def bass_share(path: Path) -> float:
    """The share of this file's level the phone takes away: 0 is a sound
    the phone plays whole, 1 is one it does not play at all."""
    path = Path(path)
    key = hashlib.sha1(path.read_bytes()).hexdigest()
    if key not in _bass_cache:
        full = _pcm(path, phone=False)
        e_full = float((full * full).sum())
        if e_full <= 0:
            _bass_cache[key] = 0.0
        else:
            through = _pcm(path, phone=True)
            _bass_cache[key] = min(max(1.0 - float((through * through).sum()) / e_full,
                                       0.0), 1.0)
    return _bass_cache[key]


def masked_seconds(voice_stem: Path, rest_stem: Path, *,
                   margin_db: float = MARGIN_DB) -> list[int]:
    """The seconds he speaks in and leads the rest by less than the margin,
    both heard through the phone."""
    v, r = _levels(voice_stem), _levels(rest_stem)
    return [i for i, (a, b) in enumerate(zip(v, r))
            if a > SPEAKS_DB and a - b < margin_db]


def _key(path: Path) -> str:
    stem = Path(path).stem
    base, _, n = stem.rpartition("-")
    return base if base and n.isdigit() else stem


def phone_report(tracks: Sequence[AudioTrack], duration: float,
                 out_dir: Path) -> dict:
    """`{"masked": [seconds], "bass_effects": [keys]}` for one mix; empty
    when there is no voice, or nothing under it, to measure."""
    voice = next((t for t in tracks if t.voice), None)
    rest = [t for t in tracks if not t.voice]
    if voice is None or not rest or duration <= 0:
        return {}
    out_dir = Path(out_dir)
    v_stem, r_stem = out_dir / "phone_voice.wav", out_dir / "phone_rest.wav"
    try:
        render_audio(CompositeSpec(base_input_args=[], audio=[voice], duration=duration,
                                   normalise_audio=False), v_stem)
        render_audio(CompositeSpec(base_input_args=[],
                                   audio=[replace(voice, key_only=True), *rest],
                                   duration=duration, normalise_audio=False), r_stem)
        masked = masked_seconds(v_stem, r_stem)
        effects = {t.path for t in rest if not t.loop and not t.duck}
        bass = sorted({_key(p) for p in effects
                       if Path(p).exists() and bass_share(p) >= BASS_WARN})
    except Exception as e:                      # noqa: BLE001
        # A measurement, not the render: the video is already made.
        log.warning("phone check skipped: %s", e)
        return {}
    finally:
        v_stem.unlink(missing_ok=True)
        r_stem.unlink(missing_ok=True)
    return {"masked": masked, "bass_effects": bass}


def _clock(s: int) -> str:
    return f"{s // 60}:{s % 60:02d}"


def phone_line(report: dict) -> str:
    """The record's line: whether he reads, and which effects do not."""
    if not report:
        return ""
    masked = list(report.get("masked") or [])
    bits = []
    if len(masked) >= MASKED_WARN_S:
        shown = ", ".join(_clock(int(s)) for s in masked[:SHOW_S])
        more = f" +{len(masked) - SHOW_S}" if len(masked) > SHOW_S else ""
        bits.append(f"VOICE BURIED {len(masked)}s ({shown}{more})")
    else:
        bits.append("voice reads")
    bass = list(report.get("bass_effects") or [])
    bits.append(f"NO SOUND ON A PHONE: {', '.join(bass)}" if bass
                else "effects read")
    return " · ".join(bits)
