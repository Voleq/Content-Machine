"""What changes across a video: light, clutter, the wall, the clock.

Four devices that run the whole length of a LONG, so the room at minute
fifteen is not the room at minute one. They are all functions of one number —
how far through the video a shot sits — and none of them is anything the
script can ask for. Progression is a property of position, not of content.

Deliberately dumb thresholds. A curve would be harder to reason about and no
truer: the point is that the room is visibly later by the end, not that the
falloff is physical.
"""

from __future__ import annotations

from dataclasses import dataclass

# Daylight to 3am across the runtime. Group M, register-agnostic, delivered
# once — and 16:9 only, so this is a LONG device. The vertical formats get
# no light because the kit ships none at 9:16.
LIGHT_STEPS: tuple[tuple[float, str], ...] = (
    (0.00, "light-daylight"),
    (0.35, "light-afternoon"),
    (0.65, "light-dusk"),
    (0.85, "light-3am"),
)

# The room fills up. Five plates carry these three states, and the slot
# geometry is identical across them, so swapping is free.
CLUTTER_STEPS: tuple[tuple[float, str], ...] = (
    (0.00, "tidy"),
    (0.40, "lived-in"),
    (0.75, "3am"),
)

# The wall fills up too. All three states declare the SAME nine pin slots,
# which is what stops a pinned item jumping when the wall changes under it.
WALL_STEPS: tuple[tuple[float, str], ...] = (
    (0.00, "empty"),
    (0.40, "half"),
    (0.75, "full"),
)

# The clock reads the light. Hours are what the light states mean, so the
# hands are drawn from the same number rather than tracked separately —
# a clock disagreeing with the window is worse than no clock.
LIGHT_HOURS = {
    "light-daylight": 10.5,
    "light-afternoon": 15.0,
    "light-dusk": 19.5,
    "light-3am": 3.1,
}

# Ambient loops that are purely ADDITIVE and may be composited over any room
# shot. loop-plant and loop-curtain are deliberately absent: the manifest says
# they REPLACE the plate's drawn plant and curtain, and no room plate in this
# delivery ships without them. Overlaying gives the doubled outline the
# manifest warns about, so they stay unused until a plate without the drawn
# furniture exists. See the Stage 3b report.
AMBIENT_ADDITIVE_USED: tuple[str, ...] = ("loop-steam", "loop-cursor",
                                          "loop-second-hand")

# Where each additive loop sits, as fractions of the frame. The kit gives no
# slot for them — they are objects in the room, not declared boxes — so the
# placement is here, once, rather than in every template.
AMBIENT_PLACEMENT = {
    "loop-steam": (0.545, 0.545, 0.055, 0.085),
    "loop-cursor": (0.300, 0.560, 0.022, 0.038),
    "loop-second-hand": (0.176, 0.140, 0.050, 0.090),
}


def _pick(steps: tuple[tuple[float, str], ...], progress: float) -> str:
    out = steps[0][1]
    for at, value in steps:
        if progress >= at:
            out = value
    return out


@dataclass(frozen=True)
class Progression:
    """The state of the room at one point in the video."""

    progress: float
    light: str
    clutter: str
    wall: str

    @property
    def hour(self) -> float:
        return LIGHT_HOURS.get(self.light, 12.0)


def at(progress: float) -> Progression:
    p = min(max(progress, 0.0), 1.0)
    return Progression(progress=p, light=_pick(LIGHT_STEPS, p),
                       clutter=_pick(CLUTTER_STEPS, p),
                       wall=_pick(WALL_STEPS, p))


def restate(concept: str | None, state: "Progression") -> str | None:
    """Re-point a stateful concept at the state this moment is in.

    Each family reads its OWN axis: a room plate takes the clutter state, the
    wall takes the wall state. Handing the clutter state to the wall asks the
    kit for `evidence-wall-tidy`, which does not exist — the two advance
    together but they are not the same scale.

    A concept with no state is returned unchanged, so this is safe to call on
    everything.
    """
    if not concept:
        return concept
    if concept.startswith("evidence-wall-"):
        return f"evidence-wall-{state.wall}"
    if "--" in concept:
        stem, _, tail = concept.rpartition("--")
        if tail in {v for _a, v in CLUTTER_STEPS}:
            return f"{stem}--{state.clutter}"
    return concept


def clock_hands(hour: float) -> tuple[float, float]:
    """`(hour_angle, minute_angle)` in degrees clockwise from twelve."""
    h = hour % 12.0
    return (h * 30.0, (hour % 1.0) * 360.0)
