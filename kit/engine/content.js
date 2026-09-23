/* Dennis v2 — content.js
 *
 * SAMPLE CONTENT FOR EVERY PLATE, DERIVED FROM THE PLATE'S OWN SLOT TABLE.
 *
 * Not script copy. This is review content: enough real structure that a plate
 * can be judged, generated per FAMILY from the slots each plate publishes
 * rather than hand-written ninety-three times. Hand-writing it would drift the
 * moment a plate's slot table changed, and nobody would notice which plates
 * had gone stale (§8.1).
 *
 * THE ONE RULE: every string is checked against its slot's own `maxChars`
 * before it is returned. A plate that only fits because the words were chosen
 * short is a plate that will break on the first real script, so the budget is
 * enforced here rather than admired in the manifest.
 *
 * Values come from ONE fictional filing — the claims desk, FY19 to FY24 — so
 * a contact sheet of ninety-three plates reads as one story rather than as
 * ninety-three unrelated demos. Coherence is what makes a contact sheet
 * judgeable: a number that appears on two plates is the same number.
 */

'use strict';

/* ── the one story ──────────────────────────────────────────────────────── */

const STORY = {
  periods: ['FY19', 'FY20', 'FY21', 'FY22', 'FY23', 'FY24'],
  quarters: ['Q1 23', 'Q2 23', 'Q3 23', 'Q4 23', 'Q1 24', 'Q2 24', 'Q3 24', 'Q4 24'],
  filed: [1180, 1240, 1310, 1402, 1466, 1511],
  checked: [1102, 1140, 1180, 1204, 1188, 1388],
  waived: [78, 100, 130, 198, 278, 123],
  revenue: [412, 438, 451, 470, 489, 508],
  reserve: [96, 94, 89, 81, 62, 40],
  headcount: [1240, 1198, 1150, 1102, 981, 902],
  /* Rows seven and eight, so the 7- and 8-row sheets stop repeating Revenue
   * and Claims filed at the bottom. FY23 and FY24 agree with growth-and-margin. */
  expense: [96, 102, 110, 119, 131, 164],
  opProfit: [82, 88, 92, 101, 108, 93],
  peers: [['OURS', 91.9, 2.1], ['ALPH', 74.0, -1.4], ['BETA', 68.5, 0.3], ['GAMM', 62.2, -3.8], ['DELT', 59.7, 0.9], ['EPSI', 55.1, -0.6]],
  regions: [['North', 489], ['Central', 402], ['South', 381], ['Coastal', 152], ['Islands', 87]],
  steps: [['Reserve release', -18.0], ['Claims paid', -12.5], ['Legal', -4.5], ['Undisclosed', -5.0], ['Recovered', 0.0]],
  said: [
    ['\u201cBest quarter yet\u201d', 'Revenue fell 4%'],
    ['\u201cNo material exposure\u201d', '$40m written down'],
    ['\u201cFully staffed\u201d', '11% vacancy at year end'],
    ['\u201cOne-off in nature\u201d', 'Third year running'],
    ['\u201cNo change in policy\u201d', 'Policy rewritten in March'],
    ['\u201cThe second read is standard\u201d', '123 claims had none'],
  ],
  lines: [
    'Claims desk, FY24 as filed',
    'The other 123 were signed off on a summary',
    'Four peers, same disclosure year',
    'Kept because somebody kept it',
    'Annual report, p.41 \u2014 emphasis theirs',
    'File, check, restate, repeat',
  ],
};

/* ── budget enforcement ─────────────────────────────────────────────────── */

/* Shortening is deliberate and ordered: drop a trailing clause, then an
 * article, then truncate. A plate that needs the truncation branch is telling
 * you its slot is too small for the role, which is worth knowing. */
/* THE BUDGET A SLOT DOES NOT PUBLISH. Only some slots carry `maxChars`; the
 * rest carried none, so `fit()` waved everything through and 68 strings
 * rendered wider than their own boxes — a quote at 5.97x its slot, series
 * labels at 2.3x. A character budget that is absent is not a budget of
 * infinity: the box and the role size already imply one, so derive it.
 *
 * WHERE THE ADVANCE COMES FROM — CORRECTED AT REBUILD-15, and the correction
 * matters more than the original fix. `engine/budget.js` is the kit's
 * authority on this and I wrote a second model without reading it. It derives
 * a per-slot capacity from the box using the SHIPPED FONTS' OWN `hmtx`
 * advances — Courier Prime exactly 0.5996 em for every glyph, Archivo Narrow
 * per character class and per weight (its lowercase runs 0.31 em) plus
 * tracking and a safety factor — and `Plate.manifest()` runs it over every
 * plate so a re-emit cannot drift.
 *
 * My replacement used a flat 0.54 em. Measured across 1,778 slots that is
 * tighter than the real metric on 330 of them and looser on 490.
 *
 * **So the earlier claim that "314 slots publish a budget wider than their own
 * geometry" was wrong.** It compared the kit's real-metric number against my
 * estimate and blamed the kit. `structure/sensitivity` promising 7 characters
 * in an 88px box is not a defect: at role size 25 with Archivo Narrow's actual
 * advances, seven characters fit. The published number was right and the
 * measurement was wrong.
 *
 * The rule now: **a published `maxChars` is authoritative.** Derive one only
 * when a slot carries none, and derive it with budget.js's own `perChar` when
 * that module has been handed over. The flat constant survives as a last
 * resort for a role that is not in the type table at all. */
let METRICS = null;
function useMetrics(B) { METRICS = B && B.perChar ? B : null; return CONTENT; }
function perChar(roleName, role) {
  if (METRICS) { try { return METRICS.perChar(roleName || '', role || {}); } catch (e) { /* fall through */ } }
  return (role && role.font) === 'Courier Prime' ? 0.5996 : 0.54;
}
/* How far the renderer may scale type down to make a string fit its box.
 * Below about half, a label stops matching the plate's type hierarchy and
 * starts looking like a mistake; above it, truncation kicks in instead. */
const SHRINK_FLOOR = 0.55;

/* The size a slot's type must actually render at for this string to fit.
 * Both the review surface and the exporter call this, so a plate looks the
 * same in review as it does in the delivered file. */
function fittedSize(slot, roles, text) {
  const R = (roles && roles[slot.role]) || {};
  const size = R.size || Math.max(14, Math.round(slot.h * 0.6));
  const lines = slot.wraps || (slot.h > size * 1.9 ? Math.floor(slot.h / (size * 1.25)) : 1);
  const need = (String(text).length * perChar(slot.role, Object.assign({ size: size }, R))) / lines;
  if (need <= 0) return size;
  return Math.max(Math.round(size * SHRINK_FLOOR), Math.min(size, Math.floor(slot.w / need)));
}

function budgetOf(slot, roles) {
  if (!slot) return null;
  const R = (roles && roles[slot.role]) || {};
  const size = R.size || Math.max(14, Math.round(slot.h * 0.6));
  const lines = slot.wraps || (slot.h > size * 1.9 ? Math.floor(slot.h / (size * 1.25)) : 1);
  /* Floor of 2, not 4. A four-character floor still overflowed nine slots
   * whose boxes cannot hold four characters at their own role size — the
   * budget was rounding UP into an overflow. If a slot cannot hold two
   * characters it cannot hold type at all, and the caller drops it. */
  /* SHRINK THE TYPE BEFORE CUTTING THE WORDS. The budget used to be computed
   * at the role's full size, so "Filed" in a narrow column became a giant
   * "F…" — a five-letter label destroyed to protect a font size. The renderer
   * is allowed to scale a slot's type down to SHRINK_FLOOR of its role size,
   * so the budget is computed at that floor and truncation becomes the last
   * resort it should always have been, for genuinely long strings only. */
  const pc = perChar(slot.role, Object.assign({ size: size }, R));
  const derived = Math.max(2, Math.floor((slot.w / (size * SHRINK_FLOOR * pc)) * lines));
  /* The published budget wins where it exists, because budget.js measured it
   * off this box with the real face. The derived number is only for slots that
   * publish none, and it is computed at the shrink floor so truncation stays
   * the last resort rather than the first. */
  return slot.maxChars ? Math.min(slot.maxChars, derived) : derived;
}

function fit(text, slot, roles) {
  const max = slot && budgetOf(slot, roles);
  let s = String(text);
  if (!max || s.length <= max) return s;
  const cut = s.lastIndexOf(',');
  if (cut > 0 && cut <= max) return s.slice(0, cut);
  s = s.replace(/\b(the|a|an|of|and) /gi, '').trim();
  if (s.length <= max) return s;
  return s.slice(0, Math.max(1, max - 1)).trimEnd() + '\u2026';
}

const money = v => (v < 0 ? '\u2212' : '') + '$' + Math.abs(v).toFixed(1) + 'm';
const pct = v => (v > 0 ? '+' : v < 0 ? '\u2212' : '') + Math.abs(v).toFixed(1) + '%';
const thou = v => v.toLocaleString('en-US');

/* MEASURES — the thing a plate is actually about. Each carries its value, its
 * label and its unit together, because the first cut handed every measure
 * slot the same number (`checked[5]`, 1,388) and every label the same string:
 * nineteen figures rendered as nineteen copies of one plate. A plate looked
 * simple because the CONTENT was repeating, not because the drawing was thin.
 *
 * Indexed by slot position, so a compare plate gets two different things to
 * compare and a label never sits above a number from a different row. */
const MEASURES = [
  { label: 'Claims checked', value: 1388, unit: 'of 1,511 filed', delta: +16.8, fmt: 'count' },
  { label: 'Reserve', value: 40, unit: '$m, year end', delta: -35.5, fmt: 'money' },
  { label: 'Claims waived', value: 123, unit: 'no second read', delta: -55.8, fmt: 'count' },
  { label: 'Revenue', value: 508, unit: '$m', delta: +3.9, fmt: 'money' },
  { label: 'Headcount', value: 902, unit: 'at year end', delta: -8.1, fmt: 'count' },
  { label: 'Days to close', value: 41, unit: 'median', delta: +12.0, fmt: 'count' },
  { label: 'Escalated', value: 41, unit: 'to legal', delta: +2.5, fmt: 'count' },
  { label: 'Written off', value: 62, unit: '$m', delta: -21.4, fmt: 'money' },
];
/* Each plate leads with a DIFFERENT measure. A plate with one figure slot
 * always asks for position 0, so without an offset every big-number in the
 * kit says the same thing and a contact sheet reads as one plate printed
 * nineteen times. The offset is derived from the key, so it is stable across
 * runs (the same plate always shows the same measure) but spread across the
 * set. Each plate is still about ONE coherent measure with its own label. */
let MEASURE_OFFSET = 0;
function keyOffset(key) {
  let h = 0;
  for (let i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) >>> 0;
  return h % MEASURES.length;
}
const measure = n => MEASURES[(n + MEASURE_OFFSET) % MEASURES.length];
const mval = m => (m.fmt === 'money' ? '$' + m.value + 'm' : thou(m.value));

/* ── per-role defaults ──────────────────────────────────────────────────────
 *
 * A role is the same job on every plate — that is what makes a role a role —
 * so most slots can be filled by role alone, and a family only overrides where
 * it genuinely differs. */
