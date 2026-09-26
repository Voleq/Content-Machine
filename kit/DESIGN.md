# Dennis v2 — DESIGN.md

**The spec, and the only source of truth.** If a decision is only in a chat message it does
not exist. Every entry below carries its reason, because a decision without a reason gets
re-opened by the next session.

Numbers and colours are NOT in this file — they are in `design-tokens.json`, which the
engine reads. This file says what the numbers mean and why they are what they are.

| file | holds |
|---|---|
| `DESIGN.md` | the spec. Part set, laws, composition rules, pose inventory, reasons. |
| `design-tokens.json` | everything numeric or chromatic. The engine reads it; nothing is hardcoded in a draw function. |
| `REBUILD_STATE.md` | what is done, what is next. Read it first. |

---

## 0 · The diagnosis, so the rebuild does not inherit it

Six rounds of the hand-drawn treatment each fixed the loudest fault and shipped the next.
The cause is that a drawn figure has about a dozen independent ways to be wrong and **not
one of them is expressible as a number anyone can assert** — so there was nothing to check,
only something to look at.

`hand.js` made it structural: three unverifiable systems stacked (perpendicular noise
decides where the edge is, a second pressure pass decides how heavy it reads, hatch-inside-
outline decides what colour the surface actually is), then judged by eye on a phone.

**The replacement is not "draw it better". It is: remove the ways to be wrong.** Closed
shapes, flat fills from a fixed table, proportion set once as a number, colour picked by
hand and never computed. `hand.js` does not survive in its current form.

Every law below exists to convert a judgement into a number, and §10 checks each one
mechanically. A rule that cannot be checked is a rule that comes back.

---

## 1 · The flat-paint law

**A surface is one flat colour. When light divides a surface it becomes TWO SHAPES with two
flat colours — never one shape with a gradient, a hatch, or a dark overlay.**

The old kit darkened a base colour to make its shadow, and that reads as *dirt on the
object* because it literally is: something laid over the paint. It also drifts — every
multiplied colour heads toward the same grey-brown, which is why the frames went muddy.

Enforced by audit rules 1, 2 and 3. Rule 2 is the one that matters: **every `opacity` and
`fill-opacity` in an emitted SVG is exactly 0 or 1.** A black at 0.3 is how shading sneaks
back in, and it sneaks back in every time it is left possible.

### 1.1 The shadow colour is authored, and shifts hue

A shadow is **cooler and differently hued**, not the same hue darker. A red apple's shadow
is violet. Both members of every `{lit, shade}` pair in `design-tokens.json` are picked by
eye; **neither is a function of the other**, and nothing in the engine may derive one from
the other.

### 1.2 What "shade" means — the two-source reading

This resolves an ambiguity in the brief, and it is the most load-bearing decision in the
colour system, so it is written down rather than assumed.

The brief's rule is *"lit shifts toward the key; shade shifts toward the ambient"* — but its
own night example gives skin `{lit: #8FA8B8, shade: #D9A06B}`: a cool lit side and a **warm
amber** shade side, which is not the ambient at all. Both are right, and the reconciliation
is that the night set has **two** sources:

- **the monitor** — cyan, the key, the reason he is up
- **the desk lamp** — amber, the fill, which reaches the desk, the paper, his hands and one
  side of his face, and **does not reach the back wall**

So: **`lit` is the key side. `shade` is whatever secondary source reaches that surface —
the lamp for anything near it, the ambient for anything it does not reach.** The brief's own
table is exactly consistent with this: `wall.shade` IS the ambient `#141824`, while
`skin.shade` is lamp amber. Two warm accents in a cool field is the whole night look, and it
only exists because shade is per-material rather than one global darkening.

`dusk` has the same structure with the window as key and violet as ambient, which is why
every dark in that hour leans violet: it stops a warm key from going orange-and-brown.

### 1.3 Small palettes

**13 material roles per hour**, each `{lit, shade}` — 26 colours, and that is the entire
chromatic vocabulary of a video. Small palettes look composed; large ones look muddy,
because a large palette is *generated* rather than chosen. The 13: wall, wallSide, floor,
desk, screen, glow, lamp, skin, hair, shirt, **trouser**, paper, prop. Plus one `contour`
and a 9-entry `ink` set for data plates and overlays.

`trouser` is the thirteenth and it is a deliberate addition: the brief's example table had
no role for legs, and without one the legs would have to borrow `shirt` or `prop`. Recorded
here because this section said 12 through rebuild-01 while `design-tokens.json`,
`REBUILD_STATE.md` and the review page all said 13 — the tokens file was right.

---

## 1.2a · Which source is on his face

`shade` is the secondary source that reaches the surface (§1.2), and **which source that is
depends on where he is looking.** The monitor is the cyan key and it is a fixed object on
the desk: it cannot be on his face when he is turned away from it. Facing it, cyan is the
base and the lamp is the rim. Reading a page, head in hands, walking out — the lamp lands
on him, so amber is the base and the cool becomes the rim. Same two shapes, same two
colours, assignment swapped; no new colours and no gradient. `turn-to-screen` additionally
flips which edge the shade band sits on, because he faces camera-right.

---

## 2 · The figure — constructed, not drawn

