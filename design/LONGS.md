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
Feed tables are `sourceManaged`: they are omitted from the writer's menu and
PLATE-tag example. The bot's feed resolver supplies them alongside the writer
values before `prepare` or `draw`. `example_fill` includes illustrative feed
tables solely to make the complete review fixture reproducible; runtime code
never substitutes those examples when a feed is missing.
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
losses are invented. `cueAt: checkpoint-end` aligns the documented arrival with
the words that reach that figure; the live counter is hidden before the run.
The pure `clock_face` drawer accepts the exact time.

The toy table requires EXAMPLE or TOY NUMBERS and verifies every running total.
Its manifest tells the future fact-check adapter to skip only on that required
tag. Legal statuses are enumerated, and an untried settlement leaves TRIED hollow.

## Stock-long additions

Part 2 adds the promise ledger, insider trades, stock versus driver, public
claim versus dated check, and historical precedent paths. It extends the existing
`finance/thesis-tripwires` instead of adding a duplicate concept.

The promise ledger has four rows in 16:9 and three in 9:16. Its field_key,
sheet and period controls resolve the result's real unit and workbook source;
`prepare.sources` returns the resolved provenance. A vague undated promise is
only DROPPED after a later-call disappearance check. Promises are verbatim quotes.

Insider data retains only P/S transactions. Planned and tax-related open-market
sales are quiet; grants and withholding codes are not counted. Totals cover the
calendar twelve months ending on the last fetched price date, with distinct
people counts. A small real feed total remains dollars rather than printing
zero million. Trade-focus circles use an actual plotted trade, never a fabricated
date or an inferred price through a hole in the feed.

Stock versus driver uses dates present in both feeds, a shared base of 100 and
one y-axis. Its native `spread_fill` is translated to the exact line scale.
The precedent aligns each company's actual event-day close and stops at each
path's own final observation. A requested result beyond past coverage is refused.

Public checks require both a page name and a valid ISO date. The plate carries
only words and optional figures; the screenshot remains a separate WEB shot.
Tripwire limits and the new 16-character review dates are explicitly unchecked
writer assumptions. All three current tripwire figures retain workbook sources,
including the declared same-period cash-conversion/revenue-growth calculations.

## The recurring question

Part 3 is `cards/question-card`, available to all 28 current chapter types. It
has only the question and optional kicker on paper: no answer, figure, source
line or other furniture. Its large shared `big` type is vertically and
horizontally centered, limited to three lines in 16:9 and five in 9:16.
The optional hidden `stress-words` control must be an actual substring; otherwise
the first content word is selected. The second of two motion ideas publishes
that character range for the existing highlight move and spoken alignment.

## Watching the motion

After a delivery build, run `python design/build_motion_preview.py --delivery
/tmp/long-proposals` and open its `motion/index.html`. The separate, portable
review player reads the delivered recipes, shapes and slots; it does not change
the production manifests or install a bot player. Its clock hands and running
total move together, and pause/seek land only at checkpoint totals. All other
published moves are playable, including highlights on exact question words.
The examples and preview durations are illustrative. Voice timing and the
production `clock-run` implementation remain bot-side work.

With Playwright and Chromium installed, `python design/check_motion_preview.py
--delivery /tmp/long-proposals --chromium /usr/bin/chromium` checks every preview
in the browser, including intermediate geometry, replay, mobile layout and
offline playback.
