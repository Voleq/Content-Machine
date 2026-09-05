/* Dennis v2 — the contact sheet packer.

   This file exists for the reason render.js exists. Every family's
   contact-sheet.svg was packed by a throwaway script, and it shows: nine
   families sit on one grid — 3 up, a 420-unit cell, 34 of padding, each plate
   scaled to fit its own cell and centred in it — and `tables/` sits on a second
   one that grouped the landscapes three-up and then squeezed six portraits into
   a single row at a smaller scale. Two packers means the sheets are not
   comparable, which is the one job a contact sheet has.

   So the grid is declared once, here, and a sheet is regenerated rather than
   maintained. It inlines each plate's own vector geometry, which is why host/
   and room/ have no sheet and ship thumbnails instead: a room plate is ~1.4 MB
   of vector and twenty-four of them is not a sheet, it is a download.

   Run it from a page that has already loaded hand.js, plates.js, series.js and
   build.js. It touches no files. */
(function (g) {
  const PAD = 34, CELL = 420, COLS = 3;
  const PITCH = CELL + PAD;

  // A tile is the plate's own body, scaled to fit the cell and centred in it.
  // Never a redraw at tile size: a plate drawn small is a different drawing, and
  // that is exactly what makes a contact sheet lie.
  function tileOf(svg, w, h, col, row) {
    const k = Math.min(CELL / w, CELL / h);
    const x = PAD + col * PITCH + (CELL - w * k) / 2;
    const y = PAD + row * PITCH + (CELL - h * k) / 2;
    const body = svg.replace(/^<svg[^>]*>/, "").replace(/<\/svg>\s*$/, "");
    return `<g transform="translate(${x.toFixed(1)}, ${y.toFixed(1)}) scale(${k.toFixed(5)})">${body}</g>`;
  }

  // items: [{ svg, w, h }] in the order build.js declares them, which is the
  // order the family reads in.
  function pack(items, bg) {
    const rows = Math.ceil(items.length / COLS);
    const W = PAD + COLS * PITCH, H = PAD + rows * PITCH;
    const tiles = items.map(function (it, i) {
      return tileOf(it.svg, it.w, it.h, i % COLS, Math.floor(i / COLS));
    });
    return `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">`
      + `<rect width="${W}" height="${H}" fill="${bg}"></rect>${tiles.join("")}</svg>`;
  }

  g.SHEET = {
    PAD: PAD, CELL: CELL, COLS: COLS,
    pack: pack,
    // Frame one of every declared asset in a family, packed.
    family: function (dir) {
      const items = g.BUILD.of(dir).map(function (it) {
        const fr = g.BUILD.framesOf(it)[0];
        const P = g.BUILD.draw(it, null, fr.args);
        return { svg: P.toSVG(), w: P.w, h: P.h };
      });
      // A sheet is a file, so it is serialised the way every other file in this
      // library is — see engine/render.js fileSVG.
      return g.RENDER.fileSVG(pack(items, g.PLATES.SURFACES["night-card"].ground2));
    },
  };
})(typeof window !== "undefined" ? window : globalThis);
