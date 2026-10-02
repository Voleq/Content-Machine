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
        # THE COMPANY'S PICTURE (item 34) is a required slot on the short's
        # second beat, so a resolver that fills everything hands it a file.
        return Path(f"{src}.png") if src.startswith("photo.") else None

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
        # EVERY PLATE THE BEAT CAN LAND ON, not only the authored one. An
        # alternate the kit does not carry is dropped silently at render time
        # — deliberately, so a kit swap degrades rather than fails — which
        # means a typo in one is invisible unless it is caught here.
        for variant in shot.variants:
            role = (variant.plate.split("/", 1)[1]
                    if variant.plate.startswith("room/") else "")
            if role and role in reg.room_roles:
                continue
            assert resolve_plate(reg, variant.plate, fmt.aspect) is not None, \
                f"{name}/{shot.id}: {variant.plate!r} is not a plate in the kit"
        if shot.host:
            assert shot.host.pose in reg or shot.host.pose in reg.host_roles, \
                f"{name}/{shot.id}: {shot.host.pose!r} is neither pose nor role"


@pytest.mark.parametrize("name", VERTICAL)
def test_a_vertical_format_reaches_only_vertical_plates(name):
    """The scatter, the multiple bridge and the flow plates are 16:9 by design.

    They need horizontal room to be readable and do not belong in a
    fifty-second vertical cut. One named here would render letterboxed with its type at a third
    of the size it was drawn at.
    """
    reg = _reg()
    fmt = load_format(name)
    for shot in fmt.shots:
        for variant in shot.variants:
            if variant.plate.startswith("room/"):
                continue
            plate = resolve_plate(reg, variant.plate, fmt.aspect)
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
    # The numbers beat is one card a row (item 26): a sequence the writer's
    # rows drive, never a sheet of four rows at table size.
    repeats = [s for s in raw["shots"] if s.get("repeat")]
    assert [s["id"] for s in repeats] == ["numbers"]
    assert repeats[0]["repeat"]["arrange"] == "sequence"


def test_the_short_manifest_names_the_template_it_rendered(settings, tmp_path,
                                                           short_valid_json):
    """P4: `/headline` picks `short`, `earnings` or `macro` per video and the
    three are different beat orders out of one renderer. Which one ran was
    recoverable from nothing — so an earnings video that came out reading
    like a plain short had no artefact saying which template drew it."""
    import json

    from pipeline.parser_short import parse_short_script
    from pipeline.render_short import render_short
    from pipeline.tts import TTSEngine

    small = settings.model_copy(update={"short_width": 270,
                                        "short_height": 480})
    script, _ = parse_short_script(short_valid_json, settings=small)
    tts = TTSEngine(small).synthesize(script.audio_script, fmt="short",
                                      free_only=True)
    _out, manifest_path = render_short(script, tts, tmp_path, small,
                                       proof=True)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["engine"] == "shots"
    assert manifest["format"] == "short"
    assert manifest["provenance"]["render"] == {"engine": "shots",
                                                "format": "short"}

    from pipeline.provenance import Provenance

    line = next(ln for ln in
                Provenance.from_json(manifest["provenance"])
                .render_text().splitlines() if ln.startswith("render"))
    assert "shots" in line and "template short" in line

    # Measured on the frames, not skipped: a list, where `None` would
    # mean they could not be read back.
    pacing = manifest["pacing"]
    assert pacing["hold_ceiling_s"] == small.short_max_hold_s
    assert isinstance(pacing["held_over_ceiling"], list)
