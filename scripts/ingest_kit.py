#!/usr/bin/env python3
"""Materialise the design kit: run the engine, write the artwork, verify it.

    python scripts/ingest_kit.py kit            build from the delivery in kit/
    python scripts/ingest_kit.py kit --outfit cardigan
    python scripts/ingest_kit.py --check        verify what is already on disk

THE KIT IS CODE, NOT PICTURES. `kit/engine/build.js` declares every asset as an
author plus a seed plus arguments, and `BUILD.draw()` reproduces it byte for
byte. Outfits, boil frames and aspects are arguments — which is why the delivery
is 1.4 MB of JS rather than 860 MB of PNGs, and why five outfits are not five
families somebody has to re-export.

So ingest RUNS the engine and writes real files out, and the render path then
loads plain PNGs exactly as it always did. Node is a build-time dependency and
must never appear in the render path: a bug in `plates.js` has to break a build,
not a published video. Nothing under `pipeline/` imports this module or shells
out to node — `tests/test_ingest.py` holds that line.

Nothing here trusts anything. The engine's own manifest is checked against the
manifest the delivery shipped, every frame it names is opened and measured, and
a PNG on disk that the registry does not name is a failure rather than dead
weight nobody notices. Any single failure exits non-zero and says DO NOT COMMIT,
because a missing asset must never reach a render and degrade quietly into an
empty box.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.plates import (  # noqa: E402
    CHAPTER_TYPES, PLATES_DIRNAME, REGISTRY_NAME, PlateError, load_registry,
)

REPO = Path(__file__).resolve().parents[1]
DRIVER = REPO / "scripts" / "kit_engine.js"

# The families the delivery ships. A family on disk that is not here, or one
# here with nothing on disk, is a delivery that changed shape without anyone
# saying so — which is the moment to look, not to carry on.
EXPECTED_FAMILIES = frozenset({
    "annotations", "cards", "charts", "cycles", "figures", "frames", "host",
    "overlays", "paper", "peers", "room", "shorts", "structure", "tables",
})


def _node(delivery: Path, out: Path, outfit: str) -> dict:
    """Run the engine. Its stdout is the registry; stderr is for the operator."""
    if not DRIVER.exists():
        raise PlateError(f"missing engine driver {DRIVER}")
    cmd = ["node", str(DRIVER), "--kit", str(delivery), "--out", str(out),
           "--outfit", outfit]
    print(f"  $ {' '.join(cmd)}")
    try:
        proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
    except FileNotFoundError:
        raise PlateError(
            "node is not on PATH. The kit is JS and is rendered at INGEST — "
            "install Node 18+ and run `npm ci` for the rasteriser. The render "
            "path needs neither."
        ) from None
    if proc.stderr.strip():
        for line in proc.stderr.strip().splitlines():
            print(f"  {line}")
    if proc.returncode != 0:
        raise PlateError(f"the engine failed (exit {proc.returncode})")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise PlateError(f"the engine did not emit a registry: {exc}") from None


def _shipped_manifests(delivery: Path) -> dict:
    """Every asset the delivery's own manifests declare, merged."""
    out: dict = {}
    for m in sorted(delivery.glob("*/manifest.json")):
        raw = json.loads(m.read_text(encoding="utf-8"))
        for key, entry in raw.get("assets", {}).items():
            out[key] = entry
    return out


def _reconcile(built: dict, shipped: dict) -> list[str]:
    """The engine drew it; the delivery said what it would be. They must agree.

    This is the check that makes "the engine is the source, the PNGs are a
    cache" safe to act on. If a re-run of the engine produced different slot
    geometry from the manifests the artwork was signed off against, every
    downstream coordinate is wrong and no rendered frame would look obviously
    broken — the figures would just sit somewhere else.
    """
    problems: list[str] = []
    for key in sorted(set(shipped) - set(built)):
        problems.append(f"{key}: the delivery declares it, the engine did not draw it")
    for key in sorted(set(built) - set(shipped)):
        problems.append(f"{key}: the engine drew it, no manifest declares it")
    for key in sorted(set(built) & set(shipped)):
        b, s = built[key], shipped[key]
        for field in ("canvas", "exportScale", "playback", "frameCount", "slots"):
            if b.get(field) != s.get(field):
                problems.append(
                    f"{key}: {field} disagrees with the shipped manifest "
                    f"(engine {b.get(field)!r} vs delivery {s.get(field)!r})")
    return problems


