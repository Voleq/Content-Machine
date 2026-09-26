/* Run the design kit's engine and write the artwork out.
 *
 * BUILD-TIME ONLY. Nothing in the render path may shell out to node: a bug in
 * the kit has to break a build, never a published video. `scripts/ingest_kit.py`
 * is the only caller, and what it leaves on disk is plain PNGs plus one registry
 * that the renderer reads with no JS anywhere near it.
 *
 *   node scripts/kit_engine.js --kit <delivery> --out <dir> --emit <plates.json>
 *                              [--against <export dir>] [--only FAMILY] [--svg]
 *
 * THE KIT IS CODE, NOT PICTURES, and this is the rebuild layout of it. `port.js`
 * is the plate engine: the legacy authors in `plates.js`, then every later round
 * installed onto the same registry (`plates-r1.js`, `plates-r2.js`, and
 * `plates-r3.js` building its rows out of `sector-copy.js`), recoloured per hour
 * through one palette map, with `catalogue()` naming every plate once. The rooms
 * are the flat model in `kit-model.js`; the host is `figure.js`, one paint order
 * for every frame of every strip. Every plate exists at every hour in
 * `design-tokens.json`, so every plate is drawn once per hour here.
 *
 * MOTION IS AUTHORED, AND DRAWN HERE THE WAY THE KIT DRAWS IT. A data plate's
 * frames are `toSVG({ ruleOffset })` for each of `motion.dataRuleOffsets`: its
 * rule lines move a unit and its axes and values stay where they are. A host
 * strip's frames are `figure.svg` for each of `figure.framesOf(strip)`: the
 * talk strip cycles the six mouths, idle moves the head, blink closes the eyes.
 *
 * AGAINST THE KIT'S EXPORT, BYTE FOR BYTE. Since rebuild-17 `engine/export.js`
 * writes BLANK files, every one of them through the same `emit.build()` that
 * writes the manifests the audit reads. `--against` proves this driver draws
 * exactly those files — every frame of every plate and strip equal to design's,
 * and every room the same shapes in the same colours. A drawing that differs is
 * not the drawing the kit's audit passed.
 *
 * What it writes, per asset:
 *   <out>/<family>/<name>.png         the base file, which is also frame one
 *   <out>/<family>/<name>_fNN.png     every other frame that differs from one
 *   <out>/<family>/<name>_back.png    rooms with a host anchor: everything
 *   <out>/<family>/<name>_front.png   behind him, and everything in front
 *   <out>/<family>/<name>.svg         only with --svg; the engine IS the source
 *
 * and, on stdout, the registry entries for all of it.
 */
"use strict";

const fs = require("fs");
const path = require("path");

/* Required as CommonJS modules, because that is how the kit wrote them.
 * port.js loads the plate engine, kit-model.js draws the rooms, and figure.js
 * draws the host. */
const ENGINE_MODULES = ["port.js", "kit-model.js", "figure.js"];

/* Loaded BY port.js, not by this driver, each with what it adds. They are named
 * because a round that port.js stops installing is a family of plates that
 * silently stops existing, and one it starts installing has to be looked at
 * before it reaches a video. The catalogue check in main() then proves the set
 * drawn here is exactly the set the kit's audit passed. */
const ENGINE_VIA_PORT = {
  "hand.js": "the hand every plate author draws with",
  "budget.js": "the type budgets; loaded before plates.js, whose manifest() derives every slot's maxChars from it",
  "plates.js": "the legacy plate authors",
  "build.js": "read as text for the legacy catalogue, never run",
  "plates-r1.js": "round one's authors, installed onto the same registry",
  "plates-r2.js": "round two: six software and six industrials sector plates",
  "plates-r3.js": "rounds three and four: a set per GICS sector, built out of round two's shapes",
  "sector-copy.js": "round four's plates as rows of data, read by plates-r3.js",
  "plates-r5.js": "round five: five new shapes, the banks and insurers, macro drivers, sector performance and said-vs-happened sets, the chapter bumper and source tag, the shorts plates and the wipes",
  "copy-r5.js": "round five's copy and sample series, and the sector variant of each shape, read by plates-r5.js",
};

/* Engine files that ship and are DELIBERATELY not run by this driver, each with
 * the reason. Named rather than merely absent so the check below can tell "we
 * decided not to load this" apart from "nobody noticed this arrived". */
const ENGINE_NOT_LOADED = {
  "audit.js": "the kit's own audit; ingest_kit.py runs it on a staged copy",
  "audit.legacy.js": "the delta-15 audit, kept by the kit for its old manifests",
  "audit.test.js": "the audit's own tests",
  "content.js": "the sample filing the review set is filled with; the bot fills every slot itself",
  "emit.js": "writes emit/ and the family manifests; ingest_kit.py runs its --check on a staged copy and passes --emit",
  "export.js": "writes the kit's blank files; ingest_kit.py runs it on a staged copy and passes --against",
  "kit-plates.js": "eleven flat-model exemplars the audit reads; sample type, no slots, not plates a shot can cut to",
  "series.js": "draws the review set's data layer; the bot draws every series itself (pipeline/chart.py)",
  "motion.js": "the thirteen moves as per-frame functions, played over a plate's slots by the renderer rather than drawn here; the data half, emit/motion.json, is read by ingest_kit.py",
};

/* THE HOUR THE KEYS DO NOT NAME. Every other hour is a suffix on the key,
 * inserted before the aspect: `cards/definition-16x9` at dusk is
 * `cards/definition-dusk-16x9`, and `host/to-camera-talk` is
 * `host/to-camera-talk-dusk`. That is the shape `Registry.at` resolves, so one
 * rule covers every plate. */
const BASE_HOUR = "night";

/* FAMILIES INSTALLED AS STILLS, each with the reason.
 *
 * The marks: ANSWERS.md §1 decided "the frame breathes, the mark does not", and
 * the operator approved exactly that. rebuild-19 and -20 still exported every
 * mark with three frames, the whole mark shifted a unit on frame two; since
 * rebuild-21 the kit draws them still/1/1 itself, once, at offset 0, and so
 * does this. */
const STILL_FAMILIES = {
  annotations: "ANSWERS.md §1: the mark does not move",
};

/* A WIPE IS DRAWN BY ITS PROGRESS, NOT ITS BOIL (rebuild-34). A plate whose
 * catalogue args carry `transition` is a fresh drawing per frame at these
 * steps of `t`, played ONCE at the kit's move rate, and the cut falls under
 * the frame its manifest names (`transition.cutAt`). These are emit.js's own
 * numbers, and the export check holds every frame to design's file. Drawn at
 * the rule offsets, a wipe is its midpoint, a full hatched cover boiling in
 * place; registered as a loop at the plate rate, its eight frames repeat every
 * 2.7 seconds instead of playing once. */
const TRANSITION_STEPS = [0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875, 1];
const TRANSITION_FPS = 12;

