/* Dennis · LONG-FORM 16:9 · extends the marker engine with the wide room,
   its standing furniture, the artefacts, the clutter states, the dive,
   the stinger and the light overlays.
   Load AFTER dennis-marker-ink.js — it adds to the same registry, so the
   same render()/svgFor()/manifest() serve both formats.
   Author 1920x1080, deliver 3840x2160. Slots are identical across registers. */
(function (global) {
  var W = 1920, H = 1080, API, P, C, A;
  /* the host may inject both engines at once, so this file cannot assume the
     marker engine has run yet — it waits for it, then registers. */
  function boot() {
    API = global.DennisInk;
    P = API.Ink.prototype; C = API.C; A = API.ASSETS;
    build();
    if (API.boilAll) API.boilAll();
    global.dispatchEvent(new Event('dennis-ink-long-ready'));
  }
  function build() {

  /* draw a whole plate inside another, with its slots mapped into the outer
     canvas — so the doorway shows THE SAME ROOM rather than a second drawing
     of it, and its clock face and screen are still declared where they land. */
  P._nest = function (dx, dy, k, clip, fn) {
    var base = this.slot, self = this, out;
    this.slot = function (n, x, y, w, h) { return base.call(self, n, dx + x * k, dy + y * k, w * k, h * k); };
    try { out = fn.call(this); } finally { this.slot = base; }
    var id = 'nest' + Math.round(dx) + '-' + Math.round(dy) + '-' + Math.round(k * 1000);
    var g = '<g transform="translate(' + dx.toFixed(2) + ',' + dy.toFixed(2) + ') scale(' + k.toFixed(4) + ')">' + out + '</g>';
    if (!clip) return g;
    return '<defs><clipPath id="' + id + '"><rect x="' + clip[0] + '" y="' + clip[1] + '" width="' + clip[2] + '" height="' + clip[3] + '"/></clipPath></defs>'
      + '<g clip-path="url(#' + id + ')">' + g + '</g>';
  };

  /* ── standing furniture · the same objects in every viewpoint ───────── */

  P.crumple = function (rand, x, y, k) {
    k = k || 1; var n = 9, p = [], i;
    for (i = 0; i < n; i++) { var a = Math.PI * 2 * i / n, rr = (24 + rand() * 15) * k; p.push([x + rr * Math.cos(a), y + rr * Math.sin(a) * 0.84]); }
    p.push([p[0][0], p[0][1]]);
    var s = this._stroke(p, rand, { w: 5, r: 2.6 });
    for (i = 0; i < 3; i++) s += this._stroke([[x + (rand() * 2 - 1) * 17 * k, y + (rand() * 2 - 1) * 15 * k], [x + (rand() * 2 - 1) * 19 * k, y + (rand() * 2 - 1) * 17 * k]], rand, { w: 3.4, r: 2, s: C.grey, op: 0.62 });
    return s;
  };

  P.shelfBinders = function (rand, x, y, w, h, n) {
    var s = this._stroke([[x, y + h], [x + w, y + h - 3]], rand, { w: 7, r: 2.6, ov: 12 });
    s += this._stroke([[x - 4, y + h + 15], [x + w + 4, y + h + 12]], rand, { w: 4, r: 2.4, s: C.grey, op: 0.55, ov: 8 });
    s += this._stroke([[x + 6, y + h], [x + 2, y + h + 44]], rand, { w: 5, r: 2.4, op: 0.8 });
    s += this._stroke([[x + w - 6, y + h], [x + w - 2, y + h + 44]], rand, { w: 5, r: 2.4, op: 0.8 });
    var cx = x + 10, i = 0, lean;
    while (cx < x + w - 34 && i < n) {
      var bw = 24 + rand() * 26, bh = h * (0.7 + rand() * 0.27);
      lean = (rand() * 2 - 1) * 11;
      s += this._stroke([[cx, y + h], [cx + lean, y + h - bh], [cx + bw + lean, y + h - bh], [cx + bw, y + h]], rand, { w: 5, r: 2.4 });
      s += this._stroke([[cx + lean * 0.7 + bw * 0.22, y + h - bh * 0.6], [cx + bw * 0.78, y + h - bh * 0.46]], rand, { w: 4, r: 2.2, s: C.grey, op: 0.72 });
      cx += bw + 3 + rand() * 7; i++;
    }
    /* the one that gave up: lying flat on top of the rest */
    s += this._stroke([[x + w * 0.38, y + h - h * 0.94], [x + w * 0.86, y + h - h * 0.99], [x + w * 0.87, y + h - h * 0.78], [x + w * 0.39, y + h - h * 0.73]], rand, { w: 5, r: 2.4, close: true });
    return s;
  };

  P.laptopIgnored = function (rand, x, y, k, ang) {
    k = k || 1;
    var s = this._stroke([[x, y], [x + 152 * k, y + 6 * k], [x + 180 * k, y - 92 * k], [x + 24 * k, y - 100 * k]], rand, { w: 6, r: 2.6, close: true });
    s += this._stroke([[x + 24 * k, y - 100 * k], [x + 180 * k, y - 92 * k], [x + 198 * k, y - 226 * k], [x + 36 * k, y - 234 * k]], rand, { w: 6, r: 2.6, close: true });
    s += this._stroke([[x + 52 * k, y - 118 * k], [x + 186 * k, y - 110 * k]], rand, { w: 4, r: 2.2, s: C.grey, op: 0.7 });
    s += this._stroke([[x + 44 * k, y - 122 * k], [x + 52 * k, y - 210 * k]], rand, { w: 3.6, r: 2.4, s: C.grey, op: 0.5 });
    return this._rot(ang || 0, x + 90 * k, y - 60 * k, s);
  };

  P.cableRun = function (rand, x1, y1, x2, y2, sag, n) {
    n = n || 2; var s = '', i;
    for (i = 0; i < n; i++) {
      var o = i * 10, mx = (x1 + x2) / 2 + (rand() * 2 - 1) * 46, my = Math.max(y1, y2) * 0.5 + y1 * 0.5 + sag + (rand() * 2 - 1) * 20;
      s += this._stroke([[x1 + o, y1], [mx, my], [x2 + o * 0.4, y2]], rand, { w: 4.5, r: 2.8, s: C.grey, op: 0.78 });
    }
    return s;
  };

  P.wasteBasket = function (rand, x, y, k) {
    k = k || 1; var tw = 76 * k, bw = 56 * k, h = 108 * k, i;
    var s = this._stroke([[x - tw, y - h], [x - bw, y], [x + bw, y], [x + tw, y - h]], rand, { w: 7, r: 2.8 });
    s += this._stroke(this._ell(x, y - h, tw, tw * 0.26, 0, Math.PI * 2), rand, { w: 6, r: 2.6, close: true });
    for (i = 0; i < 5; i++) s += this._stroke([[x - tw * 0.66 + i * tw * 0.33, y - h + 14], [x - tw * 0.56 + i * tw * 0.33, y - 16]], rand, { w: 3.4, r: 3, s: C.grey, op: 0.46 });
    s += this.crumple(rand, x - 22 * k, y - h - 26 * k, 0.86 * k) + this.crumple(rand, x + 30 * k, y - h - 12 * k, 0.7 * k);
    s += this.crumple(rand, x + tw + 32 * k, y - 14 * k, 0.76 * k);
    s += this.shade(rand, x + tw, y - 4, 62 * k);
    return s;
  };

  P.dyingPlant = function (rand, x, y, k) {
    k = k || 1; var pw = 44 * k, ph = 54 * k, self = this;
    var s = this._stroke([[x - pw, y - ph], [x - pw * 0.72, y], [x + pw * 0.72, y], [x + pw, y - ph]], rand, { w: 7, r: 2.8 });
    s += this._stroke([[x - pw, y - ph], [x + pw, y - ph - 2]], rand, { w: 6, r: 2.6, ov: 6 });
    s += this._stroke([[x + 2 * k, y - ph], [x - 8 * k, y - ph - 70 * k]], rand, { w: 5, r: 2.6 });
    [[-1, 0.9], [1, 1.1], [-0.55, 1.25]].forEach(function (d) {
      var bx = x - 8 * k, by = y - ph - 62 * k * d[1],
        leaf = [[bx, by], [bx + d[0] * 46 * k, by - 10 * k], [bx + d[0] * 74 * k, by + 34 * k], [bx + d[0] * 62 * k, by + 62 * k]];
      s += self._wash(leaf, rand, C.world.plant, 0.5);
      s += self._stroke(leaf, rand, { w: 5, r: 2.8, s: C.world.plant });
    });
    /* the leaf that fell */
    s += this._stroke([[x + pw + 22 * k, y - 4 * k], [x + pw + 62 * k, y - 12 * k], [x + pw + 54 * k, y + 6 * k]], rand, { w: 4.5, r: 2.6, s: C.world.plant });
    s += this.shade(rand, x + pw, y - 6, 58 * k);
    return s;
  };

  P.wallClock = function (rand, cx, cy, r, slotName) {
    var s = this._stroke(this._ell(cx, cy, r, r, 0, Math.PI * 2), rand, { w: 8, r: 3, close: true });
    s += this._stroke(this._ell(cx, cy, r * 0.87, r * 0.87, 0, Math.PI * 2), rand, { w: 4, r: 2.4, s: C.grey, op: 0.66, close: true });
    var i; for (i = 0; i < 12; i++) {
      var a = Math.PI * 2 * i / 12, r0 = r * 0.76, r1 = r * (i % 3 === 0 ? 0.6 : 0.68);
      s += this._stroke([[cx + r0 * Math.cos(a), cy + r0 * Math.sin(a)], [cx + r1 * Math.cos(a), cy + r1 * Math.sin(a)]], rand, { w: i % 3 === 0 ? 5.4 : 3.4, r: 1.5 });
    }
    s += this._stroke(this._ell(cx, cy, 5, 5, 0, Math.PI * 2), rand, { w: 4, r: 1.3, close: true });
    s += this.shade(rand, cx + r * 0.78, cy + r * 0.72, 42);
    if (slotName) s += this.slot(slotName, cx - r * 0.56, cy - r * 0.56, r * 1.12, r * 1.12);
    return s;
  };

  P.framedShot = function (rand, x, y, w, h, slotName) {
    var s = this._box(rand, x, y, w, h, { w: 9 });
    s += this._box(rand, x + 15, y + 15, w - 30, h - 30, { w: 4, r: 2.4, ov: 6, s: C.grey });
    s += this.shade(rand, x + w + 3, y + h * 0.86, 50);
    if (slotName) s += this.slot(slotName, x + 24, y + 24, w - 48, h - 48);
    return s;
  };

  P.wallCalendar = function (rand, x, y, w, h, slotName) {
    var s = this._box(rand, x, y, w, h, { w: 8 });
    s += this._stroke([[x + 10, y + h * 0.23], [x + w - 10, y + h * 0.23 - 4]], rand, { w: 6, r: 2.6, ov: 8 });
    s += this._stroke([[x + w * 0.5, y], [x + w * 0.5 - 2, y - 20]], rand, { w: 5, r: 2.4, s: C.grey });
    s += this.pin(rand, x + w * 0.5 - 2, y - 26, 1);
    s += this.shade(rand, x + w + 3, y + h * 0.9, 46);
    if (slotName) s += this.slot(slotName, x + 16, y + h * 0.3, w - 32, h * 0.6);
    return s;
  };

  P.postIt = function (rand, x, y, k, ang, struck) {
    k = k || 1; var w = 76 * k;
    var s = this._wash([[x, y], [x + w, y - 3], [x + w + 2, y + w - 4], [x - 2, y + w]], rand, C.world.postIt, 0.62);
    s += this._stroke([[x, y], [x + w, y - 3], [x + w + 2, y + w - 4], [x - 2, y + w]], rand, { w: 5, r: 2.4, close: true });
    s += this._stroke([[x + 10, y + w * 0.34], [x + w - 13, y + w * 0.3]], rand, { w: 5, r: 2.6, s: C.grey, op: 0.82 });
    s += this._stroke([[x + 10, y + w * 0.6], [x + w * 0.6, y + w * 0.58]], rand, { w: 4, r: 2.4, s: C.grey, op: 0.58 });
    if (struck) s += this._stroke([[x + 3, y + w * 0.74], [x + w - 3, y + w * 0.18]], rand, { w: 6, r: 2.4, s: C.red });
    s += this.shade(rand, x + w + 2, y + w * 0.88, 24 * k);
    return this._rot(ang || 0, x + w / 2, y + w / 2, s);
  };

  P.canEmpty = function (rand, x, y, k, crushed) {
    k = k || 1; var w = 27 * k, h = 82 * k;
    var s;
    if (crushed) {
      s = this._wash([[x - w, y - h * 0.62], [x - w * 0.44, y - h * 0.4], [x - w * 0.9, y], [x + w * 0.86, y], [x + w * 0.4, y - h * 0.36], [x + w * 0.92, y - h * 0.6]], rand, C.world.can, 0.4);
      s += this._stroke([[x - w, y - h * 0.62], [x - w * 0.44, y - h * 0.4], [x - w * 0.9, y], [x + w * 0.86, y], [x + w * 0.4, y - h * 0.36], [x + w * 0.92, y - h * 0.6]], rand, { w: 6, r: 2.6, close: true });
      s += this._stroke(this._ell(x, y - h * 0.62, w * 0.9, w * 0.3, 0, Math.PI * 2), rand, { w: 5, r: 2.4, close: true });
    } else {
      s = this._wash([[x - w, y - h], [x - w * 0.92, y], [x + w * 0.92, y], [x + w, y - h]], rand, C.world.can, 0.42);
      s += this._stroke([[x - w, y - h], [x - w * 0.92, y], [x + w * 0.92, y], [x + w, y - h]], rand, { w: 6, r: 2.6 });
      s += this._stroke(this._ell(x, y - h, w, w * 0.3, 0, Math.PI * 2), rand, { w: 5.4, r: 2.4, close: true });
      s += this._stroke([[x - w * 0.3, y - h - 2], [x + w * 0.34, y - h - 5]], rand, { w: 4, r: 2, s: C.grey });
      s += this._stroke([[x - w * 0.78, y - h * 0.6], [x + w * 0.8, y - h * 0.64]], rand, { w: 4, r: 2.4, s: C.grey, op: 0.6 });
    }
    s += this.shade(rand, x + w, y - 2, 34 * k);
    return s;
  };

  P.noodlePot = function (rand, x, y, k) {
    k = k || 1; var tw = 50 * k, bw = 36 * k, h = 62 * k;
    var s = this._wash([[x - tw, y - h], [x - bw, y], [x + bw, y], [x + tw, y - h]], rand, C.world.curtain, 0.5);
    s += this._stroke([[x - tw, y - h], [x - bw, y], [x + bw, y], [x + tw, y - h]], rand, { w: 6, r: 2.6 });
    s += this._stroke(this._ell(x, y - h, tw, tw * 0.27, 0, Math.PI * 2), rand, { w: 6, r: 2.6, close: true });
    s += this._stroke([[x - tw * 0.82, y - h - 4], [x - tw * 0.3, y - h - 42 * k], [x + tw * 0.56, y - h - 30 * k]], rand, { w: 5, r: 2.6 });
    s += this._stroke([[x - tw * 0.68, y - h * 0.48], [x + tw * 0.68, y - h * 0.52]], rand, { w: 4, r: 2.4, s: C.grey, op: 0.68 });
    s += this.shade(rand, x + tw * 0.9, y - 2, 42 * k);
    return s;
  };

  P.phoneDown = function (rand, x, y, k, ang) {
    k = k || 1; var w = 128 * k, h = 66 * k;
    var s = this._stroke([[x, y], [x + w, y - 4], [x + w + 3, y + h], [x - 3, y + h + 4]], rand, { w: 6, r: 2.4, close: true });
    s += this._stroke(this._ell(x + w * 0.2, y + h * 0.36, 12 * k, 12 * k, 0, Math.PI * 2), rand, { w: 4.5, r: 2, close: true });
    s += this.shade(rand, x + w + 4, y + h * 0.88, 32 * k);
    return this._rot(ang || 0, x + w / 2, y + h / 2, s);
  };

  /* half-drawn blackout curtain: rail across the whole window, cloth over part */
  P.curtainHalf = function (rand, x, y, w, h, side) {
    var cw = w * 0.46, cx = side > 0 ? x + w - cw : x, i, n = 5;
    var s = this._wash([[cx, y - 8], [cx + cw, y - 12], [cx + cw + 6, y + h - 8], [cx - 4, y + h]], rand, C.world.curtain, 0.66);
    s += this._stroke([[x - 10, y - 16], [x + w + 12, y - 20]], rand, { w: 6, r: 2.4, ov: 10 });
    s += this._stroke([[cx, y - 8], [cx + cw, y - 12]], rand, { w: 7, r: 2.6, ov: 6 });
    for (i = 0; i <= n; i++) {
      var fx = cx + cw * i / n;
      s += this._stroke([[fx, y - 6], [fx + (i % 2 ? 11 : -9), y + h * 0.52], [fx + (i % 2 ? -5 : 9), y + h]], rand, { w: 5, r: 2.6 });
    }
    s += this._stroke([[cx - 4, y + h], [cx + cw + 4, y + h - 10]], rand, { w: 5, r: 3, ov: 6 });
    return s;
  };

  P.windowWide = function (rand, x, y, w, h, side, rayLen) {
    var s = this._box(rand, x, y, w, h, { w: 7 });
    s += this._stroke([[x, y + h * 0.48], [x + w, y + h * 0.44]], rand, { w: 5, r: 2.4 });
    s += this._stroke([[x + w * 0.54, y], [x + w * 0.54, y + h]], rand, { w: 5, r: 2.4 });
    s += this.curtainHalf(rand, x, y, w, h, side == null ? 1 : side);
    return s + this.lightRays(rand, x + w + 18, y + h * 0.6, 3, rayLen || 250, 74);
  };

  /* ── clutter · tidy / lived-in / 3am, strictly additive, never on a slot ── */
  P.clutter = function (rand, state, spots) {
    var n = state === 'tidy' ? 0 : state === '3am' ? spots.length : Math.min(3, spots.length), s = '', i;
    for (i = 0; i < n; i++) {
      var p = spots[i], kind = p[2], k = p[3] || 1;
      s += kind === 'can' ? this.canEmpty(rand, p[0], p[1], k, i > 3)
        : kind === 'cup' ? this.mugFront(rand, p[0], p[1], k)
        : kind === 'pot' ? this.noodlePot(rand, p[0], p[1], k)
        : this.crumple(rand, p[0], p[1], k);
    }
    return s;
  };

  /* ── A · the five viewpoints, 1920×1080 ─────────────────────────────── */

  P.roomWide16 = function (rand, state) {
    /* the desk sits low so a seated figure gets real height in a wide frame:
       the figure slot is 540×530 — 28% of frame width — and every tall object on
       the desk stays outside its x-range so nothing is drawn where he will be. */
    var FY = 712, DY = 780, s = '';
    s += this.wallFloor(rand, FY, W);
    s += this.floorPlane(rand, FY, { w: W, x0: -30, x1: W + 30 });
    s += this.windowWide(rand, -70, 118, 336, 306, 1, 250);
    s += this.wallClock(rand, 434, 190, 76, 'clock-face');
    s += this.framedShot(rand, 528, 78, 286, 172, 'framed-screenshot');
    s += this.postIt(rand, 928, 92, 1, -6, false) + this.postIt(rand, 1040, 110, 0.9, 6, true) + this.postIt(rand, 982, 180, 0.84, -12, false);
    s += this.shelfBinders(rand, 1290, 148, 306, 112, 8);
    s += this.shelfBinders(rand, 1290, 330, 306, 112, 7);
    s += this.wallCalendar(rand, 1662, 118, 218, 300, 'calendar-face');
    s += this.deskSlab(rand, 252, DY, 1300, 60, 372, 1428, 236);
    s += this._stroke([[262, DY + 62], [1544, DY + 58]], rand, { w: 4, r: 2.6, s: C.grey, op: 0.44, ov: 8 });
    s += this.lamp(rand, 316, DY - 2, state === '3am');
    s += this.monitorFront(rand, 428, DY - 240, 330, 238, 'screen');
    s += this.cableRun(rand, 560, DY + 6, 520, 1032, 130, 2);
    s += this.cableRun(rand, 1300, DY + 8, 1364, 1030, 110, 1);
    s += this.phoneDown(rand, 852, DY + 4, 0.74, -7);
    s += this.mugFront(rand, 1218, DY - 12, 0.84);
    s += this.laptopIgnored(rand, 1300, DY, 0.72, -9);
    s += this.paperStack(rand, 1452, DY, 100, 4);
    s += this.wasteBasket(rand, 196, 1024, 1.05);
    s += this.dyingPlant(rand, 1782, 1012, 1.15);
    s += this.shade(rand, 766, DY + 44, 72) + this.shade(rand, 1266, DY + 46, 54);
    s += this.clutter(rand, state, [[648, DY - 4, 'can', 0.84], [1186, DY - 2, 'cup', 0.44], [326, 1030, 'crumple', 0.78],
      [582, DY - 4, 'can', 0.78], [1520, DY, 'pot', 0.7], [452, 1042, 'crumple', 0.68], [1560, DY - 4, 'can', 0.7]]);
    s += this.slot('figure', 700, 250, 540, 530);
    return s;
  };

  P.roomSide16 = function (rand, state) {
    var FY = 806, s = '';
    s += this.wallFloor(rand, FY, W);
    s += this.floorPlane(rand, FY, { w: W, x0: 560, x1: W + 30 });
    s += this.windowWide(rand, -60, 108, 320, 300, 1, 230);
    s += this.wallClock(rand, 402, 208, 70, 'clock-face');
    s += this.framedShot(rand, 552, 104, 268, 182, 'framed-screenshot');
    s += this.shelfBinders(rand, 902, 122, 268, 112, 7);
    s += this.wallCalendar(rand, 1252, 128, 214, 262, 'calendar-face');
    s += this.postIt(rand, 1554, 168, 0.86, 7, true) + this.postIt(rand, 1642, 232, 0.8, -9, false);
    s += this.deskSlab(rand, 780, 716, 1140, 60, 900, 1740, 300);
    s += this.monitorSide(rand, 1662, 428, 296);
    s += this.lamp(rand, 826, 712, state === '3am');
    s += this.paperStack(rand, 1150, 716, 196, 4);
    s += this.mugFront(rand, 1424, 704, 0.84);
    s += this.phoneDown(rand, 1268, 706, 0.74, 6);
    s += this.cableRun(rand, 1700, 776, 1780, 1080, 120, 2);
    /* the chair, side-on and clear of the desk */
    s += this._stroke([[430, 796], [742, 790]], rand, { w: 9, r: 3, ov: 14 });
    s += this._stroke([[434, 812], [740, 806]], rand, { w: 5, r: 2.4, ov: 8 });
    s += this._stroke([[712, 806], [726, 1080]], rand, { w: 8, r: 3 }) + this._stroke([[458, 808], [442, 1080]], rand, { w: 8, r: 3 });
    s += this._stroke([[440, 794], [408, 470]], rand, { w: 9, r: 3 });
    s += this._stroke([[408, 470], [352, 476], [378, 792], [440, 794]], rand, { w: 7, r: 3 });
    s += this._stroke([[358, 462], [416, 466]], rand, { w: 9, r: 2.4, ov: 6 });
    s += this._stroke([[368, 560], [420, 566]], rand, { w: 5, r: 2.2, s: C.grey, op: 0.7, ov: 4 });
    s += this.wasteBasket(rand, 300, 960, 0.94);
    s += this.dyingPlant(rand, 1866, 928, 1);
    s += this.shade(rand, 1352, 760, 78) + this.shade(rand, 1706, 782, 58);
    s += this.clutter(rand, state, [[1000, 712, 'can', 0.82], [1512, 708, 'cup', 0.44], [420, 968, 'crumple', 0.74],
      [1074, 710, 'can', 0.78], [1348, 714, 'pot', 0.7], [560, 976, 'crumple', 0.66], [960, 708, 'can', 0.7]]);
    s += this.slot('figure-seated', 340, 330, 400, 470);
    return s;
  };

  P.roomOver16 = function (rand, state) {
    var s = '';
    s += this.wallFloor(rand, 866, W);
    s += this.lightRays(rand, -30, 60, 3, 250, 78);
    s += this.wallClock(rand, 148, 176, 66, 'clock-face');
    s += this.shelfBinders(rand, 1640, 112, 258, 106, 7);
    s += this.postIt(rand, 1568, 268, 0.8, -8, true);
    s += this.monitorFront(rand, 470, 150, 986, 546, 'screen');
    s += this._stroke([[0, 880], [W, 868]], rand, { w: 8, r: 3, ov: 22 });
    s += this.shade(rand, 1468, 830, 86);
    s += this.mugFront(rand, 300, 856, 0.8);
    s += this.paperStack(rand, 1548, 872, 132, 3);
    s += this.phoneDown(rand, 340, 872, 0.74, -6);
    s += this.clutter(rand, state, [[214, 858, 'can', 0.8], [1740, 866, 'cup', 0.44], [128, 872, 'crumple', 0.66],
      [1660, 862, 'can', 0.76], [1500, 866, 'pot', 0.68], [60, 862, 'can', 0.66], [1806, 858, 'can', 0.62]]);
    /* back of head, neck, one shoulder, low in frame */
    s += this._stroke([[602, 1080], [672, 1008], [790, 968], [896, 960]], rand, { w: 9, r: 4 });
    s += this._stroke([[1032, 962], [1148, 986], [1250, 1034], [1300, 1080]], rand, { w: 9, r: 4 });
    s += this._stroke(this._ell(962, 790, 150, 158, -0.18, Math.PI * 2 + 0.42), rand, { w: 9, r: 4.4 });
    s += this._stroke([[906, 928], [910, 962]], rand, { w: 7, r: 3 }) + this._stroke([[1012, 926], [1008, 960]], rand, { w: 7, r: 3 });
    s += this._stroke([[956, 640], [928, 596], [978, 614], [962, 646]], rand, { w: 7, r: 3.4 });
    return s;
  };

  P.deskTop16 = function (rand, state) {
    var s = '';
    s += this._stroke([[0, 86], [W, 78]], rand, { w: 8, r: 3.4, ov: 24 });
    s += this._stroke([[0, 140], [W, 132]], rand, { w: 4, r: 3, s: C.grey, op: 0.5, ov: 16 });
    s += this.lightRays(rand, -40, 300, 3, 150, 66);
    s += this._stroke([[0, 1032], [W, 1024]], rand, { w: 9, r: 3.4, ov: 24 });
    s += this.mugTop(rand, 214, 268, 96);
    s += this.penTop(rand, 154, 942, 244, -0.2);
    s += this.paperStackTop(rand, 1470, 176, 300, 226);
    s += this.keebCorner(rand, 1408, 782, 424, 220);
    s += this.phoneDown(rand, 214, 466, 0.9, -12);
    s += this.shade(rand, 322, 350, 92) + this.shade(rand, 1782, 420, 82) + this.shade(rand, 300, 990, 68);
    s += this.clutter(rand, state, [[430, 300, 'can', 0.94], [1330, 268, 'cup', 0.52], [1290, 980, 'crumple', 0.8],
      [376, 214, 'can', 0.86], [1230, 372, 'pot', 0.8], [246, 700, 'crumple', 0.7], [1348, 154, 'can', 0.8]]);
    s += this.slot('desk-surface', 560, 190, 800, 760);
    return s;
  };

  P.atSheet16 = function (rand, state) {
    var s = '';
    s += this.wallFloor(rand, 172, W);
    s += this.lightRays(rand, -40, 208, 3, 130, 62);
    var sheet = this._box(rand, 700, 96, 1000, 940, { w: 9 })
      + this._stroke([[736, 244], [1666, 236]], rand, { w: 6, r: 3, ov: 14 });
    s += this._rot(-1.4, 1200, 560, sheet);
    s += this._stroke(this._ell(738, 128, 15, 15, 0, Math.PI * 2), rand, { w: 6, r: 2, close: true });
    s += this._stroke(this._ell(1660, 118, 15, 15, 0, Math.PI * 2), rand, { w: 6, r: 2, close: true });
    s += this.slot('sheet', 740, 268, 916, 736);
    s += this.penTop(rand, 486, 980, 210, -0.5);
    s += this.clutter(rand, state, [[300, 1010, 'can', 0.9], [560, 1030, 'cup', 0.5], [176, 1046, 'crumple', 0.74],
      [232, 1006, 'can', 0.82], [420, 1040, 'pot', 0.76], [640, 1058, 'crumple', 0.66], [128, 998, 'can', 0.7]]);
    s += this.shade(rand, 1706, 1030, 92);
    s += this.slot('figure', 120, 250, 500, 700);
    return s;
  };

  /* ── B · surfaces ───────────────────────────────────────────────────── */

  /* the nine pin slots — one table, shared by all three evidence-wall states */
  var PINS = [
    [206, 150, 300, 380], [548, 128, 400, 268], [990, 156, 268, 356], [1300, 138, 380, 250],
    [214, 578, 384, 252], [640, 442, 292, 372], [974, 552, 366, 246], [1382, 430, 300, 384],
    [700, 856, 380, 190]
  ];
  P.evidenceWall = function (rand, level) {
    var s = this._box(rand, 90, 74, 1740, 1000, { w: 10 }), i, self = this, rr = rand;
    s += this._box(rand, 116, 100, 1688, 948, { w: 5, r: 2.6, ov: 8, s: C.grey });
    /* cork tooth — sparse dots, denser toward the edges */
    for (i = 0; i < 90; i++) s += this.blot(rand, 130 + rand() * 1660, 116 + rand() * 916, 1.3 + rand() * 1.6);
    var n = level === 'empty' ? 9 : level === 'half' ? 4 : 9;
    /* HALF fills four pins spread across the board, not the top row — the wall
       has to look like it is filling up, not like it is being loaded in order */
    var HALF = [0, 2, 4, 7];
    PINS.forEach(function (p, idx) {
      var cx = p[0] + p[2] / 2, top = p[1];
      if (level === 'empty') { s += self.pin(rr, cx, top - 16, 1.05); return; }
      var shown = level === 'half' ? HALF.indexOf(idx) >= 0 : true;
      if (!shown) { s += self.pin(rr, cx, top - 16, 1.05); return; }
      var ang = (rr() * 2 - 1) * (level === 'full' ? 3.4 : 1.8);
      var card = self._box(rr, p[0], top, p[2], p[3], { w: 6 })
        + self.foldCorner(rr, p[0] + p[2], top + p[3], 0.5, 1);
      if (level === 'full') card += self.shade(rr, p[0] + p[2] + 4, top + p[3] * 0.9, 44);
      s += self._rot(ang, cx, top + p[3] / 2, card);
      s += self.pin(rr, cx, top + 8, 1.15);
    });
    if (level !== 'empty') {
      /* string: a few runs on half, a web on full */
      var runs = level === 'half' ? [[0, 2], [2, 4]] : [[0, 1], [1, 3], [3, 7], [4, 5], [5, 6], [6, 8], [2, 5], [0, 4]];
      runs.forEach(function (r) {
        var a = PINS[r[0]], b = PINS[r[1]];
        s += self._stroke([[a[0] + a[2] / 2, a[1] + 8], [(a[0] + b[0]) / 2 + a[2] / 2, (a[1] + b[1]) / 2 + 40], [b[0] + b[2] / 2, b[1] + 8]], rr, { w: 4, r: 3, s: C.red, op: 0.72 });
      });
    }
    PINS.forEach(function (p, i) { s += self.slot('pin-' + (i + 1), p[0], p[1], p[2], p[3]); });
    return s;
  };

  P.doorway16 = function (rand) {
    /* the establishing shot: we are outside the door looking in. The interior
       is the wide room, scaled down and clipped to the opening, so the viewer
       learns the geography of the space they will spend half an hour in. */
    var OX = 336, OY = 108, OW = 1248, OH = 900, k = 0.78,
      dx = OX + (OW - W * k) / 2, dy = OY + (OH - H * k) / 2 + 40, s = '';
    s += this._nest(dx, dy, k, [OX, OY, OW, OH], function () { return this.roomWide16(rand, 'lived-in'); });
    /* the jamb, heavy, in front of everything */
    s += this._stroke([[OX, OY], [OX, 1080]], rand, { w: 26, r: 3.4 });
    s += this._stroke([[OX + OW, OY], [OX + OW, 1080]], rand, { w: 26, r: 3.4 });
    s += this._stroke([[OX - 14, OY], [OX + OW + 14, OY - 6]], rand, { w: 26, r: 3.4, ov: 6 });
    s += this._stroke([[OX - 46, 0], [OX - 46, 1080]], rand, { w: 8, r: 2.6, s: C.grey, op: 0.7 });
    s += this._stroke([[OX + OW + 46, 0], [OX + OW + 46, 1080]], rand, { w: 8, r: 2.6, s: C.grey, op: 0.7 });
    s += this._stroke([[OX - 52, OY - 52], [OX + OW + 52, OY - 58]], rand, { w: 8, r: 2.6, s: C.grey, op: 0.7, ov: 8 });
    /* the light spilling out of the opening onto the near floor */
    s += this._stroke([[OX + 20, 1010], [OX + OW - 20, 1006]], rand, { w: 9, r: 3, ov: 10 });
    s += this.shade(rand, OX + OW + 20, 1024, 130) + this.shade(rand, OX - 30, 1028, 120, 2.7);
    return s;
  };

  P.doorway16Old = function (rand) {
    /* the room from outside the door: jamb in the near dark, the desk far off */
    var s = '';
    s += this._stroke([[318, -20], [330, 1100]], rand, { w: 12, r: 3.4 });
    s += this._stroke([[1596, -20], [1584, 1100]], rand, { w: 12, r: 3.4 });
    s += this._stroke([[326, 96], [1590, 88]], rand, { w: 12, r: 3.4, ov: 8 });
    s += this._stroke([[286, -20], [298, 1100]], rand, { w: 6, r: 2.6, s: C.grey, op: 0.7 });
    s += this._stroke([[1628, -20], [1616, 1100]], rand, { w: 6, r: 2.6, s: C.grey, op: 0.7 });
    s += this._stroke([[294, 62], [1622, 54]], rand, { w: 6, r: 2.6, s: C.grey, op: 0.7, ov: 8 });
    /* threshold and the light spilling out of it */
    s += this._stroke([[330, 1012], [1584, 1006]], rand, { w: 8, r: 3, ov: 10 });
    s += this.shade(rand, 1600, 1020, 120) + this.shade(rand, 250, 1024, 110, 2.7);
    /* inside: back wall, floor, window at the far left, the desk across the room */
    s += this.wallFloor(rand, 712, W);
    s += this._stroke([[404, 712], [352, 1006]], rand, { w: 4, r: 2.6, s: C.grey, op: 0.4 });
    s += this._stroke([[1520, 708], [1566, 1004]], rand, { w: 4, r: 2.6, s: C.grey, op: 0.4 });
    s += this.windowWide(rand, 372, 236, 214, 208, 1, 130);
    s += this.wallClock(rand, 700, 292, 44, 'clock-face');
    s += this.framedShot(rand, 800, 250, 148, 100, 'framed-screenshot');
    s += this.shelfBinders(rand, 1032, 254, 178, 72, 6);
    s += this.wallCalendar(rand, 1300, 258, 122, 146, 'calendar-face');
    s += this.deskSlab(rand, 640, 640, 780, 36, 720, 1320, 178);
    s += this.monitorFront(rand, 738, 512, 190, 128, 'screen');
    s += this.lamp(rand, 668, 638, true);
    s += this.laptopIgnored(rand, 1234, 640, 0.4, -7);
    s += this.mugFront(rand, 1152, 632, 0.44);
    s += this.paperStack(rand, 1330, 640, 64, 3);
    s += this.wasteBasket(rand, 596, 748, 0.56);
    s += this.dyingPlant(rand, 1486, 736, 0.6);
    s += this.cableRun(rand, 812, 678, 790, 818, 70, 2);
    s += this.canEmpty(rand, 1078, 636, 0.44, false);
    s += this.crumple(rand, 636, 762, 0.44);
    s += this.slot('figure', 940, 424, 220, 220);
    return s;
  };

  P.whiteboard16 = function (rand) {
    var s = this._box(rand, 120, 96, 1680, 800, { w: 10 });
    s += this._box(rand, 150, 126, 1620, 740, { w: 4, r: 2.4, ov: 8, s: C.grey });
    /* tray, one marker, a stray cloth */
    s += this._stroke([[188, 918], [1732, 912]], rand, { w: 8, r: 3, ov: 12 });
    s += this._stroke([[196, 940], [1724, 934]], rand, { w: 5, r: 2.6, s: C.grey, op: 0.7, ov: 8 });
    s += this._stroke([[420, 906], [560, 902]], rand, { w: 12, r: 2.4 });
    s += this._stroke([[1180, 900], [1250, 886], [1310, 902], [1256, 924], [1186, 918]], rand, { w: 6, r: 3.4, close: true });
    s += this.shade(rand, 1806, 890, 96);
    s += this.wallFloor(rand, 1004, W);
    s += this.slot('board', 168, 146, 1584, 700);
    return s;
  };

  P.pastCalls16 = function (rand) {
    /* the channel's own record: five cards hanging in a column, some struck */
    var s = '', i, self = this, x = 1246, y = 78, cw = 436, ch = 150, gap = 26;
    s += this._stroke([[1150, 30], [1150, 1046]], rand, { w: 5, r: 3, s: C.grey, op: 0.5 });
    for (i = 0; i < 5; i++) {
      var cy = y + i * (ch + gap), ang = (i % 2 ? 1 : -1) * (1 + i * 0.5);
      var card = this._box(rand, x, cy, cw, ch, { w: 6 });
      if (i > 2) card += this._stroke([[x + 20, cy + ch - 22], [x + cw - 24, cy + ch - 26]], rand, { w: 4, r: 2.6, s: C.grey, op: 0.6 });
      s += this._rot(ang, x + cw / 2, cy + ch / 2, card);
      s += this.pin(rand, x + cw / 2, cy + 10, 1.1);
      s += this._stroke([[1152, cy + 22], [x + cw / 2, cy + 6]], rand, { w: 4, r: 3, s: C.grey, op: 0.55 });
      if (i === 1 || i === 4) s += this._stroke([[x + 8, cy + ch * 0.66], [x + cw - 8, cy + ch * 0.34]], rand, { w: 8, r: 3, s: C.red, op: 0.86 });
      s += this.slot('card-' + (i + 1), x + 24, cy + 20, cw - 48, ch - 40);
    }
    s += this.wallFloor(rand, 1006, W);
    s += this.shelfBinders(rand, 160, 120, 268, 108, 7);
    s += this.slot('figure', 480, 300, 500, 700);
    return s;
  };

  P.projection16 = function (rand) {
    /* footage large behind him, him small and silhouetted. Slight keystone. */
    var s = this.wallFloor(rand, 1004, W);
    /* the projected rectangle: 1680×804 of a 1920×1080 frame — 65% — with a slight keystone */
    var q = [[110, 44], [1812, 78], [1788, 882], [134, 848]];
    s += this._stroke(q.concat([q[0]]), rand, { w: 10, r: 3.4 });
    s += this._stroke([[140, 74], [1782, 108], [1758, 852], [164, 818], [140, 74]], rand, { w: 4, r: 2.6, s: C.grey, op: 0.66 });
    s += this.lightRays(rand, 20, 920, 2, 130, 54);
    s += this.slot('projection', 158, 92, 1606, 742);
    /* him small and silhouetted at the foot of the wall, below the projection */
    s += this.slot('figure', 720, 890, 260, 190);
    return s;
  };

  P.floorSpread16 = function (rand) {
    /* looking down at documents across the floor, him crouching at frame edge */
    var s = '', i, self = this;
    s += this._stroke([[0, 120], [W, 106]], rand, { w: 5, r: 3.4, s: C.grey, op: 0.42, ov: 20 });
    var docs = [[420, 168, 380, 480, -7], [860, 132, 400, 500, 5], [1330, 210, 386, 470, -4],
      [640, 594, 400, 470, 9], [1130, 604, 400, 466, -8]];
    docs.forEach(function (d, idx) {
      var card = self._box(rand, d[0], d[1], d[2], d[3], { w: 7 })
        + self._stroke([[d[0] + 26, d[1] + 74], [d[0] + d[2] - 26, d[1] + 68]], rand, { w: 5, r: 2.8, ov: 10 })
        + self.shade(rand, d[0] + d[2] + 4, d[1] + d[3] * 0.9, 56);
      s += self._rot(d[4], d[0] + d[2] / 2, d[1] + d[3] / 2, card);
      s += self.slot('doc-' + (idx + 1), d[0] + 24, d[1] + 96, d[2] - 48, d[3] - 124);
    });
    s += this.crumple(rand, 1810, 460, 0.9) + this.crumple(rand, 288, 880, 0.8);
    s += this.penTop(rand, 1740, 900, 180, -0.6);
    s += this.slot('figure', 20, 300, 360, 700);
    return s;
  };

  P.window16 = function (rand, mode) {
    /* the window alone, close. What is outside changes with the light overlay. */
    var s = this.windowFrame(rand, 380, 96, 1160, 800, mode || 'clear');
    s += this._stroke([[356, 918], [1564, 910]], rand, { w: 9, r: 3, ov: 14 });
    s += this.curtainHalf(rand, 380, 96, 1160, 800, 1);
    s += this.lightRays(rand, 200, 700, 3, 220, 80);
    s += this.wallFloor(rand, 1010, W);
    s += this.shade(rand, 1580, 900, 110);
    return s;
  };

  /* ── C · data plates ────────────────────────────────────────────────── */
  P.screenFull16 = function (rand) {
    var s = this._box(rand, 64, 44, 1792, 992, { w: 11 });
    s += this._box(rand, 108, 86, 1704, 872, { w: 5, r: 2.6, ov: 10 });
    s += this._stroke(this._ell(960, 1006, 12, 12, 0, Math.PI * 2), rand, { w: 5, r: 1.6, s: C.grey, close: true });
    s += this.slot('screen', 126, 104, 1668, 836);
    return s;
  };

  P.numberFull16 = function (rand) {
    var s = this.wallFloor(rand, 918, W);
    s += this.floorPlane(rand, 918, { w: W, x0: -30, x1: 620 });
    s += this.lightRays(rand, -30, 120, 3, 200, 72);
    s += this.slot('label', 470, 128, 980, 116);
    s += this.slot('figure', 260, 288, 1400, 520);
    s += this.slot('host', 1500, 470, 300, 450);
    s += this.shade(rand, 1470, 924, 96);
    return s;
  };

  P.sheetWide = function (rand) {
    var x = 96, y = 74, w = 1728, h = 936, i;
    var s = this._box(rand, x, y, w, h, { w: 9 });
    s += this._stroke([[x + 26, y + 132], [x + w - 26, y + 124]], rand, { w: 7, r: 3, ov: 16 });
    s += this.clip(rand, x + w / 2, y - 30, 1.3);
    s += this.pin(rand, x + 42, y + 34, 1.1) + this.pin(rand, x + w - 42, y + 30, 1.1);
    var ix = x + 32, iy = y + 158, iw = w - 64, ih = h - 190, bh = ih / 8;
    s += this.slot('interior', ix, iy, iw, ih);
    for (i = 0; i < 8; i++) {
      s += this.slot('row-' + (i + 1), ix, Math.round(iy + i * bh), iw, Math.round(bh));
      if (i > 0) s += this._stroke([[ix + 8, iy + i * bh], [ix + iw - 8, iy + i * bh - 3]], rand, { w: 3.4, r: 2.6, s: C.grey, op: 0.42, ov: 6 });
    }
    s += this.shade(rand, x + w + 8, y + h * 0.92, 96);
    return s;
  };

  /* ── E3 · a filing page on the desk, room at one edge for a red circle ── */
  P.filingPage = function (rand) {
    var x = 90, y = 70, w = 1000, h = 1300;
    var page = this._box(rand, x, y, w, h, { w: 8 })
      + this._stroke([[x + 60, y + 96], [x + w - 60, y + 88]], rand, { w: 6, r: 2.8, ov: 12 })
      + this._stroke([[x + 60, y + 150], [x + w * 0.5, y + 144]], rand, { w: 5, r: 2.6, s: C.grey, op: 0.7 })
      + this._stroke([[x + 60, y + h - 92], [x + w - 60, y + h - 98]], rand, { w: 4, r: 2.6, s: C.grey, op: 0.6, ov: 8 })
      + this.foldCorner(rand, x + w, y + h, 0.9, 1);
    var s = this._rot(-1.6, x + w / 2, y + h / 2, page);
    s += this.shade(rand, x + w + 10, y + h * 0.9, 84);
    /* the interior stays clean and high-contrast: a real screenshot drops in here */
    s += this.slot('page', x + 52, y + 196, w - 186, h - 342);
    /* the margin the red circle lives in — outside the interior, never over it */
    s += this.slot('margin', x + w - 126, y + 196, 118, h - 342);
    return s;
  };

  /* ── I · chapter stinger. A beat of silence: a rule and two slots. ───── */
  P.stinger16 = function (rand) {
    var s = this._stroke([[720, 596], [1200, 590]], rand, { w: 9, r: 3.4, ov: 18 });
    s += this.slot('chapter-number', 820, 400, 280, 108);
    s += this.slot('chapter-title', 300, 640, 1320, 200);
    return s;
  };

  /* ── J · the question card, and its struck-through answer state ──────── */
  P.questionCard = function (rand, answered) {
    var x = 300, y = 220, w = 1320, h = 620;
    var card = this._stroke([[x, y], [x + w, y - 10]], rand, { w: 8, r: 3.4, ov: 10 })
      + this._stroke([[x + w, y - 10], [x + w + 8, y + h]], rand, { w: 8, r: 3.4, ov: 8 })
      + this.tornEdge(rand, x + w + 8, y + h, x - 6, y + h + 12, 18)
      + this._stroke([[x - 6, y + h + 12], [x, y]], rand, { w: 8, r: 3.4, ov: 8 });
    var s = this._rot(-2.6, x + w / 2, y + h / 2, card);
    s += this.pin(rand, x + w * 0.5, y + 6, 1.5);
    s += this.shade(rand, x + w + 16, y + h * 0.92, 90);
    if (answered) s += this._stroke([[x + 20, y + h * 0.62], [x + w - 20, y + h * 0.4]], rand, { w: 13, r: 3.6, s: C.red, op: 0.9 });
    s += this.slot('question', x + 70, y + 90, w - 140, h - 210);
    return s;
  };

  /* ── H · close-ups ──────────────────────────────────────────────────── */
  P.cuPage = function (rand) {
    var s = this._box(rand, 180, -190, 1560, 1090, { w: 12 });
    s += this._stroke([[258, 218], [1662, 206]], rand, { w: 9, r: 3.4, ov: 18 });
    /* a hand, frame-filling, holding the page down at the lower edge */
    s += this._stroke([[420, 1080], [452, 940], [548, 872], [700, 852]], rand, { w: 11, r: 4 });
    s += this._stroke([[700, 852], [880, 858], [1010, 902], [1052, 1010], [1040, 1080]], rand, { w: 11, r: 4 });
    var i; for (i = 0; i < 4; i++) {
      var fx = 700 + i * 92, fy = 856 + i * 16;
      s += this._stroke([[fx, fy], [fx + 54, fy - 66], [fx + 116, fy - 40], [fx + 122, fy + 34]], rand, { w: 9, r: 3.4 });
    }
    s += this._stroke([[498, 906], [572, 878]], rand, { w: 6, r: 2.6, s: C.grey, op: 0.7 });
    s += this.shade(rand, 1750, 880, 110);
    s += this.slot('page', 240, 250, 1440, 560);
    return s;
  };

  P.cuNumber = function (rand) {
    /* paper this close: the tooth of it, a rule above and below, a pen edge */
    var s = this._stroke([[0, 150], [W, 138]], rand, { w: 5, r: 3.4, s: C.grey, op: 0.5, ov: 20 });
    s += this._stroke([[0, 946], [W, 934]], rand, { w: 5, r: 3.4, s: C.grey, op: 0.5, ov: 20 });
    var i; for (i = 0; i < 26; i++) {
      var gx = rand() * W, gy = 170 + rand() * 750, gl = 30 + rand() * 90;
      s += this._stroke([[gx, gy], [gx + gl, gy + gl * 0.3]], rand, { w: 3, r: 3.4, s: C.grey, op: 0.14 + rand() * 0.12 });
    }
    s += this.tornEdge(rand, 0, 62, W, 44, 22);
    s += this.penTop(rand, 1540, 1020, 420, -0.74);
    s += this.shade(rand, 1560, 1010, 120);
    s += this.slot('figure', 300, 260, 1080, 540);
    return s;
  };

  /* ── K · thumbnails, 1280×720 ───────────────────────────────────────── */
  P.thumbNumber = function (rand) {
    /* everything here has to survive 210px wide: heavy edge, one heavy rule */
    var s = this._box(rand, 22, 22, 1236, 676, { w: 16 });
    s += this._stroke([[70, 596], [760, 588]], rand, { w: 20, r: 4 });
    s += this._stroke([[820, 300], [1206, 294]], rand, { w: 13, r: 3.4, ov: 8 });
    s += this.slot('figure', 70, 110, 700, 452);
    s += this.slot('headline', 820, 130, 386, 150);
    s += this.slot('host', 820, 330, 386, 330);
    return s;
  };
  P.thumbFace = function (rand) {
    var s = this._box(rand, 22, 22, 1236, 676, { w: 16 });
    s += this._stroke([[646, 40], [654, 680]], rand, { w: 16, r: 4 });
    s += this._stroke([[700, 452], [1204, 446]], rand, { w: 18, r: 4 });
    s += this.slot('host', 56, 56, 566, 608);
    s += this.slot('headline', 700, 150, 508, 282);
    s += this.slot('figure', 700, 480, 508, 184);
    return s;
  };
  P.thumbSplit = function (rand) {
    var s = this._box(rand, 22, 22, 1236, 676, { w: 16 });
    s += this._stroke([[586, -20], [700, 740]], rand, { w: 26, r: 5 });
    s += this._stroke([[86, 232], [520, 226]], rand, { w: 16, r: 3.6 });
    s += this._stroke([[766, 232], [1200, 226]], rand, { w: 16, r: 3.6 });
    s += this.slot('headline', 86, 74, 434, 140);
    s += this.slot('figure', 86, 264, 434, 384);
    s += this.slot('host', 766, 264, 434, 384);
    return s;
  };

  /* ── L · the closing plate. Right third and lower band stay empty. ───── */
  P.closingPlate16 = function (rand) {
    var FY = 712, DY = 780;
    var s = this.wallFloor(rand, FY, W);
    s += this.floorPlane(rand, FY, { w: W, x0: -30, x1: 1180 });
    s += this.windowWide(rand, -70, 118, 336, 306, 1, 220);
    s += this.wallClock(rand, 434, 190, 76, 'clock-face');
    s += this.deskSlab(rand, 252, DY, 990, 60, 372, 1140, 236);
    s += this._stroke([[262, DY + 62], [1234, DY + 58]], rand, { w: 4, r: 2.6, s: C.grey, op: 0.44, ov: 8 });
    s += this.lamp(rand, 316, DY - 2, true);
    s += this.monitorFront(rand, 428, DY - 240, 330, 238, 'screen');
    s += this.cableRun(rand, 560, DY + 6, 520, 1032, 130, 2);
    s += this.wasteBasket(rand, 196, 1024, 1.05);
    s += this.shade(rand, 766, DY + 44, 72);
    /* the two regions the platform cards will cover, declared so nothing lands there */
    s += this.slot('clear-right-third', 1280, 0, 640, 1080);
    s += this.slot('clear-lower-band', 0, 860, 1920, 220);
    s += this.slot('figure', 700, 250, 540, 530);
    s += this.slot('sign-off', 120, 96, 1040, 150);
    return s;
  };

  /* ── D · THE DIVE. The bezel grows; the viewer travels into it.
     The landing is exact: the over-shoulder monitor's OUTER BEZEL is drawn to
     the same aspect as screen-full-16's bezel, so the last dive frame and the
     screen plate are the same picture and the cut is invisible. ─────────── */
  var DIVE_BEZEL = { x: 470, y: 150, w: 986, h: 546 };   /* roomOver16's monitor */
  var DIVE_TARGET = { x: 64, y: 44, w: 1792, h: 992 };   /* screenFull16's bezel */
  P.diveTransform = function (t) {
    var K = DIVE_TARGET.w / DIVE_BEZEL.w,
      TX = DIVE_TARGET.x - DIVE_BEZEL.x * K, TY = DIVE_TARGET.y - DIVE_BEZEL.y * K,
      e = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2,
      k = 1 + (K - 1) * e;
    return 'translate(' + (TX * e).toFixed(2) + ',' + (TY * e).toFixed(2) + ') scale(' + k.toFixed(4) + ')';
  };
  P.dive = function (rand, f, total, dir) {
    var t = total < 2 ? 1 : f / (total - 1); if (dir < 0) t = 1 - t;
    return '<g transform="' + this.diveTransform(t) + '">' + this.roomOver16(rand, 'lived-in') + '</g>';
  };

  /* ── the cut, 16:9 · one broad chisel sweep on, then off ────────────── */
  P.inkWipe16 = function (rand, f, total) {
    total = total || 9;
    var mid = (total - 1) / 2, cov = f <= mid ? f / mid : (total - 1 - f) / mid, laying = f <= mid;
    if (cov <= 0.001) return '';
    var s = '', i, span = W + 320,
      edgeX = laying ? -160 + cov * span : (1 - cov) * span - 160,
      x0 = laying ? -160 : edgeX, x1 = laying ? edgeX : W + 160,
      wid = Math.max(1, x1 - x0), edge = [];
    for (i = 0; i <= 12; i++) edge.push([(laying ? x1 : x0) + (rand() * 2 - 1) * 32, -60 + i * (H + 120) / 12]);
    var poly = laying ? [[x0, -60]].concat(edge).concat([[x0, H + 60]]) : edge.concat([[x1, H + 60], [x1, -60]]);
    s += this._p(this.rpath(poly, rand, 7) + 'Z', { f: this.pen.ink, s: 'none', w: 0 });
    var n = Math.max(2, Math.round(wid / 92));
    for (i = 0; i < n; i++) {
      var bx = x0 + (i + 0.5) * wid / n;
      s += this._stroke([[bx + (rand() * 2 - 1) * 14, -40], [bx + (rand() * 2 - 1) * 28, H + 40]], rand, { w: 3.6, r: 6, s: C.paper, op: 0.15 });
    }
    var ex = laying ? x1 : x0, dir = laying ? 1 : -1;
    for (i = 0; i < 5; i++) {
      var ey = 80 + rand() * (H - 160), L = 40 + rand() * 150;
      s += this._stroke([[ex, ey], [ex + dir * L, ey + (rand() * 2 - 1) * 26]], rand, { w: 6 + rand() * 10, r: 3.4, op: 0.82 });
    }
    return s;
  };

  /* ── M · light overlays. Register-agnostic, multiplied over a room plate.
     Subtle by construction: they shift mood, they do not recolour the ink. ── */
  var LIGHT = {
    daylight: { wash: '#fffdf7', shaft: '#ffffff', shaftOp: 0.9, shadow: '#efece2', shadowOp: 0.5, len: 300, lamp: 0 },
    afternoon: { wash: '#fff6e6', shaft: '#fff2da', shaftOp: 0.85, shadow: '#e9e1cf', shadowOp: 0.6, len: 620, lamp: 0 },
    dusk: { wash: '#eee7e6', shaft: '#f6ddc6', shaftOp: 0.7, shadow: '#d8d0cb', shadowOp: 0.66, len: 980, lamp: 0.35 },
    '3am': { wash: '#c3c8d6', shaft: '#cdd2df', shaftOp: 0.5, shadow: '#a9aebd', shadowOp: 0.62, len: 0, lamp: 1 }
  };
  P.lightPlate = function (rand, mode) {
    var L = LIGHT[mode], s = '', i, id = mode.replace(/[^a-z0-9]/g, '');
    /* gradients, not wedges: at full strength these shift the mood and leave
       the ink alone. No hard edge anywhere — light does not have outlines. */
    s += '<defs>'
      + '<linearGradient id="sh-' + id + '" x1="0" y1="0" x2="1" y2="0.5">'
      + '<stop offset="0" stop-color="' + L.shaft + '" stop-opacity="' + L.shaftOp + '"/>'
      + '<stop offset="0.55" stop-color="' + L.shaft + '" stop-opacity="' + (L.shaftOp * 0.45).toFixed(3) + '"/>'
      + '<stop offset="1" stop-color="' + L.shaft + '" stop-opacity="0"/></linearGradient>'
      + '<linearGradient id="sd-' + id + '" x1="0" y1="0" x2="1" y2="0">'
      + '<stop offset="0" stop-color="' + L.shadow + '" stop-opacity="0"/>'
      + '<stop offset="0.62" stop-color="' + L.shadow + '" stop-opacity="' + (L.shadowOp * 0.4).toFixed(3) + '"/>'
      + '<stop offset="1" stop-color="' + L.shadow + '" stop-opacity="' + (L.shadowOp * 0.78).toFixed(3) + '"/></linearGradient>'
      + '<linearGradient id="fl-' + id + '" x1="0" y1="0" x2="0" y2="1">'
      + '<stop offset="0" stop-color="' + L.shadow + '" stop-opacity="0"/>'
      + '<stop offset="1" stop-color="' + L.shadow + '" stop-opacity="' + (L.shadowOp * 0.5).toFixed(3) + '"/></linearGradient>';
    if (L.lamp > 0) {
      s += '<radialGradient id="lp-' + id + '" cx="0.5" cy="0.5" r="0.5">'
        + '<stop offset="0" stop-color="#fff0cd" stop-opacity="' + L.lamp + '"/>'
        + '<stop offset="0.55" stop-color="#fff0cd" stop-opacity="' + (L.lamp * 0.4).toFixed(3) + '"/>'
        + '<stop offset="1" stop-color="#fff0cd" stop-opacity="0"/></radialGradient>';
    }
    s += '</defs>';
    s += '<rect x="0" y="0" width="' + W + '" height="' + H + '" fill="' + L.wash + '"/>';
    s += '<rect x="0" y="0" width="' + W + '" height="' + H + '" fill="url(#sd-' + id + ')"/>';
    if (L.len > 0) s += '<rect x="0" y="0" width="' + Math.min(W, L.len + 380) + '" height="' + H + '" fill="url(#sh-' + id + ')"/>';
    if (L.lamp > 0) s += '<ellipse cx="300" cy="640" rx="680" ry="560" fill="url(#lp-' + id + ')"/>';
    s += '<rect x="0" y="' + (H * 0.72).toFixed(0) + '" width="' + W + '" height="' + (H * 0.28).toFixed(0) + '" fill="url(#fl-' + id + ')"/>';
    /* paper grain, so the layer reads as drawn and not as a gel */
    for (i = 0; i < 34; i++) {
      var gx = rand() * W, gy = rand() * H, gl = 60 + rand() * 210;
      s += '<path d="M' + gx.toFixed(0) + ',' + gy.toFixed(0) + ' L' + (gx + gl).toFixed(0) + ',' + (gy + gl * 0.44).toFixed(0) + '" stroke="' + L.shadow + '" stroke-width="' + (10 + rand() * 30).toFixed(1) + '" opacity="' + (0.04 + rand() * 0.07).toFixed(3) + '" fill="none"/>';
    }
    return s;
  };

  /* ── registry ───────────────────────────────────────────────────────── */
  var SRC16 = { x: 0, y: 0, w: W, h: H }, CAN16 = [1920, 1080], DEL16 = [3840, 2160], KW = 1.6;
  function reg16(key, o) {
    o.src = o.src || SRC16; o.canvas = o.canvas || CAN16; o.deliver = o.deliver || DEL16; o.kw = o.kw == null ? KW : o.kw;
    A[key + '--marker'] = o;
  }

  /* A · five viewpoints × three clutter states */
  var VIEWS = [['room-wide-16', 'roomWide16', 101], ['room-side-16', 'roomSide16', 102],
    ['room-over-shoulder-16', 'roomOver16', 103], ['desk-top-down-16', 'deskTop16', 104], ['at-the-sheet-16', 'atSheet16', 105]];
  var STATES = [['tidy', 0], ['lived-in', 1], ['3am', 2]];
  VIEWS.forEach(function (v) {
    STATES.forEach(function (st) {
      reg16(v[0] + '--' + st[0], {
        concept: v[0] + '--' + st[0], group: 'A', seed: v[2] * 13 + st[1],
        draw: (function (fn, state) { return function (i, r) { return i[fn](r, state); }; })(v[1], st[0])
      });
    });
  });

  /* B · surfaces */
  reg16('whiteboard-16', { concept: 'whiteboard-16', group: 'B', seed: 121, draw: function (i, r) { return i.whiteboard16(r); } });
  ['empty', 'half', 'full'].forEach(function (lv, n) {
    reg16('evidence-wall-' + lv, { concept: 'evidence-wall-' + lv, group: 'B', seed: 130 + n, draw: function (i, r) { return i.evidenceWall(r, lv); } });
  });
  reg16('wall-of-past-calls-16', { concept: 'wall-of-past-calls-16', group: 'B', seed: 134, draw: function (i, r) { return i.pastCalls16(r); } });
  reg16('projection-wall-16', { concept: 'projection-wall-16', group: 'B', seed: 135, draw: function (i, r) { return i.projection16(r); } });
  reg16('floor-spread-16', { concept: 'floor-spread-16', group: 'B', seed: 136, draw: function (i, r) { return i.floorSpread16(r); } });
  reg16('window-16', { concept: 'window-16', group: 'B', seed: 137, draw: function (i, r) { return i.window16(r, 'clear'); } });
  reg16('doorway-16', { concept: 'doorway-16', group: 'B', seed: 138, draw: function (i, r) { return i.doorway16(r); } });

  /* C · data plates */
  reg16('screen-full-16', { concept: 'screen-full-16', group: 'C', seed: 141, draw: function (i, r) { return i.screenFull16(r); } });
  reg16('number-full-16', { concept: 'number-full-16', group: 'C', seed: 142, draw: function (i, r) { return i.numberFull16(r); } });
  reg16('sheet-wide', { concept: 'sheet-wide', group: 'C', seed: 143, draw: function (i, r) { return i.sheetWide(r); } });

  /* D · the dive */
  reg16('dive-in', {
    concept: 'dive-in', group: 'D', seed: 151, frames: 10, playback: 'one-shot',
    draw: function (i, r, f) { return i.dive(r, f, 10, 1); }
  });
  reg16('dive-out', {
    concept: 'dive-out', group: 'D', seed: 151, frames: 10, playback: 'one-shot',
    draw: function (i, r, f) { return i.dive(r, f, 10, -1); }
  });

  /* E · media and filings */
  reg16('filing-page-on-desk', {
    concept: 'filing-page-on-desk', group: 'E', seed: 161,
    src: { x: 0, y: 0, w: 1180, h: 1440 }, canvas: [1200, 1464], deliver: [2400, 2928], kw: 1.2,
    draw: function (i, r) { return i.filingPage(r); }
  });

  /* H · close-ups */
  reg16('cu-page', { concept: 'cu-page', group: 'H', seed: 171, draw: function (i, r) { return i.cuPage(r); } });
  reg16('cu-number', { concept: 'cu-number', group: 'H', seed: 172, draw: function (i, r) { return i.cuNumber(r); } });

  /* I · the chapter stinger */
  reg16('chapter-stinger', { concept: 'chapter-stinger', group: 'I', seed: 181, draw: function (i, r) { return i.stinger16(r); } });

  /* J · the open loop */
  reg16('question-card', { concept: 'question-card', group: 'J', seed: 191, draw: function (i, r) { return i.questionCard(r, false); } });
  reg16('question-card-answered', { concept: 'question-card-answered', group: 'J', seed: 191, draw: function (i, r) { return i.questionCard(r, true); } });

  /* K · thumbnails */
  [['thumb-number', 'thumbNumber', 201], ['thumb-face', 'thumbFace', 202], ['thumb-split', 'thumbSplit', 203]].forEach(function (t) {
    reg16(t[0], {
      concept: t[0], group: 'K', seed: t[2], src: { x: 0, y: 0, w: 1280, h: 720 },
      canvas: [1280, 720], deliver: [1280, 720], kw: 1.05,
      draw: (function (fn) { return function (i, r) { return i[fn](r); }; })(t[1])
    });
  });

  /* L · the closing plate */
  reg16('closing-plate-16', { concept: 'closing-plate-16', group: 'L', seed: 211, draw: function (i, r) { return i.closingPlate16(r); } });

  /* the 16:9 cut */
  reg16('ink-wipe-16', {
    concept: 'ink-wipe-16', group: 'E', seed: 221, frames: 9, playback: 'one-shot',
    draw: function (i, r, f) { return i.inkWipe16(r, f, 9); }, frameSeed: function (f) { return 221 * 7919 + f * 331; }
  });

  /* M · light. Delivered once — these are register-agnostic. */
  ['daylight', 'afternoon', 'dusk', '3am'].forEach(function (m, n) {
    A['light-' + m] = {
      concept: 'light-' + m, group: 'M', src: SRC16, canvas: CAN16, deliver: DEL16, kw: 1, seed: 231 + n,
      registerAgnostic: true, draw: function (i, r) { return i.lightPlate(r, m); }
    };
  });

  /* the other three registers: same geometry, same slots, different instrument.
     M is not cloned — light is light. */
  [['ballpoint', 'ballpoint', 1000], ['grease-pencil', 'grease', 2000], ['cut-paper', 'cutpaper', 3000]].forEach(function (rg) {
    Object.keys(A).forEach(function (key) {
      var a = A[key];
      if (a.group === 'ID' || a.group === 'M' || a.pen || !/--marker$/.test(key)) return;
      if (A[key.replace(/--marker$/, '--' + rg[0])]) return;
      var o = {}; Object.keys(a).forEach(function (p) { o[p] = a[p]; });
      o.pen = rg[1]; o.seed = a.seed + rg[2];
      if (a.frameSeed) { var sd = o.seed; o.frameSeed = function (f) { return sd * 7919 + f * 331; }; }
      A[key.replace(/--marker$/, '--' + rg[0])] = o;
    });
  });

  API.PINS = PINS;
  API.LONG = { W: W, H: H, DIVE_BEZEL: DIVE_BEZEL, DIVE_TARGET: DIVE_TARGET };
  }
  /* boot, then keep watching: if the host rebuilds DennisInk (hot reload), this
     file must register into the NEW registry or the page shows a stale kit. */
  var booted = null;
  function tryBoot() {
    if (!global.DennisInk || global.DennisInk === booted) return;
    booted = global.DennisInk; boot();
  }
  tryBoot();
  setInterval(tryBoot, 250);
})(typeof window !== 'undefined' ? window : globalThis);
