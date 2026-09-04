# dennis-v2 — visual system v2

Everything here is drawn by `engine/hand.js` + `engine/plates.js`. **The manifest is
emitted by the same function call that draws the plate.** There is no measuring step,
so slot geometry cannot drift from the artwork.

## What's in this batch (board 01)

| Path | What |
|---|---|
| `engine/hand.js` | the hand: seeded wobble, two-pass pressure strokes, hatch fills, ground tooth, `Plate` container (art + slots + manifest) |
| `engine/plates.js` | palette roles, three surface candidates, plate authors |
| `engine/series.js` | the DATA renderers — line, sparkline bars, cycle path. A plate reserves a region and knows nothing about numbers; this is the other half |
| `peers/` | `peer-strip-16x9`, `peer-strip-9x16` — the complex, one row each |
| `cycles/` | `cycle-frame-16x9`, `cycle-frame-9x16`, `cycle-proof` — the same metric at two moments |
| `board/` | palette board pieces: 8 role swatches, three-series worked example, 3 surface candidates |
| `tables/` | `numbers-sheet-6r-16x9`, `numbers-sheet-4r-9x16`, `manifest.json`, `contact-sheet.svg` |
| `overlays/` | `row-band` — the row highlight, composited into any `band-N` slot |

`Dennis v2 — palette board.dc.html` (project root) is the board. Its numbers-sheet
panel loads `tables/manifest.json` at runtime and places every figure from the slot
table — if a coordinate were wrong, it would be visible there.

## Palette — eight roles, a colour never does two jobs

| Role | Hex | Job |
|---|---|---|
| ground | `#E6DDC9` | the surface everything sits on |
| second ground | `#CBBC9B` | lower plane in the room; row bands. Carries no meaning |
| structure | `#242A31` | rules, line work, type — and the subject's own series |
| down | `#A6412B` | a loss, a fall, a bad number. Nothing else |
| up | `#4B7745` | a rise. Only a rise |
| neutral data | `#6D7B88` | revenue, capital, share count — no direction |
| attention | `#D79E22` | the one thing to look at, once per frame |
| the other party | `#6A5C8B` | peers, consensus, last year, the market's opinion |

Surface: **night card** (`night-card`). Legal pad and whiteboard are drawn as
candidates in `board/` with the argument against each on the board.

Application rule enforced in code: colour is laid as hatch strokes *inside* an
outline with deliberate overshoot and undershoot (`hatch({over})`), density varying
where the hand pauses, ground tooth showing through. Line work is emitted after
colour, always (`Plate.colour` renders under `Plate.ink`).

## Contract

- **No baked text.** Plate authors never emit a `<text>` node. Every word and figure
  is a slot.
- **Every cell is its own slot.** A 6×6 numbers sheet = 55 slots: `unit`,
  `head-1…6`, `label-1…6`, `cell-R-C`, `band-1…6`.
- **Six periods always.** Four fiscal years, last full year, LTM.
- **Coordinates are canvas units, origin top-left.** `exportScale` (2) is declared per
  asset; delivered pixels are `canvas × exportScale`. The manifest never carries
  delivered pixels.
- **9:16 is re-authored, not cropped** — different margins, label column and figure
  size, six periods kept.
- **Type sizes belong to the plate.** Each asset carries `typeRoles` (font, size,
  weight, colour role, `maxChars`) so the renderer sets rather than guesses.
- **Data plates are `playback: "static"`.** Nothing else in this batch boils yet;
  boiling frames land with the room and host families.

## The host: closed, on route 2

Route 2 (constrained construction) shipped. The skeleton was never the hard part —
the **face** was. The first pass drew hollow lidded eyes with no pupils, a wide flat
mouth and hair as strokes radiating off the skull: individually defensible, together
a horror mask. What fixed it:

- Glasses have lenses **and** pupils. Empty lids read as a corpse, every time.
- Brows lift at the **inner** end. Lifted-inner is weary; the mirror image (angled
  down toward the nose) is menacing, and it is the same two strokes.
