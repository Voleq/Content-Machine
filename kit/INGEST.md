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
| `*/manifest.json` | 14 families, 270 assets, 3,033 slots. Geometry, playback, type roles. Emitted by the same call that draws the plate. **One location**: `kit/<family>/manifest.json`. delta-14 ships its copies under `kit/manifests/<family>/`, which the ingest's glob does not match — placed there they read as zero assets and the reconcile compares against nothing. |
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

## The build is memory-bound

924 frames across 270 plates. A single-pass ingest has been OOM-killed part
way through on a small machine, and the cause is not what it looks like.

**It is not plate cost.** The largest single frame is a room at about 1.5 MB
of SVG and the whole library serialised is survivable. It is **retention**: a
caller that walks the library, calls `draw()` per frame and keeps the
returned plate objects holds 924 path lists, slot tables and manifests at
once. That is what the kernel kills.

Three routes, in order of what to try:

```bash
python scripts/ingest_kit.py kit              # one pass — try this first
python scripts/ingest_kit.py kit --batched    # 14 processes, one per family
python scripts/ingest_kit.py kit --only room  # re-do one family, verify only
```

`--batched` is the supported fallback: one process per family, each exiting
and returning its memory to the OS before the next starts. It costs fourteen
process starts and fourteen engine parses, shares no work between families,
and cannot see a cross-family defect — the same blindness the per-family
manifest generation has. It is slower than one pass and it is meant to be.

`--only FAMILY` builds and reconciles one family and **does not install a
registry**. A registry holding one family is not a kit, and writing one would
leave the render path at a library with thirteen holes in it. Use it to
regenerate the family a batched run failed on, then re-run `--batched`.

`BUILD.stream(fn, opts)` in `engine/build.js` is the in-process fix for the
same problem: it yields one frame, hands it over and drops every reference
before building the next, so peak memory is one frame plus whatever the
consumer keeps. `kit/scripts/build_batch.mjs` is design's own per-family
driver and documents the contract either route must not break.

**~400 MB lands in `assets/plates/`**, which is gitignored. That directory is
the build product the render path reads; nothing else reads the kit.

## Facts the pipeline needs

- **`exportScale: 2` on every asset.** Slot boxes are in canvas units; delivered
  pixels are canvas × 2. Getting this wrong puts every figure at half its
  intended position, silently.
- **`frames` is a list of objects**, not filenames: `{tag, svg, png, boil}`.
- **The base PNG is byte-identical to frame `f01`** on all 267 plates that carry
  more than one frame, so a loop can be entered from the still without a pop.
  `files.baseIsFrame` says so per plate; the ingest checks the bytes.
- **A data plate's FRAME breathes and its FIGURES do not.** This line used to
  read *"Data plates are `playback: "static"` — tables, charts, figures,
  structure, peers and cycles never boil, 44 assets"*, and that rule was
  retracted in the engine without this file following. All 122 data-family
  plates are `playback: "loop"`. The boil is turned on for their FURNITURE —
  paper edge, corner wear, rule lines, hatch — and `HAND.setBoil`'s gate keeps
  axes, series lines, figures and cells emitting the identical path they
  emitted at boil 0, bit for bit. A number still never moves; the paper it is
  printed on does. `engine/build.js` §1.5 is the statement of it.
- **270 plates: 260 `loop`, 7 `overlay`, 3 `static`.** The 7 are the host's
  blink strips, composited over the matching idle frame rather than played. The
  3 are `overlays/row-band` and the two lower thirds — furniture that sits under
  type held still, where movement would be relative movement, and in the lower
  third's case a wobble at the edge of vision for forty minutes.
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
