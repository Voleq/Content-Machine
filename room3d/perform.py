"""DENNIS PERFORMS A SHOT (item 47): the Blender side of the 3D Dennis.

The pipeline keeps one of these running for a render and sends it a shot at a
time; it answers with a folder of frames. Each frame is him alone, drawn in
the room's lines, over a transparent ground: the room itself is in the frame
only as shadow catchers, so it takes his shadow and hides whatever of him the
desk or the monitor stands in front of, and the installed picture of the room
goes underneath in the pipeline. Nothing here knows about videos.

    python room3d/perform.py --serve

reads one JSON job per line on stdin:

    {"angle": "desk-front", "season": "plain", "aspect": "16x9",
     "size": [2560, 1440], "fps": 12, "samples": 8, "seed": "EXMPL|12",
     "words": [{"word": "So.", "start": 0.12, "end": 0.40}, ...],
     "duration": 4.93, "stance": "host/arms-crossed", "out": "/abs/folder"}

and, for a two-shot, `"plate": [u, v]`, where the evidence sits in the frame
(0-1 from the top left), so he can show it; for the close-up, `"close": true`;
for a cover, `"still": true` and no words: one frame of him mid-sentence, to
the camera, with nothing of the room drawn (no shadow, nothing in front of
him), so the cover can stand him where its type leaves room.
It renders `out/d_0000.png` ... and answers with one line that starts with
`@@` (Blender prints its own chatter on stdout too):

    @@{"ok": true, "frames": 59, "out": "/abs/folder", "seconds": 812.4,
       "window": null}

where `window` is, for a close-up, the piece of the room's picture that is
behind him ([x0, y0, x1, y1], 0-1 from the top left), blown up to the frame.

An empty line or `{"op": "quit"}` ends it. A frame already on disk is not
drawn again, so a render that stopped picks up where it was.

    python room3d/perform.py --bench

times him on this machine: a few frames of a wide shot and a close-up at the
long's size, and what that makes a long and a short cost.
"""
from __future__ import annotations

import json
import math
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import bpy  # noqa: E402
from mathutils import Matrix, Vector  # noqa: E402

import build as room  # noqa: E402
import motion  # noqa: E402
from dennis import JOINTS, bounds, build_dennis  # noqa: E402

BEARD = "short"          # item 64, 3 Oct


def _gpu() -> str:
    """Cycles on the graphics card when there is one, else the processor."""
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
    except KeyError:
        return "CPU"
    for kind in ("OPTIX", "CUDA", "HIP", "METAL", "ONEAPI"):
        try:
            prefs.compute_device_type = kind
            prefs.get_devices()
        except (TypeError, ValueError, RuntimeError):
            continue
        devices = [d for d in prefs.devices if d.type == kind]
        if devices:
            for d in prefs.devices:
                d.use = d.type == kind
            return "GPU"
    return "CPU"


