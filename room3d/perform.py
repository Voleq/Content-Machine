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
     "duration": 4.93, "out": "/abs/folder"}

renders `out/d_0000.png` ... and answers with one line that starts with
`@@` (Blender prints its own chatter on stdout too):

    @@{"ok": true, "frames": 59, "out": "/abs/folder", "seconds": 812.4}

An empty line or `{"op": "quit"}` ends it. A frame already on disk is not
drawn again, so a render that stopped picks up where it was.
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
        room.camera(angle, aspect)
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

    def looks(self, angle: str, aspect: str) -> dict:
        """Where the screen and the board are from his spot, and the arm
        angles that point at each (solved once per spot)."""
        spot = tuple(room.view(angle, aspect)["spot"])
        if spot in self._looks:
            return self._looks[spot]
        rig = self.rig
        self.rest()
        root, head = rig.joints["root"], rig.joints["head"]
        R3 = root.matrix_world.to_3x3()
        up = Vector((0.0, 0.0, 1.0))

        def look(target: Vector) -> motion.Look:
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
            # the finger stops well short of what it points at, so a near
            # screen gets a bent arm, not a hand through the glass
            tip = min(d.length - 0.22, 0.70)
            point = self.reach(side, S + dh * max(tip - 0.19, 0.18), pole, dh,
                               -up if abs(dh.z) < 0.8 else back)
            return motion.Look(yaw=yaw, pitch=pitch, side=side, point=point)

        scr = bpy.data.objects["screenface"]
        screen_c = scr.matrix_world @ (sum((Vector(c) for c in scr.bound_box), Vector()) / 8)
        bx0, bx1, bz0, bz1 = room.BOARD
        board_c = Vector(((bx0 + bx1) / 2, room.BACK - 0.03, (bz0 + bz1) / 2))
        self._looks[spot] = {"screen": look(screen_c), "board": look(board_c)}
        return self._looks[spot]

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

    def shot(self, job: dict) -> dict:
        t0 = time.monotonic()
        season = job.get("season", "plain")
        if season != self.season:
            self.build(season)
        aspect = job.get("aspect", "16x9")
        self.frame_up(tuple(job["size"]), int(job.get("samples", 8)))
        self.place(job["angle"], aspect)
        looks = self.looks(job["angle"], aspect)
        words = [type("W", (), w) for w in job["words"]]
        fps = int(job.get("fps", 12))
        st = self.fit(motion.stance_of(str(job.get("stance", ""))))
        perf = motion.perform(words, float(job["duration"]), fps=fps,
                              seed=str(job.get("seed", "")), looks=looks, stance=st)
        self.rig.hold(st.prop, st.prop_side)
        out = Path(job["out"])
        out.mkdir(parents=True, exist_ok=True)
        scn = bpy.context.scene
        from bpy_extras.object_utils import world_to_camera_view

        for i in range(perf.frames):
            f = out / f"d_{i:04d}.png"
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
        meta = {"fps": fps, "frames": perf.frames, "duration": float(job["duration"]),
                "device": self.device}
        (out / "perf.json").write_text(json.dumps(meta))
        return {"ok": True, "frames": perf.frames, "out": str(out),
                "seconds": round(time.monotonic() - t0, 1), "device": self.device}


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
    print(__doc__)
    sys.exit(2)
