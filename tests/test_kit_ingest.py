"""The ingest reads the delivery the delivery was actually shipped as.

`scripts/ingest_kit.py` is the only bridge between the design kit — which is
a JavaScript engine plus per-family manifests — and `assets/plates/`, which
is what every render reads. Both halves of that bridge have failed silently
before, and the failure always looks the same from the outside: the ingest
runs, prints a number, and the number is of the wrong thing.

Nothing here runs the engine. It needs `node` and about thirty seconds a
family, and it is the operator's step.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "kit"

_spec = importlib.util.spec_from_file_location(
    "_ingest_kit", ROOT / "scripts" / "ingest_kit.py")
ingest = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ingest)


FAMILIES = ("annotations", "cards", "charts", "cycles", "figures", "frames",
            "host", "overlays", "paper", "peers", "room", "shorts",
            "structure", "tables")


# --------------------------------------------------------------------------
# The manifests are where the repository puts them, and the ingest finds them.
# --------------------------------------------------------------------------


def test_the_shipped_manifests_are_read_from_the_repository_layout():
    """delta-14 ships its manifests at `kit/manifests/<family>/manifest.json`
    and the ingest globs `kit/<family>/manifest.json`. Copied as-is the glob
    matches nothing, `_shipped_manifests` returns `{}`, and `_reconcile`
    compares the engine's output against an empty dict — so every plate is
    "the engine drew it, no manifest declares it", or worse, nothing is
    checked at all.

    The fix is the repository's layout, not a wider glob: two valid homes
    for a generated file is a worse state than one.
    """
    assert not (KIT / "manifests").exists(), (
        "kit/manifests/ is back — that is the drop's layout, and having the "
        "manifests in two places means the ingest reconciles against "
        "whichever it happens to find")

    shipped = ingest._shipped_manifests(KIT)
    assert len(shipped) == 270, f"expected 270 assets, got {len(shipped)}"
    assert {k.split("/")[0] for k in shipped} == set(FAMILIES)
    for family in FAMILIES:
        assert (KIT / family / "manifest.json").is_file(), family


def test_a_manifest_the_glob_cannot_reach_is_worth_nothing(tmp_path):
    """The failure this is guarding, in miniature: the same 270 assets one
    directory deeper read as zero, and nothing raises."""
    misplaced = tmp_path / "kit"
    (misplaced / "manifests" / "charts").mkdir(parents=True)
    (misplaced / "manifests" / "charts" / "manifest.json").write_text(
        (KIT / "charts" / "manifest.json").read_text(encoding="utf-8"),
        encoding="utf-8")

    assert ingest._shipped_manifests(misplaced) == {}, (
        "the glob now reaches kit/manifests/ — it must not; place the "
        "manifests in the repository layout instead")


@pytest.mark.parametrize("table", ["plates", "assets"])
def test_both_generations_of_the_manifest_table_are_read(tmp_path, table):
    """delta-14 renamed the table `assets` -> `plates`. Reading both is not
    the same mistake as accepting two locations: the key is a fact about
    which pack generated the file, where a second search path would be a
    decision about where files live."""
    fam = tmp_path / "kit" / "charts"
    fam.mkdir(parents=True)
    entry = {"canvas": [1920, 1080], "exportScale": 2, "frameCount": 3}
    (fam / "manifest.json").write_text(
        json.dumps({"family": "charts", table: {"charts/x-16x9": entry}}),
        encoding="utf-8")

    got = ingest._shipped_manifests(tmp_path / "kit")
    assert got == {"charts/x-16x9": entry}


def test_every_shipped_asset_carries_what_reconcile_compares():
    """`_reconcile` checks canvas, exportScale, playback, frameCount, slots
    and the typeRoles floors. A manifest missing one of those does not fail
    — it compares None against a real value for every plate, or agrees with
    itself about nothing. The schema changed in this drop, so this is the
    check that it changed compatibly."""
    shipped = ingest._shipped_manifests(KIT)
    required = ("canvas", "exportScale", "playback", "frameCount", "slots",
                "typeRoles")
    missing: dict[str, list[str]] = {}
    for key, entry in shipped.items():
        absent = [f for f in required if f not in entry]
        if absent:
            missing[key] = absent
    assert not missing, (
        f"{len(missing)} plate(s) lack fields `_reconcile` compares: "
        f"{dict(list(missing.items())[:5])}")


def test_the_delivery_declares_the_pack_it_came_from():
    """A manifest that cannot say which pack drew it makes a reconciliation
    failure unattributable."""
    charts = json.loads((KIT / "charts" / "manifest.json")
                        .read_text(encoding="utf-8"))
    assert charts.get("pack"), "the manifest does not name its pack"
    assert charts["assetCount"] == len(charts["plates"])


# --------------------------------------------------------------------------
# The files the drop does NOT ship have to still be here.
# --------------------------------------------------------------------------


def test_the_files_the_drop_does_not_replace_survived_the_upgrade():
    """The drop is a PARTIAL update: 35 files against a kit of 56. Clearing
    `kit/` first and copying the drop in is the obvious move and it destroys
    the build — and three of the four groups fail in a way that does not
    look like a missing file.
    """
    fonts = sorted(p.name for p in (KIT / "fonts").glob("*.ttf"))
    assert fonts, (
        "kit/fonts/ is empty — budget.js derives every maxChars in the kit "
        "from these metrics, so the failure will read as a budget bug")
    assert any("Archivo" in f for f in fonts) and any("Courier" in f for f in fonts)

    roles = json.loads((KIT / "roles.json").read_text(encoding="utf-8"))
    for table in ("hostRoles", "hostPoses", "roomRoles", "chapterTypes"):
        assert roles.get(table), (
            f"kit/roles.json lost {table} — this is the renderer's own role "
            f"table, and without it every room and host shot in every video "
            f"fails to resolve. It is NOT roles.fragment.json.")

    for name in ("render.js", "series.js", "sheet.js"):
        assert (KIT / "engine" / name).is_file(), (
            f"kit/engine/{name} is gone; the drop ships none of the three "
            f"and series.js is loaded by the driver")


def test_every_engine_file_is_accounted_for_by_the_driver():
    """`kit_engine.js` refuses to run on an engine file it has never heard
    of, because an unnamed file loads nothing and fails no check. The drop
    replaces five engine sources; this is the check that it did not add a
    sixth nobody wired in."""
    driver = (ROOT / "scripts" / "kit_engine.js").read_text(encoding="utf-8")
    named = set()
    for line in driver.splitlines():
        if line.startswith(("const ENGINE_FILES", "const ENGINE_NOT_LOADED")):
            named.update(part.strip().strip('"\'')
                         for part in line.split("[")[1].split("]")[0].split(","))
    on_disk = {p.name for p in (KIT / "engine").glob("*.js")}
    assert on_disk <= named, (
        f"engine file(s) the driver does not name: {sorted(on_disk - named)}")
    assert "series.js" in named and "render.js" in named


# --------------------------------------------------------------------------
# roles.fragment.json — merged into the renderer's vocabulary, never copied.
# --------------------------------------------------------------------------


def _fragment() -> dict:
    raw = json.loads((KIT / "roles.fragment.json").read_text(encoding="utf-8"))
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def _roles() -> dict:
    return json.loads((KIT / "roles.json").read_text(encoding="utf-8"))


def _shipped() -> dict:
    return ingest._shipped_manifests(KIT)


RENDERER_OWNED = {"room", "host", "annotations", "overlays", "frames"}


def test_the_fragment_is_not_the_renderers_roles_file():
    """`roles.fragment.json` is deliberately named so a copy cannot overwrite
    `roles.json`. They are different files with different jobs: one maps new
    plate keys to where they may appear, the other is the renderer's own
    role table and is what makes `room/talk` resolve to one of three desk
    angles by seed."""
    roles = _roles()
    for table in ("hostRoles", "hostPoses", "roomRoles", "chapterTypes",
                  "purposes", "wardrobe"):
        assert roles.get(table), f"roles.json lost {table}"
    frag = json.loads((KIT / "roles.fragment.json").read_text(encoding="utf-8"))
    assert "hostRoles" not in frag and "roomRoles" not in frag, (
        "roles.fragment.json now looks like roles.json — one of them has "
        "been copied over the other")


def test_every_name_the_fragment_uses_resolves_against_the_real_vocabulary():
    """An earlier fragment named 32 chapter types that do not exist. Every
    value here is checked against the sixteen real types, the four real
    formats and the structural shot ids the chapter files actually use — so
    a mapping cannot be merged into a slot nothing reads."""
    from pipeline.plates import CHAPTER_TYPES
    from pipeline.shots import available_formats

    formats = set(available_formats())
    shot_ids = set()
    for chapter in sorted((ROOT / "templates" / "chapters").glob("*.json")):
        spec = json.loads(chapter.read_text(encoding="utf-8"))
        shot_ids.update(s["id"] for s in spec["shots"])

    bad: list[str] = []
    for key, spec in _fragment().items():
        for c in (spec.get("chapter_types") or []):
            if c not in CHAPTER_TYPES:
                bad.append(f"{key}: chapter type {c!r} does not exist")
        for f in (spec.get("formats") or []):
            if f not in formats:
                bad.append(f"{key}: format {f!r} does not exist")
        for s in (spec.get("shot_ids") or []):
            if s not in shot_ids:
                bad.append(f"{key}: shot id {s!r} is in no chapter file")
    assert not bad, "\n".join(bad[:10])


def test_every_plate_the_fragment_maps_was_actually_shipped():
    """A mapping for a plate that does not exist is a route to nothing."""
    shipped = _shipped()
    missing = sorted(k for k in _fragment() if k not in shipped)
    assert not missing, f"mapped but not in any manifest: {missing}"


def test_the_fragments_chapter_mappings_reached_the_curation():
    """THE MERGE ITSELF. `plates_for_chapter` gates the library by chapter
    type off `roles.json`, so a plate the curation does not allow cannot be
    named by a `[PLATE]` tag no matter what the fragment says — and
    `reachable_plates` reports it as artwork with no route to the screen.

    Asserted by the curation's own prefix rule rather than by looking for a
    literal, because `"structure/language-shift"` legitimately covers both
    of its aspects.
    """
    roles = _roles()
    ct = roles["chapterTypes"]
    universal = ct["_universal"]

    def allowed(key: str, ctype: str) -> bool:
        prefixes = list(universal) + list((ct.get(ctype) or {}).get("plates") or [])
        return any(key == p or key.startswith(p) for p in prefixes)

    unreached: list[str] = []
    for key, spec in _fragment().items():
        if key.split("/", 1)[0] in RENDERER_OWNED:
            continue      # a director never names one of these; see below
        for ctype in (spec.get("chapter_types") or []):
            if not allowed(key, ctype):
                unreached.append(f"{key} is not allowed in {ctype}")
    assert not unreached, (
        f"{len(unreached)} fragment mapping(s) never reached the curation:\n  "
        + "\n  ".join(unreached[:12]))


def test_the_new_host_poses_and_room_angle_reached_the_role_tables():
    """The renderer-owned families take the other route: a `[PLATE]` tag
    cannot name the set or the man standing in it, so `roomRoles` and
    `hostPoses` are where these become reachable."""
    roles = _roles()
    assert "room/over-the-shoulder" in roles["roomRoles"]["read"], (
        "the over-the-shoulder angle has no role, so no shot can ask for it")

    poses = roles["hostPoses"]
    assert "host/sitting-at-desk" in poses, (
        "every LONG is him standing for forty minutes; the seated pose is "
        "the cheapest way to make a chapter feel like a different scene")
    assert poses["host/sitting-at-desk"]["talks"] is True
    assert "host/empty-chair" in poses
    assert poses["host/empty-chair"]["talks"] is False, (
        "an empty chair cannot have a talk strip")
    assert poses["host/empty-chair"]["limit"] == 1, (
        "the absence stops reading if it happens twice in one video")

    served = {k for v in roles["hostRoles"].values() if isinstance(v, list)
              for k in v}
    assert "host/sitting-at-desk" in served, "no shot role serves the seated pose"
    assert "host/empty-chair" in served


def test_the_furniture_and_the_blink_are_not_chapter_plates():
    """The two entries that carry `any` rather than a list, handled as the
    real cases they are.

    `overlays/lower-third` is composited over whatever the format is showing
    for as long as the director leaves it up — it belongs to the FORMAT, not
    to a beat, which is why its entry has no `beats` field at all.
    `host/close-up-blink` is not a pose and no template selects it: the
    renderer lays it over the idle strip, frame for frame.

    Both are renderer-owned, so putting them in a chapter's curation would
    be the wrong answer — a `[PLATE]` tag must not be able to name either.
    """
    frag = _fragment()
    third = frag["overlays/lower-third-16x9"]
    assert "beats" not in third, (
        "the lower third has acquired a beats field — it is persistent "
        "furniture, not a beat")
    assert set(third["formats"]) == {"long", "earnings", "macro"}

    blink = frag["host/close-up-blink"]
    assert blink.get("any") is True and blink.get("any_shot") is True
    assert blink["overlay_of"] == "host/close-up-idle"
    assert blink["playback"] == "overlay"

    roles = _roles()
    ct = roles["chapterTypes"]
    for name, spec in ct.items():
        if name.startswith("_"):
            continue
        for pre in (spec or {}).get("plates") or []:
            assert not pre.startswith("overlays/lower-third"), (
                f"{name} offers the lower third as a chapter plate; the "
                f"compositor places it, a director never names it")
            assert "blink" not in pre, f"{name} offers a blink overlay"
