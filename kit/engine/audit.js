#!/usr/bin/env node
/**
 * Dennis v2 — audit.js
 *
 * DESIGN.md §8's rules, executed. Not asserted, not described: run, with counts.
 *
 *   node engine/audit.js --check            # exit 1 on any FAIL or DID NOT RUN
 *   node engine/audit.js --check --json     # machine-readable
 *   node engine/audit.js                    # human report, always exit 0
 *
 * FOUR STATES, and this is load-bearing (§8):
 *
 *   pass          the rule ran and the condition held
 *   FAIL          the rule ran and the condition did not hold
 *   needs-data    the rule cannot run yet; the input it needs does not exist
 *   DID NOT RUN   the rule threw, or its input was present but unreadable
 *
 * `needs-data` and `DID NOT RUN` were one sentinel for exactly one rebuild, and
 * in that rebuild a rule that silently failed to execute was reported — and
 * counted — as a rule that was not due yet. A rule that did not run is LOUDER
 * than a rule that failed, because a failure is at least information.
 *
 * --check exits non-zero on FAIL *and* on DID NOT RUN. It does not exit on
 * needs-data: that is a schedule, not a defect.
 */

'use strict';
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const read = p => JSON.parse(fs.readFileSync(path.join(ROOT, p), 'utf8'));
const exists = p => fs.existsSync(path.join(ROOT, p));

/* ── colour ─────────────────────────────────────────────────────────────── */

const srgb = c => (c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4));
const rgb = hex => [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255);
const lum = hex => { const [r, g, b] = rgb(hex).map(srgb); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
const wcag = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };

function oklab(hex) {
  const [R, G, B] = rgb(hex).map(srgb);
  const l = Math.cbrt(0.4122214708 * R + 0.5363325363 * G + 0.0514459929 * B);
  const m = Math.cbrt(0.2119034982 * R + 0.6806995451 * G + 0.1073969566 * B);
  const s = Math.cbrt(0.0883024619 * R + 0.2817188376 * G + 0.6299787005 * B);
  return [0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
          1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
          0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s];
}
const deltaE = (a, b) => { const A = oklab(a), B = oklab(b); return Math.hypot(A[0] - B[0], A[1] - B[1], A[2] - B[2]); };

/* ── the run ────────────────────────────────────────────────────────────── */

const RULES = [];
const rule = (n, name, fn) => RULES.push({ n, name, fn });

/** A rule body returns {ok, count, note} or throws NeedsData. */
class NeedsData extends Error {}
const needs = what => { throw new NeedsData(what); };

const T = () => read('design-tokens.json');
const HOURS = ['night', 'dusk'];
const FIGURE_ROLES = ['skin', 'hair', 'shirt', 'trouser', 'prop'];
const TEXT_ROLES = ['structure', 'quiet', 'ground', 'band'];

const manifest = () => (exists('emit/manifest.json') ? read('emit/manifest.json') : needs('emit/manifest.json — run the emitter'));
const plates = () => (exists('emit/plates.json') ? read('emit/plates.json') : needs('emit/plates.json — run the emitter'));
const exportIndex = () => (exists('out/index.json') ? read('out/index.json') : needs('out/index.json — run engine/export.js'));
const roles = () => (exists('roles.fragment.json') ? read('roles.fragment.json') : needs('roles.fragment.json'));

rule(1, 'No gradients', () => {
  const m = manifest();
  const bad = Object.keys(m.assets).filter(k => (m.assets[k].gradients || 0) > 0);
  return { ok: !bad.length, count: `${Object.keys(m.assets).length} assets`,
    note: bad.length ? `gradient nodes in ${bad.slice(0, 3).join(', ')}` : 'No <linearGradient> or <radialGradient> in any emitted plate.' };
});

/* SCOPED BY FAMILY (§8.2). The flat law governs everything the host touches —
 * figure, rooms, title grounds. The ported plates are hand-drawn ink and fail
 * this by construction, which is the technique and not a defect: §0's
 * diagnosis is about a drawn FIGURE, and the six rejections were the host. An
 * asset opts out by declaring `drawn: true`, and the count says how many did,
 * so the exemption is visible in the report rather than silent. */
