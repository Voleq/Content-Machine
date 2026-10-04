"""The SHORT writer's `sources`: where a figure on screen comes from (item 14).

Keyed by the beat that shows the figure, held to design's source tag (forty
characters, never the data vendor), and slid in under that beat's plate once
its figures land. A script that names none keeps the hash it always had.
"""

from __future__ import annotations

import hashlib
import json
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
    # As it serialised before the beat marks, the sources and the long lane's
    # `beside` on the tag existed.
    old = hashlib.sha256(script.model_dump_json(
        exclude={"beat_marks": True, "sources": True,
                 "inline_events": {"__all__": {"beside"}}}
    ).encode("utf-8")).hexdigest()[:16]
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


def _short_plan(short_valid_json, settings, tmp_path, sources, crowd=None):
    from pipeline import moves as MV
    from pipeline.compose import build_layers
    from pipeline.plates import load_plates
    from pipeline.render_short import (ShortResolver, build_anchors,
                                       prune_empty_shots, shot_sources)
    from pipeline.shots import (apply_order, choose_order, expand_sequences,
                                load_format, resolve_spans)
    from pipeline.tts import TTSEngine

    reg = load_plates(settings.assets_dir)
    script, _ = parse_short_script(_with_sources(short_valid_json, sources), settings)
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
    if crowd is not None:
        crowd(MV, result)
    plan = MV.plan_short(fmt, result, reg, list(tts.words),
                         seed=script.content_sha(), settings=settings,
                         sources=shot_sources(script, fmt))
    return reg, result, plan


def test_a_source_slides_in_where_design_gives_it_room(short_valid_json,
                                                       settings, tmp_path):
    """Design says where the tag can rest on each plate and whether that spot
    is clear. The sheet's is not (the tag would cover its last rows), so its
    source goes on the next shot that has room: a room or host shot, or a
    plate whose spot is clear. Never over the figures, and never over a plate
    that prints a source line of its own."""
    from pipeline import moves as MV

    reg, result, plan = _short_plan(short_valid_json, settings, tmp_path,
                                    {"numbers": "10-K filings, FY21-FY25"})
    layers = MV.shot_plates(result)
    order = [sp.shot.id for sp in result.spans]
    # The numbers beat is one card a row (item 26); its source belongs to
    # the first card, and rests there or on the next shot with room.
    (tag,) = plan.tags
    assert tag.text == "10-K filings, FY21-FY25"
    assert order.index(tag.shot_id) >= order.index("numbers-1")
    for sid in order[order.index("numbers-1"):order.index(tag.shot_id)]:
        if sid in layers:
            plate = reg.get(layers[sid].entry_key)
            assert not MV.tag_clear(plate) or plate.slot("source") is not None
    span = next(sp for sp in result.spans if sp.shot.id == tag.shot_id)
    layer = layers.get(tag.shot_id)
    if layer is not None:
        plate = reg.get(layer.entry_key)
        assert MV.tag_clear(plate) and plate.slot("source") is None
    assert span.start < tag.start and tag.end == pytest.approx(span.end)
    rows = [r for r in plan.record()["moves"] if r["move"] == "slide-in"]
    assert [(r["shot_id"], r["start"]) for r in rows] == \
        [(tag.shot_id, round(tag.start, 3))]


def test_a_carried_source_stops_at_the_next_beat_with_its_own(short_valid_json,
                                                              settings, tmp_path,
                                                              monkeypatch):
    """The numbers beat's plates have no clear spot, so its source waits for
    the next shot with room. When that next beat cites its own figure first,
    the numbers' line must not turn up a shot later under a figure it does not
    source."""
    from pipeline import moves as MV

    def crowd(MV, result):
        full = {layer.entry_key for shot, layer in MV.shot_plates(result).items()
                if shot.startswith("numbers")}
        clear = MV.tag_clear
        monkeypatch.setattr(MV, "tag_clear",
                            lambda p: clear(p) and getattr(p, "key", None) not in full)

    reg, result, plan = _short_plan(
        short_valid_json, settings, tmp_path,
        {"numbers": "10-K filings, FY21-FY25", "numbers_comment": "FY25 10-K"},
        crowd=crowd)
    assert "10-K filings, FY21-FY25" not in [t.text for t in plan.tags]
    assert any("gave way" in s for s in plan.skipped), plan.skipped
    # the comment's own line is still cited: under it, or in the plate's own
    # source slot where the plate prints one
    layer = MV.shot_plates(result)["the-comment"]
    plate = reg.get(layer.entry_key)
    if plate.slot("source") is not None:
        assert layer.values.get("source") == "FY25 10-K"
    else:
        assert [(t.shot_id, t.text) for t in plan.tags] == \
            [("the-comment", "FY25 10-K")]


