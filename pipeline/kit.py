"""The design-kit asset registry.

`scripts/export_design_kit.py` turns ~43 live design documents into ~760 PNGs
under `assets/kit/`, with a manifest recording every frame's name, size and
whether it carries alpha. This module is the read side of that: everything
downstream addresses an asset by NAME — its kit-relative path without the
extension, e.g. `type/callouts/term-roic` or `mascot/host/look-left-talk-open`
— instead of hardcoding a path.

That indirection is the point. Tags (`[TERM: roic]`, `[PROP: warehouse]`),
layouts and the host rig all resolve through here, so re-exporting the kit or
moving a family is a manifest change rather than a code change.

Three shapes of asset need more than a single lookup:

* **boil pairs** — a frame shipping a `_b` twin, alternated to make the ink
  shimmer the way the hand-drawn doodles do;
* **frame sequences** — stings and bumpers ship as `f01…f06` strips meant to
  play on twos, not as stills;
* **families** — a folder of interchangeable frames (reaction cutaways,
  object props) to pick from deterministically.

A missing kit is never fatal: every lookup returns None or an empty list and
the caller falls back to what it drew before.
"""

from __future__ import annotations

import functools
import hashlib
import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

KIT_DIRNAME = "kit"
MANIFEST_NAME = "manifest.json"

# Frame strips (stings, bumpers) play at this rate — six frames "on twos" at
# 24fps is the ~0.5s ink transition the design brief specifies.
STRIP_FPS = 12


class Kit:
    """Read-only index over an exported design kit."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self._assets: dict[str, dict] = {}
        manifest = self.root / MANIFEST_NAME
        if not manifest.exists():
            log.warning("design kit manifest not found at %s — kit lookups will "
                        "return nothing (run scripts/export_design_kit.py)", manifest)
            return
        try:
            self._assets = json.loads(manifest.read_text()).get("assets", {})
        except (OSError, ValueError) as exc:
            log.warning("design kit manifest unreadable (%s) — kit lookups disabled", exc)

    # ---------------------------------------------------------------- lookup
    def __contains__(self, name: str) -> bool:
        return self.path(name) is not None

    def __len__(self) -> int:
        return len(self._assets)

    def path(self, name: str) -> Path | None:
        """Absolute path for one asset name, or None when it is not shipped."""
        row = self._assets.get(name)
        if row is None:
            return None
        p = self.root / f"{name}.png"
        return p if p.exists() else None

    def size(self, name: str) -> tuple[int, int] | None:
        row = self._assets.get(name)
        if row is None or "w" not in row:
            return None
        return int(row["w"]), int(row["h"])

    def has_alpha(self, name: str) -> bool:
        return bool(self._assets.get(name, {}).get("alpha"))

    # -------------------------------------------------------------- families
    @functools.lru_cache(maxsize=256)  # noqa: B019 (instances are long-lived)
    def family(self, prefix: str) -> tuple[str, ...]:
        """Every asset directly under `prefix`, boil twins excluded.

        The `_b` frames are alternates of their base frame, not separate
        assets, so they never show up as independent choices.
        """
        head = prefix.rstrip("/") + "/"
        return tuple(sorted(
            n for n in self._assets
            if n.startswith(head) and "/" not in n[len(head):] and not n.endswith("_b")
        ))

    def pick(self, prefix: str, seed: str) -> Path | None:
        """One asset from a family, chosen deterministically from `seed`.

        The same seed always picks the same frame, so a render is
        reproducible, while different scripts spread across the family.
        """
        options = self.family(prefix)
        if not options:
            return None
        digest = hashlib.sha256(f"{prefix}|{seed}".encode()).hexdigest()
        return self.path(options[int(digest[:8], 16) % len(options)])

    def resolve(self, prefix: str, key: str) -> Path | None:
        """An asset by family + key, tolerating the family's naming prefix.

        `[PROP: laptop]` should find `props/objects/obj-laptop`, and
        `[TERM: roic]` should find `type/callouts/term-roic`, without the
        script author having to know the kit's internal naming.
        """
        key = key.strip().lower().replace(" ", "-").replace("_", "-")
        head = prefix.rstrip("/") + "/"
        direct = self.path(f"{head}{key}")
        if direct is not None:
            return direct
        for name in self.family(prefix):
            leaf = name[len(head):]
            if leaf == key or leaf.split("-", 1)[-1] == key:
                return self.path(name)
        return None

    # ----------------------------------------------------------- boil pairs
    def boil(self, name: str) -> list[Path]:
        """[frame] or [frame, frame_b] — the pair to alternate on a hold."""
        base = self.path(name)
        if base is None:
            return []
        twin = self.path(f"{name}_b")
        return [base, twin] if twin is not None else [base]

    # ------------------------------------------------------ frame sequences
    def sequence(self, prefix: str) -> list[Path]:
        """The `f01…fNN` frames of a sting or bumper, in order.

        These are animated ink strips, so they are composited like the doodle
        boil — an alpha frame-sequence turned into a clip — never as a still.
        """
        head = prefix.rstrip("/") + "/"
        frames = sorted(
            n for n in self._assets
            if n.startswith(head) and n[len(head):].startswith("f")
            and n[len(head) + 1:].isdigit()
        )
        return [p for p in (self.path(n) for n in frames) if p is not None]

    def sequences(self, prefix: str) -> tuple[str, ...]:
        """The named strips under `prefix` (e.g. every sting)."""
        head = prefix.rstrip("/") + "/"
        names = {n[len(head):].split("/")[0] for n in self._assets if n.startswith(head)}
        return tuple(sorted(n for n in names
                            if self.sequence(f"{head}{n}")))


@functools.lru_cache(maxsize=8)
def load_kit(assets_dir: Path) -> Kit:
    """The kit under an assets directory, cached per path."""
    return Kit(Path(assets_dir) / KIT_DIRNAME)
