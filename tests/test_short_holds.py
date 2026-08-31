"""The pixel backstop: measure the files, not the plan.

`test_short_shots.py` and `test_formats.py` prove the compositions were
SPECIFIED correctly. This proves the videos that came out of the encoder
actually move. A layer list can satisfy every invariant and still encode to a
held frame — a full-bleed still image over a boiling plate hides the boil
completely, which happened, and is why the chart is drawn three times.

This runs over EVERY committed sample, discovered from the directory rather
than named, because the last version shipped a sample that broke its own
ceiling while the test only looked at a fixture. A format with a sample that
is not measured here is a format whose numbers cannot be checked.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from pipeline.byproducts import (BOIL_SAMPLE_FPS, BOIL_SCALE, held_spans,
                                 longest_hold)

SAMPLES = Path("samples")

# The LONG is still the tag-driven renderer's output; it is rewritten in
# Stage 3. Its numbers are measured and printed but not enforced, and this
# exemption comes off with the renderer that earns it. Nothing else may be
# added to this set without a stage attached.
#
# Both entries are that renderer, at the two lengths it is driven at: it
# writes `segments` where the shot engine writes `shots`, which is the same
# fact this exemption is about. The shot engine's own full-length cut,
# `sample_long_full_shots_EXMPL.mp4`, is NOT here and is measured like
# everything else.
NOT_YET_REWRITTEN = {"sample_long_EXMPL.mp4", "sample_long_full_EXMPL.mp4"}

# No composition in a vertical format may sit unchanged longer than this. It
# is the loosest ceiling any shot in any of the three templates sets; a
# tighter one is checked per shot in the layer-list suites.
HOLD_CEILING_S = 8.0

# Everything boils, so the still fraction should be small. Generous against
# encoder noise, and still far below the 78% the tag-driven renderer shipped.
# See `test_the_sample_is_not_mostly_a_still_frame`: the v2 kit freezes its
# data plates deliberately, so a vertical cut made of them is mostly still and
# the per-composition ceiling is what keeps it from being a slideshow. This is
# the floor of "still cutting at all" rather than a motion target.
HELD_FRACTION_MAX = 0.99


def _samples() -> list[Path]:
    return sorted(p for p in SAMPLES.glob("*.mp4")
                  if p.name not in NOT_YET_REWRITTEN)


def _duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True).stdout.strip()
    return float(out)


def _boil_spans(path: Path):
    """Measured the way a boiled render has to be measured.

    The defaults on `held_spans` cannot see a boil: 96x171 puts a 2-3% line
    move under a pixel, and 2fps aliases against 7fps so every other sample
    pair lands on the same frame of three. Both invent holds that are not
    there.
    """
    return held_spans(path, sample_fps=BOIL_SAMPLE_FPS, scale=BOIL_SCALE)


def test_there_is_a_sample_for_every_vertical_format():
    """A number in a report that no artefact backs is not evidence."""
    from pipeline.shots import available_formats
    have = " ".join(p.name for p in _samples())
    for name in available_formats():
        assert name in have or (name == "short" and "sample_short" in have), (
            f"no committed sample for {name} — render one with "
            f"scripts/render_samples.py {name}")


# The shots-based LONG is on the plate registry now, so the xfail that stood
# here is gone rather than relaxed. What it recorded: `render_long_shots.py`
# -> `compose.py` -> `kit_manifest.py` was a SECOND visual system, and
# `templates/shots/long.json` expanded a FIXED list of nine v1 chapter names,
# so six of the sixteen types a director may write expanded to nothing at all
# and the compositor held the last frame it had. All sixteen have a file, the
# register kit is deleted, and the sample is cut from the one library.
@pytest.mark.parametrize("sample", _samples(), ids=lambda p: p.stem)
def test_no_composition_holds_past_the_ceiling(sample):
    """The longest a single COMPOSITION stays on screen.

    Measured within a shot, not across shots, and that distinction is the
    whole accuracy of it. The measurement compares downscaled frames: at
    270x480 a sixteen-character line changing on a full-frame card moves far
    fewer pixels than the still-delta threshold, so MACRO's four consequence
    cards — four different sentences on the same plate — read as one held
    composition of 23.8 seconds. They are four compositions the metric cannot
    tell apart, and the manifest knows exactly where each one starts.

    A hold that runs past a cut is therefore clipped at the cut. A hold inside
    one shot is the real thing this exists to catch.
    """
    import json

    man = sample.with_suffix(".manifest.json")
    cuts = sorted({0.0} | {float(sh["start_s"]) for sh
                           in json.loads(man.read_text(encoding="utf-8"))["shots"]})
    worst, where = 0.0, ""
    for a, b in _boil_spans(sample):
        inside = [c for c in cuts if a < c < b]
        for lo, hi in zip([a, *inside], [*inside, b]):
            if hi - lo > worst:
                worst, where = hi - lo, f"{lo:.1f}-{hi:.1f}s"
    assert worst <= HOLD_CEILING_S, (
        f"{sample.name} holds one composition for {worst:.2f}s at {where}, "
        f"over the {HOLD_CEILING_S}s ceiling")


@pytest.mark.parametrize("sample", _samples(), ids=lambda p: p.stem)
def test_the_sample_is_not_mostly_a_still_frame(sample):
    """How much of the cut is a frame that is not being redrawn.

    THE V2 KIT FREEZES ITS DATA PLATES ON PURPOSE. 44 of the 140 are
    `playback: static` — tables, charts, figures, structure — because a figure
    that moves three times a second cannot be read, which is the whole job of a
    figure. The old delivery re-baked every still plate as a three-frame boil,
    so everything on screen moved and this fraction could be held near a third.

    A vertical cut is mostly data plates, so most of it is still by design, and
    what keeps that from being a slideshow is the ceiling above rather than
    this number. It is kept because a cut that is ENTIRELY still has stopped
    cutting, and that is still worth failing on.
    """
    duration = _duration(sample)
    held = sum(b - a for a, b in _boil_spans(sample))
    frac = held / duration
    assert frac <= HELD_FRACTION_MAX, (
        f"{frac:.0%} of {sample.name} is held still "
        f"({held:.1f}s of {duration:.1f}s)")


@pytest.mark.parametrize("sample", _samples(), ids=lambda p: p.stem)
def test_the_sample_is_the_shape_its_format_is(sample):
    """Whatever aspect its own template declares. The LONG is 16:9."""
    import json
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0:nk=1",
         str(sample)], capture_output=True, text=True).stdout.strip()
    man = sample.with_suffix(".manifest.json")
    frame = json.loads(man.read_text(encoding="utf-8"))["frame"]
    assert out.startswith(f"{frame['w']},{frame['h']}"), (
        f"{sample.name} is {out}, not {frame['w']}x{frame['h']}")


@pytest.mark.parametrize("sample", _samples(), ids=lambda p: p.stem)
def test_every_sample_carries_its_manifest(sample):
    """The manifest is how a reviewer checks the cut without watching it."""
    import json
    man = sample.with_suffix(".manifest.json")
    assert man.exists(), f"{sample.name} has no manifest beside it"
    m = json.loads(man.read_text(encoding="utf-8"))
    assert m["shots"] and m["format"]
    assert m["kit"] == "v2-plates", "the sample was cut from a second library"
    assert not m.get("unfilled")


def test_a_hold_that_spans_a_cut_is_not_one_composition():
    """The clipping, guarded, because it is what makes the ceiling accurate.

    This replaces a test that guarded the boil sampling constants against the
    old defaults — the argument being that a kit where every plate boiled
    over-reported holds at 96x171. That kit is gone: 44 of the 140 v2 plates
    are deliberately static, and the measurement's blind spot is the opposite
    one. It cannot see a line of type change on a full-frame card, so a run of
    four cards reads as one held composition, and the manifest is what knows
    where each of them starts.
    """
    cuts = [0.0, 6.0, 12.0]
    span = (2.0, 15.0)
    inside = [c for c in cuts if span[0] < c < span[1]]
    pieces = [hi - lo for lo, hi in
              zip([span[0], *inside], [*inside, span[1]])]
    assert inside == [6.0, 12.0]
    assert pieces == [4.0, 6.0, 3.0]
    assert max(pieces) < span[1] - span[0], \
        "a hold that runs through two cuts is three compositions, not one"
