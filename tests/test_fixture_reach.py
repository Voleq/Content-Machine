"""What the committed SHORT fixture actually reaches, rendered end to end.

`fixtures/scripts/short_valid.json` is the script the sample MP4 is built
from, so it is what an operator or a new contributor reads to learn what the
format can do.

Under the tag model, reach was an accident: the script named scenes, and a
showcase render reached 17 of 442 assets with the desk carrying every beat
that had a figure in it. Under the shot templates it is a property of the
twelve shots, and the script cannot affect it — which is the point of the
rewrite. So what is checked here has changed. It is no longer "did the writer
name enough scenes" but "does the format, driven by a real script, actually
put the kit on screen and animate it".

The two paths that stay green while being visibly wrong are still both
exercised off a real render: a figure composited into a declared slot, and a
frame sequence played out rather than held.
"""

from __future__ import annotations

import json

import pytest

from config import Settings
from pipeline.kit_manifest import REGISTERS, kit_for
from pipeline.parser_short import parse_short_script
from pipeline.render_short import render_short
from pipeline.tts import TTSEngine

# A short is twelve shots, so it reaches roughly a dozen entries — it cannot
# and should not reach a large fraction of a 476-entry kit. These are floors
# on the format doing its job, not on a writer naming things.
MIN_ENTRIES = 8
MIN_CONCEPTS = 5
MIN_ANIMATED = 8


@pytest.fixture(scope="module")
def fixture_render(tmp_path_factory):
    from pathlib import Path
    settings = Settings(MOCK_MODE=True, _env_file=None)
    settings.workspace_dir = tmp_path_factory.mktemp("ws")
    settings.cache_dir = tmp_path_factory.mktemp("cache")
    settings.state_dir = tmp_path_factory.mktemp("state")
    settings.ensure_runtime_dirs()
    raw = Path("fixtures/scripts/short_valid.json").read_text(encoding="utf-8")
    script, warnings = parse_short_script(raw, settings)
    tts = TTSEngine(settings).synthesize(script.audio_script, "short",
                                         events=script.inline_events)
    ws = settings.workspace_dir / "EXMPL" / "fixture"
    ws.mkdir(parents=True, exist_ok=True)
    _out, manifest_path = render_short(script, tts, ws, settings)
    return settings, script, warnings, json.loads(
        manifest_path.read_text(encoding="utf-8"))


def test_the_fixture_puts_the_kit_on_screen(fixture_render):
    _s, _script, _w, manifest = fixture_render
    used = manifest["kit_assets_used"]
    assert len(used) >= MIN_ENTRIES, f"only {len(used)} kit entries: {used}"


def test_every_entry_reached_is_in_the_videos_own_register(fixture_render):
    """A video is entirely one register. Mixed mark-making is the one thing
    the four-register delivery must never produce."""
    _s, _script, _w, manifest = fixture_render
    register = manifest["register"]
    assert register in REGISTERS
    kit = kit_for(register)
    for key in manifest["kit_assets_used"]:
        entry = kit[key]
        assert entry.register in (register, "light"), (
            f"{key} is {entry.register} in a {register} video")


def test_the_fixture_plays_a_frame_sequence(fixture_render):
    """The frame-sequence path: a boil runs continuously, a one-shot runs its
    whole strip. A composition where nothing plays is a held photograph."""
    _s, _script, _w, manifest = fixture_render
    kit = kit_for(manifest["register"])
    animated = [k for k in manifest["kit_assets_used"]
                if kit[k].is_animated]
    assert len(animated) >= MIN_ANIMATED, (
        f"only {len(animated)} animated entries: {animated}")
    # A boil is three frames; a one-shot transition runs a longer strip.
    assert any(kit[k].playback == "boil" for k in animated), "nothing boils"
    assert any(kit[k].frames > 3 for k in animated), (
        "no entry plays a strip longer than a boil")


def test_the_fixture_reaches_distinct_concepts_not_one_plate_repeated(
        fixture_render):
    _s, _script, _w, manifest = fixture_render
    concepts = {manifest_shot["plate"] for manifest_shot in manifest["shots"]
                if manifest_shot["plate"]}
    assert len(concepts) >= MIN_CONCEPTS, f"only {len(concepts)}: {concepts}"


def test_the_fixture_fills_the_slots_it_asks_for(fixture_render):
    """Without a value a declared box renders EMPTY. The build now refuses to
    reach an encoder in that state, so a completed render is the assertion —
    but the fixture must still be rich enough to exercise the path."""
    _s, _script, _w, manifest = fixture_render
    assert not manifest.get("unfilled")
    filled = [l for sh in manifest["shots"] for l in sh["layers"]
              if ":fill:" in l]
    assert len(filled) >= 6, f"only {len(filled)} slot fills: {filled}"


def test_the_render_states_its_own_reach(fixture_render):
    _s, _script, _w, manifest = fixture_render
    assert manifest["kit_reach"].startswith("Kit: ")


def test_a_shot_the_script_cannot_fill_is_dropped_not_drawn_blank(
        fixture_render):
    """The fixture has no turn line, so THE TURN is not in its cut."""
    _s, script, _w, manifest = fixture_render
    ids = {sh["id"] for sh in manifest["shots"]}
    if not script.turn_line:
        assert "the-turn" not in ids
        assert "the-turn" in manifest["dropped_shots"]
