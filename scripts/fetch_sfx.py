#!/usr/bin/env python3
"""Pull real CC0 sound effects into `assets/sfx/`.

The SFX taxonomy in `SFX_KEYS`, the gain staging and every cue that fires them
were already right. Only the FILES were fake: `scripts/gen_assets.py` builds
each one out of ffmpeg oscillators, so the "cash register" is a sine sweep.
That is the correct default for a repo that has to build and test offline, and
it is not something to publish.

This fetches the real thing from Freesound, which is the only large library
with a machine-readable licence per sound and a free API. Every file gets:

* **provenance**, in `assets/sfx/SOURCES.json` — the source URL, the licence
  and the author, so a licence can be re-checked later without guessing;
* **one peak**, normalised to `TARGET_PEAK_DBFS`, so swapping a placeholder
  for a real effect does not change the mix under it.

Only CC0 is taken. The channel is built to be monetised, which is commercial
use, so a NonCommercial sound cannot be played at all, and an Attribution one
would owe a credit in every video that plays it, which no upload carries.
Commit `assets/sfx/` after a run: the files and `SOURCES.json` are what every
checkout, CI included, reads the gate from.

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

The room bed is ON by default (`--room-tone` is `store_true, default=True`),
so passing it explicitly changes nothing. It is also not the whole job: the
audio gate is PER FILE, so fixing room tone alone leaves the other fourteen
blocking. This script exits non-zero until every audio file in the target
directory carries provenance.

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
    AUDIO_SUFFIXES,
    ROOM_TONE_NAME,
    SIDECAR_NAME,
    TARGET_PEAK_DBFS,
    AudioSource,
    is_cc0,
    load_sources,
    save_sources,
)
from pipeline.models import SFX_KEYS  # noqa: E402
from pipeline.sound import EFFECT_KEYS, variant_names  # noqa: E402

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
    # not in SFX_KEYS: the machine fires these off structure
    # (`pipeline/sound.py`). The swish on every cut, and the hit on a short's
    # first frame, its payoff and every chapter change of the long.
    "whoosh": "whoosh transition swish short",
    "impact": "cinematic impact hit low punch short",
    # One per design move, fetched now so this one run gets everything; the
    # renderer plays them once the moves are wired (`sound.MOVE_SOUNDS`).
    "tick_roll": "fast mechanical ratchet ticking counter short",
    "marker_draw": "marker pen writing on paper stroke short",
    "marker_circle": "marker pen circling scribble on paper",
    "knock": "soft single knock wood tap dry",
    "pin_tap": "push pin into cork board tap",
    "flip": "flip clock card flap mechanical single",
    "sting": "short musical sting accent",
    "pop": "pop bubble click short",
}

# Every effect the renderers fire gets this many takes: `key.wav`, `key-2.wav`,
# `key-3.wav`. One file played on every cut is what makes a video sound
# assembled; `sound.Voicing` never plays the same take twice running.
VARIANTS = 3

# The room bed. Not an effect — a continuous low hum that runs under the whole
# video, so the audio between words is a room rather than digital silence.
ROOM_QUERY = "room tone ambience quiet office hum"

# The room at each hour, and what plays under a shot that shows rain, snow or
# a flickering screen (`sound.ROOM_BY_HOUR`, `sound.SET_LAYERS`). Loops, so a
# take has to be long enough to loop without the seam being the loudest thing
# in it.
AMBIENCE_QUERIES: dict[str, str] = {
    "room_night": "quiet room at night ambience radiator hum",
    "room_dusk": "quiet room evening ambience distant city traffic window",
    "rain_window": "rain on window glass indoor ambience",
    "winter_room": "quiet winter indoor ambience wind outside muffled",
    "screen_buzz": "crt monitor electrical hum faint",
}

# CC0 only (see the module docstring). The filter takes the licence's NAME,
# but the `license` field of a result is its deed URL — the API serialises
# `license.deed_url` — so the licence is read off each hit by `is_cc0`, which
# knows both. This used to match names against that field, which matched
# nothing: every key came back "no licence-clean result" and the gate could
# not be cleared.
CC0_FILTER = 'license:"Creative Commons 0"'

MAX_SECONDS = 4.0        # an effect longer than this is a recording, not a cue
ROOM_MAX_SECONDS = 60.0
AMBIENCE_MIN_SECONDS = 8.0   # shorter than this loops audibly
LOOP_SECONDS = 30.0          # what a loop is cut to, seam crossfaded
LOOP_SEAM_SECONDS = 1.0


def wanted() -> list[tuple[str, str, str, float, bool]]:
    """Every file this fetch fills: `(file, key, query, max_s, loop)`.

    The room tone is not here; `--room-tone` owns it, as it always has.
    """
    out: list[tuple[str, str, str, float, bool]] = []
    for key, query in QUERIES.items():
        n = VARIANTS if key in EFFECT_KEYS else 1
        for name in variant_names(key, n):
            out.append((name, key, query, MAX_SECONDS, False))
    for key, query in AMBIENCE_QUERIES.items():
        out.append((f"{key}.wav", key, query, ROOM_MAX_SECONDS, True))
    return out


def _key() -> str | None:
    return os.environ.get("FREESOUND_API_KEY") or os.environ.get("FREESOUND_TOKEN")


def search(query: str, token: str, *, max_s: float,
           min_s: float = 0.1) -> dict | None:
    """The most relevant CC0 hit for `query`, or None."""
    hits = search_many(query, token, max_s=max_s, min_s=min_s, n=1)
    return hits[0] if hits else None


def search_many(query: str, token: str, *, max_s: float, min_s: float = 0.1,
                n: int = 1) -> list[dict]:
    """Up to `n` CC0 hits for `query`, most relevant first.

    Asks for CC0 outright, then, if that filter is refused or turns up nothing,
    once more without it, picking CC0 out of the answer here. So a filter the
    API reads differently costs one request rather than every sound.
    """
    import httpx

    duration = f"duration:[{min_s} TO {max_s}]"
    failures: list[Exception] = []
    for flt in (f"{duration} {CC0_FILTER}", duration):
        params = {
            "query": query,
            "filter": flt,
            "fields": "id,name,username,license,previews,duration",
            "page_size": 30,
            "token": token,
        }
        try:
            r = httpx.get(f"{API}/search/text/", params=params, timeout=30)
            r.raise_for_status()
            results = (r.json() or {}).get("results") or []
        except Exception as exc:  # noqa: BLE001 — one failed key is not fatal
            failures.append(exc)
            continue
        # Freesound's relevance order, not the shortest hit: the shortest
        # record scratch or sad trombone under the cap is a fragment of one.
        hits = [h for h in results if is_cc0(h.get("license", ""))]
        if hits:
            return hits[:n]
    if len(failures) == 2:
        print(f"  search failed: {failures[-1]}", file=sys.stderr)
    return []


def download(hit: dict, dest: Path, *, loop: bool = False) -> bool:
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
        return normalise(raw, dest, loop=loop)


def normalise(src: Path, dest: Path, *, loop: bool = False) -> bool:
    """One peak for every cue, so the mix under them never has to move.

    A LOOP is also cut to `LOOP_SECONDS` with its seam crossfaded: the take
    starts one seam in, and its last second fades into its first, so when
    the renderer plays it round again the join is a continuation rather than
    a click and a jump in the rain.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    level = (f"loudnorm=I=-18:TP={TARGET_PEAK_DBFS}:LRA=11,"
             f"alimiter=limit={10 ** (TARGET_PEAK_DBFS / 20):.4f}")
    if loop:
        d, total = LOOP_SEAM_SECONDS, LOOP_SECONDS + LOOP_SEAM_SECONDS
        graph = (f"[0:a]atrim=0:{total},asplit[a][b];"
                 f"[a]atrim=start={d},asetpts=PTS-STARTPTS[body];"
                 f"[b]atrim=0:{d},asetpts=PTS-STARTPTS[head];"
                 f"[body][head]acrossfade=d={d}:c1=tri:c2=tri,{level}[out]")
        af = ["-filter_complex", graph, "-map", "[out]"]
    else:
        af = ["-af", level]
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
        *af, "-ac", "1", "-ar", "44100", "-c:a", "pcm_s16le", str(dest),
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
    files = wanted()
    todo = [w for w in files
            if args.force or known.get(w[0]) is None or known[w[0]].generated]

    print(f"target      : {out}")
    print(f"files       : {len(files)} known, {len(todo)} still to fetch")
    if args.room_tone:
        rt = known.get(ROOM_TONE_NAME)
        if args.force or rt is None or rt.generated:
            print(f"room tone   : {ROOM_TONE_NAME} will be fetched")
    if args.dry_run:
        for name, _key, query, _max_s, _loop in todo:
            print(f"  would fetch {name:20s} <- {query!r}")
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
    # One search per KEY, however many of its takes are missing: the takes
    # are the next most relevant CC0 hits, never one already on disk.
    by_key: dict[str, list[tuple[str, str, str, float, bool]]] = {}
    for w in todo:
        by_key.setdefault(w[1], []).append(w)
    for key, need in by_key.items():
        _name, _key, query, max_s, loop = need[0]
        takes = sum(1 for w in files if w[1] == key)
        hits = search_many(query, token, max_s=max_s, n=takes + len(need),
                           min_s=AMBIENCE_MIN_SECONDS if loop else 0.1)
        held = {known[w[0]].source for w in files
                if w[1] == key and w not in need and known.get(w[0])}
        hits = [h for h in hits
                if f"https://freesound.org/s/{h.get('id')}/" not in held]
        for name, *_ in need:
            print(f"  {name} ...", end=" ", flush=True)
            if not hits:
                print("no CC0 result")
                continue
            hit = hits.pop(0)
            dest = out / name
            backup = dest.with_suffix(".wav.placeholder")
            if dest.exists() and not backup.exists():
                shutil.copy2(dest, backup)      # keep the offline fallback
            if not download(hit, dest, loop=loop):
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
    # WHAT THE GATE WILL SEE, not what this script set out to fetch.
    #
    # `still` used to be computed over `QUERIES` alone — fourteen keys — while
    # `check_audio` reads the DIRECTORY and counts any file without a
    # provenance entry as a placeholder. `room_tone.wav` is not a query key,
    # so a run where every effect downloaded and the room bed did not exited
    # 0 and left every final render blocked, with nothing connecting the two.
    # The same is true of any file an operator drops in by hand.
    #
    # So this asks the gate's own question, of the gate's own directory.
    unattributed = _unattributed(out, known)
    print()
    print(f"fetched     : {fetched}")
    print(f"provenance  : {path}")
    # Only a file added by hand can land here, since the fetch takes CC0.
    attribution = [s for s in known.values()
                   if s.real and not is_cc0(s.licence)]
    if attribution:
        print(f"ATTRIBUTION REQUIRED for {len(attribution)} file(s) that are "
              f"not CC0 (a NonCommercial one cannot be played at all):")
        for s in attribution:
            print(f"   {s.name:20s} {s.licence}  {s.author}  {s.source}")
    if not unattributed:
        print("still fake  : 0 — every audio file in this directory is "
              "attributed, so `check_audio` will pass.")
        return 0
    print(f"\nINCOMPLETE — {len(unattributed)} audio file(s) in {out} have no "
          f"`generated: false` entry in {SIDECAR_NAME}:", file=sys.stderr)
    for name in unattributed:
        why = ("no entry" if known.get(name) is None
               else "entry says generated: true")
        print(f"   {name:20s} {why}", file=sys.stderr)
    print("\nEvery one of these BLOCKS a final render outside MOCK_MODE "
          "(pipeline.gates.check_audio), not just the ones this script knows "
          "how to query. Re-run to retry, or replace the file by hand and add "
          "its entry.\nDo NOT hand-write `generated: false` for a file that is "
          "still an oscillator — that defeats the gate rather than passing it.",
          file=sys.stderr)
    return 1


def _unattributed(directory: Path, known: dict) -> list[str]:
    """Audio files in `directory` the audio gate will call placeholders.

    Deliberately the same rule as `pipeline.audio_assets.generated_audio`:
    read off the directory, and treat a missing entry as generated. Two
    implementations of one question is how they come to disagree, and the
    disagreement here is a silent render block.
    """
    out: list[str] = []
    if not directory.is_dir():
        return out
    for f in sorted(directory.iterdir()):
        if f.suffix.lower() not in AUDIO_SUFFIXES:
            continue
        entry = known.get(f.name)
        if entry is None or entry.generated:
            out.append(f.name)
    return out


if __name__ == "__main__":
    raise SystemExit(main())