**FOURTEEN authored closed paths as of rebuild-02, not nine.** The nine were a body with
no face on it, and the character this show already has is written down in the predecessor
kit's own `host/manifest.json → character` — deadpan, tired, half-lidded, flat mouth with
one corner dropped, stretched tee collar, hair flattened on the slept-on side. Not one line
of it had a shape. The five added are **nose, mouth, brow ×2, under-eye ×2, collar**, and
each exists to carry a named line of that sheet rather than to decorate.

**Stubble was tried and dropped, and the reason is a palette limit rather than taste.** The
sheet asks for it "deliberately faint", which needs a value one step off the skin; a
13-role flat palette has no such colour, `skin.shade` is the lamp, and `hair.shade` over
the jaw at full opacity draws a beard. Faint is only reachable through a partial opacity
and audit rule 2 bans those. So the fatigue is carried by the under-eye pair and the
dropped mouth corner. A fourteenth material role would buy stubble back if it is wanted.

Each path is placed by a number from the proportion table. **A pose is a
set of part transforms, not a redraw.** `close-up` is the same head at a larger scale under
a tighter crop, not a separately drawn head — which is what makes him the same person in
every plate, something the drawn version never achieved.

| part | notes |
|---|---|
| head | one silhouette, authored once, never varies |
| hair | one shape sitting on the head |
| glasses | **the signature** — two rounded rects and a bridge, always present |
| eye ×2 | two short horizontal dashes. That is the whole deadpan. |
| torso | one shape. The neck is drawn with it — one path, not a tenth part. |
| arm ×2 | upper + fore as one shape per arm, per pose |
| hand ×2 | mitten silhouette, no fingers |
| leg ×2 | one shape per leg, per pose |
| nose · mouth · brow ×2 · under-eye ×2 · collar | **rebuild-02.** The face and the tee, one line of the character sheet each. |
| foot ×2 | **the ninth.** The brief's table listed eight rows while calling for nine paths; this is the missing one. It cannot fold into the leg without painting his shoes in trouser colour. |

### 2.1 Proportion is a table, not a judgement

`design-tokens.json → proportion`. Unit is **HU, one head height**, so the figure has one
size number and everything else is a ratio. *"Is he a midget"* stops being expressible.

**Seven widths moved at rebuild-02, none of them vertical**, so the closure below is
untouched and total height is still 7.00. `shoulderWidth` 2.05 → 1.80 is the one that
matters: at 2.05 the shoulder line is 2.6 head widths and the torso reads as a slab with a
head on it. That is a proportion complaint of exactly the kind this table exists to answer
— it was simply the horizontal one, and nobody had measured it. The other six are the
glasses (0.72 → 0.62 wide: at 0.72 the frames span 92% of the head and the face is a pair
of frames), the eye dashes and the hand. All carry a `_widthsMoved` note in
`design-tokens.json`.

**Total height is 7.0 HU, not the old kit's 6.8.** The complaint was about proportion, so
the number that drew it gets changed deliberately rather than kept. Seven heads reads adult
and composed at 9:16; six-and-a-half reads juvenile.

The table is **arithmetically closed**, so a fresh session can check it rather than trust
it: shoulder 1.32 + torso 2.45 = hip 3.77, + legs 1.60 + 1.63 = 7.00. Arms close too —
shoulder 1.32 + upper 1.32 + fore 1.18 = wrist at 3.82, which is 0.05 HU below the hip, so
arms hang correctly at rest with no per-pose correction.

### 2.2 Contour

**One uniform contour on the figure: one weight (0.035 HU), one colour, no pressure, no
taper.** It is what makes him read against any wall in either hour.

**The room carries none.** It separates by **perceptual difference between adjacent flat
shapes — value, hue, or both** (see §2.2a for why it cannot be value alone), which forces
the palette to be good: if two room planes do not separate without a line, the colours are
wrong and a contour would only hide it. Audit rule 4 checks uniformity.

### 2.2a What actually makes him read — and the metric this got wrong twice

The brief says the uniform contour "is what makes him read against any wall in either
hour." **Measured, that is false for night**, which is the hour the show is set in: the
contour `#0B0E16` against `night.wall.lit #20293C` is **1.33:1**, and a contour darker than
the wall barely separates anything. The top of his head and both legs dissolved into the
back wall. In dusk the same contour is **6.25:1** and works fine, which is why the claim
survived unexamined.

**And a per-hour light contour does not fix it.** A light contour reads against the night
wall (`#AEBECE` would be 7.6:1) but then vanishes against his own skin at 1.3:1 — and the
contour's second job is separating part from part. One uniform contour cannot be both.

So the rule is the other way round: **the wall is the most separated thing in the frame and
every figure material sits clear of it.** The contour then reads as the boundary between two
things that already separate. This is also just true of the fiction — he is lit by the
monitor and the back wall is not.

#### The metric is ΔE in OKLab, NOT a WCAG contrast ratio

The first cut of this rule said "≥ 2:1 WCAG against `wall.lit`". That is wrong, and
`dusk.shirt` is the case that proves it: `#93AECE` on `#B9A184` is **1.08:1 WCAG** —
nominally a failure — and it reads immediately, because light blue on tan separates by
**hue** while their luminances happen to match. WCAG ratio measures relative luminance only.
It is the right tool for type on a ground (§5.3, audit rule 5) and the wrong tool for two
flat shapes meeting.

