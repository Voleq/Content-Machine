# Dennis v2 — delta pack 15

## Drop fifteen — the two failing host plates

`1353 passing, 2 failed` on `394c1be`. Both are role-membership on the surface and only
one of them actually is.

### §1 · `sitting-at-desk` in `to-camera` — the fragment's instruction caused it

**Your (a).** Take it out; it stays in the pose roles, where a floor exists. Do not make it
a framing — it is a full figure at 0.739 of a standing height and `meta.seated.heights`
exists so the compositor can scale it against that ratio, so a `-close` variant would break
the scaling contract to fix a membership error.

`to-camera` lives in the renderer's `roles.json`, not in the kit — but the kit is where the
bad membership came from. `roles.fragment.json` `_hostSeated.hostPoses_fragment` read:

> *"add `sitting-at-desk` to the seated role **and to any role a LONG chapter opener
> uses**"*

A long chapter opener does use `to-camera`. **The instruction was followed exactly and
produced the defect** — which is the more useful finding than the membership, because the
next pose added to the kit would have gone the same way. It now says *a POSE role*, with
the invariant stated as a rule a check can run:

> A role the renderer swaps to for a floorless room may contain only plates with
> `floorLineY: false`.

Measured against the emitted manifest: **28 host plates qualify, 22 do not.** The field is
published on every host plate precisely so this is checkable rather than remembered.
`host/sitting-at-desk` now carries a `host_roles` line saying which roles it may not enter.

### §2 · `empty-chair` "is not a cut-out" — it is one, and two fields were missing

**Your (a), and cheaper than the write-up assumes: no alpha to publish, nothing to
re-draw.** The plate has been an alpha cut-out since drop four — `ground: "none"`,
`grain: null`, composites onto a host-anchor, and its own `dataPolicy` string has said
*"alpha cut-out, no ground"* in prose the whole time.

What it never published is the two fields a gate can read. `engine/plates.js emptyChair()`
was written apart from `hostFigure()` and `hostHead()`, both of which set
`cutout: true, alpha: true` in that same meta object. This author didn't. So the test read
absence as denial, and the prose that contradicted it was in a field nothing parses.

Fixed in `plates.js` — two fields, `host/manifest.json` re-emitted. **50 host plates, 0
geometry diffs, 0 frame-hash diffs, exactly one plate's meta changed.** The role membership
needs no change: it stays in `beat`.

It is furniture rather than a pose, and your (b) is coherent, but furniture that goes
*where he would have been* is what a host role is for — and (b) costs it a route it
already has.

### §3 · Found while checking: the fragment held the pre-drop-eight scaling contract

`roles.fragment.json` `host/empty-chair.renderer_contract` still read *"scales like a
figure: (floorLineY - figure.y) to the anchor height directly. The seated ratio does NOT
apply."* Drop eight overturned that — it is the §14 finding, the chair rendering **64%
larger with nobody in it, taller than the man who sits in it**, on the one cut the plate
exists for. The engine and the manifest have carried `meta.chair.heights.ratio` (0.608)
since; this entry was the last copy of the old reasoning, sitting in the file the renderer
merges from. Marked superseded rather than deleted.

Same shape as the `_titleGround` stale note in drop twelve, and the same lesson: a stale
note someone trusts is worse than an absent one.

### §4 · The invariant is now a command, not a sentence

`scripts/check_roles.mjs` takes the renderer's `roles.json` and checks host role
membership against what the plates publish. Both failures as two rules:

```
node kit/scripts/check_roles.mjs ../roles.json
```

**Rule 1** — a substitution role may contain only plates with `floorLineY: false`.
**Rule 2** — every member of any host role must publish `cutout: true`.

Run against main's current `roles.json` it reports **one violation**:
`[rule 1] to-camera -> host/sitting-at-desk : floorLineY 1728`. Rule 2 is silent because
§2's fix is already in the engine — before it, rule 2 named `host/empty-chair`. With
`sitting-at-desk` out of `to-camera` it is clean. `--census` needs no `roles.json` at all:
**50 host plates, 28 framings, 22 poses, 0 not publishing a cut-out.**

This is the kit's half and it constrains the set the renderer picks from. It does not make
the substitution site verify its pick — that guard is yours, and both are needed.

### §5 · Your §3 and §4, acknowledged

The unguarded substitution is theirs and I have not touched it. Worth saying that the guard
and the invariant in §1 are the same check from two sides — they verify the plate they
picked, the kit constrains the set they pick from — and either alone would have stopped
this render defect.

Urgency read as you set it: shorts unaffected, and the first long that picks
`short-interest` ships wrong. Neither fix needs a re-render.

---

# Dennis v2 — delta pack 15 · drop fourteen

## Drop fourteen — the fourteen manifests re-emitted from the engine in main

**270 plates, 3,033 slots, 924 frames. No plate changed, no geometry moved, nothing
redrawn.** Fourteen files rewritten, one directory deleted, two scripts added.

### §1 · What the ingest was actually refusing

PR #25 fails on a pristine clone with *"slots disagrees with the shipped manifest"* — and
the geometry is innocent. **Zero differences in x, y, w or h. Not one, on any plate.** What
differs is fields the engine publishes that the shipped copy does not carry.

The cause is one line in `engine/hand.js`:

```js
P.slots[key] = Object.assign({}, extra || {}, { x, y, w, h })
```

A slot carries **whatever its author passed**. delta-14's writer was a throwaway script
that copied a whitelist — `x, y, w, h, role, align, maxChars, region, note` — and dropped
every other field silently. So the manifests were not wrong about the plates; they were an
incomplete transcript of them, and the ingest compares the whole slot object.

**The reported diff was a partial one.** The failure names eighteen fields; the full
reconcile against delta-14 finds **twenty-nine, on 146 plates** — the eighteen plus
`ground` (56 slots), `groundBox` (56), `scales` (40), `contact` (24), `count` (14),
`steps` (6), `columns` (6), `fit` (6), `cropped` (4), `cropNote` (4), `extentOf` (2). Worth
knowing before the next pack is checked against a list of eighteen.

Measured, emitted against shipped: **0 geometry diffs, 0 plates added or removed, 0
slot-count changes, 0 fields lost.** The change is purely additive metadata, which is what
"an engine from one drop paired with manifests from another" should look like when the
engine is the one telling the truth.

### §2 · The fix is code that ships, not a script someone had lying around

`scripts/manifest_core.js` is now what a manifest IS. Slots are emitted **verbatim** from
`Plate.manifest()` — no whitelist, nothing to fall behind. A plate author who adds a slot
field gets it in the manifest by construction, and this defect cannot recur by omission.

`scripts/emit_manifests.mjs` is the route: all fourteen in place, `--family` for one, and
**`--check`**, which emits into memory and diffs against the tree. A clean `--check` means
the manifests in the tree came from the engine in the tree — the invariant the whole pack
depends on and the one nothing was enforcing. It is one command and it is the check that
would have caught this.

The header is also complete for the first time. `engine/build.js` FAMILY_NOTES has always
been the declared source — *"so RENDER.manifestFor emits a complete file, header and
assets from one source"* — and delta-14 typed its own headers into the writer and never
emitted the declared ones at all. They are in now: `engine`, `coordinateOrigin`, `units`,
`bakedText`, `reproduce`, `dataPolicy`, `slotKinds`, `surface`, `motion`, `scaleAuthority`,
`frameShape`, `baseFileRule`, `boilPolicy`, `maxCharsNote`, per family.

### §3 · Location, and the directory that is now deleted

`kit/<family>/manifest.json`, beside the family's plates, which is where the ingest's glob
looks. delta-14 shipped under `kit/manifests/<family>/`, which that glob does not match:
the ingest finds no manifest beside any family, reads the pack as zero assets, and
reconciles against nothing. **That directory is deleted rather than left in place** — two
copies of a manifest is the condition that produced this bug, and the stale one is not
worth keeping for reference when it can be regenerated in one command.

### §4 · THE HASH CHANGED, AND THIS IS THE ONE THING TO READ BEFORE MERGING

**No hash function ships anywhere in `engine/`.** The one delta-14 used cannot be recovered
or re-run — its values are not reproducible from the engine you are holding, which is the
same class of defect as the slots and went unnoticed because nothing recomputes them.

So the emitter declares one: **FNV-1a 32-bit over the emitted SVG string**, written into
every header as `hashAlgo`, recomputable with `MANIFEST_EMIT.hash(svg)`. **Every frame's
hash therefore changes from delta-14** — 924 values. Nothing in the kit reads them as an
identity; they are a fingerprint for *did this byte-sequence move*. A hash nobody can
recompute was worth less than a hash that changes once.

**If `ingest_kit.py` compares frame hashes against its own rendering, it will now disagree
with every frame until it adopts `hashAlgo` — check that before merging.** It is the only
field in these files whose value is not derived from something already in the tree.

### §5 · What was NOT verified, stated plainly

**`scripts/ingest_kit.py` has not been run against this pack.** That script is not in the
kit — it lives on the pipeline side — and the reconcile above is a field-by-field diff of
emitted-against-shipped run in the engine's own runtime, not the ingest's verdict. It
establishes that the fourteen files agree with the engine in main and that nothing but
added metadata and the hashes moved. It does not establish that the ingest accepts them.

**The one command still to run, on a clean clone, before this ships:**

```
node kit/scripts/emit_manifests.mjs --check    # expect: all manifests match the engine
python scripts/ingest_kit.py kit               # expect: 270 plates, 3,033 slots
```

---

# Dennis v2 — delta pack 14

## Drop thirteen — the boil answered, the overlay contract, the six stems

**270 assets, 924 frames, 0 errors, 0 text nodes. No plate changed.** One new proof page,
one contract written into the engine, four fragment entries added.

### §1 · Every data plate boils. Was that the intention?

**Yes, deliberately — and the premise of the question is wrong in a way that is the
answer.** Answer (1), with one real defect found inside it.

**No number in this kit wobbles, and none can.** A plate contains no content; it contains
slots, and every figure on a numbers sheet is type the compositor sets into a slot box at
video time. **Measured: 315 slot boxes across 12 plates, 0 units of deviation across all
three frames.** The type is pinned by construction, not by restraint — if the figures
moved, the proof page's type layer would have to be rebuilt per frame, and it is built once
and never touched by the clock.

The 47 plates did not become boiling plates. The boil was turned on for their **furniture**,
behind a gate: with the gate up a mark takes the boil offset only if it was drawn inside
`HAND.breathe()`. That reasoning is not missing from the pack — it is **§1.5 in
`engine/build.js`**, at the point the gate is raised, and it retracts the old rule
explicitly and names what stays pinned: *axis lines, series lines, slot underlays and
highlight boxes.*

**So the documentation defect is real and it is worse than reported.** `compose.py`'s
paragraph states the old rule as settled fact — and so did `build.js` itself, **2,848
characters above its own retraction, in the same file.** That comment read *"A data plate
does NOT boil"* until this drop. A reader who stops at the first statement gets the old
rule twice, from two files, one of which contains the correction. Both are now corrected;
`compose.py` is the pipeline's and is yours.

#### The defect inside the answer: the gate leaks in exactly the place §1.5 names

**Thirteen plates move a band or hatch behind pinned type** — the third exclusion,
violated:

| plates | measured |
|---|---|
| `tables/numbers-sheet-*` (10) | 86–191 band marks moving under 6–18 pinned cell boxes, displaced **0.01–3.70 units**. Zebra row striping is a slot underlay. |
| `structure/row-spotlight` (2) | 133 landscape / 177 portrait band marks under 6 value boxes. A **highlight box**, named in the exclusion list by those words. |
| `structure/multiple-bridge-16x9` | 80 band marks under 3 value boxes. |

And the tell the brief spotted was right, but inverted. `overlays/row-band` is frozen
*because the figures behind it are held still* — and that reasoning is sound. What happened
is that the protection was applied to the **overlay** version of a row band and missed on
the ten plates that draw their **own**. The problem `row-band` is protected from has not
gone away; `row-band` is the only place it was fixed.

**Where the gate holds**, and why the answer is not "turn the boil off": `cash-flow`,
`big-number`, `peer-strip`, `line-dense`, `timeline`, `unit-ladder` boil 1–76% of their
marks and **none of it passes under a value box**. `peer-strip` moves 178 of 233 marks and
hits nothing — it is all hatch. Seven chart plates have exactly one hairline crossing their
value labels, displaced **0.83 units** (1.7px delivered); covered by §1.5's own sorting
principle and named rather than fixed.

**PROPOSED, NOT APPLIED:** add the band and hatch fill used by those 13 plates to the same
pinned set that already holds axis lines, series lines and underlays. It is a **gate
change, not a redraw, and not a manifest change** — these plates should keep
`playback: loop`, because their paper edge and rules should go on breathing. Reverting them
to `static` would fix the leak by reintroducing the defect §1.5 was written to remove.

#### The render is the deliverable: `proof/boil-motion.html`

The frames on a timer at the fps the manifest declares, so the boil can be **watched** for
the first time. `numbers-sheet-5r` and `cash-flow` as asked, plus `row-spotlight` and
`bars-8q`. Three columns each: as shipped, **the proposed fix previewed** by substituting
frame one's band paths (123 of 227 paths on the sheet — nothing in `plates.js` touched),
and the moving ink isolated. Controls for 1/2/8 fps, figures on and off, and a 1:1 crop row
where one canvas unit is one CSS pixel. Frames are built once and the timer swaps them; a
loop that called `draw()` per tick would be measuring the engine, not the plate.

### §2 · The overlay contract, in the manifest

Eight clauses on all seven `-blink` strips, and **every one is derived from the
registration rather than chosen**, which is why they are rules and not preferences.

- **Which idle frame:** index-matched, blink `_fNN` over idle `_fNN` — derived, not
  conventional. The two strips are authored from **byte-identical args at every index**
  (bob 0/3/2, boil 3/4/6). Verified on all seven pairs.
- **Why not over a talk frame:** talk is all three frames at **one** boil index; blink
  carries idle's 3/4/6. A blink over a talk frame puts a lid drawn at boil 4 over a socket
  drawn at boil 1 and the linework will not meet. Registration forbids it. A blink while
  speaking is a **new strip** at the talk index, not a reuse of this one.
- **Cadence:** ~100ms, uniform on [3.0s, 4.5s], resampled after each blink. Seeded from the
  asset's own `seed` advanced by **blink count since the video started** — never by shot
  index, never reset at a cut. Reseeding per shot is the implementation that produces the
  lockstep defect: every cut restarts the clock, so he blinks at the same offset after each
  cut and it reads as a tic.
- **At a cut:** a blink in progress is **abandoned**, not carried across — the registration
  does not hold across poses. Lids open on the new shot, cadence clock continues. And no
  blink starts within 150ms of a shot end: one clipped to 40ms reads as a dropped frame.

### §3 · The six unreachable stems — four gaps and a checker mismatch

**Two of the six were already mapped.** `structure/said-happened-5` and
`structure/sensitivity` have had entries all along, as `-16x9` keys. The check compares
**bare stems** against a fragment keyed by **aspect** — 57 of 60 keys carry a suffix, only
the three host poses are bare — so a stem lookup misses every aspect-qualified entry. It
reports reachable plates as unreachable, which is the safe direction and still wrong: it
cannot distinguish a real gap from a keying mismatch. Recorded in `_reachability` with a
proposed fix, **not applied** — the check is the pipeline's, and whether mappings may differ
per aspect is a decision, not a bug. They currently do: several portrait keys carry
different beats from their landscape twin, so collapsing to stems would lose that.

**Four were genuine gaps**, now mapped:

| stem | now says | why |
|---|---|---|
| `said-happened-3`, `-4` | `guidance-estimates` `management` `resigned-close` · evidence, land | Same argument and same homes as `-5`, which was mapped. The count variants never got entries, so a director asking for three pairs had no reachable plate while five pairs did. |
| `whiteboard-3`, `-4` | `one-framework` `moat` `how-the-money-is-made` · open, evidence | `one-framework` is nearly literal — the chapter *is* a framework drawn out, and this is the only surface in the kit for drawing one. |

**And `moat` is now reached, which closes the older gap from the other side.** It was the
one chapter type of the sixteen that no plate served, and I had proposed building something
for it. A whiteboard is the answer: a moat argument is a structural claim that needs a board
rather than a chart, and this plate is panels-and-arrows with no data commitment. **That
half is a proposal, not an assumption** — reject it if a director reads `moat` as a
comparison rather than an explanation. **All sixteen chapter types are now referenced**; 64
keys, every name resolving.

### UNVERIFIED — drop thirteen

1. **`boil-motion.html` is a browser at its own frame rate, not the render path.** The
   frames are the kit's and the fps is the manifest's; the compositing is CSS. Whether 2fps
   through resvg and the encoder looks the same is the cut's answer.
2. **Whether the 0.83-unit hairline is visible to a person** is what the page's controls are
   for, and I cannot settle it from here. Same for whether the pinned preview is
   distinguishable from shipped at real viewing distance.
3. **The 13-plate band finding is measured; the fix is previewed, not built.** The preview
   substitutes paths in the emitted SVG. A real gate change may catch marks the substitution
   misses, or miss marks it catches.
4. **The reachability explanation is inferred.** I have not seen the check's source — it is
   the most likely reading of its output against this file's keys, not a confirmed one.
5. **The blink contract has no consumer yet.** Every clause is derived and checked against
   the strips, and none has been played. The cadence numbers in particular (3.0–4.5s, 150ms
   guard) are judgement expressed as a range, not measurements.
6. **`compose.py` still states the old boil rule.** It is the pipeline's file. The two in
   the kit are corrected.


## Drop twelve — §0's manifests, the build cost, and two cleanups

**270 assets, 924 frames, 3,033 slots, 0 errors.** No plate changed. This drop is the
blocking §0 deliverable plus the other three items. `engine/build.js` gains `stream()` and
`families()` — additive, no existing function touched — and `scripts/build_batch.mjs` is
new.

### The build cost — `BUILD.stream()`, and the batch script as the documented fallback

Both, as asked. **The fix is the shape of the call, not an optimisation.**

The OOM at 286 frames of 924 is not a plate being expensive: the largest single frame in
the library is a room at ~1.5mb of SVG, and the whole library serialised is survivable.
What is not survivable is **holding** it. Every caller so far — check A, the baseline
generator, every proof page — walks `LIB`, calls `draw()` per frame and keeps the returned
`P` objects in an array, because the next check wants them. A `P` is not a string; it holds
its path list, its slot table and its manifest, and 924 of those retained at once is what
the kernel killed.

`BUILD.stream(fn, opts)` yields one frame at a time, hands it over, and drops every
reference before building the next. **Peak memory is one frame plus whatever the consumer
keeps** — for an ingest writing a PNG and moving on, that is one frame, flat, whether the
library is 270 assets or 2,700.

```js
BUILD.stream(function (f) {
  writePNG(f.path, rasterise(f.svg, f.delivered));   // f.svg is a STRING
});                                                  // nothing retained
```

**And it found a defect in §0's own contract on the way in.** Streaming three plates and
reading the paths back showed a static plate emitting its one untagged file correctly and
an animated plate emitting `_f01.._f03` **and no base at all** — because `framesOf()` does
not return the base, while every manifest declares `files.base`. An ingest walking
`framesOf()` alone writes the frames and never writes the base it promised. `stream()` now
emits **every file the manifest declares**: **1,191 files for 924 frames** — 921 tagged
frames, 267 animated bases, and the 3 static plates' single untagged file. The base comes
from frame one's own args, so `baseIsFrame` is true by construction rather than by a copy
step the ingest has to remember; verified byte-for-byte at 1,522,843 bytes on
`room/desk-front-16x9`.

**What `stream()` does not do**, said rather than discovered: it does not make the build
parallel, and it does not help a consumer that accumulates. A caller that pushes `f.svg`
into an array has rebuilt the original defect with extra steps — which is exactly what
every existing caller does, deliberately, because a check comparing frame against frame
has to hold two. `stream()` is for the **ingest**, which holds none. The proof pages are
unchanged and still build eagerly.

#### `scripts/build_batch.mjs` — the fallback, and when it is the right answer

For the case `stream()` cannot reach: **the process itself is the thing that will not
survive.** If the host is memory-capped below one family, or the runtime leaks across
iterations, no in-process iterator helps — the only fix left is a smaller process. So: one
process per family, fourteen of them, each exiting and returning its memory to the OS
before the next starts.

A family is the unit for two reasons. It is the largest chunk that **actually built in one
pass** when §0's manifests were generated — one pass over all 270 timed out and had to be
chunked, with `room` alone needing splitting in two, which is the same failure as the OOM
reached by a different road. And manifests are already per-family, so a batch that fails
names a file you can regenerate alone rather than invalidating the run.

It loads the five engine files the way the proof pages do — plain scripts onto one global,
not modules, so nothing here forks them — streams each family, asserts **no `<text>` nodes
per frame** rather than trusting the guarantee, and shells out to `resvg` for PNG so the
bytes match what the render path reads. `--list` prints the per-family frame counts;
`--family` regenerates one.

**What it costs, stated rather than buried:** fourteen process starts, fourteen engine
parses, no shared work between families, and it is slower than one streaming pass by
design. It also **cannot catch a cross-family defect**, because nothing in it ever sees two
families at once — the same blindness the family-chunked manifest generation has, and worth
knowing before this becomes the default rather than the fallback.

### §0 · the fourteen per-family manifests — the blocking deliverable

`manifests/<family>/manifest.json`, one per family, **generated from the engine and never
hand-edited**. 14 files, **270 plates, 924 frame files, 3,033 slots.**

Each plate entry carries `canvas`, `delivered` (canvas × 2), `exportScale`,
`playback`/`fps`/`frameCount`, the `_f01.._fNN` file list with a per-frame FNV-1a hash,
every slot with its derived budgets, the type roles, and the plate's own `meta`. The schema
is not invented here — `engine/audit.js` already validated manifest entries against
`canvas`, `delivered` and `exportScale`, so the generator runs `scaleVerdict` on every
entry as it writes it. **All 270 pass.**

Verified at generation rather than asserted: `delivered` = canvas × 2 on all 270;
`exportScale` 2 everywhere; the frame tags run `_f01.._fNN` contiguous with no gaps; and
every key matches `family/name-aspect`.

**One finding, and it is a contract correction.** My first pass wrote `baseIsFrame: true`
on every plate, which is wrong for the three static ones — `overlays/row-band` and both
`overlays/lower-third` have `frameCount: 1` and **no frame one to be identical to**. The
base is the whole asset and the only file. Claiming `true` would have an ingest look for a
`_f01` that does not exist and an audit compare the base against a missing file. Those
three now carry `baseIsFrame: false` plus `staticSingleFile: true` and a note saying the
flag is false because there is no frame one, *not* because the base disagrees with one —
two different claims, and the manifest now publishes the right one. The
base-equals-frame-one contract is a claim about animated plates only, which is now said in
`frameNaming` rather than assumed.

### §3.5 channel art — CANCELLED

Dropped, not deferred. `proof/channel-art.html` is deleted and both candidate routes are
withdrawn. Nothing in the kit depended on it — no keys, no families, no
`roles.fragment.json` entries, no baseline rows, no reachability row — which is why it
comes out by deletion rather than by unwinding. Every claim it carried about the profile
and the banner is withdrawn with it; the unverified item about judging the profile against
a real page is withdrawn too, because there is no longer a candidate to judge.

### `_titleGround.switch` said `null`; the shipped value is `"card"`

