/* Dennis v2 — grounds.js (rebuild-41)
 *
 * THE RESTYLE, IN ONE PLACE. The plates keep their layouts, keys, slots and
 * roles; this module changes their colour, weight and finish:
 *
 *   groundOf(key)            paper | screen | mark | null   (design-tokens plateStyle.grounds)
 *   inkFor(tokens, hour, k)  the plate's ink set (plateInk[ground], or the old `ink`)
 *   palFor(tokens, hour, k)  the legacy-role palette a plate author is handed
 *   restyle(P, key, tokens)  scale the layout into the safe area, bolden bars,
 *                            set the lead figure, floor 9:16 type, then make the
 *                            drawing flat (every opacity 0 or 1) and, on paper,
 *                            outline every filled shape in the one contour
 *
 * Nothing here is placed by eye: every number is in design-tokens.json →
 * plateStyle, and every move is published back onto the plate (meta.restyle).
 */
'use strict';

const NOT_TEXT = ['band', 'marker', 'plot-area', 'bars', 'bridge', 'path', 'spark', 'point-column', 'bar',
  'media', 'highlight-band', 'wraps', 'control', 'mark-area'];
const DATA = ['plot-area', 'bars', 'bar', 'bridge', 'path', 'spark', 'media', 'mark-area'];
const DATA_GAP = 14;
const isText = s => !(s.overlay || s.container || s.region || NOT_TEXT.indexOf(s.role) >= 0);

function groundOf(key, tokens) {
  const G = (tokens && tokens.plateStyle && tokens.plateStyle.grounds) || {};
  const k = String(key || ''), fam = k.split('/')[0], id = k.replace(/-(16x9|9x16)$/, '');
  if ((G.screenKeys || []).indexOf(id) >= 0) return 'screen';
  for (const g of ['paper', 'screen', 'mark']) if ((G[g] || []).indexOf(fam) >= 0) return g;
  if (!k.includes('/') && ['paper', 'screen', 'mark'].indexOf(k) >= 0) return k;
  return null;
}
function inkFor(tokens, hour, key) {
  const g = groundOf(key, tokens), H = tokens.hours[hour] || tokens.hours.night;
  return g && H.plateInk ? H.plateInk[g] : H.ink;
}
/* The legacy roles the drawn authors speak (port.js's eight lines), per ground.
 * On paper `down` is marker red — the old kit's own meaning — because lamp
 * amber cannot carry a bare line on cream. */
function palFor(tokens, hour, key) {
  const I = inkFor(tokens, hour, key), g = groundOf(key, tokens);
  return {
    surfaceKey: 'night-card', grain: null, hour, groundKind: g || 'legacy',
    ground: g === 'mark' ? 'none' : I.ground, ground2: I.band, structure: I.structure,
    down: I.down || (g === 'paper' ? I.attention : I.subject2), second: I.subject2, up: I.subject, neutralData: I.quiet,
    attention: I.attention, otherParty: I.axis,
  };
}

/* ── colour ─────────────────────────────────────────────────────────────── */
const hex2 = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16));
const lin = c => { c /= 255; return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); };
function oklabLin(v) {
  const l = Math.cbrt(0.4122214708 * v[0] + 0.5363325363 * v[1] + 0.0514459929 * v[2]);
  const m = Math.cbrt(0.2119034982 * v[0] + 0.6806995451 * v[1] + 0.1073969566 * v[2]);
  const s = Math.cbrt(0.0883024619 * v[0] + 0.2817188376 * v[1] + 0.6299787005 * v[2]);
  return [0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s, 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s, 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s];
}
const oklab = h => oklabLin(hex2(h).map(lin));
const lum = h => { const v = hex2(h).map(lin); return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2]; };
const wcag = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
const CVD = {
  protan: [[0.152286, 1.052583, -0.204868], [0.114503, 0.786281, 0.099216], [-0.003882, -0.048116, 1.051998]],
  deutan: [[0.367322, 0.860646, -0.227968], [0.280085, 0.672501, 0.047413], [-0.01182, 0.04294, 0.968881]],
  tritan: [[1.255528, -0.076749, -0.178779], [-0.078411, 0.930809, 0.147602], [0.004733, 0.691367, 0.3039]],
};
function dE(a, b, kind) {
  const f = h => { const v = hex2(h).map(lin), M = CVD[kind]; return oklabLin(M ? M.map(r => Math.max(0, Math.min(1, r[0] * v[0] + r[1] * v[1] + r[2] * v[2]))) : v); };
  const p = f(a), q = f(b);
  return Math.hypot(p[0] - q[0], p[1] - q[1], p[2] - q[2]);
}
const NEUTRAL = ['ground', 'band', 'rule', 'axis', 'quiet', 'structure'];
const CHROMA = ['subject', 'subject2', 'subject3', 'subject4', 'subject5', 'attention'];

