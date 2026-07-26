# Dennis

Telegram-controlled, human-in-the-loop video pipeline that renders
financial videos hosted by **Dennis** — a smart, dry, deadpan, burnt-out
everyman who reads 10-Ks at 3am because the void won't let him sleep.
Funny on purpose (never merely bored), a disappointed realist rather than
a hater.
Two formats:

- **SHORT** — 9:16 vertical, ~60–75s **"Noise or signal?"** on a trending
  stock. Branded price chart rendered by the pipeline from its own price
  data (never a screenshot), driver headlines overlaid on the chart, a
  multi-year numbers sheet, hand-drawn scribbles, a deadpan free-text
  payoff. No verdict, no stamp — the viewer draws the conclusion.
- **LONG** — 16:9 deadpan deep-dive on a beaten-down value-lane stock
  (never the trending names): real operations imagery, auto-generated
  charts, unnamed-source filing flashes auto-pulled from the 10-K (SEC
  EDGAR → smoking-gun quotes → headless-Chromium screenshots, no manual
  uploads), at most 1–2 memes from the owned library, fast ~1.5–3s cuts,
  resigned close.

The operator supplies the judgment (numbers, thesis, approval); the
machine does 100% of voice, asset fetching, composition and rendering.
**Every visual cue is positioned by real audio timestamps** — there are
no hardcoded scene timings anywhere in the render code.

```
/short TICKER  (or /long TICKER) → the bot refreshes the numbers in Excel
itself → run the pre-filled master prompt in Claude/GPT → paste the output
back → validation + cost report → tweak in chat if needed → Approve ✅ →
/render TICKER → shareable link
```

(Off the Windows render box, or with no data add-in loaded, step two is the
manual upload it always was — `dennis_data.xlsx` into the chat.)

---

## Hard guarantees (enforced in code, not by discipline)

| Rule | Where |
|---|---|
| `MOCK_MODE=true` by default; no paid/live API during dev & tests | `config.py`, mock TTS/Pexels/images/memes/prices/delivery, pytest network guard |
| One paid TTS per approved script; unchanged content ⇒ **zero** calls | `pipeline/tts.py` sha256(voice·model·settings·text) cache |
| Character budgets (`SHORT_MAX_CHARS=800`, `LONG_MAX_CHARS=22000`) rejected **before** any spend | parsers + `TTSEngine` |
| Nothing paid before the operator taps **Approve** on the cost report | `bot/handlers.py` approval gate; approvals pin the script sha |
| Monthly cap (`MONTHLY_SPEND_CAP=50`) blocks paid calls in code | `pipeline/cost.py` SpendLedger, checked inside `TTSEngine` |
| One final render per approved ticker | job queue + `/draft`; no variant generation exists |
| A `/draft` never spends: free local voice, else the mock hum — never ElevenLabs | `TTSEngine.tier_for`; the tier is part of the cache key |
| Draft audio can never become a final render (its word timings are interpolated) | `render_long` / `render_short` refuse `tts.draft` |
| Visuals: owned library → cache → fetch → filler; a missing item **never** aborts a render | `pipeline/broll.py` content engine, `pipeline/memes.py` |
| The data vendor is never named on screen — scripts are hard-rejected if they try | parsers' vendor block; filing overlays carry a generic "FROM THE 10-K" chip |
| `[ASSET]` tags **block** the render until the designed file exists | `validate_long_script` + `assets/custom/` |
| 1–2 memes max per LONG (information-first) | `validate_long_script` meme cap |
| Audio timestamps are the master clock (`ffprobe` + ElevenLabs alignment) | `pipeline/timeline.py` (pure, exhaustively tested) |
| Screener is data-only, never spends, degrades gracefully | `pipeline/screener.py` |

---

## Repository map