// The canvas a room is delivered on. The model draws rooms in a 320x180 box;
// every other plate in the library is 1920x1080 at exportScale 2, and a shot
// that mixes a room with a card must not need a resample step.
const ROOM_CANVAS = { "16x9": [1920, 1080], "9x16": [1080, 1920] };

function die(msg) {
  process.stderr.write("kit_engine: " + msg + "\n");
  process.exit(1);
}

function parseArgs(argv) {
  const out = { kit: "kit", out: null, only: null, svg: false, emit: null, against: null };
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--kit") out.kit = argv[++i];
    else if (a === "--out") out.out = argv[++i];
    else if (a === "--only") out.only = argv[++i];
    else if (a === "--emit") out.emit = argv[++i];
    else if (a === "--against") out.against = argv[++i];
    else if (a === "--svg") out.svg = true;
    else die("unknown argument " + a);
  }
  if (!out.out) die("--out is required");
  if (!out.emit) die("--emit is required: the rooms' anchors, windows and occlusion splits come off the kit's own emitter, never out of this file");
  return out;
}

/* A NEW ENGINE FILE MUST BE A DECISION, NOT A NO-OP.
 *
 * `budget.js` arrived in delta-10a carrying the whole type-budget derivation,
 * and not naming it failed nothing: BUDGET was undefined, the derivation was
 * skipped, and the build emitted slots with no budgets. The missing feature
 * was not the bug; nothing saying anything was. So a file in none of the three
 * lists stops the build here, where the message can name the actual choice. */
function accountForEngine(engineDir) {
  const known = new Set([...ENGINE_MODULES, ...Object.keys(ENGINE_VIA_PORT), ...Object.keys(ENGINE_NOT_LOADED)]);
  const stray = fs.readdirSync(engineDir).filter((f) => f.endsWith(".js") && !known.has(f)).sort();
  if (stray.length) {
    die(
      "engine file(s) not accounted for: " + stray.join(", ") + "\n" +
      "  Every .js in " + engineDir + " must be named in kit_engine.js: in\n" +
      "  ENGINE_MODULES to require it, in ENGINE_VIA_PORT if port.js loads it,\n" +
      "  or in ENGINE_NOT_LOADED with the reason the ingest does not run it. An\n" +
      "  unnamed file loads NOTHING and fails no check, so whatever it was meant\n" +
      "  to add is simply absent from the kit."
    );
  }
  for (const f of [...ENGINE_MODULES, ...Object.keys(ENGINE_VIA_PORT)]) {
    if (!fs.existsSync(path.join(engineDir, f))) die("missing engine file " + path.join(engineDir, f));
  }
}

/* The plate engine, exactly as emit.js and export.js hold it: port.js's own
 * global, with every round installed. */
function loadPort(engineDir) {
  const PORT = require(path.join(engineDir, "port.js"));
  const g = PORT.engine;
  if (!g || typeof PORT.catalogue !== "function" || typeof PORT.palFor !== "function") {
    die("port.js exports no engine, catalogue() or palFor(); the plate engine has to come off the kit");
  }
  if (!g.BUDGET) die("port.js loaded but BUDGET is not defined; every slot would lose its maxChars");
  if (!g.PLATES || !g.HAND) die("port.js loaded but PLATES/HAND are not defined");
  return PORT;
}

/* The rasteriser. resvg is a pure vector renderer and that is exactly what this
 * library needs: the plates carry no <text> node at all (every word on screen is
 * a slot the compositor fills), so there is no font resolution to get wrong.
 * Fonts are switched off deliberately — if a plate ever did emit text, a silent
 * fallback face would be worse than the blank it draws. */
function loadRasteriser() {
  let Resvg;
  try {
    Resvg = require("@resvg/resvg-js").Resvg;
  } catch (e) {
    die(
      "@resvg/resvg-js is not installed. It is a BUILD-time dependency only:\n" +
      "    npm ci      (or: npm install)\n" +
      "The render path never loads it — see the header of this file."
    );
  }
  /* THE LEAK WAS THE LOOP, NOT THE LIBRARY. Every render holds its 4K pixmap
   * in native memory, which the JS heap does not count, so V8 never feels the
   * pressure to collect; and the finalizer that frees it runs on a LATER TICK
   * of the event loop, which a synchronous loop never reaches. Measured on one
   * room drawn thirty times: +32 MB a render, 1 GB at thirty, with or without
   * a gc() — and flat at 84 MB with a gc() and one tick after each. That is
   * how one process drawing the library reached 13.5 GB and was killed, and
   * why the ingest was split one family per process. So every render is
   * collected and awaited before the next starts. */
  const gc = exposeGc();
  const raster = async function raster(svg, scale) {
    const png = new Resvg(svg, {
      fitTo: { mode: "zoom", value: scale },
      font: { loadSystemFonts: false },
      background: "rgba(0,0,0,0)",
    }).render().asPng();
    gc();
    await new Promise((resolve) => setImmediate(resolve));
    return png;
  };
  /* The ink box of an SVG as resvg lays it out, transforms applied — the
   * figure's head sits inside two of them, so a box read off the raw path
   * numbers is somewhere else. [x, y, w, h] in the SVG's user units. */
  raster.bbox = (svg) => {
    const b = new Resvg(svg, { font: { loadSystemFonts: false } }).getBBox();
    return b ? [b.x, b.y, b.width, b.height] : null;
  };
  /* Which pixels an SVG inks, at `width` pixels wide: 1 where alpha > half. */
  raster.mask = (svg, width) => {
    const img = new Resvg(svg, {
      fitTo: { mode: "width", value: width },
      font: { loadSystemFonts: false },
      background: "rgba(0,0,0,0)",
    }).render();
    const px = img.pixels, n = img.width * img.height, mask = new Uint8Array(n);
    for (let i = 0; i < n; i++) mask[i] = px[i * 4 + 3] > 127 ? 1 : 0;
    gc();
    return { mask, width: img.width, height: img.height };
  };
  return raster;
}

/* The collector, without asking the caller for a --expose-gc flag. */
function exposeGc() {
  if (typeof global.gc === "function") return global.gc;
  require("v8").setFlagsFromString("--expose-gc");
  const gc = require("vm").runInNewContext("gc");
  if (typeof gc !== "function") die("could not reach the garbage collector; run node with --expose-gc");
  return gc;
}

function mkdirp(d) { fs.mkdirSync(d, { recursive: true }); }

const pad = (n) => String(n).padStart(2, "0");

/* `cards/definition-16x9` at `dusk` -> `cards/definition-dusk-16x9`. */
function hourKey(key, hour) {
  if (hour === BASE_HOUR) return key;
  const m = /^(.*?)(-(?:16x9|9x16))?$/.exec(key);
  return m[1] + "-" + hour + (m[2] || "");
}

/* Design's export, blank since rebuild-17: the file must be this string. When
 * it is this string with data or type layers appended, the export has gone back
 * to burning the review set's sample filing in, and that is said by name. */
