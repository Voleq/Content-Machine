/* Dennis v2 — plates-r1.js
 *
 * ROUND-ONE PLATE AUTHORS. Fifteen 9:16 shorts plates, each a beat the kit had
 * no answer for.
 *
 *   window.PLATES_R1.install(PLATES, HAND)   // adds the authors to PLATES
 *
 * WHY A SEPARATE FILE. `plates.js` is the 7,861-line legacy generator and the
 * whole rebuild rests on loading it untouched. Appending authors into it would
 * put new work inside the one file nobody wants to diff. So the authors live
 * here and are installed onto the same `PLATES` object — one registry, two
 * files, and the layout machinery (`base`, `TR`, `place`, `unitOf`) is IMPORTED
 * from plates.js rather than copied. A second copy of the type scale is how
 * two plates in one kit end up disagreeing about what a kicker is.
 *
 * EVERY PUBLISHED maxChars IS DERIVED FROM ITS BOX by `mc()` below, never
 * typed. The kit shipped 314 slots promising more characters than their own
 * geometry holds, and `maxChars` is a hard limit the compositor refuses a
 * render against — so a promise wider than the box is worse than no promise.
 * If a budget here is wrong it is wrong because the BOX is wrong, which is
 * visible.
 *
 * REGION SLOTS use only the roles the renderer knows — `plot-area`, `bars`,
 * `path`, plus the `band`/`marker`/`bar-N`/`point-N` shapes engine/series.js
 * already draws. Nothing here invents a region name. Where a plate needs a
 * mark area for a [SCRIBBLE:] composite, that is declared `overlay: true`,
 * which is not a data region and carries no words of its own.
 */

'use strict';

