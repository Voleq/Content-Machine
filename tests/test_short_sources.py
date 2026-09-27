"""The SHORT writer's `sources`: where a figure on screen comes from (item 14).

Keyed by the beat that shows the figure, held to design's source tag (forty
characters, never the data vendor), and slid in under that beat's plate once
its figures land. A script that names none keeps the hash it always had.
"""

from __future__ import annotations

import hashlib
import json
from collections import namedtuple
from pathlib import Path

import pytest

from pipeline.parser_short import ScriptParseError, parse_short_script

ROOT = Path(__file__).resolve().parents[1]


def _with_sources(raw: str, sources: dict) -> str:
    data = json.loads(raw)
    data["sources"] = sources
    return json.dumps(data)


def test_a_source_is_kept_under_the_beat_it_names(short_valid_json, settings):
    script, _ = parse_short_script(
        _with_sources(short_valid_json, {"Cheap or trap": "  FY25   10-K ",
                                         "numbers": "10-K filings, FY21-FY25"}),
        settings)
    assert script.sources == {"cheap_or_trap": "FY25 10-K",
                              "numbers": "10-K filings, FY21-FY25"}


@pytest.mark.parametrize("sources, why", [
    ({"numbers": "x" * 41}, "holds 40"),
    ({"numbers": "Refinitiv"}, "vendor"),
    ({"the-sheet": "FY25 10-K"}, "no beat"),
])
def test_a_source_the_tag_cannot_carry_is_refused(short_valid_json, settings,
                                                  sources, why):
    with pytest.raises(ScriptParseError, match=why):
        parse_short_script(_with_sources(short_valid_json, sources), settings)


def test_a_script_with_no_sources_keeps_its_hash(short_valid_json, settings):
    """The hash is what an approval is recorded against and every render seed
    comes from, so a new empty field must not change it."""
    script, _ = parse_short_script(short_valid_json, settings)
    old = hashlib.sha256(script.model_dump_json(
        exclude={"beat_marks", "sources"}).encode("utf-8")).hexdigest()[:16]
    assert script.sources == {} and script.content_sha() == old
    sourced, _ = parse_short_script(
        _with_sources(short_valid_json, {"numbers": "FY25 10-K"}), settings)
    assert sourced.content_sha() != script.content_sha()


def test_a_beat_s_source_reaches_the_shot_that_plays_it(short_valid_json,
                                                        settings):
    from pipeline.render_short import shot_sources
    from pipeline.shots import load_format

    script, _ = parse_short_script(
        _with_sources(short_valid_json, {"numbers": "FY25 10-K",
                                         "numbers_comment": "FY25 10-K"}),
        settings)
    got = shot_sources(script, load_format("short"))
    assert got == {"numbers": "FY25 10-K", "the-comment": "FY25 10-K"}


def test_the_sheet_s_source_slides_in_once_its_rows_are_read(short_valid_json,
                                                             settings, tmp_path):
    """Under the sheet, after the last figure it counts up has landed, and
    held to the cut — and nowhere a plate prints a source line of its own."""
    from pipeline import moves as MV
    from pipeline.compose import build_layers
    from pipeline.plates import load_plates
    from pipeline.render_short import (ShortResolver, build_anchors,
                                       prune_empty_shots, shot_sources)
    from pipeline.shots import (apply_order, choose_order, expand_sequences,
                                load_format, resolve_spans)
    from pipeline.tts import TTSEngine

    reg = load_plates(settings.assets_dir)
    script, _ = parse_short_script(
        _with_sources(short_valid_json, {"numbers": "10-K filings, FY21-FY25",
                                         "numbers_comment": "FY25 10-K"}),
        settings)
    tts = TTSEngine(settings).synthesize(script.audio_script, "short")
    resolver = ShortResolver(script=script, workdir=tmp_path, settings=settings,
                             prices=None, handle="@channel")
    fmt = load_format("short")
    fmt = apply_order(fmt, choose_order(fmt, seed=script.content_sha(), avoid=set()))
    fmt = expand_sequences(fmt, resolver.list_for)
    fmt, _ = prune_empty_shots(fmt, resolver)
    spans = resolve_spans(fmt, tts.words, tts.duration_s, build_anchors(script))
    result = build_layers(fmt, spans, resolver, reg, aspect=fmt.aspect,
                          seed=script.content_sha(), avoid=set())
    plan = MV.plan_short(fmt, result, reg, list(tts.words),
                         seed=script.content_sha(), settings=settings,
                         sources=shot_sources(script, fmt))

    layers = MV.shot_plates(result)
    beat = lambda sid: sid[:-3] if sid.endswith("-in") else sid  # noqa: E731
    tags = [t for t in plan.tags if beat(t.shot_id) == "numbers"]
    assert len(tags) == 1, plan.tags
    (tag,) = tags
    assert tag.text == "10-K filings, FY21-FY25"
    layer = layers[tag.shot_id]
    landed = [m.end for m in plan.moves if m.shot_id == tag.shot_id
              and m.move == "count-up"]
    assert tag.start >= max(landed, default=layer.t_start)
    assert tag.end == layer.t_end
    for t in plan.tags:
        assert reg.get(layers[t.shot_id].entry_key).slot("source") is None
    rows = [r for r in plan.record()["moves"] if r["move"] == "slide-in"]
    assert sorted((r["shot_id"], r["start"]) for r in rows) == \
        sorted((t.shot_id, t.start) for t in plan.tags)


def test_both_short_prompts_teach_the_field():
    for name in ("master_prompt_short.md", "master_prompt_headline.md"):
        text = (ROOT / "templates" / name).read_text(encoding="utf-8")
        assert '"sources": {"numbers":' in text, name
        assert "never a data vendor" in text, name