def test_a_shot_too_short_for_its_source_hands_it_on(short_valid_json, settings,
                                                    tmp_path, monkeypatch):
    """A shot too short to slide the tag in and read it hands the line to the
    next shot with room, as a plate with no clear spot does, instead of
    dropping it."""
    from pipeline import moves as MV

    tag, tried = MV._source_tag, []

    def too_short_first(reg, fmt, plate, shot_id, *rest):
        tried.append(shot_id)
        return None if len(tried) == 1 else tag(reg, fmt, plate, shot_id, *rest)

    monkeypatch.setattr(MV, "_source_tag", too_short_first)
    _, _, plan = _short_plan(short_valid_json, settings, tmp_path,
                             {"numbers": "10-K filings, FY21-FY25"})
    assert tried, "no shot tried the numbers' source"
    assert [t.text for t in plan.tags] == ["10-K filings, FY21-FY25"], plan.skipped
    assert plan.tags[0].shot_id != tried[0]


SUPPLIED_PROVENANCE = ("news", "fred", "pic", "data")


@pytest.mark.parametrize("fmt_name", ["short", "earnings", "macro"])
def test_a_card_with_its_own_source_line_prints_the_writer_s(fmt_name):
    """The quote card has a source line, so no tag slides in over it (moves
    skips it: "the plate prints a source line of its own"). That line has to
    be the writer's source for the beat, or the source reaches no frame."""
    from pipeline.shots import load_format

    fmt = load_format(fmt_name)
    for shot in fmt.shots:
        if not shot.anchor:
            continue            # no beat, so nothing a writer can source
        for v in (shot, *shot.alts):
            bind = v.resolved(shot)[0] if v is not shot else shot.bind
            if "source" in bind:
                # A card that prints where its OWN material came from (the
                # release's publisher, FRED's series id, the photo's credit)
                # is citing data the bot supplied, not the writer's figure.
                if all(alt.lstrip("?").split(".", 1)[0] in SUPPLIED_PROVENANCE
                       for alt in bind["source"].split("|")):
                    continue
                assert f"source.{shot.anchor}" in bind["source"], \
                    f"{fmt_name}/{shot.id} {getattr(v, 'plate', '')}"


def test_the_writer_s_source_wins_and_the_card_s_own_line_is_the_fallback(
        short_valid_json, settings, tmp_path):
    from pipeline.render_short import ShortResolver

    src = "source.numbers_comment|numbers.unit"
    bare, _ = parse_short_script(short_valid_json, settings)
    sourced, _ = parse_short_script(
        _with_sources(short_valid_json, {"numbers_comment": "FY25 10-K"}), settings)
    plain = ShortResolver(script=bare, workdir=tmp_path, settings=settings)
    cited = ShortResolver(script=sourced, workdir=tmp_path, settings=settings)
    assert cited.text_for(src) == "FY25 10-K"
    assert plain.text_for(src) == plain.text_for("numbers.unit")


def test_the_tag_rests_where_design_puts_it(settings):
    """Over a plate, the plate's own spot; on a room or host shot, the kit's
    default for the frame: centred on 9:16, its foot 24 above the 1560 line."""
    from pipeline import moves as MV
    from pipeline.plates import load_plates

    reg = load_plates(settings.assets_dir)
    tag = reg.get(reg.aspect_key("overlays/source-tag", "9x16"))
    x, y, w, h = MV.tag_rect(tag, None, (1080, 1920), reg)
    assert (x, y, w, h) == (50, 1444, 980, 92)
    assert x + w / 2 == 540 and y + h == 1560 - 24
    plate = reg.get("tables/customer-cohorts-9x16")
    spot = plate.motion["slide-in"]
    assert spot["clear"] is True
    assert MV.tag_rect(tag, plate, (540, 960), reg)[:2] == \
        (round(spot["box"]["x"] / 2), round(spot["box"]["y"] / 2))


def test_both_short_prompts_teach_the_field():
    for name in ("master_prompt_short.md", "master_prompt_headline.md"):
        text = (ROOT / "templates" / name).read_text(encoding="utf-8")
        assert '"sources": {"numbers":' in text, name
        assert "never a data vendor" in text, name