rule(2, 'No opacity shading (flat families)', () => {
  const m = manifest();
  const ids = Object.keys(m.assets);
  const flat = ids.filter(k => !m.assets[k].drawn);
  const drawn = ids.length - flat.length;
  const bad = flat.filter(k => (m.assets[k].partialOpacity || 0) > 0);
  return { ok: !bad.length, count: `${flat.length} flat assets${drawn ? `, ${drawn} drawn exempt` : ''}`,
    note: bad.length ? `partial opacity in ${bad.slice(0, 3).join(', ')}` : 'Every opacity in a flat-family asset is exactly 0 or 1. Drawn families keep their ink by declaration (§8.2), never by omission.' };
});

rule(3, 'Palette closure', () => {
  const t = T(), p = plates();
  const declared = {};
  HOURS.forEach(h => {
    const s = new Set([t.hours[h].contour]);
    Object.keys(t.hours[h].materials).forEach(k => { s.add(t.hours[h].materials[k].lit); s.add(t.hours[h].materials[k].shade); });
    Object.keys(t.hours[h].ink).forEach(k => s.add(t.hours[h].ink[k]));
    declared[h] = s;
  });
  let fills = 0; const stray = [];
  p.plates.forEach(pl => (pl.fills || []).forEach(f => { fills++; if (!declared[pl.hour] || !declared[pl.hour].has(f)) stray.push(`${pl.id}:${f}`); }));
  return { ok: !stray.length, count: `${fills} fills`,
    note: stray.length ? `outside the palette: ${stray.slice(0, 3).join(', ')}` : 'Every fill resolves through a role name; no literal is typed into a draw call.' };
});

rule(4, 'Uniform contour (flat families)', () => {
  const t = T(), p = plates();
  const seen = {}; let drawn = 0;
  p.plates.forEach(pl => {
    if (pl.drawn) { drawn++; return; }
    (pl.strokes || []).forEach(s => { (seen[pl.hour] = seen[pl.hour] || new Set()).add(`${s.colour}@${s.width}`); });
  });
  const bad = HOURS.filter(h => seen[h] && seen[h].size > 1);
  return { ok: !bad.length, count: HOURS.map(h => `${h} ${(seen[h] || new Set()).size}`).join(', ') + (drawn ? `, ${drawn} drawn exempt` : ''),
    note: bad.length ? `more than one contour in: ${bad.join(', ')}` : `One colour and one width per hour in the flat families: ${t.hours.night.contour} / ${t.hours.dusk.contour}. Drawn plates carry their own weights (§8.2).` };
});

rule(5, 'Type legibility ≥ 4.5:1', () => {
  const t = T(); const pairs = [];
  HOURS.forEach(h => {
    const I = t.hours[h].ink;
    pairs.push({ id: `${h} card title`, r: wcag(I.structure, I.ground) });
    pairs.push({ id: `${h} card caption`, r: wcag(I.quiet, I.ground) });
    // A slab sits on wall.shade, not on ink.ground (§5.3). Different ground,
    // so it needs its own measurement and its own pair.
    const g = t.hours[h].materials.wall.shade;
    const ranked = TEXT_ROLES.map(k => ({ k, r: wcag(I[k], g) })).sort((a, b) => b.r - a.r);
    pairs.push({ id: `${h} slab title`, r: ranked[0].r });
    pairs.push({ id: `${h} slab caption`, r: (ranked.slice(1).find(c => c.r >= 4.5) || ranked[1]).r });
  });
  // EVERY TYPE ENTRY ON EVERY EMITTED PLATE, against the ground that plate
  // declares behind it. Without this the rule only ever checked the two title
  // treatments — eleven data plates carrying forty type entries were emitted
  // unmeasured, which is the half of §5.3 that has no wall to hide behind.
  try {
    plates().plates.forEach(pl => (pl.typeOn || []).forEach(t => {
      const I = T().hours[pl.hour].ink;
      if (I[t.role] && I[t.on]) pairs.push({ id: `${pl.id} ${t.role}/${t.on}`, r: wcag(I[t.role], I[t.on]) });
    }));
  } catch (e) { if (!(e instanceof NeedsData)) throw e; }
  const worst = pairs.reduce((a, b) => (a.r < b.r ? a : b));
  return { ok: worst.r >= 4.5, count: `${pairs.length} pairs, worst ${worst.r.toFixed(2)}:1`,
    note: `Tightest is ${worst.id}. Sampled against the ground actually behind the box, never against the wall.` };
});