function byRole(role, i, slot) {
  const P = STORY.periods, n = i || 0;
  switch (role) {
    case 'kicker': return 'CLAIMS DESK \u00b7 FY24 AS FILED';
    case 'unit': return 'claims, unless stated';
    case 'caption': return STORY.lines[n % STORY.lines.length];
    /* A label names the measure beside it. Pulling labels from one list and
     * values from another is how "Reserve release" ended up over 1,388. */
    case 'label': case 'item': return measure(n).label;
    case 'stepLabel': return STORY.steps[n % STORY.steps.length][0];
    case 'period': return P[n % P.length];
    case 'huge': case 'value': case 'end': return mval(measure(n));
    case 'amount': case 'cell': return thou(STORY.filed[n % 6]);
    case 'metric': return measure(n).label;
    case 'then': return thou(STORY.checked[0]);
    case 'now': return thou(STORY.checked[5]);
    case 'moment': return n === 0 ? P[0] : P[5];
    case 'ticker': case 'tickerSubject': return STORY.peers[n % STORY.peers.length][0];
    case 'move': return pct(STORY.peers[n % STORY.peers.length][2]);
    case 'fwd': return STORY.peers[n % STORY.peers.length][1].toFixed(1);
    case 'rail': return n === 0 ? 'SAID' : 'HAPPENED';
    case 'axis': case 'tick': return String(Math.round((5 - (n || 0)) * 5));
    case 'head': return 'CLAIMS DESK';
    case 'total': return thou(STORY.waived[5]);
    case 'foot': case 'source': return 'Kept because somebody kept it';
    case 'body': case 'quote': case 'statement': return '\u201cNobody asked where the other nine went.\u201d';
    case 'attribution': return 'Internal memo';
    case 'detail': case 'note': case 'endLabel': return measure(n).unit;
    case 'media': return '';
    case 'trough': return thou(Math.min.apply(null, STORY.checked));
    /* The long tail. Every one of these turned up in the coverage pass rather
     * than being guessed at — the plates were asked what roles they publish
     * and this is the answer, which is why the list looks arbitrary and is
     * not. `figure` alone accounts for 121 slots across four families. */
    case 'figure': case 'big': case 'subtotal': case 'median': return mval(measure(n));
    case 'delta': return pct(measure(n).delta);
    case 'date': case 'year': return P[n % P.length];
    case 'headline': case 'title': return STORY.said[n % STORY.said.length][1];
    case 'step': case 'node': case 'waypoint': return ['File', 'Check', 'Restate', 'Repeat', 'Escalate'][n % 5];
    case 'who': case 'subject': return ['Claims desk', 'Audit', 'Reserving', 'Legal', 'Board'][n % 5];
    case 'segLabel': case 'tileLabel': case 'barLabel': case 'group': case 'column': case 'row':
      return STORY.regions[n % STORY.regions.length][0];
    case 'segValue': return pct(STORY.peers[n % STORY.peers.length][2]);
    case 'series': return ['Filed', 'Checked', 'Waived'][n % 3];
    case 'refLabel': case 'anchorLabel': case 'axisTitle': case 'deltaLabel': case 'tag':
      return ['as filed', 'checked', 'restated', 'chg'][n % 4];
    case 'link': case 'sub': case 'line': case 'entry': return 'restated in March';
    case 'check': return ['✓', '✗'][n % 2];
    case 'band': return pct(STORY.peers[n % STORY.peers.length][2]);
    case 'phrase': case 'term': case 'example':
      return ['“one-off”', '“non-recurring”', '“normalised”', '“adjusted”'][n % 4];
    case 'hook': return 'They checked 1,388 of 1,511.';
    case 'tagline': return 'reads the filings so you do not have to';
    case 'strike': case 'demand': case 'marker': return thou(STORY.filed[n % 6]);
    case 'hand': return 'and the other nine';
    case 'outcome': return 'Third year running';
    default: return null;
  }
}

/* ── per-family overrides ───────────────────────────────────────────────── */

const FAMILY = {
  structure(slots, key) {
    const out = {};
    const pairs = STORY.said;
    Object.keys(slots).forEach(name => {
      const m = name.match(/^(said|happened)-(\d+)$/);
      if (m) out[name] = pairs[(+m[2] - 1) % pairs.length][m[1] === 'said' ? 0 : 1];
      if (/^rail-said$/.test(name)) out[name] = 'SAID';
      if (/^rail-happened$/.test(name)) out[name] = 'HAPPENED';
    });
    if (slots.kicker) out.kicker = 'WHAT WAS SAID, AND WHAT HAPPENED';
    return out;
  },
  tables(slots) {
    const out = {}, rows = [
      ['Revenue', STORY.revenue], ['Claims filed', STORY.filed], ['Checked', STORY.checked],
      ['Waived', STORY.waived], ['Reserve', STORY.reserve], ['Headcount', STORY.headcount],
      ['Claims expense', STORY.expense], ['Operating profit', STORY.opProfit],
    ];
    Object.keys(slots).forEach(name => {
      let m = name.match(/^label-(\d+)$/);
      if (m) out[name] = rows[(+m[1] - 1) % rows.length][0];
      m = name.match(/^cell-(\d+)-(\d+)$/);
      if (m) { const row = rows[(+m[1] - 1) % rows.length][1]; out[name] = thou(row[(+m[2] - 1) % row.length]); }
      m = name.match(/^head-(\d+)$/);
      if (m) out[name] = STORY.periods[(+m[1] - 1) % 6];
    });
    /* The sparkline column header names the SPAN the spark covers, not a
     * year. It fell through the numbered-head pattern to the generic period
     * list and came back "FY19", which reads as a seventh year column sitting
     * beside FY19 itself. */
    if (slots['head-spark']) {
      const p = STORY.periods;
      out['head-spark'] = p[0] + '\u2013' + p[p.length - 1].replace(/^FY/, '');
    }
    if (slots.unit) out.unit = '$m and counts, as filed';
    return out;
  },
  peers(slots) {
    const out = {};
    Object.keys(slots).forEach(name => {
      const m = name.match(/^(ticker|move|fwd)-(\d+)$/);
      if (!m) return;
      const p = STORY.peers[(+m[2] - 1) % STORY.peers.length];
      out[name] = m[1] === 'ticker' ? p[0] : m[1] === 'move' ? p[1].toFixed(1) : pct(p[2]);
    });
    if (slots['head-move']) out['head-move'] = 'FY24';
    if (slots['head-fwd']) out['head-fwd'] = 'chg';
    if (slots.unit) out.unit = 'claims checked, % of filed';
    return out;
  },
  figures(slots, key) {
    const out = {};
    if (/waterfall/.test(key)) {
      Object.keys(slots).forEach(name => {
        const m = name.match(/^label-(\d+)$/);
        if (m) out[name] = STORY.steps[(+m[1] - 1) % STORY.steps.length][0];
      });
      if (slots.kicker) out.kicker = 'WHERE THE $40m WENT';
      if (slots.unit) out.unit = '$m';
      if (slots['total-label']) out['total-label'] = 'Opening';
      if (slots['remainder-label']) out['remainder-label'] = 'Closing';
      if (slots.total) out.total = '40.0';
      if (slots.remainder) out.remainder = '0.0';
    }
    if (/by-region/.test(key)) {
      Object.keys(slots).forEach(name => {
        let m = name.match(/^label-(\d+)$/);
        if (m) out[name] = STORY.regions[(+m[1] - 1) % STORY.regions.length][0];
        m = name.match(/^value-(\d+)$/);
        if (m) out[name] = thou(STORY.regions[(+m[1] - 1) % STORY.regions.length][1]);
      });
    }
    if (/big-fraction/.test(key)) { if (slots.value) out.value = '1,388'; if (slots.of) out.of = '1,511'; }
    /* A COMPARE PLATE MUST COMPARE TWO DIFFERENT THINGS. The generic path gave
     * both sides the same measure, which is the most confident way to render
     * a chart that says nothing. */
    if (/compare/.test(key)) {
      const pair = [MEASURES[0], MEASURES[2]];
      let side = 0;
      Object.keys(slots).forEach(name => {
        const m2 = name.match(/^(figure|value|big|huge)-?(\d*)$/);
        if (!m2) return;
        const M2 = pair[(m2[2] ? +m2[2] - 1 : side++) % 2];
        out[name] = mval(M2);
        const lab = name.replace(/^(figure|value|big|huge)/, 'label');
        if (slots[lab]) out[lab] = M2.label;
        const det = name.replace(/^(figure|value|big|huge)/, 'detail');
        if (slots[det]) out[det] = M2.unit;
      });
      if (slots.kicker) out.kicker = 'CHECKED AGAINST WAIVED';
    }
    return out;
  },
  charts(slots) {
    const out = {};
    /* Eight columns are quarters, six are years. Labelling eight columns from
     * a six-year list repeated FY19 and FY20 at the end of the axis. */
    const cols = Object.keys(slots).filter(n => /^(bar|point)-\d+$/.test(n)).length;
    const heads = cols > 6 ? STORY.quarters : STORY.periods;
    Object.keys(slots).forEach(name => {
      let m = name.match(/^head-(\d+)$/);
      if (m) out[name] = heads[(+m[1] - 1) % heads.length];
      m = name.match(/^value-(\d+)$/);
      if (m) out[name] = (STORY.checked[(+m[1] - 1) % 6] / 100).toFixed(1);
      /* y-1 IS THE BOTTOM TICK. The slots run bottom-to-top (y-1 at y=884,
       * y-5 at y=196) and this was counting down, so every chart in the kit
       * had 20 at the baseline and 4 at the ceiling — an inverted axis under
       * a correctly drawn series. */
      m = name.match(/^y-(\d+)$/);
      if (m) out[name] = String((+m[1] - 1) * 5);
    });
    if (slots.unit) out.unit = 'claims checked, hundreds';
    return out;
  },
  cycles(slots) {
    const out = {};
    Object.keys(slots).forEach(name => {
      const m = name.match(/^head-(\d+)$/);
      if (m) out[name] = STORY.periods[(+m[1] - 1) % 6];
    });
    if (slots.metric) out.metric = 'Claims checked';
    if (slots['then-date']) out['then-date'] = 'FY19';
    if (slots['then-value']) out['then-value'] = '1,102';
    if (slots['now-date']) out['now-date'] = 'FY24';
    if (slots['now-value']) out['now-value'] = '1,388';
    return out;
  },
  paper(slots) {
    const out = {}, items = [['Received', 1511], ['Checked', 1388], ['Waived', 123], ['Reopened', 0],
      ['Escalated', 41], ['Closed', 1347], ['Pending', 164], ['Written off', 62]];
    Object.keys(slots).forEach(name => {
      let m = name.match(/^label-(\d+)$/);
      if (m) out[name] = items[(+m[1] - 1) % items.length][0];
      m = name.match(/^line-(\d+)$/);
      if (m) out[name] = thou(items[(+m[1] - 1) % items.length][1]);
    });
    if (slots.head) out.head = 'CLAIMS DESK';
    if (slots.takings) out.takings = '1,511';
    if (slots.left) out.left = '123';
    return out;
  },
  annotations() { return {}; },
};

