"""Dennis's room, built once in 3D and rendered from every angle the long shoots.

Item 36 of the build plan. The kit's rooms were flat polygons: a lamp, a board
and a stack of paper were rectangles nobody could name. This is one room, made
of real objects (Kenney's CC0 furniture plus objects built here), lit the way
the kit lights it (the monitor is the key, the desk lamp the fill, a dark blue
room) and outlined in Dennis's own ink, so the set and the figure in it are
drawn the same way.

It runs HERE, never on the render box: every angle is rendered once, and the
pictures it writes into `room3d/renders/` are committed. `scripts/ingest_kit.py`
installs them as every room the kit draws, the long's 16:9 ones and the
shorts' 9:16 ones (from cameras of their own, `PORTRAIT`), under the names
the kit used, so the writer's [SCENE] menu, the room roles and every test
that names a room keep working.

    pip install bpy==5.0.1 OpenEXR      # Blender as a Python module
    python3 room3d/textures.py           # the pictures on the things
    python3 room3d/build.py              # every angle, both seasons, both frames
    python3 room3d/build.py --cam desk-front --preview   # one, fast and small
    python3 room3d/build.py --aspect 9x16 --cam desk-front --preview   # the phone's

What one angle writes (2560x1440 JPEGs, 1440x2560 for the phone's, whose
names end `-9x16`; the ingest brings them to the kit's delivered size):

    <angle><state>.jpg       the room in one light state. Plain angles have
                             four: the night, `_rain`, `_dusk` and
                             `_dusk_rain`, each its own sky through the window
                             and its own light from it. The December twin
                             `<angle>-christmas` has each bulb string lit
                             (`_t0/1/2`, the kit's lights-twinkle) at night and
                             at dusk (`_t0_dusk`...), under the snow skies.
                             Lights are light groups, so a state is a mix,
                             never a render (`states`).
    <angle>_mask_front.png   what stands between him and the camera, per
                             pixel (movable things nearer than where he
                             stands); the ingest cuts each frame's front
                             layer with it
    <angle>_mask_board.png   what the camera sees of the board, the monitor
    <angle>_mask_screen.png  and the night outside, where each video writes
    <angle>_mask_window.png  its board and chart and the ingest draws rain
                             and snow

and `rooms.json`: where he stands in each angle (the host-anchor, solved from
the camera, never guessed), where a chapter title is chalked (the slate, for
the opener angles), how much of his head the front layer covers, and the
board's and the screen's corners and painted colours
(`pipeline/room_dressing.py` writes on them).
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from pathlib import Path

import bpy  # noqa: I001  (bpy first: it puts Blender's own modules on the path)
import addon_utils
import bmesh
import numpy as np
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Matrix, Vector

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from textures import (BOARD_PAPER, CARD_PAPERS, LABELS, NOTE_PAPERS,  # noqa: E402
                      SCREEN_BACKLIGHT, SCREEN_CHART, SCREEN_TEX)

MODELS = HERE / "models"
TEX = HERE / "textures"
RENDERS = HERE / "renders"
REPO = HERE.parent

# The kit's canvas: slots are written in these units, at exportScale 2. The
# long is shot 16:9 and the shorts 9:16 (the phone's rooms are the same room,
# from cameras of their own: `PORTRAIT`).
ASPECTS = ("16x9", "9x16")
CANVASES = {"16x9": (1920, 1080), "9x16": (1080, 1920)}
FULLS = {"16x9": (2560, 1440), "9x16": (1440, 2560)}
PREVIEWS = {"16x9": (640, 360), "9x16": (360, 640)}
FULL = FULLS["16x9"]

# Dennis's standing figure box is 720 units from its top to his floor line and
# his crown sits 11 units under the top (host/to-camera's alpha), so a 1.78 m
# man is a 1.81 m box. The anchor's height is the box's projected height.
DENNIS_CROWN_M = 1.78
DENNIS_BOX_M = DENNIS_CROWN_M * 720 / 709
SHOULDER_UNITS = 192          # kit_engine.js: crown 60 + 1.32 head units

INK = "#0B0E16"               # his outline colour; the set is drawn in it too

# --------------------------------------------------------------------- the room
# Metres. x runs left to right as you face the window wall, y into the room
# towards it, z up. The window wall's face is y = 2.0.
BACK, LEFT, RIGHT, FRONT, HEIGHT = 2.0, -3.2, 3.2, -3.6, 2.8
WINDOW = (0.70, 2.30, 0.95, 2.35)        # x0, x1, z0, z1
BOARD = (-2.90, -1.00, 0.92, 2.02)       # the whiteboard
SLATE = (-0.86, 0.58, 1.42, 2.14)        # the slate a chapter title is chalked on
DOOR = (-1.36, -0.44, 2.08)              # on the left wall: y0, y1, height
DESK = (2.05, 0.86, 1.62, 0.76, 1.04)    # centre x, centre y, width, depth, top z
SCREEN_ROT = -25                         # the screen turned to the room: its chart reads
MONITOR_GLASS = (0.78, 0.78 * 9 / 16)    # the glass, 16:9 like the plates it shows
MONITOR_TILT = 6                         # degrees it leans back

# ------------------------------------------------------------------- the angles
# Every angle the kit drew at 16:9, under its own name, each with its job:
#   cam      where the camera is, what it looks at, its lens (mm, 36 mm film)
#   spot     where he stands (floor x, y), or None where nobody does
#   title    the angle opens chapters: the title is chalked on the slate
# Every one of them is a camera in the same room, so a cut between two of them
# is a cut between two views of one place.
CAMERAS: dict[str, dict] = {
    # establish / opener: the room, whole, him behind the desk
    "desk-wide": {"cam": ((-0.20, -3.30, 1.62), (0.60, 2.0, 1.32), 24),
                  "spot": (2.05, 1.46), "title": True},
    # talk: at the desk, the window behind him
    "desk-front": {"cam": ((1.70, -1.05, 1.52), (1.90, 2.0, 1.28), 30),
                   "spot": (1.95, 1.46)},
    "desk-front-b": {"cam": ((0.60, -0.90, 1.48), (2.20, 2.0, 1.28), 30),
                     "spot": (2.05, 1.55)},
    "desk-front-low": {"cam": ((1.05, -0.65, 0.95), (2.00, 2.0, 1.45), 28),
                       "spot": (2.02, 1.46)},
    # read: closer, the papers and the screen
    "desk-side": {"cam": ((2.55, -0.60, 1.55), (1.35, 1.35, 1.15), 30),
                  "spot": (1.55, 1.48)},
    "read-close": {"cam": ((1.85, -0.20, 1.45), (1.95, 2.0, 1.38), 34),
                   "spot": (1.80, 1.46)},
    "turn-to-screen": {"cam": ((0.15, -0.60, 1.50), (2.15, 1.20, 1.20), 32),
                       "spot": (1.25, 1.38)},
    # the board: the receipts close, him beside it, and the wide
    "board": {"cam": ((-1.95, -0.25, 1.47), (-1.95, 2.0, 1.47), 33), "spot": None},
    # the wall clock, close: the clock jump between scenes (the long only)
    "clock": {"cam": ((-1.27, 0.55, 2.33), (-1.25, 2.0, 2.42), 64), "spot": None},
    "board-side": {"cam": ((-3.00, -0.55, 1.55), (-1.40, 2.0, 1.38), 28),
                   "spot": (-2.25, 1.30)},
    "board-wide": {"cam": ((-1.45, -3.20, 1.60), (-1.10, 2.0, 1.36), 24),
                   "spot": (-2.25, 1.30), "title": True},
    # the window wall
    "window-wall": {"cam": ((-0.35, -1.10, 1.50), (1.60, 2.0, 1.45), 28),
                    "spot": (0.45, 1.34)},
    "window-talk": {"cam": ((0.55, -1.30, 1.52), (1.30, 2.0, 1.45), 30),
                    "spot": (0.95, 1.40)},
    "window-wide": {"cam": ((-1.20, -3.10, 1.60), (1.20, 2.0, 1.40), 24),
                    "spot": (0.45, 1.34), "title": True},
    # exit: the door in the left wall
    "doorway": {"cam": ((1.30, 0.40, 1.55), (-3.20, -0.90, 1.25), 28),
                "spot": (-2.70, -0.05)},
    "doorway-wide": {"cam": ((2.20, -0.70, 1.60), (-3.20, -0.75, 1.25), 24),
                     "spot": (-2.55, 0.55)},
    # surface: straight down on the desk; nobody stands on a desk
    "desk-top-down": {"cam": ((1.85, 0.50, 2.35), (1.92, 0.80, 1.04), 30), "spot": None},
    # panel: him on the left, a quiet wall on the right for the evidence
    "panel-left": {"cam": ((-1.60, -2.00, 1.50), (0.90, 2.0, 1.35), 30),
                   "spot": (-0.35, 1.25)},
}

# THE PHONE'S ANGLES (the shorts, 9:16): the same angles in the same room, each
# from a camera of its own, because a 9:16 crop of a 16:9 frame is a strip of
# wall with half of him in it. He stands where the long stands him and the
# camera comes round to put him in the middle of the phone at the size
# design's 9:16 rooms drew him (feet and height as their anchors had them),
# along the long camera's own line to him, so a short and the long see the
# same corner from the same side. `roll` turns the frame on its axis: the desk
# seen from above runs down the phone, not across it. No angle chalks a title:
# a short has no chapters, and from a phone's width the slate is either behind
# his head or out of shot (the ingest takes the title off the 9:16 openers).
PORTRAIT: dict[str, dict] = {
    "desk-wide": {"cam": ((0.68, -1.45, 1.62), (2.04, 1.44, 1.04), 30),
                 "spot": (2.05, 1.46)},
    "desk-front": {"cam": ((1.74, -0.64, 1.52), (1.95, 1.42, 0.96), 30),
                  "spot": (1.95, 1.46)},
    "desk-front-b": {"cam": ((0.92, -0.36, 1.48), (2.03, 1.52, 0.95), 30),
                    "spot": (2.05, 1.55)},
    "desk-front-low": {"cam": ((0.96, -0.83, 0.95), (2.02, 1.47, 0.98), 30),
                      "spot": (2.02, 1.46)},
    "desk-side": {"cam": ((2.70, -0.91, 1.55), (1.56, 1.47, 1.07), 30),
                 "spot": (1.55, 1.48)},
    "read-close": {"cam": ((1.88, -1.06, 1.45), (1.80, 1.43, 0.95), 30),
                  "spot": (1.80, 1.46)},
    # (turning to the screen, the screen is the point: this camera keeps to
    # his left with the monitor on the phone's right, 24 Oct 2026, V8)
    "turn-to-screen": {"cam": ((-0.30, -0.70, 1.52), (1.80, 1.20, 1.00), 28),
                      "spot": (1.25, 1.38)},
    "board": {"cam": ((-1.80, -0.25, 1.47), (-1.80, 2.0, 1.47), 26), "spot": None},
    "board-side": {"cam": ((-2.99, -0.54, 1.55), (-2.26, 1.28, 1.06), 24.6),
                  "spot": (-2.25, 1.30)},
    "board-wide": {"cam": ((-1.69, -1.85, 1.60), (-2.25, 1.32, 1.37), 30),
                  "spot": (-2.25, 1.30)},
    "window-wall": {"cam": ((-0.38, -1.20, 1.50), (0.44, 1.31, 0.97), 30),
                   "spot": (0.45, 1.34)},
    "window-talk": {"cam": ((0.56, -1.23, 1.52), (0.94, 1.37, 0.97), 30),
                   "spot": (0.95, 1.40)},
    "window-wide": {"cam": ((-0.74, -1.85, 1.60), (0.46, 1.36, 1.34), 30),
                   "spot": (0.45, 1.34)},
    "doorway": {"cam": ((-0.24, 0.23, 1.55), (-2.66, -0.04, 0.94), 30),
               "spot": (-2.70, -0.05)},
    "doorway-wide": {"cam": ((-0.51, 0.01, 1.60), (-2.52, 0.54, 1.01), 30),
                    "spot": (-2.55, 0.55)},
    "desk-top-down": {"cam": ((2.00, 0.68, 2.35), (2.05, 0.86, 1.04), 30), "spot": None,
                      "roll": 90},
    "panel-left": {"cam": ((-1.19, -0.94, 1.50), (-0.36, 1.22, 0.98), 30),
                  "spot": (-0.35, 1.25)},
}

# THE PAPER ON THE FLOOR IN FRONT OF HIM (V8, 24 Oct 2026): on the phone's
# wide angles the floor between him and the camera was bare. Each of these has
# two piles of its own, either side of him and a step nearer the camera, clear
# of him and inside the phone's frame, built in the room and rendered in that
# angle only (`camera`): where each stands on the floor, its turn, and its
# height, in metres.
FLOOR_PILES = {
    "board-wide": (((-1.70, 1.07), 14, 0.40), ((-2.70, 0.90), -9, 0.30)),
    "doorway": (((-2.35, -0.50), 8, 0.40), ((-2.48, 0.48), -15, 0.28)),
    "doorway-wide": (((-2.42, 0.05), -6, 0.28), ((-2.23, 0.93), 12, 0.40)),
    "panel-left": (((-0.88, 1.17), 10, 0.30), ((-0.03, 0.83), -12, 0.40)),
}
RUG = (0.15, -0.05, 3.3, 2.2)                   # centre x, y, width, depth

# THE READ 10-Ks (V12, 24 Oct 2026): a report for every long that has gone
# public, squared up on the floor under the board beside the box of old
# filings; from the twenty-fifth a second pile beside the first, and never
# more than PILE_MAX. It grows per video, so the room is rendered without it
# and perform draws it for each video (`ten_k_pile`). Both piles are behind
# every spot he stands on (x, y, turn).
PILES = ((-1.62, 1.72, -6.0), (-1.95, 1.74, 9.0))
PILE_SIZE = 24
PILE_MAX = 2 * PILE_SIZE

# The kit's December twins: the angles the Christmas set dresses.
CHRISTMAS = ("desk-front", "desk-wide", "desk-side", "turn-to-screen", "window-wall",
             "doorway", "desk-front-b", "desk-front-low", "read-close", "board-side",
             "board-wide", "window-wide", "window-talk", "doorway-wide", "panel-left")

# THE LIGHT GROUPS. Everything that lights the room is in one, and a picture
# is a mix of them, so a state is never a second render. The view through the
# window is one group a sky (V10, 24 Oct 2026): each sky's pane, and the
# light it throws into the room, are seen and lit on their own, so the night,
# the dusk and the rain are three mixes of one render. December's skies are
# the snow twins, and its three bulb strings are a group each. The rest are
# the room's own (`room`, the world's dark blue and its fills), the desk
# lamp, the screen's glow and the laundromat's light from the street.
SKIES = {"plain": {"sky": "night", "sky_rain": "night_rain", "sky_dusk": "dusk",
                   "sky_dusk_rain": "dusk_rain"},
         "christmas": {"sky": "night_snow", "sky_dusk": "dusk_snow"}}
# Each sky's light into the room (the moon's, at night): its colour and power.
SKY_LIGHT = {"night": ("#9AB4E0", 70), "night_rain": ("#8C9AB4", 48),
             "dusk": ("#D8A4B4", 160), "dusk_rain": ("#A89CB4", 90),
             "night_snow": ("#A8BCE4", 80), "dusk_snow": ("#D4ACC0", 165)}
# The room at each hour, in each weather: which sky, and what else moves. The
# laundromat over the road (pick 8) is a glow at night, little against the
# last of the daylight, softer in the rain; a weight may be a tint (r, g, b).
NIGHT = dict(room=1.0, lamp=1.0, screen=1.0, laundromat=1.0)
LOOKS = {"": dict(sky=1.0),
         "_rain": dict(sky_rain=1.0, laundromat=0.75),
         "_dusk": dict(sky_dusk=1.0, laundromat=0.4, room=(1.10, 1.02, 0.96)),
         "_dusk_rain": dict(sky_dusk_rain=1.0, laundromat=0.55, room=(1.04, 1.0, 0.99))}
# December's lights-twinkle steps the three bulb strings every four frames.
TWINKLE = (dict(xmasA=1.0, xmasB=0.18, xmasC=0.18),
           dict(xmasA=0.18, xmasB=1.0, xmasC=0.18),
           dict(xmasA=0.18, xmasB=0.18, xmasC=1.0))
# (The kit's screen-flicker dips are not rendered since 24 Oct 2026: the
# ingest has played none since the monitor was made to hold still, 3 Oct.)


def states(season: str) -> dict[str, dict]:
    """Every picture a loop of this season shows, by tag, as the weight of
    each light group (a group not named is off): plain `""` (night), `_rain`,
    `_dusk` and `_dusk_rain`; December `_t<n>` and `_t<n>_dusk`, a bulb
    string lit at each hour (snow is drawn on the glass at install)."""
    if season == "plain":
        return {tag: dict(NIGHT, **look) for tag, look in LOOKS.items()}
    return {f"_t{t}{hour}": dict(NIGHT, **LOOKS[hour], **bulbs)
            for t, bulbs in enumerate(TWINKLE) for hour in ("", "_dusk")}


def apply_state(season: str, tag: str = "") -> None:
    """Light the built room as one of its states for a render that is NOT a
    mix of light groups (perform's: him, lit by the room). A light is scaled
    and tinted by its group's weight, and a lit thing whose group the state
    leaves out goes dark. Without it every sky would light him at once."""
    weights = states(season)[tag or next(iter(states(season)))]
    for o in bpy.context.scene.objects:
        g = o.lightgroup
        if not g:
            continue
        w = weights.get(g, 0.0)
        tint = np.broadcast_to(np.asarray(w, dtype=float), (3,))
        k = float(tint.mean())
        if o.type == "LIGHT":
            o.data["energy0"] = o.data.get("energy0", o.data.energy)
            o.data["colour0"] = list(o.data.get("colour0", o.data.color))
            o.data.energy = o.data["energy0"] * k
            if k > 0:
                o.data.color = [c * t / k for c, t in zip(o.data["colour0"], tint)]
        else:
            o.hide_render = k == 0


# ----------------------------------------------------------------- materials
def lin(h: str) -> tuple[float, float, float, float]:
    h = h.lstrip("#")
    c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return tuple(((v + 0.055) / 1.055) ** 2.4 if v > 0.04045 else v / 12.92 for v in c) + (1.0,)


_MATS: dict[str, bpy.types.Material] = {}


def mat(name: str, color: str, rough: float = 0.9, *, image: str = "",
        emit: str = "", strength: float = 0.0, metal: float = 0.0) -> bpy.types.Material:
    if name in _MATS:
        return _MATS[name]
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = lin(color)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    if image:
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = bpy.data.images.load(str(TEX / image))
        tex.extension = "CLIP"
        nt.links.new(tex.outputs["Color"], b.inputs["Base Color"])
        if emit:
            nt.links.new(tex.outputs["Color"], b.inputs["Emission Color"])
    if emit:
        if not image:
            b.inputs["Emission Color"].default_value = lin(emit)
        b.inputs["Emission Strength"].default_value = strength
    _MATS[name] = m
    return m


def screen_mat() -> bpy.types.Material:
    """The monitor's picture, lit by itself and seen by the camera ONLY.

    Its chart area is a flat backlight the bot draws each episode's chart
    through, so the panel's brightness must not light the room: the screen's
    light on the desk and on him is the `screenglow` area light, which is the
    same whatever chart is showing. Strength 1 keeps the backlight at its own
    value in the render, where 8 bits have room for a dark chart and a bright
    line both.
    """
    m = bpy.data.materials.new("screen")
    m.use_nodes = True
    nt = m.node_tree
    for nd in list(nt.nodes):
        nt.nodes.remove(nd)
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = bpy.data.images.load(str(TEX / "monitor.png"))
    tex.extension = "CLIP"
    path = nt.nodes.new("ShaderNodeLightPath")
    em = nt.nodes.new("ShaderNodeEmission")
    nt.links.new(tex.outputs["Color"], em.inputs["Color"])
    nt.links.new(path.outputs["Is Camera Ray"], em.inputs["Strength"])
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(em.outputs["Emission"], out.inputs["Surface"])
    return m


def sky_mat(picture: str) -> bpy.types.Material:
    """One sky through the window: its picture as light, and every ray let
    through, so the panes stacked behind it are seen too, each in its own
    light group (`SKIES`). Lit by itself, as the night outside always was."""
    m = bpy.data.materials.new(f"sky-{picture}")
    m.use_nodes = True
    nt = m.node_tree
    for nd in list(nt.nodes):
        nt.nodes.remove(nd)
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = bpy.data.images.load(str(TEX / f"{picture}.png"))
    tex.extension = "CLIP"
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Strength"].default_value = 1.3
    nt.links.new(tex.outputs["Color"], em.inputs["Color"])
    clear = nt.nodes.new("ShaderNodeBsdfTransparent")
    add = nt.nodes.new("ShaderNodeAddShader")
    nt.links.new(em.outputs["Emission"], add.inputs[0])
    nt.links.new(clear.outputs["BSDF"], add.inputs[1])
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(add.outputs["Shader"], out.inputs["Surface"])
    return m


# Kenney's material names, recoloured to the night set.
KENNEY = {"wood": "#7A5638", "woodDark": "#4A3426", "metal": "#9AA4B4",
          "metalMedium": "#5A6880", "metalDark": "#262E3C", "carpet": "#3C4C6C",
          "carpetDarker": "#2A3650", "carpetWhite": "#C9D2D8", "plant": "#3D7A5A",
          "glass": "#2A3446", "_defaultMat": "#2A3448", "metalLight": "#C4CCD6"}


# ----------------------------------------------------------------- the things
# Every object belongs to a THING, and a thing is the unit an angle sorts into
# in front of him or behind him. `fixed` things are the room itself (walls,
# floor, what hangs on the walls): never in front of anybody.
THINGS: dict[str, dict] = {}
_current = {"thing": None}
# THE THINGS THE BOT LETTERS (18 Oct 2026): each plane painted blank, by name,
# with its kind (textures.LABELS) and its paper. rooms.json says where each is
# in a shot and the mask pass draws them red, so the video's words go on them
# through the room's light (pipeline/room_dressing.py).
LETTERED: dict[str, dict] = {}


def lettered(o: bpy.types.Object, kind: str, paper=None,
             half: tuple[float, float] = (0.5, 0.5)) -> bpy.types.Object:
    """`o` lettered by the bot; `half` its half width and height in its own
    units (a unit plane's 0.5, the clock face's radius)."""
    LETTERED[o.name] = {"kind": kind, "paper": list(paper or LABELS[kind][1]),
                        "half": list(half)}
    return o


def thing(name: str, *, fixed: bool = False, season: str = ""):
    """Start a thing, or go back to one: every object made until the next call
    belongs to it."""
    THINGS.setdefault(name, {"objects": [], "fixed": fixed, "season": season})
    _current["thing"] = name
    return name


def own(obj: bpy.types.Object, group: str = "") -> bpy.types.Object:
    THINGS[_current["thing"]]["objects"].append(obj)
    if group:
        obj.lightgroup = group
    return obj


def box(name: str, size, loc, m, rot=(0, 0, 0), group: str = "") -> bpy.types.Object:
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc, rotation=rot)
    o = bpy.context.object
    o.name = name
    o.scale = size
    o.data.materials.append(m)
    return own(o, group)


def plane(name: str, size, loc, rot, m, group: str = "") -> bpy.types.Object:
    bpy.ops.mesh.primitive_plane_add(size=1, location=loc, rotation=rot)
    o = bpy.context.object
    o.name = name
    o.scale = (size[0], size[1], 1)
    o.data.materials.append(m)
    return own(o, group)


def cyl(name: str, r: float, depth: float, loc, m, rot=(0, 0, 0), verts: int = 24,
        group: str = "") -> bpy.types.Object:
    bpy.ops.mesh.primitive_cylinder_add(radius=r, depth=depth, location=loc, rotation=rot,
                                        vertices=verts)
    o = bpy.context.object
    o.name = name
    o.data.materials.append(m)
    return own(o, group)


def sphere(name: str, r: float, loc, m, group: str = "") -> bpy.types.Object:
    bpy.ops.mesh.primitive_uv_sphere_add(radius=r, location=loc, segments=12, ring_count=8)
    o = bpy.context.object
    o.name = name
    o.data.materials.append(m)
    return own(o, group)


def cone(name: str, r: float, depth: float, loc, m) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cone_add(radius1=r, depth=depth, location=loc, vertices=20)
    o = bpy.context.object
    o.name = name
    o.data.materials.append(m)
    return own(o)


def kenney(name: str, loc, rot: float = 0.0, scale: float = 2.0, recolor=None):
    """Import one of Kenney's models, recoloured, sat on (x, y, z) by its
    footprint's centre and its lowest point."""
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(MODELS / f"{name}.glb"))
    new = [o for o in bpy.data.objects if o not in before]
    root = bpy.data.objects.new(f"{name}_root", None)
    bpy.context.scene.collection.objects.link(root)
    for o in new:
        if o.parent is None:
            o.parent = root
        if o.type == "MESH":
            for s in o.material_slots:
                if s.material:
                    base = s.material.name.split(".")[0]
                    colour = (recolor or {}).get(base) or KENNEY.get(base)
                    if colour:
                        s.material = mat(f"k_{base}_{colour}", colour)
            own(o)
    root.scale = (scale,) * 3
    root.rotation_euler = (0, 0, math.radians(rot))
    bpy.context.view_layer.update()
    mn, mx = bbox([o for o in new if o.type == "MESH"])
    root.location = Vector(loc) - Vector(((mn.x + mx.x) / 2, (mn.y + mx.y) / 2, mn.z))
    bpy.context.view_layer.update()
    return bbox([o for o in new if o.type == "MESH"])


