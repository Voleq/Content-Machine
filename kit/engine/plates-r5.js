/* Dennis v2 — plates-r5.js
 *
 * ROUND FIVE: NEW SHAPES. Rounds three and four reused nine round-two shapes.
 * These are five shapes the library could not draw, each at 16:9 and 9:16:
 *
 *   valuationHistory   a multiple over five years on its own range + average
 *   guidanceRange      the guided range per quarter as a bar, the actual as a mark
 *   smallMultiples     4 or 6 mini lines on ONE shared scale
 *   earningsVsCash     net income against operating cash, gap filled, accruals row
 *   segmentMarginGrid  margin by segment x year, each cell banded on one scale
 *
 *   window.PLATES_R5.install(PLATES, HAND)   // AFTER PLATES_R3.install
 *
 * Every region publishes its ink and scale (DESIGN.md §5.5, rule 29), so a
 * consumer never reads the drawing to know how to fill it. Copy and sample
 * data live in copy-r5.js, keyed on type.
 */

'use strict';

(function (g) {
  function install(P0, H) {
    const { base, TR, blockH } = P0;
    const K = P0.R1_HELPERS, Q = P0.R2_HELPERS;
    if (!K || !Q) throw new Error('plates-r5.js installs after plates-r2.js: it reuses round two\u2019s furniture');
    const { role, sized, tighten, R, band, rule } = K;
    const { frame, topRoles, top, foot, key, floor, grid, row, callout, calloutRoles } = Q;

    /* rebuild-38: a MULTI-LINE role. The fitter honours maxLines only when the
     * ROLE carries maxLines and maxCharsPerLine (as every legacy plate does); a
     * maxLines on the slot alone was ignored and the text fitted to one line. */
    const ml = (r, n, w) => Object.assign({}, r, { maxLines: n,
      maxCharsPerLine: Math.max(8, Math.floor(w / (r.size * (r.font === 'Courier Prime' ? 0.5996 : 0.54)))) });
    const cols = (P, name, x0, W, n, pt, pb) => {
      const colW = W / n;
      for (let i = 1; i <= n; i++) {
        const x = x0 + colW * (i - 1);
        P.slot(name + '-' + i, Math.round(x), pt, Math.round(colW), pb - pt, { role: 'point-column', container: true, anchorX: Math.round(x + colW / 2) });
      }
    };

    /* valuation. A multiple is only cheap or dear against something, and the
     * least arguable something is its own history. Five years of the multiple
     * on one line, its five-year range as a band behind it and the average as
     * a level, so "cheap" is a position you can see rather than a word. One
     * shape, four multiples: the type carries which. */
    P0.valuationHistory = function (o) {
      const F = frame(o), n = o.points || 20, yrs = n / 4;
      const W = F.land ? F.cw - 440 : F.cw, cw2 = F.land ? 380 : F.cw, colW = W / n;
      const roles = Object.assign(topRoles(F, true), {
        rangeLabel: role(TR.caption, 24, F.land ? W : F.cw), head: role(TR.caption, 22, colW * 4 - 8),
      }, calloutRoles(F.land ? cw2 : 520, 6));
      const P = base(o, o.type || 'valuation-history', roles);
      P.meta.family = o.family || 'charts';
      P.meta.columns = n;
      top(P, F, roles);
      const pt = F.land ? 260 : 520, pb = F.land ? 740 : 1020;
      P.slot('range-label', F.L, pt - 56, F.land ? W : F.cw, blockH(roles.rangeLabel, 1), { align: 'left', role: 'rangeLabel' });
      grid(P, F.L, F.L + W, pt, pb, [0.25, 0.5, 0.75], 5010);
      floor(P, F.L, pb, F.L + W, 5014);
      P.slot('plot-area', F.L, pt, W, pb - pt, { role: 'plot-area', container: true, tone: 'subject',
        note: 'the multiple, quarterly for five years \u2014 linePath through point-N with accentLast, on the plate\u2019s min\u2013max; the last point is today' });
      P.slot('range', F.L, pt, W, pb - pt, { role: 'band', region: true, axis: 'vertical', ink: 'band', scale: 'plot-area', under: true,
        note: 'the five-year low to high \u2014 historyBand, vertical, [low, high] as fractions of the plot-area scale; drawn under the line' });
      P.slot('average', F.L, pt, W, pb - pt, { role: 'marker', region: true, axis: 'vertical', ink: 'quiet', scale: 'plot-area',
        note: 'the five-year average \u2014 axisMark, vertical, as a fraction of the plot-area scale' });
      cols(P, 'point', F.L, W, n, pt, pb);
      for (let i = 1; i <= yrs; i++)
        P.slot('head-' + i, Math.round(F.L + colW * 4 * (i - 1) + 4), pb + 18, Math.round(colW * 4 - 8), blockH(roles.head, 1), { align: 'center', role: 'head' });
      if (F.land) callout(P, roles, 'latest', F.Rr - 360, 300, 360);
      else callout(P, roles, 'latest', F.L, 1200, F.cw);
      foot(P, F, roles);
      return tighten(P);
    };

    /* guidance. What management said the quarter would be, as a range, and
     * what it was, as a mark on it. Eight quarters side by side show the
     * habit, beating the top every time or landing low in the range, which
     * one quarter's headline never does. */
    P0.guidanceRange = function (o) {
      const F = frame(o), n = o.quarters || 8;
      const W = F.land ? F.cw - 420 : F.cw, colW = W / n, cw2 = F.land ? 360 : F.cw;
      const roles = Object.assign(topRoles(F, true), {
        legend: role(TR.label, 30, F.land ? 300 : F.cw), head: role(TR.caption, 22, colW - 6),
        value: role(TR.figure, F.land ? 28 : 24, colW - 6),
      }, calloutRoles(F.land ? cw2 : 520, 6));
      const P = base(o, o.type || 'guidance-range', roles);
      P.meta.family = o.family || 'charts';
      P.meta.columns = n;
      top(P, F, roles);
      const ly = F.land ? 166 : 350;
      key(P, 'legend-1', F.L, ly, F.land ? 300 : F.cw, 'neutralData', 'legend', roles, 5101);
      key(P, 'legend-2', F.land ? F.L + 320 : F.L, F.land ? ly : ly + 46, F.land ? 300 : F.cw, 'attention', 'legend', roles, 5102);
      const pt = F.land ? 250 : 470, pb = F.land ? 700 : 1000;
      grid(P, F.L, F.L + W, pt, pb, [0.25, 0.5, 0.75], 5110);
      floor(P, F.L, pb, F.L + W, 5114);
      P.slot('plot-area', F.L, pt, W, pb - pt, { role: 'plot-area', container: true,
        note: 'guide-N and actual-N are on ONE scale, the plate\u2019s min\u2013max; pass each as fractions of it' });
      for (let i = 1; i <= n; i++) {
        const cx = F.L + colW * (i - 0.5), gw = Math.round(colW * 0.34), aw = Math.round(colW * 0.62);
        P.slot('guide-' + i, Math.round(cx - gw / 2), pt, gw, pb - pt, { role: 'band', region: true, axis: 'vertical', ink: 'quiet', scale: 'plot-area',
          note: 'the guided range for the quarter \u2014 historyBand, vertical, [low, high, "quiet"]' });
        P.slot('actual-' + i, Math.round(cx - aw / 2), pt, aw, pb - pt, { role: 'marker', region: true, axis: 'vertical', ink: 'attention', scale: 'plot-area',
          note: 'what was reported \u2014 axisMark, vertical; a value off the range is the story, so it is never clamped to the range' });
      }
      row(P, 'head', F.L, colW, n, pb + 18, 'head', blockH(roles.head, 1));
      row(P, 'value', F.L, colW, n, pb + 54, 'value', blockH(roles.value, 1));
      if (F.land) callout(P, roles, 'record', F.Rr - 360, 290, 360);
      else callout(P, roles, 'record', F.L, 1220, F.cw);
      foot(P, F, roles);
      return tighten(P);
    };

    /* small multiples. Four or six series that would be spaghetti on one plot,
     * each in its own panel, on ONE scale. The shared scale is the point: a
     * panel that rescaled to itself would make a 2% segment look like a 20%
     * one. So there is one unit line for the plate and none per panel. */
    P0.smallMultiples = function (o) {
      const F = frame(o), n = o.panels || 4;
      const layout = F.land ? (n === 4 ? [4, 1] : [3, 2]) : (n === 4 ? [2, 2] : [2, 3]);
      const [nc, nr] = layout, gx = F.land ? 60 : 48, gy = F.land ? 56 : 64;
      const top0 = F.land ? 240 : 470, bot = F.land ? F.capY - 90 : F.capY - 110;
      const pw = (F.cw - gx * (nc - 1)) / nc, ph = (bot - top0 - gy * (nr - 1)) / nr;
      const roles = Object.assign(topRoles(F, true), {
        label: role(TR.label, F.land ? 30 : 28, pw - 130), value: role(TR.figure, F.land ? 30 : 28, 120),
        end: role(TR.caption, 22, 120),
      });
      const P = base(o, o.type || 'small-multiples-' + n, roles);
      P.meta.family = o.family || 'charts';
      P.meta.panels = n;
      top(P, F, roles);
      const lh = blockH(roles.label, 1), eh = blockH(roles.end, 1);
      for (let i = 1; i <= n; i++) {
        const c = (i - 1) % nc, r = Math.floor((i - 1) / nc);
        const x = Math.round(F.L + (pw + gx) * c), y = Math.round(top0 + (ph + gy) * r), w = Math.round(pw);
        const py = y + lh + 18, pb = Math.round(y + ph - eh - 10);
        P.slot('label-' + i, x, y, w - 130, lh, { align: 'left', role: 'label' });
        P.slot('value-' + i, x + w - 120, y, 120, blockH(roles.value, 1), { align: 'right', role: 'value' });
        /* A floor per panel and no hatched ground: six hatched panels made a
         * 400 KB file for no extra reading. Zero is the renderer's, because
         * only the data knows where it falls. */
        rule(P, x, pb, x + w, 5210 + i, 2.4, 0.6);
        P.slot('panel-' + i, x, py, w, pb - py, { role: 'plot-area', container: true, tone: 'subject', scale: 'shared',
          note: 'one series \u2014 linePath, evenly spaced, on the plate\u2019s SHARED min\u2013max: never rescale a panel to itself' });
        P.slot('start-' + i, x, pb + 8, 120, eh, { align: 'left', role: 'end' });
        P.slot('end-' + i, x + w - 120, pb + 8, 120, eh, { align: 'right', role: 'end' });
      }
      foot(P, F, roles);
      return tighten(P);
    };

    /* quality of earnings. Net income against operating cash flow, year by
     * year on one scale, the gap filled, and the gap as a row of figures:
     * accruals. Profit that keeps running ahead of cash is profit the cash has
     * not confirmed, and a filled area makes the run visible. */
    P0.earningsVsCash = function (o) {
      const F = frame(o), n = o.years || 8;
      const W = F.land ? F.cw - 420 : F.cw, colW = W / n, cw2 = F.land ? 360 : F.cw;
      const roles = Object.assign(topRoles(F, true), {
        legend: role(TR.label, 30, F.land ? 380 : F.cw), head: role(TR.caption, 22, colW - 6),
        rowLabel: role(TR.caption, 24, W), accrual: role(TR.figure, F.land ? 26 : 22, colW - 6),
      }, calloutRoles(F.land ? cw2 : 520, 6));
      const P = base(o, o.type || 'earnings-vs-cash', roles);
      P.meta.family = o.family || 'charts';
      P.meta.columns = n;
      top(P, F, roles);
      const ly = F.land ? 166 : 350;
      key(P, 'legend-1', F.L, ly, F.land ? 380 : F.cw, 'up', 'legend', roles, 5301);
      key(P, 'legend-2', F.land ? F.L + 400 : F.L, F.land ? ly : ly + 46, F.land ? 380 : F.cw, 'down', 'legend', roles, 5302);
      const pt = F.land ? 240 : 460, pb = F.land ? 640 : 980;
      grid(P, F.L, F.L + W, pt, pb, [0.25, 0.5, 0.75], 5310);
      floor(P, F.L, pb, F.L + W, 5314);
      P.slot('plot-area', F.L, pt, W, pb - pt, { role: 'plot-area', container: true, tone: 'subject', tone2: 'subject2', spreadFill: true,
        note: 'two linePaths on ONE scale through point-N, the second in subject2, and spreadFill between them; the gap is accruals' });
      cols(P, 'point', F.L, W, n, pt, pb);
      row(P, 'head', F.L, colW, n, pb + 18, 'head', blockH(roles.head, 1));
      P.slot('accruals-label', F.L, pb + 64, W, blockH(roles.rowLabel, 1), { align: 'left', role: 'rowLabel' });
      row(P, 'accrual', F.L, colW, n, pb + 98, 'accrual', blockH(roles.accrual, 1));
      if (F.land) callout(P, roles, 'gap', F.Rr - 360, 280, 360);
      else callout(P, roles, 'gap', F.L, 1250, F.cw);
      foot(P, F, roles);
      return tighten(P);
    };

    /* segment margins. Segments down, years across, the margin in each cell
     * with a bar under it on ONE fixed scale. A table of margins is read row
     * by row. The bars let you read a column too: which segment carries the
     * group in a given year. */
    P0.segmentMarginGrid = function (o) {
      const F = frame(o), nr = o.rows || 5, nc = o.cols || 5, sc = o.scale || [0, 40];
      const labW = F.land ? 360 : 230, gx = F.land ? 40 : 16;
      const cx0 = F.L + labW + gx, cellW = (F.Rr - cx0) / nc;
      const topY = F.land ? 300 : 560, rowH = F.land ? 112 : 176;
      const roles = Object.assign(topRoles(F, true), {
        col: role(TR.caption, 22, cellW - 12), label: role(TR.label, F.land ? 32 : 26, labW),
        cell: role(TR.figure, F.land ? 34 : 28, cellW - 16),
      });
      const P = base(o, o.type || 'segment-margin-grid', roles);
      P.meta.family = o.family || 'tables';
      P.meta.rows = nr; P.meta.cols = nc;
      P.meta.scale = { margin: sc.slice(), why: 'fixed, so a cell\u2019s bar means the same length in every row and year' };
      top(P, F, roles);
      const ch = blockH(roles.col, 1);
      for (let c = 1; c <= nc; c++)
        P.slot('col-' + c, Math.round(cx0 + cellW * (c - 1) + 6), topY - ch - 18, Math.round(cellW - 12), ch, { align: 'center', role: 'col' });
      rule(P, F.L, topY - 8, F.Rr, 5401, 3, 0.6);
      const lh = blockH(roles.label, 1), vh = blockH(roles.cell, 1);
      for (let r = 1; r <= nr; r++) {
        const y = topY + rowH * (r - 1);
        if (r % 2 === 0) band(P, F.L - 20, y, F.cw + 40, rowH - 8, 5410 + r, 0.32);
        P.slot('label-' + r, F.L, y + Math.round((rowH - lh) / 2) - 4, labW, lh, { align: 'left', role: 'label' });
        for (let c = 1; c <= nc; c++) {
          const x = Math.round(cx0 + cellW * (c - 1));
          P.slot('cell-' + r + '-' + c, x + 8, y + 14, Math.round(cellW - 16), vh, { align: 'center', role: 'cell' });
          P.slot('bar-' + r + '-' + c, x + 14, y + rowH - 40, Math.round(cellW - 28), 14, { role: 'band', region: true, axis: 'horizontal',
            ink: 'subject', scale: sc.slice(), note: 'the cell\u2019s margin on the fixed ' + sc[0] + '\u2013' + sc[1] + ' scale \u2014 historyBand from 0; pass [0, margin/' + sc[1] + ', ink role]' });
        }
      }
      foot(P, F, roles);
      return tighten(P);
    };

    /* ── Q3 · banks and insurers ────────────────────────────────────────── */

    /* A capital ratio against the floor a regulator sets, quarter by quarter,
     * on a FIXED scale. CET1 for a bank, the solvency ratio for an insurer:
     * the number is only meaningful as headroom over the line, so the line is
     * on the plate and the headroom is the callout. */
    P0.ratioVsFloor = function (o) {
      const F = frame(o), n = o.quarters || 8, sc = o.scale || [0, 20];
      const W = F.land ? F.cw - 420 : F.cw, colW = W / n, cw2 = F.land ? 360 : F.cw;
      const roles = Object.assign(topRoles(F, true), {
        legend: role(TR.label, 28, F.land ? 380 : F.cw), head: role(TR.caption, 22, colW - 6),
        value: role(TR.figure, F.land ? 28 : 24, colW - 6),
      }, calloutRoles(F.land ? cw2 : 520, 6));
      const P = base(o, o.type || 'ratio-vs-floor', roles);
      P.meta.family = o.family || 'charts';
      P.meta.columns = n;
      P.meta.scale = { y: sc.slice(), why: 'fixed, so the floor sits at the same height every quarter and in every episode' };
      top(P, F, roles);
      const ly = F.land ? 166 : 350;
      key(P, 'legend-1', F.L, ly, F.land ? 380 : F.cw, 'attention', 'legend', roles, 5501);
      key(P, 'legend-2', F.land ? F.L + 400 : F.L, F.land ? ly : ly + 46, F.land ? 380 : F.cw, 'neutralData', 'legend', roles, 5502);
      const pt = F.land ? 250 : 470, pb = F.land ? 700 : 1000;
      grid(P, F.L, F.L + W, pt, pb, [0.25, 0.5, 0.75], 5510);
      floor(P, F.L, pb, F.L + W, 5514);
      P.slot('plot-area', F.L, pt, W, pb - pt, { role: 'plot-area', container: true, tone: 'subject', scale: { y: sc.slice() },
        note: 'the ratio as columns on the FIXED ' + sc[0] + '\u2013' + sc[1] + ' scale: pass min ' + sc[0] + ' and max ' + sc[1] });
      P.slot('floor', F.L, pt, W, pb - pt, { role: 'marker', region: true, axis: 'vertical', ink: 'attention', scale: sc.slice(),
        note: 'the regulatory minimum \u2014 axisMark, vertical, as a fraction of the fixed scale' });
      P.slot('target', F.L, pt, W, pb - pt, { role: 'band', region: true, axis: 'vertical', ink: 'band', under: true, scale: sc.slice(),
        note: 'the minimum plus buffers, or the company\u2019s own target range \u2014 historyBand, vertical, [low, high] as fractions; drawn under the columns' });
      for (let i = 1; i <= n; i++) {
        const x = F.L + colW * (i - 1), bw = Math.round(colW * 0.56);
        P.slot('bar-' + i, Math.round(x + (colW - bw) / 2), pt, bw, pb - pt, { role: 'point-column', container: true, anchorX: Math.round(x + colW / 2), baselineY: pb, growth: 'up-from-baseline' });
      }
      row(P, 'head', F.L, colW, n, pb + 18, 'head', blockH(roles.head, 1));
      row(P, 'value', F.L, colW, n, pb + 54, 'value', blockH(roles.value, 1));
      if (F.land) callout(P, roles, 'headroom', F.Rr - 360, 290, 360);
      else callout(P, roles, 'headroom', F.L, 1220, F.cw);
      foot(P, F, roles);
      return tighten(P);
    };

    /* The combined ratio: claims plus costs as one column per year, the two
     * parts stacked, against the 100% line where underwriting stops making
     * money. Stacked because the parts add up to the headline. The line is
     * drawn because above it the insurer is paying out more than it takes in. */
    P0.stackedToLine = function (o) {
      const F = frame(o), n = o.years || 6, sc = o.scale || [0, 120];
      const W = F.land ? F.cw - 420 : F.cw, colW = W / n, cw2 = F.land ? 360 : F.cw;
      const roles = Object.assign(topRoles(F, true), {
        legend: role(TR.label, 28, F.land ? 300 : F.cw), head: role(TR.caption, 22, colW - 6),
        value: role(TR.figure, F.land ? 30 : 26, colW - 6),
      }, calloutRoles(F.land ? cw2 : 520, 6));
      const P = base(o, o.type || 'stacked-to-line', roles);
      P.meta.family = o.family || 'charts';
      P.meta.columns = n;
      P.meta.scale = { y: sc.slice(), why: 'fixed, so 100% is the same height in every year and every episode' };
      top(P, F, roles);
      const ly = F.land ? 166 : 350;
      key(P, 'legend-1', F.L, ly, F.land ? 300 : F.cw, 'up', 'legend', roles, 5601);
      key(P, 'legend-2', F.land ? F.L + 320 : F.L, F.land ? ly : ly + 46, F.land ? 300 : F.cw, 'down', 'legend', roles, 5602);
      const pt = F.land ? 250 : 470, pb = F.land ? 700 : 1000;
      grid(P, F.L, F.L + W, pt, pb, [0.25, 0.5, 0.75], 5610);
      floor(P, F.L, pb, F.L + W, 5614);
      P.slot('plot-area', F.L, pt, W, pb - pt, { role: 'plot-area', container: true, scale: { y: sc.slice() },
        note: 'part-a-N and part-b-N stacked on the FIXED ' + sc[0] + '\u2013' + sc[1] + ' scale; they add up to the value-N row' });
      P.slot('line', F.L, pt, W, pb - pt, { role: 'marker', region: true, axis: 'vertical', ink: 'attention', scale: sc.slice(),
        note: 'the 100% line \u2014 axisMark, vertical; above it underwriting loses money' });
      for (let i = 1; i <= n; i++) {
        const x = F.L + colW * (i - 1), bw = Math.round(colW * 0.56), bx = Math.round(x + (colW - bw) / 2);
        P.slot('part-a-' + i, bx, pt, bw, pb - pt, { role: 'band', region: true, axis: 'vertical', ink: 'subject', scale: sc.slice(),
          note: 'the lower part (loss ratio) \u2014 historyBand, vertical, [0, a, "subject"]' });
        P.slot('part-b-' + i, bx, pt, bw, pb - pt, { role: 'band', region: true, axis: 'vertical', ink: 'subject2', scale: sc.slice(),
          note: 'the upper part (expense ratio), stacked on the lower \u2014 historyBand, vertical, [a, a + b, "subject2"]' });
      }
      row(P, 'head', F.L, colW, n, pb + 18, 'head', blockH(roles.head, 1));
      row(P, 'value', F.L, colW, n, pb + 54, 'value', blockH(roles.value, 1));
      if (F.land) callout(P, roles, 'latest', F.Rr - 360, 290, 360);
      else callout(P, roles, 'latest', F.L, 1220, F.cw);
      foot(P, F, roles);
      return tighten(P);
    };

    /* Reserve development: for each accident year, what the insurer first set
     * aside and what it thinks now, as two marks on one rail. A mark moving
     * right is money it did not know it would pay. Rails, not a triangle,
     * because a triangle is read by actuaries and this is read by a viewer. */
    P0.developmentRails = function (o) {
      const F = frame(o), n = o.rows || 6;
      const G = F.land
        ? { labW: 220, rx: F.L + 260, rw: F.cw - 260 - 220, vx: F.Rr - 190, vw: 190, top: 300, rowH: 104, railH: 30 }
        : { labW: F.cw - 200, rx: F.L, rw: F.cw, vx: F.Rr - 190, vw: 190, top: 560, rowH: 170, railH: 32 };
      const roles = Object.assign(topRoles(F, true), {
        legend: role(TR.label, 28, F.land ? 380 : F.cw), label: role(TR.label, F.land ? 32 : 32, G.labW),
        dev: role(TR.figure, F.land ? 32 : 30, G.vw), axisEnd: role(TR.caption, 22, 140),
      });
      const P = base(o, o.type || 'development-rails', roles);
      P.meta.family = o.family || 'figures';
      P.meta.rows = n;
      top(P, F, roles);
      const ly = F.land ? 166 : 350;
      key(P, 'legend-1', F.L, ly, F.land ? 380 : F.cw, 'neutralData', 'legend', roles, 5701);
      key(P, 'legend-2', F.land ? F.L + 400 : F.L, F.land ? ly : ly + 46, F.land ? 380 : F.cw, 'attention', 'legend', roles, 5702);
      for (let i = 1; i <= n; i++) {
        const y = G.top + G.rowH * (i - 1), ry = F.land ? y + 20 : y + 56;
        P.slot('label-' + i, F.L, F.land ? y + 16 : y, G.labW, blockH(roles.label, 1), { align: 'left', role: 'label' });
        P.slot('dev-' + i, G.vx, F.land ? y + 16 : y, G.vw, blockH(roles.dev, 1), { align: 'right', role: 'dev' });
        band(P, G.rx, ry, G.rw, G.railH, 5710 + i, 0.4);
        P.slot('first-' + i, G.rx, ry, G.rw, G.railH, { role: 'marker', region: true, axis: 'horizontal', ink: 'quiet', scale: 'rail',
          note: 'the first estimate for the accident year \u2014 axisMark, as a fraction of the plate\u2019s rail scale, which need not start at zero (these are marks, not bars); axis-low and axis-high print its ends' });
        P.slot('now-' + i, G.rx, ry, G.rw, G.railH, { role: 'marker', region: true, axis: 'horizontal', ink: 'attention', scale: 'rail',
          note: 'the latest estimate for the same year, on the same rail' });
        if (i < n) rule(P, F.L, y + G.rowH - 8, F.Rr, 5720 + i, 1.6, 0.22);
      }
      const ay = G.top + G.rowH * n + 4, ah = blockH(roles.axisEnd, 1);
      P.slot('axis-low', G.rx, ay, 140, ah, { align: 'left', role: 'axisEnd' });
      P.slot('axis-high', G.rx + G.rw - 140, ay, 140, ah, { align: 'right', role: 'axisEnd' });
      foot(P, F, roles);
      return tighten(P);
    };

    /* ── Q4 · macro drivers ────────────────────────────────────────────── */

    /* A driver and what it does to the company, as TWO panels on one time
     * axis, each on its OWN published scale. Never two axes on one plot: that
     * is how a viewer reads a correlation the data does not contain. The
     * sensitivity the company discloses is the callout, because the panels
     * show that the two move together and the callout says by how much. */
    P0.driverEffect = function (o) {
      const F = frame(o), n = o.points || 8;
      const W = F.land ? F.cw - 440 : F.cw, cw2 = F.land ? 380 : F.cw, colW = W / n;
      const roles = Object.assign(topRoles(F, true), {
        label: role(TR.label, F.land ? 30 : 28, W - 170), value: role(TR.figure, F.land ? 30 : 28, 160),
        head: role(TR.caption, 22, colW - 6),
      }, calloutRoles(F.land ? cw2 : 520, 7));
      const P = base(o, o.type || 'driver-effect', roles);
      P.meta.family = o.family || 'charts';
      P.meta.columns = n;
      top(P, F, roles);
      const lh = blockH(roles.label, 1);
      const t0 = F.land ? 200 : 430, gap = F.land ? 40 : 60, ph = F.land ? 210 : 300;
      [1, 2].forEach(i => {
        const y = t0 + (lh + 14 + ph + gap) * (i - 1), py = y + lh + 14;
        P.slot('label-' + i, F.L, y, W - 170, lh, { align: 'left', role: 'label' });
        P.slot('value-' + i, F.L + W - 160, y, 160, blockH(roles.value, 1), { align: 'right', role: 'value' });
        grid(P, F.L, F.L + W, py, py + ph, [0.5], 5810 + i * 4);
        rule(P, F.L, py + ph, F.L + W, 5820 + i, 2.4, 0.6);
        P.slot('panel-' + i, F.L, py, W, ph, { role: 'plot-area', container: true, tone: i === 1 ? 'quiet' : 'subject', scale: 'own',
          note: (i === 1 ? 'the DRIVER' : 'the EFFECT on the company') + ' \u2014 linePath, evenly spaced, on this panel\u2019s OWN min\u2013max (data.panelScale); never share a plot with the other panel' });
      });
      const hy = t0 + (lh + 14 + ph + gap) * 2 - gap + 16;
      for (let i = 1; i <= n; i++) P.slot('head-' + i, Math.round(F.L + colW * (i - 1)), hy, Math.round(colW), blockH(roles.head, 1), { align: 'center', role: 'head' });
      if (F.land) callout(P, roles, 'sens', F.Rr - 380, 250, 380);
      else callout(P, roles, 'sens', F.L, 1300, F.cw);
      foot(P, F, roles);
      return tighten(P);
    };

    /* ── Q7 · six plates ─────────────────────────────────────────────── */

    /* Two measures per row on two FIXED scales, each bar from its own zero:
     * the earnings surprise on the left, the share-price move that followed
     * on the right. The shape answers "does the market care" row by row. */
    P0.pairedBars = function (o) {
      const F = frame(o), n = o.rows || 8, sa = o.scaleA || [-10, 10], sb = o.scaleB || [-15, 15];
      const labW = F.land ? 200 : 170, gx = F.land ? 60 : 24;
      const bw = (F.cw - labW - gx * 2) / 2, ax = F.L + labW + gx, bx = ax + bw + gx;
      const top0 = F.land ? 300 : 560, rowH = ((F.land ? 900 : 1640) - top0) / n;
      const roles = Object.assign(topRoles(F, true), {
        col: role(TR.caption, 22, bw), label: role(TR.label, F.land ? 28 : 26, labW),
        value: role(TR.figure, F.land ? 24 : 22, 110),
      });
      const P = base(o, o.type || 'paired-bars', roles);
      P.meta.family = o.family || 'charts';
      P.meta.rows = n;
      P.meta.scale = { a: sa.slice(), b: sb.slice(), why: 'fixed and symmetric, so zero is each column\u2019s centre' };
      top(P, F, roles);
      const ch = blockH(roles.col, 1);
      P.slot('col-a', Math.round(ax), top0 - ch - 20, Math.round(bw), ch, { align: 'center', role: 'col' });
      P.slot('col-b', Math.round(bx), top0 - ch - 20, Math.round(bw), ch, { align: 'center', role: 'col' });
      [[ax, sa, 6001], [bx, sb, 6002]].forEach(([x, s, sd]) => {
        const zx = Math.round(x + bw * (0 - s[0]) / (s[1] - s[0]));
        H.pin(function () { P.inkAdd(H.line(zx, top0 - 6, zx + 1, top0 + rowH * n + 6, { stroke: P.pal.structure, width: 3, opacity: 0.7, amp: 1.4, over: 6, seed: sd })); });
      });
      const lh = blockH(roles.label, 1), vh = blockH(roles.value, 1), bh = Math.round(Math.min(30, rowH * 0.42));
      for (let i = 1; i <= n; i++) {
        const y = top0 + rowH * (i - 1), cy = y + rowH / 2;
        if (i % 2 === 0) band(P, F.L - 20, Math.round(y), F.cw + 40, Math.round(rowH), 6010 + i, 0.28);
        P.slot('label-' + i, F.L, Math.round(cy - lh / 2), labW, lh, { align: 'left', role: 'label' });
        ['a', 'b'].forEach((k, j) => {
          const x = j ? bx : ax, s = j ? sb : sa;
          P.slot(k + '-' + i, Math.round(x), Math.round(cy - bh / 2 - (F.land ? 0 : 10)), Math.round(bw), bh, { role: 'band', region: true, axis: 'horizontal', ink: 'subject', scale: s.slice(),
            note: 'a bar from zero on the fixed ' + s[0] + '\u2013' + s[1] + ' scale \u2014 historyBand, [min(zero,v), max(zero,v), ink]; up or down ink by sign' });
          P.slot(k + 'v-' + i, Math.round(j ? bx + bw - 110 : ax), Math.round(F.land ? cy + bh / 2 + 2 : cy + bh / 2 - 6), 110, vh, { align: j ? 'right' : 'left', role: 'value' });
        });
      }
      foot(P, F, roles);
      return tighten(P);
    };

    /* A list of lines, each with a mark in its own column: + added, − removed,
     * ~ reworded. Risk factors change between filings a sentence at a time,
     * and a list of the sentences is what the viewer needs to hear read. */
    P0.markedList = function (o) {
      const F = frame(o), n = o.rows || 5;
      const markW = F.land ? 90 : 80, tx = F.L + markW + 20, tw = F.Rr - tx;
      const top0 = F.land ? 250 : 480, rowH = ((F.land ? 900 : 1640) - top0) / n;
      const roles = Object.assign(topRoles(F, true), {
        mark: role(TR.figure, F.land ? 44 : 44, markW), line: ml(role(TR.label, 32, tw), F.land ? 2 : 3, tw),
        tag: role(TR.caption, 22, tw),
      });
      const P = base(o, o.type || 'marked-list', roles);
      P.meta.family = o.family || 'paper';
      P.meta.rows = n;
      top(P, F, roles);
      const th = blockH(roles.tag, 1), ll = F.land ? 2 : 3, lh = blockH(roles.line, ll);
      for (let i = 1; i <= n; i++) {
        const y = Math.round(top0 + rowH * (i - 1));
        P.slot('mark-' + i, F.L, y, markW, blockH(roles.mark, 1), { align: 'center', role: 'mark', inkBy: 'the mark: + in down (a new risk), \u2212 in up (a risk dropped), ~ in quiet' });
        P.slot('tag-' + i, tx, y, tw, th, { align: 'left', role: 'tag' });
        P.slot('line-' + i, tx, y + th + 6, tw, lh, { align: 'left', role: 'line', maxLines: ll });
        if (i < n) rule(P, F.L, Math.round(y + rowH - 12), F.Rr, 6100 + i, 1.6, 0.22);
      }
      foot(P, F, roles);
      return tighten(P);
    };

    /* One footnote, quoted, on a paper ground, with the sentence that matters
     * underlined and one figure pulled out. The plate is a reading, not a
     * chart: the host reads it aloud while it is on screen. */
    P0.footnoteSpot = function (o) {
      const F = frame(o);
      const qw = F.land ? F.cw - 460 : F.cw;
      const roles = Object.assign(topRoles(F, true), {
        ref: role(TR.caption, 22, qw), quote: ml(role(TR.label, 34, qw), F.land ? 4 : 6, qw), mark: ml(role(TR.label, 34, qw), F.land ? 3 : 4, qw),
      }, calloutRoles(F.land ? 400 : 520, 7));
      const P = base(o, o.type || 'footnote-spotlight', roles);
      P.meta.family = o.family || 'paper';
      top(P, F, roles);
      const y0 = F.land ? 230 : 460, rh = blockH(roles.ref, 1);
      band(P, F.L - 30, y0 - 24, qw + 60, F.land ? 640 : 900, 6201, 0.5);
      P.slot('ref', F.L, y0, qw, rh, { align: 'left', role: 'ref' });
      const ql = F.land ? 4 : 6, qh = blockH(roles.quote, ql);
      P.slot('quote', F.L, y0 + rh + 24, qw, qh, { align: 'left', role: 'quote', maxLines: ql });
      const my = y0 + rh + 24 + qh + 20, mln = F.land ? 3 : 4, mh = blockH(roles.mark, mln);
      P.slot('marked', F.L, my, qw, mh, { align: 'left', role: 'mark', maxLines: mln, underline: 'attention',
        note: 'the sentence that matters, in the text colour with an attention underline drawn by the renderer' });
      rule(P, F.L, my + mh + 6, F.L + qw * 0.8, 6205, 5, 0.9);
      if (F.land) callout(P, roles, 'pull', F.Rr - 400, 280, 400);
      else callout(P, roles, 'pull', F.L, my + mh + 70, F.cw);
      foot(P, F, roles);
      return tighten(P);
    };

    /* The next dates that can move the shares, on one rail across a fixed
     * window, each numbered, with the list below saying what to watch. */
    P0.eventCalendar = function (o) {
      const F = frame(o), n = o.events || 5, months = o.months || 6;
      const roles = Object.assign(topRoles(F, true), {
        month: role(TR.caption, 22, F.cw / months - 8), num: role(TR.figure, 28, 60),
        date: role(TR.label, F.land ? 28 : 28, F.land ? 190 : 200), event: role(TR.label, F.land ? 30 : 30, F.land ? 560 : F.cw - 280),
        watch: role(TR.caption, 24, F.land ? 700 : F.cw - 280),
      });
      const P = base(o, o.type || 'event-calendar', roles);
      P.meta.family = o.family || 'structure';
      P.meta.rows = n; P.meta.months = months;
      top(P, F, roles);
      const ry = F.land ? 260 : 490, rh = 40, mw = F.cw / months;
      band(P, F.L, ry, F.cw, rh, 6301, 0.45);
      for (let m = 1; m <= months; m++) {
        P.slot('month-' + m, Math.round(F.L + mw * (m - 1) + 4), ry + rh + 12, Math.round(mw - 8), blockH(roles.month, 1), { align: 'left', role: 'month' });
        if (m > 1) rule(P, Math.round(F.L + mw * (m - 1)), ry - 6, Math.round(F.L + mw * (m - 1)), 6310 + m, 2, 0.5);
      }
      for (let i = 1; i <= n; i++)
        P.slot('when-' + i, F.L, ry, F.cw, rh, { role: 'marker', region: true, axis: 'horizontal', ink: i === 1 ? 'attention' : 'subject', scale: 'window', weight: 10,
          note: 'event ' + i + ' \u2014 axisMark as a fraction of the plate\u2019s window; num-' + i + ' carries its number' });
      const l0 = ry + rh + 70, lr = ((F.land ? 900 : 1640) - l0) / n, nh = blockH(roles.num, 1), wh = blockH(roles.watch, 1);
      for (let i = 1; i <= n; i++) {
        const y = Math.round(l0 + lr * (i - 1));
        P.slot('num-' + i, F.L, y, 60, nh, { align: 'left', role: 'num' });
        P.slot('date-' + i, F.L + 70, y, F.land ? 190 : 200, blockH(roles.date, 1), { align: 'left', role: 'date' });
        const ex = F.land ? F.L + 280 : F.L + 280, ew = F.land ? 560 : F.cw - 280;
        P.slot('event-' + i, ex, y, ew, blockH(roles.event, 1), { align: 'left', role: 'event' });
        P.slot('watch-' + i, F.land ? F.L + 880 : ex, F.land ? y + 4 : y + blockH(roles.event, 1) + 6, F.land ? F.Rr - F.L - 880 : ew, wh, { align: 'left', role: 'watch' });
        if (i < n) rule(P, F.L, Math.round(y + lr - 12), F.Rr, 6320 + i, 1.4, 0.2);
      }
      foot(P, F, roles);
      return tighten(P);
    };

    /* ── Q9 · episode furniture ─────────────────────────────────────────
     * The end card and the name lower third already exist (plates.js). These
     * are the two the episodes lacked. */

    /* The chapter bumper: a full frame between chapters, the chapter number
     * large, its title, and the episode it belongs to. Held for two seconds
     * over the room tone; the number is the only thing that changes between
     * two bumpers in one episode, so the viewer reads it as a count. */
    P0.chapterBumper = function (o) {
      const land = o.w > o.h, L = land ? 160 : 90, Rr = o.w - L, cw = Rr - L;
      const roles = {
        num: role(TR.figure, land ? 300 : 320, land ? 420 : cw),
        of: role(TR.caption, land ? 30 : 30, land ? 420 : cw),
        title: ml(role(TR.label, land ? 84 : 64, land ? cw - 520 : cw), 2, land ? cw - 520 : cw),
        episode: role(TR.caption, land ? 28 : 28, cw),
      };
      const P = base(o, o.type || 'chapter-bumper', roles);
      P.meta.family = o.family || 'structure';
      P.meta.hold = { seconds: 2, why: 'long enough to read a number and five words, short enough not to be a pause' };
      const nh = blockH(roles.num, 1), th = blockH(roles.title, 2), oh = blockH(roles.of, 1), eh = blockH(roles.episode, 1);
      if (land) {
        const y = Math.round((o.h - nh) / 2) - 40;
        P.slot('num', L, y, 420, nh, { align: 'left', role: 'num' });
        P.slot('of', L, y + nh + 8, 420, oh, { align: 'left', role: 'of' });
        /* rule() is horizontal only; the upright divider is a narrow band. */
        band(P, L + 466, y + 30, 6, nh + oh - 30, 6401, 0.9);
        P.slot('title', L + 520, y + Math.round((nh - th) / 2), cw - 520, th, { align: 'left', role: 'title', maxLines: 2 });
      } else {
        const y = 560;
        P.slot('num', L, y, cw, nh, { align: 'left', role: 'num' });
        P.slot('of', L, y + nh + 8, cw, oh, { align: 'left', role: 'of' });
        rule(P, L, y + nh + oh + 40, L + cw * 0.5, 6401, 4, 0.8);
        P.slot('title', L, y + nh + oh + 80, cw, th, { align: 'left', role: 'title', maxLines: 2 });
      }
      P.slot('episode', L, o.h - (land ? 110 : 200), cw, eh, { align: 'left', role: 'episode' });
      return tighten(P);
    };

    /* The source tag: where the number on screen came from, as a small alpha
     * strip that sits over a plate or the room. Every figure on screen can be
     * traced, and this is where the trace is printed. */
    P0.sourceTag = function (o) {
      const land = o.w > o.h * 3;
      const roles = { label: role(TR.caption, land ? 22 : 26, 150), source: role(TR.caption, land ? 26 : 30, o.w - 210) };
      const P = base(Object.assign({}, o, { pal: Object.assign({}, o.pal, { ground: 'none', grain: null }) }), o.type || 'source-tag', roles);
      P.meta.family = o.family || 'overlays';
      P.meta.composite = 'alpha, over anything';
      band(P, 0, 0, o.w, o.h, 6501, 0.92);

      const lh = blockH(roles.label, 1), sh = blockH(roles.source, 1);
      P.slot('label', 30, Math.round((o.h - lh) / 2), 150, lh, { align: 'left', role: 'label' });
      P.slot('source', 190, Math.round((o.h - sh) / 2), o.w - 210, sh, { align: 'left', role: 'source' });
      return tighten(P);
    };

    /* ── Q10 · shorts plates. 9:16 only: a short is read on a phone at arm's
     * length in three seconds, so each carries ONE thing, set large in the
     * middle third, clear of the platform's UI at top and bottom (the safe
     * area is published). */
    const SAFE = { top: 260, bottom: 1560, why: 'clear of the platform\u2019s caption, buttons and progress bar' };
    const shortBase = (o, type, roles) => { const P = base(o, type, roles); P.meta.family = 'shorts'; P.meta.safe = SAFE; P.meta.format = 'short'; return P; };

    P0.shortNumber = function (o) {
      const L = 90, cw = o.w - 180;
      const roles = { label: role(TR.caption, 34, cw), num: role(TR.figure, 230, cw), context: ml(role(TR.label, 46, cw), 2, cw), source: role(TR.caption, 24, cw) };
      const P = shortBase(o, o.type || 'short-number', roles);
      const nh = blockH(roles.num, 1), lh = blockH(roles.label, 1), ch = blockH(roles.context, 2);
      const y = Math.round((SAFE.top + SAFE.bottom - nh) / 2) - 60;
      P.slot('label', L, y - lh - 30, cw, lh, { align: 'left', role: 'label' });
      P.slot('num', L, y, cw, nh, { align: 'left', role: 'num', inkBy: 'attention for a fall or a warning, subject otherwise' });
      rule(P, L, y + nh + 20, L + cw * 0.4, 6601, 5, 0.9);
      P.slot('context', L, y + nh + 50, cw, ch, { align: 'left', role: 'context', maxLines: 2 });
      P.slot('source', L, SAFE.bottom - 40, cw, blockH(roles.source, 1), { align: 'left', role: 'source' });
      return tighten(P);
    };

    P0.shortQuote = function (o) {
      const L = 90, cw = o.w - 180;
      /* The fitter sets one line per slot, so the quote is four LINE slots,
       * quote-1..4, broken on words by the copy (never mid-word). */
      const roles = { quote: role(TR.label, 64, cw), who: role(TR.caption, 30, cw), when: role(TR.caption, 26, cw) };
      const P = shortBase(o, o.type || 'short-quote', roles);
      const l1 = blockH(roles.quote, 1), qh = l1 * 4, wh = blockH(roles.who, 1);
      const y = Math.round((SAFE.top + SAFE.bottom - qh) / 2);
      band(P, L - 30, y - 10, 8, qh + 20, 6702, 0.9);
      for (let i = 1; i <= 4; i++) P.slot('quote-' + i, L, y + l1 * (i - 1), cw, l1, { align: 'left', role: 'quote', optional: i > 1 });
      rule(P, L, y + qh + 30, L + 120, 6701, 5, 0.9);
      P.slot('who', L, y + qh + 56, cw, wh, { align: 'left', role: 'who' });
      P.slot('when', L, y + qh + 56 + wh + 8, cw, blockH(roles.when, 1), { align: 'left', role: 'when' });
      return tighten(P);
    };

    P0.shortChart = function (o) {
      const L = 90, cw = o.w - 180;
      const roles = { label: role(TR.caption, 34, cw), delta: role(TR.figure, 200, cw), end: role(TR.caption, 28, 300), source: role(TR.caption, 24, cw) };
      const P = shortBase(o, o.type || 'short-chart', roles);
      const lh = blockH(roles.label, 1), dh = blockH(roles.delta, 1), eh = blockH(roles.end, 1);
      const y0 = SAFE.top + 120;
      P.slot('label', L, y0, cw, lh, { align: 'left', role: 'label' });
      P.slot('delta', L, y0 + lh + 20, cw, dh, { align: 'left', role: 'delta' });
      const pt = y0 + lh + dh + 90, pb = SAFE.bottom - 180;
      floor(P, L, pb, L + cw, 6801);
      P.slot('plot-area', L, pt, cw, pb - pt, { role: 'plot-area', container: true, tone: 'subject', note: 'ONE series, linePath with accentLast, evenly spaced; the whole chart is the line and its last point' });
      P.slot('start', L, pb + 16, 300, eh, { align: 'left', role: 'end' });
      P.slot('end', L + cw - 300, pb + 16, 300, eh, { align: 'right', role: 'end' });
      P.slot('source', L, SAFE.bottom - 40, cw, blockH(roles.source, 1), { align: 'left', role: 'source' });
      return tighten(P);
    };

    /* ── Q11 · transitions. Played ONCE, eight frames at the plate fps, alpha
     * outside the cover. The cover is full on frame 4 (meta.cutAt): the edit
     * cuts from the outgoing shot to the incoming one under it, so the wipe
     * never shows two shots at once. Drawn in the ground and band inks, the
     * room's own colours, so a wipe reads as the set and not as an effect. */
    const TFRAMES = [0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875, 1];
    const cover = (P, x, y, w, h, seed, ink) => {
      if (w <= 0 || h <= 0) return;
      P.colourAdd(H.hatch(H.polyRect(x, y, w, h), { color: ink, opacity: 1, gap: 14, width: 38, angle: -4, over: 18, seed }));
    };
    const wipeBase = (o, type) => {
      const P = base(Object.assign({}, o, { pal: Object.assign({}, o.pal, { ground: 'none', grain: null }) }), type, {});
      P.meta.family = 'overlays'; P.meta.composite = 'alpha, over the cut';
      P.meta.transition = { frames: TFRAMES.length, playback: 'once', cutAt: 4, why: 'the cover is full on frame 4; cut the shots under it there' };
      return P;
    };
    /* progress 0..1 -> the covered span: grows to full at 0.5, then leaves. */
    const span = t => (t <= 0.5 ? [0, t * 2] : [(t - 0.5) * 2, 1]);

    P0.wipeSweep = function (o) {
      const P = wipeBase(o, o.type || 'wipe-sweep'), t = o.t == null ? 0.5 : o.t, [a, b] = span(t);
      const lead = Math.round(o.w * 0.04);
      cover(P, Math.round(o.w * a) - (t > 0.5 ? 0 : lead), -20, Math.round(o.w * (b - a)) + lead, o.h + 40, 6901, P.pal.ground2 || P.pal.structure);
      if (t !== 0.5) cover(P, Math.round(o.w * (t < 0.5 ? b : a)) - 6, -20, 12, o.h + 40, 6902, P.pal.structure);
      return tighten(P);
    };
    P0.wipePage = function (o) {
      const P = wipeBase(o, o.type || 'wipe-page'), t = o.t == null ? 0.5 : o.t, [a, b] = span(t);
      /* a sheet up from the bottom edge, then on out of the top */
      const y0 = Math.round(o.h * (1 - b)), y1 = Math.round(o.h * (1 - a));
      cover(P, -20, y0, o.w + 40, y1 - y0, 6911, P.pal.ground2 || P.pal.structure);
      if (t < 0.5) cover(P, -20, y0 - 8, o.w + 40, 8, 6912, P.pal.structure);
      return tighten(P);
    };
    P0.wipeBlinds = function (o) {
      const P = wipeBase(o, o.type || 'wipe-blinds'), t = o.t == null ? 0.5 : o.t, n = o.w > o.h ? 6 : 10;
      const k = t <= 0.5 ? t * 2 : (1 - t) * 2, sh = o.h / n;
      for (let i = 0; i < n; i++) cover(P, -20, Math.round(sh * i), o.w + 40, Math.round(sh * k) + (k >= 1 ? 2 : 0), 6920 + i, P.pal.ground2 || P.pal.structure);
      return tighten(P);
    };

    /* ── Q6 · more said-vs-happened and revision trails ───────────────────
     * Same drawings, their own types, so each variant carries its own copy,
     * data, purpose and caution (the round-three pattern). */
    P0.saidHappenedAs = function (o) { const P = P0.saidHappened(o); P.meta.type = o.type; return P; };
    P0.revisionTrailAs = function (o) { const P = P0.revisionTrail(o); P.meta.type = o.type; return P; };

    /* ── Q5 · sector performance ──────────────────────────────────────── */

    /* Every sector's return over one period, ranked, as bars from a zero in
     * the middle of a FIXED symmetric scale, with the market as one line down
     * all the rows. The sector the episode is about is in attention, and the
     * rest are one ink, so the eye goes to where it ranks and not to the
     * colours. */
    P0.sectorRanking = function (o) {
      const F = frame(o), n = o.rows || 11, sc = o.scale || [-30, 30];
      const G = F.land
        ? { labW: 330, bx: F.L + 350, bw: F.cw - 350 - 170, vx: F.Rr - 150, vw: 150, top: 250, bot: 900 }
        : { labW: F.cw - 170, bx: F.L, bw: F.cw, vx: F.Rr - 150, vw: 150, top: 520, bot: 1640 };
      const rowH = (G.bot - G.top) / n;
      const roles = Object.assign(topRoles(F, true), {
        legend: role(TR.label, 26, F.land ? 420 : F.cw), label: role(TR.label, F.land ? 26 : 26, G.labW),
        value: role(TR.figure, F.land ? 26 : 26, G.vw), axisEnd: role(TR.caption, 22, 120),
      });
      const P = base(o, o.type || 'sector-ranking', roles);
      P.meta.family = o.family || 'peers';
      P.meta.rows = n;
      P.meta.scale = { x: sc.slice(), why: 'fixed and symmetric, so zero is always the centre and two periods cut together compare' };
      top(P, F, roles);
      const ly = F.land ? 166 : 350;
      key(P, 'legend-1', F.L, ly, F.land ? 420 : F.cw, 'attention', 'legend', roles, 5901);
      key(P, 'legend-2', F.land ? F.L + 440 : F.L, F.land ? ly : ly + 42, F.land ? 420 : F.cw, 'neutralData', 'legend', roles, 5902);
      const zx = Math.round(G.bx + G.bw * (0 - sc[0]) / (sc[1] - sc[0]));
      H.pin(function () {
        P.inkAdd(H.line(zx, G.top - 8, zx - 2, G.bot + 8, { stroke: P.pal.structure, width: 3, opacity: 0.7, amp: 1.6, over: 6, seed: 5905 }));
      });
      const lh = blockH(roles.label, 1), vh = blockH(roles.value, 1), bh = Math.round(Math.min(34, rowH * 0.5));
      for (let i = 1; i <= n; i++) {
        const y = G.top + rowH * (i - 1);
        if (i % 2 === 0) band(P, F.L - 20, Math.round(y), F.cw + 40, Math.round(rowH), 5910 + i, 0.28);
        const ty = F.land ? Math.round(y + (rowH - lh) / 2) : Math.round(y + 6);
        P.slot('label-' + i, F.L, ty, G.labW, lh, { align: 'left', role: 'label' });
        P.slot('value-' + i, G.vx, F.land ? Math.round(y + (rowH - vh) / 2) : Math.round(y + 6), G.vw, vh, { align: 'right', role: 'value' });
        const by = F.land ? Math.round(y + (rowH - bh) / 2) : Math.round(y + lh + 16);
        P.slot('bar-' + i, G.bx, by, G.bw, bh, { role: 'band', region: true, axis: 'horizontal', ink: 'subject', scale: sc.slice(),
          note: 'the sector\u2019s return on the fixed ' + sc[0] + '\u2013' + sc[1] + ' scale, a bar from zero \u2014 historyBand, [zero, value] as fractions, ink "attention" for the episode\u2019s sector' });
      }
      P.slot('market', G.bx, G.top, G.bw, G.bot - G.top, { role: 'marker', region: true, axis: 'horizontal', ink: 'quiet', scale: sc.slice(), weight: 5,
        note: 'the market\u2019s return for the same period, one line down all the rows \u2014 axisMark as a fraction of the fixed scale' });
      const ah = blockH(roles.axisEnd, 1);
      P.slot('axis-low', G.bx, G.bot + 12, 120, ah, { align: 'left', role: 'axisEnd' });
      P.slot('axis-high', G.bx + G.bw - 120, G.bot + 12, 120, ah, { align: 'right', role: 'axisEnd' });
      foot(P, F, roles);
      return tighten(P);
    };

    return P0;
  }

  const COPY = (typeof require === 'function') ? require('./copy-r5') : (g.COPY_R5 || { SPEC: [] });
  const LIB = COPY.SPEC.reduce(function (out, r, i) {
    const args = Object.assign({ type: r[1], family: r[0] }, r[3]);
    /* sizes: an overlay drawn at its own canvas, not the full frame (lower-third's rule). */
    const sz = r[3].sizes || { land: [1920, 1080], port: [1080, 1920] };
    const both = [
      { dir: r[0], key: r[0] + '/' + r[1] + '-16x9', author: r[2], args: Object.assign({}, args, { w: sz.land[0], h: sz.land[1] }), seed: 1501 + i * 2 },
      { dir: r[0], key: r[0] + '/' + r[1] + '-9x16', author: r[2], args: Object.assign({}, args, { w: sz.port[0], h: sz.port[1] }), seed: 1502 + i * 2 },
    ];
    /* landOnly: an author drawn for 16:9 alone (revision-trail), as in round one. */
    return out.concat(r[3].landOnly ? both.slice(0, 1) : r[3].portOnly ? both.slice(1) : both);
  }, []);

  const API = { install, LIB };
  if (typeof module !== 'undefined' && module.exports) module.exports = API;
  g.PLATES_R5 = API;
})(typeof window !== 'undefined' ? window : globalThis);
