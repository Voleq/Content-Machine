"""The plate registry — the read side of the materialised design kit.

``assets/plates/plates-registry.json`` is the single source of truth: 113
addressable plates under ``family/name`` keys, each declaring its frames,
playback, canvas, ``exportScale`` and its slots. ``scripts/ingest_kit.py``
writes it by running the kit's own engine; this module reads it and *only* it.

Nothing is discovered from the filesystem. A PNG that the registry does not
name does not exist, and ingest fails the build when one turns up in a family
folder. That is not pedantry — walking the filesystem is how a contact sheet
became an addressable asset, and how a drawing whose entry had moved stayed
resolvable from a script long after it stopped meaning anything.

Three things here are contracts rather than conveniences:

* **Colour is asked for by ROLE.** :meth:`Registry.colour` takes ``"down"`` or
  ``"attention"``; there is no hex literal anywhere in ``pipeline/``. The kit
  ships eight roles and a colour never does two jobs — ``down`` is a fall and
  nothing else, and emphasis is ``attention``. The previous kit had one red
  doing both, so a frame could not distinguish "this number went down" from
  "look at this number".

* **A slot is never clipped to its canvas.** Twelve annotation slots sit
  outside their own plate on purpose — ``annotations/bracket-rows``'s ``area``
  is at x = −880 — because a mark is composited onto something else and its
  caption lands beside the mark, not inside it. Clipping silently drops every
  annotation caption, and silently is the operative word.

* **``exportScale`` is 2 and slot boxes are canvas units.** Delivered pixels
  are canvas × 2. Getting this wrong puts every figure at half its intended
  position, silently, which is why :class:`Slot` carries the scale rather than
  leaving the multiply to each call site.
"""

from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

PLATES_DIRNAME = "plates"
REGISTRY_NAME = "plates-registry.json"

# The eight palette roles the kit declares. Named here so a typo in a call site
# fails loudly against a known set instead of resolving to None and painting
# black — but the VALUES come off the registry, which got them off the engine
# that drew the plates. No hex literal lives in Python.
PALETTE_ROLES = (
    "ground", "second-ground", "structure", "down", "up",
    "neutral-data", "attention", "other-party",
)

# The sixteen generic chapter types, fixed. A director returns one of these
# plus a display title; the type decides which plates the chapter may use and
# the title is the only thing that reaches the screen.
#
# A type may appear TWICE in one video under different titles — "the numbers"
# early and again after guidance — so nothing keyed off a type may assume
# uniqueness, and no plate carries a baked ordinal.
CHAPTER_TYPES = (
    "cold-open", "how-we-got-here", "how-the-money-is-made", "the-numbers",
    "one-framework", "moat", "sector-comps", "management",
    "capital-allocation", "guidance-estimates", "short-interest", "valuation",
    "risk", "filing-walk", "bull-vs-bear", "resigned-close",
)

# Six periods, always: four fiscal years, the last full year, and LTM. Every
# table and every time-series chart in the kit is authored six wide. Anything
# that assumes five drops LTM, which is the column the argument usually turns
# on.
PERIOD_COUNT = 6

# Slot roles that reserve an area for DATA rather than for words. The plate
# draws the furniture around them and knows nothing about numbers; series.py
# and pipeline.chart fill them.
DATA_REGION_ROLES = frozenset({"plot-area", "bars", "path", "spark",
                               "host-anchor", "media", "figure", "head",
                               "mouth"})


class PlateError(RuntimeError):
    """A plate is missing, unknown, or the registry disagrees with the disk."""


