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
audio gate is PER FILE, so fixing room tone alone leaves every other file
blocking. This script exits non-zero until every audio file in the target
directory carries provenance.

Without a key it explains what to set and exits non-zero rather than silently
leaving the oscillators in place.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Collection, Sequence
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
from pipeline.sound import BODY_KEYS, EFFECT_KEYS, variant_names  # noqa: E402

API = "https://freesound.org/apiv2"

# What to ask for, per key, most specific first. Freesound treats every word
# of a query as mandatory, so one query of five words only finds a sound
# tagged with all five: "windows error beep alert chime" found nothing, and
# the first real run came back with 10 of its 33 files. Each key now steps
# down to shorter wording until it has a take for every file it fills. The
# wording still matters, so a bare word is only ever the last resort:
# "buzzer" alone returns klaxons.
QUERIES: dict[str, tuple[str, ...]] = {
    "windows_error": ("windows error", "computer error beep", "error beep"),
    "cash_register": ("cash register ka-ching", "cash register", "cash till"),
    "record_scratch": ("vinyl record scratch stop", "record scratch",
                       "vinyl scratch"),
    "sad_trombone": ("sad trombone", "trombone fail", "trombone"),
    "camera_shutter": ("camera shutter click dslr", "camera shutter",
                       "shutter click"),
    "vine_boom": ("boom impact bass", "bass boom", "boom hit"),
    "coffee_slurp": ("coffee slurp", "slurp", "coffee sip"),
    "keyboard_clack": ("mechanical keyboard keypress", "mechanical keyboard",
                       "keyboard key"),
    "paper_rustle": ("paper page turn", "page turn", "paper rustle"),
    "buzzer": ("buzzer wrong answer", "wrong buzzer", "game show buzzer",
               "buzzer"),
    "ding": ("small bell ding", "bell ding", "ding"),
    # not in SFX_KEYS: the machine fires these off structure
    # (`pipeline/sound.py`). The swish on every cut, and the hit on a short's
    # first frame, its payoff and every chapter change of the long.
    "whoosh": ("whoosh transition swish short", "whoosh transition", "whoosh",
               "swish"),
    "impact": ("cinematic impact hit", "impact hit", "impact"),
    # One per design move, fetched now so this one run gets everything; the
    # renderer plays them once the moves are wired (`sound.MOVE_CUES`).
    "tick_roll": ("ratchet ticking", "ratchet", "mechanical ticking"),
    "marker_draw": ("marker pen writing", "marker writing", "marker pen"),
    "marker_circle": ("marker scribble", "pen scribble", "scribble"),
    "knock": ("single knock wood", "knock wood", "knock"),
    "pin_tap": ("push pin cork board", "push pin", "thumbtack"),
    "flip": ("flip clock", "card flip", "flap mechanical"),
    "sting": ("musical sting", "music stinger", "stinger"),
    "pop": ("pop bubble click short", "pop click", "pop"),
    # His clothes when the 3D Dennis turns or moves an arm (`sound.body_cues`).
    "cloth_rustle": ("cloth movement foley", "clothes rustle", "cloth rustle",
                     "fabric rustle"),
}

# Every effect the renderers fire gets this many takes: `key.wav`, `key-2.wav`,
# `key-3.wav`. One file played on every cut is what makes a video sound
# assembled; `sound.Voicing` never plays the same take twice running.
VARIANTS = 3

# The room bed. Not an effect — a continuous low hum that runs under the whole
# video, so the audio between words is a room rather than digital silence.
# It loops, so it is cut and seamed like the ambience below.
ROOM_QUERIES: tuple[str, ...] = ("room tone office", "office room tone",
                                 "room tone", "office ambience")

