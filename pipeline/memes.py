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

Everything used as a freeze-frame is normalized to a still PNG on ingest
(GIFs contribute their first frame) and cached.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

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


# ---------------------------------------------------------------------------
# Fallback providers (real + mock behind one shape).
# ---------------------------------------------------------------------------


class MemeProvider(Protocol):
    name: str
    def search(self, query: str) -> str | None: ...
    def download(self, url: str, dest: Path) -> Path: ...


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

    def search(self, query: str) -> str | None:
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
        for item in r.json().get("data", []):
            images = item.get("images", {})
            url = (images.get("downsized_still") or images.get("original_still") or {}).get("url")
            if url:
                return url
        return None


class TenorClient(_PoliteHttp):
    name = "tenor"

    def search(self, query: str) -> str | None:
        if not self.settings.tenor_api_key:
            return None
        self._respect_interval()
        r = httpx.get(
            f"{self.settings.tenor_base_url}/v2/search",
            params={"key": self.settings.tenor_api_key, "q": query,
                    "limit": 3, "media_filter": "png_transparent,gifpreview"},
            timeout=30,
        )
        if r.status_code != 200:
            log.warning("tenor %s for %r", r.status_code, query)
            return None
        for item in r.json().get("results", []):
            formats = item.get("media_formats", {})
            for fmt in ("png_transparent", "gifpreview", "gif"):
                url = (formats.get(fmt) or {}).get("url")
                if url:
                    return url
        return None


class ImgflipClient(_PoliteHttp):
    name = "imgflip"

    def search(self, query: str) -> str | None:
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


class MockMemeClient:
    """Deterministic offline fallback provider used in MOCK_MODE: search
    yields a mock:// URL; download GENERATES a captioned placeholder so
    the exact cache/normalize path is exercised with zero network."""

    name = "mock"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.search_calls: list[str] = []
        self.download_calls: list[str] = []

    def search(self, query: str) -> str | None:
        self.search_calls.append(query)
        return f"mock://meme/{query.replace(' ', '-')}"

    def download(self, url: str, dest: Path) -> Path:
        self.download_calls.append(url)
        from PIL import Image, ImageDraw

        seed = int(hashlib.sha256(url.encode()).hexdigest()[:6], 16)
        dest.parent.mkdir(parents=True, exist_ok=True)
        img = Image.new("RGB", (720, 540), ((seed % 80) + 40, 40, (seed % 60) + 60))
        d = ImageDraw.Draw(img)
        d.rectangle([12, 12, 707, 527], outline=(240, 240, 240), width=4)
        d.text((30, 250), url.rsplit("/", 1)[-1][:40], fill=(240, 240, 240))
        img.save(dest, format="PNG")  # dest may have a non-image suffix
        return dest


# ---------------------------------------------------------------------------
# Manager.
# ---------------------------------------------------------------------------


def normalize_meme(src: Path, dest: Path) -> Path:
    """Any input image -> a still PNG (GIFs freeze on frame 0)."""
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
                stem = src.stem
                norm = self.settings.cache_dir / "memes" / "library" / f"{stem}.png"
                if not norm.exists():
                    normalize_meme(src, norm)
                return MemeAsset(key=key, path=norm, source="library",
                                 attribution=f"owned meme library ({stem})")

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

        path = self.settings.cache_dir / "memes" / "filler" / "meme_filler.png"
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            img = Image.new("RGB", (720, 540), (24, 26, 32))
            d = ImageDraw.Draw(img)
            d.rectangle([10, 10, 709, 529], outline=(120, 126, 138), width=3)
            d.text((40, 250), "( meme unavailable )", fill=(170, 176, 188))
            img.save(path)
        return MemeAsset(key=key, path=path, source="filler")
