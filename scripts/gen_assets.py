"""Generate the placeholder AUDIO committed to the repo.

THE VISUAL HALF OF THIS SCRIPT IS GONE. It generated placeholder backdrops,
doodles, memes and kit assets, all of which existed because the pipeline had no
real artwork. It has 113 drawn plates now, built at ingest from the kit's own
engine, and a procedural stand-in beside them is not a fallback — it is a second
visual language that ships when the first one is missing, which is exactly how a
placeholder reaches a published video.

What is left is the audio, which the `check_audio` gate still depends on: a
MOCK_MODE render must never be silent, and nothing here has a drawn equivalent.

Run from the repo root:  .venv/bin/python scripts/gen_assets.py

Everything here is procedural (ffmpeg lavfi), seeded and deterministic — no
downloads, no licences to clear. The licensed bed and the real sfx drop over the
same filenames.

Outputs:
  assets/sfx/*.wav              the sfx palette, plus room tone
  assets/music/dennis_bed.m4a   60s lo-fi placeholder bed
"""

from __future__ import annotations

import random
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ASSETS = ROOT / "assets"
FONTS = ASSETS / "fonts"
def _lavfi(out: Path, *args: str) -> None:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args, str(out)]
    subprocess.run(cmd, check=True, capture_output=True)


def gen_sfx() -> None:
    out = ASSETS / "sfx"
    out.mkdir(parents=True, exist_ok=True)
    wav = ["-c:a", "pcm_s16le", "-ar", "44100"]

    _lavfi(out / "windows_error.wav",
           "-f", "lavfi", "-i", "sine=f=830:d=0.14",
           "-f", "lavfi", "-i", "sine=f=623:d=0.22",
           "-filter_complex",
           "[0]volume=0.7[a];[1]volume=0.7[b];[a][b]concat=n=2:v=0:a=1,afade=t=out:st=0.30:d=0.06",
           *wav)
    _lavfi(out / "cash_register.wav",
           "-f", "lavfi", "-i", "sine=f=1568:d=0.5",
           "-f", "lavfi", "-i", "sine=f=2093:d=0.5",
           "-filter_complex",
           "[0][1]amix=inputs=2:normalize=0,volume=0.5,afade=t=out:st=0.08:d=0.42",
           *wav)
    _lavfi(out / "record_scratch.wav",
           "-f", "lavfi", "-i", "anoisesrc=d=0.35:color=white:seed=7",
           "-af", "highpass=f=1800,tremolo=f=34:d=0.9,volume=0.8,afade=t=out:st=0.25:d=0.1",
           *wav)
    _lavfi(out / "sad_trombone.wav",
           "-f", "lavfi", "-i", "sine=f=392:d=0.4",
           "-f", "lavfi", "-i", "sine=f=370:d=0.4",
           "-f", "lavfi", "-i", "sine=f=349:d=0.4",
           "-f", "lavfi", "-i", "sine=f=311:d=0.7",
           "-filter_complex",
           "[0]vibrato=f=6:d=0.4[a];[1]vibrato=f=6:d=0.4[b];[2]vibrato=f=6:d=0.4[c];"
           "[3]vibrato=f=7:d=0.6,afade=t=out:st=0.3:d=0.4[d];"
           "[a][b][c][d]concat=n=4:v=0:a=1,volume=0.55",
           *wav)
    _lavfi(out / "camera_shutter.wav",
           "-f", "lavfi", "-i", "anoisesrc=d=0.03:color=white:seed=3",
           "-f", "lavfi", "-i", "anullsrc=d=0.05",
           "-f", "lavfi", "-i", "anoisesrc=d=0.04:color=white:seed=4",
           "-filter_complex",
           "[0]volume=0.9[a];[1]volume=0[b];[2]volume=0.6[c];[a][b][c]concat=n=3:v=0:a=1,highpass=f=900",
           *wav)
    _lavfi(out / "vine_boom.wav",
           "-f", "lavfi", "-i", "sine=f=52:d=0.9",
           "-af", "volume=1.4,afade=t=in:st=0:d=0.005,afade=t=out:st=0.15:d=0.75,aecho=0.8:0.6:60:0.35",
           *wav)
    # ---- the deadpan set: dry, lo-fi, no drama --------------------------
    # These are placeholders so a MOCK_MODE render is never silent. The
    # shipping versions are generated in ElevenLabs and dropped in over the
    # top — same filenames, same keys, nothing in the pipeline changes.
    _lavfi(out / "coffee_slurp.wav",
           "-f", "lavfi", "-i", "anoisesrc=d=0.42:color=brown:seed=11",
           "-af", "bandpass=f=620:width_type=h:w=400,tremolo=f=11:d=0.5,"
                  "afade=t=in:st=0:d=0.05,afade=t=out:st=0.28:d=0.14,volume=0.5",
           *wav)
    _lavfi(out / "keyboard_clack.wav",
           "-f", "lavfi", "-i", "anoisesrc=d=0.02:color=white:seed=21",
           "-f", "lavfi", "-i", "anullsrc=d=0.07",
           "-f", "lavfi", "-i", "anoisesrc=d=0.02:color=white:seed=22",
           "-f", "lavfi", "-i", "anullsrc=d=0.05",
           "-f", "lavfi", "-i", "anoisesrc=d=0.02:color=white:seed=23",
           "-filter_complex",
           "[0]volume=0.8[a];[1]volume=0[b];[2]volume=0.7[c];[3]volume=0[d];"
           "[4]volume=0.75[e];[a][b][c][d][e]concat=n=5:v=0:a=1,"
           "bandpass=f=2400:width_type=h:w=1800,volume=0.6",
           *wav)
    _lavfi(out / "paper_rustle.wav",
           "-f", "lavfi", "-i", "anoisesrc=d=0.55:color=pink:seed=31",
           "-af", "highpass=f=2200,tremolo=f=17:d=0.7,"
                  "afade=t=in:st=0:d=0.08,afade=t=out:st=0.34:d=0.2,volume=0.42",
           *wav)
    _lavfi(out / "buzzer.wav",
           "-f", "lavfi", "-i", "sine=f=196:d=0.45",
           "-f", "lavfi", "-i", "sine=f=208:d=0.45",
           "-filter_complex",
           "[0][1]amix=inputs=2:normalize=0,lowpass=f=1400,"
           "afade=t=out:st=0.34:d=0.11,volume=0.5",
           *wav)
    _lavfi(out / "ding.wav",
           "-f", "lavfi", "-i", "sine=f=1760:d=0.6",
           "-af", "afade=t=in:st=0:d=0.004,afade=t=out:st=0.05:d=0.55,volume=0.34",
           *wav)

    # UI sound used by the renderers themselves (beat transitions)
    _lavfi(out / "whoosh.wav",
           "-f", "lavfi", "-i", "anoisesrc=d=0.45:color=pink:seed=6",
           "-af", "lowpass=f=1100,afade=t=in:st=0:d=0.12,afade=t=out:st=0.2:d=0.25,volume=0.7",
           *wav)
    print("sfx: 13 written")
