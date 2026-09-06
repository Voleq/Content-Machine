"""Delivery direction: what the writer declares, and what each model performs.

THE WRITER DECLARES DELIVERY; THE PIPELINE NEVER INVENTS IT. Same rule as the
plates — the director names the plate and fills its slots, and the renderer
places what it was given. Nothing here looks at a sentence and decides it wants
a sigh.

That rule is why ElevenLabs' "Enhance" button is not wired in and must not be.
It runs a model over the text inserting tags for you, and its published prompt
tells it to "strive for a diverse range of emotional expressions (e.g.
energetic, relaxed, casual, surprised)" — which is the exact opposite brief to
the one the voice bible sets, and it would put a model in charge of the
register that the bible, this linter and the fact-check gate exist to keep it
out of.

ONE TABLE, TWO TIERS. Every script tag has a v3 emission and a pre-v3
fallback, so a model switch is never a content change. A fallback of "" means
emit nothing: on a model that cannot perform the direction, silence is correct
and the bracket text is not — an unsupported tag is READ ALOUD, which is the
failure this table exists to make impossible.
"""

from __future__ import annotations

from dataclasses import dataclass

from pipeline.models import TagType

# Models that perform audio tags inline rather than reading them out.
#
# Substring-matched, because ElevenLabs ships dated and suffixed variants of a
# model id and a new one must not silently lose the tags.
V3_MODELS = ("eleven_v3",)


def performs_audio_tags(model_id: str) -> bool:
    """Whether this model performs bracket tags instead of speaking them."""
    return any(m in (model_id or "") for m in V3_MODELS)


@dataclass(frozen=True)
class Direction:
    """One inline direction, and what each tier is given for it.

    `v3` goes into the request on a model that performs tags; `v2` on one that
    does not. An empty `v2` means the direction is dropped there — see the
    module docstring.
    """

    v3: str
    v2: str
    mode: str        # the §7 mode of the voice bible this serves
    why: str


# The vocabulary: eight inline directions here, plus the two register tags
# below, and that is the whole of what a writer may declare.
#
# `[CURIOUS]` is the one that earns the v3 migration. §7 of the bible:
#
#     Rare genuine interest — a mechanism he actually respects; the monotone
#     lifts. THESE LIFTS ARE THE RETENTION.
#
# That instruction had no mechanism behind it on any earlier model: there is no
# slider for "lifts, briefly, because this bit is genuinely clever". It has one
# now, and the density ceiling below is what keeps a lift a lift.
DIRECTIONS: dict[TagType, Direction] = {
    TagType.BEAT: Direction(
        v3="… ", v2='<break time="0.6s" /> ', mode="timing",
        why="the deliberate pause the writer placed"),
    TagType.LONG_BEAT: Direction(
        v3="[long pause] ", v2='<break time="1.2s" /> ', mode="timing",
        why="the pause that has stopped being a pause and become a silence"),
    TagType.SIGH: Direction(
        v3="[sighs] ", v2='<break time="0.4s" /> ', mode="tired explainer",
        why="the sound of having read the filing"),
    TagType.EXHALE: Direction(
        v3="[exhales] ", v2='<break time="0.4s" /> ', mode="quiet exasperation",
        why="shorter than a sigh and less resigned — the breath before the point"),
    TagType.SNORT: Direction(
        v3="[snorts] ", v2="", mode="the joke he cannot let pass",
        why="a man reading a filing at 3am snorts; he does not laugh"),
    TagType.SARCASTIC: Direction(
        v3="[sarcastic] ", v2="", mode="quiet exasperation",
        why="the line means its opposite and the delivery has to carry that"),
    TagType.CURIOUS: Direction(
        v3="[curious] ", v2="", mode="rare genuine interest",
        why="the monotone lifts, and §7 says these lifts are the retention"),
    TagType.QUIET: Direction(
        v3="[whispers] ", v2="", mode="dark calm",
        why="the register drops rather than rises — the opposite of emphasis"),
}


@dataclass(frozen=True)
class Register:
    """A whole-generation register instruction, not an inline event.

    Two mechanisms, because the models want opposite things:

    * Pre-v3 takes it on the sliders — stability up, style down.
    * v3 must NOT. On v3, 0.85 stability is the Robust end, and Robust
      "reduces responsiveness to directional prompts" — so [FLAT] and [DRY],
      the two commonest tags in any Dennis script, would suppress every other
      tag around them. The register moves inline and the sliders are left at
      Natural.
    """

    v3: str
    v2_settings: dict
    mode: str
    why: str


