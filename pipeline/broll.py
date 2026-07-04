"""B-roll manager — the reliability-critical piece (§6).

A FIXED vetted palette of ~50 keys maps to pre-tested Pexels queries.
Resolution order per key:

    1. local `assets/broll_library/` (owned, on-brand — always preferred)
    2. cache (previously fetched + normalized)
    3. Pexels fetch (rate-limited, capped, attribution stored)
    4. generic filler clip (deterministic, generated once)

A missing clip must NEVER abort a render — every failure path degrades to
the filler. Every ingested clip is normalized once (16:9 project res, fps,
capped duration, audio stripped) and cached; renders only ever touch
normalized files.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from config import Settings
from pipeline.cost import SpendCapExceededError, SpendLedger
from pipeline.render_common import RenderError, ffprobe_duration, run_ffmpeg

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# The vetted palette: key -> pre-tested Pexels video query.
# Keys are the ONLY vocabulary the LONG master prompt may use (§5.4).
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


def broll_cache_key(query: str, provider: str = "pexels") -> str:
    """§2.4: cache B-roll by sha256(query + provider)."""
    return hashlib.sha256(f"{query}|{provider}".encode()).hexdigest()[:24]


@dataclass
class BrollClip:
    key: str
    path: Path           # normalized, render-ready file
    source: str          # local | cache | pexels | filler
    attribution: str = ""


# ---------------------------------------------------------------------------
# Pexels clients (real + mock behind the same shape).
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
            last = float(self._stamp.read_text())
        except (FileNotFoundError, ValueError):
            last = 0.0
        wait = self.settings.pexels_min_interval_s - (time.time() - last)
        if wait > 0:
            time.sleep(wait)
        self._stamp.parent.mkdir(parents=True, exist_ok=True)
        self._stamp.write_text(str(time.time()))

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
    """Deterministic fixture-backed client (§0.2): search reads fixture
    JSON; download GENERATES a deterministic clip locally, exercising the
    exact same normalize+cache path as production. Zero network."""

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
        return json.loads(self._fixture_for(query).read_text())

    def download(self, url: str, dest: Path) -> Path:
        self.download_calls.append(url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        seed = int(hashlib.sha256(url.encode()).hexdigest()[:6], 16)
        hue = seed % 360
        run_ffmpeg([
            "-f", "lavfi",
            "-i", f"testsrc2=size=1280x720:rate=30:duration=6",
            "-vf", f"hue=h={hue}:s=0.35,eq=brightness=-0.28:saturation=0.8,"
                   f"drawbox=x=0:y=0:w=iw:h=ih:color=black@0.25:t=fill",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
            "-an", str(dest),
        ])
        return dest


# ---------------------------------------------------------------------------
# Manager.
# ---------------------------------------------------------------------------


def normalize_clip(src: Path, dest: Path, settings: Settings) -> Path:
    """One-time ingest normalization: cover-crop to LONG res, project fps,
    duration cap, audio stripped."""
    W, H = settings.long_resolution
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


class BrollManager:
    def __init__(
        self,
        settings: Settings,
        ledger: SpendLedger | None = None,
        client=None,
        library_dir: Path | None = None,
    ):
        self.settings = settings
        self.ledger = ledger or SpendLedger(settings)
        self.library_dir = library_dir or settings.assets_dir / "broll_library"
        if client is not None:
            self.client = client
        elif settings.mock_mode:
            self.client = MockPexelsClient(settings)
        else:
            self.client = RealPexelsClient(settings, self.ledger)

    # ------------------------------------------------------------- resolve
    def resolve(self, key: str, choice: int = 0) -> BrollClip:
        """Resolve a palette key to a normalized clip. Never raises for
        content reasons — worst case returns the filler clip.

        `choice` picks the nth candidate (the Approve-flow "Swap clip"
        button re-resolves with choice+1).
        """
        try:
            local = self._from_library(key, choice)
            if local:
                return local
            if key not in PALETTE:
                log.warning("b-roll key %r not in palette — filler", key)
                return self.filler(key)
            cached = self._from_cache(key, choice)
            if cached:
                return cached
            return self._fetch(key, choice)
        except SpendCapExceededError as e:
            log.warning("b-roll %r: %s — filler", key, e)
            return self.filler(key)
        except (PexelsError, RenderError, httpx.HTTPError, OSError) as e:
            log.warning("b-roll %r failed (%s) — filler", key, e)
            return self.filler(key)

    def plan(self, keys: list[str], overrides: dict[str, int] | None = None) -> list[BrollClip]:
        """Resolve a whole script's keys (for the §9.2 report/contact sheet)."""
        overrides = overrides or {}
        return [self.resolve(k, overrides.get(k, 0)) for k in keys]

    # ------------------------------------------------------- local library
    def _library_candidates(self, key: str) -> list[Path]:
        if not self.library_dir.is_dir():
            return []
        exact = sorted(self.library_dir.glob(f"{key}.*"))
        variants = sorted(self.library_dir.glob(f"{key}__*.*"))
        return [p for p in exact + variants if p.suffix.lower() in (".mp4", ".mov", ".mkv", ".webm")]

    def _from_library(self, key: str, choice: int) -> BrollClip | None:
        candidates = self._library_candidates(key)
        if not candidates:
            return None
        src = candidates[min(choice, len(candidates) - 1)]
        norm = self.settings.cache_dir / "broll" / "library" / f"{src.stem}.mp4"
        if not norm.exists():
            normalize_clip(src, norm, self.settings)
        return BrollClip(key=key, path=norm, source="local",
                         attribution=f"owned library clip ({src.name})")

    # --------------------------------------------------------------- cache
    def _cache_dir_for(self, key: str) -> Path:
        return self.settings.cache_dir / "broll" / broll_cache_key(PALETTE[key])

    def _from_cache(self, key: str, choice: int) -> BrollClip | None:
        cdir = self._cache_dir_for(key)
        norm = cdir / f"normalized_{choice}.mp4"
        meta = cdir / f"meta_{choice}.json"
        if norm.exists():
            attribution = ""
            if meta.exists():
                attribution = json.loads(meta.read_text()).get("attribution", "")
            return BrollClip(key=key, path=norm, source="cache", attribution=attribution)
        return None

    # --------------------------------------------------------------- fetch
    def _fetch(self, key: str, choice: int) -> BrollClip:
        query = PALETTE[key]
        data = self.client.search(query)
        videos = data.get("videos") or []
        if not videos:
            log.warning("pexels: no results for %r — filler", query)
            return self.filler(key)
        video = videos[min(choice, len(videos) - 1)]
        file_url = self._pick_file(video)
        if not file_url:
            return self.filler(key)

        cdir = self._cache_dir_for(key)
        raw = cdir / f"raw_{choice}.mp4"
        norm = cdir / f"normalized_{choice}.mp4"
        self.client.download(file_url, raw)
        normalize_clip(raw, norm, self.settings)
        raw.unlink(missing_ok=True)

        user = video.get("user", {})
        attribution = f"Video by {user.get('name', 'unknown')} on Pexels ({video.get('url', '')})"
        (cdir / f"meta_{choice}.json").write_text(json.dumps({
            "key": key, "query": query, "provider": "pexels",
            "video_id": video.get("id"), "attribution": attribution,
        }, indent=2))
        return BrollClip(key=key, path=norm, source="pexels", attribution=attribution)

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

    # -------------------------------------------------------------- filler
    def filler(self, key: str) -> BrollClip:
        """Deterministic generic glitch/static filler — the never-fail floor."""
        W, H = self.settings.long_resolution
        path = self.settings.cache_dir / "broll" / "filler" / "static_filler.mp4"
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            run_ffmpeg([
                "-f", "lavfi",
                "-i", f"color=c=0x17120d:size={W}x{H}:rate={self.settings.fps}:duration={self.settings.broll_max_clip_s:.1f}",
                "-vf", "noise=alls=9:allf=t,vignette=PI/5",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
                "-an", str(path),
            ])
        return BrollClip(key=key, path=path, source="filler",
                         attribution="")

    # -------------------------------------------------- approval-flow bits
    def alternates_count(self, key: str) -> int:
        """How many swap choices exist for this key (library + provider)."""
        n = len(self._library_candidates(key))
        if key in PALETTE:
            try:
                n += len((self.client.search(PALETTE[key]) or {}).get("videos", []))
            except Exception:
                pass
        return max(n, 1)

    def thumbnail(self, clip: BrollClip, dest: Path) -> Path:
        """First-frame thumbnail for the approval contact sheet."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        run_ffmpeg(["-i", str(clip.path), "-frames:v", "1",
                    "-vf", "scale=320:180", str(dest)])
        return dest
