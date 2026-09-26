#!/usr/bin/env python3
"""Make the channel's own music, once: the theme and the loops under a short.

YouTube's Content ID claims music, and a claimed video's money goes to the
claimant. So every note the videos play is one the channel owns: generated
once by ElevenLabs Music (`POST /v1/music`), instrumental only, and kept in
`assets/score/` with a record of where each file came from. The operator chose
this over CC0 music and over the YouTube Audio Library on 2026-09-25.

What it makes:

* `theme-outro.m4a`, the theme, about sixteen seconds. The LONG plays it so
  it ends with the video.
* `theme-intro.m4a`, the theme's first six seconds, faded. The LONG's cold
  open. Cut from the same take, so the intro and the outro are one motif by
  construction rather than two generations that happen to agree.
* `bed-1.m4a` … `bed-6.m4a`, loops of about 77 seconds (32 bars at 100 BPM)
  that sit under a short, one per video, dipped whenever he speaks. The same
  instruments as the theme, so the channel sounds like one place.

THE THEME NEVER VARIES. The effects are played with small changes every time
(`pipeline/sound.py`); the theme is the one thing a viewer is meant to learn.

    python scripts/make_score.py --dry-run          # what it would make, and the cost
    python scripts/make_score.py --confirm          # make whatever is missing
    python scripts/make_score.py --confirm --only bed-3 --force   # redo one

SPEND IS FENCED here the way it is for the voice: nothing is generated in
MOCK_MODE, nothing without `--confirm`, nothing past the monthly cap, and every
generation is recorded in the ledger under lane `score`. The price is per
minute of music (`USD_PER_MINUTE`, from elevenlabs.io/pricing/api on
2026-09-25). Commercial use needs a paid plan (Starter or above), so a free
account is refused.

Listen to every file before committing `assets/score/`. A loop you don't like
is one `--only … --force` away.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.audio_assets import (  # noqa: E402
    SCORE_DIR_NAME,
    AudioSource,
    load_sources,
    save_sources,
)
from pipeline.sound import BED_PREFIX, THEME_INTRO, THEME_OUTRO  # noqa: E402

MODEL = "music_v1"
OUTPUT_FORMAT = "mp3_44100_192"
# Listed API price, all plans, checked 2026-09-25. Override if it moves.
USD_PER_MINUTE = 0.15

INTRO_SECONDS = 6.0
INTRO_FADE_SECONDS = 1.5
BEDS = 6
BED_MS = 76_800           # 32 bars of 4/4 at 100 BPM
THEME_MS = 16_000

# What every piece shares, so the theme and the loops sound like one room.
_SET = ("Instrumental only, no vocals. Muted felt piano, a warm and sparse "
        "Rhodes, a soft sub bass. Intimate, dry, understated: a finance show "
        "recorded alone at a desk at three in the morning. Not hype, not "
        "cinematic, no risers, no drops.")

THEME_PROMPT = (
    f"{_SET} A short, memorable theme: one four-note piano motif, stated, "
    f"answered, stated again and resolved gently on the last bar. 92 BPM, "
    f"minor key, no drums. It has to work as a signature a viewer learns.")

# Each loop changes one thing, never the set.
_BED_TURNS = (
    "A minor, a soft kick on every beat and a brushed snare on two and four",
    "D minor, a soft kick and rim clicks, a slow piano arpeggio",
    "F major with a melancholy lean, a soft kick and a shaker",
    "E minor, a soft kick, a muted clap on four, sparse piano stabs",
    "C minor, a soft kick and brushed snare, a repeating two-chord Rhodes",
    "G minor, a soft kick, a ticking hi-hat, low piano octaves",
)


def bed_prompt(i: int) -> str:
    turn = _BED_TURNS[(i - 1) % len(_BED_TURNS)]
    return (f"{_SET} A steady loop for talking over, 100 BPM in 4/4, {turn}. "
            f"No melody that competes with a speaking voice, no build, no "
            f"change of section. It ends where it began so it can loop.")


@dataclass(frozen=True)
class Piece:
    name: str             # what `--only` takes
    prompt: str
    length_ms: int
    files: tuple[str, ...]  # what it writes


def pieces() -> list[Piece]:
    out = [Piece("theme", THEME_PROMPT, THEME_MS, (THEME_OUTRO, THEME_INTRO))]
    for i in range(1, BEDS + 1):
        out.append(Piece(f"{BED_PREFIX}{i}", bed_prompt(i), BED_MS,
                         (f"{BED_PREFIX}{i}.m4a",)))
    return out


def cost_usd(ps: list[Piece]) -> float:
    return round(sum(p.length_ms for p in ps) / 60_000 * USD_PER_MINUTE, 2)


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args],
                   check=True, capture_output=True)


def _level(src: Path, dest: Path, *, seconds: float = 0.0) -> None:
    """One loudness for the whole score, stereo AAC; optionally the head only."""
    af = "loudnorm=I=-18:TP=-2:LRA=11"
    head = []
    if seconds:
        head = ["-t", f"{seconds}"]
        af += (f",afade=t=out:st={seconds - INTRO_FADE_SECONDS}"
               f":d={INTRO_FADE_SECONDS}")
    _ffmpeg("-i", str(src), *head, "-af", af, "-ac", "2", "-ar", "44100",
            "-c:a", "aac", "-b:a", "256k", str(dest))


def generate(piece: Piece, settings) -> tuple[bytes, str]:
    """One paid generation. Returns the audio and ElevenLabs' song id."""
    import httpx

    r = httpx.post(
        f"{settings.eleven_base_url}/v1/music",
        params={"output_format": OUTPUT_FORMAT},
        headers={"xi-api-key": settings.elevenlabs_api_key},
        json={"prompt": piece.prompt, "music_length_ms": piece.length_ms,
              "model_id": MODEL, "force_instrumental": True},
        timeout=600)
    r.raise_for_status()
    return r.content, r.headers.get("song-id", "")


