#!/usr/bin/env node
/* Dennis v2 — audit.test.js · the NEGATIVE CONTROL
 *
 *   node engine/emit.js && node engine/audit.test.js
 *
 * A green audit proves nothing on its own. A rule that always passes and a
 * rule that cannot fail look identical from the outside, and this kit has
 * already shipped a rule that reported itself as not-yet-due while silently
 * never executing (§8.0). So: break each rule's condition on purpose, one at a
 * time, against a throwaway copy of the emitted files, and require the rule to
 * notice.
 *
 * A rule that does not catch its own violation is a rule that is not there.
 *
 * Exits 1 if any injected violation goes uncaught.
 */

'use strict';
const fs = require('fs');
const path = require('path');
const ROOT = path.resolve(__dirname, '..');
const read = p => JSON.parse(fs.readFileSync(path.join(ROOT, p), 'utf8'));

const first = o => o[Object.keys(o)[0]];

const CASES = [
  [1, 'gradient in one asset', d => { first(d.manifest.assets).gradients = 1; }],
  [2, 'partial opacity', d => { first(d.manifest.assets).partialOpacity = 2; }],
  [3, 'fill outside the palette', d => { d.plates.plates[0].fills.push('#FF00FF'); }],
  [4, 'a second contour width', d => { d.plates.plates[0].strokes.push({ colour: '#000000', width: 0.07 }); }],
  [5, 'caption under the floor', d => { d.tokens.hours.night.ink.quiet = '#6E7C90'; }],
  [6, 'twin geometry drift', d => { const t = d.plates.plates.find(p => p.role === 'room');
      const o = d.plates.plates.find(p => p.twinId === t.twinId && p !== t); if (o) o.geometryHash = 'deadbeef'; }],
  [7, 'host role with no anchor', d => { const k = Object.keys(d.manifest.assets).find(x => d.manifest.assets[x].hostAnchor);
      d.manifest.assets[k].role = 'host'; delete d.manifest.assets[k].hostAnchor; }],
  [8, 'manifest C disagreeing with the table', d => { d.manifest.C = 0.61; }],
  [9, 'manifest record missing fps', d => { delete first(d.manifest.assets).fps; }],
  [10, 'a live <text> node', d => { first(d.manifest.assets).textNodes = 1; }],
  [11, 'room under the six-shape floor', d => { d.plates.plates.find(p => p.role === 'room').shapeCount = 4; }],
  [12, 'figure material merged into the wall', d => { d.tokens.hours.night.materials.shirt.lit = d.tokens.hours.night.materials.wall.lit; }],
  [13, 'ink outside the published box', d => { d.plates.plates.find(p => p.role === 'host').inkBox = [-40, 0, 900, 900]; }],
  [14, 'anchor clipped by the portrait window', d => { d.plates.plates.find(p => p.portraitWindow).portraitWindow = [0, 0, 10, 10]; }],
  [15, 'anchored room with no split', d => { delete d.plates.plates.find(p => p.role === 'room' && p.hostAnchor).occlusionSplit; }],
  [16, 'anchor width not derived', d => { d.plates.plates.find(p => p.role === 'room' && p.hostAnchor).hostAnchor = [10, 10, 110, 116]; }],
  [27, 'a shelf across his head', d => { d.plates.plates.find(p => p.role === 'room' && p.clearance).clearance.head.headCover = 67; }],
  [28, 'title card off the portrait window', d => { d.plates.plates.filter(p => p.title).forEach(p => { p.title.ground = [0, 9, 92, 44]; }); }],
  [17, 'band direction flipped', d => { d.tokens.hours.night.ink.band = '#0A0D14'; }],
  [18, 'slab caption broken', d => { d.tokens.hours.dusk.ink.band = '#6B5F50'; d.tokens.hours.dusk.ink.ground = '#5F5570'; }],
];

/* Load audit.js with its inputs swapped for the mutated copies. */
function runAudit(tokens, manifest, plates) {
  let src = fs.readFileSync(path.join(__dirname, 'audit.js'), 'utf8');
  src = src.replace(/^[\s\S]*?const ROOT = [^\n]*\n/, '')
    .replace(/const T = \(\) => read\('design-tokens\.json'\);/, 'const T = () => __t;')
    .replace(/const manifest = \(\)[^\n]*\n/, 'const manifest = () => __m;\n')
    .replace(/const plates = \(\)[^\n]*\n/, 'const plates = () => __p;\n')
    .replace(/\/\* ── report[\s\S]*$/, '')
    .replace(/\nconst argv = process\.argv[\s\S]*$/, '\n');
  /* eslint-disable no-new-func */
  /* rebuild-21: fs, path, ROOT and require are passed in. They used to be
   * stripped with the header, so every rule that reads a file of its own
   * (22, 24, 25, 26 — the export index and the roles file) threw, the baseline
   * came up not-green, and this test had been refusing to run since rule 22. */
  return new Function('__t', '__m', '__p', 'fs', 'path', 'ROOT', 'require', 'process', src + `
    return RULES.map(r => { try { const o = r.fn(); return { n: r.n, state: o.ok ? 'pass' : 'FAIL' }; }
      catch (e) { return { n: r.n, state: e instanceof NeedsData ? 'needs-data' : 'DID NOT RUN' }; } });`
  )(tokens, manifest, plates, fs, path, ROOT, require, process);
}

const clean = () => ({
  tokens: read('design-tokens.json'),
  manifest: read('emit/manifest.json'),
  plates: read('emit/plates.json'),
});

/* The audit must be green BEFORE anything is broken, or the test proves nothing. */
const baseline = (() => { const d = clean(); return runAudit(d.tokens, d.manifest, d.plates); })();
const notGreen = baseline.filter(r => r.state !== 'pass');
if (notGreen.length) {
  process.stdout.write(`baseline is not green — ${notGreen.map(r => r.n + ':' + r.state).join(', ')}\n`);
  process.stdout.write('the negative control cannot mean anything until it is\n');
  process.exit(1);
}

let caught = 0;
CASES.forEach(([n, label, mutate]) => {
  const d = clean();
  mutate(d);
  const r = runAudit(d.tokens, d.manifest, d.plates).find(x => x.n === n);
  const ok = r && r.state === 'FAIL';
  if (ok) caught++;
  process.stdout.write(`${ok ? '  caught ' : '  MISSED '} ${String(n).padStart(2)}  ${label}${ok ? '' : `  (reported ${r ? r.state : 'nothing'})`}\n`);
});

process.stdout.write(`\n${caught} of ${CASES.length} injected violations caught\n`);
if (caught !== CASES.length) process.exit(1);
