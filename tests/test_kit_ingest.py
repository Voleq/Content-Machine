"""The ingest proves the delivery, draws it, installs it — and nothing else.

`scripts/ingest_kit.py` is the only bridge between the design kit — a
JavaScript engine plus per-family manifests of what it draws — and
`assets/plates/`, which is what every render reads. Both halves of that bridge
have failed silently before, and the failure always looks the same from the
outside: the ingest runs, prints a number, and the number is of the wrong
thing.

Nothing here runs the engine. It needs `node` and a few minutes, and it is the
operator's step (CI runs it). What is tested is everything the ingest decides
in Python: which files are the delivery's slot tables, what a room and a host
install as, what counts as a disagreement, how design's notes are filed and
checked, and what the curation may not do.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from pipeline.plates import PlateError

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "kit"

_spec = importlib.util.spec_from_file_location(
    "_ingest_kit", ROOT / "scripts" / "ingest_kit.py")
ingest = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ingest)


def _roles() -> dict:
    return json.loads((KIT / "roles.json").read_text(encoding="utf-8"))


def _shipped() -> dict:
    return ingest._shipped_slot_tables(KIT)


@pytest.fixture(scope="module")
def registry():
    from config import Settings
    from pipeline.plates import load_plates

    try:
        return load_plates(Settings(_env_file=None).assets_dir)
    except PlateError as exc:
        pytest.skip(f"no design kit on this checkout: {exc}")


# --------------------------------------------------------------------------
# What a delivery is, and where its slot tables are.
# --------------------------------------------------------------------------


def test_the_kit_in_the_repository_is_a_rebuild_delivery():
    """The rebuild is an engine the ingest runs, not a set of pictures. The
    drawn kit before it is retired, not supported alongside, so a checkout
    whose `kit/` is not a rebuild is refused before anything is drawn."""
    for marker in ingest.REBUILD_MARKERS:
        assert (KIT / marker).exists(), f"kit/{marker} is missing"
    for family in ingest.EXPECTED_FAMILIES:
        assert (KIT / family / "manifest.json").is_file(), family


def test_a_delivery_that_is_not_a_rebuild_is_refused_before_anything_runs(
        tmp_path):
    (tmp_path / "engine").mkdir()
    with pytest.raises(PlateError, match="not a rebuild delivery"):
        ingest.build(tmp_path)


def test_every_family_ships_the_slot_tables_it_counts():
    """A manifest that says 133 plates and tables 132 has lost one, and the
    reconciliation would report the drawn one as unpublished — a design bug
    that reads as an ingest bug."""
    shipped = _shipped()
    assert {k.split("/", 1)[0] for k in shipped} == set(ingest.EXPECTED_FAMILIES)
    for family in sorted(ingest.EXPECTED_FAMILIES):
        raw = json.loads((KIT / family / "manifest.json").read_text(encoding="utf-8"))
        table = ingest._plate_table(raw)
        assert raw.get("pack"), f"{family}: the manifest does not name its pack"
        if "assetCount" in raw:
            assert raw["assetCount"] == len(table), family
        if family in ingest._FLAT_FAMILIES:
            continue      # drawn flat by kit-model.js and figure.js: no tables
        for key, entry in table.items():
            assert isinstance(entry.get("slots"), dict), f"{key}: no slot table"


@pytest.mark.parametrize("table", ["plates", "assets"])
def test_both_generations_of_the_manifest_table_are_read(tmp_path, table):
    """delta-14 renamed the table `assets` -> `plates`. Reading both is not
    the same mistake as accepting two locations: the key is a fact about
    which pack generated the file, where a second search path would be a
    decision about where files live."""
    fam = tmp_path / "charts"
    fam.mkdir(parents=True)
    entry = {"canvas": [1920, 1080], "exportScale": 2, "slots": {}}
    (fam / "manifest.json").write_text(
        json.dumps({"family": "charts", table: {"charts/x-16x9": entry}}),
        encoding="utf-8")
    assert ingest._shipped_slot_tables(tmp_path) == {"charts/x-16x9": entry}


def test_the_emitters_manifest_is_never_read_as_a_slot_table(tmp_path):
    """The rebuild also ships `emit/manifest.json`, which a `*/manifest.json`
    glob matches. It names every plate once without its aspect and carries a
    slot COUNT, not slots — read as a slot table it reports every plate the
    engine draws as undeclared."""
    (tmp_path / "emit").mkdir()
    (tmp_path / "emit" / "manifest.json").write_text(json.dumps(
        {"assets": {"charts/x": {"slots": 3}}}), encoding="utf-8")
    assert ingest._shipped_slot_tables(tmp_path) == {}


def test_a_room_installs_at_both_aspects_and_the_host_at_one(tmp_path):
    """A room publishes one table for both aspects and the driver crops it
    once per aspect; the host's figure is one drawing at every aspect. The
    preflight compares the installed library against these keys, so either
    spelled wrong reads as a kit that was never ingested."""
    for family, key in (("room", "room/desk-front"), ("host", "host/to-camera"),
                        ("cards", "cards/term-16x9")):
        (tmp_path / family).mkdir()
        (tmp_path / family / "manifest.json").write_text(json.dumps(
            {"plates": {key: {"slots": {}}}}), encoding="utf-8")
    assert ingest._shipped_keys(tmp_path) == {
        "room/desk-front-16x9", "room/desk-front-9x16", "host/to-camera",
        "cards/term-16x9"}


# --------------------------------------------------------------------------
# The engine drew it; the delivery said what it would be.
# --------------------------------------------------------------------------


def _drawn(key: str, **over) -> dict:
    e = {"family": key.split("/", 1)[0], "hour": ingest.BASE_HOUR,
         "canvas": [1920, 1080], "exportScale": 2,
         "slots": {"title": {"x": 100, "y": 80, "w": 600, "h": 90}},
         "typeRoles": {"title": {"size": 60, "note": "prose"}}}
    e.update(over)
    return e


def test_agreement_is_silent_and_a_moved_slot_is_named():
    built = {"cards/term-16x9": _drawn("cards/term-16x9")}
    shipped = {"cards/term-16x9": {k: copy.deepcopy(v) for k, v in
                                    built["cards/term-16x9"].items()
                                    if k in ("canvas", "exportScale", "slots",
                                             "typeRoles")}}
    assert ingest._reconcile(built, shipped) == []

    shipped["cards/term-16x9"]["slots"]["title"]["x"] = 140
    got = ingest._reconcile(built, shipped)
    assert len(got) == 1 and "cards/term-16x9: slots disagrees" in got[0]


def test_a_type_budget_is_reconciled_and_its_prose_is_not():
    """The role-level floor is the budget every slot without one of its own is
    measured against; a sentence about it that differs by two words is not a
    contract violation."""
    built = {"cards/term-16x9": _drawn("cards/term-16x9")}
    shipped = {"cards/term-16x9": _drawn("cards/term-16x9")}
    shipped["cards/term-16x9"]["typeRoles"]["title"]["note"] = "other prose"
    assert ingest._reconcile(built, shipped) == []
    shipped["cards/term-16x9"]["typeRoles"]["title"]["size"] = 48
    assert any("typeRoles['title']" in p for p in ingest._reconcile(built, shipped))


def test_an_undrawn_plate_and_an_unpublished_one_are_both_named():
    built = {"cards/term-16x9": _drawn("cards/term-16x9")}
    shipped = {"cards/term-16x9": _drawn("cards/term-16x9"),
               "cards/gone-16x9": _drawn("cards/gone-16x9")}
    assert any("cards/gone-16x9: the delivery declares it" in p
               for p in ingest._reconcile(built, shipped))
    built["cards/new-16x9"] = _drawn("cards/new-16x9")
    assert any("no published slot table" in p
               for p in ingest._reconcile(built, shipped))


def test_every_hour_is_one_shape_list():
    """Dusk is a second colour table read through one shape list. A dusk
    plate whose slots moved would put every figure somewhere else after
    sunset, and nothing about the plate would look wrong."""
    night = _drawn("cards/term-16x9")
    dusk = _drawn("cards/term-16x9", hour="dusk", atBaseHour="cards/term-16x9")
    built = {"cards/term-16x9": night, "cards/term-dusk-16x9": dusk}
    shipped = {"cards/term-16x9": _drawn("cards/term-16x9")}
    assert ingest._reconcile(built, shipped) == []
    dusk["slots"] = {"title": {"x": 0, "y": 0, "w": 1, "h": 1}}
    assert any("cards/term-dusk-16x9" in p
               for p in ingest._reconcile(built, shipped))


# --------------------------------------------------------------------------
# Design's note on every plate, read and never trusted.
# --------------------------------------------------------------------------


def _fragment(tmp_path: Path, entries: dict) -> Path:
    (tmp_path / "roles.fragment.json").write_text(json.dumps(entries),
                                                   encoding="utf-8")
    return tmp_path


def test_a_note_is_filed_under_the_plate_it_names_and_checked(tmp_path):
    """A value that resolves to nothing is a promise no shot can keep, so it
    is dropped and said out loud rather than merged."""
    built = {"cards/term-16x9": {}, "annotations/circle": {}}
    notes, problems, remarks = ingest._plate_notes(_fragment(tmp_path, {
        "_note": "ignored",
        "cards/term-16x9": {"purpose": " defines a term ", "caution": "short",
                            "chapter_types": ["valuation", "astrology"],
                            "sectors": ["energy", "crypto"]},
        "annotations/circle-16x9": {"purpose": "a ring round one figure"},
        "cards/retired-16x9": {"purpose": "a plate the rebuild removed"},
    }), built)
    assert problems == []
    term = notes["cards/term-16x9"]
    assert term["purpose"] == "defines a term" and term["caution"] == "short"
    assert term["chapterTypes"] == ["valuation"]
    assert term["sectors"] == ["energy"]
    # An aspect on a plate that has none is a spelling, not a stale entry.
    assert notes["annotations/circle"]["purpose"] == "a ring round one figure"
    assert "cards/retired-16x9" not in notes
    said = " ".join(remarks)
    assert "cards/retired-16x9" in said
    assert "'astrology'" in said and "'crypto'" in said


def test_a_delivery_with_no_notes_cannot_be_installed(tmp_path):
    """Every chapter's menu is built from the fragment. Without it every
    menu is empty, which is a problem, not a remark."""
    _notes, problems, _remarks = ingest._plate_notes(tmp_path, {})
    assert problems and "roles.fragment.json" in problems[0]


def test_the_installed_kit_carries_designs_notes(registry):
    """0 of 95 plates had a purpose before design wrote them. The writer's
    menu reads these, so a kit that installs without them is a menu of bare
    names."""
    content = [p for k, p in registry.assets.items()
               if p.family not in ("room", "host") and "-dusk" not in k]
    with_purpose = [p for p in content if p.purpose]
    assert len(with_purpose) >= 0.9 * len(content), (
        f"only {len(with_purpose)} of {len(content)} plates say what they are for")
    assert any(p.sectors for p in content), "no plate names a sector"
    assert any(p.caution for p in content), "no plate carries a caution"


# --------------------------------------------------------------------------
# The curation: held back is off every menu, and the host is placeable.
# --------------------------------------------------------------------------


def test_what_roles_json_holds_back_is_not_also_wired_in():
    """Empty since rebuild-21 fixed the plates and rooms it held; the rule is
    for the day a drop breaks one again."""
    roles = _roles()
    held_plates, held_rooms = ingest._held_back(roles)
    for role, stems in roles["roomRoles"].items():
        if role.startswith("_"):
            continue
        clash = set(stems) & set(held_rooms)
        assert not clash, f"the {role!r} room role stands him in held-back {clash}"


def test_a_held_back_plate_is_on_no_chapters_menu(registry):
    held = set(registry.held_back.get("plates", {}))
    assert registry.chapter_types_available()
    for ctype in registry.chapter_types_available():
        for key in registry.plates_for_chapter(ctype):
            assert ingest._stem(key) not in held, (
                f"{ctype} offers {key}, which roles.json holds back")


def test_the_installed_kit_satisfies_the_host_contract(registry):
    assert ingest._host_contract(registry) == []


class _HostStub:
    """Just enough registry for `_host_contract` to read."""

    def __init__(self, plates: dict, host_roles: dict, room_roles=None,
                 strips=None):
        self._plates = plates
        self.host_roles = host_roles
        self.room_roles = room_roles or {}
        self.held_back = {}
        self._strips = strips or {}

    def get(self, key):
        return self._plates.get(key)

    def host_strip(self, key, kind):
        return self._strips.get((key, kind))


def test_a_close_framing_with_nothing_to_play_between_words_is_refused():
    """A close-up held on its still is the closed mouth at close-up scale —
    a dash (ANSWERS.md §4, finding 2) — so a framing must ship the idle
    strip its silences are cut to."""
    framing = SimpleNamespace(key="host/close-up", floor_line_y=False, alpha=True)
    reg = _HostStub({"host/close-up": framing}, {"to-camera": ["host/close-up"]})
    got = ingest._host_contract(reg)
    assert any("host/close-up-idle" in p for p in got), got

    reg._strips[("host/close-up", "idle")] = object()
    assert ingest._host_contract(reg) == []


def test_a_room_that_paints_over_his_head_cannot_hold_a_role():
    """rebuild-19 shipped rooms that put a frame or a shelf in front of him,
    and every check passed because the rooms were checked with nobody in
    them. The driver stands him in each and measures it."""
    room = SimpleNamespace(key="room/x-16x9", refuses_host=False,
                           head_covered=0.6)
    reg = _HostStub({"room/x-16x9": room}, {}, room_roles={"talk": ["room/x"]})
    got = ingest._host_contract(reg)
    assert any("room/x-16x9" in p for p in got), got
    room.head_covered = 0.0
    assert ingest._host_contract(reg) == []


# --------------------------------------------------------------------------
# The driver, and the line between build time and render time.
# --------------------------------------------------------------------------


def test_every_engine_file_is_accounted_for_by_the_driver():
    """`kit_engine.js` refuses to run on an engine file it has never heard of,
    because an unnamed file loads nothing and fails no check. This is the
    same check without node, so a drop that adds a file is caught by the
    suite rather than by the operator's first ingest."""
    driver = (ROOT / "scripts" / "kit_engine.js").read_text(encoding="utf-8")
    named = set(re.findall(r'"([\w.-]+\.js)"', driver))
    on_disk = {p.name for p in (KIT / "engine").glob("*.js")}
    assert on_disk <= named, (
        f"engine file(s) the driver does not name: {sorted(on_disk - named)}")
    assert {"port.js", "kit-model.js", "figure.js"} <= named


