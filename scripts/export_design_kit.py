#!/usr/bin/env python3
"""Export the Claude-Design kit (``*.dc.html``) to PNG.

The design delivery ships ~43 design documents whose artwork is live
HTML/CSS/SVG painted at render time by ``support.js``.  Nothing in there is a
picture until a browser has run it, so this script *is* the only way the kit
becomes files the pipeline can composite.

How it works
------------
Every exportable element carries a ``data-export="<id>"`` attribute (templated
in the source, expanded once the page renders).  Every document carries an
``EXPORT · <target> · <size>`` marker naming where the frames land and how big
they should be.  This script:

1. serves the repo over a loopback HTTP server so ``./support.js`` resolves,
2. loads each document in headless Chromium (the browser already vendored for
   :mod:`pipeline.filings`),
3. pins React/ReactDOM to the copies in ``assets/design_kit/vendor`` and the
   webfonts to ``assets/fonts`` — so the export is deterministic and offline,
4. clones each ``[data-export]`` element into a clean overlay, scales it to the
   size its marker asks for, and screenshots it with a transparent backdrop,
5. writes ``assets/kit/manifest.json`` (id → path → size → alpha) so a missing
   asset is obvious.

It is a *build* script, not a runtime dependency: nothing under ``pipeline/``
imports it and the test suite never runs it.

Usage
-----
    python scripts/export_design_kit.py                # everything
    python scripts/export_design_kit.py --doc Callouts # one document
    python scripts/export_design_kit.py --list         # plan, render nothing
"""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import shutil
import socketserver
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KIT_SRC = ROOT / "assets" / "design_kit"
KIT_OUT = ROOT / "assets" / "kit"
FONT_DIR = ROOT / "assets" / "fonts"
MANIFEST = KIT_OUT / "manifest.json"

# support.js pulls these three from unpkg; ``window.__resources`` lets us point
# it at local copies instead (vendored next to the documents, SRI-verified).
CDN_OVERRIDES = {
    "https://unpkg.com/react@18.3.1/umd/react.production.min.js": "assets/design_kit/vendor/react.production.min.js",
    "https://unpkg.com/react-dom@18.3.1/umd/react-dom.production.min.js": "assets/design_kit/vendor/react-dom.production.min.js",
}

# The documents ask Google Fonts for Shantell Sans 400/600/700/800, Space
# Grotesk 400/500/600/700 and Space Mono 400/700.  We ship static faces only,
# so the bold cut covers 600-900: a weight range keeps the browser from
# synthesising a fake bold (which would not match the design) and keeps every
# glyph identical between runs.
FONT_FACES = [
    ("Shantell Sans", "ShantellSans-Regular.ttf", "400", "normal"),
    ("Shantell Sans", "ShantellSans-Bold.ttf", "600 900", "normal"),
    ("Shantell Sans", "ShantellSans-BoldItalic.ttf", "600 900", "italic"),
    ("Space Grotesk", "SpaceGrotesk-Regular.ttf", "400", "normal"),
    ("Space Grotesk", "SpaceGrotesk-Medium.ttf", "500", "normal"),
    ("Space Grotesk", "SpaceGrotesk-Bold.ttf", "600 900", "normal"),
    ("Space Mono", "SpaceMono-Regular.ttf", "400", "normal"),
    ("Space Mono", "SpaceMono-Bold.ttf", "600 900", "normal"),
]
FONT_FAMILIES = ("Shantell Sans", "Space Grotesk", "Space Mono")

# Layout viewport.  The documents cap their content at max-width:1440px, so any
# viewport at or above that lays out identically — pinning it keeps the CSS
# sizes (and therefore the export scales) stable run to run.
VIEWPORT = {"width": 1920, "height": 1920}
DEVICE_SCALE = 2.0

# A frame is matched to one of its document's declared sizes by scaling to that
# width and checking the height lands close enough.  Artwork is never squashed
# to hit a declared height exactly — the width is the budget, the aspect wins.
HEIGHT_TOLERANCE = 0.08


