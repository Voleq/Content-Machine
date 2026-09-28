"""Owned meme library + fallback providers (§6).

`[MEME: key]` (and the SHORT script's optional meme slot) resolves here:

    1. the OWNED library — assets/meme_library/, indexed by
       meme_index.json (filename stem -> tags + a one-line "use when").
       A key matches by exact stem first, then by tag.
    2. cache (a previously fetched fallback)
    3. fallback providers, only on a library miss: Giphy -> Tenor ->
       imgflip (each skipped unless configured; imgflip's get_memes is
       keyless). MOCK_MODE swaps in a deterministic offline client.
    4. a deterministic filler card — a missing meme never aborts a render.

`[MEME]` IS STILL, `[CLIP]` MOVES. Everything resolved through here is a
freeze-frame and is normalized to a still PNG on ingest (GIFs contribute their
first frame) and cached — a frozen meme is drier, and the freeze IS the joke's
timing. The same providers also answer the clip chain in `pipeline.broll`,
where the ask is the opposite: `search(..., animated=True)` returns the moving
form, because a clip of a shot going in reduced to one frame of a man mid-jump
has lost the only thing that made it worth showing.

A SHORT gets ONE meme, and it is picked here rather than asked for:
`choose_for_short` reads the script's own fields for the situation the story
is in — a beat that still sold off, a guidance cut, a hot print, a Fed day,
dilution, a squeeze, a press-release pump, a value trap — and matches it
against the index's tags and "use when". It reaches the OWNED LIBRARY AND
NOTHING PAST IT: no cache of fetched memes, no provider, no filler. A short
with nothing in the library that fits gets no meme, which is a better video
than one with a meme that does not fit.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Collection

import httpx

from config import Settings

log = logging.getLogger(__name__)

_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".gif")


@dataclass
class MemeAsset:
    key: str
    path: Path            # normalized still PNG, render-ready
    source: str           # library | cache | giphy | tenor | imgflip | filler
    attribution: str = ""


# ---------------------------------------------------------------------------
# The owned library.
# ---------------------------------------------------------------------------


class MemeLibrary:
    """assets/meme_library/ + meme_index.json. The index is the matching
    contract: stem -> {tags: [...], use_when: "..."}."""

    def __init__(self, settings: Settings, library_dir: Path | None = None):
        self.settings = settings
        self.dir = library_dir or settings.assets_dir / "meme_library"

    def index(self) -> dict[str, dict]:
        f = self.dir / "meme_index.json"
        if not f.exists():
            return {}
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            log.warning("meme_index.json is invalid JSON — library disabled")
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
        """Resolve a script key to an index stem: exact stem, then tag,
        then substring — deterministic (sorted stems)."""
        key_n = key.strip().lower().replace(" ", "-").replace("_", "-")
        idx = self.index()
        if key_n in idx:
            return key_n
        for stem in sorted(idx):
            tags = [t.lower() for t in idx[stem].get("tags", [])]
            if key_n in tags:
                return stem
        for stem in sorted(idx):
            if key_n in stem:
                return stem
        return None

    def resolve(self, key: str) -> Path | None:
        stem = self.match(key)
        return self._file_for(stem) if stem else None


# How an owned-library meme is credited, on the asset and so on the LONG's
# manifest. Written in one place because it is also READ: `recent_memes` finds
# the stems a long put on screen by parsing it back off the manifest, and a
# second spelling of the same sentence is the day that stops matching.
LIBRARY_ATTRIBUTION = "owned meme library ({stem})"
_LIBRARY_ATTRIBUTION_RE = re.compile(r"^owned meme library \((?P<stem>[^()]+)\)$")


def library_still(settings: Settings, src: Path) -> Path:
    """An owned-library meme as the render-ready still: a PNG, frozen, cached.

    One place for the library half of `MemeManager.resolve` and for the SHORT,
    which reaches the library and nothing past it.

    REDRAWN WHEN THE SOURCE IS NEWER. The cache is keyed on the stem, so a
    meme re-exported under the same name — a better crop, a typo fixed in the
    caption — would otherwise keep rendering the old file for as long as the
    cache lived, and nothing on screen would say why.
    """
    norm = settings.cache_dir / "memes" / "library" / f"{src.stem}.png"
    try:
        stale = (not norm.exists()
                 or norm.stat().st_mtime < src.stat().st_mtime)
    except OSError:
        stale = True
    if stale:
        normalize_meme(src, norm)
    return norm


# ---------------------------------------------------------------------------
# Fallback providers.
# ---------------------------------------------------------------------------


class _PoliteHttp:
    """Shared politeness: min interval between calls via a stamp file."""

    def __init__(self, settings: Settings, name: str):
        self.settings = settings
        self._stamp = settings.state_dir / f"{name}_last_call"

    def _respect_interval(self) -> None:
        try:
            last = float(self._stamp.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            last = 0.0
        wait = self.settings.image_min_interval_s - (time.time() - last)
        if wait > 0:
            time.sleep(wait)
        self._stamp.parent.mkdir(parents=True, exist_ok=True)
        self._stamp.write_text(str(time.time()), encoding="utf-8")

    def download(self, url: str, dest: Path) -> Path:
        self._respect_interval()
        dest.parent.mkdir(parents=True, exist_ok=True)
        with httpx.stream("GET", url, timeout=120, follow_redirects=True) as r:
            if r.status_code != 200:
                raise httpx.HTTPStatusError(
                    f"download failed {r.status_code}", request=r.request, response=r,
                )
            with open(dest, "wb") as f:
                for chunk in r.iter_bytes(1 << 16):
                    f.write(chunk)
        return dest


class GiphyClient(_PoliteHttp):
    name = "giphy"

    # The still forms, and the moving ones. Same search, same result set —
    # only which rendition is pulled off each hit changes, which is the whole
    # difference between a meme and an illustration.
    #
    # The moving list is ordered mp4-first: `downsized_small` and
    # `original_mp4` ARE mp4s, which are a fraction of the gif's size and are
    # what normalize_clip wants anyway. The two gif renditions are the
    # fallback for a hit that ships no mp4.
    _STILL_FORMS = ("downsized_still", "original_still")
    _MOVING_FORMS = ("downsized_small", "original_mp4", "downsized", "original")

    def search(self, query: str, *, animated: bool = False) -> str | None:
        if not self.settings.giphy_api_key:
            return None
        self._respect_interval()
        r = httpx.get(
            f"{self.settings.giphy_base_url}/v1/gifs/search",
            params={"api_key": self.settings.giphy_api_key, "q": query,
                    "limit": 3, "rating": "pg-13"},
            timeout=30,
        )
        if r.status_code != 200:
            log.warning("giphy %s for %r", r.status_code, query)
            return None
        forms = self._MOVING_FORMS if animated else self._STILL_FORMS
        for item in r.json().get("data", []):
            images = item.get("images", {})
            for form in forms:
                rendition = images.get(form) or {}
                url = (rendition.get("mp4") if animated else None) \
                    or rendition.get("url")
                if url:
                    return url
        return None


class TenorClient(_PoliteHttp):
    name = "tenor"

    _STILL_FORMS = ("png_transparent", "gifpreview", "gif")
    _MOVING_FORMS = ("mp4", "tinymp4", "gif", "tinygif")

    def search(self, query: str, *, animated: bool = False) -> str | None:
        if not self.settings.tenor_api_key:
            return None
        forms = self._MOVING_FORMS if animated else self._STILL_FORMS
        self._respect_interval()
        r = httpx.get(
            f"{self.settings.tenor_base_url}/v2/search",
            params={"key": self.settings.tenor_api_key, "q": query,
                    "limit": 3, "media_filter": ",".join(forms)},
            timeout=30,
        )
        if r.status_code != 200:
            log.warning("tenor %s for %r", r.status_code, query)
            return None
        for item in r.json().get("results", []):
            formats = item.get("media_formats", {})
            for fmt in forms:
                url = (formats.get(fmt) or {}).get("url")
                if url:
                    return url
        return None


class ImgflipClient(_PoliteHttp):
    name = "imgflip"

    def search(self, query: str, *, animated: bool = False) -> str | None:
        # imgflip is a library of meme TEMPLATES — flat jpgs, every one of
        # them. It has nothing to offer a caller that asked for motion, and
        # saying so is better than handing back a still that then normalises
        # into a one-frame "clip".
        if animated:
            return None
        self._respect_interval()
        r = httpx.get(f"{self.settings.imgflip_base_url}/get_memes", timeout=30)
        if r.status_code != 200:
            return None
        memes = r.json().get("data", {}).get("memes", [])
        tokens = {t for t in query.lower().replace("-", " ").split() if len(t) > 2}
        for m in memes:
            name_tokens = set(m.get("name", "").lower().split())
            if tokens & name_tokens:
                return m.get("url")
        return None


# How many frames a mock animated stand-in carries, and how long it runs.
# Short enough that a hold is usually LONGER than it is, which is the case the
# loop exists for; more than one frame, which is the whole point.
MOCK_GIF_FRAMES = 8
MOCK_GIF_FRAME_MS = 120


class MockMemeClient:
    """Deterministic offline fallback provider used in MOCK_MODE: search
    yields a mock:// URL; download GENERATES a captioned placeholder so
    the exact cache/normalize path is exercised with zero network.

    It answers both asks, because the two chains it stands in for want
    different things from the same provider. `animated=True` yields a
    `mock://gif/…` URL and downloads a real multi-frame GIF whose frames
    visibly differ — so "the clip moves and the meme does not" is a property
    of the artefact offline, not just of the production code path."""

    name = "mock"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.search_calls: list[str] = []
        self.download_calls: list[str] = []

    def search(self, query: str, *, animated: bool = False) -> str | None:
        self.search_calls.append(query)
        kind = "gif" if animated else "meme"
        return f"mock://{kind}/{query.replace(' ', '-')}"

    def download(self, url: str, dest: Path) -> Path:
        self.download_calls.append(url)
        from PIL import Image, ImageDraw

        from pipeline.rasters import COURIER_BOLD, load_font

        seed = int(hashlib.sha256(url.encode()).hexdigest()[:6], 16)
        dest.parent.mkdir(parents=True, exist_ok=True)
        label = url.rsplit("/", 1)[-1][:40]
        animated = "mock://gif/" in url
        font = load_font(self.settings, COURIER_BOLD, 28)

        def frame(i: int) -> Image.Image:
            img = Image.new("RGB", (720, 540),
                            ((seed % 80) + 40, 40, (seed % 60) + 60))
            d = ImageDraw.Draw(img)
            d.rectangle([12, 12, 707, 527], outline=(240, 240, 240), width=4)
            d.text((30, 250), label, font=font, fill=(240, 240, 240))
            if animated:
                # A bar that walks across the frame. Anything that samples two
                # frames of this and finds them identical has frozen the clip.
                x = 40 + i * (620 // max(MOCK_GIF_FRAMES - 1, 1))
                d.rectangle([x, 320, x + 60, 400], fill=(240, 240, 240))
            return img

        if animated:
            frames = [frame(i) for i in range(MOCK_GIF_FRAMES)]
            frames[0].save(dest, format="GIF", save_all=True,
                           append_images=frames[1:],
                           duration=MOCK_GIF_FRAME_MS, loop=0)
        else:
            frame(0).save(dest, format="PNG")  # dest may have a non-image suffix
        return dest


# ---------------------------------------------------------------------------
# Manager.
# ---------------------------------------------------------------------------


def animated_providers(settings: Settings) -> list:
    """The providers that can return something that MOVES, in chain order.

    Giphy and Tenor, and deliberately not imgflip: it is a library of flat
    meme templates and has nothing to answer with. These are the same clients
    the meme chain uses, configured the same way — `pipeline.broll` hangs the
    tail of its `[CLIP]` chain off them rather than adding a dependency,
    because Pexels is a STOCK library and stock will never have LeBron
    shooting a three.
    """
    if settings.mock_mode:
        return [MockMemeClient(settings)]
    return [GiphyClient(settings, "giphy"), TenorClient(settings, "tenor")]


def normalize_meme(src: Path, dest: Path) -> Path:
    """Any input image -> a still PNG (GIFs freeze on frame 0).

    THE FREEZE IS THE POINT here, and it is why `[CLIP]` does not come through
    this function: a frozen meme is drier and the freeze is the joke's timing,
    where a frozen illustration is a man stopped mid-jump.
    """
    from PIL import Image

    dest.parent.mkdir(parents=True, exist_ok=True)
    img = Image.open(src)
    if getattr(img, "is_animated", False):
        img.seek(0)
    img.convert("RGB").save(dest, format="PNG")
    return dest


class MemeManager:
    def __init__(
        self,
        settings: Settings,
        library: MemeLibrary | None = None,
        providers: list | None = None,
    ):
        self.settings = settings
        self.library = library or MemeLibrary(settings)
        if providers is not None:
            self.providers = providers
        elif settings.mock_mode:
            self.providers = [MockMemeClient(settings)]
        else:
            self.providers = [
                GiphyClient(settings, "giphy"),
                TenorClient(settings, "tenor"),
                ImgflipClient(settings, "imgflip"),
            ]

    def _cache_dir(self, key: str) -> Path:
        h = hashlib.sha256(f"meme|{key.lower()}".encode()).hexdigest()[:24]
        return self.settings.cache_dir / "memes" / h

    def resolve(self, key: str) -> MemeAsset:
        """Owned library -> cache -> fallback providers -> filler. Never
        raises for content reasons."""
        try:
            src = self.library.resolve(key)
            if src is not None:
                return MemeAsset(
                    key=key, path=library_still(self.settings, src),
                    source="library",
                    attribution=LIBRARY_ATTRIBUTION.format(stem=src.stem))

            cdir = self._cache_dir(key)
            norm = cdir / "normalized.png"
            meta = cdir / "meta.json"
            if norm.exists():
                attribution = ""
                source = "cache"
                if meta.exists():
                    m = json.loads(meta.read_text(encoding="utf-8"))
                    attribution = m.get("attribution", "")
                return MemeAsset(key=key, path=norm, source=source,
                                 attribution=attribution)

            query = key.replace("-", " ").replace("_", " ")
            for provider in self.providers:
                try:
                    url = provider.search(query)
                except (httpx.HTTPError, OSError) as e:
                    log.warning("meme provider %s failed (%s)", provider.name, e)
                    continue
                if not url:
                    continue
                raw = cdir / "raw.bin"
                provider.download(url, raw)
                normalize_meme(raw, norm)
                raw.unlink(missing_ok=True)
                attribution = f"meme via {provider.name} ({url})"
                cdir.mkdir(parents=True, exist_ok=True)
                meta.write_text(json.dumps({
                    "key": key, "provider": provider.name, "url": url,
                    "attribution": attribution,
                }, indent=2), encoding="utf-8")
                return MemeAsset(key=key, path=norm, source=provider.name,
                                 attribution=attribution)
        except Exception as e:  # the filler floor — mirror broll's guarantee
            log.warning("meme %r failed (%s) — filler", key, e)
        return self.filler(key)

    def filler(self, key: str) -> MemeAsset:
        from PIL import Image, ImageDraw

        from pipeline.rasters import COURIER_BOLD, load_font, role

        # The kit's ground, second ground and neutral ink, and keyed on the
        # ground so a card drawn for one kit is never served under another.
        ground = role(self.settings, "ground")
        path = (self.settings.cache_dir / "memes" / "filler"
                / ("meme_filler_%02x%02x%02x.png" % ground))
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            img = Image.new("RGB", (720, 540), ground)
            d = ImageDraw.Draw(img)
            d.rectangle([10, 10, 709, 529],
                        outline=role(self.settings, "second-ground"), width=3)
            font = load_font(self.settings, COURIER_BOLD, 26)
            text = "( meme unavailable )"
            d.text(((720 - d.textlength(text, font=font)) / 2, 270), text,
                   font=font, fill=role(self.settings, "neutral-data"),
                   anchor="lm")
            img.save(path)
        return MemeAsset(key=key, path=path, source="filler")


# ---------------------------------------------------------------------------
# The SHORT's one meme.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Situation:
    """A story the SHORT formats keep telling, and the tags that answer it.

    `tag` is the word a meme carries in the index to say "I am FOR this".
    `says` are phrases in the script's own fields that put a short in the
    situation, and `shows` the facts about it that do: which way the move went
    (`up`, `down`), the format (`earnings`, `macro`), a print above consensus
    (`hot`), a share count that grew (`dilution`). Where `also_says` or
    `also_shows` is set, one of those has to hold as well — "beat" alone is
    half of a beat that still sold off.

    `related` are tags the library ALREADY carries that answer the same story
    less exactly. A meme drawn for the situation outscores one that happens to
    fit it, which is what lets a new meme take over from the old ones the day
    it lands in the index, with nobody editing this table.
    """

    tag: str
    says: tuple[str, ...] = ()
    shows: tuple[str, ...] = ()
    also_says: tuple[str, ...] = ()
    also_shows: tuple[str, ...] = ()
    related: tuple[str, ...] = ()

    def holds(self, text: str, facts: "Collection[str]") -> bool:
        """Whether a script read as `text` and `facts` is in this situation."""
        if not (any(_says(text, p) for p in self.says)
                or any(f in facts for f in self.shows)):
            return False
        if not (self.also_says or self.also_shows):
            return True
        return (any(_says(text, p) for p in self.also_says)
                or any(f in facts for f in self.also_shows))


# THE STORIES, one row each: what the vertical formats keep hitting. The
# library was thin on every one of them when this was written, so the tags are
# also the list of memes worth making next, and the words to file them under.
SITUATIONS: tuple[Situation, ...] = (
    Situation(
        "beat-sold-off",
        says=("beat", "beats", "beat and raise", "topped estimates",
              "ahead of estimates", "ahead of the estimate"),
        also_says=("sold off", "sell off", "selloff", "fell", "slid", "sank",
                   "dropped", "did not matter", "didnt matter", "gave back",
                   "give back", "gives back", "shrugged", "priced in"),
        also_shows=("down",),
        related=("hiding-the-pain", "priced-in", "sell-the-news")),
    Situation(
        "guidance-cut",
        says=("guided below", "guides below", "guided lower", "guides lower",
              "guided down", "guides down", "cut guidance", "cuts guidance",
              "cut its guidance", "guidance cut", "lowered guidance",
              "lowers guidance", "lowered its guidance", "cut the guide",
              "cuts the guide", "lowered the guide", "cut its outlook",
              "cuts its outlook", "lowered its outlook", "lowers its outlook",
              "weak guidance", "soft guidance"),
        related=("hiding-the-pain", "reversal")),
    Situation(
        "hot-print",
        says=("cpi", "inflation", "pce", "ppi", "consumer prices",
              "price index"),
        also_says=("hot", "hotter", "above expected", "above expectations",
                   "above forecast", "higher than expected", "accelerated",
                   "accelerating", "reaccelerated", "re accelerated"),
        also_shows=("hot",),
        related=("inflation", "rate-pain", "fed", "powell")),
    Situation(
        "fed-day",
        says=("the fed", "fed chair", "fed funds", "fomc", "powell",
              "federal reserve", "rate decision", "rate cut", "rate cuts",
              "rate hike", "rate hikes", "basis points", "dot plot"),
        related=("fed", "powell", "rate-pain")),
    # "Diluted" is not here on its own: it is also the first word of
    # "diluted EPS", which is every earnings sheet and no dilution at all.
    Situation(
        "dilution",
        says=("dilution", "dilutive", "diluting", "got diluted",
              "been diluted", "being diluted", "share count up",
              "share count rose", "share count grew", "share count climbed",
              "more shares", "new shares", "share issuance", "issued shares",
              "issuing shares", "secondary offering", "stock offering",
              "equity raise", "at the market offering", "atm offering",
              "stock based comp", "stock based compensation"),
        shows=("dilution",)),
    Situation(
        "short-squeeze",
        says=("squeeze", "squeezed", "short interest", "of the float",
              "short sellers", "shorts covering", "short covering"),
        related=("vertical", "up-only", "chasing", "pump")),
    Situation(
        "press-release-pump",
        says=("press release", "partnership", "partners with", "announces",
              "announced", "announcement", "letter of intent",
              "memorandum of understanding", "pilot program",
              "collaboration", "strategic review"),
        also_says=("pump", "pumped", "soared", "soars", "jumped", "jumps",
                   "spiked", "ripped", "surged", "popped", "vertical"),
        also_shows=("up",),
        related=("pump", "vertical", "up-only", "bullish-signal",
                 "noise-or-signal")),
    Situation(
        "value-trap",
        says=("value trap", "is a trap", "its a trap", "looks like a trap",
              "cheap for a reason", "cheap only", "falling knife",
              "catching knives", "cheap on paper", "looks cheap",
              "optically cheap", "sliding stops", "keeps sliding",
              "still sliding"),
        related=("bagholder", "catching-knives", "averaging-down",
                 "buy-the-dip", "hiding-the-pain", "still-losing")),
)

# WHAT IS TRUE OF EVERY SHORT: which way it moved and which format it is. A
# point each and never enough alone — not every up day is a FOMO joke, and a
# meme that fits only the direction fits every other video that week too.
CONTEXTS: tuple[Situation, ...] = (
    Situation("rally", shows=("up",),
              related=("up-only", "vertical", "pump", "fomo", "wish-i-bought",
                       "chasing", "missed-it", "missed-the-rally",
                       "left-out", "envy")),
    Situation("selloff", shows=("down",),
              related=("crash", "drawdown", "loss", "red", "market-drop",
                       "wiped-out", "down-50", "down-99", "portfolio-halved",
                       "bagholder", "blown-up", "daily-loss", "capitulation",
                       "all-time-low", "loss-porn")),
    Situation("earnings", shows=("earnings",),
              related=("adjusted-earnings", "earnings-before", "non-gaap",
                       "ebitda", "add-backs")),
    Situation("macro", shows=("macro",),
              related=("fed", "powell", "inflation", "rate-pain", "tariffs",
                       "policy-risk", "geopolitics")),
)

# The points. A meme drawn FOR the story beats one that fits it, which beats a
# word in common; three is the floor, so one of the first two, or a phrase the
# script says in so many words plus anything else, is what it takes.
SITUATION_POINTS = 3     # the meme carries the situation's own tag
RELATED_POINTS = 2       # ... or a tag the library already files it under
CONTEXT_POINTS = 1       # the move's direction, the format
PHRASE_POINTS = 2        # a hyphenated tag the script says outright
WORD_POINTS = 1          # a one-word tag the script says
USE_WHEN_POINTS = 2      # at most, for words the script shares with "use when"
MEME_FLOOR = 3

# A JOKE IS REMEMBERED LONGER THAN A DRAWING. Plates rotate off the last three
# renders, which is one week of the short lane; the same meme two weeks running
# is a rerun somebody scrolling the channel page sees side by side. So memes
# look further back, and unlike the plates the rotation is a RULE: when every
# meme that fits was on screen recently the short gets none, because a repeated
# joke is worse than no joke and — unlike a missing plate — costs the render
# nothing.
MEME_ROTATION_WINDOW = 6

# THE SHAPE A MEME HAS TO BE TO READ IN A VERTICAL FRAME. It is fitted whole
# into a frames/ plate's window, which at 9:16 is about square, so a meme wider
# than two to one — a tweet screenshot, a chart strip — lands at under half the
# window's height, with its type at a size nobody reads in a second and a half.
# Square or 4:5 fills it.
SHORT_ASPECT = (0.5, 2.0)

# A share count this much higher in the last column than the first is dilution
# whatever the writer called it: a tenth more shares is a tenth less company.
SHARE_GROWTH = 0.10

# THE FIELDS IT READS: the ones the writer states the story in — the hook, the
# headline and what it means, the turn, the verdict and the call — plus the few
# that carry a situation outright. NOT `audio_script`: two hundred words of
# narration say "beat" and "the Fed" in passing, and a meme picked off a
# passing word is a meme about something the video is not about. NOT the row
# labels either: "Diluted EPS" is a metric's name, not a statement.
_READ_FIELDS = ("hook_text", "move_summary", "turn_line", "verdict",
                "cheap_or_trap", "conclusion", "guidance", "numbers_comment")

# Words too common to say anything about which meme fits.
_COMMON = frozenset("""
a about after again against all also an and any are as at be been before being
but by can could did do does down during each even every for from had has have
having here how if in into is it its just like made make more most much no nor
not now of off on once one only or other our out over own same should so some
such than that the their them then there these they this those through to too
two under until up very was we were what when where which while who why will
with would you your yet still get got new day week year years today
stock stocks share shares market markets price prices company portfolio
investor investors money someone everyone something nothing everything
""".split())

_FIGURE_RE = re.compile(r"([-+−]?)\$?(\d[\d,]*(?:\.\d+)?)\s*([kmbt]?)",
                        re.IGNORECASE)
_MAGNITUDE = {"": 1.0, "k": 1e3, "m": 1e6, "b": 1e9, "t": 1e12}


def _plain(text: str) -> str:
    """Lower case, apostrophes dropped, everything else not a word a space."""
    text = re.sub(r"['‘’`]", "", str(text or "").lower())
    return " ".join(re.sub(r"[^a-z0-9%]+", " ", text).split())


def _says(text: str, phrase: str) -> bool:
    """Whether padded plain `text` contains `phrase` as whole words."""
    want = _plain(phrase)
    return bool(want) and f" {want} " in text


def _stem(word: str) -> str:
    """The plural off, and nothing cleverer: "consumers" meets "consumer"."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _words(text: str) -> frozenset[str]:
    """The words of `text` that could say something about a meme."""
    return frozenset(_stem(w) for w in _plain(text).split()
                     if len(w) > 2 and w not in _COMMON)


