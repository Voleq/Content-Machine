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


# --------------------------------------------------------------------------
# What the library's SIZE and SHAPE are, and what must not assume them.
# --------------------------------------------------------------------------


def test_nothing_in_the_suite_hard_codes_the_library_size():
    """The kit went 143 -> 270 and will move again. A literal count in a
    test turns a correct reach line into a failure on the day the operator
    ingests a new pack, which is the day it is hardest to tell a stale test
    from a real regression."""
    import re

    offenders: list[str] = []
    for path in sorted((ROOT / "tests").glob("*.py")):
        if path.name == "test_kit_ingest.py":
            continue      # this file counts on purpose, against the manifests
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.lstrip().startswith("assert"):
                continue
            if re.search(r"\bof (143|270) plates\b", line):
                offenders.append(f"{path.name}:{n}: {line.strip()}")
    assert not offenders, (
        "a plate count is asserted as a literal; read it off the registry "
        "instead:\n  " + "\n  ".join(offenders))


def test_the_playback_vocabulary_is_one_the_renderer_knows():
    """delta-14 introduced `overlay`, a third value, on the seven blink
    strips. `Plate.animated` was `playback != "static"`, so an overlay strip
    would have been played as a loop in its own right — a disembodied pair
    of eyelids — rather than composited over the matching idle frame.

    Nothing plays them yet, which is correct; what this holds is that a
    fourth value cannot arrive unnoticed.
    """
    from collections import Counter

    known = {"static", "loop", "overlay"}
    got = Counter(v.get("playback") for v in _shipped().values())
    unknown = set(got) - known
    assert not unknown, (
        f"playback value(s) no code path handles: {sorted(unknown)} — "
        f"`Plate.animated` and `plate_frames` both branch on this")
    assert got["overlay"] == 7, f"expected seven blink strips, got {got}"


def test_an_overlay_strip_is_not_treated_as_an_animation():
    """The failure this prevents, at the one place it is decided."""
    from pipeline.plates import Plate

    def _plate(playback: str) -> Plate:
        return Plate(
            key="host/close-up-blink", family="host", name="close-up-blink",
            canvas=(100, 100), delivered=(200, 200), export_scale=2,
            aspect="", playback=playback, fps=8.0, frame_count=6, frames=(),
            files_png="", files_svg="", base_is_frame="", slots={},
            type_roles={}, root=ROOT)

    assert _plate("loop").animated is True
    assert _plate("static").animated is False
    assert _plate("overlay").animated is False, (
        "a blink strip played as a loop is a pair of eyelids with no face "
        "behind them")


def test_the_data_plates_now_boil_and_that_is_the_packs_decision():
    """A design decision from delta-14 that reverses a documented rule, held
    here so it is a recorded fact rather than a surprise on the first render
    of a numbers sheet: the 143-plate kit had 47 static data plates; this
    one has three, and all three are furniture."""
    shipped = _shipped()
    static = sorted(k for k, v in shipped.items() if v.get("playback") == "static")
    assert static == ["overlays/lower-third-16x9", "overlays/lower-third-9x16",
                      "overlays/row-band"], static
    numbers = [k for k in shipped if k.startswith(("tables/", "charts/"))]
    assert numbers and all(shipped[k].get("playback") == "loop" for k in numbers)


# --------------------------------------------------------------------------
# §5 — the batched route, which exists because the ingest is memory-bound.
# --------------------------------------------------------------------------


def test_the_batched_route_partitions_the_library_and_merges_it(monkeypatch,
                                                                tmp_path):
    """One process per family, fourteen of them, each returning its memory to
    the OS before the next starts. Asserted on the merged registry rather
    than on the fact that `--only` was passed: what matters is that a
    batched build produces the same library a single pass would.

    The engine is faked — running it needs `node` and about thirty seconds a
    family, and it is the operator's step.
    """
    seen: list[str] = []

    def _fake_node(delivery, out, outfit, only=""):
        seen.append(only)
        return {"assets": {f"{only}/plate-{i}": {"canvas": [1, 1]}
                           for i in range(2)},
                "outfit": outfit}

    monkeypatch.setattr(ingest, "_node", _fake_node)
    merged = ingest._node_batched(tmp_path, tmp_path / "out", "shirt")

    assert sorted(seen) == sorted(ingest.EXPECTED_FAMILIES), (
        "a batched run must cover every family exactly once")
    assert len(merged["assets"]) == 2 * len(ingest.EXPECTED_FAMILIES)
    assert {k.split("/")[0] for k in merged["assets"]} == ingest.EXPECTED_FAMILIES
    assert merged["outfit"] == "shirt", "non-asset registry fields are carried"


