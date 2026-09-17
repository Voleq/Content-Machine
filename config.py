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

import json
import logging
import os
import shutil
from functools import lru_cache
from pathlib import Path
from typing import Annotated, ClassVar

from pydantic import Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent

# ElevenLabs list price, USD per 1,000 characters, by model id.
#
# EXACT MATCH ONLY, and never a default. Both halves of that are the lesson
# from the two ways this has already been wrong.
#
# It began as a hardcoded 0.15 for every model, which was the price of none of
# them. That erred SAFE: it overstated, so a $50 cap stopped paid calls at
# about $16.67 of real spend. Annoying, and not dangerous.
#
# It was then corrected to 0.05 for `eleven_v3`, which erred the other way and
# is much worse. `eleven_v3` is $0.10; it is `eleven_v3_conversational` that is
# $0.05, and they are separate models with separate included-character
# allowances (220,000 vs 440,000 on Creator). Pricing v3 at half its rate makes
# SpendLedger meter at half speed, so the same $50 cap would wave through
# roughly $100 of real spend. The cap is the only hard stop in this system and
# it must never fail in that direction.
#
# WHICH IS WHY LOOKUP IS EXACT. `eleven_v3_conversational` starts with
# `eleven_v3` and costs half as much, so any prefix or substring match is wrong
# by construction — it would price the dearer model at the cheaper one's rate,
# which is precisely the failure above. Note that `direction.performs_audio_tags`
# DOES substring-match, and is right to: both models perform audio tags. The two
# questions look alike and must not share a lookup.
#
# An id that is not here raises rather than defaulting, because a missing entry
# and a wrong one are indistinguishable at runtime, and the guess is what caused
# the harm both times. USD_PER_1K_CHARS is the escape hatch when a price moves
# or a model is newer than this table.
ELEVEN_USD_PER_1K_CHARS: dict[str, float] = {
    "eleven_turbo_v2_5": 0.05,
    "eleven_flash_v2_5": 0.05,
    # The narration model, and the one this pipeline chose: the selection guide
    # puts narration here. Twice turbo's price, and the audio tags are what the
    # difference buys.
    "eleven_v3": 0.10,
    # NOT the same model, and not interchangeable with it. This is the Agents
    # Platform model, tuned for ~280ms latency — which buys an unattended batch
    # render exactly nothing. Recorded so the distinction stays recorded rather
    # than being rediscovered by a cap that failed open.
    "eleven_v3_conversational": 0.05,
    "eleven_multilingual_v2": 0.10,
}