(function (g) {
  function install(P0, H) {
    const { base, TR, unitOf, blockH } = P0;

    /* The character budget a box can actually hold. Courier advances at
     * ~0.60em, Archivo Narrow at ~0.54em — the same constants the emitter
     * outlines type with. Two characters is the floor: a box that cannot hold
     * two cannot hold type, and an ellipsis in it reads as a defect. */
    const mc = (w, size, mono, lines) =>
      Math.max(2, Math.floor((w / (size * (mono ? 0.6 : 0.54))) * (lines || 1)));

    /* A role whose SIZE is derived from the box and the character count it
     * must hold: size = width / (chars x advance), capped at the preferred
     * size. This is the kit's own rule from plates.js bigNumber, and the two
     * plates here whose job is one number both got it wrong the first time. */
    const sized = (base0, w, chars, prefer) => {
      const adv = base0.font === 'Courier Prime' ? 0.5996 : 0.54;
      const size = Math.min(prefer, Math.floor(w / (chars * adv)));
      return Object.assign({}, base0, { size: size, maxChars: chars });
    };

    /* A role with its budget derived from the box it will sit in. */
    const role = (base0, size, w, lines) => {
      /* A WRAPPING ROLE MUST NOT BE GIVEN A maxChars. budget.js expresses a
       * wrapping budget as maxCharsPerLine x maxLines and a single-line one as
       * maxChars, and it fills whichever the role declares. Injecting maxChars
       * onto a role that wraps collapsed it to ONE line, so a three-line
       * headline budgeted 36 characters and a four-line hook card 23 — both
       * truncating sentences that fit the box comfortably. Leave the wrapping
       * roles alone and let budget.js do its job. */
      if ('maxCharsPerLine' in base0 || 'maxLines' in base0) {
        return Object.assign({}, base0, { size: size });
      }
      return Object.assign({}, base0, {
        size: size, maxChars: mc(w, size, base0.font === 'Courier Prime', lines),
      });
    };

    /* TIGHTEN — the post-pass that makes every published budget true.
     *
     * A type role is shared by several slots and a budget derived from the
     * role's nominal width is wrong for the narrowest box that uses it: the
     * first cut of this file published 21 characters for a 355px label column
     * that holds 16, which is exactly the defect the kit already had in 314
     * places. Because `maxChars` is a HARD limit the compositor refuses a
     * render against, an over-promise fails late and on somebody else's shift.
     *
     * So no author here computes a budget by hand. Every author ends with
     * `tighten(P)`, which walks the slots it actually declared and writes a
     * PER-SLOT budget of min(role intent, what this box holds) — using the
     * same 1.25 leading and the same 0.6/0.54 advances the compositor and
     * audit rule 23 use. A wide box keeps its generous budget; a narrow one
     * gets the truth. */
    function tighten(P) {
      const roles = (P.meta && P.meta.typeRoles) || {};
      Object.keys(P.slots).forEach(function (k) {
        const s = P.slots[k];
        if (s.overlay || s.container || s.region) return;
        const r = roles[s.role];
        if (!r || !r.size) return;
        const lines = s.wraps || Math.max(1, Math.floor(s.h / (r.size * 1.25)));
        const fits = Math.max(2, Math.floor((s.w / (r.size * (r.font === 'Courier Prime' ? 0.6 : 0.54))) * lines));
        s.maxChars = Math.min(r.maxChars || fits, fits);
        if (lines > 1) s.wraps = lines;
      });
      return P;
    }

    const R = {
      kicker: (w) => role(TR.kicker, 28, w),
      caption: (w) => role(TR.caption, 26, w),
      label: (w) => role(TR.label, 34, w),
      detail: (w, l) => role(TR.detail, 30, w, l),
      head: (w) => role(TR.statement, 62, w),
      big: (w) => role(TR.big, 200, w),
      figure: (w) => role(TR.figure, 58, w),
      mono: (w, s) => role(TR.figure, s || 40, w),
    };

    const band = (P, x, y, w, h, seed, op) =>
      P.colourAdd(H.hatch(H.polyRect(x, y, w, h),
        { color: P.pal.ground2, opacity: op == null ? 0.55 : op, gap: 8, width: 12, angle: -4, over: 14, seed: seed }));
    const rule = (P, x1, y, x2, seed, wt, op) =>
      P.inkAdd(H.line(x1, y, x2, y - 4, { stroke: P.pal.structure, width: wt || 3.2,
        opacity: op == null ? 0.55 : op, amp: 2.8, over: 10, seed: seed }));
    const tick = (P, x, y, len, colour, seed) =>
      P.colourAdd(H.stroke([{ x: x, y: y }, { x: x + len, y: y - 2 }],
        { stroke: colour, width: 9, amp: 2.2, over: 7, seed: seed }));

    /* ── news release ─────────────────────────────────────────────────────── */

    /* THE PLATE THE NEWS FORMAT WAS MISSING. One news beat existed — a headline
     * in a band — and a news short is about a DOCUMENT. This is the document:
     * masthead, dateline, headline, opening paragraph, and a reserved area over
     * one sentence for the mark. */
    P0.pressRelease = function (o) {
      const w = o.w, h = o.h, L = 96, Rr = w - 96, cw = Rr - L;
      const P = base(o, 'press-release', {
        source: role(TR.kicker, 30, cw * 0.6), date: role(TR.caption, 26, cw * 0.36),
        headline: R.head(cw), body: R.detail(cw, 3), caption: R.caption(cw),
      });
      P.meta.family = 'paper';
      /* The sheet, and a masthead rule under it — the two marks that say
       * "document" before a word is read. */
      band(P, L - 34, 250, cw + 68, 1180, 401, 0.32);
      P.inkAdd(H.outline(H.polyRect(L - 34, 250, cw + 68, 1180),
        { stroke: P.pal.structure, width: 3.4, opacity: 0.8, amp: 3, over: 12, seed: 402 }));
      P.slot('source', L, 306, cw * 0.6, blockH(P.meta.typeRoles.source, 1), { align: 'left', role: 'source' });
      P.slot('date', L + cw * 0.62, 310, cw * 0.38, blockH(P.meta.typeRoles.date, 1), { align: 'right', role: 'date' });
      rule(P, L, 380, Rr, 403, 4.4, 0.85);
      P.slot('headline', L, 430, cw, 330, { align: 'left', role: 'headline' });
      rule(P, L, 800, L + cw * 0.34, 404, 3, 0.5);
      P.slot('body', L, 850, cw, 330, { align: 'left', role: 'body' });
      /* Reserved for the mark. Not a data region and it carries no words: the
       * sentence it marks is in `body`, above it. */
      P.slot('mark-area', L - 16, 860, cw + 32, 130,
        { overlay: true, role: 'mark-area', note: 'a [SCRIBBLE:] composites here, over the first sentence of body' });
      P.slot('caption', L, 1470, cw, blockH(P.meta.typeRoles.caption, 1), { align: 'left', role: 'caption' });
      return tighten(P);
    };

    /* Wire headlines as a vertical ticker, oldest at top. Fills straight from a
     * feed of {time, headline, source} — which is why it is rows rather than a
     * hand-built stack. */
    P0.wireStrip = function (o) {
      const n = o.rows, w = o.w, h = o.h, L = 96, Rr = w - 96, cw = Rr - L;
      const roles = { kicker: R.kicker(cw), caption: R.caption(cw) };
      const top = 340, avail = 1360, rowH = Math.floor(avail / n);
      const headW = cw - 150;
      roles.time = role(TR.figure, 30, 130);
      roles.headline = role(TR.statement, n <= 3 ? 54 : 42, headW, 2);
      roles.source = role(TR.caption, 24, headW);
      const P = base(o, 'wire-strip-' + n, roles);
      P.meta.family = 'paper';
      P.meta.rows = n;
      P.slot('kicker', L, 260, cw, blockH(roles.kicker, 1), { align: 'left', role: 'kicker' });
      for (let i = 1; i <= n; i++) {
        const y = top + rowH * (i - 1);
        if (i % 2 === 0) band(P, L - 24, y - 12, cw + 48, rowH - 16, 410 + i, 0.4);
        P.slot('time-' + i, L, y + 6, 130, blockH(roles.time, 1), { align: 'left', role: 'time' });
        /* rebuild-22: the box is exactly two lines. It was the row height less
         * a margin, so tighten() published maxLines 3 while the source sat
         * under line two, and a three-line headline ran into it. */
        P.slot('headline-' + i, L + 150, y, headW, Math.ceil(roles.headline.size * 1.16 * 2) + 2, { align: 'left', role: 'headline', wraps: 2 });
        /* Under its headline. RECHECK rebuild-19: it was pinned to the foot of
         * the row, so at three rows a one-line headline sat 250px above its
         * own source and the source read as the next row's. */
        P.slot('source-' + i, L + 150, y + blockH(roles.headline, 2) + 14, headW, blockH(roles.source, 1),
          { align: 'left', role: 'source' });
        if (i < n) rule(P, L, y + rowH - 22, Rr, 420 + i, 2.2, 0.32);
      }
      /* The newest is the one being reported, so it is marked rather than
       * merely last: a ticker where every row is equal has no beat. */
      tick(P, L - 46, top + rowH * (n - 1) + 30, 34, P.pal.attention, 430);
      P.slot('caption', L, 1760, cw, blockH(roles.caption, 1), { align: 'left', role: 'caption' });
      return tighten(P);
    };

    /* Expected over announced, with the gap between them carried on the
     * divider. Two panels rather than two columns, because a phone reads
     * vertically and the SECOND panel is the news. */
    P0.beforeAfter = function (o) {
      const w = o.w, L = 96, Rr = w - 96, cw = Rr - L;
      const roles = { kicker: R.kicker(cw), label: R.kicker(cw * 0.7), caption: R.caption(cw) };
      roles.body = role(TR.statement, 52, cw, 3);
      roles.delta = role(TR.figure, 64, cw * 0.5);
      const P = base(o, 'before-after', roles);
      P.meta.family = 'structure';
      P.slot('kicker', L, 250, cw, blockH(roles.kicker, 1), { align: 'left', role: 'kicker' });
      const pH = 500, aY = 340, bY = aY + pH + 190;
      band(P, L - 30, aY, cw + 60, pH, 441, 0.3);
      P.slot('label-1', L, aY + 34, cw * 0.7, blockH(roles.label, 1), { align: 'left', role: 'label' });
      P.slot('body-1', L, aY + 110, cw, pH - 150, { align: 'left', role: 'body' });
      /* The divider is where the delta lives. A gap with a number in it is an
       * argument; a gap with nothing in it is a margin. */
      rule(P, L - 30, bY - 120, Rr + 30, 442, 6, 0.9);
      P.slot('delta', L, bY - 104, cw * 0.55, blockH(roles.delta, 1), { align: 'left', role: 'delta' });
      P.colourAdd(H.stroke([{ x: Rr - 60, y: bY - 150 }, { x: Rr - 60, y: bY - 60 }],
        { stroke: P.pal.attention, width: 11, amp: 2.4, over: 8, seed: 443 }));
      band(P, L - 30, bY, cw + 60, pH, 444, 0.5);
      P.inkAdd(H.outline(H.polyRect(L - 30, bY, cw + 60, pH),
        { stroke: P.pal.structure, width: 3.6, opacity: 0.85, amp: 3, over: 12, seed: 445 }));
      P.slot('label-2', L, bY + 34, cw * 0.7, blockH(roles.label, 1), { align: 'left', role: 'label' });
      P.slot('body-2', L, bY + 110, cw, pH - 150, { align: 'left', role: 'body' });
      P.slot('caption', L, 1760, cw, blockH(roles.caption, 1), { align: 'left', role: 'caption' });
      return tighten(P);
    };

    /* One number, a direction, and the session under it. The direction is a
     * SHAPE not a glyph — an arrow drawn as type is a font dependency. */
    P0.moveOnTheDay = function (o) {
      const w = o.w, L = 96, Rr = w - 96, cw = Rr - L;
      const roles = { kicker: R.kicker(cw), caption: R.caption(cw), label: R.label(cw) };
      /* THE SIZE COMES OFF THE BOX, not off a preference. plates.js says it
       * in bigNumber's own comment — "picking a size first and hoping is how
       * you get a 7-character value running off the plate" — and a 240pt
       * huge in a 698px column budgets FOUR characters, which cannot hold
       * "−18.4%" on the plate whose entire job is that number. */
      roles.huge = sized(TR.big, cw - 190, 7, 240);
      roles.unit = role(TR.caption, 30, cw);
      const P = base(o, o.direction === 'up' ? 'move-on-the-day-up' : 'move-on-the-day', roles);
      P.meta.family = 'figures';
      P.slot('kicker', L, 250, cw, blockH(roles.kicker, 1), { align: 'left', role: 'kicker' });
      const vy = 420;
      band(P, 0, vy + 40, w, 200, 451, 0.42);
      P.slot('value', L, vy, cw - 190, 280, { align: 'left', role: 'huge' });
      /* THE ARROW IS BAKED, SO ITS DIRECTION IS AN ARG. RECHECK rebuild-19: the
       * only variant pointed up, and the plate's own sample — and the move it
       * was built for — is −18.4%. A drawn direction cannot follow the data,
       * so there are two plates, -down and -up, and the caution says pick by sign.
       * A fall takes attention; a rise takes the up series ink. */
      const dn = o.direction !== 'up', sgn = dn ? -1 : 1, col = dn ? P.pal.attention : (P.pal.up || P.pal.structure);
      const ax = Rr - 130, ay = vy + 150;
      P.meta.direction = dn ? 'down' : 'up';
      P.colourAdd(H.stroke([{ x: ax, y: ay - 90 * sgn }, { x: ax, y: ay + 90 * sgn }],
        { stroke: col, width: 18, amp: 3, over: 10, seed: 452 }));
      P.colourAdd(H.stroke([{ x: ax - 54, y: ay + (dn ? 30 : -30) }, { x: ax, y: ay + (dn ? 96 : -96) }, { x: ax + 54, y: ay + (dn ? 30 : -30) }],
        { stroke: col, width: 18, amp: 3, over: 10, seed: 453 }));
      P.slot('label', L, vy + 320, cw, blockH(roles.label, 1), { align: 'left', role: 'label' });
      /* The session beneath, so the number has a shape behind it. */
      P.slot('unit', L, 900, cw, blockH(roles.unit, 1), { align: 'left', role: 'unit' });
      const pt = 960, pb = 1400;
      P.slot('plot-area', L, pt, cw, pb - pt, { role: 'plot-area', container: true, note: 'code draws the intraday path in here only' });
      for (let i = 1; i <= 6; i++) {
        const bx = L + (cw / 6) * (i - 1);
        P.slot('point-' + i, bx, pt, cw / 6, pb - pt,
          { role: 'point-column', container: true, anchorX: Math.round(bx + cw / 12) });
      }
      rule(P, L, pb, Rr, 454, 3.4, 0.6);
      P.slot('caption', L, 1760, cw, blockH(roles.caption, 1), { align: 'left', role: 'caption' });
      return tighten(P);
    };

    /* ── earnings ─────────────────────────────────────────────────────────── */

    /* Reported against expected as ONE paired figure with the beat in points.
     * Two big numbers side by side make the viewer do the subtraction, which on
     * a phone means they do not do it. */
    P0.printVsConsensus = function (o) {
      const w = o.w, L = 96, Rr = w - 96, cw = Rr - L;
      const roles = { kicker: R.kicker(cw), caption: R.caption(cw), label: R.label(cw) };
      roles.reported = sized(TR.big, cw, 7, 190);
      roles.expected = role(TR.figure, 70, cw * 0.55);
      roles.deltaLabel = role(TR.kicker, 26, cw * 0.4);
      /* Sized against the box it is DECLARED in (cw*0.32), not the one it was
       * first written against — sizing to a wider column than the slot is the
       * same error one level up. */
      roles.delta = sized(TR.figure, cw * 0.32, 7, 84);
      const P = base(o, 'print-vs-consensus', roles);
      P.meta.family = 'figures';
      P.slot('kicker', L, 250, cw, blockH(roles.kicker, 1), { align: 'left', role: 'kicker' });
      P.slot('label', L, 340, cw, blockH(roles.label, 1), { align: 'left', role: 'label' });
      band(P, 0, 430, w, 250, 461, 0.45);
      P.slot('reported', L, 440, cw, 230, { align: 'left', role: 'reported' });
      rule(P, L, 740, Rr, 462, 4, 0.7);
      P.slot('expected-label', L, 780, cw * 0.55, blockH(roles.deltaLabel, 1), { align: 'left', role: 'deltaLabel' });
      P.slot('expected', L, 830, cw * 0.55, blockH(roles.expected, 1), { align: 'left', role: 'expected' });
      /* The beat, set off to the right and marked — it is the only thing on the
       * plate the viewer cannot derive themselves. */
      P.colourAdd(H.stroke([{ x: L + cw * 0.62, y: 790 }, { x: L + cw * 0.62, y: 960 }],
        { stroke: P.pal.attention, width: 10, amp: 2.6, over: 8, seed: 463 }));
      P.slot('delta-label', L + cw * 0.68, 780, cw * 0.32, blockH(roles.deltaLabel, 1), { align: 'left', role: 'deltaLabel' });
      P.slot('delta', L + cw * 0.68, 824, cw * 0.32, blockH(roles.delta, 1), { align: 'left', role: 'delta' });
      rule(P, L, 1010, Rr, 464, 3, 0.4);
      P.slot('caption', L, 1720, cw, blockH(roles.caption, 2), { align: 'left', role: 'caption' });
      return tighten(P);
    };

    /* Eight quarters at phone proportions, the current one picked out. The
     * existing 8q bars are built for a long's width and at 9:16 the columns
     * come out narrower than their own labels. */
    P0.quarterBars = function (o) {
      const w = o.w, L = 96, Rr = w - 96, cw = Rr - L, n = 8;
      const colW = cw / n;
      const roles = { kicker: R.kicker(cw * 0.6), caption: R.caption(cw) };
      roles.unit = role(TR.caption, 28, cw * 0.38);
      roles.head = role(TR.caption, 24, colW);
      roles.value = role(TR.figure, 30, colW);
      const P = base(o, 'quarter-bars-8q', roles);
      P.meta.family = 'charts';
      P.meta.columns = n;
      P.slot('kicker', L, 250, cw * 0.6, blockH(roles.kicker, 1), { align: 'left', role: 'kicker' });
      P.slot('unit', L + cw * 0.62, 250, cw * 0.38, blockH(roles.unit, 1), { align: 'right', role: 'unit' });
      const pt = 420, pb = 1420;
      P.slot('plot-area', L, pt, cw, pb - pt, { role: 'plot-area', container: true, note: 'code draws the bars in here only' });
      /* Gridlines are furniture; the baseline is a measurement reference and is
       * pinned, because every bar's height is read from it. */
      [0.25, 0.5, 0.75].forEach((f, i) => rule(P, L, Math.round(pb - (pb - pt) * f), Rr, 470 + i, 1.8, 0.26));
      H.pin(function () {
        P.inkAdd(H.line(L - 12, pb, Rr + 12, pb - 3,
          { stroke: P.pal.structure, width: 5, opacity: 0.9, amp: 2.6, over: 12, seed: 474 }));
      });
      for (let i = 1; i <= n; i++) {
        const bx = L + colW * (i - 1);
        P.slot('bar-' + i, bx + colW * 0.14, pt, colW * 0.72, pb - pt,
          { role: 'point-column', container: true, anchorX: Math.round(bx + colW / 2) });
        P.slot('head-' + i, bx, pb + 24, colW, blockH(roles.head, 1), { align: 'center', role: 'head' });
        P.slot('value-' + i, bx, pb + 78, colW, blockH(roles.value, 1), { align: 'center', role: 'value' });
      }
      P.slot('caption', L, 1760, cw, blockH(roles.caption, 1), { align: 'left', role: 'caption' });
      return tighten(P);
    };

    /* Three metrics against the same quarter last year. The existing sheets are
     * six-period and unreadable at arm's length — three rows and three columns
     * is what a phone holds. */
    P0.threeLines = function (o) {
      const w = o.w, L = 96, Rr = w - 96, cw = Rr - L;
      const labW = cw * 0.40, colW = cw * 0.30;
      const roles = { kicker: R.kicker(cw), caption: R.caption(cw) };
      roles.head = role(TR.caption, 26, colW);
      roles.label = role(TR.label, 40, labW);
      roles.cell = role(TR.figure, 52, colW);
      roles.delta = role(TR.figure, 44, colW);
      const P = base(o, 'three-lines', roles);
      P.meta.family = 'tables';
      P.meta.rows = 3;
      P.slot('kicker', L, 250, cw, blockH(roles.kicker, 1), { align: 'left', role: 'kicker' });
      const top = 420, rowH = 280;
      P.slot('head-1', L + labW, top - 70, colW, blockH(roles.head, 1), { align: 'right', role: 'head' });
      P.slot('head-2', L + labW + colW, top - 70, colW, blockH(roles.head, 1), { align: 'right', role: 'head' });
      rule(P, L, top - 18, Rr, 481, 4.2, 0.85);
      for (let i = 1; i <= 3; i++) {
        const y = top + rowH * (i - 1);
        if (i % 2 === 0) band(P, L - 24, y, cw + 48, rowH - 16, 482 + i, 0.4);
        P.slot('label-' + i, L, y + 70, labW, blockH(roles.label, 1), { align: 'left', role: 'label' });
        P.slot('cell-' + i + '-1', L + labW, y + 58, colW, blockH(roles.cell, 1), { align: 'right', role: 'cell' });
        P.slot('cell-' + i + '-2', L + labW + colW, y + 58, colW, blockH(roles.cell, 1), { align: 'right', role: 'cell' });
        P.slot('delta-' + i, L + labW, y + 150, colW * 2, blockH(roles.delta, 1), { align: 'right', role: 'delta' });
        rule(P, L, y + rowH - 12, Rr, 490 + i, 2, 0.3);
      }
      P.slot('caption', L, 1700, cw, blockH(roles.caption, 2), { align: 'left', role: 'caption' });
      return tighten(P);
    };

    /* Old range and new range as two whiskers on one axis, direction called.
     * Uses `band` for the extent and `marker` for the new midpoint — the two
     * region shapes engine/series.js already draws, because a range is an
     * extent and drawing it as a bar from zero claims a baseline it lacks. */
    P0.guidanceRange = function (o) {
      const w = o.w, L = 96, Rr = w - 96, cw = Rr - L;
      const roles = { kicker: R.kicker(cw), caption: R.caption(cw), label: R.label(cw) };
      roles.axisTitle = role(TR.caption, 26, cw * 0.4);
      roles.head = role(TR.statement, 54, cw);
      roles.figure = role(TR.figure, 48, cw * 0.44);
      const P = base(o, 'guidance-raise-cut', roles);
      P.meta.family = 'figures';
      P.slot('kicker', L, 250, cw, blockH(roles.kicker, 1), { align: 'left', role: 'kicker' });
      P.slot('head', L, 330, cw, 190, { align: 'left', role: 'head' });
      const railY = 720, railH = 120;
      P.slot('row-axis', L, railY - 70, cw * 0.4, blockH(roles.axisTitle, 1), { align: 'left', role: 'axisTitle' });
      rule(P, L, railY + railH + 30, Rr, 501, 4, 0.8);
      /* The old range: an extent on the axis. */
      P.slot('band', L, railY, cw, railH, { role: 'band', region: true, axis: 'horizontal',
        note: 'the prior range as an extent — engine/series.js historyBand draws it from low/high' });
      /* The new midpoint: one position, marked. */
      P.slot('marker', L, railY - 26, cw, railH + 52, { role: 'marker', region: true, axis: 'horizontal',
        note: 'the new guide as one position — engine/series.js axisMark draws it, and reports a clamp' });
      P.slot('label-1', L, railY + railH + 54, cw * 0.44, blockH(roles.label, 1), { align: 'left', role: 'label' });
      P.slot('figure-1', L, railY + railH + 110, cw * 0.44, blockH(roles.figure, 1), { align: 'left', role: 'figure' });
      P.slot('label-2', L + cw * 0.56, railY + railH + 54, cw * 0.44, blockH(roles.label, 1), { align: 'right', role: 'label' });
      P.slot('figure-2', L + cw * 0.56, railY + railH + 110, cw * 0.44, blockH(roles.figure, 1), { align: 'right', role: 'figure' });
      P.slot('caption', L, 1720, cw, blockH(roles.caption, 2), { align: 'left', role: 'caption' });
      return tighten(P);
    };

    /* ── the move ─────────────────────────────────────────────────────────── */

    /* One session, open to close, with the event marked. The format currently
     * reaches for a multi-year line here, which answers a different question. */
    P0.intraday = function (o) {
      const w = o.w, L = 96, Rr = w - 96, cw = Rr - L, n = 7;
      const roles = { kicker: R.kicker(cw * 0.6), caption: R.caption(cw) };
      roles.unit = role(TR.caption, 28, cw * 0.38);
      roles.head = role(TR.caption, 24, cw / n);
      roles.eventLabel = role(TR.label, 32, cw * 0.5);
      roles.figure = role(TR.figure, 56, cw * 0.4);
      const P = base(o, 'intraday', roles);
      P.meta.family = 'charts';
      P.meta.columns = n;
      P.slot('kicker', L, 250, cw * 0.6, blockH(roles.kicker, 1), { align: 'left', role: 'kicker' });
      P.slot('unit', L + cw * 0.62, 250, cw * 0.38, blockH(roles.unit, 1), { align: 'right', role: 'unit' });
      P.slot('figure', L, 330, cw * 0.4, blockH(roles.figure, 1), { align: 'left', role: 'figure' });
      const pt = 520, pb = 1360;
      /* The prior close is the reference the whole session is read against, so
       * it is a pinned rule rather than a gridline. */
      H.pin(function () {
        P.inkAdd(H.line(L - 12, Math.round(pt + (pb - pt) * 0.62), Rr + 12, Math.round(pt + (pb - pt) * 0.62) - 3,
          { stroke: P.pal.structure, width: 4.4, opacity: 0.75, amp: 2.4, over: 12, seed: 511 }));
      });
      P.slot('plot-area', L, pt, cw, pb - pt, { role: 'plot-area', container: true, note: 'code draws the session path in here only' });
      for (let i = 1; i <= n; i++) {
        const bx = L + (cw / n) * (i - 1);
        P.slot('point-' + i, bx, pt, cw / n, pb - pt,
          { role: 'point-column', container: true, anchorX: Math.round(bx + cw / (n * 2)) });
        if (i % 2 === 1) P.slot('head-' + i, bx, pb + 22, cw / n, blockH(roles.head, 1), { align: 'center', role: 'head' });
      }
      /* The event marker is furniture the writer aims: a vertical at the third
       * column with room for a label beside it. */
      P.colourAdd(H.stroke([{ x: L + (cw / n) * 2.5, y: pt }, { x: L + (cw / n) * 2.5, y: pb }],
        { stroke: P.pal.attention, width: 7, amp: 2.2, over: 9, seed: 512 }));
      P.slot('event-label', L + (cw / n) * 2.5 + 26, pt + 30, cw * 0.5, blockH(roles.eventLabel, 2),
        { align: 'left', role: 'eventLabel' });
      P.slot('caption', L, 1700, cw, blockH(roles.caption, 2), { align: 'left', role: 'caption' });
      return tighten(P);
    };

    /* A vertical rail with the low, the high and where it sits now. Vertical
     * because the question is "how far up the range", and a horizontal rail
     * makes that a left-right judgement the viewer has to translate. */
    P0.fiftyTwoWeek = function (o) {
      const w = o.w, h = o.h, L = 96, Rr = w - 96, cw = Rr - L;
      const roles = { kicker: R.kicker(cw), caption: R.caption(cw) };
      roles.label = role(TR.label, 34, cw * 0.44);
      roles.figure = role(TR.figure, 54, cw * 0.44);
      roles.now = sized(TR.big, cw * 0.5, 8, 130);
      const P = base(o, '52-week-position', roles);
      P.meta.family = 'figures';
      P.slot('kicker', L, 250, cw, blockH(roles.kicker, 1), { align: 'left', role: 'kicker' });
      const railX = L + cw * 0.14, railW = 150, top = 420, bot = 1440;
      P.inkAdd(H.outline(H.polyRect(railX, top, railW, bot - top),
        { stroke: P.pal.structure, width: 3.4, opacity: 0.6, amp: 3, over: 12, seed: 521 }));
      /* The range as an extent, and the current price as one position on it. */
      P.slot('band', railX, top, railW, bot - top, { role: 'band', region: true, axis: 'vertical',
        note: 'the 52-week range as an extent — historyBand draws it from low/high' });
      P.slot('marker', railX - 30, top, railW + 60, bot - top, { role: 'marker', region: true, axis: 'vertical',
        note: 'where it sits now — axisMark draws it and reports a clamp if the price is outside the range' });
      const tx = railX + railW + 70, tw = cw - (railX - L) - railW - 70;
      P.slot('label-high', tx, top - 10, tw * 0.5, blockH(roles.label, 1), { align: 'left', role: 'label' });
      P.slot('figure-high', tx, top + 40, tw * 0.5, blockH(roles.figure, 1), { align: 'left', role: 'figure' });
      P.slot('label-now', tx, (top + bot) / 2 - 140, tw * 0.6, blockH(roles.label, 1), { align: 'left', role: 'label' });
      P.slot('now', tx, (top + bot) / 2 - 80, tw, blockH(roles.now, 1), { align: 'left', role: 'now' });
      P.slot('label-low', tx, bot - 90, tw * 0.5, blockH(roles.label, 1), { align: 'left', role: 'label' });
      P.slot('figure-low', tx, bot - 40, tw * 0.5, blockH(roles.figure, 1), { align: 'left', role: 'figure' });
      P.slot('caption', L, 1700, cw, blockH(roles.caption, 2), { align: 'left', role: 'caption' });
      return tighten(P);
    };

    /* ── furniture ────────────────────────────────────────────────────────── */

    /* Hook treatments four and five. Every short opens on one of three cards;
     * five halves how often two consecutive uploads open the same way, which
     * is the cheapest variety in the brief and a product requirement rather
     * than polish — the monetization policy is about low-variation output. */
    P0.hookCardT = function (o) {
      const t = o.treatment, w = o.w, h = o.h, L = 90, Rr = w - 90, cw = Rr - L;
      const roles = {
        ticker: role(TR.figure, 40, 240), move: role(TR.figure, 52, cw * 0.4),
        hook: role(TR.statement, t === 4 ? 96 : 84, cw, 4),
        huge: role(TR.big, 240, cw),
        sub: role(TR.detail, 36, cw, 2),
      };
      const P = base(o, 'hook-card-t' + t, roles);
      P.meta.family = 'shorts';
      P.meta.treatment = t;
      if (t === 4) {
        /* T4 — THE NUMBER FIRST. t1 and t2 lead with words and t3 with a
         * question; nothing led with the figure. The hook is what the number
         * means, under it. */
        band(P, 0, 380, w, 420, 531, 0.5);
        P.slot('huge', L, 400, cw, 380, { align: 'left', role: 'huge' });
        P.inkAdd(H.line(L - 10, 830, Rr, 824,
          { stroke: P.pal.structure, width: 9, opacity: 0.92, amp: 4, over: 16, seed: 532 }));
        P.slot('hook', L, 890, cw, 660, { align: 'left', role: 'hook' });
        P.slot('ticker', L, 250, 240, blockH(roles.ticker, 1), { align: 'left', role: 'ticker' });
        P.slot('move', L + 270, 250, cw * 0.4, blockH(roles.move, 1), { align: 'left', role: 'move' });
        P.slot('sub', L, 1620, cw, blockH(roles.sub, 2), { align: 'left', role: 'sub' });
      } else {
        /* T5 — THE STATEMENT ON A FULL FIELD, ticker at the foot. The other
         * four all put identifying furniture at the top, so the eye lands on a
         * chip first; here it lands on the sentence. */
        band(P, 0, 300, w, 1080, 541, 0.34);
        P.inkAdd(H.outline(H.polyRect(-40, 300, w + 80, 1080),
          { stroke: P.pal.structure, width: 4.2, opacity: 0.75, amp: 3.4, over: 14, seed: 542 }));
        P.slot('hook', L, 420, cw, 840, { align: 'left', role: 'hook' });
        P.colourAdd(H.stroke([{ x: L - 10, y: 1290 }, { x: L + cw * 0.34, y: 1286 }],
          { stroke: P.pal.attention, width: 12, amp: 2.6, over: 9, seed: 543 }));
        P.slot('sub', L, 1440, cw, blockH(roles.sub, 2), { align: 'left', role: 'sub' });
        P.slot('ticker', L, 1600, 240, blockH(roles.ticker, 1), { align: 'left', role: 'ticker' });
        P.slot('move', L + 270, 1600, cw * 0.4, blockH(roles.move, 1), { align: 'left', role: 'move' });
      }
      return tighten(P);
    };

    /* Closing treatments two and three. One drawing currently ends every short
     * in all three formats, which is the most repeated frame in the channel. */
    P0.closingT = function (o) {
      const t = o.treatment, w = o.w, h = o.h, L = 96, Rr = w - 96, cw = Rr - L;
      const roles = { kicker: R.kicker(cw), caption: R.caption(cw * 0.5) };
      roles.detail = role(TR.detail, t === 2 ? 44 : 38, cw - 100, 2);
      roles.figure = role(TR.figure, 48, cw * 0.5);
      roles.statement = role(TR.statement, 58, cw, 3);
      const P = base(o, 'closing-t' + t, roles);
      P.meta.family = 'structure';
      P.meta.treatment = t;
      P.slot('kicker', L, 280, cw, blockH(roles.kicker, 1), { align: 'left', role: 'kicker' });
      if (t === 2) {
        /* T2 — THE ONE THING. The original closes on three lines; a short
         * often has one, and three slots force two of them to be padding. */
        band(P, 0, 560, w, 460, 551, 0.45);
        P.slot('statement', L, 600, cw, 380, { align: 'left', role: 'statement' });
        P.inkAdd(H.line(L - 10, 1070, Rr * 0.72, 1064,
          { stroke: P.pal.structure, width: 8, opacity: 0.9, amp: 3.6, over: 14, seed: 552 }));
        P.slot('line-1', L, 1130, cw - 100, blockH(roles.detail, 2), { align: 'left', role: 'detail' });
        P.slot('date-label', L, 1560, cw * 0.5, blockH(roles.caption, 1), { align: 'left', role: 'caption' });
        P.slot('date', L + cw * 0.5, 1548, cw * 0.5, blockH(roles.figure, 1), { align: 'right', role: 'figure' });
      } else {
        /* T3 — THE CHECKLIST. Four short lines with marks, for the close that
         * lists what to watch rather than concluding. */
        const top = 480, lineH = 220;
        for (let i = 1; i <= 4; i++) {
          const y = top + lineH * (i - 1);
          if (i % 2 === 1) band(P, L - 24, y - 10, cw + 48, lineH - 30, 560 + i, 0.32);
          tick(P, L, y + 44, 44, P.pal.attention, 570 + i);
          P.slot('line-' + i, L + 74, y, cw - 100, blockH(roles.detail, 2), { align: 'left', role: 'detail' });
          if (i < 4) rule(P, L, y + lineH - 34, Rr, 580 + i, 2, 0.28);
        }
        P.slot('date-label', L, 1520, cw * 0.5, blockH(roles.caption, 1), { align: 'left', role: 'caption' });
        P.slot('date', L + cw * 0.5, 1508, cw * 0.5, blockH(roles.figure, 1), { align: 'right', role: 'figure' });
      }
      return tighten(P);
    };

    /* ══ LONG SIDE (16:9) ══════════════════════════════════════════════════
     *
     * Ordered by how thin the chapter type is today. `filing-walk` may name
     * four plates — the fewest of any type, for the chapter meant to be the
     * channel's differentiator — so it goes first.
     */

    /* filing-walk. A filing page with a reading window over one passage and
     * the rest legible but recessed. The point is that the document is REAL
     * and the camera is choosing where to look, which is the opposite of
     * pulling a quote out onto a card. */
    P0.filingPage = function (o) {
      const w = o.w, h = o.h, L = 150, Rr = w - 150, cw = Rr - L;
      const sheetW = Math.round(cw * 0.52), sx = L;
      const roles = {
        kicker: R.kicker(cw), caption: R.caption(cw),
        docref: role(TR.caption, 28, cw * 0.4),
        passage: role(TR.statement, 46, cw * 0.4, 5),
        note: R.detail(cw * 0.4, 3),
      };
      const P = base(o, 'filing-page', roles);
      P.meta.family = 'paper';
      P.slot('kicker', L, 110, cw * 0.55, blockH(roles.kicker, 1), { align: 'left', role: 'kicker' });
      P.slot('docref', Rr - cw * 0.4, 110, cw * 0.4, blockH(roles.docref, 1), { align: 'right', role: 'docref' });
      /* The page: a sheet with ruled body text drawn as furniture, because
       * nobody reads it — they read the window. Twenty-three lines of rule at
       * 0.22 opacity is a page; type would be a wall of words. */
      band(P, sx, 210, sheetW, h - 400, 701, 0.26);
      P.inkAdd(H.outline(H.polyRect(sx, 210, sheetW, h - 400),
        { stroke: P.pal.structure, width: 3.2, opacity: 0.7, amp: 3, over: 12, seed: 702 }));
      const winTop = 210 + Math.round((h - 400) * 0.42), winH = Math.round((h - 400) * 0.17);
      for (let i = 0; i < 23; i++) {
        const y = 250 + i * Math.round((h - 470) / 23);
        const inWin = y > winTop && y < winTop + winH;
        rule(P, sx + 34, y, sx + sheetW - (i % 5 === 4 ? 180 : 34), 710 + i, inWin ? 3.4 : 2, inWin ? 0.62 : 0.2);
      }
      /* The reading window: a field over the passage plus a marked left edge.
       * Recessing the rest is done by DRAWING the rest lighter, not by
       * dimming it — there is no opacity shading in this kit. */
      P.colourAdd(H.stroke([{ x: sx + 10, y: winTop }, { x: sx + 10, y: winTop + winH }],
        { stroke: P.pal.attention, width: 11, amp: 2.4, over: 9, seed: 703 }));
      const tx = sx + sheetW + 90;
      P.slot('passage', tx, winTop - 30, Rr - tx, 260, { align: 'left', role: 'passage' });
      P.slot('note', tx, winTop + 250, Rr - tx, 150, { align: 'left', role: 'note' });
      P.slot('caption', L, h - 130, cw, blockH(roles.caption, 1), { align: 'left', role: 'caption' });
      return tighten(P);
    };

    /* filing-walk. A footnote at display size with its parent line above it.
     * The parent line is the whole argument: a footnote alone is trivia, and a
     * footnote under the sentence it qualifies is the chapter. */
    P0.footnotePull = function (o) {
      const w = o.w, h = o.h, L = 200, Rr = w - 200, cw = Rr - L;
      const roles = {
        kicker: R.kicker(cw), caption: R.caption(cw),
        parent: role(TR.detail, 38, cw, 2),
        fnMarker: role(TR.figure, 40, 90),
        footnote: role(TR.statement, 54, cw - 120, 4),
        docref: role(TR.caption, 28, cw * 0.5),
      };
      const P = base(o, 'footnote-pull', roles);
      P.meta.family = 'paper';
      P.slot('kicker', L, 120, cw, blockH(roles.kicker, 1), { align: 'left', role: 'kicker' });
      /* The parent, set small and recessed — it is context, not the point. */
      P.slot('parent', L, 210, cw, blockH(roles.parent, 2), { align: 'left', role: 'parent' });
      rule(P, L, 360, Rr, 721, 4.4, 0.8);
      /* The footnote marker, at the size the eye goes to first. */
      band(P, 0, 430, w, h - 660, 722, 0.34);
      /* NOT role 'marker' — that name is reserved for a data region the
       * renderer draws into, and content.js correctly skips those. A type
       * slot borrowing the name renders nothing, silently. */
      P.slot('fn-marker', L, 470, 90, blockH(roles.fnMarker, 1), { align: 'left', role: 'fnMarker' });
      P.slot('footnote', L + 120, 460, cw - 120, 330, { align: 'left', role: 'footnote' });
      P.slot('docref', L, h - 200, cw * 0.5, blockH(roles.docref, 1), { align: 'left', role: 'docref' });
      P.slot('caption', L, h - 130, cw, blockH(roles.caption, 1), { align: 'left', role: 'caption' });
      return tighten(P);
    };

    /* filing-walk. The same filing paragraph from two years, with the changed
     * language marked. The most filing-walk-specific plate in the library and
     * nothing like it existed — languageShift is one column.
     *
     * Two columns of the SAME sentence is the only layout that makes a
     * deletion visible: a diff rendered as one column with strikethrough
     * reads as an edit, not as two filings. */
    P0.yearOnYearDiff = function (o) {
      const w = o.w, h = o.h, L = 150, Rr = w - 150, cw = Rr - L;
      const colW = Math.round((cw - 80) / 2);
      const roles = {
        kicker: R.kicker(cw), caption: R.caption(cw),
        year: role(TR.figure, 44, colW * 0.4),
        para: role(TR.detail, 34, colW, 7),
        verdict: role(TR.label, 36, cw * 0.7),
      };
      const P = base(o, 'year-on-year-diff', roles);
      P.meta.family = 'structure';
      P.slot('kicker', L, 110, cw, blockH(roles.kicker, 1), { align: 'left', role: 'kicker' });
      [0, 1].forEach(function (i) {
        const x = L + (colW + 80) * i;
        P.slot('year-' + (i + 1), x, 200, colW * 0.4, blockH(roles.year, 1), { align: 'left', role: 'year' });
        if (i === 1) band(P, x - 26, 190, colW + 52, h - 460, 731, 0.4);
        P.inkAdd(H.outline(H.polyRect(x - 26, 190, colW + 52, h - 460),
          { stroke: P.pal.structure, width: i ? 3.6 : 2.4, opacity: i ? 0.85 : 0.5, amp: 3, over: 12, seed: 732 + i }));
        P.slot('para-' + (i + 1), x, 300, colW, h - 590, { align: 'left', role: 'para' });
      });
      /* The mark belongs on what is new, so it sits on the SECOND column only,
       * under its year: "this is the version that changed".
       *
       * RECHECK rebuild-19: this was a margin bar from the first line to 300px
       * off the floor, at the paragraph's own x. It ran three times the height
       * of a real paragraph, read as a column rule rather than as a change, and
       * the first letter of every FY24 line sat on it. The plate cannot know
       * which words changed and the renderer can — so the column gets the mark
       * and the changed words get an overlay for a [SCRIBBLE:] composite. */
      const x2 = L + colW + 80;
      tick(P, x2, 200 + blockH(roles.year, 1) + 16, Math.round(colW * 0.14), P.pal.attention, 734);
      P.slot('mark-area', x2 - 14, 290, colW + 28, h - 570,
        { overlay: true, role: 'mark-area', note: 'a [SCRIBBLE:] composites here, over the changed words of para-2' });
      P.slot('verdict', L, h - 240, cw * 0.7, blockH(roles.verdict, 1), { align: 'left', role: 'verdict' });
      P.slot('caption', L, h - 130, cw, blockH(roles.caption, 1), { align: 'left', role: 'caption' });
      return tighten(P);
    };

    /* the-numbers. One sheet with a growth column and a margin column side by
     * side, the RATE columns formatted in points rather than percentages.
     * The data layer already knows which fields are rates and no plate
     * honoured the distinction — which is the difference between a checkable
     * number and a meaningless one. A margin moving 18.4% to 22.1% did not
     * grow 20%; it grew 3.7 points. */
    P0.growthAndMargin = function (o) {
      const w = o.w, h = o.h, L = 150, Rr = w - 150, cw = Rr - L, n = o.rows || 5;
      const labW = Math.round(cw * 0.30), colW = Math.round((cw - labW) / 4);
      const roles = {
        kicker: R.kicker(cw * 0.6), unit: role(TR.caption, 28, cw * 0.38),
        head: role(TR.caption, 26, colW), label: role(TR.label, 34, labW),
        cell: role(TR.figure, 38, colW), rate: role(TR.figure, 38, colW),
        caption: R.caption(cw),
      };
      const P = base(o, 'growth-and-margin', roles);
      P.meta.family = 'tables';
      P.meta.rows = n;
      P.slot('kicker', L, 110, cw * 0.6, blockH(roles.kicker, 1), { align: 'left', role: 'kicker' });
      P.slot('unit', Rr - cw * 0.38, 110, cw * 0.38, blockH(roles.unit, 1), { align: 'right', role: 'unit' });
      const top = 260, rowH = Math.floor((h - top - 190) / n);
      ['head-1', 'head-2', 'head-3', 'head-4'].forEach(function (k, i) {
        P.slot(k, L + labW + colW * i, top - 60, colW, blockH(roles.head, 1), { align: 'right', role: 'head' });
      });
      rule(P, L, top - 14, Rr, 741, 4.2, 0.85);
      /* As filed | derived. The rule sits between the two amount columns and
       * the two rate columns: a gap there reads as a missing column and the
       * reader looks for it.
       *
       * RECHECK rebuild-19: it was drawn 24px INSIDE the FY23 column, whose
       * figures are set flush right, so it cut the last glyph of every one of
       * them. The rates are flush right too, which leaves the left of their
       * column empty — that is where the rule has room. */
      const divX = L + labW + colW * 2 + 26;
      P.inkAdd(H.line(divX, top, divX - 4, top + rowH * n,
        { stroke: P.pal.structure, width: 2.6, opacity: 0.45, amp: 2.4, over: 9, seed: 742 }));
      for (let i = 1; i <= n; i++) {
        const y = top + rowH * (i - 1);
        if (i % 2 === 0) band(P, L - 24, y, cw + 48, rowH - 10, 750 + i, 0.38);
        P.slot('label-' + i, L, y + 20, labW, blockH(roles.label, 1), { align: 'left', role: 'label' });
        P.slot('cell-' + i + '-1', L + labW, y + 18, colW, blockH(roles.cell, 1), { align: 'right', role: 'cell' });
        P.slot('cell-' + i + '-2', L + labW + colW, y + 18, colW, blockH(roles.cell, 1), { align: 'right', role: 'cell' });
        P.slot('growth-' + i, L + labW + colW * 2, y + 18, colW, blockH(roles.rate, 1), { align: 'right', role: 'rate' });
        P.slot('margin-' + i, L + labW + colW * 3, y + 18, colW, blockH(roles.rate, 1), { align: 'right', role: 'rate' });
        if (i < n) rule(P, L, y + rowH - 6, Rr, 760 + i, 1.8, 0.26);
      }
      P.slot('caption', L, h - 130, cw, blockH(roles.caption, 1), { align: 'left', role: 'caption' });
      return tighten(P);
    };

    /* sector-comps. Four to six metrics, each a rail with the median marked
     * and the subject's position on it. Fills from a six-field structure the
     * export already carries and only one plate half-draws.
     *
     * A rail per metric rather than a table of percentiles, because "63rd
     * percentile" is a number you have to think about and a mark two-thirds
     * along a line is not. */
    P0.percentileRail = function (o) {
      const w = o.w, h = o.h, L = 150, Rr = w - 150, cw = Rr - L, n = o.rows || 5;
      const labW = Math.round(cw * 0.26), railW = cw - labW - 190;
      const roles = {
        kicker: R.kicker(cw * 0.6), unit: role(TR.caption, 28, cw * 0.38),
        label: role(TR.label, 34, labW), value: role(TR.figure, 38, 170),
        caption: R.caption(cw), axisTitle: role(TR.caption, 24, railW * 0.3),
      };
      const P = base(o, 'percentile-rail', roles);
      P.meta.family = 'tables';
      P.meta.rows = n;
      P.slot('kicker', L, 110, cw * 0.6, blockH(roles.kicker, 1), { align: 'left', role: 'kicker' });
      P.slot('unit', Rr - cw * 0.38, 110, cw * 0.38, blockH(roles.unit, 1), { align: 'right', role: 'unit' });
      const top = 280, rowH = Math.floor((h - top - 190) / n);
      P.slot('axis-low', L + labW, top - 56, railW * 0.3, blockH(roles.axisTitle, 1), { align: 'left', role: 'axisTitle' });
      P.slot('axis-high', L + labW + railW * 0.7, top - 56, railW * 0.3, blockH(roles.axisTitle, 1), { align: 'right', role: 'axisTitle' });
      for (let i = 1; i <= n; i++) {
        const y = top + rowH * (i - 1), ry = y + Math.round(rowH * 0.32), rh = Math.round(rowH * 0.3);
        P.slot('label-' + i, L, y + 12, labW, blockH(roles.label, 1), { align: 'left', role: 'label' });
        band(P, L + labW, ry, railW, rh, 770 + i, 0.44);
        P.inkAdd(H.outline(H.polyRect(L + labW, ry, railW, rh),
          { stroke: P.pal.structure, width: 2.4, opacity: 0.5, amp: 2.6, over: 10, seed: 780 + i }));
        /* The median tick is the plate's, at the midpoint, because a
         * percentile rail with no median is just a bar. The subject's mark is
         * the renderer's. */
        P.inkAdd(H.line(L + labW + railW / 2, ry - 12, L + labW + railW / 2, ry + rh + 12,
          { stroke: P.pal.structure, width: 3.4, opacity: 0.7, amp: 2, over: 8, seed: 790 + i }));
        P.slot('marker-' + i, L + labW, ry - 16, railW, rh + 32,
          { role: 'marker', region: true, axis: 'horizontal',
            note: 'the subject\'s position 0-1 — axisMark draws it and reports a clamp' });
        P.slot('value-' + i, Rr - 170, y + 12, 170, blockH(roles.value, 1), { align: 'right', role: 'value' });
      }
      P.slot('caption', L, h - 130, cw, blockH(roles.caption, 1), { align: 'left', role: 'caption' });
      return tighten(P);
    };

    /* cold-open. The chapter list as a contents card. Gives a long a roadmap
     * shot it has never had, and it is a retention shape as much as a design
     * one — a viewer who can see the end stays for the middle. */
    P0.whereThisGoes = function (o) {
      const w = o.w, h = o.h, L = 200, Rr = w - 200, cw = Rr - L, n = o.rows || 5;
      const roles = {
        kicker: R.kicker(cw), caption: R.caption(cw),
        num: role(TR.figure, 34, 70),
        item: role(TR.statement, 46, cw - 140),
      };
      const P = base(o, 'where-this-goes', roles);
      P.meta.family = 'structure';
      P.meta.rows = n;
      P.slot('kicker', L, 130, cw, blockH(roles.kicker, 1), { align: 'left', role: 'kicker' });
      rule(P, L, 220, Rr, 801, 4.4, 0.85);
      const top = 290, rowH = Math.floor((h - top - 190) / n);
      for (let i = 1; i <= n; i++) {
        const y = top + rowH * (i - 1);
        P.slot('num-' + i, L, y + 14, 70, blockH(roles.num, 1), { align: 'left', role: 'num' });
        P.slot('item-' + i, L + 140, y, cw - 140, blockH(roles.item, 1), { align: 'left', role: 'item' });
        if (i < n) rule(P, L + 140, y + rowH - 18, Rr, 810 + i, 1.8, 0.24);
      }
      P.slot('caption', L, h - 130, cw, blockH(roles.caption, 1), { align: 'left', role: 'caption' });
      return tighten(P);
    };

    /* how-we-got-here. Eight to twelve dated events on one rail. The existing
     * timeline is built for four or five and crowds past six.
     *
     * Events alternate above and below the rail so a dense run does not
     * collide — twelve labels on one side of a line is a paragraph. */
    P0.timelineDense = function (o) {
      const w = o.w, h = o.h, L = 120, Rr = w - 120, n = o.rows || 10;
      /* LABELS HANG RIGHT FROM THEIR TICKS.
       *
       * RECHECK rebuild-19: labels were set flush left inside boxes CENTRED on
       * their ticks, so no label started at its tick; the first box was then
       * clamped to the margin and its text ran into the third
       * ("…writtenRestatement"). A label now starts at its tick and may run to
       * just short of the next tick on the same side, and the rail stops one
       * label-width short of the frame so the last label fits:
       *   L + (n-1)·step + (2·step - gap) = Rr. */
      const gap = 44;
      const step = (Rr - L + gap) / (n + 1);
      const bw = Math.round(2 * step - gap), Rt = L + step * (n - 1);
      const cw = Rr - L;
      const roles = {
        kicker: R.kicker(cw), caption: R.caption(cw),
        date: role(TR.caption, 24, bw),
        event: role(TR.detail, 26, bw, 3),
      };
      const P = base(o, 'timeline-dense', roles);
      P.meta.family = 'structure';
      P.meta.rows = n;
      P.slot('kicker', L, 110, cw, blockH(roles.kicker, 1), { align: 'left', role: 'kicker' });
      const ry = Math.round(h * 0.52);
      H.pin(function () {
        P.inkAdd(H.line(L - 30, ry, Rt + 60, ry - 3,
          { stroke: P.pal.structure, width: 5.5, opacity: 0.9, amp: 2.6, over: 14, seed: 821 }));
      });
      for (let i = 1; i <= n; i++) {
        const x = L + step * (i - 1), up = i % 2 === 1;
        P.colourAdd(H.stroke([{ x: x, y: ry }, { x: x, y: ry + (up ? -34 : 34) }],
          { stroke: i === n ? P.pal.attention : P.pal.structure, width: i === n ? 9 : 5, amp: 2, over: 7, seed: 830 + i }));
        const bx = Math.round(x - 4);
        const by = up ? ry - 60 - 150 : ry + 60;
        P.slot('date-' + i, bx, up ? by + 106 : by, bw, blockH(roles.date, 1), { align: 'left', role: 'date' });
        P.slot('event-' + i, bx, up ? by : by + 40, bw, 100, { align: 'left', role: 'event' });
      }
      P.slot('caption', L, h - 120, cw, blockH(roles.caption, 1), { align: 'left', role: 'caption' });
      return tighten(P);
    };

    /* how-the-money-is-made. Four and five stage flows. One drawing carries
     * every unit-economics chapter today. A stage count is free variety and
     * the kit's own convention (waterfall-3s/4s/5s), so this is one author. */
    P0.flowN = function (o) {
      const w = o.w, h = o.h, n = o.stages, L = 120, Rr = w - 120, cw = Rr - L;
      const boxW = Math.round((cw - (n - 1) * 70) / n);
      const roles = {
        kicker: R.kicker(cw), caption: R.caption(cw),
        stage: role(TR.label, 32, boxW - 40, 2),
        figure: role(TR.figure, 42, boxW - 40),
        note: role(TR.caption, 24, boxW - 40, 2),
      };
      const P = base(o, 'flow-' + n, roles);
      P.meta.family = 'structure';
      P.meta.stages = n;
      P.slot('kicker', L, 120, cw, blockH(roles.kicker, 1), { align: 'left', role: 'kicker' });
      const by = Math.round(h * 0.34), bh = Math.round(h * 0.30);
      for (let i = 1; i <= n; i++) {
        const x = L + (boxW + 70) * (i - 1);
        band(P, x, by, boxW, bh, 840 + i, i === n ? 0.5 : 0.32);
        P.inkAdd(H.outline(H.polyRect(x, by, boxW, bh),
          { stroke: P.pal.structure, width: i === n ? 4 : 2.8, opacity: i === n ? 0.9 : 0.6, amp: 3, over: 12, seed: 850 + i }));
        P.slot('stage-' + i, x + 20, by + 26, boxW - 40, blockH(roles.stage, 2), { align: 'left', role: 'stage' });
        P.slot('figure-' + i, x + 20, by + bh - 130, boxW - 40, blockH(roles.figure, 1), { align: 'left', role: 'figure' });
        P.slot('note-' + i, x + 20, by + bh - 70, boxW - 40, blockH(roles.note, 2), { align: 'left', role: 'note' });
        /* The connector is a drawn wedge, not a glyph arrow. It also tells you
         * which way the money moves, which a gap does not. */
        if (i < n) {
          const ax = x + boxW + 14, ay = by + bh / 2;
          P.colourAdd(H.stroke([{ x: ax, y: ay }, { x: ax + 42, y: ay }],
            { stroke: P.pal.structure, width: 7, amp: 2, over: 7, seed: 860 + i }));
          P.colourAdd(H.stroke([{ x: ax + 24, y: ay - 16 }, { x: ax + 44, y: ay }, { x: ax + 24, y: ay + 16 }],
            { stroke: P.pal.structure, width: 7, amp: 2, over: 7, seed: 870 + i }));
        }
      }
      P.slot('caption', L, h - 130, cw, blockH(roles.caption, 1), { align: 'left', role: 'caption' });
      return tighten(P);
    };

    /* how-the-money-is-made. One unit: price, cost, contribution, margin —
     * and the last two are DERIVED ON THE PLATE, which is the point. A unit
     * economics chapter where the margin is typed is a chapter where nobody
     * can check the arithmetic. */
    P0.unitEconomics = function (o) {
      const w = o.w, h = o.h, L = 180, Rr = w - 180, cw = Rr - L;
      const colW = Math.round(cw * 0.46);
      const roles = {
        kicker: R.kicker(cw), caption: R.caption(cw),
        unitLabel: role(TR.label, 38, colW),
        line: role(TR.label, 34, colW * 0.62),
        amount: role(TR.figure, 40, colW * 0.34),
        big: sized(TR.big, cw * 0.44, 6, 170),
        bigLabel: role(TR.kicker, 28, cw * 0.44),
      };
      const P = base(o, 'unit-economics', roles);
      P.meta.family = 'figures';
      P.slot('kicker', L, 120, cw, blockH(roles.kicker, 1), { align: 'left', role: 'kicker' });
      P.slot('unit-label', L, 210, colW, blockH(roles.unitLabel, 1), { align: 'left', role: 'unitLabel' });
      const top = 310, rowH = 92;
      ['price', 'cost', 'contribution'].forEach(function (k, i) {
        const y = top + rowH * i;
        if (i === 2) rule(P, L, y - 16, L + colW, 881, 4.2, 0.85);
        P.slot(k + '-label', L, y, colW * 0.62, blockH(roles.line, 1), { align: 'left', role: 'line' });
        P.slot(k, L + colW * 0.64, y - 4, colW * 0.34, blockH(roles.amount, 1), { align: 'right', role: 'amount' });
      });
      /* The margin, derived, on its own field — the one number the chapter is
       * actually about. */
      band(P, Rr - cw * 0.46, top - 40, cw * 0.46, 300, 882, 0.46);
      P.slot('margin-label', Rr - cw * 0.44, top - 10, cw * 0.44, blockH(roles.bigLabel, 1), { align: 'left', role: 'bigLabel' });
      P.slot('margin', Rr - cw * 0.44, top + 50, cw * 0.44, 190, { align: 'left', role: 'big' });
      P.slot('caption', L, h - 130, cw, blockH(roles.caption, 1), { align: 'left', role: 'caption' });
      return tighten(P);
    };

    /* one-framework. Four to six criteria, each with a pass, a fail or a
     * partial mark. The mark is a SHAPE per verdict — a filled block, an
     * empty one, a half one — because a tick and a cross are font glyphs and
     * this kit outlines its type. */
    P0.scorecard = function (o) {
      const w = o.w, h = o.h, L = 180, Rr = w - 180, cw = Rr - L, n = o.rows || 5;
      /* RECHECK rebuild-19: the verdict was a tick in a 120px pill with nothing
       * to read it against — at video size "pass" and "fail" were a mark at one
       * end or the other of an unlabelled box. The rail is now wide enough to
       * hold three STATIONS, marked on every row and named once above the
       * first, the way percentile-rail names WORST and BEST. */
      const markW = 360, railW = markW - 40, inset = 30;
      const roles = {
        kicker: R.kicker(cw), caption: R.caption(cw),
        criterion: role(TR.label, 38, cw - markW - 60),
        /* THE VERDICT SITS UNDER THE CRITERION, not beside it. Beside it the
         * box was 300px — a nineteen-character budget for a sentence — and
         * every verdict truncated. A 19-character column is a bad box, and
         * shortening the copy to fit a bad box is fixing the wrong end. */
        verdict: role(TR.detail, 26, cw - markW - 60, 2),
        station: role(TR.caption, 22, 130),
      };
      const P = base(o, 'scorecard', roles);
      P.meta.family = 'structure';
      P.meta.rows = n;
      P.slot('kicker', L, 120, cw, blockH(roles.kicker, 1), { align: 'left', role: 'kicker' });
      rule(P, L, 210, Rr, 891, 4.2, 0.85);
      const top = 280, rowH = Math.floor((h - top - 190) / n);
      const mx = Rr - railW, sx = f => Math.round(mx + inset + f * (railW - 2 * inset));
      [0, 0.5, 1].forEach(function (f, j) {
        P.slot('station-' + (j + 1), sx(f) - 65, top - 40, 130, blockH(roles.station, 1), { align: 'center', role: 'station' });
      });
      for (let i = 1; i <= n; i++) {
        const y = top + rowH * (i - 1);
        if (i % 2 === 0) band(P, L - 26, y, cw + 52, rowH - 12, 900 + i, 0.36);
        P.slot('criterion-' + i, L, y + 12, cw - markW - 60, blockH(roles.criterion, 1), { align: 'left', role: 'criterion' });
        P.slot('verdict-' + i, L, y + 66, cw - markW - 60, blockH(roles.verdict, 2), { align: 'left', role: 'verdict' });
        const my = y + Math.round(rowH * 0.22), mh = Math.round(rowH * 0.34);
        P.inkAdd(H.outline(H.polyRect(mx, my, railW, mh),
          { stroke: P.pal.structure, width: 3.2, opacity: 0.8, amp: 2.8, over: 11, seed: 910 + i }));
        /* The stations are what the mark is read against, so they are pinned. */
        H.pin(function () {
          [0, 0.5, 1].forEach(function (f, j) {
            P.inkAdd(H.line(sx(f), my + 8, sx(f), my + mh - 8,
              { stroke: P.pal.structure, width: 2.4, opacity: 0.4, amp: 1.2, over: 4, seed: 960 + i * 3 + j }));
          });
        });
        P.slot('mark-' + i, mx + inset, my, railW - 2 * inset, mh,
          { role: 'marker', region: true, axis: 'horizontal',
            note: 'verdict on three stations: 0 fails, 0.5 partial, 1 holds — axisMark draws the mark' });
      }
      P.slot('caption', L, h - 130, cw, blockH(roles.caption, 1), { align: 'left', role: 'caption' });
      return tighten(P);
    };

    /* moat. Four named sources of advantage with a strength mark each. The
     * strength is a rail and not a star rating, because a rail can be read
     * against the others at a glance and five stars cannot. */
    P0.moatSources = function (o) {
      const w = o.w, h = o.h, L = 180, Rr = w - 180, cw = Rr - L, n = o.rows || 4;
      const railW = Math.round(cw * 0.34);
      const roles = {
        kicker: R.kicker(cw), caption: R.caption(cw),
        source: role(TR.label, 40, cw - railW - 120),
        detail: role(TR.detail, 28, cw - railW - 120, 2),
        strength: role(TR.caption, 24, railW),
      };
      const P = base(o, 'moat-sources-' + n, roles);
      P.meta.family = 'structure';
      P.meta.rows = n;
      P.slot('kicker', L, 120, cw, blockH(roles.kicker, 1), { align: 'left', role: 'kicker' });
      const top = 260, rowH = Math.floor((h - top - 190) / n);
      for (let i = 1; i <= n; i++) {
        const y = top + rowH * (i - 1);
        P.slot('source-' + i, L, y + 10, cw - railW - 120, blockH(roles.source, 1), { align: 'left', role: 'source' });
        P.slot('detail-' + i, L, y + 70, cw - railW - 120, blockH(roles.detail, 2), { align: 'left', role: 'detail' });
        const rx = Rr - railW, ry = y + 22, rh = 34;
        band(P, rx, ry, railW, rh, 920 + i, 0.42);
        P.inkAdd(H.outline(H.polyRect(rx, ry, railW, rh),
          { stroke: P.pal.structure, width: 2.4, opacity: 0.5, amp: 2.4, over: 10, seed: 930 + i }));
        P.slot('strength-' + i, rx, ry, railW, rh,
          { role: 'marker', region: true, axis: 'horizontal',
            note: 'strength 0-1 — axisMark draws the mark on a shared scale across the rows' });
        P.slot('strength-label-' + i, rx, ry + 48, railW, blockH(roles.strength, 1), { align: 'left', role: 'strength' });
        if (i < n) rule(P, L, y + rowH - 16, Rr, 940 + i, 1.8, 0.24);
      }
      P.slot('caption', L, h - 130, cw, blockH(roles.caption, 1), { align: 'left', role: 'caption' });
      return tighten(P);
    };

    /* sector-comps. Growth against multiple, subject picked out. The one
     * comps shape nothing in the kit draws — a strip ranks on one axis and
     * cannot show that the expensive name is also the fast one. */
    P0.peerScatter = function (o) {
      const w = o.w, h = o.h, L = 200, Rr = w - 200, cw = Rr - L, n = o.points || 8;
      const roles = {
        kicker: R.kicker(cw * 0.6), unit: role(TR.caption, 28, cw * 0.38),
        xAxis: role(TR.caption, 26, cw * 0.4), yAxis: role(TR.caption, 26, 300),
        ticker: role(TR.figure, 26, 120), caption: R.caption(cw),
      };
      const P = base(o, 'peer-scatter', roles);
      P.meta.family = 'peers';
      P.meta.points = n;
      P.slot('kicker', L, 110, cw * 0.6, blockH(roles.kicker, 1), { align: 'left', role: 'kicker' });
      P.slot('unit', Rr - cw * 0.38, 110, cw * 0.38, blockH(roles.unit, 1), { align: 'right', role: 'unit' });
      const pt = 250, pb = h - 250;
      [0.25, 0.5, 0.75].forEach(function (f, i) {
        rule(P, L, Math.round(pb - (pb - pt) * f), Rr, 950 + i, 1.8, 0.22);
        P.inkAdd(H.line(L + cw * f, pt, L + cw * f - 3, pb, { stroke: P.pal.structure, width: 1.8, opacity: 0.22, amp: 2.2, over: 8, seed: 960 + i }));
      });
      H.pin(function () {
        P.inkAdd(H.line(L - 14, pb, Rr + 14, pb - 3, { stroke: P.pal.structure, width: 5, opacity: 0.9, amp: 2.6, over: 13, seed: 963 }));
        P.inkAdd(H.line(L, pt - 14, L - 3, pb + 14, { stroke: P.pal.structure, width: 5, opacity: 0.9, amp: 2.6, over: 13, seed: 964 }));
      });
      P.slot('plot-area', L, pt, cw, pb - pt,
        { role: 'plot-area', container: true, note: 'code draws one mark per peer in here only; the subject is the accent' });
      for (let i = 1; i <= n; i++) {
        P.slot('ticker-' + i, L, pt, 120, blockH(roles.ticker, 1),
          { overlay: true, role: 'ticker', note: 'positioned by the renderer beside its own mark' });
      }
      P.slot('x-axis', L, pb + 30, cw * 0.4, blockH(roles.xAxis, 1), { align: 'left', role: 'xAxis' });
      P.slot('y-axis', L, pt - 60, 300, blockH(roles.yAxis, 1), { align: 'left', role: 'yAxis' });
      P.slot('caption', L, h - 130, cw, blockH(roles.caption, 1), { align: 'left', role: 'caption' });
      return tighten(P);
    };

    /* capital-allocation. Operating cash flow split across capex, buybacks,
     * dividends and debt. One bar and its parts, not a pie: the question is
     * "how much of it", and a pie makes that an angle. */
    P0.whereTheCashWent = function (o) {
      const w = o.w, h = o.h, L = 180, Rr = w - 180, cw = Rr - L, n = o.parts || 4;
      const roles = {
        kicker: R.kicker(cw), caption: R.caption(cw),
        total: sized(TR.big, cw * 0.4, 7, 150), totalLabel: role(TR.kicker, 28, cw * 0.4),
        part: role(TR.label, 32, Math.round(cw / n) - 30),
        amount: role(TR.figure, 38, Math.round(cw / n) - 30),
        share: role(TR.caption, 24, Math.round(cw / n) - 30),
      };
      const P = base(o, 'where-the-cash-went', roles);
      P.meta.family = 'figures';
      P.meta.parts = n;
      P.slot('kicker', L, 120, cw, blockH(roles.kicker, 1), { align: 'left', role: 'kicker' });
      P.slot('total-label', L, 210, cw * 0.4, blockH(roles.totalLabel, 1), { align: 'left', role: 'totalLabel' });
      P.slot('total', L, 260, cw * 0.4, 170, { align: 'left', role: 'total' });
      const by = Math.round(h * 0.52), bh = 120;
      P.inkAdd(H.outline(H.polyRect(L, by, cw, bh),
        { stroke: P.pal.structure, width: 3.6, opacity: 0.85, amp: 3, over: 12, seed: 971 }));
      /* One bar, split by the renderer. The plate declares the bar and the
       * label columns; how it divides is data. */
      P.slot('bars', L, by, cw, bh,
        { role: 'bars', region: true, note: 'the split — series.splitBar draws the parts end to end, in the order the label columns read, on one scale' });
      const colW = Math.round(cw / n);
      for (let i = 1; i <= n; i++) {
        const x = L + colW * (i - 1);
        P.slot('band-' + i, x, by, colW, bh, { role: 'point-column', container: true, anchorX: Math.round(x + colW / 2) });
        P.slot('part-' + i, x, by + bh + 30, colW - 30, blockH(roles.part, 1), { align: 'left', role: 'part' });
        P.slot('amount-' + i, x, by + bh + 86, colW - 30, blockH(roles.amount, 1), { align: 'left', role: 'amount' });
        P.slot('share-' + i, x, by + bh + 140, colW - 30, blockH(roles.share, 1), { align: 'left', role: 'share' });
      }
      P.slot('caption', L, h - 120, cw, blockH(roles.caption, 1), { align: 'left', role: 'caption' });
      return tighten(P);
    };

    /* capital-allocation. The two rates on one axis with the spread called.
     * Two marks on ONE axis, because the whole claim is the gap between them
     * and two separate gauges make the reader hold two numbers instead. */
    P0.roicVsWacc = function (o) {
      const w = o.w, h = o.h, L = 200, Rr = w - 200, cw = Rr - L;
      const roles = {
        kicker: R.kicker(cw), caption: R.caption(cw),
        label: role(TR.label, 36, cw * 0.4), figure: role(TR.figure, 54, cw * 0.28),
        spread: sized(TR.big, cw * 0.34, 6, 150), spreadLabel: role(TR.kicker, 28, cw * 0.34),
        axisTitle: role(TR.caption, 24, cw * 0.3),
      };
      const P = base(o, 'roic-vs-wacc', roles);
      P.meta.family = 'figures';
      P.slot('kicker', L, 120, cw, blockH(roles.kicker, 1), { align: 'left', role: 'kicker' });
      const railY = Math.round(h * 0.42), railH = 130;
      P.slot('axis-low', L, railY - 56, cw * 0.3, blockH(roles.axisTitle, 1), { align: 'left', role: 'axisTitle' });
      P.slot('axis-high', Rr - cw * 0.3, railY - 56, cw * 0.3, blockH(roles.axisTitle, 1), { align: 'right', role: 'axisTitle' });
      band(P, L, railY, cw, railH, 981, 0.34);
      P.inkAdd(H.outline(H.polyRect(L, railY, cw, railH),
        { stroke: P.pal.structure, width: 3.2, opacity: 0.7, amp: 3, over: 12, seed: 982 }));
      /* The spread as an extent between the two marks, then each mark. Order
       * matters: the band goes under. */
      P.slot('band', L, railY, cw, railH,
        { role: 'band', region: true, axis: 'horizontal', note: 'the spread as an extent from wacc to roic — historyBand' });
      P.slot('marker', L, railY - 24, cw, railH + 48,
        { role: 'marker', region: true, axis: 'horizontal', note: 'roic as one position — axisMark' });
      [['wacc', 0], ['roic', 1]].forEach(function (pair, i) {
        const x = i ? Rr - cw * 0.28 : L;
        P.slot(pair[0] + '-label', x, railY + railH + 40, cw * 0.28, blockH(roles.label, 1), { align: i ? 'right' : 'left', role: 'label' });
        P.slot(pair[0], x, railY + railH + 100, cw * 0.28, blockH(roles.figure, 1), { align: i ? 'right' : 'left', role: 'figure' });
      });
      P.slot('spread-label', L + cw * 0.34, railY + railH + 40, cw * 0.34, blockH(roles.spreadLabel, 1), { align: 'center', role: 'spreadLabel' });
      P.slot('spread', L + cw * 0.34, railY + railH + 90, cw * 0.34, 160, { align: 'center', role: 'spread' });
      P.slot('caption', L, h - 120, cw, blockH(roles.caption, 1), { align: 'left', role: 'caption' });
      return tighten(P);
    };

    /* guidance-estimates. How the estimate moved across four to six dates.
     * A trail, not a line chart: the dates are irregular and the point is
     * that it moved AFTER each event, which an evenly spaced axis hides. */
    P0.revisionTrail = function (o) {
      const w = o.w, h = o.h, L = 160, Rr = w - 160, cw = Rr - L, n = o.rows || 5;
      const step = cw / n;
      const roles = {
        kicker: R.kicker(cw), caption: R.caption(cw),
        date: role(TR.caption, 24, step - 20), est: role(TR.figure, 40, step - 20),
        move: role(TR.caption, 24, step - 20), note: role(TR.detail, 26, cw * 0.6, 2),
      };
      const P = base(o, 'revision-trail', roles);
      P.meta.family = 'structure';
      P.meta.rows = n;
      P.slot('kicker', L, 120, cw, blockH(roles.kicker, 1), { align: 'left', role: 'kicker' });
      const pt = 280, pb = Math.round(h * 0.64);
      P.slot('plot-area', L, pt, cw, pb - pt,
        { role: 'plot-area', container: true, note: 'code draws the revision path in here only' });
      rule(P, L, pb, Rr, 991, 4.4, 0.8);
      for (let i = 1; i <= n; i++) {
        const x = L + step * (i - 1);
        P.slot('point-' + i, x, pt, step, pb - pt, { role: 'point-column', container: true, anchorX: Math.round(x + step / 2) });
        /* Centred under the point. RECHECK rebuild-19: these were flush left in
         * the column while the point sits at its centre, so every date read as
         * belonging halfway to the previous point. */
        P.slot('date-' + i, x + 10, pb + 26, step - 20, blockH(roles.date, 1), { align: 'center', role: 'date' });
        P.slot('est-' + i, x + 10, pb + 66, step - 20, blockH(roles.est, 1), { align: 'center', role: 'est' });
        P.slot('move-' + i, x + 10, pb + 122, step - 20, blockH(roles.move, 1), { align: 'center', role: 'move' });
      }
      P.slot('note', L, h - 200, cw * 0.6, blockH(roles.note, 2), { align: 'left', role: 'note' });
      P.slot('caption', L, h - 120, cw, blockH(roles.caption, 1), { align: 'left', role: 'caption' });
      return tighten(P);
    };

    /* valuation. Bear, base and bull as three endpoints from one starting
     * price. A fan and not three numbers, because the shape carries the
     * asymmetry — whether the upside is bigger than the downside is the
     * thing you are supposed to see without arithmetic. */
    P0.scenarioFan = function (o) {
      const w = o.w, h = o.h, L = 180, Rr = w - 180, cw = Rr - L;
      const roles = {
        kicker: R.kicker(cw), caption: R.caption(cw),
        start: role(TR.figure, 44, 240), startLabel: role(TR.caption, 24, 240),
        scenario: role(TR.label, 34, 300), price: role(TR.figure, 48, 300),
        move: role(TR.caption, 26, 300),
      };
      const P = base(o, 'scenario-fan', roles);
      P.meta.family = 'figures';
      P.slot('kicker', L, 120, cw, blockH(roles.kicker, 1), { align: 'left', role: 'kicker' });
      /* RECHECK rebuild-19: the origin sat 60px in from the margin and the
       * starting price was set from the margin, so the price was printed across
       * the first 80px of the fan. The price now ends 30px short of the origin,
       * set flush right against it, so it reads as the origin's label. */
      const ox = L + 250, oy = Math.round(h * 0.5);
      const tipX = Rr - 340;
      /* The three rays are furniture at fixed spread; the ENDPOINTS carry the
       * numbers, so a writer cannot accidentally imply a path. */
      P.colourAdd(H.stroke([{ x: ox, y: oy }, { x: ox + 26, y: oy }], { stroke: P.pal.structure, width: 8, amp: 2, over: 7, seed: 1001 }));
      [[-1, 'bull'], [0, 'base'], [1, 'bear']].forEach(function (pair, i) {
        const dy = pair[0] * Math.round((h * 0.22));
        P.colourAdd(H.stroke([{ x: ox + 30, y: oy }, { x: tipX, y: oy + dy }],
          { stroke: i === 1 ? P.pal.structure : (i === 2 ? P.pal.attention : P.pal.up || P.pal.structure),
            width: i === 1 ? 7 : 5, amp: 2.4, over: 9, seed: 1010 + i }));
        const ey = oy + dy;
        P.slot(pair[1] + '-label', tipX + 30, ey - 58, 300, blockH(roles.scenario, 1), { align: 'left', role: 'scenario' });
        P.slot(pair[1] + '-price', tipX + 30, ey - 12, 300, blockH(roles.price, 1), { align: 'left', role: 'price' });
        P.slot(pair[1] + '-move', tipX + 30, ey + 44, 300, blockH(roles.move, 1), { align: 'left', role: 'move' });
      });
      P.slot('start-label', L - 20, oy - 70, 240, blockH(roles.startLabel, 1), { align: 'right', role: 'startLabel' });
      P.slot('start', L - 20, oy - 26, 240, blockH(roles.start, 1), { align: 'right', role: 'start' });
      P.slot('caption', L, h - 120, cw, blockH(roles.caption, 1), { align: 'left', role: 'caption' });
      return tighten(P);
    };

    /* risk. Four risks, each with a likelihood and a severity mark. Two marks
     * per row rather than one composite score: a rare catastrophe and a
     * frequent nuisance can score the same and are not the same risk. */
    P0.riskRegister = function (o) {
      const w = o.w, h = o.h, L = 160, Rr = w - 160, cw = Rr - L, n = o.rows || 4;
      const railW = Math.round(cw * 0.17);
      const roles = {
        kicker: R.kicker(cw), caption: R.caption(cw),
        risk: role(TR.label, 36, cw - railW * 2 - 160),
        detail: role(TR.detail, 26, cw - railW * 2 - 160, 2),
        head: role(TR.caption, 24, railW),
      };
      const P = base(o, 'risk-register-' + n, roles);
      P.meta.family = 'structure';
      P.meta.rows = n;
      P.slot('kicker', L, 120, cw, blockH(roles.kicker, 1), { align: 'left', role: 'kicker' });
      const lx = Rr - railW * 2 - 60, sx = Rr - railW;
      P.slot('head-likelihood', lx, 220, railW, blockH(roles.head, 1), { align: 'left', role: 'head' });
      P.slot('head-severity', sx, 220, railW, blockH(roles.head, 1), { align: 'left', role: 'head' });
      rule(P, L, 276, Rr, 1021, 4.2, 0.85);
      const top = 330, rowH = Math.floor((h - top - 190) / n);
      for (let i = 1; i <= n; i++) {
        const y = top + rowH * (i - 1);
        if (i % 2 === 0) band(P, L - 24, y, cw + 48, rowH - 14, 1030 + i, 0.36);
        P.slot('risk-' + i, L, y + 10, cw - railW * 2 - 160, blockH(roles.risk, 1), { align: 'left', role: 'risk' });
        P.slot('detail-' + i, L, y + 66, cw - railW * 2 - 160, blockH(roles.detail, 2), { align: 'left', role: 'detail' });
        [[lx, 'likelihood'], [sx, 'severity']].forEach(function (pair, k) {
          const rx = pair[0], ry = y + 20, rh = 30;
          band(P, rx, ry, railW, rh, 1040 + i * 2 + k, 0.42);
          P.inkAdd(H.outline(H.polyRect(rx, ry, railW, rh),
            { stroke: P.pal.structure, width: 2.2, opacity: 0.5, amp: 2.4, over: 9, seed: 1050 + i * 2 + k }));
          P.slot(pair[1] + '-' + i, rx, ry, railW, rh,
            { role: 'marker', region: true, axis: 'horizontal',
              note: pair[1] + ' 0-1 on a scale shared across the rows — axisMark' });
        });
      }
      P.slot('caption', L, h - 120, cw, blockH(roles.caption, 1), { align: 'left', role: 'caption' });
      return tighten(P);
    };

    /* bull-vs-bear. The shared facts on top, the divergence beneath — the
     * chapter's honest shape. Two ledgers side by side imply the cases
     * disagree about everything, and they almost never do: they agree on the
     * numbers and differ on what the numbers mean. */
    P0.whereTheyAgree = function (o) {
      const w = o.w, h = o.h, L = 160, Rr = w - 160, cw = Rr - L, n = o.rows || 3;
      const colW = Math.round((cw - 90) / 2);
      const roles = {
        kicker: R.kicker(cw), caption: R.caption(cw),
        agreed: role(TR.label, 34, cw - 80),
        sideLabel: role(TR.kicker, 28, colW),
        side: role(TR.detail, 30, colW, 4),
      };
      const P = base(o, 'where-they-agree', roles);
      P.meta.family = 'structure';
      P.meta.rows = n;
      P.slot('kicker', L, 110, cw, blockH(roles.kicker, 1), { align: 'left', role: 'kicker' });
      /* The agreed facts on a field, because they are the ground the argument
       * stands on and the plate should look like that. */
      const aTop = 200, aH = 90 + n * 64;
      band(P, L - 30, aTop, cw + 60, aH, 1061, 0.44);
      P.inkAdd(H.outline(H.polyRect(L - 30, aTop, cw + 60, aH),
        { stroke: P.pal.structure, width: 3.6, opacity: 0.85, amp: 3, over: 12, seed: 1062 }));
      P.slot('agreed-label', L, aTop + 24, cw * 0.5, blockH(roles.sideLabel, 1), { align: 'left', role: 'sideLabel' });
      for (let i = 1; i <= n; i++) {
        P.slot('agreed-' + i, L + 40, aTop + 80 + 64 * (i - 1), cw - 80, blockH(roles.agreed, 1), { align: 'left', role: 'agreed' });
        P.colourAdd(H.stroke([{ x: L + 4, y: aTop + 100 + 64 * (i - 1) }, { x: L + 26, y: aTop + 98 + 64 * (i - 1) }],
          { stroke: P.pal.structure, width: 6, amp: 2, over: 6, seed: 1070 + i }));
      }
      /* Then the split. The rule between is the divergence itself. */
      const dTop = aTop + aH + 90;
      P.inkAdd(H.line(L + colW + 45, dTop - 30, L + colW + 41, h - 190,
        { stroke: P.pal.structure, width: 4.4, opacity: 0.8, amp: 3, over: 12, seed: 1081 }));
      [['bull', 0], ['bear', 1]].forEach(function (pair, i) {
        const x = L + (colW + 90) * i;
        P.slot(pair[0] + '-label', x, dTop - 60, colW, blockH(roles.sideLabel, 1), { align: 'left', role: 'sideLabel' });
        P.slot(pair[0], x, dTop, colW, h - dTop - 200, { align: 'left', role: 'side' });
      });
      P.slot('caption', L, h - 120, cw, blockH(roles.caption, 1), { align: 'left', role: 'caption' });
      return tighten(P);
    };

    /* capital-allocation, REDRAWN on the operator's verdict (ANSWERS.md §5).
     *
     * The proposal was buyback-vs-price. Shares repurchased and the price
     * paid are not real columns, and deriving shares retired from the change
     * in diluted count is wrong for anything with meaningful stock comp —
     * which is most of the companies where the question is interesting. So
     * this is buyback DOLLARS per year with the SHARE-COUNT CHANGE beneath
     * them. Both are real columns, and the pair still answers the question:
     * money out, and whether the count actually fell. */
    P0.buybackDollars = function (o) {
      const w = o.w, h = o.h, L = 160, Rr = w - 160, cw = Rr - L, n = o.years || 6;
      const colW = cw / n;
      const roles = {
        kicker: R.kicker(cw * 0.6), unit: role(TR.caption, 28, cw * 0.38),
        head: role(TR.caption, 24, colW), spend: role(TR.figure, 32, colW),
        count: role(TR.figure, 30, colW), countLabel: role(TR.caption, 24, cw * 0.4),
        caption: R.caption(cw),
      };
      const P = base(o, 'buyback-dollars', roles);
      P.meta.family = 'charts';
      P.meta.columns = n;
      P.slot('kicker', L, 110, cw * 0.6, blockH(roles.kicker, 1), { align: 'left', role: 'kicker' });
      P.slot('unit', Rr - cw * 0.38, 110, cw * 0.38, blockH(roles.unit, 1), { align: 'right', role: 'unit' });
      const pt = 250, pb = Math.round(h * 0.58);
      P.slot('plot-area', L, pt, cw, pb - pt, { role: 'plot-area', container: true, note: 'code draws the spend bars in here only' });
      [0.33, 0.66].forEach(function (f, i) { rule(P, L, Math.round(pb - (pb - pt) * f), Rr, 1091 + i, 1.8, 0.22); });
      H.pin(function () {
        P.inkAdd(H.line(L - 14, pb, Rr + 14, pb - 3, { stroke: P.pal.structure, width: 5, opacity: 0.9, amp: 2.6, over: 13, seed: 1093 }));
      });
      for (let i = 1; i <= n; i++) {
        const x = L + colW * (i - 1);
        P.slot('bar-' + i, x + colW * 0.16, pt, colW * 0.68, pb - pt, { role: 'point-column', container: true, anchorX: Math.round(x + colW / 2) });
        P.slot('head-' + i, x, pb + 22, colW, blockH(roles.head, 1), { align: 'center', role: 'head' });
        P.slot('spend-' + i, x, pb + 66, colW, blockH(roles.spend, 1), { align: 'center', role: 'spend' });
      }
      /* The share count under the spend, as its own row of figures rather
       * than a second axis: two axes on one plate is how a viewer reads a
       * correlation the data does not contain. */
      rule(P, L, pb + 150, Rr, 1094, 3.4, 0.6);
      P.slot('count-label', L, pb + 168, cw * 0.4, blockH(roles.countLabel, 1), { align: 'left', role: 'countLabel' });
      for (let i = 1; i <= n; i++) {
        P.slot('count-' + i, L + colW * (i - 1), pb + 212, colW, blockH(roles.count, 1), { align: 'center', role: 'count' });
      }
      P.slot('caption', L, h - 110, cw, blockH(roles.caption, 1), { align: 'left', role: 'caption' });
      return tighten(P);
    };

    /* Round two installs after this and reuses these helpers rather than
     * copying them — one budget derivation for every new plate. Not
     * enumerable, so nothing walking PLATES mistakes it for an author. */
    Object.defineProperty(P0, 'R1_HELPERS', { value: { mc, sized, role, tighten, R, band, rule, tick }, enumerable: false, configurable: true });
    return P0;
  }

  /* THE CATALOGUE for the new plates, beside the authors that draw them. The
   * legacy 270 live in build.js's LIB; consumers concat this onto it rather
   * than either file knowing about the other. Each entry is author + args +
   * seed, the same shape build.js uses, so nothing downstream special-cases
   * these fifteen. */
  const LIB = [
    ['paper', 'press-release-9x16', 'pressRelease', {}],
    ['paper', 'wire-strip-3-9x16', 'wireStrip', { rows: 3 }],
    ['paper', 'wire-strip-5-9x16', 'wireStrip', { rows: 5 }],
    ['structure', 'before-after-9x16', 'beforeAfter', {}],
    ['figures', 'move-on-the-day-9x16', 'moveOnTheDay', { direction: 'down' }],
    ['figures', 'move-on-the-day-up-9x16', 'moveOnTheDay', { direction: 'up' }],
    ['figures', 'print-vs-consensus-9x16', 'printVsConsensus', {}],
    ['charts', 'quarter-bars-8q-9x16', 'quarterBars', {}],
    ['tables', 'three-lines-9x16', 'threeLines', {}],
    ['figures', 'guidance-raise-cut-9x16', 'guidanceRange', {}],
    ['charts', 'intraday-9x16', 'intraday', {}],
    ['figures', '52-week-position-9x16', 'fiftyTwoWeek', {}],
    ['shorts', 'hook-card-t4', 'hookCardT', { treatment: 4 }],
    ['shorts', 'hook-card-t5', 'hookCardT', { treatment: 5 }],
    ['structure', 'closing-t2-9x16', 'closingT', { treatment: 2 }],
    ['structure', 'closing-t3-9x16', 'closingT', { treatment: 3 }],
  ].map(function (r, i) {
    return { dir: r[0], key: r[0] + '/' + r[1], author: r[2],
      args: Object.assign({ w: 1080, h: 1920 }, r[3]), seed: 601 + i };
  }).concat([
    /* ── the long side, all 16:9 ──────────────────────────────────────────
     * Ordered by how thin the chapter type is today: filing-walk may name
     * four plates, the fewest of any type, so it leads. Row and stage counts
     * are the kit's own variety convention and cost a fraction of a drawing.
     */
    ['paper', 'filing-page-16x9', 'filingPage', {}],
    ['paper', 'footnote-pull-16x9', 'footnotePull', {}],
    ['structure', 'year-on-year-diff-16x9', 'yearOnYearDiff', {}],
    ['tables', 'numbers-sheet-7r-16x9', 'numbersSheet', { rows: 7 }],
    ['tables', 'numbers-sheet-8r-16x9', 'numbersSheet', { rows: 8 }],
    ['tables', 'growth-and-margin-16x9', 'growthAndMargin', { rows: 5 }],
    ['tables', 'percentile-rail-16x9', 'percentileRail', { rows: 5 }],
    ['structure', 'said-happened-6-16x9', 'saidHappened', { events: 6 }],
    ['structure', 'where-this-goes-16x9', 'whereThisGoes', { rows: 5 }],
    ['structure', 'timeline-dense-16x9', 'timelineDense', { rows: 10 }],
    ['structure', 'flow-4-16x9', 'flowN', { stages: 4 }],
    ['structure', 'flow-5-16x9', 'flowN', { stages: 5 }],
    ['figures', 'unit-economics-16x9', 'unitEconomics', {}],
    ['structure', 'scorecard-16x9', 'scorecard', { rows: 5 }],
    ['structure', 'moat-sources-4-16x9', 'moatSources', { rows: 4 }],
    ['peers', 'scatter-16x9', 'peerScatter', { points: 8 }],
    ['figures', 'where-the-cash-went-16x9', 'whereTheCashWent', { parts: 4 }],
    ['figures', 'roic-vs-wacc-16x9', 'roicVsWacc', {}],
    ['structure', 'revision-trail-16x9', 'revisionTrail', { rows: 5 }],
    ['figures', 'scenario-fan-16x9', 'scenarioFan', {}],
    ['structure', 'risk-register-4-16x9', 'riskRegister', { rows: 4 }],
    ['structure', 'where-they-agree-16x9', 'whereTheyAgree', { rows: 3 }],
    ['charts', 'buyback-dollars-16x9', 'buybackDollars', { years: 6 }],
  ].map(function (r, i) {
    return { dir: r[0], key: r[0] + '/' + r[1], author: r[2],
      args: Object.assign({ w: 1920, h: 1080 }, r[3]), seed: 701 + i };
  }));

  const API = { install: install, LIB: LIB };
  if (typeof module !== 'undefined' && module.exports) module.exports = API;
  g.PLATES_R1 = API;
})(typeof window !== 'undefined' ? window : globalThis);
