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
  const boils = (dir) => DATA_FAMILIES.indexOf(dir) < 0;

  const ANGLES = ["wide", "wide-tight", "desk-front", "desk-corner", "from-behind-the-monitor", "whiteboard-wall", "printer-corner", "doorway"];

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

    [A("overlays", "overlays/row-band", "rowBand", { w: 1744, h: 112 })],

    both("paper", "paper/headline-band-t1", "headlineBand", { treatment: 1 }),
    both("paper", "paper/headline-band-t2", "headlineBand", { treatment: 2 }),
    both("paper", "paper/headline-band-t3", "headlineBand", { treatment: 3 }),

    ANGLES.reduce((acc, angle) => acc.concat(both("room", `room/${angle}`, "room", { angle: angle })), []),
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
    // Every frame an asset ships, as {tag, args}. One entry for a static plate,
    // two for anything that boils, and the strip's own frames for a motion strip.
    // The renderer walks this — it never has to know which case it is in.
    framesOf: function (item) {
      if (item.strip) return item.strip.frames;
      if (!boils(item.dir)) return [{ tag: "", args: {} }];
      return [{ tag: "_f01", args: { boil: 1 } }, { tag: "_f02", args: { boil: 2 } }];
    },
    playbackOf: function (item) {
      if (item.strip) return { playback: item.strip.playback, fps: item.strip.fps || null, frameCount: item.strip.frames.length };
      if (!boils(item.dir)) return { playback: "static", fps: null, frameCount: 1 };
      return { playback: "loop", fps: 2, frameCount: 2 };
    },
    // Render any host item in a different outfit: BUILD.draw(item, null, "cardigan")
    drawWith: function (item, outfit, frameArgs) {
      const fn = g.PLATES[item.author];
      if (!fn) throw new Error("no author " + item.author);
      const fa = frameArgs || {};
      g.HAND.setBoil(fa.boil || 0);
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
      g.HAND.setBoil(fa.boil || 0);
      try {
        return fn(Object.assign({ key: item.key, pal: p, seed: item.seed }, item.args, fa));
      } finally { g.HAND.setBoil(0); }
    },
  };
})(typeof window !== "undefined" ? window : globalThis);
