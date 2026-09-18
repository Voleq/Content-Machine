/* Dennis v2 — THE MANIFEST EMITTER, and the single source of what a manifest is.
 *
 * WHY THIS FILE EXISTS
 *
 * The delta-14 manifests were written by a throwaway script in drop twelve. That
 * script whitelisted the slot fields it copied — x, y, w, h, role, align,
 * maxChars, region, note — and silently dropped every other field the engine
 * publishes. HAND.Plate.slot() does this:
 *
 *   P.slots[key] = Object.assign({}, extra || {}, { x, y, w, h })
 *
 * so a slot carries WHATEVER ITS AUTHOR PASSED. anchorX, growth, baselineY,
 * year, overlay, quarter, index, axisY, container, renderer, series, optional,
 * points, tick, spans, axis, identifier, rows — eighteen fields across 64 plates
 * — were published by the engine and absent from the shipped copy. Geometry was
 * never the problem: not one x, y, w or h differs. The ingest compares the full
 * slot object, finds keys it did not get, and refuses the pack.
 *
 * The header had the same defect from the other direction: the family notes were
 * TYPED into the writer script, so engine/build.js FAMILY_NOTES — the declared
 * source, sitting beside the assets it describes — was never emitted at all.
 *
 * So the emit is code that ships, not a script someone had lying around, and it
 * is loaded by both routes: scripts/emit_manifests.mjs (node) and any browser
 * page that wants to diff a manifest against the engine in front of it.
 *
 * THE RULE THIS FILE KEEPS: slots are emitted VERBATIM as P.manifest() returns
 * them. No whitelist, no field list to maintain, nothing to fall behind. A plate
 * author who adds a field gets it in the manifest by construction.
 *
 * WHAT IS DELIBERATELY UNCHANGED from the delta-14 shape, so that a reconcile
 * against the shipped copy shows only the fields at issue:
 *   - plate entry key order, and typeRoles hoisted out of meta to plate level
 *   - meta emitted as manifest() returns it, including its static-defaults
 *     frameCount/fps/playback. Those disagree with the plate-level playback on
 *     an animated plate and always have; the plate level is authoritative and
 *     the ingest reads it. Left alone on purpose — fixing it here would put a
 *     second change into a pack whose whole job is the slot fields.
 *
 * THE HASH, STATED RATHER THAN BURIED. No hash function ships in engine/, so the
 * one drop twelve used cannot be recovered or re-run — its values are not
 * reproducible from the engine you are holding, which is the same class of defect
 * as the slots. This file declares one (FNV-1a 32-bit over the emitted SVG
 * string) and writes the algorithm into every manifest header as hashAlgo, so the
 * next reader can recompute rather than trust. The values therefore CHANGE from
 * delta-14 on every frame. They are a fingerprint for "did this byte-sequence
 * move", nothing else reads them as an identity, and a hash nobody can recompute
 * was worth less than a hash that changes once.
 */
