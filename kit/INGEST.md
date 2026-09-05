# dennis-v2 — what's in this archive and how to use it

This is the **code-facing** pack. It is deliberately not the artwork.

The full delivery is ~860 MB of 3840×2160 RGBA PNGs and SVGs. It does not need
to be shipped, because the library is deterministic: every asset is an author
plus a seed, declared in `engine/build.js`, and `BUILD.draw()` reproduces it
byte for byte. **The engine is the source; the PNGs are a cache.**

## Contents

| path | what |
|---|---|
| `engine/` | `hand.js` (the drawing hand), `plates.js` (every plate author), `series.js` (data renderers), `build.js` (the declared library — author + seed per asset), `audit.js` |
| `*/manifest.json` | 14 families, 143 assets, 1,444 slots. Geometry, playback, type roles. Emitted by the same call that draws the plate. |
| `fonts/` | Archivo Narrow + Courier Prime, every weight the manifests reference |
| `_reference/` | 27 downscaled PNGs, one or two per family, so you can see what a plate looks like without the full pack |
| `scripts/` | per-family notes on what each plate is for |
| `README.md` | the palette, the contract, the surface decision |

## Generating the artwork

`BUILD.draw(item, pal, frameArgs)` and `BUILD.drawWith(item, outfit, frameArgs)`
reproduce any asset. Outfits, boil frames and aspects are arguments, not files.

That is why the outfits are not shipped: five outfits × two boil frames × six
poses is 60 host plates that go stale the moment anything changes.

**Run the engine at ingest and write PNGs out. Do not call it at render time.**
A bug in `plates.js` should break a build, not a published video.

## Facts the pipeline needs

- **`exportScale: 2` on every asset.** Slot boxes are in canvas units; delivered
  pixels are canvas × 2. Getting this wrong puts every figure at half its
  intended position, silently.
- **`frames` is a list of objects**, not filenames: `{tag, svg, png, boil}`.
- **The base PNG is byte-identical to frame `f01`** on all 69 strips, so a loop
  can be entered from the still without a pop.
- **Data plates are `playback: "static"`.** Tables, charts, figures, structure,
  peers and cycles never boil — 44 assets. The other 69 are two-frame loops.
- **Twelve annotation slots sit OUTSIDE their own canvas** — `bracket-rows/area`
  is at x = −880. That is deliberate: annotations are overlays composited onto
  something else and their caption lands beside the mark, not inside it. A
  renderer that clips slots to the canvas will silently drop every annotation
  caption.
- **Room plates declare `floorLineY`** and a `host-anchor` region. The region's
  HEIGHT is the host's target height: scale the host so
  `(floorLineY − slots.figure.y)` equals it, then sit the host's `floorLineY`
  on the region's bottom edge. Never scale to the anchor's width.
- **No baked text anywhere.** Every word and figure on screen is a slot.
