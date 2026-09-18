# Dennis v2 — delta 14, plus §1 and §2

Read **`CHANGES.md`** first. It states what moved, what was measured, and what was
not. The top section is **§2, the quarter** — ten new assets for the data the
pipeline loads and the kit could not draw. Below it, **§1, the title's own ground**
— three treatments, built, measured, and now ON: `card`.

Drop one is **§1 entire, plus §2.1 waterfall and §2.2 what-has-to-be-true** —
the shape you proposed in your answers. §1.4, the settle, is answered in writing
and lands in drop two so that an asset change and a renderer change do not arrive
together.

## What is in the pack

```
engine/          drop-in, same shape as delta-13
  hand.js        + breathe/pin gate, + Plate.clipTo, empty-mark suppression
  plates.js      + hostBlink, waterfall, impliedPlate; ambient props; talk visemes;
                 + titleGround (§1: card · scrim · slab)
                 + quarterPair, seasonality, 8q types on chartFrame (§2)
  build.js       three-frame strips, blink strips, the gate wiring, TITLE_GROUND
  budget.js      unchanged
  audit.js       unchanged
proof/
  preflight.html           sixteen checks, A–P, all passing in ~30s. Buttons write the
                           JSON. P is new in drop eight: every box that declares
                           maxLines, against the lines it declares, at the kit's own
                           pitch. It also closes check E, which had been failing on the
                           four insider-flow plates since drop six
  title-ground.html        §1 — the three treatments on the worst wall and the
                           clean one, with the measured contrast floor in the
                           title box, and the whole-family audit of what is
                           behind that box today
  boil-motion.html         THE BOIL, WATCHED — data plates looping at 2fps, the first
                           time anything in this kit has been seen moving. Start here
                           for the boil question: no number wobbles (315 slot boxes,
                           0 units of deviation), but 13 plates move a band UNDER
                           pinned type. Shipped / fix-previewed / moving-ink columns

  render-scale.html        the review pass at 1:1. ?s=1…?s=14, one at a time.
                           8–14 are drop eight's pass over everything built
                           since drop two — furniture, confession, the quarter,
                           the five pipeline plates, the 24 dusk rooms, the
                           filing reader, and the seated pose composited
  two-against-three.html   §8 — the boil decision, in motion, with a rate slider
  new-plates.html          §0.3 — every new plate filled with real words, now
                           including §2's ten quarter assets, filled twice each
                           from unrelated numbers at different counts
  captions.html            §5 — the two caption options, over a real frame
audit/
  README.md      how to regenerate the pair
  baseline-14.json  per-frame hashes, 270 assets / 924 frames. The file the NEXT
                    pack is checked against — every earlier one is void by design.
  breathe-map.json  per-plate share of ink that breathes, and why each
                    still-by-design plate is still
scripts/build_batch.mjs
                  THE BATCH FALLBACK — one process per family, fourteen of them,
                  each exiting before the next. For the case the process itself
                  will not survive; the real fix is BUILD.stream() in the engine.
                  --list for per-family counts, --family to regenerate one.
                  WRITTEN BUT NEVER EXECUTED — see CHANGES, drop twelve.
scripts/manifest_core.js
                  WHAT A MANIFEST IS, as code. Slots are emitted VERBATIM from
                  Plate.manifest() — no field whitelist, so a plate author who
                  adds a slot field gets it in the manifest by construction.
                  Loaded by the emitter and by any page that wants to diff a
                  manifest against the engine in front of it.
scripts/emit_manifests.mjs
                  THE EMITTER. `node scripts/emit_manifests.mjs` rewrites all
                  fourteen in place; --family for one; --check emits into memory
                  and diffs against the tree, exit 1 if any manifest no longer
                  matches the engine beside it. Run --check before shipping a
                  pack: it is the invariant delta-14 broke and nothing enforced.

<family>/manifest.json
                  §0 · THE FOURTEEN PER-FAMILY MANIFESTS. Generated from the
                  engine, never hand-edited. 270 plates, 924 frame files, 3,033
                  slots. Each entry carries canvas, delivered (canvas x 2),
                  exportScale, playback/fps/frameCount, the _f01.._fNN file list
                  with a per-frame hash, every slot with its derived budgets, the
                  type roles and the plate's own meta. This is what
                  scripts/ingest_kit.py and the renderer read; a plate contains
                  no content, only slots.
                  BESIDE THE FAMILY'S PLATES AND NOWHERE ELSE. delta-14 put its
                  copies under manifests/<family>/, which the ingest's glob does
                  not match — placed there the pack reads as zero assets and the
                  reconcile compares against nothing. That directory is deleted.

§3.5 CHANNEL ART IS CANCELLED (drop twelve) — dropped, not deferred. proof/channel-art.html
is deleted and the two candidate routes are withdrawn. Nothing in the kit depended on it:
it produced no keys, no families, no fragment entries and no baseline rows, which is why
it can be removed rather than unwound.

THE BUILD COST IS ANSWERED (drop twelve). BUILD.stream(fn, opts) yields one frame at a
time and drops it, so peak memory is one frame regardless of library size — the OOM at 286
of 924 was every caller RETAINING its P objects, not any plate being expensive. It emits
every file the manifests declare: 1,191 for 924 frames (921 tagged, 267 animated bases, 3
static). An ingest walking framesOf() alone writes the frames and never writes the base.
scripts/build_batch.mjs is the documented fallback for when the process is the constraint.

roles.fragment.json  where each new plate is allowed on screen. A FRAGMENT to be
                 merged by hand — deliberately not named roles.json, which is the
                 renderer's own file (hostRoles, hostPoses, roomRoles, chapterTypes,
                 wardrobe) and must not be overwritten by a copy operation
CHANGES.md       the pack — read the top section first
README.md        run order, and what to push back on
```

