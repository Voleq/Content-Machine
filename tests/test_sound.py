"""What the videos sound like beyond the voice.

A short went out as the voice alone from 15 August on, because the shots
rewrite replaced the mix with a `-shortest` mux and nothing checked what a
short sounded like. These check it from both ends: what the mix is built
from, and what the file measures.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from pipeline.audio_assets import ROOM_TONE_GAIN_DB, ROOM_TONE_NAME
from pipeline.render_common import AudioTrack, mix_under_picture, run_ffmpeg
from pipeline.sound import (CUT_KEY, CUT_LEAD_S, DROP_S, HIT_KEY,
                            MOVE_CUES, MOVE_GAP_S, RATE_SPREAD,
                            TRIM_SPREAD_DB, Cut, Move, Voicing, bed_track,
                            manifest_rows, move_cues, normalises, room_track,
                            set_layers, short_mix, shot_tags, sound_summary,
                            structure_cues, theme_tracks, variants)

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class FakeTTS:
    audio_path: Path | None
    draft: bool = False


def _voice(path: Path, pattern: str = "sine=f=220:d=2,apad=pad_dur=1") -> Path:
    """Two seconds of tone, then a second of nothing: a sentence and a pause."""
    run_ffmpeg(["-f", "lavfi", "-i", pattern, "-c:a", "aac", str(path)])
    return path


def _tone(path: Path, pattern: str) -> Path:
    codec = "aac" if path.suffix == ".m4a" else "pcm_s16le"
    run_ffmpeg(["-f", "lavfi", "-i", pattern, "-c:a", codec,
                "-ar", "44100", str(path)])
    return path


def _picture(path: Path, seconds: float) -> Path:
    run_ffmpeg(["-f", "lavfi", "-i", f"color=c=0xF2F2EF:s=64x64:d={seconds}:r=15",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)])
    return path


def _silences(path: Path) -> list[str]:
    proc = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", str(path),
         "-af", "silencedetect=n=-70dB:d=0.4", "-f", "null", "-"],
        capture_output=True, text=True, check=True)
    return re.findall(r"silence_start: ([\d.]+)", proc.stderr)


def _integrated_lufs(path: Path) -> float:
    proc = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", str(path),
         "-af", "ebur128", "-f", "null", "-"],
        capture_output=True, text=True, check=True)
    found = re.findall(r"I:\s+(-?[\d.]+) LUFS", proc.stderr)
    assert found, "ebur128 reported no integrated loudness"
    return float(found[-1])


def _rms_db(path: Path, start: float, end: float) -> float:
    """RMS level of one stretch of a file, in dB."""
    proc = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", str(path), "-af",
         f"atrim={start}:{end},astats=metadata=0:measure_overall=RMS_level",
         "-f", "null", "-"],
        capture_output=True, text=True, check=True)
    found = re.findall(r"RMS level dB:\s+(-?[\d.inf]+)", proc.stderr)
    assert found, proc.stderr[-400:]
    value = found[-1]
    return -200.0 if "inf" in value else float(value)


def _streams(path: Path) -> dict[str, dict]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)],
        capture_output=True, text=True, check=True).stdout
    return {s["codec_type"]: s for s in json.loads(out)["streams"]}


@pytest.fixture()
def assets(tmp_path, settings):
    """A private copy of the shipped effects, so a test can add files."""
    root = tmp_path / "assets"
    shutil.copytree(ROOT / "assets" / "sfx", root / "sfx")
    return root, settings.model_copy(update={"assets_dir": root})


# A short cut the way the template cuts one: a hook, two beats, a quick one,
# the payoff, the close.
CUTS = [
    Cut("hook", 0.0, 5.0),
    Cut("the-move", 5.0, 12.0),
    Cut("the-news", 12.0, 12.8),
    Cut("payoff", 12.8, 18.0),
    Cut("close", 18.0, 20.0),
]


# ---------------------------------------------------------------- the floor


def test_a_short_is_the_voice_over_the_room(settings, tmp_path):
    voice = _voice(tmp_path / "voice.m4a")
    tracks = short_mix(FakeTTS(voice), settings)

    by_name = {t.name: t for t in tracks}
    assert set(by_name) == {"voice", "room_tone"}
    assert by_name["voice"].voice is True, "the voice is compressed, as on the long"
    assert by_name["voice"].gain_db == 0.0
    room = by_name["room_tone"]
    assert room.path.name == ROOM_TONE_NAME
    assert room.loop is True and room.start_s == 0.0
    assert room.gain_db == ROOM_TONE_GAIN_DB, "the same room level as the long"


def test_no_voice_means_no_mix(settings, tmp_path):
    """A room with nobody in it proves nothing; the picture goes out silent,
    which is what a proof on a missing file always did."""
    assert short_mix(FakeTTS(tmp_path / "missing.m4a"), settings) == []
    assert short_mix(FakeTTS(None), settings) == []


def test_placeholder_audio_skips_the_loudness_pass(settings):
    """The LONG's rule, for the LONG's reason: `loudnorm` on a placeholder
    raises it thirty decibels and measures nothing real."""
    assert normalises(settings, FakeTTS(None)) is False, "mock voice"
    live = settings.model_copy(update={"mock_mode": False})
    assert normalises(live, FakeTTS(None)) is True
    assert normalises(live, FakeTTS(None, draft=True)) is False, "draft voice"


def test_the_manifest_row_says_what_played(settings, tmp_path):
    rows = manifest_rows(short_mix(FakeTTS(_voice(tmp_path / "v.m4a")), settings))
    assert rows[0] == {"name": "voice", "start": 0.0, "gain_db": 0.0,
                       "loop": False, "file": "v.m4a"}
    assert rows[1] == {"name": "room_tone", "start": 0.0,
                       "gain_db": round(ROOM_TONE_GAIN_DB, 1), "loop": True,
                       "file": ROOM_TONE_NAME}


# -------------------------------------------------------------- the room


def test_the_room_is_the_hour_the_set_is_drawn_at(assets):
    root, settings = assets
    assert room_track(settings, "night").path.name == "room_night.wav"
    assert room_track(settings, "dusk").path.name == "room_dusk.wav"
    # An hour with no room of its own keeps the generic one, under the same
    # name, so nothing downstream has to know which file it was.
    assert room_track(settings, "dawn").path.name == ROOM_TONE_NAME
    (root / "sfx" / "room_dusk.wav").unlink()
    dusk = room_track(settings, "dusk")
    assert dusk.path.name == ROOM_TONE_NAME and dusk.name == "room_tone"


def test_the_set_is_heard_only_while_it_is_on_screen(assets):
    root, settings = assets
    tags = shot_tags(["room/desk-front-christmas-9x16", "figures/x"])
    assert tags == {"christmas"}
    assert shot_tags(["room/window-wall-9x16"], motions=["window-rain"]) \
        == {"window-rain"}
    assert shot_tags(["room/desk-front-9x16"]) == set()

    layers = set_layers(settings, [(0.0, 5.0, set()),
                                   (5.0, 9.0, {"window-rain"}),
                                   (9.0, 12.0, {"christmas"})])
    assert [(t.path.name, t.start_s, t.max_s) for t in layers] == [
        ("rain_window.wav", 5.0, 4.0), ("winter_room.wav", 9.0, 3.0)]
    assert all(t.loop and t.gain_db < -30 for t in layers)


# ------------------------------------------------------------ the cues


def test_every_cut_swishes_and_the_payoff_lands(assets):
    root, settings = assets
    tracks, drops = structure_cues(CUTS, settings,
                                   Voicing(root / "sfx", "seed"), chapters=False)
    names = [t.name for t in tracks]
    assert names[0] == "hook_hit@0.00", "the first frame lands with a hit"
    assert names[-2] == "payoff_hit@12.80"

    swishes = [t for t in tracks if t.name.startswith(CUT_KEY)]
    # Every cut but the payoff, which gets the hit instead.
    assert [round(t.start_s + CUT_LEAD_S, 2) for t in swishes] == [5.0, 12.0, 18.0]
    # A quick shot gets a quick swish: 0.8s on screen, cut at half of it.
    quick = next(t for t in swishes if abs(t.start_s + CUT_LEAD_S - 12.0) < 1e-6)
    assert quick.max_s == pytest.approx(0.4)
    assert all(0 < t.max_s <= 0.45 for t in swishes)
    assert all(t.gain_db < settings.sfx_gain_db for t in swishes), \
        "a swish on every cut is punctuation, it sits under the writer's cues"

    assert drops == [(12.8 - DROP_S, 12.8)]


def test_the_drop_silences_everything_but_the_voice(assets, tmp_path):
    root, settings = assets
    tracks = short_mix(FakeTTS(_voice(tmp_path / "v.m4a")), settings,
                       cuts=CUTS, hour="night", seed="s")
    for t in tracks:
        if t.loop:
            assert t.gaps == ((12.8 - DROP_S, 12.8),), t.name
        else:
            assert t.gaps == (), t.name


def test_a_chaptered_format_hits_on_each_chapter_and_nothing_else(assets):
    root, settings = assets
    cuts = [Cut("ch1-open", 0.0, 4.0, chapter_n=1),
            Cut("ch1-a", 4.0, 9.0, chapter_n=1),
            Cut("ch2-open", 9.0, 14.0, chapter_n=2),
            Cut("ch2-a", 14.0, 20.0, chapter_n=2)]
    tracks, drops = structure_cues(cuts, settings,
                                   Voicing(root / "sfx", "seed"), chapters=True)
    assert [t.name for t in tracks] == ["chapter_hit@0.00", "chapter_hit@9.00"]
    assert all(t.path.stem.startswith(HIT_KEY) for t in tracks)
    assert drops == []


# ---------------------------------------------------------- design's moves

# Design's rebuild-39 timing, in seconds from each move's first frame: the
# frame the picture finishes on. Copied from the contract rather than read
# from the table under test, so a slip in the table fails here.
DESIGN_LANDS_S = {
    "count-up": 0.500, "line-draw": 0.750, "highlight": 0.417,
    "pen-circle": 0.583, "zoom-to-slot": 0.917, "slide-in": 0.417,
    "bars-grow": 0.583, "card-pin": 0.583, "tick-over": 0.250,
}


def test_every_move_sounds_on_design_s_frames(assets):
    """A drawn sound runs with the drawing and stops on the frame it finishes;
    a struck one lands on the frame. One move at a time, well clear of any
    cut, so nothing is thinned out."""
    root, settings = assets
    assert set(MOVE_CUES) == set(DESIGN_LANDS_S)
    for move, lands in DESIGN_LANDS_S.items():
        [tr] = move_cues([Move(move, 3.0)], settings,
                         Voicing(root / "sfx", move), cuts=CUTS)
        cue = MOVE_CUES[move]
        assert tr.path.stem.split("-")[0] == cue.key, move
        if cue.drawn:
            assert tr.start_s == pytest.approx(3.0), move
            assert tr.max_s == pytest.approx(lands), move
        else:
            assert tr.start_s == pytest.approx(3.0 + lands), move
            assert tr.max_s == 0.0, move
        assert tr.gain_db < settings.sfx_gain_db - 8.0, \
            "a move is detail inside a shot: it sits under the cut's swish"


def test_moves_make_fewer_sounds_than_moves(assets):
    """What the picture plays is not all heard: a move that opens with its
    shot is the cut's swish already, the payoff's half-second of nothing
    stays nothing, a burst of moves is one sound, and a looping move is the
    room's job."""
    root, settings = assets
    moves = [
        Move("zoom-to-slot", 5.05),     # opens with the cut at 5.0
        Move("count-up", 7.0),
        Move("highlight", 7.3),         # inside MOVE_GAP_S of the count-up
        Move("pen-circle", 12.4),       # runs into the payoff's drop
        Move("window-rain", 14.0),      # a loop: set layer, not a cue
        Move("tick-over", 15.0),
    ]
    _, drops = structure_cues(CUTS, settings, Voicing(root / "sfx", "s"),
                              chapters=False)
    tracks = move_cues(moves, settings, Voicing(root / "sfx", "s"),
                       cuts=CUTS, drops=drops)
    assert [t.name for t in tracks] == ["move:count-up@7.00",
                                        "move:tick-over@15.25"]
    assert 7.3 - 7.0 < MOVE_GAP_S