@dataclass(frozen=True)
class Route:
    """A destination for the ids in one document that share a prefix.

    Some documents ship two families at once — Reactions carries both the
    ``reactions/`` cutaways (700×830, transparent) and the ``straps/``
    furniture (1920×220) — so the id prefix picks the folder *and* the size.
    """

    prefix: str  # data-export id prefix, "" matches everything
    target: str  # destination folder under assets/kit/
    sizes: tuple[tuple[int, int], ...] = ()  # declared export sizes
    default_scale: float = 3.0  # used when no declared size fits


@dataclass(frozen=True)
class DocSpec:
    """Where one design document's frames land, and how big."""

    doc: str  # file name stem match (unique substring of the .dc.html name)
    target: str  # destination folder under assets/kit/ (the default route)
    sizes: tuple[tuple[int, int], ...] = ()  # declared export sizes
    default_scale: float = 3.0  # used when no declared size fits
    routes: tuple[Route, ...] = ()  # prefix overrides, checked longest-first
    exclude: tuple[str, ...] = ()  # data-export ids that are guides, not assets
    note: str = ""

    def route_for(self, export_id: str) -> Route:
        for r in sorted(self.routes, key=lambda r: -len(r.prefix)):
            if export_id.startswith(r.prefix):
                return r
        return Route("", self.target, self.sizes, self.default_scale)


