# Dennis v2 — ANSWERS.md

Four written answers requested before the 45-plate round. Each states what is measured,
what is decided, and what is still unverified.

---

## 1 · The stroke-boil decision for the ten marks

**The marks keep their strokes. There is no flat rebuild, and the `[SCRIBBLE:]`
vocabulary is unchanged.**

The premise the question rests on has moved. §6 removed stroke *boil* — the per-frame
re-jitter — but the rebuild also scoped rules 2 and 4 **by family** (`DESIGN.md` §8.2)
when the drawn plates were ported. `annotations/` is one of the twelve drawn families. A
mark's varied stroke weights and partial opacity are the technique, not a defect, and
they are exempt by declaration, counted in every audit report (rule 19: 93 of 141), and
closed to `host` and `room` absolutely.

So:

- **Nothing about the existing ten changes.** They are drawn, ported, recoloured, and
  now carry purpose lines. Their character is intact.
- **New marks are authored in the same idiom** — strokes, not closed flat shapes. This
  unblocks proposals 108–110 with no character question attached.
- **Boil specifically is gone.** A mark does not re-jitter per frame. Under §6 its
  motion is the data-plate rule: the frame breathes, the mark does not. A mark sits over
  a plate and is pinned to what it marks; a jittering circle around a fixed number is
  exactly the thing that made the drawn kit feel unstable.

Three faults were found and fixed in the marks during the port, none of them the
drawing: the port mapped legacy `attention` to the wrong ink so every mark was the wrong
colour; the review showed them on a bare wall when a mark is `cutout: true, over: "any
plate"`; and they were painting a caption of their own, which a cut-out must never do —
the words belong to the plate underneath.

---

## 2 · What a plate's motion now is — BUILT at rebuild-17

**§2 as first written described motion that was not built.** Every host strip exported
byte-identical to its pose's still, nothing drew `mouthClosed/Mid/Wide` into a frame,
and nothing read `design-tokens.json → motion`. It is built now, in `engine/figure.js`
(host) and `engine/hand.js` (plates), and `node engine/export.js` writes every frame as
its own file, listed in `out/index.json`. The contract your renderer reads —
`playback`, `fps`, `frameCount` — is unchanged; the frames now exist.

- **Host.** `-talk` loop/8/3: the three mouths, closed → mid → wide, each on its head
  offset from `motion.hostOffsets` so it reads as speech. `-idle` loop/4/3: the head
  offsets alone (rotation about the neck join, shoulder line moving a unit). `-blink`
  overlay/4/2: eyes open, then closed (each eye squashed to 16% of its height about its
  own centre — the model carries no closed eye, so it is authored, not drawn). **The base
  strip is now a true still, 1 frame** — it was declared a 3-frame loop while exporting
  one image, and looping the offsets there as well would make two strips do one job.
- **Data plates** loop/3/3. The frame's rule lines take `motion.dataRuleOffsets`
  (0, 1, 0). Ink drawn inside `H.pin()` — axes, baselines, the prior close — and every
  value stay still. `hand.js` now records pinned-ness at the draw call and `toSVG`
  offsets only the unpinned ink; at offset 0 the output is byte-identical to before, so
  the base file IS `_f01`.
- **Rooms** still/1/1.

**Audit rule 25** fails any talk, idle or blink strip whose frames all hash the same.
Today: 72 strips, all moving.

---

## 3 · The rasterisation step — stays with you, and the review set is NOT the kit

**Correction.** This section used to tell you to rasterise `out/`, and `out/` had the
sample content burned into 390 of its 536 files — "MERIDIAN · 14 FEBRUARY" on the
intraday chart. Rasterised as the kit, that would have put a fictional company under
every real figure.

**`node engine/export.js` now writes BLANK plates** — empty forms, as the kit has always
meant them. The review set with the sample burned in exists only under
`node engine/export.js --sample` and goes to a separate directory, `out-review/`, whose
index says in its header not to rasterise it. You have said your ingest draws each plate
blank from the engine anyway; this removes the hazard for anyone else.

Rasterising stays with you (your decision). The kit ships SVG masters and the work list:

```
node engine/export.js         # out/*.svg + out/index.json
```

**Expected: 1,964 SVG files — 536 base files and 1,428 animation frames — 0 failures.**
By directory: structure 384, figures 368, host 288, charts 264, paper 168, tables 152,
annotations 80, cards 48, shorts 40, peers 40, room 28, overlays 24, cycles 16, frames 64.
Every entry carries `file`, `frame` (`null` for the base, `_f01`… otherwise),
`canvas`, `viewBox`, `inkBox`, `delivered`, `hash` and `bytes`.

