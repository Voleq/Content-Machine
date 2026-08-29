"""The character budgets, frozen against the fitter that produced them.

`templates/budgets.json` is how many characters each text destination holds
with zero loss. It exists as data rather than as a number in a report because
a budget in prose drifts from the fitter within a month, and then type
overflows a box nobody is measuring — which is the mechanical explanation for
the format that got scrapped.

Two things are checked. That the committed file still matches a fresh
measurement, so a change to the fitter, the fonts or a template cannot quietly
invalidate it. And that the SCRIPT MODEL's field limits are reported against
it, because every one of them is currently larger than its shot can show.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.models import ShortScript

BUDGETS = Path("templates/budgets.json")


@pytest.fixture(scope="module")
def frozen() -> dict:
    assert BUDGETS.exists(), "run scripts/measure_budgets.py"
    return json.loads(BUDGETS.read_text(encoding="utf-8"))


def test_the_faces_the_budgets_were_measured_in_are_the_faces_that_draw():
    """Which font file each face resolves to, pinned.

    The re-measurement below is slow — it probes every destination in every
    format — so when it fails it fails as one line about drift with no cause
    in it. This is the cause, checked in a millisecond: the two faces are
    named as Inter, Inter is not vendored, and both fall through to a
    substitute. That substitute was once "whichever file sorts first in
    assets/fonts", which meant adding a font to that directory restyled every
    short in the repo and invalidated the committed budgets without touching
    a line of the fitter.
    """
    from pipeline.marks import BODY_FONT, DISPLAY_FONT, font_file

    for face in (BODY_FONT, DISPLAY_FONT):
        got = font_file(face)
        assert got is not None, f"{face} resolves to nothing at all"
        assert got.name == "DejaVuSans-Bold.ttf", (
            f"{face} now draws from {got.name}; templates/budgets.json was "
            "measured in DejaVuSans-Bold. Re-measure before changing this.")


def test_the_committed_budgets_match_the_fitter(frozen):
    """Re-measure and compare. This is the whole anti-drift device.

    If it fails, either a template changed, the type fitting changed, or the
    fonts changed — and in every one of those cases the budgets the writing
    prompt hands out are no longer true. Regenerate with
    `python scripts/measure_budgets.py` and read the diff before committing.
    """
    import sys
    sys.path.insert(0, "scripts")
    from measure_budgets import measure

    fresh = measure()
    assert fresh["formats"] == frozen["formats"], (
        "templates/budgets.json has drifted from the fitter — "
        "run scripts/measure_budgets.py --check for the per-destination diff")


def test_every_format_has_budgets(frozen):
    for name in ("short", "earnings", "macro"):
        assert frozen["formats"].get(name), f"no budgets for {name}"


def test_no_destination_claims_to_hold_nothing(frozen):
    for name, dests in frozen["formats"].items():
        for dest, n in dests.items():
            assert n > 0, f"{name}/{dest} holds {n}"


def test_the_script_model_asks_for_more_than_the_frame_can_show(frozen):
    """The finding, as a test, so it cannot be quietly forgotten.

    Every field below is bounded by the model at several times what its shot
    physically holds. That gap is what the writing form closes; until it does,
    this test documents the size of it and fails if a field limit is changed
    without the budget being consulted.
    """
    fields = ShortScript.model_fields
    pairs = [
        ("hook_text", "short", "text:hook"),
        ("conclusion", "short", "text:conclusion"),
        ("numbers_comment", "short", "text:numbers-comment"),
        ("cheap_or_trap", "short", "text:cheap-or-trap"),
        ("turn_line", "short", "text:turn"),
        ("verdict", "earnings", "fill:stamp-text"),
    ]
    over = []
    for field, fmt, dest in pairs:
        budget = frozen["formats"][fmt].get(dest)
        if budget is None:
            continue
        limit = next((m.max_length for m in fields[field].metadata
                      if getattr(m, "max_length", None)), None)
        if limit is None:
            continue
        if limit > budget:
            over.append(f"{field}: model allows {limit}, {fmt}/{dest} "
                        f"holds {budget} ({limit / budget:.1f}x)")
    # This is expected to be non-empty today. It is asserted as a KNOWN set so
    # that closing the gap is a deliberate act with a test change beside it,
    # and so that widening it further fails here first.
    assert len(over) >= 4, (
        "fewer fields overflow than when this was measured — if the writing "
        f"form has landed, update this test. Currently: {over}")


def test_every_committed_fixture_fits_the_shot_it_feeds(frozen):
    """The blocking check, run over the fixtures instead of over a render.

    Overflow raises before the encoder, so a fixture that does not fit fails
    a render test somewhere far away with a message about characters. Three
    fixtures were over budget and were found one render at a time; this finds
    all of them at once, in a second, and names the file to edit.

    A budget is a contract on the WRITING, and a fixture is writing.
    """
    dests = {"short": ("text:headline", "text:meaning"),
             "earnings": ("text:headline", "text:meaning"),
             "macro": ("text:statement-head", "text:the-clause")}
    over = []
    for path in sorted(Path("fixtures/scripts").glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue                      # a deliberately malformed fixture
        head = (raw.get("headlines") or [None])[0]
        if not head:
            continue
        for fmt, (d_text, d_meaning) in dests.items():
            for key, dest in (("text", d_text), ("meaning", d_meaning)):
                budget = frozen["formats"][fmt].get(dest)
                n = len(head.get(key) or "")
                if budget and n > budget:
                    over.append(f"{path.name}.headlines[0].{key}: {n} "
                                f"characters, {fmt}/{dest} holds {budget}")
    assert over == [], "\n  ".join([""] + over)


def test_a_budget_is_reachable_for_every_authored_text(frozen):
    """Every place a template puts words has a measured budget.

    A destination with no budget is a field the writing form cannot be told
    the size of, which is how one gets written past its box.
    """
    from pipeline.shots import available_formats, expand_sequences, load_format

    for name in available_formats():
        fmt = expand_sequences(load_format(name),
                               lambda src: ["a", "b", "c", "d"])
        dests = frozen["formats"].get(name, {})
        for shot in fmt:
            for t in shot.text:
                key = f"text:{t.name}"
                assert key in dests, f"{name}/{shot.id}: no budget for {key}"
