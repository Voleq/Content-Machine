"""Frame checks: golden frames and held compositions.

Two measurements of a finished render's pixels, because the tests that assert
on filter graphs and manifests catch a wrong argument and not a frame that
went wrong.

**Golden frames.** The render pipeline has no way to notice that it broke
something *visually*: a host gone invisible against a new backdrop is a bug
this project has actually shipped. So: pull key frames, compare against
stored goldens with a perceptual tolerance, and fail on a real change while
ignoring encoder noise. No goldens are committed today; the previous set was
drawn on a kit two deliveries old, and a golden is only worth blessing from a
render somebody has looked at.

The tolerance is the whole design. Byte comparison fails on every ffmpeg
build; a loose threshold notices nothing. This uses a downscaled per-channel
mean-absolute-difference, which is stable across encoders and still moves
sharply when a layout shifts or a plate changes colour.

**Held compositions.** How long the frame sits still, measured off the video
rather than inferred from the cut list (see `held_spans`).

This module used to build "by-products" too: bare room plates stamped with a
ticker, three families of them per render, from the layout families of an
earlier kit. They were written into the workspace and never delivered, so
they went with that kit. A render's real by-products (cover, subtitles, the
upload package) are `pipeline.publish`'s.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from config import Settings

log = logging.getLogger(__name__)

GOLDEN_DIRNAME = "golden"
MANIFEST_NAME = "golden.json"

# Frames are compared at this size. Small enough that encoder dithering
# averages out, large enough that a moved element still shows.
COMPARE_SIZE = (160, 90)

# The frame is scored tile by tile so a small change isn't averaged away.
TILE_GRID = (8, 6)

# Worst-tile mean absolute per-channel difference, 0-255. Below this is
# encoder noise; above it something actually changed. Measured on the cases
# that matter: ±2 dithering across half the pixels scores 0.4, a 50×50 element
# moving on a 640×360 frame scores 78, and a light-to-dark plate scores 216.
# Two orders of magnitude between noise and the smallest real change, which is
# what makes 6.0 a safe place to draw the line rather than a guess.
DEFAULT_TOLERANCE = 6.0


@dataclass
class FrameDiff:
    name: str
    distance: float
    tolerance: float

    @property
    def ok(self) -> bool:
        return self.distance <= self.tolerance

    def render(self) -> str:
        mark = "✅" if self.ok else "❌"
        return f"{mark} {self.name}: Δ{self.distance:.2f} (tolerance {self.tolerance})"


# --------------------------------------------------------------------------
# Perceptual comparison.
# --------------------------------------------------------------------------


def _load_small(path: Path):
    from PIL import Image

    with Image.open(path) as img:
        return img.convert("RGB").resize(COMPARE_SIZE, Image.BILINEAR)


def frame_distance(a: Path, b: Path) -> float:
    """Worst-tile mean absolute difference of two frames, 0-255.

    Two decisions, both load-bearing:

    **Downscale first.** At full resolution two encodes of identical source
    differ on almost every pixel by a little, and any threshold tolerating
    that would tolerate real changes too. Averaged down, encoder noise
    collapses toward zero.

    **Score the worst TILE, not the whole frame.** A frame-wide average is
    blind to small elements: a 50×50 badge moving across a 640×360 frame
    touches 2% of the pixels and scores about 3 — under any threshold that
    also survives dithering. Splitting into tiles and taking the worst one
    means a localised change registers at full strength while global noise,
    being uniform, stays low in every tile.
    """
    from PIL import ImageChops

    ia, ib = _load_small(a), _load_small(b)
    diff = ImageChops.difference(ia, ib)
    w, h = diff.size
    tw = max(1, w // TILE_GRID[0])
    th = max(1, h // TILE_GRID[1])
    worst = 0.0
    for ty in range(0, h, th):
        for tx in range(0, w, tw):
            tile = diff.crop((tx, ty, min(tx + tw, w), min(ty + th, h)))
            pixels = tile.size[0] * tile.size[1]
            if not pixels:
                continue
            hist = tile.histogram()
            total = 0.0
            for channel in range(3):
                band = hist[channel * 256:(channel + 1) * 256]
                total += sum(v * c for v, c in enumerate(band)) / pixels
            worst = max(worst, total / 3.0)
    return round(worst, 4)


def key_times(duration: float, n: int = 6) -> list[float]:
    """Evenly spaced sample points, avoiding the very edges.

    The first and last frames are the least informative — a fade in or out —
    and the most likely to differ for uninteresting reasons.
    """
    if duration <= 0:
        return []
    if duration < 2:
        return [duration / 2]
    span = duration * 0.9
    start = duration * 0.05
    step = span / max(1, n - 1)
    return [round(start + i * step, 2) for i in range(n)]


# --------------------------------------------------------------------------
# The golden set.
# --------------------------------------------------------------------------


def golden_dir(settings: Settings, name: str) -> Path:
    """Where the reference frames live.

    Configurable so a test run cannot bless frames into the repo's own
    fixtures — which is exactly what happened the first time this was written.
    """
    if settings.golden_dir:
        return Path(settings.golden_dir) / name
    return settings.fixtures_dir / GOLDEN_DIRNAME / name


def bless(frames: Sequence[Path], settings: Settings, name: str) -> int:
    """Adopt these frames as the reference. Deliberately explicit.

    Blessing has to be a decision, never a side effect of a failing run —
    otherwise the first accidental regression silently becomes the new truth.
    """
    dest = golden_dir(settings, name)
    dest.mkdir(parents=True, exist_ok=True)
    import shutil

    for f in frames:
        shutil.copy2(f, dest / f.name)
    (dest / MANIFEST_NAME).write_text(json.dumps(
        {"frames": sorted(f.name for f in frames),
         "tolerance": DEFAULT_TOLERANCE}, indent=2), encoding="utf-8")
    log.info("golden: blessed %d frame(s) for %s", len(frames), name)
    return len(frames)


def compare_against_golden(frames: Sequence[Path], settings: Settings,
                           name: str, *,
                           tolerance: float | None = None) -> list[FrameDiff]:
    """Compare fresh frames with the stored set.

    A frame with no golden is reported as a miss rather than passing quietly:
    "we have no reference for this" and "this matches" must not look alike.
    """
    ref_dir = golden_dir(settings, name)
    if not ref_dir.is_dir():
        return []
    try:
        manifest = json.loads((ref_dir / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        manifest = {}
    tol = tolerance if tolerance is not None else float(
        manifest.get("tolerance", DEFAULT_TOLERANCE))

    out: list[FrameDiff] = []
    for f in sorted(frames):
        ref = ref_dir / f.name
        if not ref.exists():
            out.append(FrameDiff(name=f.name, distance=float("inf"),
                                 tolerance=tol))
            continue
        out.append(FrameDiff(name=f.name, distance=frame_distance(ref, f),
                             tolerance=tol))
    return out


def check_report(diffs: Sequence[FrameDiff]) -> str:
    if not diffs:
        return "No goldens stored — nothing to compare against yet."
    bad = [d for d in diffs if not d.ok]
    lines = [d.render() for d in diffs]
    lines.append("")
    lines.append(f"{len(diffs) - len(bad)}/{len(diffs)} frames within tolerance")
    if bad:
        lines.append("A frame moved. If the change was intended, re-bless; if "
                     "not, this is the visual regression the render tests "
                     "cannot see.")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Held compositions: how long the frame sits still.
# --------------------------------------------------------------------------
# A cut is not evidence that anything MOVED. The filter graph can be entirely
# correct — right layers, right windows, right cue times — and still produce a
# composition that holds for twelve and a half seconds, because nothing in the
# system ever measured the output. A real SHORT came out with 72% of its
# runtime inside holds of 3s or more and four compositions carrying 40 of its
# 79 seconds, in a format whose spec is fast cuts, with a green suite.
#
# So this measures the frames. Downscaled greyscale, sampled on a fixed grid,
# mean absolute delta under the threshold means "nothing changed".

HOLD_SAMPLE_FPS = 2.0
HOLD_STILL_DELTA = 2.0      # mean |delta| below this: the frame did not change
HOLD_SCALE = "96:171"

# Measuring a BOILED render needs a finer look than the defaults above, which
# suit footage that moves by cutting and sliding whole elements.
#
# * Scale. A boil redraws the line by a few pixels. On a 1920-tall frame
#   squashed to 171 rows that is under a pixel, so a frame that is visibly
#   redrawing measures as perfectly still.
# * Rate. The kit boils a data plate through three drawings at 3fps and loops
#   a room at 12fps. At 5fps a sample pair that lands on one drawing lasts a
#   single step, well under any hold ceiling, so a boiling frame never adds
#   up to a hold that does not exist.
BOIL_SAMPLE_FPS = 5.0
BOIL_SCALE = "270:480"


def held_spans(video: Path, *, sample_fps: float = HOLD_SAMPLE_FPS,
               still_delta: float = HOLD_STILL_DELTA,
               scale: str = HOLD_SCALE) -> list[tuple[float, float]]:
    """`(start, end)` for every span the composition holds unchanged.

    Reproduce by hand with:
        ffmpeg -i in.mp4 -vf "fps=2,scale=96:171,format=gray" -f image2 out/%04d.pgm

    For a render whose motion is a boil rather than a cut, pass
    `sample_fps=BOIL_SAMPLE_FPS, scale=BOIL_SCALE` — see the note above.
    """
    import tempfile

    from PIL import Image, ImageChops, ImageStat

    from pipeline.render_common import run_ffmpeg

    step = 1.0 / sample_fps
    with tempfile.TemporaryDirectory(prefix="holds_") as td:
        out = Path(td)
        run_ffmpeg(["-i", str(video),
                    "-vf", f"fps={sample_fps},scale={scale},format=gray",
                    "-f", "image2", str(out / "%05d.pgm")])
        frames = sorted(out.glob("*.pgm"))
        if len(frames) < 2:
            return []
        imgs = [Image.open(f).convert("L").copy() for f in frames]

    spans: list[tuple[float, float]] = []
    start: int | None = None
    for i, (a, b) in enumerate(zip(imgs, imgs[1:])):
        still = ImageStat.Stat(ImageChops.difference(a, b)).mean[0] < still_delta
        if still and start is None:
            start = i
        elif not still and start is not None:
            spans.append((start * step, i * step))
            start = None
    if start is not None:
        spans.append((start * step, (len(imgs) - 1) * step))
    return spans


def holds_past(spans: Sequence[tuple[float, float]], cuts: Sequence[float],
               ceiling: float) -> list[tuple[float, float]]:
    """Every held composition longer than `ceiling`, split at the cuts.

    `spans` is what `held_spans` measured and `cuts` the times the manifest
    starts a shot. A measured hold that runs across a cut is two compositions
    the metric could not tell apart: four sentences set on the same card move
    fewer pixels than the threshold. So it is split at the cut and each piece
    judged alone, which is the rule `test_short_holds` applies to the
    committed samples. What is left over the ceiling is one shot holding.
    """
    marks = sorted({float(c) for c in cuts})
    out: list[tuple[float, float]] = []
    for a, b in spans:
        inside = [c for c in marks if a < c < b]
        for lo, hi in zip([a, *inside], [*inside, b]):
            if hi - lo > ceiling + 1e-6:
                out.append((lo, hi))
    return out