def test_a_short_plays_its_moves_under_its_cuts(assets, tmp_path):
    root, settings = assets
    tracks = short_mix(FakeTTS(_voice(tmp_path / "v.m4a")), settings,
                       cuts=CUTS, seed="s", moves=[Move("count-up", 7.0)])
    assert "move:count-up@7.00" in [t.name for t in tracks]
    assert not any(t.name.startswith("move:") for t in short_mix(
        FakeTTS(_voice(tmp_path / "w.m4a")), settings, cuts=CUTS, seed="s"))


# ---------------------------------------------------------- the variation


def test_no_effect_plays_the_same_take_twice_running(assets):
    root, settings = assets
    sfx = root / "sfx"
    for i in (2, 3):
        shutil.copy(sfx / "whoosh.wav", sfx / f"whoosh-{i}.wav")
    assert [p.name for p in variants(sfx, "whoosh")] == [
        "whoosh.wav", "whoosh-2.wav", "whoosh-3.wav"]

    v = Voicing(sfx, "a video")
    fired = [v.fire("whoosh", float(i), -14.0) for i in range(30)]
    takes = [t.path.name for t in fired]
    assert all(a != b for a, b in zip(takes, takes[1:])), takes
    assert len(set(takes)) == 3
    assert all(abs(t.rate - 1.0) <= RATE_SPREAD + 1e-9 for t in fired)
    assert all(abs(t.trim_db) <= TRIM_SPREAD_DB + 1e-9 for t in fired)
    assert len({t.rate for t in fired}) > 1, "the pitch never moved"
    # The staged level is what the manifest reports; the trim rides on top.
    assert all(t.gain_db == -14.0 for t in fired)

    again = Voicing(sfx, "a video")
    assert [again.fire("whoosh", float(i), -14.0).path.name
            for i in range(30)] == takes, "one video must sound the same twice"


