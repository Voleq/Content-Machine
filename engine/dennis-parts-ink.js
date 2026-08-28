/* Dennis · PARTS · the data containers (F), the media carriers (E), the host's
   range (G), the frame-filling face (H3) and the five ambient loops (3.3).
   Loads after dennis-marker-ink.js and dennis-long-ink.js.

   F is the important discipline here: NOT ONE of these draws data. Each is
   frame, axis furniture, rules and header with an empty interior, and code
   draws the bars, lines, figures and labels at render time in the same stroke.
   No sample bars, no placeholder rows, no numbers, and no world colour —
   world colour never touches a plate interior. */
(function (global) {
  var W = 1920, H = 1080;

  function boot() {
    var API = global.DennisInk, P = API.Ink.prototype, C = API.C, A = API.ASSETS;

    /* ── F · data display containers ─────────────────────────────────── */

    /* the shared furniture: a plot box with an axis band and a title band, so
       all ten plates sit on one grid and code can trust the same margins */
    P.plotFrame = function (rand, o) {
      o = o || {};
      var x = o.x || 190, y = o.y || 210, w = o.w || 1560, h = o.h || 640,
        ticks = o.ticks == null ? 4 : o.ticks, cols = o.cols || 0, i, s = '';
      s += this._stroke([[x, y - 44], [x, y + h]], rand, { w: 8, r: 2.8, ov: 14 });
      s += this._stroke([[x, y + h], [x + w + 40, y + h]], rand, { w: 8, r: 2.8, ov: 14 });
      for (i = 1; i <= ticks; i++) {
        var yy = y + h - h * i / ticks;
        s += this._stroke([[x - 20, yy], [x + 14, yy - 2]], rand, { w: 4.4, r: 2, s: C.grey });
        s += this._stroke([[x + 24, yy], [x + w, yy - 5]], rand, { w: 2.8, r: 3.4, s: C.grey, op: 0.24 });
      }
      for (i = 0; i < cols; i++) {
        var xx = x + w * (i + 0.5) / cols;
        s += this._stroke([[xx, y + h], [xx, y + h + 20]], rand, { w: 4.4, r: 2, s: C.grey });
      }
      s += this.slot('plot', x + 12, y, w, h - 8);
      s += this.slot('axis-band', x, y + h + 26, w, 96);
      if (o.title !== false) s += this.slot('title', x - 6, 74, w * 0.78, 112);
      return s;
    };

    P.seriesLine = function (rand) { return this.plotFrame(rand, { ticks: 4, cols: 6 }); };
    P.seriesBar = function (rand) {
      var s = this.plotFrame(rand, { ticks: 4, cols: 9 });
      /* the one thing a bar container owns that a line container does not:
         a baseline heavy enough for bars to sit on */
      return s + this._stroke([[190, 850], [1790, 848]], rand, { w: 11, r: 2.6, ov: 16 });
    };

    P.waterfall = function (rand) {
      /* a bridge: the start and end columns are DRAWN because they are the
         container's furniture; the floating middles are slots for code */
      var x = 190, y = 210, w = 1560, h = 640, i, s = this.plotFrame(rand, { ticks: 4, title: true });
      s += this._stroke([[x + 20, y + h], [x + 20, y + h]], rand, { w: 4 });
      s += this.slot('start-column', x + 26, y + 150, 170, h - 158);
      s += this.slot('end-column', x + w - 190, y + 90, 170, h - 98);
      for (i = 0; i < 4; i++) s += this.slot('bridge-' + (i + 1), x + 250 + i * 240, y + 60, 170, h - 120);
      /* the connector rules between columns, dotted, drawn */
      for (i = 0; i < 5; i++) {
        var cx = x + 210 + i * 240;
        s += this._stroke([[cx, y + 120 + i * 20], [cx + 36, y + 118 + i * 20]], rand, { w: 3.4, r: 2.6, s: C.grey, op: 0.5 });
      }
      return s;
    };

    P.splitBar = function (rand) {
      var x = 210, y = 380, w = 1500, h = 240;
      var s = this._box(rand, x, y, w, h, { w: 10 });
      s += this._stroke([[x + w * 0.62, y - 18], [x + w * 0.62, y + h + 18]], rand, { w: 8, r: 2.8 });
      s += this.slot('plot', x + 8, y + 8, w - 16, h - 16);
      s += this.slot('label-a', x, y + h + 54, w * 0.62, 130);
      s += this.slot('label-b', x + w * 0.62, y + h + 54, w * 0.38, 130);
      s += this.slot('title', x - 6, 120, w * 0.8, 118);
      return s;
    };

    P.theDollar = function (rand) {
      /* one unit divided into labelled slices, largest first. The unit is a
         drawn bar; the divisions and every label are slots. */
      var x = 200, y = 250, w = 1520, h = 300, i, cuts = [0.42, 0.66, 0.82, 0.93];
      var s = this._box(rand, x, y, w, h, { w: 12 });
      for (i = 0; i < cuts.length; i++) {
        var cx = x + w * cuts[i];
        s += this._stroke([[cx, y - 10], [cx, y + h + 10]], rand, { w: 7, r: 2.8 });
      }
      s += this.slot('unit', x + 10, y + 10, w - 20, h - 20);
      var edges = [0].concat(cuts).concat([1]);
      for (i = 0; i < 5; i++) {
        var a = x + w * edges[i], b = x + w * edges[i + 1];
        s += this.slot('label-' + (i + 1), a + 8, y + h + 40, b - a - 16, 210);
      }
      s += this.slot('title', x - 6, 96, w * 0.78, 112);
      return s;
    };

    P.compsTable = function (rand) {
      var x = 120, y = 190, w = 1680, h = 780, rows = 6, i,
        pct = 190, body = w - pct, colw = body / 4, rh = (h - 96) / rows;
      var s = this._box(rand, x, y, w, h, { w: 9 });
      s += this._stroke([[x + 14, y + 96], [x + w - 14, y + 92]], rand, { w: 7, r: 2.8, ov: 12 });
      s += this._stroke([[x + body, y + 8], [x + body, y + h - 8]], rand, { w: 7, r: 2.8 });
      for (i = 1; i < 4; i++) s += this._stroke([[x + colw * i, y + 104], [x + colw * i, y + h - 12]], rand, { w: 3.4, r: 2.8, s: C.grey, op: 0.4 });
      for (i = 1; i < rows; i++) s += this._stroke([[x + 16, y + 96 + rh * i], [x + w - 16, y + 94 + rh * i]], rand, { w: 3.4, r: 2.6, s: C.grey, op: 0.4, ov: 6 });
      s += this.slot('header', x + 20, y + 12, w - 40, 76);
      for (i = 0; i < rows; i++) s += this.slot('row-' + (i + 1), x + 14, Math.round(y + 96 + rh * i), w - 28, Math.round(rh));
      for (i = 0; i < 4; i++) s += this.slot('col-' + (i + 1), Math.round(x + colw * i), y + 96, Math.round(colw), h - 108);
      s += this.slot('col-percentile', Math.round(x + body), y + 96, pct, h - 108);
      return s;
    };

    P.rankStrip = function (rand) {
      var x = 200, y = 470, w = 1520, i;
      var s = this._stroke([[x, y], [x + w, y - 4]], rand, { w: 14, r: 3 });
      for (i = 0; i <= 10; i++) {
        var cx = x + w * i / 10, tall = i % 5 === 0;
        s += this._stroke([[cx, y - (tall ? 34 : 20)], [cx, y + (tall ? 34 : 20)]], rand, { w: tall ? 6 : 4, r: 2, s: tall ? C.ink : C.grey });
      }
      s += this.slot('strip', x, y - 30, w, 60);
      s += this.slot('marker', x, y - 190, w, 150);
      s += this.slot('label-low', x - 30, y + 70, 460, 130);
      s += this.slot('label-high', x + w - 430, y + 70, 460, 130);
      s += this.slot('title', x - 6, 150, w * 0.78, 118);
      return s;
    };

    P.scatter = function (rand) {
      var s = this.plotFrame(rand, { x: 260, y: 200, w: 1440, h: 660, ticks: 4 });
      s += this.slot('label-x', 300, 930, 1360, 108);
      /* the y label runs up the left edge, so it gets its own upright slot */
      s += this.slot('label-y', 40, 240, 176, 600);
      return s;
    };

    P.bigFraction = function (rand) {
      var s = this._stroke([[430, 552], [1490, 546]], rand, { w: 16, r: 3.4, ov: 18 });
      s += this.slot('numerator', 430, 130, 1060, 380);
      s += this.slot('denominator', 430, 590, 1060, 340);
      s += this.slot('caption', 430, 962, 1060, 96);
      return s;
    };

    P.quotePull = function (rand) {
      /* the oversized opening mark is furniture and IS drawn — it is a piece of
         the plate, not content. Everything else is a slot. */
      var mark = function (self, x) {
        /* a comma, not a letter: a heavy head and a tail that drops away */
        return self._stroke(self._ell(x, 232, 40, 40, 0.5, Math.PI * 2.1), rand, { w: 22, r: 3.4 })
          + self._stroke([[x + 4, 268], [x - 14, 322], [x - 46, 348]], rand, { w: 20, r: 3.4 });
      };
      var s = mark(this, 250) + mark(this, 386);
      s += this._stroke([[240, 830], [640, 826]], rand, { w: 8, r: 2.8, ov: 10 });
      s += this.slot('quote', 240, 340, 1440, 430);
      s += this.slot('attribution', 240, 880, 1000, 130);
      return s;
    };

    /* ── E · the media carriers ──────────────────────────────────────── */

    P.printOnDesk = function (rand) {
      /* a photographic print: torn on one edge, curled on another, and it has
         thickness — the shadow says so */
      var x = 110, y = 120, w = 1180, h = 820;
      var g = this._stroke([[x, y], [x + w, y - 14]], rand, { w: 7, r: 2.6 })
        + this._stroke([[x + w, y - 14], [x + w + 10, y + h - 30]], rand, { w: 7, r: 2.6 })
        + this.tornEdge(rand, x + w + 10, y + h - 30, x - 8, y + h, 20)
        + this._stroke([[x - 8, y + h], [x, y]], rand, { w: 7, r: 2.6 })
        + this.foldCorner(rand, x + w + 6, y + h - 34, 1.3, 1);
      var s = this._rot(-2, x + w / 2, y + h / 2, g);
      s += this.shade(rand, x + w + 18, y + h * 0.9, 96) + this.shade(rand, x + w * 0.5, y + h + 16, 70);
      s += this.slot('image', x + 34, y + 34, w - 88, h - 96);
      return s;
    };

    P.pinnedItem = function (rand) {
      /* sized to sit in an evidence-wall pin slot: one tack, hanging crooked */
      var x = 90, y = 110, w = 900, h = 1120;
      var g = this._box(rand, x, y, w, h, { w: 8 }) + this.foldCorner(rand, x + w, y + h, 1.1, 1);
      var s = this._rot(2.6, x + w / 2, y + 60, g);
      s += this.pin(rand, x + w * 0.5, y + 26, 1.7);
      s += this.shade(rand, x + w + 12, y + h * 0.9, 90);
      s += this.slot('image', x + 40, y + 96, w - 80, h - 170);
      return s;
    };

    P.filingOnScreen = function (rand) {
      /* the same document as E3, now on the monitor, him at the frame edge.
         The interior is clean and high-contrast: a real screenshot lands here. */
      /* the monitor owns the frame, him at the edge reading it */
      var s = this._box(rand, 352, 40, 1536, 1000, { w: 13 });
      s += this._box(rand, 398, 88, 1444, 904, { w: 5, r: 2.6, ov: 10, s: C.grey });
      s += this._stroke(this._ell(414, 1014, 11, 11, 0, Math.PI * 2), rand, { w: 5, r: 1.6, s: C.grey, close: true });
      s += this.lightRays(rand, -30, 90, 3, 210, 74);
      s += this.slot('screen', 418, 108, 1404, 864);
      s += this.slot('figure', 0, 330, 340, 750);
      return s;
    };

    /* ── H3 · his face, frame-filling. The confession beat. No slot. ─── */
    P.cuFace = function (rand) {
      /* frame-filling means frame-filling: the head is cropped by the frame at
         the crown and the chin sits near the lower edge. No slot — this plate
         is for the confession beat and nothing else. */
      var K = 5.6, cx = 960, cy = 560;
      var g = this.hHead(rand) + this.hEyes(rand, 0) + this.hMouth(rand, 'closed');
      var s = '<g transform="translate(' + (cx - 500 * K).toFixed(1) + ',' + (cy - 300 * K).toFixed(1) + ') scale(' + K + ')">' + g + '</g>';
      s += this._stroke([[-60, 1080], [180, 1006], [430, 986]], rand, { w: 22, r: 6 });
      s += this._stroke([[1490, 986], [1740, 1010], [1980, 1080]], rand, { w: 22, r: 6 });
      return s;
    };

    /* ── G · the host's range ────────────────────────────────────────── */

    /* four more arms, so the four gestures are the same rig and not new art */
    var baseArm = P.hArm;
    P.hArm = function (rand, arm) {
      var self = this, L = function (pts, w) { return self._stroke(pts, rand, { w: w || 7, r: 3 }); };
      if (arm === 'arms-folded')
        return L([[418, 500], [452, 566], [590, 578]]) + L([[582, 500], [552, 570], [418, 560]])
          + this._stroke([[440, 556], [578, 566]], rand, { w: 5, r: 2.6, s: C.grey, op: 0.7 });
      if (arm === 'weighing')
        return L([[418, 500], [330, 552], [268, 574]]) + this._stroke([[268, 574], [232, 566], [236, 596], [266, 598]], rand, { w: 5, r: 2.4 })
          + L([[582, 500], [670, 552], [732, 574]]) + this._stroke([[732, 574], [768, 566], [764, 596], [734, 598]], rand, { w: 5, r: 2.4 });
      if (arm === 'rub-neck')
        return L([[418, 500], [404, 594], [400, 650]])
          + L([[582, 500], [640, 430], [598, 344]]) + this._stroke([[598, 344], [566, 330], [552, 356], [580, 366]], rand, { w: 5, r: 2.4 });
      if (arm === 'hand-stop')
        return L([[418, 500], [404, 594], [400, 650]])
          + L([[582, 500], [660, 456], [700, 404]])
          + this._stroke([[700, 404], [742, 358], [786, 372], [764, 424], [716, 436]], rand, { w: 6, r: 2.6, close: true });
      return baseArm.call(this, rand, arm);
    };

    /* EIGHT more faces, all with OPEN eyes — weariness is a heavy lid over an
       open eye, never a closed arc. Closed is reserved for the blink. */
    P.hFace = function (rand, variant) {
      var Lx = 456, Rx = 544, s = '', lid = 0, mouth = 'closed', brow = 'flat', gaze = 0;
      if (variant === 'squinting') { lid = 1; brow = 'down'; }
      else if (variant === 'eyebrows-up-sceptical') { brow = 'up-one'; }
      else if (variant === 'looking-away-unconvinced') { gaze = 1; brow = 'flat'; }
      else if (variant === 'slow-blink') { lid = 2; }
      else if (variant === 'rubbing-eyes') { lid = 2; }
      else if (variant === 'mouth-tight-annoyed') { mouth = 'tight'; brow = 'down'; }
      else if (variant === 'faint-almost-smile') { mouth = 'faint'; }
      else if (variant === 'staring-through-it') { lid = 0; gaze = 0; brow = 'flat'; }
      s += this.hHead(rand);
      s += gaze ? this.hEyesSide(rand, 'right', lid) : this.hEyes(rand, lid);
      /* the brow does the work these faces need */
      if (brow === 'down') s += this._stroke([[Lx - 26, 240], [Lx + 22, 254]], rand, { w: 7, r: 2.6 })
        + this._stroke([[Rx - 22, 254], [Rx + 26, 240]], rand, { w: 7, r: 2.6 });
      else if (brow === 'up-one') s += this._stroke([[Lx - 26, 232], [Lx + 24, 220]], rand, { w: 7, r: 2.6 })
        + this._stroke([[Rx - 24, 246], [Rx + 26, 244]], rand, { w: 7, r: 2.6 });
      else s += this._stroke([[Lx - 26, 240], [Lx + 24, 238]], rand, { w: 6.4, r: 2.6 })
        + this._stroke([[Rx - 24, 238], [Rx + 26, 240]], rand, { w: 6.4, r: 2.6 });
      s += mouth === 'tight' ? this._stroke([[474, 360], [526, 358]], rand, { w: 8, r: 1.6, ov: 2 })
        : mouth === 'faint' ? this._stroke([[468, 356], [500, 366], [532, 354]], rand, { w: 5, r: 2 })
          : this.hMouth(rand, 'closed');
      if (variant === 'rubbing-eyes') s += this.hArm(rand, 'rub-neck');
      return s;
    };

    /* four poses, each with a talk loop, an IDLE loop and a closed-mouth still.
       The idle is the point: between gestures he used to freeze. */
    var POSE = {
      'at-the-whiteboard': { body: 'stand', head: 'right', arm: ['present-right', 'present-right-lo'] },
      'at-the-wall': { body: 'stand', head: 'front', arm: ['arms-folded', 'arms-folded'] },
      'seated-talking': { body: 'seated', head: 'front', arm: ['rest', 'gesture'] },
      'crouching': { body: 'crouch', head: 'right', arm: ['point-up', 'point-up-b'] }
    };
    P.hBodyCrouch = function (rand) {
      var s = this._stroke([[430, 520], [592, 512]], rand, { w: 7, r: 3, ov: 12 });
      s += this._stroke([[592, 512], [610, 660]], rand, { w: 7, r: 3 });
      s += this._stroke([[430, 520], [416, 664]], rand, { w: 7, r: 3 });
      s += this._stroke([[416, 664], [352, 742], [386, 800]], rand, { w: 8, r: 3 });
      s += this._stroke([[610, 660], [672, 742], [636, 802]], rand, { w: 8, r: 3 });
      s += this._stroke([[352, 806], [430, 802]], rand, { w: 7, r: 2.6, ov: 8 });
      s += this._stroke([[600, 806], [682, 802]], rand, { w: 7, r: 2.6, ov: 8 });
      return s;
    };
    P.poseBody = function (rand, kind) {
      return kind === 'seated' ? this.hBodySeated(rand) : kind === 'crouch' ? this.hBodyCrouch(rand) : this.hBody(rand);
    };
    P.poseHead = function (rand, kind, lid) {
      return kind === 'right' ? this.hHeadSide(rand, 'right') + this.hEyesSide(rand, 'right', lid)
        : this.hHead(rand) + this.hEyes(rand, lid);
    };
    P.pose = function (rand, key, mode, f) {
      var p = POSE[key], mouth, lid = 0, dx = p.head === 'right' ? 40 : 0, s;
      if (mode === 'talk') {
        mouth = ['closed', 'mid', 'open', 'mid', 'open', 'mid'][f % 6];
        lid = f % 6 === 4 ? 1 : 0;
        s = this.poseBody(rand, p.body) + this.hArm(rand, p.arm[f % 2])
          + this.poseHead(rand, p.head, lid) + this._shift(dx, 2, this.hMouth(rand, mouth));
        return this._shift(0, [0, -3, 0, 2][f % 4], s);
      }
      if (mode === 'idle') {
        /* weight shifting, shoulders settling, the hand drifting — 8 frames,
           and a slow blink lands inside it so he never stares */
        var sway = [0, -1, -2, -2, -1, 0, 1, 1][f % 8], rise = [0, -1, -1, 0, 1, 2, 1, 0][f % 8];
        lid = f % 8 === 5 ? 1 : f % 8 === 6 ? 2 : 0;
        s = this.poseBody(rand, p.body) + this.hArm(rand, p.arm[f % 8 < 4 ? 0 : 0])
          + this.poseHead(rand, p.head, lid) + this._shift(dx, 2, this.hMouth(rand, 'closed'));
        return this._shift(sway, rise, s);
      }
      return this.poseBody(rand, p.body) + this.hArm(rand, p.arm[0])
        + this.poseHead(rand, p.head, 0) + this._shift(dx, 2, this.hMouth(rand, 'closed'));
    };

    /* ── 3.3 · AMBIENT LOOPS. Almost subliminal. Their whole job is to stop
       the frame being a photograph. Each is a small transparent asset the
       renderer pins over its object in the room. ──────────────────────── */

    P.loopSteam = function (rand, f, total) {
      var t = f / total, s = '', i;
      for (i = 0; i < 3; i++) {
        var ph = (t + i / 3) % 1, x = 60 + i * 42, y = 250 - ph * 210,
          op = Math.sin(ph * Math.PI) * 0.5, sw = 6 + ph * 10;
        s += this._stroke([[x, y], [x + 16 - ph * 24, y - 42], [x - 6 + ph * 20, y - 84]], rand,
          { w: sw, r: 3.4, s: C.grey, op: Math.max(0, op) });
      }
      return s;
    };

    P.loopPlant = function (rand, f, total) {
      /* the plant moving slightly: the whole thing leans a degree and back */
      var a = Math.sin((f / total) * Math.PI * 2) * 1.1;
      return this._rot(a, 150, 300, this.dyingPlant(rand, 150, 290, 1.5));
    };

    P.loopCurtain = function (rand, f, total) {
      /* the curtain breathing: the folds move, the rail does not */
      var t = (f / total) * Math.PI * 2, i, s = '', n = 5, w = 420, h = 700;
      s += this._stroke([[10, 26], [w + 30, 22]], rand, { w: 7, r: 2.6, ov: 8 });
      for (i = 0; i <= n; i++) {
        var fx = 30 + w * i / n, sw = Math.sin(t + i * 0.7) * 11;
        s += this._stroke([[fx, 30], [fx + sw, h * 0.5], [fx + sw * 0.4, h]], rand, { w: 6, r: 2.6 });
      }
      s += this._stroke([[24, h], [w + 36, h - 12]], rand, { w: 5, r: 3, ov: 6 });
      return s;
    };

    P.loopCursor = function (rand, f, total) {
      /* a cursor blinking on the ignored second monitor: on for half the loop */
      return f < total / 2 ? this._stroke([[30, 20], [30, 92]], rand, { w: 13, r: 2 }) : '';
    };

    P.loopSecond = function (rand, f, total) {
      /* the clock's second hand. The hour and minute hands stay code-drawn from
         the light; this is the tick that says the room is running. */
      var a = (f / total) * Math.PI * 2 - Math.PI / 2, R = 120;
      return this._stroke([[150, 150], [150 + Math.cos(a) * R, 150 + Math.sin(a) * R]], rand,
        { w: 4.4, r: 1.6, s: C.red, op: 0.9 });
    };

    /* ── N · THE SHORTS ROOM, REVISED ─────────────────────────────────
       The shorts room and the long room must be the same place. Each of the
       five delivered 9:16 plates gains the standing furniture and the
       artefacts — placed strictly in the regions the delivered slots leave
       free, so SLOT NAMES AND COORDINATES DO NOT MOVE. The wrapper adds no
       slot of its own; the original function still declares them, in the same
       order, at the same x/y/w/h. One clutter state: lived-in. */
    function wrapShort(fn, add) {
      var base = P[fn];
      P[fn] = function (rand) {
        var body = base.call(this, rand);   /* slots are declared in here, untouched */
        return add.call(this, rand) + body; /* new furniture sits BEHIND the original */
      };
    }

    /* lived-in, and only lived-in: a short has no time to pass */
    P.shortClutter = function (rand, spots) { return this.clutter(rand, 'lived-in', spots); };

    wrapShort('roomWide', function (rand) {
      /* free: the wall above y=540, the right column beyond x=820, the floor
         below y=1330. The screen slot (69,965) and figure (400,550) are avoided. */
      var s = this.shelfBinders(rand, 706, 232, 330, 128, 8);
      s += this.shelfBinders(rand, 706, 424, 330, 128, 7);
      s += this.wallClock(rand, 168, 262, 84);
      s += this.framedShot(rand, 300, 168, 290, 196);
      s += this.postIt(rand, 636, 604, 1, -7, false) + this.postIt(rand, 636, 712, 0.9, 6, true);
      s += this.wallCalendar(rand, 856, 610, 196, 250);
      s += this.dyingPlant(rand, 972, 1452, 1.25);
      s += this.wasteBasket(rand, 148, 1560, 1.15);
      s += this.cableRun(rand, 300, 1290, 250, 1920, 190, 2);
      s += this.laptopIgnored(rand, 828, 1300, 0.68, -8);
      s += this.noodlePot(rand, 690, 1296, 0.86);
      s += this.canEmpty(rand, 610, 1292, 0.86, false) + this.canEmpty(rand, 950, 1288, 0.8, true);
      s += this.crumple(rand, 300, 1620, 0.9) + this.crumple(rand, 470, 1690, 0.78);
      s += this.phoneDown(rand, 176, 1268, 0.72, -8);
      return s;
    });

    wrapShort('roomSide', function (rand) {
      /* free: everything above y=840, and the right column beyond x=500 */
      var s = this.shelfBinders(rand, 596, 236, 400, 132, 9);
      s += this.shelfBinders(rand, 596, 434, 400, 132, 8);
      s += this.wallClock(rand, 214, 268, 86);
      s += this.framedShot(rand, 356, 170, 284, 190);
      s += this.wallCalendar(rand, 128, 470, 200, 254);
      s += this.postIt(rand, 400, 470, 0.94, -8, true) + this.postIt(rand, 400, 580, 0.86, 7, false);
      s += this.dyingPlant(rand, 992, 1560, 1.2);
      s += this.wasteBasket(rand, 620, 1720, 1.1);
      s += this.laptopIgnored(rand, 560, 1180, 0.62, -7);
      s += this.canEmpty(rand, 528, 1176, 0.8, false) + this.noodlePot(rand, 806, 1180, 0.8);
      s += this.crumple(rand, 700, 1790, 0.86);
      s += this.cableRun(rand, 900, 1240, 960, 1920, 180, 2);
      return s;
    });

    wrapShort('roomOver', function (rand) {
      /* free: above y=390 and below y=970 at the frame edges — the screen slot
         (177,410 727x540) and the back of his head stay clear */
      var s = this.shelfBinders(rand, 700, 96, 340, 118, 8);
      s += this.wallClock(rand, 112, 150, 74);
      s += this.postIt(rand, 258, 96, 0.86, -8, true);
      s += this.canEmpty(rand, 78, 1108, 0.86, false) + this.canEmpty(rand, 1006, 1104, 0.8, true);
      s += this.noodlePot(rand, 168, 1112, 0.8);
      s += this.crumple(rand, 940, 1150, 0.78);
      s += this.cableRun(rand, 250, 1060, 210, 1300, 120, 2);
      return s;
    });

    wrapShort('deskTop', function (rand) {
      /* free: above y=450 and below y=1520 — the pages slot (140,470 800x1040)
         is never intruded on */
      var s = this.phoneDown(rand, 96, 210, 0.94, -11);
      s += this.canEmpty(rand, 520, 300, 1, false) + this.canEmpty(rand, 616, 292, 0.9, true);
      s += this.noodlePot(rand, 880, 306, 0.94);
      s += this.crumple(rand, 250, 1650, 0.94) + this.crumple(rand, 830, 1690, 0.84);
      s += this.penTop(rand, 120, 1760, 250, -0.22);
      s += this.canEmpty(rand, 960, 1660, 0.86, true);
      return s;
    });

    wrapShort('atSheet', function (rand) {
      /* free: above y=290, and the right column beyond x=680 below y=1160 —
         the sheet (160,310) and the figure (80,1200) keep their ground */
      var s = this.wallClock(rand, 892, 150, 78);
      s += this.postIt(rand, 150, 96, 0.9, -7, false) + this.postIt(rand, 268, 108, 0.82, 8, true);
      s += this.shelfBinders(rand, 420, 84, 340, 112, 8);
      s += this.dyingPlant(rand, 968, 1560, 1.2);
      s += this.canEmpty(rand, 760, 1300, 0.9, false) + this.noodlePot(rand, 900, 1306, 0.86);
      s += this.crumple(rand, 800, 1700, 0.9) + this.crumple(rand, 960, 1790, 0.8);
      s += this.wasteBasket(rand, 720, 1860, 1.05);
      return s;
    });

    /* ── registry ────────────────────────────────────────────────────── */
    var SRC16 = { x: 0, y: 0, w: W, h: H }, CAN16 = [1920, 1080], DEL16 = [3840, 2160];
    function reg(key, o) { A[key + '--marker'] = o; }

    /* F · ten containers, all 16:9, all empty inside */
    [['series-line', 'seriesLine', 301], ['series-bar', 'seriesBar', 302], ['waterfall', 'waterfall', 303],
    ['split-bar', 'splitBar', 304], ['the-dollar', 'theDollar', 305], ['comps-table', 'compsTable', 306],
    ['rank-strip', 'rankStrip', 307], ['scatter', 'scatter', 308], ['big-fraction', 'bigFraction', 309],
    ['quote-pull', 'quotePull', 310]].forEach(function (t) {
      reg(t[0], {
        concept: t[0], group: 'F', src: SRC16, canvas: CAN16, deliver: DEL16, kw: 1.6, seed: t[2],
        draw: (function (fn) { return function (i, r) { return i[fn](r); }; })(t[1])
      });
    });

    /* E · the media carriers */
    reg('print-on-desk', {
      concept: 'print-on-desk', group: 'E', src: { x: 0, y: 0, w: 1400, h: 1080 },
      canvas: [1440, 1112], deliver: [2880, 2224], kw: 1.4, seed: 321,
      draw: function (i, r) { return i.printOnDesk(r); }
    });
    reg('pinned-item', {
      concept: 'pinned-item', group: 'E', src: { x: 0, y: 0, w: 1080, h: 1320 },
      canvas: [1080, 1320], deliver: [2160, 2640], kw: 1.2, seed: 322,
      draw: function (i, r) { return i.pinnedItem(r); }
    });
    reg('filing-on-screen', {
      concept: 'filing-on-screen', group: 'E', src: SRC16, canvas: CAN16, deliver: DEL16, kw: 1.6, seed: 323,
      draw: function (i, r) { return i.filingOnScreen(r); }
    });

    /* H3 · the frame-filling face */
    reg('cu-face', {
      concept: 'cu-face', group: 'H', src: SRC16, canvas: CAN16, deliver: DEL16, kw: 1.6, seed: 331,
      draw: function (i, r) { return i.cuFace(r); }
    });

    /* G · four poses × talk loop + idle loop + closed still */
    var HOSTSRC = { x: 280, y: 60, w: 720, h: 900 };
    [['at-the-whiteboard', 341], ['at-the-wall', 342], ['seated-talking', 343], ['crouching', 344]].forEach(function (p) {
      reg(p[0], {
        concept: p[0], group: 'G', src: HOSTSRC, canvas: [720, 900], deliver: [1440, 1800], kw: 1.167,
        seed: p[1], frames: 6, fps: 8, playback: 'loop',
        draw: function (i, r, f) { return i.pose(r, p[0], 'talk', f); },
        frameSeed: function (f) { return p[1] * 7919 + f * 331; }
      });
      reg(p[0] + '--idle', {
        concept: p[0] + '--idle', group: 'G', src: HOSTSRC, canvas: [720, 900], deliver: [1440, 1800], kw: 1.167,
        seed: p[1] + 40, frames: 8, fps: 7, playback: 'loop',
        draw: function (i, r, f) { return i.pose(r, p[0], 'idle', f); },
        frameSeed: function (f) { return (p[1] + 40) * 7919 + f * 331; }
      });
      reg(p[0] + '--closed', {
        concept: p[0] + '--closed', group: 'G', src: HOSTSRC, canvas: [720, 900], deliver: [1440, 1800], kw: 1.167,
        seed: p[1] + 80,
        draw: function (i, r) { return i.pose(r, p[0], 'still', 0); }
      });
    });

    /* G · eight faces */
    ['squinting', 'eyebrows-up-sceptical', 'looking-away-unconvinced', 'slow-blink',
      'rubbing-eyes', 'mouth-tight-annoyed', 'faint-almost-smile', 'staring-through-it'].forEach(function (v, n) {
        reg('face-' + v, {
          concept: 'face-' + v, group: 'G', src: { x: 340, y: 150, w: 320, h: 300 },
          canvas: [480, 460], deliver: [960, 920], kw: 1.0, seed: 361 + n,
          draw: function (i, r) { return i.hFace(r, v); }
        });
      });

    /* G · four gestures */
    [['arms-folded', 'arms-folded', 371], ['both-hands-open-weighing', 'weighing', 372],
    ['one-hand-rubbing-neck', 'rub-neck', 373], ['hand-flat-stop', 'hand-stop', 374]].forEach(function (g) {
      reg('gesture-' + g[0], {
        concept: 'gesture-' + g[0], group: 'G', src: HOSTSRC, canvas: [720, 900], deliver: [1440, 1800], kw: 1.167,
        seed: g[2],
        draw: function (i, r) {
          return i.hBody(r) + i.hArm(r, g[1]) + i.hHead(r) + i.hEyes(r, 0) + i.hMouth(r, 'closed');
        }
      });
    });

    /* the five ambient loops. Small, transparent, continuous. */
    [['loop-steam', 'loopSteam', 381, { x: 0, y: 0, w: 220, h: 300 }, [240, 320], 6, 8],
    ['loop-plant', 'loopPlant', 382, { x: 0, y: 0, w: 300, h: 400 }, [320, 420], 8, 6],
    ['loop-curtain', 'loopCurtain', 383, { x: 0, y: 0, w: 480, h: 740 }, [480, 740], 8, 6],
    ['loop-cursor', 'loopCursor', 384, { x: 0, y: 0, w: 60, h: 110 }, [80, 130], 4, 4],
    ['loop-second-hand', 'loopSecond', 385, { x: 0, y: 0, w: 300, h: 300 }, [320, 320], 8, 8]].forEach(function (l) {
      reg(l[0], {
        concept: l[0], group: 'AMB', src: l[3], canvas: l[4], deliver: [l[4][0] * 2, l[4][1] * 2], kw: 1.1,
        seed: l[2], frames: l[5], fps: l[6], playback: 'loop',
        draw: (function (fn, n) { return function (i, r, f) { return i[fn](r, f, n); }; })(l[1], l[5]),
        frameSeed: (function (sd) { return function (f) { return sd * 7919 + f * 331; }; })(l[2])
      });
    });

    /* clone the three other registers, then boil the whole registry */
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

    API.boilAll();
    global.dispatchEvent(new Event('dennis-ink-parts-ready'));
  }

  /* same watch as the long engine: re-register whenever the registry is new */
  var booted = null;
  function tryBoot() {
    var API = global.DennisInk;
    if (!API || !API.LONG) return;
    if (API !== booted) {
      if (API.ASSETS['seated-talking--idle--marker']) booted = API;
      else { booted = API; boot(); return; }
    }
    /* the two engines can re-register in either order after a reload, so any
       plate that arrived unboiled gets boiled here. boilAll skips the rest. */
    API.boilAll();
  }
  tryBoot();
  setInterval(tryBoot, 250);
})(typeof window !== 'undefined' ? window : globalThis);