```
config.py                typed settings (pydantic-settings) — every cap/knob,
                         voice placeholder + audition shortlist
main.py                  bot entrypoint
pipeline/
  models.py              data contracts: ShortScript ("Noise or signal?"
                         strict JSON), LongScript + Dennis tag grammar,
                         CompanyData (latest + 5y history), CostReport,
                         JobRecord, Candidate — no verdict enum anywhere
  parser_short.py        tolerant JSON extraction + inline [DOODLE]/[SCRIBBLE]
  parser_long.py         offset-aware tag tokenizer + ASSET-prompt trailer
  tagging.py             the shared tag tokenizer (both formats) + chart style
  tts.py                 ElevenLabs with-timestamps client + cache + budgets
  timeline.py            THE MASTER CLOCK: beats/anchors -> cue times,
                         fast-cut segment planner, doodle/scribble overlays
  prices.py              Yahoo price history behind an interface (cached,
                         synthetic floor) — feeds the branded chart
  chart.py               branded price chart, crude "marker" napkin chart,
                         multi-year metric charts
  rasters.py             the SHORT kit: headline cards, numbers sheet,
                         scribbles, zoom-punch, stingers, karaoke captions,
                         doodle boil
  render_common.py       ffmpeg wrappers, encode profiles, compositing engine
  render_short.py        9:16 "Noise or signal?" template filler
  render_long.py         16:9 fast-cut concat engine (draft + final)
  broll.py               the content engine: [CLIP] Pexels palette,
                         [IMG]/[PRODUCT] Wikimedia + company site,
                         [MEME] owned library + fallbacks, [CHART] auto,
                         [SCREENGRAB]/[ASSET] custom files — cached, attributed
  memes.py               owned meme library (meme_index.json) + providers
  doodles.py             owned doodle library (doodles_index.json) + boil
  company_data.py        two-sheet Excel export reader + filing screenshots
  excel_refresh.py       drives Excel over COM to refresh the data itself
  local_tts.py           the free draft voice (Piper) + sentence-anchored timings
  standing.py            thesis book, ranked idea queue, overnight batch
  alerts.py              intraday watch: moves, volume, earnings, filings —
                         de-duplicated, quiet-hours aware, one-tap /short
  script_edit.py         in-chat revision: line/range edits, find-replace, undo
  cost.py                spend ledger, gates, report builders
  jobs.py                persisted async job queue (one render at a time)
  delivery.py            gdrive (default) / s3 / telegram / local
  repurpose.py           best ~58s of a LONG -> 9:16 SHORT (free)
  thumbnail.py           auto YouTube thumbnail (ticker + shock metric)
  screener.py            Yahoo + StockTwits lanes + digest + move context
  cleanup.py             RETENTION_DAYS disk hygiene (keeps caches)
  workspace.py           per-ticker/date dirs, approvals, chat context
bot/
  handlers.py            BotCore (all logic, Telegram-free) + PTB glue
  prompts.py             master-prompt placeholder filling + the kit catalog
                         generated from the manifest (never a hand-kept list)
  keyboards.py           Approve / Swap clip / Cancel, candidate buttons
assets/                  fonts, backgrounds, overlays, sfx, music,
                         hook_bank.json, meme_library/ (16 owned memes +
                         index), doodle_library — doodles/ (14 crude marker
                         overlays + index), broll_library/ (drop owned clips),
                         custom/ (Claude-Design [ASSET] + [SCREENGRAB] files)
templates/               master prompts + dennis_data_template.xlsx
fixtures/                mock scripts / Pexels / Wikimedia / TTS / prices /
                         screener JSON / company data
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
.venv/bin/python scripts/gen_assets.py      # deterministic placeholder kit
.venv/bin/python -m pytest tests/           # offline, zero network calls
.venv/bin/python scripts/render_samples.py  # sample MP4s from fixtures
```

### Windows 11 (the render desktop)

Runs **natively on Windows, not under WSL** — Playwright, FFmpeg and NVENC
all behave better outside the WSL boundary, and the GPU is directly
available.

```powershell
winget install Gyan.FFmpeg Python.Python.3.12   # then reopen the terminal
powershell -ExecutionPolicy Bypass -File deploy\bootstrap.ps1
notepad .env                                     # token + operator chat id
.venv\Scripts\python.exe main.py
```

`bootstrap.ps1` is the counterpart to `bootstrap.sh`: venv, pinned deps,
FFmpeg check, an NVENC heads-up, headless Chromium, `.env` scaffold,
generated assets, design-kit check, offline suite. It is idempotent.

To leave the bot up across reboots, register the logon task:

```powershell
powershell -ExecutionPolicy Bypass -File deploy\install-task.ps1
```

Task Scheduler rather than a service, deliberately: the task runs as the
logged-in user, so it inherits the normal PATH, environment and GPU.
Manual `python main.py` stays the default way to run it.

