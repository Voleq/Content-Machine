/* Run the design-kit engine and write the artwork out.
 *
 * BUILD-TIME ONLY. Nothing in the render path may shell out to node: a bug in
 * plates.js has to break a build, never a published video. `scripts/ingest_kit.py`
 * is the only caller, and what it leaves on disk is plain PNGs plus one registry
 * that the renderer reads with no JS anywhere near it.
 *
 *   node scripts/kit_engine.js --kit kit --out assets/plates --outfit shirt
 *
 * The kit is deterministic — every asset is an author plus a seed, declared in
 * engine/build.js — so this reproduces the delivered artwork rather than
 * unpacking a copy of it. That is the whole reason the delivery is 1.4 MB of JS
 * instead of 860 MB of PNGs, and it is why an outfit is an argument here rather
 * than four more families nobody re-exports.
 *
 * What it writes, per asset:
 *   <out>/<family>/<name>.png            the base file
 *   <out>/<family>/<name>_f01.png        frame one — the SAME BYTES as the base
 *   <out>/<family>/<name>_f02.png        frame two, where the asset boils
 *   <out>/<family>/<name>.svg            only with --svg; the engine IS the source
 *
 * and one registry describing all of it. The SVGs are off by default because
 * they are 200 MB of exactly what `engine/` already says: a vector source is
 * only worth keeping when it is the thing you cannot regenerate, and here it is
 * two minutes of CPU away. Pass --svg when you want to look at one.
 *
 * The base file is written by copying frame one's buffer, not by drawing a third
 * time: a base that is its own render pops on the first frame of the loop, which
 * is what six host poses used to do.
 */
"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");

// budget.js FIRST: `Plate.manifest()` in hand.js calls `g.BUDGET.derive(...)`
// behind an `if (g.BUDGET && ...)` guard, so a BUDGET that has not loaded by
// then is not an error — the derivation is simply skipped and the engine
// emits slots with no budgets while the delivered manifests carry them.
// `_reconcile` then fails on 103 of 143 assets for what looks like a
// geometry disagreement. Order is load-bearing here, not cosmetic.
const ENGINE_FILES = ["budget.js", "hand.js", "plates.js", "series.js", "audit.js", "build.js"];

/* Engine files that ship in the delivery and are DELIBERATELY not loaded here.
 *
 * `render.js` emits manifests and `sheet.js` draws contact sheets; both are the
 * delivery's own authoring tools and neither is on the ingest path. They are
 * named rather than merely absent from ENGINE_FILES so that the check below can
 * tell "we decided not to load this" apart from "nobody noticed this arrived". */
const ENGINE_NOT_LOADED = ["render.js", "sheet.js"];

function die(msg) {
  process.stderr.write("kit_engine: " + msg + "\n");
  process.exit(1);
}

function parseArgs(argv) {
  const out = { kit: "kit", out: "assets/plates", outfit: "shirt", only: null, svg: false };
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--kit") out.kit = argv[++i];
    else if (a === "--out") out.out = argv[++i];
    else if (a === "--outfit") out.outfit = argv[++i];
    else if (a === "--only") out.only = argv[++i];
    else if (a === "--svg") out.svg = true;
    else die("unknown argument " + a);
  }
  return out;
}

/* The engine is four IIFEs that hang themselves off `globalThis`. It has no
 * module system and no dependencies, so a bare vm context is the whole loader —
 * no npm install, no bundler, no build of the build. */
function loadEngine(kitDir) {
  const engineDir = path.join(kitDir, "engine");
  const ctx = { console: console };
  ctx.globalThis = ctx;
  vm.createContext(ctx);
  /* A NEW ENGINE FILE MUST BE A DECISION, NOT A NO-OP.
   *
   * `budget.js` arrived in delta-10a carrying the whole type-budget derivation,
   * and `Plate.manifest()` calls it behind `if (g.BUDGET && ...)`. Not naming it
   * here did not fail: BUDGET was simply undefined, the derivation was skipped,
   * and the engine emitted slots with no budgets while the delivered manifests
   * carried them — surfacing 103 files later as "slots disagrees with the
   * shipped manifest", which reads like a geometry problem and is not one.
   *
   * The missing feature was not the bug. Nothing saying anything was. So an
   * engine file that is in neither list stops the build here, where the message
   * can name the actual choice. */
  const known = new Set([...ENGINE_FILES, ...ENGINE_NOT_LOADED]);
  const stray = fs.readdirSync(engineDir)
    .filter((f) => f.endsWith(".js") && !known.has(f))
    .sort();
  if (stray.length) {
    die(
      "engine file(s) not accounted for: " + stray.join(", ") + "\n" +
      "  Every .js in " + engineDir + " must be named in kit_engine.js — in\n" +
      "  ENGINE_FILES to load it (order matters: a file whose globals another\n" +
      "  file reads at load time goes first), or in ENGINE_NOT_LOADED to say it\n" +
      "  is authoring tooling the ingest does not run.\n" +
      "  An unnamed file loads NOTHING and fails no check, so whatever it was\n" +
      "  meant to add is simply absent from every manifest this build emits."
    );
  }

  for (const f of ENGINE_FILES) {
    const p = path.join(engineDir, f);
    if (!fs.existsSync(p)) die("missing engine file " + p);
    vm.runInContext(fs.readFileSync(p, "utf8"), ctx, { filename: f });
  }
  /* BUDGET is loaded but its hook is guarded, so "loaded" and "ran" are not the
   * same claim. This is the one global whose absence is silent downstream. */
  if (!ctx.BUDGET) die("budget.js loaded but BUDGET is not defined — the type-budget derivation would be skipped and every manifest would emit slots with no maxChars");
  if (!ctx.BUILD || !ctx.PLATES || !ctx.HAND) die("engine loaded but BUILD/PLATES/HAND are not defined");
  return ctx;
}

