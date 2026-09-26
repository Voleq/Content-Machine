#!/usr/bin/env node
/* Dennis v2 — export.js
 *
 * THE FILES. Every frame of every plate, strip and room, as its own SVG, with
 * a work list.
 *
 *   node engine/export.js              # out/: the KIT — blank plates, every frame
 *   node engine/export.js --index      # out/index.json only, no files
 *   node engine/export.js --sample     # out-review/: the REVIEW set, sample content burned in
 *
 * THE DEFAULT IS BLANK (rebuild-17). The previous export burned the sample
 * content into 390 of 536 files, so the intraday chart read "MERIDIAN · 14
 * FEBRUARY" and ANSWERS.md told the reader to rasterise it — which would have
 * put a fictional company under every real figure. A plate is an empty form;
 * the kit ships empty forms. The review set only exists under --sample and goes
 * to a DIFFERENT DIRECTORY, so nobody can rasterise it by accident.
 *
 * ONE PATH. Files are produced by emit.build(), the same call that writes the
 * manifests, so a frame hash in <family>/manifest.json is the hash of the file
 * written here. The previous export had its own host and frame logic, which is
 * how it drew the host into the room's 320x180 box and wrote one frame for
 * strips the manifest declared as three.
 *
 * SVG is the master. Rasterising stays with the ingest; out/index.json is the
 * work list, with `delivered` as the pixel size.
 */

'use strict';
const fs = require('fs');
const path = require('path');
const E = require('./emit');
const CONTENT = require('./content');
const ROOT = path.resolve(__dirname, '..');
const SERIES = require('./series');
const tokens = JSON.parse(fs.readFileSync(path.join(ROOT, 'design-tokens.json'), 'utf8'));

/* ── the review layers (--sample only) ──────────────────────────────────── */

/* Type is outlined into the file, never a <text> node (rule 10): each string is
 * a filled box at its advance width with the string kept in data-text — the
 * seam a real glyph outliner drops into. */
function typeLayer(m, content, hour) {
  const ink = tokens.hours[hour].ink, roles = m.typeRoles || {};
  const esc = s => String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
  const parts = Object.keys(content.text).map(name => {
    const sl = (m.slots || {})[name]; if (!sl) return '';
    const R = roles[sl.role] || {};
    const size = CONTENT.fittedSize ? CONTENT.fittedSize(sl, roles, content.text[name]) : (R.size || 30);
    const adv = Math.min(sl.w, size * 0.54 * String(content.text[name]).length);
    const x = sl.align === 'center' ? sl.x + (sl.w - adv) / 2 : sl.align === 'right' ? sl.x + sl.w - adv : sl.x;
    return '<rect x="' + Math.round(x) + '" y="' + Math.round(sl.y) + '" width="' + Math.round(adv) + '" height="' + Math.round(size)
      + '" fill="' + (ink[R.colour] || ink.structure) + '" data-slot="' + name + '" data-text="' + esc(content.text[name]) + '"/>';
  });
  return parts.length ? '<g data-layer="type">' + parts.join('') + '</g>' : '';
}

