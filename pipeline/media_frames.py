"""Foreign media gets a frame.

`[CLIP]`, `[IMG]`, `[SHOW ARTICLE]` and `[SHOW FILING]` bring in something this
engine did not draw — a photograph, a stock shot, a screenshot of a filing. All
four used to land raw and full-frame, which destroys the drawn surface the rest
of the video is built on: thirty minutes of hand-drawn ink, and then a 4K stock
photograph edge to edge, and then back. It reads as two different videos cut
together.

So they composite INSIDE a plate. The kit ships four:

    frames/media-frame-t1   lightest border — for a busy image
    frames/media-frame-t2   middle weight
    frames/media-frame-t3   heaviest — for a sparse image
    frames/capture-frame    for text captures: headline, body, and a mark on
                            whatever inside the capture is being pointed at

Both aspects, all four.

**Treatments rotate so consecutive ones differ.** Three media frames back to
back in the same treatment is the same defect one layer down — the frame stops
being a frame and becomes a border the eye edits out. :class:`FrameRotation`
steps rather than hashes, because "unlikely to repeat" is not the same as "does
not repeat", and a hash collides exactly when two clips are adjacent.

A text capture goes in `capture-frame` rather than a media frame, because it has
somewhere to put the headline and the mark. That is a property of what is being
shown, not a rotation slot, so it does not take a turn in the cycle.
"""

from __future__ import annotations

import logging

from pipeline.models import CueKind, TagType
from pipeline.plates import Plate, Registry

log = logging.getLogger(__name__)

# The rotating treatments, in cycle order. capture-frame is deliberately not
# here: it is chosen by WHAT is being shown, not by whose turn it is.
MEDIA_TREATMENTS = ("frames/media-frame-t1", "frames/media-frame-t2",
                    "frames/media-frame-t3")

# What lands in a capture frame rather than a media frame. These are captures of
# TEXT — a filing page, a headline, an app screen — and the capture frame is the
# one with a headline slot, a body slot and a mark for what you are pointing at
# inside it. Putting a filing excerpt in a media frame throws that away and
# leaves the operator captioning it from outside.
CAPTURE_TAGS = frozenset({TagType.SHOW_FILING, TagType.SHOW_ARTICLE,
                          TagType.SCREENGRAB})
CAPTURE_KINDS = frozenset({CueKind.FILING, CueKind.ARTICLE, CueKind.SCREENGRAB})


class FrameRotation:
    """Hands out media-frame treatments so consecutive ones differ.

    Stepping, not hashing. A hash makes a repeat unlikely; a counter makes it
    impossible, and the case that matters is exactly the adjacent one.
    """

    def __init__(self, start: int = 0):
        self._i = int(start)
        self._last = ""

    def next_key(self, aspect: str, *, capture: bool = False) -> str:
        if capture:
            return f"frames/capture-frame-{aspect}"
        key = f"{MEDIA_TREATMENTS[self._i % len(MEDIA_TREATMENTS)]}-{aspect}"
        self._i += 1
        if key == self._last and len(MEDIA_TREATMENTS) > 1:
            key = f"{MEDIA_TREATMENTS[self._i % len(MEDIA_TREATMENTS)]}-{aspect}"
            self._i += 1
        self._last = key
        return key

    def next_plate(self, reg: Registry, aspect: str, *,
                   capture: bool = False) -> Plate | None:
        return reg.get(self.next_key(aspect, capture=capture))


def frame_for(reg: Registry, rotation: FrameRotation, aspect: str, *,
              tag: TagType | None = None, kind: CueKind | None = None
              ) -> Plate | None:
    """The frame plate this piece of foreign media goes inside."""
    capture = (tag in CAPTURE_TAGS) if tag is not None else (kind in CAPTURE_KINDS)
    return rotation.next_plate(reg, aspect, capture=capture)


def composite(reg: Registry, frame: Plate, media, settings, *,
              values: dict[str, str] | None = None, frame_index: int = 0):
    """Put `media` inside `frame`, and fill the frame's own slots.

    The media goes into the frame's `media` region — cover-fitted, so it fills
    the aperture rather than sitting letterboxed inside a drawn border, which
    would be a frame around a frame. Everything else on the plate (caption,
    source, headline, the mark) is a slot the director wrote.
    """
    from pipeline.plate_frames import cover_into, render_frame

    base = render_frame(frame, frame_index, values or {}, settings, reg)
    region = frame.slot("media") or next(
        (s for s in frame.slots.values() if s.role == "media"), None)
    if region is None:
        log.warning("%s declares no media region — the image has nowhere to go",
                    frame.key)
        return base

    x, y, w, h = region.scaled()
    fitted = cover_into(media.convert("RGBA"), w, h)

    # THE MEDIA GOES UNDER THE FRAME'S INK. The border, the taped corners and
    # the caption rules are drawn on the plate, and the tape deliberately
    # overlaps the aperture — so pasting the photograph straight on top covers
    # the very thing that makes it a frame.
    #
    # The plate is a flat PNG with an opaque ground, so there is no ink layer to
    # sit above: it is recovered by distance from the ground role. That is safe
    # here rather than clever, because the separation is not marginal — the
    # aperture interior is 98.5% exactly-ground, the grain sits at 8.5% opacity
    # and does not reach the threshold, and every mark on the plate is drawn in
    # structure or attention, both of which are hundreds of units away.
    out = base.copy()
    out.alpha_composite(fitted, (x, y))
    ink = _ink_mask(base.crop((x, y, x + w, y + h)), reg)
    out.paste(base.crop((x, y, x + w, y + h)), (x, y), ink)
    return out


# How far from the ground colour a pixel has to be to count as ink. Summed
# absolute RGB difference, so a threshold of 30 is about a 4% step per channel —
# comfortably above the grain and far below any drawn mark.
_INK_THRESHOLD = 30


def _ink_mask(tile, reg: Registry):
    """A mask of everything on the plate that is not its own ground."""
    from PIL import Image

    ground = reg.colour("ground")
    rgb = tile.convert("RGB")
    # Per-channel absolute difference, summed, thresholded — done with Pillow's
    # own point/merge rather than numpy so this stays a Pillow-only dependency.
    bands = []
    for chan, g in zip(rgb.split(), ground):
        bands.append(chan.point(lambda v, g=g: abs(v - g)))
    total = bands[0]
    for b in bands[1:]:
        total = Image.blend(total, b, 0.5)      # mean; scaled back below
    return total.point(lambda v: 255 if v * 3 > _INK_THRESHOLD else 0)


def aperture(frame: Plate) -> tuple[int, int, int, int] | None:
    """The frame's media region in delivered pixels, for the FFmpeg graph."""
    region = frame.slot("media") or next(
        (s for s in frame.slots.values() if s.role == "media"), None)
    return region.scaled() if region is not None else None
