# DENNIS — everything

**476 entries · 1,772 frames · four registers · zero slot drift.**

```
assets/          the deliverable: a flat PNG per frame at delivered size,
                 with its SVG source beside it
  marker/ 467 · ballpoint/ 431 · grease-pencil/ 431 · cut-paper/ 431 · light/ 12
  <register>-svg/  the matching SVG for every frame
  manifest.json              every entry, with the on-disk filename per frame
  manifest-<register>.json   the same, split per register
  README.md                  how to read a frame

pages/           two things to open in a browser. No build step.
  Dennis Kit - Motion Test.dc.html    sixty seconds, marker, eleven shots
  Dennis Kit - Long-Form Set.dc.html  the contact sheet for the whole kit,
                                      with register / boil / slots toggles
                                      and a live slot-drift check
engine/          the three files that draw everything, for reference
```

Sizes: 3840×2160 for 16:9, 2160×3840 for 9:16, 1280×720 for thumbnails,
native canvas ×2 for cut-outs and loops.

## Filenames

`<name>.png` for a single frame, `<name>_f01.png … _fNN.png` in playback
order for anything longer. The SVG carries the same stem. The manifest lists
the files for every entry, so nothing has to be inferred from the naming.

`light` is group M — register-agnostic, delivered once, not per register.

## Reading a frame

Slots are `x/y/w/h` in the asset's own canvas coordinates, origin top-left.
Multiply by `deliver / canvas` for pixels in the PNG. No text, number or datum
is drawn in any asset; every interior is empty for code.

## The three rules the files obey

**Boil.** Anything that was one static plate is three genuinely redrawn frames
at 7fps (`playback: "boil"` — 388 of the 476 entries). Play them on a loop.
The drawing is made again each frame rather than transformed, so the line lands
about 2–3% differently. Slots do not move between frames.

**Slot parity.** Slot names and coordinates are identical across all four
registers, every frame, and every clutter state — swapping register or state
needs no recalculation. The five 9:16 shorts plates still hold the coordinates
the shorts renderer was built against; the contact sheet re-checks this on
every load and prints the result.

**World colour never touches data.** post-it `#e8d98a` · mug `#c98b52` ·
can `#7b9aa8` · curtain `#d8cfc0` · plant `#a8845c`, on physical objects
only. Ink `#232326`, red `#ff5247`, green `#2fd576` for an up move alone.
The plant is brown because it is dying, which keeps green meaning one thing.

## Two notes for the renderer

`loop-plant` and `loop-curtain` **replace** the plate's drawn plant and
curtain — they do not overlay, or you get a doubled outline. `loop-steam`,
`loop-cursor` and `loop-second-hand` are purely additive.

Light overlays multiply over a room plate and sit **below** anything code
draws, so numbers and charts are never tinted.

## One open question

The light overlays are boiled, three frames each. They are wash layers rather
than ink, so the boil adds nothing visually and triples their weight — they are
the heaviest files here at ~4.4MB a frame. The manifest declared it, so that is
what was baked; say the word and they become single static frames.