/* ── round-one shorts content ──────────────────────────────────────────────
 *
 * A SECOND STORY, because the shorts plates are a different editorial world.
 * The claims-desk filing drives the long-form library and reads correctly
 * there; poured into a wire ticker or a print-vs-consensus it produced
 * "Kept because somebody kept it" as a newswire source and left the reported
 * figure blank. Sample content has to be shaped like the real thing or a plate
 * only looks filled.
 *
 * One story again, so a shorts contact sheet reads as one upload: a single
 * fictional issuer, its release, the print, and the session that followed.
 * Every string is written near its budget rather than short — a plate that
 * fits only because the sample was chosen short breaks on the first script.
 *
 * Keyed on `manifest.type`, which every author sets, so a plate gets its copy
 * without content.js knowing which file drew it. */
const WIRE = [
  ['07:02', 'Claims desk suspends second review', 'Reuters'],
  ['08:14', 'Company says backlog is “temporary”', 'Bloomberg'],
  ['09:31', 'Regulator asks for the waiver list', 'Dow Jones'],
  ['11:47', 'Two directors sold into the bounce', 'FT Alphaville'],
  ['14:02', 'Filing confirms 123 claims unreviewed', 'Company filing'],
];

const R1 = {
  'line-dense': () => ({ 'head-1': 'Jan 24', 'head-2': 'May 24', 'head-3': 'Sep 24', 'head-4': 'Dec 24',
    'mark-high': 'HIGH 13.4', 'mark-low': 'LOW 9.6', 'mark-last': '', 'value-last': '10.1' }),
  'press-release': () => ({
    source: 'MERIDIAN CLAIMS GROUP',
    date: '14 Feb, 14:02 ET',
    headline: 'Meridian confirms 123 claims closed without a second review',
    body: 'The Company confirms that 123 claims were closed following a single '
      + 'assessment. Management does not expect a material impact on reserves.',
    caption: 'Release, p.1 — emphasis ours',
  }),
  'wire-strip-3': (s) => wire(s, 3),
  'wire-strip-5': (s) => wire(s, 5),
  'before-after': () => ({
    kicker: 'WHAT WAS GUIDED, AND WHAT WAS FILED',
    'label-1': 'GUIDED IN NOVEMBER',
    'body-1': '“Every claim gets a second read before it closes.”',
    delta: '123 did not',
    'label-2': 'FILED IN FEBRUARY',
    'body-2': '123 claims closed on a single assessment, worth $40m.',
    caption: 'Guidance call, 9 Nov · 10-K filed 14 Feb',
  }),
  'move-on-the-day-up': () => ({
    kicker: 'MERIDIAN \u00b7 THE DAY AFTER', value: '+6.2%', label: 'Half of the fall back by the close',
    unit: 'intraday, from the prior close', caption: 'A rebound on no news, on a third of the volume' }),
  'move-on-the-day': () => ({
    kicker: 'MERIDIAN · REACTION TO THE FILING',
    value: '−18.4%',
    label: 'worst session since the 2021 restatement',
    unit: 'intraday, from the prior close',
    caption: 'Filed 14:02 ET · the move began at 14:04',
  }),
  'print-vs-consensus': () => ({
    kicker: 'MERIDIAN · Q4 EARNINGS',
    label: 'Earnings per share, reported against consensus',
    reported: '$1.12',
    'expected-label': 'CONSENSUS',
    expected: '$1.31',
    'delta-label': 'MISS',
    delta: '−14.5%',
    caption: 'Eleven analysts, as of the day before the print',
  }),
  'quarter-bars-8q': (s) => {
    const out = { kicker: 'CLAIMS CLOSED PER QUARTER', unit: 'hundreds of claims',
      caption: 'The last column is the quarter just filed' };
    const heads = ['Q1 23', 'Q2 23', 'Q3 23', 'Q4 23', 'Q1 24', 'Q2 24', 'Q3 24', 'Q4 24'];
    const vals = ['11.0', '11.4', '11.8', '12.0', '11.9', '13.2', '13.6', '13.9'];
    heads.forEach((h, i) => { if (s['head-' + (i + 1)]) out['head-' + (i + 1)] = h; });
    vals.forEach((v, i) => { if (s['value-' + (i + 1)]) out['value-' + (i + 1)] = v; });
    return out;
  },
  'three-lines': (s) => {
    const rows = [['Revenue', '$508m', '$489m', '+3.9%'],
      ['Operating margin', '18.4%', '22.1%', '−3.7pt'],
      ['Earnings per share', '$1.12', '$1.31', '−14.5%']];
    const out = { kicker: 'Q4 AGAINST THE SAME QUARTER LAST YEAR',
      'head-1': 'THIS QUARTER', 'head-2': 'YEAR AGO',
      caption: 'As reported · margin in points, the rest as percentages' };
    rows.forEach((r, i) => {
      out['label-' + (i + 1)] = r[0];
      out['cell-' + (i + 1) + '-1'] = r[1];
      out['cell-' + (i + 1) + '-2'] = r[2];
      out['delta-' + (i + 1)] = r[3];
    });
    return out;
  },
  'guidance-raise-cut': () => ({
    kicker: 'MERIDIAN · FULL-YEAR GUIDANCE',
    head: 'Guidance cut for the second time this year',
    'row-axis': 'EPS, FULL YEAR',
    'label-1': 'PREVIOUS RANGE',
    'figure-1': '$4.80–5.20',
    'label-2': 'NEW RANGE',
    'figure-2': '$4.10–4.40',
    caption: 'Both ranges as the company gave them · consensus $5.05',
  }),
  intraday: (s) => {
    const out = { kicker: 'MERIDIAN · 14 FEBRUARY', unit: 'price, one session',
      figure: '−18.4%',
      'event-label': 'Filing hits the wire, 14:02',
      caption: 'The dashed reference is the prior close' };
    ['09:30', '11:00', '13:00', '15:00'].forEach((t, i) => {
      const k = 'head-' + (i * 2 + 1); if (s[k]) out[k] = t;
    });
    return out;
  },
  '52-week-position': () => ({
    kicker: 'WHERE THE PRICE SITS IN ITS OWN RANGE',
    'label-high': '52-WEEK HIGH',
    'figure-high': '$74.10',
    'label-now': 'AFTER THE FILING',
    now: '$31.80',
    'label-low': '52-WEEK LOW',
    'figure-low': '$29.40',
    caption: 'Eleven per cent above the low; at the high in October',
  }),

  /* ── the long side ────────────────────────────────────────────────────────
   * Same issuer as the shorts, so the whole round reads as one company rather
   * than two demos. Written near budget, not short. */
  'filing-page': () => ({
    kicker: 'THE FILING, PAGE 41',
    docref: '10-K, filed 14 Feb',
    passage: 'Certain claims were closed following a single assessment.',
    note: 'That sentence is the entire disclosure. It does not say how many.',
    caption: 'Reading window ours \u00b7 the rest of the page is as filed',
  }),
  'footnote-pull': () => ({
    kicker: 'WHAT THE FOOTNOTE SAYS',
    parent: 'Reserves are reviewed at each period end and adjusted as required.\u2074',
    'fn-marker': '4',
    footnote: 'Of the claims closed in the period, 123 were not subject to the '
      + 'second assessment described in the Group’s stated policy.',
    docref: '10-K, note 4 to the accounts',
    caption: 'The number appears once, in a footnote, on page 41',
  }),
  'year-on-year-diff': () => ({
    kicker: 'THE SAME PARAGRAPH, TWO YEARS APART',
    'year-1': 'FY23',
    'para-1': 'Every claim is subject to a second assessment before closure. '
      + 'Management reviews the reserve at each period end and adjusts it as required.',
    'year-2': 'FY24',
    'para-2': 'Claims are subject to assessment before closure. Management reviews '
      + 'the reserve at each period end and adjusts it as required.',
    verdict: 'One word went: \u201csecond\u201d. Nothing else changed.',
    caption: 'FY23 10-K p.38 against FY24 10-K p.41',
  }),
  'growth-and-margin': function (s) {
    var rows = [['Revenue', '$508m', '$489m', '+3.9%', '\u2014'],
      ['Gross profit', '$221m', '$226m', '\u22122.2%', '\u22122.7pt'],
      ['Operating profit', '$93m', '$108m', '\u221213.9%', '\u22123.7pt'],
      ['Claims expense', '$164m', '$131m', '+25.2%', '+5.5pt'],
      ['Net income', '$61m', '$79m', '\u221222.8%', '\u22123.1pt']];
    var out = { kicker: 'GROWTH AND MARGIN, SIDE BY SIDE',
      unit: '$m \u00b7 growth in %, margin in POINTS',
      'head-1': 'FY24', 'head-2': 'FY23', 'head-3': 'GROWTH', 'head-4': 'MARGIN',
      caption: 'A margin moving 22.1% to 18.4% did not fall 17% \u2014 it fell 3.7 points' };
    rows.forEach(function (r, i) {
      out['label-' + (i + 1)] = r[0];
      out['cell-' + (i + 1) + '-1'] = r[1];
      out['cell-' + (i + 1) + '-2'] = r[2];
      out['growth-' + (i + 1)] = r[3];
      out['margin-' + (i + 1)] = r[4];
    });
    return out;
  },
  'percentile-rail': function (s) {
    var rows = [['Revenue growth', '18th'], ['Operating margin', '31st'],
      ['Reserve coverage', '9th'], ['Claims closed per head', '78th'], ['Forward multiple', '64th']];
    var out = { kicker: 'AGAINST THE SECTOR, METRIC BY METRIC',
      unit: 'percentile, eleven-name peer set',
      'axis-low': 'WORST', 'axis-high': 'BEST',
      caption: 'The tick is the sector median \u00b7 ninth percentile on reserve coverage' };
    rows.forEach(function (r, i) { out['label-' + (i + 1)] = r[0]; out['value-' + (i + 1)] = r[1]; });
    return out;
  },
  'where-this-goes': function (s) {
    var items = ['How the claims desk actually makes money',
      'The numbers, and which of them are rates',
      'What the filing says on page 41',
      'What the second read was for',
      'What it is worth if the reserve is wrong'];
    var out = { kicker: 'WHERE THIS GOES', caption: 'Five chapters \u00b7 the filing walk is the third' };
    items.forEach(function (t, i) { out['num-' + (i + 1)] = ('0' + (i + 1)).slice(-2); out['item-' + (i + 1)] = t; });
    return out;
  },
  'timeline-dense': function (s) {
    var ev = [['Mar 19', 'Second-read policy written'], ['Nov 20', 'Backlog first disclosed'],
      ['Jun 21', 'Restatement, $22m'], ['Feb 22', 'Auditor changes'],
      ['Aug 22', 'Policy reaffirmed on the call'], ['Mar 23', 'Reserve cut by a third'],
      ['Sep 23', 'Two directors sell'], ['Nov 23', 'Guidance raised'],
      ['Jan 24', 'Regulator asks for the list'], ['Feb 24', '123 claims disclosed']];
    var out = { kicker: 'HOW WE GOT HERE', caption: 'Ten dated events \u00b7 the last one is this video' };
    ev.forEach(function (e, i) { if (s['date-' + (i + 1)]) { out['date-' + (i + 1)] = e[0]; out['event-' + (i + 1)] = e[1]; } });
    return out;
  },
  'flow-4': function (s) { return flow(s, 4); },
  'flow-5': function (s) { return flow(s, 5); },
  'unit-economics': () => ({
    kicker: 'ONE CLAIM, END TO END',
    'unit-label': 'Per claim assessed',
    'price-label': 'Premium allocated', price: '$412',
    'cost-label': 'Cost to assess', cost: '$268',
    'contribution-label': 'Contribution', contribution: '$144',
    'margin-label': 'CONTRIBUTION MARGIN', margin: '35.0%',
    caption: 'The second read costs $41 of the $268. That is what was skipped.',
  }),
  scorecard: function (s) {
    var rows = [['Pricing power', 'Holds \u2014 renewals repriced above claims inflation'],
      ['Recurring revenue', 'Holds \u2014 84% renews'],
      ['Reserve discipline', 'Fails \u2014 cut three years'],
      ['Disclosure quality', 'Partial \u2014 in a footnote'],
      ['Insider alignment', 'Fails \u2014 directors sold']];
    var out = { kicker: 'THE FRAMEWORK, APPLIED', caption: 'Five criteria \u00b7 two pass',
      'station-1': 'FAILS', 'station-2': 'PARTIAL', 'station-3': 'HOLDS' };
    rows.forEach(function (r, i) { out['criterion-' + (i + 1)] = r[0]; out['verdict-' + (i + 1)] = r[1]; });
    return out;
  },
  'moat-sources-4': function (s) {
    var rows = [['Regulatory licence', 'Twelve-year approval, not contestable', 'Strong'],
      ['Claims data', 'Nineteen years of loss history nobody else holds', 'Strong'],
      ['Switching cost', 'Brokers re-paper every policy to move', 'Moderate'],
      ['Scale in assessment', 'Cost per claim falls with volume', 'Weakening']];
    var out = { kicker: 'WHERE THE ADVANTAGE ACTUALLY COMES FROM',
      caption: 'The fourth one is the one that broke' };
    rows.forEach(function (r, i) { out['source-' + (i + 1)] = r[0]; out['detail-' + (i + 1)] = r[1];
      out['strength-label-' + (i + 1)] = r[2]; });
    return out;
  },
  'peer-scatter': () => ({
    kicker: 'GROWTH AGAINST MULTIPLE, EIGHT NAMES',
    unit: 'multiple against 3Y growth',
    'x-axis': 'REVENUE GROWTH, 3Y CAGR',
    'y-axis': 'FORWARD MULTIPLE',
    caption: 'Meridian is the accent \u00b7 the slowest of the eight, and the dearest',
  }),
  'where-the-cash-went': function (s) {
    var parts = [['Capex', '$88m', '31%'], ['Buybacks', '$104m', '37%'],
      ['Dividends', '$52m', '18%'], ['Debt repaid', '$38m', '14%']];
    var out = { kicker: 'WHERE THE CASH WENT', 'total-label': 'OPERATING CASH FLOW', total: '$282m',
      caption: 'More went to buybacks than to the business' };
    parts.forEach(function (p, i) { out['part-' + (i + 1)] = p[0]; out['amount-' + (i + 1)] = p[1];
      out['share-' + (i + 1)] = p[2]; });
    return out;
  },
  'roic-vs-wacc': () => ({
    kicker: 'RETURN ON CAPITAL AGAINST THE COST OF IT',
    'axis-low': '0%', 'axis-high': '20%',
    'wacc-label': 'Cost of capital', wacc: '8.4%',
    'roic-label': 'Return on capital', roic: '11.9%',
    'spread-label': 'SPREAD', spread: '+3.5pt',
    caption: 'Three and a half points, and it was six before the reserve cut',
  }),
  'revision-trail': function (s) {
    var rows = [['9 Nov', '$5.20', 'initial'], ['14 Jan', '$5.05', '\u22122.9%'],
      ['1 Feb', '$4.90', '\u22123.0%'], ['14 Feb', '$4.25', '\u221213.3%'], ['28 Feb', '$4.10', '\u22123.5%']];
    var out = { kicker: 'HOW THE ESTIMATE MOVED',
      note: 'Four cuts in four months; the largest came the day of the filing',
      caption: 'Consensus EPS for the full year, by date' };
    rows.forEach(function (r, i) { out['date-' + (i + 1)] = r[0]; out['est-' + (i + 1)] = r[1];
      out['move-' + (i + 1)] = r[2]; });
    return out;
  },
  'scenario-fan': () => ({
    kicker: 'THREE WAYS THIS ENDS',
    'start-label': 'TODAY', start: '$31.80',
    'bull-label': 'Reserve holds', 'bull-price': '$48.00', 'bull-move': '+51%',
    'base-label': 'One more cut', 'base-price': '$34.00', 'base-move': '+7%',
    'bear-label': 'Restatement', 'bear-price': '$18.00', 'bear-move': '\u221243%',
    caption: 'The downside is wider than the upside, which is the whole point',
  }),
  'risk-register-4': function (s) {
    var rows = [['The 123 are reopened', 'Reserve rebuilt at full cost, retrospectively'],
      ['Regulator compels the list', 'Every closed claim re-examined, not just these'],
      ['Auditor qualifies the opinion', 'Covenant test fails on the same day'],
      ['Policy rewritten again', 'Nothing breaks, and nothing is disclosed']];
    var out = { kicker: 'WHAT BREAKS, AND HOW BADLY',
      'head-likelihood': 'LIKELIHOOD', 'head-severity': 'SEVERITY',
      caption: 'The fourth is the likeliest and the least severe' };
    rows.forEach(function (r, i) { out['risk-' + (i + 1)] = r[0]; out['detail-' + (i + 1)] = r[1]; });
    return out;
  },
  'where-they-agree': function (s) {
    return { kicker: 'WHERE THE BULL AND THE BEAR AGREE',
      'agreed-label': 'BOTH SIDES ACCEPT',
      'agreed-1': '123 claims closed on a single assessment',
      'agreed-2': 'The reserve has been cut three years running',
      'agreed-3': 'The policy sentence was rewritten in March',
      'bull-label': 'THE BULL READS IT AS',
      bull: 'A backlog cleared cheaply. The claims were low-value, the read '
        + 'would not have changed them, and the loss history says the reserve '
        + 'is adequate.',
      'bear-label': 'THE BEAR READS IT AS',
      bear: 'A control removed and not disclosed. If the read did not matter, '
        + 'the policy would not have needed rewriting to stop mentioning it.',
      caption: 'They agree on every number \u00b7 they differ on what it was for' };
  },
  'buyback-dollars': function (s) {
    var heads = ['FY19', 'FY20', 'FY21', 'FY22', 'FY23', 'FY24'];
    var spend = ['$21m', '$44m', '$68m', '$81m', '$96m', '$104m'];
    var count = ['412m', '409m', '404m', '401m', '399m', '398m'];
    var out = { kicker: 'BUYBACK SPEND, AND WHAT IT BOUGHT',
      unit: '$m per year',
      'count-label': 'DILUTED SHARES OUTSTANDING',
      caption: '$414m spent over six years and the count fell 3.4%' };
    heads.forEach(function (hh, i) { if (s['head-' + (i + 1)]) { out['head-' + (i + 1)] = hh;
      out['spend-' + (i + 1)] = spend[i]; out['count-' + (i + 1)] = count[i]; } });
    return out;
  },
  'hook-card-t4': () => ({
    ticker: 'MRDN', move: '−18.4%',
    huge: '123',
    hook: 'claims closed without the second read the company promised',
    sub: 'The filing says so, on page 41.',
  }),
  'hook-card-t5': () => ({
    ticker: 'MRDN', move: '−18.4%',
    hook: 'They told the market every claim got a second read. One hundred and twenty-three did not.',
    sub: 'Filed at two in the afternoon, on a Friday.',
  }),
  'closing-t2': () => ({
    kicker: 'THE ONE THING',
    statement: 'A reserve that only works if the claims were read is not a reserve.',
    'line-1': 'It restates, or it repeats.',
    'date-label': 'NEXT FILING',
    date: '12 May',
  }),
  'closing-t3': (s) => {
    const out = { kicker: 'WHAT TO WATCH', 'date-label': 'NEXT FILING', date: '12 May' };
    ['Are the 123 reopened, or written off?',
      'Whether the auditor signs the reserve',
      'Whether the policy is rewritten',
      'Insider sales after the filing'].forEach((l, i) => {
      if (s['line-' + (i + 1)]) out['line-' + (i + 1)] = l;
    });
    return out;
  },
};

