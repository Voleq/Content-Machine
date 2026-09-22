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
 * THE KIT IS CODE, NOT PICTURES, and this is the rebuild layout of it: the
 * content plates are the legacy authors in `plates.js` plus the round-one
 * authors in `plates-r1.js`, recoloured per hour through `port.js`'s palette
 * map; the rooms and the host are the flat model in `kit-model.js`. Every
 * plate exists at every hour in `design-tokens.json`, so every plate is drawn
 * once per hour here.
 *
 * WHY THE KIT'S OWN EXPORT IS NOT WHAT GETS INSTALLED. `engine/export.js` burns
 * sample content into its files, 390 of 536 of them: the fictional filing's
 * text and its chart data. It is a review set. This draws the same authors
 * with the same arguments and stops before the content, which is the plate the
 * compositor fills. `--against` then proves that is all that differs: every
 * blank plate drawn here must be design's exported file byte for byte, minus
 * the `data` and `type` layers the export appends. A plate that differs in
 * anything else is not the drawing the kit's audit passed.
 *
 * What it writes, per asset:
 *   <out>/<family>/<name>.png         the base file, which is also frame one
 *   <out>/<family>/<name>_back.png    rooms with a host anchor: everything
 *   <out>/<family>/<name>_front.png   behind him, and everything in front
 *   <out>/<family>/<name>.svg         only with --svg; the engine IS the source
 *
 * and, on stdout, the registry entries for all of it.
 */
"use strict";

const fs = require("fs");
const path = require("path");

/* Loaded into ONE shared global, in this order — the order the kit's own
 * export.js and port.js load them. `budget.js` before `plates.js` is load-
 * bearing: `Plate.manifest()` derives every slot's type budget behind an
 * `if (g.BUDGET && ...)` guard, so a BUDGET that has not loaded yet is not an
 * error, it is 103 plates with no maxChars and a reconcile that blames the
 * geometry. `build.js` last: its catalogue names authors the others define. */
const ENGINE_FILES = ["hand.js", "budget.js", "plates.js", "plates-r1.js", "build.js"];

/* Required as CommonJS modules, because that is how the kit wrote them.
 * kit-model draws the rooms and the host; port exports the palette map. */
const ENGINE_MODULES = ["kit-model.js", "port.js"];

/* Engine files that ship and are DELIBERATELY not run by this driver, each with
 * the reason. Named rather than merely absent so the check below can tell "we
 * decided not to load this" apart from "nobody noticed this arrived". */
const ENGINE_NOT_LOADED = {
  "audit.js": "the kit's own 24-rule check; ingest_kit.py runs it on a staged copy",
  "audit.legacy.js": "the delta-15 audit, kept by the kit for its old manifests",
  "audit.test.js": "the audit's own tests",
  "content.js": "the sample filing the review set is filled with; the bot fills every slot itself",
  "emit.js": "writes emit/ for the audit; ingest_kit.py runs it on a staged copy and passes --emit",
  "export.js": "the review set, sample content burned in; ingest_kit.py runs it on a staged copy and passes --against",
  "kit-plates.js": "eleven flat-model exemplars the audit reads; sample type, no slots, not plates a shot can cut to",
  "series.js": "draws the review set's data layer; the bot draws every series itself (pipeline/series.py)",
};

/* THE HOUR THE KEYS DO NOT NAME. Every other hour is a suffix on the key,
 * inserted before the aspect: `cards/definition-16x9` at dusk is
 * `cards/definition-dusk-16x9`. That is the shape `Registry.at_hour` and
 * `aspect_key` already resolve for rooms, so one rule covers every plate. */
const BASE_HOUR = "night";

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
  const known = new Set([...ENGINE_FILES, ...ENGINE_MODULES, ...Object.keys(ENGINE_NOT_LOADED)]);
  const stray = fs.readdirSync(engineDir).filter((f) => f.endsWith(".js") && !known.has(f)).sort();
  if (stray.length) {
    die(
      "engine file(s) not accounted for: " + stray.join(", ") + "\n" +
      "  Every .js in " + engineDir + " must be named in kit_engine.js: in\n" +
      "  ENGINE_FILES to load it into the shared global (order matters), in\n" +
      "  ENGINE_MODULES to require it, or in ENGINE_NOT_LOADED with the reason\n" +
      "  the ingest does not run it. An unnamed file loads NOTHING and fails no\n" +
      "  check, so whatever it was meant to add is simply absent from the kit."
    );
  }
  for (const f of [...ENGINE_FILES, ...ENGINE_MODULES]) {
    if (!fs.existsSync(path.join(engineDir, f))) die("missing engine file " + path.join(engineDir, f));
  }
}