@dataclass(frozen=True)
class Slot:
    """A declared box on a plate, in CANVAS units.

    Delivered pixels are canvas × ``export_scale``. Use :meth:`scaled` — the
    multiply belongs here, once, not at forty call sites.
    """

    name: str
    x: int
    y: int
    w: int
    h: int
    role: str = ""
    align: str = "left"
    region: bool = False          # a reserved area, not a text box
    overlay: str = ""             # the plate composited into it (band-N)
    renderer: str = ""            # a data region series.py fills
    export_scale: int = 2
    note: str = ""

    def scaled(self) -> tuple[int, int, int, int]:
        """The box in delivered pixels."""
        s = self.export_scale
        return (self.x * s, self.y * s, self.w * s, self.h * s)

    @property
    def is_text(self) -> bool:
        """Whether anything typed goes here.

        A region reserves space for something composited into it —
        ``host-anchor`` for the host, ``plot-area``/``bars``/``path`` for a data
        series. A slot carrying an ``overlay`` is a row highlight: naming it
        lights the band, it never takes words.

        Both of those were text boxes for one revision, which put a literal "1"
        over a lit row and counted a chart's plot area as copy somebody had
        forgotten to write.
        """
        return (not self.region and not self.renderer and not self.overlay
                and self.role not in DATA_REGION_ROLES)

    @property
    def is_band(self) -> bool:
        return bool(self.overlay)

    @classmethod
    def from_registry(cls, name: str, raw: dict, export_scale: int) -> "Slot":
        return cls(
            name=name,
            x=int(raw["x"]), y=int(raw["y"]),
            w=int(raw["w"]), h=int(raw["h"]),
            role=str(raw.get("role", "")),
            align=str(raw.get("align", "left")),
            region=bool(raw.get("region", False)),
            overlay=str(raw.get("overlay", "")),
            renderer=str(raw.get("renderer", "")),
            export_scale=export_scale,
            note=str(raw.get("note", "")),
        )


@dataclass(frozen=True)
class Frame:
    """One frame of a plate.

    FRAMES ARE OBJECTS, NOT FILENAMES, and this is permanent. A bare filename
    cannot say what a frame *is* — its boil offset, whether the mouth is open —
    so a player had to parse meaning out of a string suffix, which is exactly
    why a static plate and a two-frame loop looked identical to it. Read
    ``frame.png``; never build a name out of a key and a guessed suffix.
    """

    tag: str
    png: str
    svg: str = ""
    boil: int = 0
    mouth_open: bool = False
    bob: int = 0


@dataclass(frozen=True)
class Plate:
    """One addressable plate."""

    key: str
    family: str
    name: str
    canvas: tuple[int, int]
    delivered: tuple[int, int]
    export_scale: int
    aspect: str                   # "16x9", "9x16", or "" for aspect-free marks
    playback: str                 # "static" | "loop"
    fps: float
    frame_count: int
    frames: tuple[Frame, ...]
    files_png: str
    files_svg: str
    base_is_frame: str
    slots: dict[str, Slot]
    type_roles: dict[str, dict]
    root: Path
    purpose: str = ""
    author: str = ""
    seed: int = 1
    outfit: str = ""
    floor_line_y: int | None = None
    host_anchor: dict = field(default_factory=dict)
    alpha: bool = False
    solve: str = ""
    anchor: str = ""
    ink_weight: float = 0.0
    columns: int = 0

    @property
    def animated(self) -> bool:
        return self.playback != "static" and self.frame_count > 1

    @property
    def path(self) -> Path:
        """The base file — byte-identical to frame one on every boiling plate."""
        return self.root / self.family / self.files_png

    def frame_paths(self) -> list[Path]:
        return [self.root / self.family / f.png for f in self.frames]

    def slot(self, name: str) -> Slot | None:
        return self.slots.get(name)

    def require_slot(self, name: str) -> Slot:
        s = self.slots.get(name)
        if s is None:
            raise PlateError(
                f"{self.key} has no slot {name!r} — it declares "
                f"{', '.join(sorted(self.slots)) or '(none)'}")
        return s

    def text_slots(self) -> dict[str, Slot]:
        return {k: v for k, v in self.slots.items() if v.is_text}

    def slots_with_role(self, role: str) -> list[Slot]:
        return [s for s in self.slots.values() if s.role == role]

    @property
    def pixel_size(self) -> tuple[int, int]:
        return (self.delivered[0], self.delivered[1])