**Encode politeness.** This is somebody's daily-driver desktop and renders
are unattended, so FFmpeg is capped to about half the cores and its
processes run below normal priority — slower, but the machine stays usable.
Tune with `RENDER_THREAD_FRACTION`, `RENDER_THREADS` (0 = derive) and
`RENDER_BELOW_NORMAL_PRIORITY` in `.env`.

### VPS (production)

```bash
sudo bash deploy/bootstrap.sh /opt/dennis
sudo nano /opt/dennis/.env                  # token + operator chat id
sudo systemctl enable --now dennis
```

The bootstrap installs apt deps, builds the venv from the **pinned**
`pyproject.toml`, generates assets, runs the offline suite, and installs
the service + daily cleanup timer. No display server, no ImageMagick.
The Linux path stays supported — a weaker always-on box can host the bot
with the desktop acting as a render worker later.

### Going live (spending real money)

1. Leave `MOCK_MODE=true` until a full mock run works end-to-end in your
   chat.
2. Set `ELEVENLABS_API_KEY` and pick the Dennis voice —
   `ELEVEN_VOICE_ID_SHORT/LONG` are deliberate placeholders; audition
   Brian (dry/deadpan), Charlie (casual everyman) or George (weary/raspy)
   and paste one id. Set `PEXELS_API_KEY`, `GDRIVE_CREDENTIALS`
   (service-account JSON path) and `GDRIVE_ROOT_FOLDER_ID` (share the
   folder with the service account). `GIPHY_API_KEY`/`TENOR_API_KEY` are
   optional meme fallbacks — the owned library comes first anyway.
3. Flip `MOCK_MODE=false`, restart, `/cost` to confirm the cap.

---

## Operator flow (one video, start to finish)

1. `/screen` (or the pre-market digest) → tap a candidate, or name the lane
   yourself: **`/short TICKER`** or **`/long TICKER`**. One command prepares
   one prompt, and `/render` follows from the lane rather than being a second
   choice. Trending lane → SHORT; beaten-down value lane → LONG, and picking
   a trending name for a LONG gets a warning, not a refusal — the screener is
   a suggestion engine. The screener's move context is baked into the SHORT
   prompt automatically. (`/new` still works for one release, preparing both
   prompts as before.)
2. The numbers arrive on their own: `/new` copies
   `templates/dennis_data_template.xlsx`, sets the ticker in `Snapshot!C3`,
   fires the add-in's refresh, waits for it to genuinely finish, and files a
   dated copy in the workspace. `/refresh TICKER` re-pulls; a second argument
   pins a **RIC override** for good (`/refresh PLTR PLTR.O`) for the cases the
   template's own exchange lookup can't get right. Anywhere without Excel and
   a loaded add-in the bot says so and takes the manual upload instead — that
   path is unchanged. Optionally upload raw screenshot PNGs for
   `[SHOW FILING: file.png]` moments — they get a generic "FROM THE 10-K"
   label on screen.
3. The bot replies with the lane's **pre-filled master prompt** — run it in
   Claude/GPT, paste the model's output back (message or .txt). The prompt
   carries a **kit catalog generated from the manifest at fill time**: exactly
   which `[TERM]`, `[BIGNUM]`, `[TABLE]`, `[PROP]` and `[ALERT]` keys have
   artwork, the concept illustrations with a one-line "use when", the chapter
   kits, the host's poses and reactions — plus the expressivity tags and the
   pacing rules. Validation already rejects unknown keys; this stops them
   being invented, and because it is read off disk it cannot drift from what
   is shipped.
4. Read the **validation + cost report** (chars, $ estimate, cache hits,
   visual sources + contact sheet, meme count, blockers, month-to-date
   spend). If the LONG used `[ASSET: slug]` tags, the bot attaches each
   appended **Claude Design prompt as a paste-ready file** and BLOCKS the
   render until you paste it into Claude Design, export, and upload the
   PNG (bespoke visuals never come from an image-generation API).
   `Swap clip 🔄` rotates any `[CLIP]` pick. Approve ✅ arms the render.
