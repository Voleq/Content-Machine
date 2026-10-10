"""The 3D Dennis, pipeline side (item 47): which rooms he is drawn in, the
switch, and the conversation with the Blender process, with a stand-in
process that draws boxes, so none of it needs Blender."""
from __future__ import annotations

import json
import shutil
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from pipeline import dennis3d
from pipeline.render_common import RenderError


def _room(key: str, author: str = "room3d"):
    return SimpleNamespace(key=key, author=author)


def test_a_3d_room_names_its_angle_season_and_aspect():
    assert dennis3d.angle_of(_room("room/desk-front-16x9")) == ("desk-front", "plain", "16x9")
    assert dennis3d.angle_of(_room("room/desk-front-christmas-16x9")) == \
        ("desk-front", "christmas", "16x9")
    assert dennis3d.angle_of(_room("room/window-talk-9x16")) == ("window-talk", "plain", "9x16")
    assert dennis3d.angle_of(_room("room/doorway-wide-christmas-9x16")) == \
        ("doorway-wide", "christmas", "9x16")
    assert dennis3d.angle_of(_room("room/receipts-16x9", author="kit")) is None
    assert dennis3d.angle_of(None) is None


def test_the_switch_is_off_by_default_and_on_means_on(settings, monkeypatch):
    assert settings.dennis_3d == "off"
    assert not dennis3d.wanted(settings)
    monkeypatch.setattr(settings, "dennis_3d_python", f"{sys.executable} -c 'raise SystemExit(1)'")
    dennis3d._has_bpy.cache_clear()
    monkeypatch.setattr(dennis3d, "_has_bpy", lambda python: False)
    monkeypatch.setattr(settings, "dennis_3d", "auto")
    assert not dennis3d.wanted(settings), "auto without Blender draws the kit's Dennis"
    monkeypatch.setattr(settings, "dennis_3d", "on")
    with pytest.raises(RenderError, match="pip install bpy"):
        dennis3d.wanted(settings)


def test_on_names_what_the_blender_python_is_missing(settings, monkeypatch, tmp_path):
    """A Python with bpy and nothing else passed `import bpy`, then failed
    every shot of the render on the worker's next import."""
    fake = tmp_path / "python"
    fake.write_text("#!/bin/sh\necho \"ModuleNotFoundError: No module named 'PIL'\" >&2\n"
                    "exit 1\n", encoding="utf-8")
    fake.chmod(0o755)
    dennis3d._has_bpy.cache_clear()
    monkeypatch.setattr(settings, "dennis_3d_python", str(fake))
    monkeypatch.setattr(settings, "dennis_3d", "on")
    with pytest.raises(RenderError, match="No module named 'PIL'"):
        dennis3d.wanted(settings)


def test_the_worker_needs_no_pydantic():
    """`room3d/motion.py` reads the mouths off `pipeline.host`, in Blender's
    own Python, which the setup gives bpy and Pillow and nothing else."""
    import subprocess

    root = Path(dennis3d.__file__).resolve().parent.parent
    got = subprocess.run(
        [sys.executable, "-c", "import sys; sys.modules['pydantic'] = None; "
         "sys.path[:0] = ['room3d', '.']; import pipeline.host"],
        cwd=root, capture_output=True, text=True)
    assert got.returncode == 0, got.stderr


FAKE = textwrap.dedent('''
    import json, sys
    from pathlib import Path
    from PIL import Image
    for line in sys.stdin:
        line = line.strip()
        if not line:
            break
        job = json.loads(line)
        print("Fra:1 blender chatter", flush=True)
        if job["angle"] == "board":
            print("@@" + json.dumps({"ok": False, "error": "nobody stands in board"}), flush=True)
            continue
        out = Path(job["out"]); out.mkdir(parents=True, exist_ok=True)
        n = 1 if job.get("still") else max(int(round(job["duration"] * job["fps"])), 1)
        w, h = job["size"]
        # in the room for a cover he is on the right, but at the board on the left
        x0 = w * 5 // 8 if job.get("in_room") and "board" not in job["stance"] else w // 4
        for i in range(n):
            im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            im.paste((60, 90, 140, 255), (x0 + i, h // 4, x0 + w // 4 + i, h - 4))
            im.save(out / f"d_{i:04d}.png")
        (Path(job["out"]).parent / "calls").open("a").write(json.dumps(job.get("words")) + "\\n")
        (Path(job["out"]).parent / "job.json").write_text(json.dumps(job))
        window = [0.25, 0.1, 0.5, 0.35] if job.get("close") else None
        print("@@" + json.dumps({"ok": True, "frames": n, "out": str(out), "seconds": 0.1,
                                 "device": "CPU", "window": window}), flush=True)
''')


