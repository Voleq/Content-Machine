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
from typing import Sequence

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
    avoid: Sequence[tuple[float, float]] = (),
    min_gap_s: float = 5.0,
) -> tuple[float, float]:
    """Slide candidate windows over the cue list; densest one wins.
    Candidates start slightly before each cue (so the window opens on
    action) plus t=0. Ties go to the earliest window.

    `avoid` holds (start, end) ranges already taken. A candidate is excluded
    when its own window would overlap one — plus `min_gap_s` of breathing
    room, so two clips are two different moments rather than the same moment
    shifted a few seconds."""
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
    if avoid:
        def clear(s: float) -> bool:
            e = s + window_s
            return all(e + min_gap_s <= ts or s >= te + min_gap_s
                       for ts, te in avoid)

        candidates = {s for s in candidates if clear(s)}
        if not candidates:
            return None, None       # nothing left that doesn't overlap
    best_start = max(sorted(candidates), key=score)

    if words:  # snap to a word start (that still fits) so speech isn't clipped
        valid = [w.start for w in words if w.start <= duration - window_s]
        if valid:
            best_start = min(valid, key=lambda s: abs(s - best_start))
    end = min(best_start + window_s, duration)
    return best_start, end


def pick_best_windows(
    cues: list[dict],
    duration: float,
    n: int = 3,
    window_s: float = 58.0,
    words: list[WordTimestamp] | None = None,
    min_gap_s: float = 5.0,
) -> list[tuple[float, float]]:
    """The best `n` NON-OVERLAPPING windows, best first (P3.3).

    A forty-minute cut has more than one good minute in it, and taking only
    the top-scoring window threw the rest away. Windows are picked greedily,
    each one blocking its own span, because the two highest-scoring starts are
    almost always the same moment a couple of seconds apart — which would ship
    as two near-identical shorts.

    Fewer than `n` come back when the source is too short to hold them. That
    is the honest answer; padding the list with overlapping near-duplicates
    would not be.
    """
    if duration <= window_s:
        return [(0.0, duration)]

    taken: list[tuple[float, float]] = []
    for _ in range(max(1, n)):
        start, end = pick_best_window(cues, duration, window_s, words=words,
                                      avoid=taken, min_gap_s=min_gap_s)
        if start is None:
            break
        taken.append((start, end))
    return taken


def repurpose_short_from_long(
    long_mp4: Path,
    manifest_path: Path,
    settings: Settings,
    out_path: Path | None = None,
    words: list[WordTimestamp] | None = None,
) -> tuple[Path, dict]:
    """Cut + center-crop the best window to 9:16. Returns (mp4, info)."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
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
    out_path.with_suffix(".repurpose.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    return out_path, info


def repurpose_clips_from_long(
    long_mp4: Path,
    manifest_path: Path,
    settings: Settings,
    *,
    n: int = 3,
    words: list[WordTimestamp] | None = None,
    out_dir: Path | None = None,
) -> list[tuple[Path, dict]]:
    """The best `n` clips, not just the best one (P3.3).

    Still free — no new TTS, no new fetching, just cuts out of a finished
    render. A short LONG yields fewer than `n`; that is the honest answer
    rather than padding the list with overlapping near-duplicates.
    """
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    duration = float(manifest["duration"])
    windows = pick_best_windows(manifest.get("cues", []), duration, n=n,
                                words=words)
    out_dir = out_dir or long_mp4.parent
    results: list[tuple[Path, dict]] = []
    for i, (start, end) in enumerate(windows, 1):
        dest = out_dir / f"short_repurposed_{i}.mp4"
        path, info = _cut_window(long_mp4, start, end, dest, settings)
        info["rank"] = i
        info["of"] = len(windows)
        path.with_suffix(".repurpose.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
        results.append((path, info))
    log.info("repurpose: %d clip(s) from a %.0fs LONG", len(results), duration)
    return results


def _cut_window(long_mp4: Path, start: float, end: float, out_path: Path,
                settings: Settings) -> tuple[Path, dict]:
    """One 9:16 cut. Shared by the single- and multi-clip paths."""
    length = end - start
    W, H = settings.short_resolution
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
    return out_path, {
        "source": str(long_mp4),
        "window": [start, end],
        "duration": ffprobe_duration(out_path),
        "note": "repurposed from LONG — zero new TTS/fetch spend",
    }