def _figure(value) -> float | None:
    """The first figure written in `value`, magnitude applied, or None."""
    m = _FIGURE_RE.search(str(value or ""))
    if not m:
        return None
    try:
        n = float(m.group(2).replace(",", ""))
    except ValueError:
        return None
    n *= _MAGNITUDE.get(m.group(3).lower(), 1.0)
    return -n if m.group(1) in ("-", "−") else n


def _share_count_grew(rows) -> bool:
    """A row naming the share count, ending at least a tenth above its start."""
    for row in rows:
        if " share" not in f" {_plain(getattr(row, 'label', ''))}":
            continue
        vals = [v for v in (getattr(row, "values", None) or ())
                if str(v).strip()]
        if len(vals) < 2:
            continue
        first, last = _figure(vals[0]), _figure(vals[-1])
        if first and last and first > 0 and last >= first * (1 + SHARE_GROWTH):
            return True
    return False


@dataclass(frozen=True)
class Reading:
    """A script as the picker reads it: its words and the facts about it."""

    text: str                                   # padded plain text
    words: frozenset[str]
    facts: frozenset[str]
    situations: tuple[Situation, ...] = ()
    contexts: tuple[Situation, ...] = ()


def read_script(script, *, fmt: str = "short", direction: str = "") -> Reading:
    """Which situations a short is in, off its own fields and its format.

    `direction` is the move's — "up", "down" or "" — as the renderer reads it
    off `move_summary`, passed in rather than parsed twice. Duck-typed, so any
    object with the SHORT's field names reads.
    """
    parts = [str(getattr(script, f, "") or "") for f in _READ_FIELDS]
    for h in getattr(script, "headlines", None) or ():
        parts += [str(getattr(h, "text", "") or ""),
                  str(getattr(h, "meaning", "") or "")]
    for name in ("mechanism", "consequences"):
        parts += [str(x) for x in (getattr(script, name, None) or ())]
    joined = " ".join(p for p in parts if p)
    text = f" {_plain(joined)} "

    facts: set[str] = set()
    if direction in ("up", "down"):
        facts.add(direction)
    if fmt in ("earnings", "macro"):
        facts.add(fmt)
    # A PRINT ABOVE CONSENSUS IS HOT ONLY ON A MACRO PRINT. An earnings beat is
    # also a reported figure over an expected one, and calling it "hot" would
    # file every beat under inflation.
    if fmt == "macro":
        got = _figure(getattr(script, "reported", None))
        want = _figure(getattr(script, "expected", None))
        if got is not None and want is not None and got > want:
            facts.add("hot")
    if _share_count_grew(getattr(script, "numbers", None) or ()):
        facts.add("dilution")

    return Reading(
        text=text, words=_words(joined), facts=frozenset(facts),
        situations=tuple(s for s in SITUATIONS if s.holds(text, facts)),
        contexts=tuple(c for c in CONTEXTS if c.holds(text, facts)))