/* The data layer, from engine/series.js, reading only the geometry the plate published. */
function dataLayer(m, data, hour) {
  const ink = tokens.hours[hour].ink, SL = m.slots || {};
  if (!data || !Object.keys(data).length) return '';
  const pick = re => Object.keys(SL).filter(k => re.test(k))
    .sort((a, b) => +a.split('-').pop() - +b.split('-').pop()).map(k => SL[k]);
  const outs = [];
  /* rebuild-23: a band that publishes `under: true` (a range behind a line)
   * paints before the series, or it hides the line it frames. */
  Object.keys(data.bands || {}).forEach(k => { const b = SL[k], v = data.bands[k]; if (b && v && b.under) outs.push(SERIES.historyBand({ box: b, low: v[0], high: v[1], tone: v[2], axis: b.axis || 'horizontal', ink })); });
  /* rebuild-22: fill and second-series ink default to what the plate PUBLISHES
   * on its plot-area, so real data drawn without them matches the legend. */
  const PA = SL['plot-area'] || {};
  data = Object.assign({}, data, { spread: data.spread != null ? data.spread : PA.spreadFill === true, tone2: data.tone2 || PA.tone2 || 'subject2' });
  const barCols = pick(/^bar-\d+$/), pairCols = pick(/^pair-\d+$/), pointCols = pick(/^point-\d+$/);
  /* A second series shares the first one's scale — two scales on one plot is
   * how a viewer reads a correlation the data does not contain. */
  if (data.spread && data.series && data.series2 && SL['plot-area'] && SERIES.spreadFill) outs.push(SERIES.spreadFill({ box: SL['plot-area'], columns: pointCols, a: data.series, b: data.series2, min: data.min, max: data.max, ink }));
  if (data.series && barCols.length && SERIES.columnBars) outs.push(SERIES.columnBars({ columns: barCols, values: data.series.slice(0, barCols.length), min: data.min, max: data.max, accent: data.accent, ink }));
  else if (data.series && SL['plot-area']) outs.push(SERIES.linePath({ box: SL['plot-area'], columns: pointCols, values: data.series, min: data.min, max: data.max, accentLast: data.accentLast, zeroRule: data.zeroRule, zero: data.zero, ink }));
  if (data.series2 && pairCols.length) outs.push(SERIES.columnBars({ columns: pairCols, values: data.series2.slice(0, pairCols.length), min: data.min, max: data.max, tone: data.tone2 || 'subject2', ink }));
  else if (data.series2 && SL['plot-area']) outs.push(SERIES.linePath({ box: SL['plot-area'], columns: pointCols, values: data.series2, min: data.min, max: data.max, tone: data.tone2 || 'subject2', zeroRule: data.zeroRule, zero: data.zero, ink }));
  if (data.split && SL.bars && SERIES.splitBar) outs.push(SERIES.splitBar({ box: SL.bars, values: data.split, accent: data.accent, ink }));
  else if (data.bars && SL.bars) outs.push(SERIES.rowBars({ box: SL.bars, rows: pick(/^band-\d+$/), values: data.bars, accent: data.accent != null ? data.accent : 0, min: data.min, max: data.max, ink }));
  if (data.steps && SL.bridge) outs.push(SERIES.bridge({ box: SL.bridge, columns: pick(/^step-\d+$/), steps: data.steps, open: data.open, close: data.close,
    openColumn: SL['step-open'], closeColumn: SL['step-close'], float: data.float, ink }));
  if (data.points && SL['plot-area'] && SERIES.scatter) outs.push(SERIES.scatter({ box: SL['plot-area'], points: data.points, accent: data.accent, ink }));
  /* Named per-slot marks and extents: a plate with one rail per row publishes
   * marker-N / band-N regions, and the data names which value goes in which. */
  Object.keys(data.marks || {}).forEach(k => { const b = SL[k]; if (b) outs.push(SERIES.axisMark({ box: b, value: data.marks[k], axis: b.axis || 'horizontal', tone: b.ink, ink })); });
  /* rebuild-30: the attention underline a slot publishes (footnote-spotlight). */
  Object.keys(SL).forEach(k => { const b = SL[k]; if (b && b.underline) outs.push({ nodes: [{ tag: 'rect', attrs: { x: Math.round(b.x), y: Math.round(b.y + b.h + 2), width: Math.round(b.w * 0.8), height: 5, fill: ink[b.underline] } }] }); });
  /* rebuild-29: said-happened's diverge-N. The slot note always promised "the
   * renderer draws the tie in attention" and no renderer did. A tie is one
   * attention bar down the middle of the named column's diverge box. */
  (data.diverge || []).forEach(i => { const b = SL['diverge-' + i]; if (b) outs.push({ nodes: [{ tag: 'rect', attrs: { x: Math.round(b.x + b.w / 2 - 4), y: Math.round(b.y), width: 8, height: Math.round(b.h), fill: ink.attention } }] }); });
  /* rebuild-23: small multiples. One series per published panel-N, all on the
   * plate's ONE min-max, evenly spaced across the panel. */
  Object.keys(data.panels || {}).forEach(k => { const b = SL[k], ps = (data.panelScale || {})[k] || [data.min, data.max]; if (b) outs.push(SERIES.linePath({ box: b, values: data.panels[k], min: ps[0], max: ps[1], zeroRule: data.zeroRule, accentLast: data.accentLast, tone: b.tone, ink })); });
  Object.keys(data.bands || {}).forEach(k => { const b = SL[k], v = data.bands[k]; if (b && v && !b.under) outs.push(SERIES.historyBand({ box: b, low: v[0], high: v[1], tone: v[2], axis: b.axis || 'horizontal', ink })); });
  if (data.cycle && SL.path) outs.push(SERIES.cycleArc({ box: SL.path, values: data.cycle, troughBox: SL.trough, ink }));
  if (data.spark) pick(/^spark-\d+$/).forEach(box => outs.push(SERIES.sparkBars({ box, values: data.spark, ink })));
  if (data.low !== undefined && SL.band) outs.push(SERIES.historyBand({ box: SL.band, low: data.low, high: data.high, axis: SL.band.axis, ink }));
  if (data.mark !== undefined && SL.marker) outs.push(SERIES.axisMark({ box: SL.marker, value: data.mark, axis: SL.marker.axis, ink }));
  const nodes = outs.filter(Boolean).reduce((a, o) => a.concat(o.nodes || []), []);
  if (!nodes.length) return '';
  return '<g data-layer="data">' + nodes.map(n => '<' + n.tag + ' ' + Object.keys(n.attrs).map(k => k + '="' + n.attrs[k] + '"').join(' ') + '/>').join('') + '</g>';
}

