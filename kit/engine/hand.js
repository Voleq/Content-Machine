/* Dennis v2 — hand engine.
   Deterministic procedural drawing. Every plate is drawn by this file, and the
   manifest is emitted by the same call that draws it (see plates.js). Never
   measure a plate afterwards.

   TWO HANDS LIVE IN HERE NOW, AND WHICH ONE DRAWS IS A PER-FAMILY CHOICE.

   `hand-1` is the shipped hand, unchanged, and it draws twelve of the fourteen
   families. Its principles:
   - no perfect line: every stroke is resampled, perpendicular-noised, and overshoots its ends
   - two passes per stroke (pressure): a light wide pass + a darker narrow pass, offset
   - colour is laid as hatch strokes INSIDE an outline and deliberately misses it
   - line work is emitted after colour, always

   `hand-2` draws host/ and room/ only. Those three principles are exactly what
   was wrong with those 63 plates: overshoot plus perpendicular noise gives every
   contour three or four searching lines, a fixed two-pass gives the texture of
   pressure with none of its meaning, and hatch-as-fill covers hair, face and
   jacket at one angle and one density so nothing in the picture turns. hand-2
   replaces them with:
   - ONE committed edge per contour, or none (§3.2)
   - a declared light direction the whole family shades against (§3.1)
   - weight that follows form: heavy in occlusion and on undersides, light on lit
     edges and on the outer silhouette (§3.3)
   - hatch ONLY as shading — angled across the form, densifying into the core
     shadow, fading out rather than ending on a boundary; broad areas washed
     rather than hatched (§3.4)
   - edge bloom: pigment pooling as a darker rim just inside each wash (§3.5)

   The profile is resolved from the plate key's family in Plate(), so it is one
   table here and no change at any call site. The other twelve families take the
   identical code path they always did and re-ingest byte-identical.

   NOT IN THIS PACK: §3.6, the detail budget on the face. Crisp eyes, one
   confident line on the glasses and a simplified jacket are author changes in
   engine/plates.js (hostFace/hostHead), not engine changes, and they are the
   next pack. Everything here is the hand.
*/
(function (g) {
  const RAD = Math.PI / 180;

  // ---------- render profile -------------------------------------------------
  const P1 = "hand-1", P2 = "hand-2";
  // The opt-in list, and the whole of §4. Twelve families are absent on purpose.
  const PROFILE_FAMILIES = { host: P2, room: P2 };
  let PROFILE = P1;
  const familyOf = (key) => String(key || "").split("/")[0];
  function profileFor(key) { return PROFILE_FAMILIES[familyOf(key)] || P1; }
  function setProfile(n) { PROFILE = n === P2 ? P2 : P1; }
  const two = () => PROFILE === P2;

  // §3.1 — ONE LIGHT, WHOLE KIT. Upper-left, and it does not vary by pose, by
  // room or by plate: a character lit from a different side in consecutive shots
  // is two characters. This vector is the direction TOWARD the light, so a
  // surface normal dotted against it is +1 fully lit and -1 fully turned away,
  // and every shading decision in hand-2 is that one number.
  //
  // Nothing else here reads correctly without it. It is also the only new input
  // to the drawing: no colour is added anywhere, every shade and every rim is
  // derived from the palette token the author already passed in.
  const LIGHT = { x: -0.6, y: -0.8 };

  // Value, not hue. A wash's bloom rim and a shadow's density are the same
  // colour multiplied down — so §6 holds (no re-hueing, no new tokens) while §3
  // gets the tonal separation it needs. Magnitudes are listed in
  // audit/hand-profile.json.
  function darken(hex, k) {
    const h = String(hex).trim();
    if (h.charAt(0) !== "#" || (h.length !== 7 && h.length !== 4)) return h;
    const f = h.length === 4
      ? [parseInt(h[1] + h[1], 16), parseInt(h[2] + h[2], 16), parseInt(h[3] + h[3], 16)]
      : [parseInt(h.substr(1, 2), 16), parseInt(h.substr(3, 2), 16), parseInt(h.substr(5, 2), 16)];
    const c = f.map((v) => Math.max(0, Math.min(255, Math.round(v * k))));
    return "#" + c.map((v) => ("0" + v.toString(16)).slice(-2)).join("");
  }

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
  //
  // AMPLITUDE IS AN ABSOLUTE, NOT A PERCENTAGE: ~2 canvas units of movement per
  // point, on every asset, whatever its size. It is declared PER ASSET in
  // build.js as the amount that should survive to the frame divided by the solve
  // the asset will get, because solve scale multiplies every canvas-unit quantity
  // a plate declares.
  //
  // AND hand-2 TAKES LESS OF IT. The 2-unit figure was tuned against four
  // tentative contours, where movement hides inside the scribble. Against a
  // single committed edge the same amplitude reads as the line swimming rather
  // than breathing, exactly as §5 predicted. hand-2 draws the boil at 0.55 of the
  // authored amplitude — ~1.1 units — which is the one number in this pack that
  // can only be judged in motion, not from a still.
  let BOIL = 0;
  let BOIL_AMP = 2.0;
  const BOIL_AMP_DEFAULT = 2.0;
  const BOIL_P2_FACTOR = 0.55;

  // §1.5 — THE GATE, AND WHICH WAY ROUND IT POINTS.
  //
  // Forty-seven plates are frozen because wobbling figures are unreadable, and
  // that is right. But the sheet they are printed on need not be: the paper edge,
  // the corner wear, the rule lines and the hatch can breathe while everything a
  // viewer reads a VALUE off stays pinned.
  //
  // The first cut of this made breathing opt-IN — gate up, and a mark moves only
  // inside breathe(). It was the safe-looking choice and it was the wrong one:
  // the pre-flight found forty-four of the forty-seven still completely frozen,
  // because a data plate's furniture is drawn in twenty different authors and
  // each would have needed hand-wrapping. Opt-in defaults to FROZEN, which is
  // the bug it was supposed to prevent, arriving silently.
  //
  // So it is opt-OUT, and that turns out to be the honest shape for a reason
  // beyond convenience: ON A DATA PLATE, ALMOST NOTHING DRAWN IS DATA. Every
  // figure, every series, every band is a SLOT the compositor fills — the plate
  // itself draws rules, panels, hatch and frames. The marks that are genuinely
  // measurement references are few enough to name:
  //
  //   - chart axes and their tick marks
  //   - the waterfall's baseline
  //   - the implied plate's axis
  //
  // Those are wrapped in pin(). Everything else on a gated plate breathes, which
  // is what §1.5 asks for. The list is short, it is enumerable, and the pre-flight
  // asserts every pinned mark is byte-identical across the three frames — so a
  // missing pin is caught by a test rather than by a viewer watching an axis
  // crawl.
  let BOIL_GATE = 0;
  let BREATHING = 0;
  let PINNED = 0;
  // The plate's own area, set by Plate(). hatch() needs it to tell a FORM from a
  // PLANE: §3.4 says broad areas are washed rather than hatched, and "broad" can
  // only mean broad relative to the frame. A 400x300 prop on a 1920x1080 room is
  // a form and takes the modelling; the wall behind it is a plane and takes the
  // wash alone. Without this the first room render came out with a diagonal
  // hatch across the wall and the floor — wallpaper, not shading.
  let PLATE_AREA = 0;
  function setBoil(n, amp, gate) {
    BOIL = n | 0;
    BOIL_AMP = amp == null ? BOIL_AMP_DEFAULT : amp;
    BOIL_GATE = gate ? 1 : 0;
    // A gated plate starts BREATHING. See the note above: opt-out, not opt-in.
    BREATHING = BOIL_GATE;
    PINNED = 0;
  }
  // Kept so call sites that mean "this is furniture" can say so, and so the
  // intent survives if the gate is ever inverted again. On a gated plate it is a
  // no-op; on an ungated one everything boils anyway.
  function breathe(fn) {
    BREATHING++;
    try { return fn(); } finally { BREATHING = Math.max(0, BREATHING - 1); }
  }
  // PIN: this mark is something a viewer reads a value off. It emits the identical
  // path at every boil index — not "barely moving", the same path.
  //
  // It pins on EVERY plate, not only gated ones. A chart axis in a boiling
  // family would be the same defect, and the rule is about what the mark is for
  // rather than which family it landed in.
  function pin(fn) {
    PINNED++;
    try { return fn(); } finally { PINNED = Math.max(0, PINNED - 1); }
  }
  const boiling = () => !!(BOIL && !PINNED && (!BOIL_GATE || BREATHING));

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

  const centroidOf = (pts) => {
    let x = 0, y = 0;
    for (const p of pts) { x += p.x; y += p.y; }
    return { x: x / (pts.length || 1), y: y / (pts.length || 1) };
  };
  const areaOf = (poly) => {
    let a = 0;
    for (let i = 0; i < poly.length; i++) {
      const p = poly[i], q = poly[(i + 1) % poly.length];
      a += p.x * q.y - q.x * p.y;
    }
    return Math.abs(a) / 2;
  };
  // Inward offset, by scaling toward the centroid. Crude against a concave
  // polygon and entirely adequate for a bloom rim, which only has to sit inside
  // the wash it belongs to.
  function insetPoly(poly, d) {
    const c = centroidOf(poly);
    let rad = 0;
    for (const p of poly) rad = Math.max(rad, Math.hypot(p.x - c.x, p.y - c.y));
    const k = Math.max(0.5, 1 - d / (rad || 1));
    return poly.map((p) => ({ x: c.x + (p.x - c.x) * k, y: c.y + (p.y - c.y) * k }));
  }

  // Resample a polyline and push each interior point off-axis. Low-frequency drift
  // (the wrist) + high-frequency tremor (the hand).
  //
  // §3.2 lives here. hand-2 keeps the wrist and nearly all of the tremor goes:
  // drift at 0.42 of the authored amplitude, tremor at 0.34 of that again, and
  // the overshoot at both ends set to zero. The r() calls are all still made in
  // the same order, so the two profiles sample the same drift table and a
  // before/after is point-for-point comparable rather than a different drawing.
  //
  // What disappears with the overshoot: the doubled lapel, the second shoulder
  // floating outside the silhouette, the stray horizontals across the torso and
  // the tripled chin. None of those were drawn — they are ends of lines that
  // carried on past their corners.
  function wobble(pts, o) {
    const t2 = two();
    const r = rng(o.seed || 1);
    const br = boiling() ? rng((o.seed || 1) * 31 + BOIL * 9173) : null;
    const amp = (o.amp == null ? 1.7 : o.amp) * (t2 ? 0.42 : 1);
    const trem = t2 ? 0.34 : 1;
    const stepIn = (o.step || 26) * (t2 ? 1.25 : 1);
    const overIn = t2 ? 0 : (o.over == null ? 5 : o.over);
    const bAmp = BOIL_AMP * (t2 ? BOIL_P2_FACTOR : 1);
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
    // not exist. Both scale with the stroke.
    const step = Math.min(stepIn, Math.max(2.2, total / 5));
    const over = Math.min(overIn, total * 0.35);

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
      const hi = (Math.sin(k * 19 + dphase) * amp * 0.35 + (r() - 0.5) * amp * 0.55) * trem;
      const nx = -seg.uy, ny = seg.ux;
      const bo = br ? (br() - 0.5) * 2 * bAmp : 0;
      out.push({ x: px + nx * (lo + hi + bo), y: py + ny * (lo + hi + bo) });
      cursor += step * (0.72 + r() * 0.6);
    }
    return out;
  }

  // A MARK WITH NO GEOMETRY IS NOT A MARK.
  //
  // Pre-flight check D found one of these: `<path d="" stroke="#7d5f44" .../>` on
  // close-up frame three, present in one drawing and absent in the other. It
  // renders nothing, so no screenshot would ever have shown it — but it makes two
  // otherwise identical plates differ, which is exactly the kind of phantom that
  // makes a byte-identity baseline untrustworthy and sends someone hunting for a
  // drawing error that does not exist.
  //
  // The cause is upstream: a stroke whose point list collapses at some boil and
  // bob combination. Suppressing the empty element here does not repair that
  // stroke, and it is recorded as open in CHANGES rather than treated as fixed.
  // What it does do is stop a non-mark from counting as a difference.
  function rawStroke(d, o) {
    if (!d) return "";
    return `<path d="${d}" fill="none" stroke="${o.stroke}" stroke-width="${num(o.width)}" stroke-opacity="${num(o.opacity == null ? 1 : o.opacity)}" stroke-linecap="${o.cap || "round"}" stroke-linejoin="round"/>`;
  }
  function rawFill(d, o) {
    if (!d) return "";
    return `<path d="${d}Z" fill="${o.fill}" fill-opacity="${num(o.opacity == null ? 1 : o.opacity)}" stroke="none"/>`;
  }

  // hand-1: a drawn line as two pressure passes over the same wobble seed family.
  // Both passes share the seed, so they trace the SAME wobble and the broad pass
  // blooms around the fine one instead of leaving it.
  function stroke1(pts, o) {
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

  // §3.3 — hand-2: ONE line, whose weight is information.
  //
  // A constant two-pass applies the same pressure to every edge on every plate,
  // which is why nothing in the reference renders reads as turning away. Here the
  // single contour is emitted in a handful of consecutive spans and each span
  // takes its own width and opacity from three things:
  //
  //   light      — the span's outward normal against LIGHT: a lit edge thins and
  //                pales, an edge turned away thickens and darkens. This is the
  //                whole of the modelling, and it is free: the geometry already
  //                knows which way it faces.
  //   occlusion  — o.heavy (a multiplier the author sets where two forms overlap
  //                or a form undercuts: a collar over a shoulder, a jaw over a
  //                neck). Default 1, so nothing changes until an author says so.
  //   silhouette — o.silhouette thins the whole contour. The outer edge of a form
  //                against empty ground is the LEAST important line in the
  //                picture; drawn at full weight it reads as a cut-out.
  //
  // Spans are emitted with round caps and share an endpoint, so the line reads as
  // one gesture that swells and thins, not as segments.
  function stroke2(pts, o) {
    const w = o.width == null ? 2.6 : o.width;
    const seed = o.seed == null ? 7 : o.seed;
    const col = o.stroke || "#000";
    const op = o.opacity == null ? 1 : o.opacity;
    const heavy = o.heavy == null ? 1 : o.heavy;
    const sil = o.silhouette ? 0.82 : 1;
    const a = wobble(pts, { seed, amp: o.amp, step: o.step, over: o.over });
    if (a.length < 2) return "";
    const n = a.length;
    const cen = centroidOf(a);
    const spans = Math.min(10, Math.max(2, Math.round((n - 1) / 2)));
    let out = "";
    for (let c = 0; c < spans; c++) {
      const i0 = Math.floor((c * (n - 1)) / spans);
      const i1 = Math.floor(((c + 1) * (n - 1)) / spans);
      const sub = a.slice(i0, i1 + 1);
      if (sub.length < 2) continue;
      const m0 = sub[0], m1 = sub[sub.length - 1];
      const dx = m1.x - m0.x, dy = m1.y - m0.y, L = Math.hypot(dx, dy) || 1;
      let nx = -dy / L, ny = dx / L;
      // outward: away from the whole stroke's centre of mass. For a closed
      // outline that is the true outward normal; for an open stroke it is the
      // side the form is not on, which is the same decision a hand makes.
      const ox = (m0.x + m1.x) / 2 - cen.x, oy = (m0.y + m1.y) / 2 - cen.y;
      if (nx * ox + ny * oy < 0) { nx = -nx; ny = -ny; }
      const lit = nx * LIGHT.x + ny * LIGHT.y;              // +1 lit, -1 turned away
      const ends = (c === 0 || c === spans - 1) ? 0.78 : 1; // the pen arrives and leaves
      const wf = (1 - 0.36 * lit) * heavy * sil * ends;
      const of = Math.max(0.18, Math.min(1, (1 - 0.2 * lit) * (o.silhouette ? 0.9 : 1)));
      out += rawStroke(toPath(sub), { stroke: col, width: Math.max(0.35, w * wf), opacity: op * of, cap: o.cap });
    }
    return out;
  }

  function stroke(pts, o) {
    o = o || {};
    return two() ? stroke2(pts, o) : stroke1(pts, o);
  }

  const line = (x1, y1, x2, y2, o) => stroke([{ x: x1, y: y1 }, { x: x2, y: y2 }], o);

  function polyRect(x, y, w, h) {
    return [{ x, y }, { x: x + w, y }, { x: x + w, y: y + h }, { x, y: y + h }];
  }

  function outline(poly, o) {
    return stroke(poly.concat([poly[0]]), o);
  }

  // hand-1: colour laid inside an outline, missing it. Hatch strokes, rotated,
  // scanline-clipped. Unchanged — twelve families draw through this.
  function hatch1(poly, o) {
    const seed = o.seed == null ? 3 : o.seed;
    const r = rng(seed);
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
        const span = xs[k + 1] - xs[k];
        const ovk = Math.min(over, span * 0.3);
        const s = xs[k] - ovk * r() * (r() < 0.55 ? 1 : 0.15);
        const e = xs[k + 1] + ovk * r() * (r() < 0.55 ? 1 : 0.15);
        if (e - s < 1.5) continue;
        const p1 = rot({ x: s, y: y + (r() - 0.5) * 1.8 }, ang);
        const p2 = rot({ x: e, y: y + (r() - 0.5) * 1.8 }, ang);
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

  // §3.4 + §3.5 — hand-2: the region is WASHED, and hatch is shading only.
  //
  // The old call laid every colour as hatch at a constant angle and density, so
  // hair, face, neck and jacket were covered identically, nothing followed a
  // form, and where a hatched region stopped it stopped — the hard vertical seam
  // down the middle of the face on close-up-glance-left is a hatch region
  // terminating on a straight clip boundary. Three changes, same call signature:
  //
  //   the wash     a single fill of the author's colour, wobbled at its edge. A
  //                broad area is paint, not 400 parallel strokes.
  //   the bloom    §3.5: a darker rim just inside the wash, where pigment pools.
  //                Value only — the token multiplied down, no new hue. It is the
  //                most recognisable signature of real paint and the cheapest
  //                thing in this pack.
  //   the shading  hatch runs ACROSS the form (perpendicular to LIGHT, so it
  //                rakes the way the light does), and its density RAMPS from
  //                nothing on the lit side to full in the core shadow. Every
  //                scanline also shortens as it weakens, so a hatch field frays
  //                out instead of ending on a line. A region can no longer show
  //                the seam, because the seam is where the density is zero.
  //
  // — Small regions are wash-and-rim only.
  // — `rim: false` suppresses the bloom. A CONSTRUCTION POLYGON IS NOT A
  //   MATERIAL EDGE: the neck is authored as a quad whose bottom edge is under
  //   the collar and whose sides are under the jaw, so rimming it draws a box on
  //   his chest — the first hostHead proof did exactly that. Where the polygon's
  //   boundary is not the material's boundary, the author says so.
  //
  // AND A SHADOW IS NOT A MATERIAL. The authors call this function for both: a
  // jacket is cloth at 0.88, a jaw shadow is the ink token at 0.2 over skin that
  // is already there. Washing the second one the way you wash the first puts a
  // flat slab with a rim around it under his chin — a drawn beard, not a shadow,
  // and the first proof render did exactly that. So opacity is the discriminator,
  // because it is already what the authors use to mean this: at or above 0.4 the
  // region is a material (wash, rim, then shading), below it the region IS
  // shading (the ramp alone, no fill and no rim, so it fades on every side and
  // never gets an edge of its own). `material: true|false` overrides per call.
  function hatch2(poly, o) {
    const seed = o.seed == null ? 3 : o.seed;
    const r = rng(seed);
    const col = o.color || "#000";
    const op = o.opacity == null ? 0.6 : o.opacity;
    const gap = (o.gap == null ? 5.5 : o.gap) * 1.35;
    const width = o.width == null ? 3.4 : o.width;
    const area = areaOf(poly);
    if (area < 4) return "";
    const material = o.material == null ? op >= 0.4 : !!o.material;
    const small = area < 2600;
    // a plane: too big relative to the frame to be a form that turns
    const plane = o.plane == null ? (PLATE_AREA > 0 && area > PLATE_AREA * 0.055) : !!o.plane;
    const rimW = Math.max(1.6, Math.min(7, Math.sqrt(area) * 0.035));
    let out = "";

    if (material || small) {
      // the wash. THE AUTHORED OPACITY WAS COVERAGE, NOT TRANSLUCENCY: hatch at
      // 0.62 lays overlapping two-pass strokes until the region reads as solid
      // colour, so a fill at 0.62 is not the same tone — on a cutout plate over a
      // dark ground it is half a face. A material wash goes to x1.5, i.e. opaque
      // for anything the author meant as covered, and a shadow wash (small
      // regions only) stays near its authored value because there the number
      // really is translucency.
      const edge = wobble(poly.concat([poly[0]]), { seed: seed * 7 + 3, amp: 1.1, step: 30, over: 0 });
      out += rawFill(toPath(edge), { fill: col, opacity: Math.min(1, op * (material ? 1.5 : 0.78)) });
    }
    if (material && o.rim !== false && !plane) {
      // the bloom rim
      const rim = insetPoly(poly, rimW * 1.4);
      out += stroke2(rim.concat([rim[0]]), {
        stroke: darken(col, 0.84), width: rimW, opacity: Math.min(0.85, op * 0.7),
        amp: 1.2, seed: seed * 13 + 5, silhouette: true,
      });
    }

    if (o.shade === false || small || plane) return out;

    // the shading: across the form, densifying into the core shadow
    const ang = o.shadeAngle == null ? Math.atan2(LIGHT.y, LIGHT.x) + Math.PI / 2 : o.shadeAngle * RAD;
    const rot = (p, s) => ({ x: p.x * Math.cos(s) - p.y * Math.sin(s), y: p.x * Math.sin(s) + p.y * Math.cos(s) });
    const Q = insetPoly(poly, rimW * 0.8).map((p) => rot(p, -ang));
    const ys = Q.map((p) => p.y);
    const y0 = Math.min.apply(null, ys), y1 = Math.max.apply(null, ys);
    const span0 = y1 - y0 || 1;
    // which end of the rotated axis the light is on
    const rl = rot(LIGHT, -ang);
    const lightAtY0 = rl.y < 0;
    const shadeCol = material ? darken(col, 0.62) : col;
    let i = 0;
    for (let y = y0; y < y1; y += gap * (0.85 + r() * 0.4)) {
      let t = (y - y0) / span0;
      if (lightAtY0) t = t; else t = 1 - t;
      // 0 for the lit half, easing up to 1 at the far edge: the ramp IS the form
      const d = Math.max(0, (t - (material ? 0.34 : 0.12)) / (material ? 0.66 : 0.88));
      const dens = material ? d * d : 0.25 + d * d * 0.75;
      if (dens < 0.05) { i++; continue; }
      const xs = [];
      for (let k = 0; k < Q.length; k++) {
        const A = Q[k], B = Q[(k + 1) % Q.length];
        if ((A.y <= y && B.y > y) || (B.y <= y && A.y > y)) xs.push(A.x + ((y - A.y) / (B.y - A.y)) * (B.x - A.x));
      }
      xs.sort((m, n) => m - n);
      for (let k = 0; k + 1 < xs.length; k += 2) {
        // a weak scanline is also a SHORT one, pulled in from both ends, so the
        // field frays instead of stopping on the clip boundary
        const mid = (xs[k] + xs[k + 1]) / 2, half = (xs[k + 1] - xs[k]) / 2;
        const keep = half * Math.min(1, 0.35 + dens * 0.8);
        const s = mid - keep * (0.8 + r() * 0.2), e = mid + keep * (0.8 + r() * 0.2);
        if (e - s < 2) continue;
        const p1 = rot({ x: s, y: y + (r() - 0.5) * 1.2 }, ang);
        const p2 = rot({ x: e, y: y + (r() - 0.5) * 1.2 }, ang);
        out += rawStroke(toPath(wobble([p1, p2], { seed: seed * 131 + i * 17, amp: 1.3, step: 34, over: 0 })), {
          stroke: shadeCol, width: width * (0.5 + dens * 0.5), opacity: Math.min(0.8, op * (material ? 0.85 : 1.3) * dens),
        });
        i++;
      }
    }
    return out;
  }

  function hatch(poly, o) {
    o = o || {};
    return two() ? hatch2(poly, o) : hatch1(poly, o);
  }

  const fillRect = (x, y, w, h, o) => hatch(polyRect(x, y, w, h), o);

  // Ground tooth. Drawn, not filtered — CSS/SVG filters do not survive
  // rasterisation. Identical in both profiles: the sheet is not being redrawn.
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
    // §4 — THE PROFILE IS BOUND HERE, from the key's family, before a single mark
    // is made. Every author starts by constructing its Plate, so this is the one
    // place that can set it without touching 143 call sites; cfg.profile lets a
    // proof harness force either hand on any key.
    setProfile(cfg.profile || profileFor(cfg.key));
    PLATE_AREA = (cfg.w || 0) * (cfg.h || 0);
    const prof = PROFILE;
    const P = {
      key: cfg.key,
      w: cfg.w, h: cfg.h, seed: cfg.seed || 1,
      pal: cfg.pal,
      hand: prof,
      colour: [], ink: [], top: [],
      slots: {}, decor: [],
      meta: cfg.meta || {},
      _r: (function () { const b = BOIL; BOIL = 0; const g = rng(cfg.seed || 1); BOIL = b; return g; })(),
    };
    P.r = () => P._r();
    P.colourAdd = (s) => { P.colour.push(s); return P; };
    /* PINNED IS RECORDED AT THE MOMENT OF THE DRAW (rebuild-17). H.pin() already
     * marks measurement references — axes, baselines, the prior close — as
     * "must not move". Recording it per ink entry is what lets toSVG give the
     * frame's rule lines their authored offset (tokens.motion.dataRuleOffsets)
     * while everything a viewer reads a value off stays still. This and the
     * ruleOffset branch in toSVG are the only edits to this file; with offset 0
     * the output is byte-identical to before, so the base file IS frame one. */
    P.inkPin = [];
    P.inkAdd = (s) => { P.ink.push(s); P.inkPin.push(PINNED > 0); return P; };
    P.topAdd = (s) => { P.top.push(s); return P; };
    P.slot = (key, x, y, w, h, extra) => {
      // the box always wins: extra metadata can never clobber geometry
      P.slots[key] = Object.assign({}, extra || {}, {
        x: Math.round(x), y: Math.round(y), w: Math.round(w), h: Math.round(h),
      });
      return P;
    };
    P.artBox = (label, x, y, w, h) => {
      P.decor.push({ label: label, x: Math.round(x), y: Math.round(y), w: Math.round(w), h: Math.round(h) });
      return P;
    };
    // §1.2 — CLIP THE PLATE TO A BOX, so an overlay can be a REGION of a drawing
    // rather than a second drawing of a region.
    //
    // The blink is the idle head re-drawn with the lids down and clipped to the
    // eye box. Every mark inside that box which is not the eye — the skin wash,
    // its grain, the glasses, the brow — comes off the same seed at the same boil
    // index as the frame underneath, so it is not similar to what is beneath it,
    // it is the SAME PATH. That is what makes the clip edge invisible: there is
    // no seam to hide, because the two drawings agree everywhere except the lids.
    //
    // It also means registration is identity. The overlay keeps the full canvas
    // and the full viewBox, so the compositor stacks it at 0,0 with no offset
    // arithmetic — the class of bug that produced the desk-height and neck-span
    // errors in the last two packs cannot occur here.
    P.clipBox = null;
    // §1.4 — THE SETTLE. A frame that lands slightly past its position and comes
    // back, authored as frames rather than as an easing curve.
    //
    // Applied to the whole plate after the author has drawn it, because a settle
    // is a property of the SHOT — the card arriving — not of the drawing. Every
    // author would otherwise need to thread an offset through its geometry, and
    // the first one to forget would ship a card that arrives without settling.
    //
    // It keeps the hand because each settle frame also carries its own boil index:
    // the linework re-wobbles as it lands, which an easing transform on one static
    // frame cannot do.
    P.settleOffset = null;
    P.settleTo = function (dx, dy) {
      P.settleOffset = { dx: +dx.toFixed(2), dy: +dy.toFixed(2) };
      return P;
    };
    P.clipTo = function (x, y, w, h) {
      P.clipBox = { x: Math.round(x), y: Math.round(y), w: Math.round(w), h: Math.round(h) };
      return P;
    };
    P.toSVG = function (opts) {
      opts = opts || {};
      const prev = PROFILE;
      setProfile(prof);
      const grain = P.pal.grain;
      const body = [
        `<rect x="0" y="0" width="${P.w}" height="${P.h}" fill="${P.pal.ground}"/>`,
        grain ? (function () { const b = BOIL; BOIL = 0; const s = speckle(P.w, P.h, { seed: P.seed * 3 + 7, color: grain.tint, opacity: grain.opacity, count: Math.round((P.w * P.h) / 900) }); BOIL = b; return s; })() : "",
        cfg.surface || "",
        P.colour.join(""),
        (function (dy) {
          if (!dy) return P.ink.join("");
          let out = "", run = "";
          P.ink.forEach((s, i) => {
            if (P.inkPin[i]) { if (run) { out += '<g transform="translate(0 ' + dy + ')">' + run + "</g>"; run = ""; } out += s; }
            else run += s;
          });
          if (run) out += '<g transform="translate(0 ' + dy + ')">' + run + "</g>";
          return out;
        })(opts.ruleOffset || 0),
        P.top.join(""),
      ].join("");
      setProfile(prev);
      const wrap = (inner) => {
        let s = inner;
        if (P.clipBox) {
          const c = P.clipBox, id = "clip-" + String(P.key).replace(/[^a-zA-Z0-9]/g, "-");
          s = `<defs><clipPath id="${id}"><rect x="${c.x}" y="${c.y}" width="${c.w}" height="${c.h}"/></clipPath></defs><g clip-path="url(#${id})">${s}</g>`;
        }
        if (P.settleOffset) s = `<g transform="translate(${P.settleOffset.dx} ${P.settleOffset.dy})">${s}</g>`;
        return s;
      };
      return `<svg xmlns="http://www.w3.org/2000/svg" width="${P.w}" height="${P.h}" viewBox="0 0 ${P.w} ${P.h}">${wrap(body)}</svg>`;
    };
    P.manifest = function (o) {
      o = o || {};
      // ONE SCALE, WHOLE LIBRARY, AND NOT A PARAMETER.
      const scale = (g.AUDIT && g.AUDIT.EXPORT_SCALE) || 2;
      const name = P.key.split("/").pop();
      // TYPE BUDGETS COME OFF THE BOXES, HERE, FOR EVERY PLATE.
      //
      // The derivation returns a PER-PLATE copy of the role table on
      // `rows.roles`, and this plate emits that copy rather than the shared
      // table the author handed it. Emitting the shared one is what let a family
      // build accumulate role floors across plates (see engine/budget.js).
      let meta = P.meta;
      if (g.BUDGET && P.meta && P.meta.typeRoles) {
        P.budgets = g.BUDGET.derive(P.slots, P.meta.typeRoles);
        if (P.budgets && P.budgets.roles) meta = Object.assign({}, P.meta, { typeRoles: P.budgets.roles });
      }
      const m = Object.assign({
        canvas: [P.w, P.h],
        exportScale: scale,
        delivered: [P.w * scale, P.h * scale],
        frameCount: 1, fps: 0, playback: "static",
        frames: [{ tag: "", svg: name + ".svg", png: name + ".png" }],
        files: { png: name + ".png", svg: name + ".svg" },
        slots: P.slots,
        clipBox: P.clipBox || undefined,
        settleOffset: P.settleOffset || undefined,
        decorBoxes: P.decor.length ? P.decor : undefined,
      }, meta);
      // The opted-in families SAY SO in the manifest. A plate drawn by a
      // different hand than the family beside it is the one fact a reader
      // downstream cannot recover from the PNG, and it is the field to grep when
      // the two hands have to be told apart in a cut. Absent on the twelve
      // families that did not opt in, so their manifests do not move.
      if (prof !== P1) m.hand = prof;
      return m;
    };
    return P;
  }

  g.HAND = {
    rng, wobble, stroke, line, hatch, fillRect, polyRect, outline, toPath, Plate, num, speckle,
    setBoil, boilAmp: () => BOIL_AMP, breathe, pin, boiling,
    boilGate: () => !!BOIL_GATE, boilFrame: () => BOIL,
    // §4's one-line switch: PROFILE_FAMILIES is the whole opt-in list. Adding a
    // family here converts it; emptying it reverts the kit to one hand.
    PROFILES: { legacy: P1, revised: P2 }, PROFILE_FAMILIES, profileFor,
    setProfile, profile: () => PROFILE, LIGHT, darken,
  };
})(typeof window !== "undefined" ? window : globalThis);
