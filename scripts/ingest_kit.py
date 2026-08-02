#!/usr/bin/env python3
"""Rebuild ``assets/kit/`` from a design-delivery archive.

The previous kit was copied in by hand: meta files sat in the same folders as
artwork, the same drawing shipped under two naming schemes, and nothing
recorded which files were addressable. This script is the answer to that — the
ingest is a rule, not a habit, so the next delivery lands the same way.

    python scripts/ingest_kit.py path/to/dennis-assets-min

What it does

1. **Deletes ``assets/kit/`` outright**, then writes it fresh. Merging is what
   left dark-theme leftovers resolvable last time; there is no merge mode.
2. Copies ``kit-v1/`` to ``assets/kit/`` and ``shorts/`` to
   ``assets/kit/shorts/`` — the two roots the registry declares.
3. Copies **only files the registry lists as frames**. Contact sheets, index
   sheets and probe files are for humans and stay in the archive; an orphan
   like ``press/podium-ceo_b.png`` (whose base moved to ``props/``) is left
   behind rather than shipped as an asset nothing can address.
4. Writes ``assets/kit/kit-registry.json`` — the single source of truth —
   extended with:
   * ``aliases``: the fifteen byte-identical duplicate groups collapsed to one
     canonical name each, so variant selection stops offering the same drawing
     three times;
   * the three blank layouts carried forward from the previous kit, with the
     slot geometry that finally makes them fillable.
5. Restyles the seven dark cards to the light theme (see
   :mod:`scripts.restyle_dark_cards`), so a video no longer switches theme to
   close.

Per-family ``manifest.json`` files are NOT copied: they duplicate the registry
exactly (verified at ingest), and a second source of truth is how the geometry
drifts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Run as `python scripts/ingest_kit.py`, sys.path[0] is scripts/ — so the
# sibling import below resolves only under pytest, which is exactly where the
# portability guard was being exercised and nowhere else.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

KIT_OUT = ROOT / "assets" / "kit"
REGISTRY_NAME = "kit-registry.json"

# Files that live in the asset folders but are not assets: contact sheets,
# index sheets, style references and probes. They are kept in the archive for
# humans; nothing in the pipeline may resolve them.
META_NAMES = ("contact-sheet.png", "_index.png", "_STYLE-REF.png")
META_DIRS = ("_meta", "_probe")


def is_meta(rel: Path) -> bool:
    return rel.name in META_NAMES or any(p in META_DIRS for p in rel.parts)


# --------------------------------------------------------------------------
# Per-family manifests.
#
# The top-level `kit-registry.json` is the delivery's own index, and it only
# knows about the families that were in the delivery when it was written. A
# folder that GAINS a family — the commissioned `stings/`, say — shipped its
# own `manifest.json` and had nowhere to go: registering it meant hand-merging
# entries into the top-level registry, which is a code-adjacent edit for what
# is really just new artwork arriving.
#
# So every `manifest.json` found under any source is merged. A family that
# ships one registers with no edit and no code change.
# --------------------------------------------------------------------------
MANIFEST_NAME = "manifest.json"


def discover_manifests(sources: list[Path]) -> list[tuple[Path, dict]]:
    """Every per-family `manifest.json` under the given sources."""
    found: list[tuple[Path, dict]] = []
    for src in sources:
        if not src.exists():
            continue
        for mpath in sorted(src.rglob(MANIFEST_NAME)):
            try:
                data = json.loads(mpath.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                print(f"skipping unreadable {mpath}: {exc}", file=sys.stderr)
                continue
            if isinstance(data, dict) and data.get("assets"):
                found.append((mpath, data))
    return found


def entries_from_manifest(mpath: Path, data: dict) -> tuple[dict[str, dict], Path]:
    """`{registry key: entry}` for one family manifest, and its frame root.

    The manifest's own `family` is the authority for the key, not the folder
    it happens to sit in — `stings/` arrived nested three deep inside the
    delivery and still has to register as `stings/<name>`.
    """
    family = str(data.get("family") or mpath.parent.name).strip("/")
    canvas = data.get("canvas") or {}
    cw = int(canvas.get("width") or canvas.get("w") or 0)
    ch = int(canvas.get("height") or canvas.get("h") or 0)
    export_scale = int(canvas.get("exportScale") or 1)
    fam_fps = int(data.get("fps") or 12)

    out: dict[str, dict] = {}
    for raw in data.get("assets") or []:
        name = str(raw.get("name") or "").strip()
        if not name:
            continue
        files = [str(f) for f in (raw.get("files") or [])]
        if not files:
            single = raw.get("path")
            files = [Path(str(single)).name] if single else []
        if not files:
            continue
        acanvas = raw.get("canvas") or {}
        aw = int(acanvas.get("width") or acanvas.get("w") or cw)
        ah = int(acanvas.get("height") or acanvas.get("h") or ch)
        entry = {
            "family": family,
            "name": name,
            "frames": [f"{family}/{Path(f).name}" for f in files],
            "frameCount": int(raw.get("frameCount") or len(files)),
            "playback": str(raw.get("playback")
                            or ("one-shot" if len(files) > 1 else "static")),
            "fps": int(raw.get("fps") or fam_fps),
            "canvas": {"w": aw, "h": ah},
            "aspect": _aspect(aw, ah),
            "alpha": True,
            "slots": raw.get("slots") or [],
            "source": f"manifest:{family}",
        }
        if raw.get("title"):
            entry["title"] = str(raw["title"])
        if export_scale > 1:
            entry["exportScale"] = export_scale
        for extra in ("coverFrames", "direction", "note"):
            if raw.get(extra) is not None:
                entry[extra] = raw[extra]
        out[f"{family}/{name}"] = entry
    return out, mpath.parent


def _aspect(w: int, h: int) -> str:
    """The registry's aspect string for a canvas, or "" when unknown."""
    if not w or not h:
        return ""
    ratio = w / h
    for label, value in (("1:1", 1.0), ("16:9", 16 / 9), ("9:16", 9 / 16),
                         ("4:5", 0.8), ("4:3", 4 / 3)):
        if abs(ratio - value) / value < 0.02:
            return label
    return f"{w}:{h}"