rule(6, 'Twin geometry', () => {
  const p = plates(), by = {};
  p.plates.forEach(pl => { (by[pl.twinId || pl.id] = by[pl.twinId || pl.id] || []).push(pl); });
  const bad = Object.keys(by).filter(k => by[k].length === 2 && by[k][0].geometryHash !== by[k][1].geometryHash);
  return { ok: !bad.length, count: `${Object.keys(by).length} twin pairs`,
    note: bad.length ? `geometry differs between hours: ${bad.slice(0, 3).join(', ')}` : 'Each hour pair shares one geometry hash — the hours are one shape list read through two colour tables.' };
});

rule(7, 'Role coherence', () => {
  const m = manifest();
  const bad = Object.keys(m.assets).filter(k => { const a = m.assets[k]; return a.role === 'host' && !a.hostAnchor; });
  return { ok: !bad.length, count: `${Object.keys(m.assets).length} assets`,
    note: bad.length ? `host-role without an anchor: ${bad.slice(0, 3).join(', ')}` : 'No asset can be selected into a host role without publishing an anchor.' };
});

rule(8, 'Anchor constant C', () => {
  const t = T(), P = t.proportion;
  const figY = 40, boxH = 720;
  const C = ((60 + P.shoulderFromCrown * 100) + (P.armUpperLength + P.armForeLength) * 100 - figY) / boxH;
  let declaredC = null;
  try { declaredC = manifest().C; } catch (e) { /* derivable without it */ }
  const ok = declaredC === null || Math.abs(declaredC - C) < 1e-4;
  return { ok, count: `C = ${C.toFixed(4)}`,
    note: 'Derived from the proportion table, so it is identical for every pose. A plate reporting a different C has a broken box (§2.5).' };
});

rule(9, 'Manifests are what the engine emits', () => {
  /* RUN, not named. This rule used to carry the name of emit_manifests --check
   * and not execute it, which is why it showed as passing while that script
   * crashed on this file's own shebang. It now rebuilds every manifest in
   * memory through engine/emit.js and diffs it against what is on disk. */
  const E = require('./emit');
  const b = E.build();
  /* The two files the other rules read are compared as LOADED — the thing the
   * audit actually judged — the rest against disk. Same build, one pass. */
  const loaded = { 'emit/manifest.json': manifest(), 'emit/plates.json': plates() };
  const diffs = Object.keys(b.outputs).filter(rel => rel in loaded
    ? JSON.stringify(loaded[rel], null, 1) !== b.outputs[rel]
    : !exists(rel) || fs.readFileSync(path.join(ROOT, rel), 'utf8') !== b.outputs[rel]);
  const r = { ok: !diffs.length, diffs, files: Object.keys(b.outputs).length };
  return { ok: r.ok, count: r.files + ' manifest files',
    note: r.ok ? 'emit/manifest.json, emit/plates.json, emit/slots.json and every <family>/manifest.json match a fresh build from the engine.'
      : r.diffs.length + ' differ from a fresh build: ' + r.diffs.slice(0, 5).join(', ') + ' \u2014 run node engine/emit.js' };
});
rule(10, 'No <text> nodes', () => {
  const m = manifest();
  const bad = Object.keys(m.assets).filter(k => (m.assets[k].textNodes || 0) > 0);
  return { ok: !bad.length, count: `${Object.keys(m.assets).length} assets`,
    note: bad.length ? `live text in ${bad.slice(0, 3).join(', ')}` : 'All type is outlined; nothing depends on a font at render time.' };
});

