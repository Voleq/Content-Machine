#!/usr/bin/env node
/* Dennis v2 — THE BATCH FALLBACK.
 *
 * WHY THIS EXISTS, AND WHY IT IS NOT THE PRIMARY ROUTE
 *
 * scripts/ingest_kit.py OOM-killed at 286 frames of 924. The real fix is the
 * shape of the call, and it is in the engine: BUILD.stream() yields one frame at
 * a time and drops it, so peak memory is one frame regardless of library size.
 * An ingest that uses stream() does not need this script.
 *
 * This is the fallback for the case stream() cannot reach: the process itself is
 * the thing that will not survive. If the ingest host is memory-capped below one
 * family, or the runtime leaks across iterations, or a single plate is the thing
 * that dies, then no in-process iterator helps — the only fix left is a smaller
 * process. So: ONE PROCESS PER FAMILY, fourteen of them, each exiting and
 * returning its memory to the OS before the next starts.
 *
 * A family is the unit because it is the largest chunk that actually built in one
 * pass when §0's manifests were generated in drop twelve, and because manifests
 * are already per-family — so a batch that fails names a file you can regenerate
 * alone, rather than invalidating the run.
 *
 * WHAT IT COSTS, stated rather than buried: fourteen process starts, fourteen
 * engine parses, and no shared work between families. It is slower than one
 * streaming pass and it is meant to be. It also cannot catch a cross-family
 * defect, because nothing in it ever sees two families at once — which is the
 * same blindness the family-chunked manifest generation has, and worth knowing
 * before this becomes the default rather than the fallback.
 *
 * USAGE
 *   node scripts/build_batch.mjs --out ../assets/plates            # all fourteen
 *   node scripts/build_batch.mjs --out ../assets/plates --family room
 *   node scripts/build_batch.mjs --out ../assets/plates --svg-only # no rasteriser
 *   node scripts/build_batch.mjs --list                            # families + counts
 *
 * It writes SVG by default and shells out to `resvg` for PNG when --png is given.
 * resvg is the pipeline's own rasteriser, so the PNG path here produces the same
 * bytes the render path reads; the SVG path is for checking without one installed.
 *
 * THE CONTRACT THIS SCRIPT MUST NOT BREAK
 *   - exportScale 2. delivered = canvas x 2. Never authored here, read off the plate.
 *   - _f01.._fNN, zero-padded, contiguous. The base carries no tag.
 *   - The base is byte-identical to _f01 on an ANIMATED plate, because both are
 *     emitted from frame one's own args — verified, not assumed: 1,522,843 bytes
 *     identical on room/desk-front-16x9. On a STATIC plate (frameCount 1) there
 *     is no frame one and the base is the only file, so one untagged file is
 *     written and NO _f01. Getting that backwards is what §0's manifests were
 *     corrected for in drop twelve.
 *   - 1,191 FILES for 924 frames: 921 tagged frames, 267 animated bases, and the
 *     3 static plates' single untagged file. An ingest that writes 924 has
 *     skipped every base its own manifest declares.
 *   - No <text> nodes. Asserted per frame below, not assumed.
 */

