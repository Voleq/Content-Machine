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

import numpy as np
import pytest
from PIL import Image

from pipeline import dennis3d
from pipeline.render_common import RenderError, run_ffmpeg


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
        if job.get("op") == "pile":
            if job["angle"] == "desk-front":
                print("@@" + json.dumps({"ok": False, "error": "the pile is not in shot at desk-front"}), flush=True)
                continue
            if job["angle"] == "board":
                print("@@" + json.dumps({"ok": False, "error": "it broke"}), flush=True)
                continue
            out = Path(job["out"]); out.parent.mkdir(parents=True, exist_ok=True)
            w, h = job["size"]
            im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            im.paste((200, 30, 30, 255), (w // 8, h // 2, w // 4, h * 3 // 4))
            im.save(out)
            (out.parent / "job.json").write_text(json.dumps(job))
            print("@@" + json.dumps({"ok": True, "out": str(out), "seconds": 0.1, "device": "CPU"}), flush=True)
            continue
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
        push = None
        if job.get("push"):
            hs = [1 - (1 - 1 / job["push"]["z"]) * i / max(n - 1, 1) for i in range(n)]
            push = [[0.5 - h / 2, 0.5 - h / 2, 0.5 + h / 2, 0.5 + h / 2] for h in hs]
        print("@@" + json.dumps({"ok": True, "frames": n, "out": str(out), "seconds": 0.1,
                                 "device": "CPU", "window": window, "push": push}),
              flush=True)
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
    assert int(info["nb_frames"]) == 2 * performer.settings.dennis_3d_fps, \
        "two seconds at his drawing rate"
    calls = list((tmp_path / "cache").glob("*/calls"))
    assert len(calls) == 1
    assert '"start": 0.2' in calls[0].read_text(encoding="utf-8"), "words go over on the shot's own clock"
    # The same shot again is the file on disk, not a second drawing.
    assert performer.shot(room, words, 10.0, 2.0, (320, 180), seed="EXMPL|4") == layer
    assert len(calls[0].read_text(encoding="utf-8").splitlines()) == 1
    assert performer.shots[-1]["cached"] is True


def test_gpu_lines_are_the_default_and_a_change_to_them_draws_him_again(performer,
                                                                      monkeypatch):
    """Valentin chose the lines found in the GPU render's passes (11 Oct).
    A shot drawn so is keyed on what finds them (room3d/lines.py): after a
    change to it the shot is drawn again, not served as it was drawn before."""
    words = [SimpleNamespace(word="So.", start=0.2, end=0.5)]
    room = _room("room/desk-front-16x9")
    assert performer.settings.dennis_3d_lines == "passes"
    first = performer.shot(room, words, 0.0, 0.5, (320, 180), seed="lines")
    assert json.loads((first.parent / "job.json").read_text(encoding="utf-8"))["lines"] == "passes"
    assert performer.shot(room, words, 0.0, 0.5, (320, 180), seed="lines") == first
    monkeypatch.setattr(dennis3d, "_lines_digest", lambda: "lines.py changed")
    assert performer.shot(room, words, 0.0, 0.5, (320, 180), seed="lines") != first
    monkeypatch.setattr(performer.settings, "dennis_3d_lines", "freestyle")
    traced = performer.shot(room, words, 0.0, 0.5, (320, 180), seed="lines")
    assert "lines" not in json.loads((traced.parent / "job.json").read_text(encoding="utf-8"))


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


def test_a_push_in_says_what_of_the_room_is_behind_him_on_every_frame(performer):
    room = _room("room/desk-wide-16x9")
    still = performer.shot(room, [], 0.0, 1.0, (320, 180), seed="x")
    assert dennis3d.pushed(still) is None
    push = {"z": 1.9, "t0": 0.2, "t1": 0.9}
    layer = performer.shot(room, [], 0.0, 1.0, (320, 180), seed="x", push=push)
    assert layer != still, "the push-in is its own shot"
    got = dennis3d.pushed(layer)
    assert got is not None and len(got) == performer.settings.dennis_3d_fps
    assert got[0] == (0.0, 0.0, 1.0, 1.0) and got[-1][2] - got[-1][0] < 0.6
    job = json.loads((layer.parent / "job.json").read_text(encoding="utf-8"))
    assert job["push"] == push
    # remembered with the shot
    assert performer.shot(room, [], 0.0, 1.0, (320, 180), seed="x", push=push) == layer
    assert dennis3d.pushed(layer) == got


def test_a_two_shot_tells_him_where_the_evidence_is(performer):
    import json

    layer = performer.shot(_room("room/panel-left-16x9"), [], 0.0, 1.0, (320, 180),
                           seed="x", stance="host/gesturing-at-plate", plate=(0.71, 0.5))
    job = json.loads((layer.parent / "job.json").read_text(encoding="utf-8"))
    assert job["plate"] == [0.71, 0.5] and job["stance"] == "host/gesturing-at-plate"


def test_his_extent_is_every_pixel_of_him_over_the_shot(performer):
    layer = performer.shot(_room("room/desk-front-16x9"), [], 0.0, 1.0, (320, 180), seed="x")
    x0, y0, x1, y1 = dennis3d.extent(layer, (320, 180))
    # the stand-in draws a box from x=80+i over a second of frames, rows 45..176
    n = performer.settings.dennis_3d_fps
    assert abs(x0 - 80) <= 8 and abs(x1 - (160 + n - 1)) <= 8
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
    assert Path(him.path).name == "layer.mov", "read off his layer, not unpacked"
    assert not (Path(him.path).parent / "frames").exists()
    assert room.window == (0.25, 0.1, 0.5, 0.35), "behind him, the piece the lens sees"
    assert "the-turn:caption" in [l.name for l in result.layers]
    job = json.loads((Path(him.path).parent / "job.json").read_text(encoding="utf-8"))
    assert job["aspect"] == "9x16" and job["close"] and job["stance"] == "host/close-up"
    assert job["size"] == [1440, 2560], "drawn at the file's size, not the layout's"
    assert [w["word"] for w in job["words"]] == ["Plus", "squeeze."], "only his own line"
    assert did == [{"shot": "the-turn", "room": "room/desk-front-b-9x16",
                    "stance": "host/close-up", "close_up": True, "frames": 24,
                    "start": 10.0, "events": []}]


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
    # His layer as the performer writes it: PNG frames in an RGBA .mov,
    # read straight off it (item 23).
    mov = tmp_path / "layer.mov"
    run_ffmpeg(["-framerate", "12", "-i", str(frames / "d_%04d.png"),
                "-c:v", "png", "-pix_fmt", "rgba", "-f", "mov", str(mov)])
    shutil.rmtree(frames)
    assert dennis3d.Performer.frame_count(mov) == 3
    him = Layer("h", "host3d", "t", 0.0, 2.0, 0, 0, 100, 200, path=mov,
                frame_count=3, fps=12, loops=False, z=40)
    # In order, past the end (the last frame holds), and back to the top.
    for t, x in ((0.0, 15), (1 / 12 + 0.01, 45), (1.5, 75), (0.0, 15)):
        canvas = Image.new("RGBA", (100, 200), (0, 0, 0, 255))
        _draw_layer(canvas, him, t, cache, reg=None, settings=settings, lost={})
        assert canvas.getpixel((x, 100))[:3] == (250, 250, 250), t
        assert canvas.getpixel((x, 20))[:3] == (0, 0, 0)
    cache.close()


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
    # three longs gone public before this one: three read 10-Ks on his floor
    from pipeline.youtube import RECORDS_FILE

    (settings.state_dir / RECORDS_FILE).write_text(json.dumps([
        {"ticker": t, "video_id": t, "title": t, "privacy": "public", "workdate": d,
         "fmt": "long"} for t, d in (("AAA", "2026-06-01"), ("BBB", "2026-06-08"),
                                     ("CCC", "2026-06-15"))]), encoding="utf-8")
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
    # THE WIDE ROOMS OPEN A CHAPTER, and go in to him there.
    from pipeline.plates import load_plates
    from pipeline.render_long import WIDE_SHARE

    reg = load_plates(settings.assets_dir)
    desk = reg.get("room/desk-front-16x9").slot("host-anchor").h
    wide = [s for s in shots
            if reg.get(s["room"]).slot("host-anchor").h < WIDE_SHARE * desk]
    assert wide, "the cold open is a wide room"
    assert all(s.get("push_in") for s in wide if not s.get("two_shot")), wide
    assert len(wide) <= len(manifest.get("chapters") or []) + 1, wide
    info = ffprobe_json(out)
    # the voice, then the end screen held on him (V3)
    assert abs(float(info["format"]["duration"]) - manifest["duration"]) < 1.0
    assert manifest["voice_end"] == pytest.approx(tts.duration_s, abs=0.01)
    end = manifest["dennis3d"][-1]
    assert end["segment"] == len(manifest["segments"]) - 1 and not end["close_up"]
    # the fake slides a pixel a frame, across the boxes' side by the end: the
    # check reads where he went, not where the room said he stands
    assert manifest["end_screen"]["side"] and manifest["end_screen"]["clear"] is False



def test_a_3d_long_lays_the_read_10ks_on_its_rooms_and_his_shadow_falls_on_them(long_3d):
    settings = long_3d[0]
    root = settings.cache_dir / "dennis3d"
    piles = [json.loads(f.read_text(encoding="utf-8")) for f in root.glob("piles/*/job.json")]
    assert piles and {j["pile"] for j in piles} == {3}
    assert all(j["size"] == [2560, 1440] for j in piles), "drawn as big as the room was"
    shots = [json.loads(f.read_text(encoding="utf-8")) for f in root.glob("*/job.json")]
    assert shots and all(j.get("pile") == 3 for j in shots)
    written = list((settings.workspace_dir / "EXMPL" / "test").rglob("written/**/*.png"))
    red = [f for f in written
           if (np.asarray(Image.open(f).convert("RGB")) == (200, 30, 30)).all(axis=2).any()]
    assert red, "no room went up with the pile on it"


def test_he_wears_the_winter_jumper_from_december_to_february(tmp_path):
    """V12: the video's day picks his jumper, as it picks the season."""
    from pipeline.plates import jumper_of_episode

    for day, want in (("2026-12-01", "winter"), ("2027-01-15", "winter"),
                      ("2027-02-28", "winter"), ("2027-03-01", ""),
                      ("2026-11-30", ""), ("2026-07-04", "")):
        assert jumper_of_episode(tmp_path / "EXMPL" / day) == want, day
    assert jumper_of_episode(tmp_path / "scratch") == ""


def test_a_shot_in_the_winter_jumper_is_drawn_apart_from_the_navy(performer):
    """The jumper rides in the job only when he wears it, so the navy keeps
    every shot already drawn, and a winter video draws its own."""
    from pipeline.plates import episode_jumper

    words = [SimpleNamespace(word="So.", start=0.2, end=0.5)]
    room = _room("room/desk-front-16x9")
    navy = performer.shot(room, words, 0.0, 0.5, (320, 180), seed="jumper")
    assert "jumper" not in json.loads((navy.parent / "job.json").read_text(encoding="utf-8"))
    with episode_jumper("winter"):
        winter = performer.shot(room, words, 0.0, 0.5, (320, 180), seed="jumper")
        cover = performer.still(room, (320, 180), seed="jumper")
    assert winter != navy
    assert json.loads((winter.parent / "job.json").read_text(encoding="utf-8"))["jumper"] == "winter"
    assert json.loads((cover.parent / "job.json").read_text(encoding="utf-8"))["jumper"] == "winter"


def _lit_room(key: str, hour: str = "night", weather: str = ""):
    return SimpleNamespace(key=key, author="room3d", hour=hour, weather=weather)


def test_he_is_lit_as_the_room_s_picture_behind_him(performer):
    """V10: at dusk the dusk sky lights him, in the rain the rain's, and in
    December the bulbs; at night, dry, the job is as it was, so every shot
    of him at night keeps its cache."""
    assert dennis3d.light_of(_lit_room("room/desk-front-16x9")) == ""
    assert dennis3d.light_of(_lit_room("room/desk-front-16x9", weather="rain")) == "_rain"
    assert dennis3d.light_of(_lit_room("room/desk-front-16x9", "dusk", "rain")) == "_dusk_rain"
    assert dennis3d.light_of(_lit_room("room/desk-front-christmas-16x9", "dusk", "snow")) == "_t0_dusk"
    assert dennis3d.light_of(_lit_room("room/desk-front-christmas-16x9")) == "_t0"
    words = [SimpleNamespace(word="So.", start=0.2, end=0.5)]
    night = performer.shot(_lit_room("room/desk-front-16x9"), words, 0.0, 0.5, (320, 180), seed="lit")
    dusk = performer.shot(_lit_room("room/desk-front-16x9", "dusk"), words, 0.0, 0.5, (320, 180),
                          seed="lit")
    job = lambda layer: json.loads((layer.parent / "job.json").read_text(encoding="utf-8"))  # noqa: E731
    assert "light" not in job(night) and "pile" not in job(night)
    assert job(dusk)["light"] == "_dusk" and dusk != night


def test_the_10k_pile_is_drawn_once_an_angle_and_he_throws_his_shadow_on_it(performer):
    """V12: the read 10-Ks are drawn alone, lit as the room's picture is,
    once for each angle and count; every shot of him has them on the floor."""
    room = _lit_room("room/board-wide-16x9", "dusk")
    assert performer.pile_layer(room, (320, 180)) is None, "no public long, no pile"
    performer.pile = 7
    png = performer.pile_layer(room, (320, 180))
    job = json.loads((png.parent / "job.json").read_text(encoding="utf-8"))
    assert (job["op"], job["pile"], job["angle"], job["light"]) == ("pile", 7, "board-wide", "_dusk")
    assert Image.open(png).size == (320, 180)
    assert json.loads((performer.pile_layer(room, (3840, 2160)).parent / "job.json")
                      .read_text(encoding="utf-8"))["size"] == [2560, 1440], \
        "never drawn bigger than the room was rendered"
    stamp = png.stat().st_mtime_ns
    assert performer.pile_layer(room, (320, 180)) == png and png.stat().st_mtime_ns == stamp
    words = [SimpleNamespace(word="So.", start=0.2, end=0.5)]
    layer = performer.shot(room, words, 0.0, 0.5, (320, 180), seed="pile")
    assert json.loads((layer.parent / "job.json").read_text(encoding="utf-8"))["pile"] == 7
    assert performer.pile_layer(_room("room/receipts-16x9", author="kit"), (320, 180)) is None


def test_a_pile_out_of_shot_is_asked_once_and_one_that_fails_is_left_out(performer):
    room = _lit_room("room/desk-front-16x9")
    performer.pile = 3
    assert performer.pile_layer(room, (320, 180)) is None
    assert list(performer.cache.glob("piles/*/not-in-shot")), "not in shot is remembered"
    assert performer.pile_layer(_lit_room("room/board-16x9"), (320, 180)) is None, \
        "a pile that could not be drawn stopped the render"


def test_a_word_under_way_at_his_cut_is_his_to_say(short_3d):
    """Cuts are snapped to the frame grid, so one written on a word's start
    often lands just after it, and that word was left out of his line: he
    opened the shot with his mouth shut while his voice spoke."""
    import json

    from pipeline.render_short import perform_3d

    settings, performer = short_3d
    result, reg = _short_cut()
    words = [SimpleNamespace(word="Earlier.", start=9.0, end=9.8),
             SimpleNamespace(word="Plus", start=9.98, end=10.4),
             SimpleNamespace(word="squeeze.", start=10.5, end=11.0)]
    perform_3d(result, reg, words, settings, aspect="9x16", scale=4 / 3,
               seed="sha", performer=performer)
    him = next(l for l in result.layers if l.kind == "host3d")
    job = json.loads((Path(him.path).parent / "job.json").read_text(encoding="utf-8"))
    assert [w["word"] for w in job["words"]] == ["Plus", "squeeze."]
    assert job["words"][0]["start"] < 0 < job["words"][0]["end"]


def test_a_drawn_shot_is_stored_once(performer):
    """The worker's frames stayed beside the layer made of them: every shot
    stored twice, a hundred gigabytes and more on a long at 1080p. The layer
    is kept, and the short reads its frames straight off it."""
    layer = performer.shot(_room("room/desk-front-9x16"), [], 0.0, 1.0, (64, 112), seed="y")
    assert layer.exists() and not (layer.parent / "frames").exists()
    assert dennis3d.Performer.frame_count(layer) == performer.settings.dennis_3d_fps


LOOK_RAW = """[SCENE: desk-side | pose=holding-a-mug] EXMPL is down sixty percent and nobody cares anymore. Which is when I start reading the filings.
[SCENE: board | pose=close-up] Here is what they actually do. Software for depots, real customers, and not many of them.
[SCENE: desk-front | pose=to-camera] See you at the next filing, where the contracts are all short.

=== CHAPTERS ===
00:00 cold-open | nobody cares anymore
00:12 resigned-close | see you at the next filing"""


@pytest.fixture(scope="module")
def look_long(tmp_path_factory):
    """A small long's preview with the 3D Dennis on: a beat at the desk, then
    his close-up asked for at the board, which nobody stands in."""
    from config import Settings
    from pipeline.broll import ContentManager
    from pipeline.company_data import load_company_data
    from pipeline.parser_long import parse_long_script
    from pipeline.plates import load_plates
    from pipeline.render_long import render_long
    from pipeline.tts import TTSEngine

    if shutil.which("ffmpeg") is None:
        pytest.skip("needs ffmpeg")
    tmp = tmp_path_factory.mktemp("look_long")
    settings = Settings(MOCK_MODE=True, workspace_dir=tmp / "ws", cache_dir=tmp / "cache",
                        state_dir=tmp / "state", long_width=640, long_height=360,
                        long_min_chars=0, DENNIS_3D="on", DENNIS_3D_PYTHON=sys.executable,
                        _env_file=None)
    settings.ensure_runtime_dirs()
    if dennis3d.drawn_rooms(load_plates(settings.assets_dir), "16x9"):
        pytest.skip("the kit's long rooms are not the 3D room (run the kit ingest)")
    fake = tmp / "fake_worker.py"
    fake.write_text(FAKE, encoding="utf-8")
    script, _ = parse_long_script(LOOK_RAW, "EXMPL", settings)
    ws = settings.workspace_dir / "EXMPL" / "look"
    ws.mkdir(parents=True)
    shutil.copy(Path(__file__).resolve().parents[1] / "fixtures" / "company_data"
                / "dennis_data.xlsx", ws / "dennis_data.xlsx")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(dennis3d, "WORKER", fake)
        mp.setattr(dennis3d, "_has_bpy", lambda python: True)
        tts = TTSEngine(settings).synthesize(script.narration, "long")
        render_long(script, tts, ws, settings, content=ContentManager(settings),
                    preview=True, as_of="2026-07-01", company_data=load_company_data(ws))
    jobs = [json.loads(f.read_text(encoding="utf-8"))
            for f in (settings.cache_dir / "dennis3d").glob("*/job.json")]
    return settings, jobs


def test_he_turns_to_where_his_close_up_at_the_board_is_shot(look_long):
    """His close-up at the board is taken where he talks, but the beat before
    it had him turn to the board's camera as it ended, a look to a camera the
    cut never went to (scan, 24 Oct 2026)."""
    _settings, jobs = look_long
    close = [j for j in jobs if j.get("close")]
    assert close and all(j["angle"] != "board" for j in close), close
    assert all(j.get("next") != "board" for j in jobs), [j.get("next") for j in jobs]


def test_a_preview_draws_him_at_the_preview_s_rate(look_long):
    """A preview is 15 frames a second and drew him at 30: half the shots'
    Blender time spent on frames the preview drops."""
    settings, jobs = look_long
    assert jobs and all(j["fps"] == settings.preview_fps for j in jobs), \
        [j["fps"] for j in jobs]


def _blender_python() -> str | None:
    """Blender's own Python where this box has one (his install has it at
    /opt/blender-py), else None and the test below is skipped."""
    import os
    import subprocess

    for p in (os.environ.get("DENNIS_3D_PYTHON"), "/opt/blender-py/bin/python"):
        if p and Path(p).exists() and subprocess.run(
                [p, "-c", "import bpy"], capture_output=True, timeout=120).returncode == 0:
            return p
    return None


def test_switching_his_lines_keeps_his_collection_counted(tmp_path):
    """His bench logged "ID user decrement error: GRdennis ... 0 <= 0" (25 Oct
    2026): a line set's collection is not counted when it is set but is
    uncounted when the set is freed, so every switch of DENNIS_3D_LINES took
    the scene's own count of his collection to nought and then below."""
    import subprocess

    py = _blender_python()
    if py is None:
        pytest.skip("needs Blender's Python (DENNIS_3D_PYTHON)")
    room3d = Path(__file__).resolve().parents[1] / "room3d"
    script = tmp_path / "linesets.py"
    script.write_text(textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {str(room3d)!r})
        import bpy
        import build
        bpy.ops.wm.read_factory_settings(use_empty=True)
        him = bpy.data.collections.new("dennis")
        bpy.context.scene.collection.children.link(him)
        fs = bpy.context.view_layer.freestyle_settings
        for _ in range(3):
            build.clear_linesets(fs)
            for name in ("outline", "detail"):
                ls = fs.linesets.new(name)
                ls.select_by_collection = True
                ls.collection = him
        print("USERS", him.users)
    """), encoding="utf-8")
    got = subprocess.run([py, str(script)], capture_output=True, text=True, timeout=300)
    said = got.stdout + got.stderr
    assert "USERS 1" in got.stdout, said
    assert "decrement error" not in said