# Derived from each document's own EXPORT marker (recorded in the manifest so a
# marker that changes is easy to spot).  Documents that are reference sheets —
# the rig teardowns and the style board — carry no exportable artwork and are
# deliberately absent.
DOC_SPECS: tuple[DocSpec, ...] = (
    # --- host rig -----------------------------------------------------------
    DocSpec("Host Poses", "mascot", default_scale=3.0,
            note="EXPORT · mascot/host/ · transparent PNG · capture each data-export at scale"),
    DocSpec("Mascot - Export", "mascot/expressions", default_scale=3.0),
    DocSpec("Reactions", "mascot", sizes=((700, 830),), default_scale=4.0,
            routes=(Route("straps/", "type", ((1920, 220),), 1.5),),
            note="EXPORT · mascot/reactions/ 700×830 · type/straps/ 1920×220"),
    # --- typographic furniture (full 16:9 frames) ---------------------------
    DocSpec("Callouts", "type/callouts", sizes=((1920, 1080),), default_scale=4.0),
    DocSpec("Chapter Opener", "type", sizes=((1920, 1080),), default_scale=4.0),
    DocSpec("Chapter Recap Boards", "type", sizes=((1920, 1080),), default_scale=3.0),
    DocSpec("Data Tables", "type", sizes=((1920, 1080),), default_scale=3.0),
    DocSpec("Episode Furniture", "type", sizes=((1920, 1080),), default_scale=3.0),
    DocSpec("Lower-Third Alerts", "type", sizes=((1920, 1080),), default_scale=3.0),
    DocSpec("Quote Cards", "type", sizes=((1920, 1080),), default_scale=3.0),
    DocSpec("Scenarios", "type", sizes=((1920, 1080),), default_scale=3.0),
    DocSpec("Transcript Pull-Outs", "type", sizes=((1920, 1080),), default_scale=3.0),
    DocSpec("Comparison Sliders", "type", sizes=((1920, 1080),), default_scale=4.0),
    DocSpec("End Screens", "type", sizes=((1920, 1080),), default_scale=3.0,
            exclude=("end-screens/safe-zones",),
            note="export the CLEAN frame; the guide frame is for checking only"),
    DocSpec("Type Furniture", "type/furniture",
            sizes=((1600, 900), (1000, 1250), (1000, 1000)), default_scale=3.0),
    # --- motion strips ------------------------------------------------------
    DocSpec("Stings", "", sizes=((1920, 1080),), default_scale=12.0,
            note="EXPORT · stings/<name>/f01…f06.png · 1920×1080"),
    DocSpec("Bumper Transitions", "type", sizes=((1920, 1080),), default_scale=4.0,
            note="IN and OUT are 6 frames each in the edit; HOLD is a still"),
    # --- props --------------------------------------------------------------
    DocSpec("Chart Props", "props", sizes=((920, 600),), default_scale=4.0),
    DocSpec("Objects", "props", sizes=((600, 600),), default_scale=4.0),
    DocSpec("Concepts", "props/concepts", sizes=((1000, 1000),), default_scale=3.33),
    DocSpec("Management & News", "props/management",
            sizes=((1000, 1000), (1000, 500), (1600, 360)), default_scale=3.0),
    # --- chapter evidence kits ---------------------------------------------
    DocSpec("Ch Long-form", "chapters/long-form", sizes=((1600, 900),), default_scale=3.0),
    DocSpec("Ch Cold-Open", "chapters/cold-open", sizes=((1600, 900),), default_scale=3.0),
    DocSpec("Ch How Money", "chapters/how-money",
            sizes=((1000, 1280), (1040, 600), (1800, 480)), default_scale=3.0),
    DocSpec("Ch Capital Allocation", "chapters/capital-allocation", sizes=((1600, 900),), default_scale=3.0),
    DocSpec("Ch Filing Walk", "chapters/filing-walk", sizes=((1600, 900),), default_scale=3.0),
    DocSpec("Ch Guidance", "chapters/guidance", sizes=((1600, 900),), default_scale=3.0),
    DocSpec("Ch How We Got Here", "chapters/how-we-got-here", sizes=((1600, 900),), default_scale=3.0),
    DocSpec("Ch Management", "chapters/management", sizes=((1600, 900),), default_scale=3.0),
    DocSpec("Ch Moat", "chapters/moat", sizes=((1600, 900),), default_scale=3.0),
    DocSpec("Ch Sector Comps", "chapters/sector-comps", sizes=((1600, 900),), default_scale=3.0),
    DocSpec("Ch Short Interest", "chapters/short-interest", sizes=((1600, 900),), default_scale=3.0),
    # --- short form ---------------------------------------------------------
    DocSpec("Short Variants", "short", sizes=((1080, 1920), (920, 520)), default_scale=4.0,
            note="EXPORT · short/variants/ + short/host-bookend/ · beats 1080×1920 · minis 920px"),
    DocSpec("Short GET-GO", "short/getgo", sizes=((1080, 1920),), default_scale=4.0),
    # --- publishing ---------------------------------------------------------
    DocSpec("Thumbnails", "", sizes=((1280, 720),), default_scale=2.0),
    DocSpec("Social Quote Cards", "", sizes=((1080, 1080), (1080, 1350)), default_scale=3.0),
    # This sheet lays its frames out at their real export size already.
    DocSpec("Export Frames", "frames", default_scale=1.0),
    # --- the light restyle of the existing (dark) kit, 1:1 by name ----------
    DocSpec("Restyle Brand", "restyle", default_scale=3.0),
    DocSpec("Restyle Concepts", "restyle", default_scale=3.0),
    DocSpec("Restyle Injokes", "restyle", default_scale=3.0),
    DocSpec("Restyle Marks", "restyle", default_scale=3.0),
)


# --------------------------------------------------------------------------- #
# paths
# --------------------------------------------------------------------------- #
def merge_path(target: str, export_id: str) -> str:
    """Resolve a ``data-export`` id against its document's target folder.

    Ids are sometimes bare (``moat-wide``) and sometimes already carry their
    own folders (``host/look-left-talk-open``, ``mascot/mouth-mid``).  When the
    id's first segment already appears in the target folder the two are merged
    at that point rather than nested twice::

        mascot        + host/look-left-talk-open -> mascot/host/look-left-talk-open
        mascot        + mascot/mouth-mid         -> mascot/mouth-mid
        type/callouts + callouts/term-roic       -> type/callouts/term-roic
        type          + bumpers/paper/in         -> type/bumpers/paper/in
    """
    tgt = [p for p in target.split("/") if p]
    idp = [p for p in export_id.split("/") if p]
    if len(idp) > 1 and idp[0] in tgt:
        return "/".join(tgt[: tgt.index(idp[0])] + idp)
    return "/".join(tgt + idp)