@pytest.fixture
def performer(settings, tmp_path, monkeypatch):
    if shutil.which("ffmpeg") is None:
        pytest.skip("needs ffmpeg")
    fake = tmp_path / "fake_worker.py"
    fake.write_text(FAKE, encoding="utf-8")
    monkeypatch.setattr(dennis3d, "WORKER", fake)
    monkeypatch.setattr(settings, "dennis_3d_python", sys.executable)
    p = dennis3d.Performer(settings, cache=tmp_path / "cache")
    yield p
    p.close()


def test_a_shot_comes_back_as_his_layer_and_is_drawn_once(performer, tmp_path):
    from pipeline.render_common import ffprobe_json

    words = [SimpleNamespace(word="So.", start=10.2, end=10.5),
             SimpleNamespace(word="Cash.", start=10.9, end=11.4)]
    room = _room("room/desk-front-16x9")
    layer = performer.shot(room, words, 10.0, 2.0, (320, 180), seed="EXMPL|4")
    info = ffprobe_json(layer)["streams"][0]
    assert (info["width"], info["height"]) == (320, 180)
    assert info["pix_fmt"] in ("rgba", "argb"), "he is a layer, the room shows round him"
    assert int(info["nb_frames"]) == 24, "two seconds at twelve drawings a second"
    calls = list((tmp_path / "cache").glob("*/calls"))
    assert len(calls) == 1
    assert '"start": 0.2' in calls[0].read_text(encoding="utf-8"), "words go over on the shot's own clock"
    # The same shot again is the file on disk, not a second drawing.
    assert performer.shot(room, words, 10.0, 2.0, (320, 180), seed="EXMPL|4") == layer
    assert len(calls[0].read_text(encoding="utf-8").splitlines()) == 1
    assert performer.shots[-1]["cached"] is True


def test_a_proof_draws_him_at_half_the_size_and_the_final_at_full(performer):
    """The proof's voice is not the final's, so the final draws him again to
    its own words: the proof's drawing is thrown away and costs a quarter."""
    from pipeline.render_common import ffprobe_json

    words = [SimpleNamespace(word="So.", start=0.2, end=0.5)]
    room = _room("room/desk-front-16x9")
    performer.draft = True
    proof = performer.shot(room, words, 0.0, 0.5, (320, 180), seed="p")
    info = ffprobe_json(proof)["streams"][0]
    assert (info["width"], info["height"]) == (160, 90)
    performer.draft = False
    final = performer.shot(room, words, 0.0, 0.5, (320, 180), seed="p")
    info = ffprobe_json(final)["streams"][0]
    assert final != proof and (info["width"], info["height"]) == (320, 180)


def test_a_shot_he_cannot_stand_in_fails_the_render(performer):
    with pytest.raises(RenderError, match="nobody stands in board"):
        performer.shot(_room("room/board-16x9"), [], 0.0, 1.0, (320, 180), seed="x")
    with pytest.raises(RenderError, match="not a 3D room"):
        performer.shot(_room("room/receipts-16x9", author="kit"), [], 0.0, 1.0, (320, 180),
                       seed="x")


def test_a_worker_that_dies_says_so(settings, tmp_path, monkeypatch):
    dead = tmp_path / "dead.py"
    dead.write_text("import sys\nsys.stderr.write('bpy exploded')\nsys.exit(3)\n", encoding="utf-8")
    monkeypatch.setattr(dennis3d, "WORKER", dead)
    monkeypatch.setattr(settings, "dennis_3d_python", sys.executable)
    with dennis3d.Performer(settings, cache=tmp_path / "c") as p:
        with pytest.raises(RenderError, match="bpy exploded"):
            p.shot(_room("room/desk-front-16x9"), [], 0.0, 1.0, (64, 36), seed="x")