(function (g) {
  const PACK = "delta-15";

  const SPEC = "PER-FAMILY PLATE MANIFEST. One file per family, generated from the engine — never hand-edited. Everything here is READ by scripts/ingest_kit.py and by the renderer; nothing here is authored. A plate contains no content, it contains SLOTS: the renderer fills them at video time. canvas is in canvas units; delivered is canvas x exportScale and is the pixel size of the PNG on disk. maxChars / maxCharsPerLine / maxLines are DERIVED by budget.js from each role's own font metrics and are enforced, not advisory — the compositor errors on an over-budget fill and the shot does not render, so a string past the budget is an ABSENT plate, not a tight one. SLOT FIELDS ARE EMITTED VERBATIM from Plate.manifest(): every field a plate author attaches to a slot appears here, because the emitter copies the slot object rather than a whitelist of fields it knows about. delta-14's copies dropped eighteen such fields across 64 plates and the ingest refused the pack.";

  const FRAME_NAMING = "_f01.._fNN, zero-padded to two digits, appended to the plate name before the extension. The BASE file carries no tag and is emitted from frame one's own args, so it is byte-identical to _f01 by construction — files.baseIsFrame is true on every entry and is derived here rather than asserted by hand. An ingest that writes the base and the frames writes frame one twice, deliberately: a renderer that wants a still takes the base without knowing the frame count.";

  const GENERATED = "engine/build.js + engine/plates.js via scripts/manifest_core.js. Deterministic — regenerate from the engine you are holding rather than trusting this copy: node scripts/emit_manifests.mjs";

  const HASH_ALGO = "fnv1a-32 over the emitted SVG string (UTF-16 code units), lowercase hex, zero-padded to 8. Recompute with MANIFEST_EMIT.hash(svg). NOT the function delta-14 used — that one ships nowhere in engine/ and its values cannot be reproduced, so they were replaced with values that can be.";

  function hash(s) {
    let h = 0x811c9dc5;
    for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 0x01000193) >>> 0; }
    return (h >>> 0).toString(16).padStart(8, "0");
  }

  // One plate, every field the shipped shape carries. `frames` is the frame list
  // from BUILD.framesOf and is walked ONCE — each frame is drawn, hashed and
  // dropped, so peak memory here is one plate whatever the family size.
  function plateEntry(B, item) {
    const name = item.key.split("/").pop();
    const frames = B.framesOf(item);
    const play = B.playbackOf(item);
    const m = B.draw(item, null, frames[0].args).manifest();

    const fileFrames = frames.map(function (fr) {
      const svg = B.draw(item, null, fr.args).toSVG();
      return { file: name + (fr.tag || "") + ".png", tag: fr.tag || null, args: fr.args, hash: hash(svg) };
    });

    // meta minus the two fields hoisted to plate level. Everything else the
    // author published rides along untouched.
    const meta = {};
    Object.keys(m).forEach(function (k) {
      if (k === "slots" || k === "typeRoles" || k === "canvas" || k === "exportScale") return;
      if (m[k] !== undefined) meta[k] = m[k];
    });

    const e = {
      key: item.key,
      dir: item.dir,
      aspect: m.aspect || (/-(\d+x\d+)$/.test(item.key) ? item.key.match(/-(\d+x\d+)$/)[1] : undefined),
      canvas: m.canvas,
      delivered: m.delivered,
      exportScale: m.exportScale,
      playback: play.playback,
      fps: play.fps,
      frameCount: play.frameCount,
      files: { base: name + ".png", baseIsFrame: frames.length > 1, frames: fileFrames },
      slotCount: Object.keys(m.slots).length,
      typeRoles: m.typeRoles,
      slots: m.slots,
      meta: meta,
    };
    if (play.loopStart !== undefined) e.loopStart = play.loopStart;
    if (play.settleNote) e.settleNote = play.settleNote;
    if (play.overlayOf) e.overlayOf = play.overlayOf;
    if (play.overlayContract) e.overlayContract = play.overlayContract;
    if (play.boilGate) e.boilGate = play.boilGate;
    if (e.typeRoles === undefined) delete e.typeRoles;
    if (e.aspect === undefined) delete e.aspect;
    return e;
  }

  // One family, complete: the header from BUILD.FAMILY_NOTES (the declared
  // source) plus every plate in it.
  function emitFamily(B, family) {
    const items = B.LIB.filter(function (x) { return x.key.split("/")[0] === family; });
    if (!items.length) throw new Error("no such family: " + family);
    const notes = B.FAMILY_NOTES[family] || { family: family };

    const out = {
      family: family,
      pack: PACK,
      generated: GENERATED,
      _spec: SPEC,
      exportScale: 2,
      hashAlgo: HASH_ALGO,
      frameNaming: FRAME_NAMING,
      assetCount: items.length,
    };
    // The declared family notes, which delta-14 typed into its writer and then
    // did not emit. Header and assets from ONE source, which is the whole point
    // of FAMILY_NOTES living in build.js beside the assets.
    Object.keys(notes).forEach(function (k) {
      if (k === "family" || k === "exportScale") return;
      out[k] = notes[k];
    });

    const plates = {};
    let slotTotal = 0, frameTotal = 0;
    items.forEach(function (it) {
      const e = plateEntry(B, it);
      slotTotal += e.slotCount;
      frameTotal += e.frameCount;
      plates[it.key] = e;
    });
    out.slotTotal = slotTotal;
    out.frameTotal = frameTotal;
    out.plates = plates;
    return out;
  }

  g.MANIFEST_EMIT = { emitFamily: emitFamily, plateEntry: plateEntry, hash: hash, PACK: PACK };
})(typeof window !== "undefined" ? window : globalThis);