const SAMPLE_LAYERS = /^(?:<g data-layer="(?:data|type)">(?:(?!<g[\s>]).)*?<\/g>)*$/s;
function againstExport(svg, file) {
  if (!fs.existsSync(file)) return "the kit's export has no " + path.basename(file);
  const exp = fs.readFileSync(file, "utf8");
  if (exp === svg) return null;
  const close = "</svg>";
  const head = svg.slice(0, -close.length);
  if (svg.endsWith(close) && exp.startsWith(head) && exp.endsWith(close)
      && SAMPLE_LAYERS.test(exp.slice(head.length, -close.length))) {
    return "design's export burns sample content into " + path.basename(file) + " (data/type layers); the kit's files are meant to be blank";
  }
  return "differs from design's " + path.basename(file);
}

/* The paths of a flat SVG, in paint order, as [d, fill] pairs. */
function flatPaths(svg) {
  const out = [];
  const re = /<path d="([^"]*)"(?: fill="([^"]*)")?[^>]*\/>/g;
  let m;
  while ((m = re.exec(svg))) out.push([m[1], m[2] || "none"]);
  return out;
}

/* THE KEY IS DRAWN, NOT PUBLISHED. A plate that names its series in a legend
 * draws a short swatch in the series' ink just left of the label (`key()` in
 * plates-r2.js, and the swatched rows of its paired charts), and its manifest
 * carries the label's box but never the ink. The inks differ by plate:
 * book-to-bill and its sector copies key the second series in neutralData,
 * the other paired charts in down. A renderer that assumed one drew revenue in
 * a colour its own legend does not show. So the ink is read off the drawing:
 * a short stroke in a palette ink, wholly inside the swatch box left of a
 * `legend-N` or `row-N` label. Returned as {slot: registry palette role}. */
const KEY_INKS = { up: "up", down: "down", neutralData: "neutral-data", attention: "attention",
  otherParty: "other-party", structure: "structure" };
function keyInks(svg, slots, pal) {
  const roleOf = {};
  for (const [k, role] of Object.entries(KEY_INKS)) {
    if (typeof pal[k] === "string") roleOf[pal[k].toUpperCase()] = role;
  }
  const strokes = [];
  const re = /<path d="([^"]*)"([^>]*)\/>/g;
  let m;
  while ((m = re.exec(svg))) {
    const st = /\bstroke="(#[0-9A-Fa-f]{6})"/.exec(m[2]);
    const role = st && roleOf[st[1].toUpperCase()];
    if (!role) continue;
    const n = (m[1].match(/-?\d+(?:\.\d+)?/g) || []).map(Number);
    const xs = n.filter((_, i) => i % 2 === 0), ys = n.filter((_, i) => i % 2 === 1);
    if (!xs.length || !ys.length) continue;
    strokes.push({ x0: Math.min(...xs), x1: Math.max(...xs), y0: Math.min(...ys), y1: Math.max(...ys), role });
  }
  const keys = {};
  for (const [name, sl] of Object.entries(slots || {})) {
    if (!/^(legend|row)-\d+$/.test(name) || !sl || !(sl.w > 0)) continue;
    const roles = new Set(strokes.filter((s) => s.x1 - s.x0 >= 24 && s.x1 - s.x0 <= 60 && s.y1 - s.y0 <= 16
      && s.x0 >= sl.x - 64 && s.x1 <= sl.x - 4 && s.y0 >= sl.y - 6 && s.y1 <= sl.y + sl.h + 6).map((s) => s.role));
    if (roles.size === 1) keys[name] = [...roles][0];
  }
  return keys;
}

/* THE INK A KEYED LABEL PUBLISHES, as the palette role the swatch is drawn in.
 * Since rebuild-22 a legend or row label carries `ink`, the data ink role its
 * series is drawn in, and plates-r2.js's `key()` draws the swatch and publishes
 * the ink off ONE palette key; this is that map read backwards. */
const DATA_INK_ROLE = { subject: "up", subject2: "down", quiet: "neutral-data", attention: "attention",
  axis: "other-party" };

/* Frames to files: every distinct drawing gets one PNG, named after the first
 * frame that drew it, and the base file IS frame one — the same file, so a loop
 * entered from the base cannot pop. */
async function writeFrames(ctx, famDir, name, svgs, scale) {
  const { raster, args } = ctx;
  const fileOf = new Map();
  const files = [];
  for (let i = 0; i < svgs.length; i++) {
    let f = fileOf.get(svgs[i]);
    if (!f) {
      f = i === 0 ? name : name + "_f" + pad(i + 1);
      fileOf.set(svgs[i], f);
      fs.writeFileSync(path.join(famDir, f + ".png"), await raster(svgs[i], scale));
      if (args.svg) fs.writeFileSync(path.join(famDir, f + ".svg"), svgs[i]);
    }
    files.push(f);
  }
  return files.map((f) => ({ png: f + ".png", svg: args.svg ? f + ".svg" : null }));
}

// ---------------------------------------------------------------- content