def bbox(objs):
    mn = Vector((1e9,) * 3)
    mx = Vector((-1e9,) * 3)
    for o in objs:
        if o.type != "MESH":
            continue
        for c in o.bound_box:
            w = o.matrix_world @ Vector(c)
            mn = Vector(map(min, mn, w))
            mx = Vector(map(max, mx, w))
    return mn, mx


def pleats(name: str, x0: float, x1: float, y: float, z0: float, z1: float,
           folds: int, depth: float, m) -> bpy.types.Object:
    """A curtain: a strip folded back and forth, hanging from z1 to z0."""
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    n = folds * 2
    cols = []
    for i in range(n + 1):
        x = x0 + (x1 - x0) * i / n
        dy = depth * (0.5 + 0.5 * math.cos(i * math.pi))
        cols.append((bm.verts.new((x, y - dy, z0)), bm.verts.new((x, y - dy, z1))))
    for (a0, a1), (b0, b1) in zip(cols, cols[1:]):
        bm.faces.new((a0, b0, b1, a1))
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(o)
    me.materials.append(m)
    mod = o.modifiers.new("thick", "SOLIDIFY")
    mod.thickness = 0.012
    return own(o)


# ----------------------------------------------------------------- the build
def ribbon(name: str, path, width: float, m) -> bpy.types.Object:
    """A strip of paper along `path`, `width` wide across x: adding-machine
    tape. Smoothed through its points so it curls rather than kinks."""
    pts = [Vector(p) for p in path]
    fine = []
    for i in range(len(pts) - 1):
        p0, p1 = pts[max(i - 1, 0)], pts[i]
        p2, p3 = pts[i + 1], pts[min(i + 2, len(pts) - 1)]
        for k in range(6):
            t = k / 6
            fine.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t
                               + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3))
    fine.append(pts[-1])
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    half = Vector((width / 2, 0, 0))
    rows = [(bm.verts.new(p - half), bm.verts.new(p + half)) for p in fine]
    for (a0, a1), (b0, b1) in zip(rows, rows[1:]):
        bm.faces.new((a0, a1, b1, b0))
    bm.to_mesh(mesh)
    bm.free()
    o = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(o)
    o.data.materials.append(m)
    return own(o)


def mug(name: str, loc, colour: str, turn: float = 0.0) -> None:
    """A mug, its handle turned `turn` degrees."""
    m = mat(f"mug-{colour}", colour, 0.5)
    cyl(name, 0.045, 0.10, (loc[0], loc[1], loc[2] + 0.05), m)
    a = math.radians(turn)
    bpy.ops.mesh.primitive_torus_add(major_radius=0.03, minor_radius=0.009,
                                     location=(loc[0] + 0.05 * math.cos(a), loc[1] + 0.05 * math.sin(a), loc[2] + 0.055),
                                     rotation=(math.radians(90), 0, a + math.radians(90)))
    bpy.context.object.data.materials.append(m)
    own(bpy.context.object)