5. Tweak it in chat, without going back to the model. `/script` prints the
   script numbered; `/edit 12 <new text>` replaces line 12 (`12-14` for a
   range, no text to delete it); `/replace four point seven => four point six`
   fixes a figure by its own words (`all:` for every occurrence); `/undo`
   steps back. **An edit that doesn't parse never lands** — the workspace
   keeps the script it had and you get the parser's complaint. Every revision
   that does land re-runs the gates, re-prices, and drops the approval, so
   nothing renders from a version nobody read. A full re-paste still works too.
6. `/render TICKER` (SHORT) or `/render_long TICKER` — for LONG,
   `/draft TICKER` first gives a half-res check for **free**: it uses the
   local neural voice (Piper) when the box has one, the mock hum otherwise,
   and never ElevenLabs. Draft audio is listenable but its word timings are
   exact per sentence and interpolated within one, so judge pacing and edit
   points, not lip-sync — and the renderer refuses to build a final from it.
   Progress and failures arrive as messages.
7. Delivery: Google Drive link (default) posted in chat with attribution
   (Pexels + Wikimedia credits written beside the file);
   `/repurpose TICKER` afterwards cuts the best two or three ~58s windows
   of the LONG into free vertical SHORTs (non-overlapping, best first).
8. `/status`, `/cancel TICKER`, `/cost` any time. `/ideas` is the ranked
   backlog (fed by every screen and by any thesis that moves), `/thesis
   TICKER` re-checks what you said against today's numbers, and `/batch`
   queues renders to run unattended overnight.

### The data contract (private, no API)

`templates/dennis_data_template.xlsx` has two fixed sheets read strictly
by **field name** (never cell positions):

- `Latest` — `field | value | group` rows; the operator's live copy holds
  Excel add-in formulas in the value column.
- `History` — row 1 = year labels (oldest → newest), one row per
  direction metric (revenue, margins, net income, FCF, share count,
  debt, cash). This is what makes the SHORT's multi-year gut check and
  the LONG's `[CHART: metric]` possible.

Missing identity/size/margins/cash fields **block** the run; other gaps
warn; a missing History sheet warns. CSV (`field,value`) is accepted for
the snapshot only. Nothing in scripts, tags, overlays or captions may
name the data vendor — the parsers reject it, and on screen the data is
"from the 10-K".

#### Refreshing it without touching Excel yourself

`pipeline/excel_refresh.py` drives Excel over COM on the render box.

Two input cells, and they mean different things. **`Snapshot!C3`** takes the
plain ticker and every `CIQ(...)` formula reads it. **`Snapshot!B3` derives**
the Refinitiv RIC from C3, looking the suffix up from the exchange via the
hidden `_RICMap` table — it is a formula and writing to it would silently
detach every green cell from the ticker. **`Snapshot!E2`** forces a RIC for
the cases the lookup can't know (a dual listing, a share class); leave it
empty and the template does the work, which is right more often than a guess.
`/refresh PLTR PLTR.O` pins E2 for that ticker permanently.

The step that matters is the wait: the add-in resolves **asynchronously**, so
the refresh call returns instantly while cells still read `#N/A` or
`Requesting Data...`. Reading at that moment produces a workbook full of
blanks that looks like a successful refresh — a video built on nothing. So the
refresh only counts as done when every field worth waiting for has resolved
*and* the sheet has stopped changing for `EXCEL_SETTLE_POLLS` consecutive
reads.

"Worth waiting for" is two tiers, because the template grades its own fields
in the `Priority` column and grades twelve as Required where `DATA_REQUIRED`
names six. The poll waits for all twelve — a stronger completion signal, so it
cannot stop while the valuation block is still filling in — but only the six
are hard: a thinly-covered small-cap missing `ev_ebitda` gets a warning and a
usable workbook, not a failed refresh.

Consequences, by design:

- A timeout, or a `DATA_REQUIRED` field still unresolved, is a **hard failure**
  with the fields and the symbol named. Nothing is written to
  `dennis_data.xlsx`; a workbook already in the workspace is left exactly as
  it was.
- Excel or the add-in missing is **reported**, not crashed on, and the manual
  upload takes over.
- The scratch copy is deleted and Excel is quit — and killed by PID if a
  modal dialog swallowed the quit — on every path, including failure.
- Freshness is measured from `data_refresh.json`'s recorded refresh time, not
  from the sheet's `=TODAY()` (which only says when it was last recalculated)
  and not from the file's mtime (which re-saving resets without changing a
  single number).