- Hair is a soft cap with a receding front. No spikes.
- The mouth is short and gently curved — roughly half its old width.
- Ears, a small nose, and glasses temples running back to them, so the head has
  depth instead of being a mask painted on an oval.

Structurally: a limb quad is handed to the stroke pass as an **open** polyline, so
its first edge goes undrawn and the joint buries into the trunk rather than having a
seam ruled across it. Shoulders slope, the waist narrows. Skin `#DDB794`, hair
`#7A6650` — character colours, not a ninth and tenth data role.

## The room: what a set needs that a diagram doesn't

Same lesson, different subject. The first room was geometrically correct and read as
empty, because furniture had been placed by its own top edge and because most of the
dressing only existed in one angle. The rules now, enforced in `roomKit`:

- **Objects take the surface they sit on**, not their own top edge — otherwise the
  keyboard sinks into the desk slab and vanishes.
- **A mug is a cylinder** with a rim ellipse and a handle. A disc is a mug seen from
  a camera position no shot in this video uses.
- **A chair back must clear the desk top**, or it reads as a lollipop; and a chair
  behind a desk cannot overlap the screens, so it gets pushed to the desk's end.
- **A tight angle stops drawing the far wall** instead of cropping the calendar in
  half at the top edge.
- **The screen's back gets vents and a stand.** A blank slab reads as an error.
- Depth is three declared planes: back wall, baseboard, floor.

Set colours: foliage `#7C8B62`, terracotta `#B5745A`, screen `#2E3742`.

## Reproducing an asset, and two writer behaviours that will mislead you

Every delivered plate comes back byte-for-byte from `PLATES.<author>({key, w, h,
seed, pal, …})` — same key, same seed. Two things about how files land here will
make it look otherwise:

1. **Self-closing tags are normalised on write.** The engine emits `<rect/>`; the
   file on disk holds `<rect></rect>`. A raw string compare therefore always fails.
   Diff after collapsing `<t …/>` to `<t …></t>`, or compare path `d=` attributes.
2. **`href` and `xlink:href` are stripped from SVG entirely.** An SVG written here
   cannot reference an external image and cannot embed a base64 one — a test file
   went in at 2,292 bytes carrying two data-URI `<image>` elements and came back at
   206 bytes with zero `href` attributes.

(2) is why `host/` and `room/` have no `contact-sheet.svg`. The other families
inline each plate's own vector geometry into one sheet, which works because those
plates are light; a room plate is ~1.45 MB (grain is only 4% of that, so stripping
it saves nothing), so eighteen of them is ~26 MB. Redrawing the plates small
instead is not an option either — line weight, tremor and overshoot are canvas-unit
quantities, and scaling them down makes the hatch pass degenerate into hollow
outlines with overshoot spikes. So these two families ship `thumbs/<name>.png`
instead: a real downscale of the delivered plate, referenced from the board's HTML
where `<img src>` works. **A thumbnail is always a downscale, never a redraw at
tile size.**

## The operator's scripts

`scripts/*.txt` — fifteen files, one per family plus `00-how-to-read-these.txt`. The
engine does not read them. Each has the same four sections: **USE WHEN** (the
narrative condition that calls for the family), **MEMBERS** (each asset and the one
thing that distinguishes it), **SLOTS** (what populates each, with limits),
**SEQUENCE** (reveal order in beats), and a TRAPS list. The rules that hold across
all twelve — no baked text, six periods always, attention once per frame, direction
colours are direction only, `maxChars` is hard, 9:16 is a re-author — live only in
`00`, and the composite render order (room → band → data plate → host → data region
→ text) with them.

## annotations — the marks the script asks for by name

The SNDK script calls for `annotations/scrawl-oval-wide` and a circle on a table
row. There was no such family. There is now: nine alpha cut-outs — two scrawled
ovals, an underline swipe, a strike-out, a box, a row bracket, an elbow arrow, a
caret and three ticks — stretched onto whatever they wrap.

They are drawn in **attention**, and that is the point: an annotation *spends* the
frame's one attention, so a plate that already carries an attention mark cannot
also be annotated. Making them a family rather than a flag on every plate forces
the operator to choose.