def paper_stack(name: str, loc, height: float, top: str, turn: float = 0.0, tabs: int = 4) -> None:
    """A printed filing, A4 and thick, with sticky tabs out of its edge where
    somebody marked the pages that matter."""
    x, y, z = loc
    rot = (0, 0, math.radians(turn))
    box(f"{name}-paper", (0.21, 0.297, height), (x, y, z + height / 2), mat("stackpaper", "#E8E8E2", 0.9), rot=rot)
    plane(f"{name}-top", (0.21, 0.297), (x, y, z + height + 0.001), rot, mat(f"top-{top}", "#E8E8E2", image=top))
    inks = ("#F2D45C", "#F07A8A", "#7FC4E8", "#9AD47F")
    a = math.radians(turn)
    for k in range(tabs):
        side = 1 if k % 2 == 0 else -1
        along = -0.10 + 0.2 * (k + 0.5) / tabs
        tx = x + side * 0.115 * math.cos(a) - along * math.sin(a)
        ty = y + side * 0.115 * math.sin(a) + along * math.cos(a)
        tz = z + height * (0.2 + 0.6 * ((k * 0.37) % 1))
        box(f"{name}-tab{k}", (0.03, 0.022, 0.002), (tx, ty, tz), mat(f"tab{k % 4}", inks[k % 4], 0.7), rot=rot)


def dead_screen(name: str, loc, rot: float, scale: float = 1.9) -> None:
    """One of the screens from the trading years: off, dusty, one cracked."""
    smn, smx = kenney("computerScreen", loc, rot=rot, scale=scale, recolor={k: "#30363F" for k in KENNEY})
    r = math.radians(rot)
    n = Vector((math.sin(r), -math.cos(r), 0))
    sw = math.hypot(smx.x - smn.x, smx.y - smn.y)
    face = plane(f"{name}-face", (sw * 0.80, (smx.z - smn.z) * 0.60),
                 ((smn.x + smx.x) / 2, (smn.y + smx.y) / 2, smn.z + (smx.z - smn.z) * 0.60),
                 (math.radians(90), 0, r), mat("deadscreen", "#10141A", 0.25, image="dead_screen.png"))
    face.location += n * 0.04


def band(name: str, centre, r: float, z0: float, z1: float, facing: float, span: float,
         m) -> bpy.types.Object:
    """A label round a jar: a strip of its side, `span` degrees about the
    side that faces `facing` (degrees, x towards y), its picture the right
    way round from outside."""
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    uv = bm.loops.layers.uv.new()
    n = 16
    cols = []
    for i in range(n + 1):
        a = math.radians(facing - span / 2 + span * i / n)
        x, y = centre[0] + r * math.cos(a), centre[1] + r * math.sin(a)
        cols.append((bm.verts.new((x, y, z0)), bm.verts.new((x, y, z1)), i / n))
    for (b0, t0, u0), (b1, t1, u1) in zip(cols, cols[1:]):
        f = bm.faces.new((b0, b1, t1, t0))
        for loop, st in zip(f.loops, ((u0, 0), (u1, 0), (u1, 1), (u0, 1))):
            loop[uv].uv = st
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(o)
    me.materials.append(m)
    return own(o)


def jar(name: str, at, facing: float) -> None:
    """Mum's jar (pick 3): glass, a red lid, her masking tape reading DENNIS
    (AGAIN) turned to the room, and a few coins in the bottom."""
    x, y, z = at
    r, h = 0.075, 0.20
    glass = mat("jarglass", "#DCEAE6", 0.04)
    glass.node_tree.nodes["Principled BSDF"].inputs["Transmission Weight"].default_value = 1.0
    bpy.ops.mesh.primitive_cylinder_add(radius=r, depth=h, location=(x, y, z + h / 2), vertices=40,
                                        end_fill_type="NOTHING")
    o = bpy.context.object
    o.name = f"{name}-glass"
    o.data.materials.append(glass)
    o.modifiers.new("wall", "SOLIDIFY").thickness = 0.004
    own(o)
    cyl(f"{name}-base", r - 0.002, 0.006, (x, y, z + 0.003), glass, verts=40)
    cyl(f"{name}-lid", r + 0.005, 0.032, (x, y, z + h + 0.016), mat("jarlid", "#B23A2E", 0.5), verts=40)
    coin = mat("coin", "#C8A048", 0.35, metal=0.8)
    rnd = random.Random(3)
    for k in range(8):
        a, d = rnd.uniform(0, math.tau), rnd.uniform(0, r - 0.022)
        cyl(f"{name}-coin{k}", 0.0115, 0.0024, (x + d * math.cos(a), y + d * math.sin(a), z + 0.008 + 0.0025 * (k % 3)),
            coin, rot=(rnd.uniform(-0.25, 0.25), rnd.uniform(-0.25, 0.25), 0), verts=16)
    span = 110
    tall = 2 * math.pi * (r + 0.003) * span / 360 / 3.2      # the tape's picture is 3.2 to 1
    band(f"{name}-label", (x, y), r + 0.003, z + 0.07, z + 0.07 + tall, facing, span,
         mat("jarlabel", "#E2D2A4", 0.8, image="jar_label.png"))


def plant_tag(at, facing: float) -> None:
    """A plant's name tag (pick 2) on its stake in the soil at `at`, its face
    turned `facing` degrees from the room's -y, leaning back a little. The
    bot writes the name (`plant`)."""
    x, y, z = at
    a = math.radians(facing)
    out = Vector((math.sin(a), -math.cos(a), 0))
    box("plant-stake", (0.014, 0.004, 0.17), (x, y, z + 0.085), mat("stake", "#E8E8E2", 0.5), rot=(0, 0, a))
    lettered(plane("plant-tag", (0.15, 0.083), Vector((x, y, z + 0.205)) + out * 0.006,
                   (math.radians(74), 0, a), mat("planttag", "#F2F2EC", 0.5, image="plant_tag.png")), "plant")


def blanket(name: str, front: float, y0: float, y1: float, seat: float, m) -> bpy.types.Object:
    """The blanket thrown back off the sofa: crumpled on the seat from the
    back cushion to the front edge, `y0` to `y1` along it, heaped where it was
    pushed off, then down the front with its hem uneven."""
    rnd = random.Random(6)
    waves = [(rnd.uniform(4, 11), rnd.uniform(3, 9), rnd.uniform(0, 6.3), rnd.uniform(0.006, 0.016))
             for _ in range(5)]
    lie, drop = 0.50, 0.30
    nu, ns = 36, 28
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    uv = bm.loops.layers.uv.new()
    grid = []
    for i in range(nu + 1):
        u = i / nu
        row = []
        for j in range(ns + 1):
            s = (lie + drop) * j / ns
            y = y0 + (y1 - y0) * u
            if s <= lie:
                heap = 0.07 * math.exp(-((u - 0.35) ** 2 / 0.025 + (s - 0.22) ** 2 / 0.02))
                crumple = abs(sum(a * math.sin(fu * u * 6 + fs * s * 6 + ph) for fu, fs, ph, a in waves))
                p = (front - lie + s, y, seat + 0.025 + heap + crumple)
            else:
                d = (s - lie) * (0.78 + 0.22 * math.sin(u * 7 + 0.5))
                fold = 0.025 * math.sin(u * 19 + 1.3) * min(d / 0.08, 1.0)
                p = (front + 0.05 + fold, y, seat + 0.02 - d)
            row.append(bm.verts.new(p))
        grid.append(row)
    for i in range(nu):
        for j in range(ns):
            f = bm.faces.new((grid[i][j], grid[i][j + 1], grid[i + 1][j + 1], grid[i + 1][j]))
            for loop, (a, b) in zip(f.loops, ((i, j), (i, j + 1), (i + 1, j + 1), (i + 1, j))):
                loop[uv].uv = (a / nu, b / ns)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(o)
    me.materials.append(m)
    o.modifiers.new("cloth", "SOLIDIFY").thickness = 0.01
    return own(o)


def floor_pile(name: str, at, turn: float, height: float, seed: int) -> None:
    """Filings on the floor where he left them: reams squared up and knocked
    askew to `height`, and a sheet that slid off."""
    rnd = random.Random(seed)
    x, y = at
    rx, ry, rw, rd = RUG
    ground = 0.0085 if abs(x - rx) < rw / 2 and abs(y - ry) < rd / 2 else 0.0
    z = ground
    tops = ("form10q.png", "proxy.png", "sheet.png")
    k = 0
    while height - z > 0.03:
        h = min(rnd.uniform(0.07, 0.13), height - z)
        paper_stack(f"{name}-{k}", (x + rnd.uniform(-0.03, 0.03), y + rnd.uniform(-0.03, 0.03), z), h,
                    tops[k % 3], turn=turn + rnd.uniform(-14, 14), tabs=rnd.choice((0, 2, 3)))
        z += h
        k += 1
    a = math.radians(turn + rnd.uniform(30, 60))
    plane(f"{name}-loose", (0.21, 0.297), (x + 0.26 * math.cos(a), y + 0.26 * math.sin(a), ground + 0.0015),
          (0, 0, a + 0.4), mat("sheet", "#D9DDE0", image="sheet.png"))


def ten_k_pile(count: int) -> list[bpy.types.Object]:
    """The read 10-Ks, `count` of them (PILE_SIZE to a pile, at most
    PILE_MAX), as the thing `tenk`: letter-size reports a centimetre or so
    thick, each knocked a little askew, some with a binder clip or a tab, and
    a 10-K's cover on top. Each report is seeded by its place in the pile, so
    the pile grows by one and the rest stay where they were."""
    thing("tenk")
    made = []
    papers = [mat(f"tenk{k}", c, 0.9) for k, c in enumerate(("#E6E6DE", "#DCDCD2", "#EAE6D8"))]
    clip = mat("tenkclip", "#1C2027", 0.4, metal=0.6)
    inks = ("#F2D45C", "#F07A8A", "#7FC4E8", "#9AD47F")
    count = max(0, min(int(count), PILE_MAX))
    for p, (x, y, turn) in enumerate(PILES):
        n = min(max(count - p * PILE_SIZE, 0), PILE_SIZE)
        z, top = 0.0, None
        for k in range(n):
            rnd = random.Random(f"tenk-{p}-{k}")
            t = rnd.uniform(0.010, 0.016)
            a = math.radians(turn + rnd.uniform(-7, 7))
            cx, cy = x + rnd.uniform(-0.012, 0.012), y + rnd.uniform(-0.012, 0.012)
            made.append(box(f"tenk{p}-{k}", (0.216, 0.279, t), (cx, cy, z + t / 2),
                            papers[rnd.randrange(3)], rot=(0, 0, a)))
            # along the report (its long side) and across it, in the room
            along, across = Vector((-math.sin(a), math.cos(a), 0)), Vector((math.cos(a), math.sin(a), 0))
            if rnd.random() < 0.35:
                at = Vector((cx, cy, z + t / 2)) + along * 0.135 + across * rnd.uniform(-0.05, 0.05)
                made.append(box(f"tenk{p}-{k}-clip", (0.05, 0.022, t + 0.006), at, clip, rot=(0, 0, a)))
            if rnd.random() < 0.3:
                side = rnd.choice((-1, 1))
                at = Vector((cx, cy, z + t * 0.6)) + across * side * 0.116 + along * rnd.uniform(-0.09, 0.09)
                made.append(box(f"tenk{p}-{k}-tab", (0.03, 0.022, 0.002), at,
                                mat(f"tab{k % 4}", inks[k % 4], 0.7), rot=(0, 0, a)))
            z += t
            top = (cx, cy, z, a)
        if top is not None:
            cx, cy, z, a = top
            made.append(plane(f"tenk{p}-cover", (0.216, 0.279), (cx, cy, z + 0.0008), (0, 0, a),
                              mat("tenkcover", "#E6E6DE", image="filing_held.png")))
    return made


def wallpaper(name: str, base: str, stripe: str, period: float = 0.22) -> bpy.types.Material:
    """A papered wall, not bare plaster: broad stripes a shade apart, laid by
    where they are in the room (x + y), so every wall's run on round the
    corner without a seam."""
    m = mat(name, base)
    nt = m.node_tree
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    add = nt.nodes.new("ShaderNodeMath")
    add.operation = "ADD"
    div = nt.nodes.new("ShaderNodeMath")
    div.operation = "DIVIDE"
    div.inputs[1].default_value = period
    frac = nt.nodes.new("ShaderNodeMath")
    frac.operation = "FRACT"
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.interpolation = "CONSTANT"
    ramp.color_ramp.elements[0].position = 0.0
    ramp.color_ramp.elements[0].color = lin(base)
    ramp.color_ramp.elements[1].position = 0.55
    ramp.color_ramp.elements[1].color = lin(stripe)
    nt.links.new(geo.outputs["Position"], sep.inputs[0])
    nt.links.new(sep.outputs["X"], add.inputs[0])
    nt.links.new(sep.outputs["Y"], add.inputs[1])
    nt.links.new(add.outputs[0], div.inputs[0])
    nt.links.new(div.outputs[0], frac.inputs[0])
    nt.links.new(frac.outputs[0], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], nt.nodes["Principled BSDF"].inputs["Base Color"])
    return m


# The wood panelling round the bottom of every wall, its rail, and the
# skirting under it: what makes four painted walls a room somebody lives in.
WAINSCOT = 0.84


