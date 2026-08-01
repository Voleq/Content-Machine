"""The SHORT pacing contract, exercised on both sides.

`plan_short_pacing` had no direct coverage at all: the rules were reachable
only through a render, and the one fixture that reached them under-populated
its runtime, so the event-count band had only ever been checked from below.
That is the same shape as the bug this rebuild is about — a rule that exists,
runs, and is never actually tested against the case it was written for.

Every rule gets a test that would fail if the rule were deleted:

* a data beat holds 3-8s and is never cut short;
* punctuation stays 0.6-2s;
* two data beats never land on top of each other;
* a data beat with no room before the payoff is dropped, not flashed;
* Dennis returns every four to five beats, counting the fixed beats too;
* the event count is warned about above the band as well as below it.
"""

from __future__ import annotations

import pytest

from pipeline.models import Cue, CueKind
from pipeline.timeline import (
    SHORT_DATA_HOLD_S,
    SHORT_EVENTS_PER_75S,
    SHORT_HOST_EVERY,
    SHORT_PUNCT_HOLD_S,
    plan_short_pacing,
)

DURATION = 75.0


def data(t: float, value: str = "big-number", tag: str = "BIGNUM") -> Cue:
    lo, hi = SHORT_DATA_HOLD_S
    return Cue(t=t, kind=CueKind.BIGNUM,
               payload={"value": value, "tag": tag, "class": "data",
                        "hold": lo, "min_hold": lo, "max_hold": hi})


def punct(t: float, value: str = "crushed-flat") -> Cue:
    lo, hi = SHORT_PUNCT_HOLD_S
    return Cue(t=t, kind=CueKind.PROP,
               payload={"value": value, "tag": "PROP", "class": "punct",
                        "hold": lo, "min_hold": lo, "max_hold": hi})


def frame(kind: CueKind, t: float, **payload) -> Cue:
    return Cue(t=t, kind=kind, payload=payload)


def skeleton(payoff: float = 66.0) -> list[Cue]:
    """The fixed beats every short has, so the host cadence has something to
    count and the payoff exists to be pushed against."""
    return [
        frame(CueKind.HOST_OPEN, 0.0, until=4.0),
        frame(CueKind.HOOK, 0.0, text="hook", until=4.0),
        frame(CueKind.HEADLINE, 8.0, index=0, text="h0", until=20.0),
        frame(CueKind.HEADLINE, 14.0, index=1, text="h1", until=20.0),
        frame(CueKind.NUMBERS, 34.0, rows=3, until=DURATION),
        frame(CueKind.CHEAP_OR_TRAP, 56.0, text="trap", until=payoff),
        frame(CueKind.CONCLUSION, payoff, text="Noise.", until=DURATION),
        frame(CueKind.HOST_CLOSE, payoff, until=DURATION),
    ]


# A tag load that lands the whole cut inside the 18-22 band: data beats with
# punctuation between them, spread across the runtime.
WELL_PACED = [punct(8.0), data(14.0), punct(22.0), data(28.0),
              punct(38.0), data(44.0), punct(52.0), punct(60.0)]


def by_kind(cues: list[Cue], kind: CueKind) -> list[Cue]:
    return [c for c in cues if c.kind is kind]


def evidence(cues: list[Cue]) -> list[Cue]:
    return [c for c in cues if c.payload.get("class") in ("data", "punct")]


# --------------------------------------------------------------------------
# Rule 1 — a data beat is never cut short.
# --------------------------------------------------------------------------


def test_a_data_beat_holds_at_least_its_minimum():
    out, _ = plan_short_pacing(skeleton() + [data(20.0)], DURATION)
    beat = evidence(out)[0]
    assert beat.payload["hold"] >= SHORT_DATA_HOLD_S[0]