def pick_scale(css_w: float, css_h: float, route: Route) -> tuple[float, str]:
    """Scale factor for one frame, plus a human note about how it was chosen.

    The declared width is the budget.  Artwork is never squashed to hit a
    declared height: the closest-fitting declared size wins on width and the
    aspect ratio is preserved.
    """
    best: tuple[float, tuple[int, int]] | None = None
    for tw, th in route.sizes:
        k = tw / css_w
        err = abs(css_h * k - th) / th
        if best is None or err < best[0]:
            best = (err, (tw, th))
    if best is not None and best[0] <= HEIGHT_TOLERANCE:
        tw, th = best[1]
        note = f"{tw}×{th}" if best[0] < 0.005 else f"{tw}w (declared {tw}×{th}, kept aspect)"
        return tw / css_w, note
    return route.default_scale, f"×{route.default_scale:g}"


# --------------------------------------------------------------------------- #
# browser plumbing
# --------------------------------------------------------------------------- #
def font_css(base_url: str) -> str:
    return "\n".join(
        "@font-face{font-family:'%s';"
        "src:url('%s/assets/fonts/%s') format('truetype');"
        "font-weight:%s;font-style:%s;font-display:block;}" % (fam, base_url, fn, wt, st)
        for fam, fn, wt, st in FONT_FACES
    )


def serve(root: Path) -> tuple[str, socketserver.TCPServer]:
    """A quiet loopback file server so ``./support.js`` and the fonts resolve."""
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    handler.log_message = lambda *a, **k: None  # type: ignore[assignment]

    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    srv = Server(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_address[1]}", srv


# Clone the frame into a clean fixed overlay before shooting it: the clone is
# immune to the grid it was sitting in (ancestor overflow, transforms, the
# swatch background behind it) and gets an explicit pixel size, so scaling it
# cannot reflow its insides.  Presentation-only chrome — the rounded corner and
# drop shadow that make the design doc readable — is stripped, because a video
# frame is full-bleed.
#
# The rest of the document is then hidden and the page background cleared:
# `omit_background` only drops the browser's *default* white, so the design
# doc's own paper-coloured body would otherwise fill in behind every frame the
# kit wants transparent.  Because that hiding also collapses the originals,
# each element's CSS size is measured up front and passed back in here.
#
# Typography inherits down the document (the docs set the family once on their
# root and let it cascade), so the source's computed text properties are
# re-applied to the clone — it now hangs off <body> instead.
PREPARE_JS = """
(args) => {
  const {id, k, w, h} = args;
  const src = document.querySelector('[data-export="' + id.replace(/"/g, '\\\\"') + '"]');
  if (!src) return null;
  let host = document.getElementById('__dc_export_stage');
  if (!host) {
    const iso = document.createElement('style');
    iso.textContent =
      'html,body{background:transparent !important;margin:0 !important;padding:0 !important;}' +
      'body > *:not(#__dc_export_stage){display:none !important;}';
    document.head.appendChild(iso);
    host = document.createElement('div');
    host.id = '__dc_export_stage';
    host.style.cssText = 'position:fixed;left:0;top:0;margin:0;padding:0;' +
                         'background:transparent;z-index:2147483647;';
    document.body.appendChild(host);
  }
  const cs = getComputedStyle(src);
  for (const prop of ['fontFamily', 'fontSize', 'fontWeight', 'fontStyle', 'lineHeight',
                      'letterSpacing', 'color', 'textAlign', 'textTransform',
                      'fontVariantNumeric', 'wordSpacing']) {
    host.style[prop] = cs[prop];
  }
  host.innerHTML = '';
  const clone = src.cloneNode(true);
  clone.style.width = w + 'px';
  clone.style.height = h + 'px';
  clone.style.margin = '0';
  clone.style.flex = 'none';
  clone.style.borderRadius = '0';
  clone.style.boxShadow = 'none';
  const scale = (el) => {
    el.style.transform = 'scale(' + k + ')';
    el.style.transformOrigin = 'top left';
  };
  if (args.cqType) {
    // Rebuild the query container the frame was measured against, at the
    // same width relative to the frame, so every cqw resolves as authored.
    // Its own padding is dropped so the frame still starts at the origin.
    const cq = document.createElement('div');
    cq.style.cssText = 'position:relative;margin:0;padding:0;border:0;';
    cq.style.containerType = args.cqType;
    cq.style.width = (w * args.cqRatio) + 'px';
    cq.style.height = (h * args.cqRatio) + 'px';
    cq.appendChild(clone);
    host.appendChild(cq);
    if (args.cqBg) {
      // The frame fills its container, so that container's paper is the
      // frame's backdrop: carry it over and scale the pair as one, leaving
      // whatever transform the frame already had for itself.
      cq.style.backgroundColor = args.cqBg.color;
      cq.style.backgroundImage = args.cqBg.image;
      cq.style.backgroundSize = args.cqBg.size;
      cq.style.backgroundPosition = args.cqBg.position;
      cq.style.backgroundRepeat = args.cqBg.repeat;
      scale(cq);
    } else {
      scale(clone);
    }
  } else {
    scale(clone);
    host.appendChild(clone);
  }
  const out = (args.cqBg ? clone.parentElement : clone).getBoundingClientRect();
  return {w: out.width, h: out.height};
}
"""

