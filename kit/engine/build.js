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

  const POSES = ["leaning-on-desk", "hands-in-pockets", "holding-a-page", "pointing-down-at-desk", "head-in-hands", "walking-out-of-frame",
    // §4.1 — SITTING DOWN, the brief's highest-priority pose. Same three strips as
    // every other pose (base, talk, idle): he talks and idles sitting down, and a
    // seated pose that could not talk would be a cut-away rather than a scene.
    "sitting-at-desk"];
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
  // §1.1 — THREE FRAMES, NOT TWO.
  //
  // Every animated plate in the kit was frameCount 2, and a two-frame loop is not
  // a living line: the eye finds the alternation in about a second and from then
  // on the plate is vibrating between two known states. Three breaks the lock.
  // It is one more draw per plate, not a new system.
  //
  // THE TALK STRIP IS THE ONE THAT CHANGES SHAPE, and it is a fix rather than an
  // extension. The shipped talk strip was mouthOpen true at boil 1, then
  // mouthOpen false at boil 2 — so two talk frames differed at the mouth AND at
  // the boil, which breaks §7's one hard rule. The renderer picks a talk frame
  // against the audio, so any non-mouth difference between talk frames
  // desynchronises from the voice, and no still will ever show it.
  //
  // So all three talk frames now sit at ONE boil index and differ only in how far
  // the mouth is open — 0, a half-open middle, and wide. That is three visemes
  // instead of two states, which is both what a mouth does and what the rule
  // requires. mouthOpen became a number to allow it; `true` still means 1, so
  // nothing else in the library moved.
  const HOST_STRIPS = [
    { suffix: "", playback: "loop", fps: 2, frames: [
      { tag: "_f01", args: { mouthOpen: false, bob: 0, boil: 1 } },
      { tag: "_f02", args: { mouthOpen: false, bob: 0, boil: 2 } },
      { tag: "_f03", args: { mouthOpen: false, bob: 0, boil: 5 } },
    ] },
    // ONE BOIL INDEX ACROSS ALL THREE. See above — this is the §7 rule, in the
    // data rather than in a comment.
    { suffix: "-talk", playback: "loop", fps: 8, frames: [
      { tag: "_f01", args: { mouthOpen: 0, bob: 0, boil: 1 } },
      { tag: "_f02", args: { mouthOpen: 0.45, bob: 0, boil: 1 } },
      { tag: "_f03", args: { mouthOpen: 1, bob: 0, boil: 1 } },
    ] },
    { suffix: "-idle", playback: "loop", fps: 4, frames: [
      { tag: "_f01", args: { mouthOpen: false, bob: 0, boil: 3 } },
      { tag: "_f02", args: { mouthOpen: false, bob: 3, boil: 4 } },
      { tag: "_f03", args: { mouthOpen: false, bob: 2, boil: 6 } },
    ] },
  ];

  // §1.2 — THE BLINK STRIP. Overlay, not a pose.
  //
  // Three frames because the IDLE strip is three: blink _fNN composites over idle
  // _fNN at the same boil index, so the lids meet the socket they belong to. The
  // frame count is registration, not rate — the renderer decides when to cut one
  // in (~100ms, every 3–4s) and the strip says nothing about how often.
  //
  // playback "overlay" rather than "loop": a player that loops this would blink
  // him continuously. It is the one strip in the kit that is not played by
  // advancing through it.
  // DROP THIRTEEN — THE OVERLAY CONTRACT, because "most of a contract" is what a
  // renderer cannot act on. Every clause below is DERIVED from the registration
  // rather than chosen, which is why it can be stated as a rule instead of a
  // preference. Verified against all seven strips.
  const BLINK_CONTRACT = {
      "mode": "Composite the blink frame OVER the matching idle frame at 0,0, same canvas, same scale. It is not played by advancing through it: a player that loops this blinks him continuously, which is why playback is \"overlay\" and fps is null.",
      "which_idle_frame": "INDEX-MATCHED, and derived rather than conventional: blink _fNN composites over idle _fNN. The two strips are authored from byte-identical args at every index (bob 0/3/2, boil 3/4/6), so the lid meets the socket it was drawn for. Checked on all seven pairs. A renderer holding idle frame 2 must use blink _f02 — not the nearest, not the first.",
      "why_not_over_talk": "A BLINK MAY NOT LAND ON A TALK FRAME, and this is registration, not taste. The talk strip is all three frames at ONE boil index (the section 7 rule); the blink strip carries idle's indices, 3/4/6. Compositing blink _f02 over a talk frame puts a lid drawn at boil 4 over a socket drawn at boil 1, and the linework will not meet. If the host must blink while speaking, that is a new strip authored at the talk index, not a reuse of this one.",
      "cadence": "~100ms in, every 3-4s, JITTERED. Uniform on [3.0s, 4.5s], resampled after each blink.",
      "cadence_seed": "seed = the asset's own seed field, advanced by BLINK COUNT SINCE THE VIDEO STARTED — never by shot index and never reset at a cut. Reseeding per shot is the one implementation that produces the defect worth avoiding: every cut restarts the clock, so he blinks at the same offset after each cut and it reads as a tic rather than as a person. The seed is per-asset so two poses in one video do not share a phase.",
      "at_a_cut": "A BLINK IN PROGRESS IS ABANDONED, not finished across the cut. It is ~100ms; carrying it into the next shot means compositing a lid over a frame from a different pose, and the registration above does not hold across poses. The new shot starts with lids open and the cadence clock CONTINUES from where it was, so the next blink does not arrive early.",
      "minimum_hold": "Do not start a blink within 150ms of the end of a shot. A blink clipped to 40ms by an incoming cut reads as a dropped frame, which is worse than not blinking.",
      "frame_count_is_registration": "Three frames because idle is three. The count is registration, NOT rate: the strip says nothing about how often, and a renderer must not infer a duration from it."
  };
  const BLINK_STRIP = { suffix: "-blink", playback: "overlay", fps: null, overlayOf: "-idle",
    contract: BLINK_CONTRACT, frames: [
    { tag: "_f01", args: { mouthOpen: false, bob: 0, boil: 3 } },
    { tag: "_f02", args: { mouthOpen: false, bob: 3, boil: 4 } },
    { tag: "_f03", args: { mouthOpen: false, bob: 2, boil: 6 } },
  ] };

  // THE BOIL. Everything that is not a data plate moves at two frames, 1–1.5% of
  // line movement — the room and the annotations were specified that way and both
  // shipped frozen. The mechanism is the same one the host frames already use:
  // hand.js takes a seed offset, so frame 2 is the identical drawing re-wobbled.
  // A data plate's FIGURES do not boil: a figure that moves is a figure being
  // re-read. The plate itself does — see section 1.5 immediately below, which is
  // where the gate is raised and where the old blanket rule is retracted. This
  // comment read "A data plate does NOT boil" until drop thirteen, 2,848
  // characters above the paragraph that overturns it, in the same file. Same
  // defect as pipeline/compose.py's paragraph, found by the same question: a
  // reader who stops at the first statement gets the old rule as settled fact.
  const DATA_FAMILIES = ["tables", "figures", "charts", "peers", "structure", "cycles"];

  // AND ONE OVERLAY, FOR THE SAME REASON THE DATA FAMILIES DO NOT BOIL.
  // overlays/row-band is not a plate the eye reads on its own — it composites
  // INTO a band-N slot on a numbers sheet, behind figures that are deliberately
  // still. The static rule exists precisely to stop movement under type that is
  // being read, and a boiling band under a frozen row breaks it from the other
  // side: the plate obeys the rule, the thing drawn on top of it does not.
  // It also takes the worst of the stretch — up to 3.75x in y on the 3-row
  // sheet — so it was the loudest thing in the frame it was meant to sit behind.
  // AND THE LOWER THIRD, for the same reason taken further. It is on screen
  // longer than any other asset in the product — a wobble re-drawn three times a
  // second at the edge of vision for forty minutes is a crawl, not craft. The
  // row-band exemption is about movement under type held still; this one is about
  // duration, and the viewer is not even looking at it. See plates.js
  // lowerThird(): the hand is in the drawing, not in the motion.
  const NO_BOIL_KEYS = ["overlays/row-band", "overlays/lower-third-16x9", "overlays/lower-third-9x16"];

  // §1.4 — A SETTLE ON ARRIVAL.
  //
  // Two frames at the head where the plate lands slightly past its position and
  // comes back. Authored as frames rather than as an easing transform, and each
  // settle frame carries its own boil index, so the linework re-wobbles as it
  // lands — which is the part an easing curve on a static frame cannot do.
  //
  // ONE STRIP, PLUS meta.loopStart, per your answer. The renderer's frame picker
  // is `i % frame_count` for a looping layer, so a strip with settle frames at the
  // head loops THROUGH them forever and the card re-settles every cycle. It has
  // to know where the loop begins whichever way this is authored — so publish the
  // index the picker consumes rather than a `settleFrames` count it has to derive.
  // A derived index is exactly the class of thing that has bitten this project
  // twice: the boil amplitude unit and the neck span were both a correct intent
  // with a wrong conversion.
  //
  // The overshoot is small and DOWN-AND-RIGHT into the frame, then back: a card
  // arriving has been put down, not thrown.
  const SETTLE = [
    { args: { boil: 7, settle: [7, 9] } },
    { args: { boil: 8, settle: [-2.5, -3] } },
  ];
  // NOT ROOMS. A room that settles reads as a camera bump, and the camera is the
  // one thing in this kit that never moves.
  const SETTLE_DIRS = ["cards", "figures", "paper"];
  const settles = (dir, key) => SETTLE_DIRS.indexOf(dir) >= 0 && NO_BOIL_KEYS.indexOf(key) < 0;

  // §1.5 — A DATA PLATE'S FRAME BREATHES AND ITS FIGURES DO NOT.
  //
  // Forty-seven plates were `playback: static`, which made them the only dead
  // things on screen — a frozen table in a boiling room reads as a screenshot
  // pasted over a cartoon, the same defect the base host pose had two revisions
  // ago and for the same reason.
  //
  // They are frozen because wobbling figures are unreadable, and that stays true.
  // So the boil is not turned on for these plates; it is turned on for their
  // FURNITURE. HAND.setBoil's third argument raises a gate, and with the gate up
  // a mark takes the boil offset only if it was drawn inside HAND.breathe() —
  // paper edge, corner wear, rule lines, hatch. Everything else emits the
  // identical path it emitted at boil 0, bit for bit.
  //
  // WHAT IS DELIBERATELY NOT IN THE BREATHING SET, because the option that
  // suggested them bundled two different things:
  //   - axis lines. An axis IS a measurement reference: move it and the data
  //     appears to move even though the series is pinned.
  //   - series lines. That is the data itself, on a channel whose premise is real
  //     numbers. A wobbling series reports a different value every frame.
  //   - slot underlays and highlight boxes. An underlay moving behind pinned type
  //     creates RELATIVE motion, which reads worse than either moving alone.
  //
  // The sorting principle is not "anything near type" — it is anything a viewer
  // uses to READ A VALUE. Nobody reads a number off a table rule.
  const GATED_FAMILIES = DATA_FAMILIES;
  const gated = (dir, key) => GATED_FAMILIES.indexOf(dir) >= 0 && NO_BOIL_KEYS.indexOf(key) < 0;
  // Everything now has motion of some kind except the one overlay that must not.
  const boils = (dir, key) => NO_BOIL_KEYS.indexOf(key) < 0;

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

  // §4.2 — TIME OF DAY, AND WHY IT IS NOT A SWITCH ANY MORE.
  //
  // It shipped as a library-wide flag while §1 was open, which was the right
  // shape for a thing that could not be turned on: one value, all rooms, easy to
  // revert. Now that the title carries its own ground (§1 chose `card`) the
  // blocker is gone, and a library-wide flag is the WRONG shape — it does not
  // give you a variant axis, it makes the whole channel dusk.
  //
  // So the variants are ASSETS. `room/desk-front-dusk-16x9` sits beside
  // `room/desk-front-16x9`, and the director picks an hour per episode by
  // picking a key — which is exactly how roomRoles already resolves `talk` to
  // one of three desk angles by seed. Nothing in the engine needs a mode.
  //
  // DUSK ONLY, AND `day` IS DELIBERATELY NOT SHIPPED. The set is lit by one warm
  // desk lamp and one cold monitor, and every cast shadow in every room is
  // derived from those two. At dusk that is still true — the light outside is
  // failing, the lamp is still the source, and the shadows stay honest. In
  // daylight it is false: the lamp would not be the brightest thing in the room
  // and every shadow on every prop would be pointing the wrong way. Shipping
  // `day` would mean a relight, which is a much larger job than a wall tone and
  // is not this. room() still accepts "day" so the work is not thrown away; no
  // asset uses it.
  const TIME_OF_DAY_VARIANTS = ["dusk"];

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
  const CAMERA_ANGLES = ["corner-perspective", "low-desk-height", "high-desk-down",
    // §4.3 — OVER THE SHOULDER. A camera position, so it belongs on this list
    // rather than with the eight furniture arrangements — and the only room plate
    // with a figure in it: his shoulder and the back of his head crop the near
    // corner, so it declares no host anchor and no title slot. See the branch in
    // engine/plates.js room().
    "over-the-shoulder"];

  // §1 — THE TITLE'S OWN GROUND. DECIDED: "card".
  //
  // Chapter-opener titles were legible because the wall behind them happened to be
  // flat and pale, which is a property of the wall and not of the title. Measured,
  // that rule was not even holding: 16 of the 22 chapter openers already had drawn
  // ink under the title box, worst at 28% of the box on room/whiteboard-wall-16x9.
  //
  // So the title carries its own ground: an opaque drawn card, taped at two
  // corners, with its own bloom rim and its own cast. Of the three treatments in
  // proof/title-ground.html it is the one that makes contrast wall-independent
  // (floor 11.9:1 on every wall, spread 0.0) WITHOUT moving the type colour — so
  // the back catalogue and the renderer's chapter-opener template both stay as
  // they are, and slots.title.colour is still `structure`. On the clean walls it
  // costs nothing: 0.14% of the box failing becomes 0.00%.
  //
  // What it costs, stated where the switch is: a prop now appears in the room that
  // was not there before, and on the plates where the box is over something it
  // covers work somebody drew — the printer-corner window, two of
  // low-desk-height's wall bands, three post-its on desk-corner, one of
  // high-desk-down's sheets. That was the price in CHANGES.md and it is accepted.
  //
  // room/over-the-shoulder declares no title slot, so it takes no ground: the
  // call is per-plate and derived from what the plate published, not a list.
  const TITLE_GROUND = "card";

  // §4.2 — TIME OF DAY. Still null, and now for a different reason.
  //
  // A variant axis on the existing rooms rather than new angles: same props, same
  // anchors, same shadows, a different hour on the wall. engine/plates.js room()
  // takes "dusk" or "day"; null is the three-in-the-morning set the kit was built
  // as.
  //
  // §1's blocker is GONE: the title now carries its own ground, so a toned wall no
  // longer costs the chapter opener its legibility, which is exactly what the
  // brief said §1 would unlock. What keeps this at null is that nobody has looked
  // at a dusk plate yet — the tone is measured to land on all 18 set plates, and
  // whether it reads as dusk rather than as a beige wall is a question for a
  // render. Turn it on after that pass, not before.
  //
  // Set to "dusk" or "day" and the FULL ANGLE SET gets the variant — which is
  // also the shape of the decision: a time of day is an episode-level choice like
  // the wardrobe, not a per-shot one. Two hours on one wall in one video is two
  // rooms.
  const TIME_OF_DAY = null;

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

    // §1.1 — THE LOWER THIRD. Its own size, not a frame: an overlay the
    // compositor places, like row-band. The two aspects are re-authored rather
    // than scaled — a 9:16 lower third is proportionally wider and its type is a
    // step up, because it is read on a phone at arm's length.
    [A("overlays", "overlays/lower-third-16x9", "lowerThird", { w: 820, h: 208 }),
     A("overlays", "overlays/lower-third-9x16", "lowerThird", { w: 960, h: 252 })],

    both("paper", "paper/headline-band-t1", "headlineBand", { treatment: 1 }),
    both("paper", "paper/headline-band-t2", "headlineBand", { treatment: 2 }),
    both("paper", "paper/headline-band-t3", "headlineBand", { treatment: 3 }),

    ANGLES.reduce((acc, angle) => acc.concat(both("room", `room/${angle}`, "room", { angle: angle, titleGround: TITLE_GROUND, timeOfDay: TIME_OF_DAY })), []),
    CAMERA_ANGLES.reduce((acc, angle) => acc.concat(both("room", `room/${angle}`, "room", { angle: angle, titleGround: TITLE_GROUND, timeOfDay: TIME_OF_DAY })), []),

    // §4.2 — the same eleven angles at the other hour. Same props, same anchors,
    // same slots, same shadows: only the wall tone differs, which is what makes
    // this a variant rather than eleven new rooms. See TIME_OF_DAY_VARIANTS for
    // why dusk and not day.
    TIME_OF_DAY_VARIANTS.reduce((acc, tod) => acc.concat(
      ANGLES.concat(CAMERA_ANGLES).reduce((a2, angle) => a2.concat(
        both("room", `room/${angle}-${tod}`, "room", { angle: angle, titleGround: TITLE_GROUND, timeOfDay: tod })
      ), [])
    ), []),
    both("room", "room/wall-of-calls", "wallOfCalls", {}),
    // §3.3 — the same wall with one more card just pinned to it, crooked, over the
    // others. A variant rather than a new family: cutting from one to the other IS
    // the card arriving, which is the beat.
    both("room", "room/wall-of-calls-pinned", "wallOfCalls", { pinned: true }, 7),

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
    both("cycles", "cycles/cycle-frame", "cycleFrame", {}, 88),

    // §2.1 — WATERFALL. Three, four and five costs, both aspects.
    //
    // Count variants rather than one elastic plate, for the reason tables/ ships
    // 3r through 6r: a five-step waterfall is useless to a three-cost script, and
    // an elastic one would have to re-derive its column grid at render time,
    // which is where a generic plate stops being predictable. Three and five are
    // the minimum the brief asks for; four is here because the middle case is the
    // most plausible of the three — revenue, COGS, opex, tax, what is left.
    [3, 4, 5].reduce((acc, n) => acc.concat(both("figures", `figures/waterfall-${n}s`, "waterfall", { steps: n }, 31 + n)), []),

    // §2.2 — WHAT HAS TO BE TRUE. Fixed shape: one demand, one history.
    both("structure", "structure/implied", "impliedPlate", {}, 37),

    // DROP TWO, first slice — §2.3, §2.4, §2.11.
    //
    // The three six-period charts, landed together because they are one group:
    // same author, same margins, same tick convention, so any of them can sit in
    // the same cut as charts/line-6y or bars-6y without the years changing width
    // mid-video. That is the whole reason §0.2 fixes periods at six.
    both("charts", "charts/dilution-6y", "chartFrame", { type: "dilution-6y" }, 41),
    both("charts", "charts/maturities", "chartFrame", { type: "maturities" }, 43),
    both("charts", "charts/guided-vs-actual-6y", "chartFrame", { type: "guided-vs-actual-6y" }, 47),

    // DROP TWO, the rest — §2.5 … §2.14.
    //
    // §2.6 / §2.12 / §2.14 are ONE author. All three are a single bar that
    // divides; what differs is the count and what the segments mean, which lives
    // in the key and the manifest. Same call as the six-period charts.
    [2, 3, 4].reduce((acc, n) => acc.concat(both("figures", `figures/share-of-${n}`, "proportionBar", { segments: n, kind: "share-of" }, 50 + n)), []),
    [3, 4, 5].reduce((acc, n) => acc.concat(both("figures", `figures/by-region-${n}`, "proportionBar", { segments: n, kind: "by-region" }, 60 + n)), []),
    // Three segments, fixed: insider, institutional, the rest. A fourth slice is a
    // different argument, so there are no count variants.
    both("figures", "figures/ownership", "proportionBar", { segments: 3, kind: "ownership" }, 67),

    both("peers", "peers/distribution", "distribution", {}, 71),
    [2, 3].reduce((acc, n) => acc.concat(both("figures", `figures/scale-${n}`, "scaleFig", { refs: n }, 73 + n)), []),
    [4, 6, 8].reduce((acc, n) => acc.concat(both("paper", `paper/receipt-${n}`, "receipt", { lines: n }, 80 + n)), []),
    [3, 4, 5].reduce((acc, n) => acc.concat(both("structure", `structure/said-happened-${n}`, "saidHappened", { events: n }, 90 + n)), []),
    both("structure", "structure/sensitivity", "sensitivity", {}, 97),
    // §3.2 — the whiteboard as a PLATE, where the diagram is the content. Three
    // and four nodes: the two counts an explainer diagram actually comes in.
    [3, 4].reduce((acc, n) => acc.concat(both("structure", `structure/whiteboard-${n}`, "whiteboard", { nodes: n }, 110 + n)), []),
    [4, 6].reduce((acc, n) => acc.concat(both("charts", `charts/multiples-grid-${n}`, "multiplesGrid", { cells: n }, 100 + n)), []),

    // §2 — THE QUARTER. Data the pipeline loads and the kit could not draw.
    //
    // Every chart in the kit was annual. The pipeline was changed to read a
    // Quarters sheet carrying six to eight quarters, so the data path existed and
    // the video had nowhere to put it. These ten assets are that gap, and they
    // are deliberately three different KINDS of answer rather than one elastic
    // plate:
    //
    //   bars-8q / line-8q     eight periods, quarterly labels. A column count on
    //                         chartFrame, so they share the margins, the tick
    //                         convention and the axis pinning with line-6y and
    //                         bars-6y — which is what lets a quarterly chart cut
    //                         against an annual one without the grid shifting.
    //   figures/qoq-yoy       the editorial instrument. Both readings of one
    //                         quarter, equal weight, and structurally unable to
    //                         resolve them into a single growth figure.
    //   seasonality-{4,6}y    four quarters across, one series per year. Count
    //                         variants on YEARS — the quarters are always four,
    //                         so there is nothing to vary on the horizontal.
    //
    // Eight rather than six on the 8q pair: the sheet carries up to eight, and
    // eight is two whole years, which is the shortest span in which a seasonal
    // pattern is visible at all. A six-quarter variant would show Q4 once and
    // invite exactly the comparison qoq-yoy exists to stop.
    both("charts", "charts/bars-8q", "chartFrame", { type: "bars-8q" }, 121),
    both("charts", "charts/line-8q", "chartFrame", { type: "line-8q" }, 123),
    both("figures", "figures/qoq-yoy", "quarterPair", {}, 125),
    [4, 6].reduce((acc, n) => acc.concat(both("charts", `charts/seasonality-${n}y`, "seasonality", { years: n }, 130 + n)), []),

    // §2 — THE CONFESSION. Two treatments, both shipped, because tone cannot be
    // chosen from a description — the axis is what carries the credibility: that
    // the correction is as considered as the claim was (`statement`), or that a
    // record of these exists at all (`ledger`). Recommendation in CHANGES.md.
    //
    // BOTH SHIP rather than one being picked here: unlike §1's title ground,
    // these are not mutually exclusive library-wide settings — a chapter can
    // reach for either, and keeping both costs four assets. If one is never
    // used after a real cut, delete it then.
    ["statement", "ledger"].reduce((acc, t) => acc.concat(both("structure", `structure/confession-${t}`, "confession", { treatment: t }, 170 + t.length)), []),

    // §3 — FIVE PLATES THE PIPELINE ALREADY HAS DATA FOR. Each exists because the
    // code pulls the data and had nowhere to draw it.
    //
    // 3.1 replaces figures/big-number-l2 in short-interest's evidence beat: four
    // quantities that mean nothing individually, with the one proportion among
    // them drawn as a proportion. 3.2 is the Form 4 flow, count variants on
    // marks. 3.3 is the FRED series — same name as line-6y, different plate.
    // 3.4 is the end card, and it is the only plate in the kit whose layout is
    // dictated from outside it.
    //
    // 3.5, THE CHANNEL ART, IS NOT HERE and is not forgotten: a banner and a
    // profile drawn from the host and room families is illustration, not plate
    // work, and hand-writing it as SVG at banner scale produces a diagram rather
    // than artwork. It needs a decision — compose it from existing host/ plates,
    // brief an illustrator, or accept what a drawn attempt would be. See CHANGES.
    both("figures", "figures/short-interest", "shortInterest", {}, 181),
    [6, 12].reduce((acc, n) => acc.concat(both("charts", `charts/insider-flow-${n}`, "insiderFlow", { marks: n }, 184 + n)), []),
    both("charts", "charts/macro-series", "macroSeries", {}, 191),
    both("structure", "structure/end-card", "endCard", {}, 194),

    // §3 — WHAT THE FILING READER FOUND.    //
    // The pipeline now reads this year's report, last year's and the quarterlies,
    // and produces what CHANGED: risk factors that appeared or vanished,
    // management language that shifted, segments that moved. That output had
    // nowhere to land on screen.
    //
    // structure/language-shift is the narrow case and the common one: the same
    // thing, described two different ways, a year apart. Fixed shape, no count
    // variants — there is one pair. A second pair would be a list of shifts,
    // which is a different argument and would want a different plate.
    both("structure", "structure/language-shift", "languageShift", {}, 141),
    // paper/headline-stack is the other half of §3: headlines now reach the
    // writer, headline-band carries one, and nothing carried several. Three and
    // four, for tables/'s reason — the strip measure is fixed so the headline
    // budget is stable, and an elastic plate would re-derive its strip height at
    // render time. Five would be a list.
    [3, 4].reduce((acc, n) => acc.concat(both("paper", `paper/headline-stack-${n}`, "headlineStack", { items: n }, 150 + n)), []),

    // §1.2 — THE BLINK. One overlay strip per hostHead key that has an idle.
    //
    // hostFigure poses are excluded deliberately and it is not an omission: those
    // are full-body 9:16 plates where the head is a few dozen pixels across, and
    // a blink drawn at that size is one pixel changing. The behaviour belongs
    // where the face is legible.
    HOST_FRAMINGS.reduce((acc, fr) => acc.concat([
      (function () {
        const size = fr === "close-up" ? { w: 1080, h: 1080 } : { w: 1080, h: 1440 };
        const it = A("host", `host/${fr}-blink`, "hostBlink", Object.assign({ framing: fr }, size, BLINK_STRIP.frames[0].args));
        it.strip = BLINK_STRIP;
        return it;
      })(),
    ].concat([["left", -1], ["right", 1]].map(function (gl) {
      const size = fr === "close-up" ? { w: 1080, h: 1080 } : { w: 1080, h: 1440 };
      const it = A("host", `host/${fr}-glance-${gl[0]}-blink`, "hostBlink",
        Object.assign({ framing: fr, glance: gl[1] }, size, BLINK_STRIP.frames[0].args));
      it.strip = BLINK_STRIP;
      return it;
    }))), []),
    [(function () {
      const it = A("host", "host/medium-robe-blink", "hostBlink",
        Object.assign({ framing: "medium", outfit: "robe", w: 1080, h: 1440 }, BLINK_STRIP.frames[0].args));
      it.strip = BLINK_STRIP;
      return it;
    })()],

    // §4.3 — THE EMPTY CHAIR. One plate, 9:16 like every host cut-out, and it is
    // the same hostChair() the seated pose sits on: the empty chair and the
    // occupied one are one object by construction. It boils like the rest of the
    // family — an empty chair frozen in a room that breathes is the still-image
    // defect the base pose already had once.
    [A("host", "host/empty-chair", "emptyChair", Object.assign({}, P916), 161)]
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
      "titleGround": "§1. The chapter-opener title borrows its legibility from the wall behind it: a flat pale plane that no angle happens to put a prop, a tone or a shadow on. mass() encodes that accidentally — it suppresses every cast shadow whose base sits above 36% of frame height so the title box keeps a clean ground — and nothing else in the family states the rule at all. titleGround gives the title its own drawn ground instead: \"card\" (opaque taped card, contrast guaranteed and identical on every wall), \"scrim\" (three feathered washes, the room still reads through, contrast improved but not guaranteed) or \"slab\" (ink block, title reversed out, the most robust and the largest change). The panel is drawn AROUND the published title box, so slots.title does not move on any plate; it spans title and caption together where an angle sets a caption under the title. It is PINNED — a ground is a slot underlay and an underlay breathing behind still type is relative motion. When a ground is on, the plate publishes meta.titleGround (box, opacity, slots covered) and slots.title.colour, and the chapter-opener shot template must read that colour rather than assume structure. Currently null in engine/build.js: the treatment is an open decision, see proof/title-ground.html.",
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
    TITLE_GROUND: TITLE_GROUND,
    TIME_OF_DAY: TIME_OF_DAY,
    TIME_OF_DAY_VARIANTS: TIME_OF_DAY_VARIANTS,
    boils: boils,
    settles: settles,
    SETTLE_DIRS: SETTLE_DIRS,
    gated: gated,
    GATED_FAMILIES: GATED_FAMILIES,
    NO_BOIL_KEYS: NO_BOIL_KEYS,
    BOIL_AMP: BOIL_AMP,
    boilAmpOf: boilAmpOf,
    // Every frame an asset ships, as {tag, args}. One entry for the one asset
    // that must not move, three for anything that boils, and the strip's own
    // frames for a motion strip. The renderer walks this — it never has to know
    // which case it is in.
    framesOf: function (item) {
      if (item.strip) return item.strip.frames;
      if (!boils(item.dir, item.key)) return [{ tag: "", args: {} }];
      const loop = [{ args: { boil: 1 } }, { args: { boil: 2 } }, { args: { boil: 5 } }];
      const head = settles(item.dir, item.key) ? SETTLE.map((f) => ({ args: f.args })) : [];
      // Tags are positional and continuous across the whole strip. A settle frame
      // is not a different KIND of file and should not be named as though it were
      // — the renderer reads meta.loopStart to know where the loop begins, and the
      // filenames stay _f01.._fNN exactly as §7 requires.
      return head.concat(loop).map((f, i) => ({ tag: "_f0" + (i + 1), args: f.args }));
    },
    playbackOf: function (item) {
      if (item.strip) return { playback: item.strip.playback, fps: item.strip.fps || null,
        frameCount: item.strip.frames.length, overlayOf: item.strip.overlayOf || undefined,
        overlayContract: item.strip.contract || undefined };
      if (!boils(item.dir, item.key)) return { playback: "static", fps: null, frameCount: 1 };
      const s = settles(item.dir, item.key);
      const r = { playback: "loop", fps: 2, frameCount: s ? 5 : 3 };
      if (s) {
        r.loopStart = SETTLE.length;
        r.settleNote = "frames 0.." + (SETTLE.length - 1) + " play ONCE on arrival, then the layer loops frames " + SETTLE.length + ".." + (r.frameCount - 1) + " forever. A picker that does `i % frameCount` on the whole strip will re-settle the plate every cycle.";
      }
      if (gated(item.dir, item.key)) r.boilGate = "frame-only";
      return r;
    },
    // Render any host item in a different outfit: BUILD.draw(item, null, "cardigan")
    drawWith: function (item, outfit, frameArgs) {
      const fn = g.PLATES[item.author];
      if (!fn) throw new Error("no author " + item.author);
      const fa = frameArgs || {};
      g.HAND.setBoil(fa.boil || 0, boilAmpOf(item.key), gated(item.dir, item.key));
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
      // caller can never leak a frame offset into the next asset. The gate goes
      // with it: a data plate is drawn at a real boil index with only its
      // furniture allowed to take the offset (§1.5).
      g.HAND.setBoil(fa.boil || 0, boilAmpOf(item.key), gated(item.dir, item.key));
      try {
        const P = fn(Object.assign({ key: item.key, pal: p, seed: item.seed }, item.args, fa));
        if (fa.settle && P.settleTo) P.settleTo(fa.settle[0], fa.settle[1]);
        return P;
      } finally { g.HAND.setBoil(0); }
    },

    // ======================================================================
    // THE BUILD COST — stream(), and why the shape of the call is the fix
    //
    // scripts/ingest_kit.py OOM-KILLED AT 286 FRAMES of 924. The cause is not
    // that a plate is expensive: the most expensive single frame in the library
    // is a room at ~250kb of SVG, and 924 of those is ~120mb of string, which is
    // survivable. What is not survivable is HOLDING them. Every caller so far —
    // preflight.html's check A, the baseline generator, every proof page — walks
    // LIB, calls draw() per frame, and keeps the returned P objects in an array
    // because the next check wants them. A P is not a string; it holds its path
    // list, its slot table and its manifest, and 924 of them retained at once is
    // what the kernel killed.
    //
    // So the fix is not an optimisation, it is the SHAPE OF THE CALL. stream()
    // yields one frame at a time, hands it to the consumer, and drops every
    // reference before building the next. Peak memory is ONE frame plus whatever
    // the consumer keeps — for an ingest writing a PNG and moving on, that is one
    // frame, flat, whether the library is 270 assets or 2,700.
    //
    // I found this from the other end while generating §0's manifests in drop
    // twelve: one pass over all 270 assets timed out, and I had to chunk it by
    // family, with room alone needing splitting in two. Same failure, same cause,
    // reached by a different road — which is the part worth trusting.
    //
    //   BUILD.stream(function (f) {
    //     writePNG(f.path, rasterise(f.svg, f.delivered));   // f.svg is a STRING
    //   });                                                  // nothing retained
    //
    // The callback gets {key, dir, family, tag, path, args, svg, canvas,
    // delivered, exportScale, isBase, baseIsFrame, index, total, frameIndex,
    // frameCount} — everything an ingest needs to write the file and nothing that
    // keeps the plate alive. Return false from the callback to stop early.
    //
    // It emits EVERY FILE THE MANIFEST DECLARES: the frames plus the untagged
    // base on an animated plate. opts: {family, dir, keys, baseOnly, framesOnly}.
    //
    // WHAT IT DOES NOT DO: it does not make the build parallel, and it does not
    // help a consumer that accumulates. A caller that pushes f.svg into an array
    // has rebuilt the original defect with extra steps — which is exactly what
    // every existing caller does, deliberately, because a check that compares
    // frame against frame has to hold two. stream() is for the INGEST, which
    // holds none. The proof pages are unchanged and still build eagerly; the
    // pages that need every frame at once are the pages that cannot use this.
    // ======================================================================
    stream: function (fn, opts) {
      const o = opts || {};
      const items = LIB.filter(function (it) {
        if (o.family && it.key.split("/")[0] !== o.family) return false;
        if (o.dir && it.dir !== o.dir) return false;
        if (o.keys && o.keys.indexOf(it.key) < 0) return false;
        return true;
      });
      const SC = 2;
      let total = 0;
      items.forEach(function (it) {
        const n = g.BUILD.framesOf(it).length;
        total += o.baseOnly ? (n > 1 ? 1 : n) : n + (n > 1 && !o.framesOnly ? 1 : 0);
      });
      let n = 0, stopped = false;
      for (let a = 0; a < items.length && !stopped; a++) {
        const item = items[a];
        const frames = g.BUILD.framesOf(item);
        const family = item.key.split("/")[0];
        const nameBase = item.key.split("/").slice(1).join("/");
        // THE BASE FILE, WHICH framesOf() DOES NOT RETURN. §0's manifests declare
        // files.base on every plate, and on an animated one it is byte-identical
        // to _f01 — so an ingest walking framesOf() alone writes the frames and
        // never writes the base the manifest promised. Found by streaming three
        // plates and reading the paths back: a static plate emitted its one
        // untagged file correctly and an animated plate emitted _f01.._f03 and no
        // base at all. Emitted here from frame one's own args, so the identity is
        // by construction rather than by a copy step the ingest has to remember.
        // opts.baseOnly / opts.framesOnly are for an ingest that wants to split
        // the two passes; the default is everything the manifest declares.
        const wantBase = frames.length > 1 && !o.framesOnly;
        const emit = [];
        if (wantBase) emit.push({ tag: "", args: frames[0].args, isBase: true, fi: null });
        if (!o.baseOnly) frames.forEach(function (fr, fx) { emit.push({ tag: fr.tag, args: fr.args, isBase: !fr.tag, fi: fx }); });
        for (let i = 0; i < emit.length && !stopped; i++) {
          const fr = emit[i];
          // Built, handed over, and dropped inside one iteration. P goes out of
          // scope at the end of this block and the string goes with it; nothing
          // above this loop holds a reference to either.
          const P = g.BUILD.draw(item, null, fr.args);
          const m = P.manifest();
          const payload = {
            key: item.key, dir: item.dir, family: family,
            tag: fr.tag || null, args: fr.args,
            path: family + "/" + nameBase + (fr.tag || "") + ".png",
            svg: P.toSVG(),
            canvas: m.canvas,
            delivered: [m.canvas[0] * SC, m.canvas[1] * SC],
            exportScale: SC,
            isBase: !!fr.isBase,
            baseIsFrame: frames.length > 1,
            index: n, total: total,
            frameIndex: fr.fi, frameCount: frames.length,
          };
          n++;
          if (fn(payload) === false) stopped = true;
        }
      }
      return { frames: n, assets: items.length, stopped: stopped };
    },

    // The batch fallback's unit of work, and the reason it is a unit: a family is
    // the largest chunk that built in one pass in drop twelve, and manifests are
    // already per-family, so a batch that fails names a file you can regenerate
    // alone. See scripts/build_batch.mjs.
    families: function () {
      return LIB.map(function (x) { return x.key.split("/")[0]; })
        .filter(function (d, i, a) { return a.indexOf(d) === i; }).sort();
    },
  };
})(typeof window !== "undefined" ? window : globalThis);
