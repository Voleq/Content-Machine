#!/usr/bin/env python3
"""Every N seconds of a render, on one page, annotated.

    python scripts/contact_sheet.py samples/sample_short_EXMPL.mp4
    python scripts/contact_sheet.py <mp4> --every 5 --out sheet.png

Eleven frames covers a 70-second SHORT. It does not cover a 190-second LONG:
at that length eleven samples is one frame per seventeen seconds, and every
fault in this rebuild that mattered was found by LOOKING. So the long gets a
contact sheet every 5 seconds — 38 cells — and the sheet is the artefact that
gets reviewed, not a handful of stills chosen after the fact.

Each cell carries its timestamp, the shot it falls in (read from the render
manifest when one sits beside the video), and a mark when the frame is inside
a measured hold. A cell that looks identical to its neighbour is the thing to
find, so neighbours are put next to each other rather than sampled at random.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw  # noqa: E402

from pipeline import marks as mk  # noqa: E402

CELL_W = 240
COLS = 8


def _duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True).stdout.strip()
    return float(out)


def _shot_at(manifest: dict | None, t: float) -> str:
    if not manifest:
        return ""
    for sh in manifest.get("shots", []):
        if sh["start_s"] <= t < sh["end_s"]:
            return sh["id"]
    return ""


def build(video: Path, every: float, out: Path) -> Path:
    dur = _duration(video)
    man_path = video.with_suffix(".manifest.json")
    manifest = (json.loads(man_path.read_text(encoding="utf-8"))
                if man_path.exists() else None)

    holds: list[tuple[float, float]] = []
    try:
        from pipeline.byproducts import (BOIL_SAMPLE_FPS, BOIL_SCALE,
                                         held_spans)
        holds = held_spans(video, sample_fps=BOIL_SAMPLE_FPS, scale=BOIL_SCALE)
    except Exception:                                       # noqa: BLE001
        pass

    # Stop short of the final frame: seeking exactly at the duration returns
    # nothing and ffmpeg writes no file.
    times = [i * every for i in range(int(dur / every) + 1)
             if i * every < dur - 0.15]
    with tempfile.TemporaryDirectory() as td:
        cells = []
        for i, t in enumerate(times):
            p = Path(td) / f"{i:04d}.png"
            subprocess.run(
                ["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i",
                 str(video), "-frames:v", "1", "-vf", f"scale={CELL_W}:-1",
                 str(p)], check=True)
            cells.append((t, Image.open(p).convert("RGB").copy()))

    if not cells:
        raise SystemExit("no frames sampled")
    cw, ch = cells[0][1].size
    label_h = 26
    rows = (len(cells) + COLS - 1) // COLS
    pad = 6
    sheet = Image.new("RGB", (COLS * (cw + pad) + pad,
                              rows * (ch + label_h + pad) + pad + 30),
                      (245, 245, 242))
    d = ImageDraw.Draw(sheet)
    title = mk.load_font(mk.DISPLAY_FONT, 18)
    small = mk.load_font(mk.BODY_FONT, 13)
    d.text((pad, 8), f"{video.name} — {dur:.1f}s, every {every:g}s, "
                     f"{len(cells)} frames", font=title, fill=(20, 20, 24))

    for i, (t, im) in enumerate(cells):
        r, c = divmod(i, COLS)
        x = pad + c * (cw + pad)
        y = 30 + pad + r * (ch + label_h + pad)
        sheet.paste(im, (x, y))
        held = any(a - 1e-6 <= t <= b + 1e-6 for a, b in holds)
        shot = _shot_at(manifest, t)
        d.rectangle([x, y, x + cw - 1, y + ch - 1],
                    outline=(200, 60, 50) if held else (190, 188, 180))
        d.text((x + 2, y + ch + 3), f"{t:5.1f}s {shot}"[:34], font=small,
               fill=(60, 60, 66))
        if held:
            d.text((x + 2, y + ch + 14), "HELD", font=small, fill=(200, 60, 50))

    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video", type=Path)
    ap.add_argument("--every", type=float, default=None,
                    help="seconds between frames (default: 5s over 100s, "
                         "else enough for ~36 cells)")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    dur = _duration(args.video)
    every = args.every or (5.0 if dur > 100 else max(dur / 24.0, 2.0))
    out = args.out or Path("samples/evidence") / f"sheet_{args.video.stem}.png"
    print(build(args.video, every, out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