MEASURE_JS = """
() => {
  const els = [];
  document.querySelectorAll('[data-export]').forEach(el => {
    const r = el.getBoundingClientRect();
    // Most of the kit sizes its type in container-query units. When the
    // element that carries data-export is *inside* the query container
    // rather than being it, lifting it onto the export stage would strand
    // every `cqw` against the viewport — so record the container to rebuild.
    let cqType = null, cqRatio = 1, cqBg = null;
    for (let p = el.parentElement; p; p = p.parentElement) {
      const cs = getComputedStyle(p);
      if (cs.containerType && cs.containerType !== 'normal') {
        cqType = cs.containerType;
        cqRatio = p.getBoundingClientRect().width / (r.width || 1);
        // When the frame fills its container, the container's paper is the
        // frame's own backdrop — carry it over, or the export loses the
        // background the design doc shows behind the artwork.
        if (Math.abs(cqRatio - 1) < 0.01) {
          cqBg = {color: cs.backgroundColor, image: cs.backgroundImage,
                  size: cs.backgroundSize, position: cs.backgroundPosition,
                  repeat: cs.backgroundRepeat};
        }
        break;
      }
    }
    els.push({id: el.getAttribute('data-export'), w: r.width, h: r.height,
              cqType, cqRatio, cqBg});
  });
  const markers = [...document.querySelectorAll('*')]
      .filter(e => e.childElementCount === 0 && (e.textContent || '').trim().startsWith('EXPORT'))
      .map(e => (e.textContent || '').trim().replace(/\\s+/g, ' '));
  return {els, markers};
}
"""

# A webfont that silently falls back would ship the whole kit in the wrong
# typeface, so prove each family is really doing the drawing: the same string
# measured in the family and in a deliberately-absent family must differ.
# The faces are awaited first — `font-display:block` means an unloaded face
# measures like the fallback, which would read as a false alarm.
FONT_PROBE_JS = """
async (families) => {
  for (const fam of families) {
    for (const wt of ['400', '700']) {
      try { await document.fonts.load(wt + ' 80px "' + fam + '"'); } catch (e) {}
    }
  }
  await document.fonts.ready;
  const probe = document.createElement('span');
  probe.style.cssText = 'position:absolute;left:-9999px;top:0;font-size:80px;white-space:pre;';
  probe.textContent = 'Dennis 0123 mwil';
  document.body.appendChild(probe);
  const out = {};
  for (const fam of families) {
    probe.style.fontFamily = '"__dc_missing_face__"';
    const fallback = probe.getBoundingClientRect().width;
    probe.style.fontFamily = '"' + fam + '", "__dc_missing_face__"';
    const actual = probe.getBoundingClientRect().width;
    probe.style.fontWeight = '700';
    const bold = probe.getBoundingClientRect().width;
    probe.style.fontWeight = '400';
    out[fam] = {fallback, actual, bold};
  }
  probe.remove();
  return out;
}
"""


