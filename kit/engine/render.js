/* Dennis v2 — the renderer.

   This file exists because for four revisions the plates were emitted by
   throwaway scripts. build.js says what the library IS; this says how a declared
   asset becomes the files on disk, and it is the only place that knows the
   answer. Anything it does that build.js or audit.js could own belongs there
   instead.

   THREE RULES IT ENFORCES, none of which a caller can opt out of:

   1. The base file is the SAME RENDER as frame one, byte for byte — not a third
      draw. It is produced by copying frames[0], never by drawing again with
      boil 0. A base file that is its own render pops on the first frame of a loop.

   2. exportScale comes from AUDIT.EXPORT_SCALE and is 2 for every family. The
      PNG is rasterised at canvas x 2 and the manifest records the same number,
      because they come from the same constant.

   3. The manifest is emitted by the call that DRAWS the plate. Geometry cannot
      drift from the drawing if there is no second code path that could disagree.

   Run it from a page that has already loaded hand.js, plates.js, audit.js,
   series.js and build.js. RENDER.family("room") returns everything a writer
   needs to put on disk; it touches no files itself, so the same function serves
   a preview board and a delta pack. */
(function (g) {
  // THE ON-DISK FORM, and it took writing a fifth pack to notice.
  //
  // Every SVG in this library was written to disk through a browser DOM round
  // trip, which expands empty elements: the files say `<path …></path>` where
  // toSVG() says `<path …/>`. Identical drawing, identical geometry, different
  // bytes — so "reproduces byte-for-byte from PLATES.<author>({key, seed})" was
  // true about the DRAWING and false about the FILE for four revisions, and any
  // check that compared a fresh render against disk reported 23 changed assets
  // that had not changed at all. That is precisely the class of false positive
  // the audit exists to not produce.
  //
  // So the serialisation is declared here, in the one file that says how an
  // asset becomes a file, and every writer goes through it: plates, proofs and
  // contact sheets alike. Verified on re-emit — all 23 previously shipped assets
  // in the two families this pack touches reproduce their files byte-for-byte.
  const VOID = /<(rect|path|circle|ellipse|line|polyline|polygon|use|image|stop)((?:"[^"]*"|[^>"])*?)\/>/g;
  const fileSVG = function (svg) { return svg.replace(VOID, "<$1$2></$1>"); };

  const svgOf = function (item, frameArgs) {
    const P = g.BUILD.draw(item, null, frameArgs);
    return { svg: fileSVG(P.toSVG()), plate: P };
  };

  // Every file one asset ships, plus the manifest entry that describes it.
  // frames[] entries are OBJECTS — {tag, svg, png, boil, ...} — because a bare
  // filename cannot say what a frame is, and a player should never parse meaning
  // out of a string suffix.
  const asset = function (item) {
    const name = item.key.split("/").pop();
    const frames = g.BUILD.framesOf(item);
    const pb = g.BUILD.playbackOf(item);
    const files = [];
    let manifest = null;

    frames.forEach(function (fr, i) {
      const r = svgOf(item, fr.args);
      const tag = fr.tag || "";
      files.push({ path: item.dir + "/" + name + tag + ".svg", svg: r.svg });
      if (i === 0) {
        manifest = Object.assign(r.plate.manifest(), {
          author: item.author,
          seed: item.seed,
          surface: g.BUILD.surfaceOf(item.key),
          frameCount: pb.frameCount,
          fps: pb.fps,
          playback: pb.playback,
          // ONE FRAME SHAPE FOR THE WHOLE LIBRARY: {tag, svg, png, boil, …}.
          // A static plate carries boil 0 and tag null rather than dropping the
          // key and emitting "" — an absent field and an empty string are two
          // different statements to a strict reader, and a library with two
          // frame shapes in it makes every reader guess which one it has.
          frames: frames.map(function (f2) {
            return Object.assign({
              tag: f2.tag || null,
              svg: name + (f2.tag || "") + ".svg",
              png: name + (f2.tag || "") + ".png",
            }, f2.args, { boil: (f2.args && f2.args.boil) | 0 });
          }),
          files: {
            png: name + ".png",
            svg: name + ".svg",
            baseIsFrame: frames[0].tag || null,
            note: "The base file is the SAME RENDER as " + (frames[0].tag || "frame one") + ", byte for byte — not a third draw. A player that shows the base and then enters the loop must not see the line jump on the first frame.",
          },
        });
        // RULE 1, and it is mechanical rather than trusted: the base file is a
        // COPY of frame one's bytes. There is no code path here that could draw
        // it a second time, so it cannot drift.
        files.push({ path: item.dir + "/" + name + ".svg", svg: r.svg });
      }
    });
    return { key: item.key, dir: item.dir, name: name, files: files, manifest: manifest };
  };

  // ---------------- proofs ----------------
  // A TYPESETTING PROOF, which is a different artifact from a plate: it is the
  // only file in this library that has text in it, and that is the whole point.
  // The plates declare a box and a point size per slot and the compositor fits
  // type INTO the box, so a slot too small for the copy it is meant to hold
  // never fails — it silently renders smaller than declared. A number in a
  // manifest cannot show that. Type set at the declared size, unfitted, against
  // the box outline can: anything crossing its outline is copy the renderer will
  // shrink, and you can see by how much.
  //
  // Never ingest one. It is not in build.js, it has no manifest entry, and it
  // breaks the library's no-baked-text rule on purpose.
  //
  // fontCSS is passed IN (an @font-face block with the faces embedded) because
  // this file reads no files. Without it a rasteriser substitutes and the proof
  // proves nothing about the fonts the kit actually ships.
  const proof = function (key, fills, opts) {
    opts = opts || {};
    const item = g.BUILD.LIB.filter(function (it) { return it.key === key; })[0];
    if (!item) throw new Error("proof: " + key + " is not a declared asset");
    const fr = g.BUILD.framesOf(item)[0];
    const P = g.BUILD.draw(item, null, fr.args);
    const man = P.manifest();
    const hex = opts.hex || {};
    const roles = man.typeRoles || {};
    const parts = [];
    if (opts.fontCSS) parts.push("<defs><style>" + opts.fontCSS + "</style></defs>");

    Object.keys(man.slots).forEach(function (nm) {
      const sl = man.slots[nm];
      if (sl.region) {
        // The regions the plate reserved, filled by the renderer it names, so the
        // proof is the whole frame rather than the type half of it.
        const d = (opts.marks || {})[nm];
        if (d && g.SERIES) parts.push('<g transform="translate(' + sl.x + ',' + sl.y + ')">' +
          g.SERIES.rangeMark({ box: { x: 0, y: 0, w: sl.w, h: sl.h }, t: d.t, median: d.median, pal: opts.pal || {}, seed: 1600 }).svg + "</g>");
        return;
      }
      const text = fills[nm];
      if (text == null || text === "") return;
      const tr = roles[sl.role];
      if (!tr) return;
      // The box, so an overrun is measurable off the picture and not asserted.
      parts.push('<rect x="' + sl.x + '" y="' + sl.y + '" width="' + sl.w + '" height="' + sl.h +
        '" fill="none" stroke="' + (hex.attention || "#E0A016") + '" stroke-width="1.5" stroke-dasharray="7 6" opacity="0.75"></rect>');
      const anchor = sl.align === "right" ? "end" : sl.align === "center" ? "middle" : "start";
      const tx = sl.align === "right" ? sl.x + sl.w : sl.align === "center" ? sl.x + sl.w / 2 : sl.x;
      const body = tr.transform === "uppercase" ? String(text).toUpperCase() : String(text);
      parts.push('<text x="' + tx + '" y="' + (sl.y + sl.h / 2) + '" text-anchor="' + anchor +
        '" dominant-baseline="central" font-family="' + tr.font + '" font-size="' + tr.size +
        '" font-weight="' + (tr.weight || 400) + '" fill="' + (hex[tr.colour] || hex.structure || "#1C222A") +
        '" opacity="' + (tr.opacity == null ? 1 : tr.opacity) + '"' +
        (tr.tracking ? ' letter-spacing="' + tr.tracking + '"' : "") +
        ' xml:space="preserve">' + body.replace(/&/g, "&amp;").replace(/</g, "&lt;") + "</text>");
    });

    const svg = fileSVG(P.toSVG()).replace(/<\/svg>\s*$/, parts.join("") + "</svg>");
    return { key: key, svg: svg, w: P.w, h: P.h, slots: man.slots, typeRoles: roles };
  };

  g.RENDER = {
    asset: asset,
    proof: proof,
    fileSVG: fileSVG,
    of: function (keys) {
      const want = {};
      keys.forEach(function (k) { want[k] = 1; });
      return g.BUILD.LIB.filter(function (it) { return want[it.key]; }).map(asset);
    },
    family: function (dir) { return g.BUILD.of(dir).map(asset); },
    // The manifest for a whole family, complete rather than partial: a merge
    // downstream should be a REPLACE of one file, never a patch applied to one.
    // The family HEADER comes from build.js too. It used to be typed into a
    // writer script beside the manifest it described, which is the same drift
    // this file exists to close: the header says what the family is FOR, and a
    // hand-maintained copy of that had nothing checking it.
    manifestFor: function (dir, extra) {
      const out = { assets: {} };
      g.BUILD.of(dir).forEach(function (it) { out.assets[it.key] = asset(it).manifest; });
      return Object.assign({}, (g.BUILD.FAMILY_NOTES || {})[dir] || {}, extra || {}, out);
    },
    EXPORT_SCALE: (g.AUDIT && g.AUDIT.EXPORT_SCALE) || 2,
  };
})(typeof window !== "undefined" ? window : globalThis);