## Run order

1. `proof/title-ground.html` — **§1, and the one decision this pack is asking
   for.** Three title treatments on the two worst walls in the family and on the
   clean one, with the measured contrast floor inside the published title box. The table
   at the foot is the whole-family audit: sixteen of the twenty-two chapter
   openers already have drawn ink under that box today. Four room draws plus the
   audit, about twenty seconds. The measured columns need the page served over
   http (`python3 -m http.server`) — a `file://` canvas comes back tainted and the
   page says so rather than printing a number it cannot stand behind. The renders
   themselves need nothing.
2. `proof/new-plates.html` — **§2, the quarter.** Ten new assets, each filled twice
   from unrelated numbers at different counts. Read the §2.1 note at the end of the
   eight-quarter row before the rest: it is the trap that plate sets and the reason
   `figures/qoq-yoy` exists.
3. `proof/preflight.html` — builds all 270 assets at all 924 frames and runs the
   checks, now sixteen, A–P. **Check P is new in drop eight**: every box that declares
   `maxLines`, against the lines it declares, at the kit's own 1.16em pitch. It reports
   2,280 type slots, 357 of them multi-line, and **none short of the lines it declares**
   — the derivation confirmed library-wide rather than trusted. Running it also turned
   up **check E failing since drop six** on all four `charts/insider-flow` plates, which
   is resolved by declaring them still-by-design: every mark on them is the pinned axis
   the trades are read against, the same argument `structure/implied` carries. The
   omission was in the list, not in the artwork. The buttons rewrite
   `audit/baseline-14.json` and `audit/breathe-map.json`; both are in the pack,
   generated from this engine, and since the build is deterministic you should
   prefer the copy you generate from the engine you are holding.
4. `proof/two-against-three.html` — the §1.1 decision. Move the slider before
   deciding; the question is "2 or 3 at what fps".
5. `proof/render-scale.html` — the review pass at 1:1. Fourteen sections, one at a
   time. **Start at `?s=14`**, then `?s=10`. §14 holds the worst of the three findings:
   `host/empty-chair`'s published scaling contract renders the same chair 64% larger
   with nobody in it — taller than the man who sits in it — on the one cut the plate
   exists for. §10 holds the plate that does not render at all (`figures/qoq-yoy-9x16`,
   an eight-character figure in a seven-character box) and the answer to the 23-unit
   seasonality column. Verdicts are in CHANGES, drop eight.
6. `proof/captions.html` — §5, and the one place this pack asks you a question
   rather than answering one.

Nothing in the proof pages needs a rasteriser or a server — open them directly.

## §1 is decided: `card`

`engine/build.js TITLE_GROUND = "card"`. All 22 chapter openers carry a drawn
ground behind the title; the title slot does not move on any plate and the type
colour is unchanged, so nothing in the renderer needs touching. The room
baseline is reset accordingly — `audit/baseline-14.json` is the new one.

**Start with the live UNVERIFIED list at the top of `CHANGES.md`** — one list, each item
stamped with the drop it survived, replacing the eight per-section lists a reader used to
have to assemble.

**Drop eleven applied all five of drop ten's findings.** What is left to push back on is
one gap rather than a list of defects — see item 9 in the live list — plus the four
judgements in drop eleven's own UNVERIFIED block, of which the one worth a look first is
landscape `cash-flow`'s lost size step.

Drop ten's findings, for the record, in the order they were taken:

1. **The confession treatments disagree on their body measure** by 4 characters a line
   landscape and 3 portrait — so a confession written to the ledger does not fit the
   statement, and an over-budget fill renders nothing. It blocks the treatment pick, and
   it is the chair's failure shape again: each plate correct alone, the pair not measured.
2. **`figures/big-number-l2-16x9` cannot draw a five-character number.** Four-character
   budget on a 350u role, so `87.4%`, `1,284` and `$15.6bn` all render blank — in the
   plate whose entire job is one number.
3. **`cash-flow-9x16`'s totals hold three characters** against the landscape twin's eight,
   and less than the cells they total.
4. **Check C is aimed at 2 of 14 talk strips.** Right method, hardcoded list; deriving the
   set the way check D derives its own turns 4 comparisons into 28.

And the gap behind findings 1–3: **nothing in the kit asks whether a derived budget is
big enough for what a script actually writes.** Sixteen checks confirm `maxChars` is
derived and consistent; none compares it to realistic content. That check needs a human to
author one realistic string per role, which is why it does not exist yet.

The three earlier proposals are all resolved: drop nine applied them.

1. `host/empty-chair` publishing its own 0.6083 ratio. A contract and manifest change, not
   a drawing change, and the cheapest of the three. It is also the only one where the
   current behaviour is wrong rather than tight.
2. `figures/qoq-yoy-9x16`'s figure type step, which is what makes that plate render at all.
3. Whether the confession ledger's block height should buy its 4.4 units of descender
   clearance. Optional.

Everything else is in the UNVERIFIED lists.

## And the gate

The gate in §1.5 is **opt-out**: on a data plate everything breathes except the
marks wrapped in `pin()`. The pinned list is short and named in CHANGES. If you
disagree with any single entry on it, that is a one-line change and worth making
before drop two builds on top of it.

## And one you did not ask for
`figures/compare-side-9x16` has been redrawn. It was rendering the stacked plate
under its own key — byte-identical to `compare-stacked-9x16` across all three
frames — which the new baseline caught on its first run. If you would rather that
key simply not exist than be a real side-by-side on a phone, say so; it is a
deletion rather than a redraw and I would rather you chose it than inherit my
guess.