def _tags(entry: dict) -> set[str]:
    return {str(t).strip().lower().replace(" ", "-").replace("_", "-")
            for t in (entry.get("tags") or ()) if str(t).strip()}


def score_meme(entry: dict, reading: Reading) -> tuple[int, tuple[str, ...]]:
    """How well one index entry answers a script, and what it scored on.

    Tags first, then "use when": a tag is the index saying what a meme is for,
    and "use when" is the same thing in a sentence, so its words count for
    less and only up to a ceiling — a long sentence must not outvote a tag.
    """
    tags = _tags(entry)
    score, why = 0, []
    credited: set[str] = set()
    for sit in reading.situations:
        if sit.tag in tags:
            score += SITUATION_POINTS
            why.append(sit.tag)
            credited.add(sit.tag)
            continue
        hit = sorted(tags & set(sit.related))
        if hit:
            score += RELATED_POINTS
            why.append(f"{sit.tag} ({hit[0]})")
    for ctx in reading.contexts:
        if ctx.tag in tags or tags & set(ctx.related):
            score += CONTEXT_POINTS
            why.append(ctx.tag)
            credited.add(ctx.tag)
    said: set[str] = set()
    for tag in sorted(tags - credited):
        phrase = tag.replace("-", " ")
        if _says(reading.text, phrase):
            score += PHRASE_POINTS if "-" in tag else WORD_POINTS
            why.append(f'"{phrase}"')
            said |= _words(phrase)
    shared = sorted((_words(str(entry.get("use_when") or "")) & reading.words)
                    - said)
    if shared:
        score += min(len(shared), USE_WHEN_POINTS)
        why.append("use when: " + ", ".join(shared[:USE_WHEN_POINTS]))
    return score, tuple(why)


