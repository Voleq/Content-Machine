/* Dennis v2 — sector-copy.js
 *
 * ROUND FOUR: TEN PLATES PER SECTOR. The eleven GICS sectors each get at least
 * ten sector-specific plates; this file holds the eighty added in round four,
 * as DATA. Each entry names one of nine round-two shapes and carries its own
 * copy, numbers, purpose and caution:
 *
 *   spread   two rates on one scale, gap optionally filled   priceCostSpread
 *   walk     a bridge between two levels (float for rates)   walkN
 *   rails    share bar + growth rail per row                 endMarketExposure
 *   ceiling  eight quarters against a fixed 100%             rpoCoverage
 *   pairs    two series per year + a derived ratio row       pairedN
 *   b2b      two series per quarter + a ratio row            bookToBill
 *   tracks   three extents on one fixed scale                cashConversionCycle
 *   cohort   a triangle of cohorts by years since start      nrrCohorts
 *   payback  a cumulative line against a level              cacPayback
 *
 * ONE SOURCE. plates-r3.js reads SPEC from here, content.js reads the copy and
 * data from here, and roles.fragment.json is generated from here. The builders
 * DERIVE every figure that follows from the others: a walk's closing level and
 * net change come from its opening level and its steps, a ratio row is the two
 * rows divided, a payback month is the level over the monthly margin. So the
 * arithmetic on a plate cannot disagree with itself, and check() reports any
 * row of shares that does not sum to 100.
 */

'use strict';

