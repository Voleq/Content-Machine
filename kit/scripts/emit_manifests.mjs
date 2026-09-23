#!/usr/bin/env node
/* Dennis v2 — scripts/emit_manifests.mjs
 *
 * RETIRED AS A SECOND GENERATOR (rebuild-17). It used to load engine/audit.js
 * through new Function — which throws on the audit's own #!/usr/bin/env node
 * line before checking anything — and, pointed at audit.legacy.js, it checked
 * the old 270-plate kit rather than this one. Two generators for one set of
 * manifests is how they drift, so this is now a thin door onto the one that
 * exists: engine/emit.js, which writes every <family>/manifest.json itself.
 * scripts/manifest_core.js is no longer called by anything.
 *
 *   node scripts/emit_manifests.mjs            # = node engine/emit.js
 *   node scripts/emit_manifests.mjs --check    # = node engine/emit.js --check
 */
import { createRequire } from 'module';
const require = createRequire(import.meta.url);
const E = require('../engine/emit.js');
if (process.argv.includes('--check')) {
  const r = E.check();
  process.stdout.write(r.ok ? 'emit --check clean: ' + r.files + ' files match the engine\n'
    : 'emit --check: ' + r.diffs.length + ' of ' + r.files + ' files differ:\n  ' + r.diffs.join('\n  ') + '\n');
  process.exit(r.ok ? 0 : 1);
} else {
  const b = E.run();
  process.stdout.write(b.counts.assets + ' assets · ' + b.counts.families + ' family manifests written\n');
}
