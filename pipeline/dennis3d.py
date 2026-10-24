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

import functools
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
LOOK_VERSION = "47-64-14"     # 14: his poses at dusk, the count put down (scan, 24 Oct 2026)


@functools.cache
def _lines_digest() -> str:
    """What draws his lines from the passes (room3d/lines.py), as a short
    digest of its text."""
    return hashlib.sha256((REPO / "room3d" / "lines.py").read_bytes()).hexdigest()[:12]

# How long one shot may take before the worker is taken for hung: a fixed
# allowance for Blender to come up, and a generous one per frame (a frame is
# seconds on the GPU line pass and up to ~45 s on a CPU at 1080p; three times
# that is not a slow frame). Without it a wedged Blender held the render
# worker — and the whole queue — for ever, past any /cancel. It was 300 s a
# frame, sized for 12 drawings a second: at 30 a ten-second shot was allowed
# twenty-five hours before anyone noticed.
SHOT_BASE_TIMEOUT_S = 600.0
FRAME_TIMEOUT_S = 120.0
# The long side the 3D room is rendered at (room3d/build.py FULLS): the 10-K
# pile is drawn no bigger, so it is as sharp as the room it is laid on and
# scaled with it.
ROOM_LONG_SIDE = 2560
# The drawing rate a job without one is rendered at: Settings.dennis_3d_fps's
# default, and what perform.py assumes for a hand-made job.
DEFAULT_FPS = 30


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
    # The BASE key: the same angle at every hour. Read off `plate.key`, a
    # room seen at dusk sent "desk-front-dusk" to the worker, which has no
    # such camera, and lost its season.
    name = (getattr(plate, "base_key", "") or plate.key).rsplit("/", 1)[-1]
    aspect = "9x16" if name.endswith("-9x16") else "16x9"
    stem = name.rsplit("-", 1)[0] if name.endswith(("-9x16", "-16x9")) else name
    season = "plain"
    if stem.endswith("-christmas"):
        stem, season = stem[: -len("-christmas")], "christmas"
    return stem, season, aspect


