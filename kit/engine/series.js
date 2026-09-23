/* Dennis v2 — series.js
 *
 * THE MISSING RENDERER. Every data plate in the kit publishes a `region` slot
 * with a `renderer` name and a note saying, in the plate's own words, "the
 * plate draws nothing here — engine/series.js draws it from the data". Six
 * renderer names are referenced across four families:
 *
 *     series.cycleArc      cycles/       the intervening periods, as a path
 *     series.rowBars       peers/        one horizontal bar per row
 *     series.sparkBars     tables/       a row's six values as a shape
 *     series.axisMark      peers/, structure/   one position on an axis
 *     series.historyBand   structure/    an extent on an axis, not a bar
 *     series.rangeMark     tables/       a position between a low and a high
 *
 * **`engine/series.js` was never in the handoff.** That is why every chart,
 * table and peer strip renders as an empty frame: the furniture is there and
 * the data layer does not exist. The kit's own `proof/pipeline-plates.html`
 * says as much — "Region fills below stand in for engine/series.js" — so the
 * gap was known and was never closed.
 *
 * This is that file, written against the contracts the plates already publish.
 *
 * THE RULE EVERY RENDERER HERE OBEYS: **read the geometry the plate published,
 * re-derive nothing.** A renderer that recomputes a column position from its
 * own idea of the layout will drift the moment the plate changes, and the
 * drift is invisible — a line half a tick off the axis looks like a line.
 * Every x comes from `anchorX`, every box from the slot.
 *
 *   const S = require('./series');
 *   S.rowBars({ box: slots.bars, rows: rowSlots, values, accent: 0, ink });
 *   // -> [{ tag:'rect'|'path'|'circle', attrs:{...} }]   plus, sometimes, a
 *   //    `returns` object the caller positions a text slot from.
 *
 * Renderers return PLAIN NODE DESCRIPTIONS, not SVG strings and not DOM. The
 * emitter turns them into paths, the review surface turns them into elements,
 * and neither has to agree about anything but the shape of this array.
 */

'use strict';

/* ── helpers ────────────────────────────────────────────────────────────── */

const num = v => (typeof v === 'number' && isFinite(v) ? v : null);
const clamp01 = v => Math.max(0, Math.min(1, v));
const rect = (x, y, w, h, fill) => ({ tag: 'rect', attrs: { x: r1(x), y: r1(y), width: r1(Math.max(0, w)), height: r1(Math.max(0, h)), fill } });
const circle = (cx, cy, r, fill) => ({ tag: 'circle', attrs: { cx: r1(cx), cy: r1(cy), r: r1(r), fill } });
const path = (d, attrs) => ({ tag: 'path', attrs: Object.assign({ d, fill: 'none' }, attrs || {}) });
const r1 = n => Math.round(n * 10) / 10;

/* A scale that always includes zero when the data crosses it, because a bar
 * chart whose baseline is not zero is a lie the audit cannot catch. */
function extent(values, opts) {
  const o = opts || {};
  const vs = values.filter(v => num(v) !== null);
  let lo = o.min != null ? o.min : Math.min.apply(null, vs);
  let hi = o.max != null ? o.max : Math.max.apply(null, vs);
  if (o.zero !== false && lo > 0) lo = 0;
  if (o.zero !== false && hi < 0) hi = 0;
  if (hi === lo) { hi = lo + 1; }
  return { lo, hi, span: hi - lo };
}

/* ── series.cycleArc ────────────────────────────────────────────────────────
 *
 * cycles/: "every period between the two moments… draws it from the data and
 * RETURNS THE TROUGH'S COORDINATES". The return value is part of the contract —
 * the plate reserves a `trough` box but only the data knows where the minimum
 * sits, so the caller positions that slot from what comes back here. */
