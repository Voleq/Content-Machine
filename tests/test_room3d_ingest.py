"""The 3D room installed under the kit's own room names (item 36)."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("ingest_kit", ROOT / "scripts" / "ingest_kit.py")
ingest = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ingest)

SIZE = (96, 54)
# The kit's flicker, as its frames name pictures: rest, a dip on 4, a deeper
# one on 8, both again on 9 and 10.
KIT_FLICKER = "AAABAAACBCAA"
CHRISTMAS = ("_t0", "_t0_dip", "_t1", "_t1_dip2", "_t2", "_t2_dip", "_t2_dip2")


def _kit_room(name: str, hour: str, *, season: str = "", loops=("screen-flicker",),
              rain: bool = False) -> dict:
    letters = KIT_FLICKER if not season else "ABCDEFGHIJKL"
    pngs = {c: f"{name}.png" if c == "A" else f"{name}_f{letters.index(c) + 1:02d}.png"
            for c in letters}
    frames = [{"tag": f"_f{i + 1:02d}", "png": pngs[c], "svg": None,
               "front": f"{name}_front.png"} for i, c in enumerate(letters)]
    e = {"family": "room", "aspect": "16x9", "hour": hour, "season": season or None,
         "angle": "desk-wide" + (f"-{season}" if season else ""),
         "delivered": list(SIZE), "canvas": [48, 27], "loops": list(loops),
         "playback": "loop", "fps": 12, "frameCount": 12, "frames": frames,
         "files": {"png": frames[0]["png"], "svg": None, "baseIsFrame": "_f01"},
         "layers": {"back": f"{name}_back.png", "split": 17, "front": f"{name}_front.png"},
         "slots": {"title": {"role": "title", "x": 1, "y": 1, "w": 10, "h": 4},
                   "host-anchor": {"role": "host-anchor", "x": 0, "y": 0, "w": 1, "h": 1}},
         "typeRoles": {"title": {"size": 76}}}
    if rain:
        e["weathers"] = {"rain": {"loops": ["screen-flicker", "window-rain"],
                                  "playback": "loop", "fps": 12, "frameCount": 12,
                                  "frames": [dict(f, png=f"{name}_rain_f{i + 1:02d}.png")
                                             for i, f in enumerate(frames)]}}
    return e


def _renders(tmp: Path) -> Path:
    """A rooms.json for desk-wide and its December twin, tiny and flat."""
    r = tmp / "renders"
    r.mkdir()
    rooms = {}
    win = np.zeros(SIZE[::-1], np.uint8)
    win[5:30, 50:90] = 255
    front = np.zeros(SIZE[::-1], np.uint8)
    front[38:, 10:40] = 255
    board = np.zeros(SIZE[::-1], np.uint8)
    board[4:20, 4:30] = 255
    for stem, tags in (("desk-wide", ("", "_dip", "_dip2")), ("desk-wide-christmas", CHRISTMAS)):
        states = []
        for i, tag in enumerate(tags):
            png = f"{stem}{tag}.png"
            Image.new("RGB", SIZE, (40 + 20 * i, 60, 90)).save(r / png)
            states.append({"tag": tag, "png": png})
        masks = {}
        for k, m in (("window", win), ("front", front), ("board", board)):
            Image.fromarray(m).save(r / f"{stem}_mask_{k}.png")
            masks[k] = f"{stem}_mask_{k}.png"
        rooms[stem] = {
            "angle": "desk-wide", "season": "christmas" if "christmas" in stem else "plain",
            "anchor": {"x": 30, "y": 8, "w": 5, "h": 15},
            "title": {"x": 2, "y": 2, "w": 12, "h": 5,
                      "groundBox": {"x": 1, "y": 1, "w": 14, "h": 7}},
            "camera": {}, "headCovered": 0.01, "masks": masks, "states": states,
            "surfaces": {"board": {"quad": [[2, 2], [15, 2], [15, 10], [2, 10]],
                                   "paper": [238, 241, 242], "size": [1.46, 0.98]}},
        }
    (r / "rooms.json").write_text(json.dumps(rooms), encoding="utf-8")
    return r


def _install(tmp: Path):
    built = {"assets": {
        "room/desk-wide-16x9": _kit_room("desk-wide-16x9", "night", rain=True),
        "room/desk-wide-dusk-16x9": _kit_room("desk-wide-dusk-16x9", "dusk", rain=True),
        "room/desk-wide-christmas-16x9": _kit_room(
            "desk-wide-christmas-16x9", "night", season="christmas",
            loops=("screen-flicker", "lights-twinkle", "window-snow")),
        "room/board-16x9": dict(_kit_room("board-16x9", "night", loops=()),
                                angle="board"),
    }}
    drawn = tmp / "drawn"
    (drawn / "room").mkdir(parents=True)
    problems = ingest._rooms_3d(built, drawn, _renders(tmp))
    return built["assets"], drawn / "room", problems


def _px(p: Path) -> np.ndarray:
    return np.asarray(Image.open(p))


def test_every_room_is_the_render_under_the_kit_name(tmp_path):
    assets, room, problems = _install(tmp_path)
    assert any("board-16x9" in p and "rendered no board" in p for p in problems), \
        "a room with no render must be a problem, not a flat fallback"
    e = assets["room/desk-wide-16x9"]
    assert e["author"] == ingest.ROOM3D_AUTHOR
    pngs = [f["png"] for f in e["frames"]]
    # The dips land on the kit's frames: 4 and 9 one picture, 8 and 10 another.
    assert pngs[3] == pngs[8] != pngs[0] and pngs[7] == pngs[9] != pngs[3]
    assert len(set(pngs)) == 3 and e["files"]["png"] == pngs[0] == "desk-wide-16x9.png"
    for f in e["frames"]:
        assert Image.open(room / f["png"]).size == SIZE
    # The anchor and the slate are the 3D camera's.
    assert e["slots"]["host-anchor"]["h"] == 15 and e["floorLineY"] == 23
    assert e["slots"]["title"]["groundBox"]["w"] == 14
    assert "back" not in (e["layers"] or {})


def test_dusk_is_the_night_render_under_the_same_files(tmp_path):
    assets, _, _ = _install(tmp_path)
    night, dusk = assets["room/desk-wide-16x9"], assets["room/desk-wide-dusk-16x9"]
    assert [f["png"] for f in dusk["frames"]] == [f["png"] for f in night["frames"]]
    assert [f["front"] for f in dusk["frames"]] == [f["front"] for f in night["frames"]]


def test_the_front_is_the_frame_cut_by_the_mask_with_straight_alpha(tmp_path):
    assets, room, _ = _install(tmp_path)
    e = assets["room/desk-wide-16x9"]
    front = _px(room / e["frames"][3]["front"])
    frame = _px(room / e["frames"][3]["png"])
    mask = _px(tmp_path / "renders" / "desk-wide_mask_front.png")
    assert (front[..., 3] == mask).all(), "the alpha is not the mask (squared?)"
    on = mask > 0
    assert (front[..., :3][on] == frame[on]).all()
    assert (front[..., :3][~on] == 0).all()
    assert e["layers"]["front"] == e["frames"][0]["front"]


def test_rain_and_snow_fall_only_on_the_glass_and_the_same_every_install(tmp_path):
    assets, room, _ = _install(tmp_path)
    win = _px(tmp_path / "renders" / "desk-wide_mask_window.png") > 0
    e = assets["room/desk-wide-16x9"]
    rain = e["weathers"]["rain"]
    assert rain["frameCount"] == 12 and rain["loops"] == ["screen-flicker", "window-rain"]
    plain = _px(room / e["frames"][0]["png"])
    wet = _px(room / rain["frames"][0]["png"])
    assert (wet[~win] == plain[~win]).all() and (wet[win] != plain[win]).any()
    # The rain dips with the screen on the same frames as the dry room.
    assert rain["frames"][3]["front"] == e["frames"][3]["front"]

    xmas = assets["room/desk-wide-christmas-16x9"]
    snowy = _px(room / xmas["frames"][0]["png"])
    flat = _px(tmp_path / "renders" / "desk-wide-christmas_t0.png")
    assert (snowy[~win] == flat[~win]).all() and (snowy[win] != flat[win]).any()
    assert len({f["png"] for f in xmas["frames"]}) == 12, "the snow stopped falling"

    first = hashlib.sha256((room / rain["frames"][1]["png"]).read_bytes()).hexdigest()
    again = tmp_path / "again"
    again.mkdir()
    _, room2, _ = _install(again)
    assert hashlib.sha256((room2 / rain["frames"][1]["png"]).read_bytes()).hexdigest() == first


def test_december_dips_on_its_plain_rooms_frames(tmp_path):
    """The twin is processed after its plain room has been rewritten, and still
    reads the kit's flicker."""
    assets, _, problems = _install(tmp_path)
    assert not [p for p in problems if "christmas" in p]
    xmas = assets["room/desk-wide-christmas-16x9"]
    fronts = [f["front"] for f in xmas["frames"]]
    # t0 rest x3, t0 dip; t1 rest x3, t1 dip2; t2 dip, t2 dip2, t2 rest x2.
    assert fronts[0] == fronts[1] == fronts[2] != fronts[3]
    assert fronts[4] == fronts[5] == fronts[6] != fronts[7]
    assert len(set(fronts)) == 7


def test_the_board_is_writable(tmp_path):
    assets, room, _ = _install(tmp_path)
    w = assets["room/desk-wide-16x9"]["writable"]
    assert set(w) == {"board"} and w["board"]["paper"] == [238, 241, 242]
    assert Image.open(room / w["board"]["mask"]).size == SIZE


def test_the_plan_never_asks_for_a_state_the_render_skipped():
    states = dict.fromkeys(CHRISTMAS)
    levels = [0, 0, 0, 1, 0, 0, 0, 2, 1, 2, 0, 0]
    plan = ingest._room3d_plan(("screen-flicker", "lights-twinkle"), levels, 12, states)
    assert [t for t, _, _ in plan] == ["_t0", "_t0", "_t0", "_t0_dip", "_t1", "_t1", "_t1",
                                       "_t1_dip2", "_t2_dip", "_t2_dip2", "_t2", "_t2"]
    # A level the render has no state for falls back to the bulbs at rest.
    off = copy.copy(levels)
    off[0] = 2
    assert ingest._room3d_plan(("screen-flicker", "lights-twinkle"), off, 12, states)[0][0] == "_t0"
