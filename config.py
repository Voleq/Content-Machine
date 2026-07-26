"""Typed settings for the Dennis pipeline.

Every cap, limit, path and knob lives here (pydantic-settings). Values come
from the environment / a `.env` file; defaults are the documented sensible
defaults (see README "Defaults & deviations").

Hard rules encoded here:
  * MOCK_MODE defaults to True — no paid/live API is ever called unless the
    operator explicitly flips it.
  * All spend limits (character budgets, monthly cap, Pexels quota) are
    enforced in code by the modules that spend, using these values.
"""

from __future__ import annotations

import os
import shutil
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    # ------------------------------------------------------------------ modes
    mock_mode: bool = Field(default=True, alias="MOCK_MODE")
    log_level: str = "INFO"

    # ------------------------------------------------------------------ paths
    base_dir: Path = BASE_DIR
    workspace_dir: Path = BASE_DIR / "workspace"
    cache_dir: Path = BASE_DIR / "cache"
    state_dir: Path = BASE_DIR / "state"
    assets_dir: Path = BASE_DIR / "assets"
    templates_dir: Path = BASE_DIR / "templates"
    fixtures_dir: Path = BASE_DIR / "fixtures"

    # --------------------------------------------------------------- telegram
    telegram_bot_token: str = ""
    # Only these chat ids may drive the bot. Comma separated in env.
    operator_chat_ids: list[int] = Field(default_factory=list, alias="OPERATOR_CHAT_IDS")
    # Cloud Bot API upload cap (self-hosted Bot API server raises this).
    telegram_upload_limit_mb: int = 50
    telegram_api_base_url: str = ""  # set when using a self-hosted Bot API server

    # ------------------------------------------------------------- elevenlabs
    # VOICE IS A PLACEHOLDER — the final Dennis voice is a to-be-decided,
    # one-line change (set ELEVEN_VOICE_ID_SHORT / ELEVEN_VOICE_ID_LONG).
    # Audition shortlist (stock ElevenLabs premade voices):
    #   Brian   — dry / deadpan
    #   Charlie — casual everyman
    #   George  — weary / raspy
    # Deadpan settings for whichever wins: stability ~0.65–0.75, style low,
    # rate slightly slow. Both formats share the Dennis register now.
    elevenlabs_api_key: str = ""
    eleven_base_url: str = "https://api.elevenlabs.io"
    # Turbo/Flash tier by default (~half the credit cost per character);
    # premium multilingual only behind an explicit flag.
    eleven_model_id: str = "eleven_turbo_v2_5"
    eleven_premium_model_id: str = "eleven_multilingual_v2"
    eleven_use_premium: bool = False
    eleven_voice_id_short: str = ""   # placeholder — Dennis voice TBD
    eleven_voice_id_long: str = ""    # placeholder — Dennis voice TBD
    eleven_stability_short: float = 0.68
    eleven_similarity_short: float = 0.75
    eleven_style_short: float = 0.15
    eleven_stability_long: float = 0.72
    eleven_similarity_long: float = 0.75
    eleven_style_long: float = 0.05
    eleven_speed_long: float = 0.95
    eleven_speed_short: float = 0.97

    # ------------------------------------------------------- character budgets
    # SHORT is 60–75s of retention-first "Noise or signal?": ~180–210 spoken
    # words at the mock ~2.7 w/s. 210 words of ordinary English runs right at
    # 1200 chars, which left the budget with no headroom at all — 1400 is the
    # ceiling (not a target) so a script at the top of the word range fits.
    short_max_chars: int = Field(default=1400, alias="SHORT_MAX_CHARS")
    # LONG length is complexity-driven, not fixed: a clean thesis is a few
    # chapters (~12 min), a messy one is 7+ (~40 min). The budget is the
    # ceiling for the longest cut (~36k chars ≈ 40 min at deadpan pace), not a
    # target — the writer assembles chapters and runtime falls out of that.
    long_max_chars: int = Field(default=36000, alias="LONG_MAX_CHARS")
    # LONG scripts are chunked by paragraph to stay under request limits.
    tts_chunk_chars: int = 4000

    # ------------------------------------------------------------------- cost
    usd_per_1k_chars: float = Field(default=0.15, alias="USD_PER_1K_CHARS")
    monthly_spend_cap_usd: float = Field(default=50.0, alias="MONTHLY_SPEND_CAP")

    # ----------------------------------------------------------------- pexels
    pexels_api_key: str = ""
    pexels_base_url: str = "https://api.pexels.com"
    pexels_min_interval_s: float = 2.0     # free tier politeness
    pexels_monthly_call_cap: int = 1000    # hard stop well under free 20k/month
    broll_max_clip_s: float = 8.0          # normalize clips to at most this long

    # -------------------------------------------- content engine (multi-source)
    # [IMG]/[PRODUCT] real-imagery chain: Wikimedia Commons first (free,
    # attribution stored), then the company's own site (og:image best effort).
    wikimedia_base_url: str = "https://commons.wikimedia.org"
    image_min_interval_s: float = 1.0
    # [MEME] fallback providers, tried only on an owned-library miss and only
    # when a key is configured; the meme library in assets/ is always first.
    giphy_api_key: str = ""
    giphy_base_url: str = "https://api.giphy.com"
    tenor_api_key: str = ""
    tenor_base_url: str = "https://tenor.googleapis.com"
    imgflip_base_url: str = "https://api.imgflip.com"  # get_memes is keyless
    # information-first: a LONG may carry at most this many memes (validated)
    meme_max_per_long: int = 2

    # ---------------------------------------------- filings (10-K auto-screenshot)
    # Pull the latest 10-K from SEC EDGAR, flag smoking-gun quotes with a cheap
    # LLM, and Playwright-screenshot each — replacing the manual PNG upload.
    # All network is skipped in MOCK_MODE (fixtures, $0); a failed pull never
    # blocks a render. SEC requires a declared User-Agent for live pulls.
    filings_enabled: bool = Field(default=True, alias="FILINGS_ENABLED")  # per-run kill switch
    sec_user_agent: str = Field(default="", alias="SEC_USER_AGENT")  # "Name email" — REQUIRED live
    sec_base_url: str = "https://www.sec.gov"
    sec_data_base_url: str = "https://data.sec.gov"
    sec_min_interval_s: float = 0.11        # SEC fair-access: keep well under 10 req/s
    filings_include_10q: bool = Field(default=False, alias="FILINGS_INCLUDE_10Q")
    filings_max_shots: int = Field(default=3, alias="FILINGS_MAX_SHOTS")
    # smoking-gun flagging LLM — swappable. Default: GitHub Models gpt-4o-mini
    # (free tier, OpenAI-compatible endpoint + a GitHub token). MOCK -> fixture.
    filings_llm_provider: str = Field(default="github", alias="FILINGS_LLM_PROVIDER")  # github|openai|mock
    filings_llm_model: str = Field(default="gpt-4o-mini", alias="FILINGS_LLM_MODEL")
    filings_llm_max_chars: int = 24000      # per-call section budget (free tier is rate-limited)
    filings_llm_usd_per_call: float = 0.0   # free tier; still recorded in the ledger
    github_models_token: str = Field(default="", alias="GITHUB_MODELS_TOKEN")
    github_models_endpoint: str = Field(
        default="https://models.inference.ai.azure.com", alias="GITHUB_MODELS_ENDPOINT")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_base_url: str = "https://api.openai.com"
    # --- LLM routing ------------------------------------------------------
    # The cheap passes run local-first: a 7-8B model on the render box's GPU
    # has no rate limit and no quota, and is still $0. Hosted tiers are the
    # fallback. Comma-separated; empty means ollama,github,openai.
    llm_provider_order: str = Field(default="", alias="LLM_PROVIDER_ORDER")
    # A render built on a stale snapshot states old numbers as current.
    data_max_age_days: int = Field(default=10, alias="DATA_MAX_AGE_DAYS")
    data_stale_blocks: bool = Field(default=False, alias="DATA_STALE_BLOCKS")

    # ------------------------------------------------- Excel refresh (COM)
    # The render box runs Windows with Excel and the LSEG/CIQ add-in loaded,
    # so the bot refreshes the data template itself instead of asking for an
    # upload. Off-Windows (and with the switch off) the manual upload is the
    # only path — which is exactly what it was before this existed.
    excel_refresh_enabled: bool = Field(default=True, alias="EXCEL_REFRESH_ENABLED")
    excel_template_path: str = Field(default="", alias="EXCEL_TEMPLATE_PATH")
    # v3.1 template: the plain Capital IQ ticker goes in Snapshot!C3 and every
    # CIQ formula reads it; B3 DERIVES the Refinitiv RIC from it and must not
    # be written. Override only if the template moves them.
    excel_ticker_cell: str = Field(default="C3", alias="EXCEL_TICKER_CELL")
    excel_ric_cell: str = Field(default="E2", alias="EXCEL_RIC_CELL")
    # Normally blank: the template looks the RIC suffix up from the exchange
    # itself (the hidden _RICMap table), which beats guessing. Set this to
    # force one — ".O" makes PLTR into PLTR.O. Per-ticker pins in
    # state/excel_symbols.json beat this, and both land in the RIC override
    # cell, never in the ticker cell.
    excel_symbol_suffix: str = Field(default="", alias="EXCEL_SYMBOL_SUFFIX")
    # Which add-in macro fires the refresh differs by vintage; comma-separated
    # candidates, tried in order, falling back to a full recalculation.
    excel_refresh_macros: str = Field(default="", alias="EXCEL_REFRESH_MACROS")
    # CIQ/LSEG refreshes are asynchronous. Finishing early yields a workbook
    # full of blanks that looks like success, so the poll is generous and a
    # timeout is a hard failure.
    excel_refresh_timeout_s: float = Field(default=240.0, alias="EXCEL_REFRESH_TIMEOUT_S")
    excel_poll_interval_s: float = Field(default=2.0, alias="EXCEL_POLL_INTERVAL_S")
    # Consecutive unchanged polls before the snapshot is called settled.
    excel_settle_polls: int = Field(default=3, alias="EXCEL_SETTLE_POLLS")
    excel_visible: bool = Field(default=False, alias="EXCEL_VISIBLE")
    ollama_base_url: str = Field(default="http://127.0.0.1:11434",
                                 alias="OLLAMA_BASE_URL")
    ollama_model: str = Field(default="llama3.1:8b", alias="OLLAMA_MODEL")
    ollama_timeout_s: float = 120.0
    # headless Chromium for the screenshots; empty -> Playwright default, or the
    # pre-provisioned browser if present.
    playwright_chromium_path: str = Field(default="", alias="PLAYWRIGHT_CHROMIUM_PATH")

    # ------------------------------------------------------------------ prices
    # Price history feeds the branded chart (rendered by the pipeline, never a
    # screenshot). Same Yahoo feed the screener uses; cached, data-only.
    price_history_days: int = 120
    prices_cache_ttl_s: int = 3600

    # ------------------------------------------------------------------ video
    fps: int = 30
    short_width: int = 1080
    short_height: int = 1920
    long_width: int = 1920
    long_height: int = 1080
    short_target_seconds: float = 70.0  # 60–75s "Noise or signal?" band midpoint
    # Deliberate pacing (§editing): Dennis holds the frame and cuts away to
    # evidence that stays up long enough to read. `long_min_readable_s` is the
    # floor for data visuals — a later cut is deferred rather than truncating
    # a chart or a filing the viewer is still reading.
    long_min_readable_s: float = 5.0
    # host on each side of a chapter boundary, so chapters bookend on his face
    long_chapter_host_s: float = 2.5

    # encode profiles (§7.3) — libx264 assumed on a cheap VPS; hardware
    # encoders are auto-detected at startup and used when present.
    final_preset: str = "veryfast"
    draft_preset: str = "ultrafast"
    short_crf: int = 20
    long_crf: int = 22
    draft_crf: int = 32
    draft_scale: float = 0.5               # draft renders at half resolution
    # PREVIEW is a third, cheaper tier below draft: 480p at 15fps, for
    # judging edit and pacing when neither resolution nor smoothness
    # matters. Halving the frame rate roughly halves the filter-graph work,
    # which is where the time actually goes.
    preview_scale: float = 0.25
    preview_fps: int = 15
    preview_crf: int = 34
    audio_bitrate: str = "192k"
    music_gain_db: float = -22.0           # music bed under the VO
    sfx_gain_db: float = -6.0
    use_hardware_encoder: bool = True      # if detected; falls back to libx264

    # --- encode politeness ------------------------------------------------
    # The render box is the operator's daily-driver desktop, and renders are
    # unattended: slower-but-polite is the right trade. ffmpeg is capped to a
    # share of the cores and runs de-prioritised, so a 40-minute LONG never
    # makes the machine unusable.
    #
    # `render_thread_fraction` is a share of os.cpu_count(); the resolved cap
    # is at least 1 and never exceeds the core count. Set
    # `render_threads` to pin an exact number instead (0 = derive it).
    render_thread_fraction: float = Field(default=0.5, ge=0.05, le=1.0)
    render_threads: int = Field(default=0, ge=0)
    # Below-normal priority on Windows, +10 nice on POSIX. Off means the
    # render competes with the desktop on equal terms.
    render_below_normal_priority: bool = True
    # Encode each beat as its own clip — content-hash cached, encoded in
    # parallel, resumable across a reboot — then concatenate. False falls back
    # to the original monolithic filter_complex, kept for comparison.
    render_segmented: bool = Field(default=True, alias="RENDER_SEGMENTED")
    # Bound the segment cache; it lives outside the workspace on purpose so it
    # survives cleanup and reboots.
    segment_cache_max_files: int = 4000

    # --------------------------------------------------------------- delivery
    # The renderer is now the operator's own machine, so a Drive round-trip
    # is pure latency: write to a watched folder and post the path. gdrive
    # stays available for when the bot moves to a separate always-on host.
    delivery_backend: str = Field(default="local", alias="DELIVERY_BACKEND")  # gdrive | s3 | telegram | local
    gdrive_credentials: str = Field(default="", alias="GDRIVE_CREDENTIALS")    # path to service-account/OAuth JSON
    gdrive_root_folder_id: str = Field(default="", alias="GDRIVE_ROOT_FOLDER_ID")
    gdrive_folder_name: str = "Dennis"
    s3_bucket: str = ""
    s3_prefix: str = "dennis"
    s3_region: str = "us-east-1"

    # ------------------------------------------------------------------- jobs
    max_concurrent_renders: int = 1
    retention_days: int = Field(default=14, alias="RETENTION_DAYS")

    # --------------------------------------------------------------- screener
    screen_top_n: int = Field(default=8, alias="SCREEN_TOP_N")
    cooldown_days: int = Field(default=30, alias="COOLDOWN_DAYS")
    # 5-field cron, interpreted in screen_timezone. Default: 07:30 ET weekdays.
    screen_digest_cron: str = Field(default="30 7 * * 1-5", alias="SCREEN_DIGEST_CRON")
    screen_timezone: str = "America/New_York"
    screen_min_price: float = 2.0
    screen_min_market_cap: float = 300e6
    screen_min_avg_volume: float = 500_000
    screen_value_low_pct: float = 15.0     # within 15% of 52w low
    screen_value_drawdown_pct: float = 40.0  # >= 40% off the 52w high
    stocktwits_base_url: str = "https://api.stocktwits.com"
    screener_cache_ttl_s: int = 900
    screen_allow_list: list[str] = Field(default_factory=list)
    screen_deny_list: list[str] = Field(default_factory=list)

    # -------------------------------------------------------------- editorial
    disclaimer_text: str = Field(
        default="Opinion / entertainment. Not financial advice.",
        alias="DISCLAIMER_TEXT",
    )
    # brand copy burned into the intro/outro bug — never the data vendor
    brand_name: str = "DENNIS"
    brand_tagline: str = "NOISE OR SIGNAL?"

    # ------------------------------------------------------------ mock timing
    # Deterministic mock TTS pacing (words per second) so rendered fixtures
    # have realistic durations without any paid call.
    mock_wps_short: float = 2.7
    mock_wps_long: float = 2.3

    # ------------------------------------------------------------- validators
    @field_validator("operator_chat_ids", "screen_allow_list", "screen_deny_list", mode="before")
    @classmethod
    def _split_csv(cls, v):
        if isinstance(v, str):
            v = [item.strip() for item in v.split(",") if item.strip()]
        return v

    @field_validator("delivery_backend")
    @classmethod
    def _check_backend(cls, v: str) -> str:
        allowed = {"gdrive", "s3", "telegram", "local"}
        v = v.lower()
        if v not in allowed:
            raise ValueError(f"DELIVERY_BACKEND must be one of {sorted(allowed)}")
        return v

    # ------------------------------------------------------------ conveniences
    @property
    def short_resolution(self) -> tuple[int, int]:
        return (self.short_width, self.short_height)

    @property
    def long_resolution(self) -> tuple[int, int]:
        return (self.long_width, self.long_height)

    @property
    def active_eleven_model(self) -> str:
        return self.eleven_premium_model_id if self.eleven_use_premium else self.eleven_model_id

    @property
    def fonts_dir(self) -> Path:
        return self.assets_dir / "fonts"

    def voice_settings(self, fmt: str) -> dict:
        """Per-format ElevenLabs voice settings (part of the TTS cache key)."""
        if fmt == "short":
            return {
                "stability": self.eleven_stability_short,
                "similarity_boost": self.eleven_similarity_short,
                "style": self.eleven_style_short,
                "speed": self.eleven_speed_short,
            }
        return {
            "stability": self.eleven_stability_long,
            "similarity_boost": self.eleven_similarity_long,
            "style": self.eleven_style_long,
            "speed": self.eleven_speed_long,
        }

    def voice_id(self, fmt: str) -> str:
        return self.eleven_voice_id_short if fmt == "short" else self.eleven_voice_id_long

    def max_chars(self, fmt: str) -> int:
        return self.short_max_chars if fmt == "short" else self.long_max_chars

    def ensure_runtime_dirs(self) -> None:
        for d in (self.workspace_dir, self.cache_dir, self.state_dir):
            d.mkdir(parents=True, exist_ok=True)

    def resolved_render_threads(self) -> int:
        """How many threads ffmpeg may use, leaving the desktop responsive."""
        cores = os.cpu_count() or 4
        if self.render_threads:
            return max(1, min(self.render_threads, cores))
        return max(1, min(cores, round(cores * self.render_thread_fraction)))


def detect_ffmpeg() -> tuple[str, str]:
    """Locate ffmpeg/ffprobe or fail loudly at startup."""
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError(
            "ffmpeg/ffprobe not found on PATH. Install FFmpeg 6+ — "
            "Linux: `apt install ffmpeg`; "
            "Windows: `winget install Gyan.FFmpeg` (then reopen the terminal "
            "so PATH refreshes)."
        )
    return ffmpeg, ffprobe


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
