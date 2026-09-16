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