The mark goes on the **type**, not on the slot rectangle. A table cell is 216
canvas units tall for 30-unit figures; an oval stretched onto the rectangle is an
oval around empty space. Each mark declares an `area` slot — "what this wraps" —
and the compositor solves the transform so `area` lands on the target and the ink
falls where it was drawn to fall. That is also what makes `underline-swipe` work
without special-casing: its swipe is drawn *below* its area.

Each mark declares how it may be solved onto its target. `both` (x and y
independently) is only safe for marks that **enclose** — an oval is meant to take
its target's proportions. Lines of their own natural thickness are `x-uniform`:
fit the width, same scale for y, or independent y stretches an underline's swipe
into a fat wave. Those also declare an anchor — `bottom` for underlines, whose
ink sits below the area slot, `middle` for strikes.

The ovals are one geometry sampled twice: the reinforcing arc shares the primary's
waver seed (a different seed reads as a second, wrong circle) and its radial
offset is windowed to zero at both ends, so it leaves the primary line and rejoins
it. The waver is two or three slow lobes across the whole sweep — per-point noise
reads as a lumpy potato — the ellipse is tilted a few degrees because nobody draws
one axis-aligned, and the pen flies outward over the last 8%. Overshoot extends a
stroke tangentially past its last point, so the primary keeps it (that is the
flyout) and the reinforcing arc must not (that was the blunt stub).

Two size classes, because **line weight is a canvas-unit quantity**. Wide marks
wrap headlines and rows; tight marks (`scrawl-oval-tight`, `underline-tight`) wrap
one cell or one word and carry **absolute** stroke weights — fractional weights on
a small canvas come out as hairlines at use size. Every mark declares
`inkWeight` (the authored primary stroke, in canvas units) and the compositor
warns when `inkWeight × solve` leaves the legible band of roughly 3.2–26 units.
Solve *scale* is not the metric: a tight mark reads fine at 0.4×, a wide mark at
0.4× is a hairline. The first version of that check compared scale alone and told
the operator to use the tight mark they were already using.

## episodes + the compositor

`dennis-v2/episodes/sndk-short.json` is the SNDK script as a shot list: 17 shots,
74 seconds, every word in a named slot, every scrawl on a named anchor word.
`dennis-v2/episodes/README.md` is the schema.

`Dennis v2 - compositor.dc.html` reads it and renders each shot for real — room
under band under plate under host under text under scrawl — and audits it against
the limits in the manifests. It exists because every asset in this library had
only ever been checked alone. Within an hour of existing it found four things:

- `mark-last` on a chart was 10 chars against a 7-char limit
- a headline body wrapped to 4 lines against a 3-line limit
- a closing date was 11 chars against 8
- an oval solved onto the whole 900u `hook` slot drew 88u off each side of a
  1080u frame, so the stage clipped both arcs square. A mark draws *outside* what
  it wraps, so a target that wide cannot be circled at all — the fix is to circle
  the figure rather than the sentence, and the audit now errors when a mark's
  solved canvas leaves the frame
- **`overlays/row-band` was drawn in attention**, not second ground — so a
  banded row plus a scrawl was two attentions in one frame. The doctrine in this
  README had said second ground since the first batch; the code had never agreed.
  Fixed in the engine, not in the doc.

The two host-placement rules are in the compositor because they are the two ways
a composite goes wrong: the host scales to the anchor's **height** with the floor
line pinned (never to its width — the figure box includes the arms, which are
meant to pass it), and `row-band` stretches in **x only** (stretched in y, the
hatch degenerates into a slab).

## Status

Complete: 119 shipping assets across 14 families, every manifest consistent with
disk. `structure/flow` is 16:9-only by design — a left-to-right process has no
portrait form; in 9:16 use `timeline` or `unit-ladder`.

## The audit reconciliation — two real defects, two measurement artefacts

A pipeline-side audit reported four things. Two were real and are fixed; two do not
reproduce at any asset the report named, and the reason they do not is that the two
sides were measuring differently. So **the metric now ships in the engine** as
`engine/audit.js`, and `dennis-v2/audit/report.json` is its output. `Dennis v2 -
scale and boil audit.dc.html` reads that file — it is not a hand-written page, so it
cannot drift from the numbers.

