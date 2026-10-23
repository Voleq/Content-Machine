"""V7: a video that looks like the last few.

The sameness gate reads the script's words. Two videos can say different
things over the same plates in the same order, from the same chairs, and
look like one video twice. After a proof or a final, the render's plate
order and room order are compared with the last 3 longs or 5 shorts.
"""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

from pipeline import look_alike
from pipeline.look_alike import (LONG_WINDOW, PLATE_RATIO, ROOM_RATIO,
                                 SHORT_WINDOW)

PLATES = ["charts/bars-6y", "figures/big-number-l1", "cards/definition",
          "structure/both-true", "charts/line-dense", "paper/headline-band"]
ROOMS = ["room/desk-front", "room/desk-wide", "room/board-wide",
         "room/desk-front", "room/window-wide"]


def _settings(tmp_path):
    return SimpleNamespace(workspace_dir=tmp_path)


def _video(tmp_path, ticker, day, look, *, name="render_long_manifest.json",
           age=0):
    ws = tmp_path / ticker / day
    ws.mkdir(parents=True)
    m = ws / name
    m.write_text(json.dumps({"look": look} if look is not None else {}),
                 encoding="utf-8")
    t = 1_800_000_000 - age
    os.utime(m, (t, t))
    return ws


def test_the_thresholds():
    assert (PLATE_RATIO, ROOM_RATIO) == (0.75, 0.8)
    assert (LONG_WINDOW, SHORT_WINDOW) == (3, 5)


def test_the_same_plates_in_the_same_order_are_named(tmp_path):
    _video(tmp_path, "AAA", "2026-10-20", {"plates": PLATES, "rooms": ROOMS[::-1]})
    me = _video(tmp_path, "BBB", "2026-10-23", None)
    got = look_alike.findings(_settings(tmp_path), "long",
                              {"plates": PLATES, "rooms": ROOMS}, exclude=me)
    assert got == [{"video": "AAA 2026-10-20", "what": "plates", "ratio": 1.0}]


def test_the_same_rooms_in_the_same_order_are_named(tmp_path):
    _video(tmp_path, "AAA", "2026-10-20", {"plates": PLATES[::-1], "rooms": ROOMS})
    me = _video(tmp_path, "BBB", "2026-10-23", None)
    got = look_alike.findings(_settings(tmp_path), "long",
                              {"plates": PLATES, "rooms": ROOMS}, exclude=me)
    assert [f["what"] for f in got] == ["rooms"]


def test_a_different_video_is_quiet(tmp_path):
    _video(tmp_path, "AAA", "2026-10-20",
           {"plates": PLATES[3:] + PLATES[:3], "rooms": ROOMS[2:] + ROOMS[:2]})
    me = _video(tmp_path, "BBB", "2026-10-23", None)
    assert look_alike.findings(_settings(tmp_path), "long",
                               {"plates": PLATES, "rooms": ROOMS},
                               exclude=me) == []


def test_only_the_last_three_longs_count(tmp_path):
    _video(tmp_path, "OLD", "2026-10-01", {"plates": PLATES, "rooms": []}, age=999)
    for i, t in enumerate(("C1", "C2", "C3")):
        _video(tmp_path, t, "2026-10-2%d" % i,
               {"plates": PLATES[::-1], "rooms": []}, age=i)
    me = _video(tmp_path, "BBB", "2026-10-23", None)
    assert look_alike.findings(_settings(tmp_path), "long",
                               {"plates": PLATES, "rooms": []}, exclude=me) == []


def test_a_short_is_compared_with_shorts_only(tmp_path):
    _video(tmp_path, "AAA", "2026-10-20", {"plates": PLATES, "rooms": []})
    _video(tmp_path, "CCC", "2026-10-21", {"plates": PLATES[::-1], "rooms": []},
           name="short_final.manifest.json")
    me = _video(tmp_path, "BBB", "2026-10-23", None, name="short_final.manifest.json")
    assert look_alike.findings(_settings(tmp_path), "short",
                               {"plates": PLATES, "rooms": []}, exclude=me) == []


def test_its_own_earlier_renders_never_count(tmp_path):
    me = _video(tmp_path, "BBB", "2026-10-23", {"plates": PLATES, "rooms": ROOMS},
                name="render_long_proof_manifest.json")
    assert look_alike.findings(_settings(tmp_path), "long",
                               {"plates": PLATES, "rooms": ROOMS}, exclude=me) == []


def test_old_manifests_and_a_first_video_are_quiet(tmp_path):
    assert look_alike.findings(_settings(tmp_path / "none"), "long",
                               {"plates": PLATES, "rooms": ROOMS}) == []
    _video(tmp_path, "AAA", "2026-10-20", None)
    (tmp_path / "AAA" / "2026-10-20" / "x.manifest.json").write_text(
        "not json", encoding="utf-8")
    assert look_alike.findings(_settings(tmp_path), "long",
                               {"plates": PLATES, "rooms": ROOMS}) == []


def test_a_few_beats_are_too_few_to_call_alike(tmp_path):
    _video(tmp_path, "AAA", "2026-10-20", {"plates": PLATES[:2], "rooms": ROOMS[:2]})
    assert look_alike.findings(_settings(tmp_path), "long",
                               {"plates": PLATES[:2], "rooms": ROOMS[:2]}) == []


def test_the_report_names_the_video_and_the_fix():
    text = look_alike.report({"look_alike": [
        {"video": "AAA 2026-10-20", "what": "plates", "ratio": 0.82},
        {"video": "CCC 2026-10-21", "what": "rooms", "ratio": 0.9}]})
    assert "AAA 2026-10-20" in text and "82%" in text
    assert "CCC 2026-10-21" in text and "90%" in text
    assert "[PLATE]" in text
    assert look_alike.report({}) == ""


def test_a_short_is_told_to_space_them_apart():
    text = look_alike.report({"look_alike": [
        {"video": "AAA 2026-10-20", "what": "plates", "ratio": 0.8}]}, "short")
    assert "Space the two apart" in text
    assert "[PLATE]" not in text
