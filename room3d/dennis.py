"""Dennis in 3D (item 47): the same man as design's drawing, built in the room.

A cartoon, never a likeness of anybody: tall and thin, a navy crew-neck
sweater, glasses, brown hair parted on the side, brown shoes, drawn in the
room's own ink. He is a puppet of rigid parts on a chain of joints, so a pose
is a set of joint angles and an animation is those angles over time, and his
mouth is one shape with a key for each of the kit's six mouths, so the words
drive it the way they drive the drawn one (`pipeline.host.word_mouths`).

    from dennis import build_dennis
    rig = build_dennis(spot=(2.05, 1.46), face=(0.6, -3.3))
    rig.pose(...)                  # joint angles, degrees
    rig.mouth("mouthO")            # one of the six

`motion.py` turns a line's word timings into his movement.
"""
from __future__ import annotations

import math
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Vector

# His palette, from design's drawing of him.
SKIN = "#E2A97C"
SWEATER = "#3F5C8C"
COLLAR = "#2C3E5E"
TROUSERS = "#4E4A62"
SHOES = "#5A3A28"
HAIR = "#6A4630"
FRAMES = "#171B23"
EYES = "#141820"
MOUTH = "#5A2426"

MOUTHS = ("mouthClosed", "mouthMid", "mouthWide", "mouthO", "mouthEE", "mouthFV")

# Where each joint sits on its parent, metres, standing straight, facing -y.
JOINTS = {
    "hips": ("root", (0, 0, 0.93)),
    "spine": ("hips", (0, 0, 0.11)),
    "chest": ("spine", (0, 0, 0.21)),
    "neck": ("chest", (0, 0, 0.20)),
    "head": ("neck", (0, 0, 0.12)),
    "shoulder.L": ("chest", (-0.168, 0.0, 0.15)),
    "elbow.L": ("shoulder.L", (0, 0, -0.29)),
    "wrist.L": ("elbow.L", (0, 0, -0.26)),
    "shoulder.R": ("chest", (0.168, 0.0, 0.15)),
    "elbow.R": ("shoulder.R", (0, 0, -0.29)),
    "wrist.R": ("elbow.R", (0, 0, -0.26)),
    "thigh.L": ("hips", (-0.095, 0, -0.02)),
    "knee.L": ("thigh.L", (0, 0, -0.43)),
    "ankle.L": ("knee.L", (0, 0, -0.41)),
    "thigh.R": ("hips", (0.095, 0, -0.02)),
    "knee.R": ("thigh.R", (0, 0, -0.43)),
    "ankle.R": ("knee.R", (0, 0, -0.41)),
}
FINGERS = ("index", "middle", "ring", "little", "thumb")
# His hands are drawn a size up from life, as cartoon hands are.
HAND_SCALE = 1.18
# What he may hold (the kit's holding-a-mug, -phone, -page, -filing poses):
# where each sits in the right hand, in the wrist's frame (metres; the palm
# faces -y and the fingers run down -z), and its turn in degrees. The left
# hand mirrors it. Each goes with its arm pose in `motion` (hold, phone,
# page, filing): the mug stands upright against the palm, the phone and the
# page lie on it (the mug hangs off his fingers by its handle, its body
# clear of the hand where the camera can see it), and the filing stands on its edge in the palm, its width
# running across to the other hand, its cover to the camera.
PROPS = {
    "mug": ((0.0, -0.10, -0.09), (90, 0, 90)),
    "phone": ((0.0, -0.036, -0.13), (0, 0, 0)),
    "page": ((-0.07, -0.032, -0.15), (0, 0, 0)),
    "filing": ((0.0, -0.11, -0.10), (0, 0, 90)),
}
# the mug is the red one off his desk; the filing is the desk's annual report
# and the phone's back is light, or it is lost against the navy sweater
MUG, PHONE, PAPER, FOLDER = "#C24A38", "#B4BCC8", "#F2EEE6", "#E6E4DC"
TEXTURES = Path(__file__).resolve().parent / "textures"
# Beards: how far each sits off the skin, metres.
BEARDS = {"none": 0.0, "stubble": 0.0022, "short": 0.0065}
STUBBLE = "#9A6C50"      # the skin with a few days' growth through it


def _lin(h: str) -> tuple[float, float, float, float]:
    h = h.lstrip("#")
    c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return tuple(((v + 0.055) / 1.055) ** 2.4 if v > 0.04045 else v / 12.92 for v in c) + (1.0,)


_MATS: dict[str, bpy.types.Material] = {}


def _mat(name: str, colour: str, rough: float = 0.85, sheen: float = 0.0) -> bpy.types.Material:
    key = f"dennis_{name}"
    try:
        if key in _MATS and _MATS[key].name in bpy.data.materials:
            return _MATS[key]
    except ReferenceError:      # left over from before a factory reset
        pass
    m = bpy.data.materials.new(key)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = _lin(colour)
    b.inputs["Roughness"].default_value = rough
    if sheen:
        b.inputs["Sheen Weight"].default_value = sheen
    _MATS[key] = m
    return m


