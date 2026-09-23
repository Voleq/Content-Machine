#!/usr/bin/env node
/* Dennis v2 — check a roles.json's HOST ROLE MEMBERSHIP against what the plates
 * actually publish. This is drop fifteen's two failures as one command.
 *
 * WHY IT EXISTS. Both host failures on 394c1be were membership errors that the
 * kit had all the data to refuse:
 *
 *   test_a_room_that_refuses_a_cut_out_gets_a_framing_instead
 *     host/sitting-at-desk stands in a room with no floor
 *   test_every_role_can_supply_a_shot
 *     host/empty-chair is not a cut-out
 *
 * Both are checkable from published fields. Every host plate declares floorLineY
 * (a number, or false for a framing) and cutout/alpha. So:
 *
 *   TWO RULES, and they are the two tests.
 *
 *   1. A SUBSTITUTION ROLE may contain only plates with floorLineY: false.
 *      The renderer swaps to one of these for a room declaring
 *      hostAnchor: false (compose.py:86 HOST_WHERE_NOBODY_STANDS). A framing is
 *      a camera distance with no floor line to pin; a pose needs a floor, and in
 *      a floorless room it stands on nothing. `to-camera` is one by default.
 *
 *   2. EVERY member of ANY host role must publish cutout: true.
 *      A host role's members get composited onto a room's host-anchor, so a
 *      member the compositor cannot composite is a role that cannot supply a
 *      shot.
 *
 * WHAT IT DOES NOT CHECK, so nobody reads a pass as more than it is: it says
 * nothing about whether a pose SUITS a chapter, and it does not look at the
 * renderer's substitution code. The unguarded substitution site is a separate
 * defect on the pipeline side — this check constrains the set that code picks
 * from, it does not make that code verify its pick.
 *
 * USAGE
 *   node scripts/check_roles.mjs ../roles.json
 *   node scripts/check_roles.mjs ../roles.json --floorless to-camera,other-role
 *   node scripts/check_roles.mjs --census        # no roles.json: just print what
 *                                                 the plates publish
 *
 * Exit 0 clean, 1 on a violation, 2 on a usage or read error.
 */
import { readFileSync, existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const KIT = resolve(HERE, "..");
const argv = process.argv.slice(2);
const val = (n, d) => { const i = argv.indexOf(n); return i >= 0 ? argv[i + 1] : d; };
const CENSUS = argv.indexOf("--census") >= 0;
const FLOORLESS = val("--floorless", "to-camera").split(",").map((s) => s.trim()).filter(Boolean);
const rolesPath = argv.find((a) => !a.startsWith("--") && argv[argv.indexOf(a) - 1] !== "--floorless");

// The plates' own published facts, read from the emitted manifests rather than by
// re-drawing 924 frames. If host/manifest.json is stale against the engine,
// scripts/emit_manifests.mjs --check is the command that says so — this one
// trusts the manifest deliberately, because the manifest is what the renderer
// reads too.
const MAN = join(KIT, "host", "manifest.json");
if (!existsSync(MAN)) {
  console.error("no kit/host/manifest.json — run: node scripts/emit_manifests.mjs");
  process.exit(2);
}
const host = JSON.parse(readFileSync(MAN, "utf8"));
const PLATE = {};
for (const [key, p] of Object.entries(host.plates)) {
  PLATE[key] = {
    floorLineY: p.meta.floorLineY,
    framing: p.meta.floorLineY === false,
    cutout: p.meta.cutout === true,
    playback: p.playback,
  };
}
const shortName = (k) => k.replace(/^host\//, "");

if (CENSUS || !rolesPath) {
  const fr = Object.keys(PLATE).filter((k) => PLATE[k].framing);
  const po = Object.keys(PLATE).filter((k) => !PLATE[k].framing);
  const nc = Object.keys(PLATE).filter((k) => !PLATE[k].cutout);
  console.log("host plates: " + Object.keys(PLATE).length);
  console.log("\nfloorLineY: false — FRAMINGS, legal in a substitution role (" + fr.length + ")");
  console.log("  " + fr.map(shortName).join(" "));
  console.log("\nfloorLineY: <number> — POSES, need a floor under them (" + po.length + ")");
  console.log("  " + po.map(shortName).join(" "));
  console.log("\ncutout: not true — cannot be composited onto a host-anchor (" + nc.length + ")");
  console.log("  " + (nc.length ? nc.map(shortName).join(" ") : "none"));
  if (!rolesPath && !CENSUS) {
    console.log("\n(no roles.json given — census only. Pass a path to check membership.)");
  }
  if (!rolesPath) process.exit(0);
}

const rp = resolve(rolesPath);
if (!existsSync(rp)) { console.error("cannot read " + rp); process.exit(2); }
const roles = JSON.parse(readFileSync(rp, "utf8"));
const hostRoles = roles.hostRoles || roles.host_roles;
if (!hostRoles) { console.error("no hostRoles in " + rp); process.exit(2); }

const fail = [];
const unknown = [];
for (const [role, members] of Object.entries(hostRoles)) {
  if (!Array.isArray(members)) continue;
  const substitution = FLOORLESS.indexOf(role) >= 0;
  for (const raw of members) {
    const key = raw.indexOf("/") >= 0 ? raw : "host/" + raw;
    const p = PLATE[key];
    if (!p) { unknown.push(role + " -> " + raw); continue; }
    if (substitution && !p.framing) {
      fail.push({
        rule: 1, role, key,
        why: "declares floorLineY " + p.floorLineY + ", so it needs a floor. " + role +
             " is the role substituted into a room with hostAnchor: false, where there is none.",
      });
    }
    if (!p.cutout) {
      fail.push({
        rule: 2, role, key,
        why: "does not publish cutout: true, so the compositor cannot composite it onto a host-anchor.",
      });
    }
  }
}

const roleCount = Object.keys(hostRoles).length;
console.log("checked " + roleCount + " host roles in " + rolesPath +
  "  (substitution roles: " + FLOORLESS.join(", ") + ")");
if (unknown.length) {
  console.log("\nNOT IN THE KIT — named in a role, no such plate (" + unknown.length + "):");
  unknown.forEach((u) => console.log("  " + u));
  console.log("  (not a failure here: the renderer may have plates the kit did not build.)");
}
if (!fail.length) { console.log("\nok — every host role can supply a shot, and no pose sits in a substitution role."); process.exit(0); }

console.log("\n" + fail.length + " VIOLATION" + (fail.length > 1 ? "S" : "") + ":");
for (const f of fail) console.log("  [rule " + f.rule + "] " + f.role + " -> " + f.key + "\n      " + f.why);
console.log("\nrule 1: a substitution role may contain only plates with floorLineY: false.");
console.log("rule 2: every member of a host role must publish cutout: true.");
process.exit(1);