Corrected. The same object's `decided` field said `CARD` the whole time, so the entry
disagreed with itself for three drops and the stale half read as evidence that the
treatment was still off. Same rule as the baselines: **a stale note someone trusts is
worse than an absent one** — and it applies to prose in a data file as much as to a number.

I scanned the fragment for the same shape. One other field claims a shipped value,
`_timeOfDay`'s *"it ships null"*, and that one is **accurate**: §4.2 shipped dusk as 24
assets rather than as a mode, so `TIME_OF_DAY` is genuinely null and the note is right.


## Drop eleven — the five fixes, applied

**270 assets, 924 frames, 0 errors, 0 text nodes. No new assets.** You said decide, so all
five of drop ten's findings are applied and `audit/baseline-14.json` is regenerated. Four
plate families changed geometry: `structure/confession` (all four), `figures/big-number-l2`
(landscape), `tables/cash-flow` (both) and `structure/sensitivity` (metadata only).

### 1 · The confession pair now has one measure

The indent is the same on both treatments and only the statement draws a rail in it.

```
                    before                        after
  ledger-16x9       x=190 w=1580  68 chars/line   x=241 w=1529  66
  statement-16x9    x=241 w=1529  66              x=241 w=1529  66   identical
  ledger-9x16       x=84  w=920   37              x=156 w=848   34
  statement-9x16    x=156 w=848   34              x=156 w=848   34   identical
```

**A confession written once now fits either treatment**, so the pick is a drawing choice
rather than a copy constraint — which unblocks it. The ledger gives up the 2–3 characters
a line it had; both plates still clear their captions and fill 0.61–0.82 of the band.

### 2 · `big-number-l2`'s size is derived per layout

Landscape **350u → 214u**, and the budget goes **4 characters → 7**. `87.4%`, `1,284` and
`$15.6bn` all render now. The kit's own rule was already written above the function —
*size = columnWidth / (maxChars × 0.6)* — and layout 1 obeyed it at a 1,480-unit measure
while layout 2 hardcoded a 900-unit column and inherited layout 1's size. It now derives
from whichever column its own layout uses, and publishes `meta.hugeDerivation` saying so.

**Still true and now consistent:** portrait big-number holds **six** characters on both
layouts, so `$15.6bn` at seven wants landscape or the short form `15.6bn`. That is the
family's declared portrait budget rather than a defect — l1 has shipped at it — and it is a
**directing rule**, in the same species as the seasonality column.

### 3 · A total can no longer blank where its own lines render

Portrait **44u → 32u**, budget 3 → 5. And a second pass on the same fix, worth recording
because the first version was wrong: I kept landscape's step up, since 36u derives 8 there
and every realistic total I tested fits. Measured, that **still violated the rule** — the
landscape cells derive 11, so a nine-digit total would blank while its own line items
render. A total is a sum, so it is the value most likely to be longest on the plate, and a
173-unit column cannot hold both the step up and the cells' budget.

So the budget wins on both aspects: landscape **36u → 26u**, budget 8 → 11, and the total
is distinguished by weight 700 and the rule above it, which is how the rest of the kit
marks a total anyway. **Both aspects now satisfy `total ≥ cell`.** Landscape gives up a
visible size step; that is the cost and it is named rather than buried.

### 4 · `sensitivity`'s two slots are control channels, not zero-sized regions

Metadata only, not a mark changes. They carry `control: true`, `drawn: false`,
`dimensionless: true` and a note saying w/h have no extent and must not be used to compute
a fill area or a scale. "Not drawn" and "zero-sized" were different claims and the plate
published the second.

### 5 · Check C's coverage is derived

`B.LIB.filter(i => /-talk$/.test(i.key))` instead of `["close-up","medium"]` — **2 strips
to 14, 4 comparisons to 28**, including `sitting-at-desk-talk`. The method never changed;
it was pointed at two plates. This closes the mouth contract on the seated pose, which had
been on the unverified list since drop eight under the wrong explanation.

The lesson is in the check now: **a check that passes because it never looked is worse than
a dishonest declaration**, which at least leaves a sentence to argue with. Check D was
already deriving its set; C is the one that named it.

### UNVERIFIED — drop twelve

1. **`stream()` has been exercised on families, not on the whole library in one call.**
   The per-family runs are clean and the arithmetic is flat by construction, but the run
   that matters — 1,191 files in one process against the real ingest's memory cap — is the
   Python side's to make, and it is the run that was failing.
2. **`build_batch.mjs` has never been executed.** It is written against the engine's real
   surface and its loader shape is verified here, but this sandbox has no node process, no
   filesystem to write PNGs into and no `resvg`. The `--png` path in particular invokes a
   binary I cannot call. Treat it as reviewed code, not as a tested script.
3. **The manifests were generated before `stream()` existed**, by the chunked path. They
   are consistent with it — same `framesOf()`, same `exportScale`, and the base-file
   correction went into both — but they have not been regenerated *through* `stream()`, so
   the two agreeing is an argument rather than a diff.
4. **1,191 is derived, not written.** 921 + 267 + 3 follows from the frame counts and the
   static/animated split; nothing has counted files on a disk, because nothing has written
   any.

### UNVERIFIED — drop eleven

1. **The five fixes are asserted by the build, not watched.** Each is geometry, each is
   measured, none has been seen in a cut. *The live list at the top is unchanged otherwise.*
2. **The confession's shared measure is asserted at authored newlines.** Both treatments
   now derive 34 portrait and 66 landscape, so a body written once fits both *as authored*.
   Line breaking is still the compositor's, by measured width — and this was the assumption
   I said in drop ten I trusted least. It is now the same assumption on both plates instead
   of two different ones, which is better and not settled.
3. **Landscape `cash-flow`'s lost size step is a judgement.** The arithmetic is certain;
   whether a 26u total reads as a total against 26u cells, on weight and a rule alone, is
   something to look at in a real frame. If it does not, the answer is a wider column, not
   a bigger type size.
4. **`big-number-l2` landscape at 214u has not been seen at 1:1.** `render-scale.html` has
   no section for the figures family. The budget is derived and the geometry is measured;
   214u is still a 39% reduction in the headline number on that layout and it should be
   looked at before it is cut.


## Drop ten — two cleanups, one decision, and a findings pass

**270 assets, 924 frames, 0 errors, 0 text nodes, sixteen checks passing. No plate
changed, and nothing in Part 3 is applied.** The measure/apply split is the default from
here, so this pack measures and proposes; a separate approve-then-apply drop follows.

Two of the three decisions could not be resolved because their inputs did not arrive —
said plainly at the top rather than buried, because both are blocking:

- **2.1 the wordmark and strapline** came through as `[FILL IN]`. Still placeholders.
- **2.2 the profile** needed the attached screenshots; the brief carries
  `[SCREENSHOTS — desktop light, desktop dark, phone, subscriptions list]` and no files.
  Unchanged from drop nine: candidate A has no edge against a light page, and I cannot
  see a real page to judge it.

### UNVERIFIED — the live list

Consolidated, at the top, because a reader should not have to assemble it from eight
per-section lists. Each item says which drop it survived. The per-section lists below are
stamped historical and the ten items answered by drops eight and nine are **removed**
rather than struck through — a list a reader still has to parse is the stale-baseline
problem in another form.

**Can only be settled by a cut or a real page** — do not chase from here:
1. **Nothing in the kit has been watched moving.** Every breathe share, boil index and
   loop claim is arithmetic. *Survived eight, nine, ten — and it is now the largest
   unverified class in the pack.*
2. **The chair fix in a cut** — him, then his chair. *Survived nine.*
3. **Night cut against dusk.** Reads as a difference side by side; whether a cut between
   hours reads as time passing or as a continuity error needs an edit. *Survived eight.*
4. **Neither channel-art candidate on a real YouTube page**, either theme, real device
   pixel ratio, next to other channels' marks. *Survived nine, ten.*

**Waiting on something outside the kit:**
5. **The captions `force_style`** — libass, not a proof page. *Survived eight, nine, ten.*
6. **The end card's keep-out fractions** against YouTube's current spec. The 1:1 pass
   confirms the content band clears the zones *as published*; it cannot confirm the zones.
   *Survived eight, nine, ten.*
7. **Renderer-side reachability of `roles.fragment.json`.** Every name resolves against
   the sixteen, checked by walking the file. What has not happened is the renderer loading
   it and reporting reachability from its own side — the check that would catch a
   *correct* name in the wrong chapter. *Survived eight, nine, ten.*
8. **`insider-flow`'s shared-scale contract.** A renderer using two scales draws a plate
   that looks entirely correct. *Survived eight, nine, ten.*

**Closed by drop eleven** — all four of drop ten's in-kit findings are fixed: check C's
coverage, the two blank-rendering budgets, the confession measure and sensitivity's
regions. What replaces them is one gap rather than four defects:

9. **Nothing in the kit asks whether a derived budget is big enough for what a script
   writes.** Sixteen checks confirm `maxChars` is derived and consistent; none compares it
   to realistic content. Drop ten found four instances of it by hand and drop eleven fixed
   them, which is the wrong end of the problem — the next one will be found the same way.
   The check needs one realistic string per role, authored by a person. *New in eleven.*

**Rasteriser and instrument caveats**, unchanged: every measured colour or contrast number
in this pack is the browser's rasteriser, not resvg; the vertical-fit pass uses the right
pitch and faces but line *breaking* is the compositor's; and check P is geometry, so it
cannot assert the compositor uses the published pitch. *Survived eight, nine.*

---

## PART 1 · The two cleanups, applied

### 1.1 Prose in a list field

Both `overlays/lower-third` entries carried a sentence in `beats`. Moved to `note`, and
`beats` is now **absent rather than empty** — the plate genuinely has no beat, it is
persistent furniture composited over whatever the format is showing, and an empty list
would read as "no beats found", which is a different claim.

**The rest of the fragment, scanned for the same shape.** The criterion was mechanical
rather than a read-through: a vocabulary name is lowercase, hyphenated and has no spaces,
so any value in `chapter_types`, `shot_ids`, `formats` or `beats` containing a space or
an em dash, running over 24 characters, or starting with a capital, is prose wearing a
name's clothing. **Two hits across 60 keys, both the ones named.** The inverse shape — a
bare name sitting in a prose field — returned nothing. 27 entries carry a real `beats`
field and all of their values resolve.

The criterion is now recorded in `_vocabulary.field_shapes` so the next author has the
rule rather than the instance.

### 1.2 The UNVERIFIED blocks, folded

**Ten answered items removed; five per-section lists stamped historical** with what they
answered and where the answer is. The live list at the top is the single place to look.
You made this argument about baselines and it applies here: a reader hitting "no 1:1 render
of any §3 plate exists" had no way to know it was answered two drops later, and a
struck-through item is still something they have to read and discount.

---

## PART 2 · The decisions

### 2.3 The 1.46× portrait weighting — resolved, and the concern inverts

The decision was *keep figure-first, but the two deltas must read as a matched pair.*

**The pair is intact, and it was never what the fix touched.** Measured on both aspects:

```
                  figure   delta   ratio    delta boxes    one role?   maxChars
qoq-yoy-16x9       190u    110u    1.727x   750x128 both   yes         11 / 11
qoq-yoy-9x16       190u    130u    1.462x   864x151 both   yes         11 / 11
```

Both deltas are one `delta` role and both labels one `deltaLabel` role, with equal boxes,
equal budgets and equal alignment — landscape side by side on one baseline, portrait
stacked. The plate's own meta says it: *"two roles is how a pair stops being a pair."* The
matched pair is a property of the two deltas **against each other**, and the fix changed
only the figure. The deltas are untouched at 130u.

**And the number that should worry you is not the one you asked about.** 1.46× is portrait.
Landscape is **1.727×** — more figure-dominant — and has never been questioned. Stepping
the portrait figure 220u → 190u moved the deltas *up* in relative weight, from 1.69× to
1.46×, which is the direction the argument wants. **Portrait is now the better of the two
aspects on the plate's own claim, and landscape is the outlier.**

So: no further step proposed on portrait. If 1.46× is the threshold where a figure starts
reading as the claim, landscape at 1.727× fails it and is the one to look at — which is a
question about landscape, not a consequence of the fix. I have not proposed a landscape
step because nothing measured says 1.727× is wrong; it is simply the larger number, and
the plate has shipped at it since drop four.

---

## PART 3 · The findings — measured, proposed, none applied

Every verdict carries the number that produced it. Where I could not get a number, the
finding says so instead of dressing it up.

### F1 · The confession treatments disagree on their measure — and it blocks the pick

**The chair's shape exactly: true of each plate alone, false of the pair.** Both plates
declare `congruent: true` and both are telling the truth — that flag asserts the *three
blocks within one plate* are congruent, not that the two treatments agree with each other.
Nothing measures across the pair.

```
                   said/happened/wrong box      chars per line   per block (x2 lines)
ledger-16x9        x=190  w=1580               68               136
statement-16x9     x=241  w=1529               66               132   -4 chars
ledger-9x16        x=84   w=920                37                74
statement-9x16     x=156  w=848                34                68   -6 chars
```

Same `y`, same `h`, same `maxLines`, same body size — the statement's rail and its three
spurs take 51 landscape units and 72 portrait units off the left, and the budget follows
the measure. Each plate is correct. **The consequence is that a confession written to the
ledger at 37 characters a line does not fit the statement**, and an over-budget fill does
not render, so switching treatment after the copy is written blanks the plate. That lands
directly on the open treatment decision: the pick currently changes what copy is legal.

**Proposed, not applied.** Set both treatments' body measure to the *narrower* of the two —
the statement's, since the rail is real and the ledger has room to give — so the budget is
34 portrait and 66 landscape on both, and a confession written once fits either. It costs
the ledger 4–6 characters a line it currently has. The alternative, widening the statement,
means drawing the rail over the type. This is a geometry change in a drawing function, so
it is a proposal; it is also the cheapest of the four here and the only one that unblocks a
decision you are waiting on.

### F2 · `figures/big-number-l2-16x9` renders blank on a realistic number

**The `qoq-yoy` defect again, in the plate whose entire job is one big number**, and
undetected until this pass. The `huge` role is 350u and the derived budget is **four
characters**:

```
  "87.4%"    5 chars   BLANK
  "1,284"    5 chars   BLANK
  "$15.6bn"  7 chars   BLANK
  "3.2x"     4 chars   renders
```

Four characters holds `3.2x` or `87%` and nothing with a decimal and a unit. This is the
plate a script reaches for when there is one number that matters, so the realistic content
is exactly the content that does not render.

**It is also the plate check P flagged as a leading overhang** — 350u type in a 340-unit
box — and the real defect was next door in the same slot, in the other dimension. P looked
at height and the budget is width.

**Proposed, not applied:** one type step down on the landscape `huge` role buys characters
five and six; the exact step wants deriving against the 900-unit box rather than guessing,
and `big-number-l1` at 7 characters is the reference for what the family already accepts.

### F3 · `tables/cash-flow-9x16`'s totals hold three characters, against landscape's eight

```
                            role     size   box      maxChars
  cash-flow-9x16 total-1    total    44u    103x65   3
  cash-flow-16x9 total-1    total    36u    173x44   8
```

A cash-flow **total** that cannot hold `1,284`, `(482)` or `12,486` — all three blank —
while the landscape twin at a *smaller* type size holds all of them, because its column is
70 units wider. The portrait plate's cells are better off than its totals: `cell-1-1-1` at
32u derives 5 and holds `1,284` and `(482)`, failing only at six digits. **The total is
tighter than the line items it totals**, which cannot be right in a cash-flow table.

**Proposed, not applied:** the portrait `total` role is 44u against the cells' 32u — the
step up is what costs it the characters. Setting `total` to the cells' size, or nearer it,
buys the digits; distinguishing a total by weight or a rule rather than by size is the
move the rest of the kit already makes.

### F4 · `structure/row-spotlight-9x16`'s spotlit cells hold three characters

`figure` at 44u in a 100-unit column, six cells, budget **3**. `12,486`, `$15.6bn` and
`(482)` all blank. The plate exists to pull one row out of a table and show it larger, so
a cell here holds *less* than the same figure in the sheet it was pulled from. Same
diagnosis as F3 and the same proposed direction; I have not costed it because the column
count may be the real constraint rather than the type size, and that is a design question.

### F5 · `structure/sensitivity` publishes two 0×0 regions

```
  sensitivity-16x9   mark-row [320,302,0,0]   mark-col [320,302,0,0]   role control, region true
  sensitivity-9x16   mark-row [96,653,0,0]    mark-col [96,653,0,0]
```

Both carry `note: "not drawn. See meta.mark."`, and the intent is right — the mark is the
renderer's to place. But **"not drawn" and "zero-sized" are different claims**, and the
plate publishes the second. A renderer computing a fill area gets zero, a renderer scaling
into the box divides by zero, and a renderer that trusts the note gets no help finding
where the mark goes. It reports success either way.

**Proposed, not applied:** publish the region at the size the mark should be, with
`drawn: false` saying the plate does not draw it — which is the pattern
`bandsNotDrawn` already uses on `macro-series`, where four band regions are published at
real size and none is filled. The precedent is in the kit; these two slots predate it.

### F6 · The chair's borrowed constant — check L is sound, and here is the test

You asked what happens if the source moves. `emptyChair` hardcodes
`STANDING_EQUIV = h * 0.6755` while the seated pose derives its standing equivalent from
the rig, so the literal is a copy that cannot follow. **Check L catches it, and not by
luck — algebraically.** Both composites reduce to `targetHeight / standingEquivalent`: the
seated pose's ratio has the derived value in its denominator, the chair's has the literal,
so the two scales are equal only while the literal is right. Room-independent, because
`targetHeight` cancels.

Verified by perturbation rather than by the algebra alone:

```
  rig moves    0%   ->  L sees 0.05% drift   passes (rounding in two 4-decimal ratios)
  rig moves   +3%   ->  L sees 2.94% drift   CAUGHT
  rig moves   -5%   ->  L sees 5.05% drift   CAUGHT
```

**A negative finding, stated as one.** What L still would not catch is both moving
together — someone editing the rig *and* the literal to match — which is the case I flagged
in drop nine and which remains true. No change proposed: deriving the constant would be
better, but the chair author has no access to the figure solve, and a check that catches
the realistic failure is worth more than a refactor that removes it.

### F7 · Count variants agree on every shared quantity — also a negative finding

The hunt was: alternates of one family get cut in sequence, so a shared quantity that
differs makes something jump. Measured across every count-variant family at both aspects —
`insider-flow` 6/12, `waterfall` 3/4/5, `seasonality` 4y/6y, `headline-stack` 3/4,
`said-happened` 3/4/5, and `bars-8q` against `line-8q`:

```
  insider-flow-6/12-16x9    axisY 530 both   plot 200,153,1570,753 both   kicker 84   caption 960
  insider-flow-6/12-9x16    axisY 965 both   plot 96,306,904,1318 both    kicker 190  caption 1732
  waterfall-3/4/5s-16x9     baseline y=806 all three                      kicker 88   caption 950
  seasonality-4y/6y-9x16    plot 150,430,840,1070 both                    only the column width differs
  bars-8q / line-8q         plot identical at both aspects
```

**Every one agrees.** Only the per-mark width changes, which is what the count *is*. The
shared-quantity discipline holds library-wide, measured rather than assumed — and the one
family that broke it is the confession pair in F1, which is not a count variant but a
treatment pair, which is why the pattern missed it.

### F8 · The declared-tight boxes, separated from the defects

Not every tight box is F2. `waterfall-5s-9x16`'s `step` derives **5** and
`-1,284`/`+2.4bn` both blank — but five characters at five steps in 9:16 is written down
in the contract and was a deliberate trade. It stays a **directing rule**: a five-step
waterfall in a short takes short figures, and a script that needs `-1,284` wants `-4s`.
Likewise `overlays/lower-third-16x9`'s six-character ticker, which drop eight already
called marginal for the same reason.

The distinction that separates F2–F4 from these: **a declared constraint is one the author
recorded and the routing respects; a defect is one nothing in the kit knows about.** Nobody
wrote down that the big-number plate cannot draw a five-character number.

---

## 3.3 · The instrument audit — what slips past each check

Every check, what it catches, and what gets past it. Two entries are the live examples the
brief asked about.

| check | what it catches | what slips past it |
|---|---|---|
| **A** build, every asset and frame | a plate that throws, a frame-count mismatch, any byte change against the baseline | **a plate that draws successfully and wrongly.** A hash proves determinism, not correctness — and the baseline is self-generated, so a defect present when it was written is enshrined by it. Every finding in Part 3 passed A. |
| **B** frame counts and the settle | a missing boil or settle frame, a frame tag that breaks `_f01.._fNN` | whether the settle *settles* anything a viewer would see. It counts frames and reads tags; it does not compare them. |
| **C** talk frames differ only at the mouth | real work, by the right method — frame against frame within a strip, with a mouth-bbox test. It caught the shipped strip re-wobbling its whole face | **coverage: it is hardcoded to `["close-up","medium"]` and the library has 14 `-talk` strips, all with mouth slots.** Twelve are unchecked, including `sitting-at-desk-talk`. Method right, aim narrow. |
| **D** blink registration | a blink overlay whose marks fall outside the clip box | nothing obvious — and note *why*: D **derives** its set (`author === "hostBlink"` → 7 plates) instead of naming it. That is the pattern C should follow. |
| **E** the frame breathes, the figures do not | a plate frozen and undeclared — it was **failing since drop six** on all four `insider-flow` plates | whether a declaration is *honest*. E now passes because 32 plates are on a list with reasons, and the list is human-written. A plate wrongly declared still is invisible to it. Drop nine's insider-flow entry is the one to re-read if you doubt any. |
| **F** the new plates, every count variant | a missing count variant or aspect, a band or axis that did not get published | the *values* inside them. F confirms `waterfall-5s-9x16` publishes five steps; F8's five-character budget is not its business. |
| **G** no `<text>` nodes | the structural guarantee, across all 924 frames | nothing. This one is airtight because it is a property of the emitted string, and it is the cheapest check in the file. |
| **H** the baseline and which families it resets | which families changed bytes since the last pack | it *is* the baseline, so it cannot disagree with itself. H reports the reset; it cannot tell you the reset was correct. |
| **H2** distinct keys, distinct artwork | two keys whose every frame is byte-identical — a copy-paste that never got edited | two keys that differ by one mark and should differ by more. It is an identity test, not a similarity test. |
| **I** §1's ground | the four properties the title ground has to hold | whether `card` was the right treatment. That was a judgement, and §3.5 is the place it gets re-examined. |
| **J** §2's quarter | period budgets, the value row, pair congruence, group geometry — and it found `language-shift`'s 1.997-line box by accident | **the same thing P missed on `big-number`: budgets against realistic content.** J asserts the budget exists and is consistent; nothing asserts it is large enough for what a script writes. |
| **K** what the filing reader found | §3's geometry and its published fields | as J. |
| **L** the rooms and the poses | the seated ratio, the floor pins, and now the chair composite — **inverted in drop nine, because it had been asserting the chair carries no ratio, which is the reasoning that caused the defect** | both sides of a borrowed constant moving together (F6). Also: it composites onto one room, which is sound here only because `targetHeight` cancels. |
| **M** marks asked for and never drawn | a hatch or fill that returns an empty string — the §4.2 wall tone that drew nothing | a mark that draws *something* wrong. M counts blanks, not correctness. |
| **N** the furniture, the confession, the end card | the published fields on §1, §2 and §3.4 | **F1.** N checks the confession treatments with a hardcoded `["statement","ledger"]` loop and asserts each one's internal congruence; it never compares the two to each other. |
| **O** declared identifiers | a slot that should declare itself an identifier and does not — the mistake that happened three times | nothing much. Worth recording that **O's first version was thrown away for raising false alarms**, which is why P was built to note rather than fail. |
| **P** boxes against the lines they declare | a box too short for its own `maxLines` at the kit's pitch — 2,280 slots, 357 multi-line, none short | **width.** P is one dimension. It flagged `big-number-l2` as a leading overhang and missed that the same slot cannot hold a five-character number (F2). |

