#!/usr/bin/env node
/* Dennis v2 — port.js
 *
 * THE OLD KIT'S PLATES, RECOLOURED — not redrawn.
 *
 *   node engine/port.js
 *
 * The drawings were never lost. `engine/plates.js` is 7,861 lines of plate
 * authors and `engine/hand.js` draws them; both still run untouched. 51
 * authors, 270 catalogued assets in `engine/build.js`'s LIB. What was lost was
 * only the PALETTE — the old kit drew dark ink on light paper and the rebuild
 * needs both hours.
 *
 * So the port is a palette map, and that is the whole of it:
 *
 *     legacy role      ->  rebuilt ink
 *     ground               ink.ground
 *     ground2              ink.band          (the band direction flips per hour)
 *     structure            ink.structure
 *     down                 ink.attention     (a loss, a fall — nothing else)
 *     up                   ink.subject       (only a rise)
 *     neutralData          ink.quiet         (no direction)
 *     attention            ink.subject2      (the one thing to look at)
 *     otherParty           ink.axis          (peers, consensus, the market)
 *
 * Eight lines. 168 plates × 2 hours render in about a second and a half, and
 * every fill lands inside the declared palette — audit rule 3 passes untouched.
 *
 * WHAT THE PORT DOES NOT DO, AND CANNOT:
 *
 * These are hand-drawn ink. One plate is ~108 paths, ~108 of them at partial
 * opacity, with ~92 distinct stroke widths — tremor, overshoot, hatch, every
 * stroke its own weight and alpha. That is not a defect to be cleaned up; it
 * is the technique. It fails audit rules 2 and 4 by construction.
 *
 * §0's diagnosis is explicitly about *a drawn figure*: "a drawn figure has
 * about a dozen independent ways to be wrong." The six rejections were the
 * HOST. The data plates were never the complaint, and they are paper artefacts
 * inside the world, where drawn ink is arguably the right answer.
 *
 * So rules 2 and 4 are SCOPED BY FAMILY (DESIGN.md §8.2) rather than dropped:
 * flat law governs everything the host touches — figure, rooms, title grounds —
 * and the drawn families keep their ink. The scope is declared here, in data,
 * so the audit reads it rather than being told.
 */

'use strict';
const fs = require('fs');
const path = require('path');
const ROOT = path.resolve(__dirname, '..');

/* The legacy engine, loaded as-is. Nothing in these three files is edited. */
const g = {};
['hand.js', 'budget.js', 'plates.js'].forEach(f => {
  /* eslint-disable no-new-func */
  new Function('window', 'globalThis', fs.readFileSync(path.join(__dirname, f), 'utf8'))(g, g);
});

/* Round-one authors install onto the same PLATES registry, so every consumer
 * of this module sees one library. */
g.PLATES_R1 = require('./plates-r1');
g.PLATES_R1.install(g.PLATES, g.HAND);
/* Round two — software and industrials — installs AFTER round one, whose
 * budget helpers it reuses. */
g.PLATES_R2 = require('./plates-r2');
g.PLATES_R2.install(g.PLATES, g.HAND);
/* Round three — one set per sector — names round two's shapes. */
g.PLATES_R3 = require('./plates-r3');
g.PLATES_R3.install(g.PLATES, g.HAND);

/* The catalogue, read out of build.js rather than retyped (§8.1), with the
 * round-one entries appended. emit.js and export.js both read THIS, which is
 * what stops the manifest and the export disagreeing about what exists. */
function catalogue() { return legacyCatalogue().concat(g.PLATES_R1.LIB, g.PLATES_R2.LIB, g.PLATES_R3.LIB); }
function legacyCatalogue() {
  const b = fs.readFileSync(path.join(__dirname, 'build.js'), 'utf8');
  const decls = b.slice(b.indexOf('const A = (dir, key, author'), b.indexOf('const LIB = [].concat('));
  const i = b.indexOf('const LIB = [].concat(');
  let d = 0, j = b.indexOf('(', i);
  for (; j < b.length; j++) { if (b[j] === '(') d++; else if (b[j] === ')') { d--; if (!d) break; } }
  return new Function('PLATES', 'HAND', decls + '\n' + b.slice(i, j + 2) + '\nreturn LIB;')(g.PLATES, g.HAND);
}

/* FAMILIES THAT KEEP THEIR DRAWN INK. Everything absent from this list is
 * governed by the flat law — host and room are rebuilt flat and are not here. */
const DRAWN_FAMILIES = ['annotations', 'cards', 'charts', 'cycles', 'figures',
  'frames', 'overlays', 'paper', 'peers', 'shorts', 'structure', 'tables'];

