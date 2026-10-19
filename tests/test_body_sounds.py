"""A10: his clothes heard when the 3D Dennis turns or moves an arm."""

import shutil
import sys
import textwrap
from collections import namedtuple
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "room3d"))

import motion  # noqa: E402

from pipeline import dennis3d  # noqa: E402
from pipeline.sound import (BODY_GAIN_REL_DB, BODY_KEY, BODY_TURN_DB,  # noqa: E402
                            EFFECT_KEYS, BodyMove, body_cues, body_moves)

W = namedtuple("W", "word start end")
FPS = 30


def _perf(n: int, **cols) -> motion.Performance:
    return motion.Performance(fps=FPS, frames=n, channels={
        k: list(v) for k, v in cols.items()})


def _ramp(n: int, at: int, to: float, frames: int = 6) -> list[float]:
    return [0.0 if i < at else to * min((i - at) / frames, 1.0) for i in range(n)]


def test_events_from_channels():
    n = 120
    got = motion.body_events(_perf(n, **{
        "head.z": _ramp(n, 30, 12), "hips.z": _ramp(n, 30, 12),
        "shoulder.L.x": _ramp(n, 100, -40), "elbow.L.x": _ramp(n, 100, -30)}))
    assert [e["kind"] for e in got] == ["turn", "arm"]
    # on the frame the move sets off, never ahead of it
    assert 30 / FPS <= got[0]["t"] <= 32 / FPS
    assert 100 / FPS <= got[1]["t"] <= 102 / FPS


def test_small_moves_make_no_sound():
    n = 120
    assert motion.body_events(_perf(n, **{
        "head.z": _ramp(n, 30, 8), "shoulder.R.x": _ramp(n, 60, -20)})) == []