rule(11, '≥ 6 flat shapes per room', () => {
  const p = plates();
  const rooms = p.plates.filter(pl => pl.role === 'room');
  if (!rooms.length) needs('no room plates in emit/plates.json');
  const counts = rooms.map(r => r.shapeCount);
  const min = Math.min.apply(null, counts);
  return { ok: min >= 6, count: `${rooms.length} room plates, ${min}–${Math.max.apply(null, counts)} shapes`,
    note: 'Six is the measured floor at which a 9:16 crop stops reading as a backdrop (§4.3).' };
});

rule(12, 'Figure reads against wall', () => {
  const t = T(); let worst = Infinity, which = '';
  HOURS.forEach(h => FIGURE_ROLES.forEach(k => {
    const d = deltaE(t.hours[h].materials[k].lit, t.hours[h].materials.wall.lit);
    if (d < worst) { worst = d; which = `${h}.${k}`; }
  }));
  return { ok: worst >= 0.10, count: `${HOURS.length * FIGURE_ROLES.length} materials, worst ΔE ${worst.toFixed(3)}`,
    note: `Tightest is ${which}. Floor is 0.10 OKLab — deliberately not a WCAG ratio (§2.2a).` };
});

rule(13, 'Ink inside the published box', () => {
  const p = plates();
  const figs = p.plates.filter(pl => pl.role === 'host' && pl.inkBox && pl.box);
  if (!figs.length) needs('no host plates with inkBox in emit/plates.json');
  const over = figs.filter(f => f.inkBox[0] < f.box[0] || f.inkBox[1] < f.box[1]
    || f.inkBox[2] > f.box[0] + f.box[2] || f.inkBox[3] > f.box[1] + f.box[3]);
  return { ok: !over.length, count: `${figs.length} plates scanned, ${over.length} outside`,
    note: over.length ? `ink leaves the box: ${over.slice(0, 3).map(f => f.id).join(', ')}` : 'The box is a promise about where the ink is; a pose that breaks it is cropped at composite (§2.5).' };
});

rule(14, 'Anchor survives the portrait window', () => {
  const p = plates();
  const rooms = p.plates.filter(pl => pl.role === 'room' && pl.hostAnchor && pl.portraitWindow);
  if (!rooms.length) needs('no anchored room plates with a portrait window');
  const clipped = rooms.filter(r => {
    const [ax, ay, aw, ah] = r.hostAnchor, [wx, wy, ww, wh] = r.portraitWindow;
    return ax < wx || ay < wy || ax + aw > wx + ww || ay + ah > wy + wh;
  });
  return { ok: !clipped.length, count: `${rooms.length} anchored room plates, ${clipped.length} clipped`,
    note: clipped.length ? `clipped: ${clipped.slice(0, 3).map(r => r.id).join(', ')}` : '9:16 is a declared window, not a crop — the anchor has to be inside it with margin (§4.4a).' };
});

rule(15, 'Anchored rooms declare a split', () => {
  const p = plates();
  const rooms = p.plates.filter(pl => pl.role === 'room' && pl.hostAnchor);
  if (!rooms.length) needs('no anchored room plates');
  const missing = rooms.filter(r => typeof r.occlusionSplit !== 'number');
  return { ok: !missing.length, count: `${rooms.length - missing.length} of ${rooms.length}`,
    note: missing.length ? `no split: ${missing.slice(0, 3).map(r => r.id).join(', ')}` : 'Every room a host can stand in says which shapes paint in front of him (§4.5). A room with no anchor declares no split.' };
});

rule(16, 'Every drawn anchor comes from one derivation', () => {
  const t = T(), p = plates();
  const rooms = p.plates.filter(pl => pl.role === 'room' && pl.hostAnchor);
  if (!rooms.length) needs('no anchored room plates');
  // An anchor publishes a HEIGHT; its width follows from the figure's ink
  // aspect (§4.4a). A published width that does not match is a second source.
  const ratio = p.figureInkAspect;
  if (typeof ratio !== 'number') needs('plates.json does not publish figureInkAspect');
  const bad = rooms.filter(r => Math.abs(r.hostAnchor[2] - r.hostAnchor[3] * ratio) > 0.2);
  return { ok: !bad.length, count: `${rooms.length} anchor rects`,
    note: bad.length ? `width not derived: ${bad.slice(0, 3).map(r => r.id).join(', ')}` : 'Every anchor width equals height × the figure ink aspect. A self-consistent model plus one stale source is invisible to any other check.' };
});

