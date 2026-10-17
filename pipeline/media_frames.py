"""The media frames still in use: the short's.

The LONG plays everything taken from outside full screen — b-roll, memes,
filing pages and screengrabs (Valentin, 10-10: "the b rolls should be full
screen together with everything that is taken from the net like memes and
reports"); see `render_long`'s clip and filing branches. The frame
compositing that used to put them inside a taped paper plate is gone.

The SHORT's company photograph went full screen too (10-17, his pick: the
`the-picture` shot has no plate, and its name and credit sit on strips of
paper over it). What is left is a SHORT's meme, when `SHORT_MEME` turns them
on: it goes in one of three taped treatments, the `-9x16` cut of each name
below (`compose._meme_frame`), rotating off recent videos.
"""

from __future__ import annotations

# The rotating treatments, in cycle order.
MEDIA_TREATMENTS = ("frames/media-frame-t1", "frames/media-frame-t2",
                    "frames/media-frame-t3")

# How far into the aperture the frame's own ink may reach back, as a fraction
# of the aperture's short side. Wide enough for a drawn border and a taped
# corner, narrow enough that it never argues with the image.
_EDGE_BAND = 0.06