/* THE ROUND-ONE REVIEW DATA, keyed on type like R1. Until rebuild-19 these
 * plates had words and no numbers of their own: the family rule handed every
 * chart the same claims series, so buyback-dollars burned bars of 11 to 14
 * under labels reading $21m to $104m, and the rail plates drew no marks at
 * all in the review set. The values are the ones the labels state. */
const R1D = {
  /* RECHECK rebuild-19. line-dense is a 12-tick plate for dense series, and
   * the family rule handed it six yearly values, FY heads and three generic
   * figures — so the high, low and last callouts read "123", "$40m" and a
   * "1,388" printed over the high. Twelve monthly points, date heads at the
   * plate's own anchor ticks, and callouts that are the series' own high and
   * low. mark-last is placed by code at the path end, so it is left to the
   * renderer rather than filled into a box that overlaps the high. */
  'line-dense': () => ({ series: [11.0, 11.4, 11.9, 12.3, 12.0, 12.8, 13.4, 13.1, 12.2, 10.4, 9.6, 10.1], min: 0, max: 15, accentLast: true }),
  'percentile-rail': () => ({ marks: { 'marker-1': 0.18, 'marker-2': 0.31, 'marker-3': 0.09, 'marker-4': 0.78, 'marker-5': 0.64 } }),
  scorecard: () => ({ marks: { 'mark-1': 1, 'mark-2': 1, 'mark-3': 0, 'mark-4': 0.5, 'mark-5': 0 } }),
  'moat-sources-4': () => ({ marks: { 'strength-1': 0.92, 'strength-2': 0.88, 'strength-3': 0.61, 'strength-4': 0.34 } }),
  'risk-register-4': () => ({ marks: { 'likelihood-1': 0.34, 'severity-1': 0.92, 'likelihood-2': 0.21, 'severity-2': 0.78,
    'likelihood-3': 0.14, 'severity-3': 0.88, 'likelihood-4': 0.71, 'severity-4': 0.18 } }),
  'roic-vs-wacc': () => ({ low: 0.42, high: 0.595, mark: 0.595 }),
  'where-the-cash-went': () => ({ split: [88, 104, 52, 38], accent: 1 }),
  'revision-trail': () => ({ series: [5.2, 5.05, 4.9, 4.25, 4.1], min: 4, max: 5.4, zero: false, accentLast: true }),
  'buyback-dollars': () => ({ series: [21, 44, 68, 81, 96, 104], min: 0, max: 120, accent: 5 }),
  'peer-scatter': () => ({ points: [[0.72, 0.31], [0.61, 0.44], [0.55, 0.38], [0.48, 0.62], [0.41, 0.51], [0.33, 0.58], [0.24, 0.66], [0.09, 0.74]], accent: 7 }),
  'quarter-bars-8q': () => ({ series: [11.0, 11.4, 11.8, 12.0, 11.9, 13.2, 13.6, 13.9], min: 0, max: 16, accent: 7 }),
  intraday: () => ({ series: [10.2, 10.4, 10.3, 6.1, 5.4, 5.8, 5.6], min: 0, max: 12, accentLast: true }),
  'move-on-the-day-up': () => ({
    kicker: 'MERIDIAN \u00b7 THE DAY AFTER', value: '+6.2%', label: 'Half of the fall back by the close',
    unit: 'intraday, from the prior close', caption: 'A rebound on no news, on a third of the volume' }),
  'move-on-the-day': () => ({ series: [13.88, 11.88, 12.04, 11.8, 11.4, 11.0], min: 0, max: 16, accentLast: true }),
  'move-on-the-day-up': () => ({ series: [11.0, 11.3, 11.9, 11.7, 11.6, 11.7], min: 0, max: 16, accentLast: true }),
  'guidance-raise-cut': () => ({ low: 0.62, high: 0.88, mark: 0.34 }),
  '52-week-position': () => ({ low: 0, high: 1, mark: 0.053 }),
};

