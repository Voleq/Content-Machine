"""Every format, against the one engine.

The test that matters for Stage 2 is not that EARNINGS and MACRO render — it
is that they render through the SAME code as the SHORT. So these run over
every template in `templates/shots/` rather than naming two of them: a fourth
format is a JSON file, and it is covered here the moment it exists.

A template engine that needs code per format is not a template engine.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.compose import build_layers, check_invariants
from pipeline.kit_manifest import REGISTERS, kit_for
from pipeline.shots import (LARGE_TYPE_FH, MIN_TYPE_FH, available_formats,
                            expand_sequences, load_format, parse_format,
                            resolve_spans, TemplateError)

FORMATS = available_formats()


class FakeWord:
    def __init__(self, w: str, a: float, b: float) -> None:
        self.word, self.start, self.end = w, a, b


class StubResolver:
    def text_for(self, src: str) -> str | None:
        # Text of the SHAPE the format actually puts there. A stub that
        # returns thirteen characters for the compare plate's "vs" marker
        # fails a geometry check that real content would pass.
        leaf = src.rsplit(".", 1)[-1]
        if leaf in ("versus", "reported", "expected", "latest", "label"):
            return "vs" if leaf == "versus" else "3.4%"
        return f"words for {leaf}"

    def image_for(self, src: str):
        return None

    def list_for(self, src: str):
        return ["one", "two", "three", "four"]

    def frac_box_for(self, src: str):
        return (0.4, 0.3, 0.12, 0.09)


def _cut(name: str):
    """A format as it is cut: sequence repeats expanded against a stub list."""
    return expand_sequences(load_format(name),
                            lambda src: ["a", "b", "c", "d"])


def _words(duration: float, n: int = 240):
    step = duration / n
    return [FakeWord(f"w{i}", i * step, (i + 1) * step) for i in range(n)]


def test_there_are_at_least_three_formats():
    assert {"short", "earnings", "macro"} <= set(FORMATS)


@pytest.mark.parametrize("name", FORMATS)
def test_the_template_parses(name):
    fmt = load_format(name)
    assert fmt.name == name
    assert len(fmt) >= 5


@pytest.mark.parametrize("name", FORMATS)
def test_every_plate_exists_in_every_register(name):
    fmt = _cut(name)
    for register in REGISTERS:
        k = kit_for(register)
        for shot in fmt:
            for concept in filter(None, [shot.plate, shot.enter,
                                         shot.host.pose if shot.host else None,
                                         shot.repeat.concept if shot.repeat else None]):
                assert k.has(concept, register), (
                    f"{name}/{shot.id}: {concept!r} missing in {register}")


@pytest.mark.parametrize("name", FORMATS)
def test_every_bound_slot_is_declared_by_the_plate_it_binds(name):
    """A binding to a slot the plate does not have is a no-op that draws
    nothing and says nothing. It is caught here rather than in a frame."""
    fmt = _cut(name)
    k = kit_for("marker")
    for shot in fmt:
        if not shot.plate:
            continue
        entry = k.concept(shot.plate, "marker")
        for slot in shot.bind:
            assert slot in entry.slots, (
                f"{name}/{shot.id}: binds {slot!r}, but {shot.plate} declares "
                f"{sorted(entry.slots)}")
        if shot.lit and shot.lit != "all":
            assert shot.lit in shot.bind, (
                f"{name}/{shot.id}: lights {shot.lit!r}, which it does not bind")


@pytest.mark.parametrize("name", FORMATS)
def test_a_repeat_binds_only_slots_its_card_declares(name):
    fmt = load_format(name)
    k = kit_for("marker")
    for shot in fmt:
        if not shot.repeat or not shot.repeat.spatial:
            continue
        entry = k.concept(shot.repeat.concept, "marker")
        for slot in shot.repeat.bind:
            assert slot in entry.slots, (
                f"{name}/{shot.id}: repeat binds {slot!r}, but "
                f"{shot.repeat.concept} declares {sorted(entry.slots)}")
        assert shot.repeat.stagger_s > 0, (
            f"{name}/{shot.id}: a repeat with no stagger puts every card on "
            f"screen at once, and nothing enters")


@pytest.mark.parametrize("name", FORMATS)
def test_the_composition_satisfies_every_invariant(name):
    fmt = _cut(name)
    kit = kit_for("marker")
    for duration in (45.0, 70.0):
        spans = resolve_spans(fmt, _words(duration), duration, {})
        result = build_layers(fmt, spans, StubResolver(), kit, "marker")
        host_shots = [s.id for s in fmt.shots if s.host]
        problems = check_invariants(fmt, result, host_shots=host_shots)
        assert problems == [], f"{name} at {duration}s:\n" + "\n".join(problems)


@pytest.mark.parametrize("name", FORMATS)
def test_a_bare_shot_never_outruns_its_ceiling(name):
    fmt = _cut(name)
    for duration in (40.0, 70.0, 120.0):
        for span in resolve_spans(fmt, _words(duration), duration, {}):
            if span.shot.plate or span.shot.repeat:
                continue
            assert span.dur <= span.shot.max_hold_s + 1e-6, (
                f"{name}/{span.shot.id} runs {span.dur:.1f}s on bare ground")


@pytest.mark.parametrize("name", FORMATS)
def test_large_type_and_captions_never_share_a_shot(name):
    for shot in _cut(name):
        if any(t.size_fh >= LARGE_TYPE_FH for t in shot.text):
            assert not shot.captions, f"{name}/{shot.id}"


@pytest.mark.parametrize("name", FORMATS)
def test_nothing_is_authored_below_the_readability_floor(name):
    for shot in _cut(name):
        for t in shot.text:
            assert t.size_fh >= MIN_TYPE_FH, f"{name}/{shot.id}:{t.name}"


# ---------------------------------------------------------------------------
# The parser refuses what it cannot act on
# ---------------------------------------------------------------------------

def test_an_unknown_shot_key_is_refused():
    """`repeat` was dropped in silence the first time MACRO declared it.

    A template key the engine does not read is a no-op, and a no-op in data
    is invisible — the shot rendered as bare ground and the format was one
    shot shorter than it said it was, with nothing logged.
    """
    raw = {"format": "x", "frame": {"w": 1080, "h": 1920},
           "shots": [{"id": "a", "plate": "room-wide", "reapeat": {}}]}
    with pytest.raises(TemplateError, match="unknown key"):
        parse_format(raw)


def test_an_unknown_text_key_is_refused():
    raw = {"format": "x", "frame": {"w": 1080, "h": 1920},
           "shots": [{"id": "a", "plate": "room-wide",
                      "text": [{"src": "script.conclusion", "size_fh": 0.05,
                                "maxlines": 2}]}]}
    with pytest.raises(TemplateError, match="unknown key"):
        parse_format(raw)


def test_a_shot_that_draws_nothing_is_refused():
    raw = {"format": "x", "frame": {"w": 1080, "h": 1920},
           "shots": [{"id": "a", "plate": None}]}
    with pytest.raises(TemplateError, match="nothing for this shot to draw"):
        parse_format(raw)


def test_a_repeat_missing_its_source_is_refused():
    raw = {"format": "x", "frame": {"w": 1080, "h": 1920},
           "shots": [{"id": "a", "plate": None,
                      "repeat": {"concept": "card-consequence"}}]}
    with pytest.raises(TemplateError, match="repeat missing"):
        parse_format(raw)


# ---------------------------------------------------------------------------
# The engine carries the formats without knowing about them
# ---------------------------------------------------------------------------

def test_no_format_is_named_anywhere_in_the_engine():
    """The whole Stage 2 test, as one assertion.

    If EARNINGS or MACRO appears by name in the compositor, the template
    model, the kit loader or the marks, then adding a format costs code and
    this is not a template engine.
    """
    for module in ("compose.py", "shots.py", "kit_manifest.py", "marks.py"):
        src = Path("pipeline") / module
        text = src.read_text(encoding="utf-8").lower()
        for token in ("earnings", "macro"):
            # Prose in a docstring is fine; a string literal or an identifier
            # is not. Check the code with comments and docstrings stripped.
            import io, tokenize
            code = []
            for tok in tokenize.generate_tokens(
                    io.StringIO(src.read_text(encoding="utf-8")).readline):
                if tok.type not in (tokenize.COMMENT, tokenize.STRING):
                    code.append(tok.string)
            assert token not in " ".join(code).lower(), (
                f"{module} names {token!r} in code — the engine knows about a "
                f"format, so adding one is not just a JSON file")


def test_the_renderer_selects_a_format_by_name_only():
    """render_short's only format knowledge is which file to load."""
    import inspect
    from pipeline import render_short as rs
    src = inspect.getsource(rs.render_short)
    assert "load_format(format_name)" in src
    assert '"earnings"' not in src and '"macro"' not in src


@pytest.mark.parametrize("name", FORMATS)
def test_the_template_is_a_file_not_code(name):
    raw = json.loads(Path(f"templates/shots/{name}.json").read_text(
        encoding="utf-8"))
    assert raw["format"] == name
    assert raw["shots"]
