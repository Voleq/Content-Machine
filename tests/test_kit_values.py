"""What gets written into the artwork, and how it is framed.

The 74 declared slots were unreachable for the whole life of the feature: a
named asset resolved, played its frames, and drew every box empty, because the
render only ever passed values for the three blank layouts. These cover the
route from the tag's text to the pixels — the grammar, the binding, the
registers that decide how big a beat lands, and the drawing-selection that
happens when the writer names nothing at all.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.kit import load_kit
from pipeline.kit_frames import (
    FULL_BLEED,
    PUNCH,
    STAGE,
    bind_slot_values,
    is_full_frame,
    punch_crop,
    render_still,
    strip_baked_furniture,
)
from pipeline.number_beats import NUMBER_BEATS, beat_for_row, classify, pick
from pipeline.tagging import parse_slot_values

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"


@pytest.fixture(scope="module")
def kit():
    return load_kit(ASSETS)


# --------------------------------------------------------------------------
# The grammar: [PROP: key = value] and its plural.
# --------------------------------------------------------------------------


def test_a_bare_value_is_offered_to_the_only_slot():
    assert parse_slot_values("crushed-flat = -41%") == ("crushed-flat",
                                                        {"": "-41%"})


def test_named_bindings_keep_their_names():
    key, values = parse_slot_values("see-saw = heavy:$1.1B, light:$40M")
    assert key == "see-saw"
    assert values == {"heavy": "$1.1B", "light": "$40M"}


def test_a_bare_list_binds_by_position():
    _, values = parse_slot_values("numbers-raining = -8%, -12%, -3%")
    assert values == {"#0": "-8%", "#1": "-12%", "#2": "-3%"}


def test_a_half_bound_tail_is_kept_whole_rather_than_split():
    """A comma inside one value is far likelier than a script that binds one
    slot by name and leaves the next anonymous. Guessing splits a figure in
    half; the render-time binder warns instead."""
    _, values = parse_slot_values("term-card = word:Moat, a durable advantage")
    assert list(values.values()) == ["word:Moat, a durable advantage"]


def test_a_key_with_no_value_carries_no_values():
    assert parse_slot_values("crushed-flat") == ("crushed-flat", {})
    assert parse_slot_values("crushed-flat =") == ("crushed-flat", {})


# --------------------------------------------------------------------------
# Binding: grammar output onto an asset's declared boxes.
# --------------------------------------------------------------------------


def test_a_single_value_fills_the_only_slot(kit):
    asset = kit.get("shorts/dennis-vs-numbers/crushed-flat")
    assert len(asset.slots) == 1
    values, warnings = bind_slot_values(asset, {"": "-41%"})
    assert values == {asset.slots[0].name: "-41%"}
    assert warnings == []


def test_named_values_reach_the_slots_they_name(kit):
    asset = kit.get("shorts/dennis-vs-numbers-2/see-saw-two-numbers")
    names = {s.name for s in asset.slots}
    assert {"heavy", "light"} <= names
    values, warnings = bind_slot_values(asset, {"heavy": "$1.1B", "light": "$40M"})
    assert values["heavy"] == "$1.1B"
    assert values["light"] == "$40M"
    assert warnings == []


def test_positional_values_land_in_declaration_order(kit):
    asset = kit.get("shorts/dennis-vs-numbers/numbers-raining")
    order = [s.name for s in asset.slots]
    raw = {f"#{i}": f"-{i}%" for i in range(3)}
    values, _ = bind_slot_values(asset, raw)
    assert [values[n] for n in order[:3]] == ["-0%", "-1%", "-2%"]


def test_a_name_no_slot_declares_is_reported_not_swallowed(kit):
    asset = kit.get("shorts/dennis-vs-numbers/crushed-flat")
    _, warnings = bind_slot_values(asset, {"nonesuch": "12"})
    assert warnings, "an unbindable name must say so — it is a typo in a script"
    assert "nonesuch" in " ".join(warnings)


# --------------------------------------------------------------------------
# ...and the other direction: a BOX WITH NOTHING IN IT.
# --------------------------------------------------------------------------
# The binder reported a value with nowhere to go, and a value naming a slot
# that does not exist, and said nothing whatsoever about a slot that received
# nothing — which is the only one of the three the viewer can see. It is a
# drawn, empty box in the middle of a beat, and one shipped in the committed
# sample: a lift shaft with six floors and a row of five numbers.


def test_a_box_with_nothing_in_it_is_reported(kit):
    """Six floors, four figures — two warnings, and they name which two.

    The library has no five-slot drawing, so this is 4-of-6 rather than the
    3-of-5 the report is written against; the property is the same and the
    asset is the one that actually shipped an empty box.
    """
    asset = kit.get("shorts/vertical-scenes-2/b2-elevator-drop")
    names = [s.name for s in asset.slots]
    assert len(names) == 6
    given = {n: f"-${i + 1}M" for i, n in enumerate(names[:4])}
    values, warnings = bind_slot_values(asset, given)

    assert values == given, "the bound values still bind"
    unfilled = [w for w in warnings if "no value" in w]
    assert len(unfilled) == 2, warnings
    assert all(any(n in w for w in unfilled) for n in names[4:]), unfilled
    assert not any(n in w for n in names[:4] for w in unfilled), \
        "a filled box must not be reported empty"


def test_a_tag_with_no_value_at_all_is_the_loudest_case_not_the_quietest(kit):
    """`[PROP: crushed-flat]` — no `= value`, every box empty.

    This is the one that shipped, and it was the one line the binder never
    reached: `if not values: return {}, []` was the first statement in it.
    The catalogue promises the writer otherwise — "WITHOUT the `= value` the
    drawing renders with its boxes EMPTY. Always give a figure."
    """
    asset = kit.get("shorts/dennis-vs-numbers/crushed-flat")
    values, warnings = bind_slot_values(asset, None)
    assert values == {}
    assert len(warnings) == 1 and asset.slots[0].name in warnings[0], warnings

    empty, empty_warnings = bind_slot_values(asset, {})
    assert empty == {} and empty_warnings == warnings, \
        "no `=` and an empty `=` are the same drawing with the same empty box"


def test_a_drawing_with_no_slots_is_still_a_no_op(kit):
    """Nothing to fill and nothing asked for: silence is correct here."""
    asset = next(kit.get(k) for k in kit.keys()
                 if kit.get(k) is not None and not kit.get(k).slots)
    assert bind_slot_values(asset, None) == ({}, [])


def test_a_box_a_layout_means_to_clear_is_not_an_empty_box(kit, settings):
    """The blank layouts declare `clear` on every slot.

    Their boxes carry dummy copy that an empty value ERASES — leaving one
    empty is what the layout is for, not an omission, and reporting it would
    make the warning worth ignoring.
    """
    from pipeline.kit_frames import unfilled_slots

    asset = kit.get("blanks/big-number-blank")
    assert asset.slots and all(s.clear for s in asset.slots)
    assert unfilled_slots(asset, {"figure": "6% a year"}) == []


# --------------------------------------------------------------------------
# The values actually reach the pixels.
# --------------------------------------------------------------------------


def test_a_filled_slot_changes_the_drawing(settings, kit):
    """The bug this whole area exists for: the asset resolved, the frames
    played, and every declared box came out empty."""
    asset = kit.get("shorts/dennis-vs-numbers/crushed-flat")
    slot = asset.slots[0].name
    blank = render_still(asset, None, settings)
    filled = render_still(asset, {slot: "-41%"}, settings)
    assert blank.tobytes() != filled.tobytes()


def test_a_clear_slot_is_wiped_even_with_no_value(settings, kit):
    """A blank layout's boxes ship with dummy copy printed in them. Skipping a
    slot because its value was empty is how "What the number is" went out
    under a real figure."""
    asset = kit.get("blanks/big-number-blank")
    clearing = [s for s in asset.slots if s.clear]
    assert clearing, "the blank layouts declare `clear` boxes"
    untouched = render_still(asset, None, settings)
    partial = render_still(asset, {clearing[0].name: ""}, settings)
    assert untouched.tobytes() != partial.tobytes()


# --------------------------------------------------------------------------
# Framing registers.
# --------------------------------------------------------------------------


def test_a_vertical_scene_is_recognised_as_the_whole_frame(kit):
    asset = kit.get("shorts/vertical-scenes/b-towering-chart")
    assert asset.aspect == "9:16"
    assert is_full_frame(asset, (1080, 1920))


def test_a_square_prop_is_not_the_whole_frame(kit):
    asset = kit.get("shorts/dennis-vs-numbers/crushed-flat")
    assert not is_full_frame(asset, (1080, 1920))


def test_the_punch_register_crops_and_keeps_the_aspect(settings, kit):
    asset = kit.get("shorts/dennis-vs-numbers/crushed-flat")
    img = render_still(asset, None, settings)
    cropped = punch_crop(img, asset)
    assert cropped.width < img.width and cropped.height < img.height
    assert abs(cropped.width / cropped.height - img.width / img.height) < 0.02


def test_a_punch_never_crops_a_slot_out_of_frame(settings, kit):
    """An asset with two slots is a COMPARISON. Cropping the see-saw around
    its first slot showed $1.1B on a tilted plank with the $40M it is being
    weighed against outside the frame."""
    for key in ("shorts/dennis-vs-numbers-2/see-saw-two-numbers",
                "shorts/dennis-vs-numbers/numbers-raining",
                "shorts/dennis-vs-numbers/crushed-flat"):
        asset = kit.get(key)
        img = render_still(asset, None, settings)
        scale = max(asset.export_scale or 1, 1)
        boxes = [s.scaled(scale) for s in asset.slots]
        span_w = max(b[0] + b[2] for b in boxes) - min(b[0] for b in boxes)
        span_h = max(b[1] + b[3] for b in boxes) - min(b[1] for b in boxes)
        cropped = punch_crop(img, asset)
        assert cropped.width >= span_w and cropped.height >= span_h, (
            f"{key}: the punch crops to {cropped.size} but its slots span "
            f"{span_w}x{span_h} — a declared box lands off-frame")


def test_a_punch_still_tightens_when_it_can(settings, kit):
    asset = kit.get("shorts/dennis-vs-numbers-2/see-saw-two-numbers")
    img = render_still(asset, None, settings)
    assert punch_crop(img, asset).width < img.width


def test_the_registers_are_three_distinct_names():
    assert len({FULL_BLEED, STAGE, PUNCH}) == 3


# --------------------------------------------------------------------------
# Reaching for the numbers batch without being asked.
# --------------------------------------------------------------------------


def test_a_rising_series_reads_as_up():
    assert classify([400.0, 452.0, 471.0, 496.0], "Revenue") == "up"


def test_a_deepening_loss_is_a_fall_not_a_scale():
    """-8M to -89M is an eleven-fold change and emphatically a fall. Checking
    magnitude before direction called it "scale" and reached for a wheelbarrow
    of cash."""
    assert classify([-8.0, -25.0, -49.0, -70.0, -89.0], "Net income") == "down"


def test_a_large_rise_is_about_scale():
    assert classify([40.0, 1100.0], "Cash") == "scale"


def test_a_debt_row_is_a_burden_whatever_it_does():
    assert classify([100.0, 120.0], "Total debt") == "burden"
    assert classify([120.0, 100.0], "Cash burn") == "burden"


def test_every_bank_key_exists_in_the_kit(kit):
    """A bank naming artwork that does not ship picks nothing and the beat is
    silently lost."""
    missing = [k for keys in NUMBER_BEATS.values() for k in keys if k not in kit]
    assert not missing, f"number-beat banks name missing artwork: {missing}"


def test_the_pick_is_deterministic_for_a_script(kit):
    a = pick(kit, "down", seed="sha-abc")
    b = pick(kit, "down", seed="sha-abc")
    assert a == b and a in NUMBER_BEATS["down"]


def test_a_drawing_the_writer_already_named_is_not_offered_again(kit):
    """Excluding after the draw lost the beat entirely whenever the dice
    landed on a tagged prop; the bank has to be filtered first."""
    taken = pick(kit, "down", seed="sha-abc")
    again = pick(kit, "down", seed="sha-abc", exclude=[taken])
    assert again is not None and again != taken


def test_excluding_the_whole_bank_returns_nothing(kit):
    assert pick(kit, "down", seed="s", exclude=NUMBER_BEATS["down"]) is None


def test_a_row_gets_a_drawing_carrying_its_latest_figure(kit):
    got = beat_for_row(kit, "Net income",
                       ["-$8M", "-$25M", "-$49M", "-$70M", "-$89M"], seed="sha")
    assert got is not None
    key, values = got
    assert key in NUMBER_BEATS["down"]
    assert list(values.values()) == ["-$89M"], "the beat is about the figure said"


def test_a_row_with_no_values_gets_no_drawing(kit):
    assert beat_for_row(kit, "Revenue", [], seed="sha") is None


# --------------------------------------------------------------------------
# ...and the full-frame batch, which reached for a drawing it could not fill.
# --------------------------------------------------------------------------
# Nobody writes these on a tag: a key-number beat picks one off the number.
# Three of the eleven are built around a SERIES — eight rungs, six floors, six
# bricks — and five years of accounts fills none of them, so the renderer
# chose a lift shaft for a five-value row and drew the sixth floor empty. That
# is the frame at t≈40s of the committed sample.


def test_the_full_frame_batch_never_picks_a_drawing_the_row_cannot_fill(kit):
    """Every scene it can choose, for every row shape a script can have."""
    from pipeline.kit_frames import unfilled_slots
    from pipeline.vertical_beats import VERTICAL_BEATS
    from pipeline.vertical_beats import beat_for_row as vertical_beat_for_row

    rows = [
        ("Net income", ["-$8M", "-$25M", "-$49M", "-$70M", "-$89M"]),
        ("Revenue", ["$400M", "$452M", "$471M", "$491M", "$496M"]),
        ("Total debt", ["$1.1B", "$1.4B", "$1.9B"]),
        ("Cash", ["$40M"]),
    ]
    for label, values in rows:
        for seed in (f"s{i}" for i in range(24)):
            got = vertical_beat_for_row(kit, label, values, seed=seed)
            assert got is not None, f"{label} reached for nothing at {seed}"
            key, bound = got
            asset = kit.get(key)
            assert unfilled_slots(asset, bound) == [], (
                f"{label} ({len(values)} figures) reached for {key}, which "
                f"declares {len(asset.slots)} boxes — "
                f"{unfilled_slots(asset, bound)} would render empty")

    # And the series scenes are still reachable — the fix is a filter on the
    # choice, not a quiet removal of three drawings from the library.
    series = [k for keys in VERTICAL_BEATS.values() for k in keys
              if kit.get(k) is not None and len(kit.get(k).slots) > 1]
    assert series, "no multi-slot vertical scene in the banks to check"
    long_row = [f"-${i}M" for i in range(1, 9)]
    reached = {vertical_beat_for_row(kit, "Net income", long_row, seed=f"s{i}")[0]
               for i in range(40)}
    assert reached & set(series), \
        "a row long enough to fill one still never reaches a series scene"


# --------------------------------------------------------------------------
# Baked long-form furniture.
# --------------------------------------------------------------------------


def test_the_host_cards_lose_their_placeholder_ticker(kit):
    """The chapter cards paint a ticker chip and a disclaimer into the PNG.
    A short draws both itself, so leaving them on puts a hard-coded `GYMX`
    from the design file on screen beside our own `$EXMPL`."""
    from PIL import Image

    asset = kit.get("chapters/cold-open/at-desk-open")
    src = Image.open(asset.frames[0]).convert("RGBA")
    out = strip_baked_furniture(src, asset)
    assert out is not src, "the host's own card must come out clean"

    import numpy as np

    def ink(img, box):
        a = np.asarray(img.crop(box)).astype(int)
        return int(((a[..., :3].mean(axis=2) < 120) & (a[..., 3] > 80)).sum())

    chip = (60, 70, 500, 108)
    assert ink(src, chip) > 200, "the source really does carry a chip"
    assert ink(out, chip) == 0


def test_a_card_with_artwork_in_the_band_is_left_alone(kit):
    """The gate fails safe. A blanket crop of the same bands was measured
    against the library and would have damaged 32 cards at the top and 75 at
    the bottom — legs, chart axes and table rules all cross there."""
    from PIL import Image

    asset = kit.get("chapters/capital-allocation/uses-of-cash")
    src = Image.open(asset.frames[0]).convert("RGBA")
    assert strip_baked_furniture(src, asset) is src


def test_a_square_prop_is_never_touched(kit):
    from PIL import Image

    asset = kit.get("shorts/dennis-vs-numbers/crushed-flat")
    src = Image.open(asset.frames[0]).convert("RGBA")
    assert strip_baked_furniture(src, asset) is src
