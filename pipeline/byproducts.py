"""Golden frames and by-products (P3.6).

Two unrelated things that share a motive: the assets and the checks that
already exist but go unused.

**Golden frames.** The render pipeline has no way to notice that it broke
something *visually*. Tests assert on filter graphs and manifests, which
catches a wrong argument and not a host who has gone invisible against a new
backdrop — a bug this project has actually shipped. So: render the fixtures,
pull key frames, compare against stored goldens with a perceptual tolerance,
and fail on a real change while ignoring encoder noise.

The tolerance is the whole design. Byte comparison fails on every ffmpeg
build; a loose threshold notices nothing. This uses a downscaled per-channel
mean-absolute-difference, which is stable across encoders and still moves
sharply when a layout shifts or a plate changes colour.

**By-products.** The kit ships eight thumbnail layouts, nine social cards and
five end screens, and a finished render currently produces one thumbnail. The
rest are free: same data, same fonts, already drawn. A render now emits the
set, so a video arrives with the things you would otherwise make by hand at
midnight.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
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


class GoldenMismatch(AssertionError):
    """A frame moved further than the tolerance allows."""


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


def extract_frames(video: Path, out_dir: Path, *, at: Sequence[float],
                   settings: Settings | None = None) -> list[Path]:
    """Pull frames at given seconds. Named by timestamp so goldens line up."""
    from pipeline.render_common import run_ffmpeg

    out_dir.mkdir(parents=True, exist_ok=True)
    out: list[Path] = []
    for t in at:
        dest = out_dir / f"t{t:07.2f}.png".replace(".", "_", 1)
        run_ffmpeg(["-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1",
                    "-y", str(dest)])
        if dest.exists():
            out.append(dest)
    return out


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
# By-products.
# --------------------------------------------------------------------------


# The kit families each by-product comes from, and how many of each to emit.
# Re-pointed at the rebuilt kit. `thumbs`/`social`/`type/end-screens` were
# families of the old ad-hoc export and no longer exist.
#
# Several families per label, because the rebuilt kit spreads them: the
# channel marks and the brand scenes are both social cards, and the caps are
# set above what each ships so nothing is silently dropped — a cap is there to
# stop a future family of two hundred swamping the folder, not to trim this
# one.
BYPRODUCT_FAMILIES: dict[str, tuple[tuple[str, ...], int]] = {
    "thumbnails": (("thumbnails", "scenes"), 8),
    "social": (("restyled/channel", "restyled/brand-scenes"), 20),
    "end_screens": (("chapters/resigned-close",), 12),
}


@dataclass
class ByProducts:
    thumbnails: list[str] = field(default_factory=list)
    social: list[str] = field(default_factory=list)
    end_screens: list[str] = field(default_factory=list)

    def total(self) -> int:
        return len(self.thumbnails) + len(self.social) + len(self.end_screens)

    def to_json(self) -> dict:
        return asdict(self)


def build_byproducts(workspace: Path, settings: Settings, *,
                     ticker: str = "", script=None, data=None) -> ByProducts:
    """Emit every by-product the kit can fill, from a finished render.

    All free: same data, same fonts, artwork already drawn. The alternative is
    the operator making them by hand at midnight, which is how a daily channel
    stops being daily.

    Best-effort per item — one unfillable layout must not cost the other
    twenty-one.
    """
    from pipeline.kit import load_kit

    kit = load_kit(settings.assets_dir)
    out_dir = workspace / "byproducts"
    out_dir.mkdir(parents=True, exist_ok=True)
    result = ByProducts()

    for label, (families, cap) in BYPRODUCT_FAMILIES.items():
        made: list[str] = []
        assets = [a for fam in families for a in kit.family(fam)][:cap]
        for asset in assets:
            src = kit.path(asset)
            if src is None:
                continue
            dest = out_dir / f"{label}_{asset.rsplit('/', 1)[-1]}.png"
            try:
                _compose(src, dest, ticker=ticker or "", settings=settings,
                         script=script, data=data)
                made.append(dest.name)
            except Exception as e:  # noqa: BLE001 - one layout, not all of them
                log.warning("by-product %s failed: %s", asset, e)
        setattr(result, label, made)

    (out_dir / "byproducts.json").write_text(json.dumps(result.to_json(), indent=2), encoding="utf-8")
    log.info("by-products: %d asset(s) for %s", result.total(), ticker or "?")
    return result


def _compose(src: Path, dest: Path, *, ticker: str, settings: Settings,
             script=None, data=None) -> Path:
    """Fill one kit layout with this video's real data.

    The layouts carry their own typography, so this overlays the few things
    that change — the ticker and one number — rather than redrawing them.
    """
    from PIL import Image, ImageDraw

    from pipeline.rasters import load_font

    with Image.open(src) as img:
        canvas = img.convert("RGBA").copy()
    draw = ImageDraw.Draw(canvas)
    w, h = canvas.size
    if ticker:
        font = load_font(settings, "DejaVuSansMono-Bold.ttf", max(18, h // 14))
        draw.text((int(w * 0.06), int(h * 0.06)), ticker.upper(),
                  font=font, fill=(35, 35, 38, 255))
    metric = _headline_metric(data)
    if metric:
        small = load_font(settings, "DejaVuSansMono-Bold.ttf", max(14, h // 22))
        draw.text((int(w * 0.06), int(h * 0.86)), metric, font=small,
                  fill=(200, 32, 42, 255))
    canvas.convert("RGB").save(dest)
    return dest


def _headline_metric(data) -> str:
    """The one number worth putting on a card, or "".

    Reuses the thumbnail's shock-metric logic so a video's by-products all say
    the same thing rather than each picking their own favourite number.
    """
    if data is None:
        return ""
    try:
        from pipeline.thumbnail import shock_metric

        return shock_metric(data) or ""
    except Exception:  # noqa: BLE001
        return ""
