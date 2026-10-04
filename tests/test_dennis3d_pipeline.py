"""The 3D Dennis, pipeline side (item 47): which rooms he is drawn in, the
switch, and the conversation with the Blender process, with a stand-in
process that draws boxes, so none of it needs Blender."""
from __future__ import annotations

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
        n = max(int(round(job["duration"] * job["fps"])), 1)
        w, h = job["size"]
        for i in range(n):
            im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            im.paste((60, 90, 140, 255), (w // 4 + i, h // 4, w // 2 + i, h - 4))
            im.save(out / f"d_{i:04d}.png")
        (Path(job["out"]).parent / "calls").open("a").write(json.dumps(job["words"]) + "\\n")
        print("@@" + json.dumps({"ok": True, "frames": n, "out": str(out), "seconds": 0.1,
                                 "device": "CPU"}), flush=True)
''')


@pytest.fixture
def performer(settings, tmp_path, monkeypatch):
    if shutil.which("ffmpeg") is None:
        pytest.skip("needs ffmpeg")
    fake = tmp_path / "fake_worker.py"
    fake.write_text(FAKE)
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
    assert '"start": 0.2' in calls[0].read_text(), "words go over on the shot's own clock"
    # The same shot again is the file on disk, not a second drawing.
    assert performer.shot(room, words, 10.0, 2.0, (320, 180), seed="EXMPL|4") == layer
    assert len(calls[0].read_text().splitlines()) == 1
    assert performer.shots[-1]["cached"] is True


def test_a_shot_he_cannot_stand_in_fails_the_render(performer):
    with pytest.raises(RenderError, match="nobody stands in board"):
        performer.shot(_room("room/board-16x9"), [], 0.0, 1.0, (320, 180), seed="x")
    with pytest.raises(RenderError, match="not a 3D room"):
        performer.shot(_room("room/receipts-16x9", author="kit"), [], 0.0, 1.0, (320, 180),
                       seed="x")


def test_a_worker_that_dies_says_so(settings, tmp_path, monkeypatch):
    dead = tmp_path / "dead.py"
    dead.write_text("import sys\nsys.stderr.write('bpy exploded')\nsys.exit(3)\n")
    monkeypatch.setattr(dennis3d, "WORKER", dead)
    monkeypatch.setattr(settings, "dennis_3d_python", sys.executable)
    with dennis3d.Performer(settings, cache=tmp_path / "c") as p:
        with pytest.raises(RenderError, match="bpy exploded"):
            p.shot(_room("room/desk-front-16x9"), [], 0.0, 1.0, (64, 36), seed="x")
