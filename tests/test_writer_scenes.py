"""The LONG writer's [SCENE]: where Dennis is, and what he is doing there.

The long is writer-driven. The writer imagines each beat of him — the room
angle and the pose — and names it with [SCENE]; the renderer shoots it and
picks nothing for a beat he directed. It holds across the cutaways until the
next [SCENE]. The menu he picks from is generated off the kit, so a drop's
rooms and poses reach the prompt with no edit.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.models import Cue, CueKind, TagType
from pipeline.parser_long import parse_long_script, validate_long_script
from pipeline.plates import load_plates
from pipeline.scenes import (pose_key, resolve_scene, room_stem,
                             scene_catalogue, scene_poses, scene_problems,
                             scene_rooms)
from pipeline.timeline import (HOST_GAP_WARN_S, MIN_HOST_BEAT_S,
                               plan_long_segments, scene_in_force)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def settings(settings):
    return settings.model_copy(update={"long_min_chars": 0})


@pytest.fixture()
def reg(settings):
    return load_plates(settings.assets_dir)


# --------------------------------------------------------------------------
# What the writer may name: off the kit.
# --------------------------------------------------------------------------

def test_names_are_forgiving_about_how_the_writer_spells_them():
    assert room_stem("Desk Side") == "room/desk-side"
    assert room_stem("room/desk-side-16x9") == "room/desk-side"
    assert room_stem("") == ""
    assert pose_key("holding a mug") == "host/holding-a-mug"
    assert pose_key("host/to-camera") == "host/to-camera"


def test_every_angle_the_long_can_be_shot_in_is_on_the_menu(reg):
    """The reading rooms, the exit, the board and the desk from above were
    drawn and never cut to (picks 6 and 7). They are the writer's now."""
    rooms = scene_rooms(reg)
    for stem in ("room/desk-side", "room/read-close", "room/turn-to-screen",
                 "room/desk-top-down", "room/board", "room/doorway",
                 "room/doorway-wide", "room/board-wide", "room/window-wide",
                 "room/desk-front"):
        assert stem in rooms, f"{stem} is not on the writer's menu"
    # The vertical cut's own angle, and December's twins, are not his.
    assert "room/window-talk" not in rooms
    assert not [s for s in rooms if "christmas" in s]


def test_every_pose_is_on_the_menu_and_no_strip_is(reg):
    poses = scene_poses(reg)
    for key in ("host/to-camera", "host/head-in-hands",
                "host/walking-out-of-frame", "host/close-up",
                "host/holding-a-mug"):
        assert key in poses
    assert not [k for k in poses if k.endswith(("-talk", "-idle", "-blink"))]


def test_the_menu_says_what_design_says_of_each(reg):
    text = scene_catalogue(reg)
    for stem in scene_rooms(reg):
        assert f"  {stem.removeprefix('room/')} " in text
    for key in scene_poses(reg):
        assert f"  {key.removeprefix('host/')} " in text
    # The limits a writer has to know before he picks.
    head = text[text.index("  head-in-hands "):].split("\n  ", 2)
    assert "NO MOUTH" in text[text.index("  head-in-hands "):
                              text.index("  holding-a-filing ")]
    assert "at most 1 a video" in "\n".join(head)
    board = text[text.index("  board "):text.index("  board-side ")]
    assert "NOBODY STANDS HERE" in board


def test_design_s_pose_to_room_pairs_reach_the_menu(reg):
    """kit-model.js says which rooms each pose was drawn for; the ingest
    carries it into the registry and the menu prints it."""
    text = scene_catalogue(reg)
    block = text[text.index("  walking-out-of-frame "):]
    assert "drawn for doorway" in block


# --------------------------------------------------------------------------
# Resolving one [SCENE] against the kit.
# --------------------------------------------------------------------------

def test_a_scene_resolves_to_its_room_and_pose(reg):
    fill = resolve_scene(reg, "desk-side | pose=holding-a-mug")
    assert fill.ok and not fill.warnings, fill.warnings
    assert fill.values == {"room": "room/desk-side", "pose": "host/holding-a-mug"}