async function drawContent(ctx, items, emitWrite) {
  const { g, tokens, hours, palFor, args, problems } = ctx;
  const offs = (tokens.motion && tokens.motion.dataRuleOffsets) || [0];
  // The kit's own rule (emit.js): a still family is drawn once, at offset 0.
  const offsFor = (family) => (STILL_FAMILIES[family] ? [0] : offs);
  const fps = (tokens.motion && tokens.motion.fps) || 0;
  let checked = 0;
  for (const it of items) {
    const family = it.key.split("/")[0];
    for (const hour of hours) {
      let P, m, svgs;
      const wipe = !!(it.args && it.args.transition);
      try {
        const draw = (extra) => g.PLATES[it.author](Object.assign({}, it.args, extra || {},
          { key: it.key, seed: it.seed, pal: palFor(tokens, hour) }));
        P = draw();
        m = P.manifest();
        if (wipe) {
          svgs = TRANSITION_STEPS.map((t) => draw({ t }).toSVG());
        } else {
          /* One draw per distinct offset, in the kit's order: a drawing that
           * consumes its seed as it goes has to be asked the same questions in
           * the same sequence to give the same answers. */
          const cache = {};
          svgs = offsFor(family).map((dy) => cache[dy] || (cache[dy] = P.toSVG({ ruleOffset: dy })));
        }
      } catch (e) {
        problems.push(it.key + " at " + hour + ": the engine failed to draw it (" + e.message + ")");
        continue;
      }
      if (svgs.some((s) => /<text[\s>]/.test(s))) problems.push(it.key + " at " + hour + ": carries a <text> node; every word on screen is a slot");
      if (!Array.isArray(m.canvas) || m.canvas[0] !== P.w || m.canvas[1] !== P.h) {
        problems.push(it.key + ": manifest canvas " + JSON.stringify(m.canvas) + " is not the drawing's " + P.w + "x" + P.h);
      }
      if (args.against) {
        const stem = path.basename(it.key) + "-" + hour;
        /* A still family exports its base file and no frames (rebuild-21:
         * emit.js draws the marks once, at offset 0). */
        const want = [[stem + ".svg", svgs[0]]].concat(STILL_FAMILIES[family] ? []
          : svgs.map((s, i) => [stem + "_f" + pad(i + 1) + ".svg", s]));
        for (const [file, svg] of want) {
          const why = againstExport(svg, path.join(args.against, it.dir, file));
          if (why) problems.push(it.key + " at " + hour + ": " + why);
        }
        checked++;
      }

      const key = hourKey(it.key, hour);
      const name = key.split("/").pop();
      const famDir = path.join(args.out, family);
      mkdirp(famDir);
      /* A plate whose frames are all one drawing is a still, and so is a family
       * the kit's own answers say does not move. Neither is a loop of copies. */
      const still = !!STILL_FAMILIES[family] || svgs.every((s) => s === svgs[0]);
      const drawn = await writeFrames(ctx, famDir, name, still ? svgs.slice(0, 1) : svgs, m.exportScale);
      const keys = keyInks(svgs[0], m.slots, palFor(tokens, hour));
      /* A KEY THAT LIES. A label that publishes its ink says which ink the data
       * layer draws its series in, so the swatch beside it must be that ink. A
       * label that publishes none is the older contract: the data layer draws
       * the first series in subject and nothing else, so a first label keyed in
       * another ink is keying a colour nothing on the plate is drawn in. */
      for (const [label, drawnIn] of Object.entries(keys)) {
        const said = m.slots[label] && m.slots[label].ink;
        if (said) {
          if (DATA_INK_ROLE[said] !== drawnIn) {
            problems.push(it.key + " at " + hour + ": " + label + " publishes ink " + said + " ("
              + (DATA_INK_ROLE[said] || "no palette role") + ") and its swatch is drawn in " + drawnIn);
          }
        } else if ((label === "legend-1" || label === "row-1") && drawnIn !== "up") {
          problems.push(it.key + " at " + hour + ": " + label + " keys the first series in " + drawnIn
            + ", and the data layer draws it in subject (up)");
        }
      }
      emitWrite(key, Object.assign({}, m, Object.keys(keys).length ? { keys } : {}, {
        family: family,
        author: it.author,
        seed: it.seed,
        surface: palFor(tokens, hour).surfaceKey,
        hour: hour,
        atBaseHour: it.key,
        playback: still ? "static" : wipe ? "once" : "loop",
        fps: still ? 0 : wipe ? TRANSITION_FPS : fps,
        frameCount: still ? 1 : svgs.length,
        frames: still ? [{ tag: "", png: drawn[0].png, svg: drawn[0].svg }]
          : drawn.map((d, i) => Object.assign({ tag: "_f" + pad(i + 1), png: d.png, svg: d.svg },
            wipe ? { t: TRANSITION_STEPS[i] } : { boil: offs[i] })),
        files: { png: drawn[0].png, svg: drawn[0].svg, baseIsFrame: still ? null : "_f01" },
        dir: family + "/",
      }));
    }
  }
  return checked;
}

// ------------------------------------------------------------------ rooms

/* A ROOM IS TWO LAYERS, because he stands BEHIND the desk. The kit publishes
 * the split as `occlusionSplit`: shapes before it are the room behind him,
 * shapes from it on are the furniture in front. A room drawn as one picture
 * and a host pasted over it puts him in front of his own desk. */
/* HOW MUCH OF HIS HEAD A ROOM PAINTS OVER, with him standing in it by the
 * contract: the 720-unit standing box scaled to the anchor's height, its top on
 * the anchor's top and its centre on the anchor's (DESIGN.md §2.5), and the
 * room's front layer — the shapes from the published split on — over him.
 *
 * rebuild-19's rooms were checked with nobody in them, and four list a wall
 * item after the desk, so the split puts a frame, a sheet or a shelf in front of
 * his face. This is the check that would have caught it; the ingest refuses a
 * room in a role whose number here is more than a sliver. Measured once, on the
 * base hour's plain standing pose: every hour is the same shapes, and the head
 * is where it is in every standing pose. */
const COVER_POSE = "to-camera";
const COVER_WIDTH = 1280;          // 4 px a room unit; the head is ~40 px tall
const SHOULDER_Y = 192;            // figure.js: crown 60 + 1.32 head units
function headCovered(ctx, r, e) {
  const { M, F, tokens, raster } = ctx;
  if (!e || !e.hostAnchor || typeof e.occlusionSplit !== "number") return null;
  const H0 = M.HOURS.find((h) => h.name === BASE_HOUR);
  const [bx, by, bw, bh] = F.BOX;
  const [ax, ay, aw, ah] = e.hostAnchor;
  const s = ah / bh, tx = ax + aw / 2 - (bx + bw / 2) * s, ty = ay - by * s;
  const fig = F.svg(M, COVER_POSE, H0, null, tokens).replace(/^<svg[^>]*>/, "").replace(/<\/svg>\s*$/, "");
  const room = (inner) => '<svg xmlns="http://www.w3.org/2000/svg" width="320" height="180" viewBox="0 0 320 180">' + inner + "</svg>";
  const him = raster.mask(room('<g transform="translate(' + tx + " " + ty + ") scale(" + s + ')">' + fig + "</g>"), COVER_WIDTH);
  const front = raster.mask(room(r.shapes.slice(e.occlusionSplit).map((sh) => '<path d="' + sh.d + '" fill="#000"/>').join("")), COVER_WIDTH);
  const k = him.width / 320, headRows = Math.round((ty + SHOULDER_Y * s) * k);
  let head = 0, covered = 0;
  for (let i = 0; i < him.mask.length && Math.floor(i / him.width) < headRows; i++) {
    if (!him.mask[i]) continue;
    head++;
    if (front.mask[i]) covered++;
  }
  return head ? +(covered / head).toFixed(3) : null;
}

