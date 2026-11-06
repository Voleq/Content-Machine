# Standalone paper plates, ready for an adapter review

**188 concepts / 376 layouts**, all on the bot's warm paper ground. The delivery
contains **63 text-only concepts** and **125 numeric concepts**. Each concept has
one canonical key and one source record, with motion attached where available.
Nothing is registered with the bot or installed into `assets/plates/`.

Build the complete delivery with the existing Python environment:

```sh
python design/build_all.py --out /tmp/dennis-delivery --ground paper --scale 2
```

The command writes only PNGs and JSON files under `--out`. It builds native
1920×1080 and 1080×1920 layouts and delivers them at 3840×2160 and 2160×3840.
Each family gets the kit's `plates` manifest shape, text-free blanks, hashes,
slot dictionaries, ink-role type tables and curation notes. Root JSON files
summarize the delivery and include the role fragment and existing-kit motions.
Night and dusk reuse the same paper drawing.

Pillow is already in `requirements.lock.txt`. There are **no new dependencies**:
no Node, resvg, FFmpeg, FontTools, jsonschema or vendored font copies are needed
for this build. Type fit is measured with the actual files under `assets/fonts/`,
including Archivo Narrow's declared variable weight.

For optional, portable review pages and filled research examples:

```sh
python design/build_all.py --out /tmp/dennis-review --ground paper --scale 2 --review
```

Open `/tmp/dennis-review/review/index.html`. The sixteen small pages embed their
images and need no JavaScript, fonts or adjacent image files. Page navigation
and full-size downloads use the files beside each page. Review output stays
under `--out`, outside Git. The earlier galleries, PDFs and clips are retained
in the separate review archive supplied with this task.

Validate without generating files, or build a single concept/family:

```sh
python design/build_all.py --out /tmp/check-only --check
python design/build_all.py --out /tmp/one-plate --only investigations/profit-vs-cash
python design/build_all.py --out /tmp/chapter-review --only chapters --review
.venv/bin/python -m pytest -q tests/test_design_delivery.py
```

## Sources and contracts

- [catalog.json](catalog.json) owns all 188 concepts, source examples, workbook
  input models, curation and motion selections. Families are `investigations`,
  `finance`, `stock`, `charts` and `chapters`; no volume or library IDs survive.
- [core.py](core.py) and [drawings/](drawings/) declare geometry and text slots.
  They never load fonts, write files or invoke a subprocess.
- [data.py](data.py) draws each numeric recipe from declared workbook slots.
  `draw(region, numbers, inks)` returns `rect`, `circle` and `path` dictionaries
  accepted by `pipeline.series.paint()`. `labels()` computes the matching ticks,
  periods, values and positions. Both are pure Python and perform no I/O.
  Existing `line_path`, `column_bars` and `spread_fill` are reused where their
  geometry fits; `data-area.uses` names them.
- [contracts.py](contracts.py) builds a writer menu and a flat `[PLATE: ...]`
  example **from the emitted manifest alone**. `prepare()` validates the written
  slot values and returns shapes, visible strings and dynamic label boxes.
- [kit-motion.json](kit-motion.json) proposes motion for **52 existing kit
  plates / 104 layouts** using their published slot names. It never redraws
  those plates or reaches into `kit/engine/`.

Every word is a slot, including fixed labels, units, dates, years, legends and
chapter display labels. Fixed words may have editable defaults. The brand line
and template counter are removed. Numeric inputs are script strings such as
`$125m` and `12.5%`, with a per-slot workbook/period note, source unit and length
limit. Source controls are data inputs and are never typeset into their 0×0
boxes. Calculated labels come from those same inputs; the writer supplies no
geometry, formulas, normalized positions or timing.

**120 standalone concepts** have ordered motion steps. Together with the
52 existing-kit proposals, these are recipes over slots and regions, not video
assets. Steps appear, draw or clip into view, with compatible native move IDs
where applicable. There are no seconds, frame counts, FPS, fades or partial
opacity in motion recipes. The future player can align them to spoken words
and to the actual beat length.

## Integration boundary

These are **unwired source proposals**, not a drop-in registry installation.
The manifests use the kit table format and are checked with its table reader.
Production ingest still has an explicit family list; custom data and motion
recipes are deliberately unregistered. A later adapter can register the new
families, retain the `data-area.recipe`, include its `inputSlots` in the writer
menu, call `contracts.prepare()` and paint its results using the existing bot
renderers. No changes to the production writer, parser, fact-checker, registry,
shot selection, moves or render path are made here.

The branch contains sources only. Generated PNGs, galleries, PDFs, clips and font
copies are absent from its commit history. Its earlier media commits were
replaced from the original base; review files remain in the external archive.
