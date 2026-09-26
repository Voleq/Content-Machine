"""What the videos sound like, beyond the voice.

The LONG builds its mix inline in `render_long`, beside the segments its cues
hang off; it takes its variation, its room and its theme from here. The
SHORT's whole mix lives here, because the compositor is the wrong place for
it: sound reads the shot spans AFTER composition and changes nothing about the
picture, so the two can move independently.

THE SHORT HAD NO MIX FOR SIX WEEKS. The shots rewrite (10c4d23, 15 Aug)
replaced the old renderer's audio block with a `-shortest` mux of the voice
alone. The room tone, the effects, the voice compression and the loudness
pass all went with it, and the commit never said so. A short went out as a
raw, uncompressed voice with digital silence between words, at whatever
level the voice model happened to hand back. Both formats now mix through
`render_common.audio_graph`, so a change to the master reaches both or
neither.

What a short gets, each decided by the operator (2026-09-25):

* the room under everything, at the hour the set is drawn at;
* a swish on every cut, cut short when the next shot is short;
* a hit on the first frame, and on the payoff: everything but the voice
  drops out for half a second, then the hit lands on the number;
* a quiet loop under the voice that dips whenever he speaks, one of the
  owned pack's loops, not the one the last few shorts used.

What the LONG gets: a hit on every chapter change (not music), and the
channel theme as the intro and the outro, dipped under the voice.

NO EFFECT PLAYS THE SAME WAY TWICE. Each firing picks one of the key's
variants, never the one it picked last time, a few percent off in speed and a
decibel or so off in level. Seeded by the script, so the draft, the proof and
the final of one video sound the same. The THEME never varies: it is the one
piece a viewer is meant to recognise.
"""

from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from pipeline.audio_assets import (ROOM_TONE_GAIN_DB, ROOM_TONE_NAME,
                                   SCORE_DIR_NAME, audio_banner)
from pipeline.models import SFX_KEYS
from pipeline.render_common import AudioTrack

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# The library
# --------------------------------------------------------------------------

# Effects the MACHINE fires, off structure. The writer's palette is
# `models.SFX_KEYS`; these are never in a script.
CUT_KEY = "whoosh"          # every cut in a short
HIT_KEY = "impact"          # the hook, the payoff, a chapter change

# One sound per design move (kit/emit/motion.json). Fetched now so one run of
# `scripts/fetch_sfx.py` gets everything; PLAYED once the visuals work says
# how the bot plays the moves. A move with no entry gets no sound: a looping
# move sits under the shot as a set layer instead (`SET_LAYERS`).
MOVE_SOUNDS: dict[str, str] = {
    "count-up": "tick_roll",
    "line-draw": "marker_draw",
    "highlight": "marker_draw",
    "pen-circle": "marker_circle",
    "bars-grow": "knock",
    "card-pin": "pin_tap",
    "tick-over": "flip",
    "zoom-to-slot": CUT_KEY,
    "slide-in": CUT_KEY,
}

MACHINE_KEYS: tuple[str, ...] = tuple(dict.fromkeys(
    (CUT_KEY, HIT_KEY, *MOVE_SOUNDS.values())))

# Every key that can fire as an effect, the writer's and the machine's. Each
# one gets variants from the fetch.
EFFECT_KEYS: tuple[str, ...] = tuple(dict.fromkeys((*SFX_KEYS, *MACHINE_KEYS)))

# The room at each hour the set is drawn at. `room_tone.wav` stays the floor
# when an hour has no file of its own.
ROOM_BY_HOUR: dict[str, str] = {"night": "room_night", "dusk": "room_dusk"}

# What is on screen, to what plays under that shot. Tags come from the plate
# key (`-christmas`) and from the room motion a shot plays (`window-rain`,
# `window-snow`, `screen-flicker`), once the renderer plays them.
SET_LAYERS: dict[str, str] = {
    "window-rain": "rain_window",
    "window-snow": "winter_room",
    "christmas": "winter_room",
    "screen-flicker": "screen_buzz",
}

