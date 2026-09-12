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

import re
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