def test_a_batch_that_draws_nothing_stops_the_run(monkeypatch, tmp_path):
    """A silent empty family would install a registry with a hole in it, and
    the hole is only visible when a render reaches for a plate that is not
    there."""
    def _fake_node(delivery, out, outfit, only=""):
        return {"assets": {} if only == "room" else {f"{only}/p": {}}}

    monkeypatch.setattr(ingest, "_node", _fake_node)
    with pytest.raises(ingest.PlateError) as err:
        ingest._node_batched(tmp_path, tmp_path / "out", "shirt")
    assert "room" in str(err.value)
    assert "--only room" in str(err.value), (
        "the error does not say how to retry just that family")


def test_two_batches_may_not_claim_the_same_plate(monkeypatch, tmp_path):
    """Merging fourteen registries is only sound because the batches
    partition the library. If two ever drew the same key, the last one would
    silently win and the reconcile would still pass."""
    def _fake_node(delivery, out, outfit, only=""):
        return {"assets": {"charts/shared": {}, f"{only}/own": {}}}

    monkeypatch.setattr(ingest, "_node", _fake_node)
    with pytest.raises(ingest.PlateError) as err:
        ingest._node_batched(tmp_path, tmp_path / "out", "shirt")
    assert "partition" in str(err.value)


def test_building_one_family_never_installs_a_registry(monkeypatch, tmp_path,
                                                       capsys):
    """`--only` is for regenerating the family a batched run failed on. A
    registry holding one family is not a kit, and writing one would leave
    the render path pointing at a library with thirteen holes in it."""
    installed: list = []
    monkeypatch.setattr(ingest, "_node", lambda d, o, outfit, only="": {
        "assets": {f"{only}/a": {"canvas": [1, 1], "exportScale": 2,
                                 "playback": "loop", "frameCount": 2,
                                 "slots": {}, "typeRoles": {}}}})
    monkeypatch.setattr(ingest, "_shipped_manifests", lambda d: {
        "charts/a": {"canvas": [1, 1], "exportScale": 2, "playback": "loop",
                     "frameCount": 2, "slots": {}, "typeRoles": {}},
        "room/b": {"canvas": [9, 9]}})
    monkeypatch.setattr(ingest, "_install",
                        lambda *a, **k: installed.append(a))

    rc = ingest._build_one(tmp_path, tmp_path / "s", "shirt", "charts")
    out = capsys.readouterr().out
    assert rc == 0
    assert installed == [], "a one-family build installed a registry"
    assert "NOT INSTALLED" in out
    # …and it reconciled against that family only, not against room/b.
    assert "1 plates match" in out


def test_the_two_batch_flags_are_not_combinable():
    """`--batched` builds all fourteen one at a time; `--only` builds one.
    Together they are ambiguous, and the ambiguous reading is the one that
    silently installs a partial kit."""
    import subprocess
    import sys as _sys

    got = subprocess.run(
        [_sys.executable, str(ROOT / "scripts" / "ingest_kit.py"),
         "kit", "--batched", "--only", "room"],
        capture_output=True, text=True, cwd=ROOT, timeout=120)
    assert got.returncode != 0
    assert "Pick one" in got.stderr

    bad = subprocess.run(
        [_sys.executable, str(ROOT / "scripts" / "ingest_kit.py"),
         "kit", "--only", "nosuchfamily"],
        capture_output=True, text=True, cwd=ROOT, timeout=120)
    assert bad.returncode != 0
    assert "unknown family" in bad.stderr