def palette_offenders(paths: dict[str, Path]) -> list[str]:
    """Source PNGs saved in palette mode, as `key -> file` lines.

    A palette PNG is a size optimisation that hard-quantises the antialiased
    edges the whole kit is drawn with — the line work is the artwork here, so
    an optimised delivery is a lossy one. It also surfaces as a Pillow
    transparency warning at render time rather than as an error at ingest.
    """
    from PIL import Image

    bad: list[str] = []
    for key, path in sorted(paths.items()):
        try:
            with Image.open(path) as im:
                mode = im.mode
        except OSError:
            continue
        if mode not in ("RGBA", "LA"):
            bad.append(f"{key} -> {path.name} ({mode})")
    return bad


def unportable(rel: str) -> str | None:
    """Why a registry frame path could not be checked out everywhere, or None.

    The ingest is the thing that writes ``assets/kit/`` now, so this is where
    the check belongs. A path Windows cannot create fails `git checkout` for
    every file under it while the Linux tree still looks clean — which is what
    ``restyle/con/`` did, taking eighteen frames with it. A delivery is
    somebody else's export, so it is checked rather than trusted.
    """
    from scripts.export_design_kit import DOS_DEVICES, ILLEGAL_CHARS

    for part in Path(rel).parts:
        if ILLEGAL_CHARS.search(part):
            return f"{part!r} contains a character Windows forbids"
        if part != part.rstrip(". ") or part != part.lstrip(" "):
            return f"{part!r} ends in a dot or space"
        if part.partition(".")[0].upper() in DOS_DEVICES:
            return f"{part!r} is a reserved DOS device name"
    return None