function cycleArc(o) {
  const box = o.box, values = o.values || [], ink = o.ink || {};
  if (!box || values.length < 2) return { nodes: [], returns: null };
  const e = extent(values, { zero: false });
  const x = i => box.x + (i / (values.length - 1)) * box.w;
  const y = v => box.y + box.h - ((v - e.lo) / e.span) * box.h;
  const pts = values.map((v, i) => [x(i), y(v)]);

  /* A band, not an arrow (the manifest is explicit). Drawn as a filled ribbon
   * so it needs no stroke width of its own — the flat families have one
   * contour weight and a series may not spend it. */
  const t = (o.weight || 10) / 2;
  const up = pts.map(p => [p[0], p[1] - t]);
  const dn = pts.slice().reverse().map(p => [p[0], p[1] + t]);
  const d = 'M' + up.concat(dn).map(p => r1(p[0]) + ',' + r1(p[1])).join('L') + 'Z';

  const nodes = [{ tag: 'path', attrs: { d, fill: ink.subject || '#7FD4E8' } }];
  values.forEach((v, i) => nodes.push(circle(x(i), y(v), o.dot || 7, ink.subject || '#7FD4E8')));

  let mi = 0;
  values.forEach((v, i) => { if (num(v) !== null && v < values[mi]) mi = i; });
  nodes.push(circle(x(mi), y(values[mi]), (o.dot || 7) + 5, ink.attention || '#F07A5A'));

  /* The trough box, centred on the minimum and lifted clear of the band. */
  const tb = o.troughBox;
  return {
    nodes,
    returns: {
      minIndex: mi, minValue: values[mi],
      x: r1(x(mi)), y: r1(y(values[mi])),
      troughBox: tb ? { x: r1(x(mi) - tb.w / 2), y: r1(y(values[mi]) - tb.h - 18), w: tb.w, h: tb.h } : null,
    },
  };
}

/* ── series.rowBars ─────────────────────────────────────────────────────────
 *
 * peers/: "one horizontal bar per row, ON A SCALE SHARED ACROSS THE ROWS, from
 * a zero rule the renderer places." The shared scale is the whole point — five
 * bars each normalised to themselves is five plates, not one. */
function rowBars(o) {
  const box = o.box, rows = o.rows || [], values = o.values || [], ink = o.ink || {};
  if (!box || !rows.length) return { nodes: [], returns: null };
  const e = extent(values, o);
  const zeroX = box.x + ((0 - e.lo) / e.span) * box.w;
  const nodes = [];
  /* The zero rule is the renderer's, per the note — the plate does not draw it
   * because the plate does not know where zero falls. */
  if (e.lo < 0) nodes.push(rect(zeroX - 1, box.y, 2, box.h, ink.axis || '#4A566A'));
  values.forEach((v, i) => {
    const row = rows[i]; if (!row || num(v) === null) return;
    const h = Math.round(row.h * (o.thickness || 0.42));
    const vx = box.x + ((v - e.lo) / e.span) * box.w;
    nodes.push(rect(Math.min(zeroX, vx), row.y + (row.h - h) / 2, Math.abs(vx - zeroX), h,
      i === o.accent ? (ink.attention || '#F07A5A') : (ink.subject || '#7FD4E8')));
  });
  return { nodes, returns: { zeroX: r1(zeroX), lo: e.lo, hi: e.hi } };
}

/* ── series.sparkBars ───────────────────────────────────────────────────────
 *
 * tables/: "the row's own six values as a shape." Own — each spark is scaled
 * to its own row, which is correct here and wrong in rowBars, and the two
 * notes say so. Reading them as the same problem is how a sparkline column
 * ends up lying about magnitude. */
function sparkBars(o) {
  const box = o.box, values = o.values || [], ink = o.ink || {};
  if (!box || !values.length) return { nodes: [], returns: null };
  const e = extent(values, { zero: true });
  const gap = o.gap == null ? 0.22 : o.gap;
  const bw = box.w / values.length;
  const zeroY = box.y + box.h - ((0 - e.lo) / e.span) * box.h;
  const nodes = values.map((v, i) => {
    if (num(v) === null) return null;
    const vy = box.y + box.h - ((v - e.lo) / e.span) * box.h;
    return rect(box.x + i * bw + bw * gap / 2, Math.min(zeroY, vy), bw * (1 - gap), Math.abs(vy - zeroY),
      v < 0 ? (ink.attention || '#F07A5A') : (ink.quiet || '#8592A6'));
  }).filter(Boolean);
  return { nodes, returns: { zeroY: r1(zeroY) } };
}

