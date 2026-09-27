"""The room keeps moving behind him (item 19).

design's four room loops are content-free, so the ingest bakes them into the
rooms' own frames: a screen that dips and a lamp that flickers in every room
that has one, Christmas bulbs that twinkle and snow in the window on the
December twins, and rain in the window as a weather an episode may be shot
in. The renderers play a room as any looping plate.

The first half builds a registry of its own, because what is under test is
how a season and a weather are chosen and applied to a kit; the second reads
the installed kit, because what is under test there is what the ingest drew.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from pipeline.plates import (
    PALETTE_ROLES, REGISTRY_NAME, PlateError, at_episode_hour,
    current_episode_dressing, episode_dressing, episode_hour, load_plates,
    season_of_episode, weather_of_episode,
)

ROOT = Path(__file__).resolve().parents[1]
MOTION_JS = ROOT / "kit" / "engine" / "motion.js"

NIGHT = dict(zip(PALETTE_ROLES, ("#171D2A", "#1F2634", "#C6D2E0", "#F0B460",
                                 "#7FD4E8", "#8592A6", "#F07A5A", "#4A566A")))
DUSK = dict(zip(PALETTE_ROLES, ("#F2E8D4", "#E6D8C0", "#2A2036", "#D88A2F",
                                "#2F5FA8", "#685A48", "#A8243C", "#A08E74")))


def _loop(name: str, n: int = 12, *, front: bool = True, stem: str = "") -> list:
    """Twelve frames showing three pictures, the way a flicker installs."""
    pics = {3: "_f04", 8: "_f04", 7: "_f08", 9: "_f08"}
    out = []
    for i in range(n):
        tag = pics.get(i, "")
        f = {"tag": f"_f{i + 1:02d}", "png": f"{name}{stem}{tag}.png"}
        if front:
            f["front"] = f"{name}_front{stem}{tag}.png"
        out.append(f)
    return out


def _room(key: str, hour: str = "night", base: str = "", *, loops=("screen-flicker",),
          season: str = "", dressed_from: str = "", rain: bool = False) -> dict:
    name = key.split("/", 1)[1]
    frames = _loop(name)
    e = {"family": "room", "aspect": "16x9", "canvas": [1920, 1080],
         "exportScale": 2, "playback": "loop", "fps": 12, "frameCount": 12,
         "frames": frames, "loops": list(loops),
         "files": {"png": f"{name}.png", "baseIsFrame": "_f01"},
         "layers": {"back": f"{name}_back.png", "front": f"{name}_front.png",
                    "split": 20},
         "slots": {}, "seed": None, "duskSafe": True, "hostAnchor": False,
         "hour": hour, "atBaseHour": base or key}
    if season:
        e["season"], e["dressedFrom"] = season, dressed_from
    if rain:
        e["weathers"] = {"rain": {
            "loops": [*loops, "window-rain"], "playback": "loop", "fps": 12,
            "frameCount": 12, "frames": _loop(name, stem="_rain")}}
    return e


def _write_kit(root: Path) -> Path:
    assets: dict = {}
    for stem, twin, rain in (("room/desk", True, False),
                             ("room/window", True, True),
                             ("room/board", False, False)):
        key, dusk = f"{stem}-16x9", f"{stem}-dusk-16x9"
        assets[key] = _room(key, rain=rain)
        assets[dusk] = _room(dusk, "dusk", key, rain=rain)
        if twin:
            tkey, tdusk = f"{stem}-christmas-16x9", f"{stem}-christmas-dusk-16x9"
            loops = ("screen-flicker", "lights-twinkle")
            assets[tkey] = _room(tkey, loops=loops, season="christmas",
                                 dressed_from=key)
            assets[tdusk] = _room(tdusk, "dusk", tkey, loops=loops,
                                  season="christmas", dressed_from=key)
    raw = {
        "kit": "test", "generated": "now", "exportScale": 2,
        "hours": {"suffixes": {"night": "", "dusk": "-dusk"},
                  "episodes": ["night", "dusk"]},
        "palette": {"surface": "night-card", "roles": NIGHT},
        "palettes": {"night": NIGHT, "dusk": DUSK},
        "assets": assets,
        "roomRoles": {"talk": ["room/desk", "room/window", "room/board"]},
        "hostRoles": {}, "hostPoses": {}, "wardrobe": {},
        "chapterTypes": {}, "purposes": {},
        "motion": {"fps": 12, "moves": {}},
    }
    plates = root / "plates"
    plates.mkdir(parents=True, exist_ok=True)
    (plates / REGISTRY_NAME).write_text(json.dumps(raw), encoding="utf-8")
    return root


@pytest.fixture()
def kit(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(assets_dir=_write_kit(tmp_path / "assets"),
                           workspace_dir=tmp_path / "workspace")


def _dated(tmp_path: Path, day: str, ticker: str = "AAA") -> Path:
    ws = tmp_path / "workspace" / ticker / day
    ws.mkdir(parents=True, exist_ok=True)
    return ws


# ------------------------------------------------------------ the plates


def test_a_looping_room_plays_its_own_frames_at_the_move_rate(kit):
    room = load_plates(kit.assets_dir).get("room/desk-16x9")

    assert room.animated and not room.plays_once
    assert (room.frame_count, room.fps, room.loops) == (12, 12.0, ("screen-flicker",))
    # The front moves with the room: frame four's desk is frame four's.
    assert room.front_path(3).name == "desk-16x9_front_f04.png"
    assert room.front_path(0) == room.layer_path("front")


def test_december_shoots_every_angle_as_its_twin(kit):
    """Every angle or none: a dressed angle cut among plain ones flickers the
    decorations in and out, so a season is applied to the whole view."""
    plain = load_plates(kit.assets_dir).at("night")
    dressed = load_plates(kit.assets_dir).at("night", season="christmas")

    assert plain.get("room/desk-16x9").key == "room/desk-16x9"
    assert dressed.get("room/desk-16x9").key == "room/desk-christmas-16x9"
    assert dressed.assets["room/window-16x9"].key == "room/window-christmas-16x9"
    # Every angle the role can pick is dressed, and one with no twin is shot
    # as it is rather than dropped.
    picked = {dressed.room_for("talk", "16x9", seed=str(i)).key for i in range(40)}
    assert picked == {"room/desk-christmas-16x9", "room/window-christmas-16x9",
                      "room/board-16x9"}
    assert dressed.plate_at("room/desk-16x9", "night").season == "christmas"


def test_a_dusk_angle_dresses_as_the_dusk_twin(kit):
    dressed = load_plates(kit.assets_dir).at("dusk", season="christmas")

    assert dressed.get("room/desk-16x9").key == "room/desk-christmas-dusk-16x9"
    assert dressed.plate_at("room/desk-16x9", "dusk").key == \
        "room/desk-christmas-dusk-16x9"


def test_a_season_the_kit_draws_nothing_for_changes_nothing(kit):
    reg = load_plates(kit.assets_dir)
    assert reg.at("night", season="midsummer").get("room/desk-16x9").key == \
        "room/desk-16x9"


def test_rain_is_the_same_room_playing_its_rain_loop(kit):
    """Same key, same drawing, the rain loop as its frames: a renderer that
    asks the episode's registry for the room again gets it in the rain."""
    wet = load_plates(kit.assets_dir).at("night", weather="rain")
    room = wet.get("room/window-16x9")

    assert room.key == "room/window-16x9"
    assert room.weather == "rain"
    assert room.loops == ("screen-flicker", "window-rain")
    assert room.path.name == "window-16x9_rain.png"
    assert room.layers["front"] == "window-16x9_front_rain.png"
    assert room.front_path(3).name == "window-16x9_front_rain_f04.png"
    # A room with no window pane in shot is the room it always was.
    assert wet.get("room/desk-16x9").weather == ""


