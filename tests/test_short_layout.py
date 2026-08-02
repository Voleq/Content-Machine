"""How much of the frame a short's beats actually occupy.

The short read empty, and the cause was arithmetic nobody had done: the stage
box was a 1000x760 LANDSCAPE rectangle on a 1080x1920 frame, so a 1:1 drawing
— 134 of the kit's assets — contain-fitted to 760x760 and covered 28% of the
screen. The top nineteen per cent of every frame was blank while the hook, the
ledger and the captions competed in the bottom third.

These assert the geometry rather than anybody's impression of it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from pipeline.render_short import (
    HOOK_Y,
    LEDGER_Y,
    PUNCT_BOX,
    STAGE_H,
    STAGE_MAX_W,
    STAGE_Y,
    _median_coverage,
    fit_to_frame,
    stage_box,
)

ROOT = Path(__file__).resolve().parents[1]
W, H = 1080, 1920


def px(v):        # the identity scale — design px are frame px at 1080 wide
    return int(v)


# --------------------------------------------------------------------------
# The stage fits to WIDTH for anything that is not landscape.
# --------------------------------------------------------------------------


def test_a_square_drawing_takes_the_frames_width():
    """The single largest change available to the short, and it costs
    nothing: 760x760 is 28% of the frame, 1080x1080 is 56%."""
    box = stage_box(W, H, px, is_data=True)
    out = fit_to_frame(Image.new("RGBA", (1080, 1080)), box, W, H, px)
    assert out.size == (1080, 1080)
    assert out.width * out.height / (W * H) > 0.5


def test_a_portrait_drawing_fills_the_band():
    """Taller than the stage, so the band caps it rather than the width — but
    it still lands far bigger than the old 1000x760 landscape box, which gave
    the same drawing 608x760."""
    box = stage_box(W, H, px, is_data=True)
    out = fit_to_frame(Image.new("RGBA", (1080, 1350)), box, W, H, px)
    assert out.height == box[1]
    assert out.width > 800
    assert out.width * out.height / (W * H) > 0.4


def test_a_landscape_drawing_is_contain_fitted_as_before():
    """Widening a 16:9 card only adds empty margin — its height is what is
    capped, and that is arithmetic rather than a layout choice."""
    box = stage_box(W, H, px, is_data=True)
    out = fit_to_frame(Image.new("RGBA", (1920, 1080)), box, W, H, px)
    assert out.size == (1080, 607)


def test_a_very_tall_drawing_is_clamped_to_the_band():
    box = stage_box(W, H, px, is_data=True)
    out = fit_to_frame(Image.new("RGBA", (600, 3000)), box, W, H, px)
    assert out.height <= box[1]


def test_a_punctuation_beat_is_bigger_than_a_sticker():
    """520 put a 1:1 reaction at 13% of frame."""
    assert PUNCT_BOX >= 700
    box = stage_box(W, H, px, is_data=False)
    out = fit_to_frame(Image.new("RGBA", (1080, 1080)), box, W, H, px)
    assert out.width * out.height / (W * H) > 0.2


def test_a_degenerate_image_does_not_crash():
    box = stage_box(W, H, px, is_data=True)
    assert fit_to_frame(Image.new("RGBA", (0, 0)), box, W, H, px) is not None


# --------------------------------------------------------------------------
# The bands.
# --------------------------------------------------------------------------


def test_the_stage_starts_high_and_runs_tall():
    """360..1120 left the top fifth of the frame empty, and was too short for
    a square drawing to take the frame's width."""
    assert STAGE_Y <= 260
    assert STAGE_H >= 1080, "a 1:1 asset at full width needs 1080 of band"
    assert STAGE_Y + STAGE_H <= 1400, "the stage must stay clear of captions"


def test_the_hook_sits_above_the_stage():
    """Vertical video reads text-top, action-centre, captions-bottom. The
    hook used to render in the ledger band UNDER the artwork."""
    assert HOOK_Y < STAGE_Y
    assert HOOK_Y < LEDGER_Y


def test_the_ledger_is_below_the_stage():
    assert LEDGER_Y >= STAGE_Y + STAGE_H - 60


def test_the_stage_is_as_wide_as_the_frame():
    assert STAGE_MAX_W >= 1080


# --------------------------------------------------------------------------
# The measurement itself.
# --------------------------------------------------------------------------


def test_the_median_is_the_middle_of_the_data_beats():
    beats = [{"class": "data", "frac": 0.2}, {"class": "data", "frac": 0.6},
             {"class": "data", "frac": 0.4}, {"class": "punct", "frac": 0.9}]
    assert _median_coverage(beats, "data") == 0.4
    assert _median_coverage(beats, "punct") == 0.9


def test_an_even_count_averages_the_middle_pair():
    beats = [{"class": "data", "frac": 0.2}, {"class": "data", "frac": 0.6}]
    assert _median_coverage(beats, "data") == 0.4


def test_no_beats_of_a_class_is_zero_not_a_crash():
    assert _median_coverage([], "data") == 0.0
