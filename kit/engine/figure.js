/* Dennis v2 — figure.js
 *
 * THE HOST, RENDERED. One paint order, one box, every frame of every strip.
 *
 *   const F = require('./figure');
 *   F.svg(M, 'to-camera', M.NIGHT, F.frameOf('-talk', 1, tokens), tokens);
 *
 * Why this file exists (rebuild-17). export.js drew every pose into the ROOM'S
 * 320x180 box while the figure lives in its own 400x720 box, so eleven poses
 * exported as a head cut off at the neck and sitting-at-desk exported empty.
 * It also painted only what M.paint() returns \u2014 body, head, brow/nose marks
 * \u2014 and dropped everything M.geometry() returns for the FACE: eyes, glasses,
 * three mouths, and the headT/glassesT transforms that put them on the skull.
 * And no frame ever differed from the still.
 *
 * The close-crop review had the correct paint order all along. It lives here
 * now, and emit.js and export.js both call it \u2014 so the manifest's frame
 * hashes and the exported files are the same drawing by construction.
 */

'use strict';

/* The figure's own box, [x, y, w, h]. The crown sits at y=60 and one head unit
 * is 100 canvas units (guides: crown 60, shoulder 192 = 60 + 1.32 x 100). */
const BOX = [0, 40, 400, 720];

/* A prop drawn BEHIND the body rather than over it. The chair is behind the
 * sitter; a page or a mug is in front of the hands. */
const PROP_BEHIND = ['sitting-at-desk'];

/* ── the strips ─────────────────────────────────────────────────────────────
 *
 * What each strip's frames ARE. Motion is AUTHORED, never noise: the head
 * offsets come from design-tokens.json -> motion.hostOffsets, the mouths and
 * the blink are the geometry the model already carries.
 *
 * The base strip is a true still (1 frame). It used to be declared a 3-frame
 * loop while exporting one image, and `-idle` would have looped the same
 * offsets \u2014 two strips doing one job. `-idle` owns the breathing now. */
const STRIPS = [
  { suffix: '', playback: 'still', fps: 1 },
  { suffix: '-talk', playback: 'loop', fps: 8 },
  { suffix: '-idle', playback: 'loop', fps: 4 },
  { suffix: '-blink', playback: 'overlay', fps: 4 },
];

function framesOf(suffix, tokens) {
  const off = (tokens.motion && tokens.motion.hostOffsets) || [{ headRotate: 0, shoulderY: 0 }];
  const o = i => off[i % off.length];
  if (suffix === '-talk') {
    /* Three mouths, closed \u2192 mid \u2192 wide, each on its own head offset so the
     * talk reads as speech and not as a mouth sliding on a still face. */
    /* rebuild-31: six visemes, not three. The order is a phrase, not a sweep:
     * closed, mid, wide, O, EE, F/V, so the loop never reads as a mouth
     * opening and closing on a metronome. */
    return ['mouthClosed', 'mouthMid', 'mouthWide', 'mouthO', 'mouthEE', 'mouthFV'].map((mouth, i) =>
      ({ mouth, headRotate: o(i).headRotate, shoulderY: o(i).shoulderY, eyes: 'open' }));
  }
  if (suffix === '-idle') {
    return off.map(x => ({ mouth: 'mouthClosed', headRotate: x.headRotate, shoulderY: x.shoulderY, eyes: 'open' }));
  }
  if (suffix === '-blink') {
    return [{ mouth: 'mouthClosed', headRotate: 0, shoulderY: 0, eyes: 'open' },
      { mouth: 'mouthClosed', headRotate: 0, shoulderY: 0, eyes: 'closed' }];
  }
  return [{ mouth: 'mouthClosed', headRotate: 0, shoulderY: 0, eyes: 'open' }];
}

/* ── path geometry ─────────────────────────────────────────────────────── */

/* Absolute bbox of an SVG path string, M/L/H/V/C/S/Q/T/A/Z, either case.
 * Control points are included, which makes the box conservative. */