def test_a_twin_is_its_angle_to_the_rotation(kit):
    """A December video recorded the twins it shot. The next video steers off
    the ANGLES, or December's history would steer nothing."""
    reg = load_plates(kit.assets_dir)

    assert reg.undressed_key("room/desk-christmas-dusk-16x9") == "room/desk-16x9"
    for i in range(20):
        got = reg.room_for("talk", "16x9", seed=str(i), avoid={
            "room/desk-christmas-16x9", "room/board-16x9"})
        assert got.key == "room/window-16x9"


def test_verify_names_a_front_frame_that_is_missing(kit):
    reg = load_plates(kit.assets_dir)
    problems = reg.verify()
    assert any("missing front layer of _f04" in p and "desk-16x9_front_f04.png" in p
               for p in problems)
    assert any("missing rain frame" in p for p in problems)


# ------------------------------------------------------- the episode's


@pytest.mark.parametrize(("day", "season"), [
    ("2026-12-01", "christmas"), ("2026-12-31", "christmas"),
    ("2026-11-30", ""), ("2027-01-01", ""), ("scratch", ""),
])
def test_the_season_is_december_to_the_day(tmp_path, day, season):
    assert season_of_episode(tmp_path / "workspace" / "AAA" / day) == season


def test_rain_is_one_lot_per_video_and_never_in_december(tmp_path):
    days = [f"2026-{m:02d}-{d:02d}" for m in (3, 6, 10) for d in range(1, 29)]
    lots = [weather_of_episode(tmp_path / "AAA" / day, "AAA") for day in days]

    # The draft, the proof and the final of one video draw the same lot.
    assert lots == [weather_of_episode(tmp_path / "AAA" / day, "AAA")
                    for day in days]
    assert set(lots) == {"", "rain"}
    assert 0.1 < lots.count("rain") / len(lots) < 0.45
    assert {weather_of_episode(tmp_path / "AAA" / f"2026-12-{d:02d}", "AAA")
            for d in range(1, 32)} == {""}, "December snows; it never rains"
    assert weather_of_episode(tmp_path / "scratch", "AAA") == ""