def _mesh_object(name: str, bm: bmesh.types.BMesh, m, coll, smooth: bool = True,
                 subdiv: int = 1) -> bpy.types.Object:
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    if smooth:
        for p in me.polygons:
            p.use_smooth = True
    me.materials.append(m)
    o = bpy.data.objects.new(name, me)
    coll.objects.link(o)
    if subdiv:
        mod = o.modifiers.new("smooth", "SUBSURF")
        mod.levels = mod.render_levels = subdiv
    return o


def loft(name: str, rings, m, coll, *, n: int = 20, subdiv: int = 1,
         cap_top: bool = True, cap_bottom: bool = True) -> bpy.types.Object:
    """A smooth body through elliptical rings `(z, rx, ry[, cx, cy])`, bottom
    to top, each ring's front (-y) flattened by `flat` when given as a sixth
    value. A ring of radius 0 closes the body to a point."""
    bm = bmesh.new()
    loops = []
    for ring in rings:
        z, rx, ry = ring[:3]
        cx, cy = (ring[3], ring[4]) if len(ring) > 4 else (0.0, 0.0)
        flat = ring[5] if len(ring) > 5 else 1.0
        if rx <= 1e-6 and ry <= 1e-6:
            loops.append([bm.verts.new((cx, cy, z))])
            continue
        vs = []
        for i in range(n):
            a = 2 * math.pi * i / n
            x, y = math.sin(a) * rx, -math.cos(a) * ry
            if y < 0:
                y *= flat
            vs.append(bm.verts.new((cx + x, cy + y, z)))
        loops.append(vs)
    for lo, hi in zip(loops, loops[1:]):
        if len(lo) == 1 and len(hi) == 1:
            continue
        if len(lo) == 1:
            for i in range(n):
                bm.faces.new((lo[0], hi[i], hi[(i + 1) % n]))
        elif len(hi) == 1:
            for i in range(n):
                bm.faces.new((lo[i], lo[(i + 1) % n], hi[0]))
        else:
            for i in range(n):
                bm.faces.new((lo[i], lo[(i + 1) % n], hi[(i + 1) % n], hi[i]))
    if cap_bottom and len(loops[0]) > 1:
        bm.faces.new(list(reversed(loops[0])))
    if cap_top and len(loops[-1]) > 1:
        bm.faces.new(loops[-1])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return _mesh_object(name, bm, m, coll, subdiv=subdiv)


def blob(name: str, size, m, coll, *, segs: int = 16, rings: int = 10, subdiv: int = 0):
    """An ellipsoid with half-axes `size`."""
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=segs, v_segments=rings, radius=1.0)
    bmesh.ops.scale(bm, vec=Vector(size), verts=bm.verts)
    return _mesh_object(name, bm, m, coll, subdiv=subdiv)