AMBIENCE_KEYS: tuple[str, ...] = tuple(dict.fromkeys(
    (*ROOM_BY_HOUR.values(), *SET_LAYERS.values())))

# The owned score (`scripts/make_score.py`). The theme is two cuts of one
# piece, so the intro and the outro are the same motif by construction.
THEME_INTRO = "theme-intro.m4a"
THEME_OUTRO = "theme-outro.m4a"
BED_PREFIX = "bed-"
SCORE_SUFFIXES = (".m4a", ".wav")

# Levels, relative to `settings.sfx_gain_db` (the writer's cue level). A
# swish on every cut is punctuation, not an event, so it sits well under.
CUT_GAIN_REL_DB = -8.0
HIT_GAIN_REL_DB = 0.0
SET_LAYER_GAIN_DB = ROOM_TONE_GAIN_DB + 6.0
THEME_GAIN_DB = -16.0

# How far ahead of the cut a swish starts: it is a movement INTO the next
# shot, so it peaks on the cut rather than starting on it. A hit lands ON the
# frame; a clack or a rustle arrives just ahead and announces it.
CUT_LEAD_S = 0.10
_LEAD_S = {HIT_KEY: 0.0}
DEFAULT_LEAD_S = 0.15

# The swish is cut off at this share of the incoming shot, inside these
# bounds: a quick cut gets a quick swish.
CUT_SHARE = 0.5
CUT_MIN_S, CUT_MAX_S = 0.15, 0.45

# The half-second before the payoff where everything but the voice stops.
DROP_S = 0.5

# Which shot is a format's payoff. Template JSON refuses keys the engine does
# not read, and this is a fact about sound, so it lives with the sound.
PAYOFF_SHOTS = frozenset({"payoff", "so-what"})

# How far one firing may wander from the staged sound.
RATE_SPREAD = 0.04          # about two thirds of a semitone
TRIM_SPREAD_DB = 1.5

VARIANT_SEP = "-"


def cue_lead_s(key: str) -> float:
    """How far ahead of the picture an effect starts."""
    return _LEAD_S.get(key, DEFAULT_LEAD_S)


def variant_names(key: str, n: int) -> list[str]:
    """`key.wav`, `key-2.wav`, … — the files one key can be played from."""
    return [f"{key}.wav" if i == 1 else f"{key}{VARIANT_SEP}{i}.wav"
            for i in range(1, n + 1)]


def variants(sfx_dir: Path, key: str) -> list[Path]:
    """The files on disk for one key: the base file first, then `-2`, `-3`…"""
    base = sfx_dir / f"{key}.wav"
    extra = sorted(p for p in sfx_dir.glob(f"{key}{VARIANT_SEP}*.wav")
                   if p.stem[len(key) + 1:].isdigit())
    return ([base] if base.exists() else []) + extra


def score_dir(settings) -> Path:
    return settings.assets_dir / SCORE_DIR_NAME


# --------------------------------------------------------------------------
# Variation
# --------------------------------------------------------------------------

class Voicing:
    """Which file, how fast and how loud, for each firing of an effect.

    One per video, seeded by the script: the same video sounds the same on
    every pass, and two videos do not.
    """

    def __init__(self, sfx_dir: Path, seed: str = ""):
        self.sfx_dir = sfx_dir
        self.rng = random.Random(seed or "dennis")
        self._last: dict[str, Path] = {}

    def fire(self, key: str, t: float, gain_db: float, *, name: str = "",
             max_s: float = 0.0, vary: bool = True) -> AudioTrack | None:
        files = variants(self.sfx_dir, key)
        if not files:
            return None
        pick = [f for f in files if f != self._last.get(key)] or files
        path = self.rng.choice(pick)
        self._last[key] = path
        rate, trim = 1.0, 0.0
        if vary:
            rate = round(1.0 + self.rng.uniform(-RATE_SPREAD, RATE_SPREAD), 3)
            trim = round(self.rng.uniform(-TRIM_SPREAD_DB, TRIM_SPREAD_DB), 1)
        return AudioTrack(path=path, start_s=max(t, 0.0), gain_db=gain_db,
                          rate=rate, trim_db=trim, max_s=max_s,
                          name=name or f"{key}@{max(t, 0.0):.2f}")


