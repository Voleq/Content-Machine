# Due Diligence Desk

Telegram-controlled, human-in-the-loop video pipeline that renders
financial-analysis videos in two formats:

- **SHORT** — 9:16 vertical, ~55–60s "forensic audit" of a stock. Dark
  mahogany desk, case-file folder, typewriter data block, marker
  highlight, verdict stamp.
- **LONG** — 16:9 horizontal deadpan deep-dive with ironic B-roll jump
  cuts, full-screen Refinitiv "raw reality" flashes, music bed.

The operator supplies the judgment (numbers, thesis, approval); the
machine does 100% of voice, asset fetching, composition and rendering.
**Every visual cue is positioned by real audio timestamps** — there are
no hardcoded scene timings anywhere in the render code.

```
/new MSTR → upload data_refinitiv.xlsx → run the pre-filled master prompt
in Claude/GPT → paste the output back → validation + cost report →
Approve ✅ → /render MSTR → shareable Drive link
```

---

## Hard guarantees (enforced in code, not by discipline)

| Rule | Where |
|---|---|
| `MOCK_MODE=true` by default; no paid/live API during dev & tests | `config.py`, mock TTS/Pexels/delivery, pytest network guard |
| One paid TTS per approved script; unchanged content ⇒ **zero** calls | `pipeline/tts.py` sha256(voice·model·settings·text) cache |
| Character budgets (`SHORT_MAX_CHARS=800`, `LONG_MAX_CHARS=22000`) rejected **before** any spend | parsers + `TTSEngine` |
| Nothing paid before the operator taps **Approve** on the cost report | `bot/handlers.py` approval gate; approvals pin the script sha |
| Monthly cap (`MONTHLY_SPEND_CAP=50`) blocks paid calls in code | `pipeline/cost.py` SpendLedger, checked inside `TTSEngine` |
| One final render per approved ticker; draft = same cached audio, low-res | job queue + `/draft`; no variant generation exists |
| B-roll: owned library → cache → Pexels (rate-capped) → filler; a missing clip **never** aborts a render | `pipeline/broll.py` |
| Audio timestamps are the master clock (`ffprobe` + ElevenLabs alignment) | `pipeline/timeline.py` (pure, exhaustively tested) |
| Screener is data-only, never spends, degrades gracefully | `pipeline/screener.py` |

---

## Repository map

```
config.py                typed settings (pydantic-settings) — every cap/knob
main.py                  bot entrypoint
pipeline/
  models.py              data contracts: ShortScript (strict JSON), LongScript,
                         Verdict taxonomy (5 scathing + 5 laudatory), Refinitiv
                         schema, CostReport, JobRecord, Candidate
  parser_short.py        tolerant JSON extraction -> strict validation
  parser_long.py         offset-aware tag tokenizer ([B-ROLL:…] etc.)
  tts.py                 ElevenLabs with-timestamps client + cache + budgets
  timeline.py            THE MASTER CLOCK: anchors/offsets -> cue times,
                         jump-cut segment planner
  rasters.py             Pillow text/stamp/animation frames + ASS karaoke
  render_common.py       ffmpeg wrappers, encode profiles, compositing engine
  render_short.py        9:16 scene engine (one filtergraph, one encode)
  render_long.py         16:9 jump-cut concat engine (draft + final)
  broll.py               vetted 52-key palette, local-first resolution chain
  refinitiv.py           Excel-add-in export reader + screenshot normalizer
  cost.py                spend ledger, gates, §9.3 report builders
  jobs.py                persisted async job queue (one render at a time)
  delivery.py            gdrive (default) / s3 / telegram / local
  repurpose.py           best ~58s of a LONG -> 9:16 SHORT (free)
  thumbnail.py           auto YouTube thumbnail
  screener.py            Yahoo + StockTwits candidate lanes + digest
  cleanup.py             RETENTION_DAYS disk hygiene (keeps caches)
  workspace.py           per-ticker/date dirs, approvals, chat context
bot/
  handlers.py            BotCore (all logic, Telegram-free) + PTB glue
  prompts.py             master-prompt placeholder filling
  keyboards.py           Approve / Swap clip / Cancel, candidate buttons
assets/                  fonts, stamps, backgrounds, overlays, sfx, music,
                         broll_library/ (drop your owned clips here)
templates/               master prompts (§Appendix A) + refinitiv_audit_template.xlsx
fixtures/                mock scripts / Pexels / TTS alignment / screener JSON
samples/                 sample SHORT + LONG MP4s rendered from fixtures
deploy/                  systemd units + cleanup timer + bootstrap.sh
scripts/                 gen_assets.py, gen_fixtures.py, render_samples.py
workspace|cache|state/   runtime (gitignored)
```

