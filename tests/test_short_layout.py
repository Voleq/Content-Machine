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
    _roll_frames_matched,
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


# --------------------------------------------------------------------------
# The marks.
#
# `marks/` ships twelve drawings and the pipeline reached one of them — the
# ring on the price chart. `[SCRIBBLE: …]` drew a procedural ellipse over
# artwork that already existed, and it only had three names for it.
#
# The golden set does not sample the callout's 2.1s window, so this is the
# pixel evidence that the real mark is what gets drawn.
# --------------------------------------------------------------------------


def _ink(img) -> np.ndarray:
    """The alpha silhouette of a mark, as a boolean mask."""
    return np.array(img.convert("RGBA"))[..., 3] > 40


def test_a_scribble_draws_the_kit_mark_not_a_drawn_stand_in():
    """Every style in the vocabulary resolves to its own drawing.

    Compared against the artwork's own silhouette rather than against "some
    ink appeared": a procedural fallback also draws ink, and the failure this
    guards is exactly the fallback quietly taking over.
    """
    from pipeline.rasters import (
        SCRIBBLE_MARKS,
        fitted_mark,
        mark_frames,
        scribble_callout_frames,
    )

    for style, (key, fallback) in sorted(SCRIBBLE_MARKS.items()):
        art = fitted_mark(SETTINGS, 400, 240, style=style)
        assert art is not None, f"{style} resolves no artwork ({key})"
        drawn = mark_frames(SETTINGS, 400, 240, style=style, draw_seconds=0.4)[-1]
        overlap = (_ink(drawn) & _ink(art)).sum() / max(_ink(art).sum(), 1)
        assert overlap > 0.9, (
            f"{style} drew something other than {key} "
            f"({overlap:.0%} of the artwork's ink)")

        # and the same mark reaches the callout the renderer composites
        callout = scribble_callout_frames(
            SETTINGS, 400, 380, style=style, target="Net income",
            fps=30, hold_seconds=0.1)[-1]
        assert _ink(callout)[:240].sum() > 0.5 * _ink(art).sum(), \
            f"{style}: the callout's mark band is emptier than the artwork"


def test_a_kit_with_no_mark_still_draws_one():
    """Decoration is never fatal — the chart's rule, for every mark.

    `settings=None` is the "kit not ingested" case, and an unknown style is the
    "writer typed something new" case. Both draw, neither raises.
    """
    from pipeline.rasters import mark_frames

    for settings, style in ((None, "check"), (SETTINGS, "not-a-mark")):
        frames = mark_frames(settings, 400, 240, style=style, draw_seconds=0.3)
        assert frames and frames[-1].size == (400, 240)
        assert _ink(frames[-1]).sum() > 200, \
            f"the stand-in for {style!r} drew nothing"


def test_the_scribble_vocabulary_is_the_artwork_that_exists():
    """The mapping table and the enum say the same thing, both ways.

    Three names against twelve marks is how nine drawings stayed dead; a
    fourteenth name with no drawing behind it would be the same bug pointed the
    other way.
    """
    from pipeline.kit import load_kit
    from pipeline.models import ScribbleStyle
    from pipeline.rasters import SCRIBBLE_MARKS

    kit = load_kit(SETTINGS.assets_dir)
    assert {s.value for s in ScribbleStyle} == set(SCRIBBLE_MARKS), \
        "a style a writer can type must have a row in the mapping table"
    for style, (key, fallback) in SCRIBBLE_MARKS.items():
        assert kit.get(key) is not None, f"{style} names missing artwork {key}"
        assert fallback in ("circle", "arrow", "underline"), \
            f"{style} falls back to {fallback!r}, which nothing draws"
    # Every mark in the family is reachable from a script.
    named = {key for key, _ in SCRIBBLE_MARKS.values()}
    unreachable = [k for k in kit.family("marks") if k not in named]
    assert not unreachable, f"artwork nothing can ask for: {unreachable}"


# --------------------------------------------------------------------------
# The $TICKER chip states a direction or states nothing.
# --------------------------------------------------------------------------
# It was filled GREEN unconditionally, so a SHORT about a 48% drawdown carried
# a bright green $SNDK in the corner of every frame. The channel rule — stated
# in thumbnail.py and enforced by metric_colour — is that green is UP ONLY.
# A chip that is green on every video says nothing, which is the argument
# 87f2839 made when it took GOLD off the thumbnail for being on every one.


