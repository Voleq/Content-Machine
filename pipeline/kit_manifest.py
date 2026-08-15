"""The DENNIS kit: 476 entries, 1,772 frames, four registers plus light.

`assets/manifest.json` is the single source of truth. A PNG with no manifest
entry does not exist; a manifest entry with no PNG fails the load. There is no
filesystem discovery and no naming convention to infer from — the manifest
lists the files for every entry, in playback order.

Two things here are silent when they are missed, so neither is ever left to a
call site:

* **Scale.** Slots are authored in the asset's own CANVAS coordinates. The PNG
  is delivered at `delivered`, which is 2x canvas for 452 of the 476 entries
  and 1:1 for the other 24 (groups ID and K — and K has slots). A slot box
  composited without its own entry's scale puts every figure at half its
  intended position on a drawing that still looks perfectly correct. So
  `Entry.scale` is read from the entry, per entry, and `slot_px()` is the only
  supported way to reach pixels.

* **Playback.** `boil` is three genuinely redrawn frames at 7fps that must run
  continuously — it is what stops a frame reading as a held photograph.
  `loop` and `one-shot` are also present and mean different things, at five
  different frame rates between them. `fps` and `playback` are read from the
  entry; nothing here is hardcoded.

This delivery contains no `static` entries at all: every plate that used to be
one still PNG was re-baked as a 3-frame boil. `static` stays in the accepted
set because the schema allows it, not because anything ships it.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterator, Mapping

MANIFEST_NAME = "manifest.json"

# Registers a video may be drawn in. `light` is group M: register-agnostic,
# delivered once, and never chosen as a video's register.
REGISTERS: tuple[str, ...] = ("marker", "ballpoint", "grease-pencil", "cut-paper")
LIGHT_REGISTER = "light"

PLAYBACKS = frozenset({"static", "boil", "loop", "one-shot"})

# The ambient loops that run continuously under every room shot. The two named
# here REPLACE the plate's drawn furniture rather than overlaying it — an
# overlay gives you a doubled outline. The manifest note is the authority;
# this is the renderer's copy of it.
AMBIENT_REPLACING = frozenset({"loop-plant", "loop-curtain"})
AMBIENT_ADDITIVE = frozenset({"loop-steam", "loop-cursor", "loop-second-hand"})


class KitError(RuntimeError):
    """The kit on disk does not match its manifest. Never degrade past this."""


def _png_size(path: Path) -> tuple[int, int]:
    """Width/height from the IHDR, without decoding the image.

    1,772 PNGs at 3840x2160 is far too much pixel data to decode just to check
    a dimension. The header is the first 24 bytes and it is enough.
    """
    with path.open("rb") as fh:
        head = fh.read(24)
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n":
        raise KitError(f"not a PNG: {path}")
    if head[12:16] != b"IHDR":
        raise KitError(f"PNG has no leading IHDR chunk: {path}")
    w, h = struct.unpack(">II", head[16:24])
    return int(w), int(h)


@dataclass(frozen=True)
class Slot:
    """A declared box, in the entry's CANVAS coordinates, origin top-left.

    Nothing is drawn inside a slot by the artwork: every interior is empty for
    code. Reach pixels with `Entry.slot_px`, never by using x/y directly.
    """

    name: str
    x: int
    y: int
    w: int
    h: int

    @property
    def box(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.w, self.h)


@dataclass(frozen=True)
class Entry:
    key: str
    concept: str
    group: str
    register: str
    canvas: tuple[int, int]
    delivered: tuple[int, int]
    background: str
    frames: int
    fps: int
    playback: str
    files: tuple[str, ...]
    svg_files: tuple[str, ...]
    dir: str
    svg_dir: str
    slots: Mapping[str, Slot]
    root: Path

    # -- geometry ---------------------------------------------------------
    @property
    def scale(self) -> tuple[float, float]:
        """`delivered / canvas`, read from this entry. Never assumed to be 2."""
        return (self.delivered[0] / self.canvas[0],
                self.delivered[1] / self.canvas[1])

    def slot_px(self, name: str) -> tuple[int, int, int, int]:
        """A slot as `(x, y, w, h)` in DELIVERED pixels."""
        try:
            s = self.slots[name]
        except KeyError:
            raise KitError(
                f"{self.key} has no slot {name!r}; it has "
                f"{sorted(self.slots) or 'none'}") from None
        sx, sy = self.scale
        return (round(s.x * sx), round(s.y * sy),
                round(s.w * sx), round(s.h * sy))

    # -- playback ---------------------------------------------------------
    @property
    def is_animated(self) -> bool:
        return self.frames > 1

    @property
    def loops(self) -> bool:
        """Runs continuously, versus playing once and holding its last frame."""
        return self.playback in ("boil", "loop")

    @property
    def cycle_s(self) -> float:
        """Seconds for one pass through the frames."""
        return self.frames / self.fps if self.fps else 0.0

    def frame_path(self, index: int) -> Path:
        """Absolute path to frame `index`, wrapping if this entry loops."""
        if self.loops:
            index %= self.frames
        index = min(max(index, 0), self.frames - 1)
        return self.root / self.dir / self.files[index]

    @property
    def paths(self) -> tuple[Path, ...]:
        return tuple(self.root / self.dir / f for f in self.files)

    def frame_at(self, t: float, *, t0: float = 0.0) -> Path:
        """The frame showing at time `t`, for an entry started at `t0`."""
        if not self.is_animated or not self.fps:
            return self.frame_path(0)
        return self.frame_path(int((t - t0) * self.fps))


class Kit:
    """Loaded, verified access to the kit by concept and register."""

    def __init__(self, root: Path, raw: dict, entries: list[Entry]) -> None:
        self.root = root
        self.raw = raw
        self.entries = entries
        self._by_key = {e.key: e for e in entries}
        self._by_concept: dict[tuple[str, str], Entry] = {}
        for e in entries:
            self._by_concept[(e.concept, e.register)] = e
        self.palette: dict[str, str] = dict(raw.get("palette") or {})
        self.groups: dict[str, str] = dict(raw.get("groups") or {})

    # -- lookup -----------------------------------------------------------
    def concept(self, name: str, register: str) -> Entry:
        """The entry for `name` in `register`, falling back to group-M light.

        Light (group M) and channel identity (group ID) are delivered once
        rather than per register, so a lookup for them in any register
        resolves to the single copy that exists.
        """
        hit = self._by_concept.get((name, register))
        if hit is not None:
            return hit
        for fallback in (LIGHT_REGISTER, "marker"):
            hit = self._by_concept.get((name, fallback))
            if hit is not None:
                return hit
        raise KitError(
            f"no kit concept {name!r} in register {register!r}. "
            f"Nearest: {sorted(self.suggest(name))[:5] or 'nothing similar'}")

    def has(self, name: str, register: str) -> bool:
        return (self._by_concept.get((name, register)) is not None
                or self._by_concept.get((name, LIGHT_REGISTER)) is not None)

    def suggest(self, name: str) -> set[str]:
        stem = name.split("-")[0]
        return {c for (c, _r) in self._by_concept if stem and stem in c}

    def concepts(self, register: str | None = None) -> set[str]:
        return {c for (c, r) in self._by_concept
                if register is None or r == register}

    def by_group(self, group: str, register: str | None = None) -> list[Entry]:
        return [e for e in self.entries if e.group == group
                and (register is None or e.register in (register, LIGHT_REGISTER))]

    def __getitem__(self, key: str) -> Entry:
        try:
            return self._by_key[key]
        except KeyError:
            raise KitError(f"no kit entry with key {key!r}") from None

    def __iter__(self) -> Iterator[Entry]:
        return iter(self.entries)

    def __len__(self) -> int:
        return len(self.entries)


def _parse_entries(raw: dict, root: Path) -> list[Entry]:
    out: list[Entry] = []
    for i, a in enumerate(raw.get("assets") or []):
        try:
            canvas = (int(a["canvas"]["w"]), int(a["canvas"]["h"]))
            delivered = (int(a["delivered"]["w"]), int(a["delivered"]["h"]))
            slots = {s["name"]: Slot(s["name"], int(s["x"]), int(s["y"]),
                                     int(s["w"]), int(s["h"]))
                     for s in (a.get("slots") or [])}
            out.append(Entry(
                key=a["key"], concept=a["concept"], group=a["group"],
                register=a["register"], canvas=canvas, delivered=delivered,
                background=a.get("background", "transparent"),
                frames=int(a["frames"]), fps=int(a["fps"]),
                playback=a["playback"],
                files=tuple(a["files"]), svg_files=tuple(a.get("svg") or ()),
                dir=a["dir"], svg_dir=a.get("svgDir", ""),
                slots=slots, root=root))
        except (KeyError, TypeError, ValueError) as exc:
            raise KitError(f"manifest asset #{i} is malformed: {exc}") from exc
    return out


def verify_entries(entries: list[Entry], *, registers: set[str] | None = None,
                   check_files: bool = True,
                   check_sizes: bool = True) -> list[str]:
    """Every way the kit can be wrong, as a list of human-readable problems.

    Geometry is checked for every entry given (it is pure arithmetic on the
    manifest). File existence and on-disk size are checked only for the
    registers actually being loaded, because reading 3,544 file headers to
    render one 9:16 SHORT is waste — `scripts/ingest_kit.py` does the
    exhaustive pass over every register at ingest time.
    """
    problems: list[str] = []
    for e in entries:
        # -- shape
        if e.playback not in PLAYBACKS:
            problems.append(f"{e.key}: unknown playback {e.playback!r}")
        if e.frames != len(e.files):
            problems.append(
                f"{e.key}: declares {e.frames} frames but lists "
                f"{len(e.files)} files")
        if e.frames > 1 and e.fps <= 0:
            problems.append(f"{e.key}: {e.frames} frames at fps={e.fps}")
        if e.canvas[0] <= 0 or e.canvas[1] <= 0:
            problems.append(f"{e.key}: canvas {e.canvas}")

        # -- every slot fits inside its canvas
        for s in e.slots.values():
            if s.w <= 0 or s.h <= 0:
                problems.append(f"{e.key}: slot {s.name} has size {s.w}x{s.h}")
            if (s.x < 0 or s.y < 0
                    or s.x + s.w > e.canvas[0] or s.y + s.h > e.canvas[1]):
                problems.append(
                    f"{e.key}: slot {s.name} {s.box} falls outside canvas "
                    f"{e.canvas[0]}x{e.canvas[1]}")

        if registers is not None and e.register not in registers:
            continue
        if not check_files:
            continue

        # -- every file exists, at exactly the delivered size
        for f in e.files:
            p = e.root / e.dir / f
            if not p.exists():
                problems.append(f"{e.key}: missing frame {p}")
                continue
            if not check_sizes:
                continue
            try:
                got = _png_size(p)
            except KitError as exc:
                problems.append(str(exc))
                continue
            if got != e.delivered:
                problems.append(
                    f"{e.key}: {f} is {got[0]}x{got[1]} on disk but the "
                    f"manifest declares {e.delivered[0]}x{e.delivered[1]}")
    return problems


def load_kit(root: Path | str = ".", *, registers: set[str] | None = None,
             check_files: bool = True, check_sizes: bool = True) -> Kit:
    """Load and verify the kit. Raises `KitError` loudly on any problem.

    A missing asset must never degrade silently into an empty box, so this
    raises rather than warning, and it raises before a render can start.
    """
    root = Path(root)
    mpath = root / "assets" / MANIFEST_NAME
    if not mpath.exists():
        raise KitError(
            f"no kit manifest at {mpath}. Run scripts/ingest_kit.py against "
            f"the delivery to install one.")
    try:
        raw = json.loads(mpath.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise KitError(f"{mpath} is not valid JSON: {exc}") from exc

    entries = _parse_entries(raw, root)
    if not entries:
        raise KitError(f"{mpath} declares no assets")

    want = None if registers is None else set(registers) | {LIGHT_REGISTER}
    problems = verify_entries(entries, registers=want,
                              check_files=check_files, check_sizes=check_sizes)
    if problems:
        shown = "\n  ".join(problems[:25])
        more = (f"\n  ... and {len(problems) - 25} more"
                if len(problems) > 25 else "")
        raise KitError(
            f"kit failed verification ({len(problems)} problems):\n  "
            f"{shown}{more}")
    return Kit(root, raw, entries)


@lru_cache(maxsize=8)
def _cached_kit(root_str: str, registers: tuple[str, ...] | None,
                check_files: bool, check_sizes: bool) -> Kit:
    return load_kit(Path(root_str), registers=set(registers) if registers else None,
                    check_files=check_files, check_sizes=check_sizes)


def kit_for(register: str, root: Path | str = ".", *,
            check_files: bool = True, check_sizes: bool = True) -> Kit:
    """The kit, verified for one register. Cached — a render loads it once."""
    return _cached_kit(str(Path(root).resolve()), (register,),
                       check_files, check_sizes)


def pick_register(script_sha: str) -> str:
    """The register for a video, seeded by its script sha.

    Chosen ONCE per video and applied to every plate in it: a video is
    entirely marker or entirely ballpoint, never mixed. Slot geometry is
    identical across all four registers precisely so this swap costs nothing
    — no coordinate anywhere is recalculated when it changes.
    """
    if not script_sha:
        return REGISTERS[0]
    return REGISTERS[int(script_sha[:8], 16) % len(REGISTERS)]