**THE FLOOR: every figure material's `lit` is ≥ 0.10 ΔE from its hour's `wall.lit`, measured
as Euclidean distance in OKLab.** That counts value, hue and chroma together, which is what
§2.2's "separation between adjacent flat shapes" was actually reaching for. Measured:

| | night ΔE | night WCAG | dusk ΔE | dusk WCAG |
|---|---|---|---|---|
| skin | 0.437 | 5.86 | 0.140 | 1.59 |
| hair | 0.199 | 2.22 | 0.360 | 4.36 |
| shirt | 0.175 | 2.02 | **0.106** | **1.08** |
| trouser | 0.184 | 2.09 | 0.220 | 2.26 |
| prop (shoes) | 0.155 | 1.72 | 0.216 | 2.26 |
| *contour* | *0.119* | *1.33* | *0.464* | *6.25* |

Every figure material clears 0.10 in both hours. The contour clears it in dusk and does not
in night, which is the finding stated plainly rather than papered over.

**Four values moved to get here**, each carrying a `_floor` note in `design-tokens.json`
saying what it was: `night.hair.lit` (ΔE 0.030 → 0.199), `night.trouser.lit` (0.033 →
0.184), `night.prop.lit` (0.074 → 0.155), `dusk.prop.lit` (0.054 → 0.216). Nothing the
brief authored by hand needed changing: `night.skin`, `night.shirt`, `dusk.desk`,
`dusk.shirt` and `dusk.skin` all clear the floor as picked.

**And the honest note on process:** the first pass fixed only the two materials that had
been named out loud and left `prop` failing in both hours — which is exactly the
fix-the-loudest-fault-and-ship pattern §0 diagnoses. It was caught by measuring all five
materials in both hours instead of the two under discussion. Audit rule 12 exists so that
sweep is not a thing anyone has to remember to do.

### 2.3 Where the personality lives

The glasses, the two dash eyes, posture (shoulder line and head angle, per pose), and the
room. **Four places, none of them line quality.** The wobble was never carrying the
character — that is the finding behind this whole rebuild.

### 2.4 Poses and framings — the distinction that got violated

- **A POSE** is a cut-out with alpha that stands in a room. It publishes `floorLineY` and a
  figure box, and the compositor solves it onto a room's `hostAnchor`.
- **A FRAMING** is a camera distance — the whole shot. It publishes `floorLineY: false` and
  an eye-line `fit`, and is **never** solved onto an anchor.

Two live bugs from the drawn kit are fixed here by construction rather than carried over:
`host/sitting-at-desk` was in the framings-only role while declaring a floor line, and
`host/empty-chair` sat in a host role while publishing no alpha.

**The two laws, now audit rule 7:** every member of a host role publishes `cutout: true`;
every member of a framings role has `floorLineY: false`. `scripts/check_roles.mjs` already
runs both against `roles.json` and survives the rebuild unchanged.

### 2.5 Inventory

Re-derived from what the show needs, not ported. Minimum: a neutral to-camera, a gesture, a
seated-at-desk, a turn-to-screen, plus the framings. Full inventory is slice 3 and is not
settled yet — it is proposed in `REBUILD_STATE.md` when slice 2 clears.

### 2.6 The anchor constant `C`

`contact.y = anchor.y + C·anchor.h`. **`C` is free to change** — it is a property of the new
figure — but it stays a single constant **derived from the rig, published once, identical
across every pose**. Derivation, unchanged in form from the drawn kit:

    C = (rig.forearmY − slots.figure.y) / (floorLineY − slots.figure.y)

Computed closed-form per pose from the solved rig and asserted equal across poses, never
typed. **The new value is published when the rig exists — slice 2.** Audit rule 8.

---

## 2.5 · The figure box, and C

**C = 0.5583.** The forearm's height as a fraction of the figure box — the number the
anchor solve needs and the one slice 2 owed. It is derived, not measured off a plate:

    shoulderFromCrown 1.32 + armUpper 1.32 + armFore 1.18 = 3.82 HU from the crown
    figure box = floorLineY 760 − figure.y 40 = 720 units = 7.20 HU
    C = (3.82 + 0.20 crown padding) / 7.20 = 0.5583

Because it comes from the proportion table, and the table does not move between poses, **C
is identical for all ten poses.** A plate reporting a different C has a broken box.

**LAW — every pose publishes the STANDING figure box, padded above, never its own.**
`sitting-at-desk` spans 534 units against the standing 720. The anchor contract scales by
`floorLineY − figure.y`, so an honest seated box scales him up by 35% and he changes size
between two cuts in the same room. Pad above the crown and publish 720. Costs nothing, and
it is undetectable until two plates are cut together — which is after the volume slices.

---

## 3 · The two hours

One hour per episode, **never mixed inside one video** — two hours on one wall is two rooms.
`roomHours` keeps its `hours` / `episodes` split and `episodes` enforces the pick.

- **`night` — three in the morning.** Dark room, monitor as cyan key, desk lamp as amber
  fill, most of the frame in near-black ambient. Highest character, and the hour the show is
  set in.
- **`dusk` — the lit set.** Warm key, deep cool shadow, violet-leaning darks. Calmer, more
  legible, safer for a dense data chapter.