def plan_tier(settings) -> str:
    """The ElevenLabs plan this key is on, or "" when it cannot be read."""
    import httpx

    try:
        r = httpx.get(f"{settings.eleven_base_url}/v1/user/subscription",
                      headers={"xi-api-key": settings.elevenlabs_api_key},
                      timeout=30)
        r.raise_for_status()
        return str((r.json() or {}).get("tier") or "")
    except Exception:  # noqa: BLE001 — unknown is reported, not fatal
        return ""


def main(argv: list[str] | None = None) -> int:
    from config import get_settings
    from pipeline.cost import SpendLedger

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--only", nargs="*", default=None,
                    help="piece names: theme, bed-1 … bed-6")
    ap.add_argument("--force", action="store_true",
                    help="remake pieces that already exist")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--confirm", action="store_true",
                    help="actually spend: without it nothing is generated")
    args = ap.parse_args(argv)

    settings = get_settings()
    out: Path = args.out or settings.assets_dir / SCORE_DIR_NAME
    known = load_sources(out)
    todo = [p for p in pieces()
            if (args.only is None or p.name in args.only)
            and (args.force or not all((out / f).exists() and f in known
                                       for f in p.files))]
    est = cost_usd(todo)
    print(f"target      : {out}")
    print(f"to make     : {', '.join(p.name for p in todo) or 'nothing'}")
    print(f"music       : {sum(p.length_ms for p in todo) / 1000:.0f}s, "
          f"about ${est:.2f} at ${USD_PER_MINUTE}/min")
    if not todo:
        return 0
    if args.dry_run:
        for p in todo:
            print(f"\n  {p.name} ({p.length_ms / 1000:.0f}s) -> "
                  f"{', '.join(p.files)}\n    {p.prompt}")
        return 0
    if settings.mock_mode:
        print("\nMOCK_MODE is on, so nothing is generated. Set MOCK_MODE=false "
              "for this run to spend.", file=sys.stderr)
        return 2
    if not settings.elevenlabs_api_key:
        print("\nELEVENLABS_API_KEY is not set.", file=sys.stderr)
        return 2
    if not args.confirm:
        print(f"\nThis spends about ${est:.2f}. Re-run with --confirm.",
              file=sys.stderr)
        return 2
    tier = plan_tier(settings)
    if tier.lower() == "free":
        print("\nThis key is on the free plan, and ElevenLabs music is only "
              "licensed for commercial use on a paid plan (Starter or above). "
              "Nothing was generated.", file=sys.stderr)
        return 2
    if not tier:
        print("warning     : could not read the plan; commercial use needs "
              "Starter or above", file=sys.stderr)
    ledger = SpendLedger(settings)
    if ledger.would_exceed(est):
        print(f"\nAbout ${est:.2f} would pass the monthly cap "
              f"(${settings.monthly_spend_cap_usd:.2f}). Nothing was generated.",
              file=sys.stderr)
        return 2

    out.mkdir(parents=True, exist_ok=True)
    made = 0
    for p in todo:
        print(f"  {p.name} ...", end=" ", flush=True)
        try:
            audio, song_id = generate(p, settings)
        except Exception as exc:  # noqa: BLE001 — one failed piece is not fatal
            print(f"failed: {exc}")
            continue
        usd = round(p.length_ms / 60_000 * USD_PER_MINUTE, 4)
        ledger.record_tts(usd, lane="score", tier="music")
        with tempfile.TemporaryDirectory(prefix="score_") as td:
            raw = Path(td) / "raw.mp3"
            raw.write_bytes(audio)
            try:
                _level(raw, out / p.files[0])
                if p.name == "theme":
                    _level(raw, out / THEME_INTRO, seconds=INTRO_SECONDS)
            except (OSError, subprocess.CalledProcessError) as exc:
                print(f"could not encode: {exc}")
                continue
        for f in p.files:
            known[f] = AudioSource(
                name=f, source=f"elevenlabs.io/v1/music {MODEL} song {song_id}",
                licence=f"ElevenLabs commercial, {tier or 'paid'} plan",
                author="ElevenLabs Music", generated=False)
        save_sources(out, known)
        made += 1
        print(f"ok  (${usd:.2f})")

    print(f"\nmade        : {made} of {len(todo)}")
    print(f"provenance  : {out / 'SOURCES.json'}")
    print("\nListen to every file, then commit and push assets/score/.")
    return 0 if made == len(todo) else 1


if __name__ == "__main__":
    raise SystemExit(main())