class UnknownModelPriceError(RuntimeError):
    """No list price for the selected model, and no override to stand in.

    Deliberately fatal. Guessing a rate is how a spend cap comes to meter at
    the wrong speed, and a cap that meters at the wrong speed is worse than no
    cap at all — it reports a number the operator trusts.
    """


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    # ------------------------------------------------------------------ modes
    # MOCK_MODE is the master switch and the hard cost rule: on by default, and
    # with it on no paid API can be called at all.
    mock_mode: bool = Field(default=True, alias="MOCK_MODE")

    # Per-subsystem overrides. Unset (None) means "follow MOCK_MODE".
    #
    # These exist because "mock" was one undifferentiated flag and nothing on
    # screen said which parts of a run were fake. /screen returned fixture
    # tickers and the chart drew synthetic prices, neither labelled, and the
    # result was a bug report about data that was never real. Splitting them
    # lets a run be honest about exactly which half is invented — and lets an
    # operator mock only the expensive one.
    mock_tts: bool | None = Field(default=None, alias="MOCK_TTS")
    mock_prices: bool | None = Field(default=None, alias="MOCK_PRICES")
    mock_screener: bool | None = Field(default=None, alias="MOCK_SCREENER")

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
    # Only these chat ids may drive the bot. A JSON array or a bare
    # comma-separated list; see `_split_csv`.
    operator_chat_ids: Annotated[list[int], NoDecode] = Field(
        default_factory=list, alias="OPERATOR_CHAT_IDS")
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
    # THE model setting: name the model you want. The price follows it (see
    # ELEVEN_USD_PER_1K_CHARS above) and so does audio-tag support. Empty means
    # "whichever tier the deprecated boolean below picks", which is what every
    # .env written before this setting existed is asking for.
    #
    # Choosing a model used to run through ELEVEN_USE_PREMIUM, a boolean over
    # two hardcoded ids. The field would have taken any id, but nothing said
    # so - not .env.example, not the README - and the boolean quietly decided
    # between the other two regardless, so `eleven_v3` was unreachable in
    # practice. v3 is the only model that honours [SIGH] instead of having it
    # read aloud (see pipeline/tts.py), so what that cost was the register the
    # voice bible is built on.
    #
    # It is NOT free: v3 is $0.10/1k against turbo's $0.05, and the audio tags
    # are what the difference buys. `eleven_v3_conversational` is the $0.05
    # one, and it is a different model — the Agents Platform's, tuned for
    # ~280ms latency, which is worth nothing to an unattended batch render.
    eleven_model_id: str = Field(default="", alias="ELEVEN_MODEL_ID")
    # The two tier defaults, and DEPRECATED with the boolean that picks between
    # them. Kept, rather than folded into constants, so an .env that already
    # sets one keeps working.
    eleven_default_model_id: str = "eleven_turbo_v2_5"
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
    # Which LONG engine renders a final (D6). "segments" is the tag-driven
    # jump-cut compositor in `render_long.py`, which is what the bot has
    # always used. "shots" is `render_long_shots.py`: the director picks nine
    # chapter TYPES, each expands to its own shot list from
    # `templates/chapters/`, and the composition goes through the same
    # compositor the SHORT uses.
    #
    # The shots engine had its own committed samples and manifests and no
    # path from any command — reachable only from `scripts/render_samples.py`
    # — which is how a second render engine sat there being genuinely
    # ambiguous about which code was live. It has a route now. The default
    # does not move: the segments engine is what every finished video on the
    # channel was cut with, and switching that is an editorial decision, not
    # a defect fix.
    long_render_engine: str = Field(default="segments",
                                    alias="LONG_RENDER_ENGINE")
    long_max_chars: int = Field(default=36000, alias="LONG_MAX_CHARS")
    # The LONG parser's floor (C1). It used to reject only EMPTY input, so a
    # plain chat remark — "hold on, the revenue number in row 2 looks wrong"
    # — parsed as a valid forty-minute script and was saved over whatever was
    # there. A real LONG runs to twenty thousand characters; four hundred is
    # far below anything a writer would send and far above anything an
    # operator would type into a chat by accident.
    long_min_chars: int = Field(default=400, alias="LONG_MIN_CHARS")
    # LONG scripts are chunked by paragraph to stay under request limits.
    tts_chunk_chars: int = 4000

    # ------------------------------------------------------------------- cost
    # An OVERRIDE, not the rate. Unset means "whatever the selected model
    # costs", which is the only version of this number that cannot go stale
    # against the model actually being called - see tts_usd_per_1k_chars.
    #
    # It was a hardcoded 0.15 that matched neither model the code could select:
    # turbo is $0.05 and multilingual_v2 is $0.10. That is not a cosmetic
    # figure on the approval screen. SpendLedger meters against it, so a $50
    # cap stopped paid calls after about $16.67 of real spend and every cost
    # report read 3x high. Set this only to correct a price this table has
    # wrong, or to meter a model it does not know.
    usd_per_1k_chars: float | None = Field(default=None,
                                           alias="USD_PER_1K_CHARS")
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
    # GIF-sourced visuals per video (H3). Giphy and Tenor content is
    # user-uploaded and frequently copyrighted, and the fallback fires
    # precisely when a clip is specific enough that stock footage misses —
    # so it was the most legally exposed surface in the pipeline with no
    # counter, no report line and no ceiling, while memes from the OWNED
    # library were capped at one or two. Same shape as the meme cap.
    gif_max_per_video: int = Field(default=2, alias="GIF_MAX_PER_VIDEO")
    # Rewrite an OFF-PALETTE clip subject into stock-searchable terms before
    # the Pexels call (H4). The 53-entry palette is hand-curated and
    # pre-tested and bypasses this entirely — never rewrite a query someone
    # already tested. Only free-text subjects go through it, and they are the
    # minority that misses on stock footage and falls through to the GIF
    # providers. Local-first and cached; off means the raw text is sent, as
    # it always was.
    broll_rewrite_offpalette: bool = Field(default=True,
                                           alias="BROLL_REWRITE_OFFPALETTE")

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
    # --- the pre-angle filing brief (K) ----------------------------------
    # The reading starts the instant `/long TICKER` is typed, in parallel
    # with the operator refreshing the workbook — a dozen-odd LLM calls over
    # two annual reports and the quarterly pair beside them, eight to ten
    # minutes. Ten minutes of dead time AFTER an upload is the difference
    # between a feature that gets used and one that gets switched off.
    filing_brief_enabled: bool = Field(default=True, alias="FILING_BRIEF_ENABLED")
    # How long the upload reply will wait for a reading still in flight. A
    # slow operator finds it done; a fast one waits. Past this the prompt
    # goes out without the brief rather than the operator watching a silent
    # bot — an absent brief is a normal outcome, a hung intake is not.
    filing_brief_wait_s: float = Field(default=600.0, alias="FILING_BRIEF_WAIT_S")
    # The filing passes route through `pipeline.llm.chat` like every other
    # LLM call, so `llm_provider_order` below decides WHERE they run. This
    # setting's only remaining job is the offline escape hatch: `mock`
    # serves the fixtures without MOCK_MODE being on globally.
    #
    # It used to select the provider itself, for a private httpx client in
    # `filings.py` that ignored the routing table — so a box with Ollama
    # running served every gate locally and every filing call over the
    # network, for money, with nothing saying so (K2).
    filings_llm_provider: str = Field(default="routed", alias="FILINGS_LLM_PROVIDER")  # routed|mock
    # The HOSTED model name, read by `llm.py` for the github/openai tiers.
    # The local tier uses `ollama_model`.
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
    #
    # Blocking by default (B5). The README's guarantee table has always
    # listed freshness as a blocking gate; the code shipped it as a warning,
    # and a row that says "enforced in code" while the code shrugs is worse
    # than no row. This is also the house rule: a refusal is data, and the
    # choice between failing loudly and carrying on quietly goes to loud.
    # Set DATA_STALE_BLOCKS=false to go back to advisory.
    data_max_age_days: int = Field(default=10, alias="DATA_MAX_AGE_DAYS")
    data_stale_blocks: bool = Field(default=True, alias="DATA_STALE_BLOCKS")

    # ------------------------------------- by-products + status page (P3.6)
    # Every finished render emits the kit's thumbnail layouts, social cards
    # and end screens — free, since the artwork and the data already exist.
    byproducts_enabled: bool = Field(default=True, alias="BYPRODUCTS_ENABLED")
    # Where golden reference frames live. Blank = fixtures/golden. Overridden
    # in tests so a run can never bless frames into the repo's own fixtures.
    golden_dir: str = Field(default="", alias="GOLDEN_DIR")
    # A read-only localhost view of queue/backlog/renders. Loopback only: it
    # shows the render box's internals and has no authentication.
    status_page_enabled: bool = Field(default=False, alias="STATUS_PAGE_ENABLED")
    status_page_port: int = Field(default=8787, alias="STATUS_PAGE_PORT")
    status_refresh_s: int = Field(default=20, alias="STATUS_REFRESH_S")

    # -------------------------------------- YouTube publishing (P3.5 + 5b)
    # Uploads are ALWAYS private or scheduled — never public straight out of a
    # machine. Long-form gets made in batches, so a publish datetime can be
    # set per video and the cadence runs itself.
    youtube_enabled: bool = Field(default=False, alias="YOUTUBE_ENABLED")
    youtube_credentials: str = Field(default="", alias="YOUTUBE_CREDENTIALS")
    youtube_category_id: str = Field(default="25", alias="YOUTUBE_CATEGORY_ID")  # News & Politics
    # How far back the Analytics query looks when pulling retention.
    retention_window_days: int = Field(default=28, alias="RETENTION_WINDOW_DAYS")

    # ------------------------------------------------ free sources (P3.4)
    # 8-K/EX-99.1, Form 4 and 13F reuse the EDGAR client above (SEC_USER_AGENT
    # and the fair-access interval apply). FRED needs its own free key. Every
    # source degrades to "unavailable" rather than failing a run.
    fred_api_key: str = Field(default="", alias="FRED_API_KEY")
    fred_base_url: str = "https://api.stlouisfed.org"
    # Optional webcast transcription. Slow and GPU-hungry; nothing waits on it.
    whisper_enabled: bool = Field(default=False, alias="WHISPER_ENABLED")
    whisper_model: str = Field(default="base.en", alias="WHISPER_MODEL")
    whisper_cuda: bool = Field(default=True, alias="WHISPER_CUDA")

    # ---------------------------------------------- intraday alerting (3b)
    # Short-form is time-sensitive, and one pre-market digest doesn't cover
    # it. These watch covered names during market hours. Every knob here
    # exists to stop the bot being chatty: a muted alerter is worse than none.
    alerts_enabled: bool = Field(default=True, alias="ALERTS_ENABLED")
    alert_poll_minutes: int = Field(default=15, alias="ALERT_POLL_MINUTES")
    alert_move_pct: float = Field(default=6.0, alias="ALERT_MOVE_PCT")
    alert_volume_multiple: float = Field(default=3.0, alias="ALERT_VOLUME_MULTIPLE")
    # A mover we've never covered has to be much bigger to be worth saying —
    # otherwise this just duplicates the screener, loudly.
    alert_unwatched_pct: float = Field(default=12.0, alias="ALERT_UNWATCHED_PCT")
    alert_cooldown_minutes: int = Field(default=180, alias="ALERT_COOLDOWN_MINUTES")
    # Inside the cooldown, a repeat needs to be this much bigger to speak.
    alert_escalation_factor: float = Field(default=1.75, alias="ALERT_ESCALATION_FACTOR")
    alert_max_per_poll: int = Field(default=4, alias="ALERT_MAX_PER_POLL")
    # The hours alerts ARE allowed, local time (may cross midnight).
    alert_start_hour: int = Field(default=9, alias="ALERT_START_HOUR")
    alert_end_hour: int = Field(default=17, alias="ALERT_END_HOUR")
    alert_weekends: bool = Field(default=False, alias="ALERT_WEEKENDS")

    # ------------------------------------------------ standing state (P3.3)
    # What the bot remembers between sessions: each covered ticker's thesis
    # and the numbers behind it, a ranked idea backlog, and renders queued to
    # run unattended overnight.
    thesis_tracking: bool = Field(default=True, alias="THESIS_TRACKING")
    idea_queue_max_age_days: int = Field(default=30, alias="IDEA_QUEUE_MAX_AGE_DAYS")
    repurpose_clips: int = Field(default=3, alias="REPURPOSE_CLIPS")
    # The unattended window, local time. The render box is a desktop that
    # sleeps, so a batch that does not run is a non-event — the work waits.
    batch_start_hour: int = Field(default=1, alias="BATCH_START_HOUR")
    batch_end_hour: int = Field(default=7, alias="BATCH_END_HOUR")
    batch_enabled: bool = Field(default=True, alias="BATCH_ENABLED")

    # -------------------------------------------------- local TTS (drafts)
    # A third audio tier between the mock hum and the paid voice: a local
    # neural voice on the render box's GPU, free, listenable, and marked
    # draft. Purpose is to iterate on pacing and edit points without spending;
    # the final still buys one ElevenLabs generation. Absent Piper, a draft
    # falls back to mock — never to paid.
    local_tts_enabled: bool = Field(default=True, alias="LOCAL_TTS_ENABLED")
    local_tts_binary: str = Field(default="piper", alias="LOCAL_TTS_BINARY")
    local_tts_model: str = Field(default="", alias="LOCAL_TTS_MODEL")  # .onnx voice
    local_tts_speaker: int = Field(default=-1, alias="LOCAL_TTS_SPEAKER")  # -1 = default
    # CPU by default: Piper medium runs several times faster than real time on
    # CPU, and the GPU path needs onnxruntime-gpu against a matching CUDA
    # stack — a fragile dependency on a modest laptop, for a tier whose whole
    # value is that it always works. The GPU is reserved for NVENC on finals.
    local_tts_cuda: bool = Field(default=False, alias="LOCAL_TTS_CUDA")

    ollama_base_url: str = Field(default="http://127.0.0.1:11434",
                                 alias="OLLAMA_BASE_URL")
    # THE MODEL THE FILING BRIEF WAS SIZED FOR (K2b). Dense 12B, 256K
    # context, ~8GB at int4 QAT — fits an RTX 3060 12GB with headroom for
    # the KV cache. Needs Ollama 0.22 or newer.
    #
    # Three properties drove the choice and are worth preserving if you swap:
    #
    # - Context. 24k-character sections are fine anywhere, but the
    #   CONDENSATION pass has to hold every section summary from up to four
    #   filings plus the workbook dashboard at once. A 32K-context model
    #   gets tight there.
    # - Dense, not MoE. A model that spills into system RAM has
    #   unpredictable latency, and latency failures here are invisible (see
    #   `ollama_timeout_s` below).
    # - Fully resident in VRAM. The box renders video on the same hardware.
    #   ffmpeg's x264 work is CPU-side so contention is minimal, but only if
    #   the model stays loaded — set `OLLAMA_KEEP_ALIVE` to at least `30m`
    #   or every section call pays an 8GB reload.
    #
    # `qwen3:14b` (~9GB Q4_K_M) is the fallback if the briefs come out thin:
    # the stronger general reasoner, with a 32K context and a tighter fit.
    #
    # A box with a different model pulled sets `OLLAMA_MODEL`. Getting this
    # wrong costs the optional passes (no brief, no skeptic read, each
    # saying so) and never a render.
    ollama_model: str = Field(default="gemma4:12b-it-qat", alias="OLLAMA_MODEL")
    # The context window Ollama is TOLD to use (K2). Its default has
    # historically been 2048-4096 tokens; `filings_llm_max_chars` is 24000
    # (~6,000 tokens), and Ollama does not error on an overflowing prompt —
    # it drops the front and summarises what remains, so roughly half of
    # every 10-K section fell off and the brief came back plausible,
    # confident and partly fiction.
    #
    # Here rather than in an Ollama Modelfile: a Modelfile works and hides a
    # load-bearing value somewhere the repository cannot see, audit or test,
    # and the whole reason this defect existed is that the budget lived in
    # one place and the context limit in another.
    #
    # `scripts/check_llm_context.py` proves it is actually taking effect.
    ollama_num_ctx: int = Field(default=16384, alias="OLLAMA_NUM_CTX")
    # Raised from 120s (K2). Two full 10-Ks is a dozen-plus calls on a
    # background job with no user waiting on it, and a timeout used to be
    # swallowed as "unavailable" at debug level — indistinguishable from a
    # missing daemon. It is logged at warning level now, because a pass that
    # nearly worked is different information from one that never started.
    ollama_timeout_s: float = Field(default=300.0, alias="OLLAMA_TIMEOUT_S")
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
    # The ceiling on a held composition. Nothing on a SHORT may sit unchanged
    # longer than this without a cut, a new overlay or motion — measured off
    # the frames, not the manifest, because a filter graph that "has the right
    # arguments" is exactly what produced a 12.5-second still.
    #
    # Defaulted from the format's own spec rather than picked: timeline's
    # SHORT_DATA_HOLD_S tops out at 8s, so a composition holding longer than
    # the longest legitimate DATA hold is not being read, it is being waited
    # out — in a format whose spec is fast cuts.
    short_max_hold_s: float = 8.0
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
    # Three passes sit below a final, and each answers a DIFFERENT question.
    # Read the scale, not the name, before reusing one:
    #
    #   draft   (0.5, real fps)   — does the TIMING work? where do the cuts land?
    #   preview (0.25, 15 fps)    — does the EDIT work, at contact-sheet size?
    #   proof   (1.0, real fps)   — does it LOOK right on a phone?
    #
    # PROOF is the only one that can answer the third question, because
    # legibility is a function of RESOLUTION: a headline card that renders
    # around 9px-equivalent is unreadable at 1080p and invisible at 270p, and
    # both cheaper passes destroy exactly the evidence you are looking for.
    # So proof keeps the full frame and buys its speed from the ENCODER
    # instead — veryfast/crf 26, which is where a modest laptop should be
    # saving. Encode quality does not change whether type is readable at
    # size; frame size does.
    proof_scale: float = 1.0
    proof_crf: int = 26
    proof_preset: str = "veryfast"
    audio_bitrate: str = "192k"
    sfx_gain_db: float = -6.0
    use_hardware_encoder: bool = True      # if detected; falls back to libx264

    # --- the mix reacts to structure --------------------------------------
    # A forty-minute video has no felt structure. The chapter opener is
    # visual only — the room plate with the title in its slot — so a viewer
    # who looks away misses that a new argument started. This is a NAVIGATION
    # SIGNPOST, not atmosphere: it fires because a chapter began, and the
    # sound is diegetic (he is typing the chapter title) so it cannot read as
    # hype. A `ding` sounds like a notification, and sound boards are what
    # Cramer does.
    #
    # A setting rather than a constant because the choice can only really be
    # made by listening to real videos: `paper_rustle` and `ding` are the
    # alternatives worth auditioning. Blank turns the cue off. LONG only —
    # shorts have no chapters.
    chapter_cue_sfx: str = Field(default="keyboard_clack", alias="CHAPTER_CUE_SFX")

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
    # When a bare date means (E6). `resolve_publish_at`'s docstring has
    # described "the configured hour" since it was written and no such
    # setting existed: a bare date parsed to midnight UTC, so
    # `/upload TICKER 2026-09-20` published at 2am in Bucharest. Naive times
    # with an explicit clock are read in this zone too, rather than UTC.
    # How many times a dropped resumable upload retries before giving up
    # (E8). The session URI is persisted either way, so a give-up is
    # resumable rather than a restart.
    youtube_upload_retries: int = Field(default=4,
                                        alias="YOUTUBE_UPLOAD_RETRIES")
    # The language YouTube is told the uploaded .srt is in (E7).
    captions_language: str = Field(default="en", alias="CAPTIONS_LANGUAGE")
    publish_timezone: str = Field(default="Europe/Bucharest",
                                  alias="PUBLISH_TIMEZONE")
    publish_hour: int = Field(default=17, alias="PUBLISH_HOUR")
    publish_minute: int = Field(default=0, alias="PUBLISH_MINUTE")
    gdrive_credentials: str = Field(default="", alias="GDRIVE_CREDENTIALS")    # path to service-account/OAuth JSON
    gdrive_root_folder_id: str = Field(default="", alias="GDRIVE_ROOT_FOLDER_ID")
    gdrive_folder_name: str = "Dennis"
    # Make the uploaded final readable by anyone with the link (E4). OFF:
    # this used to be applied unconditionally, so every final render of an
    # unpublished video sat on a public URL — the same exposure the README's
    # "never public from a machine" row exists to prevent, through a
    # different door. Off, the link still works for whoever the Drive account
    # already shares the folder with.
    gdrive_link_anyone: bool = Field(default=False, alias="GDRIVE_LINK_ANYONE")
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
    screen_allow_list: Annotated[list[str], NoDecode] = Field(default_factory=list)
    screen_deny_list: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # -------------------------------------------------------------- editorial
    disclaimer_text: str = Field(
        default="Opinion / entertainment. Not financial advice.",
        alias="DISCLAIMER_TEXT",
    )
    # brand copy burned into the intro/outro bug — never the data vendor
    brand_name: str = "DENNIS"
    brand_tagline: str = "NOISE OR SIGNAL?"
    # the handle the signature close card signs off with
    brand_handle: str = Field(default="@dennisreads", alias="BRAND_HANDLE")

    # `SHORT_OPEN_STYLE`, `SHORT_OPEN_BUG_S` and `assets/hook_bank.json`
    # lived here and nothing read any of them (found by the new
    # `tests/test_asset_reach.py`, which is what J8 is for).
    #
    # They described the SHORT's signature open — a corner bug, a sampled
    # opener line, a length to hold it for — and the SHORT's open is now
    # whatever `templates/shots/short.json` puts in its `hook` shot. The
    # README described all three as live and tunable against retention data,
    # which is the same shape as `assets/brand/`: an instrument documented,
    # trusted, and wired to nothing.

    # ------------------------------------------------------------ mock timing
    # Deterministic mock TTS pacing (words per second) so rendered fixtures
    # have realistic durations without any paid call.
    mock_wps_short: float = 2.7
    mock_wps_long: float = 2.3

    # ------------------------------------------------------------- validators
    @field_validator("operator_chat_ids", "screen_allow_list", "screen_deny_list",
                     mode="before")
    @classmethod
    def _split_csv(cls, v):
        """Accept a JSON array OR a plain comma-separated list.

        `NoDecode` above turns off pydantic-settings' automatic JSON parsing
        for these three, so this validator sees the raw environment string.
        That matters: with JSON parsing on, `OPERATOR_CHAT_IDS=1569716319`
        decoded to an int and blew up with "Input should be a valid list" —
        a pydantic traceback in answer to the single most obvious thing to
        type. Both forms work now, and .env.example documents the JSON one.
        """
        if isinstance(v, str):
            s = v.strip()
            if s.startswith("[") or s.startswith("{"):
                try:
                    return json.loads(s)
                except ValueError:
                    pass  # fall through to CSV; the field error will be clearer
            v = [item.strip().strip("\"'") for item in s.split(",") if item.strip()]
        return v

    @field_validator("usd_per_1k_chars", mode="before")
    @classmethod
    def _blank_rate_means_derive(cls, v):
        """`USD_PER_1K_CHARS=` in a .env is "use the model's price", not a
        crash.

        A blank key in a .env file arrives as the empty string, and float
        validation rejects it — so an operator clearing a rate they no longer
        want to pin would get a pydantic traceback at startup instead of the
        default they were asking for. .env.example ships this key blank.
        """
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @field_validator("delivery_backend")
    @classmethod
    def _check_backend(cls, v: str) -> str:
        allowed = {"gdrive", "s3", "telegram", "local"}
        v = v.lower()
        if v not in allowed:
            raise ValueError(f"DELIVERY_BACKEND must be one of {sorted(allowed)}")
        return v

    # ------------------------------------------------------------------ mocks
    @property
    def mocking_tts(self) -> bool:
        return self.mock_mode if self.mock_tts is None else self.mock_tts

    @property
    def mocking_prices(self) -> bool:
        return self.mock_mode if self.mock_prices is None else self.mock_prices

    @property
    def mocking_screener(self) -> bool:
        return self.mock_mode if self.mock_screener is None else self.mock_screener

    def active_mocks(self) -> list[str]:
        """Which subsystems are producing invented data, right now.

        Everything that shows a result to the operator reads this: startup,
        `/status`, the digest and the validation report. A number nobody
        labelled as fake is a number somebody will act on.
        """
        return [name for name, on in (
            ("TTS", self.mocking_tts),
            ("PRICES", self.mocking_prices),
            ("SCREENER", self.mocking_screener),
        ) if on]

    def mock_banner(self, *, prefix: str = "") -> str:
        """One loud line naming the fake subsystems, or "" when all are live."""
        active = self.active_mocks()
        if not active:
            return ""
        return (f"{prefix}⚠️ MOCK DATA — {' + '.join(active)} "
                f"{'are' if len(active) > 1 else 'is'} invented, not real. "
                f"Nothing here is a market observation.")

    def deployment_warnings(self) -> list[str]:
        """Things about THIS deployment that quietly make videos worse.

        Not errors — nothing here refuses to boot, and none of it blocks a
        render. Each one costs a feature or a fallback that the operator
        would otherwise discover from the output weeks later, which is the
        same shape as every defect the provenance record exists to reveal.

        Said at startup, beside the mock banner, at the same moment: these
        are facts about the box, so the moment the box starts is when they
        are true and cheap to act on.
        """
        out: list[str] = []
        if not self.mock_mode and not self.sec_user_agent.strip():
            # The SEC requires a real name and email in the User-Agent and
            # rate-limits or 403s generic ones. Every caller falls back to a
            # literal and every SEC-backed feature degrades SILENTLY by
            # design — the filing brief, the 8-K news source and
            # [SHOW FILING] screenshots all return nothing rather than
            # raising. So three features go missing and nothing says why.
            out.append(
                "SEC_USER_AGENT is empty — SEC EDGAR requires a real name "
                "and email and rate-limits or 403s generic agents. The "
                "filing brief, the 8-K news source and [SHOW FILING] "
                "screenshots will degrade to nothing, quietly and by "
                "design. Set SEC_USER_AGENT='Your Name your@email'.")
        if self.broll_library_size() == 0:
            # THE OWNED LIBRARY IS THE FIRST LINK IN THE VISUAL CHAIN, and
            # the whole of H3's mitigation. Design: owned library → stock
            # footage → GIF providers. With nothing owned, EVERY clip goes
            # to Pexels and every Pexels miss goes to Giphy or Tenor — the
            # most legally exposed surface in the pipeline, on
            # user-uploaded and frequently copyrighted content. The GIF path
            # will fire far more often than the design assumes, from the
            # first video, and the cap is a ceiling rather than a plan.
            out.append(
                f"assets/broll_library/ is empty — the owned-first visual "
                f"chain has nothing to be first. Every [CLIP] will reach "
                f"for Pexels, and every Pexels miss for Giphy/Tenor, which "
                f"is the most legally exposed source in the pipeline. "
                f"GIF_MAX_PER_VIDEO={self.gif_max_per_video} caps it; it "
                f"does not replace owning clips.")
        return out

    def broll_library_size(self) -> int:
        """How many owned clips this deployment actually has."""
        lib = self.assets_dir / "broll_library"
        if not lib.is_dir():
            return 0
        return sum(1 for f in lib.iterdir()
                   if f.suffix.lower() in (".mp4", ".mov", ".mkv", ".webm"))

    # ------------------------------------------------------------ conveniences
    @property
    def short_resolution(self) -> tuple[int, int]:
        return (self.short_width, self.short_height)

    @property
    def long_resolution(self) -> tuple[int, int]:
        return (self.long_width, self.long_height)

    @property
    def active_eleven_model(self) -> str:
        """The model id every paid call and every price uses.

        ELEVEN_MODEL_ID wins when it names anything, because it is the setting
        that can name ANY model. ELEVEN_USE_PREMIUM is the deprecated path and
        still decides between exactly the two ids it always decided between,
        so an .env written before this change does what it always did.

        "Was it set?" is answered by an empty default rather than by
        model_fields_set, which is not the same question: pydantic-settings
        records a field as set when it arrives by env var or by field name, but
        not when it arrives as an alias keyword, and a resolution rule that
        depends on which of three equivalent spellings the caller used is a
        rule that will be wrong somewhere.
        """
        if self.eleven_model_id:
            return self.eleven_model_id
        if self.eleven_use_premium:
            return self.eleven_premium_model_id
        return self.eleven_default_model_id

    @property
    def tts_usd_per_1k_chars(self) -> float:
        """What a thousand characters actually costs, for the selected model.

        Derived rather than configured. A single hardcoded number cannot stay
        true across models at different prices, and the one that was here was
        true of none of them - which mattered because the spend cap is metered
        with it, not just the approval screen.

        An unknown model RAISES. It used to bill at the dearest known rate on
        the reasoning that guessing high is the safe direction - but a guess is
        still a guess, and the guess that actually shipped was in the other
        direction and would have let a $50 cap through about $100 of spend.
        A missing entry and a wrong one look identical at runtime; only one of
        them announces itself.
        """
        if self.usd_per_1k_chars is not None:
            return self.usd_per_1k_chars
        model = self.active_eleven_model
        try:
            return ELEVEN_USD_PER_1K_CHARS[model]
        except KeyError:
            raise UnknownModelPriceError(
                f"No list price for ELEVEN_MODEL_ID={model!r}, so the monthly "
                f"spend cap cannot be metered and nothing here will guess at "
                f"one.\n\n"
                f"Priced models: "
                f"{', '.join(sorted(ELEVEN_USD_PER_1K_CHARS))}\n\n"
                f"Note that the lookup is EXACT: eleven_v3_conversational is a "
                f"different model from eleven_v3 at half the price, so a name "
                f"that merely starts with a known one is not the same model.\n\n"
                f"Either add {model!r} to ELEVEN_USD_PER_1K_CHARS in config.py "
                f"with its real rate, or set USD_PER_1K_CHARS in .env to the "
                f"USD-per-1,000-characters this model actually bills."
            ) from None

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

    # ------------------------------------------------- WSL filesystem check
    # Under WSL2 a path beginning /mnt/ is a Windows drive reached through the
    # 9p/drvfs translation layer. It works, but per-file overhead is an order
    # of magnitude worse than the Linux filesystem, and the render cache is
    # the worst possible shape for it: `cache/segments` holds thousands of
    # small clips that are stat'd on every render to decide what to reuse.
    # The cost lands exactly on the operation that is supposed to make a
    # re-render fast.
    #
    # These are the three that matter. `assets_dir`, `templates_dir` and
    # `fixtures_dir` sit next to the code and are read a handful of times per
    # run; workspace/cache/state are written continuously.
    RUNTIME_DIR_ATTRS: ClassVar[tuple[str, ...]] = (
        "workspace_dir", "cache_dir", "state_dir")

    def windows_drive_dirs(self) -> list[tuple[str, Path]]:
        """Runtime dirs that resolve onto a Windows drive under WSL.

        Resolved, not just prefix-matched, so a symlink into /mnt/c is caught
        as well — that is the realistic way this happens by accident.
        """
        found: list[tuple[str, Path]] = []
        for attr in self.RUNTIME_DIR_ATTRS:
            path = Path(getattr(self, attr))
            try:
                resolved = path.resolve()
            except OSError:
                resolved = path.absolute()
            if resolved == Path("/mnt") or Path("/mnt") in resolved.parents:
                found.append((attr, resolved))
        return found

    def warn_about_windows_drives(self, logger: logging.Logger) -> list[str]:
        """Log a warning for each runtime dir on a Windows drive.

        Returns the offending setting names so a caller can surface them
        somewhere more visible than the log if it wants to.
        """
        offenders = self.windows_drive_dirs()
        for attr, resolved in offenders:
            env_name = attr.upper()
            logger.warning(
                "%s resolves to %s, which is a Windows drive. The render "
                "cache writes thousands of small files and every one crosses "
                "the WSL translation layer — expect renders to crawl. Move it "
                "onto the Linux filesystem and set %s (e.g. ~/dennis/%s).",
                attr, resolved, env_name, attr.removesuffix("_dir"))
        return [attr for attr, _ in offenders]

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