**Geometry is shared between twins** — byte-identical slot boxes, `floorLineY` and
`hostAnchor`; only colour differs. This held on the drawn kit's dusk plates and is kept and
kept asserted (audit rule 6). The parts are geometry; the hour is a colour table.

---

## 4 · Rooms

### 4.1 Why the corner view failed

An interior corner in naive perspective reads as **a cardboard box**: two walls meeting at a
vertical, floor wedging in at the bottom, nothing for the eye to sit on. Flat colour makes
it worse, because flat has no atmospheric depth to rescue a weak construction.

### 4.2 Rules

1. **Depth from stacked flat planes, not perspective.** Foreground object, mid plane (desk),
   back wall. Depth is overlap plus value separation between planes.
2. **Frontal or near-frontal by default.** Square to the wall or a shallow angle. **Corner
   views are dropped** unless one earns its place with a strong composition.
3. **Every room needs an anchor object** — lamp, monitor, window, stack of paper, plant. A
   bare wall with a desk is the "boring" that was called out. Two or three deliberate
   objects, each a flat shape, each in the palette.
4. **The light source is visible or implied by a hard-edged shape.** In `night` the monitor
   glow is a flat quadrilateral on desk and wall; in `dusk` the window light is a flat
   parallelogram on the floor. Hard edges, palette colours, **no falloff**.
5. **Negative space is a composition tool** — but it needs one strong shape to be negative
   *against*.

Room concepts are delivered as a **set**, not one at a time: they have to look like one
apartment.

### 4.3 DECIDED — texture: none, and relief comes from shape count

Pure flat can read sterile at 9:16, and the answer is **more flat shapes** — never a texture
overlay, never noise, never a gradient (audit rules 1–3 make those three impossible anyway).

**The rule: every room plate carries at least SIX flat shapes** — back wall, a second wall
plane or floor, desk, one hard-edged light shape, and two anchor objects. Six is the measured
floor at which a 9:16 crop stops reading as a backdrop and starts reading as a room, and it
is a count an audit can check.

### 4.4 PROPOSED — room count: 5 angles, 20 plates

The drawn kit had **52 room plates across twelve angles**, and most existed because the
generator could make them rather than because a shot needed them. Proposed replacement —
**5 angles × 2 hours × 2 aspects = 20 plates**:

| angle | why the show needs it |
|---|---|
| `desk-front` | the talk shot. Square to the wall. The default, and most of every video. |
| `desk-wide` | the scene change and the chapter opener. Carries the title ground. |
| `turn-to-screen` | he reads something off the monitor; the viewer is behind the decision. Replaces over-the-shoulder. |
| `desk-side` | a shallow angle for a second cut inside one chapter, so a forty-minute chapter is not one take. |
| `board` | the wall of index cards. Full-frame data plate, **no host anchor** — cut to it over his voice. |

**Three more at rebuild-02, taking it to 8 angles × 2 hours × 2 aspects = 32 plates.**
`window-wall` is the only angle with the key source in frame, so it is the one that makes
the hour itself legible; `doorway` is the entrance `walking-out-of-frame` had nowhere to
walk to; `desk-top-down` is a detail cut-away with no figure, so it cuts under any voice
line. Still under two thirds of the drawn kit's 52.

**Reasoning:** the original five are the five relationships the show has to its material —
talking to you, showing you the room, reading with you, a cut for rhythm, and cutting away.
Twelve angles of a corner nobody likes is not coverage. **Fewer rooms that look composed
beats more rooms that do not**, and 20 plates is a set one session can make look like one
apartment. Needs sign-off in slice 1.

---

## 3.5 · The strip contract

Every pose emits **four strips and eleven frames, the same for every pose.** A strip length
that varies by pose is a renderer bug waiting for a slot to land on it.

| strip | frames | fps | playback |
|---|---|---|---|
| `base` | 3 | 2 | loop — frame 1 byte-identical to `-talk` frame 1 |
| `-talk` | 3 | 8 | loop — mouth only, one boil index |
| `-idle` | 3 | 4 | loop — a 3-unit shoulder bob, mouth closed |
| `-blink` | 2 | 4 | overlay — index-matched onto idle, **never** onto talk |

**A figure plate is emitted once per hour, not once per aspect.** It carries alpha and is
placed by the anchor solve, so the same plate composites into 16:9 and 9:16 alike. Ten
poses × 11 frames × 2 hours = **220 plates**, where emitting per aspect would be 440. Only
rooms are aspect-bound.

**LAW — a prop declares which side of the figure it paints on.** The page in
`holding-a-page` is in his hands and paints after them; the chair in `sitting-at-desk`
paints before. Same class of mistake as §4.5 and just as invisible until two plates sit
side by side.

---

## 4.4a · Aspects — portrait is a window, not a crop

A 180-unit-tall window taken out of a 320×180 frame is **101 units wide**, which is
narrower than the desk. Cropping landscape to portrait therefore cannot work, and no amount
of re-centring fixes it.

**LAW — each room declares a portrait window into its own shape list**, placed so the host
anchor sits inside it with margin. Same geometry, different viewBox: no second drawing, and
the twin-geometry law (rule 6) holds across aspects as well as hours.

