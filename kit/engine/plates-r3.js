/* Dennis v2 — plates-r3.js
 *
 * ROUND THREE: ONE SET PER SECTOR. The eleven GICS sectors, each with plates
 * for the question that sector is argued on. Round two covered Information
 * Technology (as software) and Industrials; this adds the other nine.
 *
 *   window.PLATES_R3.install(PLATES, HAND)   // AFTER PLATES_R2.install
 *
 * NO NEW DRAWING WHERE A SHAPE EXISTS. A utility's allowed-against-earned
 * return is the same drawing as an industrial's price against cost: two
 * rates on one scale with the gap filled. So each entry here names a round-two
 * shape (priceCostSpread, walkN, endMarketExposure, rpoCoverage, pairedN,
 * cashConversionCycle) and gives it a type, a family and its args. The type
 * is what content.js and roles.fragment.json key on, so each plate carries its
 * own copy, data, purpose and caution, and a writer sees eighteen distinct
 * plates. The laws in DESIGN.md §5.4 still hold: occupancy and utilisation use
 * rpoCoverage's fixed 100% ceiling because 100% is a real ceiling for them, and
 * every walk between levels is zero-based.
 */

'use strict';

(function (g) {
  function install(P0) {
    ['priceCostSpread', 'walkN', 'endMarketExposure', 'rpoCoverage', 'pairedN', 'cashConversionCycle'].forEach(function (a) {
      if (typeof P0[a] !== 'function') throw new Error('plates-r3.js needs round two\u2019s ' + a + ': install PLATES_R2 first');
    });
    return P0;
  }

  const SPEC = [
    // sector, family, name, shape, args
    ['energy', 'charts', 'breakeven-vs-price', 'priceCostSpread', { quarters: 8 }],
    ['energy', 'figures', 'production-mix', 'endMarketExposure', { rows: 5 }],
    ['materials', 'figures', 'ebitda-walk', 'walkN', { cols: 6 }],
    ['materials', 'charts', 'capacity-utilisation', 'rpoCoverage', { quarters: 8 }],
    ['consumer-discretionary', 'charts', 'inventory-vs-sales', 'priceCostSpread', { quarters: 8 }],
    ['consumer-discretionary', 'figures', 'store-count-bridge', 'walkN', { cols: 5 }],
    ['consumer-staples', 'charts', 'price-vs-volume', 'priceCostSpread', { quarters: 8 }],
    ['consumer-staples', 'figures', 'net-sales-walk', 'walkN', { cols: 6 }],
    ['health-care', 'structure', 'exclusivity-runway', 'cashConversionCycle',
      { ticks: 6, bands: [['band-1'], ['band-2'], ['band-3']], scale: { years: [2025, 2040], why: 'fixed, so every product is read on one calendar' },
        bandNote: 'years of protection on the fixed 2025\u20132040 scale \u2014 historyBand draws it; pass [start, end] as fractions of 15 years, then an ink role' }],
    ['health-care', 'figures', 'product-concentration', 'endMarketExposure', { rows: 5 }],
    ['financials', 'charts', 'nim-spread', 'priceCostSpread', { quarters: 8 }],
    ['financials', 'figures', 'deposit-mix', 'endMarketExposure', { rows: 5 }],
    ['communication-services', 'figures', 'subscriber-bridge', 'walkN', { cols: 5 }],
    ['communication-services', 'charts', 'content-vs-revenue', 'pairedN',
      { years: 6, rows: [{ label: 'row-1', name: 'rev', swatch: 'up' }, { label: 'row-2', name: 'content', swatch: 'down' }, { label: 'ratio-label', name: 'ratio', rule: true }] }],
    ['utilities', 'charts', 'allowed-vs-earned-roe', 'priceCostSpread', { quarters: 8 }],
    ['utilities', 'figures', 'generation-mix', 'endMarketExposure', { rows: 5 }],
    ['real-estate', 'charts', 'occupancy', 'rpoCoverage', { quarters: 8 }],
    ['real-estate', 'figures', 'noi-walk', 'walkN', { cols: 6 }],
  ];

  /* ROUND FOUR — ten per sector. The rows live in sector-copy.js beside their
   * copy, so a plate and its words are one entry. */
  const COPY = (typeof require === 'function') ? require('./sector-copy') : (g.SECTOR_COPY || { SPEC: [] });
  COPY.SPEC.forEach(function (r) { SPEC.push(r); });

  const LIB = SPEC.reduce(function (out, r, i) {
    const args = Object.assign({ type: r[2], family: r[1] }, r[4]);
    return out.concat([
      { dir: r[1], key: r[1] + '/' + r[2] + '-16x9', author: r[3], args: Object.assign({ w: 1920, h: 1080 }, args), seed: 1101 + i * 2 },
      { dir: r[1], key: r[1] + '/' + r[2] + '-9x16', author: r[3], args: Object.assign({ w: 1080, h: 1920 }, args), seed: 1102 + i * 2 },
    ]);
  }, []);

  /* All eleven, so a consumer asks one place. IT and Industrials are round two's. */
  const SECTOR = {
    'energy': [], 'materials': [], 'industrials': ['book-to-bill', 'margin-walk', 'end-market-exposure', 'price-cost-spread', 'cash-conversion-cycle', 'capex-vs-depreciation'],
    'consumer-discretionary': [], 'consumer-staples': [], 'health-care': [], 'financials': [],
    'information-technology': ['arr-bridge', 'nrr-cohorts', 'rule-of-40', 'sbc-vs-buybacks', 'rpo-coverage', 'cac-payback'],
    'communication-services': [], 'utilities': [], 'real-estate': [],
  };
  SPEC.forEach(function (r) { SECTOR[r[0]].push(r[2]); });

  const API = { install: install, LIB: LIB, SECTOR: SECTOR };
  if (typeof module !== 'undefined' && module.exports) module.exports = API;
  g.PLATES_R3 = API;
})(typeof window !== 'undefined' ? window : globalThis);