def test_nothing_in_the_render_path_runs_the_engine():
    """Node is a build-time dependency. A bug in the kit has to break a
    build, not a published video, so nothing under pipeline/ or bot/ may
    shell out to it or import the ingest."""
    offenders = []
    for path in sorted([*(ROOT / "pipeline").rglob("*.py"),
                        *(ROOT / "bot").rglob("*.py")]):
        text = path.read_text(encoding="utf-8")
        if re.search(r"""["']node["']""", text) or "kit_engine" in text \
                or re.search(r"^\s*(from|import)\s+.*ingest_kit", text, re.M):
            offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, offenders


def test_the_preflight_notices_an_installed_kit_from_a_different_pack(tmp_path):
    """A pack lands in `kit/` as manifests and an engine; `assets/plates/`
    only changes when the ingest runs. In between, the render path draws the
    OLD library while the curation, the prompts and the reachability report
    all describe the new one — and nothing about a finished video would look
    wrong, because every plate it drew exists. It is just the wrong kit.
    """
    import os
    import subprocess
    import sys as _sys

    env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(ROOT),
           "MOCK_MODE": "true"}
    got = subprocess.run(
        [_sys.executable, str(ROOT / "scripts" / "check_preflight.py")],
        capture_output=True, text=True, env=env, cwd=ROOT, timeout=180)

    shipped = ingest._shipped_keys(KIT)
    from config import Settings
    from pipeline.plates import load_plates

    try:
        installed = set(load_plates(
            Settings(MOCK_MODE=True, _env_file=None).assets_dir).keys())
    except PlateError:
        installed = set()

    if shipped <= installed:
        assert "[PASS] design kit" in got.stdout, got.stdout
    else:
        assert "[FAIL] design kit" in got.stdout, got.stdout
        assert "ingest_kit.py" in got.stdout
        assert got.returncode == 1