/* ── round two: software and industrials ─────────────────────────────────────────────
 *
 * TWO MORE ISSUERS, deliberately. Every sample in the kit so far was one
 * insurer, so every plate read as a claims-desk plate. Round two's plates only
 * make sense for their sectors, and their sample copy says so: Tessera, a
 * subscription-software company, and Harrow, a maker of pumps and valves.
 * Both fictional; every figure below reconciles with its neighbours (the ARR
 * bridge closes, the margin walk adds up, the ratios are the columns divided).
 * Keyed on type, so each covers both aspects; a portrait box that is narrower
 * gets the shorter string where one is needed. */
const Q8 = ['Q1 24', 'Q2 24', 'Q3 24', 'Q4 24', 'Q1 25', 'Q2 25', 'Q3 25', 'Q4 25'];
const Y6 = ['FY20', 'FY21', 'FY22', 'FY23', 'FY24', 'FY25'];
/* A phone-width caption box holds 56 characters; the long one is kept for 16:9. */
const nar = s => !!(s && s.caption && s.caption.w < 1000);
const each = (out, pfx, list) => { list.forEach((v, i) => { out[pfx + '-' + (i + 1)] = v; }); return out; };
const R2 = {
  'arr-bridge': (s) => {
    const out = { kicker: 'ANNUAL RECURRING REVENUE, FY25', unit: '$m of ARR, opening to closing',
      'nrr-label': 'NET RETENTION', nrr: '101%', 'grr-label': 'GROSS RETENTION', grr: '90%',
      caption: nar(s) ? 'Expansion only just covers churn; growth is new logos' : 'Expansion covers churn with a point to spare \u2014 the growth is new customers' };
    each(out, 'head', ['OPENING', 'NEW', 'EXPANSION', 'CONTRACTION', 'CHURN', 'CLOSING']);
    return each(out, 'value', ['$612m', '+$96m', '+$71m', '\u2212$18m', '\u2212$44m', '$717m']);
  },
  'nrr-cohorts': (s) => {
    const narrow = s['label-1'] && s['label-1'].w < 250;
    const rows = [[126, 141, 150, 156, 160], [124, 138, 146, 151], [119, 129, 133], [112, 117], [104]];
    const out = { kicker: 'NET REVENUE RETENTION BY COHORT', unit: '% of starting ARR',
      head: 'Every cohort still grows. Each grows less than the last.',
      caption: nar(s) ? 'Year-one retention: 126% for FY20, 104% for FY24' : 'Year-one retention has fallen from 126% to 104% across five cohorts' };
    each(out, 'col', ['YEAR 1', 'YEAR 2', 'YEAR 3', 'YEAR 4', 'YEAR 5']);
    ['FY20', 'FY21', 'FY22', 'FY23', 'FY24'].forEach((c, r) => {
      out['label-' + (r + 1)] = narrow ? c : c + ' cohort';
      rows[r].forEach((v, j) => { out['cell-' + (r + 1) + '-' + (j + 1)] = v + '%'; });
    });
    return out;
  },
  'rule-of-40': (s) => {
    const out = { kicker: 'GROWTH PLUS MARGIN, EIGHT NAMES', unit: 'revenue growth + free-cash margin',
      'x-axis': 'REVENUE GROWTH', 'y-axis': 'FREE-CASH-FLOW MARGIN', 'line-label': 'RULE OF 40',
      name: 'TESSERA', 'score-label': 'GROWTH + MARGIN', score: '29',
      'score-detail': 'Eleven points under the line, and the lowest score of the eight',
      caption: nar(s) ? 'Above the diagonal, growth plus margin clears 40' : 'Above the diagonal, growth plus free-cash margin clears 40' };
    each(out, 'x-tick', ['0%', '10%', '20%', '30%', '40%', '50%']);
    return each(out, 'y-tick', ['\u221210%', '0%', '10%', '20%', '30%', '40%']);
  },
  'sbc-vs-buybacks': (s) => {
    const out = { kicker: 'BUYBACKS AGAINST STOCK COMPENSATION', unit: '$m per year',
      'row-1': 'BOUGHT BACK', 'row-2': 'PAID IN STOCK', 'count-label': 'DILUTED SHARES OUTSTANDING',
      verdict: 'The buyback pays the stock bill. It does not shrink the count.',
      caption: nar(s) ? '$1.47bn bought back, and the count still rose 5%' : '$1.47bn bought back since FY21, and the share count still rose 5%' };
    each(out, 'head', Y6);
    each(out, 'spend', ['$0m', '$120m', '$240m', '$310m', '$380m', '$420m']);
    each(out, 'sbc', ['$180m', '$230m', '$290m', '$340m', '$395m', '$440m']);
    return each(out, 'count', ['301m', '309m', '312m', '314m', '315m', '316m']);
  },
  'rpo-coverage': () => {
    const out = { kicker: 'HOW MUCH OF NEXT YEAR IS ALREADY SIGNED', unit: 'cRPO \u00f7 next 12 months of revenue',
      'ceiling-label': '100% \u00b7 FULLY CONTRACTED', 'latest-label': 'SIGNED TODAY', latest: '61%',
      'latest-detail': '$509m of current RPO against $834m of expected revenue',
      caption: 'Nine points less of next year is signed than a year ago' };
    each(out, 'head', Q8);
    return each(out, 'value', ['68%', '67%', '69%', '70%', '66%', '64%', '62%', '61%']);
  },
  'cac-payback': (s) => {
    const out = { kicker: 'THE COST OF A CUSTOMER, AND THE PAYBACK',
      'legend-1': 'Gross profit, cumulative', 'legend-2': 'Cost to acquire',
      'x-axis': 'MONTHS SINCE SIGNING',
      'cac-label': 'CAC PER CUSTOMER', cac: '$84k', 'arr-label': 'NEW ARR PER CUSTOMER', arr: '$60k',
      'gm-label': 'GROSS MARGIN', gm: '78%',
      'payback-label': 'PAID BACK IN', payback: '22', 'payback-unit': 'MONTHS',
      caption: nar(s) ? '$60k of ARR at 78% margin repays $84k in 22 months' : '$60k of ARR at a 78% margin earns back $84k in about 22 months' };
    return each(out, 'head', ['0', '6', '12', '18', '24', '30', '36']);
  },
  'book-to-bill': (s) => {
    const out = { kicker: 'ORDERS AGAINST REVENUE, EIGHT QUARTERS', unit: '$m per quarter',
      'legend-1': 'Orders', 'legend-2': 'Revenue', 'ratio-label': 'BOOK-TO-BILL',
      'latest-label': 'LATEST QUARTER', latest: '0.89\u00d7',
      'latest-detail': 'Backlog $1.71bn, 8.8 months of revenue, down from 10.1',
      caption: nar(s) ? 'Six quarters under 1.0\u00d7 \u2014 the backlog is shrinking' : 'Six quarters under 1.0\u00d7 \u2014 the backlog is being worked down, not refilled' };
    each(out, 'head', Q8);
    return each(out, 'ratio', ['1.06\u00d7', '1.07\u00d7', '0.99\u00d7', '0.94\u00d7', '0.92\u00d7', '0.89\u00d7', '0.93\u00d7', '0.89\u00d7']);
  },
  'margin-walk': (s) => {
    const out = { kicker: 'OPERATING MARGIN, FY24 TO FY25', unit: 'points \u00b7 axis not from zero',
      'change-label': 'NET CHANGE', change: '\u22121.8pt',
      caption: nar(s) ? 'Price added 1.6pt; volume and costs took 2.6pt back' : 'Price added 1.6 points; volume and input costs took 2.6 back' };
    each(out, 'head', ['FY24', 'PRICE', 'VOLUME', 'MIX', 'INPUT COSTS', 'FX & OTHER', 'FY25']);
    return each(out, 'value', ['15.2%', '+1.6pt', '\u22121.1pt', '\u22120.4pt', '\u22121.5pt', '\u22120.4pt', '13.4%']);
  },
  'end-market-exposure': () => {
    const out = { kicker: 'WHERE THE REVENUE COMES FROM', 'head-share': 'SHARE OF FY25 REVENUE',
      'head-growth': 'GROWTH, YEAR ON YEAR', 'axis-low': '\u221220%', 'axis-high': '+20%',
      caption: 'A third of revenue is in the market shrinking fastest' };
    each(out, 'label', ['Oil & gas', 'Water', 'Chemicals', 'Aerospace', 'Food & pharma']);
    each(out, 'share', ['34%', '26%', '18%', '12%', '10%']);
    return each(out, 'growth-value', ['\u22128%', '+6%', '\u22123%', '+14%', '+2%']);
  },
  'price-cost-spread': (s) => {
    const out = { kicker: 'PRICE AGAINST COST, EIGHT QUARTERS', unit: '% change on a year earlier',
      'legend-1': 'Price realised', 'legend-2': 'Input cost inflation',
      'spread-label': 'LATEST SPREAD', spread: '\u22122.2pt',
      'spread-detail': 'Costs have outrun price for two quarters running',
      caption: nar(s) ? 'Where cost is above price, margin is given back' : 'Where the cost line sits above the price line, margin is being given back' };
    return each(out, 'head', Q8);
  },
  'cash-conversion-cycle': (s) => {
    const out = { kicker: 'CASH CONVERSION CYCLE, FY25', head: 'Cash is out for 108 days before it comes back',
      'days-unit': 'DAYS',
      'label-1': 'Inventory, then receivables', 'detail-1': '96 days to sell, 64 more to collect', 'days-1': '160',
      'label-2': 'Supplier credit', 'detail-2': 'Suppliers are paid on day 52', 'days-2': '52',
      'label-3': 'Cash tied up', 'detail-3': '14 days longer than in FY24', 'days-3': '108',
      caption: nar(s) ? '96 inventory + 64 receivable \u2212 52 payable days = 108' : 'Inventory days plus receivable days, less payable days: 96 + 64 \u2212 52 = 108' };
    return each(out, 'tick', ['0', '30', '60', '90', '120', '150', '180']);
  },
  'capex-vs-depreciation': (s) => {
    const out = { kicker: 'CAPEX AGAINST DEPRECIATION', unit: '$m per year',
      'row-1': 'CAPITAL SPENDING', 'row-2': 'DEPRECIATION', 'ratio-label': 'CAPEX \u00f7 DEPRECIATION',
      verdict: 'It spends less each year than its plant wears out.',
      caption: nar(s) ? 'Five years under 1.0\u00d7 \u2014 the plant is being run down' : 'Five years under 1.0\u00d7 \u2014 the asset base is being run down, not renewed' };
    each(out, 'head', Y6);
    each(out, 'capex', ['$88m', '$72m', '$64m', '$61m', '$58m', '$55m']);
    each(out, 'da', ['$80m', '$82m', '$83m', '$85m', '$86m', '$88m']);
    return each(out, 'ratio', ['1.10\u00d7', '0.88\u00d7', '0.77\u00d7', '0.72\u00d7', '0.67\u00d7', '0.63\u00d7']);
  },
};