**Was anything else made to pass rather than made correct?** One, and it is C: it passes
because it never looks at twelve of the fourteen strips it is named for. That is not a
dishonest declaration like E's was — it is worse in one way, because nothing announces the
gap. **Proposed, not applied:** derive C's set the way D derives its own — every key ending
`-talk` — which turns 4 comparisons into 28 and needs no new technique.

**And the class of defect no check covers at all:** *a derived budget that is smaller than
the realistic content of the slot.* `budget.js` derives `maxChars` correctly from font
metrics, every check confirms it is derived and consistent, and **nothing anywhere asks
whether the number is big enough.** That is F2, F3 and F4, it is what drop eight's "worst
realistic copy" instruction found by hand in `qoq-yoy`, and it is the gap I would close
next: a check that pairs each tight slot with one realistic string, authored per role, and
fails when the string does not fit. It needs a human to write the strings, which is exactly
why it does not exist yet.

---

## 3.5 · What would have to be true for this to be wrong

### The chair's 0.608 ratio
**Assumption:** that a chair should scale to the same standing-equivalent reference a
seated body does — that "how big is this object in this room" has one answer per room.
**How I would know it was wrong:** if a real cut from him to his chair reads as the camera
having moved. The fix makes the chair one *size*; it does not make the cut work. That is
the item on the live list, and it is a cut, not a pass.

### `qoq-yoy-9x16`'s 190u figure
**Assumption:** that eight characters is the realistic ceiling for a quarter figure.
**How I would know it was wrong:** a script writing `$15.643bn` or `(1,284)m` — nine
characters — blanks the plate again, and the fix bought exactly one character. The honest
version of this fix is the check I proposed above, not the step I took.

### The confession's 12-unit descender allowance
**Assumption:** that two lines at the published pitch is the worst case. **How I would know
it was wrong:** the compositor breaking a line where the author did not. P measures at
authored newlines; line breaking is the renderer's, by measured width. A body that wraps to
three lines overruns a box that now clears by 12.4 units — and F1 says the two treatments
disagree about where the wrap happens, which makes this the assumption I trust least.

### The title `card` decision
**Assumption:** that a title needs its own ground because the wall behind it is
unpredictable. **This one is the best-supported of the four** — §12 measured the contrast
floor inside the box on dusk walls against a `titleGround: null` control and the floor is
wall-independent with the card and borrowed without it. **How I would know it was wrong:**
if the card reads as pasted-on in a cut rather than as paper on a wall — again a cut, and
§3.5's channel art is where the same treatment gets its second test at a different scale.

---

## PART 4 · The three at a real limit

Nothing new on any of the three, and I did not go looking. `seasonality-6y-9x16`, the dusk
relight and the chair-in-a-cut are all correctly scoped as directing rules or as
watch-the-video questions. The one adjacent thing worth saying: **F8 is the same species as
the seasonality rule** — a declared constraint that becomes a directing rule rather than a
plate change — and separating that species from a real defect is what made F2 findable.


## Drop nine — the three fixes, applied

**270 assets, 924 frames, 0 errors, 0 text nodes. All sixteen pre-flight checks pass in
29.8s. No new assets, and no new plates.** The
three fixes drop eight proposed and did not apply are approved and in, and §3.5's two
buildable routes are built as candidates rather than as a decision. All sixteen pre-flight checks pass,
and **`audit/baseline-14.json` is regenerated** — three plate families changed geometry,
so byte-identity against the drop-eight baseline does not hold for them and is not
asserted.

Each one was a measurement before it was a change, which is the only reason they were
safe to make in one pass.

### 1 · `host/empty-chair` publishes a ratio of its own

The worst of the three: the same chair rendered **64% larger with nobody in it**, taller
than the man who sits in it, its back 220 units higher up the frame — on the one cut the
plate exists for.

```
                    ratio     scale    the chair renders
seated pose         0.7394    0.4333   342
empty chair, was    none      0.7123   562     <- 64% larger, and the man is 416
empty chair, now    0.6080    0.4331   342     <- 0.05% apart, which is rounding
```

The chair now publishes `meta.chair.heights.ratio` — **789 / 1,297 = 0.608** — against the
same standing equivalent the seated pose uses, and its contract reads *scale so
(floorLineY − figure.y) equals anchor.targetHeight × ratio* rather than *to the target
height directly*. Derived in the author, not authored: the seated pose publishes its
standing equivalent as 0.6755 of canvas height and the ratio is this plate's own span over
that.

**Pre-flight check L was asserting the wrong thing and is inverted.** It used to assert
the chair carries *no* ratio, on the reasoning that there is no seated body to scale —
which is exactly the reasoning that produced the defect, because the anchor's target
height is a *standing* figure's. It now composites both plates onto `room/desk-front-16x9`
and fails if the same chair comes out more than 0.5% apart. **The assertion is the
composite, not the field**, because the field was self-consistent the whole time.

### 2 · `figures/qoq-yoy-9x16`'s figure steps 220u → 190u

At 220u the box derived **seven** characters and `$15.64bn` is eight, so an over-budget
fill did not render and the plate was blank where the quarter goes. Two decimals in
billions is what a real script writes. At 190u the box derives **8** and the string
renders.

**The cost, stated rather than buried:** the figure was 1.69× the delta beside it and is
now **1.46×**. Still the dominant quantity on the plate, and nearer landscape's 1.73× than
it was, but a real reduction in the weighting the plate's argument rests on. 190u is the
only step that buys the eighth character against a 936-unit box, so the alternative was
not a smaller step — it was leaving the plate unable to draw a real number. The delta role
is untouched, and the pair is still congruent.

### 3 · The confession's descender allowance goes 4 → 12

Two lines of body at the compositor's 1.16em pitch occupy 134.6 units in what was a
139-unit box, so the ledger's second line sat **4.4 units** off the rule below it — 9px
delivered. Measured at 1:1 in §9, not computed. The allowance is now 12, the clearance
12.4, and it cost 24 units out of the band across the three blocks. Both plates still
clear their captions and fill 0.61–0.82 of the band.

**Applied to the statement treatment too, deliberately.** It has no rule to clear, so it
did not need it — but the two treatments share one body geometry, and that congruence is
§2's tone decision expressed as geometry. Fixing one and not the other would have bought
9px of clearance at the price of the thing the plates are for.

### §3.5 — the channel art, built so you can pick

`proof/channel-art.html`. §3.5 was left as a question rather than an asset and the
question was *which route*. Two of the three routes are mine to build, so both are built,
full size, against the real geometry, with the same copy. **Route 2 — brief an
illustrator, with the kit as reference — is still the best result and is not on the page**,
because I cannot deliver it. Route 3, hand-drawn SVG at 2560×1440, I recommend against and
did not build: it produces a diagram.

**Nothing here is a plate.** No new keys, no new families, no entry in
`roles.fragment.json`, and `gates.reachable_plates` does not gain a row. It is
composition of assets that already exist, which is what route 1 asked for.

**The geometry, which was ready before any decision.** The banner is 2560×1440 and almost
nobody sees it whole. Every surface crops toward the middle — TV 2560×1440, desktop
2560×423, tablet 1855×423 — and the **1546×423 safe area** is the only region guaranteed
on all of them. So the banner has one job: everything that must be read goes inside
1546×423, and the rest is a frame that survives being cut away. The page draws the safe
area and both intermediate crops over each candidate.

**Route 1A — the room, cropped to a banner.** `room/wide-16x9` scaled 1.333 to the banner
(same 16:9, no cropping) with `host/hands-in-pockets` composited at the anchor by the
plate's own published contract, so it is a real composite rather than a mock-up. It is
unarguably the current kit. It also fails on its own terms, and the page shows why: inside
the safe area there is part of a wall, part of a desk, the top of a monitor and a figure
cut off at the chest. The composition lives at 2560×1440 and the frame that matters is
1546×423, so everything that makes it read as a room is in the part that gets cropped.
A video still used as channel art reads as a video still, which is the risk §3.5 named.

**Route 1B — the card on kit ground. My pick.** §1's decided treatment — an opaque card
carrying its own ground — applied to the first thing a viewer ever sees. Measured on the
page: the card is 1180×372 and sits inside the safe area on all four edges, margins
183/183/26/26. It survives every crop by construction rather than by luck, and the 1,014
units above and below it can be cut to nothing without losing anything.

**And a finding came out of building it.** I built 1B on a room's wall first, positioned by
the plate's own `meta.titleGround.box` — the patch §1 chose to put a title card on, which
is the same question asked at video scale. It does not work, and the reason is measurable:
**the widest uninterrupted wall in the room family is 597×366**, so filling a 1546×423 safe
area with it needs **2.59×** enlargement, which puts a monitor and a desk edge in frame at
two and a half times their drawn weight. There is no 1546×423-shaped clean wall anywhere in
the library at 1:1. So 1B's ground is the dusk wall's tone taken **flat** — the kit's
materials without its hand, which is not a new idea here: it is exactly the decision §1.2
made for the captions, for the same reason. A banner is the one surface in this product
where the kit's line work cannot be shown at its own scale.

**Two defects in the channel-art page itself, found on review.** Both are the
asserted-vs-measured failure, in the page rather than in the plates, which makes four
times this pack has caught it:

1. **The ground tone was hardcoded while the comment said it was read off the plate.** The
   code tried `gm.wallTone` and `gm.timeOfDay.wall` — *neither field exists* — and fell
   through to a literal hex. There is no field to read because dusk is not a flat colour:
   `timeOfDay.emittedAs` says it draws two warm washes at real fill-opacity over the base
   wall, so the rendered tone is a composite. It is now **sampled**: the plate is
   rasterised and the mean pixel inside its own `meta.titleGround.box` is taken, the same
   technique §12 uses, with the same browser-rasteriser caveat. The page prints the tone,
   where it came from, and — when they differ — what the hardcoded value had been.
2. **Route 1A's strapline was stacked by eye** while 1B's was stacked off the line box.
   Nothing was touching (the wordmark is all caps, so it was leading overhang — check P's
   note-not-failure class), but two candidates that exist to be compared should not be
   spaced by two different methods. 1A now uses the same 290-unit arithmetic.

Also corrected in the same pass: the card ground reads `pal("night-card").ground` rather
than repeating the hex, and the note no longer claims "the wall is a shipped room plate" —
the wall *was* a room plate for one draft and is now a sampled flat tone, and the card is
a rect with a hairline standing in for `P.card()`'s drawn edge rather than being it.

**The profile.** Square, uploaded at 800×800, drawn as a circle, shown at about 48px
wherever it matters — where a figure is a smudge and a room is noise. Both candidates are
one letterform, which is a finding rather than a shortcut: at 48px the counter of a D is
about nine pixels across. A takes the card ground so the profile and banner are the same
object twice; B takes the wall tone with a hairline, which holds its edge against both
YouTube themes where A on a light page has no edge at all. Shown at 400, 96 and 48 —
judge it at 48.

### What the baseline reset covers

Three families change geometry and therefore bytes: `figures` (qoq-yoy, both aspects),
`structure` (all four confession plates), `host` (empty-chair's figure slot and new
`meta.chair`). Everything else is byte-identical to drop eight. The new
`audit/baseline-14.json` is the file the next pack is checked against.

### Check P now rides on check A, and the page is twice as fast

Worth a note because it is the third time this page has learned the same lesson. P's first
cut called `manifest()` on all 270 plates *after* check A had retained 924 `Plate` objects,
and the page stopped finishing — not a logic error (the identical walk runs clean in 4.2s
on its own) but memory thrash. A now records the three numbers P needs per type slot as
flat values during its own build and drops everything else, exactly the way check M's
hatch counter rides on it.

**Sixteen checks in 29.8s**, down from 64.7s, all passing. The same correction check M got
when its own second library pass took the page from slow to unopenable, and the same one
the review page got when it hung on twelve room plates: *the check was right and the way it
was run was not affordable.*

`proof/channel-art.html` needed the same treatment for the same reason — three room plates
scaled past the banner frame as live SVG made it take tens of seconds to settle, so each
ground is now rasterised once as a data-URI image instead of held as a DOM tree.

### UNVERIFIED — drop nine

1. **The three fixes are asserted by the build and by `render-scale.html`, not watched.**
   Each is geometry, each is now measured at 1:1 on the page that asked for it, and none
   has been seen in motion or in a real cut. The chair fix in particular is a *cut*
   property — him, then his chair — and a cut is the one thing a proof page cannot show.
2. **The empty chair's ratio rests on the seated pose's standing equivalent being 0.6755
   of canvas height.** That constant is read off the seated author's published number
   rather than re-derived from the rig, because the chair author has no access to the
   figure solve. Check L catches drift between the two plates, which is the failure that
   matters; it would not catch both moving together.
3. **1.46× has not been looked at as a judgement.** The arithmetic is certain and the
   plate still reads figure-first at 1:1. Whether the portrait pair is now weighted the
   way the plate's argument wants is a design call, and the reviewer who cares about it is
   the one who wrote the argument down.
4. **Everything in drop eight's UNVERIFIED list still stands**, except where a fix closed
   it. The captions `force_style`, the end card's zone fractions, the renderer-side
   reachability of `roles.fragment.json`, the mouth contract on the seated pose, and
   motion are all unchanged.
5. **Neither channel-art candidate has been seen on a real YouTube page.** Not in either
   theme, not at a real device pixel ratio, not next to other channels' marks, and not at
   the actual crops a phone applies — the page draws YouTube's published crop geometry,
   which is not the same as looking at it. The profile is the one that turns on this: A
   has no edge at all against a light page, and that is the check I cannot run.
6. **The sampled ground tone is the browser's rasteriser**, like every other measured
   number in this pack, and the page needs serving over http or it reports a tainted
   canvas and falls back to the authored value — labelled as such rather than silently.
7. **The wordmark and strapline are placeholders.** "DENNIS" and "the numbers, and where
   they came from" are set to show the type doing its job at banner scale; the strapline
   is sized to the card by measurement (Courier Prime is monospaced, so the line is
   exactly chars x size x (0.5996 + tracking), and at the first size I tried it ran 1,702
   units in a 1,180-unit card). Real words will need the size re-derived, not reused.


## Drop eight — the 1:1 pass, and the vocabulary

**270 assets, 924 frames, 0 errors. No plate changed.** Both open items were
measurements, and both are now measured. Three files moved: `proof/render-scale.html` gained
**seven** sections, `roles.fragment.json` had 44 of its 60 entries remapped, and
`proof/preflight.html` gained **check P** — plus a declaration that makes **check E**,
which had been failing since drop six, pass honestly. `plates.js`,
`build.js`, `hand.js` and `budget.js` are untouched, so every baseline still holds.

### The 1:1 pass — 50 assets that had never been seen at delivered scale

`render-scale.html` had not moved in two drops: its seven sections were byte-identical to
the previous pack and all seven cover drops one and two. Everything built since was
asserted by the build and confirmed by nobody, which is what five separate UNVERIFIED
blocks said. Sections **8–12** are that pass, in the existing switcher style; **13** and
**14** then clear drop five's ten, which were unseen for the same reason.

Three rules the new sections hold to, and the third is the one that makes the verdicts
mean anything:

1. **One canvas unit is one CSS pixel.** Type fills are absolute px off the published slot
   box at the published role size — no container queries, nothing derived. `furniture.html`
   rendered every lower third 2.33× oversized by sizing type against the wrong container;
   at 1:1 there is no container to get wrong. **In 9:16, 1:1 *is* phone scale** — a
   1080-unit canvas delivered at 2× on an 1170px phone is 1.08 display px per canvas unit,
   so a portrait tile on that page is within 8% of what a viewer holds.
2. **The face comes off the role, not off a lookup table in the page.** `budget.js` derives
   every `maxChars` from the role's own `font`, `transform` and `tracking`, so type set in
   any other face measures a different plate than the budget describes. This caught itself
   on the way in: the first pass set `insider-flow`'s date row in Courier Prime and it
   overflowed. The role is Archivo Narrow 600, which is what the eight-character box was
   measured with, and in the right face twelve dates clear each other. **The verdict went
   from marginal to passes because the page was wrong, not the plate.**
3. **Worst realistic copy, not the neatest** — longest plausible ticker, longest plausible
   label, the count variant with the least room. The kit already learned the inverse the
   hard way: a budget reporter that raised five false alarms out of seven was correctly
   called out, on the grounds that a report flagging correct copy trains people to ignore
   it. A proof page filled with short tidy strings does the same thing from the other side.
   Every fill is checked against the budget derived for the box it lands in and each
   section reports what went over, because an over-budget fill does not render at all — a
   verdict of "legible" on a string the compositor would refuse is not a verdict.

### The verdicts

**Three findings across the seven sections.** One plate that does not render
(`qoq-yoy-9x16`), one limit confirmed rather than overturned (the 23-unit column), and one
scaling contract that is wrong in a way only a composite could show
(`host/empty-chair`, §14). Everything else passes or is marginal for a stated reason.

| asset | verdict | what the 1:1 pass shows |
|---|---|---|
| `overlays/lower-third-{16x9,9x16}` | **passes** | 78u ticker, 34u tagline, over a room, a chart and a 41-box table. The panel reads as an object on all three grounds and the type never touches drawn ink. |
| the ticker box | **marginal** | `$GOOGL` is exactly six characters, the derived budget. It fits and has nothing spare; a seventh character is an absent shot, not a tight one, and `$BRK.B` only fits portrait's eight. Right for a ticker, wrong for anything else — which is what it was narrowed for. |
| captions — option B at 37u | **passes** | legible over the room and over the panel's own rim at 1:1; the numbers line settles it, and Courier Prime's 3/8 and 5/6 stay apart at this size. `MarginV` and the box inset are still unrun — libass, not this page. |
| `structure/confession-statement-16x9` | **passes** | 58u body, two full lines at 68 characters, rail and three spurs. Nothing on the plate marks the third block as the bad one, which is its whole argument, and at 1:1 that is visibly geometry rather than intent. |
| `structure/confession-ledger-16x9` | **marginal** | same body geometry on a ruled sheet. Two lines render **134.5 in a 139-unit box** — measured off the page, not computed — so the second line's descenders sit 4.5 units off the rule below, 9px delivered. On a ledger that is a line written on a ruled line and it is right; it is the tightest fit on either treatment, and worth knowing before that block height is ever touched. Portrait is the same shape: 143.8 in 148. *Proposed, not applied:* eight more units of block height buys the clearance, at 24 units out of the band. |
| `structure/confession-{ledger,statement}-9x16` | **marginal** | 37 and 34 characters a line at two lines: four or five words a line, so a real confession has to be written to the plate before it is recorded, not trimmed after. Legible, and tight in the way that matters — the sentence has to be short, not the type. The body size did not shrink, which was the risk the ledger treatment was warned about. |
| `charts/bars-8q-{16x9,9x16}` | **passes** | eight 111u / 59u columns, `Q3'25` heads at five characters clearing each other, and the landscape value row holds `$15.1bn` at nine. Portrait's single `value-last` callout is the right call — eight figures at 30u across 840 units is the row that stops the shot. |
| `charts/line-8q-{16x9,9x16}` | **passes** | the path reads as a shape at both aspects; the loosest boxes in the quarter set. |
| `figures/qoq-yoy-16x9` | **passes** | 220u figure, 130u deltas, congruent side by side. Neither delta reads as the headline. |
| `figures/qoq-yoy-9x16` | **fails at 1:1** | **the figure box holds seven characters and `$15.64bn` is eight.** An over-budget fill does not render, so the plate is blank where the quarter goes — and two decimals in billions is what a real script writes. *Proposed fix, not applied:* the portrait `figure` role is 220u in a 936u box; one type step down (~190u) buys the eighth character and the figure is still four times the delta. That is a drawing change, so it is a proposal. |
| `charts/seasonality-4y-{16x9,9x16}` | **passes** | 67u and 35u columns, four values a group, the ramp separates every year. |
| `charts/seasonality-6y-16x9` | **passes** | 45u columns, six values a group, newest at full subject ink. |
| `charts/seasonality-6y-9x16` | **marginal** | **the 23-unit column question, answered.** The columns render and the group structure reads — four quarters, six bars each, unmistakably. What does not survive is the ramp's bottom end: FY21 at 0.26 against FY22 at 0.37 on a 23px mark cannot be put in order at phone distance, so the plate reads as four groups rising rather than as six dated years. `meta.crowded` confirmed, not overturned: legible at desk distance, not countable on a phone. No fix proposed — a wider column means fewer years, which is what `-4y` already is. |
| `figures/short-interest-{16x9,9x16}` | **passes** | 78u figures, short fill inside the float outline, proportion read without dividing anything. Portrait's 26-character labels hold `free float 1,284.6m` with two spare — the tightest real string on the plate. |
| `charts/insider-flow-6-9x16` | **passes** | six 38u marks either side of the axis, dates at eleven characters, and the per-mark who row still fits — `Dir (chair)` is the 16-character budget's worst realistic case. |
| `charts/insider-flow-12-{16x9,9x16}` | **passes** | twelve marks, one ink, one weight; the pattern is the argument and it reads before any label. The portrait date row was the suspected constraint and it holds — see the face rule above. A date here is day and month; the year is on the unit line or nowhere. |
| `charts/macro-series-{16x9,9x16}` | **passes** | ten decades, forty minor ticks, bands behind the series at 0.13 without out-contrasting it. The 20u source line is the smallest type in the library and 74 characters of it runs the full 894-unit measure; it reads at 1:1. It stays required, and it is the first thing a crop would remove. |
| `structure/end-card-{16x9,9x16}` | **passes** | with the keep-out zones drawn at 1:1, the derived content band is clear of all three on both aspects and the 76u closing line has the frame to itself. The zone fractions are still designed-against — unchanged by this pass, and not something a render can answer. |
| the 24 dusk assets, as a set | **passes** | the tone lands on all 24 and reads as a warm wall with a weighted ceiling joint, not a flat beige fill. The frayed join does the work: at 1:1 the boundary is visibly a fray rather than a painted stripe, which was the one thing the drawing had to get right. |
| the chapter opener on a dusk wall | **passes** | the `card` sits on the toned wall as paper on a wall; the title is 76u structure ink on the card's own ground and the tone behind it is covered rather than borrowed from. Measured below. |
| `room/over-the-shoulder-dusk-{16x9,9x16}` | **passes** | the two dusk plates with no title slot, correctly — they take the tone and take no ground. The near silhouette reads as a shoulder and a head-back at 1:1 rather than as a blob, which was §4.3's open question. The tone does not change it either way, and the night twins differ only in wall tone. |
| night against dusk | **marginal** | as a *difference* it reads: side by side at 1:1 the wall is warmer and the ceiling heavier. Alone in a cut it reads as "the same room, later" only because the lamp is still the brightest thing in frame — which is the argument for dusk and against `day`, and it depends on a viewer never seeing the two within a few seconds of each other. |
| the relight | **fails at 1:1** | the known deliberate limit, now visible rather than predicted: every cast shadow still falls where the lamp and the monitor put it, and on `wide-dusk-16x9` the desk's cast reads as lamp-lit while the wall reads as late light from outside. *Proposed fix:* none — a relight is a much larger job than a wall tone and is the reason `day` is absent. What this pass adds is that it shows on the **widest** angles, so a director cutting dusk should prefer the tighter ones. |