rule(27, 'He stands clear of the front layer, composited', () => {
  /* rebuild-21. Four rooms hung a wall item across his head and two talk angles
   * stood him behind the monitor, while rules 14–16 passed: they check the
   * anchor and the split, never the room WITH HIM IN IT. emit.js composites
   * every pose that fits the room by the contract and measures the cover; this
   * fails any head under a front shape, and any room hiding more than 10% of
   * him above the desk top. The desk hiding his legs is the design. */
  const p = plates(), LIMIT = 10;
  const rooms = p.plates.filter(pl => pl.role === 'room' && pl.hostAnchor);
  if (!rooms.length) needs('no anchored room plates');
  const unmeasured = rooms.filter(r => !r.clearance);
  if (unmeasured.length) needs('room plates carry no clearance — run node engine/emit.js');
  const bad = rooms.filter(r => r.clearance.head.headCover > 0 || r.clearance.upper.upperCover > LIMIT);
  const worst = rooms.reduce((a, r) => Math.max(a, r.clearance.upper.upperCover), 0);
  return { ok: !bad.length, count: `${rooms.length - bad.length} of ${rooms.length}`,
    note: bad.length ? 'covered: ' + bad.slice(0, 4).map(r => `${r.id} head ${r.clearance.head.headCover}% / upper ${r.clearance.upper.upperCover}% (${r.clearance.upper.pose})`).join(', ')
      : `No head under a front shape; worst cover above the desk ${worst}% (limit ${LIMIT}%), over every pose that fits each room (§4.5).` };
});

rule(28, 'A chapter title has somewhere to land', () => {
  /* rebuild-21. None of the rebuilt rooms published a title slot, so every
   * chapter title would have dropped silently. This fails unless at least one
   * anchored room opens a chapter, and fails any title that leaves its card,
   * leaves the portrait window, or sits over him. Room units throughout. */
  const p = plates();
  const rooms = p.plates.filter(pl => pl.role === 'room' && pl.hostAnchor && pl.aspect === '16x9');
  if (!rooms.length) needs('no anchored room plates');
  const openers = rooms.filter(r => r.title);
  const inside = (a, b) => a[0] >= b[0] && a[1] >= b[1] && a[0] + a[2] <= b[0] + b[2] && a[1] + a[3] <= b[1] + b[3];
  const hits = (a, f) => !(a[0] + a[2] <= f[0] || a[0] >= f[2] || a[1] + a[3] <= f[1] || a[1] >= f[3]);
  const bad = openers.filter(r => !inside(r.title.slot, r.title.ground) || !inside(r.title.ground, r.portraitWindow)
    || (r.clearance && hits(r.title.ground, r.clearance.figureBox)));
  return { ok: openers.length > 0 && !bad.length, count: `${new Set(openers.map(r => r.twinId)).size} opener room(s), ${openers.length} plates`,
    note: !openers.length ? 'no anchored room publishes a title slot — every chapter title would drop'
      : bad.length ? 'title misplaced: ' + bad.map(r => r.id).join(', ')
      : 'Every opener room\u2019s title sits on its card, inside the portrait window, and clear of every pose that fits the room.' };
});

rule(25, 'Every talk, idle and blink strip actually moves', () => {
  /* The host exported 72 strip files byte-identical to the pose's still while
   * the manifest declared three-frame loops. This fails any strip whose frames
   * all hash the same. */
  const x = exportIndex(), groups = {};
  x.index.forEach(e => {
    if (!e.frame || !/^-(talk|idle|blink)$/.test(e.strip || '')) return;
    (groups[e.key + '@' + e.hour] = groups[e.key + '@' + e.hour] || new Set()).add(e.hash);
  });
  const keys = Object.keys(groups);
  if (!keys.length) needs('out/index.json lists no strip frames \u2014 run node engine/export.js');
  const frozen = keys.filter(k => groups[k].size < 2);
  return { ok: !frozen.length, count: keys.length + ' strips',
    note: frozen.length ? frozen.length + ' strips have identical frames: ' + frozen.slice(0, 4).join(', ')
      : 'Every talk, idle and blink strip has at least two distinct frames, measured by hash off the exported files.' };
});

