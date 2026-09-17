"""The content engine — every visual tag resolves here (§5).

Grown out of the original Pexels-only b-roll fetcher into a multi-source
content manager. Resolution order per tag, all cached, all behind
interfaces, all with the same guarantee: a missing visual NEVER aborts a
render — every failure path degrades to a deterministic filler.

    [CLIP: q] / [BROLL: q]  vetted palette -> owned library -> cache ->
                            Pexels (rate-capped) -> Giphy -> Tenor ->
                            filler clip. IT MOVES: an animated source
                            normalises to a short looping mp4, never a
                            freeze-frame
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
from pipeline.memes import MemeManager, animated_providers
from pipeline.render_common import RenderError, ffprobe_duration, run_ffmpeg

log = logging.getLogger(__name__)


def _compact(value: float) -> str:
    """`400000000` -> `400M`.

    Every figure slot in the kit declares a `maxChars`, and it is a HARD limit:
    over it the line collides with rules drawn in ink. A raw `{:,.0f}` on a
    revenue figure is eleven characters against a seven-character axis label,
    which is how a chart came out with every gridline overset.
    """
    n = float(value)
    for cut, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(n) >= cut:
            scaled = n / cut
            return (f"{scaled:.0f}{suffix}" if abs(scaled) >= 10
                    else f"{scaled:.1f}{suffix}".replace(".0", ""))
    return f"{n:,.0f}"

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
    # Whether this clip is meant to REPEAT to fill its beat rather than hold
    # its last frame. A gif is two seconds long and a hold may be four; a
    # looping source that freezes for the back half is the same failure as a
    # frozen gif, arriving later.
    loops: bool = False


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
        """One API call, counted once, at the point of dispatch.

        Counting after the response returned meant a call that 429'd or
        timed out was never counted — the exact calls the quota is there to
        bound. And `check_pexels_budget()` runs before the request, so a
        count recorded after it was always evaluated one call stale.
        """
        if not self.settings.pexels_api_key:
            raise PexelsError("PEXELS_API_KEY is not set and MOCK_MODE is off")
        self.ledger.check_pexels_budget()
        self._respect_rate_limit()
        # Dispatch is the billable event. Whatever comes back — 200, 429, a
        # dropped connection — the quota was spent the moment this left.
        self.ledger.record_pexels_call()
        resp = httpx.get(
            f"{self.settings.pexels_base_url}/videos/search",
            params={"query": query, "per_page": per_page},
            headers={"Authorization": self.settings.pexels_api_key},
            timeout=60,
        )
        if resp.status_code == 429:
            raise PexelsError("Pexels rate limit hit (429)")
        if resp.status_code != 200:
            raise PexelsError(f"Pexels error {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    def download(self, url: str, dest: Path) -> Path:
        """A CDN fetch. NOT an API call, and therefore not counted (A3).

        This used to `record_pexels_call()` too, so one clip cost two units
        against `PEXELS_MONTHLY_CALL_CAP` and the cap was effectively
        halved. It was wrong in principle as well as in arithmetic: the
        video file comes off a CDN, the quota is on the API, and the two are
        not the same resource. The rate limit still applies — politeness to
        the host is a separate question from the quota.
        """
        self._respect_rate_limit()
        dest.parent.mkdir(parents=True, exist_ok=True)
        with httpx.stream("GET", url, timeout=300, follow_redirects=True) as r:
            if r.status_code != 200:
                raise PexelsError(f"download failed {r.status_code}")
            with open(dest, "wb") as f:
                for chunk in r.iter_bytes(1 << 16):
                    f.write(chunk)
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
    from pipeline.rasters import role

    frame = cover_fill_frame(src, W, H, ground=role(settings, "ground"),
                             line=role(settings, "structure"))
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
        gif_clients: list | None = None,
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
        # The tail of the [CLIP] chain. Same clients the meme chain uses,
        # asked for the moving rendition instead of the still one.
        self.gif_clients = (gif_clients if gif_clients is not None
                            else animated_providers(settings))

    # ------------------------------------------------------------- clips
    def resolve_clip(self, key: str, choice: int = 0, *,
                     portrait: bool = False) -> Visual:
        """Resolve a [CLIP]/[BROLL] key (palette preferred, raw query
        tolerated) to a normalized clip. Never raises for content reasons.

        owned library -> cache -> Pexels -> Giphy -> Tenor -> filler.

        THE GIF PROVIDERS ARE WHY A SPECIFIC ILLUSTRATION CAN LAND. Pexels is
        a stock library: it has "basketball court" and it will never have
        LeBron shooting a three, a film moment, or any of the culturally
        specific things a `[CLIP]` written to PROVE a claim reaches for. Every
        one of those used to search, miss, log `pexels: no results` and draw a
        filler card, silently. Owned-library-first stays first, for the
        reason it always was — see `_fetch_gif_clip`.

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
            fetched = self._fetch_clip(key, choice, portrait)
            if fetched is not None:
                return fetched
        except SpendCapExceededError as e:
            # The Pexels cap is Pexels' alone — the gif providers are free and
            # are the point of the fallback, so a spent cap falls through to
            # them rather than straight to a filler card.
            log.info("clip %r: %s — trying the gif providers", key, e)
        except (PexelsError, RenderError, httpx.HTTPError, OSError) as e:
            log.warning("clip %r: pexels failed (%s)", key, e)
        try:
            gif = self._fetch_gif_clip(key, choice, portrait)
            if gif is not None:
                return gif
        except (RenderError, httpx.HTTPError, OSError) as e:
            log.warning("clip %r: gif providers failed (%s)", key, e)
        log.warning("clip %r resolved to nothing — filler", key)
        return self.filler_clip(key)

    def _clip_query(self, key: str) -> str:
        """The stock-search query for a clip key.

        A PALETTE key maps to its pre-tested query and stops there — the 53
        entries are hand-curated, `dumpster_fire` is
        `"dumpster fire burning night"` rather than `"dumpster fire"`, and
        rewriting one would be undoing work somebody already did (H4).

        Anything else is the writer going off-palette, which the prompt
        discourages and `validate_*_script` already warns about. It is a
        minority of visuals and precisely the minority that misses on stock
        footage and falls through to Giphy/Tenor — the most legally exposed
        surface in the pipeline (H3). So a free-text subject is rewritten
        into stock-searchable terms first: "a plateau in a costume" is not a
        stock query, "flat desert mesa landscape wide" is.
        """
        if key in PALETTE:
            return PALETTE[key]
        raw = key.replace("_", " ")
        return self._stock_query(raw)

    def _stock_query(self, subject: str) -> str:
        """`subject` rewritten for a stock library, or `subject` unchanged.

        Cached on the subject text, beside the clip cache: the same subject
        is rewritten once, ever, rather than once per off-palette visual per
        render. Degrades to the raw text on every failure path — this is a
        query, not a fact, and a worse query is much cheaper than a stalled
        plan.
        """
        if not self.settings.broll_rewrite_offpalette or not subject.strip():
            return subject
        cache = self.settings.cache_dir / "broll" / "queries.json"
        try:
            store = json.loads(cache.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            store = {}
        if subject in store:
            return str(store[subject]) or subject

        from pipeline.llm import chat

        out = chat(
            subject,
            self.settings,
            system=(
                "You turn a director's free-text visual note into a search "
                "query for a stock-footage library. Reply with the query "
                "ONLY: three to six concrete, literal, photographable nouns "
                "and adjectives, no punctuation, no quotes, no explanation. "
                "Drop metaphor and keep what a camera could actually see — "
                '"a plateau in a costume" becomes "flat desert mesa '
                'landscape wide". Do not think out loud.'),
            purpose="broll query",
        )
        query = (str(out or "").strip().splitlines() or [""])[0].strip(' "\'')
        # A rewrite that came back long, empty, or with punctuation in it is
        # a model answering a different question. The raw text is the floor.
        if not query or len(query) > 120 or any(c in query for c in ".!?:;"):
            if out:
                log.info("broll query rewrite for %r looked wrong (%r) — "
                         "using the raw subject", subject, out)
            query = subject
        store[subject] = query
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(store, indent=2), encoding="utf-8")
        except OSError as e:  # advisory — a cache miss costs a call, not a run
            log.warning("could not cache the broll query rewrite: %s", e)
        return query

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

    # Each fetch FAMILY caches under its own key, in chain order. One dir per
    # family rather than one per key, so adding the gif chain did not
    # invalidate a warm Pexels cache — and re-warming that one costs calls
    # against a monthly cap, not just time.
    _CLIP_CACHE_FAMILIES = ("pexels", "gif")

    def _clip_cache_dir(self, key: str, family: str = "pexels") -> Path:
        return (self.settings.cache_dir / "broll"
                / content_cache_key(self._clip_query(key), family))

    def _clip_from_cache(self, key: str, choice: int, portrait: bool) -> Visual | None:
        suffix = "_p" if portrait else ""
        for family in self._CLIP_CACHE_FAMILIES:
            cdir = self._clip_cache_dir(key, family)
            norm = cdir / f"normalized_{choice}{suffix}.mp4"
            meta = cdir / f"meta_{choice}.json"
            if not norm.exists():
                continue
            attribution, loops = "", False
            if meta.exists():
                m = json.loads(meta.read_text(encoding="utf-8"))
                attribution = m.get("attribution", "")
                # A gif that loops has to keep looping out of the cache, or
                # the second render of the same script freezes where the first
                # one moved.
                loops = bool(m.get("loops", False))
            return Visual(key=key, kind="clip", path=norm, is_video=True,
                          source="cache", attribution=attribution, loops=loops)
        return None

    def _fetch_clip(self, key: str, choice: int, portrait: bool) -> Visual | None:
        """Pexels. `None` means "no result" — the caller carries on down the
        chain, which is the whole reason this no longer returns a filler."""
        query = self._clip_query(key)
        data = self.clip_client.search(query)
        videos = data.get("videos") or []
        if not videos:
            log.info("pexels: no results for %r", query)
            return None
        video = videos[min(choice, len(videos) - 1)]
        file_url = self._pick_file(video)
        if not file_url:
            return None

        cdir = self._clip_cache_dir(key)
        suffix = "_p" if portrait else ""
        # Both names carry the orientation (H1). The normalised output always
        # did; the raw download did not, so two renders of the same key at
        # different orientations wrote the same raw path and could read each
        # other's half-written bytes. Latent at MAX_CONCURRENT_RENDERS=1 and
        # a real corruption the moment anyone raises it.
        raw = cdir / f"raw_{choice}{suffix}.mp4"
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

    def _fetch_gif_clip(self, key: str, choice: int, portrait: bool) -> Visual | None:
        """Giphy, then Tenor — asked for the MOVING rendition.

        Whatever comes back goes through `normalize_clip`, so it arrives in
        the same shape Pexels footage does: a short mp4 at the project's
        resolution and fps, audio stripped, capped in length. The renderer
        does not need to know which chain produced it and plays it inside the
        same frames/ plate either way.

        WORTH DECIDING DELIBERATELY, and not a legal opinion: Giphy and Tenor
        content is user-uploaded and frequently copyrighted — sports
        highlights and film clips especially, which is exactly what a specific
        illustration reaches for. That material has been in this pipeline for
        memes at one or two per video; illustration will reach it more often
        and more deliberately, because that is what it is for. The mitigation
        is the one already built and it is the reason owned-library-first is
        first: this only fires on a miss, so the more the owned library
        covers, the less this matters.
        """
        query = self._clip_query(key)
        cdir = self._clip_cache_dir(key, "gif")
        suffix = "_p" if portrait else ""
        for provider in self.gif_clients:
            # One provider failing is the next one's turn, not the end of the
            # chain — a Giphy timeout that took Tenor down with it would be a
            # filler card drawn for a reason that had nothing to do with the
            # illustration. So the whole fetch is inside the loop's guard, not
            # just the search.
            try:
                url = provider.search(query, animated=True)
                if not url:
                    continue
                raw = cdir / f"raw_{choice}.bin"
                provider.download(url, raw)
                norm = cdir / f"normalized_{choice}{suffix}.mp4"
                normalize_clip(raw, norm, self.settings, self._res(portrait))
                raw.unlink(missing_ok=True)
            except (RenderError, httpx.HTTPError, OSError) as e:
                log.warning("gif provider %s failed for %r (%s)",
                            provider.name, query, e)
                continue
            attribution = f"clip via {provider.name} ({url})"
            cdir.mkdir(parents=True, exist_ok=True)
            (cdir / f"meta_{choice}.json").write_text(json.dumps({
                "key": key, "query": query, "provider": provider.name,
                "url": url, "attribution": attribution, "loops": True,
            }, indent=2), encoding="utf-8")
            return Visual(key=key, kind="clip", path=norm, is_video=True,
                          source=provider.name, attribution=attribution,
                          loops=True)
        return None

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
            # The directory has to exist BEFORE anything is written into it
            # (H2). It used to be created after the download, the normalise
            # and the unlink had all already used it — which made the whole
            # image chain depend on whichever download client happened to
            # create parents, and the failure mode was a silent fall-back to
            # a filler card.
            cdir.mkdir(parents=True, exist_ok=True)
            raw = cdir / f"raw_{choice}.bin"
            client = self.image_client if source != "company_site" else self.site_client
            client.download(pick["url"], raw)
            normalize_image(raw, norm, self.settings)
            raw.unlink(missing_ok=True)
            meta.write_text(json.dumps({
                "query": query, "provider": source, "url": pick["url"],
                "attribution": pick.get("attribution", ""),
            }, indent=2), encoding="utf-8")
            return Visual(key=query, kind=kind, path=norm, is_video=False,
                          source=source, attribution=pick.get("attribution", ""))
        except (httpx.HTTPError, OSError, KeyError, json.JSONDecodeError) as e:
            log.warning("image %r failed (%s) — filler", query, e)
            return self.filler_image(query, kind)

    @staticmethod
    def _compact_number(value: float) -> str:
        return _compact(value)

    def filler_image(self, query: str, kind: str = "img") -> Visual:
        from PIL import Image, ImageDraw

        path = self.settings.cache_dir / "images" / "filler" / "image_filler.png"
        if not path.exists():
            W, H = self.settings.long_resolution
            path.parent.mkdir(parents=True, exist_ok=True)
            from pipeline.rasters import role

            img = Image.new("RGB", (W, H), role(self.settings, "ground"))
            d = ImageDraw.Draw(img)
            d.rectangle([16, 16, W - 17, H - 17],
                        outline=role(self.settings, "second-ground"), width=3)
            d.text((W // 8, H // 2), "( imagery unavailable )",
                   fill=role(self.settings, "neutral-data"))
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
                from pipeline.chart import render_price_plate
                from pipeline.plates import load_plates
                from pipeline.prices import get_price_history

                # There is one price chart now, not a clean one and a "marker"
                # one. The marker variant existed because the branded card was
                # too clean to sit beside hand-drawn work; the plate IS
                # hand-drawn, so `style` no longer selects a second look.
                series = get_price_history(ticker, self.settings)
                h = hashlib.sha256(
                    f"price|{ticker}|{series.dates[-1]}|{series.closes[-1]}".encode()
                ).hexdigest()[:20]
                out = self.settings.cache_dir / "charts" / f"{h}.png"
                if not out.exists():
                    out.parent.mkdir(parents=True, exist_ok=True)
                    W, H = self.settings.long_resolution
                    reg = load_plates(self.settings.assets_dir)
                    tmp = out.with_suffix(".plate.png")
                    render_price_plate(reg, series, tmp, self.settings,
                                       aspect="9x16" if H > W else "16x9",
                                       seed=f"price|{ticker}")
                    from PIL import Image

                    Image.open(tmp).convert("RGB").resize((W, H)).save(out)
                    tmp.unlink(missing_ok=True)
                return Visual(key=metric, kind="chart", path=out, is_video=False,
                              source="generated", attribution="")

            years, values = [], []
            if company_data is not None:
                years = list(company_data.history_years)
                values = list(company_data.history_row(metric))
            if not values or all(v is None for v in values):
                log.warning("chart metric %r has no history — filler", metric)
                return self.filler_image(metric, "chart")
            from pipeline.chart import render_series
            from pipeline.plates import PERIOD_COUNT, load_plates

            # SIX PERIODS. Four fiscal years, the last full year, LTM. A shorter
            # history is padded at the FRONT with empty periods rather than
            # squeezed into fewer columns: the plate is authored six wide, and
            # an empty cell means NO DATA, which is information — a missing
            # column is a lie about which year each figure belongs to.
            years = ([""] * max(PERIOD_COUNT - len(years), 0) + years)[-PERIOD_COUNT:]
            values = ([None] * max(PERIOD_COUNT - len(values), 0)
                      + list(values))[-PERIOD_COUNT:]

            label = metric.replace("_", " ").capitalize()
            h = hashlib.sha256(
                json.dumps([metric, years, [str(v) for v in values]]).encode()
            ).hexdigest()[:20]
            out = self.settings.cache_dir / "charts" / f"{h}.png"
            if not out.exists():
                out.parent.mkdir(parents=True, exist_ok=True)
                reg = load_plates(self.settings.assets_dir)
                aspect = ("9x16" if self.settings.long_resolution[0]
                          < self.settings.long_resolution[1] else "16x9")
                plate = reg.require(reg.aspect_key("charts/line-6y", aspect))
                # The axis labels ARE the scale, so they are written from the
                # same numbers the path is drawn from. Five gridlines, evenly
                # spaced across the series' own range.
                present = [float(v) for v in values if v is not None]
                lo, hi = (min(present), max(present)) if present else (0.0, 1.0)
                slot_values = {"unit": label}
                for i, y in enumerate(years, start=1):
                    slot_values[f"head-{i}"] = str(y)
                for i in range(5):
                    slot_values[f"y-{i + 1}"] = _compact(lo + (hi - lo) * i / 4)
                for i, v in enumerate(values, start=1):
                    if v is not None:
                        slot_values[f"value-{i}"] = _compact(float(v))
                img = render_series(reg, plate,
                                    [None if v is None else float(v) for v in values],
                                    self.settings, slot_values=slot_values,
                                    seed=f"{metric}|{h}")
                img.convert("RGB").resize(
                    tuple(self.settings.long_resolution)).save(out)
            return Visual(key=metric, kind="chart", path=out, is_video=False,
                          source="generated", attribution="")
        except (OSError, RenderError) as e:
            log.warning("chart %r failed (%s) — filler", metric, e)
            return self.filler_image(metric, "chart")

    # ------------------------------------------------------------ assets
    # Video containers an operator capture may arrive in. A screen-record is
    # normally .mp4 or .mov; the other two turn up from screen tools.
    _CLIP_SUFFIXES = (".mp4", ".mov", ".mkv", ".webm")

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
        # An override is keyed on (TAG, OCCURRENCE INDEX) — `CLIP:3` — not on
        # the payload text (G5). The prompt encourages reusing palette keys,
        # so a payload-keyed override swapped every beat that shared one, and
        # could not tell a `[CLIP]` from an `[IMG]` carrying the same subject.
        # `swap_index` counts the swappable tags in script order, which is
        # exactly what the swap menu numbers its buttons by.
        swap_index = -1
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
            if e.type in (TagType.CLIP, TagType.BROLL, TagType.IMG,
                          TagType.PRODUCT, TagType.MEME):
                swap_index += 1
            slot = f"{e.type.value}:{swap_index}"
            choice = overrides.get(slot)
            if choice is None:
                # Overrides written before the slot keys existed. Honouring
                # them keeps a workspace mid-flow working across the change;
                # the next swap rewrites the key.
                choice = overrides.get(e.payload, 0)
            style = e.style or "clean"
            # De-duplication is on the RESOLVED identity, so two occurrences
            # of one payload with different takes are two entries.
            ident = (kind, f"{e.payload}:{style}:{choice}")
            if ident in seen:
                continue
            seen.add(ident)
            out.append(self.resolve_visual(
                kind, e.payload, ticker=script.ticker,
                company_data=company_data, website=website,
                choice=int(choice), style=style,
            ))
        return out

    # -------------------------------------------------- approval-flow bits
    # How many provider takes a swap can address without asking anyone.
    # `search()` requests `per_page=5` and `_fetch_clip` clamps `choice` to
    # what came back, so five is the range the chain can reach — the exact
    # number the old live search was being spent to discover.
    SWAP_PROVIDER_TAKES = 5

    def alternates_count(self, key: str) -> int:
        """How many swap choices exist for a clip key, without a live call.

        This number exists to put a digit on a button. It used to run a real
        Pexels search to get it, so merely OPENING the swap menu spent
        quota, before the operator had swapped anything — and every failure
        was swallowed, so the count silently degraded to the owned-library
        size without saying so (A4).

        It is now the owned library plus the range the provider chain can
        address. That range is a constant rather than a measurement because
        measuring it is what cost money: `search()` asks for five results and
        `_fetch_clip` clamps `choice` to what comes back, so five is what a
        swap can reach and a sixth tap would land on the fifth clip anyway.
        Where a key has already been fetched more widely than that, the
        cached takes win — those are known to exist.

        A key with no provider chain at all (every client removed) counts
        only what is owned, which is the honest answer there.
        """
        n = len(self._library_candidates(key))
        reachable = len(self._cached_provider_takes(key))
        if self.clip_client is not None or self.gif_clients:
            reachable = max(reachable, self.SWAP_PROVIDER_TAKES)
        return max(n + reachable, 1)

    def _cached_provider_takes(self, key: str) -> list[Path]:
        """Provider takes already fetched for this key, from the clip cache.

        `meta_*.json` is written beside each normalised clip at fetch time,
        so the cache knows how many takes it holds without asking anyone.
        """
        cdir = self._clip_cache_dir(key)
        if not cdir.exists():
            return []
        return sorted(cdir.glob("meta_*.json"))

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
