/* Dennis v2 — kit-model.js
 *
 * THE MODEL, once. The proportion table, the two hour palettes, the fourteen
 * parts, the ten poses and the eight rooms — as one module that both the
 * emitter and the review surface read.
 *
 * It exists because of §8.1 and because of what happened without it: the
 * anchor derivation lived inside one section of the review page for a rebuild,
 * and two other sections carried on drawing a stale rectangle. A model that
 * lives in a page cannot be read by an emitter, and a model that is copied is
 * a model that disagrees with itself.
 *
 * Nothing here knows about the DOM, React, or how anything is presented.
 *
 *   const M = require('./kit-model');
 *   M.geometry('sitting-at-desk');   // the fourteen paths for one pose
 *   M.paint(g, M.NIGHT);             // the same paths, one hour's colours
 *   M.anchorOf(room);                // [x, y, w, h], width derived
 *
 * Generated from the review surface at rebuild-06 rather than retyped.
 */

'use strict';

class KitModel {
  static P = {
    totalHeight: 7.0, headHeight: 1.0, headWidth: 0.78, eyelineFromCrown: 0.52,
    shoulderFromCrown: 1.32, shoulderWidth: 1.80, torsoLength: 2.45, hipFromCrown: 3.77,
    armUpperLength: 1.32, armForeLength: 1.18, handLength: 0.46, handWidth: 0.30,
    legUpperLength: 1.60, legLowerLength: 1.63, footLength: 0.62, seatedRatio: 0.735,
    glassesWidth: 0.62, glassesLensHeight: 0.20, glassesRadius: 0.06,
    eyeDashLength: 0.10, eyeDashWeight: 0.038,
  };

  // THE RIG SLUMP. The character sheet is explicit that this lives at the
  // skeleton and not in the outline — revision 06 of the drawn kit dipped the
  // torso polygon while the skeleton stayed vertical and mirrored, and nothing
  // read. So: loaded leg camera-left, that hip raised, shoulders counter-tilting
  // to it, spine bowed, head off the vertical. Five numbers, one place.
  static RIG = { hipRaiseL: -9, hipDropR: 5, shoulderDropL: 8, shoulderRiseR: -5, spineBow: 6, headDx: 3, headRot: -2.6, glassesRot: 2.2 };

  static NIGHT = {
    name: "night", label: "three in the morning", contour: "#0B0E16",
    sources: [{ name: "key · monitor", hex: "#7FD4E8" }, { name: "fill · lamp", hex: "#F0B460" }, { name: "ambient", hex: "#141824" }],
    m: {
      wall: ["#20293C", "#141824"], wallSide: ["#27324A", "#171C2B"], floor: ["#1A2130", "#0F131D"],
      desk: ["#3E4759", "#6B4A32"], screen: ["#7FD4E8", "#4FA8BE"], glow: ["#3C7A8C", "#2A5866"],
      lamp: ["#F0B460", "#C4813A"], skin: ["#8FA8B8", "#D9A06B"], hair: ["#525E74", "#6B5247"],
      shirt: ["#46596E", "#2A3242"], trouser: ["#4E5A70", "#38404F"], paper: ["#C9D2D8", "#E0BC88"],
      prop: ["#5A4A3E", "#38302A"],
    },
    ink: { ground: "#171D2A", band: "#1F2634", rule: "#2C3444", axis: "#4A566A", quiet: "#8592A6", structure: "#C6D2E0", subject: "#7FD4E8", subject2: "#F0B460", attention: "#F07A5A" },
  };
  static DUSK = {
    name: "dusk", label: "the lit set", contour: "#2A2036",
    sources: [{ name: "key · window", hex: "#F2B268" }, { name: "fill · lamp", hex: "#F5C981" }, { name: "ambient", hex: "#3B3550" }],
    m: {
      wall: ["#B9A184", "#5E5470"], wallSide: ["#A8906F", "#514868"], floor: ["#9B7F5E", "#453C58"],
      desk: ["#D8A95F", "#6A5A70"], screen: ["#8FB8C4", "#5E8894"], glow: ["#F0D49A", "#C9A870"],
      lamp: ["#F5C981", "#C99A55"], skin: ["#F5C79A", "#B06A5E"], hair: ["#4A3A34", "#33283C"],
      shirt: ["#93AECE", "#3B4A72"], trouser: ["#6B6480", "#3E3850"], paper: ["#F2E8D4", "#B8A894"],
      prop: ["#6E6478", "#453E55"],
    },
    ink: { ground: "#F2E8D4", band: "#E6D8C0", rule: "#D8C8AC", axis: "#A08E74", quiet: "#685A48", structure: "#2A2036", subject: "#2F5FA8", subject2: "#D88A2F", attention: "#A8243C" },
  };





  // A band of a joint chain, between two fractions of the half-width. f = -1 is
  // the camera-right edge, f = +1 the camera-left edge, so (-1, -0.32) is the
  // shade strip down the key-away side of any limb in any pose. THIS is the fix
  // for "I don't get that shade of light from him": v1 clipped every part
  // against one straight line down the frame, which is a mask, not light.
  band(pts, widths, a, b) {
    const n = pts.length, A = [], B = [];
    for (let i = 0; i < n; i++) {
      const p0 = pts[Math.max(0, i - 1)], p1 = pts[Math.min(n - 1, i + 1)];
      let dx = p1[0] - p0[0], dy = p1[1] - p0[1];
      const len = Math.hypot(dx, dy) || 1;
      const nx = -dy / len, ny = dx / len, h = widths[i] / 2;
      A.push([pts[i][0] + nx * h * a, pts[i][1] + ny * h * a]);
      B.push([pts[i][0] + nx * h * b, pts[i][1] + ny * h * b]);
    }
    const f = p => p[0].toFixed(1) + "," + p[1].toFixed(1);
    return "M" + A.map(f).join(" L") + " L" + B.reverse().map(f).join(" L") + " Z";
  }

  roundRect(x, y, w, h, r) {
    return "M" + (x + r) + "," + y + " L" + (x + w - r) + "," + y +
      " Q" + (x + w) + "," + y + " " + (x + w) + "," + (y + r) +
      " L" + (x + w) + "," + (y + h - r) + " Q" + (x + w) + "," + (y + h) + " " + (x + w - r) + "," + (y + h) +
      " L" + (x + r) + "," + (y + h) + " Q" + x + "," + (y + h) + " " + x + "," + (y + h - r) +
      " L" + x + "," + (y + r) + " Q" + x + "," + y + " " + (x + r) + "," + y + " Z";
  }

  // THE ONE ANCHOR DERIVATION, used by every section that draws or prints an
  // anchor. It lived inside the slice-4 block for one rebuild, which left the
  // slice-2 diagram and the §8 room cards still drawing the old typed
  // rectangle — the page then showed two different "host anchor" widths for the
  // same room, which is the defect §4.4a and §8.1 were written to outlaw,
  // reproduced by the fix for it. One definition, no exceptions.
  figInk() {
    if (KitModel._figInk) return KitModel._figInk;
    const g = this.geometry("to-camera");
    const ds = g.body.map(p => p.d).concat(g.head.map(p => p.d));
    let x0 = 1e9, x1 = -1e9;
    const re = /(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)/g;
    ds.forEach(d => { let m; while ((m = re.exec(d))) { const x = parseFloat(m[1]); if (x < x0) x0 = x; if (x > x1) x1 = x; } });
    return (KitModel._figInk = (x1 - x0) / 720);
  }
  // An anchor publishes a HEIGHT; the width follows from the figure's ink
  // aspect, centred on the authored rect's centre (§4.4a).
  anchorOf(r) {
    if (!r || !r.anchor) return null;
    const A = r.anchor, cx = A[0] + A[2] / 2, w = A[3] * this.figInk();
    return [Math.round((cx - w / 2) * 10) / 10, A[1], Math.round(w * 10) / 10, A[3]];
  }

