"""Typed settings for the Due Diligence Desk pipeline.

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
    elevenlabs_api_key: str = ""
    eleven_base_url: str = "https://api.elevenlabs.io"
    # Cheap tier by default; premium behind a flag (cost rule §8.5).
    eleven_model_id: str = "eleven_turbo_v2_5"
    eleven_premium_model_id: str = "eleven_multilingual_v2"
    eleven_use_premium: bool = False
    eleven_voice_id_short: str = ""
    eleven_voice_id_long: str = ""
    # Deadpan LONG vs energetic SHORT (§10).
    eleven_stability_short: float = 0.45
    eleven_similarity_short: float = 0.75
    eleven_style_short: float = 0.45
    eleven_stability_long: float = 0.80
    eleven_similarity_long: float = 0.75
    eleven_style_long: float = 0.05
    eleven_speed_long: float = 0.95
    eleven_speed_short: float = 1.0

    # ------------------------------------------------------- character budgets
    short_max_chars: int = Field(default=800, alias="SHORT_MAX_CHARS")
    long_max_chars: int = Field(default=22000, alias="LONG_MAX_CHARS")
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

    # ------------------------------------------------------------------ video
    fps: int = 30
    short_width: int = 1080
    short_height: int = 1920
    long_width: int = 1920
    long_height: int = 1080
    short_target_seconds: float = 60.0
    long_min_cut_s: float = 3.0
    long_max_cut_s: float = 5.0

    # encode profiles (§7.3) — libx264 assumed on a cheap VPS; hardware
    # encoders are auto-detected at startup and used when present.
    final_preset: str = "veryfast"
    draft_preset: str = "ultrafast"
    short_crf: int = 20
    long_crf: int = 22
    draft_crf: int = 32
    draft_scale: float = 0.5               # draft renders at half resolution
    audio_bitrate: str = "192k"
    music_gain_db: float = -22.0           # music bed under the VO
    sfx_gain_db: float = -6.0
    use_hardware_encoder: bool = True      # if detected; falls back to libx264

    # --------------------------------------------------------------- delivery
    delivery_backend: str = Field(default="gdrive", alias="DELIVERY_BACKEND")  # gdrive | s3 | telegram | local
    gdrive_credentials: str = Field(default="", alias="GDRIVE_CREDENTIALS")    # path to service-account/OAuth JSON
    gdrive_root_folder_id: str = Field(default="", alias="GDRIVE_ROOT_FOLDER_ID")
    gdrive_folder_name: str = "DueDiligenceDesk"
    s3_bucket: str = ""
    s3_prefix: str = "due-diligence-desk"
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


def detect_ffmpeg() -> tuple[str, str]:
    """Locate ffmpeg/ffprobe or fail loudly at startup."""
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError(
            "ffmpeg/ffprobe not found on PATH. Install FFmpeg 6+ (apt install ffmpeg)."
        )
    return ffmpeg, ffprobe


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