def test_a_room_the_kit_does_not_draw_is_refused_with_the_menu(reg):
    fill = resolve_scene(reg, "the kitchen | pose=to-camera")
    assert not fill.ok
    assert "desk-side" in fill.problems[0]


def test_an_unknown_pose_is_dropped_and_the_room_stands(reg):
    fill = resolve_scene(reg, "desk-front | pose=moonwalking")
    assert fill.ok and fill.pose == ""
    assert any("moonwalking" in w for w in fill.warnings)


def test_nobody_stands_in_the_board_but_the_close_up_can_be_shot_there(reg):
    standing = resolve_scene(reg, "board | pose=to-camera")
    assert standing.ok and standing.pose == ""
    assert any("nobody is in it" in w for w in standing.warnings)
    alone = resolve_scene(reg, "desk-top-down")
    assert alone.ok and not alone.warnings
    close = resolve_scene(reg, "board | pose=close-up")
    assert close.ok and close.pose == "host/close-up" and not close.warnings


def test_a_pose_outside_design_s_rooms_stands_and_says_so(reg):
    fill = resolve_scene(reg, "board-side | pose=walking-out-of-frame")
    assert fill.ok and fill.pose == "host/walking-out-of-frame"
    assert any("design drew that pose" in w for w in fill.warnings)


def test_a_standing_room_with_no_pose_asks_the_writer_to_name_one(reg):
    fill = resolve_scene(reg, "doorway")
    assert fill.ok and fill.pose == ""
    assert any("names no pose" in w for w in fill.warnings)


# --------------------------------------------------------------------------
# The parse, and validation across the script.
# --------------------------------------------------------------------------

def test_a_scene_is_parsed_and_never_spoken(settings):
    raw = ("[SCENE: window-wide | pose=to-camera] Nobody cares anymore. "
           "[SCENE: desk side | pose=holding a mug] Which is when I read.")
    script, _ = parse_long_script(raw, "EXMPL", settings)
    scenes = script.events_of(TagType.SCENE)
    assert [e.values for e in scenes] == [
        {"room": "room/window-wide", "pose": "host/to-camera"},
        {"room": "room/desk-side", "pose": "host/holding-a-mug"}]
    assert "SCENE" not in script.narration and "mug" not in script.narration


def test_a_scene_in_a_room_the_kit_lacks_is_dropped_and_named(settings):
    script, warnings = parse_long_script(
        "[SCENE: the kitchen | pose=to-camera] Hello.", "EXMPL", settings)
    assert not script.events_of(TagType.SCENE)
    assert any("kitchen" in w for w in warnings)


def test_a_script_with_no_scene_is_told_the_bot_picked(settings, reg):
    script, _ = parse_long_script("Nobody cares anymore.", "EXMPL", settings)
    warnings, blocking = scene_problems(script, reg)
    assert not blocking and any("no [SCENE]" in w for w in warnings)


def test_a_capped_pose_named_twice_is_warned(settings, reg):
    raw = ("[SCENE: desk-front | pose=head-in-hands] One. Two three four. "
           "[SCENE: desk-front | pose=head-in-hands] Five.")
    script, _ = parse_long_script(raw, "EXMPL", settings)
    warnings, _ = scene_problems(script, reg)
    assert any("head-in-hands is in 2 scenes" in w for w in warnings)


def test_validation_carries_the_scene_warnings(settings, tmp_path):
    script, _ = parse_long_script("Nobody cares anymore.", "EXMPL", settings)
    warnings, _ = validate_long_script(script, set(), tmp_path, settings)
    assert any("no [SCENE]" in w for w in warnings)


def test_the_short_strips_a_scene(settings):
    from pipeline.models import SHORT_TAG_TYPES

    assert TagType.SCENE not in SHORT_TAG_TYPES


