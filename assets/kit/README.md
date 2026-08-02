# The design kit

`kit-registry.json` is the single source of truth. Nothing here is discovered
by walking the filesystem: a PNG with no registry entry does not exist, and
`Kit.verify()` (and `/kit doctor`) fails the build when one turns up.

**387 assets · 597 frames · 74 text slots · 84 multi-frame.**

## The contract

| Field | Meaning |
|---|---|
| key | `family/asset` — the only way anything here is addressed |
| `frames` | ordered, relative to the entry's root (`assets/kit/` or `assets/kit/shorts/`) |
| `frameCount` / `fps` | read by the player; never hardcoded anywhere |
| `playback` | `static` · `boil` (2-frame wobble, ~6fps) · `one-shot` (play once, hold last) · `loop` |
| `canvas` | the coordinate space slot boxes are authored in |
| `exportScale` | the PNGs are this many times the canvas. **2** on the whole shorts batch |
| `aspect` | `16:9` · `1:1` · `9:16` |
| `slots` | declared text boxes with `align` / `valign` / `font`, in **canvas** coords |
| `slotFrameDelta` | how the slot boxes move per frame index, and where they wrap |
| `aliasOf` | this key is a second name for one drawing; it resolves through |
| `deadMouthFlap` | a `-talk` twin identical to its base — artwork owed |

Two of these are silent when missed, which is why the code never leaves them
to a call site:

* **`exportScale`** — a slot box composited without it puts every figure at
  exactly half its intended position, on a drawing that still looks fine.
* **`slotFrameDelta`** — only `shorts/dennis-vs-numbers/numbers-raining` has
  one. Ignore it and the figures hang in the air while the rain falls past
  them.

## Re-ingesting a delivery

```
python scripts/ingest_kit.py path/to/dennis-assets-min
python scripts/restyle_dark_cards.py
```

The ingest **deletes `assets/kit/` and writes it fresh**. There is no merge
mode: merging is what left dark-theme leftovers resolvable last time.

### One command lands a delivery

```
python scripts/ingest_kit.py <delivery-dir> [<more-dirs>...]
```

That is the whole procedure, and its output decides whether to commit. It
takes **several source directories**, so a batch that arrives on its own does
not have to be copied into the main delivery first.

* **A family that ships its own `manifest.json` registers itself.** Every
  `manifest.json` under any source is merged into the registry, keyed by the
  manifest's own `family` field rather than the folder it sits in — the
  commissioned `stings/` arrived nested three deep and still had to register
  as `stings/<name>`. A family the top-level `kit-registry.json` already
  indexes is left to it, so re-registering the delivery's own shorts batch
  under unprefixed keys cannot happen.
* **Palette-mode source PNGs are refused, by name.** Palette is a size
  optimisation that hard-quantises the antialiased edges the kit is drawn
  with, and the line work IS the artwork here; it only ever surfaced as a
  Pillow transparency warning at render time. `--allow-palette` proceeds
  anyway and marks the run LOSSY, for working on a repo while a full-RGBA
  re-export is outstanding.
* **The dark cards are relit automatically**, then `--check`ed, so a
  re-ingest cannot restore the dark closing cards. It used to be a separate
  command somebody had to remember.
* **It ends with a verification block** — assets, frames on disk, families,
  aliases collapsed, anything not ingested, and `Kit.verify()`. A non-empty
  `verify()` exits non-zero and says DO NOT COMMIT.

### The three blank layouts are NOT in the delivery

`big-number-blank`, `term-card-blank` and `quote-pull-blank` came from the 2024
kit. `dennis-assets.zip` contains no `type/callouts/`, no `type/quotes/` and no
file with `blank` in the name — **the copies in `assets/kit/blanks/` are the
last ones that exist.** They are artwork we are owed; until Design ships them
in a delivery this repo is the only source.

The ingest reads them out of `assets/kit/blanks/` before it deletes anything
and writes them back afterwards, so an ordinary re-ingest carries them forward
with no staging at all. If they are genuinely absent it **refuses** (exit 2)
rather than proceeding — an earlier version deleted them first and printed one
line to stderr, which would have destroyed them permanently. To recover:

```
git checkout HEAD -- assets/kit/blanks/       # from this repo's history
```

or stage a previous kit export at `assets/_kit_previous/` carrying
`type/callouts/big-number-blank.png`, `type/callouts/term-card-blank.png` and
`type/quotes/pull-blank.png`.

### The chapter cards carry long-form furniture

The 138 16:9 `chapters/` cards were drawn to BE the long-form frame, so each
one has the frame's furniture painted into the PNG: a ticker chip at
`(73, 78)` and the `Opinion / entertainment. Not financial advice.` line at
`(73, 818)`, both on the 1600x900 canvas. The chip's copy is the design file's
placeholder — `GYMX ▼ 34%`.

A short composites those cards over a 9:16 frame that draws both itself, so
they arrive as a duplicated disclaimer and a **second, wrong ticker**: `$EXMPL`
in our chip and `GYMX ▼ 34%` in theirs, on screen together in the bookends of
every video. **What we are owed is the same cards without the furniture** — it
belongs to the frame, not to the drawing.