def test_the_memory_characteristic_is_written_down_where_it_is_hit():
    """§5.3: an OOM part way through an ingest should read as a known shape
    with a documented route out, not as a mystery on a machine the operator
    then assumes is too small."""
    ingest_md = (KIT / "INGEST.md").read_text(encoding="utf-8")
    assert "memory-bound" in ingest_md
    assert "--batched" in ingest_md and "--only" in ingest_md
    # The diagnosis matters as much as the workaround: a reader who thinks
    # it is plate cost goes looking for the big plate.
    assert "retention" in ingest_md
    assert "not plate cost" in ingest_md.lower()
    assert "400 MB" in ingest_md and "gitignored" in ingest_md

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    preflight = readme.split("## Preflight")[1].split("\n## ")[0]
    assert "memory-bound" in preflight
    assert "--batched" in preflight


# --------------------------------------------------------------------------
# §6 — two rules artwork cannot carry, so the writer has to.
# --------------------------------------------------------------------------


class _StubPlate:
    def __init__(self, key, aspect, purpose=""):
        self.key, self.aspect, self.purpose = key, aspect, purpose
        self.slots = {}


class _StubRegistry:
    def __init__(self, keys):
        self.assets = {k: _StubPlate(k, a) for k, a in keys}

    def families(self):
        return sorted({k.split("/")[0] for k in self.assets})

    def family(self, name):
        return sorted(k for k in self.assets if k.startswith(name + "/"))


@pytest.fixture()
def _stub_registry(monkeypatch):
    """The delta-14 plates the notes are about, without needing an ingest."""
    import pipeline.plates as plates_mod

    reg = _StubRegistry([
        ("charts/seasonality-4y-16x9", "16x9"),
        ("charts/seasonality-4y-9x16", "9x16"),
        ("charts/seasonality-6y-16x9", "16x9"),
        ("charts/seasonality-6y-9x16", "9x16"),
    ])
    monkeypatch.setattr(plates_mod, "load_plates", lambda *_a, **_k: reg)
    return reg


def test_the_nine_by_sixteen_seasonality_warning_reaches_the_writer(
        settings, _stub_registry):
    """§6: `seasonality-6y` in 9:16 is twenty-four columns and reads as four
    groups rising, not six dated years. No redraw fixes it — a wider column
    means fewer years, which is what `-4y` already is. So the writer is told
    beside the plate, in the catalogue the prompt generates."""
    from bot.prompts import plate_catalogue

    portrait = plate_catalogue(settings, fmt="short")
    line = next((ln for ln in portrait.splitlines()
                 if "seasonality-6y" in ln), None)
    assert line is not None
    idx = portrait.splitlines().index(line)
    note = "\n".join(portrait.splitlines()[idx:idx + 3])
    assert "NOT countable" in note
    assert "seasonality-4y" in note, "it does not name the plate to use instead"

    # …and the rule is aspect-specific: six years is fine across a 16:9.
    landscape = plate_catalogue(settings, fmt="long")
    line = next(ln for ln in landscape.splitlines() if "seasonality-6y" in ln)
    idx = landscape.splitlines().index(line)
    assert "NOT countable" not in "\n".join(
        landscape.splitlines()[idx:idx + 3]), (
        "the 9:16 warning is being shown on a 16:9 prompt, where six years "
        "are perfectly countable")


def test_the_dusk_rule_is_recorded_where_a_catalogue_note_cannot_reach():
    """The other half of §6, and the reason it is not a catalogue entry: a
    `[PLATE]` tag cannot name a room, so the writer never picks the angle
    and a note beside it would reach nobody. The renderer chooses from
    `roomRoles`, so the rule belongs with whoever wires the dusk variants
    into an episode-level selector."""
    from bot.prompts import DIRECTING_NOTES, RENDERER_DIRECTING_NOTES

    rule = RENDERER_DIRECTING_NOTES["room/*-dusk"]
    assert "widest" in rule.lower() and "tighter" in rule
    assert "never mix hours inside one video" in rule.lower(), (
        "the rule omits the constraint that makes it actionable")

    assert not any(str(k).startswith("room/") for k in DIRECTING_NOTES), (
        "a room rule is in the writer-facing catalogue, where a script "
        "cannot act on it")


