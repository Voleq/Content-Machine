"""The SHORT's invariants, asserted on the LAYER LIST rather than on pixels.

Every rule this format has is a property of which layers exist and when, so
these run in milliseconds on every commit. The pixel backstop
(`test_short_holds.py`) is separate and answers a different question: whether
the video that came out actually moves.

The repo has shipped, under a green suite, a 12.5-second still frame and a
disclaimer printed twice in two typefaces. Both were layer-list facts. Neither
had a test.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.compose import build_layers, check_invariants, held_layer_spans
from pipeline.render_short import HOST_SHOTS, build_anchors
from pipeline.shots import (LARGE_TYPE_FH, MIN_TYPE_FH, expand_sequences,
                            load_format, parse_format, resolve_spans,
                            TemplateError)

# Shots the host appears in. The spec said 1, 5-8, 11, 12; 5-8 are the
# numbers walk, and the push-in that makes the walk a composition change also
# leaves no room for a figure — see the note on the `numbers` shot.
# The host is in ONE vertical shot now, and it is the turn: the line the
# cut rests on, in close-up. He was in three, all at full figure in a wide
# room, which is the shot you use when the room is the point.
SPEC_HOST_SHOTS = {"the-turn"}


class FakeWord:
    def __init__(self, word: str, start: float, end: float) -> None:
        self.word, self.start, self.end = word, start, end


class StubResolver:
    """Fills everything a template asks for, so the invariants are what fail."""

    def __init__(self, chart: Path | None = None) -> None:
        self.chart = chart

    def text_for(self, src: str) -> str | None:
        # Text of the SHAPE the format actually puts there. A stub that
        # returns thirteen characters for the compare plate's "vs" marker
        # fails a geometry check that real content would pass.
        if src == "numbers.header":
            return "\tFY-4\tFY-3\tFY-2\tFY-1\tFY-0"
        # A DATA REGION AND A ROW TAKE FIGURES, NOT WORDS. `plot-area`, a
        # series and a sheet row are shapes the plate reserves for numbers, and
        # a stub that hands them prose fails a check real content would pass.
        # Matched on the whole source: `numbers.figures.0` ends in "0".
        parts = set(src.split("."))
        if {"series", "figures"} & parts:
            return ",".join(str(10 + i * 3) for i in range(6))
        # The heads are however many the plate declares — four on the dense
        # chart, six on a per-period one.
        if {"heads", "axis"} & parts:
            return "a,b,c,d"
        if "years" in parts:
            return "a,b,c,d,e,f"
        leaf = src.rsplit(".", 1)[-1]
        if leaf in ("versus", "reported", "expected", "latest", "label",
                    "headline_figure", "headline_label", "headline_kicker",
                    "last", "unit", "ticker", "kicker", "expected_label"):
            return "vs" if leaf == "versus" else "3.4%"
        return f"words for {leaf}"

    def image_for(self, src: str):
        return self.chart if src == "chart.price" else None

    def frac_box_for(self, src: str):
        return (0.4, 0.3, 0.12, 0.09)


@pytest.fixture()
def fmt():
    """The SHORT as it is CUT, not as it is authored.

    Nine shots are authored; the numbers beat is one sequence repeat that
    becomes one shot per metric. Four metrics is the fixture's shape and the
    twelve-shot spec's shape, so every invariant below still reads against
    twelve.
    """
    return expand_sequences(load_format("short"),
                            lambda src: ["m1", "m2", "m3", "m4"])


@pytest.fixture()
def authored():
    return load_format("short")


@pytest.fixture(scope="module")
def reg():
    from config import Settings
    from pipeline.plates import load_plates
    return load_plates(Settings(_env_file=None).assets_dir)


def _words(duration: float = 70.0, n: int = 240) -> list[FakeWord]:
    step = duration / n
    return [FakeWord(f"w{i}", i * step, (i + 1) * step) for i in range(n)]


def _build(fmt, reg, chart: Path | None = None, duration: float = 70.0):
    spans = resolve_spans(fmt, _words(duration), duration, {})
    return spans, build_layers(fmt, spans, StubResolver(chart), reg,
                               aspect=fmt.aspect, seed="test")


# ---------------------------------------------------------------------------
# The template itself
# ---------------------------------------------------------------------------

def test_the_numbers_beat_is_authored_once_and_cut_many_times(fmt, authored):
    """A beat is an idea the format has; a shot is a frame.

    The walk down the sheet is one shot definition and as many cuts as the
    script carries metrics — four metrics make four, two make two, and neither
    case is authored twice.
    """
    assert len(authored) == 10
    assert [s.id for s in authored] == [
        "hook", "the-move", "the-news", "the-turn", "numbers", "the-sheet",
        "the-comment", "cheap-or-trap", "payoff", "close"]
    walk = [s.id for s in fmt if s.id.startswith("numbers-")]
    assert walk == ["numbers-1", "numbers-2", "numbers-3"]
    assert len(fmt) == len(authored) + len(walk) - 1


def test_every_plate_the_template_names_is_in_the_kit(fmt, reg):
    """A name that resolves to nothing draws nothing.

    There is one library now. This used to check four hand-drawn registers
    for the same plate, because a video seeded into the one that was missing
    it failed at render time for a reason that had nothing to do with the
    script — and the two libraries living in one repository is what this
    conversion removes.
    """
    from pipeline.compose import resolve_plate

    for shot in fmt:
        if shot.plate:
            role = (shot.plate.split("/", 1)[1]
                    if shot.plate.startswith("room/") else "")
            if role and role in reg.room_roles:
                continue                       # a role, resolved by rotation
            assert resolve_plate(reg, shot.plate, fmt.aspect) is not None, \
                f"{shot.id}: {shot.plate!r} is not a plate in the kit"
        if shot.host:
            pose = shot.host.pose
            assert pose in reg or pose in reg.host_roles, \
                f"{shot.id}: {pose!r} is neither a pose nor a host role"


def test_the_vertical_set_stays_vertical(fmt, reg):
    """Ten families, and none of the 16:9-only plates.

    The comps table, the scatter, the waterfall, the grouped bars, the flow
    plate and the diff plate need horizontal room to be readable and do not
    belong in seventy-five seconds. Naming one here would render it letterboxed
    into a vertical frame with its type at a third of the size it was drawn at.
    """
    from pipeline.compose import resolve_plate

    for shot in fmt:
        if not shot.plate or shot.plate.startswith("room/"):
            continue
        plate = resolve_plate(reg, shot.plate, fmt.aspect)
        assert plate is not None and plate.aspect in ("9x16", ""), \
            f"{shot.id}: {plate.key} is {plate.aspect}, not a vertical plate"


def test_a_template_carrying_large_type_and_captions_is_refused():
    """The two are mutually exclusive, and the parser is where that is caught."""
    raw = {"format": "bad", "frame": {"w": 1080, "h": 1920},
           "shots": [{"id": "x", "plate": None, "captions": True,
                      "text": [{"src": "script.conclusion",
                                "size_fh": LARGE_TYPE_FH + 0.01}]}]}
    with pytest.raises(TemplateError, match="mutually exclusive"):
        parse_format(raw)


def test_type_below_the_floor_is_refused():
    raw = {"format": "bad", "frame": {"w": 1080, "h": 1920},
           "shots": [{"id": "x", "plate": None,
                      "text": [{"src": "script.conclusion",
                                "size_fh": MIN_TYPE_FH - 0.005}]}]}
    with pytest.raises(TemplateError, match="below"):
        parse_format(raw)


# ---------------------------------------------------------------------------
# The invariants
# ---------------------------------------------------------------------------

def test_the_composition_satisfies_every_invariant(fmt, reg, tmp_path):
    chart = tmp_path / "chart.png"
    from PIL import Image
    Image.new("RGBA", (872, 1712), (255, 255, 255, 255)).save(chart)
    _spans, result = _build(fmt, reg, chart)
    problems = check_invariants(
        fmt, result,
        host_shots=[sh.id for sh in fmt.shots if sh.host])
    assert problems == [], "\n".join(problems)


def test_no_layer_outlives_its_shot(fmt, reg):
    spans, result = _build(fmt, reg)
    by_id = {s.shot.id: s for s in spans}
    for layer in result.layers:
        span = by_id[layer.shot_id]
        assert layer.t_start >= span.start - 1e-6, layer.name
        assert layer.t_end <= span.end + 1e-6, layer.name


def test_the_host_appears_in_exactly_the_shots_they_are_in(fmt, reg):
    _spans, result = _build(fmt, reg)
    got = {l.shot_id for l in result.layers if l.kind == "host"}
    assert got == SPEC_HOST_SHOTS
    assert set(HOST_SHOTS) == SPEC_HOST_SHOTS


def test_large_type_and_the_caption_band_never_share_a_shot(fmt, reg):
    _spans, result = _build(fmt, reg)
    for span in result.spans:
        big = [l for l in result.layers
               if l.shot_id == span.shot.id and l.kind == "text"
               and l.size_fh >= LARGE_TYPE_FH]
        assert not (big and span.shot.captions), span.shot.id


def test_nothing_renders_below_three_and_a_half_percent(fmt, reg):
    _spans, result = _build(fmt, reg)
    for layer in result.layers:
        if layer.kind == "text":
            assert layer.size_fh >= MIN_TYPE_FH, layer.name


def test_no_composition_holds_past_its_ceiling(fmt, reg):
    """Every shot either moves continuously or changes inside its ceiling."""
    _spans, result = _build(fmt, reg)
    for span in result.spans:
        moving = any(l.shot_id == span.shot.id and l.moves
                     for l in result.layers)
        if moving:
            continue
        worst = max((b - a for a, b, sid in held_layer_spans(result)
                     if sid == span.shot.id), default=0.0)
        assert worst <= span.shot.max_hold_s + 1e-6, (
            f"{span.shot.id} holds {worst:.2f}s over "
            f"{span.shot.max_hold_s}s")


def test_every_shot_reaches_the_plate_the_template_names(fmt, reg):
    _spans, result = _build(fmt, reg)
    for span in result.spans:
        if not span.shot.plate:
            continue
        plates = [l for l in result.layers
                  if l.shot_id == span.shot.id and l.kind == "plate"]
        assert len(plates) == 1, span.shot.id
        # `entry_key` is the registry key the layer reached; a template may
        # name a bare plate, an aspect-free stem, or a room ROLE, and what
        # matters is that the shot landed on the plate the kit resolved for it.
        assert plates[0].entry_key, span.shot.id
        assert plates[0].concept == plates[0].entry_key.split("/", 1)[0]


def test_the_templates_line_budget_reaches_the_layer(fmt, reg):
    """`max_lines` is a constraint the writer is given, so it must be applied.

    The renderer hardcoded six and THE TURN set three, so the turn rendered
    four lines — the template asked for a limit the drawing ignored.
    """
    _spans, result = _build(fmt, reg)
    for shot in fmt:
        for spec in shot.text:
            layer = next((l for l in result.layers
                          if l.name == f"{shot.id}:text:{spec.name}"), None)
            if layer is not None:
                assert layer.max_lines == spec.max_lines, layer.name


def test_a_bare_shot_never_outruns_its_own_ceiling(fmt, reg):
    """A shot with no plate has no boil under it.

    Its type draws on and then the frame is genuinely motionless, so its
    ceiling limits the SPAN and not merely the gap between layer edges. THE
    TURN reached 7.7s against a 5s ceiling this way, and the layer-list rules
    all passed because the type technically boils — a sub-pixel wobble the
    measurement cannot see. The pixel backstop caught it; this is the cheap
    version of that catch.
    """
    for duration in (40.0, 71.5, 120.0):
        spans = resolve_spans(fmt, _words(duration), duration, {})
        for span in spans:
            if span.shot.plate:
                continue
            # A bare shot never takes the spread, so its ceiling is exact.
            assert span.dur <= span.shot.max_hold_s + 1e-6, (
                f"{span.shot.id} runs {span.dur:.2f}s on bare ground, over "
                f"its {span.shot.max_hold_s}s ceiling, at {duration}s runtime")


def test_every_shot_is_present_and_ordered(fmt, reg):
    spans, _result = _build(fmt, reg)
    assert [s.shot.id for s in spans] == [s.id for s in fmt]
    for a, b in zip(spans, spans[1:]):
        assert a.end <= b.start + 1e-6, f"{a.shot.id} overlaps {b.shot.id}"
        assert a.dur > 0


def test_an_unfilled_slot_is_a_failure_not_an_empty_box(fmt, reg):
    """A slot with no value must fail the build, never draw an empty box."""
    class Empty:
        def text_for(self, src): return None
        def image_for(self, src): return None

    spans = resolve_spans(fmt, _words(), 70.0, {})
    result = build_layers(fmt, spans, Empty(), reg, aspect=fmt.aspect,
                          seed="test")
    assert result.unfilled, "an empty resolver filled every slot"
    problems = check_invariants(
        fmt, result,
        host_shots=[sh.id for sh in fmt.shots if sh.host])
    assert any("required and empty" in p for p in problems)


# ---------------------------------------------------------------------------
# Timing comes from the audio, never from a constant
# ---------------------------------------------------------------------------

def test_duration_comes_from_the_audio_clock(fmt, reg):
    """The same template against two different runtimes yields two cuts."""
    short_spans = resolve_spans(fmt, _words(40.0), 40.0, {})
    long_spans = resolve_spans(fmt, _words(90.0), 90.0, {})
    assert short_spans[-1].end == pytest.approx(40.0)
    assert long_spans[-1].end == pytest.approx(90.0)
    assert sum(s.dur for s in long_spans) > sum(s.dur for s in short_spans)


def test_a_shot_starts_where_its_words_are_spoken(fmt):
    """Anchoring is the whole timing model: find the words, cut there."""
    words = [FakeWord(w, i * 1.0, i * 1.0 + 0.9) for i, w in enumerate(
        "one two three the market did not care about this at all nine ten "
        "eleven twelve".split())]
    spans = resolve_spans(fmt, words, 14.0,
                          {"move": "the market did not care"})
    move = next(s for s in spans if s.shot.id == "the-move")
    assert move.anchored
    assert move.start == pytest.approx(3.0, abs=0.6)


def test_the_template_is_data_not_code():
    """Adding a format is authoring a file. This is that promise, checked."""
    raw = json.loads(Path("templates/shots/short.json").read_text(
        encoding="utf-8"))
    assert raw["format"] == "short"
    # Ten authored, twelve cut. The numbers beat is one declaration.
    assert len(raw["shots"]) == 10
    assert all("plate" in s for s in raw["shots"])
    seq = [s for s in raw["shots"] if s.get("repeat", {}).get("arrange") == "sequence"]
    assert len(seq) == 1 and seq[0]["id"] == "numbers"
