# Long-video plate proposals

These records extend the source-only delivery. They do not register chapter
types, feeds, renderers, moves or plates in the bot. The production kit and
workbook are untouched. All filled examples are illustrative fixtures.

```sh
python design/build_all.py --out /tmp/implosion --only part-1 --review
python design/build_all.py --out /tmp/long-proposals --only round3 --review
.venv/bin/python -m pytest tests/test_long_plates.py
```

`longs.json` is the catalogue. `longs.py` compiles its native canvas slots and
contains pure validation/drawing. The delivery retains the existing kit-shaped
family manifests, 2x PNGs, semantic inks, shared type roles, hashes and curation
fragment. The new vocabulary lives in this proposal catalogue, outside kit roles.

Every word is a slot. No new plate has a source footer. The press release's
`source` slot is its agency heading; its existing 9:16 kit counterpart is reused,
and this pack supplies only the missing 16:9 half.

Use `contracts.writer_menu`, `example_fill` and `prepare` for both generations.
The helpers recognize `longRecipe` entries without production registration.
Writer values remain flat strings. Hidden feed tables use semicolon-separated
CSV rows; the field's `columns` declares each column's real unit. Runtime callers
may also supply table rows as lists. No drawer fetches anything from a network.
Raw money inputs can use whole amounts or explicit `m`/`bn`; a non-zero amount
that rounds to zero is rejected before drawing. The formatted output has its
own character budget, separate from the longer source representation.

Real observations use `workbook`, `filing`, `document` or `feed` provenance.
Document notes start `From a document sentence:`; feed notes name `feed price`,
`feed form4`, `feed fred`, `feed edgar` or `feed web_shots`. Manual layout controls
and expressly fictional toy amounts have `factCheck: false`, rather than an
invented evidence source. The checklist publishes workbook/document alternatives.
`History!accounts_receivable` is marked pending because the bot's parallel work
adds it; it is not claimed to exist in the current workbook.

Each region's `design.longs.draw(region, inputs, inks)` returns only paintable
rect/circle/path nodes. `labels` supplies computed positions and labels. A
composite region publishes `children`: its static drawing includes those parts,
while motion targets individual parts to reveal pins or ladder rows in order.
Do not paint both a composite and its children into a static frame. `prepare`
already returns the complete body once, along with visible `values`, dynamic
`boxes`, resolved `units` and semantic `colours`.

Motion steps are ideas; `includeSlots` shares their reveal. Within an idea,
`effects` can count a figure and highlight its mark on their own spoken cues.
The motion targets and `motionAnchors` are published slot boxes, never engine
internals. Runtime `prepare` returns fresh motion and anchors when row count,
checkpoints, the stop step or a selected trade changes. Context and chart
furniture have no spoken cues. All moves are existing kit moves except
`clock-run`, which is explicitly left for the bot's player to implement.

`clock-run` names its start/end time slots and documented target total. Its
counter is continuous between checkpoints and rests only on documented values.
One final checkpoint requires an `over N minutes` caption. No intermediate
losses are invented. The pure `clock_face` drawer accepts the exact time.

The toy table requires EXAMPLE or TOY NUMBERS and verifies every running total.
Its manifest tells the future fact-check adapter to skip only on that required
tag. Legal statuses are enumerated, and an untried settlement leaves TRIED hollow.
