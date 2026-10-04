"""How Dennis moves while he talks (item 47).

A line's word timings in, his performance out: every joint angle, his mouth,
his blinks and his brows, frame by frame, as plain numbers, so nothing here
needs Blender and every choice can be tested. `dennis.Rig.play` puts a
performance on the puppet.

What drives what:

* THE MOUTH follows the letters, through the same reading of a word as the
  drawn Dennis (`pipeline.host.mouth_track`), but read twelve times a second
  and eased from shape to shape, because a 3D mouth can move between its
  shapes where a drawn one can only swap.
* STRESSED WORDS (long content words, figures, the first word after a pause)
  get a nod, a lift of the brows and, while a hand is up, a beat of the hand.
  The hand lands a little before the word, the way people do it.
* PHRASES (cut at punctuation and pauses) each get one gesture: one hand or
  both up and beating, a shrug on a question, a point and a turn of the head
  when the phrase names the screen or the board, or, now and then, nothing,
  so he is not waving all the time. Between phrases the hands come down when
  there is time to.
* UNDER EVERYTHING he breathes, shifts his weight now and then, blinks every
  few seconds, and his head never quite holds still.

Every random choice is seeded by the line, so a re-render moves the same way.
"""
from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass, field, replace
from typing import Sequence

FPS = 30

# The six mouths, in dennis.MOUTHS order; the first is the basis (shut).
MOUTHS = ("mouthClosed", "mouthMid", "mouthWide", "mouthO", "mouthEE", "mouthFV")
MOUTH_HOLD_S = 1.0 / 12          # a 3D mouth may change twelve times a second
MOUTH_EASE_S = 0.05              # and takes this long to go from one to the next

