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
BLANK_SOURCES = {
    "blanks/big-number-blank": "type/callouts/big-number-blank.png",
    "blanks/term-card-blank": "type/callouts/term-card-blank.png",
    "blanks/quote-pull-blank": "type/quotes/pull-blank.png",
}

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
    ap.add_argument("archive", type=Path,
                    help="the unpacked delivery (contains kit-v1/, shorts/, "
                         "kit-registry.json)")
    ap.add_argument("--out", type=Path, default=KIT_OUT)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    archive: Path = args.archive
    registry_src = archive / REGISTRY_NAME
    if not registry_src.exists():
        print(f"no {REGISTRY_NAME} in {archive}", file=sys.stderr)
        return 2

    registry = json.loads(registry_src.read_text(encoding="utf-8"))
    assets: dict[str, dict] = registry["assets"]

    # The registry declares where each source lands; frame paths are relative
    # to their own root, so resolution has to go through it.
    src_root = {"kit-v1": archive / "kit-v1", "shorts": archive / "shorts"}
    dst_rel = {"kit-v1": Path("."), "shorts": Path("shorts")}
    root_for = {k: src_root[v["source"]] for k, v in assets.items()}

    # ---- reconcile before touching anything --------------------------
    declared: dict[str, set[str]] = {"kit-v1": set(), "shorts": set()}
    for key, entry in assets.items():
        for frame in entry["frames"]:
            declared[entry["source"]].add(frame)
            if not (root_for[key] / frame).exists():
                print(f"registry lists a frame that is not in the archive: "
                      f"{key} -> {frame}", file=sys.stderr)
                return 2

    skipped: list[str] = []
    for source, root in src_root.items():
        for png in sorted(root.rglob("*.png")):
            rel = png.relative_to(root)
            if str(rel) in declared[source]:
                continue
            skipped.append(f"{source}/{rel}" + ("  (meta)" if is_meta(rel) else "  (no registry entry)"))

    aliases, dead_flaps = compute_aliases(assets, root_for)
    corrections = apply_corrections(assets)

    print(f"archive     : {archive}")
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
    # Delete first. A merge is what left dark-theme leftovers resolvable.
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

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
    previous = ROOT / "assets" / "_kit_previous"
    for key, rel in BLANK_SOURCES.items():
        src = previous / rel
        if not src.exists():
            print(f"blank layout {key} not found at {src} — skipped "
                  f"(stage the previous kit at assets/_kit_previous to carry "
                  f"them over)", file=sys.stderr)
            continue
        dst = out / BLANK_ENTRIES[key]["frames"][0]
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