def test_a_crowding_beat_does_not_shorten_the_one_before_it():
    """A later tag is pushed out; it never truncates what is being read."""
    out, _ = plan_short_pacing(
        skeleton() + [data(20.0), punct(20.4)], DURATION)
    first, second = evidence(out)
    assert first.payload["hold"] >= SHORT_DATA_HOLD_S[0]
    assert second.t >= first.t + first.payload["hold"], \
        "the punctuation cut into the data beat instead of waiting"


def test_a_data_beat_is_capped_so_it_does_not_stall_the_cut():
    """Alone in a forty-second gap it still lets go after eight seconds."""
    out, _ = plan_short_pacing(skeleton(payoff=70.0) + [data(20.0)], 80.0)
    assert evidence(out)[0].payload["hold"] <= SHORT_DATA_HOLD_S[1]


def test_a_data_beat_with_no_room_before_the_payoff_is_dropped():
    """An unreadable beat is worse than a missing one, and it says so."""
    out, warnings = plan_short_pacing(
        skeleton(payoff=60.0) + [data(59.0, value="too-late")], DURATION)
    assert not evidence(out), "the beat was kept and will flash past"
    assert any("too-late" in w and "dropped" in w for w in warnings)


# --------------------------------------------------------------------------
# Rule 2 — punctuation stays punctuation.
# --------------------------------------------------------------------------


def test_punctuation_is_held_inside_its_band():
    out, _ = plan_short_pacing(
        skeleton() + [punct(20.0), punct(45.0)], DURATION)
    for beat in evidence(out):
        lo, hi = SHORT_PUNCT_HOLD_S
        assert lo <= beat.payload["hold"] <= hi


def test_punctuation_never_gets_a_data_beats_hold():
    """The two classes are the whole rhythm; a reaction held for five seconds
    is a slideshow with a joke in it."""
    out, _ = plan_short_pacing(skeleton() + [punct(20.0)], DURATION)
    assert evidence(out)[0].payload["hold"] < SHORT_DATA_HOLD_S[0]


# --------------------------------------------------------------------------
# Rule 3 — never two data beats adjacent.
# --------------------------------------------------------------------------


def test_two_data_beats_are_separated():
    out, warnings = plan_short_pacing(
        skeleton() + [data(20.0, value="first"), data(20.2, value="second")],
        DURATION)
    first, second = evidence(out)
    gap = second.t - (first.t + first.payload["hold"])
    assert gap >= SHORT_PUNCT_HOLD_S[0] - 1e-6, \
        "the second data beat lands before the first can be read"
    assert any("second" in w and "pushed" in w for w in warnings)


def test_two_data_beats_already_far_apart_are_not_warned_about():
    """A warning that fires on a normal edit is a warning nobody reads — and
    it used to claim a beat had been "moved" when nothing had moved."""
    out, warnings = plan_short_pacing(
        skeleton() + [data(16.0, value="first"), data(40.0, value="second")],
        DURATION)
    assert [c.t for c in evidence(out)] == [16.0, 40.0]
    assert not any("pushed" in w for w in warnings)


def test_punctuation_between_two_data_beats_is_enough():
    """That is what punctuation is FOR — it does not need pushing apart."""
    out, warnings = plan_short_pacing(
        skeleton() + [data(16.0), punct(20.0), data(24.0, value="second")],
        DURATION)
    assert len(evidence(out)) == 3
    assert not any("pushed" in w for w in warnings)


# --------------------------------------------------------------------------
# Rule 4 — Dennis comes back.
# --------------------------------------------------------------------------


def test_the_host_returns_every_few_beats():
    out, _ = plan_short_pacing(
        skeleton() + [punct(18.0), data(24.0), punct(40.0), data(46.0)],
        DURATION)
    assert by_kind(out, CueKind.HOST_BEAT), "Dennis never comes back"


def test_the_host_cadence_counts_the_fixed_beats_too():
    """A short whose evidence is the fixed cards still spends forty seconds
    away from his face. Counting only tagged beats meant a script with three
    of them never brought him back at all."""
    out, _ = plan_short_pacing(skeleton() + [punct(20.0)], DURATION)
    assert by_kind(out, CueKind.HOST_BEAT)