### Measured — the card's contrast floor on a dusk wall

§4.2 listed this as measurable and unmeasured. Section 12 rasterises at 1:1 and measures
inside the published title box, against the same `titleGround: null` control the §1
decision was made from. The rasteriser is the browser's, not resvg — stated, as
`title-ground.html` states it, and the page needs serving over http for the measured
columns or it reports a tainted canvas rather than a number.

### VOCABULARY — `roles.fragment.json` mapped onto the real sixteen

The fragment named things that do not exist: **44 of 60 keys** touched at least one
invented name — 32 invented chapter types and all 9 shot-template names. The cause is in
the record already: the values were *not read off `templates/`*. The fourteen newest
entries were clean because they were written against the real list, and they are the model
the rest now follow.

**What the nine invented shot templates were really carrying.** `full-plate`,
`push-in-on-plate`, `plate-with-host-medium`, `plate-with-host-close-up`,
`short-full-plate`, `short-plate-over-host`, `host-over-room`, `two-shot` and
`plate-with-host` all encoded one real question — whether the plate survives sharing the
frame with the host. That is a property of the **plate**, not a template name, so it is
now stated in the plate's own note as prose and the field holds the real structural shot
id (`open` / `evidence` / `land`, plus `on-the-desk` in `filing-walk`).

**Three rules held while mapping.** No wildcard strings: `"*"` and `"any LONG chapter"`
do not resolve against sixteen names, so the two entries that genuinely belong everywhere
now say `"any": true` (and `"any_shot": true`). No new chapter type invented to make an
entry fit. Nothing deleted to make the count clean — the count is still 60.

| plate key | what it said | what it now says | why |
|---|---|---|---|
| `charts/bars-8q-16x9` | ct: `the-numbers` `what-they-earn` `the-latest-quarter` `momentum`<br>st: `full-plate` `plate-with-host-medium` `push-in-on-plate` | ct: `the-numbers`<br>si: `evidence` `land`<br>fmt: `earnings` `long`<br>beats: `the-print` `the-sheet` | `the-latest-quarter`, `momentum` and `what-they-earn` are three names for `the-numbers`. Its earnings-format home was missing entirely; it is a print plate. |
| `charts/bars-8q-9x16` | ct: `short-the-number` `short-the-quarter`<br>st: `short-full-plate` `short-plate-over-host` | ct: `the-numbers`<br>si: `evidence`<br>fmt: `short`<br>beats: `numbers` `the-sheet` | `short-the-number`/`short-the-quarter` were SHORT beats, not chapter types — `numbers` and `the-sheet`. Keeps `the-numbers` for a long-form 9:16 cut. |
| `charts/line-8q-16x9` | ct: `the-numbers` `momentum` `the-latest-quarter`<br>st: `full-plate` `plate-with-host-medium` `push-in-on-plate` | ct: `the-numbers` `how-we-got-here`<br>si: `evidence`<br>fmt: `earnings` `long`<br>beats: `the-print` | as bars-8q; `how-we-got-here` added because a path across eight quarters is the shape argument that chapter is for. |
| `charts/line-8q-9x16` | ct: `short-the-number` `short-the-quarter`<br>st: `short-full-plate` | ct: `the-numbers`<br>si: `evidence`<br>fmt: `short`<br>beats: `numbers` | beats, as above. |
| `figures/qoq-yoy-16x9` | ct: `the-latest-quarter` `the-numbers` `momentum` `the-claim`<br>st: `full-plate` `plate-with-host-medium` `push-in-on-plate` | ct: `the-numbers` `guidance-estimates`<br>si: `evidence` `land`<br>fmt: `earnings`<br>beats: `vs-expected` `the-turn` | `the-claim` is a management claim about growth — `guidance-estimates`. Its real home is earnings' `vs-expected`, which the invented wiring had no way to name. |
| `figures/qoq-yoy-9x16` | ct: `short-the-number` `short-the-claim` `short-the-quarter`<br>st: `short-full-plate` `short-plate-over-host` | ct: `the-numbers`<br>si: `evidence`<br>fmt: `short`<br>beats: `numbers` `the-turn` | `short-the-number`/`short-the-claim`/`short-the-quarter` → `numbers` + `the-turn`. |
| `charts/seasonality-4y-16x9` | ct: `the-numbers` `the-business` `momentum` `what-they-sell`<br>st: `full-plate` `plate-with-host-medium` `push-in-on-plate` | ct: `the-numbers` `how-the-money-is-made`<br>si: `evidence`<br>fmt: `earnings`<br>beats: `the-print` | `the-business`/`what-they-sell` are `how-the-money-is-made`; `momentum` is `the-numbers`. |
| `charts/seasonality-4y-9x16` | ct: `short-the-claim` `short-the-quarter`<br>st: `short-full-plate` | ct: `the-numbers`<br>si: `evidence`<br>fmt: `short`<br>beats: `numbers` `the-turn` | beats. This is the variant the routing prefers for a short and the 1:1 pass agrees. |
| `charts/seasonality-6y-16x9` | ct: `the-numbers` `the-business` `momentum`<br>st: `full-plate` `push-in-on-plate` | ct: `the-numbers` `how-the-money-is-made`<br>si: `evidence` | as -4y. |
| `charts/seasonality-6y-9x16` | ct: `short-the-claim`<br>st: `short-full-plate` | ct: `the-numbers`<br>si: `evidence`<br>fmt: `short`<br>beats: `numbers` | `short-the-claim` → `numbers`. Marked marginal at phone scale by this drop's 1:1 pass. |
| `structure/language-shift-16x9` | ct: `what-they-said` `management` `risk` `the-claim`<br>st: `full-plate` `plate-with-host-medium` `push-in-on-plate` | ct: `guidance-estimates` `management` `filing-walk` `risk`<br>si: `evidence` `on-the-desk` | `what-they-said` splits by plate: this one is the filing reader's diff, so `guidance-estimates` + `management`, plus `filing-walk` where it is read off the document. `the-claim` folded into `guidance-estimates`. |
| `structure/language-shift-9x16` | ct: `short-the-claim`<br>st: `short-full-plate` `short-plate-over-host` | ct: `management`<br>si: `evidence`<br>fmt: `short`<br>beats: `the-comment` `the-turn` | `short-the-claim` → `the-comment` + `the-turn`. |
| `paper/headline-stack-3-16x9` | ct: `the-story` `what-happened` `risk` `the-setup`<br>st: `full-plate` `plate-with-host-medium` `push-in-on-plate` | ct: `how-we-got-here` `cold-open` `risk`<br>si: `open` `evidence` | `the-story`/`what-happened` are `how-we-got-here`; `the-setup` is `cold-open`, which is where a dated stack of headlines actually opens a video. |
| `paper/headline-stack-3-9x16` | ct: `short-the-story` `short-the-claim`<br>st: `short-full-plate` | ct: `how-we-got-here`<br>si: `evidence`<br>fmt: `short`<br>beats: `hook` `the-news` | `short-the-story` → `hook` + `the-news`. |
| `paper/headline-stack-4-16x9` | ct: `the-story` `what-happened` `risk`<br>st: `full-plate` `push-in-on-plate` | ct: `how-we-got-here` `risk`<br>si: `evidence` | as -3. |
| `paper/headline-stack-4-9x16` | ct: `short-the-story`<br>st: `short-full-plate` | ct: `how-we-got-here`<br>si: `evidence`<br>fmt: `short`<br>beats: `the-news` | beats. |
| `room/over-the-shoulder-16x9` | ct: `the-numbers` `the-filing` `what-they-said` `the-evidence`<br>st: `full-plate` `push-in-on-plate` | ct: `filing-walk` `the-numbers` `guidance-estimates`<br>si: `evidence` `on-the-desk` | `the-filing` is `filing-walk`; `the-evidence` was an invented name for what is really the `evidence` SHOT position, and this plate's home beat is `on-the-desk`, which only `filing-walk` publishes. |
| `room/over-the-shoulder-9x16` | ct: `short-the-evidence` `short-the-number`<br>st: `short-full-plate` | ct: `filing-walk`<br>si: `evidence`<br>fmt: `short`<br>beats: `the-sheet` `the-news` | `short-the-evidence`/`short-the-number` → `the-sheet` + `the-news`. |
| `host/sitting-at-desk` | ct: `any LONG chapter` `the-numbers` `what-they-said` `the-verdict`<br>st: `plate-with-host-medium` `host-over-room` `two-shot` | `"any": true`<br>si: `open` `evidence` `land`<br>fmt: `long` `earnings` `macro` | `"any LONG chapter"` is not a name. Replaced with `"any": true` + `formats` — a pose belongs to the format, not to a chapter. `the-verdict` folded into the same statement. |
| `host/empty-chair` | ct: `the-verdict` `the-close` `any LONG chapter ending`<br>st: `host-over-room` `full-plate` | ct: `resigned-close`<br>si: `land` | `the-verdict`/`the-close` are `resigned-close`; `"any LONG chapter ending"` is not a name, and the plate's real position is `land`. |
| `figures/waterfall-3s-16x9` | ct: `the-numbers` `what-they-earn` `cost-structure`<br>st: `full-plate` `plate-with-host-medium` `push-in-on-plate` | ct: `how-the-money-is-made` `the-numbers`<br>si: `evidence` | `what-they-earn` and `cost-structure` are both `how-the-money-is-made` — which is the chapter a waterfall exists for. |
| `figures/waterfall-4s-16x9` | ct: `the-numbers` `what-they-earn` `cost-structure`<br>st: `full-plate` `plate-with-host-medium` `push-in-on-plate` | ct: `how-the-money-is-made` `the-numbers`<br>si: `evidence` | as -3s. |
| `figures/waterfall-5s-16x9` | ct: `the-numbers` `what-they-earn` `cost-structure`<br>st: `full-plate` `push-in-on-plate` | ct: `how-the-money-is-made` `the-numbers`<br>si: `evidence` | as -3s. |
| `figures/waterfall-3s-9x16` | ct: `short-the-number` `short-the-claim`<br>st: `short-full-plate` `short-plate-over-host` | ct: `how-the-money-is-made`<br>si: `evidence`<br>fmt: `short`<br>beats: `numbers` `the-sheet` | beats. |
| `figures/waterfall-4s-9x16` | ct: `short-the-number`<br>st: `short-full-plate` | ct: `how-the-money-is-made`<br>si: `evidence`<br>fmt: `short`<br>beats: `numbers` | beats. |
| `figures/waterfall-5s-9x16` | ct: `short-the-number`<br>st: `short-full-plate` | ct: `how-the-money-is-made`<br>si: `evidence`<br>fmt: `short`<br>beats: `numbers` | beats. |
| `structure/implied-16x9` | ct: `the-price` `valuation` `what-has-to-be-true` `the-verdict`<br>st: `full-plate` `plate-with-host-medium` `push-in-on-plate` | ct: `valuation` `resigned-close`<br>si: `evidence` `land` | `the-price` and `what-has-to-be-true` are both `valuation`; `the-verdict` is `resigned-close`. |
| `structure/implied-9x16` | ct: `short-the-claim` `short-the-price`<br>st: `short-full-plate` `short-plate-over-host` | ct: `valuation`<br>si: `evidence`<br>fmt: `short`<br>beats: `cheap-or-trap` `payoff` | `short-the-claim`/`short-the-price` → `cheap-or-trap` + `payoff`. |
| `charts/dilution-6y-16x9` | ct: `the-numbers` `what-they-earn` `management` `the-price`<br>st: `full-plate` `plate-with-host-medium` `push-in-on-plate` | ct: `capital-allocation` `management` `the-numbers`<br>si: `evidence` | `the-price` here is really about issuance, so `capital-allocation` — which the invented list had no entry for at all despite it being one of the sixteen. |
| `charts/dilution-6y-9x16` | ct: `short-the-number` `short-the-claim`<br>st: `short-full-plate` `short-plate-over-host` | ct: `capital-allocation`<br>si: `evidence`<br>fmt: `short`<br>beats: `numbers` | beats. |
| `charts/maturities-16x9` | ct: `the-balance-sheet` `risk` `survivability`<br>st: `full-plate` `plate-with-host-medium` | ct: `risk` `capital-allocation`<br>si: `evidence` | `the-balance-sheet` and `survivability` are both `risk`; `capital-allocation` added because a maturity wall is what allocation ran into. |
| `charts/maturities-9x16` | ct: `short-the-risk`<br>st: `short-full-plate` | ct: `risk`<br>si: `evidence`<br>fmt: `short`<br>beats: `cheap-or-trap` | `short-the-risk` → `cheap-or-trap`. |
| `charts/guided-vs-actual-6y-16x9` | ct: `what-they-said` `management` `the-verdict`<br>st: `full-plate` `plate-with-host-medium` `push-in-on-plate` | ct: `guidance-estimates` `management` `resigned-close`<br>si: `evidence` `land` | `what-they-said` → `guidance-estimates`, which is the chapter type this plate is the picture of. `the-verdict` → `resigned-close`. |
| `charts/guided-vs-actual-6y-9x16` | ct: `short-the-claim`<br>st: `short-full-plate` | ct: `guidance-estimates`<br>si: `evidence`<br>fmt: `short` `earnings`<br>beats: `the-comment` `vs-expected` | `short-the-claim` → `the-comment`, and it also has an earnings home at `vs-expected`. |
| `peers/distribution-16x9` | ct: `the-price` `valuation` `peers`<br>st: `full-plate` `plate-with-host-medium` `push-in-on-plate` | ct: `sector-comps` `valuation`<br>si: `evidence` | `peers` is `sector-comps`; `the-price` is `valuation`. |
| `figures/share-of-4-16x9` | ct: `the-numbers` `cost-structure` `management`<br>st: `full-plate` `plate-with-host-medium` | ct: `how-the-money-is-made` `the-numbers`<br>si: `evidence` | `cost-structure` → `how-the-money-is-made`. `management` dropped — a share-of bar is not a management plate and was there to pad the list. |
| `figures/by-region-5-16x9` | ct: `the-business` `macro` `risk`<br>st: `full-plate` `plate-with-host-medium` | ct: `how-the-money-is-made` `risk` `one-framework`<br>si: `evidence` | `the-business` → `how-the-money-is-made`; `macro` is a FORMAT, not a chapter type — the chapter that wanted it is `one-framework`. |
| `figures/ownership-16x9` | ct: `management` `the-business` `the-verdict`<br>st: `full-plate` `plate-with-host-medium` | ct: `management` `short-interest`<br>si: `evidence` | `the-business`/`the-verdict` dropped as padding; `short-interest` added, because who holds it is the other half of that chapter's argument. |
| `figures/scale-3-16x9` | ct: `the-balance-sheet` `the-numbers` `survivability`<br>st: `full-plate` `push-in-on-plate` | ct: `risk` `the-numbers`<br>si: `evidence` | `the-balance-sheet`/`survivability` → `risk`. |
| `paper/receipt-8-16x9` | ct: `the-numbers` `cost-structure`<br>st: `full-plate` `push-in-on-plate` `plate-with-host-close-up` | ct: `how-the-money-is-made` `the-numbers`<br>si: `evidence` | `cost-structure` → `how-the-money-is-made`. |
| `structure/said-happened-5-16x9` | ct: `what-they-said` `management` `the-verdict`<br>st: `full-plate` `push-in-on-plate` | ct: `guidance-estimates` `management` `resigned-close`<br>si: `evidence` `land` | `what-they-said` → `guidance-estimates`; `the-verdict` → `resigned-close`. |
| `structure/sensitivity-16x9` | ct: `valuation` `the-price` `the-verdict`<br>st: `full-plate` `push-in-on-plate` | ct: `valuation`<br>si: `evidence` | `the-price`/`the-verdict` → `valuation`, which is the only chapter a 3×3 outcome grid belongs in. |
| `charts/multiples-grid-6-16x9` | ct: `the-business` `the-numbers` `segments`<br>st: `full-plate` | ct: `sector-comps` `the-numbers`<br>si: `evidence` | `the-business`/`segments` → `sector-comps` + `the-numbers`. `segments` was the closest thing to a real gap and it is not one: the plate compares names, not segments. |
| `host/close-up-blink` | ct: `*`<br>st: `*` | `"any": true`<br>`"any_shot": true` | `"*"` in both fields. It genuinely does belong everywhere, so it now says so with `"any": true` and `"any_shot": true`. A wildcard string does not resolve against sixteen names. |

### Five entries that were already clean, and were still wrong

`figures/short-interest-9x16`, `charts/insider-flow-{6,12}-9x16` and
`structure/confession-{ledger,statement}-9x16` named **real** SHORT beats
(`the-move`, `numbers`, `the-news`, `the-turn`) — but filed them under `shot_ids`, which
holds per-chapter structural ids. Every name resolved; the field did not. Moved to
`formats: ["short"]` + `beats: [...]`, with `shot_ids` left holding the structural position
for the long-form 9:16 cut. This is the failure mode the task warned about: it fails
silently, because nothing is misspelled.

### The count after

- **60 plate keys** — unchanged. Nothing deleted.
- **15 chapter types referenced**, all 15 of the sixteen.
- **4 shot ids** referenced: `open`, `evidence`, `land`, `on-the-desk`. No others exist.
- **4 formats** and their real beats only; `long` carries no beats of its own, because
  `templates/shots/long.json` holds none.
- **2 entries** carry `"any": true` instead of a wildcard string.
- **Every chapter_types, shot_ids, formats and beats value in the file resolves against the
  sixteen chapter types, the four structural shot ids and the three beat lists.** Checked
  by walking the file against those lists, not by reading it.

The file's `_note` no longer carries a stale-vocabulary warning, because there is nothing
stale to warn about. It now carries a `_vocabulary` block holding the sixteen, the shot
ids, the four formats and their beats — a record of what the entries were checked against,
with `templates/` still the source.

### `moat` — the one thing the mapping could not place, in the other direction

Of the sixteen, **`moat` is referenced by no plate in the kit.** That is not a fragment
defect and it is not fixed by adding `moat` to a plate that is not about a moat, which is
exactly the move that produced the invented list. It is a **library** gap: the kit has no
plate whose argument is durability of advantage — `peers/distribution` and
`structure/sensitivity` are the closest and both are valuation instruments.

*Proposed, not built:* the chapter wants a plate that holds a claimed advantage against
something that would erode it over time — nearer `structure/said-happened` in shape than
any chart in the kit. It needs a decision about what the second track is before it is
worth drawing, so it is a question rather than a plate. `cold-open` is now reached, by
`paper/headline-stack-3-16x9`.

### One defect in this page, found on review and fixed

Worth recording because it is the same shape as a defect this pack already called out, and
because it would have made three of the verdicts above wrong.

`fill1()` set type with the CSS `font` **shorthand**. The shorthand resets every omitted
longhand to its initial value, so it silently set `line-height: normal` — about 1.35em for
Archivo Narrow — over the kit's own pitch. Every two-line fill rendered roughly 16% too
tall and overflowed its published box, **while the section reports said everything was
inside budget**, because the reporter only checked character budgets. That is the budget
reporter's defect inverted: not five false alarms out of seven, but a clean report about
type visibly out of its box.

Two fixes, both in the page:

1. **The pitch is read off the kit, like the face.** `budget.js` publishes
   `BUDGET.PITCH = 1.16` and caps every slot's `maxLines` against it, so the page now
   sets `line-height` from that value as a longhand. A page setting type at any other
   pitch measures a different plate than the budget describes — the same rule that caught
   the insider-flow date row.
2. **The reporter gained the other half of fit.** Every fill's rendered height is now
   measured against the published `slots[name].h` once the real faces have loaded, and
   each section reports it. A fill inside its `maxChars` can still be taller than its box,
   and nothing in the kit reported that.

The verdicts above are unchanged by the fix, and the two numbers that came from a hand
computation are now measurements: the ledger's two lines render **134.5 in a 139-unit
box**, and the deliberate refusal tile in §13 is caught in both dimensions — 120
characters in a 78-character block, wrapping to **4 rendered lines in a 2-line box**.

**One new observation, noted rather than failed.** Nine single-line fills across §10 and
§11 — all of them the `unit` role, 30u type in a 32-unit box — have a line box 2.8 units
taller than the box they sit in. No ink overflows: cap height plus descender is about
0.93em, so 30u puts roughly 28 units of ink in a 32-unit box and overhangs only in
leading. The page reports these as notes, not failures, deliberately — nine false alarms
would be the reporter defect all over again. It is worth one line in the record because
the box does not contain a full line box at the pitch the budgets are capped against,
which is a thing to know the moment anything is drawn tight beneath a unit line.

### Sections 13 and 14 — the rest of the backlog, and the one defect worth the trip

The five sections above covered the 50 assets the UNVERIFIED blocks named. That left drop
five's ten — six filing-reader plates and four host assets — still unseen at 1:1, on the
same page, for the same reason. Sections **13** and **14** close them.

**§13, the filing reader.** `structure/language-shift` and `paper/headline-stack-{3,4}`,
both aspects. These are the class §0.3 exists to catch — plates that are fine until real
words go in them — and they had never been filled at 1:1 in either page. All six pass or
are marginal. `language-shift-9x16` is **marginal** for an authoring reason rather than a
drawing one: 96u type in a 22-character line is four words a line, eight words total, so
the phrase has to be chosen against the budget before the short is written. The landscape
25-character portrait source box holds *The Wall Street Journal* with two characters
spare, which is the longest publication name a real story carries. The section's last tile
is the plate's **refusal** — a 118-character pasted filing sentence in a 39×2 box, over
budget on purpose, so the contract is visible rather than described.

**§14, the seated pose, composited.** The gap here was never legibility. §4.1 said it
plainly: a rig change can produce a figure that measures correctly and stands wrong, and
nobody had composited the pose. The section does the composite the renderer will do, from
the plate's own published numbers, and puts the wrong scaling beside it.

- **The seated ratio passes.** Composited at `target × 0.7394` he lands at the desk, at
  desk height, feet on the floor, pin holding. The standing equivalent the ratio is
  derived against is 1,297 units and the standing pose built in the same run measures
  **1,299** — two units apart on a figure 1,300 tall. Arithmetic confirmed by a render
  rather than by itself.
- **Scaled as a standing pose it fails, visibly, and nothing looks broken.** He is 35%
  oversized, sitting in exactly the right place, with the desk at the right height. That
  is the failure §4.1 said no still would show, now shown.
- **`host/empty-chair`'s scaling contract fails at 1:1.** This is the find. Both plates
  draw the same chair — one function, which is the pack's own claim — but the empty chair's
  published contract scales its 789-unit span to the anchor's **standing** target height,
  while the seated pose scales through the 0.7394 ratio. On `room/desk-front-16x9`:
  scale **0.7123** against **0.4333**, so the chair renders **562 units against 342 —
  64% larger — and 562 against the seated man's 416**, which is a chair taller than the
  man who sits in it. Its back sits 220 units higher up the frame on the one cut the plate
  exists for: him, then his chair.

  *Proposed fix, not applied:* the empty chair publishes a ratio of its own — **789 /
  1,297 = 0.6083** — and its contract reads "scale so the span equals target × 0.6083".
  That puts both plates at scale 0.4333 and the chair at one size. It is a **manifest and
  contract change rather than a drawing change**, and it is the cheapest of the three open
  fixes; it still changes what `plates.js` publishes, so it is a proposal.

  The reason this was invisible is worth recording: *"it is the same chair the seated pose
  sits on (one function), so the absence reads"* is true of the **drawing** and false of
  the **composite as contracted**. One function, two sizes. The claim is what hid it, and
  only a composite could see it — no baseline, budget or byte count would.