@dataclass
class DocResult:
    doc: str
    written: int = 0
    skipped: int = 0
    markers: list[str] = field(default_factory=list)
    missing_backdrops: set[str] = field(default_factory=set)
    warnings: list[str] = field(default_factory=list)


def export_doc(page, base_url: str, spec: DocSpec, doc_path: Path,
               out_root: Path, missing: set[str], plan_only: bool) -> DocResult:
    from urllib.parse import quote

    res = DocResult(doc=doc_path.name)
    url = f"{base_url}/{quote(str(doc_path.relative_to(ROOT)))}"
    page.goto(url, wait_until="load", timeout=60_000)
    try:
        page.wait_for_selector("[data-export]", timeout=20_000)
    except Exception:
        res.warnings.append("no [data-export] elements appeared")
        return res
    page.evaluate("document.fonts.ready")
    # The rig paints its SVG layers after mount; give the last frames a beat.
    page.wait_for_timeout(900)

    probe = page.evaluate(FONT_PROBE_JS, list(FONT_FAMILIES))
    for fam, m in probe.items():
        if abs(m["actual"] - m["fallback"]) < 0.5:
            raise SystemExit(
                f"FONT FALLBACK: '{fam}' did not load in {doc_path.name} — "
                f"refusing to export the kit in the wrong typeface."
            )
        # Space Mono is monospaced — its bold cut has identical advance widths
        # by design, so the width test cannot say anything about it.
        if fam != "Space Mono" and abs(m["bold"] - m["actual"]) < 0.5:
            res.warnings.append(f"{fam}: bold cut measured identical to regular")

    info = page.evaluate(MEASURE_JS)
    res.markers = info["markers"]
    res.missing_backdrops = set(missing)

    entries = []
    for el in info["els"]:
        eid = el["id"]
        if not eid or "{{" in eid:
            res.warnings.append(f"unexpanded template id {eid!r}")
            continue
        if eid in spec.exclude:
            res.skipped += 1
            continue
        route = spec.route_for(eid)
        k, how = pick_scale(el["w"], el["h"], route)
        rel = merge_path(route.target, eid)
        entries.append((eid, rel, k, how, el["w"], el["h"], el))

    if plan_only:
        for eid, rel, k, how, w, h, _el in entries:
            print(f"    {rel + '.png':58s} {w:7.1f}×{h:<7.1f} → {how}")
        res.written = len(entries)
        return res

    for eid, rel, k, how, w, h, el in entries:
        # `k` scales a frame's CSS size to its final *device* pixels, and the
        # context already renders at DEVICE_SCALE — so the clone only carries
        # the remainder, and the clip stays in CSS pixels.
        #
        # Snap that clip to whole CSS pixels and size the clone to match.
        # Without this a fractional CSS size (621×349.31 is typical) leaves
        # the last row and column half-covered, and the screenshot picks up a
        # 1px transparent seam around an otherwise opaque frame.
        css_k = k / DEVICE_SCALE
        clip_w, clip_h = round(w * css_k), round(h * css_k)
        if clip_w > VIEWPORT["width"] or clip_h > VIEWPORT["height"]:
            res.warnings.append(
                f"{eid}: {clip_w * DEVICE_SCALE:.0f}×{clip_h * DEVICE_SCALE:.0f} "
                f"exceeds the stage viewport — clipped")
            clip_w = min(clip_w, VIEWPORT["width"])
            clip_h = min(clip_h, VIEWPORT["height"])
        # Overscan by a pixel: browser layout quantises to 1/64 px, so a frame
        # sized to exactly the clip can still fall a hair short of covering
        # its last row. The extra pixel is painted outside the clip and never
        # reaches the file — it only guarantees full coverage inside it.
        got = page.evaluate(PREPARE_JS,
                            {"id": eid, "k": css_k,
                             "w": (clip_w + 1) / css_k, "h": (clip_h + 1) / css_k,
                             "cqType": el.get("cqType"), "cqRatio": el.get("cqRatio", 1),
                             "cqBg": el.get("cqBg")})
        if not got:
            res.warnings.append(f"{eid}: vanished before capture")
            continue
        dest = out_root / f"{rel}.png"
        dest.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(dest), omit_background=True,
                        clip={"x": 0, "y": 0, "width": clip_w, "height": clip_h})
        res.written += 1
        MANIFEST_ROWS.append({
            "id": eid,
            "path": str(dest.relative_to(ROOT)),
            "doc": doc_path.name,
            "scale": round(k, 4),
            "sizing": how,
        })
    return res


