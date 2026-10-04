"""3D Dennis's performance of a line (item 47): plain numbers, no Blender."""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("dennis_motion", ROOT / "room3d" / "motion.py")
motion = importlib.util.module_from_spec(_spec)
sys.modules["dennis_motion"] = motion
_spec.loader.exec_module(motion)


@dataclass
class W:
    word: str
    start: float
    end: float


def _line(text: str, *, at: float = 0.5, rate: float = 0.28, pause: float = 0.35) -> list[W]:
    out, t = [], at
    for w in text.split():
        out.append(W(w, round(t, 3), round(t + rate - 0.03, 3)))
        t += rate + (pause if w[-1] in ".?!," else 0.0)
    return out


LINE = _line("So the company calls this buyback a gift. Look at the screen. "
             "Five years, and the share count went up. So who is paying for it?")
SCREEN = motion.Look(yaw=50.0, pitch=-8.0, side="R",
                     point={"shoulder": (-32, -90, 0), "elbow": (-25, 0, 0), "wrist": (0, 0, 0)})


def _perf(**kw):
    return motion.perform(LINE, LINE[-1].end + 1.2, fps=12, seed="t", **kw)


def test_the_line_is_cut_at_commas_for_the_head_and_at_sentences_for_the_hands():
    small = motion.phrases(LINE)
    big = motion.phrases(LINE, marks=".?!", gap=motion.SENTENCE_GAP_S)
    assert [p.text for p in big][1] == "Look at the screen."
    assert len(small) == len(big) + 1          # "Five years," is a phrase, not a sentence
    assert big[-1].question and not big[0].question


def test_he_leans_on_content_words_never_two_at_once():
    picks = motion.stressed(LINE)
    words = [w.word.strip(".,?") for w in picks]
    assert "company" in words and "buyback" in words
    assert not {"the", "a", "this"} & set(words)
    assert all(b.start - a.start >= 0.5 for a, b in zip(picks, picks[1:]))


def test_every_channel_runs_the_whole_shot_and_a_rerender_moves_the_same():
    a, b = _perf(), _perf()
    assert all(len(v) == a.frames for v in a.channels.values())
    assert a.channels == b.channels
    other = motion.perform(LINE, LINE[-1].end + 1.2, fps=12, seed="another")
    assert other.channels != a.channels


def test_the_mouth_moves_with_the_words_and_shuts_in_silence():
    p = _perf()
    open_ = [max(p.channels[f"mouth.{m}"][i] for m in motion.MOUTHS[1:]) for i in range(p.frames)]
    assert max(open_[: int(0.4 * 12)]) == 0, "his mouth moved before he spoke"
    assert max(open_[-6:]) == 0, "his mouth moved after he finished"
    talking = [open_[i] for i in range(p.frames) if LINE[0].start <= i / 12 <= LINE[-1].end]
    assert sum(v > 0.5 for v in talking) > len(talking) / 3


def test_he_turns_and_points_when_he_names_the_screen():
    p = _perf(looks={"screen": SCREEN})
    look = next(s for s in motion.phrases(LINE, marks=".?!", gap=0.45) if "screen" in s.text)
    mid = int((look.start + 0.35) * 12)
    assert p.channels["head.z"][mid] > 15, "he did not turn to the screen"
    assert p.channels["shoulder.R.y"][mid] < -60, "his arm did not go out to it"
    assert p.channels["curl.R.middle"][mid] > 60 and p.channels["curl.R.index"][mid] < 10
    assert abs(p.channels["head.z"][-1]) < 6, "he never looked back at the camera"
    # without a screen in the shot he does not point at nothing
    plain = _perf()
    assert plain.channels["shoulder.R.y"][mid] > -40


def test_a_question_ends_in_a_shrug_with_the_brows_up():
    p = _perf()
    q = motion.phrases(LINE, marks=".?!", gap=0.45)[-1]
    i = int((q.words[-1].start + 0.1) * 12)
    assert p.channels["lift.L"][i] > 0.015 and p.channels["lift.R"][i] > 0.015
    assert p.channels["brow"][i] > 0.8


def test_he_moves_while_he_talks_and_rests_at_the_end():
    p = _perf()
    talk = [i for i in range(p.frames) if LINE[0].start <= i / 12 <= LINE[-1].end]
    for ch in ("elbow.L.x", "elbow.R.x"):
        assert min(p.channels[ch]) < -60, f"{ch}: that hand never came up"
    assert max(p.channels["head.x"][i] for i in talk) > 3, "no nods"
    assert max(p.channels["blink"]) == 1.0
    end = p.at(p.frames - 1)
    assert abs(end["elbow.L.x"] - (-14)) < 3 and abs(end["elbow.R.x"] - (-14)) < 3, \
        "his hands did not come down when he finished"