# The room at each hour, and what plays under a shot that shows rain, snow or
# a flickering screen (`sound.ROOM_BY_HOUR`, `sound.SET_LAYERS`). Loops, so a
# take has to be long enough to loop without the seam being the loudest thing
# in it.
AMBIENCE_QUERIES: dict[str, tuple[str, ...]] = {
    "room_night": ("night room ambience radiator", "night room ambience",
                   "night interior", "night ambience"),
    "room_dusk": ("evening room ambience traffic", "evening room ambience",
                  "distant traffic window", "evening ambience"),
    "rain_window": ("rain window indoor", "rain window", "rain glass",
                    "rain indoor"),
    "winter_room": ("winter wind indoor", "wind outside window",
                    "wind indoor", "wind window"),
    "screen_buzz": ("crt monitor hum", "crt hum", "electrical hum"),
}

# Freesound allows 60 API requests a minute (and 2000 a day). Every rung of a
# ladder can cost two (the CC0 filter, then once without it), so the searches
# are spaced to stay under it rather than turning into 429s halfway through.
# The previews come from Freesound's CDN, which is not counted.
REQUEST_GAP_S = 1.1
THROTTLED_WAIT_S = 65.0
DOWNLOAD_TRIES = 3

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
MIN_CUE_SECONDS = 0.1       # less than this left after normalising is a failure
LOOP_SECONDS = 30.0          # what a loop is cut to, seam crossfaded
LOOP_SEAM_SECONDS = 1.0


Wanted = tuple[str, str, tuple[str, ...], float, bool]


def wanted() -> list[Wanted]:
    """Every file this fetch fills: `(file, key, queries, max_s, loop)`.

    The room tone is not here; `--room-tone` owns it, as it always has.
    """
    out: list[Wanted] = []
    for key, queries in QUERIES.items():
        n = VARIANTS if key in EFFECT_KEYS or key in BODY_KEYS else 1
        for name in variant_names(key, n):
            out.append((name, key, queries, MAX_SECONDS, False))
    for key, queries in AMBIENCE_QUERIES.items():
        out.append((f"{key}.wav", key, queries, ROOM_MAX_SECONDS, True))
    return out


def _key() -> str | None:
    return os.environ.get("FREESOUND_API_KEY") or os.environ.get("FREESOUND_TOKEN")


def page_url(hit: dict) -> str:
    """The sound's own page: what SOURCES.json records as its source."""
    return f"https://freesound.org/s/{hit.get('id')}/"


def search(queries: str | Sequence[str], token: str, *, max_s: float,
           min_s: float = 0.1) -> dict | None:
    """The most relevant CC0 hit for `queries`, or None."""
    hits = search_many(queries, token, max_s=max_s, min_s=min_s, n=1)
    return hits[0] if hits else None


def search_many(queries: str | Sequence[str], token: str, *, max_s: float,
                min_s: float = 0.1, n: int = 1,
                skip: Collection[str] = ()) -> list[dict]:
    """CC0 hits enough for `n` files, most relevant first.

    The queries are asked in turn, most specific first, until `n` hits are in
    hand. Freesound needs every word of a query to match, so a long one finds
    exactly the sound or nothing, and a shorter one behind it finds the rest.
    A later query's hits come after an earlier one's and never repeat them,
    nor a sound in `skip` (page URLs another file already plays). All of the
    last answer is kept, so a failed download has a spare behind it.

    Each query asks for CC0 outright, then, if that filter is refused or
    turns up nothing, once more without it, picking CC0 out of the answer
    here. So a filter the API reads differently costs one request rather than
    every sound.
    """
    if isinstance(queries, str):
        queries = (queries,)
    duration = f"duration:[{min_s} TO {max_s}]"
    seen = set(skip)
    out: list[dict] = []
    for query in queries:
        hits, failures = _cc0_hits(query, duration, token)
        if len(failures) == 2:
            exc = failures[-1]
            status = getattr(getattr(exc, "response", None), "status_code", None)
            print(f"  search failed: {type(exc).__name__}"
                  f"{f' {status}' if status else ''}", file=sys.stderr)
            # A refused search is not one that shorter words would answer.
            break
        for hit in hits:
            if page_url(hit) not in seen:
                seen.add(page_url(hit))
                out.append(hit)
        if len(out) >= n:
            break
    return out