def test_the_theme_never_varies(settings, tmp_path):
    """The one thing a viewer is meant to learn plays the same every time."""
    score = tmp_path / "assets" / "score"
    score.mkdir(parents=True)
    _tone(score / "theme-intro.m4a", "sine=f=330:d=6")
    _tone(score / "theme-outro.m4a", "sine=f=330:d=10")
    s = settings.model_copy(update={"assets_dir": tmp_path / "assets"})

    tracks = theme_tracks(s, duration=60.0)
    assert [t.name for t in tracks] == ["theme_intro@0.00", "theme_outro@50.00"]
    assert all(t.rate == 1.0 and t.trim_db == 0.0 for t in tracks)
    assert all(t.duck for t in tracks), "dipped under the voice, not over it"
    assert tracks[1].start_s + 10.0 == pytest.approx(60.0), \
        "the outro ends with the video"


# --------------------------------------------------------------- the loop


def test_a_short_gets_one_owned_loop_and_not_the_last_ones(settings, tmp_path):
    score = tmp_path / "assets" / "score"
    score.mkdir(parents=True)
    for i in (1, 2, 3):
        _tone(score / f"bed-{i}.m4a", f"sine=f={200 + i * 50}:d=4")
    s = settings.model_copy(update={"assets_dir": tmp_path / "assets"})

    bed = bed_track(s, "seed")
    assert bed.duck and bed.loop and bed.name == "bed"
    assert bed.gain_db == s.short_bed_gain_db
    for seed in ("a", "b", "c", "d", "e"):
        got = bed_track(s, seed, avoid={"bed-1.m4a", "bed-2.m4a"})
        assert got.path.name == "bed-3.m4a"
    # Everything recent: it still plays something rather than nothing.
    assert bed_track(s, "x", avoid={f"bed-{i}.m4a" for i in (1, 2, 3)})
    assert bed_track(s.model_copy(update={"short_bed": False}), "x") is None


