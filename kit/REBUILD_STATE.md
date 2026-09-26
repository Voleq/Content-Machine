# Dennis v2 — REBUILD_STATE.md

> ## rebuild-39 — stamp move removed (user call)
> `stamp` is gone from `motion.js` (MOVES, stampScale, anchorFor), from `emit/motion.json` (moves and all 573 anchor sets) and from Motion Review. 13 moves remain. Older notes below that mention the stamp are history.

> ## rebuild-38 — multi-line text and motion anchors
>
> **Multi-line text: where it broke.** `content.js budgetOf()` capped every slot at its published
> `maxChars`, which is the ONE-line figure, even where the slot wraps. Legacy multi-line slots
> (755 of them) publish no `maxChars` and were fine. The 17 round-five slots that wrap were cut to
> one line. These are risk-factor lines, the footnote quote and the marked sentence, the bumper
> title, and the short-number context.
> - The cap is now `maxCharsPerLine × lines` where the slot wraps.
> - Round five's multi-line roles now carry `maxLines` and `maxCharsPerLine`, via `ml()` in
>   `plates-r5.js`.
> - The full-length footnote quote and risk line are restored, and all 134 round-five plates fit
>   uncut. Audit 30 of 30.
>
> **Motion anchors.** Nothing is placed by eye now:
> - `motion.anchorFor(manifest)` reads where each move lands from the plate's own slots:
>   - count-up and pen-circle go on the callout figure (X with X-label and X-detail), then
>     `num`/`delta`, then the biggest one-line slot;
>   - stamp and line-draw go on the plot area;
>   - highlight and zoom go on the underline, quote or marked slot;
>   - tick-over goes on `num`.
> - It is published for all 573 plates in `emit/motion.json → anchors`. `null` means skip the move.
> - `inkBox()` shrinks a slot box to the text's ink, so the circle rings the figure.
> - `pinSpot(room)` puts the new card over the union of that wall's existing cards.
> - Motion Review shows pen-circle and stamp on three different plates each, and card-pin on both
>   board angles.

> ## rebuild-37 — housekeeping
>
> - `content.js`: for a round-five type, any text slot the copy does not fill is now `''`, not
>   generic sample copy. Container, region, band and marker slots are untouched. Audit 30 of 30.
> - `/New Shapes Review.dc.html` groups all round-five plates (shapes, banks, macro, sectors,
>   said, six, furniture, shorts, wipes, variants). Variants can be filtered by sector, and the
>   9:16-only shorts now show.
> - **Still open, needing a decision:**
>   - The fitter (`sized()`/`fit()`) fits every slot as ONE line, and `maxLines` is ignored.
>     Multi-line quotes use line slots as a workaround.
>   - The motion demos place the pen circle, stamp and pinned card by eye. Publishing an anchor
>     slot per plate would make them exact.

> ## rebuild-36 — sector variants of the round-five shapes
>
> Through the kit's own scripts: `emit.js` **414 assets · 1,386 plate records · 573 slot tables**;
> `export.js --index` **5,088 files**; `audit.js --check` **30 of 30**. Every copy string on all
> 134 round-five plates fits uncut.
>
> **30 new types, 60 plates**, in `copy-r5.js`, each gated by `sectors`:
> - **Valuation against its own history, ×10:** each sector on the multiple it is priced on.
>   - EV/EBITDA for energy, materials, media and retail.
>   - Forward P/E for utilities, health care and staples.
>   - P/FFO for REITs, P/TBV for banks, and P/B for insurers.
> - **Small multiples, ×4:** basins (energy), customer classes (utilities), property types (REIT),
>   and six drugs (health care).
> - **Earnings against cash, ×4:** software (share pay), industrials (working capital), health care,
>   and REIT (non-cash writedowns).
> - **Segment margin grid, ×4:** media, staples, health care and materials.
> - **Guidance range, ×4:** energy output, utility EPS, retail revenue and health-care revenue.
> - **Macro driver, ×4:** oil to producer cash, gas to utility fuel cost, bond yields to REIT NAV,
>   and the euro to staples growth.
>
> The series come from a seeded walk, so they are deterministic. Ranges, averages, records and
> accruals are still derived. There are four new fictional issuers: **Ashby** (energy), **Norland**
> (utilities), **Calder** (real estate) and **Vireo** (health care).
>
> **Not reviewed by eye.** The shapes were built before sign-off, as asked. The sample numbers are
> plausible, not researched.

> ## rebuild-35 — motion moves
>
> **`engine/motion.js`** plus **`emit/motion.json`** make up a catalogue of 14 moves at 12 fps. They are
> published as DATA, not baked frames. Each move names what it applies to, its frames, its easing and
> whether it plays once or loops, and `motion.js` exports the pure per-frame function. A renderer
> plays a move OVER a plate's published slots. The plates stay stills, so no audit or asset count
> changed.
> - **Plate:** `count-up`, `line-draw`, `bars-grow`, `highlight`, `pen-circle`, `stamp`, `zoom-to-slot`.
> - **Room:** `screen-flicker`, `window-snow`, `window-rain`, `lights-twinkle`, `card-pin`.
> - **Overlay:** `slide-in` (lower third and source tag) and `tick-over` (the bumper number).
>
> No move fades (rule 2). Things draw on, grow, slide, or land with a small overshoot (`E.land`).
> They play live in section 3 of `/Motion Review.dc.html`.

