"""Where kit artwork lands in the LONG, and what it looks like when it gets there.

The short engine was rebuilt around named bands and framing registers; the
long one was not, and the two diverged badly enough that a video could pass
every structural test in `test_render_long.py` while looking like a collage.

Three things were wrong and are asserted here:

* **The long addressed the kit by PATH**, so it got the raw first frame of the
  PNG. 39 reachable drawings played with their declared boxes empty, both
  blank layouts shipped the placeholder copy printed into them, and every
  one-shot froze on frame 1 — a drawing of nothing having happened yet.
* **The two-shot stacked three finished compositions**: a designed filler
  backdrop with its own giant ticker and grid, an evidence card on top, and a
  whole 16:9 host SLIDE over both, carrying its own headline and often its own
  illustration.
* **The host was sized like a cut-out** when the shots became composed 16:9
  cards, so at 82% of the frame height a "two-shot" host covered the panel.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.host import (
    HOST_BANKS,
    PANEL_FIGURES,
    _FIGURE_PARTS,
    panel_figure,
)
from pipeline.kit import load_kit
from pipeline.models import KIT_TAG_BLANKS, KIT_TAG_FAMILIES, TagType
from pipeline.parser_long import parse_long_script

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def kit():
    return load_kit(ROOT / "assets")


# --------------------------------------------------------------------------
# The grammar reaches the long parser too.
# --------------------------------------------------------------------------


def test_a_long_script_can_write_a_value_into_the_artwork(settings):
    raw = ("EXMPL is down sixty percent and nobody cares. "
           "[PROP: crushed-flat = -41%] The number lands on him. "
           "[TERM: owner earnings = what is left after keeping it alive] "
           "That is the whole idea. I will be up at three either way.")
    script, _ = parse_long_script(raw, "EXMPL", settings)
    by_type = {e.type: e for e in script.events}
    assert by_type[TagType.PROP].payload == "crushed-flat"
    assert by_type[TagType.PROP].values == {"": "-41%"}
    assert by_type[TagType.TERM].values == {
        "": "what is left after keeping it alive"}


def test_the_long_timeline_carries_the_values_to_the_renderer(settings):
    from pipeline.models import WordTimestamp
    from pipeline.timeline import build_long_timeline

    raw = ("EXMPL is down sixty percent and nobody cares at all. "
           "[PROP: crushed-flat = -41%] The number lands on him and stays. "
           "I will be up at three in the morning either way, as usual.")
    script, _ = parse_long_script(raw, "EXMPL", settings)
    words, cursor = [], 0
    for i, w in enumerate(script.narration.split()):
        start = script.narration.index(w, cursor)
        cursor = start + len(w)
        words.append(WordTimestamp(word=w, start=i * 0.3, end=i * 0.3 + 0.28,
                                   char_start=start, char_end=cursor))
    cues = build_long_timeline(script, words, words[-1].end)
    prop = next(c for c in cues if c.payload.get("tag") == "PROP")
    assert prop.payload["values"] == {"": "-41%"}


# --------------------------------------------------------------------------
# The two-shot is one composition.
# --------------------------------------------------------------------------


def test_the_two_shot_figure_is_a_cut_out_not_a_slide(kit):
    """Every HOST_BANKS entry is a complete 16:9 scene. Insetting one beside
    the evidence puts two finished compositions in one frame."""
    from PIL import Image
    import numpy as np

    figure = panel_figure(kit, 0)
    assert figure is not None
    assert figure.aspect == "1:1", "a 16:9 card brings its own background"
    alpha = np.asarray(Image.open(figure.frames[0]).convert("RGBA"))[..., 3]
    assert (alpha < 20).mean() > 0.8, (
        "the two-shot figure must be a cut-out — anything with a background "
        "paints a rectangle over the evidence beside it")


def test_no_panel_figure_is_a_limb_or_a_face(kit):
    """Half of `mascot/` is components for the old layer rig. `arm-gesture`
    in this list put a pair of disembodied arms next to the evidence."""
    for key in PANEL_FIGURES:
        leaf = key.rsplit("/", 1)[-1]
        assert not leaf.startswith(_FIGURE_PARTS), f"{key} is a component"
        assert kit.get(key) is not None, f"{key} is not in the kit"


def test_the_panel_figures_step_rather_than_repeat(kit):
    seen = [panel_figure(kit, i).key for i in range(len(PANEL_FIGURES))]
    assert len(set(seen)) == len(seen), "two adjacent two-shots share a pose"


def test_the_host_banks_are_still_whole_scenes(kit):
    """The distinction this rests on: a bank shot IS the frame, a panel figure
    stands in one. If a bank shot were 1:1 the two would have collapsed."""
    for role, keys in HOST_BANKS.items():
        for key in keys:
            asset = kit.get(key)
            if asset is None:
                continue
            assert asset.aspect == "16:9", f"{role}/{key} is not a full scene"


# --------------------------------------------------------------------------
# Every tag-reachable asset can be rendered for the long frame.
# --------------------------------------------------------------------------


def test_every_tag_reachable_asset_renders(settings, kit):
    """The audit that found all of the above: walk everything a long script
    can name and render it, rather than trusting that it would work."""
    from pipeline.kit_frames import render_still, strip_baked_furniture

    reachable: set[str] = set()
    for families in KIT_TAG_FAMILIES.values():
        for family in families:
            reachable.update(kit.family(family))
    reachable.update(v for v in KIT_TAG_BLANKS.values() if v in kit)
    assert len(reachable) > 60, "the tag families reach almost nothing"

    for key in sorted(reachable):
        asset = kit.get(key)
        img = strip_baked_furniture(render_still(asset, None, settings), asset)
        assert img.width and img.height, key


def test_the_blank_layouts_are_reachable_from_a_long_script(kit):
    """`[TERM: something-we-never-drew]` has to land on the blank layout, or
    the beat is lost. The long engine had no fallthrough at all."""
    for tag, blank in KIT_TAG_BLANKS.items():
        assert blank in kit, f"{tag.value} falls through to a missing layout"
        assert any(s.clear for s in kit.get(blank).slots), (
            f"{blank} must clear its placeholder copy before the real text")


# --------------------------------------------------------------------------
# Baked furniture is a placement rule, not a report.
#
# The long sample printed "Opinion / entertainment. Not financial advice."
# twice — once in the card's own face, once in the renderer's Space Mono — in
# four of the eight frames sampled across its runtime. The stripper was not at
# fault: it is timid by design, because a blanket crop of the same bands was
# measured against the library and damages 32 cards at the top and 75 at the
# bottom. The artwork broke the convention, `kit_doctor` reported it, and a
# report does not stop a frame reaching YouTube.
#
# These assert on SELECTION. A pixel test here would rot the first time the
# palette moves, and the property that matters is upstream of the pixels: a
# card that keeps its furniture is never chosen.
# --------------------------------------------------------------------------


def test_no_stuck_card_can_be_selected_for_a_long_form_beat(kit):
    """Every path that puts a chapter card on a rendered frame."""
    from pipeline.host import HOST_BANKS, shots

    stuck = kit.furniture_stuck()
    assert stuck, "the fixture kit is supposed to have some — else this is vacuous"

    for role in HOST_BANKS:
        chosen = {s.key for s in shots(kit, role)}
        assert chosen, f"the {role} bank has no usable shot left"
        assert not (chosen & stuck), \
            f"{role} can still place {sorted(chosen & stuck)}"

    # the tag path: every key a script can name, resolved the way a renderer
    # resolves it
    for tag, families in KIT_TAG_FAMILIES.items():
        for family in families:
            for key in kit.family(family):
                leaf = key.rsplit("/", 1)[-1]
                asset = kit.resolve_asset(families, leaf, placeable=True)
                assert asset is None or asset.key not in stuck, \
                    f"[{tag.value}: {leaf}] resolved to the stuck {asset.key}"


def test_a_beat_with_only_stuck_artwork_blocks_rather_than_falling_back(settings, kit):
    """A silent fallback to a stuck card is how this shipped. It blocks now."""
    from pipeline.gates import kit_doctor
    from pipeline.models import TagType

    # `[TABLE: …]` resolves against chapters/sector-comps, five of whose six
    # drawings keep their furniture — so this is a real key, not a made-up one.
    stuck_leaf = next(
        (k.rsplit("/", 1)[-1] for k in sorted(kit.furniture_stuck())
         if k.startswith("chapters/sector-comps/")), None)
    if stuck_leaf is None:
        pytest.skip("no stuck sector-comps card in this kit")

    class _Script:
        events = [type("E", (), {"type": TagType.TABLE, "payload": stuck_leaf})()]
        inline_events: list = []

    findings, stats = kit_doctor(_Script(), settings)
    blocking = [f for f in findings if f.severity == "block"]
    assert blocking, f"no blocking finding for [TABLE: {stuck_leaf}]"
    assert stuck_leaf in blocking[0].message, "the finding has to name the beat"
    assert "Artwork owed" in blocking[0].message


def test_the_work_order_lists_drawings_not_twins(kit, settings):
    """(b): the list Design works from. One row per card, not one per strip."""
    from pipeline.gates import FURNITURE_ASK, _furniture_work_order, kit_doctor_text

    order = _furniture_work_order(kit)
    assert order, "nothing owed — then the containment above is untestable"
    flat = [k for keys in order.values() for k in keys]
    assert set(flat) <= set(kit.furniture_stuck())
    for key in flat:
        leaf = key.rsplit("/", 1)[-1]
        assert not leaf.endswith(("-talk", "-blink", "-idle", "-idle-b")), \
            f"{key} is a twin of the card beside it — Design redraws one"
        assert key in kit.family(key.rsplit("/", 1)[0]), \
            f"{key} is not an independently pickable drawing"
    assert len(flat) < len(kit.furniture_stuck()), \
        "de-twinning removed nothing — the count overstates the ask"

    report = kit_doctor_text(settings)
    assert "ARTWORK OWED" in report
    assert FURNITURE_ASK in report, "the report has to say what is being asked for"
    for family in order:
        assert family in report, f"{family} is owed but not in the report"


def test_a_card_with_no_furniture_stays_usable(kit):
    """The distinction the containment turns on.

    "The strip did nothing" is not "the card carries furniture": three
    `how-the-money-is-made` drawings and `resigned-close/end-card` have none at
    all, and excluding them would cost usable artwork for no reason. The other
    direction matters more: `outro-subscribe` prints the disclaimer
    RIGHT-aligned, so the eraser's left-margin signature misses it and the
    sentence is on screen twice anyway.
    """
    from PIL import Image

    from pipeline.kit_frames import carries_baked_furniture, strip_baked_furniture

    stuck = kit.furniture_stuck()
    for key in ("chapters/resigned-close/end-card",
                "chapters/how-the-money-is-made/segments-pie"):
        asset = kit.get(key)
        if asset is None:
            continue
        img = Image.open(asset.frames[0]).convert("RGBA")
        assert strip_baked_furniture(img, asset) is img, \
            f"{key} was expected to have nothing to strip"
        assert not carries_baked_furniture(img, asset), f"{key} has no furniture"
        assert key not in stuck and kit.placeable(key)

    right = kit.get("chapters/resigned-close/outro-subscribe")
    if right is not None:
        img = Image.open(right.frames[0]).convert("RGBA")
        assert carries_baked_furniture(img, right), \
            "the right-aligned disclaimer has to be detected"
        assert not kit.placeable(right.key)