/* The shared global, loaded the way export.js loads it: each file is a function
 * of (window, globalThis, module) and hangs itself off the first. */
function loadEngine(engineDir) {
  const g = {};
  for (const f of ENGINE_FILES) {
    const src = fs.readFileSync(path.join(engineDir, f), "utf8");
    // eslint-disable-next-line no-new-func
    new Function("window", "globalThis", "module", src)(g, g, { exports: {} });
  }
  if (!g.BUDGET) die("budget.js loaded but BUDGET is not defined; every slot would lose its maxChars");
  if (!g.PLATES || !g.HAND || !g.BUILD) die("engine loaded but PLATES/HAND/BUILD are not defined");
  if (!g.PLATES_R1 || typeof g.PLATES_R1.install !== "function") die("plates-r1.js loaded but PLATES_R1.install is not defined");
  g.PLATES_R1.install(g.PLATES, g.HAND);
  return g;
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
  return async function raster(svg, scale) {
    const png = new Resvg(svg, {
      fitTo: { mode: "zoom", value: scale },
      font: { loadSystemFonts: false },
      background: "rgba(0,0,0,0)",
    }).render().asPng();
    gc();
    await new Promise((resolve) => setImmediate(resolve));
    return png;
  };
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

/* `cards/definition-16x9` at `dusk` -> `cards/definition-dusk-16x9`. */
function hourKey(key, hour) {
  if (hour === BASE_HOUR) return key;
  const m = /^(.*?)(-(?:16x9|9x16))?$/.exec(key);
  return m[1] + "-" + hour + (m[2] || "");
}

/* Design's export, blank. The export is `toSVG()` with the data and type
 * layers inserted before the closing tag, and nothing else, so the file minus
 * those layers must be this string exactly. */
const SAMPLE_LAYERS = /^(?:<g data-layer="(?:data|type)">(?:(?!<g[\s>]).)*?<\/g>)*$/s;
function againstExport(svg, file) {
  if (!fs.existsSync(file)) return "the kit's export has no " + path.basename(file);
  const exp = fs.readFileSync(file, "utf8");
  const close = "</svg>";
  if (!svg.endsWith(close)) return "the engine's SVG does not end in </svg>";
  const head = svg.slice(0, -close.length);
  if (!exp.startsWith(head) || !exp.endsWith(close)) {
    return "the blank drawing differs from design's export before the sample layers";
  }
  if (!SAMPLE_LAYERS.test(exp.slice(head.length, -close.length))) {
    return "design's export appends something other than its data and type layers";
  }
  return null;
}

/* The paths of a flat SVG, in paint order, as [d, fill] pairs. */
function flatPaths(svg) {
  const out = [];
  const re = /<path d="([^"]*)"(?: fill="([^"]*)")?[^>]*\/>/g;
  let m;
  while ((m = re.exec(svg))) out.push([m[1], m[2] || "none"]);
  return out;
}

// ---------------------------------------------------------------- content

