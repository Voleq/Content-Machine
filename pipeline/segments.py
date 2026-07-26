"""Per-segment encoding: content-hash cache, parallel workers, resumable.

The LONG used to be one enormous `filter_complex` — every segment's scaling,
padding and host compositing in a single graph, one encode, all or nothing.
On a forty-minute cut that meant a changed word re-did the whole job, a
crashed machine lost the whole job, and one unresolvable asset failed the
whole job.

Here each segment is encoded to its own clip, keyed by a hash of what
actually determines its pixels: the input files (path, size, mtime), the
filter chain, the duration, the output size, the frame rate and the encode
profile. Then the clips are concatenated with `-c copy`.

Three properties fall out of that, and they are the point:

* **Incremental** — an unchanged segment is never re-encoded. Editing one
  beat re-encodes one beat.
* **Resumable** — the cache lives outside the workspace and clips are
  renamed into place atomically, so a reboot mid-render costs the segment in
  flight and nothing else. The render box is a daily driver; this matters.
* **Granular** — a segment that fails to encode falls back to a still, and
  the other thirty-nine minutes still render.

Removing Ken Burns (P3.0) is what made this possible: a still is now a plain
scale + pad, so its output depends on the asset and the size but not on
where it sits in the timeline.

Global overlays — the corner bug, the disclaimer, captions, alerts — are NOT
baked in here. They span segment boundaries, so they composite once over the
concatenated stream.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

from pipeline.render_common import (
    EncodeProfile,
    RenderError,
    ffprobe_duration,
    run_ffmpeg,
)

log = logging.getLogger(__name__)

CACHE_DIRNAME = "segments"

# A worker gets this many ffmpeg threads. Two is the sweet spot for x264 on
# short clips — more brings little and the aggregate cap is what protects the
# desktop.
THREADS_PER_WORKER = 2


def plan_workers(total_threads: int, n_segments: int) -> tuple[int, int]:
    """(workers, threads each) that together stay inside the politeness cap.

    The cap is an *aggregate*: eight concurrent ffmpeg processes each taking
    half the machine is not politeness. workers × threads never exceeds the
    budget the operator set.
    """
    budget = max(1, total_threads)
    per = min(THREADS_PER_WORKER, budget)
    workers = max(1, budget // per)
    return min(workers, max(1, n_segments)), per


# Reading a file to hash it is cheap next to encoding, but not free, so the
# digest is memoised per (path, size, mtime) for the life of the process.
_STAMP_MEMO: dict[tuple[str, int, int], str] = {}

# Above this, fall back to size+mtime. Nothing the renderer feeds a segment
# is this big — b-roll is normalised to a few seconds — so it is a guard
# against a pathological input, not a normal path.
_STAMP_MAX_BYTES = 64 * 1024 * 1024


def _file_stamp(path: Path) -> str:
    """Content identity for an input file.

    This has to be the file's *contents*, not its mtime. Most of what a
    segment consumes is generated during the render — the designed backdrop,
    the host's talking clip, the two-shot plate, the normalised filing
    screenshot — and all of it is deterministic. Keying on mtime meant a
    render that regenerated an identical backdrop saw a different segment, so
    a resumed job re-encoded almost everything. Keying on content, a
    regenerated file is the same file.
    """
    try:
        st = path.stat()
    except OSError:
        return f"{path.name}:missing"
    memo_key = (str(path), st.st_size, st.st_mtime_ns)
    hit = _STAMP_MEMO.get(memo_key)
    if hit is not None:
        return hit
    if st.st_size > _STAMP_MAX_BYTES:
        stamp = f"{path.name}:{st.st_size}:{st.st_mtime_ns}"
    else:
        digest = hashlib.sha256()
        try:
            with path.open("rb") as fh:
                for block in iter(lambda: fh.read(1 << 20), b""):
                    digest.update(block)
            stamp = f"{st.st_size}:{digest.hexdigest()[:32]}"
        except OSError:
            stamp = f"{path.name}:unreadable"
    _STAMP_MEMO[memo_key] = stamp
    return stamp


@dataclass(frozen=True)
class SegmentSpec:
    """Everything needed to encode one segment, and nothing else.

    `filter_chain` must consume the declared inputs and produce `[out]`.
    """

    index: int
    kind: str
    duration: float
    width: int
    height: int
    fps: int
    inputs: tuple[tuple[str, ...], ...]      # ffmpeg -i argument groups
    filter_chain: str
    layout: str = ""
    extra_identity: tuple[str, ...] = ()     # anything not visible in the args

    def input_files(self) -> list[Path]:
        """The real files among the input args — what the hash must notice."""
        out: list[Path] = []
        for group in self.inputs:
            for j, arg in enumerate(group):
                if arg == "-i" and j + 1 < len(group):
                    out.append(Path(group[j + 1]))
        return out

    def content_hash(self, profile: EncodeProfile) -> str:
        payload = json.dumps({
            "kind": self.kind,
            "duration": round(self.duration, 4),
            "size": [self.width, self.height],
            "fps": self.fps,
            "layout": self.layout,
            "filter": self.filter_chain,
            "inputs": [list(g) for g in self.inputs],
            "stamps": [_file_stamp(p) for p in self.input_files()],
            "profile": profile.video_args(),
            "extra": list(self.extra_identity),
        }, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:32]


@dataclass
class SegmentResult:
    index: int
    path: Path
    cached: bool
    failed: bool = False
    detail: str = ""


@dataclass
class SegmentRun:
    results: list[SegmentResult] = field(default_factory=list)

    @property
    def cached(self) -> int:
        return sum(1 for r in self.results if r.cached)

    @property
    def failures(self) -> list[SegmentResult]:
        return [r for r in self.results if r.failed]

    def clips(self) -> list[Path]:
        return [r.path for r in sorted(self.results, key=lambda r: r.index)]


def _encode_one(spec: SegmentSpec, dest: Path, profile: EncodeProfile,
                threads: int) -> None:
    """Encode one segment to `dest`, atomically."""
    part = dest.with_suffix(".part.mp4")
    args: list[str] = []
    for group in spec.inputs:
        args += list(group)
    args += [
        "-filter_complex", spec.filter_chain,
        "-map", "[out]",
        "-an",
        "-t", f"{spec.duration:.4f}",
        "-r", str(spec.fps),
        *profile.video_args(),
        # Independently decodable: the concat demuxer needs a keyframe at the
        # start of every clip or the joins glitch.
        "-g", str(max(spec.fps, 1)),
        str(part),
    ]
    try:
        run_ffmpeg(args, threads=threads)
        os.replace(part, dest)      # atomic: a crash never leaves a half clip
    finally:
        part.unlink(missing_ok=True)


def encode_segments(
    specs: Sequence[SegmentSpec],
    cache_dir: Path,
    profile: EncodeProfile,
    *,
    total_threads: int,
    fallback: Callable[[SegmentSpec], SegmentSpec | None] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> SegmentRun:
    """Encode every segment, reusing the cache, in parallel, resumably."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    workers, threads = plan_workers(total_threads, len(specs))
    log.info("segments: %d to encode, %d worker(s) × %d thread(s)",
             len(specs), workers, threads)

    run = SegmentRun()
    done = 0
    total = len(specs)

    def work(spec: SegmentSpec) -> SegmentResult:
        dest = cache_dir / f"{spec.content_hash(profile)}.mp4"
        if dest.exists() and dest.stat().st_size > 0:
            try:
                ffprobe_duration(dest)      # a truncated clip is not a hit
                return SegmentResult(spec.index, dest, cached=True)
            except RenderError:
                log.warning("segments: cached clip %s is unreadable — re-encoding",
                            dest.name)
                dest.unlink(missing_ok=True)
        try:
            _encode_one(spec, dest, profile, threads)
            return SegmentResult(spec.index, dest, cached=False)
        except Exception as e:  # noqa: BLE001
            log.warning("segment %d (%s) failed: %s", spec.index, spec.kind, e)
            # One bad asset must not cost the other thirty-nine minutes.
            if fallback is not None:
                alt = fallback(spec)
                if alt is not None:
                    try:
                        alt_dest = cache_dir / f"{alt.content_hash(profile)}.mp4"
                        if not (alt_dest.exists() and alt_dest.stat().st_size > 0):
                            _encode_one(alt, alt_dest, profile, threads)
                        return SegmentResult(spec.index, alt_dest, cached=False,
                                             failed=True,
                                             detail=f"{spec.kind}: {e}")
                    except Exception as e2:  # noqa: BLE001
                        log.error("segment %d fallback also failed: %s",
                                  spec.index, e2)
            raise RenderError(
                f"segment {spec.index} ({spec.kind}) could not be encoded "
                f"and has no fallback: {e}") from e

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(work, s): s for s in specs}
        for fut in as_completed(futures):
            run.results.append(fut.result())
            done += 1
            if on_progress is not None:
                on_progress(done, total)

    log.info("segments: %d/%d reused from cache, %d fell back",
             run.cached, total, len(run.failures))
    return run


