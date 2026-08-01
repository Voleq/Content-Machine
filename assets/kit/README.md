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