class Registry:
    """Every plate, the palette, and the curation that decides what goes where."""

    def __init__(self, root: Path):
        self.root = Path(root)
        path = self.root / REGISTRY_NAME
        if not path.exists():
            raise PlateError(
                f"no {REGISTRY_NAME} in {self.root} — run "
                f"`python scripts/ingest_kit.py kit` to materialise the design kit")
        raw = json.loads(path.read_text(encoding="utf-8"))

        self.kit: str = raw.get("kit", "")
        self.generated: str = raw.get("generated", "")
        self.outfit: str = raw.get("outfit", "")
        self.export_scale: int = int(raw.get("exportScale", 2))

        pal = (raw.get("palette") or {}).get("roles") or {}
        missing = [r for r in PALETTE_ROLES if r not in pal]
        if missing:
            raise PlateError(
                f"the registry palette is missing {', '.join(missing)} — it "
                f"must declare all eight roles, because code asks for a role "
                f"and never for a hex")
        self.palette: dict[str, str] = {k: str(v) for k, v in pal.items()}
        self.surface: str = (raw.get("palette") or {}).get("surface", "")

        purposes: dict[str, str] = raw.get("purposes") or {}
        self.assets: dict[str, Plate] = {}
        for key, entry in (raw.get("assets") or {}).items():
            self.assets[key] = self._build(key, entry, purposes)

        self.host_roles: dict[str, tuple[str, ...]] = {
            k: tuple(v) for k, v in (raw.get("hostRoles") or {}).items()}
        self.host_poses: dict[str, dict] = raw.get("hostPoses") or {}
        self.room_roles: dict[str, tuple[str, ...]] = {
            k: tuple(v) for k, v in (raw.get("roomRoles") or {}).items()}
        self._chapter_types: dict[str, dict] = raw.get("chapterTypes") or {}
        self._universal: tuple[str, ...] = tuple(
            (self._chapter_types.get("_universal") or {}).get("plates", ()))

    # ---------------------------------------------------------------- build

    def _build(self, key: str, e: dict, purposes: dict[str, str]) -> Plate:
        family = e.get("family") or key.split("/", 1)[0]
        name = key.split("/")[-1]
        scale = int(e.get("exportScale", self.export_scale))
        canvas = tuple(e["canvas"])
        delivered = tuple(e.get("delivered") or (canvas[0] * scale, canvas[1] * scale))

        frames = tuple(
            Frame(
                tag=str(f.get("tag") or ""),
                png=str(f["png"]),
                svg=str(f.get("svg") or ""),
                boil=int(f.get("boil") or 0),
                mouth_open=bool(f.get("mouthOpen", False)),
                bob=int(f.get("bob") or 0),
            )
            for f in e.get("frames", [])
        )
        files = e.get("files") or {}
        slots = {n: Slot.from_registry(n, s, scale)
                 for n, s in (e.get("slots") or {}).items()}

        # The purpose is looked up by key first and then by the aspect-free
        # stem, because a purpose is a property of the PLATE, not of which way
        # up it is: `tables/numbers-sheet-6r-16x9` and `-9x16` are one plate
        # re-authored, and writing the line twice is how the two drift apart.
        stem = key
        for suffix in ("-16x9", "-9x16"):
            if stem.endswith(suffix):
                stem = stem[: -len(suffix)]
        purpose = purposes.get(key) or purposes.get(stem, "")

        return Plate(
            key=key, family=family, name=name,
            canvas=canvas, delivered=delivered, export_scale=scale,
            aspect=str(e.get("aspect") or ""),
            playback=str(e.get("playback", "static")),
            fps=float(e.get("fps") or 0.0),
            frame_count=int(e.get("frameCount", len(frames) or 1)),
            frames=frames,
            files_png=str(files.get("png") or f"{name}.png"),
            files_svg=str(files.get("svg") or ""),
            base_is_frame=str(files.get("baseIsFrame") or ""),
            slots=slots,
            type_roles=e.get("typeRoles") or {},
            root=self.root,
            purpose=purpose,
            author=str(e.get("author", "")),
            seed=int(e.get("seed", 1)),
            outfit=str(e.get("outfit") or ""),
            floor_line_y=e.get("floorLineY"),
            host_anchor=e.get("hostAnchor") or {},
            alpha=bool(e.get("alpha", False)),
            solve=str(e.get("solve", "")),
            anchor=str(e.get("anchor", "")),
            ink_weight=float(e.get("inkWeight") or 0.0),
            columns=int(e.get("columns") or 0),
        )

    # ---------------------------------------------------------------- basics

    def __len__(self) -> int:
        return len(self.assets)

    def __contains__(self, key: str) -> bool:
        return key in self.assets

    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(self.assets))

    def get(self, key: str) -> Plate | None:
        return self.assets.get(key)

    def require(self, key: str, *, why: str = "") -> Plate:
        p = self.assets.get(key)
        if p is not None:
            return p
        near = self.nearest(key)
        hint = f" Did you mean {near}?" if near else ""
        raise PlateError(
            f"no plate {key!r}" + (f" ({why})" if why else "") + "." + hint)

    def nearest(self, key: str) -> str:
        """The closest registered key, for an error message worth reading."""
        import difflib
        m = difflib.get_close_matches(key, self.assets, n=1, cutoff=0.6)
        return m[0] if m else ""

    def family(self, name: str) -> tuple[str, ...]:
        pre = name if name.endswith("/") else name + "/"
        return tuple(sorted(k for k in self.assets if k.startswith(pre)))

    def families(self) -> tuple[str, ...]:
        return tuple(sorted({p.family for p in self.assets.values()}))

    # ---------------------------------------------------------------- colour

    def colour(self, role: str) -> tuple[int, int, int]:
        """The RGB for a palette ROLE. There is no hex literal in the pipeline.

        ``down`` is a fall and nothing else; emphasis is ``attention``. The old
        kit had one red doing both jobs, so nothing on screen could tell "this
        number went down" apart from "look at this number".
        """
        hex_ = self.palette.get(role)
        if hex_ is None:
            raise PlateError(
                f"unknown palette role {role!r} — the kit declares "
                f"{', '.join(sorted(self.palette))}")
        h = hex_.lstrip("#")
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))

    def colour_hex(self, role: str) -> str:
        self.colour(role)          # validate
        return self.palette[role]

    def direction_colour(self, value: float) -> tuple[int, int, int]:
        """``up`` for a rise, ``down`` for a fall, ``neutral-data`` for neither.

        A number with no direction is neutral data even when the story about it
        is bad news — that is the rule the eight roles exist to keep.
        """
        if value > 0:
            return self.colour("up")
        if value < 0:
            return self.colour("down")
        return self.colour("neutral-data")

    # ---------------------------------------------------------------- aspect

    def aspect_key(self, stem: str, aspect: str) -> str | None:
        """``("tables/numbers-sheet-6r", "16x9")`` -> the key that exists.

        9:16 is a re-author, not a crop, so both halves are separate plates and
        some families ship only one — ``structure/flow`` is 16:9 only because a
        left-to-right process has no portrait form.
        """
        for cand in (f"{stem}-{aspect}", stem):
            if cand in self.assets:
                p = self.assets[cand]
                if not p.aspect or p.aspect == aspect:
                    return cand
        return None

    # ------------------------------------------------------------- chapters

    def chapter_types_available(self) -> tuple[str, ...]:
        """The types this kit carries curation for, in the fixed canonical order."""
        return tuple(c for c in CHAPTER_TYPES if c in self._chapter_types)

    def universal_plates(self) -> tuple[str, ...]:
        """Every plate available to EVERY chapter type.

        Titles, the set, the host, marks, row highlights and framed foreign
        media belong to every chapter, so they are declared once rather than
        repeated sixteen times.
        """
        out: set[str] = set()
        for key in self.assets:
            for pre in self._universal:
                if key == pre or key.startswith(pre):
                    out.add(key)
                    break
        return tuple(sorted(out))

    def chapter_purpose(self, ctype: str) -> str:
        return (self._chapter_types.get(ctype) or {}).get("purpose", "")

    def plates_for_chapter(self, ctype: str) -> tuple[str, ...]:
        """Every plate key this chapter TYPE may use.

        The type gates the library; the title is the only thing on screen. A
        prefix in the curation matches a family (``"tables/"``) or a plate stem
        across both aspects (``"structure/flow"``).
        """
        if ctype not in CHAPTER_TYPES:
            raise PlateError(
                f"unknown chapter type {ctype!r} — the sixteen are "
                f"{', '.join(CHAPTER_TYPES)}")
        allowed = list(self._universal)
        allowed += list((self._chapter_types.get(ctype) or {}).get("plates", ()))
        out: set[str] = set()
        for key in self.assets:
            for pre in allowed:
                if key == pre or key.startswith(pre):
                    out.add(key)
                    break
        return tuple(sorted(out))

    def chapter_allows(self, ctype: str, key: str) -> bool:
        return key in self.plates_for_chapter(ctype)

    # ----------------------------------------------------------------- host

    def host_for(self, role: str, seed: str = "") -> Plate | None:
        """A host pose for a shot ROLE, off the registry.

        The roles and the poses that serve them are curation shipped WITH the
        kit, not a list in this codebase. A new kit with a different set of
        poses drops in by shipping its own ``roles.json``.
        """
        options = [k for k in self.host_roles.get(role, ()) if k in self.assets]
        if not options:
            return None
        rng = random.Random(f"{role}|{seed}")
        return self.assets[rng.choice(options)]

    def host_roles_available(self) -> tuple[str, ...]:
        return tuple(sorted(self.host_roles))

    def host_strip(self, pose_key: str, kind: str) -> Plate | None:
        """``("host/leaning-on-desk", "talk")`` -> the talk strip, or None.

        ``head-in-hands`` and ``walking-out-of-frame`` ship talk frames for
        continuity of the file set and declare ``talks: false``, because using
        them looks like a mistake. Honour the declaration, not the file list.
        """
        if kind == "talk" and not self.host_poses.get(pose_key, {}).get("talks", True):
            return None
        return self.assets.get(f"{pose_key}-{kind}" if kind else pose_key)

    def host_limit(self, pose_key: str) -> int | None:
        v = self.host_poses.get(pose_key, {}).get("limit")
        return int(v) if v is not None else None

    def room_for(self, role: str, aspect: str, seed: str = "") -> Plate | None:
        options = [k for stem in self.room_roles.get(role, ())
                   if (k := self.aspect_key(stem, aspect))]
        if not options:
            return None
        rng = random.Random(f"{role}|{aspect}|{seed}")
        return self.assets[rng.choice(options)]

    # --------------------------------------------------------------- verify

    def verify(self) -> list[str]:
        """Every file the registry names, present. Returns problems, never raises."""
        problems: list[str] = []
        for key, p in sorted(self.assets.items()):
            if not p.path.exists():
                problems.append(f"{key}: missing base file {p.path}")
            for fr, fp in zip(p.frames, p.frame_paths()):
                if not fp.exists():
                    problems.append(f"{key}: missing frame {fr.tag or '(base)'} {fp}")
        return problems


