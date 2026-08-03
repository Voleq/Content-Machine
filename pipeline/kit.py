"""The design-kit asset registry.

``assets/kit/kit-registry.json`` is the single source of truth for the kit:
384 addressable assets under ``family/asset`` keys, each declaring its frames,
``frameCount``, ``fps``, ``playback``, ``canvas``, ``aspect``, ``exportScale``
and ``slots``. This module is the read side of it.

It reads the registry and *only* the registry. The previous version walked the
filesystem, which is how contact sheets became addressable assets, how a stray
``_b`` twin whose base had moved families stayed resolvable, and how the same
drawing under two naming schemes counted as two options. Nothing is discovered
here: a file that is not in the registry does not exist, and
:meth:`Kit.verify` fails the build when one turns up in an asset folder.

Four shapes of asset need more than a single lookup, and all four are declared
rather than inferred:

* **playback** — ``static``, ``boil`` (a two-frame line wobble at ~6fps),
  ``one-shot`` (play once, hold the last frame) and ``loop``. The player in
  :mod:`pipeline.kit_frames` reads this plus ``frameCount``/``fps``; there is
  no per-family special case anywhere.
* **slots** — declared text boxes in **canvas** coordinates. The shorts batch
  is exported at ``exportScale: 2``, so a slot box has to be scaled before it
  is composited onto the raw PNG. Getting that wrong misplaces every number by
  exactly half, silently, which is why :class:`Slot` carries the scale rather
  than leaving it to each call site.
* **aliases** — fifteen groups of byte-identical drawings shipped under two
  naming schemes. The alias resolves *through* to its canonical key, and
  :meth:`Kit.family` hides aliases, so "pick a different reaction" can no
  longer hand back the same drawing.
* **meta** — contact sheets and probes are never ingested (see
  ``scripts/ingest_kit.py``), and the names are recorded here so
  :meth:`Kit.verify` can tell "someone left a contact sheet in the folder"
  apart from "this artwork has no registry entry".

A missing kit is not fatal for lookups — they return ``None`` and the caller
falls back to what it drew before — but an *unresolved key* is: see
:meth:`Kit.require`, which is what the render path calls.
"""

from __future__ import annotations

import functools
import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

KIT_DIRNAME = "kit"
REGISTRY_NAME = "kit-registry.json"

# Fallbacks for a registry that predates a field. Every current entry declares
# its own, so these only matter for hand-written test fixtures.
DEFAULT_FPS = 12
BOIL_FPS = 6

PALETTE = {
    "paper": (242, 242, 239),
    "floor": (219, 212, 200),
    "ink": (35, 35, 38),
    "red": (255, 82, 71),
    "green": (47, 213, 118),
    "grey": (143, 140, 131),
}


class KitError(RuntimeError):
    """An asset the render needs is not in the kit.

    Raised rather than warned: a beat that silently degrades to a backdrop is
    how a render ships looking wrong while every test stays green.
    """


@dataclass(frozen=True)
class Slot:
    """One declared text box on an asset, in CANVAS coordinates."""

    name: str
    x: int
    y: int
    w: int
    h: int
    align: str = "center"
    valign: str = "middle"
    font_family: str = "Space Mono"
    font_weight: int = 700
    colour: str = "ink"
    case: str = ""          # "upper" folds the value before drawing
    tracking: float = 0.0   # extra letter-spacing, as a fraction of the size
    italic: bool = False
    wrap: bool = False      # long copy wraps to the box instead of shrinking
    clear: str = ""         # paint the box back to this palette colour first
    note: str = ""

    def scaled(self, export_scale: int) -> tuple[int, int, int, int]:
        """The box in PIXEL coordinates of the exported PNG.

        The trap this exists to close: the boxes are authored against the
        canvas (1080x1080), the PNGs ship at 2x (2160x2160), and compositing
        the unscaled box puts every figure at half its intended position with
        nothing on screen to say so.
        """
        s = max(int(export_scale or 1), 1)
        return self.x * s, self.y * s, self.w * s, self.h * s

    @classmethod
    def from_registry(cls, raw: dict) -> "Slot":
        box = raw.get("box") or {}
        font = raw.get("font") or {}
        return cls(
            name=str(raw.get("name", "")),
            x=int(box.get("x", 0)), y=int(box.get("y", 0)),
            w=int(box.get("w", 0)), h=int(box.get("h", 0)),
            align=str(raw.get("align", "center")),
            valign=str(raw.get("valign", "middle")),
            font_family=str(font.get("family", "Space Mono")),
            font_weight=int(font.get("weight", 700)),
            colour=str(raw.get("colour", "ink")),
            case=str(raw.get("case", "")),
            tracking=float(raw.get("tracking", 0.0)),
            italic=bool(raw.get("italic", False)),
            wrap=bool(raw.get("wrap", False)),
            clear=str(raw.get("clear", "")),
            note=str(raw.get("note", "")),
        )