/* ── series.axisMark ────────────────────────────────────────────────────────
 *
 * peers/, structure/: "a value outside 0-1 means the market is asking for
 * something outside the company's own history IN THE DIRECTION OF THE
 * OVERSHOOT — clamp the mark and report it." Clamping silently would draw a
 * mark sitting exactly on the end of the range, which is a different claim
 * from "off the end of it", so the overshoot comes back in `returns`. */
function axisMark(o) {
  const box = o.box, ink = o.ink || {};
  const raw = num(o.value);
  if (!box || raw === null) return { nodes: [], returns: null };
  const v = clamp01(raw);
  const vertical = o.axis === 'vertical';
  const t = o.weight || 8;
  const nodes = [];
  if (vertical) {
    const y = box.y + box.h - v * box.h;
    nodes.push(rect(box.x, y - t / 2, box.w, t, ink.attention || '#F07A5A'));
  } else {
    const x = box.x + v * box.w;
    nodes.push(rect(x - t / 2, box.y, t, box.h, ink.attention || '#F07A5A'));
  }
  return { nodes, returns: { clamped: raw !== v, raw, value: v, overshoot: raw > 1 ? raw - 1 : raw < 0 ? raw : 0 } };
}

/* ── series.historyBand ─────────────────────────────────────────────────────
 *
 * structure/: "drawn as a band on the axis, NOT as a bar from zero: it is an
 * extent, and a bar would claim a baseline the data does not have." */
function historyBand(o) {
  const box = o.box, ink = o.ink || {};
  const lo = num(o.low), hi = num(o.high);
  if (!box || lo === null || hi === null) return { nodes: [], returns: null };
  const a = clamp01(Math.min(lo, hi)), b = clamp01(Math.max(lo, hi));
  /* `tone` lets one plate lay several extents on one day scale in different
   * inks (structure/cash-conversion-cycle). Default unchanged. */
  const fill = (o.tone && ink[o.tone]) || ink.band || '#1F2634';
  const nodes = o.axis === 'vertical'
    ? [rect(box.x, box.y + box.h - b * box.h, box.w, (b - a) * box.h, fill)]
    : [rect(box.x + a * box.w, box.y, (b - a) * box.w, box.h, fill)];
  return { nodes, returns: { low: a, high: b } };
}

/* ── series.rangeMark ───────────────────────────────────────────────────────
 *
 * tables/: "the subject's position between the peer low and the peer high, 0
 * to 1… the rail under it is the plate's." So this draws the mark only — a
 * renderer that also drew the rail would double it. */
function rangeMark(o) {
  const box = o.box, ink = o.ink || {};
  const raw = num(o.value);
  if (!box || raw === null) return { nodes: [], returns: null };
  const v = clamp01(raw);
  const x = box.x + v * box.w;
  const w = o.weight || 10;
  return {
    nodes: [rect(x - w / 2, box.y, w, box.h, ink.attention || '#F07A5A')],
    returns: { clamped: raw !== v, raw, value: v },
  };
}

/* ── the line series the chart frame reserves ───────────────────────────────
 *
 * charts/: `plot-area` carries the note "code draws the data path in here
 * only", and each `point-N` publishes an `anchorX`. The x positions are READ,
 * never derived — that is what keeps the line on the ticks. */