/* ── round three: one set per sector ──────────────────────────────────────────────────────────────
 *
 * Nine more fictional issuers, one per sector, so no plate reads as another
 * sector's: Ardent Energy (oil and gas), Corvane (copper), Larkin (apparel
 * retail), Fenwick Foods, Quillon Therapeutics, Merrow Bank, Brightline
 * (streaming), Calder Power, Holloway (office REIT). Every walk closes, every
 * share column sums to 100, every ratio is its columns divided. Captions fit
 * one phone line (56 characters), so one string serves both aspects. */
const two = (a, b) => ({ 'legend-1': a, 'legend-2': b });
const rails = (o, rows) => { rows.forEach((r, i) => { o['label-' + (i + 1)] = r[0]; o['share-' + (i + 1)] = r[1] + '%'; o['growth-value-' + (i + 1)] = (r[2] > 0 ? '+' : r[2] < 0 ? '\u2212' : '') + Math.abs(r[2]) + '%'; }); o['axis-low'] = '\u221220%'; o['axis-high'] = '+20%'; return o; };
const railData = (rows, max) => { const marks = {}; rows.forEach((r, i) => { marks['growth-' + (i + 1)] = (r[2] + 20) / 40; }); return { bars: rows.map(r => r[1]), min: 0, max, accent: 0, marks }; };
const WALK = (heads, vals) => { const o = {}; each(o, 'head', heads); return each(o, 'value', vals); };
const R3rows = {
  prod: [['Permian oil', 41, 4], ['Gulf oil', 22, -12], ['Natural gas', 24, 9], ['NGLs', 9, 2], ['Other', 4, -6]],
  drugs: [['Velostat', 58, 3], ['Orvane', 27, 18], ['Brisa', 8, 11], ['Tenmar', 4, -9], ['Other', 3, -4]],
  deposits: [['Current accounts', 21, -14], ['Savings', 34, -3], ['Money market', 18, 6], ['Time deposits', 22, 19], ['Brokered', 5, 12]],
  gen: [['Gas', 38, -4], ['Nuclear', 24, 0], ['Wind', 19, 12], ['Solar', 11, 18], ['Coal', 8, -19]],
};
const R3 = {
  'breakeven-vs-price': () => Object.assign({ kicker: 'REALISED PRICE AGAINST BREAKEVEN', unit: '$ per barrel',
    'spread-label': 'LATEST MARGIN', spread: '\u2212$3', 'spread-detail': 'Per barrel under breakeven, the first time in two years',
    caption: 'Where breakeven is above price, every barrel loses money' }, two('Realised oil price', 'Breakeven, all-in'), each({}, 'head', Q8)),
  'production-mix': () => rails({ kicker: 'WHAT THE WELLS PRODUCE', 'head-share': 'SHARE OF FY25 OUTPUT', 'head-growth': 'GROWTH, YEAR ON YEAR',
    caption: 'The Gulf is a fifth of output and falling fastest' }, R3rows.prod),
  'ebitda-walk': () => Object.assign({ kicker: 'EBITDA, FY24 TO FY25', unit: '$m', 'change-label': 'NET CHANGE', change: '\u2212$10m',
    caption: 'A higher copper price, spent on lower volume and costs' },
    WALK(['FY24', 'PRICE', 'VOLUME', 'COSTS', 'FX', 'FY25'], ['$1,840m', '+$310m', '\u2212$140m', '\u2212$220m', '+$40m', '$1,830m'])),
  'capacity-utilisation': () => each({ kicker: 'SMELTER UTILISATION', unit: 'output \u00f7 nameplate capacity', 'ceiling-label': '100% \u00b7 NAMEPLATE',
    'latest-label': 'LATEST QUARTER', latest: '71%', 'latest-detail': 'Two furnaces down for relining since August',
    caption: 'Seventeen points below its peak in six quarters' }, 'head', Q8),
  'inventory-vs-sales': () => Object.assign({ kicker: 'INVENTORY AGAINST SALES', unit: '% change on a year earlier',
    'spread-label': 'LATEST GAP', spread: '14.9pt', 'spread-detail': 'Inventory up 13.5% on sales down 1.4% \u2014 markdowns follow',
    caption: 'Past the crossing, stock builds faster than sales' }, two('Sales growth', 'Inventory growth'), each({}, 'head', Q8)),
  'store-count-bridge': () => Object.assign({ kicker: 'STORES, START TO END OF FY25', unit: 'stores', 'change-label': 'NET CHANGE', change: '\u221266 stores',
    caption: 'Closures outran openings for the third year' },
    WALK(['OPENING', 'OPENED', 'CLOSED', 'FRANCHISED', 'CLOSING'], ['1,204', '+62', '\u221288', '\u221240', '1,138'])),
  'price-vs-volume': () => Object.assign({ kicker: 'PRICE AGAINST VOLUME', unit: 'points of organic growth',
    'spread-label': 'ORGANIC GROWTH', spread: '+1.7pt', 'spread-detail': 'Price is fading faster than volume is coming back',
    caption: 'Two years of growth bought with price, not volume' }, two('Price and mix', 'Volume'), each({}, 'head', Q8)),
  'net-sales-walk': () => Object.assign({ kicker: 'NET SALES, FY24 TO FY25', unit: '$m', 'change-label': 'NET CHANGE', change: '+$60m',
    caption: 'Price added $240m; volume and currency took back $210m' },
    WALK(['FY24', 'PRICE', 'VOLUME', 'MIX', 'FX', 'FY25'], ['$4,210m', '+$240m', '\u2212$120m', '+$30m', '\u2212$90m', '$4,270m'])),
  'exclusivity-runway': () => each({ kicker: 'HOW LONG EACH PRODUCT IS PROTECTED', head: 'Most of the revenue loses protection in two years',
    'days-unit': 'UNTIL',
    'label-1': 'Velostat, 58% of revenue', 'detail-1': 'US compound patent expires 2027', 'days-1': '2027',
    'label-2': 'Orvane, 27% of revenue', 'detail-2': 'Protected to 2033, growing 18%', 'days-2': '2033',
    'label-3': 'Pipeline, Phase III', 'detail-3': 'First approval expected in 2029', 'days-3': '2029',
    caption: 'The pipeline arrives two years after Velostat goes' }, 'tick', ['2025', '2028', '2031', '2034', '2037', '2040']),
  'product-concentration': () => rails({ kicker: 'WHERE THE REVENUE COMES FROM', 'head-share': 'SHARE OF FY25 REVENUE', 'head-growth': 'GROWTH, YEAR ON YEAR',
    caption: 'One drug is 58% of revenue, and it goes off patent next' }, R3rows.drugs),
  'nim-spread': () => Object.assign({ kicker: 'WHAT THE BANK EARNS ON THE SPREAD', unit: '% a year',
    'spread-label': 'LATEST SPREAD', spread: '2.5pt', 'spread-detail': 'Down from 4.4 points two years ago as deposits repriced',
    caption: 'The filled gap is the margin, and it has halved' }, two('Yield on loans', 'Cost of deposits'), each({}, 'head', Q8)),
  'deposit-mix': () => rails({ kicker: 'WHERE THE DEPOSITS SIT', 'head-share': 'SHARE OF DEPOSITS', 'head-growth': 'GROWTH, YEAR ON YEAR',
    caption: 'The cheapest deposits are the ones leaving' }, R3rows.deposits),
  'subscriber-bridge': () => Object.assign({ kicker: 'SUBSCRIBERS, FY25', unit: 'millions', 'change-label': 'NET ADDS', change: '\u22120.6m',
    caption: 'Churn now outruns gross adds for the first time' },
    WALK(['OPENING', 'GROSS ADDS', 'CHURNED', 'WIN-BACKS', 'CLOSING'], ['48.2m', '+9.6m', '\u221211.3m', '+1.1m', '47.6m'])),
  'content-vs-revenue': () => { const o = { kicker: 'CONTENT SPEND AGAINST REVENUE', unit: '$bn per year',
      'row-1': 'REVENUE', 'row-2': 'CONTENT SPEND', 'ratio-label': 'CONTENT \u00f7 REVENUE',
      verdict: 'Content takes more of every dollar each year.',
      caption: 'From 66% of revenue to 78% in six years' };
    each(o, 'head', Y6); each(o, 'rev', ['$6.1bn', '$7.4bn', '$8.2bn', '$8.9bn', '$9.3bn', '$9.6bn']);
    each(o, 'content', ['$4.0bn', '$5.2bn', '$6.0bn', '$6.6bn', '$7.1bn', '$7.5bn']);
    return each(o, 'ratio', ['66%', '70%', '73%', '74%', '76%', '78%']); },
  'allowed-vs-earned-roe': () => Object.assign({ kicker: 'ALLOWED RETURN AGAINST EARNED', unit: '% return on equity',
    'spread-label': 'REGULATORY LAG', spread: '\u22122.1pt', 'spread-detail': 'Earning 2.1 points under what the regulator allows',
    caption: 'The gap is the return the next rate case has to win back' }, two('Allowed return', 'Earned return'), each({}, 'head', Q8)),
  'generation-mix': () => rails({ kicker: 'WHERE THE POWER COMES FROM', 'head-share': 'SHARE OF FY25 OUTPUT', 'head-growth': 'GROWTH, YEAR ON YEAR',
    caption: 'Renewables are 30% of output and all of the growth' }, R3rows.gen),
  'occupancy': () => each({ kicker: 'OCCUPANCY, EIGHT QUARTERS', unit: 'leased \u00f7 rentable space', 'ceiling-label': '100% \u00b7 FULLY LEASED',
    'latest-label': 'LATEST QUARTER', latest: '81%', 'latest-detail': '1.9m sq ft empty, the most since the portfolio was built',
    caption: 'Ten points of occupancy lost in two years' }, 'head', Q8),
  'noi-walk': () => Object.assign({ kicker: 'NET OPERATING INCOME, FY24 TO FY25', unit: '$m', 'change-label': 'NET CHANGE', change: '\u2212$57m',
    caption: 'Rent growth added $18m; vacancy took $41m' },
    WALK(['FY24', 'RENT GROWTH', 'VACANCY', 'OPEX', 'SALES', 'FY25'], ['$612m', '+$18m', '\u2212$41m', '\u2212$12m', '\u2212$22m', '$555m'])),
};
R3['capacity-utilisation'] = ((f) => () => each(f(), 'value', ['88%', '90%', '87%', '85%', '83%', '79%', '74%', '71%']))(R3['capacity-utilisation']);
R3['occupancy'] = ((f) => () => each(f(), 'value', ['91%', '90%', '89%', '88%', '86%', '85%', '83%', '81%']))(R3['occupancy']);
const R3D = {
  'breakeven-vs-price': () => ({ series: [82, 79, 85, 78, 74, 71, 68, 66], series2: [58, 59, 61, 63, 64, 66, 67, 69], min: 0, max: 100, spread: true, accentLast: false }),
  'production-mix': () => railData(R3rows.prod, 50),
  'ebitda-walk': () => ({ steps: [310, -140, -220, 40], open: 1840, close: 1830 }),
  'capacity-utilisation': () => ({ series: [88, 90, 87, 85, 83, 79, 74, 71], min: 0, max: 100, accent: 7 }),
  'inventory-vs-sales': () => ({ series: [6.1, 5.4, 4.2, 2.8, 1.9, 0.6, -0.8, -1.4], series2: [3.2, 4.0, 5.6, 7.9, 9.4, 11.2, 12.8, 13.5], min: -5, max: 15, spread: true, accentLast: false, zeroRule: true }),
  'store-count-bridge': () => ({ steps: [62, -88, -40], open: 1204, close: 1138 }),
  'price-vs-volume': () => ({ series: [7.8, 6.9, 5.6, 4.4, 3.6, 2.9, 2.4, 2.1], series2: [-2.1, -2.8, -3.4, -2.9, -2.2, -1.6, -0.9, -0.4], min: -5, max: 10, accentLast: false, zeroRule: true }),
  'net-sales-walk': () => ({ steps: [240, -120, 30, -90], open: 4210, close: 4270 }),
  'exclusivity-runway': () => ({ bands: { 'band-1': [0, 2 / 15, 'attention'], 'band-2': [0, 8 / 15, 'subject'], 'band-3': [4 / 15, 1, 'subject2'] } }),
  'product-concentration': () => railData(R3rows.drugs, 60),
  'nim-spread': () => ({ series: [5.2, 5.5, 5.8, 6.0, 6.1, 6.1, 6.0, 5.9], series2: [0.8, 1.3, 1.9, 2.4, 2.8, 3.1, 3.3, 3.4], min: 0, max: 7, spread: true, accentLast: false }),
  'deposit-mix': () => railData(R3rows.deposits, 40),
  'subscriber-bridge': () => ({ steps: [9.6, -11.3, 1.1], open: 48.2, close: 47.6 }),
  'content-vs-revenue': () => ({ series: [6.1, 7.4, 8.2, 8.9, 9.3, 9.6], series2: [4.0, 5.2, 6.0, 6.6, 7.1, 7.5], min: 0, max: 11, tone2: 'subject2' }),
  'allowed-vs-earned-roe': () => ({ series: [9.8, 9.8, 9.8, 9.9, 9.9, 9.9, 10.1, 10.1], series2: [9.4, 9.1, 8.8, 8.6, 8.9, 8.3, 8.1, 8.0], min: 0, max: 12, spread: true, accentLast: false }),
  'generation-mix': () => railData(R3rows.gen, 40),
  'occupancy': () => ({ series: [91, 90, 89, 88, 86, 85, 83, 81], min: 0, max: 100, accent: 7 }),
  'noi-walk': () => ({ steps: [18, -41, -12, -22], open: 612, close: 555 }),
};
/* Round four's copy and data live beside their catalogue rows. */
const SECTOR_COPY = (typeof require === 'function') ? (() => { try { return require('./sector-copy'); } catch (e) { return null; } })()
  : (typeof window !== 'undefined' ? window.SECTOR_COPY || null : null);
