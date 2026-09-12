#!/usr/bin/env python3
"""Does the audio in this checkout let a final render proceed? (P0b / P5)

`assets/sfx/` ships fifteen ffmpeg oscillators built by `gen_assets.py`.
That is the right default for a repo that has to build and test offline, and
it is not something to publish: `pipeline.gates.check_audio` reports every
file with no provenance entry as a placeholder and BLOCKS any final render
outside MOCK_MODE.

The gate is PER FILE. Fetching the room bed alone leaves fourteen blockers,
which is the thing most likely to be misread as "the fix did not work".

    python scripts/check_sfx.py

Exit 0 when every audio file carries provenance and a final render can go
ahead. Exit 1 with the list when it cannot. No network.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    from config import get_settings
    from pipeline.audio_assets import SIDECAR_NAME, load_sources
    from pipeline.audio_assets import generated_audio

    settings = get_settings()
    sfx = settings.assets_dir / "sfx"
    print(f"sfx directory : {sfx}")
    if not sfx.is_dir():
        print("\nMISSING — there is no sfx directory at all. Run "
              "`python scripts/gen_assets.py` for the offline placeholders, "
              "then `scripts/fetch_sfx.py` for the real thing.",
              file=sys.stderr)
        return 1

    known = load_sources(sfx)
    files = [p.name for p in sorted(sfx.iterdir())
             if p.suffix.lower() in (".wav", ".mp3", ".m4a", ".ogg")]
    placeholders = generated_audio(settings)
    print(f"sidecar       : {sfx / SIDECAR_NAME}"
          f"{'' if (sfx / SIDECAR_NAME).is_file() else '  (MISSING)'}")
    print(f"audio files   : {len(files)}")
    print(f"attributed    : {len(files) - len(placeholders)}")
    print(f"placeholders  : {len(placeholders)}")

    attribution = [s for s in known.values()
                   if s.real and "attribution" in s.licence.lower()]
    if attribution:
        print(f"\nATTRIBUTION REQUIRED for {len(attribution)} file(s) — these "
              f"belong in the video description:")
        for s in sorted(attribution, key=lambda x: x.name):
            print(f"  {s.name:20s} {s.author}  {s.source}")

    if not placeholders:
        print("\nPASS — every sound file carries provenance. `check_audio` "
              "will not block a final render.")
        return 0

    print(f"\nBLOCKED — {len(placeholders)} file(s) are synthesised "
          f"placeholders, so every FINAL render outside MOCK_MODE is refused "
          f"by `pipeline.gates.check_audio`:", file=sys.stderr)
    for name in placeholders:
        print(f"  {name}", file=sys.stderr)
    print("\nTo fix:\n"
          "  export FREESOUND_API_KEY=<your key from "
          "https://freesound.org/apiv2/apply/>\n"
          "  python scripts/fetch_sfx.py\n"
          "  python scripts/check_sfx.py\n\n"
          "Do NOT hand-write `generated: false` into the sidecar for a file "
          "that is still an oscillator. The gate exists to keep a synthesised "
          "cash register out of a published video; editing the sidecar around "
          "it publishes the oscillator and removes the only warning.",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
