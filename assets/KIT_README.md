# DENNIS — the complete kit, baked

**476 entries · 1,772 frames · 4 registers · zero slot drift.**

Every asset as a flat PNG at its delivered size, with its SVG source beside it.

```
assets/marker/          467 PNG   assets/marker-svg/          467 SVG
assets/ballpoint/       431       assets/ballpoint-svg/       431
assets/grease-pencil/   431       assets/grease-pencil-svg/   431
assets/cut-paper/       431       assets/cut-paper-svg/       431
assets/light/            12       assets/light-svg/            12
manifest.json           every entry, with the on-disk filename for every frame
manifest-<register>.json  the same, split per register
```

Sizes: 3840×2160 for 16:9, 2160×3840 for 9:16, 1280×720 for thumbnails,
native canvas ×2 for cut-outs and loops.

## Filenames

Single-frame assets are `<name>.png`. Multi-frame assets are
`<name>_f01.png … _fNN.png` in playback order. The SVG carries the same stem.
The manifest lists the files for every entry, so nothing has to be inferred
from the naming.

`light` is group M — register-agnostic, delivered once, not per register.

## Reading a frame

Slots are `x/y/w/h` in the asset's own canvas coordinates, origin top-left.
Multiply by `deliver / canvas` for pixels in the PNG. No text, number or datum
is drawn in any asset; every interior is empty for code.

## The three rules the files obey

**Boil.** Anything that was one static plate is three genuinely redrawn frames
at 7fps (`playback: "boil"` — 388 of the 476 entries). Play them on a loop. The
drawing is made again each frame rather than transformed, so the line lands
about 2–3% differently. Slots do not move between frames.

**Slot parity.** Slot names and coordinates are identical across all four
registers, every frame, and every clutter state — swapping register or state
needs no recalculation. The five 9:16 shorts plates still hold the coordinates
the shorts renderer was built against.

**World colour never touches data.** post-it `#e8d98a` · mug `#c98b52` ·
can `#7b9aa8` · curtain `#d8cfc0` · plant `#a8845c`, on physical objects only.
Ink `#232326`, red `#ff5247`, green `#2fd576` for an up move alone. The plant
is brown because it is dying, which keeps green meaning one thing.

## Two notes for the renderer

`loop-plant` and `loop-curtain` **replace** the plate's drawn plant and curtain
— they do not overlay, or you get a doubled outline. `loop-steam`,
`loop-cursor` and `loop-second-hand` are purely additive.

Light overlays multiply over a room plate and sit **below** anything code
draws, so numbers and charts are never tinted.