def concat_clips(clips: Sequence[Path], out_path: Path) -> Path:
    """Join encoded segments without re-encoding them.

    `-c copy` is what keeps the cache worth having: a cached segment is
    copied through rather than decoded and re-encoded.
    """
    if not clips:
        raise RenderError("nothing to concatenate")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    listing = out_path.with_suffix(".concat.txt")
    listing.write_text("".join(
        # the demuxer's own quoting rule: single quotes doubled
        f"file '{Path(c).resolve().as_posix()}'\n" for c in clips
    ), encoding="utf-8")
    run_ffmpeg([
        "-f", "concat", "-safe", "0", "-i", str(listing),
        "-c", "copy", "-movflags", "+faststart", str(out_path),
    ])
    return out_path


def prune_cache(cache_dir: Path, keep_hashes: set[str], max_files: int = 4000) -> int:
    """Drop clips no current render refers to, oldest first.

    The cache is deliberately outside the workspace so it survives cleanup
    and reboots, which means something has to bound it.
    """
    if not cache_dir.is_dir():
        return 0
    files = sorted(cache_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime)
    removed = 0
    for f in files:
        if len(files) - removed <= max_files:
            break
        if f.stem in keep_hashes:
            continue
        f.unlink(missing_ok=True)
        removed += 1
    if removed:
        log.info("segments: pruned %d stale cached clip(s)", removed)
    return removed


def cache_size_mb(cache_dir: Path) -> float:
    if not cache_dir.is_dir():
        return 0.0
    return sum(f.stat().st_size for f in cache_dir.glob("*.mp4")) / 1e6


def clear_cache(cache_dir: Path) -> None:
    shutil.rmtree(cache_dir, ignore_errors=True)