async function drawRooms(ctx, emitWrite) {
  const { M, hours, raster, args, problems, emitted } = ctx;
  let checked = 0;
  const famDir = path.join(args.out, "room");
  mkdirp(famDir);
  for (const r of M.rooms()) {
    const covered = headCovered(ctx, r, emitted["room/" + r.id + "@" + BASE_HOUR + ".16x9"]);
    for (const hour of hours) {
      const H = M.HOURS.find((h) => h.name === hour);
      if (!H) { problems.push("kit-model.js draws no " + hour + " hour for the rooms"); continue; }
      const fill = (sh) => (sh.ink ? H.ink[sh.role] : H.m[sh.role][sh.tone === "shade" ? 1 : 0]);
      const nodes = r.shapes.map((sh) => [sh.d, fill(sh)]);
      const bad = nodes.filter((n) => !n[1]);
      if (bad.length) problems.push("room/" + r.id + " at " + hour + ": " + bad.length + " shape(s) name a role the hour has no colour for");

      if (args.against) {
        const file = path.join(args.against, "room", r.id + "-" + hour + ".svg");
        if (!fs.existsSync(file)) problems.push("room/" + r.id + " at " + hour + ": the kit's export has no " + path.basename(file));
        else if (JSON.stringify(flatPaths(fs.readFileSync(file, "utf8"))) !== JSON.stringify(nodes)) {
          problems.push("room/" + r.id + " at " + hour + ": the shapes differ from design's export");
        }
        checked++;
      }

      for (const aspect of ["16x9", "9x16"]) {
        const e = emitted["room/" + r.id + "@" + hour + "." + aspect];
        if (!e) { problems.push("room/" + r.id + " at " + hour + " " + aspect + ": the kit's emitter publishes no plate for it"); continue; }
        const [cw, ch] = ROOM_CANVAS[aspect];
        /* The portrait window is 98 x 174 units, which is 9:16 to within
         * 0.13%. Kept exact by extending it 0.2 units down rather than by
         * stretching the room: the width is the window's, the height follows. */
        const box = aspect === "16x9" ? [0, 0, 320, 180]
          : [e.box[0], e.box[1], e.box[2], +(e.box[2] * 16 / 9).toFixed(4)];
        const s = cw / box[2];
        const key = hourKey("room/" + r.id + "-" + aspect, hour);
        const name = key.split("/").pop();
        const svgOf = (list) => '<svg xmlns="http://www.w3.org/2000/svg" viewBox="' + box.join(" ") +
          '" width="' + cw + '" height="' + ch + '">' +
          list.map((n) => '<path d="' + n[0] + '" fill="' + n[1] + '"/>').join("") + "</svg>";

        const files = { png: name + ".png", svg: args.svg ? name + ".svg" : null, baseIsFrame: null };
        const whole = svgOf(nodes);
        fs.writeFileSync(path.join(famDir, files.png), await raster(whole, 2));
        if (args.svg) fs.writeFileSync(path.join(famDir, files.svg), whole);

        const entry = {
          canvas: [cw, ch], exportScale: 2, delivered: [cw * 2, ch * 2], aspect: aspect,
          family: "room", author: "kit-model.rooms", seed: null, surface: "set",
          hour: hour, atBaseHour: "room/" + r.id + "-" + aspect, angle: r.id,
          playback: "static", fps: 0, frameCount: 1,
          frames: [{ tag: "", png: files.png, svg: files.svg }],
          files: files, slots: {}, typeRoles: {}, dir: "room/",
          duskSafe: r.duskSafe === undefined ? null : !!r.duskSafe,
          hostAnchor: false,
          opener: !!r.opener,
        };

        /* THE TITLE SLOT (rebuild-21). A chapter opener is the room with the
         * chapter's title set in the room's `title` slot, and the card under it
         * is drawn into the room's back layer, so the slot is all the bot adds.
         * emit.js publishes it per aspect in canvas units; only `opener` rooms
         * have one. groundBox arrives as [x, y, w, h] and is carried as the
         * {x, y, w, h} every other slot's ground uses. */
        const table = (ctx.slotTables || {})["room/" + r.id + "-" + aspect];
        if (table && table.slots) {
          for (const [slotName, raw] of Object.entries(table.slots)) {
            const slot = Object.assign({}, raw);
            if (Array.isArray(slot.groundBox)) {
              const [gx, gy, gw, gh] = slot.groundBox;
              slot.groundBox = { x: gx, y: gy, w: gw, h: gh };
            }
            entry.slots[slotName] = slot;
          }
          Object.assign(entry.typeRoles, table.typeRoles || {});
        }
        if (r.opener && !entry.slots.title) {
          problems.push("room/" + r.id + " at " + hour + " " + aspect + ": the kit marks it a chapter opener and publishes no title slot for it");
        }

        if (e.hostAnchor) {
          const [ax, ay, aw, ah] = e.hostAnchor;
          const slot = {
            role: "host-anchor", region: true, scales: "host",
            note: "composite a host cut-out here. This region's HEIGHT is his target height: scale him so (host.floorLineY - host.slots.figure.y) equals it, then sit his floorLineY on this region's bottom edge. Width is advisory and never scales him.",
            x: Math.round((ax - box[0]) * s), y: Math.round((ay - box[1]) * s),
            w: Math.round(aw * s), h: Math.round(ah * s),
          };
          entry.slots["host-anchor"] = slot;
          entry.floorLineY = slot.y + slot.h;
          entry.hostAnchor = { targetHeight: slot.h, scales: "host.floorLineY - host.slots.figure.y" };
          if (covered !== null) entry.occlusion = { pose: COVER_POSE, headCovered: covered };
          if (typeof e.occlusionSplit === "number" && e.occlusionSplit > 0 && e.occlusionSplit <= nodes.length) {
            /* A split AT the shape count is a room with nothing in front of
             * him — board-side, where he stands at the near edge of the wall.
             * Its front layer is empty and is not drawn. */
            entry.layers = { back: name + "_back.png", split: e.occlusionSplit };
            fs.writeFileSync(path.join(famDir, entry.layers.back), await raster(svgOf(nodes.slice(0, e.occlusionSplit)), 2));
            if (e.occlusionSplit < nodes.length) {
              entry.layers.front = name + "_front.png";
              fs.writeFileSync(path.join(famDir, entry.layers.front), await raster(svgOf(nodes.slice(e.occlusionSplit)), 2));
            }
          } else {
            // Anchored and no split. Drawn, and said: the kit's own audit fails
            // a room like this (rule 15), so it is design's to decide, not
            // something to paper over by guessing a split.
            entry.layers = null;
            entry.layersNote = "the kit publishes no occlusion split for this anchored room, so nothing is drawn in front of him";
          }
        }
        emitWrite(key, entry);
      }
    }
  }
  return checked;
}

// ------------------------------------------------------------------- host

/* THE HOST, DRAWN BY THE KIT'S OWN PAINT ORDER AND CHECKED AGAINST HIS MODEL.
 *
 * rebuild-14 exported eleven of twelve poses as a head cut off at the neck, the
 * seated pose empty, no face on any of them and no strip moving — every check
 * the kit ran passed, because none of them asked what the figure IS. So the
 * questions here are asked of `kit-model.js`, not of `figure.js`, and a
 * drawing that fails one is refused however it got made:
 *
 *   the ink lies inside the figure box, and the feet on its bottom edge
 *   the eyes, the glasses and a mouth are drawn                (a face)
 *   the still is one frame; talk shows an open mouth; every moving strip moves
 *
 * THE BOX IS THE STANDING BOX FOR EVERY POSE (DESIGN.md §2.5): 720 units from
 * the box top to the floor line, the crown padded below the top. The anchor
 * solve scales by `floorLineY - figure.y`, so a seated pose publishing its own
 * shorter box would be scaled up a third and change size between two cuts in
 * one room. */
