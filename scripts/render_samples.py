"""Render the sample MP4s from fixtures (MOCK_MODE, zero network).

Usage:  .venv/bin/python scripts/render_samples.py [short|long|all]

Outputs to samples/ at the repo root: full-spec Dennis renders driven
end-to-end by mock TTS timestamps — the SHORT "Noise or signal?"
template and the LONG deadpan deep-dive.
"""

from __future__ import annotations

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


# Every 9:16 format and the fixture it is built from. A format with no
# committed sample is a format whose hold numbers cannot be checked against
# an artefact — an evidence frame is a still, and a still cannot show a hold.
VERTICAL_SAMPLES = {
    "short": "short_valid",
    "earnings": "earnings_valid",
    "macro": "macro_valid",
}


def render_vertical_sample(format_name: str = "short") -> Path:
    from pipeline.render_short import render_short

    settings = _settings()
    fixture = VERTICAL_SAMPLES[format_name]
    raw = (ROOT / "fixtures" / "scripts" / f"{fixture}.json").read_text(encoding="utf-8")
    script, warnings = parse_short_script(raw, settings)
    for w in warnings:
        print(f"  warning: {w}")
    tts = TTSEngine(settings).synthesize(script.audio_script, "short")
    print(f"  mock audio: {tts.duration_s:.1f}s, {len(tts.words)} words")
    ws = WORK / script.ticker / f"sample_{format_name}"
    ws.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    out, manifest = render_short(script, tts, ws, settings,
                                 format_name=format_name,
                                 out_name=f"{format_name}_final.mp4")
    print(f"  rendered in {time.time() - t0:.0f}s")
    SAMPLES.mkdir(exist_ok=True)
    stem = ("sample_short_EXMPL" if format_name == "short"
            else f"sample_{format_name}_{script.ticker}")
    dest = SAMPLES / f"{stem}.mp4"
    shutil.copy(out, dest)
    shutil.copy(manifest, SAMPLES / f"{stem}.manifest.json")
    return dest


def render_short_sample() -> Path:
    return render_vertical_sample("short")


def _long_inputs():
    """Script, workspace and data export for the deep-dive fixture.

    Shared by both long renderers so the two are driven by identical inputs
    and any difference between them is the composition, not the fixture.
    """
    from pipeline.company_data import load_company_data
    from pipeline.parser_long import parse_long_script

    settings = _settings()
    # a denser, purpose-built deep-dive that showcases the kit (charts,
    # doodles, scribbles, memes); long_valid.txt stays the parser fixture
    raw = (ROOT / "fixtures" / "scripts" / "long_sample.txt").read_text(encoding="utf-8")
    script, warnings = parse_long_script(raw, "EXMPL", settings)
    for w in warnings:
        print(f"  warning: {w}")
    ws = WORK / "EXMPL" / "sample"
    ws.mkdir(parents=True, exist_ok=True)
    # the two-sheet data export feeds [CHART] + the corner bug's as-of
    shutil.copy(ROOT / "fixtures" / "company_data" / "dennis_data.xlsx",
                ws / "dennis_data.xlsx")
    data = load_company_data(ws)
    # the fixture references one filing screenshot — synthesize it (the
    # renderer adds the generic "FROM THE 10-K" chip; no vendor anywhere)
    shot = ws / "income_statement.png"
    if not shot.exists():
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (1600, 900), (16, 20, 28))
        d = ImageDraw.Draw(img)
        for y in range(80, 860, 52):
            d.line([40, y, 1560, y], fill=(46, 54, 66), width=1)
        d.text((60, 30), "EXMPL — Income Statement (mock screenshot)",
               fill=(210, 214, 220))
        d.text((60, 120), "Revenue TTM            496,000,000   (+1.0% YoY)", fill=(210, 214, 220))
        d.text((60, 172), "Net income TTM         -89,000,000   (margin -18%)", fill=(235, 90, 90))
        img.save(shot)
    tts = TTSEngine(settings).synthesize(script.narration, "long")
    print(f"  mock audio: {tts.duration_s:.1f}s, {len(tts.words)} words")
    return settings, script, ws, data, tts


def render_long_sample() -> Path:
    from pipeline.broll import ContentManager
    from pipeline.render_long import render_long

    settings, script, ws, data, tts = _long_inputs()
    t0 = time.time()
    out, manifest = render_long(script, tts, ws, settings,
                                content=ContentManager(settings),
                                as_of=str(data.get("as_of_date") or ""),
                                company_data=data)
    print(f"  rendered in {time.time() - t0:.0f}s")
    SAMPLES.mkdir(exist_ok=True)
    dest = SAMPLES / "sample_long_EXMPL.mp4"
    shutil.copy(out, dest)
    shutil.copy(manifest, SAMPLES / "sample_long_EXMPL.manifest.json")
    return dest


def render_long_shots_sample() -> Path:
    """The LONG through the shot engine — nine chapters, one compositor."""
    from pipeline.broll import ContentManager
    from pipeline.render_long_shots import render_long_shots

    settings, script, ws, data, tts = _long_inputs()
    t0 = time.time()
    out, manifest = render_long_shots(script, tts, ws, settings,
                                      content=ContentManager(settings),
                                      company_data=data,
                                      out_name="long_shots_final.mp4")
    print(f"  rendered in {time.time() - t0:.0f}s")
    SAMPLES.mkdir(exist_ok=True)
    dest = SAMPLES / "sample_long_shots_EXMPL.mp4"
    shutil.copy(out, dest)
    shutil.copy(manifest, SAMPLES / "sample_long_shots_EXMPL.manifest.json")
    return dest


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    for name in VERTICAL_SAMPLES:
        if what in (name, "vertical", "all"):
            print(f"{name.upper()} sample:")
            print(" ->", render_vertical_sample(name))
    if what in ("long-shots", "all"):
        print("LONG sample (shot engine):")
        print(" ->", render_long_shots_sample())
    if what == "long":
        print("LONG sample (old renderer):")
        print(" ->", render_long_sample())