def _cc0_hits(query: str, duration: str,
              token: str) -> tuple[list[dict], list[Exception]]:
    """One query's CC0 hits in Freesound's relevance order, and what failed."""
    failures: list[Exception] = []
    for flt in (f"{duration} {CC0_FILTER}", duration):
        params = {
            "query": query,
            "filter": flt,
            "fields": "id,name,username,license,previews,duration",
            "page_size": 30,
        }
        try:
            results = _ask(params, token)
        except Exception as exc:  # noqa: BLE001 — one failed key is not fatal
            failures.append(exc)
            continue
        # Freesound's relevance order, not the shortest hit: the shortest
        # record scratch or sad trombone under the cap is a fragment of one.
        hits = [h for h in results if is_cc0(h.get("license", ""))]
        if hits:
            return hits, failures
    return [], failures


_last_ask = 0.0


def _ask(params: dict, token: str) -> list[dict]:
    """One text search, spaced under the rate limit. Throttled anyway, it
    waits once for the minute to pass and asks again."""
    import httpx

    global _last_ask
    for attempt in (1, 2):
        wait = _last_ask + REQUEST_GAP_S - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_ask = time.monotonic()
        # In a header, not a `token=` parameter: httpx's error text carries
        # the URL, and it was printed with the key in it.
        r = httpx.get(f"{API}/search/text/", params=params, timeout=30,
                      headers={"Authorization": f"Token {token}"})
        if r.status_code == 429 and attempt == 1:
            print(f"  Freesound says slow down; waiting "
                  f"{THROTTLED_WAIT_S:.0f}s", file=sys.stderr)
            time.sleep(THROTTLED_WAIT_S)
            continue
        r.raise_for_status()
        return (r.json() or {}).get("results") or []
    return []


def download(hit: dict, dest: Path, *, loop: bool = False,
             trim_lead: bool = True) -> bool:
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
        return normalise(raw, dest, loop=loop, trim_lead=trim_lead)