import { readFileSync, mkdirSync, writeFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ENGINE = resolve(HERE, "../engine");
const ORDER = ["budget.js", "hand.js", "plates.js", "audit.js", "build.js"];

const argv = process.argv.slice(2);
const flag = (n) => argv.indexOf(n) >= 0;
const val = (n, d) => { const i = argv.indexOf(n); return i >= 0 ? argv[i + 1] : d; };

const OUT = val("--out", null);
const ONE = val("--family", null);
const PNG = flag("--png");
const LIST = flag("--list");
const QUIET = flag("--quiet");

// The engine is browser-shaped: five plain scripts that hang off a global. Load
// them in order into one sandboxed global rather than importing — they are not
// modules and must not be made into modules, because the proof pages load these
// same five files with <script src> and any change here would fork them.
function loadEngine() {
  const g = {};
  for (const f of ORDER) new Function("window", "globalThis", readFileSync(join(ENGINE, f), "utf8")).call(g, g, g);
  if (!g.BUILD) throw new Error("engine loaded but BUILD is absent — check engine/ is intact");
  if (typeof g.BUILD.stream !== "function") throw new Error("this engine has no BUILD.stream(); it predates drop twelve");
  return g.BUILD;
}

const B = loadEngine();
const FAMILIES = ONE ? [ONE] : B.families();

if (LIST) {
  let t = 0;
  for (const fam of B.families()) {
    const n = B.stream(() => {}, { family: fam }).frames;
    t += n;
    console.log(String(n).padStart(4) + " frames  " + fam);
  }
  console.log("----\n" + String(t).padStart(4) + " frames, " + B.families().length + " families");
  process.exit(0);
}
if (!OUT) { console.error("need --out <dir> (or --list)"); process.exit(2); }
if (ONE && B.families().indexOf(ONE) < 0) { console.error("no such family: " + ONE + "\nhave: " + B.families().join(", ")); process.exit(2); }

// A family in THIS process. The parent re-spawns per family so that each one's
// memory is returned to the OS on exit; this branch is the child's whole job.
if (ONE) {
  let frames = 0, bytes = 0, texty = [];
  const t0 = Date.now();
  B.stream(function (f) {
    const abs = join(resolve(OUT), f.path);
    mkdirSync(dirname(abs), { recursive: true });
    // The structural guarantee, asserted per frame rather than trusted: P.toSVG()
    // can only emit rect, path, g, defs/clipPath and the root svg. A <text> node
    // would mean a font dependency in the render path, which is the one thing the
    // kit promises never to hand the pipeline.
    if (/<text[\s>]/.test(f.svg)) texty.push(f.path);
    if (PNG) {
      const svgPath = abs.replace(/\.png$/, ".svg");
      writeFileSync(svgPath, f.svg);
      execFileSync("resvg", [svgPath, abs, "--width", String(f.delivered[0]), "--height", String(f.delivered[1])]);
    } else {
      writeFileSync(abs.replace(/\.png$/, ".svg"), f.svg);
    }
    frames++; bytes += f.svg.length;
  }, { family: ONE });
  const line = ONE.padEnd(12) + String(frames).padStart(4) + " frames  " +
    String(Math.round(bytes / 1024)).padStart(6) + "kb svg  " +
    String(((Date.now() - t0) / 1000).toFixed(1)).padStart(6) + "s  rss " +
    Math.round(process.memoryUsage().rss / 1048576) + "mb";
  if (!QUIET) console.log(line);
  if (texty.length) { console.error("TEXT NODES in " + texty.length + " frame(s): " + texty.join(", ")); process.exit(1); }
  process.exit(0);
}

// The parent: one child per family, sequential, each exiting before the next.
// Sequential deliberately — the point is that only one family is resident at a
// time, and running them in parallel would put all fourteen back in memory at
// once, which is the defect this script exists to avoid.
let failed = [];
const t0 = Date.now();
for (const fam of FAMILIES) {
  try {
    const out = execFileSync(process.execPath, [fileURLToPath(import.meta.url), "--out", OUT, "--family", fam].concat(PNG ? ["--png"] : []), { encoding: "utf8" });
    process.stdout.write(out);
  } catch (e) {
    failed.push(fam);
    console.error("FAILED " + fam + " — " + (e.stderr || e.message || "").toString().trim().split("\n").slice(0, 3).join(" / "));
    console.error("  regenerate this family alone: node scripts/build_batch.mjs --out " + OUT + " --family " + fam);
  }
}
console.log("----");
console.log(FAMILIES.length - failed.length + "/" + FAMILIES.length + " families in " + ((Date.now() - t0) / 1000).toFixed(1) + "s" +
  (failed.length ? "  FAILED: " + failed.join(", ") : ""));
process.exit(failed.length ? 1 : 0);
