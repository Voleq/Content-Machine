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
NOT_YET_REWRITTEN = {"sample_long_EXMPL.mp4"}

# No composition in a vertical format may sit unchanged longer than this. It
# is the loosest ceiling any shot in any of the three templates sets; a
# tighter one is checked per shot in the layer-list suites.
HOLD_CEILING_S = 8.0

# Everything boils, so the still fraction should be small. Generous against
# encoder noise, and still far below the 78% the tag-driven renderer shipped.
HELD_FRACTION_MAX = 0.35


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


@pytest.mark.parametrize("sample", _samples(), ids=lambda p: p.stem)
def test_no_composition_holds_past_the_ceiling(sample):
    worst = longest_hold(sample, sample_fps=BOIL_SAMPLE_FPS, scale=BOIL_SCALE)
    assert worst <= HOLD_CEILING_S, (
        f"{sample.name} holds a composition for {worst:.2f}s, over the "
        f"{HOLD_CEILING_S}s ceiling")


@pytest.mark.parametrize("sample", _samples(), ids=lambda p: p.stem)
def test_the_sample_is_not_mostly_a_still_frame(sample):
    duration = _duration(sample)
    held = sum(b - a for a, b in _boil_spans(sample))
    frac = held / duration
    assert frac <= HELD_FRACTION_MAX, (
        f"{frac:.0%} of {sample.name} is held still "
        f"({held:.1f}s of {duration:.1f}s)")


@pytest.mark.parametrize("sample", _samples(), ids=lambda p: p.stem)
def test_the_sample_is_the_shape_its_format_is(sample):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0:nk=1",
         str(sample)], capture_output=True, text=True).stdout.strip()
    assert out.startswith("1080,1920"), f"{sample.name} is {out}, not 9:16"


@pytest.mark.parametrize("sample", _samples(), ids=lambda p: p.stem)
def test_every_sample_carries_its_manifest(sample):
    """The manifest is how a reviewer checks the cut without watching it."""
    import json
    man = sample.with_suffix(".manifest.json")
    assert man.exists(), f"{sample.name} has no manifest beside it"
    m = json.loads(man.read_text(encoding="utf-8"))
    assert m["shots"] and m["register"] and m["format"]
    assert not m.get("unfilled")


def test_the_defaults_would_have_missed_this():
    """Guard the reason the measurement changed, so it is not quietly undone.

    Measured with the old defaults the same files read as substantially held.
    If someone reverts the scale or the rate, this fails and says why rather
    than silently returning to a metric that cannot see the format's motion.
    """
    sample = SAMPLES / "sample_short_EXMPL.mp4"
    if not sample.exists():
        pytest.skip("short sample not present")
    duration = _duration(sample)
    blind = sum(b - a for a, b in held_spans(sample))     # 96x171 @ 2fps
    seeing = sum(b - a for a, b in _boil_spans(sample))
    assert seeing < blind, (
        "the boil-aware measurement should see MORE motion than the default "
        f"one, but got {seeing:.1f}s held vs {blind:.1f}s")
    assert blind / duration > HELD_FRACTION_MAX, (
        "the old defaults no longer over-report holds on this render; if the "
        "renderer changed, re-derive the boil sampling constants")