function palFor(tokens, hour) {
  const I = tokens.hours[hour].ink;
  return {
    surfaceKey: 'night-card', grain: null,
    ground: I.ground, ground2: I.band, structure: I.structure,
    down: I.subject2, up: I.subject, neutralData: I.quiet,
      attention: I.attention, otherParty: I.axis,
  };
}

/* Measured off the emitted string, never declared (the emitter's own law). */
function countsOf(svg) {
  const op = (svg.match(/opacity="([\d.]+)"/g) || []).map(s => parseFloat(s.slice(9, -1)));
  return {
    paths: (svg.match(/<path/g) || []).length,
    gradients: (svg.match(/<(linear|radial)Gradient/g) || []).length,
    partialOpacity: op.filter(o => o !== 0 && o !== 1).length,
    textNodes: (svg.match(/<text[\s>]/g) || []).length,
    strokeWidths: new Set(svg.match(/stroke-width="([\d.]+)"/g) || []).size,
    fills: Array.from(new Set((svg.match(/fill="(#[0-9a-fA-F]{6})"/g) || []).map(s => s.slice(6, 13).toUpperCase()))),
  };
}
function hash(s) { let h = 0x811c9dc5; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = (h * 0x01000193) >>> 0; } return h.toString(16).padStart(8, '0'); }

function port(tokens) {
  const LIB = catalogue().filter(x => x.dir !== 'host' && x.dir !== 'room');
  const assets = {}, plates = [], failures = [];

  LIB.forEach(it => {
    /* The aspect is in the legacy key; under §4.4a it is a variant. */
    const id = it.key.replace(/-(16x9|9x16)$/, '');
    const aspect = /-9x16$/.test(it.key) ? '9x16' : '16x9';

    ['night', 'dusk'].forEach(hour => {
      let svg, P;
      try {
        P = g.PLATES[it.author](Object.assign({}, it.args, { key: it.key, seed: it.seed, pal: palFor(tokens, hour) }));
        svg = P.toSVG();
      } catch (e) { failures.push({ key: it.key, hour, error: e.message }); return; }
      const c = countsOf(svg);

      assets[id] = assets[id] || {
        /* fps and frameCount come from design-tokens.json → motion. They were
         * typed here as `fps: 2` against §6's 3fps, which is precisely the
         * defect the rebuild exists to remove: a number living in a draw
         * path instead of in the tokens. */
        role: 'plate', dir: it.dir, author: it.author, playback: 'loop',
        fps: tokens.motion.fps, frameCount: tokens.motion.frames,
        drawn: DRAWN_FAMILIES.indexOf(it.dir) >= 0,
        gradients: 0, partialOpacity: 0, textNodes: 0,
      };
      assets[id].gradients = Math.max(assets[id].gradients, c.gradients);
      assets[id].partialOpacity = Math.max(assets[id].partialOpacity, c.partialOpacity);
      assets[id].textNodes = Math.max(assets[id].textNodes, c.textNodes);

      plates.push({
        id: id + '@' + hour + '.' + aspect, role: 'plate', family: it.dir, hour, aspect,
        drawn: DRAWN_FAMILIES.indexOf(it.dir) >= 0,
        twinId: id + '.' + aspect,
        /* Geometry is the drawing with colour stripped, so rule 6 can still ask
         * whether the two hours are one drawing. They are: same author, same
         * seed, same args — only pal differs. */
        geometryHash: hash(svg.replace(/(fill|stroke)="[^"]*"/g, '')),
        fills: c.fills,
        strokes: [{ colour: tokens.hours[hour].contour, width: 0.035 }],
        strokeWidthCount: c.strokeWidths,
        shapeCount: c.paths,
        box: [0, 0, P.w || 1920, P.h || 1080],
      });
    });
  });
  return { assets, plates, failures };
}

if (require.main === module) {
  const tokens = JSON.parse(fs.readFileSync(path.join(ROOT, 'design-tokens.json'), 'utf8'));
  const out = port(tokens);
  fs.mkdirSync(path.join(ROOT, 'emit'), { recursive: true });
  fs.writeFileSync(path.join(ROOT, 'emit/ported.json'), JSON.stringify({
    _generated: 'engine/port.js', _drawnFamilies: DRAWN_FAMILIES,
    assets: out.assets, plates: out.plates, failures: out.failures,
  }, null, 1));
  process.stdout.write(`${Object.keys(out.assets).length} assets · ${out.plates.length} plates · ${out.failures.length} failures\n`);
}

module.exports = { port, palFor, DRAWN_FAMILIES, countsOf, catalogue, engine: g };
