#!/usr/bin/env python3
"""Materialise the design kit: prove it, draw it, install it, verify it.

    python scripts/ingest_kit.py kit              build from the delivery in kit/
    python scripts/ingest_kit.py kit --only room  draw one family and check it
    python scripts/ingest_kit.py --check          verify what is already on disk

THE KIT IS CODE, NOT PICTURES. The delivery is an engine, and every plate in
it is an author plus a seed plus arguments, drawn once per hour of the set. So
ingest RUNS the engine and writes real files out, and the render path then
loads plain PNGs exactly as it always did. Node is a build-time dependency and
must never appear in the render path: a bug in the kit has to break a build,
not a published video. Nothing under `pipeline/` imports this module or shells
out to node — `tests/test_kit_ingest.py` holds that line.

NOTHING HERE TRUSTS ANYTHING, and it runs in this order:

1. The kit proves itself, on a staged copy so the checkout is never written
   to: its own audit on the files it shipped, then its emitter's own check
   that every shipped manifest is what the engine writes (`node engine/emit.js
   --check`), then its own export, which the plates are checked against.
2. `scripts/kit_engine.js` draws every plate BLANK at every hour, and proves
   each one is design's exported file byte for byte. It also draws the host's
   close-up, which the kit specifies as a window rather than ships as a file,
   and stands him in every room to measure what paints over him.
3. Every drawn plate's slot table is checked against the one the delivery
   published, and every hour's slots against the base hour's.
4. Design's note on every plate (`roles.fragment.json`: purpose, caution,
   chapter types, sector) is filed under the key it names and checked against
   the vocabulary it claims; `roles.json` adds who stands where and what is
   held back.
5. The host and the rooms are checked against the roles that use them.

Every problem from every stage is collected and printed together, because a
drop that fails is a message to design, and a message that stops at the first
failure takes as many round trips as there are failures. Any single problem
exits non-zero and says DO NOT COMMIT, because a missing asset must never reach
a render and degrade quietly into an empty box.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.plates import (  # noqa: E402
    CHAPTER_TYPES, GICS_SECTORS, PLATES_DIRNAME, REGISTRY_NAME, PlateError,
    load_registry,
)

REPO = Path(__file__).resolve().parents[1]
DRIVER = REPO / "scripts" / "kit_engine.js"
STAGE = REPO / ".kit-build"

# The families the delivery ships. A family on disk that is not here, or one
# here with nothing on disk, is a delivery that changed shape without anyone
# saying so — which is the moment to look, not to carry on.
EXPECTED_FAMILIES = frozenset({
    "annotations", "cards", "charts", "cycles", "figures", "frames", "host",
    "overlays", "paper", "peers", "room", "shorts", "structure", "tables",
})

# The hour whose keys carry no suffix. The driver says the same; see there.
BASE_HOUR = "night"

# What a rebuild delivery is. The drawn kit before it was build.js and its
# manifests alone; this reads the flat model and the tokens, and a delivery
# without them is not something this script knows how to draw.
REBUILD_MARKERS = ("engine/kit-model.js", "engine/port.js", "design-tokens.json")


def _node(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    """One node process. Its stdout is data; stderr is for the operator."""
    try:
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    except FileNotFoundError:
        raise PlateError(
            "node is not on PATH. The kit is JS and is drawn at INGEST — "
            "install Node 18+ and run `npm ci` for the rasteriser. The render "
            "path needs neither."
        ) from None


def _stage(delivery: Path) -> Path:
    """A copy of the delivery to run the kit's own tools in.

    `emit.js` and `export.js` write into the kit's own `emit/` and `out/`, and
    the checkout's `kit/` is source. Running them in place would leave the
    working tree dirty after every ingest, and a regenerated manifest sitting
    in `kit/` is indistinguishable from one design shipped.
    """
    staged = STAGE / "delivery"
    if STAGE.exists():
        shutil.rmtree(STAGE)
    shutil.copytree(delivery, staged, ignore=shutil.ignore_patterns("out"))
    return staged


_AUDIT_FAIL = re.compile(r"^\s*FAIL\s+(\d+)\s+(.+?)\s*$")


def _audit(staged: Path, when: str) -> list[str]:
    """The kit's own audit, as a list of the rules it fails."""
    proc = _node(["node", "engine/audit.js", "--check"], staged)
    failed = [f"rule {m.group(1)} ({m.group(2)})"
              for line in proc.stdout.splitlines()
              if (m := _AUDIT_FAIL.match(line))]
    if proc.returncode == 0 and not failed:
        return []
    if not failed:
        tail = (proc.stderr or proc.stdout).strip().splitlines()[-1:] or ["no output"]
        return [f"the kit's audit {when} exits {proc.returncode}: {tail[0]}"]
    return [f"the kit's audit {when} fails {len(failed)} rule(s): {', '.join(failed)}"]


def _asset_count(staged: Path) -> int:
    path = staged / "emit" / "manifest.json"
    try:
        return len(json.loads(path.read_text(encoding="utf-8")).get("assets") or {})
    except (OSError, ValueError):
        return 0