MANIFEST_ROWS: list[dict] = []


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #
def resolve_specs(only: str | None) -> list[tuple[DocSpec, Path]]:
    out: list[tuple[DocSpec, Path]] = []
    docs = sorted(KIT_SRC.glob("*.dc.html"))
    for spec in DOC_SPECS:
        matches = [d for d in docs if spec.doc in d.name]
        if not matches:
            print(f"  ! no document matches spec {spec.doc!r}", file=sys.stderr)
            continue
        if len(matches) > 1:
            # "Concepts" matches both Concepts and Restyle Concepts.
            exact = [d for d in matches if d.name == f"Dennis Kit - {spec.doc}.dc.html"]
            matches = exact or matches[:1]
        if only and only.lower() not in spec.doc.lower():
            continue
        out.append((spec, matches[0]))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--doc", help="only documents whose spec name contains this")
    ap.add_argument("--out", type=Path, default=KIT_OUT, help="output root (default assets/kit)")
    ap.add_argument("--list", action="store_true", help="print the plan, render nothing")
    ap.add_argument("--clean", action="store_true", help="delete the output root first")
    args = ap.parse_args()

    if not KIT_SRC.exists():
        print(f"design kit not found at {KIT_SRC}", file=sys.stderr)
        return 2
    for _fam, fn, _wt, _st in FONT_FACES:
        if not (FONT_DIR / fn).exists():
            print(f"missing font {FONT_DIR / fn}", file=sys.stderr)
            return 2
    for local in CDN_OVERRIDES.values():
        if not (ROOT / local).exists():
            print(f"missing vendored runtime {local} — see the header of this file", file=sys.stderr)
            return 2

    specs = resolve_specs(args.doc)
    if args.clean and args.out.exists() and not args.list:
        shutil.rmtree(args.out)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright is not installed — pip install -e '.[filings]'", file=sys.stderr)
        return 2

    base_url, srv = serve(ROOT)
    css = font_css(base_url)
    missing_uploads: set[str] = set()
    started = time.monotonic()
    results: list[DocResult] = []

    try:
        with sync_playwright() as p:
            from pipeline.filings import _chromium_executable  # noqa: PLC0415
            from config import Settings  # noqa: PLC0415

            exe = _chromium_executable(Settings(_env_file=None))
            browser = p.chromium.launch(headless=True, executable_path=exe)
            ctx = browser.new_context(viewport=VIEWPORT, device_scale_factor=DEVICE_SCALE)
            ctx.add_init_script(
                "window.__resources = "
                + json.dumps({k: f"{base_url}/{v}" for k, v in CDN_OVERRIDES.items()})
                + ";"
            )
            ctx.route("https://fonts.googleapis.com/**",
                      lambda route: route.fulfill(status=200, content_type="text/css", body=css))
            ctx.route("https://fonts.gstatic.com/**", lambda route: route.abort())
            # Anything still reaching for the network would make the export
            # non-reproducible; fail the run rather than ship a silent variant.
            ctx.route("https://unpkg.com/**", lambda route: route.abort())

            page = ctx.new_page()
            page.on("response", lambda r: (
                missing_uploads.add(r.url.rsplit("/", 1)[-1])
                if r.status == 404 and "/uploads/" in r.url else None))

            for spec, doc_path in specs:
                missing_uploads.clear()
                print(f"  {doc_path.name}")
                res = export_doc(page, base_url, spec, doc_path, args.out,
                                 missing_uploads, args.list)
                results.append(res)
                tail = f"  ({res.skipped} guide frames skipped)" if res.skipped else ""
                print(f"    → {res.written} frames{tail}")
                for w in res.warnings:
                    print(f"    ! {w}")
            browser.close()
    finally:
        srv.shutdown()

    total = sum(r.written for r in results)
    if args.list:
        print(f"\nplan: {total} frames across {len(results)} documents")
        return 0

    alpha_report = verify_and_manifest(args.out, results, started)
    print(f"\n{total} frames from {len(results)} documents "
          f"in {time.monotonic() - started:.0f}s → {args.out}")
    print(f"  {alpha_report['transparent']} transparent · "
          f"{alpha_report['opaque']} opaque · manifest {MANIFEST.relative_to(ROOT)}")
    for r in results:
        for w in r.warnings:
            print(f"  ! {r.doc}: {w}")

    degraded = sorted({b for r in results for b in r.missing_backdrops})
    if degraded:
        print("\n  ! the delivery did not include these backdrop images:")
        for b in degraded:
            print(f"      uploads/{b}")
        print("    Frames that use them fall back to flat paper (#f2f2ef), which is")
        print("    on-palette but loses the paper grain / room vignette. Drop the")
        print(f"    files into {KIT_SRC.relative_to(ROOT)}/uploads/ and re-run to fix.")
    return 0