# --------------------------------------------------------------------------
# The blank layouts carried forward from the previous kit.
#
# Three parameterised cards shipped in the 2024 kit and nothing ever filled
# them — they are the only assets in either kit that were designed to take
# arbitrary text, and they were sitting in `type/callouts` and `type/quotes`
# with placeholder copy baked in. They come across as first-class registry
# entries with real slot geometry, so the slot filler treats them like any
# other slotted asset.
#
# `clear` is why they need their own entries: the placeholder text is part of
# the PNG, so the box has to be painted back to paper before the real text is
# drawn. Nothing in the shorts batch needs this — those boxes are empty
# regions of the drawing — so it is declared per slot rather than assumed.
# --------------------------------------------------------------------------
# Where each blank layout is looked for, in order. The kit's OWN copy comes
# first, so a re-ingest of a repo that already has them carries them forward
# without any staging at all — which is the ordinary case and the one that
# used to destroy them.
#
# THE DELIVERY DOES NOT CONTAIN THESE. `dennis-assets.zip` has no
# `type/callouts/`, no `type/quotes/`, and no file with `blank` in the name;
# these three are the last surviving copies from the 2024 kit. They are
# artwork we are owed, not a config problem — until Design ships them in a
# delivery, this repo is the only place they exist.
BLANK_SOURCES: dict[str, tuple[str, ...]] = {
    "blanks/big-number-blank": (
        "blanks/big-number-blank.png",              # the current kit
        "type/callouts/big-number-blank.png",       # a staged 2024 kit
    ),
    "blanks/term-card-blank": (
        "blanks/term-card-blank.png",
        "type/callouts/term-card-blank.png",
    ),
    "blanks/quote-pull-blank": (
        "blanks/quote-pull-blank.png",
        "type/quotes/pull-blank.png",
    ),
}

# Searched in order for the sources above.
def blank_search_roots(out: Path) -> tuple[Path, ...]:
    return (out, ROOT / "assets" / "_kit_previous")


def find_blank_sources(out: Path) -> tuple[dict[str, Path], list[str]]:
    """(key -> staged file, missing keys). Runs BEFORE anything is deleted."""
    found: dict[str, Path] = {}
    missing: list[str] = []
    for key, candidates in BLANK_SOURCES.items():
        for root in blank_search_roots(out):
            hit = next((root / c for c in candidates if (root / c).is_file()), None)
            if hit is not None:
                found[key] = hit
                break
        else:
            missing.append(key)
    return found, missing

_MONO = {"family": "Space Mono", "weight": 700}
_DISPLAY = {"family": "Shantell Sans", "weight": 800}

