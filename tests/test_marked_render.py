"""A marked script, cut: in the order its markers name, each beat on its own
words, and a beat that runs long recorded as both of its parts.

The frames are not drawn here. What is under test is the wiring in
`_render_short` — which order is picked, which words each shot waits for, and
what the manifest says about it — and drawing two thousand frames to learn
that takes minutes. `render_frames` is stood in for by a blank clip of the
right length, and the frame measurement that reads it is stood in for by an
empty list. Everything between the script and the manifest is real.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from pipeline.models import TTSResult
from pipeline.parser_short import parse_short_script
from pipeline.tts import mock_words

# Where each beat of the fixture starts, marked so the news comes before the
# move — the order the short template declares as `news-first`.
_MARKS = (
    ("EXMPL is up twenty nine", "hook"),
    ("The news is an AI", "headline"),
    ("A press release, not", "move"),
    ("Plus squeeze chatter", "turn"),
    ("Revenue went four hundred", "numbers"),
    ("Then the share count.", "numbers_comment"),
    ("Eleven times earnings", "cheap_or_trap"),
    ("Noise. A press release", "conclusion"),
)

# The shot each marked beat starts, in the short template.
_SHOT_OF = {"hook": "hook", "headline": "the-news", "move": "the-move",
            "turn": "the-turn", "numbers": "numbers-1",
            "numbers_comment": "the-sheet", "cheap_or_trap": "cheap-or-trap",
            "conclusion": "payoff"}


def _marked(short_valid_json: str) -> str:
    data = json.loads(short_valid_json)
    text = data["audio_script"]
    for words, key in _MARKS:
        assert text.count(words) == 1, words
        text = text.replace(words, f"[BEAT: {key}] {words}")
    data["audio_script"] = text
    return json.dumps(data)


def _voice(script, duration: float, workdir: Path) -> TTSResult:
    """A silent track of `duration` with mock word timings over it.

    Built here rather than asked of the TTS engine, which may reach for the
    local neural voice when a box has one — and whose pace would then decide
    which beats run long.
    """
    audio = workdir / "voice.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                    "-i", "anullsrc=r=44100:cl=mono", "-t", f"{duration:.2f}",
                    str(audio)], check=True)
    return TTSResult(audio_path=audio,
                     words=mock_words(script.audio_script, duration),
                     duration_s=duration, chars=script.char_count,
                     cached=False, cost_usd=0.0, tier="mock")


@pytest.fixture(scope="module")
def cut(tmp_path_factory):
    """One render, read by every test below."""
    import pipeline.render_short as rs
    from config import Settings

    tmp = tmp_path_factory.mktemp("marked")
    settings = Settings(MOCK_MODE=True, DATA_STALE_BLOCKS=False,
                        workspace_dir=tmp / "workspace", cache_dir=tmp / "cache",
                        state_dir=tmp / "state", short_width=270,
                        short_height=480, _env_file=None)
    settings.ensure_runtime_dirs()
    raw = (Path(__file__).resolve().parents[1] / "fixtures" / "scripts"
           / "short_valid.json").read_text(encoding="utf-8")
    script, _ = parse_short_script(_marked(raw), settings)
    # Slow enough that the beats run past their ceilings, which is the case
    # a split exists for.
    duration = round(script.word_count / 1.5, 2)
    ws = settings.workspace_dir / "EXMPL" / "2026-07-01"
    ws.mkdir(parents=True)
    tts = _voice(script, duration, tmp)

    def blank(result, resolver, duration, out, settings, **_kw):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                        "-i", f"color=c=white:s=270x480:r=10:d={duration:.2f}",
                        "-pix_fmt", "yuv420p", str(out)], check=True)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(rs, "render_frames", blank)
        mp.setattr(rs, "held_over_ceiling", lambda *a, **k: [])
        _out, manifest = rs.render_short(script, tts, ws, settings, proof=True)
    return script, tts, json.loads(Path(manifest).read_text(encoding="utf-8"))


def test_a_marked_script_is_cut_in_the_order_its_markers_name(cut):
    script, _tts, manifest = cut
    assert manifest["shot_order"] == "news-first"
    assert manifest["beat_order"] == [key for _w, key in _MARKS]
    ids = [s["id"] for s in manifest["shots"]]
    assert ids[0] == "hook"
    assert ids.index("the-news") < ids.index("the-move")


def test_every_marked_beat_starts_on_the_word_after_its_marker(cut):
    script, tts, manifest = cut
    by_id = {s["id"]: s for s in manifest["shots"]}
    for mark in script.beat_marks:
        if mark.key == "hook":
            continue
        spoken = next(w for w in tts.words if w.char_start >= mark.char_offset)
        shot = by_id[_SHOT_OF[mark.key]]
        assert shot["anchored"], mark.key
        assert shot["start_s"] == pytest.approx(spoken.start, abs=1e-3), \
            mark.key


def test_a_beat_that_runs_long_is_in_the_manifest_as_both_its_parts(cut):
    _script, _tts, manifest = cut
    shots = manifest["shots"]
    seconds = [s for s in shots if s.get("part") == 2]
    assert seconds, "nothing ran long enough to be split"
    for second in seconds:
        i = shots.index(second)
        first = shots[i - 1]
        assert first["id"] == second["part_of"]
        assert first["part"] == 1
        assert first["plate"] == second["plate"]
        assert first["end_s"] == pytest.approx(second["start_s"])
        # The beat after it still starts on its own words.
        if i + 1 < len(shots):
            assert shots[i + 1]["start_s"] == pytest.approx(second["end_s"])
    assert manifest["shots_count"] == len(shots)