@dataclass(frozen=True)
class SlotFrameDelta:
    """How an asset's slot boxes move per frame index.

    Only ``shorts/dennis-vs-numbers/numbers-raining`` declares one: the rain
    falls, so a figure that stays put detaches from the drop it is supposed to
    be sitting in. The wrap is what makes the loop seamless — a box that has
    fallen past ``max_y`` comes back up by ``span``.
    """

    dx: float = 0.0
    dy: float = 0.0
    min_y: float | None = None
    max_y: float | None = None
    span: float = 0.0

    def at(self, slot: Slot, frame_index: int) -> tuple[int, int]:
        """Slot origin (canvas coords) on `frame_index`."""
        x = slot.x + self.dx * frame_index
        y = slot.y + self.dy * frame_index
        if self.span > 0 and self.max_y is not None:
            while y > self.max_y:
                y -= self.span
            if self.min_y is not None:
                while y < self.min_y:
                    y += self.span
        return int(round(x)), int(round(y))

    @classmethod
    def from_registry(cls, raw: dict | None) -> "SlotFrameDelta | None":
        if not raw:
            return None
        wrap = raw.get("wrap") or {}
        return cls(
            dx=float(raw.get("x", 0.0)), dy=float(raw.get("y", 0.0)),
            min_y=(float(wrap["minY"]) if "minY" in wrap else None),
            max_y=(float(wrap["maxY"]) if "maxY" in wrap else None),
            span=float(wrap.get("span", 0.0)),
        )


@dataclass(frozen=True)
class Asset:
    """One addressable kit asset, exactly as the registry declares it."""

    key: str
    family: str
    name: str
    source: str
    frames: tuple[Path, ...]
    frame_count: int
    playback: str
    fps: int
    canvas: tuple[int, int]
    export_scale: int
    aspect: str
    alpha: bool
    title: str = ""
    slots: tuple[Slot, ...] = ()
    slot_frame_delta: SlotFrameDelta | None = None
    alias_of: str = ""
    dead_mouth_flap: bool = False
    # For a micro-motion strip: the shot it animates. Its f01 must stay
    # byte-identical to that shot's still.
    base_asset: str = ""

    @property
    def animated(self) -> bool:
        return self.frame_count > 1 and self.playback != "static"

    @property
    def path(self) -> Path:
        """The first frame — what a still-image caller wants."""
        return self.frames[0]

    def slot(self, name: str) -> Slot | None:
        return next((s for s in self.slots if s.name == name), None)

    @property
    def pixel_size(self) -> tuple[int, int]:
        s = max(self.export_scale or 1, 1)
        return self.canvas[0] * s, self.canvas[1] * s


