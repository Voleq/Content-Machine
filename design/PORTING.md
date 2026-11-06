# Porting review changes

The source-only delivery addresses the ten format changes in the supplied review.
It remains separate from the production bot.

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
source/period note, a declared source unit and `maxChars`. An input already
printed by the plate reuses its visible slot when the units and value match;
other observations use non-typeset source controls. Every observation must be
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
`action` or native `move`, an optional direction and a `cueSlot`. The director
and voice alignment choose when each step lands. Recipes have no fixed duration
or frame-rate requirement. The published native move catalogue is unchanged.

Native kit recipes only refer to `kit/*/manifest.json` keys and slot names.
They contain no geometry aliases, engine snapshots, palette overrides or
pre-rendered kit frames. Missing published slots fail validation.

## Validation boundary

The new tests cover every concept/aspect, actual font fit, text-free/data-free
blanks, pure rendering with file/font/image/subprocess access blocked, input
immutability, unit parsing, independent financial examples, slot-based motion,
4K raster dimensions/hashes, repeatable CLI output and the existing kit table
parser. The production render-path engine prohibition is also checked.

Reading the kit table shape is not registration. The production ingest's
family allowlist, writer menu, data dispatcher and motion player remain
unchanged until integration is separately requested.