- **Attempted and inconclusive: "talk frames differ only at the mouth", on the seated
  pose.** The page rasterises base against `-talk` at 1:1, differences them, and reports
  the bounding box of every changed pixel against the published `mouth` region
  (552,927 → 598,957). The result is **no pixel differs** — base and `-talk` rasterise
  identically at boil 1, because the strip's variation lives across its *frames*, not
  between the base and the strip. So the comparison exercised nothing and **the contract
  is still unchecked on this pose.** The check wants the three frame files differenced
  against each other, which needs the ingest's frame output rather than a `P.toSVG()` at
  one boil index. Recorded as unverified below rather than counted as a measurement.

  The attempt is left on the page because a check that returns nothing is worth seeing
  return nothing. The §14 verdict for the strips is **marginal** rather than passes for
  the same reason: what was established is that the three head-and-shoulders crops show
  no drift at 1:1, which is not the contract.

### Check P, and the check that was already failing

**`preflight.html` is sixteen checks, A–P.** Check **P** is new and exists because the
proof page had the defect rather than the plates: it asserts library-wide that every box
declaring `maxLines` can hold those lines at the kit's own pitch. `budget.js` *derives*
`maxLines` from box height at 1.16em, so the relationship holds by construction — and a
property that holds by construction is the kind that stops holding when the construction
is edited, with nothing to say so. Check J found precisely this on one plate by accident
in drop six: `language-shift`'s phrase box derived **1.997** lines where the plate needed
two. P is that arithmetic across all 270 assets, riding on check A's build rather than
taking a second library pass.

**Result: 2,280 type slots, 357 of them multi-line, and none is short of the lines it
declares.** The `maxLines` derivation is now confirmed library-wide rather than trusted.
Twenty-eight single-line boxes have a line box taller than the slot — sixteen of them the
`unit` role at 30u in 32u — and P **notes** those rather than failing them: cap height
plus descender is about 0.93em, so no ink leaves the box and it overhangs in leading only.
Failing them would be 28 false alarms, which is the reporter defect this pack already
called out and the reason check O's first version was thrown away.

**And the first cut of P shipped one anyway, which is worth recording.** It failed any box
shorter than its point size — one hit, `figures/big-number-l2-16x9`'s `value`: 350u type
in a 340-unit box. That is not a defect. An em box is not ink; at 0.93em the value inks
about **325.5 units in a 340-unit box** and fits with room. The threshold is now ink
rather than point size, and P reports **0** boxes where the ink does not fit. Three times
now this pack has had to learn the same thing about its own reporters, so it is written
into the check: the constant is named `INK`, off the faces' metrics, and the comment says
why the obvious criterion is the wrong one.

**And running it turned up a check that had been failing since drop six.** Check E — the
breathe gate — was **FAIL** on all four `charts/insider-flow` plates: *"nothing breathes,
and it is not on the still-by-design list."* It is not a defect in the plates. The plate
draws a time axis, its ticks and the date rules — 81 marks on the 12-column landscape
plate, and **all 81 are byte-identical across boil indices** — because every trade is a
`mark-N` region the compositor fills from `axisY`. Its entire drawn content is the
measurement reference the marks are read against, which is the argument
`structure/implied` already carries, arrived at independently by a different author.

So the fix is the **declaration**, not the drawing: the four keys join `STILL_BY_DESIGN`
with that reason stated, and E passes. Worth recording plainly — the plates shipped frozen
and unnamed for two drops, and the gate is built to surface exactly that. The omission was
in the list, not in the artwork. For contrast, the other §3 plates do breathe:
`macro-series` moves 8 of 159 marks, `short-interest` 2 of 59. The still-by-design list
is now 32 plates.

**All sixteen checks pass**, in 64.7s in one browser process with no rasteriser. P is also
wrapped in its own try/catch, for the reason the page paints as it goes: a throw inside a
late check used to take every check after it down with it, silently, leaving the page
looking merely slow.

### UNVERIFIED — drop eight

1. **The 1:1 pass is a browser render, not resvg.** Same standing caveat as every measured
   number in this pack: colour management, gradient interpolation and blur are the
   browser's. The geometry is the kit's own published numbers, so boxes and budgets are
   exact; tone judgements carry the rasteriser caveat.
2. **1:1 is not viewing distance.** The page answers "is this legible at delivered scale",
   which is the question it was built for. It cannot answer what a phone at arm's length
   in daylight does, and the `seasonality-6y-9x16` verdict is the one place that
   distinction decides the result — it is marginal *because* of distance, not size.
3. **Nobody has cut night against dusk**, unchanged from §4.2. The side-by-side row shows
   the difference reads *as a difference*; whether a cut between hours reads as time
   passing or as a continuity error is a question for a real edit.
4. **The keep-out fractions are still designed-against**, unchanged. The 1:1 pass confirms
   the content band clears the zones *as published*; it cannot confirm the zones.
5. **The two proposed fixes are unimplemented by design.** `qoq-yoy-9x16`'s figure step
   and the confession ledger's block height both change a drawing function, which is a
   design decision rather than a cleanup. Neither has been tried, so neither is costed.
6. **The mapping is a reading of `templates/`, not a run against it.** Every value
   resolves against the recorded sixteen, the four shot ids and the three beat lists. What
   has not happened is the renderer loading this fragment and reporting reachability from
   its own side — which is the check that would catch a *correct* name in the wrong
   chapter, and the one thing a name-resolution pass cannot see.
7. **Whether each plate belongs in the chapter it is now mapped to is editorial.** Name
   resolution is mechanical and is done. A plate landing in `the-numbers` that a director
   would rather see in `how-the-money-is-made` is a judgement call, and 44 of them were
   made in one pass by one reader.
8. **The seated composite is one room.** `room/desk-front-16x9`, whose anchor target is
   562 units. The ratio is a ratio so the arithmetic carries to the other eleven angles,
   but `low-desk-height-16x9` has a target of 1,145 and a floor line outside the frame,
   and that combination has not been composited. The empty-chair defect scales with the
   target, so it is worse there, not better.
9. **`new-plates.html` still has no §3 or §4 section.** §13 and §14 close the 1:1 gap;
   the §0.3 gap — every new plate filled with real words on the fills page — is closed
   for the filing reader only incidentally, by this page doing it at 1:1 instead. The
   host assets have no §0.3 case at all, correctly: they carry no type.
10. **Nothing in the kit has been seen in motion.** Unchanged, and now the largest
   remaining class. Every breathe share, boil index and loop claim in the pack is
   asserted; the three seated strips are one figure at one boil index by construction and
   the head-and-shoulders crops show no drift at 1:1, which is not the same as watching
   them run.
11. **"Talk frames differ only at the mouth" is still unchecked on the seated pose.** §14
   attempts it and the comparison comes back empty — base and `-talk` rasterise
   identically at boil 1, so nothing was exercised. The real check differences the three
   frame files against each other and wants the ingest's frame output, not a single
   `P.toSVG()`. The contract remains asserted for this pose, as it is for every other.
12. **The vertical-fit pass is the browser's text layout, not the compositor's.** It
   measures at `BUDGET.PITCH` with the real faces, which is the right pitch and the right
   faces — but line *breaking* is the compositor's, by measured width. A fill that fits at
   an authored newline can still break elsewhere in the real renderer, which is §2's
   standing `qoq-yoy` label caveat generalised to every multi-line box on the page.
13. **Check P is geometry, not typesetting.** It asserts the box can hold the lines at the
   published pitch. It cannot assert that the compositor uses that pitch — nothing in the
   kit can, and a renderer setting its own leading reproduces the exact defect this drop
   found in the proof page. Worth one line in the renderer's own audit.
14. **The 28 noted leading overhangs are judged, not measured.** "No ink leaves the box"
   rests on cap-height-plus-descender being about 0.93em for these faces, which is read
   off the metrics rather than off a raster. The one that would repay a look is
   `huge 350u in a 340u box` — the box is shorter than the point size, and it is the only
   signature where that is true.
15. **`charts/insider-flow` is now declared still by design, and that is a judgement.**
   The measurement is certain — all 81 marks identical across boil indices — but whether
   the plate *should* have breathing furniture, rather than being all reference, is a
   design call I made by matching `structure/implied`. A reviewer who thinks a twelve-mark
   Form 4 plate wants a panel or a rule behind it is disagreeing with the declaration,
   not with the number.


## Drop seven — §4.2, and it stopped being a switch

**270 assets, 924 frames, 0 errors.** Twenty-four new room assets: the dusk variant on
all twelve angles, both aspects.

### It ships as assets, not as a mode, and that is the change

Time of day shipped last drop as a library-wide flag — `TIME_OF_DAY = null` in
`build.js`, one value for every room. That was the right shape for something that could
not be turned on: one switch, easy to revert, obviously off.

It is the wrong shape now. **A flag does not give you a variant axis; it makes the whole
channel dusk.** So the variants are keys: `room/desk-front-dusk-16x9` sits beside
`room/desk-front-16x9`, and the director picks an hour per episode by picking keys —
exactly how `roomRoles` already resolves `talk` to one of three desk angles by seed.
Nothing in the engine needs a mode, and an episode that wants night simply does not
reference the dusk keys.

The old flag stays in `build.js` at `null` and is now only useful for rendering the whole
library at an hour to look at it.

### Verified rather than asserted: they are variants, not new rooms

Every one of the 24 has **byte-identical slot boxes, `floorLineY` and `hostAnchor` to its
night twin** — checked, all 24, zero drift. Only the wall tone differs. So a shot template
that works on `room/desk-front-16x9` works on `room/desk-front-dusk-16x9` with no change
at all, and that is what earns them the word "variant".

The tone lands on all 24 (+21KB of ink on a landscape plate). Worth stating because the
first build of this drew **nothing** and said nothing: `hatch2` lays no wash below opacity
0.4 and returns early for a region over 5.5% of the plate, so a faint wall-sized hatch is
both and emits an empty string. Check M exists because of that, and check L now asserts
the bytes rather than trusting the call.

### §1 is what unblocked it, and the loop is closed on the same page

A toned wall behind the chapter-opener title box is *precisely* the borrowed legibility §1
measured — that is why §4.2 was held back rather than merely deferred. §1 chose `card`,
the title now carries its own ground, and `proof/title-ground.html` has a new row:
**`room/whiteboard-wall-dusk-16x9`**, the worst angle in the family at the new hour, with
the tone actually on the wall. If the card holds there it holds anywhere the room family
is going. The page measures it in the same table as the other five walls.

### `day` is deliberately not shipped

The set is lit by one warm desk lamp and one cold monitor, and every cast shadow in every
room derives from those two. **At dusk that is still true** — the light outside is failing,
the lamp is still the source, the shadows stay honest. In daylight it is false: the lamp
would not be the brightest thing in the room, and every shadow on every prop would point
the wrong way. Shipping `day` means a relight, which is a substantially larger job than a
wall tone and is not what §4.2 asked for.

`room()` still accepts `"day"`, so the work is not thrown away and someone can render one
to see the problem for themselves. No asset uses it. `TIME_OF_DAY_VARIANTS` in
`build.js` is the one-line place to add it if the relight ever happens.

### UNVERIFIED — §4.2 *(historical — drop eight answered two items)*

The dusk 1:1 pass and the card's contrast floor on a dusk wall are both done, in §12. What is below survived, and the relight item gained drop eight's finding that it shows on the widest angles.


3. **Nobody has cut night against dusk.** The variants exist so a long chapter can feel
   like a different scene; whether a cut between hours reads as time passing or as a
   continuity error is a question for a real edit, not a proof page.
4. **The shadows are unchanged and that is a deliberate limit, not an oversight** — see
   above. At dusk it is defensible. It is the reason `day` is absent. **Drop eight adds
   where it shows:** at 1:1 on `wide-dusk-16x9` the desk's cast reads as lamp-lit while
   the wall reads as late light from outside, so a director cutting dusk should prefer the
   tighter angles. No fix proposed — a relight is a much larger job than a wall tone.

## Drop six — §1 the furniture, §2 the confession, §3 the data with nowhere to go

**246 assets, 852 frames, 0 errors, 0 text nodes.** §1, §2 and §3.1–3.4 are built and
wired to the real vocabulary. §3.5, the channel art, is deliberately not built — it needs
a decision, not a plate. Baselines regenerated against this engine.

### §3 — five plates the pipeline already has data for

Each exists because the code pulls the data and had nowhere to draw it. Ten assets.

**3.1 `figures/short-interest`** replaces `figures/big-number-l2` in the short-interest
chapter's evidence beat, and the reason is the whole design: "forty million shares short"
is enormous or trivial depending entirely on the float, so a number on its own is what
this plate exists to remove.

Four quantities, and **only one of them is a proportion.** Shares short against float
gets the bar — the outline *is* the float, the fill inside it is the short interest, and
the reader does not divide anything. Days-to-cover is a duration and cost-to-borrow is a
rate; drawing either as a bar would invite a comparison that means nothing, so they sit
as figures under a dividing rule. All four values are one type role at one size: a plate
that sets days-to-cover larger has decided which of the four the story is.

Nothing is pre-coloured and nothing is marked — no threshold line, no tick at a level the
plate finds interesting. A 30%-of-float short position is a squeeze or a nothing depending
on who holds it and why.

**3.2 `charts/insider-flow-{6,12}`.** Form 4 trades on a time axis, sized by value —
`figures/ownership` is the static picture, this is the flow. Count variants 6 and 12: six
is a normal quarter where individual trades are still the argument, twelve is the case the
plate exists for, where the pattern is.

**Above for a purchase and below for a sale is not a verdict**, and it is worth being
explicit because it looks like one. Direction is the *data*, exactly as a waterfall step
can add or subtract. What would be a verdict is colour, and there is none: one ink, one
weight, both ways, so a plate of all sells looks like a plate of all buys inverted.

The subtler trap this plate had to close: **both halves share one scale.** Scaling buys
and sells independently would make a $200k purchase look like a $4m sale — a verdict
reached by arithmetic, which is the hardest kind to notice. `scale-above` and
`scale-below` are published separately so the renderer can *state* the scale, not so it
can use two.

Measured consequence: at twelve marks in 9:16 the per-mark "who" box is under six
characters, so that aspect publishes one `who-note` line instead of a row of initials.
`budget.js` decided that, not me.

**3.3 `charts/macro-series`.** A decades-long FRED series: ten labelled decades, forty
unlabelled minor ticks, four band regions and a source line. **The bands are regions and
none is filled** — a recession's extent is data, so drawing one would be drawing the data.
Fill the ones the series spans and leave the rest empty; do not distribute four because
four exist. The `source` slot is not optional: a macro series with no provenance is the
one chart on a real-numbers channel that nobody can check.

**3.4 `structure/end-card`.** The closing frame built around the platform's furniture —
the only plate in the kit whose layout is dictated from outside it. Three keep-out zones
(two video cards, a circular subscribe) are published in `meta.keepOut` as fractions of
the frame, and the content band is *derived* from them rather than authored beside them,
so correcting a zone moves the type with it.

**I checked the keep-out claim rather than asserting it, and it was overstated.** Slots:
0 overlaps on both aspects. Authored marks: 0. But the **paper surface does** extend under
the zones — necessarily and correctly, because that is what a ground is and the platform
draws opaque elements on top of it. The claim is now what is actually true and testable:
no slot and no authored mark. What must not be under a subscribe button is content.

One copy decision in the plate: the `hand` slot is what the viewer does next in the
host's own register — "the ledger is in the description" — **not** "like and subscribe."
The platform is already drawing a subscribe button in the same frame, and saying it twice
is worse than not saying it.

### §3.5 — the channel art, and why it is a question rather than an asset

Every viewer sees the banner and the profile *before* they see a frame of the kit, so I
agree it matters. But a banner drawn from the host and room families is **illustration,
not plate work**, and I should say plainly what I can and cannot do: I cannot generate
images, and hand-writing an SVG figure at banner scale produces a diagram, not artwork.
The `host/` family works because it is procedural line-work seen at video scale in
motion; the same geometry sitting still at 2560×1440 as the first thing a viewer ever sees
is a different job.

Three routes, and this is the one item in the brief I would rather you picked:

1. **Compose it from existing `host/` and `room/` plates** — render `room/wide-16x9` at
   banner crop with a host cut-out composited in, at the safe area. Cheap, honest, and it
   is unarguably the current kit. Risk: a banner is not a frame, and a video still used as
   channel art tends to look like a video still.
2. **Brief an illustrator** with the kit as reference. Best result, not something I can
   deliver.
3. **I attempt it as drawn SVG** knowing it will read as a diagram. I do not recommend it,
   and I would rather be told to than offer it.

What I *can* do without a decision is the geometry: YouTube's banner is 2560×1440 with a
1546×423 safe area, and the profile is square and shown as a circle — so both need
composing against a crop that most viewers never see in full. That much is ready whenever
the route is chosen.

### The preflight, now thirteen plus two

`proof/preflight.html` gained **N** and **O**, so it is fifteen checks, A–O, all
passing. Both assert things that are invisible in a render.

**N** covers §1, §2 and §3.4. The lower third is asserted still **under a forced boil
index**, not merely shipped as one frame — the one-frame build would hide a broken pin
until someone gave `overlays/` a boil strip, at which point the one asset on screen for
forty minutes starts to crawl. The confession's three bodies are asserted to be one type
role on one budget with congruent boxes, which is §2's tone decision expressed as
geometry: a 4pt difference between "what I said" and "what I got wrong" looks like
nothing and reads as a verdict. And the end card's zones are asserted clear of every slot
and every **authored** mark — authored being the operative word, since scanning the
emitted SVG counts the paper ground and reports 14 false overlaps, which is what the
first version of that check did.

**O** is the identifier check, and **its first version was wrong in a way worth
recording.** The mistake it exists to catch happened three times: a short identifier
handed the full measure because nothing was going to sit next to it, and `budget.js`
duly deriving room for a sentence — 59 characters for "2024", 15 for "$HTZ", 26 for
"no. 14".

My first attempt found them geometrically: short role floor, wide box. That cannot work,
because **a role's `maxChars` is itself derived** — `budget.js` sets it to the minimum
across every box using the role. So the test only finds roles serving boxes of different
widths, which is normal. It flagged ten plates and all ten were false; `structure/flow`'s
caption role reads a floor of 6 because its narrowest caption box is 6, and there is
nothing wrong with it.

Nothing in the manifest separates an identifier from a caption, because the difference is
semantic. So it is **declared**: `identifier: <intended max>` on the slot, and the check
asserts the derived box is within 1.6× of it. New identifier slots opt in — the same
structural pattern as `pin()`, a rule that cannot be broken by someone who has not read
the comment.

**It immediately caught a fourth instance, which was mine.** `structure/language-shift`'s
landscape year box still held 18 characters against a declared 10 after I narrowed it the
first time — ×1.80. Narrowed again to 22% of the measure: 13 characters, ×1.30. Eight
slots now declare themselves identifiers and all eight are inside tolerance.

### One thing the baseline cannot see

Narrowing that year box changed every budget on the slot and produced **zero** baseline
diffs — correctly, because `baseline-14.json` hashes the emitted SVG and a slot is not
drawn. The renderer composites against slot boxes, so a slot moving is exactly the kind
of change the pipeline cares about and that file will never report it. Written up in
`audit/README.md`; the checks in `preflight.html` are where slot changes get caught, and
they are not redundant with the baseline. A manifest baseline would close it, and it
wants a decision about what counts as a meaningful slot diff before it is worth writing.

### Still outstanding after this drop

- ~~`preflight.html` has no check for §1, §2 or §3~~ — **closed, drop eight.** Check P
  makes it sixteen, A–P; and check E's failure on the four `insider-flow` plates is
  resolved by declaring them still-by-design. Checks N and O
  cover §1, §2 and §3.4. Still missing: **insider-flow's shared-scale contract**, which is
  the one claim in §3 that cannot be asserted from the kit at all — the plate publishes
  both scale slots and says loudly that they share a scale, but a renderer using two would
  produce a plate that looks entirely correct. That is a shot-audit check and it lives on
  the renderer's side.
- ~~The right-aligned-identifier trap~~ — **closed.** Check O, declared intent, and it
  caught a fourth instance on the way in. See above.
- ~~The stale invented vocabulary in the older `roles.fragment.json` entries~~ —
  **closed, drop eight.** 44 of the 60 entries remapped onto the sixteen real chapter
  types, the four structural shot ids and the real format beats. Mapping table in
  §VOCABULARY above. Nothing deleted, no chapter type invented, no wildcard strings left.

### UNVERIFIED — §3 *(historical — drop eight answered the 1:1 item)*

§11 rendered all ten pipeline plates at their worst count. What is below survived.

2. **The end card's zone fractions are designed-against, not confirmed.** I could not
   check YouTube's current published spec. They are in the manifest so one correction
   fixes the plate; the 9:16 case is worse, because shorts' end-screen behaviour differs
   from long-form and I could not check it at all.
3. **`insider-flow`'s one-scale contract is unenforceable from the kit.** The plate
   publishes both scale slots and says loudly that they share a scale, but a renderer that
   uses two would produce a plate that looks entirely correct. That is a shot-audit check,
   and it does not exist.
4. **`short-interest` assumes all four quantities are present.** If the pipeline has float
   and shares-short but no borrow rate — common for illiquid names — the plate has an
   empty figure and no shape for it.
5. **`macro-series`' four band regions are a guess at the usual count.** A series spanning
   1970 to now has five or six recessions, not four, and the plate would silently drop the
   extra ones.

**236 assets, 818 frames, 0 errors.** §1 and §2 are built. §3 is not started.

Housekeeping first, both from your notes: the fragment is now **`roles.fragment.json`**,
because a copy operation does not read a "merge rather than replace" note and overwriting
the renderer's `hostRoles`/`hostPoses`/`roomRoles` would break every room and host shot
in every video. Its `_note` also carried a **stale-vocabulary warning** — the invented
chapter types and shot templates in the pre-existing per-plate entries were not read off
`templates/`, so every one of those values was flagged UNVERIFIED until the rewrite pass.
§1's and §2's own entries use the real sixteen chapter types, the real shot ids
(`open`/`evidence`/`land`/`on-the-desk`) and the real format beats. **That pass landed in
drop eight and the warning is gone from `_note`; the measured counts were 32 invented
chapter types and all 9 shot-template names, across 44 of the 60 keys.**

### §1 — one decision, two surfaces

`proof/furniture.html` renders both together, which is the point: deciding them
separately produces two answers that do not match.

**`overlays/lower-third-{16x9,9x16}`.** Two slots rather than one formatted string —
the ticker is a proper noun that must not wrap, the tagline is copy that may change, and
one string cannot carry two failure modes. It carries its own ground for §1's reason,
but **no tape**, unlike the title card: tape says the object arrived after the room did,
true of a chapter title and false of the channel's own furniture.

Three things worth reading off it:

