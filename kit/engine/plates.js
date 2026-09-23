/* Dennis v2 — plate authors.
   Each author returns a HAND.Plate: the drawing and the slot table come out of the
   same function, so the manifest is generated, never measured. */
(function (g) {
  const H = g.HAND;

  // ---------------- palette ----------------
  // Eight roles. A colour never does two jobs.
  const ROLES = {
    ground: { hex: "#E6DDC9", note: "night card — the surface everything sits on" },
    ground2: { hex: "#D5CAB1", note: "lower plane in the room; row bands on tables" },
    structure: { hex: "#1C222A", note: "rules, line work, type — and the subject's own series" },
    down: { hex: "#B23C22", note: "a loss, a fall, a bad number. Nothing else" },
    up: { hex: "#3F7347", note: "a rise. Only a rise" },
    neutralData: { hex: "#63727E", note: "revenue, capital, share count — no direction" },
    attention: { hex: "#E0A016", note: "the one thing to look at" },
    otherParty: { hex: "#665694", note: "peers, consensus, last year, the market's opinion" },
  };

  const SURFACES = {
    "night-card": {
      ground: "#E6DDC9", ground2: "#CBBC9B",
      grain: { tint: "#6b5a3c", opacity: 0.085, freq: "0.9" },
      rules: null,
    },
    "legal-pad": {
      ground: "#EFE4A8", ground2: "#E3D68F",
      grain: { tint: "#7a6b2a", opacity: 0.062, freq: "0.85" },
      rules: { colour: "#8CA3C0", margin: "#B8564A" },
    },
    whiteboard: {
      ground: "#F1F2EE", ground2: "#E2E4DE",
      grain: { tint: "#6d7a72", opacity: 0.04, freq: "1.1" },
      rules: null, smears: true,
    },
  };

  // §2 — THE POSE CONSTANT, PUBLISHED FROM THE SOLVED RIG.
  //
  //   C = (rig.forearmY - slots.figure.y) / (floorLineY - slots.figure.y)
  //
  // Closed form, per pose, exactly as the decision asks: never a typed constant,
  // so a room that one day declares a contact for pointing-down-at-desk or
  // holding-a-page gets that pose's own C without anybody revisiting this. It is
  // filled in by hostFigure() when a pose is actually drawn, because forearmY is
  // only known once the arms have been solved — a table of literals here would
  // be the thing the decision rules out.
  //
  // A room built in the same run as its host pose therefore has C; a room built
  // alone does not, and falls back to the authored desk height. build.js emits
  // host/ before room/, so a kit build always has it.
  // MEMO ONLY — never a channel between plates. delta-13c's §2 did not execute
  // for exactly that reason: the table was filled by hostFigure() and read by
  // room(), which works in a single-context kit build and silently yields null
  // anywhere the two are not built in the same run and the same order. A pack
  // whose correctness depends on emission order is not correct.
  //
  // So contactC() SOLVES the pose on demand: it builds the host pose once on a
  // nominal canvas, reads the rig it published, and memoises the ratio. The
  // ratio is dimensionless, so the nominal canvas cancels. The probe is drawn
  // with the shipped hand and its own key, and the caller's render profile is
  // saved and restored around it — a probe that left PROFILE moved would be the
  // same class of bug as the role-floor accumulation.
  const POSE_CONTACT_C = {};
  function contactC(pose) {
    if (POSE_CONTACT_C[pose] === undefined) {
      POSE_CONTACT_C[pose] = null;
      const prev = H.profile();
      // AND THE BOIL, WHICH THE PROFILE FIX MISSED.
      //
      // This memo is filled by whichever plate asks for a pose first, and it was
      // filled with the CALLER'S boil state still set globally. The probe passes
      // boil: 0 in its own arguments, but that only governs the geometry the
      // author derives itself — every mark it makes still goes through the global
      // offset, so a rig value read back off the probe depended on which plate
      // happened to be drawn first in the build.
      //
      // That is the same bug as the profile leak one line above and the same bug
      // as the role-floor accumulation: a cache capturing ambient state. Caught
      // by pre-flight check D, which reported a stray mark on one blink frame
      // that could not be reproduced when the plate was drawn on its own — the
      // signature of an order dependency, not of a geometry error.
      const pb = H.boilFrame(), pa = H.boilAmp(), pg = H.boilGate();
      H.setBoil(0);
      try {
        const probe = hostFigure({
          key: "_probe/" + pose, w: 1080, h: 1920, pal: pal("night-card"),
          seed: 1, pose: pose, mouthOpen: false, bob: 0, boil: 0, profile: "hand-1",
        });
        const fy = probe.meta.rig && probe.meta.rig.forearmY;
        const figY = probe.slots.figure && probe.slots.figure.y;
        const fl = probe.meta.floorLineY;
        if (fy != null && figY != null && fl != null && fl !== figY) {
          POSE_CONTACT_C[pose] = (fy - figY) / (fl - figY);
        }
      } catch (e) {
        POSE_CONTACT_C[pose] = null;
      }
      H.setBoil(pb, pa, pg);
      H.setProfile(prev);
    }
    return POSE_CONTACT_C[pose];
  }

  function pal(surfaceKey) {
    const s = SURFACES[surfaceKey];
    const p = { ground: s.ground, ground2: s.ground2, grain: s.grain, surfaceKey };
    for (const k in ROLES) if (k !== "ground" && k !== "ground2") p[k] = ROLES[k].hex;
    return p;
  }

  // Line weight, tremor and overshoot are canvas-unit quantities. A plate drawn on
  // a smaller canvas must scale them, or it is a different drawing rather than a
  // smaller one — which is what makes contact sheets lie.
  // Boil: the same drawing redrawn, not a different drawing. Every stroke's seed
  // is shifted by a per-frame constant, so tremor, overshoot and hatch phase all
  // land somewhere new while geometry, weight and density are untouched. n=0 is
  // the identity, so a hold frame reproduces byte-for-byte.
  function boilShift(S, n) {
    if (!n) return S;
    const off = n * 9173;
    const sh = function (o) {
      const r = Object.assign({}, o || {});
      if (typeof r.seed === "number") r.seed = r.seed + off;
      return r;
    };
    return {
      hatch: function (poly, o) { return S.hatch(poly, sh(o)); },
      outline: function (poly, o) { return S.outline(poly, sh(o)); },
      stroke: function (pts, o) { return S.stroke(pts, sh(o)); },
      line: function (x1, y1, x2, y2, o) { return S.line(x1, y1, x2, y2, sh(o)); },
    };
  }

  function inkScale(k) {
    if (!k || k === 1) return { hatch: H.hatch, outline: H.outline, stroke: H.stroke, line: H.line };
    const sc = function (o) {
      const r = Object.assign({}, o || {});
      ["width", "gap", "amp", "over"].forEach(function (key) {
        if (typeof r[key] === "number") r[key] = r[key] * k;
      });
      return r;
    };
    return {
      hatch: function (poly, o) { return H.hatch(poly, sc(o)); },
      outline: function (poly, o) { return H.outline(poly, sc(o)); },
      stroke: function (pts, o) { return H.stroke(pts, sc(o)); },
      line: function (x1, y1, x2, y2, o) { return H.line(x1, y1, x2, y2, sc(o)); },
    };
  }

  // Ground furniture that belongs to a surface (pad rules, board smears)
  function surfaceFurniture(P, s) {
    let out = "";
    if (s.rules) {
      for (let y = 120; y < P.h - 40; y += 74) {
        out += H.line(46, y, P.w - 34, y, { stroke: s.rules.colour, width: 1.6, opacity: 0.5, amp: 1.1, seed: (y * 7) | 0 });
      }
      out += H.line(96, 20, 92, P.h - 18, { stroke: s.rules.margin, width: 2.2, opacity: 0.45, amp: 2.2, seed: 991 });
    }
    if (s.smears) {
      const r = H.rng(41);
      for (let i = 0; i < 5; i++) {
        const x = 60 + r() * (P.w - 220), y = 60 + r() * (P.h - 140);
        out += H.hatch(H.polyRect(x, y, 120 + r() * 200, 40 + r() * 60), { color: "#8d968f", opacity: 0.1, gap: 9, width: 7, angle: -6 + r() * 12, seed: (i * 37 + 5) | 0 });
      }
    }
    return out;
  }

  // ---------------- numbers sheet ----------------
  // R rows × 6 period columns. Every cell is its own slot.
  function numbersSheet(o) {
    const rows = o.rows, w = o.w, h = o.h, land = w > h;
    const p = o.pal;
    const s = SURFACES[p.surfaceKey];
    /* LEGACY PASS, rebuild-21: portrait side margins 48 -> 56. At 48 the unit and
     * every row label started inside the 5% safe margin (54 of 1080). */
    const m = land ? { l: 118, r: 118, t: 92, b: 96 } : { l: 56, r: 56, t: 200, b: 220 };
    const P = H.Plate({
      key: o.key, w, h, seed: o.seed, pal: p,
      meta: {
        aspect: land ? "16x9" : "9x16", rows, columns: 6, family: "tables",
        type: o.spark ? "numbers-sheet-spark" : "numbers-sheet",
        // set sizes belong to the plate, not to the renderer's judgement.
        // The spark variants are not the same sheet with a column bolted on: the
        // column takes real width, so figures and labels are re-sized to fit what
        // is left. Labels get abbreviated ("FCF", not "Free cash flow") — the
        // doctrine is already abbreviate the label, never the unit.
        typeRoles: o.spark ? {
          unit: { font: "Courier Prime", size: 26, weight: 400, colour: "structure", opacity: 0.72, tracking: "0.04em", maxChars: land ? 46 : 38 },
          period: { font: "Archivo Narrow", size: land ? 30 : 26, weight: 600, colour: "structure", tracking: "0.02em", maxChars: 6 },
          label: { font: "Archivo Narrow", size: land ? 32 : 24, weight: 500, colour: "structure", maxChars: land ? 21 : 11 },
          figure: { font: "Courier Prime", size: land ? 38 : 26, weight: 400, colour: "structure", lastColumnWeight: 700, maxChars: land ? 7 : 6 },
        } : {
          unit: { font: "Courier Prime", size: 26, weight: 400, colour: "structure", opacity: 0.72, tracking: "0.04em", maxChars: land ? 46 : 38 },
          period: { font: "Archivo Narrow", size: land ? 30 : 28, weight: 600, colour: "structure", tracking: "0.02em", maxChars: 6 },
          label: { font: "Archivo Narrow", size: land ? 34 : 28, weight: 500, colour: "structure", maxChars: land ? 26 : 18 },
          figure: { font: "Courier Prime", size: land ? 46 : 30, weight: 400, colour: "structure", lastColumnWeight: 700, maxChars: land ? 7 : 6 },
        },
      },
    });
    P.colourAdd(surfaceFurniture(P, s));

    const unitH = land ? 42 : 50;
    // A sparkline column is a column: it takes width from the sheet rather than
    // floating over it, so the figures never have to share space with the shape.
    const sparkW = o.spark ? Math.round((w - m.l - m.r) * (land ? 0.14 : 0.17)) : 0;

    const headY = m.t + unitH + (land ? 58 : 74);
    const headH = land ? 54 : 58;
    const ruleY = headY + headH + (land ? 22 : 24);
    const bodyTop = ruleY + (land ? 20 : 22);
    const bodyBot = h - m.b;
    const rowH = (bodyBot - bodyTop) / rows;

    const innerL = m.l, innerR = w - m.r - sparkW;
    // the unit runs the full width of the sheet — it is a sentence, not a column
    P.slot("unit", innerL, m.t, innerR - innerL, unitH, { align: "left", role: "unit" });
    const labelW = Math.round((innerR - innerL) * (o.spark ? (land ? 0.26 : 0.19) : (land ? 0.3 : 0.24)));
    const colsL = innerL + labelW;
    const colW = (innerR - colsL) / 6;

    // second-ground bands on alternate rows (a lower plane, not a highlight)
    for (let i = 2; i <= rows; i += 2) {
      const y = bodyTop + (i - 1) * rowH;
      P.colourAdd(H.hatch(H.polyRect(innerL - 14, y + 3, innerR + sparkW - innerL + 28, rowH - 6), {
        color: p.ground2, opacity: 0.72, gap: 7.5, width: 12, angle: -4, over: 16, seed: 300 + i * 13,
      }));
    }

    // header row slots + faint column structure
    for (let c = 1; c <= 6; c++) {
      const x = colsL + (c - 1) * colW;
      P.slot(`head-${c}`, x + 8, headY, colW - 16, headH, { align: "right", role: "period" });
      if (c > 1) P.inkAdd(H.line(x, headY - 8, x, bodyBot - 6, { stroke: p.structure, width: 2, opacity: 0.28, amp: 4, over: 5, seed: 700 + c * 29 }));
    }
    P.inkAdd(H.line(colsL - 18, headY - 10, colsL - 18, bodyBot - 6, { stroke: p.structure, width: 2.3, opacity: 0.34, amp: 4.4, over: 6, seed: 641 }));
    if (o.spark) {
      const sgx = innerR + (land ? 14 : 10);
      P.slot("head-spark", innerR + (land ? 30 : 22), headY, sparkW - (land ? 38 : 28), headH, { align: "left", role: "period" });
      P.inkAdd(H.line(sgx, headY - 8, sgx, bodyBot - 6, { stroke: p.structure, width: 2.3, opacity: 0.34, amp: 4.4, over: 6, seed: 655 }));
    }

    // heavy rule under the header
    P.inkAdd(H.line(innerL - 8, ruleY, innerR + 8, ruleY, { stroke: p.structure, width: land ? 7 : 6, opacity: 0.95, amp: 3.6, over: 12, seed: 88 }));

    for (let rI = 1; rI <= rows; rI++) {
      const y = bodyTop + (rI - 1) * rowH;
      P.slot(`band-${rI}`, innerL - 30, y + 2, innerR + sparkW - innerL + 60, rowH - 4, { role: "highlight-band", overlay: "overlays/row-band" });
      P.slot(`label-${rI}`, innerL, y + rowH * 0.16, labelW - 26, rowH * 0.68, { align: "left", role: "label" });
      for (let c = 1; c <= 6; c++) {
        P.slot(`cell-${rI}-${c}`, colsL + (c - 1) * colW + 8, y + rowH * 0.16, colW - 16, rowH * 0.68, { align: "right", role: "figure" });
      }
      if (o.spark) {
        P.slot(`spark-${rI}`, innerR + (land ? 30 : 22), y + rowH * 0.2, sparkW - (land ? 38 : 28), rowH * 0.6, {
          role: "spark", region: true, renderer: "series.sparkBars",
          note: "the row's own six values as a shape. The plate draws nothing here — engine/series.js draws it from the data",
        });
      }
      if (rI < rows) {
        P.inkAdd(H.line(innerL - 4, y + rowH, innerR + 4, y + rowH, { stroke: p.structure, width: 2.9, opacity: 0.6, amp: 3, over: 8, seed: 400 + rI * 41 }));
      }
    }
    // foot rule
    P.inkAdd(H.line(innerL - 8, bodyBot, innerR + 8, bodyBot, { stroke: p.structure, width: land ? 4.6 : 4, opacity: 0.85, amp: 3.2, over: 11, seed: 133 }));
    return P;
  }

  // Highlight overlay: composites into any band-N slot
  function rowBand(o) {
    const P = H.Plate({ key: o.key, w: o.w, h: o.h, seed: 55, pal: Object.assign({}, o.pal, { ground: "none", grain: null }),
      meta: { family: "overlays", type: "row-band", composite: "multiply-ok", stretch: "x-only",
        colourRule: "second ground, bracketed in structure. The band says HERE, never good or bad — direction stays in the cells, and attention belongs to annotations.",
        why: "ground2 hatch alone is invisible on the sheet's own ground2 zebra stripe, so the row is bracketed top and bottom in structure. That reads on a striped row and an unstriped one alike." } });
    P.colourAdd(H.hatch(H.polyRect(6, 5, o.w - 12, o.h - 10), { color: o.pal.ground2, opacity: 0.8, gap: 5.5, width: 13, angle: -3, over: 18, seed: 71 }));
    P.inkAdd(H.line(4, 7, o.w - 4, 5, { stroke: o.pal.structure, width: 3.4, opacity: 0.6, amp: 2.4, over: 14, seed: 12 }));
    P.inkAdd(H.line(4, o.h - 6, o.w - 4, o.h - 8, { stroke: o.pal.structure, width: 3.4, opacity: 0.6, amp: 2.4, over: 14, seed: 19 }));
    P.slot("area", 0, 0, o.w, o.h, { role: "band" });
    return P;
  }

  /* ---------------- §1.1 · THE LOWER THIRD ----------------

     The most visible inconsistency in the product, and the cheapest to fix.
     render_long.py builds it with simple_text() — PIL, Courier Bold, a stroke
     outline — so the one persistent brand element in a forty-minute video is a
     font with an outline sitting in a library of drawn ink.

     THREE THINGS DECIDE THIS PLATE, and two of them are not obvious.

     1. IT CARRIES ITS OWN GROUND, for exactly the reason the title took the
        `card`. This sits over a room, a chart, a filing screenshot and stock
        footage — there is no wall to borrow legibility from, and unlike the
        chapter opener there is not even a family of walls to measure against.
        So: an opaque panel, its own bloom rim, its own cast. §1's audit is the
        argument and this plate is the case where it is unarguable.

        NO TAPE, though, and that is the one place it departs from the card. Tape
        says "this arrived after the room did" — true of a chapter title, false
        of the channel's own furniture. The lower third was always there.

     2. IT DOES NOT BOIL. It is on screen longer than any other asset in the
        product, and a wobble that re-draws three times a second at the edge of
        vision for forty minutes is not craft, it is a crawl. `overlays/row-band`
        is already in NO_BOIL_KEYS for the narrower version of this reason —
        movement under type that is deliberately still. Here the type is still
        and the viewer is not looking at it, which is worse. Drawn once, dead
        still, forever.

        This is the one asset where the hand is in the DRAWING and not in the
        MOTION, and it is deliberate rather than an omission.

     3. THE TICKER AND THE TAGLINE ARE TWO SLOTS, NOT ONE STRING. The renderer
        currently formats `$TICKER · noise or signal?` and hands it to PIL as a
        single line. Two slots, two roles, two budgets: the ticker is a proper
        noun that must not wrap and the tagline is copy that might change, and
        one string cannot carry two different failure modes. A five-character
        ticker and a short tagline both sit comfortably — measured, not hoped. */
  function lowerThird(o) {
    const land = o.w > o.h;
    const p = o.pal;
    const W = o.w, HH = o.h;
    const roles = {
      ticker: { font: "Courier Prime", size: land ? 78 : 86, weight: 700, colour: "structure", tracking: "0.01em", maxChars: 9 },
      tagline: { font: "Archivo Narrow", size: land ? 34 : 38, weight: 600, colour: "structure", opacity: 0.86, tracking: "0.02em", maxChars: 30 },
    };
    const P = H.Plate({
      key: o.key, w: W, h: HH, seed: 1401,
      // ground "none": it is an overlay and composites onto whatever is behind
      // it. The PANEL it draws is its own ground — that is the whole point — but
      // the plate itself has no surface and no grain.
      pal: Object.assign({}, p, { ground: "none", grain: null }),
      meta: {
        aspect: land ? "16x9" : "9x16", family: "overlays", type: "lower-third",
        composite: "alpha, over anything",
        typeRoles: roles,
      },
    });
    const q = (n) => n * (land ? 1 : 1.06);
    const m = q(10);                       // the cast needs room inside the canvas
    const panel = { x: m, y: m, w: W - m * 2 - q(12), h: HH - m * 2 - q(12) };
    const ink = p.structure;
    const ring = (g2) => H.polyRect(panel.x - g2, panel.y - g2, panel.w + g2 * 2, panel.h + g2 * 2);
    // Emitted directly rather than through hatch(): hatch treats its authored
    // opacity as COVERAGE and multiplies to solid, and this panel's contrast
    // floor is the exact alpha. Same call the title ground makes.
    const wash = function (poly, colour, alpha, sd) {
      const pts = H.wobble(poly.concat([poly[0]]), { amp: q(2), over: 0, seed: sd, step: q(26) });
      P.colourAdd(`<path d="${H.toPath(pts)}Z" fill="${colour}" fill-opacity="${H.num(alpha)}"/>`);
    };
    // EVERY MARK ON THIS PLATE IS PINNED, which is belt and braces on purpose.
    // The build declares it static so only one frame ever ships — but a plate that
    // is still because of its frame count is still by accident, and the next
    // person to give the overlays family a boil strip gets a crawling lower third
    // with nothing to warn them. Pinned, it cannot wobble even if asked.
    // Structural guarantee rather than relying on care, same as no text nodes.
    H.pin(function () {
      // light is upper-left across the whole kit, so the cast goes down and right
      const off = Math.max(q(6), panel.w * 0.011);
      wash(H.polyRect(panel.x + off * 1.7, panel.y + off * 1.7, panel.w, panel.h), ink, 0.05, 1403);
      wash(H.polyRect(panel.x + off, panel.y + off, panel.w, panel.h), ink, 0.1, 1405);
      wash(ring(0), p.ground, 1, 1407);
      const rim = H.polyRect(panel.x + q(8), panel.y + q(8), panel.w - q(16), panel.h - q(16));
      P.colourAdd(H.stroke(rim.concat([rim[0]]), { stroke: H.darken(p.ground, 0.86), width: q(5), opacity: 0.5, amp: 1.2, over: 0, seed: 1409, silhouette: true }));
      P.inkAdd(H.outline(ring(0), { stroke: ink, width: q(3.6), opacity: 0.92, amp: 3.2, over: q(12), seed: 1411 }));
    });

    const padX = q(30), padY = q(24);
    const L = panel.x + padX, R = panel.x + panel.w - padX;
    const tH = blockH(roles.ticker, 1), gH = blockH(roles.tagline, 1);
    const tY = panel.y + padY;
    // THE TICKER BOX IS 44% OF THE MEASURE, not all of it, and the reason is the
    // same one the language-shift year box ran into: at full width budget.js
    // derived fifteen characters, which is an invitation to put a company name in
    // a slot whose job is $HTZ. Narrowed, it derives six — a five-character ticker
    // with its sigil, and nothing more.
    const tickW = Math.round((R - L) * 0.44);
    P.slot("ticker", L, tY, tickW, tH, { align: "left", role: "ticker", identifier: 9, note: "the ticker as the script names it, e.g. $HTZ. Must not wrap. The box is deliberately narrow: at full measure it would hold a company name, and this slot is not for one." });
    // The rule between them is furniture — it separates a proper noun from copy.
    // Pinned with everything else on the plate.
    const rY = Math.round(tY + tH + q(9));
    H.pin(function () {
      P.inkAdd(H.line(L, rY, R, rY - 2, { stroke: ink, width: q(3), opacity: 0.45, amp: 2.2, over: q(8), seed: 1413 }));
    });
    P.slot("tagline", L, rY + q(11), R - L, gH, { align: "left", role: "tagline", note: "the channel's line, e.g. 'noise or signal?'. Copy, so it may change — which is why it is its own slot with its own budget rather than half of a formatted string." });

    P.meta.panel = { x: Math.round(panel.x), y: Math.round(panel.y), w: Math.round(panel.w), h: Math.round(panel.h), opaque: true };
    P.meta.noBoil = "DELIBERATE, AND THE REASON IS DURATION. This is on screen longer than any other asset in the product. A wobble re-drawn three times a second at the edge of vision for forty minutes is not craft, it is a crawl — overlays/row-band is already exempt for the narrower case (movement under type held still), and here the viewer is not even looking at it. The hand is in the drawing, not in the motion. Enforced twice: engine/build.js NO_BOIL_KEYS ships one frame, AND every mark is inside pin(), so the plate cannot wobble even if a later boil strip asks it to.";
    P.meta.ownGround = "It composites over a room, a chart, a filing screenshot and stock footage, so there is no wall to borrow legibility from — not even a family of walls to measure against, as the chapter openers had. Hence an opaque panel with its own bloom rim and its own cast: §1's finding, applied where it is unarguable. NO TAPE, unlike the title card: tape says the object arrived after the room did, which is true of a chapter title and false of the channel's own furniture.";
    P.meta.replaces = "render_long.py:1450 simple_text() from rasters.py — PIL, Courier Bold, stroke outline. Two slots replace one formatted string: the ticker is a proper noun that must not wrap and the tagline is copy that might change, and one string cannot carry two failure modes.";
    P.meta.placement = "the renderer positions this plate; it does not fill a frame. Bottom-left at one panel-height of margin is what it was designed against. It is its own size for the same reason overlays/row-band is — an overlay the compositor places, not a full-frame plate.";
    P.meta.captionRegister = "SEE THE CAPTION DECISION IN CHANGES.md §1.2. This plate is drawn in the kit's hand because it is large, persistent and a brand element. Captions are NOT, and get the kit's materials without its hand — the two are one decision, and they differ on purpose.";
    return P;
  }

  /* ---------------- §2 · THE CONFESSION ----------------

     The most distinctive thing the channel does, and it had no plate — roughly
     one video in three carries the moment the host says he got something wrong
     about this company before, and on screen it has been reaching for whatever
     generic plate the chapter happened to have.

     WHAT IT IS NOT. The shape is close to `structure/said-happened` and the
     difference is the whole point: said-happened is a company's claim against
     the outcome, drawn as a two-track timeline, and it is built to read as an
     indictment. Pointing that instrument at the host would make the plate an
     indictment of him, which is the opposite of what a confession is for.

     THE TONE IS THE BRIEF, so it is worth writing down what is banned and why:
     no cross, no strike-through, no red, no rule through the old claim, nothing
     that performs contrition. Equally, not small type at the bottom of the
     frame. The register is a person saying plainly "I had this wrong, here is
     what I missed", which is a CREDIBILITY move rather than an apology — and a
     plate that performs either the shame or the shrug has taken the tone out of
     the host's hands, which is mistake 3 in a new costume.

     TWO TREATMENTS, because tone cannot be chosen from a description. They
     differ on a nameable axis \u2014 what carries the credibility:

       statement  THE CORRECTION IS AS CONSIDERED AS THE CLAIM WAS. Three blocks
                  in one continuous statement, one left edge, one type size, one
                  rail down the side. "What I got wrong" is set in exactly the
                  weight of "what I said" \u2014 nothing marks it as the bad one. The
                  credibility is in the EQUAL WEIGHT: he is not flinching and he
                  is not shrugging, and the geometry is what says so.

       ledger     HE KEEPS A RECORD OF THESE. The entry is numbered and dated on
                  a ruled sheet, because the pipeline already tracks confessions
                  in a ledger and the plate can say so. The credibility is in the
                  EXISTENCE OF THE RECORD rather than in this admission: one
                  confession performed carefully still reads as a performance,
                  where "no. 14, and I write them all down" cannot.

                  The risk it runs is the other failure mode \u2014 a ledger entry
                  drawn small and neat is the confession hidden at the bottom of
                  the frame. So the body type here is the SAME SIZE as the
                  statement treatment's. It is ruled like a book and set like a
                  headline, deliberately. */
  const CONFESSION_TREATMENTS = ["statement", "ledger"];

  function confession(o) {
    const land = o.w > o.h, w = o.w, h = o.h, p = o.pal;
    const T = o.treatment;
    if (CONFESSION_TREATMENTS.indexOf(T) < 0) throw new Error("unknown confession treatment " + T);
    const roles = {
      kicker: TR.kicker, caption: TR.caption,
      // ONE role for all three bodies, and that is the tone decision expressed
      // as code. Three roles is how "what I got wrong" becomes the loud one or
      // the quiet one; there is no size at which a correction set differently
      // from its claim reads as level.
      body: { font: "Archivo Narrow", size: land ? 58 : 62, weight: 600, colour: "structure", tracking: "-.01em", maxLines: 2, maxCharsPerLine: land ? 44 : 30 },
      label: { font: "Courier Prime", size: land ? 27 : 26, weight: 700, colour: "structure", opacity: 0.72, tracking: "0.06em", maxChars: 22 },
      entry: { font: "Courier Prime", size: land ? 34 : 32, weight: 700, colour: "structure", opacity: 0.8, tracking: "0.03em", maxChars: 14 },
    };
    const P = base(o, "confession-" + T, roles);
    P.meta.family = "structure";
    P.meta.treatment = T;
    const u = unitOf(h);
    const L = land ? 190 : 84, R = w - (land ? 150 : 76);
    const kickY = land ? 84 : 190, kickH = blockH(roles.kicker, 1);
    P.slot("kicker", L, kickY, (R - L) * 0.62, kickH, { align: "left", role: "kicker" });
    if (T === "ledger") {
      // the entry number and date sit on the kicker's line, right-aligned: a
      // ledger entry is identified before it is read
      P.slot("entry-no", L + (R - L) * 0.76, kickY - u * 0.2, (R - L) * 0.24, blockH(roles.entry, 1),
        { align: "right", role: "entry", identifier: 12, note: "the ledger entry, e.g. 'no. 14'. Deliberately a narrow box \u2014 at a third of the measure budget.js derived 26 characters, which is room for a sentence in a slot whose job is a number. The pipeline already has the count; this is what puts it on screen, and it is the treatment's whole argument: not one careful admission, a practice." });
    }

    // DROP EIGHT: the descender allowance went 4 -> 12. Two lines of body set at
    // the compositor's 1.16em pitch occupy 134.6 of what was a 139-unit box, so the
    // second line's descenders sat 4.4 units off the rule below it on the ledger —
    // measured at 1:1 in render-scale.html §9, not computed. Twelve units puts the
    // clearance at 12.4 and costs 24 units out of the band across the three blocks.
    // Applied to BOTH treatments deliberately: the statement has no rule to clear,
    // but the two plates share one body geometry and that congruence is §2's tone
    // decision expressed as geometry.
    const labH = blockH(roles.label, 1), bodyH = blockH(roles.body, 2) + 12;
    const blockH2 = labH + Math.round(u * 0.5) + bodyH;
    const capY = h - (land ? 118 : 186);
    const headBottom = Math.round(kickY + kickH + u * (land ? 2.0 : 2.6));
    // THE GAP IS DERIVED FROM THE BAND, NOT AUTHORED, and the portrait plate is
    // why. At a fixed gap the three blocks finished at y=1023 on a 1920-tall
    // frame with the caption at 1734 — 680 units of dead space, the whole
    // statement bunched into the top half and reading as though the plate had
    // been cropped. Three blocks and two gaps have to USE the band between the
    // head and the caption, so the gap is what is left over — clamped, so
    // landscape does not get airier than it should and a tight frame still
    // keeps the blocks apart.
    const band = capY - Math.round(u * 1.1) - headBottom;
    const slack = band - 3 * blockH2;
    const gap = Math.max(Math.round(u * 1.5), Math.min(Math.round(u * (land ? 2.1 : 4.2)), Math.floor(slack / 2)));
    // and the group is centred in whatever band is left over, so neither aspect
    // hangs off the top
    const top = headBottom + Math.max(0, Math.round((band - (3 * blockH2 + 2 * gap)) / 2));
    // DROP TEN: THE INDENT IS THE SAME ON BOTH TREATMENTS, and only the statement
    // draws a rail in it. It used to be 0 on the ledger, which made the ledger's
    // measure 51 landscape units and 72 portrait units WIDER — 68 characters a
    // line against the statement's 66, and 37 against 34. Each plate was correct;
    // the PAIR was never measured, which is host/empty-chair's failure shape
    // exactly. The consequence was that a confession written to the ledger at 37
    // characters a line does not fit the statement, and an over-budget fill
    // renders nothing — so picking a treatment after the copy was written blanked
    // the plate. Both now derive the SAME body box from the same indent, so a
    // confession written once fits either and the treatment is a drawing choice
    // rather than a copy constraint. The ledger gives up the 2-3 characters a line
    // it had; that is the cost, and it is the right direction because the rail is
    // real and the ledger had the room to give.
    const indent = Math.round(u * (land ? 3.0 : 2.4));
    const NAMES = ["said", "happened", "wrong"];
    const boxes = [];
    NAMES.forEach(function (nm, i) {
      const by = top + i * (blockH2 + gap);
      const bx = L + indent;
      boxes.push({ name: nm, x: bx, y: by, w: R - bx, h: blockH2 });
      P.slot(nm + "-label", bx, by, (R - bx) * 0.5, labH, { align: "left", role: "label" });
      P.slot(nm, bx, by + labH + Math.round(u * 0.5), R - bx, bodyH, { align: "left", role: "body" });
    });

    if (T === "statement") {
      // ONE rail across all three blocks, with a spur into each. One rail is
      // what makes them one statement; three rails would be three claims, and a
      // rail that stopped short of the third block would mark it out.
      const railX = L + Math.round(indent * 0.44);
      const railTop = top + Math.round(labH * 0.3);
      const railBot = top + 2 * (blockH2 + gap) + labH + Math.round(bodyH * 0.45);
      P.inkAdd(H.breathe(function () {
        return H.line(railX, railTop, railX + 2, railBot, { stroke: p.structure, width: 4.2, opacity: 0.55, amp: 2.8, over: 11, seed: 1511 });
      }));
      boxes.forEach(function (b, i) {
        const sy = b.y + Math.round(labH * 0.52);
        P.inkAdd(H.breathe(function () {
          return H.line(railX, sy, b.x - Math.round(u * 0.5), sy - 1, { stroke: p.structure, width: 3.2, opacity: 0.48, amp: 1.8, over: 7, seed: 1520 + i * 9 });
        }));
      });
    } else {
      // A RULED SHEET, and the rules run the full measure under each body — the
      // page of a book he writes these in. They are furniture: they say "this is
      // a record", nothing is measured off them, so they breathe.
      boxes.forEach(function (b, i) {
        const ry = b.y + b.h + Math.round(gap * 0.42);
        P.inkAdd(H.breathe(function () {
          return H.line(L - u * 0.4, ry, R + u * 0.4, ry - 2, { stroke: p.structure, width: 2.6, opacity: 0.34, amp: 2.4, over: 9, seed: 1540 + i * 11 });
        }));
      });
      // and one rule under the kicker row, closing the entry's head
      const hy = Math.round(kickY + kickH + u * 0.8);
      P.inkAdd(H.breathe(function () {
        return H.line(L - u * 0.4, hy, R + u * 0.4, hy - 1, { stroke: p.structure, width: 3.4, opacity: 0.5, amp: 2.4, over: 10, seed: 1535 });
      }));
    }

    P.slot("caption", L, capY, R - L, blockH(roles.caption, 1), { align: "left", role: "caption" });
    const bottom = top + 3 * blockH2 + 2 * gap + (T === "ledger" ? Math.round(gap * 0.42) : 0);
    P.meta.fit = { top: top, blockH: blockH2, gap: gap, band: band, bottom: bottom, captionY: capY,
      clears: bottom < capY - Math.round(u * 0.6), fillsBand: +((bottom - top) / band).toFixed(3) };
    P.meta.blocks = boxes;
    P.meta.congruent = boxes.every((b) => b.h === boxes[0].h && b.w === boxes[0].w);
    P.meta.notSaidHappened = "structure/said-happened is a COMPANY's claim against the outcome, drawn as a two-track timeline and built to read as an indictment. This is the host's own claim. Pointing that instrument at him would make the plate an indictment of him, which is the opposite of what a confession is for \u2014 so it is a separate author rather than a variant, and it has no rails, no intervals and no event marks.";
    P.meta.refusesVerdict = "NO CROSS, NO STRIKE-THROUGH, NO RED, NO RULE THROUGH THE OLD CLAIM. All three bodies are ONE type role at ONE size in `structure`, so the plate cannot mark which of them is the bad one. If the script wants the old claim struck, that is annotations/strike-out applied by the compositor \u2014 and worth arguing about before it is asked for, because a confession that strikes its own claim is performing contrition, which is the thing this plate exists not to do.";
    P.meta.tone = "the register is 'I had this wrong, here is what I missed' \u2014 a credibility move, not an apology. The plate carries the weight by giving the correction the same weight as the claim; it does not shout it and it does not hide it. Neither the shame nor the shrug is drawn in, because both belong to the voice.";
    P.meta.labelContract = "the -label slots carry the STEP, not a judgement: 'WHAT I SAID', 'WHAT HAPPENED', 'WHAT I GOT WRONG'. A label reading 'MY MISTAKE' or 'IN FAIRNESS' on the third block is the plate taking the tone out of the host's hands.";
    P.meta.argument = T === "statement"
      ? "THE CORRECTION IS AS CONSIDERED AS THE CLAIM WAS. Three blocks, one continuous statement, one left edge, one type size, one rail down the side with a spur into each. Nothing marks the third block as the bad one \u2014 the credibility is in the equal weight, and it is geometry rather than intent, so it is assertable."
      : "HE KEEPS A RECORD OF THESE. A numbered, dated entry on a ruled sheet \u2014 the pipeline already tracks confessions in a ledger, and this plate says so on screen. The credibility is in the existence of the record rather than in this admission: one confession performed carefully still reads as a performance; 'no. 14, and I write them all down' cannot. Ruled like a book and set like a headline, because a ledger entry drawn small and neat is the confession hidden at the bottom of the frame.";
    return P;
  }

  /* ---------------- §3.1 · SHORT INTEREST ----------------

     There is a `short-interest` chapter type and it has been filling its
     evidence beat with `figures/big-number-l2` — days-to-cover as a big number.
     A number on its own is the one thing this plate exists to replace.

     A SQUEEZE SETUP IS FOUR QUANTITIES THAT MEAN NOTHING INDIVIDUALLY: float,
     shares short, days to cover, cost to borrow. "Forty million shares short" is
     enormous or trivial depending entirely on the float, and the plate's job is
     to make the RELATIONSHIP legible rather than to stack four figures.

     SO THE PROPORTION IS DRAWN AND THE DURATION IS NOT, and that is the whole
     design. Two of the four are a share of something: shares short against
     float. That gets the bar — the outline IS the float, the region inside it is
     the short interest, and the reader does not divide anything. The other two
     are not proportions at all: days-to-cover is a duration and cost-to-borrow
     is a rate, and drawing either as a bar would invite a comparison that means
     nothing. They sit as figures, paired, under the bar.

     WHAT IS NOT DRAWN: the bar's outline is the float, so it is a measurement
     reference and the plate is otherwise still — see the breathe map's
     still-by-design list, same as `figures/share-of`.

     AND NOTHING IS PRE-COLOURED. A 30%-of-float short position is a squeeze
     setup or a nothing depending on who holds it and why, and the script decides
     which. No alarm colour, no threshold, no mark at some level the plate thinks
     is interesting. */
  function shortInterest(o) {
    const land = o.w > o.h, w = o.w, h = o.h, p = o.pal;
    const roles = {
      kicker: TR.kicker, caption: TR.caption, unit: TR.detail,
      // ONE role for all four values: they are four readings of one situation,
      // and a plate that sets days-to-cover larger than cost-to-borrow has
      // decided which one the story is.
      value: { font: "Courier Prime", size: land ? 88 : 78, weight: 700, colour: "structure", maxChars: 8 },
      label: { font: "Archivo Narrow", size: land ? 30 : 28, weight: 600, colour: "structure", opacity: 0.8, tracking: "0.03em", maxLines: 2, maxCharsPerLine: land ? 20 : 18 },
      barLabel: { font: "Courier Prime", size: land ? 30 : 28, weight: 700, colour: "structure", opacity: 0.85, maxChars: 18 },
    };
    const P = base(o, "short-interest", roles);
    P.meta.family = "figures";
    const u = unitOf(h);
    const L = land ? 170 : 80, R = w - (land ? 150 : 76);
    const kickY = land ? 86 : 192, kickH = blockH(roles.kicker, 1);
    P.slot("kicker", L, kickY, (R - L) * 0.64, kickH, { align: "left", role: "kicker" });
    P.slot("unit", L + (R - L) * 0.66, kickY, (R - L) * 0.34, kickH, { align: "right", role: "unit" });

    // ---- the proportion ----
    const barY = Math.round(kickY + kickH + u * (land ? 2.4 : 3.0));
    const barH = Math.round(land ? u * 4.6 : u * 4.0);
    // the outline IS the float: a measurement reference, so it is pinned
    H.pin(function () {
      P.inkAdd(H.outline(H.polyRect(L, barY, R - L, barH), { stroke: p.structure, width: land ? 4.4 : 4, opacity: 0.9, amp: 3, over: q12(u), seed: 1611 }));
    });
    P.slot("float", L, barY, R - L, barH, {
      role: "whole", region: true, container: true,
      note: "THE FLOAT IS THE WHOLE BAR. Do not fill this region \u2014 its outline is already drawn and it is the reference everything else is read against. It is published as a region only so the compositor knows the extent that `short` is a share of.",
    });
    P.slot("short", L, barY, R - L, barH, {
      role: "bar", region: true, growth: "right-from-left", extentOf: "float",
      note: "shares short, drawn as a share of the float region from the left edge. THE POINT OF THE PLATE: the reader does not divide anything. Fill to (sharesShort / float) of the width.",
    });
    P.slot("float-label", L, barY + barH + Math.round(u * 0.6), (R - L) * 0.48, blockH(roles.barLabel, 1), { align: "left", role: "barLabel", note: "what the bar is, e.g. 'free float 84.2m'" });
    P.slot("short-label", L + (R - L) * 0.52, barY + barH + Math.round(u * 0.6), (R - L) * 0.48, blockH(roles.barLabel, 1), { align: "right", role: "barLabel", note: "the filled part, e.g. '31.4m short'. Right-aligned so it reads off the end of the bar rather than competing with the float label." });

    // ---- the two that are not proportions ----
    const figTop = Math.round(barY + barH + blockH(roles.barLabel, 1) + u * (land ? 2.6 : 3.2));
    const valH = blockH(roles.value, 1), labH = blockH(roles.label, 2);
    const cellW = Math.round(((R - L) - u * (land ? 2.4 : 2.0)) / 2);
    const gut = (R - L) - cellW * 2;
    [["days", "days to cover \u2014 a DURATION, not a share of anything. At one day's average volume."],
     ["borrow", "cost to borrow \u2014 a RATE. Annualised, as the script quotes it."]].forEach(function (pr, i) {
      const cx = L + i * (cellW + gut);
      P.slot(pr[0], cx, figTop, cellW, valH, { align: "left", role: "value", note: pr[1] });
      P.slot(pr[0] + "-label", cx, figTop + valH + Math.round(u * 0.4), cellW, labH, { align: "left", role: "label" });
    });
    // one rule between the proportion and the two figures: they are different
    // KINDS of quantity and the plate should not let them read as a set of four
    const rY = Math.round(figTop - u * (land ? 1.3 : 1.6));
    P.inkAdd(H.breathe(function () {
      return H.line(L, rY, R, rY - 2, { stroke: p.structure, width: 3, opacity: 0.4, amp: 2.4, over: 9, seed: 1621 });
    }));

    const capY = h - (land ? 118 : 186);
    P.slot("caption", L, capY, R - L, blockH(roles.caption, 1), { align: "left", role: "caption" });
    P.meta.fit = { figuresBottom: figTop + valH + Math.round(u * 0.4) + labH, captionY: capY,
      clears: figTop + valH + Math.round(u * 0.4) + labH < capY - Math.round(u * 0.6) };
    P.meta.argument = "four quantities that mean nothing individually. Two of them are a share of something \u2014 shares short against float \u2014 and those get the bar, so the relationship is drawn rather than divided. The other two are a duration and a rate: they sit as figures, because drawing them as bars would invite a comparison that means nothing.";
    P.meta.replaces = "figures/big-number-l2 in the short-interest chapter's evidence beat. A number on its own is what this plate exists to replace: 'forty million shares short' is enormous or trivial entirely depending on the float.";
    P.meta.signAgnostic = "NOTHING IS PRE-COLOURED AND NOTHING IS MARKED. A 30%-of-float short position is a squeeze setup or a nothing depending on who holds it and why; the script decides. No alarm colour, no threshold line, no tick at a level the plate finds interesting.";
    P.meta.valueRole = "all four values are ONE type role at ONE size. A plate that sets days-to-cover larger than cost-to-borrow has decided which of the four the story is, which is the script's job.";
    P.meta.stillByDesign = "the bar outline is the float, which is a measurement reference, so it is pinned. Only the dividing rule breathes.";
    return P;
  }

  /* ---------------- §3.2 · INSIDER FLOW ----------------

     The pipeline pulls Form 4 filings — who bought or sold, when, how much.
     `figures/ownership` covers the static picture; nothing covered the flow,
     which is arguably the highest-signal thing in the filings stack.

     A TIMELINE WITH THE TRADES AS MARKS, SIZED BY VALUE. The axis is drawn and
     pinned; each mark is a region the renderer fills from the axis, in the
     direction the trade went.

     ABOVE AND BELOW THE AXIS IS NOT A VERDICT, and this is worth being explicit
     about because it looks like one. Up-for-buy and down-for-sell is the same
     encoding `figures/waterfall` uses for a step that adds or subtracts: the
     direction IS the data, not a judgement about it. What would be a verdict is
     colour — green-good, red-bad — and there is none. Both directions are one
     ink at one weight, and a plate of all sells looks exactly like a plate of
     all buys, inverted.

     COUNT VARIANTS ON MARKS: 6 and 12. Six is a normal quarter's filings; twelve
     is the case the plate exists for, where the pattern is the argument. Both are
     authored rather than one elastic plate, for tables/'s reason — an elastic one
     would re-derive its pitch at render time. */
  function insiderFlow(o) {
    const land = o.w > o.h, w = o.w, h = o.h, p = o.pal;
    const N = o.marks;
    const roles = {
      kicker: TR.kicker, caption: TR.caption, unit: TR.detail,
      date: { font: "Archivo Narrow", size: land ? 26 : 22, weight: 600, colour: "structure", opacity: 0.78, maxChars: 8 },
      who: { font: "Courier Prime", size: land ? 24 : 21, weight: 400, colour: "structure", opacity: 0.72, maxChars: 14 },
      axis: { font: "Courier Prime", size: land ? 25 : 23, weight: 400, colour: "structure", opacity: 0.7, maxChars: 9 },
    };
    const P = base(o, "insider-flow-" + N, roles);
    P.meta.family = "charts";
    P.meta.marks = N;
    const u = unitOf(h);
    const L = land ? 200 : 96, R = w - (land ? 150 : 80);
    const kickY = land ? 84 : 190, kickH = blockH(roles.kicker, 1);
    P.slot("kicker", L, kickY, (R - L) * 0.62, kickH, { align: "left", role: "kicker" });
    P.slot("unit", L + (R - L) * 0.64, kickY, (R - L) * 0.36, kickH, { align: "right", role: "unit" });

    const capY = h - (land ? 120 : 188);
    const plotTop = Math.round(kickY + kickH + u * (land ? 2.2 : 2.8));
    // LEGACY PASS, rebuild-21: the date and who rows hang under the plot, and in
    // 16:9 the who row ran into the caption. The plot now stops where both rows
    // and half a unit still clear it.
    const plotBot = Math.round(Math.min(capY - u * (land ? 3.2 : 3.6),
      capY - Math.round(u * 1.0) - blockH(roles.date, 1) - blockH(roles.who, 1)));
    const axisY = Math.round((plotTop + plotBot) / 2);
    P.slot("plot-area", L, plotTop, R - L, plotBot - plotTop, { role: "plot-area", container: true, note: "code draws the marks in here only" });
    // THE AXIS IS TIME AND IT IS THE ZERO LINE FOR VALUE. Pinned: every mark's
    // height is measured from it, which is the waterfall's baseline argument.
    H.pin(function () {
      P.inkAdd(H.line(L - u * 0.5, axisY, R + u * 0.5, axisY - 2, { stroke: p.structure, width: land ? 4.6 : 4, opacity: 0.92, amp: 3, over: q12(u), seed: 1711 }));
    });
    // two scale references, one each side, so a mark's size is readable at all
    [["above", -1], ["below", 1]].forEach(function (pr, i) {
      const y = axisY + pr[1] * Math.round((plotBot - plotTop) * 0.5);
      P.slot("scale-" + pr[0], L - (land ? 170 : 90), y - 26, land ? 150 : 76, 52, { align: "right", role: "axis",
        note: "the value at the top of the " + pr[0] + " half, e.g. '$4m'. Both halves share ONE scale \u2014 a plate whose buys and sells are scaled independently is unreadable and would be a verdict by arithmetic." });
    });

    const step = (R - L) / N;
    const markW = Math.round(step * (N > 8 ? 0.5 : 0.42));
    P.meta.marksGeo = [];
    for (let i = 1; i <= N; i++) {
      const cx = L + step * (i - 0.5);
      // one region per trade, spanning BOTH halves. The renderer fills from the
      // axis in the direction the trade went — it does not pick a slot, which is
      // what keeps the plate from encoding the direction itself.
      P.slot("mark-" + i, Math.round(cx - markW / 2), plotTop, markW, plotBot - plotTop, {
        role: "mark", region: true, growth: "from-axis-both-ways", axisY: axisY, index: i,
        note: "one Form 4 trade. Fill from axisY upward for a purchase and downward for a sale, to (value / scale) of the half-height. Direction is the DATA, not a judgement \u2014 one ink, one weight, both ways.",
      });
      // a tick where the trade sits on the time axis: read off, so pinned
      H.pin(function () {
        P.inkAdd(H.line(cx, axisY - 9, cx, axisY + 9, { stroke: p.structure, width: 2.2, opacity: 0.62, amp: 1.1, seed: 1720 + i * 7 }));
      });
      P.slot("date-" + i, Math.round(cx - step / 2), plotBot + Math.round(u * 0.5), Math.round(step), blockH(roles.date, 1),
        { align: "center", role: "date", note: "when, e.g. \"12 Mar\". Under the plot, not under the mark: a mark can sit either side of the axis and its label must not move with it." });
    }
    // WHO TRADED, only where it measures out. At twelve marks in 9:16 a name box
    // is under four characters, and a row of initials is worse than no row —
    // budget.js decides, not me.
    const whoFits = g.BUDGET.capacity({ w: step }, "who", roles.who) >= 6;
    if (whoFits) {
      for (let i = 1; i <= N; i++) {
        const cx = L + step * (i - 0.5);
        P.slot("who-" + i, Math.round(cx - step / 2), plotBot + Math.round(u * 0.5) + blockH(roles.date, 1), Math.round(step), blockH(roles.who, 1),
          { align: "center", role: "who", note: "who, e.g. 'CFO'. A role rather than a name where it fits \u2014 the argument is almost never about the individual." });
      }
    } else {
      P.slot("who-note", L, plotBot + Math.round(u * 0.5) + blockH(roles.date, 1), R - L, blockH(roles.who, 1),
        { align: "left", role: "who", note: "ONE line standing in for a per-mark who row, which does not fit at this count in this aspect: the box measures under six characters and an over-budget fill does not render. e.g. 'all four officers'." });
    }
    P.slot("caption", L, capY, R - L, blockH(roles.caption, 1), { align: "left", role: "caption" });

    P.meta.axisY = axisY;
    P.meta.argument = N + " Form 4 trades on a time axis, sized by value. figures/ownership is the static picture; this is the flow \u2014 and at " + N + " marks the " + (N > 8 ? "pattern is the argument" : "individual trades still are") + ".";
    P.meta.signAgnostic = "ABOVE FOR A PURCHASE, BELOW FOR A SALE \u2014 direction is the DATA, exactly as a waterfall step can add or subtract. What would be a verdict is colour, and there is none: one ink, one weight, both ways, so a plate of all sells looks like a plate of all buys inverted. No green, no red, no arrow.";
    P.meta.oneScale = "BOTH HALVES SHARE ONE SCALE. Scaling buys and sells independently would make a $200k purchase look like a $4m sale \u2014 a verdict reached by arithmetic, which is the hardest kind to notice. scale-above and scale-below are published separately so the renderer can state the scale, not so it can use two.";
    P.meta.counts = "6 and 12. Six is a normal quarter's filings; twelve is the case the plate exists for. Authored rather than elastic \u2014 an elastic plate re-derives its pitch at render time, and the pitch is the thing that has to stay still between cuts.";
    P.meta.whoRow = whoFits ? "per-mark who row published \u2014 the box measures " + g.BUDGET.capacity({ w: step }, "who", roles.who) + " characters." : "NO per-mark who row at this count and aspect: the box measures under six characters and an over-budget fill does not render. One who-note line instead.";
    return P;
  }

  /* ---------------- §3.3 · MACRO SERIES ----------------

     The pipeline pulls FRED series for the `macro` format. `charts/line-6y` is
     built for six annual company periods; a macro series is decades long with a
     much denser axis, and it needs somewhere to put recession bands. Same name,
     different plate — and the count convention does not apply, because the
     periods here are not the company's.

     THE BANDS ARE REGIONS, NOT DRAWN. A recession band's extent is data — when
     it started and when it ended — so drawing one would be drawing the data.
     Four band regions are published across the plot and the renderer fills the
     ones the series actually spans, at low value, behind the line.

     THE AXIS IS DENSE AND ONLY SOME OF IT IS LABELLED. Ten labelled decades and
     forty unlabelled minor ticks: the minor ticks give the eye the scale without
     forty labels competing with the series. Both pinned \u2014 they are read off. */
  function macroSeries(o) {
    const land = o.w > o.h, w = o.w, h = o.h, p = o.pal;
    const roles = {
      kicker: TR.kicker, caption: TR.caption, unit: TR.detail,
      axis: { font: "Courier Prime", size: land ? 25 : 22, weight: 400, colour: "structure", opacity: 0.7, maxChars: 9 },
      period: { font: "Archivo Narrow", size: land ? 26 : 22, weight: 600, colour: "structure", opacity: 0.78, maxChars: 6 },
      source: { font: "Courier Prime", size: land ? 22 : 20, weight: 400, colour: "structure", opacity: 0.62, maxChars: 44 },
    };
    const P = base(o, "macro-series", roles);
    P.meta.family = "charts";
    const u = unitOf(h);
    const L = land ? 210 : 110, R = w - (land ? 140 : 76);
    const kickY = land ? 84 : 190, kickH = blockH(roles.kicker, 1);
    P.slot("kicker", L, kickY, (R - L) * 0.62, kickH, { align: "left", role: "kicker" });
    P.slot("unit", L + (R - L) * 0.64, kickY, (R - L) * 0.36, kickH, { align: "right", role: "unit" });
    const srcH = blockH(roles.source, 1);
    const capY = h - (land ? 116 : 182);
    const srcY = Math.round(capY - srcH - u * 0.5);
    const y0 = Math.round(kickY + kickH + u * (land ? 2.0 : 2.6));
    const y1 = Math.round(srcY - u * (land ? 3.0 : 3.4));
    P.slot("plot-area", L, y0, R - L, y1 - y0, { role: "plot-area", container: true, note: "code draws the series and the bands in here only" });

    // gridlines breathe, axes are pinned — §1.5, same as every chart
    for (let i = 0; i <= 4; i++) {
      const y = y1 - ((y1 - y0) / 4) * i;
      if (i > 0) P.inkAdd(H.breathe(function () {
        return H.line(L, y, R, y, { stroke: p.structure, width: 1.7, opacity: 0.19, amp: 2.6, over: 7, seed: 1810 + i * 7 });
      }));
      /* LEGACY PASS, rebuild-21: the bottom label was centred on the baseline and
       * hung into head-1 under it. It now sits on the baseline, the mirror of
       * the top label sitting under its line. */
      P.slot("y-" + (i + 1), L - (land ? 170 : 100), i === 4 ? y + 6 : i === 0 ? y - 50 : y - 26, land ? 150 : 86, 52, { align: "right", role: "axis" });
    }
    H.pin(function () {
      P.inkAdd(H.line(L, y0 - 14, L, y1, { stroke: p.structure, width: land ? 4.6 : 4, opacity: 0.9, amp: 3, over: 11, seed: 1821 }));
      P.inkAdd(H.line(L, y1, R + 16, y1, { stroke: p.structure, width: land ? 4.6 : 4, opacity: 0.9, amp: 3, over: 11, seed: 1822 }));
    });
    // ten labelled decades, forty minor ticks between them
    const MAJOR = 10, MINOR = 4;
    const mstep = (R - L) / (MAJOR - 1);
    for (let i = 0; i < MAJOR; i++) {
      const x = L + mstep * i;
      H.pin(function () {
        P.inkAdd(H.line(x, y1, x, y1 + 15, { stroke: p.structure, width: 2.4, opacity: 0.75, amp: 1.1, seed: 1830 + i * 7 }));
      });
      P.slot("head-" + (i + 1), Math.round(x - mstep * 0.5), y1 + Math.round(u * 0.55), Math.round(mstep), blockH(roles.period, 1),
        { align: "center", role: "period", anchorX: Math.round(x), note: "a decade, e.g. '1990'. Ten of them \u2014 the count convention does not apply here: these are not the company's periods." });
      if (i < MAJOR - 1) {
        for (let k = 1; k <= MINOR; k++) {
          const mx = x + (mstep / (MINOR + 1)) * k;
          H.pin(function () {
            P.inkAdd(H.line(mx, y1, mx, y1 + 7, { stroke: p.structure, width: 1.7, opacity: 0.5, amp: 0.9, seed: 1860 + i * 11 + k }));
          });
        }
      }
    }
    P.slot("series", L, y0, R - L, y1 - y0, {
      role: "series", region: true,
      note: "THE SERIES. One path across the plot \u2014 the shape is the data and it is not drawn here. Subject ink, single weight.",
    });
    // FOUR BAND REGIONS. A recession's extent is data (when it began, when it
    // ended), so the plate publishes places a band may go and fills none.
    for (let i = 1; i <= 4; i++) {
      P.slot("band-" + i, L, y0, R - L, y1 - y0, {
        role: "band", region: true, index: i, spans: "x-only",
        note: "a recession band: full plot height, x extent set by the renderer from the dates. Fill at LOW value behind the series \u2014 a band that out-contrasts the line has become the subject. Four are published because a long series usually spans three or four; fill only the ones the data has, and leave the rest empty rather than distributing them.",
      });
    }
    P.slot("source", L, srcY, R - L, srcH, { align: "left", role: "source",
      note: "the series and its provenance, e.g. 'FRED: UNRATE, monthly, seasonally adjusted'. REQUIRED on this plate \u2014 a macro series with no source is the one chart on a real-numbers channel that nobody can check." });
    P.slot("caption", L, capY, R - L, blockH(roles.caption, 1), { align: "left", role: "caption" });
    P.meta.axis = { major: MAJOR, minorPerMajor: MINOR, labelled: MAJOR };
    P.meta.argument = "a decades-long series with recession bands. charts/line-6y is six annual company periods; this is the same name and a different plate \u2014 denser axis, band regions, and a source line that is not optional.";
    P.meta.bandsNotDrawn = "A RECESSION'S EXTENT IS DATA \u2014 when it began and when it ended. Drawing one would be drawing the data, so four band regions are published and none is filled. Fill the ones the series spans and leave the others empty; do not distribute four bands across the plot because four exist.";
    P.meta.densityNote = MAJOR + " labelled decades and " + (MAJOR - 1) * MINOR + " unlabelled minor ticks. The minor ticks give the eye the scale without forty labels competing with the series. All pinned: a tick is read off.";
    return P;
  }

  /* ---------------- §3.4 · THE END CARD ----------------

     `structure/closing` exists as a chapter plate, but YouTube end screens have
     fixed geometry: the platform overlays subscribe and next-video elements in
     specific rectangles over the final twenty seconds. A closing plate that does
     not know where they land gets covered up.

     THIS IS THE ONE PLATE IN THE KIT WHOSE LAYOUT IS DICTATED FROM OUTSIDE IT,
     so the zones are published in the manifest rather than described here — the
     composition has to work with the platform's furniture sitting in it, and the
     next person to touch this plate needs the numbers, not my account of them.

     THE ZONES ARE LEFT DELIBERATELY EMPTY. Not "kept clear where convenient":
     no slot, no mark and no region overlaps them, and preflight can assert it.
     A caption that runs under a subscribe button is not a caption.

     WHAT IS UNVERIFIED, AND IT MATTERS HERE: I designed against YouTube's
     end-screen element grid as I understand it — elements are placed on a
     coarse grid in the 16:9 frame, video cards are 16:9, the subscribe element
     is circular. I could not check the current spec, so the numbers below are
     DESIGNED-AGAINST rather than confirmed, and they are published precisely so
     that when someone checks them the plate can be corrected in one place. */
  function endCard(o) {
    const land = o.w > o.h, w = o.w, h = o.h, p = o.pal;
    const roles = {
      kicker: TR.kicker, caption: TR.caption,
      line: { font: "Archivo Narrow", size: land ? 82 : 76, weight: 700, colour: "structure", tracking: "-.01em", maxLines: 2, maxCharsPerLine: land ? 26 : 22 },
      hand: { font: "Courier Prime", size: land ? 30 : 28, weight: 400, colour: "structure", opacity: 0.74, maxLines: 2, maxCharsPerLine: land ? 34 : 28 },
    };
    const P = base(o, "end-card", roles);
    P.meta.family = "structure";
    const u = unitOf(h);
    // THE PLATFORM'S FURNITURE, as fractions of the frame. Fractions rather than
    // units so the same numbers describe both aspects and survive a canvas change.
    const ZONES = land
      ? [{ id: "video-1", kind: "video card", x: 0.505, y: 0.14, w: 0.225, h: 0.30 },
         { id: "video-2", kind: "video card", x: 0.755, y: 0.14, w: 0.225, h: 0.30 },
         { id: "subscribe", kind: "subscribe (circular)", x: 0.505, y: 0.56, w: 0.16, h: 0.285 }]
      : [{ id: "video-1", kind: "video card", x: 0.10, y: 0.60, w: 0.36, h: 0.115 },
         { id: "video-2", kind: "video card", x: 0.52, y: 0.60, w: 0.36, h: 0.115 },
         { id: "subscribe", kind: "subscribe (circular)", x: 0.40, y: 0.755, w: 0.20, h: 0.11 }];
    // The content band is what is left. Derived from the zones rather than
    // authored beside them, so moving a zone moves the type — which is the whole
    // point of publishing them.
    const keepOut = ZONES.map(function (z) {
      return { id: z.id, kind: z.kind, x: Math.round(z.x * w), y: Math.round(z.y * h), w: Math.round(z.w * w), h: Math.round(z.h * h) };
    });
    const L = land ? 150 : 84;
    const R = land ? Math.round(Math.min.apply(null, keepOut.map((z) => z.x)) - u * 1.6) : w - 84;
    const topB = land ? Math.round(h * 0.16) : Math.round(h * 0.17);
    const botB = land ? Math.round(h * 0.84) : Math.round(Math.min.apply(null, keepOut.map((z) => z.y)) - u * 1.8);
    P.slot("content-area", L, topB, R - L, botB - topB, { role: "content-area", container: true,
      note: "everything on this plate lives here. It is DERIVED from the keep-out zones, not authored beside them, so correcting a zone moves the type with it." });

    const kickH = blockH(roles.kicker, 1), lineH = blockH(roles.line, 2) + 4, handH = blockH(roles.hand, 2);
    const stackH = kickH + Math.round(u * 0.8) + lineH + Math.round(u * 1.1) + handH;
    const sTop = topB + Math.max(0, Math.round((botB - topB - stackH) / 2));
    P.slot("kicker", L, sTop, R - L, kickH, { align: "left", role: "kicker" });
    P.slot("line", L, sTop + kickH + Math.round(u * 0.8), R - L, lineH, { align: "left", role: "line",
      note: "the closing line, two lines at " + roles.line.maxCharsPerLine + " characters measured. Not a sign-off: the script's last claim." });
    const hY = sTop + kickH + Math.round(u * 0.8) + lineH + Math.round(u * 1.1);
    P.slot("hand", L, hY, R - L, handH, { align: "left", role: "hand",
      note: "what the viewer does next, in the host's own register, e.g. 'the ledger is in the description'. NOT 'like and subscribe' \u2014 the platform is already drawing a subscribe button four hundred units to the right, and saying it twice is worse than not saying it." });
    // a rule under the stack, stopping short of the first zone
    const rY = Math.round(hY + handH + u * 0.9);
    if (rY < botB) P.inkAdd(H.breathe(function () {
      return H.line(L, rY, R, rY - 2, { stroke: p.structure, width: 3.2, opacity: 0.42, amp: 2.4, over: 9, seed: 1911 });
    }));

    P.meta.keepOut = keepOut;
    P.meta.keepOutSource = "DESIGNED-AGAINST, NOT CONFIRMED. YouTube's end-screen elements sit on a coarse grid in the 16:9 frame; video cards are 16:9 and the subscribe element is circular. I could not check the current published spec, so treat these fractions as the numbers this composition was built for rather than as the platform's. They are in the manifest so that when someone checks them, the plate is corrected in ONE place and the content band moves with them.";
    P.meta.zonesEmpty = "NO SLOT AND NO AUTHORED MARK overlaps a keep-out zone \u2014 not 'kept clear where convenient'. Measured on both aspects: 0 slot overlaps, 0 ink or colour marks reaching a zone. THE PAPER SURFACE DOES extend under them, necessarily and correctly: that is what a ground is, and the platform draws opaque elements on top of it. What must not be under a subscribe button is CONTENT \u2014 type, and the marks that organise type. Preflight can assert the content half because the zones are published.";
    P.meta.notClosing = "structure/closing is a chapter plate and knows nothing about the platform. This one's layout is dictated from outside the kit, which is why it is a separate plate rather than a variant \u2014 and the only plate here whose geometry someone else can change without telling us.";
    P.meta.duration = "the platform draws its elements over the final twenty seconds. If the cut holds this plate for less than that, the zones are empty for no reason \u2014 which is a director's problem, not the plate's, but worth knowing.";
    return P;
  }

  // small helper: the standard overshoot at this scale
  function q12(u) { return Math.round(u * 0.42); }

  // ---------------- board demos (not shipping plates: these carry drawn data) ----------------
  function threeSeries(o) {
    const p = o.pal, w = o.w, h = o.h;
    const P = H.Plate({ key: o.key, w, h, seed: 9, pal: p, meta: { family: "board", type: "worked-example" } });
    const m = { l: 150, r: 120, t: 110, b: 140 };
    const x0 = m.l, x1 = w - m.r, y0 = m.t, y1 = h - m.b;
    // gridlines
    for (let i = 1; i <= 4; i++) {
      const y = y1 - ((y1 - y0) / 4) * i;
      P.inkAdd(H.line(x0, y, x1, y, { stroke: p.structure, width: 1.8, opacity: 0.22, amp: 2.6, over: 7, seed: 200 + i * 7 }));
    }
    // frame: axes only
    P.inkAdd(H.line(x0, y0 - 14, x0, y1, { stroke: p.structure, width: 4.4, opacity: 0.9, amp: 3, over: 10, seed: 21 }));
    P.inkAdd(H.line(x0, y1, x1 + 16, y1, { stroke: p.structure, width: 4.4, opacity: 0.9, amp: 3, over: 10, seed: 22 }));
    const cols = 6, step = (x1 - x0) / (cols - 1);
    for (let c = 0; c < cols; c++) {
      const x = x0 + step * c;
      P.inkAdd(H.line(x, y1, x, y1 + 16, { stroke: p.structure, width: 2.2, opacity: 0.8, amp: 1.2, seed: 300 + c * 11 }));
    }
    const series = [
      { key: "subject", col: p.structure, v: [0.30, 0.52, 0.74, 0.66, 0.20, 0.28], w: 4.2 },
      { key: "revenue", col: p.neutralData, v: [0.14, 0.24, 0.42, 0.56, 0.70, 0.76], w: 3.6 },
      { key: "peer", col: p.otherParty, v: [0.44, 0.46, 0.43, 0.47, 0.45, 0.44], w: 3.4 },
    ];
    series.forEach((s, si) => {
      const pts = s.v.map((v, i) => ({ x: x0 + step * i, y: y1 - v * (y1 - y0) }));
      P.inkAdd(H.stroke(pts, { stroke: s.col, width: s.w, amp: 2.4, step: 34, over: 4, seed: 900 + si * 57 }));
      pts.forEach((pt, i) => {
        P.inkAdd(H.stroke([{ x: pt.x - 5, y: pt.y }, { x: pt.x + 5, y: pt.y }], { stroke: s.col, width: s.w, amp: 1, over: 2, seed: 950 + si * 13 + i }));
      });
    });
    // the last point of the subject series marked with attention
    const last = { x: x0 + step * 5, y: y1 - 0.28 * (y1 - y0) };
    P.colourAdd(H.hatch([{ x: last.x - 30, y: last.y - 30 }, { x: last.x + 30, y: last.y - 30 }, { x: last.x + 30, y: last.y + 30 }, { x: last.x - 30, y: last.y + 30 }], { color: p.attention, opacity: 0.5, gap: 7, width: 7, angle: -70, seed: 61 }));
    return P;
  }

  function swatch(o) {
    const p = o.pal;
    const P = H.Plate({ key: o.key, w: o.w, h: o.h, seed: o.seed, pal: p, meta: { family: "board", type: "swatch" } });
    if (o.mode === "hatch") {
      P.colourAdd(H.hatch(H.polyRect(18, 16, o.w - 36, o.h - 32), { color: o.hex, opacity: 0.78, gap: 6, width: 7, angle: -76, over: 10, seed: o.seed * 3 + 1 }));
      P.inkAdd(H.outline(H.polyRect(18, 16, o.w - 36, o.h - 32), { stroke: p.structure, width: 2.4, opacity: 0.85, amp: 2, over: 7, seed: o.seed * 7 + 3 }));
    } else {
      P.colourAdd(H.hatch(H.polyRect(0, 0, o.w, o.h), { color: o.hex, opacity: 0.9, gap: 5, width: 9, angle: -80, over: 14, seed: o.seed * 5 }));
    }
    return P;
  }

  // A surface candidate: the ground under load — rules, a band, a coloured bar
  function surfaceCard(o) {
    const key = o.surfaceKey, p = pal(key), s = SURFACES[key];
    const w = o.w, h = o.h;
    const P = H.Plate({ key: o.key, w, h, seed: o.seed, pal: p, meta: { family: "board", type: "surface-candidate", surface: key } });
    P.colourAdd(surfaceFurniture(P, s));
    const L = 60, R = w - 60, T = 70, B = h - 70;
    const rows = 4, rowH = (B - T - 60) / rows, colsL = L + 200, colW = (R - colsL) / 6;
    P.colourAdd(H.hatch(H.polyRect(L - 10, T + 60 + rowH, R - L + 20, rowH), { color: p.attention, opacity: 0.45, gap: 7, width: 12, angle: -3, over: 16, seed: 77 }));
    P.inkAdd(H.line(L - 6, T + 52, R + 6, T + 52, { stroke: p.structure, width: 5, opacity: 0.95, amp: 2.6, over: 10, seed: 31 }));
    for (let i = 1; i < rows; i++) P.inkAdd(H.line(L, T + 60 + rowH * i, R, T + 60 + rowH * i, { stroke: p.structure, width: 2.3, opacity: 0.55, amp: 2.4, over: 7, seed: 500 + i * 19 }));
    for (let c = 1; c < 6; c++) P.inkAdd(H.line(colsL + colW * c, T + 30, colsL + colW * c, B - 40, { stroke: p.structure, width: 1.7, opacity: 0.26, amp: 3.2, seed: 600 + c * 23 }));
    // a down bar and an up bar, to see colour on this ground
    P.colourAdd(H.hatch(H.polyRect(L, B - 26, 120, 20), { color: p.down, opacity: 0.7, gap: 5, width: 7, angle: -78, seed: 12 }));
    P.colourAdd(H.hatch(H.polyRect(L + 150, B - 26, 120, 20), { color: p.up, opacity: 0.7, gap: 5, width: 7, angle: -78, seed: 13 }));
    P.colourAdd(H.hatch(H.polyRect(L + 300, B - 26, 120, 20), { color: p.neutralData, opacity: 0.7, gap: 5, width: 7, angle: -78, seed: 14 }));
    P.colourAdd(H.hatch(H.polyRect(L + 450, B - 26, 120, 20), { color: p.otherParty, opacity: 0.7, gap: 5, width: 7, angle: -78, seed: 15 }));
    return P;
  }

  // ---------------- waterfall: what the revenue turns into ----------------
  // §2.1. USE WHEN the claim is where a figure WENT — revenue at the top, each
  // cost knocking a chunk out of it, what is left at the bottom.
  //
  // Not structure/flow and not structure/multiple-bridge. Both of those are
  // about VALUATION — flow walks a process, the bridge changes a denominator at
  // every step. This is quantity: one unit, one scale, and every bar measured
  // against the same zero. That is why it cannot be either of them with different
  // labels.
  //
  // WHY THE BARS ARE A REGION AND THE COLUMNS ARE DRAWN.
  //
  // A waterfall's bar heights ARE the data — a plate that drew them would be a
  // chart of invented numbers, which §0.1 forbids. But the COLUMN GRID is
  // structural: how many steps there are, where each sits, and that they share
  // one baseline is true before any number arrives. So the plate draws the
  // baseline, the column centres and the connector stubs, and `bridge` is a
  // region that engine/series.js fills. With no data in it the plate still reads
  // as a waterfall with nothing in it yet, rather than as an empty box.
  //
  // SIGN IS THE RENDERER'S, NOT THE AUTHOR'S. A step can ADD as well as subtract
  // — a tax credit, a one-off gain — and the brief is explicit that this must not
  // send the author to a different plate. So nothing here is drawn downward:
  // there is no arrow, no pre-drawn descent, and the connector stubs are
  // horizontal. series.waterfall decides up or down per step from the value's own
  // sign, and the geometry accommodates either because it commits to neither.
  //
  // The step columns are also NOT pre-coloured down. A cost is not a loss — it is
  // the ordinary operation of a business — and colouring five subtractions red
  // before the script has spoken makes the plate argue ahead of the voice-over.
  function waterfall(o) {
    const land = o.w > o.h, w = o.w, h = o.h, p = o.pal;
    const n = o.steps;
    const roles = {
      kicker: TR.kicker, caption: TR.caption, unit: TR.unit || TR.detail,
      // The end figures are the two the viewer is asked to hold — what came in
      // and what was left — so they are the largest type on the plate.
      end: { font: "Courier Prime", size: land ? 76 : 64, weight: 700, colour: "structure", maxChars: 8 },
      // A step figure is read against the end figures, never on its own, so it is
      // deliberately smaller. Same family, one step down.
      step: { font: "Courier Prime", size: land ? 44 : 38, weight: 700, colour: "structure", maxChars: 8 },
      // Cost names are the longest strings on the plate and the most variable
      // ("Stock-based compensation" against "Tax"). Narrow face, two lines.
      stepLabel: { font: "Archivo Narrow", size: land ? 28 : 26, weight: 500, colour: "structure", opacity: 0.86, maxLines: 2, maxCharsPerLine: land ? 15 : 13 },
      endLabel: { font: "Archivo Narrow", size: land ? 32 : 30, weight: 600, colour: "structure", tracking: "0.04em", maxLines: 2, maxCharsPerLine: land ? 14 : 12 },
    };
    const P = base(o, "waterfall-" + n + "s", roles);
    P.meta.family = "figures";
    P.meta.steps = n;
    const u = unitOf(h);
    const L = land ? 150 : 72, R = w - (land ? 150 : 72);
    P.slot("kicker", L, land ? 88 : 196, (R - L) * 0.7, blockH(roles.kicker, 1), { align: "left", role: "kicker" });
    P.slot("unit", L + (R - L) * 0.72, land ? 88 : 196, (R - L) * 0.28, blockH(roles.kicker, 1), { align: "right", role: "unit" });

    // The column grid. n steps plus the two ends, one baseline under all of them.
    const cols = n + 2;
    const top = land ? 210 : 330;
    const labelH = blockH(roles.stepLabel, 2) + u;
    const figH = blockH(roles.end, 1);
    const capH = blockH(roles.caption, 1);
    const baseY = h - (land ? 150 : 230) - capH - labelH - u;
    const plotH = baseY - top - figH - u;
    const gut = (R - L) / cols;
    // Bars take three-quarters of their column, so the gap between them is the
    // quarter — enough to read as separate quantities rather than a filled block.
    const barW = Math.round(gut * 0.74);
    const colX = (i) => Math.round(L + gut * i + (gut - barW) / 2);

    // THE BASELINE IS THE ONE DRAWN MEASUREMENT REFERENCE ON THIS PLATE, and it
    // is pinned: every bar is read against it. §1.5's rule at the point it costs
    // something.
    H.pin(function () {
      P.inkAdd(H.line(L - u, baseY, R + u, baseY - 3, { stroke: p.structure, width: 5.2, opacity: 0.92, amp: 3.2, over: 13, seed: 301 }));
    });

    // Connector stubs: horizontal, one between each pair of columns, at no
    // particular height — series.waterfall raises each to the top of the step it
    // leaves. Drawn faint so an unfilled plate still shows the chain.
    for (let i = 0; i < cols - 1; i++) {
      const x2 = colX(i) + barW, x3 = colX(i + 1);
      leader(P, x2, x3, baseY - Math.round(plotH * 0.44), 320 + i * 11, 0.2);
    }

    P.slot("bridge", L, top + figH + u, R - L, plotH, {
      role: "bridge", region: true, renderer: "series.waterfall", steps: n, columns: cols,
      note: "the bars, and ONLY the bars. Column geometry is in meta.columns — x and width per column, already measured — so the renderer places heights on a shared scale and never re-derives where a column is. Step sign comes from the value: negative knocks down from the running total, positive builds up from it. The plate draws no direction and no colour, so an upward step needs no second plate.",
    });
    P.meta.columns = [];
    for (let i = 0; i < cols; i++) P.meta.columns.push({ x: colX(i), w: barW, role: i === 0 ? "total" : i === cols - 1 ? "remainder" : "step-" + i });

    // Figures ABOVE the plot for the two ends, labels BELOW for everything.
    // A step's own figure sits with its label, because a number floating over a
    // bar whose height the plate does not know can collide with the bar.
    // THE END FIGURES ARE NOT CONSTRAINED TO THEIR COLUMN, and this is a fix the
    // two-workbook check earned. At five steps in portrait a column is ~130 units
    // wide, which will not hold a five-digit figure at end weight — the first cut
    // put "7,410" in a box that fitted "7,41". The two end values are the pair the
    // viewer is asked to hold, they sit above the plot where there is nothing else,
    // and the first and last columns are at the two edges anyway: so they get half
    // the plate each and align outward. Nothing about that depends on step count,
    // which is the property that was missing.
    P.slot("total", L, top, (R - L) * 0.46, figH, { align: "left", role: "end" });
    P.slot("remainder", L + (R - L) * 0.54, top, (R - L) * 0.46, figH, { align: "right", role: "end" });
    // LEGACY PASS, rebuild-21: the end labels took 0.2 of a gutter each side and
    // ran 0.07 of a gutter into step-1 / step-n, whose boxes take 0.13. Same
    // inset as the steps now, so neighbouring label boxes meet and never cross.
    P.slot("total-label", colX(0) - Math.round(gut * 0.13), baseY + u, barW + Math.round(gut * 0.26), labelH, { align: "center", role: "endLabel" });
    P.slot("remainder-label", colX(cols - 1) - Math.round(gut * 0.13), baseY + u, barW + Math.round(gut * 0.26), labelH, { align: "center", role: "endLabel" });
    for (let i = 1; i <= n; i++) {
      const x = colX(i) - Math.round(gut * 0.13), cw = barW + Math.round(gut * 0.26);
      P.slot(`step-${i}`, x, baseY + Math.round(u * 0.3), cw, blockH(roles.step, 1), { align: "center", role: "step" });
      P.slot(`label-${i}`, x, baseY + Math.round(u * 0.3) + blockH(roles.step, 1), cw, labelH - Math.round(u * 0.3), { align: "center", role: "stepLabel" });
    }
    P.slot("caption", L, h - (land ? 130 : 200), R - L, capH, { align: "left", role: "caption" });
    return P;
  }

  // ---------------- what has to be true ----------------
  // §2.2. The price as a DEMAND rather than as a number: at this multiple the
  // market needs this much growth for this long — and here is what the company
  // has actually managed, beside it, on the same axis.
  //
  // The whole argument is the COMPARISON, and specifically whether the marker
  // sits inside the band or outside it. So the two live on one axis and the axis
  // is drawn: its extent is what makes "outside" mean anything, and it is true
  // before any value arrives.
  //
  // The band and the marker are regions for the reason every other data region
  // in this kit is one — the plate cannot know a growth rate. But they are two
  // regions rather than one, because they have different failure modes: a band
  // wider than the axis is a legitimate reading that the renderer clamps and
  // marks, and a marker outside the axis is the most important thing the plate
  // can ever say and must never be silently dropped.
  //
  // Fixed shape, no count variants: there is one demand and one history. A
  // second band would be a different argument and a different plate.
  function impliedPlate(o) {
    const land = o.w > o.h, w = o.w, h = o.h, p = o.pal;
    const roles = {
      kicker: TR.kicker, caption: TR.caption,
      // The statement IS the plate. It is the sentence the marker is evidence
      // for, and it is set at headline weight because on a 9:16 phone it is what
      // survives when the axis is small.
      statement: { font: "Archivo Narrow", size: land ? 62 : 54, weight: 700, colour: "structure", tracking: "-.01em", maxLines: 3, maxCharsPerLine: land ? 30 : 22 },
      demand: { font: "Courier Prime", size: land ? 58 : 50, weight: 700, colour: "structure", maxChars: 7 },
      band: { font: "Courier Prime", size: land ? 30 : 28, weight: 700, colour: "otherParty", maxChars: 7 },
      axis: { font: "Courier Prime", size: land ? 26 : 25, weight: 400, colour: "structure", opacity: 0.7, maxChars: 7 },
      tag: { font: "Archivo Narrow", size: land ? 27 : 26, weight: 600, colour: "structure", opacity: 0.74, tracking: "0.06em", maxChars: land ? 24 : 18 },
    };
    const P = base(o, "implied", roles);
    P.meta.family = "structure";
    const u = unitOf(h);
    const L = land ? 150 : 72, R = w - (land ? 150 : 72);
    P.slot("kicker", L, land ? 88 : 190, R - L, blockH(roles.kicker, 1), { align: "left", role: "kicker" });

    // The axis. Landscape puts it right of the statement and runs it vertically —
    // growth over time reads as height, and a horizontal axis beside a
    // left-aligned sentence would fight the sentence for the same eye-line.
    // Portrait puts it under the statement and runs it horizontally, because a
    // vertical axis on a phone leaves the band a few pixels wide.
    const vert = land;
    let ax;
    if (vert) {
      const x = Math.round(L + (R - L) * 0.72);
      const y0 = Math.round(h * 0.2), y1 = Math.round(h * 0.78);
      ax = { x0: x, y0: y0, x1: x, y1: y1, len: y1 - y0 };
      // PINNED: the band and the marker are both read off this line.
      H.pin(function () { P.inkAdd(H.line(x, y0 - u, x, y1 + u, { stroke: p.structure, width: 4.4, opacity: 0.9, amp: 2.8, over: 12, seed: 401 })); });
      P.slot("axis-high", x + u * 2, y0 - Math.round(blockH(roles.axis, 1) * 0.5), R - x - u * 2, blockH(roles.axis, 1), { align: "left", role: "axis" });
      P.slot("axis-low", x + u * 2, y1 - Math.round(blockH(roles.axis, 1) * 0.5), R - x - u * 2, blockH(roles.axis, 1), { align: "left", role: "axis" });
      P.slot("band", x - Math.round(u * 3.4), y0, Math.round(u * 2.6), y1 - y0, {
        role: "band", region: true, renderer: "series.historyBand", axis: "vertical",
        note: "the company's own range, from history-low and history-high as fractions of the axis. Drawn as a band on the axis, not as a bar from zero: it is an extent, and a bar would claim a baseline the plate does not have.",
      });
      P.slot("marker", x + Math.round(u * 0.6), y0, Math.round(u * 5), y1 - y0, {
        role: "marker", region: true, renderer: "series.axisMark", axis: "vertical",
        note: "the demand, at one position on the same axis. A value outside 0-1 means the market is asking for something outside the company's own history in the direction of the overshoot — clamp to the end and MARK it. Dropping it silently removes the only claim the plate makes.",
      });
    } else {
      const y = Math.round(h * 0.6);
      const x0 = L, x1 = R;
      ax = { x0: x0, y0: y, x1: x1, y1: y, len: x1 - x0 };
      // PINNED, same as the landscape axis.
      H.pin(function () { P.inkAdd(H.line(x0 - u, y, x1 + u, y - 3, { stroke: p.structure, width: 4.4, opacity: 0.9, amp: 2.8, over: 12, seed: 401 })); });
      P.slot("axis-low", x0, y + u * 2, (x1 - x0) * 0.4, blockH(roles.axis, 1), { align: "left", role: "axis" });
      P.slot("axis-high", x0 + (x1 - x0) * 0.6, y + u * 2, (x1 - x0) * 0.4, blockH(roles.axis, 1), { align: "right", role: "axis" });
      P.slot("band", x0, y + Math.round(u * 0.8), x1 - x0, Math.round(u * 2.6), {
        role: "band", region: true, renderer: "series.historyBand", axis: "horizontal",
        note: "the company's own range, from history-low and history-high as fractions of the axis. Drawn as a band on the axis, not as a bar from zero: it is an extent, and a bar would claim a baseline the plate does not have.",
      });
      P.slot("marker", x0, y - Math.round(u * 5.6), x1 - x0, Math.round(u * 5), {
        role: "marker", region: true, renderer: "series.axisMark", axis: "horizontal",
        note: "the demand, at one position on the same axis. A value outside 0-1 means the market is asking for something outside the company's own history in the direction of the overshoot — clamp to the end and MARK it. Dropping it silently removes the only claim the plate makes.",
      });
    }
    P.meta.axis = { x0: ax.x0, y0: ax.y0, x1: ax.x1, y1: ax.y1, orientation: vert ? "vertical" : "horizontal", note: "one axis, both regions on it. The band and the marker MUST share this scale or the comparison is a lie — which is why the geometry is published here rather than measured twice." };

    // A STACK, MEASURED, rather than three fractions of the height that happen not
    // to collide on one aspect. The first cut put the demand figure at 0.2h and the
    // statement at 0.16h with three lines to run into it, and at three lines they
    // overlapped — on the landscape plate, with the sample text, visibly. Stacking
    // off the measured block heights means a two-line statement and a three-line
    // one both work, which is what maxLines is for.
    let sy = land ? 160 : 270;
    const colW = land ? (R - L) * 0.52 : R - L;
    P.slot("statement", L, sy, colW, blockH(roles.statement, 3), { align: "left", role: "statement" });
    sy += blockH(roles.statement, 3) + u * 2;
    P.slot("demand", L, sy, colW, blockH(roles.demand, 1), { align: "left", role: "demand" });
    sy += blockH(roles.demand, 1);
    P.slot("demand-label", L, sy, colW, blockH(roles.tag, 1), { align: "left", role: "tag" });
    sy += blockH(roles.tag, 1) + u * 2;
    P.slot("history-low", L, sy, colW * 0.46, blockH(roles.band, 1), { align: "left", role: "band" });
    P.slot("history-high", L + colW * 0.5, sy, colW * 0.46, blockH(roles.band, 1), { align: "left", role: "band" });
    sy += blockH(roles.band, 1);
    P.slot("history-label", L, sy, colW, blockH(roles.tag, 1), { align: "left", role: "tag" });
    P.slot("caption", L, h - (land ? 130 : 200), R - L, blockH(roles.caption, 1), { align: "left", role: "caption" });
    return P;
  }

  // ---------------- part of a whole: one bar that divides ----------------
  // §2.6 share-of, §2.12 ownership, §2.14 by-region — ONE AUTHOR.
  //
  // All three are the same picture: a single bar, divided, labelled. What differs
  // is the count and what the segments MEAN, which lives in the key and the
  // manifest rather than in the geometry. Same call as the six-period charts, and
  // for the same reason: a shared drawing with different meaning is a family.
  //
  // §2.14 is deliberately a bar and not a map. The argument is the PROPORTION,
  // not the geography — a map is a different and much larger problem, and it
  // would put Kansas and Karnataka on the same visual footing as their revenue.
  //
  // The segments are ONE region, not n regions. A part-of-a-whole divides a fixed
  // length: if each segment were its own box the renderer could produce a set that
  // does not sum to the bar, which is the one thing this plate must never show.
  function proportionBar(o) {
    const land = o.w > o.h, w = o.w, h = o.h, p = o.pal;
    const n = o.segments, kind = o.kind;
    const roles = {
      kicker: TR.kicker, caption: TR.caption,
      headline: { font: "Archivo Narrow", size: land ? 58 : 50, weight: 700, colour: "structure", tracking: "-.01em", maxLines: 2, maxCharsPerLine: land ? 34 : 24 },
      segLabel: { font: "Archivo Narrow", size: land ? 30 : 27, weight: 600, colour: "structure", maxLines: 2, maxCharsPerLine: land ? 18 : 14 },
      segValue: { font: "Courier Prime", size: land ? 46 : 40, weight: 700, colour: "structure", maxChars: 6 },
    };
    const P = base(o, kind + "-" + n, roles);
    P.meta.family = kind === "ownership" ? "figures" : "figures";
    P.meta.segments = n;
    P.meta.kind = kind;
    const u = unitOf(h), L = land ? 150 : 72, R = w - (land ? 150 : 72);
    P.slot("kicker", L, land ? 92 : 200, R - L, blockH(roles.kicker, 1), { align: "left", role: "kicker" });
    P.slot("headline", L, land ? 156 : 272, land ? (R - L) * 0.8 : R - L, blockH(roles.headline, 2), { align: "left", role: "headline" });
    const barY = Math.round(h * (land ? 0.44 : 0.42));
    const barH = Math.round(h * (land ? 0.13 : 0.075));
    field(P, L, barY, R - L, barH, 601, 0.34);
    H.pin(function () {
      P.inkAdd(H.outline(H.polyRect(L, barY, R - L, barH), { stroke: p.structure, width: 4.4, opacity: 0.92, amp: 3, over: 12, seed: 602 }));
    });
    P.slot("segments", L, barY, R - L, barH, {
      role: "segments", region: true, renderer: "series.divide", count: n,
      note: "ONE region, divided into " + n + " by the renderer from " + n + " values that sum to the whole. Not " + n + " boxes: separate boxes can be filled with a set that does not sum to the bar, and a part-of-a-whole that does not add up is the one thing this plate must never show. The outline and the ends are drawn and pinned — the division is data.",
    });
    const colW = (R - L) / n;
    for (let i = 1; i <= n; i++) {
      const x = L + colW * (i - 1);
      P.slot(`value-${i}`, x, barY + barH + u, colW - u, blockH(roles.segValue, 1), { align: "left", role: "segValue" });
      P.slot(`label-${i}`, x, barY + barH + u + blockH(roles.segValue, 1), colW - u, blockH(roles.segLabel, 2), { align: "left", role: "segLabel" });
      if (i > 1) H.pin(function () { P.inkAdd(H.line(x, barY - u * 0.6, x, barY + barH + u * 0.6, { stroke: p.structure, width: 2, opacity: 0.22, amp: 1.6, over: 4, seed: 610 + i })); });
    }
    P.slot("caption", L, h - (land ? 130 : 200), R - L, blockH(roles.caption, 1), { align: "left", role: "caption" });
    if (kind === "ownership") {
      P.meta.argument = "insider, institutional, and everyone else. Both figures are already in the workbook and 'management owns nought point four percent of this' had nowhere to land.";
      P.meta.fixedCount = "three, and not a variant. A fourth slice is a different argument.";
    }
    if (kind === "by-region") {
      P.meta.argument = "where the revenue actually comes from. Matters enormously for macro and tariff stories.";
      P.meta.notAMap = "a labelled proportional bar, deliberately. The argument is the proportion; a map is a different and much larger problem, and it would give a large empty country the same weight as its revenue.";
    }
    if (kind === "share-of") {
      P.meta.argument = "one quantity as a share of another. 'Stock comp was fifty-eight percent of revenue' had no visual home — figures/big-fraction sets it as TYPE, which is not the same as watching it take more than half.";
    }
    return P;
  }

  // ---------------- distribution — §2.5 ----------------
  // A histogram of the peer set with the subject marked in it. "22x earnings" is
  // only cheap or expensive against a spread; peers/peer-strip gives a LIST, which
  // is not a judgement.
  function distribution(o) {
    const land = o.w > o.h, w = o.w, h = o.h, p = o.pal;
    const buckets = 7;
    const roles = {
      kicker: TR.kicker, caption: TR.caption,
      axis: { font: "Courier Prime", size: land ? 26 : 24, weight: 400, colour: "structure", opacity: 0.7, maxChars: 8 },
      marker: { font: "Archivo Narrow", size: land ? 34 : 30, weight: 700, colour: "structure", maxLines: 2, maxCharsPerLine: land ? 20 : 16 },
      unit: { font: "Courier Prime", size: 26, weight: 400, colour: "structure", opacity: 0.72, tracking: "0.04em", maxChars: land ? 46 : 38 },
    };
    const P = base(o, "distribution", roles);
    P.meta.family = "peers";
    P.meta.buckets = buckets;
    const u = unitOf(h), L = land ? 170 : 80, R = w - (land ? 170 : 80);
    P.slot("kicker", L, land ? 92 : 200, (R - L) * 0.7, blockH(roles.kicker, 1), { align: "left", role: "kicker" });
    P.slot("unit", L + (R - L) * 0.72, land ? 92 : 200, (R - L) * 0.28, blockH(roles.kicker, 1), { align: "right", role: "unit" });
    const baseY = Math.round(h * (land ? 0.74 : 0.66));
    const plotT = Math.round(h * (land ? 0.30 : 0.34));
    H.pin(function () {
      P.inkAdd(H.line(L - u, baseY, R + u, baseY - 3, { stroke: p.structure, width: 4.6, opacity: 0.92, amp: 3, over: 12, seed: 651 }));
    });
    const step = (R - L) / buckets, barW = step * 0.78;
    for (let i = 1; i <= buckets; i++) {
      const x = L + step * (i - 1) + (step - barW) / 2;
      P.slot(`bucket-${i}`, Math.round(x), plotT, Math.round(barW), baseY - plotT, {
        role: "bucket", region: true, growth: "up-from-baseline", baselineY: Math.round(baseY),
        note: "a count of peers in this band. Seven buckets, fixed — a histogram whose bucket count moves is not comparable with the one in the previous chapter.",
      });
      H.pin(function () { P.inkAdd(H.line(x + barW / 2, baseY, x + barW / 2, baseY + u * 0.7, { stroke: p.structure, width: 2.2, opacity: 0.6, amp: 1.1, seed: 660 + i })); });
    }
    P.slot("marker", L, plotT - u * 2, R - L, baseY - plotT + u * 2, {
      role: "marker", region: true, renderer: "series.axisMark", axis: "horizontal",
      note: "the SUBJECT's position on the same axis as the buckets, 0 at axis-low and 1 at axis-high. This is the whole plate: a spread without the subject in it is a statistic, and the subject without the spread is a number. A position outside 0-1 means the subject is off the peer range — clamp to the end and MARK it, never drop it.",
    });
    P.slot("marker-label", L, plotT - u * 2 - blockH(roles.marker, 2), (R - L) * 0.5, blockH(roles.marker, 2), { align: "left", role: "marker" });
    P.slot("axis-low", L, baseY + u * 1.6, (R - L) * 0.4, blockH(roles.axis, 1), { align: "left", role: "axis" });
    P.slot("axis-high", L + (R - L) * 0.6, baseY + u * 1.6, (R - L) * 0.4, blockH(roles.axis, 1), { align: "right", role: "axis" });
    P.slot("caption", L, h - (land ? 130 : 200), R - L, blockH(roles.caption, 1), { align: "left", role: "caption" });
    P.meta.axisNote = "the buckets and the marker share one horizontal scale, published here. Two scales would put the subject in the wrong bucket, which is a lie the plate would tell silently.";
    return P;
  }

  // ---------------- scale — §2.7 ----------------
  // A large figure with one or two human-sized things beside it, to the same
  // scale. "$1.28B in cash" is a noise; next to a year of operating expense it
  // becomes "they can afford to be wrong for eight years."
  function scaleFig(o) {
    const land = o.w > o.h, w = o.w, h = o.h, p = o.pal;
    const refs = o.refs;
    const roles = {
      kicker: TR.kicker, caption: TR.caption,
      anchorLabel: { font: "Archivo Narrow", size: land ? 34 : 30, weight: 700, colour: "structure", maxLines: 2, maxCharsPerLine: land ? 22 : 18 },
      refLabel: { font: "Archivo Narrow", size: land ? 28 : 26, weight: 600, colour: "structure", opacity: 0.88, maxLines: 2, maxCharsPerLine: land ? 20 : 16 },
    };
    const P = base(o, "scale-" + refs, roles);
    P.meta.family = "figures";
    P.meta.refs = refs;
    const u = unitOf(h), L = land ? 150 : 72, R = w - (land ? 150 : 72);
    P.slot("kicker", L, land ? 92 : 200, R - L, blockH(roles.kicker, 1), { align: "left", role: "kicker" });
    const baseY = Math.round(h * (land ? 0.78 : 0.70));
    const plotT = Math.round(h * (land ? 0.22 : 0.28));
    H.pin(function () {
      P.inkAdd(H.line(L - u, baseY, R + u, baseY - 3, { stroke: p.structure, width: 4.6, opacity: 0.92, amp: 3, over: 12, seed: 671 }));
    });
    const cols = refs + 1, gut = (R - L) / cols, colW = Math.round(gut * 0.72);
    const cx = (i) => Math.round(L + gut * i + (gut - colW) / 2);
    P.slot("anchor", cx(0), plotT, colW, baseY - plotT, {
      role: "anchor", region: true, growth: "up-from-baseline", baselineY: Math.round(baseY),
      note: "the big figure, as a HEIGHT. It sets the scale and everything beside it is measured against the same one — that shared scale is the entire point of the plate.",
    });
    P.slot("anchor-label", cx(0) - Math.round(gut * 0.1), baseY + u, colW + Math.round(gut * 0.2), blockH(roles.anchorLabel, 2), { align: "left", role: "anchorLabel" });
    for (let i = 1; i <= refs; i++) {
      P.slot(`ref-${i}`, cx(i), plotT, colW, baseY - plotT, {
        role: "ref", region: true, growth: "up-from-baseline", baselineY: Math.round(baseY),
        note: "a human-sized comparison, on the anchor's scale. If it is drawn to its own scale the plate says nothing.",
      });
      P.slot(`ref-label-${i}`, cx(i) - Math.round(gut * 0.1), baseY + u, colW + Math.round(gut * 0.2), blockH(roles.refLabel, 2), { align: "left", role: "refLabel" });
    }
    P.meta.columns = [];
    for (let i = 0; i < cols; i++) P.meta.columns.push({ x: cx(i), w: colW, role: i ? "ref-" + i : "anchor" });
    P.meta.scaleNote = "ONE scale across every column, and the renderer must not normalise each to its own height. The whole argument is that the reference is small next to the anchor — rescaling them to fill the plot destroys it and would look tidier, which is how it would get done by accident.";
    P.slot("caption", L, h - (land ? 130 : 200), R - L, blockH(roles.caption, 1), { align: "left", role: "caption" });
    return P;
  }

  // ---------------- the receipt — §2.8 ----------------
  // Costs as a till roll, torn at the bottom edge. Tactile, faintly funny, and it
  // turns an income statement into an OBJECT rather than a table.
  function receipt(o) {
    const land = o.w > o.h, w = o.w, h = o.h, p = o.pal;
    const lines = o.lines;
    const roles = {
      kicker: TR.kicker,
      head: { font: "Courier Prime", size: land ? 34 : 30, weight: 700, colour: "structure", tracking: "0.08em", maxChars: 22 },
      item: { font: "Courier Prime", size: land ? 27 : 25, weight: 400, colour: "structure", maxChars: 22 },
      itemBold: { font: "Courier Prime", size: land ? 27 : 25, weight: 700, colour: "structure", maxChars: 22 },
      amount: { font: "Courier Prime", size: land ? 27 : 25, weight: 700, colour: "structure", maxChars: 10 },
      total: { font: "Courier Prime", size: land ? 38 : 34, weight: 700, colour: "structure", maxChars: 10 },
      foot: { font: "Courier Prime", size: 22, weight: 400, colour: "structure", opacity: 0.7, maxChars: 30 },
    };
    const P = base(o, "receipt-" + lines, roles);
    P.meta.family = "paper";
    P.meta.lines = lines;
    const u = unitOf(h);
    // The roll is a fixed narrow column whatever the aspect — a till roll that
    // fills a 16:9 frame is a poster, not a receipt.
    const rollW = Math.round(land ? h * 0.46 : w * 0.62);
    const x = Math.round((w - rollW) / 2);
    const top = Math.round(h * (land ? 0.10 : 0.16));
    const rowH = Math.round(u * 2.5);
    const bodyTop = top + Math.round(u * 5.5);
    const bot = bodyTop + rowH * lines + Math.round(u * 6);
    // the roll itself
    P.colourAdd(H.breathe(function () {
      return H.hatch(H.polyRect(x, top, rollW, bot - top), { color: p.ground2, opacity: 0.3, gap: 7, width: 11, angle: -2, over: 14, seed: 681 });
    }));
    P.inkAdd(H.breathe(function () {
      return H.stroke([{ x: x, y: top }, { x: x, y: bot }], { stroke: p.structure, width: 2.6, opacity: 0.5, amp: 2.4, over: 5, seed: 682 });
    }));
    P.inkAdd(H.breathe(function () {
      return H.stroke([{ x: x + rollW, y: top }, { x: x + rollW, y: bot }], { stroke: p.structure, width: 2.6, opacity: 0.5, amp: 2.4, over: 5, seed: 683 });
    }));
    // THE TORN EDGE. Drawn, not a slot: a tear is the object, not the data.
    const teeth = 18, tw = rollW / teeth, pts = [];
    for (let i = 0; i <= teeth; i++) pts.push({ x: x + tw * i, y: bot + (i % 2 ? u * 0.55 : -u * 0.2) });
    P.inkAdd(H.breathe(function () {
      return H.stroke(pts, { stroke: p.structure, width: 2.8, opacity: 0.72, amp: 1.8, over: 4, seed: 684 });
    }));
    // THE KICKER BELONGS TO THE PLATE, NOT TO THE ROLL.
    //
    // It was given the roll's width, which is ~497 canvas units on a 16:9 plate —
    // and a kicker at 28px Courier needs roughly 670 to hold the length the role
    // declares. So a normal-length kicker wrapped to two lines in a one-line box.
    // Found by the §0.3 pass with real words in it; invisible with short ones,
    // which is exactly why that pass exists.
    //
    // The roll is narrow because a till roll that fills the frame is a poster. The
    // kicker has no such constraint: it is a label for the plate, there is empty
    // ground either side of the roll, and it takes the full text column.
    const kickL = land ? 150 : 72;
    P.slot("kicker", kickL, top - u * 2.4, w - kickL * 2, blockH(roles.kicker, 1), { align: "left", role: "kicker" });
    P.slot("head", x + u, top + u, rollW - u * 2, blockH(roles.head, 1), { align: "center", role: "head" });
    P.slot("takings", x + u, top + u + blockH(roles.head, 1) + u * 0.4, rollW - u * 2, blockH(roles.amount, 1), { align: "center", role: "amount" });
    leader(P, x + u, x + rollW - u, bodyTop - u * 0.8, 690, 0.3);
    for (let i = 1; i <= lines; i++) {
      const y = bodyTop + rowH * (i - 1);
      P.slot(`label-${i}`, x + u, y, rollW * 0.6 - u, rowH - 4, { align: "left", role: "item" });
      P.slot(`line-${i}`, x + rollW * 0.6, y, rollW * 0.4 - u, rowH - 4, { align: "right", role: "amount" });
    }
    const ly = bodyTop + rowH * lines;
    H.pin(function () { P.inkAdd(H.line(x + u, ly + u * 0.6, x + rollW - u, ly + u * 0.5, { stroke: p.structure, width: 3, opacity: 0.7, amp: 2, over: 6, seed: 692 })); });
    P.slot("left", x + u, ly + u * 1.4, rollW - u * 2, blockH(roles.total, 1), { align: "right", role: "total" });
    P.slot("footnote", x + u, ly + u * 1.4 + blockH(roles.total, 1), rollW - u * 2, blockH(roles.foot, 1), { align: "center", role: "foot" });
    P.meta.highlight = {
      slot: "highlight-index",
      note: "1-based index of the line that is the point, or 0 for none. The bot sets it and the renderer sets THAT line in the itemBold role — one plate, not a second plate per highlightable line. A highlight is a weight change, never a colour: the receipt has no direction in it.",
      roles: ["item", "itemBold"],
    };
    P.slot("highlight-index", x, ly, 0, 0, { role: "control", region: true, note: "not drawn. See meta.highlight." });
    return P;
  }

  // ---------------- two-track timeline — §2.9 ----------------
  // What they said along the top rail, what happened along the bottom, and a mark
  // where the two diverge. structure/timeline has ONE rail; a contradiction needs
  // two, and putting the second one underneath is what makes the gap legible as a
  // gap rather than as a longer list.
  function saidHappened(o) {
    const land = o.w > o.h, w = o.w, h = o.h, p = o.pal;
    const n = o.events;
    const roles = {
      kicker: TR.kicker, caption: TR.caption,
      date: { font: "Courier Prime", size: land ? 28 : 25, weight: 700, colour: "structure", maxChars: 8 },
      said: { font: "Archivo Narrow", size: land ? 28 : 25, weight: 600, colour: "otherParty", maxLines: 3, maxCharsPerLine: land ? 24 : 20 },
      happened: { font: "Archivo Narrow", size: land ? 28 : 25, weight: 600, colour: "structure", maxLines: 3, maxCharsPerLine: land ? 24 : 20 },
      rail: { font: "Archivo Narrow", size: land ? 26 : 24, weight: 700, colour: "structure", opacity: 0.7, tracking: "0.08em", maxChars: 16 },
    };
    const P = base(o, "said-happened-" + n, roles);
    P.meta.family = "structure";
    P.meta.events = n;
    const u = unitOf(h), L = land ? 200 : 80, R = w - (land ? 150 : 72);
    P.slot("kicker", L, land ? 92 : 200, R - L, blockH(roles.kicker, 1), { align: "left", role: "kicker" });
    const midY = Math.round(h * (land ? 0.5 : 0.46));
    const gap = Math.round(h * (land ? 0.12 : 0.09));
    const saidY = midY - gap, hapY = midY + gap;
    // Two rails. PINNED: they are the time axis, and an event is read off them.
    H.pin(function () {
      P.inkAdd(H.line(L, saidY, R, saidY - 3, { stroke: p.structure, width: 3.6, opacity: 0.62, amp: 2.6, over: 10, seed: 701 }));
      P.inkAdd(H.line(L, hapY, R, hapY - 3, { stroke: p.structure, width: 4.6, opacity: 0.92, amp: 3, over: 12, seed: 702 }));
    });
    /* LEGACY PASS, rebuild-21: the rail names sat in the left gutter, x 20 in
     * 16:9 and 4 in 9:16, outside the 5% safe margin and too narrow for
     * "WHAT HAPPENED" at rail size. Each name now heads its own track: above the
     * said row, below the happened row, flush with the rails' left end. */
    const railH = blockH(roles.rail, 1), railW = Math.round((R - L) * 0.5);
    P.slot("rail-said", L, Math.round(saidY - u * 1.2 - blockH(roles.said, 3) - u * 0.4 - railH), railW, railH, { align: "left", role: "rail" });
    P.slot("rail-happened", L, Math.round(hapY + u * 1.2 + blockH(roles.happened, 3) + u * 0.4), railW, railH, { align: "left", role: "rail" });
    const step = (R - L) / n, colW = Math.round(step * 0.88);
    for (let i = 1; i <= n; i++) {
      const cx = Math.round(L + step * (i - 0.5));
      const x = cx - Math.round(colW / 2);
      H.pin(function () {
        P.inkAdd(H.outline(ellipse(cx, saidY, u * 0.5, u * 0.5, 10, 0.08, 710 + i), { stroke: p.structure, width: 2.6, opacity: 0.6, amp: 1.2, over: 3, seed: 712 + i }));
        P.colourAdd(H.hatch(ellipse(cx, hapY, u * 0.55, u * 0.55, 10, 0.08, 720 + i), { color: p.structure, opacity: 0.8, gap: 3, width: 5, angle: -40, seed: 722 + i }));
      });
      P.slot(`date-${i}`, x, midY - blockH(roles.date, 1) / 2, colW, blockH(roles.date, 1), { align: "center", role: "date" });
      P.slot(`said-${i}`, x, saidY - u * 1.2 - blockH(roles.said, 3), colW, blockH(roles.said, 3), { align: "center", role: "said" });
      P.slot(`happened-${i}`, x, hapY + u * 1.2, colW, blockH(roles.happened, 3), { align: "center", role: "happened" });
      P.slot(`diverge-${i}`, x, saidY, colW, hapY - saidY, {
        role: "diverge", region: true, optional: true,
        note: "set only where the two tracks CONTRADICT each other. The renderer draws the tie between the pair in `attention`. Leaving every one of them set would make the plate shout at every column and say nothing — the mark means something because it is rare.",
      });
    }
    P.slot("caption", L, h - (land ? 130 : 200), R - L, blockH(roles.caption, 1), { align: "left", role: "caption" });
    P.meta.railNote = "the SAID rail is drawn lighter and its marks are hollow; the HAPPENED rail is heavier and its marks are filled. A claim and an outcome are not the same kind of fact and the plate should not draw them as though they were.";
    return P;
  }

  // ---------------- sensitivity — §2.10 ----------------
  // Three by three outcomes with the axes labelled and one cell markable. "Cheap
  // only if the margin keeps climbing on eight percent growth" is a sentence in
  // the sample script, and it is a picture.
  function sensitivity(o) {
    const land = o.w > o.h, w = o.w, h = o.h, p = o.pal;
    const roles = {
      kicker: TR.kicker, caption: TR.caption,
      axisTitle: { font: "Archivo Narrow", size: land ? 27 : 25, weight: 700, colour: "structure", opacity: 0.72, tracking: "0.08em", maxChars: 20 },
      head: { font: "Archivo Narrow", size: land ? 30 : 27, weight: 600, colour: "structure", maxChars: 8 },
      cell: { font: "Courier Prime", size: land ? 44 : 36, weight: 700, colour: "structure", maxChars: 6 },
    };
    const P = base(o, "sensitivity", roles);
    P.meta.family = "structure";
    /* LEGACY PASS, rebuild-21: the row labels started at x 20 (16:9) and 4 (9:16),
     * inside the 5% margin, and in 16:9 the column axis title ran into the column
     * heads under it. Row labels now start at the margin — portrait gives the
     * grid 54 units for it — and the axis title stacks above the heads. */
    const u = unitOf(h), L = land ? 320 : 150, R = w - (land ? 220 : 72);
    const rowX = land ? 96 : 56, rowW = L - rowX - (land ? 20 : 8);
    P.slot("kicker", L, land ? 92 : 200, R - L, blockH(roles.kicker, 1), { align: "left", role: "kicker" });
    const gridT = Math.round(h * (land ? 0.28 : 0.34));
    const gridB = Math.round(h * (land ? 0.80 : 0.70));
    const cw = (R - L) / 3, ch = (gridB - gridT) / 3;
    field(P, L, gridT, R - L, gridB - gridT, 731, 0.26);
    // The grid lines are separators between cells, not a scale — nothing is
    // measured off them, so they breathe.
    for (let i = 0; i <= 3; i++) {
      const gx = L + cw * i, gy = gridT + ch * i;
      P.inkAdd(H.breathe(function () { return H.line(gx, gridT, gx, gridB, { stroke: p.structure, width: i === 0 || i === 3 ? 3.6 : 2, opacity: i === 0 || i === 3 ? 0.85 : 0.34, amp: 2.4, over: 8, seed: 740 + i }); }));
      P.inkAdd(H.breathe(function () { return H.line(L, gy, R, gy, { stroke: p.structure, width: i === 0 || i === 3 ? 3.6 : 2, opacity: i === 0 || i === 3 ? 0.85 : 0.34, amp: 2.4, over: 8, seed: 750 + i }); }));
    }
    const axisY = Math.round(Math.min(gridT - u * 3.2, gridT - u * 1.6 - blockH(roles.axisTitle, 1) - u * 0.3));
    P.slot("col-axis", L, axisY, R - L, blockH(roles.axisTitle, 1), { align: "center", role: "axisTitle" });
    P.slot("row-axis", rowX, axisY, rowW, blockH(roles.axisTitle, 1), { align: "right", role: "axisTitle" });
    for (let c = 1; c <= 3; c++) {
      P.slot(`col-${c}`, L + cw * (c - 1), gridT - u * 1.6, cw, blockH(roles.head, 1), { align: "center", role: "head" });
      P.slot(`row-${c}`, rowX, gridT + ch * (c - 1) + ch / 2 - blockH(roles.head, 1) / 2, rowW, blockH(roles.head, 1), { align: "right", role: "head" });
      for (let r = 1; r <= 3; r++) {
        P.slot(`cell-${r}-${c}`, L + cw * (c - 1), gridT + ch * (r - 1) + ch / 2 - blockH(roles.cell, 1) / 2, cw, blockH(roles.cell, 1), { align: "center", role: "cell", region: true });
      }
    }
    P.meta.mark = {
      slots: ["mark-row", "mark-col"],
      note: "1-3 each, or 0 for no mark. The renderer rings THAT cell in `attention`. Two integers rather than a marked cell slot, because the mark is a claim about which scenario the script is arguing for — it moves with the voice-over, and a plate per cell would be nine plates.",
    };
    // DROP TEN: declared as CONTROL CHANNELS rather than as zero-sized regions.
    // Both carried region: true at 0x0 with "not drawn" in a note — and "not
    // drawn" and "zero-sized" are different claims, of which the plate published
    // the second. A renderer computing a fill area got zero, one scaling into the
    // box divided by zero, and one trusting the note got no help. It reported
    // success either way. These two slots carry two INTEGERS; x,y locate the grid
    // they index and w/h are meaningless by design, which is now said in the
    // field rather than implied by a zero.
    const CTRL = { role: "control", region: true, control: true, drawn: false,
      dimensionless: true, note: "A CONTROL CHANNEL, NOT AN AREA. Carries an integer 1-3 (or 0 for no mark) naming which row/column the script is arguing about; the renderer rings that cell in 'attention'. w and h are 0 because this slot has no extent — do not compute a fill area or a scale from it. x,y locate the grid it indexes. See meta.mark." };
    P.slot("mark-row", L, gridT, 0, 0, CTRL);
    P.slot("mark-col", L, gridT, 0, 0, CTRL);
    P.slot("caption", L, h - (land ? 130 : 200), R - L, blockH(roles.caption, 1), { align: "left", role: "caption" });
    P.meta.gridNote = "three by three, fixed. A sensitivity table is read by SHAPE — where the outcome flips — and a grid whose dimensions change between chapters cannot be compared with the previous one.";
    return P;
  }

  // ---------------- small multiples — §2.13 ----------------
  // Four or six tiny charts in a grid, each with its own label and series. The
  // "here is everything at once, and only one of them is moving" beat.
  function multiplesGrid(o) {
    const land = o.w > o.h, w = o.w, h = o.h, p = o.pal;
    const n = o.cells;
    const cols = land ? (n === 4 ? 4 : 3) : 2, rows = Math.ceil(n / cols);
    const roles = {
      kicker: TR.kicker, caption: TR.caption,
      tileLabel: { font: "Archivo Narrow", size: land ? 26 : 24, weight: 700, colour: "structure", maxLines: 2, maxCharsPerLine: land ? 16 : 14 },
      tileValue: { font: "Courier Prime", size: land ? 30 : 28, weight: 700, colour: "structure", maxChars: 7 },
    };
    const P = base(o, "multiples-grid-" + n, roles);
    P.meta.family = "charts";
    P.meta.cells = n;
    P.meta.grid = { cols: cols, rows: rows };
    const u = unitOf(h), L = land ? 150 : 72, R = w - (land ? 150 : 72);
    P.slot("kicker", L, land ? 92 : 200, R - L, blockH(roles.kicker, 1), { align: "left", role: "kicker" });
    const gridT = Math.round(h * (land ? 0.26 : 0.30));
    const gridB = Math.round(h * (land ? 0.80 : 0.74));
    const gx = (R - L) / cols, gy = (gridB - gridT) / rows;
    const padX = Math.round(gx * 0.08), padY = Math.round(gy * 0.1);
    P.meta.tiles = [];
    for (let i = 1; i <= n; i++) {
      const c = (i - 1) % cols, r = Math.floor((i - 1) / cols);
      const x = Math.round(L + gx * c + padX), y = Math.round(gridT + gy * r + padY);
      const tw = Math.round(gx - padX * 2), th = Math.round(gy - padY * 2);
      const labH = blockH(roles.tileLabel, 2), valH = blockH(roles.tileValue, 1);
      const plotY = y + labH + Math.round(u * 0.4), plotH = th - labH - valH - Math.round(u * 0.8);
      P.slot(`label-${i}`, x, y, tw, labH, { align: "left", role: "tileLabel" });
      P.slot(`value-${i}`, x, y + th - valH, tw, valH, { align: "left", role: "tileValue" });
      P.slot(`series-${i}`, x, plotY, tw, plotH, {
        role: "series", region: true, points: 6,
        note: "six points, its own vertical scale. Each tile is a SHAPE, not a quantity — the reader is comparing whether one is rising while the others are flat, and forcing a shared scale would flatten every tile whose numbers are small.",
      });
      // NOT PINNED, and this is the one place in the pack where the rule pointed
      // the other way from the instinct. A tile baseline looks like a chart axis,
      // but this plate's own note says each tile is read as a SHAPE rather than a
      // quantity — nobody reads a value off it. Pinning it would have contradicted
      // the manifest one line below.
      P.inkAdd(H.breathe(function () {
        return H.line(x, plotY + plotH, x + tw, plotY + plotH - 2, { stroke: p.structure, width: 2.4, opacity: 0.6, amp: 1.8, over: 6, seed: 760 + i * 7 });
      }));
      P.meta.tiles.push({ i: i, x: x, y: plotY, w: tw, h: plotH });
    }
    P.slot("caption", L, h - (land ? 130 : 200), R - L, blockH(roles.caption, 1), { align: "left", role: "caption" });
    P.meta.scaleNote = "PER-TILE scales, deliberately, and it is the opposite of the rule on figures/scale. There the argument is relative size, so one scale; here the argument is relative SHAPE — which one is moving — so each tile gets its own. Publishing both notes is how the renderer is supposed to tell them apart.";
    return P;
  }

  // ---------------- the whiteboard as a plate — §3.2 ----------------
  // room/whiteboard-wall is a room he STANDS IN. This is a whiteboard where the
  // diagram IS the content, drawn by the same hand that draws everything else —
  // the most on-brand explainer surface the kit can have.
  //
  // Kept genuinely generic per the brief: three or four labelled nodes and their
  // links, not a pre-drawn diagram of one idea. The boxes and the connectors are
  // drawn because a diagram's SHAPE is structural — which things connect to which
  // is the argument's skeleton and is true before any label arrives — and every
  // word in it is a slot.
  //
  // The links are authored as a fixed spine: 1→2→3(→4) left to right, with the
  // last node also tied back to the first when there are four. That is the shape
  // nearly every explainer diagram on this channel actually has, and a plate that
  // let the bot choose arbitrary edges would need an edge-routing renderer, which
  // is a different and much larger problem — the same call as §2.14's map.
  function whiteboard(o) {
    const land = o.w > o.h, w = o.w, h = o.h, p = o.pal;
    const n = o.nodes;
    const roles = {
      kicker: TR.kicker, caption: TR.caption,
      node: { font: "Archivo Narrow", size: land ? 40 : 34, weight: 700, colour: "structure", maxLines: 2, maxCharsPerLine: land ? 14 : 12 },
      link: { font: "Archivo Narrow", size: land ? 26 : 24, weight: 600, colour: "structure", opacity: 0.8, maxLines: 2, maxCharsPerLine: land ? 16 : 13 },
      title: { font: "Archivo Narrow", size: land ? 54 : 46, weight: 700, colour: "structure", tracking: "-.01em", maxLines: 2, maxCharsPerLine: land ? 30 : 22 },
    };
    const P = base(o, "whiteboard-" + n, roles);
    P.meta.family = "structure";
    P.meta.nodes = n;
    const u = unitOf(h), k = land ? w / 1920 : w / 1080;
    const S = inkScale(k);
    const L = land ? 140 : 64, R = w - (land ? 140 : 64);
    // THE BOARD. A whiteboard is a pale panel with a tray and old ghost-erase
    // smears — the smears are what stop it reading as a blank rectangle, and they
    // are texture, so they breathe.
    const bT = Math.round(h * (land ? 0.17 : 0.22)), bB = Math.round(h * (land ? 0.86 : 0.80));
    P.colourAdd(H.breathe(function () {
      return S.hatch(H.polyRect(L - u, bT, R - L + u * 2, bB - bT), { color: p.ground2, opacity: 0.22, gap: 11, width: 16, angle: -2, over: 22, seed: 1101 });
    }));
    P.inkAdd(H.breathe(function () {
      return S.outline(H.polyRect(L - u, bT, R - L + u * 2, bB - bT), { stroke: p.structure, width: 4, opacity: 0.6, amp: 3.2, over: 12, seed: 1102 });
    }));
    for (let i = 0; i < 3; i++) {
      P.colourAdd(H.breathe(function () {
        return S.hatch(ellipse(L + (R - L) * (0.2 + i * 0.31), bT + (bB - bT) * (0.26 + (i % 2) * 0.44), (R - L) * 0.12, (bB - bT) * 0.11, 14, 0.16, 1110 + i * 7), { color: p.ground2, opacity: 0.2, gap: 6, width: 10, angle: -22 + i * 14, over: 9, seed: 1114 + i });
      }));
    }
    // the tray, and a pen on it
    P.inkAdd(H.breathe(function () {
      return S.line(L - u, bB + u * 0.5, R + u, bB + u * 0.42, { stroke: p.structure, width: 5, opacity: 0.7, amp: 2.6, over: 9, seed: 1120 });
    }));
    P.inkAdd(H.breathe(function () {
      return S.line(L + (R - L) * 0.62, bB + u * 0.22, L + (R - L) * 0.73, bB + u * 0.2, { stroke: p.structure, width: 7, opacity: 0.8, amp: 1.6, over: 4, seed: 1121 });
    }));

    P.slot("kicker", L, bT - u * 2.6, R - L, blockH(roles.kicker, 1), { align: "left", role: "kicker" });
    P.slot("title", L + u, bT + u * 1.1, (R - L) * 0.72, blockH(roles.title, 2), { align: "left", role: "title" });

    // Nodes on one rail in landscape, stacked in portrait. A left-to-right chain
    // has no portrait form at four boxes wide, so 9:16 is a re-author down the
    // frame rather than the same row squeezed.
    const rowY = bT + (bB - bT) * 0.62;
    const boxW = land ? Math.round((R - L) / n * 0.72) : Math.round((R - L) * 0.6);
    const boxH = Math.round(land ? boxW * 0.52 : (bB - bT) * 0.13);
    const pos = [];
    for (let i = 0; i < n; i++) {
      if (land) pos.push({ x: Math.round(L + ((R - L) / n) * (i + 0.5) - boxW / 2), y: Math.round(rowY - boxH / 2 + (i % 2 ? u * 1.6 : -u * 1.6)) });
      else pos.push({ x: Math.round(L + (R - L) * (i % 2 ? 0.34 : 0.04)), y: Math.round(bT + (bB - bT) * (0.30 + i * (0.56 / Math.max(1, n - 1))) - boxH / 2) });
    }
    pos.forEach(function (q2, i) {
      P.colourAdd(H.hatch(H.polyRect(q2.x, q2.y, boxW, boxH), { color: p.ground, opacity: 0.92, gap: 8, width: 13, angle: -3, over: 14, seed: 1130 + i * 5 }));
      P.inkAdd(H.breathe(function () {
        return S.outline(H.polyRect(q2.x, q2.y, boxW, boxH), { stroke: p.structure, width: 4.6, opacity: 0.94, amp: 3.4, over: 13, seed: 1136 + i * 5 });
      }));
      P.slot(`node-${i + 1}`, q2.x + u * 0.6, q2.y + boxH * 0.5 - blockH(roles.node, 2) / 2, boxW - u * 1.2, blockH(roles.node, 2), { align: "center", role: "node" });
    });
    // the links, and a label slot on each
    P.meta.links = [];
    for (let i = 0; i < n - 1; i++) {
      const a = pos[i], b = pos[i + 1];
      const ax = land ? a.x + boxW : a.x + boxW * 0.5, ay = land ? a.y + boxH * 0.5 : a.y + boxH;
      const bx = land ? b.x : b.x + boxW * 0.5, by = land ? b.y + boxH * 0.5 : b.y;
      P.inkAdd(H.breathe(function () {
        return S.stroke([{ x: ax, y: ay }, { x: (ax + bx) / 2, y: (ay + by) / 2 }, { x: bx, y: by }], { stroke: p.structure, width: 3.6, opacity: 0.85, amp: 2.8, over: 7, seed: 1150 + i * 4 });
      }));
      // the head, drawn: an arrow means direction and direction is structure
      const dx = bx - ax, dy = by - ay, dl = Math.hypot(dx, dy) || 1;
      const hx = bx - (dx / dl) * u * 0.9, hy = by - (dy / dl) * u * 0.9;
      P.inkAdd(H.breathe(function () {
        return S.stroke([
          { x: hx - (dy / dl) * u * 0.5, y: hy + (dx / dl) * u * 0.5 },
          { x: bx, y: by },
          { x: hx + (dy / dl) * u * 0.5, y: hy - (dx / dl) * u * 0.5 },
        ], { stroke: p.structure, width: 3.6, opacity: 0.85, amp: 1.6, over: 3, seed: 1156 + i * 4 });
      }));
      const lw2 = Math.round(Math.abs(land ? bx - ax : boxW) * 0.9) || Math.round(u * 8);
      P.slot(`link-${i + 1}`, Math.round((ax + bx) / 2 - lw2 / 2), Math.round((ay + by) / 2 - blockH(roles.link, 2) - u * 0.4), lw2, blockH(roles.link, 2), { align: "center", role: "link" });
      P.meta.links.push({ from: i + 1, to: i + 2, label: "link-" + (i + 1) });
    }
    P.slot("caption", L, h - (land ? 92 : 150), R - L, blockH(roles.caption, 1), { align: "left", role: "caption" });
    P.meta.shapeNote = "a fixed spine: node 1 to 2 to 3 (to 4), left to right in 16:9 and down the frame in 9:16. Arbitrary edges would need an edge-routing renderer, which is a different and much larger problem — the same call as §2.14 being a bar rather than a map. If a script needs a shape this cannot draw, that is a new plate, not an argument to this one.";
    P.meta.genericNote = "nothing on it is a diagram of any particular idea. Three or four labelled boxes and their links, every word a slot.";
    return P;
  }

  // ---------------- charts ----------------
  // Axes, ticks, gridlines and frame are drawn. Code draws only the data path
  // inside plot-area. Every column/point gets its own slot.
  // One callout instead of a row of figures that will not fit. Not a fallback
  // with a shrug: the last quarter is the one the script is talking about, and
  // the other seven are a shape.
  function valueCallout(P, x0, y0, x1, land) {
    P.slot("value-last", x1 - (land ? 300 : 220), y0 - 50, land ? 300 : 220, 46, {
      align: "right", role: "value",
      note: "the latest period's figure, and the only one. Per-column values are not published at this column count in this aspect — the box measures under the six-character floor, and an over-budget fill does not render. Put the rest in the voice-over.",
    });
  }

  // What a quarterly plate says about itself. The label SHAPE is the part a
  // renderer gets wrong silently: "Q3'25" is five characters where "2025" is
  // four, and a compositor that formats quarters as "Q3 2025" (seven) walks
  // straight into the budget on the narrow aspects.
  function quarterly(P, land, kind) {
    P.meta.periods = "quarters";
    P.meta.periodFormat = "Q3'25 — quarter, apostrophe, two-digit year. FIVE characters. Not 'Q3 2025' and not '2025 Q3': the head boxes are budgeted at this column count, and a seven-character label is an over-budget fill, which does not render at all.";
    P.meta.argument = kind === "bars"
      ? "eight quarters as columns. The sheet the pipeline now loads, at the count it loads it — two years of quarters, which is the shortest span in which a seasonal pattern is visible at all."
      : "eight quarters as a path. Same data as bars-8q; the line is for when the shape between quarters is the point rather than the size of each one.";
    P.meta.seasonalityWarning = "EIGHT QUARTERS IS TWO YEARS, so Q4 appears twice and so does Q1. A rise from Q3 to Q4 on this plate is not growth until it has been read against the other Q4 — which is figures/qoq-yoy's whole job. This plate does not make that comparison and must not be captioned as if it had.";
    P.meta.seriesNote = "one series, subject colour. No up, no down: a quarter is not a verdict.";
  }

  // ---------------- §2.2 · the seasonality pair ----------------
  /* figures/qoq-yoy — AN EDITORIAL INSTRUMENT, NOT A CHART.

     A quarter can be read two ways and they routinely disagree: against the
     previous quarter (is it moving?) and against the same quarter a year ago (is
     it actually moving, or is this just what Q4 always looks like?). A retailer's
     Q4 beats its Q3 every single year, and reporting that as growth is what this
     channel exists to puncture.

     So the plate presents BOTH comparisons at once, labelled, as a pair — and it
     cannot present one. There is no slot on it for a blended growth figure, which
     is the same kind of structural refusal as there being no way to emit a text
     node: a rule nothing can accidentally break beats a rule everyone agrees with.

     EQUAL WEIGHT IS GEOMETRY, NOT INTENT. The two cells come out of one
     expression with only an offset differing, so they are congruent by
     construction rather than by care, and preflight asserts it. If one read as
     the headline and the other as a footnote, the plate would have taken a side
     the data has not.

     THE ARRANGEMENT DIFFERS BY ASPECT, and that is the one real decision here.
     16:9 sets the cells side by side. 9:16 STACKS them: two 470-unit cells side
     by side in portrait would force the delta type down two steps, and deltas
     that small lose the pair its weight against the figure above — the same
     failure from the other direction. Stacked congruent cells keep both. Reading
     order is the nearer comparison first, which is as arbitrary as
     left-before-right and no more so.

     Sign-agnostic, for the reason waterfall is: a delta can be either sign, and
     a plate that pre-colours one has argued ahead of the voice. */
  function quarterPair(o) {
    const land = o.w > o.h, w = o.w, h = o.h, p = o.pal;
    const roles = {
      kicker: TR.kicker, caption: TR.caption, unit: TR.detail,
      // The quarter's own figure: the subject of the plate, and the only thing on
      // it that is a quantity rather than a comparison.
      // DROP EIGHT: portrait stepped 220 -> 190. At 220u the derived box held SEVEN
      // characters and "$15.64bn" is eight, so the plate rendered blank where the
      // quarter goes — an over-budget fill does not render. Two decimals in billions
      // is what a real script writes, and render-scale.html §10 is where it was
      // caught. The figure is still ~4x the delta beside it, which is the weighting
      // the plate's argument needs; the delta is untouched.
      figure: { font: "Courier Prime", size: 190, weight: 700, colour: "structure", maxChars: 7 },
      // ONE role for both deltas. Two roles is how they stop being equal.
      delta: { font: "Courier Prime", size: land ? 110 : 130, weight: 700, colour: "structure", maxChars: 7 },
      deltaLabel: { font: "Archivo Narrow", size: land ? 34 : 36, weight: 600, colour: "structure", opacity: 0.88, tracking: "0.03em", maxLines: 2, maxCharsPerLine: land ? 18 : 22 },
    };
    const P = base(o, "qoq-yoy", roles);
    P.meta.family = "figures";
    const u = unitOf(h);
    const L = land ? 150 : 72, R = w - (land ? 150 : 72);
    const kickY = land ? 88 : 196, kickH = blockH(roles.kicker, 1);
    P.slot("kicker", L, kickY, (R - L) * 0.66, kickH, { align: "left", role: "kicker" });
    P.slot("unit", L + (R - L) * 0.68, kickY, (R - L) * 0.32, kickH, { align: "right", role: "unit" });

    const figY = kickY + kickH + u * 2, figH = blockH(roles.figure, 1);
    P.slot("figure", L, figY, R - L, figH, { align: "left", role: "figure" });

    // The rule under the figure separates the quantity from the two readings of
    // it, so it breathes. Nobody reads a value off it.
    const ruleY = Math.round(figY + figH + u * 1.4);
    P.inkAdd(H.breathe(function () {
      return H.line(L, ruleY, R, ruleY - 2, { stroke: p.structure, width: 3.4, opacity: 0.5, amp: 2.4, over: 9, seed: 411 });
    }));

    const labH = blockH(roles.deltaLabel, 2), delH = blockH(roles.delta, 1);
    const pad = Math.round(u * 1.2);
    const cellH = pad * 2 + labH + Math.round(u * 0.8) + delH;
    const gut = Math.round(u * (land ? 2.4 : 2.0));
    const cellW = land ? Math.round((R - L - gut) / 2) : (R - L);
    const top = Math.round(ruleY + u * 2.2);

    // ONE expression, two cells.
    const boxes = [];
    ["qoq", "yoy"].forEach(function (nm, i) {
      const cx = land ? L + i * (cellW + gut) : L;
      const cy = land ? top : top + i * (cellH + gut);
      boxes.push({ name: nm, x: Math.round(cx), y: Math.round(cy), w: cellW, h: cellH });
      // The cell edge is furniture: it groups, it is not measured against.
      P.inkAdd(H.breathe(function () {
        return H.outline(H.polyRect(cx, cy, cellW, cellH), { stroke: p.structure, width: 3, opacity: 0.42, amp: 2.6, over: 10, seed: 420 + i * 17 });
      }));
      P.slot(nm + "-label", cx + pad, cy + pad, cellW - pad * 2, labH, { align: "center", role: "deltaLabel" });
      P.slot(nm, cx + pad, cy + pad + labH + Math.round(u * 0.8), cellW - pad * 2, delH, { align: "center", role: "delta" });
    });

    P.slot("caption", L, h - (land ? 130 : 200), R - L, blockH(roles.caption, 1), { align: "left", role: "caption" });

    P.meta.pair = {
      arrangement: land ? "side-by-side" : "stacked",
      cells: boxes,
      congruent: boxes[0].w === boxes[1].w && boxes[0].h === boxes[1].h,
      typeRole: "both deltas are set in ONE role (delta) and both labels in ONE role (deltaLabel). Two roles is how a pair stops being a pair.",
      note: land
        ? "side by side, equal boxes, equal type. Neither position is the headline."
        : "stacked, equal boxes, equal type. Side-by-side halves in 9:16 would force the deltas down two type steps, which costs the pair its weight against the figure — the same failure from the other direction. Order is the nearer comparison first, which is as arbitrary as left-before-right.",
    };
    P.meta.refusesSingleFigure = "THERE IS NO SLOT FOR A BLENDED GROWTH FIGURE, and that absence is the plate. A quarter read against the previous quarter and against the same quarter a year ago are two statements that routinely disagree; resolving them into one number is the failure this plate exists to prevent, not an output it declines to offer. A script that wants one growth number wants figures/big-number.";
    P.meta.signAgnostic = "Neither delta carries direction. No colour, no arrow, no order preference, and the two cells are identical, so a fall and a rise are drawn the same. Sign comes from the value the compositor fills; the script decides what is bad. Same call as figures/waterfall.";
    P.meta.labelContract = "the -label slots carry the BASIS, not a verdict: 'vs Q2 2025' and 'vs Q3 2024', or 'quarter on quarter' and 'year on year'. Two lines each, budgeted. A label reading 'growth' on one cell and 'seasonal' on the other breaks the pair as surely as a colour would.";
    return P;
  }

  // ---------------- §2.3 · seasonality ----------------
  /* charts/seasonality-{4,6}y — Q1 to Q4 across, one series per year.

     Seasonality stops being an argument the script has to make and becomes a
     shape on screen: four years of identical December humps is self-evident in a
     way no sentence is.

     Its own author rather than a chartFrame type, because the horizontal is not a
     period axis — it is four positions that every series shares, and the series
     are the years. That inverts what a column means, which is the one thing
     chartFrame's slot naming cannot absorb: `bar-3` would be ambiguous between
     "Q3" and "the third year", and an ambiguous slot name on a data plate is how
     a renderer fills the right number into the wrong column.

     COUNT VARIANTS ON YEARS. The quarters are always four. */
  function seasonality(o) {
    const p = o.pal, w = o.w, h = o.h, land = w > h;
    const s = SURFACES[p.surfaceKey];
    const Y = o.years;
    const P = H.Plate({
      key: o.key, w, h, seed: o.seed, pal: p,
      meta: {
        aspect: land ? "16x9" : "9x16", family: "charts", type: "seasonality-" + Y + "y",
        columns: 4, quarters: 4, years: Y,
        typeRoles: {
          unit: { font: "Courier Prime", size: 26, weight: 400, colour: "structure", opacity: 0.72, tracking: "0.04em", maxChars: 46 },
          period: { font: "Archivo Narrow", size: land ? 30 : 28, weight: 600, colour: "structure", maxChars: 4 },
          axis: { font: "Courier Prime", size: land ? 26 : 24, weight: 400, colour: "structure", opacity: 0.7, maxChars: 7 },
          series: { font: "Courier Prime", size: land ? 28 : 26, weight: 700, colour: "structure", maxChars: 5 },
        },
        seriesRoles: { subject: "structure", neutral: "neutralData", mark: "attention" },
      },
    });
    P.colourAdd(H.breathe(function () { return surfaceFurniture(P, s); }));
    // A deeper top margin than chartFrame: the legend row is the one thing this
    // plate has that the others do not, and it gets its own band rather than
    // sharing the value row's.
    const m = land ? { l: 200, r: 130, t: 290, b: 170 } : { l: 150, r: 90, t: 430, b: 420 };
    const x0 = m.l, x1 = w - m.r, y0 = m.t, y1 = h - m.b;
    P.slot("unit", land ? 118 : 60, land ? 92 : 200, x1 - (land ? 118 : 60), land ? 42 : 50, { align: "left", role: "unit" });
    P.slot("plot-area", x0, y0, x1 - x0, y1 - y0, { role: "plot-area", container: true, note: "code draws the data in here only" });

    // gridlines breathe, axes are pinned — §1.5, same as every chart
    const gl = 4;
    for (let i = 0; i <= gl; i++) {
      const y = y1 - ((y1 - y0) / gl) * i;
      if (i > 0) P.inkAdd(H.breathe(function () {
        return H.line(x0, y, x1, y, { stroke: p.structure, width: 1.8, opacity: 0.2, amp: 2.6, over: 7, seed: 610 + i * 7 });
      }));
      P.slot(`y-${i + 1}`, x0 - (land ? 160 : 130), i === gl ? y + 6 : y - 26, land ? 140 : 112, 52, { align: "right", role: "axis" });
    }
    H.pin(function () {
      P.inkAdd(H.line(x0, y0 - 16, x0, y1, { stroke: p.structure, width: land ? 4.6 : 4, opacity: 0.9, amp: 3, over: 11, seed: 621 }));
      P.inkAdd(H.line(x0, y1, x1 + 18, y1, { stroke: p.structure, width: land ? 4.6 : 4, opacity: 0.9, amp: 3, over: 11, seed: 622 }));
    });

    // Four quarter bands, Y columns inside each — one per year, oldest left.
    const bandW = (x1 - x0) / 4;
    const inner = bandW * 0.78;
    const colW = inner / Y;
    const colGap = Math.max(2, Math.round(colW * 0.14));
    P.meta.groups = [];
    for (let q = 1; q <= 4; q++) {
      const bx = x0 + bandW * (q - 1);
      const ix = bx + (bandW - inner) / 2;
      // a band boundary is a tick: it says where a quarter IS, so it is pinned
      H.pin(function () { P.inkAdd(H.line(bx, y1, bx, y1 + 16, { stroke: p.structure, width: 2.4, opacity: 0.75, amp: 1.2, seed: 630 + q * 11 })); });
      P.slot(`head-q${q}`, bx, y1 + 30, bandW, 52, { align: "center", role: "period", note: "Q1 … Q4. Always four, and never a year." });
      const cols = [];
      for (let n = 1; n <= Y; n++) {
        const cxx = ix + colW * (n - 1) + colGap / 2, cw = colW - colGap;
        P.slot(`y${n}-q${q}`, cxx, y0, cw, y1 - y0, {
          role: "bar", region: true, growth: "up-from-baseline", baselineY: Math.round(y1),
          year: n, quarter: q, anchorX: Math.round(cxx + cw / 2),
        });
        cols.push({ year: n, x: Math.round(cxx), w: Math.round(cw), anchorX: Math.round(cxx + cw / 2) });
      }
      P.meta.groups.push({ quarter: q, x: Math.round(bx), w: Math.round(bandW), columns: cols });
    }
    H.pin(function () { P.inkAdd(H.line(x1, y1, x1, y1 + 16, { stroke: p.structure, width: 2.4, opacity: 0.75, amp: 1.2, seed: 679 })); });

    // The legend row: one slot per year, in series order. It is the only place on
    // the plate that says which column is which, so it is not optional.
    const legW = (x1 - x0) / Y;
    for (let n = 1; n <= Y; n++) {
      P.slot(`series-${n}`, x0 + legW * (n - 1), y0 - (land ? 78 : 92), legW, 50, {
        align: "center", role: "series", year: n,
        note: "the year this series is, e.g. 2025. Position in the legend row matches position within every quarter band.",
      });
    }

    P.meta.argument = "four quarters across, " + Y + " years deep. The same December hump repeated is an argument the plate makes on its own — the script stops having to assert seasonality and starts pointing at it.";
    P.meta.seriesOrder = "OLDEST LEFT, NEWEST RIGHT, in every band, and series-1 is the oldest. A renderer that fills them the other way round inverts the reading with the furniture unchanged, which is the one error this plate cannot show you.";
    P.meta.seriesColour = "ONE HUE, VALUE RAMPED: oldest lightest, newest at full subject ink. Y distinct series colours is what this plate refuses — six hues on one plot is a different channel, and this kit's own doctrine is light as value falloff rather than as new colour. The ramp also does the editorial work for free: the year the script is about is the darkest thing on the plot.";
    P.meta.rendererNote = "BARS OR A LINE, from the same geometry. Fill each y{n}-q{q} region for grouped columns, or join the four anchorX points of one year for a line per year. meta.groups carries every column's x, width and anchor already measured, so neither route re-derives the grid — the property that keeps a seasonality plate and a bars-8q in the same cut.";
    P.meta.zeroNote = "a missing quarter is a GAP, not a zero. Draw nothing in that region and leave its head label — a zero-height bar on the baseline reads as 'they sold nothing', which is a different and much stronger claim than 'we do not have it'.";
    // MEASURED, AND SAID OUT LOUD WHERE IT IS TIGHT. Y x 4 columns is 24 bars on
    // the 6y plate, and in 9:16 that is a 23-unit column — 46 delivered pixels at
    // exportScale 2. It draws and it is legible on a desktop; on a phone it is
    // the thinnest data mark in the library. The plate publishes the number
    // rather than the judgement, so a shot template can decide.
    const drawnW = Math.round(colW - colGap);
    P.meta.columnWidth = { units: drawnW, deliveredPx: drawnW * 2 };
    if (drawnW < 30) P.meta.crowded = "a " + drawnW + "-unit column (" + drawnW * 2 + "px delivered) is the thinnest data mark in the kit. It renders and it is legible at desk distance; for a SHORT prefer seasonality-4y, whose column is 35 units in this aspect. Not a defect — a measured limit of " + (Y * 4) + " bars in a 9:16 plot.";
    return P;
  }

  // ---------------- §3.1 · language shift ----------------
  /* structure/language-shift — THE SAME THING, DESCRIBED TWO DIFFERENT WAYS, A
     YEAR APART.

     The filing reader now produces what CHANGED between this year's report and
     last year's: risk factors that appeared or vanished, management language that
     shifted, segments that moved. That output had nowhere to land.

     `structure/said-happened` is close and is not it: that is a two-track
     timeline of claim against outcome, N events wide. This is narrower and it is
     one pair — the same statement in two versions.

     THE TWO BLOCKS ARE STACKED, NOT SIDE BY SIDE, and that is the whole design.
     Side by side is what `figures/compare-side` is, and it reads as two claims
     about two things. Stacked, at one left edge, at one width, in one type role,
     with one rail down the side joining them, it reads as one statement written
     twice — which is what the data actually is.

     IT ENFORCES THE PHRASE RATHER THAN INVITING A PARAGRAPH. A language shift is
     four or five words ("committed to disciplined growth" becoming "focused on
     cash generation"), and the failure mode is a compositor pasting in the whole
     sentence from the filing. So the type is set LARGE and the box holds two
     lines: measured, that is ~30 characters a line in 16:9 and ~21 in 9:16, so a
     paragraph does not fit and does not render. The constraint is the plate's,
     not the writer's discipline.

     AND IT DOES NOT DRAW THE DIFF. No strike-through on the old, no highlight on
     the new. That is the annotations family's job, applied by the compositor when
     the script asks for it — baking it in makes the plate argue ahead of the
     voice. */
  function languageShift(o) {
    const land = o.w > o.h, w = o.w, h = o.h, p = o.pal;
    const roles = {
      kicker: TR.kicker, caption: TR.caption,
      // The year is the whole reason the pair means anything, so it is set in the
      // figure face rather than as a label: it is a date, not a heading.
      year: { font: "Courier Prime", size: land ? 40 : 36, weight: 700, colour: "structure", opacity: 0.8, tracking: "0.04em", maxChars: 10 },
      // ONE role for both phrases. Two roles is how "the same statement twice"
      // becomes "a claim and a correction".
      phrase: { font: "Archivo Narrow", size: 96, weight: 700, colour: "structure", tracking: "-.02em", maxLines: 2, maxCharsPerLine: land ? 30 : 21 },      source: { font: "Courier Prime", size: land ? 24 : 22, weight: 400, colour: "structure", opacity: 0.68, maxChars: 40 },
    };
    const P = base(o, "language-shift", roles);
    P.meta.family = "structure";
    const u = unitOf(h);
    const L = land ? 200 : 88, R = w - (land ? 150 : 72);
    const indent = Math.round(u * (land ? 3.4 : 2.6));   // room for the rail
    P.slot("kicker", L, land ? 92 : 200, R - L, blockH(roles.kicker, 1), { align: "left", role: "kicker" });

    const yearH = blockH(roles.year, 1), srcH = blockH(roles.source, 1);
    // +4 UNITS, AND NOT A ROUNDING NICETY. budget.js derives maxLines as
    // floor(box.h / (size * 1.16)), and blockH rounds 2 x 120 x 1.16 down to 278
    // — which divides to 1.997 lines and floors to ONE. The box was a quarter of
    // a unit short of holding the two lines it was built for, and the derived
    // budget said so: this is the first render of this plate reporting
    // maxLines 1 in 16:9. Clearing the boundary rather than authoring around it.
    const phraseH = blockH(roles.phrase, 2) + 4;
    const blockH2 = yearH + Math.round(u * 0.5) + phraseH + Math.round(u * 0.6) + srcH;
    const gap = Math.round(u * (land ? 2.6 : 3.2));
    // TWO BLOCKS PLUS THEIR GAP HAS TO CLEAR THE CAPTION, and in 16:9 that is
    // what set the phrase size rather than taste. At 120 the second block ran to
    // y=1055 against a caption at 950 — the plate overflowed its own frame, and
    // the only thing that reported it was this arithmetic. 96 fits both aspects,
    // which also means one phrase size and one budget across the two.
    const top = Math.round(h * (land ? 0.2 : 0.22));
    const capY = h - (land ? 130 : 200);

    // ONE expression, two blocks. Congruence is what makes them versions.
    const boxes = [];
    ["then", "now"].forEach(function (nm, i) {
      const by = top + i * (blockH2 + gap);
      boxes.push({ name: nm, x: L + indent, y: by, w: R - (L + indent), h: blockH2 });
      // The year box is a THIRD of the measure, not all of it. Full width made
      // the derived budget 59 characters, which is an invitation to put "FY2024
      // annual report, risk factors" in a slot whose job is "2024".
      P.slot(nm + "-year", L + indent, by, Math.round((R - (L + indent)) * 0.22), yearH, { align: "left", role: "year", identifier: 10 });
      P.slot(nm + "-phrase", L + indent, by + yearH + Math.round(u * 0.5), R - (L + indent), phraseH, { align: "left", role: "phrase" });
      P.slot(nm + "-source", L + indent, by + yearH + Math.round(u * 0.5) + phraseH + Math.round(u * 0.6), R - (L + indent), srcH, { align: "left", role: "source" });
    });

    // THE RAIL. One mark down the left of both blocks, with a short spur into
    // each: the thing that says these are two versions of one statement rather
    // than two statements. It breathes — it groups, and nobody reads a value off
    // it — but it is drawn as ONE line across both blocks rather than as two,
    // because two rails would be two claims again.
    const railX = L + Math.round(indent * 0.42);
    const railTop = top + Math.round(yearH * 0.3);
    const railBot = top + blockH2 + gap + Math.round(yearH * 0.3) + Math.round(phraseH * 0.5);
    P.inkAdd(H.breathe(function () {
      return H.line(railX, railTop, railX + 2, railBot, { stroke: p.structure, width: 4.2, opacity: 0.55, amp: 2.8, over: 11, seed: 811 });
    }));
    boxes.forEach(function (b, i) {
      const sy = b.y + Math.round(yearH * 0.55);
      P.inkAdd(H.breathe(function () {
        return H.line(railX, sy, b.x - Math.round(u * 0.5), sy - 1, { stroke: p.structure, width: 3.4, opacity: 0.5, amp: 1.8, over: 7, seed: 820 + i * 9 });
      }));
    });

    P.slot("caption", L, capY, R - L, blockH(roles.caption, 1), { align: "left", role: "caption" });
    const stackBottom = top + blockH2 * 2 + gap;
    P.meta.fit = { top: top, blockH: blockH2, gap: gap, bottom: stackBottom, captionY: capY, clears: stackBottom < capY - Math.round(u * 0.8) };

    P.meta.pair = {
      arrangement: "stacked, one left edge, one width, one type role",
      blocks: boxes,
      congruent: boxes[0].w === boxes[1].w && boxes[0].h === boxes[1].h,
      note: "the two blocks are identical boxes at the same left edge, joined by one rail. That is what makes them read as the same statement in two versions rather than as two unrelated claims — and it is geometry rather than intent, so preflight can assert it.",
    };
    P.meta.order = "THEN ON TOP, NOW BELOW. Reading down is time passing, and the slot names say so rather than leaving a renderer to infer it from the years it happens to fill in.";
    P.meta.refusesDiff = "THE PLATE DOES NOT DRAW THE DIFF. No strike-through on the old phrase, no highlight on the new, no colour on either — both phrases are one type role in `structure`. Emphasis is the annotations family's, applied by the compositor when the script asks for it: annotations/strike-out over then-phrase, annotations/underline-tight under now-phrase. Baking it in would make the plate argue ahead of the voice.";
    P.meta.phraseContract = "A PHRASE, NOT A SENTENCE. Two lines at " + roles.phrase.maxCharsPerLine + " characters measured — a shift is four or five words, and the box is sized so a pasted filing sentence does not fit and therefore does not render. If the shift genuinely needs a sentence, it is a quote and wants cards/quote-pull.";
    P.meta.notSaidHappened = "structure/said-happened is a two-track TIMELINE, N events wide, claim against outcome. This is one pair: the same thing described two ways a year apart. Using said-happened for it would imply the second block is what HAPPENED, when it is what they now SAY.";
    return P;
  }

  // ---------------- §3.2 · headline stack ----------------
  /* paper/headline-stack-{3,4} — several headlines, dated, stacked
     chronologically. The visual form of "this has been building for a while",
     which a single band cannot say.

     News headlines now reach the writer and `paper/headline-band` carries ONE.
     The band is a clipping; this is the pile.

     OLDEST AT THE TOP. Reading down is time passing, and the argument is
     accumulation — the plate is not a timeline (that is `structure/said-happened`
     and it has rails and gaps), it is a stack of things that each happened.

     Count variants at three and four, for tables/'s reason: the strips are a
     fixed measure so the headline budget is stable, and one elastic plate would
     re-derive its strip height at render time. Three is what a 16:9 chapter beat
     uses and four is the ceiling before the headline type drops below the band's;
     five would be a list, and a list is a different argument. */
  function headlineStack(o) {
    const land = o.w > o.h, w = o.w, h = o.h, p = o.pal;
    const n = o.items;
    const roles = {
      kicker: TR.kicker, caption: TR.caption,
      date: { font: "Courier Prime", size: land ? 28 : 26, weight: 700, colour: "structure", opacity: 0.82, tracking: "0.04em", maxChars: 12 },
      // Smaller than headline-band's 96, and sized to FIT FOUR. See the strip
      // arithmetic below: the four-item plate is the constraint, and both counts
      // share one strip height and one headline size so a script can swap three
      // for four without the budget moving.
      headline: { font: "Archivo Narrow", size: land ? 42 : 56, weight: 700, colour: "structure", tracking: "-.02em", maxLines: 2, maxCharsPerLine: land ? 46 : 40 },
      source: { font: "Courier Prime", size: land ? 22 : 21, weight: 400, colour: "structure", opacity: 0.66, maxChars: 30 },
    };
    const P = base(o, "headline-stack-" + n, roles);
    P.meta.family = "paper";
    P.meta.items = n;
    const u = unitOf(h);
    const L = land ? 160 : 76, R = w - (land ? 160 : 76);
    P.slot("kicker", L, land ? 88 : 196, R - L, blockH(roles.kicker, 1), { align: "left", role: "kicker" });

    const dateH = blockH(roles.date, 1), srcH = blockH(roles.source, 1);
    // +4, same boundary as language-shift's phrase box. See the note there.
    const headH = blockH(roles.headline, 2) + 4;
    const pad = Math.round(u * 1.1);
    // The source sits on the date's row (right-aligned), so its height is NOT
    // added again here. It was, in the first build, and those 33 units a strip
    // are most of why the four-item landscape stack overflowed its own frame.
    const stripH = pad * 2 + dateH + Math.round(u * 0.4) + headH;
    const gap = Math.round(u * 1.2);
    // THE STACK IS SIZED FOR FOUR IN BOTH COUNTS, and the first build of this
    // plate is why the arithmetic is written down. At the authored 60/48 the
    // four-item strips ran to y=1288 on a 1080 canvas and the three-item ones to
    // 1015 against a caption at 960 — the plate overflowed its own frame and
    // nothing but the numbers said so. Four strips plus three gaps has to clear
    // the caption, so the type is set from that and not the other way round.
    const top = Math.round(h * (land ? 0.16 : 0.18));
    const capY = h - (land ? 90 : 190);
    const boxes = [];
    for (let i = 1; i <= n; i++) {
      const sy = top + (i - 1) * (stripH + gap);
      // Each item is a clipping: a ground-coloured strip with a drawn edge top
      // and bottom, laid on the surface. NOT ROTATED, and that is a contract
      // rather than a style — a rotated strip needs rotated slots, and every box
      // in this library is axis-aligned because the compositor's fill is. The
      // askew comes from the hand on the edges, which is where it can.
      P.colourAdd(H.hatch(H.polyRect(L - pad, sy, R - L + pad * 2, stripH), { color: p.ground, opacity: 0.9, gap: 7, width: 14, angle: -2 + i, over: 16, seed: 851 + i * 7 }));
      P.inkAdd(H.line(L - pad, sy, R + pad, sy + (i % 2 ? 3 : -2), { stroke: p.structure, width: 2.8, opacity: 0.5, amp: 2.6, over: 10, seed: 860 + i * 7 }));
      P.inkAdd(H.line(L - pad, sy + stripH, R + pad, sy + stripH + (i % 2 ? -2 : 3), { stroke: p.structure, width: 2.2, opacity: 0.38, amp: 2.6, over: 10, seed: 870 + i * 7 }));
      const iy = sy + pad;
      P.slot(`date-${i}`, L, iy, Math.round((R - L) * 0.22), dateH, { align: "left", role: "date" });
      P.slot(`source-${i}`, L + Math.round((R - L) * 0.66), iy, Math.round((R - L) * 0.34), dateH, { align: "right", role: "source" });
      // 16:9 gives the headline 72% of the measure rather than all of it. At full
      // width the derived budget came out 78 characters a line, and 78 x 2 at
      // headline weight is a paragraph wearing a headline's clothes — the stack's
      // whole argument is that there are three or four of these, which fails if
      // any one of them can run long enough to be read as the only one.
      P.slot(`headline-${i}`, L, iy + dateH + Math.round(u * 0.4), land ? Math.round((R - L) * 0.72) : (R - L), headH, { align: "left", role: "headline" });
      boxes.push({ item: i, x: L - pad, y: sy, w: R - L + pad * 2, h: stripH });
    }
    P.slot("caption", L, capY, R - L, blockH(roles.caption, 1), { align: "left", role: "caption" });
    // measured, not assumed: the four-item stack has to end above the caption
    const stackBottom = top + 4 * stripH + 3 * gap;
    P.meta.fit = { top: top, stripH: stripH, gap: gap, fourItemBottom: stackBottom, captionY: capY, clears: stackBottom < capY - Math.round(u * 0.8) };

    P.meta.strips = boxes;
    P.meta.congruent = boxes.every((b) => b.h === boxes[0].h && b.w === boxes[0].w);
    P.meta.order = "OLDEST AT THE TOP, NEWEST AT THE BOTTOM. date-1 is the oldest. Reading down is time passing; filled the other way the plate says the opposite with the same ink, and nothing would report it.";
    P.meta.argument = n + " headlines, dated, stacked. paper/headline-band carries one story; this carries the fact that there have been " + n + " of them. That accumulation is the whole difference — it is the picture of 'this has been building for a while'.";
    P.meta.notATimeline = "this is not structure/said-happened and not structure/timeline. There is no rail, no interval and no gap: the strips are evenly spaced whatever the dates say, because the argument is HOW MANY, not how far apart. If the spacing matters, the script wants the timeline.";
    P.meta.seriesNote = "every item is one type role at one size, and no strip is emphasised. The headline the script is about gets an annotation over it from the compositor — a stack with one item pre-lifted has chosen the story for the voice.";
    P.meta.sourceContract = "date-N and source-N are separate slots and both are required: a headline without a publication is a claim with no author, on a channel whose premise is real numbers. The source box is budgeted for " + roles.source.maxChars + " characters, which holds a masthead, not a URL.";
    P.meta.headlineBudgetNote = "the headline box is CAPACITY, not a target. At " + (P.slots["headline-1"] ? P.slots["headline-1"].maxChars || "~48" : "~48") + " characters a line it will hold a long one — but a headline that runs to both full lines on every strip is a script that wants paper/headline-band and one story, not a stack whose argument is how many there have been.";
    return P;
  }

  // §2.1 — EIGHT QUARTERS, AND WHY THEY ARE TYPES ON THIS AUTHOR.
  //
  // The pipeline reads a Quarters sheet carrying six to eight quarters. Every
  // chart in the kit was annual, so the data path existed and the video had
  // nowhere to put it.
  //
  // Eight columns rather than six, and a period label of a different shape:
  // Q3'25, not 2025. Both are layout, not content, which is why they are a
  // COLUMN COUNT on this author rather than a second one — the margins, the
  // gridlines, the axis pinning and the tick convention are the things that have
  // to be identical for a quarterly chart to sit in the same cut as an annual
  // one, and sharing the author makes that true by construction.
  //
  // What does NOT transfer is the value row. See vFits below: it is measured.
  const QUARTERLY = { "bars-8q": 1, "line-8q": 1 };

  function chartFrame(o) {
    const p = o.pal, w = o.w, h = o.h, land = w > h;
    const s = SURFACES[p.surfaceKey];
    const N = QUARTERLY[o.type] ? 8 : 6;
    const P = H.Plate({
      key: o.key, w, h, seed: o.seed, pal: p,
      meta: {
        aspect: land ? "16x9" : "9x16", family: "charts", type: o.type, columns: N,
        typeRoles: {
          unit: { font: "Courier Prime", size: 26, weight: 400, colour: "structure", opacity: 0.72, tracking: "0.04em", maxChars: land ? 46 : 38 },
          period: { font: "Archivo Narrow", size: land ? 28 : 26, weight: 600, colour: "structure", maxChars: 6 },
          axis: { font: "Courier Prime", size: land ? 26 : 24, weight: 400, colour: "structure", opacity: 0.7, maxChars: 7 },
          value: { font: "Courier Prime", size: land ? 34 : 30, weight: 700, colour: "structure", maxChars: 7 },
        },
        seriesRoles: { subject: "structure", neutral: "neutralData", otherParty: "otherParty", up: "up", down: "down", mark: "attention" },
      },
    });
    P.colourAdd(H.breathe(function () { return surfaceFurniture(P, s); }));
    const m = land ? { l: 200, r: 130, t: 190, b: 170 } : { l: 150, r: 90, t: 330, b: 420 };
    const x0 = m.l, x1 = w - m.r, y0 = m.t, y1 = h - m.b;
    const ticks = o.type === "line-dense" ? 12 : N;

    // THE VALUE ROW IS MEASURED, NOT ASSUMED, and this is the whole of what
    // §2.1's "real layout difference" turns out to be at these canvas sizes.
    //
    // At six columns a value box holds a money string in both aspects. At eight
    // in 9:16 it does not: the plot is 840 units wide, a column is 105, and the
    // value role is 30-unit Courier at 0.5996em — 18 units a character, so the
    // box takes five. "$1.2B" fits and "$12.4B" does not, and an over-budget
    // fill does not render at all (budget.js). A row of per-column figures that
    // silently stops the shot is worse than no row.
    //
    // So the per-column value row exists where it measures out, and where it does
    // not the plate publishes ONE value callout instead — which is also the
    // honest picture: nobody reads eight stacked figures off a phone screen.
    // Six is the floor because it is the shortest useful money string with a
    // sign and a unit ("-$1.2B", "+12.4%").
    const VALUE_FLOOR = 6;
    const fitsValue = function (boxW) {
      return g.BUDGET.capacity({ w: boxW }, "value", P.meta.typeRoles.value) >= VALUE_FLOOR;
    };

    P.slot("unit", land ? 118 : 60, land ? 92 : 200, x1 - (land ? 118 : 60), land ? 42 : 50, { align: "left", role: "unit" });
    P.slot("plot-area", x0, y0, x1 - x0, y1 - y0, { role: "plot-area", container: true, note: "code draws the data path in here only" });

    // y gridlines + their label slots
    const gl = o.type === "line-dense" ? 3 : 4;
    for (let i = 0; i <= gl; i++) {
      const y = y1 - ((y1 - y0) / gl) * i;
      // §1.5 — GRIDLINES BREATHE, AXES DO NOT, and this is the exact line where
      // the distinction has to be made rather than described. A gridline is a
      // separator: nobody reads a value off it, they read it off the axis label
      // beside it. The axis below is a measurement reference — move it and the
      // data appears to move even though every series point is pinned.
      if (i > 0) P.inkAdd(H.breathe(function () {
        return H.line(x0, y, x1, y, { stroke: p.structure, width: 1.8, opacity: 0.2, amp: 2.6, over: 7, seed: 210 + i * 7 });
      }));
      // the topmost label tucks under its gridline, so it never reaches the value row
      P.slot(`y-${i + 1}`, x0 - (land ? 160 : 130), i === gl ? y + 6 : y - 26, land ? 140 : 112, 52, { align: "right", role: "axis" });
    }
    // axes — PINNED. See the gridline note above. An axis is a measurement
    // reference: move it and the data appears to move even though every series
    // point is held still.
    H.pin(function () {
      P.inkAdd(H.line(x0, y0 - 16, x0, y1, { stroke: p.structure, width: land ? 4.6 : 4, opacity: 0.9, amp: 3, over: 11, seed: 21 }));
      P.inkAdd(H.line(x0, y1, x1 + 18, y1, { stroke: p.structure, width: land ? 4.6 : 4, opacity: 0.9, amp: 3, over: 11, seed: 22 }));
    });

    // §2.3 / §2.4 / §2.11 — THREE NEW SIX-PERIOD CHARTS, AND WHY THEY ARE TYPES
    // ON THIS AUTHOR RATHER THAN THREE NEW ONES.
    //
    // Dilution, the debt wall and guidance-versus-actual are all "six periods on
    // one plot", which is exactly what this author already is. A new author would
    // duplicate the margins, the gridlines, the axis pinning and the tick
    // convention — and the brief is explicit that these must sit in the same cut
    // as an existing chart without the years changing width mid-video. Sharing
    // the author makes that true by construction rather than by care.
    //
    // What differs per type is the SLOT SET and what the plate says about itself,
    // which is the part that belongs to the argument:
    //
    //   dilution-6y   share count rising. Same slots as bars-6y so it drops in
    //                 beside the others — but its own key, because "shares
    //                 outstanding" is not "revenue" and the manifest should not
    //                 pretend a script can swap them.
    //   maturities    the debt wall. Also bars, also six periods, and the one of
    //                 the three where a column can legitimately be ZERO.
    //   guided-vs-actual-6y  two series on one plot, one scale, published once —
    //                 for the same reason the implied plate publishes its axis.
    const BARS = { "bars-6y": 1, "bars-8q": 1, "dilution-6y": 1, "maturities": 1 };
    if (BARS[o.type]) {
      const step = (x1 - x0) / N, barW = step * 0.56;
      const vFits = fitsValue(step);
      for (let c = 1; c <= N; c++) {
        const cx = x0 + step * (c - 0.5);
        // PINNED: a tick is where a period IS. It is read off, not decoration.
        H.pin(function () { P.inkAdd(H.line(cx, y1, cx, y1 + 16, { stroke: p.structure, width: 2.4, opacity: 0.75, amp: 1.2, seed: 300 + c * 11 })); });
        P.slot(`bar-${c}`, cx - barW / 2, y0, barW, y1 - y0, { role: "bar", region: true, growth: "up-from-baseline", baselineY: Math.round(y1) });
        if (vFits) P.slot(`value-${c}`, cx - step / 2, y0 - 50, step, 46, { align: "center", role: "value" });
        P.slot(`head-${c}`, cx - step / 2, y1 + 30, step, 52, { align: "center", role: "period" });
      }
      if (!vFits) valueCallout(P, x0, y0, x1, land);
      if (o.type === "dilution-6y") {
        P.meta.argument = "shares outstanding, rising. Stock comp appears in every script and nothing else in the kit shows the viewer what it costs THEM.";
        P.meta.seriesNote = "one series, subject colour. NOT drawn in `down` — a rising share count is a rise, and colouring it as a loss makes the plate deliver the verdict before the voice-over does.";
        P.meta.unitNote = "a COUNT, not a percentage. The dilution is the line going up; a percentage hides that behind a denominator.";
      }
      if (o.type === "bars-8q") quarterly(P, land, "bars");
      if (o.type === "maturities") {
        P.meta.argument = "when the debt comes due, by year. The thing that decides whether a bad year is survivable, and the kit could not draw it.";
        P.meta.zeroNote = "A ZERO COLUMN IS DATA. A year with nothing due is the good news in this picture, and the shape of the wall depends on that gap being visible. Render a zero as a zero-height bar ON the baseline with its head label intact — do not drop the column.";
        P.meta.seriesNote = "one series, subject colour. The bars are a schedule, not a performance: no up, no down.";
      }
    } else if (o.type === "guided-vs-actual-6y") {
      const step = (x1 - x0) / 5;
      for (let c = 1; c <= 6; c++) {
        const cx = x0 + step * (c - 1);
        H.pin(function () { P.inkAdd(H.line(cx, y1, cx, y1 + 16, { stroke: p.structure, width: 2.4, opacity: 0.7, amp: 1.2, seed: 300 + c * 11 })); });
        const px = Math.max(x0, Math.min(x1 - 84, cx - 42));
        P.slot(`guided-${c}`, px, y0, 84, y1 - y0, {
          role: "point-column", region: true, series: "guided", anchorX: Math.round(cx),
          note: "what they forecast. Drawn FAINT and WIDE — a forecast is a claim with a width, and giving it the same weight as the outcome is the plate arguing that a guess and a result are the same kind of thing.",
        });
        P.slot(`actual-${c}`, px, y0, 84, y1 - y0, {
          role: "point-column", region: true, series: "actual", anchorX: Math.round(cx),
          note: "what happened. Solid and narrow, over the guided band. Same column, same scale — the gap between them IS the argument.",
        });
        const vw = Math.min(152, step * 0.8);
        /* LEGACY PASS, rebuild-21: the last value box centred on the end point ran
         * past the 5% margin. Clamped inside it; the text stays centred in the box. */
        P.slot(`value-${c}`, Math.min(w * 0.95 - vw, Math.max(w * 0.05, cx - vw / 2)), y0 - 50, vw, 46, { align: "center", role: "value" });
        P.slot(`head-${c}`, cx - (land ? 84 : 62), y1 + 30, land ? 168 : 124, 52, { align: "center", role: "period" });
      }
      P.meta.argument = "the forecast faint and wide, the outcome solid and narrow. The whole format is 'they said, then look' — this is that sentence as a picture.";
      P.meta.scaleNote = "guided-N and actual-N are measured against the SAME plot-area on the SAME scale. Two series on two scales is not a comparison, and the plate publishes one plot-area precisely so a renderer cannot accidentally use two.";
      P.meta.seriesNote = "guided is otherParty — it is someone else's claim about the future; actual is subject. Neither is up or down: a miss is not a fall.";
    } else {
      const step = (x1 - x0) / (ticks - 1);
      const isLine = o.type === "line-6y" || o.type === "line-8q";
      // a point column is a fixed 84 wide, so at eight quarters the value box is
      // the column rather than the pitch — measure the box that actually exists
      const vFits = isLine && fitsValue(Math.min(152, step * 0.8));
      for (let c = 1; c <= ticks; c++) {
        const cx = x0 + step * (c - 1);
        // PINNED, same reason as the bar ticks.
        H.pin(function () { P.inkAdd(H.line(cx, y1, cx, y1 + (o.type === "line-dense" ? 11 : 16), { stroke: p.structure, width: o.type === "line-dense" ? 1.9 : 2.4, opacity: 0.7, amp: 1.2, seed: 300 + c * 11 })); });
        if (isLine) {
          const px = Math.max(x0, Math.min(x1 - 84, cx - 42));
          P.slot(`point-${c}`, px, y0, 84, y1 - y0, { role: "point-column", region: true, anchorX: Math.round(cx) });
          const vw = Math.min(152, step * 0.8);
          if (vFits) P.slot(`value-${c}`, Math.min(w * 0.95 - vw, Math.max(w * 0.05, cx - vw / 2)), y0 - 50, vw, 46, { align: "center", role: "value" });
          const hw = Math.min(land ? 168 : 124, step * 0.94);
          P.slot(`head-${c}`, cx - hw / 2, y1 + 30, hw, 52, { align: "center", role: "period", anchorX: Math.round(cx) });
        }
      }
      if (isLine && !vFits) valueCallout(P, x0, y0, x1, land);
      if (o.type === "line-8q") quarterly(P, land, "line");
      if (o.type === "line-dense") {
        // a price chart is labelled at a handful of dates, not at every tick
        const anchors = [1, 5, 9, 12];
        const hw = step * 2;
        anchors.forEach((t, k) => {
          const cx = x0 + step * (t - 1);
          /* LEGACY PASS, rebuild-21: clamped to the 5% margin, not to 12 units. */
          const hx = Math.max(Math.ceil(w * 0.05), Math.min(Math.floor(w * 0.95) - hw, cx - hw / 2));
          P.slot(`head-${k + 1}`, hx, y1 + 30, hw, 52, { align: "center", role: "period", anchorX: Math.round(cx), tick: t });
        });
        P.slot("mark-high", x0, y0, x1 - x0, 56, { align: "right", role: "value", region: true, note: "52-week high callout" });
        P.slot("mark-low", x0, y1 - 56, x1 - x0, 56, { align: "right", role: "value", region: true, note: "52-week low callout" });
        P.slot("mark-last", x1 - (land ? 300 : 220), y0, land ? 300 : 220, y1 - y0, { align: "right", role: "value", region: true, note: "last price, placed by code at the path end" });
      }
    }
    return P;
  }

  // ---------------- cash-flow summary ----------------
  // Three grouped blocks, a ruled subtotal each, a bold total at the foot.
  function cashFlow(o) {
    const w = o.w, h = o.h, land = w > h, p = o.pal, s = SURFACES[p.surfaceKey];
    const blocks = land ? [2, 2, 2] : [3, 3, 3]; // 16:9 has less vertical room — fewer line rows, not smaller type
    const P = H.Plate({
      key: o.key, w, h, seed: o.seed, pal: p,
      meta: {
        aspect: land ? "16x9" : "9x16", family: "tables", type: "cash-flow-summary", columns: 6, blocks: blocks.length,
      },
    });
    P.colourAdd(surfaceFurniture(P, s));
    /* LEGACY PASS, rebuild-21: portrait side margins 48 -> 56, same reason as the
     * numbers sheet — the unit, group names and total label sat in the margin. */
    const m = land ? { l: 118, r: 118, t: 78, b: 74 } : { l: 56, r: 56, t: 180, b: 200 };
    const innerL = m.l, innerR = w - m.r;
    P.slot("unit", innerL, m.t, innerR - innerL, 40, { align: "left", role: "unit" });
    const headY = m.t + 40 + (land ? 30 : 60);
    const headH = land ? 44 : 48;
    const ruleY = headY + headH + 14;
    const labelW = Math.round((innerR - innerL) * (land ? 0.34 : 0.30));
    const colsL = innerL + labelW, colW = (innerR - colsL) / 6;
    for (let c = 1; c <= 6; c++) {
      const x = colsL + (c - 1) * colW;
      P.slot(`head-${c}`, x + 6, headY, colW - 12, headH, { align: "right", role: "period" });
    }
    P.inkAdd(H.line(innerL - 8, ruleY, innerR + 8, ruleY, { stroke: p.structure, width: land ? 6 : 5.4, opacity: 0.95, amp: 3.4, over: 12, seed: 88 }));

    const totalRows = blocks.reduce((a, b) => a + b + 2, 0) + 2; // line rows + subtotal + group label per block, plus the total
    const bodyTop = ruleY + (land ? 22 : 26);
    const bodyBot = h - m.b;
    const groupGap = land ? 20 : 30;
    const rowH = (bodyBot - bodyTop - groupGap * blocks.length - (land ? 26 : 40)) / totalRows;
    let y = bodyTop;
    // type sizes are derived from the row height that actually came out, so a
    // declared size can never exceed the box the renderer is given
    const fit = (frac, min, max) => Math.max(min, Math.min(max, Math.round(rowH * frac)));
    P.meta.typeRoles = {
      unit: { font: "Courier Prime", size: 26, weight: 400, colour: "structure", opacity: 0.72, maxChars: land ? 46 : 38 },
      period: { font: "Archivo Narrow", size: land ? 26 : 26, weight: 600, colour: "structure", maxChars: 6 },
      group: { font: "Archivo Narrow", size: fit(0.46, 24, 30), weight: 700, colour: "structure", tracking: ".08em", transform: "uppercase", maxChars: 24 },
      label: { font: "Archivo Narrow", size: fit(0.5, 24, 30), weight: 400, colour: "structure", maxChars: land ? 30 : 22 },
      figure: { font: "Courier Prime", size: fit(0.52, 24, 32), weight: 400, colour: "structure", maxChars: 7 },
      subtotal: { font: "Courier Prime", size: fit(0.52, 24, 32), weight: 700, colour: "structure", maxChars: 7 },
      // DROP TEN: THE PORTRAIT TOTAL TAKES THE CELLS' SIZE; LANDSCAPE IS UNTOUCHED.
      // At fit(0.72,30,44) the portrait total was 44u in a 103-unit column and
      // derived THREE characters, while the 32u cells beneath it derived five — so
      // the total could not hold "1,284" or "(482)" and the line items it totals
      // could. A total tighter than its own lines cannot be right in a cash-flow
      // table.
      //
      // I tried keeping landscape's step up, since 36u derives 8 there and every
      // realistic total I tested fits. Measured, that still violates the rule:
      // the landscape CELLS derive 11, so a 9-digit total blanks while its own
      // line items render — the same defect, needing a bigger number. A total is
      // a sum, so it is the value most likely to be the longest on the plate, and
      // a 173-unit column cannot hold both the step up and the cells' budget.
      // So the budget wins on both aspects and the total is distinguished by
      // weight 700 and by the rule above it, which is how the rest of the kit
      // marks a total anyway. Landscape gives up 36u for 26u; that is the cost,
      // and it buys the invariant that a total can never blank where its own
      // lines render.
      total: { font: "Courier Prime", size: fit(0.52, 24, 32), weight: 700, colour: "structure", maxChars: 7 },
    };
    blocks.forEach((n, bi) => {
      const b = bi + 1;
      P.slot(`group-${b}`, innerL, y, labelW - 20, rowH, { align: "left", role: "group" });
      y += rowH;
      for (let r = 1; r <= n; r++) {
        P.slot(`band-${b}-${r}`, innerL - 26, y + 2, innerR - innerL + 52, rowH - 4, { role: "highlight-band", overlay: "overlays/row-band" });
        P.slot(`label-${b}-${r}`, innerL + (land ? 26 : 18), y + rowH * 0.12, labelW - (land ? 52 : 40), rowH * 0.76, { align: "left", role: "label" });
        for (let c = 1; c <= 6; c++) {
          P.slot(`cell-${b}-${r}-${c}`, colsL + (c - 1) * colW + 6, y + rowH * 0.12, colW - 12, rowH * 0.76, { align: "right", role: "figure" });
        }
        y += rowH;
      }
      // subtotal: ruled above, over the columns only
      P.inkAdd(H.line(colsL - 6, y + 3, innerR + 4, y + 3, { stroke: p.structure, width: 2.4, opacity: 0.7, amp: 2, over: 7, seed: 500 + b * 31 }));
      P.slot(`subtotal-label-${b}`, innerL + (land ? 26 : 18), y + rowH * 0.14, labelW - (land ? 52 : 40), rowH * 0.76, { align: "left", role: "label" });
      for (let c = 1; c <= 6; c++) {
        P.slot(`subtotal-${b}-${c}`, colsL + (c - 1) * colW + 6, y + rowH * 0.14, colW - 12, rowH * 0.76, { align: "right", role: "subtotal" });
      }
      y += rowH + groupGap;
    });
    // bold total at the foot, double rule. No clamp: a bad row budget must fail visibly, never overprint a block.
    const tY = y;
    P.inkAdd(H.line(innerL - 8, tY - 6, innerR + 8, tY - 6, { stroke: p.structure, width: 3.4, opacity: 0.9, amp: 2.6, over: 10, seed: 611 }));
    P.inkAdd(H.line(innerL - 8, tY + rowH * 1.24, innerR + 8, tY + rowH * 1.24, { stroke: p.structure, width: 2.2, opacity: 0.8, amp: 2.2, over: 9, seed: 612 }));
    P.slot("total-label", innerL, tY + rowH * 0.16, labelW - 20, rowH * 0.9, { align: "left", role: "group" });
    for (let c = 1; c <= 6; c++) {
      P.slot(`total-${c}`, colsL + (c - 1) * colW + 6, tY + rowH * 0.16, colW - 12, rowH * 0.9, { align: "right", role: "total" });
    }
    return P;
  }

  // ---------------- headline band ----------------
  // Three treatments. Three in one video must not look identical.
  function headlineBand(o) {
    const w = o.w, h = o.h, land = w > h, p = o.pal, s = SURFACES[p.surfaceKey];
    const t = o.treatment; // 1 rule-under · 2 ruled panel · 3 taped strip
    const P = H.Plate({
      key: o.key, w, h, seed: o.seed, pal: p,
      meta: {
        aspect: land ? "16x9" : "9x16", family: "paper", type: "headline-band", treatment: t,
        typeRoles: {
          kicker: { font: "Courier Prime", size: land ? 28 : 30, weight: 400, colour: "structure", opacity: 0.7, tracking: ".16em", transform: "uppercase", maxChars: 34 },
          headline: { font: "Archivo Narrow", size: land ? 96 : 84, weight: 700, colour: "structure", tracking: "-.02em", maxLines: 3, maxCharsPerLine: land ? 30 : 20 },
          sub: { font: "Archivo Narrow", size: land ? 34 : 32, weight: 400, colour: "structure", opacity: 0.85, maxLines: 2, maxCharsPerLine: land ? 62 : 40 },
        },
      },
    });
    P.colourAdd(surfaceFurniture(P, s));
    const m = land ? { l: 150, r: 150 } : { l: 80, r: 80 };
    const L = m.l, R = w - m.r, mid = h / 2;
    const hlH = land ? 250 : 330;

    if (t === 1) {
      const top = mid - hlH * 0.62;
      P.slot("kicker", L, top - (land ? 62 : 74), R - L, land ? 44 : 50, { align: "left", role: "kicker" });
      P.slot("headline", L, top, R - L, hlH, { align: "left", role: "headline" });
      // TREATMENT 1 IS THE ONE PLATE IN THE PACK WITH NOTHING ON IT TO BOIL.
      //
      // t2 draws a hatched panel and t3 a taped strip, so 3.6% of their pixels
      // change between frames — right in the 1-6% pack band. t1 drew ONE rule,
      // which is 0.40%: a plate that is frozen with a single element twitching,
      // and that reads worse than an honest still. Amplitude could never fix it
      // (it was already at 1.39 units, dead centre of spec) because the problem
      // is how much ink is on the plate, not how far it moves.
      //
      // What is added is inside the treatment's own vocabulary rather than
      // borrowed from t2's: t1 IS the rule-under treatment, so it gets a rule a
      // hand actually drew — a reinforcing second pass that leaves the primary
      // and rejoins it, the same idiom the scrawled ovals use — plus the short
      // kicker tick the other two get for free from their panel edges. No box,
      // no hatch: those are what makes a plate t2.
      // Rule extents are proportions of the TEXT MEASURE (R - L), not of R. In
      // landscape those are nearly the same number and the bug never showed; in
      // portrait R*0.62 is 670 units of a 920-unit measure, so every rule came
      // out short and the plate lost a third of its ink in the aspect that had
      // least to spare. Same class as the rhythm defect the text plates had:
      // a constant standing in for a measurement.
      const meas = R - L;
      const ruleY = top + hlH + 20;
      P.inkAdd(H.line(L - 10, ruleY, L + meas * (land ? 0.68 : 0.88), ruleY, { stroke: p.structure, width: land ? 9 : 11, opacity: 0.95, amp: 4, over: 16, seed: 71 }));
      P.inkAdd(H.line(L - 4, ruleY + (land ? 3 : 2.5), L + meas * (land ? 0.6 : 0.8), ruleY + (land ? 3 : 2.5), { stroke: p.structure, width: land ? 4.2 : 5.2, opacity: 0.42, amp: 5, over: 12, seed: 72 }));
      P.inkAdd(H.line(L - 10, top - (land ? 78 : 92), L + meas * (land ? 0.19 : 0.3), top - (land ? 78 : 92), { stroke: p.structure, width: land ? 5 : 6.2, opacity: 0.8, amp: 3.4, over: 10, seed: 73 }));
      // and a closing rule under the sub. Without it the sub hangs off the
      // bottom of nothing, which is the same fragment-of-a-longer-list problem
      // the peer strip's foot rule solves — so it earns its place on the plate
      // rather than being ink added to satisfy a number.
      const subBase = top + hlH + 48 + (land ? 92 : 110) + (land ? 26 : 30);
      P.inkAdd(H.line(L - 6, subBase, L + meas * (land ? 0.5 : 0.68), subBase, { stroke: p.structure, width: land ? 5.5 : 6.8, opacity: 0.7, amp: 3.6, over: 12, seed: 74 }));
      P.slot("sub", L, top + hlH + 48, (R - L) * 0.8, land ? 92 : 110, { align: "left", role: "sub" });
    } else if (t === 2) {
      const pt = mid - hlH * 0.9;
      const hy = pt + (land ? 62 : 76);
      const subH = land ? 92 : 110;
      const subY = hy + hlH + (land ? 30 : 36);
      const pb = subY + subH + (land ? 12 : 16);
      P.colourAdd(H.hatch(H.polyRect(L - 30, pt - 26, R - L + 60, pb - pt + 52), { color: p.ground2, opacity: 0.6, gap: 8, width: 13, angle: -3, over: 20, seed: 41 }));
      P.inkAdd(H.outline(H.polyRect(L - 30, pt - 26, R - L + 60, pb - pt + 52), { stroke: p.structure, width: 4.2, opacity: 0.9, amp: 3.4, over: 14, seed: 42 }));
      P.slot("kicker", L, pt, R - L, land ? 44 : 50, { align: "left", role: "kicker" });
      P.slot("headline", L, hy, R - L, hlH, { align: "left", role: "headline" });
      P.slot("sub", L, subY, (R - L) * 0.86, subH, { align: "left", role: "sub" });
    } else {
      // taped strip: a clipping laid on the desk, slightly askew tape at both ends
      const st = mid - hlH * 0.78;
      const hy = st + (land ? 60 : 74);
      const subH = land ? 84 : 100;
      const subY = hy + hlH + (land ? 26 : 32);
      const sb = subY + subH + (land ? 14 : 18);
      P.colourAdd(H.hatch(H.polyRect(L - 46, st - 34, R - L + 92, sb - st + 68), { color: p.ground, opacity: 0.9, gap: 7, width: 14, angle: -2, over: 18, seed: 51 }));
      P.inkAdd(H.line(L - 46, st - 34, R + 46, st - 30, { stroke: p.structure, width: 2.6, opacity: 0.55, amp: 3, over: 10, seed: 52 }));
      P.inkAdd(H.line(L - 46, sb + 34, R + 46, sb + 30, { stroke: p.structure, width: 2.6, opacity: 0.55, amp: 3, over: 10, seed: 53 }));
      [[L - 170, st - 122], [R - 40, sb + 6]].forEach((tp, i) => {
        const poly = [{ x: tp[0], y: tp[1] }, { x: tp[0] + 150, y: tp[1] - 18 }, { x: tp[0] + 160, y: tp[1] + 46 }, { x: tp[0] + 10, y: tp[1] + 64 }];
        P.colourAdd(H.hatch(poly, { color: p.attention, opacity: 0.3, gap: 7, width: 11, angle: -8, over: 12, seed: 60 + i }));
        P.inkAdd(H.outline(poly, { stroke: p.structure, width: 1.9, opacity: 0.4, amp: 2.4, over: 6, seed: 65 + i }));
        P.artBox(`tape-${i + 1}`, tp[0] - 12, tp[1] - 30, 184, 106);
      });
      P.slot("kicker", L, st, R - L, land ? 44 : 50, { align: "left", role: "kicker" });
      P.slot("headline", L, hy, R - L, hlH, { align: "left", role: "headline" });
      P.slot("sub", L, subY, (R - L) * 0.9, subH, { align: "left", role: "sub" });
    }
    return P;
  }

  // ---------------- cross-chapter structure ----------------
  function base(o, type, roles) {
    const land = o.w > o.h, p = o.pal;
    const P = H.Plate({
      key: o.key, w: o.w, h: o.h, seed: o.seed, pal: p,
      meta: { aspect: land ? "16x9" : "9x16", family: "structure", type: type, typeRoles: roles },
    });
    // §1.5 — the surface's own furniture BREATHES. Pad rules and board smears are
    // decoration of the sheet: nobody reads a value off them, and on a gated
    // plate they are the largest thing on screen that is allowed to move.
    P.colourAdd(H.breathe(function () { return surfaceFurniture(P, SURFACES[p.surfaceKey]); }));
    return P;
  }
  // ---------------- composition ----------------
  // One vertical rhythm for every text plate.
  //
  // The old plates placed each slot at a hand-picked constant and then gave it a
  // generous box — statement at y=330 with h=330, detail at y=680. But two lines
  // of 62-unit type is 145 units, so 185 units of dead air sat INSIDE the
  // statement slot: the gap you saw on screen was never the gap in the code, and
  // no amount of moving constants could fix it. Measure the type, stack by a
  // unit, and the rhythm becomes something you can reason about.
  function unitOf(h) { return Math.max(14, Math.round(h * 0.0156)); }
  function blockH(role, lines) { return Math.round((lines || 1) * role.size * 1.16); }
  function ruleH(u) { return Math.max(2, Math.round(u * 0.2)); }

  // A ledger leader: short dashes tying a label to the figure it belongs to, or
  // giving a bar a rail to sit on. Drawn as separate strokes rather than a dash
  // array, because a dashed line is one path with one tremor — the dashes would
  // all waver identically, which is the one thing a hand never does.
  // §1.5: a leader is a separator, so it breathes. It ties a label to a figure;
  // it is not a scale anyone reads the figure off.
  function leader(P, x1, x2, y, seed, op) {
    const step = 21, len = 7;
    let i = 0;
    for (let x = x1; x < x2 - len; x += step) {
      P.inkAdd(H.breathe(function () {
        return H.line(x, y, x + len, y - 1, {
          stroke: P.pal.structure, width: 2, opacity: op == null ? 0.24 : op,
          amp: 1.1, over: 0, step: 4, seed: seed + i * 3,
        });
      }));
      i += 1;
    }
  }

  // A ground2 panel. Gives a figure something to stand on — the single biggest
  // reason the old figure plates read as floating in a void.
  //
  // §1.5: PINNED, and this is the call that decides what the rule actually means.
  // It is hatch, and hatch breathes — but this hatch is a SLOT UNDERLAY: it sits
  // directly behind a figure the plate holds still. An underlay moving behind
  // pinned type creates RELATIVE motion, which reads worse than either moving
  // alone. "Texture fills breathe" and "underlays do not" are both true and this
  // is where they meet; what the mark is FOR wins over what it is made of.
  function field(P, x, y, w, h, seed, op) {
    return H.pin(function () { return fieldMarks(P, x, y, w, h, seed, op); });
  }
  function fieldMarks(P, x, y, w, h, seed, op) {
    P.colourAdd(H.hatch(H.polyRect(x, y, w, h), {
      color: P.pal.ground2, opacity: op == null ? 0.5 : op,
      gap: 7, width: 7.8, angle: -3, over: 9, seed: seed || 900,
    }));
  }

  // spec: { x, w, align, unit, roles, blocks:[{name, role, lines, gap, indent} | {rule:true, width, weight}] }
  function measure(spec) {
    let t = 0;
    spec.blocks.forEach(function (b, i) {
      if (i) t += Math.round((b.gap == null ? 1 : b.gap) * spec.unit);
      t += b.rule ? ruleH(spec.unit) : blockH(spec.roles[b.role], b.lines);
    });
    return t;
  }

  function place(P, spec, top) {
    let y = top;
    const items = {};
    spec.blocks.forEach(function (b, i) {
      if (i) y += Math.round((b.gap == null ? 1 : b.gap) * spec.unit);
      if (b.rule) {
        const rh = ruleH(spec.unit);
        const rw = b.width == null ? spec.w : spec.w * b.width;
        const rx = (spec.align === "center") ? spec.x + (spec.w - rw) / 2 : spec.x;
        // §1.5: a composition rule is furniture, not a measurement reference.
        P.inkAdd(H.breathe(function () {
          return H.line(rx, y + rh / 2, rx + rw, y + rh / 2 - 5, {
            stroke: P.pal.structure, width: b.weight || 6, opacity: 0.9, amp: 3.4, over: 13, seed: b.seed || 211,
          });
        }));
        y += rh;
        return;
      }
      const ind = (b.indent || 0) * spec.unit;
      const hh = blockH(spec.roles[b.role], b.lines);
      const rect = { x: spec.x + ind, y: y, w: spec.w - ind, h: hh };
      P.slot(b.name, rect.x, rect.y, rect.w, rect.h, { align: b.align || spec.align || "left", role: b.role });
      items[b.name] = rect;
      y += hh;
    });
    return { items: items, bottom: y };
  }

  // Direction glyph. mark-1 and mark-2 on a both-true are DIRECTION, not truth —
  // both statements are true, that is the premise. The old plate drew a green
  // tick beside both of them, which says "true, true" and destroys the tension
  // the frame exists to hold.
  function dirArrow(P, x, y, size, dir, seed) {
    const col = dir === "down" ? P.pal.down : P.pal.up;
    const s = size, cx = x + s * 0.5;
    const tipY = dir === "down" ? y + s : y;
    const tailY = dir === "down" ? y : y + s;
    const wt = Math.max(6, s * 0.16);
    P.colourAdd(H.stroke([{ x: cx, y: tailY }, { x: cx, y: tipY }], { stroke: col, width: wt, amp: 2.2, over: 5, seed: seed }));
    P.colourAdd(H.stroke([
      { x: cx - s * 0.36, y: dir === "down" ? tipY - s * 0.42 : tipY + s * 0.42 },
      { x: cx, y: tipY },
      { x: cx + s * 0.36, y: dir === "down" ? tipY - s * 0.42 : tipY + s * 0.42 },
    ], { stroke: col, width: wt, amp: 1.8, over: 4, seed: seed + 1 }));
  }

  // The face's own skin token, in ONE place. hostFigure and hostHead each
  // carried their own copy of the literal, which was harmless while they were the
  // only two authors of a face — §1.2's blink overlay is a third, and it has to
  // paint over the open eye it replaces, so a divergence here would show as a
  // patch of the wrong colour on his face and nowhere else.
  const SKIN = "#C99A6E";

  // §4.1 — WHICH POSES ARE SEATED. Declared at module level because hostFigure
  // reads it while solving proportion, which happens before its own POSE table is
  // in scope. One entry, and the emptyChair author below shares the chair it
  // implies.
  const POSE_SEATED = { "sitting-at-desk": 1 };

  /* §4.1/§4.3 — THE CHAIR, ONCE.

     It is drawn on the HOST plate rather than in the room, and that is a decision
     with a cost. A seated cut-out composited onto a room whose set has no chair is
     a man hovering at desk height; the chair has to travel with him. The price is
     that his chair is the same chair in every room, which is the lesser problem —
     it is his chair.

     It is drawn QUIETLY: half the figure's hatch opacity and two-thirds its line
     weight. room/ doctrine is that Dennis is the highest-contrast object in any
     frame he is in, and a chair drawn at his weight competes with him inside his
     own cut-out.

     Geometry is one function so the seated pose and the empty chair cannot drift
     apart — the empty chair IS this chair with nobody in it, and two copies of
     the arithmetic would eventually make them two different chairs. */
  function hostChair(o) {
    const P = o.P, S = o.S, HU = o.HU, cx = o.cx, seatY = o.seatY, floorY = o.floorY;
    const ink = o.ink, fwd = o.fwd;
    const wood = "#6B5A46";
    const quad = function (a, b, wa, wb) {
      const dx = b.x - a.x, dy = b.y - a.y, L = Math.hypot(dx, dy) || 1;
      const nx = -dy / L, ny = dx / L;
      return [{ x: a.x + nx * wa, y: a.y + ny * wa }, { x: b.x + nx * wb, y: b.y + ny * wb },
        { x: b.x - nx * wb, y: b.y - ny * wb }, { x: a.x - nx * wa, y: a.y - ny * wa }];
    };
    const part = function (poly, colour, op, lw, angle, seed) {
      P.colourAdd(S.hatch(poly, { color: colour, opacity: op, gap: 6.2, width: 10, angle: angle, over: 9, seed: seed }));
      P.inkAdd(S.outline(poly, { stroke: ink, width: lw, opacity: 0.8, amp: 2, over: 8, seed: seed + 3 }));
    };
    // the seat, seen slightly from the side: a slab running back from under the
    // hips, away from the direction the knees go
    const seatFront = { x: cx + fwd * HU * 0.62, y: seatY + HU * 0.04 };
    const seatBack = { x: cx - fwd * HU * 0.96, y: seatY };
    part(quad(seatFront, seatBack, HU * 0.14, HU * 0.16), wood, 0.5, 3.2, -6, 1101);
    // the back: one post and one rail, behind him. Two posts would close the
    // silhouette behind his shoulders and he would read as being in a box.
    const postTop = { x: seatBack.x - fwd * HU * 0.06, y: seatY - HU * 2.05 };
    part(quad(seatBack, postTop, HU * 0.11, HU * 0.09), wood, 0.44, 3, -80, 1111);
    const railA = { x: postTop.x + fwd * HU * 0.1, y: postTop.y + HU * 0.16 };
    const railB = { x: postTop.x - fwd * HU * 0.78, y: postTop.y + HU * 0.3 };
    part(quad(railA, railB, HU * 0.13, HU * 0.11), wood, 0.44, 3, -10, 1117);
    // two legs, front and back, splayed as a real chair is
    [[seatFront, 0.18], [seatBack, -0.22]].forEach(function (pr, i) {
      const topP = { x: pr[0].x, y: pr[0].y + HU * 0.1 };
      const footP = { x: pr[0].x + fwd * HU * pr[1], y: floorY - HU * 0.02 };
      part(quad(topP, footP, HU * 0.08, HU * 0.07), wood, 0.42, 2.8, -78, 1121 + i * 7);
    });
    return { seatFront: seatFront, seatBack: seatBack, postTop: postTop };
  }

  const TR = {
    kicker: { font: "Courier Prime", size: 28, weight: 400, colour: "structure", opacity: 0.7, tracking: ".16em", transform: "uppercase", maxChars: 34 },
    statement: { font: "Archivo Narrow", size: 62, weight: 700, colour: "structure", tracking: "-.02em", maxLines: 3, maxCharsPerLine: 22 },
    detail: { font: "Archivo Narrow", size: 30, weight: 400, colour: "structure", opacity: 0.85, maxLines: 2, maxCharsPerLine: 40 },
    label: { font: "Archivo Narrow", size: 34, weight: 500, colour: "structure", maxChars: 30 },
    figure: { font: "Courier Prime", size: 44, weight: 700, colour: "structure", maxChars: 8 },
    big: { font: "Courier Prime", size: 120, weight: 700, colour: "structure", maxChars: 6 },
    caption: { font: "Courier Prime", size: 26, weight: 400, colour: "structure", opacity: 0.72, maxChars: 60 },
  };

  // Both-true: every video opens on this
  function bothTrue(o) {
    const P = base(o, "both-true", TR), p = o.pal, w = o.w, h = o.h, land = w > h;
    const u = unitOf(h);
    const gutter = Math.round(u * 2.4);
    P.slot("kicker", land ? 150 : 80, land ? 96 : 190, w - (land ? 300 : 160), blockH(TR.kicker, 1), { align: "left", role: "kicker" });

    const spec = function (i, x, colW) {
      return {
        x: x, w: colW, align: "left", unit: u, roles: TR,
        blocks: [
          // Two lines, not three. At 22 characters per line a statement that runs
          // to three is already over the role's own maxChars, so the third line
          // was never copy — it was a reserved line of air under every headline,
          // and it is the whole reason this plate read loose.
          { name: "statement-" + (i + 1), role: "statement", lines: 2 },
          { name: "detail-" + (i + 1), role: "detail", lines: 2, gap: 0.85 },
          { name: "mark-" + (i + 1), role: "label", lines: 1, gap: 1.15, indent: 2.4 },
        ],
      };
    };

    if (land) {
      const cx = w / 2, colW = cx - 220;
      const s0 = spec(0, 150, colW), s1 = spec(1, cx + 70, colW);
      const top = Math.round((h - Math.max(measure(s0), measure(s1))) * 0.5);
      P.inkAdd(H.line(cx, top - u, cx - 8, top + Math.max(measure(s0), measure(s1)) + u, { stroke: p.structure, width: 4.6, opacity: 0.85, amp: 4.5, over: 14, seed: 31 }));
      [s0, s1].forEach(function (s, i) {
        const r = place(P, s, top);
        const mk = r.items["mark-" + (i + 1)];
        const as = Math.round(mk.h * 1.25);
        dirArrow(P, s.x, mk.y + (mk.h - as) / 2, as, i ? "down" : "up", 60 + i * 3);
      });
    } else {
      const colW = w - 160;
      const s0 = spec(0, 80, colW), s1 = spec(1, 80, colW);
      const h0 = measure(s0), h1 = measure(s1);
      // the divider sits between the two blocks in the same rhythm as everything
      // else, so the pause reads as a beat rather than as leftover space
      const total = h0 + gutter * 2 + ruleH(u) + h1;
      const top = Math.round((h - total) * 0.52);
      const r0 = place(P, s0, top);
      const dy = top + h0 + gutter;
      P.inkAdd(H.line(80, dy, w - 80, dy - 10, { stroke: p.structure, width: 4.6, opacity: 0.85, amp: 4.5, over: 14, seed: 31 }));
      const r1 = place(P, s1, dy + ruleH(u) + gutter);
      [r0, r1].forEach(function (r, i) {
        const mk = r.items["mark-" + (i + 1)];
        const as = Math.round(mk.h * 1.25);
        dirArrow(P, 80, mk.y + (mk.h - as) / 2, as, i ? "down" : "up", 60 + i * 3);
      });
    }
    P.slot("caption", land ? 150 : 80, h - (land ? 130 : 150), w - (land ? 300 : 160), blockH(TR.caption, 1), { align: "left", role: "caption" });
    return P;
  }

  // Unit ladder: one dollar at the top, subtractions down the frame
  function unitLadder(o) {
    const P = base(o, "unit-ladder", TR), p = o.pal, w = o.w, h = o.h, land = w > h;
    const steps = 5;
    const L = land ? 420 : 90, R = w - (land ? 420 : 90);
    P.slot("kicker", L, land ? 84 : 200, R - L, 50, { align: "left", role: "kicker" });
    const topY = land ? 160 : 290;
    P.slot("top-label", L, topY, (R - L) * 0.52, land ? 120 : 140, { align: "left", role: "label" });
    P.slot("top-value", L + (R - L) * 0.54, topY, (R - L) * 0.46, land ? 120 : 140, { align: "right", role: "big" });
    P.inkAdd(H.line(L - 10, topY + (land ? 136 : 160), R + 10, topY + (land ? 132 : 156), { stroke: p.structure, width: 5.4, opacity: 0.92, amp: 3.4, over: 12, seed: 41 }));
    const first = topY + (land ? 166 : 196);
    const lastH = land ? 150 : 190;
    const stepH = (h - (land ? 120 : 210) - lastH - first) / steps;
    for (let i = 1; i <= steps; i++) {
      const y = first + stepH * (i - 1);
      P.slot(`band-${i}`, L - 26, y + 2, R - L + 52, stepH - 6, { role: "highlight-band", overlay: "overlays/row-band" });
      // a drawn minus, so the arithmetic is visible without narration
      P.colourAdd(H.stroke([{ x: L - 4, y: y + stepH * 0.5 }, { x: L + 30, y: y + stepH * 0.5 }], { stroke: p.down, width: 7, amp: 2, over: 5, seed: 70 + i }));
      P.slot(`step-${i}-label`, L + 52, y + stepH * 0.14, (R - L) * 0.6, stepH * 0.72, { align: "left", role: "label" });
      P.slot(`step-${i}-value`, L + (R - L) * 0.68, y + stepH * 0.14, (R - L) * 0.32, stepH * 0.72, { align: "right", role: "figure" });
      if (i < steps) P.inkAdd(H.line(L, y + stepH, R, y + stepH, { stroke: p.structure, width: 1.9, opacity: 0.42, amp: 2.4, over: 7, seed: 90 + i }));
    }
    const outY = first + stepH * steps + (land ? 18 : 26);
    P.inkAdd(H.line(L - 10, outY, R + 10, outY - 4, { stroke: p.structure, width: 5, opacity: 0.9, amp: 3, over: 11, seed: 51 }));
    P.slot("out-label", L, outY + 22, (R - L) * 0.5, lastH - 40, { align: "left", role: "label" });
    P.slot("out-value", L + (R - L) * 0.5, outY + 14, (R - L) * 0.5, lastH - 30, { align: "right", role: "big" });
    return P;
  }

  // Closing plate: three lines of what to watch, room for a date. Not a verdict.
  function closingPlate(o) {
    const P = base(o, "closing", TR), p = o.pal, w = o.w, h = o.h, land = w > h;
    const L = land ? 200 : 90, R = w - (land ? 200 : 90);
    P.slot("kicker", L, land ? 130 : 280, R - L, 52, { align: "left", role: "kicker" });
    const top = land ? 250 : 430;
    const lineH = land ? 170 : 250;
    for (let i = 1; i <= 3; i++) {
      const y = top + lineH * (i - 1);
      P.colourAdd(H.stroke([{ x: L, y: y + 42 }, { x: L + 54, y: y + 40 }], { stroke: p.attention, width: 8, amp: 2.4, over: 7, seed: 110 + i }));
      P.slot(`line-${i}`, L + 82, y, R - L - 82, lineH - (land ? 40 : 60), { align: "left", role: "detail" });
      P.inkAdd(H.line(L, y + lineH - (land ? 34 : 48), R, y + lineH - (land ? 38 : 52), { stroke: p.structure, width: 1.8, opacity: 0.36, amp: 2.6, over: 8, seed: 130 + i }));
    }
    const dY = top + lineH * 3 + (land ? 30 : 60);
    P.slot("date-label", L, dY, (R - L) * 0.5, 60, { align: "left", role: "caption" });
    P.slot("date", L + (R - L) * 0.5, dY - 8, (R - L) * 0.5, 76, { align: "right", role: "figure" });
    return P;
  }

  // Row spotlight: one row lifted out of the table, enlarged
  function rowSpotlight(o) {
    const P = base(o, "row-spotlight", TR), p = o.pal, w = o.w, h = o.h, land = w > h;
    const L = land ? 140 : 60, R = w - (land ? 140 : 60);
    const cardT = land ? 300 : 620, cardB = land ? 780 : 1300;
    P.slot("kicker", L, land ? 120 : 300, R - L, 52, { align: "left", role: "kicker" });
    P.colourAdd(H.hatch(H.polyRect(L - 24, cardT - 30, R - L + 48, cardB - cardT + 60), { color: p.ground2, opacity: 0.5, gap: 8, width: 13, angle: -3, over: 20, seed: 141 }));
    P.inkAdd(H.outline(H.polyRect(L - 24, cardT - 30, R - L + 48, cardB - cardT + 60), { stroke: p.structure, width: 4, opacity: 0.9, amp: 3.4, over: 13, seed: 142 }));
    const labelW = (R - L) * (land ? 0.28 : 0.3);
    const colsL = L + labelW, colW = (R - colsL) / 6;
    P.slot("label", L + 10, cardT + 10, labelW - 30, cardB - cardT - 20, { align: "left", role: "label" });
    for (let c = 1; c <= 6; c++) {
      const x = colsL + colW * (c - 1);
      P.slot(`head-${c}`, x + 6, cardT + 4, colW - 12, 60, { align: "right", role: "caption" });
      P.slot(`cell-${c}`, x + 6, cardT + 76, colW - 12, cardB - cardT - 96, { align: "right", role: "figure" });
      if (c > 1) P.inkAdd(H.line(x, cardT + 6, x, cardB - 6, { stroke: p.structure, width: 1.6, opacity: 0.24, amp: 3, seed: 150 + c }));
    }
    P.slot("caption", L, cardB + (land ? 60 : 90), R - L, 70, { align: "left", role: "caption" });
    return P;
  }

  // Flow plate: input left, boxes across, output right. 16:9 only.
  function flowPlate(o) {
    const P = base(o, "flow", TR), p = o.pal, w = o.w, h = o.h;
    const boxes = 3, midY = h * 0.54, boxH = 260, boxW = 300;
    P.slot("kicker", 150, 110, w - 300, 52, { align: "left", role: "kicker" });
    /* LEGACY PASS, rebuild-21: input and output ran 6 units into the 5% margin
     * each side. The chain starts at the margin and the output stops at it. */
    const inX = Math.ceil(w * 0.05) + 4;
    P.slot("input", inX, midY - 90, 240, 180, { align: "left", role: "label" });
    const gap = 84;
    const startX = inX + 240 + gap;
    for (let i = 1; i <= boxes; i++) {
      const x = startX + (boxW + gap) * (i - 1);
      P.colourAdd(H.hatch(H.polyRect(x, midY - boxH / 2, boxW, boxH), { color: p.ground2, opacity: 0.5, gap: 8, width: 13, angle: -3, over: 18, seed: 160 + i }));
      P.inkAdd(H.outline(H.polyRect(x, midY - boxH / 2, boxW, boxH), { stroke: p.structure, width: 4, opacity: 0.9, amp: 3.4, over: 12, seed: 170 + i }));
      P.slot(`box-${i}`, x + 22, midY - boxH / 2 + 22, boxW - 44, boxH - 44, { align: "left", role: "label" });
      // arrow into this box
      const ax = x - gap + 12, ay = midY;
      P.inkAdd(H.stroke([{ x: ax, y: ay }, { x: x - 12, y: ay }], { stroke: p.structure, width: 3.4, amp: 2.4, over: 6, seed: 180 + i }));
      P.inkAdd(H.stroke([{ x: x - 34, y: ay - 16 }, { x: x - 12, y: ay }, { x: x - 34, y: ay + 16 }], { stroke: p.structure, width: 3.4, amp: 1.8, over: 4, seed: 190 + i }));
      P.slot(`arrow-${i}`, ax - 10, ay - 74, gap + 20, 60, { align: "center", role: "caption" });
    }
    const outX = startX + (boxW + gap) * boxes;
    P.inkAdd(H.stroke([{ x: outX - gap + 12, y: midY }, { x: outX - 12, y: midY }], { stroke: p.structure, width: 3.4, amp: 2.4, over: 6, seed: 201 }));
    P.inkAdd(H.stroke([{ x: outX - 34, y: midY - 16 }, { x: outX - 12, y: midY }, { x: outX - 34, y: midY + 16 }], { stroke: p.structure, width: 3.4, amp: 1.8, over: 4, seed: 202 }));
    P.slot(`arrow-${boxes + 1}`, outX - gap + 2, midY - 74, gap + 20, 60, { align: "center", role: "caption" });
    P.slot("output", outX + 34, midY - 100, Math.floor(w * 0.95) - 4 - (outX + 34), 200, { align: "left", role: "statement" });
    P.slot("caption", 150, h - 150, w - 300, 70, { align: "left", role: "caption" });
    return P;
  }

  // ---------------- multiple bridge ----------------
  // USE WHEN a headline multiple is not the multiple the argument is about. One
  // figure walked into another, and what came out at each step.
  //
  // This is the clearest move in the valuation chapter and there was no way to
  // draw it. A trailing P/E crushed by deal amortisation says nothing useful; the
  // whole argument is the walk down to the forward number, and a walk is three
  // anchors and two removals.
  //
  // NOT A UNIT LADDER, which already exists two functions up and looks similar
  // enough to confuse. unit-ladder subtracts line items from ONE figure and the
  // rows are all in the same unit — dollars out of a dollar. Here every step is a
  // DIFFERENT multiple against a different denominator, so the steps cannot stack
  // in a column and be read as arithmetic. They sit side by side and the removal
  // goes in the gap.
  //
  // WEIGHTING. Steps 1 and 2 are the same size in neutralData: they are waypoints
  // doing the same job. Step 3 is larger and in structure, because it is the
  // number the chapter argues for. Two sizes for two jobs — the walk-down itself
  // is not a third job, and sizing the figures 3-2-1 to "show the fall" would draw
  // a chart of the multiple shrinking, which is not what happened: nothing fell,
  // the denominator changed.
  //
  // The removals are the only marks on this plate carrying direction colour. A
  // multiple is not up or down; a subtraction is.
  function multipleBridge(o) {
    const w = o.w, h = o.h;
    const roles = {
      kicker: TR.kicker,
      // Courier advances at ~0.6em, so maxChars is the inner box width divided by
      // size*0.6 — picked from the geometry rather than hoped for.
      waypoint: { font: "Courier Prime", size: 96, weight: 700, colour: "neutralData", maxChars: 6 },
      outcome: { font: "Courier Prime", size: 118, weight: 700, colour: "structure", maxChars: 5 },
      step: { font: "Archivo Narrow", size: 32, weight: 500, colour: "structure", opacity: 0.9, maxLines: 2, maxCharsPerLine: 22 },
      strike: { font: "Archivo Narrow", size: 28, weight: 400, colour: "down", maxLines: 2, maxCharsPerLine: 26 },
      caption: TR.caption,
    };
    const P = base(o, "multiple-bridge", roles), p = o.pal;
    P.meta.stepsNote = "three steps and two connectors, fixed. A fourth step is a different plate: structure/unit-ladder subtracts line items from one figure in one unit, this converts one multiple into another and every step has a different denominator.";
    P.meta.weightNote = "steps 1 and 2 are neutralData at one size (waypoints, same job); step 3 is structure and larger (the number the chapter argues for). Sizing the three 3-2-1 would draw the multiple shrinking, and nothing shrank — the denominator changed.";
    P.meta.linkNote = "link-N-note is what was REMOVED to get to the next figure — drawn in down with a minus beside it and a drop line to the connector it belongs to. The removals are the only direction colour on the plate: a multiple is not up or down, a subtraction is.";
    P.meta.aspectNote = "16:9 only. Three figures side by side need the width, and a trailing-to-forward walk does not belong in seventy-five seconds.";

    const boxes = 3, boxW = 420, gap = 215, boxH = 260;
    const startX = Math.round((w - (boxW * boxes + gap * (boxes - 1))) / 2);
    const midY = Math.round(h * 0.5);
    const boxT = midY - boxH / 2, boxB = midY + boxH / 2;
    P.slot("kicker", 150, 110, w - 300, blockH(roles.kicker, 1), { align: "left", role: "kicker" });

    for (let i = 1; i <= boxes; i++) {
      const x = startX + (boxW + gap) * (i - 1);
      const last = i === boxes;
      P.colourAdd(H.hatch(H.polyRect(x, boxT, boxW, boxH), { color: p.ground2, opacity: 0.5, gap: 8, width: 13, angle: -3, over: 18, seed: 820 + i }));
      P.inkAdd(H.outline(H.polyRect(x, boxT, boxW, boxH), { stroke: p.structure, width: last ? 5.2 : 3.6, opacity: last ? 0.95 : 0.82, amp: 3.4, over: 12, seed: 830 + i }));
      P.slot(`step-${i}-figure`, x + 22, boxT + 26, boxW - 44, blockH(last ? roles.outcome : roles.waypoint, 1), { align: "center", role: last ? "outcome" : "waypoint" });
      P.slot(`step-${i}-label`, x + 22, boxT + 174, boxW - 44, blockH(roles.step, 2), { align: "center", role: "step" });
      P.inkAdd(H.line(x + 60, boxT + 158, x + boxW - 60, boxT + 155, { stroke: p.structure, width: 1.9, opacity: 0.34, amp: 2.4, over: 7, seed: 840 + i }));

      if (i === boxes) continue;
      // the connector, then the removal hung under it
      const ax = x + boxW, bx = x + boxW + gap, cx = Math.round((ax + bx) / 2);
      P.inkAdd(H.stroke([{ x: ax + 18, y: midY }, { x: bx - 20, y: midY }], { stroke: p.structure, width: 3.6, amp: 2.4, over: 6, seed: 850 + i }));
      P.inkAdd(H.stroke([{ x: bx - 44, y: midY - 17 }, { x: bx - 20, y: midY }, { x: bx - 44, y: midY + 17 }], { stroke: p.structure, width: 3.6, amp: 1.8, over: 4, seed: 860 + i }));
      const noteW = gap + 120, noteY = boxB + 48;
      // the tie, from the connector down to the removal it belongs to. Slanted
      // rather than dropped on the centre: the note reads left to right from its
      // minus, so the line has to land on the minus and not in the middle of a
      // sentence.
      P.inkAdd(H.line(cx - 6, midY + 24, cx - noteW / 2 + 4, noteY + 10, { stroke: p.structure, width: 1.8, opacity: 0.3, amp: 2.2, over: 5, seed: 870 + i }));
      // a drawn minus, in down, so the subtraction is visible without narration
      P.colourAdd(H.stroke([{ x: cx - noteW / 2, y: noteY + 20 }, { x: cx - noteW / 2 + 34, y: noteY + 19 }], { stroke: p.down, width: 6.4, amp: 2, over: 5, seed: 880 + i }));
      P.slot(`link-${i}-note`, cx - noteW / 2 + 52, noteY, noteW - 52, blockH(roles.strike, 2), { align: "left", role: "strike" });
    }
    P.slot("caption", 150, h - 130, w - 300, blockH(roles.caption, 1), { align: "left", role: "caption" });
    return P;
  }

  // ---------------- single figure ----------------
  function figRoles(land, big) {
    return {
      kicker: TR.kicker, caption: TR.caption, label: TR.label, detail: TR.detail,
      huge: { font: "Courier Prime", size: big, weight: 700, colour: "structure", tracking: "-.02em", maxChars: land ? 7 : 6 },
      figure: { font: "Courier Prime", size: land ? 84 : 76, weight: 700, colour: "structure", maxChars: 8 },
      statement: TR.statement,
    };
  }

  function bigNumber(o) {
    const land = o.w > o.h, w = o.w, h = o.h;
    // The huge role is sized so a full-length value (maxChars) still fits the
    // column: Courier advances at ~0.6em, so size = columnWidth / (maxChars*0.6).
    // Picking a size first and hoping is how you get a 7-character value running
    // off the plate.
    // DROP TEN: THE SIZE IS DERIVED PER LAYOUT, because the two layouts do not
    // share a column. The comment above is the kit's own rule — size =
    // columnWidth / (maxChars * 0.6) — and layout 1 obeys it: 1,480 units of
    // measure at 350u holds its seven characters. Layout 2 hardcodes a 900-unit
    // number column and INHERITED layout 1's 350u, which derives FOUR characters,
    // so "87.4%", "1,284" and "$15.6bn" all rendered blank — in the plate whose
    // entire job is one number. A borrowed quantity, correct where it came from.
    // Portrait was already right by luck: its column is 920 and 250u derives six.
    const hugeCols = o.layout === 1 ? (land ? 1480 : 900) : (land ? 900 : w - 160);
    const hugeChars = land ? 7 : 6;
    const hugeSize = Math.min(land ? 350 : 250, Math.floor(hugeCols / (hugeChars * 0.5996)));
    const P = base(o, "big-number-l" + o.layout, figRoles(land, hugeSize));
    P.meta.hugeDerivation = "size = numberColumn / (maxChars x 0.5996), capped at the layout-1 size. Layout " +
      o.layout + ": column " + hugeCols + " units, target " + hugeChars + " characters, size " + hugeSize +
      "u. Never authored — layout 2 shipped at layout 1's 350u against a 900-unit column and could not draw a five-character number.";
    P.meta.layout = o.layout;
    const p = o.pal;
    if (o.layout === 1) {
      // centred: kicker, the number on a field, a rule, label, caption
      const L = land ? 220 : 90, R = w - (land ? 220 : 90);
      const u = unitOf(h), roles = P.meta.typeRoles;
      const spec = {
        x: L, w: R - L, align: "center", unit: u, roles: roles,
        blocks: [
          { name: "kicker", role: "kicker", lines: 1 },
          { name: "value", role: "huge", lines: 1, gap: 1.2 },
          { rule: true, gap: 0.7, width: 0.5, weight: 7, seed: 211 },
          { name: "label", role: "label", lines: 2, gap: 0.9 },
          { name: "caption", role: "caption", lines: 1, gap: 1.4 },
        ],
      };
      const total = measure(spec);
      // A stack centred on the geometric middle reads LOW, because the eye is
      // pulled by the big number. Sit it a little above centre.
      const top = Math.round((h - total) * 0.44);
      const vy = top + blockH(roles.kicker, 1) + Math.round(1.2 * u);
      const vh = blockH(roles.huge, 1);
      // Full-bleed band rather than a panel around the digits: a band cannot look
      // mis-sized against text whose width the plate does not know, and it reads
      // as structure instead of as a highlighter smear.
      field(P, 0, vy + (vh - Math.round(vh * 0.6)) / 2, w, Math.round(vh * 0.6), 214, 0.44);
      place(P, spec, top);
    } else {
      // asymmetric: number left, the words stacked right of it
      const L = land ? 150 : 80;
      const numW = land ? 900 : w - 160;
      const numY = land ? 280 : 420;
      P.slot("kicker", L, land ? 150 : 300, numW, 54, { align: "left", role: "kicker" });
      P.slot("value", L, numY, numW, land ? 340 : 280, { align: "left", role: "huge" });
      if (land) {
        const RX = L + numW + 90;
        P.inkAdd(H.line(RX - 46, numY - 10, RX - 50, numY + 340, { stroke: p.structure, width: 4.4, opacity: 0.8, amp: 4, over: 12, seed: 212 }));
        P.slot("label", RX, numY + 10, w - RX - 150, 120, { align: "left", role: "label" });
        P.slot("detail", RX, numY + 150, w - RX - 150, 190, { align: "left", role: "detail" });
      } else {
        const ry = numY + 300;
        P.inkAdd(H.line(L, ry, w - 80, ry - 6, { stroke: p.structure, width: 5, opacity: 0.85, amp: 3.4, over: 12, seed: 212 }));
        P.slot("label", L, ry + 30, w - 160, 120, { align: "left", role: "label" });
        P.slot("detail", L, ry + 170, w - 160, 200, { align: "left", role: "detail" });
      }
      P.slot("caption", L, h - (land ? 140 : 190), w - L * 2, 64, { align: "left", role: "caption" });
    }
    return P;
  }

  function bigFraction(o) {
    const land = o.w > o.h, w = o.w, h = o.h, p = o.pal;
    const P = base(o, "big-fraction", figRoles(land, land ? 190 : 160));
    const L = land ? 260 : 90, R = w - (land ? 260 : 90);
    const mid = h * (land ? 0.5 : 0.46);
    P.slot("kicker", L, land ? 120 : 260, R - L, 54, { align: "left", role: "kicker" });
    P.slot("numerator", L, mid - (land ? 230 : 250), (R - L) * 0.62, land ? 200 : 180, { align: "left", role: "huge" });
    P.slot("numerator-label", L + (R - L) * 0.66, mid - (land ? 200 : 220), (R - L) * 0.34, land ? 140 : 130, { align: "left", role: "label" });
    P.inkAdd(H.line(L - 14, mid, R + 14, mid - 7, { stroke: p.structure, width: 9, opacity: 0.95, amp: 4, over: 18, seed: 221 }));
    P.slot("denominator", L, mid + (land ? 40 : 50), (R - L) * 0.62, land ? 200 : 180, { align: "left", role: "huge" });
    P.slot("denominator-label", L + (R - L) * 0.66, mid + (land ? 70 : 84), (R - L) * 0.34, land ? 140 : 130, { align: "left", role: "label" });
    const eqY = mid + (land ? 280 : 260);
    P.inkAdd(H.stroke([{ x: L, y: eqY + 26 }, { x: L + 70, y: eqY + 24 }], { stroke: p.structure, width: 5, amp: 2.4, over: 6, seed: 222 }));
    P.inkAdd(H.stroke([{ x: L, y: eqY + 50 }, { x: L + 70, y: eqY + 48 }], { stroke: p.structure, width: 5, amp: 2.4, over: 6, seed: 223 }));
    P.slot("result", L + 100, eqY, (R - L) * 0.5, land ? 110 : 130, { align: "left", role: "figure" });
    P.slot("caption", L, h - (land ? 130 : 180), R - L, 64, { align: "left", role: "caption" });
    return P;
  }

  function compare(o) {
    const land = o.w > o.h, w = o.w, h = o.h, p = o.pal;
    // PORTRAIT `side` WAS THE STACKED PLATE UNDER ANOTHER NAME.
    //
    // The branch read `o.mode === "side" && land`, so in 9:16 the side-by-side
    // fell through to stacked — and `figures/compare-side-9x16` shipped as a
    // distinct key whose three frames are BYTE-IDENTICAL to
    // `figures/compare-stacked-9x16`. Two assets, one drawing, and a manifest
    // saying `type: "compare-side"` over artwork that is not.
    //
    // Found by the new per-frame baseline (§1.1), which is the first artefact in
    // this project able to see it: nothing about a single plate is wrong, and no
    // screenshot of either one would look like a defect. It took hashing every
    // frame in the library and noticing two signatures collide.
    //
    // Fixed by making portrait `side` a real re-author rather than a fall-through.
    // The reason it was avoided is real — two columns in 9:16 are ~430 units wide
    // and the landscape figure size does not fit — so the figure is sized to the
    // column by the same rule bigNumber uses: size = columnWidth / (maxChars *
    // 0.6), Courier's advance. A short comparing two numbers is a real beat and
    // now it has a real plate.
    const sideCols = !land && o.mode === "side";
    const roles = figRoles(land, land ? 170 : 160);
    if (sideCols) {
      const colW = (w - 160 - 40) / 2;
      roles.huge = Object.assign({}, roles.huge, { size: Math.floor(colW / (roles.huge.maxChars * 0.6)) });
      roles.label = Object.assign({}, roles.label, { maxCharsPerLine: 14 });
    }
    const P = base(o, "compare-" + o.mode, roles);
    P.meta.mode = o.mode;
    const L = land ? 150 : 80, R = w - (land ? 150 : 80);
    P.slot("kicker", L, land ? 110 : 250, R - L, 54, { align: "left", role: "kicker" });
    if (o.mode === "side" && land) {
      const cx = w / 2;
      P.inkAdd(H.line(cx, 250, cx - 10, h - 220, { stroke: p.structure, width: 4.4, opacity: 0.8, amp: 4.5, over: 14, seed: 231 }));
      [0, 1].forEach((i) => {
        const X = i ? cx + 80 : L, W = cx - L - 80;
        P.slot(`label-${i + 1}`, X, 300, W, 90, { align: "left", role: "label" });
        P.slot(`value-${i + 1}`, X, 410, W, 220, { align: "left", role: "huge" });
        P.slot(`detail-${i + 1}`, X, 660, W, 150, { align: "left", role: "detail" });
      });
    } else if (sideCols) {
      // Two columns, a rule between them, figures sized to the column. The same
      // composition as the landscape plate at a size a phone can carry — which is
      // what "a re-author, never a crop" means here.
      const cx = w / 2, gap = 20;
      const colW = (R - L - gap * 2) / 2;
      const top = Math.round(h * 0.30);
      P.inkAdd(H.line(cx, top - 30, cx - 8, top + 560, { stroke: p.structure, width: 4, opacity: 0.78, amp: 4.2, over: 13, seed: 231 }));
      [0, 1].forEach(function (i) {
        const X = i ? cx + gap : L;
        P.slot(`label-${i + 1}`, X, top, colW, 96, { align: "left", role: "label" });
        P.slot(`value-${i + 1}`, X, top + 118, colW, blockH(roles.huge, 1), { align: "left", role: "huge" });
        P.slot(`detail-${i + 1}`, X, top + 132 + blockH(roles.huge, 1), colW, 210, { align: "left", role: "detail" });
      });
      P.slot("delta", L, top + 620, R - L, 110, { align: "left", role: "figure" });
    } else {
      // stacked: one above the other, the second offset so they never read as a pair of equals
      const top = land ? 210 : 380;
      const blockH = land ? 320 : 480;
      [0, 1].forEach((i) => {
        const Y = top + blockH * i;
        const X = L + (i ? (land ? 120 : 60) : 0);
        P.slot(`label-${i + 1}`, X, Y, R - X, land ? 70 : 90, { align: "left", role: "label" });
        P.slot(`value-${i + 1}`, X, Y + (land ? 82 : 108), R - X, land ? 210 : 250, { align: "left", role: "huge" });
        if (i === 0) P.inkAdd(H.line(L, Y + blockH - (land ? 20 : 40), R, Y + blockH - (land ? 26 : 46), { stroke: p.structure, width: 3.4, opacity: 0.65, amp: 3, over: 10, seed: 241 }));
      });
      P.slot("delta", L, top + blockH * 2 + (land ? -20 : 10), R - L, land ? 92 : 110, { align: "left", role: "figure" });
    }
    P.slot("caption", L, h - (land ? 130 : 180), R - L, 64, { align: "left", role: "caption" });
    return P;
  }

  // ---------------- cards ----------------
  function cardShell(P, x, y, w, h, seed) {
    const p = P.pal;
    // §1.5: the card's own edge and its tooth. The paper, not the words on it.
    P.colourAdd(H.breathe(function () {
      return H.hatch(H.polyRect(x, y, w, h), { color: p.ground2, opacity: 0.45, gap: 8.5, width: 13, angle: -3, over: 20, seed: seed });
    }));
    P.inkAdd(H.breathe(function () {
      return H.outline(H.polyRect(x, y, w, h), { stroke: p.structure, width: 4.2, opacity: 0.9, amp: 3.6, over: 14, seed: seed + 1 });
    }));
  }

  function definitionCard(o) {
    const land = o.w > o.h, w = o.w, h = o.h;
    const P = base(o, "definition-card", { kicker: TR.kicker, term: { font: "Archivo Narrow", size: land ? 76 : 80, weight: 700, colour: "structure", tracking: "-.02em", maxChars: land ? 24 : 20 }, body: { font: "Archivo Narrow", size: land ? 40 : 44, weight: 400, colour: "structure", maxLines: land ? 4 : 5, maxCharsPerLine: land ? 46 : 25 }, example: TR.caption });
    const u = unitOf(h), roles = P.meta.typeRoles;
    const L = land ? 260 : 90, R = w - (land ? 260 : 90);
    const pad = Math.round(u * 1.6);
    const spec = {
      x: L, w: R - L, align: "left", unit: u, roles: roles,
      blocks: [
        { name: "kicker", role: "kicker", lines: 1 },
        { name: "term", role: "term", lines: 1, gap: 0.8 },
        { rule: true, gap: 0.7, width: 0.62, weight: 5, seed: 253 },
        { name: "body", role: "body", lines: land ? 3 : 5, gap: 1.1 },
      ],
    };
    const bodyH = measure(spec);
    const exH = blockH(roles.example, 1);
    // The example is not a footnote drifting at the bottom of a big empty card —
    // it is the half of a definition that makes it concrete, so it gets its own
    // field and the card closes right under it.
    const total = bodyH + Math.round(u * 1.8) + exH + Math.round(u * 1.2);
    const T = Math.round((h - total) * 0.46);
    cardShell(P, L - pad, T - pad, (R - L) + pad * 2, total + pad * 2, 251);
    place(P, spec, T);
    const exY = T + bodyH + Math.round(u * 1.8);
    field(P, L - Math.round(u * 0.5), exY - Math.round(u * 0.45), (R - L) + u, exH + Math.round(u * 0.9), 255, 0.5);
    P.slot("example", L, exY, R - L, exH, { align: "left", role: "example" });
    return P;
  }

  function quotePull(o) {
    const land = o.w > o.h, w = o.w, h = o.h, p = o.pal;
    const P = base(o, "quote-pull", { body: { font: "Archivo Narrow", size: land ? 62 : 54, weight: 500, colour: "structure", maxLines: 4, maxCharsPerLine: land ? 40 : 26 }, attribution: TR.label, source: TR.caption });
    const L = land ? 300 : 140, R = w - (land ? 220 : 80);
    const T = land ? 250 : 520;
    // oversized opening mark, drawn
    const mx = L - (land ? 150 : 120), my = T + (land ? 40 : 30);
    [0, 1].forEach((i) => {
      const ox = mx + i * (land ? 62 : 44);
      P.colourAdd(H.stroke([{ x: ox + 40, y: my }, { x: ox + 6, y: my + 52 }, { x: ox + 4, y: my + 108 }], { stroke: p.attention, width: land ? 15 : 12, amp: 3.4, over: 8, seed: 261 + i }));
      P.artBox(`quote-mark-${i + 1}`, ox - 8, my - 14, 66, 136);
    });
    P.slot("body", L, T, R - L, land ? 400 : 560, { align: "left", role: "body" });
    const aY = T + (land ? 440 : 610);
    P.inkAdd(H.line(L, aY, L + (land ? 220 : 160), aY - 4, { stroke: p.structure, width: 4, opacity: 0.85, amp: 2.6, over: 9, seed: 263 }));
    P.slot("attribution", L, aY + 26, R - L, land ? 80 : 90, { align: "left", role: "attribution" });
    P.slot("source", L, aY + (land ? 120 : 132), R - L, 60, { align: "left", role: "source" });
    return P;
  }

  function criteriaCard(o) {
    const land = o.w > o.h, w = o.w, h = o.h, p = o.pal;
    const P = base(o, "criteria-card", { title: { font: "Archivo Narrow", size: land ? 60 : 52, weight: 700, colour: "structure", tracking: "-.02em", maxLines: 2, maxCharsPerLine: land ? 34 : 24 }, row: { font: "Archivo Narrow", size: land ? 40 : 36, weight: 400, colour: "structure", maxLines: 2, maxCharsPerLine: land ? 42 : 26 }, caption: TR.caption });
    const L = land ? 240 : 90, R = w - (land ? 240 : 90);
    const T = land ? 170 : 400;
    P.slot("title", L, T, R - L, land ? 150 : 200, { align: "left", role: "title" });
    const rowT = T + (land ? 200 : 260);
    const rowH = land ? 190 : 300;
    for (let i = 1; i <= 3; i++) {
      const y = rowT + rowH * (i - 1);
      const box = H.polyRect(L, y, land ? 78 : 70, land ? 78 : 70);
      P.inkAdd(H.outline(box, { stroke: p.structure, width: 4, opacity: 0.9, amp: 3, over: 10, seed: 270 + i }));
      P.slot(`check-${i}`, L, y, land ? 78 : 70, land ? 78 : 70, { role: "check", note: "true/false mark drawn by code inside the box" });
      P.slot(`row-${i}`, L + (land ? 120 : 106), y - 4, R - L - (land ? 120 : 106), rowH - (land ? 50 : 80), { align: "left", role: "row" });
    }
    P.slot("caption", L, h - (land ? 140 : 200), R - L, 64, { align: "left", role: "caption" });
    return P;
  }

  // Timeline: six dated marks, labels alternating either side of the rule
  function timeline(o) {
    const land = o.w > o.h, w = o.w, h = o.h, p = o.pal;
    const P = base(o, "timeline", { kicker: TR.kicker, date: { font: "Courier Prime", size: land ? 32 : 28, weight: 700, colour: "structure", maxChars: 8 }, label: { font: "Archivo Narrow", size: land ? 32 : 28, weight: 400, colour: "structure", maxLines: 2, maxCharsPerLine: land ? 26 : 20 }, caption: TR.caption });
    if (land) {
      const L = 170, R = w - 170, y = h * 0.52;
      P.slot("kicker", L, 120, R - L, 54, { align: "left", role: "kicker" });
      P.inkAdd(H.line(L - 30, y, R + 30, y - 6, { stroke: p.structure, width: 5.4, opacity: 0.92, amp: 3.6, over: 16, seed: 281 }));
      const step = (R - L) / 5;
      for (let i = 1; i <= 6; i++) {
        const cx = L + step * (i - 1), up = i % 2 === 1;
        P.inkAdd(H.line(cx, y - 24, cx, y + 24, { stroke: p.structure, width: 3.6, opacity: 0.85, amp: 1.6, over: 5, seed: 290 + i }));
        /* LEGACY PASS, rebuild-21: the end labels were centred on the end ticks and
         * half of each fell past the 5% margin. The two ends align inward from
         * their tick, date and label together. */
        const end = i === 1 ? "left" : i === 6 ? "right" : "center";
        const bx = end === "left" ? cx - 20 : end === "right" ? cx + 20 - step * 0.92 : cx - step * 0.46;
        P.slot(`date-${i}`, bx, up ? y - 116 : y + 52, step * 0.92, 48, { align: end, role: "date" });
        P.slot(`label-${i}`, bx, up ? y - 236 : y + 108, step * 0.92, 110, { align: end, role: "label" });
      }
      P.slot("caption", L, h - 130, R - L, 64, { align: "left", role: "caption" });
    } else {
      const T = 420, B = h - 300, x = w * 0.42;
      P.slot("kicker", 80, 280, w - 160, 54, { align: "left", role: "kicker" });
      P.inkAdd(H.line(x, T - 30, x - 8, B + 30, { stroke: p.structure, width: 5.4, opacity: 0.92, amp: 3.6, over: 16, seed: 281 }));
      const step = (B - T) / 5;
      for (let i = 1; i <= 6; i++) {
        const cy = T + step * (i - 1);
        P.inkAdd(H.line(x - 24, cy, x + 24, cy, { stroke: p.structure, width: 3.6, opacity: 0.85, amp: 1.6, over: 5, seed: 290 + i }));
        P.slot(`date-${i}`, 80, cy - 26, x - 130, 52, { align: "right", role: "date" });
        P.slot(`label-${i}`, x + 54, cy - 40, w - x - 130, 100, { align: "left", role: "label" });
      }
      P.slot("caption", 80, h - 180, w - 160, 64, { align: "left", role: "caption" });
    }
    return P;
  }

  // ---------------- peers: the complex, one row each ----------------
  // USE WHEN the beat is "it did not move alone". Two figure columns, because a
  // strip carrying only the move is a fact with no consequence: the move says
  // what happened today, the forward multiple says what the market now thinks of
  // it. Ticker, move, multiple — a third figure does not survive a 3-second read.
  //
  // Emphasis is decided here rather than left to the operator: the MOVE is the
  // largest figure (it is the beat), the multiple is secondary, the ticker is the
  // smallest — it is a label, not a number. The subject's ticker is drawn in
  // structure and every peer's in otherParty, so the row you are in is legible
  // with no highlight at all, which keeps band-N free for the row the voice-over
  // is actually on.
  //
  // No ground2 field behind the rows, deliberately. row-band is ground2, and a
  // ground2 band on a ground2 panel is the invisible-highlight defect this
  // library has already shipped once. The strip stands on rules instead.
  function peerStrip(o) {
    const w = o.w, h = o.h, land = w > h, p = o.pal;
    const rows = land ? 5 : 4;
    const roles = {
      unit: { font: "Courier Prime", size: 26, weight: 400, colour: "structure", opacity: 0.72, tracking: "0.04em", maxChars: land ? 46 : 38 },
      period: { font: "Archivo Narrow", size: land ? 26 : 24, weight: 600, colour: "structure", opacity: 0.68, tracking: "0.06em", maxChars: 12 },
      tickerSubject: { font: "Courier Prime", size: land ? 56 : 52, weight: 700, colour: "structure", maxChars: 7 },
      ticker: { font: "Courier Prime", size: land ? 48 : 46, weight: 700, colour: "otherParty", maxChars: 7 },
      move: { font: "Courier Prime", size: land ? 62 : 58, weight: 700, colour: "down", maxChars: 7 },
      moveUp: { font: "Courier Prime", size: land ? 62 : 58, weight: 700, colour: "up", maxChars: 7 },
      fwd: { font: "Courier Prime", size: land ? 48 : 44, weight: 700, colour: "otherParty", maxChars: 7 },
      caption: { font: "Courier Prime", size: 26, weight: 400, colour: "structure", opacity: 0.72, maxChars: 60 },
    };
    const P = H.Plate({
      key: o.key, w, h, seed: o.seed || 77, pal: p,
      meta: {
        aspect: land ? "16x9" : "9x16", family: "peers", type: "peer-strip", rows, typeRoles: roles,
        moveNote: "move-N is authored in the down colour, because a peer strip is called for when a complex moves together and that move is almost always red. A green row is a role override on the shot: boxes['move-2'] = { …rect, role: 'moveUp' }.",
        subjectNote: "row 1 is the subject — its ticker role is tickerSubject (structure). Rows 2+ are otherParty.",
      },
    });
    P.colourAdd(surfaceFurniture(P, SURFACES[p.surfaceKey]));

    const u = unitOf(h);
    const m = { l: land ? 190 : 84, r: land ? 190 : 84, t: land ? 88 : 186, b: land ? 84 : 150 };
    const L = m.l, R = w - m.r;
    const unitH = blockH(roles.unit, 1);
    P.slot("unit", L, m.t, R - L, unitH, { align: "left", role: "unit" });

    const headH = blockH(roles.period, 1);
    const capH = blockH(roles.caption, 1);
    // A row's height is a multiple of the figure in it, never the frame divided
    // by the row count: dividing 1,300 units among four rows of 58-unit type puts
    // 260 units of air inside every row, and no constant moved anywhere fixes
    // that. Measure the type, stack, then centre the block in what is left.
    const rowH = Math.round(blockH(roles.move, 1) * (land ? 1.85 : 1.95));
    const availTop = m.t + unitH + Math.round(u * (land ? 2.2 : 3));
    const availBot = h - m.b - capH - Math.round(u * 1.8);
    const headGap = Math.round(u * 1.5);
    const headY = availTop + Math.max(0, Math.round((availBot - availTop - (headH + headGap + rowH * rows)) / 2));
    const bodyTop = headY + headH + headGap;
    const bodyBot = bodyTop + rowH * rows;

    const tickW = Math.round((R - L) * 0.27);
    const barsW = Math.round((R - L) * 0.25);
    const figL = L + tickW;
    const barsX = figL + Math.round(u * 0.9);
    const moveL = figL + barsW;
    const moveW = Math.round((R - moveL) * 0.56);
    const fwdX = moveL + moveW;

    P.slot("head-move", moveL, headY, moveW - Math.round(u * 1.2), headH, { align: "right", role: "period" });
    P.slot("head-fwd", fwdX, headY, R - fwdX, headH, { align: "right", role: "period" });
    P.inkAdd(H.line(L - 14, bodyTop - Math.round(u * 0.6), R + 14, bodyTop - Math.round(u * 0.6) - 4, { stroke: p.structure, width: 4.6, opacity: 0.9, amp: 4, over: 16, seed: 701 }));
    // the ledger closes at the foot. Without it the last row's figures hang off
    // the bottom of nothing and the strip reads as a fragment of a longer list.
    P.inkAdd(H.line(L - 14, bodyBot + Math.round(u * 0.5), R + 14, bodyBot + Math.round(u * 0.5) - 3, { stroke: p.structure, width: 2.6, opacity: 0.5, amp: 3.4, over: 12, seed: 703 }));
    P.inkAdd(H.line(figL - Math.round(u * 0.8), headY - 8, figL - Math.round(u * 0.8), bodyBot + Math.round(u * 0.2), { stroke: p.structure, width: 2.3, opacity: 0.32, amp: 4.4, over: 6, seed: 707 }));
    // a second, lighter divide between the two figure columns. Both are
    // right-aligned Courier, and without it the multiple reads as part of the
    // move — "-12% 7.8x" as one number.
    P.inkAdd(H.line(fwdX - Math.round(u * 0.7), bodyTop + 4, fwdX - Math.round(u * 0.7), bodyBot - 4, { stroke: p.structure, width: 1.9, opacity: 0.2, amp: 4, over: 5, seed: 709 }));

    // The move as a shape as well as a figure. It is a region, not artwork: the
    // plate cannot know the moves, and a strip drawn with invented bars would be
    // a chart of nothing. The rails are drawn either way, so the rows keep their
    // structure when the operator has no data yet.
    P.slot("bars", barsX, bodyTop, moveL - Math.round(u * 0.6) - barsX, rowH * rows, {
      role: "bars", region: true, renderer: "series.rowBars", rows: rows,
      note: "one horizontal bar per row, on a scale shared across the rows, from a zero rule the renderer places. engine/series.js draws it from the data",
    });

    for (let i = 1; i <= rows; i++) {
      const y = bodyTop + (i - 1) * rowH;
      P.slot(`band-${i}`, L - Math.round(u * 1.8), y + 2, R - L + Math.round(u * 3.6), rowH - 4, { role: "highlight-band", overlay: "overlays/row-band" });
      P.slot(`ticker-${i}`, L, y + rowH * 0.18, tickW - Math.round(u * 1.2), rowH * 0.64, { align: "left", role: i === 1 ? "tickerSubject" : "ticker" });
      P.slot(`move-${i}`, moveL, y + rowH * 0.13, moveW - Math.round(u * 1.2), rowH * 0.74, { align: "right", role: "move" });
      P.slot(`fwd-${i}`, fwdX, y + rowH * 0.18, R - fwdX, rowH * 0.64, { align: "right", role: "fwd" });
      leader(P, barsX, moveL - Math.round(u * 0.6), y + rowH * 0.5, 740 + i * 37, 0.22);
    }
    P.slot("caption", L, h - m.b - capH, R - L, capH, { align: "left", role: "caption" });
    return P;
  }

  // ---------------- multiples strip: relative pricing, in one frame ----------------
  // USE WHEN the claim is what the subject COSTS against its peers.
  //
  // peers/peer-strip is the wrong shape for this and it was the first thing
  // checked. Its rows are COMPANIES — a ticker each, with a move and a forward
  // multiple — so it answers "what did the complex do today". The valuation
  // chapter asks the inverse: one company against a peer set on several metrics
  // at once. So here the rows are METRICS and the columns are subject, peer
  // median, and where the subject sits between them.
  //
  // THE MARKER IS THE WHOLE POINT. A figure beside a median is a table; a figure
  // with a POSITION is an argument, and it is what turns "94th percentile on P/E"
  // from a statistic into a picture.
  //
  // Which is why the rail is drawn and the marker is not. The extent of a peer
  // range is structural — it is what the two ends of the rail MEAN — so the plate
  // draws the rail and its end ticks and the rows keep their shape with no data
  // in them. Everything between the ticks is data: marker-N is a region and
  // series.rangeMark puts the subject on it at a 0–1 position, with the median's
  // own position optional beside it. A plate cannot know a percentile.
  //
  // NO DIRECTION COLOUR ANYWHERE ON IT. Cheap is not up and expensive is not
  // down: a low multiple is a price, not a rise, and drawing the marker in `down`
  // when it sits high would make the plate argue the short before the script
  // does. The subject is structure and the peer median is otherParty, exactly as
  // on the peer strip, so the row is legible with no highlight at all and band-N
  // stays free for the row the voice-over is on.

  function multiplesStrip(o) {
    const w = o.w, h = o.h, land = w > h, p = o.pal;
    const rows = land ? 6 : 3;
    const roles = {
      unit: { font: "Courier Prime", size: 26, weight: 400, colour: "structure", opacity: 0.72, tracking: "0.04em", maxChars: land ? 46 : 38 },
      column: { font: "Archivo Narrow", size: land ? 26 : 28, weight: 600, colour: "structure", opacity: 0.68, tracking: "0.06em", maxChars: 10 },
      // 40 portrait against 36 landscape: still larger, and the four points came
      // off because the box has to hold "EV / EBITDA (fwd)" — the longest metric
      // name a valuation chapter writes — rather than the shortest one.
      metric: { font: "Archivo Narrow", size: land ? 36 : 40, weight: 500, colour: "structure", maxChars: land ? 24 : 16 },
      subject: { font: "Courier Prime", size: land ? 58 : 62, weight: 700, colour: "structure", maxChars: 7 },
      median: { font: "Courier Prime", size: 46, weight: 700, colour: "otherParty", maxChars: 7 },
      caption: { font: "Courier Prime", size: 26, weight: 400, colour: "structure", opacity: 0.72, maxChars: 60 },
    };
    // THREE COLUMNS IN PORTRAIT, and it is a cut rather than a squeeze. The
    // portrait boxes are ~0.56 of the landscape ones while the type is LARGER;
    // four columns of it capacity out at about half the declared string, so the
    // renderer's fit-to-box would shrink a 62pt figure to roughly 35pt and land
    // the portrait figures SMALLER than the landscape ones — the exact opposite
    // of what the variant exists for, and silently.
    //
    // So the peer median stops being a column here. It is not lost: rangeMark
    // already puts the median's own tick on the rail, which is where a phone
    // reads a comparison anyway. A short is where you cut things.
    if (!land) delete roles.median;
    const P = H.Plate({
      key: o.key, w, h, seed: o.seed || 21, pal: p,
      meta: {
        aspect: land ? "16x9" : "9x16", family: "tables", type: "multiples-strip", rows, typeRoles: roles,
        markerNote: "marker-N is a REGION, not artwork. The plate draws the rail and its two end ticks; series.rangeMark({ box: slots['marker-3'], t, median, pal }) draws what sits on it — t is 0 at the low end of the peer range and 1 at the high end, median the same scale. A t outside 0–1 is a real reading (the subject is off the peer range) and the renderer clamps the dot to the end and marks it, rather than dropping it.",
        columnNote: land
          ? "subject-N is the subject's own value, in structure; median-N is the peer set's, in otherParty. Same rule as peers/peer-strip: the row you are in is legible with no highlight at all, which keeps band-N free for the row the voice-over is on."
          : "THREE COLUMNS: metric, subject, rail. There is no median-N and no head-median on this aspect — pass median to series.rangeMark and the tick it puts on the rail IS the peer number. Four columns at portrait width cannot hold the type this plate declares, and the renderer would silently shrink the figures below the landscape ones to fit.",
        budgetNote: "This plate no longer carries its own budget arithmetic and no longer needs to be the exception: engine/budget.js derives maxChars from the slot boxes for EVERY family, off the real hmtx advances rather than an 0.47em average. What is still worth knowing here is that the figure columns are Courier (monospaced, so the count is exact) and the metric column is Archivo Narrow set in a box cut to hold 'EV / EBITDA (fwd)'. See the family's maxCharsNote.",
        directionNote: "nothing on this plate is drawn in up or down. Cheap is not up and expensive is not down — a multiple is a price, not a direction — and a red marker high on the rail would argue the short before the script does. Position carries the claim.",
        rowsNote: land ? "six metric rows: the relative-pricing half of a valuation chapter in one frame." : "three rows, not six. A short's cheap-or-trap beat wants the same picture with less in it, and three rows of larger type is that picture — not the 16:9 sheet scaled down.",
      },
    });
    P.colourAdd(surfaceFurniture(P, SURFACES[p.surfaceKey]));

    const u = unitOf(h);
    const m = { l: land ? 150 : 84, r: land ? 150 : 84, t: land ? 92 : 186, b: land ? 96 : 150 };
    const L = m.l, R = w - m.r;
    const unitH = blockH(roles.unit, 1);
    P.slot("unit", L, m.t, R - L, unitH, { align: "left", role: "unit" });

    const headH = blockH(roles.column, 1);
    const capH = blockH(roles.caption, 1);
    // Row height is a multiple of the figure in it, never the frame divided by
    // the row count — the lesson the peer strip paid for. Measure the type, stack
    // it, then centre the block in what is left.
    const availTop = m.t + unitH + Math.round(u * (land ? 2.2 : 3));
    const availBot = h - m.b - capH - Math.round(u * 1.8);
    const headGap = Math.round(u * 1.5);
    // Landscape measures the type and stacks it — six rows of it fill the frame
    // on their own. Portrait has three rows in twice the height, so the same
    // arithmetic leaves the strip a narrow band floating in a tall frame with the
    // rail squeezed beside it. Every other 9:16 plate in the kit fills its safe
    // band, so this one takes the height it is given and divides it.
    const rowH = land
      ? Math.round(blockH(roles.subject, 1) * 1.62)
      : Math.max(Math.round(blockH(roles.subject, 1) * 2.1), Math.floor((availBot - availTop - headH - headGap) / rows));
    const headY = availTop + Math.max(0, Math.round((availBot - availTop - (headH + headGap + rowH * rows)) / 2));
    const bodyTop = headY + headH + headGap;
    const bodyBot = bodyTop + rowH * rows;

    // Portrait spends the width the median column freed on the rail, not on the
    // two text columns: three columns exist so the rail can be read at arm's
    // length, and a 200-unit rail with a dot on it is a decoration.
    const labelW = Math.round((R - L) * (land ? 0.29 : 0.38));
    const subjW = Math.round((R - L) * (land ? 0.15 : 0.3));
    const medW = land ? Math.round((R - L) * 0.13) : 0;
    const figL = L + labelW;
    const medX = figL + subjW;
    const trackX = medX + medW + Math.round(u * 1.6);

    // This plate used to derive its own budgets here, off an 0.47em average for
    // Archivo Narrow. It no longer needs to: Plate.manifest() runs
    // engine/budget.js over every plate in the library, measuring each slot with
    // the real face. The boxes are still cut here — the budget is what is
    // computed from them, not the geometry.
    const labelBox = labelW - Math.round(u * 1.4), subjBox = subjW - Math.round(u * 1.2), medBox = medW - Math.round(u * 1.2);

    P.slot("head-subject", figL, headY, subjBox, headH, { align: "right", role: "column" });
    if (land) P.slot("head-median", medX, headY, medBox, headH, { align: "right", role: "column" });
    P.inkAdd(H.line(L - 14, bodyTop - Math.round(u * 0.6), R + 14, bodyTop - Math.round(u * 0.6) - 4, { stroke: p.structure, width: 4.6, opacity: 0.9, amp: 4, over: 16, seed: 601 }));
    // the ledger closes at the foot, or the last row's figures hang off the
    // bottom of nothing and the strip reads as a fragment of a longer list
    P.inkAdd(H.line(L - 14, bodyBot + Math.round(u * 0.5), R + 14, bodyBot + Math.round(u * 0.5) - 3, { stroke: p.structure, width: 2.6, opacity: 0.5, amp: 3.4, over: 12, seed: 603 }));
    P.inkAdd(H.line(figL - Math.round(u * 0.8), headY - 8, figL - Math.round(u * 0.8), bodyBot + Math.round(u * 0.2), { stroke: p.structure, width: 2.3, opacity: 0.32, amp: 4.4, over: 6, seed: 607 }));
    // and a lighter divide before the rail column. Both figure columns are
    // right-aligned Courier; without it "99.0x 21.4x" reads as one number, the
    // same defect the peer strip found between its move and forward columns.
    P.inkAdd(H.line(trackX - Math.round(u * 0.8), bodyTop + 4, trackX - Math.round(u * 0.8), bodyBot - 4, { stroke: p.structure, width: 1.9, opacity: 0.2, amp: 4, over: 5, seed: 609 }));

    for (let i = 1; i <= rows; i++) {
      const y = bodyTop + (i - 1) * rowH;
      const cy = y + rowH * 0.5;
      P.slot(`band-${i}`, L - Math.round(u * 1.8), y + 2, R - L + Math.round(u * 3.6), rowH - 4, { role: "highlight-band", overlay: "overlays/row-band" });
      P.slot(`label-${i}`, L, y + rowH * 0.18, labelBox, rowH * 0.64, { align: "left", role: "metric" });
      P.slot(`subject-${i}`, figL, y + rowH * 0.13, subjBox, rowH * 0.74, { align: "right", role: "subject" });
      if (land) P.slot(`median-${i}`, medX, y + rowH * 0.18, medBox, rowH * 0.64, { align: "right", role: "median" });
      // THE RAIL, drawn: a light rule between two end ticks. The ticks are the
      // low and the high of the peer range, which is structure rather than data —
      // the range is what the rail is.
      const tickH = Math.round(u * 0.62);
      P.inkAdd(H.line(trackX, cy, R, cy - 1, { stroke: p.structure, width: 2.2, opacity: 0.3, amp: 2.6, over: 6, seed: 620 + i }));
      [trackX, R].forEach(function (x, n) {
        P.inkAdd(H.line(x, cy - tickH, x, cy + tickH, { stroke: p.structure, width: 2.8, opacity: 0.5, amp: 1.8, over: 3, seed: 640 + i * 3 + n }));
      });
      P.slot(`marker-${i}`, trackX, cy - Math.round(rowH * 0.3), R - trackX, Math.round(rowH * 0.6), {
        role: "marker", region: true, renderer: "series.rangeMark",
        note: "the subject's position between the peer low and the peer high, 0 to 1. engine/series.js draws it from the data; the rail under it is the plate's.",
      });
    }
    P.slot("caption", L, h - m.b - capH, R - L, capH, { align: "left", role: "caption" });
    return P;
  }

  // ---------------- cycles: the same metric at two moments ----------------
  // USE WHEN the claim is about a NUMBER'S HISTORY rather than its level. Two
  // figures, and the path between them.
  //
  // The composition question this plate answers: then → now is not a trajectory,
  // it is two anchors with a trough between them. A cycle frame that drew an
  // arrow from one number to the other would be making the bull case by accident
  // — the whole reason the frame exists is that the line went somewhere else
  // first. So the two moments are type (anchored to the left and right ends of
  // the band, with drop lines tying each figure to its end of the path) and the
  // shape between them is DATA: every intervening period, drawn by
  // series.cycleArc, whose minimum the operator labels in `trough`.
  //
  // Weighting: now is the largest figure in structure (it is the subject, and the
  // number under discussion), then is 0.68 of it in otherParty (the past is the
  // other party), trough smallest in down. Three sizes, three colours, three
  // jobs — no other emphasis is applied anywhere on the plate.
  function cycleFrame(o) {
    const w = o.w, h = o.h, land = w > h, p = o.pal;
    const roles = {
      unit: { font: "Courier Prime", size: 26, weight: 400, colour: "structure", opacity: 0.72, tracking: "0.04em", maxChars: land ? 46 : 38 },
      metric: { font: "Archivo Narrow", size: land ? 68 : 62, weight: 700, colour: "structure", tracking: "-.02em", maxChars: land ? 30 : 24 },
      moment: { font: "Courier Prime", size: land ? 30 : 28, weight: 400, colour: "structure", opacity: 0.7, tracking: "0.1em", maxChars: 14 },
      period: { font: "Courier Prime", size: land ? 26 : 24, weight: 400, colour: "structure", opacity: 0.66, maxChars: 6 },
      then: { font: "Courier Prime", size: land ? 112 : 100, weight: 700, colour: "otherParty", maxChars: 6 },
      now: { font: "Courier Prime", size: land ? 168 : 148, weight: 700, colour: "structure", maxChars: 6 },
      trough: { font: "Courier Prime", size: land ? 46 : 42, weight: 700, colour: "down", maxChars: 6 },
      caption: { font: "Courier Prime", size: 26, weight: 400, colour: "structure", opacity: 0.72, maxChars: 60 },
    };
    const P = H.Plate({
      key: o.key, w, h, seed: o.seed || 88, pal: p,
      meta: {
        aspect: land ? "16x9" : "9x16", family: "cycles", type: "cycle-frame", typeRoles: roles,
        pathNote: "the band is not decoration and not an arrow: it is the intervening periods. Draw it with series.cycleArc({ box: slots.path, values }) and label its returned minimum in `trough`.",
      },
    });
    P.colourAdd(surfaceFurniture(P, SURFACES[p.surfaceKey]));

    const u = unitOf(h);
    const m = { l: land ? 190 : 90, r: land ? 190 : 90, t: land ? 88 : 186, b: land ? 84 : 150 };
    const L = m.l, R = w - m.r;
    const unitH = blockH(roles.unit, 1);
    P.slot("unit", L, m.t, R - L, unitH, { align: "left", role: "unit" });

    const metH = blockH(roles.metric, 1);
    const momH = blockH(roles.moment, 1);
    const valH = blockH(roles.now, 1);
    const capH = blockH(roles.caption, 1);
    const troughH = blockH(roles.trough, 1);
    const availTop = m.t + unitH + Math.round(u * 2);
    const availBot = h - m.b - capH - Math.round(u * 1.6);
    const gapMet = Math.round(u * (land ? 2.4 : 2.6));
    const gapVal = Math.round(u * 0.6);
    const gapBand = Math.round(u * (land ? 2.2 : 2.8));
    const gapTr = Math.round(u * 1.2);
    P.slot("caption", L, h - m.b - capH, R - L, capH, { align: "left", role: "caption" });

    // Two branches, because the band wants the frame's long axis. Portrait: the
    // two figures side by side with the path full-width beneath them, tied to it
    // by a drop line each, so the eye reads then → down → now. Landscape: the
    // figures stack down the left and the path stands beside them — reading order
    // is already left-to-right, so ties would be furniture for its own sake.
    const headH = blockH(roles.period, 1);
    const headRow = headH + Math.round(u * 1.1);
    const ruleGap = Math.round(u * 0.5), ruleH2 = 8;
    // Each figure gets a rule in its own colour under it — the pairing made
    // explicit, so the two colours are declared on the plate and not only in the
    // type. It is also what stops a big Courier figure floating over the band.
    const valRule = function (x, y, wd, col, wt, seed) {
      P.inkAdd(H.line(x, y, x + wd, y - 4, { stroke: col, width: wt, opacity: 0.92, amp: 3.2, over: 12, seed: seed }));
    };
    let band;
    if (land) {
      const colW = Math.round((R - L) * 0.42);
      const bandX = L + colW + Math.round(u * 3);
      const inner = metH + gapMet + momH + gapVal + valH + ruleGap + ruleH2 + Math.round(u * 2.2) + momH + gapVal + valH + ruleGap + ruleH2;
      const top = availTop + Math.max(0, Math.round((availBot - availTop - (inner + headRow)) / 2));
      P.slot("metric", L, top, colW, metH, { align: "left", role: "metric" });
      P.inkAdd(H.line(L - 10, top + metH + Math.round(u * 0.5), L + colW * 0.72, top + metH + Math.round(u * 0.5) - 5, { stroke: p.structure, width: 8, opacity: 0.92, amp: 4, over: 16, seed: 811 }));
      const thenY = top + metH + gapMet;
      P.slot("then-date", L, thenY, colW, momH, { align: "left", role: "moment" });
      P.slot("then-value", L, thenY + momH + gapVal, colW, valH, { align: "left", role: "then" });
      valRule(L, thenY + momH + gapVal + valH + ruleGap, Math.round(colW * 0.44), p.otherParty, 5, 821);
      const nowY = thenY + momH + gapVal + valH + ruleGap + ruleH2 + Math.round(u * 2.2);
      P.slot("now-date", L, nowY, colW, momH, { align: "left", role: "moment" });
      P.slot("now-value", L, nowY + momH + gapVal, colW, valH, { align: "left", role: "now" });
      valRule(L, nowY + momH + gapVal + valH + ruleGap, Math.round(colW * 0.62), p.structure, 7, 823);
      band = { x: bandX, y: top, w: R - bandX, h: inner - headRow };
    } else {
      const half = Math.round((R - L) * 0.44);
      const bandH = Math.round((R - L) * 0.58);
      const block = metH + gapMet + momH + gapVal + valH + ruleGap + ruleH2 + gapBand + bandH + headRow;
      const top = availTop + Math.max(0, Math.round((availBot - availTop - block) / 2));
      P.slot("metric", L, top, R - L, metH, { align: "left", role: "metric" });
      P.inkAdd(H.line(L - 10, top + metH + Math.round(u * 0.5), L + (R - L) * 0.42, top + metH + Math.round(u * 0.5) - 5, { stroke: p.structure, width: 7, opacity: 0.92, amp: 4, over: 16, seed: 811 }));
      const rowY = top + metH + gapMet;
      P.slot("then-date", L, rowY, half, momH, { align: "left", role: "moment" });
      P.slot("then-value", L, rowY + momH + gapVal, half, valH, { align: "left", role: "then" });
      valRule(L, rowY + momH + gapVal + valH + ruleGap, Math.round(half * 0.44), p.otherParty, 5, 821);
      P.slot("now-date", R - half, rowY, half, momH, { align: "right", role: "moment" });
      P.slot("now-value", R - half, rowY + momH + gapVal, half, valH, { align: "right", role: "now" });
      valRule(R - Math.round(half * 0.62), rowY + momH + gapVal + valH + ruleGap, Math.round(half * 0.62), p.structure, 7, 823);
      band = { x: L, y: rowY + momH + gapVal + valH + ruleGap + ruleH2 + gapBand, w: R - L, h: bandH };
      [L + 2, R - 2].forEach(function (x, i) {
        P.inkAdd(H.line(x, band.y - gapBand + Math.round(u * 0.4), x, band.y - Math.round(u * 0.3), { stroke: p.structure, width: 2.2, opacity: 0.42, amp: 2.6, over: 7, step: 5, seed: 951 + i * 4 }));
      });
    }

    // The band is a plot area, drawn in the charts family's own vocabulary: a
    // faint tint, gridlines at 0.2, the L-axis at 0.9, ticks under the baseline
    // and the six periods named. The first version was a hatched slab with a thin
    // box round it — a slab with a line on it. A path needs a plane to be read
    // against, and the periods are half the claim: "three years ago" is only
    // legible if the axis says which three years.
    field(P, band.x, band.y, band.w, band.h, 941, 0.16);
    for (let i = 1; i <= 3; i++) {
      const gy = band.y + band.h - (band.h / 3) * i;
      P.inkAdd(H.line(band.x, gy, band.x + band.w, gy, { stroke: p.structure, width: 1.8, opacity: 0.26, amp: 2.6, over: 7, seed: 960 + i * 7 }));
    }
    P.inkAdd(H.line(band.x, band.y - 14, band.x, band.y + band.h, { stroke: p.structure, width: land ? 4.6 : 4, opacity: 0.9, amp: 3, over: 11, seed: 971 }));
    P.inkAdd(H.line(band.x, band.y + band.h, band.x + band.w + 16, band.y + band.h, { stroke: p.structure, width: land ? 4.6 : 4, opacity: 0.9, amp: 3, over: 11, seed: 972 }));
    const pStep = band.w / 5;
    for (let c = 0; c < 6; c++) {
      const cx = band.x + pStep * c;
      // step is the wobble's sampling interval and it defaults to 26 units, which
      // is LONGER than a tick: sampled once, the path collapses and every tick on
      // the plate silently disappears. Same defect the sparkline bars had.
      P.inkAdd(H.line(cx, band.y + band.h, cx, band.y + band.h + 13, { stroke: p.structure, width: 2.2, opacity: 0.75, amp: 1.2, step: 4, seed: 980 + c * 11 }));
      /* LEGACY PASS, rebuild-21: head-1 and head-6 were centred on the band's end
       * ticks, so half of each hung off the band — into now-value in 16:9, past
       * the safe margin in 9:16. The end labels align inward from their tick. */
      const endIn = Math.round(u * 0.4);
      const end = c === 0 || c === 5, hw = end ? Math.round(pStep / 2) + endIn : pStep;
      const hx = c === 0 ? band.x - endIn : c === 5 ? band.x + band.w - Math.round(pStep / 2) : Math.max(0, cx - pStep / 2);
      P.slot(`head-${c + 1}`, hx, band.y + band.h + Math.round(u * 0.7), hw, headH, { align: c === 0 ? "left" : c === 5 ? "right" : "center", role: "period" });
    }
    // The path IS the band: first and last points sit on the axis ends, so they
    // line up with head-1, head-6 and the two figures above. An inset would put
    // the series a few units inside its own axis and nothing would register.
    P.slot("path", band.x, band.y, band.w, band.h, {
      role: "path", region: true, renderer: "series.cycleArc",
      note: "every period between the two moments. The plate draws nothing here — engine/series.js draws it from the data and returns the trough's coordinates",
    });
    P.slot("trough", band.x + Math.round(band.w * 0.36), band.y + Math.round(band.h * 0.52), Math.round(band.w * 0.28), troughH, {
      align: "center", role: "trough", region: true,
      note: "the low point's own figure, called out inside the plot. Region because only the data knows where the minimum sits — box it just above the ring, at the x that series.cycleArc returns",
    });
    return P;
  }

  // ---------------- frames: real footage and captured documents live inside these ----------------
  function mediaFrame(o) {
    const land = o.w > o.h, w = o.w, h = o.h, p = o.pal, t = o.treatment;
    const P = base(o, "media-frame-t" + t, { caption: TR.caption, label: TR.label });
    P.meta.treatment = t;
    const iw = land ? w * 0.68 : w * 0.82;
    /* LEGACY PASS, rebuild-21: under the monitor's stand (t2) the source line fell
     * past the bottom 5% in 16:9. The t2 screen is 4% of the height shorter. */
    const ih = land ? h * (t === 2 ? 0.56 : 0.6) : h * 0.44;
    const ix = (w - iw) / 2, iy = land ? h * 0.12 : h * 0.26;

    if (t === 1) {
      // taped photo corners
      P.inkAdd(H.outline(H.polyRect(ix - 16, iy - 16, iw + 32, ih + 32), { stroke: p.structure, width: 3.6, opacity: 0.85, amp: 3.2, over: 12, seed: 301 }));
      [[ix - 40, iy - 46], [ix + iw - 100, iy - 40], [ix - 34, iy + ih - 24], [ix + iw - 106, iy + ih - 18]].forEach((c, i) => {
        const poly = [{ x: c[0], y: c[1] }, { x: c[0] + 140, y: c[1] - 14 }, { x: c[0] + 146, y: c[1] + 52 }, { x: c[0] + 8, y: c[1] + 62 }];
        P.colourAdd(H.hatch(poly, { color: p.attention, opacity: 0.26, gap: 7, width: 11, angle: -6, over: 12, seed: 310 + i }));
        P.inkAdd(H.outline(poly, { stroke: p.structure, width: 1.8, opacity: 0.36, amp: 2.2, over: 6, seed: 320 + i }));
        P.artBox(`tape-${i + 1}`, c[0] - 10, c[1] - 26, 170, 100);
      });
    } else if (t === 2) {
      // monitor bezel, with a stand
      P.colourAdd(H.hatch(H.polyRect(ix - 44, iy - 44, iw + 88, ih + 88), { color: p.ground2, opacity: 0.55, gap: 8, width: 13, angle: -3, over: 18, seed: 331 }));
      P.inkAdd(H.outline(H.polyRect(ix - 44, iy - 44, iw + 88, ih + 88), { stroke: p.structure, width: 5, opacity: 0.92, amp: 3.6, over: 14, seed: 332 }));
      P.inkAdd(H.outline(H.polyRect(ix, iy, iw, ih), { stroke: p.structure, width: 3, opacity: 0.7, amp: 2.6, over: 9, seed: 333 }));
      const sx = w / 2, sy = iy + ih + 44;
      P.inkAdd(H.stroke([{ x: sx - 40, y: sy }, { x: sx - 30, y: sy + 70 }, { x: sx + 30, y: sy + 70 }, { x: sx + 40, y: sy }], { stroke: p.structure, width: 4, amp: 2.6, over: 7, seed: 334 }));
      P.inkAdd(H.line(sx - 120, sy + 74, sx + 120, sy + 70, { stroke: p.structure, width: 5, opacity: 0.9, amp: 2.6, over: 10, seed: 335 }));
      P.artBox("stand", sx - 130, sy - 6, 260, 92);
    } else {
      // pinned print: one pin, a slight curl at the lower corner
      P.inkAdd(H.outline(H.polyRect(ix - 12, iy - 12, iw + 24, ih + 24), { stroke: p.structure, width: 3.4, opacity: 0.8, amp: 3.4, over: 12, seed: 341 }));
      P.inkAdd(H.stroke([{ x: ix + iw - 40, y: iy + ih + 12 }, { x: ix + iw + 6, y: iy + ih - 30 }], { stroke: p.structure, width: 3, amp: 2.4, over: 6, seed: 342 }));
      const px = w / 2, py = iy - 30;
      P.colourAdd(H.hatch([{ x: px - 22, y: py - 22 }, { x: px + 22, y: py - 20 }, { x: px + 20, y: py + 22 }, { x: px - 20, y: py + 20 }], { color: p.down, opacity: 0.6, gap: 6, width: 9, angle: -70, over: 8, seed: 343 }));
      P.inkAdd(H.outline([{ x: px - 22, y: py - 22 }, { x: px + 22, y: py - 20 }, { x: px + 20, y: py + 22 }, { x: px - 20, y: py + 20 }], { stroke: p.structure, width: 2.4, opacity: 0.8, amp: 2, over: 5, seed: 344 }));
      P.artBox("pin", px - 34, py - 34, 68, 68);
    }
    P.slot("media", ix, iy, iw, ih, { role: "media", region: true, fit: "cover", note: "stock footage or a photograph plays inside here" });
    const capY = iy + ih + (t === 2 ? 150 : 70);
    P.slot("caption", (w - iw) / 2, capY, iw, land ? 70 : 90, { align: "left", role: "label" });
    P.slot("source", (w - iw) / 2, capY + (land ? 84 : 104), iw, 56, { align: "left", role: "caption" });
    return P;
  }

  // Capture frame: a filing page or article headline, drawn as paper on the desk
  function captureFrame(o) {
    const land = o.w > o.h, w = o.w, h = o.h, p = o.pal;
    const P = base(o, "capture-frame", {
      source: TR.caption,
      headline: { font: "Archivo Narrow", size: land ? 52 : 46, weight: 700, colour: "structure", maxLines: 2, maxCharsPerLine: land ? 40 : 26 },
      body: { font: "Archivo Narrow", size: land ? 30 : 28, weight: 400, colour: "structure", maxLines: 3, maxCharsPerLine: land ? 62 : 38 },
      caption: TR.caption,
    });
    const pw = land ? w * 0.62 : w * 0.86, ph = land ? h * 0.76 : h * 0.62;
    const px = (w - pw) / 2, py = land ? h * 0.12 : h * 0.2;
    P.colourAdd(H.hatch(H.polyRect(px, py, pw, ph), { color: p.ground, opacity: 0.95, gap: 7, width: 14, angle: -2, over: 16, seed: 351 }));
    P.inkAdd(H.outline(H.polyRect(px, py, pw, ph), { stroke: p.structure, width: 3.4, opacity: 0.8, amp: 3.6, over: 13, seed: 352 }));
    // staple, top left
    P.inkAdd(H.stroke([{ x: px + 30, y: py + 46 }, { x: px + 70, y: py + 30 }], { stroke: p.structure, width: 4.4, amp: 1.8, over: 4, seed: 353 }));
    P.artBox("staple", px + 18, py + 18, 68, 44);
    const L = px + (land ? 70 : 46), R = px + pw - (land ? 70 : 46);
    P.slot("source", L, py + (land ? 76 : 64), R - L, 52, { align: "left", role: "source" });
    P.slot("headline", L, py + (land ? 150 : 132), R - L, land ? 140 : 180, { align: "left", role: "headline" });
    P.inkAdd(H.line(L - 8, py + (land ? 310 : 330), R + 8, py + (land ? 306 : 326), { stroke: p.structure, width: 3.4, opacity: 0.7, amp: 2.6, over: 9, seed: 354 }));
    const bodyY = py + (land ? 340 : 366);
    P.slot("body", L, bodyY, R - L, land ? 190 : 260, { align: "left", role: "body" });
    // the marked passage: a highlight region the renderer can lay over the body
    P.slot("mark", L - 14, bodyY - 8, R - L + 28, land ? 70 : 84, { role: "highlight-band", region: true, overlay: "overlays/row-band" });
    P.slot("caption", px, py + ph + (land ? 40 : 60), pw, 56, { align: "left", role: "caption" });
    return P;
  }

  // Hook card: the first three seconds of every short. 9:16 only.
  function hookCard(o) {
    const w = o.w, h = o.h, p = o.pal, t = o.treatment;
    const P = base(o, "hook-card-t" + t, {
      ticker: { font: "Courier Prime", size: 40, weight: 700, colour: "structure", tracking: ".08em", maxChars: 6 },
      move: { font: "Courier Prime", size: 52, weight: 700, colour: "structure", maxChars: 8 },
      hook: { font: "Archivo Narrow", size: t === 3 ? 76 : 92, weight: 700, colour: "structure", tracking: "-.025em", maxLines: 4, maxCharsPerLine: t === 3 ? 22 : 18 },
      huge: { font: "Courier Prime", size: 260, weight: 700, colour: "structure", maxChars: 5 },
      sub: { font: "Archivo Narrow", size: 36, weight: 400, colour: "structure", opacity: 0.85, maxLines: 2, maxCharsPerLine: 34 },
    });
    P.meta.treatment = t;
    const L = 90, R = w - 90;
    if (t === 1) {
      // ticker chip top-left, statement filling the frame
      const chip = H.polyRect(L, 260, 300, 96);
      P.colourAdd(H.hatch(chip, { color: p.ground2, opacity: 0.6, gap: 8, width: 12, angle: -4, over: 14, seed: 361 }));
      P.inkAdd(H.outline(chip, { stroke: p.structure, width: 3.6, opacity: 0.9, amp: 3, over: 10, seed: 362 }));
      P.slot("ticker", L + 24, 282, 252, 52, { align: "left", role: "ticker" });
      P.slot("move", L + 340, 282, R - L - 340, 56, { align: "left", role: "move" });
      P.slot("hook", L, 460, R - L, 900, { align: "left", role: "hook" });
      P.inkAdd(H.line(L - 10, 1420, R * 0.7, 1414, { stroke: p.structure, width: 8, opacity: 0.92, amp: 4, over: 16, seed: 363 }));
      P.slot("sub", L, 1460, R - L, 160, { align: "left", role: "sub" });
    } else if (t === 2) {
      // the question, boxed, off-centre
      const bx = L - 30, by = 420, bw = R - L + 60, bh = 900;
      P.colourAdd(H.hatch(H.polyRect(bx, by, bw, bh), { color: p.ground2, opacity: 0.42, gap: 9, width: 13, angle: -3, over: 20, seed: 371 }));
      P.inkAdd(H.outline(H.polyRect(bx, by, bw, bh), { stroke: p.structure, width: 4.6, opacity: 0.9, amp: 3.8, over: 14, seed: 372 }));
      P.slot("ticker", L, 300, 300, 56, { align: "left", role: "ticker" });
      P.slot("move", L + 340, 300, R - L - 340, 56, { align: "left", role: "move" });
      P.slot("hook", L, by + 70, R - L, bh - 200, { align: "left", role: "hook" });
      P.slot("sub", L, by + bh + 60, R - L, 160, { align: "left", role: "sub" });
    } else {
      // number-led: the move itself is the hook
      P.slot("ticker", L, 300, 300, 56, { align: "left", role: "ticker" });
      P.slot("huge", L, 420, R - L, 300, { align: "left", role: "huge" });
      // Same defect as headline-band-t1, same fix, same restraint. t3 drew ONE
      // rule: 0.16% of its pixels changed between frames against a 1-6% pack
      // band, so the plate was frozen with one element twitching. t1 draws a
      // hatched ticker chip and t2 a hatched box, and copying either would make
      // t3 stop being the number-led treatment. So it gets a rule a hand drew
      // over twice, and a short ticker tick — ink that belongs to a plate whose
      // whole argument is one figure.
      const rY = 760;
      P.inkAdd(H.line(L - 10, rY, R - 200, rY - 6, { stroke: p.structure, width: 9, opacity: 0.95, amp: 4.2, over: 18, seed: 381 }));
      P.inkAdd(H.line(L - 2, rY + 5, R - 260, rY + 1, { stroke: p.structure, width: 4.6, opacity: 0.4, amp: 5.2, over: 13, seed: 382 }));
      P.inkAdd(H.line(L - 10, 372, L + 210, 372, { stroke: p.structure, width: 5.4, opacity: 0.78, amp: 3.4, over: 11, seed: 383 }));
      P.slot("hook", L, 810, R - L, 620, { align: "left", role: "hook" });
      P.inkAdd(H.line(L - 6, 1452, L + (R - L) * 0.62, 1452, { stroke: p.structure, width: 5.8, opacity: 0.68, amp: 3.6, over: 12, seed: 384 }));
      P.slot("sub", L, 1480, R - L, 160, { align: "left", role: "sub" });
    }
    return P;
  }

  // ---------------- host ----------------
  // Big flat shapes, minimal detail, read from silhouette at phone size.
  // Variants are proportion + treatment sets, not different characters.
  function ellipse(cx, cy, rx, ry, n, jit, seed) {
    const r = H.rng(seed || 7), pts = [];
    for (let i = 0; i < (n || 22); i++) {
      const a = (i / (n || 22)) * Math.PI * 2;
      const k = 1 + (r() - 0.5) * (jit == null ? 0.06 : jit);
      pts.push({ x: cx + Math.cos(a) * rx * k, y: cy + Math.sin(a) * ry * k });
    }
    return pts;
  }

  // WARDROBE, hoisted to module scope so the close-up and the medium wear the same
  // clothes as the full figure rather than a second copy of the same hexes. Moving
  // the table changes no drawing: hostFigure reads the identical values in the
  // identical order, so all thirty shipped host plates stay byte-identical.
  // HEAD TILT, one constant for the whole family so every plate is the same man.
  // ~2.6 degrees. Small on purpose: enough that he is not square to the lens,
  // nowhere near enough to read as a man about to fall over. Symmetry is what was
  // making him look composed, and composed is the one thing he is not.
  const HEAD_TILT = 0.075;

  const HOST_OUTFITS = {
    // THE DEFAULT: a washed-out tee with a collar that has lost its shape. This
    // replaces the open shirt, which read as smart-casual office — a man dressed
    // to be seen. He is not; he has been at this desk since three.
    "tee": { top: "#8C918C", leg: "#2E353F", layer: null, sleeves: "short", collar: "stretched" },
    // the same tee under a robe, for the pieces shot at the worst hour
    "robe": { top: "#8C918C", leg: "#2E353F", layer: "robe", sleeves: "long", collar: "stretched" },
    // the shipped open collar over a tee, kept so anything already cut against it
    // still resolves — no longer the default
    "shirt": { top: "#7C8794", leg: "#2E353F", layer: null, sleeves: "long" },
    // a cardigan over the shirt — the late-night, been-here-since-six look
    "cardigan": { top: "#8A8378", leg: "#31363E", layer: "cardigan", sleeves: "long" },
    // sleeves rolled: the same shirt, working
    "rolled": { top: "#6F8290", leg: "#2C333C", layer: null, sleeves: "rolled" },
    // a crew jumper, no collar. The darkest top in the set
    "jumper": { top: "#5E6A72", leg: "#2A3038", layer: null, sleeves: "long" },
    // gilet over a shirt, for the pieces shot in the cold office
    "gilet": { top: "#7C8794", leg: "#2E353F", layer: "gilet", sleeves: "long" },
  };
  const HOST_OUTFIT_DEFAULT = "tee";

  /* THE FACE — authored once, drawn by both the full figure and the close-up.

     Revision 05 duplicated this vocabulary between hostFigure and hostHead, on the
     grounds that extracting it meant proving the emitted string sequence had not
     changed across thirty shipped files. Revision 06 changes the face on every one
     of those files by instruction, so the re-render is happening regardless and
     the reason for the duplication is gone. Extracting it now is the cheap moment;
     leaving it duplicated would mean authoring the same tired face twice and
     watching the two drift apart on the next note.

     WHAT THIS FACE IS. Deadpan. Not sad, not sour, not pleading — the resting face
     of a man who has been awake since three and is about to say something very dry
     about a filing. He is telling the joke, never wearing it. The line between
     tired and pathetic is held by three things, and every value below is set
     against them: the brow stays LEVEL (a raised inner brow is what reads as
     wounded), the mouth stays FLAT rather than turned down, and the eyes stay open
     enough to be looking AT you. Droop any of the three further and he becomes the
     target instead of the teller. */
  function hostFace(o) {
    const P = o.P, S = o.S, ell = o.ell, dot = o.dot;
    /* §3.6 — THE DETAIL BUDGET GOES ON THE FACE, and only under the revised hand.

       H2 is true exactly when engine/hand.js has bound the hand-2 profile for
       this plate (host/ and room/). Everything gated on it is additive detail in
       the one place the operator's reference puts it: the eyes are the single
       resolved element in an otherwise battered frame, and here they were the
       muddiest thing on screen — two scribbled dark blobs behind a doubled rim.

       Nothing here is gated OFF for hand-1, so the twelve untouched families and
       any plate still drawn by the shipped hand emit the identical string
       sequence they always did. */
    const H2 = !!(H.profile && H.profile() === "hand-2");
    const hcx = o.cx, hcy = o.cy, R = o.R;
    const ink = o.ink, skin = o.skin, hair = o.hair;
    const lw = o.lw || 1, seg = o.seg || 0, fine = !!o.fine;
    const mouthOpen = o.mouthOpen, closedEyes = !!o.closedEyes;
    // GLANCE. -1 looks camera-left, +1 camera-right, 0 straight down the lens.
    // He faced camera in every frame regardless of what was on screen, so he could
    // never look at the chart he was discussing.
    //
    // The whole read is the PUPIL, and it is not just an x offset. A real glance
    // moves both pupils the same way while the two eyes show DIFFERENT amounts of
    // white — the eye he turns toward crowds its outer corner, the far one opens
    // up — and the head yaws a few degrees with it. Offset alone, applied
    // symmetrically, reads as a squint.
    const glance = o.glance || 0;

    // TILT. Pivoted at the throat, not the head's centre, so the head leans on the
    // neck instead of sliding sideways off it. Small: 3-4 degrees is the whole
    // difference between composed and not, and 10 is a man falling over.
    const tilt = o.tilt || 0;
    const rotAbout = function (px, py, a) {
      const c = Math.cos(a), s = Math.sin(a);
      return function (pt) {
        const dx = pt.x - px, dy = pt.y - py;
        return { x: px + dx * c - dy * s, y: py + dx * s + dy * c };
      };
    };
    const T = rotAbout(hcx, hcy + R * 1.05, tilt);
    const M = function (arr) { return arr.map(T); };
    const pt = function (x, y) { return T({ x: x, y: y }); };

    const head = M(ell(hcx, hcy, R * 0.86, R * 0.98, seg || 26, 0.04, 701));
    P.colourAdd(S.hatch(head, { color: skin, opacity: 0.62, gap: 6, width: 10, angle: -82, over: 11, seed: 702 }));
    const headDark = clipHalf(head, -1, 0, -(hcx + R * 0.2));
    if (headDark) P.colourAdd(S.hatch(headDark, { color: ink, opacity: 0.2, gap: 8, width: 12, angle: -80, over: 8, seed: 704 }));
    // under the jaw and the brow: the two shadows that make a face read as a head
    P.colourAdd(S.hatch(M(ell(hcx, hcy + R * 0.80, R * 0.58, R * 0.21, 14, 0.08, 706)), { color: ink, opacity: 0.2, gap: 6, width: 9, angle: -8, over: 6, seed: 707 }));

    // HOLLOW UNDER THE CHEEKBONE. Lower and stronger than the faint cheek pass it
    // replaces, and deliberately uneven — the lit side keeps some, the turned side
    // gets most. A symmetric pair of these reads as blusher.
    P.colourAdd(S.hatch(M(ell(hcx - R * 0.44, hcy + R * 0.33, R * 0.21, R * 0.13, 12, 0.1, 761)), { color: ink, opacity: 0.105, gap: 8, width: 11, angle: -54, over: 5, seed: 762 }));
    P.colourAdd(S.hatch(M(ell(hcx + R * 0.47, hcy + R * 0.30, R * 0.17, R * 0.11, 12, 0.1, 763)), { color: ink, opacity: 0.07, gap: 9, width: 11, angle: -112, over: 5, seed: 764 }));

    // STUBBLE. Two passes at different angles over the jaw, heavier on the turned
    // side. Even stubble is a beard; uneven stubble is three days of not deciding.
    // Kept LIGHT: at 0.17 it read as a full dark beard, which is a different man.
    // The polygon starts below the cheekbone so it does not climb into the hollow
    // and gang up with it into one dark mask.
    const jaw = M([
      { x: hcx - R * 0.68, y: hcy + R * 0.44 }, { x: hcx - R * 0.50, y: hcy + R * 0.80 },
      { x: hcx, y: hcy + R * 0.97 }, { x: hcx + R * 0.52, y: hcy + R * 0.78 },
      { x: hcx + R * 0.66, y: hcy + R * 0.42 }, { x: hcx + R * 0.38, y: hcy + R * 0.58 },
      { x: hcx - R * 0.36, y: hcy + R * 0.60 },
    ]);
    P.colourAdd(S.hatch(jaw, { color: ink, opacity: 0.105, gap: 5.2, width: 8, angle: -74, over: 5, seed: 766 }));
    P.colourAdd(S.hatch(clipHalf(jaw, -1, 0, -(hcx + R * 0.1)) || jaw, { color: ink, opacity: 0.07, gap: 6.4, width: 9, angle: -30, over: 4, seed: 768 }));

    // ONE CONTOUR ON THE SKULL. Two outlines over the same polygon is where the
    // doubled rim came from — it is not a heavier line, it is two lines, and at
    // close-up size they read as an abandoned underdrawing. hand-2 draws it once,
    // flagged as silhouette: the outer edge of a head against empty ground is the
    // least important line in the picture, and the weight it gives up here is
    // spent on the eyes below.
    if (H2) {
      P.inkAdd(S.outline(head, { stroke: ink, width: 6.4 * lw, opacity: 0.97, amp: 2.4, over: 10, seed: 708, silhouette: true }));
    } else {
      P.inkAdd(S.outline(head, { stroke: ink, width: 6.4 * lw, opacity: 0.97, amp: 2.4, over: 10, seed: 708 }));
      P.inkAdd(S.outline(head, { stroke: ink, width: 4.2 * lw, opacity: 0.92, amp: 2.6, over: 12, seed: 703 }));
    }
    [-1, 1].forEach(function (s, i) {
      P.inkAdd(S.stroke(M([
        { x: hcx + s * R * 0.82, y: hcy - R * 0.1 },
        { x: hcx + s * R * 0.98, y: hcy + R * 0.08 },
        { x: hcx + s * R * 0.79, y: hcy + R * 0.26 },
      ]), { stroke: ink, width: 3.2 * lw, opacity: 0.8, amp: 1.6, over: 5, seed: 706 + i }));
    });

    // HAIR: a soft cap with a receding front, FLATTENED on his right (camera-left)
    // where he has been leaning on his hand, and standing up on the other side.
    // No radiating spikes — those read as a horror mask.
    const cap = [], N = seg ? 20 : 16;
    for (let i = 0; i <= N; i++) {
      const a = Math.PI * 1.06 + (Math.PI * 0.88 * i) / N;
      const cxu = Math.cos(a), cyu = Math.sin(a);
      const flat = cxu < 0 ? 0.83 : 0.97;                 // slept-on side sits closer to the skull
      const lift = cxu > 0.45 ? 1.06 : 1.0;               // and pushed up on the other
      cap.push({ x: hcx + cxu * R * 0.9 * flat, y: hcy + cyu * R * 1.02 * lift });
    }
    const capBack = [
      { x: hcx + R * 0.42, y: hcy - R * 0.52 }, { x: hcx - R * 0.02, y: hcy - R * 0.54 }, { x: hcx - R * 0.40, y: hcy - R * 0.44 },
    ];
    const capAll = M(cap.concat(capBack)), capM = M(cap);
    P.colourAdd(S.hatch(capAll, { color: hair, opacity: 0.52, gap: 5.5, width: 9, angle: -66, over: 10, seed: 711 }));
    P.inkAdd(S.stroke(capM, { stroke: ink, width: 3.8 * lw, opacity: 0.88, amp: 2.2, over: 9, seed: 712 }));
    P.inkAdd(S.stroke([capM[capM.length - 1]].concat(M(capBack)).concat([capM[0]]), { stroke: ink, width: 2.6, opacity: 0.46, amp: 2.2, over: 6, seed: 713 }));
    for (let i = 0; i < (seg ? 4 : 3); i++) {
      const bx = hcx - R * 0.36 + i * R * 0.34;
      P.inkAdd(S.stroke(M([{ x: bx, y: hcy - R * 0.86 }, { x: bx + R * 0.18, y: hcy - R * 0.64 }]), { stroke: ink, width: 2.4, opacity: 0.36, amp: 1.8, over: 5, seed: 715 + i }));
    }
    // the piece that will not lie down, on the un-slept side
    P.inkAdd(S.stroke(M([
      { x: hcx + R * 0.50, y: hcy - R * 0.74 }, { x: hcx + R * 0.66, y: hcy - R * 0.96 }, { x: hcx + R * 0.80, y: hcy - R * 0.88 },
    ]), { stroke: ink, width: 2.8, opacity: 0.5, amp: 2.2, over: 6, seed: 719 }));

    // ---- eyes ---------------------------------------------------------------
    // The glasses sit CROOKED: the whole pair is rotated a degree and a half about
    // the bridge, on top of whatever the head is doing. Nobody straightens their
    // glasses at four in the morning.
    const eyeY = hcy + R * 0.04;
    const G = rotAbout(hcx, eyeY, tilt + 0.026);
    const GM = function (arr) { return arr.map(G); };

    [-1, 1].forEach(function (s, i) {
      const lx = hcx + s * R * 0.35;
      const lens = GM(ell(lx, eyeY, R * 0.29, R * 0.235, seg ? 20 : 18, 0.03, 721 + i));
      P.colourAdd(S.hatch(lens, { color: "#FFFFFF", opacity: 0.26, gap: 6, width: 9, angle: -60, over: 6, seed: 723 + i }));
      // CLEAN WHITES. The eye itself, inside the lens: a real wash at a real
      // value rather than the lens glint standing in for one. Without it the
      // pupil sits on skin and the whole eye reads as a smudge, which is what
      // made the eyes the muddiest thing on the plate.
      if (H2) {
        const sclera = GM(ell(lx, eyeY + R * 0.035, R * 0.205, R * 0.125, 16, 0.02, 901 + i));
        P.colourAdd(S.hatch(sclera, { color: "#F3EEE4", opacity: 0.94, gap: 6, width: 9, seed: 903 + i, material: true }));
      }

      // HALF-LIDDED. The lid comes down over the top third of the eye and the pupil
      // sits low and partly under it. This is the single strongest fatigue cue on
      // the plate — wide open eyes read as alert no matter what the rest is doing.
      if (!closedEyes) {
        const lidY = eyeY - R * 0.055 + (s < 0 ? 0 : R * 0.012);
        const lidPoly = GM([
          { x: lx - R * 0.27, y: eyeY - R * 0.24 }, { x: lx + R * 0.27, y: eyeY - R * 0.24 },
          { x: lx + R * 0.25, y: lidY }, { x: lx, y: lidY + R * 0.035 }, { x: lx - R * 0.25, y: lidY - R * 0.01 },
        ]);
        P.colourAdd(S.hatch(lidPoly, { color: skin, opacity: 0.72, gap: 5, width: 9, angle: -70, over: 6, seed: 773 + i }));
        P.colourAdd(S.hatch(lidPoly, { color: ink, opacity: 0.085, gap: 7, width: 9, angle: -64, over: 5, seed: 775 + i }));
        P.topAdd(S.stroke(GM([
          { x: lx - R * 0.25, y: lidY - R * 0.01 }, { x: lx, y: lidY + R * 0.035 }, { x: lx + R * 0.25, y: lidY },
        ]), { stroke: ink, width: 3.4 * lw, opacity: 0.88, amp: 1, over: 4, seed: 777 + i }));
      }

      // §5 — THE RIM IS HARDWARE, NOT A SILHOUETTE. Under hand-2 the light-facing
      // spans thinned it to near-invisible grey; glasses are the one manufactured
      // object on his face and they hold one confident line at full weight.
      P.topAdd(S.outline(lens, H2
        ? { stroke: ink, width: 4.4 * lw, opacity: 1, amp: 1.2, seed: 725 + i, heavy: 1.15 }
        : { stroke: ink, width: 3.4 * lw, opacity: 0.9, amp: 1.6, over: 6, seed: 725 + i }));
      // ONE CONFIDENT LINE FOR THE GLASSES, TEMPLE ARM ATTACHED. The shipped arm
      // started 0.01R inside the rim and drifted further out with the overshoot,
      // so it floated off the frame. hand-2 starts it ON the rim, carries real
      // weight at the hinge (heavy) and lands on the skull edge.
      if (H2) {
        // TWO POINTS, not three. A catmull-rom through three points that turn a
        // corner at the hinge overshoots into a loop, which is the floating
        // diamond by the camera-left ear. Rim to skull, one segment.
        P.topAdd(S.stroke(GM([
          { x: lx + s * R * 0.29, y: eyeY - R * 0.045 },
          { x: hcx + s * R * 0.84, y: hcy - R * 0.02 },
        ]), { stroke: ink, width: 3.4 * lw, opacity: 0.95, amp: 0.9, seed: 727 + i, heavy: 1.22 }));
      } else {
        P.topAdd(S.stroke(GM([{ x: lx + s * R * 0.28, y: eyeY - R * 0.05 }, { x: hcx + s * R * 0.83, y: hcy - R * 0.04 }]), { stroke: ink, width: 2.6, opacity: 0.66, amp: 1.2, over: 4, seed: 727 + i }));
      }
      // a smudge on one lens, because he has taken them off and put them back on
      if (s < 0) {
        P.topAdd(S.stroke(GM([{ x: lx - R * 0.16, y: eyeY + R * 0.12 }, { x: lx + R * 0.05, y: eyeY - R * 0.10 }]), { stroke: "#FFFFFF", width: 5, opacity: 0.3, amp: 1.4, over: 4, seed: 779 }));
      }

      // BROW, LEVEL. The old brow lifted at the inner end, which is the shape that
      // reads as pleading — the exact thing this revision is told not to be. Flat
      // and slightly heavy instead: unimpressed, not wounded.
      P.topAdd(S.stroke(M([
        { x: hcx + s * R * 0.13, y: hcy - R * 0.33 - (s > 0 ? R * 0.02 : 0) },
        { x: hcx + s * R * 0.38, y: hcy - R * 0.345 },
        { x: hcx + s * R * 0.58, y: hcy - R * 0.30 },
      ]), { stroke: ink, width: 3.8 * lw, opacity: 0.82, amp: 1.4, over: 4, seed: 729 + i }));

      // UNDER-EYE: the bag, then the fold under it. Two marks, not one — a single
      // line under an eye is a wrinkle; a shaded pouch with a crease under it is
      // not having slept. The shading is deliberately FAINT: at 0.19 the pair read
      // as two black eyes, and a man who looks beaten is the target of the joke
      // rather than the one telling it. The crease does most of the work.
      P.colourAdd(S.hatch(M(ell(lx, eyeY + R * 0.205, R * 0.24, R * 0.075, 12, 0.09, 781 + i)), { color: ink, opacity: 0.095, gap: 6.5, width: 9, angle: -12, over: 4, seed: 783 + i }));
      P.topAdd(S.stroke(M([
        { x: lx - R * 0.21, y: eyeY + R * 0.145 }, { x: lx, y: eyeY + R * 0.20 }, { x: lx + R * 0.19, y: eyeY + R * 0.15 },
      ]), { stroke: ink, width: 2.4, opacity: 0.42, amp: 1, over: 3, seed: 785 + i }));
      if (fine) {
        P.topAdd(S.stroke(M([
          { x: lx - R * 0.16, y: eyeY + R * 0.30 }, { x: lx + R * 0.14, y: eyeY + R * 0.295 },
        ]), { stroke: ink, width: 1.9, opacity: 0.3, amp: 0.9, over: 3, seed: 787 + i }));
      }

      if (closedEyes) {
        P.topAdd(S.stroke(GM([
          { x: lx - R * 0.15, y: eyeY + R * 0.01 }, { x: lx, y: eyeY + R * 0.07 }, { x: lx + R * 0.15, y: eyeY + R * 0.01 },
        ]), { stroke: ink, width: 3 * lw, opacity: 0.85, amp: 1.1, over: 3, seed: 731 + i }));
      } else {
        // The pupil rides toward the glance, and further on the eye he is turning
        // TOWARD (s === glance) than on the trailing one — that difference in how
        // much white each eye shows is what sells a look as a look.
        const lead = s === glance;
        const gx = glance * R * (lead ? 0.155 : 0.115);
        dot(G({ x: lx + s * R * 0.03 + gx, y: eyeY + R * 0.075 }), R * 0.075, 733 + i * 5);
        // A DEFINITE PUPIL, and the catchlight that makes it one. The iris ring
        // sits under the pupil dot the line above already drew, and the highlight
        // goes upper-left because that is where the light is (§3.1) — the same
        // vector every other shaded thing on the plate refers to. This is the
        // whole of the reference's technique on the eye: one bright, resolved
        // element and everything else modelled.
        if (H2) {
          const px = lx + s * R * 0.03 + gx, py = eyeY + R * 0.075;
          P.topAdd(S.hatch(GM(ell(px, py, R * 0.105, R * 0.1, 14, 0.03, 905 + i)), { color: ink, opacity: 0.42, gap: 5, width: 7, seed: 906 + i, material: false }));
          P.topAdd(S.hatch(GM(ell(px - R * 0.035, py - R * 0.032, R * 0.026, R * 0.024, 10, 0.05, 907 + i)), { color: "#FFFFFF", opacity: 0.96, gap: 3, width: 4, seed: 908 + i, material: true }));
        }
      }
    });

    // A HEAD YAW GOES WITH IT. Eyes alone slide in a fixed skull; a few degrees of
    // turn is what makes him look AT the thing rather than past it. The nose and
    // philtrum carry the yaw — they are the landmarks a turn is read from — the
    // far cheek gains an edge, and the mouth shifts a fraction of the same amount.
    const YAW = glance * R * 0.075;
    P.topAdd(S.stroke(GM([{ x: hcx - R * 0.07 + YAW, y: eyeY - R * 0.04 }, { x: hcx + R * 0.07 + YAW, y: eyeY - R * 0.04 }]), { stroke: ink, width: 3, opacity: 0.82, amp: 0.9, over: 3, seed: 741 }));
    P.topAdd(S.stroke(M([
      { x: hcx + R * 0.03 + YAW, y: hcy + R * 0.17 }, { x: hcx + R * 0.1 + YAW * 1.3, y: hcy + R * 0.36 }, { x: hcx - R * 0.03 + YAW * 1.3, y: hcy + R * 0.38 },
    ]), { stroke: ink, width: 3 * lw, opacity: 0.68, amp: 1.2, over: 4, seed: 743 }));
    if (glance) {
      P.colourAdd(S.hatch(M(ell(hcx - glance * R * 0.62, hcy + R * 0.16, R * 0.16, R * 0.34, 14, 0.08, 791)), { color: ink, opacity: 0.075, gap: 8, width: 11, angle: -84, over: 5, seed: 792 }));
    }

    // ---- mouth --------------------------------------------------------------
    // FLAT, AND NOT LEVEL. The shipped mouth lifted at both corners: small, closed,
    // pleasant — a smile, in every pose, under writing about extradition. This one
    // is a straight set with the camera-right corner a hair lower than the left.
    // The asymmetry is doing the work: a perfectly level mouth reads as composed,
    // and one dropped corner reads as a man who has heard it all before. It is
    // deliberately NOT turned down at both ends, which would be sulking.
    // §1.2 — A TALK FRAME IS A VISEME, AND THE MOUTH OPENS BY DEGREES.
    //
    // mouthOpen was a boolean, so a talk strip could only alternate shut and
    // wide — and to get a third frame out of it the shipped strip varied the
    // BOIL between talk frames as well, which breaks §7's one hard rule: talk
    // frames differ only at the mouth. A number gives three visemes at one boil
    // index, so the rule is satisfied in the artwork rather than in a comment.
    // `true` is 1, so every existing call is unchanged.
    const MO = mouthOpen === true ? 1 : (typeof mouthOpen === "number" ? Math.max(0, Math.min(1, mouthOpen)) : 0);
    if (MO > 0.04) {
      // the aperture, not the mouth: a viseme at 0.45 is the same lips less open
      const ax = R * 0.15 * (0.52 + 0.48 * MO), ay = R * 0.11 * (0.26 + 0.74 * MO);
      const m = M(ell(hcx, hcy + R * 0.62, ax, ay, seg ? 16 : 14, 0.05, 751));
      P.colourAdd(S.hatch(m, { color: ink, opacity: 0.36, gap: 5, width: 8, angle: -70, over: 6, seed: 752 }));
      P.topAdd(S.outline(m, { stroke: ink, width: 3 * lw, opacity: 0.86, amp: 1.2, over: 5, seed: 753 }));
    } else {
      P.topAdd(S.stroke(M([
        { x: hcx - R * 0.235 + YAW * 0.5, y: hcy + R * 0.612 },
        { x: hcx + R * 0.01 + YAW * 0.5, y: hcy + R * 0.623 },
        { x: hcx + R * 0.225 + YAW * 0.5, y: hcy + R * 0.652 },
      ]), { stroke: ink, width: 4 * lw, opacity: 0.92, amp: 1.1, over: 5, seed: 754 }));
      // the crease at the dropped corner only
      P.topAdd(S.stroke(M([
        { x: hcx + R * 0.25 + YAW * 0.5, y: hcy + R * 0.60 }, { x: hcx + R * 0.30 + YAW * 0.5, y: hcy + R * 0.70 },
      ]), { stroke: ink, width: 2.2, opacity: 0.42, amp: 1, over: 3, seed: 757 }));
      // A MOUTH WITH FORM. The set line stays exactly where it is — it is the
      // expression and it was argued for. What it lacked was a lip: a shadow
      // under the lower one and a short plane above the upper, both shading
      // passes rather than lines, so the mouth has thickness without gaining a
      // second contour. Still flat, still not turned down at both ends.
      if (H2) {
        // Deeper and wider than the first cut: at 0.13 and 0.09 over a small
        // region these came out as a 0.10 wash and did not survive to render
        // scale. Still shading passes, still no second contour on the mouth.
        P.colourAdd(S.hatch(M(ell(hcx + YAW * 0.5, hcy + R * 0.70, R * 0.225, R * 0.075, 14, 0.08, 910)), { color: ink, opacity: 0.3, gap: 6, width: 8, seed: 911, material: false }));
        P.colourAdd(S.hatch(M(ell(hcx + YAW * 0.5, hcy + R * 0.558, R * 0.19, R * 0.055, 14, 0.08, 912)), { color: ink, opacity: 0.2, gap: 6, width: 8, seed: 913, material: false }));
      }
    }
    P.topAdd(S.stroke(M([{ x: hcx - R * 0.2, y: hcy + R * 0.76 }, { x: hcx + R * 0.2, y: hcy + R * 0.755 }]), { stroke: ink, width: 2.2, opacity: 0.3, amp: 1, over: 4, seed: 756 }));
    return { eyeY: eyeY, tilt: tilt, glance: glance };
  }

  function hostFigure(o) {
    const w = o.w, h = o.h, p = o.pal, pose = o.pose, mouthOpen = o.mouthOpen, bob = o.bob || 0;
    const P = H.Plate({
      key: o.key, w: w, h: h, seed: o.seed,
      pal: { ground: "none", ground2: p.ground2, grain: null, structure: p.structure, surfaceKey: p.surfaceKey },
      meta: { family: "host", pose: pose, aspect: "9x16", cutout: true, alpha: true, boil: o.boil | 0 },
    });
    // Character colours. Not data roles — a role never does two jobs, so the man
    // is not allowed to borrow one. Shirt and trousers are DIFFERENT colours:
    // when both were ground2 the whole figure read as one tan slab with a head
    // on it, which is the single biggest reason he looked like a sandwich board.
    const ink = p.structure;
    // He was cream on cream: shirt #D9CFBB against a #E6DDC9 ground is a four
    // percent step, so the largest shape in the frame had no edge. He is the
    // reason anyone is watching and he has to be the highest-contrast thing in
    // frame, so the clothing carries real value now — a mid-slate shirt and near
    // -black trousers — and the outlines run heavier than anything in the set.
    // WARDROBE. He hosts every episode, and one outfit across a whole series
    // reads as a uniform — so the outfit is an episode-level choice, not a
    // redraw: same body, same poses, same seeds, different clothes.
    //
    // Every outfit has to keep the two things the tonal system depends on: the
    // torso is mid-to-dark so he separates from a pale wall, and the trousers are
    // the darkest cloth on the plate. An outfit that breaks either one puts him
    // back at the desk's value, which is the defect revisions 02 and 03 were
    // spent fixing. So these vary in HUE and in detail, and only slightly in
    // value.
    const OUTFITS = HOST_OUTFITS;
    const OUT = OUTFITS[o.outfit] || OUTFITS[HOST_OUTFIT_DEFAULT];
    P.meta.outfit = o.outfit || HOST_OUTFIT_DEFAULT;
    const shirt = OUT.top, trouser = OUT.leg, shoeC = "#1E242B", skin = SKIN, hair = "#3B3129";
    // §3.6, the paying half: under hand-2 the clothing gives up its quiet
    // secondary lines so the face can afford resolved eyes. Same flag as
    // hostFace() and hostHead(), and nothing is gated off for hand-1.
    const H2 = !!(H.profile && H.profile() === "hand-2");
    const floorY = Math.round(h * 0.9);
    P.meta.floorLineY = floorY;
    const BOFF = (o.boil | 0) * 9173;
    const S = boilShift(inkScale(h / 1920), o.boil | 0);
    const ell = function (cx2, cy2, rx, ry, n, jit, seed) { return ellipse(cx2, cy2, rx, ry, n, jit, seed + BOFF); };

    // ---- proportion -------------------------------------------------------
    // Landmarked ONCE, in head units, and used everywhere after. The old figure
    // placed shoulders, hips and knees from independent fractions of the canvas,
    // so the torso grew into a slab and the legs hung off the bottom of it with
    // nothing joining them. 6.8 heads: stylised enough to read as a drawing,
    // tall enough not to read as a child.
    const figH = h * 0.665;
    const topY = floorY - figH;
    const HU = figH / 6.8;
    // §4.1 — THE SEAT DROP, and it is why a seated pose is a rig term rather than
    // a new drawing. Every landmark on this figure comes out of at(n), so lowering
    // the hip by moving `at` itself carries the head, the shoulders, the spine
    // curve, the arms and the face with it, unchanged. Nothing above the hip knows
    // it is sitting down.
    //
    // 1.8 head units: standing, the hip sits 3.7HU above the floor; on a chair it
    // sits at knee height, which this rig puts at 1.95HU. So the drop is the
    // difference, and the seated figure occupies 5.0HU against the standing 6.8 —
    // a height ratio of 0.735, published in meta because the renderer cannot
    // scale a seated cut-out the way it scales a standing one. See seatedNote.
    const SEATED = !!POSE_SEATED[pose];
    const SEAT_DROP = SEATED ? HU * 1.8 : 0;
    const at = function (n) { return topY + HU * n + SEAT_DROP; };
    const headCy = at(0.46) + bob;
    const shoulderY = at(1.30) + bob * 0.5, chestY = at(1.85), waistY = at(2.6);
    const hipY = at(3.1), kneeY = at(4.85), ankleY = at(6.55);
    // Seated, the foot is on the floor rather than at the bottom of a standing
    // leg: at(6.55) with the seat drop applied sits 1.55HU BELOW the floor line,
    // which would have put his shoes through it.
    const ankY = SEATED ? floorY - HU * 0.1 : ankleY;
    const shoulderHalf = HU * 0.86, chestHalf = HU * 0.8, waistHalf = HU * 0.66, hipHalf = HU * 0.78;

    // ---- pose -------------------------------------------------------------
    // Every pose used to be the same body with different elbow angles. A pose is
    // a LEAN and a STRIDE as well as an arm: those are what make a stance read.
    //
    // REVISION 07 — THE RIG, not the pose values.
    //
    // Revision 06 was told to make him asymmetric and slumped and it failed,
    // because there was nothing in the armature for either word to act on. The
    // skeleton was vertical and mirrored: `leanAt` tilted a STRAIGHT line about the
    // hip (linear in y, so no curve anywhere), both hips sat at one shared `hipY`
    // with x mirrored, stride was equal and opposite, and `arms[i] || arms[0]` gave
    // four of six poses two reflected arms. Revision 06's shoulder drop went onto
    // the torso OUTLINE only — the silhouette dipped while the shoulder joints the
    // arms hang from stayed level, and the legs never saw it at all. Moving the
    // outline is not moving the skeleton. Same failure as the line-weight pass:
    // the multiplier was fine, the input barely varied.
    //
    // So slump and weight are now RIG TERMS, and the drawing reads them:
    //
    //   slump   the spine's forward bow. Quadratic, peaking mid-torso, so the head
    //           ends up forward of the hips over a hollowed chest — a C-curve. A
    //           linear tilt can only ever be a plank leaning.
    //   weight  which leg carries him, +1 camera-right. The loaded hip RIDES UP and
    //           the free hip drops (that is the real anatomy, and it is the readable
    //           half of contrapposto); the loaded leg goes vertical under its hip
    //           while the free one bends and swings its ankle in.
    //   shoulderTilt  derived, always OPPOSITE the hip tilt, and applied to the
    //           shoulder JOINTS so the arms inherit it instead of just the outline.
    //   arms    asymmetric by default — one hanging, one occupied. The `|| arms[0]`
    //           fallback is gone: every pose states both arms, because a man with
    //           two identical arms is a mannequin.
    const POSE = {
      // his weight is ON THE DESK: forearm flat, that shoulder dropped hard, hip
      // pushed out the other way. contact.forearmY publishes where the forearm
      // lands so the compositor can sit it on the room plate's own contact point.
      "leaning-on-desk": { lean: 0.26, stride: 0.06, weight: -1, slump: 0.34,
        arms: [[0.34, 1.16, 1.02, 1.52], [0.50, 1.30, 0.30, 2.36]], forearm: "left" },
      "hands-in-pockets": { lean: 0.06, stride: 0.05, weight: 1, slump: 0.30,
        arms: [[0.56, 1.20, 0.34, 2.30], [0.50, 1.16, 0.42, 2.24]] },
      "holding-a-page": { lean: 0.12, stride: 0.04, weight: -1, slump: 0.26,
        arms: [[0.62, 1.14, 0.26, 2.00], [0.54, 1.20, 0.34, 1.92]] },
      "pointing-down-at-desk": { lean: 0.40, stride: 0.06, weight: -1, slump: 0.30,
        arms: [[0.52, 1.22, 0.34, 2.38], [0.70, 1.04, 1.16, 2.10]] },
      // the hands have to REACH the face — a head in hands that floats beside the
      // head is just a man surrendering. Offsets are solved against the head
      // landmark, not guessed: shoulder sits 0.84HU below head centre.
      // The deepest slump in the set. Elbows DOWN and out with the forearms running
      // steeply up to the TEMPLES — heels of the hands pressed to the side of the
      // head, fingers into the hair. Elbows above the shoulders splay into
      // surrender, which is a different gesture and the wrong one.
      //
      // Both hand targets are SOLVED against the head landmark, not guessed: the
      // head sits 0.98HU above the shoulder joint before sink, the sink is
      // 0.17·slump, and the head's own half-width is 0.40HU — so a hand at ±0.52HU
      // from the head centre lands just outside the silhouette and reads as
      // pressed against it. The two arms differ because the spine has carried the
      // head off the shoulder centreline, so a mirrored pair would miss on one side.
      "head-in-hands": { lean: 0.40, stride: 0.03, weight: 1, slump: 0.66,
        arms: [[0.30, 0.55, -0.49, -0.91], [0.34, 0.60, 0.19, -1.17]] },
      "walking-out-of-frame": { lean: 0.20, stride: 0.40, weight: 1, slump: 0.22,
        arms: [[0.46, 1.20, 0.24, 2.32], [0.56, 1.10, 0.90, 2.04]] },
      // §4.1 — SITTING DOWN. The highest-value pose in the brief by some distance:
      // every LONG is him standing for forty minutes, and a seated pose is the
      // cheapest way to make a long chapter feel like a different scene.
      //
      // It is a RIG term, not an arm arrangement — see SEAT_DROP below. The hip
      // descends to seat height and the whole upper body comes with it, the thighs
      // run forward instead of down, and the shins drop vertically to the floor.
      // Everything above the hip is the figure that already exists, which is the
      // point: it has to be recognisably the same man sitting down, not a second
      // character.
      //
      // He sits FORWARD, elbow on the desk, the deepest lean in the set bar
      // head-in-hands. A man sitting upright in a chair reads as an interview; a
      // man leaning into his own desk at three in the morning reads as this
      // channel.
      "sitting-at-desk": { lean: 0.34, stride: 0, weight: 1, slump: 0.40, seated: true,
        arms: [[0.36, 1.14, 0.98, 1.44], [0.52, 1.26, 0.26, 2.06]], forearm: "left" },
    }[pose] || { lean: 0.06, stride: 0.04, weight: 1, slump: 0.28,
      arms: [[0.54, 1.06, 0.30, 1.98], [0.48, 1.10, 0.36, 1.92]] };

    const cx = w * (pose === "walking-out-of-frame" ? 0.56 : 0.5);
    const WGT = POSE.weight || 1, SLUMP = POSE.slump || 0;
    // THE SPINE, AS A CURVE. Both terms are powers of u, so displacement piles up
    // toward the crown and the mid-torso lags behind: the head finishes forward of
    // the hips over a chest that is still back. That lag IS the C. A linear ramp
    // — what shipped through revision 06 — can only ever be a plank leaning, no
    // matter what you multiply it by.
    //
    // The bow is NOT multiplied by weight. The slump direction is the lean
    // direction; tying it to which leg carries him made the curve reverse between
    // poses, which is a man bending away from his own lean.
    const spineAt = function (y) {
      const u = Math.max(0, Math.min(1, (hipY - y) / (hipY - topY)));
      return POSE.lean * HU * Math.pow(u, 1.7) + SLUMP * HU * 0.72 * Math.pow(u, 2.3);
    };
    const leanAt = spineAt;
    // A SLUMP ALSO SHORTENS. Displacement alone reads as a man leaning; what says
    // slumped is the head sinking toward the shoulders as the upper back rounds
    // over. Applied at the neck and the head together so the neck compresses
    // rather than the head detaching and floating down.
    const HEAD_SINK = SLUMP * HU * 0.17;
    // HIPS AND SHOULDERS TILT OPPOSITE WAYS. The loaded hip rises; the shoulder
    // over it drops. Level shoulders on level hips was the last symmetry left, and
    // these have to be big enough to SEE — the first pass set them at half this
    // and the drawing read square anyway.
    const HIP_TILT = HU * 0.15, SH_TILT = HU * 0.13;
    const hipYof = function (s) { return hipY - s * WGT * HIP_TILT; };
    const shYof = function (s) { return shoulderY + s * WGT * SH_TILT; };
    const clampX = function (x) { return Math.max(HU * 0.4, Math.min(w - HU * 0.4, x)); };

    const quad = function (a2, b2, wa, wb) {
      const dx = b2.x - a2.x, dy = b2.y - a2.y, L = Math.hypot(dx, dy) || 1;
      const nx = -dy / L, ny = dx / L;
      return [
        { x: a2.x + nx * wa, y: a2.y + ny * wa }, { x: b2.x + nx * wb, y: b2.y + ny * wb },
        { x: b2.x - nx * wb, y: b2.y - ny * wb }, { x: a2.x - nx * wa, y: a2.y - ny * wa },
      ];
    };
    // Per-part hatch ANGLE. One uniform -74 everywhere is why the old figure read
    // flat: shirt, trousers and arms all shared a single texture, so nothing
    // separated the planes. Cloth on the trunk runs with the drape; limbs run
    // along their own length.
    // DENNIS IS THE HIGHEST-CONTRAST OBJECT IN ANY FRAME HE IS IN. He is the
    // reason anyone is watching, and the composite test is the only one that
    // matters: drop him on a room plate and your eye has to go to him first.
    //
    // So he is NOT lit like the room. Revision 01 tinted him per part from two
    // off-frame sources, which put him at the same value as the desk behind him
    // and made him disappear into it. What separates him instead is that his own
    // material hatch runs heavier than anything in the set, and each part carries
    // a neutral weight pass on its inboard side — the room's furniture tops out
    // at a 0.19 ink hatch, and he sits well above that.
    // §3 — NO BLOOM ON A MASS. Every polygon that comes through here is a
    // CONSTRUCTION polygon: a torso quad whose bottom is under the trousers, a
    // limb quad whose ends are inside the shoulder and the hand it joins. Their
    // boundaries are not the material's boundary, so rimming them draws exactly
    // what the review found — a quadrilateral across the shirt, a parallelogram
    // where the forearm crosses the sleeve, a hard rectangle at the elbow,
    // horizontal breaks at the knees. Same rule the neck quad already uses; the
    // silhouette is carried by outline() below, which is the line that is real.
    // §5c — THE OUTLINE CLAUSE. delta-12 suppressed the bloom on construction
    // polygons and left their CONTOUR, which is the line the rule deliberately
    // preserves — and on a buried edge that line is not real either. The review
    // found it on the neck: two verticals from inside the jaw to mid-shirt, on
    // the most-used plate in the kit. Same defect as the quadrilateral across the
    // shirt, one layer up.
    //
    // So the clause: on a construction polygon, the silhouette stays and the
    // INTERIOR edges go — outline and rim both. Which edges are interior is a
    // property of the construction, so it is derived from the construction rather
    // than listed per call:
    //
    //   "quad"   a limb from quad(a, b, wa, wb): points are [a+n, b+n, b-n, a-n],
    //            so edges 1 and 3 are the ENDS — inside the shoulder and inside
    //            the hand the limb joins. The two long sides are the silhouette.
    //   "trunk"  a torso: the shoulder-to-shoulder top edge is under the collar
    //            and the hip-to-hip bottom edge is under the trousers. Both
    //            derived as the edges whose endpoints both sit at the extreme of
    //            the polygon's y-range, so it holds for either torso poly without
    //            being told their point order.
    //
    // Edges that remain are drawn as OPEN strokes, which is also why they read
    // better: stroke2 tapers the ends of an open span, so a silhouette now fades
    // where the form goes under a garment instead of stopping on a corner.
    const interiorEdges = function (poly, mode) {
      const n = poly.length;
      if (mode === "quad") return { 1: 1, 3: 1 };
      const ys = poly.map(function (p) { return p.y; });
      const y0 = Math.min.apply(null, ys), y1 = Math.max.apply(null, ys);
      const band = (y1 - y0) * 0.08, out = {};
      for (let i = 0; i < n; i++) {
        const a = poly[i], b = poly[(i + 1) % n];
        if ((a.y <= y0 + band && b.y <= y0 + band) || (a.y >= y1 - band && b.y >= y1 - band)) out[i] = 1;
      }
      return out;
    };
    const contour = function (poly, mode, o) {
      if (!H2 || !mode) return P.inkAdd(S.outline(poly, o));
      // "none" — every edge is interior. The neck is the case: BOTH its long
      // sides are buried at the top (inside the skull) and at the bottom (under
      // the collar), so there is no whole edge left to draw and the visible span
      // has to be cut from the drawing's own boundaries instead. The caller draws
      // it; see the neck below.
      if (mode === "none") return P;
      const skip = interiorEdges(poly, mode);
      const n = poly.length;
      let run = [];
      for (let i = 0; i < n; i++) {
        if (skip[i]) {
          if (run.length > 1) P.inkAdd(S.stroke(run, Object.assign({}, o, { silhouette: true })));
          run = [];
        } else {
          if (!run.length) run.push(poly[i]);
          run.push(poly[(i + 1) % n]);
        }
      }
      if (run.length > 1) P.inkAdd(S.stroke(run, Object.assign({}, o, { silhouette: true })));
      return P;
    };
    const mass = function (poly, colour, op, lw, ang, seed, mode) {
      const c = centroid(poly);
      const noRim = H2 ? { rim: false } : null;
      P.colourAdd(S.hatch(poly, Object.assign({ color: colour, opacity: op, gap: 6.8, width: 11.5, angle: ang, over: 11, seed: seed }, noRim)));
      // the turned form, in ink: this is what carries his contrast
      const inboard = c.x < cx ? clipHalf(poly, -1, 0, -c.x) : clipHalf(poly, 1, 0, c.x);
      if (inboard) P.colourAdd(S.hatch(inboard, { color: ink, opacity: 0.2, gap: 8, width: 12, angle: ang - 6, over: 8, seed: seed + 3 }));
      contour(poly, mode, { stroke: ink, width: lw * 1.35, opacity: 0.97, amp: 2.8, over: 10, seed: seed + 1 });
    };
    const dot = function (x, y, r, seed) {
      P.topAdd(S.hatch(ell(x, y, r, r, 12, 0.05, seed), { color: ink, opacity: 0.95, gap: 2.4, width: 4.4, angle: -60, over: 3, seed: seed + 1 }));
    };

    // ---- the chair, drawn BEFORE the legs so he sits in front of it --------
    if (SEATED) {
      hostChair({ P: P, S: S, HU: HU, cx: cx, seatY: hipY + HU * 0.5, floorY: floorY, ink: ink, fwd: -1 });
    }

    // ---- legs (behind the shirt hem) --------------------------------------
    // The loaded leg is straight and vertical under its own raised hip; the free
    // leg bends and swings its ankle inward. Mirrored legs with equal-and-opposite
    // stride is what made every pose read as a figure on a stand.
    [-1, 1].forEach(function (s, i) {
      const loaded = s === WGT;
      const sw = POSE.stride * HU * (i === 0 ? -1 : 1);
      const hy = hipYof(s);
      const hipP = { x: cx + s * hipHalf * 0.5 + spineAt(hy), y: hy };
      // The loaded leg is a straight column under its own raised hip. The free leg
      // breaks at the knee, carries it inward across the body and lands its ankle
      // further in still — that inward break is the whole reason a standing figure
      // reads as resting rather than as a figure on a stand.
      const kneeP = loaded
        ? { x: hipP.x - s * HU * 0.03, y: kneeY }
        : { x: hipP.x - s * hipHalf * 0.16 + sw * 0.7, y: kneeY - HU * 0.06 };
      const ankP = loaded
        ? { x: hipP.x - s * HU * 0.06, y: ankleY }
        : { x: hipP.x - s * hipHalf * 0.26 + sw, y: ankleY };
      // §4.1 — SEATED: the thigh runs FORWARD at seat height instead of down, and
      // the shin drops vertically to the floor. The near leg carries its knee a
      // little further out and a little lower, so the pair reads as two legs at
      // different depths rather than as one leg drawn twice — the same reason the
      // standing rig refuses mirrored legs.
      const seatedKnee = { x: hipP.x - HU * (1.02 + (i === 0 ? 0.2 : 0)), y: hipY + HU * (0.1 + (i === 0 ? 0.06 : 0)) };
      const seatedAnk = { x: seatedKnee.x - HU * 0.06, y: ankY };
      const kP = SEATED ? seatedKnee : kneeP, aP = SEATED ? seatedAnk : ankP;
      mass(quad(hipP, kP, HU * 0.31, HU * 0.24), trouser, 0.88, 4.2, SEATED ? -10 + i * 6 : -70 + i * 8, 601 + i * 9, "quad");
      mass(quad(kP, aP, HU * 0.24, HU * 0.17), trouser, 0.88, 4.0, -70 + i * 8, 615 + i * 9, "quad");
      const dir = pose === "walking-out-of-frame" ? 1 : (i === 0 ? -1 : 1);
      const L = HU * 0.6, hgt = HU * 0.19;
      const sh = [
        { x: aP.x - L * 0.3 * dir, y: ankY + hgt * 0.1 },
        { x: aP.x + L * 0.72 * dir, y: ankY + hgt * 0.42 },
        { x: aP.x + L * 0.7 * dir, y: floorY }, { x: aP.x - L * 0.34 * dir, y: floorY },
      ];
      P.colourAdd(S.hatch(sh, { color: shoeC, opacity: 0.66, gap: 5.6, width: 9, angle: -8, over: 8, seed: 626 + i }));
      P.inkAdd(S.outline(sh, { stroke: ink, width: 3.6, opacity: 0.92, amp: 2, over: 8, seed: 629 + i }));
      // the shoe's welt line stays: it is a real edge on a real object, and a
      // shoe without one reads as a slipper.
      P.inkAdd(S.line(sh[3].x, floorY - hgt * 0.3, sh[2].x, floorY - hgt * 0.32, { stroke: ink, width: 2.4, opacity: 0.5, amp: 1.3, over: 5, step: 6, seed: 633 + i }));
    });

    // ---- neck, drawn BEFORE the shirt so the collar sits on top of it ------
    const nTop = { x: cx + leanAt(headCy + HU * 0.4), y: headCy + HU * 0.36 + HEAD_SINK };
    const nBot = { x: cx + leanAt(shoulderY), y: shoulderY + HU * 0.12 };
    // §5c, the span — and this is the pair the review measured. "quad" kept the
    // two LONG sides, which is right for a limb and wrong for a neck: a limb's
    // long sides are its silhouette, whereas a neck's are buried at BOTH ends —
    // the top inside the skull (nTop sits HU*0.11 above the head's lower
    // boundary, by construction) and the bottom under the collar (nBot is
    // HU*0.12 below the shoulder line). So the quad's own extent is not its
    // visible extent, which is exactly the symptom: seven times too long, and
    // still ending in mid-garment.
    //
    // The visible span is cut from the drawing's own boundaries instead of from
    // the quad: it starts where the HEAD ELLIPSE's lower edge crosses the neck's
    // own half-width, and ends just inside the shirt. Nothing is hand-tuned —
    // both bounds are the geometry already in scope, so a change to head size,
    // sink or shoulder height carries the neck with it.
    const nq = quad(nTop, nBot, HU * 0.19, HU * 0.24);
    mass(nq, skin, 0.44, 3.0, -84, 641, "none");
    if (H2) {
      // the head's radius, HU * 0.47, taken from HU rather than from R because R
      // is declared further down this author — same number, no forward reference
      const halfW = HU * 0.19, headRad = HU * 0.47;
      const jawY = headCy + HEAD_SINK + Math.sqrt(Math.max(1, headRad * headRad - halfW * halfW));
      const tuckY = shoulderY + HU * 0.03;
      const span = (nBot.y - nTop.y) || 1;
      const sideAt = function (a, b, y) {
        const t = Math.max(0, Math.min(1, (y - nTop.y) / span));
        return { x: a.x + (b.x - a.x) * t, y: y };
      };
      [[nq[0], nq[1]], [nq[3], nq[2]]].forEach(function (e, i) {
        if (tuckY - jawY < HU * 0.04) return;
        P.inkAdd(S.stroke([sideAt(e[0], e[1], jawY), sideAt(e[0], e[1], tuckY)], {
          stroke: ink, width: 3.0 * 1.35, opacity: 0.95, amp: 2, seed: 646 + i, heavy: 1.18,
        }));
      });
    } else {
      P.inkAdd(S.outline(nq, { stroke: ink, width: 3.0 * 1.35, opacity: 0.97, amp: 2.8, over: 10, seed: 642 }));
    }

    // ---- torso: shoulders, waist, hip. A body has a middle ----------------
    // The outline now follows the RIG rather than carrying its own cosmetic dip:
    // every point takes its x from spineAt() at that height and its y from the
    // tilted shoulder and hip lines. Revision 06 hand-dipped this polygon while
    // the joints stayed level, which is exactly why it did not read.
    const lS = spineAt(shoulderY), lC = spineAt(chestY), lW = spineAt(waistY);
    const torso = [
      { x: cx - shoulderHalf * 0.84 + lS, y: shYof(-1) - HU * 0.045 },
      { x: cx + shoulderHalf * 0.84 + lS, y: shYof(1) - HU * 0.045 },
      { x: cx + chestHalf + lC, y: chestY + WGT * HU * 0.03 },
      { x: cx + waistHalf + lW, y: waistY },
      { x: cx + hipHalf + spineAt(hipYof(1)), y: hipYof(1) + HU * 0.16 },
      { x: cx - hipHalf + spineAt(hipYof(-1)), y: hipYof(-1) + HU * 0.20 },
      { x: cx - waistHalf + lW, y: waistY },
      { x: cx - chestHalf + lC, y: chestY - WGT * HU * 0.03 },
    ];
    mass(torso, shirt, 0.88, 4.8, -78, 651, "trunk");
    // THE COLLAR HAS LOST ITS SHAPE — a crew neck stretched wide and sagging
    // off-centre, with a second slack line where the ribbing has given up. Same
    // neckline as the close-up, at full-figure scale: one shirt, two framings.
    // It rides the shoulder tilt, so it sags toward the dropped side.
    const CW = HU * 0.34, CD = HU * 0.16, cSag = WGT * HU * 0.05;
    P.inkAdd(S.stroke([
      { x: cx - CW * 1.10 + lS, y: shYof(-1) + HU * 0.02 },
      { x: cx - CW * 0.62 + lS, y: shYof(-0.5) + HU * 0.18 },
      { x: cx + CW * 0.10 + lS, y: shoulderY + CD * 1.45 + cSag },
      { x: cx + CW * 0.78 + lS, y: shYof(0.5) + HU * 0.17 },
      { x: cx + CW * 1.06 + lS, y: shYof(1) + HU * 0.06 },
    ], { stroke: ink, width: 3.4, opacity: 0.84, amp: 2.2, over: 6, seed: 655 }));
    // THE SLACK SECOND COLLAR LINE comes off under hand-2 — a 0.36 line a few
    // units below a 0.84 one is the tentative-second-edge read this revision
    // exists to remove, and the collar's sag is already in the line above it.
    if (!H2) P.inkAdd(S.stroke([
      { x: cx - CW * 0.86 + lS, y: shYof(-1) + HU * 0.10 },
      { x: cx + CW * 0.06 + lS, y: shoulderY + CD * 1.92 + cSag },
      { x: cx + CW * 0.86 + lS, y: shYof(1) + HU * 0.12 },
    ], { stroke: ink, width: 2.2, opacity: 0.36, amp: 2.4, over: 5, seed: 658 }));
    // ---- the outfit's layer, over the torso -------------------------------
    if (OUT.layer) {
      const inset = HU * 0.1;
      const panelL = [
        { x: cx - chestHalf + lC + inset, y: chestY },
        { x: cx - HU * 0.16 + lC, y: chestY },
        { x: cx - HU * 0.2 + lW, y: waistY },
        { x: cx - waistHalf + lW + inset, y: waistY },
      ];
      const panelR = [
        { x: cx + HU * 0.16 + lC, y: chestY },
        { x: cx + chestHalf + lC - inset, y: chestY },
        { x: cx + waistHalf + lW - inset, y: waistY },
        { x: cx + HU * 0.2 + lW, y: waistY },
      ];
      const layerC = OUT.layer === "gilet" ? "#4E5862" : "#5A5F5C";
      [panelL, panelR].forEach(function (pn, i) {
        P.colourAdd(S.hatch(pn, { color: layerC, opacity: 0.9, gap: 6.2, width: 10, angle: -80 + i * 6, over: 10, seed: 731 + i * 5 }));
        P.inkAdd(S.outline(pn, { stroke: ink, width: 4.6, opacity: 0.95, amp: 2.4, over: 9, seed: 735 + i * 5 }));
      });
      // a gilet stops at the shoulder; a cardigan carries down the arm
      if (OUT.layer === "cardigan") {
        P.inkAdd(S.stroke([{ x: cx - chestHalf + lC, y: chestY + HU * 0.1 }, { x: cx - waistHalf + lW, y: waistY }], { stroke: ink, width: 3, opacity: 0.5, amp: 2, over: 6, seed: 741 }));
      }
    }
    // The rolled cuff is drawn with the ARM, not here: the arms are laid down
    // after the torso, so a cuff drawn at this point would sit under the sleeve it
    // is supposed to be a fold in. OUT.sleeves is read at the arm loop below.
    // placket and hem: two quiet lines that tell you it is a shirt. Under hand-2
    // the PLACKET goes and the HEM stays: the hem is the garment's bottom edge,
    // which is structure, and the placket is decoration on a torso that is now
    // modelled by a wash and does not need a seam drawn down it.
    if (!H2) P.inkAdd(S.line(cx + leanAt(shoulderY + HU * 0.4), shoulderY + HU * 0.4, cx + leanAt(waistY), waistY + HU * 0.2, { stroke: ink, width: 2.2, opacity: 0.3, amp: 2.2, over: 5, step: 7, seed: 657 }));
    P.inkAdd(S.line(cx - hipHalf * 0.92, hipY + HU * 0.06, cx + hipHalf * 0.92, hipY + HU * 0.02, { stroke: ink, width: 2.6, opacity: 0.34, amp: 2.4, over: 6, step: 7, seed: 659 }));

    // ---- arms, over the trunk ---------------------------------------------
    const hands = [];
    let forearmY = null;
    [-1, 1].forEach(function (s, i) {
      // No `|| arms[0]` fallback any more: every pose states both arms, because a
      // man with two identical arms is a mannequin. The shoulder joint takes the
      // TILTED shoulder height, so the arm inherits the posture instead of hanging
      // off a level peg while the outline dips around it.
      const t = POSE.arms[i];
      const sh = { x: cx + s * shoulderHalf * 0.78 + lS, y: shYof(s) + HU * 0.14 };
      let el = { x: clampX(sh.x + s * HU * t[0]), y: sh.y + HU * t[1] };
      let hd = { x: clampX(sh.x + s * HU * t[2]), y: sh.y + HU * t[3] };
      // WEIGHT ON THE DESK. The forearm is levelled — elbow and hand at one height
      // — because a forearm resting on a surface is horizontal, and a diagonal one
      // is a man reaching toward a desk he never touches. The height is published
      // in the manifest so the compositor can sit it on the room plate's own
      // contact point rather than guessing a desk height.
      const isForearm = (POSE.forearm === "left" && s === -1) || (POSE.forearm === "right" && s === 1);
      if (isForearm) {
        const fy = Math.max(el.y, hd.y);
        el = { x: el.x, y: fy };
        hd = { x: hd.x, y: fy + HU * 0.02 };
        forearmY = fy;
      }
      // rolled sleeves stop at the elbow: upper arm in cloth, forearm bare
      mass(quad(sh, el, HU * 0.27, HU * 0.21), shirt, 0.86, 4.0, -60 + i * 20, 661 + i * 17, "quad");
      mass(quad(el, hd, HU * 0.19, HU * 0.15), OUT.sleeves === "rolled" ? skin : skin, 0.46, 3.6, -60 + i * 20, 681 + i * 17, "quad");
      if (OUT.sleeves === "rolled") {
        // the fold itself: a short heavy band across the elbow
        P.inkAdd(S.stroke([{ x: el.x - HU * 0.2, y: el.y - HU * 0.04 }, { x: el.x + HU * 0.2, y: el.y + HU * 0.02 }], { stroke: ink, width: 5.4, opacity: 0.9, amp: 2, over: 6, seed: 751 + i }));
        P.colourAdd(S.hatch(quad(sh, el, HU * 0.27, HU * 0.21).slice(0, 4), { color: shirt, opacity: 0.3, gap: 8, width: 11, angle: -60 + i * 20, over: 8, seed: 755 + i, rim: false }));
      }
      if (OUT.layer === "cardigan") {
        // the cardigan carries down the upper arm
        P.colourAdd(S.hatch(quad(sh, el, HU * 0.28, HU * 0.22), { color: "#5A5F5C", opacity: 0.82, gap: 6.4, width: 10, angle: -60 + i * 20, over: 9, seed: 761 + i * 5 }));
        P.inkAdd(S.outline(quad(sh, el, HU * 0.28, HU * 0.22), { stroke: ink, width: 4.2, opacity: 0.92, amp: 2.2, over: 8, seed: 765 + i * 5 }));
      }
      const hand = ell(hd.x, hd.y + HU * 0.12, HU * 0.19, HU * 0.17, 16, 0.06, 691 + i);
      P.colourAdd(S.hatch(hand, { color: skin, opacity: 0.5, gap: 5.6, width: 9, angle: -70, over: 7, seed: 695 + i }));
      P.inkAdd(S.outline(hand, { stroke: ink, width: 3.4, opacity: 0.9, amp: 1.9, over: 7, seed: 699 + i }));
      // §6 — A THUMB AND ONE KNUCKLE BREAK. The hand was a circle: an
      // undifferentiated mitten, and at render scale a blob. A hand resting on a
      // surface is the most legible "this person is doing something" signal on
      // the plate, and two strokes is all it takes at this size — more than that
      // is fingers, and fingers at 0.43 scale are noise. The thumb goes on the
      // INBOARD side (toward the body, which is where a thumb is when a palm is
      // down) and carries occlusion weight where it leaves the hand; the knuckle
      // break runs across the back, not around it.
      if (H2) {
        const hx = hd.x, hy = hd.y + HU * 0.12;
        P.inkAdd(S.stroke([
          { x: hx - s * HU * 0.15, y: hy + HU * 0.04 },
          { x: hx - s * HU * 0.235, y: hy - HU * 0.055 },
          { x: hx - s * HU * 0.165, y: hy - HU * 0.135 },
        ], { stroke: ink, width: 3.2, opacity: 0.93, amp: 1.1, seed: 960 + i, heavy: 1.2 }));
        P.inkAdd(S.stroke([
          { x: hx - s * HU * 0.09, y: hy - HU * 0.105 },
          { x: hx + s * HU * 0.13, y: hy - HU * 0.05 },
        ], { stroke: ink, width: 2.3, opacity: 0.62, amp: 0.9, seed: 962 + i }));
      }
      hands.push({ x: hd.x, y: hd.y + HU * 0.12 });
    });

    if (pose === "holding-a-page") {
      const midX = (hands[0].x + hands[1].x) / 2, midY = (hands[0].y + hands[1].y) / 2;
      const pw2 = HU * 0.95, ph2 = HU * 1.25;
      const page = [
        { x: midX - pw2, y: midY - ph2 * 0.86 }, { x: midX + pw2, y: midY - ph2 * 0.94 },
        { x: midX + pw2 * 0.94, y: midY + ph2 * 0.28 }, { x: midX - pw2 * 1.02, y: midY + ph2 * 0.22 },
      ];
      // a page held against a pale shirt needs its own value or it reads as a smear
      P.colourAdd(S.hatch(page, { color: "#F6F1E4", opacity: 0.96, gap: 7, width: 8, angle: -4, over: 7, seed: 681 }));
      P.inkAdd(S.outline(page, { stroke: ink, width: 4.2, opacity: 0.95, amp: 2.6, over: 9, seed: 682 }));
      for (let i = 1; i <= 5; i++) {
        const ly = midY - ph2 * 0.66 + i * (ph2 * 0.17);
        P.inkAdd(S.line(midX - pw2 * 0.72, ly, midX + pw2 * (0.2 + (i % 3) * 0.22), ly - 2, { stroke: ink, width: 2.2, opacity: 0.5, amp: 1.8, over: 5, step: 7, seed: 685 + i }));
      }
      P.artBox("page", midX - pw2 - 14, midY - ph2 * 0.98, pw2 * 2 + 28, ph2 * 1.34);
    }

    // ---- head -------------------------------------------------------------
    const R = HU * 0.47;
    const hcx = cx + leanAt(headCy), hcy = headCy + HEAD_SINK;
    // THE HEAD IS WHERE THE EYE HAS TO LAND, and it was the one part still sitting
    // cream on a cream wall: the shirt and trousers were fixed in revision 03, so
    // the eye went to his chest instead of his face. The head now carries the
    // heaviest outline on the plate and a skin value with somewhere to go, plus a
    // turned plane strong enough to model it.
    //
    // The drawing itself lives in hostFace so the close-up and the full figure
    // cannot disagree about what he looks like.
    const FACE = hostFace({
      P: P, S: S, ell: ell, dot: function (q, r, sd) { dot(q.x, q.y, r, sd); },
      cx: hcx, cy: hcy, R: R, ink: ink, skin: skin, hair: hair,
      lw: 1, seg: 0, fine: false, tilt: HEAD_TILT,
      mouthOpen: mouthOpen, closedEyes: pose === "head-in-hands",
    });
    const eyeY = FACE.eyeY;

    // THE RIG, PUBLISHED. Declared here rather than beside floorLineY because
    // forearmY is only known once the arms have been solved. A compositor cutting
    // two-shots needs to know which way he leans and which leg carries him, and
    // forearmY is what lets leaning-on-desk actually meet a desk: align it to the
    // room plate's own slots["host-anchor"].contact.y instead of guessing a height.
    P.meta.rig = {
      pose: pose,
      seated: SEATED,
      weightOn: WGT < 0 ? "camera-left leg" : "camera-right leg",
      lean: POSE.lean,
      slump: SLUMP,
      spine: "curved: offset = lean·u^1.7 + 0.72·slump·u^2.3, u = 0 at the hip and 1 at the crown. Both terms are powers, so displacement piles up toward the head and the mid-torso lags behind — the head finishes forward of the hips over a chest that is still back. A linear ramp, which is what shipped through revision 06, can only ever be a plank leaning.",
      headSink: Math.round(HEAD_SINK),
      hipTilt: "loaded hip raised " + Math.round(HIP_TILT) + "px; shoulders counter-tilt " + Math.round(SH_TILT) + "px the other way, applied to the shoulder JOINTS so the arms inherit it",
      armsMirrored: false,
      forearmY: forearmY == null ? null : Math.round(forearmY),
      forearmNote: forearmY == null
        ? "this pose makes no surface contact"
        : "his forearm rests at this y. Align it to the room plate's host-anchor contact point; the forearm is drawn level because a forearm resting on a desk is horizontal, and a diagonal one is a man reaching for a desk he never touches.",
    };

    // Contact: small and tight, so he stands ON the floor line rather than
    // hovering over it. The one thing on this plate allowed darker than the line.
    P.colourAdd(S.hatch(ell(cx, floorY + HU * 0.02, hipHalf * 1.0, HU * 0.1, 14, 0.08, 781), { color: "#1C222A", opacity: 0.3, gap: 4.5, width: 8, angle: -6, over: 5, seed: 782 }));
    P.colourAdd(S.hatch(ell(cx, floorY + HU * 0.015, hipHalf * 0.55, HU * 0.06, 12, 0.1, 783), { color: "#1C222A", opacity: 0.44, gap: 3.4, width: 6, angle: -6, over: 4, seed: 784 }));
    P.meta.contrast = {
      rule: "Dennis is the highest-contrast object in any frame he is in",
      why: "he is the reason anyone is watching, and a figure at the same value as the desk behind him disappears into it",
      how: "his own material hatch and a neutral ink pass on each part's turned side; the room's heaviest furniture tops out at a 0.19 ink hatch and he sits above it",
      note: "he is NOT lit to match the room. Revision 01 tinted him from the room's two sources and that is exactly what closed the gap. The room gives way to him, not the other way round.",
    };

    P.slot("mouth", hcx - R * 0.26, hcy + R * 0.44, R * 0.52, R * 0.34, { role: "mouth", region: true, note: "talk frames differ here only" });
    P.slot("head", hcx - R, hcy - R * 1.15, R * 2, R * 2.2, { role: "head", region: true });
    P.slot("figure", cx - shoulderHalf * 1.9, hcy - R * 1.35, shoulderHalf * 3.8, floorY - hcy + R * 1.5, { role: "figure", region: true, note: "cut-out bounds; stand on floorLineY. A room's host-anchor height scales (floorLineY - this box's y), not the box height — the box runs past the floor line to carry the shoes" });
    // §4.1 — WHAT A SEATED CUT-OUT NEEDS THE RENDERER TO KNOW, and it is not what
    // a standing one needs.
    //
    // The anchor contract scales a host until (floorLineY - figure.y) equals the
    // anchor's height. Applied to this plate unchanged, a seated Dennis is scaled
    // UP until his 5.0HU seated height fills a 6.8HU standing anchor — a 36%
    // oversized man sitting in exactly the right place. The plate publishes the
    // ratio rather than leaving the renderer to notice, because no still would
    // show it: he would simply look close to camera.
    if (SEATED) {
      P.meta.seated = {
        // DERIVED, not authored. The seat drop is the only difference between this
        // plate's scaling height and a standing pose's, so the ratio comes out of
        // the rig rather than out of a head count: measured 959 against 1297 on a
        // 1920-tall plate, which is the 0.738 below.
        heights: {
          seatedScaleHeight: Math.round(floorY - (hcy - R * 1.35)),
          standingEquivalent: Math.round(floorY - (hcy - R * 1.35) + SEAT_DROP),
          seatDrop: Math.round(SEAT_DROP),
          ratio: +((floorY - (hcy - R * 1.35)) / (floorY - (hcy - R * 1.35) + SEAT_DROP)).toFixed(4),
        },
        anchorScale: "STANDING-EQUIVALENT. Scale so (floorLineY - figure.y) equals anchor.targetHeight x heights.ratio, NOT the target height. The floor pin is unchanged — his feet are on the floor and floorLineY still lands on the room's floorLineY.",
        chair: "drawn ON THIS PLATE, not in the room. A seated cut-out over a set with no chair is a man hovering at desk height, so the chair travels with him. The cost is that it is the same chair in every room, which is the lesser problem: it is his chair.",
        chairContrast: "the chair is hatched at about half the figure's opacity and outlined at two thirds its weight. room/ doctrine is that he is the highest-contrast object in any frame he is in, and that has to hold inside his own cut-out too.",
        note: "seated and leaning into the desk, not upright in a chair: a man sitting straight reads as an interview, and this channel is a man at his own desk at three in the morning.",
      };
    }
    return P;
  }

  /* §4.3 — THE EMPTY CHAIR. His chair, with nobody in it.

     One plate, and it is the same chair the seated pose sits on — literally the
     same function, so the two cannot drift into being two different chairs. That
     shared geometry is the only reason this asset is cheap enough to ship in this
     drop while over-the-shoulder is not.

     What it is FOR: the cut-away at the end of a long chapter, or under a line the
     voice-over delivers over an empty set. It is the one host-family plate with no
     host on it, which is the whole point — the absence reads because the chair is
     recognisably the one he was in.

     It publishes floorLineY and stands on it like a figure does, so it composites
     onto an existing host-anchor with no new contract: the chair's own height is
     1.0 by definition, and the seated ratio does not apply because there is no
     seated body to scale. */
  function emptyChair(o) {
    const w = o.w, h = o.h, p = o.pal;
    const P = H.Plate({
      key: o.key, w, h, seed: o.seed, pal: Object.assign({}, p, { ground: "none", grain: null }),
      meta: {
        aspect: w > h ? "16x9" : "9x16", family: "host", type: "empty-chair",
        // DECLARED, not implied. This author was written apart from hostFigure and
        // hostHead and never carried the two fields both of those set in this same
        // object — so the one host plate that IS unarguably a cut-out (ground
        // "none", no grain, composites onto a host-anchor, and its own dataPolicy
        // below says so in prose) published nothing a gate could read, and
        // test_every_role_can_supply_a_shot failed on "not a cut-out". The plate
        // was always a cut-out; the metadata was the defect.
        cutout: true, alpha: true,
        dataPolicy: "alpha cut-out, no ground: it composites onto a room's host-anchor exactly as a figure does",
      },
    });
    const floorY = Math.round(h * 0.9);
    P.meta.floorLineY = floorY;
    const S = boilShift(inkScale(h / 1920), o.boil | 0);
    const HU = (h * 0.665) / 6.8;
    const cx = w * 0.5;
    const ink = ROLES.structure.hex;
    const seatY = floorY - HU * 1.95;   // the same seat height the rig sits at
    const geo = hostChair({ P: P, S: S, HU: HU, cx: cx, seatY: seatY, floorY: floorY, ink: ink, fwd: -1 });
    // The contact shadow, the same pair the figure gets — without it the chair
    // hovers, which is the defect this plate exists to avoid in the first place.
    P.colourAdd(S.hatch(ellipse(cx - HU * 0.1, floorY + HU * 0.02, HU * 0.9, HU * 0.1, 14, 0.08, 1191), { color: "#1C222A", opacity: 0.26, gap: 4.5, width: 8, angle: -6, over: 5, seed: 1192 }));
    // THE CHAIR CARRIES ITS OWN RATIO, and this is drop eight's correction.
    //
    // It used to say: scale (floorLineY - figure.y) to the anchor height DIRECTLY,
    // because there is no seated body to scale. That reasoning is wrong in a way
    // only a composite shows, and render-scale.html §14 is where it showed. The
    // anchor's targetHeight is a STANDING figure's height. Scaling a chair to it
    // makes the chair as tall as a standing man: on room/desk-front-16x9 the same
    // chair came out at 562 units under this plate and 342 under the seated pose —
    // 64% larger with nobody in it, and taller than the 416-unit man who sits in
    // it — with its back 220 units higher up the frame on the one cut the plate
    // exists for. The claim that hid it was true of the drawing and false of the
    // contract: same chair, one function, two sizes.
    //
    // So it publishes a ratio like the seated pose does, against the same standing
    // equivalent, and the two now composite at one scale. DERIVED, not authored:
    // the seated pose publishes standingEquivalent as 0.6755 of canvas height, and
    // the ratio is this plate's own span over that. preflight check L asserts it
    // against a seated pose measured in the same run, so neither can drift alone.
    const figY = geo.postTop.y - HU * 0.2, chairSpan = floorY - figY;
    const STANDING_EQUIV = h * 0.6755;
    P.slot("figure", cx - HU * 1.5, figY, HU * 3, chairSpan + HU * 0.2, {
      role: "figure", region: true,
      note: "cut-out bounds; stand on floorLineY, same as a host figure. Scale so (floorLineY - figure.y) equals anchor.targetHeight x chair.heights.ratio — NOT the target height directly. The anchor height is a STANDING figure's; a chair scaled to it is a chair taller than the man who sits in it.",
    });
    P.meta.chair = {
      heights: {
        chairHeight: Math.round(chairSpan),
        standingEquivalent: Math.round(STANDING_EQUIV),
        ratio: +(chairSpan / STANDING_EQUIV).toFixed(4),
      },
      anchorScale: "STANDING-EQUIVALENT, exactly as the seated pose. Scale so (floorLineY - figure.y) equals anchor.targetHeight x heights.ratio. The floor pin is unchanged — the chair stands on the floor and floorLineY still lands on the room's floorLineY.",
      matchesSeated: "this ratio and host/sitting-at-desk's are different numbers against the SAME standing equivalent, and they are what make the chair one size across the cut: him, then his chair. A renderer that applies the seated 0.7394 here, or no ratio at all, breaks that in opposite directions.",
    };
    P.meta.emptyChair = {
      shares: "engine/plates.js hostChair() — the identical function the sitting-at-desk pose draws, so the empty chair and the occupied one are the same object by construction rather than by care.",
      use: "the cut-away at the end of a long chapter, or under a line delivered over an empty set. The absence reads because the chair is recognisably the one he was in.",
      note: "no host, and no host-anchor contract of its own. It is furniture that composites where he would have been.",
    };
    return P;
  }

  const HOST_POSES = ["leaning-on-desk", "hands-in-pockets", "holding-a-page", "pointing-down-at-desk", "head-in-hands", "walking-out-of-frame", "sitting-at-desk"];

  /* THE HOST, CLOSE. Two framings: head-and-shoulders and waist-up.

     Six poses shipped, all full-body, all the same size in frame — so in a forty
     minute video the shot needed most, his FACE, did not exist. The confession,
     the turn, the moment the argument lands: none of them have a plate.

     Why this is a draw and not a crop. Everywhere else in this pack a tighter
     framing is free — the plates are 3840x2160 and the video is 1920x1080, so the
     renderer crops a native-resolution medium out of any wide. It does not work
     here: on the full figure the head slot is 176x194 canvas units, and filling a
     1080-tall frame with it is a 6x upscale of a line drawing. A close-up needs the
     head drawn AT close-up size, where the jaw, the brow and the mouth carry real
     line weight. That is a different drawing, not a different rectangle.

     Why the head vocabulary is duplicated from hostFigure rather than shared. The
     six poses are finished, verified and shipped, and their thirty files must stay
     byte-identical: extracting a shared head means proving the emitted string
     sequence did not change, which costs a re-render of all thirty to verify. So
     the head is copied here, at close-up scale, and the two are kept in step by
     hand. That is the honest trade, and it is written down so the next revision
     knows it is a decision and not an accident.

     NO FLOOR LINE. These are not standing figures and there is nothing to pin to a
     room's floor. They declare `fit` instead — an EYE LINE, which is how a close-up
     is actually placed — and `floorLineY: false` rather than a number a compositor
     could believe. */
  function hostHead(o) {
    const w = o.w, h = o.h, p = o.pal, mouthOpen = o.mouthOpen, bob = o.bob || 0;
    const framing = o.framing === "medium" ? "medium" : "close-up";
    const close = framing === "close-up";
    const P = H.Plate({
      key: o.key, w: w, h: h, seed: o.seed,
      pal: { ground: "none", ground2: p.ground2, grain: null, structure: p.structure, surfaceKey: p.surfaceKey },
      meta: { family: "host", framing: framing, pose: framing, aspect: close ? "1x1" : "3x4", cutout: true, alpha: true, boil: o.boil | 0 },
    });
    const ink = p.structure;
    const OUT = HOST_OUTFITS[o.outfit] || HOST_OUTFITS[HOST_OUTFIT_DEFAULT];
    P.meta.outfit = o.outfit || HOST_OUTFIT_DEFAULT;
    const shirt = OUT.top, skin = SKIN, hair = "#3B3129";
    const H2 = !!(H.profile && H.profile() === "hand-2");
    const BOFF = (o.boil | 0) * 9173;
    const S = boilShift(inkScale(h / 1920), o.boil | 0);
    const ell = function (cx2, cy2, rx, ry, n, jit, seed) { return ellipse(cx2, cy2, rx, ry, n, jit, seed + BOFF); };

    // ---- framing ----------------------------------------------------------
    // R is the head's radius unit, exactly as in hostFigure (there R = HU*0.47).
    // Everything below is landmarked off it, so the two framings are the same man
    // at two distances rather than two differently-proportioned drawings.
    //
    // The close-up's two numbers are SOLVED, not chosen: the head top wants to sit
    // just inside the frame and the shoulders want to enter around three quarters
    // down, which given shoulderY = hcy + 1.787R fixes both R and hcy. Set by eye
    // the first time, the shoulders landed at 0.87h and the plate came out as a
    // head on a stick with a slab of shirt under it.
    const R = close ? h * 0.241 : h * 0.158;
    const HU = R / 0.47;
    const cx = w * 0.5;
    const hcy = (close ? h * 0.301 : h * 0.2174) + bob;
    const hcx = cx;
    const shoulderY = hcy + HU * 0.84 + bob * 0.5;
    const chestY = hcy + HU * 1.39, waistY = hcy + HU * 2.14, hipY = hcy + HU * 2.64;
    // In a close-up the shoulders RUN OFF both edges. A close-up whose shoulders
    // fit inside the frame is a medium shot with a big head in it.
    const shoulderHalf = close ? R * 1.78 : HU * 0.86;
    const chestHalf = close ? R * 2.0 : HU * 0.8;
    const waistHalf = HU * 0.66, hipHalf = HU * 0.78;

    // §3 — NO BLOOM ON A MASS. Every polygon that comes through here is a
    // CONSTRUCTION polygon: a torso quad whose bottom is under the trousers, a
    // limb quad whose ends are inside the shoulder and the hand it joins. Their
    // boundaries are not the material's boundary, so rimming them draws exactly
    // what the review found — a quadrilateral across the shirt, a parallelogram
    // where the forearm crosses the sleeve, a hard rectangle at the elbow,
    // horizontal breaks at the knees. Same rule the neck quad already uses; the
    // silhouette is carried by outline() below, which is the line that is real.
    // §5c — the outline clause, same derivation as hostFigure: on a construction
    // polygon the silhouette stays and the interior edges go, outline as well as
    // rim. "quad" drops a limb's two buried ends; "trunk" drops the edges whose
    // endpoints both sit at the extreme of the polygon's y-range — the
    // shoulder-to-shoulder top, under the collar, and the hem, under the frame.
    const interiorEdges = function (poly, mode) {
      const n = poly.length;
      if (mode === "quad") return { 1: 1, 3: 1 };
      const ys = poly.map(function (p) { return p.y; });
      const y0 = Math.min.apply(null, ys), y1 = Math.max.apply(null, ys);
      const band = (y1 - y0) * 0.08, out = {};
      for (let i = 0; i < n; i++) {
        const a = poly[i], b = poly[(i + 1) % n];
        if ((a.y <= y0 + band && b.y <= y0 + band) || (a.y >= y1 - band && b.y >= y1 - band)) out[i] = 1;
      }
      return out;
    };
    const contour = function (poly, mode, o) {
      if (!H2 || !mode) return P.inkAdd(S.outline(poly, o));
      // "none" — every edge is interior. The neck is the case: BOTH its long
      // sides are buried at the top (inside the skull) and at the bottom (under
      // the collar), so there is no whole edge left to draw and the visible span
      // has to be cut from the drawing's own boundaries instead. The caller draws
      // it; see the neck below.
      if (mode === "none") return P;
      const skip = interiorEdges(poly, mode);
      const n = poly.length;
      let run = [];
      for (let i = 0; i < n; i++) {
        if (skip[i]) {
          if (run.length > 1) P.inkAdd(S.stroke(run, Object.assign({}, o, { silhouette: true })));
          run = [];
        } else {
          if (!run.length) run.push(poly[i]);
          run.push(poly[(i + 1) % n]);
        }
      }
      if (run.length > 1) P.inkAdd(S.stroke(run, Object.assign({}, o, { silhouette: true })));
      return P;
    };
    const mass = function (poly, colour, op, lw, ang, seed, mode) {
      const c = centroid(poly);
      const noRim = H2 ? { rim: false } : null;
      P.colourAdd(S.hatch(poly, Object.assign({ color: colour, opacity: op, gap: 6.8, width: 11.5, angle: ang, over: 11, seed: seed }, noRim)));
      const inboard = c.x < cx ? clipHalf(poly, -1, 0, -c.x) : clipHalf(poly, 1, 0, c.x);
      if (inboard) P.colourAdd(S.hatch(inboard, { color: ink, opacity: 0.2, gap: 8, width: 12, angle: ang - 6, over: 8, seed: seed + 3 }));
      contour(poly, mode, { stroke: ink, width: lw * 1.35, opacity: 0.97, amp: 2.8, over: 10, seed: seed + 1 });
    };
    const dot = function (x, y, r, seed) {
      P.topAdd(S.hatch(ell(x, y, r, r, 12, 0.05, seed), { color: ink, opacity: 0.95, gap: 2.4, width: 4.4, angle: -60, over: 3, seed: seed + 1 }));
    };
    const quad = function (a2, b2, wa, wb) {
      const dx = b2.x - a2.x, dy = b2.y - a2.y, L = Math.hypot(dx, dy) || 1;
      const nx = -dy / L, ny = dx / L;
      return [
        { x: a2.x + nx * wa, y: a2.y + ny * wa }, { x: b2.x + nx * wb, y: b2.y + ny * wb },
        { x: b2.x - nx * wb, y: b2.y - ny * wb }, { x: a2.x - nx * wa, y: a2.y - ny * wa },
      ];
    };

    // ---- torso, then neck, then head: back to front -----------------------
    // THE SHOULDERS SLOPE, IN BOTH FRAMINGS. A torso whose top edge is horizontal
    // from one arm to the other is a plank he is standing behind — which is what
    // both of these were on the first pass. A trapezius line from the neck out to
    // each shoulder point is the whole difference between a bust and a sandwich
    // board, and at waist-up it is the only thing giving the figure a top.
    // ONE SHOULDER LOWER. Square shoulders are the last symmetry left once the
    // head is tilted, and square reads as composed. His camera-right shoulder
    // drops; the tilt leans the other way, which is what a person standing on one
    // leg actually does. The medium takes LESS of it than the close-up: at the
    // close-up's figure the drop is a shoulder, but across a waist-up torso the
    // same fraction bends the whole ribcage and he reads as deformed rather than
    // relaxed. Same posture, read at two distances, so it is two numbers.
    const DROP = R * (close ? 0.17 : 0.085);
    const nHalf = R * 0.40;
    const torso = close ? [
      { x: cx - nHalf, y: shoulderY - R * 0.52 },
      { x: cx - shoulderHalf * 0.54, y: shoulderY - R * 0.34 },
      { x: cx - shoulderHalf, y: shoulderY + R * 0.10 },
      { x: cx - chestHalf, y: h + HU * 0.4 },
      { x: cx + chestHalf, y: h + HU * 0.4 },
      { x: cx + shoulderHalf, y: shoulderY + R * 0.12 + DROP },
      { x: cx + shoulderHalf * 0.54, y: shoulderY - R * 0.32 + DROP },
      { x: cx + nHalf, y: shoulderY - R * 0.52 + DROP * 0.34 },
    ] : [
      { x: cx - nHalf, y: shoulderY - R * 0.48 },
      { x: cx - shoulderHalf * 0.55, y: shoulderY - R * 0.30 },
      { x: cx - shoulderHalf * 0.94, y: shoulderY + R * 0.12 },
      { x: cx - chestHalf, y: chestY },
      { x: cx - waistHalf, y: waistY },
      { x: cx - hipHalf, y: hipY },
      { x: cx + hipHalf, y: hipY },
      { x: cx + waistHalf, y: waistY },
      { x: cx + chestHalf, y: chestY },
      { x: cx + shoulderHalf * 0.94, y: shoulderY + R * 0.14 + DROP },
      { x: cx + shoulderHalf * 0.55, y: shoulderY - R * 0.28 + DROP },
      { x: cx + nHalf, y: shoulderY - R * 0.48 + DROP * 0.34 },
    ];
    // The neck is SHORT in both: it starts under the jaw rather than at the head's
    // centre, which is what keeps it from reading as a trunk.
    const neckTop = hcy + R * 0.56;
    const neckBot = shoulderY - R * (close ? 0.18 : 0.14) + (H2 ? R * 0.5 : 0);
    const neckPoly = quad({ x: hcx, y: neckTop }, { x: cx, y: neckBot }, R * 0.36, R * 0.42);
    // NO CLOSED OUTLINE ON THE NECK. mass() puts every hatch on the colour layer
    // and every line on the ink layer, so a neck outlined as a quad has its bottom
    // edge painted on top of the shirt that is meant to cover it. At full-figure
    // size the collar hides that; at these sizes it is a box drawn on his chest.
    // Two side lines from jaw to collar is all a neck needs.
    //
    // AND UNDER hand-2 THE SAME PROBLEM COMES BACK THROUGH THE COLOUR LAYER. A
    // wash has an edge where a hatch had none, so the quad's straight bottom and
    // its rim drew the box on his chest that the note above is about. Two fixes,
    // both local to the construction: `rim: false` (the quad's boundary is not
    // the material's — the bottom is under the collar and the sides are under the
    // jaw), and the quad runs half a head-radius further down so its end is
    // behind the shirt that mass() lays over it on the next line.
    const neckRim = H2 ? { rim: false } : null;
    P.colourAdd(S.hatch(neckPoly, Object.assign({ color: skin, opacity: 0.44, gap: 6.8, width: 11.5, angle: -84, over: 11, seed: 641 }, neckRim)));
    const inb = clipHalf(neckPoly, -1, 0, -cx);
    if (inb) P.colourAdd(S.hatch(inb, Object.assign({ color: ink, opacity: 0.2, gap: 8, width: 12, angle: -90, over: 8, seed: 644 }, neckRim)));
    // §5c — AND THE NECK'S OWN SIDES ARE THE CASE THAT FOUND THE CLAUSE. They
    // ran the full height of the quad: the top end starts at neckTop, which is
    // inside the head ellipse (ry is R*0.98 against a neckTop of R*0.56), and the
    // bottom end lands on the shirt, because ink draws over colour. A line that
    // passes through a jaw and stops in mid-garment is not an edge.
    //
    // Under hand-2 the visible span only: it begins where the jaw's silhouette
    // leaves off and ends above the collar line, and stroke2 tapers both ends, so
    // the neck goes under the shirt rather than stopping on it. Full height under
    // hand-1, as shipped.
    [-1, 1].forEach(function (s, i) {
      // THE SPAN IS THE VISIBLE SKIN, and both ends are now read off the two
      // shapes that actually occlude it rather than estimated from the quad.
      //
      // top: the head is drawn by hostFace as ell(hcx, hcy, R*0.86, R*0.98), so
      // its lower boundary at the neck's own half-width is exact — plus R*0.12,
      // because that boundary carries a 6.4-wide outline and the skin only
      // starts below it. delta-13c still began inside the jaw; this is why.
      //
      // bottom: scanned off the TORSO polygon at the same x. delta-13c used
      // shoulderY + R*0.05, which is below the shirt's upper edge — so the line
      // got LONGER, not shorter, which is exactly what the crop shows. The shirt
      // is the thing that hides the neck, so the shirt is what the line must
      // stop at: its own boundary, minus a hair so the taper finishes on skin.
      const upperAt = function (poly, xq) {
        let best = null;
        for (let q = 0; q < poly.length; q++) {
          const a = poly[q], b = poly[(q + 1) % poly.length];
          if ((a.x <= xq && b.x > xq) || (b.x <= xq && a.x > xq)) {
            const yq = a.y + ((xq - a.x) / (b.x - a.x)) * (b.y - a.y);
            if (best === null || yq < best) best = yq;
          }
        }
        return best;
      };
      const xq = cx + s * R * 0.38;
      const shirtTop = upperAt(torso, xq);
      const y0 = H2
        ? hcy + R * (0.98 * Math.sqrt(Math.max(0, 1 - Math.pow(0.38 / 0.86, 2))) + 0.12)
        : neckTop;
      const y1 = H2
        ? (shirtTop == null ? shoulderY - R * 0.12 : shirtTop - R * 0.03)
        : shoulderY - R * (close ? 0.18 : 0.14);
      if (H2 && y1 - y0 < R * 0.05) return;
      // PUBLISHED, so the span is checkable without a rasteriser and without an
      // endpoint detector guessing which marks are the neck. The drawn line is
      // this interval plus wobble and minus the taper, never outside it: hand-2
      // sets the stroke overshoot to 0, so there is no end extension to add.
      if (s < 0) P.meta.neckSpan = [Math.round(y0), Math.round(y1)];
      P.inkAdd(S.stroke([{ x: cx + s * R * 0.36, y: y0 }, { x: cx + s * R * 0.40, y: y1 }], { stroke: ink, width: close ? 4.4 : 3.8, opacity: 0.9, amp: 2, over: 7, seed: 646 + i, heavy: H2 ? 1.2 : 1 }));
    });
    mass(torso, shirt, 0.88, close ? 5.6 : 5, -78, 651, "trunk");
    // THE COLLAR HAS LOST ITS SHAPE. The shipped neckline was a tidy V — smart
    // casual, a man dressed to be seen. This is a crew neck stretched wide and
    // sagging off-centre, with a second slack line where the ribbing has given up.
    const CW = R * 0.66, CD = R * 0.30;
    P.inkAdd(S.stroke([
      { x: cx - CW * 1.18, y: shoulderY - R * 0.34 },
      { x: cx - CW * 0.72, y: shoulderY + R * 0.06 },
      { x: cx - CW * 0.18, y: shoulderY + CD },
      { x: cx + CW * 0.34, y: shoulderY + CD * 0.86 + DROP * 0.5 },
      { x: cx + CW * 0.80, y: shoulderY + R * 0.01 + DROP * 0.6 },
      { x: cx + CW * 1.14, y: shoulderY - R * 0.40 + DROP * 0.7 },
    ], { stroke: ink, width: (close ? 5.2 : 4.4) * 0.92, opacity: 0.88, amp: 2.4, over: 7, seed: 655 }));
    // AND THE JACKET PAYS FOR THE FACE. §3.6: detail everywhere is the same as
    // detail nowhere, so the second slack collar line — the ribbing that has
    // given up — comes off under hand-2. It was a 0.4-opacity line a couple of
    // units below a 0.88 one, which at close-up size is the same tentative
    // second edge this revision exists to remove, and the collar's shape is
    // already carried by the line above it and the wash under it.
    if (!H2) P.inkAdd(S.stroke([
      { x: cx - CW * 0.92, y: shoulderY - R * 0.10 },
      { x: cx - CW * 0.22, y: shoulderY + CD * 1.26 },
      { x: cx + CW * 0.38, y: shoulderY + CD * 1.10 + DROP * 0.5 },
      { x: cx + CW * 0.92, y: shoulderY - R * 0.16 + DROP * 0.6 },
    ], { stroke: ink, width: 2.6, opacity: 0.4, amp: 2.6, over: 6, seed: 658 }));
    if (OUT.layer) {
      const robe = OUT.layer === "robe";
      const inset = HU * 0.1, layerC = OUT.layer === "gilet" ? "#4E5862" : robe ? "#6E6A62" : "#5A5F5C";
      const lowY = close ? h + HU * 0.4 : waistY;
      // A ROBE IS NOT A CARDIGAN. Its panels are wider, they cross toward the
      // middle instead of hanging parallel, and it has a SHAWL collar — one
      // continuous band folded back around the neck, which is the whole silhouette
      // of the garment. Drawn as cardigan panels in a different grey it would read
      // as the same knitwear again, and the point of a second outfit is that the
      // episode looks different.
      [[-1], [1]].forEach(function (sg, i) {
        const s2 = sg[0];
        const pn = robe ? [
          { x: cx + s2 * (chestHalf + inset * 0.4), y: chestY - R * 0.10 },
          { x: cx + s2 * HU * 0.05, y: chestY + R * 0.32 },
          { x: cx + s2 * HU * 0.12, y: lowY },
          { x: cx + s2 * (chestHalf + inset * 0.2), y: lowY },
        ] : [
          { x: cx + s2 * (chestHalf - inset), y: chestY }, { x: cx + s2 * HU * 0.16, y: chestY },
          { x: cx + s2 * HU * 0.2, y: lowY }, { x: cx + s2 * ((close ? chestHalf : waistHalf) - inset), y: lowY },
        ];
        P.colourAdd(S.hatch(pn, { color: layerC, opacity: 0.9, gap: 6.2, width: 10, angle: -80 + i * 6, over: 10, seed: 731 + i * 5 }));
        P.inkAdd(S.outline(pn, { stroke: ink, width: 4.6, opacity: 0.95, amp: 2.4, over: 9, seed: 735 + i * 5 }));
      });
      if (robe) {
        [[-1], [1]].forEach(function (sg, i) {
          const s2 = sg[0];
          const band = [
            { x: cx + s2 * CW * 1.16, y: shoulderY - R * 0.40 },
            { x: cx + s2 * CW * 1.52, y: shoulderY - R * 0.22 },
            { x: cx + s2 * HU * 0.20, y: chestY + R * 0.30 },
            { x: cx + s2 * HU * 0.04, y: chestY + R * 0.24 },
            { x: cx + s2 * CW * 0.74, y: shoulderY - R * 0.14 },
          ];
          P.colourAdd(S.hatch(band, { color: layerC, opacity: 0.72, gap: 5.4, width: 9, angle: -62 + i * 10, over: 9, seed: 761 + i * 5 }));
          P.inkAdd(S.outline(band, { stroke: ink, width: 4.2, opacity: 0.9, amp: 2.2, over: 8, seed: 765 + i * 5 }));
        });
        // the tie belt sits at waistY, which in a waist-up frame is the crop edge
        // itself — drawn there it was a smudge on the bottom border rather than a
        // belt. Raised into the frame, where it reads, and the crossing lapels are
        // doing most of the work anyway.
        if (!close) {
          P.inkAdd(S.stroke([
            { x: cx - chestHalf * 0.86, y: waistY - R * 0.52 },
            { x: cx - HU * 0.10, y: waistY - R * 0.34 },
            { x: cx + chestHalf * 0.78, y: waistY - R * 0.56 },
          ], { stroke: ink, width: 5.2, opacity: 0.86, amp: 2.6, over: 8, seed: 771 }));
        }
      }
    }
    if (!H2) P.inkAdd(S.line(cx, shoulderY + HU * 0.4, cx, close ? h : waistY + HU * 0.2, { stroke: ink, width: 2.2, opacity: 0.3, amp: 2.2, over: 5, step: 7, seed: 657 }));
    // ---- arms: only the medium has them in frame --------------------------
    if (!close) {
      [-1, 1].forEach(function (s, i) {
        // The arm hangs from just INSIDE the shoulder point, and the sleeve is
        // narrow enough to sit within the torso silhouette where the two meet.
        // Wider than that, the sleeve's outline crosses the torso's outline — and
        // since every outline is on the ink layer, both stay visible and he ends up
        // wearing a cape with a seam down the chest.
        const sh = { x: cx + s * shoulderHalf * 0.70, y: shoulderY + R * 0.04 };
        const el = { x: sh.x + s * R * 0.30, y: sh.y + HU * 1.16 };
        const hd = { x: sh.x + s * R * 0.12, y: sh.y + HU * 2.22 };
        // A ROBE HAS SLEEVES. Left in the tee's grey, the upper arm read as a
        // t-shirt sleeve laid over a dressing gown, with both outlines visible
        // because they are all on the ink layer — the exact seam-down-the-chest
        // failure described above, one joint further out.
        const upperC = OUT.layer === "robe" ? "#6E6A62" : shirt;
        mass(quad(sh, el, HU * 0.21, HU * 0.17), upperC, 0.86, 4.2, -60 + i * 20, 661 + i * 17);
        mass(quad(el, hd, HU * 0.16, HU * 0.13), OUT.layer === "robe" ? upperC : skin, 0.46, 3.6, -60 + i * 20, 681 + i * 17);
        if (OUT.layer === "robe") {
          // a cuff, so the sleeve ends somewhere rather than fading into the crop
          P.inkAdd(S.stroke([
            { x: hd.x - s * HU * 0.15, y: hd.y - HU * 0.30 },
            { x: hd.x + s * HU * 0.15, y: hd.y - HU * 0.26 },
          ], { stroke: ink, width: 4.4, opacity: 0.85, amp: 2, over: 6, seed: 691 + i }));
        }
        if (OUT.sleeves === "rolled") {
          P.inkAdd(S.stroke([{ x: el.x - HU * 0.2, y: el.y - HU * 0.04 }, { x: el.x + HU * 0.2, y: el.y + HU * 0.02 }], { stroke: ink, width: 5.4, opacity: 0.9, amp: 2, over: 6, seed: 751 + i }));
        }
        if (OUT.layer === "cardigan") {
          P.colourAdd(S.hatch(quad(sh, el, HU * 0.28, HU * 0.22), { color: "#5A5F5C", opacity: 0.82, gap: 6.4, width: 10, angle: -60 + i * 20, over: 9, seed: 761 + i * 5 }));
          P.inkAdd(S.outline(quad(sh, el, HU * 0.28, HU * 0.22), { stroke: ink, width: 4.2, opacity: 0.92, amp: 2.2, over: 8, seed: 765 + i * 5 }));
        }
      });
    }

    // ---- head ---------------------------------------------------------------
    const FACE = hostFace({
      P: P, S: S, ell: ell, dot: function (q, r, sd) { dot(q.x, q.y, r, sd); },
      cx: hcx, cy: hcy, R: R, ink: ink, skin: skin, hair: hair,
      lw: close ? 1.3 : 1, seg: 20, fine: true, tilt: HEAD_TILT,
      mouthOpen: mouthOpen, closedEyes: !!o.closedEyes, glance: o.glance || 0,
    });
    const eyeY = FACE.eyeY;
    P.meta.glance = o.glance ? (o.glance < 0 ? "camera-left" : "camera-right") : "to camera";
    P.meta.glanceNote = o.glance
      ? "He is looking at something off to " + (o.glance < 0 ? "camera-left" : "camera-right") + ". Cut this against a chart or an insert on THAT side of frame; using it with the graphic on the opposite side is worse than him facing camera."
      : "He is looking down the lens. Use this when he is addressing the viewer, not when a graphic is on screen.";

    P.meta.contrast = {
      rule: "Dennis is the highest-contrast object in any frame he is in",
      why: "he is the reason anyone is watching, and a figure at the same value as the desk behind him disappears into it",
      how: "his own material hatch and a neutral ink pass on each part's turned side; the room's heaviest furniture tops out at a 0.19 ink hatch and he sits above it",
      note: "he is NOT lit to match the room. Revision 01 tinted him from the room's two sources and that is exactly what closed the gap. The room gives way to him, not the other way round.",
    };
    // NO FLOOR LINE, STATED AS DATA. These are not standing figures: there is
    // nothing to pin to a room's floorLineY, and a number here is a number a
    // compositor would believe. Placement code branches on floorLineY === false
    // and reads `fit` instead.
    P.meta.floorLineY = false;
    P.meta.fit = {
      mode: "eye-line",
      eyeLineY: Math.round(eyeY),
      eyeLineFraction: +(eyeY / h).toFixed(4),
      headHeightFraction: +((R * 1.96) / h).toFixed(4),
      note: "A close-up is placed on its EYE LINE, not on a bounding box: scale so slots.head height is the fraction of frame height the shot wants (0.42-0.56 for the close-up, 0.16-0.22 for the medium), then put eyeLineY on the frame's upper third. Both framings run off the left and right edges by design — the width is not a bound, and cropping to it re-frames the shot.",
      cropsAt: close ? "shoulders leave frame left, right and bottom" : "hands leave frame at the bottom",
    };
    // THE MOUTH REGION IS THE REGION THAT VARIES, not the aperture.
    //
    // §7 says talk frames differ only at the mouth, and the pre-flight checks it
    // by asserting every mark that moves between talk frames falls inside this
    // box. It failed on three marks — the nasolabial fold on the outboard cheek,
    // which moves with the mouth because on a face it does.
    //
    // The fix is the box, not the drawing. Suppressing the fold to satisfy the
    // rule would make him talk with a rigid cheek, and the rule does not exist to
    // forbid that motion: it exists so the renderer knows WHICH REGION varies
    // when it cuts a talk frame against the audio. A slot that understates the
    // varying region is the defect — it described the aperture while the artwork
    // varied a wider area, exactly the sort of quiet disagreement between
    // manifest and plate this pack exists to remove.
    P.slot("mouth", hcx - R * 0.4, hcy + R * 0.4, R * 0.8, R * 0.42, { role: "mouth", region: true, note: "the region that DIFFERS between talk frames — the aperture and the fold that moves with it — not the lips alone. Verified by pre-flight check C." });
    P.slot("eyes", hcx - R * 0.7, eyeY - R * 0.3, R * 1.4, R * 0.6, { role: "eyes", region: true, note: "the eye line is fit.eyeLineY; this box is the pair" });
    P.slot("head", hcx - R * 0.9, hcy - R * 1.12, R * 1.8, R * 2.1, { role: "head", region: true });
    P.slot("figure", 0, hcy - R * 1.2, w, h - (hcy - R * 1.2), { role: "figure", region: true, note: "visible extent only. There is no floorLineY on this plate and this box is NOT a scaling authority — see meta.fit" });
    return P;
  }

  // §1.2 — THE BLINK, AND WHY IT IS ITS OWN STRIP.
  //
  // A blink is about a tenth of a second. The idle boil frame is 250ms at 4fps.
  // Those are different clocks and they must not share a strip: three open
  // frames then three closed makes a 750ms blink, which does not read as a blink
  // — it reads as falling asleep. One extra frame inside the looping idle strip
  // is worse, because a non-loop frame in a looping strip blinks at i % 4,
  // roughly once a second, forever.
  //
  // So: a separate overlay strip, on the anchor the contract already provides —
  // `eyes` is region: true on every hostHead plate, which is a documented box for
  // exactly this. The compositing question was answered before it was asked.
  //
  // THE FRAME COUNT IS NOT THE BLINK'S OWN RATE. It is three because the idle
  // strip is three: the overlay has to be drawn at the SAME boil index as the
  // frame it covers, or the lid meets a socket that has wobbled somewhere else.
  // So blink _fNN pairs with idle _fNN by index, and the renderer chooses WHEN
  // to show one — a tenth of a second, every three to four seconds — on its own
  // schedule. Frame count is registration; the schedule is the renderer's.
  //
  // On the previous kit's `dennis-both-hands-blink_f01..f03`: worth reading for
  // the lid shape and the timing, but its structure does not transfer. It had no
  // three-frame boil to stay registered against.
  function hostBlink(o) {
    const P = hostHead(Object.assign({}, o, { closedEyes: true }));
    // THE CLIP IS MEASURED, NOT AUTHORED.
    //
    // It was the eyes slot plus a guessed pad, and the pre-flight caught a mark
    // on the close-up variants that differed and reached past it — which would
    // have clipped part of a stroke the overlay needed to replace, leaving the
    // idle frame's own version of it showing through the other half.
    //
    // So the box comes from the difference itself: draw the open-eyed head the
    // overlay will sit on, take every mark that is not in both, and clip to the
    // union of their extents. That cannot be short by construction, and it stays
    // correct if the lid shape, the glasses or the head size ever change.
    //
    // Padding costs nothing — a wider box only includes more marks that already
    // agree — but being short costs a visible seam, so the error is taken in the
    // direction that is free.
    const openP = hostHead(Object.assign({}, o, { closedEyes: false }));
    const marksOf = (p) => (p.toSVG().match(/<path\b[^>]*\/>/g) || []);
    const have = new Map();
    marksOf(openP).forEach((m) => have.set(m, (have.get(m) || 0) + 1));
    const differing = [];
    marksOf(P).forEach((m) => { const n = have.get(m) || 0; if (n > 0) have.set(m, n - 1); else differing.push(m); });
    have.forEach((n, m) => { for (let i = 0; i < n; i++) differing.push(m); });
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    differing.forEach(function (m) {
      const nums = (m.match(/d="([^"]+)"/) || [, ""])[1].match(/-?\d+(\.\d+)?/g);
      if (!nums) return;
      for (let i = 0; i + 1 < nums.length; i += 2) {
        const x = +nums[i], y = +nums[i + 1];
        if (x < x0) x0 = x; if (x > x1) x1 = x;
        if (y < y0) y0 = y; if (y > y1) y1 = y;
      }
    });
    const e = P.slots.eyes;
    if (!isFinite(x0)) { x0 = e.x; y0 = e.y; x1 = e.x + e.w; y1 = e.y + e.h; }
    // Union with the declared anchor, so the overlay always covers the box the
    // contract names even if a future lid shape sits entirely inside it.
    x0 = Math.min(x0, e.x); y0 = Math.min(y0, e.y);
    x1 = Math.max(x1, e.x + e.w); y1 = Math.max(y1, e.y + e.h);
    const pad = Math.round(e.h * 0.35);
    P.clipTo(x0 - pad, y0 - pad, (x1 - x0) + pad * 2, (y1 - y0) + pad * 2);
    P.meta.overlay = true;
    P.meta.overlayAnchor = "eyes";
    P.meta.clipDerivedFrom = "the measured difference against the open-eyed head, unioned with the eyes slot and padded. Not a hand-set box.";
    P.meta.pairing = "index-matched: blink _fNN composites over idle _fNN, at the same boil. Not interchangeable — a blink frame over the wrong idle frame puts the lids on a socket that has moved.";
    P.meta.schedule = "renderer-owned: ~100ms, every 3-4s, idle strips only. The strip does not encode a rate.";
    // The talk contract, restated where it can be violated: this overlay never
    // goes over a talk frame. Talk frames differ only at the mouth, and an eye
    // closing between two talk frames is a difference that is not the mouth.
    P.meta.notOnTalk = true;
    return P;
  }

  // ---------------- the room ----------------
  // Every plate declares floorLineY and the figure stands on it.
  //
  // He works at three in the morning, and that is the whole lighting design: one
  // warm desk lamp and the cold glow of a monitor. Every mass in the room is
  // toned by those two sources and by its DEPTH — near things get darker line and
  // more contrast, far things flatten toward the wall. That is atmospheric
  // perspective done with tone instead of with more objects, and it is why the
  // room can be much richer than the plates without touching the palette rules:
  // in here colour is light and material (warm lamp, cold screen, dying plant),
  // never meaning. Nothing red goes anywhere it could be read as a loss.
  //
  // Draw order is now per-prop rather than colour-then-line for the whole plate,
  // so props can occlude each other: a mug half behind a monitor needs the
  // monitor's OWN line covered, and a global ink layer paints every line over
  // every fill. Each mass lays an opaque mask first, then its tone, then its
  // line — so whatever is drawn later is genuinely in front.
  // REVISION 02 — the tonal scheme.
  //
  // The direction: the ground stays the ground (#E6DDC9 / the pad is the surface
  // everything sits on, and nothing goes over the top of it globally — if the
  // paper colour is not visible in frame, the treatment is wrong). Light is
  // VALUE FALLOFF, not a colour layer: a lamp does not tint a room, it makes near
  // things lighter and far things darker, following the shapes of objects rather
  // than sitting behind them in a rectangle. The ink line is always the darkest
  // thing in frame, with contact shadows the one exception — small, tight, and
  // allowed to go darker. Hatch selectively: texture is only depth when some
  // things have it and some do not.
  //
  // Revision 01 mixed every mass toward warm and cold, hazed the far ones toward
  // an olive ambient, and laid a flat night wash under the whole frame. The
  // washes behind the calendar and the monitor read as coloured paper taped to
  // the wall, and the whole treatment closed the value gap that makes a drawing
  // read. All four of those constants are gone. SHADOW is the only dark left, and
  // it is only ever used for a contact pool.
  const SHADOW = "#1C222A";
  // REAL DARKS, and they are OBJECTS — not a filter, not a wash.
  //
  // Revision 02 ran 80–232 with a mean of 208: almost the whole frame sat in the
  // top quarter of the range, which is why it read as a light drawing with some
  // texture on it rather than a room. The fix is not more hatch anywhere; it is
  // three or four genuinely dark THINGS: the shadow under the desk, the back of
  // the monitor, the inside of the bin, the gap behind the printer. Each is a
  // surface that really is dark, drawn at a value that shows it.
  const DEEP = "#2B323C";
  const hex3 = (c) => [parseInt(c.slice(1, 3), 16), parseInt(c.slice(3, 5), 16), parseInt(c.slice(5, 7), 16)];
  const mixHex = function (a, b, t) {
    const A = hex3(a), B = hex3(b);
    return "#" + A.map((v, i) => Math.max(0, Math.min(255, Math.round(v + (B[i] - v) * t))).toString(16).padStart(2, "0")).join("");
  };
  const centroid = function (poly) {
    let x = 0, y = 0;
    poly.forEach((q) => { x += q.x; y += q.y; });
    return { x: x / poly.length, y: y / poly.length };
  };
  // Sutherland-Hodgman against one half-plane: the lit half of a shape and the
  // shaded half are the same polygon cut by a line through its middle, square to
  // the direction the light comes from.
  const clipHalf = function (poly, nx, ny, c) {
    const out = [], side = (q) => nx * q.x + ny * q.y - c;
    for (let i = 0; i < poly.length; i++) {
      const a = poly[i], b = poly[(i + 1) % poly.length], sa = side(a), sb = side(b);
      if (sa <= 0) out.push(a);
      if ((sa < 0 && sb > 0) || (sa > 0 && sb < 0)) {
        const t = sa / (sa - sb);
        out.push({ x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t });
      }
    }
    return out.length > 2 ? out : null;
  };

  function roomKit(P, p, k, sc) {
    const S = inkScale(k || 1);
    // §4 — the cast-and-contact pass is hand-2 only, like every other change in
    // these two packs. Under hand-1 a room emits exactly what it always did.
    const H2 = !!(H.profile && H.profile() === "hand-2");
    const q = function (n) { return n * (k || 1); };
    const ink = p.structure, paper = p.ground, wood = p.ground2;
    // set colours, not data roles
    const foliage = "#6F7F55", terracotta = "#B5745A", screen = "#2E3742";
    const W = sc ? sc.w : 1920, HH = sc ? sc.h : 1080, FY = sc ? sc.floorY : HH * 0.8;
    // Two sources. Until a branch sets them the room is lit softly from the
    // front-left, so a new angle is never unlit by omission.
    let lampL = { x: W * 0.2, y: FY - HH * 0.2, r: W * 0.42 };
    let screenL = { x: W * 0.42, y: FY - HH * 0.26, r: W * 0.34 };
    const clamp01 = (v) => Math.max(0, Math.min(1, v));
    // Inverse-square-ish, normalised: full at the bulb, a quarter at its radius.
    const fall = function (x, y, L) {
      const d = Math.hypot(x - L.x, y - L.y) / L.r;
      return 1 / (1 + d * d * 3);
    };
    // DEPTH, and why line weight did not read for three revisions.
    //
    // The multiplier was widened twice and neither time made a visible
    // difference, because the INPUT barely varied: depth came from height in
    // frame, and almost every prop in this set sits in the same y-band around the
    // desk and the floor line. A linear map over that band returns 0.46–0.8 for
    // nearly everything, so a 3.5x multiplier range was being fed a 1.4x spread.
    // Widening the multiplier again would have changed nothing.
    //
    // So depth is now a steep curve over the WHOLE canvas, and the props that
    // belong to a different plane say so explicitly (opt.depth): wall-mounted
    // things are far, the desk and its furniture are mid, the cropped foreground
    // object is at the camera. That is what produces a real spread.
    const depthAt = function (y) {
      const t = clamp01((y - HH * 0.04) / (HH * 0.96));
      return Math.pow(t, 1.7);
    };
    const PLANE = { wall: 0.04, back: 0.3, desk: 0.55, floor: 0.78, near: 1 };
    // §1.3 — WHAT THE ROOM HAS THAT COULD MOVE, recorded as it is drawn.
    //
    // The ambient prop is CHOSEN from what the plate already put on screen rather
    // than authored angle by angle: every branch that draws a mug or a monitor
    // registers it here, and ambient() picks one at the end. Eleven angles plus
    // wallOfCalls needed one call each, not eleven placements to keep in step
    // with furniture that moves whenever the desk height rule does.
    const AMB = { mugs: [], screens: [], spills: [], cards: [] };
    const emit = (s) => P.inkAdd(s);
    // opaque mask, so a near prop can cover a far prop's line as well as its tone
    const solid = function (poly, colour, opacity, seed) {
      const pts = H.wobble(poly.concat([poly[0]]), { amp: 2.2 * (k || 1), over: 0, seed: seed || 1, step: 22 * (k || 1) });
      emit(`<path d="${H.toPath(pts)}Z" fill="${colour}" fill-opacity="${opacity == null ? 1 : opacity}"/>`);
    };

    // Value falloff: 1 next to a source, 0 far from any. It REMOVES hatch near a
    // lamp — it never adds colour.
    const lumAt = function (x, y) {
      return clamp01(Math.max(fall(x, y, lampL), fall(x, y, screenL) * 0.85));
    };

    // A mass is its own material colour, hatched. How much hatch it carries IS
    // the lighting. opt.flat leaves a surface as bare ground with only its line:
    // texture is only depth when some things have it and some do not, and
    // hatching everything at one density cancels itself out.
    const mass = function (poly, colour, opacity, seed, hatchAngle, lw, opt) {
      opt = opt || {};
      const c = centroid(poly);
      const d = opt.depth == null ? depthAt(c.y) : opt.depth;
      const lum = lumAt(c.x, c.y);
      if (opt.mask !== false) solid(poly, paper, 1, seed + 91);
      const ang = hatchAngle == null ? -74 : hatchAngle;
      // Everything a mass draws goes on the ORDERED layer, in this sequence:
      // mask, hatch, turned-away face, line. The mask is what lets a near prop
      // occlude a far prop's line as well as its tone — and it has to sit in the
      // same layer as the hatch it precedes. (First revert pass put the hatch on
      // the colour layer while the mask stayed on the ordered one, so every mass
      // painted its own hatch and then covered it. The room came out as pure
      // outline and I mistook that for the hatch being too weak.)
      if (!opt.flat) {
        const base = opacity == null ? 0.6 : opacity;
        // Lit → lighter, unlit → heavier, around board 01's strength. The FIRST
        // revert pass multiplied base by (1 - lum*0.42), which only ever removed
        // weight: every surface came out fainter than board 01 and the room had
        // no mid-tones left at all. Falloff has to cut BOTH ways around the
        // material's own value, or "light" just means "washed out".
        P.inkAdd(S.hatch(poly, { color: colour, opacity: clamp01(base * (1.18 - lum * 0.5)), gap: 7.5, width: 12, angle: ang, over: 14, seed: seed }));
        // The face turned away from the key, in the SAME colour: a second pass of
        // the material reads as a plane turning away, where a grey would read as
        // dirt. This is the falloff following the object's own shape.
        const key = fall(c.x, c.y, lampL) >= fall(c.x, c.y, screenL) ? lampL : screenL;
        const vx = key.x - c.x, vy = key.y - c.y, vl = Math.hypot(vx, vy) || 1;
        const away = clipHalf(poly, vx / vl, vy / vl, (vx / vl) * c.x + (vy / vl) * c.y);
        if (away) P.inkAdd(S.hatch(away, { color: colour, opacity: 0.2 + 0.2 * (1 - lum), gap: 9.5, width: 13, angle: ang - 7, over: 10, seed: seed + 47 }));
      }
      // opt.weight: a NEUTRAL weight pass, hatched in ink at low opacity. On the
      // legal pad the ground is #EFE4A8 and ground2 is #E3D68F — a 7% step, so
      // hatching a surface in the wood colour cannot make a mid-tone however hard
      // it is pushed. Weight has to come from the ink itself, and a 0.16 hatch of
      // ink is far lighter than the 0.92 solid line, so the line stays the darkest
      // thing in frame. This is the "hatch where a surface needs weight" of board
      // 01: it goes on the desk, the chair, the printer, the bin — never on the
      // wall, the floor, the paper, or anything the eye should pass over.
      if (opt.weight) {
        P.inkAdd(S.hatch(poly, { color: ink, opacity: (0.1 + 0.09 * (1 - lum)) * (opt.weight === true ? 1 : opt.weight), gap: 9, width: 13, angle: ang + 6, over: 10, seed: seed + 61 }));
      }
      // §4 — CAST AND CONTACT. The room had a light MODEL (two declared sources,
      // falloff, a turned-away face per mass) and no light EVIDENCE: nothing cast
      // a shadow, nothing darkened where it met the thing it stood on, and floor
      // and wall sat at one value separated by a line. After §3.1 Dennis is
      // modelled and the room was not, so he composited as a cut-out on a
      // backdrop — two levels of finish in one frame.
      //
      // Two marks per mass, both derived from the key source this mass is already
      // lit by, so the direction cannot disagree with the shading above:
      //   the cast    a low quad on the plane below, thrown AWAY from the key and
      //               tapering — it is a shadow, so it is a wash and not a line.
      //   the contact the kit's own contact(), tight against the base. This is
      //               the one the review missed most: a desk leg meeting a floor
      //               with nothing at the join reads as a sticker.
      //
      // Restraint, per the two constraints: nothing whose base is above 36% of frame height, so
      // the title box stays on flat wall and the chapter openers keep a clean
      // ground for type; and nothing on a mass narrower than a few units, so
      // wall-of-calls' eight data slots do not acquire a shadow each.
      if (H2 && opt.cast !== false && !opt.flat) {
        const xs = poly.map(function (p) { return p.x; }), ys = poly.map(function (p) { return p.y; });
        const bx0 = Math.min.apply(null, xs), bx1 = Math.max.apply(null, xs);
        const by = Math.max.apply(null, ys), wdt = bx1 - bx0;
        // A DESK IS NOT A PROP. The first pass ran this on every mass, so the
        // desk — 1075 units wide — got a contact ellipse 473 units across and the
        // room grew black lagoons. Contact belongs to things that SIT on a plane
        // at prop scale; the desk's own join is what underDesk() is for, and it
        // is already drawn. So: prop-scale masses only, and the contact is capped
        // in absolute units as well as in proportion.
        if (by > P.h * 0.36 && wdt > q(26) && wdt < P.w * 0.3) {
          const kk = fall(c.x, c.y, lampL) >= fall(c.x, c.y, screenL) ? lampL : screenL;
          const dir = c.x - kk.x >= 0 ? 1 : -1;
          // §4b — OFFSET AND SOFTNESS FOLLOW STAND-OFF. The first pass gave every
          // object the same offset and the same edge, which at render scale is the
          // signature of a drop shadow applied per object rather than one light in
          // a room: a clock standing well off the wall and a sheet pinned nearly
          // flush had comparable shadows. Stand-off is already declared — it is
          // opt.depth, the plane the object sits on — so the shadow reads it.
          // A flush object (PLANE.wall) throws a tight, near shadow; a near object
          // throws a long, soft one.
          const so = Math.max(0, Math.min(1, ((opt.depth == null ? PLANE.back : opt.depth) - PLANE.wall) / (1 - PLANE.wall)));
          const off = Math.max(q(3), wdt * (0.05 + 0.16 * so));
          const dep = Math.max(q(2), wdt * (0.025 + 0.075 * so));
          const dens = 0.09 + 0.07 * (1 - lum);
          const throwQuad = function (m, o2) {
            return [
              { x: bx0 + dir * off * 0.35 * m, y: by - dep * 0.2 * m },
              { x: bx1 + dir * off * 0.55 * m, y: by - dep * 0.2 * m },
              { x: bx1 + dir * off * m, y: by + dep * m },
              { x: bx0 + dir * off * 0.7 * m, y: by + dep * m },
            ];
          };
          // core, then a wider halo whose spread is the softness. A flush object
          // gets almost no halo; a near one gets a penumbra you can see.
          solid(throwQuad(1, dens), ink, dens, seed + 77);
          if (so > 0.25) solid(throwQuad(1.35 + so * 0.5), ink, dens * 0.42 * so, seed + 78);
          contact(c.x, by, Math.min(wdt * 0.44, q(70)), seed + 79);
        }
      }
      // The line: ink, always, at full strength — the darkest thing in frame.
      // Only its WEIGHT reads depth, and the range has to be wide enough to SEE:
      // 0.72–1.22x across the frame (revisions 01 and 02) is a 1.7x spread that
      // reads as uniform. 0.5–1.75x is a 3.5x spread, which reads as distance.
      P.inkAdd(S.outline(poly, { stroke: ink, width: (lw == null ? 4 : lw) * (0.34 + 1.9 * d), opacity: 0.92, amp: 3.2, over: 12, seed: seed + 1 }));
    };
    const rect = function (x, y, w, h) { return H.polyRect(x, y, w, h); };
    const thin = function (pts, op, lw, seed) {
      const d = depthAt(centroid(pts).y);
      P.inkAdd(S.stroke(pts, { stroke: ink, width: (lw == null ? 2.4 : lw) * (0.4 + 1.7 * d), opacity: op == null ? 0.45 : op, amp: 1.8, over: 6, seed: seed }));
    };
    // Where an object meets a surface: SMALL and DARK — the size of the object's
    // footprint, not a halo around it. The one thing allowed to go darker than
    // the line.
    const contact = function (cx, baseY, halfW, seed, spread) {
      const sp = spread == null ? 1 : spread;
      P.inkAdd(S.hatch(ellipse(cx, baseY, halfW * 0.92 * sp, Math.max(q(3), halfW * 0.13), 12, 0.1, seed), { color: SHADOW, opacity: 0.3, gap: 4.5, width: 8, angle: -6, over: 5, seed: seed + 1 }));
      P.inkAdd(S.hatch(ellipse(cx, baseY, halfW * 0.5 * sp, Math.max(q(2), halfW * 0.075), 10, 0.1, seed + 2), { color: SHADOW, opacity: 0.44, gap: 3.4, width: 6, angle: -6, over: 4, seed: seed + 3 }));
    };

    // A dark that reads as SHADOW rather than as a slab.
    //
    // Three things separate the two, and the first version had none of them: a
    // shadow is DENSEST where it meets what casts it and lightens away from it;
    // its edge is ragged, not a drawn outline; and the ground shows through it,
    // because a shadow is the surface in shade rather than a new object on top.
    // Drawn as a uniform fill with an outline round it, the under-desk mass and
    // the foreground crop became the biggest darks in frame and pulled the eye
    // off the host — which is the one thing the room must not do.
    //
    // `from` says which edge the shadow is cast from ("top" for a recess under a
    // desk, "bottom" for an object standing on the floor). Bands run from that
    // edge outward, each lighter than the last, and none of them fills.
    const deep = function (poly, seed, op, lw, from) {
      const base = op == null ? 0.72 : op;
      let y0 = Infinity, y1 = -Infinity, x0 = Infinity, x1 = -Infinity;
      poly.forEach(function (p2) { y0 = Math.min(y0, p2.y); y1 = Math.max(y1, p2.y); x0 = Math.min(x0, p2.x); x1 = Math.max(x1, p2.x); });
      const H2 = y1 - y0, bands = 5, top = from !== "bottom";
      for (let i = 0; i < bands; i++) {
        const t = i / bands;
        // inset the far end so the shadow does not reach the polygon's edge as a
        // straight line — the fade IS the edge
        const a0 = top ? y0 + H2 * t : y1 - H2 * (t + 1 / bands);
        const inset = (x1 - x0) * 0.012 * i;
        const band = H.polyRect(x0 + inset, a0, (x1 - x0) - inset * 2, H2 / bands + 2);
        const fade = Math.pow(1 - t, 1.5);
        P.inkAdd(S.hatch(band, { color: DEEP, opacity: base * (0.34 + 0.66 * fade), gap: 5.4 + i * 1.3, width: 8, angle: -74, over: 9, seed: seed + i * 7 }));
        if (i < 2) P.inkAdd(S.hatch(band, { color: DEEP, opacity: base * 0.3 * fade, gap: 6.5 + i, width: 9, angle: -12, over: 7, seed: seed + 40 + i }));
      }
      // A ragged terminating edge instead of an outline: a few short strokes that
      // break up where the shadow stops. Never a closed line — an outline is what
      // made this read as an object.
      const eY = top ? y1 : y0;
      for (let i = 0; i < 7; i++) {
        const sx = x0 + (x1 - x0) * (0.06 + i * 0.135);
        const dy = (top ? -1 : 1) * H2 * (0.03 + (i % 3) * 0.035);
        P.inkAdd(S.stroke([{ x: sx, y: eY + dy }, { x: sx + (x1 - x0) * 0.09, y: eY + dy * 0.4 }], { stroke: DEEP, width: 6, opacity: base * 0.42, amp: 2.6, over: 5, seed: seed + 60 + i }));
      }
      if (lw) P.inkAdd(S.stroke([{ x: x0, y: top ? y0 : y1 }, { x: x1, y: (top ? y0 : y1) - 2 }], { stroke: ink, width: lw, opacity: 0.85, amp: 2.4, over: 8, seed: seed + 3 }));
    };

    return {
      mass: mass, rect: rect, thin: thin, contact: contact, deep: deep,
      // The recess under a desk is the darkest thing in most of these frames, and
      // it costs one polygon. Without it the desk is a plank floating on legs.
      // The recess under a desk: the desk casts it, so it is densest right under
      // the top and fades toward the floor, with the ground showing through.
      underDesk: function (x, y, w2, h2, seed) {
        deep([
          { x: x + w2 * 0.03, y: y }, { x: x + w2 * 0.97, y: y },
          { x: x + w2 * 0.93, y: y + h2 }, { x: x + w2 * 0.07, y: y + h2 },
        ], seed, 0.66, 0, "top");
        // §4b — IT WAS READING AS A HOLE, not a shadow: hard on all four sides
        // and the same density to the floor. A recess is darkest immediately
        // under the top and lets the ground back through as it comes forward, and
        // it does not end on a line — so the density comes down and the last of
        // it spills PAST the opening onto the floor, wider than the recess.
        if (H2) {
          deep([
            { x: x + w2 * 0.09, y: y + h2 * 0.45 }, { x: x + w2 * 0.91, y: y + h2 * 0.45 },
            { x: x + w2 * 1.02, y: y + h2 + q(22) }, { x: x - w2 * 0.02, y: y + h2 + q(18) },
          ], seed + 30, 0.2, 0, "top");
        }
      },
      // ONE object clearly in the foreground, cropped by the frame edge. Every
      // angle in revisions 01 and 02 laid its props along a single horizontal
      // line, so nothing was in front of anything: the room had width but no
      // depth. A cropped near object fixes that in a single element, because the
      // crop itself is the depth cue — the frame edge can only cut what is close.
      foreground: function (kind, side, floorY2, seed) {
        const s = side < 0 ? -1 : 1;
        const bx = s < 0 ? -W * 0.06 : W * 0.82;
        if (kind === "chair") {
          // a chair back, close, cut by the edge. It is an OBJECT, so it keeps a
          // real outline and a mass — only its shading uses the shadow grade.
          const top = floorY2 - HH * 0.46, bw = W * 0.3, bh = HH * 0.26;
          mass(rect(bx, top, bw, bh), wood, 0.62, seed, -76, 6.4, { weight: 1, depth: PLANE.near });
          deep(rect(bx + bw * 0.06, top + bh * 0.42, bw * 0.88, bh * 0.55), seed + 20, 0.5, 0, "bottom");
          P.inkAdd(S.outline(rect(bx + bw * 0.08, top + bh * 0.14, bw * 0.84, bh * 0.7), { stroke: ink, width: 4.4, opacity: 0.5, amp: 2.6, over: 10, seed: seed + 3 }));
          mass(rect(bx + bw * 0.42, top + bh, bw * 0.12, HH * 0.2), wood, 0.5, seed + 8, -76, 6, { weight: 1, depth: PLANE.near });
        } else if (kind === "shoulder") {
          /* §4.3 — THE BACK OF HIM, CROPPED BY THE FRAME EDGE.

             The over-the-shoulder shot's foreground is the shot. It lives in this
             function because this function's whole job is "one object clearly in
             front of everything else, cut by the edge" — the crop IS the depth
             cue, and that is as true of a shoulder as of a mug.

             HE GETS THE HEAVIEST LINE AND THE HEAVIEST TONE, which no other
             foreground kind does. The comment above is right that a near prop
             needs only the line: a mug with both competes with the host. This
             near object IS the host, and room/ doctrine is that he is the
             highest-contrast thing in any frame he is in — so here the two rules
             point the same way for once.

             It is a SILHOUETTE, not a portrait: no face, no features, no eyeline.
             We are behind him. Anything more would be a second Dennis, drawn by a
             different author from the host family, disagreeing with the real one
             about who he is — the exact defect hostFace() exists to prevent. */
          const shW = W * 0.42, shTop = floorY2 - HH * 0.30;
          const bx2 = s < 0 ? -W * 0.14 : W * 0.72;
          // the shoulder and upper arm, rising out of the bottom edge
          const shoulder = [
            { x: bx2, y: floorY2 + HH * 0.2 },
            { x: bx2 + shW * 0.06, y: shTop + HH * 0.07 },
            { x: bx2 + shW * 0.34, y: shTop },
            { x: bx2 + shW * 0.72, y: shTop + HH * 0.035 },
            { x: bx2 + shW, y: shTop + HH * 0.16 },
            { x: bx2 + shW * 1.04, y: floorY2 + HH * 0.2 },
          ];
          mass(shoulder, ink, 0.72, seed, -70, 7.2, { weight: 1, depth: PLANE.near });
          // the head, seen from behind: a plain dome sitting on the shoulder line,
          // with the hair mass a shade heavier at the crown
          const hr = HH * 0.135, hcx2 = bx2 + shW * (s < 0 ? 0.62 : 0.38), hcy2 = shTop - hr * 0.72;
          const dome = [];
          for (let i = 0; i <= 20; i++) {
            const a = Math.PI * (1 + i / 20);
            dome.push({ x: hcx2 + Math.cos(a) * hr * 1.02, y: hcy2 + Math.sin(a) * hr * 1.16 });
          }
          dome.push({ x: hcx2 + hr * 0.92, y: shTop + HH * 0.02 });
          dome.push({ x: hcx2 - hr * 0.92, y: shTop + HH * 0.02 });
          mass(dome, ink, 0.74, seed + 11, -68, 7.2, { weight: 1, depth: PLANE.near });
          // and the one edge that says which way he is facing: the ear side, read
          // as a notch in the silhouette rather than as a drawn ear
          P.inkAdd(S.line(hcx2 + s * hr * 0.86, hcy2 + hr * 0.25, hcx2 + s * hr * 0.98, hcy2 + hr * 0.72,
            { stroke: ink, width: 5.2, opacity: 0.55, amp: 2, over: 6, seed: seed + 17 }));
        } else if (kind === "stack") {
          const bw = W * 0.26, top = floorY2 - HH * 0.2;
          for (let i = 0; i < 5; i++) {
            mass(rect(bx + (i % 2 ? q(10) : 0), top + i * HH * 0.04, bw, HH * 0.042), paper, 0.86, seed + i * 3, -3, 5.2, { flat: true, depth: PLANE.near });
          }
          contact(bx + bw * 0.5, floorY2 + q(4), bw * 0.5, seed + 40, 1.2);
        } else {
          // A mug, very close. It has to be BIG and clearly cut by the frame edge
          // — a small object near the bottom corner just reads as another prop on
          // the floor, which is what the first attempt did. At this size the crop
          // itself is the depth cue.
          const r = HH * 0.19, cxx = bx + W * 0.03, byy = floorY2 - HH * 0.01;
          const body = [{ x: cxx - r, y: byy - r * 1.5 }, { x: cxx + r, y: byy - r * 1.5 }, { x: cxx + r * 0.85, y: byy }, { x: cxx - r * 0.85, y: byy }];
          // the mug is an object at the camera: its own material, heaviest line in
          // frame, and the shade on it graded from the bottom rather than filled
          // Weight kept modest on purpose: this is a depth cue, not a subject. A
          // near object gets the heaviest LINE in frame, which is enough to place
          // it — it does not also need the heaviest tone, and when it had both it
          // competed with the host.
          mass(body, wood, 0.46, seed, -74, 6.6, { weight: 0.5, depth: PLANE.near });
          deep([{ x: cxx - r * 0.94, y: byy - r * 1.05 }, { x: cxx + r * 0.94, y: byy - r * 1.05 }, { x: cxx + r * 0.85, y: byy }, { x: cxx - r * 0.85, y: byy }], seed + 20, 0.3, 0, "bottom");
          P.inkAdd(S.outline(ellipse(cxx, byy - r * 1.5, r, r * 0.3, 14, 0.05, seed + 2), { stroke: ink, width: 5.4, opacity: 0.9, amp: 2, over: 7, seed: seed + 3 }));
          P.inkAdd(S.stroke([{ x: cxx + r * 0.95, y: byy - r * 1.15 }, { x: cxx + r * 1.6, y: byy - r * 0.85 }, { x: cxx + r * 0.9, y: byy - r * 0.35 }], { stroke: ink, width: 5.6, opacity: 0.92, amp: 2.2, over: 6, seed: seed + 5 }));
        }
      },
      lights: function (lamp, scr) {
        if (lamp) lampL = { x: lamp.x, y: lamp.y, r: lamp.r || W * 0.4 };
        if (scr) screenL = { x: scr.x, y: scr.y, r: scr.r || W * 0.34 };
        P.meta.light = {
          key: "a desk lamp and a monitor at three in the morning, expressed as VALUE FALLOFF only — surfaces near a source carry less hatch and show more bare ground, surfaces away from one carry more. No tint and no wash: the ground colour is visible everywhere in frame.",
          lamp: { x: Math.round(lampL.x), y: Math.round(lampL.y), r: Math.round(lampL.r) },
          monitor: { x: Math.round(screenL.x), y: Math.round(screenL.y), r: Math.round(screenL.r) },
          line: "the ink line is the darkest thing in frame; only contact shadows go darker",
          host: "a host cut-out composited here must be the highest-contrast object in the frame — he is the reason anyone is watching. Do not add tone to the room that closes that gap.",
        };
      },
      // glow() is deliberately absent. It drew a soft radial pool of warm or cold
      // BEHIND whatever sat near a source — which is a rectangle of coloured paper
      // taped to the wall, not light. A lamp shows up in this room by taking hatch
      // OFF nearby surfaces (see lumAt), never by adding a layer over the ground.
      // Blinds, mostly closed. Dark enough to say the middle of the night, and
      // nothing like the darkest thing in frame: a solid black rectangle pulls the
      // eye off the host every time, which is exactly what the last one did. It is
      // a stack of slats in the wood colour, and the night shows only in a few of
      // the gaps between them.
      windowNight: function (x, y, w, hh, seed) {
        for (let i = 0; i < 15; i++) {
          const sy = y + hh * (0.03 + i * 0.066);
          P.inkAdd(S.hatch(rect(x + q(4), sy, w - q(8), hh * 0.04), { color: wood, opacity: 0.44, gap: 5, width: 9, angle: -4, over: 6, seed: seed + i * 3 }));
          thin([{ x: x + q(4), y: sy }, { x: x + w - q(4), y: sy - q(2) }], 0.3, 2.2, seed + 40 + i);
        }
        [2, 5, 9, 12].forEach(function (i, n) {
          const sy = y + hh * (0.03 + i * 0.066) + hh * 0.042;
          P.inkAdd(S.hatch(rect(x + q(6), sy, w - q(12), hh * 0.02), { color: SHADOW, opacity: 0.28, gap: 3.4, width: 6, angle: -4, over: 4, seed: seed + 80 + n }));
        });
        mass(rect(x - q(12), y - q(12), w + q(24), q(16)), wood, 0.5, seed + 40, -4, 3.4, { depth: 0.3 });
        mass(rect(x - q(12), y + hh - q(4), w + q(24), q(20)), wood, 0.56, seed + 44, -4, 3.6, { depth: 0.32 });
        [-1, 1].forEach(function (s, i) {
          mass(rect(s < 0 ? x - q(12) : x + w - q(4), y - q(4), q(16), hh + q(8)), wood, 0.44, seed + 50 + i * 4, -76, 3.2, { depth: 0.3 });
        });
      },
      // wear: a desk that has had a mug on it for nine years
      ringStain: function (x, y, r, seed) {
        P.inkAdd(S.outline(ellipse(x, y, r, r * 0.34, 16, 0.08, seed), { stroke: ink, width: 3, opacity: 0.24, amp: 2, over: 6, seed: seed + 1 }));
        P.inkAdd(S.hatch(ellipse(x, y, r * 0.9, r * 0.3, 14, 0.1, seed + 2), { color: wood, opacity: 0.16, gap: 6, width: 9, angle: -8, over: 6, seed: seed + 3 }));
      },
      // cables behind a monitor are never one cable
      cableMess: function (x, y, w, hh, seed) {
        for (let i = 0; i < 4; i++) {
          const x1 = x + w * (0.1 + i * 0.2), x2 = x + w * (0.3 + ((i * 7) % 5) * 0.14);
          P.inkAdd(S.stroke([
            { x: x1, y: y }, { x: x1 - w * 0.06, y: y + hh * 0.42 },
            { x: x2, y: y + hh * 0.72 }, { x: x2 + w * 0.05, y: y + hh },
          ], { stroke: ink, width: 3.2, opacity: 0.4, amp: 3.4, over: 7, seed: seed + i * 3 }));
        }
      },
      crumples: function (x, baseY, s, n, seed) {
        for (let i = 0; i < n; i++) {
          const cx2 = x + ((i % 3) - 1) * s * 0.7, cy2 = baseY - Math.floor(i / 3) * s * 0.5;
          // paper IS the ground colour, so a crumple reads as line, not as tone
          mass(ellipse(cx2, cy2, s * 0.4, s * 0.34, 9, 0.22, seed + i * 4), paper, 0.8, seed + i * 4, -3, 2.6, { flat: true });
          thin([{ x: cx2 - s * 0.2, y: cy2 + s * 0.06 }, { x: cx2 + s * 0.1, y: cy2 - s * 0.1 }, { x: cx2 + s * 0.26, y: cy2 + s * 0.1 }], 0.4, 2, seed + i * 4 + 2);
        }
      },
      // A doorway is a lit OPENING, not an orange panel. The hallway beyond is
      // brighter than anything in the room, but it is still a room seen through a
      // hole: it has its own floor, its own far wall, and it falls off upward
      // away from the hall light. Drawn flat (the first pass) it read as a slab
      // of colour pasted on the wall.
      // A lit doorway is the one place where BARE GROUND is the brightest thing
      // in frame — so it is drawn by leaving the paper alone and hatching only
      // the top of the opening, where the hall light does not reach. Revision 01
      // filled it with warm and it read as an orange panel taped to the wall.
      openDoor: function (x, y, w2, floorY2, seed) {
        const hh2 = floorY2 - y;
        solid(rect(x, y, w2, hh2), paper, 1, seed);
        // the hall's far wall: hatched, so the opening has depth in it. The hall
        // FLOOR (below the skirting) is left bare — that bare paper is the light.
        P.inkAdd(S.hatch(rect(x, y, w2, hh2 * 0.62), { color: wood, opacity: 0.34, gap: 9, width: 14, angle: -76, over: 12, seed: seed + 6 }));
        P.inkAdd(S.hatch(rect(x, y, w2, hh2 * 0.3), { color: wood, opacity: 0.26, gap: 10, width: 15, angle: -76, over: 12, seed: seed + 8 }));
        P.inkAdd(S.hatch(rect(x, y, w2, hh2 * 0.12), { color: wood, opacity: 0.22, gap: 11, width: 16, angle: -76, over: 12, seed: seed + 10 }));
        // hall skirting and the far wall meeting the floor: depth through the hole
        thin([{ x: x + q(6), y: y + hh2 * 0.62 }, { x: x + w2 - q(6), y: y + hh2 * 0.6 }], 0.4, 3.4, seed + 12);
        thin([{ x: x + q(6), y: y + hh2 * 0.66 }, { x: x + w2 - q(6), y: y + hh2 * 0.64 }], 0.24, 2.4, seed + 14);
        // the jamb: near, so it is the darkest line in the frame
        P.inkAdd(S.outline(rect(x, y, w2, hh2), { stroke: ink, width: 5.6, opacity: 0.9, amp: 3, over: 12, seed: seed + 16 }));
        mass(rect(x - q(22), y - q(20), w2 + q(44), q(22)), wood, 0.6, seed + 20, -4, 4.2, { depth: 0.85 });
        [-1, 1].forEach(function (s, i) {
          mass(rect(s < 0 ? x - q(22) : x + w2, y - q(20), q(22), hh2 + q(20)), wood, 0.6, seed + 24 + i * 4, -76, 4.2, { depth: 0.85 });
        });
      },
      // Light falling out of an open door onto a dark floor: warm, because it is
      // the lit hallway, and it stops where the throw stops.
      doorSpill: function (dx, dy, dw, floorY2, hh2, land2, seed) {
        AMB.spills.push({ x0: dx + dw * 0.06, x1: dx + dw * 0.94, y0: dy + (floorY2 - dy) * 0.12, y1: floorY2, seed: seed });
        const poly = [
          { x: dx + dw * 0.06, y: floorY2 }, { x: dx + dw * 0.94, y: floorY2 },
          { x: dx + dw * 1.34, y: hh2 }, { x: dx - dw * 0.28, y: hh2 },
        ];
        // The throw is where the floor is LEFT BARE while the floor either side
        // of it carries hatch — light as an absence of tone. Two edge lines give
        // it a shape; nothing is painted inside.
        solid(poly, paper, 1, seed);
        [[poly[0], poly[3]], [poly[1], poly[2]]].forEach(function (e, i) {
          thin([e[0], e[1]], 0.2, 2.4, seed + 20 + i);
        });
      },

      // the room before the furniture: ceiling line, a lower-wall tone so the wall
      // is not one flat field, a baseboard, and a floor that reads as a floor
      // The wall and the floor are the GROUND, left bare. Revision 01 put a flat
      // wash over the whole frame and then built the room back up on top of it,
      // which is what made the paper colour disappear — and once the paper is
      // gone, every value in the drawing has to be found again against a tone
      // that should not have been there.
      //
      // So: no wash. The wall is bare ground with a light hatch only in the band
      // FAR from both sources (the top of the wall, where nothing reaches), and
      // the floor carries a little more toward the camera. The falloff is a
      // gradient in how much hatch there is, not a colour.
      shell: function (floorY, w, h, seed) {
        // Six bands down the wall. The top of the wall is furthest from both
        // sources and carries the most hatch; the band behind the desk is nearly
        // bare ground. That gradient IS the lamp.
        const wallSteps = 6;
        for (let i = 0; i < wallSteps; i++) {
          const y0 = (floorY / wallSteps) * i, hgt = floorY / wallSteps + 2;
          const lum = lumAt(w * 0.5, y0 + hgt * 0.5);
          // The back wall RECEDES: the darks in this frame are objects now, so the
          // wall's job is to be the lightest plane in the room and stay out of the
          // way. Revision 02 gave it up to 0.5 of hatch and it competed with props.
          const op = clamp01(0.26 * (1 - lum) * (1 - i / (wallSteps + 1)));
          if (op > 0.02) P.colourAdd(S.hatch(rect(-20, y0, w + 40, hgt), { color: wood, opacity: op, gap: 10 + i * 0.5, width: 15, angle: -3, over: 26, seed: seed + i }));
        }
        // floor: heavier at the very front, where it is nearest camera
        P.colourAdd(S.hatch(rect(-20, floorY, w + 40, h - floorY), { color: wood, opacity: 0.3, gap: 9, width: 14, angle: -7, over: 26, seed: seed + 4 }));
        P.colourAdd(S.hatch(rect(-20, floorY + (h - floorY) * 0.5, w + 40, (h - floorY) * 0.5), { color: wood, opacity: 0.22, gap: 10, width: 15, angle: -7, over: 26, seed: seed + 5 }));
        // §4b — THE GROUND PLANE. Floor and wall sat at one value separated by a
        // single line, so nothing told the eye that one surface is horizontal and
        // the other vertical — which is why the room had no ground even with the
        // floor line at full ink. Two marks, and neither is a new colour:
        //   a value STEP, densest right at the junction and gone a third of the
        //   way down, because a floor is always darker where it meets a wall; and
        //   a second pass ACROSS the boards, so the two surfaces have different
        //   grain direction as well as different value. A plane is legible from
        //   the direction of its texture before it is legible from its tone.
        if (H2) {
          const fh = h - floorY;
          P.colourAdd(S.hatch(rect(-20, floorY, w + 40, fh * 0.34), { color: ink, opacity: 0.1, gap: 11, width: 15, angle: -7, over: 24, seed: seed + 30, material: false, plane: false }));
          P.colourAdd(S.hatch(rect(-20, floorY, w + 40, fh), { color: wood, opacity: 0.13, gap: 26, width: 11, angle: -84, over: 20, seed: seed + 32, material: false, plane: false }));
        }
        thin([{ x: -20, y: h * 0.05 }, { x: w + 20, y: h * 0.04 }], 0.24, 3, seed + 6);
        mass(rect(-20, floorY - q(24), w + 40, q(24)), wood, 0.42, seed + 8, -4, 3, { depth: 0.5 });
        // the floor line: the anchor of the whole drawing, so it is full ink
        P.inkAdd(S.line(-20, floorY, w + 20, floorY - 8, { stroke: ink, width: 4.6, opacity: 0.9, amp: 4, over: 24, seed: seed + 12 }));
        for (let i = 0; i < 4; i++) thin([{ x: w * (0.1 + i * 0.26), y: floorY + 8 }, { x: w * (0.04 + i * 0.3), y: h }], 0.14, 2.4, seed + 20 + i);
      },

      desk: function (x, y, w, h, seed) {
        // The top edge band and the front apron carry weight; the desk SURFACE is
        // left as ground, because that is the plane the lamp actually falls on.
        mass(rect(x, y, w, h * 0.15), wood, 0.7, seed, -4, 4, { weight: 0.8 });
        mass(rect(x + 8, y + h * 0.15, w - 16, h * 0.05), wood, 0.36, seed + 4, -4, 2.6, { weight: 1 });
        mass(rect(x + w * 0.04, y + h * 0.2, w * 0.06, h * 0.8), wood, 0.44, seed + 8, -74, 4, { weight: 1 });
        mass(rect(x + w * 0.9, y + h * 0.2, w * 0.06, h * 0.8), wood, 0.44, seed + 12, -74, 4, { weight: 1 });
        mass(rect(x + w * 0.2, y + h * 0.24, w * 0.6, h * 0.28), wood, 0.11, seed + 16, -76, 1.6);
        // §4b — THE DESK IS THE ROOM'S DEPTH, and it was carrying none of it. The
        // cast pass in mass() skips anything wider than 30% of frame (a desk is
        // not a prop), so the desk's own three shadows have to be authored here.
        // They are the largest depth cues available on the plate and all three
        // were absent: the review is right that the wall was the easier half.
        if (H2) {
          const kk = fall(x + w * 0.5, y + h, lampL) >= fall(x + w * 0.5, y + h, screenL) ? lampL : screenL;
          const dir = x + w * 0.5 - kk.x >= 0 ? 1 : -1;
          // 1 — the desk on the floor. A big object standing on the plane below
          // it: long throw, soft, and it starts under the apron rather than at
          // the leg, because the whole mass occludes.
          solid([
            { x: x + dir * w * 0.02, y: y + h - q(4) },
            { x: x + w + dir * w * 0.06, y: y + h - q(4) },
            { x: x + w + dir * w * 0.15, y: y + h + q(30) },
            { x: x + dir * w * 0.08, y: y + h + q(26) },
          ], ink, 0.13, seed + 68);
          solid([
            { x: x + dir * w * 0.04, y: y + h + q(8) },
            { x: x + w + dir * w * 0.1, y: y + h + q(8) },
            { x: x + w + dir * w * 0.24, y: y + h + q(58) },
            { x: x + dir * w * 0.14, y: y + h + q(50) },
          ], ink, 0.055, seed + 70);
          // 2 — the desk top onto the desk front. The nearest occlusion in the
          // composition and the cheapest: an overhang always shades what is
          // directly under it, hard at the lip and gone within a few units.
          // Tight: an overhang shadow is a few units of dark right at the lip,
          // not a band across the furniture. The first cut ran 12% of the desk's
          // height at 0.16 and read as a painted stripe.
          solid(rect(x + q(6), y + h * 0.15, w - q(12), h * 0.035), ink, 0.13, seed + 72);
          solid(rect(x + q(6), y + h * 0.185, w - q(12), h * 0.028), ink, 0.05, seed + 74);
        }
        // 3 — the legs meet the floor. These existed and were too small to see at
        // render scale: a leg is 6% of the desk, so 5% of the desk width was a
        // smear a third of the leg's own width.
        contact(x + w * 0.07, y + h, w * (H2 ? 0.1 : 0.05), seed + 60, H2 ? 1.35 : 1);
        contact(x + w * 0.93, y + h, w * (H2 ? 0.1 : 0.05), seed + 64, H2 ? 1.35 : 1);
      },

      // sits ON deskTop: foot plate on the surface, neck, then the panel above it
      monitor: function (x, deskTop, w, hh, seed) {
        const ww = w, hd = hh;
        const bot = deskTop - q(46), top = bot - hd;
        AMB.screens.push({ x: x, y: top, w: ww, h: hd, seed: seed });
        mass(rect(x, top, ww, hd), wood, 0.5, seed, -76, 4, { weight: 0.9 });
        // The panel is a source, so it is the LIGHTEST thing in frame: bare
        // ground inside its bezel, no fill at all. Revision 01 hatched it cold
        // blue, which made the brightest object in the room a mid-tone.
        mass(rect(x + q(16), top + q(16), ww - q(32), hd - q(44)), screen, 0.1, seed + 4, -70, 2.4, { flat: true });
        const sx = x + q(32), sw = ww - q(64), sy = top + q(32), sh = hd - q(76);
        const pts = [];
        for (let i = 0; i < 7; i++) pts.push({ x: sx + (sw / 6) * i, y: sy + sh * (0.22 + 0.09 * i + (i % 2 ? 0.06 : -0.04)) });
        // set dressing, drawn in INK. It was p.down — a data role, red — which is
        // the plate system leaking into the room: a red line on a monitor in the
        // background reads as a loss the script never mentioned.
        P.inkAdd(S.stroke(pts, { stroke: ink, width: 3.2, opacity: 0.34, amp: 2, over: 6, seed: seed + 6 }));
        thin([{ x: sx, y: sy + sh }, { x: sx + sw, y: sy + sh }], 0.26, 2, seed + 8);
        for (let i = 1; i < 4; i++) thin([{ x: sx, y: sy + sh * i * 0.24 }, { x: sx + sw * 0.5, y: sy + sh * i * 0.24 - q(2) }], 0.14, 2, seed + 10 + i);
        thin([{ x: x + q(22), y: bot - q(20) }, { x: x + ww - q(22), y: bot - q(22) }], 0.28, 2.2, seed + 16);
        const cxm = x + ww / 2;
        mass(rect(cxm - ww * 0.05, bot, ww * 0.1, q(44)), wood, 0.5, seed + 20, -78, 3.2);
        mass(rect(cxm - ww * 0.19, deskTop - q(14), ww * 0.38, q(16)), wood, 0.56, seed + 24, -4, 3.2);
        contact(cxm, deskTop + q(2), ww * 0.21, seed + 28);
      },

      keyboard: function (x, baseY, w, seed) {
        const y = baseY - q(52);
        contact(x + w * 0.5, baseY - q(2), w * 0.46, seed + 60);
        mass([{ x: x, y: y }, { x: x + w, y: y - q(8) }, { x: x + w - q(14), y: y + q(44) }, { x: x + q(12), y: y + q(52) }], wood, 0.6, seed, -8, 3.4);
        for (let r = 0; r < 3; r++) for (let c = 0; c < 12; c++) {
          const kx = x + q(24) + c * ((w - q(48)) / 12), ky = y + q(10) + r * q(12);
          thin([{ x: kx, y: ky }, { x: kx + (w - q(48)) / 17, y: ky - q(1) }], 0.2, 2, seed + r * 20 + c);
        }
      },
      mouse: function (x, baseY, s, seed) {
        const y = baseY - s * 0.34;
        contact(x, baseY, s * 0.5, seed + 20);
        mass(ellipse(x, y, s * 0.5, s * 0.34, 16, 0.05, seed), wood, 0.58, seed, -70, 3.2);
        thin([{ x: x, y: y - s * 0.3 }, { x: x, y: y }], 0.28, 2, seed + 3);
      },
      // a cylinder, not a disc seen from above — and chipped, nine years in
      mug: function (x, baseY, r, seed, chipped) {
        contact(x, baseY, r * 0.95, seed + 30);
        AMB.mugs.push({ x: x, top: baseY - r * 1.5, r: r, seed: seed });
        mass([{ x: x - r, y: baseY - r * 1.5 }, { x: x + r, y: baseY - r * 1.5 }, { x: x + r * 0.85, y: baseY }, { x: x - r * 0.85, y: baseY }], wood, 0.6, seed, -74, 3.4);
        P.inkAdd(S.outline(ellipse(x, baseY - r * 1.5, r, r * 0.3, 14, 0.05, seed + 2), { stroke: ink, width: 3, opacity: 0.75, amp: 1.6, over: 6, seed: seed + 3 }));
        P.inkAdd(S.stroke([{ x: x + r * 0.95, y: baseY - r * 1.18 }, { x: x + r * 1.7, y: baseY - r * 0.86 }, { x: x + r * 0.9, y: baseY - r * 0.34 }], { stroke: ink, width: 3.2, opacity: 0.8, amp: 1.8, over: 5, seed: seed + 5 }));
        if (chipped) {
          solid([{ x: x - r * 0.42, y: baseY - r * 1.62 }, { x: x - r * 0.14, y: baseY - r * 1.6 }, { x: x - r * 0.26, y: baseY - r * 1.38 }], paper, 1, seed + 7);
          thin([{ x: x - r * 0.44, y: baseY - r * 1.5 }, { x: x - r * 0.26, y: baseY - r * 1.34 }, { x: x - r * 0.1, y: baseY - r * 1.5 }], 0.6, 2.6, seed + 9);
        }
      },
      plant: function (x, baseY, s, seed) {
        contact(x, baseY, s * 0.34, seed + 40);
        mass([{ x: x - s * 0.36, y: baseY - s * 0.52 }, { x: x + s * 0.36, y: baseY - s * 0.52 }, { x: x + s * 0.26, y: baseY }, { x: x - s * 0.26, y: baseY }], terracotta, 0.5, seed, -70, 3.6, { weight: 0.7 });
        thin([{ x: x - s * 0.36, y: baseY - s * 0.43 }, { x: x + s * 0.36, y: baseY - s * 0.44 }], 0.4, 2.4, seed + 2);
        P.inkAdd(S.stroke([{ x: x, y: baseY - s * 0.5 }, { x: x + s * 0.05, y: baseY - s * 1.0 }], { stroke: foliage, width: 5.2, opacity: 0.75, amp: 2.2, over: 6, seed: seed + 4 }));
        for (let i = 0; i < 5; i++) {
          const sg = i % 2 ? 1 : -1, t = 0.3 + i * 0.13;
          const bx = x + sg * s * 0.05, by = baseY - s * (0.56 + t * 0.52);
          P.inkAdd(S.stroke([
            { x: bx, y: by }, { x: bx + sg * s * 0.3, y: by - s * 0.05 }, { x: bx + sg * s * 0.44, y: by + s * 0.2 },
          ], { stroke: foliage, width: 6.4, opacity: 0.72 - i * 0.05, amp: 3.2, over: 6, seed: seed + 10 + i }));
        }
        P.inkAdd(S.stroke([{ x: x + s * 0.5, y: baseY - 5 }, { x: x + s * 0.74, y: baseY - 2 }], { stroke: foliage, width: 5.4, opacity: 0.5, amp: 2.2, over: 5, seed: seed + 20 }));
      },
      printer: function (x, baseY, w, hh, seed) {
        const top = baseY - hh;
        contact(x + w * 0.5, baseY, w * 0.46, seed + 50);
        // the gap behind it, against the wall: dark, and it sets the printer off
        deep(rect(x - q(6), top - q(4), w + q(12), q(22)), seed + 210, 0.66, 3, "top");
        mass(rect(x, top, w, hh), wood, 0.48, seed, -78, 4, { weight: 0.85 });
        thin([{ x: x + q(14), y: top + hh * 0.44 }, { x: x + w - q(14), y: top + hh * 0.42 }], 0.45, 2.6, seed + 4);
        // the page in the tray has been sitting there long enough to curl
        mass([{ x: x + w * 0.18, y: top }, { x: x + w * 0.8, y: top - q(6) }, { x: x + w * 0.76, y: top - q(48) }, { x: x + w * 0.22, y: top - q(42) }], paper, 0.85, seed + 8, -3, 3);
        thin([{ x: x + w * 0.22, y: top - q(42) }, { x: x + w * 0.44, y: top - q(56) }, { x: x + w * 0.76, y: top - q(48) }], 0.4, 2.6, seed + 9);
        mass(rect(x + w * 0.1, baseY - hh * 0.22, w * 0.8, hh * 0.13), wood, 0.28, seed + 12, -4, 2.6);
        P.colourAdd(S.hatch(ellipse(x + w * 0.85, top + hh * 0.22, q(9), q(8), 10, 0.08, seed + 16), { color: p.down, opacity: 0.7, gap: 3, width: 5, angle: -60, seed: seed + 17 }));
      },
      calendar: function (x, y, w, hh, seed) {
        mass(rect(x, y, w, hh), paper, 0.88, seed, -3, 3.6);
        mass(rect(x, y, w, hh * 0.2), wood, 0.38, seed + 3, -4, 2.6);
        const cols = 5, rows = 4;
        for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) {
          const dx = x + q(14) + c * ((w - q(28)) / cols), dy = y + hh * 0.28 + r * ((hh * 0.66) / rows);
          if ((r === 1 && c === 3) || (r === 3 && c === 1)) {
            P.colourAdd(S.hatch(ellipse(dx + q(9), dy + q(8), q(15), q(13), 12, 0.08, seed + r * 5 + c), { color: p.down, opacity: 0.42, gap: 4.5, width: 7, angle: -70, seed: seed + r + c }));
          }
          thin([{ x: dx, y: dy + q(8) }, { x: dx + q(13), y: dy + q(7) }], 0.28, 1.8, seed + r * 7 + c);
        }
      },
      postits: function (x, y, n, seed) {
        for (let i = 0; i < n; i++) mass(rect(x + i * q(60), y + (i % 2 ? q(12) : 0), q(50), q(50)), p.attention, 0.36, seed + i * 3, -6, 3);
      },
      tapedPage: function (x, y, w, hh, seed) {
        mass(rect(x, y, w, hh), paper, 0.86, seed, -3, 3.4);
        for (let i = 0; i < 5; i++) thin([{ x: x + q(16), y: y + hh * (0.26 + i * 0.14) }, { x: x + w * (0.46 + (i % 3) * 0.17), y: y + hh * (0.26 + i * 0.14) - q(3) }], 0.32, 2.2, seed + i * 4);
        mass(rect(x + w * 0.36, y - q(13), w * 0.28, q(22)), p.attention, 0.24, seed + 30, -5, 2.2);
      },
      // §1.3 — ONE THING MOVING, AND IT IS STEAM BY DEFAULT.
      //
      // The candidate props do not have the same clock. A cursor blinks at about
      // 1 Hz in life and a room strip runs at 2 fps, so a caret driven off the
      // frame index blinks two or three times a second and reads as nervous; a
      // second hand at 2 fps is visibly wrong and a minute hand does not move
      // within a shot at all. Both want a clock of their own, which is the same
      // problem the blink has and the same answer — a separate strip — and that
      // is more than a decorative prop earns.
      //
      // Steam is the one candidate whose natural rate matches the boil's.
      // It DRIFTS, and drift looks correct at any frame rate, so it can ride the
      // room's own three-frame clock without lying about its speed. Nothing here
      // is synchronised to anything: the wisps are at three different phases in
      // the same rise, and which phase each is at comes off the frame index.
      //
      // Drawn in `paper` over a room that is darker than it: steam is lighter
      // than what is behind it, and this adds no colour token.
      steam: function (x, topY, r, seed, ph) {
        const f = ((ph | 0) % 3 + 3) % 3;
        for (let i = 0; i < 3; i++) {
          const t = ((f * 0.34 + i * 0.33) % 1);
          const rise = r * (1.4 + 2.7 * t);
          const sway = r * 0.44 * Math.sin(t * 5.4 + i * 2.1);
          const x0 = x + (i - 1) * r * 0.32;
          // it thins as it rises, and it is gone before it reaches the top
          P.inkAdd(S.stroke([
            { x: x0, y: topY - r * 0.18 },
            { x: x0 + sway * 0.5, y: topY - rise * 0.42 },
            { x: x0 - sway * 0.4, y: topY - rise * 0.76 },
            { x: x0 + sway, y: topY - rise },
          ], {
            stroke: paper, width: q(4.4) * (1 - t * 0.45), opacity: 0.30 * (1 - t) + 0.05,
            amp: 2.6, over: 0, seed: seed + 70 + i * 7 + f * 31,
          }));
        }
      },
      // The exception, and it has to be earned: on the angle where the SCREEN is
      // the subject, the thing that should be alive is the screen. A caret is
      // on for two frames of three, which at 2 fps is the slowest blink the
      // strip can express and still be a blink.
      cursor: function (sx, sy, seed, ph) {
        if (((ph | 0) % 3) === 2) return;
        P.inkAdd(S.line(sx, sy, sx, sy + q(30), { stroke: paper, width: q(8), opacity: 0.42, amp: 1.1, over: 0, seed: seed + 88 }));
      },
      // Called once per plate, AFTER the furniture. Returns the descriptor
      // whatever the frame index is — so the manifest says the same thing on
      // every frame — and draws only when there is a frame to draw on. A boil-0
      // hold is the identity and nothing moves on it.
      ambient: function (frame, subject) {
        const f = frame | 0;
        const biggest = (a) => a.reduce(function (m, v) { return (v.r || v.w) > (m.r || m.w) ? v : m; });
        let d = null;
        if (subject === "screen" && AMB.screens.length) {
          const s = biggest(AMB.screens);
          d = { prop: "cursor", on: "monitor", x: Math.round(s.x + s.w * 0.17), y: Math.round(s.y + s.h * 0.28) };
          if (f) this.cursor(s.x + s.w * 0.17, s.y + s.h * 0.28, s.seed, f);
        } else if (AMB.cards.length) {
          // §3.3 takes priority over the mug where a card has just been pinned: it
          // is a BEAT, and the room should move where the story is.
          const c = AMB.cards[AMB.cards.length - 1];
          d = { prop: "flutter", on: "pinned-card", x: Math.round(c.x), y: Math.round(c.y) };
          if (f) this.flutter(c.x, c.y, c.s, c.seed, f);
        } else if (AMB.mugs.length) {
          const m = biggest(AMB.mugs);
          d = { prop: "steam", on: "mug", x: Math.round(m.x), y: Math.round(m.top) };
          if (f) this.steam(m.x, m.top, m.r, m.seed, f);
        } else if (AMB.screens.length) {
          const s = biggest(AMB.screens);
          d = { prop: "cursor", on: "monitor", x: Math.round(s.x + s.w * 0.17), y: Math.round(s.y + s.h * 0.28) };
          if (f) this.cursor(s.x + s.w * 0.17, s.y + s.h * 0.28, s.seed, f);
        } else if (AMB.spills.length) {
          const v = AMB.spills[0];
          d = { prop: "spill", on: "doorway", x: Math.round(v.x0), y: Math.round(v.y0) };
          if (f) this.spill(v.x0, v.x1, v.y0, v.y1, v.seed, f);
        }
        if (d) {
          d.note = "one unsynchronised prop, riding this plate's own three-frame clock. Nobody looks at it directly; it is what stops the room being a photograph. A second one reads as a screensaver.";
          d.clock = "the boil index. Steam drifts, so it is honest at any frame rate; the cursor is on for two frames of three, which is the slowest blink a 2fps strip can express.";
        }
        return d;
      },
      // §1.3 — the wavering edge of light from the hall. The doorway draws no mug
      // and no monitor, so without this it is one of three rooms with nothing
      // alive in it. A spill edge drifts for the same reason steam does — it is
      // air and light, not a mechanism — so it stays honest at any frame rate.
      spill: function (x0, x1, y0, y1, seed, ph) {
        const f = ((ph | 0) % 3 + 3) % 3;
        for (let i = 0; i < 2; i++) {
          const t = ((f * 0.34 + i * 0.5) % 1);
          const k2 = q(9) * (0.5 + t);
          P.inkAdd(S.stroke([
            { x: x0 + k2 * 0.4, y: y0 },
            { x: (x0 + x1) / 2 + k2 * Math.sin(t * 4.1), y: (y0 + y1) / 2 },
            { x: x1 - k2 * 0.6, y: y1 },
          ], { stroke: paper, width: q(5) * (1 - t * 0.4), opacity: 0.20 * (1 - t) + 0.06, amp: 3.2, over: 0, seed: seed + 61 + i * 13 + f * 29 }));
        }
      },
      // §3.3 — a card that has just been pinned sits proud of the others and has
      // not settled. One corner lifts and falls: the newest thing on the wall is
      // the only thing on it still moving, which is the gag doing double duty as
      // §1.3's one moving prop.
      flutter: function (x, y, s2, seed, ph) {
        const f = ((ph | 0) % 3 + 3) % 3;
        const lift = q(7) * [0.2, 1, 0.55][f];
        P.inkAdd(S.stroke([
          { x: x, y: y },
          { x: x + s2 * 0.5, y: y - lift * 0.6 },
          { x: x + s2, y: y - lift },
        ], { stroke: ink, width: q(3.4), opacity: 0.72, amp: 1.6, over: 3, seed: seed + 77 + f * 19 }));
      },
      registerCard: function (x, y, s2, seed) { AMB.cards.push({ x: x, y: y, s: s2, seed: seed }); },
      clock: function (x, y, r, seed) {
        mass(ellipse(x, y, r, r, 22, 0.025, seed), paper, 0.8, seed, -70, 3.6);
        thin([{ x: x, y: y }, { x: x, y: y - r * 0.62 }], 0.7, 3.4, seed + 4);
        thin([{ x: x, y: y }, { x: x + r * 0.46, y: y + r * 0.2 }], 0.7, 3, seed + 6);
      },
      chair: function (x, baseY, s, seed) {
        contact(x, baseY, s * 0.5, seed + 40, 1.3);
        mass(rect(x - s * 0.44, baseY - s * 2.1, s * 0.88, s * 0.9), wood, 0.5, seed, -74, 4, { weight: 0.9 });
        thin([{ x: x - s * 0.32, y: baseY - s * 1.74 }, { x: x + s * 0.32, y: baseY - s * 1.77 }], 0.3, 2.4, seed + 2);
        mass(rect(x - s * 0.5, baseY - s * 1.24, s * 1.0, s * 0.16), wood, 0.6, seed + 4, -4, 3.4);
        mass(rect(x - s * 0.07, baseY - s * 1.08, s * 0.14, s * 0.78), wood, 0.48, seed + 8, -78, 3.2);
        [-1, 1].forEach(function (sg, i) {
          thin([{ x: x, y: baseY - s * 0.3 }, { x: x + sg * s * 0.46, y: baseY - s * 0.06 }], 0.6, 4, seed + 12 + i);
          P.inkAdd(S.outline(ellipse(x + sg * s * 0.48, baseY, s * 0.075, s * 0.075, 10, 0.06, seed + 16 + i), { stroke: ink, width: 3, opacity: 0.7, amp: 1.4, over: 5, seed: seed + 18 + i }));
        });
      },
      // the back of the screen, for the over-the-shoulder angle: vents and a stand,
      // not a blank slab
      monitorBack: function (x, baseY, w, hh, seed) {
        const top = baseY - hh;
        // The back of a monitor is a DARK object. Drawn as a pale panel it was the
        // largest mid-tone in the over-the-shoulder angle and flattened the frame.
        mass(rect(x, top, w, hh), wood, 0.6, seed, -78, 5, { weight: 1, depth: PLANE.back });
        deep(rect(x + w * 0.06, top + hh * 0.3, w * 0.88, hh * 0.66), seed + 300, 0.6, 0, "bottom");
        for (let i = 0; i < 9; i++) thin([{ x: x + w * 0.58, y: top + hh * 0.2 + i * (hh * 0.5 / 9) }, { x: x + w * 0.9, y: top + hh * 0.2 + i * (hh * 0.5 / 9) - 3 }], 0.26, 2.4, seed + 4 + i);
        mass(rect(x + w * 0.3, top + hh * 0.3, w * 0.2, hh * 0.22), wood, 0.3, seed + 20, -70, 2.6);
        mass(rect(x + w * 0.42, baseY, w * 0.1, hh * 0.24), wood, 0.5, seed + 26, -78, 3.2);
        mass(rect(x + w * 0.28, baseY + hh * 0.24, w * 0.38, hh * 0.06), wood, 0.56, seed + 30, -4, 3.2);
      },
      openReport: function (x, baseY, w, seed) {
        const hh = w * 0.34;
        mass([{ x: x, y: baseY - hh * 0.86 }, { x: x + w * 0.5, y: baseY - hh }, { x: x + w * 0.5, y: baseY }, { x: x + 6, y: baseY - 4 }], paper, 0.86, seed, -4, 3);
        mass([{ x: x + w * 0.5, y: baseY - hh }, { x: x + w, y: baseY - hh * 0.88 }, { x: x + w - 6, y: baseY - 4 }, { x: x + w * 0.5, y: baseY }], paper, 0.8, seed + 4, -4, 3);
        for (let i = 0; i < 5; i++) {
          thin([{ x: x + w * 0.06, y: baseY - hh * (0.72 - i * 0.13) }, { x: x + w * 0.44, y: baseY - hh * (0.75 - i * 0.13) }], 0.3, 2.2, seed + 10 + i);
          thin([{ x: x + w * 0.56, y: baseY - hh * (0.74 - i * 0.13) }, { x: x + w * 0.94, y: baseY - hh * (0.77 - i * 0.13) }], 0.3, 2.2, seed + 20 + i);
        }
        P.inkAdd(S.stroke([{ x: x + w * 0.62, y: baseY - hh * 0.52 }, { x: x + w * 0.86, y: baseY - hh * 0.3 }], { stroke: p.down, width: 4, opacity: 0.45, amp: 2.6, over: 6, seed: seed + 40 }));
      },
      pen: function (x, baseY, len, seed) {
        P.inkAdd(S.stroke([{ x: x, y: baseY }, { x: x + len, y: baseY - len * 0.16 }], { stroke: ink, width: 7, opacity: 0.65, amp: 1.6, over: 4, seed: seed }));
        P.inkAdd(S.stroke([{ x: x + len * 0.86, y: baseY - len * 0.14 }, { x: x + len, y: baseY - len * 0.16 }], { stroke: p.attention, width: 7, opacity: 0.5, amp: 1.2, over: 3, seed: seed + 2 }));
      },
      // an overfull bin: the whole point of a bin in this room
      wastebasket: function (x, baseY, s, seed) {
        contact(x, baseY, s * 0.36, seed + 30);
        mass([{ x: x - s * 0.4, y: baseY - s }, { x: x + s * 0.4, y: baseY - s }, { x: x + s * 0.3, y: baseY }, { x: x - s * 0.3, y: baseY }], wood, 0.42, seed, -76, 3.4, { weight: 0.9 });
        // the inside of the bin: a hole, and one of the frame's real darks
        deep(ellipse(x, baseY - s, s * 0.38, s * 0.11, 14, 0.06, seed + 200), seed + 200, 0.8, 3, "top");
        P.inkAdd(S.outline(ellipse(x, baseY - s, s * 0.4, s * 0.12, 14, 0.06, seed + 4), { stroke: ink, width: 3, opacity: 0.7, amp: 1.6, over: 6, seed: seed + 5 }));
        mass(ellipse(x + s * 0.1, baseY - s * 1.1, s * 0.18, s * 0.14, 12, 0.14, seed + 8), paper, 0.8, seed + 8, -3, 2.6);
        mass(ellipse(x - s * 0.14, baseY - s * 1.16, s * 0.15, s * 0.13, 11, 0.2, seed + 12), paper, 0.76, seed + 12, -3, 2.4);
        mass(ellipse(x + s * 0.3, baseY - s * 1.02, s * 0.13, s * 0.11, 10, 0.24, seed + 16), paper, 0.72, seed + 16, -3, 2.4);
        mass(ellipse(x + s * 0.52, baseY - s * 0.1, s * 0.16, s * 0.13, 11, 0.22, seed + 20), paper, 0.74, seed + 20, -3, 2.4);
      },
      coat: function (x, y, s, seed) {
        thin([{ x: x - s * 0.2, y: y }, { x: x + s * 0.2, y: y - 2 }], 0.55, 4, seed);
        mass([{ x: x - s * 0.36, y: y + s * 0.12 }, { x: x + s * 0.36, y: y + s * 0.12 }, { x: x + s * 0.3, y: y + s * 1.2 }, { x: x - s * 0.3, y: y + s * 1.26 }], wood, 0.44, seed + 4, -76, 3.4);
        thin([{ x: x, y: y + s * 0.2 }, { x: x - s * 0.04, y: y + s * 1.16 }], 0.3, 2.4, seed + 8);
      },
      lamp: function (x, baseY, s, seed) {
        // The lamp does not paint a cone. What a lamp does in this drawing is take
        // hatch OFF the surfaces near it — which lumAt already handles, since the
        // lamp's position is declared. All that is drawn here is the object, plus
        // two faint rays that read as a lit direction without laying down tone.
        [0.34, 0.72].forEach(function (t, i) {
          thin([{ x: x + s * (0.1 + t * 0.7), y: baseY - s * 0.78 }, { x: x + s * (0.5 + t * 1.2), y: baseY - q(2) }], 0.14, 2, seed + 12 + i);
        });
        contact(x, baseY, s * 0.3, seed + 16);
        mass(rect(x - s * 0.3, baseY - s * 0.1, s * 0.6, s * 0.1), wood, 0.5, seed, -4, 3);
        thin([{ x: x, y: baseY - s * 0.1 }, { x: x - s * 0.06, y: baseY - s * 0.9 }, { x: x + s * 0.38, y: baseY - s * 1.06 }], 0.72, 4.4, seed + 4);
        mass([{ x: x + s * 0.14, y: baseY - s * 1.04 }, { x: x + s * 0.66, y: baseY - s * 1.12 }, { x: x + s * 0.78, y: baseY - s * 0.8 }, { x: x + s * 0.04, y: baseY - s * 0.74 }], wood, 0.54, seed + 8, -70, 3.4);
      },
      stack: function (x, baseY, w, n, seed) {
        contact(x + w * 0.5, baseY, w * 0.5, seed + 40);
        for (let i = 0; i < n; i++) mass(rect(x + (i % 2 ? q(7) : 0), baseY - (i + 1) * q(20), w, q(20)), paper, 0.82, seed + i * 3, -3, 2.8);
        // the top sheet's corner has lifted
        thin([{ x: x + w * 0.62, y: baseY - n * q(20) }, { x: x + w * 0.88, y: baseY - n * q(20) - q(13) }, { x: x + w, y: baseY - n * q(20) + q(3) }], 0.34, 2.4, seed + 44);
      },
      stackHeight: function (n) { return n * q(20); },
      medal: function (x, baseY, s, seed) {
        mass([{ x: x - s * 0.22, y: baseY - s * 1.1 }, { x: x + s * 0.22, y: baseY - s * 1.1 }, { x: x + s * 0.1, y: baseY - s * 0.52 }, { x: x - s * 0.1, y: baseY - s * 0.52 }], p.attention, 0.28, seed, -72, 3);
        mass(ellipse(x, baseY - s * 0.3, s * 0.3, s * 0.3, 16, 0.04, seed + 4), p.attention, 0.4, seed + 4, -70, 3.4);
      },
      // Binders hang on the wall, but they are drawn low in the frame, so their y
      // says "near camera" and their plane says "far". This is the one case the
      // steep depth curve gets wrong on its own, so the plane is stated.
      binders: function (x, baseY, w, hh, n, seed) {
        contact(x + w * 0.5, baseY + q(16), w * 0.55, seed + 40);
        mass(rect(x - q(14), baseY, w + q(28), q(16)), wood, 0.5, seed, -4, 3.2, { depth: PLANE.wall });
        for (let i = 0; i < n; i++) {
          const bw = w / n, bx = x + i * bw, t = i === n - 1 ? q(12) : 0;
          mass([{ x: bx + t, y: baseY - hh }, { x: bx + bw - q(6) + t * 1.7, y: baseY - hh }, { x: bx + bw - q(6), y: baseY }, { x: bx, y: baseY }], i % 2 ? wood : paper, i % 2 ? 0.5 : 0.78, seed + 6 + i * 5, -76, 3);
        }
      },
      whiteboard: function (x, y, w, hh, seed) {
        mass(rect(x, y, w, hh), "#F1F2EE", 0.9, seed, -2);
        for (let i = 0; i < 8; i++) {
          const gy = y + q(44) + i * ((hh - q(96)) / 8);
          thin([{ x: x + q(34) + (i % 3) * q(26), y: gy }, { x: x + w * (0.4 + (i % 4) * 0.13), y: gy - q(4) }], i % 3 === 0 ? 0.14 : 0.5, 3, seed + i * 7);
        }
        P.inkAdd(S.stroke([{ x: x + w * 0.6, y: y + hh * 0.28 }, { x: x + w * 0.86, y: y + hh * 0.54 }], { stroke: p.down, width: 5, opacity: 0.4, amp: 3.6, over: 7, seed: seed + 40 }));
        mass(rect(x + w * 0.1, y + hh, w * 0.5, q(14)), wood, 0.44, seed + 50, -4, 2.8);
      },
      // a cord with actual slack: four points, so it hangs instead of kinking
      cable: function (x1, y1, x2, y2, seed) {
        const dx = x2 - x1, dy = y2 - y1;
        P.inkAdd(S.stroke([
          { x: x1, y: y1 }, { x: x1 + dx * 0.18, y: y1 + dy * 0.5 },
          { x: x1 + dx * 0.5, y: y1 + dy * 0.86 }, { x: x1 + dx * 0.8, y: y2 - dy * 0.06 }, { x: x2, y: y2 },
        ], { stroke: ink, width: 3, opacity: 0.3, amp: 2.2, over: 6, seed: seed }));
      },

      // ================= CAMERA ==============================================
      // Every primitive above this line draws a flat ELEVATION. A rect is a rect,
      // the horizon sits at whatever height the floor line was put, and no edge
      // runs away from the viewer — so eight angles assembled out of them are
      // eight arrangements of furniture photographed from one position, and
      // cutting between them reads as props sliding around on a shelf rather than
      // as cutting. Closing that is the whole of revision 05.
      //
      // Three variables were going unused. PERSPECTIVE is the one that needs new
      // geometry, and it is what these add: a vanishing point, and walls, floors
      // and desks that converge on it. HEIGHT and SHOT SIZE are then just choices
      // about where to put the camera, which the angle branches make.
      //
      // Tone is unchanged. lumAt still carries the light and depth still sets
      // line weight; the one addition is that a receding surface is not at a
      // single depth, so it is drawn in depth BANDS and each band declares its
      // own. A gradient of line weight down the length of one desk is the thing
      // that reads as distance — it is the same trick the props already use to
      // separate planes, applied within a single object.
      vanish: function (vx, vy) {
        return {
          x: vx, y: vy,
          // t is 0 at the picture plane and 1 at the vanishing point
          to: function (x, y, t) { return { x: x + (vx - x) * t, y: y + (vy - y) * t }; },
          // what an object at depth t shrinks to
          s: function (t) { return 1 - t; },
          // depth of a point that lands at screen x on a line through (x0,y0)
          tAtX: function (x0, x) { return (x - x0) / ((vx - x0) || 1); },
        };
      },

      // A room with a CORNER in it: one wall square to camera, one running away
      // to the vanishing point, meeting on a vertical. The floor boards and the
      // ceiling line converge on the same point, which is what makes the two
      // walls read as one space instead of two flats stood side by side.
      //
      // The corner vertical is the single most important line on the plate and it
      // gets full ink at near weight. Without it the two walls are just two
      // differently-hatched rectangles.
      cornerRoom: function (V, cornerX, ceilY, floorY, tFar, seed) {
        const jF = function (x) { const t = (x - cornerX) / ((V.x - cornerX) || 1); return floorY + (V.y - floorY) * t; };
        const jC = function (x) { const t = (x - cornerX) / ((V.x - cornerX) || 1); return ceilY + (V.y - ceilY) * t; };
        const xR = W + 20;
        // FRONTAL WALL, camera-left of the corner. Flat, and the lightest plane in
        // the room: same six-band treatment as shell(), because it is the same
        // kind of surface.
        for (let i = 0; i < 5; i++) {
          const bh = (floorY - ceilY) / 5, y0 = ceilY + bh * i;
          const lum = lumAt(cornerX * 0.5, y0 + bh * 0.5);
          const op = clamp01(0.24 * (1 - lum) * (1 - i / 6));
          if (op > 0.02) P.colourAdd(S.hatch(rect(-20, y0, cornerX + 20, bh + 2), { color: wood, opacity: op, gap: 10 + i * 0.5, width: 15, angle: -3, over: 26, seed: seed + i }));
        }
        // RECEDING WALL. Banded in DEPTH rather than in height, and each band
        // carries a little more hatch than the one in front of it: the wall is now
        // the surface with real distance in it, so it is where atmospheric
        // perspective belongs.
        for (let i = 0; i < 6; i++) {
          const t0 = (tFar / 6) * i, t1 = (tFar / 6) * (i + 1);
          const band = [V.to(cornerX, ceilY, t0), V.to(cornerX, ceilY, t1), V.to(cornerX, floorY, t1), V.to(cornerX, floorY, t0)];
          const c = centroid(band);
          P.colourAdd(S.hatch(band, { color: wood, opacity: clamp01((0.1 + 0.26 * (1 - lumAt(c.x, c.y))) * (0.45 + i * 0.13)), gap: 9.5, width: 14, angle: -70, over: 22, seed: seed + 20 + i }));
        }
        // CEILING. Above the frontal wall it is a flat band; past the corner it
        // comes DOWN toward the horizon, and that descending line is half of what
        // says the wall is receding.
        P.colourAdd(S.hatch(rect(-20, -20, cornerX + 20, ceilY + 22), { color: wood, opacity: 0.2, gap: 11, width: 16, angle: -3, over: 24, seed: seed + 40 }));
        P.colourAdd(S.hatch([{ x: cornerX, y: ceilY }, { x: xR, y: jC(xR) }, { x: xR, y: -20 }, { x: cornerX, y: -20 }], { color: wood, opacity: 0.16, gap: 12, width: 16, angle: -70, over: 22, seed: seed + 42 }));
        // FLOOR. The mirror of the ceiling: past the corner it opens UP toward the
        // horizon, so the floor gets bigger as the wall goes away.
        P.colourAdd(S.hatch(rect(-20, floorY, W + 40, HH - floorY + 20), { color: wood, opacity: 0.3, gap: 9, width: 14, angle: -7, over: 26, seed: seed + 44 }));
        P.colourAdd(S.hatch([{ x: cornerX, y: floorY }, { x: xR, y: jF(xR) }, { x: xR, y: floorY }], { color: wood, opacity: 0.26, gap: 10, width: 15, angle: -7, over: 24, seed: seed + 46 }));
        // §4b IN THE CORNER ROOM. shell() got the ground plane and this did not,
        // which is worse than either room being unconverted: two rooms at two
        // levels of finish in one cut. Same two marks, and the value step follows
        // the junction rather than a horizontal — in here the junction is the
        // receding line jF(x), so the step is a band between the floor line and
        // its own offset, and it opens up as the wall goes away exactly as the
        // floor does.
        if (H2) {
          const fh = HH - floorY;
          P.colourAdd(S.hatch([
            { x: -20, y: floorY }, { x: cornerX, y: floorY }, { x: xR, y: jF(xR) },
            { x: xR, y: jF(xR) + fh * 0.3 }, { x: cornerX, y: floorY + fh * 0.34 }, { x: -20, y: floorY + fh * 0.34 },
          ], { color: ink, opacity: 0.1, gap: 11, width: 15, angle: -7, over: 24, seed: seed + 60, material: false, plane: false }));
          P.colourAdd(S.hatch(rect(-20, floorY, W + 40, HH - floorY + 20), { color: wood, opacity: 0.13, gap: 26, width: 11, angle: -84, over: 20, seed: seed + 62, material: false, plane: false }));
        }
        // FLOOR BOARDS, converging. Six lines from the bottom edge of the frame to
        // the vanishing point. This is the cheapest perspective cue on the plate
        // and the one the eye reads first.
        for (let i = 0; i < 7; i++) {
          const bx = -W * 0.15 + W * 0.24 * i;
          const end = V.to(bx, HH + 20, 0.82);
          thin([{ x: bx, y: HH + 20 }, { x: (bx + end.x) / 2, y: (HH + 20 + end.y) / 2 }, { x: end.x, y: end.y }], 0.16, 2.6, seed + 60 + i);
        }
        // CEILING JOINTS, converging on the same point
        for (let i = 0; i < 3; i++) {
          const bx = -W * 0.1 + W * 0.3 * i;
          const end = V.to(bx, -20, 0.7);
          thin([{ x: bx, y: -20 }, { x: end.x, y: end.y }], 0.1, 2.2, seed + 70 + i);
        }
        // the two junction lines, and the corner
        P.inkAdd(S.line(-20, floorY, cornerX, floorY - 3, { stroke: ink, width: 4.4, opacity: 0.9, amp: 3.6, over: 22, seed: seed + 80 }));
        P.inkAdd(S.stroke([{ x: cornerX, y: floorY }, V.to(cornerX, floorY, tFar * 0.55), V.to(cornerX, floorY, tFar)], { stroke: ink, width: 4.2, opacity: 0.88, amp: 3.2, over: 20, seed: seed + 82 }));
        // THE TWO DIAGONALS IN THE EMPTY UPPER RIGHT. These are the ceiling
        // junction, so they are real architecture — but on a large flat field
        // with nothing else in it they read as construction left in the drawing,
        // which the render-scale pass called correctly. A ceiling line earns its
        // place where it meets something; out in the open it is two lines across
        // nothing. Under hand-2 the near wall's junction stays (it terminates on
        // the corner, which explains it) and the receding one stops at 45% of the
        // run, tapering out instead of crossing the whole field.
        thin([{ x: -20, y: ceilY }, { x: cornerX, y: ceilY + 2 }], H2 ? 0.22 : 0.3, 3, seed + 84);
        if (H2) thin([{ x: cornerX, y: ceilY }, V.to(cornerX, ceilY, tFar * 0.28), V.to(cornerX, ceilY, tFar * 0.45)], 0.14, 2.4, seed + 86);
        else thin([{ x: cornerX, y: ceilY }, V.to(cornerX, ceilY, tFar * 0.6), V.to(cornerX, ceilY, tFar)], 0.3, 3, seed + 86);
        // THE CORNER. Near camera, so it is the heaviest vertical in frame.
        P.inkAdd(S.stroke([{ x: cornerX, y: ceilY - 4 }, { x: cornerX + q(3), y: (ceilY + floorY) / 2 }, { x: cornerX, y: floorY + 4 }], { stroke: ink, width: 5.4, opacity: 0.9, amp: 3, over: 18, seed: seed + 88 }));
        // skirting, on both walls, following their own junction
        mass(rect(-20, floorY - q(24), cornerX + 20, q(24)), wood, 0.42, seed + 90, -4, 3, { depth: 0.6 });
        mass([{ x: cornerX, y: floorY - q(24) }, V.to(cornerX, floorY - q(24), tFar), V.to(cornerX, floorY, tFar), { x: cornerX, y: floorY }], wood, 0.4, seed + 94, -70, 3, { depth: 0.4 });
        return { floorAt: jF, ceilAt: jC };
      },

      // A desk running INTO the frame. The back edge lies along the receding wall
      // and the front edge is a line parallel to it, so both converge on the same
      // point; the apron under the front edge narrows with depth, which gives the
      // plate a second set of converging lines under the first.
      //
      // Returns at(t) so the branch can stand a prop on the surface at a stated
      // depth and get back both the point and the scale it should be drawn at —
      // props on a receding desk have to shrink or the desk stops receding.
      deskInto: function (V, backX, topY, offX, offY, deskH, tNear, tFar, seed) {
        const bN = V.to(backX, topY, tNear), bF = V.to(backX, topY, tFar);
        const fN = V.to(backX + offX, topY + offY, tNear), fF = V.to(backX + offX, topY + offY, tFar);
        const sN = V.s(tNear), sF = V.s(tFar);
        const apN = { x: fN.x, y: fN.y + deskH * sN }, apF = { x: fF.x, y: fF.y + deskH * sF };
        // the recess under it, drawn first: the darkest thing in the frame
        deep([fN, fF, apF, apN], seed + 200, 0.6, 0, "top");
        // TOP SURFACE. Left as ground — it is the plane the lamp falls on — with
        // only enough weight at the far end to say it is going away.
        mass([bN, bF, fF, fN], wood, 0.14, seed, -70, 3.4, { depth: PLANE.desk, weight: 0.35 });
        // the far half again, heavier: the surface fades out rather than ending
        mass([V.to(backX, topY, (tNear + tFar) / 2), bF, fF, V.to(backX + offX, topY + offY, (tNear + tFar) / 2)], wood, 0.22, seed + 4, -70, 2.4, { depth: 0.42, mask: false });
        // FRONT APRON. Banded in depth so its weight falls off along its own
        // length, but the bands are HATCH ONLY with a single outline over the whole
        // apron at the end. Drawn as four masses it came out as four panels with
        // seams between them — a sideboard, not a desk.
        solid([fN, fF, apF, apN], paper, 1, seed + 8);
        for (let i = 0; i < 4; i++) {
          const ta = tNear + (tFar - tNear) * (i / 4), tb = tNear + (tFar - tNear) * ((i + 1) / 4);
          const a = V.to(backX + offX, topY + offY, ta), b = V.to(backX + offX, topY + offY, tb);
          const band = [a, b, { x: b.x, y: b.y + deskH * V.s(tb) }, { x: a.x, y: a.y + deskH * V.s(ta) }];
          const c = centroid(band), lum = lumAt(c.x, c.y);
          P.inkAdd(S.hatch(band, { color: wood, opacity: clamp01((0.62 - i * 0.07) * (1.18 - lum * 0.5)), gap: 7.5, width: 12, angle: -4, over: 14, seed: seed + 10 + i * 4 }));
          P.inkAdd(S.hatch(band, { color: ink, opacity: (0.1 + 0.09 * (1 - lum)) * (0.8 - i * 0.16), gap: 9, width: 13, angle: 2, over: 10, seed: seed + 30 + i * 4 }));
        }
        P.inkAdd(S.outline([fN, fF, apF, apN], { stroke: ink, width: 4.6, opacity: 0.92, amp: 3, over: 14, seed: seed + 38 }));
        // the front edge itself: one heavy converging line, near end to far end
        P.inkAdd(S.stroke([fN, { x: (fN.x + fF.x) / 2, y: (fN.y + fF.y) / 2 }, fF], { stroke: ink, width: 5.6, opacity: 0.92, amp: 2.6, over: 16, seed: seed + 40 }));
        // legs at both ends, so the desk has a near end and a far end
        [[tNear, sN], [tFar, sF]].forEach(function (pr, i) {
          const t = pr[0], s = pr[1];
          const lp = V.to(backX + offX * 0.86, topY + offY * 0.86, t);
          mass([{ x: lp.x - q(9) * s, y: lp.y + deskH * s * 0.1 }, { x: lp.x + q(9) * s, y: lp.y + deskH * s * 0.1 },
            { x: lp.x + q(8) * s, y: lp.y + deskH * s * 1.6 }, { x: lp.x - q(8) * s, y: lp.y + deskH * s * 1.6 }],
            wood, 0.46, seed + 60 + i * 6, -74, 4, { depth: 0.7 - i * 0.34, weight: 0.7 });
          contact(lp.x, lp.y + deskH * s * 1.6, q(14) * s, seed + 70 + i);
        });
        return {
          at: function (t, across) {
            const a = across == null ? 0.5 : across;
            const pt = V.to(backX + offX * a, topY + offY * a, t);
            return { x: pt.x, y: pt.y, s: V.s(t) };
          },
        };
      },

      // Looking UP. The ceiling is in frame, its joints converge on a point above
      // the top edge, and the wall's verticals lean in with them. Nothing else in
      // this library has a ceiling in it — at eye level there is nothing above the
      // wall to draw, which is precisely why every plate reads as the same shot.
      ceilingUp: function (junctionY, seed) {
        const vx = W * 0.5, vy = -HH * 0.85;
        P.colourAdd(S.hatch(rect(-20, -20, W + 40, junctionY + 22), { color: wood, opacity: 0.34, gap: 9, width: 14, angle: -70, over: 24, seed: seed }));
        P.colourAdd(S.hatch(rect(-20, -20, W + 40, junctionY * 0.5), { color: wood, opacity: 0.22, gap: 10, width: 15, angle: -70, over: 22, seed: seed + 2 }));
        // TILE JOINTS, converging on a point above the top edge. These are the only
        // lines in the pack that say "up", so they are drawn to be SEEN — at 0.2
        // opacity they were invisible and the ceiling read as a soffit.
        for (let i = 0; i < 6; i++) {
          const bx = -W * 0.14 + W * 0.26 * i, t = 0.8;
          thin([{ x: bx, y: junctionY }, { x: bx + (vx - bx) * t, y: junctionY + (vy - junctionY) * t }], 0.4, 3.4, seed + 10 + i);
        }
        // the ceiling/wall junction: seen from below it bows, it does not rule
        P.inkAdd(S.stroke([{ x: -20, y: junctionY - q(14) }, { x: W * 0.5, y: junctionY }, { x: W + 20, y: junctionY - q(18) }], { stroke: ink, width: 4.8, opacity: 0.9, amp: 3.4, over: 20, seed: seed + 30 }));
        // A strip light, because that is what is above a desk at three in the
        // morning and it is the one object only this camera can see. It is BIG: a
        // small one floating in the top band read as a canoe.
        const lx = W * 0.24, lw = W * 0.54, ly = junctionY * 0.30;
        mass([{ x: lx, y: ly }, { x: lx + lw, y: ly - q(16) }, { x: lx + lw * 0.93, y: ly + q(74) }, { x: lx + lw * 0.06, y: ly + q(86) }], wood, 0.5, seed + 40, -4, 4.6, { depth: 0.55, weight: 0.85 });
        // the tube: bare ground, because it is a source
        mass([{ x: lx + lw * 0.07, y: ly + q(18) }, { x: lx + lw * 0.93, y: ly + q(4) }, { x: lx + lw * 0.9, y: ly + q(50) }, { x: lx + lw * 0.09, y: ly + q(64) }], paper, 0.1, seed + 44, -4, 2.6, { flat: true });
        [0.22, 0.78].forEach(function (t, i) {
          thin([{ x: lx + lw * t, y: ly + q(78) }, { x: lx + lw * t + q(8), y: junctionY - q(16) }], 0.34, 3, seed + 50 + i);
        });
      },

      // The near edge of the desk, seen from desk height. The surface is a
      // TRAPEZOID — its far edge is shorter than its near one, because it is
      // further away — and the two side edges are the only converging lines this
      // camera can show. Drawn as a horizontal band (the first pass) it read as a
      // dado rail with monitors hung above it: a wall, not a desk.
      deskEdgeNear: function (farY, nearY, inset, seed) {
        const xl = -20, xr = W + 20, fl = inset, fr = W - inset;
        const surf = [{ x: fl, y: farY }, { x: fr, y: farY - q(4) }, { x: xr, y: nearY }, { x: xl, y: nearY + q(8) }];
        deep(rect(xl, nearY, xr - xl, HH - nearY + 20), seed + 300, 0.34, 0, "bottom");
        mass(surf, wood, 0.2, seed, -4, 3.6, { depth: 0.8, weight: 0.4 });
        thin([{ x: xl, y: nearY + q(8) }, { x: fl, y: farY }], 0.55, 4.4, seed + 4);
        thin([{ x: xr, y: nearY }, { x: fr, y: farY - q(4) }], 0.55, 4.4, seed + 6);
        // the front edge: nearest thing in frame, heaviest line on the plate
        P.inkAdd(S.stroke([{ x: xl, y: nearY + q(8) }, { x: W * 0.5, y: nearY + q(2) }, { x: xr, y: nearY }], { stroke: ink, width: 7, opacity: 0.94, amp: 3, over: 22, seed: seed + 10 }));
        mass(rect(xl, nearY + q(8), xr - xl, HH - nearY), wood, 0.66, seed + 14, -4, 4.6, { depth: PLANE.near, weight: 1 });
        for (let i = 0; i < 4; i++) thin([{ x: W * (0.08 + i * 0.28), y: nearY + q(30) }, { x: W * (0.1 + i * 0.28), y: HH + 20 }], 0.16, 2.6, seed + 20 + i);
        return { farL: fl, farR: fr, farW: fr - fl };
      },

      // Looking DOWN at the desk surface, and nothing else: no horizon, no floor
      // line, no wall. The plane fills the frame, so the perspective is in the
      // objects on it — rectangles on a surface tilted away from camera converge
      // toward a point well below the frame.
      deskPlan: function (V, seed) {
        // The surface is hatched CELL BY CELL from lumAt rather than at one flat
        // opacity, so the lamp still reads as an absence of tone in one corner.
        // Same rule as everywhere else in this room — light removes hatch — and on
        // a plate that is nothing but one surface it is the only thing modelling
        // it. A single opacity over the whole frame made the desk a flat field
        // with objects sitting on top of nothing.
        for (let r = 0; r < 5; r++) for (let c = 0; c < 5; c++) {
          const cw = (W + 40) / 5, ch = (HH + 40) / 5, x0 = -20 + cw * c, y0 = -20 + ch * r;
          const op = clamp01(0.3 * (1 - lumAt(x0 + cw * 0.5, y0 + ch * 0.5)));
          if (op > 0.02) P.colourAdd(S.hatch(rect(x0, y0, cw + 2, ch + 2), { color: wood, opacity: op, gap: 11, width: 16, angle: -84, over: 26, seed: seed + r * 7 + c }));
        }
        // grain, running the length of the desk and converging with everything else
        for (let i = 0; i < 9; i++) {
          const bx = -W * 0.1 + W * 0.15 * i;
          const end = V.to(bx, -20, 0.3);
          thin([{ x: bx, y: -20 }, { x: end.x, y: (end.y + HH) * 0.5 }, { x: V.to(bx, -20, 0.5).x, y: HH + 20 }], 0.1, 2.4, seed + 10 + i);
        }
        // the far edge of the desk, top of frame — the one straight line, and the
        // only thing that says which way is away
        thin([{ x: -20, y: HH * 0.06 }, { x: W + 20, y: HH * 0.05 }], 0.3, 3.4, seed + 40);
        return {
          // A rectangle lying ON the desk. Its far edge is NARROWER than its near
          // one, and its line weight comes from how far down the frame it sits —
          // on a plate with no horizon those two are the only cues saying which
          // way is away, so both are stated rather than implied.
          sheet: function (cx2, cy2, w2, h2, rot, tone, sd) {
            const conv = 0.9;
            const co = Math.cos(rot), si = Math.sin(rot);
            const poly = [[-w2 / 2 * conv, -h2 / 2], [w2 / 2 * conv, -h2 / 2], [w2 / 2, h2 / 2], [-w2 / 2, h2 / 2]]
              .map(function (d) { return { x: cx2 + d[0] * co - d[1] * si, y: cy2 + d[0] * si + d[1] * co }; });
            // A sheet lying on a desk casts a thin, tight dark down ONE side. Without
            // it the paper and the desk are the same plane and the sheet reads as a
            // hole in the surface rather than as an object on it.
            deep([poly[3], poly[2], { x: poly[2].x + q(10), y: poly[2].y + q(14) }, { x: poly[3].x + q(8), y: poly[3].y + q(14) }], sd + 400, 0.5, 0, "top");
            mass(poly, tone || paper, 0.84, sd, -3, 3.2, { flat: true, depth: 0.3 + clamp01(cy2 / HH) * 0.55 });
            return poly;
          },
        };
      },

      // A mug from above is a RING, not a cylinder — the one prop that only this
      // camera can draw, and the reason the high angle is worth a plate.
      planMug: function (x, y, r, seed) {
        // §1.3 — registered like any other mug. It was missed because a plan-view
        // mug is drawn by a different call than an elevation one, which left
        // high-desk-down as one of three rooms with nothing alive in it.
        AMB.mugs.push({ x: x, top: y - r * 0.2, r: r, seed: seed });
        mass(ellipse(x, y, r, r * 0.97, 20, 0.03, seed), wood, 0.5, seed, -74, 4.2, { depth: 0.72, weight: 0.7 });
        deep(ellipse(x, y, r * 0.78, r * 0.76, 18, 0.04, seed + 4), seed + 4, 0.72, 3, "top");
        P.inkAdd(S.outline(ellipse(x, y, r * 0.78, r * 0.76, 18, 0.04, seed + 6), { stroke: ink, width: 3.4, opacity: 0.82, amp: 1.8, over: 7, seed: seed + 7 }));
        // the handle, seen flat
        P.inkAdd(S.stroke([{ x: x + r * 0.96, y: y - r * 0.24 }, { x: x + r * 1.5, y: y }, { x: x + r * 0.96, y: y + r * 0.24 }], { stroke: ink, width: 5, opacity: 0.9, amp: 2, over: 6, seed: seed + 10 }));
      },
      // A keyboard from above is the only view where it is actually a grid, so the
      // keys are drawn as KEYS — small quads with gaps — not as short strokes. As
      // strokes the whole slab came out as corduroy.
      planKeyboard: function (x, y, w2, rot, seed) {
        const h2 = w2 * 0.36, co = Math.cos(rot), si = Math.sin(rot);
        const pt = function (dx, dy) { return { x: x + dx * co - dy * si, y: y + dx * si + dy * co }; };
        const poly = [pt(-w2 / 2 * 0.96, -h2 / 2), pt(w2 / 2 * 0.96, -h2 / 2), pt(w2 / 2, h2 / 2), pt(-w2 / 2, h2 / 2)];
        // the well the keys sit in is one of the frame's real darks
        mass(poly, wood, 0.5, seed, -8, 4.4, { depth: 0.72, weight: 1 });
        deep([pt(-w2 * 0.45, -h2 * 0.42), pt(w2 * 0.45, -h2 * 0.42), pt(w2 * 0.45, h2 * 0.42), pt(-w2 * 0.45, h2 * 0.42)], seed + 200, 0.44, 0, "top");
        const cols = 13, rows = 5, kw = (w2 * 0.9) / cols, kh = (h2 * 0.84) / rows;
        for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) {
          const dx = -w2 * 0.45 + kw * c + (r === rows - 1 && c > 2 && c < 10 ? 0 : 0);
          const dy = -h2 * 0.42 + kh * r;
          const wide = r === rows - 1 && c === 5;
          const kq = [pt(dx + kw * 0.1, dy + kh * 0.12), pt(dx + kw * (wide ? 4.2 : 0.9), dy + kh * 0.12),
            pt(dx + kw * (wide ? 4.2 : 0.9), dy + kh * 0.88), pt(dx + kw * 0.1, dy + kh * 0.88)];
          if (wide || !(r === rows - 1 && c > 5 && c < 10)) {
            P.inkAdd(S.hatch(kq, { color: paper, opacity: 0.34, gap: 7, width: 9, angle: -8, over: 4, seed: seed + r * 20 + c }));
            P.inkAdd(S.outline(kq, { stroke: ink, width: 2, opacity: 0.44, amp: 0.7, over: 3, seed: seed + 300 + r * 20 + c }));
          }
        }
      },
    };
  }

  // ---------------- §1 · THE TITLE'S OWN GROUND ----------------
  /* Chapter-opener titles are legible today because the wall behind them happens
     to be flat and pale. That is a property of the WALL, borrowed — not a
     property of the title. The rule keeping it true is undocumented and obeyed
     by accident: mass() suppresses every cast shadow whose base sits above 36%
     of frame height so "the title box stays on flat wall", and no angle puts a
     prop, a tone or a shadow behind that box. One toned wall, one dusk variant,
     one taped page moved up the wall, and the chapter opener loses its
     legibility silently — on the one plate where a chapter title reaches the
     screen at all.

     So the title carries its own ground. Three treatments, because this cannot
     be chosen from a description:

       card   an opaque drawn card, taped, with its own rim and its own cast.
              Paper on the wall. Contrast is GUARANTEED and identical on every
              wall, because nothing behind it reaches the type.
       scrim  no object and no edge: the wall goes quiet. Three feathered washes
              of the ground colour, frayed at the rim, so the room still reads
              through faintly. Keeps the plate a room; does NOT guarantee
              contrast, because what it cannot cover it can only dilute.
       slab   a heavy ink block with the title REVERSED OUT of it. The most
              robust of the three on any ground, and the largest change to what
              a chapter opener looks like — it is the one treatment that moves
              the type colour, which is why it publishes typeColour rather than
              leaving the renderer to infer it.

     THREE PROPERTIES EVERY TREATMENT HOLDS.

     1. THE TITLE SLOT DOES NOT MOVE. The panel is drawn AROUND the published
        box — same x, y, w, h on every plate, so nothing already composited
        against slots.title shifts by a pixel. What changes is what is behind it.

     2. IT IS PINNED. A ground is a slot underlay, and an underlay moving behind
        pinned type is the relative motion §1.5 ruled out — the same call field()
        makes on a data plate, for the same reason. Rooms are not gated, so
        without pin() this panel would breathe against dead-still type at the
        one size on the plate where it would be visible. What a mark is FOR wins
        over which family it landed in.

     3. IT COVERS THE WHOLE TYPE BLOCK, not just the title. Three angles set a
        caption directly under the title — desk-corner, corner-perspective and
        high-desk-down — and a panel behind the title with the caption hanging
        off its bottom edge onto bare wall is worse than no panel at all: the
        smaller type is the one that needs the ground more. So the panel spans
        the union of title and caption where the caption sits within one
        title-height of it.

     It draws into P.top, which is emitted after colour and ink, because the
     ground has to sit over whatever the room already put on that wall. That is
     the whole mechanism: nothing about the room art changes, and no angle needs
     a placement of its own. */
  const TITLE_GROUNDS = ["card", "scrim", "slab"];

  // The type block this ground has to cover. Title, plus a caption that belongs
  // to it — measured off the published boxes, never authored per angle.
  function typeBlockOf(P) {
    const t = P.slots.title;
    if (!t) return null;
    const c = P.slots.caption;
    const b = { x: t.x, y: t.y, w: t.w, h: t.h, joined: false };
    if (c && c.y >= t.y && c.y - (t.y + t.h) < t.h * 1.5) {
      const x0 = Math.min(t.x, c.x), y0 = Math.min(t.y, c.y);
      const x1 = Math.max(t.x + t.w, c.x + c.w), y1 = Math.max(t.y + t.h, c.y + c.h);
      b.x = x0; b.y = y0; b.w = x1 - x0; b.h = y1 - y0; b.joined = true;
    }
    return b;
  }

  function titleGround(P, treatment, k, seed) {
    if (!treatment) return null;
    if (TITLE_GROUNDS.indexOf(treatment) < 0) throw new Error("unknown titleGround " + treatment);
    const blk = typeBlockOf(P);
    if (!blk) return null;
    const p = P.pal, ink = p.structure;
    const q = function (n) { return n * (k || 1); };
    const padX = Math.max(q(26), blk.w * 0.055);
    const padY = Math.max(q(22), blk.h * 0.11);
    const m = q(12); // the panel never touches the plate edge
    const x0 = Math.max(m, blk.x - padX), y0 = Math.max(m, blk.y - padY);
    const x1 = Math.min(P.w - m, blk.x + blk.w + padX), y1 = Math.min(P.h - m, blk.y + blk.h + padY);
    const panel = { x: Math.round(x0), y: Math.round(y0), w: Math.round(x1 - x0), h: Math.round(y1 - y0) };
    const ring = function (g2) { return H.polyRect(panel.x - g2, panel.y - g2, panel.w + g2 * 2, panel.h + g2 * 2); };
    // An opaque area of colour with a drawn edge. Emitted directly rather than
    // through hatch(), because hatch()'s authored opacity is COVERAGE and gets
    // multiplied to solid — and the scrim's whole argument is the exact alpha.
    const wash = function (poly, colour, alpha, sd) {
      const pts = H.wobble(poly.concat([poly[0]]), { amp: q(2), over: 0, seed: sd, step: q(26) });
      P.topAdd(`<path d="${H.toPath(pts)}Z" fill="${colour}" fill-opacity="${H.num(alpha)}"/>`);
    };
    const out = {
      treatment: treatment,
      box: panel,
      typeBlock: { x: blk.x, y: blk.y, w: blk.w, h: blk.h, joinedCaption: blk.joined },
      slotsCovered: blk.joined ? ["title", "caption"] : ["title"],
      opaque: treatment !== "scrim",
      typeColour: treatment === "slab" ? "ground" : "structure",
      pinned: true,
      pinNote: "the ground is a slot underlay and emits the identical path at every boil index. An underlay breathing behind dead-still type is relative motion, which reads worse than either moving alone.",
    };
    H.pin(function () {
      if (treatment === "card") {
        // LIGHT is upper-left for the whole kit, so the cast goes down and right.
        // Two quads, the wider one fainter: a card stands a few millimetres off a
        // wall, so its shadow is tight and its penumbra is small.
        const off = Math.max(q(7), panel.w * 0.013);
        wash(H.polyRect(panel.x + off * 1.7, panel.y + off * 1.7, panel.w, panel.h), ink, 0.055, seed + 3);
        wash(H.polyRect(panel.x + off, panel.y + off, panel.w, panel.h), ink, 0.1, seed + 5);
        wash(ring(0), p.ground, 1, seed + 7);
        // the bloom rim: pigment pooling just inside the edge of a wash, value
        // only — the ground token multiplied down, no new colour
        const rim = H.polyRect(panel.x + q(9), panel.y + q(9), panel.w - q(18), panel.h - q(18));
        P.topAdd(H.stroke(rim.concat([rim[0]]), { stroke: H.darken(p.ground, 0.86), width: q(5), opacity: 0.5, amp: 1.2, over: 0, seed: seed + 11, silhouette: true }));
        P.topAdd(H.outline(ring(0), { stroke: ink, width: q(3.6), opacity: 0.92, amp: 3.2, over: q(12), seed: seed + 13 }));
        // Two pieces of tape across the top corners, crooked. The card is the
        // only thing in the frame that arrived after the room did.
        [[panel.x, -1], [panel.x + panel.w, 1]].forEach(function (c, i) {
          const tw = Math.max(q(46), panel.w * 0.075), th = q(26);
          const cx = c[0], cy = panel.y, d = c[1];
          const a = (i ? -0.42 : 0.42);
          const co = Math.cos(a), si = Math.sin(a);
          const pt = function (dx, dy) { return { x: cx + (dx * co - dy * si) * 1, y: cy + (dx * si + dy * co) }; };
          const tp = [pt(-tw * 0.5 * d, -th * 0.5), pt(tw * 0.5 * d, -th * 0.5), pt(tw * 0.5 * d, th * 0.5), pt(-tw * 0.5 * d, th * 0.5)];
          wash(tp, p.ground2, 0.62, seed + 21 + i * 4);
          P.topAdd(H.outline(tp, { stroke: ink, width: q(2), opacity: 0.34, amp: 1.6, over: q(4), seed: seed + 23 + i * 4 }));
        });
      } else if (treatment === "scrim") {
        // No object and no edge. Three washes, each smaller and stronger than the
        // last, so the boundary is a gradient rather than a line — and a fray of
        // short ground-coloured strokes across the outer rim, so where it stops
        // it frays instead of stopping.
        // The alphas are the treatment. Three layers multiply, so the middle
        // transmits 0.78 x 0.66 x 0.42 = 21.6% of whatever is behind it, the band
        // outside the panel transmits 51%, and the outermost 78%. The number that
        // matters is the first one: a fifth of the wall still reaches the type,
        // which is why this treatment IMPROVES the floor and cannot guarantee it.\n        wash(ring(padX * 0.95), p.ground, 0.22, seed + 31);
        wash(ring(padX * 0.45), p.ground, 0.34, seed + 33);
        wash(ring(0), p.ground, 0.58, seed + 35);
        const per = ring(padX * 0.95);
        for (let i = 0; i < 18; i++) {
          const t = i / 18, e = t * 4, sd = Math.floor(e), f = e - sd;
          const a = per[sd % 4], b = per[(sd + 1) % 4];
          const px = a.x + (b.x - a.x) * f, py = a.y + (b.y - a.y) * f;
          const ox = px - (panel.x + panel.w / 2), oy = py - (panel.y + panel.h / 2);
          const l = Math.hypot(ox, oy) || 1, len = q(30) + (i % 3) * q(12);
          P.topAdd(H.stroke([{ x: px - (ox / l) * len * 0.4, y: py - (oy / l) * len * 0.4 },
            { x: px + (ox / l) * len, y: py + (oy / l) * len }],
            { stroke: p.ground, width: q(13), opacity: 0.42, amp: 2.2, over: 0, seed: seed + 40 + i }));
        }
      } else {
        // slab: the type reverses out of it, so the block itself has to be the
        // darkest thing in the frame rather than a mid-tone with type over it.
        // 0.96 rather than 1: the room doctrine keeps the ground visible
        // everywhere in frame, and a fully opaque black rectangle reads as a hole
        // punched in the plate. What shows through at 4% is a texture, not a
        // shape — measured tonal range inside the box is 1.0 L against the
        // control's 70.9.
        wash(ring(0), ink, 0.96, seed + 51);
        // a torn terminating edge instead of a mechanical one. Biased INWARD: a
        // stroke that mostly sticks out reads as a peg, and the first render came
        // out looking stitched to the wall.
        const per = ring(0);
        for (let i = 0; i < 22; i++) {
          const t = i / 22, e = t * 4, sd = Math.floor(e), f = e - sd;
          const a = per[sd % 4], b = per[(sd + 1) % 4];
          const px = a.x + (b.x - a.x) * f, py = a.y + (b.y - a.y) * f;
          const ox = px - (panel.x + panel.w / 2), oy = py - (panel.y + panel.h / 2);
          const l = Math.hypot(ox, oy) || 1, len = q(9) + (i % 4) * q(4);
          P.topAdd(H.stroke([{ x: px - (ox / l) * len, y: py - (oy / l) * len },
            { x: px + (ox / l) * len * 0.16, y: py + (oy / l) * len * 0.16 }],
            { stroke: ink, width: q(8), opacity: 0.9, amp: 2.4, over: 0, seed: seed + 60 + i }));
        }
      }
    });
    return out;
  }

  function room(o) {
    const land = o.w > o.h, w = o.w, h = o.h, p = o.pal, angle = o.angle;
    const P = base(o, "room-" + angle, {
      title: { font: "Archivo Narrow", size: land ? 76 : 62, weight: 700, colour: "structure", tracking: "-.02em", maxLines: 3, maxCharsPerLine: land ? 22 : 16 },
      kicker: TR.kicker, caption: TR.caption,
    });
    P.meta.family = "room";
    P.meta.angle = angle;
    // the profile is bound by Plate() off the key's family, so this is just the
    // gate every other change in these packs uses
    const H2 = !!(H.profile && H.profile() === "hand-2");
    // FLOOR LINE, AND WHY IT IS NO LONGER THE SAME NUMBER ON EVERY PLATE.
    //
    // Eight angles all put it at 0.8h (0.7h portrait), which is another way of
    // saying eight cameras stood in the same place. The three angles added in
    // revision 05 are camera POSITIONS, so each states its own — and two of them
    // put the floor line off the bottom of the canvas, because a camera at desk
    // height and a camera looking down at the desk genuinely cannot see the
    // floor. It is still declared, because the anchor arithmetic is defined
    // against it; it is simply not in frame.
    const CAM = { "corner-perspective": 1, "low-desk-height": 1, "high-desk-down": 1 }[angle] ? angle : null;
    const floorY = angle === "low-desk-height" ? Math.round(h * 1.26)
      : angle === "high-desk-down" ? Math.round(h * 2.2)
      : angle === "corner-perspective" ? Math.round(h * (land ? 0.74 : 0.66))
      : Math.round(h * (land ? 0.8 : 0.7));
    P.meta.floorLineY = floorY;
    const k = land ? w / 1920 : w / 1080;
    const S = inkScale(k);
    const K = roomKit(P, p, k, { w: w, h: h, floorY: floorY });
    // The camera angles draw their own shell. shell() IS a flat elevation — a
    // horizontal floor line and a wall banded by height — which is precisely the
    // thing these three exist to stop doing.
    if (!CAM) K.shell(floorY, w, h, 801);

    /* §4.2 — TIME OF DAY, AS A VARIANT AXIS ON THE EXISTING ROOMS.

       The set is built for three in the morning: one warm desk lamp, one cold
       monitor, everything else falling away. A time-of-day variant is not a new
       room, it is that room at a different hour — so it is an argument to this
       author rather than eight more angles, and every prop, shadow and anchor
       stays exactly where it is.

       WHAT IT DRAWS: a tone on the wall above the floor line, and nothing else.
       Dusk warms and darkens the upper wall; day lifts it. Both are washes under
       everything the angle branch then draws, which is why no branch needs to
       know about it.

       AND THEY ARE EMITTED AS FILLS RATHER THAN THROUGH hatch(), which is the
       one real finding in this section. The first build called
       H.hatch(wall, {opacity: 0.34, …}) and the dusk plate came out BYTE-IDENTICAL
       to the night plate: two marks pushed onto the colour layer, zero bytes in
       the SVG. hatch2() — the hand-2 path, which every room draws through — treats
       the authored opacity as COVERAGE and only lays its wash when
       `op >= 0.4` (material) or the region is under 2600 units square; and it
       returns early for a `plane`, meaning any region over 5.5% of the plate.
       A low-alpha wash the size of a wall is both non-material AND a plane, so it
       drew nothing and said nothing. 0.42 would have worked and 0.34 silently did
       not.

       That is a trap for anything that wants a large area of faint tone, so the
       wash here is what titleGround() already uses for the same reason: a wobbled
       path with a real fill-opacity. The alpha is then the alpha.

       WHAT IT DOES NOT DRAW, stated rather than implied: the props' cast shadows
       still fall the way the lamp and the monitor put them. A real relight moves
       every shadow in the room, and that is not in this drop — so these variants
       read as the same room at a different hour, not as the same room lit from a
       different place. For a dusk plate that is close to true (the lamp is still
       the source); for `day` it is the honest limit of the change.

       AND IT IS WHY §1 COMES FIRST. A toned wall behind the title box is exactly
       the borrowed-legibility failure §1 measures — the chapter openers are
       legible today because that wall is flat and pale. So a non-night variant
       DECLARES that it needs a title ground, and until one is chosen these
       variants are not allowed in a chapter-opener template. The declaration is
       in the manifest rather than in a comment, so the kit gate can see it. */
    if (o.timeOfDay && o.timeOfDay !== "night") {
      const tod = o.timeOfDay;
      if (["dusk", "day"].indexOf(tod) < 0) throw new Error("unknown timeOfDay " + tod);
      // A wash: opaque area of colour with a hand edge, and a real alpha. See the
      // hatch2 note above for why this is not a hatch() call.
      const wash = function (poly, colour, alpha, sd) {
        const pts = H.wobble(poly.concat([poly[0]]), { amp: 3.2, over: 0, seed: sd, step: 44 });
        P.colourAdd(`<path d="${H.toPath(pts)}Z" fill="${colour}" fill-opacity="${H.num(alpha)}"/>`);
      };
      // The wall, and a band at the ceiling joint. The join between them is a
      // frayed run of strokes rather than an edge — a tone that stops on a line
      // is a painted stripe, and this is meant to be the light in the room.
      // (k, not the branch-local zoom: `u` is declared further down this author,
      // after the angle branches, and this wash runs before them.)
      const fray = function (y, colour, alpha, sd) {
        for (let i = 0; i < 26; i++) {
          const x = (w / 26) * i;
          P.colourAdd(H.stroke([{ x: x, y: y - k * 18 }, { x: x + w / 22, y: y + k * 26 }],
            { stroke: colour, width: k * 34, opacity: alpha, amp: 3, over: 0, seed: sd + i }));
        }
      };
      if (tod === "dusk") {
        // warm, and heaviest at the top: the light left in the room is coming in
        // low from outside, so the ceiling joint goes first.
        wash(H.polyRect(0, 0, w, floorY), p.ground2, 0.3, 1301);
        wash(H.polyRect(0, 0, w, floorY * 0.4), p.ground2, 0.26, 1303);
        fray(floorY * 0.4, p.ground2, 0.2, 1305);
      } else {
        // day: the wall lifts. The ground token at a real alpha over the surface,
        // so the paper grain still reads through it — grain is emitted after the
        // colour layer, which is what keeps this from killing the surface.
        wash(H.polyRect(0, 0, w, floorY), p.ground, 0.34, 1311);
        wash(H.polyRect(0, 0, w, floorY * 0.46), p.ground, 0.22, 1313);
        fray(floorY * 0.46, p.ground, 0.16, 1315);
      }
      P.meta.timeOfDay = {
        variant: tod,
        draws: tod === "dusk"
          ? "two warm washes on the wall, the upper one heavier, with a frayed join at the ceiling band — the light left in the room is coming in low from outside, so the joint goes first."
          : "two pale washes lifting the wall, frayed at the join. The paper grain is emitted after the colour layer, so it still reads through.",
        emittedAs: "fills with a real fill-opacity, NOT hatch(). hatch2 lays no wash below opacity 0.4 and returns early for any region over 5.5% of the plate, so a faint wall-sized hatch draws nothing and reports nothing — see the note in engine/plates.js. Anything else in this kit that wants a large faint tone has the same trap.",
        doesNotDraw: "THE RELIGHT. Every prop's cast shadow still falls where the lamp and the monitor put it. A real change of hour moves all of them, and that is not in this drop — so this reads as the same room at a different hour rather than the same room lit from a different place.",
        titleGroundRequired: true,
        titleGroundNote: "§1. This variant puts TONE behind the chapter-opener title box, which is exactly the borrowed legibility the flat pale wall was providing for free. Until engine/build.js TITLE_GROUND names a treatment, this plate must not be used in a chapter-opener template — the title has nothing of its own to sit on. Every other shot template is unaffected.",
      };
    }

    const zoom = k * (angle === "wide-tight" || angle === "desk-corner" ? 1.45 : 1);
    const u = function (n) { return n * zoom; };
    // §2 — THE DRAWN DESK DERIVES FROM THE ANCHOR, and that is what makes the
    // decision's closed form true in the ARTWORK rather than only in the
    // manifest. Substituting deskH = (1 - C) * anchorH into deskTop = floorY -
    // deskH, with anchorY = floorY - anchorH, gives
    //
    //   contact.y = deskTop = anchorY + C * anchorH
    //
    // which is the decision's equation exactly. The difference is only which
    // quantity moves to satisfy it: the manifest number, or the desk he leans
    // on. contact.y here is already Math.round(deskTop) — emitted by the code
    // that draws the desk, which is why the three 16:9 plates share 634 (same
    // floorY, same deskH, zoom 1) rather than having been copied once. Deriving
    // the manifest number from the rig would have overwritten a measurement with
    // a wish; this way the number stays measured AND becomes right, because the
    // desk is now drawn at the height his forearm reaches.
    //
    // anchorH is hoisted from the anchor block at the foot of this author — the
    // same expression, unchanged. It stays AUTHORED, so he is one consistent size
    // across the family and the "he is too small" composition change flows
    // straight through into a taller desk.
    const anchorH = angle === "low-desk-height" ? floorY - Math.round(h * 0.20) : Math.round(h * 0.52);
    // low-desk-height is the deliberate variant: its desk is SUPPOSED to be
    // somewhere else, so it keeps its authored height and stays out of this.
    const CC = contactC("leaning-on-desk");
    const deskH = (H2 && CC != null && angle !== "low-desk-height")
      ? Math.round((1 - CC) * anchorH)
      : u(230);
    const deskTop = floorY - deskH;
    // Where his hand, hip or elbow actually meets the furniture on this plate.
    // Set by the branches that HAVE furniture he can reach; left null by the ones
    // that are open floor, because inventing a contact point on a plate with
    // nothing to touch is worse than admitting there isn't one.
    let contact = null;

    if (angle === "wide" || angle === "wide-tight") {
      const tight = angle === "wide-tight";
      // the two sources, declared before anything is drawn so every prop is lit
      K.lights({ x: w * 0.25, y: deskTop - u(105), r: w * 0.44 }, { x: w * 0.41, y: deskTop - K.stackHeight(3) - u(140), r: w * 0.36 });
      K.windowNight(w * 0.46, floorY - u(740), u(300), u(330), 951);
      if (tight) {
        K.tapedPage(w * 0.06, floorY - u(520), u(150), u(200), 895);
        K.postits(w * 0.72, floorY - u(470), 3, 907);
      } else {
        K.calendar(w * 0.06, floorY - u(660), u(190), u(215), 891);
        K.clock(w * 0.3, floorY - u(600), u(52), 893);
        K.tapedPage(w * 0.37, floorY - u(650), u(150), u(200), 895);
      }
      K.underDesk(w * 0.19, deskTop + deskH * 0.16, w * 0.56, deskH * 0.84, 990);
      K.desk(w * 0.19, deskTop, w * 0.56, deskH, 811);
      K.chair(w * 0.785, floorY - u(6), u(180), 915);
      K.ringStain(w * 0.245, deskTop + u(8), u(32), 931);
      K.ringStain(w * 0.62, deskTop + u(5), u(26), 933);
      K.cableMess(w * 0.29, deskTop - u(30), u(250), u(150), 927);
      K.stack(w * 0.28, deskTop, u(140), 3, 871);
      K.monitor(w * 0.275, deskTop - K.stackHeight(3), u(275), u(190), 821);
      K.monitor(w * 0.545, deskTop, u(130), u(200), 831);
      K.keyboard(w * 0.315, deskTop - u(4), u(215), 841);
      // in front of the keyboard, overlapping it: a desk with one thing per
      // square foot is a shop shelf, not a desk somebody works at
      K.openReport(w * 0.40, deskTop + u(2), u(250), 869);
      K.mouse(w * 0.475, deskTop - u(2), u(52), 845);
      K.mug(w * 0.225, deskTop + u(4), u(26), 851, true);
      K.mug(w * 0.585, deskTop + u(6), u(24), 861);
      K.mug(w * 0.695, deskTop + u(2), u(21), 863);
      K.lamp(w * 0.205, deskTop, u(115), 865);
      K.medal(w * 0.725, deskTop + u(2), u(48), 911);
      K.postits(w * 0.365, deskTop - K.stackHeight(3) - u(46) - u(50), 2, 901);
      K.plant(w * 0.075, floorY - u(4), u(145), 881);
      if (!tight) K.binders(w * 0.82, floorY - u(430), u(175), u(115), 5, 917);
      K.printer(w * 0.83, floorY - u(4), u(205), u(145), 919);
      K.wastebasket(w * 0.15, floorY - u(4), u(120), 923);
      K.crumples(w * 0.205, floorY - u(8), u(30), 3, 935);
      K.cable(w * 0.42, deskTop + u(6), w * 0.47, floorY - u(8), 921);
      K.foreground("mug", -1, floorY + h * 0.06, 981);
      // The desk's near end, clear of the lamp and the first mug: this is where a
      // leaning hand actually lands on this plate. The anchor region has always
      // put him beside the desk; what it never said was WHERE the desk is under
      // him, so leaning-on-desk leaned on nothing.
      contact = { pose: "leaning-on-desk", surface: "desk top, left end", x: Math.round(w * 0.235), y: Math.round(deskTop) };
      P.slot("title", w * 0.35, 70, w * 0.3, land ? 250 : 300, { align: "left", role: "title", note: "chapter opener writes here; nothing else changes" });
    } else if (angle === "desk-front") {
      K.lights({ x: w * 0.18, y: deskTop - u(135), r: w * 0.42 }, { x: w * 0.42, y: deskTop - K.stackHeight(3) - u(170), r: w * 0.38 });
      K.windowNight(w * 0.42, floorY - u(760), u(320), u(340), 954);
      K.calendar(w * 0.76, floorY - u(700), u(210), u(240), 892);
      K.clock(w * 0.09, floorY - u(640), u(56), 894);
      K.tapedPage(w * 0.16, floorY - u(690), u(160), u(215), 896);
      K.postits(w * 0.79, floorY - u(430), 2, 904);
      K.underDesk(w * 0.1, deskTop + deskH * 0.16, w * 0.68, deskH * 0.84, 991);
      K.desk(w * 0.1, deskTop, w * 0.68, deskH, 812);
      K.ringStain(w * 0.235, deskTop + u(8), u(36), 936);
      K.cableMess(w * 0.31, deskTop - u(28), u(330), u(160), 938);
      K.stack(w * 0.3, deskTop, u(230), 3, 872);
      K.monitor(w * 0.295, deskTop - K.stackHeight(3), u(370), u(250), 822);
      K.monitor(w * 0.58, deskTop, u(170), u(255), 832);
      K.postits(w * 0.42, deskTop - K.stackHeight(3) - u(46) - u(50), 2, 902);
      K.keyboard(w * 0.34, deskTop - u(2), u(280), 842);
      K.openReport(w * 0.42, deskTop + u(2), u(300), 883);
      K.mouse(w * 0.505, deskTop - u(2), u(60), 846);
      K.mug(w * 0.22, deskTop + u(4), u(30), 852, true);
      K.mug(w * 0.62, deskTop + u(6), u(28), 856);
      K.mug(w * 0.735, deskTop + u(2), u(24), 858);
      K.lamp(w * 0.14, deskTop, u(148), 866);
      K.medal(w * 0.765, deskTop + u(2), u(54), 912);
      K.plant(w * 0.055, floorY - u(4), u(165), 882);
      K.printer(w * 0.86, floorY - u(4), u(205), u(148), 918);
      K.cable(w * 0.47, deskTop + u(6), w * 0.53, floorY - u(10), 922);
      K.stack(w * 0.17, floorY - u(4), u(150), 4, 879);
      K.foreground("chair", 1, floorY + h * 0.1, 982);
      contact = { pose: "leaning-on-desk", surface: "desk top, left end", x: Math.round(w * 0.185), y: Math.round(deskTop) };
      P.slot("title", w * 0.3, 56, w * 0.3, land ? 210 : 260, { align: "left", role: "title" });
    } else if (angle === "desk-corner") {
      const dc = deskTop + u(70);
      // no monitor in frame: the cold source is off-frame left, the lamp is in it
      K.lights({ x: w * 0.92, y: dc - u(190), r: w * 0.62 }, { x: -w * 0.12, y: dc - u(300), r: w * 0.8 });
      K.tapedPage(w * 0.12, dc - u(420), u(230), u(300), 893);
      K.postits(w * 0.46, dc - u(360), 3, 903);
      K.desk(-w * 0.08, dc, w * 1.0, deskH, 813);
      // wear, not data: a ring in the varnish where the mug always goes. This was
      // a red stain, which in this library is the colour of a loss — in the room
      // colour is light and material and never means anything.
      K.ringStain(w * 0.19, dc + u(8), u(46), 861);
      K.ringStain(w * 0.44, dc + u(4), u(34), 863);
      K.openReport(w * 0.36, dc + u(4), u(400), 877);
      K.stack(w * 0.72, dc + u(2), u(230), 5, 873);
      K.keyboard(-w * 0.02, dc + u(6), u(330), 843);
      K.mug(w * 0.24, dc + u(4), u(58), 853, true);
      K.mug(w * 0.325, dc + u(2), u(42), 857);
      K.pen(w * 0.62, dc - u(2), u(130), 859);
      K.lamp(w * 0.88, dc, u(200), 867);
      K.foreground("mug", -1, dc + h * 0.16, 983);
      P.slot("title", w * 0.5, 120, w * 0.42, land ? 260 : 320, { align: "left", role: "title" });
      P.slot("caption", w * 0.5, land ? 420 : 480, w * 0.42, 64, { align: "left", role: "caption" });
    } else if (angle === "from-behind-the-monitor") {
      // we are behind the screen, so the cold light rakes past its edges
      K.lights({ x: w * 0.97, y: deskTop - u(160), r: w * 0.6 }, { x: w * 0.33, y: deskTop - u(210), r: w * 0.5 });
      K.windowNight(w * 0.1, floorY - u(760), u(300), u(330), 957);
      K.desk(w * 0.04, deskTop + u(30), w * 0.92, deskH, 814);
      K.calendar(w * 0.74, floorY - u(690), u(185), u(210), 890);
      K.monitorBack(w * 0.08, deskTop + u(30), w * 0.5, u(310), 824);
      // the back of a monitor is where the cable mess actually lives
      K.cableMess(w * 0.14, deskTop + u(60), w * 0.36, u(230), 943);
      K.stack(w * 0.66, deskTop + u(30), u(170), 3, 874);
      K.mug(w * 0.8, deskTop + u(28), u(32), 854, true);
      K.pen(w * 0.62, deskTop + u(26), u(90), 856);
      K.mouse(w * 0.6, deskTop + u(28), u(56), 858);
      K.plant(w * 0.93, floorY - u(4), u(140), 884);
      K.wastebasket(w * 0.68, floorY - u(4), u(120), 888);
      K.crumples(w * 0.62, floorY - u(8), u(30), 3, 945);
      K.binders(w * 0.72, floorY - u(430), u(170), u(115), 5, 892);
      K.cable(w * 0.32, deskTop + u(110), w * 0.4, floorY - u(10), 926);
      K.foreground("stack", 1, floorY - u(4), 984);
      P.slot("title", w * 0.08, 100, w * 0.5, land ? 280 : 320, { align: "left", role: "title" });
    } else if (angle === "over-the-shoulder") {
      /* §4.3 — OVER THE SHOULDER. The one angle where he is IN the plate.

         Every other room is a set with a hole in it for a host cut-out. This one
         is the shot you get by standing behind him: his shoulder and the back of
         his head crop the near corner, and what we are looking at is the screen
         he is looking at. So it declares NO host anchor — compositing a cut-out
         onto it would put two of him in one frame — and the figure is drawn as a
         near silhouette by K.foreground("shoulder"), the one function in the kit
         whose job is a cropped near object.

         AND NO TITLE SLOT. A chapter opener needs a flat quiet ground for type;
         this frame is a man's shoulder, a lit screen and a desk. §1's own audit is
         the argument — sixteen of twenty-two existing openers already have ink
         under the title box, and this plate would be the worst of them by a wide
         margin. It is a cut-away, not an opener, and roles.json says so.

         What it is FOR: the moment the script reads something off the screen. The
         viewer is behind him looking at the same thing, which is a different
         relationship to the material than watching him talk about it. */
      K.lights({ x: w * 0.12, y: deskTop - u(150), r: w * 0.4 }, { x: w * 0.6, y: deskTop - u(240), r: w * 0.52 });
      K.desk(w * 0.02, deskTop, w * 0.96, deskH, 826);
      K.underDesk(w * 0.04, deskTop + deskH * 0.18, w * 0.92, deskH * 0.82, 994);
      // the monitor front-on and large: it is the subject of this shot
      K.monitor(w * 0.52, deskTop, u(300), u(210), 851);
      K.cable(w * 0.56, deskTop - u(60), w * 0.2, floorY - u(10), 928);
      K.keyboard(w * 0.44, deskTop - u(2), u(250), 847);
      K.mouse(w * 0.66, deskTop + u(26), u(56), 859);
      K.openReport(w * 0.2, deskTop + u(2), u(250), 966);
      K.mug(w * 0.34, deskTop + u(26), u(34), 855, true);
      K.ringStain(w * 0.4, deskTop + u(8), u(30), 963);
      K.stack(w * 0.78, deskTop + u(2), u(160), 2, 876);
      K.pen(w * 0.3, deskTop + u(24), u(86), 857);
      K.windowNight(w * 0.86, floorY - u(740), u(260), u(300), 958);
      K.plant(w * 0.95, floorY - u(4), u(130), 886);
      // HIM, in the near corner, cut by the frame edge. Drawn after the set so he
      // is in front of all of it.
      K.foreground("shoulder", -1, floorY - u(4), 988);
      P.slot("screen", w * 0.545, deskTop - u(258), u(258), u(150), {
        role: "screen", region: true,
        note: "the monitor's own panel, front-on. The one region on any room plate a compositor may fill with content — a chart, a filing page, a terminal. Fill it at LOW VALUE: this is a screen in a dark room, not a lightbox, and it must not out-contrast him in the corner.",
      });
    } else if (angle === "whiteboard-wall") {
      K.lights({ x: w * 0.19, y: deskTop - u(130), r: w * 0.46 }, { x: w * 0.72, y: deskTop - u(120), r: w * 0.36 });
      K.whiteboard(w * (land ? 0.1 : 0.07), h * 0.11, w * (land ? 0.52 : 0.86), h * (land ? 0.42 : 0.3), 815);
      K.calendar(w * 0.72, h * 0.13, u(180), u(210), 898);
      K.underDesk(w * 0.08, deskTop + deskH * 0.16, w * 0.84, deskH * 0.84, 992);
      K.desk(w * 0.08, deskTop, w * 0.84, deskH, 825);
      K.ringStain(w * 0.2, deskTop + u(8), u(32), 962);
      K.monitor(w * 0.66, deskTop, u(230), u(165), 849);
      K.keyboard(w * 0.34, deskTop - u(2), u(230), 848);
      K.openReport(w * 0.4, deskTop + u(2), u(240), 964);
      K.mug(w * 0.18, deskTop + u(4), u(30), 855, true);
      K.mug(w * 0.28, deskTop + u(2), u(24), 859);
      K.lamp(w * 0.15, deskTop, u(132), 966);
      K.stack(w * 0.7, deskTop, u(170), 3, 875);
      K.chair(w * 0.22, floorY - u(6), u(185), 913);
      K.plant(w * 0.94, floorY - u(4), u(140), 885);
      K.foreground("chair", -1, floorY + h * 0.08, 985);
      contact = { pose: "leaning-on-desk", surface: "desk top, left end", x: Math.round(w * 0.115), y: Math.round(deskTop) };
      P.slot("title", w * (land ? 0.66 : 0.08), h * (land ? 0.58 : 0.52), w * (land ? 0.28 : 0.5), 300, { align: "left", role: "title" });
    } else if (angle === "printer-corner") {
      // both sources are off-frame here: warm from the desk behind camera-right,
      // cold raking in from the doorway on the left
      K.lights({ x: w * 1.08, y: floorY - u(520), r: w * 0.7 }, { x: -w * 0.06, y: floorY - u(430), r: w * 0.62 });
      K.windowNight(w * 0.68, floorY - u(720), u(280), u(300), 968);
      K.tapedPage(w * 0.12, floorY - u(660), u(170), u(220), 899);
      K.binders(w * 0.56, floorY - u(430), u(220), u(140), 6, 907);
      K.mass(K.rect(w * 0.1, floorY - u(210), u(430), u(210)), p.ground2, 0.44, 909, -76);
      K.printer(w * 0.14, floorY - u(210), u(360), u(230), 816);
      K.stack(w * 0.58, floorY - u(4), u(220), 5, 876);
      K.stack(w * 0.72, floorY - u(4), u(200), 3, 878);
      K.plant(w * 0.88, floorY - u(4), u(175), 886);
      K.mug(w * 0.27, floorY - u(214), u(32), 869, true);
      K.wastebasket(w * 0.44, floorY - u(4), u(130), 889);
      K.crumples(w * 0.5, floorY - u(8), u(32), 5, 970);
      K.foreground("stack", -1, floorY - u(4), 986);
      P.slot("title", w * (land ? 0.54 : 0.08), 120, w * (land ? 0.38 : 0.6), land ? 300 : 320, { align: "left", role: "title" });
    } else if (angle === "corner-perspective") {
      // THE ONE ANGLE WITH A CAMERA IN IT.
      //
      // A visible wall corner, a desk running away from the viewer, floor boards
      // and a ceiling joint converging on the same point. Every other plate in the
      // family is a flat elevation, and this is the plate that makes the others
      // read as a room when a cut lands on them: once the eye has been shown the
      // space once, it carries that reading into the elevations.
      const ceilY = h * (land ? 0.10 : 0.14);
      const cornerX = w * (land ? 0.30 : 0.26);
      const V = K.vanish(w * (land ? 0.70 : 0.78), h * (land ? 0.46 : 0.44));
      const tFar = 0.78;
      // §2 — the receding desk takes the same derivation as the elevations, so
      // the ONE camera with perspective in it is not the one plate where the
      // furniture disagrees with the man.
      const deskTopY = (H2 && CC != null)
        ? floorY - Math.round((1 - CC) * anchorH)
        : floorY - h * (land ? 0.22 : 0.17);
      const backX = cornerX + w * 0.02, offX = -w * 0.09, offY = h * (land ? 0.19 : 0.14);
      // Both sources sit at a DEPTH now, not just at an x: the lamp is a third of
      // the way down the receding desk and the monitor is further along it, so the
      // falloff runs into the frame instead of across it.
      const lampP = V.to(backX + offX, deskTopY + offY * 0.5, 0.20);
      const monP = V.to(backX, deskTopY, 0.44);
      K.lights({ x: lampP.x, y: lampP.y - h * 0.08, r: w * 0.44 }, { x: monP.x, y: monP.y - h * 0.06, r: w * 0.34 });
      K.cornerRoom(V, cornerX, ceilY, floorY, tFar, 820);
      // The frontal wall carries the flat furniture: it is the one plane in this
      // frame where an axis-aligned rectangle is the correct drawing.
      K.whiteboard(w * 0.02, h * (land ? 0.15 : 0.17), cornerX - w * 0.07, h * (land ? 0.30 : 0.22), 826);
      K.clock(cornerX - w * 0.045, h * (land ? 0.55 : 0.47), u(48), 893);
      // And the receding wall carries its page as a CONVERGING quad. An
      // axis-aligned rect on a wall that is running away is the exact tell that
      // there is no camera, so it is drawn in the same perspective as the wall.
      [[0.14, 0.30], [0.42, 0.19]].forEach(function (pr, i) {
        const t0 = pr[0], sz = pr[1], wy = h * (land ? 0.20 : 0.24), wh = h * (land ? 0.17 : 0.13);
        K.mass([V.to(cornerX, wy, t0), V.to(cornerX, wy, t0 + sz * 0.34),
          V.to(cornerX, wy + wh, t0 + sz * 0.34), V.to(cornerX, wy + wh, t0)],
          p.ground, 0.84, 830 + i * 6, -3, 3.2, { depth: 0.42 - i * 0.16 });
      });
      const D = K.deskInto(V, backX, deskTopY, offX, offY, h * (land ? 0.20 : 0.15), 0.02, 0.62, 840);
      // Props DOWN the desk, each shrinking with its own depth. A prop that does
      // not shrink stops the desk receding all by itself.
      const far = D.at(0.46, 0.25), mid = D.at(0.30, 0.5), near = D.at(0.10, 0.6), edge = D.at(0.02, 0.78);
      K.stack(far.x, far.y, u(190) * far.s, 4, 872);
      K.cableMess(mid.x - u(70) * mid.s, mid.y - u(24) * mid.s, u(210) * mid.s, u(140) * mid.s, 927);
      K.monitor(mid.x - u(160) * mid.s, mid.y, u(310) * mid.s, u(205) * mid.s, 822);
      K.postits(mid.x + u(130) * mid.s, mid.y - u(240) * mid.s, 2, 902);
      K.lamp(near.x - u(260) * near.s, near.y - u(4), u(140) * near.s, 865);
      K.keyboard(near.x - u(110) * near.s, near.y, u(240) * near.s, 842);
      K.openReport(near.x + u(150) * near.s, near.y + u(6) * near.s, u(230) * near.s, 869);
      K.ringStain(edge.x - u(70) * edge.s, edge.y + u(8), u(36) * edge.s, 931);
      K.mug(edge.x + u(80) * edge.s, edge.y + u(10), u(32) * edge.s, 851, true);
      // the floor is a real plane on this plate, so things stand at two depths on it
      K.plant(w * 0.055, floorY - u(4), u(150), 881);
      K.wastebasket(w * 0.155, floorY + h * (land ? 0.11 : 0.09), u(140), 923);
      K.crumples(w * 0.235, floorY + h * (land ? 0.14 : 0.11), u(34), 3, 935);
      // The right of the frame is the floor opening toward the vanishing point, and
      // it was empty: a receding plane with nothing standing on it reads as a
      // backdrop again. Two objects at two DEPTHS is what makes it a floor.
      const fp1 = V.to(cornerX + w * 0.34, floorY + h * 0.05, 0.20);
      const fp2 = V.to(cornerX + w * 0.46, floorY + h * 0.02, 0.44);
      K.printer(fp1.x, fp1.y, u(280) * V.s(0.20), u(200) * V.s(0.20), 919);
      K.stack(fp2.x, fp2.y, u(210) * V.s(0.44), 5, 876);
      // NO CROPPED FOREGROUND OBJECT ON THIS PLATE, and that is the point.
      // foreground() exists because the eight elevations laid every prop along one
      // horizontal line and had no depth without it. This plate has depth from the
      // geometry, and the near mug at this size read as a bin standing in the
      // middle of the floor — the darkest thing in frame, sitting on nothing, next
      // to the one part of the drawing worth looking at.
      // AND THE CONTACT POINT MOVES ALONG THE DESK INSTEAD OF THE DESK MOVING.
      // On an elevation the desk top is one height, so deriving the height is the
      // whole fix. Here the desk RECEDES: its surface passes through a range of
      // screen heights, so there is a point on it that is already at his forearm
      // height, and the honest contact is that point rather than the near corner.
      // This is why corner-perspective was the one plate still at +412 after the
      // elevations came into line — its contact was pinned to the near end by
      // construction, and the near end is the lowest part of the surface.
      const cp = (function () {
        if (!(H2 && CC != null)) return { x: edge.x, y: edge.y, s: edge.s };
        const want = (floorY - anchorH) + CC * anchorH;
        // TWO parameters, not one. D.at(t, v) takes a depth t down the desk AND a
        // lateral v across it, and the surface height varies with both — so a
        // search over t alone at a fixed v = 0.78 can only ever reach the band of
        // heights that one lateral line passes through. That is why the first cut
        // came down to +60 and stopped: the point it wanted was further back
        // across the surface, not further along it.
        // Coarse sweep, then two refinements around the best cell. A single pass
        // at grid resolution leaves a residual the size of the grid — which is
        // how this plate sat at +3.6 and +15.5 while every elevation was inside
        // half a unit. The bar is one unit, so the search has to beat one unit.
        let bt = 0.02, bv = 0.78, bd = Infinity;
        const sweep = function (t0, t1, v0, v1, steps) {
          const dt = (t1 - t0) / steps, dv = (v1 - v0) / steps;
          for (let i = 0; i <= steps; i++) {
            for (let j = 0; j <= steps; j++) {
              const t = t0 + dt * i, v = v0 + dv * j;
              const q = D.at(t, v), dd = Math.abs(q.y - want);
              if (dd < bd) { bd = dd; bt = t; bv = v; }
            }
          }
          return { dt: dt, dv: dv };
        };
        let g = sweep(0.02, 0.66, 0.02, 0.98, 48);
        g = sweep(bt - g.dt, bt + g.dt, bv - g.dv, bv + g.dv, 16);
        sweep(bt - g.dt, bt + g.dt, bv - g.dv, bv + g.dv, 16);
        return D.at(bt, bv);
      })();
      contact = { pose: "leaning-on-desk", surface: "desk top, at forearm height", x: Math.round(cp.x - u(150) * cp.s), y: Math.round(cp.y) };
      P.slot("title", w * (land ? 0.035 : 0.05), h * (land ? 0.48 : 0.42), w * (land ? 0.24 : 0.4), land ? 210 : 250, { align: "left", role: "title" });
      P.slot("caption", w * (land ? 0.035 : 0.05), h * (land ? 0.68 : 0.60), w * (land ? 0.22 : 0.35), 64, { align: "left", role: "caption" });
    } else if (angle === "low-desk-height") {
      // CAMERA AT DESK HEIGHT, LOOKING UP.
      //
      // The desk edge cuts across the foreground, the ceiling exists, and there is
      // no floor in frame at all. He is ABOVE the lens instead of standing in the
      // middle of it, which is the shot the confession and the turn actually need.
      const farY = h * (land ? 0.62 : 0.58), nearY = h * (land ? 0.86 : 0.80);
      const ceilJ = h * (land ? 0.22 : 0.26);
      K.lights({ x: w * 0.22, y: farY - h * 0.10, r: w * 0.50 }, { x: w * 0.62, y: farY - h * 0.20, r: w * 0.40 });
      // The wall is lightest at the bottom where the desk lamp reaches and
      // heaviest at the top: looking up is looking away from the only light in the
      // room, which is the opposite gradient to every other plate in the family.
      for (let i = 0; i < 5; i++) {
        const bh = (farY - ceilJ) / 5, y0 = ceilJ + bh * i;
        P.colourAdd(S.hatch(K.rect(-20, y0, w + 40, bh + 2), { color: p.ground2, opacity: 0.25 - i * 0.045, gap: 10 + i * 0.4, width: 15, angle: -3, over: 26, seed: 861 + i }));
      }
      K.ceilingUp(ceilJ, 870);
      // The desk is drawn BEFORE the props that stand on it, because the surface is
      // a trapezoid now and the monitors are placed against its inset far edge.
      const DE = K.deskEdgeNear(farY, nearY, w * (land ? 0.13 : 0.09), 812);
      // wall furniture hangs HIGH from down here: the calendar is above the lens
      // rather than beside it, which is most of why this reads as a low angle
      K.calendar(w * 0.06, ceilJ + h * (land ? 0.04 : 0.03), u(210), u(240), 891);
      K.tapedPage(w * 0.29, ceilJ + h * (land ? 0.02 : 0.015), u(165), u(220), 895);
      K.binders(w * 0.80, ceilJ + h * (land ? 0.22 : 0.18), u(195), u(130), 5, 917);
      // The monitors are BIG and stand on the desk's FAR edge, inset from the frame:
      // from desk height a screen towers, and the first pass had them at
      // picture-frame size floating mid-wall, which is a wall elevation with
      // monitors hung on it.
      K.monitor(DE.farL + DE.farW * 0.40, farY + u(30), u(560), u(400), 821);
      K.monitor(DE.farL + DE.farW * 0.02, farY + u(38), u(300), u(420), 831);
      K.stack(DE.farL + DE.farW * 0.30, farY + u(34), u(230), 3, 871);
      K.postits(DE.farL + DE.farW * 0.36, farY - u(150), 2, 901);
      K.cableMess(DE.farL + DE.farW * 0.12, farY - u(30), u(240), u(150), 927);
      // The props on the near surface are cropped by its front edge, and THAT is
      // this plate's foreground crop — it does not also need a near mug pasted into
      // a corner. The desk edge cutting across the bottom is the depth cue the
      // whole camera position is built on.
      K.keyboard(w * 0.30, nearY + u(24), u(330), 842);
      K.openReport(w * 0.55, nearY + u(30), u(330), 869);
      K.mug(w * 0.13, nearY + u(58), u(86), 851, true);
      K.ringStain(w * 0.45, nearY + u(30), u(64), 931);
      K.pen(w * 0.84, nearY + u(16), u(190), 859);
      contact = { pose: "leaning-on-desk", surface: "desk top, far edge", x: Math.round(w * 0.42), y: Math.round(farY + u(8)) };
      P.slot("title", w * (land ? 0.42 : 0.06), ceilJ + h * (land ? 0.03 : 0.03), w * (land ? 0.32 : 0.5), land ? 200 : 240, { align: "left", role: "title" });
    } else if (angle === "high-desk-down") {
      // CAMERA ABOVE THE DESK, LOOKING DOWN AT THE SURFACE.
      //
      // No horizon, no floor line, no wall: the plane fills the frame, so all the
      // perspective is in the objects. Rectangles lying on a surface tilted away
      // from the lens converge toward a point well below the bottom edge, and
      // their line weight falls off with how far up the frame they sit.
      //
      // THIS PLATE DECLARES hostAnchor: false. See the anchor block below.
      const V = K.vanish(w * 0.5, h * 3.2);
      K.lights({ x: w * 0.18, y: h * 0.26, r: w * 0.58 }, { x: w * 0.86, y: h * 0.12, r: w * 0.44 });
      const PL = K.deskPlan(V, 818);
      const ruled = function (cx2, cy2, w2, h2, rot, n, sd) {
        PL.sheet(cx2, cy2, w2, h2, rot, p.ground, sd);
        const co = Math.cos(rot), si = Math.sin(rot);
        for (let i = 0; i < n; i++) {
          const dy = -h2 * 0.34 + (h2 * 0.68 / (n - 1)) * i;
          const x1 = -w2 * 0.34, x2 = w2 * (0.08 + (i % 3) * 0.12);
          K.thin([{ x: cx2 + x1 * co - dy * si, y: cy2 + x1 * si + dy * co },
            { x: cx2 + x2 * co - dy * si, y: cy2 + x2 * si + dy * co }], 0.3, 2.2, sd + 20 + i);
        }
      };
      // a loose drift of paper, three sheets out of square with each other
      PL.sheet(w * 0.27, h * 0.40, w * 0.30, h * (land ? 0.36 : 0.22), -0.07, p.ground, 941);
      ruled(w * 0.31, h * 0.44, w * 0.29, h * (land ? 0.35 : 0.21), 0.05, 6, 943);
      // an open report from above is a SPREAD: two pages and a gutter, and this is
      // the only camera in the pack that can say so
      ruled(w * 0.63, h * 0.35, w * 0.20, h * (land ? 0.32 : 0.20), 0.02, 5, 945);
      ruled(w * 0.82, h * 0.345, w * 0.20, h * (land ? 0.32 : 0.20), -0.01, 5, 947);
      K.thin([{ x: w * 0.73, y: h * 0.19 }, { x: w * 0.725, y: h * 0.51 }], 0.5, 3.4, 949);
      K.planKeyboard(w * 0.44, h * (land ? 0.82 : 0.76), w * 0.34, -0.03, 843);
      K.planMug(w * 0.15, h * (land ? 0.72 : 0.64), u(72), 851);
      K.planMug(w * 0.87, h * (land ? 0.63 : 0.57), u(52), 853);
      // A phone face-down on bare desk: the one genuinely dark object in a frame
      // that is otherwise all paper and pale wood, and the plate needs one. It sits
      // clear of the sheets — laid on top of one it read as a hole punched in the
      // paper rather than as an object beside it.
      K.mass([{ x: w * 0.10, y: h * (land ? 0.60 : 0.54) }, { x: w * 0.195, y: h * (land ? 0.585 : 0.528) },
        { x: w * 0.205, y: h * (land ? 0.75 : 0.665) }, { x: w * 0.11, y: h * (land ? 0.775 : 0.685) }],
        "#2E3742", 0.72, 951, -78, 4.4, { depth: 0.62, weight: 1 });
      K.ringStain(w * 0.25, h * (land ? 0.86 : 0.80), u(52), 931);
      K.ringStain(w * 0.70, h * (land ? 0.78 : 0.70), u(38), 933);
      K.pen(w * 0.62, h * (land ? 0.66 : 0.60), u(170), 859);
      K.crumples(w * 0.91, h * (land ? 0.87 : 0.82), u(42), 2, 935);
      // one more sheet, well up the frame, so the top-left is not dead space and
      // the drift of paper has somewhere to have come from
      PL.sheet(w * 0.10, h * (land ? 0.20 : 0.16), w * 0.20, h * (land ? 0.24 : 0.15), 0.09, p.ground, 953);
      P.slot("title", w * 0.06, h * (land ? 0.09 : 0.07), w * (land ? 0.30 : 0.44), land ? 220 : 250, { align: "left", role: "title" });
      P.slot("caption", w * 0.06, h * (land ? 0.28 : 0.20), w * (land ? 0.26 : 0.4), 64, { align: "left", role: "caption" });
    } else {
      // The doorway: he is standing in a lit hallway looking into a dark room, so
      // the warm source is the doorway itself and the cold monitor glow is the
      // thing behind camera. The spill used to be drawn in p.attention — a DATA
      // role, the colour that means "look here" on a plate — which is exactly the
      // confusion note 4 names: in the room, colour is light and material and
      // means nothing.
      const dx0 = w * (land ? 0.55 : 0.36), dw = w * 0.32;
      K.lights({ x: dx0 + dw * 0.5, y: floorY - h * 0.3, r: w * 0.5 }, { x: -w * 0.1, y: floorY - u(300), r: w * 0.5 });
      K.openDoor(dx0, h * 0.09, dw, floorY, 817);
      K.doorSpill(dx0, h * 0.09, dw, floorY, h, land, 829);
      K.calendar(w * (land ? 0.16 : 0.08), h * 0.18, u(200), u(230), 897);
      K.clock(w * (land ? 0.38 : 0.24), h * 0.2, u(50), 905);
      K.binders(w * (land ? 0.08 : 0.05), floorY - u(4), u(190), u(130), 5, 908);
      K.plant(w * (land ? 0.44 : 0.28), floorY - u(4), u(150), 887);
      K.coat(w * (land ? 0.5 : 0.31), h * 0.26, u(215), 911);
      K.wastebasket(w * (land ? 0.3 : 0.19), floorY - u(4), u(130), 913);
      K.crumples(w * (land ? 0.36 : 0.23), floorY - u(8), u(30), 3, 917);
      K.thin([{ x: w * (land ? 0.29 : 0.18), y: floorY - u(440) }, { x: w * (land ? 0.29 : 0.18), y: floorY - u(388) }], 0.6, 7, 915);
      K.foreground("chair", -1, floorY + h * 0.1, 987);
      P.slot("title", w * (land ? 0.12 : 0.07), h * 0.5, w * (land ? 0.36 : 0.5), land ? 260 : 300, { align: "left", role: "title" });
    }

    // §1.3 — the one moving thing, chosen from what this angle actually drew.
    // `from-behind-the-monitor` is the angle whose SUBJECT is the screen, so it
    // is the one plate where the caret earns the job over the mug.
    P.meta.ambient = K.ambient(o.boil | 0, angle === "from-behind-the-monitor" ? "screen" : null);

    // §1 — THE TITLE'S OWN GROUND. One call, after every branch has drawn and
    // declared its boxes, so no angle carries a placement of its own and a new
    // angle gets the ground for free. Off by default: see build.js TITLE_GROUND.
    const TG = titleGround(P, o.titleGround, k, 700);
    if (TG) {
      P.meta.titleGround = TG;
      const t = P.slots.title;
      // the slot box is re-declared unchanged — geometry always wins in P.slot(),
      // so this adds fields without moving anything already composited here
      P.slot("title", t.x, t.y, t.w, t.h, Object.assign({}, t, { ground: TG.treatment, groundBox: TG.box, colour: TG.typeColour }));
      if (TG.typeBlock.joinedCaption && P.slots.caption) {
        const c = P.slots.caption;
        P.slot("caption", c.x, c.y, c.w, c.h, Object.assign({}, c, { ground: TG.treatment, groundBox: TG.box, colour: TG.typeColour }));
      }
      if (TG.typeColour !== "structure") {
        // CLONED, NEVER MUTATED. TR.caption is one shared object across the
        // library — re-colouring it in place would reverse the caption on every
        // plate that borrows it. Same class of bug as the role-floor accumulation.
        P.meta.typeRoles = Object.assign({}, P.meta.typeRoles, {
          title: Object.assign({}, P.meta.typeRoles.title, { colour: TG.typeColour }),
        });
        if (TG.typeBlock.joinedCaption && P.meta.typeRoles.caption) {
          P.meta.typeRoles.caption = Object.assign({}, P.meta.typeRoles.caption, { colour: TG.typeColour });
        }
      }
    }

    // host-anchor: the region IS the host's target box, not a hint
    //
    // The spec question was whether the renderer should read this height as the
    // host's target height. It should, and saying so is the whole point of the
    // rebuild — otherwise the renderer is guessing how big Dennis is. The
    // quantity it scales is the host's TOP-OF-FIGURE-TO-FLOOR distance
    // (floorLineY - figure.y), not the raw figure box: the figure slot runs a
    // little past the floor line to carry the shoes, and scaling by the box
    // would shrink him by that overhang. This is the number the compositor
    // already solves with; it is written down here so the two cannot drift.
    //
    // REVISION 05 — TWO ADDITIONS, BOTH DATA.
    //
    // 1. CONTACT. Every plate declared its anchor in open floor, including the
    //    ones whose whole mid-frame is desk, so leaning-on-desk had nothing under
    //    the elbow. A plate with furniture he can reach now declares the POINT he
    //    meets it and the pose that meets it. The anchor's own x/y/w/h are
    //    untouched on every existing plate — this is a new field on the same slot,
    //    so nothing already composited against the region moves.
    //
    // 2. AN EXPLICIT REFUSAL, AS A BOOLEAN. high-desk-down looks straight down at
    //    the desk: there is no floor line and no standing figure to place, and a
    //    renderer that assumes every room plate can hold a host will either crash
    //    or invent a position. A sentence in a meta string does not stop that, so
    //    the plate ships `hostAnchor: false` and no host-anchor slot. Placement
    //    code branches on the boolean; hostAnchorNote is for the human reading the
    //    manifest. A room plate that declares NEITHER a host-anchor slot nor
    //    hostAnchor === false is a bug, and the audit is what catches it.
    if (angle === "high-desk-down" || angle === "over-the-shoulder") {
      P.meta.hostAnchor = false;
      if (angle === "over-the-shoulder") {
        P.meta.hostAnchorNote = "Deliberately none, and for the opposite reason to high-desk-down: he is ALREADY IN THIS PLATE. The near silhouette in the corner is him, drawn by K.foreground('shoulder'), so compositing a host cut-out onto this frame would put two of him in one shot. It is the only room plate with a figure in it.";
        P.meta.overTheShoulder = {
          figure: "drawn into the plate as a near silhouette — no face, no features, no eyeline, because we are behind him. Anything more would be a second Dennis drawn by a different author, disagreeing with hostFace() about who he is.",
          contrast: "he keeps the heaviest line AND the heaviest tone in frame, which no other foreground kind gets. room/ doctrine is that he is the highest-contrast object in any frame he is in, and here the near-object rule and the host rule point the same way for once.",
          noTitle: "NO title slot. A chapter opener needs a quiet flat ground and this frame is a shoulder, a lit screen and a desk — §1's family audit is the argument. This is a cut-away, not an opener.",
          screen: "the one room plate that publishes a `screen` region. Fill it with what the script is reading off it, at low value.",
          use: "the moment the script reads something off the screen. The viewer is behind him looking at the same thing, which is a different relationship to the material than watching him talk about it.",
        };
      } else {
        P.meta.hostAnchorNote = "Deliberately none. This camera is above the desk looking down at the surface: no floor line is in frame, and a standing cut-out has nothing to stand on. Cut to this plate over his voice, or pair it with a hand or forearm plate — which this pack does not yet carry. Do not synthesise a position.";
      }
    } else {
      const anchorX = Math.round(w * (angle === "doorway" ? 0.62 : angle === "low-desk-height" ? 0.27 : angle === "corner-perspective" ? 0.05 : 0.14));
      const anchorW = Math.round(w * (angle === "low-desk-height" ? 0.26 : 0.34));
      P.slot("host-anchor", anchorX, floorY - anchorH, anchorW, anchorH, Object.assign({
        role: "host-anchor", region: true, scales: "host",
        note: "composite a host cut-out here. This region's HEIGHT is the host's target height: scale the host plate so (host.floorLineY - host.slots.figure.y) equals this height, then sit the host's floorLineY on this region's bottom edge (which is this plate's floorLineY). Width is advisory — how much lateral room he has — and is never used to scale him, because the figure box includes arms that are meant to pass it",
      }, contact ? { contact: contact } : {}, angle === "low-desk-height" ? {
        cropped: "below",
        cropNote: "SAME ARITHMETIC, DIFFERENT PIN — no special case in the renderer. The camera is at desk height, so this region runs off the bottom of the canvas exactly as the floor does: scale by (floorLineY - figure.y) as always and pin floorLineY to the region's bottom edge, which lands at y=" + floorY + " on a canvas " + h + " tall. His legs finish below the frame, which is what a low angle does to a standing man.",
      } : {}));
      P.meta.hostAnchor = {
        targetHeight: anchorH,
        scales: "host.floorLineY - host.slots.figure.y",
        pin: "host.floorLineY onto this plate's floorLineY",
        floorLineY: floorY,
        floorInFrame: floorY <= h,
        widthIsAdvisory: true,
        contact: contact || null,
        light: "light the cut-out from this plate's meta.light — same two sources, same sides",
      };
    }
    return P;
  }

  // Wall of calls: its own plate so it can be cut to directly
  function wallOfCalls(o) {
    const land = o.w > o.h, w = o.w, h = o.h, p = o.pal;
    const rows = 7;
    const P = base(o, "wall-of-calls", {
      kicker: TR.kicker,
      ticker: { font: "Courier Prime", size: land ? 40 : 34, weight: 700, colour: "structure", maxChars: 6 },
      date: { font: "Courier Prime", size: land ? 28 : 26, weight: 400, colour: "structure", opacity: 0.75, maxChars: 8 },
      outcome: { font: "Archivo Narrow", size: land ? 34 : 30, weight: 600, colour: "structure", maxChars: 12 },
    });
    P.meta.family = "room";
    P.meta.rows = rows;
    P.meta.floorLineY = Math.round(h * 0.92); // a wall plate: the floor is still declared
    // NO HOST ANCHOR, DECLARED AS DATA. This is a board plate: it is a wall of
    // tickers cut to directly, and there is nowhere on it a figure belongs. It
    // carried neither an anchor slot nor a refusal, which is precisely the case
    // the revision-05 rule exists to catch — a renderer looping over the room
    // family and assuming every plate can hold a host would have invented a
    // position here. Metadata only: not a mark on this plate changes.
    P.meta.hostAnchor = false;
    P.meta.hostAnchorNote = "Deliberately none. A wall of call tickers is a full-frame data plate, not a set: cut to it over his voice. floorLineY is still declared because the wall meets a floor, but nothing should be stood on it.";
    const k = land ? w / 1920 : w / 1080;
    const S = inkScale(k);
    const q = function (n) { return n * k; };
    const K = roomKit(P, p, k);
    P.colourAdd(S.hatch(H.polyRect(0, 0, w, h), { color: p.ground2, opacity: 0.28, gap: 9, width: 14, angle: -3, over: 24, seed: 921 }));
    P.slot("kicker", q(land ? 150 : 80), q(land ? 100 : 200), w - q(land ? 300 : 160), q(54), { align: "left", role: "kicker" });
    const top = q(land ? 210 : 320);
    const rowH = ((h - top - q(land ? 120 : 220)) / rows);
    const L = q(land ? 150 : 80), R = w - q(land ? 150 : 80);
    for (let i = 1; i <= rows; i++) {
      const y = top + rowH * (i - 1);
      // each call is a pinned slip
      const jag = q((i % 3) * 12 - 12), wob = q(i % 2 ? 5 : -4);
      K.mass([
        { x: L - q(20) + jag, y: y + q(8) + wob }, { x: R + q(20) - (i % 4) * q(26), y: y + q(4) - wob },
        { x: R + q(14) - (i % 4) * q(26), y: y + rowH - q(12) - wob }, { x: L - q(26) + jag, y: y + rowH - q(8) + wob },
      ], p.ground, 0.78, 930 + i * 5, -3);
      K.thin([{ x: L + (R - L) * 0.24, y: y + q(16) }, { x: L + (R - L) * 0.24, y: y + rowH - q(20) }], 0.16, 2, 934 + i);
      K.thin([{ x: L + (R - L) * 0.53, y: y + q(16) }, { x: L + (R - L) * 0.53, y: y + rowH - q(20) }], 0.16, 2, 938 + i);
      P.slot(`ticker-${i}`, L + 10, y + rowH * 0.2, (R - L) * 0.22, rowH * 0.6, { align: "left", role: "ticker" });
      P.slot(`date-${i}`, L + (R - L) * 0.26, y + rowH * 0.34, (R - L) * 0.22, rowH * 0.5, { align: "left", role: "date" });
      P.slot(`outcome-${i}`, L + (R - L) * 0.56, y + rowH * 0.2, (R - L) * 0.42, rowH * 0.6, { align: "right", role: "outcome" });
      const px = L + (R - L) * (0.32 + (i % 4) * 0.14);
      P.colourAdd(S.hatch(ellipse(px, y + q(14), q(15), q(14), 12, 0.08, 960 + i), { color: p.down, opacity: 0.62, gap: 4, width: 7, angle: -70, seed: 965 + i }));
      P.inkAdd(S.outline(ellipse(px, y + q(14), q(15), q(14), 12, 0.08, 960 + i), { stroke: p.structure, width: 2.4, opacity: 0.5, amp: 1.2, over: 4, seed: 968 + i }));
      P.artBox(`pin-${i}`, px - q(20), y - q(2), q(40), q(34));
    }

    // §3.3 — SOMETHING JUST PINNED TO THE BOARD.
    //
    // A variant, not a second plate: `pinned: true` lays one more slip over the
    // others, crooked, with its own pin and its own ticker-and-outcome slots. A
    // beat, a callback and a running gag in one asset — and it is the same
    // wall, so cutting between the two states is the card ARRIVING.
    //
    // It also earns the room its §1.3 prop. The board draws no mug and no
    // monitor, so it was one of three rooms with nothing alive in it; the newest
    // card is the only thing on a wall of settled paper that has not settled, and
    // one lifted corner is both the beat and the motion. Nothing else on the
    // plate moves — a wall of fluttering cards is a noticeboard in a gale.
    if (o.pinned) {
      const py = top + rowH * (rows - 2.35);
      const pL = L + (R - L) * 0.16, pW = (R - L) * 0.76, pH = rowH * 1.15;
      const tilt = q(26);
      K.mass([
        { x: pL, y: py + tilt }, { x: pL + pW, y: py },
        { x: pL + pW - q(6), y: py + pH }, { x: pL - q(8), y: py + pH + tilt },
      ], p.ground, 0.92, 980, -3);
      P.inkAdd(S.outline([
        { x: pL, y: py + tilt }, { x: pL + pW, y: py },
        { x: pL + pW - q(6), y: py + pH }, { x: pL - q(8), y: py + pH + tilt },
      ], { stroke: p.structure, width: q(3.4), opacity: 0.9, amp: 3, over: 10, seed: 982 }));
      const npx = pL + pW * 0.5;
      P.colourAdd(S.hatch(ellipse(npx, py + q(18), q(17), q(16), 12, 0.08, 984), { color: p.attention, opacity: 0.7, gap: 4, width: 7, angle: -70, seed: 985 }));
      P.inkAdd(S.outline(ellipse(npx, py + q(18), q(17), q(16), 12, 0.08, 984), { stroke: p.structure, width: 2.6, opacity: 0.55, amp: 1.2, over: 4, seed: 986 }));
      P.slot("new-ticker", pL + q(24), py + pH * 0.26, pW * 0.3, pH * 0.5, { align: "left", role: "ticker" });
      P.slot("new-date", pL + pW * 0.34, py + pH * 0.34, pW * 0.24, pH * 0.42, { align: "left", role: "date" });
      P.slot("new-outcome", pL + pW * 0.58, py + pH * 0.26, pW * 0.38, pH * 0.5, { align: "right", role: "outcome" });
      P.artBox("pin-new", npx - q(22), py, q(44), q(38));
      // the corner that has not settled
      K.registerCard(pL - q(8), py + pH + tilt, q(70), 988);
      P.meta.pinned = {
        note: "the newest call, laid over the others and not straightened. Cut from the un-pinned plate to this one and the card has just arrived.",
        slots: ["new-ticker", "new-date", "new-outcome"],
        pin: "drawn in `attention` rather than `down` — the pin marks WHICH card is new, and nothing about a new call is a loss yet.",
      };
    }
    // §1.3 — STATED, EVEN THOUGH IT IS EMPTY.
    //
    // wallOfCalls draws pinned cards and no desk, so it registers neither a mug
    // nor a monitor and this returns null. Calling it anyway means the manifest
    // SAYS the plate has no ambient prop rather than simply not mentioning one —
    // an absent field and a field that is null are different claims, and only the
    // second is checkable.
    //
    // It is the plate that most obviously wants a prop: a card that has just been
    // pinned, slightly crooked, over the others, is §3.3's beat. Deliberately not
    // invented here — that is drop three, and it is a writing decision as much as
    // a drawing one.
    P.meta.ambient = K.ambient(o.boil | 0, null);
    if (!P.meta.ambient) {
      P.meta.ambientNote = "None, and declared rather than missed. §1.3 asks for one moving thing in each ROOM — a set he is standing in, which should not read as a photograph. This is not one: it declares hostAnchor false and is a full-frame data plate cut to over his voice, a wall of settled paper with nothing on it that moves. The variant that DOES have a beat is room/wall-of-calls-pinned, where the newest card has not settled yet.";
    }
    return P;
  }

  // ---------------- annotations ----------------
  // Marks made ON another plate: the scrawls the script calls for by name.
  // Alpha cut-outs, no ground, stretched onto the slot they wrap.
  //
  // Doctrine: an annotation is drawn in ATTENTION. It therefore *spends* the
  // frame's one attention — a plate that already has an attention mark cannot
  // also be annotated. This is why annotations are their own family and not a
  // flag on every plate: the operator has to choose.
  // A hand circling something moves fast and wavers slowly. The wobble is two or
  // three lobes across the whole sweep, not noise per point (that reads as a
  // lumpy potato); the ellipse is tilted a few degrees, because nobody draws one
  // axis-aligned; and the pen flies outward at the end rather than closing neatly
  // on where it started.
  //
  // One geometry, sampled twice. The reinforcing arc has to be the SAME waver as
  // the primary or it reads as a second, wrong circle — and its radial offset is
  // windowed to zero at both ends, so it leaves the primary line and rejoins it
  // instead of starting in open space with a blunt stub.
  function ovalGeom(cx, cy, rx, ry, seed) {
    const r = H.rng(seed);
    const tilt = -0.075 + r() * 0.05, ct = Math.cos(tilt), st = Math.sin(tilt);
    const l1 = 2 + r() * 0.8, p1 = r() * 6.283, l2 = 3 + r() * 1.2, p2 = r() * 6.283;
    return function (a, k) {
      // more lopsided than a drawing compass and less than a scribble: the low
      // frequency is what makes one side of the lap run wider than the other,
      // which is most of what separates a drawn ring from a vector ellipse.
      //
      // The two terms are biased OUTWARD (they sum to 0 at their tightest, not
      // -6.4%). A ring that dips inside its nominal radius reads no differently
      // — the lopsidedness is what the eye reads — but every dip has to be paid
      // for twice over in the inscribed box, once on each side, so the inward
      // half of that wobble was costing ~10% of the area the mark can wrap.
      const kk = (k || 1) * (1 + (Math.sin(a * l1 + p1) + 1) * 0.021 + (Math.sin(a * l2 + p2) + 1) * 0.011);
      const x = Math.cos(a) * rx * kk, y = Math.sin(a) * ry * kk;
      return { x: cx + x * ct - y * st, y: cy + x * st + y * ct };
    };
  }

  // A circled word is a SPIRAL, not a closed ellipse. The lap drifts steadily
  // outward across its whole length, so the finish passes OUTSIDE the start and
  // the two cross the way a pen carrying on round actually crosses.
  //
  // The old version held a constant radius and then kicked the last 8% outward
  // by up to 0.13r to fake a pen-lift. That kick is the spur: a sudden radial
  // dogleg with tangential overshoot on the end of it, landing in open space
  // next to the start of the lap. It read as a mistake rather than a gesture,
  // and no amount of wobble anywhere else could cover it.
  function annOval(cx, cy, rx, ry, turns, seed, phase, grow) {
    const at = ovalGeom(cx, cy, rx, ry, seed), n = Math.round(84 * turns), pts = [];
    const a0 = phase == null ? -2.1 : phase;
    const gr = grow == null ? 0.08 : grow;
    for (let i = 0; i <= n; i++) {
      const t = i / n, a = a0 + t * Math.PI * 2 * turns;
      pts.push(at(a, 1 - gr * 0.5 + gr * t));
    }
    return pts;
  }

  // The largest rectangle of a given aspect, centred on the mark, that clears
  // every point of the drawn ink.
  //
  // Earlier versions solved this the other way round: assume the ink is the
  // nominal ellipse, inscribe r/√2, then discount for GROW and worst-case
  // WOBBLE. That is a chain of estimates about a line that has already been
  // drawn — and it was wrong, because the spiral's phase decides WHERE the
  // tight side lands, so the worst case is only reachable at some angles and
  // the box was simultaneously too generous on one side and too mean on the
  // other. Measuring the ink is exact and needs no constants: a rectangle is
  // clear of a loop iff no point of the loop lies inside it.
  //
  // Clearance is PER AXIS. One isotropic figure spends the same absolute margin
  // against ry as against rx, and on a 2.3:1 mark ry is less than half of rx —
  // a 13u allowance is 3% of the width and 23% of the height. That asymmetry,
  // not the measurement, is what collapsed the solved box to a third of the
  // canvas and made every target demand a canvas 2.3× its own width.
  function inscribeRect(pts, cx, cy, aspX, aspY, clearX, clearY) {
    const dx = pts.map((p) => Math.abs(p.x - cx)), dy = pts.map((p) => Math.abs(p.y - cy));
    const hits = (s) => {
      const hx = s * aspX + clearX, hy = s * aspY + clearY;
      for (let i = 0; i < dx.length; i++) if (dx[i] < hx && dy[i] < hy) return true;
      return false;
    };
    // bracket first, THEN bisect. Halving until the rect stops hitting and
    // bisecting [0, that] is wrong: it throws away the whole interval the
    // answer lives in and converges on the last probe instead of the boundary,
    // which is how the measured box came out a third of its true size.
    let lo, hi;
    if (hits(1)) {
      hi = 1;
      let s = 0.85;
      while (s > 0.02 && hits(s)) { hi = s; s *= 0.85; }
      lo = s;
    } else {
      lo = 1;
      let s = 1.2;
      while (s < 6 && !hits(s)) { lo = s; s *= 1.2; }
      hi = s;
    }
    for (let i = 0; i < 30; i++) {
      const m = (lo + hi) / 2;
      if (hits(m)) hi = m; else lo = m;
    }
    return { ax: lo * aspX, ay: lo * aspY };
  }

  // stroke() runs the line past both ends by `over`, along the direction it was
  // travelling. That ink is real and has to be measured, but it lives at the two
  // ends of the lap — folding it into the clearance charges every angle for it.
  function withOvershoot(pts, over) {
    if (!over || pts.length < 2) return pts;
    const ext = (a, b) => {
      const dx = b.x - a.x, dy = b.y - a.y, L = Math.hypot(dx, dy) || 1;
      return { x: b.x + (dx / L) * over, y: b.y + (dy / L) * over };
    };
    return [ext(pts[1], pts[0])].concat(pts, [ext(pts[pts.length - 2], pts[pts.length - 1])]);
  }

  // sub-arc of the same circle, offset inward and windowed to zero at both ends
  function annOvalHug(cx, cy, rx, ry, seed, a0, sweep, off) {
    const at = ovalGeom(cx, cy, rx, ry, seed), n = Math.max(14, Math.round(60 * Math.abs(sweep) / 6.283)), pts = [];
    for (let i = 0; i <= n; i++) {
      const u = i / n;
      pts.push(at(a0 + u * sweep, 1 + off * Math.sin(Math.PI * u)));
    }
    return pts;
  }

  function annotation(o) {
    const p = o.pal, w = o.w, h = o.h, type = o.type;
    const P = H.Plate({
      key: o.key, w: w, h: h, seed: o.seed,
      pal: { ground: "none", grain: null, structure: p.structure, surfaceKey: p.surfaceKey },
      meta: {
        family: "annotations", type: type, cutout: true, alpha: true,
        over: "any plate", stretch: "both",
        colourRule: "drawn in attention — an annotated frame has spent its one attention",
      },
    });
    const A = p.attention, mid = { x: w / 2, y: h / 2 };
    let primary = 0;
    // Every point of ink the mark lays down, each carrying the distance its own
    // stroke can reach past that point (half the nib, plus the wobble pass's
    // amplitude). Slots are measured against THIS, not against the nominal
    // geometry the strokes were built from — the two are not the same line, and
    // the difference is exactly the margin that decides whether a mark lands on
    // the type it is supposed to be marking.
    const inked = [];
    // Record the ink DENSELY. A stroke is authored as a polyline — the four sides
    // of box-scrawl are two points each — and stroke() resamples and wobbles it
    // on the way to the page. Storing only the authored vertices leaves the whole
    // middle of every long side unmeasured, so a slot could poke straight through
    // a side and still be reported clear: box-scrawl's block came out WIDER than
    // the box drawn around it.
    const record = function (pts, pad) {
      const step = Math.max(2, pad * 0.75);
      for (let i = 0; i < pts.length; i++) {
        inked.push({ x: pts[i].x, y: pts[i].y, pad: pad });
        if (i === pts.length - 1) break;
        const a2 = pts[i], b2 = pts[i + 1];
        const n = Math.floor(Math.hypot(b2.x - a2.x, b2.y - a2.y) / step);
        for (let k = 1; k < n; k++) inked.push({ x: a2.x + (b2.x - a2.x) * (k / n), y: a2.y + (b2.y - a2.y) * (k / n), pad: pad });
      }
    };
    const ink = function (pts, lw, op, amp, over, seed) {
      if (!primary) primary = lw;
      const pad = lw / 2 + amp;
      record(withOvershoot(pts, over), pad);
      P.inkAdd(H.stroke(pts, { stroke: A, width: lw, opacity: op, amp: amp, over: over, seed: seed }));
    };
    // the four edges of the ink, each pushed out by the reach of the stroke that
    // drew it — i.e. the smallest rectangle that certainly contains the mark
    const inkBox = () => ({
      x0: Math.min.apply(null, inked.map((q) => q.x - q.pad)),
      y0: Math.min.apply(null, inked.map((q) => q.y - q.pad)),
      x1: Math.max.apply(null, inked.map((q) => q.x + q.pad)),
      y1: Math.max.apply(null, inked.map((q) => q.y + q.pad)),
    });

    if (type === "scrawl-oval-wide" || type === "scrawl-oval-tight") {
      // rx/ry are the NOMINAL radii; the outward-biased wobble adds up to 6.4%
      // and the spiral another half of GROW, so the ink reaches ~1.11× these.
      // Sized so that reach, plus half a stroke and the wobble pass, still lands
      // inside the canvas — an alpha cut-out clipped by its own viewBox is a
      // mark with a flat side.
      const rx = w * 0.428, ry = h * 0.4;
      // Tight marks carry ABSOLUTE weights. A mark is scaled to the thing it
      // wraps, and a cell is a seventh of a headline — fractional weights on a
      // small canvas come out as hairlines at use size.
      const tight = type === "scrawl-oval-tight";
      // 1.22 turns: enough overlap that the crossing is unmistakably deliberate.
      // Overshoot is now small — the spiral does the work the flyout was faking,
      // so the ends no longer need a spike to look like they were drawn.
      const GROW = 0.085;
      // Authored weight is set by what the mark DELIVERS, not by how it looks on
      // its own canvas. solveMark scales the canvas by target/area, so delivered
      // weight is lw × (target / area.w): the honest area ratio makes that scale
      // ~1.7×, and the old absolute 15u then inked at 37u — a marker pen, and the
      // compositor's own weight guard said so.
      const lw = tight ? 11 : w * 0.0095, amp = tight ? 2.8 : w * 0.004, over = tight ? 4 : w * 0.005;
      const lap = annOval(mid.x, mid.y, rx, ry, 1.22, 311, -2.1, GROW);
      ink(lap, lw, 0.92, amp, over, 312);
      // No second reinforcing arc. It hugged the primary closely enough over a
      // 2.5-radian sweep that it read as a misregistered duplicate — a printing
      // fault, not a second pass of the pen. The spiral's own overlap IS the
      // reinforcement, and it lands where a real one does: at the crossing.
      //
      // The area slot is the thing being circled, and the compositor solves it
      // onto the target box, so area must be a rectangle that genuinely FITS
      // INSIDE the ink that was just drawn. It is measured off `lap` — with the
      // end overshoot appended where it actually falls — rather than derived
      // from rx/ry, so the clearance covers the real geometry (spiral growth,
      // wobble phase, stroke half-width, the wobble pass's amplitude) instead of
      // a worst-case guess that could be spent before the pen moved.
      //
      // The aspect handed in is the aspect of the THING WRAPPED, not of the
      // canvas. A rectangle inscribed in an ellipse is largest at the ellipse's
      // own proportions, but that is not the shape being solved onto: type is
      // flatter than the ring that circles it, and a flatter box fits much
      // further out along the major axis. Matching the canvas aspect quietly
      // capped area at ~0.46w, which forced solveMark to blow the canvas up to
      // 2.3× the target — so the ring's ends swept across the words either side
      // of the one being circled. A tight mark rings a figure or a short phrase
      // (~3:1); a wide mark rings a line of headline (~8:1).
      const wrapAR = tight ? 3 : 8;
      const pad = lw / 2 + amp;
      const box = inscribeRect(withOvershoot(lap, over), mid.x, mid.y, rx, rx / wrapAR, pad, pad);
      P.slot("area", mid.x - box.ax, mid.y - box.ay, box.ax * 2, box.ay * 2, { role: "wraps", region: true, note: "the thing being circled — the mark solves this slot onto it, and the box is measured against the drawn ink so the lap always lands clear of the type" });
    } else if (type === "underline-swipe") {
      const y0 = h * 0.42;
      ink([{ x: w * 0.04, y: y0 }, { x: w * 0.42, y: y0 + h * 0.09 }, { x: w * 0.97, y: y0 - h * 0.04 }], w * 0.009, 0.94, w * 0.004, w * 0.02, 321);
      ink([{ x: w * 0.1, y: y0 + h * 0.3 }, { x: w * 0.55, y: y0 + h * 0.36 }, { x: w * 0.82, y: y0 + h * 0.26 }], w * 0.006, 0.62, w * 0.004, w * 0.016, 323);
      P.slot("area", 0, 0, w, Math.round(inkBox().y0), { role: "wraps", region: true, note: "the line of type sitting above the swipe — the floor is the topmost ink, so descenders clear the stroke" });
    } else if (type === "underline-tight") {
      const y0 = h * 0.44;
      ink([{ x: w * 0.02, y: y0 }, { x: w * 0.5, y: y0 + h * 0.1 }, { x: w * 0.98, y: y0 - h * 0.05 }], 13, 0.94, 4.2, 16, 391);
      ink([{ x: w * 0.12, y: y0 + h * 0.28 }, { x: w * 0.62, y: y0 + h * 0.32 }, { x: w * 0.9, y: y0 + h * 0.24 }], 8, 0.6, 3.4, 12, 393);
      // Both underlines used to declare a floor of ~0.4h, a fraction picked to
      // look right on the canvas. The swipe's own crest sits at 0.38h and the
      // stroke reaches ~0.06h past that, so the mark ran through the bottom of
      // the type it was drawn to sit under. Measured, it cannot.
      P.slot("area", 0, 0, w, Math.round(inkBox().y0), { role: "wraps", region: true, note: "the figure sitting above the swipe — for a cell or a single word" });
    } else if (type === "strike-out") {
      // absolute weights: a strike always lands on a number, i.e. cell-sized
      ink([{ x: w * 0.04, y: h * 0.28 }, { x: w * 0.5, y: h * 0.52 }, { x: w * 0.96, y: h * 0.68 }], 13, 0.92, 3.6, 6, 331);
      ink([{ x: w * 0.06, y: h * 0.72 }, { x: w * 0.52, y: h * 0.46 }, { x: w * 0.94, y: h * 0.3 }], 9, 0.72, 3.2, 5, 333);
      // Full canvas on purpose: a strike is the one mark that is SUPPOSED to
      // cross its target, so there is nothing to clear.
      P.slot("area", 0, 0, w, h, { role: "wraps", region: true, note: "what is being struck out — the ink crosses it by definition, so this is the whole canvas" });
    } else if (type === "box-scrawl") {
      const L = w * 0.05, R = w * 0.95, T = h * 0.12, B = h * 0.88;
      const ov = w * 0.03;
      ink([{ x: L - ov, y: T }, { x: R + ov * 0.6, y: T - h * 0.03 }], w * 0.009, 0.9, w * 0.005, w * 0.018, 341);
      ink([{ x: R, y: T - h * 0.05 }, { x: R + w * 0.006, y: B + h * 0.04 }], w * 0.009, 0.9, w * 0.005, w * 0.018, 342);
      ink([{ x: R + ov * 0.5, y: B }, { x: L - ov * 0.8, y: B + h * 0.035 }], w * 0.009, 0.9, w * 0.005, w * 0.018, 343);
      ink([{ x: L, y: B + h * 0.05 }, { x: L - w * 0.004, y: T - h * 0.05 }], w * 0.009, 0.9, w * 0.005, w * 0.018, 344);
      // The four sides are drawn ON L/T/R/B with overshoot and wobble, so that
      // rectangle is the ink, not the space inside it. Measured, keeping the
      // box's proportions.
      const bp = Math.max.apply(null, inked.map((q) => q.pad));
      const bs = inscribeRect(inked, mid.x, mid.y, (R - L) / 2, (B - T) / 2, bp, bp);
      P.slot("area", Math.round(mid.x - bs.ax), Math.round(mid.y - bs.ay), Math.round(bs.ax * 2), Math.round(bs.ay * 2), { role: "wraps", region: true, note: "the cell or block being boxed, inside the drawn sides" });
    } else if (type === "bracket-rows") {
      const x = w * 0.62;
      ink([
        { x: x - w * 0.34, y: h * 0.04 }, { x: x, y: h * 0.1 },
        { x: x + w * 0.06, y: h * 0.5 }, { x: x, y: h * 0.9 }, { x: x - w * 0.34, y: h * 0.96 },
      ], w * 0.05, 0.9, w * 0.03, w * 0.06, 351);
      ink([{ x: x + w * 0.06, y: h * 0.5 }, { x: w * 0.99, y: h * 0.5 }], w * 0.045, 0.8, w * 0.025, w * 0.06, 353);
      // Rows are wider than the bracket that groups them and sit to its LEFT, so
      // the area runs off the canvas the way bracket-rows' note already does. A
      // 0.6w box inside the canvas sat under the arms; the measured 38u strip
      // that replaced it was honest but useless — solveMark would have blown the
      // bracket up 6× to make a row block fit it.
      P.slot("area", Math.round(-w * 4), 0, Math.round(w * 4 + inkBox().x0), h, { role: "wraps", region: true, note: "the rows being grouped — they run off to the left and end where the bracket's arms begin" });
      P.slot("note", w * 1.02, h * 0.36, w * 1.9, h * 0.28, { align: "left", role: "caption", note: "what the group is — sits outside the plate, to the right" });
    } else if (type === "arrow-elbow") {
      const a = { x: w * 0.06, y: h * 0.14 }, b = { x: w * 0.52, y: h * 0.2 }, c = { x: w * 0.86, y: h * 0.86 };
      ink([a, b, { x: b.x + w * 0.12, y: b.y + h * 0.14 }, c], w * 0.014, 0.92, w * 0.007, w * 0.02, 361);
      ink([{ x: c.x - w * 0.13, y: c.y - h * 0.06 }, c], w * 0.012, 0.9, w * 0.005, w * 0.012, 363);
      ink([{ x: c.x - w * 0.03, y: c.y - h * 0.17 }, c], w * 0.012, 0.9, w * 0.005, w * 0.012, 364);
      P.slot("note", w * 0.02, h * 0.02 - h * 0.2, w * 0.5, h * 0.18, { align: "left", role: "caption", note: "the scrawled words, at the arrow's tail" });
      // points-at, not wraps: the head LANDS on the target, so the target sits
      // just past the tip, down and to the right of where the arrow arrives. The
      // old box was centred on the tip, which put the arrowhead in the middle of
      // the thing it was pointing at.
      // A gap, not a touch: the head's reach plus a little air. Landing the box
      // exactly on the tip puts the arrowhead against the first glyph, which
      // reads as the arrow crossing the number rather than arriving at it.
      const tip = Math.max.apply(null, inked.map((q) => q.pad)) + h * 0.03;
      P.slot("area", Math.round(c.x + tip), Math.round(c.y + tip), Math.round(w * 0.5), Math.round(h * 0.24), { role: "points-at", region: true, note: "what the arrow lands on — a short gap past the tip, so the head arrives at it and never crosses it" });
    } else if (type === "caret-note") {
      const cx = w * 0.5, cy = h * 0.78;
      ink([{ x: cx - w * 0.09, y: cy }, { x: cx, y: cy - h * 0.26 }, { x: cx + w * 0.09, y: cy }], w * 0.016, 0.92, w * 0.007, w * 0.02, 371);
      ink([{ x: cx, y: cy - h * 0.24 }, { x: cx + w * 0.02, y: cy - h * 0.44 }], w * 0.012, 0.7, w * 0.006, w * 0.016, 373);
      P.slot("note", w * 0.06, h * 0.06, w * 0.88, h * 0.4, { align: "center", role: "caption", note: "the words above the caret" });
      P.slot("area", Math.round(cx - w * 0.12), Math.round(inkBox().y1), Math.round(w * 0.24), Math.round(h * 0.2), { role: "points-at", region: true, note: "the gap in the type the caret points up into — it starts below the apex, so the caret never sits on the glyphs" });
    } else if (type === "tick-marks") {
      for (let i = 0; i < 3; i++) {
        const x = w * (0.2 + i * 0.3);
        ink([{ x: x - w * 0.05, y: h * 0.44 }, { x: x, y: h * 0.72 }, { x: x + w * 0.09, y: h * 0.16 }], w * 0.014, 0.9, w * 0.006, w * 0.02, 381 + i * 7);
      }
      P.slot("area", 0, 0, w, h, { role: "wraps", region: true, note: "the three things being ticked, evenly spaced — the ticks land on them, so this is the whole canvas" });
    }
    // ---- the mark's words ---------------------------------------------------
    // Marks carry captions: "this candle", "7% three years ago", "-120m → 4.5b".
    // Three marks declared a `note` slot with role "scrawl" — and no plate in
    // this family declared any typeRoles at all, so that role resolved to
    // nothing: the renderer had no size, weight or colour to set the words in,
    // and the compositor's audit skips a slot whose role it cannot find. The
    // caption is now a real role, on every mark in the family.
    //
    // Its size is tied to the PEN, not to the canvas. A mark and its caption are
    // scaled together by solveMark, and the one relation that survives that
    // scaling is the one between the nib and the hand writing with it.
    const capSize = Math.max(16, Math.round(primary * 2.6));
    P.meta.typeRoles = {
      caption: {
        font: "Courier Prime", size: capSize, weight: 400, colour: "attention",
        tracking: ".01em", maxLines: 2, maxCharsPerLine: Math.floor((w * 0.92) / (capSize * 0.62)),
        note: "the mark's own words, in the mark's own colour — an annotated frame has already spent its one attention, so a caption never introduces a second",
      },
    };
    if (!P.slots.note) {
      const b = inkBox(), capH = Math.round(capSize * 2.4), lead = Math.round(capSize * 0.5);
      // below the ink where the canvas has room, above it where it does not, and
      // just past the edge when neither band fits — a caption is words beside a
      // mark, so it may sit outside the cut-out like bracket-rows' does.
      const y = (h - b.y1 >= capH + lead) ? b.y1 + lead
        : (b.y0 >= capH + lead) ? b.y0 - lead - capH
        : b.y1 + lead;
      const nx = Math.max(0, Math.round(b.x0)), nr = Math.min(w, Math.round(b.x1));
      P.slot("note", nx, Math.round(y), nr - nx, capH, { align: "left", role: "caption", note: "the mark's words, set clear of the ink — below it where the canvas has room, otherwise just outside the edge" });
    }
    // How the compositor is allowed to solve this mark onto its target.
    //   both      — x and y independently. Only safe for marks that ENCLOSE, where
    //               the enclosure is meant to take the target's proportions.
    //   x-uniform — fit the width, use that same scale for y. For marks whose ink
    //               is a line of its own natural thickness (underlines, strikes):
    //               solving y independently stretches the swipe into a fat wave.
    P.meta.solve = (type.indexOf("underline") === 0 || type === "strike-out" || type === "tick-marks") ? "x-uniform" : "both";
    // Where an x-uniform mark registers against its target. An underline's ink is
    // drawn BELOW its area, so centring puts the swipe through the glyph bottoms
    // — it registers bottom-to-bottom. A strike crosses the middle by definition.
    P.meta.anchor = type.indexOf("underline") === 0 ? "bottom" : "middle";
    // The authored weight of the primary stroke, in canvas units. A mark is
    // solved onto whatever it wraps, and line weight is a canvas-unit quantity:
    // inkWeight x solve is the ONLY thing that says whether the mark will read.
    // Scale alone lies, because tight marks carry absolute weights.
    P.meta.inkWeight = Math.round(primary * 10) / 10;
    return P;
  }

  const ANNOTATIONS = [
    { type: "scrawl-oval-wide", w: 1200, h: 230 },
    { type: "scrawl-oval-tight", w: 340, h: 150 },
    { type: "underline-swipe", w: 1000, h: 140 },
    { type: "underline-tight", w: 300, h: 90 },
    { type: "strike-out", w: 320, h: 90 },
    { type: "box-scrawl", w: 1000, h: 320 },
    { type: "bracket-rows", w: 220, h: 700 },
    { type: "arrow-elbow", w: 760, h: 520 },
    { type: "caret-note", w: 620, h: 300 },
    { type: "tick-marks", w: 720, h: 220 },
  ];

  const ROOM_ANGLES = ["wide", "wide-tight", "desk-front", "desk-corner", "from-behind-the-monitor", "whiteboard-wall", "printer-corner", "doorway"];
  // Camera positions rather than furniture arrangements — see build.js CAMERA_ANGLES.
  const ROOM_CAMERA_ANGLES = ["corner-perspective", "low-desk-height", "high-desk-down"];
  const HOST_FRAMINGS = ["close-up", "medium"];

  /* ROUND-ONE ADDITION (rebuild-15), and the ONLY edit to this file: the private
   layout helpers are exported so engine/plates-r1.js can author new plates with
   the SAME machinery rather than a copy of it. No drawing code is touched. A
   second copy of base()/place()/TR is how two plates in one kit end up with
   different type scales and nobody can say which is right. */
  g.PLATES = { base, TR, figRoles, unitOf, blockH, measure, place, field, ruleH, surfaceFurniture,
    ROLES, SURFACES, pal, titleGround, typeBlockOf, TITLE_GROUNDS, quarterPair, seasonality, languageShift, headlineStack, emptyChair, hostChair, lowerThird, confession, CONFESSION_TREATMENTS, shortInterest, insiderFlow, macroSeries, endCard, multiplesStrip, multipleBridge, numbersSheet, rowBand, threeSeries, swatch, surfaceCard, chartFrame, cashFlow, headlineBand, bothTrue, unitLadder, closingPlate, rowSpotlight, flowPlate, bigNumber, bigFraction, compare, definitionCard, quotePull, criteriaCard, timeline, mediaFrame, captureFrame, hookCard, hostFigure, hostHead, hostBlink, waterfall, impliedPlate, proportionBar, distribution, scaleFig, receipt, saidHappened, sensitivity, multiplesGrid, whiteboard, HOST_POSES, HOST_FRAMINGS, HOST_OUTFITS, ellipse, room, wallOfCalls, ROOM_ANGLES, ROOM_CAMERA_ANGLES, annotation, ANNOTATIONS, peerStrip, cycleFrame };
})(typeof window !== "undefined" ? window : globalThis);