# Boxes are MEASURED off the delivered PNGs (the ink bands of the placeholder
# copy), not eyeballed — the placeholder is exactly where the real value has to
# land, and a box that misses it leaves the dummy text showing through.
BLANK_ENTRIES: dict[str, dict] = {
    "blanks/big-number-blank": {
        "family": "blanks",
        "name": "big-number-blank",
        "title": "Big number — blank layout",
        "frames": ["blanks/big-number-blank.png"],
        "frameCount": 1,
        "playback": "static",
        "fps": 0,
        "canvas": {"w": 1920, "h": 1080},
        "aspect": "16:9",
        "alpha": False,
        "slots": [
            {"name": "kicker", "box": {"x": 560, "y": 272, "w": 800, "h": 46},
             "align": "center", "valign": "middle", "font": _MONO,
             "clear": "paper", "tracking": 0.18, "case": "upper",
             "colour": "grey", "note": "the label above the figure"},
            # The band includes the green up-arrow. It is cleared with the
            # rest: a hardcoded arrow is wrong on every figure that went down.
            {"name": "figure", "box": {"x": 400, "y": 370, "w": 1120, "h": 226},
             "align": "center", "valign": "middle", "font": _DISPLAY,
             "clear": "paper", "note": "the number itself"},
            {"name": "headline", "box": {"x": 400, "y": 638, "w": 1120, "h": 84},
             "align": "center", "valign": "middle", "font": _DISPLAY,
             "clear": "paper", "note": "what the number is"},
            {"name": "context", "box": {"x": 460, "y": 758, "w": 1000, "h": 48},
             "align": "center", "valign": "middle", "font": _MONO,
             "clear": "paper", "colour": "grey", "note": "one line, no more"},
        ],
        "source": "kit-v1",
    },
    "blanks/term-card-blank": {
        "family": "blanks",
        "name": "term-card-blank",
        "title": "Term card — blank layout",
        "frames": ["blanks/term-card-blank.png"],
        "frameCount": 1,
        "playback": "static",
        "fps": 0,
        "canvas": {"w": 1920, "h": 1080},
        "aspect": "16:9",
        "alpha": False,
        "slots": [
            {"name": "kicker", "box": {"x": 152, "y": 262, "w": 900, "h": 44},
             "align": "left", "valign": "middle", "font": _MONO,
             "clear": "paper", "tracking": 0.18, "case": "upper",
             "colour": "red", "note": "the word-of-the-day strap"},
            {"name": "term", "box": {"x": 152, "y": 330, "w": 1400, "h": 142},
             "align": "left", "valign": "middle", "font": _DISPLAY,
             "clear": "paper", "note": "the term being defined"},
            {"name": "definition", "box": {"x": 152, "y": 572, "w": 1260, "h": 154},
             "align": "left", "valign": "top",
             "font": {"family": "Space Grotesk", "weight": 500},
             "clear": "paper", "wrap": True,
             "note": "one sentence, plain words"},
            {"name": "footnote", "box": {"x": 152, "y": 768, "w": 1100, "h": 48},
             "align": "left", "valign": "middle",
             "font": {"family": "Space Grotesk", "weight": 400},
             "clear": "paper", "colour": "grey", "italic": True,
             "note": "the aside under the definition"},
        ],
        "source": "kit-v1",
    },
    "blanks/quote-pull-blank": {
        "family": "blanks",
        "name": "quote-pull-blank",
        "title": "Pull quote — blank layout",
        "frames": ["blanks/quote-pull-blank.png"],
        "frameCount": 1,
        "playback": "static",
        "fps": 0,
        "canvas": {"w": 1920, "h": 1080},
        "aspect": "16:9",
        "alpha": False,
        "slots": [
            # Starts below the decorative quote mark, which stays.
            {"name": "quote", "box": {"x": 152, "y": 352, "w": 1360, "h": 340},
             "align": "left", "valign": "top", "font": _DISPLAY,
             "clear": "paper", "wrap": True,
             "note": "the sentence, in full, nothing trimmed"},
            # Left of x=330 is the red rule, which is furniture, not content.
            {"name": "attribution", "box": {"x": 336, "y": 788, "w": 940, "h": 44},
             "align": "left", "valign": "middle", "font": _MONO,
             "clear": "paper", "tracking": 0.16, "case": "upper",
             "colour": "grey", "note": "who said it · where · when"},
        ],
        "source": "kit-v1",
    },
}


# --------------------------------------------------------------------------
# Corrections applied to the delivered registry
#
# The delivery is data, and data can be wrong. Each fix here is measured
# against the artwork itself, stated in full, and re-applied on every ingest so
# a fresh delivery cannot quietly reintroduce it.
# --------------------------------------------------------------------------
def apply_corrections(assets: dict[str, dict]) -> list[str]:
    notes: list[str] = []

    # `slotFrameDelta.y = 118` on numbers-raining is documented as "per frame
    # index", but the drops in the artwork fall 19.9 +/- 0.7 canvas px per
    # frame (measured over 150 box tops across all six frames). 118 is the
    # travel over the whole SIX-FRAME cycle: 118/6 = 19.67, inside the
    # measurement noise. Read literally the figures would fall six times faster
    # than the rain they are supposed to be sitting in — which looks like the
    # delta working, from a distance, and is why it is worth stating.
    key = "shorts/dennis-vs-numbers/numbers-raining"
    entry = assets.get(key)
    if entry and entry.get("slotFrameDelta"):
        delta = entry["slotFrameDelta"]
        frames = max(int(entry.get("frameCount") or 1), 1)
        if delta.get("y") and frames > 1 and delta["y"] > 60:
            was = delta["y"]
            delta["y"] = round(was / frames, 2)
            delta["note"] = (
                f"slot boxes shift by this delta per frame index; wrap y back "
                f"by wrap.span when it passes wrap.maxY. Corrected at ingest: "
                f"the delivery carried {was} (the travel over the whole "
                f"{frames}-frame cycle) against a note saying per-frame. The "
                f"drops measure {delta['y']}/frame in the artwork.")
            notes.append(f"{key}: slotFrameDelta.y {was} -> {delta['y']} "
                         f"(per frame, measured off the drawing)")
    return notes


