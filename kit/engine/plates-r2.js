/* Dennis v2 — plates-r2.js
 *
 * ROUND-TWO PLATE AUTHORS: SOFTWARE AND INDUSTRIALS. Twelve plates, each at
 * 16:9 and 9:16, for the questions those two sectors are argued on and an
 * insurer never raises. The library before this round was built around one
 * sample issuer, a claims desk, and it showed: nothing could draw an ARR
 * bridge, a cohort triangle, a book-to-bill or a margin walk.
 *
 *   window.PLATES_R2.install(PLATES, HAND)   // AFTER PLATES_R1.install
 *
 *   software      figures/arr-bridge        tables/nrr-cohorts
 *                 peers/rule-of-40          charts/sbc-vs-buybacks
 *                 charts/rpo-coverage       figures/cac-payback
 *   industrials   charts/book-to-bill       figures/margin-walk
 *                 figures/end-market-exposure   charts/price-cost-spread
 *                 structure/cash-conversion-cycle   charts/capex-vs-depreciation
 *
 * THE SAME CONTRACT AS ROUND ONE, and the same machinery: `base`, `TR` and
 * `blockH` come from plates.js, and the budget helpers (`role`, `sized`,
 * `tighten`) come from plates-r1.js rather than being copied here — so a
 * published maxChars in this file is derived from its box by exactly the code
 * that derives every other one. Region slots use only shapes engine/series.js
 * draws. Two plates publish a FIXED SCALE on their region (rule-of-40,
 * rpo-coverage), because they draw furniture that is only true on that scale:
 * the Rule of 40 diagonal, the 100% ceiling. Everything else is scaled by the
 * data, as before.
 *
 * Every author is aspect-aware: 16:9 puts the callout beside the chart, 9:16
 * puts it under. Nothing is a crop of the other.
 */

'use strict';

