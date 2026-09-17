"""Every shipped asset has a code path, and every plate a template names exists.

`gates.reachable_plates` already reports kit plates that no template, chapter
type or renderer can put on screen — that is why the kit stayed honest through
a whole kit change. The NON-kit asset directories were never covered by it,
which is exactly how `assets/brand/` — a mascot head, an intro bug, a
wordmark and eleven chapter backdrops, in a visual language the current kit
does not use — sat there through that change with nothing loading any of it
(J7, J8).

The second check here is the cheaper half of the same idea and catches a
different drift: the plate CATALOGUE in the prompts is generated from the
registry so it cannot go stale, but the hand-written prose around it was
never covered. `master_prompt_long_write.md` told the writer that foreign
media lands in `frames/media-frame`, and the kit ships `-t1`, `-t2` and
`-t3` — there is no bare `media-frame`, so `Registry.aspect_key` could not
rescue it either (M4).

This is X3's habit in art instead of code: an artefact that exists, is
trusted to be live, and is connected to nothing.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

from config import Settings

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"

# Directories that are BUILD PRODUCTS or runtime caches rather than shipped
# art, so absence of a loader says nothing about them.
_NOT_SHIPPED = {
    "plates",        # materialised by scripts/ingest_kit.py from kit/
    "custom",        # operator uploads, per video
    "voices",        # downloaded Piper model
}

# Assets a human uses by hand rather than a code path. Each one needs a
# reason, and the reason is the point: "nothing loads it" has to be a
# DECISION on the record, not the state that `assets/brand/` was in.
_BY_HAND = {
    "channel": ("YouTube channel art — banner and avatar, uploaded by hand "
                "in YouTube Studio. No render path should touch these."),
}


def _source_text() -> str:
    parts = []
    for sub in ("pipeline", "bot", "scripts"):
        for py in sorted((ROOT / sub).rglob("*.py")):
            parts.append(py.read_text(encoding="utf-8"))
    for extra in ("config.py", "main.py"):
        parts.append((ROOT / extra).read_text(encoding="utf-8"))
    for tmpl in sorted((ROOT / "templates").rglob("*")):
        if tmpl.is_file() and tmpl.suffix in (".md", ".json"):
            parts.append(tmpl.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parts)


def test_every_shipped_asset_directory_has_something_that_loads_it():
    src = _source_text()
    orphans: list[str] = []
    for entry in sorted(ASSETS.iterdir()):
        name = entry.name
        if name.startswith(".") or name in _NOT_SHIPPED or name in _BY_HAND:
            continue
        if entry.is_file():
            if name not in src:
                orphans.append(name)
            continue
        # A directory is reachable if the code names the directory, or names
        # a settings field that resolves to it, or names one of its files.
        if f'"{name}"' in src or f"/{name}/" in src or f"{name}/" in src:
            continue
        stems = {p.stem for p in entry.rglob("*") if p.is_file()}
        if any(stem in src for stem in stems):
            continue
        orphans.append(f"{name}/")
    assert not orphans, (
        "shipped under assets/ and loaded by nothing:\n  "
        + "\n  ".join(orphans)
        + "\n\nEither wire it up, delete it, or add it to _BY_HAND with the "
          "reason a human uses it directly.")


def test_the_by_hand_exceptions_still_exist():
    """An exemption for a directory that is gone is its own kind of stale."""
    missing = [name for name in _BY_HAND if not (ASSETS / name).is_dir()]
    assert not missing, f"exempted but absent: {missing}"


# --------------------------------------------------------------------------
# Template plate references.
# --------------------------------------------------------------------------

# `family/name` as it appears in prose and in shot templates. The families
# are read off the registry rather than listed, so a kit that adds one is
# covered the day it lands.
_TOKEN = re.compile(r"\b([a-z]+)/([a-z0-9][a-z0-9-]*)\b")

# Tokens that LOOK like a plate reference and are not.
_NOT_A_PLATE = {
    "and/or", "n/a", "w/h", "km/h",
}


@pytest.fixture(scope="module")
def registry():
    from pipeline.plates import PlateError, load_plates

    try:
        return load_plates(Settings(_env_file=None).assets_dir)
    except PlateError as e:
        pytest.skip(f"no design kit on this checkout: {e}")


def test_every_plate_a_template_names_resolves(registry):
    """The catalogue is generated and cannot drift; the prose around it was
    never checked, and it was wrong (M4)."""
    families = set(registry.families())

    problems: list[str] = []
    for tmpl in sorted((ROOT / "templates").rglob("*")):
        if not tmpl.is_file() or tmpl.suffix not in (".md", ".json"):
            continue
        text = tmpl.read_text(encoding="utf-8", errors="replace")
        for line_no, line in enumerate(text.splitlines(), 1):
            for m in _TOKEN.finditer(line):
                token = m.group(0)
                if token in _NOT_A_PLATE or m.group(1) not in families:
                    continue
                if registry.get(token) is not None:
                    continue
                # `room/talk` and `host/explain` are ROLES, not plate keys:
                # `roles.json` declares them and the registry resolves one to
                # a real plate by seed, which is what gives the angle
                # rotation. Naming a role is the correct way to reference a
                # room, so it is not drift.
                if m.group(1) == "room" and m.group(2) in registry.room_roles:
                    continue
                if m.group(1) == "host" and m.group(2) in registry.host_roles:
                    continue
                # An aspect STEM resolves per format: `peers/peer-strip`
                # becomes `peer-strip-16x9` or `-9x16`. Either resolution
                # counts, because the renderer picks by the video's aspect.
                if any(registry.aspect_key(token, aspect) is not None
                       for aspect in ("16x9", "9x16")):
                    continue
                # A deliberate "this does not exist — do not reach for it"
                # warning is accurate prose, not drift.
                if "does not exist" in line or "do not reach" in line:
                    continue
                problems.append(f"{tmpl.relative_to(ROOT)}:{line_no}: {token}")
    assert not problems, (
        "named in a template and absent from the kit:\n  "
        + "\n  ".join(problems))


# --------------------------------------------------------------------------
# The audio provenance gate (P0b).
# --------------------------------------------------------------------------
#
# THIS IS A GATE, NOT A BUG. It fails on a fresh checkout and it is supposed
# to: `assets/sfx/` ships fifteen ffmpeg oscillators with no `SOURCES.json`
# beside them, `generated_audio` counts a file with no provenance entry as
# generated, and `check_audio` therefore blocks every final render outside
# MOCK_MODE. All fifteen, not just the room bed — the gate is per file.
#
# The fix is an OPERATOR action and nobody else's:
#
#     export FREESOUND_API_KEY=...
#     python scripts/fetch_sfx.py
#     python scripts/check_sfx.py      # must report zero placeholders
#
# Do not route around this by hand-writing `generated: false` for a file that
# is still a sine sweep. That turns a gate that works into a gate that lies,
# and the thing it is guarding is a synthesised cash register reaching a
# published video.


def _sfx_dir() -> Path:
    return ASSETS / "sfx"


@pytest.mark.audio_provenance
def test_every_shipped_sound_has_provenance():
    """Every audio file under `assets/sfx/` carries a `SOURCES.json` entry
    saying where it came from and that it is not generated.

    Asserted on `generated_audio` — the function the blocking gate actually
    calls — rather than on the sidecar's contents, so this passes exactly
    when a final render would be allowed to proceed and not a moment before.
    """
    from pipeline.audio_assets import generated_audio

    settings = Settings(MOCK_MODE=True, assets_dir=ASSETS, _env_file=None)
    placeholders = generated_audio(settings)
    assert not placeholders, (
        f"{len(placeholders)} of the sound files a render plays are "
        f"synthesised placeholders, so `check_audio` BLOCKS every final "
        f"render outside MOCK_MODE:\n  " + "\n  ".join(placeholders)
        + "\n\nThis is the audio provenance gate doing its job, not a test to "
          "fix. An operator runs:\n"
          "    export FREESOUND_API_KEY=...\n"
          "    python scripts/fetch_sfx.py\n"
          "    python scripts/check_sfx.py\n"
          "Never hand-write `generated: false` for an oscillator.")


def test_the_fetch_script_fails_on_a_file_it_does_not_know_how_to_query():
    """`fetch_sfx.py` has to finish by asking the GATE's question.

    It used to compute "still fake" over its own fourteen query keys, while
    `check_audio` reads the directory and counts any file without provenance
    as a placeholder. So a run that attributed every key it knew about exited
    0 — reporting success — while a file outside that list left every final
    render blocked with nothing connecting the two. `room_tone.wav` is not a
    query key; neither is anything an operator drops in by hand.

    Run as a subprocess against a throwaway directory, because the exit code
    is the whole contract and a helper called directly would pass whatever
    `main` actually does.
    """
    import importlib.util
    import subprocess
    import tempfile

    from pipeline.audio_assets import AudioSource, save_sources

    spec = importlib.util.spec_from_file_location(
        "_fetch_sfx", ROOT / "scripts" / "fetch_sfx.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    keys = list(mod.QUERIES)

    with tempfile.TemporaryDirectory() as tmp:
        sfx = Path(tmp)
        attributed = {}
        for i, key in enumerate(keys + ["room_tone"]):
            (sfx / f"{key}.wav").write_bytes(b"RIFF")
            attributed[f"{key}.wav"] = AudioSource(
                name=f"{key}.wav", source=f"freesound.org/s/{i}/",
                licence="CC0", author="someone", generated=False)
        # One file the script has no query for, with no provenance — exactly
        # what an unfetchable room bed or a hand-dropped effect looks like.
        (sfx / "applause.wav").write_bytes(b"RIFF")
        save_sources(sfx, attributed)

        env = {"PATH": os.environ.get("PATH", ""),
               "PYTHONPATH": str(ROOT),
               # A key so `main` gets past the token check; nothing is
               # fetched because every query key is already attributed.
               "FREESOUND_API_KEY": "not-used-offline"}
        got = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "fetch_sfx.py"),
             "--out", str(sfx)],
            capture_output=True, text=True, env=env, cwd=ROOT, timeout=120)

        assert got.returncode == 1, (
            "the script reported success while a file with no provenance "
            "was still blocking every final render:\n"
            + got.stdout + got.stderr)
        assert "applause.wav" in got.stderr
        assert "INCOMPLETE" in got.stderr
        assert "BLOCKS a final render" in got.stderr

        # …and it reports success once that file is attributed too.
        attributed["applause.wav"] = AudioSource(
            name="applause.wav", source="freesound.org/s/99/",
            licence="CC0", author="someone", generated=False)
        save_sources(sfx, attributed)
        ok = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "fetch_sfx.py"),
             "--out", str(sfx)],
            capture_output=True, text=True, env=env, cwd=ROOT, timeout=120)
        assert ok.returncode == 0, ok.stdout + ok.stderr
        assert "still fake  : 0" in ok.stdout


def test_the_fetch_script_and_the_gate_share_one_definition_of_audio():
    """Two implementations of "which files are placeholders" is how they come
    to disagree, and the disagreement is a silent render block: a file the
    script does not consider audio but the gate does gets reported as fetched
    and refuses every final render.

    Exercised against a directory holding more than one container, because
    `assets/sfx/` happens to be all `.wav` — so a narrowed suffix list there
    would look identical either way.
    """
    import importlib.util
    import tempfile

    from pipeline.audio_assets import generated_audio, load_sources

    spec = importlib.util.spec_from_file_location(
        "_fetch_sfx_defs", ROOT / "scripts" / "fetch_sfx.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    with tempfile.TemporaryDirectory() as tmp:
        assets = Path(tmp)
        sfx = assets / "sfx"
        sfx.mkdir(parents=True)
        for name in ("ding.wav", "crowd.mp3", "bed.ogg", "notes.txt"):
            (sfx / name).write_bytes(b"RIFF")
        settings = Settings(MOCK_MODE=True, assets_dir=assets, _env_file=None)

        theirs = mod._unattributed(sfx, load_sources(sfx))
        ours = [p.removeprefix("sfx/") for p in generated_audio(settings)]
        assert theirs == ours, (
            "fetch_sfx.py and the audio gate disagree about which files are "
            f"placeholders: script says {theirs}, gate says {ours}")
        assert ours == ["bed.ogg", "crowd.mp3", "ding.wav"], ours
        assert "notes.txt" not in " ".join(ours)

    # …and on the real directory too, which is the one that matters.
    sfx = _sfx_dir()
    settings = Settings(MOCK_MODE=True, assets_dir=ASSETS, _env_file=None)
    assert (mod._unattributed(sfx, load_sources(sfx))
            == [p.removeprefix("sfx/") for p in generated_audio(settings)])


def test_the_room_bed_is_not_the_whole_job():
    """Two things that were documented wrongly, and both mattered.

    `--room-tone` is `store_true, default=True` — already on — so passing it
    explicitly changes nothing and calling it required is wrong. And the room
    bed is one file of fifteen: an operator who fetched only that would have
    found fourteen blockers left and no explanation of why the render still
    refused.
    """
    import importlib.util
    import tempfile

    from pipeline.audio_assets import AudioSource, generated_audio, save_sources

    spec = importlib.util.spec_from_file_location(
        "_fetch_sfx_flags", ROOT / "scripts" / "fetch_sfx.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # The flag is on without being asked for.
    assert mod.main.__module__
    parser_default = mod.argparse.ArgumentParser()
    del parser_default
    src = (ROOT / "scripts" / "fetch_sfx.py").read_text(encoding="utf-8")
    assert '"--room-tone", action="store_true", default=True' in src.replace(
        "\n                    ", " "), "the room bed stopped defaulting on"
    assert len(mod.QUERIES) >= 14, "the effect taxonomy shrank"

    # And one attributed file does not clear the gate for the rest.
    with tempfile.TemporaryDirectory() as tmp:
        assets = Path(tmp)
        sfx = assets / "sfx"
        sfx.mkdir(parents=True)
        for name in ("room_tone.wav", "cash_register.wav", "ding.wav"):
            (sfx / name).write_bytes(b"RIFF")
        save_sources(sfx, {"room_tone.wav": AudioSource(
            name="room_tone.wav", source="freesound.org/s/1/",
            licence="CC0", author="someone", generated=False)})
        settings = Settings(MOCK_MODE=True, assets_dir=assets, _env_file=None)
        assert generated_audio(settings) == ["sfx/cash_register.wav",
                                             "sfx/ding.wav"]


def test_the_sfx_check_script_passes_only_when_a_render_could_proceed():
    """`scripts/check_sfx.py` is what the operator runs, so its exit code is
    the contract — not the text it prints. Exercised both ways against a
    throwaway assets dir, because on this checkout it can only ever fail."""
    import subprocess
    import tempfile

    from pipeline.audio_assets import AudioSource, save_sources

    def _run(assets: Path) -> subprocess.CompletedProcess:
        env = {"PATH": os.environ.get("PATH", ""),
               "MOCK_MODE": "true", "ASSETS_DIR": str(assets),
               "PYTHONPATH": str(ROOT)}
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "check_sfx.py")],
            capture_output=True, text=True, env=env, cwd=ROOT)

    with tempfile.TemporaryDirectory() as tmp:
        assets = Path(tmp)
        sfx = assets / "sfx"
        sfx.mkdir(parents=True)
        (sfx / "ding.wav").write_bytes(b"RIFF")
        (sfx / "pop.wav").write_bytes(b"RIFF")

        bad = _run(assets)
        assert bad.returncode == 1, bad.stdout + bad.stderr
        assert "BLOCKED" in bad.stderr
        assert "ding.wav" in bad.stderr and "pop.wav" in bad.stderr

        save_sources(sfx, {
            name: AudioSource(name=name, source=f"freesound.org/s/{i}/",
                              licence="CC0", author="someone", generated=False)
            for i, name in enumerate(("ding.wav", "pop.wav"))})
        good = _run(assets)
        assert good.returncode == 0, good.stdout + good.stderr
        assert "PASS" in good.stdout