The add-in's refresh macro is named differently in every vintage, so
`EXCEL_REFRESH_MACROS` is a list of candidates tried in order, falling back to
a full recalculation — most add-in formulas are volatile, so that works too,
just less directly. Set the var once you know which macro your box has.

---

## Configuration reference (env / .env)

| Var | Default | Meaning |
|---|---|---|
| `MOCK_MODE` | `true` | mock all paid APIs + local delivery |
| `TELEGRAM_BOT_TOKEN` | — | from @BotFather (free; required even in mock) |
| `OPERATOR_CHAT_IDS` | — | comma-separated allow-list; empty denies all |
| `ELEVEN_VOICE_ID_SHORT/LONG` | — | **placeholder** — the Dennis voice is a one-line change (shortlist in `config.py`) |
| `SHORT_MAX_CHARS` / `LONG_MAX_CHARS` | 800 / 22000 | TTS budgets, rejected pre-spend |
| `USD_PER_1K_CHARS` | 0.15 | TTS cost estimate for reports |
| `MONTHLY_SPEND_CAP` | 50.0 | hard code-level gate |
| `ELEVEN_USE_PREMIUM` | false | Turbo tier by default (~half credit cost) |
| `GIPHY_API_KEY` / `TENOR_API_KEY` | — | optional [MEME] fallbacks (library first) |
| `DELIVERY_BACKEND` | gdrive | gdrive · s3 · telegram · local |
| `GDRIVE_CREDENTIALS` / `GDRIVE_ROOT_FOLDER_ID` | — | Drive delivery |
| `EXCEL_REFRESH_ENABLED` | true | let the bot refresh its own numbers (Windows + add-in) |
| `EXCEL_SYMBOL_SUFFIX` | — | `.O` builds `PLTR.O`; per-ticker pins beat it |
| `EXCEL_REFRESH_MACROS` | — | add-in refresh macro candidates; blank = try known ones |
| `EXCEL_REFRESH_TIMEOUT_S` | 240 | a timeout is a hard failure, never accepted as data |
| `LOCAL_TTS_ENABLED` / `LOCAL_TTS_MODEL` | true / — | free draft voice (Piper .onnx); drafts fall back to mock, never to paid |
| `RETENTION_DAYS` | 14 | cleanup horizon (caches never pruned) |
| `SCREEN_TOP_N` / `COOLDOWN_DAYS` | 8 / 30 | screener caps |
| `SCREEN_DIGEST_CRON` | `30 7 * * 1-5` | digest, `SCREEN_TIMEZONE` (ET) |
| `ALERTS_ENABLED` / `ALERT_POLL_MINUTES` | true / 15 | intraday watch on covered names |
| `ALERT_MOVE_PCT` / `ALERT_COOLDOWN_MINUTES` | 6.0 / 180 | when it speaks, and how rarely it repeats |
| `DISCLAIMER_TEXT` | Opinion / entertainment… | burned into every frame |

Full list with encode/voice/pacing knobs: `config.py` (every field is an
env var, case-insensitive).

---

## Defaults & deviations (decisions the build made for you)

- **No MoviePy, no ImageMagick.** Row type-ons, scribbles, zoom-punches
  and flash stingers are generated as small Pillow RGBA frame sequences,
  encoded once into alpha `.mov` clips, and composited by FFmpeg. MoviePy
  remains available as an optional extra (`pip install -e '.[moviepy]'`).
- **The branded chart is rendered by the pipeline** from the same Yahoo
  feed the screener uses (cached, TTL'd, synthetic deterministic floor if
  the feed dies) — never a TradingView screenshot. Two styles: the clean
  branded card and a crude hand-drawn "marker" napkin chart on black;
  a SHORT picks via `chart_style`, a LONG via `[CHART: metric style=marker]`.
- **Hand-drawn overlay language**: `[DOODLE: key]` drops a crude marker
  overlay (stick-figure reactions, arrows, a scribble explosion — 14 in
  `assets/doodles/`, indexed like the memes, resolved locally, given a
  frame-to-frame "boil"); `[SCRIBBLE: circle|arrow|underline -> target]`
  draws a mark plus a target callout on a number/point. Both parse in the
  SHORT (inline in `audio_script`, stripped before TTS) and the LONG, and
  composite as the TOP layer over charts, screenshots and b-roll.