(function (g) {
  function install(P0, H) {
    const { base, TR, blockH } = P0;
    const K = P0.R1_HELPERS;
    if (!K) throw new Error('plates-r2.js installs after plates-r1.js: it reuses round one\u2019s budget helpers rather than copying them');
    const { role, sized, tighten, R, band, rule, tick } = K;

    /* ── shared furniture ────────────────────────────────────────────────── */

    const frame = o => (o.w > o.h
      ? { land: true, L: 160, Rr: o.w - 160, cw: o.w - 320, kickY: 110, capY: o.h - 120 }
      : { land: false, L: 96, Rr: o.w - 96, cw: o.w - 192, kickY: 250, capY: 1760 });

    /* Kicker, unit and caption. At 9:16 the unit takes its own line under the
     * kicker, because a phone-width kicker shares its line with nothing. The
     * caption is one line in both aspects, as everywhere else in the kit. */
    const topRoles = (F, unit) => Object.assign({
      kicker: R.kicker(F.land && unit ? F.cw * 0.6 : F.cw), caption: R.caption(F.cw),
    }, unit ? { unit: role(TR.caption, 28, F.land ? F.cw * 0.38 : F.cw) } : {});
    /* A caption-style role that WRAPS. budget.js reads maxLines off the role,
     * not the box, so a two-line label has to be declared as one — a tall box
     * alone still publishes a one-line budget and the fill is cut. */
    const wrapCaption = (size, w, lines) => {
      const r = Object.assign({}, TR.caption, { maxLines: lines, maxCharsPerLine: 12 });
      delete r.maxChars;
      return role(r, size, w);
    };
    function top(P, F, roles) {
      if (roles.unit && F.land) {
        P.slot('kicker', F.L, F.kickY, F.cw * 0.6, blockH(roles.kicker, 1), { align: 'left', role: 'kicker' });
        P.slot('unit', F.Rr - F.cw * 0.38, F.kickY, F.cw * 0.38, blockH(roles.unit, 1), { align: 'right', role: 'unit' });
        return;
      }
      P.slot('kicker', F.L, F.kickY, F.cw, blockH(roles.kicker, 1), { align: 'left', role: 'kicker' });
      if (roles.unit) P.slot('unit', F.L, F.kickY + 50, F.cw, blockH(roles.unit, 1), { align: 'left', role: 'unit' });
    }
    const foot = (P, F, roles) =>
      P.slot('caption', F.L, F.capY, F.cw, blockH(roles.caption, 1), { align: 'left', role: 'caption' });

    /* A key: the series' own ink as a short drawn swatch, then its name. The
     * swatch is what ties a bar to a word without colouring the word. */
    /* rebuild-22: the swatch and the published `ink` come from ONE palette key,
     * so a slot cannot publish a colour its drawing does not show. INK maps the
     * drawn kit's palette names onto the data ink roles series.js takes. */
    const INK = { up: 'subject', down: 'subject2', neutralData: 'quiet', attention: 'attention', otherParty: 'axis' };
    function key(P, name, x, y, w, palKey, roleName, roles, seed) {
      const hh = blockH(roles[roleName], 1);
      tick(P, x, y + Math.round(hh / 2) + 2, 36, P.pal[palKey], seed);
      P.slot(name, x + 52, y, w - 52, hh, { align: 'left', role: roleName, ink: INK[palKey] });
    }
    /* The floor a bar is measured from is a reference, so it is pinned. */
    const floor = (P, x1, y, x2, seed) => H.pin(function () {
      P.inkAdd(H.line(x1 - 14, y, x2 + 14, y - 3, { stroke: P.pal.structure, width: 5, opacity: 0.9, amp: 2.6, over: 13, seed: seed }));
    });
    const grid = (P, x1, x2, pt, pb, fs, seed) =>
      fs.forEach(function (f, i) { rule(P, x1, Math.round(pb - (pb - pt) * f), x2, seed + i, 1.8, 0.22); });
    const row = (P, name, x0, colW, n, y, roleName, hh) => {
      for (let i = 1; i <= n; i++) P.slot(name + '-' + i, Math.round(x0 + colW * (i - 1)), y, Math.round(colW), hh, { align: 'center', role: roleName });
    };

    /* Two series per period, side by side on ONE scale: bar-N and pair-N.
     * columnBars draws each from its own list; the scale is shared by the
     * caller, because two scales on one plot is how a viewer reads a
     * relationship the data does not contain. */
    function pairs(P, x0, W, n, pt, pb, seed, note, tone2) {
      const colW = W / n, bw = Math.round(colW * 0.3), gi = Math.max(6, Math.round(colW * 0.05));
      grid(P, x0, x0 + W, pt, pb, [1 / 3, 2 / 3], seed);
      floor(P, x0, pb, x0 + W, seed + 5);
      P.slot('plot-area', x0, pt, W, pb - pt, { role: 'plot-area', container: true, tone: 'subject', tone2: tone2 || 'subject2', note: note });
      for (let i = 1; i <= n; i++) {
        const cx = x0 + colW * (i - 0.5), ax = Math.round(cx - gi / 2 - bw), bx = Math.round(cx + gi / 2);
        P.slot('bar-' + i, ax, pt, bw, pb - pt, { role: 'point-column', container: true, anchorX: ax + Math.round(bw / 2), baselineY: pb, growth: 'up-from-baseline' });
        P.slot('pair-' + i, bx, pt, bw, pb - pt, { role: 'point-column', container: true, anchorX: bx + Math.round(bw / 2), baselineY: pb, growth: 'up-from-baseline' });
      }
      return colW;
    }

    /* A callout: a small tracked label, one big figure sized from its box and
     * the characters it must hold (the bigNumber law), and a detail line. */
    const calloutRoles = (w, chars, prefer) => ({
      calloutLabel: role(TR.kicker, 24, w), big: sized(TR.big, w, chars, prefer || 150),
      calloutDetail: role(TR.detail, 28, w, 3),
    });
    function callout(P, roles, pfx, x, y, w) {
      const bh = blockH(roles.big, 1);
      P.slot(pfx + '-label', x, y, w, blockH(roles.calloutLabel, 1), { align: 'left', role: 'calloutLabel' });
      P.slot(pfx, x, y + 44, w, bh, { align: 'left', role: 'big' });
      P.slot(pfx + '-detail', x, y + 56 + bh, w, 112, { align: 'left', role: 'calloutDetail' });
    }

    /* ── the walk: ARR bridge and margin walk ────────────────────────────── */

    /* One author, two plates, because they are one shape with two different
     * honesty problems. An ARR bridge walks between two LEVELS of a stock, so
     * its ends are bars from zero and its steps are small against them — that
     * is the truth about a subscription book. A margin walk goes between two
     * RATES, and on a zero-based scale a 0.4-point step is four pixels, so it
     * FLOATS: the ends become levels, no bar claims a baseline, and the unit
     * line says the axis does not start at zero. The columns are named
     * step-open, step-1..N, step-close so series.bridge can draw all of it. */
    function walk(o, spec) {
      const F = frame(o), n = spec.cols, colW = F.cw / n;
      const roles = Object.assign(topRoles(F, true), {
        head: F.land ? role(TR.caption, 24, colW - 12) : wrapCaption(20, colW - 8, 2),
        value: role(TR.figure, F.land ? 38 : 30, colW - 8),
        calloutLabel: role(TR.kicker, 24, 400), callout: role(TR.figure, 58, 400),
      });
      const P = base(o, spec.type, roles);
      P.meta.family = o.family || 'figures';
      P.meta.columns = n;
      if (spec.float) P.meta.float = 'the scale does not start at zero; the ends are drawn as levels, never as bars';
      top(P, F, roles);
      const pt = F.land ? 240 : 440, pb = F.land ? 630 : 1220;
      P.slot('bridge', F.L, pt, F.cw, pb - pt, { role: 'bridge', region: true, float: !!spec.float, note: spec.note });
      grid(P, F.L, F.Rr, pt, pb, [0.25, 0.5, 0.75], spec.seed);
      if (spec.float) rule(P, F.L, pb, F.Rr, spec.seed + 4, 2.6, 0.5);
      else floor(P, F.L, pb, F.Rr, spec.seed + 4);
      for (let i = 1; i <= n; i++) {
        const x = F.L + colW * (i - 1), bw = Math.round(colW * 0.6), bx = Math.round(x + (colW - bw) / 2);
        const name = i === 1 ? 'step-open' : i === n ? 'step-close' : 'step-' + (i - 1);
        P.slot(name, bx, pt, bw, pb - pt, { role: 'point-column', container: true, anchorX: Math.round(x + colW / 2), baselineY: pb });
        P.slot('head-' + i, Math.round(x + 4), pb + 22, Math.round(colW - 8), F.land ? blockH(roles.head, 1) : 52, { align: 'center', role: 'head' });
        P.slot('value-' + i, Math.round(x + 4), pb + (F.land ? 62 : 84), Math.round(colW - 8), blockH(roles.value, 1), { align: 'center', role: 'value' });
      }
      const cy = F.land ? pb + 150 : pb + 200;
      spec.callouts.forEach(function (c, j) {
        const cx = F.L + j * 460;
        P.slot(c + '-label', cx, cy, 400, blockH(roles.calloutLabel, 1), { align: 'left', role: 'calloutLabel' });
        P.slot(c, cx, cy + 40, 400, blockH(roles.callout, 1), { align: 'left', role: 'callout' });
      });
      foot(P, F, roles);
      return tighten(P);
    }

    /* software/how-the-money-is-made. Opening ARR, what was won, what was
     * lost, closing ARR — and the two retention ratios DERIVED on the plate,
     * because net retention typed by a writer is a number nobody can check. */
    P0.arrBridge = function (o) {
      return walk(o, { type: 'arr-bridge', cols: 6, seed: 2101, callouts: ['nrr', 'grr'],
        note: 'series.bridge: step-open and step-close as bars from zero, step-1..4 as the moves between them, on one scale that holds the running total' });
    };

    /* industrials/the-numbers. Last year's operating margin to this year's,
     * through price, volume, mix, input costs and the rest. */
    P0.marginWalk = function (o) {
      return walk(o, { type: 'margin-walk', cols: 7, seed: 2201, float: true, callouts: ['change'],
        note: 'series.bridge with float: the ends are LEVELS, the steps float between them, and the scale is fitted to the walk \u2014 it does not start at zero' });
    };

    /* ── software ────────────────────────────────────────────────────────── */

    /* software/moat. Net revenue retention by cohort, as a triangle: each
     * year's customers on a row, their ARR as a share of what they started
     * with, one column per year since they signed. The cells a cohort has not
     * reached yet are hatched rather than left blank, because a blank cell
     * reads as a missing number and a hatched one reads as "not yet". */
    P0.nrrCohorts = function (o) {
      const F = frame(o), n = o.cohorts || 5;
      const labW = F.land ? 300 : 170, colW = (F.cw - labW) / n;
      const roles = Object.assign(topRoles(F, true), {
        head: role(TR.statement, F.land ? 46 : 52, F.cw),
        col: role(TR.caption, F.land ? 24 : 22, colW - 16),
        label: role(TR.label, F.land ? 34 : 32, labW - 20),
        cell: role(TR.figure, F.land ? 38 : 34, colW - 24),
      });
      const P = base(o, o.type || 'nrr-cohorts', roles);
      P.meta.family = o.family || 'tables';
      P.meta.rows = n;
      top(P, F, roles);
      P.slot('head', F.L, F.land ? 176 : 380, F.cw, F.land ? blockH(roles.head, 1) : blockH(roles.head, 2) + 10, { align: 'left', role: 'head' });
      const t0 = F.land ? 340 : 660, rowH = F.land ? 94 : 165;
      const cx = c => F.L + labW + colW * (c - 1);
      const X = r => F.L + labW + (n - r + 1) * colW;     // right edge of row r's last cell
      for (let c = 1; c <= n; c++) P.slot('col-' + c, Math.round(cx(c) + 8), t0 - 50, Math.round(colW - 16), blockH(roles.col, 1), { align: 'right', role: 'col' });
      rule(P, F.L, t0 - 8, F.Rr, 2301, 4, 0.8);
      for (let r = 1; r <= n; r++) {
        const y = t0 + rowH * (r - 1);
        if (r > 1) band(P, X(r), y + 8, F.Rr - X(r), rowH - 16, 2310 + r, 0.3);
        P.slot('label-' + r, F.L, Math.round(y + (rowH - blockH(roles.label, 1)) / 2), labW - 20, blockH(roles.label, 1), { align: 'left', role: 'label' });
        for (let c = 1; c <= n - r + 1; c++) {
          P.slot('cell-' + r + '-' + c, Math.round(cx(c) + 8), Math.round(y + (rowH - blockH(roles.cell, 1)) / 2), Math.round(colW - 24), blockH(roles.cell, 1), { align: 'right', role: 'cell' });
        }
        if (r < n) rule(P, F.L, y + rowH, X(r + 1), 2320 + r, 1.6, 0.26);
      }
      /* The staircase is the edge of what has been observed. Straight
       * segments, one per step: a single spline through the corners would
       * round them off into a slope, and the steps are the information. */
      H.pin(function () {
        for (let r = 1; r < n; r++) {
          const y = t0 + rowH * r;
          P.inkAdd(H.line(X(r), y, X(r + 1), y, { stroke: P.pal.structure, width: 3, opacity: 0.75, amp: 1.6, over: 4, seed: 2330 + r * 2 }));
          P.inkAdd(H.line(X(r + 1), y, X(r + 1), y + rowH, { stroke: P.pal.structure, width: 3, opacity: 0.75, amp: 1.6, over: 4, seed: 2331 + r * 2 }));
        }
      });
      foot(P, F, roles);
      return tighten(P);
    };

    /* software/sector-comps. Growth against free-cash margin with the Rule of
     * 40 drawn in. THE SCALE IS FIXED, and that is the plate: growth 0 to 50%
     * across, margin -10% to 40% up. On exactly that scale growth + margin =
     * 40 is the box's own diagonal (x/50 + (y+10)/50 = 1), so the plate can
     * draw the line as furniture and it is true for any data placed on it. */
    P0.ruleOf40 = function (o) {
      const F = frame(o), n = o.points || 8;
      const px = F.L + 90, pw = F.land ? F.cw - 90 - 420 : F.cw - 90;
      const pt = F.land ? 220 : 440, ph = F.land ? 560 : 700, pb = pt + ph;
      const cw2 = F.land ? 360 : F.cw;
      const roles = Object.assign(topRoles(F, true), {
        tick: role(TR.caption, 22, 90), axisTitle: role(TR.caption, 24, F.land ? 520 : F.cw - 90),
        lineLabel: role(TR.kicker, 24, 260), ticker: role(TR.figure, 24, 120),
        name: role(TR.kicker, 28, cw2), scoreLabel: role(TR.caption, 24, cw2),
        score: sized(TR.big, 360, 3, 150), detail: role(TR.detail, 28, cw2, 3),
      });
      const P = base(o, o.type || 'rule-of-40', roles);
      P.meta.family = o.family || 'peers';
      P.meta.points = n;
      P.meta.scale = { x: [0, 50], y: [-10, 40], why: 'growth + margin = 40 is the diagonal only on this scale' };
      top(P, F, roles);
      P.slot('y-axis', px, pt - 56, F.land ? 520 : F.cw - 90, blockH(roles.axisTitle, 1), { align: 'left', role: 'axisTitle' });
      for (let i = 1; i <= 4; i++) {
        const gx = Math.round(px + pw * i / 5), gy = Math.round(pb - ph * i / 5);
        P.inkAdd(H.line(gx, pt, gx - 3, pb, { stroke: P.pal.structure, width: 1.8, opacity: 0.2, amp: 2, over: 6, seed: 2400 + i }));
        if (i > 1) rule(P, px, gy, px + pw, 2410 + i, 1.8, 0.2);
      }
      H.pin(function () {
        P.inkAdd(H.line(px - 14, pb, px + pw + 14, pb - 3, { stroke: P.pal.structure, width: 5, opacity: 0.9, amp: 2.6, over: 13, seed: 2420 }));
        P.inkAdd(H.line(px, pt - 14, px - 3, pb + 14, { stroke: P.pal.structure, width: 5, opacity: 0.9, amp: 2.6, over: 13, seed: 2421 }));
        /* Zero margin, heavier than the grid: above it the business makes cash. */
        P.inkAdd(H.line(px, Math.round(pb - ph * 0.2), px + pw, Math.round(pb - ph * 0.2) - 2, { stroke: P.pal.structure, width: 2.8, opacity: 0.55, amp: 2, over: 8, seed: 2422 }));
        P.inkAdd(H.line(px, pt, px + pw, pb, { stroke: P.pal.structure, width: 4.6, opacity: 0.85, amp: 2.4, over: 10, seed: 2423 }));
      });
      P.slot('line-label', Math.round(px + pw * 0.1), Math.round(pt + ph * 0.1 - 52), 260, blockH(roles.lineLabel, 1), { align: 'left', role: 'lineLabel' });
      P.slot('plot-area', px, pt, pw, ph, { role: 'plot-area', container: true, scale: { x: [0, 50], y: [-10, 40] },
        note: 'series.scatter places one mark per company on this FIXED scale and clamps and reports anything off it; the subject is the accent' });
      for (let i = 1; i <= n; i++) {
        P.slot('ticker-' + i, px, pt, 120, blockH(roles.ticker, 1), { overlay: true, role: 'ticker', note: 'positioned by the renderer beside its own mark' });
      }
      const th = blockH(roles.tick, 1);
      for (let i = 1; i <= 6; i++) {
        P.slot('x-tick-' + i, i === 6 ? px + pw - 90 : Math.round(px + pw * (i - 1) / 5 - 45), pb + 16, 90, th, { align: i === 6 ? 'right' : 'center', role: 'tick' });
        P.slot('y-tick-' + i, px - 100, Math.round(pb - ph * (i - 1) / 5 - th / 2), 84, th, { align: 'right', role: 'tick' });
      }
      P.slot('x-axis', px, pb + 56, F.land ? 520 : F.cw - 90, blockH(roles.axisTitle, 1), { align: 'left', role: 'axisTitle' });
      const cx = F.land ? F.Rr - 360 : F.L, cy = F.land ? 250 : pb + 130;
      P.slot('name', cx, cy, cw2, blockH(roles.name, 1), { align: 'left', role: 'name' });
      P.slot('score-label', cx, cy + 50, cw2, blockH(roles.scoreLabel, 1), { align: 'left', role: 'scoreLabel' });
      P.slot('score', cx, cy + 90, 360, blockH(roles.score, 1), { align: 'left', role: 'score' });
      P.slot('score-detail', cx, cy + 100 + blockH(roles.score, 1), cw2, 108, { align: 'left', role: 'detail' });
      foot(P, F, roles);
      return tighten(P);
    };

    /* Years of two series side by side, then the rows of figures that carry
     * the numbers — each row named once, with its series' swatch, so a
     * column of two figures is never ambiguous. */
    function pairedYears(o, spec) {
      const F = frame(o), n = spec.cols, colW = F.cw / n;
      const roles = Object.assign(topRoles(F, true), {
        head: role(TR.caption, F.land ? 24 : 22, colW - 8),
        rowLabel: role(TR.caption, 24, F.cw - 60),
        value: role(TR.figure, F.land ? 32 : 26, colW - 8),
      });
      if (!F.land) roles.verdict = role(TR.statement, 52, F.cw);
      const P = base(o, spec.type, roles);
      P.meta.family = o.family || 'charts';
      P.meta.columns = n;
      top(P, F, roles);
      const pt = F.land ? 210 : 420, pb = F.land ? 510 : 1000;
      const sw = spec.rows.filter(r => r.swatch);
      pairs(P, F.L, F.cw, n, pt, pb, spec.seed, spec.note, sw[1] ? INK[sw[1].swatch] : 'subject2');
      const hh = blockH(roles.head, 1), vh = blockH(roles.value, 1), lh = blockH(roles.rowLabel, 1);
      row(P, 'head', F.L, colW, n, pb + 18, 'head', hh);
      let y = pb + 18 + hh + 20;
      spec.rows.forEach(function (r, j) {
        if (r.rule) { rule(P, F.L, y + 4, F.Rr, spec.seed + 20 + j, 3.2, 0.6); y += 20; }
        if (r.swatch) tick(P, F.L, y + Math.round(lh / 2) + 2, 36, P.pal[r.swatch], spec.seed + 30 + j);
        P.slot(r.label, F.L + (r.swatch ? 52 : 0), y, F.cw - 60, lh, r.swatch ? { align: 'left', role: 'rowLabel', ink: INK[r.swatch] } : { align: 'left', role: 'rowLabel' });
        y += lh + 6;
        row(P, r.name, F.L, colW, n, y, 'value', vh);
        y += vh + 16;
      });
      if (!F.land) P.slot('verdict', F.L, 1420, F.cw, blockH(roles.verdict, 2) + 10, { align: 'left', role: 'verdict' });
      foot(P, F, roles);
      return tighten(P);
    }

    /* software/capital-allocation. The buyback against the stock it is
     * buying back — spend beside stock-based compensation, year by year, and
     * the diluted count under both. The question a software buyback has to
     * answer is whether it shrinks the count or only pays the stock bill. */
    P0.sbcVsBuybacks = function (o) {
      return pairedYears(o, { type: 'sbc-vs-buybacks', cols: o.years || 6, seed: 2501,
        note: 'buybacks on bar-N, stock-based compensation on pair-N, ONE scale \u2014 columnBars draws both',
        rows: [{ label: 'row-1', name: 'spend', swatch: 'up' }, { label: 'row-2', name: 'sbc', swatch: 'down' },
          { label: 'count-label', name: 'count', rule: true }] });
    };

    /* industrials/capital-allocation. Capex beside depreciation. Under 1.0x
     * for long enough, the asset base is being run down, and the margin it
     * flatters is borrowed from the next cycle. */
    P0.capexVsDepreciation = function (o) {
      return pairedYears(o, { type: 'capex-vs-depreciation', cols: o.years || 6, seed: 3201,
        note: 'capex on bar-N, depreciation on pair-N, ONE scale \u2014 columnBars draws both',
        rows: [{ label: 'row-1', name: 'capex', swatch: 'up' }, { label: 'row-2', name: 'da', swatch: 'neutralData' },
          { label: 'ratio-label', name: 'ratio', rule: true }] });
    };

    /* software/guidance-estimates. How much of the next twelve months is
     * already contracted, quarter by quarter. The top of the plot IS 100% —
     * a fixed scale, because coverage cannot exceed it and a ceiling that
     * moved with the data would say it could. */
    P0.rpoCoverage = function (o) {
      const F = frame(o), n = o.quarters || 8;
      const W = F.land ? F.cw - 420 : F.cw, colW = W / n, cw2 = F.land ? 360 : F.cw;
      const roles = Object.assign(topRoles(F, true), {
        head: role(TR.caption, 22, colW - 6), value: role(TR.figure, F.land ? 32 : 28, colW - 6),
        ceiling: role(TR.caption, 22, W * 0.6),
      }, calloutRoles(cw2, 4));
      const P = base(o, o.type || 'rpo-coverage', roles);
      P.meta.family = o.family || 'charts';
      P.meta.columns = n;
      P.meta.scale = { y: [0, 100], why: 'the top of the plot is the 100% the plate draws' };
      top(P, F, roles);
      const pt = F.land ? 250 : 470, pb = F.land ? 700 : 1040;
      grid(P, F.L, F.L + W, pt, pb, [0.5], 2710);
      floor(P, F.L, pb, F.L + W, 2711);
      H.pin(function () {
        P.inkAdd(H.line(F.L - 14, pt, F.L + W + 14, pt - 3, { stroke: P.pal.structure, width: 3.4, opacity: 0.75, amp: 2.4, over: 10, seed: 2712 }));
      });
      P.slot('ceiling-label', F.L, pt - 40, Math.round(W * 0.6), blockH(roles.ceiling, 1), { align: 'left', role: 'ceiling' });
      P.slot('plot-area', F.L, pt, W, pb - pt, { role: 'plot-area', container: true, scale: { y: [0, 100] },
        note: 'coverage, 0 to 100% FIXED: pass min 0 and max 100, because the top of this box is the ceiling the plate draws' });
      for (let i = 1; i <= n; i++) {
        const x = F.L + colW * (i - 1), bw = Math.round(colW * 0.62);
        P.slot('bar-' + i, Math.round(x + (colW - bw) / 2), pt, bw, pb - pt, { role: 'point-column', container: true, anchorX: Math.round(x + colW / 2), baselineY: pb, growth: 'up-from-baseline' });
      }
      row(P, 'head', F.L, colW, n, pb + 18, 'head', blockH(roles.head, 1));
      row(P, 'value', F.L, colW, n, pb + 56, 'value', blockH(roles.value, 1));
      if (F.land) callout(P, roles, 'latest', F.Rr - 360, 290, 360);
      else callout(P, roles, 'latest', F.L, 1240, F.cw);
      foot(P, F, roles);
      return tighten(P);
    };

    /* software/how-the-money-is-made. What a customer costs to win and how
     * long it takes to earn it back: cumulative gross profit per customer
     * against the acquisition cost, both on ONE scale, so the payback month
     * is where the line crosses the level rather than a number to trust. The
     * inputs sit under the chart, because payback typed alone is unauditable. */
    P0.cacPayback = function (o) {
      const F = frame(o), n = 7;
      const W = F.land ? F.cw - 440 : F.cw, cw2 = F.land ? 380 : F.cw, third = W / 3;
      const roles = {
        kicker: R.kicker(F.cw), caption: R.caption(F.cw),
        legend: role(TR.label, 30, F.land ? 480 : F.cw),
        head: role(TR.caption, 22, 80), axisTitle: role(TR.caption, 24, Math.round(W * 0.6)),
        fLabel: role(TR.caption, 22, Math.round(third - 20)), fValue: role(TR.figure, F.land ? 44 : 40, Math.round(third - 20)),
        calloutLabel: role(TR.kicker, 24, cw2), big: sized(TR.big, F.land ? cw2 : 400, 2, 200), unitBig: role(TR.label, 36, cw2),
      };
      const P = base(o, o.type || 'cac-payback', roles);
      P.meta.family = o.family || 'figures';
      P.meta.columns = n;
      P.slot('kicker', F.L, F.kickY, F.cw, blockH(roles.kicker, 1), { align: 'left', role: 'kicker' });
      const ly = F.land ? 166 : 310;
      key(P, 'legend-1', F.L, ly, F.land ? 480 : F.cw, 'up', 'legend', roles, 2801);
      key(P, 'legend-2', F.land ? F.L + 520 : F.L, F.land ? ly : ly + 46, F.land ? 480 : F.cw, 'attention', 'legend', roles, 2802);
      const pt = F.land ? 240 : 450, pb = F.land ? 640 : 1030;
      grid(P, F.L, F.L + W, pt, pb, [1 / 3, 2 / 3], 2810);
      floor(P, F.L, pb, F.L + W, 2813);
      H.pin(function () {
        P.inkAdd(H.line(F.L, pt - 14, F.L - 3, pb + 14, { stroke: P.pal.structure, width: 5, opacity: 0.9, amp: 2.6, over: 13, seed: 2814 }));
      });
      P.slot('plot-area', F.L, pt, W, pb - pt, { role: 'plot-area', container: true, tone: 'subject',
        note: 'cumulative gross profit per customer, month 0 to 36 \u2014 linePath draws it through point-N' });
      P.slot('cac-line', F.L, pt, W, pb - pt, { role: 'marker', region: true, axis: 'vertical', ink: 'attention',
        note: 'the acquisition cost on the SAME scale as the line \u2014 axisMark draws it level across the plot; the crossing is the payback month' });
      for (let i = 1; i <= n; i++) {
        const ax = Math.round(F.L + W * (i - 1) / (n - 1)), half = Math.round(W / (2 * (n - 1)));
        P.slot('point-' + i, ax - half, pt, half * 2, pb - pt, { role: 'point-column', container: true, anchorX: ax });
        P.slot('head-' + i, ax - 40, pb + 16, 80, blockH(roles.head, 1), { align: 'center', role: 'head' });
      }
      P.slot('x-axis', F.L, pb + 52, Math.round(W * 0.6), blockH(roles.axisTitle, 1), { align: 'left', role: 'axisTitle' });
      const fy = F.land ? pb + 120 : pb + 130;
      ['cac', 'arr', 'gm'].forEach(function (k, j) {
        const x = Math.round(F.L + third * j);
        P.slot(k + '-label', x, fy, Math.round(third - 20), blockH(roles.fLabel, 1), { align: 'left', role: 'fLabel' });
        P.slot(k, x, fy + 34, Math.round(third - 20), blockH(roles.fValue, 1), { align: 'left', role: 'fValue' });
      });
      const c = F.land ? { x: F.Rr - 380, y: 270 } : { x: F.L, y: fy + 130 };
      P.slot('payback-label', c.x, c.y, cw2, blockH(roles.calloutLabel, 1), { align: 'left', role: 'calloutLabel' });
      P.slot('payback', c.x, c.y + 40, F.land ? cw2 : 400, blockH(roles.big, 1), { align: 'left', role: 'big' });
      P.slot('payback-unit', c.x, c.y + 48 + blockH(roles.big, 1), cw2, blockH(roles.unitBig, 1), { align: 'left', role: 'unitBig' });
      foot(P, F, roles);
      return tighten(P);
    };

    /* ── industrials ─────────────────────────────────────────────────────── */

    /* industrials/the-numbers. Orders beside revenue, quarter by quarter, and
     * the ratio under each pair. Book-to-bill as a row of figures rather than
     * a second axis: the ratio is the columns divided, and a line on its own
     * scale would invite a reading of the two that the data does not hold. */
    P0.bookToBill = function (o) {
      const F = frame(o), n = o.quarters || 8;
      const W = F.land ? F.cw - 420 : F.cw, colW = W / n, cw2 = F.land ? 360 : F.cw;
      const roles = Object.assign(topRoles(F, true), {
        legend: role(TR.label, 30, 300), head: role(TR.caption, 22, colW - 6),
        ratioLabel: role(TR.caption, 24, W), ratio: role(TR.figure, F.land ? 30 : 26, colW - 6),
      }, calloutRoles(F.land ? cw2 : 520, 5));
      const P = base(o, o.type || 'book-to-bill', roles);
      P.meta.family = o.family || 'charts';
      P.meta.columns = n;
      top(P, F, roles);
      const ly = F.land ? 166 : 350;
      key(P, 'legend-1', F.L, ly, 300, 'up', 'legend', roles, 2601);
      key(P, 'legend-2', F.L + 320, ly, 300, 'neutralData', 'legend', roles, 2602);
      const pt = F.land ? 240 : 430, pb = F.land ? 680 : 1000;
      pairs(P, F.L, W, n, pt, pb, 2610, 'orders on bar-N, revenue on pair-N, ONE scale \u2014 columnBars draws both; pair-N in quiet, as legend-2 keys it', 'quiet');
      row(P, 'head', F.L, colW, n, pb + 18, 'head', blockH(roles.head, 1));
      P.slot('ratio-label', F.L, pb + 66, W, blockH(roles.ratioLabel, 1), { align: 'left', role: 'ratioLabel' });
      row(P, 'ratio', F.L, colW, n, pb + 100, 'ratio', blockH(roles.ratio, 1));
      if (F.land) callout(P, roles, 'latest', F.Rr - 360, 280, 360);
      else callout(P, roles, 'latest', F.L, 1220, F.cw);
      foot(P, F, roles);
      return tighten(P);
    };

    /* industrials/how-the-money-is-made. Revenue by end market: each
     * market's share as a bar on one scale, and its growth as a mark on a
     * rail centred on zero. Two readings per row, because an industrial is
     * judged on both at once — how much of it is where, and which parts of it
     * are shrinking. A pie would answer the first and hide the second. */
    P0.endMarketExposure = function (o) {
      const F = frame(o), n = o.rows || 5;
      const G = F.land
        ? { labW: 320, bx: F.L + 340, bw: 520, sx: F.L + 880, sw: 120, gx: F.L + 1080, gw: 360, vx: F.Rr - 140, vw: 140, top: 300, rowH: 116 }
        : { labW: F.cw - 170, bx: F.L, bw: F.cw, sx: F.Rr - 150, sw: 150, gx: F.L, gw: F.cw - 170, vx: F.Rr - 150, vw: 150, top: 540, rowH: 224 };
      const roles = {
        kicker: R.kicker(F.cw), caption: R.caption(F.cw),
        colHead: role(TR.kicker, 22, F.land ? 520 : F.cw), axisEnd: role(TR.caption, 22, 120),
        label: role(TR.label, F.land ? 36 : 38, G.labW), share: role(TR.figure, F.land ? 36 : 38, G.sw),
        growth: role(TR.figure, F.land ? 36 : 34, G.vw),
      };
      const P = base(o, o.type || 'end-market-exposure', roles);
      P.meta.family = o.family || 'figures';
      P.meta.rows = n;
      P.slot('kicker', F.L, F.kickY, F.cw, blockH(roles.kicker, 1), { align: 'left', role: 'kicker' });
      const ch = blockH(roles.colHead, 1), ah = blockH(roles.axisEnd, 1);
      if (F.land) {
        P.slot('head-share', G.bx, 200, G.bw + G.sw + 20, ch, { align: 'left', role: 'colHead' });
        P.slot('head-growth', G.gx, 200, G.gw + G.vw + 20, ch, { align: 'left', role: 'colHead' });
      } else {
        P.slot('head-share', F.L, 420, F.cw, ch, { align: 'left', role: 'colHead' });
        P.slot('head-growth', F.L, 460, F.cw, ch, { align: 'left', role: 'colHead' });
      }
      const railY = F.land ? 34 : 146, railH = F.land ? 38 : 36;
      const lastRail = G.top + G.rowH * (n - 1) + railY;
      const ay = F.land ? 246 : lastRail + railH + 10;
      P.slot('axis-low', G.gx, ay, 120, ah, { align: 'left', role: 'axisEnd' });
      P.slot('axis-high', G.gx + G.gw - 120, ay, 120, ah, { align: 'right', role: 'axisEnd' });
      P.slot('bars', G.bx, G.top, G.bw, G.rowH * n, { role: 'bars', region: true,
        note: 'each market\u2019s share \u2014 rowBars draws one bar per band-N on ONE scale from the left edge' });
      /* The bars' zero edge, drawn only where the labels have their own column:
       * at 9:16 the labels sit at the same x as the bars and a full-height
       * rule there runs through the first letter of every market. */
      if (F.land) H.pin(function () {
        P.inkAdd(H.line(G.bx, G.top + 8, G.bx - 2, G.top + G.rowH * n - 8, { stroke: P.pal.structure, width: 3, opacity: 0.7, amp: 1.8, over: 6, seed: 2901 }));
      });
      for (let i = 1; i <= n; i++) {
        const y = G.top + G.rowH * (i - 1);
        const lh = blockH(roles.label, 1);
        P.slot('label-' + i, F.L, y + (F.land ? 30 : 0), G.labW, lh, { align: 'left', role: 'label' });
        P.slot('share-' + i, G.sx, y + (F.land ? 30 : 0), G.sw, blockH(roles.share, 1), { align: 'right', role: 'share' });
        P.slot('band-' + i, G.bx, y + (F.land ? 20 : 56), G.bw, F.land ? 76 : 70, { role: 'point-column', container: true });
        const ry = y + railY;
        band(P, G.gx, ry, G.gw, railH, 2910 + i, 0.4);
        P.inkAdd(H.outline(H.polyRect(G.gx, ry, G.gw, railH), { stroke: P.pal.structure, width: 2.4, opacity: 0.5, amp: 2.4, over: 10, seed: 2920 + i }));
        H.pin(function () {
          P.inkAdd(H.line(G.gx + G.gw / 2, ry - 10, G.gx + G.gw / 2, ry + railH + 10, { stroke: P.pal.structure, width: 3.2, opacity: 0.7, amp: 1.6, over: 6, seed: 2930 + i }));
        });
        P.slot('growth-' + i, G.gx + 18, ry, G.gw - 36, railH, { role: 'marker', region: true, axis: 'horizontal', scale: [-20, 20], clamp: true,
          note: 'growth on a rail centred on zero, -20% to +20% \u2014 axisMark draws it; pass (g + 20) / 40' });
        P.slot('growth-value-' + i, G.vx, y + (F.land ? 30 : railY - 6), G.vw, blockH(roles.growth, 1), { align: 'right', role: 'growth' });
        if (i < n) rule(P, F.L, y + G.rowH - 6, F.Rr, 2940 + i, 1.6, 0.22);
      }
      foot(P, F, roles);
      return tighten(P);
    };

    /* industrials/the-numbers. Price realised against input-cost inflation,
     * both as change on a year earlier, on ONE scale, with the spread between
     * them filled. Where the cost line is above the price line the margin is
     * being given back; the fill makes that an area you see rather than two
     * lines you compare. */
    P0.priceCostSpread = function (o) {
      const F = frame(o), n = o.quarters || 8;
      const W = F.land ? F.cw - 420 : F.cw, colW = W / n, cw2 = F.land ? 360 : F.cw;
      const roles = Object.assign(topRoles(F, true), {
        legend: role(TR.label, 30, F.land ? 380 : F.cw), head: role(TR.caption, 22, colW - 6),
      }, calloutRoles(F.land ? cw2 : 520, 6));
      const P = base(o, o.type || 'price-cost-spread', roles);
      /* rebuild-22: whether the gap is filled is a property of the plate, and
       * it is published. Two rates you compare (price against cost) fill; two
       * parts that ADD UP to the headline (price plus volume) do not, because
       * the area between them is not a quantity. */
      const fill = o.fill !== false;
      P.meta.family = o.family || 'charts';
      P.meta.columns = n;
      top(P, F, roles);
      const ly = F.land ? 166 : 350;
      key(P, 'legend-1', F.L, ly, F.land ? 380 : F.cw, 'up', 'legend', roles, 3001);
      key(P, 'legend-2', F.land ? F.L + 400 : F.L, F.land ? ly : ly + 46, F.land ? 380 : F.cw, 'down', 'legend', roles, 3002);
      const pt = F.land ? 240 : 460, pb = F.land ? 720 : 1080;
      grid(P, F.L, F.L + W, pt, pb, [0.25, 0.5, 0.75], 3010);
      floor(P, F.L, pb, F.L + W, 3014);
      P.slot('plot-area', F.L, pt, W, pb - pt, { role: 'plot-area', container: true, tone: 'subject', tone2: 'subject2', spreadFill: fill,
        note: fill ? 'two linePaths on ONE scale through point-N, the second in subject2, and spreadFill between them; zero drawn by the renderer if the data crosses it'
          : 'two linePaths on ONE scale through point-N, the second in subject2, gap NOT filled: the two are parts that add up, not rates compared; zero drawn by the renderer if the data crosses it' });
      for (let i = 1; i <= n; i++) {
        const x = F.L + colW * (i - 1);
        P.slot('point-' + i, Math.round(x), pt, Math.round(colW), pb - pt, { role: 'point-column', container: true, anchorX: Math.round(x + colW / 2) });
      }
      row(P, 'head', F.L, colW, n, pb + 18, 'head', blockH(roles.head, 1));
      if (F.land) callout(P, roles, 'spread', F.Rr - 360, 290, 360);
      else callout(P, roles, 'spread', F.L, 1200, F.cw);
      foot(P, F, roles);
      return tighten(P);
    };

    /* industrials/how-the-money-is-made. The cash conversion cycle as three
     * tracks on one day scale: the operating cycle (inventory days, then
     * receivable days), the credit suppliers give, and the gap between them
     * — the days the business finances itself. As a formula it is three
     * numbers; as tracks, the gap is visibly the part that got longer. The
     * scale is fixed at 180 days so two years cut together stay comparable. */
    P0.cashConversionCycle = function (o) {
      const F = frame(o), TK = (o.ticks || 7) - 1;
      const G = F.land
        ? { labW: 440, rx: F.L + 480, rw: F.cw - 480 - 200, fx: F.Rr - 170, fw: 170, top: 330, rowH: 170, railY: 20, railH: 56 }
        : { labW: F.cw - 200, rx: F.L, rw: F.cw, fx: F.Rr - 190, fw: 190, top: 600, rowH: 300, railY: 104, railH: 60 };
      const roles = {
        kicker: R.kicker(F.cw), caption: R.caption(F.cw),
        head: role(TR.statement, F.land ? 46 : 52, F.cw),
        label: role(TR.label, 36, G.labW), detail: role(TR.detail, 26, F.land ? G.labW : F.cw, F.land ? 2 : 1),
        days: role(TR.figure, 48, G.fw), daysUnit: role(TR.caption, 22, G.fw), tick: role(TR.caption, 22, 100),
      };
      const P = base(o, o.type || 'cash-conversion-cycle', roles);
      /* rebuild-22: the band slots publish the plate's REAL scale. Eight plates
       * on this shape are not on days; they said so only in the note. */
      const sc = o.bandScale || [0, 180];
      P.meta.family = o.family || 'structure';
      P.meta.scale = o.scale || { days: [0, 180], why: 'fixed, so two years cut together are on one scale' };
      P.slot('kicker', F.L, F.kickY, F.cw, blockH(roles.kicker, 1), { align: 'left', role: 'kicker' });
      P.slot('head', F.L, F.land ? 170 : 360, F.cw, F.land ? blockH(roles.head, 1) : blockH(roles.head, 2) + 10, { align: 'left', role: 'head' });
      P.slot('days-unit', G.fx, G.top - 44, G.fw, blockH(roles.daysUnit, 1), { align: 'right', role: 'daysUnit' });
      const bands = o.bands || [['band-inventory', 'band-receivables'], ['band-payables'], ['band-gap']];
      const railTop = G.top + G.railY, railBot = G.top + G.rowH * 2 + G.railY + G.railH;
      /* The day grid. At 16:9 the labels have their own column and one line
       * can run through all three tracks; at 9:16 the labels sit BETWEEN the
       * tracks, so the grid is drawn inside each track only, or it would cross
       * every label on the plate. */
      H.pin(function () {
        const spans = F.land ? [[railTop - 12, railBot + 12]]
          : [0, 1, 2].map(i => [G.top + G.rowH * i + G.railY - 10, G.top + G.rowH * i + G.railY + G.railH + 10]);
        spans.forEach(function (sp, si) {
          for (let j = 0; j <= TK; j++) {
            const x = Math.round(G.rx + G.rw * j / TK);
            P.inkAdd(H.line(x, sp[0], x - 2, sp[1], { stroke: P.pal.structure, width: j === 0 ? 3.2 : 1.8, opacity: j === 0 ? 0.7 : 0.24, amp: 1.6, over: 4, seed: 3101 + j + si * 7 }));
          }
        });
      });
      for (let i = 1; i <= 3; i++) {
        const y = G.top + G.rowH * (i - 1), ry = y + G.railY;
        P.slot('label-' + i, F.L, y + (F.land ? 14 : 0), G.labW, blockH(roles.label, 1), { align: 'left', role: 'label' });
        P.slot('detail-' + i, F.L, y + (F.land ? 62 : 54), F.land ? G.labW : F.cw, F.land ? 66 : 34, { align: 'left', role: 'detail' });
        P.slot('days-' + i, G.fx, y + (F.land ? 18 : 0), G.fw, blockH(roles.days, 1), { align: 'right', role: 'days' });
        P.inkAdd(H.outline(H.polyRect(G.rx, ry, G.rw, G.railH), { stroke: P.pal.structure, width: 2.4, opacity: 0.45, amp: 2.2, over: 8, seed: 3110 + i }));
        bands[i - 1].forEach(function (b) {
          P.slot(b, G.rx, ry, G.rw, G.railH, { role: 'band', region: true, axis: 'horizontal', scale: sc.slice(),
            note: o.bandNote || 'an extent in days on the fixed 0-180 scale \u2014 historyBand draws it; pass [start/180, end/180, ink role]' });
        });
      }
      const th = blockH(roles.tick, 1);
      for (let j = 1; j <= TK + 1; j++) {
        const ex = j === 1 ? G.rx : j === TK + 1 ? G.rx + G.rw - 100 : Math.round(G.rx + G.rw * (j - 1) / TK - 50);
        P.slot('tick-' + j, ex, railBot + 14, 100, th, { align: j === 1 ? 'left' : j === TK + 1 ? 'right' : 'center', role: 'tick' });
      }
      foot(P, F, roles);
      return tighten(P);
    };

    /* GENERIC FORMS, for round three. A sector plate is a type, a family and
     * copy; where its shape is one round two already draws, it names that
     * shape instead of redrawing it. */
    P0.walkN = function (o) {
      return walk(o, { type: o.type, cols: o.cols, seed: 2150, float: !!o.float, callouts: o.callouts || ['change'],
        note: o.float ? 'series.bridge with float: the ends are LEVELS, the steps float between them; the scale does not start at zero'
          : 'series.bridge: step-open and step-close as bars from zero, the steps between them, on one scale that holds the running total' });
    };
    P0.pairedN = function (o) {
      return pairedYears(o, { type: o.type, cols: o.years || 6, seed: 2550, rows: o.rows,
        note: 'first series on bar-N, second on pair-N, ONE scale \u2014 columnBars draws both' });
    };

    /* Round five draws new shapes from the same furniture instead of copying it. */
    P0.R2_HELPERS = { frame, topRoles, top, foot, key, floor, grid, row, pairs, callout, calloutRoles, INK };
    return P0;
  }

  /* THE CATALOGUE. Each plate twice, 16:9 and 9:16, the same author drawing
   * both from the aspect it is handed. One asset id per plate — emit.js keys
   * assets on the name without its aspect, so the pair is one asset with two
   * slot tables, which is how the drawn library's twins already work. */
  const LIB = [
    ['figures', 'arr-bridge', 'arrBridge', {}],
    ['tables', 'nrr-cohorts', 'nrrCohorts', { cohorts: 5 }],
    ['peers', 'rule-of-40', 'ruleOf40', { points: 8 }],
    ['charts', 'sbc-vs-buybacks', 'sbcVsBuybacks', { years: 6 }],
    ['charts', 'rpo-coverage', 'rpoCoverage', { quarters: 8 }],
    ['figures', 'cac-payback', 'cacPayback', {}],
    ['charts', 'book-to-bill', 'bookToBill', { quarters: 8 }],
    ['figures', 'margin-walk', 'marginWalk', {}],
    ['figures', 'end-market-exposure', 'endMarketExposure', { rows: 5 }],
    ['charts', 'price-cost-spread', 'priceCostSpread', { quarters: 8 }],
    ['structure', 'cash-conversion-cycle', 'cashConversionCycle', {}],
    ['charts', 'capex-vs-depreciation', 'capexVsDepreciation', { years: 6 }],
  ].reduce(function (out, r, i) {
    return out.concat([
      { dir: r[0], key: r[0] + '/' + r[1] + '-16x9', author: r[2], args: Object.assign({ w: 1920, h: 1080 }, r[3]), seed: 901 + i * 2 },
      { dir: r[0], key: r[0] + '/' + r[1] + '-9x16', author: r[2], args: Object.assign({ w: 1080, h: 1920 }, r[3]), seed: 902 + i * 2 },
    ]);
  }, []);

  const SECTOR = {
    software: ['arr-bridge', 'nrr-cohorts', 'rule-of-40', 'sbc-vs-buybacks', 'rpo-coverage', 'cac-payback'],
    industrials: ['book-to-bill', 'margin-walk', 'end-market-exposure', 'price-cost-spread', 'cash-conversion-cycle', 'capex-vs-depreciation'],
  };

  const API = { install: install, LIB: LIB, SECTOR: SECTOR };
  if (typeof module !== 'undefined' && module.exports) module.exports = API;
  g.PLATES_R2 = API;
})(typeof window !== 'undefined' ? window : globalThis);
