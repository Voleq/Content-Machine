"""The content engine — every visual tag resolves here (§5).

Grown out of the original Pexels-only b-roll fetcher into a multi-source
content manager. Resolution order per tag, all cached, all behind
interfaces, all with the same guarantee: a missing visual NEVER aborts a
render — every failure path degrades to a deterministic filler.

    [CLIP: q] / [BROLL: q]  vetted palette -> owned library -> cache ->
                            Pexels (rate-capped) -> filler clip
    [IMG: q] / [PRODUCT: q] real imagery: cache -> Wikimedia Commons
                            (free, attribution stored) -> the company's
                            own site (og:image, real mode) -> filler card
    [MEME: key]             owned meme library -> providers (pipeline.memes)
    [CHART: metric]         auto-generated channel-style chart (pipeline.chart)

`[SHOW FILING: file]` stays with the renderer (workspace screenshots,
normalized + generically labelled by pipeline.company_data).

Every ingested clip/image is normalized once and cached; renders only
ever touch normalized files. Attribution is stored beside every fetched
item and flows into the delivery credits.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from config import Settings
from pipeline.cost import SpendCapExceededError, SpendLedger
from pipeline.memes import MemeManager
from pipeline.render_common import RenderError, ffprobe_duration, run_ffmpeg

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# The vetted palette: key -> pre-tested Pexels video query. The preferred
# [CLIP] vocabulary; unknown payloads fall through as raw queries (warned
# at validation) and still land on the filler if the fetch fails.
# ---------------------------------------------------------------------------

PALETTE: dict[str, str] = {
    # disaster & decay
    "dumpster_fire": "dumpster fire burning night",
    "sinking_ship": "ship sinking storm sea",
    "house_of_cards": "house of cards collapsing",
    "dominoes_falling": "dominoes falling chain",
    "explosion_slowmo": "explosion slow motion",
    "demolition": "building demolition collapse",
    "car_crash_test": "car crash test dummy",
    "paper_shredder": "paper shredder document",
    "balloon_pop": "balloon popping slow motion",
    "melting_ice": "ice melting timelapse",
    "storm_clouds": "dark storm clouds timelapse",
    "graveyard": "old graveyard fog",
    "tumbleweed": "tumbleweed rolling desert",
    "maze": "hedge maze aerial",
    "tightrope_walker": "tightrope walker balancing",
    "life_raft": "life raft ocean rescue",
    "leaking_pipe": "water leaking pipe drip",
    "band_aid": "band aid plaster applying",
    # absurdity
    "clown": "clown makeup circus",
    "juggling": "juggling balls street performer",
    "magic_trick": "magician magic trick cards",
    "puppet": "puppet marionette strings",
    "hamster_wheel": "hamster running wheel",
    "treadmill_running": "man running treadmill gym",
    "casino_roulette": "casino roulette wheel spinning",
    "casino_chips": "casino chips stack poker",
    "rocket_launch": "rocket launch smoke",
    # money
    "printing_money": "money printing press dollars",
    "counting_cash": "hands counting cash dollars",
    "coins_falling": "gold coins falling slow motion",
    "piggy_bank": "piggy bank coins saving",
    "gold_bars": "gold bars bullion stack",
    "wallet_empty": "empty wallet no money",
    "monopoly_money": "board game money colorful",
    "atm_machine": "atm cash withdrawal machine",
    "bank_vault": "bank vault door opening",
    # corporate theater
    "confused_office_worker": "confused man office computer",
    "empty_office": "empty office desks abandoned",
    "boardroom_suits": "business meeting boardroom suits",
    "empty_promise_handshake": "business handshake deal suits",
    "powerpoint_presentation": "businessman presentation projector screen",
    "stock_exchange_floor": "stock exchange trading floor",
    "trading_screen": "stock market chart screen red",
    "calculator": "calculator accounting hands",
    "paperwork_stack": "stack of paperwork documents desk",
    "rubber_stamp": "rubber stamp approving document",
    # the (backhanded) praise lane
    "growing_plant": "plant growing timelapse soil",
    "watch_gears": "watch mechanism gears macro",
    "moat_castle": "medieval castle moat aerial",
    "assembly_line": "factory assembly line precision robots",
    "marathon_runner": "marathon runner endurance road",
    "yacht": "luxury yacht sailing sea",
    "private_jet": "private jet airplane tarmac",
}


def palette_keys() -> list[str]:
    return sorted(PALETTE.keys())


def content_cache_key(query: str, provider: str) -> str:
    """Cache by sha256(query + provider) — unchanged content, zero calls."""
    return hashlib.sha256(f"{query}|{provider}".encode()).hexdigest()[:24]


@dataclass
class Visual:
    """One render-ready visual, whatever chain produced it."""

    key: str
    kind: str            # clip | img | meme | chart | asset
    path: Path           # normalized, render-ready file
    is_video: bool
    source: str          # local | library | cache | pexels | wikimedia |
                         # company_site | giphy | tenor | imgflip | mock |
                         # generated | filler
    attribution: str = ""


# ---------------------------------------------------------------------------
# Pexels clients (real + mock behind the same shape) — the [CLIP] chain.
# ---------------------------------------------------------------------------


class PexelsError(Exception):
    pass


class RealPexelsClient:
    """Free-tier-polite client: min interval between calls + monthly cap,
    both enforced via SpendLedger / a state timestamp file."""

    def __init__(self, settings: Settings, ledger: SpendLedger):
        self.settings = settings
        self.ledger = ledger
        self._stamp = settings.state_dir / "pexels_last_call"

    def _respect_rate_limit(self) -> None:
        try:
            last = float(self._stamp.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            last = 0.0
        wait = self.settings.pexels_min_interval_s - (time.time() - last)
        if wait > 0:
            time.sleep(wait)
        self._stamp.parent.mkdir(parents=True, exist_ok=True)
        self._stamp.write_text(str(time.time()), encoding="utf-8")

    def search(self, query: str, per_page: int = 5) -> dict:
        if not self.settings.pexels_api_key:
            raise PexelsError("PEXELS_API_KEY is not set and MOCK_MODE is off")
        self.ledger.check_pexels_budget()
        self._respect_rate_limit()
        resp = httpx.get(
            f"{self.settings.pexels_base_url}/videos/search",
            params={"query": query, "per_page": per_page},
            headers={"Authorization": self.settings.pexels_api_key},
            timeout=60,
        )
        self.ledger.record_pexels_call()
        if resp.status_code == 429:
            raise PexelsError("Pexels rate limit hit (429)")
        if resp.status_code != 200:
            raise PexelsError(f"Pexels error {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    def download(self, url: str, dest: Path) -> Path:
        self.ledger.check_pexels_budget()
        self._respect_rate_limit()
        dest.parent.mkdir(parents=True, exist_ok=True)
        with httpx.stream("GET", url, timeout=300, follow_redirects=True) as r:
            if r.status_code != 200:
                raise PexelsError(f"download failed {r.status_code}")
            with open(dest, "wb") as f:
                for chunk in r.iter_bytes(1 << 16):
                    f.write(chunk)
        self.ledger.record_pexels_call()
        return dest


class MockPexelsClient:
    """Deterministic fixture-backed client: search reads fixture JSON;
    download GENERATES a deterministic clip locally, exercising the exact
    same normalize+cache path as production. Zero network."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.search_calls: list[str] = []
        self.download_calls: list[str] = []

    def _fixture_for(self, query: str) -> Path:
        fdir = self.settings.fixtures_dir / "pexels"
        for key, q in PALETTE.items():
            if q == query and (fdir / f"search_{key}.json").exists():
                return fdir / f"search_{key}.json"
        return fdir / "search_generic.json"

    def search(self, query: str, per_page: int = 5) -> dict:
        self.search_calls.append(query)
        data = json.loads(self._fixture_for(query).read_text(encoding="utf-8"))
        # thread the query into the mock links so download can label the tile
        for v in data.get("videos", []):
            for f in v.get("video_files", []):
                f["link"] = f"mock://clip/{query}"
        return data

    def download(self, url: str, dest: Path) -> Path:
        """Generate a self-documenting b-roll stand-in: a dark cinematic
        brand gradient + film grain + vignette with the subject labelled in
        Space Grotesk — never a test pattern, so mock renders read as
        intentional footage placeholders rather than broken."""
        self.download_calls.append(url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        subject = url.split("/clip/", 1)[-1] if "/clip/" in url else url.rsplit("/", 1)[-1]
        subject = re.sub(r"[^A-Za-z0-9 -]", " ", subject).strip()[:40] or "b-roll"
        seed = int(hashlib.sha256(url.encode()).hexdigest()[:6], 16)
        hue = seed % 360
        dur = self.settings.broll_max_clip_s
        body = str(self.settings.fonts_dir / "SpaceGrotesk-Bold.ttf")
        kick = str(self.settings.fonts_dir / "SpaceMono-Bold.ttf")
        vf = (
            f"hue=h={hue},noise=alls=14:allf=t,vignette=PI/5,"
            f"eq=brightness=0.0:saturation=0.75,"
            f"drawtext=fontfile='{kick}':text='B-ROLL':fontcolor=0x6b6b70:"
            f"fontsize=26:x=(w-text_w)/2:y=(h-text_h)/2-66,"
            f"drawtext=fontfile='{body}':text='{subject}':fontcolor=0xf2f2ef:"
            f"fontsize=46:x=(w-text_w)/2:y=(h-text_h)/2:box=1:"
            f"boxcolor=0x0a0a0b@0.5:boxborderw=24"
        )
        run_ffmpeg([
            "-f", "lavfi",
            "-i", (f"gradients=s=1280x720:c0=0x141a24:c1=0x1c3128:nb_colors=2:"
                   f"speed=0.01:d={dur:.1f}:r=30"),
            "-vf", vf,
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
            "-an", str(dest),
        ])
        return dest


# ---------------------------------------------------------------------------
# Image clients — the [IMG]/[PRODUCT] chain (real imagery of operations,
# products, facilities). Wikimedia Commons first (free, attribution kept),
# then the company's own site.
# ---------------------------------------------------------------------------


class WikimediaImageClient:
    """Commons search via the public API; polite UA, no key needed."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._stamp = settings.state_dir / "wikimedia_last_call"

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

    def search(self, query: str, limit: int = 5) -> list[dict]:
        """Returns [{url, attribution}] — free files with credit strings."""
        self._respect_interval()
        r = httpx.get(
            f"{self.settings.wikimedia_base_url}/w/api.php",
            params={
                "action": "query", "format": "json",
                "generator": "search", "gsrnamespace": 6,
                "gsrsearch": f"filetype:bitmap {query}", "gsrlimit": limit,
                "prop": "imageinfo", "iiprop": "url|extmetadata",
                "iiurlwidth": 1600,
            },
            headers={"User-Agent": "dennis-content-machine/1.0 (offline video pipeline)"},
            timeout=30,
        )
        if r.status_code != 200:
            log.warning("wikimedia %s for %r", r.status_code, query)
            return []
        pages = (r.json().get("query") or {}).get("pages") or {}
        results: list[dict] = []
        for page in pages.values():
            infos = page.get("imageinfo") or []
            if not infos:
                continue
            info = infos[0]
            url = info.get("thumburl") or info.get("url")
            if not url:
                continue
            meta = info.get("extmetadata") or {}
            artist = re.sub(r"<[^>]+>", "", (meta.get("Artist") or {}).get("value", "")).strip()
            license_ = (meta.get("LicenseShortName") or {}).get("value", "")
            title = page.get("title", "").removeprefix("File:")
            attribution = f'"{title}" by {artist or "unknown"}, {license_ or "see source"}, via Wikimedia Commons'
            results.append({"url": url, "attribution": attribution})
        return results

    def download(self, url: str, dest: Path) -> Path:
        self._respect_interval()
        dest.parent.mkdir(parents=True, exist_ok=True)
        with httpx.stream("GET", url, timeout=120, follow_redirects=True,
                          headers={"User-Agent": "dennis-content-machine/1.0"}) as r:
            if r.status_code != 200:
                raise httpx.HTTPStatusError(f"download failed {r.status_code}",
                                            request=r.request, response=r)
            with open(dest, "wb") as f:
                for chunk in r.iter_bytes(1 << 16):
                    f.write(chunk)
        return dest


class CompanySiteImageClient:
    """Best-effort og:image from the company's own site / IR pages —
    the company photographs its own operations better than stock does."""

    _OG_RE = re.compile(
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
        re.IGNORECASE,
    )

    def __init__(self, settings: Settings):
        self.settings = settings

    def search(self, query: str, website: str = "", limit: int = 5) -> list[dict]:
        if not website:
            return []
        try:
            r = httpx.get(website, timeout=20, follow_redirects=True,
                          headers={"User-Agent": "dennis-content-machine/1.0"})
            if r.status_code != 200:
                return []
            m = self._OG_RE.search(r.text)
            if not m:
                return []
            return [{"url": m.group(1),
                     "attribution": f"company website ({website})"}]
        except httpx.HTTPError as e:
            log.warning("company site %s failed (%s)", website, e)
            return []

    def download(self, url: str, dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with httpx.stream("GET", url, timeout=60, follow_redirects=True,
                          headers={"User-Agent": "dennis-content-machine/1.0"}) as r:
            if r.status_code != 200:
                raise httpx.HTTPStatusError(f"download failed {r.status_code}",
                                            request=r.request, response=r)
            with open(dest, "wb") as f:
                for chunk in r.iter_bytes(1 << 16):
                    f.write(chunk)
        return dest


class MockImageClient:
    """Fixture-backed search + deterministic generated download."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.search_calls: list[str] = []
        self.download_calls: list[str] = []

    def search(self, query: str, limit: int = 5) -> list[dict]:
        self.search_calls.append(query)
        fixture = self.settings.fixtures_dir / "wikimedia" / "search_generic.json"
        results = json.loads(fixture.read_text(encoding="utf-8"))["results"][:limit]
        # thread the real query into the mock urls so each distinct [IMG]
        # renders a distinct colored, labelled card (not one generic image)
        for i, r in enumerate(results):
            r["url"] = f"mock://img/{query}" + (f" {i}" if i else "")
        return results

    def download(self, url: str, dest: Path) -> Path:
        """On-brand imagery stand-in: a full-frame COLOURED card (subject
        seeds a distinct deep-tone gradient) with the subject labelled in
        Space Grotesk — so a MOCK long previews the real composition
        (full-frame media, held still), not text on black."""
        self.download_calls.append(url)
        import colorsys

        from PIL import Image, ImageDraw, ImageFont

        dest.parent.mkdir(parents=True, exist_ok=True)
        W, H = 1600, 900
        subject = url.split("/img/", 1)[-1] if "/img/" in url else url.rsplit("/", 1)[-1]
        subject = subject.rsplit(".", 1)[0].replace("_", " ").strip() or "imagery"
        seed = int(hashlib.sha256(url.encode()).hexdigest()[:8], 16)
        hue = (seed % 360) / 360.0
        top = tuple(int(c * 255) for c in colorsys.hsv_to_rgb(hue, 0.5, 0.62))
        bot = tuple(int(c * 255) for c in colorsys.hsv_to_rgb((hue + 0.08) % 1.0, 0.62, 0.3))
        img = Image.new("RGB", (W, H), bot)
        d = ImageDraw.Draw(img)
        for y in range(0, H, 2):  # vertical gradient
            t = y / H
            d.line([(0, y), (W, y)],
                   fill=tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)))
        d.rounded_rectangle([28, 28, W - 29, H - 29], radius=18,
                            outline=(242, 242, 239), width=2)
        fonts = self.settings.assets_dir / "fonts"
        try:
            kick = ImageFont.truetype(str(fonts / "SpaceMono-Bold.ttf"), 34)
            size = 72
            body = ImageFont.truetype(str(fonts / "SpaceGrotesk-Bold.ttf"), size)
            while size > 30 and d.textlength(subject, font=body) > W - 180:
                size -= 4
                body = ImageFont.truetype(str(fonts / "SpaceGrotesk-Bold.ttf"), size)
        except OSError:  # fallback if brand fonts absent
            kick = body = ImageFont.load_default()
        d.text((72, 72), "IMAGERY", font=kick, fill=(242, 242, 239))
        tw = d.textlength(subject, font=body)
        d.text(((W - tw) / 2, H / 2 - body.size / 2), subject, font=body,
               fill=(255, 255, 255), stroke_width=2, stroke_fill=(0, 0, 0))
        img.save(dest, format="PNG")
        return dest