---

## Setup

### Local (development)

```bash
sudo apt install ffmpeg fonts-dejavu-core   # FFmpeg 6+
python3.11 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/python scripts/gen_assets.py      # deterministic brand assets
.venv/bin/python -m pytest tests/           # offline, zero network calls
.venv/bin/python scripts/render_samples.py  # sample MP4s from fixtures
```

### VPS (production)

```bash
sudo bash deploy/bootstrap.sh /opt/due-diligence-desk
sudo nano /opt/due-diligence-desk/.env      # token + operator chat id
sudo systemctl enable --now due-diligence-desk
```

The bootstrap installs apt deps, builds the venv from the **pinned**
`pyproject.toml`, generates assets, runs the offline suite, and installs
the service + daily cleanup timer. No display server, no ImageMagick.

### Going live (spending real money)

1. Leave `MOCK_MODE=true` until a full mock run works end-to-end in your
   chat.
2. Set `ELEVENLABS_API_KEY`, `ELEVEN_VOICE_ID_SHORT/LONG`,
   `PEXELS_API_KEY`, `GDRIVE_CREDENTIALS` (service-account JSON path) and
   `GDRIVE_ROOT_FOLDER_ID` (share the folder with the service account).
3. Flip `MOCK_MODE=false`, restart, `/cost` to confirm the cap.

---

## Operator flow (one video, start to finish)

1. `/screen` (or the pre-market digest) → tap a candidate, or `/new TICKER`.
2. Refresh `templates/refinitiv_audit_template.xlsx` for the ticker in
   Excel (Refinitiv/LSEG add-in), upload it here. Optionally upload raw
   Refinitiv screenshot PNGs (referenced by `[SHOW REFINITIV: file.png]`).
3. The bot replies with both **pre-filled master prompts** — run one in
   Claude/GPT, paste the model's output back (message or .txt).
4. Read the **validation + cost report** (chars, $ estimate, cache hits,
   B-roll sources + contact sheet, blockers, month-to-date spend).
   `Swap clip 🔄` rotates any B-roll pick. Approve ✅ arms the render.
5. `/render TICKER` (SHORT) or `/render_long TICKER` — for LONG,
   `/draft TICKER` first gives a half-res timing check that reuses the
   same audio. Progress and failures arrive as messages.
6. Delivery: Google Drive link (default) posted in chat with attribution;
   `/repurpose TICKER` afterwards cuts the best ~58s of the LONG into a
   free vertical SHORT.
7. `/status`, `/cancel TICKER`, `/cost` any time.

### The data contract (Refinitiv, no API)

`templates/refinitiv_audit_template.xlsx` has one fixed sheet (`Audit`)
with `field | value | group` columns — the operator's live copy holds
Refinitiv Excel-add-in formulas in the value column. The reader matches
**field names only** (never cell positions). Missing
identity/size/margins/cash fields **block** the run; other gaps warn.
CSV (`field,value`) is accepted too.

---

## Configuration reference (env / .env)

| Var | Default | Meaning |
|---|---|---|
| `MOCK_MODE` | `true` | mock all paid APIs + local delivery |
| `TELEGRAM_BOT_TOKEN` | — | from @BotFather (free; required even in mock) |
| `OPERATOR_CHAT_IDS` | — | comma-separated allow-list; empty denies all |
| `SHORT_MAX_CHARS` / `LONG_MAX_CHARS` | 800 / 22000 | TTS budgets, rejected pre-spend |
| `USD_PER_1K_CHARS` | 0.15 | TTS cost estimate for reports |
| `MONTHLY_SPEND_CAP` | 50.0 | hard code-level gate |
| `ELEVEN_USE_PREMIUM` | false | turbo tier by default (§8.5) |
| `DELIVERY_BACKEND` | gdrive | gdrive · s3 · telegram · local |
| `GDRIVE_CREDENTIALS` / `GDRIVE_ROOT_FOLDER_ID` | — | Drive delivery |
| `RETENTION_DAYS` | 14 | cleanup horizon (caches never pruned) |
| `SCREEN_TOP_N` / `COOLDOWN_DAYS` | 8 / 30 | screener caps |
| `SCREEN_DIGEST_CRON` | `30 7 * * 1-5` | digest, `SCREEN_TIMEZONE` (ET) |
| `DISCLAIMER_TEXT` | Opinion / entertainment… | burned into every frame (§11) |