**LAW — an anchor publishes a HEIGHT; its width is derived from the figure's ink aspect,
and the portrait window's position is derived from the anchor.** The solve scales by
height, so height is the only free number. Typing the width as well let `desk-front`
publish a 110u anchor for a figure occupying 35u, which no 98u window could contain — rule
14 then failed on all six anchored rooms for a reason that was in the numbers, not the
geometry. Two typed tables are two chances to disagree (§8.1).

**A room is aspect-bound; a figure plate is not.** The figure carries alpha and is placed
by the anchor solve, so one plate composites into either window unchanged. Eight angles ×
two hours × two aspects = **32 room plates**, against 220 figure plates that need no
aspect variants at all.

---

## 4.5 · The occlusion split

**LAW — every room declares the index from which its shapes paint AFTER the host.** Flat
art has no z. Without the split the figure is pasted over the room: he stands at the back
wall and paints over the desk in front of him, which is the fastest way to make a composite
look like a sticker.

**The split is derived, never typed — and since rebuild-21 it is derived from a LAYER ON
EVERY SHAPE, not from the first desk.** Each room shape carries `front: true|false`. The
desk and everything authored after it defaults to front; a shape authored after the desk
that sits behind him (a wall shelf, a frame, a sheet pinned up, a floor-standing unit
against the wall) is marked `b(...)` in `kit-model.js`. `rooms()` orders each room
behind-then-front, and the split is the index of the first front shape. The old rule — "the
first desk-role shape" — painted every wall item listed after the desk over his head: a
frame across 97% of it in `panel-left`, a shelf across his shoulders in `turn-to-screen`.
Behind: wall, pinboard, floor, back glow, and anything hung on the wall. In front: the desk
slab and what rests on it.

**LAW — check the room WITH HIM IN IT.** Rules 14–16 check the anchor and the split and
passed while the composite was wrong; rebuild-18's recheck looked at empty rooms. `emit.js`
now composites every pose that fits each room by the contract (`M.clearanceOf`) and
publishes the cover as `clearance` on each room plate: `headCover` (share of head and
hair under a front shape — must be 0) and `upperCover` (share of his ink above the desk
top under a front shape — at most 10%). Audit rule 27 fails either. The desk hiding his
legs is the design; a monitor across his chest is not, which is why `desk-front-b` and
`desk-front-low` moved their anchors clear of the monitor, and `window-wall`, `doorway`
and `doorway-wide` moved theirs or the monitor.
A room with no desk — `board`, `desk-top-down` — has no host anchor and needs no split.
An index written into prose is the defect §0 diagnoses; the rule is the record. The host anchor is placed in a **clear column**
— furniture in front of him is depth, furniture through his head is a mistake, and the
difference is whether the anchor was placed before or after the clutter.

---

## 5 · Every other asset — the recolour is half the work

**The entire drawn kit was dark ink on light paper.** Charts, tables, axes, rule lines, row
bands, lower thirds, title cards, statement and caption grounds, callouts, and the frame art
on every data plate. On a dark room all of them break.

**Do not invert.** White-on-black at the same values reads heavier and dirtier than
black-on-white, and every accent shifts perceived brightness. Each asset gets **authored**
dark-ground colours, picked by eye against the actual wall it sits on.

**One `ink` set per hour**, in `design-tokens.json`. Overlays composite over the room, so
their colours interact with the hour: the same lower third on the night wall and the dusk
wall is two different design problems.

### 5.1 The direction that flips, and gets it wrong by instinct

- **`night` plates are dark-ground.** Row bands and cell fills are **lighter** than the
  ground by a small amount (`ground #171D2A` → `band #1F2634`).
- **`dusk` plates are light-ground** — warm off-white, violet ink. Bands are **darker**
  than the ground (`ground #F2E8D4` → `band #E6D8C0`).

Dusk keeps a light ground deliberately: it is the lit hour, the wall behind is a mid warm,
and a dark plate on a lit set is the muddy inversion this section forbids. **Getting this
direction right before authoring 200 of them is the whole point of writing it down.**

### 5.2 Chart ink

Series colours are **picked for a dark ground**, not the light-ground ones darkened. Axes
and rule lines quiet; series loud. **On dark, gridlines need to be much fainter than
instinct suggests** — `night.ink.rule #2C3444` is barely above the ground, and that is
correct.

### 5.3 Type legibility

Title slots publish `ground`, `groundBox` and `colour`; `TITLE_GROUND` selects `card` or
`slab`, and the resolved colour moves from `structure` to `ground` between them.

**Rooms that open a chapter publish a title slot (rebuild-21).** None of the rebuilt rooms
did, so every chapter title would have dropped. A room declares `title: { slot, ground }`
in room units on the model and draws its card as an `ink.ground` shape behind him. `emit.js`
publishes the slot per aspect in canvas units (16:9 = room ×6; 9:16 = the portrait window
scaled to 1080 wide, origin at the window) with `ground: "card"`, `groundBox`,
`colour: "structure"` and budgets from `budget.js`, in `room/manifest.json` (`slots`,
`slotsByAspect`, `opener: true`) and in `emit/slots.json` as `room/<id>-16x9` / `-9x16`.
The card has to sit inside the portrait window and clear of his head, so it goes above him;
audit rule 28 checks both. **Only `desk-wide` opens a chapter today.** The read and talk
angles are framed too tight to hold a card inside the window above his head. A chapter
template has to open on an `opener` room.