- **It does not boil, and that is enforced twice.** On screen longer than any other asset
  in the product; a wobble re-drawn three times a second at the edge of vision for forty
  minutes is a crawl, not craft. `NO_BOIL_KEYS` ships one frame *and* every mark is inside
  `pin()`, so it cannot wobble even if the overlays family is later given a boil strip.
  Structural guarantee rather than care, same as no text nodes.
- **The ticker box is 44% of the measure.** At full width `budget.js` derived 15
  characters — room for a company name in a slot whose job is `$HTZ`. Narrowed it derives
  6 in landscape and 8 in portrait. Same trap the language-shift year box hit.
- **The ground that settles it is the filing screenshot**, not the chart. White type with
  a black outline on a near-white page loses its fill entirely and leaves the outline
  doing the work — and that is today's build, on the one persistent brand element in a
  forty-minute video.

**Captions: deliberately a different register.** The kit's *materials* without its *hand*
— kit ink `#1C222A` on kit ground `#E6DDC9`, the kit's own Courier Prime, no outline, no
drawn edge, no wobble. `BorderStyle=4` is the load-bearing field: it swaps the outline for
a box, which is the same argument §1.1 and the title card both make, and that is what
makes this one decision rather than two.

The argument is scale and duration, not taste. A wobbled edge is a mark at 78px and a
rendering fault at 22px. libass re-renders every frame with no boil index, so the kit's
hand there is either dead still — which reads as an effect that failed — or re-wobbled at
25fps, which crawls under running text. What is lost is the wobble, the grain and the
bloom rim, stated plainly so nobody reopens this expecting it to be cheap. What is kept is
the part that makes the furniture read as a set.

**What changes from today:** the typeface, the ink colour and the ground become the kit's,
and the outline goes. That is the whole diff, and it converts an accident into a decision.

### §2 — the confession, and my recommendation is `ledger`

Two treatments, both shipped (four assets). They differ on a nameable axis: **what carries
the credibility.**

- **`statement`** — the correction is as considered as the claim was. Three blocks as one
  continuous statement, one left edge, one type size, one rail with a spur into each.
  Nothing marks the third block as the bad one.
- **`ledger`** — he keeps a record of these. A numbered, dated entry on a ruled sheet.

**I would pick `ledger`, and the reason is that it is the only one of the two that cannot
be read as a performance.** A single confession laid out carefully is still a confession
laid out carefully; a viewer can reasonably wonder whether this is the one he chose to
admit. "No. 14, and I write them all down" closes that off, and it is the one thing a
single-confession treatment structurally cannot say. It also matches the data — the
pipeline already tracks these in a ledger, and `entry-no` puts the count it already holds
on screen.

Its risk is the opposite failure mode: a ledger entry drawn small and neat is the
confession hidden at the bottom of the frame. So the body type is the **same size** as the
statement treatment's — ruled like a book, set like a headline.

**What both refuse, in the plate rather than in a comment:** no cross, no strike-through,
no red, no rule through the old claim. All three bodies are one type role at one size in
`structure`, so neither plate can mark which is the bad one. If a script asks for the old
claim struck, that is `annotations/strike-out` — and worth arguing about before it is
applied, because a confession that strikes its own claim is performing contrition, which
is the thing the plate exists not to do.

It is **not** `said-happened` re-pointed: that plate is a company's claim against the
outcome, built to read as an indictment. Aimed at the host it would make the plate an
indictment of him.

One layout finding, caught by the fit arithmetic rather than by eye: **the portrait plates
had 680 units of dead space** below the blocks on a 1920-tall frame — the whole statement
bunched into the top half, reading as though the plate had been cropped. The gap is now
derived from the band between the head and the caption and clamped, and the group is
centred in what is left. `meta.fit.fillsBand` publishes the number: 0.77 landscape, 0.59
portrait.

### UNVERIFIED — §1 and §2 *(historical — drop eight answered the 1:1 item)*

The 1:1 item is gone: §8 and §9 of `render-scale.html` answered it and the verdicts are in drop eight's table. What is listed below survived that pass and is restated in **the live list** at the top of this file.

2. **The caption `force_style` string is unrun.** I cannot run libass here. The colours,
   the face and `BorderStyle=4` are straightforward ASS fields; `MarginV` and the box's
   exact inset want one real render to confirm.
3. **The filing-screenshot ground is a labelled placeholder**, not a real capture. Its
   *value* is what matters for the argument — a bright near-white page — and that much is
   right, but the real thing will have structure the placeholder does not.
4. **`preflight.html` has no check for §1 or §2.** The properties that want asserting are
   named in the plate comments: the lower third's pin (it is the one asset where stillness
   is load-bearing), and the confession's one-role/one-budget congruence across all three
   bodies, which is the tone decision expressed as geometry.
5. **The confession's three-block shape assumes the ledger always has all three.** If the
   pipeline ever holds a confession with no "what happened" yet — wrong, but not yet
   resolved — neither treatment has a shape for it. Not handled.

## The check pass — what a full read-through turned up

Three real defects, all in the proof pages rather than in the plates, and all found
by looking rather than by asserting.

**1. `preflight.html` had stopped finishing.** Check M's first version did its own
full-library pass to count hatch calls — 230 room-weight draws on top of check A's 804
frames — and check L drew every room plate seven times for the time-of-day comparison,
144 more. The page ran ~40 seconds of blocking JavaScript and rendered once at the end,
so nothing painted and the load never completed. Same lesson as the review page that
hung on twelve room plates: the check was right and the way it was run was not
affordable.

Fixed three ways. M now rides on check A's build (the hatch counter is installed before
anything draws, so the check costs nothing beyond reading it). L samples **four** plates
spanning every `floorY` case instead of all eighteen — the wash is one call before any
angle branch, so eighteen plates of identical code prove nothing the fourth does not.
And the page is now async: it paints each check as it lands and names what it is working
on, so it is readable from the first second. Thirteen checks, A–M, all PASS.

**2. `new-plates.html`'s budget reporter was wrong about wrapping** — and it was wrong
in the direction that matters, crying wolf. It compared whole strings against
`maxCharsPerLine`, so an unbroken 52-character statement in a 33-per-line box holding
three lines was reported as over budget. Five of its seven complaints were false. A
report that flags correct copy trains people to ignore it, which is worse than no
report. It now asks the right question per role: `maxChars` is a one-line box and the
whole string must fit; `maxCharsPerLine` is a wrapping box, so an unbroken string is
checked against the whole block and only AUTHORED lines (the ones with a newline, as
qoq-yoy's labels have) are checked per line.

**3. And under that, two genuine overflows in delta-14's own sample copy.**
`figures/waterfall-5s-9x16` step figures were six characters — "−2,840" — in a
measured five-character box. Five steps in portrait leaves ~130 units a column, and the
step role is 38-unit Courier. The sample is now scaled to what a script would really
write at that count, and the constraint is worth knowing: **at five steps in 9:16 a step
figure gets five characters.** `roles.fragment.json` already routed shorts to `-3s`; this is the
measurement behind that advice.

Everything else came back clean: 230 assets, 804 frames, 0 errors, 0 text nodes, all
references in all six proof pages resolve, every fill on the render page inside its
derived budget, and no new slot-geometry defects — the nine off-canvas slots and ten
zero-size slots in the library are all delta-14's and all deliberate (annotation
captions sit outside the sticker by design; the zero-size ones are `control` regions
that are explicitly not drawn).

## Drop five — §3, and as much of §4 as is honest

**230 assets, 804 frames, 0 errors.** §3 and §4 are both complete. §4 is complete — each stated below rather than averaged
into a claim.

### §3.1 · `structure/language-shift`

Two blocks, then and now, each with its year. **Stacked, not side by side** — side by
side is what `figures/compare-side` is, and it reads as two claims about two things.
One left edge, one width, one type role, one rail down the side with a spur into each
block: that is what makes them read as the same statement in two versions, and it is
geometry rather than intent, so it is assertable.

**It enforces the phrase rather than inviting a paragraph.** Measured, the box holds
two lines at 31 characters in 16:9 and 22 in 9:16 — a four-or-five-word shift fits and
a pasted filing sentence is over budget, which means it does not render. The
constraint is the plate's, not the writer's discipline.

**It does not draw the diff.** No strike-through on the old, no highlight on the new,
both phrases in one role in `structure`. Emphasis is the annotations family's, applied
by the compositor — `roles.fragment.json` names which marks. Fixed shape, no count variants:
there is one pair, and a second would be a list of shifts.

Two defects the derived budgets caught during the build, both worth recording because
neither is visible in a render:

- **`maxLines` came back 1 on a two-line box.** `budget.js` derives lines as
  `floor(box.h / (size × 1.16))`, and `blockH` rounds 2 × 120 × 1.16 down to 278 —
  which divides to 1.997 and floors to one. The box was a quarter of a unit short of
  holding the two lines it was built for. Cleared the boundary rather than authoring
  around it.
- **The 16:9 plate overflowed its own frame.** At a 120-unit phrase the second block
  ran to y=1055 against a caption at 950. The phrase is 96 in both aspects now, which
  also means one size and one budget across the two. `meta.fit.clears` publishes the
  arithmetic.

### §3.2 · `paper/headline-stack-{3,4}`

Three or four headlines, each with a date and a source, **oldest at the top** —
reading down is time passing. Not a timeline: no rail, no interval, evenly spaced
whatever the dates say, because the argument is how many there have been, not how far
apart. `structure/said-happened` is the timeline and `meta.notATimeline` says so.

Each item is a clipping: a ground-coloured strip with a drawn edge top and bottom,
alternating which end lifts. **Not rotated** — that is a contract, not a style: a
rotated strip needs rotated slots, and every box in this library is axis-aligned
because the compositor's fill is. The askew lives in the hand on the edges.

Both counts share one strip height and one headline size, so a script can swap three
for four without the budget moving. **The four-item landscape stack overflowed too**
on the first build (y=1288 on a 1080 canvas) — the source's height was being counted
in the strip when the source sits on the date's row. `meta.fit` publishes top, strip
height, gap and whether four clears the caption.

### §4.1 · `host/sitting-at-desk` — the brief's top-priority pose, and it is a rig term

Not a new drawing. Every landmark on the figure comes out of `at(n)`, so the seat drop
is applied to `at` itself and the head, shoulders, spine curve, arms and face come
down with it unchanged — it is recognisably the same man sitting down, which is the
whole requirement. The thighs run forward at seat height, the shins drop to the floor,
and the near leg carries its knee further out and lower so the pair reads as two legs
at two depths rather than one leg drawn twice.

He sits **forward, elbow on the desk** — the second-deepest lean in the set. A man
sitting upright in a chair reads as an interview; this channel is a man at his own
desk at three in the morning.

**The scaling contract is the finding.** A room's host-anchor scales a host until
`floorLineY - figure.y` equals the anchor height. Applied unchanged, a seated Dennis
is scaled **up** until his seated height fills a standing anchor — a 36% oversized man
sitting in exactly the right place, and no still would show it: he would simply look
close to camera. So the plate publishes a measured ratio — **0.7394**, from 959 units
against a standing 1297, derived from the rig rather than from a head count — and the
renderer must scale by `targetHeight × ratio`. Three strips, like every pose: he talks
and idles sitting down.

**The chair is drawn on the host plate**, not in the room, because a seated cut-out
over a set with no chair is a man hovering at desk height. The cost is that it is the
same chair in every room, which is the lesser problem: it is his chair. It is hatched
at about half his opacity and outlined at two thirds his weight — `room/` doctrine is
that he is the highest-contrast object in any frame he is in, and that has to hold
inside his own cut-out.

### §4.3 · `host/empty-chair`

The same chair with nobody in it — literally the same function, so the two cannot
drift into being two different chairs. That shared geometry is the only reason this
one was cheap enough to ship in this drop. It scales like a figure, with no new
contract, and it gets the same contact shadow: without it the chair hovers, which is
the defect it exists to avoid.

### §4.2 · time of day — a variant axis on the existing rooms

A time-of-day variant is the same room at a different hour, so it is an argument to
`room()` rather than eight more angles: every prop, shadow, slot and anchor stays
exactly where it is, and the tone goes on under everything the angle branch then
draws — no branch needs to know about it. `engine/build.js TIME_OF_DAY` takes
`"dusk"` or `"day"`; it ships `null`, and the room family is byte-identical to
delta-14 (verified, both ways).

Dusk warms the wall and weights the ceiling joint, because the light left in the room
is coming in low from outside. Day lifts it. Both fray at the join rather than ending
on a line — a tone that stops on an edge is a painted stripe. Measured, every one of
the 18 set plates takes the tone in both aspects; the four `wall-of-calls` plates do
not, and correctly: those are full-frame board plates drawn by a different author,
with no set in them to light.

**The finding, and it is the useful part of this section.** The first build called
`H.hatch(wall, {opacity: 0.34, …})` and the dusk plate came out **byte-identical to
the night plate** — two marks pushed onto the colour layer, zero bytes in the SVG.
`hatch2()`, the hand-2 path every room draws through, treats the authored opacity as
*coverage*: it lays its wash only when `op >= 0.4` or the region is under 2,600 units
square, and it returns early for a `plane` — any region over 5.5% of the plate. A
faint wall-sized wash is both non-material and a plane, so it drew nothing and
reported nothing. 0.42 would have worked; 0.34 silently did not.

So the washes are emitted as fills with a real `fill-opacity`, the same way
`titleGround()` does it and for the same reason. **Anything else in this kit that
wants a large area of faint tone has that trap waiting for it** — it is worth a
pre-flight assertion (a hatch call that returns an empty string is almost always a
mistake), and that check is not written. `meta.timeOfDay.emittedAs` records it on
every variant plate.

**What it does not draw, stated rather than implied:** the relight. Every prop's cast
shadow still falls where the lamp and the monitor put it. A real change of hour moves
all of them, and that is not in this drop — so these read as the same room at a
different hour, not the same room lit from a different place. For dusk that is close
to true (the lamp is still the source); for `day` it is the honest limit.

**And the §1 dependency is real, not caution.** A toned wall behind the chapter-opener
title box is precisely the borrowed legibility §1 measures — `room/low-desk-height`,
the one plate that already has a banded wall, reads a 2.4:1 floor in the control
state. So a non-night variant declares `meta.timeOfDay.titleGroundRequired`, and
until a title ground is chosen those plates must not be used in a chapter-opener
template. Every other shot template is unaffected. That is why the brief puts §1
first, and it is why this switch is `null` rather than `"dusk"`.

### §4.3 · `room/over-the-shoulder` — the one plate with him in it

A camera position, so it is a room angle rather than a host framing — and the only
room plate in the kit with a figure drawn into it. His shoulder and the back of his
head crop the near corner; the subject is the screen he is looking at.

**It declares no host anchor, and for the opposite reason to `high-desk-down`.** That
plate has nowhere for a figure to stand; this one already has him. Compositing a
cut-out onto it would put two of him in one frame, so `hostAnchor: false` is
load-bearing rather than a gap.

**It declares no title slot either.** A chapter opener needs a flat quiet ground and
this frame is a shoulder, a lit screen and a desk — §1's own family audit is the
argument, and this plate would be the worst offender in it by a wide margin. It is a
cut-away, not an opener, and `roles.fragment.json` routes it accordingly.

**The figure is a silhouette, not a portrait.** No face, no features, no eyeline,
because we are behind him. Anything more would be a second Dennis drawn by a different
author, disagreeing with `hostFace()` about who he is — the exact defect that function
exists to prevent. It lives in `K.foreground()` as a new `"shoulder"` kind, because
that function's whole job is one object clearly in front of everything else, cut by the
frame edge: the crop *is* the depth cue, and that is as true of a shoulder as of a mug.
It is the one foreground kind that gets the heaviest line **and** the heaviest tone —
the near-object rule says line only, the host rule says he outranks everything, and
here they point the same way.

**And it publishes a `screen` region** — the only room plate that does. Fill it with
what he is reading: a chart plate, a filing page, a terminal, at low value. A screen in
a dark room, not a lightbox; it must not out-contrast him in the corner.

### UNVERIFIED — §3 and §4 *(historical — drop eight answered three items)*

The 1:1 items for the filing reader, the time-of-day plates and the over-the-shoulder silhouette are all answered — §11, §12, §13 and §14. One of them found the empty chair's scaling contract, which drop nine fixed. What is below survived.

2. **`new-plates.html` has no §3 or §4 section.** Still true of *that* page. The gap it
   describes — §3's two text authors never filled with real words — is closed by drop
   eight's §13, which fills all six at 1:1 with the worst realistic copy and one
   deliberate over-budget refusal. The §0.3 page itself has not gained a section.
3. **The §3 and §4 checks ARE wired now.** `preflight.html` gained checks K, L and M
   this drop: K asserts language-shift's congruence, shared roles, shared budgets,
   two-line capacity and frame fit plus headline-stack's strip congruence, four-item
   fit and the date/source pair; L measures the seated ratio against a standing pose
   built in the same run, asserts the empty chair does *not* carry it, counts the
   plates the time-of-day tone actually lands on, and **fails if `TIME_OF_DAY` is
   flipped before §1 is answered** — the dependency enforced rather than documented.
   M is the new one below.


6. **The hatch2 trap now has a guard — check M, "marks asked for and never drawn."**
   It wraps `hatch()` across a full library build and reports every call that
   returned an empty string. Measured: **7,102 hatch calls, 266 of them empty, across
   55 plates** — all pre-existing, all host-family face detail at small scale, where a
   region under four units square legitimately draws nothing. So M reports rather than
   fails, and the signature to act on is a *new* entry. It would have caught §4.2's
   defect in the build instead of in a byte count.


## Drop four — §2, the quarter

Ten assets, three authors, both aspects each. The pipeline reads a `Quarters` sheet
carrying six to eight quarters and the kit was entirely annual, so the data path existed
and the video had nowhere to put it. `proof/new-plates.html` has every one of them filled
twice from unrelated numbers at different counts; `proof/preflight.html` check **J** is
new and asserts the four properties that would otherwise fail silently.

**208 → 218 assets, 726 → 760 frames, 0 errors.** Every pre-existing frame in `charts/`
and `figures/` is byte-identical to delta-14 — hashed both ways, 218 frames, 0 changed,
so §2 adds and changes nothing.

### 2.1 · `charts/bars-8q` and `charts/line-8q`

Eight columns and a five-character period label. **Types on `chartFrame`, not a new
author**, because the margins, the gridlines, the pinned axes and the tick convention are
exactly what has to be identical for a quarterly chart to cut against an annual one
without the grid shifting — sharing the author makes that true by construction rather
than by care. The column count became a variable; nothing else moved.

**The real layout difference turned out to be the value row, not the labels.** The brief
expected label width and column pitch to fight, and measured, they do not: `Q3'25` is
five characters where `2025` is four, and even at eight columns the head box holds 15 in
16:9 and 8 in 9:16. What does not survive is the per-column figure row. At eight columns
in 9:16 a value box is 105 units and the role is 30-unit Courier at 0.5996em — **five
characters**, so `$1.2B` fits and `$12.4B` does not, and an over-budget fill does not
render at all. A row of figures that silently stops the shot is worse than no row.

So the portrait plates publish **one `value-last` callout** instead of a row of eight, and
check J asserts a plate has a value row *or* a callout — never neither, never both. The
decision is `budget.js`'s, not mine: the plate asks whether six characters fit and
publishes what does.

**The trap these plates set, and the reason §2.2 exists.** Eight quarters is two years, so
Q4 appears twice and so does Q1. Read left to right, the render in `new-plates.html` looks
like a company that grew 57% last quarter; it is a company whose Q4 is always its best and
whose Q4 grew 4%. The plate carries that in `meta.seasonalityWarning` rather than drawing
an argument about it — the comparison belongs to the next plate.

### 2.2 · `figures/qoq-yoy` — the seasonality plate

An editorial instrument, and the most valuable thing in this drop.

Both readings of one quarter, at once, labelled, as a pair: against the previous quarter
(is it moving?) and against the same quarter a year ago (is it *actually* moving, or is
this just what Q4 always looks like?). Slots are exactly the eight the brief names —
kicker, unit, figure, the two deltas, a label each, caption.

**It cannot resolve them into one figure.** There is no slot a blended growth number could
go in, and check J asserts the slot set rather than trusting the comment — the same
structural refusal as no author being able to emit a text node. A rule nothing can
accidentally break beats a rule everyone agrees with.

**Equal weight is geometry.** The two cells come out of one expression with only an offset
differing, both deltas are set in one type role, both labels in one role, and both deltas
carry one derived budget. Check J asserts congruence, shared roles and equal budgets on
all four plates. If one read as the headline and the other as a footnote, the plate would
have taken a side the data has not.

**The arrangement differs by aspect, and that is the one real decision here.** 16:9 sets
the cells side by side. 9:16 **stacks** them: two 470-unit cells side by side in portrait
would force the delta type down two steps, and deltas that small lose the pair its weight
against the figure above — the same failure from the other direction. Stacked congruent
cells keep both. Reading order is the nearer comparison first, which is as arbitrary as
left-before-right and no more so.

Sign-agnostic, for `waterfall`'s reason: no colour, no arrow, no order preference, and the
two cells are identical, so a fall and a rise are drawn the same.

One thing for the renderer, in `roles.fragment.json`: **fill both deltas or neither.** A composite
that fills `qoq` and leaves `yoy` empty is the single-figure resolution arriving by
omission, and the shot audit should error rather than render half a pair.

### 2.3 · `charts/seasonality-{4,6}y`

Q1 to Q4 across, one series per year, oldest left. Count variants on **years**; the
quarters are always four.

**Its own author, not a `chartFrame` type**, because the horizontal is no longer a period
axis — it is four positions every series shares, and the series are the years. That
inverts what a column means, and `bar-3` would be ambiguous between "Q3" and "the third
year". An ambiguous slot name on a data plate is how a renderer fills the right number
into the wrong column.

**One hue, value ramped** — oldest lightest, newest at full subject ink — rather than four
or six series colours. Six hues on one plot is a different channel, and this kit's
doctrine is light as value falloff rather than as new colour. It also does the editorial
work for free: the year the script is about is the darkest thing on the plot.

`meta.groups` publishes every column's x, width and anchor already measured, so a renderer
draws grouped bars *or* a line per year without re-deriving the grid. Check J compares
`meta.groups` against the slots column by column — 24 columns on the 6y plate, and a
one-unit disagreement would put every bar a unit out with nothing reporting it.

**Measured and said out loud:** 6 years × 4 quarters in 9:16 is a **23-unit column, 46px
delivered** — the thinnest data mark in the library. It renders and it reads at desk
distance. The plate publishes the number as `meta.columnWidth` and the judgement as
`meta.crowded`, `roles.fragment.json` routes shorts to `-4y` (35 units), and I have not
claimed it works on a phone. **Drop eight looked at it: marginal** — the columns and the
group structure read, the ramp's bottom end does not order at phone distance. The routing
stands.

### Where they go

All ten reach a chapter type in `roles.fragment.json`, so none is reported unreachable.
~~New chapter types the wiring assumes: `the-latest-quarter`, `momentum`,
`short-the-quarter`~~ — **none of those three existed.** Drop eight mapped them: the first
two are `the-numbers`, and `short-the-quarter` was a SHORT beat wearing a chapter type's
clothing (`numbers` / `the-sheet`). `seasonality-6y-16x9` is deliberately not given to a
shot that shares the frame with the host — 24 columns will not survive it, the same call
`waterfall-5s` already makes.

