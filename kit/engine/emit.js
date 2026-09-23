#!/usr/bin/env node
/* Dennis v2 — emit.js
 *
 * THE ONE PIPELINE. Everything the kit ships is built here, from the engine,
 * in one pass:
 *
 *   emit/manifest.json        one record per ASSET  (what it is, how it plays)
 *   emit/plates.json          one record per PLATE  (asset x hour x aspect) + the facts the audit reads
 *   emit/slots.json           every plate's slot table: position, type role, maxChars
 *   <family>/manifest.json    the per-family manifests the ingest globs for, frames and slots included
 *
 *   node engine/emit.js                 # write all of the above
 *   node engine/emit.js --check         # write nothing; exit 1 if anything on disk differs
 *   node engine/emit.js && node engine/audit.js --check
 *
 * WHY THIS WAS REWRITTEN (rebuild-17). The previous emit.js walked only
 * kit-model.js and kit-plates.js. Every ported plate and every round-one plate
 * reached emit/manifest.json through ad-hoc scripts run from the review pages,
 * never through this file \u2014 so a clean `node engine/emit.js` rewrote the
 * manifest with 73 assets instead of 193, and the audit then failed. The same
 * scripts stubbed M.anchorOf to null, which is why the six new rooms shipped
 * with no host anchor. A pipeline that only works when somebody runs the right
 * scripts by hand is not a pipeline. This file now builds everything, and
 * export.js builds its files by calling build() here \u2014 so the manifest's
 * frame hashes and the exported files cannot disagree.
 *
 * It emits FACTS ABOUT WHAT IT DREW, measured off the serialised SVG \u2014 never
 * numbers copied from the spec. If the emitter reported the spec's figures,
 * --check would be a tautology and every rule would pass for the wrong reason.
 */

'use strict';
const fs = require('fs');
const path = require('path');
const M = require('./kit-model');
const F = require('./figure');
const PORT = require('./port');
const CONTENT = require('./content');

const ROOT = path.resolve(__dirname, '..');
const g = PORT.engine;
const PW = 98, PH = 174, PY = 4;
const read = p => JSON.parse(fs.readFileSync(path.join(ROOT, p), 'utf8'));
const pad = n => String(n).padStart(2, '0');

function hash(s) { let h = 0x811c9dc5; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = (h * 0x01000193) >>> 0; } return h.toString(16).padStart(8, '0'); }
function countsOf(svg) {
  const op = (svg.match(/opacity="([\d.]+)"/g) || []).map(s => parseFloat(s.slice(9, -1)));
  return {
    gradients: (svg.match(/<(linear|radial)Gradient/g) || []).length,
    partialOpacity: op.filter(o => o !== 0 && o !== 1).length,
    textNodes: (svg.match(/<text[\s>]/g) || []).length,
  };
}
const fillsOf = svg => Array.from(new Set((svg.match(/fill="(#[0-9a-fA-F]{6})"/g) || []).map(s => s.slice(6, 13).toUpperCase())));
function boxOfPaths(ds) { const b = [Infinity, Infinity, -Infinity, -Infinity]; ds.forEach(d => F.pathBox(d, b)); return b.map(v => Math.round(v)); }

/* Region and furniture roles carry no words of their own. Same list content.js skips. */
const NOT_TEXT = ['band', 'marker', 'plot-area', 'bars', 'bridge', 'path', 'spark', 'point-column',
  'media', 'highlight-band', 'wraps', 'control', 'mark-area'];
const isText = s => !(s.overlay || s.container || s.region || NOT_TEXT.indexOf(s.role) >= 0);

function roomSvg(r, H) {
  return '<svg xmlns="http://www.w3.org/2000/svg" width="320" height="180" viewBox="0 0 320 180">'
    + r.shapes.map(s => '<path d="' + s.d + '" fill="' + (s.ink ? H.ink[s.role] : H.m[s.role][s.tone === 'shade' ? 1 : 0]) + '"/>').join('')
    + '</svg>';
}

/* build({ decorate, onFile }) \u2014 decorate(entry, manifest, hour) returns SVG to
 * burn into a plate (export --sample only); onFile(indexEntry, svg) receives
 * every file as it is produced. */