# [flat] and [deadpan] are NOT in ElevenLabs' documented tag list. They are
# here because the docs say "there are likely many more effective tags beyond
# this list; experiment with descriptive emotional states", and because the
# alternative — leaving stability at 0.85 — is known to be wrong on v3.
#
# UNVERIFIED AGAINST THE LIVE API. If they turn out not to take, the honest
# fallback is `v3=""`: drop the direction and leave the register to the voice,
# which was cast understated for exactly this reason. That is a one-word edit
# here and nowhere else, which is the point of the table.
#
# NOT touched here, and worth knowing about: the BASE voice settings in
# config.py (eleven_stability_short 0.68, eleven_stability_long 0.72) are still
# sent on v3. v3 documents stability as three settings rather than a continuous
# dial — Creative, Natural, Robust — and 0.72 sits between the last two, which
# is the same neighbourhood this table just stopped [FLAT] from pushing into.
# Whether that is snapped, interpolated or ignored is a question for a real
# generation, not for a guess in a comment. It is left alone because those
# numbers are the cast register, tuned for the deadpan, and changing them is a
# voice decision rather than a delivery one.
_FLAT_SLIDERS = {"stability": 0.85, "style": 0.0}

REGISTERS: dict[TagType, Register] = {
    TagType.FLAT: Register(
        v3="[flat] ", v2_settings=dict(_FLAT_SLIDERS), mode="register",
        why="hold the whole generation flatter than baseline"),
    TagType.DRY: Register(
        v3="[deadpan] ", v2_settings=dict(_FLAT_SLIDERS), mode="register",
        why="the flatness IS the joke, and the bible says so in §2"),
}


# --------------------------------------------------------------------------
# What the writer may NOT declare.
# --------------------------------------------------------------------------
# Refused BY NAME rather than merely left out of the table above. A tag that is
# simply unknown is stripped in silence, and silence teaches nothing — the
# first writer who reads the ElevenLabs docs will try these, get no complaint,
# and try them again.
#
# The lowercase spelling is the dangerous one, and it is the one the docs use.
# The tokenizer's bracket grammar only matches an UPPERCASE type, so `[laughs]`
# is not a tag at all: it survives into the narration, gets spoken, and reaches
# the captions. `[LAUGHS]` is merely stripped. Both are named here.

_TRYING = (
    "§2 — still banned: anything that reads as trying. A host who audibly "
    "laughs at his own line has broken the deadpan, and the bible is explicit "
    "that the flatness is the delivery"
)
_FABRICATION = (
    "a sound effect is the pipeline manufacturing an event that did not "
    "happen, in a product whose whole claim is that every figure is checked"
)

BANNED_TAGS: dict[str, str] = {
    # Performance. Every one of these reads as trying.
    "excited": _TRYING,
    "happy": _TRYING,
    "angry": _TRYING,
    "crying": _TRYING,
    "laughs": _TRYING,
    "laughs harder": _TRYING,
    "starts laughing": _TRYING,
    "wheezing": _TRYING,
    "woo": _TRYING,
    "sings": _TRYING,
    "mischievously": _TRYING,
    "surprised": _TRYING,
    # Sound effects. Banned on the stronger ground.
    "applause": _FABRICATION,
    "clapping": _FABRICATION,
    "gunshot": _FABRICATION,
    "explosion": _FABRICATION,
}


# --------------------------------------------------------------------------
# Density — a ceiling, the same as everything else.
# --------------------------------------------------------------------------
# The bible caps repetition ("no construction twice per script") because a
# device used constantly stops being a device. Direction is a device.
#
# All of these are WARNINGS. Same contract as the rest of the linter: notes and
# blocks, never rewrites — the writer decides.
#
# The numbers are a starting point and are meant to be tuned against real
# scripts, not defended.

# One per sentence, and never two with nothing between them.
MAX_TAGS_PER_SENTENCE = 1

# Across the whole script. Three per thousand characters is roughly one every
# three sentences; past that the direction is the texture rather than the
# exception to it.
TAGS_PER_1K_CHARS_WARN = 3.0

# The lift is the retention, and a lift that happens six times is a monotone
# again.
CURIOUS_MAX_PER_LONG = 2

# Dark calm is earned, not opened on.
QUIET_MAX = 1

# One snort. A man reading a filing at 3am snorts; he does not laugh, and he
# does not snort twice.
SNORT_MAX = 1

# Ceilings that are simply "n per script", by tag. Kept as data so the linter
# reads them off one place and the prompts can be generated from the same.
PER_SCRIPT_MAX: dict[TagType, int] = {
    TagType.CURIOUS: CURIOUS_MAX_PER_LONG,
    TagType.QUIET: QUIET_MAX,
    TagType.SNORT: SNORT_MAX,
}


def emission(tag: TagType, model_id: str) -> str:
    """What goes into the request for `tag` on `model_id`.

    "" means emit nothing — the model cannot perform this direction and the
    bracket text would be read aloud.
    """
    if tag in REGISTERS:
        return REGISTERS[tag].v3 if performs_audio_tags(model_id) else ""
    d = DIRECTIONS.get(tag)
    if d is None:
        return ""
    return d.v3 if performs_audio_tags(model_id) else d.v2


def setting_overrides(tag: TagType, model_id: str) -> dict:
    """The voice-setting changes `tag` makes, which is only ever the register.

    Empty on v3 by design: see `Register`. Moving [FLAT] onto the sliders there
    is what would suppress every other tag in the script.
    """
    r = REGISTERS.get(tag)
    if r is None or performs_audio_tags(model_id):
        return {}
    return dict(r.v2_settings)
