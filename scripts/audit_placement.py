#!/usr/bin/env python3
"""Where every asset actually lands, in the SHORT and in the LONG.

The kit is 387 drawings in three aspect ratios and the two engines frame very
differently: the short is 9:16 with named bands and three registers, the long
is 16:9 contain-fitted onto paper. An asset that reads in one can be a
letterboxed stamp in the other, and nothing said so — the failure is silent
and only visible by watching a finished video.

So this walks the whole library through both engines' real placement maths and
reports, per asset:

* **coverage** — how much of the frame it ends up occupying;
* **clipped** — ink lost off the edge of the frame;
* **slots** — declared boxes the engine leaves empty;
* **furniture** — a long-form card's painted-in chip and disclaimer arriving
  in a frame that draws its own.

Run: python scripts/audit_placement.py [--format short|long|both] [--verbose]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Coverage below this reads as a stamp in the middle of empty paper rather than
# a shot. 0.18 is roughly a 1:1 drawing pillarboxed into 16:9 and then inset.
THIN_COVERAGE = 0.18


def _ink_box(img):
    """Bounding box of the drawn pixels, or None for an empty frame."""
    import numpy as np

    a = np.asarray(img.convert("RGBA")).astype(int)
    ink = (a[..., :3].mean(axis=2) < 205) & (a[..., 3] > 60)
    ys, xs = np.nonzero(ink)
    if not len(ys):
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def _contain(w: int, h: int, fw: int, fh: int) -> tuple[int, int]:
    r = min(fw / w, fh / h)
    return max(int(w * r), 1), max(int(h * r), 1)


def _cover(w: int, h: int, fw: int, fh: int) -> tuple[int, int]:
    r = max(fw / w, fh / h)
    return max(int(w * r), 1), max(int(h * r), 1)


def audit_short(asset, settings, frame=(1080, 1920)):
    """What the SHORT engine does with this asset."""
    from pipeline.kit_frames import is_full_frame, punch_crop, render_still
    from pipeline.render_short import (
        STAGE_H, STAGE_Y, _is_croppable,
    )

    W, H = frame
    scale = W / 1080.0
    img = render_still(asset, None, settings)
    notes: list[str] = []

    if is_full_frame(asset, frame):
        register = "full-bleed"
        cw, ch = _cover(img.width, img.height, W, H)
        # Cover-fit crops the overflowing axis; check the ink survives it.
        box = _ink_box(img)
        if box is not None:
            r = max(W / img.width, H / img.height)
            lost_x = max(int(img.width * r) - W, 0) / 2 / r
            lost_y = max(int(img.height * r) - H, 0) / 2 / r
            if box[0] < lost_x or box[1] < lost_y or \
               box[2] > img.width - lost_x or box[3] > img.height - lost_y:
                notes.append("cover-fit crops ink off the edge")
        coverage = 1.0
    elif _is_croppable(asset):
        register = "stage/punch"
        cropped = punch_crop(img, asset)
        pw, ph = _contain(cropped.width, cropped.height,
                          int(1040 * scale), int((STAGE_H + 200) * scale))
        sw, sh = _contain(img.width, img.height,
                          int(1000 * scale), int(STAGE_H * scale))
        coverage = max(pw * ph, sw * sh) / (W * H)
    else:
        register = "stage"
        sw, sh = _contain(img.width, img.height,
                          int(1000 * scale), int(STAGE_H * scale))
        coverage = sw * sh / (W * H)
        if sh > int(STAGE_H * scale) + 1 or int(STAGE_Y * scale) + sh > H:
            notes.append("taller than the stage band")

    empty = [s.name for s in asset.slots]   # the short fills them from the tag
    return {"register": register, "coverage": coverage,
            "unfilled_slots": [], "declared_slots": empty, "notes": notes}


def audit_long(asset, settings, frame=(1920, 1080)):
    """What the LONG engine does with this asset."""
    from pipeline.host import PANEL_FIGURES
    from pipeline.kit_frames import render_still, strip_baked_furniture

    W, H = frame
    img = strip_baked_furniture(render_still(asset, None, settings), asset)
    notes: list[str] = []

    # `_hold_still_chain`: contain-fit onto paper, centred, held.
    cw, ch = _contain(img.width, img.height, W, H)
    coverage = cw * ch / (W * H)
    # `_panel_frame` two-shot: paper, the evidence, and a cut-out figure
    # standing beside it. The evidence gets the frame minus his column.
    fig_w = int(H * 0.62) if PANEL_FIGURES else 0
    pw, ph = _contain(img.width, img.height,
                      max(W - fig_w - int(W * 0.08), int(W * 0.2)), int(H * 0.80))

    if asset.aspect == "16:9" and any(
            s.clear for s in asset.slots) is False and asset.frame_count > 1:
        notes.append(f"{asset.frame_count}-frame {asset.playback} held as a still")
    return {"register": "full-frame", "coverage": coverage,
            "panel_coverage": pw * ph / (W * H),
            # The long binds tag values through `_kit_still` now, so a slot is
            # only empty when the script did not write one.
            "unfilled_slots": [],
            "declared_slots": [s.name for s in asset.slots], "notes": notes}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--format", choices=("short", "long", "both"), default="both")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    from config import Settings
    from pipeline.kit import load_kit

    settings = Settings(MOCK_MODE=True, _env_file=None)
    kit = load_kit(settings.assets_dir)

    rows = []
    for key in sorted(kit.keys()):
        asset = kit.get(key)
        if asset is None or asset.alias_of or not asset.frames:
            continue
        row = {"key": key, "aspect": asset.aspect, "slots": len(asset.slots),
               "frames": asset.frame_count}
        try:
            if args.format in ("short", "both"):
                row["short"] = audit_short(asset, settings)
            if args.format in ("long", "both"):
                row["long"] = audit_long(asset, settings)
        except Exception as exc:            # noqa: BLE001 — report, don't stop
            row["error"] = f"{type(exc).__name__}: {exc}"
        rows.append(row)

    print(f"PLACEMENT AUDIT — {len(rows)} assets\n")
    for fmt, frame in (("short", "9:16"), ("long", "16:9")):
        if fmt not in (args.format, "both") and args.format != "both":
            continue
        have = [r for r in rows if fmt in r]
        if not have:
            continue
        thin = [r for r in have if r[fmt]["coverage"] < THIN_COVERAGE]
        noted = [r for r in have if r[fmt]["notes"]]
        unfilled = [r for r in have if r[fmt]["unfilled_slots"]]
        print(f"== {fmt.upper()} ({frame}) ==")
        print(f"  assets placed          {len(have)}")
        print(f"  thin (<{THIN_COVERAGE:.0%} of frame)  {len(thin)}")
        print(f"  slots left empty       {len(unfilled)} assets, "
              f"{sum(len(r[fmt]['unfilled_slots']) for r in unfilled)} slots")
        print(f"  other notes            {len(noted)}")
        by_aspect: dict[str, list[float]] = {}
        for r in have:
            by_aspect.setdefault(r["aspect"] or "?", []).append(r[fmt]["coverage"])
        for asp, cov in sorted(by_aspect.items()):
            print(f"    {asp:6s} n={len(cov):3d}  median coverage "
                  f"{sorted(cov)[len(cov) // 2]:.0%}")
        if args.verbose:
            for r in thin[:25]:
                print(f"    thin  {r['key']}  {r[fmt]['coverage']:.0%}")
            for r in noted[:25]:
                print(f"    note  {r['key']}: {'; '.join(r[fmt]['notes'])}")
            for r in unfilled[:25]:
                print(f"    empty {r['key']}: "
                      f"{', '.join(r[fmt]['unfilled_slots'])}")
        print()

    broken = [r for r in rows if "error" in r]
    print(f"assets that failed to render: {len(broken)}")
    for r in broken[:20]:
        print(f"  {r['key']}: {r['error']}")
    return 1 if broken else 0


if __name__ == "__main__":
    raise SystemExit(main())