# ---------------------------------------------------------------------------
# Normalization (one-time ingest -> render-ready files).
# ---------------------------------------------------------------------------


def normalize_clip(src: Path, dest: Path, settings: Settings,
                   resolution: tuple[int, int] | None = None) -> Path:
    """One-time ingest normalization: cover-crop to the target resolution
    (LONG 16:9 by default; pass short_resolution for 9:16 cutaways),
    project fps, duration cap, audio stripped."""
    W, H = resolution or settings.long_resolution
    dest.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg([
        "-i", str(src),
        "-t", f"{settings.broll_max_clip_s:.2f}",
        "-vf",
        f"scale={W}:{H}:force_original_aspect_ratio=increase,"
        f"crop={W}:{H},fps={settings.fps},setsar=1",
        "-an",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        str(dest),
    ])
    return dest


def normalize_image(src: Path, dest: Path, settings: Settings) -> Path:
    """Compose the image to FILL the LONG frame (§editing: media is the
    background). Real photos cover the frame edge-to-edge; logos and tall
    grabs are contained sharp over a blurred, brand-tinted cover of
    themselves — a designed full-frame shot, never a letterboxed black
    frame. The renderer then holds that WxH still — nothing drifts."""
    from pipeline.rasters import cover_fill_frame

    W, H = settings.long_resolution
    frame = cover_fill_frame(src, W, H)
    dest.parent.mkdir(parents=True, exist_ok=True)
    frame.save(dest, format="PNG")
    return dest