# --------------------------------------------------------------------------
# The plan: a scene cuts the beat of him it lands in, and holds.
# --------------------------------------------------------------------------

def _scene(t: float, room: str, pose: str = "", order: int = 0) -> Cue:
    return Cue(t=t, kind=CueKind.SCENE,
               payload={"order": order, "value": f"room/{room}",
                        "values": {"room": f"room/{room}",
                                   "pose": f"host/{pose}" if pose else ""}})


def test_a_scene_cuts_the_beat_of_him_on_its_word():
    segs, _ = plan_long_segments([_scene(0.0, "window-wide", "to-camera"),
                                  _scene(6.0, "desk-side", "holding-a-mug")],
                                 10.0)
    assert [(s.start, s.end) for s in segs] == [(0.0, 6.0), (6.0, 10.0)]
    assert segs[0].payload["scene"] == {"room": "room/window-wide",
                                        "pose": "host/to-camera"}
    assert segs[1].payload["scene"]["pose"] == "host/holding-a-mug"


def test_a_directed_beat_is_one_shot_however_long():
    """Splitting it every twelve seconds would cut his picture against
    itself; the planner says so instead when it runs long."""
    segs, warnings = plan_long_segments([_scene(0.0, "desk-front", "to-camera")],
                                        HOST_GAP_WARN_S + 5)
    assert len(segs) == 1 and segs[0].payload["scene"]
    assert any("one scene held" in w for w in warnings)


def test_a_scene_holds_across_the_cutaway():
    cues = [_scene(0.0, "desk-side", "holding-a-filing"),
            Cue(t=4.0, kind=CueKind.CLIP, payload={"value": "a"})]
    segs, _ = plan_long_segments(cues, 14.0)
    kinds = [s.kind for s in segs]
    assert kinds[0] == "host" and "clip" in kinds and kinds[-1] == "host"
    assert segs[-1].payload["scene"]["room"] == "room/desk-side"


def test_beats_before_the_first_scene_are_the_bot_s_as_ever():
    segs, _ = plan_long_segments([_scene(20.0, "doorway", "walking-out-of-frame")],
                                 26.0)
    assert "scene" not in segs[0].payload
    assert segs[-1].payload["scene"]["pose"] == "host/walking-out-of-frame"


def test_a_chapter_inside_a_scene_still_gets_its_cut():
    segs, _ = plan_long_segments([_scene(0.0, "desk-front", "to-camera")], 30.0,
                                 chapter_starts=[(0.0, "a"), (15.0, "b")])
    assert 15.0 in [s.start for s in segs]
    assert all(s.payload.get("scene") for s in segs)


def test_two_scenes_a_breath_apart_are_one_cut_to_the_later():
    segs, _ = plan_long_segments([_scene(0.0, "desk-front", "to-camera"),
                                  _scene(5.0, "desk-side", "holding-a-mug", 1),
                                  _scene(5.4, "read-close", "considering", 2)],
                                 12.0)
    assert [s.start for s in segs] == [0.0, 5.0]
    assert segs[1].payload["scene"]["room"] == "room/read-close"


def test_the_scene_in_force_is_the_latest_said():
    cues = [_scene(0.0, "desk-front"), _scene(10.0, "board-wide", order=1)]
    assert scene_in_force(cues, 5.0).payload["value"] == "room/desk-front"
    assert scene_in_force(cues, 10.0 - MIN_HOST_BEAT_S / 2).payload["value"] \
        == "room/board-wide"
    assert scene_in_force([], 5.0) is None


# --------------------------------------------------------------------------
# The prompt tells him.
# --------------------------------------------------------------------------

def test_both_long_prompts_carry_the_menu_and_the_short_does_not():
    from bot.prompts import payload_tokens

    assert "{{scene_catalogue}}" in payload_tokens("long_write")
    assert "{{scene_catalogue}}" in payload_tokens("update")
    assert "{{scene_catalogue}}" not in payload_tokens("short")
    for name in ("long_write", "update"):
        text = (ROOT / "templates" / f"master_prompt_{name}.md").read_text(
            encoding="utf-8")
        assert "{{scene_catalogue}}" in text and "[SCENE:" in text