function linePath(o) {
  const box = o.box, values = o.values || [], ink = o.ink || {};
  /* COLUMNS ARE OPTIONAL. Where a plate publishes per-point columns the x
   * positions are READ from their anchorX — that is what keeps a line on its
   * ticks. Where it publishes only a plot region (line-dense, macro-series,
   * each cell of a small-multiples grid), the points are evenly spaced across
   * that region instead. Requiring columns made nine charts in the kit draw
   * nothing at all: the renderer was right to refuse, and the caller was
   * wrong to have nothing else to offer. */
  let cols = o.columns || [];
  if (!box || !values.length) return { nodes: [], returns: null };
  if (cols.length !== values.length) {
    if (cols.length) return { nodes: [], returns: null };
    cols = values.map((_, i) => ({ anchorX: box.x + (values.length === 1 ? box.w / 2 : (i / (values.length - 1)) * box.w) }));
  }
  const e = extent(values, o);
  const y = v => box.y + box.h - ((v - e.lo) / e.span) * box.h;
  const pts = values.map((v, i) => [cols[i].anchorX, y(v)]);
  /* `tone` names the ink role for a SECOND series on the same plot (price
   * against cost). It is a role name, never a colour, so both hours hold. */
  const col = ink[o.tone || 'subject'] || ink.subject || '#7FD4E8';
  const nodes = [];
  /* Zero is drawn by the renderer when the data crosses it, because only the
   * data knows where zero falls — the rowBars convention. */
  if (o.zeroRule && e.lo < 0 && e.hi > 0) nodes.push(rect(box.x, y(0) - 1, box.w, 2, ink.axis || '#4A566A'));
  nodes.push(path('M' + pts.map(p => r1(p[0]) + ',' + r1(p[1])).join('L'),
    { stroke: col, 'stroke-width': o.weight || 6, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }));
  pts.forEach((p, i) => {
    const last = i === pts.length - 1;
    nodes.push(circle(p[0], p[1], last && o.accentLast ? 13 : 9,
      last && o.accentLast ? (ink.attention || '#F07A5A') : col));
  });
  return { nodes, returns: { lo: e.lo, hi: e.hi, points: pts.map(p => [r1(p[0]), r1(p[1])]) } };
}

/* ── series.marks ──────────────────────────────────────────────────────────
 *
 * One mark per period, each in its own published region — insider-flow draws
 * a dot per window rather than a connected line, because the periods are
 * discrete events and a line between them would claim a trend. */
function marks(o) {
  const cols = o.columns || [], values = o.values || [], ink = o.ink || {};
  if (!cols.length) return { nodes: [], returns: null };
  const vs = values.length ? values : cols.map(() => 1);
  const e = extent(vs, o);
  const nodes = cols.map((c, i) => {
    const v = num(vs[i % vs.length]); if (v === null) return null;
    const cy = c.y + c.h - ((v - e.lo) / e.span) * c.h;
    return circle(c.x + c.w / 2, cy, Math.max(4, Math.min(c.w, c.h) * 0.16),
      v < 0 ? (ink.attention || '#F07A5A') : (ink.subject || '#7FD4E8'));
  }).filter(Boolean);
  return { nodes, returns: { lo: e.lo, hi: e.hi } };
}

/* ── series.columnBars ─────────────────────────────────────────────────────
 *
 * A bar chart publishes one `bar-N` region per column, each carrying
 * `growth: "up-from-baseline"` and its own `baselineY` — the plate draws the
 * frame and the axis and leaves the bars to the data, exactly as the line
 * chart does. There was no renderer for them, so every bar chart in the kit
 * rendered as an empty grid: axes, year labels, value labels, no bars.
 *
 * The baseline is READ from the slot, never assumed to be the bottom of the
 * plot area — that is what `baselineY` is for, and a chart that crosses zero
 * needs it. */
function columnBars(o) {
  const cols = o.columns || [], values = o.values || [], ink = o.ink || {};
  if (!cols.length || cols.length !== values.length) return { nodes: [], returns: null };
  const e = extent(values, o);
  const nodes = [];
  values.forEach((v, i) => {
    const c = cols[i];
    if (!c || num(v) === null) return;
    const base = c.baselineY != null ? c.baselineY : c.y + c.h;
    const top = c.y + c.h - ((v - e.lo) / e.span) * c.h;
    const y0 = Math.min(base, top), hgt = Math.max(3, Math.abs(base - top));
    nodes.push(rect(c.x, y0, c.w, hgt,
      i === o.accent ? (ink.attention || '#F07A5A') : (ink[o.tone || 'subject'] || ink.subject || '#7FD4E8')));
  });
  return { nodes, returns: { lo: e.lo, hi: e.hi } };
}