def wainscot(name: str, along: str, at: float, inward: int, a0: float, a1: float) -> None:
    """Panelling on one run of wall, `along` x (the back and front walls) or y
    (the side walls), whose face is at `at`, the room on its `inward` side,
    from a0 to a1: a backing board, raised panels, the rail on top and the
    skirting at the foot."""
    back = mat("wainscot", "#4A3424", 0.7)
    raised = mat("wainpanel", "#5A402C", 0.6)
    rail = mat("wainrail", "#6A4A32", 0.55)
    skirt = mat("skirting", "#3A281C", 0.6)
    length = a1 - a0

    def put(nm, depth, run, height, off, z, m, a=None):
        c = (a0 + a1) / 2 if a is None else a
        if along == "x":
            box(f"{name}-{nm}", (run, depth, height), (c, at + inward * off, z), m)
        else:
            box(f"{name}-{nm}", (depth, run, height), (at + inward * off, c, z), m)

    put("back", 0.018, length, WAINSCOT, 0.009, WAINSCOT / 2, back)
    put("rail", 0.045, length, 0.05, 0.0225, WAINSCOT, rail)
    put("skirt", 0.045, length, 0.14, 0.0225, 0.07, skirt)
    n = max(1, round(length / 0.72))
    pitch = length / n
    if pitch > 0.30:
        for k in range(n):
            put(f"panel{k}", 0.012, pitch - 0.12, WAINSCOT - 0.36, 0.024, 0.14 + (WAINSCOT - 0.14) / 2 + 0.01,
                raised, a=a0 + pitch * (k + 0.5))


def cornice(name: str, along: str, at: float, inward: int, a0: float, a1: float) -> None:
    """The moulding where a wall meets the ceiling, in two steps."""
    TRIM = mat("trim", "#C2C8D0", 0.6)
    for k, (depth, height, z) in enumerate(((0.07, 0.08, HEIGHT - 0.04), (0.035, 0.05, HEIGHT - 0.105))):
        if along == "x":
            box(f"{name}-cornice{k}", (a1 - a0, depth, height), ((a0 + a1) / 2, at + inward * depth / 2, z), TRIM)
        else:
            box(f"{name}-cornice{k}", (depth, a1 - a0, height), (at + inward * depth / 2, (a0 + a1) / 2, z), TRIM)


