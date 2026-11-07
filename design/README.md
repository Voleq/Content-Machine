# Standalone paper plates, ready for an adapter review

**203 concepts / 415 layouts**, all on the bot's warm paper ground. The original
188 concepts / 376 layouts contain 63 text-only and 125 numeric concepts.
Round 3 adds 15 concepts / 39 layouts and extends the existing tripwires plate.
The implosion group comes first, then the stock-long group and question card.
See [LONGS.md](LONGS.md) for the new source, drawer and motion contracts. Each concept has
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

Pillow and openpyxl are already in `requirements.lock.txt`. There are **no new dependencies**:
no Node, resvg, FFmpeg, FontTools, jsonschema or vendored font copies are needed
for this build. Type fit is measured with the actual files under `assets/fonts/`,
including Archivo Narrow's declared variable weight.

For optional, portable review pages and filled research examples:

```sh
python design/build_all.py --out /tmp/dennis-review --ground paper --scale 2 --review
```

Open `/tmp/dennis-review/review/index.html`. The small paginated pages embed their
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

- [catalog.json](catalog.json) owns the original 188 concepts, source examples, workbook
  input models, curation and motion selections. Families are `investigations`,
  `finance`, `stock`, `charts` and `chapters`; no volume or library IDs survive.
- [longs.json](longs.json) owns the 15 Round 3 concepts, including the six
  mechanism variants and missing 16:9 press release. `--only part-1`,
  `--only part-2`, `--only part-3` and `--only round3` build focused deliveries.
- [core.py](core.py) and [drawings/](drawings/) declare geometry and text slots.
  They never load fonts, write files or invoke a subprocess.
- [data.py](data.py) draws each numeric recipe from declared workbook slots.
  `draw(region, numbers, inks)` returns `rect`, `circle` and `path` dictionaries
  accepted by `pipeline.series.paint()`. `labels()` computes the matching ticks,
  periods, values and positions. Both are pure Python and perform no I/O.
  Existing `line_path`, `column_bars` and `spread_fill` are reused where their
  geometry fits; `data-area.uses` names them.
- [sources.py](sources.py) resolves each catalogue input's authored unit and
  workbook row/period or filing location. [workbook.py](workbook.py) checks
  those references against `templates/dennis_data_template.xlsx` at build time.
- [contracts.py](contracts.py) builds a writer menu and a flat `[PLATE: ...]`
  example **from the emitted manifest alone**. `prepare()` validates the written
  slot values and returns shapes, visible strings and dynamic label boxes.
- [kit-motion.json](kit-motion.json) proposes motion for **52 existing kit
  plates / 104 layouts** using their published slot names. It never redraws
  those plates or reaches into `kit/engine/`.

Every word is a slot, including fixed labels, units, dates, years, legends and
chapter display labels. Fixed words may have editable defaults. The brand line
and template counter are removed. Numeric inputs are script strings such as
`$125m` and `12.5%`, with a per-slot source/period note, source unit and length
limit. Source controls are data inputs and are never typeset into their 0×0
boxes. Calculated labels come from those same inputs; the writer supplies no
geometry, formulas, normalized positions or timing.

Input notes start with a real reference such as `History!capex, FY-4` or
`Snapshot!price, as-of`. A figure outside that workbook starts with
`From the filing:` and names the relevant note/table and period; it explicitly
cannot be confirmed by a workbook row. Assumptions and supplied market-data
exhibits are identified as such. Annual series use distinct fiscal years;
they do not silently append an overlapping LTM observation.

The renderer accepts the bot reader's whole-unit amounts. For `money_m`,
`1200000000`, `1,200,000,000` and `$1.2bn` all mean `$1,200m`. A bare `120`
means $120, so a figure copied from a filing table in millions needs `120m`.
`shares_m` likewise accepts whole shares or `50m`. Per-share money, percentages,
multiples and counts have their own declared units. Unit labels are calculated
outputs, absent from the writer menu; the reporting-label input cannot override
them. Cash outflows used as spending magnitudes are normalized explicitly.
Non-zero money/share inputs that would round to zero at the plate's precision
are rejected before drawing. The error identifies the input and asks for `m`
or `bn` when transcribing a filing table in millions or billions. An explicit
suffix does not bypass the precision check. Actual zero inputs remain valid
where the model permits them, as do zero results such as profit minus equal cash.

All concepts publish `sectors: []`; their source/caution notes determine fit.
Type slots share semantic kit roles, including `caption`, `value`, `label`,
`tick`, `legend`, `unit` and `period`, with per-slot ink overrides and text budgets.

**121 original standalone concepts** have 4–6 ordered motion steps. Round 3
uses 3–6 ideas, with the requested two-idea exception for the question card.
The 52 existing-kit
proposals use 2–6: compact quotes and closing cards need fewer ideas. Chart
furniture appears with its data area, and related labels/figures share a step
through `includeSlots`. Only `cueSlot` names words intended to be spoken;
an uncued context reveal follows the preceding idea. All 16 published native
`line-draw` anchors and all 13 `highlight` anchors are used. `count-up` is listed
as an optional, disabled proposal for Valentin, requiring a numeric fill.
These recipes have no seconds, frame counts, FPS, fades or partial opacity.

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