# One correct example per setting that is easy to get wrong. Keyed by the env
# var name, because that is what the operator typed.
_SETTING_EXAMPLES: dict[str, str] = {
    "OPERATOR_CHAT_IDS": 'OPERATOR_CHAT_IDS=["123456789"]   (or: 123456789)',
    "SCREEN_ALLOW_LIST": 'SCREEN_ALLOW_LIST=["AAPL","MSFT"]   (or: AAPL,MSFT)',
    "SCREEN_DENY_LIST": 'SCREEN_DENY_LIST=["GME"]   (or: GME)',
    "MOCK_MODE": "MOCK_MODE=true      (true | false)",
    "MOCK_TTS": "MOCK_TTS=true       (true | false; unset follows MOCK_MODE)",
    "MOCK_PRICES": "MOCK_PRICES=false   (true | false; unset follows MOCK_MODE)",
    "MOCK_SCREENER": "MOCK_SCREENER=false (true | false; unset follows MOCK_MODE)",
    "DELIVERY_BACKEND": "DELIVERY_BACKEND=gdrive   (gdrive | s3 | telegram | local)",
    "MONTHLY_SPEND_CAP": "MONTHLY_SPEND_CAP=50.0",
    "SHORT_MAX_CHARS": "SHORT_MAX_CHARS=1400",
    "LONG_MAX_CHARS": "LONG_MAX_CHARS=36000",
    "OPERATOR_CHAT_ID": 'OPERATOR_CHAT_IDS=["123456789"]   (note the S)',
    # The SEC refuses a generic agent, so a placeholder here is worse than
    # nothing: it looks set and behaves as if it is not.
    "SEC_USER_AGENT": "SEC_USER_AGENT=Your Name your@email",
}