def test_a_close_up_says_what_of_the_room_is_behind_him(performer):
    room = _room("room/desk-front-16x9")
    wide = performer.shot(room, [], 0.0, 1.0, (320, 180), seed="x")
    assert performer.window(wide) is None
    close = performer.shot(room, [], 0.0, 1.0, (320, 180), seed="x", close=True)
    assert close != wide, "the close-up is its own shot"
    assert performer.window(close) == (0.25, 0.1, 0.5, 0.35)
    # and it is remembered with the shot, so a cached close-up still knows
    assert performer.shot(room, [], 0.0, 1.0, (320, 180), seed="x", close=True) == close
    assert performer.window(close) == (0.25, 0.1, 0.5, 0.35)


def test_a_two_shot_tells_him_where_the_evidence_is(performer):
    import json

    layer = performer.shot(_room("room/panel-left-16x9"), [], 0.0, 1.0, (320, 180),
                           seed="x", stance="host/gesturing-at-plate", plate=(0.71, 0.5))
    job = json.loads((layer.parent / "job.json").read_text(encoding="utf-8"))
    assert job["plate"] == [0.71, 0.5] and job["stance"] == "host/gesturing-at-plate"


def test_his_extent_is_every_pixel_of_him_over_the_shot(performer):
    layer = performer.shot(_room("room/desk-front-16x9"), [], 0.0, 1.0, (320, 180), seed="x")
    x0, y0, x1, y1 = dennis3d.extent(layer, (320, 180))
    # the stand-in draws a box from x=80+i over twelve frames, rows 45..176
    assert abs(x0 - 80) <= 8 and abs(x1 - (160 + 11)) <= 8
    assert abs(y0 - 45) <= 8 and abs(y1 - 176) <= 8


def test_a_card_over_him_is_told_from_one_beside_him(performer):
    """The long's lower third sat on his face for the whole turn to the screen."""
    layer = performer.shot(_room("room/desk-front-16x9"), [], 0.0, 1.0, (320, 180), seed="x")
    # the stand-in's box: x 80..171, rows 45..176
    assert dennis3d.under(layer, (320, 180), (0, 0, 60, 40)) is False
    assert dennis3d.under(layer, (320, 180), (100, 50, 140, 90)) is True
    assert dennis3d.under(layer, (320, 180), (0, 0, 70, 36)) is False
    assert dennis3d.under(layer, (320, 180), (0, 0, 70, 36), margin=16) is True


# --------------------------------------------------------------------------
# The short (3 Oct: "the shorts should be on this engine as well")
# --------------------------------------------------------------------------

def _short_cut(room_author: str = "room3d"):
    """The turn as `build_layers` leaves it: the room, the drawn close-up,
    the desk in front of him and the caption; and a kit with that room."""
    from pipeline.compose import BuildResult, Layer

    room = SimpleNamespace(key="room/desk-front-b-9x16", family="room", author=room_author)
    other = SimpleNamespace(key="room/board-9x16", family="room", author="room3d")
    plates = {p.key: p for p in (room, other)}
    reg = SimpleNamespace(get=plates.get, all_plates=lambda: dict(plates))
    layers = [Layer("the-turn:plate", "plate", "the-turn", 10.0, 12.0, 0, 0, 1080, 1920,
                    entry_key=room.key, frame_count=12, fps=12, loops=True, z=10),
              Layer("the-turn:host:close-up", "host", "the-turn", 10.0, 12.0,
                    -1021, -14, 3097, 2679, entry_key="host/close-up", z=40),
              Layer("the-turn:front", "front", "the-turn", 10.0, 12.0, 0, 0, 1080, 1920,
                    entry_key=room.key, z=45),
              Layer("the-turn:caption", "caption", "the-turn", 10.0, 12.0, 108, 1395, 864, 85),
              Layer("hook:plate", "plate", "hook", 0.0, 10.0, 0, 0, 1080, 1920,
                    entry_key="shorts/hook-card")]
    return BuildResult(layers=layers, spans=[], frame=(1080, 1920), aspect="9x16"), reg


@pytest.fixture
def short_3d(settings, performer, monkeypatch):
    import pipeline.host as host

    monkeypatch.setattr(dennis3d, "_has_bpy", lambda python: True)
    monkeypatch.setattr(settings, "dennis_3d", "on")
    monkeypatch.setattr(settings, "dennis_3d_fps", 12)
    monkeypatch.setattr(host, "host_shot", lambda reg, key: SimpleNamespace(
        is_framing=key.endswith("close-up")))
    return settings, performer


