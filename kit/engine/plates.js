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
    const m = land ? { l: 118, r: 118, t: 92, b: 96 } : { l: 48, r: 48, t: 200, b: 220 };
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

  // ---------------- charts ----------------
  // Axes, ticks, gridlines and frame are drawn. Code draws only the data path
  // inside plot-area. Every column/point gets its own slot.
  function chartFrame(o) {
    const p = o.pal, w = o.w, h = o.h, land = w > h;
    const s = SURFACES[p.surfaceKey];
    const P = H.Plate({
      key: o.key, w, h, seed: o.seed, pal: p,
      meta: {
        aspect: land ? "16x9" : "9x16", family: "charts", type: o.type, columns: 6,
        typeRoles: {
          unit: { font: "Courier Prime", size: 26, weight: 400, colour: "structure", opacity: 0.72, tracking: "0.04em", maxChars: land ? 46 : 38 },
          period: { font: "Archivo Narrow", size: land ? 28 : 26, weight: 600, colour: "structure", maxChars: 6 },
          axis: { font: "Courier Prime", size: land ? 26 : 24, weight: 400, colour: "structure", opacity: 0.7, maxChars: 7 },
          value: { font: "Courier Prime", size: land ? 34 : 30, weight: 700, colour: "structure", maxChars: 7 },
        },
        seriesRoles: { subject: "structure", neutral: "neutralData", otherParty: "otherParty", up: "up", down: "down", mark: "attention" },
      },
    });
    P.colourAdd(surfaceFurniture(P, s));
    const m = land ? { l: 200, r: 130, t: 190, b: 170 } : { l: 150, r: 90, t: 330, b: 420 };
    const x0 = m.l, x1 = w - m.r, y0 = m.t, y1 = h - m.b;
    const ticks = o.type === "line-dense" ? 12 : 6;

    P.slot("unit", land ? 118 : 60, land ? 92 : 200, x1 - (land ? 118 : 60), land ? 42 : 50, { align: "left", role: "unit" });
    P.slot("plot-area", x0, y0, x1 - x0, y1 - y0, { role: "plot-area", container: true, note: "code draws the data path in here only" });

    // y gridlines + their label slots
    const gl = o.type === "line-dense" ? 3 : 4;
    for (let i = 0; i <= gl; i++) {
      const y = y1 - ((y1 - y0) / gl) * i;
      if (i > 0) P.inkAdd(H.line(x0, y, x1, y, { stroke: p.structure, width: 1.8, opacity: 0.2, amp: 2.6, over: 7, seed: 210 + i * 7 }));
      // the topmost label tucks under its gridline, so it never reaches the value row
      P.slot(`y-${i + 1}`, x0 - (land ? 160 : 130), i === gl ? y + 6 : y - 26, land ? 140 : 112, 52, { align: "right", role: "axis" });
    }
    // axes
    P.inkAdd(H.line(x0, y0 - 16, x0, y1, { stroke: p.structure, width: land ? 4.6 : 4, opacity: 0.9, amp: 3, over: 11, seed: 21 }));
    P.inkAdd(H.line(x0, y1, x1 + 18, y1, { stroke: p.structure, width: land ? 4.6 : 4, opacity: 0.9, amp: 3, over: 11, seed: 22 }));

    if (o.type === "bars-6y") {
      const step = (x1 - x0) / 6, barW = step * 0.56;
      for (let c = 1; c <= 6; c++) {
        const cx = x0 + step * (c - 0.5);
        P.inkAdd(H.line(cx, y1, cx, y1 + 16, { stroke: p.structure, width: 2.4, opacity: 0.75, amp: 1.2, seed: 300 + c * 11 }));
        P.slot(`bar-${c}`, cx - barW / 2, y0, barW, y1 - y0, { role: "bar", region: true, growth: "up-from-baseline", baselineY: Math.round(y1) });
        P.slot(`value-${c}`, cx - step / 2, y0 - 50, step, 46, { align: "center", role: "value" });
        P.slot(`head-${c}`, cx - step / 2, y1 + 30, step, 52, { align: "center", role: "period" });
      }
    } else {
      const step = (x1 - x0) / (ticks - 1);
      for (let c = 1; c <= ticks; c++) {
        const cx = x0 + step * (c - 1);
        P.inkAdd(H.line(cx, y1, cx, y1 + (o.type === "line-dense" ? 11 : 16), { stroke: p.structure, width: o.type === "line-dense" ? 1.9 : 2.4, opacity: 0.7, amp: 1.2, seed: 300 + c * 11 }));
        if (o.type === "line-6y") {
          const px = Math.max(x0, Math.min(x1 - 84, cx - 42));
          P.slot(`point-${c}`, px, y0, 84, y1 - y0, { role: "point-column", region: true, anchorX: Math.round(cx) });
          const vw = Math.min(152, step * 0.8);
          P.slot(`value-${c}`, cx - vw / 2, y0 - 50, vw, 46, { align: "center", role: "value" });
          P.slot(`head-${c}`, cx - (land ? 84 : 62), y1 + 30, land ? 168 : 124, 52, { align: "center", role: "period" });
        }
      }
      if (o.type === "line-dense") {
        // a price chart is labelled at a handful of dates, not at every tick
        const anchors = [1, 5, 9, 12];
        const hw = step * 2;
        anchors.forEach((t, k) => {
          const cx = x0 + step * (t - 1);
          const hx = Math.max(12, Math.min(w - hw - 12, cx - hw / 2));
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
    const m = land ? { l: 118, r: 118, t: 78, b: 74 } : { l: 48, r: 48, t: 180, b: 200 };
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
      total: { font: "Courier Prime", size: fit(0.72, 30, 44), weight: 700, colour: "structure", maxChars: 7 },
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
    P.colourAdd(surfaceFurniture(P, SURFACES[p.surfaceKey]));
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
  function leader(P, x1, x2, y, seed, op) {
    const step = 21, len = 7;
    let i = 0;
    for (let x = x1; x < x2 - len; x += step) {
      P.inkAdd(H.line(x, y, x + len, y - 1, {
        stroke: P.pal.structure, width: 2, opacity: op == null ? 0.24 : op,
        amp: 1.1, over: 0, step: 4, seed: seed + i * 3,
      }));
      i += 1;
    }
  }

  // A ground2 panel. Gives a figure something to stand on — the single biggest
  // reason the old figure plates read as floating in a void.
  function field(P, x, y, w, h, seed, op) {
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
        P.inkAdd(H.line(rx, y + rh / 2, rx + rw, y + rh / 2 - 5, {
          stroke: P.pal.structure, width: b.weight || 6, opacity: 0.9, amp: 3.4, over: 13, seed: b.seed || 211,
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
    P.slot("input", 90, midY - 90, 240, 180, { align: "left", role: "label" });
    const gap = 84;
    const startX = 90 + 240 + gap;
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
    P.slot("output", outX + 34, midY - 100, w - outX - 124, 200, { align: "left", role: "statement" });
    P.slot("caption", 150, h - 150, w - 300, 70, { align: "left", role: "caption" });
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
    const P = base(o, "big-number-l" + o.layout, figRoles(land, land ? 350 : 250));
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
    const P = base(o, "compare-" + o.mode, figRoles(land, land ? 170 : 160));
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
    P.colourAdd(H.hatch(H.polyRect(x, y, w, h), { color: p.ground2, opacity: 0.45, gap: 8.5, width: 13, angle: -3, over: 20, seed: seed }));
    P.inkAdd(H.outline(H.polyRect(x, y, w, h), { stroke: p.structure, width: 4.2, opacity: 0.9, amp: 3.6, over: 14, seed: seed + 1 }));
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
        P.slot(`date-${i}`, cx - step * 0.46, up ? y - 116 : y + 52, step * 0.92, 48, { align: "center", role: "date" });
        P.slot(`label-${i}`, cx - step * 0.46, up ? y - 236 : y + 108, step * 0.92, 110, { align: "center", role: "label" });
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
      P.slot(`head-${c + 1}`, Math.max(0, cx - pStep / 2), band.y + band.h + Math.round(u * 0.7), pStep, headH, { align: "center", role: "period" });
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
    const ih = land ? h * 0.6 : h * 0.44;
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

    P.inkAdd(S.outline(head, { stroke: ink, width: 6.4 * lw, opacity: 0.97, amp: 2.4, over: 10, seed: 708 }));
    P.inkAdd(S.outline(head, { stroke: ink, width: 4.2 * lw, opacity: 0.92, amp: 2.6, over: 12, seed: 703 }));
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

      P.topAdd(S.outline(lens, { stroke: ink, width: 3.4 * lw, opacity: 0.9, amp: 1.6, over: 6, seed: 725 + i }));
      P.topAdd(S.stroke(GM([{ x: lx + s * R * 0.28, y: eyeY - R * 0.05 }, { x: hcx + s * R * 0.83, y: hcy - R * 0.04 }]), { stroke: ink, width: 2.6, opacity: 0.66, amp: 1.2, over: 4, seed: 727 + i }));
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
    if (mouthOpen) {
      const m = M(ell(hcx, hcy + R * 0.62, R * 0.15, R * 0.11, seg ? 16 : 14, 0.05, 751));
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
    const shirt = OUT.top, trouser = OUT.leg, shoeC = "#1E242B", skin = "#C99A6E", hair = "#3B3129";
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
    const at = function (n) { return topY + HU * n; };
    const headCy = at(0.46) + bob;
    const shoulderY = at(1.30) + bob * 0.5, chestY = at(1.85), waistY = at(2.6);
    const hipY = at(3.1), kneeY = at(4.85), ankleY = at(6.55);
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
    const mass = function (poly, colour, op, lw, ang, seed) {
      const c = centroid(poly);
      P.colourAdd(S.hatch(poly, { color: colour, opacity: op, gap: 6.8, width: 11.5, angle: ang, over: 11, seed: seed }));
      // the turned form, in ink: this is what carries his contrast
      const inboard = c.x < cx ? clipHalf(poly, -1, 0, -c.x) : clipHalf(poly, 1, 0, c.x);
      if (inboard) P.colourAdd(S.hatch(inboard, { color: ink, opacity: 0.2, gap: 8, width: 12, angle: ang - 6, over: 8, seed: seed + 3 }));
      P.inkAdd(S.outline(poly, { stroke: ink, width: lw * 1.35, opacity: 0.97, amp: 2.8, over: 10, seed: seed + 1 }));
    };
    const dot = function (x, y, r, seed) {
      P.topAdd(S.hatch(ell(x, y, r, r, 12, 0.05, seed), { color: ink, opacity: 0.95, gap: 2.4, width: 4.4, angle: -60, over: 3, seed: seed + 1 }));
    };

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
      mass(quad(hipP, kneeP, HU * 0.31, HU * 0.24), trouser, 0.88, 4.2, -70 + i * 8, 601 + i * 9);
      mass(quad(kneeP, ankP, HU * 0.24, HU * 0.17), trouser, 0.88, 4.0, -70 + i * 8, 615 + i * 9);
      const dir = pose === "walking-out-of-frame" ? 1 : (i === 0 ? -1 : 1);
      const L = HU * 0.6, hgt = HU * 0.19;
      const sh = [
        { x: ankP.x - L * 0.3 * dir, y: ankleY + hgt * 0.1 },
        { x: ankP.x + L * 0.72 * dir, y: ankleY + hgt * 0.42 },
        { x: ankP.x + L * 0.7 * dir, y: floorY }, { x: ankP.x - L * 0.34 * dir, y: floorY },
      ];
      P.colourAdd(S.hatch(sh, { color: shoeC, opacity: 0.66, gap: 5.6, width: 9, angle: -8, over: 8, seed: 626 + i }));
      P.inkAdd(S.outline(sh, { stroke: ink, width: 3.6, opacity: 0.92, amp: 2, over: 8, seed: 629 + i }));
      P.inkAdd(S.line(sh[3].x, floorY - hgt * 0.3, sh[2].x, floorY - hgt * 0.32, { stroke: ink, width: 2.4, opacity: 0.5, amp: 1.3, over: 5, step: 6, seed: 633 + i }));
    });

    // ---- neck, drawn BEFORE the shirt so the collar sits on top of it ------
    const nTop = { x: cx + leanAt(headCy + HU * 0.4), y: headCy + HU * 0.36 + HEAD_SINK };
    const nBot = { x: cx + leanAt(shoulderY), y: shoulderY + HU * 0.12 };
    mass(quad(nTop, nBot, HU * 0.19, HU * 0.24), skin, 0.44, 3.0, -84, 641);

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
    mass(torso, shirt, 0.88, 4.8, -78, 651);
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
    P.inkAdd(S.stroke([
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
    // placket and hem: two quiet lines that tell you it is a shirt
    P.inkAdd(S.line(cx + leanAt(shoulderY + HU * 0.4), shoulderY + HU * 0.4, cx + leanAt(waistY), waistY + HU * 0.2, { stroke: ink, width: 2.2, opacity: 0.3, amp: 2.2, over: 5, step: 7, seed: 657 }));
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
      mass(quad(sh, el, HU * 0.27, HU * 0.21), shirt, 0.86, 4.0, -60 + i * 20, 661 + i * 17);
      mass(quad(el, hd, HU * 0.19, HU * 0.15), OUT.sleeves === "rolled" ? skin : skin, 0.46, 3.6, -60 + i * 20, 681 + i * 17);
      if (OUT.sleeves === "rolled") {
        // the fold itself: a short heavy band across the elbow
        P.inkAdd(S.stroke([{ x: el.x - HU * 0.2, y: el.y - HU * 0.04 }, { x: el.x + HU * 0.2, y: el.y + HU * 0.02 }], { stroke: ink, width: 5.4, opacity: 0.9, amp: 2, over: 6, seed: 751 + i }));
        P.colourAdd(S.hatch(quad(sh, el, HU * 0.27, HU * 0.21).slice(0, 4), { color: shirt, opacity: 0.3, gap: 8, width: 11, angle: -60 + i * 20, over: 8, seed: 755 + i }));
      }
      if (OUT.layer === "cardigan") {
        // the cardigan carries down the upper arm
        P.colourAdd(S.hatch(quad(sh, el, HU * 0.28, HU * 0.22), { color: "#5A5F5C", opacity: 0.82, gap: 6.4, width: 10, angle: -60 + i * 20, over: 9, seed: 761 + i * 5 }));
        P.inkAdd(S.outline(quad(sh, el, HU * 0.28, HU * 0.22), { stroke: ink, width: 4.2, opacity: 0.92, amp: 2.2, over: 8, seed: 765 + i * 5 }));
      }
      const hand = ell(hd.x, hd.y + HU * 0.12, HU * 0.19, HU * 0.17, 16, 0.06, 691 + i);
      P.colourAdd(S.hatch(hand, { color: skin, opacity: 0.5, gap: 5.6, width: 9, angle: -70, over: 7, seed: 695 + i }));
      P.inkAdd(S.outline(hand, { stroke: ink, width: 3.4, opacity: 0.9, amp: 1.9, over: 7, seed: 699 + i }));
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
    return P;
  }

  const HOST_POSES = ["leaning-on-desk", "hands-in-pockets", "holding-a-page", "pointing-down-at-desk", "head-in-hands", "walking-out-of-frame"];

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
    const shirt = OUT.top, skin = "#C99A6E", hair = "#3B3129";
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

    const mass = function (poly, colour, op, lw, ang, seed) {
      const c = centroid(poly);
      P.colourAdd(S.hatch(poly, { color: colour, opacity: op, gap: 6.8, width: 11.5, angle: ang, over: 11, seed: seed }));
      const inboard = c.x < cx ? clipHalf(poly, -1, 0, -c.x) : clipHalf(poly, 1, 0, c.x);
      if (inboard) P.colourAdd(S.hatch(inboard, { color: ink, opacity: 0.2, gap: 8, width: 12, angle: ang - 6, over: 8, seed: seed + 3 }));
      P.inkAdd(S.outline(poly, { stroke: ink, width: lw * 1.35, opacity: 0.97, amp: 2.8, over: 10, seed: seed + 1 }));
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
    const neckBot = shoulderY - R * (close ? 0.18 : 0.14);
    const neckPoly = quad({ x: hcx, y: neckTop }, { x: cx, y: neckBot }, R * 0.36, R * 0.42);
    // NO CLOSED OUTLINE ON THE NECK. mass() puts every hatch on the colour layer
    // and every line on the ink layer, so a neck outlined as a quad has its bottom
    // edge painted on top of the shirt that is meant to cover it. At full-figure
    // size the collar hides that; at these sizes it is a box drawn on his chest.
    // Two side lines from jaw to collar is all a neck needs.
    P.colourAdd(S.hatch(neckPoly, { color: skin, opacity: 0.44, gap: 6.8, width: 11.5, angle: -84, over: 11, seed: 641 }));
    const inb = clipHalf(neckPoly, -1, 0, -cx);
    if (inb) P.colourAdd(S.hatch(inb, { color: ink, opacity: 0.2, gap: 8, width: 12, angle: -90, over: 8, seed: 644 }));
    [-1, 1].forEach(function (s, i) {
      P.inkAdd(S.stroke([{ x: cx + s * R * 0.36, y: neckTop }, { x: cx + s * R * 0.40, y: neckBot }], { stroke: ink, width: close ? 4.4 : 3.8, opacity: 0.9, amp: 2, over: 7, seed: 646 + i }));
    });
    mass(torso, shirt, 0.88, close ? 5.6 : 5, -78, 651);
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
    P.inkAdd(S.stroke([
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
    P.inkAdd(S.line(cx, shoulderY + HU * 0.4, cx, close ? h : waistY + HU * 0.2, { stroke: ink, width: 2.2, opacity: 0.3, amp: 2.2, over: 5, step: 7, seed: 657 }));
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
      mouthOpen: mouthOpen, closedEyes: false, glance: o.glance || 0,
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
    P.slot("mouth", hcx - R * 0.26, hcy + R * 0.44, R * 0.52, R * 0.34, { role: "mouth", region: true, note: "talk frames differ here only" });
    P.slot("eyes", hcx - R * 0.7, eyeY - R * 0.3, R * 1.4, R * 0.6, { role: "eyes", region: true, note: "the eye line is fit.eyeLineY; this box is the pair" });
    P.slot("head", hcx - R * 0.9, hcy - R * 1.12, R * 1.8, R * 2.1, { role: "head", region: true });
    P.slot("figure", 0, hcy - R * 1.2, w, h - (hcy - R * 1.2), { role: "figure", region: true, note: "visible extent only. There is no floorLineY on this plate and this box is NOT a scaling authority — see meta.fit" });
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
        contact(x + w * 0.07, y + h, w * 0.05, seed + 60);
        contact(x + w * 0.93, y + h, w * 0.05, seed + 64);
      },

      // sits ON deskTop: foot plate on the surface, neck, then the panel above it
      monitor: function (x, deskTop, w, hh, seed) {
        const ww = w, hd = hh;
        const bot = deskTop - q(46), top = bot - hd;
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
        thin([{ x: -20, y: ceilY }, { x: cornerX, y: ceilY + 2 }], 0.3, 3, seed + 84);
        thin([{ x: cornerX, y: ceilY }, V.to(cornerX, ceilY, tFar * 0.6), V.to(cornerX, ceilY, tFar)], 0.3, 3, seed + 86);
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

  function room(o) {
    const land = o.w > o.h, w = o.w, h = o.h, p = o.pal, angle = o.angle;
    const P = base(o, "room-" + angle, {
      title: { font: "Archivo Narrow", size: land ? 76 : 62, weight: 700, colour: "structure", tracking: "-.02em", maxLines: 3, maxCharsPerLine: land ? 22 : 16 },
      kicker: TR.kicker, caption: TR.caption,
    });
    P.meta.family = "room";
    P.meta.angle = angle;
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

    const zoom = k * (angle === "wide-tight" || angle === "desk-corner" ? 1.45 : 1);
    const u = function (n) { return n * zoom; };
    const deskH = u(230), deskTop = floorY - deskH;
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
      const deskTopY = floorY - h * (land ? 0.22 : 0.17);
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
      contact = { pose: "leaning-on-desk", surface: "desk top, near end", x: Math.round(edge.x - u(150) * edge.s), y: Math.round(edge.y) };
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
    if (angle === "high-desk-down") {
      P.meta.hostAnchor = false;
      P.meta.hostAnchorNote = "Deliberately none. This camera is above the desk looking down at the surface: no floor line is in frame, and a standing cut-out has nothing to stand on. Cut to this plate over his voice, or pair it with a hand or forearm plate — which this pack does not yet carry. Do not synthesise a position.";
    } else {
      const anchorH = angle === "low-desk-height" ? floorY - Math.round(h * 0.20) : Math.round(h * 0.52);
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

  g.PLATES = { ROLES, SURFACES, pal, numbersSheet, rowBand, threeSeries, swatch, surfaceCard, chartFrame, cashFlow, headlineBand, bothTrue, unitLadder, closingPlate, rowSpotlight, flowPlate, bigNumber, bigFraction, compare, definitionCard, quotePull, criteriaCard, timeline, mediaFrame, captureFrame, hookCard, hostFigure, hostHead, HOST_POSES, HOST_FRAMINGS, HOST_OUTFITS, ellipse, room, wallOfCalls, ROOM_ANGLES, ROOM_CAMERA_ANGLES, annotation, ANNOTATIONS, peerStrip, cycleFrame };
})(typeof window !== "undefined" ? window : globalThis);