# --------------------------------------------------------------------------
# The render shoots it.
# --------------------------------------------------------------------------

RAW = """[SCENE: window-wide | pose=to-camera] EXMPL is down sixty percent and nobody cares anymore. Which is when I start reading.
[SCENE: desk-side | pose=holding-a-mug] Here is what they actually do. Software for depots. Real customers, and not many of them.
[CHART: revenue] Revenue is a plateau wearing a growth costume. Five years of it, flat as a table.
[SCENE: desk-top-down] The contracts are on the desk. All of them, and they are short.
[SCENE: doorway | pose=walking-out-of-frame] See you at the next filing.

=== CHAPTERS ===
00:00 cold-open | nobody cares anymore
00:10 resigned-close | see you at the next filing"""


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    import shutil

    from config import Settings
    from pipeline.broll import ContentManager
    from pipeline.company_data import load_company_data
    from pipeline.render_long import render_long
    from pipeline.tts import TTSEngine

    tmp = tmp_path_factory.mktemp("scenes")
    settings = Settings(
        MOCK_MODE=True, long_min_chars=0,
        workspace_dir=tmp / "ws", cache_dir=tmp / "cache", state_dir=tmp / "state",
        long_width=640, long_height=360, _env_file=None)
    settings.ensure_runtime_dirs()
    script, _ = parse_long_script(RAW, "EXMPL", settings)
    ws = settings.workspace_dir / "EXMPL" / "scenes"
    ws.mkdir(parents=True)
    shutil.copy(ROOT / "fixtures" / "company_data" / "dennis_data.xlsx",
                ws / "dennis_data.xlsx")
    tts = TTSEngine(settings).synthesize(script.narration, "long")
    _out, manifest = render_long(script, tts, ws, settings,
                                 content=ContentManager(settings),
                                 as_of="2026-07-01",
                                 company_data=load_company_data(ws))
    return json.loads(manifest.read_text(encoding="utf-8"))


def test_the_render_shoots_the_writer_s_rooms_and_poses(rendered):
    rows = rendered["scenes"]
    assert rows, "no directed beat reached the manifest"
    shot = {r["room"].removesuffix("-16x9").split("-dusk")[0]: r for r in rows}
    assert shot["room/desk-side"]["shot"] == "host/holding-a-mug"
    assert shot["room/desk-top-down"]["shot"] == "room alone"
    motion = {m["segment"]: m for m in rendered["host_motion"]}
    directed = [r for r in rows if r["shot"].startswith("host/")]
    for r in directed:
        assert motion[r["segment"]]["directed"], r
    # The room alone has no figure in it.
    alone = [r["segment"] for r in rows if r["shot"] == "room alone"]
    assert alone and not [s for s in alone if s in motion]


def test_the_writer_opens_the_video(rendered):
    assert rendered["cold_open_room"].startswith("room/window-wide")


def test_the_lower_third_is_design_s_and_rides_his_beats(rendered):
    layers = [l for l in rendered["layers"] if l["name"] == "lower_third"]
    assert layers
    host = [(s["start"], s["end"]) for s in rendered["segments"]
            if s["kind"] == "host"]
    for l in layers:
        assert any(a - 1e-3 <= l["t_start"] and l["t_end"] <= b + 1e-3
                   for a, b in _runs(host)), l
    assert any(m["move"] == "slide-in" and m["shot_id"] == "lower_third"
               for m in rendered["moves"]["moves"])
    assert any(k.startswith("overlays/lower-third") for k in rendered["plates_used"])


def _runs(spans):
    out: list[list[float]] = []
    for a, b in sorted(spans):
        if out and abs(out[-1][1] - a) < 1e-6:
            out[-1][1] = b
        else:
            out.append([a, b])
    return out