def build_room(season: str) -> None:
    scn = bpy.context.scene
    xmas = season == "christmas"

    WALL = wallpaper("wall", "#2C3752", "#33405F")
    SIDEWALL = wallpaper("wallSide", "#28324B", "#2E3A56")
    FLOOR = mat("floor", "#FFFFFF", 0.7, image="floor.png")
    WOOD = mat("deskwood", "#8A6240", 0.6)
    DARKMETAL = mat("darkmetal", "#20262F", 0.5, metal=0.4)
    PALE = mat("pale", "#D6DCE2", 0.6)

    # ---- the shell
    thing("floor", fixed=True)
    fl = plane("floor", (RIGHT - LEFT, BACK - FRONT), (0, (BACK + FRONT) / 2, 0), (0, 0, 0), FLOOR)
    fl.data.uv_layers.active.data.foreach_set(
        "uv", [c for v in ((0, 0), (3.2, 0), (3.2, 2.8), (0, 2.8)) for c in v])
    # the boards run on across the whole floor (a picture's default is to
    # stop at its edge, which left all but one corner of it bare)
    for nd in FLOOR.node_tree.nodes:
        if nd.type == "TEX_IMAGE":
            nd.extension = "REPEAT"
    thing("ceiling", fixed=True)
    plane("ceiling", (RIGHT - LEFT, BACK - FRONT), (0, (BACK + FRONT) / 2, HEIGHT),
          (math.radians(180), 0, 0), mat("ceil", "#30384A"))
    # the room's own light, off at this hour: a glass dome on a rose
    cyl("ceilingrose", 0.17, 0.03, (0.6, -0.6, HEIGHT - 0.015), mat("trim", "#C2C8D0", 0.6), verts=32)
    dome = sphere("ceilinglight", 0.24, (0.6, -0.6, HEIGHT - 0.03), mat("dome", "#D8D4C8", 0.4))
    dome.scale = (1, 1, 0.42)

    thing("backwall", fixed=True)
    wall = box("backwall", (RIGHT - LEFT, 0.12, HEIGHT), (0, BACK + 0.06, HEIGHT / 2), WALL)
    x0, x1, z0, z1 = WINDOW
    bpy.ops.mesh.primitive_cube_add(size=1, location=((x0 + x1) / 2, BACK + 0.06, (z0 + z1) / 2))
    cut = bpy.context.object
    cut.scale = (x1 - x0, 0.6, z1 - z0)
    mod = wall.modifiers.new("window", "BOOLEAN")
    mod.operation, mod.object = "DIFFERENCE", cut
    bpy.context.view_layer.objects.active = wall
    bpy.ops.object.modifier_apply(modifier="window")
    bpy.data.objects.remove(cut)
    wainscot("back", "x", BACK, -1, LEFT, RIGHT)
    cornice("back", "x", BACK, -1, LEFT, RIGHT)

    thing("leftwall", fixed=True)
    lw = box("leftwall", (0.12, BACK - FRONT, HEIGHT), (LEFT - 0.06, (BACK + FRONT) / 2, HEIGHT / 2), SIDEWALL)
    dy0, dy1, dh = DOOR
    bpy.ops.mesh.primitive_cube_add(size=1, location=(LEFT - 0.06, (dy0 + dy1) / 2, dh / 2))
    cut = bpy.context.object
    cut.scale = (0.6, dy1 - dy0, dh)
    mod = lw.modifiers.new("door", "BOOLEAN")
    mod.operation, mod.object = "DIFFERENCE", cut
    bpy.context.view_layer.objects.active = lw
    bpy.ops.object.modifier_apply(modifier="door")
    bpy.data.objects.remove(cut)
    # round the door, clear of its casing
    wainscot("left-a", "y", LEFT, 1, FRONT, dy0 - 0.08)
    wainscot("left-b", "y", LEFT, 1, dy1 + 0.08, BACK)
    cornice("left", "y", LEFT, 1, FRONT, BACK)
    box("switch", (0.012, 0.08, 0.12), (LEFT + 0.006, dy1 + 0.22, 1.18), PALE)

    thing("rightwall", fixed=True)
    box("rightwall", (0.12, BACK - FRONT, HEIGHT), (RIGHT + 0.06, (BACK + FRONT) / 2, HEIGHT / 2), SIDEWALL)
    wainscot("right", "y", RIGHT, -1, FRONT, BACK)
    cornice("right", "y", RIGHT, -1, FRONT, BACK)
    thing("frontwall", fixed=True)
    box("frontwall", (RIGHT - LEFT, 0.12, HEIGHT), (0, FRONT - 0.06, HEIGHT / 2), SIDEWALL)
    wainscot("front", "x", FRONT, 1, LEFT, RIGHT)
    cornice("front", "x", FRONT, 1, LEFT, RIGHT)

    # ---- the window: frame, bars, sill, curtains, the radiator under it
    thing("window", fixed=True)
    FRAME = mat("frame", "#D8DEE4", 0.55)
    t = 0.07
    for nm, sz, lc in (
            ("wl", (t, 0.14, z1 - z0), (x0 + t / 2, BACK, (z0 + z1) / 2)),
            ("wr", (t, 0.14, z1 - z0), (x1 - t / 2, BACK, (z0 + z1) / 2)),
            ("wt", (x1 - x0, 0.14, t), ((x0 + x1) / 2, BACK, z1 - t / 2)),
            ("wb", (x1 - x0, 0.14, t), ((x0 + x1) / 2, BACK, z0 + t / 2)),
            ("wv", (0.045, 0.09, z1 - z0), ((x0 + x1) / 2, BACK, (z0 + z1) / 2)),
            ("wh", (x1 - x0, 0.09, 0.045), ((x0 + x1) / 2, BACK, (z0 + z1) / 2 + 0.12))):
        box(nm, sz, lc, FRAME)
    box("sill", (x1 - x0 + 0.24, 0.24, 0.05), ((x0 + x1) / 2, BACK - 0.09, z0 - 0.025), FRAME)
    # The view: one see-through pane a sky, stacked a centimetre apart in
    # front of a black backing, each lit and seen in its own light group,
    # so a state shows one of them (`states`). The mask pass sees the first
    # pane as "the outside", where the weather is drawn.
    for k, (group, picture) in enumerate(SKIES[season].items()):
        plane(f"outside-{group}", (3.4, 2.9), ((x0 + x1) / 2, BACK + 1.2 + 0.01 * k, (z0 + z1) / 2 + 0.15),
              (math.radians(90), 0, 0), sky_mat(picture), group=group)
    plane("outside-back", (3.6, 3.1), ((x0 + x1) / 2, BACK + 1.3, (z0 + z1) / 2 + 0.15),
          (math.radians(90), 0, 0), mat("outside-back", "#000000", 1.0))
    CURTAIN = mat("curtain", "#3E4E78", 0.95)
    pleats("curtain-l", x0 - 0.42, x0 + 0.06, BACK - 0.10, 0.30, z1 + 0.20, 5, 0.07, CURTAIN)
    pleats("curtain-r", x1 - 0.06, x1 + 0.42, BACK - 0.10, 0.30, z1 + 0.20, 5, 0.07, CURTAIN)
    cyl("rod", 0.016, x1 - x0 + 1.1, ((x0 + x1) / 2, BACK - 0.11, z1 + 0.24), DARKMETAL,
        rot=(0, math.radians(90), 0))
    RAD = mat("radiator", "#C8CED6", 0.5)
    for k in range(14):
        box(f"fin{k}", (0.05, 0.08, 0.56), (x0 + 0.22 + k * 0.085, BACK - 0.07, 0.46), RAD)
    box("radpipe", (0.02, 0.02, 0.2), (x0 + 0.14, BACK - 0.07, 0.12), RAD)

    # ---- the whiteboard: frame, tray, markers, the cards held on by magnets
    thing("whiteboard", fixed=True)
    bx0, bx1, bz0, bz1 = BOARD
    WB = mat("board", "#EEF1F2", 0.3, image="whiteboard.png")
    AL = mat("alu", "#AAB4BF", 0.35, metal=0.6)
    plane("boardface", (bx1 - bx0, bz1 - bz0), ((bx0 + bx1) / 2, BACK - 0.025, (bz0 + bz1) / 2),
          (math.radians(90), 0, 0), WB)
    for nm, sz, lc in (
            ("bl", (0.04, 0.05, bz1 - bz0 + 0.08), (bx0 - 0.02, BACK - 0.025, (bz0 + bz1) / 2)),
            ("br", (0.04, 0.05, bz1 - bz0 + 0.08), (bx1 + 0.02, BACK - 0.025, (bz0 + bz1) / 2)),
            ("bt", (bx1 - bx0 + 0.08, 0.05, 0.04), ((bx0 + bx1) / 2, BACK - 0.025, bz1 + 0.02)),
            ("bb", (bx1 - bx0 + 0.08, 0.05, 0.04), ((bx0 + bx1) / 2, BACK - 0.025, bz0 - 0.02)),
            ("tray", (bx1 - bx0 - 0.3, 0.10, 0.025), ((bx0 + bx1) / 2, BACK - 0.075, bz0 - 0.055))):
        box(nm, sz, lc, AL)
    for i, c in enumerate(("#283C9A", "#C4302A", "#1E2026", "#1E7A46")):
        cyl(f"marker{i}", 0.012, 0.14, (bx0 + 0.45 + i * 0.16, BACK - 0.08, bz0 - 0.03),
            mat(f"marker{i}", c, 0.5), rot=(0, math.radians(90), 0))
    box("eraser", (0.15, 0.055, 0.04), (bx1 - 0.55, BACK - 0.08, bz0 - 0.02), mat("eraser", "#3A3F48"))
    PAPER = "#F4F2EA"
    cards = [((bx0 + 0.20, bz1 - 0.18), 4, 0), ((bx0 + 0.20, bz1 - 0.48), -3, 1),
             ((bx0 + 0.21, bz1 - 0.78), 2, 2)]
    for (cx, cz), tilt, k in cards:
        lettered(plane(f"card{k}", (0.24, 0.16), (cx, BACK - 0.03, cz),
                       (math.radians(90), math.radians(tilt), 0),
                       mat(f"card{k}", PAPER, image=f"card{k}.png")), "card", CARD_PAPERS[k])
        cyl(f"magnet{k}", 0.014, 0.012, (cx, BACK - 0.037, cz + 0.06),
            mat("magnet", "#C4302A", 0.4), rot=(math.radians(90), 0, 0))

    # ---- the slate: where a chapter's title is chalked
    thing("slate", fixed=True)
    sx0, sx1, sz0, sz1 = SLATE
    plane("slateface", (sx1 - sx0, sz1 - sz0), ((sx0 + sx1) / 2, BACK - 0.03, (sz0 + sz1) / 2),
          (math.radians(90), 0, 0), mat("slate", "#222C2E", 0.95, image="chalkboard.png"))
    SW = mat("slatewood", "#6E4A30", 0.7)
    for nm, sz, lc in (
            ("sl", (0.05, 0.05, sz1 - sz0 + 0.10), (sx0 - 0.025, BACK - 0.03, (sz0 + sz1) / 2)),
            ("sr", (0.05, 0.05, sz1 - sz0 + 0.10), (sx1 + 0.025, BACK - 0.03, (sz0 + sz1) / 2)),
            ("st", (sx1 - sx0 + 0.10, 0.05, 0.05), ((sx0 + sx1) / 2, BACK - 0.03, sz1 + 0.025)),
            ("sb", (sx1 - sx0 + 0.10, 0.05, 0.05), ((sx0 + sx1) / 2, BACK - 0.03, sz0 - 0.025)),
            ("ledge", (sx1 - sx0, 0.07, 0.02), ((sx0 + sx1) / 2, BACK - 0.06, sz0 - 0.05))):
        box(nm, sz, lc, SW)
    for k, dx in enumerate((0.18, 0.27)):
        cyl(f"chalk{k}", 0.008, 0.07, (sx0 + dx, BACK - 0.065, sz0 - 0.032), PALE,
            rot=(0, math.radians(90), math.radians(8 * k)))

    # ---- the wall clock, at three in the morning: its hands are the bot's
    # (the clock jump between scenes), so the face is rendered without them
    thing("clock", fixed=True)
    cyl("clockrim", 0.19, 0.05, (-1.25, BACK - 0.03, 2.42), mat("rim", "#1C2230"),
        rot=(math.radians(90), 0, 0), verts=40)
    bpy.ops.mesh.primitive_circle_add(radius=0.165, fill_type="NGON", vertices=40,
                                      location=(-1.25, BACK - 0.058, 2.42), rotation=(math.radians(90), 0, 0))
    face = bpy.context.object
    face.name = "clockface"
    face.data.materials.append(mat("clockface", "#E8E6DE", image="clock_face.png"))
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.uv.cube_project(cube_size=0.33)
    bpy.ops.object.mode_set(mode="OBJECT")
    own(face)
    lettered(face, "clock", half=(0.165, 0.165))

    # ---- the low cabinet under the slate, and what sits on it
    thing("credenza")
    cx0, cx1, cd, ch = SLATE[0] - 0.05, SLATE[1] + 0.05, 0.44, 0.74
    box("credenza", (cx1 - cx0, cd, ch), ((cx0 + cx1) / 2, BACK - cd / 2, ch / 2), WOOD)
    for k in range(2):
        w = (cx1 - cx0) / 2 - 0.04
        box(f"cdoor{k}", (w, 0.012, ch - 0.12), (cx0 + 0.03 + w / 2 + k * (w + 0.02), BACK - cd - 0.006, ch / 2 + 0.02),
            mat("cdoor", "#7A5434", 0.65))
        box(f"cknob{k}", (0.02, 0.025, 0.06), ((cx0 + cx1) / 2 + (-0.05 if k == 0 else 0.05), BACK - cd - 0.02, ch / 2 + 0.05),
            DARKMETAL)
    kenney("books", (cx0 + 0.22, BACK - 0.22, ch), rot=180, scale=2.0)
    # the disclaimer he has to say in every video, stitched, framed, and
    # propped on the cabinet where every wide shot catches it
    thing("crossstitch")
    tilt = math.radians(82)
    box("csframe", (0.36, 0.025, 0.36), (cx0 + 0.62, BACK - 0.07, ch + 0.18), mat("csframe", "#7A5638", 0.6),
        rot=(tilt - math.radians(90), 0, 0))
    lettered(plane("cs", (0.30, 0.30), (cx0 + 0.62, BACK - 0.084, ch + 0.18), (tilt, 0, 0),
                   mat("cs", "#ECE6D6", image="cross_stitch.png")), "stitch")
    thing("credenza")
    # 3am: the coffee machine, and the mug that never goes back to the kitchen
    kenney("kitchenCoffeeMachine", (cx1 - 0.20, BACK - 0.22, ch), rot=0, scale=1.6,
           recolor={"metalDark": "#1E2228", "metal": "#8A949E"})
    mug("mug-credenza", (cx1 - 0.44, BACK - 0.16, ch), "#E8E4DA", turn=200)
    if not xmas:
        kenney("plantSmall2", ((cx0 + cx1) / 2 + 0.28, BACK - 0.2, ch), scale=2.0)

    # ---- the desk: a standing desk, its front panel hiding his legs
    thing("desk")
    dx, dy, dw, dd, dz = DESK
    box("desktop", (dw, dd, 0.04), (dx, dy, dz - 0.02), WOOD)
    for s in (-1, 1):
        lx = dx + s * (dw / 2 - 0.12)
        box(f"leg{s}", (0.07, 0.07, dz - 0.06), (lx, dy, (dz - 0.06) / 2), DARKMETAL)
        box(f"foot{s}", (0.07, dd - 0.06, 0.04), (lx, dy, 0.02), DARKMETAL)
    box("crossbar", (dw - 0.3, 0.05, 0.06), (dx, dy, dz - 0.09), DARKMETAL)
    box("modesty", (dw - 0.2, 0.015, 0.62), (dx, dy - dd / 2 + 0.06, dz - 0.40), DARKMETAL)

    thing("desk-things")
    dark = {k: "#2A303A" for k in KENNEY}
    kenney("computerKeyboard", (dx - 0.10, dy + 0.18, dz), rot=0, scale=2.0, recolor=dark)
    kenney("computerMouse", (dx + 0.28, dy + 0.20, dz), rot=0, scale=2.0, recolor=dark)
    MUG = mat("mug", "#C24A38", 0.5)
    cyl("mug", 0.045, 0.10, (dx - 0.52, dy + 0.12, dz + 0.05), MUG)
    bpy.ops.mesh.primitive_torus_add(major_radius=0.03, minor_radius=0.009,
                                     location=(dx - 0.47, dy + 0.12, dz + 0.055), rotation=(math.radians(90), 0, 0))
    bpy.context.object.data.materials.append(MUG)
    own(bpy.context.object)
    SHEET = mat("sheet", "#D9DDE0", image="sheet.png")
    for i, (ox, oy, r) in enumerate(((0.0, 0.0, 8), (0.02, 0.01, -4), (-0.01, -0.01, 15))):
        box(f"sheet{i}", (0.21, 0.297, 0.003), (dx + 0.36 + ox, dy - 0.14 + oy, dz + 0.002 + i * 0.004),
            SHEET, rot=(0, 0, math.radians(r)))
    lettered(plane("filing", (0.21, 0.297), (dx + 0.35, dy - 0.15, dz + 0.016), (0, 0, math.radians(12)),
                   mat("filing", "#E6E4DC", image="filing.png")), "report")
    box("phone", (0.075, 0.15, 0.009), (dx - 0.30, dy - 0.20, dz + 0.005), mat("phone", "#15181E", 0.3),
        rot=(0, 0, math.radians(-20)))
    # its glass, face up: dark, and lit by the bot with Kev's message in the
    # videos his tip runs in (pick 7)
    lettered(plane("phonescreen", (0.066, 0.132), (dx - 0.30, dy - 0.20, dz + 0.0101), (0, 0, math.radians(-20)),
                   mat("phonescreen", "#101218", 0.65, image="phone.png")), "phone")
    # the night so far: a second mug, two cans
    mug("mug-desk2", (dx - 0.36, dy + 0.30, dz), "#3E5C8A", turn=30)
    CAN = mat("can", "#B4BCC6", 0.3, metal=0.8)
    for k, (ox, oy) in enumerate(((-0.16, 0.32), (-0.08, 0.36))):
        cyl(f"can{k}", 0.033, 0.122, (dx + ox, dy + oy, dz + 0.061), CAN)
        cyl(f"canband{k}", 0.0335, 0.05, (dx + ox, dy + oy, dz + 0.07), mat("canband", "#2E9AA0", 0.4))
    # the adding machine, its paper tape run over the edge of the desk and on
    # to the floor: the arithmetic, done by hand, at length
    ax, ay = dx + 0.04, dy - 0.20
    box("adder", (0.20, 0.24, 0.06), (ax, ay, dz + 0.03), mat("adder", "#3A3F48", 0.5))
    box("adderkeys", (0.16, 0.13, 0.015), (ax, ay - 0.04, dz + 0.065), mat("adderkeys", "#C9CED4", 0.5),
        rot=(math.radians(-8), 0, 0))
    cyl("adderroll", 0.03, 0.07, (ax, ay + 0.10, dz + 0.09), mat("tape", "#F2F0E8", 0.8),
        rot=(0, math.radians(90), 0))
    front = dy - dd / 2
    path = [(ax, ay + 0.10, dz + 0.12), (ax, ay + 0.03, dz + 0.075), (ax, ay - 0.10, dz + 0.072),
            (ax, front + 0.05, dz + 0.003), (ax + 0.005, front - 0.004, dz - 0.004),
            (ax + 0.01, front - 0.016, dz - 0.07), (ax + 0.015, front - 0.02, dz - 0.24),
            (ax + 0.02, front - 0.05, dz - 0.33), (ax + 0.025, front - 0.09, dz - 0.31),
            (ax + 0.02, front - 0.10, dz - 0.26), (ax + 0.015, front - 0.07, dz - 0.24)]
    ribbon("tapeoff", path, 0.057, mat("tape", "#F2F0E8", 0.8))
    for k, (c, ox) in enumerate((("#F2E04C", 0.0), ("#F07AA8", 0.03))):
        cyl(f"hi{k}", 0.008, 0.12, (dx + 0.22 + ox, dy - 0.30, dz + 0.008), mat(f"hi{k}", c, 0.4),
            rot=(0, math.radians(90), math.radians(70)))
    paper_stack("deskstack", (dx + 0.66, dy - 0.16, dz), 0.11, "form10q.png", turn=-6)
    lettered(bpy.data.objects["deskstack-top"], "cover")
    box("notepad", (0.15, 0.21, 0.012), (dx - 0.60, dy - 0.16, dz + 0.006), mat("notepad", "#F2D45C", 0.8),
        rot=(0, 0, math.radians(6)))
    cyl("pen", 0.006, 0.14, (dx - 0.58, dy - 0.15, dz + 0.016), mat("pen", "#283C9A", 0.4),
        rot=(0, math.radians(90), math.radians(30)))

    # the screen, turned to face where he stands: it is his key light. Built
    # here, not Kenney's, so the glass the bot writes on IS the screen: a
    # 16:9 pane flush in a thin bezel, leaned back a little, its picture
    # edge to edge, and nothing of it a sheet floating in front of a bigger
    # dark screen (which is how a chapter's plate on it read before).
    thing("monitor")
    r, t = math.radians(SCREEN_ROT), math.radians(MONITOR_TILT)
    facing = Vector((math.sin(r), -math.cos(r), 0))
    right = Vector((math.cos(r), math.sin(r), 0))
    up = Vector((0, 0, 1))
    n = facing * math.cos(t) + up * math.sin(t)          # out of the glass
    gup = up * math.cos(t) - facing * math.sin(t)        # up the glass
    turn = Matrix((right, gup, n)).transposed().to_euler()
    gw, gh = MONITOR_GLASS
    side, top, chin, deep = 0.018, 0.018, 0.05, 0.035
    cx, cy = dx + 0.48, dy + 0.08
    gc = Vector((cx, cy, dz + 0.10 + chin + gh / 2))     # the glass's centre
    HOUSING = mat("monitorbody", "#262C36", 0.45)
    box("monitor-housing", (gw + 2 * side, gh + top + chin, deep),
        gc + gup * ((top - chin) / 2) - n * (deep / 2), HOUSING, rot=turn)
    box("monitor-back", (gw * 0.55, gh * 0.55, 0.03), gc - n * (deep + 0.015), HOUSING, rot=turn)
    box("monitor-neck", (0.07, 0.035, gc.z - dz - 0.04),
        Vector((cx, cy, (gc.z + dz - 0.04) / 2)) - facing * (deep + 0.035), HOUSING, rot=(0, 0, r))
    box("monitor-foot", (0.30, 0.20, 0.014), Vector((cx, cy, dz + 0.007)) - facing * 0.05, HOUSING,
        rot=(0, 0, r))
    scr = plane("screenface", (gw, gh), gc + n * 0.0015, turn, screen_mat(), group="screen")
    # the notes are stuck to the frame where they half cover the corner of
    # the picture, the way notes on a screen are; not on the picture itself
    for k, (u, v, roll) in enumerate(((0.02, 0.97, 6), (1.012, 0.24, -8), (0.13, -0.11, 4))):
        p = gc + right * ((u - 0.5) * gw) + gup * ((v - 0.5) * gh) + n * 0.004
        lettered(plane(f"note{k}", (0.075, 0.075), p, (Matrix((right, gup, n)).transposed()
                                                        @ Matrix.Rotation(math.radians(roll), 3, "Z")).to_euler(),
                       mat(f"note{k}", "#F2D45C", 0.9, image=f"note{k}.png")), "note", NOTE_PAPERS[k])

    # the desk lamp: the warm fill
    thing("lamp")
    lmn, lmx = kenney("lampRoundTable", (dx - 0.70, dy - 0.06, dz), rot=200, scale=1.5,
                      recolor={"lamp": "#F0B460"})
    LAMPSHADE = mat("lampglow", "#F0B460", emit="#F0B460", strength=5.0)
    for o in THINGS["lamp"]["objects"]:
        for s in o.material_slots:
            if s.material and s.material.name.startswith("k_metalLight"):
                s.material = LAMPSHADE
        o.lightgroup = "lamp"
    lamp_at = Vector(((lmn.x + lmx.x) / 2, (lmn.y + lmx.y) / 2, lmx.z - 0.08))

    # ---- the rest of the room
    thing("filing-cabinet")
    FC = mat("cabinet", "#55657C", 0.5, metal=0.3)
    fx, fy = 2.92, 1.66
    box("cabinet", (0.44, 0.56, 0.72), (fx, fy, 0.36), FC)
    for k in range(2):
        box(f"drawer{k}", (0.40, 0.012, 0.30), (fx, fy - 0.286, 0.18 + k * 0.35), mat("drawer", "#61728A", 0.5, metal=0.3))
        box(f"handle{k}", (0.14, 0.02, 0.02), (fx, fy - 0.30, 0.27 + k * 0.35), DARKMETAL)
        box(f"label{k}", (0.08, 0.005, 0.04), (fx, fy - 0.294, 0.31 + k * 0.35), PALE)
    if xmas:
        cone("minitree", 0.12, 0.34, (fx, fy, 0.72 + 0.17), mat("tree", "#2E6A48"))
    else:
        dead_screen("oldscreen0", (fx, fy - 0.02, 0.72), rot=-12)

    thing("bookcase")
    bmn, bmx = kenney("bookcaseOpen", (RIGHT - 0.22, 0.10, 0), rot=-90, scale=2.1)
    BINDER = ("#20242C", "#2E4A8A", "#8A2E2A", "#3E4450", "#2E6A48", "#20242C")
    for k, z in enumerate((0.05, 0.50, 0.95, 1.40)):
        if k in (1, 2):
            # binders, not books: the filings, kept
            for j in range(6):
                by = bmn.y + 0.10 + j * 0.075
                box(f"binder{k}{j}", (0.28, 0.065, 0.31), (RIGHT - 0.24, by, bmn.z + z + 0.04 + 0.155),
                    mat(f"binder{j}", BINDER[j], 0.6))
                lettered(plane(f"spine{k}{j}", (0.055, 0.30), (RIGHT - 0.24 - 0.141, by, bmn.z + z + 0.04 + 0.155),
                               (math.radians(90), 0, math.radians(-90)), mat("spine", "#ECECE8", image="binder.png")),
                         "spine")
            kenney("books", (RIGHT - 0.22, bmn.y + 0.25 + 0.42, bmn.z + z + 0.04), rot=-84, scale=2.0)
            continue
        for j in range(2):
            if k == 3 and j == 1:
                # Mum's jar (pick 3), where the books were: the one shelf at
                # eye height, at the window end, where the shelf's upright
                # does not hide it from the desk's wide and the window's
                jar("jar", (RIGHT - 0.35, bmn.y + 0.63, bmn.z + z + 0.04), facing=-149)
                continue
            kenney("books", (RIGHT - 0.22, bmn.y + 0.25 + j * 0.42, bmn.z + z + 0.04), rot=-90 + j * 6, scale=2.0)
    # on top: a plant that gets the lamp, and the books that did not fit
    kenney("pottedPlant", (RIGHT - 0.24, bmn.y + 0.24, bmx.z), rot=20, scale=1.0,
           recolor={"plant": "#3F6E4E"})
    kenney("books", (RIGHT - 0.22, bmn.y + 0.70, bmx.z), rot=-90, scale=2.0)

    thing("bin")
    tmn, tmx = kenney("trashcan", (2.95, 0.72, 0), scale=1.2)
    for k, (ox, oy) in enumerate(((0.0, 0.02), (0.05, -0.03), (-0.04, -0.02))):
        bpy.ops.mesh.primitive_ico_sphere_add(radius=0.04, subdivisions=1,
                                              location=(2.95 + ox, 0.72 + oy, tmx.z + 0.02))
        bpy.context.object.data.materials.append(mat("paperball", "#E4E6E8"))
        own(bpy.context.object)

    thing("rug", fixed=True)      # the floor's: he stands on it, never behind it
    rx, ry, rw, rd = RUG
    box("rugbase", (rw, rd, 0.008), (rx, ry, 0.004), mat("rugbase", "#2C3450", 0.95))
    plane("rug", (rw, rd), (rx, ry, 0.0085), (0, 0, 0), mat("rug", "#FFFFFF", 0.95, image="rug.png"))

    thing("plant")
    if not xmas:
        kenney("pottedPlant", (-2.95, 1.70, 0), rot=30, scale=2.4, recolor={"plant": "#3F6E4E"})
        # its name tag (pick 2): renamed by the bot after the latest company
        # he was wrong about. In December the tree's pot has it.
        plant_tag((-2.80, 1.56, 0.52), facing=27)

    thing("floorlamp")
    fmn, fmx = kenney("lampRoundFloor", (2.88, -1.25, 0), scale=2.2)
    floorlamp_at = Vector(((fmn.x + fmx.x) / 2, (fmn.y + fmx.y) / 2, fmx.z - 0.10))
    for o in THINGS["floorlamp"]["objects"]:
        for s in o.material_slots:
            if s.material and s.material.name.startswith("k_metalLight"):
                s.material = mat("floorglow", "#F0C890", emit="#F0C890", strength=3.0)

    # No chair: it is a standing desk, and every place a chair could stand
    # near it is a place he stands in some angle.

    # ---- the paper on the floor in front of him, one angle's at a time
    for angle, piles in FLOOR_PILES.items():
        thing(f"floorpile-{angle}")
        for k, (at, turn, height) in enumerate(piles):
            floor_pile(f"floorpile-{angle}{k}", at, turn, height, seed=11 * len(angle) + k)
        for o in THINGS[f"floorpile-{angle}"]["objects"]:
            o.hide_render = True

    # ---- the door, closed, in the left wall
    thing("door", fixed=True)
    DOORM = mat("door", "#3E4C66", 0.7)
    CASE = mat("casing", "#D0D6DC", 0.6)
    yc = (dy0 + dy1) / 2
    box("doorslab", (0.045, dy1 - dy0 - 0.02, dh - 0.01), (LEFT - 0.02, yc, dh / 2), DOORM)
    for k, (zz, hh) in enumerate(((0.55, 0.70), (1.45, 0.80))):
        box(f"panel{k}", (0.012, dy1 - dy0 - 0.26, hh), (LEFT + 0.008, yc, zz), mat("doorpanel", "#46556F", 0.7))
    cyl("knob", 0.03, 0.05, (LEFT + 0.03, dy1 - 0.12, 1.02), AL, rot=(0, math.radians(90), 0))
    box("lever", (0.02, 0.10, 0.018), (LEFT + 0.06, dy1 - 0.16, 1.02), AL)
    for nm, sz, lc in (("cl", (0.03, 0.08, dh + 0.06), (LEFT + 0.015, dy0 - 0.04, (dh + 0.06) / 2)),
                       ("cr", (0.03, 0.08, dh + 0.06), (LEFT + 0.015, dy1 + 0.04, (dh + 0.06) / 2)),
                       ("ct", (0.03, dy1 - dy0 + 0.16, 0.08), (LEFT + 0.015, yc, dh + 0.04))):
        box(nm, sz, lc, CASE)
    thing("coatrack")
    kenney("coatRackStanding", (LEFT + 0.32, dy0 - 0.55, 0), scale=2.2)

    thing("certificate", fixed=True)
    box("certframe", (0.03, 0.78, 0.58), (LEFT + 0.015, 1.06, 1.62), mat("certframe", "#2A2018", 0.6))
    plane("cert", (0.70, 0.50), (LEFT + 0.032, 1.06, 1.62), (math.radians(90), 0, math.radians(90)),
          mat("cert", "#E2DCC4", image="certificate.png"))
    # his 2022 post about the loss, printed and framed beside the margin call
    # (pick 4): a forum post drawn generic, an upvote arrow and 11k
    thing("losspost", fixed=True)
    box("lpframe", (0.03, 0.32, 0.42), (LEFT + 0.015, 0.48, 1.56), mat("certframe", "#2A2018", 0.6))
    plane("lp", (0.28, 0.38), (LEFT + 0.032, 0.48, 1.56), (math.radians(90), 0, math.radians(90)),
          mat("lp", "#F2F0EA", image="loss_post.png"))
    # the margin call that ended the trading years, framed like a diploma
    thing("margincall", fixed=True)
    box("mcframe", (0.03, 0.46, 0.60), (LEFT + 0.015, 0.06, 1.56), mat("certframe", "#2A2018", 0.6))
    plane("mc", (0.40, 0.52), (LEFT + 0.032, 0.06, 1.56), (math.radians(90), 0, math.radians(90)),
          mat("mc", "#F2F0E8", image="margin_call.png"))

    # ---- the box of old filings, lid on, by the board, the latest on top
    thing("filings")
    kmn, kmx = kenney("cardboardBoxClosed", (-1.20, 1.72, 0), rot=4, scale=1.6)
    lettered(plane("boxlabel", (min(0.34, kmx.x - kmn.x - 0.06), 0.16),
                   ((kmn.x + kmx.x) / 2, kmn.y - 0.004, kmx.z * 0.55),
                   (math.radians(90), 0, 0), mat("boxlabel", "#B08C60", image="boxlabel.png")), "box")
    paper_stack("boxstack", ((kmn.x + kmx.x) / 2, (kmn.y + kmx.y) / 2, kmx.z), 0.06, "proxy.png", turn=-8, tabs=3)
    lettered(bpy.data.objects["boxstack-top"], "cover")

    # ---- the print over the sofa
    thing("longrun", fixed=True)
    box("lrframe", (0.03, 1.06, 0.74), (LEFT + 0.015, -2.70, 1.62), mat("certframe", "#2A2018", 0.6))
    plane("lr", (0.96, 0.64), (LEFT + 0.032, -2.70, 1.62), (math.radians(90), 0, math.radians(90)),
          mat("lr", "#ECE4D0", image="long_run.png"))

    # ---- the sofa by the door, where the night ends
    thing("sofa")
    omn, omx = kenney("loungeSofa", (LEFT + 0.48, -2.70, 0), rot=90, scale=1.8,
                      recolor={"carpet": "#5A5048", "carpetDarker": "#4A4038", "wood": "#4A3426"})
    seat = omn.z + (omx.z - omn.z) * 0.48
    # where he sleeps (pick 6): a pillow off a bed at the arm, and the
    # blanket thrown back, half of it down the front to the floor
    pillow = box("bedpillow", (0.46, 0.32, 0.12), ((omn.x + omx.x) / 2 + 0.04, omn.y + 0.40, seat + 0.07),
                 mat("bedpillow", "#D6DAE2", 0.9), rot=(math.radians(-6), 0, math.radians(7)))
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    bev = pillow.modifiers.new("soft", "BEVEL")
    bev.width, bev.segments, bev.affect = 0.045, 5, "EDGES"
    blanket("blanket", omx.x - 0.02, omn.y + 0.62, omx.y - 0.22, seat, mat("blanket", "#46546E", 0.95,
                                                                           image="blanket.png"))

    # ---- December: a tree in the corner, lights on the window and the board,
    # a wreath on the door. Three strings of bulbs, each its own light group,
    # so the twinkle is three states of one render.
    if xmas:
        thing("tree", season="christmas")
        TREE = mat("tree", "#2E6A48", 0.9)
        tx, ty = -2.85, 1.55
        cyl("trunk", 0.05, 0.25, (tx, ty, 0.125), mat("trunk", "#4A3426"))
        cyl("pot", 0.17, 0.26, (tx, ty, 0.13), mat("pot", "#8A2E2A", 0.6))
        plant_tag((tx + 0.07, ty - 0.12, 0.25), facing=27)
        for k, (r, z, hgt) in enumerate(((0.55, 0.55, 0.70), (0.44, 0.95, 0.62), (0.32, 1.32, 0.52), (0.19, 1.62, 0.40))):
            cone(f"tier{k}", r, hgt, (tx, ty, z), TREE)
        star = mat("star", "#F0D060", emit="#F0D060", strength=6.0)
        sphere("star", 0.06, (tx, ty, 1.86), star, group="xmasA")
        gift = mat("gift", "#C4302A", 0.6)
        box("gift0", (0.28, 0.24, 0.20), (tx + 0.42, ty - 0.18, 0.10), gift)
        box("gift1", (0.22, 0.22, 0.16), (tx + 0.18, ty - 0.45, 0.08), mat("gift1", "#2E6AA8", 0.6))
        inks = {"xmasA": "#F07A5A", "xmasB": "#F0D060", "xmasC": "#7FD4E8"}
        bulbs = []
        for k in range(26):
            a = k * 2.4
            z = 0.32 + k * 0.052
            r = 0.55 * (1 - (z - 0.2) / 1.75) + 0.02
            bulbs.append((tx + r * math.cos(a), ty + r * math.sin(a), z))
        for k in range(14):  # along the curtain rod
            bulbs.append((WINDOW[0] - 0.45 + k * (WINDOW[1] - WINDOW[0] + 0.9) / 13, BACK - 0.14,
                          WINDOW[3] + 0.20 - 0.05 * math.sin(k * math.pi / 13 * 4)))
        for k in range(12):  # along the top of the board
            bulbs.append((BOARD[0] + k * (BOARD[1] - BOARD[0]) / 11, BACK - 0.06,
                          BOARD[3] + 0.06 - 0.04 * math.sin(k * math.pi / 11 * 4)))
        groups = ("xmasA", "xmasB", "xmasC")
        for k, p in enumerate(bulbs):
            g = groups[k % 3]
            sphere(f"bulb{k}", 0.022, p, mat(f"bulb-{g}", inks[g], emit=inks[g], strength=9.0), group=g)
        thing("wreath", season="christmas")
        bpy.ops.mesh.primitive_torus_add(major_radius=0.20, minor_radius=0.06,
                                         location=(LEFT + 0.07, yc, 1.62), rotation=(0, math.radians(90), 0))
        bpy.context.object.data.materials.append(TREE)
        own(bpy.context.object)
        box("bow", (0.03, 0.12, 0.08), (LEFT + 0.12, yc, 1.44), gift)

    # ---- light, the kit's model: the monitor is the key, the lamp the fill,
    # a dark blue room, the moon through the window
    world = bpy.data.worlds.new("w")
    scn.world = world
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = lin("#141824")
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 1.2
    world.lightgroup = "room"

    def light(name, kind, loc, color, energy, group, rot=(0, 0, 0), size=None, spot=None):
        d = bpy.data.lights.new(name, kind)
        d.color = lin(color)[:3]
        d.energy = energy
        if size and kind == "AREA":
            d.shape = "RECTANGLE"
            d.size, d.size_y = size
        if kind in ("POINT", "SPOT"):
            d.shadow_soft_size = 0.06
        if spot:
            d.spot_size = math.radians(spot)
            d.spot_blend = 0.6
        o = bpy.data.objects.new(name, d)
        o.location = loc
        o.rotation_euler = rot
        o.lightgroup = group
        scn.collection.objects.link(o)
        return o

    light("lampbulb", "POINT", lamp_at, "#F0B460", 22, "lamp")
    light("lamppool", "SPOT", lamp_at, "#F0B460", 160, "lamp",
          rot=(math.radians(25), 0, math.radians(200)), spot=100)
    # an area light shines down its own -Z: point that out of the screen
    glow = light("screenglow", "AREA", scr.location + n * 0.12, "#7FD4E8", 70, "screen",
                 size=(0.6, 0.36))
    glow.rotation_euler = n.to_track_quat("-Z", "Z").to_euler()
    # what each sky throws in through the glass: the moon's light at night
    for group, picture in SKIES[season].items():
        colour, power = SKY_LIGHT[picture]
        light(f"skylight-{group}", "AREA", ((x0 + x1) / 2, BACK + 0.35, 2.05), colour, power, group,
              rot=(math.radians(-68), 0, 0), size=(1.5, 1.2))
    # the laundromat across the road that never closes (pick 8): warm, from
    # the street below, up through the window on to the curtains and ceiling
    light("laundromat", "AREA", ((x0 + x1) / 2, BACK + 0.7, 0.6), "#F2B06A", 400, "laundromat",
          rot=(math.radians(-132), 0, 0), size=(1.6, 0.5))
    light("floorbulb", "POINT", floorlamp_at, "#F0C890", 45, "room")
    light("fill", "AREA", (0.0, -2.8, 2.65), "#8DA0C8", 520, "room",
          rot=(math.radians(58), 0, 0), size=(5.0, 2.0))
    light("shelf", "AREA", (2.4, 0.4, 2.5), "#F0C890", 60, "room",
          rot=(math.radians(35), 0, math.radians(30)), size=(0.8, 0.8))
    light("rim", "AREA", (-2.5, 1.4, 2.6), "#7FD4E8", 35, "room",
          rot=(math.radians(35), math.radians(-40), 0), size=(1.0, 1.0))
    if xmas:
        light("treeglow", "POINT", (-2.85, 1.45, 1.0), "#F0C080", 35, "xmasB")


