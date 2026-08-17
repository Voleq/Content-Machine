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
        if src == "numbers.header":
            return "\tFY-4\tFY-3\tFY-2\tFY-1\tFY-0"
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
        spans = resolve_spans(fmt, _words(duration), duration, {})
        for span in spans:
            if span.shot.plate or span.shot.repeat:
                continue
            # A bare shot never takes the spread, so its ceiling is exact.
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


def test_real_media_may_only_arrive_inside_a_container():
    """THE PORTAL RULE, enforced in the compositor rather than asked for.

    Pexels, memes and EDGAR screenshots never appear as a raw cutaway — they
    arrive inside a filing-on-screen, a print-on-desk, a pinned-item or a
    projection wall. "B-roll looks imported" was a diagnosis on the format
    that got scrapped, and a convention nobody checks is how it got there.
    """
    raw = {"format": "x", "frame": {"w": 1920, "h": 1080},
           "shots": [{"id": "raw", "plate": "room-wide-16--lived-in",
                      "bind": {"screen": "media.pexels"}}]}
    fmt = parse_format(raw)
    spans = resolve_spans(fmt, _words(10.0), 10.0, {})
    with pytest.raises(TemplateError, match="not a container"):
        build_layers(fmt, spans, StubResolver(), kit_for("marker"), "marker")


def test_a_container_takes_media_in_its_own_media_slot():
    raw = {"format": "x", "frame": {"w": 1920, "h": 1080},
           "shots": [{"id": "wrong-slot", "plate": "filing-on-screen",
                      "bind": {"figure": "media.pexels"}}]}
    fmt = parse_format(raw)
    spans = resolve_spans(fmt, _words(10.0), 10.0, {})
    with pytest.raises(TemplateError, match="whose media slot is"):
        build_layers(fmt, spans, StubResolver(), kit_for("marker"), "marker")


@pytest.mark.parametrize("name", FORMATS)
def test_type_and_data_never_boil(name):
    """THE RULE: the drawn world boils; type and data never do.

    BOIL   plates, room, props, host, marks, transitions
    NEVER  figures, labels, headers, captions, quotes, any code-drawn text,
           and any rule or box framing it

    A number that moves three times a second cannot be read, which is the
    whole job of a number. Every sheet row, card label, caption and panel
    edge carried a 7fps re-placement, and it was called twice before it was
    believed. Asserted on the layer list, so it is answered before a frame is
    drawn and cannot return as a default somebody re-adds.
    """
    fmt = _cut(name)
    for duration in (45.0, 190.0):
        spans = resolve_spans(fmt, _words(duration), duration, {})
        result = build_layers(fmt, spans, SheetResolver(), kit_for("marker"),
                              "marker", progression=fmt.progression)
        for l in result.layers:
            if l.text or l.kind in ("text", "panel", "caption"):
                assert not l.boil_fps, (
                    f"{name}/{l.name} ({l.kind}) carries type and a "
                    f"{l.boil_fps}fps boil")
        # and the ones that SHOULD move still do — losing the boil on marks
        # would be the opposite mistake and just as invisible in a manifest.
        marks = [l for l in result.layers if l.kind == "mark"]
        assert all(l.boil_fps for l in marks), [l.name for l in marks
                                                if not l.boil_fps]


def test_the_re_placement_helper_is_gone_not_zeroed():
    """`_boil_offset` nudged type by a pixel on a seed that changed at the
    boil rate. A knob at zero is a knob somebody turns back up."""
    from pipeline import render_short as rs
    assert not hasattr(rs, "_boil_offset")