class Stage:
    """The room built once per season, and him, moved to each shot's spot."""

    def __init__(self) -> None:
        self.season: str | None = None
        self.rig = None
        self.device = "CPU"
        self.size: tuple[int, int] | None = None
        self.samples = 0
        self._looks: dict[tuple, dict] = {}

    def build(self, season: str) -> None:
        import addon_utils

        bpy.ops.wm.read_factory_settings(use_empty=True)
        addon_utils.enable("cycles")
        room.THINGS.clear()
        room._MATS.clear()
        room.build_room(season)
        self.rig = build_dennis((0.0, 0.0), beard=BEARD)
        mine = set(self.rig.objects())
        for o in bpy.context.scene.objects:
            if o.type == "MESH" and o not in mine:
                o.is_shadow_catcher = True
        self.season, self.size, self._looks = season, None, {}

    def frame_up(self, size: tuple[int, int], samples: int) -> None:
        if self.size == size and self.samples == samples:
            return
        scn = bpy.context.scene
        room.setup_render(size, samples)
        self.device = _gpu()
        scn.cycles.device = self.device
        scn.render.film_transparent = True
        scn.compositing_node_group = None
        scn.cycles.use_denoising = True
        scn.render.use_persistent_data = True
        scn.cycles.max_bounces = 3
        scn.cycles.diffuse_bounces = 2
        scn.cycles.glossy_bounces = 1
        vl = bpy.context.view_layer
        vl.freestyle_settings.as_render_pass = False
        for ls in vl.freestyle_settings.linesets:
            ls.select_by_collection = True
            ls.collection = self.rig.coll
            # stubble is a shade on the skin, never a drawn shape
            ls.select_by_face_marks = True
            ls.face_mark_negation = "EXCLUSIVE"
            ls.face_mark_condition = "ONE"
        scn.render.image_settings.file_format = "PNG"
        scn.render.image_settings.color_mode = "RGBA"
        self.size, self.samples = size, samples

    def place(self, angle: str, aspect: str) -> None:
        """The camera, and him on the angle's spot, turned to the camera."""
        v = room.view(angle, aspect)
        spot = v.get("spot")
        if spot is None:
            raise ValueError(f"nobody stands in {angle} ({aspect})")
        cam_o = room.camera(angle, aspect)
        cam_o.data.shift_x = cam_o.data.shift_y = 0.0     # no close-up left over
        cam = v["cam"][0]
        root = self.rig.joints["root"]
        root.location = (spot[0], spot[1], 0.0)
        root.rotation_euler.z = math.atan2(cam[0] - spot[0], -(cam[1] - spot[1]))
        self.rig.pose({})
        bpy.context.view_layer.update()

    def rest(self) -> None:
        """Every joint back to standing straight (the root stays where it is)."""
        self.rig.pose({n: (0, 0, 0) for n in self.rig.joints if n != "root"})
        bpy.context.view_layer.update()

    def reach(self, side: str, wrist: Vector, pole: Vector, fingers: Vector,
              palm: Vector) -> dict:
        """The angles that put his `side` wrist at `wrist` (world), the elbow
        out toward `pole`, the fingers along `fingers` and the palm facing
        `palm`: two bones solved exactly, then the hand turned to match."""
        rig = self.rig
        sh = rig.joints[f"shoulder.{side}"]
        a = abs(JOINTS[f"elbow.{side}"][1][2])
        b = abs(JOINTS[f"wrist.{side}"][1][2])
        P3 = sh.parent.matrix_world.to_3x3()
        S = sh.matrix_world.translation.copy()
        d = wrist - S
        dist = min(max(d.length, abs(a - b) + 1e-4), a + b - 1e-4)
        dh = d.normalized()
        cos_a = (a * a + dist * dist - b * b) / (2 * a * dist)
        p = (pole - pole.dot(dh) * dh).normalized()
        u = dh * cos_a + p * math.sqrt(max(1 - cos_a * cos_a, 0.0))
        v = (S + dh * dist - (S + u * a)).normalized()
        y = -(v - v.dot(u) * u).normalized()
        upper = Matrix((y.cross(-u), y, -u)).transposed()
        cos_e = (a * a + b * b - dist * dist) / (2 * a * b)
        bend = 180 - math.degrees(math.acos(max(min(cos_e, 1.0), -1.0)))
        fore = upper @ Matrix.Rotation(math.radians(-bend), 3, "X")
        f = fingers.normalized()
        n = (palm - palm.dot(f) * f).normalized()
        hand = Matrix(((-n).cross(-f), -n, -f)).transposed()

        def calm(turn: Matrix, rest) -> tuple[float, float, float]:
            # of the two Euler triples for one turn, the one nearer rest
            e = [math.degrees(x) for x in turn.to_euler("XYZ")]
            best = None
            for c in (e, [e[0] + 180, 180 - e[1], e[2] + 180]):
                dd = [(x - r + 180) % 360 - 180 for x, r in zip(c, rest)]
                if best is None or max(map(abs, dd)) < max(map(abs, best)):
                    best = dd
            return tuple(round(x, 1) for x in best)

        return {"shoulder": calm(P3.inverted() @ upper, (0, 0, 0)),
                "elbow": (round(-bend, 1), 0.0, 0.0),
                "wrist": calm(fore.inverted() @ hand, rig.rest[f"wrist.{side}"])}

    def look(self, target: Vector) -> motion.Look:
        """Where `target` is from him as he stands now, and the arm angles
        that point at it and that hold a hand open toward it."""
        rig = self.rig
        root, head = rig.joints["root"], rig.joints["head"]
        R3 = root.matrix_world.to_3x3()
        up = Vector((0.0, 0.0, 1.0))
        loc = R3.inverted() @ (target - head.matrix_world.translation)
        yaw = math.degrees(math.atan2(loc.x, -loc.y))
        pitch = math.degrees(math.atan2(loc.z, math.hypot(loc.x, loc.y)))
        side = "R" if loc.x > 0 else "L"
        out = R3 @ Vector((1.0 if side == "R" else -1.0, 0.0, 0.0))
        back = R3 @ Vector((0.0, 1.0, 0.0))
        pole = out * 0.7 - up + back * 0.3
        S = rig.joints[f"shoulder.{side}"].matrix_world.translation
        d = target - S
        dh = d.normalized()
        # the finger stops well short of what it points at, so a near screen
        # gets a bent arm, not a hand through the glass
        tip = min(d.length - 0.22, 0.70)
        point = self.reach(side, S + dh * max(tip - 0.19, 0.18), pole, dh,
                           -up if abs(dh.z) < 0.8 else back)
        # "this here": the hand up and out toward it, open, the palm half to
        # it and half to the camera
        raised = (dh + up * 0.35).normalized()
        present = self.reach(side, S + raised * 0.36, pole, (up * 0.7 + dh * 0.7).normalized(),
                             dh * 0.6 - back * 0.8)
        return motion.Look(yaw=yaw, pitch=pitch, side=side, point=point, present=present)

    def looks(self, angle: str, aspect: str) -> dict:
        """Where the screen and the board are from his spot, and the arm
        angles that reach for each (solved once per spot)."""
        spot = tuple(room.view(angle, aspect)["spot"])
        if spot in self._looks:
            return self._looks[spot]
        self.rest()
        scr = bpy.data.objects["screenface"]
        screen_c = scr.matrix_world @ (sum((Vector(c) for c in scr.bound_box), Vector()) / 8)
        bx0, bx1, bz0, bz1 = room.BOARD
        board_c = Vector(((bx0 + bx1) / 2, room.BACK - 0.03, (bz0 + bz1) / 2))
        self._looks[spot] = {"screen": self.look(screen_c), "board": self.look(board_c)}
        return self._looks[spot]

    def beside(self, uv) -> Vector:
        """The point the camera sees at frame position `uv` (0-1 from the top
        left) on the upright plane through him, square to the camera: where a
        picture laid over the frame there is, as far as he is concerned."""
        scn = bpy.context.scene
        cam = scn.camera
        tr, br, bl, tl = [cam.matrix_world @ v for v in cam.data.view_frame(scene=scn)]
        u, v = float(uv[0]), float(uv[1])
        o = cam.matrix_world.translation
        d = (tl + (tr - tl) * u + (bl - tl) * v - o).normalized()
        root = self.rig.joints["root"].matrix_world
        n = root.to_3x3() @ Vector((0.0, -1.0, 0.0))
        p0 = root.translation + Vector((0.0, 0.0, 1.3))
        return o + d * ((p0 - o).dot(n) / d.dot(n))

    def close_up(self) -> list[float]:
        """Head and shoulders, down the lens: the same camera with a longer
        lens and its frame shifted onto him, so what is behind him is exactly
        a piece of the room's picture, blown up. Returns that piece as
        [x0, y0, x1, y1], 0-1 from the top left."""
        from bpy_extras.object_utils import world_to_camera_view

        scn = bpy.context.scene
        cam = scn.camera
        self.rest()
        head = self.rig.joints["head"].matrix_world.translation
        # from a hand's breadth over his hair to the middle of his chest
        top = world_to_camera_view(scn, cam, head + Vector((0.0, 0.0, 0.36)))
        low = world_to_camera_view(scn, cam, head - Vector((0.0, 0.0, 0.40)))
        h = min(max(top.y - low.y, 0.08), 1.0)
        half = h / 2
        # the window is square in frame units, so it has the frame's shape
        cx = min(max(top.x, half), 1 - half)
        cy = min(max((top.y + low.y) / 2, half), 1 - half)       # from the bottom
        k = 1.0 / h
        W, H = scn.render.resolution_x, scn.render.resolution_y
        big = max(W, H)
        cam.data.lens *= k
        cam.data.shift_x = (cx - 0.5) * k * W / big
        cam.data.shift_y = (cy - 0.5) * k * H / big
        bpy.context.view_layer.update()
        return [round(cx - half, 5), round(1 - (cy + half), 5),
                round(cx + half, 5), round(1 - (cy - half), 5)]

    def fit(self, st: motion.Stance) -> motion.Stance:
        """The stance as it can play on this spot. A hand meant for the desk
        top that would miss it (no desk in front of him, or the monitor in
        the way) tries the other hand, and failing that he talks to the
        camera."""
        if not st.desk:
            return st
        for cand in (st, motion.mirrored(st)):
            side = next((s for s, (arm, _) in cand.home.items() if arm == st.desk), cand.hand)
            if self._on_desk(side, st.desk, st.lean):
                return cand
        return motion.STANCES["to-camera"]

    def _on_desk(self, side: str, arm: str, lean: float) -> bool:
        rig = self.rig
        self.rest()
        rig.apply({**motion.lean_channels(lean), **motion.arm_channels(side, arm)})
        bpy.context.view_layer.update()
        hand = rig.joints[f"wrist.{side}"].matrix_world @ Vector((0.0, 0.0, -0.12))
        dx, dy, dw, dd, dz = room.DESK
        if abs(hand.x - dx) > dw / 2 - 0.05 or abs(hand.y - dy) > dd / 2 - 0.05:
            return False
        if not dz - 0.04 < hand.z < dz + 0.15:
            return False
        scr = bpy.data.objects["screenface"].matrix_world.translation
        return math.hypot(hand.x - scr.x, hand.y - scr.y) > 0.28

    # A COVER'S LINE: he is caught on the stressed word, mouth open, a hand up.
    STILL_WORDS = ({"word": "So", "start": 0.20, "end": 0.42},
                   {"word": "here", "start": 0.48, "end": 0.70},
                   {"word": "is", "start": 0.74, "end": 0.86},
                   {"word": "the", "start": 0.90, "end": 1.00},
                   {"word": "number.", "start": 1.05, "end": 1.60})
    STILL_AT_S = 1.25

    def _still_stance(self, st: motion.Stance) -> motion.Stance:
        """A stance a cover can show: to the camera, nothing to turn to or
        lean on, his mouth in view. The others talk to the camera instead."""
        if (st.look or st.desk or st.reach or st.lean or not st.talks
                or st.first in ("screen", "board", "plate", "desk")):
            return motion.STANCES["to-camera"]
        return st

    def _bare(self, on: bool) -> None:
        """Every mesh of the room hidden from the render (a cover), or back."""
        mine = set(self.rig.objects())
        for o in bpy.context.scene.objects:
            if o.type == "MESH" and o not in mine:
                o.hide_render = on

    def shot(self, job: dict) -> dict:
        t0 = time.monotonic()
        season = job.get("season", "plain")
        if season != self.season:
            self.build(season)
        aspect = job.get("aspect", "16x9")
        self.frame_up(tuple(job["size"]), int(job.get("samples", 8)))
        self.place(job["angle"], aspect)
        looks = self.looks(job["angle"], aspect)
        if job.get("plate"):
            # a picture beside him in the frame (a two-shot): he can show it
            self.rest()
            looks = {**looks, "plate": self.look(self.beside(job["plate"]))}
        window = self.close_up() if job.get("close") else None
        still = bool(job.get("still"))
        fps = int(job.get("fps", 12))
        st = self.fit(motion.stance_of(str(job.get("stance", ""))))
        if still:
            st, looks = self._still_stance(st), {}
            words = [type("W", (), w) for w in self.STILL_WORDS]
            perf = motion.perform(words, 2.0, fps=fps, seed=str(job.get("seed", "")),
                                  looks=looks, stance=st)
            frames = [min(int(self.STILL_AT_S * fps), perf.frames - 1)]
        else:
            words = [type("W", (), w) for w in job["words"]]
            perf = motion.perform(words, float(job["duration"]), fps=fps,
                                  seed=str(job.get("seed", "")), looks=looks, stance=st)
            frames = range(perf.frames)
        self.rig.hold(st.prop, st.prop_side)
        self._bare(still)
        try:
            return self._render(job, perf, frames, fps, window, t0)
        finally:
            self._bare(False)

    def _render(self, job: dict, perf, frames, fps: int, window, t0: float) -> dict:
        out = Path(job["out"])
        out.mkdir(parents=True, exist_ok=True)
        scn = bpy.context.scene
        from bpy_extras.object_utils import world_to_camera_view

        for n, i in enumerate(frames):
            f = out / f"d_{n:04d}.png"
            if f.exists():
                continue
            self.rig.apply(perf.at(i))
            bpy.context.view_layer.update()
            # Only round him and the shadow he throws is drawn.
            mn, mx = bounds(self.rig)
            pts = [world_to_camera_view(scn, scn.camera, Vector((x, y, z)))
                   for x in (mn.x, mx.x) for y in (mn.y, mx.y) for z in (mn.z, mx.z)]
            r = scn.render
            r.use_border, r.use_crop_to_border = True, False
            r.border_min_x = max(min(p.x for p in pts) - 0.10, 0.0)
            r.border_max_x = min(max(p.x for p in pts) + 0.12, 1.0)
            r.border_min_y = max(min(p.y for p in pts) - 0.04, 0.0)
            r.border_max_y = min(max(p.y for p in pts) + 0.05, 1.0)
            r.filepath = str(f.with_suffix(".part.png"))
            bpy.ops.render.render(write_still=True)
            f.with_suffix(".part.png").replace(f)
        meta = {"fps": fps, "frames": len(frames), "duration": perf.frames / fps,
                "device": self.device, "window": window}
        (out / "perf.json").write_text(json.dumps(meta), encoding="utf-8")
        return {"ok": True, "frames": len(frames), "out": str(out), "window": window,
                "seconds": round(time.monotonic() - t0, 1), "device": self.device}


