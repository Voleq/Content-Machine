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
import shlex
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

from pipeline.render_common import RenderError, run_ffmpeg

log = logging.getLogger(__name__)

REPO = Path(__file__).resolve().parent.parent
WORKER = REPO / "room3d" / "perform.py"
ROOM3D_AUTHOR = "room3d"
# Bumped whenever how he is built or moves changes, so no older shot is reused.
LOOK_VERSION = "47-64-2"


def _python(settings) -> list[str]:
    return shlex.split(settings.dennis_3d_python) if settings.dennis_3d_python else [sys.executable]


@lru_cache(maxsize=4)
def _has_bpy(python: tuple[str, ...]) -> bool:
    try:
        return subprocess.run([*python, "-c", "import bpy"], capture_output=True,
                              timeout=300).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


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
        raise RenderError(
            "DENNIS_3D=on but Blender's Python module does not import "
            f"({' '.join(_python(settings))} -c 'import bpy'). Install it with "
            "`pip install bpy`, point DENNIS_3D_PYTHON at a Python that has it, "
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


class Performer:
    """The Blender process and the shots it has drawn."""

    def __init__(self, settings, cache: Path | None = None):
        self.settings = settings
        self.cache = Path(cache or Path(settings.cache_dir) / "dennis3d")
        self.cache.mkdir(parents=True, exist_ok=True)
        self._proc: subprocess.Popen | None = None
        self._err = None
        self.shots: list[dict] = []          # what each shot cost, for the manifest

    # ------------------------------------------------------------------ worker
    def _start(self) -> subprocess.Popen:
        if self._proc is not None and self._proc.poll() is None:
            return self._proc
        self._err = open(self.cache / "worker.log", "a", encoding="utf-8")
        env = dict(os.environ, PYTHONUNBUFFERED="1")
        self._proc = subprocess.Popen(
            [*_python(self.settings), str(WORKER), "--serve"], cwd=str(REPO),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._err,
            text=True, bufsize=1, env=env)
        return self._proc

    def _ask(self, job: dict) -> dict:
        proc = self._start()
        try:
            proc.stdin.write(json.dumps(job) + "\n")
            proc.stdin.flush()
            for line in proc.stdout:
                if line.startswith("@@"):
                    return json.loads(line[2:])
                log.debug("blender: %s", line.rstrip())
        except BrokenPipeError:
            pass
        proc.wait(timeout=30)
        self._err.flush()
        tail = (self.cache / "worker.log").read_text(encoding="utf-8", errors="replace")[-2000:]
        raise RenderError(f"the 3D Dennis worker stopped (exit {proc.poll()}):\n{tail}")

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
             *, seed: str, stance: str = "") -> Path:
        """His layer for one shot in `room`: an RGBA .mov, `size` big, at
        `dennis_3d_fps`. `words` carry `.word`, `.start`, `.end` on the
        programme clock; `start` is the shot's start on it."""
        where = angle_of(room)
        if where is None:
            raise RenderError(f"{getattr(room, 'key', room)} is not a 3D room")
        angle, season, aspect = where
        fps = int(self.settings.dennis_3d_fps)
        job = {"angle": angle, "season": season, "aspect": aspect, "size": list(size),
               "fps": fps, "samples": int(self.settings.dennis_3d_samples),
               "seed": seed, "stance": stance, "duration": round(float(duration), 4),
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
        part.replace(layer)
        self.shots.append({"angle": angle, "aspect": aspect, "frames": reply.get("frames"),
                           "seconds": reply.get("seconds"), "device": reply.get("device")})
        return layer
