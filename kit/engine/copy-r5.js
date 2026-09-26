/* Dennis v2 — copy-r5.js
 *
 * Round five's catalogue rows, copy, sample data and roles, as ONE source (the
 * sector-copy.js pattern). plates-r5.js reads SPEC, content.js reads text()
 * and data(), and roles.fragment.json is generated from roles(). Every figure
 * that follows from others is DERIVED here: a range and an average come from
 * the series, a record from the ranges and the actuals, an accrual from the
 * two lines. So a plate cannot disagree with itself.
 *
 * Issuers are the kit's fictional ones: Harrow (pumps and valves), Tessera
 * (software), Larkin (apparel retail), Brightline (streaming).
 */

'use strict';

(function (g) {
  const MINUS = '\u2212';
  const Q8 = ['Q1 24', 'Q2 24', 'Q3 24', 'Q4 24', 'Q1 25', 'Q2 25', 'Q3 25', 'Q4 25'];
  const num = (v, d) => { const s = Math.abs(v).toFixed(d || 0); const p = s.split('.'); p[0] = p[0].replace(/\B(?=(\d{3})+(?!\d))/g, ','); return p.join('.'); };
  const fmt = (v, u, d, signed) => {
    const sg = signed ? (v > 0 ? '+' : v < 0 ? MINUS : '') : (v < 0 ? MINUS : '');
    const s = num(v, d);
    return u === '$m' ? sg + '$' + s + 'm' : u === 'x' ? sg + s + '\u00d7' : sg + s + (u || '');
  };
  const each = (o, p, l) => { l.forEach((v, i) => { o[p + '-' + (i + 1)] = v; }); return o; };
  const frac = (v, lo, hi) => +((v - lo) / (hi - lo)).toFixed(4);

  const B = {
    valuationHistory(e) {
      const s = e.series, lo = Math.min.apply(null, s), hi = Math.max.apply(null, s);
      const avg = s.reduce((a, b) => a + b, 0) / s.length, last = s[s.length - 1];
      const f = v => fmt(v, e.u, 1);
      const t = { kicker: e.kicker, unit: e.unit, caption: e.caption,
        'range-label': 'FIVE-YEAR RANGE ' + f(lo) + ' \u2013 ' + f(hi) + ' \u00b7 AVERAGE ' + f(avg),
        'latest-label': 'TODAY', latest: f(last), 'latest-detail': e.detail };
      each(t, 'head', e.heads || ['FY21', 'FY22', 'FY23', 'FY24', 'FY25']);
      return { text: t, data: { series: s, min: e.min, max: e.max, accentLast: true,
        bands: { range: [frac(lo, e.min, e.max), frac(hi, e.min, e.max), 'band'] }, marks: { average: frac(avg, e.min, e.max) } } };
    },
    guidanceRange(e) {
      const inOrAbove = e.actual.filter((a, i) => a >= e.guide[i][0]).length;
      const t = { kicker: e.kicker, unit: e.unit, 'legend-1': 'Guided range', 'legend-2': 'Reported', caption: e.caption,
        'record-label': 'AT OR ABOVE RANGE', record: inOrAbove + ' of ' + e.actual.length, 'record-detail': e.detail };
      each(t, 'head', e.heads || Q8);
      each(t, 'value', e.actual.map(v => fmt(v, e.u, 0)));
      const bands = {}, marks = {};
      e.guide.forEach((gr, i) => { bands['guide-' + (i + 1)] = [frac(gr[0], e.min, e.max), frac(gr[1], e.min, e.max), 'quiet']; });
      e.actual.forEach((a, i) => { marks['actual-' + (i + 1)] = frac(a, e.min, e.max); });
      return { text: t, data: { bands, marks, series: null } };
    },
    smallMultiples(e) {
      const t = { kicker: e.kicker, unit: e.unit, caption: e.caption };
      const panels = {};
      e.rows.forEach((r, i) => {
        t['label-' + (i + 1)] = r[0]; t['value-' + (i + 1)] = fmt(r[1][r[1].length - 1], e.u, 0, true);
        t['start-' + (i + 1)] = e.start; t['end-' + (i + 1)] = e.end;
        panels['panel-' + (i + 1)] = r[1];
      });
      return { text: t, data: { series: null, panels, min: e.min, max: e.max, zeroRule: e.min < 0, accentLast: true } };
    },
    earningsVsCash(e) {
      const acc = e.ni.map((v, i) => v - e.ocf[i]), cum = acc.reduce((a, b) => a + b, 0);
      const t = { kicker: e.kicker, unit: e.unit, 'legend-1': 'Net income', 'legend-2': 'Operating cash flow',
        'accruals-label': 'ACCRUALS \u00b7 NET INCOME LESS OPERATING CASH FLOW', caption: e.caption,
        'gap-label': 'GAP, ' + e.heads.length + ' YEARS', gap: fmt(cum, '$m', 0, true), 'gap-detail': e.detail };
      each(t, 'head', e.heads);
      each(t, 'accrual', acc.map(v => fmt(v, '$m', 0, true)));
      return { text: t, data: { series: e.ni, series2: e.ocf, min: e.min, max: e.max, spread: true, accentLast: false } };
    },
    segmentMarginGrid(e) {
      const sc = e.scale || [0, 40];
      const t = { kicker: e.kicker, unit: e.unit, caption: e.caption };
      each(t, 'col', e.heads);
      const bands = {};
      e.rows.forEach((r, i) => {
        t['label-' + (i + 1)] = r[0];
        r[1].forEach((v, c) => {
          t['cell-' + (i + 1) + '-' + (c + 1)] = fmt(v, '%', 1);
          const falling = c === r[1].length - 1 && v < r[1][c - 1];
          bands['bar-' + (i + 1) + '-' + (c + 1)] = [0, frac(v, sc[0], sc[1]), falling ? 'attention' : 'subject'];
        });
      });
      return { text: t, data: { bands, spark: null } };
    },
  };

  Object.assign(B, {
    ratioVsFloor(e) {
      const sc = e.scale, last = e.values[e.values.length - 1];
      const t = { kicker: e.kicker, unit: e.unit, 'legend-1': e.legs[0], 'legend-2': e.legs[1], caption: e.caption,
        'headroom-label': e.headLabel, headroom: fmt(last - e.floor, 'pt', e.d == null ? 1 : e.d, true), 'headroom-detail': e.detail };
      each(t, 'head', e.heads || Q8);
      each(t, 'value', e.values.map(v => fmt(v, '%', e.d == null ? 1 : e.d)));
      return { text: t, data: { series: e.values, min: sc[0], max: sc[1], accent: -1,
        marks: { floor: frac(e.floor, sc[0], sc[1]) }, bands: { target: [frac(e.target[0], sc[0], sc[1]), frac(e.target[1], sc[0], sc[1]), 'band'] } } };
    },
    stackedToLine(e) {
      const sc = e.scale, tot = e.a.map((a, i) => +(a + e.b[i]).toFixed(1)), last = tot[tot.length - 1];
      const t = { kicker: e.kicker, unit: e.unit, 'legend-1': e.legs[0], 'legend-2': e.legs[1], caption: e.caption,
        'latest-label': e.latestLabel, latest: fmt(last, '%', 1), 'latest-detail': e.detail };
      each(t, 'head', e.heads);
      each(t, 'value', tot.map(v => fmt(v, '%', 1)));
      const bands = {};
      e.a.forEach((a, i) => { bands['part-a-' + (i + 1)] = [0, frac(a, sc[0], sc[1]), 'subject']; bands['part-b-' + (i + 1)] = [frac(a, sc[0], sc[1]), frac(a + e.b[i], sc[0], sc[1]), 'subject2']; });
      return { text: t, data: { bands, marks: { line: frac(100, sc[0], sc[1]) }, series: null } };
    },
    developmentRails(e) {
      const sc = e.scale;
      const t = { kicker: e.kicker, unit: e.unit, 'legend-1': 'First estimate', 'legend-2': 'Estimate today', caption: e.caption,
        'axis-low': fmt(sc[0], '$m'), 'axis-high': fmt(sc[1], '$m') };
      const marks = {};
      e.rows.forEach((r, i) => {
        t['label-' + (i + 1)] = r[0];
        t['dev-' + (i + 1)] = fmt(Math.round((r[2] / r[1] - 1) * 100), '%', 0, true);
        marks['first-' + (i + 1)] = frac(r[1], sc[0], sc[1]); marks['now-' + (i + 1)] = frac(r[2], sc[0], sc[1]);
      });
      return { text: t, data: { marks, series: null } };
    },
  });

  B.driverEffect = e => {
    const t = { kicker: e.kicker, unit: e.unit, caption: e.caption, 'label-1': e.driver[0], 'label-2': e.effect[0],
      'value-1': e.driver[2](e.driver[1][e.driver[1].length - 1]), 'value-2': e.effect[2](e.effect[1][e.effect[1].length - 1]),
      'sens-label': e.sensLabel, sens: e.sens, 'sens-detail': e.detail };
    each(t, 'head', e.heads || Q8);
    return { text: t, data: { series: null, panels: { 'panel-1': e.driver[1], 'panel-2': e.effect[1] },
      panelScale: { 'panel-1': e.driver[3], 'panel-2': e.effect[3] }, accentLast: true, zeroRule: true } };
  };

  B.sectorRanking = e => {
    const sc = e.scale, rows = e.rows.slice().sort((a, b) => b[1] - a[1]);
    const t = { kicker: e.kicker, unit: e.unit, caption: e.caption, 'legend-1': e.subject + ' (this episode)', 'legend-2': 'The market, all sectors: ' + fmt(e.market, '%', 1, true),
      'axis-low': fmt(sc[0], '%', 0, true), 'axis-high': fmt(sc[1], '%', 0, true) };
    const bands = {}, z = frac(0, sc[0], sc[1]);
    rows.forEach((r, i) => {
      t['label-' + (i + 1)] = r[0]; t['value-' + (i + 1)] = fmt(r[1], '%', 1, true);
      const v = frac(Math.max(sc[0], Math.min(sc[1], r[1])), sc[0], sc[1]);
      bands['bar-' + (i + 1)] = [Math.min(z, v), Math.max(z, v), r[0] === e.subject ? 'attention' : 'subject'];
    });
    return { text: t, data: { bands, marks: { market: frac(e.market, sc[0], sc[1]) }, series: null } };
  };
  B.priceCostSpread = e => {
    const t = { kicker: e.kicker, unit: e.unit, 'legend-1': e.legs[0], 'legend-2': e.legs[1], caption: e.caption,
      'spread-label': e.spreadLabel, spread: e.spread, 'spread-detail': e.detail };
    each(t, 'head', e.heads);
    return { text: t, data: { series: e.a, series2: e.b, min: e.min, max: e.max, spread: e.fill !== false, accentLast: false, zeroRule: e.min < 0, zero: e.min > 0 ? false : undefined } };
  };

  B.saidHappenedAs = e => {
    const t = { kicker: e.kicker, 'rail-said': e.rails[0], 'rail-happened': e.rails[1], caption: e.caption };
    e.rows.forEach((r, i) => { t['date-' + (i + 1)] = r[0]; t['said-' + (i + 1)] = r[1]; t['happened-' + (i + 1)] = r[2]; });
    return { text: t, data: { series: null, spark: null, diverge: e.rows.map((r, i) => (r[3] ? i + 1 : 0)).filter(Boolean) } };
  };
  B.revisionTrailAs = e => {
    const t = { kicker: e.kicker, note: e.note, caption: e.caption };
    e.rows.forEach((r, i) => {
      t['date-' + (i + 1)] = r[0]; t['est-' + (i + 1)] = e.f(r[1]);
      t['move-' + (i + 1)] = i === 0 ? 'initial' : fmt((r[1] / e.rows[i - 1][1] - 1) * 100, '%', 1, true);
    });
    return { text: t, data: { series: e.rows.map(r => r[1]), min: e.min, max: e.max, zero: false, accentLast: true } };
  };

  B.pairedBars = e => {
    const t = { kicker: e.kicker, unit: e.unit, caption: e.caption, 'col-a': e.cols[0], 'col-b': e.cols[1] }, bands = {};
    const bar = (v, s) => { const z = frac(0, s[0], s[1]), f = frac(Math.max(s[0], Math.min(s[1], v)), s[0], s[1]); return [Math.min(z, f), Math.max(z, f), v >= 0 ? 'up' : 'down']; };
    e.rows.forEach((r, i) => {
      t['label-' + (i + 1)] = r[0]; t['av-' + (i + 1)] = fmt(r[1], '%', 1, true); t['bv-' + (i + 1)] = fmt(r[2], '%', 1, true);
      bands['a-' + (i + 1)] = bar(r[1], e.sa); bands['b-' + (i + 1)] = bar(r[2], e.sb);
    });
    return { text: t, data: { bands, series: null } };
  };
  B.markedList = e => {
    const t = { kicker: e.kicker, unit: e.unit, caption: e.caption };
    e.rows.forEach((r, i) => { t['mark-' + (i + 1)] = r[0] === '-' ? MINUS : r[0]; t['tag-' + (i + 1)] = r[1]; t['line-' + (i + 1)] = r[2]; });
    return { text: t, data: { series: null, markInk: e.rows.map(r => (r[0] === '+' ? 'down' : r[0] === '-' ? 'up' : 'quiet')) } };
  };
  B.footnoteSpot = e => ({ text: { kicker: e.kicker, unit: e.unit, caption: e.caption, ref: e.ref, quote: e.quote, marked: e.marked,
    'pull-label': e.pull[0], pull: e.pull[1], 'pull-detail': e.pull[2] }, data: { series: null } });
  B.eventCalendar = e => {
    const t = { kicker: e.kicker, unit: e.unit, caption: e.caption }, marks = {};
    each(t, 'month', e.months);
    e.rows.forEach((r, i) => { t['num-' + (i + 1)] = String(i + 1); t['date-' + (i + 1)] = r[0]; t['event-' + (i + 1)] = r[2]; t['watch-' + (i + 1)] = r[3];
      marks['when-' + (i + 1)] = +(r[1] / e.days).toFixed(4); });
    return { text: t, data: { marks, series: null } };
  };

  B.chapterBumper = e => ({ text: { num: e.num, of: e.of, title: e.title, episode: e.episode }, data: { series: null } });
  B.sourceTag = e => ({ text: { label: 'SOURCE', source: e.source }, data: { series: null } });

  B.shortNumber = e => ({ text: { label: e.label, num: e.num, context: e.context, source: e.source }, data: { series: null } });
  B.shortQuote = e => {
    const words = ('\u201c' + e.quote + '\u201d').split(' '), lines = [''];
    words.forEach(w => { const cur = lines[lines.length - 1]; if ((cur + ' ' + w).trim().length > (e.perLine || 22) && cur) lines.push(w); else lines[lines.length - 1] = (cur + ' ' + w).trim(); });
    if (lines.length > 4) throw new Error('short-quote: more than four lines; cut the quote, never the font');
    /* Unused line slots are set EMPTY: left unset, content.js fills them with generic sample copy. */
    const t = { who: e.who, when: e.when }; for (let i = 0; i < 4; i++) t['quote-' + (i + 1)] = lines[i] || '';
    return { text: t, data: { series: null } };
  };
  B.shortChart = e => {
    const s = e.series, d = (s[s.length - 1] / s[0] - 1) * 100;
    return { text: { label: e.label, delta: fmt(d, '%', 0, true), start: e.start, end: e.end, source: e.source },
      data: { series: s, min: e.min, max: e.max, accentLast: true, zero: e.min > 0 ? false : undefined } };
  };

  /* [family, type, author, args, entry] */
  const SPEC = [];
  const add = (family, type, author, args, e) => SPEC.push([family, type, author, args, e]);

  add('charts', 'valuation-ev-ebitda', 'valuationHistory', { points: 20 }, { u: 'x', min: 8, max: 24,
    series: [17.2, 18.4, 19.8, 21.6, 20.9, 19.1, 17.5, 16.2, 15.8, 16.4, 17.1, 16.0, 14.9, 14.2, 13.6, 13.1, 12.8, 12.4, 12.1, 11.9],
    kicker: 'EV / EBITDA, NEXT TWELVE MONTHS', unit: 'times, at each quarter-end',
    detail: 'At the bottom of its own five-year range and well under the average',
    caption: 'Harrow is at its lowest multiple in five years',
    ch: ['valuation'], purpose: 'enterprise value to forward EBITDA over five years, against its own five-year range and average: cheap or dear against its own history, not a peer\u2019s.',
    caution: 'A multiple at the bottom of its range can be right: say what changed, because the voice-over, not the plate, has to argue it is cheap.' });
  add('charts', 'valuation-pe-forward', 'valuationHistory', { points: 20 }, { u: 'x', min: 8, max: 30,
    series: [22.1, 24.8, 26.3, 25.0, 23.4, 21.9, 19.8, 18.6, 17.9, 18.8, 19.4, 18.1, 16.9, 15.2, 14.4, 13.9, 14.6, 15.3, 14.8, 14.1],
    kicker: 'PRICE TO FORWARD EARNINGS', unit: 'times, at each quarter-end',
    detail: 'Down from 26 times as the growth story faded',
    caption: 'Larkin trades at half its peak multiple',
    ch: ['valuation'], purpose: 'forward P/E over five years against its own range and average.',
    caution: 'Forward earnings are consensus estimates; if they are being cut, a falling P/E overstates how much cheaper the shares got.' });
  add('charts', 'valuation-ev-sales', 'valuationHistory', { points: 20 }, { u: 'x', min: 0, max: 24,
    series: [14.2, 17.8, 21.4, 18.6, 13.1, 9.8, 8.4, 7.9, 8.8, 9.6, 10.4, 9.1, 8.2, 7.6, 7.9, 8.3, 8.1, 7.4, 6.9, 6.6],
    kicker: 'EV / SALES, NEXT TWELVE MONTHS', unit: 'times, at each quarter-end',
    detail: 'A third of the 2021 peak, and still falling as growth slows',
    caption: 'Tessera\u2019s multiple never recovered from 2022',
    ch: ['valuation'], sectors: ['information-technology'], purpose: 'enterprise value to forward sales over five years, against its own range and average: the multiple unprofitable software is priced on.',
    caution: 'EV/Sales ignores margins. Show it beside rule-of-40 or operating-leverage, never alone.' });
  add('charts', 'valuation-fcf-yield', 'valuationHistory', { points: 20 }, { u: '%', min: 0, max: 9,
    series: [1.8, 1.6, 1.4, 1.9, 2.6, 3.4, 4.1, 4.6, 4.2, 3.9, 3.6, 4.4, 5.1, 5.8, 6.3, 6.1, 6.6, 7.0, 7.2, 7.4],
    kicker: 'FREE CASH FLOW YIELD', unit: '% of market value, last 12m',
    detail: 'Higher is cheaper: four times the yield of 2021',
    caption: 'The highest cash yield in five years',
    ch: ['valuation', 'capital-allocation'], purpose: 'free cash flow as a share of market value over five years, against its own range and average.',
    caution: 'This one reads upside down: a HIGHER yield is a CHEAPER share. Say so in the voice-over every time.' });
  add('charts', 'guidance-range', 'guidanceRange', { quarters: 8 }, { u: '$m', min: 170, max: 235,
    guide: [[180, 184], [188, 192], [196, 200], [204, 208], [210, 214], [216, 220], [220, 224], [224, 228]],
    actual: [186, 193, 199, 207, 211, 217, 219, 223],
    kicker: 'REVENUE AGAINST GUIDANCE', unit: '$m per quarter',
    detail: 'The last two quarters landed under the bottom of the range',
    caption: 'Six beats, then two misses below the range',
    ch: ['guidance-estimates', 'management'], purpose: 'the guided range for each of eight quarters as a bar, the reported figure as a mark on it: the habit of a management team, not one quarter\u2019s headline.',
    caution: 'Use the range as first given, not as revised mid-quarter; say which in the voice-over if the company revised.' });
  add('charts', 'small-multiples-4', 'smallMultiples', { panels: 4 }, { u: '%', min: -10, max: 20, start: 'Q1 24', end: 'Q4 25',
    rows: [['New pumps', [6, 4, 1, -2, -4, -6, -7, -9]], ['New valves', [3, 2, 1, 0, -1, -3, -4, -5]],
      ['Spare parts', [5, 6, 7, 8, 8, 9, 10, 11]], ['Service', [8, 9, 11, 12, 12, 13, 14, 14]]],
    kicker: 'ORGANIC GROWTH BY SEGMENT', unit: '% a year earlier, shared scale',
    caption: 'Equipment shrinks; the aftermarket grows',
    ch: ['the-numbers', 'how-the-money-is-made'], purpose: 'four series in four panels on ONE shared scale: segments, regions or products that would be spaghetti on one plot.',
    caution: 'The scale is shared on purpose. If one series dwarfs the rest, cut to it alone rather than rescaling its panel.' });
  add('charts', 'small-multiples-6', 'smallMultiples', { panels: 6 }, { u: '%', min: -8, max: 10, start: 'Q1 24', end: 'Q4 25',
    rows: [['North America', [4, 3, 2, 1, 0, -1, -2, -3]], ['United Kingdom', [2, 1, 0, -1, -2, -3, -4, -5]],
      ['Europe', [1, 1, 0, 0, -1, -1, -2, -2]], ['Middle East', [7, 8, 7, 8, 9, 8, 9, 9]],
      ['Asia Pacific', [5, 4, 4, 3, 3, 2, 2, 1]], ['Online', [8, 7, 6, 5, 5, 4, 3, 3]]],
    kicker: 'SAME-STORE SALES BY REGION', unit: '% a year earlier, shared scale',
    caption: 'Every region but one slowed for two years',
    ch: ['the-numbers', 'sector-comps'], purpose: 'six series in six panels on ONE shared scale.',
    caution: 'Six is the most a viewer can hold. More than six and the plate becomes a table; use a table plate.' });
  add('charts', 'earnings-vs-cash', 'earningsVsCash', { years: 8 }, { min: 0, max: 450,
    heads: ['FY18', 'FY19', 'FY20', 'FY21', 'FY22', 'FY23', 'FY24', 'FY25'],
    ni: [120, 160, 210, 260, 300, 340, 380, 410], ocf: [150, 170, 190, 200, 190, 180, 170, 160],
    kicker: 'NET INCOME AGAINST OPERATING CASH FLOW', unit: '$m a year',
    detail: 'Capitalised content spend keeps profit ahead of cash',
    caption: 'Profit doubled while operating cash fell',
    ch: ['the-numbers', 'risk'], purpose: 'net income and operating cash flow on one scale, the gap filled and printed as a row of accruals: earnings quality, as an area.',
    caution: 'Accruals are not fraud. Growth companies run them honestly; the question is whether the gap closes, so say what is in it.' });
  add('tables', 'segment-margin-grid', 'segmentMarginGrid', { rows: 5, cols: 5, scale: [0, 40] }, { scale: [0, 40],
    heads: ['FY21', 'FY22', 'FY23', 'FY24', 'FY25'],
    rows: [['Pumps', [18.2, 17.4, 15.9, 14.1, 12.6]], ['Valves', [14.8, 15.1, 15.6, 16.2, 16.9]],
      ['Aftermarket', [28.4, 29.1, 30.2, 31.0, 31.8]], ['Services', [9.2, 10.4, 11.1, 11.6, 12.3]],
      ['Controls', [21.6, 20.8, 19.4, 17.2, 15.1]]],
    kicker: 'OPERATING MARGIN BY SEGMENT', unit: '%, each bar on one 0\u201340% scale',
    caption: 'Aftermarket carries the group; pumps slide',
    ch: ['how-the-money-is-made', 'the-numbers'], purpose: 'margin by segment and year, a figure in each cell and a bar under it on one fixed scale. Read across for a trend and down for which segment carries a year. A falling latest year is marked.',
    caution: 'Segment margins before group costs. If the company allocates corporate costs, say whether these are before or after.' });

  /* Q3 · banks and insurers. Merrow Bank (the kit's financials issuer) and Pellam, a fictional
   * property and casualty insurer. */
  add('charts', 'cet1-vs-minimum', 'ratioVsFloor', { quarters: 8, scale: [0, 20] }, { scale: [0, 20], floor: 4.5, target: [10.5, 12.0],
    values: [13.8, 13.6, 13.1, 12.9, 12.4, 12.1, 11.6, 11.2],
    kicker: 'COMMON EQUITY TIER 1 RATIO', unit: '% of risk-weighted assets', legs: ['4.5% legal minimum', 'Minimum plus buffers'],
    headLabel: 'OVER THE MINIMUM', detail: 'Still clear of the buffers, but the margin has halved in two years',
    caption: 'Merrow’s capital cushion has shrunk for eight quarters',
    ch: ['risk', 'the-numbers'], sectors: ['financials'], purpose: 'a bank’s CET1 ratio quarter by quarter on a fixed 0–20% scale, against the legal minimum and the minimum plus buffers: capital as headroom over a line.',
    caution: 'The buffer stack differs by bank and by country; name the buffers in the voice-over and use the bank’s own disclosed requirement.' });
  add('charts', 'solvency-ratio', 'ratioVsFloor', { quarters: 8, scale: [0, 250] }, { scale: [0, 250], floor: 100, target: [150, 180], d: 0,
    values: [212, 205, 198, 186, 174, 168, 159, 152],
    kicker: 'SOLVENCY RATIO', unit: '% of the capital requirement', legs: ['100% requirement', 'Target range 150–180%'],
    headLabel: 'OVER REQUIREMENT', detail: 'At the bottom of its target range after two catastrophe years',
    caption: 'Pellam has used most of its surplus capital',
    ch: ['risk', 'capital-allocation'], sectors: ['financials'], purpose: 'an insurer’s solvency ratio quarter by quarter on a fixed scale, against the 100% requirement and its own target range.',
    caution: 'Solvency regimes differ (Solvency II, RBC, BSCR); say which, and never compare two insurers under different regimes on one plate.' });
  add('charts', 'combined-ratio', 'stackedToLine', { years: 6, scale: [0, 120] }, { scale: [0, 120],
    heads: ['FY20', 'FY21', 'FY22', 'FY23', 'FY24', 'FY25'], a: [62.1, 64.8, 71.2, 68.4, 74.9, 70.3], b: [29.4, 29.1, 28.8, 28.2, 27.9, 27.6],
    kicker: 'COMBINED RATIO', unit: '% of premiums earned', legs: ['Claims (loss ratio)', 'Costs (expense ratio)'],
    latestLabel: 'FY25 COMBINED', detail: 'Over 100% in FY22 and FY24: underwriting lost money',
    caption: 'Costs fell every year; claims decided the result',
    ch: ['the-numbers', 'how-the-money-is-made'], sectors: ['financials'], purpose: 'claims and costs as a share of premiums, stacked per year on a fixed scale, against the 100% line where underwriting stops making money.',
    caution: 'Use the ratio excluding prior-year reserve releases if the company gives it, or say that releases flatter it; show reserve-development beside it.' });
  add('figures', 'reserve-development', 'developmentRails', { rows: 6 }, { scale: [350, 600],
    rows: [['AY 2019', 420, 402], ['AY 2020', 455, 441], ['AY 2021', 470, 489], ['AY 2022', 510, 552], ['AY 2023', 530, 571], ['AY 2024', 560, 566]],
    kicker: 'RESERVE DEVELOPMENT BY ACCIDENT YEAR', unit: '$m set aside for claims',
    caption: 'Older years released reserves; newer ones cost more',
    ch: ['risk', 'the-numbers'], sectors: ['financials'], purpose: 'for each accident year, the first reserve estimate and today’s estimate as two marks on one rail: whether an insurer is finding out its claims cost more than it said.',
    caution: 'Recent years always move most; say how many years of development each has had. Adverse development in a young year is an early warning, not yet a verdict.' });

  /* Q4 · macro drivers. Each pairs a driver with one issuer the kit already has. */
  const pc = d => v => fmt(v, '%', d == null ? 1 : d), pcs = d => v => fmt(v, '%', d == null ? 1 : d, true);
  add('charts', 'macro-rates', 'driverEffect', { points: 8 }, {
    driver: ['Policy rate', [0.5, 1.5, 2.5, 3.5, 4.25, 4.5, 4.5, 4.25], pc(2), [0, 5]],
    effect: ['Merrow net interest margin', [2.41, 2.62, 2.88, 3.04, 3.12, 3.08, 2.96, 2.87], pc(2), [2, 3.4]],
    kicker: 'RATES AND WHAT THEY DO TO A BANK', unit: '% each quarter', sensLabel: 'SENSITIVITY', sens: '+$42m',
    detail: 'Net interest income for a one-point rise in rates, per the annual report',
    caption: 'The margin rose with rates, then turned before they did',
    ch: ['how-the-money-is-made', 'risk'], sectors: ['financials'], purpose: 'the policy rate above, the bank’s net interest margin below, each on its own scale, with the bank’s own disclosed sensitivity: how rates reach the income statement.',
    caution: 'Deposit costs lag rates; the margin can fall while rates are still high. Use the company’s sensitivity, never one computed from these panels.' });
  add('charts', 'macro-inflation', 'driverEffect', { points: 8 }, {
    driver: ['Food inflation', [11.8, 10.2, 7.9, 5.4, 3.6, 2.8, 2.9, 3.4], pcs(1), [0, 13]],
    effect: ['Fenwick price and mix', [9.2, 8.1, 6.4, 4.8, 3.6, 2.9, 2.2, 1.8], pcs(1), [0, 10]],
    kicker: 'INFLATION AND PRICING POWER', unit: '% on a year earlier', sensLabel: 'PRICE, LAST YEAR', sens: '+2.6%',
    detail: 'Prices followed inflation down, and have not followed it back up',
    caption: 'Fenwick could pass on inflation, until it could not',
    ch: ['moat', 'how-the-money-is-made'], sectors: ['consumer-staples'], purpose: 'inflation in the company’s inputs above, its own price increases below: pricing power as whether the second line follows the first.',
    caution: 'Use the inflation series closest to the company’s costs (food, not headline CPI) and say which.' });
  add('charts', 'macro-fx', 'driverEffect', { points: 8 }, {
    driver: ['US dollar index', [101, 104, 106, 103, 105, 108, 110, 109], v => num(v, 0), [95, 115]],
    effect: ['Currency effect on Harrow growth', [0.4, -0.6, -1.4, -0.8, -1.2, -2.1, -2.8, -2.6], v => fmt(v, 'pt', 1, true), [-4, 2]],
    kicker: 'THE DOLLAR AND REPORTED GROWTH', unit: 'index; points of revenue growth', sensLabel: 'LATEST QUARTER', sens: '−2.6pt',
    detail: 'Reported growth 3.1%, constant-currency growth 5.7%',
    caption: 'A stronger dollar took 2.6 points off growth',
    ch: ['the-numbers', 'guidance-estimates'], sectors: ['industrials'], purpose: 'the dollar above, the currency effect on reported growth below: the gap between reported and constant-currency growth, explained.',
    caution: 'Constant-currency growth is the company’s own measure; quote its definition. Hedging can delay the effect by quarters.' });
  add('charts', 'macro-commodity', 'driverEffect', { points: 8 }, {
    driver: ['Copper price, $ per pound', [3.9, 4.2, 4.3, 4.1, 4.4, 4.6, 4.5, 4.4], v => '$' + v.toFixed(2), [3.6, 4.8]],
    effect: ['Corvane EBITDA margin', [38, 41, 42, 39, 41, 43, 40, 37], pc(0), [34, 44]],
    kicker: 'THE COPPER PRICE AND THE MARGIN', unit: 'each quarter', sensLabel: 'SENSITIVITY', sens: '$85m',
    detail: 'EBITDA for each 10¢ a pound on the copper price',
    caption: 'The price held up; the margin fell as costs rose',
    ch: ['how-the-money-is-made', 'risk'], sectors: ['materials'], purpose: 'the commodity price above, the producer’s margin below: how much of the margin is the price and how much is the company.',
    caution: 'A margin that stops following the price is a cost story; say which costs. Quote the company’s own sensitivity.' });
  add('charts', 'macro-wages', 'driverEffect', { points: 8 }, {
    driver: ['Retail wage growth', [6.8, 6.4, 5.9, 5.2, 4.9, 4.6, 4.4, 4.2], pcs(1), [3, 7.5]],
    effect: ['Larkin store costs, % of sales', [21.4, 21.9, 22.3, 22.8, 23.1, 23.3, 23.6, 23.8], pc(1), [20.5, 24.5]],
    kicker: 'WAGES AND STORE COSTS', unit: '% each quarter', sensLabel: 'PER POINT OF WAGES', sens: '$11m',
    detail: 'Added to annual store costs, per the company’s own guidance',
    caption: 'Wage growth slowed; store costs kept rising',
    ch: ['how-the-money-is-made', 'risk'], sectors: ['consumer-discretionary'], purpose: 'wage growth above, store costs as a share of sales below: operating leverage going the wrong way.',
    caution: 'Costs as a share of sales rise when sales fall even if wages do not; show same-store sales alongside before blaming wages.' });

  /* Q5 · sector performance against the other sectors, over one period. */
  add('peers', 'sector-ranking', 'sectorRanking', { rows: 11, scale: [-30, 30] }, { scale: [-30, 30], subject: 'Industrials', market: 8.4,
    rows: [['Information technology', 21.6], ['Communication services', 17.2], ['Financials', 12.9], ['Industrials', 3.1], ['Consumer discretionary', 6.8],
      ['Health care', -2.4], ['Consumer staples', 1.9], ['Energy', -8.7], ['Utilities', 9.8], ['Real estate', -4.1], ['Materials', -1.3]],
    kicker: 'EVERY SECTOR, FY25', unit: 'total return, % · one fixed scale',
    caption: 'Industrials trailed the market by five points',
    ch: ['sector-comps', 'the-numbers'], purpose: 'all eleven sectors’ returns over one period, ranked, as bars from zero on a fixed symmetric scale, with the market as one line down every row: where the episode’s sector ranked.',
    caution: 'Name the index family (the sectors must come from one index) and the period in the unit line. Total return, with dividends, unless the voice-over says otherwise.' });
  add('charts', 'sector-vs-market', 'priceCostSpread', { quarters: 12, fill: false }, { min: 90, max: 125, fill: false,
    heads: ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'],
    a: [100, 101.8, 103.1, 102.4, 104.6, 106.2, 105.1, 107.8, 108.4, 109.9, 107.6, 108.4],
    b: [100, 99.1, 98.4, 97.2, 98.8, 100.4, 99.6, 101.2, 102.1, 103.8, 102.9, 103.1],
    kicker: 'INDUSTRIALS AGAINST THE MARKET, FY25', unit: 'total return, rebased to 100', legs: ['The market', 'Industrials'],
    spreadLabel: 'BEHIND THE MARKET', spread: '−5.3pt', detail: 'The gap opened in the first quarter and never closed',
    caption: 'The sector fell behind early and stayed behind',
    ch: ['sector-comps'], purpose: 'one sector against the market over one period, both rebased to 100 on one scale, the gap NOT filled: the two are compared, not added, and the callout carries the gap.',
    caution: 'Both lines from the same index family and both total return. Rebase at the start of the period the voice-over names, never at a low.' });

  /* Q6 · said-vs-happened and revision-trail variants. */
  add('structure', 'said-happened-guidance', 'saidHappenedAs', { events: 4 }, {
    kicker: 'WHAT TESSERA GUIDED, AND WHAT IT DID', rails: ['WHAT THEY GUIDED', 'WHAT WAS REPORTED'],
    rows: [['Feb 24', 'Revenue growth of 20% for the year', 'Grew 21%', false], ['May 24', 'Margins expand every quarter', 'Margin up in three of four', false],
      ['Nov 24', 'Net retention back above 115%', 'Fell to 108%', true], ['Feb 25', 'Billings to lead revenue again', 'Billings under revenue twice', true]],
    caption: 'The growth promises held; the retention ones did not',
    ch: ['guidance-estimates', 'management'], sectors: ['information-technology'], purpose: 'four things management guided against what was reported, with a tie marked only where the two contradict: a guidance record.',
    caution: 'Quote the guidance as given, with its date. Mark a contradiction only where the outcome is the opposite, not merely short.' });
  add('structure', 'said-happened-capital', 'saidHappenedAs', { events: 4 }, {
    kicker: 'HARROW ON CAPITAL, THEN AND NOW', rails: ['WHAT THEY PROMISED', 'WHAT THEY DID'],
    rows: [['Mar 23', 'A $400m buyback over two years', 'Bought back $410m', false], ['Mar 23', 'Debt under 2\u00d7 EBITDA', 'Reached 1.8\u00d7', false],
      ['Nov 23', 'No large acquisitions', 'Bought Castell for $1.1bn', true], ['Mar 24', 'Dividend to grow with earnings', 'Held flat as earnings rose', true]],
    caption: 'The buyback happened; the discipline on deals did not',
    ch: ['capital-allocation', 'management'], sectors: ['industrials'], purpose: 'four capital-allocation promises against what was done, contradictions tied.',
    caution: 'A changed plan is not a broken promise if it was announced with reasons; say so where it was.' });
  add('structure', 'said-happened-strategy', 'saidHappenedAs', { events: 4 }, {
    kicker: 'LARKIN\u2019S STORE PLAN', rails: ['THE PLAN', 'THE RESULT'],
    rows: [['Jan 22', 'Open 60 stores a year', 'Opened 62 in the first year', false], ['Jan 23', 'Online to pass 30% of sales', 'Reached 24%', true],
      ['Jan 24', 'Close 40 weak stores', 'Closed 88', true], ['Jan 25', 'Return to growth in the UK', 'UK sales fell 5%', true]],
    caption: 'Three years of plans, one of them delivered',
    ch: ['management', 'how-we-got-here'], sectors: ['consumer-discretionary'], purpose: 'a strategy as it was announced each year against what happened to it.',
    caution: 'Use each year\u2019s plan as announced that year, not as restated later.' });
  add('structure', 'revision-trail-up', 'revisionTrailAs', { rows: 5, landOnly: true }, { min: 3.6, max: 4.8, f: v => '$' + v.toFixed(2),
    rows: [['8 Aug', 3.82], ['21 Sep', 3.95], ['24 Oct', 4.18], ['2 Dec', 4.31], ['30 Jan', 4.52]],
    kicker: 'HOW THE ESTIMATE MOVED, UPWARD', note: 'Four raises in six months, the biggest after third-quarter results',
    caption: 'Consensus EPS for Merrow\u2019s full year, by date',
    ch: ['guidance-estimates'], sectors: ['financials'], purpose: 'how the consensus estimate moved across five dates, with the move called at each step, in the direction the market was being surprised.',
    caution: 'Estimates rise into good news and fall after bad; say what each move followed, or the trail reads as momentum.' });
  add('structure', 'revision-trail-target', 'revisionTrailAs', { rows: 6, landOnly: true }, { min: 30, max: 62, f: v => '$' + v.toFixed(0),
    rows: [['Jun 24', 58], ['Aug 24', 55], ['Nov 24', 48], ['Jan 25', 44], ['Mar 25', 41], ['May 25', 36]],
    kicker: 'THE AVERAGE PRICE TARGET', note: 'Cut at every one of the last six updates',
    caption: 'Analysts\u2019 average 12-month price target for Larkin',
    ch: ['guidance-estimates', 'valuation'], sectors: ['consumer-discretionary'], purpose: 'the average analyst price target across six dates, with each cut called.',
    caution: 'Targets trail the price; a falling target is often the price being described, not predicted. Say so.' });
  add('structure', 'revision-trail-revenue', 'revisionTrailAs', { rows: 4, landOnly: true }, { min: 820, max: 900, f: v => '$' + v.toFixed(0) + 'm',
    rows: [['Nov 24', 884], ['Feb 25', 871], ['May 25', 852], ['Aug 25', 838]],
    kicker: 'NEXT YEAR\u2019S REVENUE, AS FORECAST', note: 'Each quarter\u2019s results took the forecast lower',
    caption: 'Consensus revenue for Tessera\u2019s next fiscal year',
    ch: ['guidance-estimates'], sectors: ['information-technology'], purpose: 'how the revenue forecast for one year moved across four dates.',
    caution: 'The same fiscal year throughout; when the year rolls, start a new trail.' });

  /* Q7 · six plates. */
  add('charts', 'surprise-vs-reaction', 'pairedBars', { rows: 8, scaleA: [-10, 10], scaleB: [-15, 15] }, { sa: [-10, 10], sb: [-15, 15],
    cols: ['EPS AGAINST CONSENSUS', 'SHARE PRICE NEXT DAY'],
    rows: [['Q1 24', 4.2, 6.1], ['Q2 24', 3.1, 2.4], ['Q3 24', 5.8, -3.2], ['Q4 24', 2.2, -6.8], ['Q1 25', 6.4, -1.9], ['Q2 25', 1.8, -8.4], ['Q3 25', -2.6, -11.2], ['Q4 25', 3.4, 1.1]],
    kicker: 'BEATS, AND WHAT THE SHARES DID', unit: '% each quarter',
    caption: 'Seven beats in eight; shares fell after five',
    ch: ['guidance-estimates', 'the-numbers'], purpose: 'each quarter’s earnings surprise against the next day’s share move, on two fixed scales: whether beating still moves the stock.',
    caution: 'A day’s move has other causes (guidance, the market). Say what else was announced when a beat is followed by a fall.' });
  add('peers', 'peer-rank', 'sectorRanking', { rows: 8, scale: [-20, 40] }, { scale: [-20, 40], subject: 'Tessera', market: 14.6,
    rows: [['Tessera', 18.4], ['Quillon', 31.2], ['Brevard', 24.8], ['Oakum', 22.1], ['Sallow', 12.6], ['Kestrel', 9.4], ['Dunmore', 4.8], ['Pinnacle', -6.2]],
    kicker: 'REVENUE GROWTH, TESSERA AND SEVEN PEERS', unit: '% on a year earlier, FY25',
    caption: 'Fourth of eight, and above the peer median',
    ch: ['sector-comps', 'the-numbers'], sectors: ['information-technology'], purpose: 'one measure for the company and its peers, ranked, the company in attention and the peer median as a line: where it stands among the companies it is compared with.',
    caution: 'Name how the peers were chosen. The line is the peer MEDIAN here, not the market; the legend must say so.' });
  add('paper', 'risk-factor-diff', 'markedList', { rows: 5 }, {
    rows: [['+', 'NEW \u00b7 CUSTOMERS', 'One customer now accounts for more than 10% of revenue'],
      ['+', 'NEW \u00b7 REGULATION', 'Proposed rules on data residency could require new regional hosting'],
      ['~', 'REWORDED \u00b7 COMPETITION', '\u201cMay offer bundles\u201d now reads \u201care offering\u201d'],
      ['-', 'REMOVED \u00b7 FINANCING', 'The risk of breaching the revolving credit covenant is gone'],
      ['~', 'REWORDED \u00b7 PEOPLE', 'Key-person risk now names the chief technology officer'],
    ], kicker: 'WHAT CHANGED IN THE RISK FACTORS', unit: '10-K FY25 against FY24',
    caption: 'Two new risks, one dropped, two sharpened',
    ch: ['risk'], purpose: 'the changes to a company’s risk factors between two filings, as lines marked added, removed or reworded: what the lawyers decided the company must now warn about.',
    caution: 'Quote the filing’s words, not a paraphrase, in the reworded lines. Boilerplate changes are not news; leave them out.' });
  add('paper', 'footnote-spotlight', 'footnoteSpot', {}, {
    ref: 'NOTE 14 \u00b7 COMMITMENTS \u00b7 10-K FY25, PAGE 96',
    quote: '\u201cThe Company has entered into agreements with content producers under which it is obligated to make payments over the next five years.\u201d',
    marked: 'Of these obligations, $3.1 billion is not reflected on the balance sheet.',
    pull: ['OFF THE BALANCE SHEET', '$3.1bn', 'More than the $2.4bn of debt it does report'],
    kicker: 'IN THE FOOTNOTES', unit: 'Brightline annual report',
    caption: 'The biggest liability sits in a note',
    ch: ['risk', 'the-numbers'], purpose: 'one footnote quoted, with the sentence that matters underlined and its figure pulled out: the thing an annual report says quietly.',
    caution: 'Quote exactly and give the note and page. Pull out a figure only if the note states it.' });
  add('charts', 'capital-returned', 'stackedToLine', { years: 6, scale: [0, 140] }, { scale: [0, 140],
    heads: ['FY20', 'FY21', 'FY22', 'FY23', 'FY24', 'FY25'], a: [32.1, 30.4, 29.8, 31.2, 30.6, 29.4], b: [18.4, 41.2, 55.6, 62.3, 78.1, 88.9],
    kicker: 'CASH RETURNED TO SHAREHOLDERS', unit: '% of free cash flow', legs: ['Dividends', 'Buybacks'],
    latestLabel: 'FY25 RETURNED', detail: 'Over 100% for two years: the gap was borrowed',
    caption: 'Harrow now returns more cash than it makes',
    ch: ['capital-allocation'], purpose: 'dividends and buybacks as a share of free cash flow, stacked per year, against the 100% line: above it, the returns are funded from the balance sheet.',
    caution: 'Say how the excess over 100% was funded (debt, cash on hand, disposals). A year over the line is not wrong; a run of them is the story.' });
  add('structure', 'event-calendar', 'eventCalendar', { events: 5, months: 6 }, { days: 182,
    months: ['OCT', 'NOV', 'DEC', 'JAN', 'FEB', 'MAR'],
    rows: [['23 Oct', 22, 'Third-quarter results', 'Whether retention stops falling'], ['12 Nov', 42, 'Investor day', 'The new medium-term margin target'],
      ['4 Dec', 64, 'Price increase takes effect', 'Churn in the first month after'], ['29 Jan', 120, 'Full-year results and guidance', 'Next year\u2019s growth range'],
      ['15 Mar', 165, 'Credit facility matures', 'Refinancing terms']],
    kicker: 'WHAT COMES NEXT', unit: 'the next six months, Tessera',
    caption: 'Five dates, and the thing to watch on each',
    ch: ['what-to-watch', 'risk'], sectors: ['information-technology'], purpose: 'the next dates that could move the shares on one rail over a fixed window, numbered, with the list saying what to watch at each: the episode’s closing checklist.',
    caution: 'Only confirmed dates. An expected date the company has not announced goes in the voice-over, not on the rail.' });

  /* Q9 · episode furniture. */
  add('structure', 'chapter-bumper', 'chapterBumper', {}, { num: '03', of: 'OF SEVEN', title: 'Where the cash actually goes',
    episode: 'BRIGHTLINE \u00b7 EPISODE 14',
    ch: ['*'], purpose: 'the frame between chapters: the chapter number large, its title and the episode. Two seconds over room tone.',
    caution: 'The title is the chapter\u2019s claim in five words or so, not its topic. \u201cWhere the cash goes\u201d, not \u201cCash flow\u201d.' });
  add('overlays', 'source-tag', 'sourceTag', { sizes: { land: [900, 72], port: [980, 92] } }, { source: '10-K FY25, note 14, page 96',
    ch: ['*'], purpose: 'where the figure on screen came from, as an alpha strip over a plate or the room: document, note and page.',
    caution: 'Name the document and the page, never just \u201ccompany filings\u201d. One source per tag; two figures from two sources are two tags.' });

  /* Q10 · shorts, 9:16 only. */
  add('shorts', 'short-number', 'shortNumber', { portOnly: true }, { label: 'OFF THE BALANCE SHEET', num: '$3.1bn',
    context: 'Brightline\u2019s content commitments, in a footnote', source: 'SOURCE \u00b7 10-K FY25, NOTE 14',
    ch: ['*'], purpose: 'a short\u2019s one number, set large in the safe area, with one line of context and its source.',
    caution: 'One number. If the short needs two, it is two shorts or a long plate.' });
  add('shorts', 'short-quote', 'shortQuote', { portOnly: true }, { quote: 'We are not planning any large acquisitions.',
    who: 'HARROW CHIEF EXECUTIVE', when: 'MARCH 2023 \u00b7 EIGHT MONTHS BEFORE BUYING CASTELL',
    ch: ['*'], purpose: 'a short\u2019s one quote, large, with who said it and when, and the fact that makes it matter in the date line.',
    caution: 'Quote exactly from a transcript and date it. The date line carries the irony; the quote is never edited to sharpen it.' });
  add('shorts', 'short-chart', 'shortChart', { portOnly: true }, { label: 'LARKIN SHARE PRICE', min: 20, max: 60,
    series: [52, 54, 51, 48, 49, 44, 41, 42, 37, 34, 35, 31], start: 'JAN 25', end: 'DEC 25', source: 'SOURCE \u00b7 CLOSING PRICES',
    ch: ['*'], purpose: 'a three-second chart: one line, its last point, and the change as the big figure.',
    caution: 'One line and no grid. If it takes more than three seconds to read, use a long plate.' });

  /* Q11 · transitions: no copy, no data. */
  B.wipeSweep = B.wipePage = B.wipeBlinds = () => ({ text: {}, data: { series: null } });
  [['wipe-sweep', 'wipeSweep', 'a hatched cover sweeps left to right; for moving on within a chapter'],
   ['wipe-page', 'wipePage', 'a sheet rises from the bottom edge and leaves at the top; for going to a document or a plate'],
   ['wipe-blinds', 'wipeBlinds', 'slats close and reopen; for the cut into a new chapter, under the bumper']].forEach(r =>
    add('overlays', r[0], r[1], { transition: true }, { ch: ['*'], purpose: r[2] + '. Eight frames, played once, alpha outside the cover.',
      caution: 'Cut the two shots under frame 4, where the cover is full. At most one wipe a minute; the plain cut is the default.' }));

  /* ── SECTOR VARIANTS (rebuild-36): the round-five shapes across the eleven
   * sectors, one issuer each. Series are generated from a seeded walk so a
   * variant is deterministic; every derived figure is still derived. New
   * fictional issuers: Ashby (energy), Norland (utilities), Calder (real
   * estate), Vireo (health care). */
  const walk = (seed, n, start, drift, vol, dp) => { let s = seed, v = start; const r = () => ((s = (s * 9301 + 49297) % 233280) / 233280); const out = [];
    for (let i = 0; i < n; i++) { out.push(+v.toFixed(dp == null ? 1 : dp)); v = v + drift + (r() - 0.5) * vol; } return out; };
  const range = (a, pad) => { const lo = Math.min.apply(null, a), hi = Math.max.apply(null, a), p = (hi - lo) * (pad || 0.2) || 1; return [+(lo - p).toFixed(2), +(hi + p).toFixed(2)]; };
  const V = (sector, id, who, kick, u, seed, start, drift, vol, cap, ch) => { const s = walk(seed, 20, start, drift, vol); const [mn, mx] = range(s);
    add('charts', 'valuation-' + id, 'valuationHistory', { points: 20 }, { u, min: Math.max(0, Math.floor(mn)), max: Math.ceil(mx), series: s, kicker: kick, unit: 'at each quarter-end, five years',
      detail: who + ' against its own five-year range', caption: cap, ch: ['valuation'], sectors: [sector],
      purpose: kick.toLowerCase() + ' for ' + who + ' over five years against its own range and average: the sector\u2019s usual multiple.',
      caution: 'Use the multiple the sector is priced on and say why; compare it only with its own history or same-sector peers.' }); };
  V('energy', 'energy', 'Ashby', 'EV / EBITDA', 'x', 101, 5.2, -0.06, 0.7, 'Ashby trades near a five-year low');
  V('utilities', 'utilities', 'Norland', 'PRICE TO FORWARD EARNINGS', 'x', 102, 19.5, -0.12, 0.8, 'Norland is cheaper than its average');
  V('real-estate', 'reit', 'Calder', 'PRICE TO FFO', 'x', 103, 22.0, -0.3, 1.2, 'Calder at half its 2021 multiple');
  V('health-care', 'health', 'Vireo', 'PRICE TO FORWARD EARNINGS', 'x', 104, 24.0, -0.35, 1.4, 'Vireo derated as patents near expiry');
  V('financials', 'bank', 'Merrow', 'PRICE TO TANGIBLE BOOK', 'x', 105, 1.1, 0.02, 0.12, 'Merrow back above tangible book');
  V('financials', 'insurer', 'Pellam', 'PRICE TO BOOK', 'x', 106, 1.6, -0.02, 0.14, 'Pellam below its average multiple');
  V('materials', 'materials', 'Corvane', 'EV / EBITDA', 'x', 107, 6.8, 0.04, 0.8, 'Corvane mid-range, not cheap');
  V('consumer-staples', 'staples', 'Fenwick', 'PRICE TO FORWARD EARNINGS', 'x', 108, 21.0, -0.1, 0.7, 'Fenwick below its long-run premium');
  V('communication-services', 'media', 'Brightline', 'EV / EBITDA', 'x', 109, 18.0, -0.4, 1.3, 'Brightline rerated down by half');
  V('consumer-discretionary', 'retail', 'Larkin', 'EV / EBITDA', 'x', 110, 11.0, -0.25, 0.9, 'Larkin at its cheapest in five years');

  const SM = (sector, id, n, kick, labels, seed, cap) => { const rows = labels.map((l, i) => [l, walk(seed + i * 7, 8, (i % 2 ? 4 : -1) + i, (i % 2 ? 0.4 : -0.6), 2.6, 0)]);
    const all = [].concat.apply([], rows.map(r => r[1])); const [mn, mx] = range(all, 0.15);
    add('charts', 'small-multiples-' + id, 'smallMultiples', { panels: n }, { u: '%', min: Math.floor(mn), max: Math.ceil(mx), start: 'Q1 24', end: 'Q4 25', rows,
      kicker: kick, unit: '% a year earlier, shared scale', caption: cap, ch: ['the-numbers', 'how-the-money-is-made'], sectors: [sector],
      purpose: kick.toLowerCase() + ', ' + n + ' panels on ONE shared scale.', caution: 'The scale is shared on purpose; never rescale one panel.' }); };
  SM('energy', 'energy', 4, 'ASHBY OUTPUT BY BASIN', ['Permian', 'Bakken', 'Gulf', 'North Sea'], 201, 'One basin grows; three decline');
  SM('utilities', 'utilities', 4, 'NORLAND DEMAND BY CUSTOMER', ['Homes', 'Offices', 'Industry', 'Data centres'], 202, 'Data centres carry demand growth');
  SM('real-estate', 'reit', 4, 'CALDER RENT BY PROPERTY TYPE', ['Offices', 'Warehouses', 'Retail', 'Flats'], 203, 'Warehouses up, offices down');
  SM('health-care', 'health', 6, 'VIREO SALES BY DRUG', ['Talvex', 'Orimab', 'Senzo', 'Pradil', 'Kyrin', 'Others'], 204, 'Two drugs do the growing');

  const EC = (sector, id, who, ni0, niD, oc0, ocD, seed, cap, det) => { const heads = ['FY18', 'FY19', 'FY20', 'FY21', 'FY22', 'FY23', 'FY24', 'FY25'];
    const ni = walk(seed, 8, ni0, niD, ni0 * 0.08, 0), ocf = walk(seed + 3, 8, oc0, ocD, oc0 * 0.08, 0); const [, mx] = range(ni.concat(ocf), 0.1);
    add('charts', 'earnings-vs-cash-' + id, 'earningsVsCash', { years: 8 }, { min: 0, max: Math.ceil(mx / 10) * 10, heads, ni, ocf,
      kicker: who.toUpperCase() + ': PROFIT AGAINST CASH', unit: '$m a year', detail: det, caption: cap, ch: ['the-numbers', 'risk'], sectors: [sector],
      purpose: 'net income against operating cash flow for ' + who + ', the gap as accruals.', caution: 'Say what is in the gap before calling it a warning.' }); };
  EC('information-technology', 'software', 'Tessera', 60, 30, 140, 40, 301, 'Cash runs ahead of profit', 'Share pay is a cost, not a cash outflow');
  EC('industrials', 'industrials', 'Harrow', 180, 12, 200, 4, 302, 'Profit and cash now diverge', 'Working capital is absorbing the cash');
  EC('health-care', 'health', 'Vireo', 400, 10, 380, 18, 303, 'Cash keeps pace with profit', 'Earnings quality is high');
  EC('real-estate', 'reit', 'Calder', 90, -4, 160, 6, 304, 'Revaluations drag reported profit', 'Property writedowns are non-cash');

  const SG = (sector, id, who, segs, seed, cap) => { const rows = segs.map((s, i) => [s, walk(seed + i * 5, 5, 8 + i * 4, (i % 2 ? 0.8 : -0.9), 2, 1).map(v => Math.max(0.5, Math.min(39.5, v)))]);
    add('tables', 'segment-margin-grid-' + id, 'segmentMarginGrid', { rows: segs.length, cols: 5, scale: [0, 40] }, { scale: [0, 40], heads: ['FY21', 'FY22', 'FY23', 'FY24', 'FY25'], rows,
      kicker: who.toUpperCase() + ' MARGIN BY SEGMENT', unit: '%, bars on one 0\u201340% scale', caption: cap, ch: ['how-the-money-is-made'], sectors: [sector],
      purpose: 'margin by segment and year for ' + who + ', each bar on one fixed scale.', caution: 'Before or after group costs: say which.' }); };
  SG('communication-services', 'media', 'Brightline', ['Streaming', 'Studios', 'Networks', 'Games', 'Licensing'], 401, 'Streaming margin finally rising');
  SG('consumer-staples', 'staples', 'Fenwick', ['Dairy', 'Snacks', 'Drinks', 'Baby', 'Pet'], 402, 'Pet and baby carry the margin');
  SG('health-care', 'health', 'Vireo', ['Pharma', 'Vaccines', 'Devices', 'Consumer'], 403, 'Pharma margin squeezed');
  SG('materials', 'materials', 'Corvane', ['Copper', 'Zinc', 'Nickel', 'Trading'], 404, 'Copper earns the most');

  const GR = (sector, id, who, u, lo, step, width, seed, kick, cap) => { const guide = [], actual = []; let s = seed; const r = () => ((s = (s * 9301 + 49297) % 233280) / 233280);
    for (let i = 0; i < 8; i++) { const a = lo + step * i; guide.push([+a.toFixed(1), +(a + width).toFixed(1)]); actual.push(+(a + width * (r() * 1.6 - 0.3)).toFixed(1)); }
    const all = [].concat.apply(actual, guide); const [mn, mx] = range(all, 0.2);
    add('charts', 'guidance-range-' + id, 'guidanceRange', { quarters: 8 }, { u, min: Math.floor(mn), max: Math.ceil(mx), guide, actual, kicker: kick, unit: who + ', each quarter',
      detail: 'Guided range as first given', caption: cap, ch: ['guidance-estimates', 'management'], sectors: [sector],
      purpose: who + '\u2019s guided range against what it reported, eight quarters.', caution: 'Use the range as first given, not as revised.' }); };
  GR('energy', 'energy', 'Ashby', '', 400, 6, 20, 501, 'OUTPUT AGAINST GUIDANCE, KBOE/D', 'Ashby lands inside its range');
  GR('utilities', 'utilities', 'Norland', '', 60, 2, 6, 502, 'EPS AGAINST GUIDANCE, CENTS', 'Norland beats its own range');
  GR('consumer-discretionary', 'retail', 'Larkin', '$m', 900, 12, 30, 503, 'REVENUE AGAINST GUIDANCE', 'Larkin at the low end, again');
  GR('health-care', 'health', 'Vireo', '$m', 2400, 30, 80, 504, 'REVENUE AGAINST GUIDANCE', 'Vireo keeps beating the top');

  const pc2 = d => v => fmt(v, '%', d);
  add('charts', 'macro-oil', 'driverEffect', { points: 8 }, { driver: ['Brent, $ a barrel', [78, 84, 91, 82, 76, 71, 68, 72], v => '$' + num(v, 0), [60, 95]],
    effect: ['Ashby cash from operations, $m', [980, 1060, 1180, 1040, 940, 880, 820, 870], v => '$' + num(v, 0) + 'm', [760, 1220]],
    kicker: 'THE OIL PRICE AND ASHBY\u2019S CASH', unit: 'each quarter', sensLabel: 'SENSITIVITY', sens: '$38m', detail: 'Quarterly cash for each $1 a barrel',
    caption: 'Ashby\u2019s cash follows the oil price', ch: ['how-the-money-is-made', 'risk'], sectors: ['energy'],
    purpose: 'the oil price above, the producer\u2019s operating cash below, each on its own scale.', caution: 'Hedging delays the effect; say how much is hedged.' });
  add('charts', 'macro-gas-power', 'driverEffect', { points: 8 }, { driver: ['Gas price, $ per MMBtu', [2.6, 2.4, 2.9, 3.4, 3.1, 2.8, 3.6, 3.9], v => '$' + v.toFixed(2), [2, 4.2]],
    effect: ['Norland fuel cost, % of revenue', [31, 30, 32, 35, 34, 33, 36, 38], pc2(0), [28, 40]],
    kicker: 'GAS AND A UTILITY\u2019S COSTS', unit: 'each quarter', sensLabel: 'PASSED THROUGH', sens: '80%', detail: 'Share of fuel cost the regulator lets it recover',
    caption: 'Fuel costs rise; most is passed on', ch: ['how-the-money-is-made', 'risk'], sectors: ['utilities'],
    purpose: 'the gas price above, fuel as a share of revenue below.', caution: 'Recovery lags by a rate case; say the lag.' });
  add('charts', 'macro-rates-reit', 'driverEffect', { points: 8 }, { driver: ['Ten-year yield', [3.6, 3.9, 4.3, 4.6, 4.4, 4.2, 4.5, 4.3], pc2(1), [3.2, 5]],
    effect: ['Calder net asset value, $ a share', [42, 40, 37, 34, 33, 34, 32, 33], v => '$' + num(v, 0), [30, 44]],
    kicker: 'BOND YIELDS AND PROPERTY VALUES', unit: 'each quarter', sensLabel: 'PER 0.25PT ON YIELDS', sens: '\u2212$1.9', detail: 'Net asset value a share, company estimate',
    caption: 'Higher yields cut Calder\u2019s values', ch: ['valuation', 'risk'], sectors: ['real-estate'],
    purpose: 'bond yields above, the REIT\u2019s net asset value below.', caution: 'Valuers lag the market; NAV moves after yields do.' });
  add('charts', 'macro-fx-staples', 'driverEffect', { points: 8 }, { driver: ['Euro in dollars', [1.06, 1.08, 1.10, 1.09, 1.12, 1.15, 1.17, 1.16], v => '$' + v.toFixed(2), [1.02, 1.2]],
    effect: ['Currency effect on Fenwick growth', [-1.2, -0.8, -0.2, -0.4, 0.4, 1.1, 1.6, 1.4], v => fmt(v, 'pt', 1, true), [-2, 2.2]],
    kicker: 'THE EURO AND FENWICK\u2019S GROWTH', unit: 'rate; points of growth', sensLabel: 'LATEST QUARTER', sens: '+1.4pt', detail: 'Reported growth flattered by the euro',
    caption: 'A stronger euro now adds to growth', ch: ['the-numbers'], sectors: ['consumer-staples'],
    purpose: 'the euro above, the currency effect on reported growth below.', caution: 'Quote organic growth beside it.' });

  const get = t => { const r = SPEC.find(x => x[1] === t); return r ? B[r[2]](r[4]) : null; };
  const API = {
    SPEC: SPEC.map(r => r.slice(0, 4)),
    text: (type) => { const b = get(type); return b ? Object.assign({}, b.text) : null; },
    data: (type) => { const b = get(type); return b ? JSON.parse(JSON.stringify(b.data)) : null; },
    roles: () => SPEC.map(r => ({ id: r[0] + '/' + r[1], ch: r[4].ch, sectors: r[4].sectors, purpose: r[4].purpose, caution: r[4].caution })),
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = API;
  g.COPY_R5 = API;
})(typeof window !== 'undefined' ? window : globalThis);
