/* Dennis v2 — kit-plates.js
 *
 * ONE EXEMPLAR PER REMAINING CATEGORY. Eleven plates, each the pattern its
 * folder repeats: build these right and the other 79 are the same shapes with
 * different numbers.
 *
 * Every plate is a function of the hour. It returns flat shapes only — role
 * names, never literals (audit rule 3) — plus `type` entries the emitter
 * outlines. Nothing here knows what it will be rendered by.
 *
 *   const P = require('./kit-plates');
 *   P.PLATES['charts/line-6y'](M.NIGHT)   // -> {shapes, type, w, h}
 *
 * TYPE IS DATA, NOT MARKUP. A `type` entry carries its ground so audit rule 5
 * can sample contrast against what is actually behind it, and the emitter
 * outlines it so rule 10 finds no <text> node. A plate that drew its own text
 * would pass review and fail the moment a font was missing.
 */

'use strict';

const R = (x, y, w, h) => `M${x},${y}h${w}v${h}h${-w}z`;
const POLY = pts => 'M' + pts.map(p => p.join(',')).join('L') + 'Z';
/* A ring as a CLOSED FLAT SHAPE — outer ellipse, inner ellipse reversed, one
 * path, even-odd by winding. This is how every annotation survives §6: the
 * scrawls were strokes, and a stroke has no place in a kit whose contour is a
 * single declared width. */
function ring(cx, cy, rx, ry, t, wobble) {
  const N = 48, o = [], i2 = [];
  for (let i = 0; i < N; i++) {
    const a = (i / N) * Math.PI * 2;
    const w = wobble ? 1 + Math.sin(a * 3.7) * wobble : 1;
    o.push([(cx + Math.cos(a) * rx * w).toFixed(1), (cy + Math.sin(a) * ry * w).toFixed(1)]);
    i2.push([(cx + Math.cos(a) * (rx * w - t)).toFixed(1), (cy + Math.sin(a) * (ry * w - t)).toFixed(1)]);
  }
  return 'M' + o.map(p => p.join(',')).join('L') + 'Z M' + i2.reverse().map(p => p.join(',')).join('L') + 'Z';
}
const ink = (d, role) => ({ d, role, ink: true });
const mat = (d, role, tone) => ({ d, role, tone });
/* size is the type's cap height in plate units; the emitter needs it to lay out
 * outlines, and rule 5 needs `on` to know the ground behind it. */
const T = (x, y, size, role, on, text, weight) => ({ x, y, size, role, on, text, weight: weight || 400 });

const W = 320, H = 180;
const PLATES = {};
const plate = (id, fn) => { PLATES[id] = fn; };

/* ── charts ─────────────────────────────────────────────────────────────── */

plate('charts/line-6y', () => {
  const pts = [0.28, 0.44, 0.39, 0.62, 0.55, 0.86];
  const padL = 40, padB = 30, padT = 20, iw = W - padL - 18, ih = H - padT - padB;
  const xy = pts.map((v, i) => [padL + (i / (pts.length - 1)) * iw, padT + ih - v * ih]);
  const s = [ink(R(0, 0, W, H), 'ground')];
  [0, 0.5, 1].forEach(f => s.push(ink(R(padL, padT + ih - f * ih, iw, f === 0 ? 1.4 : 0.8), f === 0 ? 'axis' : 'rule')));
  /* The line is a filled ribbon, not a stroke — one contour width is a law
   * (rule 4), so a chart cannot spend it on a series. */
  const t = 2.2;
  const up = xy.map(p => [p[0], p[1] - t]), dn = xy.map(p => [p[0], p[1] + t]).reverse();
  s.push(ink(POLY(up.concat(dn)), 'subject'));
  xy.forEach((p, i) => s.push(ink(R(p[0] - 3, p[1] - 3, 6, 6), i === xy.length - 1 ? 'attention' : 'subject')));
  return { w: W, h: H, shapes: s, type: [T(padL, 16, 9, 'quiet', 'ground', 'CLAIMS PER QUARTER')] };
});

/* ── tables ─────────────────────────────────────────────────────────────── */

