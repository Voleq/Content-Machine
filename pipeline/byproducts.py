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

**By-products.** The kit ships cover, social and end-screen layouts, and a
finished render used to produce one thumbnail. The rest are free: same data,
same fonts, already drawn. A render now emits the set, so a video arrives with
the things you would otherwise make by hand at midnight.

What it emits is what the kit actually holds — measured, and reported when it
falls short of an ask. It used to say eight thumbnail layouts; there are three,
and the other five were being taken from `scenes/`, which is chapter
backdrops. A folder with eight files in it looked finished either way.
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
#
# `wanted` is a real ASK — how many distinct layouts the channel wants — and
# it is separate from the cap because the two say different things. A cap is a
# ceiling; an ask is a number somebody owes. `None` means there is no ask and
# whatever the kit ships is the right answer.
#
# Only thumbnails carry one. The cap was 8, the kit ships 3 cover layouts, and
# the difference was being made up out of `scenes/` — chapter backdrops nobody
# drew as covers. The folder came out with seven files in it and looked
# finished. `scenes` is off the list and the gap is reported as artwork owed.
#
# The other two caps stay ceilings. Reading them as asks would invent a debt
# nobody incurred: they were deliberately set above what ships so a full
# family is never trimmed.
BYPRODUCT_FAMILIES: dict[str, tuple[tuple[str, ...], int, int | None]] = {
    "thumbnails": (("thumbnails",), 8, 8),
    "social": (("restyled/channel", "restyled/brand-scenes"), 20, None),
    "end_screens": (("chapters/resigned-close",), 12, None),
}


@dataclass
class ByProducts:
    thumbnails: list[str] = field(default_factory=list)
    social: list[str] = field(default_factory=list)
    end_screens: list[str] = field(default_factory=list)
    # `{label: {wanted, found, made}}` — what was asked for against what the
    # kit could answer. Written into byproducts.json so a short delivery is a
    # number somebody can read rather than a folder somebody has to count.
    shortfall: dict = field(default_factory=dict)

    def total(self) -> int:
        return len(self.thumbnails) + len(self.social) + len(self.end_screens)

    def owed(self) -> dict[str, int]:
        """`{label: how many layouts Design still owes}`, empty when none."""
        return {label: gap["wanted"] - gap["found"]
                for label, gap in self.shortfall.items()
                if gap.get("wanted") is not None and gap["found"] < gap["wanted"]}

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

    for label, (families, cap, wanted) in BYPRODUCT_FAMILIES.items():
        made: list[str] = []
        found = [a for fam in families for a in kit.family(fam)]
        result.shortfall[label] = {"wanted": wanted, "found": len(found),
                                   "families": list(families), "made": 0}
        if wanted is None:
            result.shortfall[label]["wanted"] = len(found)  # no ask: the kit is the answer
        assets = found[:cap]
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
        result.shortfall[label]["made"] = len(made)

    (out_dir / "byproducts.json").write_text(json.dumps(result.to_json(), indent=2), encoding="utf-8")
    log.info("by-products: %d asset(s) for %s", result.total(), ticker or "?")
    for line in report_shortfall(result):
        log.warning("%s", line)
    return result


def report_shortfall(result: ByProducts) -> list[str]:
    """One line per by-product the kit cannot fill, as a Design ask.

    Said out loud because the alternative is what was happening: the
    thumbnails cap was 8, the kit ships 3 cover layouts, and the difference
    was made up from `scenes/` — chapter backdrops nobody drew as covers. The
    folder had eight files in it and looked finished.
    """
    lines: list[str] = []
    for label, gap in sorted(result.owed().items()):
        info = result.shortfall[label]
        lines.append(
            f"{label}: {info['found']} layout(s) in "
            f"{', '.join(info['families'])}, {info['wanted']} wanted — "
            f"{gap} short. ARTWORK OWED: this is a Design ask, not something "
            f"to fill from a family that was drawn for something else.")
    return lines


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

# Measuring a BOILED render needs different numbers, and both of the defaults
# above are wrong for one — not by a little.
#
# * Scale. A boil moves the line 2-3%. On a 1920-tall frame squashed to 171
#   rows that is well under a pixel, so a frame that is visibly redrawing
#   seven times a second measures as perfectly still.
# * Rate. 2fps against a 7fps boil aliases: 0.5s is 3.5 boil frames, so every
#   other sample pair lands on the same frame of the three and reads as a
#   hold that does not exist.
#
# The old renderer moved by cutting and sliding whole elements, which those
# defaults see fine. They are kept for it. Anything drawn against the DENNIS
# kit measures with these instead.
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


def longest_hold(video: Path, **kw) -> float:
    spans = held_spans(video, **kw)
    return max((b - a for a, b in spans), default=0.0)


# --------------------------------------------------------------------------
# The same ceiling, on the LAYER LIST.
# --------------------------------------------------------------------------
# `held_spans` measures the encode, which is the backstop and costs a render
# plus a decode to consult. This reads the manifest instead: it runs in
# milliseconds, it runs before anything is encoded, and — the part the pixels
# cannot do — it NAMES the layer at fault.
#
# The rule is not "no layer may be longer than the ceiling". The numbers sheet
# is up for twenty seconds and its rows type on all the way through; the
# ticker chip is up for the whole video by design. A layer may live as long as
# it likes provided the composition keeps changing under it. What is forbidden
# is a layer that outlasts the ceiling AND contains a ceiling-long window in
# which nothing else enters or leaves the frame — which is exactly what an
# act-scoped `t_end=<next act boundary>` produces when the script puts nothing
# inside the act.


@dataclass(frozen=True)
class StillLayer:
    """One layer, and the window inside it where the frame stops changing."""

    name: str
    t_start: float
    t_end: float
    window: tuple[float, float]

    @property
    def held(self) -> float:
        return self.window[1] - self.window[0]

    def line(self) -> str:
        return (f"{self.name} ({self.t_start:.1f}s->{self.t_end:.1f}s): nothing "
                f"enters or leaves between {self.window[0]:.1f}s and "
                f"{self.window[1]:.1f}s ({self.held:.1f}s)")


def still_layers(layers: Sequence[dict], ceiling: float,
                 *, eps: float = 0.05) -> list[StillLayer]:
    """Every layer that outlives `ceiling` with the frame unchanged inside it.

    `layers` is the manifest's own list — `name`, `t_start`, `t_end`. `eps`
    is the slack that stops a layer's own endpoints, and anything landing on
    the same frame as them, from counting as a change within it.
    """
    events = sorted({round(float(l[k]), 3)
                     for l in layers for k in ("t_start", "t_end")})
    out: list[StillLayer] = []
    for l in layers:
        a, b = float(l["t_start"]), float(l["t_end"])
        if b - a <= ceiling:
            continue
        marks = [a] + [e for e in events if a + eps < e < b - eps] + [b]
        for p, q in zip(marks, marks[1:]):
            if q - p > ceiling:
                out.append(StillLayer(name=str(l["name"]), t_start=a, t_end=b,
                                      window=(p, q)))
                break
    return out
