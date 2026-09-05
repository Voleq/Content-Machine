// dennis-v2 / engine / series.js
//
// The DATA renderers. Every plate in this library draws furniture and reserves a
// region — plot-area, spark-N — and knows nothing about numbers. This is the
// other half: given values and a box, it draws the series in the same hand.
//
// Why it is not part of plates.js: a plate is reproducible from its key alone,
// which is what makes the contact sheets and the audit trustworthy. A series is
// reproducible only from its data, which arrives at render time (Yahoo, a filing,
// the episode file). Keeping them apart is what stops a plate from pretending to
// know something it cannot.
//
// Both renderers return the geometry they used — points, ticks, the zero line —
// so the caller can put labels and marks on REAL coordinates instead of guessing
// where the series ended up. That is what a region slot could never tell you.
(function (g) {
  const H = g.HAND;

  // Axis steps a person would choose: 1, 2, 2.5, 5, 10 and their decades.
  function niceStep(span, target) {
    const raw = span / Math.max(1, target);
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const n = raw / mag;
    return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10) * mag;
  }

  // The domain is padded to whole steps, and ALWAYS includes zero when the data
  // crosses it — a free-cash-flow series that goes negative is a different claim
  // from one that does not, and an axis that hides the crossing tells the wrong
  // one. Never pad a domain that is entirely one side of zero into the other.
  function domain(values, ticks) {
    const vals = values.filter((v) => typeof v === "number");
    let lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals);
    if (lo > 0 && hi > 0) lo = 0;
    else if (lo < 0 && hi < 0) hi = 0;
    if (lo === hi) { hi = lo + Math.abs(lo || 1); }
    const step = niceStep(hi - lo, (ticks || 5) - 1);
    return { lo: Math.floor(lo / step) * step, hi: Math.ceil(hi / step) * step, step: step };
  }

  function ticksOf(d) {
    const out = [];
    // count from zero outward so zero is always ON a tick, never between two
    for (let v = Math.ceil(d.lo / d.step) * d.step; v <= d.hi + d.step * 1e-6; v += d.step) {
      out.push(Math.abs(v) < d.step * 1e-6 ? 0 : Number(v.toFixed(10)));
    }
    return out;
  }

  // ---- the line ----------------------------------------------------------
  // o: { box, values, pal, seed, subject, ticks, unitFmt }
  // subject false draws the other party (a peer, consensus) in its own colour.
  function line(o) {
    const b = o.box, v = o.values, p = o.pal;
    const seed = o.seed || 900;
    const d = domain(v, o.ticks || 5), tk = ticksOf(d);
    const yOf = (val) => b.y + b.h - ((val - d.lo) / (d.hi - d.lo)) * b.h;
    const xOf = (i) => b.x + (v.length === 1 ? b.w / 2 : (i / (v.length - 1)) * b.w);
    const colour = o.subject === false ? p.otherParty : p.structure;
    const k = Math.min(b.w, b.h) / 700;                 // weights scale with the box
    const out = [];

    // gridlines first, and the zero line heavier than the rest: it is the only
    // gridline that means something.
    tk.forEach((t, i) => {
      const zero = t === 0 && d.lo < 0;
      out.push(H.line(b.x, yOf(t), b.x + b.w, yOf(t), {
        stroke: p.structure, width: zero ? 3.4 : 1.8, opacity: zero ? 0.5 : 0.18,
        amp: 3, over: 9, seed: seed + 40 + i * 7,
      }));
    });

    const pts = v.map((val, i) => ({ x: xOf(i), y: yOf(val), value: val }));
    out.push(H.stroke(pts, {
      stroke: colour, width: Math.max(3.4, 5.2 * k * 1.4), opacity: 0.95,
      amp: 2.6, over: 7, seed: seed,
    }));
    // the last observation gets a mark; the rest do not. A dot on every point is
    // a table with extra steps.
    const last = pts[pts.length - 1];
    out.push(dot(last.x, last.y, Math.max(9, 13 * k * 1.4), colour, seed + 3));
    return { svg: out.join(""), points: pts, ticks: tk, domain: d, yOf: yOf, xOf: xOf };
  }

  function ring(cx, cy, r, seed, n, jit) {
    const N = n || 14, J = jit == null ? 0.16 : jit;
    const rng = H.rng(seed), pts = [];
    for (let i = 0; i < N; i++) {
      const a = (i / N) * Math.PI * 2, k = 1 + (rng() - 0.5) * J;
      pts.push({ x: cx + Math.cos(a) * r * k, y: cy + Math.sin(a) * r * k });
    }
    return pts;
  }

  // A drawn dot has to read as a POINT. The old mark hatched a 14-gon jittered
  // +/-8% and filled it with width-9 strokes on a 3.4 gap — nearly three deep,
  // so the centre went solid and the jitter showed as a lumpy edge: an ink clot
  // where the plate promised a moment. Round the polygon, tile the hatch instead
  // of piling it (width just over gap), and let one outline pass carry the edge.
  // Weights are fractions of r, so a mark scales without changing character.
  function dot(cx, cy, r, colour, seed, opacity) {
    const op = opacity == null ? 0.95 : opacity;
    // FILLED, not hatched. Hatching a mark-sized polygon can only ever knot: the
    // strokes are a meaningful fraction of the diameter, so they read as scribble
    // rather than as ink. A closed wobbly polygon filled flat is what a pen
    // actually leaves — solid centre, slightly irregular edge — and it holds that
    // character at any radius. One soft outline pass sits the edge on the paper.
    const poly = ring(cx, cy, r, seed, 30, 0.07);
    return `<path d="${H.toPath(poly.concat([poly[0]]))}" fill="${colour}" fill-opacity="${op}"/>`
      + H.outline(poly, {
        stroke: colour, width: Math.max(1.6, r * 0.13), opacity: op * 0.85,
        amp: Math.max(0.4, r * 0.035), over: 2, seed: seed + 2,
      });
  }

  // ---- the sparkline -----------------------------------------------------
  // Bars, not a line: at spark size a line is three pixels of slope and reads as
  // noise, while bars keep a per-period silhouette you can actually compare.
  //
  // Each bar is one thick STROKE, never a hatched rect: hatch gap and overshoot
  // are canvas-unit quantities, so a hatched 14-unit bar degenerates into a
  // hollow outline with spikes. This is the same law that governs the contact
  // sheets and the boil.
  function sparkBars(o) {
    const b = o.box, v = o.values, p = o.pal;
    const seed = o.seed || 1200;
    const d = domain(v, 3);
    const yOf = (val) => b.y + b.h - ((val - d.lo) / (d.hi - d.lo)) * b.h;
    const zeroY = yOf(0);
    const n = v.length;
    const pitch = b.w / n;
    const bw = Math.max(4, pitch * 0.62);
    const out = [];

    if (d.lo < 0) {
      out.push(H.line(b.x - 4, zeroY, b.x + b.w + 4, zeroY, {
        stroke: p.structure, width: 2, opacity: 0.42, amp: 2, over: 6, seed: seed + 1,
      }));
    }
    const bars = [];
    // A real value must never render as nothing: in this library an empty cell
    // means NO DATA, so a 7% bar against a 56% peak — or a -$120M against a
    // +$4.5B — has to stay visible or the sparkline lies about the period. The
    // floor is a legible stub rather than a hairline: "present but small" is a
    // reading a viewer can have, "absent" is not, and the cell beside it carries
    // the exact figure anyway.
    const minLen = Math.max(6, b.h * 0.14);
    v.forEach((val, i) => {
      const cx = b.x + pitch * (i + 0.5);
      let y = yOf(val);
      if (typeof val === "number" && Math.abs(y - zeroY) < minLen) {
        y = zeroY + (val < 0 ? minLen : -minLen);
      }
      const top = Math.min(y, zeroY), bot = Math.max(y, zeroY);
      // the latest period is the subject of the sentence, so it carries weight;
      // the rest are neutral data. No direction colour — a sparkline is a shape,
      // and the cells beside it already carry the sign.
      const latest = i === n - 1;
      // Opacity is legibility, not emphasis. The numbers sheet zebra-stripes its
      // even rows in ground2, and neutral data at 0.62 on that stripe is simply
      // gone — the same defect that made the row band invisible. The earlier
      // periods read at 0.88; the latest still separates by colour and weight.
      out.push(H.line(cx, bot, cx, top, {
        stroke: latest ? p.structure : p.neutralData,
        width: bw, opacity: latest ? 0.95 : 0.88,
        // step is the wobble's sampling interval and it defaults to 26 units —
        // longer than a short bar, so a 27-unit bar got ONE sample and its path
        // collapsed to nothing. Every bar under ~35u silently vanished. Sample
        // fine enough that the shortest possible bar is still a line.
        step: 5,
        cap: "butt",
        amp: Math.max(0.7, bw * 0.06), over: 0,
        seed: seed + 10 + i * 13,
      }));
      bars.push({ x: cx, y: y, w: bw, value: val, latest: latest });
    });
    return { svg: out.join(""), bars: bars, zeroY: zeroY, domain: d };
  }

  // ---- the cycle path ----------------------------------------------------
  // then → now is not a trajectory. The reason cycles/cycle-frame exists is that
  // the line between two moments went somewhere else first, so this renderer
  // draws every intervening period and returns the MINIMUM — the trough is the
  // claim, and the operator labels it on real coordinates rather than guessing
  // where the low point landed.
  //
  // One colour, structure, for the whole path: the segment before the trough is
  // not a different series, and colouring the fall in `down` and the recovery in
  // `up` would make the frame argue for the recovery. The ends are ringed
  // because they are the two figures in type; the trough is ringed hollow in
  // `down` because it is the one that has no figure beside it.
  function cycleArc(o) {
    const b = o.box, v = o.values, p = o.pal;
    const seed = o.seed || 1500;
    const d = domain(v, 3);
    const yOf = (val) => b.y + b.h - ((val - d.lo) / (d.hi - d.lo)) * b.h;
    const xOf = (i) => b.x + (v.length === 1 ? b.w / 2 : (i / (v.length - 1)) * b.w);
    const k = Math.min(b.w, b.h) / 700;
    const out = [];

    if (d.lo < 0) {
      out.push(H.line(b.x - 6, yOf(0), b.x + b.w + 6, yOf(0), {
        stroke: p.structure, width: 3, opacity: 0.45, amp: 2.4, over: 8, seed: seed + 2,
      }));
    }
    const pts = v.map((val, i) => ({ x: xOf(i), y: yOf(val), value: val }));
    out.push(H.stroke(pts, {
      stroke: p.structure, width: Math.max(4.6, 6 * k * 1.4), opacity: 0.95,
      amp: 2.4, over: 8, seed: seed,
    }));

    let lo = 0;
    v.forEach((val, i) => { if (typeof val === "number" && val < v[lo]) lo = i; });
    // The two moments get a filled dot, not a hatched blob: `over` overshoots
    // every hatch stroke past the outline, and 8 units of overshoot on a 30-unit
    // circle is a capsule. Small over, tight gap — it has to read as a point.
    [0, v.length - 1].forEach((i, n) => {
      out.push(dot(pts[i].x, pts[i].y, Math.max(9, 13 * k * 1.4), p.structure, seed + 7 + n));
    });
    if (lo !== 0 && lo !== v.length - 1) {
      out.push(H.outline(ring(pts[lo].x, pts[lo].y, Math.max(13, 20 * k * 1.4), seed + 21), {
        stroke: p.down, width: Math.max(3.4, 4.6 * k * 1.4), opacity: 0.95, amp: 2, over: 6, seed: seed + 23,
      }));
    }
    return { svg: out.join(""), points: pts, trough: Object.assign({ i: lo }, pts[lo]), domain: d, yOf: yOf, xOf: xOf };
  }

  // ---- the row bars -------------------------------------------------------
  // The peer strip's move as a shape as well as a figure. One horizontal bar per
  // row on a scale SHARED across the rows — that shared scale is the whole point:
  // per-row scaling would draw four bars of the same length and say nothing.
  //
  // The zero rule is placed by the domain, not by the plate: when every move is
  // red, zero is the right-hand edge and every bar runs left from it, which is
  // the shape the beat has. The plate cannot know that, so it reserves the column
  // and this draws the rule.
  function rowBars(o) {
    const b = o.box, v = o.values, p = o.pal;
    const n = o.rows || v.length;
    const seed = o.seed || 1400;
    const nums = v.filter((x) => typeof x === "number");
    if (!nums.length) return { svg: "", bars: [] };
    const d = domain(v, 3);
    const xOf = (val) => b.x + ((val - d.lo) / (d.hi - d.lo)) * b.w;
    const zeroX = xOf(0);
    const pitch = b.h / n;
    const bh = Math.max(7, pitch * 0.3);
    const out = [];
    out.push(H.line(zeroX, b.y - 6, zeroX, b.y + b.h + 6, {
      stroke: p.structure, width: 2.2, opacity: 0.45, amp: 2, over: 7, seed: seed + 1,
    }));
    const bars = [];
    // Same law as the sparkline: a real value never renders as nothing, because
    // an empty cell in this library means NO DATA. A -1% against a -12% is a stub,
    // not an absence — and the figure beside it carries the exact number anyway.
    const minLen = Math.max(7, b.w * 0.05);
    v.forEach((val, i) => {
      if (typeof val !== "number") return;
      const cy = b.y + pitch * (i + 0.5);
      let x = xOf(val);
      if (Math.abs(x - zeroX) < minLen) x = zeroX + (val < 0 ? -minLen : minLen);
      out.push(H.line(zeroX, cy, x, cy, {
        stroke: val < 0 ? p.down : p.up, width: bh, opacity: i === 0 ? 0.95 : 0.82,
        step: 5, cap: "butt", amp: Math.max(0.7, bh * 0.05), over: 0, seed: seed + 10 + i * 13,
      }));
      bars.push({ x: x, y: cy, value: val, subject: i === 0 });
    });
    return { svg: out.join(""), bars: bars, zeroX: zeroX, domain: d };
  }

  // ---- the range mark ----------------------------------------------------
  // tables/multiples-strip reserves marker-N and draws the rail under it. This
  // is what sits on the rail, and it arrives here rather than in the plate for
  // the usual reason: a percentile is data, and a plate that drew a position
  // would be inventing one.
  //
  // t is a POSITION, not a value: 0 at the low end of the peer range, 1 at the
  // high end. The caller does that division, because only the caller knows
  // whether the range is the peer min/max, the interquartile band or five years
  // of the subject's own history — three different claims that all land on the
  // same rail.
  //
  // NO DIRECTION COLOUR. The subject is structure and the median is otherParty,
  // the same two roles the strip's figures use. A marker in `down` because it
  // sits high would argue the short before the script does.
  //
  // OFF THE RANGE IS A READING, NOT AN ERROR. A subject priced above every peer
  // is the most interesting case this plate has, so t > 1 clamps the dot to the
  // end tick and adds a chevron past it. Dropping the mark, or letting it draw
  // outside the region, would both lose the one row worth talking about.
  function rangeMark(o) {
    const b = o.box, p = o.pal, seed = o.seed || 1600;
    const cy = b.y + b.h / 2;
    const r = Math.max(9, b.h * 0.3);
    const clamp = (v) => Math.max(0, Math.min(1, v));
    // The scale is INSET BY THE MARK'S OWN RADIUS, which is the difference
    // between a position and a dot at a position. Mapped edge to edge, a subject
    // level with the top peer draws a dot centred on the high end tick: it hides
    // the tick it is being measured against and half of it lands outside the
    // region the plate reserved. Inset, t = 1 sits tangent to that tick, nothing
    // paints past the box, and the two ends stay readable as ends.
    const xAt = (t) => b.x + r + clamp(t) * (b.w - r * 2);
    const out = [];

    // The median as a TICK, not a second dot: two dots on one rail read as two
    // subjects, and the peer set is not a subject.
    if (typeof o.median === "number") {
      out.push(H.line(xAt(o.median), cy - b.h * 0.4, xAt(o.median), cy + b.h * 0.4, {
        stroke: p.otherParty, width: Math.max(3.4, r * 0.42), opacity: 0.9,
        step: 5, cap: "butt", amp: 1.2, over: 2, seed: seed + 3,
      }));
    }

    const t = typeof o.t === "number" ? o.t : 0.5;
    const off = t > 1 ? 1 : t < 0 ? -1 : 0;
    // Off the range: the dot is pushed against its end tick from the INSIDE and
    // a chevron points out past it, both still inside the region. The first
    // version drew the chevron beyond the end, which put ink outside the box the
    // plate reserved and stuck the arrow onto the side of the dot.
    const x = xAt(t) - off * r * 1.9;
    out.push(dot(x, cy, r, p.structure, seed));
    if (off) {
      const tip = xAt(t) + off * r * 0.85;
      out.push(H.stroke([
        { x: tip - off * r * 0.8, y: cy - r * 0.6 },
        { x: tip, y: cy },
        { x: tip - off * r * 0.8, y: cy + r * 0.6 },
      ], { stroke: p.structure, width: Math.max(2.6, r * 0.2), opacity: 0.9, amp: 1.1, over: 3, seed: seed + 9 }));
    }
    return { svg: out.join(""), x: x, cy: cy, r: r, t: t, offRange: off !== 0 };
  }

  g.SERIES = { line: line, sparkBars: sparkBars, cycleArc: cycleArc, rowBars: rowBars, rangeMark: rangeMark, domain: domain, ticksOf: ticksOf, niceStep: niceStep };
  if (typeof module !== "undefined") module.exports = g.SERIES;
})(typeof window !== "undefined" ? window : globalThis);