plate('tables/rows-5', () => {
  const rowH = 28, s = [ink(R(0, 0, W, H), 'ground')];
  const type = [];
  ['REGION', 'FILED', 'CHECKED'].forEach((h, i) => type.push(T(14 + i * 104, 20, 9, 'structure', 'rule', h, 700)));
  s.push(ink(R(0, 0, W, rowH), 'rule'));
  [['North', '1,204', '1,204'], ['Central', '980', '974'], ['South', '1,511', '1,388'], ['Coastal', '642', '642']]
    .forEach((row, r) => {
      const y = rowH * (r + 1);
      s.push(ink(R(0, y, W, rowH), r % 2 ? 'band' : 'ground'));
      row.forEach((c, i) => type.push(T(14 + i * 104, y + 19, 11, i ? 'structure' : 'quiet', r % 2 ? 'band' : 'ground', c)));
    });
  s.push(ink(R(0, rowH * 5, W, 1.2), 'rule'));
  return { w: W, h: H, shapes: s, type };
});

/* ── figures ────────────────────────────────────────────────────────────── */

plate('figures/big-number-l1', () => ({
  w: W, h: H,
  shapes: [ink(R(0, 0, W, H), 'ground'), ink(R(28, 126, 84, 3), 'attention')],
  type: [T(28, 92, 60, 'structure', 'ground', '1,388', 700),
         T(28, 150, 12, 'quiet', 'ground', 'checked, of 1,511 filed')],
}));

/* ── structure ──────────────────────────────────────────────────────────── */

plate('structure/said-happened-3', () => {
  const s = [ink(R(0, 0, W, H), 'ground'), ink(R(W / 2 - 0.6, 30, 1.2, 128), 'rule')];
  const type = [T(20, 22, 9, 'quiet', 'ground', 'WHAT WAS SAID'), T(W / 2 + 16, 22, 9, 'quiet', 'ground', 'WHAT HAPPENED')];
  [['"Best quarter yet"', 'Revenue fell 4%'], ['"No exposure"', '$40m written down'], ['"Fully staffed"', '11% vacancy']]
    .forEach((row, i) => {
      const y = 46 + i * 38;
      s.push(ink(R(0, y - 12, W, 34), i % 2 ? 'band' : 'ground'));
      type.push(T(20, y + 10, 11, 'quiet', i % 2 ? 'band' : 'ground', row[0]));
      type.push(T(W / 2 + 16, y + 10, 11, 'structure', i % 2 ? 'band' : 'ground', row[1]));
    });
  return { w: W, h: H, shapes: s, type };
});

/* ── paper ──────────────────────────────────────────────────────────────── */

plate('paper/receipt-4', () => {
  const s = [mat(R(56, 8, 208, 164), 'paper')];
  const type = [T(72, 34, 11, 'structure', 'ground', 'FILED', 700)];
  [['Q1', '312'], ['Q2', '406'], ['Q3', '289'], ['Q4', '381']].forEach((row, i) => {
    const y = 58 + i * 26;
    s.push(ink(R(72, y + 6, 176, 0.8), 'rule'));
    type.push(T(72, y, 11, 'quiet', 'ground', row[0]));
    type.push(T(214, y, 11, 'structure', 'ground', row[1]));
  });
  /* The torn edge is a shape, not a texture (§4.3). */
  const teeth = [];
  for (let x = 56; x < 264; x += 8) teeth.push([x, 172], [x + 4, 166], [x + 8, 172]);
  s.push(mat(POLY([[56, 178]].concat(teeth).concat([[264, 178]])), 'paper'));
  return { w: W, h: H, shapes: s, type };
});

/* ── cards ──────────────────────────────────────────────────────────────── */

plate('cards/quote-pull', () => ({
  w: W, h: H,
  shapes: [ink(R(0, 0, W, H), 'ground'), ink(R(22, 40, 4, 84), 'attention')],
  type: [T(40, 62, 17, 'structure', 'ground', '"Nobody asked where'),
         T(40, 86, 17, 'structure', 'ground', 'the other nine went."'),
         T(40, 116, 10, 'quiet', 'ground', 'Internal memo, March')],
}));