/* ── series.splitBar ────────────────────────────────────────────────────────
 *
 * figures/where-the-cash-went: ONE bar and its parts, end to end, in the
 * order the label columns read. rowBars was named here first and it cannot
 * do this — it draws one bar per row from a shared zero, so four parts came
 * out as two overlapping bars. The parts are shares of their own sum; the
 * accent part takes attention and the others alternate two quiet inks so a
 * boundary is visible without a stroke. Segment extents come back so a
 * caller can check a label column against its part. */
function splitBar(o) {
  const box = o.box, values = (o.values || []).map(v => (num(v) === null ? 0 : Math.max(0, v))), ink = o.ink || {};
  const sum = values.reduce((a, b) => a + b, 0);
  if (!box || !sum) return { nodes: [], returns: null };
  const gap = o.gap == null ? 6 : o.gap, h = box.h * (o.thickness || 0.5), y = box.y + (box.h - h) / 2;
  const usable = box.w - gap * (values.length - 1);
  const nodes = [], parts = [];
  let x = box.x;
  values.forEach((v, i) => {
    const w = usable * v / sum;
    const fill = i === o.accent ? (ink.attention || '#F07A5A') : (i % 2 ? (ink.quiet || '#8592A6') : (ink.subject || '#7FD4E8'));
    nodes.push(rect(x, y, w, h, fill));
    parts.push([r1(x), r1(x + w)]);
    x += w + gap;
  });
  return { nodes, returns: { parts, sum } };
}

/* ── series.scatter ─────────────────────────────────────────────────────────
 *
 * One mark per company inside `plot-area`. Where the plate publishes a FIXED
 * scale on the slot (`scale: {x:[lo,hi], y:[lo,hi]}`) the marks are placed
 * on it, because the plate has drawn furniture that is only true on that
 * scale — peers/rule-of-40's diagonal IS growth + margin = 40 only there.
 * Without one, points arrive 0-1. Off-scale values are clamped and reported,
 * the axisMark convention. */
function scatter(o) {
  const box = o.box, pts = o.points || [], ink = o.ink || {};
  if (!box || !pts.length) return { nodes: [], returns: null };
  const sc = box.scale || { x: [0, 1], y: [0, 1] };
  const clamped = [];
  const nodes = [];
  pts.forEach((p, i) => {
    if (!p || num(p[0]) === null || num(p[1]) === null) return;
    const fx = (p[0] - sc.x[0]) / (sc.x[1] - sc.x[0]), fy = (p[1] - sc.y[0]) / (sc.y[1] - sc.y[0]);
    if (fx !== clamp01(fx) || fy !== clamp01(fy)) clamped.push(i);
    const acc = i === o.accent;
    nodes.push(circle(box.x + clamp01(fx) * box.w, box.y + box.h - clamp01(fy) * box.h, acc ? 22 : 14,
      acc ? (ink.attention || '#F07A5A') : (ink.subject || '#7FD4E8')));
  });
  /* The accent paints last, so a crowded cluster cannot bury the subject. */
  if (o.accent != null && nodes[o.accent]) nodes.push(nodes.splice(o.accent, 1)[0]);
  return { nodes, returns: { clamped } };
}

/* ── series.spreadFill ──────────────────────────────────────────────────────
 *
 * The area between two series on one plot, in the band ink — price against
 * cost, where the gap IS the margin. Drawn under both lines; the caller paints
 * the lines after it. */
function spreadFill(o) {
  const box = o.box, a = o.a || [], b = o.b || [], ink = o.ink || {};
  const cols = o.columns || [];
  if (!box || !a.length || a.length !== b.length || (cols.length && cols.length !== a.length)) return { nodes: [], returns: null };
  const xs = cols.length ? cols.map(c => c.anchorX) : a.map((_, i) => box.x + (i / (a.length - 1)) * box.w);
  const e = extent(a.concat(b), o);
  const y = v => box.y + box.h - ((v - e.lo) / e.span) * box.h;
  const up = a.map((v, i) => [xs[i], y(v)]), dn = b.map((v, i) => [xs[i], y(v)]).reverse();
  const d = 'M' + up.concat(dn).map(p => r1(p[0]) + ',' + r1(p[1])).join('L') + 'Z';
  return { nodes: [{ tag: 'path', attrs: { d, fill: ink.band || '#1F2634' } }], returns: { lo: e.lo, hi: e.hi } };
}