def _kit_proves_itself(staged: Path) -> list[str]:
    """The kit's own checks, in the order its README gives them.

    THE SHIPPED FILES PASSING IS NOT THE SAME CLAIM AS THE KIT PASSING. The
    rebuild-14 drop passes 24 of 24 on the manifest it shipped, and that
    manifest was written by design's review pages in a browser: the documented
    Node step regenerates it with 73 assets instead of 193 and the audit then
    fails three rules. A manifest nothing can regenerate is a snapshot, and a
    check against a snapshot proves only that the snapshot was checked.

    So the emitter is asked to regenerate every file it ships and compare
    (`emit.js --check`, since rebuild-19), which is the claim in full: not
    that the asset count agrees, that all of `emit/` and every family manifest
    is what the engine beside it writes. When it is not, the ingest carries on
    from what the engine writes, because that is what gets drawn, and the audit
    is asked again of that.
    """
    problems = _audit(staged, "on the files as shipped")

    proc = _node(["node", "engine/emit.js", "--check"], staged)
    if proc.returncode != 0 or "clean" not in proc.stdout:
        said = (proc.stdout or proc.stderr).strip().splitlines()
        problems.append(
            f"`node engine/emit.js --check` says the shipped manifests are not "
            f"what the kit's own emitter writes: "
            f"{'; '.join(said[:6]) or f'exit {proc.returncode}, no output'}")
        shipped = _asset_count(staged)
        proc = _node(["node", "engine/emit.js"], staged)
        if proc.returncode != 0:
            problems.append(f"`node engine/emit.js` fails (exit {proc.returncode}): "
                            f"{(proc.stderr or proc.stdout).strip()[-300:]}")
            return problems
        fresh = _asset_count(staged)
        if fresh != shipped:
            problems.append(
                f"`node engine/emit.js` regenerates {fresh} assets where the kit "
                f"shipped {shipped}")
        problems += _audit(staged, "after `node engine/emit.js`")

    proc = _node(["node", "engine/export.js"], staged)
    if proc.returncode != 0:
        problems.append(f"`node engine/export.js` fails (exit {proc.returncode}): "
                        f"{(proc.stderr or proc.stdout).strip()[-300:]}")
    return problems


def _draw(staged: Path, out: Path, only: str = "") -> dict:
    """Run the driver: every plate blank, every hour, checked against the export."""
    if not DRIVER.exists():
        raise PlateError(f"missing engine driver {DRIVER}")
    cmd = ["node", str(DRIVER), "--kit", str(staged), "--out", str(out),
           "--emit", str(staged / "emit" / "plates.json"),
           "--against", str(staged / "out")]
    if only:
        cmd += ["--only", only]
    print(f"  $ node scripts/kit_engine.js{' --only ' + only if only else ''}")
    proc = _node(cmd, REPO)
    for line in proc.stderr.strip().splitlines():
        print(f"  {line}")
    if proc.returncode != 0:
        raise PlateError(f"the engine failed (exit {proc.returncode})")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise PlateError(f"the engine did not emit a registry: {exc}") from None


# The per-family manifest's table of plates, by the name it is under.
# delta-14 renamed it `assets` -> `plates`; both are read, because a
# manifest's top-level key is a fact about which pack drew it.
_MANIFEST_TABLES = ("plates", "assets")


def _plate_table(raw: dict) -> dict:
    for name in _MANIFEST_TABLES:
        table = raw.get(name)
        if isinstance(table, dict) and table:
            return table
    return {}


def _shipped_slot_tables(delivery: Path) -> dict:
    """Every plate's published slot table, from `kit/<family>/manifest.json`.

    ONE LOCATION, deliberately, and only under a FAMILY's name. The rebuild
    also ships `emit/manifest.json`, which a `*/manifest.json` glob matches:
    it names every plate once without its aspect and carries a slot COUNT, not
    slots, so reading it as a slot table reports every plate as undrawn.
    """
    out: dict = {}
    for family in sorted(EXPECTED_FAMILIES):
        m = delivery / family / "manifest.json"
        if m.exists():
            out.update(_plate_table(json.loads(m.read_text(encoding="utf-8"))))
    return out


def _shipped_keys(delivery: Path) -> set[str]:
    """The registry keys the shipped pack installs as, at the base hour.

    What the preflight compares the installed library against. A plate's
    table is keyed as the registry keys it, and so is the host's, whose
    figure is one drawing at every aspect. A room publishes ONE table for both
    aspects too, but the driver crops it once per aspect (a 9:16 room is its
    `portraitWindow`), so `room/desk-front` installs as `room/desk-front-16x9`
    and `room/desk-front-9x16`.
    """
    out: set[str] = set()
    for key in _shipped_slot_tables(delivery):
        if key.split("/", 1)[0] == "room":
            out.update(f"{key}-{aspect}" for aspect in ("16x9", "9x16"))
        else:
            out.add(key)
    return out