def test_the_short_s_close_up_is_his_3d_layer_over_a_blown_up_room(short_3d):
    import json

    from pipeline.render_short import perform_3d

    settings, performer = short_3d
    result, reg = _short_cut()
    words = [SimpleNamespace(word="Plus", start=10.1, end=10.4),
             SimpleNamespace(word="squeeze.", start=10.5, end=11.0),
             SimpleNamespace(word="Revenue", start=12.2, end=12.6)]
    did = perform_3d(result, reg, words, settings, aspect="9x16", scale=4 / 3,
                     seed="sha", performer=performer)
    kinds = {l.kind: l for l in result.layers if l.shot_id == "the-turn"}
    assert "host" not in kinds and "front" not in kinds, \
        "no drawn Dennis, and the desk is already in front of him in his layer"
    him, room = kinds["host3d"], kinds["plate"]
    assert (him.x, him.y, him.w, him.h) == (0, 0, 1080, 1920), "his layer is the room's size"
    assert him.entry_key == "host/close-up" and him.z == 40
    assert (him.fps, him.loops) == (12, False) and him.frame_count == 24 and him.moves
    assert (Path(him.path) / "d_0023.png").exists()
    assert room.window == (0.25, 0.1, 0.5, 0.35), "behind him, the piece the lens sees"
    assert "the-turn:caption" in [l.name for l in result.layers]
    job = json.loads((Path(him.path).parent / "job.json").read_text(encoding="utf-8"))
    assert job["aspect"] == "9x16" and job["close"] and job["stance"] == "host/close-up"
    assert job["size"] == [1440, 2560], "drawn at the file's size, not the layout's"
    assert [w["word"] for w in job["words"]] == ["Plus", "squeeze."], "only his own line"
    assert did == [{"shot": "the-turn", "room": "room/desk-front-b-9x16",
                    "stance": "host/close-up", "close_up": True, "frames": 24}]


def test_a_drawn_room_in_the_kit_keeps_the_drawn_dennis_in_every_shot(short_3d, monkeypatch):
    from pipeline.render_short import perform_3d

    settings, performer = short_3d
    result, reg = _short_cut(room_author="kit-model.rooms")
    before = list(result.layers)
    with pytest.raises(RenderError, match="ingest_kit"):
        perform_3d(result, reg, [], settings, aspect="9x16", scale=1.0, seed="s",
                   performer=performer)
    monkeypatch.setattr(settings, "dennis_3d", "auto")
    assert perform_3d(result, reg, [], settings, aspect="9x16", scale=1.0, seed="s",
                      performer=performer) == []
    assert result.layers == before
    # and off is off, whatever the kit
    monkeypatch.setattr(settings, "dennis_3d", "off")
    result, reg = _short_cut()
    assert perform_3d(result, reg, [], settings, aspect="9x16", scale=1.0, seed="s",
                      performer=performer) == []
    assert "host" in {l.kind for l in result.layers}


def test_the_short_draws_his_frames_over_the_blown_up_room(tmp_path, settings):
    from pipeline.compose import Layer
    from pipeline.render_short import _Cache, _draw_layer

    # The room: left half red, right half blue, drawn at twice the canvas.
    art = Image.new("RGBA", (200, 400), (200, 30, 30, 255))
    art.paste((30, 30, 200, 255), (100, 0, 200, 400))
    cache = _Cache(settings, reg=SimpleNamespace(get=lambda k: None))
    cache._draw = lambda key, frame_i, values: art
    room = Layer("r", "plate", "t", 0.0, 2.0, 0, 0, 100, 200, entry_key="room/x",
                 window=(0.5, 0.0, 1.0, 0.5))
    canvas = Image.new("RGBA", (100, 200))
    _draw_layer(canvas, room, 0.5, cache, reg=None, settings=settings, lost={})
    assert canvas.getpixel((50, 100))[:3] == (30, 30, 200), "the right half, blown up"

    frames = tmp_path / "frames"
    frames.mkdir()
    for i in range(3):
        im = Image.new("RGBA", (100, 200), (0, 0, 0, 0))
        im.paste((250, 250, 250, 255), (10 + 30 * i, 50, 30 + 30 * i, 150))
        im.save(frames / f"d_{i:04d}.png")
    him = Layer("h", "host3d", "t", 0.0, 2.0, 0, 0, 100, 200, path=frames,
                frame_count=3, fps=12, loops=False, z=40)
    for t, x in ((0.0, 15), (1 / 12 + 0.01, 45), (1.5, 75)):   # past the end: the last
        canvas = Image.new("RGBA", (100, 200), (0, 0, 0, 255))
        _draw_layer(canvas, him, t, cache, reg=None, settings=settings, lost={})
        assert canvas.getpixel((x, 100))[:3] == (250, 250, 250), t
        assert canvas.getpixel((x, 20))[:3] == (0, 0, 0)