# Arms, as (shoulder, elbow, wrist) angles in degrees over the rest pose; `ab`
# is +1 for the left arm and -1 for the right, because the left arm opens
# away from the body on +y and the right on -y.
def _arm(name: str, ab: int) -> dict[str, tuple[float, float, float]]:
    return {
        # hanging at his side, a little away from the body
        "rest": {"shoulder": (4, 7 * ab, 0), "elbow": (-14, 0, 0), "wrist": (0, 0, 0)},
        # up in front of him, the hand at his chest, turned in a little: talking.
        # The wrist turns the palm half to the camera: edge on, an open hand
        # reads as a paddle.
        "ready": {"shoulder": (-32, 9 * ab, 10 * ab), "elbow": (-90, 0, 0),
                  "wrist": (-10, 0, -45 * ab)},
        # the close-up's talking hand: forward at the belt, under the frame,
        # so a beat moves his shoulder and no palm comes up at the frame's edge
        "low": {"shoulder": (-12, 8 * ab, 6 * ab), "elbow": (-60, 0, 0),
                "wrist": (-10, 0, -30 * ab)},
        # both hands up and apart, forward: laying something out
        "wide": {"shoulder": (-30, 18 * ab, 0), "elbow": (-88, 0, 0),
                 "wrist": (-15, 0, -60 * ab)},
        # elbows in, forearms out, palms up: who knows
        "shrug": {"shoulder": (-18, 14 * ab, -38 * ab), "elbow": (-100, 0, 0),
                  "wrist": (-10, 0, -75 * ab)},
        # THE WRITER'S POSES (item 47, phase 2): where an arm lives through
        # a whole shot when the [SCENE] puts him in one of the kit's poses.
        # Each was solved from where the hand has to be (two-bone IK on the
        # rig, the left arm; the right is its mirror), so a hand meant for a
        # pocket, a chin or the desk top lands there.
        # the hand down the front of the trouser pocket, the elbow out a little
        "pocket": {"shoulder": (15, 1 * ab, 55 * ab), "elbow": (-43, 0, 0),
                   "wrist": (12, -23 * ab, -60 * ab)},
        # arms crossed: the forearm underneath, its hand behind the other arm
        "crossed-low": {"shoulder": (0, 17 * ab, 67 * ab), "elbow": (-94, 0, 0),
                        "wrist": (-49, -1 * ab, -20 * ab)},
        # and the one over it, its hand round the other upper arm
        "crossed-high": {"shoulder": (-11, 18 * ab, 57 * ab), "elbow": (-99, 0, 0),
                         "wrist": (-54, -13 * ab, -29 * ab)},
        # the knuckles under the chin, the elbow down in front of him
        "chin": {"shoulder": (-39, 29 * ab, 42 * ab), "elbow": (-140, 0, 0),
                 "wrist": (5, 17 * ab, -45 * ab)},
        # the forearm across the belly, the hand cupping the other elbow
        "under": {"shoulder": (-8, 9 * ab, 51 * ab), "elbow": (-91, 0, 0),
                  "wrist": (13, -42 * ab, -108 * ab)},
        # a mug at the chest, upright in the palm
        "hold": {"shoulder": (0, 18 * ab, 26 * ab), "elbow": (-92, 0, 0),
                 "wrist": (0, -1 * ab, -18 * ab)},
        # a phone held up in front of him, its screen to his face, its back
        # over his fingers where the camera sees it
        "phone": {"shoulder": (-1, 14 * ab, 33 * ab), "elbow": (-91, 0, 0),
                  "wrist": (-53, 27 * ab, -91 * ab)},
        # a page at the waist, tipped up so he can read it
        "page": {"shoulder": (4, 14 * ab, 33 * ab), "elbow": (-90, 0, 0),
                 "wrist": (-29, 20 * ab, -99 * ab)},
        # the filing held up to the camera, a hand on each side of it
        "filing": {"shoulder": (-4, 19 * ab, 27 * ab), "elbow": (-98, 0, 0),
                   "wrist": (44, 45 * ab, 28 * ab)},
        # the hand flat on the desk top, the arm nearly straight, his weight
        # on it (with the stance's lean)
        "desk": {"shoulder": (15, 61 * ab, 72 * ab), "elbow": (-45, 0, 0),
                 "wrist": (35, -7 * ab, 14 * ab)},
        # the finger on the desk in front of him: this one
        "down-point": {"shoulder": (-21, 23 * ab, 14 * ab), "elbow": (-96, 0, 0),
                       "wrist": (-72, -68 * ab, 53 * ab)},
        # a palm on each cheek, the elbows down in front of him
        "face": {"shoulder": (-92, 30 * ab, -9 * ab), "elbow": (-141, 0, 0),
                 "wrist": (42, -18 * ab, -24 * ab)},
        # counting: one hand up at the chest, fingers up...
        "count-hand": {"shoulder": (-9, 18 * ab, 40 * ab), "elbow": (-91, 0, 0),
                       "wrist": (28, 53 * ab, 16 * ab)},
        # ...and the other's finger on them
        "count-point": {"shoulder": (-3, 26 * ab, 13 * ab), "elbow": (-109, 0, 0),
                        "wrist": (-35, 45 * ab, 21 * ab)},
    }[name]


HANDS = {"relaxed": (25, 30, 35, 40, 15), "open": (4, 2, 4, 8, 5),
         "point": (0, 95, 100, 100, 55), "fist": (100, 100, 100, 100, 60),
         # counting on his fingers, one to five
         "one": (0, 100, 100, 100, 60), "two": (0, 0, 100, 100, 60),
         "three": (0, 0, 0, 100, 60), "four": (0, 0, 0, 0, 60), "five": (4, 2, 4, 8, 5),
         # round a mug's handle, a phone, the edge of a page
         "grip": (70, 75, 80, 80, 40), "pinch": (35, 45, 55, 60, 30)}
FINGERS = ("index", "middle", "ring", "little", "thumb")

STOP = frozenset("""a an the and or but so to of in on at for with by from as is are was
were be been it its this that these those he she they we you i me my our your their
his her them us not no do does did have has had will would can could should just
than then there here what which who whom how why when where very really about
into over up down out off if""".split())
LOOK_WORDS = {"screen": ("screen", "chart", "monitor", "graph"),
              "board": ("board", "whiteboard", "list")}