async function drawHost(ctx, emitWrite) {
  const { M, F, tokens, hours, args, problems } = ctx;
  const [bx, by, bw, bh] = F.BOX;
  const famDir = path.join(args.out, "host");
  mkdirp(famDir);
  let checked = 0;
  const fails = { box: [], floor: [], face: [], still: [], mouth: [], moves: [] };
  for (const hour of hours) {
    const H = M.HOURS.find((h) => h.name === hour);
    if (!H) { problems.push("kit-model.js draws no " + hour + " hour for the host"); continue; }
    for (const pose of M.poseKeys) {
      const G = M.geometry(pose);
      /* Frames already drawn for this pose at this hour, by drawing: the still,
       * the first frame of talk, of idle and of blink are one picture, and one
       * file serves all four. */
      const drawnPose = new Map();
      for (const strip of F.STRIPS) {
        const baseKey = "host/" + pose + strip.suffix;
        const at = baseKey + " at " + hour;
        const frames = F.framesOf(strip.suffix, tokens);
        const svgs = frames.map((fr) => F.svg(M, pose, H, fr, tokens));

        if (strip.suffix === "") {
          const ink = F.inkBoxOfSvg(svgs[0]);
          if (!ink || ink[0] < bx - 1 || ink[1] < by - 1 || ink[2] > bx + bw + 1 || ink[3] > by + bh + 1) {
            fails.box.push(at + " (ink " + JSON.stringify(ink) + " against the box " + JSON.stringify(F.BOX) + ")");
          } else if (Math.abs(ink[3] - (by + bh)) > 1) {
            fails.floor.push(at + " (his lowest ink is at " + ink[3] + ", the floor at " + (by + bh) + ")");
          }
          const face = [].concat(G.eyes || [], G.glasses || [], [G.mouthClosed]);
          if (!face.length || !face.every((d) => d && svgs[0].indexOf(d) >= 0)) fails.face.push(at);
          if (svgs.length !== 1) fails.still.push(at + " (" + svgs.length + " frames)");
        } else if (svgs.every((s) => s === svgs[0])) {
          fails.moves.push(at);
        }
        if (strip.suffix === "-talk" && !svgs.some((s) => [G.mouthMid, G.mouthWide].some((d) => d && s.indexOf(d) >= 0))) {
          fails.mouth.push(at);
        }

        if (args.against) {
          const stem = pose + strip.suffix + "-" + hour;
          const want = [[stem + ".svg", svgs[0]]].concat(svgs.length > 1
            ? svgs.map((s, i) => [stem + "_f" + pad(i + 1) + ".svg", s]) : []);
          for (const [file, svg] of want) {
            const why = againstExport(svg, path.join(args.against, "host", file));
            if (why) problems.push(at + ": " + why);
          }
          checked++;
        }

        const key = hourKey(baseKey, hour);
        const name = key.split("/").pop();
        const files = [];
        for (let i = 0; i < svgs.length; i++) {
          let f = drawnPose.get(svgs[i]);
          if (!f) {
            f = i === 0 ? name : name + "_f" + pad(i + 1);
            drawnPose.set(svgs[i], f);
            fs.writeFileSync(path.join(famDir, f + ".png"), await ctx.raster(svgs[i], 2));
            if (args.svg) fs.writeFileSync(path.join(famDir, f + ".svg"), svgs[i]);
          }
          files.push(f);
        }
        const still = strip.playback === "still";
        emitWrite(key, {
          canvas: [bw, bh], exportScale: 2, delivered: [bw * 2, bh * 2], aspect: "",
          family: "host", author: "figure.svg", seed: null, surface: "set",
          hour: hour, atBaseHour: baseKey, pose: pose, strip: strip.suffix.slice(1) || "still",
          /* The kit's words for the three ways a strip plays, in the
           * registry's: a still is `static`, and a blink is an `overlay`
           * nothing may play as a loop in its own right. */
          playback: still ? "static" : strip.playback,
          fps: still ? 0 : strip.fps,
          frameCount: svgs.length,
          /* WHICH MOUTH, not only whether it is open. rebuild-31 draws six
           * (closed, mid, wide, O, EE, F/V), and a frame that said only
           * `mouthOpen` threw away the five shapes a voice can choose from. */
          frames: frames.map((fr, i) => ({
            tag: still ? "" : "_f" + pad(i + 1),
            png: files[i] + ".png", svg: args.svg ? files[i] + ".svg" : null,
            mouthOpen: fr.mouth !== "mouthClosed", mouth: fr.mouth, eyes: fr.eyes, bob: fr.shoulderY || 0,
          })),
          files: { png: files[0] + ".png", svg: args.svg ? files[0] + ".svg" : null, baseIsFrame: still ? null : "_f01" },
          /* A cut-out: composited onto a room, never over one. */
          alpha: true,
          /* The floor is the box's bottom edge — every pose's feet end there,
           * which the check above holds him to. */
          floorLineY: bh,
          slots: {
            figure: {
              role: "figure", region: true, x: 0, y: 0, w: bw, h: bh,
              note: "the STANDING figure box (DESIGN.md §2.5), the same for every pose: scale so (floorLineY - figure.y) is the room anchor's height",
            },
          },
          typeRoles: {}, dir: "host/",
        });
      }
    }
  }
  const say = (list, what) => {
    if (list.length) problems.push("host: " + list.length + " " + what + ", e.g. " + list.slice(0, 3).join("; "));
  };
  say(fails.box, "pose(s) drawn outside the figure box");
  say(fails.floor, "pose(s) whose feet are not on the floor line");
  say(fails.face, "pose(s) with no eyes, glasses or mouth drawn");
  say(fails.still, "still strip(s) with more than one frame");
  say(fails.moves, "talk/idle/blink strip(s) whose frames are all one drawing");
  say(fails.mouth, "talk strip(s) that never open the mouth");
  return checked;
}

/* THE CLOSE SHOT IS A WINDOW ON THE FIGURE, NOT A DRAWING. ANSWERS.md §4: the
 * rebuild dropped the drawn close-up, because the figure is one shape list at
 * one proportion and any framing is a window onto it, and design then looked at
 * that window at delivered scale ("Close Crop Review") and it reads. The kit
 * exports no such file, so it is drawn here, through figure.js's own paint order,
 * by the review's own measurements:
 *
 *   head plus the shoulder line, off the pose's own head: a pad of 0.22 head
 *   units round it, one head unit being his ink height over P.totalHeight
 *
 *   the contour thinned by how far the review's window crops in (k = its width
 *   over 320), because one contour width in figure units is a heavier line on
 *   screen the closer the camera gets — the review's own rule
 *
 * and then widened to the whole figure box and run further down his chest, so
 * the plate has no cut edge a frame can show. A framing goes in with his eyes on
 * the upper third and its bottom edge off the bottom of the frame
 * (`pipeline/host.frame_shot`); the review's window stops 0.42 head units under
 * the shoulder, and cut there it floats a straight line across his chest in a
 * 16:9 frame. The review's window is kept on the plate as `fit.reviewWindow`.
 *
 * THE POSE IS `to-camera`, the one the review looked at. Every strip is drawn
 * through the window, so the close-up talks, idles and blinks — and ANSWERS.md
 * §4's second finding (never hold close on the still, whose closed mouth is a
 * dash at this size) is a rule on the shot list, not a gap in the files. */