def test_a_box_too_short_for_its_lines_is_a_composition_failure():
    """THE NEWS shipped three lines of type through the bottom of a slot.

    `page.headline` is 825x171 on a 1080-wide page, and that page was nested
    into a desk shot at 74%, so the box was 123px tall in frame. Three lines
    at the 3.5% readability floor is 237px. The fitter could not shrink below
    the floor, so it drew all three — 114px past the box, straight over the
    red annotation in the slot below — and reported nothing lost, because
    every word had made it onto one of the three lines.

    It is pure geometry, so it is answerable before a render, with no script.
    """
    raw = {"format": "x", "frame": {"w": 1080, "h": 1920},
           "shots": [{"id": "a", "plate": "desk-top-down",
                      "bind": {"pages": "plate.page-corporate"},
                      "text": [{"name": "headline", "src": "script.hook",
                                "size_fh": 0.045, "slot": "page.headline",
                                "max_lines": 3}]}]}
    fmt = parse_format(raw)
    spans = resolve_spans(fmt, _words(10.0), 10.0, {})
    result = build_layers(fmt, spans, StubResolver(), kit_for("marker"),
                          "marker")
    problems = check_invariants(fmt, result)
    assert any("holds 1 at the" in p for p in problems), problems


def test_two_blocks_of_free_placed_type_may_not_overlap():
    """`align` is a fraction of frame height, and two chosen by hand meet."""
    raw = {"format": "x", "frame": {"w": 1080, "h": 1920},
           "shots": [{"id": "a", "plate": "room-wide",
                      "text": [{"name": "one", "src": "script.hook",
                                "size_fh": 0.05, "align": "0.40"},
                               {"name": "two", "src": "script.conclusion",
                                "size_fh": 0.05, "align": "0.44"}]}]}
    fmt = parse_format(raw)
    spans = resolve_spans(fmt, _words(10.0), 10.0, {})
    result = build_layers(fmt, spans, StubResolver(), kit_for("marker"),
                          "marker")
    assert any("overlap" in p for p in check_invariants(fmt, result))


def test_a_free_placed_box_holds_the_lines_it_promises():
    """The box and the fitter have to use the same leading.

    `size * lines * 1.25` was 13% short of `(asc + desc) * 1.18` for Inter,
    so every free-placed block in every format was given a box that could not
    hold its own line count, and the fitter drew the type smaller than the
    template asked without saying so.
    """
    from pipeline import marks as mk
    for name in FORMATS:
        fmt = _cut(name)
        spans = resolve_spans(fmt, _words(60.0), 60.0, {})
        result = build_layers(fmt, spans, StubResolver(), kit_for("marker"),
                              "marker", progression=fmt.progression)
        for l in result.layers:
            if l.kind != "text" or not l.panel:
                continue
            need = mk.block_height(mk.face_for(l.size_fh),
                                   int(l.size_fh * result.frame[1]),
                                   l.max_lines)
            assert l.h >= need, (
                f"{name}/{l.name}: box {l.h}px for {l.max_lines} lines that "
                f"measure {need}px")


class SheetResolver(StubResolver):
    """Rows the shape a real company sheet has: five periods and a stock."""

    ROWS = ["Revenue\t$400M\t$452M\t$471M\t$491M\t$496M",
            "Net income\t-$8M\t-$25M\t-$49M\t-$70M\t-$89M",
            "Free cash flow\t$12M\t-$2M\t-$6M\t-$11M\t-$15M",
            "Shares out\t365M\tat 2025"]

    def text_for(self, src: str) -> str | None:
        if src == "numbers.header":
            return "$M\t2021\t2022\t2023\t2024\t2025"
        if src.startswith("numbers.row"):
            i = int(src.rsplit(".", 1)[-1])
            return self.ROWS[i] if i < len(self.ROWS) else None
        return super().text_for(src)


def _sheet_rows(shot_id: str = "numbers-1"):
    fmt = _cut("short")
    spans = resolve_spans(fmt, _words(71.5), 71.5, {})
    result = build_layers(fmt, spans, SheetResolver(), kit_for("marker"),
                          "marker")
    return [l for l in result.layers
            if l.shot_id == shot_id and l.kind == "fill" and "\t" in l.text]


def test_every_row_of_a_sheet_is_set_at_one_size():
    """A stock row has one figure where a flow has five, so left to itself it
    never shrinks and comes out half again as big as the table it is in."""
    rows = _sheet_rows()
    assert len(rows) >= 4
    assert len({l.type_px for l in rows}) == 1, {
        l.name: l.type_px for l in rows}