# --------------------------------------------------------------------------
# The room
# --------------------------------------------------------------------------

def room_track(settings, hour: str = "") -> AudioTrack | None:
    """The room at this hour, under the whole video, or the generic room.

    Named `room_tone` whichever file it is, because the name is its role in
    the mix; the manifest row carries the file.
    """
    sfx = settings.assets_dir / "sfx"
    own = ROOM_BY_HOUR.get(hour)
    for name in ((f"{own}.wav",) if own else ()) + (ROOM_TONE_NAME,):
        path = sfx / name
        if path.exists():
            return AudioTrack(path=path, gain_db=ROOM_TONE_GAIN_DB, loop=True,
                              name="room_tone")
    return None


def shot_tags(plate_keys: Iterable[str], motions: Iterable[str] = ()) -> set[str]:
    """What a shot shows that the room should sound like."""
    tags = {m for m in motions if m in SET_LAYERS}
    if any("-christmas" in k for k in plate_keys):
        tags.add("christmas")
    return tags


def set_layers(settings, windows: Sequence[tuple[float, float, set[str]]]
               ) -> list[AudioTrack]:
    """One quiet loop per tagged shot, for exactly as long as it is on screen.

    Rain under the window angle that shows it, not under the whole video: the
    sound follows the picture, which is what makes it the room rather than a
    bed.
    """
    sfx = settings.assets_dir / "sfx"
    out: list[AudioTrack] = []
    for t0, t1, tags in windows:
        for key in sorted({SET_LAYERS[t] for t in tags if t in SET_LAYERS}):
            path = sfx / f"{key}.wav"
            if path.exists() and t1 - t0 > 0.2:
                out.append(AudioTrack(path=path, start_s=t0, loop=True,
                                      max_s=t1 - t0, gain_db=SET_LAYER_GAIN_DB,
                                      name=f"{key}@{t0:.2f}"))
    return out


# --------------------------------------------------------------------------
# The score
# --------------------------------------------------------------------------

def beds(settings) -> list[Path]:
    d = score_dir(settings)
    if not d.is_dir():
        return []
    return sorted(p for p in d.glob(f"{BED_PREFIX}*")
                  if p.suffix.lower() in SCORE_SUFFIXES)


def recent_beds(settings, *, window: int = 3,
                exclude: "Path | str | None" = None) -> set[str]:
    """Which loops the last few shorts played, off their manifests.

    Forgiving the way `reach.recent_plates` is: anything unreadable simply
    contributes nothing. `exclude` is the video being rendered, so a second
    pass does not steer off the loop its own first pass chose.
    """
    base = Path(settings.workspace_dir)
    if not base.is_dir():
        return set()
    skip = Path(exclude).resolve() if exclude else None
    found: list[tuple[float, str]] = []
    for manifest in base.glob("*/*/*manifest*.json"):
        if skip is not None and manifest.parent.resolve() == skip:
            continue
        try:
            rows = json.loads(manifest.read_text(encoding="utf-8")).get("audio") or []
            for row in rows:
                if row.get("name") == "bed" and row.get("file"):
                    found.append((manifest.stat().st_mtime, str(row["file"])))
        except (OSError, json.JSONDecodeError, ValueError, AttributeError):
            continue
    found.sort(key=lambda r: r[0], reverse=True)
    return {name for _, name in found[:window]}


def bed_track(settings, seed: str, *, avoid: set[str] = frozenset()
              ) -> AudioTrack | None:
    """One of the owned loops under a short, or none when there are none."""
    if not getattr(settings, "short_bed", True):
        return None
    pool = beds(settings)
    if not pool:
        return None
    fresh = [p for p in pool if p.name not in avoid] or pool
    path = random.Random(f"bed:{seed}").choice(fresh)
    return AudioTrack(path=path, gain_db=settings.short_bed_gain_db, loop=True,
                      duck=True, name="bed")