rule(26, 'Every exported file frames its own ink', () => {
  /* The host exported into the room's 320x180 box: a head cut off at the neck
   * and, for sitting-at-desk, an empty file. This fails any file whose ink box
   * leaves its viewBox by more than a 10% bleed allowance per edge.
   *
   * The allowance is measured, not picked: two plates run a band deliberately
   * off the side edges — paper/headline-band-t3-9x16 at 9.0%, shorts/hook-card-t5
   * at 5.3% — and every other file of 1,964 stays within 3.7%. The failure this
   * rule exists for is an order of magnitude outside it: the old host export
   * left 25% of the figure's width and three times its height out of frame. */
  const x = exportIndex(), B = 0.10, bad = [];
  let n = 0;
  x.index.forEach(e => {
    if (!e.viewBox || !e.inkBox) return;
    n++;
    const [vx, vy, vw, vh] = e.viewBox, [x0, y0, x1, y1] = e.inkBox;
    if (x0 < vx - vw * B || y0 < vy - vh * B || x1 > vx + vw * (1 + B) || y1 > vy + vh * (1 + B)) bad.push(e.file);
  });
  if (!n) needs('out/index.json carries no viewBox/inkBox \u2014 run node engine/export.js');
  return { ok: !bad.length, count: n + ' files',
    note: bad.length ? bad.length + ' files draw outside their viewBox: ' + bad.slice(0, 4).join(', ')
      : 'Every exported file contains its own ink, within a 10% bleed per edge.' };
});

rule(24, 'Every plate is reachable and explains itself', () => {
  const m = manifest();
  const rf = roles();
  const ids = Object.keys(m.assets).filter(k => m.assets[k].role === 'plate');
  const entryFor = id => rf[id + '-16x9'] || rf[id + '-9x16'] || rf[id];
  const noPurpose = ids.filter(id => { const e = entryFor(id); return !e || !e.purpose; });
  const unreachable = ids.filter(id => {
    const e = entryFor(id);
    return !e || (!(e.chapter_types || []).length && !e.reached_by);
  });
  const withCaution = ids.filter(id => { const e = entryFor(id); return e && e.caution; }).length;
  return { ok: !noPurpose.length && !unreachable.length,
    count: ids.length + ' plates, ' + withCaution + ' with a caution',
    note: noPurpose.length ? 'no purpose line: ' + noPurpose.slice(0, 4).join(', ')
      : unreachable.length ? 'reachable by nothing: ' + unreachable.slice(0, 4).join(', ')
      : 'A plate reaches the writer as a purpose line, not as a bare name and a list of slot names. '
        + 'Before this rule, 0 of 95 carried one. A plate named by no chapter type must say how it IS '
        + 'reached — as a [SCRIBBLE:] mark, a shorts shot list, the compositor or room rotation.' };
});

rule(23, 'No rendered string is wider than its slot box', () => {
  const p = plates();
  if (p.widestRatio === undefined) needs('plates.json does not report widestRatio — run engine/content.js');
  const over = p.overflowing || [];
  return { ok: !over.length,
    count: 'widest ' + p.widestRatio + 'x of box'
      + (p.loosePublishedBudgets ? ', ' + p.loosePublishedBudgets + ' loose published budgets' : ''),
    note: over.length
      ? over.length + ' strings render outside their box, worst ' + over[0].key + '.' + over[0].slot
      : 'Measured with engine/budget.js\'s own per-class advances off the shipped fonts\' hmtx table, at the '
        + 'size the renderer will actually use (content.js fittedSize). CORRECTION, rebuild-15: this rule '
        + 'previously reported "314 slots publish a budget wider than their own geometry" and that was an '
        + 'artefact of measuring with a flat 0.54em estimate instead of the real metric. Re-measured with '
        + 'budget.js the count is 0 \u2014 the published budgets were right and the measurement was wrong. What '
        + 'remains true is the original finding: 68 strings did render outside their boxes, because fit() '
        + 'only trimmed where a slot published a budget and many publish none.' };
});

