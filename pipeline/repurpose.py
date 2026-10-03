"""SHORT-from-LONG repurposing (§6): one render feeds two platforms.

Picks the highest-density ~55–60s window of a finished LONG (density =
weighted cue count from the render manifest), snaps the cut to word
boundaries using the cached TTS timestamps, and produces a 9:16
center-crop with ONE encode. No TTS, no fetches, no new paid anything.

The LONG burns no captions (its `.srt` goes up with it), and a vertical clip
is watched with the sound off, so each cut burns its own: the short's phrase
captions, from the long's word timings on the clip's own clock.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Sequence

from config import Settings
from pipeline.models import WordTimestamp
from pipeline.render_common import (encode_profile, ffprobe_duration,
                                    run_ffmpeg)
from pipeline.rasters import build_phrase_ass

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
    retention: dict | None = None,
) -> tuple[float, float]:
    """Slide candidate windows over the cue list; densest one wins.
    Candidates start slightly before each cue (so the window opens on
    action) plus t=0. Ties go to the earliest window.

    `avoid` holds (start, end) ranges already taken. A candidate is excluded
    when its own window would overlap one — plus `min_gap_s` of breathing
    room, so two clips are two different moments rather than the same moment
    shifted a few seconds.

    `retention` REPLACES the density guess when it exists (34). Cue density is
    a proxy for "where is the interesting minute"; once the long has been
    published and watched, the peaks are not a proxy at all. The heuristic
    stays as the fallback, because most clips are cut the day the long ships
    and there is nothing to read yet."""
    if duration <= window_s:
        return 0.0, duration

    def density(start: float) -> float:
        end = start + window_s
        s = 0.0
        for c in cues:
            if start <= c["t"] <= end:
                s += _WEIGHTS.get(c["kind"], 0.5)
                # a meme near the END of the window = a natural comedic payoff
                if c["kind"] == "meme" and c["t"] > end - 12:
                    s += 1.5
        return s

    def held(start: float) -> float:
        from pipeline.retention_lines import _rows_of, hold_over

        got = hold_over(_rows_of(retention), duration, start,
                        min(start + window_s, duration))
        # A window the curve says nothing about falls back to its density, so
        # partial retention data never scores a window at zero.
        return got[0] if got is not None else 0.0

    score = held if retention else density

    candidates = {0.0}
    for c in cues:
        candidates.add(min(max(c["t"] - 2.0, 0.0), duration - window_s))
    if retention:
        # The cues say where the DIRECTOR put something. With a retention
        # curve the question is where the VIEWERS stayed, and the two need
        # not coincide — so the search stops being limited to moments the
        # director marked and sweeps the whole video.
        step = max(2.0, window_s / 8.0)
        at = 0.0
        while at <= duration - window_s:
            candidates.add(round(at, 3))
            at += step
    if avoid:
        def clear(s: float) -> bool:
            e = s + window_s
            return all(e + min_gap_s <= ts or s >= te + min_gap_s
                       for ts, te in avoid)

        candidates = {s for s in candidates if clear(s)}
        if not candidates:
            return None, None       # nothing left that doesn't overlap
    best_start = max(sorted(candidates), key=score)

    # SNAP TO A SPOKEN BOUNDARY (I2). `words` is None whenever the TTS cache
    # has been swept — the retention timer deletes the `.m4a`/`.wav` — and
    # this used to cut wherever the score landed, which is mid-word as often
    # as not. The cue times are the fallback: they are positioned off the
    # same master clock and a cue lands on a phrase boundary by
    # construction, so they are a coarser version of the same information
    # rather than a different kind of guess.
    boundaries = [w.start for w in (words or [])]
    if not boundaries:
        boundaries = sorted({float(c["t"]) for c in cues if c.get("t") is not None})
    if boundaries:
        valid = [b for b in boundaries if b <= duration - window_s]
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
    retention: dict | None = None,
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
                                      avoid=taken, min_gap_s=min_gap_s,
                                      retention=retention)
        if start is None:
            break
        taken.append((start, end))
    return taken


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
    # The voice cache may have been cleared since the render; the render
    # wrote its own word timings beside the video, and those are the same
    # clock. Without either the clips cut on the manifest's beats and carry
    # no captions, which the clip's record says.
    if not words:
        words = saved_words(long_mp4.parent)
    windows = pick_best_windows(manifest.get("cues", []), duration, n=n,
                                words=words)
    out_dir = out_dir or long_mp4.parent
    results: list[tuple[Path, dict]] = []
    for i, (start, end) in enumerate(windows, 1):
        dest = out_dir / f"short_repurposed_{i}.mp4"
        path, info = _cut_window(long_mp4, start, end, dest, settings,
                                 words=words)
        info["rank"] = i
        info["of"] = len(windows)
        path.with_suffix(".repurpose.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
        results.append((path, info))
    log.info("repurpose: %d clip(s) from a %.0fs LONG", len(results), duration)
    return results


def saved_words(ws_path: Path) -> list[WordTimestamp] | None:
    """The long's word timings as the render saved them, or None."""
    from pipeline.retention_lines import load_words

    out: list[WordTimestamp] = []
    for r in load_words(ws_path, "long"):
        try:
            start = float(r["start"])
            out.append(WordTimestamp(
                word=str(r.get("word", "")), start=start,
                end=max(float(r.get("end", start)), start),
                char_start=int(r.get("char_start", 0) or 0),
                char_end=int(r.get("char_end", 0) or 0)))
        except (KeyError, TypeError, ValueError):
            continue
    return out or None