const R2D = {
  'arr-bridge': () => ({ steps: [96, 71, -18, -44], open: 612, close: 717 }),
  'margin-walk': () => ({ steps: [1.6, -1.1, -0.4, -1.5, -0.4], open: 15.2, close: 13.4, float: true }),
  'rule-of-40': () => ({ points: [[34, 18], [28, 22], [45, 5], [17, 31], [24, 12], [38, 9], [12, 26], [21, 8]], accent: 7 }),
  'sbc-vs-buybacks': () => ({ series: [0, 120, 240, 310, 380, 420], series2: [180, 230, 290, 340, 395, 440], min: 0, max: 480, tone2: 'subject2' }),
  'rpo-coverage': () => ({ series: [68, 67, 69, 70, 66, 64, 62, 61], min: 0, max: 100, accent: 7 }),
  'cac-payback': () => ({ series: [0, 23, 45, 66, 86, 104, 121], min: 0, max: 140, accentLast: false, marks: { 'cac-line': 84 / 140 } }),
  'book-to-bill': () => ({ series: [612, 640, 598, 571, 552, 530, 548, 520], series2: [580, 596, 604, 610, 602, 598, 590, 584], min: 0, max: 700, tone2: 'quiet' }),
  'end-market-exposure': () => ({ bars: [34, 26, 18, 12, 10], min: 0, max: 40, accent: 0,
    marks: { 'growth-1': 0.3, 'growth-2': 0.65, 'growth-3': 0.425, 'growth-4': 0.85, 'growth-5': 0.55 } }),
  'price-cost-spread': () => ({ series: [6.8, 6.1, 5.2, 4.4, 3.5, 2.8, 2.2, 1.9], series2: [9.5, 7.2, 4.8, 2.9, 1.8, 2.4, 3.3, 4.1],
    min: 0, max: 10, spread: true, accentLast: false, zeroRule: true }),
  'cash-conversion-cycle': () => ({ bands: { 'band-inventory': [0, 96 / 180, 'subject'], 'band-receivables': [96 / 180, 160 / 180, 'subject2'],
    'band-payables': [0, 52 / 180, 'quiet'], 'band-gap': [52 / 180, 160 / 180, 'attention'] } }),
  'capex-vs-depreciation': () => ({ series: [88, 72, 64, 61, 58, 55], series2: [80, 82, 83, 85, 86, 88], min: 0, max: 100, tone2: 'quiet' }),
};

/* The unit-economics flow, at four or five stages. Same issuer. */
function flow(slots, n) {
  const st = [['Premium in', '$412', 'per claim'],
    ['Assessment', '−$227', 'first read, always done'],
    ['Second read', '−$41', 'the step that was skipped'],
    ['Settlement', '−$0', 'only if the claim is valid'],
    ['Contribution', '$144', 'kept']];
  const pick = n === 4 ? [0, 1, 2, 4] : [0, 1, 2, 3, 4];
  const out = {};
  pick.forEach((k, i) => {
    if (!slots['stage-' + (i + 1)]) return;
    out['stage-' + (i + 1)] = st[k][0];
    out['figure-' + (i + 1)] = st[k][1];
    out['note-' + (i + 1)] = st[k][2];
  });
  out.kicker = 'HOW THE MONEY IS MADE, PER CLAIM';
  out.caption = n === 4 ? 'Four stages · the second read is the third one'
    : 'Five stages · settlement is nil when the claim fails the read';
  return out;
}

/* The unit-economics flow, at four or five stages. Same issuer. */
function flow(slots, n) {
  var st = [['Premium in', '$412', 'per claim'],
    ['Assessment', '\u2212$227', 'first read'],
    ['Second read', '\u2212$41', 'skipped'],
    ['Settlement', '\u2212$0', 'if valid'],
    ['Contribution', '$144', 'kept']];
  var pick = n === 4 ? [0, 1, 2, 4] : [0, 1, 2, 3, 4];
  var out = {};
  pick.forEach(function (k, i) {
    if (!slots['stage-' + (i + 1)]) return;
    out['stage-' + (i + 1)] = st[k][0];
    out['figure-' + (i + 1)] = st[k][1];
    out['note-' + (i + 1)] = st[k][2];
  });
  out.kicker = 'HOW THE MONEY IS MADE, PER CLAIM';
  out.caption = n === 4 ? 'Four stages \u00b7 the second read is the third one'
    : 'Five stages \u00b7 settlement is nil when the claim fails the read';
  return out;
}

function wire(slots, n) {
  const out = { kicker: 'THE WIRE, 14 FEBRUARY',
    caption: 'The last line is the filing. The rest is comment.' };
  for (let i = 1; i <= n; i++) {
    const w = WIRE[(i - 1) % WIRE.length];
    out['time-' + i] = w[0];
    out['headline-' + i] = w[1];
    out['source-' + i] = w[2];
  }
  return out;
}

/* ── the entry point ────────────────────────────────────────────────────── */

/* Returns { text: {slot: string}, data: {…} } for one plate. `data` is what
 * engine/series.js needs; everything a renderer draws is named here and
 * nowhere else, so a plate's numbers and its words come from one record. */
/* THE OVERRIDE LAYER. Everything a person edits by hand lives in
 * content-overrides.json: text per slot, numbers per series, args per plate.
 * Precedence is override > family rule > role default, and an override is
 * still checked against the slot's own maxChars — an override that does not
 * fit is a failure, not a truncation found later on screen.
 *
 * Injected rather than required, so the emitter and the review surface can
 * both supply it without this file knowing how either of them reads files. */
let OVERRIDES = {};
function setOverrides(o) { OVERRIDES = (o && o.overrides) || o || {}; }
function overridesFor(key) {
  const base = OVERRIDES[key] || {};
  const ep = EPISODE.plates && EPISODE.plates[key];
  if (!ep) return base;
  return { slots: Object.assign({}, base.slots, ep.slots), data: Object.assign({}, base.data, ep.data) };
}

/* ── the episode API ───────────────────────────────────────────────────────
 *
 * THIS IS HOW THE BOT DRESSES THE KIT FOR ONE VIDEO. content-overrides.json
 * is for a person editing by hand; this is for code, at runtime, per episode:
 *
 *   CONTENT.setEpisode({
 *     story:  { periods: [...], checked: [...] },      // the numbers behind charts
 *     measures: [ { label: 'Refunds', value: 4200, unit: 'Q3', delta: -12, fmt: 'count' } ],
 *     lines:  ['Kept because somebody kept it'],       // captions
 *     plates: { 'figures/big-number-l1': { slots: { value: '4,200' } } },
 *   });
 *
 * Everything is optional and anything omitted falls back to the sample. So a
 * bot that knows only two numbers can set two numbers and the other ninety
 * plates still render — which is the difference between a kit that degrades
 * and a kit that throws.
 *
 * Precedence, highest first:
 *   episode.plates > content-overrides.json > family rule > role default
 *
 * The budget still applies. A string the episode supplies that does not fit
 * its slot is a FAILURE the audit reports, not a silent truncation found in
 * the cut. */