**exportScale — one scale, whole library, and it is 2.** The report described rooms
at 1, cards and frames at 1.5, and 42 stale base PNGs. Measured: thirteen of fourteen
families were already 2× on disk and declared 2× in their manifests, rooms included;
no family has ever been at 1.5. The real drift was in **host**, four base poses whose
base, `_f01` and `_f02` PNGs were rasterised at 1× — 1080×1920 files behind a
manifest promising 2160×3840. Twelve files, re-rasterised from their own SVGs, base
re-copied from `_f01`, thumbnails re-cut. A 1× host composited onto a 2× room is a
soft figure on a sharp desk, which is the one thing the tonal doctrine cannot survive.

The scale is 2 because of the two things this library is actually asked to do: a 16:9
room filling a 9:16 frame, and a push-in on a card. 1 has headroom for neither.
`Plate.manifest()` used to read `o.exportScale || 2`, and **that argument was how
drift got in** — any caller could hand one plate its own scale and the manifest would
faithfully record it, so a shot mixing a room with a card needed a resample mid-
composite. It now reads `AUDIT.EXPORT_SCALE` and ignores anything passed to it. Every
manifest carries a `scaleAuthority` line saying so.

**Base must be byte-identical to `f01` — it was, everywhere except host.** 52 boiled
assets across annotations, cards, frames, overlays, paper, room and shorts already
shipped a base that matched `_f01` byte for byte. Host did not, and worse than
reported: six base poses carried a genuine third render at boil 0, and the twelve
talk/idle strips declared `files.png` / `files.svg` **that were not on disk at all**
— a player following the manifest got a 404, not a pop. One stale line in `build.js`
caused both (`playback: "static"` on the base host strip, left over from when the
base pose was held still). The base pose is now a two-frame 2fps loop like everything
else: a frozen host standing in a boiling room reads as a photograph pasted onto a
cartoon.

**Nothing is over-boiled and `hook-card-t3` is not dead.** All seven named assets
measure inside spec, as do the other 45 measurable ones: 1.08–1.56 units mean, 3.3–5.0
peak, against a 2-unit target. `overlays/row-band` reads 1.36 against a reported
14.67. Two ways to get a wrong number out of a right file, and `audit.js` closes both:

1. **Unaligned token diff.** Walking two frames' numeric tokens in order is only valid
   while both frames have the same geometry. Host frames re-roll their hatch and fibre
   counts — those line-count draws come off the same rng the wobble does — so under
   60% of paths correspond, every token after the first divergence is compared against
   the wrong one, and the mean explodes. Measured that way the host strips read
   230–296 units. They are not boiling 250 units; the metric lost alignment on token
   twelve. `AUDIT.amplitude()` aligns paths by command signature and **refuses**
   rather than returning a number when coverage drops below 80%.
2. **Sampling a sparse plate.** `shorts/hook-card-t3` moves 269 of its 11,627 numeric
   tokens: the other 11,358 are a card, a grain field and type geometry deliberately
   held still. Average across all of them, or read the head of the file, and it reports
   0.0. `amplitude()` reports displacement over the points **that move** and carries
   the moved fraction next to it, so a sparse plate can never be mistaken for a frozen
   one.

Host is the one family this metric declines on, by design. Its frames are genuinely
different drawings — an open mouth, a 3-unit bob, re-rolled hatch — so its motion is
verified from the declared boil offsets and by eye. If it has to become a number, the
honest way is a rasterised alpha-channel pixel difference, not a path diff.

**Frames as objects is deliberate and permanent.** `frames[]` entries are
`{tag, svg, png, boil, …}`, not filenames. A bare filename cannot say what a frame
*is* — its tag, its boil offset, whether the mouth is open — so the player was parsing
meaning out of a string suffix, which is exactly why a static strip and a two-frame
loop looked identical to it. `Plate.manifest()` was the last place still emitting the
old array-of-strings shape, so a re-emit of any family would have quietly reverted it;
it emits objects now. **Read `frames[i].png`; never construct a name from the asset
key.**

## The library is now one function call

