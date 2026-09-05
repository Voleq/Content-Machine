/* Dennis v2 — scripts/fontmetrics.js
   Regenerates the advance tables baked into engine/budget.js. Run it whenever a
   font file in fonts/ is replaced; nothing else in the library reads a font
   binary, and nothing else may hard-code an em advance.

   It reads hmtx directly rather than asking a canvas for a string width,
   because a canvas gives you one number for one string in one browser, and a
   budget has to be reproducible on the build machine. The wght instances are
   the exception: Archivo Narrow varies its advances through HVAR, which is not
   worth parsing for four numbers, so the 500/600/700 factors are measured once
   with the variable font loaded and recorded as ratios against 400.

   Usage (node):  node scripts/fontmetrics.js  > /tmp/metrics.json
*/
const fs = require("fs");

function parse(buf) {
  const dv = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  const u16 = (o) => dv.getUint16(o), i16 = (o) => dv.getInt16(o), u32 = (o) => dv.getUint32(o);
  const tables = {};
  for (let i = 0; i < u16(4); i++) {
    const o = 12 + i * 16;
    const tag = String.fromCharCode(dv.getUint8(o), dv.getUint8(o + 1), dv.getUint8(o + 2), dv.getUint8(o + 3));
    tables[tag] = { off: u32(o + 8), len: u32(o + 12) };
  }
  const upem = u16(tables.head.off + 18);
  const numH = u16(tables.hhea.off + 34);
  const cm = tables.cmap.off;
  let sub = null;
  for (let i = 0; i < u16(cm + 2); i++) {
    const o = cm + 4 + i * 8, pid = u16(o), eid = u16(o + 2);
    if ((pid === 3 && (eid === 1 || eid === 0)) || pid === 0) sub = cm + u32(o + 4);
  }
  const map = {};
  if (u16(sub) === 4) {
    const segX2 = u16(sub + 6), seg = segX2 / 2;
    const endO = sub + 14, startO = endO + segX2 + 2, deltaO = startO + segX2, rangeO = deltaO + segX2;
    for (let s = 0; s < seg; s++) {
      const end = u16(endO + s * 2), start = u16(startO + s * 2), delta = i16(deltaO + s * 2), ro = u16(rangeO + s * 2);
      for (let c = start; c <= end && c !== 0xffff; c++) {
        let gl;
        if (ro === 0) gl = (c + delta) & 0xffff;
        else { gl = u16(rangeO + s * 2 + ro + (c - start) * 2); if (gl) gl = (gl + delta) & 0xffff; }
        if (gl) map[c] = gl;
      }
    }
  }
  const hm = tables.hmtx.off;
  const adv = (gl) => u16(hm + Math.min(gl, numH - 1) * 4) / upem;
  const out = { upem, variable: !!tables.fvar, hasHVAR: !!tables.HVAR, adv: {} };
  const codes = [];
  for (let c = 32; c <= 126; c++) codes.push(c);
  [8211, 8212, 8217, 8220, 8221, 215].forEach((c) => codes.push(c));
  codes.forEach((c) => { if (map[c]) out.adv[c] = adv(map[c]); });
  return out;
}

// The classes engine/budget.js budgets against, and the weights that build them:
// English letter frequency, 12% of letters capitalised in mixed-case prose,
// space at SPACE_SHARE of all characters. A class mean, not an alphabet mean —
// the old 0.47em constant was the uppercase number spent on lowercase copy.
//
// SPACE_SHARE IS APPLIED, NOT TYPED. The first cut of this file wrote a literal
// weight of 80 into tables whose letter frequencies sum to 100, which makes the
// space 40% of all characters — not the 16% the comment beside it claimed. The
// space is the narrowest glyph in the face, so over-weighting it dragged both
// prose means down and every budget derived from them came out too generous:
// mixed-case by 13%, uppercase by 18%, in the loose direction this whole pack
// exists to close. A documented share and a hard-coded weight are two numbers
// that can disagree, so now there is one: the weight is SOLVED from the share
// against whatever the rest of the table sums to.
// Share of all characters that are word spaces. 0.16 is the documented figure;
// running English is nearer 0.17, which moves the class means less than 0.5% —
// well inside the 4% allowance in budget.js — so the documented number is kept
// rather than quietly swapped for a better one.
const SPACE_SHARE = 0.16;