let EPISODE = {};
function setEpisode(ep) {
  EPISODE = ep || {};
  if (EPISODE.story) Object.assign(STORY, EPISODE.story);
  if (EPISODE.measures && EPISODE.measures.length) {
    MEASURES.length = 0;
    EPISODE.measures.forEach(m => MEASURES.push(Object.assign({ unit: '', delta: 0, fmt: 'count' }, m)));
  }
  if (EPISODE.lines && EPISODE.lines.length) { STORY.lines.length = 0; EPISODE.lines.forEach(l => STORY.lines.push(l)); }
  return CONTENT;
}
function episode() { return EPISODE; }

/* What an episode WOULD break, without rendering anything. A bot should be
 * able to ask before it commits: which of my strings will not fit. */
function checkEpisode(ep, manifests) {
  const keep = EPISODE;
  setEpisode(ep);
  const bad = [];
  Object.keys(manifests || {}).forEach(key => {
    overBudget(key, manifests[key]).forEach(o => bad.push(Object.assign({ key }, o)));
    strayOverrides(key, manifests[key]).forEach(slot => bad.push({ key, slot, reason: 'no such slot' }));
  });
  setEpisode(keep);
  return bad;
}

function contentFor(key, manifest) {
  const slots = (manifest && manifest.slots) || {};
  const family = key.split('/')[0];

  /* A CUT-OUT CARRIES NO WORDS OF ITS OWN. An annotation declares
   * `cutout: true, alpha, over: "any plate"` — it is a mark that lands on top
   * of something, and the words it marks belong to the plate UNDERNEATH. The
   * generic role path was filling `caption` on every one of them, so a mark
   * painted its own stray line of copy over the thing it was annotating.
   *
   * Gated on the manifest flag, not on the family name, so it holds for any
   * future cut-out asset rather than only for the ten that exist today. */
  if (manifest && manifest.cutout === true) {
    const d0 = {};
    return { text: {}, data: Object.assign(d0, (overridesFor(key).data) || {}) };
  }
  MEASURE_OFFSET = keyOffset(key.replace(/-(16x9|9x16)$/, ''));
  /* The round-one shorts copy, keyed on the plate's declared type. Sits below
   * an explicit override and above the family rule. */
  const r1 = (manifest && R1[manifest.type]) ? R1[manifest.type](slots)
    : (manifest && R2[manifest.type]) ? R2[manifest.type](slots)
    : (manifest && R3[manifest.type]) ? R3[manifest.type](slots)
    : (manifest && SECTOR_COPY && SECTOR_COPY.text(manifest.type, slots)) || null;
  const ov = overridesFor(key);
  const over = Object.assign(
    FAMILY[family] ? FAMILY[family](slots, key) : {},
    r1 || {},
    ov.slots || {});
  const text = {};
  const counters = {};

  Object.keys(slots).forEach(name => {
    const sl = slots[name];
    if (sl.overlay || sl.container || sl.role === 'highlight-band' || sl.role === 'plot-area'
      || sl.role === 'bars' || sl.role === 'bridge' || sl.role === 'path' || sl.role === 'spark'
      || sl.role === 'marker' || sl.role === 'band' || sl.role === 'media' || sl.role === 'point-column'
      || sl.role === 'wraps' || sl.role === 'control'
      /* band and marker are RENDERER regions even on the few plates that do
       * not flag them — engine/series.js draws them (historyBand, axisMark).
       * Filling them with text would put a label where a shape goes. */
      || sl.role === 'band' || sl.role === 'marker') return;
    let v = over[name];
    if (v === undefined) {
      const idx = (name.match(/(\d+)$/) || [])[1];
      const n = idx ? +idx - 1 : (counters[sl.role] = (counters[sl.role] || 0));
      if (!idx) counters[sl.role]++;
      v = byRole(sl.role, n, sl);
    }
    if (v === null || v === undefined || v === '') return;
    /* A slot too small for two characters is not a text slot. Rendering an
     * ellipsis there is worse than rendering nothing: it reads as a defect
     * in the plate rather than as an empty box. */
    if (budgetOf(sl, manifest && manifest.typeRoles) < 2) return;
    text[name] = fit(v, sl, manifest && manifest.typeRoles);
  });

  /* The series data, per family. Only what a renderer will actually read. */
  const data = {};
  if (family === 'charts') {
    /* As many points as the plate has columns. An 8-quarter chart handed 6
     * values drew nothing at all, because a renderer that cannot line values
     * up with columns is right to refuse. */
    const cols = Object.keys(slots).filter(n => /^(bar|point)-\d+$/.test(n)).length;
    const base = STORY.checked.map(v => v / 100);
    const n = cols || base.length;
    data.series = Array.from({ length: n }, (_, i) => base[i % base.length]);
    data.min = 0; data.max = 20; data.accentLast = true;
  }
  if (family === 'peers') data.bars = STORY.peers.map(p => p[1]);
  if (family === 'cycles') data.cycle = STORY.checked.map(v => v / 100);
  if (family === 'tables') data.spark = STORY.checked.map(v => v / 100);
  if (family === 'figures' && /waterfall/.test(key)) { data.steps = STORY.steps.map(s => s[1]); data.open = 40; data.close = 0; }
  if (family === 'structure' && /sensitivity|implied|both-true/.test(key)) { data.low = 0.28; data.high = 0.74; data.mark = 0.86; }
  /* A plate's own numbers beat the family rule, the same precedence as its words. */
  const own = manifest && (R1D[manifest.type] || R2D[manifest.type] || R3D[manifest.type]
    || (SECTOR_COPY && SECTOR_COPY.data(manifest.type) ? () => SECTOR_COPY.data(manifest.type) : null));
  if (own) Object.assign(data, own());
  Object.assign(data, ov.data || {});

  /* TONE — WHICH INK ROLE A FILLED SLOT SHOULD TAKE.
   *
   * The kit declares nine ink roles per hour and the plates were rendering
   * type in two of them: structure for almost everything, quiet for the rest.
   * A palette that is declared and not used is not a palette.
   *
   * These are not decoration. The legacy palette's own semantics, which
   * DESIGN.md keeps: `down` is a loss and nothing else, `up` is only a rise,
   * `neutralData` has no direction, `attention` is the one thing to look at.
   * So a measure that fell is inked as a fall, and a measure that rose is
   * inked as a rise — the colour is the reading, not a highlight.
   *
   * Every value here is a declared ink role, so palette closure (rule 3)
   * holds without an exception. */
  /* TONE — AT MOST ONE ACCENT PER PLATE.
   *
   * The first cut of this inked every value slot by its own measure's
   * direction, so a six-point series came out red, blue, blue, blue, red,
   * red: colour varying along one line that has one meaning. That is noise
   * wearing the costume of information.
   *
   * DESIGN.md's own rule is that `attention` is THE ONE THING TO LOOK AT.
   * So: the plate's single headline figure may take the accent, and only
   * when its measure actually fell. Everything else is structure, and the
   * quiet roles stay quiet. Series colour belongs to engine/series.js, which
   * inks the whole line as one thing.
   *
   * Values are ranked lists; the renderer takes the first that clears 4.5:1
   * against the ground it sits on, because amber is legible at night and not
   * at dusk. */
  const tone = {};
  const HEADLINE = ['huge', 'big', 'figure', 'value'];
  let accentUsed = false;
  Object.keys(text).forEach(name => {
    const sl = slots[name]; if (!sl) return;
    // Only an unnumbered headline slot — a numbered one is part of a series.
    if (accentUsed || /\d$/.test(name) || HEADLINE.indexOf(sl.role) < 0) return;
    const M2 = measure(0);
    if (M2 && M2.delta < 0) { tone[name] = ['attention', 'subject2', 'structure']; accentUsed = true; }
  });
  Object.keys(text).forEach(name => {
    const sl = slots[name]; if (!sl || tone[name]) return;
    if (sl.role === 'unit' || sl.role === 'caption' || sl.role === 'source'
      || sl.role === 'foot' || sl.role === 'kicker') tone[name] = ['quiet', 'structure'];
  });

  return { text, data, tone };
}

/* Every string, checked. Returned as data so a caller can fail on it. */
function overBudget(key, manifest) {
  const c = contentFor(key, manifest);
  const slots = manifest.slots || {};
  const roles = manifest.typeRoles;
  return Object.keys(c.text).map(n => {
    const sl = slots[n]; if (!sl) return null;
    const max = budgetOf(sl, roles);
    return max && c.text[n].length > max ? { slot: n, len: c.text[n].length, max, derived: !sl.maxChars } : null;
  }).filter(Boolean);
}

/* Which override keys point at slots that do not exist. A typo in an override
 * silently does nothing, which is the worst failure mode a content file has:
 * you edit the text, nothing changes, and there is no error to read. */
function strayOverrides(key, manifest) {
  const slots = (manifest && manifest.slots) || {};
  MEASURE_OFFSET = keyOffset(key.replace(/-(16x9|9x16)$/, ''));
  /* The round-one shorts copy, keyed on the plate's declared type. Sits below
   * an explicit override and above the family rule. */
  const r1 = (manifest && R1[manifest.type]) ? R1[manifest.type](slots) : null;
  const ov = overridesFor(key);
  return Object.keys(ov.slots || {}).filter(n => !slots[n]);
}

/* A TONE IS A PREFERENCE, NOT A COMMAND. `subject2` is amber: 9.15:1 on the
 * night ground and 2.27:1 on the dusk one, because dusk is cream paper. The
 * same semantic role cannot be the same colour at both hours and still be
 * legible, so a tone is a ranked list and the renderer takes the first entry
 * that clears 4.5:1 against the ground it actually sits on.
 *
 * This is why colour is chosen here and contrast is resolved at paint: only
 * the renderer knows the hour. Rule 5 then has nothing left to catch. */
function toneColour(cands, ink, groundRole) {
  const list = Array.isArray(cands) ? cands : [cands];
  const bg = ink[groundRole || 'ground'];
  const lum = hex => {
    const f = v => { v /= 255; return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(parseInt(hex.slice(1, 3), 16)) + 0.7152 * f(parseInt(hex.slice(3, 5), 16)) + 0.0722 * f(parseInt(hex.slice(5, 7), 16));
  };
  const wc = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  for (let i = 0; i < list.length; i++) {
    const hex = ink[list[i]];
    if (hex && wc(hex, bg) >= 4.5) return hex;
  }
  return ink.structure;
}

const CONTENT = { contentFor, overBudget, toneColour, strayOverrides, setOverrides, overridesFor,
  setEpisode, episode, checkEpisode, useMetrics, STORY, MEASURES, fit, budgetOf, fittedSize, SHRINK_FLOOR };
if (typeof module !== 'undefined' && module.exports) module.exports = CONTENT;
if (typeof window !== 'undefined') window.CONTENT = CONTENT;
