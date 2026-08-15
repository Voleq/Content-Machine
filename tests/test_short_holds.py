"""The pixel backstop: measure the file, not the plan.

`test_short_shots.py` proves the composition was SPECIFIED correctly. This
proves the video that came out of the encoder actually moves. A layer list can
satisfy every invariant and still encode to a held frame — a full-bleed still
image over a boiling plate hides the boil completely, which is a thing that
happened and is why the chart is drawn three times.

This runs against the COMMITTED SAMPLE, not a fixture built for the occasion.
The last version shipped a sample that broke its own ceiling because the test
only ever looked at a fixture.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from pipeline.byproducts import (BOIL_SAMPLE_FPS, BOIL_SCALE, held_spans,
                                 longest_hold)

SAMPLE = Path("samples/sample_short_EXMPL.mp4")

# No composition in a SHORT may sit unchanged longer than this. It is the
# loosest ceiling any shot in the template sets; a shot with a tighter one is
# checked against its own in the layer-list suite.
SHORT_HOLD_CEILING_S = 6.0

# Everything in this format boils, so the still fraction should be close to
# nothing. Generous against encoder noise, and still an order of magnitude
# below the 78% the tag-driven renderer shipped.
SHORT_HELD_FRACTION_MAX = 0.15


def _ffprobe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True).stdout.strip()
    return float(out)


def _boil_spans(path: Path):
    """Measured the way a boiled render has to be measured.

    The defaults on `held_spans` cannot see a boil: 96x171 puts a 2-3% line
    move under a pixel, and 2fps aliases against 7fps so every other sample
    pair lands on the same frame of three. Both produce holds that are not
    there.
    """
    return held_spans(path, sample_fps=BOIL_SAMPLE_FPS, scale=BOIL_SCALE)


needs_sample = pytest.mark.skipif(
    not SAMPLE.exists(), reason="committed sample not present")


@needs_sample
def test_the_committed_sample_holds_nothing_past_the_ceiling():
    worst = longest_hold(SAMPLE, sample_fps=BOIL_SAMPLE_FPS, scale=BOIL_SCALE)
    assert worst <= SHORT_HOLD_CEILING_S, (
        f"the committed sample holds a composition for {worst:.2f}s, over the "
        f"{SHORT_HOLD_CEILING_S}s ceiling")


@needs_sample
def test_the_committed_sample_is_not_mostly_a_still_frame():
    duration = _ffprobe_duration(SAMPLE)
    held = sum(b - a for a, b in _boil_spans(SAMPLE))
    frac = held / duration
    assert frac <= SHORT_HELD_FRACTION_MAX, (
        f"{frac:.0%} of the committed sample is held still "
        f"({held:.1f}s of {duration:.1f}s)")


@needs_sample
def test_the_sample_is_the_shape_a_short_is():
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0:nk=1",
         str(SAMPLE)], capture_output=True, text=True).stdout.strip()
    assert out.replace("\n", "") == "1080,1920".replace(",", ",") or \
        out.startswith("1080,1920"), f"sample is {out}, not a 9:16 SHORT"


@needs_sample
def test_the_defaults_would_have_missed_this():
    """Guard the reason the measurement changed, so it is not quietly undone.

    Measured with the old defaults the same file reads as substantially held.
    If someone reverts the scale or the rate, this fails and says why rather
    than silently returning to a metric that cannot see the format's motion.
    """
    duration = _ffprobe_duration(SAMPLE)
    blind = sum(b - a for a, b in held_spans(SAMPLE))       # 96x171 @ 2fps
    seeing = sum(b - a for a, b in _boil_spans(SAMPLE))
    assert seeing < blind, (
        "the boil-aware measurement should see MORE motion than the default "
        f"one, but got {seeing:.1f}s held vs {blind:.1f}s")
    assert blind / duration > SHORT_HELD_FRACTION_MAX, (
        "the old defaults no longer over-report holds on this render; if the "
        "renderer changed, re-derive the boil sampling constants")