# ------------------------------------------------------------- per-angle setup
def view(name: str, aspect: str = "16x9") -> dict:
    """One angle's camera, where he stands and whether it opens chapters, in
    the long's frame or the phone's."""
    return CAMERAS[name] if aspect == "16x9" else PORTRAIT[name]


def stem_of(name: str, season: str, aspect: str = "16x9") -> str:
    """What an angle's pictures and its rooms.json entry are called: the long's
    under the angle's own name, the phone's with `-9x16` after it."""
    stem = name if season == "plain" else f"{name}-christmas"
    return stem if aspect == "16x9" else f"{stem}-9x16"


def canvas() -> tuple[int, int]:
    """The kit canvas of the frame being rendered: the long's, or the phone's
    when the frame stands up."""
    r = bpy.context.scene.render
    return CANVASES["16x9"] if r.resolution_x >= r.resolution_y else CANVASES["9x16"]


def camera(name: str, aspect: str = "16x9") -> bpy.types.Object:
    scn = bpy.context.scene
    loc, target, lens = view(name, aspect)["cam"]
    cam = scn.camera
    if cam is None:
        cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
        scn.collection.objects.link(cam)
        scn.camera = cam
    cam.location = loc
    cam.data.lens = lens
    cam.data.sensor_width = 36
    cam.data.clip_start = 0.05
    rot = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y")
    roll = view(name, aspect).get("roll")
    if roll:
        from mathutils import Quaternion
        rot = rot @ Quaternion((0, 0, 1), math.radians(roll))
    cam.rotation_euler = rot.to_euler()
    # an angle's own floor paper, and nobody else's
    for angle in FLOOR_PILES:
        for o in THINGS.get(f"floorpile-{angle}", {}).get("objects", ()):
            o.hide_render = not (aspect == "9x16" and angle == name)
    bpy.context.view_layer.update()
    return cam