@dataclass(frozen=True)
class Stance:
    """How one of the kit's poses (the writer's `[SCENE: ... | pose=...]`)
    plays in 3D:

    * `home`: where each arm lives (side -> (arm pose, hand shape)); an arm
      not named hangs at rest.
    * `free`: the hands that may talk; a hand holding something stays with it.
    * `talk`: how often a sentence gets one hand, both, or none.
    * `first`: what the first sentence does: "screen" or "board" (a point),
      "plate" (an open hand toward the evidence beside him, in a two-shot),
      "desk" (a finger on the desk), "count" (the fingers), "shrug".
    * `hand`: the hand that does the stance's one-handed business (the desk
      point, the counting finger).
    * `lean`: forward, at the hips, degrees.
    * `prop`, `prop_side`: what he holds and in which hand.
    * `glance`: how far down he looks to read the prop; `reads`: the share
      of sentences he reads it through.
    * `look`: what he keeps turning to ("screen", or "plate|screen" for the
      first of them that is there); `reach`: the arm on its side stays out
      toward it; `turn`: how much of the way his body turns.
    * `desk`: the arm pose whose hand has to come down on the desk top; on a
      spot with no desk in reach the stance cannot play (`perform.Stage.fit`).
    * `lens`: down the lens (the close-up): he points at nothing and turns
      to nothing, his hands mostly below the frame.
    * `talks`: False where his mouth is hidden or shut (head in hands)."""
    home: dict = field(default_factory=dict)
    free: str = "LR"
    talk: tuple[float, float, float] = (0.55, 0.25, 0.2)
    first: str = ""
    hand: str = "R"
    lean: float = 0.0
    prop: str = ""
    prop_side: str = "R"
    glance: float = 0.0
    reads: float = 0.45
    look: str = ""
    reach: bool = False
    turn: float = 0.0
    desk: str = ""
    lens: bool = False
    talks: bool = True


STANCES: dict[str, Stance] = {
    "to-camera": Stance(),
    "hands-in-pockets": Stance(home={"L": ("pocket", "fist"), "R": ("pocket", "fist")},
                               talk=(0.35, 0.0, 0.65)),
    "arms-crossed": Stance(home={"L": ("crossed-low", "grip"), "R": ("crossed-high", "grip")},
                           talk=(0.3, 0.0, 0.7)),
    # weight on one arm: the hand away from the monitor flat on the desk
    "leaning-on-desk": Stance(home={"L": ("desk", "open")}, free="R", talk=(0.55, 0.0, 0.45),
                              lean=10.0, desk="desk"),
    "considering": Stance(home={"R": ("chin", "grip"), "L": ("under", "grip")},
                          free="", talk=(0.0, 0.0, 1.0)),
    "pointing-down-at-desk": Stance(first="desk", lean=6.0, desk="down-point"),
    "turn-to-screen": Stance(first="screen", look="screen", turn=0.35),
    # the near arm out toward the graphic, reading it: the evidence beside
    # him in a two-shot, the screen in the room
    "checking-a-figure": Stance(look="plate|screen", reach=True, turn=0.2,
                                talk=(0.5, 0.0, 0.5)),
    # the PRESENT pose: the hand on the evidence's side open toward it
    "gesturing-at-plate": Stance(first="plate"),
    "counting-on-fingers": Stance(first="count"),
    "shrug": Stance(first="shrug"),
    "holding-a-mug": Stance(home={"R": ("hold", "grip")}, free="L", prop="mug",
                            talk=(0.6, 0.0, 0.4)),
    "holding-a-phone": Stance(home={"R": ("phone", "relaxed")}, free="L", prop="phone",
                              talk=(0.4, 0.0, 0.6), glance=-30.0, reads=0.85),
    "holding-a-page": Stance(home={"L": ("page", "pinch")}, free="R", prop="page",
                             prop_side="L", talk=(0.6, 0.0, 0.4), glance=-24.0),
    # held up to the camera in both hands: "it says so on page 96"
    "holding-a-filing": Stance(home={"L": ("filing", "pinch"), "R": ("filing", "pinch")},
                               free="", prop="filing", prop_side="L", talk=(0.0, 0.0, 1.0)),
    "head-in-hands": Stance(home={"L": ("face", "relaxed"), "R": ("face", "relaxed")}, free="",
                            talk=(0.0, 0.0, 1.0), talks=False),
}
# Kit poses with no 3D of their own yet play as the nearest one.
STANCES["sitting-at-desk"] = STANCES["leaning-on-desk"]
STANCES["walking-out-of-frame"] = replace(STANCES["hands-in-pockets"], talks=False)
# head and shoulders: the confession, the turn, the line a chapter rests on
STANCES["close-up"] = Stance(lens=True, talk=(0.45, 0.15, 0.4))