> ## rebuild-34 — Q11 · transitions
>
> Through the kit's own scripts: `emit.js` **384 assets · 1,266 plate records · 513 slot tables**;
> `export.js --index` **4,608 files (3,402 animation frames)**; `audit.js --check` **30 of 30**.
> Frame strip: `screenshots/q11.png`.
>
> **Three wipes in overlays/**, both aspects, alpha outside the cover:
> - `wipe-sweep`: a hatched cover moves left to right, with a structure-ink leading edge.
> - `wipe-page`: a sheet rises from the bottom and leaves at the top.
> - `wipe-blinds`: slats close and reopen. It goes under the chapter bumper.
>
> **How they play:**
> - Each is eight frames, `playback: 'once'`, at 12 fps, so about 0.7 s.
> - `role: 'transition'`, and it is reached by the assembler only, never the writer.
> - **`meta.transition.cutAt: 4`**: the cover is full on frame 4, and the edit cuts the two shots
>   under it there. A wipe never shows two shots at once.
> - They are drawn in the band ink over structure, the room's own colours.
>
> **Engine change:** `emit.js` treats `args.transition` as progress frames. It draws one plate
> per frame at t = 0.125…1, instead of the breathing rule offsets.

> ## rebuild-33 — Q10 · shorts plates
>
> Through the kit's own scripts: `emit.js` **381 assets · 1,254 plate records · 507 slot tables**;
> `export.js --index` \u2014 see below; `audit.js --check` **30 of 30**. Contact sheet:
> `screenshots/q10-v2.png`.
>
> **Three 9:16-only shorts plates** (`portOnly` in the round-five `LIB`). Each publishes
> `meta.safe` (top 260, bottom 1,560), and the content sits in the middle, clear of the platform's
> UI. `formats: ['short']` in roles.
> - `shorts/short-number`: one figure large, a label, one line of context, and the source.
> - `shorts/short-quote`: the quote as four LINE slots, `quote-1..4`, broken on words in
>   `copy-r5.js`. It throws past four lines, so the quote is cut and never the font. Who said it,
>   and a date line that carries why it matters.
> - `shorts/short-chart`: a three-second chart, one line with its last point, and the change as
>   the big figure (derived).
>
> **Noticed:** `content.js` fills any slot left unset with generic sample copy. An unused
> `quote-4` printed an unrelated sentence until it was set to `''`. Optional slots should
> probably default to empty.

> ## rebuild-32 — Q9 · episode furniture
>
> Through the kit's own scripts: `emit.js` **378 assets · 1,248 plate records · 504 slot tables**;
> `export.js --index` **4,476 files**; `audit.js --check` **30 of 30**. Contact sheet:
> `screenshots/q9-v2.png`.
>
> The end card (`structure/end-card`) and the name lower third (`overlays/lower-third`) already
> existed. The two the episodes lacked are new:
> - **`structure/chapter-bumper`** (`chapterBumper`) is the full frame between chapters.
>   - It shows the chapter number large, "of seven", the chapter's title and the episode.
>   - It is held for 2 seconds (`meta.hold`).
>   - `reached_by`: the assembler places one before every chapter after the first.
> - **`overlays/source-tag`** (`sourceTag`) is an alpha strip, "SOURCE · 10-K FY25, note 14, page 96".
>   - It has its own canvas: 900×72 at 16:9 and 980×92 at 9:16.
>   - It is placed whenever a plate carries a sourced figure.
>   - Round-five `LIB` now takes `sizes` for overlays drawn at their own canvas.
>
> **Fixed before shipping:** the first cut drew the bumper's upright divider and the tag's accent
> with `rule()`, which is horizontal-only. The weight argument became 6,401 px and covered the
> frame. The divider is now a narrow `band`, and the tag has no accent.

> ## rebuild-31 — Q8 · hand props and mouths
>
> Through the kit's own scripts: `emit.js` **376 assets · 1,240 plate records**; `export.js --index`
> **4,444 files (3,264 animation frames)**; `audit.js --check` **30 of 30**. Contact sheet:
> `screenshots/q8.png` and `q8b.png`.
>
> **Three new poses in `KitModel.POSES`.** Each prop is one path in an EXISTING material role,
> placed from the wrist it sits in, so no new colour is added:
> - `holding-a-filing`: both hands, a bound report taller than a page (paper).
> - `holding-a-phone`: right hand at the chest, head dropped to it. The phone is in the SCREEN
>   role, so it reads as lit. A dark phone read as a patch on the shirt.
> - `holding-a-mug`: right hand at the sternum, a pale mug over the fingers with a handle (paper).
>
> Each pose gets the four strips (still, talk, idle, blink): 12 new host assets.
>
> **Mouths:** the geometry now carries `mouthO`, `mouthEE` and `mouthFV` beside closed, mid and
> wide. Every `-talk` strip is six frames in phrase order (closed, mid, wide, O, EE, F/V), not
> three, so a long read no longer loops three shapes. This is a change to EVERY existing talk
> strip, which is why the animation frame count rose by 156. The head framings in `build.js`
> (`hostHead`) still use their own three-mouth talk and are unchanged.

> ## rebuild-30 — Q7 · six plates
>
> Through the kit's own scripts: `emit.js` **364 assets · 1,216 plate records · 500 slot tables**;
> `export.js --index` **4,264 files**; `audit.js --check` **30 of 30**. Every round-five copy
> string fits uncut.
>
> **New authors in `plates-r5.js`:**
> - `pairedBars` draws `charts/surprise-vs-reaction`. It shows the EPS surprise and the next
>   day's share move per quarter, on two FIXED symmetric scales, with up and down ink by sign.
> - `markedList` draws `paper/risk-factor-diff`. Each line is marked + added, − removed or
>   ~ reworded, and `data.markInk` gives each mark's ink.
> - `footnoteSpot` draws `paper/footnote-spotlight`. The note is quoted, the key sentence has an
>   attention underline (`underline` on the slot, which `dataLayer` now draws), and one figure is
>   pulled out.
> - `eventCalendar` draws `structure/event-calendar`. The next five dates sit on a six-month rail,
>   numbered, with what to watch at each.
>
> **Reused authors:**
> - `sectorRanking` draws `peers/peer-rank`. Its line is the peer MEDIAN, and the caution says the
>   legend must say so.
> - `stackedToLine` draws `charts/capital-returned`: dividends and buybacks as a % of free cash
>   flow, against a 100% line.
>
> **Noticed:** `maxLines` on the new text slots is not honoured by `sized()`, which fits them as
> ONE line. I shortened the copy instead of changing the fitter. Multi-line quotes need the
> fitter to take `maxLines`.

> ## rebuild-29 — Q6 · said-vs-happened and revision-trail variants
>
> Through the kit's own scripts: `emit.js` **358 assets · 1,192 plate records · 488 slot tables**;
> `export.js --index` **4,168 files**; `audit.js --check` **30 of 30**.
>
> - Two wrappers in `plates-r5.js`, `saidHappenedAs` and `revisionTrailAs`. They draw the
>   legacy drawings under their own `type`, so each variant carries its own copy and roles.
> - **Said-happened, four events, both aspects:**
>   - `said-happened-guidance` (Tessera)
>   - `said-happened-capital` (Harrow)
>   - `said-happened-strategy` (Larkin)
> - **Revision trail, 16:9 only** (`landOnly`, as in round one):
>   - `revision-trail-up` (Merrow EPS rising)
>   - `revision-trail-target` (Larkin's average price target, six cuts)
>   - `revision-trail-revenue` (Tessera's next-year revenue)
>
>   The moves are derived from the estimates.
> - **Fixed along the way:** said-happened's `diverge-N` note has always promised "the renderer
>   draws the tie in attention", and nothing drew it. `dataLayer` now draws `data.diverge`
>   (column indices) as an attention bar down the named column. The legacy said-happened-3–6
>   plates can use it too.
> - The review page lists round five newest first.

> ## rebuild-28 — Q5 · sector performance
>
> Through the kit's own scripts: `emit.js` **352 assets · 1,174 plate records · 479 slot tables**;
> `export.js --index` **4,096 files**; `audit.js --check` **30 of 30**.
>
> - **`peers/sector-ranking`** (new author `sectorRanking`): all eleven sectors' returns for one
>   period, ranked, as bars from zero on a FIXED symmetric −30% to +30% scale. The episode's
>   sector is in attention, and the market is one `market` line down every row. The ranking is
>   sorted in `copy-r5.js`, never typed.
> - **`charts/sector-vs-market`** (uses `priceCostSpread`, `fill: false`, 12 months): the sector and
>   the market rebased to 100 on one scale, with the gap as the callout. The scale floats on
>   purpose (`zero: false`), because the lines are rebased levels and `rebased to 100` is in the
>   unit line.
>
> The two plates reconcile: Industrials +3.1% against a market of +8.4% is the −5.3pt on both.

> ## rebuild-27 — Q4 · macro drivers
>
> Through the kit's own scripts: `emit.js` **350 assets · 1,166 plate records · 475 slot tables**;
> `export.js --index` **4,064 files**; `audit.js --check` **30 of 30**. Review: the bottom of
> `/New Shapes Review.dc.html`.
>
> **One new author, `driverEffect`:** the driver in `panel-1` (quiet) and the effect on the
> company in `panel-2` (subject), on one time axis. Each panel is on its OWN published scale
> (`data.panelScale`, which `dataLayer` now reads). There is never a second axis on one plot. The
> company's disclosed sensitivity is the callout.
>
> Five plates, each with an issuer the kit already has:
> - `macro-rates`: the policy rate against the Merrow net interest margin.
> - `macro-inflation`: food inflation against Fenwick's price and mix.
> - `macro-fx`: the dollar index against the currency effect on Harrow's growth.
> - `macro-commodity`: copper against the Corvane EBITDA margin.
> - `macro-wages`: retail wage growth against Larkin store costs.
>
> Every copy string on the round-five plates fits its box uncut. This is checked against
> content.js fit() on every run of the fit probe.

> ## rebuild-26 — Q3 · banks and insurers
>
> Through the kit's own scripts: `emit.js` **345 assets · 1,146 plate records · 465 slot tables**;
> `export.js --index` **3,984 files**; `audit.js --check` **30 of 30**. Review: the bottom of
> `/New Shapes Review.dc.html`.
>
> Three new authors in `plates-r5.js` and four plates in `copy-r5.js`, all sector `financials`:
> - `ratioVsFloor` draws both of these on a FIXED scale:
>   - `cet1-vs-minimum` (Merrow Bank, 0–20%): the 4.5% minimum is a `floor` marker in attention,
>     and the minimum plus buffers is a `target` band.
>   - `solvency-ratio` (Pellam, 0–250%): the 100% requirement, with the 150–180% target range.
> - `stackedToLine` draws `combined-ratio`: the loss and expense ratios stacked
>   (`part-a-N` / `part-b-N` bands), against a 100% `line` marker, on a fixed 0–120 scale.
> - `developmentRails` draws `reserve-development`: the first estimate (quiet) and today's
>   estimate (attention) for each accident year, on one rail. The rail runs $350m–$600m, and its
>   ends are printed.
>
> Every figure is derived: headroom, combined totals and development percentages. Pellam is a
> new fictional P&C insurer.
>
> **Noticed:** the `target` band is in `ink.band`, which is faint against the ground at night.
> It reads, but only just. A stronger ink is a one-word change if wanted.
>
> **Next:** Q4 macro drivers, then Q5 sector performance, Q6 said-vs-happened, Q7 the six plates,
> Q8 props and mouths, Q9 episode furniture, Q10 shorts, Q11 transitions.

> ## rebuild-25 — the Christmas set
>
> Through the kit's own scripts: `emit.js` **341 assets · 1,130 plate records · 457 slot
> tables**; `export.js --index` **3,920 files**; `audit.js --check` **30 of 30**. Preview:
> section 0 of `/Rooms and Poses Review.dc.html`. A grid of four dressed rooms at both
> hours is at `screenshots/xmas-grid.png`.
>
> - Every anchored angle (14) gets a seasonal twin, `room/<id>-christmas`, built by
>   `dress()` in `kit-model.js`. The plain rooms are unchanged. You switch the season by
>   picking the asset.
> - **The lights** run along the picture rail just under the ceiling, so they are in every
>   angle. Where a window pane is in frame (`desk-wide`, `window-wall`, `window-wide`) a
>   second string hangs along its head.
> - **The tree** stands on the floor at the window's left, sized from the window. It is
>   derived from each angle's own window, so it is the same tree in the same place.
>   Behind him, before the desk.
> - **A new material role, `foliage`**, is in both hours in `design-tokens.json` and
>   `KitModel.NIGHT/DUSK`. It is SEASONAL ONLY, and it is the first addition past the 13 roles.
>   Bulbs use the existing inks (attention, subject2, subject), so no other new colour.
> - The `PLAN` objects gain `tree` and `lights`. Each dressed angle is `pulledFrom` its
>   source, so rule 30 holds. Clearance is measured with the source's poses (`fitsAs`).
>   The worst cover above the desk is 3%.
> - **Noticed, not changed:** the tree is only in the three angles that show the window. In
>   `desk-wide` it is cropped by the left frame edge. The talk angles do not see the window
>   wall, so they carry the lights only. Say if a second tree position in the talk angles is
>   wanted.
> - The review page's fit section is now opt-in (`showFits` tweak). It measures cover pixel
>   by pixel and was freezing the page.

> ## rebuild-24 — the room's floor plan (Q1) and five new shapes for review (Q2)
>
> Run through the kit's own scripts under the shim:
> - `emit.js`: **327 assets · 1,074 plate records · 451 slot tables · 14 family manifests**.
> - `export.js --index`: **3,892 files**.
> - `audit.js --check`: **30 of 30**.
> - `audit.test.js`: **25 of 25**. Rule 9's rebuild was stubbed in memory for time in the
>   negative control only; unstubbed, it passes in the full audit.
>
> **Q1 · One room.** `KitModel.PLAN` lists the room's objects once: desk, monitor, desk lamp,
> window, door and board. It also lists what each of the fourteen drawn angles sees.
> `KitModel.seen()` counts the drawn objects by role. **New rule 30** fails any of these:
> - an angle that draws two of anything
> - an angle whose drawing disagrees with what it declares
> - an angle outside the drawn fourteen that isn't `pull()`-ed from one of them
>
> All 16 angles pass, and 2 are pulled. The existing fourteen were already consistent (one of
> each). The two openers were the only breach, and they were fixed in rebuild-23.
>
> **Q2 · Five new shapes**, in `engine/plates-r5.js`, with copy, data and roles in
> `engine/copy-r5.js`. Review page: `/New Shapes Review.dc.html`.
> - `valuationHistory`: four plates (EV/EBITDA, forward P/E, EV/Sales, FCF yield). A line
>   over its own five-year range (`range` band, `under: true`) and average (`average` marker,
>   `ink: quiet`).
> - `guidanceRange`: guide-N bars (quiet) and actual-N marks (attention) on one scale.
> - `smallMultiples`: 4 and 6 panels, one series per `panel-N`, on ONE shared scale.
> - `earningsVsCash`: two lines with the gap filled (`spreadFill: true`) and an accruals row.
> - `segmentMarginGrid`: 5×5 cells, each with a bar on the fixed 0–40 scale. A falling latest
>   year is in attention.
>
> Engine changes:
> - `plates-r2.js` exports `R2_HELPERS`.
> - `series.axisMark` takes `tone`.
> - `dataLayer` draws `data.panels`, paints `under` bands first, and takes a mark's ink from
>   its slot.
>
> The data is derived in `copy-r5.js`: the range, average, record and accruals are computed,
> never typed.
>
> **Sector variants wait for sign-off on these shapes.** Q3 onward are next: bank and
> insurer, macro, sector performance, said-vs-happened, the six new plates, props and mouths,
> episode furniture, shorts, then transitions.

> ## rebuild-23 — opener rooms and three poses (rooms and poses first, as asked; plates next)
>
> Through the kit's own scripts under the shim: `emit.js` **318 assets · 1,038 plate records ·
> 433 slot tables · 14 family manifests**; `export.js --index` **3,748 files** (+76: 3 poses × 4
> strips × 2 hours × frames, plus 2 rooms × 2 hours); `audit.js --check` **29 of 29**. Review:
> `/Rooms and Poses Review.dc.html`. The composites are also in `/Room Composite Check.dc.html`.
>
> **Opener rooms.** `board-wide` and `window-wide` join `desk-wide`, all with `opener: true` and the
> same 92×42 card, so one title fits all three. Rule 28 now finds 3 openers.
>
> **Corrected after operator review:** the first cut drew both from scratch. That put a second
> desk and a second monitor in his room and lost every object the viewer knows. They are now
> DERIVED by `pull()` in `kit-model.js`:
> - `window-wide` is `window-wall` and `board-wide` is `board-side`, each scaled 0.8 about the
>   floor centre.
> - Same objects, same places. Surfaces that bled off the frame still bleed off it.
> - The only addition is the title card on the wall above him, at [55, 10].
>
> Head cover is 0% in both. The worst cover above the desk is 1.7% (shrug, window-wide).
>
> **Poses** (`kit-model.js` POSES, joint positions only, no new parts):
> - `gesturing-at-plate` fits panel-left, board-side and board-wide.
> - `counting-on-fingers` fits desk-front, desk-front-b, desk-wide and window-wide.
> - `shrug` fits the same four. It adds one rig field, `shoulderDy` (−10), which lifts both shoulders.
>
> All three stay inside the 400×720 box (rule 13). The worst cover above the desk is 3.3%
> (counting-on-fingers in desk-front). `roles.fragment.json` has entries for all 12 new host
> strips and both rooms.
>
> **Noticed, not changed:** fingers are not drawn. A hand is one rounded shape, so
> counting-on-fingers reads as hands meeting, and the count is carried by the voice-over. Separate
> fingers would mean a new part, which is the operator's call.
>
> **Next, in this order:**
> 1. The five new shapes: valuation against its own history, guidance range, small multiples
>    (4 and 6), earnings against cash, and segment margin grid. These go for review before any sector variants.
> 2. Bank and insurer plates: CET1, combined ratio, reserve development, solvency.
> 3. The five macro drivers.
> 4. Sector performance against other sectors over a period.
> 5. More said-vs-happened and revision-trail variants.
> 6. Shorts plates, then transitions.

> ## rebuild-22 — the data contract, from the Node integration report
>
> Through the kit's own scripts under the shim: `emit.js` **304 assets · 1,006 plate records ·
> 429 slot tables · 14 family manifests**; `export.js --index` **3,672 files** (unchanged: no
> drawn ink moved); `audit.js --check` **29 of 29**; `audit.test.js` **23 of 23** (rule 9's
> rebuild stubbed in memory for time in the negative control only; unstubbed it passes in the
> full audit). All changes are published fields. The drawing is unchanged, so the samples
> render the same figures.
>
> 1. **Fill.** `plot-area.spreadFill` is published on all 17 two-line designs (34 tables), and
>    the note drops "and spreadFill between them" where it is false. Unfilled:
>    price-vs-volume, net-price-vs-volume, traffic-vs-ticket. **brand-vs-private-label fills.**
>    Its sample was the one that was wrong. `fill: false` is removed and the purpose now says so.
> 2. **Legend ink.** `ink` goes on every keyed legend-N/row-N (180 slots), and `tone`/`tone2` goes on
>    the plot-area. The eight ratio pairs publish `tone2: quiet`. The eight payback plates publish
>    `legend-2.ink: attention` and `cac-line.ink: attention`. The swatch colour and `ink` now come from
>    one palette key. The dataLayer defaults `tone2` and fill from the slot table.
> 3. **Band scale.** Band slots publish each plate's own range (`bandScale`). exclusivity-runway
>    and lease-maturity get [2025, 2040], rate-case-calendar [2025, 2030], trial-timeline [2025, 2031],
>    mine-life [0, 30], repricing-gap [0, 60], reserve-life [0, 20] and staples-cash-cycle [0, 120].
> 4. **Growth rail.** All 150 growth-N markers publish `scale: [-20, 20]` and `clamp: true`.
> 5. **Wire strips.** Each headline box is now exactly two lines at the compositor's pitch
>    (`maxLines 2`). The 3-row strip's headline is 340–468 with its source at 479. The 5-row
>    strip's is 340–440 with its source at 451.
>
> **New rule 29** checks all four fields against their notes and keys.
>
> **Noticed, not changed:** the report counts 18 designs with the spread note. The kit has 17
> designs (34 slot tables) on `priceCostSpread`.

> ## rebuild-21 — the composite check, and five items from the Node report (supersedes the counts below)
>
> **This is the output of the kit's own scripts, run unmodified through the CommonJS shim.**
> `emit.js` gives **304 assets · 1,006 plate records · 429 slot tables · 14 family manifests**.
> `export.js --index` gives **3,672 files**, which is 60 fewer than before because the ten marks lost
> their frames. `audit.js --check` passes **28 of 28**. `audit.test.js` catches **20 of 20**
> injected violations.
>
> **1 · Rooms, checked with him in them.** Every room shape now carries an explicit
> `front` layer. `b(...)` in `kit-model.js` marks a shape that sits behind him wherever it
> was authored. `rooms()` orders each room behind, then front, and the split is the first
> front shape (§4.5). Wall items moved behind him in `panel-left`, `read-close`,
> `turn-to-screen`, `desk-side`, `desk-front`, `desk-wide`, `window-wall`, `doorway`,
> `desk-front-b`, `desk-front-low` and `doorway-wide`. `desk-front-b` and `desk-front-low`
> had him behind the monitor, so their anchors moved right of it. `desk-front-b`'s monitor
> is now off his shoulder, as its note says. The same composite then found a monitor in
> front of him in `window-wall`, `doorway` and `doorway-wide`, and trays on the desk in
> `read-close`, `turn-to-screen` and `panel-left`. Those were moved too.
> `M.clearanceOf` composites every pose that fits each room by the contract and `emit.js`
> publishes the result as `clearance`. **New rule 27:** no head under a front shape, and
> at most 10% of him above the desk top. Result: 0% head cover in every room. The worst
> cover above the desk is 6.4%, `desk-front` with `sitting-at-desk`, from a paper stack
> on the desk. The composites are in `/Room Composite Check.dc.html`.
>
> **2 · Title slot.** `desk-wide` now publishes `slots.title` (`ground: card`,
> `groundBox`, `colour: structure`, budgets from budget.js) in both aspects:
> `room/manifest.json` → `slots`, `slotsByAspect`, `opener: true`, and `emit/slots.json`
> → `room/desk-wide-16x9` / `-9x16`. The card is drawn top-right, inside the portrait
> window and above his head. The window graphic moved to the left wall, and he stands
> about 10% further back so two lines fit in 16:9 (2 × 16 characters; 9:16 holds 3 × 37).
> **New rule 28** checks placement. **Only `desk-wide` opens a chapter.** The read and
> talk angles are too tight to fit a card inside the window above him, so a chapter
> template must open on an `opener` room.
>
> **3 · Marks are stills.** All ten `annotations/` marks are `still / 1 / 1`, with one file
> per hour and no frames.
>
> **4 · Hair.** The hair shade is now a rim crescent from crown to temple instead of half
> the hair, the same fix as the face terminator. The glasses are unchanged.
>
> **5 · Legacy pass (`plates.js` unfrozen for these five authors only).**
> - waterfall-3s/4s/5s: the end-label boxes are inset like the step boxes.
> - insider-flow: the plot stops where the date and who rows clear the caption.
> - macro-series: the bottom y label sits on the baseline.
> - cycle-frame: head-1 and head-6 align inward from their end ticks.
> - said-happened-3/4/5/6: each rail name heads its own track, inside the safe margin.
>
> Slot boxes on all 21 plates are clean for overlap and margin. `roles.fragment.json` is
> corrected at source:
> - 46 aspect-suffixed keys folded onto their asset ids.
> - 4 dropped assets removed.
> - The 24 entries that remain from the 32 with non-structural `shot_ids` now say
>   `formats` + `beats`, or `any_shot` for host poses. Every `shot_ids` value is now
>   open / evidence / land / on-the-desk.
> - The `move-on-the-day` caution is rewritten.
>
> **Also fixed:** `audit.test.js` had not run green since rule 22. It stripped `fs`/`read`,
> so rules 22–26 threw on the baseline. Rule 9 now diffs the manifest as loaded, which is
> why the fps injection is caught.
>
> **Also fixed, rebuild-21b (the rest of the stricter probe).** A text-extent probe runs
> over every plate: sample copy at the renderer's fitted size, overlap between text, and
> the 5% safe margin. It flagged these, now fixed in `plates.js`:
> - numbers-sheet-3r…6r and -4r-spark, and cash-flow: portrait side margins went from 48 to 56.
> - sensitivity: the row labels start at the margin, and the column axis title stacks above the heads.
> - line-6y, line-8q, guided-vs-actual: the last value box is clamped inside the margin.
> - line-dense: the heads are clamped to the margin, not to 12 units.
> - media-frame-t2: the screen is 4% shorter in 16:9, so the source clears the bottom.
> - flow: the input and output start and stop at the margin.
> - timeline: the end dates and labels align inward from their ticks.
>
> The probe now flags nothing except `overlays/lower-third-9x16`, and that is expected.
> It is an overlay strip measured against its own small canvas, and its on-screen
> margin is set by where the compositor places it. Rules 20 and 23 still pass, and
> nothing is over budget.
>
> **Noticed, not changed:** none.

> ## Where it stands — rebuild-19 (superseded by the rebuild-21 block above)
>
> **From the kit's own scripts, run unmodified through the CommonJS shim:** `emit.js` →
> **205 assets · 612 plate records · 230 slot tables · 14 family manifests**;
> `export.js --index` → **2,156 files** (584 base + 1,572 frames); `audit.js --check` →
> **26 of 26**. Rule 24 reports 145 plates, all 145 with a caution. Widest rendered string
> is 1.00× its box, and nothing is over budget. Everything in `emit/` and
> `out/index.json` is that run's output.
>
> **1 · Long-plate recheck, fixed first** (`/Plate Recheck.dc.html`, 1920×1080, both hours):
>
> - `year-on-year-diff`: the full-height change bar is now a mark under FY24, plus a
>   `mark-area` overlay over the changed words. The paragraphs start 20px lower.
> - `growth-and-margin`: the as-filed | derived rule moved out of the FY23 figures and into
>   the empty gutter of the growth column.
> - `timeline-dense`: labels hang right from their own ticks, and the rail stops one label-width short.
> - `scorecard`: a three-station rail (FAILS · PARTIAL · HOLDS), stations marked on every row.
> - `revision-trail`: dates, estimates and moves are centred under their points.
> - `scenario-fan`: the origin moved right, and the price is set flush against it.
> - Sample data: `content.js` now gives round-one plates numbers of their own (`R1D`, keyed
>   on type). buyback-dollars and where-the-cash-went draw what their labels state, the
>   scatter copy says eight, the 7- and 8-row sheets and said-happened-6 stop repeating, and
>   the round-one copy the budget was cutting now fits uncut.
> - **Not changed:** said-happened-6's HAPPENED label, about 46px from the edge. It comes
>   from the legacy `saidHappened` in frozen `plates.js`, so it goes to the legacy pass.
>
> **2 · Round two: software and industrials** (`engine/plates-r2.js`, `/Sector Plates.dc.html`).
> Twelve plates, each at 16:9 and 9:16. Software: arr-bridge, nrr-cohorts, rule-of-40,
> sbc-vs-buybacks, rpo-coverage, cac-payback. Industrials: book-to-bill, margin-walk,
> end-market-exposure, price-cost-spread, cash-conversion-cycle, capex-vs-depreciation.
> Sample copy comes from two new fictional issuers (Tessera, Harrow), so the kit stops
> reading as one insurer. Each plate has a purpose, a caution, chapter types and `sectors`
> in `roles.fragment.json`. The laws they add (fixed scale, floating rate walks) are in
> DESIGN.md §5.4. Engine changes: new `series.js` renderers (`splitBar`, `scatter`,
> `spreadFill`, bridge ends and float, `tone`); `export.js` exports its `dataLayer`;
> `port.js` installs round two after round one; `emit.js` tags `round: 'r2'`.
>
> **3 · Round three: one set per GICS sector** (`engine/plates-r3.js`). Eighteen plates, each
> at 16:9 and 9:16, covering the nine sectors round two did not. Energy: breakeven-vs-price,
> production-mix. Materials: ebitda-walk, capacity-utilisation. Consumer discretionary:
> inventory-vs-sales, store-count-bridge. Consumer staples: price-vs-volume, net-sales-walk.
> Health care: exclusivity-runway, product-concentration. Financials: nim-spread, deposit-mix.
> Communication services: subscriber-bridge, content-vs-revenue. Utilities:
> allowed-vs-earned-roe, generation-mix. Real estate: occupancy, noi-walk. Each one names a
> round-two shape instead of redrawing it: `plates-r2.js` authors now take `type` and
> `family`, and there are two new generic forms, `walkN` and `pairedN`. Each plate has its
> own copy, data, issuer and roles entry (`content.js` R3/R3D). `sectors` now uses GICS
> names, so round two's software plates are `information-technology`.
> **Latest run: 223 assets · 684 plate records · 266 slot tables · 2,444 export files ·
> audit 26/26 · 163 plates, all with a caution.**
>
> **4 · `charts/line-dense` fixed (both aspects).** It is a 12-tick plate, and it was being
> fed six yearly points, FY heads and three generic figures. That meant "123" and "$40m" as
> the high and low, and "1,388" printed over the high. It now gets twelve monthly points,
> date heads, and callouts that are the series' own high and low. `mark-last` is left to
> the renderer (`content.js`, R1/R1D).
>
> **5 · Finish pass, rebuild-20.** A geometry probe over every plate, checking text boxes
> that overlap and text outside the 5% safe margin. It led to fixes in cac-payback, the
> end ticks on the tracks plates, and the last tick on rule-of-40. Legacy plates it flagged,
> left alone because `plates.js` is frozen: waterfall-3s/4s/5s (total-label~step-1),
> insider-flow (who~caption), macro-series (y-1~head-1), cycle-frame (now-value~head-1) and
> said-happened-6 (rails outside the safe margin).
> Shorts recheck: `move-on-the-day`'s arrow pointed up on a −18.4% move. It is now a -down
> and -up pair, each with its own type, copy, data and roles entry. The wire-strip source now
> sits under its headline. Rooms were checked at both hours; no changes.
>
> **6 · Round four: ten plates per GICS sector** (`engine/sector-copy.js`). Eighty more plates,
> each at 16:9 and 9:16, bringing every sector to ten: 4 each for IT and Industrials, 8 each
> for the other nine. Each row is data: a shape (nine round-two shapes), its copy and
> numbers, and a purpose, caution, chapter types and beat. `plates-r3.js` reads its catalogue
> rows from it, `content.js` reads the copy and data, and `roles.fragment.json` (`round:
> 'r4'`) is generated from it. The builders DERIVE a walk's close and net change, the ratio
> rows, and the payback month, so a plate cannot disagree with itself. `check()` confirms
> every row of shares sums to 100.
> **Latest run: 304 assets · 1,006 plate records · 427 slot tables · 3,732 export files ·
> audit 26/26 · 244 plates, all with a caution. Nothing overflows, nothing is over budget.**
>
> **Still open:** the shorts recheck (15 plates), the original rooms, the legacy library
> by family, and the hair split and glasses weight (the operator's call).

> ## rebuild-17
>
> **From a fresh unzip, in real Node:** `node engine/emit.js && node engine/audit.js --check`
> passes **26 of 26**; `node engine/export.js` writes **1,964 SVGs** (536 base + 1,428
> frames). **193 assets · 564 plate records · 206 slot tables · 14 family manifests.**
> Everything in `emit/` and `out/index.json` is what a clean run of those commands
> produces — nothing in them was written by hand or by a review page.
>
> **What rebuild-17 fixed**, from the operator's Node report:
>
> 1. **The host exports are the host.** `engine/figure.js` renders the figure in its own
>    400×720 box with the full paint order — body, head, marks, glasses under `glassesT`,
>    eyes, mouth, all under `headT`. The old export drew into the room's 320×180 box and
>    dropped the face. See `screenshots/host-export-fixed.png`.
> 2. **The host talks and blinks; plates breathe.** Every frame is its own file. See
>    `ANSWERS.md` §2.
> 3. **`out/` is blank.** Sample content only under `--sample`, in `out-review/`.
>    `ANSWERS.md` §3.
> 4. **`emit.js` is the one pipeline.** It reads `port.js` (legacy library + round one),
>    `kit-model.js` and `figure.js`; `export.js` calls its `build()`, so manifest and
>    files cannot disagree. `kit-plates.js` is no longer emitted (its flat exemplars were
>    superseded by the ported originals; `tables/rows-5` is gone). `board-side` now
>    publishes its occlusion split (no desk → he is drawn over everything).
> 5. **Every plate's slot table is published** in `emit/slots.json` and again in each
>    `<family>/manifest.json` (position, type role, `maxChars`), round one included.
> 6. **`emit_manifests.mjs` is a thin door onto `emit.js`**; audit rule 9 now RUNS the
>    rebuild-and-diff instead of carrying its name.
> 7. **Two new rules:** 25 (strips must move) and 26 (files must frame their ink).
>
> **Root cause, stated plainly:** earlier rounds were verified by scripts that
> re-implemented the pipeline inside the review sandbox instead of running the kit's own
> files. Those scripts diverged — one stubbed `M.anchorOf` to `null`, which is why the
> shipped manifest left the six new rooms without their anchors. From this round the
> kit's own `emit.js`, `export.js` and `audit.js` are executed unmodified under a
> CommonJS shim, and their output is what ships.
>
> **Decisions received:** the ten marks are approved (strokes kept, no boil);
> rasterising stays with the ingest.
>
> **rebuild-18 recheck.** Face, both hours, and the six new rooms looked at again at
> render size (`screenshots/recheck.png`):
>
> - **The face terminator is already off the midline.** `kit-model.js` puts the skin
>   shade at the cheek rim plus the jaw's cast on the neck side, so the nose keeps lit
>   skin to read against. The open item from the close-crop review is closed.
> - **`room/panel-left`: the clear field is wall now, marked at its four corners.** It
>   was a dark slab that read as a switched-off screen and showed wherever a composited
>   plate was smaller than the field.
> - **`room/board-side`: the board's cast is a band under the board.** It was a dark
>   trapezoid running to the frame edge that read as a hole in the floor.
> - Kept as drawn: `desk-front-b`, `desk-front-low`, `read-close`, `doorway-wide`.
>
> Re-emitted and re-audited through the kit's own scripts: **26 of 26**, 193 assets,
> 1,964 export files.
>
> **Noticed, not changed:** at night the hair splits into blue-grey and brown roughly down
> its middle, and the glasses read heavy at close range because they use the one
> contour weight the tokens allow. Both are character decisions, not defects — change
> them only on the operator's word.

**Read this first.** What is done, what is not, what is next. Updated on every delivery.

- **Spec:** `DESIGN.md` — every decision with its reason. The only source of truth.
- **Numbers and colours:** `design-tokens.json` — the engine reads it; nothing hardcoded.
- **Review surface:** `Ported Plates.dc.html` at the ZIP ROOT — all 92 assets, both hours, content and data live. The slice pages (`Slice 1–5 Review.dc.html`) are the history and still open. The older note follows: `Slice 4 Review.dc.html` — the room set on top, then slice 3's inventory, slice 2's composites, and slice 1's evidence from §1 down. (The earlier `Slice N Review` files are kept for comparison.) (not in `kit/` — it needs
  `support.js` beside it). Open it in a browser: palettes, proportion table and part set
  rendered for judgement. It reads `kit/design-tokens.json` on load and shows a drift
  banner if its own copies disagree.

## How to continue, cold

1. Read this file, then `DESIGN.md` top to bottom. It is ~350 lines and it is the whole
   brief plus every decision and its reason. Do not skim §1.2 or §2.2a — those two resolve
   contradictions and a fresh session will otherwise re-open them.
2. Open `Ported Plates.dc.html`. That is what the operator is looking at.
3. **The build is complete (rebuild-09).** All 270 old asset names are resolved: 93 plate
   assets ported, plus the host and rooms rebuilt flat. `engine/export.js` writes 432
   files. **22 of 22 audit rules pass.** Slice 2 is signed off by the operator; slices 3–6
   are delivered on it and the operator has not walked them one by one.
   **What is NOT done: nothing has been rasterised.** `out/index.json` is the work list
   and `node engine/export.js` writes the SVGs; turning them into the 3840×2160 PNGs
   needs resvg or a headless browser, which the kit deliberately does not depend on.
   **And the content is SAMPLE** — one fictional filing, FY19–FY24. Real script copy goes
   in `content-overrides.json` per episode.
4. When you do build: `design-tokens.json` is the only place numbers and colours live. If
   you find yourself typing a hex into a draw function, stop — that is the defect the
   rebuild exists to remove.
5. Every claim you make must be measured, with the count shown. `DESIGN.md` §8 lists the
   audit rules; each law in the spec was written so one of them can check it, and the list
   grows — cite the table, never a count of it.

**The §3 test of whether this handoff worked:** you can produce the next plate and have it
match, without asking a question that was already answered. If you need to ask, the handoff
failed and the answer belongs in `DESIGN.md`.

## What is in this repo, and what is LIVE

| path | status |
|---|---|
| `REBUILD_STATE.md`, `DESIGN.md`, `design-tokens.json` | **LIVE.** The rebuild. |
| `/Slice 4 Review.dc.html`, `/support.js` | **LIVE.** The current review surface. |
| `/Slice 3 Review.dc.html`, `/Slice 2 Review.dc.html`, `/Slice 1 Review v2.dc.html`, `/Slice 1 Review.dc.html` | **SUPERSEDED**, kept for comparison. |
| `rename-map.json` | **LIVE but EMPTY.** Scaffold; populated in slice 6. |
| `scripts/manifest_core.js`, `scripts/emit_manifests.mjs` | **CARRIED FORWARD.** The manifest schema is fixed interface (brief §2.2). Emits slots verbatim. |
| `scripts/check_roles.mjs` | **CARRIED FORWARD.** Enforces audit rule 7 against `roles.json`. |
| `engine/budget.js` | **CARRIED FORWARD.** `maxChars` from the fonts' `hmtx` table. Load-bearing, do not touch. |
| `engine/hand.js` | **DEAD.** The three stacked unverifiable systems §0 diagnoses. Does not survive. |
| `engine/plates.js` | **PREDECESSOR.** The drawn art. Read it for the anchor-solve arithmetic and the slot contract; **do not read it as art direction.** |
| `engine/audit.js` | **NEW, rebuild-06.** §8's rules as runnable code. |
| `engine/audit.legacy.js` | **PREDECESSOR**, preserved. The canonical boil metric — it settled a real disagreement about over-boiled assets. §6 removes the strokes it measures, so it is dormant, not wrong. |
| `engine/rename-map.json` | **NEW, rebuild-06.** 270 old asset names → 159, every drop with its reason. |
| `emit/CONTRACT.json` | **NEW, rebuild-06.** What the emitter must write for each rule to run. |
| `engine/build.js` | **PREDECESSOR.** |
| `<family>/manifest.json` × 14 | **PREDECESSOR.** 270 plates, 3,033 slots of the drawn kit. Kept as the rename map's left-hand side. |
| `audit/baseline-14.json` | **PREDECESSOR.** Baselines for art that is being replaced. |
| `proof/*.html` | **PREDECESSOR.** Review pages for the drawn kit. `boil-motion.html` documents motion that §6 replaces with authored offsets. |
| `CHANGES.md`, `README.md` (in `kit/`), `roles.fragment.json` | **PREDECESSOR.** History and the drawn kit's role mappings. |

**Unfinished business inherited from the drawn kit, none of it blocking:** the wordmark and
strapline are still ``content-overrides.json → _wordmark``; profile screenshots never arrived; `scripts/ingest_kit.py`
(pipeline-side, not in this repo) was never run against the delta-15 manifests; and
`sitting-at-desk` still needs removing from `to-camera` in the renderer's own
`roles.json`. All four are recorded in `CHANGES.md`.

## Slices

| # | slice | gate | state |
|---|---|---|---|
| 0 | `DESIGN.md`, `design-tokens.json`, `REBUILD_STATE.md` scaffolded | — | **DONE** rebuild-01 |
| 1 | Part set + proportion table + the two hour palettes | operator | **SIGNED OFF** with slice 2 (operator, rebuild-04). Part set 9 → 14 (a face), figure lit per-part, 10 poses, 8 room angles drawn in both hours. |
| 2 | **The slice:** figure in 4 poses + 1 close-up; one room both hours; host composited at the real anchor; a title and a caption in place | **operator — hard stop** | **SIGNED OFF** by the operator, rebuild-04. |
| 3 | Full pose inventory | operator | **DELIVERED (rebuild-04).** 10 poses × 2 hours × 11 frames = 220 figure plates. Audit rule 13 added and passing. |
| 4 | Room set | operator | **DELIVERED (rebuild-05).** 8 angles × 2 hours × 2 aspects = 32 room plates, host solved into all 6 anchored rooms. Audit rules 14 and 15 added; 14 failed on all six anchored rooms on first run and the geometry was fixed — see below. |
| 5 | Data plates and overlays recoloured, both hours | operator | **DELIVERED (rebuild-06).** Chart, table bands, lower third and both title treatments at both hours. Audit rules 17 and 18 added; 18 failed on first run — see below. |
| 6 | Audit rules, re-emit, `--check`, rename map | Code | **DELIVERED (rebuild-06).** `kit-model.js` (the model, once) → `emit.js` → `emit/{manifest,plates}.json` → `audit.js --check`. **18 of 18 rules run and pass; 0 need data.** `audit.test.js` breaks each rule on purpose and all 18 catch it. Rename map: 270 old names → 159. |

**Slice 2 was the whole decision and it is signed off.** Everything after it is volume
against a fixed contract.

**Slice 3, as delivered:** all ten poses at both hours, the four strips each one emits
(`base`, `-talk`, `-idle`, `-blink` — 11 frames, identical for every pose), and the
manifest row each pose publishes, emitted as data rather than described so slice 6's
rename map has a diffable left-hand side. **220 figure plates, not 440:** a figure plate
carries alpha and is placed by the anchor solve, so it is emitted once per hour and
composites into both aspects. Only rooms are aspect-bound.

**Slice 2, as delivered:** four poses (`to-camera`, `leaning-on-desk`,
`pointing-down-at-desk`, `sitting-at-desk`) plus the close-up, composited into
`desk-front` at the room's own host anchor; the same room and pose at dusk; a title card
and caption at both hours with their contrast measured against the ground actually behind
them (night 11.00:1, dusk 12.71:1 — rule 5 floor is 4.5). The title still reads ``content-overrides.json → _wordmark``.

## RISK — the one thing this scaffolding does not solve

Every law in `DESIGN.md` converts a judgement into a checkable number **except the nine
part paths themselves.** The part set is still a drawing, and the drawing is the thing that
was rejected six times.

What the rebuild genuinely fixes: the figure can no longer be *inconsistent* (one part set,
one proportion table, poses as transforms), and it can no longer be *muddy* (flat law,
authored palettes, audit rules 1–3). What it does not fix: whether nine authored silhouettes
are good.

**The swap path, and it is cheap by design:** the parts are nine closed paths in one table,
placed by numbers from `design-tokens.json`. An illustrator's nine paths drop into the same
structure with **no engine change** — the tokens, the poses, the anchor solve, the audit and
the manifests are all indifferent to what the silhouettes look like. If slice 1's figure is
rejected, that is the route, and it costs a table swap rather than a round.

## Decided so far, so nothing is re-litigated

- 7.0 HU total height, not 6.8 (§2.1) — the complaint was proportion, so the number changed.
- `shade` = the secondary source that reaches the surface, not a global darkening (§1.2).
  This resolves the brief's own §5.2-vs-§5.3 ambiguity. **Most load-bearing colour decision.**
- 13 material roles per hour, 26 colours total per video (§1.3). The thirteenth is
  `trouser` — the figure needs legs and the brief's example table had no role for them.
- No texture; relief is a six-flat-shape minimum per room (§4.3).
- Corner views dropped (§4.2).
- **The contour does not make the figure read; the wall being clear of every figure
  material does** (§2.2a). Floor: **≥ 0.10 ΔE in OKLab** against that hour's `wall.lit`, in both
  hours — deliberately NOT a WCAG ratio, because `dusk.shirt` reads on hue at 1.08:1 WCAG
  and a luminance-only rule would have destroyed the palette to "fix" it. Four values moved
  (`night.hair`, `night.trouser`, `night.prop`, `dusk.prop`), each with a `_floor` note.
  This corrects a claim in the brief, so it is written up rather than quietly fixed.
- Dusk data plates stay **light**-ground; night are dark-ground, and the band direction
  flips between them (§5.1).
- Room count proposed at **8 angles / 32 plates** (§4.4) — was 5 / 20 at rebuild-01; `window-wall`, `doorway` and `desk-top-down` added. **Needs sign-off**.
- The figure is **fourteen paths, not nine** (§2). The five added are the face and the tee
  collar, one line of the existing character sheet each.
- **Stubble is not carried**, and it is a palette limit rather than a cut: "faint" needs a
  value one step off the skin, the 13-role palette has none, and rule 2 bans the partial
  opacity that would soften `hair.shade`. Costs a 14th material role if wanted.
- Seven widths moved (§2.1) — `shoulderWidth` 2.05 → 1.80 chief among them. No vertical
  number moved, so the table still closes at 7.00.
- **`C = 0.5583`** (§2.5) — the forearm's height as a fraction of the figure box, owed by
  slice 2. Derived closed-form from the proportion table, not measured off a plate, and
  therefore identical across all ten poses.
- **Every pose publishes the STANDING figure box** (§2.5), padded above, never its own
  tighter one — including `sitting-at-desk`.
- **Light on the face is a property of where he is looking** (§1.2a). The monitor is the
  cyan key and it is a fixed object on the desk, so it only reaches him when he is turned
  toward it; reading a page or head-down, the lamp is what lands on him and the cool
  becomes the rim. Same two shapes, same two colours, assignment swapped.
- **Rooms declare an occlusion split** (§4.5) — the point from which shapes paint *after*
  the host, derived as the first `desk`-role shape rather than written down. Flat art has
  no z, so without it the figure is pasted over the room.

## Verified, not assumed

- **Re-measured cold from `design-tokens.json`, rebuild-01 review:** all ten figure-material
  ΔE values in `DESIGN.md` §2.2a reproduce to three decimals, both contour rows reproduce,
  no material falls under the 0.10 floor in either hour, and the proportion table closes
  (3.77 hip, 7.00 total, wrist 0.05 HU below hip). Audit rule 12 would pass today.
- **One contradiction found and fixed:** `DESIGN.md` §1.3 said *12 material roles / 24
  colours* and omitted `trouser`, against 13 everywhere else. The tokens file was right;
  §1.3 now says 13 / 26 and says why trouser exists.
- `budget.js` derives `maxChars` from the fonts' `hmtx` table via `scripts/fontmetrics.js`.
  Not hand-authored. Survives the rebuild untouched.
- The engine emits **zero** `<text>` nodes today.
- `scripts/check_roles.mjs` already enforces audit rule 7 against `roles.json`.
- The review page asserts its own copies of the proportion table **and both hour palettes**
  against `design-tokens.json` on load, and shows a drift banner if they disagree. The
  tokens file is the source of record.

## Found while building slice 2

Both were invisible in slice 1 and would have shipped:

- **A seated pose that publishes its own tighter figure box gets scaled up by a third.**
  The anchor contract scales by `floorLineY − figure.y`; `sitting-at-desk` spans 534 units
  where the standing figure spans 720, so publishing the honest box makes him 35% larger
  than in the cut before it, in the same room. Costs nothing to honour — pad the box above
  the crown — and is undetectable until two plates are cut together.
- **Without a declared occlusion split the host paints over the desk he is standing
  behind.** The split is derived — the index of the room's first `desk`-role shape — so
  wall, pinboard, floor and the back glow paint behind him and the desk slab and
  everything on it paints in front. The room's
  clutter was also re-columned so the host anchor sits in clear space — furniture in front
  of him is depth, furniture through his head is a mistake.

## Audit, run early — and it found one

§8's rules belong to slice 6, but **most of them can run against the review surface
today**, so they do, on load, with counts derived on the page (§S2.4). Running them early
is not slice 6 arriving ahead of time; it is the evidence the sign-off needs.

**Rule 5 failed on its first run.** Both hours' `ink.quiet` — the caption colour — were
under the 4.5:1 floor against the ground they actually sit on: night 3.97:1, dusk 4.29:1.
Moved to `#8592A6` (5.35:1) and `#685A48` (5.49:1), with a `_quietFloor` note in
`design-tokens.json`. The pair had never been checked because a caption colour looks right
beside a title colour; it is only wrong against its own ground, which is exactly what rule
5 samples and what prose does not.

Rules 9 and 10 need the emitter and say so rather than reporting a pass. **Every runnable
rule passes as of rebuild-04**, rule 13 included.

## Found while building slice 4

- **Fixing a law in one place is not fixing it.** `anchorOf` was added inside the slice-4
  block only, so the slice-2 solve diagram and all eight §8 room cards carried on drawing
  the old typed rectangle. The page then showed `desk-front`'s host anchor as 34u wide in
  one section and 110u wide two screens later — the defect §4.4a and §8.1 were written to
  outlaw, reproduced by the change that outlawed it. The derivation is now a single
  method used by every section, and the "anchor region" row prints height as *published*
  and width as *derived* rather than a rectangle the spec says does not exist.
- **The rule written to enforce "run it, do not assert it" spent a rebuild asserting.**
  Rule 16's unresolved value was `null` — the same sentinel meaning "needs the emitter" —
  so a scan that never landed was reported *and counted* as a rule that is not due yet,
  and the summary read as though everything runnable had passed. There are now four
  states, `DID NOT RUN` is its own, it is coloured as a failure, and the scan runs
  synchronously in `componentDidMount` wrapped in a try/catch that surfaces the error
  into the rule's own note.
- **Audit rule 16, and it reads the DOM.** Both anchor contradictions shipped with a
  perfectly self-consistent model and one section drawing from a stale source, which no
  model-level check can see. Rule 16 scans the rendered SVG for anchor rectangles and
  fails any that does not match a derived anchor. It is the first rule in the kit that
  checks the output rather than the inputs — which is what §8 always meant.

- **9:16 is not a crop of 16:9, and the arithmetic says so plainly.** A 180-unit-tall
  window taken out of a 320×180 frame is 101 units wide — narrower than the desk. Portrait
  is therefore a **declared window into the same shape list**, one per room, placed so the
  host anchor sits inside it with margin. No second drawing, so the twin-geometry law
  (rule 6) now holds across aspects as well as hours.
- **This is why a room is aspect-bound and a figure plate is not.** The figure carries
  alpha and is placed by the anchor solve, so it composites into either window unchanged.
  Rooms differ per aspect because the window differs. 32 room plates + 220 figure plates.
- **Audit rule 14 failed on all six anchored rooms on its first run**, and the cause was
  two hand-typed tables free to disagree. The portrait windows were typed at 98×174 and
  the anchor rectangles were typed whole — `desk-front` published a 110u-wide anchor for
  a figure that occupies 35u, which no 98u window can ever contain. Neither number was
  wrong on its own; they were wrong together, which is precisely the failure mode §8.1
  exists for.

  **Both are now derived.** An anchor publishes a *height* — that is what the solve scales
  by — and its width follows from the figure's measured ink aspect (0.3028). The portrait
  window's position follows from the anchor it must contain, clamped to the frame. All six
  rooms now clear it with 31–36u of margin, measured.

  **This was caught by review, not by the run**, because the handoff doc was written
  claiming a pass while the page's own summary read "12 of 13". Recorded rather than
  quietly corrected: a false pass in a handoff is worse than a failing rule, because the
  failing rule is at least visible.
- **Audit rule 15:** *anchored rooms declare a split.* Every room a host can stand in must
  say which shapes paint in front of him (§4.5). Slice 2 proved what happens without one;
  this makes the omission a failure rather than a surprise. A room with **no** anchor
  declares no split — `desk-top-down` briefly reported "split at 0" because its first
  shape is desk-role, which would have painted the entire room in front of any figure ever
  composited into it.

## Found while building slice 3

- **Audit rule 13, new:** *ink inside the published box.* The box is a promise about where
  a pose's ink is, and §2.5 makes every pose publish the same one — so a pose whose hand
  leaves it is silently cropped at composite. All ten poses scanned coordinate by
  coordinate; none outside. The tightest margin is zero at the bottom edge, by
  construction: the feet sit exactly on `floorLineY`, which is the edge the solve contacts.
- **Props need a paint side.** `holding-a-page` painted the page *behind* him — it is in
  his hands, so it paints after them, while `sitting-at-desk`'s chair paints before. One
  `front` flag on the prop; the same class of mistake as the room occlusion split (§4.5),
  and it only showed up once ten poses were on one screen next to each other.

## A standing discipline, earned the hard way

`DESIGN.md` §8.1: **prose does not carry counts.** Three times now a hand-typed number or
list has contradicted the derived one — the occlusion split index, the audit-rule total,
and a part list still naming `stubble` after it was dropped. Every instance was in text
describing the fix for that very defect class. Cite the table, never a count of it; if a
review surface must show a number, it computes it.

## Not carried over from the drawn kit

`hand.js` in its current form (§0). The delta-15 per-author colour literals, superseded by
`design-tokens.json`. The twelve room angles (§4.4). `host/sitting-at-desk` in a framings
role and `host/empty-chair` without alpha — both fixed by construction (§2.4).