**Nothing in `pipeline/` reads `title.colour` yet, so a wrong value there fails silently
today.** Both treatments are tested in both hours — audit rule 5, contrast ≥ 4.5:1 sampled
against the actual ground behind the box.

**The data-plate frame** borrowed the wall's legibility on light ground. On dark it needs its
own ground shape, same logic as the title card.

**LAW — a slab's ink pair is selected against the WALL, not against `ink.ground`, and at
dusk that inverts the pair.** A card sits on `ink.ground`; a slab sits on `wall.shade`.
Dusk's ink set is authored for a light ground, so reusing the card's pair on a dusk slab
put the caption at **1.06:1** — the title passed, which is why it survived §5.3's original
wording: that sentence moves the *title* colour between treatments and says nothing about
the caption. The pair is now derived per treatment: highest contrast against the actual
ground for the title, next value down that still clears 4.5 for the caption. That returns
`structure / quiet` at night and `ground / band` at dusk on its own, so the inversion is
a consequence rather than a typed table.

**Candidates are the TEXT roles only** — `structure`, `quiet`, `ground`, `band`. Ranking
the whole ink set on contrast handed night's slab caption to `subject` at 10.53:1:
legible, and wrong, because `subject` is a chart-series accent and a caption in it reads
as a highlight. **Contrast is a floor, not a selector.**

### 5.4 Round two — sector plates (rebuild-19)

Twelve plates in `engine/plates-r2.js`, each at 16:9 and 9:16 from one aspect-aware
author: six for software, six for industrials. They go in the existing families, reuse
round one's budget helpers rather than copying them, and draw data only through
`engine/series.js`. Three decisions, so they are not re-opened:

- **LAW — a plate may fix its scale only where it draws furniture that is true only on
  that scale.** `peers/rule-of-40` fixes growth 0–50% and margin −10–40%, because on
  exactly that scale growth + margin = 40 is the box's own diagonal. `charts/rpo-coverage`
  fixes 0–100%, because the plot's top edge is the ceiling it draws.
  `structure/cash-conversion-cycle` fixes 0–180 days, so two years cut together share one
  scale. The fixed scale is published on the region slot (`scale`); everything else is
  scaled by the data, as before.
- **LAW — a walk between two RATES floats; a walk between two LEVELS does not.**
  `figures/margin-walk` goes 15.2% → 13.4% through half-point steps that are four pixels
  tall on a zero-based scale, so its scale fits the walk and its ends are drawn as levels.
  No bar claims a baseline, and the unit line says the axis does not start at zero.
  `figures/arr-bridge` walks a stock of revenue, so its ends are bars from zero.
- **`sectors` in `roles.fragment.json`** names the kind of issuer a plate's *structure*
  presumes. Absent means any sector, which covers every plate before round two.

New renderers: `splitBar` (one bar in parts, which `where-the-cash-went` had always needed
and `rowBars` could not draw), `scatter` (fixed-scale aware), `spreadFill`. Also a `tone`
on `columnBars`, `linePath` and `historyBand` for a second series, and `bridge` ends plus
float. `export.js`'s data layer draws all of these in `--sample`, and review pages now
import that one function instead of keeping their own hand-coded copy.

---

## 6 · Motion

Stroke boil has no source once there are no strokes. The rule survives by a different
mechanism, and it is correct:

> **A data plate's frame breathes and its figures do not.**

- **Host plates:** three frames of **authored micro-offsets** — head rotates ~1.5°, shoulder
  line shifts a pixel or two, blink on the `-blink` strip. Discrete, deliberate, identical
  every loop. Never noise.
- **Data plates:** the frame's rule lines take a 1px authored offset between frames.
  Figures, axes, series and cells do not move. **Anything a viewer reads a value off stays
  pinned.**
- `files.baseIsFrame` holds — the base PNG is byte-identical to `_f01`.

3fps, 3 frames. Values in `design-tokens.json → motion`.

---

## 7 · The contract that must not break

Breaking anything here means nothing renders. Verified present and working as of rebuild-01:

| item | state |
|---|---|
| Manifest schema + `manifest_core.js` emitting slots **verbatim** | ships, unchanged |
| `emit_manifests.mjs --check` exits clean | required on every delivery |
| Slot contract — named slots with `x`/`y`/`w`/`h`, `region: true` on data slots | unchanged |
| `maxChars` derived by `budget.js` from the fonts' `hmtx` table | **verified** — `scripts/fontmetrics.js` regenerates the advance tables. Never authored by hand. |
| No `<text>` nodes anywhere | **verified** — zero in the engine today. Fonts are off in resvg; type is paths. |
| `files.baseIsFrame`, `exportScale: 2` | unchanged |
| Host-anchor solve; `C` single, rig-derived, published once | form unchanged; **new value pending slice 2** |
| `roles.json` as the selection layer | mechanism fixed, contents free |
| `roomHours` `hours`/`episodes` split | kept |
| Both aspects, 16:9 and 9:16 | kept |

**A hand-typed `maxChars` is how `BOTH TRUE` came back empty**, with two strings silently
dropped for being over budget. The derivation is load-bearing and is not touched.