# --------------------------------------------------------------------------
# Deduplication
# --------------------------------------------------------------------------
# Fifteen groups of byte-identical files ship under two naming schemes
# (`mascot/` and `restyled/`). Left alone the variant picker treats them as
# distinct options, so "give me a different reaction" can hand back the same
# drawing. The canonical name is the one the rest of the pipeline already
# addresses; the others resolve THROUGH it and are hidden from selection.
#
# The last group is different in kind, and worth stating: `-talk` is meant to
# be the mouth-open twin for host beats. It is byte-identical to the closed
# frame, so the flap on that asset does nothing. Recording it as an alias is
# what lets the kit doctor report it as artwork owed rather than leaving a
# silent no-op in the render.
def _frame_digests(entry: dict, root: Path) -> tuple[str, ...]:
    return tuple(
        hashlib.sha256((root / f).read_bytes()).hexdigest()
        for f in entry["frames"] if (root / f).exists()
    )


def compute_aliases(assets: dict[str, dict], root_for: dict[str, Path],
                    prefer: tuple[str, ...] = ("mascot/", "chapters/"),
                    ) -> tuple[dict[str, str], list[str]]:
    """(alias key -> canonical key, dead mouth-flaps).

    Two kinds of duplicate, and they are not the same problem:

    * whole assets that are byte-for-byte the same drawing under two names —
      the `mascot/` vs `restyled/` split. Collapse to one canonical name so
      the variant picker stops offering one drawing as three choices.
    * a `-talk` twin identical to the frame it is supposed to differ from.
      That is not a naming duplicate, it is *missing artwork*: the mouth flap
      on that asset animates nothing. It aliases the same way, and it is
      returned separately so the kit doctor can report the gap.
    """
    digests = {k: _frame_digests(v, root_for[k]) for k, v in assets.items()}

    by_digest: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for key, d in digests.items():
        if d:
            by_digest[d].append(key)

    def rank(k: str) -> tuple[int, int, str]:
        head = next((i for i, p in enumerate(prefer) if k.startswith(p)), len(prefer))
        # a plain name beats a "-talk" twin as the canonical drawing
        return (head, 1 if k.endswith("-talk") else 0, k)

    aliases: dict[str, str] = {}
    for keys in by_digest.values():
        if len(keys) < 2:
            continue
        canonical = min(sorted(keys), key=rank)
        for k in keys:
            if k != canonical:
                aliases[k] = canonical

    # A `-talk` frame that equals the FIRST frame of its base. The base is
    # often a two-frame boil, so the whole-asset digests differ and the group
    # above never sees it — which is exactly how this one stayed invisible.
    dead_flaps: list[str] = []
    for key in sorted(assets):
        if not key.endswith("-talk"):
            continue
        base = key[: -len("-talk")]
        if base not in digests or not digests[key] or not digests[base]:
            continue
        if digests[key][0] == digests[base][0]:
            dead_flaps.append(key)
            aliases.setdefault(key, base)
    return aliases, dead_flaps


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("archive", type=Path, nargs="+",
                    help="one or more unpacked delivery directories. The "
                         "first that carries a kit-registry.json provides the "
                         "base index; every manifest.json found under any of "
                         "them registers its family.")
    ap.add_argument("--out", type=Path, default=KIT_OUT)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--allow-palette", action="store_true",
        help="ingest palette-mode PNGs anyway. They are a lossy size "
             "optimisation of artwork whose line work IS the asset; this "
             "exists only so a repo can be worked on while a full-fidelity "
             "re-export is outstanding. Every offender is still named.")
    args = ap.parse_args(argv)

    sources: list[Path] = list(args.archive)
    for src in sources:
        if not src.exists():
            print(f"no such directory: {src}", file=sys.stderr)
            return 2

    base = next((s for s in sources if (s / REGISTRY_NAME).exists()), None)
    if base is not None:
        registry = json.loads((base / REGISTRY_NAME).read_text(encoding="utf-8"))
        assets: dict[str, dict] = registry["assets"]
    else:
        # A delivery can be nothing but families with their own manifests.
        base = sources[0]
        registry = {"kit": "dennis", "version": 1, "roots": {}, "assets": {}}
        assets = registry["assets"]

    # The registry declares where each source lands; frame paths are relative
    # to their own root, so resolution has to go through it.
    src_root: dict[str, Path] = {"kit-v1": base / "kit-v1",
                                 "shorts": base / "shorts"}
    dst_rel: dict[str, Path] = {"kit-v1": Path("."), "shorts": Path("shorts")}
    root_for = {k: src_root[v["source"]] for k, v in assets.items()
                if v.get("source") in src_root}

    # ---- families that brought their own manifest ---------------------
    #
    # Only families the base registry does NOT already cover. Every family in
    # the delivery ships a manifest of its own, and those are already indexed
    # by the top-level registry — under its own keys, which carry the
    # delivery's prefix (`shorts/dennis-vs-numbers`, not `dennis-vs-numbers`).
    # Merging them again registered a second, unprefixed copy of the whole
    # shorts batch and left `shorts/dennis-vs-numbers/crushed-flat`
    # unresolvable. The manifest route is for artwork that ARRIVES, which is
    # the case it exists for.
    existing_families = {str(v.get("family", "")) for v in assets.values()}
    merged_families: list[tuple[str, int]] = []
    for mpath, data in discover_manifests(sources):
        entries, froot = entries_from_manifest(mpath, data)
        if not entries:
            continue
        family = next(iter(entries.values()))["family"]
        if any(f == family or f.endswith(f"/{family}") for f in existing_families):
            continue        # the base registry already indexes this family
        source = f"manifest:{family}"
        src_root[source] = froot.parent      # frames are `<family>/<file>`
        dst_rel[source] = Path(".")
        registry.setdefault("roots", {})[source] = "assets/kit/"
        assets.update(entries)
        for key in entries:
            root_for[key] = froot.parent
        existing_families.add(family)
        merged_families.append((family, len(entries)))

    if not assets:
        print(f"nothing to ingest — no {REGISTRY_NAME} and no {MANIFEST_NAME} "
              f"under {', '.join(str(s) for s in sources)}", file=sys.stderr)
        return 2

    # ---- reconcile before touching anything --------------------------
    declared: dict[str, set[str]] = defaultdict(set)
    unportable_paths: list[str] = []
    frame_files: dict[str, Path] = {}
    for key, entry in assets.items():
        root = root_for.get(key)
        if root is None:
            print(f"registry entry {key} has an unknown source "
                  f"{entry.get('source')!r}", file=sys.stderr)
            return 2
        for frame in entry["frames"]:
            declared[entry["source"]].add(frame)
            src = root / frame
            if not src.exists():
                print(f"registry lists a frame that is not in the archive: "
                      f"{key} -> {frame}", file=sys.stderr)
                return 2
            frame_files[f"{key} [{frame}]"] = src
            why = unportable(frame)
            if why is not None:
                unportable_paths.append(f"{key} -> {frame}: {why}")
    if unportable_paths:
        print("refusing to ingest — these paths would break `git checkout` on "
              "Windows, and every file under them with it:", file=sys.stderr)
        for line in unportable_paths:
            print(f"  {line}", file=sys.stderr)
        print("Rename them in the delivery and re-export.", file=sys.stderr)
        return 2

    # ---- full fidelity, checked rather than assumed -------------------
    palette = palette_offenders(frame_files)
    if palette:
        head = ("PALETTE-MODE SOURCE PNGs — this delivery is size-optimised, "
                f"not full fidelity ({len(palette)} of {len(frame_files)} "
                f"frames):")
        if not args.allow_palette:
            print(f"refusing to ingest — {head}", file=sys.stderr)
            for line in palette[:40]:
                print(f"  {line}", file=sys.stderr)
            if len(palette) > 40:
                print(f"  ... and {len(palette) - 40} more", file=sys.stderr)
            print(
                "\nPalette mode hard-quantises the antialiased edges the kit "
                "is drawn with, and the line work IS the artwork. Ask for a "
                "full-RGBA re-export.\nTo proceed anyway with the lossy "
                "delivery, pass --allow-palette.", file=sys.stderr)
            return 2
        print(f"WARNING     : {head}")
        for line in palette[:10]:
            print(f"              {line}")
        if len(palette) > 10:
            print(f"              ... and {len(palette) - 10} more")

    skipped: list[str] = []
    for source, root in src_root.items():
        if not root.exists():
            continue
        for png in sorted(root.rglob("*.png")):
            rel = png.relative_to(root)
            if str(rel) in declared[source]:
                continue
            if any(str(rel) in d for d in declared.values()):
                continue
            skipped.append(f"{source}/{rel}"
                           + ("  (meta)" if is_meta(rel) else "  (no registry entry)"))

    aliases, dead_flaps = compute_aliases(assets, root_for)
    corrections = apply_corrections(assets)
    _, missing_preview = find_blank_sources(args.out)

    print(f"sources     : {', '.join(str(s) for s in sources)}")
    for family, n in merged_families:
        print(f"manifest    : {family} -> {n} assets registered from its own "
              f"{MANIFEST_NAME}")
    if missing_preview:
        print(f"blanks      : MISSING — {', '.join(missing_preview)} "
              f"(the ingest will refuse)")
    for note in corrections:
        print(f"corrected   : {note}")
    print(f"assets      : {len(assets)} registered, "
          f"{sum(len(v['frames']) for v in assets.values())} frames")
    print(f"aliases     : {len(aliases)} duplicate names collapsed onto "
          f"{len(set(aliases.values()))} canonical drawings")
    for k in dead_flaps:
        print(f"              {k} is identical to its base — the mouth flap "
              f"on that asset does nothing (artwork owed)")
    print(f"not ingested: {len(skipped)}")
    for s in skipped:
        print(f"              {s}")

    if args.dry_run:
        return 0

    out: Path = args.out

    # ---- find the blank layouts BEFORE deleting anything ---------------
    # This used to run after the rmtree, reading from a staging directory that
    # does not exist by default — so an ordinary ingest deleted the only copies
    # of three irreplaceable PNGs and printed one line to stderr about it.
    blanks, missing_blanks = find_blank_sources(out)
    if missing_blanks:
        print("refusing to ingest — these blank layouts are not on disk and "
              "are NOT in the delivery:", file=sys.stderr)
        for key in missing_blanks:
            print(f"  {key}", file=sys.stderr)
        print(
            "\nThey are the only assets in either kit designed to take "
            "arbitrary text, and the copies in this repo are the last ones "
            "that exist. Recover them before ingesting:\n"
            "  git checkout HEAD -- assets/kit/blanks/\n"
            "or stage a previous kit export at assets/_kit_previous/ with\n"
            "  type/callouts/big-number-blank.png\n"
            "  type/callouts/term-card-blank.png\n"
            "  type/quotes/pull-blank.png\n"
            "If neither is available they have to be re-drawn — see "
            "assets/kit/README.md.", file=sys.stderr)
        return 2

    # Everything is staged; now it is safe to delete. A merge is what left
    # dark-theme leftovers resolvable, so there is no merge mode.
    staged = {key: src.read_bytes() for key, src in blanks.items()}
    # The kit's README documents this script. Deleting it on every run and
    # making the operator restore it from git is not a contract.
    readme = out / "README.md"
    staged_readme = readme.read_bytes() if readme.is_file() else None
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    if staged_readme is not None:
        readme.write_bytes(staged_readme)

    copied = 0
    for key, entry in assets.items():
        base_in = root_for[key]
        base_out = out / dst_rel[entry["source"]]
        for frame in entry["frames"]:
            dst = (base_out / frame).resolve()
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(base_in / frame, dst)
            copied += 1

    # ---- the blank layouts, carried forward --------------------------
    # Read into memory before the rmtree, because the kit's own copy is
    # usually the source and the rmtree is what would have eaten it.
    for key, payload in staged.items():
        dst = out / BLANK_ENTRIES[key]["frames"][0]
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(payload)
        assets[key] = BLANK_ENTRIES[key]
        copied += 1

    for alias, canonical in aliases.items():
        assets[alias]["aliasOf"] = canonical
    for key in dead_flaps:
        assets[key]["deadMouthFlap"] = True

    registry["aliases"] = dict(sorted(aliases.items()))
    registry["deadMouthFlaps"] = sorted(dead_flaps)
    registry["meta"] = {
        "names": list(META_NAMES),
        "dirs": list(META_DIRS),
        "note": "contact sheets, index sheets and probes — kept for humans, "
                "never ingested, never resolvable",
    }
    (out / REGISTRY_NAME).write_text(
        json.dumps(registry, indent=1, sort_keys=False) + "\n", encoding="utf-8")

    print(f"wrote       : {copied} frames + {REGISTRY_NAME} under {out}")

    # ---- relight the dark cards, then prove they are lit ---------------
    # Seven cards ship in the dark palette — the closing card, the subscribe
    # card, the disclaimer, the end screen. Left alone, every video closes by
    # switching theme. This used to be a separate command an operator had to
    # remember after every ingest, which means it was a step that could be
    # missed and silently restore them.
    restyled = _restyle(out)
    if restyled is None:
        return 2

    return _verify(out, assets, aliases, dead_flaps, skipped, restyled,
                   merged_families, bool(palette))


