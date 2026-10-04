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


# --- the writer's poses (item 47, phase 2)

def test_every_kit_pose_has_a_stance_built_from_poses_and_hands_that_exist():
    import json
    kit = json.loads((ROOT / "kit" / "roles.json").read_text())["hostPoses"]
    for key in kit:
        assert key.split("/", 1)[1] in motion.STANCES, f"{key} has no 3D stance"
    for name, st in motion.STANCES.items():
        for side, (arm, hand) in st.home.items():
            assert side in "LR"
            motion._arm(arm, 1)                    # raises on a pose that is not there
            assert hand in motion.HANDS, f"{name}: no hand shape {hand}"
        assert set(st.free) <= set("LR")
        if st.prop:
            assert st.home.get(st.prop_side), f"{name}: nothing holds the {st.prop}"
            assert st.prop_side not in st.free, f"{name}: the hand with the {st.prop} talks"
    assert motion.stance_of("host/arms-crossed-talk") is motion.STANCES["arms-crossed"]
    assert motion.stance_of("host/no-such-pose") is motion.STANCES["to-camera"]


def test_a_mirrored_stance_plays_with_the_other_hands():
    lean = motion.STANCES["leaning-on-desk"]
    m = motion.mirrored(lean)
    assert m.home == {"R": ("desk", "open")} and m.free == "L" and m.hand == "L"
    assert motion.mirrored(m) == lean


def test_a_pose_of_the_writers_is_held_through_a_shot_with_no_words():
    perf = motion.perform([], 3.0, fps=12, seed="t", stance="host/arms-crossed")
    low = motion._arm("crossed-low", 1)
    high = motion._arm("crossed-high", -1)
    for i in range(perf.frames):
        f = perf.at(i)
        assert f["elbow.L.x"] == low["elbow"][0] and f["elbow.R.x"] == high["elbow"][0]
        assert abs(f["shoulder.L.z"] - low["shoulder"][2]) < 1e-9


def test_he_leans_at_the_hips_and_his_legs_stay_under_him():
    perf = motion.perform([], 1.0, fps=12, seed="t", stance="leaning-on-desk")
    f = perf.at(5)
    assert f["hips.x"] == 10.0 and f["thigh.L.x"] == -10.0 and f["thigh.R.x"] == -10.0
    straight = motion.perform([], 1.0, fps=12, seed="t").at(5)
    assert straight["hips.x"] == 0.0


def test_hands_in_pockets_are_not_drawn_until_they_come_out():
    perf = motion.perform([], 2.0, fps=12, seed="t", stance="hands-in-pockets")
    assert all(perf.channels["pocket.L"]) and all(perf.channels["pocket.R"])
    talk = motion.perform(LINE, LINE[-1].end + 1.2, fps=12, seed="t")
    assert not any(talk.channels["pocket.L"])


def test_turned_to_the_screen_his_body_goes_some_of_the_way_and_his_eyes_stay():
    perf = _perf(looks={"screen": SCREEN}, stance="turn-to-screen")
    hips = perf.channels["hips.z"]
    turn = 0.35 * SCREEN.yaw
    assert all(abs(h - turn) < 3.0 for h in hips), "the turn holds under the weight shifts"
    head = [n + h + c for n, h, c in zip(perf.channels["neck.z"], perf.channels["head.z"],
                                         perf.channels["chest.z"])]
    # with the body turned, the head's own turn left over: mostly toward it
    on_it = sum(1 for y in head if y + turn > SCREEN.yaw * 0.6)
    assert on_it > len(head) * 0.5


def test_counting_puts_a_finger_up_for_each_word_he_leans_on():
    line = _line("Three things: revenue, margin and cash.")
    perf = motion.perform(line, line[-1].end + 1.0, fps=12, seed="t",
                          stance="counting-on-fingers")
    marks = motion.stressed(line)
    after = lambda t: perf.at(min(int((t + 0.15) * 12), perf.frames - 1))
    assert after(marks[0].start)["curl.L.middle"] == 100     # one finger up
    assert after(marks[1].start)["curl.L.middle"] == 0       # two
    assert after(marks[0].start)["elbow.R.x"] != 0           # the other hand is up


def test_head_in_hands_keeps_his_mouth_still():
    perf = _perf(stance="head-in-hands")
    mouths = [k for k in perf.channels if k.startswith("mouth.")]
    assert mouths and all(v == 0.0 for k in mouths for v in perf.channels[k])


def test_in_close_up_he_points_at_nothing_and_looks_down_the_lens():
    perf = _perf(looks={"screen": SCREEN}, stance="host/close-up")
    yaw = [n + h for n, h in zip(perf.channels["neck.z"], perf.channels["head.z"])]
    assert max(abs(y) for y in yaw) < 12, "no turn to the screen"
    pointing = [perf.channels[f"curl.R.middle"][i] == 100 and perf.channels["curl.R.index"][i] == 0
                for i in range(perf.frames)]
    assert not any(pointing)


def test_in_close_up_his_hands_talk_under_the_frame():
    """A hand brought up to the chest comes into a close-up at its edge,
    palm out and cut off, and reads as a wave. In close-up his hands talk at
    the belt: the arm still moves on the words, under the frame."""
    perf = _perf(stance="host/close-up")
    for side in "LR":
        assert min(perf.channels[f"shoulder.{side}.x"]) > -22, f"{side} hand came up"
    assert min(min(perf.channels["elbow.L.x"]), min(perf.channels["elbow.R.x"])) < -45, \
        "and they do still talk"