rule(22, 'Every emitted plate has an export entry', () => {
  const m = manifest(), x = exportIndex();
  const want = Object.keys(m.assets).filter(k => m.assets[k].role === 'plate');
  const have = {};
  x.index.forEach(e => { if (!e.error) have[e.key.replace(/-(16x9|9x16)$/, '') + '@' + e.hour] = 1; });
  const missing = [];
  want.forEach(k => ['night', 'dusk'].forEach(h => { if (!have[k + '@' + h]) missing.push(k + '@' + h); }));
  const failed = x.index.filter(e => e.error);
  return { ok: !missing.length && !failed.length,
    count: x.index.length + ' exported, ' + want.length + ' plate assets',
    note: failed.length ? failed.length + ' failed to render: ' + failed.slice(0, 3).map(f => f.key).join(', ')
      : missing.length ? 'emitted but never exported: ' + missing.slice(0, 4).join(', ')
      : 'The pipeline closes: every plate the audit passed has a file at both hours, from one code path. A second path is how a 2.33x lower third reached the last pack.' };
});

rule(21, 'Every override names a slot that exists', () => {
  const p = plates();
  const stray = p.strayOverrides || [];
  const count = p.overrideCount;
  if (count === undefined) needs('plates.json does not report overrideCount — run engine/emit.js');
  return { ok: !stray.length, count: count + ' overrides',
    note: stray.length
      ? 'these name no such slot: ' + stray.slice(0, 4).map(s => s.key + '.' + s.slot).join(', ')
      : 'A typo in content-overrides.json silently does nothing — you edit the text, nothing changes, and there is no error to read. This is that error.' };
});

rule(20, 'Every plate slot is filled and within budget', () => {
  const p = plates();
  const withSlots = p.plates.filter(pl => typeof pl.filledSlots === 'number');
  if (!withSlots.length) needs('no plate reports filledSlots — run engine/content.js');
  // A plate with NO text slots is not an unfilled plate — overlays/row-band is
  // a pure graphic band and has nothing to fill. The rule fired on it on its
  // first run, which is the distinction worth encoding rather than excusing.
  const empty = withSlots.filter(pl => pl.filledSlots === 0 && (pl.textSlots === undefined || pl.textSlots > 0));
  const graphic = withSlots.filter(pl => pl.textSlots === 0).length;
  const over = p.overBudget || [];
  return { ok: !empty.length && !over.length,
    count: withSlots.reduce((a2, b) => a2 + b.filledSlots, 0) + ' slots across ' + withSlots.length + ' plates'
      + (graphic ? ', ' + graphic + ' graphic-only' : ''),
    note: empty.length ? 'no content: ' + empty.slice(0, 3).map(x => x.id).join(', ')
      : over.length ? over.length + ' strings over their slot maxChars'
      : 'Content is generated from each plate\'s own slot table (engine/content.js) and every string is checked against that slot\'s maxChars. A plate that only fits because the words were chosen short breaks on the first real script.' };
});

rule(19, 'The drawn exemption is declared and bounded', () => {
  const m = manifest();
  const DRAWN = ['annotations', 'cards', 'charts', 'cycles', 'figures', 'frames', 'overlays', 'paper', 'peers', 'shorts', 'structure', 'tables'];
  const ids = Object.keys(m.assets);
  const claiming = ids.filter(k => m.assets[k].drawn);
  // An asset may only claim the exemption if its family is on the list, and no
  // host or room asset may claim it at all — that is the line §0 actually drew.
  const illegal = claiming.filter(k => DRAWN.indexOf(m.assets[k].dir) < 0);
  const hostDrawn = ids.filter(k => m.assets[k].drawn && (m.assets[k].dir === 'host' || m.assets[k].dir === 'room'));
  return { ok: !illegal.length && !hostDrawn.length,
    count: `${claiming.length} of ${ids.length} claim it`,
    note: illegal.length || hostDrawn.length
      ? `illegal exemption: ${illegal.concat(hostDrawn).slice(0, 3).join(', ')}`
      : 'Only the twelve drawn families may opt out of rules 2 and 4, and no host or room asset may — the figure is what §0 was about. New at the port.' };
});

