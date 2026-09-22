"""One hour per episode, on every plate in it.

The kit draws every plate at every hour it lights the set at: the same author,
seed and slots in another colour table. A video is at one of them. These build
a registry of their own rather than reading the installed kit, because what is
under test is how an hour is chosen and applied, and that has to hold for any
kit that draws more than one.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from pipeline.plates import (
    PALETTE_ROLES, REGISTRY_NAME, PlateError, at_episode_hour,
    current_episode_hour, episode_hour, hour_of_episode, load_plates,
    recorded_hour,
)

NIGHT = dict(zip(PALETTE_ROLES, ("#171D2A", "#1F2634", "#C6D2E0", "#F0B460",
                                 "#7FD4E8", "#8592A6", "#F07A5A", "#4A566A")))
DUSK = dict(zip(PALETTE_ROLES, ("#F2E8D4", "#E6D8C0", "#2A2036", "#D88A2F",
                                "#2F5FA8", "#685A48", "#A8243C", "#A08E74")))


def _entry(key: str, hour: str = "", base: str = "", **extra) -> dict:
    family = key.split("/", 1)[0]
    aspect = next((a for a in ("16x9", "9x16") if key.endswith(a)), "")
    canvas = [1920, 1080] if aspect != "9x16" else [1080, 1920]
    name = key.split("/", 1)[1]
    e = {"family": family, "aspect": aspect, "canvas": canvas,
         "exportScale": 2, "playback": "static", "frameCount": 1,
         "frames": [{"tag": "", "png": f"{name}.png"}],
         "files": {"png": f"{name}.png"}, "slots": {}, "seed": 7}
    if hour:
        e["hour"], e["atBaseHour"] = hour, base
    e.update(extra)
    return e


def _both(key: str, dusk_key: str, **extra) -> dict:
    return {key: _entry(key, "night", "", **extra),
            dusk_key: _entry(dusk_key, "dusk", key, **extra)}


def _write_kit(root: Path, episodes=("night", "dusk")) -> Path:
    assets: dict = {}
    assets |= _both("cards/term-16x9", "cards/term-dusk-16x9")
    assets |= _both("room/wide-16x9", "room/wide-dusk-16x9", seed=None,
                    duskSafe=True, hostAnchor=False)
    assets |= _both("room/lamp-16x9", "room/lamp-dusk-16x9", seed=None,
                    duskSafe=False, hostAnchor=False)
    for pose in ("host/medium", "host/medium-talk", "host/medium-glance-left",
                 "host/head-in-hands"):
        assets |= _both(pose, f"{pose}-dusk", framing="medium")
    raw = {
        "kit": "test", "generated": "now", "exportScale": 2,
        "hours": {"suffixes": {"night": "", "dusk": "-dusk"},
                  "episodes": list(episodes)},
        "palette": {"surface": "night-card", "roles": NIGHT},
        "palettes": {"night": NIGHT, "dusk": DUSK},
        "assets": assets,
        "roomRoles": {"talk": ["room/wide", "room/lamp"]},
        "hostRoles": {"to-camera": ["host/medium"],
                      "open": ["host/head-in-hands", "host/medium"]},
        "hostPoses": {"host/head-in-hands": {"limit": 1, "talks": False}},
        "wardrobe": {},
        "chapterTypes": {"_universal": {"plates": ["room/", "host/"]},
                         "the-numbers": {"plates": ["cards/term"]}},
        "purposes": {},
    }
    plates = root / "plates"
    plates.mkdir(parents=True, exist_ok=True)
    (plates / REGISTRY_NAME).write_text(json.dumps(raw), encoding="utf-8")
    return root


@pytest.fixture()
def kit(tmp_path: Path) -> SimpleNamespace:
    assets = _write_kit(tmp_path / "assets")
    return SimpleNamespace(assets_dir=assets,
                           workspace_dir=tmp_path / "workspace")


# ------------------------------------------------------------- the view


def test_the_library_is_the_base_hour_and_a_view_swaps_its_art(kit):
    reg = load_plates(kit.assets_dir)
    dusk = reg.at("dusk")

    assert reg.keys() == dusk.keys()
    assert "cards/term-dusk-16x9" not in reg.keys(), \
        "an hour is a variant of a plate, never a plate of its own"
    assert reg.get("cards/term-16x9").key == "cards/term-16x9"
    # Every route to a plate lands on the hour: `get` and `assets` alike.
    assert dusk.get("cards/term-16x9").key == "cards/term-dusk-16x9"
    assert dusk.assets["cards/term-16x9"].key == "cards/term-dusk-16x9"
    assert dusk.require("cards/term-16x9").hour == "dusk"
    # A night key asked of a dusk view is still the dusk drawing.
    assert dusk.get("cards/term-dusk-16x9").key == "cards/term-dusk-16x9"


def test_a_view_colours_by_its_own_hour(kit):
    reg = load_plates(kit.assets_dir)
    assert reg.colour_hex("ground").upper() == NIGHT["ground"].upper()
    assert reg.at("dusk").colour_hex("ground").upper() == DUSK["ground"].upper()


def test_an_hour_the_kit_does_not_draw_is_refused(kit):
    with pytest.raises(PlateError, match="draws no 'noon' hour"):
        load_plates(kit.assets_dir).at("noon")


def test_curation_named_by_the_base_key_still_answers_for_the_hour(kit):
    dusk = load_plates(kit.assets_dir).at("dusk")

    assert dusk.host_limit("host/head-in-hands-dusk") == 1
    assert dusk.chapter_allows("the-numbers", "cards/term-dusk-16x9")
    assert dusk.host_strip("host/medium-dusk", "talk").key == "host/medium-talk-dusk"
    assert dusk.base_keys({"cards/term-dusk-16x9", "room/wide-16x9"}) == {
        "cards/term-16x9", "room/wide-16x9"}


def test_a_dusk_host_glances_like_a_night_one(kit):
    from pipeline.host import looking_at, shots

    dusk = load_plates(kit.assets_dir).at("dusk")
    shot = next(s for s in shots(dusk, "to-camera"))
    turned = looking_at(dusk, shot, "left")

    assert turned.pose.key == "host/medium-glance-left-dusk"


def test_an_angle_kept_to_its_own_light_is_not_shot_at_dusk(kit):
    reg = load_plates(kit.assets_dir)

    assert reg.angles_for("talk", "16x9", "night") == [
        "room/wide-16x9", "room/lamp-16x9"]
    assert reg.angles_for("talk", "16x9", "dusk") == ["room/wide-16x9"]
    for seed in "abcdefgh":
        room = reg.at("dusk").room_for("talk", "16x9", seed=seed, episode="X")
        assert room.key == "room/wide-dusk-16x9"


# ------------------------------------------------------ the render's hour


def test_every_registry_loaded_inside_an_episode_is_at_its_hour(kit):
    assert current_episode_hour() == ""
    with episode_hour("dusk"):
        assert current_episode_hour() == "dusk"
        assert load_plates(kit.assets_dir).get("room/wide-16x9").hour == "dusk"
        with episode_hour("night"):
            assert load_plates(kit.assets_dir).get("room/wide-16x9").hour == "night"
        assert load_plates(kit.assets_dir).hour == "dusk"
    assert current_episode_hour() == ""
    assert load_plates(kit.assets_dir).get("room/wide-16x9").key == "room/wide-16x9"


def test_a_view_answers_every_hour_question_with_its_own_hour(kit):
    """Nothing downstream can choose a second hour and cut dusk into night."""
    with episode_hour("dusk"):
        reg = load_plates(kit.assets_dir)
        assert {reg.hour_for(e) for e in ("A", "B", "C", "D", "E", "F")} == {"dusk"}


def test_an_earlier_pass_of_the_video_decides_its_hour(kit, tmp_path):
    """The proof and the final are one video. A render between them must not
    move the rotation and put the final at the other hour."""
    ws = tmp_path / "workspace" / "AAA" / "2026-09-22"
    ws.mkdir(parents=True)
    (ws / "render_long_proof_manifest.json").write_text(
        json.dumps({"hour": "dusk", "plates_used": []}), encoding="utf-8")

    assert recorded_hour(ws) == "dusk"
    assert hour_of_episode(kit, ws, "AAA") == "dusk"


def test_a_recorded_hour_the_rotation_dropped_is_chosen_again(tmp_path):
    kit = SimpleNamespace(
        assets_dir=_write_kit(tmp_path / "assets", episodes=("night",)),
        workspace_dir=tmp_path / "workspace")
    ws = tmp_path / "workspace" / "AAA" / "2026-09-22"
    ws.mkdir(parents=True)
    (ws / "render_long_manifest.json").write_text(
        json.dumps({"hour": "dusk"}), encoding="utf-8")

    assert hour_of_episode(kit, ws, "AAA") == "night"


def test_a_fresh_video_picks_off_the_hours_recent_videos_were_shot_at(kit, tmp_path):
    reg = load_plates(kit.assets_dir)
    ep = next(e for e in (f"T{i}" for i in range(50))
              if reg.hour_for(e) == "dusk")
    old = tmp_path / "workspace" / "OLD" / "2026-09-21"
    old.mkdir(parents=True)
    (old / "render_long_manifest.json").write_text(
        json.dumps({"plates_used": ["room/wide-dusk-16x9"]}), encoding="utf-8")
    ws = tmp_path / "workspace" / ep / "2026-09-22"
    ws.mkdir(parents=True)

    assert hour_of_episode(kit, ws, ep) == "night"


def test_a_nested_episode_keeps_the_outer_hour(kit, tmp_path):
    """A cover made inside a render is a frame of that render."""
    ws = tmp_path / "workspace" / "AAA" / "2026-09-22"
    ws.mkdir(parents=True)
    with episode_hour("dusk"):
        with at_episode_hour(kit, ws, "ANY") as hour:
            assert hour == "dusk"


def test_no_kit_means_no_hour_rather_than_a_crash(tmp_path):
    bare = SimpleNamespace(assets_dir=tmp_path / "none",
                           workspace_dir=tmp_path / "workspace")
    with at_episode_hour(bare, tmp_path, "AAA") as hour:
        assert hour == ""
        with pytest.raises(PlateError, match="ingest_kit"):
            load_plates(bare.assets_dir)


def test_segment_workers_inherit_the_hour(kit):
    """The segment pool used to start each job in an empty context, so a
    fallback still drawn from a worker came out at the base hour."""
    import contextvars
    from concurrent.futures import ThreadPoolExecutor

    def hour_in_worker() -> str:
        return load_plates(kit.assets_dir).hour

    with episode_hour("dusk"), ThreadPoolExecutor(max_workers=1) as pool:
        bare = pool.submit(hour_in_worker).result()
        carried = pool.submit(contextvars.copy_context().run,
                              hour_in_worker).result()
    assert (bare, carried) == ("night", "dusk")
