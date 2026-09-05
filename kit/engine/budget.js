/* Dennis v2 — type budgets.
   maxChars is enforced, not advisory: the compositor's audit errors on a fill
   longer than its budget and the shot does not render. So a budget has to come
   off the box it is set in, measured with the face it is set in — not typed
   beside the point size. This file is the one place that arithmetic lives, and
   Plate.manifest() runs it over every plate, so a re-emit cannot drift.

   The advance tables below are read from the shipped fonts' hmtx table
   (scripts/fontmetrics.js regenerates them):

     Courier Prime   every glyph 1228/2048 em = 0.5996, regular AND bold.
                     Monospaced, so a character count IS a width. Exact.
     Archivo Narrow  proportional, upem 1000, variable on wght 400-700 with
                     HVAR. A single average over the whole alphabet is not a
                     metric — the lowercase runs 0.31em and the figures 0.44em
                     — so the mean is taken per CHARACTER CLASS, weighted by
                     English letter frequency, over the class the role sets.
                     The old library-wide 0.47em constant was the uppercase
                     figure applied to lowercase prose: 39% too wide.
*/
(function (g) {
  const MONO = 0.599609375;                     // Courier Prime, exact
  // Word spaces are 16% of characters, which is what scripts/fontmetrics.js now
  // SOLVES for. The first cut of these numbers came out of tables that weighted
  // the space at 80 against letter frequencies summing to 100 — 40% spaces —
  // and since the space is the narrowest glyph in the face, both prose means
  // came out low and every budget built on them was too generous: mixed-case by
  // 13%, uppercase by 18%. figure was unaffected (its space weight is 1) and
  // Courier was never involved.
  const CLASS = { mixed: 0.3832, upper: 0.4787, figure: 0.4391 };
  const WGHT = { 400: 1, 500: 1.0123, 600: 1.0256, 700: 1.0386 };
  // The class mean is an average, and an average budget spent on wide copy
  // overflows. 4% is the allowance that keeps it honest without pretending to
  // be a worst case — a worst case ("MMMM") would cost half the budget.
  const SAFETY = 1.04;
  const PITCH = 1.16;                           // the compositor's line pitch
  // Roles whose copy is figures rather than words. Nearly all of them are set
  // in Courier and never reach the class table; the ones that are not (a
  // period label under a bar, an outcome in narrow type) would otherwise be
  // budgeted as prose and come out ~30% short.
  const NUMERIC = /^(figure|figures|big|subject|median|value|number|total|multiple|amount|delta|pct|percent|money|price|cap|share|count|period|year|score)$/;

  function klass(name, tr) {
    if (/courier/i.test(tr.font || "")) return "mono";
    if (tr.transform === "uppercase") return "upper";
    return NUMERIC.test(name) ? "figure" : "mixed";
  }
  // em advance of one character of this role's copy, tracking included: the
  // plates set tracking in em and the renderer adds it per character.
  function perChar(name, tr) {
    const tk = parseFloat(tr.tracking || 0) || 0;
    const k = klass(name, tr);
    if (k === "mono") return MONO + tk;
    return CLASS[k] * (WGHT[String(tr.weight || 400)] || 1) * SAFETY + tk;
  }
  function capacity(box, name, tr) {
    const size = tr.size || 30;
    return Math.max(1, Math.floor(box.w / (size * perChar(name, tr))));
  }
  function lineCapacity(box, tr) {
    return Math.max(1, Math.floor(box.h / ((tr.size || 30) * PITCH)));
  }

  // Writes the derived budgets onto the SLOTS and leaves the role holding the
  // narrowest of them. Returns the audit rows, which build.js collects into
  // audit/budgets.json — including the roles no slot on the plate sets, whose
  // authored numbers are left alone because there is no box to measure.
  function derive(slots, roles) {
    const rows = [];
    if (!roles) return rows;
    Object.keys(roles).forEach(function (rn) {
      const tr = roles[rn];
      const budgeted = ("maxChars" in tr) || ("maxCharsPerLine" in tr);
      if (!budgeted) return;
      const names = Object.keys(slots).filter(function (s) { return !slots[s].region && slots[s].role === rn; });
      if (!names.length) {
        rows.push({ role: rn, kept: ("maxChars" in tr) ? tr.maxChars : tr.maxCharsPerLine, reason: "no slot on this plate sets this role — nothing to measure, authored number kept" });
        return;
      }
      let floor = Infinity, floorLines = Infinity;
      names.forEach(function (s) {
        const box = slots[s], cap = capacity(box, rn, tr);
        if ("maxChars" in tr) box.maxChars = cap;
        if ("maxCharsPerLine" in tr) {
          box.maxCharsPerLine = cap;
          const ml = Math.min(tr.maxLines || lineCapacity(box, tr), lineCapacity(box, tr));
          box.maxLines = ml;
          floorLines = Math.min(floorLines, ml);
        }
        floor = Math.min(floor, cap);
        rows.push({ role: rn, slot: s, box: [box.w, box.h], size: tr.size || 30, cls: klass(rn, tr), maxChars: cap, maxLines: box.maxLines });
      });
      const was = ("maxChars" in tr) ? tr.maxChars : tr.maxCharsPerLine;
      if ("maxChars" in tr) tr.maxChars = floor;
      if ("maxCharsPerLine" in tr) tr.maxCharsPerLine = floor;
      if ("maxLines" in tr && floorLines < Infinity) tr.maxLines = Math.min(tr.maxLines, floorLines);
      tr.budget = "derived from the slot boxes that set this role; " + floor + " is the floor (narrowest of " + names.length + "), was " + was;
    });
    return rows;
  }

  g.BUDGET = { MONO: MONO, CLASS: CLASS, WGHT: WGHT, SAFETY: SAFETY, PITCH: PITCH, NOTE: "maxChars is a HARD LIMIT, not editorial guidance. The compositor's audit raises an ERROR on any fill longer than the budget for the box it lands in, and an over-budget shot does not render — so a number authored beside the point size instead of measured off the box is a defect in both directions: too loose and it waves through copy that collides with the rule beside it, too tight and it stops a short that would have fitted. Every budget in this file is now DERIVED — box width divided by the per-character advance of the real face, read from the font's own hmtx table. Courier Prime is monospaced at 0.5996em (regular and bold identical), so its numbers are exact. Archivo Narrow is proportional, so its advance is a frequency-weighted mean over the character class the role actually sets — 0.383em mixed-case, 0.479em uppercase-transformed, 0.439em figures — instanced on the wght axis for 500/600/700 (a 700 runs 3.9% wider than a 400) and carrying a 4% allowance, which makes it a fair average rather than a promise about one wide string. BUDGETS LIVE ON THE SLOT: slots[name].maxChars is the number for THAT box and is what the audit reads, because one role is set in boxes of different widths on the same plate and a single number per role cannot be right in both. The role-level maxChars is the FLOOR — the narrowest slot on this plate that sets the role — so a reader that only knows about roles stays inside every box. maxLines is capped by box height at the compositor's 1.16em line pitch, and maxCharsPerLine is the same width derivation; line breaking itself is by measured width, never by character count. A role declared in typeRoles that no slot on the plate sets keeps its authored number and is listed in audit/budgets.json.", klass: klass, perChar: perChar, capacity: capacity, lineCapacity: lineCapacity, derive: derive };
})(typeof window !== "undefined" ? window : globalThis);