def _sits_in_a_vertical_frame(src: Path) -> bool:
    """Whether a meme's shape reads in a 9:16 frame's window. See SHORT_ASPECT."""
    from PIL import Image

    try:
        with Image.open(src) as im:
            w, h = im.size
    except (OSError, ValueError):
        return False
    return bool(w and h) and SHORT_ASPECT[0] <= w / h <= SHORT_ASPECT[1]


@dataclass(frozen=True)
class MemeChoice:
    """The one meme a short gets — or, with no key, why it gets none."""

    key: str = ""                       # the index stem
    path: Path | None = None            # the render-ready still
    file: str = ""                      # the library file it was made from
    score: int = 0
    matched: tuple[str, ...] = ()       # what it scored on
    why: str = ""
    candidates: tuple[str, ...] = field(default=(), compare=False)

    def __bool__(self) -> bool:
        return bool(self.key)


def choose_for_short(script, settings: Settings, *, fmt: str = "short",
                     direction: str = "", seed: str = "",
                     avoid: "Collection[str]" = (),
                     library: MemeLibrary | None = None) -> MemeChoice:
    """The meme this short gets, from the OWNED LIBRARY, or none.

    NEVER FETCHED. The LONG's chain falls back to the cache of fetched memes,
    then to Giphy, Tenor and imgflip, then to a filler card; a short stops at
    the library. A meme someone else drew, arriving unannounced in a
    mass-produced format, is a licence question nobody asked, and the filler
    card is a grey box with "meme unavailable" in it.

    DETERMINISTIC PER SCRIPT. The best score wins and `seed` — the script's
    content hash — breaks a tie, so the draft, the proof and the final of one
    video put the same meme on screen. `avoid` is what recent videos used (see
    `recent_memes`), and a meme in it is not picked however well it fits.
    """
    lib = library or MemeLibrary(settings)
    index = lib.index()
    if not index:
        return MemeChoice(why="the meme library is empty")
    reading = read_script(script, fmt=fmt, direction=direction)

    fits: list[tuple[int, str, Path, tuple[str, ...]]] = []
    for stem in sorted(index):
        entry = index.get(stem)
        # `"shorts": false` keeps a meme to the LONG: a screenshot of a whole
        # page is a joke in a two-second hold with a voice reading it, and
        # homework in a second and a half of a short.
        if not isinstance(entry, dict) or entry.get("shorts") is False:
            continue
        score, matched = score_meme(entry, reading)
        if score < MEME_FLOOR:
            continue
        src = lib._file_for(stem)
        if src is None or not _sits_in_a_vertical_frame(src):
            continue
        fits.append((score, stem, src, matched))
    if not fits:
        return MemeChoice(why=f"nothing in the library scored {MEME_FLOOR} or "
                              f"more for this script")

    recent = set(avoid)
    fresh = [f for f in fits if f[1] not in recent]
    if not fresh:
        return MemeChoice(
            why=(f"every meme that fits was on screen in a recent video "
                 f"({', '.join(f[1] for f in fits)})"),
            candidates=tuple(f[1] for f in fits))
    top = max(f[0] for f in fresh)
    score, stem, src, matched = random.Random(f"meme|{seed}").choice(
        [f for f in fresh if f[0] == top])
    return MemeChoice(
        key=stem, path=library_still(settings, src), file=src.name,
        score=score, matched=matched,
        why=f"scored {score} on {'; '.join(matched)}",
        candidates=tuple(f[1] for f in fits))