# --------------------------------------------------------------------------
# What the library's SIZE and SHAPE are, and what must not assume them.
# --------------------------------------------------------------------------


def test_nothing_in_the_suite_hard_codes_the_library_size():
    """The kit went 143 -> 270 -> 1014 and will move again. A literal count in a
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
            if re.search(r"\bof \d{3,4} plates\b", line):
                offenders.append(f"{path.name}:{n}: {line.strip()}")
    assert not offenders, (
        "a plate count is asserted as a literal; read it off the registry "
        "instead:\n  " + "\n  ".join(offenders))


def test_the_playback_vocabulary_is_one_the_renderer_knows(registry):
    """`overlay` was a third value once, on the blink strips, and
    `Plate.animated` was `playback != "static"` — so an overlay strip would
    have played as a loop in its own right. What this holds is that a value
    no code path handles cannot arrive unnoticed."""
    known = {"static", "loop", "overlay"}
    got = {p.playback for p in registry.assets.values()}
    assert got <= known, f"playback value(s) nothing handles: {sorted(got - known)}"


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


# --------------------------------------------------------------------------
# §6 — two rules artwork cannot carry, so the writer has to.
# --------------------------------------------------------------------------


class _StubPlate:
    def __init__(self, key, aspect, purpose=""):
        self.key, self.aspect, self.purpose = key, aspect, purpose
        self.slots, self.keys = {}, {}
        self.sectors, self.caution = (), ""


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
    half-height from the same axis. (Both plates are held back today; the
    contract is what the filler must honour the day they are not.)
    """
    shipped = _shipped()
    for key in ("charts/insider-flow-6-16x9", "charts/insider-flow-12-16x9"):
        plate = shipped[key]
        marks = [s for s in plate["slots"].values() if s.get("role") == "mark"]
        assert marks, f"{key} declares no mark slots"
        assert len({s.get("axisY") for s in marks}) == 1 \
            and marks[0].get("axisY") is not None, f"{key}: not one axis"

        note = marks[0].get("note", "")
        assert "value / scale" in note, (
            f"{key}'s mark slot no longer states the shared-scale contract:\n"
            f"{note}")
        assert "half-height" in note

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


