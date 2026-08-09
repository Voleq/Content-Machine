"""What the committed SHORT fixture actually reaches, rendered end to end.

`fixtures/scripts/short_valid.json` is the script the sample MP4 is built
from, so it is the thing an operator, a reviewer or a new contributor looks at
to learn what the format can do. It predated the beat library and named none
of it, which is why the showcase render demonstrated the failure: 17 of 442
assets, one beat-library scene, and the desk carrying every beat that had a
figure in it.

It also meant two whole paths were untested end to end — the slot fill (a
figure composited into a declared box) and the frame sequence (a one-shot
played out rather than held). Both are exercised here, off a real render,
because both are exactly the kind of thing that stays green while being
visibly wrong.

The floors are floors. Four is the format's own beat count — hook, why,
gut-check, payoff — so it is the point at which every beat has a scene rather
than the desk. Raise it from real renders; do not lower it to make a lazy
fixture pass.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.kit import load_kit
from pipeline.models import KIT_TAG_FAMILIES, TagType

ROOT = Path(__file__).resolve().parents[1]

# The floor for distinct beat-library scenes, and for scenes that play rather
# than hold. See the module docstring before touching either.
MIN_SCENES = 4
MIN_SEQUENCES = 1


@pytest.fixture(scope="module")
def fixture_render(tmp_path_factory):
    from config import Settings

    from pipeline.parser_short import parse_short_script
    from pipeline.render_short import render_short
    from pipeline.tts import TTSEngine

    tmp = tmp_path_factory.mktemp("fixture_reach")
    settings = Settings(
        MOCK_MODE=True,
        workspace_dir=tmp / "ws",
        cache_dir=tmp / "cache",
        state_dir=tmp / "state",
        short_width=540,
        short_height=960,
        _env_file=None,
    )
    settings.ensure_runtime_dirs()
    raw = (ROOT / "fixtures" / "scripts" / "short_valid.json").read_text(
        encoding="utf-8")
    script, warnings = parse_short_script(raw, settings)
    tts = TTSEngine(settings).synthesize(script.audio_script, "short",
                                         events=script.inline_events)
    ws = settings.workspace_dir / "EXMPL" / "fixture"
    ws.mkdir(parents=True)
    _out, manifest_path = render_short(script, tts, ws, settings)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return settings, script, warnings, manifest


def _beat_scenes(manifest, kit) -> list:
    """The beat-library assets a render reached.

    Read off the tag routing, not off a folder list: `shorts/the-world` (the
    desk) and `shorts/open-close` (the signature open and close) are shorts
    families the renderer places itself, and counting them would let a render
    that reached nothing but furniture clear the floor.
    """
    beat_families = {f for f in KIT_TAG_FAMILIES[TagType.PROP]
                     if f.startswith("shorts/")}
    return [kit.get(k) for k in manifest["kit_assets_used"]
            if k.rsplit("/", 1)[0] in beat_families]


def test_the_fixture_reaches_the_beat_library(fixture_render):
    settings, _script, _warnings, manifest = fixture_render
    kit = load_kit(settings.assets_dir)
    scenes = _beat_scenes(manifest, kit)
    assert len({a.key for a in scenes}) >= MIN_SCENES, \
        f"only {len(scenes)} beat-library scene(s): {[a.key for a in scenes]}"


def test_the_fixture_plays_a_frame_sequence(fixture_render):
    """The frame-sequence path: a one-shot runs its whole strip. A six-frame
    transformation cut at three frames is a drawing of nothing having
    happened, and nothing rendered from the committed fixture ever played
    one."""
    settings, _script, _warnings, manifest = fixture_render
    kit = load_kit(settings.assets_dir)
    sequences = [a for a in _beat_scenes(manifest, kit) if a.frame_count > 1]
    assert len(sequences) >= MIN_SEQUENCES, \
        f"nothing played: {[(a.key, a.frame_count) for a in _beat_scenes(manifest, kit)]}"
    transformations = [a for a in sequences if 6 <= a.frame_count <= 8]
    assert transformations, \
        f"no animated transformation: {[(a.key, a.frame_count) for a in sequences]}"


def test_the_fixture_uses_a_scene_drawn_to_be_the_frame(fixture_render):
    """One 9:16 scene, which is the register the short has and the long does
    not — and eleven assets were drawn for it."""
    settings, _script, _warnings, manifest = fixture_render
    kit = load_kit(settings.assets_dir)
    vertical = [a for a in _beat_scenes(manifest, kit) if a.aspect == "9:16"]
    assert vertical, "no full-height scene in the render"


def test_the_fixture_fills_the_slots_it_asks_for(fixture_render):
    """The slot-fill path, in all three of its forms — one value, named
    values, a bare list in slot order. Without a value the drawing renders
    with its boxes EMPTY, which is Dennis crushed under a blank rectangle."""
    _settings, script, _warnings, _manifest = fixture_render
    props = [e for e in script.inline_events if e.type is TagType.PROP]
    filled = [e for e in props if e.values]
    assert len(filled) >= 4, f"only {len(filled)} of {len(props)} props carry a figure"
    assert any(len(e.values) == 1 for e in filled), "no single-slot fill"
    assert any({"heavy", "light"} <= set(e.values) for e in filled), \
        "no named-slot fill"
    assert any(len(e.values) >= 3 for e in filled), "no ordered list fill"


def test_the_fixture_does_not_trip_its_own_reach_warning(fixture_render):
    """The fixture is what a writer copies. It has to clear the bar it sets."""
    _settings, _script, warnings, _manifest = fixture_render
    assert not [w for w in warnings if "beat-library scene" in w], warnings


def test_the_render_states_its_own_reach(fixture_render):
    _settings, _script, _warnings, manifest = fixture_render
    assert manifest["kit_reach"].startswith("Kit: ")
    assert "beat-library scene" in manifest["kit_reach"]