/* ── frames ─────────────────────────────────────────────────────────────── */

plate('frames/media-frame-t1', () => {
  const s = [ink(R(0, 0, W, H), 'ground'), ink(R(14, 14, W - 28, H - 46), 'band')];
  /* Corner marks rather than a full border: a border on a dark ground closes
   * the frame in and reads as a box, which §4.2 rule 5 warns about. */
  const L = 18, t = 2.4;
  [[14, 14, 1, 1], [W - 14, 14, -1, 1], [14, H - 32, 1, -1], [W - 14, H - 32, -1, -1]].forEach(([x, y, dx, dy]) => {
    s.push(ink(R(Math.min(x, x + dx * L), y - (dy < 0 ? t : 0), L, t), 'structure'));
    s.push(ink(R(x - (dx < 0 ? t : 0), Math.min(y, y + dy * L), t, L), 'structure'));
  });
  return { w: W, h: H, shapes: s, type: [T(14, H - 14, 10, 'quiet', 'ground', 'SOURCE — filing, p.41')] };
});

/* ── overlays ───────────────────────────────────────────────────────────── */

plate('overlays/lower-third', () => ({
  w: W, h: H,
  shapes: [ink(R(14, 112, 232, 48), 'ground'), ink(R(14, 112, 5, 48), 'attention')],
  type: [T(32, 134, 15, 'structure', 'ground', 'Dennis', 700),
         T(32, 152, 10, 'quiet', 'ground', 'reads the filings so you do not have to')],
}));

/* ── peers ──────────────────────────────────────────────────────────────── */

plate('peers/peer-strip', () => {
  const s = [ink(R(0, 0, W, H), 'ground')];
  const type = [T(18, 24, 9, 'quiet', 'ground', 'AGAINST THE SECTOR')];
  const vals = [0.34, 0.51, 0.47, 0.88, 0.42];
  vals.forEach((v, i) => {
    const y = 42 + i * 26;
    s.push(ink(R(96, y, 200, 14), 'band'));
    s.push(ink(R(96, y, 200 * v, 14), i === 3 ? 'attention' : 'subject'));
    type.push(T(18, y + 11, 10, 'quiet', 'ground', ['Alpha', 'Beta', 'Gamma', 'OURS', 'Delta'][i]));
  });
  return { w: W, h: H, shapes: s, type };
});

/* ── cycles ─────────────────────────────────────────────────────────────── */

plate('cycles/cycle-frame', () => {
  const s = [ink(R(0, 0, W, H), 'ground')];
  const cx = W / 2, cy = 92, rad = 56;
  s.push(ink(ring(cx, cy, rad, rad, 2, 0), 'rule'));
  const type = [];
  ['FILE', 'CHECK', 'RESTATE', 'REPEAT'].forEach((label, i) => {
    const a = -Math.PI / 2 + (i / 4) * Math.PI * 2;
    const x = cx + Math.cos(a) * rad, y = cy + Math.sin(a) * rad;
    s.push(ink(R(x - 7, y - 7, 14, 14), i === 3 ? 'attention' : 'subject'));
    type.push(T(x + 12, y + 4, 9, 'quiet', 'ground', label));
  });
  return { w: W, h: H, shapes: s, type };
});

/* ── annotations ────────────────────────────────────────────────────────── */

/* PROPOSAL, NOT A DECISION. The ten scrawl marks were the only stroke-based
 * assets in the kit and §6 removed the boil they depended on. Rebuilt as a
 * closed flat ring in the attention colour they satisfy rules 1-4, and the
 * hand-drawn character survives as a WOBBLE IN THE OUTLINE rather than as a
 * moving stroke. It is a real change and the operator has not agreed to it. */
plate('annotations/scrawl-oval-wide', () => ({
  w: W, h: H, transparent: true,
  shapes: [ink(ring(160, 90, 108, 46, 3.2, 0.035), 'attention')],
  type: [],
}));

module.exports = { PLATES, ids: Object.keys(PLATES), R, POLY, ring };