def to_canvas(p) -> tuple[float, float, float]:
    """A world point as canvas units (1920x1080, or 1080x1920 standing up)
    and its depth."""
    scn = bpy.context.scene
    v = world_to_camera_view(scn, scn.camera, Vector(p))
    cw, ch = canvas()
    return v.x * cw, (1 - v.y) * ch, v.z


def anchor(name: str, aspect: str = "16x9") -> dict | None:
    """His host-anchor in canvas units: the standing box's projected height,
    its bottom on the floor where he stands."""
    spot = view(name, aspect).get("spot")
    if spot is None:
        return None
    fx, fy, _ = to_canvas((spot[0], spot[1], 0.0))
    _tx, ty, _ = to_canvas((spot[0], spot[1], DENNIS_BOX_M))
    h = fy - ty
    w = h * 400 / 720 * 0.34       # advisory: about his shoulders' width
    return {"x": round(fx - w / 2), "y": round(ty), "w": round(w), "h": round(h)}


def title_slot(name: str, aspect: str = "16x9") -> dict | None:
    """Where the slate is in this angle: the rectangle inside its face that a
    flat line of type can be set in, and the frame around it as the ground."""
    if not view(name, aspect).get("title"):
        return None
    sx0, sx1, sz0, sz1 = SLATE
    face = [to_canvas((x, BACK - 0.03, z)) for x, z in ((sx0, sz1), (sx1, sz1), (sx1, sz0), (sx0, sz0))]
    tl, tr, br, bl = face
    x0, x1 = max(tl[0], bl[0]), min(tr[0], br[0])
    y0, y1 = max(tl[1], tr[1]), min(bl[1], br[1])
    cw, ch = canvas()
    if min(x0, y0) < 0 or x1 > cw or y1 > ch or x1 - x0 < 0.15 * min(cw, ch):
        return None             # the slate is not (all) in shot: no title here
    mx, my = (x1 - x0) * 0.07, (y1 - y0) * 0.12
    outer = [to_canvas((x, BACK - 0.03, z)) for x, z in
             ((sx0 - 0.05, sz1 + 0.05), (sx1 + 0.05, sz1 + 0.05), (sx1 + 0.05, sz0 - 0.05), (sx0 - 0.05, sz0 - 0.05))]
    gx0, gx1 = min(p[0] for p in outer), max(p[0] for p in outer)
    gy0, gy1 = min(p[1] for p in outer), max(p[1] for p in outer)
    return {"x": round(x0 + mx), "y": round(y0 + my), "w": round(x1 - x0 - 2 * mx),
            "h": round(y1 - y0 - 2 * my),
            "groundBox": {"x": round(gx0), "y": round(gy0), "w": round(gx1 - gx0), "h": round(gy1 - gy0)}}


def surfaces() -> dict:
    """Where the bot writes, in canvas units: the board's clear area (right of
    the cards) and the screen's chart area, each as four corners (top left,
    top right, bottom right, bottom left), with the colour that surface is
    painted, so the writing goes on as ink over it in the room's light."""
    bx0, bx1, bz0, bz1 = BOARD
    y = BACK - 0.025
    ax0, ax1, az0, az1 = bx0 + 0.38, bx1 - 0.06, bz0 + 0.06, bz1 - 0.06
    board = [to_canvas((x, y, z))[:2] for x, z in ((ax0, az1), (ax1, az1), (ax1, az0), (ax0, az0))]
    scr = bpy.data.objects["screenface"]
    lo = Vector([min(c[i] for c in scr.bound_box) for i in range(3)])
    hi = Vector([max(c[i] for c in scr.bound_box) for i in range(3)])
    W, H = SCREEN_TEX
    x0, y0, x1, y1 = SCREEN_CHART

    def texel(px, py):
        u, v = px / W, 1 - py / H
        return to_canvas(scr.matrix_world @ Vector((lo.x + u * (hi.x - lo.x), lo.y + v * (hi.y - lo.y), 0)))[:2]

    screen = [texel(x0, y0), texel(x1, y0), texel(x1, y1), texel(x0, y1)]
    rnd = lambda q: [[round(a, 1), round(b, 1)] for a, b in q]  # noqa: E731
    out = {"board": {"quad": rnd(board), "paper": list(BOARD_PAPER), "size": [ax1 - ax0, az1 - az0]},
           "screen": {"quad": rnd(screen), "backlight": list(SCREEN_BACKLIGHT),
                      "size": [x1 - x0, y1 - y0]}}
    # THE LETTERED THINGS: each plane's corners as its picture's (top left,
    # top right, bottom right, bottom left), how far off it is, its kind,
    # paper, picture size and the box on its picture the words go in.
    items = []
    for name, spec in sorted(LETTERED.items()):
        o = bpy.data.objects.get(name)
        if o is None or o.hide_render:
            continue
        hx, hy = spec.get("half", (0.5, 0.5))
        pts = [to_canvas(o.matrix_world @ Vector(c))
               for c in ((-hx, hy, 0), (hx, hy, 0), (hx, -hy, 0), (-hx, -hy, 0))]
        if min(p[2] for p in pts) <= 0.05:
            continue
        tex, _, box_ = LABELS[spec["kind"]]
        items.append({"id": name, "kind": spec["kind"], "paper": spec["paper"],
                      "tex": list(tex), "box": list(box_), "quad": rnd([p[:2] for p in pts]),
                      "depth": round(sum(p[2] for p in pts) / 4, 3)})
    if items:
        out["labels"] = {"items": items}
    return out


def his_depth(name: str, aspect: str = "16x9") -> float | None:
    """How far in front of the camera he stands (along its axis), or None
    where nobody does."""
    spot = view(name, aspect).get("spot")
    if spot is None:
        return None
    cam = bpy.context.scene.camera
    fwd = cam.matrix_world.to_quaternion() @ Vector((0, 0, -1))
    return (Vector((spot[0], spot[1], 1.0)) - cam.location).dot(fwd)


# ------------------------------------------------------------------ rendering
def light_groups() -> list[str]:
    """The light groups the built room lights with, the world's among them."""
    scn = bpy.context.scene
    got = {o.lightgroup for o in scn.objects if o.lightgroup}
    if scn.world is not None and scn.world.lightgroup:
        got.add(scn.world.lightgroup)
    return sorted(got)


def setup_render(size: tuple[int, int], samples: int) -> None:
    scn = bpy.context.scene
    r = scn.render
    r.engine = "CYCLES"
    scn.cycles.device = "CPU"
    scn.cycles.samples = samples
    scn.cycles.use_adaptive_sampling = True
    scn.cycles.adaptive_threshold = 0.03
    scn.cycles.use_denoising = False
    r.use_persistent_data = True
    scn.cycles.max_bounces = 6
    scn.cycles.diffuse_bounces = 3
    scn.cycles.glossy_bounces = 2
    scn.cycles.transmission_bounces = 2
    scn.cycles.caustics_reflective = False
    scn.cycles.caustics_refractive = False
    scn.cycles.sample_clamp_indirect = 6.0
    r.resolution_x, r.resolution_y = size
    r.resolution_percentage = 100
    scn.view_settings.view_transform = "Standard"
    scn.view_settings.look = "None"
    vl = bpy.context.view_layer
    for g in light_groups():
        if g not in vl.lightgroups:
            vl.lightgroups.add(name=g)
    vl.cycles.denoising_store_passes = True
    # Lines at Dennis's own weight, in his ink, into their own pass.
    r.use_freestyle = True
    r.line_thickness_mode = "ABSOLUTE"
    scale = max(size) / max(FULL)
    fs = vl.freestyle_settings
    fs.as_render_pass = True
    fs.crease_angle = math.radians(128)
    while fs.linesets:
        fs.linesets.remove(fs.linesets[0])
    for nm, edges, width in (("outline", ("silhouette", "border", "external_contour"), 3.6),
                             ("detail", ("crease", "material_boundary"), 2.0)):
        ls = fs.linesets.new(nm)
        ls.select_by_visibility = True
        ls.select_by_edge_types = True
        for e in ("silhouette", "border", "crease", "external_contour", "material_boundary", "contour"):
            setattr(ls, f"select_{e}", e in edges)
        style = bpy.data.linestyles.new(nm)
        style.color = lin(INK)[:3]
        style.thickness = max(width * scale, 1.4)
        style.chaining = "PLAIN"
        ls.linestyle = style


def compositor(out: Path, stem: str) -> None:
    """Each light group denoised on its own, plus alpha and the lines, into one
    multilayer EXR: the loop's frames are sums of these, so nothing is
    rendered twice to make a screen dip."""
    scn = bpy.context.scene
    ng = bpy.data.node_groups.get("comp") or bpy.data.node_groups.new("comp", "CompositorNodeTree")
    for nd in list(ng.nodes):
        ng.nodes.remove(nd)
    scn.compositing_node_group = ng
    rl = ng.nodes.new("CompositorNodeRLayers")
    fo = ng.nodes.new("CompositorNodeOutputFile")
    fo.directory = str(out) + "/"
    fo.file_name = stem
    fo.format.file_format = "OPEN_EXR_MULTILAYER"
    fo.format.color_depth = "32"
    for g in light_groups():
        dn = ng.nodes.new("CompositorNodeDenoise")
        ng.links.new(rl.outputs[f"Combined_{g}"], dn.inputs["Image"])
        ng.links.new(rl.outputs["Denoising Albedo"], dn.inputs["Albedo"])
        ng.links.new(rl.outputs["Denoising Normal"], dn.inputs["Normal"])
        fo.file_output_items.new("RGBA", g)
        ng.links.new(dn.outputs["Image"], fo.inputs[g])
    fo.file_output_items.new("FLOAT", "alpha")
    ng.links.new(rl.outputs["Alpha"], fo.inputs["alpha"])
    fo.file_output_items.new("RGBA", "lines")
    ng.links.new(rl.outputs["Freestyle"], fo.inputs["lines"])


def render_room(out: Path, stem: str) -> Path:
    """The one expensive render of an angle: the whole room, every light group
    and the lines."""
    scn = bpy.context.scene
    for t in THINGS.values():
        for o in t["objects"]:
            o.is_holdout = False
    scn.render.film_transparent = False
    scn.render.use_freestyle = True
    compositor(out, stem)
    scn.render.filepath = str(out / f"_{stem}_beauty")
    bpy.ops.render.render(write_still=False)
    exr = out / f"{stem}.exr"
    if not exr.exists():
        raise RuntimeError(f"the compositor wrote no {exr}")
    return exr


MASKS = ("front", "board", "screen", "window", "labels")