# --------------------------------------------------------------------------
# §8 — insider-flow's shared-scale contract.
# --------------------------------------------------------------------------


def test_the_insider_flow_marks_declare_one_scale_for_both_directions():
    """§8: `charts/insider-flow-6` and `-12` draw buys and sells as marks
    sized by value. A compositor that scales the two directions
    independently draws a plate that looks entirely correct and shows a
    false relationship — a small buy and a large sell the same size, with
    nothing on screen to give it away.

    The plate declares the contract itself, and this pins it: one `scale`
    divides both directions, and both are measured against the same
    half-height from the same axis.
    """
    shipped = _shipped()
    for key in ("charts/insider-flow-6-16x9", "charts/insider-flow-12-16x9"):
        plate = shipped[key]
        assert "axisY" in plate["meta"], f"{key} has no axis to measure from"
        marks = [s for n, s in plate["slots"].items() if s.get("role") == "mark"]
        assert marks, f"{key} declares no mark slots"

        note = marks[0].get("note", "")
        assert "value / scale" in note, (
            f"{key}'s mark slot no longer states the shared-scale contract:\n"
            f"{note}")
        assert "half-height" in note

        # Every mark is the same box, measured off the same axis. Two scales
        # would need two geometries, so this is the shape of the contract as
        # well as its words.
        heights = {s["h"] for s in marks}
        tops = {s["y"] for s in marks}
        assert len(heights) == 1 and len(tops) == 1, (
            f"{key}'s marks do not share one geometry: heights={heights} "
            f"tops={tops} — a per-direction scale would look like this")


def test_the_series_fillers_that_exist_already_use_one_domain():
    """Nothing fills a `mark` slot yet — the role is new in delta-14 and no
    code path in `pipeline/` draws one, so the two-scale defect is not live.
    What this holds is the house pattern the filler must match when it is
    written: every existing series scales positives and negatives against a
    single domain that spans zero."""
    import inspect

    from pipeline import chart

    for fn in (chart.draw_bars, chart.draw_row_bars):
        src = inspect.getsource(fn)
        assert "min(0.0, min(vals))" in src and "max(0.0, max(vals))" in src, (
            f"{fn.__name__} no longer derives one domain spanning zero; a "
            f"per-direction scale draws a false relationship")

    # And nothing draws a `mark` slot today, which is what makes the
    # two-scale defect not live. Asked of the function that decides, with a
    # slot shaped like insider-flow's own.
    from pipeline.plate_tags import _draws_a_series
    from pipeline.plates import Slot

    mark = Slot(name="mark-1", x=276, y=153, w=110, h=753, role="mark",
                region=True)
    assert not _draws_a_series(mark), (
        "a `mark` slot is now drawn through a series — it must honour "
        "insider-flow's one-scale contract, and this assertion should "
        "become one about what it draws rather than about its absence")


def test_the_preflight_notices_an_installed_kit_from_a_different_pack(tmp_path):
    """A pack lands in `kit/` as manifests and an engine; `assets/plates/`
    only changes when the ingest runs. In between, the render path draws the
    OLD library while the curation, the prompts and the reachability report
    all describe the new one — and nothing about a finished video would look
    wrong, because every plate it drew exists. It is just the wrong kit.

    This is the state the repository is in until the operator ingests, so
    the check has to name it rather than report a plate count and pass.
    """
    import os
    import subprocess
    import sys as _sys

    env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(ROOT),
           "MOCK_MODE": "true"}
    got = subprocess.run(
        [_sys.executable, str(ROOT / "scripts" / "check_preflight.py")],
        capture_output=True, text=True, env=env, cwd=ROOT, timeout=180)

    shipped = len(ingest._shipped_manifests(KIT))
    from pipeline.plates import load_plates
    from config import Settings

    installed = len(load_plates(
        Settings(MOCK_MODE=True, _env_file=None).assets_dir).keys())

    if installed == shipped:
        assert "[PASS] design kit" in got.stdout
        assert "matching the shipped pack" in got.stdout
    else:
        assert "[FAIL] design kit" in got.stdout, got.stdout
        assert "never ingested" in got.stdout
        assert "ingest_kit.py" in got.stdout
        assert got.returncode == 1