async function drawContent(ctx, items, emitWrite) {
  const { g, tokens, hours, palFor, raster, args, problems } = ctx;
  let checked = 0;
  for (const it of items) {
    for (const hour of hours) {
      let P, svg, m;
      try {
        P = g.PLATES[it.author](Object.assign({}, it.args, { key: it.key, seed: it.seed, pal: palFor(tokens, hour) }));
        svg = P.toSVG();
        m = P.manifest();
      } catch (e) {
        problems.push(it.key + " at " + hour + ": the engine failed to draw it (" + e.message + ")");
        continue;
      }
      if (/<text[\s>]/.test(svg)) problems.push(it.key + " at " + hour + ": carries a <text> node; every word on screen is a slot");
      if (!Array.isArray(m.canvas) || m.canvas[0] !== P.w || m.canvas[1] !== P.h) {
        problems.push(it.key + ": manifest canvas " + JSON.stringify(m.canvas) + " is not the drawing's " + P.w + "x" + P.h);
      }
      if (args.against) {
        const file = path.join(args.against, it.dir, path.basename(it.key) + "-" + hour + ".svg");
        const why = againstExport(svg, file);
        if (why) problems.push(it.key + " at " + hour + ": " + why);
        checked++;
      }

      const key = hourKey(it.key, hour);
      const family = it.key.split("/")[0];
      const name = key.split("/").pop();
      const famDir = path.join(args.out, family);
      mkdirp(famDir);
      fs.writeFileSync(path.join(famDir, name + ".png"), await raster(svg, m.exportScale));
      if (args.svg) fs.writeFileSync(path.join(famDir, name + ".svg"), svg);

      /* WHAT WAS DRAWN, not what the kit's review manifest declares. The
       * rebuild's manifest says the data plates loop at 3fps over three
       * frames, and no engine file draws a second frame, so the only honest
       * entry is the one frame that exists. */
      emitWrite(key, Object.assign({}, m, {
        family: family,
        author: it.author,
        seed: it.seed,
        surface: palFor(tokens, hour).surfaceKey,
        hour: hour,
        atBaseHour: it.key,
        playback: "static",
        fps: 0,
        frameCount: 1,
        frames: [{ tag: "", png: name + ".png", svg: args.svg ? name + ".svg" : null }],
        files: { png: name + ".png", svg: args.svg ? name + ".svg" : null, baseIsFrame: null },
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
async function drawRooms(ctx, emitWrite) {
  const { M, hours, raster, args, problems, emitted } = ctx;
  let checked = 0;
  const famDir = path.join(args.out, "room");
  mkdirp(famDir);
  for (const r of M.rooms()) {
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
        };

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
          if (typeof e.occlusionSplit === "number" && e.occlusionSplit > 0 && e.occlusionSplit < nodes.length) {
            const back = svgOf(nodes.slice(0, e.occlusionSplit));
            const front = svgOf(nodes.slice(e.occlusionSplit));
            entry.layers = { back: name + "_back.png", front: name + "_front.png", split: e.occlusionSplit };
            fs.writeFileSync(path.join(famDir, entry.layers.back), await raster(back, 2));
            fs.writeFileSync(path.join(famDir, entry.layers.front), await raster(front, 2));
          } else {
            // Anchored and nothing in front of him. Drawn, and said: the kit's
            // own audit fails a room like this (rule 15), so it is design's to
            // decide, not something to paper over by guessing a split.
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

/* THE HOST IS DESIGN'S EXPORT OR NOTHING. The figure's paint order — which
 * parts take `headT` and `glassesT`, what the face is painted over — lives in
 * design's review pages and nowhere in the engine, and design's own finding is
 * that a close crop drawn from the raw paths looks like a broken asset when it
 * is not. So this never paints him from the model. It checks what the kit
 * exports against what the model says he is, and refuses until it holds:
 *
 *   the export's viewBox contains the pose's ink box    (not a head cut at the neck)
 *   the eyes, the glasses and a mouth are in the file   (a face, not a blank)
 *   a strip exports every frame it declares, and they are not all the still
 *
 * Returns the problems. There is no host install path yet, because the
 * export format of a fixed host does not exist yet: a drop that passes these
 * checks still stops here, with a message saying the reader is the next job. */
function checkHost(ctx) {
  const { M, hours, args, emitted } = ctx;
  if (!args.against) return ["host: needs --against (the kit's export) to be checked at all"];
  const indexPath = path.join(args.against, "index.json");
  if (!fs.existsSync(indexPath)) return ["host: the kit's export has no index.json"];
  const index = JSON.parse(fs.readFileSync(indexPath, "utf8")).index || [];
  const STRIPS = ["", "-talk", "-idle", "-blink"];
  const fails = { missing: [], outside: [], faceless: [], frames: [], still: [] };
  for (const pose of M.poseKeys) {
    const G = M.geometry(pose);
    const faceParts = [G.eyes[0], G.glasses[0]];
    const mouths = [G.mouthClosed, G.mouthMid, G.mouthWide];
    for (const hour of hours) {
      let stillBytes = null;
      for (const suffix of STRIPS) {
        const key = "host/" + pose + suffix;
        const at = key + " at " + hour;
        const entries = index.filter((e) => e.key === key && e.hour === hour && !e.error);
        const files = Array.from(new Set(entries.reduce((a, e) => a.concat(
          Array.isArray(e.files) ? e.files : [], Array.isArray(e.frames) ? e.frames.filter((f) => typeof f === "string") : [],
          e.file ? [e.file] : []), [])));
        if (!files.length) { fails.missing.push(at); continue; }
        const bodies = files.map((f) => {
          const p = path.join(args.against, f);
          return fs.existsSync(p) ? fs.readFileSync(p, "utf8") : "";
        });
        const em = emitted[key + "@" + hour];
        const ink = em && em.inkBox;
        bodies.forEach((svg, i) => {
          const vb = /viewBox="([^"]+)"/.exec(svg);
          const v = vb ? vb[1].trim().split(/[\s,]+/).map(Number) : null;
          if (ink && (!v || ink[0] < v[0] || ink[1] < v[1] || ink[2] > v[0] + v[2] || ink[3] > v[1] + v[3])) {
            fails.outside.push(at + " (" + files[i] + ": viewBox " + (v ? v.join(" ") : "none") + ", ink box " + ink.join(",") + ")");
          }
          if (!faceParts.every((d) => svg.indexOf(d) >= 0) || !mouths.some((d) => svg.indexOf(d) >= 0)) {
            fails.faceless.push(at + " (" + files[i] + ")");
          }
        });
        const declared = Math.max(1, ...entries.map((e) => (typeof e.frames === "number" ? e.frames : 1)));
        if (files.length < declared) fails.frames.push(at + " (declares " + declared + " frames, exports " + files.length + " file)");
        if (suffix === "") stillBytes = bodies[0];
        else if (stillBytes !== null && bodies.every((b) => b === stillBytes)) fails.still.push(at);
      }
    }
  }
  const out = [];
  const say = (list, what) => {
    if (list.length) out.push("host: " + list.length + " " + what + ", e.g. " + list.slice(0, 3).join("; "));
  };
  say(fails.missing, "strip(s) the kit's export does not list");
  say(fails.outside, "file(s) whose viewBox cuts off the figure's own ink box");
  say(fails.faceless, "file(s) with no eyes, glasses or mouth drawn");
  say(fails.frames, "strip(s) that export fewer files than the frames they declare");
  say(fails.still, "talk/idle/blink strip(s) byte-identical to the pose's still");
  if (!out.length) {
    out.push("host: the kit's export passes every host check, and this driver has no reader for its frame files yet. " +
             "Write it in scripts/kit_engine.js before installing: the figure is the one asset the show cannot be made without.");
  }
  return out;
}

async function main() {
  const args = parseArgs(process.argv);
  args.out = path.resolve(args.out);
  const kitDir = path.resolve(args.kit);
  const engineDir = path.join(kitDir, "engine");
  accountForEngine(engineDir);

  const g = loadEngine(engineDir);
  const M = require(path.join(engineDir, "kit-model.js"));
  const PORT = require(path.join(engineDir, "port.js"));
  if (typeof PORT.palFor !== "function") die("port.js exports no palFor; the palette map has to come off the kit");
  const tokens = JSON.parse(fs.readFileSync(path.join(kitDir, "design-tokens.json"), "utf8"));
  const hours = Object.keys(tokens.hours || {}).filter((h) => !h.startsWith("_"));
  if (hours[0] !== BASE_HOUR) die("design-tokens.json lists hours " + JSON.stringify(hours) + "; the keys assume " + BASE_HOUR + " comes first");

  const emitted = {};
  for (const p of JSON.parse(fs.readFileSync(args.emit, "utf8")).plates || []) emitted[p.id] = p;

  const ctx = { g, M, tokens, hours, palFor: PORT.palFor, raster: loadRasteriser(), args, problems: [], emitted };

  /* THE CATALOGUE is the kit's own: build.js's LIB without the drawn kit's
   * host and rooms (rebuilt flat in kit-model.js), then the round-one plates
   * catalogued beside their authors. The same list export.js walks. */
  const content = g.BUILD.LIB.filter((x) => x.dir !== "host" && x.dir !== "room")
    .concat(g.PLATES_R1.LIB || []);
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
  if (want("host")) ctx.problems.push(...checkHost(ctx));

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
    exportScale: (g.AUDIT && g.AUDIT.EXPORT_SCALE) || 2,
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
