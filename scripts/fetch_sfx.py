#!/usr/bin/env python3
"""Pull real, licence-clean sound effects into `assets/sfx/`.

The SFX taxonomy in `SFX_KEYS`, the gain staging and every cue that fires them
were already right. Only the FILES were fake: `scripts/gen_assets.py` builds
each one out of ffmpeg oscillators, so the "cash register" is a sine sweep.
That is the correct default for a repo that has to build and test offline, and
it is not something to publish.

This fetches the real thing from Freesound, which is the only large library
with a machine-readable licence per sound and a free API. Every file gets:

* **provenance**, in `assets/sfx/SOURCES.json` — the source URL, the licence
  and the author, so an attribution-required sound can actually be attributed
  and a licence can be re-checked later without guessing;
* **one peak**, normalised to `TARGET_PEAK_DBFS`, so swapping a placeholder
  for a real effect does not change the mix under it.

`gen_assets.py` keeps generating placeholders, so a checkout with no network
still renders and the suite still runs. The difference is that a placeholder
cannot be published: `pipeline.gates.check_audio` is a BLOCKING finding on a
final render outside MOCK_MODE, carried in the validation report the operator
approves from, and `pipeline.audio_assets.audio_banner` still labels the log.
Until this script has run, the block is what an operator sees.

    export FREESOUND_API_KEY=...
    python scripts/fetch_sfx.py             # every key that is still a placeholder
    python scripts/fetch_sfx.py --force     # re-fetch everything
    python scripts/fetch_sfx.py --dry-run   # show what it would take

Without a key it explains what to set and exits non-zero rather than silently
leaving the oscillators in place.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.audio_assets import (  # noqa: E402
    ROOM_TONE_NAME,
    TARGET_PEAK_DBFS,
    AudioSource,
    load_sources,
    save_sources,
)
from pipeline.models import SFX_KEYS  # noqa: E402

API = "https://freesound.org/apiv2"

# What to ask for, per key. The search terms matter: "buzzer" alone returns
# klaxons, and the deadpan set is meant to be the room rather than a
# punchline, so those ask for quiet and dry.
QUERIES: dict[str, str] = {
    "windows_error": "windows error beep alert chime",
    "cash_register": "cash register ka-ching receipt",
    "record_scratch": "vinyl record scratch stop",
    "sad_trombone": "sad trombone wah wah fail",
    "camera_shutter": "camera shutter click dslr",
    "vine_boom": "boom impact bass hit short",
    "coffee_slurp": "coffee sip slurp mug quiet",
    "keyboard_clack": "mechanical keyboard single keypress dry",
    "paper_rustle": "paper page turn rustle quiet",
    "buzzer": "buzzer wrong answer short dry",
    "ding": "small bell ding single soft",
    # not in SFX_KEYS but fired by the renderers
    "whoosh": "whoosh transition swish short",
    "sting": "short musical sting accent",
    "pop": "pop bubble click short",
}

# The room bed. Not an effect — a continuous low hum that runs under the whole
# video, so the audio between words is a room rather than digital silence.
ROOM_QUERY = "room tone ambience quiet office hum"

# Licences that need no attribution to publish, preferred first. An
# attribution licence is still accepted — the sidecar records the author so
# the credit can actually be given — but CC0 is less to get wrong.
LICENCE_ORDER = ("Creative Commons 0", "Attribution", "Attribution NonCommercial")

MAX_SECONDS = 4.0        # an effect longer than this is a recording, not a cue
ROOM_MAX_SECONDS = 60.0


def _key() -> str | None:
    return os.environ.get("FREESOUND_API_KEY") or os.environ.get("FREESOUND_TOKEN")


def search(query: str, token: str, *, max_s: float) -> dict | None:
    """The best licence-clean hit for `query`, or None."""
    import httpx

    params = {
        "query": query,
        "filter": f"duration:[0.1 TO {max_s}]",
        "fields": "id,name,username,license,previews,duration",
        "page_size": 30,
        "token": token,
    }
    try:
        r = httpx.get(f"{API}/search/text/", params=params, timeout=30)
        r.raise_for_status()
    except Exception as exc:  # noqa: BLE001 — one failed key is not fatal
        print(f"  search failed: {exc}", file=sys.stderr)
        return None
    results = (r.json() or {}).get("results") or []

    def rank(hit: dict) -> tuple:
        lic = str(hit.get("license", ""))
        for i, name in enumerate(LICENCE_ORDER):
            if name.lower() in lic.lower():
                return (i, hit.get("duration", 99))
        return (len(LICENCE_ORDER), hit.get("duration", 99))

    ranked = sorted(results, key=rank)
    for hit in ranked:
        lic = str(hit.get("license", ""))
        if any(n.lower() in lic.lower() for n in LICENCE_ORDER):
            return hit
    return None


def download(hit: dict, dest: Path) -> bool:
    """Fetch the preview and normalise it to the shared peak."""
    import httpx

    url = (hit.get("previews") or {}).get("preview-hq-mp3")
    if not url:
        return False
    with tempfile.TemporaryDirectory(prefix="sfx_") as td:
        raw = Path(td) / "raw.mp3"
        try:
            with httpx.stream("GET", url, timeout=60, follow_redirects=True) as r:
                r.raise_for_status()
                with raw.open("wb") as fh:
                    for chunk in r.iter_bytes():
                        fh.write(chunk)
        except Exception as exc:  # noqa: BLE001
            print(f"  download failed: {exc}", file=sys.stderr)
            return False
        return normalise(raw, dest)


def normalise(src: Path, dest: Path) -> bool:
    """One peak for every cue, so the mix under them never has to move."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
        "-af", f"loudnorm=I=-18:TP={TARGET_PEAK_DBFS}:LRA=11,"
               f"alimiter=limit={10 ** (TARGET_PEAK_DBFS / 20):.4f}",
        "-ac", "1", "-ar", "44100", "-c:a", "pcm_s16le", str(dest),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"  normalise failed: {exc}", file=sys.stderr)
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=ROOT / "assets" / "sfx")
    ap.add_argument("--force", action="store_true",
                    help="re-fetch keys that already have a real file")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--room-tone", action="store_true", default=True,
                    help="also fetch the continuous room bed (default on)")
    args = ap.parse_args(argv)

    out: Path = args.out
    known = load_sources(out)
    wanted = list(QUERIES)
    todo = [k for k in wanted
            if args.force or known.get(f"{k}.wav") is None
            or known[f"{k}.wav"].generated]

    print(f"target      : {out}")
    print(f"keys        : {len(wanted)} known, {len(todo)} still placeholders")
    if args.room_tone:
        rt = known.get(ROOM_TONE_NAME)
        if args.force or rt is None or rt.generated:
            print(f"room tone   : {ROOM_TONE_NAME} will be fetched")
    if args.dry_run:
        for k in todo:
            print(f"  would fetch {k:16s} <- {QUERIES[k]!r}")
        return 0

    token = _key()
    if not token:
        print(
            "No Freesound API key.\n"
            "  1. Sign in at https://freesound.org and create an API key at\n"
            "     https://freesound.org/apiv2/apply/\n"
            "  2. export FREESOUND_API_KEY=<the key>\n"
            "  3. re-run this script\n"
            "\nUntil then `scripts/gen_assets.py` keeps the synthesised "
            "placeholders in place — the suite runs offline, and every render "
            "logs that the audio is not real.", file=sys.stderr)
        return 2

    try:
        import httpx  # noqa: F401
    except ImportError:
        print("httpx is not installed — pip install -e '.[dev]'", file=sys.stderr)
        return 2

    fetched = 0
    for key in todo:
        print(f"  {key} ...", end=" ", flush=True)
        hit = search(QUERIES[key], token, max_s=MAX_SECONDS)
        if hit is None:
            print("no licence-clean result")
            continue
        dest = out / f"{key}.wav"
        backup = dest.with_suffix(".wav.placeholder")
        if dest.exists() and not backup.exists():
            shutil.copy2(dest, backup)      # keep the offline fallback
        if not download(hit, dest):
            print("failed")
            continue
        known[dest.name] = AudioSource(
            name=dest.name,
            source=f"https://freesound.org/s/{hit.get('id')}/",
            licence=str(hit.get("license", "")),
            author=str(hit.get("username", "")),
            generated=False,
        )
        fetched += 1
        print(f"ok  ({hit.get('license', '?')}, {hit.get('username', '?')})")

    if args.room_tone:
        rt = known.get(ROOM_TONE_NAME)
        if args.force or rt is None or rt.generated:
            print(f"  {ROOM_TONE_NAME} ...", end=" ", flush=True)
            hit = search(ROOM_QUERY, token, max_s=ROOM_MAX_SECONDS)
            if hit is not None and download(hit, out / ROOM_TONE_NAME):
                known[ROOM_TONE_NAME] = AudioSource(
                    name=ROOM_TONE_NAME,
                    source=f"https://freesound.org/s/{hit.get('id')}/",
                    licence=str(hit.get("license", "")),
                    author=str(hit.get("username", "")),
                    generated=False,
                )
                fetched += 1
                print("ok")
            else:
                print("not found")

    path = save_sources(out, known)
    still = [k for k in wanted
             if known.get(f"{k}.wav") is None or known[f"{k}.wav"].generated]
    print()
    print(f"fetched     : {fetched}")
    print(f"provenance  : {path}")
    print(f"still fake  : {len(still)}" + (f" — {', '.join(still)}" if still else ""))
    attribution = [s for s in known.values()
                   if s.real and "attribution" in s.licence.lower()]
    if attribution:
        print(f"ATTRIBUTION REQUIRED for {len(attribution)} file(s):")
        for s in attribution:
            print(f"   {s.name:20s} {s.author}  {s.source}")
    return 0 if not still else 1


if __name__ == "__main__":
    raise SystemExit(main())