Full list with encode/voice/pexels knobs: `config.py` (every field is an
env var, case-insensitive).

---

## Defaults & deviations (decisions the build made for you)

- **No MoviePy, no ImageMagick.** Whip-pan, stamp impact, typewriter and
  highlight sweep are generated as small Pillow RGBA frame sequences,
  encoded once into alpha `.mov` clips, and composited by FFmpeg. Same
  look, two fewer fragile dependencies on a headless VPS. MoviePy remains
  available as an optional extra (`pip install -e '.[moviepy]'`) if you
  want to experiment.
- **Captions are libass karaoke** (`subtitles` filter) generated from the
  word timestamps — one filter instead of hundreds of overlays. LONG
  captions are authored narrow (≤ ~22 chars/line) so the 9:16 repurpose
  crop keeps them intact.
- **Mock TTS** synthesizes a low hum at a deterministic words-per-second
  rate (2.7 SHORT / 2.3 LONG) with linear word timestamps, so mock
  renders have realistic pacing and the full timeline logic is exercised.
- **Placeholder sfx/music/backgrounds/stamps are generated procedurally**
  (`scripts/gen_assets.py`, seeded). Replace `assets/sfx`, `assets/music`
  and drop owned clips into `assets/broll_library/` for production polish;
  everything is normalized on ingest.
- **Draft renders sit behind the same approval gate in live mode** — the
  first LONG render (draft or final) is what triggers the single paid TTS
  call; after that, drafts and re-renders are free from cache.
- **`/repurpose` needs no approval** — it cuts the already-rendered LONG;
  zero new spend by construction.
- **Fixture LONG script is ~250 words** so the committed sample renders in
  ~1 minute; the engine itself is length-agnostic (budget 22k chars).
- **yfinance/yahooquery/StockTwits are unofficial** — every call is
  wrapped, cached, rate-limited and allowed to fail into a labelled,
  degraded lane. The screener can never block or spend.
- Repo layout matches the build spec with two small additions:
  `pipeline/rasters.py` (Pillow/ASS helpers) and `pipeline/workspace.py`
  (state), both documented above.

## Legal / safety (§11)

A persistent "Opinion / entertainment. Not financial advice." overlay is
burned into both formats (`DISCLAIMER_TEXT`), the LONG carries a
`TICKER · audit as of DATE` corner bug, and the master prompts require
every claim to stay tied to the on-screen Refinitiv figures. The verdict
taxonomy cuts both ways by design — the data picks the polarity, the
model never manufactures doom (or hype).

## Testing

```bash
.venv/bin/python -m pytest tests/    # ~130 tests, fully offline
```

A conftest guard fails any test that opens a non-localhost socket. The
renderer smoke tests produce real MP4s (reduced resolution) from mock
audio and then assert the cue times that reached the actual FFmpeg
filtergraph match the timeline — the "no hardcoded timings" invariant is
executable.

Sample artifacts (committed): `samples/sample_short_EXMPL.mp4` (44s,
1080×1920) and `samples/sample_long_EXMPL.mp4` (106s, 1920×1080), both
rendered from `fixtures/` with `MOCK_MODE=true` and zero network calls:

```bash
.venv/bin/python scripts/render_samples.py all
```

## Troubleshooting

- **`ffmpeg/ffprobe not found`** — `apt install ffmpeg` (6+ required).
- **Bot replies "Not authorized"** — it prints the chat id to add to
  `OPERATOR_CHAT_IDS`.
- **"over the SHORT budget"** — the script is > `SHORT_MAX_CHARS`; trim
  and re-paste. Nothing was spent.
- **Report says BLOCKED: screenshot not found** — upload the exact
  filename the script references, or remove the tag. Renders never start
  with missing assets (§2.3).
- **Drive upload fails** — share the target folder with the service
  account email; check `GDRIVE_ROOT_FOLDER_ID`.
- **Renders feel slow on a small VPS** — lower `LONG_WIDTH/HEIGHT` to
  1280×720, keep `FINAL_PRESET=veryfast`; hardware encoders are used
  automatically when detected.