/* The rasteriser. resvg is a pure vector renderer and that is exactly what this
 * library needs: the plates carry no <text> node at all (every word on screen is
 * a slot the compositor fills), so there is no font resolution to get wrong and
 * no browser to keep alive. Fonts are switched off deliberately — if a plate ever
 * did emit text, a silent fallback face would be worse than the blank it draws. */
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
  return function raster(svg, scale) {
    const r = new Resvg(svg, {
      fitTo: { mode: "zoom", value: scale },
      font: { loadSystemFonts: false },
      background: "rgba(0,0,0,0)",
    });
    return r.render().asPng();
  };
}

function mkdirp(d) { fs.mkdirSync(d, { recursive: true }); }

function main() {
  const args = parseArgs(process.argv);
  const kitDir = path.resolve(args.kit);
  const outDir = path.resolve(args.out);
  const ctx = loadEngine(kitDir);
  const raster = loadRasteriser();
  const BUILD = ctx.BUILD;
  const PLATES = ctx.PLATES;

  if (BUILD.OUTFITS.indexOf(args.outfit) < 0) {
    die("unknown outfit " + JSON.stringify(args.outfit) +
        " — the engine ships " + BUILD.OUTFITS.join(", "));
  }

  /* The palette comes OFF THE ENGINE, never out of a table here or in Python.
   * The kit's own README lists attention as #D79E22 and the engine draws
   * #E0A016; the engine is what put ink on the plate, so the engine wins. A
   * hex copied into code is a second source of truth that silently goes stale. */
  const pal = PLATES.pal("night-card");
  const palette = {
    surface: "night-card",
    roles: {
      "ground": pal.ground,
      "second-ground": pal.ground2,
      "structure": pal.structure,
      "down": pal.down,
      "up": pal.up,
      "neutral-data": pal.neutralData,
      "attention": pal.attention,
      "other-party": pal.otherParty,
    },
  };

  const assets = {};
  const items = args.only
    ? BUILD.LIB.filter((x) => x.key.indexOf(args.only) >= 0)
    : BUILD.LIB;
  if (!items.length) die("--only " + args.only + " matched no asset");

  let wrote = 0;
  for (const item of items) {
    const famDir = path.join(outDir, item.dir);
    mkdirp(famDir);
    const name = item.key.split("/").pop();
    const frames = BUILD.framesOf(item);
    const play = BUILD.playbackOf(item);

    let manifest = null;
    const frameRecords = [];
    let baseBuf = null;
    let baseSvg = null;

    for (const fr of frames) {
      /* An outfit is an argument, not a file. drawWith threads it through to
       * hostFigure; for every other author it is ignored, so one call shape
       * covers the whole library. */
      const plate = BUILD.drawWith(item, args.outfit, fr.args);
      const svg = plate.toSVG();
      if (manifest === null) manifest = plate.manifest();
      const scale = manifest.exportScale;
      const png = raster(svg, scale);

      const stem = name + (fr.tag || "");
      fs.writeFileSync(path.join(famDir, stem + ".png"), png);
      if (args.svg) fs.writeFileSync(path.join(famDir, stem + ".svg"), svg);
      frameRecords.push(Object.assign({}, fr.args, {
        tag: fr.tag || null,
        png: stem + ".png",
        svg: args.svg ? stem + ".svg" : null,
      }));
      if (baseBuf === null) { baseBuf = png; baseSvg = svg; }
      wrote++;
    }

    /* THE BASE IS FRAME ONE'S BYTES. Not a third render of the same arguments —
     * the same buffer, written twice. Re-drawing would be reproducible and still
     * wrong: the point is that a player showing the base and then entering the
     * loop sees no jump, and only identical bytes guarantee that. */
    const baseTag = frames[0].tag || null;
    if (baseTag) {
      fs.writeFileSync(path.join(famDir, name + ".png"), baseBuf);
      if (args.svg) fs.writeFileSync(path.join(famDir, name + ".svg"), baseSvg);
    }

    assets[item.key] = Object.assign({}, manifest, {
      family: item.dir,
      author: item.author,
      seed: item.seed,
      surface: BUILD.surfaceOf(item.key),
      outfit: item.dir === "host" ? args.outfit : undefined,
      playback: play.playback,
      fps: play.fps,
      frameCount: play.frameCount,
      frames: frameRecords,
      files: {
        png: name + ".png",
        svg: args.svg ? name + ".svg" : null,
        baseIsFrame: baseTag,
      },
      dir: item.dir + "/",
    });
  }

  const registry = {
    kit: "dennis-v2",
    generated: new Date().toISOString().slice(0, 10),
    engine: {
      source: path.relative(process.cwd(), path.join(kitDir, "engine")),
      note: "build-time only — the render path reads PNGs and this registry, never JS",
    },
    outfit: args.outfit,
    exportScale: (ctx.AUDIT && ctx.AUDIT.EXPORT_SCALE) || 2,
    palette: palette,
    assets: assets,
  };

  process.stdout.write(JSON.stringify(registry));
  process.stderr.write("kit_engine: " + Object.keys(assets).length +
                       " assets, " + wrote + " frames, outfit=" + args.outfit + "\n");
}

main();