class Kit:
    """Read-only index over the exported design kit."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self._assets: dict[str, Asset] = {}
        self._aliases: dict[str, str] = {}
        self._meta_names: tuple[str, ...] = ()
        self._meta_dirs: tuple[str, ...] = ()
        self.palette: dict[str, str] = {}

        registry = self.root / REGISTRY_NAME
        if not registry.exists():
            log.warning("kit registry not found at %s — kit lookups will return "
                        "nothing (run scripts/ingest_kit.py)", registry)
            return
        try:
            data = json.loads(registry.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log.warning("kit registry unreadable (%s) — kit lookups disabled", exc)
            return

        roots = data.get("roots") or {}
        self.palette = data.get("palette") or {}
        meta = data.get("meta") or {}
        self._meta_names = tuple(meta.get("names") or ())
        self._meta_dirs = tuple(meta.get("dirs") or ())
        self._aliases = dict(data.get("aliases") or {})

        for key, raw in (data.get("assets") or {}).items():
            self._assets[key] = self._build(key, raw, roots)

    # ------------------------------------------------------------- loading
    def _frame_root(self, source: str, roots: dict) -> Path:
        """Where a source's frame paths are relative to.

        The registry states this as a repo-relative path (``assets/kit/`` and
        ``assets/kit/shorts/``); only the tail past the kit directory matters
        here, because the kit may be mounted anywhere.
        """
        declared = "/" + str(roots.get(source, "")).strip("/") + "/"
        marker = f"/{KIT_DIRNAME}/"
        tail = declared.split(marker, 1)[1] if marker in declared else ""
        return self.root / tail if tail else self.root

    def _build(self, key: str, raw: dict, roots: dict) -> Asset:
        source = str(raw.get("source", "kit-v1"))
        base = self._frame_root(source, roots)
        canvas = raw.get("canvas") or {}
        playback = str(raw.get("playback", "static"))
        fps = int(raw.get("fps") or 0)
        if not fps and playback != "static":
            fps = BOIL_FPS if playback == "boil" else DEFAULT_FPS
        return Asset(
            key=key,
            family=str(raw.get("family", key.rsplit("/", 1)[0])),
            name=str(raw.get("name", key.rsplit("/", 1)[-1])),
            source=source,
            frames=tuple(base / f for f in raw.get("frames", ())),
            frame_count=int(raw.get("frameCount") or len(raw.get("frames", ())) or 1),
            playback=playback,
            fps=fps,
            canvas=(int(canvas.get("w", 0)), int(canvas.get("h", 0))),
            export_scale=int(raw.get("exportScale") or 1),
            aspect=str(raw.get("aspect", "")),
            alpha=bool(raw.get("alpha", True)),
            title=str(raw.get("title", "")),
            slots=tuple(Slot.from_registry(s) for s in (raw.get("slots") or ())),
            slot_frame_delta=SlotFrameDelta.from_registry(raw.get("slotFrameDelta")),
            alias_of=str(raw.get("aliasOf", "")),
            dead_mouth_flap=bool(raw.get("deadMouthFlap", False)),
            base_asset=str(raw.get("baseAsset", "")),
        )

    # ---------------------------------------------------------------- basics
    def __contains__(self, key: str) -> bool:
        return self.get(key) is not None

    def __len__(self) -> int:
        return len(self._assets)

    def keys(self) -> tuple[str, ...]:
        """Every registered key, aliases included."""
        return tuple(sorted(self._assets))

    def canonical(self, key: str) -> str:
        """Follow the alias chain to the drawing that actually ships."""
        seen: set[str] = set()
        while key in self._aliases and key not in seen:
            seen.add(key)
            key = self._aliases[key]
        return key

    def get(self, key: str) -> Asset | None:
        """The asset for a key (following aliases), or None."""
        asset = self._assets.get(self.canonical(key))
        if asset is None:
            return None
        return asset if asset.frames and asset.frames[0].exists() else None

    def require(self, key: str, *, why: str = "") -> Asset:
        """The asset for a key, or raise.

        Every render path that names an asset by hand uses this. The old
        behaviour — log a warning, fall back to a designed backdrop — is why a
        short could reach six assets out of 384 and still pass its tests.
        """
        asset = self.get(key)
        if asset is None:
            known = self._assets.get(self.canonical(key))
            detail = (f"registry entry exists but its frames are missing from "
                      f"{self.root}" if known else "no registry entry")
            raise KitError(
                f"kit asset {key!r} did not resolve ({detail})"
                + (f" — needed for {why}" if why else "")
                + ". Add it to assets/kit/kit-registry.json, or use a key the "
                  "registry carries (`/kit doctor` lists what is missing)."
            )
        return asset

    def path(self, key: str) -> Path | None:
        asset = self.get(key)
        return asset.path if asset else None

    def frames(self, key: str) -> list[Path]:
        asset = self.get(key)
        return list(asset.frames) if asset else []

    def size(self, key: str) -> tuple[int, int] | None:
        asset = self.get(key)
        return asset.pixel_size if asset else None

    def has_alpha(self, key: str) -> bool:
        asset = self.get(key)
        return bool(asset and asset.alpha)

    def slots(self, key: str) -> tuple[Slot, ...]:
        asset = self.get(key)
        return asset.slots if asset else ()

    # -------------------------------------------------------------- families
    @functools.lru_cache(maxsize=512)  # noqa: B019 (instances are long-lived)
    def family(self, prefix: str) -> tuple[str, ...]:
        """Every CANONICAL, independently pickable asset in a family.

        Two exclusions, both for the same reason — an option list must only
        contain things that are actually different:

        * **aliases**, the same drawing under a second name. Offering them
          separately is what let "pick a different reaction" return the
          identical frame; the real reaction count is 10, not 25.
        * **``-talk`` twins**, which are the mouth-open frame of the asset
          beside them, reached through :meth:`talk_pair`. Listed on their own
          they read as twenty-one extra drawings that do not exist.
        """
        prefix = prefix.rstrip("/")
        return tuple(sorted(
            k for k, a in self._assets.items()
            if a.family == prefix and not a.alias_of
            and not (k.endswith("-talk") and self.canonical(k[:-5]) in self._assets)
        ))

    def families(self) -> tuple[str, ...]:
        return tuple(sorted({a.family for a in self._assets.values()}))

    def aliases(self) -> dict[str, str]:
        return dict(self._aliases)

    def dead_mouth_flaps(self) -> tuple[str, ...]:
        """`-talk` twins identical to the frame they should differ from.

        Read off the raw entries rather than through :meth:`get`, which
        follows the alias to the base and would report nothing — the flag is
        on the twin, and the twin is the alias.
        """
        return tuple(sorted(k for k, a in self._assets.items()
                            if a.dead_mouth_flap))

    def pick(self, prefix: str, seed: str, *, ledger: "VariantLedger | None" = None,
             record: bool = True) -> Path | None:
        """One asset from a family, chosen deterministically from `seed`.

        The same seed always picks the same frame, so a render is reproducible,
        while different scripts spread across the family. A `ledger` biases the
        choice away from what recent uploads already showed, so a daily channel
        does not open on the same drawing twice running.
        """
        asset = self.pick_asset(prefix, seed, ledger=ledger, record=record)
        return asset.path if asset else None

    def pick_asset(self, prefix: str, seed: str, *,
                   ledger: "VariantLedger | None" = None,
                   record: bool = True) -> Asset | None:
        options = list(self.family(prefix))
        if not options:
            return None
        if ledger is not None:
            options = ledger.unused(prefix, options)
        digest = hashlib.sha256(f"{prefix}|{seed}".encode()).hexdigest()
        chosen = options[int(digest[:8], 16) % len(options)]
        if ledger is not None and record:
            ledger.record(prefix, chosen)
        return self.get(chosen)

    # ------------------------------------------------------------ resolution
    def resolve_asset(self, prefix: str | tuple[str, ...], key: str) -> Asset | None:
        """An asset by family + key, tolerating the family's naming prefix.

        ``[PROP: podium]`` should find ``props/podium-ceo`` and
        ``[BIGNUM: buyback]`` should find ``big-number-buyback``, without the
        script author having to know the kit's internal naming — so every
        hyphen-boundary suffix is tried, longest match first.

        `prefix` may be several families: the kit spreads one tag's artwork
        across more than one folder (an ALERT is a press lower-third), and a
        tag that resolved only against a single hardcoded folder is how most of
        the library stayed unreachable.
        """
        prefixes = (prefix,) if isinstance(prefix, str) else tuple(prefix)
        key = key.strip().lower().replace(" ", "-").replace("_", "-")
        for head in prefixes:
            head = head.rstrip("/")
            direct = self.get(f"{head}/{key}")
            if direct is not None:
                return direct
        for head in prefixes:
            head = head.rstrip("/") + "/"
            for name in self.family(head.rstrip("/")):
                leaf = name[len(head):]
                if leaf == key:
                    return self.get(name)
                # leaf "big-number-buyback" offers suffixes "number-buyback"
                # and "buyback"; a bare split would only ever try the first.
                parts = leaf.split("-")
                if any("-".join(parts[i:]) == key for i in range(1, len(parts))):
                    return self.get(name)
        return None

    def resolve(self, prefix: str | tuple[str, ...], key: str) -> Path | None:
        asset = self.resolve_asset(prefix, key)
        return asset.path if asset else None

    # ------------------------------------------------------------ host pairs
    def talk_pair(self, key: str) -> tuple[Asset, Asset] | None:
        """(mouth-closed, mouth-open) for an asset shipping a ``-talk`` twin.

        Returns None when there is no twin, and also when the twin is the same
        drawing — ``chapters/management/dennis-reads-proxy-talk`` is
        byte-identical to its base, so flapping between them animates nothing.
        Saying so here means the caller holds a still instead of pretending.
        """
        base = self.get(key)
        talk = self.get(f"{key}-talk")
        if base is None or talk is None:
            return None
        if talk.key == base.key or talk.dead_mouth_flap or talk.alias_of == base.key:
            return None
        return base, talk

    # Every micro-motion strip declares the shot it animates. `-idle-b` is the
    # second idle cycle, alternated with `-idle` so a long hold never reads as
    # one repeating loop.
    MICRO_SUFFIXES = ("-blink", "-idle", "-idle-b")

    def micro_motion_pairs(self) -> list[tuple[str, str]]:
        """`(strip key, base key)` for every micro-motion strip registered.

        Read off the strip's own `baseAsset` where ingest recorded one, and
        off the naming convention otherwise — so a hand-added strip is held to
        the same rule as an ingested one.
        """
        out: list[tuple[str, str]] = []
        for key, asset in sorted(self._assets.items()):
            base = getattr(asset, "base_asset", "")
            if not base:
                for suffix in self.MICRO_SUFFIXES:
                    if key.endswith(suffix):
                        base = key[: -len(suffix)]
                        break
            if base and base in self._assets:
                out.append((key, base))
        return out

    def micro_motion_drift(self) -> list[str]:
        """Strips whose f01 is not byte-identical to the shot it belongs to.

        This is the invariant the motion batch was re-exported to satisfy, and
        the only one that cannot be recovered by looking at the artwork: f01 is
        supposed to BE the base still, so a blink can start on any hold and
        land back on the shot's own pose with nothing moving but the eyelid.

        It is a byte comparison rather than a pixel one on purpose. The failure
        this catches is a base still that went through a lossy re-encode —
        palette quantisation moved every pixel in the frame by about a level,
        which is invisible in a diff and reads on screen as a pop the moment
        the strip starts. Two files that are the same drawing but not the same
        bytes have already lost the property.
        """
        out: list[str] = []
        for key, base in self.micro_motion_pairs():
            strip, shot = self._assets[key], self._assets[base]
            if not strip.frames or not shot.frames:
                continue
            f01, still = strip.frames[0], shot.frames[0]
            if not f01.is_file() or not still.is_file():
                continue
            if f01.read_bytes() == still.read_bytes():
                continue
            out.append(
                f"{key}: f01 is not byte-identical to {base} — a blink or "
                f"idle that starts on this shot will pop "
                f"({f01.name} vs {still.name})")
        return out

    def micro_motion(self, key: str, suffix: str) -> Asset | None:
        """A ``-blink`` / ``-idle`` strip twinned with `key`, or None.

        The same naming convention :meth:`talk_pair` uses, and for the same
        reason: a later artwork batch drops the strips beside the shots they
        belong to, ingest registers them, and the face gains a blink with no
        code change and no hand-edited registry.

        The guards are the ones that made ``-talk`` honest. A strip that is an
        alias of its base, or that ships a single frame, animates nothing —
        saying so here means the caller boils instead of pretending.
        """
        base = self.get(key)
        twin = self.get(f"{key}{suffix}")
        if base is None or twin is None:
            return None
        if twin.key == base.key or twin.alias_of == base.key:
            return None
        if twin.frame_count < 2:
            log.debug("micro-motion %s%s ships %d frame(s) — skipped",
                      key, suffix, twin.frame_count)
            return None
        return twin

    # ------------------------------------------------------------------ boil
    def boil(self, key: str) -> list[Path]:
        """The frames to alternate on a hold — one entry for a static asset."""
        return self.frames(key)

    # ------------------------------------------------------------ validation
    def is_meta(self, rel: Path) -> bool:
        return (rel.name in self._meta_names
                or any(p in self._meta_dirs for p in rel.parts))

    def verify(self) -> list[str]:
        """Everything wrong with the kit on disk, as readable lines.

        Two failures, both of which used to be invisible:

        * a registry entry whose frame is not on disk — the asset resolves in
          the catalogue and then renders nothing;
        * a PNG sitting in an asset folder with no registry entry — the shape
          that let twenty contact sheets be picked up as artwork.
        """
        problems: list[str] = []
        declared: set[Path] = set()
        for key, asset in sorted(self._assets.items()):
            for frame in asset.frames:
                declared.add(frame.resolve())
                if not frame.exists():
                    problems.append(
                        f"{key}: registry lists {frame.relative_to(self.root)} "
                        f"but it is not on disk")
        problems += self.micro_motion_drift()
        if not self.root.exists():
            return problems
        for png in sorted(self.root.rglob("*.png")):
            if png.resolve() in declared:
                continue
            rel = png.relative_to(self.root)
            problems.append(
                f"{rel}: PNG in an asset folder with no registry entry"
                + (" (looks like a contact sheet — those belong in the "
                   "archive, not the kit)" if self.is_meta(rel) else ""))
        return problems


class VariantLedger:
    """Which kit variants recent videos already used.

    Deterministic selection keeps a single video from repeating itself, but the
    channel publishes daily and nothing stopped two consecutive uploads from
    opening on the same layout. This biases selection away from what was used
    recently — the cheapest thing available that actually keeps the channel
    looking fresh.

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
        """Every asset key any recent render reached — what the doctor diffs
        the library against to find the artwork nothing has ever used."""
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
    return VariantLedger(Path(settings.state_dir) / "kit_variants.json")


@functools.lru_cache(maxsize=8)
def load_kit(assets_dir: Path) -> Kit:
    """The kit under an assets directory, cached per path."""
    return Kit(Path(assets_dir) / KIT_DIRNAME)