rule(17, 'Band direction per hour', () => {
  const t = T();
  const got = HOURS.map(h => {
    const I = t.hours[h].ink;
    const want = h === 'night' ? 'lighter' : 'darker';
    const is = lum(I.band) > lum(I.ground) ? 'lighter' : 'darker';
    return { h, want, is, ok: want === is };
  });
  const bad = got.filter(g => !g.ok);
  return { ok: !bad.length, count: got.map(g => `${g.h} ${g.is}`).join(', '),
    note: bad.length ? `wrong direction: ${bad.map(g => g.h).join(', ')}` : 'Night bands sit lighter than their ground, dusk darker (§5.1) — backwards is the muddy inversion §5 forbids.' };
});

rule(18, 'Both title treatments legible, both hours', () => {
  const t = T(); const out = [];
  HOURS.forEach(h => {
    const I = t.hours[h].ink;
    out.push({ id: `${h} card`, title: wcag(I.structure, I.ground), cap: wcag(I.quiet, I.ground) });
    const g = t.hours[h].materials.wall.shade;
    const ranked = TEXT_ROLES.map(k => ({ k, r: wcag(I[k], g) })).sort((a, b) => b.r - a.r);
    const cap = ranked.slice(1).find(c => c.r >= 4.5) || ranked[1];
    out.push({ id: `${h} slab`, title: ranked[0].r, cap: cap.r, pair: `${ranked[0].k} / ${cap.k}` });
  });
  const worst = out.reduce((a, b) => (Math.min(a.title, a.cap) < Math.min(b.title, b.cap) ? a : b));
  return { ok: Math.min(worst.title, worst.cap) >= 4.5,
    count: `${out.length} combinations, worst ${Math.min(worst.title, worst.cap).toFixed(2)}:1`,
    note: `Tightest is ${worst.id}. A slab sits on wall.shade and a card on ink.ground, so the pair inverts at dusk (§5.3). Candidates are the text roles only — contrast is a floor, not a selector.` };
});

/* ── report ─────────────────────────────────────────────────────────────── */

function run() {
  return RULES.map(r => {
    try {
      const out = r.fn();
      return { n: r.n, name: r.name, state: out.ok ? 'pass' : 'FAIL', count: out.count, note: out.note };
    } catch (e) {
      if (e instanceof NeedsData) return { n: r.n, name: r.name, state: 'needs-data', count: '—', note: String(e.message) };
      return { n: r.n, name: r.name, state: 'DID NOT RUN', count: '—', note: `${e && e.message ? e.message : e}` };
    }
  });
}

const argv = process.argv.slice(2);
const results = run();
const tally = s => results.filter(r => r.state === s).length;

if (argv.includes('--json')) {
  process.stdout.write(JSON.stringify({ results, summary: { pass: tally('pass'), fail: tally('FAIL'), needsData: tally('needs-data'), didNotRun: tally('DID NOT RUN') } }, null, 1) + '\n');
} else {
  const pad = s => String(s).padStart(2);
  results.forEach(r => {
    const tag = { 'pass': '  pass', 'FAIL': '  FAIL', 'needs-data': '  data?', 'DID NOT RUN': ' !!RUN' }[r.state];
    process.stdout.write(`${tag}  ${pad(r.n)}  ${r.name}\n        ${r.count}\n        ${r.note}\n\n`);
  });
  const ran = results.filter(r => r.state === 'pass' || r.state === 'FAIL').length;
  process.stdout.write(`${tally('pass')} of ${ran} runnable rules pass · ${tally('needs-data')} need data`
    + (tally('DID NOT RUN') ? ` · ${tally('DID NOT RUN')} DID NOT RUN` : '') + '\n');
}

// --check fails on FAIL and on DID NOT RUN. needs-data is a schedule, not a defect.
if (argv.includes('--check') && (tally('FAIL') || tally('DID NOT RUN'))) process.exit(1);