def ring_frame(name: str, w: float, h: float, r: float, m, coll):
    """A rounded-rectangle wire, `w` by `h`, of thickness `r`: a lens frame."""
    bm = bmesh.new()
    pts = []
    k = 6
    cr = min(w, h) * 0.32
    for cx, cz, a0 in ((w / 2 - cr, h / 2 - cr, 0), (-w / 2 + cr, h / 2 - cr, 90),
                       (-w / 2 + cr, -h / 2 + cr, 180), (w / 2 - cr, -h / 2 + cr, 270)):
        for i in range(k + 1):
            a = math.radians(a0 + 90 * i / k)
            pts.append(Vector((cx + cr * math.cos(a), 0, cz + cr * math.sin(a))))
    n = len(pts)
    seg = 6
    rings = []
    for i, p in enumerate(pts):
        t = (pts[(i + 1) % n] - pts[i - 1]).normalized()
        nrm = Vector((0, 1, 0)).cross(t).normalized()
        ring = []
        for j in range(seg):
            a = 2 * math.pi * j / seg
            ring.append(bm.verts.new(p + nrm * (r * math.cos(a)) + Vector((0, r * math.sin(a), 0))))
        rings.append(ring)
    for i in range(n):
        a, b = rings[i], rings[(i + 1) % n]
        for j in range(seg):
            bm.faces.new((a[j], a[(j + 1) % seg], b[(j + 1) % seg], b[j]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return _mesh_object(name, bm, m, coll, subdiv=0)


class Skin:
    """A tube that bends between two joints: built straight down the first
    joint's -z as rings `(z, radius)`, each vertex then carried by the two
    joints in proportion to where it sits between `blend` (above it, all the
    first; below it, all the second). Blender is not asked to skin it: `bend`
    moves its vertices from the joints, frame by frame."""

    def __init__(self, rig: "Rig", name: str, rings, m, joints: tuple[str, str],
                 blend: tuple[float, float], n: int = 16):
        bpy.context.view_layer.update()
        top = rig.joints[joints[0]].matrix_world.copy()
        bm = bmesh.new()
        loops = []
        zs = []
        for z, r in rings:
            if r <= 1e-6:
                loops.append([bm.verts.new(top @ Vector((0, 0, z)))])
                zs.append([z])
                continue
            loops.append([bm.verts.new(top @ Vector((math.sin(2 * math.pi * i / n) * r,
                                                     -math.cos(2 * math.pi * i / n) * r, z)))
                          for i in range(n)])
            zs.append([z] * n)
        for lo, hi in zip(loops, loops[1:]):
            if len(lo) == 1:
                for i in range(n):
                    bm.faces.new((lo[0], hi[(i + 1) % n], hi[i]))
            elif len(hi) == 1:
                for i in range(n):
                    bm.faces.new((lo[i], lo[(i + 1) % n], hi[0]))
            else:
                for i in range(n):
                    bm.faces.new((lo[i], lo[(i + 1) % n], hi[(i + 1) % n], hi[i]))
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        self.obj = _mesh_object(name, bm, m, rig.coll, subdiv=1)
        rig.parts.append(self.obj)
        a, b = blend
        self.weights = [min(max((z - a) / (b - a), 0.0), 1.0) for ring in zs for z in ring]
        self.rest = [v.co.copy() for v in self.obj.data.vertices]
        self.joints = [rig.joints[j] for j in joints]
        self.inv = [j.matrix_world.inverted() for j in self.joints]

    def bend(self) -> None:
        m1, m2 = (j.matrix_world @ inv for j, inv in zip(self.joints, self.inv))
        flat = []
        for co, w in zip(self.rest, self.weights):
            p = (m1 @ co) * (1 - w) + (m2 @ co) * w
            flat.extend(p)
        self.obj.data.vertices.foreach_set("co", flat)
        self.obj.data.update()


class Rig:
    """Dennis: his joints, his parts, and the controls a motion drives."""

    def __init__(self, coll: bpy.types.Collection):
        self.coll = coll
        self.joints: dict[str, bpy.types.Object] = {}
        self.parts: list[bpy.types.Object] = []
        self.mouth_obj: bpy.types.Object | None = None
        self.lids: list[bpy.types.Object] = []
        self.brows: list[bpy.types.Object] = []
        self.rest: dict[str, tuple] = {}
        self.skins: list[Skin] = []
        self.props: dict[str, bpy.types.Object] = {}
        self.hands: dict[str, list[bpy.types.Object]] = {"L": [], "R": []}

    # --- building
    def joint(self, name: str, parent: str | None, offset) -> bpy.types.Object:
        e = bpy.data.objects.new(f"j_{name}", None)
        e.empty_display_size = 0.03
        self.coll.objects.link(e)
        if parent:
            e.parent = self.joints[parent]
        e.location = offset
        e.rotation_mode = "XYZ"
        self.joints[name] = e
        return e

    def attach(self, o: bpy.types.Object, joint: str, offset=(0, 0, 0), rot=(0, 0, 0)):
        o.parent = self.joints[joint]
        o.location = offset
        o.rotation_euler = [math.radians(a) for a in rot]
        self.parts.append(o)
        return o

    # --- controls
    def pose(self, angles: dict[str, tuple], frame: int | None = None) -> None:
        """Joint angles in degrees (x, y, z) over the rest pose; with `frame`,
        keyed there."""
        for name, a in angles.items():
            j = self.joints[name]
            base = self.rest.get(name, (0, 0, 0))
            j.rotation_euler = [math.radians(b + v) for b, v in zip(base, a)]
            if frame is not None:
                j.keyframe_insert("rotation_euler", frame=frame)
        self.bend()

    def bend(self) -> None:
        """Carry the sleeves with the arms (after any change to the joints)."""
        if self.skins:
            bpy.context.view_layer.update()
            for sk in self.skins:
                sk.bend()

    def mouth(self, which: str, frame: int | None = None, amount: float = 1.0) -> None:
        keys = self.mouth_obj.data.shape_keys.key_blocks
        for m in MOUTHS[1:]:
            keys[m].value = amount if m == which else 0.0
            if frame is not None:
                keys[m].keyframe_insert("value", frame=frame)

    def blink(self, closed: float, frame: int | None = None) -> None:
        for lid in self.lids:
            lid.scale.z = max(1.0 - closed, 0.08)
            if frame is not None:
                lid.keyframe_insert("scale", index=2, frame=frame)

    def brow(self, up: float, frame: int | None = None) -> None:
        for b in self.brows:
            b.location.z = b["rest_z"] + up * 0.008
            if frame is not None:
                b.keyframe_insert("location", index=2, frame=frame)

    def hand(self, side: str, shape: str, frame: int | None = None) -> None:
        """relaxed | open | point | fist | cup (holding a mug)."""
        curls = {"relaxed": (25, 30, 35, 40, 15), "open": (4, 2, 4, 8, 5),
                 "point": (0, 95, 100, 100, 55), "fist": (100, 100, 100, 100, 60),
                 "cup": (70, 75, 80, 80, 40)}[shape]
        self.curl(side, curls)
        if frame is not None:
            for f in FINGERS:
                self.joints[f"{f}.{side}"].keyframe_insert("rotation_euler", frame=frame)

    def curl(self, side: str, curls) -> None:
        """Finger curls in degrees, index to thumb."""
        for f, c in zip(FINGERS, curls):
            j = self.joints[f"{f}.{side}"]
            # Fingers curl towards the palm, which faces -y on the hand.
            j.rotation_euler.x = -math.radians(c if f != "thumb" else c * 0.6)
            if f == "thumb":
                s = -1 if side == "L" else 1
                j.rotation_euler.y = math.radians(s * (30 - c * 0.4))

    def apply(self, values: dict[str, float]) -> None:
        """One frame of a `motion.Performance`: every joint it names set over
        the rest pose, the shoulders lifted, the fingers curled, the face."""
        angles: dict[str, list[float]] = {}
        curls: dict[str, dict[str, float]] = {"L": {}, "R": {}}
        for k, v in values.items():
            head, _, last = k.rpartition(".")
            if k.startswith("curl."):
                _, side, finger = k.split(".")
                curls[side][finger] = v
            elif k.startswith("mouth."):
                key = self.mouth_obj.data.shape_keys.key_blocks.get(last)
                if key is not None:
                    key.value = v
            elif k.startswith("lift."):
                j = self.joints[f"shoulder.{last}"]
                j.location.z = JOINTS[f"shoulder.{last}"][1][2] + v
            elif k.startswith("pocket."):
                # a hand down a pocket is not drawn: the sleeve goes into
                # the hip, as a drawn pocket would show it
                for o in self.hands[last]:
                    o.hide_render = o.hide_viewport = v > 0.9
            elif k == "blink":
                for lid in self.lids:
                    lid.scale.z = max(1.0 - v, 0.08)
            elif k == "brow":
                for b in self.brows:
                    b.location.z = b["rest_z"] + v * 0.008
            elif head in self.joints and last in "xyz":
                angles.setdefault(head, [0.0, 0.0, 0.0])["xyz".index(last)] = v
        for name, a in angles.items():
            base = self.rest.get(name, (0, 0, 0))
            self.joints[name].rotation_euler = [math.radians(b + d) for b, d in zip(base, a)]
        for side, c in curls.items():
            if c:
                self.curl(side, [c.get(f, 0.0) for f in FINGERS])
        self.bend()

    def objects(self) -> list[bpy.types.Object]:
        return list(self.coll.all_objects)

    def hold(self, prop: str = "", side: str = "R") -> None:
        """Put `prop` (a key of `PROPS`) in his `side` hand and every other
        prop away; "" leaves his hands empty."""
        for name, o in self.props.items():
            on = name == prop
            o.hide_render = o.hide_viewport = not on
            for ch in o.children:
                ch.hide_render = ch.hide_viewport = not on
            if on:
                loc, rot = PROPS[name]
                sgn = 1 if side == "R" else -1
                o.parent = self.joints[f"wrist.{side}"]
                o.location = (loc[0] * sgn, loc[1], loc[2])
                o.rotation_euler = [math.radians(rot[0]), math.radians(rot[1] * sgn),
                                    math.radians(rot[2] * sgn)]
        bpy.context.view_layer.update()


def build_dennis(spot=(0.0, 0.0), face=None, *, name: str = "dennis",
                 beard: str = "short") -> Rig:
    """Dennis standing at `spot` (floor x, y), turned to look at `face` (a
    floor point, usually under the camera), clean-shaven or with one of
    `BEARDS`."""
    coll = bpy.data.collections.get(name) or bpy.data.collections.new(name)
    if coll.name not in bpy.context.scene.collection.children:
        bpy.context.scene.collection.children.link(coll)
    rig = Rig(coll)
    root = rig.joint("root", None, (spot[0], spot[1], 0.0))
    if face is not None:
        d = Vector((face[0] - spot[0], face[1] - spot[1], 0))
        root.rotation_euler.z = math.atan2(d.x, -d.y)
    for jn, (parent, off) in JOINTS.items():
        rig.joint(jn, parent, off)

    skin = _mat("skin", SKIN, 0.7)
    knit = _mat("sweater", SWEATER, 0.95, sheen=0.3)
    collar = _mat("collar", COLLAR, 0.95)
    cloth = _mat("trousers", TROUSERS, 0.9)
    shoe = _mat("shoes", SHOES, 0.6)
    hair = _mat("hair", HAIR, 0.8)
    frame = _mat("frames", FRAMES, 0.35)
    eye = _mat("eyes", EYES, 0.3)
    lips = _mat("mouth", MOUTH, 0.6)

    # Torso: design's box of a sweater, straight down from square shoulders,
    # a little wider at the top than at the hem.
    torso = loft("torso", [
        (-0.07, 0.150, 0.098), (0.05, 0.150, 0.098), (0.20, 0.158, 0.100),
        (0.34, 0.176, 0.104), (0.43, 0.190, 0.106), (0.485, 0.192, 0.104),
        (0.51, 0.180, 0.098), (0.528, 0.140, 0.085), (0.538, 0.075, 0.060),
    ], knit, coll, n=24)
    rig.attach(torso, "hips")
    rig.attach(loft("collar", [(0.0, 0.074, 0.062), (0.022, 0.071, 0.059)], collar, coll,
                    n=24, cap_top=False, cap_bottom=False), "chest", (0, 0.004, 0.212))
    # Long and thin, as drawn, and running up inside the head so its end
    # never shows under the chin.
    rig.attach(loft("neck", [(0.0, 0.040, 0.040), (0.15, 0.037, 0.038), (0.24, 0.034, 0.034)],
                    skin, coll, n=16), "neck", (0, 0.014, -0.03))
    # Head: an egg, the jaw narrower than the temples, its front flatter.
    head = loft("head", [
        (-0.005, 0.0, 0.0, 0, -0.012), (0.004, 0.032, 0.028, 0, -0.012, 0.9),
        (0.03, 0.062, 0.068, 0, -0.004, 0.9), (0.07, 0.080, 0.088, 0, 0, 0.92),
        (0.11, 0.087, 0.096, 0, 0.002, 0.95), (0.15, 0.088, 0.098, 0, 0.004),
        (0.19, 0.080, 0.092, 0, 0.006), (0.215, 0.060, 0.072, 0, 0.008),
        (0.232, 0.0, 0.0, 0, 0.01),
    ], skin, coll, n=24)
    rig.attach(head, "head", (0, 0, -0.01))
    for side in (-1, 1):
        ear = blob(f"ear{side}", (0.012, 0.02, 0.03), skin, coll)
        rig.attach(ear, "head", (side * 0.088, 0.012, 0.115))
    nose = blob("nose", (0.009, 0.013, 0.021), skin, coll, subdiv=1)
    rig.attach(nose, "head", (0, -0.093, 0.100), rot=(22, 0, 0))
    if BEARDS.get(beard):
        bpy.context.view_layer.update()
        mat = hair if beard == "short" else _mat("stubble", STUBBLE, 0.9)
        rig.attach(_beard(f"beard.{beard}", head, BEARDS[beard], mat, coll,
                          lined=beard == "short"), "head", (0, 0, -0.01))

    # Hair: a cap over the crown and the back of the head, swept to the side
    # at the front.
    cap = loft("hair", [
        (0.105, 0.0, 0.0, 0, 0.03), (0.11, 0.074, 0.074, 0, 0.03, 0.4),
        (0.15, 0.094, 0.104, 0, 0.006, 0.7), (0.19, 0.088, 0.100, 0, 0.006),
        (0.222, 0.068, 0.080, 0, 0.008), (0.245, 0.0, 0.0, 0, 0.01),
    ], hair, coll, n=24)
    rig.attach(cap, "head", (0, 0.0, 0.0))
    fringe = blob("fringe", (0.062, 0.03, 0.026), hair, coll, subdiv=1)
    rig.attach(fringe, "head", (0.018, -0.078, 0.192), rot=(-18, -16, 8))
    back = blob("hairback", (0.082, 0.05, 0.06), hair, coll, subdiv=1)
    rig.attach(back, "head", (0, 0.05, 0.12))

    # Eyes behind the glasses, the lids that blink them, the brows above.
    for side, name in ((-1, "L"), (1, "R")):
        # His eyes are design's level dashes: a man who has read the footnotes.
        e = blob(f"eye.{name}", (0.0105, 0.003, 0.0052), eye, coll)
        rig.attach(e, "head", (side * 0.033, -0.0935, 0.135))
        rig.lids.append(e)
        b = blob(f"brow.{name}", (0.021, 0.005, 0.0042), hair, coll)
        rig.attach(b, "head", (side * 0.034, -0.0955, 0.168), rot=(0, side * -6, 0))
        b["rest_z"] = 0.168
        rig.brows.append(b)
        lens = ring_frame(f"lens.{name}", 0.054, 0.034, 0.0026, frame, coll)
        rig.attach(lens, "head", (side * 0.034, -0.100, 0.136))
        temple = loft(f"temple.{name}", [(0.0, 0.0022, 0.0022), (0.094, 0.0022, 0.0022)],
                      frame, coll, n=6, subdiv=0)
        rig.attach(temple, "head", (side * 0.061, -0.098, 0.140), rot=(-90, 0, 0))
    bridge = loft("bridge", [(0.0, 0.0022, 0.0022), (0.016, 0.0022, 0.0022)], frame, coll,
                  n=6, subdiv=0)
    rig.attach(bridge, "head", (-0.008, -0.101, 0.142), rot=(0, 90, 0))

    # The mouth: one dark shape, a key for each of the kit's six mouths.
    rig.mouth_obj = rig.attach(_mouth("mouth", lips, coll), "head", (0, -0.084, 0.058))

    # Arms: sleeves to the cuff, a wrist of skin, a mitten of a hand with
    # fingers that curl.
    for side in ("L", "R"):
        s = -1 if side == "L" else 1
        # The sleeve is one tube from the shoulder to the cuff that bends at
        # the elbow (`Skin`), so a bent arm has no seam for the ink to find.
        rig.skins.append(Skin(rig, f"sleeve.{side}", [
            (0.041, 0.0), (0.036, 0.021), (0.022, 0.035), (0.0, 0.041), (-0.08, 0.040),
            (-0.18, 0.038), (-0.25, 0.037), (-0.29, 0.036), (-0.33, 0.035), (-0.42, 0.033),
            (-0.50, 0.032), (-0.545, 0.031), (-0.548, 0.0)],
            knit, (f"shoulder.{side}", f"elbow.{side}"), (-0.25, -0.33)))
        rig.attach(loft(f"cuff.{side}", [(-0.262, 0.030, 0.029), (-0.232, 0.034, 0.033)],
                        collar, coll, n=16), f"elbow.{side}")
        rig.attach(loft(f"wristskin.{side}", [(-0.04, 0.026, 0.022), (0.01, 0.028, 0.024)],
                        skin, coll, n=12), f"wrist.{side}")
        # A cartoon hand, a size up from life so it reads at the back of
        # the room: a thick rounded palm, four fat fingers fanned a little
        # apart so each one reads, and a thumb that stands off the palm.
        k = HAND_SCALE
        palm = loft(f"palm.{side}", [(-0.098 * k, 0.034 * k, 0.015 * k),
                                     (-0.088 * k, 0.047 * k, 0.022 * k),
                                     (-0.055 * k, 0.051 * k, 0.025 * k),
                                     (-0.018 * k, 0.045 * k, 0.024 * k),
                                     (0.0, 0.031 * k, 0.020 * k)],
                    skin, coll, n=16)
        rig.attach(palm, f"wrist.{side}", (0, 0, -0.022))
        rig.hands[side].append(palm)
        for i, f in enumerate(FINGERS):
            # The palm faces -y here and the thumb is on its outer edge;
            # the wrist turns the palm to his thigh at rest.
            if f == "thumb":
                j = rig.joint(f"thumb.{side}", f"wrist.{side}",
                              (s * 0.040 * k, -0.012 * k, -0.046 * k))
                length, r = 0.056 * k, 0.0128 * k
            else:
                j = rig.joint(f"{f}.{side}", f"wrist.{side}",
                              (s * (0.031 - i * 0.0205) * k, 0.0, -0.104 * k))
                # fanned: the index leans out to the thumb side, the little
                # finger the other way
                j.rotation_euler.y = math.radians(s * (-7 + i * 5.5))
                length = (0.060, 0.066, 0.062, 0.050)[i] * k
                r = (0.0118, 0.0122, 0.0116, 0.0102)[i] * k
            finger = loft(f"{f}.{side}.m", [(-length, 0.0, 0.0),
                                            (-length + r * 0.55, r * 0.86, r * 0.82),
                                            (-length * 0.5, r, r * 0.92), (0.0, r * 1.04, r)],
                          skin, coll, n=12)
            rig.hands[side].append(rig.attach(finger, f"{f}.{side}"))
        rig.hand(side, "relaxed")

    # Legs and shoes.
    for side in ("L", "R"):
        # one trouser leg from the hip to the shoe, bending at the knee
        rig.skins.append(Skin(rig, f"leg.{side}", [
            (0.06, 0.0), (0.05, 0.06), (0.03, 0.08), (-0.10, 0.074), (-0.25, 0.066),
            (-0.39, 0.059), (-0.43, 0.058), (-0.47, 0.057), (-0.62, 0.055), (-0.80, 0.053),
            (-0.835, 0.052), (-0.84, 0.0)],
            cloth, (f"thigh.{side}", f"knee.{side}"), (-0.39, -0.47)))
        shoe_o = loft(f"shoe.{side}", [
            (-0.09, 0.0, 0.0, 0, 0.0), (-0.085, 0.034, 0.03), (-0.03, 0.048, 0.044),
            (0.06, 0.052, 0.040), (0.15, 0.046, 0.032), (0.175, 0.0, 0.0)], shoe, coll, n=16)
        rig.attach(shoe_o, f"ankle.{side}", (0, -0.03, -0.045), rot=(90, 0, 0))
        shoe_o.scale = (1.0, 0.62, 1.0)

    _props(rig, coll)

    for side, s in (("L", -1), ("R", 1)):
        rig.joints[f"wrist.{side}"].rotation_euler.z = math.radians(-s * 90)
    for jn, j in rig.joints.items():
        rig.rest[jn] = tuple(math.degrees(a) for a in j.rotation_euler)
    # The arms hang a little away from his sides, bent at the elbow.
    rig.pose({"shoulder.L": (4, 7, 0), "shoulder.R": (4, -7, 0),
              "elbow.L": (-14, 0, 0), "elbow.R": (-14, 0, 0)})
    for o in rig.parts:
        o.lightgroup = ""
    return rig


def _props(rig: Rig, coll) -> None:
    """The things he may hold, built once and put away (`Rig.hold`)."""
    def box(name, size, colour, rough=0.6):
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=1.0)
        bmesh.ops.scale(bm, vec=Vector(size), verts=bm.verts)
        bmesh.ops.bevel(bm, geom=bm.edges[:], offset=min(size) * 0.3, segments=2,
                        affect="EDGES")
        return _mesh_object(name, bm, _mat(name, colour, rough), coll, smooth=True, subdiv=0)

    # a mug: a round body and a handle
    bm = bmesh.new()
    # a size up from life, like his hands
    bmesh.ops.create_cone(bm, cap_ends=True, segments=24, radius1=0.047, radius2=0.050,
                          depth=0.112)
    mug = _mesh_object("prop.mug", bm, _mat("prop.mug", MUG, 0.4), coll, subdiv=0)
    handle = bpy.data.curves.new("prop.mug.handle", "CURVE")
    handle.dimensions = "3D"
    handle.bevel_depth = 0.0085
    sp = handle.splines.new("POLY")
    pts = [(0.047 + 0.028 * math.sin(a), 0.0, 0.030 * math.cos(a))
           for a in [math.pi * k / 10 for k in range(11)]]
    sp.points.add(len(pts) - 1)
    for pt, xyz in zip(sp.points, pts):
        pt.co = (*xyz, 1.0)
    ho = bpy.data.objects.new("prop.mug.handle", handle)
    ho.data.materials.append(_mat("prop.mug", MUG, 0.4))
    coll.objects.link(ho)
    ho.parent = mug
    rig.props["mug"] = mug
    rig.props["phone"] = box("prop.phone", (0.080, 0.010, 0.162), PHONE, 0.3)
    rig.props["page"] = box("prop.page", (0.21, 0.0015, 0.297), PAPER, 0.9)
    rig.props["filing"] = box("prop.filing", (0.22, 0.010, 0.30), FOLDER, 0.9)
    # its cover on the face the camera sees: held, its +y faces out and its
    # -z is up
    cover_png = TEXTURES / "filing.png"
    if cover_png.exists():
        bpy.ops.mesh.primitive_plane_add(size=1.0)
        cover = bpy.context.object
        cover.name = "prop.filing.cover"
        cover.scale = (0.21, 0.288, 1.0)
        for c in cover.users_collection:
            c.objects.unlink(cover)
        coll.objects.link(cover)
        m = _mat("prop.filing.cover", FOLDER, 0.9)
        tex = m.node_tree.nodes.new("ShaderNodeTexImage")
        tex.image = bpy.data.images.load(str(cover_png), check_existing=True)
        tex.extension = "CLIP"
        m.node_tree.links.new(tex.outputs["Color"],
                              m.node_tree.nodes["Principled BSDF"].inputs["Base Color"])
        cover.data.materials.append(m)
        cover.parent = rig.props["filing"]
        cover.location = (0.0, 0.0056, 0.0)
        cover.rotation_euler = (math.radians(-90), 0.0, 0.0)
    for o in rig.props.values():
        rig.parts.append(o)
    rig.hold("")


def _beard(name: str, head: bpy.types.Object, lift: float, m, coll, *,
           lined: bool) -> bpy.types.Object:
    """A beard as a shell laid on the face `lift` off the skin: along the jaw
    from ear to ear, under the chin, a moustache, and a hole round the mouth
    as wide as its widest shape, so every mouth still shows.

    Built on a grid of rays cast out from inside the smoothed head, each hit
    pushed out along the skin's normal, so it sits on the skin at every
    angle, under the chin too. Stubble (`lined` False) carries the Freestyle face mark the
    render's linesets exclude, so it reads as a shade on the skin, not as a
    drawn shape; a beard is outlined like the rest of him."""
    ev = head.evaluated_get(bpy.context.evaluated_depsgraph_get())
    # Rays out from inside the head, round the front and down under the chin.
    # Head-mesh coordinates: the mesh hangs 1 cm under the head joint, so the
    # mouth (0.058 on the joint) is at 0.068 here and the nose's tip at 0.09.
    centre = Vector((0.0, 0.0, 0.095))
    # fine enough that the beard's edge, which follows the grid, reads as a
    # line and not a staircase
    ang = [math.radians(-118 + 236 * i / 157) for i in range(158)]
    els = [math.radians(-78 + 112 * j / 119) for j in range(120)]

    def cheek(a: float) -> float:
        # a beard's cheek line: level with the top of the moustache across
        # the front, then up the side of the face to the ear as a sideburn
        d = abs(math.degrees(a))
        if d <= 20:
            return 0.088
        return 0.088 + 0.054 * (min(d - 20, 62) / 62) ** 2.4

    def mouth(a: float, z: float) -> bool:
        # an oval round the mouth, as wide as its widest shape
        return (math.degrees(a) / 23) ** 2 + ((z - 0.0645) / 0.0150) ** 2 < 1.0

    bm = bmesh.new()
    grid: dict[tuple[int, int], tuple] = {}
    for i, a in enumerate(ang):
        for j, e in enumerate(els):
            d = Vector((math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e)))
            ok, loc, nrm, _ = ev.ray_cast(centre, d)
            if not ok:
                continue
            up = lift
            if lined and abs(math.degrees(a)) < 28 and loc.z > 0.074:
                up *= 1.4      # the moustache stands proud of the lip
            inside = loc.z <= cheek(a) and not mouth(a, loc.z)
            grid[i, j] = (bm.verts.new(loc + nrm * up), inside)
    for i in range(len(ang) - 1):
        for j in range(len(els) - 1):
            quad = [(i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)]
            if all(q in grid and grid[q][1] for q in quad):
                bm.faces.new([grid[q][0] for q in quad])
    for v in [v for v in bm.verts if not v.link_faces]:
        bm.verts.remove(v)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    o = _mesh_object(name, bm, m, coll, subdiv=1)
    if not lined:
        mark = o.data.attributes.get("freestyle_face") or \
            o.data.attributes.new("freestyle_face", "BOOLEAN", "FACE")
        mark.data.foreach_set("value", [True] * len(o.data.polygons))
    return o