# ---------------------------------------------------------------------------
# The manager.
# ---------------------------------------------------------------------------


class ContentManager:
    def __init__(
        self,
        settings: Settings,
        ledger: SpendLedger | None = None,
        clip_client=None,
        image_client=None,
        site_client=None,
        meme_manager: MemeManager | None = None,
        library_dir: Path | None = None,
    ):
        self.settings = settings
        self.ledger = ledger or SpendLedger(settings)
        self.library_dir = library_dir or settings.assets_dir / "broll_library"
        if clip_client is not None:
            self.clip_client = clip_client
        elif settings.mock_mode:
            self.clip_client = MockPexelsClient(settings)
        else:
            self.clip_client = RealPexelsClient(settings, self.ledger)
        if image_client is not None:
            self.image_client = image_client
        elif settings.mock_mode:
            self.image_client = MockImageClient(settings)
        else:
            self.image_client = WikimediaImageClient(settings)
        self.site_client = site_client if site_client is not None else (
            None if settings.mock_mode else CompanySiteImageClient(settings)
        )
        self.memes = meme_manager or MemeManager(settings)

    # ------------------------------------------------------------- clips
    def resolve_clip(self, key: str, choice: int = 0, *,
                     portrait: bool = False) -> Visual:
        """Resolve a [CLIP]/[BROLL] key (palette preferred, raw query
        tolerated) to a normalized clip. Never raises for content reasons.

        `choice` picks the nth candidate (the Approve-flow "Swap clip"
        button re-resolves with choice+1). `portrait` normalizes to 9:16
        for SHORT cutaways (cached separately).
        """
        try:
            local = self._from_library(key, choice, portrait)
            if local:
                return local
            cached = self._clip_from_cache(key, choice, portrait)
            if cached:
                return cached
            return self._fetch_clip(key, choice, portrait)
        except SpendCapExceededError as e:
            log.warning("clip %r: %s — filler", key, e)
            return self.filler_clip(key)
        except (PexelsError, RenderError, httpx.HTTPError, OSError) as e:
            log.warning("clip %r failed (%s) — filler", key, e)
            return self.filler_clip(key)

    def _clip_query(self, key: str) -> str:
        # palette keys map to their pre-tested query; anything else is
        # treated as a raw query (validation already warned about it)
        return PALETTE.get(key, key.replace("_", " "))

    def _res(self, portrait: bool) -> tuple[int, int]:
        return self.settings.short_resolution if portrait else self.settings.long_resolution

    def _library_candidates(self, key: str) -> list[Path]:
        if not self.library_dir.is_dir():
            return []
        exact = sorted(self.library_dir.glob(f"{key}.*"))
        variants = sorted(self.library_dir.glob(f"{key}__*.*"))
        return [p for p in exact + variants
                if p.suffix.lower() in (".mp4", ".mov", ".mkv", ".webm")]

    def _from_library(self, key: str, choice: int, portrait: bool) -> Visual | None:
        candidates = self._library_candidates(key)
        if not candidates:
            return None
        src = candidates[min(choice, len(candidates) - 1)]
        suffix = "_p" if portrait else ""
        norm = self.settings.cache_dir / "broll" / "library" / f"{src.stem}{suffix}.mp4"
        if not norm.exists():
            normalize_clip(src, norm, self.settings, self._res(portrait))
        return Visual(key=key, kind="clip", path=norm, is_video=True,
                      source="local", attribution=f"owned library clip ({src.name})")

    def _clip_cache_dir(self, key: str) -> Path:
        return self.settings.cache_dir / "broll" / content_cache_key(self._clip_query(key), "pexels")

    def _clip_from_cache(self, key: str, choice: int, portrait: bool) -> Visual | None:
        cdir = self._clip_cache_dir(key)
        suffix = "_p" if portrait else ""
        norm = cdir / f"normalized_{choice}{suffix}.mp4"
        meta = cdir / f"meta_{choice}.json"
        if norm.exists():
            attribution = ""
            if meta.exists():
                attribution = json.loads(meta.read_text(encoding="utf-8")).get("attribution", "")
            return Visual(key=key, kind="clip", path=norm, is_video=True,
                          source="cache", attribution=attribution)
        return None

    def _fetch_clip(self, key: str, choice: int, portrait: bool) -> Visual:
        query = self._clip_query(key)
        data = self.clip_client.search(query)
        videos = data.get("videos") or []
        if not videos:
            log.warning("pexels: no results for %r — filler", query)
            return self.filler_clip(key)
        video = videos[min(choice, len(videos) - 1)]
        file_url = self._pick_file(video)
        if not file_url:
            return self.filler_clip(key)

        cdir = self._clip_cache_dir(key)
        suffix = "_p" if portrait else ""
        raw = cdir / f"raw_{choice}.mp4"
        norm = cdir / f"normalized_{choice}{suffix}.mp4"
        self.clip_client.download(file_url, raw)
        normalize_clip(raw, norm, self.settings, self._res(portrait))
        raw.unlink(missing_ok=True)

        user = video.get("user", {})
        attribution = f"Video by {user.get('name', 'unknown')} on Pexels ({video.get('url', '')})"
        (cdir / f"meta_{choice}.json").write_text(json.dumps({
            "key": key, "query": query, "provider": "pexels",
            "video_id": video.get("id"), "attribution": attribution,
        }, indent=2), encoding="utf-8")
        return Visual(key=key, kind="clip", path=norm, is_video=True,
                      source="pexels", attribution=attribution)

    @staticmethod
    def _pick_file(video: dict) -> str | None:
        files = video.get("video_files") or []
        if not files:
            return None

        def rank(f: dict) -> tuple:
            h = f.get("height") or 0
            fits = 0 if 720 <= h <= 1080 else 1  # prefer 720–1080p (bandwidth)
            return (fits, -(h or 0))

        return sorted(files, key=rank)[0].get("link")

    def filler_clip(self, key: str) -> Visual:
        """Deterministic generic static filler — the never-fail floor.

        On PAPER. This is production code, not a mock: it fires whenever a
        real clip cannot be fetched, and it was `#0e1117` — so the fallback
        for a failed b-roll lookup was a near-black hole in the middle of a
        light-theme video. The same defect the seven dark cards had.
        """
        W, H = self.settings.long_resolution
        path = self.settings.cache_dir / "broll" / "filler" / "static_filler.mp4"
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            run_ffmpeg([
                "-f", "lavfi",
                "-i", f"color=c=0xF2F2EF:size={W}x{H}:rate={self.settings.fps}:duration={self.settings.broll_max_clip_s:.1f}",
                # Grain and a whisper of vignette so it reads as paper stock
                # rather than a dropped frame.
                "-vf", "noise=alls=6:allf=t,vignette=PI/4.2",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
                "-an", str(path),
            ])
        return Visual(key=key, kind="clip", path=path, is_video=True, source="filler")

    # ------------------------------------------------------------ images
    def resolve_image(self, query: str, *, kind: str = "img",
                      website: str = "", choice: int = 0) -> Visual:
        """[IMG]/[PRODUCT]: cache -> Wikimedia Commons -> company site ->
        filler card. Attribution stored beside the cache entry."""
        try:
            cdir = self.settings.cache_dir / "images" / content_cache_key(query, "img")
            norm = cdir / f"normalized_{choice}.png"
            meta = cdir / f"meta_{choice}.json"
            if norm.exists():
                attribution = ""
                if meta.exists():
                    attribution = json.loads(meta.read_text(encoding="utf-8")).get("attribution", "")
                return Visual(key=query, kind=kind, path=norm, is_video=False,
                              source="cache", attribution=attribution)

            results = self.image_client.search(query)
            source = "wikimedia" if not self.settings.mock_mode else "mock"
            if not results and self.site_client is not None and website:
                results = self.site_client.search(query, website=website)
                source = "company_site"
            if not results:
                return self.filler_image(query, kind)

            pick = results[min(choice, len(results) - 1)]
            raw = cdir / f"raw_{choice}.bin"
            client = self.image_client if source != "company_site" else self.site_client
            client.download(pick["url"], raw)
            normalize_image(raw, norm, self.settings)
            raw.unlink(missing_ok=True)
            cdir.mkdir(parents=True, exist_ok=True)
            meta.write_text(json.dumps({
                "query": query, "provider": source, "url": pick["url"],
                "attribution": pick.get("attribution", ""),
            }, indent=2), encoding="utf-8")
            return Visual(key=query, kind=kind, path=norm, is_video=False,
                          source=source, attribution=pick.get("attribution", ""))
        except (httpx.HTTPError, OSError, KeyError, json.JSONDecodeError) as e:
            log.warning("image %r failed (%s) — filler", query, e)
            return self.filler_image(query, kind)

    def filler_image(self, query: str, kind: str = "img") -> Visual:
        from PIL import Image, ImageDraw

        path = self.settings.cache_dir / "images" / "filler" / "image_filler.png"
        if not path.exists():
            W, H = self.settings.long_resolution
            path.parent.mkdir(parents=True, exist_ok=True)
            from pipeline.rasters import BG, BORDER, MUTED

            img = Image.new("RGB", (W, H), BG)
            d = ImageDraw.Draw(img)
            d.rectangle([16, 16, W - 17, H - 17], outline=BORDER, width=3)
            d.text((W // 8, H // 2), "( imagery unavailable )", fill=MUTED)
            img.save(path)
        return Visual(key=query, kind=kind, path=path, is_video=False, source="filler")

    # ------------------------------------------------------------- memes
    def resolve_meme(self, key: str) -> Visual:
        asset = self.memes.resolve(key)
        return Visual(key=key, kind="meme", path=asset.path, is_video=False,
                      source=asset.source, attribution=asset.attribution)

    # ------------------------------------------------------------ charts
    def resolve_chart(self, metric: str, *, ticker: str,
                      company_data=None, style: str = "clean") -> Visual:
        """[CHART: metric] -> channel-style auto chart. `price` renders the
        branded price chart (clean or marker style) from the cached price
        feed; history metrics render multi-year bars. Cached by content
        hash (style included)."""
        try:
            if metric == "price":
                from pipeline.chart import (
                    render_marker_price_chart,
                    render_price_chart,
                )
                from pipeline.prices import get_price_history

                series = get_price_history(ticker, self.settings)
                marker = style == "marker"
                h = hashlib.sha256(
                    f"price|{style}|{ticker}|{series.dates[-1]}|{series.closes[-1]}".encode()
                ).hexdigest()[:20]
                out = self.settings.cache_dir / "charts" / f"{h}.png"
                if not out.exists():
                    W, H = self.settings.long_resolution
                    render = render_marker_price_chart if marker else render_price_chart
                    render(series, out, self.settings, size=(W, H))
                return Visual(key=metric, kind="chart", path=out, is_video=False,
                              source="generated", attribution="")

            years, values = [], []
            if company_data is not None:
                years = list(company_data.history_years)
                values = list(company_data.history_row(metric))
            if not values or all(v is None for v in values):
                log.warning("chart metric %r has no history — filler", metric)
                return self.filler_image(metric, "chart")
            from pipeline.chart import render_metric_chart

            label = metric.replace("_", " ").capitalize()
            h = hashlib.sha256(
                json.dumps([metric, years, values]).encode()
            ).hexdigest()[:20]
            out = self.settings.cache_dir / "charts" / f"{h}.png"
            if not out.exists():
                render_metric_chart(label, years, values, out, self.settings,
                                    size=self.settings.long_resolution)
            return Visual(key=metric, kind="chart", path=out, is_video=False,
                          source="generated", attribution="")
        except (OSError, RenderError) as e:
            log.warning("chart %r failed (%s) — filler", metric, e)
            return self.filler_image(metric, "chart")

    # ------------------------------------------------------------ assets
    def resolve_screengrab(self, slug: str) -> Visual:
        """[SCREENGRAB: slug] -> assets/custom/<slug>.* — an operator-
        supplied real screenshot or short screen-record (broker app, P&L,
        a Google search). Images are pad-fitted; clips are normalized.
        Degrades to the filler card if it vanished since validation."""
        custom = self.settings.assets_dir / "custom"
        hits = sorted(custom.glob(f"{slug}.*")) if custom.is_dir() else []
        clips = [p for p in hits if p.suffix.lower() in self._CLIP_SUFFIXES]
        images = [p for p in hits if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")]
        if clips:
            src = clips[0]
            stamp = hashlib.sha256(src.read_bytes()).hexdigest()[:20]
            norm = self.settings.cache_dir / "custom" / f"grab_{slug}_{stamp}.mp4"
            if not norm.exists():
                self._normalize_screengrab_clip(src, norm)
            return Visual(key=slug, kind="screengrab", path=norm, is_video=True,
                          source="local", attribution="")
        if images:
            src = images[0]
            stamp = hashlib.sha256(src.read_bytes()).hexdigest()[:20]
            norm = self.settings.cache_dir / "custom" / f"grab_{slug}_{stamp}.png"
            if not norm.exists():
                normalize_image(src, norm, self.settings)
            return Visual(key=slug, kind="screengrab", path=norm, is_video=False,
                          source="local", attribution="")
        log.warning("screengrab %r missing at render time — filler", slug)
        return self.filler_image(slug, "screengrab")

    def _normalize_screengrab_clip(self, src: Path, dest: Path) -> Path:
        """Pad-fit a screen-record onto the dark canvas (never cover-crop a
        phone capture), fps + duration cap, audio stripped."""
        W, H = self.settings.long_resolution
        dest.parent.mkdir(parents=True, exist_ok=True)
        run_ffmpeg([
            "-i", str(src),
            "-t", f"{self.settings.broll_max_clip_s:.2f}",
            "-vf",
            f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=0x0b0d12,"
            f"fps={self.settings.fps},setsar=1",
            "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            str(dest),
        ])
        return dest

    # ------------------------------------------------------------- doodles
    def resolve_visual(self, kind: str, value: str, *, ticker: str = "",
                       company_data=None, website: str = "",
                       choice: int = 0, style: str = "clean") -> Visual:
        """Uniform entry point for LONG segments (kind = the CueKind value)."""
        if kind == "clip":
            return self.resolve_clip(value, choice)
        if kind == "img":
            return self.resolve_image(value, website=website, choice=choice)
        if kind == "meme":
            return self.resolve_meme(value)
        if kind == "chart":
            return self.resolve_chart(value, ticker=ticker,
                                      company_data=company_data, style=style)
        if kind == "screengrab":
            return self.resolve_screengrab(value)
        raise ValueError(f"unknown visual kind {kind!r}")

    def plan(self, script, *, company_data=None,
             overrides: dict[str, int] | None = None) -> list[Visual]:
        """Resolve a whole LONG script's fetchable visuals for the report /
        contact sheet (filing screenshots are counted separately — they are
        workspace files, not fetches)."""
        from pipeline.models import TagType

        overrides = overrides or {}
        website = str(company_data.get("website") or "") if company_data is not None else ""
        out: list[Visual] = []
        seen: set[tuple[str, str]] = set()
        for e in script.events:
            if e.type in (TagType.CLIP, TagType.BROLL):
                kind = "clip"
            elif e.type in (TagType.IMG, TagType.PRODUCT):
                kind = "img"
            elif e.type is TagType.MEME:
                kind = "meme"
            elif e.type is TagType.CHART:
                kind = "chart"
            elif e.type is TagType.SCREENGRAB:
                kind = "screengrab"
            else:
                continue
            style = e.style or "clean"
            if (kind, e.payload + f":{style}") in seen:
                continue
            seen.add((kind, e.payload + f":{style}"))
            out.append(self.resolve_visual(
                kind, e.payload, ticker=script.ticker,
                company_data=company_data, website=website,
                choice=overrides.get(e.payload, 0), style=style,
            ))
        return out

    # -------------------------------------------------- approval-flow bits
    def alternates_count(self, key: str) -> int:
        """How many swap choices exist for a clip key (library + provider)."""
        n = len(self._library_candidates(key))
        try:
            n += len((self.clip_client.search(self._clip_query(key)) or {}).get("videos", []))
        except Exception:
            pass
        return max(n, 1)

    def thumbnail(self, visual: Visual, dest: Path) -> Path:
        """Thumbnail for the approval contact sheet (clip first frame or a
        resized copy of a still)."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        if visual.is_video:
            run_ffmpeg(["-i", str(visual.path), "-frames:v", "1",
                        "-vf", "scale=320:180", str(dest)])
        else:
            from PIL import Image

            img = Image.open(visual.path).convert("RGB")
            img.thumbnail((320, 180), Image.LANCZOS)
            canvas = Image.new("RGB", (320, 180), (14, 17, 23))
            canvas.paste(img, ((320 - img.width) // 2, (180 - img.height) // 2))
            canvas.save(dest)
        return dest