/* ── the waterfall bridge ───────────────────────────────────────────────────
 *
 * figures/: the `bridge` region plus one `step-N` column each. Each step is a
 * delta and the bar spans from the running total to the new one, which is the
 * only reading under which the steps add up to the ends. */
function bridge(o) {
  const box = o.box, cols = o.columns || [], steps = o.steps || [], ink = o.ink || {};
  if (!box || cols.length !== steps.length) return { nodes: [], returns: null };
  const open = num(o.open) || 0, close = num(o.close) || 0;
  /* THE SCALE HOLDS THE RUNNING TOTAL, not just the ends. An ARR bridge that
   * adds new and expansion before it takes churn peaks above its own close,
   * and a scale built from open and close alone drew that bar off the top of
   * the box. */
  const levels = [open, close];
  let run = open;
  steps.forEach(dv => { if (num(dv) !== null) { run += dv; levels.push(run); } });
  let hi = Math.max.apply(null, levels), lo = Math.min.apply(null, levels);
  /* FLOAT — a walk between two RATES (a margin, 15.2% to 13.4%) has no
   * meaningful zero, and on a zero-based scale its steps are a few pixels
   * tall. Floating is honest only because no bar then claims a baseline: the
   * ends are drawn as LEVELS, not as bars from zero. */
  if (o.float) { const pad = (hi - lo) * 0.14 || 1; hi += pad; lo -= pad; }
  else { hi = Math.max(hi, 0); lo = Math.min(lo, 0); }
  if (o.min != null) lo = o.min;
  if (o.max != null) hi = o.max;
  const span = (hi - lo) || 1;
  const y = v => box.y + box.h - ((v - lo) / span) * box.h;
  const nodes = [];
  const end = (c, v, fill) => {
    if (!c) return;
    if (o.float) { nodes.push(rect(c.x, y(v) - 7, c.w, 14, fill)); return; }
    const base = c.baselineY != null ? c.baselineY : y(0);
    nodes.push(rect(c.x, Math.min(base, y(v)), c.w, Math.max(3, Math.abs(base - y(v))), fill));
  };
  /* A thin connector at each running level, so a step reads as leaving from
   * where the last one ended rather than floating free. */
  const joins = [];
  end(o.openColumn, open, ink.quiet || '#8592A6');
  let prev = o.openColumn || null;
  run = open;
  steps.forEach((dv, i) => {
    const c = cols[i]; if (!c || num(dv) === null) return;
    if (prev && o.openColumn) joins.push(rect(prev.x + prev.w, y(run) - 1, c.x - (prev.x + prev.w), 2, ink.axis || '#4A566A'));
    const y0 = y(run); run += dv; const y1 = y(run);
    nodes.push(rect(c.x, Math.min(y0, y1), c.w, Math.max(3, Math.abs(y1 - y0)),
      dv < 0 ? (ink.attention || '#F07A5A') : (ink.subject || '#7FD4E8')));
    prev = c;
  });
  if (prev && o.closeColumn) joins.push(rect(prev.x + prev.w, y(run) - 1, o.closeColumn.x - (prev.x + prev.w), 2, ink.axis || '#4A566A'));
  end(o.closeColumn, close, ink.structure || '#C6D2E0');
  return { nodes: joins.concat(nodes), returns: { closes: r1(run), expected: close, reconciles: Math.abs(run - close) < 1e-6, lo, hi } };
}

const SERIES = { cycleArc, rowBars, sparkBars, axisMark, historyBand, rangeMark, linePath, columnBars, marks, bridge,
  splitBar, scatter, spreadFill, extent };

if (typeof module !== 'undefined' && module.exports) module.exports = SERIES;
if (typeof window !== 'undefined') window.SERIES = SERIES;
