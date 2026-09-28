"""The writer's scenes: where Dennis is, and what he is doing there.

`[SCENE: desk-side | pose=holding-a-mug]` in a LONG, placed before the word
the cut lands on. The writer names the room angle and the pose, and the
renderer stands him there and does nothing else. It holds for every beat of
him until the next [SCENE] — across the cutaways in between, the way a scene
heading holds in a screenplay — so a chapter is directed with a handful of
them, not one per sentence.

THE WRITER PICKS, THE KIT SAYS WHAT EXISTS. Everything here reads the
registry: which angles the kit draws at 16:9, which of them a figure can stand
in (`hostAnchor`), which poses it draws, and which rooms design drew each pose
for (`fits`, carried from kit-model.js by the ingest). A new drop brings its
own rooms and poses, and the writer's menu follows it with no edit here.

Where the writer names no scene — before the first one, or in a script that
names none — the renderer picks his room and pose the way it always has.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pipeline.tagging import split_payload_fields

# The long is 16:9, and so is every scene. A room drawn only for the vertical
# cut (`plates.ONLY_AT`) is not a room the long can be shot in.
SCENE_ASPECT = "16x9"

# The strips a pose is played through. A pose is its still; these are not
# poses in their own right and a writer never names one.
_STRIPS = ("-talk", "-idle", "-blink")


def _slug(name: str) -> str:
    return re.sub(r"[\s_]+", "-", (name or "").strip().lower())


def room_stem(name: str) -> str:
    """`desk side`, `room/desk-side`, `desk-side-16x9` -> `room/desk-side`."""
    s = _slug(name)
    s = s.removeprefix("room/")
    for suffix in ("-16x9", "-9x16"):
        s = s.removesuffix(suffix)
    return f"room/{s}" if s else ""


def pose_key(name: str) -> str:
    """`holding a mug`, `host/holding-a-mug` -> `host/holding-a-mug`."""
    s = _slug(name).removeprefix("host/")
    return f"host/{s}" if s else ""


def _angle(stem: str) -> str:
    return stem.removeprefix("room/")


def scene_rooms(reg) -> dict[str, object]:
    """Every angle a long can be shot in, stem -> its 16:9 plate.

    The plain angles only: a seasonal twin is its angle dressed for December,
    and the episode's date decides that, never the writer.
    """
    from pipeline.plates import ONLY_AT

    out: dict[str, object] = {}
    for key in sorted(reg.keys()):
        p = reg.get(key)
        if p is None or p.family != "room" or p.aspect != SCENE_ASPECT:
            continue
        if p.season or p.dressed_from:
            continue
        stem = key.removesuffix(f"-{SCENE_ASPECT}")
        if SCENE_ASPECT not in ONLY_AT.get(stem, (SCENE_ASPECT,)):
            continue
        out[stem] = p
    return out


def scene_poses(reg) -> dict[str, object]:
    """Every pose the kit draws him in, key -> its plate (the still)."""
    out: dict[str, object] = {}
    for key in sorted(reg.keys()):
        p = reg.get(key)
        if p is None or p.family != "host" or key.endswith(_STRIPS):
            continue
        out[key] = p
    return out


def is_framing(pose) -> bool:
    """A camera distance (the close-up), not a figure standing in the room."""
    return not getattr(pose, "floor_line_y", None)


def stands_in(room) -> bool:
    """Whether a figure can stand in this room: it has somewhere to stand."""
    return not room.refuses_host and room.slot("host-anchor") is not None


def pose_spec(reg, key: str) -> dict:
    spec = (getattr(reg, "host_poses", None) or {}).get(key)
    return spec if isinstance(spec, dict) else {}


def drawn_for(reg, key: str) -> tuple[str, ...]:
    """The rooms design drew a pose for, as stems. Empty when the kit says none."""
    return tuple(str(r) for r in (pose_spec(reg, key).get("fits") or ()))


def talks(reg, key: str) -> bool:
    return bool(pose_spec(reg, key).get("talks", True))


@dataclass
class SceneFill:
    """A [SCENE] resolved against the kit: the room, the pose, and what is wrong."""

    room: str = ""                  # the angle's stem, "room/desk-side"
    pose: str = ""                  # the pose's key, "host/holding-a-mug"; "" = his to pick
    problems: list[str] = field(default_factory=list)   # the tag is dropped
    warnings: list[str] = field(default_factory=list)   # it stands, and says so

    @property
    def ok(self) -> bool:
        return bool(self.room) and not self.problems

    @property
    def values(self) -> dict[str, str]:
        return {"room": self.room, "pose": self.pose}


def resolve_scene(reg, payload: str) -> SceneFill:
    """`"desk-side | pose=holding-a-mug"` against the kit. Never raises."""
    head, fields, field_warnings = split_payload_fields(payload)
    fill = SceneFill()
    where = f"[SCENE: {head}]"
    fill.warnings += [f"{where} {w}" for w in field_warnings]
    pose_name = fields.pop("pose", "")
    for name in fields:
        fill.warnings.append(f"{where} has no `{name}` field — ignored. A "
                             f"scene takes the room, and `pose=`.")

    rooms = scene_rooms(reg)
    stem = room_stem(head)
    if not stem:
        fill.problems.append("[SCENE] names no room. The rooms are: "
                             + ", ".join(_angle(s) for s in rooms))
        return fill
    if stem not in rooms:
        fill.problems.append(
            f"{where} is not a room the long can be shot in. The rooms are: "
            + ", ".join(_angle(s) for s in rooms))
        return fill
    fill.room = stem
    room = rooms[stem]

    if not pose_name:
        if stands_in(room):
            fill.warnings.append(
                f"{where} names no pose, so the bot picks one. Name it "
                f"(`| pose=to-camera`): the scene is yours to imagine.")
        return fill

    key = pose_key(pose_name)
    poses = scene_poses(reg)
    if key not in poses:
        fill.warnings.append(
            f"{where} pose={pose_name!r} is not a pose the kit draws — the "
            f"bot picks one instead. The poses are: "
            + ", ".join(k.removeprefix("host/") for k in poses))
        return fill
    pose = poses[key]
    if not is_framing(pose) and not stands_in(room):
        fill.warnings.append(
            f"{where} has no floor to stand on, so nobody is in it: the scene "
            f"is the room alone, over your words. pose={pose_name} is ignored "
            f"(only the close-up can be shot here).")
        return fill
    fill.pose = key
    fits = [s for s in drawn_for(reg, key) if s in rooms and stands_in(rooms[s])]
    if fits and not is_framing(pose) and stem not in fits:
        fill.warnings.append(
            f"{where} pose={key.removeprefix('host/')}: design drew that pose "
            f"for {', '.join(_angle(s) for s in fits)}. It will stand in "
            f"{_angle(stem)}, but check the frame.")
    return fill


# --------------------------------------------------------------------------
# The writer's menu.
# --------------------------------------------------------------------------

def _one_line(text: str) -> str:
    return " ".join(str(text or "").split())


def scene_catalogue(reg) -> str:
    """Every room and pose the writer may name, and what design says of each.

    Generated, so it is always this kit's: a room or a pose that is not in
    the registry is not on the menu, and one that arrives in a drop is.
    """
    rooms = scene_rooms(reg)
    poses = scene_poses(reg)
    lines: list[str] = ["ROOMS (the angle is the scene's name; 16:9):"]
    for stem, p in rooms.items():
        notes = []
        if p.slot("title") is not None:
            notes.append("has a title slot: a scene here when the first "
                         "chapter opens carries its title")
        if not stands_in(p):
            notes.append("NOBODY STANDS HERE: the room alone, or the close-up")
        held = (getattr(reg, "held_back", {}) or {}).get("rooms", {}).get(stem)
        if held:
            notes.append("never picked by the bot: yours to name when it fits")
        purpose = _one_line(p.purpose) or "(design wrote no line for it)"
        lines.append(f"  {_angle(stem):<16} {purpose}")
        if p.caution:
            lines.append(f"  {'':<16} caution: {_one_line(p.caution)}")
        if notes:
            lines.append(f"  {'':<16} " + "; ".join(notes))
    lines.append("")
    lines.append("POSES (pose=; he talks in all of them unless it says not):")
    for key, p in poses.items():
        spec = pose_spec(reg, key)
        name = key.removeprefix("host/")
        purpose = _one_line(spec.get("purpose") or p.purpose)
        lines.append(f"  {name:<22} {purpose}")
        notes = []
        if is_framing(p):
            notes.append("a CLOSE-UP, head and shoulders: works in any room, "
                         "including the two nobody stands in")
        else:
            # Only the angles a long can shoot him standing in: design drew
            # some poses for window-talk too, which is the vertical cut's
            # alone, and names `board` where he stands at the board's side.
            fits = [s for s in drawn_for(reg, key)
                    if s in rooms and stands_in(rooms[s])]
            if fits:
                notes.append("drawn for " + ", ".join(_angle(s) for s in fits))
        if not talks(reg, key):
            notes.append("NO MOUTH: he does not speak in it — your line plays "
                         "over him, so keep it to a few words or none")
        limit = spec.get("limit")
        if limit:
            notes.append(f"at most {int(limit)} a video")
        if spec.get("plateOn"):
            notes.append(f"his hand is out to his {spec['plateOn']}: for "
                         f"showing the thing beside him")
        ctypes = tuple(getattr(p, "chapter_types", ()) or ())
        if ctypes:
            notes.append("design files it under " + ", ".join(ctypes))
        if notes:
            lines.append(f"  {'':<22} " + "; ".join(notes))
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Validation, across the whole script.
# --------------------------------------------------------------------------

def scene_problems(script, reg) -> tuple[list[str], list[str]]:
    """(warnings, blocking) for the writer's scenes as a set.

    Nothing here blocks. A scene the kit cannot shoot was dropped at parse,
    with the reason; what is left is the writer's picture, and these say
    where it will not come out as written.
    """
    from pipeline.models import TagType

    warnings: list[str] = []
    scenes = [e for e in script.events if e.type is TagType.SCENE]
    counted: dict[str, int] = {}
    for e in scenes:
        key = e.values.get("pose", "")
        if not key:
            continue
        counted[key] = counted.get(key, 0) + 1
    for key, n in sorted(counted.items()):
        limit = pose_spec(reg, key).get("limit")
        if limit and n > int(limit):
            warnings.append(
                f"pose={key.removeprefix('host/')} is in {n} scenes and the "
                f"kit allows {int(limit)} a video — past that the bot picks "
                f"his pose instead. Keep it for the one beat that earns it.")
    if not scenes:
        warnings.append(
            "no [SCENE] anywhere — the bot picks every room Dennis is in and "
            "every pose he stands in. Direct him: the rooms and poses are in "
            "the scene menu, and one [SCENE] at the top of each chapter is the "
            "least that makes the picture yours.")
    else:
        # A sentence or so of grace: "[BEAT] So." before the first scene is
        # still the writer opening the video.
        first = min(e.char_offset for e in scenes)
        if first > 200:
            warnings.append(
                "the narration runs before your first [SCENE], so the bot "
                "picks where Dennis opens the video. Put one before the first "
                "word to open it yourself.")
    return warnings, []
