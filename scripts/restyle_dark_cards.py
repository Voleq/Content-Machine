#!/usr/bin/env python3
"""Restyle the kit's seven dark cards to the light theme.

Five of the ten ``chapters/resigned-close`` frames plus ``short/card-noise``
were drawn dark — paper-coloured type on a near-black panel — in a kit that is
otherwise ink on paper. They are not decoration: they are the closing card, the
subscribe card, the disclaimer and the end screen, so *every* video ended by
switching theme mid-cut.

The restyle is a luminance inversion into the kit's own palette, not a generic
invert:

* **neutral pixels** (the panel and the type) are remapped along the
  paper -> ink ramp, so the near-black panel becomes paper and the
  paper-coloured type becomes ink. Mid-greys stay mid-grey, which keeps the
  quiet secondary lines quiet;
* **saturated pixels** are left alone. The accent red is ``#ff5247`` on both
  themes — it already reads on paper, and re-mapping it would either wash it
  out or turn it into a different brand colour;
* **alpha is untouched**, so the cards keep their transparent margins and
  composite exactly where they did before.

    python scripts/restyle_dark_cards.py            # rewrite in place
    python scripts/restyle_dark_cards.py --check    # exit 1 if any are dark

``--check`` is what the suite calls: it re-measures every card and fails if a
dark one is still resolvable, so a re-ingest cannot quietly put them back.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "assets" / "kit"

# The seven, named rather than detected. A luminance threshold would also
# catch the mascot cutouts (mostly-transparent frames read dark), and the point
# here is a deliberate list of structural cards, not a sweep.
DARK_CARDS = (
    "chapters/resigned-close/closing-card",
    "chapters/resigned-close/closing-card-talk",
    "chapters/resigned-close/outro-subscribe",
    "chapters/resigned-close/outro-subscribe-talk",
    "chapters/resigned-close/not-advice",
    "chapters/resigned-close/end-card",
    "short/card-noise",
)

PAPER = (242, 242, 239)
INK = (35, 35, 38)

# Below this chroma a pixel is "the panel or the type"; above it, it is the
# accent red and is left alone.
NEUTRAL_CHROMA = 46


def _restyle_pixel(r: int, g: int, b: int) -> tuple[int, int, int]:
    chroma = max(r, g, b) - min(r, g, b)
    if chroma > NEUTRAL_CHROMA:
        return r, g, b
    lum = (r * 299 + g * 587 + b * 114) // 1000
    t = lum / 255.0
    return tuple(round(PAPER[i] + (INK[i] - PAPER[i]) * t) for i in range(3))  # type: ignore[return-value]


def restyle(path: Path) -> None:
    from PIL import Image

    img = Image.open(path).convert("RGBA")
    rgb, alpha = img.convert("RGB"), img.getchannel("A")
    lut = {}
    out = []
    for px in rgb.getdata():
        if px not in lut:
            lut[px] = _restyle_pixel(*px)
        out.append(lut[px])
    new = Image.new("RGB", rgb.size)
    new.putdata(out)
    new = new.convert("RGBA")
    new.putalpha(alpha)
    new.save(path)


def mean_luminance(path: Path) -> float:
    """Mean luminance over the pixels that are actually drawn.

    Averaging the whole frame counts the transparent margin as black, which is
    what made the original audit's numbers hard to read.
    """
    from PIL import Image

    img = Image.open(path).convert("RGBA")
    total = count = 0
    for (r, g, b, a) in img.getdata():
        if a < 24:
            continue
        total += (r * 299 + g * 587 + b * 114) // 1000
        count += 1
    return total / count if count else 255.0


def _paths(registry: dict, key: str, kit_dir: Path = KIT) -> list[Path]:
    entry = registry["assets"][key]
    base = kit_dir / "shorts" if entry["source"] == "shorts" else kit_dir
    return [base / f for f in entry["frames"]]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="measure only; exit 1 if a card is still dark")
    ap.add_argument("--kit", type=Path, default=KIT,
                    help="the kit directory to relight (default assets/kit). "
                         "The ingest points this at whatever it just wrote, so "
                         "relighting is part of landing a delivery rather than "
                         "a separate step somebody has to remember.")
    args = ap.parse_args(argv)

    kit_dir: Path = args.kit
    registry_path = kit_dir / "kit-registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))

    dark: list[str] = []
    for key in DARK_CARDS:
        measured: list[float] = []
        for path in _paths(registry, key, kit_dir):
            if not path.exists():
                print(f"missing: {path}", file=sys.stderr)
                return 2
            # Idempotent: a luminance inversion is its own inverse, so a
            # second run would put the card straight back to dark. Only a
            # card that still measures dark is touched.
            if not args.check and mean_luminance(path) < 128:
                restyle(path)
            lum = mean_luminance(path)
            measured.append(lum)
            state = "dark" if lum < 128 else "light"
            print(f"  {lum:6.1f}  {state:<5}  {path.relative_to(kit_dir)}")
            if lum < 128:
                dark.append(str(path.relative_to(KIT)))
        # Keep the registry honest: `meanLum` is what the audit read the theme
        # off, so leaving the pre-restyle number in place would have the kit
        # still describing itself as dark.
        if not args.check and measured:
            registry["assets"][key]["meanLum"] = round(sum(measured) / len(measured))

    if not args.check:
        registry_path.write_text(
            json.dumps(registry, indent=1, sort_keys=False) + "\n", encoding="utf-8")

    if dark:
        print(f"\n{len(dark)} card(s) still dark in a light kit: "
              + ", ".join(dark), file=sys.stderr)
        return 1
    print(f"\nall {len(DARK_CARDS)} cards are light-theme")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