def test_no_score_no_loop_and_the_long_never_gets_one(settings, tmp_path):
    assert bed_track(settings, "seed") is None or \
        (settings.assets_dir / "score").is_dir()
    score = tmp_path / "assets" / "score"
    score.mkdir(parents=True)
    _tone(score / "bed-1.m4a", "sine=f=300:d=4")
    shutil.copytree(ROOT / "assets" / "sfx", tmp_path / "assets" / "sfx")
    s = settings.model_copy(update={"assets_dir": tmp_path / "assets"})
    voice = _voice(tmp_path / "v.m4a")
    short = short_mix(FakeTTS(voice), s, cuts=CUTS, seed="x")
    long = short_mix(FakeTTS(voice), s, cuts=CUTS, seed="x", chapters=True)
    assert any(t.name == "bed" for t in short)
    assert not any(t.name == "bed" for t in long)


# ------------------------------------------------------------ the file itself


def test_the_mix_goes_under_the_picture_at_the_streaming_target(settings, tmp_path):
    """MEASURED OFF THE FILE. The voice ends a second early, which is the
    gap between sentences: the room has to fill it, the whole programme has
    to land at the -14 LUFS YouTube plays at, and the picture must come
    through untouched."""
    picture = _picture(tmp_path / "picture.mp4", 3.0)
    voice = _voice(tmp_path / "voice.m4a")
    tracks = short_mix(FakeTTS(voice), settings)
    out = tmp_path / "short.mp4"

    mix_under_picture(picture, tracks, out, duration=3.0, audio_bitrate="128k",
                      normalise=True, graph_path=tmp_path / "mix.filter.txt")

    graph = (tmp_path / "mix.filter.txt").read_text(encoding="utf-8")
    assert "acompressor=" in graph and "loudnorm=I=-14.0" in graph
    assert "alimiter=" in graph

    streams = _streams(out)
    assert streams["audio"]["codec_name"] == "aac"
    assert streams["video"]["codec_name"] == _streams(picture)["video"]["codec_name"]
    assert abs(float(streams["audio"]["duration"]) - 3.0) < 0.1
    assert not _silences(out), "the gap after the sentence went to digital silence"
    assert abs(_integrated_lufs(out) - (-14.0)) < 2.0