function pathBox(d, acc) {
  /* rebuild-40: one tokenising pass into typed arrays, no per-token regex or
   * closures. Same semantics as before (checked against the old version on
   * every exported file); it was 45% of emit's time. */
  const b = acc || [Infinity, Infinity, -Infinity, -Infinity];
  const re = /[MmLlHhVvCcSsQqTtAaZz]|-?(?:\d+\.?\d*|\.\d+)(?:e[-+]?\d+)?/g, str = String(d);
  const L = [], V = []; let m;
  while ((m = re.exec(str))) { const t = m[0], c = t.charCodeAt(0); if ((c >= 65 && c <= 90) || (c >= 97 && c <= 122)) { L.push(t); V.push(0); } else { L.push(null); V.push(parseFloat(t)); } }
  const N = L.length;
  let i = 0, cmd = 'M', x = 0, y = 0, sx = 0, sy = 0, b0 = b[0], b1 = b[1], b2 = b[2], b3 = b[3];
  while (i < N) {
    if (L[i] !== null) cmd = L[i++];
    if (cmd === 'Z' || cmd === 'z') { x = sx; y = sy; continue; }
    if (i >= N || L[i] !== null) continue;
    const rel = cmd.charCodeAt(0) >= 97, C = rel ? cmd.toUpperCase() : cmd, ox = rel ? x : 0, oy = rel ? y : 0;
    let px, py;
    if (C === 'M' || C === 'L' || C === 'T') { px = V[i++] + ox; py = V[i++] + oy; x = px; y = py; if (C === 'M') { sx = x; sy = y; cmd = rel ? 'l' : 'L'; } }
    else if (C === 'H') { x = V[i++] + ox; px = x; py = y; }
    else if (C === 'V') { y = V[i++] + oy; px = x; py = y; }
    else if (C === 'C' || C === 'S' || C === 'Q') {
      const k = C === 'C' ? 2 : 1;
      for (let j = 0; j < k; j++) { const qx = V[i++] + ox, qy = V[i++] + oy; if (qx < b0) b0 = qx; if (qy < b1) b1 = qy; if (qx > b2) b2 = qx; if (qy > b3) b3 = qy; }
      px = V[i++] + ox; py = V[i++] + oy; x = px; y = py;
    }
    else if (C === 'A') { i += 5; px = V[i++] + ox; py = V[i++] + oy; x = px; y = py; }
    else { i++; continue; }
    if (px < b0) b0 = px; if (py < b1) b1 = py; if (px > b2) b2 = px; if (py > b3) b3 = py;
  }
  b[0] = b0; b[1] = b1; b[2] = b2; b[3] = b3;
  return b;
}

function pathBoxLegacy(d, acc) {
  const b = acc || [Infinity, Infinity, -Infinity, -Infinity];
  const tk = String(d).match(/[MmLlHhVvCcSsQqTtAaZz]|-?(?:\d+\.?\d*|\.\d+)(?:e[-+]?\d+)?/g) || [];
  let i = 0, cmd = 'M', x = 0, y = 0, sx = 0, sy = 0;
  const add = (px, py) => { if (px < b[0]) b[0] = px; if (py < b[1]) b[1] = py; if (px > b[2]) b[2] = px; if (py > b[3]) b[3] = py; };
  const n = () => parseFloat(tk[i++]);
  while (i < tk.length) {
    if (/[A-Za-z]/.test(tk[i])) cmd = tk[i++];
    if (cmd === 'Z' || cmd === 'z') { x = sx; y = sy; continue; }
    if (i >= tk.length || /[A-Za-z]/.test(tk[i])) continue;
    const rel = cmd === cmd.toLowerCase(), C = cmd.toUpperCase();
    const pt = () => { const px = n() + (rel ? x : 0), py = n() + (rel ? y : 0); add(px, py); return [px, py]; };
    if (C === 'M' || C === 'L' || C === 'T') { const q = pt(); x = q[0]; y = q[1]; if (C === 'M') { sx = x; sy = y; cmd = rel ? 'l' : 'L'; } }
    else if (C === 'H') { x = n() + (rel ? x : 0); add(x, y); }
    else if (C === 'V') { y = n() + (rel ? y : 0); add(x, y); }
    else if (C === 'C') { pt(); pt(); const q = pt(); x = q[0]; y = q[1]; }
    else if (C === 'S' || C === 'Q') { pt(); const q = pt(); x = q[0]; y = q[1]; }
    else if (C === 'A') { n(); n(); n(); n(); n(); const q = pt(); x = q[0]; y = q[1]; }
    else i++;
  }
  return b;
}

/* Ink box of a whole SVG string: every path d, rect and circle. [x0,y0,x1,y1]. */
function inkBoxOfSvg(svg) {
  const b = [Infinity, Infinity, -Infinity, -Infinity];
  /* rebuild-40: cached per path string. The hours and the breathing frames
   * share most of their path data, so each d is parsed once, not six times. */
  const cache = inkBoxOfSvg.cache || (inkBoxOfSvg.cache = new Map());
  if (cache.size > 200000) cache.clear();
  (svg.match(/\sd="[^"]*"/g) || []).forEach(a => {
    let p = cache.get(a);
    if (!p) { p = pathBox(a.slice(4, -1)); cache.set(a, p); }
    if (p[0] < b[0]) b[0] = p[0]; if (p[1] < b[1]) b[1] = p[1]; if (p[2] > b[2]) b[2] = p[2]; if (p[3] > b[3]) b[3] = p[3];
  });
  (svg.match(/<rect [^>]*>/g) || []).forEach(r => {
    const v = k => parseFloat((r.match(new RegExp('\\s' + k + '="(-?[\\d.]+)"')) || [0, 0])[1]);
    const x = v('x'), y = v('y'), w = v('width'), h = v('height');
    if (w || h) { if (x < b[0]) b[0] = x; if (y < b[1]) b[1] = y; if (x + w > b[2]) b[2] = x + w; if (y + h > b[3]) b[3] = y + h; }
  });
  (svg.match(/<circle [^>]*>/g) || []).forEach(c => {
    const v = k => parseFloat((c.match(new RegExp('\\s' + k + '="(-?[\\d.]+)"')) || [0, 0])[1]);
    const x = v('cx'), y = v('cy'), r = v('r');
    if (x - r < b[0]) b[0] = x - r; if (y - r < b[1]) b[1] = y - r; if (x + r > b[2]) b[2] = x + r; if (y + r > b[3]) b[3] = y + r;
  });
  return b.every(isFinite) ? b.map(v => Math.round(v)) : null;
}

