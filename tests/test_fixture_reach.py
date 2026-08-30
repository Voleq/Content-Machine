"""What the committed SHORT fixture actually reaches, rendered end to end.

`fixtures/scripts/short_valid.json` is the script the sample MP4 is built
from, so it is what an operator or a new contributor reads to learn what the
format can do.

Under the tag model, reach was an accident: the script named scenes, and a
showcase render reached 17 of 442 assets with the desk carrying every beat
that had a figure in it. Under the shot templates it is a property of the
shots, and the script cannot affect it — which is the point of the rewrite.
So what is checked here is not "did the writer name enough scenes" but "does
the format, driven by a real script, actually put the kit on screen and
animate it".

The two paths that stay green while being visibly wrong are still both
exercised off a real render: a figure composited into a declared slot, and a
frame sequence played out rather than held.
"""

from __future__ import annotations

import json

import pytest

from config import Settings
from pipeline.parser_short import parse_short_script
from pipeline.render_short import render_short
from pipeline.tts import TTSEngine

# A short is a dozen shots, so it reaches roughly a dozen plates — it cannot
# and should not reach a large fraction of a 140-plate kit. These are floors
# on the format doing its job, not on a writer naming things.
#
# ANIMATED IS A LOWER FLOOR THAN IT WAS, ON PURPOSE. The old delivery re-baked
# every still plate as a three-frame boil, so everything on screen moved. 44 of
# the 140 v2 plates are `playback: static` — tables, charts, figures,
# structure — because a figure that moves is a figure being re-read. What moves
# in a vertical cut is the room, the host and the cards.
MIN_PLATES = 8
MIN_CONCEPTS = 5
MIN_ANIMATED = 2


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
    used = manifest["plates_used"]
    assert len(used) >= MIN_PLATES, f"only {len(used)} plates: {used}"


def test_every_plate_reached_is_in_the_one_library(fixture_render):
    """There is no register to be in any more.

    This used to check that every asset a video reached was drawn in the same
    hand — a video is entirely one register, and mixed mark-making was the one
    thing the four-register delivery must never produce. The delivery is gone
    and so is the failure: `plates-registry.json` is the only library, and a
    key that is not in it does not resolve at all.
    """
    from config import Settings
    from pipeline.plates import load_plates

    _s, _script, _w, manifest = fixture_render
    assert manifest["kit"] == "v2-plates"
    reg = load_plates(Settings(_env_file=None).assets_dir)
    for key in manifest["plates_used"]:
        assert reg.get(key) is not None, f"{key} is not in the registry"


def test_the_fixture_plays_a_frame_sequence(fixture_render):
    """A composition where nothing plays is a held photograph.

    The room boils, the host's strips run, the cards and the paper loop. The
    data plates do not, and that is the rule rather than an omission.
    """
    from config import Settings
    from pipeline.plates import load_plates

    _s, _script, _w, manifest = fixture_render
    reg = load_plates(Settings(_env_file=None).assets_dir)
    used = [reg.get(k) for k in manifest["plates_used"]]
    animated = [p for p in used if p is not None and p.animated]
    assert len(animated) >= MIN_ANIMATED, (
        f"only {len(animated)} animated plates: {[p.key for p in animated]}")
    still = [p for p in used if p is not None and not p.animated]
    assert still, "every plate on screen boils — the data plates must not"


def test_the_fixture_reaches_distinct_concepts_not_one_plate_repeated(
        fixture_render):
    _s, _script, _w, manifest = fixture_render
    concepts = {sh["plate"] for sh in manifest["shots"] if sh["plate"]}
    assert len(concepts) >= MIN_CONCEPTS, f"only {len(concepts)}: {concepts}"


def test_the_fixture_fills_the_slots_it_asks_for(fixture_render):
    """Without a value a declared box renders EMPTY. The build now refuses to
    reach an encoder in that state, so a completed render is the assertion —
    but the fixture must still be rich enough to exercise the path."""
    _s, _script, _w, manifest = fixture_render
    assert not manifest.get("unfilled")
    # Every value goes into a slot the plate DECLARES, so what is counted is
    # the values themselves rather than a layer per fill: one plate carries a
    # whole sheet now.
    from config import Settings
    from pipeline.plates import load_plates

    reg = load_plates(Settings(_env_file=None).assets_dir)
    slots = sum(len(reg.get(k).slots) for k in manifest["plates_used"]
                if reg.get(k) is not None)
    assert slots >= 20, f"only {slots} declared slots across the plates reached"


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