/* A colour at a partial opacity, resolved to the palette ink it reads as over
 * the ground. Neutral inks resolve among the neutrals; a chromatic ink at 0.4
 * or more stays itself, fainter than that it is a wash and resolves among the
 * quiet neutrals. Any literal that is not a palette ink resolves to the nearest
 * neutral. The result is always a palette value at opacity 1 (or 0). */
function snapper(I, overlay) {
  const cache = {}, vals = {};
  NEUTRAL.concat(CHROMA, ['down']).forEach(k => { if (I[k]) vals[I[k].toUpperCase()] = k; });
  const G = hex2(I.ground || '#000000');
  const near = (rgb, names) => {
    const p = oklabLin(rgb.map(lin)); let best = null, bd = 9;
    names.forEach(n => { if (!I[n]) return; const q = oklab(I[n]); const d = Math.hypot(p[0] - q[0], p[1] - q[1], p[2] - q[2]); if (d < bd) { bd = d; best = I[n]; } });
    return best;
  };
  return function (col, a) {
    if (!col || col === 'none' || col[0] !== '#') return { col, a: a > 0 ? 1 : 0 };
    const C = col.toUpperCase(), k = C + '@' + a.toFixed(3);
    if (cache[k]) return cache[k];
    const role = vals[C];
    const mix = hex2(C).map((c, i) => c * a + G[i] * (1 - a));
    let out;
    if (a <= 0.02) out = { col: C, a: 0 };
    else if (overlay) out = a >= 0.4 ? { col: role ? C : near(hex2(C), NEUTRAL.concat(CHROMA)), a: 1 } : { col: C, a: 0 };
    else if (role && (CHROMA.indexOf(role) >= 0 || role === 'down')) out = a >= 0.4 ? { col: C, a: 1 } : { col: near(mix, ['ground', 'band', 'rule', 'axis']), a: 1 };
    else out = { col: near(mix, NEUTRAL), a: 1 };
    return (cache[k] = out);
  };
}

/* Every element's fill/stroke and opacity resolved to a palette ink at 0 or 1.
 * On paper, every filled shape that is not ground gets the one contour. */
function flatten(svg, I, ground, contour) {
  const snap = snapper(I, ground === 'mark');
  const groundHex = (I.ground || '').toUpperCase();
  let first = true;
  return svg.replace(/<(path|rect|circle|ellipse|polygon|polyline|line)\b([^>]*?)\/>/g, (all, tag, body) => {
    const at = {};
    body.replace(/([a-z-]+)="([^"]*)"/g, (m, k, v) => { at[k] = v; return m; });
    if (first && tag === 'rect' && at.x === '0' && at.y === '0') { first = false; return all; }
    first = false;
    const op = at.opacity != null ? +at.opacity : 1;
    let fill = at.fill, stroke = at.stroke;
    const out = Object.assign({}, at);
    delete out.opacity; delete out['fill-opacity']; delete out['stroke-opacity'];
    if (fill && fill !== 'none') {
      const r = snap(fill, op * (at['fill-opacity'] != null ? +at['fill-opacity'] : 1));
      out.fill = r.col; if (!r.a) out['fill-opacity'] = '0';
      fill = r.a ? r.col : 'none';
    }
    if (stroke && stroke !== 'none') {
      const r = snap(stroke, op * (at['stroke-opacity'] != null ? +at['stroke-opacity'] : 1));
      out.stroke = r.col; if (!r.a) out['stroke-opacity'] = '0';
    }
    const filled = fill && fill !== 'none' && (fill || '').toUpperCase() !== groundHex;
    if (contour && filled && (!stroke || stroke === 'none')) {
      out.stroke = contour.colour; out['stroke-width'] = contour.width; out['stroke-linejoin'] = 'round'; out['data-contour'] = '1';
    }
    return '<' + tag + ' ' + Object.keys(out).map(k => k + '="' + out[k] + '"').join(' ') + '/>';
  });
}