def test_a_host_return_is_never_a_flicker():
    from pipeline.timeline import MIN_HOST_RETURN_S

    out, _ = plan_short_pacing(
        skeleton() + [punct(18.0), data(24.0), punct(40.0), data(46.0)],
        DURATION)
    for beat in by_kind(out, CueKind.HOST_BEAT):
        assert float(beat.payload["until"]) - beat.t >= MIN_HOST_RETURN_S


def test_a_host_return_never_lands_after_the_payoff():
    payoff = 60.0
    out, _ = plan_short_pacing(
        skeleton(payoff=payoff) + [punct(18.0), data(24.0), punct(40.0)],
        DURATION)
    for beat in by_kind(out, CueKind.HOST_BEAT):
        assert beat.t < payoff


# --------------------------------------------------------------------------
# Rule 5 — the event-count band, from BOTH sides.
# --------------------------------------------------------------------------


def test_too_few_events_reads_as_a_slideshow():
    out, warnings = plan_short_pacing(skeleton() + [punct(20.0)], DURATION)
    assert any("slideshow" in w for w in warnings)


def test_too_many_events_says_something_will_flash_past():
    """The side that had never been exercised. A script that tags every
    sentence produces a cut nobody can follow, and the count is the only
    thing that notices."""
    crowd = [punct(6.0 + i * 1.8) for i in range(22)]
    out, warnings = plan_short_pacing(skeleton() + crowd, DURATION)
    assert any("flash past" in w for w in warnings), warnings
    assert not any("slideshow" in w for w in warnings)


def test_a_well_populated_short_is_not_warned_about_at_all():
    """The band is a real target, not a direction — a cut inside it produces
    no pacing warning of any kind."""
    out, warnings = plan_short_pacing(skeleton() + WELL_PACED, DURATION)
    assert not any("slideshow" in w or "flash past" in w for w in warnings), \
        warnings


@pytest.mark.parametrize("duration", [45.0, 60.0, 75.0, 90.0])
def test_the_band_scales_with_the_runtime(duration):
    """18-22 per 75s, not 18-22 per video: a 45-second cut with 20 events is
    frantic and a 90-second one with 20 is fine."""
    lo, hi = SHORT_EVENTS_PER_75S
    _, warnings = plan_short_pacing(skeleton() + [punct(20.0)], duration)
    band = [w for w in warnings if "band" in w]
    assert band, "the count is always reported against the band"
    assert f"{lo * duration / 75.0:.0f}-{hi * duration / 75.0:.0f}" in band[0]


# --------------------------------------------------------------------------
# Shape.
# --------------------------------------------------------------------------


def test_a_short_with_no_tags_is_returned_untouched():
    cues = skeleton()
    out, warnings = plan_short_pacing(list(cues), DURATION)
    assert [c.kind for c in out] == [c.kind for c in cues]
    assert warnings == []


def test_the_output_stays_sorted_and_keeps_the_fixed_beats():
    out, _ = plan_short_pacing(
        skeleton() + [data(46.0), punct(18.0), data(24.0)], DURATION)
    assert [c.t for c in out] == sorted(c.t for c in out)
    for kind in (CueKind.HOOK, CueKind.NUMBERS, CueKind.CONCLUSION,
                 CueKind.HOST_OPEN, CueKind.HOST_CLOSE):
        assert by_kind(out, kind), f"{kind} was dropped by the pacing pass"


def test_host_every_is_configurable_and_actually_drives_the_cadence():
    tight, _ = plan_short_pacing(skeleton() + WELL_PACED, DURATION, host_every=2)
    loose, _ = plan_short_pacing(skeleton() + WELL_PACED, DURATION,
                                 host_every=SHORT_HOST_EVERY)
    assert len(by_kind(tight, CueKind.HOST_BEAT)) > \
        len(by_kind(loose, CueKind.HOST_BEAT))