def render_masks(out: Path, stem: str, him: float | None) -> Path:
    """Five masks in one cheap pass: the board (green), the screen (blue), the
    lettered things (red), and two AOVs, the night through the window and
    what stands in front of him.
    Flat colour on a transparent film, one ray a sample, every object where
    it is, so each mask is what the camera SEES of that surface, the room's
    own occluders already cut out of it. The front layer, the episode's
    writing and the weather on the glass are all laid through these, so they
    line up with the room render pixel for pixel.

    IN FRONT OF HIM IS DECIDED PER PIXEL, not per thing. He is a flat figure
    standing at his spot, so a pixel is in front of him where the furniture
    there is nearer the camera than he is: the near end of a desk he stands
    at the side of covers him and its far end does not, which no per-thing
    rule gets right. The room itself (walls, floor, rug, what hangs on the
    walls) is never in front of him.
    """
    scn = bpy.context.scene
    vl = bpy.context.view_layer
    colour = {"boardface": (0, 1, 0, 1), "screenface": (0, 0, 1, 1),
              **{name: (1, 0, 0, 1) for name in LETTERED}}
    for o in bpy.data.objects:      # anything no thing claimed is not a mask
        o.color = (0, 0, 0, 1)
        o["win"] = o["movable"] = 0.0
    for t in THINGS.values():
        for o in t["objects"]:
            o.color = colour.get(o.name, (0, 0, 0, 1))
            o["win"] = 1.0 if o.name.startswith("outside") else 0.0
            o["movable"] = 0.0 if t["fixed"] else 1.0
    flat = bpy.data.materials.get("_mask") or bpy.data.materials.new("_mask")
    flat.use_nodes = True
    nt = flat.node_tree
    for nd in list(nt.nodes):
        nt.nodes.remove(nd)
    info = nt.nodes.new("ShaderNodeObjectInfo")
    em = nt.nodes.new("ShaderNodeEmission")
    nt.links.new(info.outputs["Color"], em.inputs["Color"])
    mo = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(em.outputs["Emission"], mo.inputs["Surface"])
    attr = nt.nodes.new("ShaderNodeAttribute")
    attr.attribute_type = "OBJECT"
    attr.attribute_name = "win"
    aov = nt.nodes.new("ShaderNodeOutputAOV")
    aov.aov_name = "win"
    nt.links.new(attr.outputs["Fac"], aov.inputs["Value"])
    camdata = nt.nodes.new("ShaderNodeCameraData")
    nearer = nt.nodes.new("ShaderNodeMath")
    nearer.operation = "LESS_THAN"
    nearer.inputs[1].default_value = him if him is not None else -1.0
    nt.links.new(camdata.outputs["View Z Depth"], nearer.inputs[0])
    movable = nt.nodes.new("ShaderNodeAttribute")
    movable.attribute_type = "OBJECT"
    movable.attribute_name = "movable"
    both = nt.nodes.new("ShaderNodeMath")
    both.operation = "MULTIPLY"
    nt.links.new(nearer.outputs["Value"], both.inputs[0])
    nt.links.new(movable.outputs["Fac"], both.inputs[1])
    aov2 = nt.nodes.new("ShaderNodeOutputAOV")
    aov2.aov_name = "front"
    nt.links.new(both.outputs["Value"], aov2.inputs["Value"])
    for name in ("win", "front"):
        if name not in vl.aovs:
            a = vl.aovs.add()
            a.name, a.type = name, "VALUE"
    saved = (scn.cycles.samples, scn.cycles.max_bounces, scn.cycles.use_adaptive_sampling)
    scn.cycles.samples, scn.cycles.max_bounces, scn.cycles.use_adaptive_sampling = 16, 0, False
    vl.material_override = flat
    scn.render.film_transparent = True
    scn.render.use_freestyle = False
    ng = bpy.data.node_groups.get("comp")
    for nd in list(ng.nodes):
        ng.nodes.remove(nd)
    rl = ng.nodes.new("CompositorNodeRLayers")
    fo = ng.nodes.new("CompositorNodeOutputFile")
    fo.directory = str(out) + "/"
    fo.file_name = stem
    fo.format.file_format = "OPEN_EXR_MULTILAYER"
    fo.format.color_depth = "32"
    fo.file_output_items.new("RGBA", "rgb")
    ng.links.new(rl.outputs["Image"], fo.inputs["rgb"])
    for name in ("win", "front"):
        fo.file_output_items.new("FLOAT", name)
        ng.links.new(rl.outputs[name], fo.inputs[name])
    scn.render.filepath = str(out / f"_{stem}_beauty")
    try:
        bpy.ops.render.render(write_still=False)
    finally:
        vl.material_override = None
        scn.cycles.samples, scn.cycles.max_bounces, scn.cycles.use_adaptive_sampling = saved
        scn.render.film_transparent = False
        scn.render.use_freestyle = True
    exr = out / f"{stem}.exr"
    if not exr.exists():
        raise RuntimeError(f"the compositor wrote no {exr}")
    return exr


# --------------------------------------------------------------- composition
def read_exr(path: Path, *, drop: bool = False) -> dict[str, np.ndarray]:
    """The planes of a multilayer EXR; `drop` deletes the file once read (an
    angle's EXRs are half a gigabyte, and a full run makes sixty-four)."""
    import OpenEXR

    planes = {}
    with OpenEXR.File(str(path)) as f:
        for part in f.parts:
            for cname, ch in part.channels.items():
                planes[cname.split(".")[0]] = np.array(ch.pixels, dtype=np.float32)
    if drop:
        path.unlink()
    return planes


def oetf(c: np.ndarray) -> np.ndarray:
    c = np.clip(c, 0.0, 1.0)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055)


def compose(planes: dict, weights: dict) -> np.ndarray:
    """One frame: the light groups at these weights (a number, or a tint as
    (r, g, b)), a group not named left out, the lines over them, 8-bit RGB."""
    rgb = sum(planes[g][..., :3] * np.asarray(w, dtype=np.float32) for g, w in weights.items() if g in planes)
    lines = planes.get("lines")
    if lines is not None:
        la = lines[..., 3]
        rgb = rgb * (1 - la[..., None]) + lines[..., :3]
    return (oetf(rgb) * 255 + 0.5).astype(np.uint8)


def masks(planes: dict, scale: float) -> dict[str, np.ndarray]:
    """The five masks as 8-bit pictures. The front one is grown by half an
    outline, so the ink drawn round the front things' edge comes forward with
    them; the others are exact."""
    from PIL import Image, ImageFilter

    rgb = planes["rgb"]
    raw = {"front": planes["front"], "board": rgb[..., 1], "screen": rgb[..., 2], "window": planes["win"],
           "labels": rgb[..., 0]}
    out = {k: (np.clip(v, 0, 1) * 255 + 0.5).astype(np.uint8) for k, v in raw.items()}
    grow = max(3, int(round(3.6 * scale)) | 1)
    out["front"] = np.asarray(Image.fromarray(out["front"]).filter(ImageFilter.MaxFilter(grow)))
    return out


def seen(mask: np.ndarray, quad) -> int:
    """How many pixels of `mask` are on inside `quad` (canvas units)."""
    from PIL import Image, ImageDraw

    h, w = mask.shape
    cw = canvas()[0]
    k = w / cw
    poly = Image.new("L", (w, h), 0)
    ImageDraw.Draw(poly).polygon([(x * k, y * k) for x, y in quad], fill=255)
    return int(((np.asarray(poly) > 0) & (mask > 127)).sum())


def cut(back: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """A front layer: the room render where the front things are. (The ingest
    makes the real ones the same way, from each frame it installs.)"""
    out = np.concatenate([back, alpha[..., None]], axis=-1)
    out[alpha == 0] = 0
    return out


def head_covered(front: np.ndarray | None, anc: dict | None) -> float | None:
    """How much of his head the front layer paints over, standing him in the
    angle by the contract with the kit's plain standing pose (the measure
    kit_engine.js headCovered takes of the drawn rooms)."""
    if front is None or anc is None:
        return None
    from PIL import Image

    host = REPO / "assets" / "plates" / "host" / "to-camera.png"
    if not host.exists():
        return None
    him = Image.open(host).getchannel("A")
    cw, ch = CANVASES["16x9"] if front.shape[1] >= front.shape[0] else CANVASES["9x16"]
    fa = Image.fromarray(front[..., 3]).resize((cw, ch), Image.BILINEAR)
    s = anc["h"] / 720
    w, h = max(int(400 * s), 1), max(int(720 * s), 1)
    him = him.resize((w, h), Image.BILINEAR)
    x0 = int(round(anc["x"] + anc["w"] / 2 - w / 2))
    y0 = int(anc["y"])
    rows = int(SHOULDER_UNITS * s)
    head = covered = 0
    hm = np.asarray(him)
    fm = np.asarray(fa)
    for yy in range(min(rows, h)):
        Y = y0 + yy
        if not 0 <= Y < ch:
            continue
        for xx in np.nonzero(hm[yy] > 0)[0]:
            X = x0 + int(xx)
            if 0 <= X < cw:
                head += 1
                covered += int(fm[Y, X] > 127)
    return round(covered / head, 3) if head else None


def save(img: np.ndarray, path: Path) -> None:
    from PIL import Image

    im = Image.fromarray(img)
    if path.suffix == ".jpg":
        im.convert("RGB").save(path, quality=90, subsampling=0)
    else:
        im.save(path, optimize=True)


def render_angle(name: str, season: str, size, samples: int, out: Path, scratch: Path,
                 aspect: str = "16x9") -> dict:
    camera(name, aspect)
    stem = stem_of(name, season, aspect)
    cam = view(name, aspect)["cam"]
    entry = {"angle": name, "season": season, "aspect": aspect, "anchor": anchor(name, aspect),
             "title": title_slot(name, aspect),
             "camera": {"location": list(cam[0]), "target": list(cam[1]), "lens": cam[2]},
             "surfaces": surfaces()}
    anc = entry["anchor"]
    whole = read_exr(render_room(scratch, stem), drop=True)
    mk = masks(read_exr(render_masks(scratch, stem + "_masks", his_depth(name, aspect)), drop=True),
               max(size) / FULL[0])
    # A mask nothing in this angle shows is not written: no front things, the
    # board or the screen out of shot, the window not in view.
    entry["masks"] = {}
    for k in MASKS:
        if int((mk[k] > 127).sum()) < 64:
            continue
        save(mk[k], out / f"{stem}_mask_{k}.png")
        entry["masks"][k] = f"{stem}_mask_{k}.png"
    lab = entry["surfaces"].get("labels")
    if lab is not None and "labels" in entry["masks"]:
        # a lettered thing the camera sees less than a few pixels of is left
        # out: nothing could be read on it
        lab["items"] = [it for it in lab["items"] if seen(mk["labels"], it["quad"]) >= 40]
        if not lab["items"]:
            entry["masks"].pop("labels")
            (out / f"{stem}_mask_labels.png").unlink()
    for k in ("board", "screen", "labels"):
        if k not in entry["masks"]:
            entry["surfaces"].pop(k, None)
    entry["states"] = []
    first_front = None
    for tag, w in states(season).items():
        back = compose(whole, w)
        save(back, out / f"{stem}{tag}.jpg")
        entry["states"].append({"tag": tag, "png": f"{stem}{tag}.jpg"})
        if first_front is None and "front" in entry["masks"]:
            first_front = cut(back, mk["front"])
    entry["headCovered"] = head_covered(first_front, anc)
    return entry


def preview_sheet(entries: list[dict], out: Path, path: Path) -> None:
    """Each angle with him stood in it by the contract, labelled: the check a
    person makes before trusting any of it."""
    from PIL import Image, ImageDraw

    host = REPO / "assets" / "plates" / "host" / "to-camera.png"
    tiles = []
    for e in entries:
        tile = (640, 360) if e.get("aspect", "16x9") == "16x9" else (270, 480)
        cw = CANVASES[e.get("aspect", "16x9")][0]
        im = Image.open(out / e["states"][0]["png"]).convert("RGBA").resize(tile)
        a = e["anchor"]
        if a and host.exists():
            k = tile[0] / cw
            hh = a["h"] * k
            him = Image.open(host).convert("RGBA")
            him = him.resize((max(int(hh * 400 / 720), 1), max(int(hh), 1)))
            im.alpha_composite(him, (int((a["x"] + a["w"] / 2) * k - him.width / 2), int(a["y"] * k)))
            fr = e["masks"].get("front")
            if fr:
                back = Image.open(out / e["states"][0]["png"]).convert("RGBA").resize(tile)
                back.putalpha(Image.open(out / fr).convert("L").resize(tile))
                im.alpha_composite(back)
        d = ImageDraw.Draw(im)
        if e.get("title"):
            t = e["title"]
            k = tile[0] / cw
            d.rectangle([t["x"] * k, t["y"] * k, (t["x"] + t["w"]) * k, (t["y"] + t["h"]) * k], outline="yellow")
        d.text((8, 8), f"{e['angle']} {e['season']} head {e.get('headCovered')}", fill="yellow")
        tiles.append(im)
    tw, th = max(t.width for t in tiles), max(t.height for t in tiles)
    cols = 3 if tw > th else 6
    sheet = Image.new("RGB", (tw * cols, th * ((len(tiles) + cols - 1) // cols)), "black")
    for i, t in enumerate(tiles):
        sheet.paste(t.convert("RGB"), ((i % cols) * tw, (i // cols) * th))
    sheet.save(path, quality=88)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cam", action="append", help="one angle (repeatable); default every angle")
    ap.add_argument("--season", choices=("plain", "christmas", "both"), default="both")
    ap.add_argument("--aspect", choices=(*ASPECTS, "both"), default="both",
                    help="the long's 16:9 cameras, the shorts' 9:16 ones, or both")
    ap.add_argument("--samples", type=int, default=32)
    ap.add_argument("--preview", action="store_true", help="640x360, 8 samples, into the scratch dir")
    ap.add_argument("--out", type=Path, default=RENDERS)
    ap.add_argument("--scratch", type=Path, default=HERE / ".scratch")
    args = ap.parse_args(argv)

    names = args.cam or list(CAMERAS)
    unknown = [n for n in names if n not in CAMERAS]
    if unknown:
        ap.error(f"unknown angle(s): {', '.join(unknown)}")
    aspects = ASPECTS if args.aspect == "both" else (args.aspect,)
    samples = 8 if args.preview else args.samples
    out = args.scratch / "preview" if args.preview else args.out
    out.mkdir(parents=True, exist_ok=True)
    args.scratch.mkdir(parents=True, exist_ok=True)
    seasons = ("plain", "christmas") if args.season == "both" else (args.season,)

    manifest_path = out / "rooms.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    entries = []
    for season in seasons:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        addon_utils.enable("cycles")
        THINGS.clear()
        LETTERED.clear()
        _MATS.clear()
        build_room(season)
        for aspect in aspects:
            size = (PREVIEWS if args.preview else FULLS)[aspect]
            setup_render(size, samples)
            for name in names:
                if season == "christmas" and name not in CHRISTMAS:
                    continue
                if aspect == "9x16" and name not in PORTRAIT:
                    continue
                print(f"[room3d] {name} {season} {aspect}", flush=True)
                t0 = time.monotonic()
                e = render_angle(name, season, size, samples, out, args.scratch, aspect)
                print(f"[room3d] {name} {season} {aspect} done in {time.monotonic() - t0:.0f}s, "
                      f"head covered {e['headCovered']}", flush=True)
                manifest[stem_of(name, season, aspect)] = e
                entries.append(e)
                # After every angle, so a long run that stops keeps what it made.
                manifest_path.write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    if args.preview or len(entries) > 1:
        preview_sheet(entries, out, out / "contact.jpg")
    print(f"[room3d] {len(entries)} angle(s) -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