/* ── geometry ───────────────────────────────────────────────────────────── */
const COLUMN = /^(bar|pair|step)-(\d+|open|close)$/;
/* A slot that publishes the plate's own usable area (end cards derive it from
 * YouTube's end-screen keep-outs) is the zone, never content, and never moves. */
const KEEP = /^content-area$/;
function zoneOf(S, W, H, ST) {
  const land = W >= H;
  let z = land ? [W * 0.05, H * 0.05, W * 0.95, H * 0.95] : [W * 0.05, ST.shorts.readable[0], W * 0.95, ST.shorts.readable[1]];
  Object.keys(S).forEach(n => { const s = S[n]; if (KEEP.test(s.role)) z = [Math.max(z[0], s.x), Math.max(z[1], s.y), Math.min(z[2], s.x + s.w), Math.min(z[3], s.y + s.h)]; });
  return z;
}

function restyle(P, key, tokens) {
  const ground = groundOf(key, tokens);
  if (!ground || P._restyled) return P;
  P._restyled = true;
  const ST = tokens.plateStyle, W = P.w, H = P.h, land = W >= H, aspect = land ? '16x9' : '9x16';
  const S = P.slots, roles = Object.assign({}, (P.meta && P.meta.typeRoles) || {});
  const id = String(key).replace(/-(16x9|9x16)$/, ''), fam = id.split('/')[0];
  const info = { ground, aspect, kx: 1, ky: 1, tx: 0, ty: 0, u: 1 };
  const full = !(fam === 'annotations' || P.meta.ground === 'none' || P.pal.ground === 'none');

  /* 1 · Scale the layout into the safe area. Identity where it already fills
   * 70% of both dimensions inside it; otherwise one uniform scale (capped
   * anisotropy where one dimension is thin), position kept relative. */
  const zone = zoneOf(S, W, H, ST);
  const names = Object.keys(S).filter(n => !S[n].overlay && S[n].role !== 'highlight-band' && !S[n].container && !KEEP.test(S[n].role));
  if (full && names.length) {
    let b = [Infinity, Infinity, -Infinity, -Infinity];
    names.forEach(n => { const s = S[n]; b = [Math.min(b[0], s.x), Math.min(b[1], s.y), Math.max(b[2], s.x + s.w), Math.max(b[3], s.y + s.h)]; });
    const zw = zone[2] - zone[0], zh = zone[3] - zone[1], bw = b[2] - b[0], bh = b[3] - b[1], F = ST.contentFill;
    const inside = b[0] >= zone[0] - 1 && b[1] >= zone[1] - 1 && b[2] <= zone[2] + 1 && b[3] <= zone[3] + 1;
    if (!(inside && bw / zw >= F && bh / zh >= F)) {
      const fit = Math.min(zw / bw, zh / bh);
      const u = inside ? Math.max(1, fit) : fit;
      let kx = Math.min(zw / bw, Math.max(u, F * zw / bw)), ky = Math.min(zh / bh, Math.max(u, F * zh / bh));
      const A = ST.maxAnisotropy || 1.25;      if (kx > ky * A) kx = ky * A; if (ky > kx * A) ky = kx * A;
      const rel = (b0, z0, zl, bl) => (zl - bl > 1 ? Math.max(0, Math.min(1, (b0 - z0) / (zl - bl))) : 0.5);
      const nx0 = zone[0] + (zw - bw * kx) * rel(b[0], zone[0], zw, bw), ny0 = zone[1] + (zh - bh * ky) * rel(b[1], zone[1], zh, bh);
      Object.assign(info, { kx: +kx.toFixed(4), ky: +ky.toFixed(4), u: +Math.min(kx, ky).toFixed(4), tx: +(nx0 - b[0] * kx).toFixed(2), ty: +(ny0 - b[1] * ky).toFixed(2) });
    }
  }
  /* 41b: how many lines each text box was authored for, before the fit and the
   * 9:16 floor reshape it; motion.theNumber keeps a wrapping slot out of the
   * one-line figure pick. Published as slot.authoredLines. */
  Object.keys(S).forEach(n => { const s = S[n], R0 = roles[s.role]; if (isText(s) && R0 && R0.size) s.authoredLines = Math.max(1, Math.floor(s.h / (R0.size * 1.15))); });
  const mx = x => x * info.kx + info.tx, my = y => y * info.ky + info.ty;
  if (info.kx !== 1 || info.ky !== 1 || info.tx || info.ty) {
    Object.keys(S).forEach(n => {
      const s = S[n];
      if (KEEP.test(s.role)) return; // derived from the end screen's keep-outs: it IS the zone
      /* Every box, text included, takes the layout's own scale each way: where
       * the two differ the box grows past the type (which scales by u, the
       * smaller), so the bigger plate buys budget instead of losing it. */
      Object.assign(s, { x: Math.round(mx(s.x)), y: Math.round(my(s.y)), w: Math.round(s.w * info.kx), h: Math.round(s.h * info.ky) });
      if (typeof s.anchorX === 'number') s.anchorX = Math.round(mx(s.anchorX));
      if (typeof s.baselineY === 'number') s.baselineY = Math.round(my(s.baselineY));
      if (typeof s.axisY === 'number') s.axisY = Math.round(my(s.axisY));
      if (Array.isArray(s.groundBox)) s.groundBox = [Math.round(mx(s.groundBox[0])), Math.round(my(s.groundBox[1])), Math.round(s.groundBox[2] * info.kx), Math.round(s.groundBox[3] * info.ky)];
    });
    (P.decor || []).forEach(d => Object.assign(d, { x: Math.round(mx(d.x)), y: Math.round(my(d.y)), w: Math.round(d.w * info.kx), h: Math.round(d.h * info.ky) }));
  }
  if (P.meta.safe) P.meta.safe = Object.assign({}, P.meta.safe, { top: ST.shorts.readable[0], bottom: ST.shorts.readable[1] });

  /* 2 · Type: scale with the layout; flat (no opacity — a quiet caption is the
   * quiet ink, not structure at 0.72); on 9:16 nothing under the floors. */
  const used = {};
  Object.keys(S).forEach(n => { if (isText(S[n])) (used[S[n].role] = used[S[n].role] || []).push(n); });
  const grew = [], rank = {};
  Object.keys(roles).forEach(rn => {
    const R = roles[rn] = Object.assign({}, roles[rn]);
    const was = R.size || 30;
    rank[rn] = was;
    R.authoredSize = was; // published: the hierarchy before the 9:16 floor (motion.theNumber, 41b)
    let size = Math.round(was * info.u);
    if (R.opacity != null && R.opacity < 1) { if (R.opacity < 0.9 && (R.colour === 'structure' || !R.colour)) R.colour = 'quiet'; R.opacity = 1; }
    if (!land && used[rn]) {
      const head = was >= 56 || /headline|title|statement|hook|quote|claim|display|big/.test(rn);
      const floor = head ? ST.shorts.headlineFloor : ST.shorts.typeFloor;
      if (size < floor) {
        /* Grow the box with the type where the room is there, so the bigger
         * size does not cut the budget; otherwise the type still wins. */
        const k = floor / size;
        used[rn].forEach(n => {
          /* rebuild-41b (bot fix 1): a box clamped at the zone edge may slide; it
           * stops DATA_GAP short of any data region it was clear of, so a
           * right-aligned axis label never crosses into the plot. */
          const s = S[n], w2 = Math.min(Math.round(s.w * k), Math.round(zone[2] - zone[0]));
          const place = w => {
            const x2 = s.align === 'right' ? s.x + s.w - w : s.align === 'center' ? s.x + (s.w - w) / 2 : s.x;
            return { x: Math.max(zone[0], Math.min(x2, zone[2] - w)), y: s.y, w: w, h: s.h };
          };
          const meets = (a, b) => !(a.x + a.w <= b.x || a.x >= b.x + b.w || a.y + a.h <= b.y || a.y >= b.y + b.h);
          const hitsText = c => Object.keys(S).some(m => m !== n && isText(S[m]) && meets(c, S[m]));
          const slid = c => s.align === 'right' ? c.x + c.w > s.x + s.w : s.align !== 'center' && c.x < s.x;
          const padded = c => ({ x: c.x - DATA_GAP, y: c.y, w: c.w + 2 * DATA_GAP, h: c.h });
          const intrudes = c => slid(c) && Object.keys(S).some(m => m !== n && DATA.indexOf(S[m].role) >= 0 && !meets(s, S[m]) && meets(padded(c), S[m]));
          let cand = place(w2);
          if (!hitsText(cand)) for (let w = w2; intrudes(cand) && w > s.w; ) cand = place(--w);
          if (!hitsText(cand) && !intrudes(cand) && cand.w > s.w) { Object.assign(s, { x: Math.round(cand.x), w: cand.w }); grew.push(n); }
        });
        size = floor;
      }
    }
    R.size = size;
  });
  /* Roles only non-text slots use (a marker's tag, a band label) still carry
   * type the viewer reads on 9:16: same floor, no box change. */
  if (!land) Object.keys(roles).forEach(rn => { if (!used[rn] && Object.keys(S).some(n => S[n].role === rn) && (roles[rn].size || 99) < ST.shorts.typeFloor) roles[rn].size = ST.shorts.typeFloor; });

  /* 3 · Bars at least barToGap x the gap beside them. Each too-wide gap
   * closes from both sides (both neighbours grow into it), the outer edges of
   * the run stay put, and a column whose anchor was its centre keeps its
   * anchor on its new centre. Widths only grow and gaps only shrink, so the
   * passes converge. */
  /* rebuild-41 (bot answer R41.2): bar-N, pair-N and step-* are role `bar`,
   * still containers with anchorX, never regions. Authors not yet renamed at
   * source are swept here, so the published role is one name everywhere. */
  Object.keys(S).forEach(n => {
    const s = S[n]; if (!COLUMN.test(n) || (s.role !== 'point-column' && s.role !== 'bar')) return;
    /* the legacy bar authors published regions; a bar region beside the plot
     * region reads as a filled share to the bot, so they become containers */
    s.role = 'bar'; s.container = true; delete s.region;
    if (typeof s.anchorX !== 'number') s.anchorX = Math.round(s.x + s.w / 2);
  });
  const cols = Object.keys(S).filter(n => COLUMN.test(n)).map(n => S[n]).filter(s => s.w > 0).sort((a, b) => a.x - b.x);
  const centred = cols.map(s => typeof s.anchorX === 'number' && Math.abs(s.anchorX - (s.x + s.w / 2)) < 2);
  const K = ST.barToGap || 2;
  for (let pass = 0; pass < 6; pass++) {
    for (let i = 1; i < cols.length; i++) {
      const a = cols[i - 1], c = cols[i];
      if (c.y > a.y + a.h || a.y > c.y + c.h) continue;
      const g = c.x - (a.x + a.w), mw = Math.min(a.w, c.w);
      if (g <= 0 || mw >= K * g) continue;
      const g2 = Math.floor((2 * mw + g) / (2 * K + 1)), d = (g - g2) / 2;
      a.w += Math.floor(d); c.x -= Math.ceil(d); c.w += Math.ceil(d);
    }
  }
  cols.forEach((s, i) => { if (centred[i]) s.anchorX = Math.round(s.x + s.w / 2); });

  /* 4 · The lead figure on number plates spans leadFigureSpan of the width:
   * the slot is at least that wide, so a string at the slot's budget (which
   * budget.js derives from this box) spans it at the role size. The size is
   * NOT raised past the scaled size here: that cut 9:16 budgets below the
   * sample copy (move-on-the-day went to 4 characters). `fit: width` is
   * published so a renderer may set a short figure up to the box width. */
  const number = (fam === 'figures' || fam === 'shorts') ;
  if (number) {
    const textNames = Object.keys(S).filter(n => isText(S[n]) && roles[S[n].role]);
    let top = 0; textNames.forEach(n => { top = Math.max(top, roles[S[n].role].size || 0); });
    const isFig = rn => /courier/i.test(roles[rn].font || '') || /value|figure|huge|number|numerator|denominator|reported|margin|total|spread/.test(rn);
    const leadRoles = Object.keys(roles).filter(rn => (roles[rn].size || 0) === top && used[rn] && isFig(rn));
    const lead = textNames.filter(n => leadRoles.indexOf(S[n].role) >= 0);
    if (top >= (land ? 120 : 96) && lead.length) {
      const span = ST.leadFigureSpan * W;
      const side = lead.length > 1 && lead.every(n => S[n].y < S[lead[0]].y + S[lead[0]].h && S[n].y + S[n].h > S[lead[0]].y);
      const want = side ? Math.ceil(span / lead.length) + 24 : Math.ceil(span) + 8;
      lead.forEach(n => {
        const s = S[n];
        if (s.w < want) { const cx = s.x + s.w / 2; s.w = want; s.x = Math.round(Math.max(zone[0], Math.min(cx - want / 2, zone[2] - want))); }
        s.fit = 'width';
      });
      leadRoles.forEach(rn => { roles[rn].fit = 'width'; });
      info.lead = lead;
    }
  }
  P.meta.typeRoles = roles;
  if (grew.length) info.grewForFloor = grew;
  info.rank = rank; // authored sizes: motion.theNumber ranks by these (41b)
  P.meta.ground = ground;
  P.meta.restyle = info;

  /* 5 · The drawing: the layout transform, then flat paint. */
  const I = inkFor(tokens, P.pal.hour || 'night', key);
  const cw = ST.contour.width / ((info.kx + info.ky) / 2);
  const contour = ground === 'paper' ? { colour: ST.contour.colour, width: +cw.toFixed(3) } : null;
  const raw = P.toSVG;
  const memo = {};
  P.toSVG = function (o) {
    const k = JSON.stringify(o || {});
    if (memo[k]) return memo[k];
    let svg = flatten(raw.call(P, o), I, ground, contour);
    if (info.kx !== 1 || info.ky !== 1 || info.tx || info.ty) {
      const at = svg.indexOf('/>', svg.indexOf('<rect')) + 2;
      svg = svg.slice(0, at) + '<g transform="matrix(' + info.kx + ' 0 0 ' + info.ky + ' ' + info.tx + ' ' + info.ty + ')">' + svg.slice(at).replace(/<\/svg>$/, '</g></svg>');
    }
    return (memo[k] = svg);
  };
  return P;
}

