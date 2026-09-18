#!/usr/bin/env node
/* Dennis v2 — emit kit/<family>/manifest.json for all fourteen families.
 *
 * WHERE THEY GO, AND WHY IT IS NOT NEGOTIABLE
 *
 * kit/<family>/manifest.json. Beside the family's plates, which is where
 * scripts/ingest_kit.py's glob looks. delta-14 shipped its copies under
 * kit/manifests/<family>/manifest.json, which that glob does not match: the
 * ingest walks the pack, finds no manifest beside any family, reads the pack as
 * zero assets, and reconciles against nothing. A manifest in the wrong directory
 * is not a manifest, it is a file.
 *
 * USAGE
 *   node scripts/emit_manifests.mjs                 # all fourteen, in place
 *   node scripts/emit_manifests.mjs --family room   # one
 *   node scripts/emit_manifests.mjs --out /tmp/m    # somewhere else, same layout
 *   node scripts/emit_manifests.mjs --check         # emit nothing; diff against what is on disk
 *
 * --check is the one to run before shipping: it emits into memory and compares
 * against the manifests already on disk, field by field, and prints what moved.
 * A clean --check means the manifests in the tree came from the engine in the
 * tree, which is the invariant the whole pack depends on and the one nothing was
 * enforcing.
 *
 * WHAT THIS DOES NOT DO: it does not render a single PNG and it does not need
 * one. A manifest is geometry and metadata, both of which come out of the same
 * call that draws the plate — see scripts/build_batch.mjs for the file emit.
 */
import { readFileSync, writeFileSync, mkdirSync, existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const KIT = resolve(HERE, "..");
const ENGINE = join(KIT, "engine");
const ORDER = ["budget.js", "hand.js", "plates.js", "audit.js", "build.js"];

const argv = process.argv.slice(2);
const flag = (n) => argv.indexOf(n) >= 0;
const val = (n, d) => { const i = argv.indexOf(n); return i >= 0 ? argv[i + 1] : d; };
const ONE = val("--family", null);
const OUT = val("--out", KIT);
const CHECK = flag("--check");

// The engine is browser-shaped: plain scripts hanging off a global, loaded in
// order. Same loader as scripts/build_batch.mjs, deliberately — the proof pages
// load these same files with <script src> and a module fork would split them.
const g = {};
const SOURCES = ORDER.map((f) => join(ENGINE, f)).concat([join(HERE, "manifest_core.js")]);
for (const p of SOURCES) {
  new Function("window", "globalThis", readFileSync(p, "utf8")).call(g, g, g);
}
if (!g.BUILD) throw new Error("engine loaded but BUILD is absent — check engine/ is intact");
if (!g.MANIFEST_EMIT) throw new Error("scripts/manifest_core.js did not load");

const B = g.BUILD;
const FAMILIES = ONE ? [ONE] : B.families();
if (ONE && B.families().indexOf(ONE) < 0) {
  console.error("no such family: " + ONE + "\nhave: " + B.families().join(", "));
  process.exit(2);
}

let plates = 0, slots = 0, moved = [];
for (const fam of FAMILIES) {
  const m = g.MANIFEST_EMIT.emitFamily(B, fam);
  const json = JSON.stringify(m, null, 1) + "\n";
  const dest = join(resolve(OUT), fam, "manifest.json");
  plates += m.assetCount;
  slots += m.slotTotal;

  if (CHECK) {
    const same = existsSync(dest) && readFileSync(dest, "utf8") === json;
    if (!same) moved.push(fam);
    console.log((same ? "ok       " : "DIFFERS  ") + fam.padEnd(12) +
      String(m.assetCount).padStart(4) + " plates  " + String(m.slotTotal).padStart(5) + " slots");
    continue;
  }

  mkdirSync(dirname(dest), { recursive: true });
  writeFileSync(dest, json);
  console.log(fam.padEnd(12) + String(m.assetCount).padStart(4) + " plates  " +
    String(m.slotTotal).padStart(5) + " slots  " + String(m.frameTotal).padStart(4) + " frames  " +
    String(Math.round(json.length / 1024)).padStart(5) + "kb  -> " + fam + "/manifest.json");
}

console.log("----");
console.log(FAMILIES.length + " families, " + plates + " plates, " + slots + " slots" +
  (CHECK ? (moved.length ? "  STALE: " + moved.join(", ") : "  all manifests match the engine") : ""));
process.exit(CHECK && moved.length ? 1 : 0);