def normalise(src: Path, dest: Path, *, loop: bool = False,
              trim_lead: bool = True) -> bool:
    """One peak for every cue, so the mix under them never has to move.

    A LOOP is also cut to `LOOP_SECONDS` with its seam crossfaded: the take
    starts one seam in, and its last second fades into its first, so when
    the renderer plays it round again the join is a continuation rather than
    a click and a jump in the rain.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.stem + ".part.wav")
    level = (f"loudnorm=I=-18:TP={TARGET_PEAK_DBFS}:LRA=11,"
             f"alimiter=limit={10 ** (TARGET_PEAK_DBFS / 20):.4f}")
    inputs = ["-i", str(src)]
    if loop:
        # The take is read twice, once for the body and once for the head.
        # One stream split in two gave acrossfade nothing to write on ffmpeg
        # 6.1: every room loop failed as "under 0.1s of sound" (25 Oct 2026).
        d, total = LOOP_SEAM_SECONDS, LOOP_SECONDS + LOOP_SEAM_SECONDS
        inputs += ["-i", str(src)]
        graph = (f"[0:a]atrim=start={d}:end={total},asetpts=PTS-STARTPTS[body];"
                 f"[1:a]atrim=0:{d},asetpts=PTS-STARTPTS[head];"
                 f"[body][head]acrossfade=d={d}:c1=tri:c2=tri,{level}[out]")
        af = ["-filter_complex", graph, "-map", "[out]"]
    elif trim_lead:
        # A one-shot starts on its first sound, not on the silence the
        # uploader left before it: the renderer places a knock or a hit on a
        # frame, and 80 ms of lead-in puts it two frames late.
        af = ["-af", f"silenceremove=start_periods=1:start_threshold=-50dB,{level}"]
    else:
        # Room tone IS the quiet: every sample of a still room can sit under
        # -50 dB, and the trim above then removed all of it.
        af = ["-af", level]
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *inputs,
        *af, "-ac", "1", "-ar", "44100", "-c:a", "pcm_s16le", str(tmp),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"  normalise failed: {exc}", file=sys.stderr)
        tmp.unlink(missing_ok=True)
        return False
    # A file with no sound left in it is a failure, not a cue: looped under a
    # render, a zero-length wav never ends and the render hangs on it. The
    # file already there (the offline placeholder) stays until one is good.
    if tmp.stat().st_size < 44 + int(44100 * 2 * MIN_CUE_SECONDS):
        print(f"  normalise left under {MIN_CUE_SECONDS}s of sound",
              file=sys.stderr)
        tmp.unlink(missing_ok=True)
        return False
    tmp.replace(dest)
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
        for name, _k, queries, _max_s, _loop in todo:
            print(f"  would fetch {name:20s} <- {' / '.join(queries)}")
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
    # A sound plays under one name only. The takes already on disk, under
    # this key or any other, are never fetched again as a new one.
    refetch = {w[0] for w in todo} | ({ROOM_TONE_NAME} if args.force else set())
    held = {s.source for name, s in known.items()
            if s.real and name not in refetch}
    # One search per KEY, however many of its takes are missing: the takes
    # are its next most relevant CC0 hits.
    by_key: dict[str, list[Wanted]] = {}
    for w in todo:
        by_key.setdefault(w[1], []).append(w)
    for key, need in by_key.items():
        _name, _k, queries, max_s, loop = need[0]
        hits = search_many(queries, token, max_s=max_s, n=len(need),
                           min_s=AMBIENCE_MIN_SECONDS if loop else 0.1,
                           skip=held)
        found = len(hits)
        for name, *_ in need:
            print(f"  {name} ...", end=" ", flush=True)
            if not hits:
                print("no CC0 result for " + " / ".join(map(repr, queries))
                      if not found else f"no take left of the {found} found")
                continue
            hit = _fetch_into(out / name, hits, loop=loop)
            if hit is None:
                print("failed")
                continue
            known[name] = _source(name, hit)
            held.add(page_url(hit))
            fetched += 1
            print(f"ok  ({hit.get('license', '?')}, {hit.get('username', '?')})")

    if args.room_tone:
        rt = known.get(ROOM_TONE_NAME)
        if args.force or rt is None or rt.generated:
            print(f"  {ROOM_TONE_NAME} ...", end=" ", flush=True)
            # It loops under the whole video, so it is cut and seamed like
            # the ambience: a two-second room repeats audibly.
            hits = search_many(ROOM_QUERIES, token, max_s=ROOM_MAX_SECONDS,
                               min_s=AMBIENCE_MIN_SECONDS, skip=held)
            hit = _fetch_into(out / ROOM_TONE_NAME, hits, loop=True)
            if hit is not None:
                known[ROOM_TONE_NAME] = _source(ROOM_TONE_NAME, hit)
                held.add(page_url(hit))
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


def _fetch_into(dest: Path, hits: list[dict], *, loop: bool) -> dict | None:
    """The first of `hits` that downloads into `dest`, taken off the list.

    A few tries at most, so a download that cannot work at all does not use
    up every take the other files of the key were going to have. The
    placeholder already there is set aside first, as the offline fallback,
    and stays in place until a download succeeds.
    """
    backup = dest.with_suffix(".wav.placeholder")
    for _ in range(DOWNLOAD_TRIES):
        if not hits:
            break
        hit = hits.pop(0)
        if dest.exists() and not backup.exists():
            shutil.copy2(dest, backup)      # keep the offline fallback
        if download(hit, dest, loop=loop):
            return hit
    return None


def _source(name: str, hit: dict) -> AudioSource:
    return AudioSource(name=name, source=page_url(hit),
                       licence=str(hit.get("license", "")),
                       author=str(hit.get("username", "")),
                       generated=False)


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