def test_every_registry_loaded_inside_a_december_episode_is_dressed(kit, tmp_path):
    ws = _dated(tmp_path, "2026-12-03")
    with at_episode_hour(kit, ws, "AAA"):
        assert current_episode_dressing() == ("christmas", "")
        assert load_plates(kit.assets_dir).get("room/desk-16x9").season == "christmas"
    assert current_episode_dressing() == ("", "")
    assert load_plates(kit.assets_dir).get("room/desk-16x9").season == ""


def test_a_nested_episode_keeps_the_outer_dressing(kit, tmp_path):
    """A cover made inside a December render is a frame of that render, even
    when it is handed a workspace of its own."""
    ws = _dated(tmp_path, "2026-10-03")
    with episode_hour("night"), episode_dressing("christmas", ""):
        with at_episode_hour(kit, ws, "AAA"):
            assert current_episode_dressing() == ("christmas", "")


def test_a_rainy_episode_shoots_its_windows_in_the_rain(kit, tmp_path):
    ticker, day = next((t, d) for t in ("A", "B", "C", "D", "E", "F")
                       for d in ("2026-10-01", "2026-10-02", "2026-10-03")
                       if weather_of_episode(Path(t) / d, t) == "rain")
    ws = _dated(tmp_path, day, ticker)
    with at_episode_hour(kit, ws, ticker):
        assert load_plates(kit.assets_dir).get("room/window-16x9").weather == "rain"


def test_no_kit_and_a_december_date_is_still_no_crash(tmp_path):
    bare = SimpleNamespace(assets_dir=tmp_path / "none",
                           workspace_dir=tmp_path / "workspace")
    with at_episode_hour(bare, _dated(tmp_path, "2026-12-03"), "AAA") as hour:
        assert hour == ""
        with pytest.raises(PlateError, match="ingest_kit"):
            load_plates(bare.assets_dir)


# --------------------------------------------------------- the ingest


def _ingest():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_ingest_kit_loops", ROOT / "scripts" / "ingest_kit.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_a_room_loop_the_kit_does_not_publish_stops_the_install():
    ingest = _ingest()
    motion = {"fps": 12, "moves": {"screen-flicker": {"frames": 12, "playback": "loop"},
                                   "card-pin": {"frames": 9, "playback": "once"}}}
    ok = {"family": "room", "loops": ["screen-flicker"], "fps": 12, "frameCount": 12}
    assert ingest._room_loops(motion, {"room/a-16x9": ok}) == []

    problems = ingest._room_loops(motion, {
        "room/b-16x9": dict(ok, loops=["card-pin"]),
        "room/c-16x9": dict(ok, frameCount=18),
        "room/d-16x9": dict(ok, fps=2),
        "room/e-16x9": dict(ok, weathers={"rain": dict(ok, loops=["window-rain"])}),
    })
    assert len(problems) == 4
    assert "does not publish as a loop" in problems[0]
    assert "not a whole number" in problems[1]
    assert "the kit's moves play at 12" in problems[2]
    assert "room/e-16x9 in the rain" in problems[3]
    assert ingest._room_loops({}, {"room/a-16x9": ok}) != []


# ------------------------------------------------------- the render path