def bench() -> int:
    """Seconds a frame of him takes here, and what a video costs at that."""
    import tempfile

    stage = Stage()
    stage.build("plain")
    words = [{"word": w, "start": 0.2 + k * 0.32, "end": 0.45 + k * 0.32}
             for k, w in enumerate("So here is the number that matters most.".split())]
    per = {}
    with tempfile.TemporaryDirectory() as tmp:
        for name, close in (("wide", False), ("close-up", True)):
            job = {"angle": "desk-front", "season": "plain", "aspect": "16x9",
                   "size": [1920, 1080], "fps": 12, "samples": 8, "seed": "bench",
                   "stance": "host/close-up" if close else "host/to-camera",
                   "duration": 0.34, "words": words, "close": close,
                   "out": str(Path(tmp) / name)}
            stage.shot({**job, "duration": 1 / 12})        # warm: build, first frame
            t = time.monotonic()
            got = stage.shot({**job, "out": job["out"] + "-timed"})
            per[name] = (time.monotonic() - t) / max(got["frames"], 1)
            print(f"{name}: {per[name]:.1f} s a frame on the {stage.device}", flush=True)
    frame = (per["wide"] * 3 + per["close-up"]) / 4    # most of his shots are wide
    # twelve drawings a second; a short draws him at 1440x2560, 1.78 times the pixels
    print(f"each minute of him in a long: about {frame * 60 * 12 / 60:.0f} minutes "
          f"to draw; a short's three-second shot of him: about "
          f"{per['close-up'] * 1.78 * 3 * 12 / 60:.0f} minutes", flush=True)
    return 0


def serve() -> int:
    stage = Stage()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            break
        try:
            job = json.loads(line)
            if job.get("op") == "quit":
                break
            reply = stage.shot(job)
        except Exception as e:  # one bad shot answers, it does not end the render
            reply = {"ok": False, "error": f"{type(e).__name__}: {e}",
                     "trace": traceback.format_exc(limit=6)}
        sys.stdout.write("@@" + json.dumps(reply) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    if "--serve" in sys.argv:
        sys.exit(serve())
    if "--bench" in sys.argv:
        sys.exit(bench())
    print(__doc__)
    sys.exit(2)