def clip_words(words: Sequence[WordTimestamp] | None, start: float,
               end: float) -> list[WordTimestamp]:
    """The words said inside [start, end), on the clip's own clock."""
    out: list[WordTimestamp] = []
    for w in words or ():
        if start - 1e-6 <= w.start < end:
            out.append(w.model_copy(update={
                "start": max(w.start - start, 0.0),
                "end": max(min(w.end, end) - start, 0.0)}))
    return out


def _caption_file(words: list[WordTimestamp], length: float, out_path: Path,
                  settings: Settings) -> Path | None:
    """The short's phrase captions for one clip, or None with nothing said.

    The short's own sizes, read off the short's frame: a clip cut from the
    long goes out in the same feed as a short and reads the same way.
    """
    if not words:
        return None
    from pipeline.compose import CAPTION_SIDE_FW, CAPTION_TYPE_FH

    W, H = settings.short_resolution
    ass = out_path.with_suffix(".ass")
    ass.write_text(build_phrase_ass(
        words, settings=settings, play_res=(W, H),
        font_size=int(H * CAPTION_TYPE_FH), margin_v=int(H * 0.13),
        margin_h=int(W * CAPTION_SIDE_FW), max_words=4, min_words=2,
        max_chars=24, key_words=True, duration=length), encoding="utf-8")
    return ass


def _ass_filter(ass: Path, settings: Settings) -> str:
    """libass over the picture, with the kit's fonts — escaped the way
    libavfilter asks (`render_short.final_encode`)."""
    spec = str(ass).replace("\\", "/").replace(":", "\\:")
    fonts = str(settings.fonts_dir).replace("\\", "/").replace(":", "\\:")
    return f"ass='{spec}':fontsdir='{fonts}'"


def _cut_window(long_mp4: Path, start: float, end: float, out_path: Path,
                settings: Settings, *,
                words: Sequence[WordTimestamp] | None = None
                ) -> tuple[Path, dict]:
    """One 9:16 cut, its captions burned. Shared by the single- and
    multi-clip paths."""
    length = end - start
    W, H = settings.short_resolution
    said = clip_words(words, start, end)
    ass = _caption_file(said, length, out_path, settings)
    # ONE ENCODE, THROUGH THE PROJECT'S PROFILE (I1).
    #
    # A correction to the diagnosis first: this cannot stream-copy. The whole
    # point of the cut is 16:9 -> 9:16, and a crop changes the geometry —
    # there is no keyframe alignment that lets `-c:v copy` produce a
    # differently-shaped picture. Cutting on a keyframe and re-encoding only
    # the lead-in is a concat-of-two-sources trick that buys nothing here,
    # because every frame needs re-encoding anyway.
    #
    # What was actually wasteful is that this hardcoded libx264 and the
    # project's final preset while the render path resolves an encoder,
    # including NVENC when the box has one — so the machine that had just
    # spent hours on the GPU did three more clips on the CPU. It uses the
    # same profile as a SHORT final now.
    profile = encode_profile(settings, "short")
    run_ffmpeg([
        "-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", str(long_mp4),
        "-vf",
        f"crop=trunc(ih*{W}/{H}/2)*2:ih,scale={W}:{H}:flags=lanczos,setsar=1"
        + (f",{_ass_filter(ass, settings)}" if ass is not None else ""),
        "-af", f"afade=t=in:st=0:d=0.25,afade=t=out:st={max(length - 0.4, 0):.3f}:d=0.4",
        *profile.video_args(),
        "-c:a", "aac", "-b:a", settings.audio_bitrate,
        "-movflags", "+faststart",
        str(out_path),
    ])
    return out_path, {
        "source": str(long_mp4),
        "window": [start, end],
        "duration": ffprobe_duration(out_path),
        "captions": len(said) if ass is not None else 0,
        "note": "repurposed from LONG — zero new TTS/fetch spend",
    }