### UNVERIFIED — §2 *(historical — drop eight answered both 1:1 items)*

Both are gone: §10 rendered all ten quarter assets and judged the 23-unit column. One of them found `qoq-yoy-9x16` rendering blank, which drop nine fixed. What is below survived.


3. **`qoq-yoy`'s two-line labels are budgeted, not typeset.** The label boxes measure 50+
   characters a line, which is generous — but `new-plates.html` sets them with a literal
   newline, and the real compositor breaks by measured width. A label that breaks
   differently in the two cells would cost the pair its symmetry, and I cannot test the
   compositor's breaker from here.
4. **The seasonality ramp is a renderer instruction, not a drawn thing.** `new-plates.html`
   implements it (0.26 → 0.82 opacity) to show the intent; nothing in the kit enforces it,
   and a compositor that ignores it gets six identical grey bars per band.
5. **Nothing about §2 has been seen in motion.** All ten plates are gated and breathe
   (0.27%–1.85% of ink), and their axes and quarter-band ticks are pinned — asserted, not
   watched.

## Drop three — §1, the title's own ground. DECIDED: `card`

**`engine/build.js TITLE_GROUND = "card"`.** All 22 chapter-opener plates now carry a
drawn ground behind the title: an opaque taped card with its own bloom rim and its own
cast. Verified across the family: the published title slot does not move on any plate,
the type colour stays `structure`, and the ground emits the identical path at boil 1
and boil 2. The six room plates with no title slot — `over-the-shoulder` ×2,
`wall-of-calls` ×4 — take no ground, and that falls out of what each plate published
rather than out of a list.

**What this changes for you, concretely.** Contrast inside the title box becomes
wall-independent: 11.9:1 on every wall, spread 0.0, against a control that ran from
1.0:1 on `whiteboard-wall` to 9.9:1 on `desk-corner`. The share of the box failing
4.5:1 goes to 0.00% everywhere, including the 16 plates that were already failing. The
renderer needs **no change** — `slots.title.colour` is still `structure`, which is the
reason `card` won over `slab`.

**What it costs, as promised.** A prop now appears in the room that was not there
before, and where the box sits over something it covers work somebody drew: the
printer-corner window, two of `low-desk-height`'s wall bands, three post-its on
`desk-corner`, one of `high-desk-down`'s sheets. `audit/baseline-14.json` is
regenerated and every earlier room hash is void.

**And it unlocks §4.2.** The time-of-day variants were held back because a toned wall
behind the title was precisely this defect; that blocker is gone. `TIME_OF_DAY` is
still `null`, now for one reason only: nobody has looked at a dusk plate yet. Check L
enforces the pair — a time-of-day variant with `TITLE_GROUND` null fails.

The original decision material, unchanged, follows.

### The three treatments as they were put to you

§1 asked for three treatments rather than one, so this drop is **the decision, built**:
the engine can give a chapter title its own ground in three ways, all three render on
the worst wall and the clean one, and the contrast floor inside the title box is
measured for each. **It ships OFF** — `engine/build.js` `TITLE_GROUND = null` — so the
library is byte-identical to delta-14 and `audit/baseline-14.json` still holds. Turning
it on is one line and resets `room/` only: 22 assets, 66 frames, nothing else in the
library.

`proof/title-ground.html`. Ten checks now pass in `proof/preflight.html`; **I** is new.

### The finding, which is worse than the risk we recorded

Last pack recorded this as a standing risk: *any* room art behind the title box would
cost the chapter opener its legibility. Measured, the rule is not being obeyed at all.

**16 of the 22 chapter-opener plates already have drawn ink under the title box,** in
the shipped library, with no new room art. Control state, no ground, share of the box
that falls under 4.5:1 against the title's own ink:

| plate | fail% of the title box | marks in the box | what is behind it |
| --- | --- | --- | --- |
| `room/whiteboard-wall-9x16` | 35.02% | 655 | the desk, a monitor, a stack |
| `room/whiteboard-wall-16x9` | 28.27% | 714 | the desk edge, the under-desk shadow, a leg, a plant |
| `room/doorway-9x16` | 21.87% | 321 | the plant and the coat |
| `room/doorway-16x9` | 14.00% | 321 | the plant |
| `room/corner-perspective-9x16` | 9.72% | 621 | the receding wall and the clock |
| `room/corner-perspective-16x9` | 7.49% | 206 | the clock, the plant |
| `room/desk-front-16x9` | 3.87% | 359 | the night window |
| `room/wide-16x9` | 3.61% | 403 | the night window |
| `room/printer-corner-16x9` | 3.55% | 573 | the night window's fifteen blind slats |
| `room/low-desk-height-9x16` | 3.07% | 236 | the toned wall bands |
| … six more between 1.0% and 2.6% | | | |

Six plates are genuinely clean, and **five of those six are portrait** — the 9:16 boxes
are the only place in the family where the ground under a title is actually flat.

The full table is regenerated at the foot of `proof/title-ground.html`, and it is the
audit the last pack recorded without taking.

**Where the undocumented rule actually lives.** One comment, in `roomKit`'s cast pass:
cast shadows are suppressed for any mass whose base sits above 36% of frame height, "so
the title box stays on flat wall and the chapter openers keep a clean ground for type."
That is the only statement of the rule anywhere in the engine, it is a side condition on
a shadow, and it governs shadows alone — props, tone and toned walls walk straight past
it, which is exactly what the sixteen plates above are.

### The three treatments

All three are one call in `room()` after every branch has drawn, so no angle carries a
placement of its own and a new angle gets the ground for free.

- **`card`** — an opaque drawn card, taped at two corners, with its own bloom rim and
  its own cast. Paper on the wall.
- **`scrim`** — no object and no edge. Three feathered washes of the ground colour,
  frayed at the rim; the middle transmits 21.6% of what is behind it.
- **`slab`** — an ink block at 0.96 with the title **reversed out**. `typeColour`
  becomes `ground`, published rather than inferred.

**Three properties every treatment holds, asserted by check I rather than by care:**

1. **The published title slot does not move.** The panel is drawn *around* the box, so
   nothing already composited against `slots.title` shifts by a pixel.
2. **It is pinned.** A ground is a slot underlay, and an underlay breathing behind
   dead-still type is the relative motion §1.5 ruled out — the same call `field()`
   makes on a data plate. Rooms are not gated, so without `pin()` this panel would
   have been the one thing on the plate breathing at title size.
3. **It covers the whole type block.** `desk-corner`, `corner-perspective` and
   `high-desk-down` set a caption directly under the title; a panel that leaves the
   smaller type on bare wall has protected the wrong element. The panel spans the union
   where the caption sits within one title-height of the title.

### Measured — the contrast floor inside the title box

`proof/title-ground.html`, rasterised at 1:1, measured inside the published box.
`floor` is the 1st-percentile luminance as a ratio against the title's own ink (not the
darkest pixel — one anti-aliased pixel off one drawn line is not what type is read
against). `fail%` is the share of the box under 4.5:1. `range` is p99−p1 of luminance
×100: how far the ground moves under the letters.

| wall | ground | floor | mid | fail% | range |
| --- | --- | --- | --- | --- | --- |
| `whiteboard-wall-16x9` — worst | control | 1.0:1 | 7.9:1 | 28.27% | 70.9 |
| | card | 11.9:1 | 11.9:1 | 0.00% | 0.0 |
| | scrim | 6.8:1 | 10.6:1 | 0.00% | 32.2 |
| | slab | 10.7:1 | 11.0:1 | 0.00% | 0.7 |
| `printer-corner-16x9` — patterned | control | 1.2:1 | 11.9:1 | 3.55% | 69.8 |
| | card | 11.9:1 | 11.9:1 | 0.00% | 0.0 |
| | scrim | 7.1:1 | 11.8:1 | 0.00% | 30.6 |
| | slab | 10.7:1 | 10.7:1 | 0.00% | 0.6 |
| `low-desk-height-16x9` — toned | control | 2.4:1 | 11.9:1 | 1.42% | 62.2 |
| | card | 11.9:1 | 11.9:1 | 0.00% | 0.0 |
| | scrim | 8.1:1 | 11.8:1 | 0.00% | 23.8 |
| | slab | 10.7:1 | 10.7:1 | 0.00% | 0.5 |
| `desk-corner-16x9` — **clean** | control | 9.9:1 | 11.9:1 | 0.14% | 13.0 |
| | card | 11.9:1 | 11.9:1 | 0.00% | 0.0 |
| | scrim | 11.2:1 | 11.8:1 | 0.00% | 3.4 |
| | slab | 10.7:1 | 10.7:1 | 0.00% | 0.1 |
| `whiteboard-wall-9x16` — worst portrait | control | 1.1:1 | 9.1:1 | 35.02% | 70.6 |
| | card | 11.9:1 | 11.9:1 | 0.00% | 0.0 |
| | scrim | 7.0:1 | 11.0:1 | 0.00% | 31.3 |
| | slab | 10.7:1 | 10.9:1 | 0.00% | 0.7 |

**The spread across the five walls is the whole claim:** control 8.8, card 0.0,
scrim 4.4, slab 0.0. A ground that carries its own contrast reads the same number on
every wall. One that borrows reads a different number on each.

**Two things worth reading off this table rather than past it.**

The **mid** column barely moves between the control and the card — 7.9 to 11.9 on the
worst plate. The mean is the statistic that cannot see this problem, which is most of
why it survived to become a standing risk. `fail%` and `range` are where it shows.

The **scrim passes the floor everywhere and still fails the argument**: 0.00% of the box
is under 4.5:1, and the ground under the letters is still moving 23–32 L, because a
fifth of the wall reaches through. It is the only treatment that does not cover the room
art it sits on, and that is the same property as its not being able to guarantee
anything.

### The price — what changes for every existing chapter opener

**All three.** 22 room plates gain a drawn panel behind the title; the chapter opener
stops being "a title on a wall" and becomes "a title on something", and that is in the
plate, not per-episode. `slots.title` keeps its box everywhere. Two new manifest fields
(`meta.titleGround`, and `ground`/`groundBox`/`colour` on the slot). The baseline resets
for `room/` only — 22 assets, 66 frames.

**`card`.** A prop appears in the room that was not there before, and on the plates
where the box is over something it covers work somebody drew: the printer-corner
window, two of `low-desk-height`'s wall bands, three post-its on `desk-corner`, one of
`high-desk-down`'s sheets. On the clean walls it reads as a taped card and costs nothing
(0.14% → 0.00%, and the floor goes up). Because the card is drawn in `ground` — the same
colour as the wall — on a pale wall it reads by its edge, its rim and its cast rather
than by its value. Drawing it in `ground2` instead is a one-word change and would make
it read as an object; I have not measured that, and it would cost about 3 points of
floor.

**`scrim`.** Nothing appears; a region of wall goes quiet. Keeps the plate a room and
covers nothing. Cannot guarantee the floor, and leaves the ground moving under the
letters — see above.

**`slab`.** The largest change, and the only one that is not reversible in the
renderer: the title reverses to the ground colour, so every new chapter opener looks
different from every one in the back catalogue, and the chapter-opener shot template has
to read `slots.title.colour` instead of assuming `structure`. In exchange it is the most
robust on any ground, including a photograph, which no other treatment here can claim.
Against it: `room/` doctrine is that Dennis is the highest-contrast object in any frame
he is in, and a slab puts the darkest mass in the frame next to him.

**What it unlocks.** The 36% restraint exists to protect this box. Once the title
carries its own ground that line can be lifted, and §4's time-of-day variants stop
being blocked on it — which is why §1 comes first. **Lifting it is not in this drop.**

### My read, and it is a recommendation rather than a choice made

**`card`.** It is the only treatment that gets wall-independence (spread 0.0) *without*
moving the type colour, so the back catalogue and the renderer's chapter-opener template
both stay as they are; it is drawn in the family's own vocabulary — paper, tape, a cast
— rather than in a new one; and on the clean walls, which are five of the six plates a
short ever cuts to, it costs nothing.

`slab` is the better answer to a question we have not been asked yet: a title over
photography. If the channel is heading there, take `slab` now rather than twice.

`scrim` I would not take. It improves every number and guarantees none of them, and
"the wall is quieter behind the title" is the kind of fix that reads as solved until one
angle puts something dark in that box.

### Regenerated, and kept this time

`audit/baseline-14.json` and `audit/breathe-map.json` are both in the pack, generated
from the engine in this pack: **228 assets, 798 frames, 0 errors.** 108 gated plates,
ink breathing 0.0%–67.6%, the pin mechanism asserting true/true, and no plate frozen
without being on the still-by-design list. Deterministic, so prefer the copy you
generate from the engine you are holding — but the pair is here rather than absent,
because this work is what the next change gets checked against.

**And the "byte-identical" claim is measured, not asserted.** Every room frame was
hashed twice — once against the delta-14 engine as it arrived, once against this one
with `TITLE_GROUND` null: **78 of 78 frames identical, 0 differing.** The `room/`
rollup in §1.1 below therefore still stands as written.

### UNVERIFIED — §1

1. **The contrast numbers come from the browser's rasteriser, not resvg.** Colour
   composition is the one thing the two should agree on exactly, and every measured
   plate has no gradient, no blur and no text in it — but I cannot run resvg here and
   I am not going to claim the two agree.
2. **The family audit is measured at frame one only.** Other boil indices re-wobble the
   same marks in the same places, so `fail%` will move by a fraction of a point rather
   than by a category. Not checked.
3. **Nothing has been seen in motion.** The ground is pinned, so it cannot crawl — that
   is asserted. Whether a card *arriving* on a cut at 2fps reads as a card or as a flash
   is a question for `two-against-three.html`, and I have not put it there.
4. **No type has been set in any of these boxes.** This page measures the ground, not a
   title. A real title at real weight could still break on a line count or a long word
   — that is the compositor's own audit, and the budgets are unchanged by this drop.
5. **The 4 GB rasterise ceiling** is unchanged and still unverified; the per-family
   batch path remains the documented route.

### What I need back

Which treatment — or that none of them is right, which is also an answer this page can
support. §2 is built and does not depend on it; §4 does, and I will not start the rooms
until it is closed.

## Scope, as it now stands

Two drops, both **built and passing**: 208 assets, 726 frames, 0 errors, nine
checks green.

- **Drop one** — §1.1 three-frame boil, §1.2 blink, §1.3 props, §1.5 breathing,
  §2.1 waterfall, §2.2 what-has-to-be-true. ✓
- **Drop two** — §1.4 settle with `meta.loopStart`, §2.3 through §2.14. ✓
- **§5 captions** — a conversation, and it stays one. `proof/captions.html`.

### Removed from scope, not deferred

**§3.1 time of day** and **§4.1 / §4.2 / §4.3** are out. Nothing in the engine
references them and nothing in `roles.fragment.json` reserves a key for them.

### The thing §3.1 turned up, which outlives it

**The chapter openers are one room-art change away from breaking, and not only by
a dusk variant.**

The `title` slot is legible today because the wall behind it is flat and pale.
That is not a property of the title — it is a property of the wall, borrowed. Any
change to room art that puts tone, a prop or a shadow behind that box costs the
chapter opener its legibility, silently, on the one plate where a chapter title
reaches the screen at all.

The fix is for the **title to carry its own ground** rather than borrow the
wall's. That is a real change with a real cost — a drawn panel behind a title box
changes what every chapter opener looks like — and it cannot be chosen from a
description. It needs a render in front of both of us.

Recorded here as a standing risk rather than a backlog item, because until it is
answered, "do not put anything behind the title box" is an undocumented rule that
the room family is currently obeying by accident.

### Already in the pack, from the §3 work before it was cut

Two plates were built before §3 was closed. They are green, they cost nothing to
keep, and neither depends on anything that was removed — but if scope is now
strictly the two drops, say so and they come out cleanly:

- `structure/whiteboard-{3,4}-{16x9,9x16}` — §3.2, the diagram as content.
- `room/wall-of-calls-pinned-{16x9,9x16}` — §3.3, the just-pinned card.

The second one is load-bearing for §1.3 as it currently stands: the plain
`wall-of-calls` has no prop that moves, and the pinned variant is where that room
gets its one moving thing. Removing it puts that room back to a declared
exemption rather than a prop — which is defensible, since it is a data plate cut
to over his voice rather than a set he stands in, but it is a change and worth
knowing about before it happens.

---

## §3 — what was built before the section was cut

**208 assets, 726 frames, 0 errors, all nine checks passing.**

What landed, and what did not, stated plainly at the top because the gap matters
more than the additions.

### §3.2 — the whiteboard as a plate ✓

`structure/whiteboard-{3,4}-{16x9,9x16}`. `room/whiteboard-wall` is a room he
stands in; this is a board where **the diagram is the content**, drawn by the same
hand as everything else.

Kept genuinely generic per the brief: three or four labelled boxes and their
links, every word a slot, no pre-drawn diagram of one idea. The boxes and arrows
are drawn because a diagram's shape is structural — which thing connects to which
is the argument's skeleton and is true before any label arrives.

**The links are a fixed spine,** 1→2→3(→4), and that is a real limitation stated
rather than hidden. Arbitrary edges need an edge-routing renderer, which is a
different and much larger problem — the same call as §2.14 being a bar rather
than a map. A script needing a shape this cannot draw needs a new plate, not an
argument to this one.

9:16 stacks down the frame. Four boxes in a row has no portrait form.

### §3.3 — something pinned to the board ✓

`room/wall-of-calls-pinned-{16x9,9x16}`. A variant, not a new family: one more
slip laid over the others, crooked, with its own pin and its own slots. **Cutting
from the plain wall to this one IS the card arriving** — a beat, a callback and a
running gag in one asset.

The pin is `attention`, not `down`. It marks which card is new, and nothing about
a new call is a loss yet.

### §1.3 — the three propless rooms, closed ✓

Twelve of thirteen room plates now carry a moving prop; the thirteenth is a
declared exemption.

- **`high-desk-down`** was a one-line miss: a plan-view mug is drawn by
  `planMug`, a different call from the elevation `mug`, so it never registered.
  Now it does.
- **`doorway`** draws no mug and no monitor, so it gets the thing it does have:
  **the wavering edge of light from the hall.** A spill edge drifts for the same
  reason steam does — it is air and light, not a mechanism — so it stays honest at
  any frame rate, which was the whole argument for steam over a clock.
- **`wall-of-calls`** gets its prop from §3.3: the newest card is the only thing
  on a wall of settled paper that has not settled, and one lifted corner is both
  the beat and the motion. Nothing else on it moves — a wall of fluttering cards
  is a noticeboard in a gale.
- **The plain `wall-of-calls` stays still, and now says why.** §1.3 asks for one
  moving thing in each ROOM — a set he stands in, which should not read as a
  photograph. That plate declares `hostAnchor: false` and is a full-frame data
  plate cut to over his voice. Declared in `meta.ambientNote` rather than left as
  a bare null.

### §5 — the captions, as a conversation ✓

`proof/captions.html`. The one item you asked to see **two options** for before
choosing, so that is what it is — a page, not a delivery: captions live on the
renderer's caption path, not in the kit.

Both options over the same frame at real caption scale, with the two lines that
make the difference stop being aesthetic: the longest line a script writes, and a
line that is mostly numbers. Sized in canvas units, so the comparison does not
change with the width of your preview.

**My read is option A — drawn container, clean type** — and the reason is not
taste. The caption is the only element in the frame whose job is to be *read*
rather than looked at; every other element earns its hand by being looked at.
Hand-lettering spends legibility, which is the one currency this element cannot
spend, for a texture nobody consciously notices after ten seconds. Numerals are
the worst case: 3/8, 5/6 and 1/7 are pairs a viewer must not confuse on a channel
about figures.

What would change my mind is on the page: if you want the captions to be *funny*
rather than transparent, hand-lettering is a joke you can keep telling for forty
minutes — and that is an editorial call about the channel's voice, not mine to
make.

### §3.1 and §4 — REMOVED FROM SCOPE

Both were proposed here as gaps and are now cut, per your call. Kept in this
section only so the reasoning survives:

- **§3.1 time of day** — blocked on the title-legibility constraint, which turned
  out to be a bigger finding than the feature. See the scope section at the top.
- **§4.1 sitting, §4.2 over the shoulder, §4.3 the empty chair** — figure work:
  a new pose skeleton, a framing that turns him from the lens, a set variant. A
  badly-drawn sitting pose is worse than an absent one because it will get used.

---

## Drop two — complete

**202 assets, 708 frames, 0 errors, all nine checks passing.** Every §2 plate
built, filled with real words and overflow-checked; §1.4 landed.

Everything in §2 is now built, plus §1.4, which was deferred out of drop one and
belonged here.

| § | plate | counts |
| --- | --- | --- |
| 2.3 | `charts/dilution-6y` | six periods |
| 2.4 | `charts/guided-vs-actual-6y` | six periods |
| 2.5 | `peers/distribution` | seven buckets, fixed |
| 2.6 | `figures/share-of-{2,3,4}` | 2–4 |
| 2.7 | `figures/scale-{2,3}` | 2–3 refs |
| 2.8 | `paper/receipt-{4,6,8}` | 4–8 lines |
| 2.9 | `structure/said-happened-{3,4,5}` | 3–5 events |
| 2.10 | `structure/sensitivity` | 3×3, fixed |
| 2.11 | `charts/maturities` | six periods |
| 2.12 | `figures/ownership` | three, fixed |
| 2.13 | `charts/multiples-grid-{4,6}` | 4 or 6 tiles |
| 2.14 | `figures/by-region-{3,4,5}` | 3–5 |

Both aspects throughout. 9:16 is a re-author, never a crop.

### §1.4 — the settle

One strip, `meta.loopStart`, exactly as you specified. Two frames at the head
where the plate lands slightly past its position and comes back; frames 0–1 play
once on arrival, 2–4 loop forever.

Published as the index the picker consumes rather than a `settleFrames` count it
has to derive — a derived index is the class of thing that has bitten this project
twice. Frame tags stay continuous `_f01.._f05`: a settle frame is not a different
kind of file and is not named as though it were, so §7's naming contract holds.

Cards, figures and paper. **Not rooms** — a room that settles reads as a camera
bump, and the camera is the one thing in this kit that never moves.

It keeps the hand because each settle frame carries its own boil index, so the
linework re-wobbles as it lands. An easing transform on one static frame cannot
do that, which is the whole reason §1.4 asked for frames.

### Three authors, not twelve

§2.6, §2.12 and §2.14 are one author. All three are a single bar that divides;
what differs is the count and what the segments mean, which lives in the key and
the manifest. Same call as the six-period charts, and the same argument:
**a shared drawing with different meaning is a family; a different drawing
promised and not delivered is a bug.**

The segments are ONE region, not n regions. A part-of-a-whole divides a fixed
length — if each segment were its own box, a renderer could produce a set that
does not sum to the bar, which is the one thing this plate must never show.

§2.14 is a labelled bar and not a map, per the brief. The argument is the
proportion; a map would give a large empty country the same weight as its revenue.

### The rules each plate carries, published in its manifest

- **`maturities`: a zero column is data.** A year with nothing due is the good
  news and the shape of the wall depends on the gap. Do not drop the column.
- **`multiples-grid`: per-tile scales** — and it is the exact opposite of
  **`scale`: one shared scale**. There the argument is relative size; here it is
  relative shape, which one is moving. Both notes are published so the renderer
  can tell them apart, because the natural instinct on both is wrong once.