def light_of(plate) -> str:
    """The state the 3D room's picture was rendered in (`room3d/build.py`
    `states`): the dusk sky or the night's, in the rain or not, and in
    December the bulbs at either hour. "" is the night, dry."""
    dusk = "_dusk" if getattr(plate, "hour", "") == "dusk" else ""
    where = angle_of(plate)
    if where is not None and where[1] == "christmas":
        return "_t0" + dusk
    return dusk + ("_rain" if getattr(plate, "weather", "") == "rain" else "")


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

    def __init__(self, settings, cache: Path | None = None, *, draft: bool = False,
                 pile: int = 0):
        self.settings = settings
        # How many read 10-Ks are on his floor this video (V12,
        # `room_dressing.pile_count`): in every shot, for his shadow to fall
        # on, and drawn on its own for the room's pictures (`pile_layer`).
        self.pile = int(pile)
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
            float(job.get("duration") or 0) * float(job.get("fps") or DEFAULT_FPS) + 1)
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
             close: bool = False, push: dict | None = None, then=None) -> Path:
        """His layer for one shot in `room`: an RGBA .mov, `size` big, at
        `dennis_3d_fps`. `words` carry `.word`, `.start`, `.end` on the
        programme clock; `start` is the shot's start on it. `stance` is the
        kit pose he plays; `plate` is where a two-shot's evidence sits in the
        frame (0-1 from the top left), for him to show; `close` is the
        close-up, whose background is `window(layer)` of the room's picture;
        `push` the push-in on a chapter's wide shot (`{"z", "t0", "t1"}`: how
        many times closer it ends, between which seconds of the shot), whose
        background is `pushed(layer)`, a piece of the room for every frame.
        `then` is the room the next shot cuts to: he turns his head toward
        its camera as this one ends (the cut on his look).
        A draft performer's layer is half `size`; whoever lays it in scales
        it to the frame."""
        where = angle_of(room)
        if where is None:
            raise RenderError(f"{getattr(room, 'key', room)} is not a 3D room")
        angle, season, aspect = where
        nxt = angle_of(then) if then is not None else None
        cue = nxt[0] if nxt is not None and nxt[2] == aspect and nxt[0] != angle else ""
        if self.draft:
            size = (max(size[0] // 4 * 2, 2), max(size[1] // 4 * 2, 2))
        fps = int(self.settings.dennis_3d_fps)
        job = {"angle": angle, "season": season, "aspect": aspect, "size": list(size),
               "fps": fps, "samples": int(self.settings.dennis_3d_samples),
               "seed": seed, "stance": stance, "duration": round(float(duration), 4),
               **self._jumper(),
               **({"plate": [round(float(c), 4) for c in plate]} if plate else {}),
               **({"close": True} if close else {}),
               **({"push": {k: round(float(v), 3) for k, v in push.items()}}
                  if push else {}),
               **({"next": cue} if cue else {}),
               **self._room(room),
               **self._line_style(),
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
        if reply.get("events"):
            (folder / "events.json").write_text(json.dumps(reply["events"]), encoding="utf-8")
        part.replace(layer)
        # THE LAYER IS THE CACHE; ITS FRAMES ARE NOT KEPT BESIDE IT. The long
        # reads the .mov and nothing else, and `frames()` unpacks them for
        # the short when it needs them. Kept, every shot was stored twice, a
        # hundred gigabytes and more on a long at 1080p (scan, 24 Oct 2026).
        import shutil

        shutil.rmtree(folder / "frames", ignore_errors=True)
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
               "seed": seed, "stance": stance, "still": True, **self._jumper(),
               **({"in_room": True} if in_room else {}), **self._room(room),
               **self._line_style()}
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

    def pile_layer(self, room, size: tuple[int, int]) -> Path | None:
        """The read 10-Ks alone in `room` (V12): a picture of `size`'s shape,
        no bigger than the room was rendered (half that for a draft), the
        pile and its shadow over nothing, lit as the room's picture is, to
        lay on every picture of the room at its size. None with no pile, in a
        drawn room, or where the pile is not in shot; a pile that could not
        be drawn is said in the log and left out, never worth a render."""
        where = angle_of(room)
        if not self.pile or where is None:
            return None
        angle, season, aspect = where
        k = min(1.0, ROOM_LONG_SIDE / max(size)) / (2 if self.draft else 1)
        size = (max(int(size[0] * k) // 2 * 2, 2), max(int(size[1] * k) // 2 * 2, 2))
        job = {"op": "pile", "pile": self.pile, "angle": angle, "season": season,
               "aspect": aspect, "size": list(size),
               "samples": max(int(self.settings.dennis_3d_samples), 16),
               **({"light": light_of(room)} if light_of(room) else {})}
        key = hashlib.sha256(json.dumps({**job, "v": LOOK_VERSION},
                                        sort_keys=True).encode()).hexdigest()[:20]
        folder = self.cache / "piles" / key
        out, nothing = folder / "pile.png", folder / "not-in-shot"
        if out.exists():
            return out
        if nothing.exists():
            return None
        try:
            reply = self._ask({**job, "out": str(out)})
        except RenderError as e:
            reply = {"ok": False, "error": str(e)}
        if not reply.get("ok"):
            why = str(reply.get("error", ""))
            if "not in shot" in why:
                folder.mkdir(parents=True, exist_ok=True)
                nothing.write_text(why, encoding="utf-8")
            else:
                log.warning("the 10-K pile could not be drawn at %s (%s): the room "
                            "goes up without it", angle, why)
            return None
        self.shots.append({"angle": angle, "aspect": aspect, "pile": self.pile,
                           "seconds": reply.get("seconds"), "device": reply.get("device")})
        return out

    def _room(self, room) -> dict:
        """The room as its picture has it, in the job only where it is not
        the default, so a shot of him at night with no pile keeps its cache:
        the light it was rendered in, and the 10-Ks on the floor."""
        light = light_of(room)
        return {**({"light": light} if light else {}),
                **({"pile": self.pile} if self.pile else {})}

    @staticmethod
    def _jumper() -> dict:
        """His winter jumper (V12), in the job only when he wears it, so a
        shot of him in the navy keeps its cache."""
        from pipeline.plates import current_jumper

        jumper = current_jumper()
        return {"jumper": jumper} if jumper else {}

    def _line_style(self) -> dict:
        """How his lines are drawn, in the job only when it is not Freestyle,
        so a shot Freestyle drew keeps its cache. Lines found in the passes
        carry what finds them, so a change to that draws them again."""
        how = str(getattr(self.settings, "dennis_3d_lines", "passes") or "passes")
        if how == "freestyle":
            return {}
        return {"lines": how, "lines_by": _lines_digest()}

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

    @staticmethod
    def events(layer: Path) -> list[dict]:
        """The moves of his body in this shot the mix gives a sound to
        (`motion.body_events`): `{"kind", "t"}`, seconds from the shot's
        start. Nothing for a shot drawn before they were recorded."""
        f = Path(layer).parent / "events.json"
        if not f.exists():
            return []
        try:
            got = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            return []
        return [{"kind": str(e.get("kind", "arm")), "t": float(e["t"])}
                for e in got if isinstance(e, dict) and "t" in e]


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