def test_every_row_of_a_sheet_shows_the_same_periods():
    """Dropping the oldest period is right for one row and a disaster for
    five: Revenue kept three years, free cash flow two, and the header still
    said five. Columns that do not line up are worse than small type."""
    rows = _sheet_rows()
    series = [len(l.text.split("\t")) - 1 for l in rows
              if not l.text.startswith("Shares out")]
    assert len(set(series)) == 1, {
        l.name: l.text for l in rows}


def test_a_sheet_row_is_legible():
    """The row that reaches the frame, measured with the renderer's fitter.

    The old check estimated `band_height * 0.42` and got 81px for a row that
    actually set at 33px — 1.7% of frame height, half the floor the rule
    exists to enforce, on a format cut for a phone.
    """
    from pipeline.compose import SLOT_TYPE_FLOOR_FH, _row_size
    for l in _sheet_rows():
        size = _row_size(l, 1920)
        assert size >= SLOT_TYPE_FLOOR_FH * 1920, (
            f"{l.name} sets at {size}px, under the "
            f"{int(SLOT_TYPE_FLOOR_FH * 1920)}px slot floor")


def test_the_host_is_not_mostly_off_the_frame():
    """A figure slot belongs to the plate, and a focus push moves the plate.

    In the numbers walk the host stood at y=1832 in a 1920 frame — 13% of him
    on screen — and how much was clipped changed with which row was lit.
    """
    for name in FORMATS:
        fmt = _cut(name)
        spans = resolve_spans(fmt, _words(70.0), 70.0, {})
        result = build_layers(fmt, spans, StubResolver(), kit_for("marker"),
                              "marker", progression=fmt.progression)
        fw, fh = result.frame
        for l in result.layers:
            if l.kind != "host":
                continue
            assert l.x >= 0 and l.y >= 0 and l.x + l.w <= fw and l.y + l.h <= fh, (
                f"{name}/{l.name} at ({l.x},{l.y}) {l.w}x{l.h} in {fw}x{fh}")


def test_full_coverage_is_reserved_for_the_chapter_boundary():
    """The black wipe is a chapter device, not a beat device.

    A full-coverage wipe every four seconds is a slideshow, so the verticals
    cut on underline-swipe and the long spends ink-wipe-16 once per chapter.
    The boundary is applied by the expansion rather than authored into nine
    chapter files: the same rule written nine times is the drift a template
    engine exists to remove, and a chapter type does not know what format it
    was picked into.
    """
    long_fmt = load_format("long")
    starts = {f"ch{n}": None for n in range(1, 10)}
    for shot in long_fmt.shots:
        key = f"ch{shot.chapter_n}"
        if key in starts and starts[key] is None:
            starts[key] = shot
    assert all(s is not None and s.enter == "ink-wipe-16"
               for s in starts.values()), {
        k: (s.id, s.enter) for k, s in starts.items()}
    covering = [s.id for s in long_fmt.shots if s.enter == "ink-wipe-16"]
    assert len(covering) == 9, f"{len(covering)} wipes for nine chapters"

    for name in FORMATS:
        if name == "long":
            continue
        for shot in _cut(name):
            assert not (shot.enter or "").startswith("ink-wipe"), (
                f"{name}/{shot.id} cuts on {shot.enter!r} — full coverage "
                f"between beats is the slideshow that got cut")


def test_the_long_is_chapters_that_expand():
    """Nine picks become thirty-eight shots; nobody authors them."""
    raw = json.loads(Path("templates/shots/long.json").read_text(
        encoding="utf-8"))
    assert len(raw["chapters"]) == 9 and "shots" not in raw
    fmt = load_format("long")
    assert len(fmt) > 30
    assert len({s.chapter_n for s in fmt.shots}) == 9
    dives = [s for s in fmt.shots if s.plate in ("dive-in", "dive-out")]
    assert len(dives) >= 10, "the dive is the format's most-used motion"


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
    # A format lists shots, or chapter types that expand to them.
    assert raw.get("shots") or raw.get("chapters")