def test_music_dips_under_the_voice_and_the_drop_is_silent(tmp_path):
    """The graph, measured: a loop that sits at one level under speech buries
    the quiet lines, and a drop that still has room tone in it is not a drop.

    The voice speaks for two seconds and stops; the loop runs throughout; the
    drop is a half-second after the voice has stopped."""
    picture = _picture(tmp_path / "p.mp4", 5.0)
    voice = _voice(tmp_path / "v.m4a", "sine=f=220:d=2,apad=pad_dur=3")
    loop = _tone(tmp_path / "loop.wav", "sine=f=600:d=1")
    out = tmp_path / "o.mp4"
    tracks = [AudioTrack(path=voice, voice=True, name="voice"),
              AudioTrack(path=loop, loop=True, duck=True, gain_db=-10.0,
                         gaps=((3.5, 4.0),), name="bed")]
    mix_under_picture(picture, tracks, out, duration=5.0, audio_bitrate="128k",
                      normalise=False, graph_path=tmp_path / "g.txt")
    graph = (tmp_path / "g.txt").read_text(encoding="utf-8")
    assert "sidechaincompress" in graph

    # Isolate the loop: bandpass around it, so the voice does not count.
    only_loop = tmp_path / "loop_only.wav"
    run_ffmpeg(["-i", str(out), "-af", "bandpass=f=600:width_type=h:w=100",
                "-c:a", "pcm_s16le", str(only_loop)])
    under_voice = _rms_db(only_loop, 0.8, 1.8)
    alone = _rms_db(only_loop, 2.6, 3.3)
    dropped = _rms_db(only_loop, 3.6, 3.9)
    assert alone - under_voice > 4.0, (under_voice, alone)
    assert dropped < alone - 40.0, (alone, dropped)


def test_the_music_outlives_the_voice_and_keeps_its_width(tmp_path):
    """The end-card theme plays after the sign-off, so the music has to run
    past the voice's last sample. An unpadded key stopped the compressor,
    and the theme with it, the moment the voice file ended. The voice here
    is a bare two seconds, not padded to the picture as the test above is.

    And the mix is stereo at 48 kHz: left to negotiate, a mono voice folded
    the programme to mono, and loudnorm's 192 kHz reached the encoder."""
    picture = _picture(tmp_path / "p.mp4", 5.0)
    voice = _voice(tmp_path / "v.m4a", "sine=f=220:d=2")
    theme = _tone(tmp_path / "theme.wav", "sine=f=600:d=6")
    out = tmp_path / "o.mp4"
    tracks = [AudioTrack(path=voice, voice=True, name="voice"),
              AudioTrack(path=theme, duck=True, gain_db=-10.0, name="theme")]
    mix_under_picture(picture, tracks, out, duration=5.0, audio_bitrate="128k",
                      normalise=True)

    audio = _streams(out)["audio"]
    assert abs(float(audio["duration"]) - 5.0) < 0.1, audio["duration"]
    assert audio["channels"] == 2 and audio["sample_rate"] == "48000"
    only_theme = tmp_path / "theme_only.wav"
    run_ffmpeg(["-i", str(out), "-af", "bandpass=f=600:width_type=h:w=100",
                "-c:a", "pcm_s16le", str(only_theme)])
    assert _rms_db(only_theme, 3.0, 4.8) > -40.0, "the theme stopped with the voice"


