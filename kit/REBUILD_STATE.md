# Dennis v2 — REBUILD_STATE.md

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
