/* Dennis v2 — the library, declared.

   Every shipping asset, with the author call and the seed that draws it. This
   file exists because the first two batches were built by throwaway calls: the
   manifests recorded geometry but not the seed, so "reproduces byte-for-byte
   from PLATES.<author>({key, seed})" was true in principle and unrunnable in
   practice. Now the whole library is one function call, and the seed is written
   into every manifest entry.

   Board demos (board/) are deliberately absent: they carry drawn data and are
   illustrations for the palette board, not plates a shot can cut to. */
(function (g) {
  const A = (dir, key, author, args, seed) => ({ dir, key, author, args: args || {}, seed: seed == null ? 1 : seed });

  // WHICH SURFACE A THING IS DRAWN ON
  //
  // A surface goes UNDER the drawing. The legal pad's ruling is furniture of the
  // page — blue rules and a red margin — and on a room plate it draws straight
  // through the desk, the props and the host: a rule crossing a man's chest is
  // not a surface he is standing on, it is a line over the top of him. So the
  // default is the plain night card, and the pad is reserved for the things that
  // ARE notes, where ruling is the whole point of the object.
  const NOTE_SURFACES = {
    "cards/criteria-16x9": "legal-pad",
    "cards/criteria-9x16": "legal-pad",
    "paper/headline-band-t3-16x9": "legal-pad",
    "paper/headline-band-t3-9x16": "legal-pad",
  };
  const surfaceOf = (key) => NOTE_SURFACES[key] || "night-card";

  // WARDROBE — an episode-level choice, not a redraw.
  //
  // He hosts every episode, and one outfit across a whole series reads as a
  // uniform. So hostFigure takes an `outfit`, and the same pose, seed and
  // geometry render in any of five: same man, different clothes. The shipped
  // 30 frames are the default ("shirt"); the pipeline renders another outfit by
  // passing it through, and every frame of one episode must use the SAME value or
  // he changes clothes mid-sentence.
  //
  // All five keep the two things the tonal system depends on: a mid-to-dark torso
  // so he separates from a pale wall, and trousers as the darkest cloth on the
  // plate. Vary the hue and the detail, never the value.
  const OUTFITS = ["shirt", "cardigan", "rolled", "jumper", "gilet"];
  const L16 = { w: 1920, h: 1080 }, P916 = { w: 1080, h: 1920 };
  const both = (dir, base, author, args, seed) => [
    A(dir, `${base}-16x9`, author, Object.assign({}, args, L16), seed),
    A(dir, `${base}-9x16`, author, Object.assign({}, args, P916), seed),
  ];

  const ANN = [
    ["scrawl-oval-wide", 1200, 230], ["scrawl-oval-tight", 340, 150],
    ["underline-swipe", 1000, 140], ["underline-tight", 300, 90],
    ["strike-out", 320, 90], ["box-scrawl", 1000, 320],
    ["bracket-rows", 220, 700], ["arrow-elbow", 760, 520],
    ["caret-note", 620, 300], ["tick-marks", 720, 220],
  ];

  const POSES = ["leaning-on-desk", "hands-in-pockets", "holding-a-page", "pointing-down-at-desk", "head-in-hands", "walking-out-of-frame"];
  // Shot size, as camera distance rather than as a crop. See the LIB entry.
  const HOST_FRAMINGS = ["close-up", "medium"];
  // base 0, talk_f01 1, talk_f02 2, idle_f01 3, idle_f02 4 — the boil index is
  // the whole difference between them, plus an open mouth on talk_f01 and a
  // 3-unit bob on idle_f02. n=0 is the identity, so the base plate is the pose.
  // A MOTION STRIP IS ONE ASSET, not two files pretending to be two assets.
  //
  // The talk and idle pairs shipped as four separate static assets per pose, each
  // frameCount 1, playback "static" — so a generic player had nothing to play. A
  // strip is one asset with N frames, a playback mode and an fps; the frames are
  // files inside it. That is the shape the player already understands, and it is
  // what `frames` in the manifest is for.
  //
  // AND THE BASE POSE BOILS TOO. It was declared static here — one frame at boil
  // 0, on the reasoning that n=0 is the identity so the base plate is the pose.
  // That reasoning is about the drawing; the shot is what matters, and in a shot
  // every other non-data plate in the frame is moving. A frozen host standing in a
  // boiling room does not read as a held pose, it reads as a still photograph
  // pasted onto a cartoon. So the base pose is a two-frame loop at 2fps like the
  // rest of the library, and the shipped files and manifests have said so for two
  // revisions — this declaration was the last place still claiming otherwise,
  // which made the reproduce claim false for exactly six of 113 assets.
  const HOST_STRIPS = [
    { suffix: "", playback: "loop", fps: 2, frames: [
      { tag: "_f01", args: { mouthOpen: false, bob: 0, boil: 1 } },
      { tag: "_f02", args: { mouthOpen: false, bob: 0, boil: 2 } },
    ] },
    { suffix: "-talk", playback: "loop", fps: 8, frames: [
      { tag: "_f01", args: { mouthOpen: true, bob: 0, boil: 1 } },
      { tag: "_f02", args: { mouthOpen: false, bob: 0, boil: 2 } },
    ] },
    { suffix: "-idle", playback: "loop", fps: 4, frames: [
      { tag: "_f01", args: { mouthOpen: false, bob: 0, boil: 3 } },
      { tag: "_f02", args: { mouthOpen: false, bob: 3, boil: 4 } },
    ] },
  ];

  // THE BOIL. Everything that is not a data plate moves at two frames, 1–1.5% of
  // line movement — the room and the annotations were specified that way and both
  // shipped frozen. The mechanism is the same one the host frames already use:
  // hand.js takes a seed offset, so frame 2 is the identical drawing re-wobbled.
  // A data plate does NOT boil: a figure that moves is a figure being re-read.
  const DATA_FAMILIES = ["tables", "figures", "charts", "peers", "structure", "cycles"];

  // AND ONE OVERLAY, FOR THE SAME REASON THE DATA FAMILIES DO NOT BOIL.
  // overlays/row-band is not a plate the eye reads on its own — it composites
  // INTO a band-N slot on a numbers sheet, behind figures that are deliberately
  // still. The static rule exists precisely to stop movement under type that is
  // being read, and a boiling band under a frozen row breaks it from the other
  // side: the plate obeys the rule, the thing drawn on top of it does not.
  // It also takes the worst of the stretch — up to 3.75x in y on the 3-row
  // sheet — so it was the loudest thing in the frame it was meant to sit behind.
  const NO_BOIL_KEYS = ["overlays/row-band"];
  const boils = (dir, key) => DATA_FAMILIES.indexOf(dir) < 0 && NO_BOIL_KEYS.indexOf(key) < 0;

  // AUTHORED BOIL AMPLITUDE, PER ASSET, in canvas units on the plate.
  //
  // The default is 2.0 and almost everything keeps it: a plate composited at its
  // authored size boils at what it declares. These are the assets that are SOLVED
  // onto a target, where the frame sees amp x solve — so the authored figure is
  // the ~2 units that should survive, divided by the solve each one actually gets.
  // The marks are annotations, whose whole job is to be stretched onto whatever
  // they wrap; the headline band is the one paper plate that gets fitted rather
  // than placed. Every figure here was set from the solve range in the episode
  // file, not picked to make a number look better.
  // Each figure is the default 2.0 scaled by (target / measured-in-frame), where
  // measured-in-frame is the pipeline's post-solve reading and the target is 1.75
  // units — the middle of the band the rest of the library sits in. Response is
  // linear (verified: amp 2.0/1.0/0.5/0.25 gives 1.51/0.75/0.38/0.19 on the
  // plate), so the arithmetic is honest rather than a tuning knob turned by eye.
  const BOIL_AMP = {
    "annotations/underline-swipe": 0.32,  // 11.0 in frame -> 1.75
    "annotations/strike-out": 0.58,       // 6.0 -> 1.75
    "annotations/underline-tight": 0.78,  // 4.5 -> 1.75
    // paper/headline-band-t1 was clamped here in patch7 and is NOT any more. It
    // was never over-boiled: a run-width metric read one stray element as large
    // displacement on a plate that is otherwise frozen, and clamping it made a
    // nearly-still plate stiller. Back on the 2.0 default. Its real problem is
    // COVERAGE, not amplitude - see AUDIT.coverage().
  };
  const boilAmpOf = (key) => BOIL_AMP[key];

  const ANGLES = ["wide", "wide-tight", "desk-front", "desk-corner", "from-behind-the-monitor", "whiteboard-wall", "printer-corner", "doorway"];

  // REVISION 05 — THE CAMERA ANGLES.
  //
  // The eight above are eight arrangements of furniture photographed from one
  // position: all eye-level, all straight-on, the floor line at the same height in
  // every one, no edge running away from the viewer. Cutting between them reads as
  // props sliding around on a shelf, and a long video built only from them is one
  // static take with the set dressing changing.
  //
  // These three are camera POSITIONS rather than furniture arrangements, and each
  // uses one of the variables the first eight left on the table: perspective
  // (corner-perspective), a low camera (low-desk-height), a high one
  // (high-desk-down). They are declared separately so the distinction stays
  // visible in the file rather than being buried in a list of eleven strings.
  //
  // Not on this list: a tighter framing of an existing angle. The plates are
  // 3840x2160 and the video is 1920x1080, so a crop out of a plate already IS a
  // native-resolution medium shot — the renderer gets shot size for free. What it
  // cannot crop into existence is a different camera position.
  const CAMERA_ANGLES = ["corner-perspective", "low-desk-height", "high-desk-down"];

  const LIB = [].concat(
    ANN.map((a) => A("annotations", `annotations/${a[0]}`, "annotation", { type: a[0], w: a[1], h: a[2] })),

    both("cards", "cards/definition", "definitionCard", {}, 3),
    both("cards", "cards/quote-pull", "quotePull", {}),
    both("cards", "cards/criteria", "criteriaCard", {}),

    both("charts", "charts/line-6y", "chartFrame", { type: "line-6y" }),
    both("charts", "charts/line-dense", "chartFrame", { type: "line-dense" }),
    both("charts", "charts/bars-6y", "chartFrame", { type: "bars-6y" }),

    both("figures", "figures/big-number-l1", "bigNumber", { layout: 1 }, 3),
    both("figures", "figures/big-number-l2", "bigNumber", { layout: 2 }, 3),
    both("figures", "figures/big-fraction", "bigFraction", {}),
    both("figures", "figures/compare-side", "compare", { mode: "side" }),
    both("figures", "figures/compare-stacked", "compare", { mode: "stacked" }),

    both("frames", "frames/media-frame-t1", "mediaFrame", { treatment: 1 }),
    both("frames", "frames/media-frame-t2", "mediaFrame", { treatment: 2 }),
    both("frames", "frames/media-frame-t3", "mediaFrame", { treatment: 3 }),
    both("frames", "frames/capture-frame", "captureFrame", {}),

    POSES.reduce((acc, pose) => acc.concat(HOST_STRIPS.map(function (st) {
      const it = A("host", `host/${pose}${st.suffix}`, "hostFigure", Object.assign({ pose: pose }, P916, st.frames[0].args));
      it.strip = st;
      return it;
    })), []),

    // REVISION 05 — THE TWO FRAMINGS HE DID NOT HAVE.
    //
    // Six poses, all full-body, all the same size in frame: the shot a forty
    // minute video needs most is his face, and it did not exist. These matter more
    // than a seventh pose would.
    //
    // They are DRAWN, not cropped, and that is the one place in this library where
    // a tighter framing is not free. Everywhere else the plates are 3840x2160
    // against a 1920x1080 video, so the renderer crops a native-resolution medium
    // out of any wide. Here the full figure's head slot is 176x194 canvas units,
    // and filling a 1080-tall frame with it is a 6x upscale of a line drawing. The
    // head has to be drawn AT close-up size for the jaw, the brow and the mouth to
    // carry line weight.
    //
    // Their canvases are not 9:16, because a head and shoulders in a 9:16 box is
    // mostly empty box. exportScale is still 2, as it is for every family.
    HOST_FRAMINGS.reduce((acc, fr) => acc.concat(HOST_STRIPS.map(function (st) {
      const size = fr === "close-up" ? { w: 1080, h: 1080 } : { w: 1080, h: 1440 };
      const it = A("host", `host/${fr}${st.suffix}`, "hostHead", Object.assign({ framing: fr }, size, st.frames[0].args));
      it.strip = st;
      return it;
    })), []),

    // SIDE-GLANCE. He faced camera in every frame regardless of what was on
    // screen, so he could never look at the thing he was discussing.
    //
    // CLOSE FRAMINGS ONLY, and that is the whole reason this is twelve assets
    // rather than thirty-six. An eye-direction change is a pupil moving a few
    // canvas units; at the size the full figure occupies in frame it does not
    // survive, exactly as the leg asymmetry does not. Spending eighteen plates on
    // a change nobody can see is the mistake this list has avoided twice.
    //
    // Left and right are separate artwork, not one plate flipped: the face is
    // asymmetric on purpose now — dropped mouth corner, slept-on hair, crooked
    // glasses, uneven stubble — so a mirror would flip all of it and read as a
    // different man looking the other way.
    HOST_FRAMINGS.reduce((acc, fr) => acc.concat([["left", -1], ["right", 1]].reduce((a2, gl) =>
      a2.concat(HOST_STRIPS.map(function (st) {
        const size = fr === "close-up" ? { w: 1080, h: 1080 } : { w: 1080, h: 1440 };
        const it = A("host", `host/${fr}-glance-${gl[0]}${st.suffix}`, "hostHead",
          Object.assign({ framing: fr, glance: gl[1] }, size, st.frames[0].args));
        it.strip = st;
        return it;
      })), [])), []),

    // THE ROBE. One strip, and it goes on the MEDIUM: a garment needs waist-up to
    // show at all, and in head-and-shoulders you would see a collar and nothing
    // else. The writing now calls for one outfit per episode, so a second option
    // is what makes that rule real rather than nominal.
    HOST_STRIPS.map(function (st) {
      const it = A("host", `host/medium-robe${st.suffix}`, "hostHead",
        Object.assign({ framing: "medium", outfit: "robe", w: 1080, h: 1440 }, st.frames[0].args));
      it.strip = st;
      return it;
    }),

    [A("overlays", "overlays/row-band", "rowBand", { w: 1744, h: 112 })],

    both("paper", "paper/headline-band-t1", "headlineBand", { treatment: 1 }),
    both("paper", "paper/headline-band-t2", "headlineBand", { treatment: 2 }),
    both("paper", "paper/headline-band-t3", "headlineBand", { treatment: 3 }),

    ANGLES.reduce((acc, angle) => acc.concat(both("room", `room/${angle}`, "room", { angle: angle })), []),
    CAMERA_ANGLES.reduce((acc, angle) => acc.concat(both("room", `room/${angle}`, "room", { angle: angle })), []),
    both("room", "room/wall-of-calls", "wallOfCalls", {}),

    [1, 2, 3].map((t) => A("shorts", `shorts/hook-card-t${t}`, "hookCard", Object.assign({ treatment: t }, P916))),

    both("structure", "structure/both-true", "bothTrue", {}, 3),
    both("structure", "structure/unit-ladder", "unitLadder", {}),
    both("structure", "structure/closing", "closingPlate", {}),
    both("structure", "structure/row-spotlight", "rowSpotlight", {}),
    // 16:9 only by design — a left-to-right process has no portrait form
    [A("structure", "structure/flow-16x9", "flowPlate", L16)],
    both("structure", "structure/timeline", "timeline", {}),

    [
      // The brief asked for four row counts in both aspects and the first batch
      // shipped two. A four-row script had nothing to use in 16:9 and a
      // three-row short had nothing at all. Six periods throughout.
      3, 4, 5, 6,
    ].reduce((acc, r) => acc.concat([
      A("tables", `tables/numbers-sheet-${r}r-16x9`, "numbersSheet", Object.assign({ rows: r }, L16)),
      A("tables", `tables/numbers-sheet-${r}r-9x16`, "numbersSheet", Object.assign({ rows: r }, P916)),
    ]), []),
    [
      A("tables", "tables/numbers-sheet-6r-spark-16x9", "numbersSheet", Object.assign({ rows: 6, spark: true }, L16), 5),
      A("tables", "tables/numbers-sheet-4r-spark-9x16", "numbersSheet", Object.assign({ rows: 4, spark: true }, P916), 5),
    ],
    both("tables", "tables/cash-flow", "cashFlow", {}),

    // THE VALUATION CHAPTER. Two plates, and neither is a variant of anything
    // already here.
    //
    // The multiples strip is the inverse of peers/peer-strip and that is why it
    // is a new author rather than an argument to that one: the peer strip's rows
    // are companies, this one's rows are metrics. Six rows in 16:9, three in
    // 9:16 — the short's cheap-or-trap beat is the same picture with less in it,
    // not the sheet scaled down.
    [
      A("tables", "tables/multiples-strip-16x9", "multiplesStrip", L16, 21),
      A("tables", "tables/multiples-strip-9x16", "multiplesStrip", P916, 21),
    ],
    // 16:9 only by design, for the same reason the flow plate is: three figures
    // side by side need the width, and a trailing-to-forward walk is not a
    // seventy-five-second beat.
    [A("structure", "structure/multiple-bridge-16x9", "multipleBridge", L16, 23)],

    both("peers", "peers/peer-strip", "peerStrip", {}, 77),
    both("cycles", "cycles/cycle-frame", "cycleFrame", {}, 88)
  );

  // Families that ship a downscaled thumbnail instead of a contact sheet: their
  // plates are too heavy to inline (a room is ~1.4 MB of vector). A thumbnail is
  // always a real downscale of the delivered plate, never a redraw at tile size.
  const THUMBS = { host: 300, room: 320 };

  // THE FAMILY HEADERS, which are the part of a manifest a human reads first and
  // the part that had nothing checking it: they were typed into whichever writer
  // script emitted the family. Declared here, beside the assets they describe,
  // so RENDER.manifestFor emits a complete file — header and assets from one
  // source — and a delta pack's manifest is a REPLACE rather than a patch.
  // ONE note, not fourteen typed copies. It describes the compositor that
  // exists — which ERRORS on an over-budget fill rather than shrinking type to
  // fit — and the derivation in engine/budget.js that every manifest's numbers
  // now come from. It was already wrong once by being edited in one place.
  const MAXCHARS_NOTE = "maxChars is a HARD LIMIT, not editorial guidance. The compositor's audit raises an ERROR on any fill longer than the budget for the box it lands in, and an over-budget shot does not render — so a number authored beside the point size instead of measured off the box is a defect in both directions: too loose and it waves through copy that collides with the rule beside it, too tight and it stops a short that would have fitted. Every budget in this file is now DERIVED — box width divided by the per-character advance of the real face, read from the font's own hmtx table. Courier Prime is monospaced at 0.5996em (regular and bold identical), so its numbers are exact. Archivo Narrow is proportional, so its advance is a frequency-weighted mean over the character class the role actually sets — 0.383em mixed-case, 0.479em uppercase-transformed, 0.439em figures — instanced on the wght axis for 500/600/700 (a 700 runs 3.9% wider than a 400) and carrying a 4% allowance, which makes it a fair average rather than a promise about one wide string. BUDGETS LIVE ON THE SLOT: slots[name].maxChars is the number for THAT box and is what the audit reads, because one role is set in boxes of different widths on the same plate and a single number per role cannot be right in both. The role-level maxChars is the FLOOR — the narrowest slot on this plate that sets the role — so a reader that only knows about roles stays inside every box. maxLines is capped by box height at the compositor's 1.16em line pitch, and maxCharsPerLine is the same width derivation; line breaking itself is by measured width, never by character count. A role declared in typeRoles that no slot on the plate sets keeps its authored number and is listed in audit/budgets.json.";

  const FAMILY_NOTES = {
    "annotations": {
      "family": "annotations",
      "engine": "engine/hand.js + engine/plates.js, declared in engine/build.js (manifest emitted by the drawing call)",
      "coordinateOrigin": "top-left of canvas",
      "units": "canvas units — multiply by exportScale for delivered pixels. exportScale is 2 for the WHOLE library: one scale, every family, so a shot can mix a room, a card and an annotation without a resample step.",
      "bakedText": false,
      "reproduce": "PLATES.<author>({ key, w, h, pal, seed, … }) — see engine/build.js for the exact call and seed of every asset in this family",
      "dataPolicy": "alpha cut-outs, no ground: the mark is composited onto whatever it wraps",
      "slotKinds": {
        "region": "what the mark wraps or points at (area) — solved onto the target, never written into",
        "caption": "the mark's own words (note), set in the caption role declared on every mark in this family"
      },
      "surface": "Bound per asset in engine/build.js (NOTE_SURFACES), not chosen by the caller. A surface goes UNDER the drawing: the legal pad's blue rules and red margin are furniture of the page, and on a room plate they draw straight through the desk, the props and the host. So the default is the plain night card, and the pad is reserved for assets that ARE notes, where the ruling is the point of the object.",
      "motion": "Two frames, loop at 2fps, ~2 canvas units of movement per point. The boil is HAND.setBoil — the same drawing re-wobbled, with plate layout and paper grain deliberately held still. The base file IS frame one (identical bytes), so entering or leaving the loop is silent.",
      "exportScale": 2,
      "scaleAuthority": "engine/audit.js EXPORT_SCALE = 2. Not a per-family choice and not a caller argument: Plate.manifest() ignores any exportScale passed to it, because that argument is how a per-family scale gets in — a caller hands one plate its own scale, the manifest faithfully records it, and a shot mixing a room with a card needs a resample step mid-composite. 2 is the floor for the two things this library is asked to do: a 16:9 room filling a 9:16 frame, and a push-in on a card. 1 has headroom for neither.",
      "frameShape": "frames[] entries are OBJECTS, not filenames — {tag, svg, png, boil, …} — and this is deliberate. A bare filename cannot say what a frame IS, so a player had to parse meaning out of a string suffix. Read frames[i].png, never a constructed name.",
      "baseFileRule": "files.png / files.svg are the SAME BYTES as frames[0] (files.baseIsFrame names which). A base file that is its own render pops on the first frame of the loop. Verify with AUDIT — do not assume.",
      "boilPolicy": "Boil amplitude is declared per asset in engine/build.js BOIL_AMP, default 2.0 canvas units. Solve scale multiplies it: an asset stretched onto a target boils at amp x solve in the frame, which is the same property the inkWeight check already enforces for line weight. Do not compare a plate-side boil figure with a frame-side one.",
      "maxCharsNote": MAXCHARS_NOTE
    },
    "cards": {
      "family": "cards",
      "engine": "engine/hand.js + engine/plates.js, declared in engine/build.js (manifest emitted by the drawing call)",
      "coordinateOrigin": "top-left of canvas",
      "units": "canvas units — multiply by exportScale for delivered pixels. exportScale is 2 for the WHOLE library: one scale, every family, so a shot can mix a room, a card and an annotation without a resample step.",
      "bakedText": false,
      "reproduce": "PLATES.<author>({ key, w, h, pal, seed, … }) — see engine/build.js for the exact call and seed of every asset in this family",
      "surface": "Bound per asset in engine/build.js (NOTE_SURFACES), not chosen by the caller. A surface goes UNDER the drawing: the legal pad's blue rules and red margin are furniture of the page, and on a room plate they draw straight through the desk, the props and the host. So the default is the plain night card, and the pad is reserved for assets that ARE notes, where the ruling is the point of the object.",
      "motion": "Two frames, loop at 2fps, ~2 canvas units of movement per point. The boil is HAND.setBoil — the same drawing re-wobbled, with plate layout and paper grain deliberately held still. The base file IS frame one (identical bytes), so entering or leaving the loop is silent.",
      "exportScale": 2,
      "scaleAuthority": "engine/audit.js EXPORT_SCALE = 2. Not a per-family choice and not a caller argument: Plate.manifest() ignores any exportScale passed to it, because that argument is how a per-family scale gets in — a caller hands one plate its own scale, the manifest faithfully records it, and a shot mixing a room with a card needs a resample step mid-composite. 2 is the floor for the two things this library is asked to do: a 16:9 room filling a 9:16 frame, and a push-in on a card. 1 has headroom for neither.",
      "frameShape": "frames[] entries are OBJECTS, not filenames — {tag, svg, png, boil, …} — and this is deliberate. A bare filename cannot say what a frame IS, so a player had to parse meaning out of a string suffix. Read frames[i].png, never a constructed name.",
      "baseFileRule": "files.png / files.svg are the SAME BYTES as frames[0] (files.baseIsFrame names which). A base file that is its own render pops on the first frame of the loop. Verify with AUDIT — do not assume.",
      "maxCharsNote": MAXCHARS_NOTE
    },
    "charts": {
      "family": "charts",
      "engine": "engine/hand.js + engine/plates.js, declared in engine/build.js (manifest emitted by the drawing call)",
      "coordinateOrigin": "top-left of canvas",
      "units": "canvas units — multiply by exportScale for delivered pixels. exportScale is 2 for the WHOLE library: one scale, every family, so a shot can mix a room, a card and an annotation without a resample step.",
      "bakedText": false,
      "reproduce": "PLATES.<author>({ key, w, h, pal, seed, … }) — see engine/build.js for the exact call and seed of every asset in this family",
      "dataPolicy": "plate draws axes/ticks/gridlines/frame only; code draws the data path inside plot-area",
      "slotKinds": {
        "container": "a region other slots legitimately sit inside (plot-area)",
        "region": "a graphic region for code to draw into, not a text box (bar-N, point-N, mark-*)"
      },
      "surface": "Bound per asset in engine/build.js (NOTE_SURFACES), not chosen by the caller. A surface goes UNDER the drawing: the legal pad's blue rules and red margin are furniture of the page, and on a room plate they draw straight through the desk, the props and the host. So the default is the plain night card, and the pad is reserved for assets that ARE notes, where the ruling is the point of the object.",
      "motion": "Two frames, loop at 2fps, ~2 canvas units of movement per point. The boil is HAND.setBoil — the same drawing re-wobbled, with plate layout and paper grain deliberately held still. The base file IS frame one (identical bytes), so entering or leaving the loop is silent.",
      "exportScale": 2,
      "scaleAuthority": "engine/audit.js EXPORT_SCALE = 2. Not a per-family choice and not a caller argument: Plate.manifest() ignores any exportScale passed to it, because that argument is how a per-family scale gets in — a caller hands one plate its own scale, the manifest faithfully records it, and a shot mixing a room with a card needs a resample step mid-composite. 2 is the floor for the two things this library is asked to do: a 16:9 room filling a 9:16 frame, and a push-in on a card. 1 has headroom for neither.",
      "frameShape": "frames[] entries are OBJECTS, not filenames — {tag, svg, png, boil, …} — and this is deliberate. A bare filename cannot say what a frame IS, so a player had to parse meaning out of a string suffix. Read frames[i].png, never a constructed name.",
      "baseFileRule": "files.png / files.svg are the SAME BYTES as frames[0] (files.baseIsFrame names which). A base file that is its own render pops on the first frame of the loop. Verify with AUDIT — do not assume.",
      "maxCharsNote": MAXCHARS_NOTE
    },
    "cycles": {
      "family": "cycles",
      "engine": "engine/hand.js + engine/plates.js, declared in engine/build.js (manifest emitted by the drawing call)",
      "coordinateOrigin": "top-left of canvas",
      "units": "canvas units — multiply by exportScale for delivered pixels. exportScale is 2 for the WHOLE library: one scale, every family, so a shot can mix a room, a card and an annotation without a resample step.",
      "bakedText": false,
      "reproduce": "PLATES.<author>({ key, w, h, pal, seed, … }) — see engine/build.js for the exact call and seed of every asset in this family",
      "dataPolicy": "plate draws the plot furniture, the moment anchors and the ties; engine/series.js draws the path inside `path` from the data",
      "slotKinds": {
        "region": "a graphic region for code to draw into (path), or a figure whose position only the data knows (trough)"
      },
      "surface": "Bound per asset in engine/build.js (NOTE_SURFACES), not chosen by the caller. A surface goes UNDER the drawing: the legal pad's blue rules and red margin are furniture of the page, and on a room plate they draw straight through the desk, the props and the host. So the default is the plain night card, and the pad is reserved for assets that ARE notes, where the ruling is the point of the object.",
      "motion": "Two frames, loop at 2fps, ~2 canvas units of movement per point. The boil is HAND.setBoil — the same drawing re-wobbled, with plate layout and paper grain deliberately held still. The base file IS frame one (identical bytes), so entering or leaving the loop is silent.",
      "exportScale": 2,
      "scaleAuthority": "engine/audit.js EXPORT_SCALE = 2. Not a per-family choice and not a caller argument: Plate.manifest() ignores any exportScale passed to it, because that argument is how a per-family scale gets in — a caller hands one plate its own scale, the manifest faithfully records it, and a shot mixing a room with a card needs a resample step mid-composite. 2 is the floor for the two things this library is asked to do: a 16:9 room filling a 9:16 frame, and a push-in on a card. 1 has headroom for neither.",
      "frameShape": "frames[] entries are OBJECTS, not filenames — {tag, svg, png, boil, …} — and this is deliberate. A bare filename cannot say what a frame IS, so a player had to parse meaning out of a string suffix. Read frames[i].png, never a constructed name.",
      "baseFileRule": "files.png / files.svg are the SAME BYTES as frames[0] (files.baseIsFrame names which). A base file that is its own render pops on the first frame of the loop. Verify with AUDIT — do not assume.",
      "maxCharsNote": MAXCHARS_NOTE
    },
    "figures": {
      "family": "figures",
      "engine": "engine/hand.js + engine/plates.js, declared in engine/build.js (manifest emitted by the drawing call)",
      "coordinateOrigin": "top-left of canvas",
      "units": "canvas units — multiply by exportScale for delivered pixels. exportScale is 2 for the WHOLE library: one scale, every family, so a shot can mix a room, a card and an annotation without a resample step.",
      "bakedText": false,
      "reproduce": "PLATES.<author>({ key, w, h, pal, seed, … }) — see engine/build.js for the exact call and seed of every asset in this family",
      "surface": "Bound per asset in engine/build.js (NOTE_SURFACES), not chosen by the caller. A surface goes UNDER the drawing: the legal pad's blue rules and red margin are furniture of the page, and on a room plate they draw straight through the desk, the props and the host. So the default is the plain night card, and the pad is reserved for assets that ARE notes, where the ruling is the point of the object.",
      "motion": "Two frames, loop at 2fps, ~2 canvas units of movement per point. The boil is HAND.setBoil — the same drawing re-wobbled, with plate layout and paper grain deliberately held still. The base file IS frame one (identical bytes), so entering or leaving the loop is silent.",
      "exportScale": 2,
      "scaleAuthority": "engine/audit.js EXPORT_SCALE = 2. Not a per-family choice and not a caller argument: Plate.manifest() ignores any exportScale passed to it, because that argument is how a per-family scale gets in — a caller hands one plate its own scale, the manifest faithfully records it, and a shot mixing a room with a card needs a resample step mid-composite. 2 is the floor for the two things this library is asked to do: a 16:9 room filling a 9:16 frame, and a push-in on a card. 1 has headroom for neither.",
      "frameShape": "frames[] entries are OBJECTS, not filenames — {tag, svg, png, boil, …} — and this is deliberate. A bare filename cannot say what a frame IS, so a player had to parse meaning out of a string suffix. Read frames[i].png, never a constructed name.",
      "baseFileRule": "files.png / files.svg are the SAME BYTES as frames[0] (files.baseIsFrame names which). A base file that is its own render pops on the first frame of the loop. Verify with AUDIT — do not assume.",
      "maxCharsNote": MAXCHARS_NOTE
    },
    "frames": {
      "family": "frames",
      "engine": "engine/hand.js + engine/plates.js, declared in engine/build.js (manifest emitted by the drawing call)",
      "coordinateOrigin": "top-left of canvas",
      "units": "canvas units — multiply by exportScale for delivered pixels. exportScale is 2 for the WHOLE library: one scale, every family, so a shot can mix a room, a card and an annotation without a resample step.",
      "bakedText": false,
      "reproduce": "PLATES.<author>({ key, w, h, pal, seed, … }) — see engine/build.js for the exact call and seed of every asset in this family",
      "surface": "Bound per asset in engine/build.js (NOTE_SURFACES), not chosen by the caller. A surface goes UNDER the drawing: the legal pad's blue rules and red margin are furniture of the page, and on a room plate they draw straight through the desk, the props and the host. So the default is the plain night card, and the pad is reserved for assets that ARE notes, where the ruling is the point of the object.",
      "motion": "Two frames, loop at 2fps, ~2 canvas units of movement per point. The boil is HAND.setBoil — the same drawing re-wobbled, with plate layout and paper grain deliberately held still. The base file IS frame one (identical bytes), so entering or leaving the loop is silent.",
      "exportScale": 2,
      "scaleAuthority": "engine/audit.js EXPORT_SCALE = 2. Not a per-family choice and not a caller argument: Plate.manifest() ignores any exportScale passed to it, because that argument is how a per-family scale gets in — a caller hands one plate its own scale, the manifest faithfully records it, and a shot mixing a room with a card needs a resample step mid-composite. 2 is the floor for the two things this library is asked to do: a 16:9 room filling a 9:16 frame, and a push-in on a card. 1 has headroom for neither.",
      "frameShape": "frames[] entries are OBJECTS, not filenames — {tag, svg, png, boil, …} — and this is deliberate. A bare filename cannot say what a frame IS, so a player had to parse meaning out of a string suffix. Read frames[i].png, never a constructed name.",
      "baseFileRule": "files.png / files.svg are the SAME BYTES as frames[0] (files.baseIsFrame names which). A base file that is its own render pops on the first frame of the loop. Verify with AUDIT — do not assume.",
      "maxCharsNote": MAXCHARS_NOTE
    },
    "host": {
      "family": "host",
      "engine": "engine/hand.js + engine/plates.js, declared in engine/build.js (manifest emitted by the drawing call)",
      "coordinateOrigin": "top-left of canvas",
      "units": "canvas units — multiply by exportScale for delivered pixels. exportScale is 2 for the WHOLE library: one scale, every family, so a shot can mix a room, a card and an annotation without a resample step.",
      "bakedText": false,
      "reproduce": "PLATES.<author>({ key, w, h, pal, seed, … }) — see engine/build.js for the exact call and seed of every asset in this family",
      "dataPolicy": "alpha cut-out figure, placed on a room host-anchor by height with the floor line pinned",
      "anchorContract": "a room's host-anchor region gives the target HEIGHT: scale this plate so (floorLineY - slots.figure.y) equals that height, then sit floorLineY on the region's bottom edge. Never scale to the anchor's width.",
      "tone": "The cut-out is NOT lit to match the room. He is the highest-contrast object in any frame he is in — his material hatch and the neutral ink pass on each part's turned side sit above the room's heaviest furniture, and his contact pool is small and tight. An earlier revision tinted him from the room's two sources and that is exactly what put him at the same value as the desk behind him.",
      "surface": "Bound per asset in engine/build.js (NOTE_SURFACES), not chosen by the caller. A surface goes UNDER the drawing: the legal pad's blue rules and red margin are furniture of the page, and on a room plate they draw straight through the desk, the props and the host. So the default is the plain night card, and the pad is reserved for assets that ARE notes, where the ruling is the point of the object.",
      "wardrobe": {
        "outfits": [
          "shirt",
          "cardigan",
          "rolled",
          "jumper",
          "gilet"
        ],
        "shipped": "shirt",
        "render": "BUILD.drawWith(item, outfit)",
        "rule": "every frame of one episode uses the SAME outfit; all five keep a mid-to-dark torso and the darkest cloth at the trousers, varying hue and detail rather than value"
      },
      "head": "The head carries the heaviest outline on the plate, with a jaw shadow and a turned plane on the skull. With the shirt and trousers fixed but the head still cream on a cream wall, the eye landed on his chest instead of his face.",
      "motion": "Two frames, loop at 2fps, ~2 canvas units of movement per point. The boil is HAND.setBoil — the same drawing re-wobbled, with plate layout and paper grain deliberately held still. The base file IS frame one (identical bytes), so entering or leaving the loop is silent.",
      "exportScale": 2,
      "scaleAuthority": "engine/audit.js EXPORT_SCALE = 2. Not a per-family choice and not a caller argument: Plate.manifest() ignores any exportScale passed to it, because that argument is how a per-family scale gets in — a caller hands one plate its own scale, the manifest faithfully records it, and a shot mixing a room with a card needs a resample step mid-composite. 2 is the floor for the two things this library is asked to do: a 16:9 room filling a 9:16 frame, and a push-in on a card. 1 has headroom for neither.",
      "frameShape": "frames[] entries are OBJECTS, not filenames — {tag, svg, png, boil, …} — and this is deliberate. A bare filename cannot say what a frame IS, so a player had to parse meaning out of a string suffix. Read frames[i].png, never a constructed name.",
      "baseFileRule": "files.png / files.svg are the SAME BYTES as frames[0] (files.baseIsFrame names which). A base file that is its own render pops on the first frame of the loop. Verify with AUDIT — do not assume.",
      "character": {
        "revision": "08 — side-glance and the robe (visual system closed)",
        "reads": "deadpan, tired, self-aware. Never the target of the joke — the one telling it.",
        "expression": "resting face is neutral to tired: flat mouth with one corner dropped, level brow, half-lidded eyes. No smile in any pose or framing.",
        "fatigue": "under-eye pouch and crease, hollow under the cheekbone, uneven stubble. Deliberately faint — shading heavy enough to read as bruising makes him look beaten, which is over the line.",
        "dress": "washed-out tee, collar stretched out of shape. Never a shirt and tie. Hair flattened on the slept-on side, glasses slightly crooked and smudged on one lens.",
        "posture": "asymmetric and slumped AT THE RIG, not at the outline. Revision 06 dipped the torso polygon while the skeleton stayed vertical and mirrored, so nothing read. The armature now carries a curved spine, a weight-bearing leg with the loaded hip raised, shoulders counter-tilting to the hips at the JOINTS, and per-pose asymmetric arms. See meta.rig on any pose plate.",
        "authoredIn": "engine/plates.js — hostFace(), shared by hostFigure and hostHead so the full figure and the close-up cannot disagree about who he is.",
        "eyeline": "The six full-figure poses and the two straight-to-camera framings look down the lens. The glance keys look off to camera-left or camera-right: match meta.glance to the side the graphic is on. A glance cut against a graphic on the opposite side is worse than him facing camera.",
        "wardrobe": "One outfit per episode. 'tee' is the default and covers every pose; 'robe' exists at medium only, for the episodes shot at the worst hour. Both read at the size he occupies in frame; the retired shirt/cardigan/rolled/jumper/gilet still resolve for anything already cut against them."
      },
      "maxCharsNote": MAXCHARS_NOTE
    },
    "overlays": {
      "family": "overlays",
      "engine": "engine/hand.js + engine/plates.js, declared in engine/build.js (manifest emitted by the drawing call)",
      "coordinateOrigin": "top-left of canvas",
      "units": "canvas units — multiply by exportScale for delivered pixels. exportScale is 2 for the WHOLE library: one scale, every family, so a shot can mix a room, a card and an annotation without a resample step.",
      "bakedText": false,
      "reproduce": "PLATES.<author>({ key, w, h, pal, seed, … }) — see engine/build.js for the exact call and seed of every asset in this family",
      "surface": "Bound per asset in engine/build.js (NOTE_SURFACES), not chosen by the caller. A surface goes UNDER the drawing: the legal pad's blue rules and red margin are furniture of the page, and on a room plate they draw straight through the desk, the props and the host. So the default is the plain night card, and the pad is reserved for assets that ARE notes, where the ruling is the point of the object.",
      "motion": "Two frames, loop at 2fps, ~2 canvas units of movement per point. The boil is HAND.setBoil — the same drawing re-wobbled, with plate layout and paper grain deliberately held still. The base file IS frame one (identical bytes), so entering or leaving the loop is silent.",
      "exportScale": 2,
      "scaleAuthority": "engine/audit.js EXPORT_SCALE = 2. Not a per-family choice and not a caller argument: Plate.manifest() ignores any exportScale passed to it, because that argument is how a per-family scale gets in — a caller hands one plate its own scale, the manifest faithfully records it, and a shot mixing a room with a card needs a resample step mid-composite. 2 is the floor for the two things this library is asked to do: a 16:9 room filling a 9:16 frame, and a push-in on a card. 1 has headroom for neither.",
      "frameShape": "frames[] entries are OBJECTS, not filenames — {tag, svg, png, boil, …} — and this is deliberate. A bare filename cannot say what a frame IS, so a player had to parse meaning out of a string suffix. Read frames[i].png, never a constructed name.",
      "baseFileRule": "files.png / files.svg are the SAME BYTES as frames[0] (files.baseIsFrame names which). A base file that is its own render pops on the first frame of the loop. Verify with AUDIT — do not assume.",
      "maxCharsNote": MAXCHARS_NOTE
    },
    "paper": {
      "family": "paper",
      "engine": "engine/hand.js + engine/plates.js, declared in engine/build.js (manifest emitted by the drawing call)",
      "coordinateOrigin": "top-left of canvas",
      "units": "canvas units — multiply by exportScale for delivered pixels. exportScale is 2 for the WHOLE library: one scale, every family, so a shot can mix a room, a card and an annotation without a resample step.",
      "bakedText": false,
      "reproduce": "PLATES.<author>({ key, w, h, pal, seed, … }) — see engine/build.js for the exact call and seed of every asset in this family",
      "surface": "Bound per asset in engine/build.js (NOTE_SURFACES), not chosen by the caller. A surface goes UNDER the drawing: the legal pad's blue rules and red margin are furniture of the page, and on a room plate they draw straight through the desk, the props and the host. So the default is the plain night card, and the pad is reserved for assets that ARE notes, where the ruling is the point of the object.",
      "motion": "Two frames, loop at 2fps, ~2 canvas units of movement per point. The boil is HAND.setBoil — the same drawing re-wobbled, with plate layout and paper grain deliberately held still. The base file IS frame one (identical bytes), so entering or leaving the loop is silent.",
      "exportScale": 2,
      "scaleAuthority": "engine/audit.js EXPORT_SCALE = 2. Not a per-family choice and not a caller argument: Plate.manifest() ignores any exportScale passed to it, because that argument is how a per-family scale gets in — a caller hands one plate its own scale, the manifest faithfully records it, and a shot mixing a room with a card needs a resample step mid-composite. 2 is the floor for the two things this library is asked to do: a 16:9 room filling a 9:16 frame, and a push-in on a card. 1 has headroom for neither.",
      "frameShape": "frames[] entries are OBJECTS, not filenames — {tag, svg, png, boil, …} — and this is deliberate. A bare filename cannot say what a frame IS, so a player had to parse meaning out of a string suffix. Read frames[i].png, never a constructed name.",
      "baseFileRule": "files.png / files.svg are the SAME BYTES as frames[0] (files.baseIsFrame names which). A base file that is its own render pops on the first frame of the loop. Verify with AUDIT — do not assume.",
      "boilPolicy": "Boil amplitude is declared per asset in engine/build.js BOIL_AMP, default 2.0 canvas units. Solve scale multiplies it: an asset stretched onto a target boils at amp x solve in the frame, which is the same property the inkWeight check already enforces for line weight. Do not compare a plate-side boil figure with a frame-side one.",
      "coveragePolicy": "Two boil metrics, and an asset must pass BOTH. AUDIT.amplitude() gives displacement per moved point (spec ~2 canvas units, band 0.4-2.0). AUDIT.coverage() gives the fraction of PIXELS that change between frames (pack band 1-6%, frozen below 0.5%). They fail independently: a one-rule plate can post a perfect amplitude and still read as a still with one element twitching, which is what happened to headline-band-t1 and hook-card-t3.",
      "maxCharsNote": MAXCHARS_NOTE
    },
    "peers": {
      "family": "peers",
      "engine": "engine/hand.js + engine/plates.js, declared in engine/build.js (manifest emitted by the drawing call)",
      "coordinateOrigin": "top-left of canvas",
      "units": "canvas units — multiply by exportScale for delivered pixels. exportScale is 2 for the WHOLE library: one scale, every family, so a shot can mix a room, a card and an annotation without a resample step.",
      "bakedText": false,
      "reproduce": "PLATES.<author>({ key, w, h, pal, seed, … }) — see engine/build.js for the exact call and seed of every asset in this family",
      "dataPolicy": "plate draws the ledger and reserves the bar column; every ticker, move and multiple is a slot, and engine/series.js draws the bars from the data",
      "slotKinds": {
        "region": "a graphic region for code to draw into, not a text box (bars)"
      },
      "surface": "Bound per asset in engine/build.js (NOTE_SURFACES), not chosen by the caller. A surface goes UNDER the drawing: the legal pad's blue rules and red margin are furniture of the page, and on a room plate they draw straight through the desk, the props and the host. So the default is the plain night card, and the pad is reserved for assets that ARE notes, where the ruling is the point of the object.",
      "motion": "Two frames, loop at 2fps, ~2 canvas units of movement per point. The boil is HAND.setBoil — the same drawing re-wobbled, with plate layout and paper grain deliberately held still. The base file IS frame one (identical bytes), so entering or leaving the loop is silent.",
      "exportScale": 2,
      "scaleAuthority": "engine/audit.js EXPORT_SCALE = 2. Not a per-family choice and not a caller argument: Plate.manifest() ignores any exportScale passed to it, because that argument is how a per-family scale gets in — a caller hands one plate its own scale, the manifest faithfully records it, and a shot mixing a room with a card needs a resample step mid-composite. 2 is the floor for the two things this library is asked to do: a 16:9 room filling a 9:16 frame, and a push-in on a card. 1 has headroom for neither.",
      "frameShape": "frames[] entries are OBJECTS, not filenames — {tag, svg, png, boil, …} — and this is deliberate. A bare filename cannot say what a frame IS, so a player had to parse meaning out of a string suffix. Read frames[i].png, never a constructed name.",
      "baseFileRule": "files.png / files.svg are the SAME BYTES as frames[0] (files.baseIsFrame names which). A base file that is its own render pops on the first frame of the loop. Verify with AUDIT — do not assume.",
      "maxCharsNote": MAXCHARS_NOTE
    },
    "room": {
      "family": "room",
      "engine": "engine/hand.js + engine/plates.js, declared in engine/build.js (manifest emitted by the drawing call)",
      "coordinateOrigin": "top-left of canvas",
      "units": "canvas units — multiply by exportScale for delivered pixels. exportScale is 2 for the WHOLE library: one scale, every family, so a shot can mix a room, a card and an annotation without a resample step.",
      "bakedText": false,
      "reproduce": "PLATES.<author>({ key, w, h, pal, seed, … }) — see engine/build.js for the exact call and seed of every asset in this family",
      "hostAnchorContract": "the host-anchor region's HEIGHT is the host's target height, and the quantity it scales is (host.floorLineY - host.slots.figure.y) — not the raw figure box, which runs past the floor line to carry the shoes. Then sit host.floorLineY on the region's bottom edge. Width is advisory: the figure box includes arms meant to pass it. See meta.hostAnchor on every plate.",
      "tone": "The ground stays the ground: the surface colour is visible everywhere in frame and nothing goes over the top of it globally. Light is VALUE FALLOFF — surfaces near a source carry less hatch and show more bare ground, surfaces away from one carry more, and the falloff follows the shapes of objects rather than sitting behind them in a rectangle. No tint, no wash, no colour layer. The ink line is the darkest thing in frame; only contact shadows go darker, and they are small and tight (the size of the object's footprint, never a halo). Hatch is SELECTIVE: furniture that needs weight carries a neutral ink hatch (max 0.19), paper and the wall and the floor are left as ground — texture is only depth when some things have it and some do not.",
      "hostContrast": "Dennis is the highest-contrast object in any frame he is in. The room is built to give way to him: nothing in the set is allowed to reach his value. The test is the composite — if your eye does not go to him first, the room is too loud.",
      "surface": "Bound per asset in engine/build.js (NOTE_SURFACES), not chosen by the caller. A surface goes UNDER the drawing: the legal pad's blue rules and red margin are furniture of the page, and on a room plate they draw straight through the desk, the props and the host. So the default is the plain night card, and the pad is reserved for assets that ARE notes, where the ruling is the point of the object.",
      "shadow": "Darks read as SHADOW, not as objects: each is densest where it meets what casts it, fades away from it, ends in a ragged edge rather than a drawn outline, and lets the ground show through. A shadow is the surface in shade, not a new object on top of it — drawn as a uniform fill with a line round it, the under-desk mass and the foreground crop became the biggest darks in frame and pulled the eye off the host.",
      "lineWeight": "Weight varies with distance across roughly a 5x spread. The multiplier was widened twice in earlier revisions with no visible effect, because the INPUT barely varied: depth came from height in frame and almost every prop sits in the same y-band. Depth is now a steep curve over the whole canvas, and props whose y contradicts their plane (wall-mounted binders, the cropped foreground) state their plane explicitly.",
      "motion": "Two frames, loop at 2fps, ~2 canvas units of movement per point. The boil is HAND.setBoil — the same drawing re-wobbled, with plate layout and paper grain deliberately held still. The base file IS frame one (identical bytes), so entering or leaving the loop is silent.",
      "exportScale": 2,
      "scaleAuthority": "engine/audit.js EXPORT_SCALE = 2. Not a per-family choice and not a caller argument: Plate.manifest() ignores any exportScale passed to it, because that argument is how a per-family scale gets in — a caller hands one plate its own scale, the manifest faithfully records it, and a shot mixing a room with a card needs a resample step mid-composite. 2 is the floor for the two things this library is asked to do: a 16:9 room filling a 9:16 frame, and a push-in on a card. 1 has headroom for neither.",
      "frameShape": "frames[] entries are OBJECTS, not filenames — {tag, svg, png, boil, …} — and this is deliberate. A bare filename cannot say what a frame IS, so a player had to parse meaning out of a string suffix. Read frames[i].png, never a constructed name.",
      "baseFileRule": "files.png / files.svg are the SAME BYTES as frames[0] (files.baseIsFrame names which). A base file that is its own render pops on the first frame of the loop. Verify with AUDIT — do not assume.",
      "maxCharsNote": MAXCHARS_NOTE
    },
    "shorts": {
      "family": "shorts",
      "engine": "engine/hand.js + engine/plates.js, declared in engine/build.js (manifest emitted by the drawing call)",
      "coordinateOrigin": "top-left of canvas",
      "units": "canvas units — multiply by exportScale for delivered pixels. exportScale is 2 for the WHOLE library: one scale, every family, so a shot can mix a room, a card and an annotation without a resample step.",
      "bakedText": false,
      "reproduce": "PLATES.<author>({ key, w, h, pal, seed, … }) — see engine/build.js for the exact call and seed of every asset in this family",
      "surface": "Bound per asset in engine/build.js (NOTE_SURFACES), not chosen by the caller. A surface goes UNDER the drawing: the legal pad's blue rules and red margin are furniture of the page, and on a room plate they draw straight through the desk, the props and the host. So the default is the plain night card, and the pad is reserved for assets that ARE notes, where the ruling is the point of the object.",
      "motion": "Two frames, loop at 2fps, ~2 canvas units of movement per point. The boil is HAND.setBoil — the same drawing re-wobbled, with plate layout and paper grain deliberately held still. The base file IS frame one (identical bytes), so entering or leaving the loop is silent.",
      "exportScale": 2,
      "scaleAuthority": "engine/audit.js EXPORT_SCALE = 2. Not a per-family choice and not a caller argument: Plate.manifest() ignores any exportScale passed to it, because that argument is how a per-family scale gets in — a caller hands one plate its own scale, the manifest faithfully records it, and a shot mixing a room with a card needs a resample step mid-composite. 2 is the floor for the two things this library is asked to do: a 16:9 room filling a 9:16 frame, and a push-in on a card. 1 has headroom for neither.",
      "frameShape": "frames[] entries are OBJECTS, not filenames — {tag, svg, png, boil, …} — and this is deliberate. A bare filename cannot say what a frame IS, so a player had to parse meaning out of a string suffix. Read frames[i].png, never a constructed name.",
      "baseFileRule": "files.png / files.svg are the SAME BYTES as frames[0] (files.baseIsFrame names which). A base file that is its own render pops on the first frame of the loop. Verify with AUDIT — do not assume.",
      "coveragePolicy": "Two boil metrics, and an asset must pass BOTH. AUDIT.amplitude() gives displacement per moved point (spec ~2 canvas units, band 0.4-2.0). AUDIT.coverage() gives the fraction of PIXELS that change between frames (pack band 1-6%, frozen below 0.5%). They fail independently: a one-rule plate can post a perfect amplitude and still read as a still with one element twitching, which is what happened to headline-band-t1 and hook-card-t3.",
      "maxCharsNote": MAXCHARS_NOTE
    },
    "structure": {
      "family": "structure",
      "engine": "engine/hand.js + engine/plates.js, declared in engine/build.js (manifest emitted by the drawing call)",
      "coordinateOrigin": "top-left of canvas",
      "units": "canvas units — multiply by exportScale for delivered pixels. exportScale is 2 for the WHOLE library: one scale, every family, so a shot can mix a room, a card and an annotation without a resample step.",
      "bakedText": false,
      "reproduce": "PLATES.<author>({ key, w, h, pal, seed, … }) — see engine/build.js for the exact call and seed of every asset in this family",
      "bridgeNote": "structure/multiple-bridge walks one multiple into another — three figures, two removals. It is not structure/unit-ladder with the rows turned sideways: the ladder subtracts line items from one figure in one unit, the bridge changes the denominator at every step, so the figures cannot stack in a column and be read as arithmetic.",
      "surface": "Bound per asset in engine/build.js (NOTE_SURFACES), not chosen by the caller. A surface goes UNDER the drawing: the legal pad's blue rules and red margin are furniture of the page, and on a room plate they draw straight through the desk, the props and the host. So the default is the plain night card, and the pad is reserved for assets that ARE notes, where the ruling is the point of the object.",
      "motion": "Two frames, loop at 2fps, ~2 canvas units of movement per point. The boil is HAND.setBoil — the same drawing re-wobbled, with plate layout and paper grain deliberately held still. The base file IS frame one (identical bytes), so entering or leaving the loop is silent.",
      "exportScale": 2,
      "scaleAuthority": "engine/audit.js EXPORT_SCALE = 2. Not a per-family choice and not a caller argument: Plate.manifest() ignores any exportScale passed to it, because that argument is how a per-family scale gets in — a caller hands one plate its own scale, the manifest faithfully records it, and a shot mixing a room with a card needs a resample step mid-composite. 2 is the floor for the two things this library is asked to do: a 16:9 room filling a 9:16 frame, and a push-in on a card. 1 has headroom for neither.",
      "frameShape": "frames[] entries are OBJECTS, not filenames — {tag, svg, png, boil, …} — and this is deliberate. A bare filename cannot say what a frame IS, so a player had to parse meaning out of a string suffix. Read frames[i].png, never a constructed name.",
      "baseFileRule": "files.png / files.svg are the SAME BYTES as frames[0] (files.baseIsFrame names which). A base file that is its own render pops on the first frame of the loop. Verify with AUDIT — do not assume.",
      "maxCharsNote": MAXCHARS_NOTE
    },
    "tables": {
      "family": "tables",
      "engine": "engine/hand.js + engine/plates.js, declared in engine/build.js (manifest emitted by the drawing call)",
      "coordinateOrigin": "top-left of canvas",
      "units": "canvas units — multiply by exportScale for delivered pixels. exportScale is 2 for the WHOLE library: one scale, every family, so a shot can mix a room, a card and an annotation without a resample step.",
      "bakedText": false,
      "reproduce": "PLATES.<author>({ key, w, h, pal, seed, … }) — see engine/build.js for the exact call and seed of every asset in this family",
      "sparkNote": "the -spark variants are not the plain sheet with a column bolted on: the sparkline column takes real width, so figures and labels are re-sized to what is left and labels must be abbreviated",
      "multiplesNote": "tables/multiples-strip is the INVERSE of peers/peer-strip and not a variant of it: the peer strip's rows are companies (a ticker each, with a move and a forward multiple), the multiples strip's rows are metrics and its columns are subject / peer median / position. marker-N is a region — the plate draws the rail, engine/series.js rangeMark draws what sits on it. Nothing on it is drawn in up or down: cheap is not up.",
      "rowCounts": "3, 4, 5 and 6 rows in both aspects, six periods throughout. A four-row script has something to use in 16:9 and a three-row short has something at all — the first batch shipped only 6r-16x9 and 4r-9x16, which left both of those with nothing.",
      "surface": "Bound per asset in engine/build.js (NOTE_SURFACES), not chosen by the caller. A surface goes UNDER the drawing: the legal pad's blue rules and red margin are furniture of the page, and on a room plate they draw straight through the desk, the props and the host. So the default is the plain night card, and the pad is reserved for assets that ARE notes, where the ruling is the point of the object.",
      "motion": "Two frames, loop at 2fps, ~2 canvas units of movement per point. The boil is HAND.setBoil — the same drawing re-wobbled, with plate layout and paper grain deliberately held still. The base file IS frame one (identical bytes), so entering or leaving the loop is silent.",
      "exportScale": 2,
      "scaleAuthority": "engine/audit.js EXPORT_SCALE = 2. Not a per-family choice and not a caller argument: Plate.manifest() ignores any exportScale passed to it, because that argument is how a per-family scale gets in — a caller hands one plate its own scale, the manifest faithfully records it, and a shot mixing a room with a card needs a resample step mid-composite. 2 is the floor for the two things this library is asked to do: a 16:9 room filling a 9:16 frame, and a push-in on a card. 1 has headroom for neither.",
      "frameShape": "frames[] entries are OBJECTS, not filenames — {tag, svg, png, boil, …} — and this is deliberate. A bare filename cannot say what a frame IS, so a player had to parse meaning out of a string suffix. Read frames[i].png, never a constructed name.",
      "baseFileRule": "files.png / files.svg are the SAME BYTES as frames[0] (files.baseIsFrame names which). A base file that is its own render pops on the first frame of the loop. Verify with AUDIT — do not assume.",
      "maxCharsNote": MAXCHARS_NOTE
    }
  };

  g.BUILD = {
    LIB: LIB,
    FAMILY_NOTES: FAMILY_NOTES,
    THUMBS: THUMBS,
    of: function (dir) { return LIB.filter((x) => x.dir === dir); },
    dirs: function () { return LIB.map((x) => x.dir).filter((d, i, a) => a.indexOf(d) === i); },
    surfaceOf: surfaceOf,
    OUTFITS: OUTFITS,
    boils: boils,
    NO_BOIL_KEYS: NO_BOIL_KEYS,
    BOIL_AMP: BOIL_AMP,
    boilAmpOf: boilAmpOf,
    // Every frame an asset ships, as {tag, args}. One entry for a static plate,
    // two for anything that boils, and the strip's own frames for a motion strip.
    // The renderer walks this — it never has to know which case it is in.
    framesOf: function (item) {
      if (item.strip) return item.strip.frames;
      if (!boils(item.dir, item.key)) return [{ tag: "", args: {} }];
      return [{ tag: "_f01", args: { boil: 1 } }, { tag: "_f02", args: { boil: 2 } }];
    },
    playbackOf: function (item) {
      if (item.strip) return { playback: item.strip.playback, fps: item.strip.fps || null, frameCount: item.strip.frames.length };
      if (!boils(item.dir, item.key)) return { playback: "static", fps: null, frameCount: 1 };
      return { playback: "loop", fps: 2, frameCount: 2 };
    },
    // Render any host item in a different outfit: BUILD.draw(item, null, "cardigan")
    drawWith: function (item, outfit, frameArgs) {
      const fn = g.PLATES[item.author];
      if (!fn) throw new Error("no author " + item.author);
      const fa = frameArgs || {};
      g.HAND.setBoil(fa.boil || 0, boilAmpOf(item.key));
      try {
        return fn(Object.assign({ key: item.key, pal: g.PLATES.pal(surfaceOf(item.key)), seed: item.seed, outfit: outfit }, item.args, fa));
      } finally { g.HAND.setBoil(0); }
    },
    // pal is optional now: the library knows which surface each asset belongs on,
    // so a caller cannot accidentally draw a room on ruled paper (which is exactly
    // what happened for two revisions).
    draw: function (item, pal, frameArgs) {
      const fn = g.PLATES[item.author];
      if (!fn) throw new Error("no author " + item.author);
      const p = pal || g.PLATES.pal(surfaceOf(item.key));
      const fa = frameArgs || {};
      // The boil is set for the duration of the draw and cleared after, so a
      // caller can never leak a frame offset into the next asset.
      g.HAND.setBoil(fa.boil || 0, boilAmpOf(item.key));
      try {
        return fn(Object.assign({ key: item.key, pal: p, seed: item.seed }, item.args, fa));
      } finally { g.HAND.setBoil(0); }
    },
  };
})(typeof window !== "undefined" ? window : globalThis);