def theme_tracks(settings, duration: float) -> list[AudioTrack]:
    """The theme as the LONG's intro and outro, dipped under the voice.

    The outro is placed to END with the video. Never varied.
    """
    from pipeline.render_common import ffprobe_duration

    d = score_dir(settings)
    out: list[AudioTrack] = []
    intro, outro = d / THEME_INTRO, d / THEME_OUTRO
    if intro.exists():
        out.append(AudioTrack(path=intro, gain_db=THEME_GAIN_DB, duck=True,
                              name="theme_intro@0.00"))
    if outro.exists():
        try:
            length = ffprobe_duration(outro)
        except Exception:  # noqa: BLE001 — an unreadable outro is no outro
            length = 0.0
        if 0 < length < duration:
            t = duration - length
            out.append(AudioTrack(path=outro, start_s=t, gain_db=THEME_GAIN_DB,
                                  duck=True, name=f"theme_outro@{t:.2f}"))
    return out


# --------------------------------------------------------------------------
# The SHORT
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Cut:
    """What sound needs to know about one shot: when it is, and what it is."""

    shot_id: str
    start: float
    end: float
    chapter_n: int = 0
    tags: frozenset = frozenset()


def structure_cues(cuts: Sequence[Cut], settings, voicing: Voicing, *,
                   chapters: bool) -> tuple[list[AudioTrack], list[tuple[float, float]]]:
    """The effects that come from the cut itself, and the drop windows.

    A chaptered format (the LONG through this engine) gets a hit on each
    chapter change and nothing else: a swish on every one of forty cuts is
    a short's pace, not a deep-dive's. Everything else gets the short's set.
    """
    tracks: list[AudioTrack] = []
    drops: list[tuple[float, float]] = []
    level = settings.sfx_gain_db
    if not cuts:
        return tracks, drops
    if chapters:
        seen: set[int] = set()
        for c in cuts:
            if c.chapter_n and c.chapter_n not in seen:
                seen.add(c.chapter_n)
                tr = voicing.fire(HIT_KEY, c.start - cue_lead_s(HIT_KEY),
                                  level + HIT_GAIN_REL_DB,
                                  name=f"chapter_hit@{c.start:.2f}")
                if tr:
                    tracks.append(tr)
        return tracks, drops

    # The hook: something lands on the first frame, so the first half second
    # is more than a voice starting.
    first = voicing.fire(HIT_KEY, cuts[0].start, level + HIT_GAIN_REL_DB,
                         name=f"hook_hit@{cuts[0].start:.2f}")
    if first:
        tracks.append(first)
    for c in cuts[1:]:
        if c.shot_id in PAYOFF_SHOTS:
            # The payoff: half a second of nothing but the voice, then the hit
            # on the number instead of a swish.
            drops.append((max(c.start - DROP_S, 0.0), c.start))
            tr = voicing.fire(HIT_KEY, c.start, level + HIT_GAIN_REL_DB,
                              name=f"payoff_hit@{c.start:.2f}")
        else:
            length = max(c.end - c.start, 0.0)
            tr = voicing.fire(
                CUT_KEY, c.start - CUT_LEAD_S, level + CUT_GAIN_REL_DB,
                max_s=min(max(length * CUT_SHARE, CUT_MIN_S), CUT_MAX_S))
        if tr:
            tracks.append(tr)
    return tracks, drops