const CLOSE = {
  key: "host/close-up",
  pose: "to-camera",
  unit: 4,            // canvas units per figure unit; x2 delivered
  pad: 0.22,          // head units round the head, the review's
  depth: 3.4,         // head units from the window's top edge to its bottom
  reviewWidth: 320,   // the review's full-frame window width, for the contour
};

async function drawClose(ctx, emitWrite) {
  const { M, F, tokens, hours, raster, args, problems } = ctx;
  if (M.poseKeys.indexOf(CLOSE.pose) < 0) {
    problems.push(CLOSE.key + ": the kit draws no " + CLOSE.pose + " pose to frame it from");
    return;
  }
  const G = M.geometry(CLOSE.pose);
  const H0 = M.HOURS.find((h) => h.name === BASE_HOUR);
  const root = (svg) => (svg.match(/^<svg [^>]*>/) || [""])[0];
  const headOf = (svg) => {
    /* figure.js closes every drawing with the head group — the neck's
     * translate/rotate round the skull's headT — so the last one is his head. */
    const i = svg.lastIndexOf('<g transform="translate(0 ');
    return i < 0 ? null : svg.slice(i, svg.length - "</svg>".length);
  };
  const still = F.svg(M, CLOSE.pose, H0, null, tokens);
  const head = headOf(still);
  if (!head || !head.endsWith("</g></g>")) {
    problems.push(CLOSE.key + ": figure.js no longer closes the drawing with the head group, so there is no head to frame");
    return;
  }
  const wrap = (inner) => root(still) + inner + "</svg>";
  const fig = raster.bbox(still);
  const hb = raster.bbox(wrap(head));
  const eb = raster.bbox(wrap('<g transform="' + (G.headT || "") + '">' +
    (G.eyes || []).map((d) => '<path d="' + d + '"/>').join("") + "</g>"));
  if (!fig || !hb || !eb) {
    problems.push(CLOSE.key + ": could not measure " + CLOSE.pose + "'s head or eyes");
    return;
  }

  const HU = fig[3] / M.P.totalHeight;
  const margin = HU * CLOSE.pad;
  const review = [hb[0] + hb[2] / 2 - (hb[2] + margin * 2.6) / 2, hb[1] - margin,
    hb[2] + margin * 2.6, (M.P.shoulderFromCrown + 0.42) * HU + margin].map((v) => Math.round(v));
  const k = review[2] / CLOSE.reviewWidth;
  const [bx, , bw] = F.BOX;
  const win = [bx, review[1], bw, Math.round(CLOSE.depth * HU)];
  const u = CLOSE.unit;
  const canvas = [win[2] * u, win[3] * u];
  const at = (v, o) => Math.round((v - o) * u);

  /* One contour weight, every part, from the tokens — the same expression
   * figure.js writes, so the string it wrote is the string replaced here. */
  const cw = ((tokens.contourWeight && tokens.contourWeight.value) || 0.035) * 100;
  const weight = 'stroke-width="' + cw + '"';
  if (still.indexOf(weight) < 0) {
    problems.push(CLOSE.key + ": figure.js no longer strokes at the token contour weight (" + cw + "), so the close-up cannot thin it");
    return;
  }
  const closer = (svg) => '<svg xmlns="http://www.w3.org/2000/svg" width="' + win[2] + '" height="' + win[3] +
    '" viewBox="' + win.join(" ") + '">' + svg.slice(root(svg).length).split(weight).join('stroke-width="' + (cw * k).toFixed(3) + '"');

  const mouths = [G.mouthClosed, G.mouthMid, G.mouthWide, G.mouthO, G.mouthEE, G.mouthFV].filter(Boolean);
  const mb = raster.bbox(wrap('<g transform="' + (G.headT || "") + '">' +
    mouths.map((d) => '<path d="' + d + '"/>').join("") + "</g>"));
  const slots = {
    head: { role: "head", region: true, x: at(hb[0], win[0]), y: at(hb[1], win[1]), w: Math.round(hb[2] * u), h: Math.round(hb[3] * u),
      note: "his head, hair to chin: a framing is scaled so THIS is the fraction of frame height the shot wants" },
    eyes: { role: "eyes", region: true, x: at(eb[0], win[0]), y: at(eb[1], win[1]), w: Math.round(eb[2] * u), h: Math.round(eb[3] * u),
      note: "the pair; the eye line is fit.eyeLineY" },
    figure: { role: "figure", region: true, x: 0, y: 0, w: canvas[0], h: canvas[1],
      note: "visible extent only. A framing has no floor line, and this box is not a scaling authority: see fit" },
  };
  if (mb) slots.mouth = { role: "mouth", region: true, x: at(mb[0], win[0]), y: at(mb[1], win[1]), w: Math.round(mb[2] * u), h: Math.round(mb[3] * u),
    note: "every mouth the talk strip draws: closed, mid, wide, O, EE and F/V" };
  const eyeLineY = at(eb[1] + eb[3] / 2, win[1]);

  const famDir = path.join(args.out, "host");
  mkdirp(famDir);
  for (const hour of hours) {
    const H = M.HOURS.find((h) => h.name === hour);
    if (!H) continue;     // drawHost has said so
    const drawn = new Map();
    for (const strip of F.STRIPS) {
      const baseKey = CLOSE.key + strip.suffix;
      const frames = F.framesOf(strip.suffix, tokens);
      const full = frames.map((fr) => F.svg(M, CLOSE.pose, H, fr, tokens));
      /* The window holds his whole head on every frame, and the only edge of
       * the plate his ink reaches is the bottom one, which the frame hides. */
      for (let i = 0; i < full.length; i++) {
        const h = raster.bbox(wrap(headOf(full[i])));
        const b = raster.bbox(full[i]);
        const inside = h && h[0] > win[0] && h[1] > win[1] && h[0] + h[2] < win[0] + win[2] && h[1] + h[3] < win[1] + win[3];
        const clear = b && b[0] > win[0] && b[0] + b[2] < win[0] + win[2] && b[1] > win[1];
        if (!inside || !clear) {
          problems.push(hourKey(baseKey, hour) + " frame " + (i + 1) + ": the close window " + JSON.stringify(win) +
            (inside ? " cuts his figure at a side or the top" : " does not hold his whole head"));
        }
      }
      const svgs = full.map(closer);
      const key = hourKey(baseKey, hour);
      const name = key.split("/").pop();
      const files = [];
      for (let i = 0; i < svgs.length; i++) {
        let f = drawn.get(svgs[i]);
        if (!f) {
          f = i === 0 ? name : name + "_f" + pad(i + 1);
          drawn.set(svgs[i], f);
          fs.writeFileSync(path.join(famDir, f + ".png"), await raster(svgs[i], u * 2));
          if (args.svg) fs.writeFileSync(path.join(famDir, f + ".svg"), svgs[i]);
        }
        files.push(f);
      }
      const still = strip.playback === "still";
      emitWrite(key, {
        canvas: canvas, exportScale: 2, delivered: [canvas[0] * 2, canvas[1] * 2], aspect: "",
        family: "host", author: "figure.svg", seed: null, surface: "set",
        hour: hour, atBaseHour: baseKey, pose: CLOSE.pose, strip: strip.suffix.slice(1) || "still",
        framing: "close-up", glance: "to camera",
        playback: still ? "static" : strip.playback,
        fps: still ? 0 : strip.fps,
        frameCount: svgs.length,
        frames: frames.map((fr, i) => ({
          tag: still ? "" : "_f" + pad(i + 1),
          png: files[i] + ".png", svg: args.svg ? files[i] + ".svg" : null,
          mouthOpen: fr.mouth !== "mouthClosed", mouth: fr.mouth, eyes: fr.eyes, bob: fr.shoulderY || 0,
        })),
        files: { png: files[0] + ".png", svg: args.svg ? files[0] + ".svg" : null, baseIsFrame: still ? null : "_f01" },
        alpha: true,
        /* A camera distance: nothing to stand on a floor. */
        floorLineY: false,
        fit: {
          mode: "eye-line", eyeLineY: eyeLineY, eyeLineFraction: +(eyeLineY / canvas[1]).toFixed(4),
          window: win, reviewWindow: review, contourScale: +k.toFixed(4),
          note: "a window on " + CLOSE.pose + " (ANSWERS.md §4): scale so slots.head is the fraction of frame height the shot wants, put eyeLineY on the upper third, and keep the bottom edge off the bottom of the frame",
        },
        slots: slots,
        typeRoles: {}, dir: "host/",
      });
    }
  }
}

