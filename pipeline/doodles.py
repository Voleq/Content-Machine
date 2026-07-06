"""Owned doodle library — the hand-drawn overlay language (§doodles).

`[DOODLE: key]` resolves here: assets/doodles/ holds crude marker-style
transparent PNGs, indexed by doodles_index.json (filename stem -> tags +
a one-line "use when") — the same contract as the meme library. Doodles
are OWNED assets only: resolution is strictly local (stem, then tag,
then substring), a miss is logged and skipped, and there is no network
fallback by design.

The renderers give every doodle a slight hand-drawn "boil": the still
PNG is jittered frame-to-frame (`wobble_frames`) so it never sits dead
on screen.
"""

from __future__ import annotations

import json
import logging
import math
import random
from pathlib import Path

from PIL import Image

from config import Settings

log = logging.getLogger(__name__)

_IMAGE_SUFFIXES = (".png", ".webp")


class DoodleLibrary:
    """assets/doodles/ + doodles_index.json — local-first, local-only."""

    def __init__(self, settings: Settings, library_dir: Path | None = None):
        self.settings = settings
        self.dir = library_dir or settings.assets_dir / "doodles"

    def index(self) -> dict[str, dict]:
        f = self.dir / "doodles_index.json"
        if not f.exists():
            return {}
        try:
            return json.loads(f.read_text())
        except json.JSONDecodeError:
            log.warning("doodles_index.json is invalid JSON — doodles disabled")
            return {}

    def keys(self) -> list[str]:
        return sorted(self.index().keys())

    def _file_for(self, stem: str) -> Path | None:
        for suffix in _IMAGE_SUFFIXES:
            p = self.dir / f"{stem}{suffix}"
            if p.exists():
                return p
        return None

    def match(self, key: str) -> str | None:
        """Stem, then tag, then substring — deterministic (sorted stems)."""
        key_n = key.strip().lower().replace(" ", "-").replace("_", "-")
        idx = self.index()
        if key_n in idx:
            return key_n
        for stem in sorted(idx):
            if key_n in [t.lower() for t in idx[stem].get("tags", [])]:
                return stem
        for stem in sorted(idx):
            if key_n in stem:
                return stem
        return None

    def resolve(self, key: str) -> Path | None:
        """The doodle PNG, or None (callers log + skip — never fatal)."""
        stem = self.match(key)
        if stem is None:
            return None
        path = self._file_for(stem)
        if path is None:
            log.warning("doodle %r indexed but has no image file", stem)
        return path


def wobble_frames(
    img: Image.Image,
    *,
    duration_s: float,
    fps: int = 30,
    boil_hz: float = 7.5,
    max_rot_deg: float = 1.6,
    max_shift_px: int = 3,
    seed: str = "doodle",
) -> list[Image.Image]:
    """The hand-drawn 'boil': a small cycle of jittered variants of the
    same image, held a few frames each — classic 2s-on-ones animation
    energy without redrawing anything."""
    rng = random.Random(f"wobble|{seed}")
    variants: list[Image.Image] = []
    pad = max_shift_px + int(math.tan(math.radians(max_rot_deg)) * max(img.size)) + 4
    cw, ch = img.width + 2 * pad, img.height + 2 * pad
    for _ in range(3):
        rot = rng.uniform(-max_rot_deg, max_rot_deg)
        dx = rng.randint(-max_shift_px, max_shift_px)
        dy = rng.randint(-max_shift_px, max_shift_px)
        frame = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        rotated = img.rotate(rot, expand=True, resample=Image.BICUBIC)
        frame.alpha_composite(rotated, ((cw - rotated.width) // 2 + dx,
                                        (ch - rotated.height) // 2 + dy))
        variants.append(frame)

    hold = max(int(round(fps / boil_hz)), 1)  # frames per variant
    total = max(int(duration_s * fps), hold)
    frames: list[Image.Image] = []
    i = 0
    while len(frames) < total:
        frames.extend([variants[i % len(variants)]] * hold)
        i += 1
    return frames[:total]