def memes_in_manifest(payload: dict) -> set[str]:
    """The library memes one render manifest says it put on screen.

    Both lanes, because a joke the long told on Monday is as stale in
    Wednesday's short: a SHORT records its meme as `meme.key`, and a LONG
    credits each library meme it froze on a segment's `attribution`.
    """
    out: set[str] = set()
    meme = payload.get("meme")
    if isinstance(meme, dict) and meme.get("key"):
        out.add(str(meme["key"]))
    for seg in payload.get("segments") or ():
        if not isinstance(seg, dict) or seg.get("kind") != "meme":
            continue
        m = _LIBRARY_ATTRIBUTION_RE.match(str(seg.get("attribution") or ""))
        if m:
            out.add(m.group("stem"))
    return out


def recent_memes(settings: Settings, *, window: int = MEME_ROTATION_WINDOW,
                 exclude: "Path | str | None" = None) -> set[str]:
    """Every library meme the last few videos put on screen.

    `reach.recent_plates` for jokes, off the same manifests and with the same
    forgiveness: an unreadable manifest, a pruned workspace, a render from
    before the field existed — each contributes nothing.

    COUNTED IN VIDEOS, NOT MANIFESTS. A proof and its final are two manifests
    in one workspace and one video on the channel; counted as two, they would
    halve how far back the window looks.

    `exclude` is the workspace being rendered and a renderer MUST pass it, for
    the reason it must pass it to `recent_plates`: without it the final reads
    the manifest its own proof wrote and steers off the meme the proof showed.
    """
    base = Path(settings.workspace_dir)
    if not base.is_dir():
        return set()
    skip = Path(exclude).resolve() if exclude else None
    videos: dict[Path, tuple[float, set[str]]] = {}
    for manifest in base.glob("*/*/*manifest*.json"):
        folder = manifest.parent.resolve()
        if skip is not None and folder == skip:
            continue
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            stamp = manifest.stat().st_mtime
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        # A RENDER's manifest, not the filings manifest that shares the folder
        # and the glob: a folder with no render in it is not a video.
        if not isinstance(payload, dict) or "plates_used" not in payload:
            continue
        when, used = videos.get(folder, (0.0, set()))
        videos[folder] = (max(when, stamp), used | memes_in_manifest(payload))
    newest = sorted(videos.values(), key=lambda v: v[0], reverse=True)
    out: set[str] = set()
    for _, used in newest[:window]:
        out |= used
    return out