# Compositing a frame at a fractional scale can leave its outermost pixels a
# level or two short of opaque. That is invisible, but it would make every
# frame look like it carries designed transparency — so anything this close to
# solid is flattened, and `alpha` in the manifest keeps meaning what it says.
NEAR_OPAQUE = 250


def verify_and_manifest(out_root: Path, results: list[DocResult], started: float) -> dict:
    """Re-open every PNG: record real pixel size and whether it carries alpha."""
    from PIL import Image

    transparent = opaque = 0
    for row in MANIFEST_ROWS:
        path = ROOT / row["path"]
        with Image.open(path) as im:
            row["w"], row["h"] = im.size
            floor = im.getchannel("A").getextrema()[0] if im.mode in ("RGBA", "LA") else 255
            if NEAR_OPAQUE <= floor < 255:
                im.convert("RGB").save(path)
                floor = 255
        row["alpha"] = floor < 255
        transparent += row["alpha"]
        opaque += not row["alpha"]

    # A marker promising transparency over frames that render their own paper
    # is a mismatch between the delivery note and the artwork. Surface it here
    # rather than quietly shipping either interpretation.
    by_doc: dict[str, list[bool]] = {}
    for row in MANIFEST_ROWS:
        by_doc.setdefault(row["doc"], []).append(row["alpha"])
    for r in results:
        alphas = by_doc.get(r.doc, [])
        promised = any("transparent" in m.lower() for m in r.markers)
        if promised and alphas and sum(alphas) < len(alphas) / 2:
            r.warnings.append(
                f"marker says transparent but {len(alphas) - sum(alphas)}/{len(alphas)} "
                f"frames paint their own background — exported as drawn")

    out_root.mkdir(parents=True, exist_ok=True)
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps({
        "generated_by": "scripts/export_design_kit.py",
        "source": str(KIT_SRC.relative_to(ROOT)),
        "seconds": round(time.monotonic() - started, 1),
        "documents": [
            {"doc": r.doc, "frames": r.written, "markers": r.markers,
             "missing_backdrops": sorted(r.missing_backdrops),
             "warnings": r.warnings}
            for r in results
        ],
        "assets": {row["id"] if "/" in row["id"] else row["path"]: row for row in MANIFEST_ROWS},
    }, indent=1, sort_keys=False) + "\n")
    return {"transparent": transparent, "opaque": opaque}


if __name__ == "__main__":
    raise SystemExit(main())