  // WHERE THE STANDING BOX LANDS in a room: the 720-unit box scaled to the
  // anchor's height, floor on the anchor's bottom edge, centred on it (§4.4a).
  placeOf(r) {
    const A = this.anchorOf(r); if (!A) return null;
    const sc = A[3] / 720;
    return { sc, tx: A[0] + A[2] / 2 - 200 * sc, ty: A[1] + A[3] - 760 * sc };
  }
  // A path as polygons: rect() form exactly, everything else by its coordinate
  // pairs in order (curve control points taken as vertices — close enough for
  // a coverage measure, and it errs toward counting a touch as a hit).
  static polys(d) {
    const out = [];
    String(d).split(/(?=M)/).forEach(sub => {
      const r = sub.match(/^M(-?[\d.]+),(-?[\d.]+)h(-?[\d.]+)v(-?[\d.]+)h/);
      if (r) { const [x, y, w, h] = r.slice(1, 5).map(Number); out.push([[x, y], [x + w, y], [x + w, y + h], [x, y + h]]); return; }
      const pts = []; const re = /(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)/g; let m;
      while ((m = re.exec(sub))) pts.push([+m[1], +m[2]]);
      if (pts.length > 2) out.push(pts);
    });
    return out;
  }
  static inPoly(P, x, y) {
    const b = P.bb || (P.bb = [Math.min(...P.map(p => p[0])), Math.min(...P.map(p => p[1])), Math.max(...P.map(p => p[0])), Math.max(...P.map(p => p[1]))]);
    if (x < b[0] || x > b[2] || y < b[1] || y > b[3]) return false;
    let c = false;
    for (let i = 0, j = P.length - 1; i < P.length; j = i++) {
      const [xi, yi] = P[i], [xj, yj] = P[j];
      if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) c = !c;
    }
    return c;
  }
  // THE COMPOSITE CHECK (§4.5, rule 27). The figure placed by the contract, the
  // room's front layer over him, measured on a 1u grid in room units:
  //   headCover  — % of head + hair under a front shape. Must be 0.
  //   upperCover — % of his ink ABOVE THE DESK TOP under a front shape. The desk
  //                itself hides his legs by design; nothing above it should
  //                hide him.
  // rebuild-18 looked at rooms with nobody in them. This looks with him in.
  clearance(r, poseKey) {
    const at = this.placeOf(r); if (!at) return null;
    const front = [].concat(...r.shapes.filter(s => s.front).map(s => KitModel.polys(s.d)));
    const deskYs = [].concat(...r.shapes.filter(s => s.front && s.role === "desk").map(s => KitModel.polys(s.d)))
      .map(P => Math.min(...P.map(p => p[1])));
    const deskTop = deskYs.length ? Math.min(...deskYs) : Infinity;
    const g = this.geometry(poseKey);
    const T = P => P.map(([x, y]) => [at.tx + x * at.sc, at.ty + y * at.sc]);
    const head = [].concat(...g.head.map(p => KitModel.polys(p.d))).map(T);
    const body = [].concat(...g.body.map(p => KitModel.polys(p.d))).map(T).concat(head);
    const all = [].concat(...body); const bx = [Math.min(...all.map(p => p[0])), Math.min(...all.map(p => p[1])), Math.max(...all.map(p => p[0])), Math.max(...all.map(p => p[1]))];
    let h = 0, hc = 0, u = 0, uc = 0; const st = 1;
    for (let y = bx[1] + st / 2; y < bx[3]; y += st) for (let x = bx[0] + st / 2; x < bx[2]; x += st) {
      const inH = head.some(P => KitModel.inPoly(P, x, y));
      const inB = inH || body.some(P => KitModel.inPoly(P, x, y));
      if (!inB) continue;
      const cov = front.some(P => KitModel.inPoly(P, x, y));
      if (inH) { h++; if (cov) hc++; }
      if (y < deskTop) { u++; if (cov) uc++; }
    }
    return { pose: poseKey, box: bx.map(v => Math.round(v * 10) / 10), headCover: h ? Math.round((hc / h) * 1000) / 10 : 0, upperCover: u ? Math.round((uc / u) * 1000) / 10 : 0 };
  }
  // Every pose that names this room in its `fits`, plus to-camera; the worst.
  clearanceOf(r) {
    if (!this.anchorOf(r)) return null;
    const keys = Object.keys(KitModel.POSES).filter(k => k === "to-camera" || KitModel.POSES[k].fits.split(" · ").indexOf(r.id) >= 0);
    const rows = keys.map(k => this.clearance(r, k));
    const worst = f => rows.reduce((a, b) => (b[f] > a[f] ? b : a));
    const box = rows.reduce((a, r) => [Math.min(a[0], r.box[0]), Math.min(a[1], r.box[1]), Math.max(a[2], r.box[2]), Math.max(a[3], r.box[3])], [Infinity, Infinity, -Infinity, -Infinity]);
    const strip = r0 => ({ pose: r0.pose, headCover: r0.headCover, upperCover: r0.upperCover });
    return { poses: keys.length, head: strip(worst("headCover")), upper: strip(worst("upperCover")), figureBox: box };
  }

  static rect(x, y, w, h) { return "M" + x + "," + y + "h" + w + "v" + h + "h" + (-w) + "z"; }
  static poly(pts) { return "M" + pts.map(p => p.join(",")).join("L") + "Z"; }

  // TEN POSES. Seven carry the drawn kit's own names — those shots were right,
  // the drawing was not — and each names the angle it exists for, so the pose
  // list and the room list cannot drift apart.
  static POSES = {
    "to-camera": { label: "to camera", origin: "new", fits: "desk-front · desk-wide", note: "Down the lens. The default, and most of every video." },
    "leaning-on-desk": { label: "leaning on desk", origin: "drawn kit", fits: "desk-front · desk-side",
      note: "Weight through the near arm onto the desk — the loaded hip swaps sides, which the rig does for free.",
      arms: c => ({ R: [[c.cx + c.sw * 0.9, c.shR + 12], [c.cx + 118, c.shR + 118], [c.cx + 150, c.shR + 232]] }),
      legs: c => ({ L: [[c.cx - 36, c.hipL - 8], [c.cx - 52, c.knee], [c.cx - 70, c.floor - 16]] }) },
    "hands-in-pockets": { label: "hands in pockets", origin: "drawn kit", fits: "desk-front · doorway",
      note: "Forearms angled in, hands at the hip. The most closed pose and the one that holds under a long voice-over.",
      arms: c => ({
        L: [[c.cx - c.sw * 0.9, c.shL + 14], [c.cx - 100, c.shL + 122], [c.cx - 58, c.shL + 212]],
        R: [[c.cx + c.sw * 0.9, c.shR + 12], [c.cx + 104, c.shR + 124], [c.cx + 64, c.shR + 216]],
      }) },
    "holding-a-page": { label: "holding a page", origin: "drawn kit", fits: "desk-front · board", face: "lamp",
      note: "Both hands to a sheet at chest height. The page is a prop path in the paper role, not part of him.",
      arms: c => ({
        L: [[c.cx - c.sw * 0.9, c.shL + 14], [c.cx - 96, c.shL + 116], [c.cx - 40, c.shL + 168]],
        R: [[c.cx + c.sw * 0.9, c.shR + 12], [c.cx + 100, c.shR + 118], [c.cx + 44, c.shR + 170]],
      }),
      prop: c => ({ d: "M" + (c.cx - 46) + "," + (c.shL + 150) + "h92v74h-92z", role: "paper", front: true }) },
    "pointing-down-at-desk": { label: "pointing down at desk", origin: "drawn kit", fits: "desk-front · desk-side", face: "lamp",
      note: "Arm out and down to the surface. Carries every \"this number here\" beat without a graphic.",
      arms: c => ({ R: [[c.cx + c.sw * 0.9, c.shR + 12], [c.cx + 126, c.shR + 104], [c.cx + 176, c.shR + 196]] }) },
    "head-in-hands": { label: "head in hands", origin: "drawn kit", fits: "desk-front · turn-to-screen", face: "lamp",
      note: "Both hands to the face, head dropped. The one pose the deadpan breaks in, so it is used once an episode at most.",
      headRot: -9, headDy: 16,
      arms: c => ({
        L: [[c.cx - c.sw * 0.88, c.shL + 16], [c.cx - 92, c.shL + 96], [c.cx - 34, c.shL - 6]],
        R: [[c.cx + c.sw * 0.88, c.shR + 14], [c.cx + 96, c.shR + 94], [c.cx + 38, c.shR - 8]],
      }) },
    "sitting-at-desk": { label: "sitting at desk", origin: "drawn kit", fits: "desk-front · turn-to-screen",
      note: "Crown drops to the 0.735 seated ratio — 5.14 HU, a seated man, not a shortened one. Highest-priority pose in the brief. The chair is a prop path: without it a seated figure reads as a standing one that has sunk.",
      upperDy: 186,
      arms: c => ({
        L: [[c.cx - c.sw * 0.9, c.shL + 14], [c.cx - 90, c.shL + 108], [c.cx - 34, c.shL + 176]],
        R: [[c.cx + c.sw * 0.9, c.shR + 12], [c.cx + 94, c.shR + 108], [c.cx + 58, c.shR + 178]],
      }),
      // The near leg is barely foreshortened and the far one carries most of the
      // run to the desk. The first cut sent both hard to camera-right from the
      // same hip, which put both feet under the far hip and read as a man
      // sliding out of shot rather than sitting in a chair.
      legs: c => ({
        L: [[c.cx - 32, c.hipL - 6], [c.cx + 42, c.hipL - 14], [c.cx + 46, c.floor - 16]],
        R: [[c.cx + 30, c.hipR - 6], [c.cx + 88, c.hipR - 26], [c.cx + 94, c.floor - 16]],
      }),
      // The chair reads from the parts that are NOT behind him: the seat running
      // out past the near hip, the post, the base, and the back's camera-left
      // edge. A back panel sized like a real chair back sits entirely behind the
      // torso and paints nothing.
      prop: c => ({ role: "prop", d:
        "M" + (c.cx - 100) + "," + (c.hipL + 18) + "h150v17h-150z" +
        " M" + (c.cx - 34) + "," + (c.hipL + 35) + "h17v62h-17z" +
        " M" + (c.cx - 76) + "," + (c.hipL + 97) + "h102v13h-102z" +
        " M" + (c.cx - 104) + "," + (c.shL + 66) + "h27v134h-27z" }) },
    "turn-to-screen": { label: "turn to screen", origin: "new", fits: "turn-to-screen · desk-side",
      note: "Shoulder line narrowed to 0.66 and the head off-axis. The viewer is behind the decision, not behind his head.",
      swScale: 0.66, headDx: 24, headRot: 1.5, keySide: "right",
      arms: c => ({
        L: [[c.cx - c.sw * 0.9, c.shL + 16], [c.cx - 62, c.shL + 120], [c.cx - 52, c.shL + 224]],
        R: [[c.cx + c.sw * 0.9, c.shR + 12], [c.cx + 78, c.shR + 114], [c.cx + 116, c.shR + 176]],
      }),
      legs: c => ({
        L: [[c.cx - 22, c.hipL - 8], [c.cx - 26, c.knee], [c.cx - 28, c.floor - 16]],
        R: [[c.cx + 26, c.hipR - 8], [c.cx + 36, c.knee], [c.cx + 42, c.floor - 16]],
      }) },
    "walking-out-of-frame": { label: "walking out of frame", origin: "drawn kit", fits: "doorway · desk-wide", face: "lamp",
      note: "The only pose where the feet separate, so it is the only one whose floor line needs a stated convention — the contact foot.",
      headDx: -16, headRot: 2,
      arms: c => ({
        L: [[c.cx - c.sw * 0.9, c.shL + 14], [c.cx - 84, c.shL + 118], [c.cx - 54, c.shL + 226]],
        R: [[c.cx + c.sw * 0.9, c.shR + 12], [c.cx + 110, c.shR + 122], [c.cx + 124, c.shR + 234]],
      }),
      legs: c => ({
        L: [[c.cx - 34, c.hipL - 8], [c.cx - 72, c.knee], [c.cx - 94, c.floor - 16]],
        R: [[c.cx + 32, c.hipR - 8], [c.cx + 58, c.knee - 12], [c.cx + 80, c.floor - 16]],
      }) },
    "arms-crossed": { label: "arms crossed", origin: "new", fits: "board · desk-wide",
      note: "Waiting. Reads as a man who has already worked out what the number means and is letting you catch up.",
      arms: c => ({
        L: [[c.cx - c.sw * 0.9, c.shL + 14], [c.cx - 102, c.shL + 122], [c.cx + 34, c.shL + 148]],
        R: [[c.cx + c.sw * 0.9, c.shR + 12], [c.cx + 102, c.shR + 112], [c.cx - 40, c.shR + 170]],
      }) },

    /* ── rebuild-14: two poses restoring roles the twelve-to-ten cut emptied ──
     *
     * Both are joint positions, not drawings — the rig solves the limb from
     * three points and the shape list is unchanged. That is what makes a pose
     * cheap and a framing free.
     */
    "considering": { label: "considering", origin: "new", fits: "read-close · desk-front-b · desk-wide",
      note: "NEW — the BEAT pose. Weight settled, one hand resting on the desk edge, the other loose. The role lost empty-chair and every chapter opener needs a shot that is not yet making a point: this is him between two sentences, not mid-argument.",
      arms: c => ({
        L: [[c.cx - c.sw * 0.9, c.shL + 16], [c.cx - 96, c.shL + 124], [c.cx - 78, c.shL + 236]],
        R: [[c.cx + c.sw * 0.9, c.shR + 14], [c.cx + 104, c.shR + 116], [c.cx + 62, c.shR + 226]],
      }),
      legs: c => ({ R: [[c.cx + 34, c.hipR - 6], [c.cx + 46, c.knee], [c.cx + 40, c.floor - 14]] }) },

    "checking-a-figure": { label: "checking a figure", origin: "new", fits: "panel-left · board-side · desk-front-low",
      note: "NEW — the EYELINE pose. Head turned toward the graphic side with the near arm raised to indicate, so his attention and the plate agree. This is what the glance keys used to provide before they were folded into one turn-to-screen; without it a figure beside him is a figure he is ignoring.",
      headTurn: 9,
      arms: c => ({
        L: [[c.cx - c.sw * 0.9, c.shL + 14], [c.cx - 118, c.shL + 86], [c.cx - 156, c.shL + 52]],
        R: [[c.cx + c.sw * 0.9, c.shR + 12], [c.cx + 96, c.shR + 122], [c.cx + 74, c.shR + 230]],
      }),
      legs: c => ({ L: [[c.cx - 34, c.hipL - 6], [c.cx - 48, c.knee], [c.cx - 58, c.floor - 14]] }) },
  };

  // EIGHT ANGLES. Five signed off in v1 plus three the five could not cover:
  // window-wall makes the hour itself legible, doorway is the entrance the
  // walking pose needs, desk-top-down is a detail cut-away with no figure.
  static rooms() {
    const R = KitModel.rect, Y = KitModel.poly;
    const s = (d, role, tone) => ({ d, role, tone });
    const ink = (d, role) => ({ d, role, ink: true });
    /* BEHIND HIM, written down (§4.5, rebuild-21). The split used to be derived
     * as "the first desk shape", so anything authored after the desk painted in
     * front of him — four rooms listed wall items after it and hung a shelf or
     * a frame across his head. Every shape now carries an explicit layer: the
     * desk and everything after it defaults to front, and b(...) marks a shape
     * that sits behind him wherever it was authored. rooms() then orders each
     * room behind-then-front and the split is the first front shape. */
    const b = (...xs) => xs.map(x => Object.assign(x, { back: true }));
    return KitModel.layered([
      { id: "desk-front", isNew: false, anchor: [178, 30, 110, 116], why: "The talk shot. Square to the wall, and most of every video.", shapes: [
        s(R(0, 0, 320, 146), "wall"), s(R(230, 0, 90, 146), "wall", "shade"),
        s(R(22, 16, 84, 54), "prop", "shade"), s(R(29, 23, 22, 15), "paper"), s(R(55, 23, 22, 15), "paper"),
        s(R(29, 42, 22, 15), "prop"), s(R(55, 42, 44, 15), "paper"),
        s(Y([[126, 74], [194, 74], [216, 138], [104, 138]]), "glow", "shade"),
        s(R(0, 138, 320, 8), "prop", "shade"), s(R(0, 146, 320, 34), "floor"), s(R(230, 146, 90, 34), "floor", "shade"),
        s(R(148, 100, 44, 20), "prop", "shade"),
        s(R(36, 118, 248, 10), "desk"), s(R(36, 128, 248, 14), "desk", "shade"),
        s(R(44, 142, 8, 28), "prop", "shade"), s(R(268, 142, 8, 28), "prop", "shade"),
        s(Y([[122, 118], [198, 118], [232, 128], [88, 128]]), "glow"),
        s(R(126, 70, 68, 46), "prop", "shade"), s(R(130, 74, 60, 38), "screen"), s(R(156, 116, 8, 4), "prop", "shade"),
        s(R(124, 112, 72, 6), "prop"), s(R(158, 128, 3, 14), "prop", "shade"),
        s(R(64, 94, 4, 24), "prop", "shade"), s(Y([[52, 82], [80, 82], [74, 94], [58, 94]]), "lamp"),
        s(Y([[46, 112], [86, 112], [100, 128], [32, 128]]), "lamp", "shade"),
        s(R(120, 106, 13, 12), "prop"), s(R(133, 109, 4, 6), "prop", "shade"),
        s(R(234, 112, 34, 6), "paper"), s(R(238, 108, 26, 4), "paper", "shade"),
        s(R(98, 96, 17, 22), "prop"), s(R(98, 92, 17, 5), "prop", "shade"),
        s(R(296, 100, 11, 18), "paper", "shade"), s(R(294, 96, 15, 5), "prop"),
        s(R(84, 108, 30, 12), "prop", "shade"), s(R(88, 104, 22, 5), "paper"),
        s(R(292, 118, 22, 24), "prop", "shade"), s(R(294, 114, 18, 5), "paper"),
        ...b(s(R(112, 22, 30, 42), "paper"), s(R(114, 26, 26, 5), "prop")),
        ...b(s(R(238, 8, 40, 26), "prop", "shade"), s(R(242, 12, 32, 5), "paper"), s(R(242, 20, 32, 5), "paper")),
        s(R(198, 126, 46, 3), "prop", "shade"),
        s(Y([[194, 116], [214, 116], [238, 128], [196, 128]]), "desk", "shade"),
        s(Y([[223, 116], [240, 116], [248, 128], [225, 128]]), "desk", "shade"),
        s(Y([[36, 142], [284, 142], [300, 162], [20, 162]]), "floor", "shade"),
        s(Y([[0, 180], [0, 118], [56, 132], [64, 180]]), "prop", "shade"),
      ] },
      { id: "desk-wide", isNew: false, anchor: [212, 56, 80, 78], opener: true,
        /* rebuild-21: THE TITLE SLOT. Every long chapter opens with its title set here,
         * and no rebuilt room published one, so every chapter title had nowhere to
         * land. The card is drawn into the room (the card ground, §5.3) top-right,
         * inside the portrait window, above his head: the window moved to the left
         * wall to make room, and he stands 10% further back so two lines fit over
         * him in 16:9. `slot` and `ground` are room units; emit.js publishes both
         * aspects in canvas units. */
        title: { slot: [210, 14, 84, 36], ground: [206, 11, 92, 42] },
        why: "The scene change and the chapter opener. Carries the title ground.", shapes: [
        s(R(0, 0, 320, 132), "wall"), s(R(0, 0, 72, 132), "wallSide"),
        s(R(286, 36, 26, 96), "wallSide", "shade"),
        s(R(20, 26, 96, 62), "prop", "shade"), s(R(25, 31, 86, 52), "glow"),
        s(R(25, 31, 86, 5), "prop", "shade"), s(R(25, 49, 86, 4), "prop", "shade"), s(R(25, 66, 86, 4), "prop", "shade"),
        s(R(0, 124, 320, 8), "prop", "shade"), s(R(0, 132, 320, 48), "floor"), s(R(0, 132, 72, 48), "floor", "shade"),
        s(Y([[25, 132], [111, 132], [130, 180], [0, 180], [0, 172]]), "glow", "shade"),
        s(R(96, 104, 112, 10), "desk"), s(R(96, 114, 112, 12), "desk", "shade"),
        s(R(100, 126, 7, 16), "prop", "shade"), s(R(197, 126, 7, 16), "prop", "shade"),
        s(R(140, 84, 40, 22), "prop", "shade"), s(R(143, 87, 34, 16), "screen"),
        s(R(112, 88, 4, 16), "prop", "shade"), s(Y([[104, 78], [126, 78], [121, 88], [109, 88]]), "lamp"),
        ...b(s(R(246, 96, 16, 36), "prop"), s(R(238, 86, 32, 12), "prop", "shade")),
        ...b(ink(R(206, 11, 92, 42), "ground"), ink(R(210, 50, 36, 2), "rule")),
        s(R(178, 96, 24, 18), "prop"), s(R(178, 92, 24, 5), "prop", "shade"),
        s(R(84, 96, 13, 18), "paper"), s(R(120, 100, 20, 6), "prop", "shade"),
        s(R(16, 96, 44, 36), "prop", "shade"), s(R(20, 100, 36, 6), "paper"), s(R(20, 110, 36, 6), "paper"), s(R(20, 120, 36, 6), "paper"),
        s(R(276, 140, 26, 32), "prop", "shade"), s(R(272, 136, 34, 6), "paper"),
        s(R(150, 150, 34, 8), "prop", "shade"), s(R(206, 158, 22, 10), "paper"),
        ...b(s(R(156, 30, 22, 28), "paper")),
        s(Y([[96, 126], [208, 126], [226, 148], [78, 148]]), "floor", "shade"),
        s(Y([[178, 112], [202, 112], [212, 122], [180, 122]]), "desk", "shade"),
        s(Y([[0, 180], [0, 134], [48, 148], [56, 180]]), "prop", "shade"),
      ] },
      { id: "desk-side", isNew: false, anchor: [228, 50, 80, 94], why: "A shallow angle for a second cut inside one chapter, so a forty-minute chapter is not one take.", shapes: [
        s(R(0, 0, 320, 144), "wall"), s(R(232, 0, 88, 144), "wallSide"), s(R(0, 18, 40, 118), "wallSide", "shade"),
        s(R(246, 26, 58, 46), "prop", "shade"), s(R(252, 32, 46, 11), "paper"), s(R(252, 47, 46, 11), "paper"),
        s(R(0, 136, 232, 8), "prop", "shade"), s(R(0, 144, 320, 36), "floor"), s(R(232, 144, 88, 36), "floor", "shade"),
        s(Y([[80, 104], [214, 96], [230, 140], [54, 148]]), "glow", "shade"),
        s(Y([[30, 112], [214, 104], [214, 118], [30, 128]]), "desk"),
        s(Y([[30, 128], [214, 118], [214, 128], [30, 140]]), "desk", "shade"),
        s(R(38, 138, 8, 28), "prop", "shade"), s(R(198, 128, 8, 28), "prop", "shade"),
        s(Y([[146, 66], [202, 60], [202, 106], [146, 108]]), "prop", "shade"),
        s(Y([[150, 70], [198, 65], [198, 102], [150, 104]]), "screen"),
        s(R(66, 88, 4, 24), "prop", "shade"), s(Y([[56, 76], [82, 76], [76, 88], [62, 88]]), "lamp"),
        s(R(104, 100, 14, 13), "prop"), s(R(122, 106, 44, 6), "paper"), s(R(126, 102, 34, 4), "paper", "shade"),
        s(R(86, 94, 15, 20), "prop"), s(R(86, 90, 15, 5), "prop", "shade"),
        s(R(172, 96, 26, 14), "prop", "shade"), s(R(174, 92, 22, 5), "paper"),
        ...b(s(R(246, 82, 58, 34), "prop", "shade"), s(R(252, 88, 46, 6), "paper"), s(R(252, 100, 46, 6), "paper")),
        s(R(34, 152, 30, 26), "prop", "shade"), s(R(30, 148, 38, 6), "paper"),
        ...b(s(R(60, 22, 44, 52), "paper"), s(R(64, 28, 36, 6), "prop"), s(R(64, 40, 36, 4), "prop", "shade")),
        ...b(s(R(120, 20, 18, 26), "prop", "shade")),
        s(Y([[30, 140], [214, 128], [230, 154], [14, 166]]), "floor", "shade"),
        s(Y([[118, 110], [140, 109], [150, 120], [120, 121]]), "desk", "shade"),
        s(Y([[320, 180], [320, 114], [266, 132], [258, 180]]), "prop", "shade"),
      ] },
      { id: "turn-to-screen", isNew: false, anchor: [28, 42, 92, 98], why: "He reads something off the monitor; the viewer is behind the decision. Replaces over-the-shoulder.", shapes: [
        s(R(0, 0, 320, 150), "wall"), s(R(0, 0, 96, 150), "wall", "shade"),
        s(R(240, 14, 66, 28), "prop", "shade"),
        s(R(0, 142, 320, 8), "prop", "shade"), s(R(0, 150, 320, 30), "floor"),
        s(R(96, 38, 124, 84), "prop", "shade"), s(R(102, 44, 112, 72), "screen"),
        s(R(108, 50, 60, 6), "glow", "shade"), s(R(108, 62, 90, 5), "glow", "shade"), s(R(108, 74, 48, 5), "glow", "shade"),
        s(R(16, 114, 288, 12), "desk"), s(R(16, 126, 288, 12), "desk", "shade"),
        s(R(24, 138, 9, 32), "prop", "shade"), s(R(288, 138, 9, 32), "prop", "shade"),
        s(Y([[100, 114], [216, 114], [262, 126], [54, 126]]), "glow"),
        s(R(120, 106, 76, 8), "prop"), s(R(226, 104, 34, 6), "paper"),
        s(R(266, 92, 4, 22), "prop", "shade"), s(Y([[256, 80], [284, 80], [278, 92], [262, 92]]), "lamp"),
        s(R(34, 96, 19, 24), "prop"), s(R(34, 92, 19, 5), "prop", "shade"),
        s(R(196, 104, 26, 10), "prop", "shade"), s(R(200, 100, 18, 5), "paper"),
        ...b(s(R(224, 38, 18, 24), "paper"), s(R(224, 66, 18, 24), "paper"), s(R(246, 46, 18, 24), "prop")),
        ...b(s(R(14, 40, 62, 40), "prop", "shade"), s(R(20, 46, 50, 6), "paper"), s(R(20, 58, 50, 6), "paper"), s(R(20, 70, 50, 5), "prop")),
        s(R(276, 122, 34, 4), "prop", "shade"),
        s(Y([[16, 138], [304, 138], [316, 158], [4, 158]]), "floor", "shade"),
        s(Y([[216, 112], [242, 112], [252, 126], [218, 126]]), "desk", "shade"),
        s(Y([[320, 180], [320, 106], [264, 122], [258, 180]]), "prop", "shade"),
      ] },
      { id: "board", isNew: false, anchor: null, why: "The wall of index cards. Full-frame data plate, no host anchor — cut to it over his voice.", shapes: [
        s(R(0, 0, 320, 160), "wall"), s(R(0, 152, 320, 8), "prop", "shade"), s(R(0, 160, 320, 20), "floor"),
        ink(R(24, 14, 272, 130), "ground"), s(R(24, 14, 272, 5), "prop", "shade"),
        s(R(38, 28, 54, 32), "paper"), s(R(100, 28, 54, 32), "paper"), s(R(162, 28, 54, 32), "prop"), s(R(224, 28, 54, 32), "paper"),
        ink(R(64, 60, 2, 16), "rule"), ink(R(126, 60, 2, 16), "rule"), ink(R(188, 60, 2, 16), "rule"), ink(R(250, 60, 2, 16), "rule"),
        ink(R(38, 78, 240, 2), "rule"),
        s(R(38, 96, 54, 32), "prop"), s(R(100, 96, 54, 32), "paper"), s(R(162, 96, 116, 32), "paper"),
        s(R(262, 146, 46, 14), "prop", "shade"),
        s(R(20, 148, 30, 14), "prop"), s(R(56, 150, 22, 12), "prop", "shade"),
        s(R(96, 152, 40, 10), "paper"), s(R(146, 150, 26, 12), "prop"),
        ink(R(38, 136, 240, 2), "rule"),
        s(R(186, 148, 30, 14), "paper", "shade"),
        s(Y([[296, 14], [307, 24], [307, 154], [296, 144]]), "wall", "shade"),
        s(Y([[24, 144], [296, 144], [306, 160], [14, 160]]), "floor", "shade"),
        s(Y([[0, 180], [0, 124], [42, 140], [50, 180]]), "prop", "shade"),
      ] },
      { id: "window-wall", isNew: true, anchor: [44, 44, 86, 94], why: "NEW — the hour itself, on screen. The one angle where the key source is in frame, so dusk reads as dusk and night as three in the morning.", shapes: [
        s(R(0, 0, 320, 142), "wall"), s(R(0, 0, 118, 142), "wall", "shade"), s(R(0, 28, 32, 82), "wallSide", "shade"),
        s(R(150, 18, 140, 96), "prop", "shade"), s(R(156, 24, 128, 84), "glow"),
        s(R(216, 24, 5, 84), "prop", "shade"), s(R(156, 62, 128, 5), "prop", "shade"),
        s(R(0, 134, 320, 8), "prop", "shade"), s(R(0, 142, 320, 38), "floor"),
        s(Y([[156, 142], [284, 142], [320, 180], [122, 180]]), "glow", "shade"),
        s(R(36, 104, 96, 10), "desk"), s(R(36, 114, 96, 12), "desk", "shade"), s(R(42, 126, 8, 18), "prop", "shade"),
        s(R(100, 82, 32, 22), "prop", "shade"), s(R(103, 85, 26, 16), "screen"),
        s(R(102, 100, 12, 12), "prop"),
        s(R(288, 96, 20, 46), "prop"), s(R(280, 82, 36, 16), "prop", "shade"),
        s(R(120, 96, 16, 20), "prop"), s(R(120, 92, 16, 5), "prop", "shade"),
        ...b(s(R(14, 40, 50, 36), "prop", "shade"), s(R(18, 44, 42, 6), "paper"), s(R(18, 54, 42, 6), "paper"), s(R(18, 64, 42, 5), "prop")),
        s(R(36, 148, 34, 26), "prop", "shade"), s(R(32, 144, 42, 6), "paper"),
        s(R(40, 96, 18, 8), "paper"), s(R(200, 150, 44, 10), "prop", "shade"),
        s(R(30, 90, 22, 14), "prop", "shade"),
        s(Y([[36, 126], [132, 126], [146, 152], [20, 152]]), "floor", "shade"),
        s(Y([[94, 110], [118, 110], [126, 122], [96, 122]]), "desk", "shade"),
        s(Y([[320, 180], [320, 110], [270, 126], [264, 180]]), "prop", "shade"),
      ] },
      { id: "doorway", isNew: true, anchor: [192, 38, 88, 100], why: "NEW — the entrance. walking-out-of-frame had nowhere to walk to, and a chapter that opens on an empty room needs a way in.", shapes: [
        s(R(0, 0, 320, 138), "wall"), s(R(0, 36, 32, 102), "wallSide", "shade"),
        s(R(54, 14, 94, 124), "prop", "shade"), s(R(60, 20, 82, 118), "wall", "shade"),
        s(R(130, 68, 7, 11), "prop"),
        s(R(0, 130, 320, 8), "prop", "shade"), s(R(0, 138, 320, 42), "floor"),
        s(Y([[60, 138], [142, 138], [170, 180], [28, 180]]), "glow", "shade"),
        s(R(188, 38, 112, 74), "prop", "shade"), s(R(194, 44, 100, 27), "paper"), s(R(194, 76, 100, 29), "prop"),
        s(R(166, 112, 142, 10), "desk"), s(R(166, 122, 142, 12), "desk", "shade"), s(R(174, 134, 8, 22), "prop", "shade"),
        s(R(262, 88, 36, 24), "prop", "shade"), s(R(265, 91, 30, 18), "screen"),
        s(R(194, 106, 26, 6), "paper"),
        s(R(276, 100, 16, 20), "prop"), s(R(276, 96, 16, 5), "prop", "shade"),
        ...b(s(R(24, 92, 26, 46), "prop", "shade"), s(R(26, 96, 22, 6), "paper"), s(R(26, 106, 22, 6), "paper")),
        s(R(58, 146, 34, 26), "prop", "shade"), s(R(54, 142, 42, 6), "paper"),
        ...b(s(R(150, 26, 26, 34), "paper"), s(R(154, 32, 18, 5), "prop")),
        s(R(110, 150, 46, 10), "prop", "shade"), s(R(248, 132, 40, 6), "paper"),
        s(Y([[148, 14], [159, 24], [159, 140], [148, 132]]), "wall", "shade"),
        s(Y([[166, 134], [308, 134], [320, 156], [152, 156]]), "floor", "shade"),
        s(Y([[0, 180], [0, 122], [46, 138], [54, 180]]), "prop", "shade"),
      ] },
      { id: "desk-top-down", isNew: true, anchor: null, why: "NEW — straight down at the surface. The detail cut-away: the page, the keyboard, the mug. No figure, so it cuts under any voice line.", shapes: [
        s(R(0, 0, 320, 180), "desk"), s(R(0, 0, 320, 50), "desk", "shade"), s(R(0, 0, 320, 10), "wall", "shade"),
        s(Y([[86, 50], [232, 50], [258, 150], [64, 150]]), "lamp", "shade"),
        s(R(96, 56, 128, 88), "paper"),
        ink(R(106, 68, 108, 4), "rule"), ink(R(106, 80, 88, 4), "rule"), ink(R(106, 92, 108, 4), "rule"), ink(R(106, 104, 64, 4), "rule"),
        s(R(234, 50, 62, 96), "paper", "shade"),
        s(R(20, 58, 58, 82), "prop", "shade"),
        s(R(26, 64, 46, 6), "prop"), s(R(26, 76, 46, 6), "prop"), s(R(26, 88, 46, 6), "prop"), s(R(26, 100, 46, 6), "prop"),
        s(R(34, 148, 28, 26), "prop"), s(R(62, 154, 8, 12), "prop", "shade"),
        s(R(140, 152, 54, 7), "prop", "shade"), s(R(248, 16, 46, 26), "lamp"),
        s(R(232, 152, 34, 22), "prop"), s(R(230, 148, 38, 5), "prop", "shade"),
        s(R(86, 152, 40, 20), "prop", "shade"), s(R(90, 156, 32, 5), "paper"),
        s(R(276, 60, 30, 44), "paper"), ink(R(282, 70, 18, 3), "rule"), ink(R(282, 80, 18, 3), "rule"),
        s(R(12, 18, 44, 26), "prop", "shade"), s(R(16, 22, 36, 5), "paper"),
        s(R(196, 150, 22, 22), "prop"),
        s(Y([[224, 56], [236, 58], [238, 148], [224, 146]]), "desk", "shade"),
        s(Y([[78, 58], [96, 56], [96, 146], [72, 146]]), "desk", "shade"),
        s(Y([[0, 146], [46, 170], [34, 180], [0, 166]]), "prop", "shade"),
      ] },

      /* ── rebuild-13: six angles restoring ROTATION, not extending coverage ──
       *
       * The rebuild cut twelve angles to eight and four of the cut ones were
       * the only other member of their role. A room is picked by code that
       * rotates against what recent videos used, so a role with one member
       * repeats in every video; per drawing these buy more than any content
       * plate in the library.
       *
       * `duskSafe` is declared per angle. The relight was scoped out, so cast
       * shadows still fall where the daylight lamp puts them. That reads on a
       * tight angle, where the lamp is the key and the cast falls inside the
       * frame, and does not on a wide one, where a long cast crosses a wall
       * that dusk lights from the other side. Wide angles are marked false
       * and should be used at night until the relight lands.
       */
      { id: "desk-front-b", isNew: true, anchor: [228, 32, 104, 112], duskSafe: true,
        role: "talk", why: "NEW — the second TALK angle. Same desk, camera stepped left and in, so the monitor sits off his shoulder rather than behind his head. talk is the only room any short ever uses and it had one member; this is the single highest-value drawing in the round.", shapes: [
        s(R(0, 0, 320, 148), "wall"), s(R(0, 0, 58, 148), "wallSide", "shade"), s(R(262, 0, 58, 148), "wall", "shade"),
        s(R(206, 14, 92, 58), "prop", "shade"), s(R(212, 20, 38, 16), "paper"), s(R(254, 20, 38, 16), "paper"),
        s(R(212, 42, 38, 16), "prop"), s(R(254, 42, 38, 16), "paper"),
        s(Y([[112, 76], [186, 76], [212, 140], [88, 140]]), "glow", "shade"),
        s(R(0, 140, 320, 8), "prop", "shade"), s(R(0, 148, 320, 32), "floor"), s(R(0, 148, 58, 32), "floor", "shade"),
        s(R(26, 120, 260, 10), "desk"), s(R(26, 130, 260, 14), "desk", "shade"),
        s(R(34, 144, 8, 28), "prop", "shade"), s(R(270, 144, 8, 28), "prop", "shade"),
        s(Y([[108, 120], [190, 120], [224, 130], [74, 130]]), "glow"),
        s(R(196, 72, 64, 44), "prop", "shade"), s(R(200, 76, 56, 36), "screen"), s(R(224, 116, 8, 4), "prop", "shade"),
        s(R(194, 112, 68, 6), "prop"),
        s(R(52, 96, 4, 24), "prop", "shade"), s(Y([[40, 84], [68, 84], [62, 96], [46, 96]]), "lamp"),
        s(Y([[34, 114], [74, 114], [88, 130], [20, 130]]), "lamp", "shade"),
        s(R(96, 108, 14, 12), "prop"), s(R(110, 111, 4, 6), "prop", "shade"),
        s(R(128, 114, 36, 6), "paper"), s(R(132, 110, 28, 4), "paper", "shade"),
        s(R(72, 98, 17, 22), "prop"), s(R(72, 94, 17, 5), "prop", "shade"),
        s(R(168, 106, 22, 14), "prop", "shade"), s(R(170, 102, 18, 5), "paper"),
        ...b(s(R(286, 104, 26, 38), "prop", "shade"), s(R(284, 100, 30, 5), "paper")),
        ...b(s(R(86, 24, 32, 44), "paper"), s(R(88, 28, 28, 5), "prop")),
        ...b(s(R(128, 30, 26, 34), "prop", "shade"), s(R(131, 34, 20, 4), "paper")),
        s(Y([[26, 144], [286, 144], [302, 164], [10, 164]]), "floor", "shade"),
        s(Y([[190, 118], [214, 118], [226, 130], [192, 130]]), "desk", "shade"),
        s(Y([[0, 180], [0, 120], [52, 134], [60, 180]]), "prop", "shade"),
      ] },

      { id: "desk-front-low", isNew: true, anchor: [236, 44, 96, 104], duskSafe: true,
        role: "talk", why: "NEW — the third TALK angle. Camera dropped to desk height so the surface reads as a foreground plane and he sits above it. Use it for the beat where the paperwork matters as much as he does.", shapes: [
        s(R(0, 0, 320, 120), "wall"), s(R(244, 0, 76, 120), "wall", "shade"), s(R(0, 0, 44, 120), "wallSide", "shade"),
        s(R(60, 10, 104, 44), "prop", "shade"), s(R(66, 16, 44, 14), "paper"), s(R(114, 16, 44, 14), "paper"),
        s(R(66, 34, 92, 14), "paper"),
        s(Y([[118, 58], [196, 58], [226, 112], [92, 112]]), "glow", "shade"),
        s(R(0, 112, 320, 8), "prop", "shade"), s(R(0, 120, 320, 60), "floor"), s(R(0, 120, 44, 60), "floor", "shade"),
        s(R(0, 128, 320, 18), "desk"), s(R(0, 146, 320, 34), "desk", "shade"),
        s(Y([[60, 128], [250, 128], [286, 146], [26, 146]]), "glow"),
        s(R(188, 74, 68, 46), "prop", "shade"), s(R(192, 78, 60, 38), "screen"),
        s(R(62, 88, 4, 30), "prop", "shade"), s(Y([[48, 74], [80, 74], [73, 88], [55, 88]]), "lamp"),
        s(R(30, 132, 78, 26), "paper"), ink(R(40, 140, 58, 3), "rule"), ink(R(40, 148, 40, 3), "rule"),
        s(R(122, 136, 60, 20), "prop", "shade"), s(R(126, 140, 52, 5), "paper"),
        s(R(214, 130, 28, 26), "prop"), s(R(212, 126, 32, 5), "prop", "shade"),
        s(R(258, 136, 44, 30), "paper"), ink(R(266, 144, 28, 3), "rule"),
        s(R(96, 100, 16, 20), "prop"), s(R(96, 96, 16, 5), "prop", "shade"),
        ...b(s(R(276, 96, 22, 24), "prop", "shade"), s(R(274, 92, 26, 5), "paper")),
        s(R(164, 98, 20, 22), "paper"), s(R(166, 102, 16, 4), "prop"),
        ...b(s(R(12, 96, 30, 24), "prop", "shade"), s(R(14, 100, 26, 5), "paper")),
        s(Y([[0, 180], [0, 150], [44, 160], [50, 180]]), "prop", "shade"),
        s(Y([[286, 146], [320, 152], [320, 180], [274, 180]]), "prop", "shade"),
      ] },

      { id: "read-close", isNew: true, anchor: [188, 40, 92, 100], duskSafe: true,
        role: "read", why: "NEW — the second READ angle. Tighter than desk-side, page raised into the light, monitor out of frame. read carries the opening and closing shot of ten of the sixteen chapters and its two members had folded onto one angle.", shapes: [
        s(R(0, 0, 320, 150), "wall"), s(R(0, 0, 66, 150), "wallSide", "shade"), s(R(276, 0, 44, 150), "wall", "shade"),
        s(R(84, 12, 108, 52), "prop", "shade"), s(R(90, 18, 46, 14), "paper"), s(R(140, 18, 46, 14), "paper"),
        s(R(90, 36, 96, 14), "paper"),
        s(Y([[96, 86], [188, 86], [210, 142], [76, 142]]), "lamp", "shade"),
        s(R(0, 142, 320, 8), "prop", "shade"), s(R(0, 150, 320, 30), "floor"), s(R(0, 150, 66, 30), "floor", "shade"),
        s(R(20, 122, 272, 10), "desk"), s(R(20, 132, 272, 14), "desk", "shade"),
        s(R(28, 146, 8, 26), "prop", "shade"), s(R(276, 146, 8, 26), "prop", "shade"),
        s(R(118, 92, 84, 32), "paper"), ink(R(128, 100, 64, 3), "rule"), ink(R(128, 108, 64, 3), "rule"), ink(R(128, 116, 40, 3), "rule"),
        s(R(52, 92, 4, 30), "prop", "shade"), s(Y([[38, 78], [72, 78], [64, 92], [46, 92]]), "lamp"),
        s(Y([[30, 116], [78, 116], [92, 132], [16, 132]]), "lamp", "shade"),
        s(R(250, 104, 40, 18), "prop", "shade"), s(R(254, 100, 32, 5), "paper"),
        s(R(84, 104, 18, 18), "prop"), s(R(84, 100, 18, 5), "prop", "shade"),
        s(R(262, 110, 30, 12), "paper"), s(R(266, 106, 22, 4), "paper", "shade"),
        ...b(s(R(232, 18, 34, 46), "paper"), s(R(234, 22, 30, 5), "prop")),
        s(R(292, 96, 22, 26), "prop", "shade"), s(R(290, 92, 26, 5), "paper"),
        s(Y([[20, 146], [292, 146], [306, 166], [6, 166]]), "floor", "shade"),
        s(Y([[0, 180], [0, 126], [48, 138], [56, 180]]), "prop", "shade"),
      ] },

      { id: "board-side", isNew: true, anchor: [42, 44, 92, 100], duskSafe: false,
        role: "diagram", why: "NEW — the second DIAGRAM angle, from the left so the wall runs away to the right and he stands at the near edge. One member served three chapter types. NOT dusk-safe: the wall cast still falls from the daylight lamp across the open right half.", shapes: [
        s(R(0, 0, 320, 152), "wall"), s(R(0, 0, 40, 152), "wallSide", "shade"),
        s(R(120, 0, 200, 152), "wall", "shade"),
        s(R(136, 16, 168, 106), "prop", "shade"),
        s(R(146, 26, 66, 22), "paper"), s(R(220, 26, 66, 22), "paper"),
        s(R(146, 56, 66, 22), "paper"), s(R(220, 56, 66, 22), "paper"),
        s(R(146, 86, 66, 22), "paper"), s(R(220, 86, 66, 22), "paper"),
        ink(R(152, 34, 48, 3), "rule"), ink(R(226, 34, 48, 3), "rule"),
        ink(R(152, 64, 48, 3), "rule"), ink(R(226, 64, 48, 3), "rule"),
        ink(R(152, 94, 48, 3), "rule"), ink(R(226, 94, 34, 3), "rule"),
        s(R(0, 144, 320, 8), "prop", "shade"), s(R(0, 152, 320, 28), "floor"), s(R(0, 152, 40, 28), "floor", "shade"),
        /* rebuild-18: the board's cast is a BAND under it, not a trapezoid to the
         * frame edge. The old shape read as a black hole in the floor. */
        s(Y([[136, 122], [304, 122], [310, 134], [128, 134]]), "wall", "shade"),
        s(R(14, 108, 40, 44), "prop", "shade"), s(R(18, 112, 32, 6), "paper"), s(R(18, 122, 32, 6), "paper"),
        s(R(60, 124, 36, 28), "prop"), s(R(58, 120, 40, 5), "prop", "shade"),
        s(R(8, 22, 26, 34), "paper"), s(R(10, 26, 22, 4), "prop"),
        s(R(104, 132, 22, 20), "prop", "shade"),
        s(Y([[0, 180], [0, 146], [40, 158], [46, 180]]), "prop", "shade"),
      ] },

      { id: "doorway-wide", isNew: true, anchor: [243, 34, 106, 114], duskSafe: false,
        role: "exit", why: "NEW — the second EXIT angle, pulled back so the whole door and the corridor light beyond are in frame. One member closes every long. NOT dusk-safe: the corridor spill is keyed to the night lamp and the wide frame shows the cast crossing the floor.", shapes: [
        s(R(0, 0, 320, 150), "wall"), s(R(0, 0, 96, 150), "wallSide", "shade"),
        s(R(108, 14, 96, 136), "prop", "shade"), s(R(116, 22, 80, 128), "glow"),
        s(R(116, 22, 80, 6), "prop", "shade"),
        s(R(196, 70, 8, 10), "prop"),
        s(Y([[116, 150], [196, 150], [232, 180], [82, 180]]), "glow", "shade"),
        s(R(0, 142, 320, 8), "prop", "shade"), s(R(0, 150, 320, 30), "floor"), s(R(0, 150, 96, 30), "floor", "shade"),
        s(R(216, 96, 96, 10), "desk"), s(R(216, 106, 96, 12), "desk", "shade"),
        s(R(222, 118, 7, 18), "prop", "shade"), s(R(300, 118, 7, 18), "prop", "shade"),
        s(R(244, 74, 36, 24), "prop", "shade"), s(R(247, 77, 30, 18), "screen"),
        s(R(230, 82, 4, 14), "prop", "shade"), s(Y([[222, 72], [244, 72], [239, 82], [227, 82]]), "lamp"),
        ...b(s(R(16, 100, 48, 50), "prop", "shade"), s(R(20, 104, 40, 6), "paper"), s(R(20, 114, 40, 6), "paper"), s(R(20, 124, 40, 6), "paper")),
        ...b(s(R(24, 20, 44, 58), "paper"), s(R(28, 26, 36, 5), "prop"), s(R(28, 38, 36, 4), "prop", "shade")),
        s(R(74, 128, 26, 22), "prop"), s(R(72, 124, 30, 5), "prop", "shade"),
        s(R(286, 130, 28, 34), "prop", "shade"), s(R(284, 126, 32, 6), "paper"),
        s(Y([[216, 118], [312, 118], [320, 140], [204, 140]]), "floor", "shade"),
        s(Y([[0, 180], [0, 152], [40, 162], [46, 180]]), "prop", "shade"),
      ] },

      { id: "panel-left", isNew: true, anchor: [58, 38, 98, 106], duskSafe: true,
        role: "panel", why: "NEW — the PANEL angle with lateral room: he stands left of centre and the right two-thirds of the wall is clear, so a full data plate sits BESIDE him rather than behind his head. The two-shot role lost two of its three members and this is the one that makes a plate legible next to a figure.", shapes: [
        s(R(0, 0, 320, 146), "wall"), s(R(0, 0, 34, 146), "wallSide", "shade"),
        s(R(150, 0, 170, 146), "wall", "shade"),
        /* The clear field. Nothing is drawn inside it: a plate composites here
         * and anything on the wall would read through it. */
        /* rebuild-18: the clear field is WALL, marked only at its corners. It was a
         * dark slab, which read as a switched-off screen and showed wherever a
         * composited plate was smaller than the field or still animating in. */
        ink(R(166, 18, 14, 2), "rule"), ink(R(166, 18, 2, 14), "rule"),
        ink(R(290, 18, 14, 2), "rule"), ink(R(302, 18, 2, 14), "rule"),
        ink(R(166, 120, 14, 2), "rule"), ink(R(166, 108, 2, 14), "rule"),
        ink(R(290, 120, 14, 2), "rule"), ink(R(302, 108, 2, 14), "rule"),
        s(R(0, 138, 320, 8), "prop", "shade"), s(R(0, 146, 320, 34), "floor"), s(R(0, 146, 34, 34), "floor", "shade"),
        s(Y([[44, 100], [148, 100], [166, 142], [26, 142]]), "lamp", "shade"),
        s(R(12, 118, 132, 10), "desk"), s(R(12, 128, 132, 14), "desk", "shade"),
        s(R(20, 142, 8, 26), "prop", "shade"), s(R(128, 142, 8, 26), "prop", "shade"),
        s(R(40, 90, 4, 28), "prop", "shade"), s(Y([[28, 78], [58, 78], [51, 90], [35, 90]]), "lamp"),
        s(R(64, 104, 16, 14), "prop"), s(R(80, 107, 4, 7), "prop", "shade"),
        s(R(124, 110, 20, 8), "paper"), s(R(126, 106, 16, 4), "paper", "shade"),
        ...b(s(R(8, 22, 30, 42), "paper"), s(R(10, 26, 26, 5), "prop")),
        ...b(s(R(48, 26, 76, 34), "prop", "shade"), s(R(54, 32, 30, 8), "paper"), s(R(90, 32, 28, 8), "paper")),
        s(R(150, 128, 24, 18), "prop", "shade"), s(R(152, 124, 20, 5), "paper"),
        s(Y([[12, 142], [144, 142], [158, 162], [0, 162]]), "floor", "shade"),
        s(Y([[0, 180], [0, 124], [44, 136], [50, 180]]), "prop", "shade"),
      ] },

    ]);
  }

  static layered(list) {
    return list.map(r => {
      const deskAt = r.shapes.findIndex(s => s.role === "desk");
      const tagged = r.shapes.map((s, i) => {
        const o = Object.assign({}, s, { front: !s.back && deskAt >= 0 && i >= deskAt });
        delete o.back; return o;
      });
      return Object.assign({}, r, { shapes: tagged.filter(s => !s.front).concat(tagged.filter(s => s.front)) });
    });
  }

  // The fourteen parts. Every one of the five new ones answers a line of
  // host/manifest.json → character that had no shape to carry it.
  geometry(poseName) {
    const P = KitModel.P, G = KitModel.RIG, HU = 100, cx = 200;
    const pose = KitModel.POSES[poseName || "to-camera"] || KitModel.POSES["to-camera"];
    const up = pose.upperDy || 0;
    const crown = 60 + up;
    const y = hu => crown + hu * HU;
    const floor = 60 + P.totalHeight * HU;
    const eyeline = y(P.eyelineFromCrown);
    const shoulder = y(P.shoulderFromCrown);
    const hip = y(P.hipFromCrown);
    const knee = hip + P.legUpperLength * HU;
    const hw = (P.headWidth * HU) / 2;
    const sw = ((P.shoulderWidth * HU) / 2) * (pose.swScale || 1);
    // WHICH SOURCE IS ON HIS FACE, and it is a property of where he is looking
    // rather than a global. The monitor is the cyan key and it is in front of
    // the desk: it only reaches him when he is turned toward it. When he is not
    // — reading a page, head down, walking out — the desk lamp is what lands on
    // him, so the base skin is the amber and the cool becomes the rim. Same two
    // shapes, same two colours, assignment swapped. `keySide` flips which edge
    // the shade band sits on for the one pose that turns to camera-right.
    const kx = pose.keySide === "right" ? -1 : 1;
    const faceSwap = pose.face === "lamp";
    const bandA = kx > 0 ? [-1, -0.3] : [0.3, 1];
    const bandL = kx > 0 ? [-1, -0.34] : [0.34, 1];
    const hcx = cx + (pose.headDx === undefined ? G.headDx : pose.headDx);
    const hcy = crown + (pose.headDy || 0);
    const shL = shoulder + G.shoulderDropL, shR = shoulder + G.shoulderRiseR;
    const hipL = hip + G.hipRaiseL, hipR = hip + G.hipDropR;
    const c = { cx, sw, shL, shR, hipL, hipR, knee, floor, HU, P };

    // ── head, local to (hcx, hcy). The jaw is asymmetric on purpose: mirrored
    // is the thing that stopped him reading as a person.
    const ey = hcy + 52;
    // A SKULL, then a JAW, then a CHIN — and an ear. The first cut was a rounded
    // rectangle with a flat top and a constant width, which is why he read as a
    // blank: a head with no taper below the cheekbone has no face on it, it has
    // a front. The cranium is widest at the temple, the jaw runs in to a chin
    // off the centre line, and camera-left carries the ear because that is the
    // side turned to us.
    const head = "M" + (hcx - 38) + "," + (hcy + 40) +
      " Q" + (hcx - 38) + "," + (hcy + 4) + " " + (hcx - 12) + "," + (hcy - 2) +
      " Q" + (hcx + 16) + "," + (hcy - 6) + " " + (hcx + 33) + "," + (hcy + 16) +
      " Q" + (hcx + 39) + "," + (hcy + 32) + " " + (hcx + 37) + "," + ey +
      " L" + (hcx + 33) + "," + (hcy + 74) +
      " Q" + (hcx + 28) + "," + (hcy + 97) + " " + (hcx + 8) + "," + (hcy + 106) +
      " Q" + (hcx - 6) + "," + (hcy + 110) + " " + (hcx - 19) + "," + (hcy + 98) +
      " Q" + (hcx - 31) + "," + (hcy + 84) + " " + (hcx - 34) + "," + (hcy + 66) +
      " Q" + (hcx - 44) + "," + (hcy + 64) + " " + (hcx - 43) + "," + (hcy + 50) +
      " Q" + (hcx - 42) + "," + (hcy + 44) + " " + (hcx - 37) + "," + (hcy + 44) +
      " L" + (hcx - 38) + "," + (hcy + 40) + " Z";
    // The hollow under the cheekbone and the shadow under the jaw, as ONE shape
    // on the key-away side. Two flat colours, one division, no gradient.
    // A TERMINATOR, NOT A SPLIT. The first cut of this put the edge down the
    // centre line, which is the two-tone mask the whole section is trying to get
    // away from — half a face in lamp amber is a colour scheme, not a light.
    // It sits out at the cheek now, so the shade is a rim plus the shadow the
    // jaw throws on the neck side, and the nose keeps lit skin to read against.
    const headShade = "M" + (hcx + 26 * kx) + "," + (hcy + 10) +
      " Q" + (hcx + 31 * kx) + "," + (hcy + 12) + " " + (hcx + 33 * kx) + "," + (hcy + 16) +
      " Q" + (hcx + 39 * kx) + "," + (hcy + 32) + " " + (hcx + 37 * kx) + "," + ey +
      " L" + (hcx + 33 * kx) + "," + (hcy + 74) +
      " Q" + (hcx + 28 * kx) + "," + (hcy + 97) + " " + (hcx + 8 * kx) + "," + (hcy + 106) +
      " Q" + (hcx - 6 * kx) + "," + (hcy + 110) + " " + (hcx - 19 * kx) + "," + (hcy + 98) +
      " L" + (hcx - 13 * kx) + "," + (hcy + 90) +
      " Q" + (hcx - 2 * kx) + "," + (hcy + 99) + " " + (hcx + 15 * kx) + "," + (hcy + 88) +
      " Q" + (hcx + 30 * kx) + "," + (hcy + 60) + " " + (hcx + 26 * kx) + "," + (hcy + 10) + " Z";
    // Flattened on the slept-on side — camera-left sits lower and flatter than
    // camera-right. A symmetrical cap reads as a helmet and always did.
    const hair = "M" + (hcx - 41) + "," + (hcy + 56) +
      " Q" + (hcx - 44) + "," + (hcy + 10) + " " + (hcx - 14) + "," + (hcy - 6) +
      " Q" + (hcx + 18) + "," + (hcy - 12) + " " + (hcx + 37) + "," + (hcy + 14) +
      " Q" + (hcx + 43) + "," + (hcy + 32) + " " + (hcx + 41) + "," + (hcy + 52) +
      " L" + (hcx + 33) + "," + (hcy + 44) +
      " Q" + (hcx + 33) + "," + (hcy + 22) + " " + (hcx + 12) + "," + (hcy + 26) +
      " Q" + (hcx - 12) + "," + (hcy + 30) + " " + (hcx - 26) + "," + (hcy + 44) +
      " Q" + (hcx - 35) + "," + (hcy + 52) + " " + (hcx - 41) + "," + (hcy + 56) + " Z";
    // A RIM, NOT A SPLIT (rebuild-21) — the face terminator's fix, applied to the
    // hair. The first cut ran the shade from the crown's centre to the temple,
    // half the hair, and at night that half is the lamp's brown against the
    // key's blue-grey: two-tone hair, not one colour lit from one side. The shade
    // is now a crescent on the key-away rim, crown to temple, following the
    // outer contour (control points from subdividing it at t = 0.75), so the
    // hair reads as the lit colour with the second source catching its edge.
    const hairShade = "M" + (hcx + 27 * kx) + "," + (hcy + 3) +
      " Q" + (hcx + 32.25 * kx) + "," + (hcy + 7.5) + " " + (hcx + 37 * kx) + "," + (hcy + 14) +
      " Q" + (hcx + 43 * kx) + "," + (hcy + 32) + " " + (hcx + 41 * kx) + "," + (hcy + 52) +
      " L" + (hcx + 33 * kx) + "," + (hcy + 44) +
      " Q" + (hcx + 34 * kx) + "," + (hcy + 30) + " " + (hcx + 30 * kx) + "," + (hcy + 18) +
      " Q" + (hcx + 29 * kx) + "," + (hcy + 10) + " " + (hcx + 27 * kx) + "," + (hcy + 3) + " Z";
    // Uneven stubble — one flat jaw mass, deliberately faint. Heavy enough to
    // read as bruising makes him look beaten, which the sheet calls over the line.
    // STUBBLE IS GONE, and this is a finding rather than a cut. "Deliberately
    // faint" needs a value a step off the skin, and a 13-role flat palette has
    // no such colour: skin.shade is the lamp, and hair.shade at full opacity
    // over the jaw is a beard, which is what it drew. Faint is only reachable
    // through a partial opacity, and rule 2 bans those — so the fatigue is
    // carried by the under-eye pair and the dropped mouth corner, and the jaw
    // stays clean. A 14th role would buy it back if the operator wants it.
    const browL = this.roundRect(hcx - 26, ey - 16, 18, 4, 2);
    const browR = this.roundRect(hcx + 8, ey - 17, 18, 4, 2);
    // The nose IS its own shadow — a flat shape in the skin's shade colour, no
    // contour. A contoured nose at 9:16 reads as a scribble on the face.
    const nose = "M" + (hcx + 1) + "," + (ey + 7) + " L" + (hcx + 8) + "," + (hcy + 70) +
      " Q" + (hcx + 9) + "," + (hcy + 74) + " " + (hcx + 4) + "," + (hcy + 74) + " L" + (hcx - 2) + "," + (hcy + 73) + " Z";
    const pouchL = this.roundRect(hcx - 25, ey + 8, 18, 3.5, 1.75);
    const pouchR = this.roundRect(hcx + 8, ey + 8, 18, 3.5, 1.75);

    const gw = P.glassesWidth * HU, lh = P.glassesLensHeight * HU, gr = P.glassesRadius * HU;
    const lensW = gw / 2 - 5;
    const glasses = [
      this.roundRect(hcx - gw / 2, ey - lh / 2, lensW, lh, gr),
      this.roundRect(hcx + 5, ey - lh / 2, lensW, lh, gr),
      "M" + (hcx - 5) + "," + (ey - 2) + " L" + (hcx + 5) + "," + (ey - 2),
    ];
    // Half-lidded: the dash sits above centre, so the lens reads mostly empty
    // below it. Level brow, no smile — the deadpan is these two marks.
    const edl = P.eyeDashLength * HU, edw = P.eyeDashWeight * HU;
    const eyes = [
      this.roundRect(hcx - gw / 2 + lensW / 2 - edl / 2, ey - edw / 2 - 2, edl, edw, edw / 2),
      this.roundRect(hcx + 5 + lensW / 2 - edl / 2, ey - edw / 2 - 1, edl, edw, edw / 2),
    ];
    // Flat mouth with ONE CORNER DROPPED, then the two open visemes. Only this
    // shape differs across the talk strip.
    const my = hcy + 87;
    const mouthClosed = "M" + (hcx - 12) + "," + my + " L" + (hcx + 12) + "," + (my + 3) + " L" + (hcx + 12) + "," + (my + 7) + " L" + (hcx - 12) + "," + (my + 4) + " Z";
    const mouthMid = this.roundRect(hcx - 10, my - 1, 21, 8, 3.5);
    const mouthWide = this.roundRect(hcx - 9, my - 3, 19, 15, 6);

    // ── body. The collar is the stretched tee: a wide shallow shape, never a
    // neckline that fits.
    const neckTop = hcy + 80, neckBase = shoulder + 16;
    const neck = this.band([[hcx, neckTop], [cx + G.spineBow, neckBase]], [28, 36], -1, 1);
    const neckShade = this.band([[hcx, neckTop], [cx + G.spineBow, neckBase]], [28, 36], -1, -0.3);

    // A WAIST. The first cut ran straight from shoulder to hip, which is a slab
    // with a head on it — and at 2.05 HU across the shoulders the slab was
    // wider than it was tall. The tee drapes: widest at the shoulder, in at the
    // waist, out again at the hip.
    const torso = "M" + (cx - sw) + "," + (shL + 20) +
      " Q" + (cx - sw * 0.86) + "," + (shL - 1) + " " + (cx - 30) + "," + (shL + 3) +
      " L" + (cx + 30) + "," + (shR + 3) +
      " Q" + (cx + sw * 0.86) + "," + (shR - 1) + " " + (cx + sw) + "," + (shR + 20) +
      " L" + (cx + 74) + "," + (shR + 130) +
      " Q" + (cx + 63) + "," + (hipR - 54) + " " + (cx + 70) + "," + hipR +
      " L" + (cx - 68) + "," + hipL +
      " Q" + (cx - 61) + "," + (hipL - 54) + " " + (cx - 72) + "," + (shL + 130) + " Z";
    const torsoShade = "M" + (cx + 18) + "," + (shR + 16) +
      " Q" + (cx + 52) + "," + (shR + 2) + " " + (cx + sw) + "," + (shR + 20) +
      " L" + (cx + 74) + "," + (shR + 130) +
      " Q" + (cx + 63) + "," + (hipR - 54) + " " + (cx + 70) + "," + hipR +
      " L" + (cx + 22) + "," + hipL +
      " Q" + (cx + 31) + "," + (shR + 140) + " " + (cx + 18) + "," + (shR + 16) + " Z";
    const collar = "M" + (cx - 34) + "," + (shL + 1) +
      " Q" + (cx + 1) + "," + (shL + 38) + " " + (cx + 36) + "," + (shR + 1) +
      " L" + (cx + 29) + "," + (shR - 3) +
      " Q" + (cx + 1) + "," + (shL + 29) + " " + (cx - 28) + "," + (shL - 3) + " Z";

    const restArms = {
      L: [[cx - sw * 0.84, shL + 18], [cx - 86, shL + P.armUpperLength * HU], [cx - 82, shL + (P.armUpperLength + P.armForeLength) * HU]],
      R: [[cx + sw * 0.84, shR + 16], [cx + 88, shR + P.armUpperLength * HU], [cx + 94, shR + (P.armUpperLength + P.armForeLength) * HU]],
    };
    const restLegs = {
      L: [[cx - 34, hipL - 8], [cx - 39, knee], [cx - 41, floor - 16]],
      R: [[cx + 34, hipR - 8], [cx + 46, knee + 4], [cx + 51, floor - 16]],
    };
    const arms = Object.assign({}, restArms, pose.arms ? pose.arms(c) : {});
    const legs = Object.assign({}, restLegs, pose.legs ? pose.legs(c) : {});

    const armW = [34, 29, 24], legW = [64, 48, 38];
    const armL = this.band(arms.L, armW, -1, 1), armR = this.band(arms.R, armW, -1, 1);
    const armLs = this.band(arms.L, armW, bandA[0], bandA[1]), armRs = this.band(arms.R, armW, bandA[0], bandA[1]);
    const legL = this.band(legs.L, legW, -1, 1), legR = this.band(legs.R, legW, -1, 1);
    const legLs = this.band(legs.L, legW, bandL[0], bandL[1]), legRs = this.band(legs.R, legW, bandL[0], bandL[1]);

    const handW = P.handWidth * HU, handH = P.handLength * HU;
    const wL = arms.L[2], wR = arms.R[2];
    const handL = this.roundRect(wL[0] - handW / 2, wL[1] - 16, handW, handH, handW * 0.46);
    const handR = this.roundRect(wR[0] - handW / 2, wR[1] - 16, handW, handH, handW * 0.46);
    const handLs = this.roundRect(wL[0] + handW * 0.12, wL[1] - 16, handW * 0.38, handH, handW * 0.19);
    const handRs = this.roundRect(wR[0] + handW * 0.12, wR[1] - 16, handW * 0.38, handH, handW * 0.19);

    const fw = P.footLength * HU;
    const footL = this.roundRect(legs.L[2][0] - fw * 0.68, floor - 24, fw, 24, 9);
    const footR = this.roundRect(legs.R[2][0] - fw * 0.32, floor - 24, fw, 24, 9);
    const footLs = this.roundRect(legs.L[2][0] - fw * 0.68, floor - 12, fw, 12, 6);
    const footRs = this.roundRect(legs.R[2][0] - fw * 0.32, floor - 12, fw, 12, 6);

    return {
      body: [
        { name: "leg ×2", role: "trouser", d: legL + " " + legR, sd: legLs + " " + legRs, box: "110 420 180 360" },
        { name: "foot ×2", role: "prop", d: footL + " " + footR, sd: footLs + " " + footRs, box: "90 720 220 60" },
        { name: "torso", role: "shirt", d: neck + " " + torso, sd: neckShade + " " + torsoShade, box: "80 170 240 290" },
        { name: "collar", role: "shirt", d: collar, sd: "", box: "140 180 120 60", flatTone: 1 },
        { name: "arm ×2", role: "shirt", d: armL + " " + armR, sd: armLs + " " + armRs, box: "50 180 300 300" },
        { name: "hand ×2", role: "skin", d: handL + " " + handR, sd: handLs + " " + handRs, box: "60 420 280 90" },
      ],
      head: [
        { name: "head", role: "skin", d: head, sd: headShade, box: "150 40 100 135", swap: faceSwap },
        { name: "hair", role: "hair", d: hair, sd: hairShade, box: "148 36 104 90", swap: faceSwap },
      ],
      marks: [
        { name: "brow ×2", role: "hair", tone: 0, d: browL + " " + browR, box: "164 82 72 26" },
        { name: "nose", role: "skin", tone: faceSwap ? 0 : 1, d: nose, box: "184 100 40 46" },
        { name: "under-eye ×2", role: "skin", tone: faceSwap ? 0 : 1, d: pouchL + " " + pouchR, box: "164 112 72 24" },
      ],
      faceSwap,
      glasses, eyes, mouthClosed, mouthMid, mouthWide,
      headT: "rotate(" + (pose.headRot === undefined ? KitModel.RIG.headRot : pose.headRot) + " " + hcx + " " + (hcy + 60) + ")",
      glassesT: "rotate(" + KitModel.RIG.glassesRot + " " + hcx + " " + ey + ")",
      prop: pose.prop ? pose.prop(c) : null,
      rig: { shL, shR, hipL, hipR, arms, legs, neckTop, neckBase, hcx, hcy },
      guides: [
        { n: "1", y: crown, label: "crown", v: "0.00 HU" },
        { n: "2", y: eyeline, label: "eyeline from crown", v: P.eyelineFromCrown.toFixed(2) + " HU" },
        { n: "3", y: shoulder, label: "shoulder from crown", v: P.shoulderFromCrown.toFixed(2) + " HU" },
        { n: "4", y: hip, label: "hip from crown", v: P.hipFromCrown.toFixed(2) + " HU" },
        { n: "5", y: knee, label: "knee — upper leg " + P.legUpperLength.toFixed(2), v: "5.37 HU" },
        { n: "6", y: floor, label: "floor — total height", v: P.totalHeight.toFixed(2) + " HU" },
      ],
    };
  }

  paint(G, H) {
    const lit = p => H.m[p.role][0], shade = p => H.m[p.role][1];
    return {
      body: G.body.map(p => ({ d: p.d, sd: p.sd, lit: p.flatTone ? shade(p) : lit(p), shade: shade(p) })),
      head: G.head.map(p => ({ d: p.d, sd: p.sd, lit: p.swap ? shade(p) : lit(p), shade: p.swap ? lit(p) : shade(p) })),
      marks: G.marks.map(m => ({ d: m.d, fill: H.m[m.role][m.tone] })),
    };
  }

}

const M = new KitModel();
module.exports = Object.assign(M, {
  P: KitModel.P, RIG: KitModel.RIG, NIGHT: KitModel.NIGHT, DUSK: KitModel.DUSK,
  POSES: KitModel.POSES, rooms: () => KitModel.rooms(), rect: KitModel.rect, poly: KitModel.poly,
  HOURS: [KitModel.NIGHT, KitModel.DUSK],
  poseKeys: Object.keys(KitModel.POSES),
});