def test_a_room_loop_clip_draws_each_picture_once(tmp_path, monkeypatch):
    """Twelve frames showing three pictures, played at 30 fps, are three
    resizes of a 4K file and not thirty."""
    from pipeline import render_long

    drawn: list[int] = []
    written: dict = {}

    def encode(frames, fps, out):
        written.update(n=len(frames), fps=fps)
        out.write_bytes(b"clip")
        return out

    monkeypatch.setattr(render_long, "frames_to_alpha_clip", encode)
    indices = [int(i / 30 * 12) % 12 for i in range(30)]
    pictures = [0, 0, 0, 1, 0, 0, 0, 2, 1, 2, 0, 0]
    out = render_long._played_clip(
        [pictures[i] for i in indices],
        lambda i: drawn.append(i) or object(), 30, tmp_path / "loop.mov")

    assert sorted(drawn) == [0, 1, 2]
    assert written == {"n": 30, "fps": 30}
    assert out.read_bytes() == b"clip" and not list(tmp_path.glob("*.part*"))


# --------------------------------------------------- the installed kit


@pytest.fixture(scope="module")
def installed():
    from config import Settings

    try:
        return load_plates(Settings(_env_file=None).assets_dir)
    except PlateError as exc:
        pytest.skip(f"no design kit on this checkout: {exc}")


def _published(name: str) -> list[int]:
    """One of motion.js's frame tables, read as design wrote it."""
    m = re.search(rf"const {name} = \[([\d,\s]+)\]", MOTION_JS.read_text(encoding="utf-8"))
    return [int(x) for x in m.group(1).split(",")]


@pytest.mark.parametrize("stem", ["desk-front", "desk-front-b", "desk-front-low",
                                  "window-wall"])
def test_the_talk_rooms_flicker_behind_him_in_the_short(installed, stem):
    room = installed.get(f"room/{stem}-9x16")
    if not room.loops:
        pytest.skip("the installed kit predates the room loops; re-run the ingest")

    assert room.animated and room.fps == 12 and room.frame_count == 12
    assert "screen-flicker" in room.loops
    assert len({f.png for f in room.frames}) > 1


def test_the_flicker_is_motion_js_frame_for_frame(installed):
    """desk-front has a screen and a lit lamp: it changes on exactly the
    frames SCREEN_PULSE and LAMP_FLICKER mark, and on no other."""
    room = installed.get("room/desk-front-16x9")
    if not room.loops:
        pytest.skip("the installed kit predates the room loops; re-run the ingest")
    screen, lamp = _published("SCREEN_PULSE"), _published("LAMP_FLICKER")

    changed = [i for i, f in enumerate(room.frames) if f.png != room.frames[0].png]
    assert changed == [i for i in range(12) if screen[i] or lamp[i]]
    assert room.frames[3].png != room.frames[7].png, "the screen and the lamp are two moves"


def test_the_windows_are_the_only_rooms_with_weather(installed):
    """No window pane is inside any 9:16 crop, and doorway-wide's lit door is
    not a window, so rain is the long's, on the three window angles."""
    rooms = [p for k, p in sorted(installed.all_plates().items())
             if p.family == "room" and p.hour in ("", installed.base_hour)]
    if not any(p.loops for p in rooms):
        pytest.skip("the installed kit predates the room loops; re-run the ingest")

    wet = {p.key for p in rooms if p.weathers}
    assert wet == {"room/desk-wide-16x9", "room/window-wall-16x9",
                   "room/window-wide-16x9"}
    snowing = {p.key for p in rooms if "window-snow" in p.loops}
    assert snowing == {"room/desk-wide-christmas-16x9",
                       "room/window-wall-christmas-16x9",
                       "room/window-wide-christmas-16x9"}
    for p in rooms:
        if p.season:
            assert "lights-twinkle" in p.loops, p.key


def test_every_twin_names_the_angle_it_dresses(installed):
    twins = [p for p in installed.assets.values() if p.season]
    if not twins:
        pytest.skip("the installed kit predates the December switch; re-run the ingest")

    assert len(twins) == 28, "fourteen rooms at two aspects"
    for p in twins:
        assert p.season == "christmas"
        assert p.dressed_from in installed.assets, p.key
        assert installed.twins_of(p.dressed_from) == (p.key,)


def test_a_christmas_twin_is_reachable_through_its_angle(installed):
    from pipeline.gates import reachable_plates

    if not installed.twins_of("room/desk-front-16x9"):
        pytest.skip("the installed kit predates the December switch; re-run the ingest")
    routes = reachable_plates(installed)
    assert "room/desk-front-christmas-16x9" in routes["template"]
    assert "room/desk-front-christmas-9x16" in routes["template"]
