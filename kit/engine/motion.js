/* Dennis v2 — motion.js (rebuild-35, anchors rebuild-38, rebuild-40)
 *
 * THE MOTION CATALOGUE. Thirteen moves, published as DATA rather than baked
 * frames: each names what it applies to, its length in frames at 12 fps, its
 * easing and whether it plays once or loops, and exports the pure function a
 * renderer calls per frame. The plates stay stills; a renderer plays a move
 * OVER a plate's published slots, so no plate is re-drawn per frame and a move
 * can never disagree with the plate it animates.
 *
 * emit.js writes emit/motion.json from this file: MOVES, TIMINGS, anchorFor()
 * for every slot table, and roomTargets() for every room. That file is the
 * contract; the review page is not (rebuild-40).
 *
 * Rules every move keeps (DESIGN.md §5, audit rule 2): no partial opacity, so
 * nothing fades; things draw on, grow, slide, or appear on a frame. The ink is
 * always the slot's published ink or the room's own material. Every loop is
 * seamless: frame 12 is frame 0 (rebuild-40).
 */
'use strict';
(function (g) {
  const FPS = 12;
  const clamp = t => Math.max(0, Math.min(1, t));
  const E = {
    linear: t => clamp(t),
    out: t => 1 - Math.pow(1 - clamp(t), 3),
    inOut: t => { t = clamp(t); return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2; },
    /* a settle: overshoots by ~6% and comes back, for things that land */
    land: t => { t = clamp(t); const c = 1.70158 * 0.6; return 1 + (c + 1) * Math.pow(t - 1, 3) + c * Math.pow(t - 1, 2); },
  };

  /* count-up: the figure in a string counted from zero, keeping its prefix,
   * suffix, sign and decimals ("$3.1bn", "−40%", "+2.6pt", "12,400"). */
  function countText(str, t) {
    const m = String(str).match(/^(.*?)([\u2212+-]?)(\d[\d,]*)(\.\d+)?(.*)$/);
    if (!m) return str;
    const whole = parseFloat((m[3] + (m[4] || '')).replace(/,/g, '')), d = m[4] ? m[4].length - 1 : 0;
    const v = whole * E.out(t);
    let s = v.toFixed(d); if (m[3].indexOf(',') >= 0) { const p = s.split('.'); p[0] = p[0].replace(/\B(?=(\d{3})+(?!\d))/g, ','); s = p.join('.'); }
    return m[1] + (v === 0 ? '' : m[2]) + s + m[5];
  }
  /* a reveal box: the part of `box` shown at t, growing from one edge */
  function reveal(box, t, from) {
    const k = E.out(t), b = box;
    if (from === 'bottom') return { x: b.x, y: b.y + b.h * (1 - k), w: b.w, h: b.h * k };
    if (from === 'top') return { x: b.x, y: b.y, w: b.w, h: b.h * k };
    return { x: b.x, y: b.y, w: b.w * (from === 'left-linear' ? E.linear(t) : k), h: b.h };
  }
  const outset = (b, p) => ({ x: b.x - p, y: b.y - p, w: b.w + p * 2, h: b.h + p * 2 });
  /* bars-grow: column i starts one frame after column i-1 (rebuild-40: the
   * catalogue's stagger, now a function so it cannot be read two ways). */
  const stagger = (f, i, frames) => clamp((f - i) / Math.max(1, frames - 1));
  /* a hand-drawn ellipse round a box, as a path and its length, for dash draw-on */
  function penCircle(box, seed) {
    const cx = box.x + box.w / 2, cy = box.y + box.h / 2, rx = box.w / 2 + 26, ry = box.h / 2 + 18, n = 40, pts = [];
    let s = seed || 7; const r = () => ((s = (s * 9301 + 49297) % 233280) / 233280);
    for (let i = 0; i <= n + 4; i++) { const a = -Math.PI * 0.62 + (i / n) * Math.PI * 2, j = 1 + (r() - 0.5) * 0.06;
      pts.push([cx + Math.cos(a) * rx * j, cy + Math.sin(a) * ry * j]); }
    let len = 0; for (let i = 1; i < pts.length; i++) len += Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]);
    return { d: 'M' + pts.map(p => p[0].toFixed(1) + ',' + p[1].toFixed(1)).join(' L'), len };
  }
  const penDash = (len, t) => ({ dasharray: len, dashoffset: len * (1 - E.inOut(t)) });
  /* zoom: the viewBox from the whole canvas to a slot, eased */
  function zoomBox(canvas, box, t, pad) {
    const k = E.inOut(t), p = pad == null ? 60 : pad, ar = canvas[0] / canvas[1];
    let w = box.w + p * 2, h = w / ar; if (h < box.h + p * 2) { h = box.h + p * 2; w = h * ar; }
    const tx = box.x + box.w / 2 - w / 2, ty = box.y + box.h / 2 - h / 2;
    return [tx * k, ty * k, canvas[0] + (w - canvas[0]) * k, canvas[1] + (h - canvas[1]) * k];
  }
  /* loops. flicker: which frames the screen and lamp drop to their shade tone */
  const SCREEN_PULSE = [0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0];
  const LAMP_FLICKER = [0, 0, 0, 0, 0, 0, 0, 1, 0, 1, 0, 0];
  /* snow: flakes falling in a window box, seeded, looping over 12 frames.
   * rebuild-40: each flake falls a WHOLE number of pane-heights per loop (1 or
   * 2), so frame 12 lands every flake where frame 0 had it. At fractional
   * speeds the loop jumped at the seam. The sway is a full sine per loop. */
  function snow(box, frame, n) {
    const out = []; let s = 11; const r = () => ((s = (s * 9301 + 49297) % 233280) / 233280);
    for (let i = 0; i < (n || 26); i++) {
      const x0 = r(), y0 = r(), sz = 0.8 + r() * 1.4, sp = r() < 0.7 ? 1 : 2;
      const y = (y0 + (frame / 12) * sp) % 1, x = (x0 + Math.sin((frame / 12) * Math.PI * 2 + i) * 0.02 + 1) % 1;
      out.push({ x: box.x + x * box.w, y: box.y + y * box.h, r: sz });
    }
    return out;
  }
  /* rain: the snow field at three times the speed, as short strokes. 3 and 6
   * pane-heights a loop: whole numbers, so it is seamless too. */
  const RAIN = (box, frame) => snow(box, frame * 3, 40).map(f => ({ x: f.x, y: f.y, w: 0.6, h: 5 }));
  /* twinkle: each bulb steps one ink every 4 frames. Three inks x 4 frames is
   * the 12-frame loop (rebuild-40; at 3 frames the cycle was 9 and one state
   * held for 6 frames at the seam). `phase` is the bulb's ink at frame 0, as
   * published in roomTargets().bulbs. */
  const TWINKLE = ['attention', 'subject2', 'subject'];
  const TWINKLE_STEP = 4;
  const twinkleInk = (phase, frame) => TWINKLE[(phase + Math.floor(frame / TWINKLE_STEP)) % 3];
  /* pin-drop: a card falls onto the wall and swings once to rest */
  function pinDrop(t) { const k = E.out(t); return { dy: -60 * (1 - k), rot: -4 + 10 * Math.sin(k * Math.PI * 2.2) * (1 - k) }; }
  /* slide-in: an overlay from off the left edge to its place, landing */
  const slideX = (w, t) => -(w + 40) * (1 - E.land(t));
  /* tick-over: the old number up and out, the new one up and in */
  const tick = (h, t) => { const k = E.inOut(t); return { oldY: -h * k, newY: h * (1 - k) }; };

  /* Timings and placements a renderer would otherwise have to guess
   * (rebuild-40: both were guessed by the bot, and both guesses were close). */
  const TIMINGS = {
    'tick-over': { startFrame: 3, startSeconds: 0.25, frames: 6, holdFrames: 24,
      why: 'the old number is on screen for a quarter second so it is read, turns over by 0.75 s, and the new one holds the remaining 1.25 s of the two-second bumper. Frames are 0-based: frame 3 is the fourth frame.' },
    'source-tag': { tag: { '16x9': [900, 72], '9x16': [980, 92] }, gap: 24, safeBottom: { '16x9': 1026, '9x16': 1560 }, left: { '16x9': 96 },
      rule: '16:9: left edge at x 96 (the 5% safe margin), bottom edge 24 above the lower of the safe bottom (1026) and the plate\u2019s caption. 9:16: centred, bottom edge 24 above the lower of the shorts safe line (1560) and the caption. Over a plate, use anchors.plates[key]["slide-in"], which applies this rule to that plate\u2019s own slots and says whether the spot is clear. Where it says clear: false, do not lay the tag over that plate: put it on the next room or host shot, or speak the source.',
      default: { '16x9': { x: 96, y: 930 }, '9x16': { x: 50, y: 1444 } } },
    'highlight': { weight: 5, gap: 2, widthOfBox: 0.8, why: 'the same rect the data layer draws for a slot that publishes underline: y = box bottom + 2, height 5, width 0.8 of the box' },
    'zoom-to-slot': { pad: 60 },
    'line-draw': { bleed: 14, why: 'the clip is the plot box grown by 14 on every side, so the line\u2019s half-weight and the end points are not cut; nothing else on the plate moves with it' },
  };

  const MOVES = [
    { id: 'count-up', group: 'plate', frames: 7, playback: 'once', ease: 'out', appliesTo: 'the figure slot anchorFor() names', how: 'countText(text, t)' },
    { id: 'line-draw', group: 'plate', frames: 10, playback: 'once', ease: 'linear', appliesTo: 'a plot-area with a linePath (anchor.box, and anchor.also for small-multiple panels, all drawn on together)', how: 'clip the data layer to reveal(outset(anchor.box, anchor.bleed), t, "left-linear"); the accent point appears on the last frame. Only the line moves: a figure counting up beside it is the count-up move, cued separately.' },
    { id: 'bars-grow', group: 'plate', frames: 8, playback: 'once', ease: 'out', appliesTo: 'plates with bar or stacked columns (anchor.columns, oldest first)', how: 'column i is clipped to reveal(column.box, E.out(stagger(f, i, frames)), "bottom"), so each starts one frame after the one before; the accented column, if the data names one, goes last. The move lasts frames + columns - 1 frames.' },
    { id: 'highlight', group: 'plate', frames: 6, playback: 'once', ease: 'out', appliesTo: 'a slot with underline, or the quote slots', how: 'a rect at TIMINGS.highlight under the line: anchor.lines[n-1] where n is the number of lines the copy sets, or anchor.box when there are no lines; width = reveal(line, t, "left").w x 0.8' },
    { id: 'pen-circle', group: 'plate', frames: 8, playback: 'once', ease: 'inOut', appliesTo: 'the figure slot anchorFor() names; the "this one" beat', how: 'penCircle(inkBox(anchor.box, text, fittedSize, anchor.align, anchor.adv)) stroked in attention with penDash(len, t). Always ring the ink, never the slot (anchor.shrink = "ink").' },
    { id: 'zoom-to-slot', group: 'plate', frames: 12, playback: 'once', ease: 'inOut', appliesTo: 'paper plates; the push in on a footnote', how: 'viewBox = zoomBox(canvas, anchor.box, t, 60): the slot as published, padding 60' },
    { id: 'screen-flicker', group: 'room', frames: 12, playback: 'loop', ease: null, appliesTo: 'rooms whose rooms[id].flicker or .lamp is not empty', how: 'the shapes in rooms[id].flicker take their shade tone where SCREEN_PULSE[f]; rooms[id].lamp where LAMP_FLICKER[f]. Window and door panes and the daylight they cast (rooms[id].panes, .daylight) never flicker.' },
    { id: 'window-snow', group: 'room', frames: 12, playback: 'loop', ease: null, appliesTo: 'rooms with a pane of kind "window"; December, with the Christmas set', how: 'snow(pane.box, f) as paper-role squares of side r, painted straight after the pane shape (pane.shape), so every later shape (frame bars, sill, tree, him) paints over the flakes' },
    { id: 'window-rain', group: 'room', frames: 12, playback: 'loop', ease: null, appliesTo: 'rooms with a pane of kind "window"; a gloomy episode', how: 'RAIN(pane.box, f) as short glow-shade strokes, painted straight after the pane shape, like the snow' },
    { id: 'lights-twinkle', group: 'room', frames: 12, playback: 'loop', ease: null, appliesTo: 'the -christmas room assets (rooms[id].bulbs)', how: 'bulb b takes twinkleInk(b.phase, f): one ink step every 4 frames' },
    { id: 'card-pin', group: 'room', frames: 9, playback: 'once', ease: 'out', appliesTo: 'the board angles (rooms[id].pin); a new card on the wall of calls', how: 'the card translated pinDrop(t).dy and rotated pinDrop(t).rot about pin.pin' },
    { id: 'slide-in', group: 'overlay', frames: 6, playback: 'once', ease: 'land', appliesTo: 'overlays/lower-third, overlays/source-tag', how: 'translateX(slideX(width, t)) into its place; for the source tag the place is TIMINGS["source-tag"], or the plate\u2019s own anchor. Out is the same move reversed.' },
    { id: 'tick-over', group: 'overlay', frames: 6, playback: 'once', ease: 'inOut', appliesTo: 'structure/chapter-bumper num slot', how: 'from TIMINGS["tick-over"].startFrame of the bumper\u2019s hold: old number at tick(h, t).oldY, new at .newY, both clipped to the slot' },
  ];

  /* ── ANCHORS (rebuild-38, rebuild-40). Where a move lands is READ from the
   * plate's own published slots, never placed by eye. anchorFor(m, key)
   * returns a record per move, or null where the plate has nothing for that
   * move to act on (the renderer then skips it). */
  const NOT_TEXT = ['band', 'marker', 'plot-area', 'bars', 'bridge', 'path', 'spark', 'point-column', 'bar', 'media', 'highlight-band', 'wraps', 'control', 'mark-area'];
  const textSlots = m => Object.keys(m.slots || {}).filter(k => { const s = m.slots[k]; return s && !s.container && !s.region && !s.overlay && NOT_TEXT.indexOf(s.role) < 0; });
  const box = s => s && { x: s.x, y: s.y, w: s.w, h: s.h };
  const IDX = /^(.*?)-(\d+)(?:-(\d+))?$/;
  /* rebuild-40: a numbered slot resolves to the LATEST of its row. Where the
   * siblings sit side by side (a sheet's year columns, a bar row's values),
   * the rightmost is the latest period, which is the one being talked about;
   * where they stack (ranked rows), the first row stays. */
  function latest(S, k) {
    const q = k.match(IDX); if (!q) return k;
    const sib = Object.keys(S).filter(j => { const r = j.match(IDX); return r && r[1] === q[1] && (q[3] ? r[3] && r[2] === q[2] : !r[3]); });
    const row = sib.filter(j => Math.abs(S[j].y - S[k].y) < 4);
    return row.length < 2 ? k : row.sort((a, b) => S[b].x - S[a].x)[0];
  }
  function theNumber(m) {
    const S = m.slots || {}, R = m.typeRoles || {};
    const call = Object.keys(S).find(k => S[k + '-label'] && S[k + '-detail']);
    if (call) return call;
    const named = ['num', 'delta', 'headline-figure', 'figure', 'value'].find(k => S[k]);
    if (named) return named;
    /* the biggest one-line slot, a figure (Courier) before a word at the same size */
    const fig = k => ((R[S[k].role] || {}).font === 'Courier Prime' ? 1 : 0), sz = k => (R[S[k].role] || {}).size || 0;
    /* rebuild-41b: ranked by the AUTHORED size (typeRoles[r].authoredSize), not the
     * published one. The 9:16 type floor lifts kickers, units and headlines to
     * the figures' size, so the published size no longer says which slot is the
     * figure; the authored hierarchy still does, on every family, and reproduces
     * the rebuild-40 anchor wherever the slot still exists. */
    const sz2 = k => { const R0 = R[S[k].role] || {}; return R0.authoredSize != null ? R0.authoredSize : (R0.size || 0); };
    /* a box authored for two lines stays a wrapping slot even where the floor
     * now sets one line in it (share-of headlines, wire-strip headlines) */
    const port = Array.isArray(m.canvas) && m.canvas[1] > m.canvas[0]; // the floor is 9:16 only
    const wraps = k => S[k].maxLines > 1 || (port && S[k].maxLines != null && S[k].authoredLines > 1);
    const big = textSlots(m).filter(k => !wraps(k)).sort((a, b) => (sz2(b) + fig(b) * 0.5) - (sz2(a) + fig(a) * 0.5))[0];
    return big ? latest(S, big) : null;
  }
  function figureAnchor(m, k) {
    const s = m.slots[k], R = (m.typeRoles || {})[s.role] || {};
    return { slot: k, box: box(s), align: s.align || 'left', size: R.size || null, adv: R.font === 'Courier Prime' ? 0.6 : 0.5, shrink: 'ink' };
  }
  function linesOf(m, s) {
    const R = (m.typeRoles || {})[s.role] || {}, n = s.maxLines || R.maxLines || 1;
    if (n < 2) return null;
    const pitch = R.size ? Math.round(R.size * 1.16) : Math.floor(s.h / n);
    return Array.from({ length: n }, (_, i) => ({ x: s.x, y: s.y + pitch * i, w: s.w, h: pitch }));
  }
  function tagPlace(m) {
    const S = m.slots || {}, cv = m.canvas || [1920, 1080], land = cv[0] > cv[1], T = TIMINGS['source-tag'];
    const [tw, th] = land ? T.tag['16x9'] : T.tag['9x16'];
    const cap = S.caption, floor = Math.min(land ? T.safeBottom['16x9'] : T.safeBottom['9x16'], cap ? cap.y : Infinity);
    const y = Math.round(floor - T.gap - th);
    const xs = land ? [T.left['16x9'], cv[0] - T.left['16x9'] - tw] : [Math.round((cv[0] - tw) / 2)];
    const hits = b => Object.keys(S).filter(k => { const s = S[k]; if (s.w >= cv[0] * 0.9 && s.h >= cv[1] * 0.9) return false;
      return s.x < b.x + b.w && s.x + s.w > b.x && s.y < b.y + b.h && s.y + s.h > b.y; });
    for (const x of xs) { const b = { x, y, w: tw, h: th }; if (!hits(b).length) return { slot: null, box: b, clear: true }; }
    /* no clear spot: say so and name what it would cover. The tag then goes on
     * the next room or host shot, or the source is spoken; never over the plate. */
    const b = { x: xs[0], y, w: tw, h: th };
    return { slot: null, box: b, clear: false, covers: hits(b) };
  }
  function anchorFor(m, key) {
    const S = m.slots || {};
    const num = theNumber(m);
    const plots = Object.keys(S).filter(k => S[k].role === 'plot-area');
    const plotKey = S['plot-area'] ? 'plot-area' : plots[0] || Object.keys(S).find(k => S[k].container && !/^(point|bar|pair|step|spark)-/.test(k)) || null;
    /* columns: bar-N, or stacked part-a-N + part-b-N, oldest (leftmost) first */
    const byN = re => Object.keys(S).filter(k => re.test(k)).sort((a, b) => +a.match(/(\d+)$/)[1] - +b.match(/(\d+)$/)[1]);
    let columns = byN(/^bar-\d+$/).filter(k => !(S[k].axis === 'horizontal')).map(k => ({ slots: [k], box: box(S[k]) }));
    if (!columns.length) columns = byN(/^part-a-\d+$/).map(k => { const n = k.match(/(\d+)$/)[1]; return { slots: [k, 'part-b-' + n].filter(j => S[j]), box: box(S[k]) }; });
    const under = Object.keys(S).find(k => S[k].underline);
    const quote = under || ['quote', 'quote-1', 'marked'].find(k => S[k]) || textSlots(m).find(k => S[k].maxLines > 2) || null;
    const qa = quote ? Object.assign({ slot: quote, box: box(S[quote]) }, linesOf(m, S[quote]) ? { lines: linesOf(m, S[quote]) } : {}) : null;
    return {
      'count-up': num ? figureAnchor(m, num) : null,
      'pen-circle': num ? figureAnchor(m, num) : null,
      'highlight': qa,
      'zoom-to-slot': quote ? { slot: quote, box: box(S[quote]), pad: TIMINGS['zoom-to-slot'].pad } : null,
      'line-draw': plotKey ? Object.assign({ slot: plotKey, box: box(S[plotKey]), bleed: TIMINGS['line-draw'].bleed }, plots.length > 1 && !S['plot-area'] ? { also: plots.slice(1) } : {}) : null,
      'bars-grow': columns.length ? { slot: plotKey, box: plotKey ? box(S[plotKey]) : null, columns } : null,
      'tick-over': S.num && /chapter-bumper/.test(key || '') ? Object.assign({ slot: 'num', box: box(S.num) }, TIMINGS['tick-over']) : null,
      'slide-in': tagPlace(m),
    };
  }
  /* rooms: the card lands on the wall it belongs to, over the cards already
   * there (the wall-of-calls-pinned beat), centred on their union. `boxOf`
   * is the caller's path-box function ({x, y, w, h}), so this file stays geometry-free. */
  function pinSpot(room, boxOf) {
    const cards = room.shapes.filter(s => s.role === 'paper' && s.tone !== 'shade' && !s.ink).map(s => boxOf(s.d));
    if (!cards.length) return null;
    const x0 = Math.min(...cards.map(b => b.x)), y0 = Math.min(...cards.map(b => b.y)), x1 = Math.max(...cards.map(b => b.x + b.w)), y1 = Math.max(...cards.map(b => b.y + b.h));
    const cw = Math.max(18, Math.min(34, (x1 - x0) * 0.22)), ch = cw * 0.7;
    return { x: (x0 + x1) / 2 - cw / 2, y: y0 + (y1 - y0) * 0.35, w: cw, h: ch, pin: [(x0 + x1) / 2, y0 + (y1 - y0) * 0.35] };
  }
  /* rebuild-40: WHICH SHAPES each room move touches, by index into the room's
   * shape list (the nth <path> of the room file). A pane is a lit glow high on
   * the wall and big enough to be glass (the test dress() in kit-model.js uses
   * to hang the lights); daylight is a shade glow reaching the floor edge, the
   * pane's cast. Neither is a screen, so neither flickers. `sees` is the
   * angle's PLAN.sees list, which says whether the pane is a window or a door. */
  function roomTargets(room, sees, boxOf) {
    const r1 = v => Math.round(v * 10) / 10, rb = b => ({ x: r1(b.x), y: r1(b.y), w: r1(b.w), h: r1(b.h) });
    const kind = (sees || []).indexOf('window') >= 0 ? 'window' : (sees || []).indexOf('door') >= 0 ? 'door' : null;
    const out = { panes: [], daylight: [], flicker: [], lamp: [], bulbs: [] };
    room.shapes.forEach((s, i) => {
      const b = boxOf(s.d), lit = s.tone !== 'shade';
      if (s.ink) { if (s.bulb) out.bulbs.push({ shape: i, phase: TWINKLE.indexOf(s.role) }); return; }
      if (s.role === 'glow' && lit && b.y < 60 && b.w >= 40 && b.h >= 36) out.panes.push({ shape: i, kind: kind || 'window', box: rb(b) });
      else if (s.role === 'glow' && !lit && b.y + b.h >= 178) out.daylight.push(i);
      else if ((s.role === 'screen' || s.role === 'glow') && lit) out.flicker.push(i);
      else if (s.role === 'lamp' && lit) out.lamp.push(i);
    });
    const pin = /^board/.test(room.id) ? pinSpot(room, boxOf) : null;
    if (pin) out.pin = { x: r1(pin.x), y: r1(pin.y), w: r1(pin.w), h: r1(pin.h), pin: pin.pin.map(r1) };
    return out;
  }

  /* the anchor box shrunk to the INK of the text in it, so a circle rings the
   * figure and not the empty end of its slot */
  function inkBox(b, text, size, align, adv) {
    const w = Math.min(b.w, String(text).length * size * (adv || 0.6)), h = Math.min(b.h, size * 1.05);
    const x = align === 'right' ? b.x + b.w - w : align === 'center' ? b.x + (b.w - w) / 2 : b.x;
    return { x, y: b.y + (b.h - h) / 2 - size * 0.05, w, h };
  }

  const API = { FPS, E, MOVES, TIMINGS, anchorFor, roomTargets, pinSpot, inkBox, theNumber, latest, tagPlace, countText, reveal, outset, stagger, penCircle, penDash, zoomBox, SCREEN_PULSE, LAMP_FLICKER, snow, RAIN, TWINKLE, TWINKLE_STEP, twinkleInk, pinDrop, slideX, tick };
  if (typeof module !== 'undefined' && module.exports) module.exports = API;
  g.MOTION = API;
})(typeof window !== 'undefined' ? window : globalThis);
