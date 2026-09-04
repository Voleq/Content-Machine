"""Every format, against the one library.

A format is a file: `templates/shots/*.json` fixes space and order and nothing
in the engine knows what a format is called. These are the checks that hold
for all of them at once, so adding a fourth is authoring a file rather than
writing a branch.

WHAT THIS FILE USED TO CHECK AND NO LONGER DOES. Half of it was about type
this code drew itself — that a sheet's rows agreed on one size, that two
free-placed boxes did not overlap, that a box was tall enough for the lines it
promised. None of that is this code's business any more: a plate declares its
slots and `plate_frames` sets them in the face, size, weight and colour role
the kit declares for each slot's role, and a value that will not fit is
refused by `check_budgets` against the kit's own `maxChars` before a frame is
drawn. The checks did not stop being true; they stopped being about anything
here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.compose import (build_layers, check_budgets, check_invariants,
                              resolve_plate)
from pipeline.shots import (LARGE_TYPE_FH, MIN_TYPE_FH, TemplateError,
                            available_formats, expand_sequences, load_format,
                            parse_format, resolve_spans)

FORMATS = available_formats()
VERTICAL = ("short", "earnings", "macro")


def _reg():
    """The one library. There is no register to pick any more."""
    from config import Settings
    from pipeline.plates import load_plates
    return load_plates(Settings(_env_file=None).assets_dir)


class FakeWord:
    def __init__(self, w, a, b):
        self.word, self.start, self.end = w, a, b


class StubResolver:
    """Fills everything a template asks for, so the invariants are what fail."""

    def text_for(self, src: str) -> str | None:
        # A DATA REGION AND A ROW TAKE FIGURES, NOT WORDS, and the heads are
        # however many the plate declares — four on a dense chart, six on a
        # per-period one.
        parts = set(src.split("."))
        if {"series", "figures"} & parts:
            return ",".join(str(10 + i * 3) for i in range(6))
        if {"heads", "axis"} & parts:
            return "a,b,c,d"
        if "years" in parts:
            return "a,b,c,d,e,f"
        return "3.4%"

    def image_for(self, src):
        return None

    def list_for(self, src):
        return ["one", "two", "three"]


def _cut(name: str):
    fmt = expand_sequences(load_format(name), lambda _s: ["a", "b", "c"])
    words = [FakeWord(f"w{i}", i * 0.3, i * 0.3 + 0.25) for i in range(240)]
    spans = resolve_spans(fmt, words, 72.0, {})
    return fmt, spans, build_layers(fmt, spans, StubResolver(), _reg(),
                                    aspect=fmt.aspect, seed=name)


# ---------------------------------------------------------------- templates


def test_there_is_at_least_one_format_and_they_all_parse():
    assert FORMATS
    for name in FORMATS:
        assert load_format(name).shots


@pytest.mark.parametrize("name", VERTICAL)
def test_every_plate_a_format_names_is_in_the_kit(name):
    """A name that resolves to nothing draws nothing.

    One library, so this is one lookup. It used to be four — the same plate
    checked in every hand-drawn register, because a video seeded into the one
    that was missing it failed at render time for a reason that had nothing to
    do with the script.
    """
    reg = _reg()
    fmt = load_format(name)
    for shot in fmt.shots:
        if shot.plate:
            role = (shot.plate.split("/", 1)[1]
                    if shot.plate.startswith("room/") else "")
            if role and role in reg.room_roles:
                continue
            assert resolve_plate(reg, shot.plate, fmt.aspect) is not None, \
                f"{name}/{shot.id}: {shot.plate!r} is not a plate in the kit"
        if shot.host:
            assert shot.host.pose in reg or shot.host.pose in reg.host_roles, \
                f"{name}/{shot.id}: {shot.host.pose!r} is neither pose nor role"


@pytest.mark.parametrize("name", VERTICAL)
def test_a_vertical_format_reaches_only_vertical_plates(name):
    """The comps table, the scatter and the waterfall are 16:9 by design.

    They need horizontal room to be readable and do not belong in seventy-five
    seconds. One named here would render letterboxed with its type at a third
    of the size it was drawn at.
    """
    reg = _reg()
    fmt = load_format(name)
    for shot in fmt.shots:
        if not shot.plate or shot.plate.startswith("room/"):
            continue
        plate = resolve_plate(reg, shot.plate, fmt.aspect)
        assert plate.aspect in ("9x16", ""), \
            f"{name}/{shot.id}: {plate.key} is {plate.aspect}"


def test_a_template_carrying_large_type_and_captions_is_refused():
    """The two are mutually exclusive, and the parser is where that is caught."""
    raw = {"format": "bad", "frame": {"w": 1080, "h": 1920},
           "shots": [{"id": "x", "plate": None, "captions": True,
                      "text": [{"src": "script.conclusion",
                                "size_fh": LARGE_TYPE_FH + 0.01}]}]}
    with pytest.raises(TemplateError):
        parse_format(raw)


def test_type_below_the_floor_is_refused():
    raw = {"format": "bad", "frame": {"w": 1080, "h": 1920},
           "shots": [{"id": "x", "plate": None,
                      "text": [{"src": "script.conclusion",
                                "size_fh": MIN_TYPE_FH - 0.005}]}]}
    with pytest.raises(TemplateError, match="below"):
        parse_format(raw)


def test_no_format_is_named_anywhere_in_the_engine():
    """Adding a format is authoring a file. This is that promise, checked."""
    for path in (Path("pipeline/compose.py"), Path("pipeline/shots.py")):
        body = path.read_text(encoding="utf-8")
        for name in FORMATS:
            assert f'"{name}"' not in body, \
                f"{path.name} names the format {name!r}"


# ----------------------------------------------------------- the LONG's shape


def test_the_long_is_chapters_and_all_sixteen_types_have_a_file():
    """Six of the sixteen types used to expand to nothing at all.

    The nine chapter files were named for a story shape — `the-unit`,
    `both-hands`, `the-event` — so a director writing `moat` or `filing-walk`
    or `short-interest` got a chapter with no shots in it.
    """
    from pipeline.plates import CHAPTER_TYPES

    # The chapter list lives in the file: `load_format` expands it into shots,
    # so the names are read where they are written.
    raw = json.loads(Path("templates/shots/long.json").read_text(
        encoding="utf-8"))
    assert list(raw["chapters"]) == list(CHAPTER_TYPES)
    files = {p.stem for p in Path("templates/chapters").glob("*.json")}
    assert files == set(CHAPTER_TYPES), \
        f"missing: {sorted(set(CHAPTER_TYPES) - files)}"


def _long_cut():
    """The LONG, composed from the chapter files, on stub copy."""
    fmt = expand_sequences(load_format("long"), lambda _s: ["a", "b", "c"])
    words = [FakeWord(f"w{i}", i * 0.3, i * 0.3 + 0.25) for i in range(4000)]
    spans = resolve_spans(fmt, words, 1200.0, {})
    return fmt, build_layers(fmt, spans, StubResolver(), _reg(),
                             aspect=fmt.aspect, seed="LONGTEST")


def test_the_long_cuts_to_the_close_up():
    """It is the shot that was missing, and it carries the beats that matter.

    Every chapter used to land on a full figure in a wide room — the shot you
    use when the ROOM is the point — for the line the chapter rests on.
    """
    _fmt, result = _long_cut()
    poses = {l.entry_key for l in result.of_kind("host")}
    assert any(k.startswith("host/close-up") for k in poses), sorted(poses)


def test_a_two_shot_puts_the_graphic_beside_him_and_not_under_him():
    """A shot carrying both a plate and a host is a split frame.

    It used to draw the plate at the full frame and then composite him into
    the middle of it, over the thing he is discussing.
    """
    _fmt, result = _long_cut()
    two_shots = [l.shot_id for l in result.of_kind("host")
                 if any(o.kind == "plate" and o.concept != "room"
                        for o in result.for_shot(l.shot_id))]
    assert two_shots, "no chapter puts him beside the evidence"
    for shot_id in two_shots:
        host = [l for l in result.for_shot(shot_id) if l.kind == "host"][0]
        for o in result.for_shot(shot_id):
            if o.kind != "plate" or o.concept == "room":
                continue
            overlap = (max(0, min(host.x + host.w, o.x + o.w) - max(host.x, o.x))
                       * max(0, min(host.y + host.h, o.y + o.h) - max(host.y, o.y)))
            assert overlap < 0.05 * o.w * o.h, \
                f"{shot_id}: he is drawn over {overlap / (o.w * o.h):.0%} of {o.entry_key}"


def test_a_glance_is_cut_on_the_two_shots():
    """INGESTING THE SHOTS AND NEVER CUTTING TO THEM IS THE FAILURE HERE.

    It is not an error and no render fails: it is every beat straight to
    camera, with four glance keys sitting unused in the kit. So the check is
    that one actually fires, and that it looks the way the graphic is.
    """
    _fmt, result = _long_cut()
    glances = [l for l in result.of_kind("host") if "-glance-" in l.entry_key]
    assert glances, "not one glance was cut in a whole long"
    for host in glances:
        side = host.entry_key.rsplit("-", 1)[1]
        plates = [o for o in result.for_shot(host.shot_id)
                  if o.kind == "plate" and o.concept != "room"]
        assert plates, f"{host.shot_id}: a glance at nothing"
        mid = plates[0].x + plates[0].w / 2
        host_mid = host.x + host.w / 2
        assert (mid < host_mid) == (side == "left"), \
            f"{host.shot_id}: {host.entry_key} against a graphic on the other side"


def test_a_room_that_refuses_a_cut_out_gets_a_framing_instead():
    """`hostAnchor: false` is branched on, not read as an omission.

    `room/wall-of-calls` is square to a wall of index cards and there is no
    floor in it. A figure was composited in front of it anyway, standing on
    nothing. A framing has no floor line to pin, so the beat survives as the
    close-up it should probably have been.
    """
    reg = _reg()
    _fmt, result = _long_cut()
    refusing = {l.shot_id for l in result.layers
                if l.kind == "plate" and (reg.get(l.entry_key) is not None
                                          and reg.get(l.entry_key).refuses_host)}
    assert refusing, "no chapter reaches a room that refuses a host"
    for shot_id in refusing:
        for host in [l for l in result.for_shot(shot_id) if l.kind == "host"]:
            pose = reg.get(host.entry_key)
            assert pose.framing, \
                f"{shot_id}: {host.entry_key} stands in a room with no floor"


def test_the_long_rotates_its_room_angles():
    """Nine straight-on eye-level plates cut like props sliding on a shelf.

    THE THREE NEW CAMERA POSITIONS ARE THE POINT. They were added because the
    room only ever had one lens on it, and a kit that ships them into a
    pipeline that never cuts to them has changed nothing. `high-desk-down` is
    the one with no floor in shot: it fills the `surface` role alone, and the
    filing walk is the beat that wants it.
    """
    _fmt, result = _long_cut()
    rooms = {l.entry_key for l in result.layers
             if l.kind == "plate" and l.concept == "room"}
    assert len(rooms) >= 8, sorted(rooms)
    for angle in ("corner-perspective", "low-desk-height", "high-desk-down"):
        assert f"room/{angle}-16x9" in rooms, \
            f"{angle} is in the kit and never cut to: {sorted(rooms)}"


# ------------------------------------------------------------- the invariants


@pytest.mark.parametrize("name", VERTICAL)
def test_every_format_satisfies_its_own_invariants(name):
    fmt, _spans, result = _cut(name)
    problems = check_invariants(
        fmt, result, host_shots=[sh.id for sh in fmt.shots if sh.host])
    assert problems == [], "\n".join(problems)


@pytest.mark.parametrize("name", VERTICAL)
def test_nothing_a_format_places_leaves_the_frame(name):
    _fmt, _spans, result = _cut(name)
    fw, fh = result.frame
    for l in result.layers:
        if l.kind in ("ground", "caption") or not (l.w and l.h):
            continue
        assert l.x + l.w > 0 and l.y + l.h > 0
        assert l.x < fw and l.y < fh


@pytest.mark.parametrize("name", VERTICAL)
def test_the_host_is_not_mostly_off_the_frame(name):
    """He is a subject and has to be seen.

    A plate pushed in on a row carries its anchor off the bottom with it: he
    stood at y=1832 in a 1920 frame once, 13% of him on screen, reading as a
    smudge at the edge.

    A FRAMING IS MEASURED ON THE HEAD, NOT ON THE PLATE. `close-up` and
    `medium` are camera distances: the kit says both run off the left and
    right edges by design and that cropping to the width re-frames the shot,
    so a close-up in a 9:16 frame is 1858px wide in a 1080px frame and 58% of
    its area is off — which is the shot working. What must be on screen is his
    face.
    """
    reg = _reg()
    _fmt, _spans, result = _cut(name)
    fw, fh = result.frame
    for h in result.of_kind("host"):
        pose = reg.get(h.entry_key)
        head = pose.slot("head") if pose is not None else None
        if pose is not None and pose.framing and head is not None:
            k = h.w / max(pose.delivered[0], 1)
            hx, hy, hw, hh = head.scaled()
            box = (h.x + hx * k, h.y + hy * k, hw * k, hh * k)
            assert box[0] >= 0 and box[0] + box[2] <= fw, \
                f"{h.name}: his head is cropped by the frame's side"
            assert box[1] >= 0 and box[1] + box[3] <= fh, \
                f"{h.name}: his head is cropped top or bottom"
            continue
        on = ((min(h.x + h.w, fw) - max(h.x, 0))
              * (min(h.y + h.h, fh) - max(h.y, 0)))
        assert on > 0.6 * h.w * h.h, \
            f"{h.name}: {on / (h.w * h.h):.0%} of him is on screen"


@pytest.mark.parametrize("name", VERTICAL)
def test_no_layer_outlives_its_shot(name):
    _fmt, _spans, result = _cut(name)
    by = {sp.shot.id: sp for sp in result.spans}
    for l in result.layers:
        sp = by[l.shot_id]
        assert l.t_start >= sp.start - 1e-6 and l.t_end <= sp.end + 1e-6


@pytest.mark.parametrize("name", VERTICAL)
def test_the_kits_budgets_are_what_a_format_is_checked_against(name):
    """`maxChars` is the kit's own limit, per slot role.

    Measured against the face and size the slot is actually set in — so the
    budget is a property of the drawing rather than of a fitter run over the
    templates, which is what `templates/budgets.json` used to be.
    """
    fmt, _spans, result = _cut(name)
    assert check_budgets(fmt, result, _reg()) == []


def test_the_template_is_data_not_code():
    raw = json.loads(Path("templates/shots/short.json").read_text(
        encoding="utf-8"))
    assert raw["format"] == "short"
    assert all("plate" in s for s in raw["shots"])
    seq = [s for s in raw["shots"]
           if s.get("repeat", {}).get("arrange") == "sequence"]
    assert len(seq) == 1 and seq[0]["id"] == "numbers"