/* Contrast for rule 32: every pair it measures, so the audit can print the worst. */
function contrastReport(tokens) {
  const C = tokens.plateStyle.contrast, out = { text: [], nonText: [], cvd: [], down: [] };
  ['night', 'dusk'].forEach(h => ['screen', 'paper', 'mark'].forEach(g => {
    const I = tokens.hours[h].plateInk[g];
    const grounds = g === 'mark' ? [tokens.hours[h].plateInk.paper.ground, tokens.hours[h].plateInk.screen.ground] : [I.ground];
    grounds.forEach(gr => {
      if (I.down) out.nonText.push({ id: h + '.' + g + '.down', r: wcag(I.down, gr), min: C.nonText });
      CHROMA.forEach(k => { if (g === 'paper' && C.paperFillOnly.indexOf(k) >= 0) return; if (g === 'mark' && k !== 'attention') return; out.nonText.push({ id: h + '.' + g + '.' + k, r: wcag(I[k], gr), min: C.nonText }); });
      if (g !== 'mark') ['structure', 'quiet'].forEach(k => out.text.push({ id: h + '.' + g + '.' + k, r: wcag(I[k], gr), min: C.text }));
    });
    if (g !== 'mark') {
      const ks = CHROMA;
      ['none', 'protan', 'deutan', 'tritan'].forEach(kind => { let m = 9, pr = ''; for (let i = 0; i < ks.length; i++) for (let j = i + 1; j < ks.length; j++) { const d = dE(I[ks[i]], I[ks[j]], kind); if (d < m) { m = d; pr = ks[i] + '/' + ks[j]; } }
        out.cvd.push({ id: h + '.' + g + '.' + kind, d: m, pair: pr, min: kind === 'none' ? C.cvd.normal : C.cvd.simulated });
        /* down is a fall, attention the highlight: a fall must never read as the highlight */
        if (I.down && C.downApart) out.down.push({ id: h + '.' + g + '.' + kind + ' down/attention', d: dE(I.down, I.attention, kind), min: kind === 'none' ? C.downApart.normal : C.downApart.simulated }); });
    }
  }));
  return out;
}

module.exports = { zoneOf, KEEP, groundOf, inkFor, palFor, restyle, flatten, contrastReport, wcag, dE, isText, NOT_TEXT, CHROMA, NEUTRAL };
