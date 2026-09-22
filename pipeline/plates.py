"""The plate registry — the read side of the materialised design kit.

``assets/plates/plates-registry.json`` is the single source of truth: every
addressable plate under a ``family/name`` key, each declaring its frames,
playback, canvas, ``exportScale`` and its slots, and each drawn once per hour
the kit lights the set at. ``scripts/ingest_kit.py`` writes it by running the
kit's own engine; this module reads it and *only* it.

THE HOUR IS THE EPISODE'S, NOT THE PLATE'S. The library a template, a director
or the curation names is the base hour's; every other hour is the same drawing
in another colour table, reached by viewing the registry at that hour
(:meth:`Registry.at`). A render picks its hour once and every registry loaded
while it runs is that view (:func:`at_episode_hour`), so no plate in a dusk
video can come out at night because the code that chose it forgot to ask.

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
import re as _re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Collection, Any, Iterator

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


def fold_chapter_type(raw: str) -> str:
    """A type as a writer typed it, in the kit's spelling.

    "Resigned close", "resigned_close" and "resigned-close" are the same type,
    and the writer types the trailer by hand. Shared rather than repeated
    because three copies of three `.replace()` calls is how the renderer comes
    to record `resigned-close` for a chapter the upload records as `resigned
    close` — the same chapter, in two buckets, which is the exact defect the
    type was introduced to fix.

    Folding only. Whether the result is one of the sixteen is a question for
    whoever is validating, and they do not all answer it the same way.
    """
    return str(raw).strip().lower().replace(" ", "-").replace("_", "-")

# Six periods, always: four fiscal years, the last full year, and LTM. Every
# table and every time-series chart in the kit is authored six wide. Anything
# that assumes five drops LTM, which is the column the argument usually turns
# on.
PERIOD_COUNT = 6

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
    # A CONTROL CHANNEL, NOT A BOX. Ten slots carry an integer that names which
    # row, column or line the script is arguing about — `structure/sensitivity`
    # rings that cell in `attention`, `paper/receipt-*` highlights that line —
    # and the engine gives them w = h = 0 on purpose, because an index has no
    # extent. Never compute a fill area, a scale or a text budget from one.
    #
    # THE KIT SAYS SO IN ITS OWN WORDS and this reads them: `control: true`
    # where the plate declares the flag, and the `control` role, which all ten
    # carry and which is the only signal the six receipt plates give. Those
    # flags are three of the twenty-nine slot fields delta-14's whitelist
    # dropped, so until the manifests were re-emitted verbatim there was
    # nothing here to read — which is why a deliberate zero was indistinguishable
    # from a broken one.
    control: bool = False
    overlay: str = ""             # the plate composited into it (band-N)
    renderer: str = ""            # a data region series.py fills
    contact: dict = field(default_factory=dict)   # where he touches the furniture
    sets_type: bool = False       # the plate declares a typeRole for its role
    export_scale: int = 2
    note: str = ""
    # THE BUDGET FOR THIS BOX, not for this role. 0 means the slot declares none
    # and the role's floor applies.
    #
    # One role is set in boxes of different widths on the same plate:
    # `structure/flow-16x9` sets `caption` in a 1620-unit strip AND in a
    # 104-unit arrow label. A single number per role is wrong in one of them by
    # construction — sized for the strip it waves through copy that collides in
    # the arrow, sized for the arrow it refuses a caption that fits. So the kit
    # derives a budget per SLOT from the box it is set in, and the role keeps
    # the narrowest of them as a floor.
    max_chars: int = 0
    max_chars_per_line: int = 0
    max_lines: int = 0
    # THE PALETTE ROLE FOR THIS BOX, not for this role — the same two-level
    # shape as `max_chars` above, and read the same way.
    #
    # IT WORKS TODAY AND THAT IS THE TRAP. `TITLE_GROUND` is `"card"`, under
    # `card` every room title resolves to `structure`, and the chapter-opener
    # path assumed `structure`. So the assumption and the kit agree, silently,
    # and nothing reads the field. The day a title is set on the `slab`
    # treatment the colour moves to `ground` and a path that assumed
    # `structure` sets dark ink on dark ink and says nothing — the same class
    # of failure as the borrowed wall legibility the title card was built to
    # fix. Empty means the slot declares none and the role's colour stands.
    colour: str = ""
    # WHAT THE TYPE SITS ON: `card`, `slab` or none. Informational here — the
    # ground is drawn into the plate art, not by this code.
    ground: str = ""
    # The box that ground occupies, in canvas units. INFORMATIONAL, and the use
    # is to assert the type lands inside its own ground rather than to draw
    # anything: a title that overhangs its card is back to being set on the
    # wall, which is the whole thing the card exists to prevent.
    ground_box: dict = field(default_factory=dict)

    def scaled(self) -> tuple[int, int, int, int]:
        """The box in delivered pixels."""
        s = self.export_scale
        return (self.x * s, self.y * s, self.w * s, self.h * s)

    @property
    def is_text(self) -> bool:
        """Whether anything typed goes here — asked of the KIT, not of Python.

        A slot takes type when its plate declares a ``typeRoles`` entry for its
        role: that entry is the face, size, weight, colour role and character
        limit the type is set in, so a slot with no entry has nothing to be set
        in and takes no words. A ``renderer`` slot is a series drawn as a
        shape; an ``overlay`` slot is a row highlight that lights when named.

        This used to be a list of role names kept in Python, and the list was
        wrong in the expensive direction: ``figure`` names the host's body on
        the eighteen room angles AND the number in every table cell, so 395
        figure slots — every cell of every sheet, every big number, every
        fraction — were classified as reserved area and silently drew nothing.
        A sheet came out with its headers, its row labels, its bands and no
        numbers, which is the one thing a numbers sheet is for.

        A kit is free to invent a role this code has never heard of. It cannot
        be free to have its type quietly dropped for having done so.
        """
        return self.sets_type and not self.renderer and not self.overlay

    @property
    def is_band(self) -> bool:
        return bool(self.overlay)

    @classmethod
    def from_registry(cls, name: str, raw: dict, export_scale: int,
                      type_roles: dict | None = None) -> "Slot":
        role = str(raw.get("role", ""))
        return cls(
            name=name,
            x=int(raw["x"]), y=int(raw["y"]),
            w=int(raw["w"]), h=int(raw["h"]),
            role=role,
            align=str(raw.get("align", "left")),
            region=bool(raw.get("region", False)),
            control=bool(raw.get("control", False)) or role == "control",
            overlay=str(raw.get("overlay", "")),
            renderer=str(raw.get("renderer", "")),
            contact=raw.get("contact") if isinstance(raw.get("contact"), dict) else {},
            sets_type=bool((type_roles or {}).get(role)),
            export_scale=export_scale,
            note=str(raw.get("note", "")),
            max_chars=int(raw.get("maxChars") or 0),
            max_chars_per_line=int(raw.get("maxCharsPerLine") or 0),
            max_lines=int(raw.get("maxLines") or 0),
            colour=str(raw.get("colour") or ""),
            ground=str(raw.get("ground") or ""),
            ground_box=(raw.get("groundBox")
                        if isinstance(raw.get("groundBox"), dict) else {}),
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
    # "static" | "loop" | "overlay".
    #
    # `overlay` ARRIVED WITH delta-14 and nothing plays it yet. The seven
    # blink strips carry it: they are not poses and no template selects one
    # — the renderer composites the strip over the matching idle frame at
    # 0,0, frame for frame, for about 100ms every three or four seconds.
    # Played as a loop in its own right a blink strip is a disembodied pair
    # of eyelids, so `animated` deliberately excludes it and the compositor
    # has to learn the mode before any of them is reachable.
    playback: str
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
    # The raw `hostAnchor` field: a dict on a plate that carries one, the
    # literal False on a plate that REFUSES one, and None when the plate never
    # mentioned it. Three states, and `or {}` collapsed the last two into each
    # other — which is how "this angle has no floor for him to stand on" and
    # "nobody wrote the field" became the same thing to this code.
    host_anchor_declared: Any = None
    alpha: bool = False
    solve: str = ""
    anchor: str = ""
    ink_weight: float = 0.0
    # HOW MANY COLUMNS THE PLATE WAS AUTHORED FOR — always a count here, even
    # on the plates whose engine field is a list. See `_build` for why the one
    # word carries two meanings and how the count is recovered from each.
    columns: int = 0
    # The per-column geometry, `{x, w, role}` in canvas units, on the plates
    # that declare it and empty on the plates that do not. Present so the
    # count above can stay a count without throwing the measurements away.
    column_boxes: tuple = ()
    # HOW MANY ROWS THE PLATE WAS AUTHORED FOR, off the manifest.
    #
    # `tables/multiples-strip` ships 6 rows in 16:9 and 3 in 9:16 — the
    # portrait plate is a re-author with fewer rows AND one fewer column, not
    # the landscape one cropped. A director that picks six metrics for a short
    # has picked a plate that cannot hold them, and the honest place to say so
    # is against the number the plate itself declares.
    rows: int = 0
    # A CAMERA DISTANCE, NOT A CUT-OUT. `close-up` and `medium` declare a
    # `framing` and no floor line: they are not figures to stand somewhere,
    # they are the shot itself, and `fit` says how to place one — on the eye
    # line, scaled by head height, running off the left and right edges by
    # design.
    framing: str = ""
    glance: str = ""              # "camera-left" | "camera-right" | "to camera"
    fit: dict = field(default_factory=dict)
    # THE HOUR THIS ART IS DRAWN AT, and the key of the same plate at the base
    # hour. Every plate exists at every hour the kit draws — same author, same
    # seed, same slots, another colour table — so an hour is a variant of a
    # plate, never a plate of its own. Empty on a registry that draws one hour.
    hour: str = ""
    at_base_hour: str = ""
    # A ROOM IN TWO LAYERS, split where he stands: `back` is everything behind
    # him and `front` the desk and whatever is on it. The base file is both at
    # once, for a shot with nobody in it. Empty on every other plate.
    layers: dict = field(default_factory=dict)
    # Whether the angle may be shot at an hour other than the one its light was
    # drawn for. The kit marks its wide angles False: their cast shadows still
    # fall where the night lamp puts them. None when the plate does not say.
    dusk_safe: bool | None = None

    @property
    def base_key(self) -> str:
        """The key this plate has at the base hour — the drawing, not the hour."""
        return self.at_base_hour or self.key

    def layer_path(self, name: str) -> Path | None:
        """``back`` or ``front`` of a layered room, or None on a flat plate."""
        f = self.layers.get(name)
        return self.root / self.family / f if f else None

    @property
    def host_anchor(self) -> dict:
        """What the plate declares about standing a host on it. `{}` if nothing."""
        d = self.host_anchor_declared
        return d if isinstance(d, dict) else {}

    @property
    def refuses_host(self) -> bool:
        """Whether the plate says, in the field, that nobody stands here.

        `room/high-desk-down` is the camera looking down at the desk: there is
        no floor in shot, so there is nowhere for him to stand and the plate
        says `hostAnchor: false` rather than leaving the field out.
        `room/wall-of-calls` refuses for the same reason.

        A refusal is DATA and is different from an omission. Reading them as
        the same thing is how a renderer ends up compositing a man onto a
        surface the camera is above.
        """
        return self.host_anchor_declared is False

    @property
    def host_contact(self) -> dict:
        """Where he touches the furniture at this angle, if the plate says.

        `{pose, surface, x, y}` in the room's CANVAS units: which pose makes
        contact here, what he is touching, and the point his hand lands on.
        Twelve room plates carry one. Without it he is placed in the middle of
        the anchor, which on a wide angle is standing in open floor next to a
        desk he is not touching.
        """
        anchor = self.slot("host-anchor")
        got = (anchor.contact if anchor is not None else None) \
            or self.host_anchor.get("contact")
        return got if isinstance(got, dict) else {}

    @property
    def animated(self) -> bool:
        return (self.playback not in ("static", "overlay")
                and self.frame_count > 1)

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



def _prefer_unused(options: list[str],
                   avoid: "Collection[str]") -> list[str]:
    """Drop what recent videos already used — unless that leaves nothing.

    A PREFERENCE, never a constraint. Rotation exists so two consecutive
    videos do not look like one video with a different ticker; a rotation that
    could fail a render for want of an unused drawing would be a worse bug
    than the sameness it prevents. When every option has been used recently,
    every option is back on the table and the seed decides as it always did.
    """
    if not avoid:
        return options
    fresh = [k for k in options if k not in avoid]
    return fresh or options


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

        # THE HOURS THE SET IS DRAWN AT: an hour name to the suffix its keys
        # carry, and the base hour is the one with none. Every plate in the
        # kit is drawn at every one of them.
        _hours = raw.get("hours") or {}
        self.hour_suffixes: dict[str, str] = {
            str(k): str(v) for k, v in (_hours.get("suffixes") or {}).items()
            if not str(k).startswith("_")}
        self.base_hour: str = next(
            (h for h, suffix in self.hour_suffixes.items() if not suffix), "")
        # WHICH OF THEM AN EPISODE MAY BE DRAWN AT, picked from uniformly. A
        # separate field from the one above because "the kit draws dusk" and
        # "half the channel is at dusk" are two different decisions, and only
        # collapsing them makes the second one nobody's. An hour the kit draws
        # and this list omits is unreachable, and `reachable_plates` says so.
        self.hour_rotation: tuple[str, ...] = tuple(
            str(h) for h in (_hours.get("episodes") or ())
            if str(h) in self.hour_suffixes) or tuple(self.hour_suffixes)[:1]

        # ONE PALETTE PER HOUR, because the plates are. Dusk plates are light
        # ground and violet ink: a caption coloured off the night table sets
        # pale type on a pale card, and nothing about the frame says why.
        raw_palettes = raw.get("palettes") or {}
        if not raw_palettes:
            raw_palettes = {self.base_hour: (raw.get("palette") or {}).get("roles") or {}}
        self.palettes: dict[str, dict[str, str]] = {}
        for hour, pal in raw_palettes.items():
            missing = [r for r in PALETTE_ROLES if r not in (pal or {})]
            if missing:
                raise PlateError(
                    f"the registry's {hour or 'base'} palette is missing "
                    f"{', '.join(missing)} — it must declare all eight roles, "
                    f"because code asks for a role and never for a hex")
            self.palettes[hour] = {k: str(v) for k, v in pal.items()}
        self.palette: dict[str, str] = self.palettes.get(
            self.base_hour, next(iter(self.palettes.values())))
        self.surface: str = (raw.get("palette") or {}).get("surface", "")

        # THE LIBRARY IS THE BASE HOUR. `assets` is every plate once, under the
        # key a template, a director or the curation names it by; its other
        # hours are variants of it, found through `plate_at` and through a
        # registry viewed at an hour. Listing them beside it would put every
        # plate into every chapter's options twice, and rotate a video between
        # a drawing and itself.
        purposes: dict[str, str] = raw.get("purposes") or {}
        self._everything: dict[str, Plate] = {}
        for key, entry in (raw.get("assets") or {}).items():
            self._everything[key] = self._build(key, entry, purposes)
        self._library: dict[str, Plate] = {
            k: p for k, p in self._everything.items()
            if not p.hour or p.hour == self.base_hour}
        self._variants: dict[str, dict[str, Plate]] = {}
        for p in self._everything.values():
            if p.hour and p.hour != self.base_hour:
                self._variants.setdefault(p.hour, {})[p.base_key] = p
        # Keyed by the base-hour key always; the VALUES are the art at the hour
        # this registry is viewed at. So a caller holding `reg.assets[key]`
        # gets the episode's hour exactly as one calling `reg.get(key)` does,
        # and no route to a plate is left drawing night into a dusk video.
        self.assets: dict[str, Plate] = self._library
        # The hour this registry is VIEWED at, set only by `at`. Empty is the
        # base library, with the base palette.
        self._hour: str = ""
        self._views: dict[str, "Registry"] = {}

        self.host_roles: dict[str, tuple[str, ...]] = {
            k: tuple(v) for k, v in (raw.get("hostRoles") or {}).items()}
        self.host_poses: dict[str, dict] = raw.get("hostPoses") or {}
        self.room_roles: dict[str, tuple[str, ...]] = {
            k: tuple(v) for k, v in (raw.get("roomRoles") or {}).items()}
        # Which keys are the same shot in other clothes. `figure` is settled at
        # ingest (the outfit is baked into the pose art); `medium` is a pair of
        # keys, so the choice is the pipeline's and has to be made once per
        # episode rather than once per shot.
        #
        # A REGISTRY WITH NO WARDROBE BLOCK IS STALE, NOT BARE. `roles.json`
        # has always declared one; the ingest did not stamp it, so this read
        # `{}` and the robe was unreachable by name — a silent no-op that
        # looked exactly like a working picker.
        if "wardrobe" not in raw:
            raise PlateError(
                f"{path} declares no `wardrobe` — the kit's roles.json has "
                f"one, so this registry predates the ingest that stamps it. "
                f"Re-run `python scripts/ingest_kit.py kit`")
        self.wardrobe: dict[str, dict] = {
            k: v for k, v in (raw.get("wardrobe") or {}).items()
            if isinstance(v, dict)}
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
        # The typeRoles table goes in with the slots: whether a slot takes type
        # is the kit's answer, and the kit gives it here.
        type_roles = e.get("typeRoles") or {}
        slots = {n: Slot.from_registry(n, s, scale, type_roles)
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

        # `columns` ARRIVES IN TWO SHAPES, because two different plate authors
        # spell two different things with one word and the registry flattens
        # `meta` onto the entry, so they land on the same key.
        #
        #   charts/*, tables/*   `columns: 6`          — a COUNT
        #   figures/waterfall-*  `meta.columns: [...]` — COLUMN GEOMETRY,
        #   figures/scale-*                              {x, w, role} per column
        #
        # `int()` on the second raises, which is what refused the whole pack
        # the first time an ingest got as far as verifying it. The count of a
        # geometry list is its length, and that is not a guess: every waterfall
        # plate also declares `columns` on its own `bridge` slot, and the two
        # agree on all six. The scale plates carry one entry per figure column
        # and no second opinion to disagree with.
        #
        # The geometry is KEPT rather than reduced away. `series.waterfall` is
        # handed x and width per column so it never re-derives where a column
        # is, and a reader who only got the count back would have to.
        raw_columns = e.get("columns")
        column_boxes = tuple(raw_columns) if isinstance(raw_columns, list) else ()
        columns = len(column_boxes) if column_boxes else int(raw_columns or 0)

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
            # A room is drawn from the set model, not by a seeded author, and
            # says so with a null.
            seed=int(e["seed"]) if e.get("seed") is not None else 1,
            outfit=str(e.get("outfit") or ""),
            floor_line_y=e.get("floorLineY"),
            host_anchor_declared=e.get("hostAnchor", None),
            alpha=bool(e.get("alpha", False)),
            solve=str(e.get("solve", "")),
            anchor=str(e.get("anchor", "")),
            ink_weight=float(e.get("inkWeight") or 0.0),
            columns=columns,
            column_boxes=column_boxes,
            rows=int(e.get("rows") or 0),
            framing=str(e.get("framing") or ""),
            glance=str(e.get("glance") or ""),
            fit=dict(e.get("fit") or {}),
            hour=str(e.get("hour") or ""),
            at_base_hour=str(e.get("atBaseHour") or ""),
            layers={k: str(v) for k, v in (e.get("layers") or {}).items()
                    if k in ("back", "front") and v},
            dusk_safe=(None if e.get("duskSafe") is None else bool(e["duskSafe"])),
        )

    # ---------------------------------------------------------------- basics

    def __len__(self) -> int:
        return len(self.assets)

    def __contains__(self, key: str) -> bool:
        return key in self._everything

    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(self.assets))

    def get(self, key: str) -> Plate | None:
        """A plate by key, AT THE HOUR THIS REGISTRY IS VIEWED AT.

        Any hour's key finds its plate; a base key on a registry viewed at dusk
        finds the dusk art. So a template or a director names a plate once,
        and the episode's hour is applied here, to every plate at once, rather
        than at each of the places a plate is chosen.
        """
        p = self._everything.get(key)
        if p is None or not self._hour:
            return p
        return self.assets.get(p.base_key, p)

    def require(self, key: str, *, why: str = "") -> Plate:
        p = self.get(key)
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

    def all_plates(self) -> dict[str, Plate]:
        """Every plate at every hour, by its own key. For checking, not choosing."""
        return dict(self._everything)

    # ----------------------------------------------------------------- hours

    @property
    def hour(self) -> str:
        """The hour this registry is viewed at; the base hour when it is not."""
        return self._hour or self.base_hour

    def at(self, hour: str) -> "Registry":
        """This registry viewed at one hour: its plates, its palette, its rooms.

        THE HOUR IS A PROPERTY OF THE EPISODE, applied once. A view returns the
        hour's art for every key and the hour's palette for every colour, and
        answers `hour_for` with its own hour whatever it is asked, so nothing
        downstream can choose a second one and cut dusk against night.
        """
        if hour not in self.hour_suffixes:
            raise PlateError(
                f"the kit draws no {hour!r} hour — it draws "
                f"{', '.join(self.hour_suffixes) or '(none)'}")
        view = self._views.get(hour)
        if view is not None:
            return view
        import copy

        view = copy.copy(self)
        view._hour = hour
        view.palette = self.palettes.get(hour, self.palette)
        view.hour_rotation = (hour,)
        swap = self._variants.get(hour, {})
        view.assets = {k: swap.get(k, p) for k, p in self._library.items()}
        self._views[hour] = view
        return view

    def plate_at(self, key: str, hour: str) -> Plate | None:
        """The plate `key` names, drawn at `hour`. None when the key is unknown.

        Falls back to the base-hour plate when the kit draws no variant at that
        hour, which is a single-hour registry or a plate that has no hour.
        """
        p = self._everything.get(key)
        if p is None:
            return None
        base = self._library.get(p.base_key, p)
        if not hour or hour == self.base_hour:
            return base
        return self._variants.get(hour, {}).get(p.base_key) or base

    def base_key(self, key: str) -> str:
        """The base-hour key of any plate key, including one this kit retired.

        Recent videos are recorded by the keys they actually used, and a dusk
        video used dusk keys. Rotation asks whether a DRAWING was used
        recently, so it compares base keys; `hour_for` reads the hours off the
        same records and needs the keys as they were.
        """
        p = self._everything.get(key)
        if p is not None:
            return p.base_key
        for hour, suffix in self.hour_suffixes.items():
            if suffix:
                m = _re.match(rf"^(.*){_re.escape(suffix)}(-16x9|-9x16)?$", key)
                if m:
                    return m.group(1) + (m.group(2) or "")
        return key

    def base_keys(self, keys: "Collection[str]") -> set[str]:
        """`base_key` over a collection: which DRAWINGS a set of keys names."""
        return {self.base_key(k) for k in keys}

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
        return self.base_key(key) in self.plates_for_chapter(ctype)

    # ----------------------------------------------------------------- host

    def host_for(self, role: str, seed: str = "",
                 avoid: "Collection[str]" = ()) -> Plate | None:
        """A host pose for a shot ROLE, off the registry.

        The roles and the poses that serve them are curation shipped WITH the
        kit, not a list in this codebase. A new kit with a different set of
        poses drops in by shipping its own ``roles.json``.

        `avoid` is what recent videos already used. It is a PREFERENCE, never
        a constraint: a role served by one pose still yields that pose, so
        rotation can never fail a render for want of a fresh drawing.
        """
        options = [k for k in self.host_roles.get(role, ()) if k in self.assets]
        if not options:
            return None
        options = _prefer_unused(options, self.base_keys(avoid))
        rng = random.Random(f"{role}|{seed}")
        return self.get(rng.choice(options))

    def framing_for(self, role: str, seed: str = "",
                    avoid: "Collection[str]" = ()) -> Plate | None:
        """A host pose for a role that is a FRAMING — a camera distance.

        ``host_for`` with the one filter the "nobody stands here" case needs. A
        room declaring ``hostAnchor: false`` has no floor, so only a plate with
        no floor line of its own can be put in it, and asking a role for any of
        its members is not the same question: a role is curation and gains
        members in a drop. delta-15 added ``host/sitting-at-desk``, a cut-out
        with ``floorLineY: 1728``, to ``to-camera`` — after which ``host_for``
        could answer that call with a figure that has to stand somewhere.

        ``None`` when the role serves no framing, which is a real answer and
        the caller's to handle: it means this kit cannot shoot that beat.
        """
        options = [k for k in self.host_roles.get(role, ())
                   if k in self.assets and not self.assets[k].floor_line_y]
        if not options:
            return None
        options = _prefer_unused(options, self.base_keys(avoid))
        rng = random.Random(f"{role}|{seed}")
        return self.get(rng.choice(options))

    def host_roles_available(self) -> tuple[str, ...]:
        return tuple(sorted(self.host_roles))

    def host_strip(self, pose_key: str, kind: str) -> Plate | None:
        """``("host/leaning-on-desk", "talk")`` -> the talk strip, or None.

        ``head-in-hands`` and ``walking-out-of-frame`` ship talk frames for
        continuity of the file set and declare ``talks: false``, because using
        them looks like a mistake. Honour the declaration, not the file list.
        """
        pose_key = self.base_key(pose_key)
        if kind == "talk" and not self.host_poses.get(pose_key, {}).get("talks", True):
            return None
        return self.get(f"{pose_key}-{kind}" if kind else pose_key)

    def host_limit(self, pose_key: str) -> int | None:
        # By the base key: the curation names each pose once, and a dusk
        # episode holding `host/head-in-hands-dusk` is still capped at one.
        v = self.host_poses.get(self.base_key(pose_key), {}).get("limit")
        return int(v) if v is not None else None

    def hour_for(self, episode: str,
                 avoid: "Collection[str]" = ()) -> str:
        """Which hour the set is at for this EPISODE. One per video, never two.

        THE ARGUMENT IS THE EPISODE AND NOTHING ELSE, and that is the whole
        guarantee. Every other seed in the room path carries a shot index or a
        title so that consecutive rooms differ — feed one of those in here and
        the hour changes mid-video, which is the one thing the kit says not to
        do: two hours on one wall in one video is two rooms, not one room later.

        An episode with no identity gets the first hour in the rotation, which
        is `night` — the set the kit was built at, and the empty suffix.

        A registry VIEWED at an hour answers with that hour, whatever it is
        asked: the render chose it once for the whole episode (`episode_hour`).
        """
        if self._hour:
            return self._hour
        hours = list(self.hour_rotation)
        if not hours:
            return ""
        if not episode:
            return hours[0]
        # An hour the recent videos have already been shot at is a preference
        # to move off, on the same terms as a plate: the set changing hour
        # between videos is most of what makes two of them look different.
        #
        # Every key belongs to exactly one hour — the one its plate is drawn
        # at, or the one whose suffix it carries, or the BASE hour when it
        # carries none. Deriving it that way rather than testing each suffix in
        # turn is what keeps the base hour avoidable: it has no suffix, so a
        # suffix test can never match it and `night` would be unavoidable.
        used = {self._hour_of_key(k) for k in avoid if k.startswith("room/")}
        fresh = [h for h in hours if h not in used]
        if fresh and len(fresh) < len(hours):
            hours = fresh
        return random.Random(f"hour|{episode}").choice(hours)

    def _hour_of_key(self, key: str) -> str:
        """Which hour a key is shot at. The base hour carries no suffix."""
        p = self._everything.get(key)
        if p is not None:
            return p.hour or self.base_hour
        if self.base_key(key) != key:
            for hour, suffix in self.hour_suffixes.items():
                if suffix and suffix in key:
                    return hour
        return self.base_hour or (self.hour_rotation[0] if self.hour_rotation else "")

    def room_for(self, role: str, aspect: str, seed: str = "",
                 episode: str = "", avoid: "Collection[str]" = ()) -> Plate:
        """One of the angles that fill a room ROLE. Raises if none do.

        THIS USED TO RETURN NONE AND THE CALLER DREW FLAT GROUND. `render_long`
        asked for a `panel` room for every two-shot and `roles.json` declared
        no such role, so every two-shot in the format was composed on a plain
        colour with no room in it at all — for weeks, silently, because a
        renderer that never fails for want of a backdrop never mentioned it.

        `episode` picks the HOUR and `seed` picks the angle within it. They are
        two arguments rather than one because they are chosen at two different
        granularities: the angle rotates shot to shot, the hour does not move
        for the whole video. Passing no episode keeps the night set.
        """
        hour = self.hour_for(episode, avoid=avoid)
        options = self.angles_for(role, aspect, hour)
        if options:
            options = _prefer_unused(options, self.base_keys(avoid))
        if not options:
            known = ", ".join(sorted(self.room_roles)) or "(none)"
            raise PlateError(
                f"no room plate fills the role {role!r} at {aspect}. The kit "
                f"declares {known} — either `roles.json` is missing this role "
                f"or none of its angles ships in this aspect")
        rng = random.Random(f"{role}|{aspect}|{seed}")
        return self.plate_at(rng.choice(options), hour)

    def angles_for(self, role: str, aspect: str, hour: str = "") -> list[str]:
        """The base keys of every angle that can shoot a room ROLE at `hour`.

        An angle the kit marks unsafe away from its own light (`duskSafe:
        false`) is left out at any hour but the base one — its cast shadows
        fall where the night lamp puts them, and a long cast across a wall
        that dusk lights from the other side reads as a mistake. Unless that
        leaves the role with nothing: then every angle is back, and the log
        says so, because a room with a wrong shadow is a smaller fault than a
        render that cannot find a room.
        """
        options = [k for stem in self.room_roles.get(role, ())
                   if (k := self.aspect_key(stem, aspect))]
        if hour and hour != self.base_hour:
            safe = [k for k in options if self.assets[k].dusk_safe is not False]
            if options and not safe:
                log.warning("every %s angle at %s is marked unsafe at %s; "
                            "shooting one anyway", role, aspect, hour)
            options = safe or options
        return options

    # --------------------------------------------------------------- verify

    def verify(self) -> list[str]:
        """Every file the registry names, present, and every room decided about.

        Returns problems, never raises.
        """
        problems: list[str] = []
        for key, p in sorted(self._everything.items()):
            for name in p.layers:
                if not p.layer_path(name).exists():
                    problems.append(f"{key}: missing {name} layer {p.layer_path(name)}")
            if not p.path.exists():
                problems.append(f"{key}: missing base file {p.path}")
            for fr, fp in zip(p.frames, p.frame_paths()):
                if not fp.exists():
                    problems.append(f"{key}: missing frame {fr.tag or '(base)'} {fp}")

            # A ROOM SAYS WHETHER ANYONE STANDS IN IT, ONE WAY OR THE OTHER.
            #
            # `room/high-desk-down` is the camera above the desk: there is no
            # floor in shot, so it declares `hostAnchor: false`. That refusal
            # is DATA. A room carrying neither an anchor nor the refusal has
            # not been decided about, and the renderer's only options are to
            # composite a man onto a surface the camera is above, or to drop
            # him silently — and it cannot tell which is intended.
            if p.family == "room" and p.slot("host-anchor") is None \
                    and not p.refuses_host:
                problems.append(
                    f"{key}: declares neither a host-anchor nor "
                    f"`hostAnchor: false`. A room says whether anyone stands "
                    f"in it; leaving the field out is not the same as saying "
                    f"no, and this code cannot tell which was meant.")
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


# The parsed registry, keyed by root, with the mtime it was parsed at.
#
# IT USED TO BE KEYED BY ROOT ALONE AND NEVER INVALIDATED, and the bot is a
# long-running process. `scripts/ingest_kit.py` installs a kit by `rmtree`-ing
# `assets/plates/` and copying the new one in, so an operator who ingested
# while the service was up got the previous kit's registry serving every render
# until somebody happened to restart — new artwork on disk, old geometry in
# memory, and nothing on screen looking wrong because every plate it named
# still existed. That is the kit-swap failure in its most literal form: the bot
# holding a delivery that is no longer installed.
#
# The registry file is rewritten by every install, so its mtime is the whole
# signal. One `stat` per `load_plates` against a parse of a ~10MB JSON.
_CACHE: dict[Path, tuple[float, Registry]] = {}


def wall_of_calls(settings, *, limit: int = 7) -> dict[str, str]:
    """`room/wall-of-calls`'s slot values, from the thesis book.

    Seven index cards on a wall: a ticker, the date it was covered, and one
    word for how it went. Every one of them is a video this channel actually
    published — the book already records the ticker, the date and whether the
    thesis is intact, cracking or broken, and until now nothing put it on
    screen. A wall of invented calls would be the exact opposite of the
    segment: it is credible because it is the receipts.

    Empty when the book is empty, which is the honest render of a channel that
    has not covered anything yet — seven blank cards, not seven made-up ones.
    """
    try:
        from pipeline.standing import ThesisBook

        book = ThesisBook(settings)
        rows = [book.get(t) for t in book.tickers()]
    except Exception:                              # noqa: BLE001 — never fatal
        return {}

    rows = [t for t in rows if t is not None]
    rows.sort(key=lambda t: (t.workdate or t.recorded_at or ""), reverse=True)
    values: dict[str, str] = {"kicker": "THE WALL"}
    for i, t in enumerate(rows[:limit], start=1):
        values[f"ticker-{i}"] = t.ticker
        values[f"date-{i}"] = (t.workdate or (t.recorded_at or "")[:10])[-5:]
        values[f"outcome-{i}"] = (t.status or "intact").split()[0][:8]
    return values


# THE HOUR OF THE EPISODE BEING RENDERED, for every registry loaded inside it.
#
# A context variable rather than an argument because a video's plates are
# chosen in a dozen modules and each of them loads the registry itself — the
# frames, the marks, the host, the charts, the colour a caption is set in — and
# an hour threaded through all of them is an hour one of them drops. The rooms
# were the only plates with an hour in the last kit, so asking at the one place
# a room was chosen was enough; in this one every plate has one. Set by
# `at_episode_hour`; empty outside a render, where `load_plates` is the base
# library it always was.
_EPISODE_HOUR: ContextVar[str] = ContextVar("episode_hour", default="")


def current_episode_hour() -> str:
    """The hour the render in progress is drawn at, or "" outside one."""
    return _EPISODE_HOUR.get()


@contextmanager
def episode_hour(hour: str) -> Iterator[str]:
    """Every registry loaded inside this block is viewed at `hour`."""
    token = _EPISODE_HOUR.set(hour or "")
    try:
        yield hour
    finally:
        _EPISODE_HOUR.reset(token)


def recorded_hour(workspace) -> str:
    """The hour an earlier pass of this video recorded, newest first, or ""."""
    try:
        found = sorted(Path(workspace).glob("*manifest*.json"),
                       key=lambda m: m.stat().st_mtime, reverse=True)
    except OSError:
        return ""
    for manifest in found:
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        hour = payload.get("hour") if isinstance(payload, dict) else None
        if isinstance(hour, str) and hour:
            return hour
    return ""


def hour_of_episode(settings, workspace, episode: str) -> str:
    """Which hour this video is drawn at. Chosen once, then kept.

    AN EARLIER PASS OF THE SAME VIDEO DECIDES IT. The draft, the proof and the
    final are one video, and a proof exists to be a proof of the thing that
    ships: choosing again at each pass lets any render in between move the
    rotation, and the final comes out at the other hour from the proof that
    was approved. So the hour a manifest in this workspace already recorded
    stands for as long as the kit still shoots episodes at it. Otherwise the
    registry picks, off the episode, steering away from the hours the last
    few videos were shot at.
    """
    from pipeline.reach import recent_plates

    reg = load_plates(settings.assets_dir)
    kept = recorded_hour(workspace)
    if kept and kept in reg.hour_rotation:
        return kept
    return reg.hour_for(episode, avoid=recent_plates(settings, exclude=workspace))


@contextmanager
def at_episode_hour(settings, workspace, episode: str) -> Iterator[str]:
    """Render inside this: one hour for the episode, on every plate in it.

    Nested, it keeps the hour already set, so a cover made inside a render is
    a frame of that render rather than a second pick. With no kit installed
    the hour is empty and the render's own `load_plates` raises the error that
    names the ingest.
    """
    hour = _EPISODE_HOUR.get()
    if not hour:
        try:
            hour = hour_of_episode(settings, workspace, episode)
        except PlateError:
            hour = ""
    with episode_hour(hour):
        yield hour


def load_registry(root: Path) -> Registry:
    """The registry at ``root``, cached until the file underneath it changes.

    Re-read on a new mtime rather than once per process: an ingest replaces
    `assets/plates/` wholesale under a running bot, and a cache with no way to
    notice is a bot rendering the kit before last. See `_CACHE`.

    Inside a render it is the registry VIEWED AT THE EPISODE'S HOUR (see
    `_EPISODE_HOUR`), which is how the hour reaches every plate at once.
    """
    root = Path(root)
    path = root / REGISTRY_NAME
    try:
        stamp = path.stat().st_mtime
    except OSError:
        # Missing or unreadable: fall through to `Registry`, whose error names
        # the ingest. Never serve a cached kit for a registry that is gone.
        _CACHE.pop(root, None)
        return Registry(root)
    hit = _CACHE.get(root)
    if hit is not None and hit[0] == stamp:
        reg = hit[1]
    else:
        reg = Registry(root)
        _CACHE[root] = (stamp, reg)
    hour = _EPISODE_HOUR.get()
    return reg.at(hour) if hour else reg


def load_plates(assets_dir: Path) -> Registry:
    """The installed kit, from an ``assets/`` directory."""
    return load_registry(Path(assets_dir) / PLATES_DIRNAME)