# --------------------------------------------------------------------------
# The boil, on the delivered artwork.
# --------------------------------------------------------------------------

# The families whose plates carry numbers a viewer reads a value off.
_DATA_FAMILIES = frozenset({
    "tables", "charts", "figures", "structure", "peers", "cycles",
})


def _frames_differ(a, b, box=None) -> bool:
    """Whether two frames differ anywhere in `box` (the whole frame if None).

    NOT `ImageChops.difference(...).getbbox()`, WHICH IS WRONG HERE AND SAYS SO
    QUIETLY. `getbbox()` on an RGBA image returns the box of non-transparent
    pixels, and a difference image between two frames with identical alpha is
    transparent everywhere — so it answers None for a pair whose colour
    channels differ in a million pixels. Written that way this check reported
    every room and every data plate as frozen. `getextrema()` reads all four
    channels and cannot be fooled the same way.
    """
    from PIL import ImageChops

    x, y = (a.crop(box), b.crop(box)) if box else (a, b)
    return any(hi > 0 for _, hi in ImageChops.difference(x, y).getextrema())


def test_a_data_plate_breathes_and_its_axes_do_not():
    """`kit/engine/build.js` §1.5, asserted against the PNGs the ingest wrote.

    THE RULE IS PER-MARK, NOT PER-PLATE, and that is what makes it testable at
    all. Every data plate used to be `playback: static` on the argument that a
    number moving three times a second cannot be read. The kit retracted the
    blanket form and kept the argument: the boil is turned on for a data
    plate's FURNITURE — paper edge, corner wear, rule lines, hatch — while
    `HAND.setBoil`'s gate keeps axis lines, series lines and underlays emitting
    the identical path they emitted at boil 0, bit for bit.

    So the check is not "does this plate declare static". That is a flag, and
    reading it told us nothing about whether a number moved. It is: the plate
    moves between frames, and inside its `axis` boxes nothing does.

    `axis` is the role asserted because it is one of the three §1.5 names and
    it is the one the PLATE actually draws. A `figure` box is empty on a data
    plate — there is no baked text anywhere in the kit, every figure is a slot
    the renderer fills — so pixels inside one are whatever furniture passes
    through, and `bar`, `series` and `highlight-band` are regions the plate
    draws furniture into. Asserting on those would be asserting that furniture
    holds still, which is the opposite of the rule.
    """
    from PIL import Image

    from config import Settings
    from pipeline.plates import PlateError, load_plates

    try:
        registry = load_plates(Settings(_env_file=None).assets_dir)
    except PlateError as exc:
        pytest.skip(f"no design kit on this checkout: {exc}")

    checked = 0
    breathing = 0
    moved: list[str] = []
    for key in sorted(registry.assets):
        plate = registry.get(key)
        if plate.family not in _DATA_FAMILIES:
            continue
        boxes = [s for s in plate.slots.values()
                 if s.role == "axis" and s.w > 0 and s.h > 0]
        if not boxes:
            continue
        paths = plate.frame_paths()
        if len(paths) < 2:
            continue
        frames = [Image.open(q).convert("RGBA") for q in paths]
        if any(_frames_differ(frames[0], f) for f in frames[1:]):
            breathing += 1
        for slot in boxes:
            x, y, w, h = slot.scaled()
            box = (max(x, 0), max(y, 0),
                   min(x + w, frames[0].width), min(y + h, frames[0].height))
            if box[2] <= box[0] or box[3] <= box[1]:
                continue
            checked += 1
            # EVERY FRAME AGAINST THE FIRST, not just the second. The boil
            # indices are 1, 2 and 5 — a pair that happens to rasterise the
            # same says nothing about the third.
            if any(_frames_differ(frames[0], f, box) for f in frames[1:]):
                moved.append(f"{key}:{slot.name}")

    assert checked, "no data plate declares an axis slot — has the kit changed shape?"
    assert not moved, (
        f"{len(moved)} axis box(es) move between frames. An axis IS a "
        f"measurement reference: move it and the data appears to move even "
        f"though the series is pinned (build.js §1.5).\n  "
        + "\n  ".join(moved[:12]))
    # AND THE OTHER HALF, or this passes on a kit where the boil stopped
    # landing anywhere. Pinned axes on a library that does not move at all is
    # exactly the check that passes because it never looked. Asserted across
    # the set rather than per plate: whether a given plate has any furniture
    # inside HAND.breathe() is a drawing decision, and several ship three
    # identical frames today.
    assert breathing, (
        "no data plate with an axis differs between any two of its frames — "
        "the frame is not breathing anywhere, so the pinned-axis check above "
        "proved nothing")