def _dominant_fill(img):
    from collections import Counter

    px = [p[:3] for p in img.convert("RGBA").getdata() if p[3] > 200]
    return Counter(px).most_common(1)[0][0]


def test_the_ticker_chip_carries_the_move(settings):
    from pipeline.rasters import GREEN, RED, ticker_pill

    assert _dominant_fill(ticker_pill(settings, "SNDK", direction="up")) == GREEN
    assert _dominant_fill(ticker_pill(settings, "SNDK", direction="down")) == RED


def test_the_ticker_chip_is_never_decoratively_green(settings):
    """No move to report means ink on paper — not green by default."""
    from pipeline.rasters import GREEN, ticker_pill

    for d in (None, "", "sideways"):
        assert _dominant_fill(ticker_pill(settings, "SNDK", direction=d)) != GREEN


def test_the_chip_is_deterministic_and_keeps_its_size(settings):
    """Same arguments, byte-identical output; and the colour must not move the
    chip, because every overlay near it is positioned against its box."""
    from pipeline.rasters import ticker_pill

    a = ticker_pill(settings, "SNDK", direction="up")
    b = ticker_pill(settings, "SNDK", direction="up")
    assert a.tobytes() == b.tobytes()
    assert a.size == ticker_pill(settings, "SNDK", direction="down").size
    assert a.size == ticker_pill(settings, "SNDK").size


def test_a_down_short_does_not_render_a_green_chip(settings, tmp_path):
    """End to end: the renderer must pass the chart's own direction through,
    not just be capable of it."""
    import json

    from pipeline.parser_short import parse_short_script
    from pipeline.render_short import render_short
    from pipeline.tts import TTSEngine

    raw = json.loads((Path(__file__).resolve().parents[1] / "fixtures" /
                      "scripts" / "short_valid.json").read_text(encoding="utf-8"))
    script, _ = parse_short_script(json.dumps(raw), settings)
    tts = TTSEngine(settings).synthesize(script.audio_script, "short",
                                         events=script.inline_events)
    out, manifest_path = render_short(script, tts, tmp_path, settings)
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))

    from PIL import Image

    from pipeline.rasters import GREEN

    pill = next(p for p in tmp_path.rglob("ticker_pill.png"))
    fill = _dominant_fill(Image.open(pill))
    if manifest["chart"]["direction"] == "down":
        assert fill != GREEN, "a down-move rendered a green chip"
    else:
        assert fill == GREEN


# --------------------------------------------------------------------------
# A counted-in beat keeps its register for the whole roll.
# --------------------------------------------------------------------------


def _drawing(w: int, h: int):
    """A transparent canvas with a stroke on it — a kit asset's alpha shape."""
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    img.paste((35, 35, 38, 255), (w // 4, h // 4, w // 2, h // 2))
    return img


def test_a_rolled_full_bleed_beat_is_opaque_on_every_frame():
    """The regression: it was opaque for exactly one frame.

    A figure ARRIVES by counting, so a full-frame scene with a `number` slot
    renders as a roll. Only frame 0 went through `cover_on_paper`; the rest
    were resized raw, so one frame in, the beat went transparent and the
    gut-check sheet showed through the drawing meant to replace it.
    """
    from pipeline.kit_frames import FULL_BLEED

    frames = [_drawing(1080, 1920) for _ in range(4)]
    first = Image.new("RGBA", (W, H), (242, 242, 239, 255))
    out = _roll_frames_matched(frames, first, FULL_BLEED)
    assert len(out) == len(frames)
    for i, frame in enumerate(out):
        assert frame.size == (W, H), i
        assert frame.getchannel("A").getextrema() == (255, 255), \
            f"frame {i} of the roll is transparent — the sheet shows through"


def test_a_staged_roll_still_matches_the_first_frame_exactly():
    """The other half of the rule: every frame of a roll is the same drawing
    with a different figure in it, so re-fitting each one would let the beat
    breathe by a pixel as the digits change width."""
    from pipeline.kit_frames import STAGE

    frames = [_drawing(900, 900) for _ in range(3)]
    first = frames[0].resize((760, 760), Image.LANCZOS)
    out = _roll_frames_matched(frames, first, STAGE)
    assert [f.size for f in out] == [(760, 760)] * 3