`engine/build.js` declares every shipping asset: the author, the arguments and
the **seed**. The first batches were built by throwaway calls — the manifests
recorded geometry but never the seed, so "reproduces byte-for-byte from
`PLATES.<author>({key, seed})`" was true in principle and unrunnable in practice.
Every manifest entry now carries `author` and `seed`, and the whole library
rebuilds from `BUILD.LIB`. It was checked against the shipped geometry before
anything was overwritten: all 119 assets reproduced their slot tables exactly.

(Board demos are deliberately not in it. They carry drawn data and illustrate the
palette board; they are not plates a shot can cut to.)

## The defect under all of it: sampling is a canvas-unit quantity

One `wobble()` call draws every mark in this library, and the marks are two
orders of magnitude apart in length: a 900-unit rule and a 12-unit axis tick go
through the same function. Its sampling step was a constant 26 units and its
overshoot a constant passed by the caller, so:

- **anything shorter than about 30 units got one sample, and `toPath` returned an
  empty string.** The mark did not draw at all. That is what made short sparkline
  bars vanish, and every x-axis tick in `charts/`, `structure/timeline` and the
  new cycle frame with them — furniture the plates had always been emitting and
  nobody had ever seen.
- **a 16-unit overshoot on a 12-unit tick is a 44-unit scribble** where a tick was
  drawn.
- and in `hatch`, overshoot is what makes a fill look laid by hand rather than
  computed — but 7 units of it across a 20-unit shape (a pupil, a mug rim, a
  point marker) is not a fill that misses its outline, it is a hairy blob.

All three now scale with the thing being drawn: step is capped to a fifth of the
stroke, stroke overshoot to a third of it, hatch overshoot to a third of the span
it fills. Long strokes are untouched — a 900-unit rule is the same drawing it
always was. Short ones are drawn as what they are. Every asset was re-rendered
through it, plus 12 contact sheets, 48 thumbnails and the five data proofs.

## peers and cycles — the two plates the SNDK script asked for and had not got

Both are compositions, not new drawing: the interesting work was deciding what
carries the weight.

**`peers/peer-strip`** — "it did not move alone". Two figure columns, because a
strip carrying only the move is a fact with no consequence: the move says what
happened today, the multiple says what the market now thinks of it. A third
figure would make it a table, which is a different plate. Emphasis is decided in
the plate rather than left to the operator — the move is the largest figure, the
multiple second, the ticker smallest, because a ticker is a label and not a
number. The subject's ticker is structure and every peer's is otherParty, so the
row you are in is legible with no highlight at all, which keeps `band-N` free for
the row the voice-over is on. `move-N` is authored in `down` (a complex moves
together and that move is almost always red); a green row is a role override on
the shot, not a second plate.

The strip is drawn as a ledger: a heavy rule under the heads, a closing rule at
the foot (without it the last row's figures hang off the bottom of nothing and
the strip reads as a fragment of a longer list), a divide between label and
figures, a lighter one between the two figure columns — both columns are
right-aligned Courier, and without it "-12% 7.8x" reads as one number — and a
dashed rail per row. The rails are drawn as separate strokes, not a dash array,
because a dashed line is one path with one tremor: the dashes would all waver
identically, which is the one thing a hand never does.

Each rail carries the row's bar. `bars` is a region: the move as a shape as well
as a figure, on one scale shared across the rows, with the zero rule placed from
the domain — so when every move is red, zero lands on the right-hand edge and
every bar runs left from it, which is the shape the beat has. The plate cannot
know that, so it reserves the column and `series.rowBars` draws it.

And no ground2 panel behind the rows: `row-band` is ground2, so a ground2 band on
a ground2 panel is the invisible-highlight defect this library has already
shipped once. The strip stands on rules.

**`cycles/cycle-frame`** — the same metric at two moments. then → now is not a
trajectory, and an arrow from one figure to the other would be making the bull
case by accident: the reason the frame exists is that the line went somewhere
else first. So the two moments are type and the shape between them is DATA —
`series.cycleArc` draws every intervening period and returns the minimum, which
the operator labels in `trough` on real coordinates. Portrait puts the figures
side by side with the path full-width beneath, tied to it by a drop line each
(then → down → now); landscape stacks the figures down the left with the path
beside them, where reading order is already left-to-right and a tie would be
furniture for its own sake. One colour for the whole path: colouring the fall in
`down` and the recovery in `up` makes the frame argue for the recovery.

