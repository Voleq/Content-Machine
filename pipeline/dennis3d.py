"""THE 3D DENNIS, PIPELINE SIDE (item 47).

A render that has him in 3D keeps one Blender process going
(`room3d/perform.py --serve`) and asks it for one shot at a time: the room's
angle, the words he says in the shot and how long it runs. What comes back is
a layer the size of the frame, him and his shadow over nothing, already behind
whatever in the room stands in front of him, to lay straight over the room's
installed picture. The kit's 2D Dennis is never mixed in: `DENNIS_3D` switches
every shot he is in, or none (`config.Settings.dennis_3d`).

Shots are kept by what they are (angle, words, timing, size), so a second
render of the same script draws nothing again.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import queue
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path

from config import detect_ffmpeg
from pipeline.render_common import RenderError, run_ffmpeg

log = logging.getLogger(__name__)

REPO = Path(__file__).resolve().parent.parent
WORKER = REPO / "room3d" / "perform.py"
ROOM3D_AUTHOR = "room3d"
# Bumped whenever how he is built or moves changes, so no older shot is reused.
LOOK_VERSION = "47-64-7"

# How long one shot may take before the worker is taken for hung: a fixed
# allowance for Blender to come up, and a generous one per frame (a Cycles
# frame on a CPU is seconds to a minute; ten times that is not a slow frame).
# Without it a wedged Blender held the render worker — and the whole queue —
# for ever, past any /cancel.
SHOT_BASE_TIMEOUT_S = 600.0
FRAME_TIMEOUT_S = 300.0


def _python(settings) -> list[str]:
    return shlex.split(settings.dennis_3d_python) if settings.dennis_3d_python else [sys.executable]


_BPY_FOUND: set[tuple[str, ...]] = set()
# What the worker imports, run where it runs. `import bpy` alone passed a
# Python that then failed every shot on the next import down (Pillow, or
# anything `motion` reaches into `pipeline` for).
_PROBE = ("import sys; sys.path[:0] = ['room3d', '.']; "
          "import bpy, PIL, numpy, motion, dennis, pipeline.host")
# Why the last probe said no, for the error that names it.
_PROBE_ERROR: dict[tuple[str, ...], str] = {}


def _has_bpy(python: tuple[str, ...]) -> bool:
    """Whether `python` can run the worker: Blender's module and everything
    the worker imports. Only a YES is remembered: a cached no meant
    installing bpy took a bot restart to be noticed."""
    if python in _BPY_FOUND:
        return True
    try:
        got = subprocess.run([*python, "-c", _PROBE], capture_output=True,
                             text=True, cwd=str(REPO), timeout=300)
        ok = got.returncode == 0
        lines = (got.stderr or "").strip().splitlines()
        _PROBE_ERROR[python] = lines[-1] if lines else f"exit {got.returncode}"
    except (OSError, subprocess.TimeoutExpired) as e:
        ok = False
        _PROBE_ERROR[python] = f"{type(e).__name__}: {e}"
    if ok:
        _BPY_FOUND.add(python)
        _PROBE_ERROR.pop(python, None)
    return ok


_has_bpy.cache_clear = _BPY_FOUND.clear      # type: ignore[attr-defined]


def wanted(settings) -> bool:
    """Whether this render draws him in 3D. `on` without Blender is an error,
    not a quiet fall back to the 2D Dennis."""
    mode = (settings.dennis_3d or "off").strip().lower()
    if mode in ("", "off", "0", "false", "no"):
        return False
    ok = WORKER.exists() and _has_bpy(tuple(_python(settings)))
    if mode == "auto":
        return ok
    if not ok:
        python = tuple(_python(settings))
        why = _PROBE_ERROR.get(python, "")
        raise RenderError(
            f"DENNIS_3D=on but {' '.join(python)} cannot run the 3D worker"
            f"{f' ({why})' if why else ''}. It needs Python 3.11 with "
            "`pip install bpy==5.0.1 pillow`; point DENNIS_3D_PYTHON at it, "
            "or set DENNIS_3D=off for the drawn Dennis.")
    return True


def angle_of(plate) -> tuple[str, str, str] | None:
    """(angle, season, aspect) of a 3D room, or None for a drawn one."""
    if plate is None or getattr(plate, "author", "") != ROOM3D_AUTHOR:
        return None
    name = plate.key.rsplit("/", 1)[-1]
    aspect = "9x16" if name.endswith("-9x16") else "16x9"
    stem = name.rsplit("-", 1)[0] if name.endswith(("-9x16", "-16x9")) else name
    season = "plain"
    if stem.endswith("-christmas"):
        stem, season = stem[: -len("-christmas")], "christmas"
    return stem, season, aspect


def drawn_rooms(reg, aspect: str) -> list[str]:
    """The rooms at `aspect` (`16x9`, `9x16`) the kit still has drawn,
    where the 3D Dennis cannot stand. A render draws him in 3D only where
    this is empty: he is in every shot or in none."""
    out = []
    for key, plate in reg.all_plates().items():
        if getattr(plate, "family", "") != "room":
            continue
        if ("9x16" if key.endswith("-9x16") else "16x9") == aspect and angle_of(plate) is None:
            out.append(key)
    return sorted(out)


def usable(settings, reg, aspect: str) -> bool:
    """`wanted`, and every room at `aspect` the 3D room. `on` with a drawn
    room in the kit is an error: the kit ingest was not rerun."""
    if not wanted(settings):
        return False
    drawn = drawn_rooms(reg, aspect)
    if not drawn:
        return True
    if (settings.dennis_3d or "").strip().lower() == "auto":
        log.info("3D Dennis off for this %s render: %d drawn rooms in the kit (%s ...)",
                 aspect, len(drawn), drawn[0])
        return False
    raise RenderError(
        f"DENNIS_3D=on but {len(drawn)} of the kit's {aspect} rooms are still drawn "
        f"({', '.join(drawn[:3])} ...), and he is never 3D in one shot and drawn in "
        "the next. Rerun `python scripts/ingest_kit.py kit`, or set DENNIS_3D=off.")


class Performer:
    """The Blender process and the shots it has drawn."""

    def __init__(self, settings, cache: Path | None = None, *, draft: bool = False):
        self.settings = settings
        # A proof's performer draws him at half the size each way, a quarter
        # of the work: the proof's voice is not the final's, so the final
        # draws every shot of him again anyway, to its own words.
        self.draft = draft
        self.cache = Path(cache or Path(settings.cache_dir) / "dennis3d")
        self.cache.mkdir(parents=True, exist_ok=True)
        self._proc: subprocess.Popen | None = None
        self._err = None
        self._lines: "queue.Queue[str | None] | None" = None
        self.shots: list[dict] = []          # what each shot cost, for the manifest

    # ------------------------------------------------------------------ worker
    def _start(self) -> subprocess.Popen:
        if self._proc is not None and self._proc.poll() is None:
            return self._proc
        if self._err is not None:            # a worker that died: its log handle
            self._err.close()
        self._err = open(self.cache / "worker.log", "a", encoding="utf-8")
        env = dict(os.environ, PYTHONUNBUFFERED="1")
        self._proc = subprocess.Popen(
            [*_python(self.settings), str(WORKER), "--serve"], cwd=str(REPO),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._err,
            text=True, bufsize=1, env=env)
        # Lines are read on a thread so a shot can be waited on with a
        # deadline; a blocking `for line in stdout` could not be.
        self._lines = queue.Queue()

        def pump(out, q) -> None:
            for line in out:
                q.put(line)
            q.put(None)                        # EOF

        threading.Thread(target=pump, args=(self._proc.stdout, self._lines),
                         daemon=True, name="dennis3d-out").start()
        return self._proc

    def _ask(self, job: dict) -> dict:
        proc = self._start()
        frames = 1 if job.get("still") else (
            float(job.get("duration") or 0) * float(job.get("fps") or 12) + 1)
        deadline = time.monotonic() + SHOT_BASE_TIMEOUT_S + frames * FRAME_TIMEOUT_S
        try:
            proc.stdin.write(json.dumps(job) + "\n")
            proc.stdin.flush()
            while True:
                left = deadline - time.monotonic()
                if left <= 0:
                    self._kill()
                    raise RenderError(
                        f"the 3D Dennis worker took longer than "
                        f"{SHOT_BASE_TIMEOUT_S + frames * FRAME_TIMEOUT_S:.0f}s "
                        f"on one shot ({job.get('angle')}) and was stopped")
                try:
                    line = self._lines.get(timeout=min(left, 5.0))
                except queue.Empty:
                    continue
                if line is None:
                    break                      # the worker closed its output
                if line.startswith("@@"):
                    return json.loads(line[2:])
                log.debug("blender: %s", line.rstrip())
        except BrokenPipeError:
            pass
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self._kill()
        self._err.flush()
        tail = (self.cache / "worker.log").read_text(encoding="utf-8", errors="replace")[-2000:]
        raise RenderError(f"the 3D Dennis worker stopped (exit {proc.poll()}):\n{tail}")

    def _kill(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            self._proc.kill()
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
        self._proc = None

    def close(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            try:
                self._proc.stdin.write("\n")
                self._proc.stdin.flush()
                self._proc.wait(timeout=60)
            except (OSError, subprocess.TimeoutExpired):
                self._proc.kill()
        self._proc = None
        if self._err is not None:
            self._err.close()
            self._err = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ------------------------------------------------------------------ shots
    def shot(self, room, words, start: float, duration: float, size: tuple[int, int],
             *, seed: str, stance: str = "", plate: tuple[float, float] | None = None,
             close: bool = False, push: dict | None = None) -> Path:
        """His layer for one shot in `room`: an RGBA .mov, `size` big, at
        `dennis_3d_fps`. `words` carry `.word`, `.start`, `.end` on the
        programme clock; `start` is the shot's start on it. `stance` is the
        kit pose he plays; `plate` is where a two-shot's evidence sits in the
        frame (0-1 from the top left), for him to show; `close` is the
        close-up, whose background is `window(layer)` of the room's picture;
        `push` the push-in on a chapter's wide shot (`{"z", "t0", "t1"}`: how
        many times closer it ends, between which seconds of the shot), whose
        background is `pushed(layer)`, a piece of the room for every frame.
        A draft performer's layer is half `size`; whoever lays it in scales
        it to the frame."""
        where = angle_of(room)
        if where is None:
            raise RenderError(f"{getattr(room, 'key', room)} is not a 3D room")
        angle, season, aspect = where
        if self.draft:
            size = (max(size[0] // 4 * 2, 2), max(size[1] // 4 * 2, 2))
        fps = int(self.settings.dennis_3d_fps)
        job = {"angle": angle, "season": season, "aspect": aspect, "size": list(size),
               "fps": fps, "samples": int(self.settings.dennis_3d_samples),
               "seed": seed, "stance": stance, "duration": round(float(duration), 4),
               **({"plate": [round(float(c), 4) for c in plate]} if plate else {}),
               **({"close": True} if close else {}),
               **({"push": {k: round(float(v), 3) for k, v in push.items()}}
                  if push else {}),
               "words": [{"word": w.word, "start": round(w.start - start, 3),
                          "end": round(w.end - start, 3)} for w in words]}
        key = hashlib.sha256(json.dumps({**job, "v": LOOK_VERSION},
                                        sort_keys=True).encode()).hexdigest()[:20]
        folder = self.cache / key
        layer = folder / "layer.mov"
        if layer.exists():
            self.shots.append({"angle": angle, "aspect": aspect, "cached": True})
            return layer
        reply = self._ask({**job, "out": str(folder / "frames")})
        if not reply.get("ok"):
            raise RenderError(f"the 3D Dennis could not draw {angle}: {reply.get('error')}\n"
                              f"{reply.get('trace', '')}")
        part = folder / "layer.part.mov"
        run_ffmpeg(["-framerate", str(fps), "-i", str(folder / "frames" / "d_%04d.png"),
                    "-c:v", "png", "-pix_fmt", "rgba", "-f", "mov", str(part)])
        if reply.get("window"):
            (folder / "window.json").write_text(json.dumps(reply["window"]), encoding="utf-8")
        if reply.get("push"):
            (folder / "push.json").write_text(json.dumps(reply["push"]), encoding="utf-8")
        part.replace(layer)
        self.shots.append({"angle": angle, "aspect": aspect, "frames": reply.get("frames"),
                           "seconds": reply.get("seconds"), "device": reply.get("device")})
        return layer

    def still(self, room, size: tuple[int, int], *, seed: str, stance: str = "",
              in_room: bool = False) -> Path:
        """Him for a cover: one RGBA frame, `size` big, standing on `room`'s
        spot as its camera sees him, caught mid-sentence, with nothing of the
        room drawn (no shadow, nothing in front of him), so the cover can
        stand him where its type leaves room; `in_room`, as a shot has him,
        the desk in front of him and his shadow on the room. A stance that
        turns him from the camera is played to it."""
        where = angle_of(room)
        if where is None:
            raise RenderError(f"{getattr(room, 'key', room)} is not a 3D room")
        angle, season, aspect = where
        job = {"angle": angle, "season": season, "aspect": aspect, "size": list(size),
               "fps": int(self.settings.dennis_3d_fps),
               "samples": max(int(self.settings.dennis_3d_samples), 16),
               "seed": seed, "stance": stance, "still": True,
               **({"in_room": True} if in_room else {})}
        key = hashlib.sha256(json.dumps({**job, "v": LOOK_VERSION},
                                        sort_keys=True).encode()).hexdigest()[:20]
        folder = self.cache / key
        out = folder / "still.png"
        if out.exists():
            return out
        reply = self._ask({**job, "out": str(folder / "frames")})
        if not reply.get("ok"):
            raise RenderError(f"the 3D Dennis could not draw {angle}: {reply.get('error')}\n"
                              f"{reply.get('trace', '')}")
        (folder / "frames" / "d_0000.png").replace(out)
        self.shots.append({"angle": angle, "aspect": aspect, "still": True,
                           "seconds": reply.get("seconds"), "device": reply.get("device")})
        return out

    @staticmethod
    def frames(layer: Path) -> Path:
        """The folder of his layer's frames, `d_0000.png` on: the worker's
        own, or unpacked from the layer when a clean-up took them."""
        folder = Path(layer).parent / "frames"
        if not (folder / "d_0000.png").exists():
            folder.mkdir(parents=True, exist_ok=True)
            run_ffmpeg(["-i", str(layer), "-start_number", "0",
                        str(folder / "d_%04d.png")])
        return folder

    @staticmethod
    def window(layer: Path) -> tuple[float, float, float, float] | None:
        """For a close-up's layer, the piece of the room's picture behind him
        (x0, y0, x1, y1, 0-1 from the top left); None for any other shot."""
        f = Path(layer).parent / "window.json"
        if not f.exists():
            return None
        x0, y0, x1, y1 = json.loads(f.read_text(encoding="utf-8"))
        return float(x0), float(y0), float(x1), float(y1)


def pushed(layer: Path) -> list[tuple[float, float, float, float]] | None:
    """For a push-in's layer, the piece of the room's picture behind him on
    every frame (x0, y0, x1, y1, 0-1 from the top left); None otherwise."""
    f = Path(layer).parent / "push.json"
    if not f.exists():
        return None
    return [tuple(float(c) for c in w) for w in json.loads(f.read_text(encoding="utf-8"))]


def _presence(layer: Path, size: tuple[int, int]):
    """Every pixel of him in any frame of his layer, read off the alpha at an
    eighth of `size`: a (h, w) bool array, or None when it cannot be read."""
    import numpy as np

    W, H = size
    w, h = max(W // 8, 1), max(H // 8, 1)
    try:
        raw = subprocess.run(
            [detect_ffmpeg()[0], "-loglevel", "error", "-i", str(layer), "-vf",
             f"alphaextract,scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
            capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    n = len(raw) // (w * h)
    if not n:
        return None
    return (np.frombuffer(raw[:n * w * h], np.uint8).reshape(n, h, w) > 64).any(axis=0)


def extent(layer: Path, size: tuple[int, int]) -> tuple[int, int, int, int] | None:
    """Where he is in his layer over the whole shot: the box (x0, y0, x1, y1,
    frame pixels) round every pixel of him in any frame, read off the alpha at
    an eighth of the size. None when there is nothing of him, or it cannot be
    read."""
    import numpy as np

    him = _presence(layer, size)
    if him is None:
        return None
    W, H = size
    h, w = him.shape
    ys, xs = np.nonzero(him)
    if not len(xs):
        return None
    return (int(xs.min() * W / w), int(ys.min() * H / h),
            int(min((xs.max() + 1) * W / w, W)), int(min((ys.max() + 1) * H / h, H)))


def under(layer: Path, size: tuple[int, int], rect: tuple[int, int, int, int],
          margin: int = 0) -> bool | None:
    """Whether any pixel of him, in any frame of the shot, falls inside `rect`
    (x0, y0, x1, y1, frame pixels) grown by `margin`: what a card laid there
    would cover of him. None when his layer cannot be read."""
    him = _presence(layer, size)
    if him is None:
        return None
    W, H = size
    h, w = him.shape
    x0, y0, x1, y1 = rect
    c0 = max(int((x0 - margin) * w / W), 0)
    r0 = max(int((y0 - margin) * h / H), 0)
    c1 = min(-(-(x1 + margin) * w // W), w)
    r1 = min(-(-(y1 + margin) * h // H), h)
    if c1 <= c0 or r1 <= r0:
        return False
    return bool(him[r0:r1, c0:c1].any())