---

### 5.4b Opener rooms (rebuild-23)

A chapter opens on a room with `opener: true`. There are three: `desk-wide`, `board-wide` and
`window-wide`. **It is one room.** A new angle may not add furniture or lose it, so an
opener is never drawn fresh. It is an existing angle's shape list pulled back (`pull()`,
scale 0.8 about the floor centre), with the title card as the only addition.
`window-wide` comes from `window-wall` and `board-wide` from `board-side`. Pulling back
leaves wall above him for a 92×42 card inside the portrait window. The card is the same size
in all three, so a title set once fits any of them.

### 5.5 The data contract lives in the slot table (rebuild-22)

A consumer drawing real data reads the slot table, not the drawing and not the prose.
Four things were only in one or the other; each is now a field:

- **`plot-area.spreadFill`** (two-line plots): `true` where the two lines are rates you
  compare and the gap is a quantity (price against cost); `false` where they are parts
  that add up to the headline (price plus volume), because the area between them is not
  a quantity. The note says the same thing. Unfilled: `price-vs-volume`,
  `net-price-vs-volume`, `traffic-vs-ticket`. **`brand-vs-private-label` fills**: the two
  are compared, and the gap is its callout.
- **`ink`** on every keyed `legend-N` / `row-N`, and **`tone` / `tone2`** on the
  plot-area. The swatch and the field come from one palette key in `key()` /
  `pairedYears`, so they cannot disagree. Ratio pairs key the second series in
  `quiet`; payback plates key the cost line in `attention` (`cac-line.ink`).
- **`scale`** on band slots is the plate's own range (`bandScale`), not the 0–180 default.
- **`scale: [-20, 20]`** and `clamp: true` on every `growth-N` rail marker.

`export.js` dataLayer defaults fill and `tone2` from these fields when the data omits them.

## 8 · Audit — run, with counts, never "as intended"

In `audit.js`, reported with counts. Slice 6, but every rule above was written to be
checkable by one of these, and the list grows as slices find new ways to be wrong — rule
13 arrived with the pose inventory. **Never cite a count for this table; cite the table.**

**A rule reports one of four states, and "did not run" is its own.** `pass`, `FAIL`,
`needs the emitter`, and `DID NOT RUN`. Collapsing the last two into one sentinel is how
rule 16 spent a rebuild reporting itself as not-yet-due while silently failing to execute,
with the summary line counting it as such. **A rule that did not run is louder than a rule
that failed**, because a failure is at least information.

| # | rule |
|---|---|
| 1 | **No gradients.** Zero `<linearGradient>`/`<radialGradient>` in any emitted SVG. |
| 2 | **No opacity shading.** Every `opacity`/`fill-opacity` is exactly 0 or 1. *Enforces §1.* |
| 3 | **Palette closure.** Distinct fills in a plate ⊆ its hour's declared palette. No computed colours. |
| 4 | **Uniform contour.** Every stroke: same width, contour colour. No second pass. |
| 5 | **Type legibility.** Contrast ≥ 4.5:1 sampled behind every title/statement/caption/cell `groundBox`, under `card` **and** `slab`, in **both** hours. |
| 6 | **Twin geometry.** night/dusk twins byte-identical in slot boxes, `floorLineY`, `hostAnchor`. |
| 7 | **Role coherence.** Every host-role member publishes alpha; every framings-role member has no floor line. |
| 8 | **Anchor constant.** `C` identical across every pose and equal to the published value. |
| 9 | **`emit_manifests.mjs --check`** clean. |
| 10 | **No `<text>` nodes.** Zero, anywhere. |
| 11 | **Six flat shapes per room** (§4.3). |
| 12 | **Figure reads against its wall.** Every figure material's `lit` is ≥ 0.10 ΔE (OKLab) from that hour's `wall.lit`, in **both** hours (§2.2a). Not a WCAG ratio — rule 5's metric is the wrong one here. |
| 13 | **Ink inside the published box.** Every coordinate of every path in every pose, against the one box the inventory publishes (§2.5). A pose whose ink leaves it is cropped at composite. |
| 14 | **Anchor survives the portrait window.** Measured per room (§4.4a). An anchor that is fine in landscape can sit half outside the portrait window, and nothing reports it until a vertical cut is assembled. |
| 15 | **Anchored rooms declare a split.** Every room a host can stand in must say which shapes paint in front of him (§4.5), derived as the first `desk`-role shape. |
| 16 | **Every drawn anchor comes from one derivation.** Scans the *rendered* SVG, not the model (§4.4a). A self-consistent model plus one section drawing from a stale source is invisible to any model-level check. |
| 17 | **Band direction per hour.** Night bands sit lighter than their ground, dusk bands darker (§5.1). Backwards is the muddy inversion §5 forbids, and it is invisible one plate at a time. |
| 18 | **Both title treatments legible, both hours.** `card` and `slab` × two hours, sampled against the ground actually behind the box (§5.3). A slab sits on `wall.shade`, a card on `ink.ground` — one measurement cannot cover both. |
| 19 | **The drawn exemption is declared and bounded.** Only the twelve drawn families may opt out of rules 2 and 4, no host or room asset may, and the count is printed (§8.2). |
| 20 | **Every plate slot is filled and within budget.** Content is generated from each plate's own slot table (`engine/content.js`) and every string is checked against that slot's `maxChars`. |
| 21 | **Every override names a slot that exists.** A typo in `content-overrides.json` silently does nothing; this turns it into a failure. |
| 22 | **Every emitted plate has an export entry at both hours.** One code path from model to file (§9). |
| 23 | **No rendered string is wider than its slot box.** `maxChars` is a character budget, not a width one; where a published budget and the box disagree the tighter wins (§8.3). |
| 24 | **Every plate is reachable and explains itself.** A purpose and a caution in `roles.fragment.json`, or a stated way it is reached. |
| 25 | **Every talk, idle and blink strip actually moves.** Distinct frame hashes off the exported files. |
| 26 | **Every exported file frames its own ink**, within a 10% bleed per edge. |
| 27 | **He stands clear of the front layer, composited.** Every pose that fits the room, placed by the contract: no head under a front shape, at most 10% of him above the desk top (§4.5). |
| 28 | **A chapter title has somewhere to land.** At least one opener room; every title inside its card, the card inside the portrait window and clear of him (§5.3). |
| 30 | **One room: no angle adds furniture** (§5.4b). At most one desk, monitor, desk lamp and lit opening per angle; drawing agrees with `KitModel.PLAN.sees`; any angle outside the drawn fourteen is pulled from one. |
| 29 | **The data contract is published, not implied** (§5.5). Every legend/row key publishes `ink`; a second series' `tone2` equals the ink its key shows; every two-line plot publishes a boolean `spreadFill` that its note agrees with; every band or marker region whose note names a scale carries that range in `scale`. |

