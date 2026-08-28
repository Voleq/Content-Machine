/* Dennis v2 — the canonical audit metric.

   This file exists because of a disagreement, not a defect. A pipeline-side
   audit reported seven over-boiled assets (overlays/row-band at 14.67 units,
   underline-swipe at 11.0) and one dead one (shorts/hook-card-t3 at 0.0). Every
   one of those assets measures 0.6–1.4 units mean, 2.8–5.0 peak, against a spec
   of ~2 units of movement per point. Both audits are reading the same files.

   Two ways to get a wrong number out of a right file, and this file closes both:

   1. UNALIGNED TOKEN DIFF. Diff two frames by walking their numeric tokens in
      order, and the reading is only valid while the two frames have the SAME
      geometry with different coordinates. The moment frame two has a different
      number of paths — the host's open mouth, a bob, any structural change —
      every token after the divergence is compared against the wrong token and
      the mean explodes. Measured that way the host strips read 230–296 units of
      "boil". They are not boiling 250 units; the metric lost alignment on token
      12 and never recovered. So amplitude() REFUSES rather than returns a
      number when the two frames are not structurally comparable.

   2. SAMPLING A SPARSE PLATE. On a full-bleed plate the ink is a small fraction
      of the numbers in the file: shorts/hook-card-t3 moves 269 of its 11,627
      tokens, because the other 11,358 are a card, a grain field and type
      geometry that are deliberately held still. Sample the head of the file and
      you measure the still part and report 0.0. So amplitude() reports movement
      over the tokens THAT MOVE, and carries the moved/total fraction next to it
      so a sparse plate can never be mistaken for a frozen one.

   Everything here is measurement only. It draws nothing and it fixes nothing —
   if a number comes back out of band, the fix belongs in hand.js or build.js. */
