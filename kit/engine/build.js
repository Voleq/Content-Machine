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

    both("peers", "peers/peer-strip", "peerStrip", {}, 77),
    both("cycles", "cycles/cycle-frame", "cycleFrame", {}, 88)
  );

  // Families that ship a downscaled thumbnail instead of a contact sheet: their
  // plates are too heavy to inline (a room is ~1.4 MB of vector). A thumbnail is
  // always a real downscale of the delivered plate, never a redraw at tile size.
  const THUMBS = { host: 300, room: 320 };

  g.BUILD = {
    LIB: LIB,
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