def test_events_spaced_and_one_per_swing():
    n = 8 * FPS
    swing = [40 * ((i // 15) % 2) for i in range(n)]      # up and down every half second
    got = motion.body_events(_perf(n, **{"shoulder.R.x": swing, "elbow.R.x": swing}))
    ts = [e["t"] for e in got]
    assert ts and all(b - a >= motion.BODY_GAP_S for a, b in zip(ts, ts[1:]))
    # a move already under way when the shot opens is the cut's
    held = _perf(n, **{"shoulder.L.x": _ramp(n, 0, -70, 4)})
    assert motion.body_events(held) == []
    assert motion.body_events(_perf(5, **{"head.z": [0, 10, 20, 30, 40]})) == []


def test_a_real_performance():
    words, t = [], 0.3
    for w in ("So here is the thing. Nobody wanted this stock in March. Then the "
              "margins came back? Revenue up thirty percent. That is not luck.").split():
        d = 0.18 + 0.03 * len(w)
        words.append(W(w, t, t + d))
        t += d + (0.35 if w[-1] in ".?" else 0.06)
    dur = t + 1.0
    got = motion.body_events(motion.perform(words, dur, fps=FPS, seed="a",
                                            cue=motion.Look(yaw=40, pitch=0)))
    ts = [e["t"] for e in got]
    assert 2 <= len(got) <= dur / motion.BODY_GAP_S
    assert {e["kind"] for e in got} <= {"turn", "arm"}
    assert ts == sorted(ts) and ts[0] >= motion.BODY_SETTLE_S and ts[-1] < dur
    assert got == motion.body_events(motion.perform(words, dur, fps=FPS, seed="a",
                                                    cue=motion.Look(yaw=40, pitch=0)))


@pytest.fixture()
def rustles(settings, tmp_path):
    sfx = tmp_path / "assets" / "sfx"
    sfx.mkdir(parents=True)
    for name in ("cloth_rustle.wav", "cloth_rustle-2.wav", "cloth_rustle-3.wav"):
        (sfx / name).write_bytes(b"RIFF")
    return settings.model_copy(update={"assets_dir": tmp_path / "assets"})


def test_cues_offset_by_shot_start(rustles):
    moves = body_moves([(10.0, [{"kind": "arm", "t": 1.5}]),
                        (20.0, [{"kind": "turn", "t": 0.5}]), (30.0, [])])
    assert moves == [BodyMove("arm", 11.5), BodyMove("turn", 20.5)]
    a, b = body_cues(moves, rustles, "sha")
    assert (a.start_s, b.start_s) == (11.5, 20.5)
    assert a.gain_db == rustles.sfx_gain_db + BODY_GAIN_REL_DB
    assert b.gain_db == a.gain_db + BODY_TURN_DB, "a turn moves more cloth"
    assert (a.max_s, b.max_s) == (0.5, 0.8)
    assert a.path.name.startswith(BODY_KEY) and a.path != b.path
    assert [t.start_s for t in body_cues(moves, rustles, "sha")] == [11.5, 20.5]


def test_cues_keep_off_cuts_and_the_payoff(rustles):
    moves = [BodyMove("arm", 11.5), BodyMove("turn", 20.5), BodyMove("arm", 21.0)]
    got = body_cues(moves, rustles, "sha", clear_of=[11.6], drops=[(20.9, 21.4)])
    assert [t.start_s for t in got] == [], "on the cut, then into the payoff's silence"
    got = body_cues(moves, rustles, "sha", drops=[(20.9, 21.4)])
    assert [t.start_s for t in got] == [11.5]


def test_no_files_no_cue_no_block(settings, tmp_path):
    from pipeline.audio_assets import generated_audio

    empty = settings.model_copy(update={"assets_dir": tmp_path / "none"})
    (tmp_path / "none" / "sfx").mkdir(parents=True)
    assert body_cues([BodyMove("arm", 3.0)], empty, "sha") == []
    assert BODY_KEY not in EFFECT_KEYS, "no placeholder is made for it"
    assert not [p for p in generated_audio(settings) if BODY_KEY in p]


def test_the_fetch_brings_three_takes():
    import importlib.util

    spec = importlib.util.spec_from_file_location("_fetch_sfx_body",
                                                  ROOT / "scripts" / "fetch_sfx.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    names = [w[0] for w in mod.wanted() if w[1] == BODY_KEY]
    assert names == ["cloth_rustle.wav", "cloth_rustle-2.wav", "cloth_rustle-3.wav"]


def test_the_rest_of_the_mix_keeps_its_takes(rustles, tmp_path):
    from types import SimpleNamespace

    from pipeline.sound import Cut, short_mix

    sfx = rustles.assets_dir / "sfx"
    for name in ("whoosh.wav", "whoosh-2.wav", "impact.wav", "room_tone.wav"):
        (sfx / name).write_bytes(b"RIFF")
    voice = tmp_path / "voice.m4a"
    voice.write_bytes(b"x")
    tts = SimpleNamespace(audio_path=voice)
    cuts = [Cut("hook", 0.0, 3.0), Cut("a", 3.0, 7.0), Cut("b", 7.0, 12.0)]
    bare = short_mix(tts, rustles, cuts=cuts, seed="sha")
    heard = short_mix(tts, rustles, cuts=cuts, seed="sha",
                      body=[BodyMove("arm", 4.2), BodyMove("turn", 9.0)])
    extra = [t for t in heard if t.name.startswith("body:")]
    assert [t.start_s for t in extra] == [4.2, 9.0]
    assert [(t.name, t.path) for t in heard if t not in extra] == \
        [(t.name, t.path) for t in bare]


FAKE = textwrap.dedent('''
    import json, sys
    from pathlib import Path
    from PIL import Image
    for line in sys.stdin:
        line = line.strip()
        if not line:
            break
        job = json.loads(line)
        out = Path(job["out"]); out.mkdir(parents=True, exist_ok=True)
        n = max(int(round(job["duration"] * job["fps"])), 1)
        for i in range(n):
            Image.new("RGBA", tuple(job["size"]), (0, 0, 0, 0)).save(out / f"d_{i:04d}.png")
        print("@@" + json.dumps({"ok": True, "frames": n, "out": str(out), "seconds": 0.1,
                                 "device": "CPU", "window": None, "push": None,
                                 "events": [{"kind": "arm", "t": 0.4}]}), flush=True)
''')


def test_the_shot_keeps_its_events(settings, tmp_path, monkeypatch):
    if shutil.which("ffmpeg") is None:
        pytest.skip("needs ffmpeg")
    from types import SimpleNamespace

    fake = tmp_path / "fake_worker.py"
    fake.write_text(FAKE, encoding="utf-8")
    monkeypatch.setattr(dennis3d, "WORKER", fake)
    monkeypatch.setattr(settings, "dennis_3d_python", sys.executable)
    room = SimpleNamespace(key="room/desk-front-16x9", family="room", author="room3d")
    p = dennis3d.Performer(settings, cache=tmp_path / "cache")
    try:
        layer = p.shot(room, [], 0.0, 1.0, (64, 36), seed="x")
        assert p.events(layer) == [{"kind": "arm", "t": 0.4}]
        assert p.shot(room, [], 0.0, 1.0, (64, 36), seed="x") == layer
        assert p.events(layer) == [{"kind": "arm", "t": 0.4}], "a cached shot still knows"
    finally:
        p.close()
    (layer.parent / "events.json").unlink()
    assert dennis3d.Performer.events(layer) == [], "a shot drawn before A10 is silent"