def _mouth(name: str, m, coll) -> bpy.types.Object:
    """The mouth as a flat dark shape on the face, its basis a closed line
    and a shape key for each open mouth."""
    n = 16
    shapes = {
        # half width, upper lip lift, lower lip drop, how round (0 wide, 1 round)
        "mouthClosed": (0.017, 0.0007, 0.0007, 0.0),
        "mouthMid": (0.016, 0.0030, 0.0065, 0.2),
        "mouthWide": (0.018, 0.0045, 0.0130, 0.15),
        "mouthO": (0.0095, 0.0060, 0.0100, 1.0),
        "mouthEE": (0.021, 0.0022, 0.0045, 0.0),
        "mouthFV": (0.016, 0.0010, 0.0022, 0.0),
    }

    def outline(w, up, down, roundness):
        pts = []
        for i in range(n):
            a = 2 * math.pi * i / n
            x = math.cos(a)
            y = math.sin(a)
            # a wide mouth is a lens, a round one an ellipse
            shape = abs(y) ** (1.0 - 0.5 * roundness)
            z = (up if y > 0 else down) * (1 if y > 0 else -1) * shape * 1.0
            pts.append((x * w, z))
        return pts

    bm = bmesh.new()
    base = outline(*shapes["mouthClosed"])
    vs = []
    for x, z in base:
        # wrapped round the face: the corners sit further back
        vs.append(bm.verts.new((x, (x / 0.02) ** 2 * 0.006, z)))
    centre = bm.verts.new((0, -0.0004, 0))
    for i in range(n):
        bm.faces.new((centre, vs[i], vs[(i + 1) % n]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    o = _mesh_object(name, bm, m, coll, smooth=False, subdiv=0)
    o.shape_key_add(name="Basis")
    for key, spec in shapes.items():
        if key == "mouthClosed":
            continue
        sk = o.shape_key_add(name=key)
        for i, (x, z) in enumerate(outline(*spec)):
            sk.data[i].co = Vector((x, (x / 0.02) ** 2 * 0.006, z))
        sk.value = 0.0
    return o


def bounds(rig: Rig) -> tuple[Vector, Vector]:
    """His world-space bounding box, as posed now."""
    bpy.context.view_layer.update()
    mn = Vector((1e9,) * 3)
    mx = Vector((-1e9,) * 3)
    for o in rig.parts:
        if o.type != "MESH" or o.hide_render:
            continue
        for c in o.bound_box:
            w = o.matrix_world @ Vector(c)
            mn = Vector(map(min, mn, w))
            mx = Vector(map(max, mx, w))
    return mn, mx


__all__ = ["build_dennis", "Rig", "MOUTHS", "bounds", "Matrix"]
