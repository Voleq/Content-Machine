"""Type budgets: the number for the BOX, and the loader that has to know it.

`maxChars` is the kit's own limit on how much copy a slot holds, and delta-10a
moved it onto the slot. That matters because one role is set in boxes of very
different widths on the same plate — `structure/flow-16x9` sets `caption` in a
1620-unit strip and again in four 104-unit arrow labels — so a single number
per role is wrong in one of them by construction.

Everything here exists because of a failure that made no noise:

* an engine file the loader was never told about loaded nothing, failed no
  check, and surfaced 103 files later as a geometry disagreement;
* a role table shared by reference between plates was mutated in place during
  derivation, so the last plate to derive won for all of them — 139 of 425
  floors emitted as one library-wide constant, 96 of them looser than the
  delivery, with every geometry field agreeing perfectly throughout.

Both were silent. Neither was a hard problem once something said so.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from pipeline.plates import load_plates

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "kit"
FAMILIES = ("annotations", "cards", "charts", "cycles", "figures", "frames",
            "host", "overlays", "paper", "peers", "room", "shorts",
            "structure", "tables")


@pytest.fixture()
def reg(settings):
    return load_plates(settings.assets_dir)


def _manifests() -> dict:
    out: dict = {}
    for fam in FAMILIES:
        out.update(json.loads((KIT / fam / "manifest.json")
                              .read_text(encoding="utf-8"))["assets"])
    return out


# --------------------------------------------------------------------------
# §0 — an engine file nobody named must stop the build.
# --------------------------------------------------------------------------
def test_every_engine_file_is_named_in_the_loader():
    """`kit/engine/*.js` is accounted for, one way or the other.

    `budget.js` arrived carrying the whole derivation and was not in
    ENGINE_FILES. It did not fail: `Plate.manifest()` calls it behind
    `if (g.BUDGET && ...)`, so BUDGET was undefined, the hook was skipped, and
    the engine emitted slots with no budgets while the delivered manifests
    carried them. The missing feature was not the bug — nothing saying anything
    was.
    """
    src = (ROOT / "scripts" / "kit_engine.js").read_text(encoding="utf-8")

    def names(const: str) -> set[str]:
        m = re.search(rf"const {const} = \[(.*?)\];", src, re.S)
        assert m, f"{const} is not declared in kit_engine.js"
        return set(re.findall(r'"([^"]+)"', m.group(1)))

    known = names("ENGINE_FILES") | names("ENGINE_NOT_LOADED")
    on_disk = {p.name for p in (KIT / "engine").glob("*.js")}
    assert on_disk <= known, (
        f"engine file(s) in neither list: {sorted(on_disk - known)}. An "
        f"unnamed file loads nothing and fails no check.")
    # The other direction — a file NAMED here but absent from disk — is already
    # fatal in the loader ("missing engine file"), so it needs no assertion.


def test_budget_js_loads_before_the_hook_that_calls_it():
    """Order is load-bearing: `hand.js` reads `g.BUDGET` at manifest time."""
    src = (ROOT / "scripts" / "kit_engine.js").read_text(encoding="utf-8")
    order = re.findall(r'"([^"]+\.js)"',
                       re.search(r"const ENGINE_FILES = \[(.*?)\];", src, re.S).group(1))
    assert "budget.js" in order, "budget.js is not loaded at all"
    assert order.index("budget.js") < order.index("hand.js"), \
        "budget.js must load before hand.js, whose Plate.manifest() calls it"


def test_the_loader_rejects_an_unaccounted_engine_file(tmp_path):
    """Not a code read — the build actually stops, with a message worth having."""
    kit = tmp_path / "kit"
    (kit / "engine").mkdir(parents=True)
    for js in (KIT / "engine").glob("*.js"):
        (kit / "engine" / js.name).write_bytes(js.read_bytes())
    (kit / "engine" / "zz-unnamed.js").write_text("// arrived with a pack\n")

    proc = subprocess.run(
        ["node", str(ROOT / "scripts" / "kit_engine.js"),
         "--kit", str(kit), "--out", str(tmp_path / "out"), "--only", "overlays"],
        capture_output=True, text=True, cwd=ROOT, timeout=300)
    assert proc.returncode != 0, "a stray engine file did not stop the build"
    assert "zz-unnamed.js" in proc.stderr
    assert "not accounted for" in proc.stderr


# --------------------------------------------------------------------------
# §1 — the budget belongs to the box, and the role holds the floor.
# --------------------------------------------------------------------------
def test_a_slot_carries_its_own_budget(reg):
    plate = reg.require("structure/flow-16x9")
    # The example the shape change exists for: one role, two box widths.
    assert plate.slot("caption").w == 1620
    assert plate.slot("arrow-1").w == 104
    assert plate.slot("caption").max_chars > plate.slot("arrow-1").max_chars * 5


def test_the_budget_prefers_the_box_and_falls_back_to_the_role(reg):
    from pipeline.plate_frames import budget, type_role

    plate = reg.require("structure/flow-16x9")
    for name in ("caption", "arrow-1"):
        slot = plate.slot(name)
        assert budget(plate, slot)["maxChars"] == slot.max_chars

    # A slot with no budget of its own is measured against the role's floor
    # rather than against nothing, which is what keeps a reader that only knows
    # roles inside every box.
    bare = next((s for p in reg.assets.values() for s in p.slots.values()
                 if s.is_text and not s.max_chars
                 and (type_role(p, s) or {}).get("maxChars")), None)
    if bare is not None:
        owner = next(p for p in reg.assets.values() if bare in p.slots.values())
        assert budget(owner, bare)["maxChars"] == type_role(owner, bare)["maxChars"]


def test_the_role_floor_is_the_narrowest_box_that_sets_it():
    """The floor is a FLOOR. If it were the widest box, a reader that only
    knows roles would go loose on every other one — the direction that lets
    copy through to collide with the rule beside it."""
    checked = 0
    for key, asset in _manifests().items():
        by_role: dict[str, list[int]] = {}
        for slot in asset["slots"].values():
            if "maxChars" in slot:
                by_role.setdefault(slot.get("role"), []).append(slot["maxChars"])
        for role, spec in (asset.get("typeRoles") or {}).items():
            boxes = by_role.get(role)
            if "maxChars" not in spec or not boxes:
                continue
            assert spec["maxChars"] == min(boxes), (
                f"{key} typeRoles[{role!r}] declares {spec['maxChars']} but its "
                f"narrowest box allows {min(boxes)}")
            checked += 1
    assert checked > 100, f"only {checked} role floors checked"


def test_check_budgets_measures_against_the_box_not_the_role(settings, reg):
    """A string that fits the role's floor but not this box is refused.

    Sized for `structure/flow`'s 1620-unit caption strip, a 100-character line
    sails through; the four 104-unit arrow labels on the same plate hold six.
    """
    from pipeline.compose import BuildResult, Layer, check_budgets
    from pipeline.shots import Format

    plate = reg.require("structure/flow-16x9")
    long_line = "x" * (plate.slot("caption").max_chars)
    result = BuildResult(
        layers=[Layer(name="p", kind="plate", shot_id="s1", t_start=0.0,
                      t_end=1.0, entry_key=plate.key,
                      values={"arrow-1": long_line})],
        spans=[], frame=(1920, 1080))
    over = check_budgets(Format.__new__(Format), result, reg)
    assert over, "a caption-sized line was waved through a 104-unit arrow label"
    assert "arrow-1" in over[0]


# --------------------------------------------------------------------------
# The reconcile that would have caught the shared-role-table bug.
# --------------------------------------------------------------------------
def test_the_engine_and_the_delivery_agree_on_every_type_role(reg):
    """Not just geometry. `typeRoles` carries the face every word is set in AND
    the role floor, and it went 139-of-425 wrong with every geometry field
    agreeing perfectly."""
    from scripts.ingest_kit import _role_diffs  # noqa: PLC0415

    installed = json.loads(
        (Path(reg.root) / "plates-registry.json").read_text(encoding="utf-8")
    )["assets"]
    shipped = _manifests()
    problems = []
    for key, want in shipped.items():
        problems += [(key, r) for r, _, _ in _role_diffs(installed[key], want)]
    assert not problems, f"{len(problems)} type-role disagreements: {problems[:5]}"


def test_reconcile_compares_type_roles():
    """The check itself, on a synthetic pair — so it cannot quietly stop
    comparing the field and still pass the test above."""
    from scripts.ingest_kit import _role_diffs

    built = {"typeRoles": {"caption": {"size": 26, "maxChars": 103}}}
    shipped = {"typeRoles": {"caption": {"size": 26, "maxChars": 6}}}
    assert _role_diffs(built, shipped)

    # Prose that describes the numbers is not the contract: reconciling on it
    # would fail every build over "was 40" against "authored was 40".
    built = {"typeRoles": {"caption": {"maxChars": 6, "budget": "was 40"}}}
    shipped = {"typeRoles": {"caption": {"maxChars": 6, "budget": "authored was 40"}}}
    assert not _role_diffs(built, shipped)


def test_the_derivation_does_not_leak_one_plates_floor_into_another(reg):
    """`plates.js` hands the same role object to several plates by reference.

    `cards/definition`'s `example`, `cards/quote-pull`'s `source` and
    `structure/flow`'s `caption` are all `TR.caption`. Deriving in place gave
    every one of them the same number.
    """
    floors = {
        k: (reg.require(k).type_roles.get(role) or {}).get("maxChars")
        for k, role in (("structure/flow-16x9", "caption"),
                        ("cards/definition-16x9", "example"),
                        ("cards/quote-pull-16x9", "source"),
                        ("cards/criteria-16x9", "caption"))
    }
    assert len(set(floors.values())) > 1, (
        f"four plates sharing one role object all report the same floor "
        f"{floors} — the derivation is mutating a shared spec again")
    assert floors["structure/flow-16x9"] == 6, floors


# --------------------------------------------------------------------------
# The budgets, against the real fonts.
# --------------------------------------------------------------------------
def test_courier_prime_is_monospaced_at_the_declared_advance(settings):
    """0.5996em, every glyph, regular AND bold — the claim 260 role budgets
    rest on. Exact, so those numbers are exact."""
    fonttools = pytest.importorskip("fontTools.ttLib")

    for face in ("CourierPrime-Regular.ttf", "CourierPrime-Bold.ttf"):
        font = fonttools.TTFont(settings.fonts_dir / face)
        upem = font["head"].unitsPerEm
        widths = {w for w, _ in font["hmtx"].metrics.values() if w}
        assert len(widths) == 1, f"{face} is not monospaced: {sorted(widths)}"
        assert abs(widths.pop() / upem - 0.5996) < 1e-4, face


def test_a_budget_length_line_fits_the_box_it_is_budgeted_for(settings, reg):
    """The budget is an average, and this is what an average has to be worth.

    A frequency-weighted run of the class the role sets, at exactly `maxChars`,
    measured in the real face at the declared size. The median has to fit —
    a budget whose typical string overflows is not a budget.
    """
    import random
    import statistics

    from PIL import Image, ImageDraw

    from pipeline.plate_frames import _load, budget

    freq = {'e': 12.49, 't': 9.28, 'a': 8.04, 'o': 7.64, 'i': 7.57, 'n': 7.23,
            's': 6.51, 'r': 6.28, 'h': 5.05, 'l': 4.07, 'd': 3.82, 'c': 3.34,
            'u': 2.73, 'm': 2.51, 'f': 2.40, 'p': 2.14, 'g': 1.87, 'w': 1.68,
            'y': 1.66, 'b': 1.48, 'v': 1.05, 'k': 0.54, 'x': 0.23, 'j': 0.16,
            'q': 0.12, 'z': 0.09}
    lower, weights = list(freq), list(freq.values())
    draw = ImageDraw.Draw(Image.new("RGBA", (8, 8)))

    fills = []
    for plate in reg.assets.values():
        for name, slot in plate.slots.items():
            spec = budget(plate, slot)
            limit, size = spec.get("maxChars"), int(spec.get("size") or 0)
            if not (limit and size and slot.is_text):
                continue
            # Pool and weights are chosen together — a Courier slot that also
            # transforms to uppercase must not get letters against digit
            # weights. Courier is monospaced, so its class does not matter to
            # the width; the digits stand in for the figures it mostly sets.
            if "courier" in str(spec.get("font", "")).lower():
                pool, w = list("0123456789"), [1] * 10
            elif str(spec.get("transform", "")).lower() == "uppercase":
                pool, w = [c.upper() for c in lower], weights
            else:
                pool, w = lower, weights
            rng = random.Random(f"{plate.key}|{name}")
            runs = []
            for _ in range(12):
                out: list[str] = []
                while len(out) < int(limit):
                    take = min(rng.randint(3, 9), int(limit) - len(out))
                    out += rng.choices(pool, weights=w, k=take)
                    if len(out) < int(limit):
                        out.append(" ")
                text = "".join(out[: int(limit)])
                track = str(spec.get("tracking") or "")
                extra = (float(track[:-2]) * size * (len(text) - 1)
                         if track.endswith("em") else 0.0)
                runs.append(draw.textlength(text, font=_load(
                    settings, spec.get("font", "Courier Prime"),
                    int(spec.get("weight", 400) or 400), size)) + extra)
            fills.append(statistics.median(runs) / slot.w)

    assert len(fills) > 500, f"only {len(fills)} budgeted text slots measured"
    median_fill = statistics.median(fills)
    assert median_fill <= 1.0, (
        f"the typical budget-length line fills {median_fill:.1%} of its box — "
        f"budgets are loose, which is the direction that breaks a render")
    # And not so tight that the budget is refusing copy that would have fitted.
    assert median_fill > 0.6, f"budgets look over-tight at {median_fill:.1%}"
