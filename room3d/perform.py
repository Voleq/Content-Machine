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
     "size": [2560, 1440], "fps": 30, "samples": 8, "seed": "EXMPL|12",
     "words": [{"word": "So.", "start": 0.12, "end": 0.40}, ...],
     "duration": 4.93, "stance": "host/arms-crossed", "out": "/abs/folder"}

and, for a two-shot, `"plate": [u, v]`, where the evidence sits in the frame
(0-1 from the top left), so he can show it; for the close-up, `"close": true`;
for the push-in on a chapter's wide shot, `"push": {"z": 1.9, "t0": 0.4,
"t1": 3.9}`: the camera goes in `z` times between those seconds of the shot;
with `"lines": "passes"`, his lines are found in the render's own passes
(`lines.py`) instead of traced by Freestyle; for a cover, `"still": true` and
no words: one frame of him mid-sentence, to
the camera, with nothing of the room drawn (no shadow, nothing in front of
him), so the cover can stand him where its type leaves room; with
`"in_room": true` as well, the room stays as a shot has it: the desk in front
of him and his shadow on the room, for a cover that is a frame of the video.
`"light"` is the state the room's picture behind him was rendered in
(`build.states`: `_dusk`, `_rain`, `_t1_dusk` ...), so he is lit by the dusk
sky or the rain's as the room is, and the night when it is left out;
`"pile"` is how many read 10-Ks are on the floor (V12), which take his shadow.
It renders `out/d_0000.png` ... and answers with one line that starts with
`@@` (Blender prints its own chatter on stdout too):

    @@{"ok": true, "frames": 59, "out": "/abs/folder", "seconds": 812.4,
       "window": null}

where `window` is, for a close-up, the piece of the room's picture that is
behind him ([x0, y0, x1, y1], 0-1 from the top left), blown up to the frame;
for a push-in the answer carries `"push"` instead, that piece for every frame.

`{"op": "pile", "pile": 30, "angle": ..., "season": ..., "aspect": ...,
"size": [...], "samples": 16, "light": "_dusk", "out": "/abs/pile.png"}` draws
the read 10-Ks alone the same way, the room as shadow catchers and nobody in
it: a picture the room's size to lay on every picture of the room, the pile
and its shadow, behind whatever stands in front of it.

An empty line or `{"op": "quit"}` ends it. A frame already on disk is not
drawn again, so a render that stopped picks up where it was.

    python room3d/perform.py --bench

times him on this machine: a few frames of the long's wide shot and close-up
and the short's close-up, each at its final size, and what that makes a minute
of him in a long and his shot in a short cost.
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
import lines  # noqa: E402
import motion  # noqa: E402
from dennis import JOINTS, bounds, build_dennis, dress  # noqa: E402

FPS = 30  # as config.dennis_3d_fps: the bench times what a render will draw

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
        self.jumper = ""
        self.rig = None
        self.device = "CPU"
        self.size: tuple[int, int] | None = None
        self.samples = 0
        self.lines = "freestyle"
        self._pass_dir: Path | None = None
        self._pushes: list[tuple[float, float, float]] = []
        self._lens0 = 0.0
        self._looks: dict[tuple, dict] = {}
        self.light = ""
        self.pile = 0
        self._pile: list = []
        self._hidden: list = []

    def build(self, season: str) -> None:
        import addon_utils

        bpy.ops.wm.read_factory_settings(use_empty=True)
        addon_utils.enable("cycles")
        room.THINGS.clear()
        room.LETTERED.clear()
        room._MATS.clear()
        room.build_room(season)
        # him lit by the room at night, by one sky, not by all of them at once
        room.apply_state(season)
        self.rig = build_dennis((0.0, 0.0), beard=BEARD)
        mine = set(self.rig.objects())
        for o in bpy.context.scene.objects:
            if o.type == "MESH" and o not in mine:
                o.is_shadow_catcher = True
        self.season, self.size, self._looks = season, None, {}
        self.jumper, self.light, self.pile, self._pile, self._hidden = "", "", 0, [], []

    def lit(self, light: str) -> None:
        """The room lit as its picture behind him was (`build.states`); the
        night for a state this season does not have."""
        if light not in room.states(self.season):
            light = ""
        if light != self.light:
            room.apply_state(self.season, light)
            self.light = light

    def piled(self, count: int) -> None:
        """The read 10-Ks on the floor, `count` of them, as shadow catchers
        like the rest of the room: he throws his shadow on them."""
        count = max(0, min(int(count), room.PILE_MAX))
        if count == self.pile:
            return
        for o in self._pile:
            bpy.data.objects.remove(o, do_unlink=True)
        room.THINGS.pop("tenk", None)
        self._pile = room.ten_k_pile(count) if count else []
        coll = bpy.data.collections.get("tenk")
        if coll is None:
            coll = bpy.data.collections.new("tenk")
            bpy.context.scene.collection.children.link(coll)
        for o in self._pile:
            for c in list(o.users_collection):
                c.objects.unlink(o)
            coll.objects.link(o)
            o.is_shadow_catcher = True
        self.pile = count

    def frame_up(self, size: tuple[int, int], samples: int, how: str = "freestyle") -> None:
        if self.size == size and self.samples == samples and self.lines == how:
            return
        scn = bpy.context.scene
        room.setup_render(size, samples)
        self.device = _gpu()
        scn.cycles.device = self.device
        scn.render.film_transparent = True
        scn.compositing_node_group = None
        scn.cycles.use_denoising = True
        # cleaned on the card he is drawn on: Blender's own default cleans
        # every frame on the processor while the card waits (his bench,
        # 25 Oct 2026); with no card for it Cycles cleans on the processor
        scn.cycles.denoising_use_gpu = self.device == "GPU"
        scn.render.use_persistent_data = True
        scn.cycles.max_bounces = 3
        scn.cycles.diffuse_bounces = 2
        scn.cycles.glossy_bounces = 1
        vl = bpy.context.view_layer
        # the room's light groups and denoising passes are for the room's own
        # picture (`room.compositor`); a frame of him is only its combined image
        while vl.lightgroups:
            vl.lightgroups.remove(vl.lightgroups[0])
        vl.cycles.denoising_store_passes = False
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
        # `_feather` writes every frame again, so this first write is a hand-over
        scn.render.image_settings.compression = 0
        if how == "passes":
            self._passes()
        self.size, self.samples, self.lines = size, samples, how

    PASSES = ("Depth", "Normal", "Object Index", "Material Index")

    def _passes(self) -> None:
        """His lines from the render's own passes: Freestyle off, and his
        depth, normals and parts written beside each frame for `lines.py`.
        His parts are numbered from one and the room is nought; his
        materials likewise, so a collar or his glasses is an edge."""
        import atexit
        import shutil
        import tempfile

        scn = bpy.context.scene
        vl = bpy.context.view_layer
        scn.render.use_freestyle = False
        vl.use_pass_z = vl.use_pass_normal = True
        vl.use_pass_object_index = vl.use_pass_material_index = True
        mats: dict = {}
        for k, o in enumerate(sorted(self.rig.objects(), key=lambda o: o.name)):
            o.pass_index = k + 1
            for slot in getattr(o, "material_slots", ()):
                if slot.material is not None:
                    slot.material.pass_index = mats.setdefault(slot.material.name, len(mats) + 1)
        if self._pass_dir is None:
            self._pass_dir = Path(tempfile.mkdtemp(prefix="dennis_passes_"))
            atexit.register(shutil.rmtree, self._pass_dir, True)
        old = bpy.data.node_groups.get("passes")
        if old is not None:
            bpy.data.node_groups.remove(old)
        ng = bpy.data.node_groups.new("passes", "CompositorNodeTree")
        scn.compositing_node_group = ng
        rl = ng.nodes.new("CompositorNodeRLayers")
        fo = ng.nodes.new("CompositorNodeOutputFile")
        fo.directory = str(self._pass_dir) + "/"
        fo.file_name = "p"
        fo.format.file_format = "OPEN_EXR_MULTILAYER"
        fo.format.color_depth = "16"
        fo.format.exr_codec = "NONE"
        for name in self.PASSES:
            fo.file_output_items.new("VECTOR" if name == "Normal" else "FLOAT", name)
            ng.links.new(rl.outputs[name], fo.inputs[name])

    def _ink(self, png: Path) -> None:
        """His lines drawn on the frame `png` from the passes of its render."""
        import numpy as np
        from PIL import Image

        from exr import read_exr

        exr = next(self._pass_dir.glob("p*.exr"))
        got = read_exr(exr)
        exr.unlink()                    # the next frame's can never be this one

        def plane(name: str, ch: str = "V"):
            return next(v for k, v in got.items() if k.endswith(f"{name}.{ch}"))

        normal = np.stack([plane("Normal", c) for c in "XYZ"], axis=-1)
        rgba = np.asarray(Image.open(png).convert("RGBA"))
        scale = max(self.size) / max(room.FULL)
        ink_rgb = tuple(int(room.INK.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
        out = lines.draw(rgba, plane("Depth"), normal, plane("Object Index"),
                         plane("Material Index"), outline_px=max(3.6 * scale, 1.4),
                         detail_px=max(2.0 * scale, 1.4), colour=ink_rgb,
                         toward=self._toward())
        Image.fromarray(out, "RGBA").save(png, compress_level=0)     # `_feather` writes it again

    def _toward(self):
        """From each pixel toward the camera: which way a surface must face
        to be seen square on."""
        scn = bpy.context.scene
        turn = scn.camera.matrix_world.to_3x3()
        tr, _br, bl, tl = (turn @ v for v in scn.camera.data.view_frame(scene=scn))
        return lines.toward(tuple(tl), tuple(tr), tuple(bl), self.size)

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

    def aim(self, target) -> motion.Look:
        """Only where `target` is from him standing straight: yaw and pitch,
        no arm (he turns his head to it, he does not reach)."""
        self.rest()
        root, head = self.rig.joints["root"], self.rig.joints["head"]
        loc = root.matrix_world.to_3x3().inverted() @ (
            Vector(target) - head.matrix_world.translation)
        return motion.Look(yaw=math.degrees(math.atan2(loc.x, -loc.y)),
                           pitch=math.degrees(math.atan2(loc.z, math.hypot(loc.x, loc.y))))

    def looks(self, angle: str, aspect: str) -> dict:
        """Where the screen and the board are from his spot, and the arm
        angles that reach for each (solved once per angle). Not once per
        spot: two angles can share his spot (board-side, board-wide) and he
        turns to each one's camera, so the screen is somewhere else from him."""
        spot = (angle, aspect)
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

    def push_in(self, push: dict, fps: int, frames: int) -> list[list[float]]:
        """THE WIDE SHOT GOES IN TO HIM (10 Oct 2026): from the whole room to
        a piece of it `push["z"]` times smaller, with his head near its top,
        between `t0` and `t1` seconds, eased at both ends. The same camera
        with a longer lens and its frame shifted, as the close-up is, so what
        is behind him is exactly a piece of the room's picture. Returns that
        piece for every frame, [x0, y0, x1, y1], 0-1 from the top left; the
        camera is set per frame by `_aim`."""
        from bpy_extras.object_utils import world_to_camera_view

        scn = bpy.context.scene
        cam = scn.camera
        self.rest()
        head = self.rig.joints["head"].matrix_world.translation
        top = world_to_camera_view(scn, cam, head + Vector((0.0, 0.0, 0.36)))
        h1 = 1.0 / min(max(float(push.get("z", 1.0)), 1.0), 4.0)
        # his hair a little under the top of the last piece, centred on him
        c1 = (min(max(top.x, h1 / 2), 1 - h1 / 2),
              min(max(top.y - 0.42 * h1, h1 / 2), 1 - h1 / 2))   # y from the bottom
        t0 = float(push.get("t0", 0.0))
        t1 = max(float(push.get("t1", t0 + 1.0)), t0 + 1e-3)
        self._lens0 = cam.data.lens
        self._pushes = []
        out = []
        for i in range(frames):
            e = min(max((i / fps - t0) / (t1 - t0), 0.0), 1.0)
            e = e * e * e * (e * (e * 6 - 15) + 10)
            # the size goes in evenly to the eye; the centre goes with it
            h = h1 ** e
            g = (1 - h) / (1 - h1) if h1 < 1 else 0.0
            cx, cy = 0.5 + (c1[0] - 0.5) * g, 0.5 + (c1[1] - 0.5) * g
            self._pushes.append((h, cx, cy))
            out.append([round(cx - h / 2, 6), round(1 - (cy + h / 2), 6),
                        round(cx + h / 2, 6), round(1 - (cy - h / 2), 6)])
        return out

    def _aim(self, i: int) -> None:
        """The camera at frame `i` of a push-in."""
        h, cx, cy = self._pushes[min(i, len(self._pushes) - 1)]
        cam = bpy.context.scene.camera
        W, H = bpy.context.scene.render.resolution_x, bpy.context.scene.render.resolution_y
        big = max(W, H)
        cam.data.lens = self._lens0 / h
        cam.data.shift_x = (cx - 0.5) / h * W / big
        cam.data.shift_y = (cy - 0.5) / h * H / big

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
        """Every mesh of the room hidden from the render (a cover), or back:
        only what was hidden here comes back, so the skies the state leaves
        dark and another angle's floor paper stay out (they were in every
        shot, unseen, hiding him and taking his shadow)."""
        if on:
            mine = set(self.rig.objects())
            self._hidden = [o for o in bpy.context.scene.objects
                            if o.type == "MESH" and o not in mine and not o.hide_render]
        for o in self._hidden:
            o.hide_render = on
        if not on:
            self._hidden = []

    def shot(self, job: dict) -> dict:
        t0 = time.monotonic()
        season = job.get("season", "plain")
        if season != self.season:
            self.build(season)
        self.lit(str(job.get("light", "")))
        self.piled(int(job.get("pile", 0)))
        jumper = str(job.get("jumper", ""))
        if jumper != self.jumper:
            dress(self.rig, jumper)
            self.jumper = jumper
        aspect = job.get("aspect", "16x9")
        self.frame_up(tuple(job["size"]), int(job.get("samples", 8)),
                      str(job.get("lines", "freestyle")))
        self.place(job["angle"], aspect)
        looks = self.looks(job["angle"], aspect)
        if job.get("plate"):
            # a picture beside him in the frame (a two-shot): he can show it
            self.rest()
            looks = {**looks, "plate": self.look(self.beside(job["plate"]))}
        window = self.close_up() if job.get("close") else None
        still = bool(job.get("still"))
        fps = int(job.get("fps", FPS))
        st = self.fit(motion.stance_of(str(job.get("stance", ""))))
        if still:
            st, looks = self._still_stance(st), {}
            words = [type("W", (), w) for w in self.STILL_WORDS]
            perf = motion.perform(words, 2.0, fps=fps, seed=str(job.get("seed", "")),
                                  looks=looks, stance=st)
            frames = [min(int(self.STILL_AT_S * fps), perf.frames - 1)]
        else:
            words = [type("W", (), w) for w in job["words"]]
            # the cut on his look: the next shot's camera, from where he stands
            cue = (self.aim(room.view(job["next"], aspect)["cam"][0])
                   if job.get("next") and window is None else None)
            perf = motion.perform(words, float(job["duration"]), fps=fps,
                                  seed=str(job.get("seed", "")), looks=looks, stance=st,
                                  cue=cue)
            frames = range(perf.frames)
        self._pushes = []
        pushes = (self.push_in(job["push"], fps, perf.frames)
                  if job.get("push") and not still and window is None else None)
        self.rig.hold(st.prop, st.prop_side)
        bare = still and not job.get("in_room")
        if bare:
            self._bare(True)
        try:
            return self._render(job, perf, frames, fps, window, t0, pushes)
        finally:
            if bare:
                self._bare(False)

    def pile_layer(self, job: dict) -> dict:
        """The read 10-Ks alone at an angle (V12), lit as the room's picture
        is: the room as shadow catchers, so the picture is the pile and its
        shadow over nothing, behind whatever of the room stands in front of
        it, and nobody in the room. Drawn in the room's lines."""
        t0 = time.monotonic()
        season = job.get("season", "plain")
        if season != self.season:
            self.build(season)
        self.lit(str(job.get("light", "")))
        self.piled(int(job["pile"]))
        if not self._pile:
            return {"ok": False, "error": "no pile to draw"}
        self.frame_up(tuple(job["size"]), int(job.get("samples", 16)), "freestyle")
        cam_o = room.camera(job["angle"], job.get("aspect", "16x9"))
        cam_o.data.shift_x = cam_o.data.shift_y = 0.0
        scn = bpy.context.scene
        vl = bpy.context.view_layer
        pile_coll = bpy.data.collections["tenk"]
        mine = self.rig.objects()
        for o in mine:
            o.hide_render = True
        for o in self._pile:
            o.is_shadow_catcher = False
        for ls in vl.freestyle_settings.linesets:
            ls.collection = pile_coll
        out = Path(job["out"])
        out.parent.mkdir(parents=True, exist_ok=True)
        part = out.with_suffix(".part.png")
        try:
            from bpy_extras.object_utils import world_to_camera_view

            vl.update()
            pts = [o.matrix_world @ Vector(c) for o in self._pile for c in o.bound_box]
            mn = Vector([min(p[i] for p in pts) for i in range(3)])
            mx = Vector([max(p[i] for p in pts) for i in range(3)])

            def seen(grow: float, up: float):
                got = [world_to_camera_view(scn, scn.camera, Vector((x, y, z)))
                       for x in (mn.x - grow, mx.x + grow) for y in (mn.y - grow, mx.y + grow)
                       for z in (0.0, mx.z + up)]
                return (min(p.x for p in got), max(p.x for p in got),
                        min(p.y for p in got), max(p.y for p in got))

            # its shadow runs out across the floor and up the wall
            body, (x0, x1, y0, y1) = seen(0.0, 0.0), seen(0.30, 0.15)
            r = scn.render
            r.use_border, r.use_crop_to_border = True, False
            r.border_min_x, r.border_max_x = max(x0, 0.0), min(x1, 1.0)
            r.border_min_y, r.border_max_y = max(y0, 0.0), min(y1, 1.0)
            if r.border_min_x >= r.border_max_x or r.border_min_y >= r.border_max_y:
                return {"ok": False, "error": f"the pile is not in shot at {job['angle']}"}
            r.filepath = str(part)
            bpy.ops.render.render(write_still=True)
            _feather(part, (r.border_min_x, r.border_max_x, r.border_min_y, r.border_max_y), body)
            part.replace(out)
        finally:
            for o in mine:
                o.hide_render = False
            for o in self._pile:
                o.is_shadow_catcher = True
            for ls in vl.freestyle_settings.linesets:
                ls.collection = self.rig.coll
        return {"ok": True, "out": str(out), "seconds": round(time.monotonic() - t0, 1),
                "device": self.device}

    def _render(self, job: dict, perf, frames, fps: int, window, t0: float,
                pushes=None) -> dict:
        out = Path(job["out"])
        out.mkdir(parents=True, exist_ok=True)
        scn = bpy.context.scene
        from bpy_extras.object_utils import world_to_camera_view

        for n, i in enumerate(frames):
            f = out / f"d_{n:04d}.png"
            if f.exists():
                continue
            self.rig.apply(perf.at(i))
            if self._pushes:
                self._aim(i)
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
            if self.lines == "passes":
                self._ink(f.with_suffix(".part.png"))
            _feather(f.with_suffix(".part.png"),
                     (r.border_min_x, r.border_max_x, r.border_min_y, r.border_max_y),
                     (min(p.x for p in pts), max(p.x for p in pts),
                      min(p.y for p in pts), max(p.y for p in pts)))
            f.with_suffix(".part.png").replace(f)
        # what of his moving the mix gives a sound to (A10)
        events = [] if job.get("still") else motion.body_events(perf)
        meta = {"fps": fps, "frames": len(frames), "duration": perf.frames / fps,
                "device": self.device, "window": window, "push": pushes, "events": events}
        (out / "perf.json").write_text(json.dumps(meta), encoding="utf-8")
        return {"ok": True, "frames": len(frames), "out": str(out), "window": window,
                "push": pushes, "events": events,
                "seconds": round(time.monotonic() - t0, 1), "device": self.device}


def _feather(png: Path, border, body) -> None:
    """His shadow faded out before the edge of the patch drawn round him.

    Only the patch round him is rendered, and the room catches his shadow
    (and its own) inside it, so without this a faint straight edge of shadow
    shows on the room where the patch ends. The fade runs from the box round
    him (`body`) out to the patch's edge (`border`), both (x0, x1, y0, y1),
    0-1 with y from the bottom, so none of him is touched; an edge at the
    frame's own edge is left alone."""
    import numpy as np
    from PIL import Image

    im = Image.open(png).convert("RGBA")
    a = np.asarray(im).copy()
    h, w = a.shape[:2]
    xs = (np.arange(w) + 0.5) / w
    ys = 1.0 - (np.arange(h) + 0.5) / h

    def fade(v, edge: float, inner: float, at_frame: bool):
        if at_frame or abs(inner - edge) < 1e-6:
            return np.ones_like(v)
        t = np.clip((v - edge) / (inner - edge), 0.0, 1.0)
        return t * t * (3 - 2 * t)

    (x0, x1, y0, y1), (bx0, bx1, by0, by1) = border, body
    fx = fade(xs, x0, bx0, x0 <= 0.0) * fade(xs, x1, bx1, x1 >= 1.0)
    fy = fade(ys, y0, by0, y0 <= 0.0) * fade(ys, y1, by1, y1 >= 1.0)
    a[..., 3] = (a[..., 3] * np.outer(fy, fx)).round().astype(np.uint8)
    Image.fromarray(a, "RGBA").save(png, compress_level=1)


def bench() -> int:
    """Seconds a frame of him takes here, with each way of drawing his lines
    (`DENNIS_3D_LINES`), and what a video costs at that."""
    import tempfile

    stage = Stage()
    stage.build("plain")
    words = [{"word": w, "start": 0.2 + k * 0.32, "end": 0.45 + k * 0.32}
             for k, w in enumerate("So here is the number that matters most.".split())]
    styles = (("freestyle", "Freestyle lines"), ("passes", "GPU lines"))
    per: dict[tuple[str, str], float] = {}
    with tempfile.TemporaryDirectory() as tmp:
        # the long's two shots of him at 1920x1080, the short's close-up at its file's size
        for name, aspect, size, close in (("long wide", "16x9", [1920, 1080], False),
                                          ("long close-up", "16x9", [1920, 1080], True),
                                          ("short close-up", "9x16", [1440, 2560], True)):
            said = []
            for how, label in styles:
                job = {"angle": "desk-front", "season": "plain", "aspect": aspect,
                       "size": size, "fps": FPS, "samples": 8, "seed": "bench",
                       "stance": "host/close-up" if close else "host/to-camera",
                       "duration": 0.25, "words": words, "close": close, "lines": how,
                       "out": str(Path(tmp) / f"{name.replace(' ', '-')}-{how}")}
                stage.shot({**job, "duration": 1 / FPS})       # warm: build, first frame
                t = time.monotonic()
                got = stage.shot({**job, "out": job["out"] + "-timed"})
                per[name, how] = (time.monotonic() - t) / max(got["frames"], 1)
                said.append(f"{per[name, how]:.1f} s with {label}")
            print(f"{name}: a frame takes {', '.join(said)}, on the {stage.device}", flush=True)
    for how, label in styles:
        long = (per["long wide", how] * 3 + per["long close-up", how]) / 4  # most of his shots are wide
        # FPS drawings a second; a proof draws him at half the size, about a quarter of this
        print(f"{label} (DENNIS_3D_LINES={how}): each minute of him in a long, about "
              f"{long * FPS:.0f} minutes to draw; the short's three-second shot of him, about "
              f"{per['short close-up', how] * 3 * FPS / 60:.0f} minutes (a proof: about a quarter)",
              flush=True)
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
            reply = stage.pile_layer(job) if job.get("op") == "pile" else stage.shot(job)
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