**Audit rule 26** fails any exported file whose ink leaves its viewBox by more than a 10%
bleed per edge — the check that would have caught the host being drawn into the room's
320×180 box.

---

## 4 · Close framing: crop or pose?

**It is a crop. Looked at, not asserted — see `Close Crop Review.dc.html`. VERDICT: the
crop reads and `close-up` stays a framing.** Two close-specific findings below, neither
a blocker, neither needing a new pose.

The rebuild drops `close-up` as a framing rather than a pose because the figure is one
shape list at one proportion and any framing is a window onto it (§S2.2). The solve is
the anchor constant **C = 0.5583**, asserted by **audit rule 8** and derived — not typed
— from the proportion table: crown to shoulder plus the arm chain over the figure box.
Rules 14 and 16 further assert that the anchor survives the portrait window across 24
anchored room plates with 0 clipped, and that every drawn anchor comes from that one
derivation.

So the mechanism is real and checked. What has **not** happened is anyone looking at a
close crop of the figure at delivered scale and judging whether the face reads. The three
host roles you say have no member without it are a product decision resting on a crop
nobody has reviewed.

**What the review showed.** The crop window is 145×199 canvas units — head plus the
shoulder line at 1.32 head-units, a close framing in the grammar of the show rather than
a passport crop. It upscales 26.5× to 3840 at no cost, because it is vector: this was
never a resolution question. The glasses, brow, nose and mouth all carry, and it is
recognisably him. **Nine head paths plus three marks is enough.** The three host roles
with no member get one at zero drawing cost.

**Finding 1 — the shade terminator is a close-range problem.** `skin.lit` is cool
blue-grey and `skin.shade` is warm orange; that is the lamp doing its job and it reads
correctly at full figure. At crop scale the boundary runs straight down the facial
midline as a hard diagonal and the two halves read as two temperatures rather than one
face lit from one side. A palette-geometry interaction, not a drawing fault. Fix is to
move the terminator off the midline for the close framing — worth doing before
`close-up` carries a confession beat.

**Finding 2 — never cut close on the still strip.** `mouthClosed` is a filled bar: a
mouth at full figure, a horizontal dash at crop scale, and a still close framing holds
that dash on screen. Cut close on `-talk` or `-idle`, where the three mouth shapes cycle,
and it resolves. **This belongs in the shot list as a rule, not in the drawing as a
change.**

**The review page was wrong before the asset was.** Its first cut drew the raw head paths
without the kit's `headT` and `glassesT` transforms, so the glasses sat adrift and the
head box was offset from the skull — indistinguishable from a close crop exposing a
broken asset. The asset was fine. Render through the kit's own paint order, never an
approximation of it.

**It stays cheap either way:** the swap path is still nine part paths into one table with
no engine change. Adding a pose is joint positions in `engine/kit-model.js → POSES`, not
a redraw.


---

## 5 · The five data-backed proposals — operator verdicts (rebuild-14)

Answered by the operator; recorded here because a plate drawn against a column that does
not exist is the most expensive kind of wasted drawing.

| # | proposal | verdict |
|---|---|---|
| 45 | `figures/cohort-3` | **DROPPED.** Cohort retention is not in the export and cannot be added as a column — it exists only where a company chooses to publish it in its own deck. |
| 62 | `charts/comp-vs-performance` | **DROPPED.** Executive pay is proxy-statement data, not in the workbook, and the price series is a 120-day window so there is no multi-year total return either. US proxies do publish the table, so it is gettable by hand — but it is two multi-year series typed from scratch, which is a lot of surface to get wrong. |
| 66 | `charts/buyback-vs-price` | **KEPT, REDRAWN.** Shares repurchased and the price paid are not real columns, and deriving shares retired from the change in diluted count is wrong for anything with meaningful stock comp — which is most of the companies where the question is interesting. Redrawn as **buyback dollars per year with the share-count change beneath**. Both are real columns. |
| 69 | `structure/acquisition-ledger` | **KEPT AS IS.** A structure plate, same shape as the promise ledger; the writer types the rows. It never needed a column. |
| 86 | `figures/customer-concentration` | **KEPT AS IS.** Not in the export, but one to three numbers off the 10-K that the writer types. **Must degrade to nothing when a company does not disclose it, rather than to an empty plate** — recorded as a requirement on the plate, not a note. |

The 86 requirement is a general one and is worth stating as a rule: **a plate whose data
may legitimately not exist must have a declared empty behaviour.** An empty plate on
screen reads as a production fault; a plate that is simply not cut reads as an editorial
choice. Tracked as `degrades_to` in `roles.fragment.json`.