function build(opts) {
  opts = opts || {};
  const tokens = read('design-tokens.json');
  let overrides = {};
  try { overrides = read('content-overrides.json'); } catch (e) { /* optional */ }
  CONTENT.setOverrides(overrides);
  /* budget.js owns type capacity; content.js must not keep a second model. */
  if (CONTENT.useMetrics) CONTENT.useMetrics(g.BUDGET);

  const assets = {}, plates = [], index = [], slots = {}, fam = {};
  const addFam = (dir, key, rec) => { (fam[dir] = fam[dir] || {})[key] = rec; };
  const emitFile = (entry, svg) => {
    entry.hash = hash(svg); entry.bytes = svg.length; entry.inkBox = F.inkBoxOfSvg(svg);
    index.push(entry);
    if (opts.onFile) opts.onFile(entry, svg);
  };
  const stroke0 = (tokens.contourWeight && tokens.contourWeight.value) || 0.035;

  /* ── host ─────────────────────────────────────────────────────────────── */

  M.poseKeys.forEach(key => {
    const g0 = M.geometry(key);
    const geomPaths = g0.body.map(p => p.d).concat(g0.head.map(p => p.d), (g0.marks || []).map(p => p.d));
    const facePaths = [].concat(g0.glasses || [], g0.eyes || [], [g0.mouthWide].filter(Boolean));
    const allPaths = geomPaths.concat(facePaths, g0.prop ? [g0.prop.d] : []);
    const ink = boxOfPaths(allPaths);
    const gHash = hash(geomPaths.join('|'));

    F.STRIPS.forEach(s => {
      const id = 'host/' + key + s.suffix;
      const frames = F.framesOf(s.suffix, tokens);
      assets[id] = { role: 'pose', dir: 'host', playback: s.playback, fps: s.fps, frameCount: frames.length,
        gradients: 0, partialOpacity: 0, textNodes: 0 };
      const byHour = {};
      M.HOURS.forEach(H => {
        const svgs = frames.map(fr => F.svg(M, key, H, fr, tokens));
        const c = countsOf(svgs.join(''));
        assets[id].gradients = Math.max(assets[id].gradients, c.gradients);
        assets[id].partialOpacity = Math.max(assets[id].partialOpacity, c.partialOpacity);
        assets[id].textNodes = Math.max(assets[id].textNodes, c.textNodes);
        plates.push({
          id: id + '@' + H.name, role: 'host', hour: H.name, aspect: 'any', twinId: id, geometryHash: gHash,
          fills: fillsOf(svgs.join('')), strokes: [{ colour: H.contour, width: stroke0 }],
          shapeCount: allPaths.length, box: F.BOX, inkBox: ink, frameHashes: svgs.map(hash),
        });
        const stem = key + s.suffix + '-' + H.name;
        const base = { key: id, hour: H.name, aspect: 'any', strip: s.suffix || 'still', canvas: [F.BOX[2], F.BOX[3]],
          viewBox: F.BOX, exportScale: 2, delivered: [F.BOX[2] * 2, F.BOX[3] * 2], slots: 0, flat: true };
        /* The base file IS frame one, byte for byte. */
        emitFile(Object.assign({}, base, { frame: null, file: 'host/' + stem + '.svg' }), svgs[0]);
        if (frames.length > 1) svgs.forEach((sv, i) =>
          emitFile(Object.assign({}, base, { frame: '_f' + pad(i + 1), file: 'host/' + stem + '_f' + pad(i + 1) + '.svg', args: frames[i] }), sv));
        byHour[H.name] = { base: stem + '.png', baseIsFrame: true,
          frames: frames.length > 1 ? svgs.map((sv, i) => ({ file: stem + '_f' + pad(i + 1) + '.png', tag: '_f' + pad(i + 1), args: frames[i], hash: hash(sv) })) : [] };
      });
      addFam('host', id, { key: id, dir: 'host', aspect: 'any', canvas: [F.BOX[2], F.BOX[3]], viewBox: F.BOX,
        delivered: [F.BOX[2] * 2, F.BOX[3] * 2], exportScale: 2, playback: s.playback, fps: s.fps,
        frameCount: frames.length, files: byHour.night, filesByHour: byHour });
    });
  });

  /* ── rooms ────────────────────────────────────────────────────────────── */

  M.rooms().forEach(r => {
    const anchor = M.anchorOf(r);
    const deskAt = r.shapes.findIndex(s => s.role === 'desk');
    /* THE SPLIT. The desk is where the figure is occluded. An anchored room with
     * no desk \u2014 board-side, where he stands at the near edge \u2014 draws him over
     * everything, so its split is the shape count. It used to publish none, and
     * rule 15 was right to fail it. */
    const split = !anchor ? undefined : (deskAt >= 0 ? deskAt : r.shapes.length);
    const cx = anchor ? anchor[0] + anchor[2] / 2 : 160;
    const win = [Math.max(0, Math.min(320 - PW, Math.round(cx - PW / 2))), PY, PW, PH];
    const gHash = hash(r.shapes.map(s => s.d).join('|'));
    const id = 'room/' + r.id;
    const c0 = countsOf(roomSvg(r, M.HOURS[0]));
    assets[id] = { role: anchor ? 'host' : 'plate', dir: 'room', playback: 'still', fps: 1, frameCount: 1,
      gradients: c0.gradients, partialOpacity: c0.partialOpacity, textNodes: c0.textNodes };
    if (anchor) assets[id].hostAnchor = anchor;
    if (r.role) assets[id].roomRole = r.role;
    if (r.duskSafe !== undefined) assets[id].duskSafe = r.duskSafe;
    const byHour = {};
    M.HOURS.forEach(H => {
      const svg = roomSvg(r, H);
      ['16x9', '9x16'].forEach(aspect => plates.push({
        id: id + '@' + H.name + '.' + aspect, role: 'room', hour: H.name, aspect, twinId: id + '.' + aspect,
        geometryHash: gHash, fills: fillsOf(svg), strokes: [{ colour: H.contour, width: stroke0 }],
        shapeCount: r.shapes.length, box: aspect === '16x9' ? [0, 0, 320, 180] : win,
        inkBox: boxOfPaths(r.shapes.map(s => s.d)),
        hostAnchor: anchor || undefined, portraitWindow: anchor ? win : undefined, occlusionSplit: split,
      }));
      const stem = r.id + '-' + H.name;
      emitFile({ key: id, hour: H.name, aspect: 'any', frame: null, file: 'room/' + stem + '.svg', canvas: [320, 180],
        viewBox: [0, 0, 320, 180], exportScale: 2, delivered: [3840, 2160], slots: 0, flat: true }, svg);
      byHour[H.name] = { base: stem + '.png', baseIsFrame: true, frames: [] };
    });
    addFam('room', id, { key: id, dir: 'room', aspect: 'any', canvas: [320, 180], delivered: [3840, 2160],
      exportScale: 2, playback: 'still', fps: 1, frameCount: 1, hostAnchor: anchor || null,
      portraitWindow: anchor ? win : null, occlusionSplit: split === undefined ? null : split,
      roomRole: r.role || null, duskSafe: r.duskSafe === undefined ? null : r.duskSafe,
      files: byHour.night, filesByHour: byHour });
  });

  /* ── plates: the ported legacy library plus round one ────────────────── */

  const LIB = PORT.catalogue().filter(x => x.dir !== 'host' && x.dir !== 'room');
  const R1 = new Set(g.PLATES_R1.LIB.map(x => x.key));
  const R2 = new Set(g.PLATES_R2.LIB.map(x => x.key));
  const R3 = new Set(g.PLATES_R3.LIB.map(x => x.key));
  const offs = (tokens.motion && tokens.motion.dataRuleOffsets) || [0];
  const fps = (tokens.motion && tokens.motion.fps) || 3;
  let widest = 0, loose = 0;
  const overflowing = [], overBudget = [];

  LIB.forEach(it => {
    const id = it.key.replace(/-(16x9|9x16)$/, '');
    const aspect = /-9x16$/.test(it.key) ? '9x16' : '16x9';
    const byHour = {};
    let slotRec = null, slotCount = 0;
    ['night', 'dusk'].forEach(hour => {
      const H = M.HOURS.find(x => x.name === hour);
      const P = g.PLATES[it.author](Object.assign({}, it.args, { key: it.key, seed: it.seed, pal: PORT.palFor(tokens, hour) }));
      const m = P.manifest();
      /* Frames: the frame's rule lines take tokens.motion.dataRuleOffsets;
       * pinned ink (axes, baselines, references) and every value stay still. */
      const cache = {};
      const svgs = offs.map(dy => cache[dy] || (cache[dy] = P.toSVG({ ruleOffset: dy })));
      const extra = opts.decorate ? opts.decorate(it, m, hour) : '';
      const files = extra ? svgs.map(s => s.replace('</svg>', extra + '</svg>')) : svgs;
      const c = countsOf(svgs[0]);
      slotCount = Object.keys(m.slots || {}).length;
      assets[id] = assets[id] || { role: 'plate', dir: it.dir, author: it.author, playback: 'loop', fps,
        frameCount: offs.length, drawn: PORT.DRAWN_FAMILIES.indexOf(it.dir) >= 0,
        gradients: 0, partialOpacity: 0, textNodes: 0, slots: slotCount };
      if (R1.has(it.key)) assets[id].round = 'r1';
      if (R2.has(it.key)) assets[id].round = 'r2';
      if (R3.has(it.key)) assets[id].round = 'r3';
      assets[id].gradients = Math.max(assets[id].gradients, c.gradients);
      assets[id].partialOpacity = Math.max(assets[id].partialOpacity, c.partialOpacity);
      assets[id].textNodes = Math.max(assets[id].textNodes, c.textNodes);

      const roles = m.typeRoles || {};
      const ct = CONTENT.contentFor(it.key, m);
      const textSlots = m.cutout === true ? 0 : Object.values(m.slots || {})
        .filter(s => isText(s) && CONTENT.budgetOf(s, roles) >= 2).length;
      if (hour === 'night') {
        slotRec = { canvas: m.canvas, aspect, typeRoles: roles, slots: m.slots };
        Object.values(m.slots || {}).forEach(s => {
          if (!isText(s) || !s.maxChars) return;
          const R = roles[s.role] || {}; const size = R.size || Math.max(14, Math.round(s.h * 0.6));
          const pc = g.BUDGET.perChar(s.role, Object.assign({}, R, { size }));
          const lines = s.wraps || s.maxLines || Math.max(1, Math.floor(s.h / (size * 1.25)));
          if (s.maxChars > Math.max(2, Math.floor((s.w / (size * pc)) * lines))) loose++;
        });
        Object.keys(ct.text).forEach(k => {
          const s = m.slots[k]; if (!s) return;
          const t = ct.text[k], R = roles[s.role] || {};
          const size = CONTENT.fittedSize(s, roles, t);
          const pc = g.BUDGET.perChar(s.role, Object.assign({}, R, { size }));
          const lines = s.wraps || s.maxLines || Math.max(1, Math.floor(s.h / (size * 1.25)));
          const ratio = (size * pc * t.length / lines) / s.w;
          if (ratio > widest) widest = ratio;
          if (ratio > 1.02) overflowing.push({ key: id, slot: k, ratio: +ratio.toFixed(2) });
        });
        CONTENT.overBudget(it.key, m).forEach(o => overBudget.push(Object.assign({ key: it.key }, o)));
      }
      plates.push({
        id: id + '@' + hour + '.' + aspect, role: 'plate', family: it.dir, hour, aspect,
        drawn: PORT.DRAWN_FAMILIES.indexOf(it.dir) >= 0, twinId: id + '.' + aspect,
        geometryHash: hash(svgs[0].replace(/(fill|stroke)="[^"]*"/g, '')),
        fills: fillsOf(svgs[0]), strokes: [{ colour: H.contour, width: stroke0 }],
        shapeCount: (svgs[0].match(/<path/g) || []).length, box: [0, 0, m.canvas[0], m.canvas[1]],
        filledSlots: Object.keys(ct.text).length, textSlots,
      });
      const stem = it.key.split('/').pop() + '-' + hour;
      const base = { key: it.key, hour, aspect, canvas: m.canvas, viewBox: [0, 0, m.canvas[0], m.canvas[1]],
        exportScale: 2, delivered: [m.canvas[0] * 2, m.canvas[1] * 2], slots: slotCount };
      emitFile(Object.assign({}, base, { frame: null, file: it.dir + '/' + stem + '.svg' }), files[0]);
      files.forEach((sv, i) => emitFile(Object.assign({}, base,
        { frame: '_f' + pad(i + 1), file: it.dir + '/' + stem + '_f' + pad(i + 1) + '.svg', args: { ruleOffset: offs[i] } }), sv));
      byHour[hour] = { base: stem + '.png', baseIsFrame: true,
        frames: svgs.map((sv, i) => ({ file: stem + '_f' + pad(i + 1) + '.png', tag: '_f' + pad(i + 1), args: { ruleOffset: offs[i] }, hash: hash(sv) })) };
    });
    slots[it.key] = slotRec;
    addFam(it.dir, it.key, Object.assign({ key: it.key, dir: it.dir, aspect, canvas: slotRec.canvas,
      delivered: [slotRec.canvas[0] * 2, slotRec.canvas[1] * 2], exportScale: 2, playback: 'loop', fps,
      frameCount: offs.length, files: byHour.night, filesByHour: byHour, slotCount,
      typeRoles: slotRec.typeRoles, slots: slotRec.slots }));
  });

  /* Overrides that name no such slot, and the count, for rule 21. */
  const stray = []; let overrideCount = 0;
  const ov = overrides.overrides || {};
  Object.keys(ov).forEach(k => {
    overrideCount += Object.keys(ov[k].slots || {}).length;
    const s0 = slots[k] || slots[k + '-16x9'] || slots[k + '-9x16'];
    if (!s0) { stray.push({ key: k, slot: '(no such asset)' }); return; }
    Object.keys(ov[k].slots || {}).forEach(n => { if (!s0.slots[n]) stray.push({ key: k, slot: n }); });
  });
  overflowing.sort((a, b) => b.ratio - a.ratio);

  const P = M.P;
  const C = ((60 + P.shoulderFromCrown * 100) + (P.armUpperLength + P.armForeLength) * 100 - F.BOX[1]) / F.BOX[3];
  const J = o => JSON.stringify(o, null, 1);
  const outputs = {};
  outputs['emit/manifest.json'] = J({ _generated: 'engine/emit.js', C, assets });
  outputs['emit/plates.json'] = J({ _generated: 'engine/emit.js', figureInkAspect: M.figInk(), plates,
    widestRatio: +widest.toFixed(2), overflowing, loosePublishedBudgets: loose, overBudget,
    strayOverrides: stray, overrideCount,
    budgetMetric: 'engine/budget.js perChar \u2014 the shipped fonts\u2019 hmtx advances' });
  outputs['emit/slots.json'] = J({
    _spec: 'Every plate\u2019s slot table, keyed by plate name with aspect: canvas, type roles and slots (x, y, w, h, role, maxChars / maxCharsPerLine x maxLines). maxChars is a HARD limit, derived by engine/budget.js from the box. Written by engine/emit.js; do not hand-edit.',
    _generated: 'engine/emit.js', count: Object.keys(slots).length, plates: slots });
  Object.keys(fam).sort().forEach(dir => {
    outputs[dir + '/manifest.json'] = J({
      family: dir, pack: 'rebuild-17',
      generated: 'engine/emit.js. Deterministic \u2014 regenerate from the engine you are holding: node engine/emit.js (node engine/emit.js --check diffs without writing).',
      exportScale: 2,
      hashAlgo: 'fnv1a-32 over the emitted SVG string (UTF-16 code units), lowercase hex, zero-padded to 8',
      frameNaming: '<name>-<hour>_f01.._fNN before the extension. The BASE file carries no frame tag and is byte-identical to _f01.',
      files: '`files` is the night hour, in the legacy shape; `filesByHour` carries both hours. Every hour is one shape list read through one colour table \u2014 an episode picks one and never mixes them.',
      motion: 'Authored, from design-tokens.json -> motion. Plates: the frame\u2019s rule lines take dataRuleOffsets; pinned ink and every value stay still. Host: -talk cycles the three mouths on the head offsets, -idle loops the head offsets, -blink closes the eyes, the base strip is a still.',
      bakedText: false,
      assetCount: Object.keys(fam[dir]).length,
      plates: fam[dir],
    });
  });
  return { outputs, index, counts: { assets: Object.keys(assets).length, plates: plates.length, files: index.length, slotTables: Object.keys(slots).length, families: Object.keys(fam).length } };
}

function check() {
  const b = build();
  const diffs = Object.keys(b.outputs).filter(rel => {
    const f = path.join(ROOT, rel);
    return !fs.existsSync(f) || fs.readFileSync(f, 'utf8') !== b.outputs[rel];
  });
  return { ok: !diffs.length, diffs, files: Object.keys(b.outputs).length, counts: b.counts };
}

function run() {
  const b = build();
  Object.keys(b.outputs).forEach(rel => {
    fs.mkdirSync(path.dirname(path.join(ROOT, rel)), { recursive: true });
    fs.writeFileSync(path.join(ROOT, rel), b.outputs[rel]);
  });
  return b;
}

if (require.main === module) {
  if (process.argv.includes('--check')) {
    const r = check();
    process.stdout.write(r.ok ? `emit --check clean: ${r.files} files match the engine\n`
      : `emit --check: ${r.diffs.length} of ${r.files} files differ from the engine:\n  ${r.diffs.join('\n  ')}\n`);
    process.exit(r.ok ? 0 : 1);
  } else {
    const b = run();
    process.stdout.write(`${b.counts.assets} assets · ${b.counts.plates} plate records · ${b.counts.slotTables} slot tables · ${b.counts.families} family manifests\n`);
  }
}

module.exports = { build, check, run, hash };