class VariantLedger:
    """Which plates recent videos already reached.

    Deterministic selection keeps a single video from repeating itself, but the
    channel publishes daily and nothing stopped two consecutive uploads from
    opening on the same angle. This biases selection away from what was used
    recently, and it is what `/kit doctor` diffs the library against to answer
    "what have we drawn and never reached" — the input to the next design
    batch.

    Stored as plain JSON in the state dir; a corrupt or missing file simply
    means no history, never an error.
    """

    def __init__(self, path: Path, keep: int = 6):
        self.path = Path(path)
        self.keep = keep
        self._recent: dict[str, list[str]] = {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._recent = {k: list(v) for k, v in data.items()
                                if isinstance(v, list)}
        except (OSError, ValueError):
            pass

    def recent(self, prefix: str) -> list[str]:
        return list(self._recent.get(prefix, []))

    def all_used(self) -> set[str]:
        """Every plate key any recent render reached."""
        return {name for names in self._recent.values() for name in names}

    def unused(self, prefix: str, options: list[str]) -> list[str]:
        """The options this family has not shown recently.

        Falls back to the full list once everything has been used — a family
        smaller than the history window must still return something.
        """
        recent = set(self._recent.get(prefix, []))
        fresh = [n for n in options if n not in recent]
        return fresh or list(options)

    def record(self, prefix: str, name: str) -> None:
        seen = [n for n in self._recent.get(prefix, []) if n != name]
        seen.append(name)
        self._recent[prefix] = seen[-self.keep:]

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._recent, indent=1, sort_keys=True),
                                 encoding="utf-8")
        except OSError as e:
            log.warning("could not persist the variant ledger (%s)", e)


def load_variant_ledger(settings) -> VariantLedger:
    """The ledger for this install. Its filename is unchanged on purpose: the
    history of what recent renders reached is still useful across the kit
    swap, even though none of the old keys resolve any more."""
    return VariantLedger(Path(settings.state_dir) / "kit_variants.json")


_CACHE: dict[Path, Registry] = {}


def load_registry(root: Path) -> Registry:
    """The registry at ``root``, cached — it is read once per process."""
    root = Path(root)
    if root not in _CACHE:
        _CACHE[root] = Registry(root)
    return _CACHE[root]


def load_plates(assets_dir: Path) -> Registry:
    """The installed kit, from an ``assets/`` directory."""
    return load_registry(Path(assets_dir) / PLATES_DIRNAME)