class ConfigError(SystemExit):
    """A settings problem, stated the way the operator can act on it."""


def _env_key(loc: tuple) -> str:
    """The environment variable name behind a pydantic error location."""
    return str(loc[0]).upper() if loc else "(unknown)"


def describe_config_error(err: ValidationError, env_file: Path) -> str:
    """Turn a pydantic ValidationError into a message naming file, key,
    problem and a correct example.

    The default is a stack trace ending in "Input should be a valid list",
    printed at startup with no indication of which file it came from, which
    key was wrong, or what the right shape looks like. Every one of those four
    facts is available here; none of them were being shown.
    """
    lines = [
        "Configuration error — the bot did not start.",
        f"  file: {env_file if env_file.exists() else str(env_file) + ' (not found)'}",
        "",
    ]
    for e in err.errors():
        key = _env_key(e.get("loc", ()))
        given = e.get("input")
        lines.append(f"  key: {key}")
        lines.append(f"  problem: {e.get('msg', 'invalid value')}")
        if given is not None and not isinstance(given, dict):
            lines.append(f"  you set: {given!r}")
        example = _SETTING_EXAMPLES.get(key)
        if example:
            lines.append(f"  correct: {example}")
        lines.append("")
    lines.append("Edit the file above and start again. .env.example carries a "
                 "correct value for every key.")
    return "\n".join(lines)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as err:
        raise ConfigError(
            describe_config_error(err, BASE_DIR / ".env")) from err