---

## 9 · Open, and who decides

Settled items are kept with their outcome rather than deleted, so a later reader can see
what was decided and when — §8.1 applies here too: cite the slice, never a recollection.

| | |
|---|---|
| **The part set as geometry** | **STILL OPEN — the standing risk.** The figure paths are the one part of this rebuild that is a drawing rather than a number. Redrawn at rebuild-02 against the character sheet in `host/manifest.json`; the swap path stays nine-plus-five paths into the same table, so replacing them with an illustrator's costs no engine change. |
| **Wordmark and strapline** | **STILL OPEN.** Both read ``content-overrides.json → _wordmark``. Not blocking — the title slot is built and measured (§S2.2 of the review surface), so a word drops straight in. |
| **Room count** | SETTLED, slice 4 — 8 angles, 32 plates (§4.4, §4.4a). |
| **Palettes and proportion table** | SETTLED, slice 2 sign-off. Seven widths moved at rebuild-02 (§2.1); both `ink.quiet` values moved at rebuild-03 when audit rule 5 caught them under the floor. |
| **Pose inventory** | SETTLED, slice 3 — 10 poses, 11 frames each, 220 figure plates (§3.5). |
| **New `C`** | SETTLED, slice 2 — `C = 0.5583`, derived from the proportion table (§2.5). |
| **Stubble** | DROPPED, rebuild-02 (§2). A palette limit, not a taste call: "faint" needs a value one step off the skin and the 13-role palette has none. Costs a 14th role to reinstate. |## 8.3 · Type capacity has one owner, and it is budget.js

`engine/budget.js` owns this. It derives a per-slot capacity from the box using the
shipped fonts' own `hmtx` advances — Courier Prime exactly 0.5996 em for every glyph,
Archivo Narrow per character class and per weight (its lowercase runs 0.31 em) plus
tracking and a safety factor — and `Plate.manifest()` runs it over every plate, so a
re-emit cannot drift. A wrapping slot gets `maxCharsPerLine` × `maxLines`; a single-line
slot gets `maxChars`.

**LAW — a published budget is authoritative. Do not write a second model.**

### The retraction (rebuild-15)

This section previously said *"314 slots publish a budget wider than their own geometry"*
and cited `structure/sensitivity` promising seven characters in a box that holds six.
**That was wrong.** It was measured with a flat 0.54 em estimate written without reading
`budget.js`, and compared against the kit's real-metric number. Re-measured with the real
metrics the count is **0** — seven characters do fit that box at role size 25. The
published budgets were right and the measurement was wrong.

Two consequences, both fixed:

- Across 1,778 slots the estimate was tighter than the real metric on **330**, so it was
  truncating strings that fit. `content.js` now trusts a published budget and derives one
  only where a slot carries none, using `budget.js`'s own `perChar`.
- It read only `maxChars`, so every wrapping box was treated as one line. A three-line
  headline budgeted 36 characters and a four-line hook card 23, both truncating sentences
  that fit comfortably. A wrapping budget is `maxCharsPerLine` × `maxLines`.

What survives from the original finding is the part that was real: **68 strings did render
outside their boxes**, because `fit()` only trimmed where a slot published a budget and
many publish none. Audit rule 23 asserts the rendered invariant with the real metrics.

**LAW — derive the point size from the box, never the reverse.** `plates.js` states it in
`bigNumber`: *"picking a size first and hoping is how you get a 7-character value running
off the plate."* Two round-one plates whose whole job is one number repeated that mistake:
a 240 pt figure in a 698 px column budgets four characters and cannot hold "−18.4%".
`size = width / (chars × advance)`, capped at the preferred size.

---


