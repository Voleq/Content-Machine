"""Render the sample MP4s from fixtures (MOCK_MODE, zero network).

Usage:  .venv/bin/python scripts/render_samples.py [short|long|all]

Outputs to samples/ at the repo root. These are the §13 deliverable
artifacts: full-spec renders driven end-to-end by mock TTS timestamps.
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import Settings  # noqa: E402
from pipeline.parser_short import parse_short_script  # noqa: E402
from pipeline.tts import TTSEngine  # noqa: E402

SAMPLES = ROOT / "samples"
WORK = ROOT / "workspace"


def _settings() -> Settings:
    s = Settings(MOCK_MODE=True, _env_file=None)
    s.ensure_runtime_dirs()
    if not s.mock_mode:
        raise SystemExit("refusing to render samples outside MOCK_MODE")
    return s


def render_short_sample() -> Path:
    from pipeline.render_short import render_short

    settings = _settings()
    raw = (ROOT / "fixtures" / "scripts" / "short_valid.json").read_text()
    script, warnings = parse_short_script(raw, settings)
    for w in warnings:
        print(f"  warning: {w}")
    tts = TTSEngine(settings).synthesize(script.audio_script, "short")
    print(f"  mock audio: {tts.duration_s:.1f}s, {len(tts.words)} words")
    ws = WORK / script.ticker / "sample"
    ws.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    out, manifest = render_short(script, tts, ws, settings)
    print(f"  rendered in {time.time() - t0:.0f}s")
    SAMPLES.mkdir(exist_ok=True)
    dest = SAMPLES / "sample_short_EXMPL.mp4"
    shutil.copy(out, dest)
    shutil.copy(manifest, SAMPLES / "sample_short_EXMPL.manifest.json")
    return dest


def render_long_sample() -> Path:
    from pipeline.broll import BrollManager
    from pipeline.parser_long import parse_long_script
    from pipeline.render_long import render_long

    settings = _settings()
    raw = (ROOT / "fixtures" / "scripts" / "long_valid.txt").read_text()
    script, warnings = parse_long_script(raw, "EXMPL", settings)
    for w in warnings:
        print(f"  warning: {w}")
    ws = WORK / "EXMPL" / "sample"
    ws.mkdir(parents=True, exist_ok=True)
    # the fixture references one Refinitiv screenshot — synthesize it
    shot = ws / "income_statement.png"
    if not shot.exists():
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (1600, 900), (16, 20, 28))
        d = ImageDraw.Draw(img)
        for y in range(80, 860, 52):
            d.line([40, y, 1560, y], fill=(46, 54, 66), width=1)
        d.text((60, 30), "REFINITIV  |  EXMPL.O  Income Statement (mock screenshot)",
               fill=(210, 214, 220))
        d.text((60, 120), "Revenue TTM            496,000,000   (+1.0% YoY)", fill=(210, 214, 220))
        d.text((60, 172), "Net income TTM         -89,000,000   (margin -18%)", fill=(235, 90, 90))
        img.save(shot)
    tts = TTSEngine(settings).synthesize(script.narration, "long")
    print(f"  mock audio: {tts.duration_s:.1f}s, {len(tts.words)} words")
    broll = BrollManager(settings)
    t0 = time.time()
    out, manifest = render_long(script, tts, ws, settings, broll=broll, draft=False)
    print(f"  rendered in {time.time() - t0:.0f}s")
    SAMPLES.mkdir(exist_ok=True)
    dest = SAMPLES / "sample_long_EXMPL.mp4"
    shutil.copy(out, dest)
    shutil.copy(manifest, SAMPLES / "sample_long_EXMPL.manifest.json")
    return dest


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    if what in ("short", "all"):
        print("SHORT sample:")
        print(" ->", render_short_sample())
    if what in ("long", "all"):
        print("LONG sample:")
        print(" ->", render_long_sample())
