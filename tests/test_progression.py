"""The room at minute fifteen is not the room at minute one.

Four devices — light, clutter, the evidence wall, the clock — run the whole
length of a LONG as functions of one number. The tests that matter are not
that `at()` returns a string: they are that every string it can return is a
concept the kit actually ships, in every register, and that each family reads
its OWN axis. A progression step naming a plate that does not exist is a
crash three-quarters of the way through a twelve-minute render.
"""

from __future__ import annotations

import pytest

from pipeline import progression as prog
from pipeline.kit_manifest import REGISTERS, kit_for
from pipeline.shots import load_format


def test_the_room_starts_in_daylight_and_ends_at_three_am():
    start, end = prog.at(0.0), prog.at(1.0)
    assert (start.light, start.clutter, start.wall) == (
        "light-daylight", "tidy", "empty")
    assert (end.light, end.clutter, end.wall) == ("light-3am", "3am", "full")


def test_progress_is_clamped_not_wrapped():
    assert prog.at(-4.0).light == prog.at(0.0).light
    assert prog.at(9.9).light == prog.at(1.0).light


@pytest.mark.parametrize("step", [v for _a, v in prog.LIGHT_STEPS])
def test_every_light_state_is_in_the_kit(step):
    # Group M is register-agnostic and 16:9 only — which is what makes
    # progression a LONG device and not something the verticals can have.
    kit = kit_for("marker")
    entry = kit.concept(step, "marker")
    w, h = entry.delivered
    assert w > h, f"{step} is not landscape; the light is a 16:9 asset"


@pytest.mark.parametrize("register", REGISTERS)
def test_every_clutter_and_wall_state_exists_in_every_register(register):
    """A room plate that only exists in marker breaks ballpoint at 75%."""
    kit = kit_for(register)
    fmt = load_format("long")
    families = {p.rpartition("--")[0] for p in
                (s.plate for s in fmt.shots if s.plate) if "--" in p}
    for family in sorted(families):
        for _at, state in prog.CLUTTER_STEPS:
            assert kit.has(f"{family}--{state}", register), (
                f"{family}--{state} missing in {register}")
    for _at, state in prog.WALL_STEPS:
        assert kit.has(f"evidence-wall-{state}", register)


def test_each_family_reads_its_own_axis():
    """`evidence-wall-tidy` does not exist. The wall and the room advance
    together but they are not the same scale, and handing the clutter state
    to the wall asked the kit for a plate nobody drew."""
    late = prog.at(0.9)
    assert prog.restate("room-wide-16--tidy", late) == "room-wide-16--3am"
    assert prog.restate("evidence-wall-empty", late) == "evidence-wall-full"


def test_a_concept_with_no_state_is_returned_unchanged():
    late = prog.at(0.9)
    for concept in ("dive-in", "chapter-stinger", "seated-talking", None):
        assert prog.restate(concept, late) == concept


def test_the_clock_reads_the_light():
    for _at, light in prog.LIGHT_STEPS:
        hour = prog.LIGHT_HOURS[light]
        h_ang, _m_ang = prog.clock_hands(hour)
        assert abs(h_ang - (hour % 12.0) * 30.0) < 1e-6


def test_only_additive_loops_are_composited():
    """loop-plant and loop-curtain REPLACE the plate's drawn furniture.

    Every room plate in this delivery ships with the plant and the curtain
    already drawn, so overlaying the loops gives the doubled outline the
    manifest warns about. They stay out until a plate without them exists.
    """
    from pipeline.kit_manifest import AMBIENT_REPLACING
    assert set(prog.AMBIENT_ADDITIVE_USED).isdisjoint(AMBIENT_REPLACING)
    for name in prog.AMBIENT_ADDITIVE_USED:
        assert name in prog.AMBIENT_PLACEMENT, (
            f"{name} is composited with no placement, so it lands at 0,0")


def test_only_the_long_turns_progression_on():
    """It is a declared property of the format, not a guess from the frame.

    Reading it off the aspect ratio switched four devices on for anything
    landscape, in silence. A future 16:9 ninety-second format has nowhere to
    travel and must be able to say so.
    """
    from pipeline.shots import available_formats
    on = [n for n in available_formats() if load_format(n).progression]
    assert on == ["long"]
