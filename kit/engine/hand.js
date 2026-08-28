/* Dennis v2 — hand engine.
   Deterministic procedural drawing. Every plate is drawn by this file, and the
   manifest is emitted by the same call that draws it (see plates.js). Never
   measure a plate afterwards.

   Principles encoded here:
   - no perfect line: every stroke is resampled, perpendicular-noised, and overshoots its ends
   - two passes per stroke (pressure): a light wide pass + a darker narrow pass, offset
   - colour is laid as hatch strokes INSIDE an outline and deliberately misses it
   - line work is emitted after colour, always
*/
(function (g) {
  const RAD = Math.PI / 180;

  // THE BOIL.
  //
  // Everything that is not a data plate moves at two frames. Rather than touching
  // a hundred authors, the offset goes in here: every drawn line's geometry comes
  // from wobble() and hatch(), and both seed their randomness from rng(). Shift
  // that seed and the identical drawing is re-wobbled — same shapes, same layout,
  // a live line. Frame 2 IS frame 1 drawn again by the same hand.
  //
  // It deliberately does NOT reach two things. Plate randomness (P._r) drives
  // content placement, so shifting it would move props between frames rather than
  // wobble them. And the paper grain does not boil: the sheet is not being
  // redrawn, only the ink on it.
  // The offset must PERTURB the hand, not replace it. Reseeding rng() outright
  // swapped the whole drift table, which moved points by 8% of frame width — that
  // is not a boil, it is redrawing the plate from scratch, and props visibly
  // jumped. So the base wobble keeps its own seed and its own call sequence
  // (identical resampling, so frames stay point-for-point comparable) and the boil
  // adds a small extra displacement from a SEPARATE generator on top.
  //
  // AMPLITUDE IS AN ABSOLUTE, NOT A PERCENTAGE: ~2 canvas units of movement per
  // point, on every asset, whatever its size.
  //
  // A percentage was the wrong unit and it was mine to get wrong. Scaled off the
  // stroke's own wobble amplitude, the same nominal figure produced 1.57u on a
  // room and 0.10u on a scrawled oval — a 15x spread, one of them invisible —
  // and I reported that as "uneven coverage" when the real fault was the unit.
  // Scaled off FRAME height it is worse in the other direction: 1% of 1080 is
  // 11u, which pulls a mug outline into a different mug between frames.
  //
  // A boil is a hand redrawing the same line, and a hand's variance does not
  // care how big the sheet is. So: 2 units, flat. A 300-unit annotation and a
  // 1920-unit room boil by the same absolute amount, which is what makes them
  // sit together in one cut.
  let BOIL = 0;
  const BOIL_AMP = 2.0;
  function setBoil(n) { BOIL = n | 0; }

  function rng(seed) {
    let a = (seed | 0) >>> 0 || 1;
    return function () {
      a += 0x6d2b79f5;
      let t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  const num = (n) => (Math.round(n * 100) / 100).toString();

  // Catmull-rom -> cubic bezier, so a noised polyline reads as one drawn gesture
  function toPath(pts) {
    if (pts.length < 2) return "";
    let d = `M${num(pts[0].x)} ${num(pts[0].y)}`;
    if (pts.length === 2) return d + `L${num(pts[1].x)} ${num(pts[1].y)}`;
    for (let i = 0; i < pts.length - 1; i++) {
      const p0 = pts[i - 1] || pts[i], p1 = pts[i], p2 = pts[i + 1], p3 = pts[i + 2] || p2;
      const c1 = { x: p1.x + (p2.x - p0.x) / 6, y: p1.y + (p2.y - p0.y) / 6 };
      const c2 = { x: p2.x - (p3.x - p1.x) / 6, y: p2.y - (p3.y - p1.y) / 6 };
      d += `C${num(c1.x)} ${num(c1.y)} ${num(c2.x)} ${num(c2.y)} ${num(p2.x)} ${num(p2.y)}`;
    }
    return d;
  }

  // Resample a polyline and push each interior point off-axis. Low-frequency drift
  // (the wrist) + high-frequency tremor (the hand).
  function wobble(pts, o) {
    const r = rng(o.seed || 1);
    const br = BOIL ? rng((o.seed || 1) * 31 + BOIL * 9173) : null;
    const amp = o.amp == null ? 1.7 : o.amp;
    const stepIn = o.step || 26;
    const overIn = o.over == null ? 5 : o.over;
    const out = [];
    const drift = [];
    for (let i = 0; i < 64; i++) drift.push(r() - 0.5);
    let dphase = r() * 6.28;

    const segs = [];
    let total = 0;
    for (let i = 0; i < pts.length - 1; i++) {
      const dx = pts[i + 1].x - pts[i].x, dy = pts[i + 1].y - pts[i].y;
      const len = Math.hypot(dx, dy) || 0.001;
      segs.push({ a: pts[i], b: pts[i + 1], len, ux: dx / len, uy: dy / len });
      total += len;
    }
    if (!total) return pts;

    // Sampling interval and overshoot are canvas-unit quantities, and this one
    // function draws marks two orders of magnitude apart: a 900-unit rule and a
    // 12-unit axis tick both come through here. At a fixed 26-unit step the tick
    // gets ONE sample, toPath returns an empty string, and the mark silently does
    // not exist — which is what made short sparkline bars and every chart tick
    // disappear. A fixed 16-unit overshoot on a 12-unit tick is likewise a
    // 44-unit scribble where a tick was drawn. Both now scale with the stroke:
    // long strokes are untouched, short ones are drawn as what they are.
    const step = Math.min(stepIn, Math.max(2.2, total / 5));
    const over = Math.min(overIn, total * 0.35);

    // overshoot start / undershoot or overshoot end — the pen arrives and leaves
    const s0 = segs[0], s1 = segs[segs.length - 1];
    const preT = over * (0.35 + r());
    const postT = over * (0.35 + r());
    let cursor = -preT;
    const endAt = total + postT;

    while (cursor <= endAt) {
      let t = Math.max(0, Math.min(total, cursor));
      let acc = 0, seg = segs[0], local = 0;
      for (const s of segs) { if (acc + s.len >= t) { seg = s; local = t - acc; break; } acc += s.len; }
      let px = seg.a.x + seg.ux * local, py = seg.a.y + seg.uy * local;
      if (cursor < 0) { px = s0.a.x + s0.ux * cursor; py = s0.a.y + s0.uy * cursor; }
      if (cursor > total) { const e = cursor - total; px = s1.b.x + s1.ux * e; py = s1.b.y + s1.uy * e; }
      const k = cursor / Math.max(1, total);
      const lo = drift[Math.floor(Math.abs(k) * 12) % 64] * amp * 1.15;
      const hi = Math.sin(k * 19 + dphase) * amp * 0.35 + (r() - 0.5) * amp * 0.55;
      const nx = -seg.uy, ny = seg.ux;
      // The boil: one extra low-frequency displacement, normal to the stroke and
      // scaled to the stroke's own amplitude. It rides ON TOP of the base wobble
      // and takes nothing from that generator, so the sampling positions are
      // identical between frames and only the ink moves.
      const bo = br ? (br() - 0.5) * 2 * BOIL_AMP : 0;
      out.push({ x: px + nx * (lo + hi + bo), y: py + ny * (lo + hi + bo) });
      cursor += step * (0.72 + r() * 0.6);
    }
    return out;
  }

  function rawStroke(d, o) {
    return `<path d="${d}" fill="none" stroke="${o.stroke}" stroke-width="${num(o.width)}" stroke-opacity="${num(o.opacity == null ? 1 : o.opacity)}" stroke-linecap="${o.cap || "round"}" stroke-linejoin="round"/>`;
  }

  // A drawn line: two pressure passes over the same wobble seed family.
  //
  // "Same seed family" is the whole contract, and it was broken: the broad pass
  // ran on `seed` and the fine pass on `seed * 31 + 11`, which is not a relative
  // of that seed — it is an unrelated drift table. So the two passes wandered
  // independently and the pale broad one drifted clear of the dark fine one,
  // reading as a misregistered second printing rather than as pressure. It was
  // worst on the heaviest marks, where the offset is widest: the encircle mark
  // looked like it had been stamped twice.
  //
  // Both passes now share the seed, so they trace the SAME wobble. The broad
  // pass differs only in amplitude and sampling — it blooms around the fine one
  // instead of leaving it, which is what ink actually does on paper.
  function stroke(pts, o) {
    o = o || {};
    const w = o.width == null ? 2.6 : o.width;
    const seed = o.seed == null ? 7 : o.seed;
    const col = o.stroke || "#000";
    const amp = o.amp == null ? 1.7 : o.amp;
    const a = wobble(pts, { seed, amp: amp * 1.12, step: (o.step || 26) * 1.15, over: o.over });
    const b = wobble(pts, { seed, amp, step: o.step, over: o.over });
    let s = rawStroke(toPath(a), { stroke: col, width: w * 1.25, opacity: (o.opacity == null ? 1 : o.opacity) * 0.36, cap: o.cap });
    s += rawStroke(toPath(b), { stroke: col, width: w * 0.85, opacity: (o.opacity == null ? 1 : o.opacity) * 0.95, cap: o.cap });
    return s;
  }

  const line = (x1, y1, x2, y2, o) => stroke([{ x: x1, y: y1 }, { x: x2, y: y2 }], o);

  function polyRect(x, y, w, h) {
    return [{ x, y }, { x: x + w, y }, { x: x + w, y: y + h }, { x, y: y + h }];
  }

  function outline(poly, o) {
    return stroke(poly.concat([poly[0]]), o);
  }

  // Colour laid inside an outline, missing it. Hatch strokes, rotated, scanline-clipped.
  function hatch(poly, o) {
    o = o || {};
    const seed = o.seed == null ? 3 : o.seed;
    const r = rng(seed);
    // Hatch carries most of the tone in this kit, so it has to boil as well —
    // with only the line work moving, every shaded area sat frozen inside a
    // living outline. The strokes are generated here and drawn through stroke(),
    // which wobbles them, so the boil reaches them by that route; this generator
    // only needs to leave the LAYOUT of the hatch alone, which it does by never
    // being seeded from BOIL.
    const ang = (o.angle == null ? -74 : o.angle) * RAD;
    const gap = o.gap == null ? 5.5 : o.gap;
    const over = o.over == null ? 7 : o.over;
    const col = o.color || "#000";
    const width = o.width == null ? 3.4 : o.width;
    const op = o.opacity == null ? 0.6 : o.opacity;
    const rot = (p, s) => ({ x: p.x * Math.cos(s) - p.y * Math.sin(s), y: p.x * Math.sin(s) + p.y * Math.cos(s) });
    const P = poly.map((p) => rot(p, -ang));
    const ys = P.map((p) => p.y);
    const y0 = Math.min.apply(null, ys), y1 = Math.max.apply(null, ys);
    let out = "";
    let i = 0;
    for (let y = y0 - gap * 0.4; y < y1 + gap * 0.4; y += gap * (0.8 + r() * 0.45)) {
      const xs = [];
      for (let k = 0; k < P.length; k++) {
        const A = P[k], B = P[(k + 1) % P.length];
        if ((A.y <= y && B.y > y) || (B.y <= y && A.y > y)) xs.push(A.x + ((y - A.y) / (B.y - A.y)) * (B.x - A.x));
      }
      xs.sort((m, n) => m - n);
      for (let k = 0; k + 1 < xs.length; k += 2) {
        // Overshoot is what makes a hatch read as laid by hand rather than
        // computed — but it is an absolute distance, so 7 units of it across a
        // 20-unit shape (a pupil, a mug rim, a point marker) is not a fill that
        // misses its outline, it is a hairy blob. Cap it to the span it fills.
        const span = xs[k + 1] - xs[k];
        const ovk = Math.min(over, span * 0.3);
        const s = xs[k] - ovk * r() * (r() < 0.55 ? 1 : 0.15);
        const e = xs[k + 1] + ovk * r() * (r() < 0.55 ? 1 : 0.15);
        if (e - s < 1.5) continue;
        const p1 = rot({ x: s, y: y + (r() - 0.5) * 1.8 }, ang);
        const p2 = rot({ x: e, y: y + (r() - 0.5) * 1.8 }, ang);
        // density: the hand pauses — some passes are doubled, some are ghosts
        const dens = r();
        out += stroke([p1, p2], {
          stroke: col, width: width * (0.7 + r() * 0.6), amp: 1.5,
          opacity: op * (dens < 0.14 ? 0.35 : 0.7 + r() * 0.5), seed: seed * 131 + i * 17,
          over: Math.min(2, span * 0.12),
        });
        if (dens > 0.9) out += stroke([{ x: p1.x, y: p1.y + 1.4 }, { x: p2.x, y: p2.y - 1.1 }], { stroke: col, width: width * 0.6, amp: 1.2, opacity: op * 0.55, seed: seed * 17 + i, over: 2 });
        i++;
      }
    }
    return out;
  }

  const fillRect = (x, y, w, h, o) => hatch(polyRect(x, y, w, h), o);

  // Ground tooth. Drawn, not filtered — CSS/SVG filters do not survive rasterisation.
  function speckle(w, h, o) {
    o = o || {};
    const r = rng(o.seed || 5);
    const count = o.count == null ? 2600 : o.count;
    const tiers = [
      { op: (o.opacity || 0.1) * 0.5, n: count * 0.55, len: 1.1, wd: 1.1 },
      { op: (o.opacity || 0.1), n: count * 0.33, len: 1.7, wd: 1.4 },
      { op: (o.opacity || 0.1) * 1.9, n: count * 0.12, len: 2.4, wd: 1.8 },
    ];
    let out = "";
    for (const t of tiers) {
      let d = "";
      for (let i = 0; i < t.n; i++) {
        const x = r() * w, y = r() * h, a = r() * Math.PI;
        d += `M${num(x)} ${num(y)}l${num(Math.cos(a) * t.len)} ${num(Math.sin(a) * t.len)}`;
      }
      out += `<path d="${d}" fill="none" stroke="${o.color || "#5a4a30"}" stroke-width="${t.wd}" stroke-opacity="${num(t.op)}" stroke-linecap="round"/>`;
    }
    // a few pulp fibres
    for (let i = 0; i < 26; i++) {
      const x = r() * w, y = r() * h, l = 14 + r() * 46, a = r() * Math.PI;
      out += stroke([{ x, y }, { x: x + Math.cos(a) * l, y: y + Math.sin(a) * l }], { stroke: o.color || "#5a4a30", width: 1.3, opacity: (o.opacity || 0.1) * 0.9, amp: 2.2, seed: 300 + i });
    }
    return out;
  }

  // ---------- plate container ----------
  // Collects art in layers (colour under line) and slots. toSVG() and manifest()
  // come from the same object, so geometry can never drift.
  function Plate(cfg) {
    const P = {
      key: cfg.key,
      w: cfg.w, h: cfg.h, seed: cfg.seed || 1,
      pal: cfg.pal,
      colour: [], ink: [], top: [],
      slots: {}, decor: [],
      meta: cfg.meta || {},
      _r: (function () { const b = BOIL; BOIL = 0; const g = rng(cfg.seed || 1); BOIL = b; return g; })(),
    };
    P.r = () => P._r();
    P.colourAdd = (s) => { P.colour.push(s); return P; };
    P.inkAdd = (s) => { P.ink.push(s); return P; };
    P.topAdd = (s) => { P.top.push(s); return P; };
    P.slot = (key, x, y, w, h, extra) => {
      // the box always wins: extra metadata can never clobber geometry
      P.slots[key] = Object.assign({}, extra || {}, {
        x: Math.round(x), y: Math.round(y), w: Math.round(w), h: Math.round(h),
      });
      return P;
    };
    // record the bounding box of a drawn decorative mark, so the audit can test
    // art against text slots as well as slots against each other
    P.artBox = (label, x, y, w, h) => {
      P.decor.push({ label: label, x: Math.round(x), y: Math.round(y), w: Math.round(w), h: Math.round(h) });
      return P;
    };
    P.toSVG = function (opts) {
      opts = opts || {};
      const gid = "g" + Math.abs(P.seed % 9999);
      const grain = P.pal.grain;
      const body = [
        `<rect x="0" y="0" width="${P.w}" height="${P.h}" fill="${P.pal.ground}"/>`,
        grain ? (function () { const b = BOIL; BOIL = 0; const s = speckle(P.w, P.h, { seed: P.seed * 3 + 7, color: grain.tint, opacity: grain.opacity, count: Math.round((P.w * P.h) / 900) }); BOIL = b; return s; })() : "",
        cfg.surface || "",
        P.colour.join(""),
        P.ink.join(""),
        P.top.join(""),
      ].join("");
      return `<svg xmlns="http://www.w3.org/2000/svg" width="${P.w}" height="${P.h}" viewBox="0 0 ${P.w} ${P.h}">${body}</svg>`;
    };
    P.manifest = function (o) {
      o = o || {};
      // ONE SCALE, WHOLE LIBRARY, AND NOT A PARAMETER. This used to read
      // `o.exportScale || 2`, which is how a per-family scale gets in: any caller
      // could hand a plate its own scale, the manifest would faithfully record
      // it, and a shot mixing a room with a card would need a resample step in
      // the middle of a composite. The scale now comes from engine/audit.js and
      // an exportScale passed in here is ignored on purpose.
      const scale = (g.AUDIT && g.AUDIT.EXPORT_SCALE) || 2;
      const name = P.key.split("/").pop();
      return Object.assign({
        canvas: [P.w, P.h],
        exportScale: scale,
        delivered: [P.w * scale, P.h * scale],
        frameCount: 1, fps: 0, playback: "static",
        // FRAMES ARE OBJECTS, NOT FILENAMES. A bare filename cannot say what a
        // frame IS — its tag, its boil offset, whether its mouth is open — so
        // the player had to parse meaning out of a string suffix. This emitter
        // was the one place still producing the old array-of-strings shape, so a
        // re-emit of any family would have quietly reverted it.
        frames: [{ tag: "", svg: name + ".svg", png: name + ".png" }],
        files: { png: name + ".png", svg: name + ".svg" },
        slots: P.slots,
        decorBoxes: P.decor.length ? P.decor : undefined,
      }, P.meta);
    };
    return P;
  }

  g.HAND = { rng, wobble, stroke, line, hatch, fillRect, polyRect, outline, toPath, Plate, num, speckle, setBoil };
})(typeof window !== "undefined" ? window : globalThis);