# Keys inside a typeRole that DESCRIBE the numbers rather than being them. The
# engine writes "…, was 40" where the delivery says "…, authored was 40", and a
# sentence that differs by two words is not a contract violation.
_ROLE_PROSE = frozenset({"budget", "note", "why"})


def _role_diffs(built: dict, shipped: dict) -> list[tuple[str, dict, dict]]:
    """Per-role type-spec disagreements, prose excluded.

    A typeRole carries the face, size, weight, colour role and tracking every
    word on screen is set in — and the role-level `maxChars` FLOOR, which is the
    budget every slot without one of its own is measured against. None of it
    was reconciled until a shared role object in the engine put 139 of 425
    floors out by up to 17x with every geometry field agreeing perfectly.
    """
    def bare(spec) -> dict:
        if not isinstance(spec, dict):
            return {}
        return {k: v for k, v in spec.items() if k not in _ROLE_PROSE}

    b_roles = built.get("typeRoles") or {}
    s_roles = shipped.get("typeRoles") or {}
    out = []
    for role in sorted(set(b_roles) | set(s_roles)):
        got, want = bare(b_roles.get(role)), bare(s_roles.get(role))
        if got != want:
            out.append((role, got, want))
    return out


# THE DRAWN KIT'S HOST AND ROOMS ARE RETIRED, NOT MISSING. The per-family
# manifests still carry delta-15's poses and angles, and the rebuild redraws
# both families flat from `kit-model.js`, which publishes no slot table for
# either. So neither family is reconciled against these files; the rooms'
# anchors are checked by the kit's own audit and the host by `checkHost`.
_FLAT_FAMILIES = frozenset({"host", "room"})

# Fields a drawn plate and its published entry must agree on. `playback` and
# `frameCount` are not among them: the published manifests are the drawn kit's,
# which boiled at 2fps, and §6 of the rebuild removed the boil.
_RECONCILED = ("canvas", "exportScale", "slots")


def _reconcile(built: dict, shipped: dict) -> list[str]:
    """The engine drew it; the delivery said what it would be. They must agree.

    This is the check that makes "the engine is the source, the PNGs are a
    cache" safe to act on. If a re-run of the engine produced different slot
    geometry from the tables the artwork was signed off against, every
    downstream coordinate is wrong and no rendered frame would look obviously
    broken — the figures would just sit somewhere else.
    """
    problems: list[str] = []
    base = {k: e for k, e in built.items()
            if e.get("hour") == BASE_HOUR and e.get("family") not in _FLAT_FAMILIES}
    unpublished = sorted(k for k in base if k not in shipped)
    if unpublished:
        problems.append(
            f"{len(unpublished)} plate(s) have no published slot table, so "
            f"nothing says where their slots were signed off: "
            f"{', '.join(unpublished[:4])}{' …' if len(unpublished) > 4 else ''}")
    drawn_families = {e.get("family") for e in base.values()}
    for key in sorted(shipped):
        family = key.split("/", 1)[0]
        if family in _FLAT_FAMILIES or family not in drawn_families:
            continue
        if key not in base:
            problems.append(f"{key}: the delivery declares it, the engine did not draw it")
    for key in sorted(set(base) & set(shipped)):
        b, s = base[key], shipped[key]
        for field in _RECONCILED:
            if b.get(field) != s.get(field):
                problems.append(
                    f"{key}: {field} disagrees with the shipped manifest "
                    f"(engine {b.get(field)!r} vs delivery {s.get(field)!r})")
        for role, got, want in _role_diffs(b, s):
            problems.append(
                f"{key}: typeRoles[{role!r}] disagrees with the shipped "
                f"manifest (engine {got!r} vs delivery {want!r})")

    # EVERY HOUR IS THE SAME PLATE. Dusk is a second colour table read through
    # one shape list, which is the kit's own twin rule; a dusk plate whose
    # slots moved would put every figure somewhere else after sunset.
    for key, e in sorted(built.items()):
        twin = built.get(e.get("atBaseHour", key))
        if e.get("hour") == BASE_HOUR or twin is None:
            continue
        if e.get("slots") != twin.get("slots") or e.get("canvas") != twin.get("canvas"):
            problems.append(f"{key}: its slots are not {e['atBaseHour']}'s, and "
                            f"every hour is meant to be one shape list")
        elif e.get("keys") != twin.get("keys"):
            problems.append(f"{key}: its legend keys {e.get('keys')!r} are not "
                            f"{e['atBaseHour']}'s {twin.get('keys')!r}, so a series would "
                            f"change colour at dusk")
    return problems


_ASPECT = re.compile(r"^(.*)-(16x9|9x16)$")


def _stem(key: str) -> str:
    m = _ASPECT.match(key)
    return m.group(1) if m else key