def mirrored(st: Stance) -> Stance:
    """The stance played with the other hands."""
    sw = {"L": "R", "R": "L"}
    return replace(st, home={sw[k]: v for k, v in st.home.items()},
                   free="".join(sorted(sw[c] for c in st.free)),
                   hand=sw[st.hand], prop_side=sw[st.prop_side])


def lean_channels(lean: float) -> dict[str, float]:
    """Bent forward at the hips, the legs kept straight under him."""
    return {"hips.x": lean, "thigh.L.x": -lean, "thigh.R.x": -lean}


def stance_of(pose: str) -> Stance:
    """The 3D stance for a kit pose key (`host/arms-crossed`, or bare)."""
    name = (pose or "").rsplit("/", 1)[-1]
    for suffix in ("-talk", "-idle", "-blink"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return STANCES.get(name, STANCES["to-camera"])


PHRASE_GAP_S = 0.22              # a pause this long ends a phrase
SENTENCE_GAP_S = 0.45            # a pause this long ends a gesture
HANDS_DOWN_GAP_S = 0.9           # a silence this long brings the hands down


@dataclass
class Performance:
    """Frame-by-frame channels: joint angles in degrees over the rest pose
    (`"head.x"`), mouth weights (`"mouth.mouthO"`), `"blink"` 0-1, `"brow"`
    0-1, shoulder lifts in metres (`"lift.L"`) and finger curls in degrees
    (`"curl.L.index"`)."""
    fps: int
    frames: int
    channels: dict[str, list[float]] = field(default_factory=dict)

    def at(self, i: int) -> dict[str, float]:
        return {k: v[i] for k, v in self.channels.items()}


@dataclass
class Look:
    """Where something he may turn to is, from where he stands: degrees of
    yaw (+ to his left as the camera sees it, the +x of his own frame) and
    pitch (+ up), the arm that reaches for it, and that arm's angles: `point`
    (the finger toward it, stopping short of it) and `present` (the hand up
    and out toward it, open: "this here")."""
    yaw: float
    pitch: float
    side: str = "R"
    point: dict[str, tuple[float, float, float]] = field(default_factory=dict)
    present: dict[str, tuple[float, float, float]] = field(default_factory=dict)


def _smooth(x: float) -> float:
    x = min(max(x, 0.0), 1.0)
    return x * x * x * (x * (6 * x - 15) + 10)


def _letters(w: str) -> str:
    return re.sub(r"[^a-z0-9]", "", w.lower())


@dataclass
class Phrase:
    words: list
    start: float
    end: float
    text: str

    @property
    def question(self) -> bool:
        return self.text.rstrip().endswith("?")


def phrases(words: Sequence, *, marks: str = ".,?!;:", gap: float = PHRASE_GAP_S) -> list[Phrase]:
    """The line cut at its punctuation and its pauses; with `marks=".?!"` and
    a longer `gap`, at its sentences (one gesture each, so a list of short
    phrases is not a flurry of hands)."""
    out: list[Phrase] = []
    cur: list = []
    end_mark = re.compile(f"[{re.escape(marks)}]$")
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        ends = end_mark.search(w.word.strip()) or nxt is None \
            or nxt.start - w.end >= gap
        if ends:
            out.append(Phrase(cur, cur[0].start, cur[-1].end, " ".join(x.word for x in cur)))
            cur = []
    return out


def stressed(words: Sequence) -> list:
    """The words he leans on: content words of five letters or more, figures,
    and the first word after a pause, no two within half a second (the longer
    wins)."""
    picks = []
    for i, w in enumerate(words):
        t = _letters(w.word)
        if not t or t in STOP:
            continue
        after_pause = i == 0 or w.start - words[i - 1].end >= PHRASE_GAP_S
        if len(t) >= 5 or any(c.isdigit() for c in t) or after_pause and len(t) >= 3:
            picks.append(w)
    kept: list = []
    for w in picks:
        if kept and w.start - kept[-1].start < 0.5:
            if len(_letters(w.word)) > len(_letters(kept[-1].word)):
                kept[-1] = w
            continue
        kept.append(w)
    return kept


class _Track:
    """A channel set that eases from one pose to the next: `go(t, pose, dur)`
    arrives at `pose` at `t`, having left the previous one at `t - dur`."""

    def __init__(self, start: dict[str, float]):
        self.keys: list[tuple[float, float, dict[str, float]]] = [(-1e9, 0.0, dict(start))]

    def go(self, t: float, pose: dict[str, float], dur: float = 0.35) -> None:
        # a call for a moment already passed lands just after the last one,
        # so the keys stay in order
        t = max(t, self.keys[-1][0] + 1e-3)
        prev = self.keys[-1][2]
        merged = dict(prev)
        merged.update(pose)
        t0 = max(t - dur, self.keys[-1][0])
        self.keys.append((t, max(t - t0, 1e-3), merged))

    def sample(self, t: float) -> dict[str, float]:
        cur = self.keys[0][2]
        for kt, dur, pose in self.keys[1:]:
            if t >= kt:
                cur = pose
                continue
            if t > kt - dur:
                a = _smooth((t - (kt - dur)) / dur)
                return {k: cur.get(k, 0.0) + (pose.get(k, 0.0) - cur.get(k, 0.0)) * a
                        for k in set(cur) | set(pose)}
            break
        return dict(cur)


def _arm_channels(side: str, pose: str | dict) -> dict[str, float]:
    ab = 1 if side == "L" else -1
    p = _arm(pose, ab) if isinstance(pose, str) else pose
    out = {}
    for part in ("shoulder", "elbow", "wrist"):
        for ax, v in zip("xyz", p.get(part, (0, 0, 0))):
            out[f"{part}.{side}.{ax}"] = float(v)
    return out


arm_channels = _arm_channels


def _hand_channels(side: str, shape: str) -> dict[str, float]:
    return {f"curl.{side}.{f}": float(c) for f, c in zip(FINGERS, HANDS[shape])}


def _hands(home: dict | None = None, **sides: tuple) -> dict[str, float]:
    """Both arms for one sentence: each side named gets its (arm pose, hand
    shape), the other goes home (hanging at rest unless the stance keeps it
    somewhere), so an arm never stays up from a gesture it is no longer
    making."""
    out: dict[str, float] = {}
    for side in "LR":
        arm, hand = sides.get(side, (home or {}).get(side, ("rest", "relaxed")))
        out.update(_arm_channels(side, arm))
        out.update(_hand_channels(side, hand))
        out[f"pocket.{side}"] = 1.0 if arm == "pocket" else 0.0
    return out


def _bump(t: float, at: float, rise: float = 0.09, fall: float = 0.32) -> float:
    """0 to 1 and back: up over `rise` before `at`, down over `fall` after."""
    if t < at - rise or t > at + fall:
        return 0.0
    if t <= at:
        return _smooth((t - (at - rise)) / rise)
    return 1.0 - _smooth((t - at) / fall)


def perform(words: Sequence, duration: float, *, fps: int = FPS, seed: str = "",
            looks: dict[str, Look] | None = None, stance: str | Stance = "") -> Performance:
    """His performance of a line: `words` carry `.word`, `.start` and `.end`
    in seconds from the start of the shot. `stance` is the kit pose the
    writer put him in (a `STANCES` key or a `Stance`); none is talking to the
    camera."""
    from pipeline.host import blink_intervals, mouth_track

    st = stance if isinstance(stance, Stance) else stance_of(stance)
    looks = {} if st.lens else (looks or {})
    home = dict(st.home)
    free = st.free
    # what he keeps turning to: the first of the stance's that is here
    held = next((looks[n] for n in st.look.split("|") if n in looks), None) if st.look else None
    if held is not None and st.reach:
        home[held.side] = (held.point or "ready", "point")
        free = free.replace(held.side, "")
    body = st.turn * held.yaw if held is not None else 0.0
    count_side = "L" if st.hand == "R" else "R"
    rng = random.Random(f"dennis|{seed}|{len(words)}|{duration:.3f}")
    n = max(int(round(duration * fps)), 1)
    ts = [i / fps for i in range(n)]

    def _hands(**sides: tuple) -> dict[str, float]:
        return globals()["_hands"](home, **sides)

    # --- the gestures, phrase by phrase
    rest = {**_hands(), "lift.L": 0.0, "lift.R": 0.0}
    arms = _Track(rest)
    # turned to something, the shot opens with him already looking at it
    gaze = _Track({"yaw": held.yaw * 0.85 if held else 0.0,
                   "pitch": held.pitch * 0.7 if held else 0.0, "roll": 0.0})
    beats: list[tuple[float, str, float]] = []         # (time, which arm(s), size)
    glance_at: list[float] = []
    ph = phrases(words, marks=".?!", gap=SENTENCE_GAP_S)
    last_hand = rng.choice(free or "LR")
    kinds: list[str] = []
    counts: list[tuple[float, int]] = []                # (time, fingers up)
    for k, p in enumerate(ph):
        nxt = ph[k + 1] if k + 1 < len(ph) else None
        gap_after = (nxt.start - p.end) if nxt else duration - p.end
        lead = min(0.35, max(p.start - (ph[k - 1].end if k else 0.0), 0.12))
        target = next((name for name, ws in LOOK_WORDS.items()
                       if name in looks and any(_letters(w.word) in ws for w in p.words)),
                      None)
        # talking to the camera, the first sentence always gets his hands and
        # he never rests them two sentences running; in a pose of the
        # writer's (arms crossed, a mug) the pose is the point, so it opens
        # the shot and the hands leave it only as often as the stance says
        quiet = st.talk[2] if k and kinds[-1] != "none" or st.home else 0.0
        one_w = st.talk[0] if free else 0.0
        both_w = st.talk[1] if len(free) == 2 else 0.0
        if k == 0 and st.first in looks:
            target = st.first
        if not free:
            kind = "none"
        elif k == 0 and st.first in ("desk", "count") or \
                k == 0 and st.first == "shrug" and len(free) == 2:
            kind = st.first
        elif target and looks[target].side in free:
            kind = "point"
        elif p.question and len(free) == 2:
            kind = "shrug"
        else:
            kind = rng.choices(("one", "both", "none"),
                               (one_w, both_w, quiet if one_w + both_w else 1.0))[0]
        kinds.append(kind)
        if kind == "point":
            look = looks[target]
            side = look.side
            # the picture beside him is shown with an open hand, not a finger
            pose = (_hands(**{side: (look.present, "open")}) if target == "plate" and look.present
                    else _hands(**{side: (look.point or "ready", "point")}))
            arms.go(p.start + 0.05, pose, 0.4)
            # held for a beat, not the whole sentence, then back to talking
            release = min(p.start + 1.3, p.end + 0.2) + 0.35
            if nxt is None or release < nxt.start:
                arms.go(release, _hands(**{side: ("ready", "open")}), 0.4)
            # the head goes first and comes back to the camera for the end of it
            gaze.go(p.start - 0.05, {"yaw": look.yaw * 0.85, "pitch": look.pitch * 0.7}, 0.35)
            if look is not held:
                back = p.start + max((p.end - p.start) * 0.7, 0.6)
                gaze.go(back + 0.35, {"yaw": 0.0, "pitch": 0.0}, 0.35)
            glance_at.append(p.start - 0.3)
        elif kind == "shrug":
            pose = {**_arm_channels("L", "shrug"), **_arm_channels("R", "shrug"),
                    **_hand_channels("L", "open"), **_hand_channels("R", "open")}
            peak = p.words[-1].start
            subs = phrases(p.words)
            if peak - p.start > 1.2:
                # a long question talks with one hand first, then gives up
                side = "R" if last_hand == "L" else "L"
                last_hand = side
                arms.go(p.start + 0.02, _hands(**{side: ("low", "relaxed") if st.lens
                                                  else ("ready", "open")}), lead + 0.1)
                for w in stressed(p.words):
                    if w.start < peak - 0.6:
                        beats.append((w.start, side, rng.uniform(0.8, 1.2)))
            for sub in subs[:-1]:
                gaze.go(sub.start + 0.1, {"yaw": rng.uniform(-5, 5),
                                          "roll": rng.uniform(-3.5, 3.5)}, 0.4)
            arms.go(max(peak - 0.05, p.start), {**pose, "lift.L": 0.03, "lift.R": 0.03}, 0.45)
            gaze.go(peak, {"yaw": 0.0, "roll": rng.choice((-6.0, 6.0)), "pitch": 2.0}, 0.4)
            gaze.go(p.end + 0.5, {"roll": 0.0, "pitch": 0.0}, 0.5)
        elif kind == "desk":
            # this one, here: a finger on the desk, held through the sentence
            side = st.hand if st.hand in free else free[0]
            arms.go(p.start + 0.05, _hands(**{side: ("down-point", "point")}), 0.4)
            gaze.go(p.start, {"pitch": -14.0, "yaw": 0.0}, 0.35)
            gaze.go(min(p.start + 0.9, p.end), {"pitch": 0.0}, 0.4)
        elif kind == "count":
            # the hands meet at the chest; a finger goes up on each word he
            # leans on, and the other hand's finger touches it
            arms.go(p.start + 0.02, _hands(**{count_side: ("count-hand", "one"),
                                              st.hand: ("count-point", "point")}), lead + 0.1)
            for c, w in enumerate(stressed(p.words)[:5]):
                counts.append((w.start - 0.05, c + 1))
        elif kind in ("one", "both"):
            side = ("R" if last_hand == "L" else "L") if len(free) == 2 else free
            last_hand = side
            if st.lens:
                pose = _hands(**{s_: ("low", "relaxed") for s_ in (free if kind == "both" else side)})
            elif kind == "both":
                pose = _hands(L=("wide", "open"), R=("wide", "open"))
            else:
                pose = _hands(**{side: ("ready", "open")})
            arms.go(p.start + 0.02, pose, lead + 0.1)
            for w in stressed(p.words):
                beats.append((w.start, "LR" if kind == "both" else side, rng.uniform(0.8, 1.2)))
        elif kind == "none":
            arms.go(p.start + 0.02, _hands(), lead + 0.1)
        if kind in ("one", "both", "none"):
            reading = bool(st.glance) and rng.random() < st.reads
            if held is not None:
                # he reads what he has turned to, and now and then comes back
                # to us for the end of the sentence
                gaze.go(p.start + 0.1, {"yaw": held.yaw * 0.85, "pitch": held.pitch * 0.7,
                                        "roll": 0.0}, 0.35)
                if p.end - p.start > 1.2 and rng.random() < 0.35:
                    gaze.go(p.start + (p.end - p.start) * 0.65 + 0.35,
                            {"yaw": 0.0, "pitch": 0.0}, 0.35)
            elif reading and st.reads >= 0.75:
                # reading it, not us: down through the sentence, up at the end
                # only now and then
                gaze.go(p.start + 0.1, {"pitch": st.glance, "yaw": rng.uniform(-4, 4),
                                        "roll": rng.uniform(-3, 3)}, 0.3)
                if rng.random() < 0.35:
                    gaze.go(p.end + 0.25, {"pitch": 0.0, "yaw": 0.0, "roll": 0.0}, 0.35)
            else:
                # with something in his hand, now and then he reads it
                look_up = p.start
                if reading:
                    gaze.go(p.start + 0.15, {"pitch": st.glance, "yaw": 0.0}, 0.3)
                    look_up = p.start + 0.15 + rng.uniform(0.6, 1.1)
                    gaze.go(look_up, {"pitch": 0.0}, 0.35)
                # a small turn of the head at every comma, held, so he is not
                # a bust
                for sub in phrases(p.words):
                    if sub.start + 0.1 > look_up:
                        gaze.go(sub.start + 0.1, {"yaw": rng.uniform(-5, 5), "pitch": 0.0,
                                                  "roll": rng.uniform(-3.5, 3.5)}, 0.4)
        if gap_after >= HANDS_DOWN_GAP_S or nxt is None:
            down = {**_hands(), "lift.L": 0.0, "lift.R": 0.0}
            arms.go(p.end + min(gap_after, 0.8), down, min(gap_after, 0.8) * 0.9 + 0.1)

    accents = stressed(words)
    questions = [p for p in ph if p.question]
    blinks = blink_intervals(0.0, duration, seed=f"dennis|{seed}") + glance_at
    blinks.sort()

    # --- the weight he shifts, a few seconds at a time
    shifts: list[tuple[float, float]] = [(0.0, rng.choice((-1.0, 1.0)))]
    t = rng.uniform(3.5, 6.0)
    while t < duration:
        shifts.append((t, -shifts[-1][1]))
        t += rng.uniform(4.0, 7.5)
    weight = _Track({"w": shifts[0][1]})
    for t, w in shifts[1:]:
        weight.go(t + 0.6, {"w": w}, 1.2)

    noise = [(rng.uniform(0.15, 0.4), rng.uniform(0, 2 * math.pi)) for _ in range(6)]

    # --- the mouth, eased between its shapes
    track = mouth_track(words, 0.0, duration, hold=MOUTH_HOLD_S)

    def mouth_at(t: float) -> dict[str, float]:
        out = {m: 0.0 for m in MOUTHS[1:]}
        for a, b, m in track:
            if a - MOUTH_EASE_S <= t < b + MOUTH_EASE_S and m != MOUTHS[0]:
                w = min(_smooth((t - (a - MOUTH_EASE_S)) / MOUTH_EASE_S),
                        _smooth(((b + MOUTH_EASE_S) - t) / MOUTH_EASE_S))
                out[m] = max(out[m], w)
        return out

    ch: dict[str, list[float]] = {}

    def put(name: str, v: float) -> None:
        ch.setdefault(name, []).append(v)

    if not st.talks:
        track = []
    for t in ts:
        a = arms.sample(t)
        up = max((c for at, c in counts if t >= at), default=0)
        if up:
            a.update(_hand_channels(count_side, ("one", "two", "three", "four", "five")[up - 1]))
        g = gaze.sample(t)
        nod = sum(_bump(t, w.start + 0.03) for w in accents)
        brow = max([0.6 * _bump(t, w.start, 0.08, 0.5) for w in accents] +
                   [1.0 if q.words[-1].start - 0.3 <= t <= q.end + 0.4 else 0.0
                    for q in questions] + [0.0])
        for side in "LR":
            ab = 1 if side == "L" else -1
            beat = sum(size * _bump(t, bt - 0.04, 0.12, 0.28)
                       for bt, sides, size in beats if side in sides)
            a[f"elbow.{side}.x"] += 13 * beat
            a[f"shoulder.{side}.x"] += 3 * beat
            a[f"wrist.{side}.x"] = a.get(f"wrist.{side}.x", 0.0) - 10 * beat
            # breathing reaches the arms a little
            a[f"shoulder.{side}.y"] += 0.6 * ab * math.sin(2 * math.pi * t / 4.2)
        for k, v in a.items():
            put(k, v)
        w = weight.sample(t)["w"]
        breath = math.sin(2 * math.pi * t / 4.2)
        wob = [amp * math.sin(2 * math.pi * f * t + ph0) for f, ph0 in noise for amp in (1.0,)]
        # his body turned some of the way to what he keeps looking at; the
        # head does the rest
        yaw, pitch, roll = g["yaw"] - body, g["pitch"], g["roll"]
        for k, v in lean_channels(st.lean).items():
            put(k, v)
        put("hips.y", 1.6 * w)
        put("hips.z", 2.2 * w + body)
        put("spine.y", -1.1 * w)
        put("spine.x", 1.2 * nod * 0.4)
        put("chest.x", 0.8 * breath + 0.3 * nod)
        put("chest.y", -0.4 * w)
        put("chest.z", 0.15 * yaw)
        put("neck.x", 0.4 * (-pitch) + 1.2 * nod)
        put("neck.z", 0.3 * yaw)
        put("head.x", 0.6 * (-pitch) + 4.2 * nod + 0.9 * wob[0] + 0.5 * wob[3])
        put("head.y", roll * 0.8 - 0.5 * w + 0.8 * wob[1])
        put("head.z", 0.55 * yaw + 1.0 * wob[2] + 0.4 * wob[4])
        put("brow", min(brow + 0.08 * (1 + wob[5]), 1.0))
        bl = 0.0
        for b in blinks:
            d = t - b
            if 0 <= d < 0.14:
                bl = max(bl, _smooth(d / 0.04) if d < 0.04 else 1.0 if d < 0.07
                         else 1.0 - _smooth((d - 0.07) / 0.07))
        put("blink", bl)
        for m, v in mouth_at(t).items():
            put(f"mouth.{m}", v)
    return Performance(fps=fps, frames=n, channels=ch)


__all__ = ["perform", "Performance", "Look", "phrases", "stressed", "MOUTHS", "FPS",
           "Stance", "STANCES", "stance_of", "mirrored", "lean_channels", "arm_channels"]