(function (g) {
  const Q8 = ['Q1 24', 'Q2 24', 'Q3 24', 'Q4 24', 'Q1 25', 'Q2 25', 'Q3 25', 'Q4 25'];
  const Y6 = ['FY20', 'FY21', 'FY22', 'FY23', 'FY24', 'FY25'];
  const MINUS = '\u2212';
  const num = (v, d) => { const s = Math.abs(v).toFixed(d || 0); const p = s.split('.'); p[0] = p[0].replace(/\B(?=(\d{3})+(?!\d))/g, ','); return p.join('.'); };
  /* A value in its unit. u: '$m' '$bn' '$k' '$' 'm' 'k' '%' 'pt' 'x' 'y' 'd' ''. */
  function fmt(v, u, d, signed) {
    const sg = signed ? (v > 0 ? '+' : v < 0 ? MINUS : '') : (v < 0 ? MINUS : '');
    const s = num(v, d);
    switch (u) {
      case '$m': return sg + '$' + s + 'm';
      case '$bn': return sg + '$' + s + 'bn';
      case '$k': return sg + '$' + s + 'k';
      case '$': return sg + '$' + s;
      case 'x': return sg + s + '\u00d7';
      default: return sg + s + (u || '');
    }
  }
  const each = (o, p, l) => { l.forEach((v, i) => { o[p + '-' + (i + 1)] = v; }); return o; };
  const round = (v, d) => +v.toFixed(d == null ? 2 : d);

  /* ── the builders: an entry in, { text, data } out ─────────────────────── */

  const B = {
    spread(e) {
      const t = { kicker: e.kicker, unit: e.unit, 'legend-1': e.legs[0], 'legend-2': e.legs[1],
        'spread-label': e.spreadLabel, spread: e.spread, 'spread-detail': e.detail, caption: e.caption };
      each(t, 'head', e.heads || Q8);
      return { text: t, data: { series: e.a, series2: e.b, min: e.min, max: e.max, spread: e.fill !== false,
        accentLast: false, zeroRule: e.min < 0 } };
    },
    walk(e) {
      const close = round(e.open + e.steps.reduce((a, b) => a + b, 0), e.d || 0);
      const t = { kicker: e.kicker, unit: e.unit, caption: e.caption, 'change-label': e.changeLabel || 'NET CHANGE',
        change: fmt(close - e.open, e.su || e.u, e.d, true) };
      each(t, 'head', e.heads);
      each(t, 'value', [fmt(e.open, e.u, e.d)].concat(e.steps.map(s => fmt(s, e.su || e.u, e.d, true)), [fmt(close, e.u, e.d)]));
      return { text: t, data: { steps: e.steps, open: e.open, close, float: !!e.float }, close };
    },
    rails(e) {
      const t = { kicker: e.kicker, 'head-share': e.headShare, 'head-growth': e.headGrowth || 'GROWTH, YEAR ON YEAR',
        caption: e.caption, 'axis-low': MINUS + '20%', 'axis-high': '+20%' };
      const marks = {};
      e.rows.forEach((r, i) => {
        t['label-' + (i + 1)] = r[0]; t['share-' + (i + 1)] = r[1] + '%'; t['growth-value-' + (i + 1)] = fmt(r[2], '%', 0, true);
        marks['growth-' + (i + 1)] = (Math.max(-20, Math.min(20, r[2])) + 20) / 40;
      });
      return { text: t, data: { bars: e.rows.map(r => r[1]), min: 0, max: e.max || Math.ceil(Math.max.apply(null, e.rows.map(r => r[1])) / 10) * 10 + 10, accent: e.accent || 0, marks } };
    },
    ceiling(e) {
      const v = e.values, last = v[v.length - 1];
      const t = { kicker: e.kicker, unit: e.unit, 'ceiling-label': e.ceilingLabel, 'latest-label': e.latestLabel || 'LATEST QUARTER',
        latest: last + '%', 'latest-detail': e.detail, caption: e.caption };
      each(t, 'head', e.heads || Q8);
      each(t, 'value', v.map(x => x + '%'));
      return { text: t, data: { series: v, min: 0, max: 100, accent: v.length - 1 } };
    },
    pairs(e) {
      const ratio = e.a.map((a, i) => (e.ratio === 'a/b' ? a / e.b[i] : e.b[i] / a));
      const rf = r => (e.ratioFmt === 'x' ? fmt(r, 'x', 2) : Math.round(r * 100) + '%');
      const t = { kicker: e.kicker, unit: e.unit, 'row-1': e.rows[0], 'row-2': e.rows[1], 'ratio-label': e.rows[2],
        verdict: e.verdict, caption: e.caption };
      each(t, 'head', e.heads || Y6);
      each(t, 'sa', e.a.map(x => fmt(x, e.u, e.d)));
      each(t, 'sb', e.b.map(x => fmt(x, e.u, e.d)));
      each(t, 'ratio', ratio.map(rf));
      return { text: t, data: { series: e.a, series2: e.b, min: 0, max: e.max, tone2: 'subject2' } };
    },
    b2b(e) {
      const ratio = e.a.map((a, i) => a / e.b[i]);
      const t = { kicker: e.kicker, unit: e.unit, 'legend-1': e.legs[0], 'legend-2': e.legs[1], 'ratio-label': e.ratioLabel,
        'latest-label': e.latestLabel || 'LATEST QUARTER', latest: fmt(ratio[ratio.length - 1], 'x', 2), 'latest-detail': e.detail, caption: e.caption };
      each(t, 'head', e.heads || Q8);
      each(t, 'ratio', ratio.map(r => fmt(r, 'x', 2)));
      return { text: t, data: { series: e.a, series2: e.b, min: 0, max: e.max, tone2: 'quiet' } };
    },
    tracks(e) {
      const lo = e.scale[0], span = e.scale[1] - e.scale[0];
      const t = { kicker: e.kicker, head: e.head, 'days-unit': e.valueHead, caption: e.caption };
      const bands = {};
      e.rows.forEach((r, i) => {
        t['label-' + (i + 1)] = r[0]; t['detail-' + (i + 1)] = r[1]; t['days-' + (i + 1)] = r[2];
        bands['band-' + (i + 1)] = [(r[3] - lo) / span, (r[4] - lo) / span, r[5] || 'subject'];
      });
      each(t, 'tick', e.ticks);
      return { text: t, data: { bands } };
    },
    cohort(e) {
      const t = { kicker: e.kicker, unit: e.unit, head: e.head, caption: e.caption };
      each(t, 'col', e.cols || ['YEAR 1', 'YEAR 2', 'YEAR 3', 'YEAR 4', 'YEAR 5']);
      e.rows.forEach((row, r) => {
        t['label-' + (r + 1)] = row[0];
        row[1].forEach((v, c) => { t['cell-' + (r + 1) + '-' + (c + 1)] = v + (e.cellUnit == null ? '%' : e.cellUnit); });
      });
      return { text: t, data: {} };
    },
    payback(e) {
      const per = e.perMonth, series = [0, 1, 2, 3, 4, 5, 6].map(i => round(per * 6 * i, 1));
      const max = Math.ceil(Math.max(e.level, series[6]) * 1.15 / 10) * 10;
      const t = { kicker: e.kicker, 'legend-1': e.legs[0], 'legend-2': e.legs[1], 'x-axis': e.xAxis || 'MONTHS SINCE LAUNCH',
        'cac-label': e.inputs[0][0], cac: e.inputs[0][1], 'arr-label': e.inputs[1][0], arr: e.inputs[1][1],
        'gm-label': e.inputs[2][0], gm: e.inputs[2][1],
        'payback-label': e.paybackLabel || 'PAID BACK IN', payback: String(Math.round(e.level / per)), 'payback-unit': 'MONTHS',
        caption: e.caption };
      each(t, 'head', ['0', '6', '12', '18', '24', '30', '36']);
      return { text: t, data: { series, min: 0, max, accentLast: false, marks: { 'cac-line': e.level / max } } };
    },
  };

  /* The round-two author each shape uses, and the args it needs. */
  const SHAPE = {
    spread: ['priceCostSpread', () => ({ quarters: 8 })],
    walk: ['walkN', e => ({ cols: e.steps.length + 2, float: !!e.float })],
    rails: ['endMarketExposure', () => ({ rows: 5 })],
    ceiling: ['rpoCoverage', () => ({ quarters: 8 })],
    pairs: ['pairedN', () => ({ years: 6, rows: [{ label: 'row-1', name: 'sa', swatch: 'up' }, { label: 'row-2', name: 'sb', swatch: 'down' }, { label: 'ratio-label', name: 'ratio', rule: true }] })],
    b2b: ['bookToBill', () => ({ quarters: 8 })],
    tracks: ['cashConversionCycle', e => ({ ticks: e.ticks.length, bands: [['band-1'], ['band-2'], ['band-3']], scale: { range: e.scale, why: 'fixed, so every row is read on one scale' },
      bandNote: 'an extent on the fixed ' + e.scale[0] + '\u2013' + e.scale[1] + ' scale \u2014 historyBand draws it; pass [start, end] as fractions of the scale, then an ink role' })],
    cohort: ['nrrCohorts', () => ({ cohorts: 5 })],
    payback: ['cacPayback', () => ({})],
  };

  /* ── the eighty ──────────────────────────────────────────────────────────
   * [sector, family, name, shape, entry]. Entry carries its roles fields:
   * ch (chapter types), beat (short beat), purpose, caution. */
  const E = [];
  const add = (sector, family, name, shape, e) => E.push({ sector, family, name, shape, e });

  /* INFORMATION TECHNOLOGY — Tessera, subscription software (+4) */
  add('information-technology', 'figures', 'product-mix', 'rails', { kicker: 'WHERE THE REVENUE COMES FROM', headShare: 'SHARE OF FY25 REVENUE',
    rows: [['Cloud platform', 46, 19], ['Licences', 22, -11], ['Maintenance', 18, -4], ['Services', 9, 2], ['Marketplace', 5, 16]],
    caption: 'Cloud is nearly half, and licences are shrinking',
    ch: ['how-the-money-is-made', 'the-numbers'], beat: 'the-sheet',
    purpose: 'revenue by product line: share as a bar, growth as a mark on a rail centred on zero \u2014 the mix shift a software transition is argued on.',
    caution: 'Product lines as reported. A line that is a bundle of two, like cloud including maintenance, must say so in the caption.' });
  add('information-technology', 'figures', 'free-cash-walk', 'walk', { kicker: 'NET INCOME TO FREE CASH FLOW', unit: '$m, FY25',
    heads: ['NET INCOME', 'STOCK COMP', 'D&A', 'DEFERRED REV', 'CAPEX', 'FREE CASH'], open: 118, steps: [440, 96, 62, -71], u: '$m',
    changeLabel: 'CASH OVER EARNINGS', caption: 'Stock pay is most of the gap between profit and cash',
    ch: ['the-numbers', 'capital-allocation'], beat: 'numbers',
    purpose: 'net income to free cash flow through stock compensation, depreciation, deferred revenue and capex \u2014 why software cash flow runs far ahead of profit.',
    caution: 'Stock compensation is a real cost paid in shares; a free-cash figure that adds it back should be shown with sbc-vs-buybacks.' });
  add('information-technology', 'charts', 'operating-leverage', 'spread', { kicker: 'REVENUE GROWTH AGAINST COST GROWTH', unit: '% change on a year earlier',
    legs: ['Revenue growth', 'Operating cost growth'], a: [24, 22, 21, 19, 18, 17, 16, 17], b: [31, 28, 24, 19, 15, 12, 10, 9], min: 0, max: 35,
    spreadLabel: 'LATEST GAP', spread: '+8pt', detail: 'Costs now growing at about half the pace of revenue',
    caption: 'Where revenue runs above costs, the margin widens',
    ch: ['the-numbers', 'how-the-money-is-made'], beat: 'the-turn',
    purpose: 'revenue growth against operating-cost growth, eight quarters on one scale with the gap filled \u2014 operating leverage, as an area.',
    caution: 'Operating costs before stock compensation or after it, but the same basis every quarter.' });
  add('information-technology', 'charts', 'billings-vs-revenue', 'b2b', { kicker: 'BILLINGS AGAINST REVENUE', unit: '$m per quarter',
    legs: ['Billings', 'Revenue'], a: [201, 238, 196, 262, 205, 229, 188, 231], b: [182, 190, 198, 206, 212, 218, 222, 226], max: 300,
    ratioLabel: 'BILLINGS \u00f7 REVENUE', detail: 'Calculated billings under revenue in two of the last three quarters',
    caption: 'Billings used to lead revenue; this year they stopped',
    ch: ['guidance-estimates', 'the-numbers'], beat: 'numbers',
    purpose: 'billings beside revenue for eight quarters with the ratio under each pair \u2014 the lead indicator a subscription book is read on.',
    caution: 'Calculated billings are revenue plus the change in deferred revenue. Seasonal annual billing makes single quarters noisy; read the trend.' });

  /* INDUSTRIALS — Harrow, pumps and valves (+4) */
  add('industrials', 'figures', 'backlog-bridge', 'walk', { kicker: 'ORDER BACKLOG, FY25', unit: '$m',
    heads: ['OPENING', 'ORDERS', 'SHIPPED', 'CANCELLED', 'FX', 'CLOSING'], open: 1920, steps: [2150, -2290, -48, -22], u: '',
    caption: 'More shipped than was ordered, so the backlog fell',
    ch: ['the-numbers', 'guidance-estimates'], beat: 'numbers',
    purpose: 'backlog from opening to closing through orders, shipments, cancellations and currency \u2014 the stock behind book-to-bill.',
    caution: 'Shipments here are revenue recognised from backlog; short-cycle sales that never enter the backlog are left out.' });
  add('industrials', 'figures', 'aftermarket-mix', 'rails', { kicker: 'NEW EQUIPMENT AGAINST AFTERMARKET', headShare: 'SHARE OF FY25 REVENUE',
    rows: [['New pumps', 38, -9], ['New valves', 21, -6], ['Spare parts', 24, 7], ['Service', 12, 11], ['Upgrades', 5, 4]],
    caption: 'Aftermarket is 41% of revenue and all of the growth',
    ch: ['how-the-money-is-made', 'moat'], beat: 'the-sheet',
    purpose: 'revenue split between original equipment and the aftermarket, share and growth per line \u2014 the recurring part of an industrial.',
    caution: 'Aftermarket margins are usually much higher; if the company reports them, say so in the voice-over rather than on this plate.' });
  add('industrials', 'charts', 'plant-utilisation', 'ceiling', { kicker: 'PLANT UTILISATION', unit: 'hours run \u00f7 hours available',
    ceilingLabel: '100% \u00b7 THREE SHIFTS', values: [86, 88, 87, 84, 80, 77, 74, 72],
    detail: 'The Ohio plant has been on two shifts since June', caption: 'Fourteen points of utilisation lost in six quarters',
    ch: ['the-numbers', 'risk'], beat: 'numbers',
    purpose: 'plant utilisation for eight quarters against a fixed 100% ceiling \u2014 the operating leverage an industrial loses when volume falls.',
    caution: 'Utilisation on available hours, not nameplate; say which. Mothballed capacity changes the base.' });
  add('industrials', 'figures', 'automation-payback', 'payback', { kicker: 'WHAT THE ROBOTS COST, AND THE PAYBACK',
    legs: ['Labour saved, cumulative', 'Automation capex'], level: 42, perMonth: 1.5, xAxis: 'MONTHS SINCE INSTALLATION',
    inputs: [['CAPEX', '$42m'], ['LABOUR SAVED', '$18m a year'], ['LINES AUTOMATED', '6 of 14']],
    caption: '$42m of robots returns its cost in about 28 months',
    ch: ['capital-allocation', 'how-the-money-is-made'], beat: 'numbers',
    purpose: 'cumulative savings against the capital spent on automation, one scale \u2014 the payback month is where the line crosses the level.',
    caution: 'Savings as the company states them are a claim, not a result; say whose number it is.' });

  /* ENERGY — Ardent Energy, oil and gas (+8) */
  add('energy', 'figures', 'reserve-bridge', 'walk', { kicker: 'PROVED RESERVES, FY25', unit: 'million barrels of oil equivalent',
    heads: ['OPENING', 'PRODUCED', 'REVISIONS', 'EXTENSIONS', 'BOUGHT', 'CLOSING'], open: 1240, steps: [-118, -46, 71, 18], u: '',
    caption: 'Replaced 75% of what was produced', ch: ['the-numbers', 'risk'], beat: 'numbers',
    purpose: 'proved reserves from opening to closing through production, revisions, extensions and acquisitions \u2014 whether the company is replacing what it pumps.',
    caution: 'Proved reserves only. Revisions for price are not discoveries; call them out separately if they dominate.' });
  add('energy', 'structure', 'reserve-life', 'tracks', { kicker: 'YEARS OF RESERVES LEFT', head: 'At today\u2019s output, the Gulf runs out first',
    valueHead: 'YEARS', scale: [0, 20], ticks: ['0', '5', '10', '15', '20'],
    rows: [['Permian', 'Proved reserves over this year\u2019s output', '14y', 0, 14], ['Gulf of Mexico', 'Two fields, both past their peak', '4y', 0, 4, 'attention'],
      ['Natural gas', 'Held by production, little drilling', '11y', 0, 11, 'subject2']],
    caption: 'Reserve life is proved reserves over annual output', ch: ['risk', 'moat'], beat: 'numbers',
    purpose: 'reserve life by basin \u2014 proved reserves over annual production \u2014 as tracks on one fixed 0\u201320 year scale.',
    caution: 'Proved reserves, current output. Probable reserves lengthen every bar and must not be mixed in.' });
  add('energy', 'figures', 'well-payback', 'payback', { kicker: 'WHAT A WELL COSTS, AND THE PAYBACK',
    legs: ['Cash from the well, cumulative', 'Cost to drill and complete'], level: 9.2, perMonth: 0.52, xAxis: 'MONTHS SINCE FIRST OIL',
    inputs: [['WELL COST', '$9.2m'], ['FIRST-YEAR OUTPUT', '410k boe'], ['AT OIL OF', '$70']],
    caption: 'At $70 oil a new well pays back in about 18 months', ch: ['how-the-money-is-made'], beat: 'numbers',
    purpose: 'cumulative cash from one well against its drilling and completion cost \u2014 the unit economics of shale.',
    caution: 'A straight cumulative line flatters shale, whose output falls fast; the voice-over must say the line is an average.' });
  add('energy', 'charts', 'reinvestment-rate', 'pairs', { kicker: 'CAPEX AGAINST OPERATING CASH FLOW', unit: '$bn per year',
    rows: ['OPERATING CASH FLOW', 'CAPEX', 'REINVESTMENT RATE'], a: [2.1, 3.4, 5.2, 4.6, 4.1, 3.8], b: [1.9, 1.6, 1.8, 2.3, 2.6, 2.7], u: '$bn', d: 1, max: 6,
    verdict: 'More of each dollar goes back into the ground.', caption: 'Reinvestment up from 35% to 71% since FY22',
    ch: ['capital-allocation', 'the-numbers'], beat: 'numbers',
    purpose: 'operating cash flow beside capex for six years, with capex as a share of cash flow underneath \u2014 the reinvestment rate.',
    caution: 'Capex including acquisitions changes the story; state which is shown.' });
  add('energy', 'charts', 'refining-margin', 'spread', { kicker: 'PRODUCT PRICES AGAINST CRUDE', unit: '$ per barrel',
    legs: ['Product basket', 'Crude cost'], a: [108, 112, 104, 96, 94, 92, 90, 88], b: [78, 82, 80, 74, 76, 78, 79, 80], min: 0, max: 120,
    spreadLabel: 'LATEST CRACK', spread: '$8', detail: 'The refining margin has fallen from $30 to $8 a barrel',
    caption: 'The filled gap is the refining margin', ch: ['the-numbers', 'how-the-money-is-made'], beat: 'the-turn',
    purpose: 'the price of refined products against the crude that makes them, one scale, the crack spread filled.',
    caution: 'A published crack spread is a benchmark, not the company\u2019s realised margin; label which.' });
  add('energy', 'charts', 'hedge-coverage', 'ceiling', { kicker: 'HOW MUCH OUTPUT IS HEDGED', unit: 'next 12 months, % of oil output',
    ceilingLabel: '100% \u00b7 FULLY HEDGED', values: [62, 60, 58, 55, 49, 42, 36, 31], detail: 'Hedged near $74; the rest sells at spot',
    caption: 'Half the protection it had two years ago', ch: ['risk', 'guidance-estimates'], beat: 'numbers',
    purpose: 'the share of the next twelve months\u2019 output that is hedged, eight quarters, against a fixed 100% ceiling.',
    caution: 'Hedges have prices; coverage without the strike is half the story. Put the price in the detail line.' });
  add('energy', 'figures', 'cash-return-walk', 'walk', { kicker: 'WHERE THE OPERATING CASH WENT', unit: '$m, FY25',
    heads: ['CASH IN', 'CAPEX', 'DIVIDEND', 'BUYBACKS', 'DEBT', 'LEFT'], open: 3800, steps: [-2700, -620, -400, -80], u: '',
    changeLabel: 'SPENT', caption: 'Almost everything went out again', ch: ['capital-allocation'], beat: 'numbers',
    purpose: 'operating cash flow split across capex, dividends, buybacks and debt repayment, with what was left at the end.',
    caution: 'The ends are levels of cash, not balances; say so. The steps must add up to what was left.' });
  add('energy', 'tables', 'well-vintages', 'cohort', { kicker: 'OUTPUT BY WELL VINTAGE', unit: '% of first-year output',
    head: 'Newer wells fall away faster than the old ones did', cols: ['YEAR 1', 'YEAR 2', 'YEAR 3', 'YEAR 4', 'YEAR 5'],
    rows: [['2020 wells', [100, 62, 48, 40, 35]], ['2021 wells', [100, 58, 44, 37]], ['2022 wells', [100, 55, 41]], ['2023 wells', [100, 51]], ['2024 wells', [100]]],
    caption: 'Year-two output: 62% for 2020 wells, 51% for 2023', ch: ['risk', 'how-we-got-here'], beat: 'the-sheet',
    purpose: 'output of each year\u2019s wells as a share of their first year, one row per vintage \u2014 the decline curve, and whether it is steepening.',
    caution: 'Every cell is relative to that vintage\u2019s own first year, so a row starts at 100% by construction.' });

  /* MATERIALS — Corvane, copper (+8) */
  add('materials', 'figures', 'metal-mix', 'rails', { kicker: 'WHAT THE MINES SELL', headShare: 'SHARE OF FY25 REVENUE',
    rows: [['Copper', 71, 6], ['Gold', 13, 18], ['Molybdenum', 8, -12], ['Silver', 5, 9], ['Zinc', 3, -15]],
    caption: 'Gold by-product is the fastest-growing line', ch: ['how-the-money-is-made'], beat: 'the-sheet',
    purpose: 'revenue by metal: share and growth \u2014 how much of a copper miner is really copper.',
    caution: 'By-product credits are often netted off costs instead; if so, the shares here are gross and say it.' });
  add('materials', 'charts', 'price-vs-cash-cost', 'spread', { kicker: 'COPPER PRICE AGAINST CASH COST', unit: '$ per pound',
    legs: ['Copper price', 'C1 cash cost'], a: [3.9, 4.2, 4.3, 4.1, 4.4, 4.6, 4.5, 4.4], b: [2.1, 2.2, 2.3, 2.4, 2.6, 2.8, 2.9, 3.0], min: 0, max: 5,
    spreadLabel: 'LATEST MARGIN', spread: '$1.40', detail: 'Costs up 43% in two years; the price up 13%',
    caption: 'The price rose; the margin shrank anyway', ch: ['the-numbers', 'risk'], beat: 'the-turn',
    purpose: 'the copper price against the company\u2019s C1 cash cost per pound, eight quarters, the margin filled.',
    caution: 'C1 excludes sustaining capex. For the full cost use all-in sustaining cost, and label it.' });
  add('materials', 'structure', 'mine-life', 'tracks', { kicker: 'YEARS LEFT AT EACH MINE', head: 'Two of three mines close within a decade',
    valueHead: 'YEARS', scale: [0, 30], ticks: ['0', '10', '20', '30'],
    rows: [['Rio Alto', 'Open pit, 61% of output', '8y', 0, 8, 'attention'], ['Kestrel', 'Underground, expanding', '24y', 0, 24],
      ['Ashby', 'Tailings reprocessing', '6y', 0, 6, 'subject2']],
    caption: 'Mine life is reserves over the current mine plan', ch: ['risk', 'moat'], beat: 'numbers',
    purpose: 'remaining life of each mine on one fixed 0\u201330 year scale \u2014 which assets the company has to replace, and when.',
    caution: 'Reserves, not resources. Resources extend every mine and belong in the voice-over, not on the bar.' });
  add('materials', 'charts', 'sustaining-vs-growth-capex', 'pairs', { kicker: 'SUSTAINING AGAINST GROWTH CAPEX', unit: '$m per year',
    rows: ['SUSTAINING', 'GROWTH', 'GROWTH SHARE'], a: [410, 430, 470, 520, 560, 610], b: [520, 610, 340, 180, 120, 90], u: '$m', ratio: 'b/a', max: 700,
    verdict: 'Almost all the spending now just keeps the mines running.', caption: 'Growth capex down from $610m to $90m',
    ch: ['capital-allocation'], beat: 'numbers',
    purpose: 'sustaining capex beside growth capex for six years, with growth as a share of sustaining underneath.',
    caution: 'The split is the company\u2019s own classification, and it is discretionary. Say so.' });
  add('materials', 'figures', 'net-debt-walk', 'walk', { kicker: 'NET DEBT, FY24 TO FY25', unit: '$m',
    heads: ['FY24', 'FREE CASH', 'DIVIDEND', 'PROJECT', 'LEASES', 'FY25'], open: 3200, steps: [-640, 380, 520, 90], u: '$m',
    caption: 'The new project was paid for with debt', ch: ['capital-allocation', 'risk'], beat: 'numbers',
    purpose: 'net debt from one year end to the next through free cash flow, dividends, project spend and leases.',
    caution: 'Free cash flow reduces debt, so it is a negative step here; the voice-over should say which way the bars run.' });
  add('materials', 'charts', 'recovery-rate', 'ceiling', { kicker: 'HOW MUCH METAL IS RECOVERED', unit: 'metal out \u00f7 metal in the ore',
    ceilingLabel: '100% \u00b7 EVERY POUND RECOVERED', values: [89, 89, 88, 87, 86, 85, 84, 83],
    detail: 'Harder ore at depth: more rock for every pound of copper', caption: 'Six points of recovery lost as the pit deepens',
    ch: ['the-numbers', 'risk'], beat: 'numbers',
    purpose: 'plant recovery rate for eight quarters against a fixed 100% ceiling \u2014 an early sign the ore is getting harder.',
    caution: 'Recovery is plant-level; blended figures across mines hide which one is slipping.' });
  add('materials', 'charts', 'shipped-vs-produced', 'b2b', { kicker: 'SHIPMENTS AGAINST PRODUCTION', unit: 'thousand tonnes per quarter',
    legs: ['Shipped', 'Produced'], a: [112, 118, 109, 114, 101, 97, 94, 92], b: [110, 116, 112, 113, 108, 106, 105, 104], max: 140,
    ratioLabel: 'SHIPPED \u00f7 PRODUCED', detail: 'Four quarters under 1.0\u00d7: metal is piling up at the mine',
    caption: 'Under 1.0\u00d7, inventory is building instead of selling', ch: ['the-numbers', 'risk'], beat: 'numbers',
    purpose: 'metal shipped beside metal produced for eight quarters, the ratio under each pair \u2014 whether output is selling.',
    caution: 'Timing of vessel loadings moves single quarters; read four quarters or more.' });
  add('materials', 'figures', 'project-payback', 'payback', { kicker: 'WHAT THE EXPANSION COSTS, AND THE PAYBACK',
    legs: ['Project cash flow, cumulative', 'Project capex'], level: 1400, perMonth: 38, xAxis: 'MONTHS SINCE FIRST PRODUCTION',
    inputs: [['CAPEX', '$1.4bn'], ['EXTRA OUTPUT', '60kt a year'], ['AT COPPER OF', '$4.20']],
    caption: 'Pays back in about three years at today\u2019s copper price', ch: ['capital-allocation', 'valuation'], beat: 'numbers',
    purpose: 'cumulative cash from an expansion project against its capital cost, one scale.',
    caution: 'Projects overrun; if the capex has already been revised, show the latest figure and say it moved.' });

  /* CONSUMER DISCRETIONARY — Larkin, apparel retail (+8) */
  add('consumer-discretionary', 'charts', 'traffic-vs-ticket', 'spread', { kicker: 'TRAFFIC AGAINST TICKET', unit: 'points of same-store sales',
    legs: ['Average ticket', 'Store traffic'], a: [4.1, 4.4, 4.8, 5.2, 5.0, 4.6, 4.2, 3.9], b: [1.2, 0.4, -0.9, -2.1, -3.0, -3.6, -4.1, -4.4], min: -6, max: 8, fill: false,
    spreadLabel: 'SAME-STORE SALES', spread: '\u22120.5%', detail: 'Fewer people through the door; each spends a little more',
    caption: 'Sales held up on price while shoppers stayed away', ch: ['the-numbers', 'how-the-money-is-made'], beat: 'the-turn',
    purpose: 'the two parts of same-store sales \u2014 average ticket and traffic \u2014 for eight quarters on one scale with zero drawn.',
    caution: 'The parts add to same-store sales, so the gap is not filled. Traffic from store counters only.' });
  add('consumer-discretionary', 'figures', 'channel-mix', 'rails', { kicker: 'WHERE THE SALES HAPPEN', headShare: 'SHARE OF FY25 SALES',
    rows: [['Full-price stores', 52, -6], ['Online', 28, 14], ['Outlet stores', 11, 3], ['Wholesale', 7, -18], ['Marketplaces', 2, 20]],
    caption: 'Online is 28% of sales and growing; stores are not', ch: ['how-the-money-is-made'], beat: 'the-sheet',
    purpose: 'sales by channel: share as a bar, growth on a rail centred on zero.',
    caution: 'Buy-online-collect-in-store is counted differently by every retailer; say where it sits.' });
  add('consumer-discretionary', 'charts', 'online-vs-stores', 'pairs', { kicker: 'ONLINE AGAINST STORES', unit: '$bn per year',
    rows: ['STORES', 'ONLINE', 'ONLINE SHARE'], a: [3.9, 4.1, 4.2, 4.0, 3.8, 3.6], b: [0.6, 0.9, 1.0, 1.1, 1.3, 1.4], u: '$bn', d: 1, ratio: 'b/a', max: 5,
    verdict: 'Online grows as fast as the stores shrink.', caption: 'Online share of store sales from 15% to 39%', ch: ['how-we-got-here', 'the-numbers'], beat: 'numbers',
    purpose: 'store sales beside online sales for six years, with online as a share of store sales underneath.',
    caution: 'The ratio is online over stores, not online over total; say which is shown.' });
  add('consumer-discretionary', 'figures', 'store-payback', 'payback', { kicker: 'WHAT A NEW STORE COSTS, AND THE PAYBACK',
    legs: ['Store cash profit, cumulative', 'Cost to open'], level: 2.4, perMonth: 0.075, xAxis: 'MONTHS SINCE OPENING',
    inputs: [['COST TO OPEN', '$2.4m'], ['FIRST-YEAR SALES', '$4.1m'], ['FOUR-WALL MARGIN', '22%']],
    caption: 'A new store earns back its cost in under three years', ch: ['how-the-money-is-made', 'capital-allocation'], beat: 'numbers',
    purpose: 'cumulative four-wall cash profit of a new store against the cost to open it, one scale.',
    caution: 'Four-wall profit leaves out head office and marketing; the voice-over must say it is a best case.' });
  add('consumer-discretionary', 'tables', 'customer-cohorts', 'cohort', { kicker: 'REPEAT CUSTOMERS BY YEAR JOINED', unit: '% of each year\u2019s joiners still buying',
    head: 'Each year\u2019s new customers drift away sooner', cols: ['YEAR 1', 'YEAR 2', 'YEAR 3', 'YEAR 4', 'YEAR 5'],
    rows: [['FY20', [100, 58, 44, 38, 35]], ['FY21', [100, 54, 40, 34]], ['FY22', [100, 49, 35]], ['FY23', [100, 45]], ['FY24', [100]]],
    caption: 'Second-year retention down from 58% to 45%', ch: ['moat', 'how-the-money-is-made'], beat: 'the-sheet',
    purpose: 'loyalty-scheme members still buying in each year after joining, one row per joining year.',
    caution: 'Loyalty members only; they are the retailer\u2019s best customers, not all of them.' });
  add('consumer-discretionary', 'charts', 'full-price-sell-through', 'ceiling', { kicker: 'SOLD AT FULL PRICE', unit: 'share of stock sold before markdown',
    ceilingLabel: '100% \u00b7 NOTHING MARKED DOWN', values: [72, 70, 69, 66, 63, 61, 58, 55],
    detail: 'Nearly half the season now sells on discount', caption: 'Seventeen points more stock marked down in two years',
    ch: ['the-numbers', 'risk'], beat: 'numbers',
    purpose: 'the share of each season\u2019s stock sold before markdown, eight quarters, against a fixed 100% ceiling.',
    caution: 'Sell-through definitions vary; the company\u2019s own figure only, never a third-party estimate.' });
  add('consumer-discretionary', 'figures', 'eps-walk', 'walk', { kicker: 'EARNINGS PER SHARE, FY24 TO FY25', unit: '$ per share',
    heads: ['FY24', 'SALES', 'MARGIN', 'COSTS', 'BUYBACKS', 'FY25'], open: 2.84, steps: [0.12, -0.41, -0.18, 0.09], u: '$', d: 2,
    caption: 'Buybacks hid a fifth of the fall in earnings', ch: ['the-numbers'], beat: 'the-sheet',
    purpose: 'earnings per share from one year to the next through sales, gross margin, costs and the share count.',
    caution: 'The buyback step is a smaller share count, not earnings; the voice-over should say so.' });
  add('consumer-discretionary', 'structure', 'retail-cash-cycle', 'tracks', { kicker: 'CASH CONVERSION CYCLE, FY25', head: 'Stock sits for 142 days before it is paid for',
    valueHead: 'DAYS', scale: [0, 180], ticks: ['0', '30', '60', '90', '120', '150', '180'],
    rows: [['Inventory days', 'Up 21 days on FY24', '186', 0, 180, 'attention'], ['Supplier credit', 'Suppliers are paid on day 44', '44', 0, 44, 'quiet'],
      ['Cash tied up', 'Inventory days less payable days', '142', 44, 180, 'subject2']],
    caption: 'Retail has no receivables: stock days less payable days', ch: ['how-the-money-is-made', 'risk'], beat: 'numbers',
    purpose: 'inventory days against supplier credit on one fixed 0\u2013180 day scale, and the gap the retailer finances.',
    caution: 'Inventory over 180 days is clamped at the edge; the value column carries the true number.' });

  /* CONSUMER STAPLES — Fenwick Foods (+8) */
  add('consumer-staples', 'figures', 'category-mix', 'rails', { kicker: 'WHAT THE COMPANY SELLS', headShare: 'SHARE OF FY25 SALES',
    rows: [['Snacks', 34, 3], ['Breakfast', 23, -4], ['Frozen', 19, -7], ['Pet food', 15, 9], ['Beverages', 9, 1]],
    caption: 'Pet food is the only category growing fast', ch: ['how-the-money-is-made'], beat: 'the-sheet',
    purpose: 'sales by category: share as a bar, growth on a rail centred on zero.',
    caution: 'Categories as the company reports them; organic growth only, so disposals do not read as decline.' });
  add('consumer-staples', 'charts', 'input-cost-vs-price', 'spread', { kicker: 'PRICE AGAINST INPUT COSTS', unit: '% change on a year earlier',
    legs: ['Price and mix', 'Input cost inflation'], a: [9.2, 8.1, 6.4, 4.8, 3.6, 2.9, 2.2, 1.8], b: [11.4, 7.9, 4.2, 1.1, 0.6, 1.9, 3.4, 4.6], min: 0, max: 12,
    spreadLabel: 'LATEST SPREAD', spread: '\u22122.8pt', detail: 'Wheat and packaging are rising again; pricing has run out',
    caption: 'Pricing covered costs for a year; now it does not', ch: ['the-numbers', 'risk'], beat: 'the-turn',
    purpose: 'price realised against input-cost inflation, eight quarters, one scale, the spread filled.',
    caution: 'Input costs are often the company\u2019s own index; name its basis in the caption.' });
  add('consumer-staples', 'charts', 'market-share', 'ceiling', { kicker: 'SHARE OF THE SNACK AISLE', unit: '% of US category sales',
    ceilingLabel: '100% \u00b7 THE WHOLE CATEGORY', values: [31, 31, 30, 30, 29, 29, 28, 27],
    detail: 'Private label took most of the four points lost', caption: 'Four points of share lost in two years',
    ch: ['moat', 'sector-comps'], beat: 'numbers',
    purpose: 'category market share for eight quarters against the whole category as a fixed 100% ceiling.',
    caution: 'Scanner data misses some channels, so it is not total share. Name the data source in the caption.' });
  add('consumer-staples', 'charts', 'ad-spend-vs-sales', 'pairs', { kicker: 'ADVERTISING AGAINST SALES', unit: '$m per year',
    rows: ['SALES', 'ADVERTISING', 'AD \u00f7 SALES'], a: [3810, 3980, 4120, 4210, 4210, 4270], b: [229, 231, 218, 197, 181, 171], u: '$m', max: 4800,
    verdict: 'Margin was protected by cutting what builds the brand.', caption: 'Advertising cut from 6.0% of sales to 4.0%',
    ch: ['capital-allocation', 'moat'], beat: 'numbers',
    purpose: 'sales beside advertising spend for six years, with advertising as a share of sales underneath.',
    caution: 'On one scale the ad bars are small by design. The ratio row carries the story.' });
  add('consumer-staples', 'figures', 'gross-margin-walk', 'walk', { kicker: 'GROSS MARGIN, FY24 TO FY25', unit: 'points \u00b7 axis not from zero',
    heads: ['FY24', 'PRICE', 'INPUTS', 'MIX', 'PRODUCTIVITY', 'FY25'], open: 36.4, steps: [1.9, -2.6, -0.3, 0.8], u: '%', su: 'pt', d: 1, float: true,
    caption: 'Price and productivity nearly covered input costs', ch: ['the-numbers', 'how-the-money-is-made'], beat: 'the-sheet',
    purpose: 'gross margin from one year to the next through price, input costs, mix and productivity. Rates, so the scale floats.',
    caution: 'Steps in points; they must add to the change in margin.' });
  add('consumer-staples', 'charts', 'brand-vs-private-label', 'spread', { kicker: 'BRANDS AGAINST PRIVATE LABEL', unit: 'volume, % change on a year earlier',
    legs: ['Private label volume', 'Branded volume'], a: [2.1, 3.4, 4.8, 5.9, 6.4, 6.8, 7.1, 7.3], b: [-0.4, -1.2, -2.1, -2.8, -3.1, -3.3, -3.0, -2.9], min: -5, max: 10, fill: false,
    spreadLabel: 'LATEST GAP', spread: '10.2pt', detail: 'Shoppers trade down once prices pass a threshold',
    caption: 'Private label has grown every quarter for two years', ch: ['moat', 'risk'], beat: 'the-turn',
    purpose: 'private-label volume growth against branded volume growth in the company\u2019s categories, eight quarters.',
    caution: 'Category volumes, not the company\u2019s own; it is a market read, not a result.' });
  add('consumer-staples', 'structure', 'staples-cash-cycle', 'tracks', { kicker: 'CASH CONVERSION CYCLE, FY25', head: 'Suppliers fund the business for 18 days',
    valueHead: 'DAYS', scale: [0, 120], ticks: ['0', '30', '60', '90', '120'],
    rows: [['Inventory, then receivables', '41 days to sell, 33 more to collect', '74', 0, 74], ['Supplier credit', 'Suppliers are paid on day 92', '92', 0, 92, 'quiet'],
      ['Supplier-funded days', 'Paid after the cash comes in', '18', 74, 92, 'subject2']],
    caption: 'Negative working capital: 41 + 33 \u2212 92 = \u221218 days', ch: ['how-the-money-is-made', 'moat'], beat: 'numbers',
    purpose: 'the operating cycle against supplier credit on one fixed 0\u2013120 day scale \u2014 the staples advantage of being paid before paying.',
    caution: 'Supplier-finance programmes stretch payables; if one exists, it belongs in the caption.' });
  add('consumer-staples', 'charts', 'shipments-vs-consumption', 'b2b', { kicker: 'SHIPMENTS AGAINST CONSUMPTION', unit: 'volume index, Q1 24 = 100',
    legs: ['Shipped to retailers', 'Bought by shoppers'], a: [100, 104, 99, 101, 94, 92, 95, 93], b: [100, 101, 100, 99, 99, 98, 98, 97], max: 120,
    ratioLabel: 'SHIPPED \u00f7 CONSUMED', detail: 'Retailers are running down their stock, not reordering',
    caption: 'Shipping less than shoppers buy means destocking', ch: ['the-numbers', 'guidance-estimates'], beat: 'numbers',
    purpose: 'what the company ships to retailers beside what shoppers buy, eight quarters, with the ratio under each pair.',
    caution: 'Consumption from scanner data covers most but not all channels; say which.' });

  /* HEALTH CARE — Quillon Therapeutics (+8) */
  add('health-care', 'structure', 'trial-timeline', 'tracks', { kicker: 'WHEN THE PIPELINE COULD REPORT', head: 'The next readout is eighteen months away',
    valueHead: 'READOUT', scale: [2025, 2031], ticks: ['2025', '2027', '2029', '2031'],
    rows: [['QT-301, Phase III', 'Heart failure, 4,200 patients', '2027', 2025, 2027], ['QT-214, Phase II', 'Obesity, dose-finding', '2028', 2025, 2028, 'subject2'],
      ['QT-118, filing', 'Expected FDA decision', '2029', 2027, 2029, 'attention']],
    caption: 'Dates are company guidance, and they slip', ch: ['guidance-estimates', 'risk'], beat: 'numbers',
    purpose: 'the pipeline as tracks on one fixed calendar \u2014 each programme from now to its next readout or decision.',
    caution: 'Company-guided dates. A missed date is itself news; if one has slipped, say by how much.' });
  add('health-care', 'charts', 'rnd-vs-revenue', 'pairs', { kicker: 'R&D AGAINST REVENUE', unit: '$bn per year',
    rows: ['REVENUE', 'R&D', 'R&D \u00f7 REVENUE'], a: [5.8, 6.3, 6.9, 7.2, 7.4, 7.3], b: [1.2, 1.3, 1.5, 1.7, 1.9, 2.1], u: '$bn', d: 1, max: 8.5,
    verdict: 'Spending more to replace the drug that is ending.', caption: 'R&D up from 21% of revenue to 29%', ch: ['capital-allocation', 'the-numbers'], beat: 'numbers',
    purpose: 'revenue beside research and development spend for six years, with R&D as a share of revenue underneath.',
    caution: 'Acquired in-process R&D is lumpy and often excluded; say whether it is in.' });
  add('health-care', 'charts', 'net-price-vs-volume', 'spread', { kicker: 'NET PRICE AGAINST VOLUME', unit: 'points of revenue growth',
    legs: ['Volume', 'Net price'], a: [6.2, 6.8, 7.1, 7.4, 7.9, 8.2, 8.6, 8.8], b: [2.1, 1.4, 0.2, -1.1, -2.4, -3.2, -4.1, -4.6], min: -6, max: 10, fill: false,
    spreadLabel: 'REVENUE GROWTH', spread: '+4.2%', detail: 'More patients, paying less each: rebates are rising',
    caption: 'Volume growth is being given back in price', ch: ['the-numbers', 'how-the-money-is-made'], beat: 'the-turn',
    purpose: 'the volume and net-price parts of revenue growth, eight quarters on one scale with zero drawn.',
    caution: 'Net price after rebates, not list price. The two parts add to growth, so the gap is not filled.' });
  add('health-care', 'figures', 'revenue-walk', 'walk', { kicker: 'REVENUE, FY24 TO FY25', unit: '$m',
    heads: ['FY24', 'VELOSTAT', 'ORVANE', 'LAUNCHES', 'FX', 'FY25'], open: 7400, steps: [-420, 310, 90, -80], u: '$m',
    caption: 'Orvane made up three-quarters of Velostat\u2019s fall', ch: ['the-numbers', 'how-the-money-is-made'], beat: 'the-sheet',
    purpose: 'revenue from one year to the next, product by product, so the drug being replaced and its replacements are on one scale.',
    caution: 'Product steps must add to total revenue change; group the tail into one step.' });
  add('health-care', 'charts', 'gross-to-net', 'ceiling', { kicker: 'WHAT IS KEPT OF THE LIST PRICE', unit: 'net sales \u00f7 gross sales at list',
    ceilingLabel: '100% \u00b7 LIST PRICE, NO REBATES', values: [58, 56, 54, 52, 49, 47, 45, 43],
    detail: 'Rebates to insurers take 57 cents of each list-price dollar', caption: 'Fifteen points of list price lost to rebates',
    ch: ['how-the-money-is-made', 'risk'], beat: 'numbers',
    purpose: 'net sales as a share of gross sales at list price, eight quarters, against a fixed 100% ceiling.',
    caution: 'Few companies disclose gross-to-net by product; where it is an estimate, say whose.' });
  add('health-care', 'figures', 'payer-mix', 'rails', { kicker: 'WHO PAYS FOR THE DRUGS', headShare: 'SHARE OF US NET SALES',
    rows: [['Commercial', 44, -3], ['Medicare Part D', 31, 8], ['Medicaid', 14, 5], ['Government, other', 6, 2], ['Cash and other', 5, -2]],
    caption: 'Medicare is growing, and its price talks begin next', ch: ['risk', 'how-the-money-is-made'], beat: 'the-sheet',
    purpose: 'US net sales by payer: share and growth \u2014 which payers the company depends on as pricing policy changes.',
    caution: 'US only. International sales belong on a separate row or plate.' });
  add('health-care', 'tables', 'launch-cohorts', 'cohort', { kicker: 'LAUNCH UPTAKE BY PRODUCT', unit: '% of peak sales forecast',
    head: 'Recent launches are ramping more slowly', cols: ['YEAR 1', 'YEAR 2', 'YEAR 3', 'YEAR 4', 'YEAR 5'],
    rows: [['Velostat', [22, 51, 78, 94, 100]], ['Orvane', [18, 44, 69, 86]], ['Brisa', [12, 31, 48]], ['Tenmar', [9, 22]], ['Selvo', [6]]],
    caption: 'Year-one uptake: 22% for Velostat, 6% for Selvo', ch: ['how-we-got-here', 'risk'], beat: 'the-sheet',
    purpose: 'each launch\u2019s sales as a share of its forecast peak by year since launch, one row per product.',
    caution: 'Peak forecasts are consensus, and they move; state the date of the forecast in the caption.' });
  add('health-care', 'figures', 'launch-payback', 'payback', { kicker: 'WHAT A DRUG COSTS, AND THE PAYBACK',
    legs: ['Contribution, cumulative', 'Development and launch cost'], level: 1900, perMonth: 58, xAxis: 'MONTHS SINCE APPROVAL',
    inputs: [['DEVELOPMENT', '$1.4bn'], ['LAUNCH', '$0.5bn'], ['PEAK SALES', '$1.2bn']],
    caption: 'Orvane earns back its cost in about 33 months', ch: ['how-the-money-is-made', 'valuation'], beat: 'numbers',
    purpose: 'cumulative contribution from one drug against what it cost to develop and launch, one scale.',
    caution: 'Development cost excludes the failures that funded it; the voice-over must say this is one success, not the average.' });

  /* FINANCIALS — Merrow Bank (+8) */
  add('financials', 'figures', 'loan-book-mix', 'rails', { kicker: 'WHAT THE BANK LENDS AGAINST', headShare: 'SHARE OF LOANS',
    rows: [['Commercial property', 31, 4], ['Residential mortgages', 28, 1], ['Business loans', 24, -6], ['Consumer', 11, 9], ['Construction', 6, 17]],
    caption: 'Property is 37% of loans, and construction is growing', ch: ['risk', 'how-the-money-is-made'], beat: 'the-sheet',
    purpose: 'loans by type: share and growth \u2014 where the bank\u2019s credit risk actually sits.',
    caution: 'Gross loans before allowances. Office exposure inside commercial property belongs in the voice-over.' });
  add('financials', 'charts', 'provisions-vs-charge-offs', 'b2b', { kicker: 'PROVISIONS AGAINST CHARGE-OFFS', unit: '$m per quarter',
    legs: ['Provisions set aside', 'Loans written off'], a: [42, 45, 48, 52, 55, 51, 49, 47], b: [28, 31, 36, 41, 49, 53, 57, 61], max: 80,
    ratioLabel: 'PROVISIONS \u00f7 CHARGE-OFFS', detail: 'Now writing off more than it sets aside',
    caption: 'Under 1.0\u00d7, the reserve is being drawn down', ch: ['risk', 'the-numbers'], beat: 'numbers',
    purpose: 'provisions for loan losses beside net charge-offs, eight quarters, the ratio under each pair.',
    caution: 'Net charge-offs after recoveries. A ratio under 1.0\u00d7 can be prudent after an over-reserved year; check the allowance.' });
  add('financials', 'charts', 'loan-to-deposit', 'ceiling', { kicker: 'LOANS AGAINST DEPOSITS', unit: 'loans \u00f7 deposits',
    ceilingLabel: '100% \u00b7 EVERY DEPOSIT LENT OUT', values: [78, 80, 83, 85, 88, 91, 93, 94],
    detail: 'Loan growth has outrun deposits for six quarters', caption: 'Sixteen points closer to lending every deposit',
    ch: ['risk', 'the-numbers'], beat: 'numbers',
    purpose: 'the loan-to-deposit ratio for eight quarters against a fixed 100% line \u2014 how much room the bank has left to lend.',
    caution: 'Banks can run above 100% on wholesale funding; if this one does, the ceiling is not a limit and this is the wrong plate.' });
  add('financials', 'figures', 'capital-walk', 'walk', { kicker: 'CET1 CAPITAL RATIO, FY24 TO FY25', unit: 'points \u00b7 axis not from zero',
    heads: ['FY24', 'EARNINGS', 'DIVIDEND', 'BUYBACK', 'LOAN GROWTH', 'FY25'], open: 12.1, steps: [1.4, -0.6, -0.5, -0.9], u: '%', su: 'pt', d: 1, float: true,
    caption: 'Loan growth used up more capital than the buyback', ch: ['capital-allocation', 'risk'], beat: 'the-sheet',
    purpose: 'the core capital ratio from one year to the next through earnings, dividends, buybacks and risk-weighted asset growth.',
    caution: 'Rates in points, so the scale floats. The regulatory minimum belongs in the voice-over.' });
  add('financials', 'tables', 'loan-vintages', 'cohort', { kicker: 'LOSSES BY YEAR OF LENDING', unit: 'cumulative % written off',
    head: 'Each year\u2019s loans are going bad sooner', cols: ['YEAR 1', 'YEAR 2', 'YEAR 3', 'YEAR 4', 'YEAR 5'], cellUnit: '%',
    rows: [['2020 loans', ['0.2', '0.6', '1.1', '1.4', '1.6']], ['2021 loans', ['0.3', '0.8', '1.4', '1.8']], ['2022 loans', ['0.4', '1.1', '1.9']], ['2023 loans', ['0.6', '1.5']], ['2024 loans', ['0.9']]],
    caption: 'Year-one losses: 0.2% for 2020 loans, 0.9% for 2024', ch: ['risk', 'how-we-got-here'], beat: 'the-sheet',
    purpose: 'cumulative losses on each year\u2019s lending by years since it was written, one row per vintage.',
    caution: 'Needs vintage disclosure, usually only for card or auto books. Never build this from a blended loss rate.' });
  add('financials', 'charts', 'fees-vs-interest', 'pairs', { kicker: 'FEES AGAINST INTEREST INCOME', unit: '$m per year',
    rows: ['NET INTEREST INCOME', 'FEE INCOME', 'FEES \u00f7 INTEREST'], a: [1420, 1380, 1510, 1840, 1760, 1690], b: [610, 650, 620, 590, 600, 620], u: '$m', max: 2100,
    verdict: 'Earnings follow interest rates; fees barely move.', caption: 'Fees are a third of what interest earns',
    ch: ['how-the-money-is-made'], beat: 'numbers',
    purpose: 'net interest income beside fee income for six years, with fees as a share of interest underneath.',
    caution: 'Trading gains are neither; leave them out or name them in the caption.' });
  add('financials', 'structure', 'repricing-gap', 'tracks', { kicker: 'WHEN ASSETS AND DEPOSITS REPRICE', head: 'Deposits reprice two years before the loans do',
    valueHead: 'MONTHS', scale: [0, 60], ticks: ['0', '12', '24', '36', '48', '60'],
    rows: [['Fixed-rate loans', 'Average time to repricing or maturity', '38', 0, 38], ['Interest-bearing deposits', 'Reprice within the year', '9', 0, 9, 'quiet'],
      ['The gap', 'Months the bank pays more before it earns more', '29', 9, 38, 'attention']],
    caption: 'A falling margin is built in until the loans roll over', ch: ['risk', 'how-the-money-is-made'], beat: 'numbers',
    purpose: 'average months until loans and deposits reprice, on one fixed 0\u201360 month scale, with the gap between them.',
    caution: 'Averages hide the tail; if the company gives a repricing table, check that the averages match it.' });
  add('financials', 'charts', 'jaws', 'spread', { kicker: 'INCOME GROWTH AGAINST COST GROWTH', unit: '% change on a year earlier',
    legs: ['Income growth', 'Cost growth'], a: [14.2, 11.8, 8.4, 5.1, 2.2, 0.4, -1.2, -1.9], b: [6.1, 6.4, 6.8, 7.2, 6.9, 6.4, 5.8, 5.1], min: -4, max: 16,
    spreadLabel: 'LATEST JAWS', spread: '\u22127pt', detail: 'Costs still rising 5%, on income that is now falling',
    caption: 'Positive jaws for two years, negative for four quarters', ch: ['the-numbers', 'risk'], beat: 'the-turn',
    purpose: 'income growth against cost growth, eight quarters on one scale with the gap filled \u2014 the jaws bank analysts watch.',
    caution: 'Income and costs on the same adjusted or reported basis; never one of each.' });

  /* COMMUNICATION SERVICES — Brightline, streaming (+8) */
  add('communication-services', 'charts', 'arpu-vs-price', 'spread', { kicker: 'LIST PRICE AGAINST WHAT IS PAID', unit: '% change on a year earlier',
    legs: ['List price change', 'Revenue per member'], a: [9, 9, 12, 12, 12, 10, 10, 10], b: [6.2, 5.8, 7.1, 6.4, 5.2, 3.9, 2.8, 2.1], min: 0, max: 14,
    spreadLabel: 'LATEST GAP', spread: '7.9pt', detail: 'Members are moving to the cheaper tier with adverts',
    caption: 'Price rises are not reaching revenue per member', ch: ['how-the-money-is-made', 'the-numbers'], beat: 'the-turn',
    purpose: 'list-price increases against growth in average revenue per member, eight quarters, the gap filled.',
    caution: 'Revenue per member mixes tiers and countries; say whether it is global or one market.' });
  add('communication-services', 'figures', 'revenue-mix', 'rails', { kicker: 'WHERE THE REVENUE COMES FROM', headShare: 'SHARE OF FY25 REVENUE',
    rows: [['Subscriptions', 78, 2], ['Advertising', 12, 19], ['Licensing', 6, -8], ['Games', 2, 14], ['Merchandise', 2, 5]],
    caption: 'Advertising is small, and it is most of the growth', ch: ['how-the-money-is-made'], beat: 'the-sheet',
    purpose: 'revenue by source: share and growth \u2014 how much of a streamer is still a subscription business.',
    caution: 'Advertising sold on its own tier only; bundled promotions are not advertising revenue.' });
  add('communication-services', 'tables', 'subscriber-cohorts', 'cohort', { kicker: 'MEMBERS STILL SUBSCRIBED', unit: '% of each year\u2019s sign-ups',
    head: 'The pandemic joiners left fastest', cols: ['YEAR 1', 'YEAR 2', 'YEAR 3', 'YEAR 4', 'YEAR 5'],
    rows: [['2020', [71, 49, 40, 35, 32]], ['2021', [66, 45, 37, 33]], ['2022', [68, 48, 41]], ['2023', [72, 53]], ['2024', [74]]],
    caption: 'Latest joiners stay better than the 2020 ones did', ch: ['moat', 'how-we-got-here'], beat: 'the-sheet',
    purpose: 'the share of each year\u2019s sign-ups still subscribed in each following year, one row per sign-up year.',
    caution: 'Rarely disclosed; third-party panel data must be named in the caption and treated as an estimate.' });
  add('communication-services', 'charts', 'monthly-active', 'ceiling', { kicker: 'MEMBERS WHO WATCH EACH MONTH', unit: 'monthly active \u00f7 paying members',
    ceilingLabel: '100% \u00b7 EVERY MEMBER WATCHING', values: [84, 83, 83, 81, 80, 78, 77, 76],
    detail: 'A quarter of members pay and do not watch: the next to cancel', caption: 'Eight points more members paying without watching',
    ch: ['risk', 'moat'], beat: 'numbers',
    purpose: 'the share of paying members who watch in a month, eight quarters, against a fixed 100% ceiling.',
    caution: 'Company-defined activity; a single minute counts for some. Say what active means.' });
  add('communication-services', 'figures', 'content-cash-walk', 'walk', { kicker: 'EBITDA TO FREE CASH FLOW', unit: '$m, FY25',
    heads: ['EBITDA', 'CONTENT GAP', 'CAPEX', 'INTEREST', 'TAX', 'FREE CASH'], open: 2100, steps: [-1380, -210, -340, -90], u: '',
    changeLabel: 'CASH GONE', caption: 'Cash spent on content ran $1.4bn ahead of its cost', ch: ['the-numbers', 'capital-allocation'], beat: 'numbers',
    purpose: 'EBITDA to free cash flow, with the gap between content cash spent and content amortised as its own step.',
    caution: 'The content gap is cash spend minus amortisation; it is the step that makes streaming EBITDA misleading.' });
  add('communication-services', 'figures', 'member-payback', 'payback', { kicker: 'WHAT A MEMBER COSTS, AND THE PAYBACK',
    legs: ['Margin per member, cumulative', 'Cost to acquire'], level: 64, perMonth: 3.1, xAxis: 'MONTHS SINCE SIGN-UP',
    inputs: [['COST TO ACQUIRE', '$64'], ['MONTHLY PRICE', '$11.40'], ['CONTRIBUTION', '27%']],
    caption: 'A new member pays back in about 21 months', ch: ['how-the-money-is-made'], beat: 'numbers',
    purpose: 'cumulative contribution per member against the cost to acquire one, one scale.',
    caution: 'Acquisition cost is marketing over gross adds, an estimate. The median member leaves inside two years, so the voice-over must say payback is at risk.' });
  add('communication-services', 'charts', 'ads-vs-subscriptions', 'pairs', { kicker: 'ADVERTISING AGAINST SUBSCRIPTIONS', unit: '$bn per year',
    rows: ['SUBSCRIPTIONS', 'ADVERTISING', 'ADS \u00f7 SUBS'], a: [5.4, 6.4, 7.0, 7.4, 7.5, 7.5], b: [0.0, 0.1, 0.4, 0.7, 1.0, 1.2], u: '$bn', d: 1, max: 9,
    verdict: 'Subscriptions have stalled; advertising is the growth.', caption: 'Advertising from nothing to 16% of subscriptions',
    ch: ['how-the-money-is-made', 'how-we-got-here'], beat: 'numbers',
    purpose: 'subscription revenue beside advertising revenue for six years, with advertising as a share of subscriptions underneath.',
    caution: 'Advertising on its own tier only; share of subscriptions, not of total revenue.' });
  add('communication-services', 'charts', 'adds-vs-churn', 'b2b', { kicker: 'GROSS ADDS AGAINST CANCELLATIONS', unit: 'million members per quarter',
    legs: ['Gross adds', 'Cancelled'], a: [2.9, 2.6, 2.8, 3.1, 2.4, 2.3, 2.5, 2.4], b: [2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9], max: 4,
    ratioLabel: 'ADDS \u00f7 CANCELLED', detail: 'Four quarters losing more members than it signs',
    caption: 'Under 1.0\u00d7, the member base is shrinking', ch: ['the-numbers', 'risk'], beat: 'numbers',
    purpose: 'gross additions beside cancellations for eight quarters, with the ratio under each pair.',
    caution: 'Needs disclosed gross adds and churn; many services report only net adds.' });

  /* UTILITIES — Calder Power (+8) */
  add('utilities', 'figures', 'rate-base-walk', 'walk', { kicker: 'RATE BASE, FY24 TO FY25', unit: '$bn',
    heads: ['FY24', 'CAPEX', 'DEPRECIATION', 'DEFERRED TAX', 'FY25'], open: 18.4, steps: [3.1, -1.2, -0.3], u: '$bn', d: 1,
    caption: 'Rate base grew 9%, and allowed earnings grow with it', ch: ['how-the-money-is-made', 'the-numbers'], beat: 'numbers',
    purpose: 'the rate base \u2014 the assets the utility is allowed to earn on \u2014 from one year to the next through capex, depreciation and deferred tax.',
    caution: 'Rate base as filed with the regulator, not balance-sheet assets.' });
  add('utilities', 'charts', 'capex-vs-depreciation-utility', 'pairs', { kicker: 'CAPEX AGAINST DEPRECIATION', unit: '$bn per year',
    rows: ['CAPEX', 'DEPRECIATION', 'DEPRECIATION \u00f7 CAPEX'], a: [1.9, 2.2, 2.5, 2.8, 3.0, 3.1], b: [0.9, 0.95, 1.0, 1.05, 1.1, 1.2], u: '$bn', d: 1, max: 3.6,
    verdict: 'Spending over twice what wears out: the rate base grows.', caption: 'Capex is two and a half times depreciation',
    ch: ['capital-allocation', 'how-the-money-is-made'], beat: 'numbers',
    purpose: 'capex beside depreciation for six years; for a regulated utility, capex above depreciation is rate-base growth.',
    caution: 'The reading is the opposite of an industrial\u2019s: here the ratio shows growth, not underinvestment. The voice-over should say so.' });
  add('utilities', 'structure', 'rate-case-calendar', 'tracks', { kicker: 'WHEN EACH STATE RESETS RATES', head: 'Two of three rate cases land next year',
    valueHead: 'DECISION', scale: [2025, 2030], ticks: ['2025', '2026', '2027', '2028', '2029', '2030'],
    rows: [['Ohio, 48% of rate base', 'Filed in March, asking for 10.4%', '2026', 2025, 2026, 'attention'], ['Kentucky, 31%', 'Settled at 9.6% until then', '2028', 2025, 2028],
      ['Indiana, 21%', 'Filing expected next spring', '2026', 2025.5, 2026, 'subject2']],
    caption: 'Rate cases set the return the utility is allowed', ch: ['guidance-estimates', 'risk'], beat: 'numbers',
    purpose: 'the next rate decision in each jurisdiction, as tracks on one fixed calendar, with each state\u2019s share of the rate base.',
    caution: 'Filing and decision dates are regulatory calendars, not company promises; name the docket if one is quoted.' });
  add('utilities', 'figures', 'customer-mix', 'rails', { kicker: 'WHO BUYS THE POWER', headShare: 'SHARE OF FY25 SALES',
    rows: [['Residential', 41, 1], ['Commercial', 29, 3], ['Industrial', 18, -2], ['Data centres', 7, 20], ['Wholesale', 5, -9]],
    caption: 'Data centres are 7% of sales and all of the growth', ch: ['how-the-money-is-made', 'risk'], beat: 'the-sheet',
    purpose: 'electricity sales by customer class: share and growth.',
    caution: 'Weather moves residential growth; use weather-adjusted growth where the company gives it.' });
  add('utilities', 'charts', 'fuel-cost-vs-recovery', 'spread', { kicker: 'FUEL COST AGAINST WHAT RATES RECOVER', unit: '$ per MWh',
    legs: ['Recovered in rates', 'Fuel and power cost'], a: [31, 31, 34, 34, 34, 36, 36, 36], b: [29, 33, 38, 41, 39, 37, 35, 33], min: 0, max: 45,
    spreadLabel: 'LATEST GAP', spread: '+$3', detail: 'Back above cost after a year of under-recovery',
    caption: 'Under-recovered costs become a balance owed by customers', ch: ['the-numbers', 'risk'], beat: 'the-turn',
    purpose: 'the fuel and purchased-power cost per megawatt-hour against what the fuel clause recovers in rates, eight quarters, the gap filled.',
    caution: 'Under-recovery is usually collected later, not lost; the voice-over must say which.' });
  add('utilities', 'charts', 'capacity-factor', 'ceiling', { kicker: 'HOW HARD THE FLEET RUNS', unit: 'output \u00f7 maximum possible output',
    ceilingLabel: '100% \u00b7 RUNNING FLAT OUT', values: [88, 91, 90, 86, 92, 89, 78, 81],
    detail: 'Unit 2 outage in Q3 took eleven points off the nuclear fleet', caption: 'The nuclear fleet ran at 81% last quarter',
    ch: ['the-numbers', 'risk'], beat: 'numbers',
    purpose: 'the nuclear fleet\u2019s capacity factor for eight quarters against a fixed 100% ceiling.',
    caution: 'One fleet per plate; a blended capacity factor across nuclear and wind means nothing.' });
  add('utilities', 'figures', 'eps-walk-utility', 'walk', { kicker: 'EARNINGS PER SHARE, FY24 TO FY25', unit: '$ per share',
    heads: ['FY24', 'RATE BASE', 'WEATHER', 'INTEREST', 'DILUTION', 'FY25'], open: 3.41, steps: [0.31, -0.08, -0.14, -0.06], u: '$', d: 2,
    caption: 'Rate-base growth, eaten by interest costs and new shares', ch: ['the-numbers', 'guidance-estimates'], beat: 'the-sheet',
    purpose: 'earnings per share from one year to the next through rate-base growth, weather, interest and share issuance.',
    caution: 'Weather is not recurring; say whether guidance is weather-normalised.' });
  add('utilities', 'charts', 'debt-vs-equity-funding', 'pairs', { kicker: 'HOW THE CAPEX IS FUNDED', unit: '$bn raised per year',
    rows: ['NEW DEBT', 'NEW EQUITY', 'EQUITY \u00f7 DEBT'], a: [0.9, 1.1, 1.3, 1.6, 1.7, 1.8], b: [0, 0.1, 0.2, 0.4, 0.6, 0.7], u: '$bn', d: 1, max: 2.2,
    verdict: 'New shares now fund more than a third of it.', caption: 'New shares went from nothing to $0.7bn a year',
    ch: ['capital-allocation', 'risk'], beat: 'numbers',
    purpose: 'debt and equity raised each year to fund capex, with equity as a share of debt underneath.',
    caution: 'Equity includes at-the-market programmes and forward sales; say which are included.' });

  /* REAL ESTATE — Holloway, office REIT (+8) */
  add('real-estate', 'structure', 'lease-maturity', 'tracks', { kicker: 'WHEN THE BIG LEASES END', head: 'The largest tenant can leave in two years',
    valueHead: 'EXPIRES', scale: [2025, 2040], ticks: ['2025', '2030', '2035', '2040'],
    rows: [['Aldine Bank, 14% of rent', 'Two towers, no renewal option', '2027', 2025, 2027, 'attention'], ['Crestmoor Law, 8%', 'Renewed last year', '2036', 2025, 2036],
      ['State agencies, 6%', 'Break clause in 2030', '2033', 2025, 2033, 'subject2']],
    caption: 'Lease end dates as filed; break clauses come first', ch: ['risk', 'how-we-got-here'], beat: 'numbers',
    purpose: 'lease terms of the three largest tenants as tracks on one fixed calendar, with each tenant\u2019s share of rent.',
    caution: 'Use the earliest date a tenant can leave, not the last date of the lease.' });
  add('real-estate', 'figures', 'tenant-mix', 'rails', { kicker: 'WHO PAYS THE RENT', headShare: 'SHARE OF FY25 RENT',
    rows: [['Financial services', 36, -8], ['Legal', 18, 2], ['Technology', 16, -14], ['Government', 12, 3], ['Healthcare', 18, 6]],
    caption: 'The two biggest industries are shrinking their space', ch: ['risk', 'how-the-money-is-made'], beat: 'the-sheet',
    purpose: 'rent by tenant industry: share and growth in leased space.',
    caution: 'Growth is in leased square feet, not rent; say so, because rent can rise as space falls.' });
  add('real-estate', 'charts', 'cap-rate-vs-debt-cost', 'spread', { kicker: 'PROPERTY YIELD AGAINST THE COST OF DEBT', unit: '% a year',
    legs: ['Implied cap rate', 'Cost of new debt'], a: [5.4, 5.6, 5.9, 6.3, 6.6, 6.9, 7.1, 7.2], b: [3.9, 4.8, 5.6, 6.2, 6.6, 6.9, 7.3, 7.5], min: 0, max: 9,
    spreadLabel: 'LATEST SPREAD', spread: '\u22120.3pt', detail: 'New debt now costs more than the buildings yield',
    caption: 'Below the line, every refinancing destroys value', ch: ['valuation', 'risk'], beat: 'the-turn',
    purpose: 'the yield the market implies for the buildings against the cost of new debt, eight quarters, the spread filled.',
    caution: 'Implied cap rate is from the share price, not appraisals; label it and say which.' });
  add('real-estate', 'charts', 'leased-vs-expiring', 'b2b', { kicker: 'SPACE LEASED AGAINST SPACE EXPIRING', unit: 'thousand sq ft per quarter',
    legs: ['Newly leased', 'Leases expiring'], a: [410, 380, 350, 340, 310, 290, 280, 270], b: [320, 340, 360, 390, 410, 430, 440, 460], max: 520,
    ratioLabel: 'LEASED \u00f7 EXPIRING', detail: 'Six quarters of leasing short of expiries',
    caption: 'Under 1.0\u00d7, occupancy can only fall', ch: ['the-numbers', 'risk'], beat: 'numbers',
    purpose: 'space newly leased beside leases expiring, eight quarters, with the ratio under each pair.',
    caution: 'New leases only, renewals excluded, or the ratio overstates demand. Say which.' });
  add('real-estate', 'figures', 'nav-walk', 'walk', { kicker: 'NET ASSET VALUE PER SHARE', unit: '$ per share',
    heads: ['FY24', 'EARNINGS', 'DIVIDEND', 'REVALUATION', 'DISPOSALS', 'FY25'], open: 48.20, steps: [2.10, -2.60, -6.40, -0.30], u: '$', d: 2,
    caption: 'The buildings were revalued down by 13%', ch: ['valuation', 'the-numbers'], beat: 'the-sheet',
    purpose: 'net asset value per share from one year to the next through earnings, dividends, revaluations and disposals.',
    caution: 'Revaluations are appraisals, and they lag the market. The share price usually already sits below this NAV.' });
  add('real-estate', 'charts', 'rent-vs-market', 'pairs', { kicker: 'RENT PAID AGAINST MARKET RENT', unit: '$ per sq ft',
    rows: ['IN-PLACE RENT', 'MARKET RENT', 'MARKET \u00f7 IN-PLACE'], a: [48, 49, 50, 51, 52, 53], b: [55, 52, 50, 48, 46, 45], u: '$', d: 0, max: 62,
    verdict: 'Every lease that renews now renews lower.', caption: 'Market rent now 15% below what tenants pay',
    ch: ['risk', 'valuation'], beat: 'numbers',
    purpose: 'average in-place rent beside market rent for six years, with market as a share of in-place underneath \u2014 the mark-to-market.',
    caution: 'Market rent is the company\u2019s or a broker\u2019s estimate; name it.' });
  add('real-estate', 'figures', 'redevelopment-payback', 'payback', { kicker: 'WHAT THE REFIT COSTS, AND THE PAYBACK',
    legs: ['Extra rent, cumulative', 'Redevelopment cost'], level: 180, perMonth: 2.1, xAxis: 'MONTHS SINCE REOPENING',
    inputs: [['COST', '$180m'], ['EXTRA RENT', '$25m a year'], ['PRE-LET', '58%']],
    caption: 'The refit pays back in about seven years', ch: ['capital-allocation', 'valuation'], beat: 'numbers',
    purpose: 'cumulative extra rent from a redevelopment against its cost, one scale. Beyond 36 months the payback is past the plot.',
    caution: 'Extra rent assumes the unlet space leases; pre-let share goes in the inputs, as here.' });
  add('real-estate', 'charts', 'loan-to-value', 'ceiling', { kicker: 'DEBT AGAINST PROPERTY VALUE', unit: 'net debt \u00f7 appraised value',
    ceilingLabel: '100% \u00b7 DEBT EQUALS VALUE', values: [34, 35, 37, 39, 42, 44, 46, 48],
    detail: 'Covenant at 60%; fourteen points of value cuts away', caption: 'Up fourteen points in two years, mostly from write-downs',
    ch: ['risk', 'capital-allocation'], beat: 'numbers',
    purpose: 'loan-to-value for eight quarters against a fixed 100% ceiling \u2014 how close falling values bring the debt to the buildings.',
    caution: 'Appraised values lag; a market-implied LTV is higher. The covenant level belongs in the detail line.' });

  /* ── outputs ──────────────────────────────────────────────────────────── */

  const byType = {};
  E.forEach(x => { byType[x.name] = x; });
  const built = {};
  const get = type => { const x = byType[type]; if (!x) return null; return built[type] || (built[type] = B[x.shape](x.e)); };

  /* plates-r3.js catalogue rows: [sector, family, name, author, args]. */
  const SPEC = E.map(x => [x.sector, x.family, x.name, SHAPE[x.shape][0], SHAPE[x.shape][1](x.e)]);

  /* Rows of shares that do not sum to 100 \u2014 reported, not fixed. */
  function check() {
    const out = [];
    E.forEach(x => { if (x.shape === 'rails') { const s = x.e.rows.reduce((a, r) => a + r[1], 0); if (s !== 100) out.push(x.name + ' shares sum to ' + s); } });
    return out;
  }

  const API = {
    SPEC, check, entries: E,
    text: (type, slots) => { const b = get(type); return b ? Object.assign({}, b.text) : null; },
    data: type => { const b = get(type); return b ? JSON.parse(JSON.stringify(b.data)) : null; },
    roles: () => E.map(x => ({ id: x.family + '/' + x.name, sector: x.sector, ch: x.e.ch, beat: x.e.beat, purpose: x.e.purpose, caution: x.e.caution })),
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = API;
  g.SECTOR_COPY = API;
})(typeof window !== 'undefined' ? window : globalThis);