function exportAll(opts) {
  const OUT = path.join(ROOT, opts.sample ? 'out-review' : 'out');
  let written = 0;
  const decorate = opts.sample ? function (it, m, hour) {
    const c = CONTENT.contentFor(it.key, m);
    return dataLayer(m, c.data, hour) + typeLayer(m, c, hour);
  } : null;
  const b = E.build({
    decorate,
    onFile: function (entry, svg) {
      if (opts.indexOnly) return;
      fs.mkdirSync(path.dirname(path.join(OUT, entry.file)), { recursive: true });
      fs.writeFileSync(path.join(OUT, entry.file), svg);
      written++;
    },
  });
  const frames = b.index.filter(e => e.frame).length;
  fs.mkdirSync(OUT, { recursive: true });
  fs.writeFileSync(path.join(OUT, 'index.json'), JSON.stringify({
    _spec: 'Every exported file, one entry per file: base files (frame null) and every frame (_f01.._fNN). SVG is the master; `delivered` is the raster size a platform asks for.',
    _blank: opts.sample
      ? 'REVIEW SET — sample content is burned in. Do NOT rasterise this as the kit.'
      : 'THE KIT — blank plates. No sample content is burned into any file.',
    _generated: 'engine/export.js via engine/emit.js build()',
    count: b.index.length, frames, index: b.index,
  }, null, 1));
  return { written, index: b.index, frames, OUT };
}

if (require.main === module) {
  const argv = process.argv.slice(2);
  const r = exportAll({ indexOnly: argv.includes('--index'), sample: argv.includes('--sample') });
  process.stdout.write(r.index.length + ' files indexed (' + r.frames + ' animation frames) · ' + r.written + ' written to ' + path.relative(ROOT, r.OUT) + '/\n');
}

/* dataLayer is exported so a review surface draws the SAME data layer the
 * --sample files carry, rather than a second hand-coded one that can drift. */
module.exports = { exportAll, dataLayer, typeLayer };
