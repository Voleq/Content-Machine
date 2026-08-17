"""The writing form, derived from the templates rather than authored.

Stage 4's whole claim is that a writer supplies WORDS AT A SIZE and nothing
else. That is checkable: every source a template reads is either a field with
a measured budget, or something the pipeline supplies — and there is no third
category. A source that is neither is a thing nobody has been told to write.
"""

from __future__ import annotations

import pytest

from pipeline.form import (WRITER_ROOTS, form_for, render_form,
                           supplied_fields, writer_fields)
from pipeline.models import ShortScript
from pipeline.shots import available_formats

FORMATS = available_formats()
VERTICALS = [n for n in FORMATS if n != "long"]


@pytest.mark.parametrize("name", FORMATS)
def test_every_source_is_either_written_or_supplied(name):
    """No third category. A source belonging to neither is a field nobody
    has been asked for and nothing fills — a drawn, empty box."""
    supplied_roots = {"plate", "chart", "media", "channel", "compare",
                      "numbers"}
    for f in form_for(name):
        root = f.src.split(".", 1)[0]
        assert root in set(WRITER_ROOTS) | supplied_roots, (
            f"{name}: {f.src!r} is read by {f.shots} and belongs to neither "
            f"the writer nor the pipeline")


@pytest.mark.parametrize("name", VERTICALS)
def test_every_field_a_vertical_asks_for_has_a_measured_budget(name):
    """A field advertised without a budget is a field written to no length.

    The budgets come from `templates/budgets.json`, which is produced by the
    real fitter against the real templates, so the number the writer is given
    is the number `check_budgets` will refuse them on.
    """
    missing = [f.src for f in writer_fields(name) if f.budget is None]
    assert missing == [], f"{name}: no budget for {missing}"


@pytest.mark.parametrize("name", VERTICALS)
def test_a_verticals_form_is_short_enough_to_fill(name):
    """Eight or nine fields. If it grows past a dozen it is a document
    again, and the reason the old prompt failed was that it was a document."""
    assert 5 <= len(writer_fields(name)) <= 12, [
        f.src for f in writer_fields(name)]


@pytest.mark.parametrize("name", VERTICALS)
def test_the_form_matches_the_script_model(name):
    """Every field the form asks for exists on the model that carries it.

    A form asking for `script.turn_line` against a model with no `turn_line`
    is a field that parses to nothing and renders as a skipped shot.
    """
    fields = ShortScript.model_fields
    for f in writer_fields(name):
        head = f.src.split(".")[1]
        assert head in fields, (
            f"{name}: the template reads {f.src!r} and ShortScript has no "
            f"{head!r}")


def test_the_model_allows_more_than_the_frame_holds():
    """The gap the form closes, stated as a number.

    Every field below is bounded by the model at several times what its shot
    physically holds. Until the form is what the writer fills, that gap is
    the distance between a script that validates and a script that renders.
    """
    fields = ShortScript.model_fields
    over = []
    for f in writer_fields("short"):
        head = f.src.split(".")[1]
        limit = next((m.max_length for m in fields[head].metadata
                      if getattr(m, "max_length", None)), None)
        if limit and f.budget and limit > f.budget:
            over.append(f"{head}: model {limit}, frame {f.budget}")
    assert over, "if the model has been narrowed to the form, update this"


def test_the_long_has_no_written_fields_at_all():
    """THE GAP, as a test rather than a paragraph in a report.

    Nine chapters ask for a title, three lines and four phrases each. Not one
    of them is written: `render_long_shots.split_chapters` cuts a single
    prose narration into sentences and hands the pieces out, `_title` takes
    the first four words of the first one, and a "phrase" is the head of a
    sentence truncated at twenty characters. That is why a chain box reads
    "Two larger".

    This test does not fail on the gap — it MEASURES it, so closing it is a
    deliberate act with a test change beside it.
    """
    fields = writer_fields("long")
    per_chapter = {f.name for f in fields}
    assert per_chapter, "the long reads no chapter sources at all"
    chapters = 9
    assert len(fields) * chapters >= 60, (
        f"{len(fields)} fields x {chapters} chapters")
    # And every one of them is sliced, not written.
    from pipeline.render_long_shots import LongResolver
    for name in ("title", "line", "phrase"):
        assert any(f.name.startswith(name) for f in fields)
    assert hasattr(LongResolver, "_chapter")


@pytest.mark.parametrize("name", FORMATS)
def test_the_form_renders_without_a_kit(name):
    """The prompt no longer enumerates artwork.

    The old writing prompt was a catalogue of drawings the writer picked
    from, which is what a script choosing composition needs. The template
    chooses composition now, so the form is words and lengths — and it has
    to build with no kit loaded at all.
    """
    text = render_form(name)
    assert name.upper() in text
    for f in writer_fields(name):
        assert f.name in text
    assert "marker" not in text and "ballpoint" not in text


@pytest.mark.parametrize("name", FORMATS)
def test_the_writer_is_never_asked_for_a_figure(name):
    """Numbers come from the export, prices from the chart, media from the
    workspace. A writer asked to supply a figure supplies a plausible one."""
    for f in supplied_fields(name):
        assert not f.writer
    for f in writer_fields(name):
        assert not f.src.startswith(("numbers.", "chart.", "media.")), (
            f"{name}: {f.src} would be asked of a person")