- **Screen-grab backbone**: `[SCREENGRAB: slug]` composites an operator-
  supplied capture (a broker app, a portfolio P&L, a Google search) —
  image or short screen-record dropped into `assets/custom/`, pad-fit
  (never cover-cropped). Same missing-file block as `[ASSET]`; the bot
  routes a matching-slug upload straight into `custom/`.
- **Captions are libass karaoke** (`subtitles` filter) generated from the
  word timestamps — words punch in as they are spoken. LONG captions are
  authored narrow (≤ ~22 chars/line) so the 9:16 repurpose crop keeps
  them intact.
- **Hook bank**: `assets/hook_bank.json` openers are sampled per render
  (seeded by the script sha — idempotent re-renders, fresh openers across
  videos).
- **Owned meme library first**: `assets/meme_library/meme_index.json`
  maps 16 descriptively-named memes to tags + a one-line "use when";
  `[MEME: key]` matches by stem or tag. Giphy/Tenor/imgflip are only
  consulted on a miss, and only when configured.
- **Mock TTS** synthesizes a low hum at a deterministic words-per-second
  rate (2.7 SHORT / 2.3 LONG) with linear word timestamps, so mock
  renders have realistic pacing and the full timeline logic is exercised.
- **Placeholder kit assets are generated procedurally**
  (`scripts/gen_assets.py`, seeded — including the 14 crude marker doodles
  drawn with wobbly Pillow strokes). Replace `assets/sfx`, `assets/music`,
  the backgrounds, and the meme + doodle placeholders with the
  Claude-Design / licensed kit for production polish; everything is
  normalized on ingest.
- **Draft renders sit behind the same approval gate in live mode** — the
  first LONG render (draft or final) is what triggers the single paid TTS
  call; after that, drafts and re-renders are free from cache.
- **`/repurpose` needs no approval** — it cuts the already-rendered LONG;
  zero new spend by construction.
- **Fixture LONG script is ~370 words** so the committed sample renders in
  ~1 minute; the engine itself is length-agnostic (budget 22k chars).
- **yfinance/yahooquery/StockTwits are unofficial** — every call is
  wrapped, cached, rate-limited and allowed to fail into a labelled,
  degraded lane. The screener can never block or spend.

## Legal / safety

A persistent "Opinion / entertainment. Not financial advice." overlay is
burned into both formats (`DISCLAIMER_TEXT`), the LONG carries a
`TICKER · as of DATE` corner bug, and the master prompts require every
claim to stay tied to the on-screen figures. The honesty cuts both ways
by design — the numbers pick the polarity, Dennis never manufactures
doom (or hype), and praise for a genuinely good business arrives through
gritted teeth rather than a stamp.

## Testing

```bash
.venv/bin/python -m pytest tests/    # ~190 tests, fully offline
```

A conftest guard fails any test that opens a non-localhost socket. The
renderer smoke tests produce real MP4s (reduced resolution) from mock
audio and then assert the cue times that reached the actual FFmpeg
filtergraph match the timeline — the "no hardcoded timings" invariant is
executable. Dedicated tests pin the deletion of the verdict system and
the desk scene, the vendor-name block, the meme cap, and the `[ASSET]`
blocking loop.

Sample artifacts (committed): `samples/sample_short_EXMPL.mp4`
(9:16 "Noise or signal?") and `samples/sample_long_EXMPL.mp4` (16:9
deep-dive), both rendered from `fixtures/` with `MOCK_MODE=true` and zero
network calls:

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
  with missing assets.
- **Report says BLOCKED: [ASSET: slug] has no file** — paste the attached
  Claude Design prompt into Claude Design, export the PNG, upload it in
  the chat (file name = slug) or drop it at `assets/custom/<slug>.png`.
- **"the data vendor's name appears"** — the model leaked the source into
  an on-screen field; regenerate or edit, then re-paste. On screen the
  data is "from the 10-K".
- **Drive upload fails** — share the target folder with the service
  account email; check `GDRIVE_ROOT_FOLDER_ID`.
- **Renders feel slow on a small VPS** — lower `LONG_WIDTH/HEIGHT` to
  1280×720, keep `FINAL_PRESET=veryfast`; hardware encoders are used
  automatically when detected.
