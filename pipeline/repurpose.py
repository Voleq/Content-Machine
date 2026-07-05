"""SHORT-from-LONG repurposing (§6): one render feeds two platforms.

Picks the highest-density ~55–60s window of a finished LONG (density =
weighted cue count from the render manifest), snaps the cut to word
boundaries using the cached TTS timestamps, and produces a 9:16
center-crop with ONE encode. No TTS, no fetches, no new paid anything —
LONG captions are authored narrow enough to survive the crop.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from config import Settings
from pipeline.models import WordTimestamp
from pipeline.render_common import ffprobe_duration, run_ffmpeg

log = logging.getLogger(__name__)

_WEIGHTS = {
    "meme": 3.0,
    "filing": 2.5,
    "chart": 2.0,
    "asset": 2.0,
    "clip": 1.5,
    "img": 1.5,
    "sound": 1.0,
}


def pick_best_window(
    cues: list[dict],
    duration: float,
    window_s: float = 58.0,
    words: list[WordTimestamp] | None = None,
) -> tuple[float, float]:
    """Slide candidate windows over the cue list; densest one wins.
    Candidates start slightly before each cue (so the window opens on
    action) plus t=0. Ties go to the earliest window."""
    if duration <= window_s:
        return 0.0, duration

    def score(start: float) -> float:
        end = start + window_s
        s = 0.0
        for c in cues:
            if start <= c["t"] <= end:
                s += _WEIGHTS.get(c["kind"], 0.5)
                # a meme near the END of the window = a natural comedic payoff
                if c["kind"] == "meme" and c["t"] > end - 12:
                    s += 1.5
        return s

    candidates = {0.0}
    for c in cues:
        candidates.add(min(max(c["t"] - 2.0, 0.0), duration - window_s))
    best_start = max(sorted(candidates), key=score)

    if words:  # snap to a word start (that still fits) so speech isn't clipped
        valid = [w.start for w in words if w.start <= duration - window_s]
        if valid:
            best_start = min(valid, key=lambda s: abs(s - best_start))
    end = min(best_start + window_s, duration)
    return best_start, end


def repurpose_short_from_long(
    long_mp4: Path,
    manifest_path: Path,
    settings: Settings,
    out_path: Path | None = None,
    words: list[WordTimestamp] | None = None,
) -> tuple[Path, dict]:
    """Cut + center-crop the best window to 9:16. Returns (mp4, info)."""
    manifest = json.loads(manifest_path.read_text())
    duration = float(manifest["duration"])
    start, end = pick_best_window(manifest.get("cues", []), duration, words=words)
    length = end - start

    W, H = settings.short_resolution
    out_path = out_path or long_mp4.with_name("short_repurposed.mp4")
    run_ffmpeg([
        "-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", str(long_mp4),
        "-vf",
        f"crop=trunc(ih*{W}/{H}/2)*2:ih,scale={W}:{H},setsar=1",
        "-af", f"afade=t=in:st=0:d=0.25,afade=t=out:st={max(length - 0.4, 0):.3f}:d=0.4",
        "-c:v", "libx264", "-preset", settings.final_preset,
        "-crf", str(settings.short_crf), "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", settings.audio_bitrate,
        "-movflags", "+faststart",
        str(out_path),
    ])
    rendered = ffprobe_duration(out_path)
    info = {
        "source": str(long_mp4),
        "window": [start, end],
        "duration": rendered,
        "note": "repurposed from LONG — zero new TTS/fetch spend",
    }
    out_path.with_suffix(".repurpose.json").write_text(json.dumps(info, indent=2))
    return out_path, info