def _template_vocabulary() -> tuple[set[str], set[str]]:
    """The formats and beats our shot templates actually define."""
    formats: set[str] = set()
    beats: set[str] = set()
    for path in sorted((REPO / "templates" / "shots").glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        formats.add(str(raw.get("format") or path.stem))
        beats |= {str(s.get("id")) for s in raw.get("shots") or [] if s.get("id")}
    return formats, beats


def _plate_notes(delivery: Path, built: dict) -> tuple[dict, list[str], list[str]]:
    """Design's note on every plate, filed under the registry key it names.

    WHAT A PLATE IS FOR IS DESIGN'S WORD, AND IT ARRIVES WITH THE PLATE. Since
    rebuild-12 every plate in `roles.fragment.json` carries a purpose, a
    caution, the chapter types it serves, and — for the sector rounds — the one
    GICS sector its structure presumes. Retyping that into our own curation is
    how the writer came to see a bare name and a list of slots: 0 of 95 plates
    had a purpose before design wrote them, and a copy is stale the drop after.

    THE FRAGMENT IS READ, NOT TRUSTED. Its keys are checked against what was
    drawn and its values against the vocabulary they claim to be in:

      a key with an aspect suffix the plate does not have (the marks, the host
      strips, the hook cards) is filed under the plate's own key — the entry is
      right, the key is spelled wrong, and design has been told;

      a key WITHOUT the aspect a plate is drawn at (rebuild-39 files round five
      and the Christmas rooms under the bare stem, `charts/valuation-history`)
      is filed under every aspect it is drawn at. Read as a miss, it dropped 86
      of the drop's 98 new notes and left their plates on no menu at all;

      a key naming nothing this kit ships is dropped and reported, not merged:
      rebuild-19's names four assets the rebuild removed;

      a chapter type outside the sixteen, a sector outside GICS, a format or a
      beat our templates do not define is dropped and reported. A value that
      resolves to nothing is a promise no shot can keep.

    Returns (notes, problems, remarks). A missing fragment is a problem: every
    chapter's menu is built from it. The rest are remarks, printed and not
    fatal, because each is a drop being tidied rather than a drop being wrong.
    """
    path = delivery / "roles.fragment.json"
    if not path.exists():
        return {}, [f"{path.name} is missing: nothing says what any plate is "
                    f"for or which chapter types may use it, so every "
                    f"chapter's menu would be empty"], []
    raw = json.loads(path.read_text(encoding="utf-8"))
    drawn = {e.get("atBaseHour") or k for k, e in built.items()}
    formats, beats = _template_vocabulary()

    notes: dict[str, dict] = {}
    respelled, stale, doubled, spread = [], [], [], []
    dropped: Counter = Counter()

    def names(field: str, v: dict, allowed) -> list[str]:
        got = v.get(field) or []
        if not isinstance(got, list):
            dropped[(field, str(got)[:40])] += 1
            return []
        keep = []
        for x in got:
            if str(x) in allowed:
                keep.append(str(x))
            else:
                dropped[(field, str(x))] += 1
        return keep

    for key, v in raw.items():
        if key.startswith("_") or not isinstance(v, dict):
            continue
        targets = [key]
        if key not in drawn:
            twins = [f"{key}-{aspect}" for aspect in ("16x9", "9x16")
                     if f"{key}-{aspect}" in drawn]
            if _stem(key) != key and _stem(key) in drawn:
                targets = [_stem(key)]
                respelled.append(key)
            elif _stem(key) == key and twins:
                targets = twins
                spread.append(key)
            else:
                stale.append(key)
                continue
        targets = [t for t in targets if t not in notes]
        if not targets:
            doubled.append(key)
            continue
        note = {
            "purpose": str(v.get("purpose") or "").strip(),
            "caution": str(v.get("caution") or "").strip(),
            "chapterTypes": names("chapter_types", v, CHAPTER_TYPES),
            "sectors": names("sectors", v, GICS_SECTORS),
            "formats": names("formats", v, formats),
            "beats": names("beats", v, beats),
        }
        if v.get("round"):
            note["round"] = str(v["round"])
        for target in targets:
            notes[target] = {k: val for k, val in note.items() if val}

    remarks = []
    if respelled:
        remarks.append(
            f"roles.fragment.json: {len(respelled)} entries add an aspect to a "
            f"plate that has none (e.g. {', '.join(respelled[:3])}); filed under "
            f"the plate's own key")
    if spread:
        remarks.append(
            f"roles.fragment.json: {len(spread)} entries name a plate without "
            f"the aspect it is drawn at (e.g. {', '.join(spread[:3])}); filed "
            f"under every aspect it has")
    if doubled:
        remarks.append(
            f"roles.fragment.json: {len(doubled)} entries repeat a plate another "
            f"entry already covers (e.g. {', '.join(doubled[:3])}); the first "
            f"one stands")
    if stale:
        remarks.append(
            f"roles.fragment.json: {len(stale)} entries name assets this kit "
            f"does not ship, dropped: {', '.join(stale)}")
    for (field, value), n in sorted(dropped.items()):
        remarks.append(
            f"roles.fragment.json: {n} entries give {field} {value!r}, which "
            f"resolves to nothing here; dropped")
    return notes, [], remarks


def _motion(delivery: Path, built: dict) -> tuple[dict, list[str]]:
    """The kit's moves and where each lands, off `emit/motion.json`.

    MOVES ARE DATA, PLAYED BY THE RENDERER OVER A PLATE'S PUBLISHED SLOTS
    (rebuild-35 on): thirteen of them, each with its frame count, whether it
    plays once or loops, and its ease, and for every plate a slot and box per
    move or null where the plate has nothing for it to act on. The anchors are
    design's reading of the plate's own slots, so they are carried as given
    and nothing here places a move by eye.

    READ, NOT TRUSTED, like the fragment: an anchor set for a plate this kit
    did not draw is dropped and reported, and one naming a slot the plate does
    not publish keeps its box — the move acts on the box — and is reported.
    rebuild-39 names `plot-area` for the line-draw and bars-grow of 105 plates
    whose plot is a container slot under another name.

    Returns (motion, remarks). A kit that ships no motion is a kit whose plates
    do not move, which is a remark rather than a failure.
    """
    path = delivery / "emit" / "motion.json"
    if not path.exists():
        return {}, [f"the kit ships no emit/{path.name}, so no plate has a move"]
    raw = json.loads(path.read_text(encoding="utf-8"))
    moves = {}
    for m in raw.get("moves") or ():
        if isinstance(m, dict) and m.get("id"):
            moves[str(m["id"])] = {k: v for k, v in m.items() if k != "id"}
    drawn = {e.get("atBaseHour") or k: e for k, e in built.items()}
    anchors: dict = {}
    stale: list[str] = []
    misnamed: Counter = Counter()
    for key, per_move in ((raw.get("anchors") or {}).get("plates") or {}).items():
        if not isinstance(per_move, dict):
            continue
        plate = drawn.get(key)
        if plate is None:
            stale.append(key)
            continue
        kept = {}
        for move, at in per_move.items():
            if not isinstance(at, dict) or not isinstance(at.get("box"), dict):
                continue
            slot = at.get("slot")
            if slot is not None and slot not in (plate.get("slots") or {}):
                misnamed[(move, str(slot))] += 1
            kept[str(move)] = {"slot": slot, "box": dict(at["box"])}
        if kept:
            anchors[key] = kept
    remarks = []
    if stale:
        remarks.append(
            f"emit/motion.json: anchors for {len(stale)} plates this kit does "
            f"not draw, dropped: {', '.join(sorted(stale)[:4])}")
    for (move, slot), n in sorted(misnamed.items()):
        remarks.append(
            f"emit/motion.json: {move} names slot {slot!r} on {n} plates that "
            f"publish none by that name; its box stands")
    return {"fps": int(raw.get("fps") or 0), "moves": moves, "anchors": anchors}, remarks


def _held_back(roles: dict) -> tuple[dict, dict]:
    """(plates, rooms) roles.json holds back, stem -> the reason."""
    block = roles.get("heldBack") or {}

    def own(name: str) -> dict:
        return {str(k): str(v) for k, v in (block.get(name) or {}).items()
                if not str(k).startswith("_")}
    return own("plates"), own("rooms")


def _chapter_types(roles: dict, notes: dict, held: dict) -> dict:
    """Each chapter type's purpose and plates: ours, plus design's filing.

    The purposes are ours and are what the director reads. Which plates a type
    may use is the union of what roles.json adds and every plate the fragment
    files under that type, minus anything held back — a plate held back is off
    every menu, whoever put it there.
    """
    block = roles.get("chapterTypes") or {}
    out: dict = {k: v for k, v in block.items() if k.startswith("_")}
    for ctype in CHAPTER_TYPES:
        own = block.get(ctype) or {}
        plates = list(own.get("plates") or ())
        plates += sorted(k for k, n in notes.items() if ctype in n.get("chapterTypes", ()))
        plates = [p for p in dict.fromkeys(plates) if _stem(p) not in held]
        entry = {k: v for k, v in own.items() if k != "plates"}
        entry["plates"] = plates
        out[ctype] = entry
    return out


def _install(built: dict, delivery: Path, staged_out: Path, dest: Path,
             notes: dict | None = None, motion: dict | None = None) -> dict:
    """Replace the installed kit with what was just drawn.

    REPLACES, never merges. Merging is what left stale assets resolvable last
    time: a family that shrank kept its old members, and they stayed addressable
    from a script long after the artwork stopped meaning anything.
    """
    roles_path = delivery / "roles.json"
    roles = json.loads(roles_path.read_text(encoding="utf-8")) if roles_path.exists() else {}
    if not roles:
        raise PlateError(
            f"{roles_path} is missing or empty. It is the curation that wires "
            f"plates into shot roles and chapter types, and a kit without it "
            f"installs artwork nothing can reach.")

    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for fam in sorted({e["family"] for e in built["assets"].values()}):
        shutil.copytree(staged_out / fam, dest / fam)
        print(f"  {fam}/  {len(list((dest / fam).iterdir()))} files")

    def own(block: str) -> dict:
        return {k: v for k, v in (roles.get(block) or {}).items() if not k.startswith("_")}

    notes = notes or {}
    held_plates, held_rooms = _held_back(roles)
    registry = {k: v for k, v in built.items()
                if k not in ("problems", "checkedAgainstExport")}
    registry["hostRoles"] = own("hostRoles")
    registry["hostPoses"] = roles.get("hostPoses", {})
    registry["roomRoles"] = own("roomRoles")
    # THE HOUR, ONE PER EPISODE, AND NOW FOR EVERY PLATE. The suffixes are the
    # kit's (every plate is drawn at every hour the tokens declare); which of
    # them an episode may be shot at is curation, so it comes from roles.json.
    registry["hours"] = {
        "suffixes": built.get("hourSuffixes") or {BASE_HOUR: ""},
        "episodes": list((roles.get("hours") or {}).get("episodes") or [BASE_HOUR]),
    }
    registry["chapterTypes"] = _chapter_types(roles, notes, held_plates)
    # A purpose roles.json writes is ours and wins; every other plate's is
    # design's, off the fragment.
    registry["purposes"] = {**{k: n["purpose"] for k, n in notes.items()
                               if n.get("purpose")}, **own("purposes")}
    registry["plateNotes"] = notes
    registry["heldBack"] = {"plates": held_plates, "rooms": held_rooms}
    registry["wardrobe"] = own("wardrobe")
    registry["motion"] = motion or {}
    (dest / REGISTRY_NAME).write_text(
        json.dumps(registry, indent=1, sort_keys=False) + "\n", encoding="utf-8")
    print(f"  {REGISTRY_NAME}")
    return registry


# The role a beat falls back to when the room it is in declares `hostAnchor:
# false`. Named once; `pipeline/compose.py` names the same one.
_ROLE_WHERE_NOBODY_STANDS = "to-camera"


def _host_contract(reg) -> list[str]:
    """What the render path requires of a plate a host ROLE serves.

    ARTWORK AND CURATION ARRIVE TOGETHER AND NOTHING RECONCILED THEM. A drop
    ships plates and a `roles.json` that wires them into shot roles, and every
    check on either half passed while the two disagreed — because they are
    checked separately. delta-15 shipped `host/empty-chair` into `beat` with no
    `alpha`, and `host/sitting-at-desk`, a cut-out with a floor line, into the
    role a beat falls back to when its room has no floor. Both are one line of
    data each and neither is visible in a diff of the artwork, so they are
    asked here, where the two halves first exist together.
    """
    problems: list[str] = []
    for role in sorted(reg.host_roles):
        for key in reg.host_roles.get(role, ()):
            pose = reg.get(key)
            if pose is None:
                problems.append(
                    f"roles.json wires {key!r} into the {role!r} host role and "
                    f"the kit ships no such plate")
                continue
            # A framing is a camera distance and composites against the frame,
            # so it is exempt from the cut-out rule by construction. What it
            # may NOT be is a framing with nothing to play between words: a
            # close-up held on its still is the closed mouth at close-up
            # scale, a dash (ANSWERS.md §4, finding 2), so the player cuts
            # its silences to the idle strip and needs one to cut to.
            if not pose.floor_line_y:
                if reg.host_strip(key, "idle") is None:
                    problems.append(
                        f"{key}: the {role!r} host role serves this framing "
                        f"and the kit ships no `{key}-idle` — a close framing "
                        f"may never hold its still, so its silences have "
                        f"nothing to play")
                continue
            if not pose.alpha:
                problems.append(
                    f"{key}: the {role!r} host role serves it and it does not "
                    f"declare `alpha` — a role's pose is composited onto a "
                    f"room, so an opaque plate paints over the room")

    served = reg.host_roles.get(_ROLE_WHERE_NOBODY_STANDS, ())
    if served and not any((p := reg.get(k)) is not None and not p.floor_line_y
                          for k in served):
        problems.append(
            f"the {_ROLE_WHERE_NOBODY_STANDS!r} role serves no framing — it is "
            f"what a beat falls back to when its room declares `hostAnchor: "
            f"false`, and every member of it has a floor line, so there is "
            f"nothing to put in a room with no floor")

    # A ROOM HE STANDS IN MUST NOT PAINT OVER HIS HEAD. rebuild-19 shipped four
    # rooms that list a wall item after the desk, so the split the kit publishes
    # puts a frame, a sheet or a shelf in FRONT of him — and every check on the
    # rooms passed, because they were checked with nobody in them. The engine
    # driver stands him in each anchored room by the contract and measures it.
    held = set((getattr(reg, "held_back", {}) or {}).get("rooms", {}))
    for role, stems in sorted(reg.room_roles.items()):
        for stem in stems:
            if stem in held:
                problems.append(
                    f"roles.json puts {stem} in the {role!r} room role and also "
                    f"holds it back; it is one or the other")
                continue
            for aspect in ("16x9", "9x16"):
                room = reg.get(f"{stem}-{aspect}")
                if room is None or room.refuses_host or room.head_covered is None:
                    continue
                if room.head_covered > _HEAD_COVER_LIMIT:
                    problems.append(
                        f"{room.key}: the {role!r} room role stands him here "
                        f"and the room's front layer covers "
                        f"{room.head_covered:.0%} of his head")

    # A CHAPTER OPENS IN A ROOM WITH SOMEWHERE TO PUT ITS TITLE. The opener is
    # the room with the chapter's title set in its `title` slot; a member with
    # no such slot is a chapter whose title silently never reaches the screen,
    # which is what every chapter was until rebuild-21 published one.
    for stem in reg.room_roles.get(_OPENER_ROLE, ()):
        for aspect in ("16x9", "9x16"):
            room = reg.get(f"{stem}-{aspect}")
            if room is not None and room.slot("title") is None:
                problems.append(
                    f"{room.key}: the {_OPENER_ROLE!r} room role opens chapters "
                    f"here and the room publishes no `title` slot, so the "
                    f"chapter's title would have nowhere to land")
    return problems


# The room role a chapter opens in. `pipeline/render_long.py` names the same one.
_OPENER_ROLE = "opener"


# How much of his head a room's front layer may cover before the room is
# refused for a role. Not zero: a lamp's rim clipping an ear is a room, and the
# four rooms rebuild-19 got wrong cover between 67% and 97% of it.
_HEAD_COVER_LIMIT = 0.05


def _verify(repo: Path) -> int:
    """The exhaustive pass: every asset, every frame, every layer, every file."""
    dest = repo / "assets" / PLATES_DIRNAME
    reg = load_registry(dest)
    # EVERY HOUR'S ART, not the library. `reg.assets` is the base hour — the
    # keys a template names — and a verify over it leaves every dusk file on
    # disk unnamed, which this pass then reports as unregistered: 958 of them
    # the first time every plate had an hour.
    everything = reg.all_plates()

    print(f"registry: {len(reg.assets)} plates at "
          f"{len(reg.hour_suffixes) or 1} hour(s), {len(everything)} drawn, "
          f"{sum(a.frame_count for a in everything.values())} frames, "
          f"hours {', '.join(reg.hour_suffixes) or '(none)'}")

    problems: list[str] = []
    named: set[Path] = set()

    def expect(key: str, p: Path, size: tuple[int, int] | None, what: str) -> None:
        named.add(p.resolve())
        if not p.exists():
            problems.append(f"{key}: missing {what} {p.relative_to(repo)}")
        elif size is not None and _png_size(p) != size:
            got = _png_size(p)
            problems.append(f"{key}: {p.name} is {got[0]}x{got[1]}, the registry "
                            f"promises {size[0]}x{size[1]}")

    for key, a in sorted(everything.items()):
        d = dest / a.family
        delivered = tuple(a.delivered)
        for fr in a.frames:
            expect(key, d / fr.png, delivered, "frame")
            if fr.svg:
                expect(key, d / fr.svg, None, "SVG source")
        base = d / a.files_png
        expect(key, base, delivered, "base file")
        if a.files_svg:
            named.add((d / a.files_svg).resolve())
        # A ROOM'S LAYERS ARE THE ROOM, split where he stands. Both have to be
        # there at the delivered size, or he is composited in front of a desk
        # he is meant to be behind.
        for layer in a.layers.values():
            expect(key, d / layer, delivered, "layer")
        if a.base_is_frame and base.exists():
            # f01 BYTE-IDENTICAL TO BASE. Not "the same drawing" — the same
            # bytes. A base that is its own render pops on the first frame of
            # the loop.
            first = d / a.frames[0].png
            if first.exists() and _sha(base) != _sha(first):
                problems.append(
                    f"{key}: the base file is not byte-identical to "
                    f"{a.frames[0].tag} — entering the loop will pop")

        # Slots are checked against the canvas but NOT clipped to it: an
        # annotation's caption lands beside the mark, outside its own plate.
        for name, s in a.slots.items():
            # A CONTROL SLOT HAS NO AREA BY DESIGN: an integer naming a row, a
            # column or a receipt line for the renderer to ring. A zero-area
            # slot that does not declare itself one is a box nothing can be
            # drawn into, and stays fatal.
            if s.control:
                continue
            if s.w <= 0 or s.h <= 0:
                problems.append(f"{key}: slot {name!r} has no area")

    for fam in sorted(EXPECTED_FAMILIES):
        fd = dest / fam
        if not fd.is_dir():
            problems.append(f"family {fam}/ is missing from the installed kit")
            continue
        # AN UNREGISTERED PNG DOES NOT EXIST — and is a failure, not a note. It
        # is how a contact sheet became an addressable asset once.
        for p in sorted(fd.iterdir()):
            if p.is_file() and p.resolve() not in named:
                problems.append(f"unregistered file on disk: {p.relative_to(repo)}")
    for fd in sorted(dest.iterdir()):
        if fd.is_dir() and fd.name not in EXPECTED_FAMILIES:
            problems.append(f"family {fd.name}/ is on disk and not expected")

    problems.extend(reg.verify())
    problems.extend(_host_contract(reg))

    fams = Counter(a.family for a in reg.assets.values())
    hours = Counter(a.hour or BASE_HOUR for a in everything.values())
    aspects = Counter(a.aspect for a in reg.assets.values())
    print(f"families:  {dict(sorted(fams.items()))}")
    print(f"hours:     {dict(sorted(hours.items()))}")
    print(f"aspects:   {dict(sorted(aspects.items()))}")
    print(f"scale:     {sorted({a.export_scale for a in everything.values()})} "
          f"<- read per plate, never assumed")
    print(f"slots:     {sum(len(a.slots) for a in reg.assets.values())} across "
          f"{len(reg.assets)} plates")
    print(f"palettes:  {', '.join(sorted(reg.palettes))}, "
          f"{len(reg.palette)} roles each")
    print(f"chapters:  {len(CHAPTER_TYPES)} types, "
          f"{sum(len(reg.plates_for_chapter(c)) for c in CHAPTER_TYPES)} "
          f"type/plate pairings")

    if problems:
        print(f"\nFAILED — {len(problems)} problems:")
        for p in problems[:40]:
            print(f"  {p}")
        if len(problems) > 40:
            print(f"  ... and {len(problems) - 40} more")
        print("\nDO NOT COMMIT.")
        return 1

    print(f"\nOK — {len(everything)} plates verified at every hour, every frame and layer "
          f"present at its delivered size, nothing on disk the registry does "
          f"not name.")
    return 0


def _sha(p: Path) -> bytes:
    return hashlib.sha256(p.read_bytes()).digest()


def _png_size(p: Path) -> tuple[int, int]:
    """Read a PNG's dimensions off the IHDR, without decoding the image."""
    with p.open("rb") as fh:
        head = fh.read(24)
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n":
        raise PlateError(f"{p} is not a PNG")
    return (int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big"))


def _report(title: str, problems: list[str]) -> None:
    print(f"\nFAILED — {title} ({len(problems)}):")
    for p in problems:
        print(f"  {p}")
    print("\nDO NOT COMMIT.")


def build(delivery: Path, only: str = "") -> int:
    """Prove the delivery, draw it, and install it — or say everything wrong."""
    missing = [m for m in REBUILD_MARKERS if not (delivery / m).exists()]
    if missing:
        raise PlateError(
            f"{delivery} is not a rebuild delivery (no {', '.join(missing)}). "
            f"This ingest draws the rebuild's flat model and its hours; the "
            f"drawn kit before it is retired, not supported alongside.")
    print(f"building from {delivery}")
    try:
        staged = _stage(delivery)
        problems = _kit_proves_itself(staged)
        print(f"  the kit's own checks: {len(problems)} problem(s)")
        drawn = STAGE / "plates"
        built = _draw(staged, drawn, only=only)
        problems += built.get("problems") or []
        shipped = _shipped_slot_tables(delivery)
        if only:
            shipped = {k: v for k, v in shipped.items() if k.split("/", 1)[0] == only}
        problems += _reconcile(built.get("assets") or {}, shipped)
        notes, note_problems, remarks = _plate_notes(delivery, built.get("assets") or {})
        motion, motion_remarks = _motion(delivery, built.get("assets") or {})
        remarks += motion_remarks
        if not only:
            problems += note_problems
        if problems:
            _report("the delivery cannot be installed", problems)
            return 1
        if only:
            print(f"\n  {only}: {len(built['assets'])} plates drawn and checked.")
            print("NOT INSTALLED — `--only` checks one family; a partial kit is "
                  "not a kit.")
            return 0
        print(f"  reconciled: {len(built['assets'])} plates; design's notes on "
              f"{len(notes)} of them")
        for remark in remarks:
            print(f"  note: {remark}")
        _install(built, delivery, drawn, REPO / "assets" / PLATES_DIRNAME,
                 notes=notes, motion=motion)
    finally:
        if STAGE.exists():
            shutil.rmtree(STAGE)
    print()
    return _verify(REPO)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("delivery", nargs="?", type=Path,
                    help="the kit delivery: engine/, design-tokens.json, roles.json")
    ap.add_argument("--check", action="store_true",
                    help="verify the installed kit without rebuilding it")
    ap.add_argument("--only", metavar="FAMILY",
                    help="draw ONE family and check it against the kit's export "
                         "and its slot tables. Installs nothing — a partial kit "
                         "is not a kit.")
    args = ap.parse_args()
    if args.only and args.only not in EXPECTED_FAMILIES:
        ap.error(f"unknown family {args.only!r} — the fourteen are "
                 f"{', '.join(sorted(EXPECTED_FAMILIES))}")
    if not args.check and args.delivery is None:
        ap.error("give a delivery directory, or --check")

    try:
        if args.delivery is not None:
            return build(args.delivery.resolve(), only=args.only or "")
        return _verify(REPO)
    except PlateError as exc:
        print(f"FAILED — {exc}", file=sys.stderr)
        print("\nDO NOT COMMIT.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