def test_a_placeholder_mix_is_limited_but_not_normalised(settings, tmp_path):
    picture = _picture(tmp_path / "picture.mp4", 2.0)
    voice = _voice(tmp_path / "voice.m4a", "sine=f=220:d=2")
    out = tmp_path / "short.mp4"
    mix_under_picture(picture, short_mix(FakeTTS(voice), settings), out,
                      duration=2.0, audio_bitrate="128k", normalise=False,
                      graph_path=tmp_path / "mix.filter.txt")
    graph = (tmp_path / "mix.filter.txt").read_text(encoding="utf-8")
    assert "loudnorm" not in graph and "alimiter=" in graph
    assert out.exists()


def test_a_mix_with_nothing_in_it_is_refused(tmp_path):
    from pipeline.render_common import RenderError

    with pytest.raises(RenderError):
        mix_under_picture(tmp_path / "p.mp4", [], tmp_path / "o.mp4",
                          duration=1.0, audio_bitrate="128k", normalise=True)


# ------------------------------------------------------ what the operator reads


def test_the_delivery_line_says_what_the_mix_did():
    from pipeline.provenance import Provenance

    rows = [{"name": "voice", "start": 0, "gain_db": 0, "loop": False, "file": "v"},
            {"name": "room_tone", "start": 0, "gain_db": -40, "loop": True,
             "file": "room_night.wav"},
            {"name": "bed", "start": 0, "gain_db": -24, "loop": True,
             "file": "bed-2.m4a"},
            {"name": "hook_hit@0.00", "start": 0, "gain_db": -6, "loop": False,
             "file": "impact.wav"},
            {"name": "whoosh@4.90", "start": 4.9, "gain_db": -14, "loop": False,
             "file": "whoosh-2.wav"},
            {"name": "rain_window@5.00", "start": 5, "gain_db": -34, "loop": True,
             "file": "rain_window.wav"}]
    summary = sound_summary(rows, lufs=-14.04, placeholders=0)
    assert summary == {"lufs": -14.0, "effects": 2, "bed": "bed-2.m4a",
                       "theme": False, "room": "room_night.wav",
                       "placeholders": 0}
    line = Provenance(sound=summary).render_text()
    assert "sound     -14.0 LUFS · 2 effects · loop bed-2 · all sounds real" in line
    fake = Provenance(sound=dict(summary, placeholders=3)).render_text()
    assert "3 PLACEHOLDER SOUNDS" in fake


# ------------------------------------------------------------- a real render


def test_a_rendered_short_carries_its_mix(settings, tmp_path, short_valid_json):
    """End to end, on the mock voice: the manifest says what was mixed, the
    cues sit on the cuts the render actually made, and the file has a sound
    floor under the whole cut."""
    from pipeline.parser_short import parse_short_script
    from pipeline.render_short import render_short
    from pipeline.tts import TTSEngine

    script, _ = parse_short_script(short_valid_json, settings)
    tts = TTSEngine(settings).synthesize(script.audio_script, "short")
    out, manifest_path = render_short(script, tts, tmp_path, settings)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    names = [a["name"] for a in manifest["audio"]]
    assert names[:2] == ["voice", "room_tone"]
    assert manifest["audio"][1]["file"] == f"room_{manifest['hour']}.wav"
    assert "hook_hit@0.00" in names

    starts = [s["start_s"] for s in manifest["shots"]][1:]
    cues = sorted(a["start"] for a in manifest["audio"]
                  if a["name"].startswith((CUT_KEY, "payoff_hit")))
    assert len(cues) == len(starts), (starts, names)
    for want, got in zip(starts, cues):
        assert got == pytest.approx(want, abs=CUT_LEAD_S + 0.02)

    assert "audio" in _streams(out)
    assert not _silences(out), "a short went to digital silence between words"
    sound = manifest["provenance"]["sound"]
    assert sound["effects"] == len(cues) + 1
    assert sound["placeholders"] > 0, "the shipped effects are oscillators"