def test_his_frames_come_back_from_the_layer_when_the_folder_went(performer):
    layer = performer.shot(_room("room/desk-front-9x16"), [], 0.0, 1.0, (64, 112), seed="x")
    folder = dennis3d.Performer.frames(layer)
    n = len(list(folder.glob("d_*.png")))
    shutil.rmtree(folder)
    again = dennis3d.Performer.frames(layer)
    assert again == folder and len(list(again.glob("d_*.png"))) == n == 12
    assert (again / "d_0000.png").exists()


# --------------------------------------------------------------------------
# The covers
# --------------------------------------------------------------------------

def _cover(monkeypatch, settings, room, performer, key="host/arms-crossed"):
    import pipeline.thumbnail as th

    monkeypatch.setattr(th, "_room", lambda *a, **k: (Image.new("RGB", th.WIDE, (40, 40, 40)), room))
    drawn = Image.new("RGBA", (200, 500), (220, 20, 20, 255))
    monkeypatch.setattr(th, "_host", lambda *a, **k: (drawn, SimpleNamespace(
        key=key, floor_line_y=480, pose=SimpleNamespace(canvas=(200, 500)))))
    return th._compose(settings, ticker="EXMPL", metric="P/S: 40x", kicker="the deep dive",
                       size=th.WIDE, orient="wide", performer=performer)


def test_a_3d_video_s_cover_is_a_frame_of_the_video_when_the_type_leaves_him_clear(
        performer, settings, monkeypatch):
    import json

    room = SimpleNamespace(key="room/desk-front-16x9", author="room3d", floor_line_y=None,
                           canvas=(2560, 1440), delivered=(2560, 1440))
    img = _cover(monkeypatch, settings, room, performer)
    px = img.load()
    # in the room the stand-in is x 800..1120, y 180..716 of 1280x720, and
    # the cover lays him there, the desk and his shadow in his own layer
    assert px[810, 450] == (60, 90, 140) and px[1110, 700] == (60, 90, 140)
    assert px[790, 450] != (60, 90, 140), "on his own spot, not moved"
    assert not any(px[x, y] == (220, 20, 20) for x in range(0, 1280, 8) for y in range(0, 720, 8))
    jobs = [json.loads(f.read_text(encoding="utf-8")) for f in performer.cache.glob("*/job.json")]
    assert len(jobs) == 1, "one drawing of him"
    assert jobs[0]["still"] and jobs[0]["in_room"] and jobs[0]["size"] == [1280, 720]
    assert jobs[0]["stance"] == "host/arms-crossed"


def test_a_3d_video_s_cover_moves_him_clear_of_the_type_when_his_spot_is_under_it(
        performer, settings, monkeypatch):
    import json

    room = SimpleNamespace(key="room/desk-front-16x9", author="room3d", floor_line_y=None,
                           canvas=(2560, 1440), delivered=(2560, 1440))
    img = _cover(monkeypatch, settings, room, performer, key="host/at-board")
    px = img.load()
    # at the board he would be x 320..640, under the ticker; cut to himself
    # instead, he goes in the cover's right-hand column, feet where they were
    assert px[1280 - 47 - 160, 450] == (60, 90, 140), "the 3D Dennis is on the cover"
    assert px[1280 - 47 - 160, 720 - 3] != (60, 90, 140)
    assert px[330, 450] != (60, 90, 140)
    assert not any(px[x, y] == (220, 20, 20) for x in range(0, 1280, 8) for y in range(0, 720, 8))
    jobs = [json.loads(f.read_text(encoding="utf-8")) for f in performer.cache.glob("*/job.json")]
    assert sorted(bool(j.get("in_room")) for j in jobs) == [False, True]
    assert all(j["still"] and j["size"] == [1280, 720] for j in jobs)


def test_a_3d_video_s_cover_over_a_drawn_room_goes_without_him(performer, settings,
                                                                monkeypatch):
    room = SimpleNamespace(key="room/receipts-16x9", author="kit", floor_line_y=None,
                           canvas=(2560, 1440), delivered=(2560, 1440))
    img = _cover(monkeypatch, settings, room, performer)
    px = img.load()
    assert not any(px[x, y] in ((220, 20, 20), (60, 90, 140))
                   for x in range(0, 1280, 8) for y in range(0, 720, 8))