- **`sensitivity`: `mark-row` / `mark-col` are two integers,** not a marked-cell
  slot. The mark is a claim the script is making and it moves with the
  voice-over; a plate per cell would be nine plates.
- **`receipt`: `highlight-index` is a weight change, never a colour.** The receipt
  has no direction in it.
- **`said-happened`: the said rail is lighter with hollow marks,** the happened
  rail heavier with filled ones. A claim and an outcome are not the same kind of
  fact. `diverge-N` is set only where the two contradict — the mark means
  something because it is rare.

### §1.5 found its boundary

The still-by-design list went from two plates to thirty. That is not a gap in the
work: most of drop two is **argument geometry** — an extent, a rail, a baseline —
and on a plate whose every drawn mark is a measurement reference, §1.5 has nothing
to move. Each one is listed with its own reason in `audit/breathe-map.json`; a
plate that is frozen and not on the list still fails check E.

One plate changed sides while I was writing it. `multiples-grid`'s tile baselines
looked like chart axes and I pinned them — then the plate's own manifest note says
each tile is read as a **shape**, not a quantity. Nobody reads a value off them,
so they breathe. Pinning them would have contradicted the line below.

### ⚠ The baseline is generated, not shipped

`audit/baseline-14.json` was checked in and went stale the moment drop two landed:
472 frames became 708, and §1.4's settle renumbers frames on cards, figures and
paper. A stale baseline someone trusts is worse than an absent one — it reports a
diff on every plate that moved for a good reason, which teaches people to ignore
it. So it is deleted, and `audit/README.md` says how to produce the current pair:
two buttons in `preflight.html`. Deterministic, so your copy beats mine.

### §0.3 — done, and it earned its keep again

`proof/new-plates.html` now fills all twelve new families with real words, at
their densest counts. **Text only, deliberately:** this check exists to catch a
plate that is fine until real words go in it, and both defects it caught in drop
one were exactly that. The region fills are the renderer's and are covered by the
geometry assertions; what cannot be checked without words is whether a box holds
its longest plausible string.

Every value in it is chosen to be awkward rather than tidy — the longest label a
script would really write, a five-digit figure where three would fit, a zero year
in the middle of the debt wall, a subject sitting outside the peer spread.

The pass measures every filled box against its content. **Sixteen plates, one
defect, now fixed:**

> `paper/receipt-8`'s kicker had been given the ROLL's width — ~497 canvas units —
> and a kicker at 28px Courier needs roughly 670 to hold the length its own role
> declares. A normal-length kicker wrapped to two lines in a one-line box.
> Invisible with short sample words, which is the whole point.
>
> The roll is narrow because a till roll that fills the frame is a poster. The
> kicker has no such constraint: it labels the plate, there is empty ground either
> side of the roll, and it now takes the full text column.

After the fix: **zero overflows across all sixteen.**

### Not yet done for drop two

Nothing. The render-scale pass is `render-scale.html?s=7`; the §0.3 pass is in
`new-plates.html`.

I have looked at part of `?s=7` rather than all twenty-four tiles — but the
overflow pass above now covers the failure mode a visual scan is worst at
spotting anyway.

---

## Drop two, first slice — §2.3, §2.4, §2.11

The three six-period charts, landed together because they are one group.

- `charts/dilution-6y-{16x9,9x16}` — shares outstanding, rising.
- `charts/maturities-{16x9,9x16}` — the debt wall.
- `charts/guided-vs-actual-6y-{16x9,9x16}` — the forecast against what happened.

**164 assets, 490 frames, 0 errors, all nine checks passing.**

### They are types on `chartFrame`, not three new authors

All three are "six periods on one plot", which is what that author already is. A
new author per chart would duplicate the margins, the gridlines, the axis pinning
and the tick convention — and §0.2 requires that any of these can sit in the same
cut as `line-6y` or `bars-6y` **without the years changing width mid-video**.
Sharing the author makes that true by construction rather than by care.

What differs per type is the slot set and what the plate says about itself, which
is the part that belongs to the argument.

### One thing to be straight about

`dilution-6y` and `maturities` draw the **same artwork** as `bars-6y` — six bars,
six ticks, six heads. Check H2 passes them as distinct only because their seeds
differ, which is a weaker pass than it looks, and I would rather say so than let
the green tick imply more than it does.

I think they are nonetheless right as separate keys, and the distinction from the
`compare-side` defect is worth stating precisely: **`compare-side-9x16` promised a
different layout and drew a stack.** These promise six bars and draw six bars.
What makes them different assets is what the manifest claims — `maturities`
carries the zero-column rule, `dilution` carries the count-not-percentage rule and
the no-`down` rule — and a script selects by key. A shared drawing with different
meaning is a family; a different drawing promised and not delivered is a bug.

If you would rather they were one key with a `meaning` argument, that is a
reasonable read and a small change. Worth deciding before §2.13 small-multiples
lands, since that one embeds these.

### The rules each carries

- **`maturities`: a zero column is data.** A year with nothing due is the good
  news in that picture and the shape of the wall depends on the gap being
  visible. A renderer that drops a zero bar removes the argument. Published as
  `meta.zeroNote`.
- **`dilution`: a count, not a percentage,** and never drawn in `down`. A rising
  share count is a rise; colouring it as a loss delivers the verdict before the
  voice-over does.
- **`guided-vs-actual`: one plot-area, one scale, published once.** Two series on
  two scales is not a comparison. Same reason the implied plate publishes its
  axis. `guided` is `otherParty` — it is someone else's claim about the future —
  and `actual` is `subject`; neither is up or down, because a miss is not a fall.

### Still to come in drop two

§2.5 distribution, §2.6 part-of-a-whole, §2.7 scale, §2.8 the receipt, §2.9
two-track timeline, §2.10 sensitivity, §2.12 ownership, §2.13 small multiples,
§2.14 geographic exposure. Plus §1.4, the settle, which was deferred out of drop
one and belongs here.

---

# Drop one

> **Drop one is §1 entire, plus §2.1 and §2.2.** Motion first, because it touches
> everything and the baseline reset wants settling before new plates land on top
> of it. §1.4 (the settle) is deliberately **not** here — see §SETTLE.

Eight checks, all passing, run against the engine files in this pack:
`proof/preflight.html`. Everything below that states a number was measured by it.
(Nine, after one of them found a bug and earned a permanent check of its own —
see §TWO BUGS.)

```
assets:  158   (was 143)
frames:  472   (was 239)
errors:  0
```

---

## §1.1 · Three frames

Every animated asset is `frameCount: 3`. One asset is deliberately still and it
is the same one as before: `overlays/row-band`, which composites *into* a band
slot behind figures that are held still on purpose — a boiling band under a
frozen row breaks the static rule from the other side.

The third frame is a third boil index, not a new mechanism. One more draw per
plate.

### The talk strip changed shape, and that is a fix

The shipped talk strip was `mouthOpen: true` at boil 1, then `mouthOpen: false`
at boil 2. Two talk frames that differ at the mouth **and at the boil**. §7 says
talk frames differ only at the mouth, and the renderer picks a talk frame against
the audio — so every non-mouth difference desynchronises from the voice, and no
still can ever show it. It survived two packs for exactly that reason.

All three talk frames now sit at **one boil index** and differ only in how far
the mouth is open: 0, a half-open middle, wide. Three visemes rather than two
states, which is both what a mouth does and what the rule requires. `mouthOpen`
became a number to allow it; `true` still evaluates to 1, so nothing else moved.

Pre-flight check C asserts it: every mark that varies across the three talk
frames falls inside the `mouth` slot.

**That check also moved the `mouth` slot, and this is the one place I changed a
published box.** It failed on three marks — the nasolabial fold on the outboard
cheek, which moves with the mouth because on a face it does. The fix is the box,
not the drawing: the rule exists so the renderer knows *which region varies*, and
a slot that understates the varying region is the defect. `mouth` is now the
aperture plus the fold that moves with it. Suppressing the fold instead would
have made him talk with a rigid cheek to satisfy a manifest.

### The build cost, and the 4 GB ceiling

Per your answer: attempt the streaming fix, ship the batch path as the documented
fallback, do not reduce `exportScale` or shorten the boil to fit the tooling.

**What I can tell you:** 472 frames build as SVG in one browser process with no
rasteriser, no errors, no growth in peak memory that I could observe.

**What I cannot:** whether node and resvg release between families inside one
process. That is the empirical question you raised and it needs a 4 GB machine
and the real rasteriser, neither of which I have. The per-family batch path is
**known** to work because it is how you built every baseline in this review, so
it remains the documented route until someone measures the streaming one.

Listed under §UNVERIFIED, not asserted.

---

## §1.2 · The blink

Its own overlay strip, on the `eyes` anchor the contract already provides.

**Frame count is registration, not rate.** The strip is three frames because the
*idle* strip is three: blink `_fNN` composites over idle `_fNN` at the same boil
index, or the lids meet a socket that has wobbled somewhere else. The renderer
decides *when* to cut one in — ~100ms, every 3–4s. The strip encodes no rate.
`playback` is `"overlay"`, not `"loop"`: a player that looped it would blink him
forever.

**The overlay is the idle frame with the lids down, clipped.** Same seed, same
boil, same everything — then clipped to the eye region. Inside the box the
overlay is not *similar* to what is beneath it, it is the same path. So the clip
edge has no seam to hide, and registration is identity: full canvas, full
viewBox, composited at 0,0, no offset arithmetic anywhere. That removes the class
of bug that produced the desk-height and neck-span errors.

**The clip box is measured, not authored.** It started as the eyes slot plus a
guessed pad and check D caught a mark that differed and reached past it. It now
comes from the difference itself — draw the open-eyed head, take every mark that
is not in both, clip to the union of their extents, pad. Cannot be short by
construction, and stays correct if the lid shape or head size ever change.

Not shipped on the six `hostFigure` poses: full-body 9:16 plates where the head
is a few dozen pixels across and a blink is one pixel changing.

On the old `dennis-both-hands-blink_f01..f03`: worth reading for lid shape and
timing, as you said. Its structure does not transfer — it had no three-frame boil
to stay registered against.

---

## §1.3 · One thing moving in each room

Steam, per your answer and for your reason: it is the only candidate whose
natural rate matches the boil's. Steam drifts, and drift looks correct at any
frame rate, so it rides the room's own three-frame clock without lying about its
speed. A cursor at 1 Hz on a 2fps strip reads as nervous; a second hand at 2fps
is visibly wrong.

**The exception you allowed:** `from-behind-the-monitor` is the angle whose
*subject* is the screen, so it gets the caret. On for two frames of three, which
is the slowest blink a 2fps strip can express and still be a blink.

**The prop is chosen from what the plate already drew, not authored per angle.**
Every branch that draws a mug or a monitor registers it; one call at the end
picks the largest and returns a descriptor into `meta.ambient`. Eleven angles
plus `wall-of-calls` needed one line, not eleven placements to keep in step with
furniture that moves whenever the desk-height rule does.

One per plate. Two reads as a screensaver.

---

## §1.5 · The frame breathes, the figures do not

The 47 static plates are now gated three-frame loops. `playbackOf` marks them
`boilGate: "frame-only"` so a colourist looking at a near-still table knows it is
near-still on purpose.

**The gate is opt-out, and that is a correction made during this drop.** It began
opt-in — a mark moves only inside `breathe()` — which looked like the safe
choice. Check E found **44 of the 47 still completely frozen**, because a data
plate's furniture is drawn across twenty authors and each would have needed
hand-wrapping. Opt-in defaults to frozen, which is the defect it was meant to
prevent, arriving silently.

Inverting it is also the more honest description of these plates: **almost
nothing drawn on a data plate is data.** Every figure, series and band is a slot
the compositor fills — the plate draws rules, panels, hatch and frames. So the
marks that are genuinely measurement references are few enough to name, and they
are wrapped in `pin()`:

- chart axes and their tick marks
- the waterfall's baseline
- the implied plate's axis
- `field()` slot underlays

`field()` is where the two halves of your answer meet. It is hatch, and hatch
breathes — but this hatch sits directly behind a figure held still, so it is a
*slot underlay*, and an underlay moving behind pinned type is the relative motion
you ruled out. **What a mark is for wins over what it is made of.**

Check E asserts the mechanism itself before any plate: a pinned mark emits the
identical path at boil 1 and boil 2, an unpinned one does not. A missing `pin()`
is caught by a test rather than by a viewer watching an axis crawl.

**Measured by ink, not by mark count.** The first cut counted paths and reported
`peers/peer-strip` at 73% "moving", which was an artefact — a leader is dozens of
tiny dashes and a panel is one big hatch, so counting marks weights the faintest
furniture most heavily. Ink (length × width × opacity) is what a viewer sees
moving, and it is the measure your 22.0% / 5.4% figures were taken with.

Range across the 54 gated plates: **0.0% – 62.6% of ink**. The top of that range
is the numbers sheets, at ~60%, and it is worth your eye: a sheet's drawn ink is
essentially *all* row rules, so "60% of ink moving" means "the rules breathe",
which is what you asked for — but the amplitude is unchanged at ~2 units and I
have only seen it at preview scale. Flagged below.

**Still by design, declared rather than thresholded:** `structure/implied` in
both aspects. Every drawn mark on it is the axis, and an axis is pinned; the band
and marker are regions, the statement is type. Nothing left to breathe — a
property of the design, not an omission. A plate that is frozen and *not* on that
list fails the check.

---

## §SETTLE — §1.4 is answered and not shipped

Per your answer: `meta.loopStart`, one strip, extended frames. Publish what the
consumer reads rather than a count it has to derive — the boil amplitude unit and
the neck span were both a correct intent with a wrong conversion.

Landing it in drop two, as you directed. §1.1 already changes `frameCount` on 96
plates; adding loop-start semantics in the same drop means an asset change and a
renderer change arrive together, and if the boil reads wrong there is no way to
tell which caused it.

---

## §2.1 · Waterfall — `figures/waterfall-{3,4,5}s-{16x9,9x16}`

Six assets. Count variants rather than one elastic plate, for the reason
`tables/` ships 3r through 6r: a five-step waterfall is useless to a three-cost
script, and an elastic one would re-derive its column grid at render time.

**Sign is the renderer's, not the author's.** Nothing is drawn descending, there
is no arrow, and the connector stubs are horizontal. `series.waterfall` decides
up or down per step from the value's own sign, and the geometry accommodates
either because it commits to neither. `proof/new-plates.html` shows a five-step
plate with an upward step at position three, in the same artwork as the
three-step all-subtractions one.

No direction colour. A cost is the ordinary operation of a business; colouring
five subtractions red makes the plate argue ahead of the voice-over.

`meta.columns` publishes x and width per column, already measured, so the
renderer never re-derives where a column is.

**The two-workbook check earned a fix.** At five steps in portrait a column is
~130 units wide and will not hold a five-digit figure at end weight — the first
render put `7,410` in a box that fitted `7,41`. The two end figures now take half
the plate each and align outward. Nothing about that depends on step count, which
is the property that was missing.

## §2.2 · What has to be true — `structure/implied-{16x9,9x16}`

Fixed shape: one demand, one history, one axis. The band and the marker are two
regions rather than one because they have different failure modes — a band wider
than the axis is a legitimate reading the renderer clamps, and a marker outside
the axis is the most important thing the plate can say and must never be silently
dropped.

Landscape runs the axis vertically (growth over time reads as height, and a
horizontal axis beside a left-aligned sentence fights it for the eye-line);
portrait runs it horizontally, because a vertical axis on a phone leaves the band
a few pixels wide. A re-author, not a rotation.

`meta.axis` publishes the geometry once. The band and the marker **must** share
that scale or the comparison is a lie, which is why it is published rather than
measured twice.

**The two-workbook check earned a fix here too.** The type stack was three
fractions of the height that happened not to collide on one aspect; at three
lines the statement ran into the demand figure, visibly, on the landscape plate.
It is stacked off measured block heights now, so a two-line statement and a
three-line one both work.

**Where they are allowed on screen:** `roles.fragment.json` in this pack — a proposed
fragment to merge, one entry per new key, chapter types and shot templates named.

---

## §1.1 · The new baseline

Byte-identity against any earlier baseline **cannot hold and is not asserted**.
Every family changes:

```
family        assets frames  rollup
annotations       10     30  c240174e   third boil frame
cards              6     18  1f610e7c   third boil frame
charts             6     18  969e5b7b   was static, now gated 3-frame loop
cycles             2      6  1b41a34a   was static, now gated
figures           16     48  322b84f1   was static, now gated; + 6 waterfall;
                                        compare-side-9x16 redrawn (see below)
frames             8     24  948b639a   third boil frame
host              46    138  6a4371a1   third frame; talk re-authored; + 7 blink
overlays           1      1  19d69668   UNCHANGED — should still match delta-13
paper              6     18  2676249e   third boil frame
peers              2      6  33efe01f   was static, now gated
room              24     72  6ea20b79   third frame; + one ambient prop each
shorts             3      9  53fb3976   third boil frame
structure         14     42  633ae281   was static, now gated; + 2 implied
tables            14     42  9eb1e325   was static, now gated
```

The rollup is an XOR of the per-frame hashes — a human-readable change detector,
not the baseline itself.

**The baseline is `audit/baseline-14.json`, and it is in the pack.**
`proof/preflight.html` regenerates it and `audit/breathe-map.json` from the two
buttons — it is deterministic, so prefer the file you generate from the engine
you are holding over the copy I shipped. 158 assets, 472 frames.

---

## Two bugs the baseline found on its first run

Neither was on your list. Both are the kind that no screenshot shows.

### `figures/compare-side-9x16` was the stacked plate under another name

The branch read `mode === "side" && land`, so in portrait the side-by-side fell
through to stacked — and the asset shipped as a distinct key whose three frames
were **byte-identical** to `figures/compare-stacked-9x16`. Two assets, one
drawing, and a manifest saying `type: "compare-side"` over artwork that is not.

Nothing about either plate looks wrong on its own. It took hashing every frame in
the library and noticing two signatures collide — which is precisely the thing a
per-frame baseline is for, and the argument for having asked for one.

Fixed by making portrait `side` a real re-author rather than a fall-through. The
reason it was avoided is real — two columns in 9:16 are ~430 units wide and the
landscape figure size does not fit — so the figure is now sized to the column by
the rule `bigNumber` already documents: `size = columnWidth / (maxChars × 0.6)`,
Courier's advance. A short comparing two numbers is a real beat and now has a
real plate.

**Pre-flight check H2 is new and asserts this permanently:** no two keys may share
a frame signature. Expected identity *within* a key is excluded and named —
`host/<pose>-talk _f01` is the same bytes as `host/<pose> _f01` because both are
the shut mouth at boil 1, which is why entering a talk cut from a held pose is
silent.

### An empty `<path d="">`

`rawStroke` emitted a mark with no geometry on close-up frame three, present in
one drawing and absent in the other. It renders nothing, so no screenshot would
ever have shown it, but it made two otherwise identical plates differ — the kind
of phantom that makes a byte-identity baseline untrustworthy and sends someone
hunting a drawing error that does not exist.

Empty elements are now suppressed at the emitter. **The underlying stroke still
collapses at some boil-and-bob combination and that is not fixed** — suppressing
the element stops a non-mark counting as a difference, nothing more. Open.

Also hardened: `contactC`'s pose memo saved and restored the render profile but
not the boil, so a cached rig value depended on which plate was drawn first in
the build. Same family as the role-floor accumulation. Fixed; it was not the
cause of the empty-path finding, which I chased there first.

---

## §8 · Two frames against three, in motion

`proof/two-against-three.html`. Three plates — room, host idle, card — each
boiled both ways, side by side, with a rate slider from 1 to 8 fps.

The left side of each pair is literally the first two frames of what delta-13
delivered, not a two-frame sequence invented for the demo. Every frame is in the
DOM once and the player toggles visibility: swapping `innerHTML` re-parses up to
1.4 MB of SVG per tick and stutters, and a stutter is indistinguishable from the
flicker the page exists to let you judge.

The slider is the point. Whether a two-frame loop reads as a flicker depends on
the rate, so the question is not "2 or 3" but "2 or 3 at what fps".

---

## One bug found that was not on the list

See the two above. This section is retired.

---

## §VERIFIED, AND WHAT THE PASS FOUND

`proof/render-scale.html` — everything below at 1:1 canvas units. Delivered is
2×, so what is legible there is comfortably legible delivered, and anything that
fails there fails delivered. One section at a time (`?s=1`…`?s=6`): twelve room
plates in one document hung the page hard enough that it could not be queried,
and a review artefact nobody can look at is not a review artefact. The crop is a
`viewBox`, not an overflow — otherwise the browser rasterises the whole plate to
show a corner of it.

**Passing.**

- **Gated plates at render scale.** Checked at both ends of the ink range: the
  numbers sheets (~60%) and `charts/bars-6y` (axis pinned, gridlines breathing).
  The gridline case is exactly right — a faint line moving ~2 units beside an
  axis that is dead reads as a breath, not a crawl. The numbers sheets are
  heavier, because a sheet's rules are structural and drawn at weight; they read
  as a sheet that is alive rather than as movement. Accepted — and if you
  disagree, those rules are one `pin()` away from still.
- **`figures/waterfall-5s-9x16` at phone scale.** Seven columns 99 units wide
  with 35-unit gutters, no overlap, labels legible at 1:1. Dense but honest.
- **`figures/compare-side-9x16`, the redraw.** Reads as a different argument from
  the stacked plate rather than the same one.
- **`corner-perspective` and `wall-of-calls`,** carried forward from delta-13.
- **The blink on its real schedule.** `?s=5` runs the idle strip at 4fps with the
  overlay cut in for 110ms every 3–4s. Registration is right and nothing but the
  eyes moves when it fires. Whether that cadence is the right cadence is still
  your call, not something a page can settle.

**Two findings, both in §1.3, both open.**

1. **Three angles carry no ambient prop at all:** `doorway`, `high-desk-down`,
   `wall-of-calls`. They register neither a mug nor a monitor, so `ambient()` has
   nothing to choose and returns null. "One thing moving in each room" is met on
   **nine of twelve**, not twelve. `wall-of-calls` was worse than the other two —
   it never called `ambient()` at all, so its manifest did not even say the field
   was empty. Fixed: an absent field and a null field are different claims, and
   only the second is checkable. What those three should actually move is a
   drawing decision I have not made — `wall-of-calls` obviously wants §3.3's
   just-pinned card, and the other two want something already in their frame.
2. **The cursor exception has no home.** I gave the caret to
   `from-behind-the-monitor` on the reasoning that it is the angle whose subject
   is the screen — and that angle registers a *mug*, because from behind the
   monitor the monitor is the **camera** and is never drawn. The exception is
   currently dead code falling through to steam. The shot that genuinely wants a
   blinking caret is §4.2, the over-the-shoulder host plate, which does not exist
   yet. Left in place and named rather than quietly deleted: it becomes correct
   the moment §4.2 lands.

## §UNVERIFIED

One item, and it is the one I cannot reach from here.

1. **The 4 GB rasterise ceiling.** 472 frames build as SVG in one process with no
   errors. Whether node and resvg release between families with the real
   rasteriser at `exportScale: 2` needs the machine and the toolchain, not the
   engine. The per-family batch path remains the documented route because it is
   known to work.

One standing caveat rather than an unverified item: the breathing/pinning
classification across ~20 data authors was applied by the rule in §1.5, not
reviewed mark by mark. I have now looked at both ends of the ink range and both
are right — evidence for the rule, not proof for every call site.