def _restyle(out: Path) -> int | None:
    """Relight the dark cards and prove it. None when it did not take."""
    from scripts.restyle_dark_cards import main as restyle_main

    print("restyle     : relighting the dark cards")
    if restyle_main(["--kit", str(out)]) != 0:
        print("restyle     : FAILED", file=sys.stderr)
        return None
    if restyle_main(["--kit", str(out), "--check"]) != 0:
        print("restyle     : ran, but --check still reports a dark card",
              file=sys.stderr)
        return None
    return 1


def _verify(out: Path, assets: dict, aliases: dict, dead_flaps, skipped: list,
            restyled, merged_families: list, lossy: bool) -> int:
    """The block that decides whether to commit.

    An ingest that printed "wrote N frames" and stopped told you it copied
    files, not that the result is loadable. This walks the written kit the way
    the pipeline will.
    """
    from collections import Counter

    from pipeline.kit import load_kit

    kit = load_kit(out.parent)
    problems = kit.verify()
    on_disk = sum(1 for _ in out.rglob("*.png"))
    by_family = Counter(a.family for k in kit.keys()
                        if (a := kit.get(k)) is not None)

    print()
    print("=" * 62)
    print("VERIFICATION")
    print("=" * 62)
    print(f"  registered assets : {len(kit)}")
    print(f"  frames on disk    : {on_disk}")
    print(f"  aliases collapsed : {len(aliases)} -> "
          f"{len(set(aliases.values()))} canonical")
    print(f"  dead mouth flaps  : {len(list(dead_flaps))}")
    print(f"  dark cards relit  : {'yes' if restyled else 'no'}")
    print(f"  not ingested      : {len(skipped)}")
    if merged_families:
        print("  families from their own manifest:")
        for family, n in merged_families:
            print(f"      {family:28s} {n:3d} assets")
    print(f"  families ({len(by_family)}):")
    for family, n in sorted(by_family.items()):
        print(f"      {family:36s} {n:3d}")
    if lossy:
        print("  fidelity          : LOSSY — palette-mode source was allowed")
    print(f"  Kit.verify()      : {len(problems)} problem(s)")
    for p in problems[:20]:
        print(f"      {p}")
    if len(problems) > 20:
        print(f"      ... and {len(problems) - 20} more")
    print("=" * 62)
    if problems:
        print("DO NOT COMMIT — the written kit does not verify.", file=sys.stderr)
        return 1
    print("OK to commit." + ("  (but the fidelity is lossy)" if lossy else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