def gen_dennis_sfx() -> None:
    """Kit stings: beat-transition riser + zoom-punch pop."""
    out = ASSETS / "sfx"
    out.mkdir(parents=True, exist_ok=True)
    wav = ["-c:a", "pcm_s16le", "-ar", "44100"]
    _lavfi(out / "sting.wav",
           "-f", "lavfi", "-i", "sine=f=220:d=0.28",
           "-af",
           "vibrato=f=9:d=0.3,volume=0.5,afade=t=in:st=0:d=0.02,afade=t=out:st=0.14:d=0.14",
           *wav)
    _lavfi(out / "pop.wav",
           "-f", "lavfi", "-i", "sine=f=520:d=0.09",
           "-f", "lavfi", "-i", "anoisesrc=d=0.03:color=pink:seed=11",
           "-filter_complex",
           "[0]volume=0.7[a];[1]highpass=f=1200,volume=0.5[b];"
           "[a][b]amix=inputs=2:normalize=0,afade=t=in:st=0:d=0.004,afade=t=out:st=0.04:d=0.05",
           *wav)
    print("dennis sfx: 2 written")


def gen_room_tone() -> None:
    """The room he is sitting in.

    A desk at three in the morning, and the audio between words was digital
    silence — the clearest tell that a cut was assembled rather than recorded.
    Brown noise rolled off hard, a mains hum, and a slow breath in the level.
    It plays at -40dB, so it is felt rather than heard.
    """
    out = ASSETS / "sfx"
    out.mkdir(parents=True, exist_ok=True)
    _lavfi(out / "room_tone.wav",
           "-f", "lavfi", "-i", "anoisesrc=d=30:color=brown:seed=7",
           "-f", "lavfi", "-i", "sine=f=50:d=30",
           "-filter_complex",
           "[0]lowpass=f=420,highpass=f=40,volume=0.5[a];"
           "[1]volume=0.05[b];"
           "[a][b]amix=inputs=2:normalize=0,"
           "tremolo=f=0.12:d=0.22,"
           "afade=t=in:st=0:d=1.5,afade=t=out:st=28.5:d=1.5",
           "-c:a", "pcm_s16le", "-ar", "44100")
    print("room tone: 1 written")


def gen_dennis_music() -> None:
    """Lo-fi-ish placeholder bed for both formats (replace with the
    Claude Design / licensed bed in production)."""
    out = ASSETS / "music"
    out.mkdir(parents=True, exist_ok=True)
    _lavfi(out / "dennis_bed.m4a",
           "-f", "lavfi", "-i", "sine=f=98:d=60",
           "-f", "lavfi", "-i", "sine=f=146.83:d=60",
           "-f", "lavfi", "-i", "sine=f=196:d=60",
           "-f", "lavfi", "-i", "anoisesrc=d=60:color=brown:seed=21",
           "-filter_complex",
           "[0]volume=0.42[a];[1]volume=0.26,tremolo=f=0.12:d=0.8[b];"
           "[2]volume=0.16[c];[3]lowpass=f=300,volume=0.06[d];"
           "[a][b][c][d]amix=inputs=4:normalize=0,lowpass=f=700,"
           "tremolo=f=0.10:d=0.3,afade=t=in:st=0:d=2,afade=t=out:st=57:d=3,volume=0.55",
           "-c:a", "aac", "-b:a", "128k")
    print("dennis music: 1 written")