def _install(built: dict, delivery: Path, staged: Path, dest: Path,
             outfit: str) -> dict:
    """Replace the installed kit with what was just drawn.

    REPLACES, never merges. Merging is what left stale assets resolvable last
    time: a family that shrank kept its old members, and they stayed addressable
    from a script long after the artwork stopped meaning anything.
    """
    roles_path = delivery / "roles.json"
    roles = json.loads(roles_path.read_text(encoding="utf-8")) if roles_path.exists() else {}
    if not roles:
        print("  (the delivery ships no roles.json — chapter types and host "
              "roles will be empty)")

    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for fam in sorted({e["family"] for e in built["assets"].values()}):
        shutil.copytree(staged / fam, dest / fam)
        print(f"  {fam}/  {len(list((dest / fam).iterdir()))} files")

    registry = dict(built)
    registry["outfit"] = outfit
    registry["hostRoles"] = {k: v for k, v in roles.get("hostRoles", {}).items()
                             if not k.startswith("_")}
    registry["hostPoses"] = roles.get("hostPoses", {})
    registry["roomRoles"] = {k: v for k, v in roles.get("roomRoles", {}).items()
                             if not k.startswith("_")}
    registry["chapterTypes"] = roles.get("chapterTypes", {})
    registry["purposes"] = {k: v for k, v in roles.get("purposes", {}).items()
                            if not k.startswith("_")}
    # ONE OUTFIT PER EPISODE. `--outfit` picks which of the five the engine
    # renders into the figure keys; the robe is a different KEY rather than a
    # recolour, so the pipeline needs the block itself to know that
    # `host/medium-robe` is the same shot in other clothes.
    registry["wardrobe"] = {k: v for k, v in roles.get("wardrobe", {}).items()
                            if not k.startswith("_")}
    (dest / REGISTRY_NAME).write_text(
        json.dumps(registry, indent=1, sort_keys=False) + "\n", encoding="utf-8")
    print(f"  {REGISTRY_NAME}")
    return registry