Until then `kit_frames.strip_baked_furniture()` erases it, and it is
deliberately timid: a card is only touched when the ink in the band matches
the known geometry *and* has the clear paper beside it that the furniture
always has. A blanket crop of the same bands was measured against the library
first and would have damaged 32 cards at the top and 75 at the bottom — legs,
chart axes and table rules all cross there. 64 of 138 cards come out clean;
the other 74 keep their furniture rather than risk the artwork.

One card is broken as delivered: `chapters/sector-comps/comps-table` prints
its `Median` row directly on top of the disclaimer, overlapping glyph for
glyph. Nothing can separate them, so stripping the disclaimer takes `Median`
with it. It needs redrawing.

`scripts/audit_placement.py` walks every asset through both engines' real
placement maths and reports coverage, empty slots and clipping. Run it after
a delivery.

### The delivery on disk is size-optimised

`dennis-assets-min` is the only archive there is, and **798 of its 846 frames
are palette-mode PNGs** — measured, not assumed. The ingest refuses it without
`--allow-palette`, which is the right refusal: the kit is line art, and
palette quantisation lands on exactly the antialiased edges that line art is
made of.

**A full-RGBA re-export is artwork we are owed.** Until it arrives the kit on
disk is the lossy version, and every ingest of it prints `fidelity : LOSSY`.
The `stings/` batch is the counter-example — it shipped full RGBA and passes
the check without the flag.

### Transitions ship in both orientations

`stings/` is 11 six-frame one-shots: 8 at 16:9 and `paper-slide-tall`,
`page-turn-tall`, `torn-edge-tall` at 9:16. `transition_asset()` picks by
**aspect**: a 9:16 short draws only from the tall strips, a 16:9 long only
from the wide ones, and a `-tall` variant replaces its wide twin rather than
competing with it. Falling back to the other orientation is logged, because
it means a strip is missing rather than that the cut is fine.

A 16:9 strip cover-fitted into 9:16 keeps 32% of its width. That is measured
per strip (`cover_keeps_fraction`) and logged whenever it happens, and a strip
whose action does not fill the crop window is contained onto paper instead —
a transition that crops its own action out is worse than the white flash it
replaced.

### A card is a whole frame; a two-shot needs a cut-out

Every `chapters/` card is a complete 16:9 composition — Dennis, a headline,
often its own illustration. They are right when they ARE the frame and wrong
as an inset: pasting one beside a piece of evidence puts two finished designs
in one frame, both with their own background and their own headline.

So the two-shot uses the `mascot/` poses instead — 1:1, 98% transparent, no
background and no copy. **Whole figures only**: `arm-*`, `face-*`, `mouth-*`
and `layer-*` are components of the old layer rig, and `arm-gesture` in that
list stood a pair of disembodied arms next to the evidence.

The long two-shot is composed as one still — paper, the evidence, the figure
standing on the floor line beside it. Never a designed backdrop underneath:
those carry their own giant ticker and grid, and a third design in the frame
is what made the cut read as a collage.

It copies only what the registry lists as a frame. Contact sheets, index
sheets and probes stay in the archive — they are for humans, and they were
previously sitting in the asset folders with ordinary names where any
glob-based loader picked them up. An orphan like `press/podium-ceo_b.png`,
whose base had moved families, is left behind rather than shipped as an asset
nothing can address.

It also refuses a path that `git checkout` cannot create on Windows, which is
what `restyle/con/` did — silently, taking eighteen frames with it, while the
Linux tree still looked clean.

### What the ingest changes, and why

* **Fifteen duplicate groups collapse.** The same drawings shipped under
  `mascot/` and `restyled/` names. Left alone the variant picker treated them
  as distinct options, so "pick a different reaction" could return the
  identical frame — 25 fake reactions where there are 10. The others become
  aliases and are hidden from `Kit.family()`.
* **`numbers-raining`'s `slotFrameDelta.y` is corrected.** The delivery
  carried `118` against a note saying per-frame; the drops measure 19.9 ± 0.7
  canvas px per frame across 150 box tops, so `118` is the travel over the
  whole six-frame cycle. Applied on every ingest so a fresh delivery cannot
  reintroduce it.
* **Three blank layouts are carried forward** from the 2024 kit —
  `big-number-blank`, `term-card-blank`, `quote-pull-blank`. They are the only
  assets in either kit designed to take arbitrary text and nothing had ever
  filled one. Their slot geometry is measured off the placeholder copy, and
  their slots set `clear` so the placeholder is painted back to paper before
  the real value goes down.
* **Seven dark cards are restyled** to the light palette by
  `scripts/restyle_dark_cards.py` — five `resigned-close` frames plus
  `short/card-noise`. They are the closing card, the subscribe card, the
  disclaimer and the end screen, so every video used to close by switching
  theme. The script is idempotent and `--check` fails if a dark one comes
  back.

## Palette

paper `#f2f2ef` · floor `#dbd4c8` · ink `#232326` · red `#ff5247` ·
green `#2fd576` (**up only**) · grey `#8f8c83`

Numbers are set in Space Mono 700, display text in Shantell Sans 800.

## Don't

**Don't Ken Burns any of this.** The motion is in the frames — 84 assets are
real sequences — and drift on top of a registered strip makes the registration
itself look broken.

**Don't re-fit per frame.** Every frame of a strip shares one canvas and one
top-left registration point. Scale the asset as a whole or it will drift.