(function (g) {
  // ONE SCALE, WHOLE LIBRARY. Not a per-family choice, and not a per-asset
  // argument: a shot cuts a room, a card and an annotation into the same frame,
  // and any family rendered at a different scale forces a resample step in the
  // middle of a composite. 2 is the floor that survives the two things this
  // library is actually asked to do — a 16:9 room filling a 9:16 frame (1.78×
  // horizontal crop-and-scale), and a push-in on a card — and 1 has no headroom
  // for either. The constant lives here, hand.js reads it, and manifest() takes
  // no scale argument at all, so drift has nowhere to enter.
  const EXPORT_SCALE = 2;

  // The boil spec, in canvas units of displacement per drawn point.
  const BOIL = {
    target: 2,        // hand.js amplitude
    meanBand: [0.4, 2.0],   // mean Euclidean displacement of a moved point
    peakBand: [1.5, 6.0],   // largest single displacement on the plate
    deadBelow: 0.15,        // below this the asset is frozen, not subtle
    minMovedFraction: 0.01, // below this the INK isn't moving, whatever the mean says
  };

  const NUM = /-?\d*\.?\d+/g;
  const CMD = /[MmLlCcQqSsTtAaZzHhVv]|-?\d*\.?\d+/g;

  // Every d="" in the file, in document order.
  function pathsOf(svg) {
    const out = []; const re = /\sd="([^"]*)"/g; let m;
    while ((m = re.exec(svg))) out.push(m[1]);
    return out;
  }

  // A path split into its command signature and its coordinate stream. The
  // signature is what makes two paths comparable: same commands in the same
  // order means the same drawing, and any coordinate difference is movement.
  function shapeOf(d) {
    const toks = d.match(CMD) || [];
    let sig = ""; const xy = [];
    for (const t of toks) {
      if (/[A-Za-z]/.test(t)) sig += t; else xy.push(+t);
    }
    return { sig: sig, xy: xy };
  }

  // Arcs and the shorthand H/V commands break the assumption that coordinates
  // arrive in (x, y) pairs, so Euclidean pairing is not valid on those paths.
  const pairable = (sig) => !/[AaHhVv]/.test(sig);

  /* Align two path lists by command signature.

     Needed because a boil offset can change a plate's path COUNT, not just its
     coordinates: the hatch and fibre passes take their line counts from the same
     rng the wobble does, so re-seeding the wobble re-rolls how many hatch lines
     the plate has. Every host frame pair differs by 10–40 paths for that reason
     alone, with no structural intent behind it. A strict count check therefore
     refuses the entire host family, which is over-strict: most paths still
     correspond, and those are measurable.

     So walk both lists and pair paths whose signatures match, skipping inserted
     ones on either side. Returns the pairs and the coverage — what fraction of
     the larger list found a partner. Low coverage still means the frames are
     different drawings, and amplitude() still refuses. */
  function align(A, B) {
    const pairs = [];
    let i = 0, j = 0, skipped = 0;
    while (i < A.length && j < B.length) {
      const a = shapeOf(A[i]), b = shapeOf(B[j]);
      if (a.sig === b.sig && a.xy.length === b.xy.length) { pairs.push([a, b]); i++; j++; continue; }
      // look a short way ahead on each side for the next signature match rather
      // than giving up — an inserted path should cost one path, not the rest
      let hit = -1, side = 0;
      for (let k = 1; k <= 6 && hit < 0; k++) {
        if (i + k < A.length) { const s = shapeOf(A[i + k]); if (s.sig === b.sig && s.xy.length === b.xy.length) { hit = k; side = 1; } }
        if (hit < 0 && j + k < B.length) { const s = shapeOf(B[j + k]); if (s.sig === a.sig && s.xy.length === a.xy.length) { hit = k; side = 2; } }
      }
      if (hit < 0) { i++; j++; skipped++; continue; }
      if (side === 1) { i += hit; skipped += hit; } else { j += hit; skipped += hit; }
    }
    return { pairs: pairs, skipped: skipped, coverage: pairs.length / Math.max(A.length, B.length) };
  }

  /* Displacement between two renders of the same drawing, in canvas units.

     Returns {comparable:false, reason} rather than a number when the two frames
     are not the same drawing — that refusal is the point of this function. When
     they are, returns mean/peak Euclidean displacement over the points that
     moved, plus how much of the plate moved at all. */
  function amplitude(svgA, svgB) {
    const A = pathsOf(svgA), B = pathsOf(svgB);
    if (!A.length || !B.length) return { comparable: false, reason: "no path data in one or both frames" };
    const al = align(A, B);
    if (al.coverage < 0.8) {
      return { comparable: false, reason: `only ${(al.coverage * 100).toFixed(0)}% of paths correspond between the frames (${A.length} vs ${B.length}) — these are different drawings, not one drawing re-wobbled, and a positional diff across them is meaningless.` };
    }
    let sum = 0, moved = 0, total = 0, peak = 0, unpairable = 0;
    for (const pr of al.pairs) {
      const a = pr[0], b = pr[1];
      if (!pairable(a.sig)) { unpairable++; continue; }
      for (let j = 0; j + 1 < a.xy.length; j += 2) {
        const dx = b.xy[j] - a.xy[j], dy = b.xy[j + 1] - a.xy[j + 1];
        const d = Math.sqrt(dx * dx + dy * dy);
        total++;
        if (d > 1e-9) { moved++; sum += d; if (d > peak) peak = d; }
      }
    }
    if (!total) return { comparable: false, reason: "no pairable coordinates (all arc/shorthand paths)" };
    return {
      comparable: true,
      partial: al.coverage < 0.999,
      coverage: al.coverage,
      mean: moved ? sum / moved : 0,
      peak: peak,
      moved: moved,
      total: total,
      movedFraction: moved / total,
      skipped: { unaligned: al.skipped, unpairable: unpairable },
    };
  }

  // Verdict for one asset's amplitude reading, against the boil spec.
  function boilVerdict(r) {
    if (!r.comparable) return { ok: null, note: r.reason };
    if (r.movedFraction < BOIL.minMovedFraction) return { ok: false, note: `only ${(r.movedFraction * 100).toFixed(1)}% of points move — the ink is frozen` };
    if (r.mean < BOIL.deadBelow) return { ok: false, note: `dead: ${r.mean.toFixed(2)} units` };
    if (r.mean < BOIL.meanBand[0]) return { ok: false, note: `under-boiled: ${r.mean.toFixed(2)} units mean` };
    if (r.mean > BOIL.meanBand[1]) return { ok: false, note: `over-boiled: ${r.mean.toFixed(2)} units mean` };
    if (r.peak > BOIL.peakBand[1]) return { ok: false, note: `peak ${r.peak.toFixed(1)} units exceeds ${BOIL.peakBand[1]}` };
    const cov = r.partial ? `, ${(r.coverage * 100).toFixed(0)}% of paths aligned` : "";
    return { ok: true, note: `${r.mean.toFixed(2)} mean / ${r.peak.toFixed(1)} peak over ${(r.movedFraction * 100).toFixed(0)}% of points${cov}` };
  }

  /* Scale check for one manifest entry. delivered MUST be canvas × EXPORT_SCALE
     and the file on disk must match delivered. Pass the real PNG dimensions in
     as [w,h]; this file does not read files. */
  function scaleVerdict(entry, filePx) {
    const want = [entry.canvas[0] * EXPORT_SCALE, entry.canvas[1] * EXPORT_SCALE];
    const declared = entry.delivered || [];
    const notes = [];
    if (entry.exportScale !== EXPORT_SCALE) notes.push(`declares exportScale ${entry.exportScale}, library scale is ${EXPORT_SCALE}`);
    if (declared[0] !== want[0] || declared[1] !== want[1]) notes.push(`declares delivered ${declared.join("×")}, canvas × ${EXPORT_SCALE} is ${want.join("×")}`);
    if (filePx && (filePx[0] !== want[0] || filePx[1] !== want[1])) notes.push(`file is ${filePx.join("×")}, should be ${want.join("×")}`);
    return { ok: !notes.length, want: want, notes: notes };
  }

  g.AUDIT = {
    EXPORT_SCALE: EXPORT_SCALE,
    BOIL: BOIL,
    pathsOf: pathsOf,
    shapeOf: shapeOf,
    align: align,
    amplitude: amplitude,
    boilVerdict: boilVerdict,
    scaleVerdict: scaleVerdict,
  };
})(typeof window !== "undefined" ? window : globalThis);