def short_mix(tts, settings, *, cuts: Sequence[Cut] = (), hour: str = "",
              seed: str = "", chapters: bool = False, duration: float = 0.0,
              workspace: "Path | str | None" = None) -> list[AudioTrack]:
    """Every track under a shots-engine render, or none when there is no voice.

    No voice file means no mix at all, the same as before: a proof run on a
    missing file renders a silent picture, and a room tone with nobody in it
    is not a proof of anything.
    """
    voice = getattr(tts, "audio_path", None)
    if not voice or not Path(voice).exists():
        return []
    tracks = [AudioTrack(path=Path(voice), gain_db=0.0, voice=True,
                         name="voice")]
    loops: list[AudioTrack] = []
    room = room_track(settings, hour)
    if room:
        loops.append(room)
    if not chapters:
        bed = bed_track(settings, seed,
                        avoid=recent_beds(settings, exclude=workspace))
        if bed:
            loops.append(bed)
    layers = set_layers(settings, [(c.start, c.end, set(c.tags)) for c in cuts])
    voicing = Voicing(settings.assets_dir / "sfx", seed)
    cues, drops = structure_cues(cuts, settings, voicing, chapters=chapters)
    # The drop silences everything that is not the voice and not the hit.
    for tr in loops + layers:
        tr.gaps = tuple(drops)
    tracks += loops + layers + cues
    if chapters and duration > 0:
        tracks += theme_tracks(settings, duration)
    banner = audio_banner(settings)
    if banner:
        log.warning("%s", banner)
    return tracks


def normalises(settings, tts) -> bool:
    """Whether the master bus moves this mix to the streaming target.

    The LONG's rule: mock and draft audio skip `loudnorm`, because measuring
    a placeholder and raising it thirty decibels tells you nothing about the
    real mix (see `CompositeSpec.normalise_audio`). The limiter runs either
    way.
    """
    return not (settings.mocking_tts or getattr(tts, "draft", False))


def manifest_rows(tracks: list[AudioTrack]) -> list[dict]:
    """What the mix did: the LONG's row shape, plus the file and any variation."""
    rows = []
    for t in tracks:
        row = {"name": t.name or t.path.stem, "start": round(t.start_s, 2),
               "gain_db": round(t.gain_db, 1), "loop": t.loop,
               "file": t.path.name}
        if t.rate != 1.0:
            row["rate"] = t.rate
        if t.trim_db:
            row["trim_db"] = t.trim_db
        if t.duck:
            row["duck"] = True
        if t.gaps:
            row["gaps"] = [[round(a, 2), round(b, 2)] for a, b in t.gaps]
        rows.append(row)
    return rows


# --------------------------------------------------------------------------
# What the operator reads
# --------------------------------------------------------------------------

def measure_lufs(path: Path) -> float | None:
    """Integrated loudness of a finished file, or None if it cannot be read."""
    import re
    import subprocess

    try:
        proc = subprocess.run(
            ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn",
             "-af", "ebur128", "-f", "null", "-"],
            capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.SubprocessError):
        return None
    found = re.findall(r"I:\s+(-?[\d.]+) LUFS", proc.stderr)
    return float(found[-1]) if found else None


def sound_summary(rows: list[dict], *, lufs: float | None,
                  placeholders: int) -> dict:
    """The record the delivery line is written from, kept on the manifest."""
    effects = [r for r in rows if "@" in r["name"] and not r["loop"]
               and not r["name"].startswith("theme_")]
    return {
        "lufs": None if lufs is None else round(lufs, 1),
        "effects": len(effects),
        "bed": next((r["file"] for r in rows if r["name"] == "bed"), ""),
        "theme": any(r["name"].startswith("theme_") for r in rows),
        "room": next((r["file"] for r in rows if r["name"] == "room_tone"), ""),
        "placeholders": placeholders,
    }


def placeholders_played(settings, tracks: list[AudioTrack]) -> int:
    """How many of the files this mix plays are placeholders.

    The ones it PLAYS, not the whole library: the delivery line is about this
    video. The gate (`gates.check_audio`) is the one that looks at them all.
    """
    from pipeline.audio_assets import generated_audio

    fake = set(generated_audio(settings))
    return len({f"{t.path.parent.name}/{t.path.name}" for t in tracks
                if not t.voice} & fake)

