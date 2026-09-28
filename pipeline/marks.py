"""Type fitting for the free-placed type in the vertical formats.

One job: fit type into a box, the wrap-then-shrink loop, in fractions of frame
height rather than hardcoded point sizes. The hand-drawn strokes that used to
sit here beside it live in `pipeline.rasters`, which is what draws with them.

WHAT THIS MODULE DOES NOT OWN is colour. It belongs to the kit, is read off
the registry, and had a stale copy here for two deliveries. See the comment
where the palette used to be. The faces below are the kit's own, named here
only so the fitter and the budget measure the same type.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import ImageFont

log = logging.getLogger(__name__)

# THERE IS NO PALETTE HERE, AND THERE MUST NOT BE ONE.
#
# Nine hex constants used to sit at this line — `INK`, `PAPER`, `CARD`, `RED`,
# `GREEN` and friends — sourced, per their own comment, from
# `assets/manifest.json`: a file belonging to the kit two deliveries ago, which
# has not existed since `862a5f9`. Beside them was `INK_FOR_REGISTER`, keyed on
# `marker` / `ballpoint` / `grease-pencil` / `cut-paper`, the four ink registers
# that kit shipped and this one does not have.
#
# Nothing read any of it. That is exactly what made it dangerous: it read as
# live API, it contradicted the contract at the top of `pipeline/plates.py`
# ("there is no hex literal anywhere in `pipeline/`"), and it was a PAPER-WHITE
# palette sitting one import away from a renderer drawing on the current kit's
# `night-card` ground. The next person to want a colour here had a
# plausible-looking answer that would have set dark ink on a dark surface.
#
# Colour comes off the registry, by ROLE: `reg.colour("structure")`,
# `reg.colour("attention")`. The registry got those values from the engine
# that put the ink on the plate, which is the only source that cannot go
# stale.


# ---------------------------------------------------------------------------
# Type
# ---------------------------------------------------------------------------

# The two faces. Named here rather than in the renderer so the budget
# measurement and the fitter cannot be measuring different type.
#
# Both are the kit's Archivo Narrow, at two of the weights its `typeRoles`
# declare. `plate_frames.py` sets every word that lands in a plate SLOT from
# the manifest; these feed what is left, the free-placed layers
# `render_short._draw_text` positions itself, so a short's free type is the
# same face as its plate type. They used to name Inter, which was never
# vendored and was drawn in a DejaVu Sans stand-in from the first scaffold.
BODY_FONT = "Archivo Narrow 500"
DISPLAY_FONT = "Archivo Narrow 700"

# Each face name -> the file it is drawn from and the weight axis it is set
# at. A name that is not here is taken as a file under assets/fonts.
_FACES = {
    BODY_FONT: ("ArchivoNarrow[wght].ttf", 500),
    DISPLAY_FONT: ("ArchivoNarrow[wght].ttf", 700),
}

# Line height as a multiple of ascent+descent. Here for the same reason as
# the faces: the compositor asks "how many lines does this box hold" before a
# render and the fitter asks it again during one, and a box that holds two
# lines by one measure and three by the other is a shot drawn through itself.
LINE_LEADING = 1.18

# At or above this fraction of frame height, type is set in the display face.
# Same reason again: the box is measured in one place and drawn in another,
# and measuring the regular face for type that draws bold gives a box the
# words do not fit.
DISPLAY_FROM_FH = 0.06


def face_for(size_fh: float) -> str:
    """Which face type of this size is set in."""
    return DISPLAY_FONT if size_fh >= DISPLAY_FROM_FH else BODY_FONT

# ANCHORED TO THE REPOSITORY, NOT TO THE WORKING DIRECTORY.
#
# This was `Path("assets/fonts")`, relative, so it resolved against whatever
# directory the process happened to start in. `deploy/dennis.service` sets
# `WorkingDirectory=/opt/dennis`, so the supported deployment happened to work
# and the bug stayed invisible — but from anywhere else (a cron entry, a manual
# run out of $HOME, a container with its own WORKDIR) `font_file` returned None,
# the substitution below never fired, and `load_font` fell through to Pillow's
# 11px bitmap default. Silently: no exception, no warning. `block_height` then
# answers 46px where it should answer 201, so the compositor believes a
# three-line block is a quarter of its real height and every line of type in the
# vertical formats is set in a face nobody chose.
_FONT_DIR = Path(__file__).resolve().parents[1] / "assets" / "fonts"

_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def font_file(name: str) -> Path | None:
    """The file a face name actually draws from, or None if nothing does.

    Split out from `load_font` so a test can pin it: the budgets are measured
    against whatever this returns, and if it starts returning something else
    the numbers the writing prompt hands out stop being true.
    """
    path = _FONT_DIR / _FACES.get(name, (name, None))[0]
    return path if path.exists() else None


def load_font(name: str, size: int) -> ImageFont.FreeTypeFont:
    key = (name, int(size))
    hit = _font_cache.get(key)
    if hit is not None:
        return hit
    path = font_file(name)
    if path is None:
        # Nothing named is on disk — a checkout without the fonts at all.
        # Pillow's own face, loudly, rather than whichever file happens to
        # sort first in the directory: the day the kit's Archivo Narrow
        # landed, "first file" had become its italic.
        log.warning("font %r is not in %s; drawing in Pillow's default",
                    name, _FONT_DIR)
        f = ImageFont.load_default(int(size))
    else:
        f = ImageFont.truetype(str(path), int(size))
        weight = _FACES.get(name, (None, None))[1]
        if weight is not None:
            try:
                f.set_variation_by_axes([weight])
            except Exception:      # a FreeType without variable support
                log.debug("no variable-font support; %s stays at 400", path.name)
    _font_cache[key] = f
    return f


def wrap_to(draw, text: str, font, max_w: int) -> list[str]:
    """Greedy wrap. A word longer than the box gets its own line rather than
    being dropped — an overflowing line is visible, a missing one is not."""
    lines: list[str] = []
    for para in str(text).split("\n"):
        cur = ""
        for word in para.split():
            trial = f"{cur} {word}".strip()
            if draw.textlength(trial, font=font) <= max_w or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
    return [ln for ln in lines if ln]


def fit_lines(draw, text: str, font_name: str, box_w: int, box_h: int,
              *, size_px: int, max_lines: int, min_px: int | None = None
              ) -> tuple[list[str], ImageFont.FreeTypeFont, int]:
    """Wrap `text` into at most `max_lines`, shrinking until it fits.

    Returns the lines and the font that holds them. The caller passes the size
    it WANTS — a fraction of frame height turned into pixels — and gets back
    the largest size at or below it that actually fits the box. Type that
    silently overflows its box is how a disclaimer ends up printed twice.
    """
    # The floor is how small type may go before it is better to overflow. It
    # was 55% of the asked size, which is not enough range for a wide clause
    # in a one-line slot: the loop hit the floor, gave up, and drew two lines
    # in a box that holds one. 38% still clears the 3.5%-of-frame-height rule
    # for every size any template asks for.
    floor = min_px if min_px is not None else max(12, int(size_px * 0.38))
    # The floor limits how far type may SHRINK. It must never raise the ask:
    # a 26px label in a small slot was being drawn at the 67px readability
    # floor because the loop below could not run at all, which made the type
    # two and a half times its box and truncated every card in the chain.
    # Type that is too small for the frame is a geometry problem to report,
    # not something to fix by drawing it bigger than the box that holds it.
    floor = min(floor, int(size_px))
    size = int(size_px)
    while size >= floor:
        font = load_font(font_name, size)
        lines = wrap_to(draw, text, font, box_w)
        # Width as well as line count. `wrap_to` puts a word too long for the
        # box on a line of its own rather than dropping it, so a narrow slot
        # accepted lines far wider than itself: three chain boxes rendered
        # their labels straight through each other and off the frame. A line
        # that does not fit the box is not a fit.
        widest = max((draw.textlength(ln, font=font) for ln in lines),
                     default=0)
        if len(lines) <= max_lines and widest <= box_w:
            asc, desc = font.getmetrics()
            line_h = (asc + desc) * LINE_LEADING
            if line_h * len(lines) <= box_h:
                return lines, font, 0
        size -= max(1, int(size * 0.06))

    # Below the floor, words start being lost. Smaller type is always better
    # than a clause that stops mid-sentence, so the only truncation that ever
    # happens is at the hard readability floor — and it is REPORTED, in
    # characters, rather than being dropped on the way to the screen.
    font = load_font(font_name, floor)
    full = wrap_to(draw, text, font, box_w)
    # THE BOX IS A LIMIT IN BOTH DIRECTIONS. Cutting at `max_lines` alone let
    # three lines of floor-height type render 237px tall inside a 123px slot,
    # straight over the annotation below it — and report nothing lost, because
    # every word had made it onto one of the three lines. Whichever of the two
    # limits is tighter is the one that binds.
    asc, desc = font.getmetrics()
    line_h = max(int((asc + desc) * LINE_LEADING), 1)
    keep = max(min(max_lines, int(box_h / line_h)), 1)
    lines = full[:keep]
    lost = sum(len(ln) for ln in full[keep:])
    return lines, font, lost


def block_height(font_name: str, size_px: int, lines: int) -> int:
    """How tall `lines` lines of this face at this size actually are.

    A box for free-placed type has to be built from the same number the
    fitter measures with, not from an estimate near it. `size * lines * 1.25`
    was the estimate, and it was 13% short of `(asc + desc) * LINE_LEADING`
    for the face of the day: every free-placed block in every format was authored a box
    that could not hold the lines it asked for, and the fitter quietly drew
    them smaller than the template said.
    """
    asc, desc = load_font(font_name, max(int(size_px), 1)).getmetrics()
    return int((asc + desc) * LINE_LEADING * max(lines, 1))
