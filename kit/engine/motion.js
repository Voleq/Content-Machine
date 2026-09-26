/* Dennis v2 — motion.js (rebuild-35)
 *
 * THE MOTION CATALOGUE. Thirteen moves, published as DATA rather than baked
 * frames: each names what it applies to, its length in frames at 12 fps, its
 * easing and whether it plays once or loops, and exports the pure function a
 * renderer calls per frame. The plates stay stills; a renderer plays a move
 * OVER a plate's published slots, so no plate is re-drawn per frame and a move
 * can never disagree with the plate it animates.
 *
 * Rules every move keeps (DESIGN.md §5, audit rule 2): no partial opacity, so
 * nothing fades; things draw on, grow, slide, or appear on a frame. The ink is
 * always the slot's published ink or the room's own material.
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
    const k = E.inOut(t), p = pad || 60, ar = canvas[0] / canvas[1];
    let w = box.w + p * 2, h = w / ar; if (h < box.h + p * 2) { h = box.h + p * 2; w = h * ar; }
    const tx = box.x + box.w / 2 - w / 2, ty = box.y + box.h / 2 - h / 2;
    return [tx * k, ty * k, canvas[0] + (w - canvas[0]) * k, canvas[1] + (h - canvas[1]) * k];
  }
  /* loops. flicker: which frames the screen and lamp drop to their shade tone */
  const SCREEN_PULSE = [0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0];
  const LAMP_FLICKER = [0, 0, 0, 0, 0, 0, 0, 1, 0, 1, 0, 0];
  /* snow: flakes falling in a window box, seeded, looping over 12 frames */
  function snow(box, frame, n) {
    const out = []; let s = 11; const r = () => ((s = (s * 9301 + 49297) % 233280) / 233280);
    for (let i = 0; i < (n || 26); i++) {
      const x0 = r(), y0 = r(), sz = 0.8 + r() * 1.4, sp = 0.6 + r() * 0.8;
      const y = (y0 + (frame / 12) * sp) % 1, x = (x0 + Math.sin((frame / 12) * Math.PI * 2 + i) * 0.02 + 1) % 1;
      out.push({ x: box.x + x * box.w, y: box.y + y * box.h, r: sz });
    }
    return out;
  }
  const RAIN = (box, frame) => snow(box, frame * 3, 40).map(f => ({ x: f.x, y: f.y, w: 0.6, h: 5 }));
  /* twinkle: each bulb's ink steps one along the cycle every 3 frames */
  const TWINKLE = ['attention', 'subject2', 'subject'];
  const twinkleInk = (i, frame) => TWINKLE[(i + Math.floor(frame / 3)) % 3];
  /* pin-drop: a card falls onto the wall and swings once to rest */
  function pinDrop(t) { const k = E.out(t); return { dy: -60 * (1 - k), rot: -4 + 10 * Math.sin(k * Math.PI * 2.2) * (1 - k) }; }
  /* slide-in: an overlay from off the left edge to its place, landing */
  const slideX = (w, t) => -(w + 40) * (1 - E.land(t));
  /* tick-over: the old number up and out, the new one up and in */
  const tick = (h, t) => { const k = E.inOut(t); return { oldY: -h * k, newY: h * (1 - k) }; };

  const MOVES = [
    { id: 'count-up', group: 'plate', frames: 7, playback: 'once', ease: 'out', appliesTo: 'any figure or callout slot whose text is one number', how: 'countText(text, t)' },
    { id: 'line-draw', group: 'plate', frames: 10, playback: 'once', ease: 'linear', appliesTo: 'plot-area with a linePath', how: 'clip the data layer to reveal(plotArea, t, "left-linear"); the accent point appears on the last frame' },
    { id: 'bars-grow', group: 'plate', frames: 8, playback: 'once', ease: 'out', appliesTo: 'point-column, bar-N and part-N slots', how: 'clip each column to reveal(box, t_i, "bottom"), t_i staggered by one frame, the attention column last' },
    { id: 'highlight', group: 'plate', frames: 6, playback: 'once', ease: 'out', appliesTo: 'a slot with underline, or the quote slots', how: 'the underline rect width = reveal(box, t, "left").w' },
    { id: 'pen-circle', group: 'plate', frames: 8, playback: 'once', ease: 'inOut', appliesTo: 'any one slot; the "this one" beat', how: 'penCircle(box) stroked in attention with penDash(len, t)' },
    { id: 'zoom-to-slot', group: 'plate', frames: 12, playback: 'once', ease: 'inOut', appliesTo: 'paper plates; the push in on a footnote', how: 'viewBox = zoomBox(canvas, slot, t)' },
    { id: 'screen-flicker', group: 'room', frames: 12, playback: 'loop', ease: null, appliesTo: 'every room angle with a screen, glow or lamp', how: 'screen and glow take their shade tone where SCREEN_PULSE[f]; lamp where LAMP_FLICKER[f]' },
    { id: 'window-snow', group: 'room', frames: 12, playback: 'loop', ease: null, appliesTo: 'angles with a window pane; December, with the Christmas set', how: 'snow(pane, f) as paper-role dots inside the pane, drawn behind the frame bars' },
    { id: 'window-rain', group: 'room', frames: 12, playback: 'loop', ease: null, appliesTo: 'angles with a window pane; a gloomy episode', how: 'RAIN(pane, f) as short glow-shade strokes inside the pane' },
    { id: 'lights-twinkle', group: 'room', frames: 12, playback: 'loop', ease: null, appliesTo: 'the -christmas room assets', how: 'bulb i takes twinkleInk(i, f)' },
    { id: 'card-pin', group: 'room', frames: 9, playback: 'once', ease: 'out', appliesTo: 'the board angles; a new card on the wall of calls', how: 'the card translated pinDrop(t).dy and rotated pinDrop(t).rot about its pin' },
    { id: 'slide-in', group: 'overlay', frames: 6, playback: 'once', ease: 'land', appliesTo: 'overlays/lower-third, overlays/source-tag', how: 'translateX(slideX(width, t)); out is the same move reversed' },
    { id: 'tick-over', group: 'overlay', frames: 6, playback: 'once', ease: 'inOut', appliesTo: 'structure/chapter-bumper num slot', how: 'old number at tick(h, t).oldY, new at .newY, both clipped to the slot' },
  ];

  /* ── ANCHORS (rebuild-38). Where a move lands is READ from the plate's own
   * published slots, never placed by eye, so the same move lands right on any
   * plate. anchorFor(manifest) returns a box per move, or null where a plate
   * has nothing for that move to act on (the renderer then skips it). */
  const textSlots = m => Object.keys(m.slots || {}).filter(k => { const s = m.slots[k]; return s && !s.container && !s.region && s.role !== 'band' && s.role !== 'marker'; });
  const box = s => s && { x: s.x, y: s.y, w: s.w, h: s.h };
  function theNumber(m) {
    const S = m.slots || {}, R = m.typeRoles || {};
    /* a callout: X with X-label and X-detail beside it */
    const call = Object.keys(S).find(k => S[k + '-label'] && S[k + '-detail']);
    if (call) return call;
    const named = ['num', 'delta', 'headline-figure', 'figure', 'value'].find(k => S[k]);
    if (named) return named;
    /* else the biggest single-line text slot */
    return textSlots(m).filter(k => !(S[k].maxLines > 1)).sort((a, b) => ((R[S[b].role] || {}).size || 0) - ((R[S[a].role] || {}).size || 0))[0] || null;
  }
  function anchorFor(m) {
    const S = m.slots || {}, cv = m.canvas || [1920, 1080];
    const num = theNumber(m);
    const plot = S['plot-area'] || Object.keys(S).map(k => S[k]).find(s => s.container) || null;
    const under = Object.keys(S).find(k => S[k].underline);
    const quote = under || ['quote', 'quote-1', 'marked'].find(k => S[k]) || textSlots(m).find(k => S[k].maxLines > 2) || null;
    return {
      'count-up': num ? { slot: num, box: box(S[num]) } : null,
      'pen-circle': num ? { slot: num, box: box(S[num]) } : null,
      'highlight': quote ? { slot: quote, box: box(S[quote]) } : null,
      'zoom-to-slot': quote ? { slot: quote, box: box(S[quote]) } : null,
      'line-draw': plot ? { slot: 'plot-area', box: box(plot) } : null,
      'bars-grow': plot ? { slot: 'plot-area', box: box(plot) } : null,
      'tick-over': S.num ? { slot: 'num', box: box(S.num) } : null,
      'slide-in': { slot: null, box: { x: 0, y: 0, w: cv[0], h: cv[1] } },
    };
  }
  /* rooms: the card lands on the wall it belongs to, over the cards already
   * there (the wall-of-calls-pinned beat), centred on their union. `boxOf`
   * is the caller's path-box function, so this file stays geometry-free. */
  function pinSpot(room, boxOf) {
    const cards = room.shapes.filter(s => s.role === 'paper' && s.tone !== 'shade' && !s.ink).map(s => boxOf(s.d));
    if (!cards.length) return null;
    const x0 = Math.min(...cards.map(b => b.x)), y0 = Math.min(...cards.map(b => b.y)), x1 = Math.max(...cards.map(b => b.x + b.w)), y1 = Math.max(...cards.map(b => b.y + b.h));
    const cw = Math.max(18, Math.min(34, (x1 - x0) * 0.22)), ch = cw * 0.7;
    return { x: (x0 + x1) / 2 - cw / 2, y: y0 + (y1 - y0) * 0.35, w: cw, h: ch, pin: [(x0 + x1) / 2, y0 + (y1 - y0) * 0.35] };
  }

  /* the anchor box shrunk to the INK of the text in it, so a circle rings the
   * figure and not the empty end of its slot */
  function inkBox(b, text, size, align, adv) {
    const w = Math.min(b.w, String(text).length * size * (adv || 0.6)), h = Math.min(b.h, size * 1.05);
    const x = align === 'right' ? b.x + b.w - w : align === 'center' ? b.x + (b.w - w) / 2 : b.x;
    return { x, y: b.y + (b.h - h) / 2 - size * 0.05, w, h };
  }

  const API = { FPS, E, MOVES, anchorFor, pinSpot, inkBox, theNumber, countText, reveal, penCircle, penDash, zoomBox, SCREEN_PULSE, LAMP_FLICKER, snow, RAIN, TWINKLE, twinkleInk, pinDrop, slideX, tick };
  if (typeof module !== 'undefined' && module.exports) module.exports = API;
  g.MOTION = API;
})(typeof window !== 'undefined' ? window : globalThis);
