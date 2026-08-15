#!/usr/bin/env python3
"""Measure how many characters each text destination actually holds.

    python scripts/measure_budgets.py            # rewrite templates/budgets.json
    python scripts/measure_budgets.py --check    # fail if the file has drifted

A budget that lives in a report drifts from the fitter within a month, and
then type overflows a box nobody is measuring. So it lives in
`templates/budgets.json`, it is produced by running the REAL fitter against
the REAL templates, and `tests/test_budgets.py` re-measures on every run and
fails if the two disagree.

The numbers are the reason the last format was scrapped: every field limit in
the script model is two to six times what its shot can physically show, so
the model wrote copy the renderer could only truncate. Under the writing form
these are the character budgets each field is given.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image  # noqa: E402

from pipeline import marks as mk  # noqa: E402
from pipeline.compose import build_layers  # noqa: E402
from pipeline.kit_manifest import kit_for  # noqa: E402
from pipeline.shots import (MIN_TYPE_FH, available_formats,  # noqa: E402
                            expand_sequences, load_format, resolve_spans)

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "templates" / "budgets.json"

# Prose with a realistic word-length distribution. Budgets measured on one
# long word or on "aaaa" would both be wrong: wrapping is what decides the
# answer, and wrapping depends on where the spaces are.
PROSE = ("revenue slipped again while margin held and guidance came in soft "
         "against a market that had already decided what it thought about "
         "the quarter before anyone read a single line of the filing").split()

STEP = 2          # characters per probe
CEILING = 320     # no destination in any format holds more than this


class _Filler:
    """A resolver that returns exactly `n` characters for anything asked."""

    def __init__(self, n: int) -> None:
        self.n = n

    def _text(self) -> str:
        out: list[str] = []
        i = 0
        while len(" ".join(out)) < self.n:
            out.append(PROSE[i % len(PROSE)])
            i += 1
        return " ".join(out)[:self.n]

    def text_for(self, src): return self._text()
    def image_for(self, src): return None
    def list_for(self, src): return [self._text()] * 4
    def frac_box_for(self, src): return None


class _Word:
    def __init__(self, w, a, b): self.word, self.start, self.end = w, a, b


def _lost_at(fmt, kit, frame, n: int) -> dict[str, int]:
    """Characters dropped per destination when every field carries `n`."""
    fw, fh = frame
    floor = max(12, int(MIN_TYPE_FH * fh))
    words = [_Word(f"w{i}", i * 0.3, i * 0.3 + 0.25) for i in range(240)]
    spans = resolve_spans(fmt, words, 72.0, {})
    result = build_layers(fmt, spans, _Filler(n), kit, "marker")
    canvas = Image.new("RGBA", (fw, fh))
    out: dict[str, int] = {}
    for l in result.layers:
        if l.kind not in ("text", "fill") or not l.text:
            continue
        if l.kind == "text":
            size = max(int(l.size_fh * fh), 12)
            lines = l.max_lines
            font = mk.DISPLAY_FONT if l.size_fh >= 0.06 else mk.BODY_FONT
        else:
            size = max(int(l.h * 0.34), 14)
            lines = max(1, int(l.h / (size * 1.18)))
            font = mk.DISPLAY_FONT
        *_b, lost = mk.draw_block(canvas, l.text, (l.x, l.y, l.w, l.h),
                                  font_name=font, size_px=size, color=(0, 0, 0, 255),
                                  max_lines=lines, min_px=floor)
        out[l.name.split(":", 1)[1]] = lost
    return out


def measure() -> dict:
    formats: dict[str, dict[str, int]] = {}
    for name in available_formats():
        fmt = expand_sequences(load_format(name), lambda src: ["a", "b", "c", "d"])
        kit = kit_for("marker")
        budgets: dict[str, int] = {}
        for n in range(STEP, CEILING + 1, STEP):
            for dest, lost in _lost_at(fmt, kit, fmt.frame, n).items():
                if lost == 0:
                    budgets[dest] = n
        formats[name] = dict(sorted(budgets.items()))
    return {
        "note": ("Characters each text destination holds with ZERO loss, "
                 "measured by running pipeline.marks.fit_lines against the "
                 "real templates. Regenerate with scripts/measure_budgets.py; "
                 "tests/test_budgets.py fails if this file and a fresh "
                 "measurement disagree."),
        "measured_with": {"font_body": mk.BODY_FONT, "font_display": mk.DISPLAY_FONT,
                          "min_type_fh": MIN_TYPE_FH, "step": STEP},
        "formats": formats,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true",
                    help="compare against the committed file instead of writing")
    args = ap.parse_args()

    fresh = measure()
    if not args.check:
        OUT.write_text(json.dumps(fresh, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {OUT.relative_to(REPO)}")
        for name, b in fresh["formats"].items():
            print(f"  {name}: {len(b)} destinations, "
                  f"{min(b.values())}-{max(b.values())} chars")
        return 0

    if not OUT.exists():
        print(f"FAILED — {OUT} does not exist. Run without --check.")
        return 1
    have = json.loads(OUT.read_text(encoding="utf-8"))
    if have.get("formats") == fresh["formats"]:
        print("OK — the committed budgets match a fresh measurement.")
        return 0
    print("FAILED — the budgets have drifted from the fitter:")
    for name in sorted(set(have.get("formats", {})) | set(fresh["formats"])):
        a = have.get("formats", {}).get(name, {})
        b = fresh["formats"].get(name, {})
        for dest in sorted(set(a) | set(b)):
            if a.get(dest) != b.get(dest):
                print(f"  {name}/{dest}: committed {a.get(dest)} "
                      f"-> measured {b.get(dest)}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
