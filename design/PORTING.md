# Porting review changes

The source-only delivery addresses the ten format changes in the supplied review.
It remains separate from the production bot.

## Round 2

| Review item | Delivery change |
| --- | --- |
| Workbook provenance | Every numeric input model has authored metadata. Emitted notes name a genuine `History!field_key`, `Quarters!field_key` or `Snapshot!field_key` and the requested period. The build validates these against the actual workbook. Unavailable figures instead name the filing note/table and period, with an explicit fact-check limitation. |
| Units | Money, share counts, percentages and other quantities have declared units. Whole-unit workbook amounts and explicit written magnitudes normalize to the same model basis. Unit labels are calculated outputs; the writer edits only a separate reporting label. |
| Sectors | All 188 concepts are generic and emit `sectors: []`. No artificial full-sector restriction remains. |
| Spoken motion | Standalone recipes use 4–6 ideas; kit recipes use 2–6. Furniture is grouped with the data reveal. Cues target headlines, figures and narrative conclusions, never ticks, units or legends. All 16 native line-draw and 13 highlight anchors are used. Count-up remains disabled for Valentin. |
| Shared typography | Slots use semantic kit roles, sharing font/size behavior while retaining per-slot text limits and ink overrides. |

| Review item | Delivery change |
| --- | --- |
| Text in blanks | Geometry-only PNGs; every visible word is a declared slot. Branding and template counters are removed. |
| Mixed grounds | All 188 concepts build on `plateInk.paper`; `--ground paper` is explicit. |
| Per-video Node data rendering | All 125 numeric concepts have pure Python shape/label recipes; native series helpers are reused. |
| Baked motion | Ordered slot/region recipes, without seconds, FPS, frames or pixels; spoken-slot cues remain for the future player. |
| Manifest variants | Five family manifests use the kit's `plates` table, slots, `typeRoles`, file hashes and 2× export conventions. |
| Writer data contract | Workbook strings are declared source slots with notes/units/limits; menu and fill helpers read only the manifest. |
| Binary history | Source-only replacement branch; media retained in a separate archive. Generated outputs and legacy review folders are ignored. |
| Build entry points/dependencies | One `build_all.py` command; existing Pillow and repo fonts, with no new dependencies. |
| Kit internals/slot aliases | 104 existing-kit motion recipes checked against published manifests, without engine imports or slot aliases. |
| Duplicate concepts | One catalogue record per concept; motion attaches to that key rather than creating another pack entry. |

## Numeric integration contract

A `data-area` region publishes its renderer, label renderer, immutable model
recipe and `inputSlots`. Each input is a named manifest slot, with a workbook
or filing source/period note, structured `source`, a declared `sourceUnit` and
`maxChars`. Numeric observations always use non-typeset source controls,
separate from their formatted visible labels. A text observation can reuse its
visible slot when the wording matches. Every observation must be
supplied. The renderer never falls back to a sample workbook number.

The future writer-menu adapter should use `contracts.writer_slots(entry)`.
That exposes source controls and prose, while leaving computed labels to the
renderer. `contracts.script_example(entry)` shows the exact `[PLATE]` syntax.
No separate fill scripts, schemas, LLM guides or Node processes are needed.

At render time, `contracts.prepare(entry, written_slots, inks)` validates those
strings and returns three things: plain shape nodes, visible slot values, and
boxes for labels whose position depends on the data. Send the nodes to
`series.paint()` and the visible values/boxes to the bot's ordinary type renderer.
The writer retains control of the chapter display label and prose. Input-only
controls must not be typeset, and a writer cannot replace a computed number
independently of its source inputs.

`sourceUnit: money_m` uses millions internally, but a bare numeric input is a
whole-unit amount, matching the bot workbook reader. `1200000000` and `$1.2bn`
both become 1200 in that model. Use `120m` when transcribing a filing's table
value of 120 million. Shares follow the same rule. Per-share money stays in
dollars and percentages use percentage points. Inputs marked
`sourceSign: outflow-magnitude` accept negative cash-flow amounts and draw
positive spending. The rare `modelScale` is explicit (for example percentage
points to a fraction). These conversions are metadata, not writer-supplied formulas.

Before any geometry is constructed, money and share inputs are checked at the
plate's display precision. A non-zero amount that would become zero fails with
the input name and an instruction to add `m` or `bn` for a filing table in
millions or billions. This applies to `draw()`, `labels()` and `prepare()`,
including signed inputs, nested series and explicit but still invisible amounts.
Real zero inputs and zero arithmetic results are preserved. The restatement
plate's EPS inputs use dollars, independently of its revenue/profit totals in millions.

Unit-bearing slots have `unitLabel: true`, no editable default, and no writer
input. A separate `input-period` carries the reporting label without units;
the label renderer adds the appropriate unit summary. Other axes and unit
annotations are computed from the immutable declared-unit model.

The same input values drive marks and displayed numbers. Unit mismatches,
missing/unknown inputs, non-finite values, invalid model bounds and an
unreconciled roll-forward fail before output. A null structural cohort cell
remains unavailable, not zero. The data area owns its axes, scales, data, ticks
and calculated labels, keeping all changing numbers out of the blank PNG.

The immutable recipe contains the authored model/constraints and native layout
box. A caller can place or resize the published region in canvas units; the
writer cannot supply geometry. Shapes use named inks supplied by the caller,
with paper contours and full opacity.

## Motion integration contract

Standalone motion is attached to each emitted plate; existing-kit motion is
in `kit-motion.json`. Both contain ordered steps with a published `slot`, an
`action` or native `move`, an optional direction and an optional `cueSlot`.
`includeSlots` names the other slots revealed with that idea. It does not apply
the primary region's clip to unrelated text boxes. A cue refers only to words
the narration actually says; uncued context follows the preceding idea. The director
and voice alignment choose when each step lands. Recipes have no fixed duration
or frame-rate requirement. The published native move catalogue is unchanged.

Native kit recipes only refer to `kit/*/manifest.json` keys and slot names.
They contain no geometry aliases, engine snapshots, palette overrides or
pre-rendered kit frames. Native moves must have an anchor for the exact slot in
`kit/emit/motion.json` under `anchors.plates`; companion `also` regions are
grouped with it. Missing published slots or move anchors fail validation.
`optionalMoves` is separate from executable steps. All 104 published count-up
anchors are recorded there with `enabled: false`, `decisionBy: Valentin` and
`requiresNumericValue: true`; text targets must never be counted blindly.

## Validation boundary

The new tests cover every concept/aspect, actual font fit, text-free/data-free
blanks, pure rendering with file/font/image/subprocess access blocked, input
immutability, unit parsing, independent financial examples, slot-based motion,
4K raster dimensions/hashes, repeatable CLI output and the existing kit table
parser. Round 2 adds workbook-schema validation, whole-unit money/share
equivalence across every numeric model, read-only units, period/sign semantics,
semantic type-role sharing, grouped furniture, exact native move anchors and
Python 3.11 parsing. The production render-path engine prohibition is also checked.

Reading the kit table shape is not registration. The production ingest's
family allowlist, writer menu, data dispatcher and motion player remain
unchanged until integration is separately requested.
