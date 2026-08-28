#!/usr/bin/env python3
"""Install a DENNIS kit delivery into the repo, or verify the installed one.

    python scripts/ingest_kit.py <delivery-dir>   install, verifying as it goes
    python scripts/ingest_kit.py --check          verify what is already here

A delivery is a directory containing `assets/manifest.json`, the per-register
PNG and SVG directories it names, and `engine/`. The ingest REPLACES the
register directories and the manifests; there is no merge mode, because
merging is what left stale assets resolvable last time.

Nothing here trusts the manifest. Every frame it names is opened and measured,
every slot is checked against its own canvas, and any single failure exits
non-zero and says DO NOT COMMIT. A missing asset must never reach a render and
degrade quietly into an empty box: this is where that is stopped.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.kit_manifest import (  # noqa: E402
    LIGHT_REGISTER, MANIFEST_NAME, REGISTERS, KitError, _parse_entries,
    _png_size, verify_entries,
)

REPO = Path(__file__).resolve().parents[1]
ALL_REGISTERS = (*REGISTERS, LIGHT_REGISTER)

# Names Windows cannot create, whatever the filesystem underneath says. A
# delivery is somebody else's export: `restyle/con/` arrived that way once and
# took eighteen frames down with it, silently, because the Linux tree still
# looked clean. 3,544 files is a lot of chances to do it again.
_WIN_RESERVED = {"con", "prn", "aux", "nul",
                 *(f"com{i}" for i in range(1, 10)),
                 *(f"lpt{i}" for i in range(1, 10))}
_WIN_ILLEGAL = set('<>:"|?*') | {chr(c) for c in range(32)}


def unportable(relpath: str) -> str | None:
    """Why Windows would refuse this path, or `None` if it would not."""
    for seg in str(relpath).replace("\\", "/").split("/"):
        if not seg:
            continue
        if seg.split(".")[0].lower() in _WIN_RESERVED:
            return f"{seg!r} is a reserved device name on Windows"
        bad = sorted(_WIN_ILLEGAL & set(seg))
        if bad:
            return f"{seg!r} contains {''.join(bad)!r}"
        if seg != seg.rstrip(" .") or seg != seg.lstrip(" "):
            return f"{seg!r} has a leading or trailing space or dot"
    return None


def _read_manifest(assets_dir: Path) -> dict:
    mpath = assets_dir / MANIFEST_NAME
    if not mpath.exists():
        raise KitError(f"no {MANIFEST_NAME} in {assets_dir}")
    return json.loads(mpath.read_text(encoding="utf-8"))


def _install(delivery: Path, repo: Path) -> None:
    src_assets = delivery / "assets"
    if not src_assets.is_dir():
        raise KitError(f"{delivery} has no assets/ directory")
    dst_assets = repo / "assets"
    dst_assets.mkdir(parents=True, exist_ok=True)

    for reg in ALL_REGISTERS:
        for sub in (reg, f"{reg}-svg"):
            src = src_assets / sub
            if not src.is_dir():
                continue
            dst = dst_assets / sub
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
            print(f"  {sub}/  {len(list(dst.iterdir()))} files")

    for m in sorted(src_assets.glob("manifest*.json")):
        shutil.copy2(m, dst_assets / m.name)
        print(f"  {m.name}")
    readme = src_assets / "README.md"
    if readme.exists():
        shutil.copy2(readme, dst_assets / "KIT_README.md")

    src_engine = delivery / "engine"
    if src_engine.is_dir():
        dst_engine = repo / "engine"
        dst_engine.mkdir(exist_ok=True)
        for js in sorted(src_engine.glob("*.js")):
            shutil.copy2(js, dst_engine / js.name)
            print(f"  engine/{js.name}")
        top_readme = delivery / "README.md"
        if top_readme.exists():
            shutil.copy2(top_readme, dst_engine / "KIT_DELIVERY.md")


def _verify(repo: Path) -> int:
    """The exhaustive pass: every register, every frame, every slot."""
    assets = repo / "assets"
    raw = _read_manifest(assets)
    entries = _parse_entries(raw, repo)

    print(f"manifest: {len(entries)} entries, "
          f"{sum(e.frames for e in entries)} frames")

    problems = verify_entries(entries, registers=None,
                              check_files=True, check_sizes=True)

    # The SVG source is the thing that allows a re-export at any resolution
    # later, so a delivery that dropped one is incomplete even though every
    # PNG is present and every render would succeed.
    for e in entries:
        for f in e.svg_files:
            p = repo / e.svg_dir / f
            if not p.exists():
                problems.append(f"{e.key}: missing SVG source {p}")

    # Anything on disk the manifest does not name. A PNG with no entry does
    # not exist as far as the renderer is concerned, and it is dead weight in
    # a repository that is already carrying 1,772 frames.
    named = {(repo / e.dir / f).resolve() for e in entries for f in e.files}
    named |= {(repo / e.svg_dir / f).resolve()
              for e in entries for f in e.svg_files}
    orphans = []
    for reg in ALL_REGISTERS:
        for sub in (reg, f"{reg}-svg"):
            d = assets / sub
            if not d.is_dir():
                continue
            for p in d.iterdir():
                if p.is_file() and p.resolve() not in named:
                    orphans.append(p)

    # Portability, on every path the manifest names.
    for e in entries:
        for f in e.files:
            why = unportable(f"{e.dir}{f}")
            if why:
                problems.append(f"{e.key}: {why}")
        for f in e.svg_files:
            why = unportable(f"{e.svg_dir}{f}")
            if why:
                problems.append(f"{e.key}: {why}")

    scales = Counter()
    for e in entries:
        sx, sy = e.scale
        scales[(sx, sy)] += 1
    playback = Counter(e.playback for e in entries)
    groups = Counter(e.group for e in entries)
    regs = Counter(e.register for e in entries)

    print(f"registers: {dict(sorted(regs.items()))}")
    print(f"groups:    {dict(sorted(groups.items()))}")
    print(f"playback:  {dict(playback)}")
    print("fps:       " + str({p: sorted({e.fps for e in entries
                                          if e.playback == p})
                               for p in sorted(playback)}))
    print(f"scale:     {dict(scales)}   <- read per entry, never assumed")
    print(f"slots:     {sum(len(e.slots) for e in entries)} across "
          f"{sum(1 for e in entries if e.slots)} entries")

    if orphans:
        print(f"\nunreferenced files on disk: {len(orphans)}")
        for p in orphans[:10]:
            print(f"  {p.relative_to(repo)}")

    if problems:
        print(f"\nFAILED — {len(problems)} problems:")
        for p in problems[:40]:
            print(f"  {p}")
        if len(problems) > 40:
            print(f"  ... and {len(problems) - 40} more")
        print("\nDO NOT COMMIT.")
        return 1

    print(f"\nOK — {len(entries)} entries verified, every frame present at "
          f"its delivered size, every slot inside its canvas.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("delivery", nargs="?", type=Path,
                    help="directory holding assets/ and engine/")
    ap.add_argument("--check", action="store_true",
                    help="verify the installed kit without installing")
    args = ap.parse_args()

    if not args.check and args.delivery is None:
        ap.error("give a delivery directory, or --check")

    try:
        if args.delivery is not None:
            print(f"installing from {args.delivery}")
            _install(args.delivery, REPO)
            print()
        return _verify(REPO)
    except KitError as exc:
        print(f"FAILED — {exc}", file=sys.stderr)
        print("\nDO NOT COMMIT.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