def test_the_storyboard_shows_the_3d_dennis_when_the_render_will(short_3d, monkeypatch):
    import pipeline.storyboard as sb

    settings, performer = short_3d
    room = SimpleNamespace(key="room/desk-front-16x9", family="room", author="room3d")
    reg = SimpleNamespace(all_plates=lambda: {room.key: room}, room_for=lambda *a, **k: room)
    monkeypatch.setattr(settings, "cache_dir", performer.cache.parent)
    monkeypatch.setattr(sb, "_DENNIS_3D", {})
    him = sb._dennis_3d(settings, reg)
    # the stand-in's box, cut to itself
    assert him is not None and him.size == (160, 266) and him.getpixel((80, 80))[3] == 255
    monkeypatch.setattr(sb, "_DENNIS_3D", {})
    monkeypatch.setattr(settings, "dennis_3d", "off")
    assert sb._dennis_3d(settings, reg) is None, "the kit's Dennis, as the render"


# --------------------------------------------------------------------------
# A whole long, with the stand-in worker
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def long_3d(tmp_path_factory):
    """One long rendered with the 3D Dennis on, every shot of him drawn by
    the stand-in, so the filtergraphs his layers go into really run."""
    import json

    from config import Settings
    from pipeline.broll import ContentManager
    from pipeline.company_data import load_company_data
    from pipeline.parser_long import parse_long_script
    from pipeline.plates import load_plates
    from pipeline.render_long import render_long
    from pipeline.tts import TTSEngine
    from tests.test_render_long import RAW

    if shutil.which("ffmpeg") is None:
        pytest.skip("needs ffmpeg")
    tmp = tmp_path_factory.mktemp("long_3d")
    settings = Settings(MOCK_MODE=True, workspace_dir=tmp / "ws", cache_dir=tmp / "cache",
                        state_dir=tmp / "state", long_width=640, long_height=360,
                        long_min_chars=0, DENNIS_3D="on", DENNIS_3D_PYTHON=sys.executable,
                        _env_file=None)
    settings.ensure_runtime_dirs()
    if dennis3d.drawn_rooms(load_plates(settings.assets_dir), "16x9"):
        pytest.skip("the kit's long rooms are not the 3D room (run the kit ingest)")
    fake = tmp / "fake_worker.py"
    fake.write_text(FAKE, encoding="utf-8")
    script, _ = parse_long_script(RAW, "EXMPL", settings)
    ws = settings.workspace_dir / "EXMPL" / "test"
    ws.mkdir(parents=True)
    Image.new("RGB", (1200, 700), (14, 18, 26)).save(ws / "income_statement.png")
    shutil.copy(Path(__file__).resolve().parents[1] / "fixtures" / "company_data"
                / "dennis_data.xlsx", ws / "dennis_data.xlsx")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(dennis3d, "WORKER", fake)
        mp.setattr(dennis3d, "_has_bpy", lambda python: True)
        tts = TTSEngine(settings).synthesize(script.narration, "long")
        out, manifest = render_long(script, tts, ws, settings,
                                    content=ContentManager(settings), as_of="2026-07-01",
                                    company_data=load_company_data(ws))
    return settings, tts, out, json.loads(manifest.read_text(encoding="utf-8"))


def test_a_3d_long_draws_every_shot_of_him_in_3d_and_none_drawn(long_3d):
    from pipeline.render_common import ffprobe_json

    settings, tts, out, manifest = long_3d
    shots = manifest["dennis3d"]
    assert shots, "he was in no shot"
    assert any(s.get("two_shot") for s in shots), "the both-true plate stands him beside it"
    # never one drawn shot among the 3D ones
    assert all(m.get("dennis3d") for m in manifest["host_motion"]), manifest["host_motion"]
    jobs = [json.loads(f.read_text(encoding="utf-8"))
            for f in (settings.cache_dir / "dennis3d").glob("*/job.json")]
    assert len(jobs) == len(shots) and all(j["size"] == [640, 360] for j in jobs)
    assert any("plate" in j for j in jobs), "the two-shot told him where the evidence is"
    info = ffprobe_json(out)
    assert abs(float(info["format"]["duration"]) - tts.duration_s) < 1.0