def _verify(repo: Path) -> int:
    """The exhaustive pass: every asset, every frame, every slot, every file."""
    dest = repo / "assets" / PLATES_DIRNAME
    reg = load_registry(dest)

    print(f"registry: {len(reg.assets)} plates, "
          f"{sum(a.frame_count for a in reg.assets.values())} frames, "
          f"outfit {reg.outfit!r}")

    problems: list[str] = []
    named: set[Path] = set()

    for key, a in sorted(reg.assets.items()):
        d = dest / a.family
        for fr in a.frames:
            p = d / fr.png
            named.add(p.resolve())
            if not p.exists():
                problems.append(f"{key}: missing frame {p.relative_to(repo)}")
                continue
            size = _png_size(p)
            if size != tuple(a.delivered):
                problems.append(
                    f"{key}: {fr.png} is {size[0]}x{size[1]}, the registry "
                    f"promises {a.delivered[0]}x{a.delivered[1]}")
            if fr.svg:
                sp = d / fr.svg
                named.add(sp.resolve())
                if not sp.exists():
                    problems.append(f"{key}: missing SVG source {sp.relative_to(repo)}")

        base = d / a.files_png
        named.add(base.resolve())
        if a.files_svg:
            named.add((d / a.files_svg).resolve())
        if not base.exists():
            problems.append(f"{key}: missing base file {base.relative_to(repo)}")
        elif a.base_is_frame:
            # f01 BYTE-IDENTICAL TO BASE. Not "the same drawing" — the same
            # bytes. A base that is its own render pops on the first frame of
            # the loop, and a re-render with the same arguments is exactly the
            # kind of thing that looks right and is not.
            first = d / a.frames[0].png
            if first.exists() and _sha(base) != _sha(first):
                problems.append(
                    f"{key}: the base file is not byte-identical to "
                    f"{a.frames[0].tag} — entering the loop will pop")

        # Slots are checked against the canvas but NOT clipped to it, and a
        # slot outside it is not an error. Twelve annotation slots sit outside
        # their own plate on purpose — `bracket-rows/area` is at x = -880 —
        # because a mark is composited onto something else and its caption
        # lands beside the mark, not inside it. A renderer that clips would
        # silently drop every annotation caption.
        for name, s in a.slots.items():
            if s.w <= 0 or s.h <= 0:
                problems.append(f"{key}: slot {name!r} has no area")

    orphans = []
    for fam in sorted(EXPECTED_FAMILIES):
        fd = dest / fam
        if not fd.is_dir():
            problems.append(f"family {fam}/ is missing from the installed kit")
            continue
        for p in sorted(fd.iterdir()):
            if p.is_file() and p.resolve() not in named:
                orphans.append(p)
    for fd in sorted(dest.iterdir()):
        if fd.is_dir() and fd.name not in EXPECTED_FAMILIES:
            problems.append(f"family {fd.name}/ is on disk and not expected")

    # AN UNREGISTERED PNG DOES NOT EXIST — and is a failure, not a note. It is
    # how a contact sheet became an addressable asset last time, and how a
    # drawing whose entry had moved stayed resolvable from a script.
    for p in orphans:
        problems.append(f"unregistered file on disk: {p.relative_to(repo)}")

    fams = Counter(a.family for a in reg.assets.values())
    playback = Counter(a.playback for a in reg.assets.values())
    aspects = Counter(a.aspect for a in reg.assets.values())
    print(f"families:  {dict(sorted(fams.items()))}")
    print(f"playback:  {dict(playback)}")
    print(f"aspects:   {dict(sorted(aspects.items()))}")
    print(f"scale:     {sorted({a.export_scale for a in reg.assets.values()})} "
          f"<- read per plate, never assumed")
    print(f"slots:     {sum(len(a.slots) for a in reg.assets.values())} across "
          f"{len(reg.assets)} plates")
    print(f"palette:   {len(reg.palette)} roles: "
          f"{', '.join(sorted(reg.palette))}")
    print(f"chapters:  {len(CHAPTER_TYPES)} types, "
          f"{sum(len(reg.plates_for_chapter(c)) for c in CHAPTER_TYPES)} "
          f"type/plate pairings")
    outside = sum(1 for a in reg.assets.values() for s in a.slots.values()
                  if s.x < 0 or s.y < 0 or s.x + s.w > a.canvas[0]
                  or s.y + s.h > a.canvas[1])
    print(f"slots outside their own canvas: {outside}  "
          f"<- deliberate; never clip a slot")

    if problems:
        print(f"\nFAILED — {len(problems)} problems:")
        for p in problems[:40]:
            print(f"  {p}")
        if len(problems) > 40:
            print(f"  ... and {len(problems) - 40} more")
        print("\nDO NOT COMMIT.")
        return 1

    print(f"\nOK — {len(reg.assets)} plates verified, every frame present at "
          f"its delivered size, every base byte-identical to its first frame, "
          f"nothing on disk the registry does not name.")
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


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("delivery", nargs="?", type=Path,
                    help="the kit delivery: engine/, per-family manifest.json, roles.json")
    ap.add_argument("--check", action="store_true",
                    help="verify the installed kit without rebuilding it")
    ap.add_argument("--outfit", default="shirt",
                    help="which wardrobe to materialise (one per episode; the "
                         "engine renders five and the pipeline uses one)")
    args = ap.parse_args()

    if not args.check and args.delivery is None:
        ap.error("give a delivery directory, or --check")

    try:
        if args.delivery is not None:
            delivery = args.delivery.resolve()
            if not (delivery / "engine").is_dir():
                raise PlateError(f"{delivery} has no engine/ directory")
            print(f"building from {delivery}, outfit {args.outfit!r}")
            staged = REPO / ".kit-build"
            if staged.exists():
                shutil.rmtree(staged)
            try:
                built = _node(delivery, staged, args.outfit)
                problems = _reconcile(built["assets"], _shipped_manifests(delivery))
                if problems:
                    print(f"\nFAILED — the engine and the delivery's manifests "
                          f"disagree ({len(problems)}):")
                    for p in problems[:20]:
                        print(f"  {p}")
                    print("\nDO NOT COMMIT.")
                    return 1
                print(f"  reconciled: {len(built['assets'])} plates match the "
                      f"manifests the artwork was signed off against")
                _install(built, delivery, staged,
                         REPO / "assets" / PLATES_DIRNAME, args.outfit)
            finally:
                if staged.exists():
                    shutil.rmtree(staged)
            print()
        return _verify(REPO)
    except PlateError as exc:
        print(f"FAILED — {exc}", file=sys.stderr)
        print("\nDO NOT COMMIT.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
