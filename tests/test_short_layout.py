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

import numpy as np
import pytest
from PIL import Image

from config import Settings
from pipeline.rasters import (
    SHANTELL,
    headline_card_frames,
    roll_steps,
    text_panel_frames,
)

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
SETTINGS = Settings()


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


# --------------------------------------------------------------------------
# Figures roll to their value wherever they land.
#
# `count_up_frames` only ever fired on a zoom cue, so the numbers sheet
# counted and every other figure in the short appeared fully formed — the
# driver headline, the payoff line, every slot on every drawing.
#
# The hard part is not the count, it is doing it WITHOUT re-wrapping the
# sentence around the digits. Both display faces have proportional figures,
# so re-rendering "fell 0%" -> "fell 41%" slides every word after the number.
# --------------------------------------------------------------------------


def test_roll_steps_lands_on_the_value_and_keeps_its_units():
    steps = roll_steps("$4.1B", 10)
    assert steps[0] == "$0.0B"
    assert steps[-1] == "$4.1B"
    assert len(steps) == 11


def test_a_string_with_no_figure_does_not_roll():
    assert roll_steps("a press release", 10) is None


def test_the_headline_figure_rolls():
    card, roll = headline_card_frames(
        SETTINGS, "Orders fell 41% after the licence changed",
        meaning="the buyer left", width=880, font_size=32, fps=30, seconds=0.6)
    assert roll is not None
    assert all(f.size == card.size for f in roll)
    assert roll[-1] is card, "the held frame must be the card itself"


def test_the_roll_repaints_only_the_digits():
    """The measurement that says this is a counter and not a wobble.

    Every pixel that changes across the roll has to sit inside the box the
    final figure occupies. Anything outside it is a word that moved.
    """
    card, roll = headline_card_frames(
        SETTINGS, "Orders fell 41% after the licence changed",
        meaning="the buyer left", width=880, font_size=32, fps=30, seconds=0.6)
    base = np.array(card)
    xs: list[int] = []
    for f in roll:
        changed = np.argwhere((np.array(f) != base).any(axis=2))
        if changed.size:
            xs += [changed[:, 1].min(), changed[:, 1].max()]
    assert xs, "nothing changed — the figure never rolled"
    # "41" at 32px is under 40px wide; a reflowed sentence would run to the
    # card's full 880.
    assert max(xs) - min(xs) < 60, f"the roll moved pixels across {max(xs)-min(xs)}px"


def test_a_headline_with_no_figure_is_the_still_it_always_was():
    card, roll = headline_card_frames(
        SETTINGS, "A press release, not a purchase order",
        meaning="nobody bought anything", width=880, font_size=32)
    assert roll is None
    assert card.size[0] == 880


def test_the_ledger_line_rolls_too():
    img, roll = text_panel_frames(
        SETTINGS, "You are paying 34 times earnings for a maybe.",
        fps=30, seconds=0.6, width=960, font_name=SHANTELL, font_size=48,
        bg=(250, 249, 246, 246))
    assert roll is not None
    assert all(f.size == img.size for f in roll)


def test_a_ledger_line_with_no_figure_stays_a_png():
    _, roll = text_panel_frames(
        SETTINGS, "That is the whole trade.", fps=30, width=960,
        font_name=SHANTELL, font_size=48, bg=(250, 249, 246, 246))
    assert roll is None