/* The neck join. The rig publishes neckTop either as a point or as a bare y
 * (with the head's centre line in hcx); read both rather than guess one. */
const neckOf = rig => {
  const r = rig || {}, v = r.neckTop, cx = typeof r.hcx === 'number' ? r.hcx : 200;
  if (Array.isArray(v)) return { x: +v[0], y: +v[1] };
  if (v && typeof v === 'object') return { x: +(v.x != null ? v.x : cx), y: +(v.y != null ? v.y : 160) };
  return { x: cx, y: typeof v === 'number' ? v : 160 };
};

/* ── the render ────────────────────────────────────────────────────────── */

function svg(M, key, H, frame, tokens) {
  const g = M.geometry(key), p = M.paint(g, H);
  const f = frame || framesOf('', tokens)[0];
  /* ONE contour weight, every part (design-tokens.json -> contourWeight, in
   * head units). 1 HU = 100 canvas units in the figure's own box. */
  const cw = ((tokens.contourWeight && tokens.contourWeight.value) || 0.035) * 100;
  const stroke = ' fill="none" stroke="' + H.contour + '" stroke-width="' + cw + '" stroke-linejoin="round" stroke-linecap="round"';
  const shp = q => '<path d="' + q.d + '" fill="' + q.lit + '"/>'
    + (q.sd ? '<path d="' + q.sd + '" fill="' + q.shade + '"/>' : '')
    + '<path d="' + q.d + '"' + stroke + '/>';

  const prop = g.prop ? '<path d="' + g.prop.d + '" fill="' + H.m[g.prop.role][0] + '"/>' : '';
  const behind = PROP_BEHIND.indexOf(key) >= 0;

  const eyes = (g.eyes || []).map(d => {
    if (f.eyes !== 'closed') return '<path d="' + d + '" fill="' + H.contour + '"/>';
    /* The blink: each eye squashed to 16% of its height about its own centre.
     * Authored, not a second drawing \u2014 the model carries no closed eye. */
    const b = pathBox(d), cx = (b[0] + b[2]) / 2, cy = (b[1] + b[3]) / 2;
    return '<path d="' + d + '" fill="' + H.contour + '" transform="translate(' + cx.toFixed(2) + ' ' + cy.toFixed(2)
      + ') scale(1 0.16) translate(' + (-cx).toFixed(2) + ' ' + (-cy).toFixed(2) + ')"/>';
  }).join('');

  const head = p.head.map(shp).join('')
    + (p.marks || []).map(q => '<path d="' + q.d + '" fill="' + q.fill + '"/>').join('')
    + '<g transform="' + (g.glassesT || '') + '"' + stroke + '>' + (g.glasses || []).map(d => '<path d="' + d + '"/>').join('') + '</g>'
    + eyes
    + (g[f.mouth] ? '<path d="' + g[f.mouth] + '" fill="' + H.contour + '"/>' : '');

  /* The head rotates about the neck join and rides the shoulder line. */
  const nt = neckOf(g.rig);
  const headGroup = '<g transform="translate(0 ' + (f.shoulderY || 0) + ') rotate(' + (f.headRotate || 0) + ' '
    + nt.x.toFixed(1) + ' ' + nt.y.toFixed(1) + ')"><g transform="' + (g.headT || '') + '">' + head + '</g></g>';

  const body = p.body.map(shp).join('');
  return '<svg xmlns="http://www.w3.org/2000/svg" width="' + BOX[2] + '" height="' + BOX[3] + '" viewBox="' + BOX.join(' ') + '">'
    + (behind ? prop : '') + body + (behind ? '' : prop) + headGroup + '</svg>';
}

module.exports = { BOX, STRIPS, framesOf, svg, pathBox, pathBoxLegacy, inkBoxOfSvg, PROP_BEHIND };