async function main() {
  const args = parseArgs(process.argv);
  args.out = path.resolve(args.out);
  const kitDir = path.resolve(args.kit);
  const engineDir = path.join(kitDir, "engine");
  accountForEngine(engineDir);

  const PORT = loadPort(engineDir);
  const g = PORT.engine;
  const M = require(path.join(engineDir, "kit-model.js"));
  const F = require(path.join(engineDir, "figure.js"));
  const tokens = JSON.parse(fs.readFileSync(path.join(kitDir, "design-tokens.json"), "utf8"));
  const hours = Object.keys(tokens.hours || {}).filter((h) => !h.startsWith("_"));
  if (hours[0] !== BASE_HOUR) die("design-tokens.json lists hours " + JSON.stringify(hours) + "; the keys assume " + BASE_HOUR + " comes first");

  const emitted = {};
  for (const p of JSON.parse(fs.readFileSync(args.emit, "utf8")).plates || []) emitted[p.id] = p;

  const ctx = { g, M, F, tokens, hours, palFor: PORT.palFor, raster: loadRasteriser(), args, problems: [], emitted };

  /* THE CATALOGUE is the kit's own — the list emit.js and export.js walk —
   * without the drawn kit's host and rooms, which are rebuilt flat. It has to
   * be exactly the set of plates the audit passed: a plate the audit saw and
   * this does not draw is missing from every video, and one this draws that the
   * audit never saw is unchecked art. */
  const content = PORT.catalogue().filter((x) => x.dir !== "host" && x.dir !== "room");
  const slotsFile = path.join(kitDir, "emit", "slots.json");
  if (fs.existsSync(slotsFile)) {
    ctx.slotTables = JSON.parse(fs.readFileSync(slotsFile, "utf8")).plates || {};
    /* Rooms publish slot tables too since rebuild-21 (an opener's title), and
     * they are drawn by drawRooms from kit-model, not from this catalogue. */
    const audited = new Set(Object.keys(ctx.slotTables).filter((k) => !k.startsWith("room/") && !k.startsWith("host/")));
    const drawn = new Set(content.map((x) => x.key));
    const unseen = [...drawn].filter((k) => !audited.has(k)).sort();
    const undrawn = [...audited].filter((k) => !drawn.has(k)).sort();
    if (unseen.length) ctx.problems.push(unseen.length + " plate(s) in port.js's catalogue have no slot table in emit/slots.json, so the audit never saw them: " + unseen.slice(0, 4).join(", "));
    if (undrawn.length) ctx.problems.push(undrawn.length + " plate(s) in emit/slots.json are not in port.js's catalogue, so nothing draws them: " + undrawn.slice(0, 4).join(", "));
  } else {
    ctx.problems.push("the kit ships no emit/slots.json, so nothing says which plates its audit passed");
  }

  const families = Array.from(new Set(content.map((x) => x.key.split("/")[0]).concat(["room", "host"]))).sort();
  if (args.only && families.indexOf(args.only) < 0) {
    die("--only " + args.only + " is not a family this kit draws (" + families.join(", ") + ")");
  }

  const assets = {};
  const write = (key, entry) => {
    if (assets[key]) ctx.problems.push(key + ": drawn twice");
    assets[key] = entry;
  };
  let checked = 0;
  const want = (fam) => !args.only || args.only === fam;
  checked += await drawContent(ctx, content.filter((x) => want(x.key.split("/")[0])), write);
  if (want("room")) checked += await drawRooms(ctx, write);
  if (want("host")) {
    checked += await drawHost(ctx, write);
    await drawClose(ctx, write);
  }

  const palettes = {};
  for (const hour of hours) {
    const p = PORT.palFor(tokens, hour);
    palettes[hour] = {
      "ground": p.ground, "second-ground": p.ground2, "structure": p.structure, "down": p.down,
      "up": p.up, "neutral-data": p.neutralData, "attention": p.attention, "other-party": p.otherParty,
    };
  }

  process.stdout.write(JSON.stringify({
    kit: "dennis-v2",
    layout: "rebuild",
    tokens: tokens.version || null,
    generated: new Date().toISOString().slice(0, 10),
    engine: {
      source: path.relative(process.cwd(), engineDir),
      note: "build-time only — the render path reads PNGs and this registry, never JS",
    },
    exportScale: 2,
    hours: hours,
    hourSuffixes: Object.fromEntries(hours.map((h) => [h, h === BASE_HOUR ? "" : "-" + h])),
    palette: { surface: "night-card", roles: palettes[BASE_HOUR] },
    palettes: palettes,
    families: families,
    assets: assets,
    checkedAgainstExport: checked,
    problems: ctx.problems,
  }));
  process.stderr.write("kit_engine: " + Object.keys(assets).length + " plates" +
    (args.only ? " (" + args.only + ")" : "") + ", " + checked + " checked against the kit's export, " +
    ctx.problems.length + " problem(s)\n");
}

main().catch((e) => die(e && e.stack ? e.stack : String(e)));