The episode uses it at s14 with `then` = FY21 rather than FY23 — with then=FY23
the trough IS then, and the frame loses the fall that made it worth drawing.

The band is drawn as a plot area in the charts family's own vocabulary: a faint
tint, gridlines, the L-axis, ticks under the baseline and the six periods named.
The first version was a hatched slab with a thin box round it, which is a slab
with a line on it — a path needs a plane to be read against, and the periods are
half the claim, because "three years ago" is only legible if the axis says which
three years. Each figure also gets a rule in its own colour under it, otherParty
under then and structure under now, so the pairing is declared on the plate and
not only in the type.

### A defect the tick marks found again

Every period tick came out invisible. `wobble`'s sampling step defaults to 26
canvas units, which is longer than a 13-unit tick: sampled once, the path
collapses to nothing. It is the same defect that made short sparkline bars
vanish, and the same fix (`step: 4`). Worth knowing that **`charts/` draws its
x-axis ticks at 11–16 units with the default step**, so they are almost certainly
gone there too — not fixed here, because it would re-author the whole charts
family.

### The rhythm defect, again

The first peer strip divided the frame by the row count: 1,300 units among four
rows of 58-unit type, which put 260 units of air inside every row, and the same
hand-picked-constant problem the text plates had. Both plates now measure the
type (`blockH`), stack, and centre the block in what is left — a row is a
multiple of the figure in it, never the frame divided by how many there are.

### The compositor now draws data

`engine/hand.js` and `engine/series.js` load in the compositor, and a shot can
carry `series: { path: […] }`. Every renderer returns SVG in canvas units, so the
whole set is laid over the stage as one SVG at the canvas viewBox — a region
cannot be scaled wrong independently of the plate under it. Layer order is now
room → band → plate → host → data → text → annotation. The audit gained two rules
with it: a renderer region with no series warns (the plate drew furniture around
a hole and the shot left it empty), and a series whose length disagrees with the
plate's period count errors.

One thing it surfaced immediately: the strip's peer rows are **empty**, because
the script names Micron, SK Hynix and WDC and prices none of them. That is the
honest state — an empty cell in this library means NO DATA — so the seven
missing figures sit in the shot's `needs` and in `gaps`, not in invented numbers.
Runtime is now 77.0s against a 75s target: s06b is a new beat, not a
substitution, and the two seconds have to come out of a headline or the sheet.

## Boil — the host only

The host's talk and idle loops did not boil. Worse: per pose, the base plate,
`talk_f02` and `idle_f01` were **byte-identical files** — three names for one
drawing. Only the mouth (talk) and a 3-unit bob (idle) had ever changed, and both
of those are geometry, not hand.

`boilShift(S, n)` wraps the stroke pass and shifts **every seed** by `n × 9173`.
Tremor, overshoot and hatch phase all land somewhere new; width, gap, amp and every
coordinate are untouched. So it is the same drawing redrawn — which is what boil
means — rather than a second drawing, which is what varying weight or amplitude
would have produced. Point rings (`ellipse`) carry their own rng and are shifted
too, or the outlines sit still inside trembling hatch.

`n = 0` is the identity, so the base plate still reproduces byte-for-byte from
`hostFigure({… boil: 0})`. Indices: base 0, `talk_f01` 1, `talk_f02` 2,
`idle_f01` 3, `idle_f02` 4. All 30 frames are now distinct files.

The board carries a **live boil check** — two stacked thumbnails cut by a CSS
`steps(1,end)` animation at 8fps on twos, pose and loop switchable. It is there to
catch the one failure mode: if the figure appears to jump position or change weight,
the boil has become a second drawing.

The room and the data plates still do not boil, deliberately — a boiling table is
unreadable, and a set that boils behind a boiling figure doubles the noise for no
gain. If the room should breathe, that is a slow drift, not a boil.
