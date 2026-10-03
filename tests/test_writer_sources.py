"""The LONG writer's [SOURCE]: where the figure on screen comes from (item 14).

Design's source tag slides in under a plate once its moves land. The writer
names the document — the filing or the agency, never the data vendor — right
after the [PLATE] it is for, and the parse holds it to the tag's size, one a
plate, and a plate that has no source slot of its own.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from pipeline.models import Cue, CueKind, TagType
from pipeline.parser_long import (LongScriptError, parse_long_script,
                                  validate_long_script)
from pipeline.plates import load_plates
from pipeline.timeline import (build_long_timeline, plan_long_segments,
                               plan_writer_sources)
from pipeline.tts import mock_words

ROOT = Path(__file__).resolve().parents[1]

# The big figure with a detail line under it: design gives it a clear spot
# for the tag. Its one-line sibling `big-number-l1` has none (`CROWDED`).
BIG = ("[PLATE: big-number-l2-16x9 | kicker=FREE CASH FLOW | value=$3.1bn | "
       "label=LTM]")
CROWDED = ("[PLATE: bars-6y-16x9 | head-1=FY20 | head-2=FY21 | head-3=FY22 | "
           "head-4=FY23 | head-5=FY24 | head-6=FY25 | value-1=1.2 | value-2=1.5 | "
           "value-3=1.9 | value-4=2.4 | value-5=2.2 | value-6=3.1 | unit=$bn]")
QUOTE = ("[PLATE: quote-pull-16x9 | body=We remain confident in the long "
         "term. | attribution=The CEO]")


@pytest.fixture()
def settings(settings):
    return settings.model_copy(update={"long_min_chars": 0})


@pytest.fixture()
def reg(settings):
    return load_plates(settings.assets_dir)


def _check(raw: str, settings, tmp_path):
    script, _ = parse_long_script(raw, "EXMPL", settings)
    warnings, blocking = validate_long_script(script, set(), tmp_path, settings)
    return ([w for w in warnings if "SOURCE" in w],
            [b for b in blocking if "SOURCE" in b], script)


def test_a_source_is_parsed_onto_the_plate_before_it_and_never_spoken(settings):
    raw = f"Cash. {BIG} [SOURCE:  FY24   10-K ] It made a lot."
    script, _ = parse_long_script(raw, "EXMPL", settings)
    src = script.events_of(TagType.SOURCE)[0]
    assert src.payload == "FY24 10-K"
    assert src.values == {"plate": "figures/big-number-l2-16x9", "on": "PLATE"}
    assert "SOURCE" not in script.narration and "10-K" not in script.narration


def test_a_valid_source_passes_validation(settings, tmp_path):
    warnings, blocking, _ = _check(f"Cash. {BIG} [SOURCE: FY24 10-K] It made a lot.",
                                   settings, tmp_path)
    assert warnings == [] and blocking == []


def test_a_source_naming_the_data_vendor_is_refused_at_the_parse(settings):
    with pytest.raises(LongScriptError, match="vendor"):
        parse_long_script(f"Cash. {BIG} [SOURCE: Refinitiv] It made a lot.",
                          "EXMPL", settings)


@pytest.mark.parametrize("raw, why", [
    ("Cash. [SOURCE: FY24 10-K] It made a lot.", "before any [PLATE]"),
    (f"Cash. {BIG} [SOURCE: {'x' * 41}] It made a lot.", "the tag holds 40"),
    (f"Cash. {BIG} [SOURCE: FY24 10-K] It made [SOURCE: Q2 10-Q] a lot.",
     "one a plate"),
    (f"Quote. {QUOTE} [SOURCE: Q2 call] He said it.", "prints its own source"),
    ("Cash. [MEME: this-is-fine] [SOURCE: FY24 10-K] It made a lot.",
     "belongs to a [MEME]"),
    (f"Revenue. {CROWDED} [SOURCE: 10-K filings, FY20–FY25] It grew.",
     "no clear spot for the source tag"),
])
def test_a_source_that_cannot_go_under_its_plate_blocks(settings, tmp_path, raw, why):
    _, blocking, _ = _check(raw, settings, tmp_path)
    assert any(why in b for b in blocking), blocking


def _cue(t, kind, order, **payload):
    return Cue(t=t, kind=kind, payload={"order": order, **payload})


def test_a_source_goes_under_its_beat_and_one_a_beat(settings):
    raw = ("Here is where the money went, and it went somewhere. "
           f"{BIG} [SOURCE: FY24 10-K] It made three point one billion "
           "dollars last year, which is a lot of money for a company this "
           "size.")
    script, _ = parse_long_script(raw, "EXMPL", settings)
    cues = build_long_timeline(script, mock_words(script.narration, 20.0), 20.0)
    segments, _ = plan_long_segments(cues, 20.0)
    sources, warnings = plan_writer_sources(cues, segments)
    assert warnings == []
    (src,) = sources
    seg = segments[src.segment]
    assert seg.kind == "plate" and src.plate == "figures/big-number-l2-16x9"
    assert seg.start <= src.t < seg.end and src.at == pytest.approx(src.t - seg.start)
    assert src.text == "FY24 10-K"


def test_a_source_spoken_after_its_plate_has_gone_is_dropped(reg):
    big = "figures/big-number-l2-16x9"
    # The writer moved on at 10 s (the clip), so the plate was gone by 25.
    cues = [_cue(2.0, CueKind.PLATE, 0, value=big, values={"value": "$1bn"}),
            _cue(10.0, CueKind.CLIP, 1, value="x"),
            _cue(25.0, CueKind.SOURCE, 2, value="FY24 10-K", plate=big,
                 plate_order=0)]
    segments, _ = plan_long_segments(cues, 30.0)
    sources, warnings = plan_writer_sources(cues, segments)
    assert sources == [] and "cut back to Dennis" in warnings[0]


def test_the_tag_slides_in_from_the_left_and_rests_on_the_plate_s_margin(
        settings, reg, tmp_path, monkeypatch):
    from pipeline import moves as MV

    got = {}

    def held(frames, out, *, fps=12):
        got["frames"], got["fps"] = frames, fps
        return out

    monkeypatch.setattr("pipeline.rasters.held_frames_to_alpha_clip", held)
    plate = reg.get("charts/earnings-vs-cash-16x9")
    panel = (100, 60, 960, 540)
    clip = MV.source_tag_clip(reg, settings, tmp_path / "s.mov", text="FY24 10-K",
                              plate=plate, aspect="16x9", panel=panel)
    # design's six frames of slide, played at the video's rate
    assert clip is not None and got["fps"] == MV.OUT_FPS
    assert len(got["frames"]) == len(MV._played_frames(clip.frames))
    assert all(abs(d * MV.OUT_FPS - 1) < 1e-9 for _, d in got["frames"])
    tag = reg.get(reg.aspect_key("overlays/source-tag", "16x9"))
    x, y, w, h = MV.tag_rect(tag, plate, panel[2:], reg)
    assert clip.y == panel[1] + y and clip.y + h <= panel[1] + panel[3]
    # Design's spot on this plate, scaled with the panel: x 96, y 930.
    spot = plate.motion["slide-in"]["box"]
    assert (x, y) == (round(spot["x"] / 2), round(spot["y"] / 2))

    def left_edge(img):
        cols = np.nonzero(np.asarray(img)[..., 3].max(axis=0))[0]
        return int(cols[0]) if len(cols) else None

    first, last = got["frames"][0][0], got["frames"][-1][0]
    assert left_edge(first) is None or left_edge(first) < panel[0] + x
    assert left_edge(last) == pytest.approx(panel[0] + x, abs=2)


def test_a_plate_with_no_clear_spot_gets_no_tag(settings, reg, tmp_path):
    """Design: where the tag would cover the plate's figures, never over it."""
    from pipeline import moves as MV

    plate = reg.get("charts/bars-6y-16x9")
    assert not MV.tag_clear(plate)
    assert MV.source_tag_clip(reg, settings, tmp_path / "s.mov", text="FY24 10-K",
                              plate=plate, aspect="16x9",
                              panel=(0, 0, 1920, 1080)) is None


def test_the_catalogue_marks_the_plates_a_source_cannot_go_under(settings):
    from bot.prompts import plate_catalogue

    slots, plate = {}, None
    for l in plate_catalogue(settings).splitlines():
        if l.startswith("  ") and not l.startswith("   "):
            plate = l.split()[0]
        elif l.strip().startswith("slots:") and plate:
            slots[plate] = l
    assert "✕source" in slots["bars-6y-16x9"]
    assert "✕source" not in slots["earnings-vs-cash-16x9"]


def test_a_plate_that_prints_its_own_source_gets_no_tag(settings, reg, tmp_path):
    from pipeline import moves as MV

    assert MV.source_tag_clip(reg, settings, tmp_path / "s.mov", text="Q2 call",
                              plate=reg.get("cards/quote-pull-16x9"),
                              aspect="16x9", panel=(0, 0, 1920, 1080)) is None


def test_the_write_prompt_teaches_the_source_tag():
    text = (ROOT / "templates" / "master_prompt_long_write.md").read_text(
        encoding="utf-8")
    assert "[SOURCE: document]" in text and "never a data vendor" in text
    assert "✕source" in text