const LOWER = { a: 8.17, b: 1.49, c: 2.78, d: 4.25, e: 12.7, f: 2.23, g: 2.02, h: 6.09, i: 6.97, j: 0.15, k: 0.77, l: 4.03, m: 2.41, n: 6.75, o: 7.51, p: 1.93, q: 0.1, r: 5.99, s: 6.33, t: 9.06, u: 2.76, v: 0.98, w: 2.36, x: 0.15, y: 1.97, z: 0.07 };
function classes(adv) {
  const mean = (w) => {
    let n = 0, d = 0;
    for (const ch in w) { const a = adv[ch.charCodeAt(0)]; if (a == null) continue; n += a * w[ch]; d += w[ch]; }
    return n / d;
  };
  const mixed = {}, upper = {}, figure = {};
  for (const k in LOWER) {
    mixed[k] = LOWER[k] * 0.88;
    mixed[k.toUpperCase()] = (mixed[k.toUpperCase()] || 0) + LOWER[k] * 0.12;
    upper[k.toUpperCase()] = LOWER[k];
  }
  Object.assign(mixed, { ".": 1.2, ",": 1.2, "-": 0.6, "/": 0.4, "(": 0.2, ")": 0.2 });
  Object.assign(upper, { ".": 1.2, ",": 0.8, "-": 0.8, "/": 1.0 });
  "0123456789".split("").forEach((d) => { mixed[d] = 1.5; upper[d] = 1.2; figure[d] = 10; });
  Object.assign(figure, { ".": 4, ",": 3, x: 2, $: 1, "%": 1, "(": 0.5, ")": 0.5, "-": 0.5, " ": 1 });
  // w / (rest + w) = SPACE_SHARE  ->  w = rest * share / (1 - share).
  // figure keeps its own space weight of 1: a figure box holds "141.6x", not
  // prose, and spacing it like a sentence is what would be wrong there.
  const solveSpace = (tbl) => {
    const rest = Object.keys(tbl).reduce((s, k) => s + tbl[k], 0);
    return rest * SPACE_SHARE / (1 - SPACE_SHARE);
  };
  mixed[" "] = solveSpace(mixed);
  upper[" "] = solveSpace(upper);
  return {
    mixed: mean(mixed), upper: mean(upper), figure: mean(figure),
    spaceShare: SPACE_SHARE, spaceWeight: { mixed: mixed[" "], upper: upper[" "] },
  };
}

const an = parse(fs.readFileSync("fonts/ArchivoNarrow[wght].ttf"));
const cp = parse(fs.readFileSync("fonts/CourierPrime-Regular.ttf"));
const cpb = parse(fs.readFileSync("fonts/CourierPrime-Bold.ttf"));
const monoSet = Object.keys(cp.adv).map((k) => cp.adv[k]).filter((v, i, a) => a.indexOf(v) === i);
if (monoSet.length !== 1) throw new Error("Courier Prime is not monospaced any more — budget.js MONO is no longer exact");
if (cpb.adv[65] !== cp.adv[65]) throw new Error("Courier Prime bold advance differs from regular — budget.js needs a weight table for it");
console.log(JSON.stringify({ mono: monoSet[0], archivo: { upem: an.upem, variable: an.variable, hasHVAR: an.hasHVAR, classes: classes(an.adv) }, weightFactorsMeasuredOnce: { 400: 1, 500: 1.0123, 600: 1.0256, 700: 1.0386 } }, null, 1));
